# Datapack reference

The datapack is everything under `game\data\`. The XML files are checked against schemas in `game\data\xsd\` (66 of
them). Point your editor at the xsd named in each file's header to get autocompletion and validation.

**Golden rule:** put new content in the `custom\` folders, or ship it in a module. The `General.ini` custom loaders
(`CustomItemsLoad`, `CustomNpcData`, `CustomSkillsLoad`, `CustomMultisellLoad`, `CustomBuyListLoad`,
`CustomTeleportTable`) are all on, so those folders load. Edit stock files only when you're changing stock content,
and log that in the changelog.

## Folder map

| Path | Files | What |
|---|---|---|
| `stats\items\` | 93 range files + `custom\` | Item templates, 100 ids per file (`04300-04399.xml`) |
| `stats\npcs\` | range files + `custom\` (13) | NPC and monster templates, drops, skills |
| `stats\skills\` | range files + `custom\` (4) | Skill definitions |
| `stats\armorsets\`, `augmentation\`, `pets\`, `players\`, `fishing\` | 7 / 166 / 12 / 190 / 3 | Set bonuses, augment tables, pet stats, class base stats and templates, fishing |
| `multisell\` (+ `custom\`) | 139 (47 custom) | Item-for-item exchange shops |
| `buylists\` | 616 | Adena NPC shops; the file name is the list id |
| `spawns\<Region>\` | 186 in 20 regions | Where NPCs and monsters spawn; `Others\` holds grid and special spawns |
| `teleporters\` | 146 | Gatekeeper destinations (`town`, `dungeon`, `clanhall`, …) |
| `zones\` | 38 | Peace, PvP, water, boss, no-store zones (`custom_*.xml` for custom ones) |
| `html\` | 3,124 | NPC dialogs (`html\default\<npcId>.htm`, `merchant\`, `teleporter\`, …), `CommunityBoard\`, `mods\` |
| `scripts\` | ~12k | Java: handlers, AI, quests, custom NPCs, events ([scripting.md](scripting.md)) |
| `instances\` | 2 | Instance zone definitions (`custom\ctf_event.xml`) |
| root `*.xml` | | `SkillLearn.xml`, `Recipes.xml`, `Doors.xml`, `EnchantItemData.xml`, `EnchantSkillTreeData.xml`, `SchemeBufferSkills.xml`, `SellBuffData.xml`, `MerchantPriceConfig.xml`, plus the fake-player files ([living-world.md](living-world.md)) |
| `geodata\`, `crests\`, `skill icons\` | | Pathfinding and binary assets (geodata and crests are not in git) |

## Items (`stats\items\`, `xsd\items.xsd`)

```xml
<item id="60000" type="EtcItem" name="Living World Token">
	<set name="icon" val="icon.etc_adena_i00" />
	<set name="displayId" val="4037" />       <!-- the client draws it as item 4037 (Coin of Luck) -->
	<set name="material" val="PAPER" />
	<set name="weight" val="0" />
	<set name="price" val="1000" />           <!-- reference price; NPCs buy it back for half -->
	<set name="is_stackable" val="true" />
	<set name="is_tradable" val="false" />
</item>
```

- `type` is `Weapon`, `Armor` or `EtcItem`.
- **Common `<set>` names:**
  - `icon`, `price`, `weight`
  - `crystal_type` (D/C/B/A/S), `bodypart` (`rhand`, `lrhand`, `chest`, `rfinger;lfinger`, `hair`…)
  - `weapon_type`, `armor_type`, `etcitem_type` (`POTION`, `SCROLL`, `RECIPE`, `MATERIAL`…)
  - `default_action`, `handler` (item handler class, e.g. `ItemSkills`)
  - `is_tradable`, `is_dropable`, `is_sellable`, `is_depositable`, `is_questitem`, `is_stackable`
  - `immediate_effect`, `displayId`
- **Weapons and armor** add `<stats><stat type="pAtk">…</stat></stats>`, plus `<skills>` or conditions.
- **Ids.** Item ids are capped at **65535** by the schema. New items take a free range from
  [id-registry.md](id-registry.md).
- **Client.** A brand-new id has no name or icon in the client. Either set `displayId` to an existing item, or add
  client `.dat` rows ([client.md](client.md)).

## NPCs (`stats\npcs\`, `xsd\npcs.xsd`)

```xml
<npc id="1003000" displayId="32138" type="Folk" name="Kadmos" usingServerSideName="true"
     title="Noblesse Master" usingServerSideTitle="true">
	<race>HUMAN</race>
	<sex>MALE</sex>
	<stats str="40" int="21" dex="30" wit="20" con="43" men="20">
		<vitals hp="2444.46819" hpRegen="7.5" mp="1345.8" mpRegen="2.7" />
		<attack physical="688.86373" magical="470.40463" random="10" critical="4" accuracy="5" attackSpeed="253" type="FIST" range="40" distance="80" width="120" />
		<defence physical="295.91597" magical="216.53847" />
		<speed><walk ground="20" /><run ground="120" /></speed>
	</stats>
	<status attackable="false" canMove="false" />
	<collision><radius normal="18" /><height normal="28" /></collision>
