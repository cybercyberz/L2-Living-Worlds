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
package modules.adventurerguide;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.logging.Logger;
import java.util.regex.Pattern;

import org.l2jmobius.commons.threads.ThreadPool;
import org.l2jmobius.gameserver.cache.HtmCache;
import org.l2jmobius.gameserver.config.custom.CommunityBoardConfig;
import org.l2jmobius.gameserver.data.SpawnTable;
import org.l2jmobius.gameserver.data.xml.ClassListData;
import org.l2jmobius.gameserver.geoengine.GeoEngine;
import org.l2jmobius.gameserver.handler.CommunityBoardHandler;
import org.l2jmobius.gameserver.handler.IParseBoardHandler;
import org.l2jmobius.gameserver.handler.IVoicedCommandHandler;
import org.l2jmobius.gameserver.managers.ScriptManager;
import org.l2jmobius.gameserver.model.Location;
import org.l2jmobius.gameserver.model.World;
import org.l2jmobius.gameserver.model.WorldObject;
import org.l2jmobius.gameserver.model.actor.Npc;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.enums.player.PlayerClass;
import org.l2jmobius.gameserver.model.actor.holders.player.ClassInfoHolder;
import org.l2jmobius.gameserver.model.events.EventType;
import org.l2jmobius.gameserver.model.events.holders.actor.player.OnPlayerLevelChanged;
import org.l2jmobius.gameserver.model.events.holders.actor.player.OnPlayerLogin;
import org.l2jmobius.gameserver.model.item.Weapon;
import org.l2jmobius.gameserver.model.item.enums.ItemProcessType;
import org.l2jmobius.gameserver.model.item.instance.Item;
import org.l2jmobius.gameserver.model.itemcontainer.Inventory;
import org.l2jmobius.gameserver.model.script.Quest;
import org.l2jmobius.gameserver.model.script.QuestState;
import org.l2jmobius.gameserver.model.spawns.Spawn;
import org.l2jmobius.gameserver.model.zone.ZoneId;
import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;
import org.l2jmobius.gameserver.network.serverpackets.RadarControl;
import org.l2jmobius.gameserver.network.serverpackets.ShowBoard;
import org.l2jmobius.gameserver.network.serverpackets.ShowMiniMap;

/**
 * The Adventurer's Guide: a Community Board section (Alt+B, "Guide") that tells a player what to do next. Every page is
 * built for the player: the quests their level, race and class can take, where to hunt, their next class change, what
 * gear grade to wear, the services of each town, and some tips. Every place can be marked on the radar and map, or
 * reached with a paid teleport to the nearest gatekeeper destination.
 * <p>
 * The data comes from {@code data/*.tsv}, written by {@code tools/guide/build_guide_data.py} from the client's quest
 * table and the server's spawns, gatekeepers and NPCs. The tips are {@code data/tips.txt}.
 */
public class AdventurerGuideModule implements GameModule
{
	private static final String CMD = "_bbs_guide";
	private static final String NAVIGATION_PATH = "data/html/CommunityBoard/Custom/navigation.html";
	private static final int ADENA = 57;
	private static final int QUEST_ROWS = 8;
	private static final int LIST_ROWS = 10;
	private static final int MOB_ROWS = 12;
	/** Go looks for a live monster this far from the group's point, and lands this far from it. */
	private static final int LIVE_MOB_RANGE = 3000;
	private static final int LANDING_OFFSET = 350;
	private static final int TOWN_ROWS = 16;
	private static final int SOON_LEVELS = 5;
	// The board sends a page in at most three 4090-character packets.
	private static final int MAX_HTML = 12270;

	// Expertise: the level each grade opens at, and its shots (index = CrystalType ordinal: NONE, D, C, B, A, S).
	private static final String[] GRADES = { "No-grade", "D", "C", "B", "A", "S" };
	private static final int[] GRADE_LEVELS = { 1, 20, 40, 52, 61, 76 };
	private static final int[] SOULSHOTS = { 1835, 1463, 1464, 1465, 1466, 1467 };
	private static final int[] SPIRITSHOTS = { 2509, 2510, 2511, 2512, 2513, 2514 };
	private static final int[] BLESSED_SPIRITSHOTS = { 3947, 3948, 3949, 3950, 3951, 3952 };
	private static final int NOVICE_SOULSHOT = 5789;
	private static final int NOVICE_SPIRITSHOT = 5790;

	private static final Pattern CLASS_QUEST = Pattern.compile("^(Path to|Trial of|Testimony of|Test of|Saga of)\\b.*");
	private static final Pattern NOBLE_QUEST = Pattern.compile(".*Precious Soul.*|.*Nobility.*");

	private Logger _log;
	private boolean _teleportEnabled;
	private double _feeMultiplier;
	private int _freeTeleportMaxLevel;
	private int _huntBelow;
	private int _huntAbove;

	private final List<QuestInfo> _quests = new ArrayList<>();
	private final Map<Integer, QuestInfo> _questById = new HashMap<>();
	private final List<Tele> _teleports = new ArrayList<>();
	private final List<Area> _areas = new ArrayList<>();
	private final List<Town> _towns = new ArrayList<>();
	private final List<String[]> _tips = new ArrayList<>();

	@Override
	public void onEnable(ModuleContext context)
	{
		if (!context.config().getBoolean("Enabled", false))
		{
			return; // Switch off: register nothing, behave as stock.
		}

		_log = context.logging();
		_teleportEnabled = context.config().getBoolean("TeleportEnabled", true);
		_feeMultiplier = context.config().getDouble("TeleportFeeMultiplier", 1.0);
		_freeTeleportMaxLevel = context.config().getInt("FreeTeleportMaxLevel", 20);
		_huntBelow = context.config().getInt("HuntLevelBelow", 3);
		_huntAbove = context.config().getInt("HuntLevelAbove", 4);

		final Path dataPath = Paths.get(context.config().getString("DataPath", "modules/adventurer-guide/data"));
		try
		{
			load(dataPath);
		}
		catch (IOException | RuntimeException e)
		{
			_log.warning("Adventurer's Guide: could not load " + dataPath.toAbsolutePath().normalize() + ": " + e + ". Run tools/guide/build_guide_data.py.");
			return;
		}

		// ModuleHandlers has no board method, so register the board handler directly.
		CommunityBoardHandler.getInstance().registerHandler(new GuideBoard());
		context.handlers().registerVoicedCommand(new GuideVoicedCommand());

		final int loginHintMaxLevel = context.config().getInt("LoginHintMaxLevel", 40);
		if (loginHintMaxLevel > 0)
		{
			context.events().onPlayers(EventType.ON_PLAYER_LOGIN, (OnPlayerLogin event) -> onLogin(event.getPlayer(), loginHintMaxLevel));
		}
		if (context.config().getBoolean("LevelUpHints", true))
		{
			context.events().onPlayers(EventType.ON_PLAYER_LEVEL_CHANGED, (OnPlayerLevelChanged event) -> onLevelUp(event.getPlayer(), event.getOldLevel(), event.getNewLevel()));
		}

		_log.info("Adventurer's Guide enabled: " + _quests.size() + " quests, " + _areas.size() + " hunting spots, " + _teleports.size() + " teleports, " + _towns.size() + " towns; registered " + CMD + " and .guide");
	}

	// ---------------------------------------------------------------- data

	private static class QuestInfo
	{
		int id;
		String title;
		int lvlMin;
		int lvlMax;
		int type;
		String startNpcName;
		int startNpc;
		int x;
		int y;
		int z;
		String requirement;
		final Set<Integer> classes = new HashSet<>();
		int reqQuest;
		String intro;
		String firstStep;

		boolean isRepeatable()
		{
			return (type == 0) || (type == 2);
		}

		boolean isClanQuest()
		{
			return requirement.toLowerCase().contains("clan");
		}

		boolean needsClanLeader()
		{
			return requirement.contains("Clan Leader");
		}

		/**
		 * @return true for the few quests with no level range that only open under special conditions (PKs, the Seven
		 *         Signs competition). The guide never offers them; the requirement text explains them.
		 */
		boolean isSpecial()
		{
			return (lvlMin == 0) && (lvlMax == 0) && !isClanQuest();
		}

		boolean isClassQuest()
		{
			return !classes.isEmpty() && (classes.size() <= 12) && CLASS_QUEST.matcher(title).matches();
		}
	}

