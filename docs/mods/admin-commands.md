# Admin commands for modding

Log in on the **`admin`** account: its characters get master access (level 100) automatically. Type commands in
chat with `//`. `//admin` opens the GM panel. Which level each command needs is set in
`game\config\AdminCommands.xml`.

## Reloading (no restart)
`//reload <what>` needs level 100 and asks for confirmation.

| `//reload …` | Reloads |
|---|---|
| `config` | `.ini` configs (most values; features that register things still need a restart) |
| `html` (or `htm`) `[file\|dir]` | HTML dialogs and Community Board pages |
| `multisell` | `data\multisell\**` |
| `buylist` | `data\buylists\**` |
| `item` | Item templates |
| `skill` | Skills |
| `npc` | NPC templates (existing spawns keep old values until they respawn) |
| `quest [id\|name]` | Scripts (all, or one by name, e.g. `//reload quest MyNpc`) |
| `handler` | Handler scripts |
| `effect` | Skill effect scripts |
| `teleport` | Teleporter data |
| `zone`, `door`, `crest`, `cw`, `walker`, `enchant`, `access` | Zones, doors, crests, cursed weapons, walker routes, enchant data, access levels |
| `fakeplayerchat` | Fake-player chat lines |
| `localisations` | Multilingual strings |

**Needs a full restart:** new spawns, new NPC templates you want in the world, `config\Custom\*` switches that
register NPCs or commands, modules, `MasterHandler` changes, and anything in `General.ini`'s custom loaders.

## Testing

| Command | What |
|---|---|
| `//create_item <id> [count]` | Give yourself an item (`//itemcreate` opens a menu) |
| `//give_item_target <id> [count]` | Give an item to your target |
| `//create_coin` | Give coins or currency |
| `//spawn <npcId>` | Spawn an NPC at your position (temporary) |
| `//spawnat`, `//spawn_once`, `//list_spawns <npcId>`, `//respawnall`, `//unspawnall` | Spawn tools |
| `/loc` (one slash: a player command) | Print your coordinates (for spawn files) |
| `//gmshop`, `//buy <buylistId>` | Open GM shops or any buylist |
| `//teleportto <name>`, `//goto`, `//recall` | Movement |
| `//set_level <lvl>`, `//add_exp_sp` | Levelling tests |

There's no command that opens a multisell by id. Test one through its NPC or board button.

## Living World

| Command | What |
|---|---|
| `//phantom spawn\|count\|clear\|reload\|playstyle\|debug` | Phantoms ([living-world.md](living-world.md)) |
| `//reloadfakeplayers`, `//fakechat` | Fake players |
| `//record_route`, `//stop_route`, `//list_routes` | FPC walking routes |
| `//debug_on`, `//debug_off` | Bot debug output |

`//phantom`, `//reloadfakeplayers` and `//debug_on`/`//debug_off` are handled in code (`AdminPhantom.java`,
`AdminFakePlayers.java`) but have no line in `AdminCommands.xml`. They're meant to be used from the master (`admin`)
account. If one is refused, add a line for it (see below).

To confirm a command exists, search `game\data\scripts\handlers\chat\commands\admin\` for `"admin_<name>"`. Its level
is in `AdminCommands.xml`, one line per command:

```xml
<admin command="gmshop" description="…" accessLevel="100" />
```
