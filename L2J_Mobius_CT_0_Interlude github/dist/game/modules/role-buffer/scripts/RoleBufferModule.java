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
package modules.rolebuffer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Logger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.l2jmobius.gameserver.cache.HtmCache;
import org.l2jmobius.gameserver.config.custom.CommunityBoardConfig;
import org.l2jmobius.gameserver.data.xml.SkillData;
import org.l2jmobius.gameserver.handler.CommunityBoardHandler;
import org.l2jmobius.gameserver.handler.IParseBoardHandler;
import org.l2jmobius.gameserver.handler.IVoicedCommandHandler;
import org.l2jmobius.gameserver.model.actor.Creature;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.Summon;
import org.l2jmobius.gameserver.model.item.enums.ItemProcessType;
import org.l2jmobius.gameserver.model.skill.Skill;
import org.l2jmobius.gameserver.model.zone.ZoneId;
import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;

/**
 * The Role Buffer: a Community Board page (Alt+B, "Buffer") with one-click buff packages per role (Warrior, Dagger,
 * Archer, Tank, Mage, Summoner, Healer/Support). Each package gives every buff, dance and song that role benefits from,
 * at the skill's highest level, for {@code BuffDurationSeconds}. A pet or summon gets the Pet package too.
 * <p>
 * The packages are {@code data/packages.txt}; the buffs' levels, stack types and effect summaries are
 * {@code data/buffs.tsv}, written and checked by {@code tools/buffer/build_buffer_data.py}.
 */
public class RoleBufferModule implements GameModule
{
	private static final String CMD = "_bbs_buffer";
	private static final String NAVIGATION_PATH = "data/html/CommunityBoard/Custom/navigation.html";
	private static final String PET_KEY = "pet";
	private static final String PET_VARIABLE = "RoleBuffer.pet";
	// The board sends a page in at most three 4090-character packets.
	private static final int MAX_HTML = 12270;
	private static final DateTimeFormatter CLOCK = DateTimeFormatter.ofPattern("HH:mm:ss");

	/** The role each class gets as "Recommended"; classes not listed are Warrior (fighters) or Mage (mystics). */
	private static final Map<String, String> CLASS_ROLES = new HashMap<>();
	static
	{
		role("dagger", "ROGUE", "TREASURE_HUNTER", "ADVENTURER", "ELVEN_SCOUT", "PLAINS_WALKER", "WIND_RIDER", "ASSASSIN", "ABYSS_WALKER", "GHOST_HUNTER");
		role("archer", "HAWKEYE", "SAGITTARIUS", "SILVER_RANGER", "MOONLIGHT_SENTINEL", "PHANTOM_RANGER", "GHOST_SENTINEL");
		role("tank", "KNIGHT", "PALADIN", "DARK_AVENGER", "PHOENIX_KNIGHT", "HELL_KNIGHT", "ELVEN_KNIGHT", "TEMPLE_KNIGHT", "EVA_TEMPLAR", "PALUS_KNIGHT", "SHILLIEN_KNIGHT", "SHILLIEN_TEMPLAR");
		role("summoner", "WARLOCK", "ARCANA_LORD", "ELEMENTAL_SUMMONER", "ELEMENTAL_MASTER", "PHANTOM_SUMMONER", "SPECTRAL_MASTER");
		role("healer", "CLERIC", "BISHOP", "CARDINAL", "PROPHET", "HIEROPHANT", "ORACLE", "ELDER", "EVA_SAINT", "SHILLIEN_ORACLE", "SHILLIEN_ELDER", "SHILLIEN_SAINT", "ORC_MAGE", "ORC_SHAMAN", "OVERLORD", "DOMINATOR", "WARCRYER", "DOOMCRYER");
	}

	private static void role(String key, String... classes)
	{
		for (String c : classes)
		{
			CLASS_ROLES.put(c, key);
		}
	}

	private Logger _log;
	private int _duration;
	private int _price;
	private int _priceItemId;
	private boolean _buffPetDefault;
	private boolean _allowInCombat;
	private int _cooldownMs;
	private boolean _debug;

	private final Map<Integer, Buff> _buffs = new HashMap<>();
	private final Map<String, Pack> _packages = new LinkedHashMap<>();
	private final Map<Integer, Long> _lastApply = new ConcurrentHashMap<>();
	private final Map<Integer, String> _lastResult = new ConcurrentHashMap<>();

