# Modules

A module is a self-contained mod folder under `game\modules\<id>\`:
- it has its own on/off switch, its own Java, and its own data;
- the server compiles and loads it at startup;
- deleting the folder removes it cleanly.

**Use a module for any new feature.** Modules survive updates better than edits to stock files. An update only
overwrites the three reference modules' files listed in `patch-manifest.txt`, never a module you add.

The framework is in the jar (`org.l2jmobius.gameserver.modules.*`). It's switched on by `EnableModules = True` in
`game\config\Modules.ini`. `ModulesRoot` is blank, which means `game\modules`.

## Folder layout

```
game\modules\my-mod\
├─ module.json            manifest (required)
├─ config\module.ini      settings; by convention Enabled = True/False
├─ scripts\*.java         compiled at startup; package = modules.<something>
├─ data\items\*.xml       optional resource folders, declared in module.json
├─ MODULE.md              what it does, enable/disable/remove
└─ TESTING.md             how to check it works
```

## `module.json`

```json
{
  "id": "custom-item",
  "name": "Custom Item",
  "version": "1.0.0",
  "apiVersion": "1",
  "entrypoint": "modules.customitem.CustomItemModule",
  "description": "Ships one item and a command to grant it.",
  "author": "core",
  "priority": 100,
  "resources": { "items": ["data/items"] },
  "reserves":  { "items": [[60000, 60009]] }
}
```

| Key | Meaning |
|---|---|
| `id` | Lowercase words joined by `-` (`[a-z0-9]+(-[a-z0-9]+)*`) |
| `apiVersion` | Must be `"1"` |
| `entrypoint` | Fully qualified class that implements `GameModule` |
| `priority` | Load order between modules |
| `resources` | Folders, relative to the module, that stock loaders read while the module is enabled. Types: `items`, `skills`, `npcs`, `spawns`, `html`, `multisell`. |
| `reserves` | Id ranges this module owns, per type, as `[[low, high], …]`. The framework has an overlap check (`ModuleIdRange.overlaps`), so keep ranges distinct. |
| `dependencies`, `conflicts` | Lists of other module ids |
| `database` | `install` / `remove` SQL scripts plus a `tables` list, for modules with their own tables. None of the reference modules uses it. Test it on a backed-up DB before relying on it. |

## The Java side

```java
package modules.healme;

import org.l2jmobius.gameserver.modules.GameModule;
import org.l2jmobius.gameserver.modules.ModuleContext;

public class HealMeModule implements GameModule
{
	@Override
	public void onEnable(ModuleContext context)
	{
		if (!context.config().getBoolean("Enabled", false))
		{
			return; // switch off: register nothing, the server stays stock
		}
		context.handlers().registerVoicedCommand(new HealMe()); // the handler from scripting.md
		context.logging().info("HealMe module enabled (.healme)");
	}
}
```

`ModuleContext` gives you the following (read from the jar with `javap`):

| Call | What |
|---|---|
| `config().getBoolean/getInt/getLong/getDouble/getString(key, default)` | Reads `config\module.ini` |
| `handlers().registerVoicedCommand(IVoicedCommandHandler)` | `.commands` |
| `handlers().registerAdminCommand(IAdminCommandHandler)` | `//commands`; also needs a line in `config\AdminCommands.xml` |
| `handlers().registerBypass(IBypassHandler)` | NPC-dialog bypass commands |
| `handlers().registerItem(IItemHandler)` | Item use handlers |
| `handlers().registerEffect(Class<? extends AbstractEffect>)` | New skill effect types |
| `handlers().registerTarget(ITargetTypeHandler)` | New skill target types |
| `events().onGlobal/onPlayers/onNpcs/onMonsters(EventType, Consumer)` | Game event listeners (login, kill, level up…; see `org.l2jmobius.gameserver.model.events.EventType`) |
| `companions().summon(player, …)`, `isCompanion(player)` | The companion API the alt-companion module uses |
| `logging()` | A `java.util.logging.Logger` |

`GameModule` also has an optional `onDisable(context)`.

## The three reference modules

| Module | Switch | Command | Shows how to |
|---|---|---|---|
| `hello-world` | `Enabled = False` | `.hello` | The minimum: manifest, config, one voiced command |
| `custom-item` | `Enabled = False` | `.token` | Ship an item (id 60000, `displayId` 4037) through a `resources` folder, and reserve an id range |
| `alt-companion` | **`Enabled = True`** | `.alt <name>` | Bring one of your own characters into your party as an AI member; uses `companions()` |
| `adventurer-guide` | **`Enabled = True`** | `.guide`, and `_bbs_guide` on the Alt+B board | A new-player guide: eligible quests from the client's quest table, hunting spots by level, class path, gear, towns, tips; radar marks and paid teleports; login and level-up hints through `events()` |
| `quest-navigator` | **`Enabled = True`** | `.questnav go\|clear\|export` | The server half of the Alt+U Quest Navigator: answers `_bbs_questnav` bypasses from the patched quest window, and registers its board handler with `CommunityBoardHandler` directly |

Each has a `MODULE.md` and `TESTING.md` worth reading before writing your own. Their docs mention a
`docs\MODULE_FRAMEWORK.md` with a reserved-range registry. That file isn't in this pack, so
[id-registry.md](id-registry.md) is the registry now.

## Checklist for a new module
1. Pick an `id` and a free id block in [id-registry.md](id-registry.md), and record it there.
2. Create `module.json`, `config\module.ini` (`Enabled = True`), and `scripts\<Name>Module.java` with
   `package modules.<name>;`.
3. Put any items, NPCs, HTML or multisells under `data\…` and declare them in `resources`.
4. Restart. Look for the `[Modules]` lines in the game console, and for compile errors in `game\log\error*.log`.
5. Test in game, then add a `CHANGELOG.md` entry and commit.

**Disable:** set `Enabled = False` and restart. **Remove:** delete the folder (and, if it made tables, drop them or
provide `database.remove`).
