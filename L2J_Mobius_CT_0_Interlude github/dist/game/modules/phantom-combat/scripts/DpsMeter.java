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
import java.util.BitSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.ToDoubleFunction;

import org.l2jmobius.gameserver.handler.IVoicedCommandHandler;
import org.l2jmobius.gameserver.managers.PhantomManager;
import org.l2jmobius.gameserver.managers.PhantomPartyManager;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.network.serverpackets.NpcHtmlMessage;

/**
 * The {@code .dps} meter: damage, DPS, share, casts and active time per party member (the owner, their recruits and
 * their pets), for the fight in progress or the last one, and for the session. A fight ends after 8 s with no damage.
 */
final class DpsMeter
{
	/** A fight ends after this long with no damage from the party. */
	private static final long FIGHT_IDLE_MS = 8000;

	/** Owner object id -> meter records. */
	private final Map<Integer, OwnerMeter> _meters = new ConcurrentHashMap<>();

	void onDamage(Player attacker, double damage, boolean bySkill, long now)
	{
		final OwnerMeter meter = meterFor(attacker);
		if (meter != null)
		{
			meter.onDamage(attacker, damage, bySkill, now);
		}
	}

	void onCast(Player caster, long now)
	{
		final OwnerMeter meter = meterFor(caster);
		if (meter != null)
		{
			meter.onCast(caster, now);
		}
	}

	void onSwing(Player attacker, long now)
	{
		final OwnerMeter meter = meterFor(attacker);
		if (meter != null)
		{
			meter.onSwing(attacker, now);
		}
	}

	void housekeeping(long now)
	{
		for (OwnerMeter meter : _meters.values())
		{
			meter.closeIfIdle(now);
		}
	}

	IVoicedCommandHandler command()
	{
		return new DpsCommand();
	}

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

		private static void table(StringBuilder sb, Map<Integer, Stat> stats, double seconds, ToDoubleFunction<Stat> active)
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