	@Override
	public void onEnable(ModuleContext context)
	{
		if (!context.config().getBoolean("Enabled", false))
		{
			return; // Switch off: register nothing, behave as stock.
		}

		_log = context.logging();
		_duration = context.config().getInt("BuffDurationSeconds", 3600);
		_price = context.config().getInt("PricePerPackage", 0);
		_priceItemId = context.config().getInt("PriceItemId", 57);
		_buffPetDefault = context.config().getBoolean("BuffPetDefault", true);
		_allowInCombat = context.config().getBoolean("AllowInCombat", false);
		_cooldownMs = context.config().getInt("ApplyCooldownMs", 1000);
		_debug = context.config().getBoolean("Debug", false);

		final Path dataPath = Paths.get(context.config().getString("DataPath", "modules/role-buffer/data"));
		try
		{
			load(dataPath);
		}
		catch (IOException | RuntimeException e)
		{
			_log.warning("Role Buffer: could not load " + dataPath.toAbsolutePath().normalize() + ": " + e + ". Run tools/buffer/build_buffer_data.py.");
			return;
		}

		// ModuleHandlers has no board method, so register the board handler directly.
		CommunityBoardHandler.getInstance().registerHandler(new BufferBoard());
		context.handlers().registerVoicedCommand(new BufferVoicedCommand());
		_log.info("Role Buffer enabled: " + _packages.size() + " packages, " + _buffs.size() + " buffs, " + (_duration > 0 ? _duration + " s each" : "normal durations") + "; registered " + CMD + " and .buff");
	}

	// ---------------------------------------------------------------- data

	private static class Buff
	{
		int id;
		int level;
		String name;
		boolean dance;
		String icon;
		String effect;
	}

	private static class Pack
	{
		String key;
		String name;
		String purpose;
		int icon;
		final List<Buff> buffs = new ArrayList<>();

		int count(boolean dances)
		{
			int n = 0;
			for (Buff b : buffs)
			{
				if (b.dance == dances)
				{
					n++;
				}
			}
			return n;
		}
	}

	private void load(Path dir) throws IOException
	{
		for (String line : Files.readAllLines(dir.resolve("buffs.tsv"), StandardCharsets.UTF_8))
		{
			if (line.isEmpty() || line.startsWith("#"))
			{
				continue;
			}
			// id level name kind type typeLevel time icon effect
			final String[] f = line.split("\t", -1);
			final Buff b = new Buff();
			b.id = Integer.parseInt(f[0]);
			b.level = Integer.parseInt(f[1]);
			b.name = f[2];
			b.dance = f[3].equals("dance");
			b.icon = f[7];
			b.effect = f[8];
			_buffs.put(b.id, b);
		}

		final Pattern header = Pattern.compile("^\\[(\\w+)\\]\\s*(.*)$");
		final Pattern id = Pattern.compile("^(\\d+)\\b.*$");
		Pack current = null;
		for (String raw : Files.readAllLines(dir.resolve("packages.txt"), StandardCharsets.UTF_8))
		{
			final String line = raw.split("//", 2)[0].trim();
			if (line.isEmpty())
			{
				continue;
			}
			Matcher m = header.matcher(line);
			if (m.matches())
			{
				current = new Pack();
				current.key = m.group(1).toLowerCase();
				final String[] fields = m.group(2).split("\\|");
				current.name = fields[0].trim().isEmpty() ? current.key : fields[0].trim();
				current.purpose = fields.length > 1 ? fields[1].trim() : "";
				for (int i = 2; i < fields.length; i++)
				{
					final String f = fields[i].trim();
					if (f.startsWith("icon="))
					{
						current.icon = Integer.parseInt(f.substring(5).trim());
					}
				}
				_packages.put(current.key, current);
				continue;
			}
			m = id.matcher(line);
			if (m.matches() && (current != null))
			{
				final Buff b = _buffs.get(Integer.parseInt(m.group(1)));
				if (b == null)
				{
					_log.warning("Role Buffer: [" + current.key + "] skill " + m.group(1) + " isn't in buffs.tsv; skipped.");
				}
				else
				{
					current.buffs.add(b);
				}
			}
		}
		if (_packages.isEmpty())
		{
			throw new IOException("no packages in packages.txt");
		}
	}

