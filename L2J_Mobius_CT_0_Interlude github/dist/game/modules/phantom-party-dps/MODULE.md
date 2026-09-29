# Phantom Party DPS module

More damage from **recruited phantom party members**, and a meter to prove it. Field hunters, supports, singers,
dancers, tanks and real players are not touched.

## Why

The party manager in `GameServer.jar` plays members for realism and safety, not damage:
- it makes **one decision per member per second**, and does nothing while the member casts;
- after every skill, the playstyle engine **waits 1.6–2.5 s** before the next one, even if it's ready;
- a **nuker never auto-attacks**, so it stands idle for most of that wait;
- a **fighter's swing stops after a skill** until the next manager tick re-arms it;
- **setup skills** (debuffs, stuns, openers) are cast even on a mob that dies two seconds later.

## What it does

**Fast follow-up.** When a DPS member starts a cast, the engine's pause is cut to `CastGapMs` (+ jitter). As soon as
the cast ends, the module picks the next skill with the same engine call the manager uses
(`PhantomPlaystyleEngine.pick`), so every playstyle rule still applies: conditions, the MP reserve, and the per-skill
`paceMs` from the `phantom-skill-pacing` module. If nothing is ready, a fighter goes straight back to swinging.

It only **follows the manager's lead**:
- it acts on the monster the member was already attacking or casting on, within the last `EngagedWindowMs`;
- it stops as soon as the member moves (repositioning, peeling, following), sits, is ordered to hold, is easing
  aggro, is recovering after a res, is in a PvP, or is switched to another target;
- **raid bosses and their minions are left entirely to the manager** and its raid gates;
- it never chooses targets: the manager (assist the leader, camp, pull) still decides what to hit.

**Burn phase.** From the party's damage over the last 4 seconds, the module estimates when each mob will die. Below
`BurnTtkSeconds`, a member's playstyle drops its DEBUFF, CONTROL and OPENER entries, so those casts become damage.
On a new target the full playstyle comes back.

**DPS meter.** `.dps` opens a window with each party member's DPS, share of damage, casts and **active %** (the share
of fight seconds with a hit, swing or cast), for the current or last fight and for the session. Pets count for their
master. `.dps reset` clears it. Use it to compare `Enabled = True` and `False` at the same spot.

## Settings (`config/module.ini`)

| Key | Default | What |
|---|---|---|
| `Enabled` | `True` | The switch |
| `Meter` | `True` | The `.dps` command |
| `FastFollowUp` | `True` | Chain casts and resume swings |
| `CastGapMs`, `CastGapJitterMs` | `250`, `250` | Pause between casts; `1600`/`900` is about stock |
| `EngagedWindowMs` | `1500` | How long after its last swing or cast a member counts as fighting |
| `BurnPhase` | `True` | Skip setup skills on dying mobs |
| `BurnTtkSeconds` | `5` | "Dying" means the party kills it within this many seconds |
| `Roles` | `WARRIOR,DAGGER,ARCHER,MONK,NUKER` | Party roles it applies to |
| `Debug` | `False` | Log every follow-up and burn switch |

## How it works

No jar change. The module listens to the global `ON_CREATURE_SKILL_USE`, `ON_CREATURE_ATTACK` and
`ON_CREATURE_DAMAGE_DEALT` events, and reaches the party manager's member records and the engine's per-member state by
reflection. If a future `GameServer.jar` changes those classes, it logs one warning and the follow-up and burn phase
stay off (the meter still works).

It needs the `phantom-skill-pacing` module: without it, cutting the engine's pause would also cut the per-skill
`paceMs` gaps.

Not changed on purpose: casters already stand up from resting as soon as the leader targets a mob (the manager does
that at 20% MP or more), so resting to full MP only happens between fights.

## Enable, disable, remove

- **Disable:** `Enabled = False`, restart.
- **Remove:** delete this folder, restart.
