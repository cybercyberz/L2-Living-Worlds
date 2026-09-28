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
package modules.questnavigator;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.TreeSet;
import java.util.logging.Logger;

import org.l2jmobius.commons.threads.ThreadPool;
import org.l2jmobius.gameserver.data.SpawnTable;
import org.l2jmobius.gameserver.data.xml.NpcData;
import org.l2jmobius.gameserver.handler.CommunityBoardHandler;
import org.l2jmobius.gameserver.handler.IParseBoardHandler;
import org.l2jmobius.gameserver.handler.IVoicedCommandHandler;
import org.l2jmobius.gameserver.managers.ScriptManager;
import org.l2jmobius.gameserver.model.World;
import org.l2jmobius.gameserver.model.WorldObject;
import org.l2jmobius.gameserver.model.actor.Npc;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.templates.NpcTemplate;
import org.l2jmobius.gameserver.model.events.EventType;
import org.l2jmobius.gameserver.model.events.ListenerRegisterType;
import org.l2jmobius.gameserver.model.events.listeners.AbstractEventListener;
import org.l2jmobius.gameserver.model.script.Quest;
import org.l2jmobius.gameserver.model.spawns.Spawn;
import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;
import org.l2jmobius.gameserver.network.serverpackets.NpcHtmlMessage;
import org.l2jmobius.gameserver.network.serverpackets.RadarControl;
import org.l2jmobius.gameserver.network.serverpackets.ShowMiniMap;

/**
 * The Quest Navigator module. It gives the modded Alt+U quest window (see {@code tools/questnav}) somewhere to send its
 * clicks, and the data to build its rows from:
 * <ul>
 * <li>{@code _bbs_questnav go <npcId>} puts the radar marker and map flag on the nearest spawn of that NPC. It is a
 * Community Board command because the server only accepts client-initiated bypasses that start with {@code _bbs}. It
 * sends no HTML, so the board does not open.</li>
 * <li>{@code _bbs_questnav clear} removes the marker.</li>
 * <li>At startup, and on {@code .questnav export} (GM only), it writes every quest's talk, start and hunt NPCs to the
 * tsv the client generator reads.</li>
 * </ul>
 */
public class QuestNavigatorModule implements GameModule
{
	private static final String BOARD_COMMAND = "_bbs_questnav";

	private Logger _log;
	private Path _exportPath;

	@Override
	public void onEnable(ModuleContext context)
	{
		if (!context.config().getBoolean("Enabled", false))
		{
			return; // Switch off: register nothing, behave as stock.
		}

		_log = context.logging();
		_exportPath = Paths.get(context.config().getString("ExportPath", "../tools/questnav/quest_npcs.tsv"));

		// ModuleHandlers has no board method, so register the board handler directly.
		CommunityBoardHandler.getInstance().registerHandler(new QuestNavBoard());
		context.handlers().registerVoicedCommand(new QuestNavVoicedCommand());

		// Quests are registered before modules load, but spawns load after, so wait until the server is up.
		if (context.config().getBoolean("ExportOnStartup", true))
		{
			ThreadPool.schedule(this::export, 120000);
		}

		_log.info("Quest Navigator module enabled, registered " + BOARD_COMMAND + " and .questnav");
	}

	/**
	 * Writes one row per quest NPC: questId, quest name, npcId, role (start, talk or hunt), level, spawn count, NPC name.
	 * @return the number of rows written, or -1 on failure
	 */
	private int export()
	{
		final List<String> lines = new ArrayList<>();
		lines.add("#questId\tquestName\tnpcId\trole\tlevel\tspawns\tnpcName");

		final List<Quest> quests = new ArrayList<>(ScriptManager.getInstance().getQuests().values());
		quests.sort(Comparator.comparingInt(Quest::getId));
		for (Quest quest : quests)
		{
			if (quest.getId() <= 0)
			{
				continue;
			}

			for (QuestNpc npc : collectQuestNpcs(quest))
			{
				lines.add(quest.getId() + "\t" + quest.getName() + "\t" + npc.npcId + "\t" + npc.role + "\t" + npc.template.getLevel() + "\t" + npc.spawns + "\t" + npc.template.getName().replace('\t', ' '));
			}
		}

		try
		{
			if (_exportPath.getParent() != null)
			{
				Files.createDirectories(_exportPath.getParent());
			}
			Files.write(_exportPath, lines, StandardCharsets.UTF_8);
		}
		catch (IOException e)
		{
			_log.warning("Quest Navigator: could not write " + _exportPath.toAbsolutePath() + ": " + e.getMessage());
			return -1;
		}

		final int rows = lines.size() - 1;
		_log.info("Quest Navigator: exported " + rows + " quest NPC rows to " + _exportPath.toAbsolutePath().normalize());
		return rows;
	}

