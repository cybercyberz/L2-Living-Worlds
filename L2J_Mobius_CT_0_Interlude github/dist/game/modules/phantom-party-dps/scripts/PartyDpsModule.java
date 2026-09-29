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
package modules.partydps;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.BitSet;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;
import java.util.logging.Logger;

import org.l2jmobius.commons.threads.ThreadPool;
import org.l2jmobius.commons.util.Rnd;
import org.l2jmobius.gameserver.ai.Action;
import org.l2jmobius.gameserver.ai.Intention;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.PlayEntry;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Playstyle;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Use;
import org.l2jmobius.gameserver.handler.IVoicedCommandHandler;
import org.l2jmobius.gameserver.managers.PhantomManager;
import org.l2jmobius.gameserver.managers.PhantomPartyManager;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine.CastAction;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine.PlayState;
import org.l2jmobius.gameserver.model.actor.Creature;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.Summon;
import org.l2jmobius.gameserver.model.actor.instance.Monster;
import org.l2jmobius.gameserver.model.events.EventType;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureAttack;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureDamageDealt;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureSkillUse;
import org.l2jmobius.gameserver.model.zone.ZoneId;
import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;
import org.l2jmobius.gameserver.network.serverpackets.NpcHtmlMessage;

/**
 * More damage from recruited phantom party members, without touching the jar.
 * <ul>
 * <li><b>DPS meter</b> ({@code .dps}): damage, DPS, casts and active time per party member, per fight and per session.</li>
 * <li><b>Fast follow-up</b>: the party manager decides once a second, and the playstyle engine then waits 1.6-2.5 s
 * before the next skill. When a DPS member starts a cast, this module shortens that wait and, as soon as the cast ends,
 * picks the next skill with the same engine call the manager uses ({@code PhantomPlaystyleEngine.pick}) - or, for a
 * fighter with nothing ready, relaunches the swing the cast interrupted. It only follows the manager's lead: it acts on
 * the target the member was already attacking, and stops the moment the member moves, sits, holds, or changes target.
 * Raid bosses and their minions are left entirely to the manager and its raid gates.</li>
 * <li><b>Burn phase</b>: on a mob that will die within a few seconds, setup skills (DEBUFF, CONTROL, OPENER) are dropped
 * from the member's playstyle so the casts go into damage.</li>
 * </ul>
 * The party manager's private state is reached by reflection; if this jar's classes differ, the module logs one warning
 * and stays off.
 */
public class PartyDpsModule implements GameModule
{
	/** A fight ends after this long with no damage from the party. */
	private static final long FIGHT_IDLE_MS = 8000;
	/** Window for the per-monster damage rate that time-to-kill is estimated from. */
	private static final long RATE_WINDOW_MS = 4000;
	/** How often the follow-up checks whether a running cast has ended. */
	private static final long CAST_POLL_MS = 100;
	/** A follow-up gives up waiting for a cast after this long (the manager's own watchdog handles stuck casts). */
	private static final long CAST_WAIT_MAX_MS = 8000;
	/** With nothing castable right now, the follow-up looks again after this long while the member stays engaged. */
	private static final long IDLE_POLL_MS = 300;

	private Logger _log;
	private boolean _debug;
	private boolean _meterOn;
	private boolean _followUpOn;
	private boolean _burnOn;
	private int _castGapMs;
	private int _castGapJitterMs;
	private long _engagedWindowMs;
	private double _burnTtkSeconds;
	private final Set<String> _roles = new HashSet<>();
	private volatile boolean _active;

	// Reflection handles into the party manager and the playstyle engine.
	private Field _membersField;
	private Field _mNpc;
	private Field _mRole;
	private Field _mPartied;
	private Field _mHolding;
	private Field _mEaseUntil;
	private Field _mRecoveryUntil;
	private Field _mPlay;
	private Field _roleMage;
	private Method _healerReady;
	private Method _underAttack;
	private Method _mpReserve;
	private Field _psPlaystyle;
	private Field _psLookedUp;
	private Field _psNextCastAt;
	private Field _psGeneration;
	private Constructor<Playstyle> _playstyleCtor;