	// ---------------------------------------------------------------- helpers

	private static String color(String hex, String text)
	{
		return "<font color=\"" + hex + "\">" + text + "</font>";
	}

	private static String gray(String text)
	{
		return color("808080", text);
	}

	private static String esc(String text)
	{
		return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
	}

	private static String link(String label, String args)
	{
		return "<a action=\"bypass " + CMD + " " + args + "\">" + label + "</a>";
	}

	private static String button(String label, String args)
	{
		return "<button value=\"" + label + "\" action=\"bypass " + CMD + " " + args + "\" width=114 height=30 back=\"L2UI_CH3.Button.bigbutton2_down\" fore=\"L2UI_CH3.Button.bigbutton2\">";
	}

	private static String iconButton(String icon, String args)
	{
		return "<button value=\" \" action=\"bypass " + CMD + " " + args + "\" width=32 height=32 back=\"" + icon + "\" fore=\"" + icon + "\">";
	}

	private String iconOf(Pack pack)
	{
		final Buff b = _buffs.get(pack.icon);
		if (b != null)
		{
			return b.icon;
		}
		return pack.buffs.isEmpty() ? "icon.skill1068" : pack.buffs.get(0).icon;
	}

	private String recommendedRole(Player player)
	{
		final String key = CLASS_ROLES.get(player.getPlayerClass().name());
		if ((key != null) && _packages.containsKey(key))
		{
			return key;
		}
		final String fallback = player.isMageClass() ? "mage" : "warrior";
		if (_packages.containsKey(fallback))
		{
			return fallback;
		}
		for (String k : _packages.keySet())
		{
			if (!k.equals(PET_KEY))
			{
				return k;
			}
		}
		return null;
	}

	private boolean petOn(Player player)
	{
		return player.getVariables().getBoolean(PET_VARIABLE, _buffPetDefault);
	}

	private static String className(Player player)
	{
		final StringBuilder sb = new StringBuilder();
		for (String word : player.getPlayerClass().name().toLowerCase().split("_"))
		{
			sb.append(sb.length() > 0 ? " " : "").append(Character.toUpperCase(word.charAt(0))).append(word.substring(1));
		}
		return sb.toString();
	}

	private static String petName(Summon summon)
	{
		final String name = summon.getName();
		return (name == null) || name.isEmpty() ? "your pet" : name;
	}

	private static String counts(Pack pack)
	{
		final int dances = pack.count(true);
		return pack.count(false) + " buffs" + (dances > 0 ? ", " + dances + " dances/songs" : "");
	}

	// ---------------------------------------------------------------- pages

	private void send(Player player, String title, String body)
	{
		final StringBuilder sb = new StringBuilder(8192);
		sb.append("<html><body><table width=700><tr><td height=10></td></tr></table>");
		sb.append("<table width=20><tr><td>%navigation%</td><td><center>");
		sb.append("<table bgcolor=\"000000\" width=500 height=415><tr><td valign=top width=500>");
		sb.append("<table width=500><tr><td height=22 align=center><font color=\"CDB67F\">Buffer</font>");
		sb.append(gray(" - " + title)).append("</td></tr></table>");
		sb.append("<img src=\"L2UI.SquareGray\" width=500 height=1><br1>");
		sb.append(body);
		sb.append("</td></tr></table>");
		sb.append("<table border=0 cellpadding=0 cellspacing=0 width=500><tr><td height=10></td></tr></table>");
		sb.append("<table border=0 bgcolor=\"000000\" cellpadding=0 cellspacing=0 width=500>");
		// The clock makes every page different, so the client always takes the new one.
		sb.append("<tr><td height=30 align=center><font color=696969>Alt+B - Buffer&nbsp;&nbsp;&nbsp;or type .buff&nbsp;&nbsp;&nbsp;").append(LocalTime.now().format(CLOCK)).append("</font></td></tr>");
		sb.append("</table></center></td></tr></table></body></html>");

		String html = sb.toString();
		final String navigation = CommunityBoardConfig.CUSTOM_CB_ENABLED ? HtmCache.getInstance().getHtm(player, NAVIGATION_PATH) : null;
		html = html.replace("%navigation%", navigation == null ? "" : navigation);
		if (html.length() > MAX_HTML)
		{
			_log.warning("Role Buffer: page '" + title + "' is " + html.length() + " characters, over the board limit of " + MAX_HTML + ".");
			player.sendMessage("Buffer: that page is too long to show.");
			return;
		}
		CommunityBoardHandler.separateAndSend(html, player);
	}