	private static class QuestNpc
	{
		final int npcId;
		final String role;
		final NpcTemplate template;
		final int spawns;

		QuestNpc(int npcId, String role, NpcTemplate template, int spawns)
		{
			this.npcId = npcId;
			this.role = role;
			this.template = template;
			this.spawns = spawns;
		}
	}

	/**
	 * @return the quest's NPCs worth going to, each with its role: start, talk or hunt
	 */
	private static List<QuestNpc> collectQuestNpcs(Quest quest)
	{
		final List<QuestNpc> result = new ArrayList<>();
		for (int npcId : new TreeSet<>(quest.getRegisteredIds(ListenerRegisterType.NPC)))
		{
			final NpcTemplate template = NpcData.getInstance().getTemplate(npcId);
			if (template == null)
			{
				continue;
			}

			final String role;
			if (hasListener(template, quest, EventType.ON_NPC_QUEST_START))
			{
				role = "start";
			}
			else if (hasListener(template, quest, EventType.ON_NPC_TALK) || hasListener(template, quest, EventType.ON_NPC_FIRST_TALK))
			{
				role = "talk";
			}
			else if (hasListener(template, quest, EventType.ON_ATTACKABLE_KILL) || hasListener(template, quest, EventType.ON_ATTACKABLE_ATTACK))
			{
				role = "hunt";
			}
			else
			{
				continue; // Spawn, skill-see and similar hooks are not places to go.
			}

			result.add(new QuestNpc(npcId, role, template, SpawnTable.getInstance().getSpawns(npcId).size()));
		}
		return result;
	}

	/**
	 * Opens the navigator window for the quest behind an Alt+U tree node: {@code root.<questId>[.<level>.<completed>[.desc]]}.
	 */
	private static void showQuest(Player player, String nodeName)
	{
		final String[] parts = nodeName.split("\\.");
		if ((parts.length < 2) || !parts[0].equals("root"))
		{
			return; // Not a quest node, for example the root itself.
		}

		final int questId;
		try
		{
			questId = Integer.parseInt(parts[1]);
		}
		catch (NumberFormatException e)
		{
			return;
		}

		final Quest quest = ScriptManager.getInstance().getQuest(questId);
		final List<QuestNpc> npcs = (quest == null) ? List.of() : collectQuestNpcs(quest);
		if (npcs.isEmpty())
		{
			player.sendMessage("Quest Navigator: no known NPCs for quest " + questId + ".");
			return;
		}

		final StringBuilder sb = new StringBuilder();
		sb.append("<html><title>Quest Navigator</title><body>");
		sb.append("<font color=\"LEVEL\">").append(prettyName(quest.getName())).append("</font><br1>");
		sb.append("<font color=\"808080\">Click a name to mark its nearest spawn on your radar and map.</font><br>");
		appendRows(sb, npcs, false, "Talk to");
		appendRows(sb, npcs, true, "Hunt");
		sb.append("<br><a action=\"bypass ").append(BOARD_COMMAND).append(" clear\">Clear marker</a>");
		sb.append("</body></html>");
		player.sendPacket(new NpcHtmlMessage(sb.toString()));
	}

	private static void appendRows(StringBuilder sb, List<QuestNpc> npcs, boolean hunt, String title)
	{
		boolean first = true;
		for (QuestNpc npc : npcs)
		{
			if (npc.role.equals("hunt") != hunt)
			{
				continue;
			}

			if (first)
			{
				sb.append("<font color=\"B09B79\">").append(title).append(":</font><br1><table width=270>");
				first = false;
			}

			sb.append("<tr><td width=200>");
			if (npc.spawns > 0)
			{
				sb.append("<a action=\"bypass ").append(BOARD_COMMAND).append(" go ").append(npc.npcId).append("\">&@").append(npc.npcId).append(";</a>");
			}
			else
			{
				sb.append("<font color=\"808080\">&@").append(npc.npcId).append("; (no fixed spawn)</font>");
			}
			if (npc.role.equals("start"))
			{
				sb.append(" <font color=\"808080\">(start)</font>");
			}
			sb.append("</td><td width=70 align=right>Lv ").append(npc.template.getLevel()).append("</td></tr>");
		}

		if (!first)
		{
			sb.append("</table><br>");
		}
	}

	/**
	 * Q00303_CollectArrowheads becomes "Collect Arrowheads".
	 */
	private static String prettyName(String scriptName)
	{
		final String name = scriptName.replaceFirst("^Q\\d+_", "");
		return name.replaceAll("([a-z0-9])([A-Z])", "$1 $2").replace('_', ' ');
	}

	private static boolean hasListener(NpcTemplate template, Quest quest, EventType type)
	{
		for (AbstractEventListener listener : template.getListeners(type))
		{
			if (listener.getOwner() == quest)
			{
				return true;
			}
		}
		return false;
	}

