# Phantom Combat module

Decides **how phantoms fight together**: when they may cast next, and how party healers share the work. It has four
sections, each with its own switch:

| Section | Who | Idea |
|---|---|---|
| **Skill pacing** | every phantom | A paced skill waits its own `paceMs`, and nothing else stalls |
| **Party tempo** | recruited DPS members | They don't idle between skills |
| **Meter** | you and your party | `.dps` measures the difference |
| **Party healing** | recruited healers | Every healer knows the whole party's HP and what the others are casting |

It replaces the two earlier modules `phantom-skill-pacing` and `phantom-party-dps`. They both changed the engine's
"next cast" gate and depended on each other, so they're one module now.

## Why

**Skill pacing.** A playstyle entry can carry `paceMs`, for example Stun Attack with `paceMs="6000"`: "don't recast
this skill more often than every 6 seconds". The engine in `GameServer.jar` (`PhantomPlaystyleEngine.pick`) instead
uses `paceMs` as the gate for **every** next cast. So after one Stun Attack a Warrior casts nothing else for about
6 seconds (only PANIC entries get through), and after Lightning Strike (`paceMs="15000"`) a Hell Knight goes silent
for 15. 49 entries use `paceMs`.

**Party tempo.** The party manager plays members for realism and safety, not damage:
- it makes one decision per member per second, and does nothing while the member casts;
- after every skill the engine waits 1.6–2.5 s before the next one, even if it's ready;
- a nuker never auto-attacks, so it stands idle for most of that wait;
- a fighter's swing stops after a skill until the next manager tick re-arms it;
- debuffs, stuns and openers are cast even on a mob that dies two seconds later.

## What it does

### Skill pacing (`SkillPacing`)
- The module reads each entry's `paceMs` (by class and skill) from the loaded playstyles and sets it to 0 in the loaded
  data. The engine then waits only its default beat after any cast.
- When a phantom casts a paced skill, that skill alone is disabled on that phantom for `paceMs`. The engine already
  skips a disabled skill. The skill's own reuse still applies, so the longer of the two wins.
- Phantoms only: field hunters, recruited party members and alt companions. A real player of the same class keeps
  normal reuse.
- `//phantom playstyle` loads fresh data; the module notices within 2 seconds and applies itself again. The XML file
  is never changed.

### Party tempo (`PartyTempo`, `BurnPhase`)
- **Follow-up:** when a DPS member starts a cast, the engine's pause is cut to `CastGapMs` (+ jitter). As soon as the
  cast ends, the next skill is picked with the same engine call the manager uses, so every playstyle rule still
  applies (conditions, the MP reserve). If nothing is ready, a fighter goes straight back to swinging.
- It only **follows the manager's lead**:
  - it acts on the monster the member was already attacking or casting on, within the last `EngagedWindowMs`;
  - it stops as soon as the member moves (repositioning, peeling, following), sits, is ordered to hold, is easing
    aggro, is recovering after a res, is in a PvP, or is switched to another target;
  - **raid bosses and their minions are left entirely to the manager** and its raid gates;
  - it never chooses targets: the manager (assist the leader, camp, pull) still decides what to hit.
- **Burn phase:** from the party's damage over the last 4 seconds, the module estimates when each mob will die. Below
  `BurnTtkSeconds`, a member's playstyle drops its DEBUFF, CONTROL and OPENER entries, so those casts become damage.
  On a new target the full playstyle comes back.

### Party healing (`PartyHealing`)
The party manager heals by fixed HP% thresholds (60%, or 80/90% in raids), and it only notices another healer if that
one claimed the same target in the same second or is casting on it right now. So heals don't match the gap (a 330 HP
Heal on a tank missing 3,000, a Greater Battle Heal on a mage missing 400). Below 50% everyone piles on, and nothing
coordinates group heals, cleanses or recharges. The res claim also lasts 4.5 s while Resurrection takes 6 s to cast.

**What every healer knows** (`PartyBoard.java`):
- **Each member:** HP, max HP, and the damage it took per second over the last 3 s.
- **The ledger:** every heal, group heal, cleanse, recharge and res that anyone in the party has started, with its
  estimated amount and landing time. That includes you and a Prophet.
