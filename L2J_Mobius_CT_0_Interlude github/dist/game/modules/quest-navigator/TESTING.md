# Testing the Quest Navigator module

## Test A: the server half, without the client mod

1. Start the server. The console shows `Quest Navigator: exported N quest NPC rows to ...quest_npcs.tsv` and
   `Quest Navigator module enabled`. `game\log\error*.log` has no compile errors for this module.
2. Open `tools\questnav\quest_npcs.tsv`. Every row reads questId, quest name, npcId, role (start, talk or hunt),
   level, spawn count and NPC name.
3. In game, type `.questnav go 20001` (a Gremlin). The minimap opens with the flag, the radar arrow points to the
   nearest Gremlin, and a system message gives the distance.
4. Type `.questnav clear`. The marker goes away.
5. Try `.questnav go` with an NPC that has no fixed spawn (a raid boss that isn't up). You get the "no fixed spawn"
   message.

## Test B: the client half

Install the patched `interface.u` (see `tools\questnav\README.md`), then follow the test steps there. In short: in
Alt+U, click a quest's name. The Quest Navigator window opens, and clicking a mob in it marks the mob on the radar.

## Test C: disabled and removed

1. Set `Enabled = False` and restart. `.questnav` isn't recognised, and nothing is exported.
2. With the server stopped, delete this directory and restart. The server starts clean.