	private void showMain(Player player)
	{
		final String recommended = recommendedRole(player);
		final StringBuilder sb = new StringBuilder();

		// Recommended role.
		sb.append("<table width=490><tr><td width=40>");
		if (recommended != null)
		{
			final Pack rec = _packages.get(recommended);
			sb.append(iconButton(iconOf(rec), "apply " + rec.key)).append("</td><td width=330>");
			sb.append("Recommended for your ").append(esc(className(player))).append(": ").append(color("LEVEL", esc(rec.name))).append("<br1>");
			sb.append(gray(esc(rec.purpose))).append("</td><td width=120 align=right>").append(button("Buff me", "apply " + rec.key));
		}
		sb.append("</td></tr></table>");

		final String result = _lastResult.get(player.getObjectId());
		if (result != null)
		{
			sb.append("<table width=490><tr><td align=center>").append(color("88CC88", esc(result))).append("</td></tr></table>");
		}
		sb.append("<img src=\"L2UI.SquareGray\" width=490 height=1><br1>");

		// Every role.
		sb.append("<table width=490>");
		for (Pack pack : _packages.values())
		{
			if (pack.key.equals(PET_KEY))
			{
				continue;
			}
			sb.append("<tr><td width=40 height=38>").append(iconButton(iconOf(pack), "apply " + pack.key)).append("</td>");
			sb.append("<td width=280>").append(pack.key.equals(recommended) ? color("LEVEL", esc(pack.name)) : color("CDB67F", esc(pack.name)));
			sb.append(gray("&nbsp;&nbsp;" + counts(pack))).append("<br1>").append(gray(esc(pack.purpose))).append("</td>");
			sb.append("<td width=50 align=center>").append(link("Details", "role " + pack.key)).append("</td>");
			sb.append("<td width=120 align=right>").append(button("Apply", "apply " + pack.key)).append("</td></tr>");
		}
		sb.append("</table>");

		// Pet, heal, remove.
		sb.append("<img src=\"L2UI.SquareGray\" width=490 height=1><br1><table width=490><tr><td width=250>");
		final Pack pet = _packages.get(PET_KEY);
		if (pet != null)
		{
			final Summon summon = player.getSummon();
			sb.append("Also buff my pet/summon: ").append(petOn(player) ? color("88CC88", "On") + gray(" / ") + link("Off", "pet off") : link("On", "pet on") + gray(" / ") + color("FF6666", "Off"));
			sb.append("<br1>").append(gray(summon == null ? "(no pet out now)" : "(" + esc(petName(summon)) + ": " + counts(pet) + ", " + link("details", "role " + PET_KEY) + ")"));
		}
		sb.append("</td><td width=120 align=center>").append(button("Heal", "heal")).append("</td>");
		sb.append("<td width=120 align=center>").append(button("Remove buffs", "clear")).append("</td></tr></table>");
		sb.append(gray("Every package lasts " + durationText() + (_price > 0 ? " and costs " + _price + " " + priceName() : ", free") + ". Applying another package replaces the buffs of the same kind."));
		send(player, "Buff packages", sb.toString());
	}

