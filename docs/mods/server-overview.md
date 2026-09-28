# Server overview

## What's in the pack

| Path | What it is | Tracked in git |
|---|---|---|
| `Start-Server.bat` / `Stop-Server.bat` | One-click start and stop; they run `launcher\launcher.ps1` / `stop.ps1` | yes |
| `LivingWorld.exe` | GUI launcher and Control Panel: start/stop, updates, config editor (`tools\l2admin`), Discord presence | no |
| `launcher\` | Boot, stop and update scripts, `launcher.ini`, `version.txt`, `patch-manifest.txt` | scripts and ini |
| `login\` | Login server working dir: `config\`, `data\servername.xml`, `log\` | config and data |
| `game\` | Game server working dir: `config\`, `data\` (datapack), `modules\`, `log\`, `presence.json` | config, data, modules |
| `libs\` | `GameServer.jar`, `LoginServer.jar`, HikariCP, MySQL connector, slf4j | no |
| `jre\` | A full **JDK** 25 (Temurin); needed because scripts are compiled at runtime | no |
| `mariadb\` | Portable MariaDB. `data\` **is the live database** | no |
| `db_installer\sql\` | Schema: `login\` (4 tables), `game\` (96 files) | yes |
| `backup\` | Target folder for DB backups | no |
| `brain\` | Optional Python chat service for fake players ([living-world.md](living-world.md)) | code and knowledge |
| `tools\` | `l2admin\` (the Control Panel's config editor), `cashshop\` (cash shop generator) | yes |
| `Client\Interlude\` | The game client ([client.md](client.md)) | no |
| `docs\`, `CHANGELOG.md`, `CLAUDE.md` | These docs, the change log, and notes for Claude sessions | yes |

## What you can and can't change

| Layer | Where | Can we change it? |
|---|---|---|
| Core engine (packets, combat formulas, AI engine, managers, the module framework, fake-player engine) | `libs\GameServer.jar` | **No.** There's no source here. The jar is built by the upstream dev repo (`L2J_Mobius_CT_0_Interlude` + `dist\`) with Ant and JDK 25. |
| Handlers: bypasses, admin/voiced/user commands, item handlers, skill effects and targets, Community Board | `game\data\scripts\handlers\` (Java) | Yes; compiled at startup |
| Quests, AI, custom NPC scripts, events | `game\data\scripts\{quests,ai,custom,events}\` (Java) | Yes |
| Game data: items, NPCs, skills, spawns, shops, zones, teleports, HTML | `game\data\**` (XML and HTML) | Yes |
| Modules | `game\modules\<name>\` | Yes; the cleanest way to add features |
| Configs | `game\config\*.ini`, `config\Custom\*.ini`, `login\config\` | Yes |
| Client look (names, icons, meshes) | `Client\Interlude\system\*.dat`, `*.utx` | Yes, with client tools ([client.md](client.md)) |

A mod that needs a core change can't be done here. Examples: a new packet, a new skill effect *type* the engine
doesn't know, or a change to a formula inside the jar.

Skill effects and handlers, on the other hand, **are** scripts: 146 effect classes live in
`scripts\handlers\skill\effects\`. A new effect type is often possible as a script.

## Ports

| Service | Address | Set in |
|---|---|---|
| Login (client connects here) | `0.0.0.0:2106` | `login\config\Server.ini` → `LoginserverHostname` / `LoginserverPort` |
| Game server ↔ login server | `127.0.0.1:9014` | `login\config\Server.ini` → `LoginHostname`; `game\config\Server.ini` |
| Game (client) | `:7777`, protocol 746 | `game\config\Server.ini` → `GameserverPort`, `AllowedProtocolRevisions` |
| MariaDB | `localhost:3306`, user `root`, no password, DB `l2jmobiusinterlude` | `launcher\launcher.ini`, `game\config\Database.ini`, `login\config\Database.ini` |
| Brain | `127.0.0.1:5000` (`POST /chat`) | hardcoded in `brain\fpc_brain.py` |

The game server registers with the login server as server id 2 ("Sieghardt"). This comes from `game\config\hexid.txt`
and the `gameservers` row that the login SQL pre-inserts.

## Java settings
- **Game** (`game\java.cfg`): `-Xms2g -Xmx4g -XX:+UseZGC -Dfile.encoding=UTF-8`, with the Mobius log manager. The game
  server uses about 4 GB when running.
- **Login** (`login\java.cfg`): `-Xms128m -Xmx256m -XX:+UseZGC`.

## Logs

| Log | Where |
|---|---|
| Game console and errors | `game\log\java*.log`, `game\log\error*.log` |
| Chat, items, GM actions, enchants | `game\log\chat*`, `item*`, `gmaudit*`, `enchant*`; also `accounting*` and `olympiad.csv` |
| Login | `login\log\java*`, `error*` |
| MariaDB | `mariadb\data\*.err` |
| Launcher | its own console only (no file) |

Rotation is set in `game\log.cfg`: 20 files of 100 MB each.

**Script compile errors** show up in the game console and `game\log\error*.log` at startup. Check there first when a
Java script or module change "does nothing".

## Startup load order (what to expect in the console)
1. Configs load.
2. Datapack XML loads: items (with the `custom\` folders when the `General.ini` custom loaders are on), NPCs,
   skills, multisells, buylists, spawns and so on.
3. Scripts compile. The server scans `data\scripts`, skipping what `config\Scripts.xml` excludes. Handlers come in
   through `handlers\MasterHandler.java`.
4. Modules load (`[Modules]` lines).
5. Fake players and phantoms spawn.
6. The server listens on 7777.
