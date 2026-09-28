# Config reference

All game configs are in `game\config\`. Every key is commented in its own file, so this page maps each file to its
purpose, lists the keys worth modding, and gives the current state.

**Applying changes:**
- `//reload config` reloads most `.ini` values live.
- A restart is needed for anything that decides what gets loaded or registered: custom loaders, `Enable…` switches
  that register commands or NPCs, and `ClassMaster.xml` spawning.
- The Control Panel's config editor (`tools\l2admin`, opened from `LivingWorld.exe`) edits these same files and keeps
  their comments.

## Core `.ini` files

| File | Purpose | Keys worth knowing (current value) |
|---|---|---|
| `Rates.ini` | XP, SP, drop, spoil, quest and karma rates | `RateXp`/`RateSp`/`RatePartyXp`/`RatePartySp` (1); `DeathDropChanceMultiplier`, `DeathDropAmountMultiplier`, `SpoilDrop*`, `RaidDrop*`, `HerbDrop*` (1); `DropChanceMultiplierByItemId` / `DropAmountMultiplierByItemId` (per-item overrides, e.g. `57,2` for double adena); `RateQuestReward*`; `BossDrop*` (extra raid loot list) |
| `General.ini` | Server-wide behaviour | `EverybodyHasAdminRights` (False); `EnableCommunityBoard` (True), `BBSDefault` (`_bbshome`); **custom loaders**: `CustomNpcData`, `CustomTeleportTable`, `CustomSkillsLoad`, `CustomItemsLoad`, `CustomMultisellLoad`, `CustomBuyListLoad` (all True; these make the `custom\` folders load); GM startup flags (`GMStartupInvulnerable`, `GMStartupInvisible` True) |
| `Player.ini` | New characters and player limits | `StartingAdena` (0), `StartingLevel` (1), `AutoLoot` (False), `MaxBuffAmount` (20), inventory, warehouse and weight limits |
| `Feature.ini` | Castles, clan halls, fortress-era features, and misc features | territory and siege details, clan hall functions |
| `NPC.ini` | NPC and monster behaviour | champion-style tweaks, guard aggro, raid respawns, corpse times |
| `PVP.ini` | Karma and PvP | karma drop, PK limits |
| `Olympiad.ini` | Olympiad period and rules | weekly period (changed by the pack) |
| `Siege.ini`, `SiegeSchedule.xml`, `ConquerableHallSiege.ini` | Castle and hall sieges | times, guards |
| `GrandBoss.ini` | Antharas, Valakas, Baium and the others | spawn intervals, entry limits |
| `Server.ini` | Game server network and identity | `GameserverPort` (7777), `RequestServerID`, `MaximumOnlineUsers` (2000) |
| `Database.ini` | DB connection and backup | `jdbc:mysql://localhost/l2jmobiusinterlude`, `root`, no password; `BackupDatabase` (False; see [operations.md](operations.md#back-up-and-restore)) |
| `Development.ini` | Debug switches | `NoQuests`, `NoSpawns` (useful for fast test boots), `ShowScriptLoadInLogs` |
| `Modules.ini` | Module framework | `EnableModules` (True), `ModulesRoot` (blank = `game\modules`) |
| `GeoEngine.ini`, `FloodProtector.ini`, `IdManager.ini`, `Threads.ini`, `Network.ini`, `Interface.ini` | Engine internals | leave these alone unless you need them |

## XML configs

| File | Purpose |
|---|---|
| `ClassMaster.xml` | Class-change NPC or popup. Currently **off** (`classChangeEnabled="false" spawnClassMasters="false"`). If enabled: 1st class free, 2nd class 1M adena. |
| `AccessLevels.xml` | Access levels: -1 (banned), 0 (player), 10–60, 70 (Admin, GM), 100 (Master, GM). Each level sets name color, title color, GM flags, and whether it can trade, drop, and so on. |
| `AdminCommands.xml` | Which access level each `//command` needs: 433 commands, written **without** the `admin_` prefix. Most need 100; 100 of them need only 30. |
| `Scripts.xml` | `<exclude>`/`<include>` rules for script loading. It excludes `handlers` (loaded by `MasterHandler` instead) and `package-info.java`. |
| `DynamicExpRates.xml` | Level-based XP multipliers. |

## `config\Custom\` feature switches
Each custom feature has its own file. The state below is as installed.

**On**

| File | What it does |
|---|---|
| `CommunityBoard.ini` | Custom Alt+B board (`CustomCommunityBoard = True`, turned on for the cash shop). Multisells, teleports, buffs and heal are on and free; delevel is off; currency is 57 (Adena). See [community-board.md](community-board.md). |
| `FakePlayers.ini` | Fake players, phantoms, bot chat and bot PvP rules ([living-world.md](living-world.md)) |
| `PhantomOlympiad.ini` | Phantom nobles in the Olympiad (roster 40, levels 76–80) |
| `AutoPlay.ini` | `.autoplay`, the built-in auto-hunt |
| `OfflineTrade.ini` | Offline private stores and crafting |
| `NpcStatMultipliers.ini` | Per-NPC-type HP, P.Atk and M.Atk multipliers (1.0 here; raid and grand boss values are set per type) |
| `RandomSpawns.ini` | Randomized spawn positions |
| `ServerTime.ini` | Shows server time |
| `ChatModeration.ini` | Chat admin tools |
| `AllowedPlayerRaces.ini` | Which races can be created (all) |

**Off** (flip `Enable…`/`…Enabled` to True, then restart):

| Group | Files |
|---|---|
| Automation and extras | AutoPotions, Banking (`.deposit`/`.withdraw`), OfflinePlay, SellBuffs, WarehouseSorting |
| Announcements and UI | BossAnnouncements, OnlineInfo, PvpAnnounce, ScreenWelcomeMessage |
| Gameplay rules | CancelReturn, ChampionMonsters, FactionSystem, FreeMounts, MerchantZeroSellPrice, StartingLocation, StartingTitle |
| PvP | FindPvP, PvpRewardItem, PvpTitleColor |
| NPC services | DelevelManager (NPC 1002000), NoblessMaster (NPC 1003000), Transmog, Wedding |
| Accounts and security | Captcha, PasswordChange, PremiumSystem (+ PC Café), WalkerBotProtection |
| Other | CustomMailManager, MultilingualSupport |

**Settings only** (no on/off switch): ClassBalance, DualboxCheck (all 0 = unlimited), PrivateStoreRange,
SchemeBuffer (4 schemes, costs item 57).

## Login server (`login\config\`)

| File | Keys |
|---|---|
| `Server.ini` | `LoginserverHostname`/`Port` (0.0.0.0:2106), `LoginHostname` (127.0.0.1:9014), `AutoCreateAccounts` (True), `AcceptNewGameServer` (True), `ShowLicence` |
| `Database.ini` | Same DB as the game server (pool of 5) |
| `Network.ini`, `Threads.ini`, `Interface.ini` | Internals (`EnableGUI`) |
| `..\data\servername.xml` | Server id → name (2 = Sieghardt) |
