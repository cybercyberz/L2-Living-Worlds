# Community Board (Alt+B) and the cash shop

## Custom board
`CustomCommunityBoard = True` in `game\config\Custom\CommunityBoard.ini` replaces the stock Alt+B home page with the
custom board. The stock board has favourites, region and clan counts; the custom board has these pages:

- **Guide** (the Adventurer's Guide module, see below)
- Home
- **Buffer** (the Role Buffer module, see below)
- Merchant
- **Cash Shop**
- Gatekeeper
- Drop Search
- Delevel
- Premium

Pages are HTML files under `game\data\html\CommunityBoard\Custom\`. The left menu is `navigation.html`, inserted
wherever a page has `%navigation%`.

`CommunityBoard.ini` also sets:
- which services are on: multisells, teleports, buffs and heal are on; delevel is off;
- their prices (all 0) and currency (`CommunityCurrencyId = 57`);
- the teleport list (`CommunityTeleportList`) and the allowed buff ids (`CommunityAvailableBuffs`);
- where the board can be used: `CommunityBoardPeaceOnly = False`; `CommunityCombatDisabled` and
  `CommunityKarmaDisabled` are both True.

**Apply:** page edits need `//reload html`, then reopen Alt+B. `.ini` changes need `//reload config` or a restart.

## Bypass commands (handled by `scripts\handlers\bypass\communityboard\HomeBoard.java`)

| Bypass | Does |
|---|---|
| `bypass _bbstop;<path>.html` | Show `Custom\<path>.html` |
| `bypass _bbsmultisell;<id>,<page>` | Show page `Custom\<page>.html` and open multisell `<id>` |
| `bypass _bbsexcmultisell;<id>,<page>` | Same, but lists only what the player has ingredients for |
| `bypass _bbssell;<page>` | Open the sell-to-NPC window |
| `bypass _bbsteleport;<name>` | Teleport to a `CommunityTeleportList` entry |
| `bypass _bbsbuff;<skill>,<lvl>;…;<page>` | Apply buffs from `CommunityAvailableBuffs` |
| `bypass _bbsheal;<page>` | Full heal |

Multisells opened from the board must list `<npc>-1</npc>` in their `<npcs>` block.

Modules can add their own board commands (any name starting with `_bbs`) by registering an `IParseBoardHandler`
with `CommunityBoardHandler` and building their pages in Java. The board picks a handler by prefix, so a new command
must not start with an existing one.

| Bypass | Module | Does |
|---|---|---|
| `bypass _bbs_guide [page …]` | `adventurer-guide` | The Adventurer's Guide pages: `quests`, `quest <id>`, `hunt`, `area <n>`, `next`, `gear`, `towns`, `town <n>`, `tips`, plus the `mark`, `npc`, `tp` and `go <area> <npcId>` actions |
| `bypass _bbs_buffer [page …]` | `role-buffer` | The buff packages: `main`, `role <key> [0\|1]`, `apply <key>`, `pet on\|off`, `heal`, `clear` |
| `bypass _bbs_questnav …` | `quest-navigator` | Quest Navigator window and radar marks |

## The Adventurer's Guide
The **Guide** button (first in `navigation.html`) opens a new-player guide built for the character
viewing it. It covers:
- the quests they can take now;
- where to hunt at their level;
- their next class change;
- gear by grade;
- every town's services;
- tips.

Places can be marked on the radar or reached with a paid teleport. It's the `adventurer-guide` module. Its pages are
built in Java, so there are no `.html` files to edit, apart from the tips in `data\tips.txt`. See
`game\modules\adventurer-guide\MODULE.md`, and `tools\guide\README.md` for the data behind it.

Generated pages have to fit the board's limit of three 4090-character packets, including `navigation.html`. The guide
pages them at 8 to 16 rows and logs a warning if one gets too long.

## The Buffer
The **Buffer** button opens the `role-buffer` module. Each role (Warrior, Dagger, Archer, Tank, Mage, Summoner,
Healer/Support) has a one-click package: every buff, dance and song that role benefits from, at max level, for an hour
(`BuffDurationSeconds`). The pet or summon gets its own package too. The page recommends the package for the
character's class, and **Details** lists what each buff does. The packages are in
`game\modules\role-buffer\data\packages.txt`; see its `MODULE.md`.

The stock buffer pages (`Custom\buffer\main.html`, `main2.html`, via `_bbsbuff`) are still there but no longer linked.
They give one level-1 buff per click, from `CommunityAvailableBuffs`. Clicking them quickly often seemed to do
nothing, for two reasons:
- the server silently drops any board click within 300 ms of the previous one
  (`FloodProtectorServerBypassInterval = 3` in `FloodProtector.ini`);
- a level-1 buff can't replace a stronger buff of the same kind that the character already has.

The Role Buffer gives a whole package per click at max level, prints what it gave, and answers "one moment" to a
click within a second of the last one. It can't answer a click the flood protector already dropped.

## Page layout rules (learned the hard way)
- **Button width.** Use `width=114` with `back="L2UI_CH3.Button.bigbutton2_down" fore="L2UI_CH3.Button.bigbutton2"`.
  The texture is drawn for 114 px; wider buttons tile a stray sliver next to the button.
- **Button labels.** Keep them short (about 14 characters); longer ones are cut off.
- **Page size.** Keep each page small (the cash shop pages are 2.4–3.6 KB). The board sends a page in a few
  fixed-size chunks, so use sub-pages instead of one long page.
- **Page frame.** Copy the frame from `merchant\main.html`: the outer tables, `%navigation%`, and the grey footer.

## The cash shop
Alt+B → **Cash Shop**. It sells every tradeable item for Adena at the item's own `price`: 5,329 items in 42
multisells, grouped into six pages.

| Page | Lists |
|---|---|
| Weapons | NG, D, C (1–2), B, A, S grade |
| Armor | NG, D, C, B, A, S grade |
| Jewelry | NG to S grade jewels, plus Accessories (hair items, cloaks, formal wear) |
| Consumables | Shots & Arrows, Potions, Scrolls, Spellbooks (1–2), Pet Items |
| Crafting | Recipes (1–4), Materials (1–3), Enchant Scrolls, Crystals & Stones, Dyes |
| Fishing/Other | Fishing (1–2), Manor seeds and crops (1–2), Other (1–2) |

**Generated, don't hand-edit.** Everything is built by `tools\cashshop\build_cashshop.py`:
- it reads every `game\data\stats\items\*.xml`;
- it writes `game\data\multisell\custom\600100.xml`… (ids 600100–600199 are reserved for it);
- it writes `game\data\html\CommunityBoard\Custom\cashshop\*.html`;
- it deletes its own old output first, so rerunning is safe.

```bash
python tools/cashshop/build_cashshop.py
```

Then `//reload multisell` and `//reload html`. The script prints how many items went into each list.

**What's excluded:**
- untradeable and quest items;
- castle mercenary tickets (`CASTLE_GUARD`);
- items priced 0 or 1 Adena, which are placeholders ("Trash", dead recipe duplicates, event paper);
- junk names: dummies, "Monster Only", "(Event)", "L2Day", "Battle Tournament", "test", "Not used", and
  digits-only names.

The `custom\` item folder is skipped, because those items only exist while `CustomItemsLoad` is on.

**Common tweaks (all near the top of the script):**
- **Prices:** `PRICE_MULT = 1.0` scales every price.
- **Currency:** change `ADENA = 57` to another item id, e.g. a custom coin.
- **List size:** `MAX_PER_LIST = 300` (lists are split evenly below it).
- **Filters:** `JUNK_NAME`, `EXCLUDED_ETC_TYPES`, and `exclusion_reason()`.
- **Categories:** `categorize()` returns `(group, label, order)`; add a branch to make a new list. `GROUPS` holds the
  page titles and main-page button labels.

After a tweak, rerun the script, reload, and add a changelog entry.
