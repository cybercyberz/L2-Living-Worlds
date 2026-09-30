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

import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ScheduledFuture;
import java.util.logging.Logger;

import org.l2jmobius.commons.threads.ThreadPool;
import org.l2jmobius.gameserver.model.actor.Creature;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.Summon;
import org.l2jmobius.gameserver.model.actor.instance.Monster;
import org.l2jmobius.gameserver.model.events.EventType;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureAttack;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureDamageDealt;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureSkillUse;
import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;

/**
 * When a phantom may cast next, in one place. Three sections, each switchable in {@code config/module.ini}:
 * <ul>
 * <li><b>Skill pacing</b> ({@link SkillPacing}, all phantoms): a playstyle's {@code paceMs} is a per-skill cooldown, not a
 * stall of the whole rotation.</li>
 * <li><b>Party tempo</b> ({@link PartyTempo}, recruited DPS members): the next skill fires as soon as a cast ends, a
 * fighter's swing resumes, and setup skills are skipped on mobs about to die.</li>
 * <li><b>Meter</b> ({@link DpsMeter}): {@code .dps}, to measure the difference.</li>
 * </ul>
 * One rule ties pacing and tempo together: every phantom whose casting pace this module sets also gets each skill's own
 * {@code paceMs}, so a shorter tempo gap never erases it - even with SkillPacing off.
 * <p>
 * All of it goes through one set of global event listeners, so the steps always run in the same order. The jar is not
 * patched: private phantom state is reached through {@link PlaystyleAccess}; if that fails on a future jar, pacing and
 * tempo switch off with a warning and the meter keeps working.
 */
public class PhantomCombatModule implements GameModule
{
	/** How often a {@code //phantom playstyle} reload is looked for. */
	private static final long SYNC_INTERVAL_MS = 2000;

	private Logger _log;
	private SkillPacing _pacing;
	private PartyTempo _tempo;
	private DpsMeter _meter;
	private ScheduledFuture<?> _syncTask;
	private ScheduledFuture<?> _housekeeping;

	@Override
	public void onEnable(ModuleContext context)
	{
		_log = context.logging();
		if (!context.config().getBoolean("Enabled", false))
		{
			return;
		}
		final boolean debug = context.config().getBoolean("Debug", false);
		final boolean skillPacing = context.config().getBoolean("SkillPacing", true);
		final boolean partyTempo = context.config().getBoolean("PartyTempo", true);
		final boolean burnPhase = context.config().getBoolean("BurnPhase", true);
		final boolean meter = context.config().getBoolean("Meter", true);

		PlaystyleAccess access = null;
		if (skillPacing || partyTempo || burnPhase)
		{
			access = new PlaystyleAccess(_log);
		}
		if ((partyTempo || burnPhase) && access.partyOk)
		{
			final Set<String> roles = new HashSet<>();
			for (String role : context.config().getString("Roles", "WARRIOR,DAGGER,ARCHER,MONK,NUKER").split(","))
			{
				if (!role.isBlank())
				{
					roles.add(role.trim().toUpperCase(Locale.ROOT));
				}
			}
			_tempo = new PartyTempo(access, _log, partyTempo, burnPhase, //
				Math.max(0, context.config().getInt("CastGapMs", 250)), //
				Math.max(0, context.config().getInt("CastGapJitterMs", 250)), //
				Math.max(500, context.config().getInt("EngagedWindowMs", 1500)), //
				context.config().getDouble("BurnTtkSeconds", 5), roles, debug);
		}
		// The paceMs table is needed for SkillPacing, and for any phantom whose pace the tempo sets.
		if ((skillPacing || ((_tempo != null) && _tempo.pacesCasts())) && access.dataOk)
		{
			_pacing = new SkillPacing(access, _log, skillPacing, debug);
			_pacing.sync();
			_syncTask = ThreadPool.scheduleAtFixedRate(_pacing::sync, SYNC_INTERVAL_MS, SYNC_INTERVAL_MS);
		}
		if (meter)
		{
			_meter = new DpsMeter();
			context.handlers().registerVoicedCommand(_meter.command());
		}

		if ((_meter != null) || (_pacing != null) || (_tempo != null))
		{
			context.events().onGlobal(EventType.ON_CREATURE_SKILL_USE, (OnCreatureSkillUse event) -> onSkillUse(event));
		}
		if ((_meter != null) || (_tempo != null))
		{
			context.events().onGlobal(EventType.ON_CREATURE_ATTACK, (OnCreatureAttack event) -> onAttack(event));
			_housekeeping = ThreadPool.scheduleAtFixedRate(this::housekeeping, 1000, 1000);
		}
		if ((_meter != null) || ((_tempo != null) && _tempo.burns()))
		{
			context.events().onGlobal(EventType.ON_CREATURE_DAMAGE_DEALT, (OnCreatureDamageDealt event) -> onDamage(event));
		}

		_log.info("Phantom Combat: " + describePacing() + "; party tempo " + ((_tempo != null) && _tempo.pacesCasts() ? "on (gap " + context.config().getInt("CastGapMs", 250) + "+" + context.config().getInt("CastGapJitterMs", 250) + " ms)" : "off") //
			+ "; burn phase " + ((_tempo != null) && _tempo.burns() ? "on (under " + context.config().getDouble("BurnTtkSeconds", 5) + " s)" : "off") //
			+ "; meter " + (_meter != null ? "on" : "off") + ".");
	}