	/** Member object id -> the monster it last attacked or cast on, and when. */
	private final Map<Integer, Engage> _engaged = new ConcurrentHashMap<>();
	/** Members with a follow-up scheduled; at most one each. */
	private final Set<Integer> _pending = ConcurrentHashMap.newKeySet();
	/** Monster object id -> recent damage taken, for time-to-kill. */
	private final Map<Integer, DamageRate> _rates = new ConcurrentHashMap<>();
	/** Full playstyle -> its burn variant; rebuilt when the playstyle data reloads. */
	private final Map<Playstyle, Playstyle> _burnVariants = new IdentityHashMap<>();
	private int _variantGeneration = Integer.MIN_VALUE;
	/** Owner object id -> DPS meter records. */
	private final Map<Integer, OwnerMeter> _meters = new ConcurrentHashMap<>();
	private ScheduledFuture<?> _housekeeping;

	@Override
	public void onEnable(ModuleContext context)
	{
		_log = context.logging();
		if (!context.config().getBoolean("Enabled", false))
		{
			return;
		}
		_debug = context.config().getBoolean("Debug", false);
		_meterOn = context.config().getBoolean("Meter", true);
		_followUpOn = context.config().getBoolean("FastFollowUp", true);
		_burnOn = context.config().getBoolean("BurnPhase", true);
		_castGapMs = Math.max(0, context.config().getInt("CastGapMs", 250));
		_castGapJitterMs = Math.max(0, context.config().getInt("CastGapJitterMs", 250));
		_engagedWindowMs = Math.max(500, context.config().getInt("EngagedWindowMs", 1500));
		_burnTtkSeconds = context.config().getDouble("BurnTtkSeconds", 5);
		for (String role : context.config().getString("Roles", "WARRIOR,DAGGER,ARCHER,MONK,NUKER").split(","))
		{
			if (!role.isBlank())
			{
				_roles.add(role.trim().toUpperCase(Locale.ROOT));
			}
		}

		if ((_followUpOn || _burnOn) && !resolveHandles())
		{
			_followUpOn = false;
			_burnOn = false;
		}

		if (_meterOn)
		{
			context.events().onGlobal(EventType.ON_CREATURE_DAMAGE_DEALT, (OnCreatureDamageDealt event) -> onDamage(event));
			context.handlers().registerVoicedCommand(new DpsCommand());
		}
		else if (_burnOn)
		{
			context.events().onGlobal(EventType.ON_CREATURE_DAMAGE_DEALT, (OnCreatureDamageDealt event) -> onDamage(event));
		}
		if (_meterOn || _followUpOn || _burnOn)
		{
			context.events().onGlobal(EventType.ON_CREATURE_SKILL_USE, (OnCreatureSkillUse event) -> onSkillUse(event));
			context.events().onGlobal(EventType.ON_CREATURE_ATTACK, (OnCreatureAttack event) -> onAttack(event));
			_housekeeping = ThreadPool.scheduleAtFixedRate(this::housekeeping, 1000, 1000);
		}
		_active = true;
		_log.info("Party DPS: meter " + onOff(_meterOn) + ", fast follow-up " + onOff(_followUpOn) + " (gap " + _castGapMs + "+" + _castGapJitterMs + " ms), burn phase " + onOff(_burnOn) + " (under " + _burnTtkSeconds + " s), roles " + _roles + ".");
	}

	@Override
	public void onDisable(ModuleContext context)
	{
		_active = false;
		if (_housekeeping != null)
		{
			_housekeeping.cancel(false);
			_housekeeping = null;
		}
		// Hand every member's playstyle back to the engine, which re-resolves the full one on its next pick.
		if (_burnOn)
		{
			try
			{
				for (Object member : ((Map<?, ?>) _membersField.get(PhantomPartyManager.getInstance())).values())
				{
					_psLookedUp.setBoolean(_mPlay.get(member), false);
				}
			}
			catch (ReflectiveOperationException | RuntimeException e)
			{
				_log.warning("Party DPS: could not restore playstyles on disable: " + e);
			}
		}
	}