	private void showRole(Player player, String key, int page)
	{
		final Pack pack = _packages.get(key);
		if (pack == null)
		{
			showMain(player);
			return;
		}
		final boolean dances = page == 1;
		final List<Buff> list = new ArrayList<>();
		for (Buff b : pack.buffs)
		{
			if (b.dance == dances)
			{
				list.add(b);
			}
		}

		final StringBuilder sb = new StringBuilder();
		sb.append("<table width=490><tr><td width=40>").append(iconButton(iconOf(pack), "apply " + pack.key)).append("</td><td width=330>");
		sb.append(color("LEVEL", esc(pack.name))).append(gray("&nbsp;&nbsp;" + counts(pack))).append("<br1>").append(gray(esc(pack.purpose))).append("</td>");
		sb.append("<td width=120 align=right>").append(button(pack.key.equals(PET_KEY) ? "Buff my pet" : "Apply", "apply " + pack.key)).append("</td></tr></table>");
		sb.append("<table width=490><tr><td align=center>");
		sb.append(dances ? link("Buffs (" + pack.count(false) + ")", "role " + key + " 0") : color("LEVEL", "Buffs (" + pack.count(false) + ")"));
		sb.append("&nbsp;&nbsp;&nbsp;&nbsp;");
		sb.append(dances ? color("LEVEL", "Dances &amp; Songs (" + pack.count(true) + ")") : link("Dances &amp; Songs (" + pack.count(true) + ")", "role " + key + " 1"));
		sb.append("</td></tr></table><img src=\"L2UI.SquareGray\" width=490 height=1><br1>");

		// Two columns: icon, name and level, what it does.
		sb.append("<table width=490>");
		for (int i = 0; i < list.size(); i += 2)
		{
			sb.append("<tr>");
			for (int j = i; j < (i + 2); j++)
			{
				if (j < list.size())
				{
					final Buff b = list.get(j);
					sb.append("<td width=36 height=36><img src=\"").append(b.icon).append("\" width=32 height=32></td>");
					sb.append("<td width=209>").append(color("CDB67F", esc(b.name))).append(gray(" " + b.level)).append("<br1>").append(gray(esc(b.effect))).append("</td>");
				}
				else
				{
					sb.append("<td width=36></td><td width=209></td>");
				}
			}
			sb.append("</tr>");
		}
		if (list.isEmpty())
		{
			sb.append("<tr><td>").append(gray("None in this package.")).append("</td></tr>");
		}
		sb.append("</table><br1><center>").append(link("Back to packages", "main")).append("</center>");
		send(player, esc(pack.name), sb.toString());
	}

	private String durationText()
	{
		if (_duration <= 0)
		{
			return "each buff's normal time";
		}
		if ((_duration % 3600) == 0)
		{
			return (_duration / 3600) + (_duration == 3600 ? " hour" : " hours");
		}
		return (_duration / 60) + " minutes";
	}

	private String priceName()
	{
		return _priceItemId == 57 ? "Adena" : "&#" + _priceItemId + ";";
	}

	// ---------------------------------------------------------------- actions

	private boolean canBuff(Player player)
	{
		if (player.getKarma() > 0)
		{
			player.sendMessage("Buffer: players with Karma can't be buffed.");
			return false;
		}
		if (player.isAlikeDead() || player.isInOlympiadMode() || player.isInDuel() || player.isInsideZone(ZoneId.SIEGE) || player.isOnEvent() || (!_allowInCombat && player.isInCombat()))
		{
			player.sendMessage("Buffer: you can't be buffed right now" + (!_allowInCombat && player.isInCombat() ? " (in combat)." : "."));
			return false;
		}
		return true;
	}

	/**
	 * Gives a package. Returns the result line, or null when nothing was given.
	 */
	private String apply(Player player, String key)
	{
		final Pack pack = _packages.get(key);
		if (pack == null)
		{
			player.sendMessage("Buffer: there's no package called " + key + ". Try: " + String.join(", ", _packages.keySet()) + ".");
			return null;
		}

		final long now = System.currentTimeMillis();
		final Long last = _lastApply.get(player.getObjectId());
		if ((last != null) && ((now - last) < _cooldownMs))
		{
			player.sendMessage("Buffer: one moment, the last package is still going on.");
			return null;
		}
		if (!canBuff(player))
		{
			return null;
		}

		final boolean petOnly = pack.key.equals(PET_KEY);
		final Summon summon = player.getSummon();
		final Pack petPack = _packages.get(PET_KEY);
		if (petOnly && (summon == null))
		{
			player.sendMessage("Buffer: call your pet or summon first.");
			return null;
		}
		if ((_price > 0) && !player.destroyItemByItemId(ItemProcessType.FEE, _priceItemId, _price, player, true))
		{
			player.sendMessage("Buffer: the " + pack.name + " package costs " + _price + " " + (_priceItemId == 57 ? "Adena" : "coins") + ".");
			return null;
		}
		_lastApply.put(player.getObjectId(), now);

		String result;
		if (petOnly)
		{
			result = pack.name + ": " + give(player, summon, pack) + " on " + petName(summon);
		}
		else
		{
			result = pack.name + " package: " + give(player, player, pack);
			if ((summon != null) && (petPack != null) && petOn(player))
			{
				result += "; " + petName(summon) + ": " + give(player, summon, petPack);
			}
		}
		result += " (" + durationText() + ").";
		player.sendMessage("Buffer: " + result);
		_lastResult.put(player.getObjectId(), result);
		if (_debug)
		{
			_log.info("Role Buffer: " + player.getName() + " applied " + pack.key + ": " + result);
		}
		return result;
	}