	/**
	 * Marks the nearest spawn of {@code npcId} on the player's radar and map.
	 */
	private static void navigate(Player player, int npcId)
	{
		final NpcTemplate template = NpcData.getInstance().getTemplate(npcId);
		if (template == null)
		{
			player.sendMessage("Quest Navigator: unknown NPC " + npcId + ".");
			return;
		}

		int[] best = null;
		double bestDistance = Double.MAX_VALUE;
		for (Spawn spawn : SpawnTable.getInstance().getSpawns(npcId))
		{
			// A live NPC's position beats the spawn point, which is 0,0 for territory spawns.
			final Npc npc = spawn.getLastSpawn();
			final int x = (npc != null) && npc.isSpawned() ? npc.getX() : spawn.getX();
			final int y = (npc != null) && npc.isSpawned() ? npc.getY() : spawn.getY();
			final int z = (npc != null) && npc.isSpawned() ? npc.getZ() : spawn.getZ();
			if ((x == 0) && (y == 0))
			{
				continue;
			}

			final double distance = player.calculateDistance2D(x, y, z);
			if (distance < bestDistance)
			{
				bestDistance = distance;
				best = new int[]
				{
					x,
					y,
					z
				};
			}
		}

		// Scripted spawns have no SpawnTable entry: look for a live one.
		if (best == null)
		{
			for (WorldObject object : World.getInstance().getVisibleObjects())
			{
				if (object.isNpc() && (((Npc) object).getId() == npcId))
				{
					final double distance = player.calculateDistance2D(object.getX(), object.getY(), object.getZ());
					if (distance < bestDistance)
					{
						bestDistance = distance;
						best = new int[]
						{
							object.getX(),
							object.getY(),
							object.getZ()
						};
					}
				}
			}
		}

		if (best == null)
		{
			player.sendMessage("Quest Navigator: " + template.getName() + " has no fixed spawn (boss, instance or scripted).");
			return;
		}

		final int[] target = best;
		player.getRadar().removeAllMarkers();
		player.sendPacket(new ShowMiniMap(-1));
		ThreadPool.schedule(() ->
		{
			player.getRadar().addMarker(target[0], target[1], target[2]);
			player.sendPacket(new RadarControl(0, 2, target[0], target[1], target[2]));
		}, 500);
		player.sendMessage("Quest Navigator: " + template.getName() + " (Lv " + template.getLevel() + ") is about " + (int) bestDistance + " away. Marked on your radar and map.");
	}

	private class QuestNavBoard implements IParseBoardHandler
	{
		private final String[] COMMANDS =
		{
			BOARD_COMMAND
		};

		@Override
		public boolean onCommand(String command, Player player)
		{
			final String[] params = command.trim().split("\\s+");
			if ((params.length >= 3) && params[1].equals("go"))
			{
				try
				{
					navigate(player, Integer.parseInt(params[2]));
				}
				catch (NumberFormatException e)
				{
					player.sendMessage("Quest Navigator: bad NPC id " + params[2] + ".");
				}
			}
			else if ((params.length >= 3) && params[1].equals("step"))
			{
				showQuest(player, params[2]);
			}
			else if ((params.length >= 2) && params[1].equals("clear"))
			{
				player.getRadar().removeAllMarkers();
				player.sendMessage("Quest Navigator: marker cleared.");
			}
			return true;
		}

		@Override
		public String[] getCommandList()
		{
			return COMMANDS;
		}
	}

	private class QuestNavVoicedCommand implements IVoicedCommandHandler
	{
		private final String[] COMMANDS =
		{
			"questnav"
		};

		@Override
		public boolean onCommand(String command, Player player, String params)
		{
			if (player == null)
			{
				return false;
			}

			final String[] args = (params == null) ? new String[0] : params.trim().split("\\s+");
			if ((args.length >= 1) && args[0].equals("export") && player.isGM())
			{
				final int rows = export();
				player.sendMessage(rows < 0 ? "Quest Navigator: export failed, see the server log." : "Quest Navigator: exported " + rows + " rows.");
			}
			else if ((args.length >= 2) && args[0].equals("go"))
			{
				try
				{
					navigate(player, Integer.parseInt(args[1]));
				}
				catch (NumberFormatException e)
				{
					player.sendMessage("Quest Navigator: bad NPC id " + args[1] + ".");
				}
			}
			else if ((args.length >= 1) && args[0].equals("clear"))
			{
				player.getRadar().removeAllMarkers();
				player.sendMessage("Quest Navigator: marker cleared.");
			}
			else
			{
				player.sendMessage("Quest Navigator: .questnav go <npcId> | .questnav clear" + (player.isGM() ? " | .questnav export" : ""));
			}
			return true;
		}

		@Override
		public String[] getCommandList()
		{
			return COMMANDS;
		}
	}
}
