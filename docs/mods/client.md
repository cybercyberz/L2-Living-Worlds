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
- **Key and mouse bindings** are in `user.ini`, section `[Engine.Input]`. It's encrypted with the l2encdec key, so
  `tools/l2mod/l2mod/crypto/ver41x.py` reads and writes it: `decrypt(raw, L2ENCDEC_MODULUS,
  L2ENCDEC_DECRYPT_EXPONENT)`, then `encrypt(..., L2ENCDEC_ENCRYPT_EXPONENT)`. The output isn't byte-identical to
  stock (zlib differs), but it decrypts to the same text. Edit it with the client closed, because the client may
  save it on exit.

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

**A real client entry (own name and icon):** add rows with the **same id** as the server. l2mod handles the name
tables (`itemname`, `npcname`, `skillname`, `systemmsg`, `sysstring`, `questname`): `clone` an existing row
under the new id, then `set` its fields. The `*grp.dat` tables (icons, models) still need an external tool:

| New… | Files |
|---|---|
| Item | `itemname-e.dat` + exactly one of `weapongrp` / `armorgrp` / `etcitemgrp.dat` (icon, e.g. `icon.etc_adena_i00` from `systextures`). If it's a crafted item, also `recipe-c.dat`. |
| NPC | `npcname-e.dat` + `npcgrp.dat` (mesh class from an `animations\*.ukx` package). Optionally `mobskillanimgrp.dat`. |
| Skill | `skillname-e.dat` + `skillgrp.dat`. Optionally `skillsoundgrp.dat`. |
| System message | `systemmsg-e.dat` |
| New art | A new or edited `.utx` (textures, icons) or `.usx`/`.ukx` (meshes) package |

## l2mod: decompile and patch the UI packages
`tools/l2mod/` reads every client `.u` package:
- `python tools/l2mod decompile interface.u` writes each class's original source and a bytecode listing;
- `python tools/l2mod selftest` proves the tools still reproduce the stock client byte for byte;
- `python tools/l2mod install tools/l2mod/patches/<name>.l2patch` compiles an UnrealScript patch and installs it.
  Close the client first; `restore` undoes it.

Use it instead of UE Explorer and hand edits. See [tools/l2mod/README.md](../tools/l2mod/README.md).

l2mod also edits the `.dat` tables: sysstring, npcname, itemname, questname, skillname and systemmsg. For example, it
can give a custom item or NPC id its own client name with `clone` and `set`. This client's `.dat` files use the
public l2encdec key (its `L2.bin` has that modulus), so re-encrypted files need no client patch. L2FileEdit and
L2ClientDat are no longer needed for these tables.

## Patched `interface.u`: the Quest Navigator
`interface.u` is encrypted with the `Lineage2Ver111` header, a different scheme from the `.dat` files:
- a 28-byte header;
- the payload XORed with `0xAC`;
- a 20-byte footer that holds a CRC32.

Each class's original UnrealScript is embedded in the package as its `ScriptText`, so the source can be read without
a decompiler. No `ucc` compiler exists for this client, so l2mod has its own. It is proven to reproduce every stock
`interface.u` function byte for byte. Patches are ordinary UnrealScript in `tools/l2mod/patches/*.l2patch`.

The only installed patch so far is the Quest Navigator (`tools/l2mod/patches/quest-navigator.l2patch`). Clicking a
quest in Alt+U opens a window of the quest's NPCs and mobs, each of which can be marked on the radar.
- **Install:** close the client, then run `python tools\l2mod install tools\l2mod\patches\quest-navigator.l2patch`.
- **Undo:** `python tools\l2mod restore interface.u`.

[tools/questnav/README.md](../tools/questnav/README.md) has the details.

## Tools

| Job | Tool |
|---|---|
| UI scripts (`interface.u`), UI layout (`interface.xdat`), and the name tables (`itemname`, `npcname`, `skillname`, `questname`, `systemmsg`, `sysstring`) | **l2mod** (`tools/l2mod`): verified against stock, installs and restores |
| Other `.dat` / `.ini` (the `*grp.dat` icon and model tables) | **L2FileEdit** or **L2ClientDat** (use the Interlude/C6 structure). This client's files use the **l2encdec** key. |
| View and export textures and meshes | **umodel** (UE Viewer) |
| Repack `.utx` / `.usx` / `.ukx` | L2-patched UnrealEd or L2Tool |

**Workflow for files l2mod doesn't cover:**
1. Copy the file you're editing to a backup.
2. Decrypt it, edit it, and re-encrypt it as Ver413.
3. Start the client.

A malformed `.dat` usually crashes the client at login or when the item or NPC first appears. Restore the backup to
recover.