	private static class Tele
	{
		String name;
		int x;
		int y;
		int z;
		int fee;
	}

	private static class Mob
	{
		int npcId;
		String name;
		int level;
		int exp;
		int sp;
		boolean aggro;
		int count;
		final List<int[]> points = new ArrayList<>();
	}

	private static class Area
	{
		int idx;
		String name;
		String region;
		int x;
		int y;
		int z;
		int teleIdx;
		int minLv;
		int maxLv;
		final List<Mob> mobs = new ArrayList<>();
	}

	private static class Service
	{
		String category;
		int npcId;
		String name;
		int x;
		int y;
		int z;
	}

	private static class Town
	{
		int idx;
		String name;
		final List<Service> services = new ArrayList<>();
		int x;
		int y;
		int z;
	}

	private static List<String[]> readTsv(Path file) throws IOException
	{
		final List<String[]> rows = new ArrayList<>();
		for (String line : Files.readAllLines(file, StandardCharsets.UTF_8))
		{
			if (!line.isEmpty() && !line.startsWith("#"))
			{
				rows.add(line.split("\t", -1));
			}
		}
		return rows;
	}

	private static int[] parsePoint(String text)
	{
		final String[] p = text.split(",");
		return new int[]
		{
			Integer.parseInt(p[0]),
			Integer.parseInt(p[1]),
			Integer.parseInt(p[2])
		};
	}

	private void load(Path dir) throws IOException
	{
		for (String[] r : readTsv(dir.resolve("quests.tsv")))
		{
			final QuestInfo q = new QuestInfo();
			q.id = Integer.parseInt(r[0]);
			q.title = r[1];
			q.lvlMin = Integer.parseInt(r[2]);
			q.lvlMax = Integer.parseInt(r[3]);
			q.type = Integer.parseInt(r[4]);
			q.startNpc = Integer.parseInt(r[5]);
			q.startNpcName = r[6];
			q.x = Integer.parseInt(r[7]);
			q.y = Integer.parseInt(r[8]);
			q.z = Integer.parseInt(r[9]);
			q.requirement = r[10];
			for (String c : r[11].split(","))
			{
				if (!c.isEmpty())
				{
					q.classes.add(Integer.parseInt(c));
				}
			}
			q.reqQuest = Integer.parseInt(r[12]);
			q.intro = r[13];
			q.firstStep = r[14];
			_quests.add(q);
			_questById.put(q.id, q);
		}

		for (String[] r : readTsv(dir.resolve("teleports.tsv")))
		{
			final Tele t = new Tele();
			t.name = r[1];
			t.x = Integer.parseInt(r[2]);
			t.y = Integer.parseInt(r[3]);
			t.z = Integer.parseInt(r[4]);
			t.fee = Integer.parseInt(r[5]);
			_teleports.add(t);
		}

		for (String[] r : readTsv(dir.resolve("areas.tsv")))
		{
			final Area a = new Area();
			a.idx = Integer.parseInt(r[0]);
			a.name = r[1];
			a.region = r[2];
			a.x = Integer.parseInt(r[3]);
			a.y = Integer.parseInt(r[4]);
			a.z = Integer.parseInt(r[5]);
			a.teleIdx = Integer.parseInt(r[6]);
			a.minLv = Integer.parseInt(r[7]);
			a.maxLv = Integer.parseInt(r[8]);
			_areas.add(a);
		}

		for (String[] r : readTsv(dir.resolve("area_mobs.tsv")))
		{
			final Mob m = new Mob();
			m.npcId = Integer.parseInt(r[1]);
			m.name = r[2];
			m.level = Integer.parseInt(r[3]);
			m.exp = Integer.parseInt(r[4]);
			m.sp = Integer.parseInt(r[5]);
			m.aggro = r[6].equals("1");
			m.count = Integer.parseInt(r[7]);
			for (String p : r[8].split(";"))
			{
				m.points.add(parsePoint(p));
			}
			_areas.get(Integer.parseInt(r[0])).mobs.add(m);
		}

		final Map<Integer, Town> towns = new LinkedHashMap<>();
		for (String[] r : readTsv(dir.resolve("services.tsv")))
		{
			final Town town = towns.computeIfAbsent(Integer.parseInt(r[0]), idx ->
			{
				final Town t = new Town();
				t.idx = idx;
				t.name = r[1];
				return t;
			});
			final Service s = new Service();
			s.category = r[2];
			s.npcId = Integer.parseInt(r[3]);
			s.name = r[4];
			s.x = Integer.parseInt(r[5]);
			s.y = Integer.parseInt(r[6]);
			s.z = Integer.parseInt(r[7]);
			town.services.add(s);
		}
		for (Town t : towns.values())
		{
			for (Service s : t.services)
			{
				t.x += s.x / t.services.size();
				t.y += s.y / t.services.size();
				t.z += s.z / t.services.size();
			}
			_towns.add(t);
		}

		final Path tips = dir.resolve("tips.txt");
		if (Files.exists(tips))
		{
			StringBuilder body = null;
			for (String line : Files.readAllLines(tips, StandardCharsets.UTF_8))
			{
				if (line.startsWith("# "))
				{
					body = new StringBuilder();
					_tips.add(new String[]
					{
						line.substring(2).trim(),
						""
					});
				}
				else if ((body != null) && !line.startsWith("//"))
				{
					final String[] tip = _tips.get(_tips.size() - 1);
					tip[1] = tip[1] + line + " ";
				}
			}
		}
	}

	// ---------------------------------------------------------------- player state

	private enum Status
	{
		AVAILABLE,
		ACTIVE,
		DONE,
		SOON,
		LOCKED,
		MISSING
	}

	/**
	 * @return where the player stands with the quest. LOCKED means race, class, clan, prerequisite or a level they have
	 *         outgrown keeps them out; MISSING means the server has no script for it.
	 */
	private Status status(Player player, QuestInfo q)
	{
		final Quest quest = ScriptManager.getInstance().getQuest(q.id);
		if (quest == null)
		{
			return Status.MISSING;
		}

		final QuestState qs = player.getQuestState(quest.getName());
		if ((qs != null) && qs.isStarted())
		{
			return Status.ACTIVE;
		}
		if ((qs != null) && qs.isCompleted() && !q.isRepeatable())
		{
			return Status.DONE;
		}
		if (!q.classes.isEmpty() && !q.classes.contains(player.getPlayerClass().getId()))
		{
			return Status.LOCKED;
		}
		if ((q.isClanQuest() && (player.getClan() == null)) || (q.needsClanLeader() && !player.isClanLeader()) || q.isSpecial())
		{
			return Status.LOCKED;
		}
		if ((q.reqQuest > 0) && !isDone(player, q.reqQuest))
		{
			return Status.LOCKED;
		}

		final int level = player.getLevel();
		if ((q.lvlMax > 0) && (level > q.lvlMax))
		{
			return Status.LOCKED;
		}
		if (level < q.lvlMin)
		{
			return (q.lvlMin - level) <= SOON_LEVELS ? Status.SOON : Status.LOCKED;
		}
		return Status.AVAILABLE;
	}

	private static boolean isDone(Player player, int questId)
	{
		final Quest quest = ScriptManager.getInstance().getQuest(questId);
		if (quest == null)
		{
			return true; // The server doesn't have it, so it can't block anything.
		}
		final QuestState qs = player.getQuestState(quest.getName());
		return (qs != null) && qs.isCompleted();
	}

	/**
	 * @return why the player can't take the quest now, or null
	 */
	private String lockReason(Player player, QuestInfo q)
	{
		if (!q.classes.isEmpty() && !q.classes.contains(player.getPlayerClass().getId()))
		{
			return "your race or class can't take it (" + esc(q.requirement) + ")";
		}
		if ((q.isClanQuest() && (player.getClan() == null)) || (q.needsClanLeader() && !player.isClanLeader()))
		{
			return "it needs a clan (" + esc(q.requirement) + ")";
		}
		if (q.isSpecial())
		{
			return "it only opens under special conditions (" + esc(q.requirement) + ")";
		}
		if ((q.reqQuest > 0) && !isDone(player, q.reqQuest))
		{
			final QuestInfo pre = _questById.get(q.reqQuest);
			return "first finish " + (pre == null ? "quest " + q.reqQuest : link(esc(pre.title), "quest " + pre.id));
		}
		if ((q.lvlMax > 0) && (player.getLevel() > q.lvlMax))
		{
			return "you are above its level range";
		}
		if (player.getLevel() < q.lvlMin)
		{
			return "you need level " + q.lvlMin;
		}
		return null;
	}