	private String describePacing()
	{
		if (_pacing == null)
		{
			return "skill pacing off";
		}
		final String counts = _pacing.entryCount() + " paced entries, " + _pacing.classCount() + " classes";
		return _pacing.strips() ? "skill pacing on (" + counts + ")" : "skill pacing for party tempo members only (" + counts + ")";
	}

	@Override
	public void onDisable(ModuleContext context)
	{
		if (_syncTask != null)
		{
			_syncTask.cancel(false);
			_syncTask = null;
		}
		if (_housekeeping != null)
		{
			_housekeeping.cancel(false);
			_housekeeping = null;
		}
		if (_tempo != null)
		{
			_tempo.shutdown();
		}
		if (_pacing != null)
		{
			_pacing.restore();
		}
	}

	// ===== The one pipeline =====

	private void onSkillUse(OnCreatureSkillUse event)
	{
		if (event.isSimultaneously() || !(event.getCaster() instanceof Player))
		{
			return;
		}
		final Player caster = (Player) event.getCaster();
		final long now = System.currentTimeMillis();
		// 1. Meter: count the cast in the owner's fight.
		if (_meter != null)
		{
			_meter.onCast(caster, now);
		}
		if (!PlaystyleAccess.isPhantom(caster))
		{
			return; // real players are never paced or chased
		}
		final Object member = (_tempo != null) ? _tempo.member(caster) : null;
		// 2. Skill pacing: every phantom when SkillPacing is on; otherwise the ones whose pace the tempo sets.
		if ((_pacing != null) && (_pacing.strips() || ((member != null) && _tempo.pacesCasts())))
		{
			_pacing.applyCooldown(caster, event.getSkill());
		}
		// 3. Party tempo: shorten the engine's wait and follow up when this cast ends.
		if (member != null)
		{
			_tempo.onCast(caster, member, event.getTarget(), now);
		}
	}

	private void onAttack(OnCreatureAttack event)
	{
		if (!(event.getAttacker() instanceof Player) || !(event.getTarget() instanceof Monster))
		{
			return;
		}
		final Player attacker = (Player) event.getAttacker();
		final long now = System.currentTimeMillis();
		if (_meter != null)
		{
			_meter.onSwing(attacker, now);
		}
		if (_tempo != null)
		{
			final Object member = _tempo.member(attacker);
			if (member != null)
			{
				_tempo.onSwing(attacker, member, (Monster) event.getTarget(), now);
			}
		}
	}

	private void onDamage(OnCreatureDamageDealt event)
	{
		if (!(event.getTarget() instanceof Monster) || (event.getDamage() <= 0))
		{
			return;
		}
		final long now = System.currentTimeMillis();
		if (_tempo != null)
		{
			_tempo.onMonsterDamaged((Monster) event.getTarget(), event.getDamage(), now);
		}
		if (_meter != null)
		{
			Creature attacker = event.getAttacker();
			if (attacker instanceof Summon)
			{
				attacker = ((Summon) attacker).getOwner(); // a pet's or servitor's damage counts for its master
			}
			if (attacker instanceof Player)
			{
				_meter.onDamage((Player) attacker, event.getDamage(), event.getSkill() != null, now);
			}
		}
	}

	private void housekeeping()
	{
		final long now = System.currentTimeMillis();
		if (_tempo != null)
		{
			_tempo.housekeeping(now);
		}
		if (_meter != null)
		{
			_meter.housekeeping(now);
		}
	}
}
