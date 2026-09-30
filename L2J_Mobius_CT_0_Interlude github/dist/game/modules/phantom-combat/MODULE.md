# Phantom Combat module

Decides **when a phantom may cast next**, in one place. It has three sections, each with its own switch:

| Section | Who | Idea |
|---|---|---|
| **Skill pacing** | every phantom | A paced skill waits its own `paceMs`, and nothing else stalls |
| **Party tempo** | recruited DPS members | They don't idle between skills |
| **Meter** | you and your party | `.dps` measures the difference |

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
- **One pipeline:** for every cast, the steps run in a fixed order: meter → skill cooldown → tempo follow-up. There's
  one listener per event.
- **Degrades gracefully:** the module reaches the jar's private phantom state by reflection (`PlaystyleAccess`). If a
  future `GameServer.jar` changes those classes, the affected section logs one warning and switches off; the meter keeps
  working.

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

Not changed on purpose: casters already stand up from resting as soon as the leader targets a mob (the manager does
that at 20% MP or more), so resting to full MP only happens between fights.

## Enable, disable, remove

- **Disable one section:** set its switch to `False` and restart.
- **Disable all:** `Enabled = False`, restart.
- **Remove:** delete this folder, restart.
