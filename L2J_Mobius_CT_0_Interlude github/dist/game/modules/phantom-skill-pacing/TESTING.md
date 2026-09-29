# Testing the Phantom Skill Pacing module

## Test A: it loads

1. Restart the server.
2. The game console shows the module compiling and enabling, plus one line from it:

   ```
   Phantom Skill Pacing: 49 paced entry(ies) across N class id(s) now pace per skill.
   ```

   The count is the number of non-PULL entries with `paceMs` in `PhantomPlaystyles.xml`.
3. `game\log\error*.log` has nothing from `modules.phantompacing`.

## Test B: a paced skill no longer stalls the rotation

1. Set `Debug = True` in `config/module.ini` and restart.
2. Recruit a party member with a paced CONTROL skill, for example a Warrior (Stun Attack, 6 s), or turn on
   `//phantom debug` near field hunters of such a class.
3. Fight a few mobs. In the console:
   - `Phantom Skill Pacing: <name> cast Stun Attack; next one in 6000 ms at the earliest.`;
   - between two Stun Attacks, the `PLAYSTYLE ... casts` debug lines show its other skills (Power Smash, Power
     Strike) firing, about every 2 seconds, instead of nothing for 6 seconds.
4. Your own character of the same class casts Stun Attack at its normal reuse: no debug line for it.

## Test C: reloads

1. With `Debug = True`, change one `paceMs` in `game\data\PhantomPlaystyles.xml` and run `//phantom playstyle`.
2. Within 2 seconds the console logs `... (playstyles reloaded).`, and the new gap applies.

## Test D: disabled is stock

1. Set `Enabled = False` and restart.
2. No line from the module. After a Stun Attack, a Warrior phantom casts nothing else for about 6 seconds again.
3. Set `Enabled = True` back and restart.