- **How estimates are made:** with the game's own heal formula (power, spiritshots, M.Atk, the target's heal bonus and
  the class multiplier).
- **When entries leave:** a finished or aborted cast drops out on its own. A res claim holds until the corpse stands up.

**What each healer does** (`HealerBrain.java`, every `HealTickMs`): it looks at the party from its own position, MP,
skills and cooldowns, and does the first thing needed:
1. **Save a life.** A member predicted below `CriticalPercent` by the time this healer's fastest heal lands gets the
   fastest heal that lifts it back over. Celestial Shield goes on a tank or on you when heals can't keep up.
2. **Party crisis:**
   - Benediction when 3 or more members are below 40%;
   - Balance Life when one member is below 30% but the party averages over 65%.

   Only one healer per party spends these.
3. **Cleanse.**
   - Paralyze or petrify first, the tank's before anyone's.
   - Then poison or bleeding on a hurt member: Vitalize if it also needs HP, else Purify or Cure Poison.
   - Cardinal's Cleanse handles a tank or leader with 3 or more debuffs.
   - One healer per target.
4. **Raise the dead.** You first, then the tank, healers, anyone. One healer per corpse; the claim is shared with the
   manager's own rezzing.
5. **Group heal** when `GroupHealMinTargets` members still need most of it once heals already on the way have landed.
   It picks the one that restores the most HP per MP, and only if no other group heal is already on its way.
6. **Single heal** on the biggest need, weighted by role (tank 1.3, you 1.2, healer 1.15, others 1, pets 0.6):
   - It uses the cheapest heal per HP that doesn't exceed `OverhealLimitPercent` of the gap.
   - If the member is falling fast, only a 2 s heal will do.
   - Gaps under `MinHealPercent` are left alone.
7. **MP** (Elders and Saints):
   - Recharge the most important drained mana user (healers, then the tank, then casters and bards) that no one else
     is recharging;
   - Mass Recharge for 3 or more;
   - Invocation for itself in a lull.

**Cancel on full:** a slow heal (4 s or more) is aborted if another heal has already filled its target.

**What the manager keeps:** buffs, following, MP rest, AoE dodging, raid backline position, and every chat order ("heal
me", "recharge X", "buff"). While a healer carries out an order, the brain leaves it alone.

**Wasted casts** (`VetoWastedHeals`): the manager's own support casts are stopped before they start (at no MP cost)
when another caster already covers them: a heal on a covered member, a second group heal, a res on a claimed corpse,
a double cleanse or recharge. Your own casts are never stopped.

**The healer role's skills** (from the datapack, at max level; cast time before casting speed):

| Kind | Skills | Used for |
|---|---|---|
| Fast single | Battle Heal (2 s, 301), Greater Battle Heal (Bishop, 2 s, 858) | saving a life, falling targets |
| Slow single | Heal (5 s, 301), Major Heal (Bishop/EE 56+, 5 s, 946, 1 Spirit Ore), Vitalize (Bishop/EE 48+, 780, removes poison and bleed), Greater Heal (721 plus a HoT) | gaps, cheapest per HP |
| % heal | Restore Life (Bishop 44+, 8 s, 30% of max HP) | big-HP members, when it's the cheapest |
| Group | Group Heal (241), Greater Group Heal (Bishop/SE, 577 plus a HoT), Major Group Heal (Bishop 58+, 1,170, 4 Spirit Ore) | several members hurt |
| Crisis | Benediction (Bishop 66, party 100%, 1 h), Balance Life (Cardinal, 2 min), Celestial Shield (Bishop 64, 10 s invincible, 30 min) | one per party |
| Raise | Resurrection (Shillien line only to level 2) | corpses |
| Cleanse | Cure Poison, Purify (Bishop/SE: poison, bleed, paralyze, petrify), Cleanse (Cardinal, every debuff) | debuffs |
| MP | Recharge (EE/SE, not on a Recharge class), Mass Recharge (Saints, needs Spell Force 3), Invocation (self) | mana users |

Left to the manager or unused on purpose:
- Mass Resurrection and Miracle affect the clan only, not the party.
- Salvation is a pre-death buff.
- Buffs and damage skills are not part of this section.

### Meter (`Meter`)
`.dps` opens a window with each party member's DPS, share of damage, casts and **active %** (the share of fight
seconds with a hit, swing or cast), for the current or last fight and for the session. Pets count for their master.
`.dps reset` clears it.

