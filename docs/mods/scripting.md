# Scripting (Java)

Datapack scripts are plain Java files under `game\data\scripts\`. **The server compiles them itself at startup** with
the bundled JDK, so there's no build step: edit, then restart (or `//reload quest` / `//reload handler`). A compile
error is printed in the game console and `game\log\error*.log`, and that script (or the whole handler set) doesn't
load. Check the log when a change "does nothing".

The engine classes you call (`Player`, `Npc`, `Script`, `ItemData`…) live in `libs\GameServer.jar` and can't be
changed. To see what a class offers, run:

```bash
jre/bin/javap -cp libs/GameServer.jar org.l2jmobius.gameserver.model.actor.Player
```

Or copy what similar scripts already do: this folder has thousands of examples.

## Layout

| Folder | Files | What |
|---|---|---|
| `handlers\` | | Registered through `handlers\MasterHandler.java` (see below) |
| ├ `actions\click`, `actions\shiftclick` | 10 / 6 | What clicking and shift-clicking an object does |
| ├ `bypass\npc` | 27 | `bypass -h npc_%objectId%_<X>` commands: `Multisell`, `Buy`, `Link`, `Wear`… |
| ├ `bypass\communityboard` | 9 | Alt+B board (`HomeBoard` = the custom board, `DropSearchBoard`…) |
| ├ `chat\commands\admin` | 81 | `//commands` (`AdminReload`, `AdminShop`, `AdminPhantom`…) |
| ├ `chat\commands\voiced` | 14 | `.commands` (`AutoPlay`, `Banking`, `Online`, `Premium`…) |
| ├ `chat\commands\user`, `chat\channels` | 13 / 14 | `/commands` and chat channels |
| ├ `items` | 25 | Item handlers (the `handler` set on an item: `ItemSkills`, `Soulshots`…) |
| ├ `skill\effects`, `skill\targets` | 146 / 34 | Skill effect types and target types |
| └ `punishments` | 3 | Ban, jail, chat ban |
| `ai\areas`, `ai\bosses`, `ai\others` | 692 | Monster and NPC AI |
| `quests\` | 346 folders | Quests, one folder each (`Q00070_SagaOfThePhoenixKnight\` with its `.java` and `.htm`) |
| `village_master\` | 992 | Class-change NPC dialogs |
| `custom\` | 193 | Custom NPC scripts: `NoblessMaster`, `DelevelManager`, `Transmog`, `SellBuff`, `FactionSystem`, `events\` (CTF, TvT, Deathmatch, Race, Elpies, Wedding)… |
| `events\`, `conquerablehalls\`, `vehicles\` | | Seasonal events, clan hall sieges, boats |

## How scripts load
- **Every script except handlers.** The server scans `data\scripts`, applies the `<exclude>`/`<include>` rules in
  `game\config\Scripts.xml` (which excludes `handlers` and `package-info.java`), compiles, and calls each class's
  `public static void main(String[])`. A script registers itself from its constructor.
- **Handlers.** `handlers\MasterHandler.java` has a hardcoded `HANDLERS` array of classes, and registers each one with
  its handler type. Some entries depend on a config, e.g. `AutoPlayConfig.ENABLE_AUTO_PLAY ? AutoPlay.class : null`.
  A new handler file does nothing until it's added to that array.
- **Warning.** `MasterHandler.java` is in the update patch list. An update overwrites your additions, so new
  commands are better shipped as a **module** ([modules.md](modules.md)).

## Recipe: an NPC with a dialog script
Copy `scripts\custom\NoblessMaster\`: one `.java` file plus `.htm` pages named after the NPC id.

1. **NPC template:** `game\data\stats\npcs\custom\MyNpc.xml`. Use `type="Folk"`, a `displayId` to borrow a model, and
   `usingServerSideName="true"` ([datapack-reference.md](datapack-reference.md#npcs-statsnpcs-xsdnpcsxsd)). Take the
   id from [id-registry.md](id-registry.md).
2. **Spawn:** add an `<npc id="…" x y z heading respawnDelay="60"/>` to a spawn file (`/loc` gives coordinates).
3. **Script:** `game\data\scripts\custom\MyNpc\MyNpc.java`:

```java
package custom.MyNpc;

