# Adventurer's Guide module

A new-player guide on the Alt+B Community Board. Press Alt+B and click **Guide** (or type `.guide`). Every page is
built for the character looking at it.

## Pages

| Page | What it shows |
|---|---|
| Home | Race, class and level, how far the next class change is, the nearest quests and the best hunting spot, and warnings about the kit: no weapon, no shots for its grade, gear below the grade you can wear |
| Quests | Tabs for Available, In progress, Coming soon (within 5 levels) and Done, nearest first. Each quest has a detail page with its story, first step, start NPC, and Mark / Teleport near / NPCs and mobs buttons |
| Hunt | Hunting spots with monsters from your level -3 to +4, close and busy ones first. A spot's page lists its monsters with level colours, base XP/SP, aggression and a Mark for the nearest group |
| Next steps | The class-change quests your current class can take (Path to, Trial/Testimony/Test, Saga), with the Class Masters of the nearest town; after the 3rd class, the noblesse quests |
| Gear | The grade each level can wear, your weapon and armor grade, the matching shot and how many you carry, and buttons to the Merchant, Cash Shop and Drop Search pages |
| Towns | Every town, nearest first, then each town's gatekeepers, warehouses, grocers, weapon and armor traders, Class Masters, skill trainers, pet managers and symbol makers |
| Tips | Short pages from `data/tips.txt` |

**Mark** puts the radar marker and map flag on the spot. **Teleport** goes to the gatekeeper destination nearest the
spot for that destination's normal fee, and is free up to level 20. It's refused in combat, while casting, dead, in
a duel, the Olympiad, a siege or PvP zone, while flagged or with Karma.

**Hints:** characters up to level 40 get a one-line reminder at login. On level up, a message says how many new quests
opened, and when a class change or a new gear grade becomes available.

## How it knows what you can do

- **Quests.** The server's quest scripts check race, class and level by hand, so they can't be asked. The guide uses
  the client's own quest table instead (`questname-e.dat`), which lists each quest's level range, allowed classes,
  prerequisite quest and start NPC. A quest shows as Available when:
  - the server has a script for it;
  - your level is in its range;
  - your current class is allowed;
  - you have a clan, if it's a clan quest;
  - you have finished its prerequisite;
  - and you haven't finished it already, unless it's repeatable.
- **Hunting spots.** They come from the monster spawns in `game\data\spawns`. A spawn is grouped under the name of the
  gatekeeper destination within 9000 units of it, or named after its spawn file.
- **Towns.** Their NPCs come from the `*NPCs.xml` town spawns. A merchant's kind comes from what its buylists sell.

All of this is in the tables under `data\`, written by `tools\guide\build_guide_data.py` (see `tools\guide\README.md`).
Rebuild them after changing spawns, gatekeepers or NPCs, and restart.

## Settings (`config/module.ini`)

| Key | Default | What |
|---|---|---|
| `Enabled` | True | Master switch |
| `DataPath` | `modules/adventurer-guide/data` | Where the tables are, relative to `game\` |
| `TeleportEnabled` | True | Show the teleport links |
| `TeleportFeeMultiplier` | 1.0 | Times the gatekeeper fee |
| `FreeTeleportMaxLevel` | 20 | Teleports are free up to this level |
| `HuntLevelBelow`, `HuntLevelAbove` | 3, 4 | The monster level band for Hunt |
| `LoginHintMaxLevel` | 40 | The login reminder goes to characters up to this level; 0 turns it off |
| `LevelUpHints` | True | The level-up messages |

## Enable, disable, remove

- **Enable or disable:** set `Enabled` in `config/module.ini`, then restart the server.
- **Remove:** delete this directory while the server is stopped, and take the Guide button out of
  `game\data\html\CommunityBoard\Custom\navigation.html`. The module has no database tables.

It registers `_bbs_guide` (a Community Board command) and `.guide`, and owns everything under this directory. The only
file outside it is that board menu, which links to `_bbs_guide`.