	private List<QuestInfo> questsWith(Player player, Status wanted)
	{
		final List<QuestInfo> result = new ArrayList<>();
		for (QuestInfo q : _quests)
		{
			if (status(player, q) == wanted)
			{
				result.add(q);
			}
		}
		result.sort(Comparator.comparingDouble((QuestInfo q) -> hasPoint(q.x, q.y) ? player.calculateDistance2D(q.x, q.y, q.z) : Double.MAX_VALUE).thenComparingInt(q -> q.lvlMin));
		return result;
	}

	private static int gradeForLevel(int level)
	{
		int grade = 0;
		for (int i = 0; i < GRADE_LEVELS.length; i++)
		{
			if (level >= GRADE_LEVELS[i])
			{
				grade = i;
			}
		}
		return grade;
	}

	private static int weaponGrade(Player player)
	{
		final Weapon weapon = player.getActiveWeaponItem();
		return weapon == null ? -1 : Math.min(weapon.getCrystalType().ordinal(), GRADES.length - 1);
	}

	private static int armorGrade(Player player)
	{
		final Item chest = player.getInventory().getPaperdollItem(Inventory.PAPERDOLL_CHEST);
		return chest == null ? -1 : Math.min(chest.getTemplate().getCrystalType().ordinal(), GRADES.length - 1);
	}

	private static String className(Player player)
	{
		final ClassInfoHolder info = ClassListData.getInstance().getClass(player.getPlayerClass());
		return info == null ? pretty(player.getPlayerClass().name()) : info.getClassName();
	}

	/**
	 * @return the level of the player's next class change, or 0 when they have all three
	 */
	private static int nextClassLevel(Player player)
	{
		switch (player.getPlayerClass().level())
		{
			case 0:
				return 20;
			case 1:
				return 40;
			case 2:
				return 76;
			default:
				return 0;
		}
	}

	private int fee(Player player, Tele tele)
	{
		return player.getLevel() <= _freeTeleportMaxLevel ? 0 : (int) Math.round(tele.fee * _feeMultiplier);
	}

	private int nearestTele(int x, int y)
	{
		int best = -1;
		double bestDistance = Double.MAX_VALUE;
		for (int i = 0; i < _teleports.size(); i++)
		{
			final Tele t = _teleports.get(i);
			final double d = Math.hypot(t.x - x, t.y - y);
			if (d < bestDistance)
			{
				bestDistance = d;
				best = i;
			}
		}
		return best;
	}

	private static int[] nearestPoint(Player player, List<int[]> points)
	{
		int[] best = null;
		double bestDistance = Double.MAX_VALUE;
		for (int[] p : points)
		{
			final double d = player.calculateDistance2D(p[0], p[1], p[2]);
			if (d < bestDistance)
			{
				bestDistance = d;
				best = p;
			}
		}
		return best;
	}

	private boolean suits(Player player, Mob mob)
	{
		return (mob.level >= (player.getLevel() - _huntBelow)) && (mob.level <= (player.getLevel() + _huntAbove));
	}

	private static boolean hasPoint(int x, int y)
	{
		return (x != 0) || (y != 0);
	}

	// ---------------------------------------------------------------- html helpers

	private static String esc(String text)
	{
		return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
	}

	private static String pretty(String enumName)
	{
		final StringBuilder sb = new StringBuilder();
		for (String word : enumName.toLowerCase().split("_"))
		{
			if (!word.isEmpty())
			{
				sb.append(sb.length() > 0 ? " " : "").append(Character.toUpperCase(word.charAt(0))).append(word.substring(1));
			}
		}
		return sb.toString();
	}

	private static String link(String label, String args)
	{
		return "<a action=\"bypass " + CMD + " " + args + "\">" + label + "</a>";
	}

	private static String button(String label, String bypass)
	{
		return "<button value=\"" + label + "\" action=\"bypass " + bypass + "\" width=114 height=30 back=\"L2UI_CH3.Button.bigbutton2_down\" fore=\"L2UI_CH3.Button.bigbutton2\">";
	}

	private static String color(String hex, String text)
	{
		return "<font color=\"" + hex + "\">" + text + "</font>";
	}

	private static String gray(String text)
	{
		return color("808080", text);
	}

	private static String dist(Player player, int x, int y, int z)
	{
		if (!hasPoint(x, y))
		{
			return gray("?");
		}
		final double d = player.calculateDistance2D(x, y, z);
		if (d < 1000)
		{
			return color("88CC88", "here");
		}
		return d < 10000 ? String.format("%.1fk", d / 1000) : ((int) (d / 1000)) + "k";
	}

	private static String markLink(int x, int y, int z)
	{
		return hasPoint(x, y) ? link("Mark", "mark " + x + " " + y + " " + z) : gray("Mark");
	}

	private String teleLink(Player player, int teleIdx, String label)
	{
		if (!_teleportEnabled || (teleIdx < 0))
		{
			return "";
		}
		final int fee = fee(player, _teleports.get(teleIdx));
		return link(label, "tp " + teleIdx) + (fee > 0 ? gray(" " + fee) : "");
	}

	/**
	 * Colour for a mob's level against the player's: grey gives little XP, green is easy, white is even, yellow is
	 * hard, red is dangerous.
	 */
	private static String levelColor(int mobLevel, int playerLevel)
	{
		final int diff = mobLevel - playerLevel;
		if (diff <= -6)
		{
			return "808080";
		}
		if (diff <= -2)
		{
			return "88CC88";
		}
		if (diff <= 2)
		{
			return "FFFFFF";
		}
		return diff <= 4 ? "FFDD66" : "FF6666";
	}

	private static String pager(String args, int page, int pages)
	{
		if (pages <= 1)
		{
			return "";
		}
		final StringBuilder sb = new StringBuilder("<table width=490><tr><td align=center>");
		sb.append(page > 0 ? link("&lt; Prev", args + " " + (page - 1)) : gray("&lt; Prev"));
		sb.append("&nbsp;&nbsp;&nbsp;Page ").append(page + 1).append(" of ").append(pages).append("&nbsp;&nbsp;&nbsp;");
		sb.append(page < (pages - 1) ? link("Next &gt;", args + " " + (page + 1)) : gray("Next &gt;"));
		return sb.append("</td></tr></table>").toString();
	}

	private static int pages(int rows, int perPage)
	{
		return Math.max(1, ((rows + perPage) - 1) / perPage);
	}

	private static int clampPage(int page, int pages)
	{
		return Math.max(0, Math.min(page, pages - 1));
	}

	private static final String[][] MENU =
	{
		{ "Home", "home" },
		{ "Quests", "quests avail 0" },
		{ "Hunt", "hunt 0" },
		{ "Next steps", "next" },
		{ "Gear", "gear" },
		{ "Towns", "towns" },
		{ "Tips", "tips" }
	};

	private void send(Player player, String title, String body)
	{
		final StringBuilder sb = new StringBuilder(8192);
		sb.append("<html><body><table width=700><tr><td height=10></td></tr></table>");
		sb.append("<table width=20><tr><td>%navigation%</td><td><center>");
		sb.append("<table bgcolor=\"000000\" width=500 height=415><tr><td valign=top width=500>");
		sb.append("<table width=500><tr><td height=22 align=center><font color=\"CDB67F\">Adventurer's Guide</font>");
		sb.append(gray(" - " + title)).append("</td></tr></table><table width=500><tr>");
		for (String[] item : MENU)
		{
			sb.append("<td align=center>").append(item[0].equals(title) ? color("LEVEL", item[0]) : link(item[0], item[1])).append("</td>");
		}
		sb.append("</tr></table><img src=\"L2UI.SquareGray\" width=500 height=1><br1>");
		sb.append(body);
		sb.append("</td></tr></table>");
		sb.append("<table border=0 cellpadding=0 cellspacing=0 width=500><tr><td height=10></td></tr></table>");
		sb.append("<table border=0 bgcolor=\"000000\" cellpadding=0 cellspacing=0 width=500>");
		sb.append("<tr><td height=30 align=center><font color=696969>Alt+B - Guide&nbsp;&nbsp;&nbsp;or type .guide</font></td></tr>");
		sb.append("</table></center></td></tr></table></body></html>");

		String html = sb.toString();
		final String navigation = CommunityBoardConfig.CUSTOM_CB_ENABLED ? HtmCache.getInstance().getHtm(player, NAVIGATION_PATH) : null;
		html = html.replace("%navigation%", navigation == null ? "" : navigation);
		if (html.length() > MAX_HTML)
		{
			_log.warning("Adventurer's Guide: page '" + title + "' is " + html.length() + " characters, over the board limit of " + MAX_HTML + ".");
			player.sendMessage("Adventurer's Guide: that page is too long to show.");
			return;
		}
		CommunityBoardHandler.separateAndSend(html, player);
	}

