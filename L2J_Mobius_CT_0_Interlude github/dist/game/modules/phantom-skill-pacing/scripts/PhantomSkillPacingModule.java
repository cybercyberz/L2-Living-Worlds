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
package modules.phantompacing;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ScheduledFuture;
import java.util.logging.Logger;

import org.l2jmobius.commons.threads.ThreadPool;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.PlayEntry;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Playstyle;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Use;
import org.l2jmobius.gameserver.managers.PhantomManager;
import org.l2jmobius.gameserver.managers.PhantomPartyManager;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.events.EventType;
import org.l2jmobius.gameserver.model.events.holders.actor.creature.OnCreatureSkillUse;
import org.l2jmobius.gameserver.model.skill.Skill;
import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;

/**
 * Makes a playstyle entry's {@code paceMs} a per-skill cooldown instead of a rotation-wide stall.
 * <p>
 * The core engine ({@code PhantomPlaystyleEngine.pick}) applies {@code paceMs} to the member's single "next cast"
 * gate, so after Stun Attack ({@code paceMs=6000}) a phantom casts nothing else for 6 seconds. This module takes the
 * value out of the loaded data (the engine then uses its default ~1.6-2.5s beat after every cast) and re-applies it to
 * the one skill: when a phantom casts a paced skill, that skill is disabled for {@code paceMs}. The engine already
 * skips a disabled skill, and the skill's own reuse still applies on top, so the longer of the two wins.
 * <p>
 * Only phantoms (field hunters, recruited party members, alt companions) are affected; real players never are.
 * A {@code //phantom playstyle} reload builds new data objects, so a timer re-strips them within a couple of seconds.
 */
public class PhantomSkillPacingModule implements GameModule
{
	private static final long SYNC_INTERVAL_MS = 2000;

	private Logger _log;
	private boolean _debug;
	private Field _byClassIdField;
	private Field _paceMsField;
	private ScheduledFuture<?> _syncTask;

	/** The data map last stripped; a reload swaps in a new map object, which is how it is detected. */
	private Object _strippedMap;
	/** classId -> skillId -> paceMs, taken from the data before stripping. */
	private volatile Map<Integer, Map<Integer, Integer>> _paces = Collections.emptyMap();
	/** Entries this module zeroed and their original value, so onDisable can hand them back. */
	private final Map<PlayEntry, Integer> _originals = new HashMap<>();

	@Override
	public void onEnable(ModuleContext context)
	{
		_log = context.logging();
		if (!context.config().getBoolean("Enabled", false))
		{
			return; // switch off: nothing stripped, the engine keeps its stock paceMs behavior
		}
		_debug = context.config().getBoolean("Debug", false);
		try
		{
			_byClassIdField = PhantomPlaystyleData.class.getDeclaredField("_byClassId");
			_byClassIdField.setAccessible(true);
			_paceMsField = PlayEntry.class.getDeclaredField("paceMs");
			_paceMsField.setAccessible(true);
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			_log.warning("Phantom Skill Pacing: this GameServer.jar's playstyle data has a different shape (" + e + "); module left inactive.");
			return;
		}

		sync();
		context.events().onGlobal(EventType.ON_CREATURE_SKILL_USE, (OnCreatureSkillUse event) -> onSkillUse(event));
		_syncTask = ThreadPool.scheduleAtFixedRate(this::sync, SYNC_INTERVAL_MS, SYNC_INTERVAL_MS);
	}

	@Override
	public void onDisable(ModuleContext context)
	{
		if (_syncTask != null)
		{
			_syncTask.cancel(false);
			_syncTask = null;
		}
		synchronized (this)
		{
			restore();
			_paces = Collections.emptyMap();
			_strippedMap = null;
		}
	}

	/** Strips paceMs from freshly loaded playstyle data, once per data map. */
	@SuppressWarnings("unchecked")
	private synchronized void sync()
	{
		final Map<Integer, List<Playstyle>> byClassId;
		try
		{
			byClassId = (Map<Integer, List<Playstyle>>) _byClassIdField.get(PhantomPlaystyleData.getInstance());
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			_log.warning("Phantom Skill Pacing: cannot read playstyle data: " + e);
			return;
		}
		if ((byClassId == null) || (byClassId == _strippedMap))
		{
			return;
		}

		// The entries zeroed last time belong to the replaced data; nothing reads them any more.
		_originals.clear();
		final Map<Integer, Map<Integer, Integer>> paces = new HashMap<>();
		final List<String> failures = new ArrayList<>();
		for (Map.Entry<Integer, List<Playstyle>> byClass : byClassId.entrySet())
		{
			for (Playstyle playstyle : byClass.getValue())
			{
				for (PlayEntry entry : playstyle.entries)
				{
					if ((entry.use == Use.PULL) || (entry.paceMs <= 0))
					{
						continue; // PULL never goes through pick(); unpaced entries have nothing to move
					}
					final int paceMs = entry.paceMs;
					try
					{
						_paceMsField.setInt(entry, 0);
					}
					catch (ReflectiveOperationException | RuntimeException e)
					{
						failures.add(playstyle.name + "/" + entry.skillId + ": " + e);
						continue; // left as-is, so the engine keeps its stock gate for this entry
					}
					_originals.put(entry, paceMs);
					paces.computeIfAbsent(byClass.getKey(), k -> new HashMap<>()).merge(entry.skillId, paceMs, Math::max);
				}
			}
		}
		_paces = paces;
		final boolean firstSync = (_strippedMap == null);
		_strippedMap = byClassId;

		if (!failures.isEmpty())
		{
			_log.warning("Phantom Skill Pacing: could not strip " + failures.size() + " entry(ies), e.g. " + failures.get(0));
		}
		if (firstSync || _debug)
		{
			_log.info("Phantom Skill Pacing: " + _originals.size() + " paced entry(ies) across " + paces.size() + " class id(s) now pace per skill" + (firstSync ? "." : " (playstyles reloaded)."));
		}
	}

	/** Writes the original paceMs back into the entries this module zeroed. */
	private void restore()
	{
		for (Map.Entry<PlayEntry, Integer> original : _originals.entrySet())
		{
			try
			{
				_paceMsField.setInt(original.getKey(), original.getValue());
			}
			catch (ReflectiveOperationException | RuntimeException e)
			{
				_log.warning("Phantom Skill Pacing: could not restore paceMs on skill " + original.getKey().skillId + ": " + e);
			}
		}
		_originals.clear();
	}

	private void onSkillUse(OnCreatureSkillUse event)
	{
		if (!(event.getCaster() instanceof Player))
		{
			return;
		}
		final Player caster = (Player) event.getCaster();
		final Map<Integer, Integer> classPaces = _paces.get(caster.getPlayerClass().getId());
		if (classPaces == null)
		{
			return;
		}
		final Skill skill = event.getSkill();
		final Integer paceMs = (skill == null) ? null : classPaces.get(skill.getId());
		if (paceMs == null)
		{
			return;
		}
		// Phantoms only: the same class played by a real player keeps normal reuse.
		if (!PhantomManager.getInstance().isPhantom(caster) && !PhantomPartyManager.getInstance().isRecruit(caster))
		{
			return;
		}
		caster.disableSkill(skill, paceMs);
		if (_debug)
		{
			_log.info("Phantom Skill Pacing: " + caster.getName() + " cast " + skill.getName() + "; next one in " + paceMs + " ms at the earliest.");
		}
	}
}
