# Testing the Phantom Combat module

## Test A: it loads

1. Restart the server.
2. The console shows the module enabling, and one line from it:

   ```
   Phantom Combat: skill pacing on (49 paced entries, 26 classes); party tempo on (gap 250+250 ms); burn phase on (under 5.0 s); meter on.
   ```

   The entry count is the number of non-PULL entries with `paceMs` in `PhantomPlaystyles.xml`. A `different shape`
   warning means this jar's classes changed; the sections it names stay off and the meter still works.
3. `game\log\error*.log` has nothing from `modules.phantomcombat`.

## Test B: skill pacing

1. Set `Debug = True`, restart.
2. Near field hunters or a recruited party of a class with a paced skill (for example a Warrior, Stun Attack 6 s):
   - `Phantom Combat: <name> cast Stun Attack; next one in 6000 ms at the earliest.`;
   - between two Stun Attacks the phantom keeps casting its other skills, instead of nothing for 6 seconds.
3. Your own character of the same class casts Stun Attack at its normal reuse: no line for it.
4. Change one `paceMs`, run `//phantom playstyle`: within 2 seconds `playstyles reloaded` is logged and the new gap
   applies.

## Test C: the meter

1. Hit a few mobs alone, then type `.dps`. A window shows you, your DPS, a 100% share, and an active %.
2. `.dps reset` clears it.

## Test D: party tempo, A/B at one spot

1. Set `PartyTempo = False` and `BurnPhase = False`, restart. Recruit a NUKER, a WARRIOR and an ARCHER (plus a
   healer), fight at one spot for about 5 minutes, and note the **Session** table of `.dps`.
2. Set both back to `True`, restart, recruit the same kinds of members, and fight the same spot for the same time.
3. Expect clearly higher DPS and active % for the nuker, and higher for the fighters. Casts should go up.

## Test E: tempo follows the manager, not the other way round

With `Debug = True`:
1. `Phantom Combat: follow-up <name> -> <skill>` lines appear during fights.
2. Tell the party to hold or follow while fighting: the follow-up lines stop at once.
3. A dagger moving behind a mob, or an archer stepping back, does not cast while moving.
4. At a raid boss: no follow-up lines for the boss or its minions; the members wait for the tank exactly as before.
5. On trash near death: `uses <playstyle> [burn]` appears, and on the next mob the full playstyle is back.

## Test F: the pacing rule without SkillPacing

1. Set `SkillPacing = False` (keep `PartyTempo = True`), restart. The startup line says
   `skill pacing for party tempo members only`.
2. A party Warrior still waits 6 s between Stun Attacks while casting its other skills in between.
3. A field-hunter Warrior shows the stock behavior: after a Stun Attack, nothing else for about 6 s.

## Test G: disabled is stock

`Enabled = False`, restart: no line from the module, `.dps` is an unknown command, and every phantom pauses 1.6–2.5 s
between skills and stalls for `paceMs` after a paced one, as the stock engine does.