	// ---------------------------------------------------------------- pages

	private void showHome(Player player)
	{
		final int level = player.getLevel();
		final StringBuilder sb = new StringBuilder();
		sb.append("<table width=490><tr><td>");
		sb.append("Welcome, ").append(color("LEVEL", player.getName())).append("! ");
		sb.append(pretty(player.getRace().name())).append(" ").append(esc(className(player))).append(", level ").append(level).append(".<br1>");

		final int next = nextClassLevel(player);
		if (next == 0)
		{
			sb.append(gray("You have all three class changes. Subclasses and noblesse are next."));
		}
		else if (level >= next)
		{
			sb.append(color("FFDD66", "You can make your next class change now!")).append(" ").append(link("See how", "next"));
		}
		else
		{
			sb.append(gray((next - level) + " level" + ((next - level) == 1 ? "" : "s") + " to your next class change (level " + next + ")."));
		}
		sb.append("</td></tr></table><br1>");

		sb.append("<table width=490><tr>");
		sb.append("<td align=center>").append(button("Quests for you", CMD + " quests avail 0")).append("</td>");
		sb.append("<td align=center>").append(button("Where to hunt", CMD + " hunt 0")).append("</td>");
		sb.append("<td align=center>").append(button("Next steps", CMD + " next")).append("</td>");
		sb.append("</tr><tr>");
		sb.append("<td align=center>").append(button("Gear by grade", CMD + " gear")).append("</td>");
		sb.append("<td align=center>").append(button("Towns", CMD + " towns")).append("</td>");
		sb.append("<td align=center>").append(button("Tips", CMD + " tips")).append("</td>");
		sb.append("</tr></table><br1>");

		// Right now: the nearest quests, the best spot, and anything wrong with the player's kit.
		sb.append(color("B09B79", "Right now")).append("<br1><table width=490>");
		final List<QuestInfo> available = questsWith(player, Status.AVAILABLE);
		for (int i = 0; i < Math.min(3, available.size()); i++)
		{
			final QuestInfo q = available.get(i);
			sb.append("<tr><td width=60>").append(gray("Quest")).append("</td><td width=280>").append(link(esc(q.title), "quest " + q.id));
			sb.append("</td><td width=60 align=right>").append(dist(player, q.x, q.y, q.z)).append("</td><td width=90 align=right>").append(markLink(q.x, q.y, q.z)).append("</td></tr>");
		}
		if (available.isEmpty())
		{
			sb.append("<tr><td>").append(gray("No quest fits your level right now. Check ")).append(link("Coming soon", "quests soon 0")).append(gray(".")).append("</td></tr>");
		}

		final List<Object[]> spots = huntSpots(player);
		if (!spots.isEmpty())
		{
			final Area a = (Area) spots.get(0)[0];
			final int[] p = (int[]) spots.get(0)[1];
			sb.append("<tr><td width=60>").append(gray("Hunt")).append("</td><td width=280>").append(link(esc(a.name), "area " + a.idx + " -1"));
			sb.append("</td><td width=60 align=right>").append(dist(player, p[0], p[1], p[2])).append("</td><td width=90 align=right>").append(markLink(p[0], p[1], p[2])).append("</td></tr>");
		}
		sb.append("</table><br1>");

		final List<String> warnings = kitWarnings(player);
		if (!warnings.isEmpty())
		{
			sb.append(color("B09B79", "Check your kit")).append("<br1>");
			for (String w : warnings)
			{
				sb.append(color("FFDD66", "- ")).append(w).append("<br1>");
			}
		}
		send(player, "Home", sb.toString());
	}

	private List<String> kitWarnings(Player player)
	{
		final List<String> warnings = new ArrayList<>();
		final int canWear = gradeForLevel(player.getLevel());
		final int weapon = weaponGrade(player);
		if (weapon < 0)
		{
			warnings.add("You have no weapon equipped.");
		}
		else
		{
			final boolean mage = player.getPlayerClass().isMage();
			final int shots = mage ? player.getInventory().getInventoryItemCount(SPIRITSHOTS[weapon], -1) + player.getInventory().getInventoryItemCount(BLESSED_SPIRITSHOTS[weapon], -1) : player.getInventory().getInventoryItemCount(SOULSHOTS[weapon], -1);
			final int novice = (weapon == 0) ? player.getInventory().getInventoryItemCount(mage ? NOVICE_SPIRITSHOT : NOVICE_SOULSHOT, -1) : 0;
			if ((shots + novice) == 0)
			{
				warnings.add("No " + (mage ? "spiritshots" : "soulshots") + " for your " + GRADES[weapon] + " weapon. A Grocer sells them: " + link("Towns", "towns") + ".");
			}
			if (weapon < canWear)
			{
				warnings.add("Your weapon is " + GRADES[weapon] + "-grade; you can use " + GRADES[canWear] + "-grade now. " + link("Gear", "gear"));
			}
		}
		final int armor = armorGrade(player);
		if ((armor >= 0) && (armor < canWear))
		{
			warnings.add("Your armor is " + GRADES[armor] + "-grade; you can wear " + GRADES[canWear] + "-grade now.");
		}
		return warnings;
	}

	private void showQuests(Player player, String tab, int page)
	{
		final Status status;
		switch (tab)
		{
			case "active":
				status = Status.ACTIVE;
				break;
			case "soon":
				status = Status.SOON;
				break;
			case "done":
				status = Status.DONE;
				break;
			default:
				tab = "avail";
				status = Status.AVAILABLE;
				break;
		}

		final Map<Status, Integer> counts = new HashMap<>();
		for (QuestInfo q : _quests)
		{
			counts.merge(status(player, q), 1, Integer::sum);
		}

		final StringBuilder sb = new StringBuilder("<table width=490><tr>");
		final String[][] tabs =
		{
			{ "avail", "Available" },
			{ "active", "In progress" },
			{ "soon", "Coming soon" },
			{ "done", "Done" }
		};
		final Status[] tabStatus = { Status.AVAILABLE, Status.ACTIVE, Status.SOON, Status.DONE };
		for (int i = 0; i < tabs.length; i++)
		{
			final String label = tabs[i][1] + " (" + counts.getOrDefault(tabStatus[i], 0) + ")";
			sb.append("<td align=center>").append(tabs[i][0].equals(tab) ? color("LEVEL", label) : link(label, "quests " + tabs[i][0] + " 0")).append("</td>");
		}
		sb.append("</tr></table><br1>");

		final List<QuestInfo> list = questsWith(player, status);
		final int pages = pages(list.size(), QUEST_ROWS);
		page = clampPage(page, pages);
		if (list.isEmpty())
		{
			sb.append(gray(status == Status.AVAILABLE ? "No quest fits you right now. Try Coming soon, or level up a little." : "Nothing here yet."));
		}
		else
		{
			sb.append(gray(status == Status.SOON ? "Quests you can take within " + SOON_LEVELS + " levels. Nearest first." : "Nearest first. Click a title for details, Mark to put its start NPC on your map.")).append("<br1>");
			sb.append("<table width=490>");
			for (int i = page * QUEST_ROWS; i < Math.min(list.size(), (page + 1) * QUEST_ROWS); i++)
			{
				final QuestInfo q = list.get(i);
				sb.append("<tr><td width=260>").append(link(esc(q.title), "quest " + q.id)).append("</td>");
				sb.append("<td width=70>Lv ").append(q.lvlMin).append(q.lvlMax > 0 ? "-" + q.lvlMax : "+").append("</td>");
				sb.append("<td width=60 align=right>").append(dist(player, q.x, q.y, q.z)).append("</td>");
				sb.append("<td width=100 align=right>").append(markLink(q.x, q.y, q.z)).append("</td></tr>");
				sb.append("<tr><td width=260>").append(gray(esc(q.startNpcName))).append("</td><td width=230 colspan=3>").append(gray(tags(q))).append("</td></tr>");
			}
			sb.append("</table>");
			sb.append(pager("quests " + tab, page, pages));
		}
		send(player, "Quests", sb.toString());
	}