	private static String onOff(boolean value)
	{
		return value ? "on" : "off";
	}

	private boolean resolveHandles()
	{
		try
		{
			_membersField = field(PhantomPartyManager.class, "_members");
			final Class<?> member = Class.forName("org.l2jmobius.gameserver.managers.PhantomPartyManager$Member");
			_mNpc = field(member, "npc");
			_mRole = field(member, "role");
			_mPartied = field(member, "partied");
			_mHolding = field(member, "holding");
			_mEaseUntil = field(member, "easeUntil");
			_mRecoveryUntil = field(member, "recoveryUntil");
			_mPlay = field(member, "play");
			final Class<?> role = Class.forName("org.l2jmobius.gameserver.managers.PhantomManager$PartyRole");
			_roleMage = field(role, "mage");
			_healerReady = PhantomPartyManager.class.getDeclaredMethod("healerReady", member);
			_healerReady.setAccessible(true);
			_underAttack = PhantomPartyManager.class.getDeclaredMethod("underAttack", Player.class);
			_underAttack.setAccessible(true);
			_mpReserve = PhantomPartyManager.class.getDeclaredMethod("mpReserve", role);
			_mpReserve.setAccessible(true);
			_psPlaystyle = field(PlayState.class, "playstyle");
			_psLookedUp = field(PlayState.class, "lookedUp");
			_psNextCastAt = field(PlayState.class, "nextCastAt");
			_psGeneration = field(PlayState.class, "generation");
			_playstyleCtor = Playstyle.class.getDeclaredConstructor(String.class, String.class, List.class);
			_playstyleCtor.setAccessible(true);
			return true;
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			_log.warning("Party DPS: this GameServer.jar's party manager has a different shape (" + e + "); follow-up and burn phase stay off.");
			return false;
		}
	}

	private static Field field(Class<?> owner, String name) throws NoSuchFieldException
	{
		final Field field = owner.getDeclaredField(name);
		field.setAccessible(true);
		return field;
	}

	// ===== Party member lookup =====

	/** The manager's Member record for a partied DPS member, else {@code null}. */
	private Object dpsMember(Player player)
	{
		if ((_membersField == null) || !PhantomPartyManager.getInstance().isRecruit(player))
		{
			return null;
		}
		try
		{
			final Object member = ((Map<?, ?>) _membersField.get(PhantomPartyManager.getInstance())).get(player.getObjectId());
			if ((member == null) || !_mPartied.getBoolean(member) || (_mNpc.get(member) != player))
			{
				return null;
			}
			return _roles.contains(((Enum<?>) _mRole.get(member)).name()) ? member : null;
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return null;
		}
	}

	// ===== Events =====

