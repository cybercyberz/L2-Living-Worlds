# Quest Navigator module

The server half of the clickable Alt+U quest window. The client half is a patched `interface.u`, made by
`tools\questnav\patch_questtreewnd.py` (see `tools\questnav\README.md`).

## What it does

- **`_bbs_questnav step <node>`** is sent by the patched quest window when you click a quest or a quest step. `<node>`
  is the tree node name, `root.<QuestID>...`. It opens a "Quest Navigator" window listing the quest's NPCs to talk
  to and mobs to hunt. Each name links to `go`, and names with no fixed spawn are greyed out.
- **`_bbs_questnav go <npcId>`** marks the nearest spawn of that NPC on the player's radar and opens the minimap with
  the flag. If the NPC is up, it uses the NPC's live position; if it has no spawn-table entry, it looks for a live
  one in the world. The navigator window's links send this. It's a Community Board
  command because the server only accepts bypasses the client sends by itself when they start with `_bbs`. It sends
  no HTML, so the Alt+B board stays closed.
- **`_bbs_questnav clear`** removes the marker.
- **`.questnav go <npcId>`**, **`.questnav clear`**: the same actions from chat, for testing without the client mod.
- **`.questnav export`** (GM only), and once at every startup: writes each quest's start, talk and hunt NPCs to
  `tools\questnav\quest_npcs.tsv`.

It touches no stock file and owns everything under this directory.

## Enable, disable, remove

- **Enable or disable:** set `Enabled` in `config/module.ini`, then restart the server.
- **Remove:** delete this directory while the server is stopped. The module has no database tables.

With the module off, the patched quest window behaves as stock: its extra bypass reaches no handler.