	private static String tags(QuestInfo q)
	{
		final List<String> tags = new ArrayList<>();
		tags.add(q.isRepeatable() ? "Repeatable" : "One-time");
		if (q.isClassQuest())
		{
			tags.add("Class change");
		}
		else if (!q.classes.isEmpty())
		{
			tags.add(esc(q.requirement));
		}
		if (q.isClanQuest())
		{
			tags.add("Clan");
		}
		return String.join(", ", tags);
	}

	private void showQuest(Player player, int questId)
	{
		final QuestInfo q = _questById.get(questId);
		if (q == null)
		{
			showQuests(player, "avail", 0);
			return;
		}

		final Status status = status(player, q);
		final StringBuilder sb = new StringBuilder("<table width=490><tr><td>");
		sb.append(color("LEVEL", esc(q.title))).append("<br1>");
		sb.append(gray("Level " + q.lvlMin + (q.lvlMax > 0 ? "-" + q.lvlMax : "+") + ", " + tags(q) + ". Requirement: " + esc(q.requirement))).append("<br1>");
		switch (status)
		{
			case AVAILABLE:
				sb.append(color("88CC88", "You can take this quest."));
				break;
			case ACTIVE:
				sb.append(color("88CC88", "In progress.")).append(gray(" Alt+U shows your current step."));
				break;
			case DONE:
				sb.append(gray("You have finished this quest."));
				break;
			case MISSING:
				sb.append(color("FF6666", "This server has no script for this quest."));
				break;
			default:
				sb.append(color("FFDD66", "Not yet: " + lockReason(player, q) + "."));
				break;
		}
		sb.append("<br><font color=\"B09B79\">Story</font><br1>").append(esc(q.intro)).append("<br>");
		if (!q.firstStep.isEmpty())
		{
			sb.append("<font color=\"B09B79\">First step</font><br1>").append(esc(q.firstStep)).append("<br>");
		}
		sb.append("<font color=\"B09B79\">Start</font><br1>Talk to ").append(color("LEVEL", esc(q.startNpcName))).append(" (").append(dist(player, q.x, q.y, q.z)).append(" away).");
		sb.append("</td></tr></table><br1><table width=490><tr>");

		final String mark = hasPoint(q.x, q.y) ? CMD + " mark " + q.x + " " + q.y + " " + q.z : CMD + " npc " + q.startNpc;
		sb.append("<td align=center>").append(button("Mark on map", mark)).append("</td>");
		final int tele = hasPoint(q.x, q.y) ? nearestTele(q.x, q.y) : -1;
		if (_teleportEnabled && (tele >= 0) && (player.calculateDistance2D(q.x, q.y, q.z) > 3000))
		{
			sb.append("<td align=center>").append(button("Teleport near", CMD + " tp " + tele)).append("</td>");
		}
		if (CommunityBoardHandler.getInstance().getHandler("_bbs_questnav") != null)
		{
			sb.append("<td align=center>").append(button("NPCs and mobs", "_bbs_questnav step root." + q.id)).append("</td>");
		}
		sb.append("</tr></table>");
		if (_teleportEnabled && (tele >= 0))
		{
			final int fee = fee(player, _teleports.get(tele));
			sb.append("<center>").append(gray("Teleport goes to " + esc(_teleports.get(tele).name) + (fee > 0 ? " for " + fee + " Adena." : ", free at your level."))).append("</center>");
		}
		sb.append("<br1><center>").append(link("Back to quests", "quests avail 0")).append("</center>");
		send(player, "Quests", sb.toString());
	}

	/**
	 * @return spots with mobs for the player's level, best first: each is {Area, nearest suitable point, suitable spawns,
	 *         min level, max level, any aggressive}
	 */
	private List<Object[]> huntSpots(Player player)
	{
		final List<Object[]> spots = new ArrayList<>();
		for (Area a : _areas)
		{
			int spawns = 0;
			int kinds = 0;
			int min = Integer.MAX_VALUE;
			int max = 0;
			boolean aggro = false;
			final List<int[]> points = new ArrayList<>();
			for (Mob m : a.mobs)
			{
				if (suits(player, m))
				{
					spawns += m.count;
					kinds++;
					min = Math.min(min, m.level);
					max = Math.max(max, m.level);
					aggro |= m.aggro;
					points.addAll(m.points);
				}
			}
			if ((kinds >= 2) || (spawns >= 8))
			{
				spots.add(new Object[]
				{
					a,
					nearestPoint(player, points),
					spawns,
					min,
					max,
					aggro
				});
			}
		}
		// Nearest first, but a spot with many more mobs is worth a walk: rank by distance divided by a crowd bonus.
		spots.sort(Comparator.comparingDouble(s ->
		{
			final int[] p = (int[]) s[1];
			return player.calculateDistance2D(p[0], p[1], p[2]) / Math.sqrt((int) s[2]);
		}));
		return spots;
	}

	private void showHunt(Player player, int page)
	{
		final List<Object[]> spots = huntSpots(player);
		final int pages = pages(spots.size(), LIST_ROWS);
		page = clampPage(page, pages);

		final StringBuilder sb = new StringBuilder();
		sb.append(gray("Spots with monsters of level " + Math.max(1, player.getLevel() - _huntBelow) + "-" + (player.getLevel() + _huntAbove) + ", close and busy ones first. "));
		sb.append(color("FF6666", "Aggro")).append(gray(" mobs attack on sight.")).append("<br1>");
		if (spots.isEmpty())
		{
			sb.append(gray("No spot found for your level."));
		}
		else
		{
			sb.append("<table width=490><tr><td width=210>").append(gray("Spot")).append("</td><td width=60>").append(gray("Mobs")).append("</td><td width=50>").append(gray("")).append("</td><td width=50 align=right>").append(gray("Dist")).append("</td><td width=120 align=right></td></tr>");
			for (int i = page * LIST_ROWS; i < Math.min(spots.size(), (page + 1) * LIST_ROWS); i++)
			{
				final Object[] s = spots.get(i);
				final Area a = (Area) s[0];
				final int[] p = (int[]) s[1];
				final int min = (int) s[3];
				final int max = (int) s[4];
				sb.append("<tr><td width=210>").append(link(esc(a.name), "area " + a.idx + " -1")).append("</td>");
				sb.append("<td width=60>Lv ").append(min).append(min == max ? "" : "-" + max).append("</td>");
				sb.append("<td width=50>").append(((boolean) s[5]) ? color("FF6666", "Aggro") : "").append("</td>");
				sb.append("<td width=50 align=right>").append(dist(player, p[0], p[1], p[2])).append("</td>");
				sb.append("<td width=120 align=right>").append(markLink(p[0], p[1], p[2])).append(" ").append(teleLink(player, a.teleIdx, "Teleport")).append("</td></tr>");
			}
			sb.append("</table>");
			sb.append(pager("hunt", page, pages));
		}
		send(player, "Hunt", sb.toString());
	}