	private String give(Player player, Creature target, Pack pack)
	{
		int buffs = 0;
		int dances = 0;
		for (Buff b : pack.buffs)
		{
			// Looked up here, not at startup: modules may start before the skills are loaded.
			final Skill skill = SkillData.getInstance().getSkill(b.id, b.level);
			if (skill == null)
			{
				_log.warning("Role Buffer: skill " + b.id + " level " + b.level + " (" + b.name + ") isn't loaded; skipped.");
				continue;
			}
			skill.applyEffects(player, target, true, _duration > 0 ? _duration : 0);
			if (b.dance)
			{
				dances++;
			}
			else
			{
				buffs++;
			}
		}
		if (target instanceof Player)
		{
			((Player) target).updateUserInfo();
		}
		return buffs + " buffs" + (dances > 0 ? ", " + dances + " dances/songs" : "");
	}

	private void heal(Player player)
	{
		if (!canBuff(player))
		{
			return;
		}
		player.setCurrentHp(player.getMaxHp());
		player.setCurrentMp(player.getMaxMp());
		player.setCurrentCp(player.getMaxCp());
		final Summon summon = player.getSummon();
		if (summon != null)
		{
			summon.setCurrentHp(summon.getMaxHp());
			summon.setCurrentMp(summon.getMaxMp());
		}
		player.updateUserInfo();
		_lastResult.put(player.getObjectId(), "HP, MP and CP restored" + (summon != null ? ", pet too." : "."));
		player.sendMessage("Buffer: HP, MP and CP restored.");
	}

	private void clear(Player player)
	{
		player.getEffectList().stopAllBuffs(true);
		player.getEffectList().stopAllDances(true);
		final Summon summon = player.getSummon();
		if (summon != null)
		{
			summon.getEffectList().stopAllBuffs(true);
			summon.getEffectList().stopAllDances(true);
		}
		player.updateUserInfo();
		_lastResult.put(player.getObjectId(), "Buffs, dances and songs removed.");
		player.sendMessage("Buffer: your buffs, dances and songs were removed.");
	}

	// ---------------------------------------------------------------- dispatch

	private void handle(Player player, String args, boolean fromBoard)
	{
		final String[] p = args.trim().isEmpty() ? new String[] { "main" } : args.trim().toLowerCase().split("\\s+");
		if (_debug)
		{
			_log.info("Role Buffer: " + player.getName() + " clicked '" + args.trim() + "'");
		}
		try
		{
			switch (p[0])
			{
				case "apply":
					apply(player, p[1]);
					if (fromBoard)
					{
						showMain(player);
					}
					break;
				case "role":
					showRole(player, p[1], p.length > 2 ? Integer.parseInt(p[2]) : 0);
					break;
				case "pet":
					player.getVariables().set(PET_VARIABLE, p[1].equals("on"));
					showMain(player);
					break;
				case "heal":
					heal(player);
					showMain(player);
					break;
				case "clear":
					clear(player);
					showMain(player);
					break;
				case "main":
					showMain(player);
					break;
				default:
					// ".buff warrior" gives the package straight away.
					if (_packages.containsKey(p[0]))
					{
						apply(player, p[0]);
						if (fromBoard)
						{
							showMain(player);
						}
					}
					else
					{
						showMain(player);
					}
					break;
			}
		}
		catch (NumberFormatException | ArrayIndexOutOfBoundsException e)
		{
			showMain(player);
		}
	}

	private class BufferBoard implements IParseBoardHandler
	{
		private final String[] COMMANDS =
		{
			CMD
		};

		@Override
		public boolean onCommand(String command, Player player)
		{
			handle(player, command.substring(CMD.length()), true);
			return true;
		}

		@Override
		public String[] getCommandList()
		{
			return COMMANDS;
		}
	}

	private class BufferVoicedCommand implements IVoicedCommandHandler
	{
		private final String[] COMMANDS =
		{
			"buff"
		};

		@Override
		public boolean onCommand(String command, Player player, String params)
		{
			if (player != null)
			{
				handle(player, params == null ? "" : params, false);
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
