# Testing the Adventurer's Guide module

## Test A: the server starts it

1. Start the server. The console shows `Adventurer's Guide enabled: 342 quests, N hunting spots, N teleports, N towns`.
   `game\log\error*.log` has no compile errors for this module.
2. If it says `could not load`, run `python tools\guide\build_guide_data.py` and restart.

## Test B: a new character

Make a level 1 character (a Human Fighter is a good start) and log in on Talking Island.

1. A system message says to press Alt+B and click Guide.
2. Alt+B, **Guide**. Home shows your name, "Human Human Fighter, level 1" and "19 levels to your next class change".
   Right now lists quests near Talking Island Village.
3. **Quests**, Available: the Talking Island quests (Letters of Love at level 2+), and no Elf- or Dark Elf-only
   quests. Open one: the story, first step and start NPC show. **Mark on map** puts the flag on the NPC. **NPCs and
   mobs** opens the Quest Navigator window (when that module is on).
4. **Hunt**: Talking Island spots with level 1-5 monsters. Open one: the monsters' levels are coloured. Mark flags the
   nearest group.
5. **Next steps**: Path to a Warrior, Path to a Human Knight and Path to a Rogue, with the Class Masters of Talking
   Island Village.
6. **Gear**: No-grade is your grade now; D-grade is next at level 20.
7. **Towns**: Talking Island Village first. Open it: gatekeeper, warehouse, grocer and trainers, each with Mark.
8. **Tips**: the list, and each page with Prev/Next links.
9. `.guide` opens the same Home page. `.guide hunt` opens Hunt.

## Test C: teleport

1. From a quest or spot far away, click Teleport. At level 20 or below it's free and you land at the gatekeeper
   destination.
2. Above level 20 (use `//set_level` on a test character), the fee is taken. With no Adena you get "costs N Adena" and
   stay put.
3. Hit a monster and click Teleport at once: "you can't teleport right now".
4. Hunt, open a spot: every monster row shows `Mark  Go`, with the fee after Go above level 20. Click Go: you land
   on the ground a few steps from a group of that monster, and "you're next to …" shows. The fee taken matches the
   one shown. With `TeleportEnabled = False` (restart), Go isn't shown.

## Test D: level-up hints

`//set_level 20` on a Human Fighter: messages say new quests opened, you can make your class change, and you can use
D-grade gear.

## Test E: disabled and removed

1. Set `Enabled = False` and restart. The Guide button does nothing, and `.guide` isn't recognised.
2. With the server stopped, delete this directory and remove the Guide button from `navigation.html`.
   The server starts clean.
