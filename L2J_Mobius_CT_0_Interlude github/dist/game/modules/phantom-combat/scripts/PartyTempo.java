/*
 * Copyright (c) 2013 L2jMobius
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
 * IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
package modules.phantomcombat;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Logger;

import org.l2jmobius.commons.threads.ThreadPool;
import org.l2jmobius.commons.util.Rnd;
import org.l2jmobius.gameserver.ai.Action;
import org.l2jmobius.gameserver.ai.Intention;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.PlayEntry;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Playstyle;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Use;
import org.l2jmobius.gameserver.managers.PhantomManager;
import org.l2jmobius.gameserver.managers.PhantomPartyManager;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine.CastAction;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine.PlayState;
import org.l2jmobius.gameserver.model.actor.Creature;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.instance.Monster;
import org.l2jmobius.gameserver.model.zone.ZoneId;

/**
 * Recruited DPS members don't idle between skills.
 * <ul>
 * <li><b>Follow-up</b>: the party manager decides once a second, and the playstyle engine then waits 1.6-2.5 s before
 * the next skill. When a DPS member starts a cast, the wait is cut to the configured gap and, as soon as the cast ends,
 * the next skill is picked with the same engine call the manager uses ({@code PhantomPlaystyleEngine.pick}) - or, for a
 * fighter with nothing ready, the swing the cast interrupted is relaunched. It only follows the manager's lead: it acts
 * on the target the member was already attacking, and stops the moment the member moves, sits, holds, or changes target.
 * Raid bosses and their minions are left entirely to the manager and its raid gates.</li>
 * <li><b>Burn phase</b>: on a mob that will die within a few seconds, setup skills (DEBUFF, CONTROL, OPENER) are dropped
 * from the member's playstyle so the casts go into damage.</li>
 * </ul>
 * The skill's own {@code paceMs} is applied by {@link SkillPacing} for every member this section paces.
 */
final class PartyTempo
{
	/** Window for the per-monster damage rate that time-to-kill is estimated from. */
	private static final long RATE_WINDOW_MS = 4000;
	/** How often the follow-up checks whether a running cast has ended. */
	private static final long CAST_POLL_MS = 100;
	/** A follow-up gives up waiting for a cast after this long (the manager's own watchdog handles stuck casts). */
	private static final long CAST_WAIT_MAX_MS = 8000;
	/** With nothing castable right now, the follow-up looks again after this long while the member stays engaged. */
	private static final long IDLE_POLL_MS = 300;

	private final PlaystyleAccess _access;
	private final Logger _log;
	private final boolean _followUpOn;
	private final boolean _burnOn;
	private final int _castGapMs;
	private final int _castGapJitterMs;
	private final long _engagedWindowMs;
	private final double _burnTtkSeconds;
	private final Set<String> _roles;
	private final boolean _debug;
	private volatile boolean _active = true;

	/** Member object id -> the monster it last attacked or cast on, and when. */
	private final Map<Integer, Engage> _engaged = new ConcurrentHashMap<>();
	/** Members with a follow-up scheduled; at most one each. */
	private final Set<Integer> _pending = ConcurrentHashMap.newKeySet();
	/** Monster object id -> recent damage taken, for time-to-kill. */
	private final Map<Integer, DamageRate> _rates = new ConcurrentHashMap<>();
	/** Full playstyle -> its burn variant; rebuilt when the playstyle data reloads. */
	private final Map<Playstyle, Playstyle> _burnVariants = new IdentityHashMap<>();
	private int _variantGeneration = Integer.MIN_VALUE;

	PartyTempo(PlaystyleAccess access, Logger log, boolean followUp, boolean burn, int castGapMs, int castGapJitterMs, long engagedWindowMs, double burnTtkSeconds, Set<String> roles, boolean debug)
	{
		_access = access;
		_log = log;
		_followUpOn = followUp;
		_burnOn = burn;
		_castGapMs = castGapMs;
		_castGapJitterMs = castGapJitterMs;
		_engagedWindowMs = engagedWindowMs;
		_burnTtkSeconds = burnTtkSeconds;
		_roles = roles;
		_debug = debug;
	}

	/** True when this section sets the member's casting pace (and so must also keep each skill's own paceMs). */
	boolean pacesCasts()
	{
		return _followUpOn;
	}

	boolean burns()
	{
		return _burnOn;
	}

	/** The manager's record for a partied member in one of the configured roles, else {@code null}. */
	Object member(Player player)
	{
		return _access.dpsMember(player, _roles);
	}

	// ===== Event hooks (called by the module) =====

	/** A member started a cast: note its target, shorten the engine's wait, and follow up when the cast ends. */
	void onCast(Player caster, Object member, Creature target, long now)
	{
		if ((target instanceof Monster) && (target != caster))
		{
			engage(caster, member, (Monster) target, now);
		}
		if (!_followUpOn)
		{
			return;
		}
		try
		{
			// The engine set its 1.6-2.5 s beat just before this cast; replace it with the short gap.
			final PlayState play = (PlayState) _access.mPlay.get(member);
			_access.psNextCastAt.setLong(play, now + _castGapMs + (_castGapJitterMs > 0 ? Rnd.get(_castGapJitterMs) : 0));
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return;
		}
		scheduleFollowUp(caster, CAST_POLL_MS, now + CAST_WAIT_MAX_MS);
	}

