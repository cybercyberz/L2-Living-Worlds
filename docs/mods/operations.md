# Operations: run, update, back up

## Start and stop
- **Start:** `Start-Server.bat`, or Start in `LivingWorld.exe`. The GUI runs the servers with `javaw` and no console
  windows.
- **Stop:** `Stop-Server.bat`. It stops the login server, the game server, the brain and the bundled MariaDB. **It
  leaves the game client open**: you're disconnected, and you log back in after restarting.
- The launcher refuses to start while a process it recorded in `launcher\.processes.json` is still alive. Stop first.

### What `launcher\launcher.ps1` does, in order
1. **Pre-flight.** Checks for Java, `mysqld.exe` (or something already on port 3306) and both jars.
2. **Java.** Uses `[java] JavaHome`, then the bundled `jre\`, then `JAVA_HOME`, then `PATH`.
3. **Database.** If nothing is on 3306, starts `mariadb\bin\mysqld --datadir=mariadb\data`. On the very first run it
   initializes the data dir. It waits up to 60 s for the port.
4. **Schema.** Runs only if `launcher\.db_installed` is missing.
   - If the database already has tables, it **skips the import**. This is on purpose: 15 of the SQL files
     `DROP TABLE` first.
   - Otherwise it imports `db_installer\sql\login\*.sql`, then `sql\game\*.sql`.
5. **Servers.** Starts the login server, then 3 s later the game server. Each runs from its own folder with its own
   `java.cfg`.
6. **Brain** (optional, `StartBrain=true`). Runs `brain\setup_brain.bat --auto`. It only starts if the brain was
   configured once before.
7. **Client** (optional, `LaunchClient=true`). Waits for port 7777, then opens `ClientExe`.

### `launcher\launcher.ini`

| Section | Keys |
|---|---|
| `[java]` | `JavaHome` (blank = bundled) |
| `[database]` | `Host`, `Port=3306`, `User=root`, `Password=`, `Database=l2jmobiusinterlude`, `MysqlBin=mariadb\bin`, `DataDir=mariadb\data` (blank = use an external MySQL/XAMPP), `AutoStartMysql` |
| `[servers]` | `StartLogin`, `StartGame`, `StartBrain` |
| `[client]` | `ClientExe`, `LaunchClient` |
| `[discord]` | `Enabled`, `ClientId` |

## Accounts and GM access
- **Auto-created accounts.** `login\config\Server.ini` has `AutoCreateAccounts = True`: any name and password
  creates an account on first login.
- **GM access.** Every character on the **`admin`** account becomes master GM (access level 100) when it enters the
  world. This hook is compiled into the jar (`EnterWorld`). Other accounts are normal players.
- **Access levels.** These are defined in `game\config\AccessLevels.xml` (see [config-reference.md](config-reference.md)).

## Updates (`scripts\Check-Updates.bat` or the launcher button)
`launcher\update.ps1` works like this:
1. Checks GitHub releases of `Teravibes/L2-Living-Worlds` against `launcher\version.txt`.
2. Asks before doing anything.
3. Runs `stop.ps1` and downloads the `vX.Y.Z-patch` zip.
4. Overlays the zip on the pack with `robocopy`, skipping `mariadb\`.
5. Stamps the new version.

It can also refresh `LivingWorld.exe`.

**What an update overwrites:**
- `libs\GameServer.jar`, always;
- every path listed in `launcher\patch-manifest.txt`. The list accumulates across releases and currently includes:
  - `handlers\MasterHandler.java`, `AdminReload.java`, `AdminPhantom.java`
  - `Phantom*.xml`, `BotClans.xml`
  - `FakePlayers.ini`, `Olympiad.ini`, `NpcStatMultipliers.ini`, `PhantomOlympiad.ini`
  - the module files
  - `tools\l2admin\*`, `brain\*`, the launcher scripts
  - `Start-Server.bat` and `Stop-Server.bat`

Your database is never touched.

**Before updating:**
1. Commit your work.
2. Run the update.
3. Run `git status` and `git diff` to see exactly which of your changes the patch reverted.
4. Reapply them, then commit.

This is the main reason the pack is under git.

## Database
- **Location.** `mariadb\data\l2jmobiusinterlude`, user `root`, no password.
- **Command-line client.** Run `mariadb\bin\mysql.exe -u root l2jmobiusinterlude` while the server is running.

### Back up and restore
With the DB running (the server is up, or you started only MariaDB):

```bash
mariadb/bin/mysqldump.exe -u root l2jmobiusinterlude > backup/l2j-$(date +%F).sql
```

Restore with the game server stopped and MariaDB still running:

```bash
mariadb/bin/mysql.exe -u root l2jmobiusinterlude < backup/l2j-YYYY-MM-DD.sql
```

The server has a built-in backup (`BackupDatabase` in both `Database.ini` files, off by default). Its
`MySqlBinLocation = ../../mariadb/bin/` is resolved from `game\` or `login\`, which points at `D:\game\mariadb\bin`
rather than the pack's `mariadb\bin`. It probably needs changing to `../mariadb/bin/` before it will work. This hasn't
been verified.

### Reinstall the schema (wipes everything)
1. Stop the server.
2. Back up if you need anything.
3. Drop the database.
4. Delete `launcher\.db_installed`.
5. Start again.

The launcher imports the schema only into an empty database.

## Version control
The pack has its **own git repo** (`D:\game\L2J-Offline-OneClick\.git`). The `D:\game` repo ignores this folder.

- **Tracked.** Only files we edit: configs, datapack (minus geodata and crests), modules, schema SQL, launcher
  scripts, brain code and knowledge, tools, and docs. The allow-list is in `.gitignore`.
- **Never tracked.**
  - `Client\`, `jre\`, `mariadb\` (the live DB), `libs\`, `backup\`
  - `brain\.env`, which holds an API key
  - logs and runtime state
- **Line endings.** `core.autocrlf` is `false` in this repo, so files keep their own endings. Stock files are mostly
  CRLF.
- **Workflow.** Make a change, test it in game, add a `CHANGELOG.md` entry, then commit with a plain summary line and
  a body saying what and why.