</npc>
```

- **`type`:** `Folk` (talk-only), `Merchant`, `Teleporter`, `Warehouse`, `Monster`, `RaidBoss`, `GrandBoss`,
  `Guard`… The type decides which default dialog and behaviour the NPC gets.
- **`displayId`** borrows an existing client model. **`usingServerSideName`/`Title`** show your own name and title
  instead of the client's, so a custom NPC needs **no client changes**.
- **Monsters** also carry `<drop>`/`<spoil>` lists, `<skills>`, `<ai>` (aggro range, clan) and `<exp>`/`<sp>`.
- **Default dialog.** With no script attached, the NPC shows `html\default\<npcId>.htm` (or the type's folder).

## Skills (`stats\skills\`, `xsd\skills.xsd`)

```xml
<skill id="1204" levels="2" name="Wind Walk" enchantGroup1="1" enchantGroup2="1">   <!-- stats\skills\01200-01299.xml -->
	<table name="#magicLevel">20 30</table>        <!-- one value per level -->
	<table name="#mpConsume">16 21</table>
	<table name="#runSpd">20 33</table>
	…
	<operateType>A2</operateType>                  <!-- A1 instant active, A2 active with a duration, A3, P passive, T toggle, CA1/CA5 channelled -->
	<targetType>ONE</targetType>
	<effects>…</effects>                            <!-- e.g. a Speed effect reading #runSpd -->
</skill>
```

- **Level tables.** `#name` tables hold one value per level.
- **Enchant routes.** `<enchant1 …>`/`<enchant2 …>` define them.
- **Effects.** Effect names map to classes in `scripts\handlers\skill\effects\`.
- **Who learns what.** `SkillLearn.xml` decides which NPCs teach skills. Class skill trees are under
  `stats\players\`.
- **Reload.** `//reload skill`.

## Spawns (`spawns\`, `xsd\spawns.xsd`)

```xml
<list enabled="true">
	<spawn name="FakePlayers">
		<npc id="80000" x="83485" y="147998" z="-3407" heading="23509" respawnDelay="60" />  <!-- a fixed point -->
	</spawn>
	<spawn name="SomeHuntingGround">
		<territory minZ="-3700" maxZ="-3300">
			<node x="…" y="…" /> <node x="…" y="…" /> <node x="…" y="…" />
		</territory>
		<npc id="21084" count="3" respawnDelay="250" respawnRandom="175" />  <!-- random inside the polygon -->
	</spawn>
</list>
```

- **Coordinates.** Stand at the spot in game and type `/loc` to get them.
- **Temporary spawns.** `//spawn <npcId>` places an NPC that is gone after a restart.
- **Where to put new ones.** Add a new file under an existing region folder, e.g. `spawns\Giran\CustomNpcs.xml`.
  There is no `Custom` spawn folder.

## Multisells (`multisell\`, `xsd\multisell.xsd`)

```xml
<list>
	<npcs><npc>-1</npc></npcs>                      <!-- which NPCs may open it; -1 = the Community Board -->
	<item>
		<ingredient id="57" count="35800" />          <!-- what the player pays (any item, not only Adena) -->
		<production id="749" count="1" />             <!-- what the player gets -->
	</item>
</list>
```

- **Id.** The file name is the list id; `custom\` files load too.
- **Opening a list.**
  - From an NPC dialog: `bypass -h npc_%objectId%_multisell <id>`. With `exc_multisell`, the list only shows entries
    the player has the ingredients for.
  - From the Community Board: `bypass _bbsmultisell;<id>,<page>`.
- **List attributes.** `applyTaxes`, `maintainEnchantment` (see `multisell\documentation.txt`).
- **Reload.** `//reload multisell`.

## Buylists (`buylists\`, `xsd\buylist.xsd`)

```xml
<list>
	<npcs><npc>32007</npc></npcs>
	<item id="5900" count="1" price="10000" restock_delay="180" />   <!-- count/restock = limited stock; omit for unlimited -->
</list>
```

- A plain Adena shop; the file name is the list id.
- Open it from dialog HTML with `bypass -h npc_%objectId%_Buy <id>`. The NPC must be a `Merchant`-type NPC.
- `price` is optional; without it the item's own `price` is used.
- **Reload.** `//reload buylist`.

## Teleports (`teleporters\`, `xsd\teleporterData.xsd`)

```xml
<npc id="30006"> <!-- Roxxy, teleporters\town\ -->
	<teleport type="NORMAL">
		<location name="The Village of Gludin" x="-80749" y="149834" z="-3043" feeCount="18000" />
	</teleport>
</npc>
```

- **Types:** `NORMAL`, `NOBLES_TOKEN`, …
- **Reload.** `//reload teleport`.

## HTML dialogs (`html\`)
- **Where they come from.** The NPC's default dialog is `html\default\<npcId>.htm`, or a type folder such as
  `html\merchant\<npcId>.htm`. Scripted NPCs use the `.htm` files in their script folder.
- **Placeholders.** `%objectId%`, `%npcname%`, `%playername%`, …
- **Buttons:**
  - `<a action="bypass -h npc_%objectId%_<command>">…</a>`
  - `<button value="…" action="bypass -h …" width=… height=… back="L2UI_CH3.Button.…" fore="…">`
- **Size limit.** An Interlude NPC dialog is limited to about 8 KB. Split long pages.
- **Reload.** `//reload html`. Some servers cache HTML, so if a change doesn't show, restart.