	/** A member swung at a monster. */
	void onSwing(Player attacker, Object member, Monster target, long now)
	{
		engage(attacker, member, target, now);
	}

	/** Damage landed on a monster (from anyone): feeds its time-to-kill. */
	void onMonsterDamaged(Monster target, double damage, long now)
	{
		if (_burnOn)
		{
			_rates.computeIfAbsent(target.getObjectId(), k -> new DamageRate()).add(now, damage);
		}
	}

	void housekeeping(long now)
	{
		_rates.values().removeIf(rate -> rate.idleSince(now) > 10000);
		_engaged.values().removeIf(engage -> (now - engage.at) > 60000);
	}

	/** Stops follow-ups and hands every member's playstyle back to the engine, which re-resolves the full one. */
	void shutdown()
	{
		_active = false;
		if (!_burnOn)
		{
			return;
		}
		try
		{
			for (Object member : _access.memberMap().values())
			{
				_access.psLookedUp.setBoolean(_access.mPlay.get(member), false);
			}
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			_log.warning("Phantom Combat: could not restore playstyles on disable: " + e);
		}
	}

	/** Records what a member is fighting; on a new target the full playstyle comes back before the first cast on it. */
	private void engage(Player npc, Object member, Monster target, long now)
	{
		final Engage previous = _engaged.put(npc.getObjectId(), new Engage(target, now));
		if (_burnOn && ((previous == null) || (previous.target != target)))
		{
			applyVariant(npc, member, target);
		}
	}

	// ===== Follow-up =====

	private void scheduleFollowUp(Player npc, long delay, long castDeadline)
	{
		if (_pending.add(npc.getObjectId()))
		{
			ThreadPool.schedule(() -> followUp(npc, castDeadline), delay);
		}
	}

	private void followUp(Player npc, long castDeadline)
	{
		final int id = npc.getObjectId();
		_pending.remove(id);
		if (!_active || !_followUpOn || npc.isDead())
		{
			return;
		}
		final long now = System.currentTimeMillis();
		if (npc.isCastingNow())
		{
			if (now < castDeadline)
			{
				scheduleFollowUp(npc, CAST_POLL_MS, castDeadline);
			}
			return;
		}
		final Object member = member(npc);
		final Engage engage = _engaged.get(id);
		if ((member == null) || (engage == null) || ((now - engage.at) > _engagedWindowMs))
		{
			return; // not fighting any more, as far as the manager is concerned
		}
		final Monster focus = engage.target;
		if (!mayAct(npc, member, focus, now))
		{
			return;
		}

		try
		{
			final PlayState play = (PlayState) _access.mPlay.get(member);
			final Object role = _access.mRole.get(member);
			final boolean mage = _access.roleMage.getBoolean(role);
			if (_burnOn)
			{
				applyVariant(npc, member, focus);
			}
			final boolean healerReady = (Boolean) _access.healerReady.invoke(PhantomPartyManager.getInstance(), member);
			final boolean underAttack = (Boolean) _access.underAttack.invoke(null, npc);
			final int mpReserve = (Integer) _access.mpReserve.invoke(null, role);
			final CastAction action = PhantomPlaystyleEngine.pick(npc, focus, play, healerReady, underAttack, mpReserve, ((Enum<?>) role).name());
			if (action != null)
			{
				if (_debug)
				{
					_log.info("Phantom Combat: follow-up " + npc.getName() + " -> " + action.skill.getName() + (action.target == npc ? " (self)" : " on " + focus.getName()));
				}
				npc.setTarget(action.target);
				npc.doCast(action.skill); // its skill-use event schedules the next follow-up
				if (npc.isCastingNow() || npc.isCastingSimultaneouslyNow())
				{
					PhantomPlaystyleEngine.confirmCast(play, action);
					return;
				}
				npc.setTarget(focus); // the core refused the cast; carry on as if nothing was picked
			}
			if (!mage)
			{
				resumeSwing(npc, focus);
			}
			// Nothing castable yet (cooldowns, pacing, MP): look again shortly while the member stays engaged.
			scheduleFollowUp(npc, IDLE_POLL_MS, now + IDLE_POLL_MS + CAST_WAIT_MAX_MS);
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			if (_debug)
			{
				_log.warning("Phantom Combat: follow-up for " + npc.getName() + " failed: " + e);
			}
		}
	}

