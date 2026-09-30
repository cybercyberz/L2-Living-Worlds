# Changelog

Every change we make to this pack. Newest first.

Each entry has a date, what changed and why, the files touched, and **how to apply** it:
- restart;
- `//reload multisell`, `//reload html` or `//reload config`;
- a client change.

The format follows [Keep a Changelog](https://keepachangelog.com/): **Added**, **Changed**, **Fixed**, **Removed**.
Every entry is committed to this folder's git repo (see [docs/operations.md](docs/operations.md#version-control)).

## 2026-09-30 — Phantom Combat: party healers that know the party

### Added
- **A party healing section in `phantom-combat`** (`PartyHealing`, on by default). The party manager in
  `GameServer.jar` heals by fixed HP% thresholds (60%, or 80/90% in raids) and only sees another healer if that one
  claimed the same target in the same second or is casting on it right now. So:
  - heals didn't match the gap;
  - below 50% HP every healer piled onto one member;
  - group heals, cleanses and recharges weren't coordinated at all;
  - the 4.5 s res claim ran out before a 6 s Resurrection landed, so a second healer could raise the same corpse.

  Now each recruited healer (Cleric, Oracles, Bishop, Elders, Cardinal, Saints) decides for itself, every 250 ms:
  - **What it knows** (`PartyBoard.java`): every member's HP, the damage it took per second over the last 3 s, and a
    ledger of every heal, group heal, cleanse, recharge and res anyone in the party has started, including yours.
    Estimates use the game's own heal formula (power, spiritshots, M.Atk, heal bonus, class multiplier). Finished or
    aborted casts drop out on their own, and a res claim holds until the corpse stands up.
  - **What it does** (`HealerBrain.java`), first need first:
    1. save a member predicted below 35% with the fastest heal that lifts it back (Celestial Shield on a tank or you
       when heals can't keep up);
    2. party crisis: Benediction or Balance Life, one healer per party;
    3. cleanse: paralyze or petrify first, then poison or bleed, with Vitalize when HP is also needed;
    4. res: you first, then the tank, healers, anyone;
    5. group heal when 3 or more members still need it after heals on the way;
    6. single heal on the biggest role-weighted need, with the cheapest heal per HP that doesn't exceed 115% of the gap;
    7. Recharge, Mass Recharge or Invocation.

    One healer per target for res, cleanse and recharge. A slow heal is cancelled if another heal already filled the
    target.
  - **Wasted casts are stopped** (`VetoWastedHeals`). The module's skill-use listener is now a function listener, so
    it can stop the manager's own heal, group heal, res, cleanse or recharge before it costs MP, when another caster
    already covers it. Your casts and chat orders ("heal me", "recharge X") are never stopped.
  - **Skills now used** that the manager never cast: Vitalize, Restore Life, Benediction, Balance Life, Celestial
    Shield, Mass Recharge, Invocation.
  - **The manager keeps** buffs, following, MP rest, AoE dodging, raid positioning and every chat order. While a healer
    carries out an order, the brain leaves it alone.
- New settings: `PartyHealing`, `HealTickMs`, `CriticalPercent`, `MinHealPercent`, `OverhealLimitPercent`,
  `GroupHealMinTargets`, `EmergencySkills`, `VetoWastedHeals`. `PlaystyleAccess.java` has a third handle group (the
  members' order fields). If it fails on a future jar, party healing alone switches off.
- **Files:** `game/modules/phantom-combat/` (`scripts/PartyBoard.java`, `scripts/HealerBrain.java` new;
  `scripts/PhantomCombatModule.java`, `scripts/PlaystyleAccess.java`, `config/module.ini`, `module.json`, `MODULE.md`,
  `TESTING.md`); `docs/modules.md`, `docs/living-world.md`, `docs/README.md`.

**Apply:** restart the server. The startup line ends with `party healing on (every 250 ms, wasted casts stopped).`
In-game checks: `game/modules/phantom-combat/TESTING.md`, test H.

## 2026-09-30 — Phantom Combat: pacing and party DPS merged into one module

### Changed
- **`phantom-skill-pacing` and `phantom-party-dps` are now one module, `phantom-combat`** (`game/modules/phantom-combat/`).
  Both decided when a phantom may cast next. Both overrode the engine's "next cast" gate and each had its own
  skill-use listener, and the DPS module depended on the pacing one. The server log showed the DPS module loading
  *before* the pacing module despite that dependency. Now there's one module with three switchable sections, and one
  listener that runs the steps in a fixed order (meter → skill cooldown → tempo follow-up):
  - **Skill pacing** (`SkillPacing`, all phantoms): `paceMs` is a per-skill cooldown. Same as before.
  - **Party tempo** (`PartyTempo`, `BurnPhase`, recruited DPS members): follow-up casting, resumed swings and burn
    phase. Same as before.
  - **Meter** (`Meter`): `.dps`. Same as before.
- **A rule replaces the dependency:** every phantom whose casting pace the module sets also gets each skill's own
  `paceMs`. With `SkillPacing = False` and `PartyTempo = True`, field hunters get the stock engine back, but party tempo
  members still keep their per-skill gaps. Before, turning pacing off made the tempo quietly erase `paceMs`.
- **Settings:** one `config/module.ini` with a section per part. `FastFollowUp` is now `PartyTempo`; every other key
  keeps its name and default. Neither old config had been edited, so there is nothing to carry over.
- **Code:** split by responsibility instead of by module. `PlaystyleAccess.java` holds every reflection handle, in two
  groups: if one breaks on a future jar, only the sections that need it switch off. The rest is `SkillPacing.java`,
  `PartyTempo.java`, `DpsMeter.java`, and `PhantomCombatModule.java` for the wiring. The logic is moved, not rewritten.
- `game/data/PhantomPlaystyles.xml`: the header's `paceMs` line names `phantom-combat`.

### Fixed
- **`docs/living-world.md`:** the pacing note had been inserted inside the data-files table, splitting its last row
  off. The note now sits after the table.

- **Files:** `game/modules/phantom-combat/` (new); `game/modules/phantom-skill-pacing/` and
  `game/modules/phantom-party-dps/` (removed); `game/data/PhantomPlaystyles.xml` (header comment);
  `docs/modules.md`, `docs/living-world.md`, `docs/README.md`.

**Apply:** restart the server. The startup line reads
`Phantom Combat: skill pacing on (49 paced entries, 26 classes); party tempo on (...); burn phase on (...); meter on.`

## 2026-09-30 — Phantom Party DPS: faster casting for party phantoms, and a DPS meter

### Added
- **The `phantom-party-dps` module** (`game/modules/phantom-party-dps/`). The party manager in `GameServer.jar` plays
  members for realism, not damage: it decides once a second, the playstyle engine then waits 1.6–2.5 s after every
  skill, a nuker never auto-attacks so it idles through that wait, and a fighter's swing stops after a skill until the
  next tick. The module, for recruited DPS members (WARRIOR, DAGGER, ARCHER, MONK, NUKER by default):
  - **Fast follow-up:** when a member starts a cast, the engine's pause is cut to 250–500 ms, and as soon as the cast
    ends the next skill is picked with the engine's own `PhantomPlaystyleEngine.pick`. A fighter with nothing ready
    resumes swinging at once.
  - It only follows the manager's lead: the target the member was already hitting, and it stops when the member moves,
    sits, holds, eases aggro, recovers after a res, is in PvP, or changes target. Raid bosses and minions stay with the
    manager's raid gates. It never picks targets.
  - **Burn phase:** from the party's damage over the last 4 s, a mob that will die within 5 s gets no DEBUFF, CONTROL
    or OPENER casts; the full playstyle returns on the next target.
  - **`.dps` meter:** DPS, share, casts and active % per party member, for the current or last fight and the session.
    `.dps reset` clears it.
  - Settings in `config/module.ini` (pace, window, burn threshold, roles, debug). It depends on
    `phantom-skill-pacing`, which keeps the per-skill `paceMs` gaps.
  - No jar change: global skill-use, attack and damage events, plus reflection on the party manager's member records
    and the engine's per-member state. On a jar whose classes differ it logs one warning and only the meter runs.
- **Files:** `game/modules/phantom-party-dps/` (new), `docs/modules.md`, `docs/living-world.md`, `docs/README.md`.

**Apply:** restart the server. Module Java compiles only at startup. Measure before and after with `.dps` (see the
module's `TESTING.md`).

## 2026-09-30 — Phantom playstyles: paceMs is per skill; header matches the engine

### Fixed
- **A paced skill stalled a phantom's whole rotation.** The engine in `GameServer.jar`
  (`PhantomPlaystyleEngine.pick`) used an entry's `paceMs` as the gate for every next cast. So after Stun Attack
  (`paceMs="6000"`) a Warrior cast nothing else for about 6 s, and after Lightning Strike (15000) it went silent for
  15 s. 49 entries have a `paceMs`. The new **`phantom-skill-pacing` module** (`game/modules/phantom-skill-pacing/`)
  makes `paceMs` a per-skill cooldown instead:
  - it zeroes `paceMs` in the loaded playstyle data, so the engine waits only its default beat (about 1.6–2.5 s)
    between casts;
  - when a phantom casts a paced skill, it disables just that skill for `paceMs`, which the engine already skips;
  - phantoms only (field hunters, party recruits, alt companions); real players keep normal reuse;
  - it re-applies itself within 2 s of `//phantom playstyle`; `Enabled = False` restores the stock behavior.

  The jar is not patched: the module uses the global `ON_CREATURE_SKILL_USE` event and reflection on
  `PhantomPlaystyleData`.
- **The `PhantomPlaystyles.xml` header was wrong about PANIC and LIMIT.** It said "LIMIT additionally needs a ready
  healer", but the engine checks no conditions for either: a LIMIT waits for a healer only with `HEALER_READY` in its
  `when`, and a PANIC waits for danger only with `SELF_HP_BELOW`/`UNDER_ATTACK`. Every entry already does this, so only
  the text changed. The header now also says that PANIC and LIMIT ignore the MP reserve, that PANIC ignores the beat,
  that OPENER fires once per target, and that ROTATION/AOE/DEBUFF/CONTROL behave the same. The `paceMs` line describes
  the per-skill meaning.
- **Files:** `game/data/PhantomPlaystyles.xml` (header comment only), `game/modules/phantom-skill-pacing/` (new),
  `docs/living-world.md`, `docs/modules.md`, `docs/README.md`.

**Apply:** restart the server. Module Java compiles only at startup.

## 2026-09-29 — Role Buffer: the pet on/off line no longer overlaps

### Fixed
- **The "Also buff my pet/summon: On / Off" line on the Buffer page.** The client drew the On/Off links on top of the
  text beside them, because it misplaces a link that shares a line with plain text. The line is now a small table
  with a cell for each piece:
  - "Buff my pet/summon:";
  - the state, green On or red Off;
  - a "Turn off" / "Turn on" link;
  - on the row below, the pet's name and buff count with a "Details" link, or "No pet out now".
- **File:** `game/modules/role-buffer/scripts/RoleBufferModule.java`.

**Apply:** restart the server. Module Java compiles only at startup.

## 2026-09-29 — Role Buffer: one-click buff packages per role

### Added
- **The `role-buffer` module** (`game/modules/role-buffer/`): Alt+B → **Buffer** now shows one-click packages for
  seven roles:
  - Warrior, Dagger, Archer and Tank;
  - Mage, Summoner and Healer/Support.

  Each package gives every buff, dance and song that role benefits from, at the skill's highest level, for an hour.
  - **Every package fills the 20 buff slots** without two skills of the same stack type. It includes one all-in-one
    buff: Chant of Victory, Prophecy of Fire, Water or Wind, or Magnus' Chant. It also fills up to 12 dance/song slots.
  - **The page recommends the package for the character's class**, and **Details** lists each buff with its icon,
    level and effect ("Might 3: P. Atk +15%").
  - **A Pet package** goes on the pet or servitor at the same time. It's switchable per character.
  - **Heal** and **Remove buffs** buttons.
  - **`.buff`** opens the page; `.buff <role>` applies a package from chat.
  - Settings in `config/module.ini`: duration, price, the pet default, buffing in combat, the cooldown, debug logging.
  - It's self-contained, so it can be shared by copying the folder (see its `MODULE.md`).
- **`tools/buffer/build_buffer_data.py`:**
  - reads the 99 buff skills from `game/data/stats/skills`;
  - writes `data/buffs.tsv`: level, dance or buff, stack type, and an effect summary;
  - checks `data/packages.txt`: known ids, no clashing stack types, and the slot caps from `Player.ini`.

### Changed
- **`game/data/html/CommunityBoard/Custom/navigation.html`:** the Buffer button opens `_bbs_buffer`. The stock pages
  `Custom/buffer/*.html` and `_bbsbuff` are untouched but no longer linked.

### Fixed
- **"Clicking a buff repeatedly doesn't give it; reopening the board helps."** The core source shows two causes on the
  stock buffer:
  - the server's flood protector silently drops any board click within 300 ms of the previous one
    (`FloodProtectorServerBypassInterval = 3` ticks);
  - the stock buttons give level 1, which can't replace a stronger buff of the same kind.

  The Role Buffer gives the whole package in one click at max level, says in chat what it gave, puts the result and
  a clock on the refreshed page, and answers "one moment" to a click within a second of the last one. A click faster
  than 300 ms is still dropped by the core before the module sees it. I haven't reproduced the old bug in game.

**Files:**
- `game/modules/role-buffer/` (new): `module.json`, `config/module.ini`, `scripts/RoleBufferModule.java`,
  `data/packages.txt`, `data/buffs.tsv`, `MODULE.md`, `TESTING.md`;
- `tools/buffer/` (new);
- `game/data/html/CommunityBoard/Custom/navigation.html`;
- `docs/community-board.md`, `docs/modules.md`, `docs/README.md`.

**Apply:** restart the server, since module Java compiles only at startup. Then open Alt+B, which also picks up the new
Buffer button.

## 2026-09-29 — Adventurer's Guide: a Go teleport for every monster

### Added
- **A Go link on every monster row of a hunting spot** (Alt+B → Guide → Hunt → a spot), next to Mark. Before this,
  the only teleport on the page was "Teleport near", which lands on the gatekeeper destination nearest the spot's
  centre, often far from the monster you want.
  - **Where it lands:** a few steps (350 units) from the live monster of that kind nearest the group Mark flags, on
    the side facing the nearest gatekeeper, and kept on this side of walls by geodata. If none is alive, it lands on
    the group's spawn point with the height taken from geodata.
  - **The fee** is the fee of the gatekeeper destination nearest the group, shown in grey after Go. It's free up to
    `FreeTeleportMaxLevel` (20). The same checks as the other teleports apply: combat, casting, Karma, and so on.
  - **Safety:** the bypass is `go <area> <npcId>`, so it can only reach groups the guide lists. The page warns that
    Go lands among the monsters. "Teleport near" stays as the town-side option.
- **Files:**
  - `game/modules/adventurer-guide/scripts/AdventurerGuideModule.java`: the Go column, `goToMob` and `landingSpot`.
    The teleport was split into `canTeleport` / `doTeleport` so `tp` and `go` share it.
  - `game/modules/adventurer-guide/MODULE.md`, `TESTING.md` and `docs/community-board.md`.

**Apply:** restart the server. Module Java compiles only at startup.

## 2026-09-29 — l2mod: stricter checks when decrypting client files

### Changed
- **`tools/l2mod/l2mod/crypto/ver41x.py`:**
  - **`decrypt` checks the footer CRC** before decrypting, so a truncated or corrupted file fails with a clear
    error instead of somewhere inside zlib. All 43 Ver41x client files pass the check.
  - **A keyless `decrypt`** uses the official key for the header's version. That key never works on this client's
    files, so when it fails the error now says to use the l2encdec key, via `dat.decrypt()`.
  - **A malformed header** (a non-numeric version, or a file too short) raises `Ver41xError` instead of
    `ValueError`.
  - **The docstring** now says exactly what round-trips: re-encrypting a file's own compressed stream rebuilds it
    byte for byte, but recompressing it with Python's zlib doesn't.
- **`tools/l2mod/tests/test_dat.py`:** four new selftest gates:
  - encrypt, then decrypt, gives the same data back (including edited data);
  - a flipped byte fails the CRC check;
  - a bad version raises `Ver41xError`;
  - a keyless decrypt names the l2encdec key.
- **`docs/client.md`:** the `user.ini` note now points at `dat.decrypt` / `dat.encrypt`.
- **`tools/l2mod/NOTES.md`:** records the CRC check and the two `Lineage2Ver111` files it doesn't cover.

**Apply:** nothing. This is tooling only. `python tools/l2mod selftest` passes (20 tests).

## 2026-09-29 — Guide button removed from the board home page

### Removed
- **`game\data\html\CommunityBoard\Custom\home.html`** is back to stock. The "Open the Guide" button and its text in
  the middle of the page weren't needed, since the **Guide** button in the left menu does the same. The button also
  overlapped the text above it.
- `docs/community-board.md` and the module's `MODULE.md` and `TESTING.md` no longer mention it.

**Apply:** `//reload html`, then reopen Alt+B.

## 2026-09-29 — A quick right-click no longer resets the camera

### Changed
- **The client's right-mouse binding** (`Client\Interlude\system\user.ini`, `[Engine.Input]`) was:

  `RightMouse=CameraRotationModeOn | CameraRotationModeOff | FixedDefaultCamera OnRelease MaxPressedTime=200.0`

  So any right-click shorter than 200 ms snapped the camera back to its default view. It's now:

  `RightMouse=CameraRotationModeOn | CameraRotationModeOff`

  That's the stock alternative the file already had commented out. Holding right-click to rotate still works.
  **Home** still resets the camera on purpose, and **PageUp/PageDown** cycle the fixed views.
- The original is kept as `user.ini.bak`, next to the patched file. The client folder isn't tracked, so this entry
  is the record of the change. To redo it after a client reinstall: decrypt `user.ini` with
  `tools/l2mod/l2mod/crypto/ver41x.py` (l2encdec key), make the same edit, and re-encrypt. See
  [docs/client.md](docs/client.md#launching).
- **`docs/client.md`:** a note on where key bindings live and how to edit `user.ini`.

**Apply:** a client change. Edit it with the client closed, then relaunch the client.

## 2026-09-29 — CLAUDE.md: the GitHub fork workflow

### Changed
- **`CLAUDE.md` gets a "GitHub: upstream and our fork" section.** It records:
  - what upstream is and the newest version seen (v0.1.25, checked 2026-09-29);
  - the fork's branches and the `base-v0.1.25` tag;
  - the path map, and what's never carried or differs on purpose;
  - the replay-after-every-commit steps (clone with `core.longpaths`);
  - how a selective update goes.

  Future sessions keep the fork in sync without re-deriving any of this.
- **The "Updates overwrite files" note** now says to update through the fork instead of `update.ps1`.
- **The "core can't change" note** now says the core's source is in the fork, with no build set up.

**Apply:** nothing. This is docs only.

## 2026-09-29 — GitHub fork of upstream, and forksync

### Added
- **The fork [cybercyberz/L2-Living-Worlds](https://github.com/cybercyberz/L2-Living-Worlds)**, branch
  `living-world-mods`. It's upstream `v0.1.25` (tag `base-v0.1.25`, `ba8c9927`) with our mods on top, one fork
  commit per local commit. The first one is the Community Board cash shop, which our baseline commit already
  carried. We can now take upstream updates selectively against a known base, instead of letting `update.ps1`
  overwrite files.
- **`tools/forksync/forksync.py`.** It maps paths between this install and upstream's source layout:
  - `replay` carries local commits to the fork;
  - `import` brings fork or upstream commits back here as working-tree changes;
  - `map` shows where a path lives.
- **`docs/operations.md`:** a new section, [The GitHub fork](docs/operations.md#the-github-fork).
  **`docs/README.md`** links to it.

**Apply:** nothing. The server doesn't use these files.

## 2026-09-29 — Adventurer's Guide: a new-player menu on Alt+B

### Added
- **The `adventurer-guide` module** (`game\modules\adventurer-guide\`). It adds a **Guide** tab to the Alt+B board
  (also `.guide`) that tells a player what to do next. Every page is built for the character viewing it:
  - **Home:** race, class, level, how far the next class change is, the nearest quests and the best hunting spot.
    It also warns about the kit: no weapon, no shots for the weapon's grade, or gear below the grade they can wear.
  - **Quests:** tabs for Available, In progress, Coming soon (within 5 levels) and Done, nearest first. Each quest
    opens a page with its story, first step and start NPC, plus Mark on map, Teleport near, and "NPCs and mobs"
    (the Quest Navigator window).
  - **Hunt:** hunting spots with monsters from your level -3 to +4. Each spot lists its monsters with level colours,
    base XP/SP and aggression.
  - **Next steps:** the Path, Trial/Testimony/Test and Saga quests your class can take, and the Class Masters of the
    nearest town. After the 3rd class, the noblesse quests.
  - **Gear:** the grade each level can wear, your weapon and armor grade, the matching shots, and links to the
    Merchant, Cash Shop and Drop Search pages.
  - **Towns:** every town's gatekeepers, warehouses, grocers, weapon and armor traders, Class Masters and trainers.
  - **Tips:** eight short pages from `data\tips.txt`.

  Every place has **Mark**, which sets the radar and map flag. There's also a **Teleport** to the nearest gatekeeper
  destination: it charges that destination's normal fee, is free up to level 20, and has the board's combat and Karma
  checks. Low-level characters get a login reminder, and level-ups say how many new quests opened and when a class
  change or new gear grade is available.
- **Why it can know what you can take:** the quest scripts check race, class and level by hand, so the server can't
  answer that question. The client's `questname-e.dat` can: it lists each quest's level range, allowed classes,
  prerequisite and start NPC.
- **`tools\guide\build_guide_data.py`** writes the module's tables:
  - quests from `questname-e.dat`, read through l2mod;
  - gatekeeper destinations;
  - hunting spots from the monster spawns;
  - town services from the town spawns and buylists.

  `--check` reports whether they're stale. See `tools\guide\README.md`.

### Changed
- **`game\data\html\CommunityBoard\Custom\navigation.html`:** a Guide button at the top.
- **`game\data\html\CommunityBoard\Custom\home.html`:** a welcome line and an "Open the Guide" button.
- **Docs:** `docs/README.md`, `docs/modules.md` and `docs/community-board.md` cover the Guide.

**Apply:** restart the server (the module compiles at startup; the board pages reload with it). If the server is
already running and you only want the buttons, `//reload html` shows them, but they do nothing until the restart. No
client change is needed.

## 2026-09-29 — Docs brought up to date with l2mod

### Changed
- **`docs/README.md`:** the "where do I change X" table now has rows for client names, UI behaviour and UI
  layout through l2mod patches, and points the Quest Navigator row at its `.l2patch`.
- **`docs/client.md`:**
  - it now says l2mod has its own compiler (the old text said there was none);
  - the tools table points `interface.u`, `interface.xdat` and the six name tables at l2mod, and notes that
    this client's `.dat` files use the l2encdec key;
  - adding a name for a new id now reads as a `clone` plus `set`.
- **`docs/modules.md`:** the `quest-navigator` module is added to the module list.

**Apply:** nothing. This is docs only.

## 2026-09-28 — l2mod stage 5: .dat game data

### Added
- **`.dat` decryption and encryption** (`tools/l2mod/l2mod/crypto/ver41x.py`). This client's tables use the public
  l2encdec key, which its `L2.bin` carries. Re-encrypting a stock table rebuilds it byte for byte, so edited
  tables load without patching the client.
- **Table schemas** (`tools/l2mod/l2mod/dat.py`) for sysstring, npcname, itemname, questname, skillname and
  systemmsg. Each round-trips exactly.
- **Row patches** (`package itemname-e.dat`, with `set`, `clone` and `remove`), and a `dat` command to look up
  or search rows.
- **An example patch,** `tools/l2mod/patches/examples/rename-adena.l2patch`. It isn't installed; use it to
  check in game that edited tables load.

**Apply:** nothing is installed.

## 2026-09-28 — l2mod stage 4: window layout (interface.xdat)

### Added
- **`tools/l2mod/l2mod/xdat.py`** reads and writes `interface.xdat`, the layout of every UI window and control.
  The stock file round-trips byte for byte: 140 windows and 31 control types.
- **Layout patches.** `package interface.xdat` patch files `set` any field, `clone` a control or `remove` one.
  They build from stock, check that untouched windows are byte-identical, and install like script patches.
- **`python tools/l2mod xdat <Window>`** lists a window's controls and fields.

**Apply:** nothing is installed. This adds tools only.

## 2026-09-28 — l2mod stage 3: an UnrealScript compiler for client patches

### Added
- **The l2mod compiler.** You write UnrealScript and it builds bytecode identical to what the original compiler
  produced.
  - **Proof:** all 1,641 functions in `interface.u`, compiled from their own embedded source, give the stock
    bytes. Most of `UWindow.u` (670 of 699) and `Engine.u` (1,288 of 1,441) match too.
  - **Rules:** the compiler rules we learned (literal typing, parentheses, overloads, contexts, short-circuit
    skips) are in `tools/l2mod/NOTES.md`.
- **Patch files** (`tools/l2mod/patches/*.l2patch`) replace whole function bodies with source (or a bytecode
  listing), with new commands:
  - `build` compiles and verifies a patch and shows the result;
  - `install` installs patches, and refuses while `L2.exe` or `L2.bin` runs;
  - `restore` puts the stock package back;
  - `status` shows what's installed.

  Every build starts from the stock package and checks that nothing outside the patched functions changed.

### Changed
- **The Quest Navigator client patch is now UnrealScript source** (`tools/l2mod/patches/quest-navigator.l2patch`).
  It builds to the exact file that was tested in game. `tools/questnav/patch_questtreewnd.py` now calls l2mod.

**Apply:** nothing. The installed `interface.u` is unchanged.

## 2026-09-28 — l2mod client toolkit, stages 1-2 (read, decompile, assemble)

### Added
- **`tools/l2mod/`**, a pure-Python toolkit for the client's UnrealScript packages. There's no `ucc` compiler for
  this client, so we built our own tools and prove each one against the stock files.
  - **`decompile`** writes every class's embedded original source (`.uc`) and a bytecode listing (`.asm`).
    **`disasm`** prints one function. **`selftest`** runs the safety gates.
  - **The package reader and writer** round-trips all 22 client `.u` files byte for byte. When an object is
    edited, it relocates only that object, so everything else keeps its bytes and offset.
  - **The bytecode decoder, listing and assembler** handle all 9,362 scripts in the client: no unknown tokens,
    exact sizes, and listings that reassemble to identical bytes.
  - **The tools read stock packages only.** Each is checked by SHA-256, and a stock copy is kept in
    `backup/client/`.
  - **Notes and gate results** are in `tools/l2mod/NOTES.md`. The next stages are a subset compiler, then
    `interface.xdat`, then `.dat` data.

### Fixed
- **The Quest Navigator's startup export listed 0 spawns for every NPC,** because spawns load after modules. It
  now runs two minutes after startup. The in-game window was never affected: it counts spawns when you click.

**Apply:** nothing for the toolkit. Restart the server to pick up the export fix.

## 2026-09-28 — Quest Navigator (clickable quests in Alt+U)

### Added
- **Clicking a quest or quest step in Alt+U opens a "Quest Navigator" window.** It lists the quest's NPCs to talk to
  and mobs to hunt. Clicking a name marks its nearest spawn on the radar and opens the minimap with the flag.
  - The server can't tell which step you're on, so the window lists all of the quest's NPCs and mobs.
  - The stock NPC-position checkbox still marks the current step's target.
- **The `quest-navigator` module** (`game/modules/quest-navigator/`) handles `_bbs_questnav step|go|clear`. It also
  adds `.questnav go <npcId>` and `.questnav clear` for anyone, and `.questnav export` for GMs, which writes
  `tools/questnav/quest_npcs.tsv`.
  - It's a board command because the server only accepts client-initiated bypasses that start with `_bbs`.
- **`tools/questnav/`:**
  - `l2ver111.py` handles `Lineage2Ver111` encryption, including the footer CRC.
  - `patch_questtreewnd.py` patches the bytecode of `QuestTreeWnd.OnClickButton` in the client's `interface.u`,
    adding `RequestBypassToServer("_bbs_questnav step " $ strID)`. The tool verifies the stock hash and the exact
    bytes before patching, and checks that every other object is unchanged after.
  - There's no UnrealScript compiler for this client, so the change is made to the compiled bytecode.
- **Docs:** `tools/questnav/README.md` and a section in `docs/client.md`.

**Apply:**
1. Restart the server so the module loads.
2. With the client closed, run `python tools\questnav\patch_questtreewnd.py`.
   - Undo with `--restore`; the original is in `backup\client\interface.u.orig`.
   - The patch is already installed on this machine.

## 2026-09-28 — Modding docs, changelog, git repo

### Added
- **`docs/`.** Modding documentation for the server and client. Start with [docs/README.md](docs/README.md). It has
  pages for:
  - operations, the config reference and the datapack reference;
  - Java scripting and modules;
  - Living World and the brain;
  - the Community Board;
  - the client;
  - the id registry and admin commands.
- **`CHANGELOG.md`** (this file).
- **`CLAUDE.md`.** Working notes for AI-assisted sessions in this folder.
- **Git repo** in the pack root, with a whitelist `.gitignore`. It tracks configs, datapack (minus geodata and
  crests), modules, schema SQL, launcher scripts, brain code, tools and docs. It leaves out the client, JDK, MariaDB,
  jars, `brain/.env` and logs.
  - The first commit is the pack as installed, and already includes the cash shop below.

**Apply:** nothing. These are docs and tracking only.

## 2026-09-28 — Community Board cash shop

### Added
- **Cash Shop on Alt+B.** It sells every tradeable item for Adena at the item's own `price`: 5,329 items in 42 lists
  across six pages (Weapons, Armor, Jewelry, Consumables, Crafting, Fishing/Other). Weapons, armor and jewelry are
  split by grade.
- **`tools/cashshop/build_cashshop.py`.** Generates the lists and pages from `game/data/stats/items/*.xml`.
  - **Excluded:**
    - untradeable and quest items;
    - castle mercenary tickets;
    - items priced 0 or 1 Adena;
    - junk names: dummies, "Monster Only", event copies, digits-only names.
  - **Tunables:** `PRICE_MULT`, currency `ADENA`, `MAX_PER_LIST`. See
    [docs/community-board.md](docs/community-board.md#the-cash-shop).
- `game/data/multisell/custom/600100.xml` – `600141.xml` (generated; 600100–600199 are reserved for the generator).
- `game/data/html/CommunityBoard/Custom/cashshop/*.html`: `main`, `weapons`, `armor`, `jewelry`, `consumables`,
  `crafting`, `other` (generated).

### Changed
- `game/config/Custom/CommunityBoard.ini`: `CustomCommunityBoard = False` → `True`. This replaces the stock Alt+B home
  page with the custom board (Home, Buffer, Merchant, Gatekeeper, Drop Search, Delevel, Premium).
- `game/data/html/CommunityBoard/Custom/navigation.html`: added the **Cash Shop** button under Merchant.

### Fixed
- Cash shop buttons showed a stray sliver, and one label was cut off ("Fishing,"). Buttons are now 114 px wide (the
  width the texture is drawn for), and the last group's button reads **Fishing/Other**.

**Apply:** restart, because the `.ini` change needs one. Later regenerations need only `//reload multisell` and
`//reload html`.

## v0.1.25 — Upstream baseline
The Living World pack (Teravibes/L2-Living-Worlds) v0.1.25 as installed. This is the starting point of the git
history.