	private void showArea(Player player, int areaIdx, int page)
	{
		if ((areaIdx < 0) || (areaIdx >= _areas.size()))
		{
			showHunt(player, 0);
			return;
		}

		final Area a = _areas.get(areaIdx);
		final List<Mob> mobs = new ArrayList<>(a.mobs);
		mobs.sort(Comparator.comparingInt((Mob m) -> m.level).thenComparing(m -> m.name));
		final int pages = pages(mobs.size(), MOB_ROWS);
		if (page < 0)
		{
			// Open on the page with the first mob for the player's level.
			page = 0;
			for (int i = 0; i < mobs.size(); i++)
			{
				if (mobs.get(i).level >= (player.getLevel() - _huntBelow))
				{
					page = i / MOB_ROWS;
					break;
				}
			}
		}
		page = clampPage(page, pages);

		final StringBuilder sb = new StringBuilder("<table width=490><tr><td>");
		sb.append(color("LEVEL", esc(a.name))).append(gray(" (" + esc(a.region) + "), monsters level " + a.minLv + "-" + a.maxLv + ".")).append("<br1>");
		sb.append(gray("Level colours: ")).append(color("808080", "too weak ")).append(color("88CC88", "easy ")).append(color("FFFFFF", "even ")).append(color("FFDD66", "hard ")).append(color("FF6666", "dangerous"));
		sb.append(gray(". A red name attacks on sight. Mark shows the nearest group"));
		sb.append(gray(_teleportEnabled ? "; Go takes you beside it" + (_freeTeleportMaxLevel > 0 ? " (free up to level " + _freeTeleportMaxLevel + ")." : ".") : ".")).append("</td></tr></table><br1>");
		sb.append("<table width=490><tr><td width=180>").append(gray("Monster")).append("</td><td width=35>").append(gray("Lv")).append("</td><td width=65 align=right>").append(gray("Base XP")).append("</td><td width=50 align=right>").append(gray("SP")).append("</td><td width=45 align=right>").append(gray("Count")).append("</td><td width=115 align=right></td></tr>");
		for (int i = page * MOB_ROWS; i < Math.min(mobs.size(), (page + 1) * MOB_ROWS); i++)
		{
			final Mob m = mobs.get(i);
			final int[] p = nearestPoint(player, m.points);
			sb.append("<tr><td width=180>").append(m.aggro ? color("FF6666", esc(m.name)) : esc(m.name)).append("</td>");
			sb.append("<td width=35>").append(color(levelColor(m.level, player.getLevel()), String.valueOf(m.level))).append("</td>");
			sb.append("<td width=65 align=right>").append(m.exp).append("</td><td width=50 align=right>").append(m.sp).append("</td><td width=45 align=right>").append(m.count).append("</td>");
			sb.append("<td width=115 align=right>");
			if ((p != null) && hasPoint(p[0], p[1]))
			{
				sb.append(markLink(p[0], p[1], p[2]));
				if (_teleportEnabled)
				{
					final int fee = goFee(player, p);
					sb.append("&nbsp;&nbsp;").append(link("Go", "go " + a.idx + " " + m.npcId)).append(fee > 0 ? gray(" " + fee) : "");
				}
			}
			sb.append("</td></tr>");
		}
		sb.append("</table>");
		sb.append(pager("area " + a.idx, page, pages));
		if (_teleportEnabled)
		{
			sb.append("<center>").append(gray("Go lands among the monsters, so red names attack at once.")).append("</center>");
		}
		sb.append("<br1><center>");
		if (_teleportEnabled && (a.teleIdx >= 0))
		{
			final Tele t = _teleports.get(a.teleIdx);
			final int fee = fee(player, t);
			sb.append(link("Teleport near", "tp " + a.teleIdx)).append(gray(" (" + esc(t.name) + (fee > 0 ? ", " + fee + " Adena" : ", free") + ")")).append("&nbsp;&nbsp;&nbsp;");
		}
		sb.append(link("Back to spots", "hunt 0")).append("</center>");
		send(player, "Hunt", sb.toString());
	}

	private void showNext(Player player)
	{
		final int level = player.getLevel();
		final PlayerClass pc = player.getPlayerClass();
		final StringBuilder sb = new StringBuilder("<table width=490><tr><td>");
		sb.append("You are a ").append(color("LEVEL", esc(className(player)))).append(" (class tier ").append(pc.level()).append(" of 3), level ").append(level).append(".<br1>");

		final int next = nextClassLevel(player);
		if (next == 20)
		{
			sb.append(gray("1st class change at level 20: finish the \"Path to\" quest of the class you want. It gives a mark; then talk to a Class Master of your race in town. Pick one:"));
		}
		else if (next == 40)
		{
			sb.append(gray("2nd class change at level 40: collect 3 marks from the Trial, Testimony and Test quests of your class, then talk to a Class Master of your race in a big town."));
		}
		else if (next == 76)
		{
			sb.append(gray("3rd class change at level 76: finish the Saga quest of your class."));
		}
		else
		{
			sb.append(gray("You have your final class. Next: a subclass from level 75 and noblesse (the Possessor of a Precious Soul quests)."));
		}
		sb.append("</td></tr></table><br1>");

		// Class quests this class can take, soonest first.
		final List<QuestInfo> classQuests = new ArrayList<>();
		for (QuestInfo q : _quests)
		{
			if (q.isClassQuest() && q.classes.contains(pc.getId()) && (status(player, q) != Status.MISSING))
			{
				classQuests.add(q);
			}
		}
		classQuests.sort(Comparator.comparingInt((QuestInfo q) -> q.lvlMin).thenComparing(q -> q.title));
		appendQuestTable(sb, player, "Class quests", classQuests);

		if (next == 0)
		{
			final List<QuestInfo> noble = new ArrayList<>();
			for (QuestInfo q : _quests)
			{
				if (NOBLE_QUEST.matcher(q.title).matches() && (status(player, q) != Status.MISSING))
				{
					noble.add(q);
				}
			}
			appendQuestTable(sb, player, "Noblesse", noble);
		}

		// Class Masters of the nearest town that has any.
		final Town town = nearestTown(player, "Class Master");
		if (town != null)
		{
			sb.append(color("B09B79", "Class Masters in " + esc(town.name))).append("<br1><table width=490>");
			int shown = 0;
			for (Service s : town.services)
			{
				if (s.category.equals("Class Master") && (shown++ < 6))
				{
					sb.append("<tr><td width=320>").append(esc(s.name)).append("</td><td width=70 align=right>").append(dist(player, s.x, s.y, s.z)).append("</td><td width=100 align=right>").append(markLink(s.x, s.y, s.z)).append("</td></tr>");
				}
			}
			sb.append("</table>");
		}
		send(player, "Next steps", sb.toString());
	}

	private void appendQuestTable(StringBuilder sb, Player player, String title, List<QuestInfo> quests)
	{
		if (quests.isEmpty())
		{
			return;
		}
		sb.append(color("B09B79", title)).append("<br1><table width=490>");
		for (QuestInfo q : quests)
		{
			final Status s = status(player, q);
			final String state;
			switch (s)
			{
				case AVAILABLE:
					state = color("88CC88", "Ready");
					break;
				case ACTIVE:
					state = color("88CC88", "In progress");
					break;
				case DONE:
					state = gray("Done");
					break;
				default:
					state = color("FFDD66", "Lv " + q.lvlMin);
					break;
			}
			sb.append("<tr><td width=250>").append(link(esc(q.title), "quest " + q.id)).append("</td><td width=80>").append(state).append("</td><td width=60 align=right>").append(dist(player, q.x, q.y, q.z)).append("</td><td width=100 align=right>").append(markLink(q.x, q.y, q.z)).append("</td></tr>");
		}
		sb.append("</table><br1>");
	}

	private Town nearestTown(Player player, String withCategory)
	{
		Town best = null;
		double bestDistance = Double.MAX_VALUE;
		for (Town t : _towns)
		{
			boolean has = withCategory == null;
			for (Service s : t.services)
			{
				has |= s.category.equals(withCategory);
			}
			final double d = player.calculateDistance2D(t.x, t.y, t.z);
			if (has && (d < bestDistance))
			{
				bestDistance = d;
				best = t;
			}
		}
		return best;
	}

