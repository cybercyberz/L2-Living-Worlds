# Quest Navigator: the client patch

Clicking a quest, or a quest step, in the Alt+U window opens a small window listing that quest's NPCs to talk to and
mobs to hunt. Clicking a name marks its nearest spawn on the radar and opens the minimap with the flag.

It has two halves:
- **Server:** the `quest-navigator` module (`game\modules\quest-navigator\`) answers `_bbs_questnav step|go|clear`.
- **Client:** a patched `Client\Interlude\system\interface.u`. This folder holds the tools that make it.

## Files
| File | What |
|---|---|
| `patch_questtreewnd.py` | Installs the patch through l2mod. `--check` verifies without writing; `--restore` puts the stock file back. The patch itself is UnrealScript source: `tools/l2mod/patches/quest-navigator.l2patch`. |
| `l2ver111.py` | Decrypts and encrypts `Lineage2Ver111` files: a 28-byte header, a payload XORed with `0xAC`, and a 20-byte footer whose bytes 12-15 are the CRC32 of the header plus the encrypted payload. `roundtrip` proves a file decodes and re-encodes to the same bytes. |
| `quest_npcs.tsv` | Written by the server module at startup and by `.questnav export`. It lists every quest's start, talk and hunt NPCs, and is for debugging only. |

## What the patch changes
The patch is ordinary UnrealScript, compiled by tools/l2mod. l2mod's compiler reproduces the original compiler
byte for byte. The first version of this patch was hand-assembled bytecode, and the source version builds to the
exact same file. It adds one statement to `QuestTreeWnd.OnClickButton`, inside its `if (Left(strID, 4) == "root")`
branch:

```
RequestBypassToServer("_bbs_questnav step " $ strID);
```

- **What `strID` is:** the clicked tree node's name. It's `root.<QuestID>` for a quest and
  `root.<QuestID>.<Level>.<Completed>` for a step.
- **Why `_bbs`:** the server rejects any bypass the client sends by itself unless it starts with `_bbs` (or one of a
  few other prefixes).
- **The byte changes:**
  - The function grows from 81 to 111 bytes, and its script from 60 to 94 bytes in memory.
  - The if-jump now targets offset `0x5c`, so non-quest clicks still skip the call.
  - The new function body is placed where the import table was, and the import and export tables move up behind it.
    Every other object keeps its bytes and its offset.

The tool refuses to run unless all of these hold:
- the input's SHA-256 is the stock file's;
- the function's bytes are exactly the ones it expects;
- the untouched tables re-serialise to identical bytes.

After patching, it re-reads the result and checks that every other export is unchanged.

The embedded `ScriptText` source still shows the stock function. That text is only there for editors; the game
runs the bytecode.

## Install
1. **Close the client.** The server can stay up.
2. Run `python tools\questnav\patch_questtreewnd.py`. The original is kept at `backup\client\interface.u.orig`, and
   the tool always patches from that file.
3. Start the client.

**Undo:** run `python tools\questnav\patch_questtreewnd.py --restore`. A client update that replaces `interface.u`
removes the patch; run the tool again after one.

## Test
1. Start the server with the module enabled, and log in.
2. Take a quest. The Talking Island newbie quests are quick.
3. Press Alt+U and click the quest's name. A "Quest Navigator" window lists its NPCs and mobs.
4. Click a mob. The minimap opens with a flag, and the radar arrow points to its nearest spawn.
5. Check the stock controls still work:
   - the "abort quest" button;
   - the NPC-position checkbox, which marks the step target when you click a step.

If the client crashes at startup or the UI doesn't load, run `--restore` and report it. That means the byte layout is
wrong, and the patch needs fixing.