	private void onSkillUse(OnCreatureSkillUse event)
	{
		if (!_active || event.isSimultaneously() || !(event.getCaster() instanceof Player))
		{
			return;
		}
		final Player caster = (Player) event.getCaster();
		final long now = System.currentTimeMillis();
		if (_meterOn)
		{
			final OwnerMeter meter = meterFor(caster);
			if (meter != null)
			{
				meter.onCast(caster, now);
			}
		}
		if (!_followUpOn && !_burnOn)
		{
			return;
		}
		final Object member = dpsMember(caster);
		if (member == null)
		{
			return;
		}
		final Creature target = event.getTarget();
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
			final PlayState play = (PlayState) _mPlay.get(member);
			_psNextCastAt.setLong(play, now + _castGapMs + (_castGapJitterMs > 0 ? Rnd.get(_castGapJitterMs) : 0));
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return;
		}
		scheduleFollowUp(caster, CAST_POLL_MS, now + CAST_WAIT_MAX_MS);
	}

	private void onAttack(OnCreatureAttack event)
	{
		if (!_active || !(event.getAttacker() instanceof Player) || !(event.getTarget() instanceof Monster))
		{
			return;
		}
		final Player attacker = (Player) event.getAttacker();
		if (_meterOn)
		{
			final OwnerMeter meter = meterFor(attacker);
			if (meter != null)
			{
				meter.onSwing(attacker, System.currentTimeMillis());
			}
		}
		if (_followUpOn || _burnOn)
		{
			final Object member = dpsMember(attacker);
			if (member != null)
			{
				engage(attacker, member, (Monster) event.getTarget(), System.currentTimeMillis());
			}
		}
	}

	private void onDamage(OnCreatureDamageDealt event)
	{
		if (!_active || !(event.getTarget() instanceof Monster) || (event.getDamage() <= 0))
		{
			return;
		}
		final long now = System.currentTimeMillis();
		final Monster target = (Monster) event.getTarget();
		if (_burnOn)
		{
			_rates.computeIfAbsent(target.getObjectId(), k -> new DamageRate()).add(now, event.getDamage());
		}
		if (!_meterOn)
		{
			return;
		}
		Creature attacker = event.getAttacker();
		if (attacker instanceof Summon)
		{
			attacker = ((Summon) attacker).getOwner(); // a pet's or servitor's damage counts for its master
		}
		if (attacker instanceof Player)
		{
			final OwnerMeter meter = meterFor((Player) attacker);
			if (meter != null)
			{
				meter.onDamage((Player) attacker, event.getDamage(), event.getSkill() != null, now);
			}
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

	// ===== Fast follow-up =====

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
		final Object member = dpsMember(npc);
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
			final PlayState play = (PlayState) _mPlay.get(member);
			final Object role = _mRole.get(member);
			final boolean mage = _roleMage.getBoolean(role);
			if (_burnOn)
			{
				applyVariant(npc, member, focus);
			}
			final boolean healerReady = (Boolean) _healerReady.invoke(PhantomPartyManager.getInstance(), member);
			final boolean underAttack = (Boolean) _underAttack.invoke(null, npc);
			final int mpReserve = (Integer) _mpReserve.invoke(null, role);
			final CastAction action = PhantomPlaystyleEngine.pick(npc, focus, play, healerReady, underAttack, mpReserve, ((Enum<?>) role).name());
			if (action != null)
			{
				if (_debug)
				{
					_log.info("Party DPS: follow-up " + npc.getName() + " -> " + action.skill.getName() + (action.target == npc ? " (self)" : " on " + focus.getName()));
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
				_log.warning("Party DPS: follow-up for " + npc.getName() + " failed: " + e);
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
			return !_mHolding.getBoolean(member) && (now >= _mEaseUntil.getLong(member)) && (now >= _mRecoveryUntil.getLong(member));
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
			final Object role = _mRole.get(member);
			final Playstyle full = PhantomPlaystyleData.getInstance().getPlaystyle(npc.getPlayerClass().getId(), ((Enum<?>) role).name());
			if (full == null)
			{
				return;
			}
			final int generation = PhantomPlaystyleData.getInstance().getGeneration();
			final boolean burn = !focus.isRaid() && !focus.isRaidMinion() && (timeToKill(focus) < _burnTtkSeconds);
			final Playstyle chosen = burn ? burnVariant(full, generation) : full;
			final PlayState play = (PlayState) _mPlay.get(member);
			if (_psPlaystyle.get(play) != chosen)
			{
				_psPlaystyle.set(play, chosen);
				_psLookedUp.setBoolean(play, true);
				_psGeneration.setInt(play, generation); // so the engine doesn't re-resolve it straight back
				if (_debug)
				{
					_log.info("Party DPS: " + npc.getName() + " uses " + chosen.name + " on " + focus.getName());
				}
			}
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			if (_debug)
			{
				_log.warning("Party DPS: burn phase for " + npc.getName() + " failed: " + e);
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
			burn = _playstyleCtor.newInstance(full.name + " [burn]", full.role, entries);
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

	// ===== Housekeeping =====

	private void housekeeping()
	{
		final long now = System.currentTimeMillis();
		_rates.values().removeIf(rate -> rate.idleSince(now) > 10000);
		_engaged.values().removeIf(engage -> (now - engage.at) > 60000);
		for (OwnerMeter meter : _meters.values())
		{
			meter.closeIfIdle(now);
		}
	}

	// ===== DPS meter =====

	/** The meter a player's damage counts toward: their own if they're a real player, their owner's if they're a recruit. */
	private OwnerMeter meterFor(Player player)
	{
		final Player owner;
		if (PhantomPartyManager.getInstance().isRecruit(player))
		{
			owner = PhantomPartyManager.getInstance().getRecruitOwner(player);
		}
		else if (PhantomManager.getInstance().isPhantom(player))
		{
			return null; // field hunters are not anyone's party
		}
		else
		{
			owner = player;
		}
		return (owner == null) ? null : _meters.computeIfAbsent(owner.getObjectId(), k -> new OwnerMeter());
	}

	private class DpsCommand implements IVoicedCommandHandler
	{
		private final String[] COMMANDS =
		{
			"dps"
		};

		@Override
		public boolean onCommand(String command, Player player, String params)
		{
			if (player == null)
			{
				return true;
			}
			final OwnerMeter meter = _meters.computeIfAbsent(player.getObjectId(), k -> new OwnerMeter());
			if ((params != null) && params.trim().equalsIgnoreCase("reset"))
			{
				meter.reset();
				player.sendMessage("DPS meter: cleared.");
				return true;
			}
			player.sendPacket(new NpcHtmlMessage(meter.render()));
			return true;
		}

		@Override
		public String[] getCommandList()
		{
			return COMMANDS;
		}
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

	private static class Stat
	{
		final String name;
		double damage;
		int hits;
		int skillHits;
		int casts;
		final BitSet activeSeconds = new BitSet();
		long activeTotal; // session: active seconds summed over closed fights

		Stat(String name)
		{
			this.name = name;
		}
	}

	private static class Fight
	{
		final long start;
		long last;
		final Map<Integer, Stat> stats = new LinkedHashMap<>();

		Fight(long start)
		{
			this.start = start;
			last = start;
		}

		double seconds()
		{
			return Math.max(1.0, (last - start) / 1000.0);
		}

		Stat stat(Player player)
		{
			return stats.computeIfAbsent(player.getObjectId(), k -> new Stat(player.getName()));
		}

		void markActive(Stat stat, long now)
		{
			stat.activeSeconds.set((int) ((now - start) / 1000));
		}
	}

	/** One party's meter: the fight in progress, the last finished one, and the session. */
	private static class OwnerMeter
	{
		private Fight _current;
		private Fight _lastFight;
		private final Map<Integer, Stat> _session = new LinkedHashMap<>();
		private double _sessionSeconds;
		private int _sessionFights;

		synchronized void onDamage(Player player, double damage, boolean bySkill, long now)
		{
			closeIfIdle(now);
			if (_current == null)
			{
				_current = new Fight(now);
			}
			_current.last = now;
			final Stat stat = _current.stat(player);
			stat.damage += damage;
			stat.hits++;
			if (bySkill)
			{
				stat.skillHits++;
			}
			_current.markActive(stat, now);
		}

		synchronized void onCast(Player player, long now)
		{
			if ((_current != null) && ((now - _current.last) <= FIGHT_IDLE_MS))
			{
				final Stat stat = _current.stat(player);
				stat.casts++;
				_current.markActive(stat, now);
			}
		}

		synchronized void onSwing(Player player, long now)
		{
			if ((_current != null) && ((now - _current.last) <= FIGHT_IDLE_MS))
			{
				_current.markActive(_current.stat(player), now);
			}
		}

		synchronized void closeIfIdle(long now)
		{
			if ((_current == null) || ((now - _current.last) <= FIGHT_IDLE_MS))
			{
				return;
			}
			final Fight fight = _current;
			_current = null;
			_lastFight = fight;
			_sessionSeconds += fight.seconds();
			_sessionFights++;
			final int span = (int) ((fight.last - fight.start) / 1000) + 1;
			for (Map.Entry<Integer, Stat> entry : fight.stats.entrySet())
			{
				final Stat from = entry.getValue();
				final Stat to = _session.computeIfAbsent(entry.getKey(), k -> new Stat(from.name));
				to.damage += from.damage;
				to.hits += from.hits;
				to.skillHits += from.skillHits;
				to.casts += from.casts;
				to.activeTotal += Math.min(span, from.activeSeconds.get(0, span).cardinality());
			}
		}

		synchronized void reset()
		{
			_current = null;
			_lastFight = null;
			_session.clear();
			_sessionSeconds = 0;
			_sessionFights = 0;
		}

		synchronized String render()
		{
			closeIfIdle(System.currentTimeMillis());
			final StringBuilder sb = new StringBuilder(4000);
			sb.append("<html><title>DPS meter</title><body>");
			final Fight shown = (_current != null) ? _current : _lastFight;
			if (shown == null)
			{
				sb.append("No fight recorded yet. Hit something, then type .dps again.<br>");
			}
			else
			{
				final int span = (int) ((shown.last - shown.start) / 1000) + 1;
				sb.append("<font color=\"LEVEL\">").append(shown == _current ? "Current fight" : "Last fight").append("</font> - ").append(String.format(Locale.ROOT, "%.1f", shown.seconds())).append(" s<br1>");
				table(sb, shown.stats, shown.seconds(), stat -> Math.min(span, stat.activeSeconds.get(0, span).cardinality()) / (double) span);
			}
			if (_sessionFights > 0)
			{
				sb.append("<br><font color=\"LEVEL\">Session</font> - ").append(_sessionFights).append(" fight(s), ").append(String.format(Locale.ROOT, "%.0f", _sessionSeconds)).append(" s in combat<br1>");
				final double seconds = _sessionSeconds;
				table(sb, _session, seconds, stat -> stat.activeTotal / seconds);
			}
			sb.append("<br><font color=\"808080\">DPS counts only time in fights (a fight ends after 8 s without damage). Active = share of fight seconds with a hit, swing or cast. .dps reset clears it.</font>");
			sb.append("</body></html>");
			return sb.toString();
		}

		private static void table(StringBuilder sb, Map<Integer, Stat> stats, double seconds, java.util.function.ToDoubleFunction<Stat> active)
		{
			double total = 0;
			for (Stat stat : stats.values())
			{
				total += stat.damage;
			}
			final List<Stat> sorted = new ArrayList<>(stats.values());
			sorted.sort((a, b) -> Double.compare(b.damage, a.damage));
			sb.append("<table width=280><tr><td width=90>Name</td><td width=50 align=right>DPS</td><td width=40 align=right>Share</td><td width=40 align=right>Casts</td><td width=60 align=right>Active</td></tr>");
			for (Stat stat : sorted)
			{
				sb.append("<tr><td>").append(stat.name).append("</td>");
				sb.append("<td align=right>").append(String.format(Locale.ROOT, "%.0f", stat.damage / seconds)).append("</td>");
				sb.append("<td align=right>").append(String.format(Locale.ROOT, "%.0f%%", total > 0 ? (100 * stat.damage) / total : 0)).append("</td>");
				sb.append("<td align=right>").append(stat.casts).append("</td>");
				sb.append("<td align=right>").append(String.format(Locale.ROOT, "%.0f%%", 100 * Math.min(1.0, active.applyAsDouble(stat)))).append("</td></tr>");
			}
			sb.append("</table>");
			sb.append(String.format(Locale.ROOT, "Party total %.0f damage, %.0f DPS<br1>", total, total / seconds));
		}
	}
}
