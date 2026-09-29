# Testing the Phantom Party DPS module

## Test A: it loads

1. Restart the server.
2. The console shows the module enabling after `phantom-skill-pacing`, and one line from it:

   ```
   Party DPS: meter on, fast follow-up on (gap 250+250 ms), burn phase on (under 5.0 s), roles [...].
   ```

   A `different shape` warning instead means this jar's party manager changed; the meter still works.
3. `game\log\error*.log` has nothing from `modules.partydps`.

## Test B: the meter

1. Hit a few mobs alone, then type `.dps`. A window shows you, your DPS, a 100% share, and an active %.
2. `.dps reset` clears it.

## Test C: A/B at one spot

1. Set `Enabled = False`, restart. Recruit a party with a NUKER, a WARRIOR and an ARCHER (plus a healer), fight at
   one spot for about 5 minutes, and note the **Session** table of `.dps`. (With the module off there is no `.dps`;
   for the "before" numbers set `FastFollowUp = False` and `BurnPhase = False` instead, and keep `Enabled = True`.)
2. Turn `FastFollowUp` and `BurnPhase` back on, restart, recruit the same kinds of members, and fight the same spot for
   the same time.
3. Expect clearly higher DPS and active % for the nuker, and higher for the fighters. Casts should go up.

## Test D: it follows the manager, not the other way round

With `Debug = True`:
1. Follow-up lines (`Party DPS: follow-up <name> -> <skill>`) appear during fights.
2. Tell the party to hold or follow while fighting: the follow-up lines stop at once.
3. A dagger moving behind a mob, or an archer stepping back, does not cast while moving.
4. At a raid boss: no follow-up lines for the boss or its minions; the members wait for the tank exactly as before.
5. On trash near death: `uses <playstyle> [burn]` appears, and on the next mob the full playstyle is back.

## Test E: disabled is stock

`Enabled = False`, restart: no line from the module, `.dps` is an unknown command, and members pause 1.6–2.5 s
between skills again.
