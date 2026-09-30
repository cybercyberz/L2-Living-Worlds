# Testing the Phantom Combat module

## Test A: it loads

1. Restart the server.
2. The console shows the module enabling, and one line from it:

   ```
   Phantom Combat: skill pacing on (49 paced entries, 26 classes); party tempo on (gap 250+250 ms); burn phase on (under 5.0 s); meter on; party healing on (every 250 ms, wasted casts stopped).
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

## Test H: party healing

Set `Debug = True`, restart. Healer lines read
`Phantom Combat: <healer> <heals|saves|group heals N members|raises|cleanses|recharges...>: <skill> -> <target> (hp x/y, incoming z)`.

1. **Two healers split the work.** Recruit two healers (for example two Bishops) and a tank, and fight a pack.
   - The two healers' lines name different targets, or the second one's `incoming` already shows the first heal.
   - One member never gets two single heals that together exceed the gap by much.
   - A small gap (under 10% of max HP) gets no heal; a Greater Battle Heal isn't spent on a small top-off.
2. **One res per corpse.** Let a member die with two healers alive: one `raises` line, and the other healer keeps
   healing. The corpse is not raised twice.
3. **One cleanse per target.** When two members are poisoned (or one is paralyzed), each healer's `cleanses`/`frees`
   line names a different member.
4. **One recharge per target.** With an Elven Elder and a Shillien Elder and a drained Bishop: one `recharges` the
   Bishop, the other moves on to the next mana user.
5. **Your heals count.** Heal a party member yourself: the phantoms don't also heal that member (their `incoming`
   shows your heal).
6. **Crisis.** At a raid, when three or more members drop low: one `calls Benediction` (Bishop 66+); a tank near death
   with heals not keeping up gets `shields` (Celestial Shield, Bishop 64+).
7. **Wasted casts.** `stopped <name>'s <skill> on <target>: already covered` appears now and then, and the healer keeps
   doing other work (buffs, following); it never freezes on the same stopped cast.
8. **Orders still work.** Say "heal me" at full HP: the healer heals you once. Say "recharge <name>": the Elder
   recharges that member until full.
9. **Off.** `PartyHealing = False`, restart: the startup line says `party healing off`, and healers behave as before
   (the party manager's thresholds).

## Test G: disabled is stock

`Enabled = False`, restart: no line from the module, `.dps` is an unknown command, every phantom pauses 1.6–2.5 s
between skills and stalls for `paceMs` after a paced one, and healers heal by the manager's thresholds, as stock.