	/** Everything that means the manager wants this member doing something other than hitting {@code focus}. */
	private boolean mayAct(Player npc, Object member, Monster focus, long now)
	{
		if (focus.isDead() || !focus.isInCombat() || focus.isRaid() || focus.isRaidMinion())
		{
			return false; // raids stay with the manager's raid gates
		}
		final Object target = npc.getTarget();
		if ((target != focus) && (target != npc))
		{
			return false; // the manager has moved it onto something else
		}
		if (npc.isMoving() || npc.isSitting() || npc.isInsideZone(ZoneId.PEACE) || focus.isInsideZone(ZoneId.PEACE) || PhantomManager.getInstance().isPvpEngaged(npc))
		{
			return false; // repositioning, peeling, resting, or a PvP the manager owns
		}
		try
		{
			return !_access.mHolding.getBoolean(member) && (now >= _access.mEaseUntil.getLong(member)) && (now >= _access.mRecoveryUntil.getLong(member));
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return false;
		}
	}

	/** Relaunches a fighter's swing after a cast, the same way the manager's engageFocus does. */
	private static void resumeSwing(Player npc, Monster focus)
	{
		if (npc.isAttackingNow() && (npc.getTarget() == focus))
		{
			return;
		}
		npc.setTarget(focus);
		npc.setRunning();
		if ((npc.getAI().getIntention() == Intention.ATTACK) && (npc.getAI().getAttackTarget() == focus))
		{
			npc.getAI().notifyAction(Action.THINK);
		}
		else
		{
			npc.getAI().setIntention(Intention.ATTACK, focus);
		}
	}

	// ===== Burn phase =====

	/** Points the member's engine state at its full or burn playstyle, depending on how soon {@code focus} will die. */
	private void applyVariant(Player npc, Object member, Monster focus)
	{
		try
		{
			final Object role = _access.mRole.get(member);
			final Playstyle full = PhantomPlaystyleData.getInstance().getPlaystyle(npc.getPlayerClass().getId(), ((Enum<?>) role).name());
			if (full == null)
			{
				return;
			}
			final int generation = PhantomPlaystyleData.getInstance().getGeneration();
			final boolean burn = !focus.isRaid() && !focus.isRaidMinion() && (timeToKill(focus) < _burnTtkSeconds);
			final Playstyle chosen = burn ? burnVariant(full, generation) : full;
			final PlayState play = (PlayState) _access.mPlay.get(member);
			if (_access.psPlaystyle.get(play) != chosen)
			{
				_access.psPlaystyle.set(play, chosen);
				_access.psLookedUp.setBoolean(play, true);
				_access.psGeneration.setInt(play, generation); // so the engine doesn't re-resolve it straight back
				if (_debug)
				{
					_log.info("Phantom Combat: " + npc.getName() + " uses " + chosen.name + " on " + focus.getName());
				}
			}
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			if (_debug)
			{
				_log.warning("Phantom Combat: burn phase for " + npc.getName() + " failed: " + e);
			}
		}
	}

	private synchronized Playstyle burnVariant(Playstyle full, int generation) throws ReflectiveOperationException
	{
		if (generation != _variantGeneration)
		{
			_burnVariants.clear();
			_variantGeneration = generation;
		}
		Playstyle burn = _burnVariants.get(full);
		if (burn == null)
		{
			final List<PlayEntry> entries = new ArrayList<>();
			for (PlayEntry entry : full.entries)
			{
				if ((entry.use != Use.DEBUFF) && (entry.use != Use.CONTROL) && (entry.use != Use.OPENER))
				{
					entries.add(entry);
				}
			}
			burn = _access.playstyleCtor.newInstance(full.name + " [burn]", full.role, entries);
			_burnVariants.put(full, burn);
		}
		return burn;
	}

	/** Seconds until {@code mob} dies at the party's current rate; infinite when there isn't enough data yet. */
	private double timeToKill(Monster mob)
	{
		final DamageRate rate = _rates.get(mob.getObjectId());
		final double dps = (rate == null) ? 0 : rate.perSecond(System.currentTimeMillis());
		return (dps <= 0) ? Double.MAX_VALUE : mob.getCurrentHp() / dps;
	}

	// ===== Small records =====

	private static class Engage
	{
		final Monster target;
		final long at;

		Engage(Monster target, long at)
		{
			this.target = target;
			this.at = at;
		}
	}

	/** Damage a monster took over the last few seconds. */
	private static class DamageRate
	{
		private final ArrayDeque<double[]> _samples = new ArrayDeque<>(); // {time, damage}

		synchronized void add(long now, double damage)
		{
			_samples.addLast(new double[]
			{
				now,
				damage
			});
			prune(now);
		}

		synchronized double perSecond(long now)
		{
			prune(now);
			if (_samples.size() < 2)
			{
				return 0;
			}
			final double span = now - _samples.peekFirst()[0];
			if (span < 800)
			{
				return 0; // too little to judge
			}
			double total = 0;
			for (double[] sample : _samples)
			{
				total += sample[1];
			}
			return total / (span / 1000.0);
		}

		synchronized long idleSince(long now)
		{
			return _samples.isEmpty() ? Long.MAX_VALUE : now - (long) _samples.peekLast()[0];
		}

		private void prune(long now)
		{
			while (!_samples.isEmpty() && ((now - _samples.peekFirst()[0]) > RATE_WINDOW_MS))
			{
				_samples.pollFirst();
			}
		}
	}
}
