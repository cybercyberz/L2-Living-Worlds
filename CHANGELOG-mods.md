# Changelog

Every change we make to this pack. Newest first.

Each entry has a date, what changed and why, the files touched, and **how to apply** it:
- restart;
- `//reload multisell`, `//reload html` or `//reload config`;
- a client change.

The format follows [Keep a Changelog](https://keepachangelog.com/): **Added**, **Changed**, **Fixed**, **Removed**.
Every entry is committed to this folder's git repo (see [docs/operations.md](docs/operations.md#version-control)).

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
