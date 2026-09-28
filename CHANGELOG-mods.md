# Changelog

Every change we make to this pack. Newest first.

Each entry has a date, what changed and why, the files touched, and **how to apply** it:
- restart;
- `//reload multisell`, `//reload html` or `//reload config`;
- a client change.

The format follows [Keep a Changelog](https://keepachangelog.com/): **Added**, **Changed**, **Fixed**, **Removed**.
Every entry is committed to this folder's git repo (see [docs/operations.md](docs/operations.md#version-control)).

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