	private void showGear(Player player)
	{
		final int canWear = gradeForLevel(player.getLevel());
		final int weapon = weaponGrade(player);
		final int armor = armorGrade(player);
		final boolean mage = player.getPlayerClass().isMage();

		final StringBuilder sb = new StringBuilder("<table width=490><tr><td>");
		sb.append("At level ").append(player.getLevel()).append(" you can use ").append(color("LEVEL", GRADES[canWear] + "-grade")).append(" gear without a penalty.<br1>");
		sb.append(gray("Weapon: ")).append(weapon < 0 ? "none" : GRADES[weapon] + "-grade").append(gray("&nbsp;&nbsp;&nbsp;Armor: ")).append(armor < 0 ? "none" : GRADES[armor] + "-grade").append("<br1>");
		sb.append(gray("Higher grades hit harder but give a big penalty until you reach their level. Shots must match your weapon's grade."));
		sb.append("</td></tr></table><br1>");

		sb.append("<table width=490><tr><td width=90>").append(gray("Grade")).append("</td><td width=70>").append(gray("From Lv")).append("</td><td width=160>").append(gray(mage ? "Your spiritshot" : "Your soulshot")).append("</td><td width=170>").append(gray("")).append("</td></tr>");
		for (int g = 0; g < GRADES.length; g++)
		{
			final String name = GRADES[g] + (g == 0 ? "" : "-grade");
			final int shot = mage ? BLESSED_SPIRITSHOTS[g] : SOULSHOTS[g];
			final int have = player.getInventory().getInventoryItemCount(shot, -1) + (mage ? player.getInventory().getInventoryItemCount(SPIRITSHOTS[g], -1) : 0);
			final String note = g == canWear ? color("88CC88", "your grade now") : (g == (canWear + 1) ? gray("next, at level " + GRADE_LEVELS[g]) : "");
			sb.append("<tr><td width=90>").append(g == canWear ? color("LEVEL", name) : name).append("</td><td width=70>").append(GRADE_LEVELS[g]).append("</td>");
			sb.append("<td width=160>&#").append(shot).append("; ").append(have > 0 ? gray("(" + have + ")") : "").append("</td><td width=170>").append(note).append("</td></tr>");
		}
		sb.append("</table><br>");

		sb.append("<table width=490><tr>");
		sb.append("<td align=center>").append(button("Merchant", "_bbstop;merchant/main.html")).append("</td>");
		sb.append("<td align=center>").append(button("Cash Shop", "_bbstop;cashshop/main.html")).append("</td>");
		sb.append("<td align=center>").append(button("Drop Search", "_bbstop;dropsearch/main.html")).append("</td>");
		sb.append("</tr></table><br1><center>").append(gray("Shots and potions: any Grocer in town. Weapons and armor: the town's Weapon and Armor traders.")).append("</center>");
		send(player, "Gear", sb.toString());
	}

	private void showTowns(Player player)
	{
		final List<Town> towns = new ArrayList<>(_towns);
		towns.sort(Comparator.comparingDouble(t -> player.calculateDistance2D(t.x, t.y, t.z)));
		final StringBuilder sb = new StringBuilder();
		sb.append(gray("Every town's gatekeeper, warehouse, shops and masters. Nearest first.")).append("<br1><table width=490>");
		for (Town t : towns)
		{
			final int tele = nearestTele(t.x, t.y);
			sb.append("<tr><td width=220>").append(link(esc(t.name), "town " + t.idx + " 0")).append("</td><td width=80 align=right>").append(dist(player, t.x, t.y, t.z)).append("</td>");
			sb.append("<td width=190 align=right>").append(player.calculateDistance2D(t.x, t.y, t.z) > 3000 ? teleLink(player, tele, "Teleport") : gray("you are here")).append("</td></tr>");
		}
		sb.append("</table>");
		send(player, "Towns", sb.toString());
	}

	private void showTown(Player player, int townIdx, int page)
	{
		Town town = null;
		for (Town t : _towns)
		{
			if (t.idx == townIdx)
			{
				town = t;
			}
		}
		if (town == null)
		{
			showTowns(player);
			return;
		}

		final int pages = pages(town.services.size(), TOWN_ROWS);
		page = clampPage(page, pages);
		final StringBuilder sb = new StringBuilder();
		sb.append(color("LEVEL", esc(town.name))).append(gray(" - click Mark to put an NPC on your map.")).append("<br1><table width=490>");
		String lastCategory = "";
		for (int i = page * TOWN_ROWS; i < Math.min(town.services.size(), (page + 1) * TOWN_ROWS); i++)
		{
			final Service s = town.services.get(i);
			sb.append("<tr><td width=110>").append(s.category.equals(lastCategory) ? "" : color("B09B79", s.category)).append("</td>");
			sb.append("<td width=240>").append(esc(s.name)).append("</td><td width=60 align=right>").append(dist(player, s.x, s.y, s.z)).append("</td><td width=80 align=right>").append(markLink(s.x, s.y, s.z)).append("</td></tr>");
			lastCategory = s.category;
		}
		sb.append("</table>");
		sb.append(pager("town " + town.idx, page, pages));
		sb.append("<br1><center>");
		if (player.calculateDistance2D(town.x, town.y, town.z) > 3000)
		{
			sb.append(teleLink(player, nearestTele(town.x, town.y), "Teleport here")).append("&nbsp;&nbsp;&nbsp;");
		}
		sb.append(link("All towns", "towns")).append("</center>");
		send(player, "Towns", sb.toString());
	}

	private void showTips(Player player, int index)
	{
		final StringBuilder sb = new StringBuilder();
		if ((index < 0) || (index >= _tips.size()))
		{
			sb.append(gray("Short answers to the questions every new adventurer has.")).append("<br><table width=490>");
			for (int i = 0; i < _tips.size(); i++)
			{
				sb.append("<tr><td>").append(color("B09B79", (i + 1) + ".")).append(" ").append(link(_tips.get(i)[0], "tips " + i)).append("</td></tr>");
			}
			sb.append("</table>");
		}
		else
		{
			sb.append("<table width=490><tr><td>").append(color("LEVEL", _tips.get(index)[0])).append("<br1>").append(_tips.get(index)[1]).append("</td></tr></table><br><center>");
			if (index > 0)
			{
				sb.append(link("&lt; " + _tips.get(index - 1)[0], "tips " + (index - 1))).append("&nbsp;&nbsp;&nbsp;");
			}
			sb.append(link("All tips", "tips"));
			if (index < (_tips.size() - 1))
			{
				sb.append("&nbsp;&nbsp;&nbsp;").append(link(_tips.get(index + 1)[0] + " &gt;", "tips " + (index + 1)));
			}
			sb.append("</center>");
		}
		send(player, "Tips", sb.toString());
	}

	// ---------------------------------------------------------------- actions

	/**
	 * Puts the radar marker and map flag on a point, the way the Quest Navigator does.
	 */
	private static void mark(Player player, int x, int y, int z)
	{
		player.getRadar().removeAllMarkers();
		player.sendPacket(new ShowMiniMap(-1));
		ThreadPool.schedule(() ->
		{
			player.getRadar().addMarker(x, y, z);
			player.sendPacket(new RadarControl(0, 2, x, y, z));
		}, 500);
		player.sendMessage("Adventurer's Guide: marked on your radar and map, about " + (int) player.calculateDistance2D(x, y, z) + " away.");
	}

