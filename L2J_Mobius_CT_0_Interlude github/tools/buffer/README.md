# Role Buffer data

`build_buffer_data.py` writes `game\modules\role-buffer\data\buffs.tsv` and checks the hand-edited
`packages.txt` next to it. The module itself is described in its `MODULE.md`.

```
python tools\buffer\build_buffer_data.py          # rewrite buffs.tsv, check the packages
python tools\buffer\build_buffer_data.py --check  # exit 1 if buffs.tsv is out of date or a package is wrong
python tools\buffer\build_buffer_data.py --dump   # print the whole catalog, grouped by stack type
```

Rerun it after editing `packages.txt` or the skill XMLs, then restart the server.

## buffs.tsv

One row per skill in the script's `CATALOG`: every buff a player can get from another class in Interlude (Prophet,
Elven Elder, Shillien Elder, Warcryer, Overlord, Bladedancer dances, Swordsinger songs), plus the 3rd-class ones
(Prophecies of Fire, Water and Wind, Chant of Victory, Magnus' Chant, Noblesse Blessing).

| Column | From the skill XML |
|---|---|
| `level` | the highest normal level (`levels=`); enchant levels aren't used |
| `kind` | `dance` when `isMagic` is 3 (dances and songs have their own 12 slots), otherwise `buff` |
| `type`, `typeLevel` | `abnormalType` and `abnormalLevel`: skills of the same type replace each other |
| `time` | the normal duration; the module overrides it with `BuffDurationSeconds` |
| `icon` | the skill icon, for the board |
| `effect` | a summary of the effect at that level, e.g. `P. Atk +15%` or `Hold/Sleep/Mental Res +50%` |

## The package checks

For each `[key]` block in `packages.txt`:
- every id must be in the catalog;
- no two skills may share a `type`, since only one of them would stay on;
- buffs must fit `MaxBuffAmount` and dances/songs `MaxDanceAmount` (read from `game\config\Player.ini`: 20 and 12).

## Choices worth knowing

- **Only one all-in-one buff per package.** Chant of Victory, Victories of Pa'agrio, the three Prophecies and Magnus'
  Chant are all `MULTI_BUFF`. Victory and the Prophecies of Fire and Water lower run speed by 10-20%; Wind Walk
  (+33) is in every package to make up for it.
- **Paired buffs are equal.** Might and Chant of Battle, Haste and Chant of Fury, Focus and Chant of Predator, and the
  other pairs have the same values and stack type, so each package lists one of them.
- **Greater Might, Greater Shield, War Chant and Earth Chant** share `PA_PD_UP`: fighters get Greater Might, and tanks
  and casters get Greater Shield.
- **Not offered:** Dance of Shadows (it halves your speed), Kiss of Eva and Decrease Weight (no combat value), and
  1461, 529 and 530, which this datapack doesn't have.