import org.l2jmobius.gameserver.model.actor.Npc;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.script.Script;

public class MyNpc extends Script
{
	private static final int NPC_ID = 1004000;

	private MyNpc()
	{
		addStartNpc(NPC_ID);
		addTalkId(NPC_ID);
		addFirstTalkId(NPC_ID);
	}

	@Override
	public String onFirstTalk(Npc npc, Player player)
	{
		return "1004000.htm"; // shown when the player clicks the NPC
	}

	@Override
	public String onEvent(String event, Npc npc, Player player)
	{
		switch (event)
		{
			case "reward":
			{
				if (getQuestItemsCount(player, 57) < 1000)
				{
					return "1004000-no.htm";
				}
				takeItems(player, 57, 1000);
				giveItems(player, 1060, 10); // 10 Lesser Healing Potions
				return "1004000-ok.htm";
			}
		}
		return null;
	}

	public static void main(String[] args)
	{
		new MyNpc();
	}
}
```

4. **Pages:** in the same folder, `1004000.htm` holds a button that fires the event:

```html
<html><body>Hello, %playername%!<br>
<a action="bypass -h Script MyNpc reward">Trade 1000 adena for potions</a>
</body></html>
```

5. **Apply:** restart. The NPC template and spawn need a restart; after that, `//reload quest MyNpc` picks up
   script changes and `//reload html` picks up page changes.

Other useful hooks on `Script` (see any `ai\` script for real use):
- **Events:** `addKillId` + `onKill(Npc, Player, boolean isSummon)`, `addAttackId` + `onAttack`, `addSpawnId` +
  `onSpawn`.
- **Timers:** `startQuestTimer(name, ms, npc, player)`.
- **Items and effects:** `giveItems`, `takeItems`, `getQuestItemsCount`, `playSound`.

## Recipe: a voiced `.command`
The clean way is a module (it survives updates, has an on/off switch, and needs no `MasterHandler` edit). See
[modules.md](modules.md). The handler itself:

```java
import org.l2jmobius.gameserver.handler.IVoicedCommandHandler;
import org.l2jmobius.gameserver.model.actor.Player;

public class HealMe implements IVoicedCommandHandler
{
	private static final String[] COMMANDS = { "healme" };  // typed as .healme

	@Override
	public boolean onCommand(String command, Player player, String params)
	{
		player.setCurrentHpMp(player.getMaxHp(), player.getMaxMp());
		player.sendMessage("Healed.");
		return true;
	}

	@Override
	public String[] getCommandList()
	{
		return COMMANDS;
	}
}
```

## Recipe: an admin `//command`
1. Write an `IAdminCommandHandler`. It's the same shape as the voiced command, but uses
   `onCommand(String command, Player activeChar)` and command names that start with `admin_`
   (`"admin_mycmd"` → typed as `//mycmd`). `handlers\chat\commands\admin\AdminShop.java` is a short model to copy.
2. Register it: from a module with `context.handlers().registerAdminCommand(...)`, or by adding it to
   `MasterHandler`.
3. Give it an access level in `game\config\AdminCommands.xml`:

   ```xml
   <admin command="mycmd" description="What it does." accessLevel="100" />
   ```

   The command name is written **without** the `admin_` prefix. Add this line so the access level is explicit. Some
   pack commands (`//phantom`) have no line and are used from the master account only.
4. Restart, or `//reload access` for the XML change.

## Recipe: a Community Board page or bypass
Pages and bypass commands are covered in [community-board.md](community-board.md). A new `_bbs…` command needs a
board handler (`IParseBoardHandler`, like `HomeBoard`), registered through `MasterHandler`.

The module API can't register board handlers. `registerBypass` takes NPC-dialog bypass handlers
(`IBypassHandler`), not board handlers. Most board features don't need a new command anyway: new pages plus the
existing `_bbstop`, `_bbsmultisell` and `_bbssell` commands cover shops and menus.