## How the sections fit together

- **One rule ties pacing and tempo:** every phantom whose casting pace the module sets also gets each skill's own
  `paceMs`. So with `SkillPacing = False` but `PartyTempo = True`:
  - field hunters get the stock engine back (the whole-rotation stall);
  - party tempo members still wait 6 s between Stun Attacks while their other skills keep firing.

  A short tempo gap can never erase a skill's own gap.
- **One pipeline:** for every cast, the steps run in a fixed order: wasted-cast check → ledger → meter → skill
  cooldown → tempo follow-up. There's one listener per event; the skill-use one is a function listener, so the first
  step can stop the cast.
- **Healers aren't paced by the tempo:** party tempo covers DPS roles; healing is its own section and never shortens a
  cast gap.
- **Degrades gracefully:** the module reaches the jar's private phantom state by reflection (`PlaystyleAccess`). If a
  future `GameServer.jar` changes those classes, the affected section logs one warning and switches off; the meter keeps
  working. Party healing needs the party group plus the members' order fields (the heal group).

## Settings (`config/module.ini`)

| Key | Default | Section | What |
|---|---|---|---|
| `Enabled` | `True` | — | The switch for the whole module |
| `Debug` | `False` | — | Log every cooldown, follow-up and burn switch |
| `SkillPacing` | `True` | Skill pacing | `paceMs` as a per-skill cooldown for all phantoms |
| `PartyTempo` | `True` | Party tempo | Chain casts and resume swings |
| `CastGapMs`, `CastGapJitterMs` | `250`, `250` | Party tempo | Pause between casts; `1600`/`900` is about stock |
| `EngagedWindowMs` | `1500` | Party tempo | How long after its last swing or cast a member counts as fighting |
| `BurnPhase` | `True` | Party tempo | Skip setup skills on dying mobs |
| `BurnTtkSeconds` | `5` | Party tempo | "Dying" means the party kills it within this many seconds |
| `Roles` | `WARRIOR,DAGGER,ARCHER,MONK,NUKER` | Party tempo | Party roles it applies to |
| `Meter` | `True` | Meter | The `.dps` command |
| `PartyHealing` | `True` | Party healing | Healers decide from the party board |
| `HealTickMs` | `250` | Party healing | How often each healer decides |
| `CriticalPercent` | `35` | Party healing | Emergency HP% (after heals on the way) |
| `MinHealPercent` | `10` | Party healing | Smaller gaps are ignored |
| `OverhealLimitPercent` | `115` | Party healing | Largest heal allowed, as a % of the gap |
| `GroupHealMinTargets` | `3` | Party healing | Members who must need a group heal |
| `EmergencySkills` | `True` | Party healing | Benediction, Balance Life, Celestial Shield |
| `VetoWastedHeals` | `True` | Party healing | Stop the manager's support casts that are already covered |

**Tune a skill's gap:** change its `paceMs` in `game\data\PhantomPlaystyles.xml`, then `//phantom playstyle` (no
restart).

## Scripts

| File | What |
|---|---|
| `PhantomCombatModule.java` | Config, the event listeners and the order of the steps |
| `PlaystyleAccess.java` | Every reflection handle into the jar, resolved once |
| `SkillPacing.java` | The `paceMs` table, stripping and restoring it, the per-skill cooldown |
| `PartyTempo.java` | Follow-up, the engaged checks, burn phase and time-to-kill |
| `DpsMeter.java` | The `.dps` meter |
| `PartyBoard.java` | Damage in per member, the intent ledger, res and crisis claims, heal estimates |
| `HealerBrain.java` | Each healer's decision, cancel-on-full, and the wasted-cast check |

Not changed on purpose: casters already stand up from resting as soon as the leader targets a mob (the manager does
that at 20% MP or more), so resting to full MP only happens between fights.

## Enable, disable, remove

- **Disable one section:** set its switch to `False` and restart.
- **Disable all:** `Enabled = False`, restart.
- **Remove:** delete this folder, restart.
