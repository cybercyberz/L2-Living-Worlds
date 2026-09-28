# Client (Interlude)

The client is at `Client\Interlude\`: about 1,540 files and roughly 6.5 GB. It isn't in git; back it up separately
before changing it. Every player who connects needs the same modified client files.

## Layout

| Folder | Files | What |
|---|---|---|
| `system\` | 137 | Executables, config `.ini`, data tables (`.dat`), UnrealScript packages (`.u`), UI layout (`interface.xdat`) |
| `maps\` | 157 `.unr` | World tiles (`15_20.unr`…) |
| `textures\` | 382 `.utx` | World, character and item textures |
| `systextures\` | 46 `.utx` + 22 `.bmp` | UI textures, **including item and skill icons** (`icon.utx`…) |
| `staticmeshes\` | 207 `.usx` | Buildings, decorations |
| `animations\` | 18 `.ukx` + 1 `.usk` | Character and monster meshes and animations |
| `sounds\`, `voice\`, `music\` | 25 `.uax`, 44, 250 `.ogg` | Sound effects, voices, music |
| `l2text\` | 176 `.htm` | Help and credits pages |

All the Unreal packages (`.u`, `.utx`, `.usx`, `.ukx`, `.unr`, `.uax`) have the header `Lineage2Ver111`, the standard
L2 package encryption.

## Launching
- **`system\L2.exe`** is **not** the stock client. It's a small .NET launcher that sets the server IP and starts the
  real game, **`system\L2.bin`** (the UE2 engine binary).
- `engine.dll`, `D3DDrv.dll` and `nwindow.dll` are newer than stock, so they're probably community-patched.
  `Option.ini` has non-stock keys: `L2Shader`, `UseBorderlessWindow`, `RENDERCHARACTERCOUNT=10000`.
- **Server address:** `l2.ini`, section `[URL]`, key `ServerAddr`. The file is **encrypted** (header
  `Lineage2Ver413`), so edit it with l2encdec or L2FileEdit.
- **Launch from the server's launcher:** set `launcher.ini` → `[client] ClientExe=…\system\L2.exe` and
  `LaunchClient=true`. The launcher opens it once port 7777 is up.
- **`Option.ini` is plain text** (resolution, window mode). `user.ini` and `Lineage2us.ini` are encrypted.

## Data tables (`system\*.dat`, all encrypted with the `Lineage2Ver413` header)

| File | Holds |
|---|---|
| `itemname-e.dat` | Item names, additional names, descriptions, set info |
| `weapongrp.dat` / `armorgrp.dat` / `etcitemgrp.dat` | Per-item icon, drop model, equip mesh and textures, sounds |
| `npcname-e.dat` | NPC names, titles, name colours |
| `npcgrp.dat` | NPC mesh, textures, animations, sounds |
| `skillname-e.dat` | Skill names and descriptions, per level |
| `skillgrp.dat` | Skill icon, cast animation, MP, range, per level |
| `systemmsg-e.dat`, `sysstring-e.dat` | System messages and UI strings |
| `questname-e.dat` | Quest journal text |
| `recipe-c.dat` | Recipe list shown in the craft window |
| `servername-e.dat`, `zonename-e.dat`, `castlename-e.dat`, `huntingzone-e.dat`… | Names shown in the UI |
| `hennagrp-e.dat`, `optiondata_client-e.dat`, `variationeffectgrp-e.dat` | Dyes, augment option text, augment effects |

`system\interface.xdat` holds the UI window layouts. It's a different format (not Ver413), edited with an XdatEditor.

## Adding content: what the client needs

**Server-side shortcuts (no client change):**
- **Items:** `<set name="displayId" val="<existing item id>"/>` makes the client draw and name a new item as an
  existing one. The `custom-item` module does this: item 60000 shows as Coin of Luck.
- **NPCs:** `displayId="<existing npc id>"` plus `usingServerSideName="true"` / `usingServerSideTitle="true"` gives a
  new NPC an existing model with your own name and title.
- **Skills:** there's no `displayId` for skills. A new skill id works on the server but shows with no name or icon
  until you add client rows.

**A real client entry (own name and icon):** add rows with the **same id** as the server:

| New… | Files |
|---|---|
| Item | `itemname-e.dat` + exactly one of `weapongrp` / `armorgrp` / `etcitemgrp.dat` (icon, e.g. `icon.etc_adena_i00` from `systextures`). If it's a crafted item, also `recipe-c.dat`. |
| NPC | `npcname-e.dat` + `npcgrp.dat` (mesh class from an `animations\*.ukx` package). Optionally `mobskillanimgrp.dat`. |
| Skill | `skillname-e.dat` + `skillgrp.dat`. Optionally `skillsoundgrp.dat`. |
| System message | `systemmsg-e.dat` |
| New art | A new or edited `.utx` (textures, icons) or `.usx`/`.ukx` (meshes) package |

## Tools

| Job | Tool |
|---|---|
| Decrypt, edit and re-encrypt `.dat` / `.ini` | **L2FileEdit** or **L2ClientDat** (use the Interlude/C6 structure); `l2encdec` for raw decrypt and encrypt |
| View and export textures and meshes | **umodel** (UE Viewer) |
| Repack `.utx` / `.usx` / `.ukx` | L2-patched UnrealEd or L2Tool |
| UI layout | XdatEditor (Interlude) |

**Workflow:**
1. Copy the file you're editing to a backup.
2. Decrypt it, edit it, and re-encrypt it as Ver413.
3. Start the client.

A malformed `.dat` usually crashes the client at login or when the item or NPC first appears. Restore the backup to
recover.
