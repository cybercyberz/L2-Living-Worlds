# Role Buffer module

One-click buff packages on the Alt+B board. Press Alt+B and click **Buffer** (or type `.buff`). Pick your role, press
**Apply**, and you get every buff, dance and song that role benefits from, at the skill's highest level, for an hour.
Your pet or summon gets its own package at the same time.

## Packages

| Role | For | All-in-one | Highlights |
|---|---|---|---|
| Warrior | Gladiator, Warlord, Destroyer, Tyrant, Bounty Hunter, Warsmith, Blade Dancer, Sword Singer | Chant of Victory | Might, Greater Might, Haste, Focus, Death Whisper, Vampiric Rage, Berserker Spirit; Warrior, Fury, Fire, Vampire dances; Hunter, Champion songs |
| Dagger | Treasure Hunter, Plainswalker, Abyss Walker | Prophecy of Wind | The Warrior buffs plus crits from behind and evasion; Song of Hunter and Dance of Fire first |
| Archer | Hawkeye, Silver Ranger, Phantom Ranger | Chant of Victory | P. Atk, accuracy (Guidance, Dance of Inspiration), crits, attack speed |
| Tank | Paladin, Dark Avenger, Temple Knight, Shillien Knight | Prophecy of Fire | Greater Shield, Bless Shield, Advanced Block, Elemental Protection, Chant of Revenge; Earth, Warding, Vitality, Vengeance, Flame/Storm Guard songs |
| Mage | Sorcerer, Necromancer, Spellsinger, Spellhowler | Prophecy of Water | Empower, Acumen, Wild Magic, Berserker Spirit, Blessed Soul, Clarity, Concentration; Mystic, Concentration, Siren's dances; Meditation, Renewal songs |
| Summoner | Warlock, Elemental Summoner, Phantom Summoner | Prophecy of Water | The Mage set for you; your servitor gets the Pet set |
| Healer/Support | Bishop, Elder, Shillien Elder, Prophet, Warcryer, Overlord | Magnus' Chant | Casting speed, MP, MP cost (Clarity, Meditation), Concentration, safety |
| Pet | Any pet or servitor, when "Also buff my pet/summon" is On | Chant of Victory | Damage, attack speed, crits, HP, speed |

Every role also gets Noblesse Blessing, Blessed Body, Magic Barrier, Mental Shield, Resist Shock, Wind Walk, Chant of
Spirit and Pa'agrio's Fist.

The page marks the role that fits your class as **Recommended**, but any package can be applied. **Details** lists
each buff with its icon, level and what it does. Each package fills the 20 buff slots and up to 12 dance/song slots
(`config/Player.ini`). Two skills of the same kind (for example Might and Chant of Battle) replace each other, so a
package never holds both. Applying another package replaces the buffs of the same kind.

The page also has:
- **Also buff my pet/summon:** On or Off, remembered per character.
- **Heal:** full HP, MP and CP for you and your pet.
- **Remove buffs:** clears your buffs, dances and songs, and your pet's.

**Chat command:** `.buff` opens the page. `.buff <role>` applies a package directly, for example `.buff dagger`.

**Rules:** buffing is refused with Karma, while dead, in combat, in the Olympiad, a duel, a siege or an event. After a
package there's a one-second pause; a click inside it says "one moment". (A click within 300 ms of the previous one
never reaches the module: the server's flood protector drops it, `FloodProtectorServerBypassInterval` in
`game\config\FloodProtector.ini`.)

## Changing the packages

Edit `data/packages.txt`. Each `[key] Name | purpose | icon=<skill id>` line starts a package, followed by one skill
id per line, most important first. Then check it:

```
python tools\buffer\build_buffer_data.py
```

It rewrites `data/buffs.tsv` (each buff's level, kind, stack type and effect, read from the skill XMLs) and reports
unknown ids, two skills of the same kind in one package, and packages over the slots. Restart the server afterwards.
Only skills in the generator's `CATALOG` can be used; add an id there to offer a new buff.

## Settings (`config/module.ini`)

| Key | Default | What |
|---|---|---|
| `Enabled` | True | Master switch |
| `DataPath` | `modules/role-buffer/data` | Where `buffs.tsv` and `packages.txt` are, relative to `game\` |
| `BuffDurationSeconds` | 3600 | How long every buff lasts; 0 keeps each skill's own time |
| `PricePerPackage`, `PriceItemId` | 0, 57 | What a package costs (the pet's included); 0 is free |
| `BuffPetDefault` | True | Whether "Also buff my pet/summon" starts On |
| `AllowInCombat` | False | Allow buffing in combat |
| `ApplyCooldownMs` | 1000 | The shortest time between two packages |
| `Debug` | False | Log every click and result |

## Enable, disable, remove

- **Enable or disable:** set `Enabled` in `config/module.ini`, then restart the server.
- **Remove:** delete this directory while the server is stopped, and point the Buffer button in
  `game\data\html\CommunityBoard\Custom\navigation.html` back to `_bbstop;buffer/main.html`. The module has no
  database tables; the pet on/off choice is a character variable (`RoleBuffer.pet`).

It registers `_bbs_buffer` (a Community Board command) and `.buff`, and owns everything under this directory. The only
file outside it is the board menu, whose Buffer button links to `_bbs_buffer`. The stock buffer pages
(`Custom\buffer\*.html`, `_bbsbuff`) are untouched.

## Sharing it

Copy this folder into another L2 Living Worlds server's `game\modules\`, and set that server's Buffer button (or add
one) to `bypass _bbs_buffer`:

```html
<button value="Buffer" action="bypass _bbs_buffer" width=114 height=30 back="L2UI_CH3.Button.bigbutton2_down" fore="L2UI_CH3.Button.bigbutton2">
```
