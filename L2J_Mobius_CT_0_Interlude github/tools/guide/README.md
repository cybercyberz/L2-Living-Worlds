# Adventurer's Guide data

`build_guide_data.py` writes the tables the `adventurer-guide` module reads (`game\modules\adventurer-guide\data\`).
The module itself is described in its `MODULE.md`.

```
python tools\guide\build_guide_data.py          # rewrite the tables
python tools\guide\build_guide_data.py --check  # exit 1 if they are out of date
```

Rerun it after changing spawns, gatekeeper lists, NPCs or buylists, then restart the server. It only rewrites its own
five files. `data\tips.txt` is hand-written and it never touches that.

## Tables

| File | From | Rows |
|---|---|---|
| `quests.tsv` | the client's `questname-e.dat`, read with `tools/l2mod` (stock file, checked by hash) | one per quest: title, level range, type, start NPC and where it stands, requirement text, allowed class ids, prerequisite quest, intro and first step |
| `teleports.tsv` | `game\data\teleporters\**` | every Adena-paid gatekeeper destination, with its cheapest fee. Noblesse lists are skipped |
| `areas.tsv` | `game\data\spawns\*\*.xml` | hunting spots: centre, nearest gatekeeper destination, monster level range |
| `area_mobs.tsv` | the same, plus `game\data\stats\npcs` | each spot's monsters: level, base exp/sp, aggressive, spawn count, and up to 8 group centres |
| `services.tsv` | `*NPCs.xml` town spawns, `stats\npcs`, `buylists` | town gatekeepers, warehouses, grocers, weapon and armor traders, Class Masters, skill trainers, pet managers, symbol makers |

## Choices worth knowing

- **Quest eligibility** comes from the client table because the quest scripts check race, class and level by hand in
  `onTalk`, and none of them registers `addCond*` conditions. The table's `class_limit` lists the class ids allowed
  (empty means everyone), and it's what the client itself uses.
- **Quest type:** 0 and 2 are shown as repeatable, 1 and 3 as one-time.
- **Spots:**
  - Only `type="Monster"` NPCs count, so there are no raid bosses, chests, or festival or rift monsters.
  - The folders `Castles`, `Catacombs` and `SevenSigns` are skipped, as are the spawn files in `SKIP_SPAWN_FILES`.
  - A spawn within `SPOT_RADIUS` (9000) of a gatekeeper destination takes that destination's name. Otherwise it's
    named after its file: the `Others\NN_NN.xml` grid files become "Wilds near <destination>", and `AREA_ALIASES`
    fixes the odd file name.
- **Merchants:** a Merchant's kind (Grocer, Weapons or Armor) is the most common item type in its buylists. A file
  with no `<npcs>` block belongs to NPC `fileId / 10`.
