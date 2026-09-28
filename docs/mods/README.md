# L2J Offline (Living World) — modding docs

This pack is an offline Lineage II **Interlude** server:
- **L2JMobius**, "Living World" pack v0.1.25 from `Teravibes/L2-Living-Worlds`;
- a bundled JDK and MariaDB;
- an Interlude client;
- an optional AI "brain" that gives the fake players chat.

These pages explain how the pieces fit together and where to change what. The log of what we changed is
[CHANGELOG.md](../CHANGELOG.md).

## How it fits together

```
 Client\Interlude\system\L2.exe ──► Login server :2106 ──► Game server :7777 ──► MariaDB :3306
       (launcher → L2.bin)          login\ + LoginServer.jar      game\ + GameServer.jar     mariadb\data\l2jmobiusinterlude
                                                                  │
                                    Game server ⇄ Login server on 127.0.0.1:9014
                                                                  │ (fake-player chat)
                                                                  ▼
                                                   brain\fpc_brain.py  Flask on 127.0.0.1:5000 → LLM provider
```

- **The core** is `libs\GameServer.jar`. There is no Java source for it in this pack, so we can't change the core.
- **Everything else is data we can edit:**
  - the datapack under `game\data` (XML, HTML and Java scripts);
  - configs;
  - modules.

  The server compiles datapack and module scripts itself when it starts, using the bundled JDK, so they need no build
  step.

## Pages

| Page | Read it when you want to… |
|---|---|
| [server-overview.md](server-overview.md) | understand the folders, ports, logs, and what can and can't be modded |
| [operations.md](operations.md) | start, stop, update, back up, reset the DB, or understand the launcher |
| [config-reference.md](config-reference.md) | change rates, switch custom features on or off, change GM access |
| [datapack-reference.md](datapack-reference.md) | add or edit items, NPCs, skills, spawns, shops, teleports |
| [scripting.md](scripting.md) | write Java: NPC dialogs, voiced `.commands`, admin `//commands` |
| [modules.md](modules.md) | package a mod as a self-contained module you can switch off |
| [living-world.md](living-world.md) | tune the fake players and phantoms, or the AI chat brain |
| [community-board.md](community-board.md) | change the Alt+B board, including the cash shop |
| [client.md](client.md) | give new items, NPCs or skills their own name and icon, or change the client |
| [id-registry.md](id-registry.md) | pick ids for new items, NPCs, skills and multisells without clashes |
| [admin-commands.md](admin-commands.md) | find the reload, spawn and item GM commands for testing |

## Where do I change X?

| I want to… | Change | Apply with |
|---|---|---|
| Change XP, SP or drop rates | `game\config\Rates.ini` | restart (or `//reload config`) |
| Change an item's stats or price | `game\data\stats\items\NNNNN-NNNNN.xml` | `//reload item` |
| Add a new item | `game\data\stats\items\custom\` or a module | restart |
| Add an NPC shop list | `game\data\multisell\custom\<id>.xml` or `buylists\` | `//reload multisell` / `//reload buylist` |
| Add an NPC to the world | NPC in `stats\npcs\custom\`, spawn in `data\spawns\…` | restart |
| Change NPC dialog text | `game\data\html\…` or the script's `.htm` | `//reload html` |
| Add a `.command` | a module ([modules.md](modules.md)) | restart |
| Change the Alt+B board | `game\data\html\CommunityBoard\Custom\` | `//reload html` |
| Rebuild the cash shop | `python tools\cashshop\build_cashshop.py` | `//reload multisell`, `//reload html` |
| Tune the fake players | `game\config\Custom\FakePlayers.ini`, `game\data\Phantom*.xml` | `//reload config`, `//phantom playstyle` |
| Give an item its own client name and icon | client `.dat` files ([client.md](client.md)) | restart the client |

## Ground rules for modding
- **Log every change.** Add an entry to [CHANGELOG.md](../CHANGELOG.md) and commit it. The pack has its own git repo
  (see [operations.md](operations.md#version-control)).
- **Prefer additive changes.** Use `custom\` folders or modules rather than editing stock files. An update
  (`update.ps1`) overwrites the files listed in `launcher\patch-manifest.txt`.
- **Take ids from [id-registry.md](id-registry.md)** and record new ones there.