	/**
	 * Marks the nearest spawn of an NPC the data has no point for: its spawn table entry, or a live one in the world.
	 */
	private static void markNpc(Player player, int npcId)
	{
		int[] best = null;
		double bestDistance = Double.MAX_VALUE;
		for (Spawn spawn : SpawnTable.getInstance().getSpawns(npcId))
		{
			final Npc npc = spawn.getLastSpawn();
			final int x = (npc != null) && npc.isSpawned() ? npc.getX() : spawn.getX();
			final int y = (npc != null) && npc.isSpawned() ? npc.getY() : spawn.getY();
			final int z = (npc != null) && npc.isSpawned() ? npc.getZ() : spawn.getZ();
			final double d = player.calculateDistance2D(x, y, z);
			if (hasPoint(x, y) && (d < bestDistance))
			{
				bestDistance = d;
				best = new int[]
				{
					x,
					y,
					z
				};
			}
		}
		if (best == null)
		{
			for (WorldObject object : World.getInstance().getVisibleObjects())
			{
				if (object.isNpc() && (((Npc) object).getId() == npcId))
				{
					final double d = player.calculateDistance2D(object.getX(), object.getY(), object.getZ());
					if (d < bestDistance)
					{
						bestDistance = d;
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
			player.sendMessage("Adventurer's Guide: that NPC has no fixed spot in the world.");
			return;
		}
		mark(player, best[0], best[1], best[2]);
	}

	private void teleport(Player player, int teleIdx)
	{
		if (!_teleportEnabled || (teleIdx < 0) || (teleIdx >= _teleports.size()) || !canTeleport(player))
		{
			return;
		}
		final Tele tele = _teleports.get(teleIdx);
		doTeleport(player, tele.x, tele.y, tele.z, fee(player, tele), tele.name);
	}

	/**
	 * The fee for Go to a mob group: the fee of the gatekeeper destination nearest that group.
	 */
	private int goFee(Player player, int[] point)
	{
		final int teleIdx = nearestTele(point[0], point[1]);
		return teleIdx < 0 ? 0 : fee(player, _teleports.get(teleIdx));
	}

	/**
	 * Teleports the player beside the group of a spot's monster that Mark flags.
	 */
	private void goToMob(Player player, int areaIdx, int npcId)
	{
		if (!_teleportEnabled || (areaIdx < 0) || (areaIdx >= _areas.size()))
		{
			return;
		}
		Mob mob = null;
		for (Mob m : _areas.get(areaIdx).mobs)
		{
			if (m.npcId == npcId)
			{
				mob = m;
				break;
			}
		}
		final int[] point = mob == null ? null : nearestPoint(player, mob.points);
		if ((point == null) || !hasPoint(point[0], point[1]))
		{
			showArea(player, areaIdx, -1);
			return;
		}
		if (!canTeleport(player))
		{
			return;
		}
		final int[] spot = landingSpot(npcId, point);
		if (doTeleport(player, spot[0], spot[1], spot[2], goFee(player, point), mob.name))
		{
			player.sendMessage("Adventurer's Guide: you're next to " + mob.name + " (level " + mob.level + ").");
		}
	}

	/**
	 * Where Go lands: a short way from the live monster nearest the group's point, on the side facing the nearest
	 * gatekeeper, kept on this side of any wall. With no live monster, the point itself on the ground.
	 */
	private int[] landingSpot(int npcId, int[] point)
	{
		Npc best = null;
		double bestDistance = LIVE_MOB_RANGE;
		for (WorldObject object : World.getInstance().getVisibleObjects())
		{
			if (object.isNpc() && (((Npc) object).getId() == npcId))
			{
				final Npc npc = (Npc) object;
				if (npc.isDead() || (npc.getInstanceId() != 0))
				{
					continue;
				}
				final double d = Math.hypot(npc.getX() - point[0], npc.getY() - point[1]);
				if (d < bestDistance)
				{
					bestDistance = d;
					best = npc;
				}
			}
		}

		final GeoEngine geo = GeoEngine.getInstance();
		if (best == null)
		{
			return new int[]
			{
				point[0],
				point[1],
				geo.getSpawnHeight(point[0], point[1], point[2])
			};
		}

		// Step back from the monster towards the nearest gatekeeper (or along +x when it has none).
		double dx = 1;
		double dy = 0;
		final int teleIdx = nearestTele(best.getX(), best.getY());
		if (teleIdx >= 0)
		{
			final Tele t = _teleports.get(teleIdx);
			final double len = Math.hypot(t.x - best.getX(), t.y - best.getY());
			if (len > 1)
			{
				dx = (t.x - best.getX()) / len;
				dy = (t.y - best.getY()) / len;
			}
		}
		final int tx = best.getX() + (int) (dx * LANDING_OFFSET);
		final int ty = best.getY() + (int) (dy * LANDING_OFFSET);
		final Location loc = geo.getValidLocation(best.getX(), best.getY(), best.getZ(), tx, ty, best.getZ(), 0);
		return new int[]
		{
			loc.getX(),
			loc.getY(),
			loc.getZ()
		};
	}

	private static boolean canTeleport(Player player)
	{
		if (player.isCastingNow() || player.isCastingSimultaneouslyNow() || player.isInCombat() || player.isInDuel() || player.isInOlympiadMode() || player.isInsideZone(ZoneId.SIEGE) || player.isInsideZone(ZoneId.PVP) || (player.getPvpFlag() > 0) || player.isAlikeDead() || player.isOnEvent() || player.isInStoreMode() || player.isJailed() || player.isFlying())
		{
			player.sendMessage("Adventurer's Guide: you can't teleport right now.");
			return false;
		}
		if (player.getKarma() > 0)
		{
			player.sendMessage("Adventurer's Guide: players with Karma can't teleport.");
			return false;
		}
		return true;
	}

	private static boolean doTeleport(Player player, int x, int y, int z, int fee, String placeName)
	{
		if ((fee > 0) && !player.destroyItemByItemId(ItemProcessType.FEE, ADENA, fee, player, true))
		{
			player.sendMessage("Adventurer's Guide: the teleport to " + placeName + " costs " + fee + " Adena.");
			return false;
		}

		player.sendPacket(new ShowBoard());
		player.disableAllSkills();
		player.setIn7sDungeon(false);
		player.setInstanceId(0);
		player.teleToLocation(x, y, z);
		ThreadPool.schedule(player::enableAllSkills, 3000);
		return true;
	}

	// ---------------------------------------------------------------- hints

	private void onLogin(Player player, int maxLevel)
	{
		if ((player == null) || (player.getLevel() > maxLevel))
		{
			return;
		}
		ThreadPool.schedule(() ->
		{
			if (player.isOnline())
			{
				player.sendMessage("Adventurer's Guide: not sure what to do? Press Alt+B and click Guide, or type .guide.");
			}
		}, 5000);
	}

	private void onLevelUp(Player player, int oldLevel, int newLevel)
	{
		if ((player == null) || (newLevel <= oldLevel) || !player.isOnline())
		{
			return;
		}

		int unlocked = 0;
		for (QuestInfo q : _quests)
		{
			if ((q.lvlMin > oldLevel) && (q.lvlMin <= newLevel) && (status(player, q) == Status.AVAILABLE))
			{
				unlocked++;
			}
		}
		if (unlocked > 0)
		{
			player.sendMessage("Adventurer's Guide: level " + newLevel + " opens " + unlocked + " new quest" + (unlocked == 1 ? "" : "s") + " for you. Type .guide to see them.");
		}
		final int next = nextClassLevel(player);
		if ((next > 0) && (oldLevel < next) && (newLevel >= next))
		{
			player.sendMessage("Adventurer's Guide: you can make your next class change now. Type .guide and open Next steps.");
		}
		if ((gradeForLevel(newLevel) > gradeForLevel(oldLevel)))
		{
			player.sendMessage("Adventurer's Guide: you can now use " + GRADES[gradeForLevel(newLevel)] + "-grade gear.");
		}
	}

	// ---------------------------------------------------------------- dispatch

	private void handle(Player player, String args)
	{
		final String[] p = args.trim().isEmpty() ? new String[] { "home" } : args.trim().split("\\s+");
		try
		{
			switch (p[0])
			{
				case "quests":
					showQuests(player, p.length > 1 ? p[1] : "avail", p.length > 2 ? Integer.parseInt(p[2]) : 0);
					break;
				case "quest":
					showQuest(player, Integer.parseInt(p[1]));
					break;
				case "hunt":
					showHunt(player, p.length > 1 ? Integer.parseInt(p[1]) : 0);
					break;
				case "area":
					showArea(player, Integer.parseInt(p[1]), p.length > 2 ? Integer.parseInt(p[2]) : -1);
					break;
				case "next":
					showNext(player);
					break;
				case "gear":
					showGear(player);
					break;
				case "towns":
					showTowns(player);
					break;
				case "town":
					showTown(player, Integer.parseInt(p[1]), p.length > 2 ? Integer.parseInt(p[2]) : 0);
					break;
				case "tips":
					showTips(player, p.length > 1 ? Integer.parseInt(p[1]) : -1);
					break;
				case "mark":
					mark(player, Integer.parseInt(p[1]), Integer.parseInt(p[2]), Integer.parseInt(p[3]));
					break;
				case "npc":
					markNpc(player, Integer.parseInt(p[1]));
					break;
				case "tp":
					teleport(player, Integer.parseInt(p[1]));
					break;
				case "go":
					goToMob(player, Integer.parseInt(p[1]), Integer.parseInt(p[2]));
					break;
				default:
					showHome(player);
					break;
			}
		}
		catch (NumberFormatException | ArrayIndexOutOfBoundsException e)
		{
			showHome(player);
		}
	}

	private class GuideBoard implements IParseBoardHandler
	{
		private final String[] COMMANDS =
		{
			CMD
		};

		@Override
		public boolean onCommand(String command, Player player)
		{
			handle(player, command.substring(CMD.length()));
			return true;
		}

		@Override
		public String[] getCommandList()
		{
			return COMMANDS;
		}
	}

	private class GuideVoicedCommand implements IVoicedCommandHandler
	{
		private final String[] COMMANDS =
		{
			"guide"
		};

		@Override
		public boolean onCommand(String command, Player player, String params)
		{
			if (player != null)
			{
				handle(player, params == null ? "" : params);
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
