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

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.PlayEntry;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Playstyle;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Use;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.skill.Skill;

/**
 * A playstyle entry's {@code paceMs} as a per-skill cooldown.
 * <p>
 * The engine ({@code PhantomPlaystyleEngine.pick}) applies {@code paceMs} to the member's single "next cast" gate, so
 * after Stun Attack ({@code paceMs=6000}) a phantom casts nothing else for 6 seconds. This section keeps a table of
 * class -> skill -> paceMs from the loaded data and, when a phantom casts a paced skill, disables just that skill for
 * that long. The engine already skips a disabled skill, and the skill's own reuse still applies on top.
 * <p>
 * With {@code strip} on (SkillPacing = True) it also zeroes {@code paceMs} in the loaded data, so the engine's shared
 * gate never stalls any phantom. With it off, the data stays stock and the table is only used for the phantoms whose
 * pace the party tempo section controls - so a shorter tempo gap can never erase a skill's own gap.
 * <p>
 * A {@code //phantom playstyle} reload swaps in a new data map; {@link #sync} (run every couple of seconds) notices the
 * new map object and re-reads it.
 */
final class SkillPacing
{
	private final PlaystyleAccess _access;
	private final Logger _log;
	private final boolean _strip;
	private final boolean _debug;

	/** The data map last read; a reload swaps in a new map object, which is how it is detected. */
	private Object _readMap;
	/** classId -> skillId -> paceMs, taken from the data before any stripping. */
	private volatile Map<Integer, Map<Integer, Integer>> _paces = Collections.emptyMap();
	/** Entries zeroed in the data and their original value, so {@link #restore} can hand them back. */
	private final Map<PlayEntry, Integer> _originals = new HashMap<>();
	private int _entryCount;

	SkillPacing(PlaystyleAccess access, Logger log, boolean strip, boolean debug)
	{
		_access = access;
		_log = log;
		_strip = strip;
		_debug = debug;
	}

	boolean strips()
	{
		return _strip;
	}

	int entryCount()
	{
		return _entryCount;
	}

	int classCount()
	{
		return _paces.size();
	}

	/** Reads (and, when stripping, zeroes) paceMs from freshly loaded playstyle data, once per data map. */
	@SuppressWarnings("unchecked")
	synchronized void sync()
	{
		final Map<Integer, List<Playstyle>> byClassId;
		try
		{
			byClassId = (Map<Integer, List<Playstyle>>) _access.byClassId.get(PhantomPlaystyleData.getInstance());
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			_log.warning("Phantom Combat: cannot read playstyle data: " + e);
			return;
		}
		if ((byClassId == null) || (byClassId == _readMap))
		{
			return;
		}

		// The entries zeroed last time belong to the replaced data; nothing reads them any more.
		_originals.clear();
		final Map<Integer, Map<Integer, Integer>> paces = new HashMap<>();
		final List<String> failures = new ArrayList<>();
		int count = 0;
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
					if (_strip)
					{
						try
						{
							_access.paceMs.setInt(entry, 0);
						}
						catch (ReflectiveOperationException | RuntimeException e)
						{
							failures.add(playstyle.name + "/" + entry.skillId + ": " + e);
							continue; // left as-is, so the engine keeps its stock gate for this entry
						}
						_originals.put(entry, paceMs);
					}
					count++;
					paces.computeIfAbsent(byClass.getKey(), k -> new HashMap<>()).merge(entry.skillId, paceMs, Math::max);
				}
			}
		}
		_paces = paces;
		_entryCount = count;
		final boolean reload = (_readMap != null);
		_readMap = byClassId;

		if (!failures.isEmpty())
		{
			_log.warning("Phantom Combat: could not strip " + failures.size() + " paceMs entry(ies), e.g. " + failures.get(0));
		}
		if (reload && _debug)
		{
			_log.info("Phantom Combat: playstyles reloaded; " + count + " paced entry(ies) across " + paces.size() + " class id(s).");
		}
	}

	/** Disables {@code skill} on {@code caster} for its class's paceMs, if it has one. */
	void applyCooldown(Player caster, Skill skill)
	{
		final Map<Integer, Integer> classPaces = _paces.get(caster.getPlayerClass().getId());
		final Integer paceMs = ((classPaces == null) || (skill == null)) ? null : classPaces.get(skill.getId());
		if (paceMs == null)
		{
			return;
		}
		caster.disableSkill(skill, paceMs);
		if (_debug)
		{
			_log.info("Phantom Combat: " + caster.getName() + " cast " + skill.getName() + "; next one in " + paceMs + " ms at the earliest.");
		}
	}

	/** Writes the original paceMs back into the entries this section zeroed. */
	synchronized void restore()
	{
		for (Map.Entry<PlayEntry, Integer> original : _originals.entrySet())
		{
			try
			{
				_access.paceMs.setInt(original.getKey(), original.getValue());
			}
			catch (ReflectiveOperationException | RuntimeException e)
			{
				_log.warning("Phantom Combat: could not restore paceMs on skill " + original.getKey().skillId + ": " + e);
			}
		}
		_originals.clear();
		_paces = Collections.emptyMap();
		_readMap = null;
	}
}
