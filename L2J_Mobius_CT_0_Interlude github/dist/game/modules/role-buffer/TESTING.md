# Testing the Role Buffer module

## Test A: the server starts it

1. Start the server. The console shows `Role Buffer enabled: 8 packages, 99 buffs, 3600 s each`.
   `game\log\error*.log` has no compile errors for this module.
2. If it says `could not load`, run `python tools\buffer\build_buffer_data.py` and restart.

## Test B: the page

1. Alt+B, **Buffer**. The top says "Recommended for your <class>: <role>" (a Gladiator sees Warrior, a Sorcerer Mage,
   a Bishop Healer/Support, a Warlock Summoner).
2. The seven roles are listed with their icon, counts ("20 buffs, 12 dances/songs"), purpose, Details and Apply.
   Nothing is cut off, and the buttons have no stray slivers.
3. **Details** on Warrior: two columns of buffs with icon, level and effect ("Might 3, P. Atk +15%"). The
   **Dances & Songs** tab lists 12. **Back to packages** returns.

## Test C: applying

1. **Apply** Warrior. Chat says "Warrior package: 20 buffs, 12 dances/songs (1 hour)". The buff bar shows them, and a
   dance shows about 60 minutes left.
2. **Apply** Mage right away (after a second). Mage buffs replace the clashing ones (Acumen, Empower and so on appear;
   Might stays, since nothing replaces it).
3. **Click Apply twice, about half a second apart:** the second click says "one moment". (A double-click faster than
   300 ms is dropped by the server's flood protector before it reaches the module, so it shows nothing.)
4. **Click Apply ten times at a normal pace** (about one a second): every click applies and the page refreshes each
   time. There's no need to close and reopen the board (the old stock buffer's problem).
5. **Remove buffs** clears them. **Heal** fills HP, MP and CP.
6. `.buff dagger` in chat applies the Dagger package without opening the board. `.buff` opens the page.
7. Hit a monster, then click Apply at once: "you can't be buffed right now (in combat)".

## Test D: pet and summon

1. Summon a servitor (or call a pet) with "Also buff my pet/summon: On". Apply any role: chat adds "<pet>: 17 buffs,
   8 dances/songs", and the pet has them.
2. Switch it **Off** and apply again: only you are buffed. Log out and in: the choice is remembered.
3. **Details** next to the pet line, then **Buff my pet**: only the pet is buffed. With no pet out it says "call your
   pet or summon first".

## Test E: price and settings

1. Set `PricePerPackage = 1000` and restart. Applying takes 1000 Adena; with less it says what it costs and gives
   nothing.
2. Set `BuffDurationSeconds = 0` and restart: buffs last their normal 20 minutes, dances 2 minutes.
3. Set `Enabled = False` and restart: the Buffer button does nothing, and `.buff` isn't recognised.

## Test F: a stock install

1. Stop the server. Set `CustomCommunityBoard = False` and point the Buffer button in `navigation.html` back to
   `bypass _bbstop;buffer/main.html`. Keep a copy of both first.
2. Start the server. The console shows `Role Buffer: pointed the Buffer button at _bbs_buffer`. Alt+B has the left
   menu, and Buffer opens the packages.
3. Restart: nothing changes. Put the two files back.
