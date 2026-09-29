# Phantom Skill Pacing module

Makes `paceMs` in `game\data\PhantomPlaystyles.xml` a **per-skill cooldown** for phantoms.

## The problem it fixes

A playstyle entry can carry `paceMs`, for example Stun Attack with `paceMs="6000"`. The authors meant "don't recast
this skill more often than every 6 seconds". The engine in `GameServer.jar` (`PhantomPlaystyleEngine.pick`) does
something else: it uses `paceMs` as the member's gate for **every** next cast. So after one Stun Attack a Warrior
casts nothing else for about 6 seconds (only PANIC entries get through) and just auto-attacks. After Lightning Strike
(`paceMs="15000"`) a Hell Knight goes silent for 15 seconds. 49 entries use `paceMs` of 4 seconds or more.

## What it does

- **Moves `paceMs` out of the engine's shared gate.** At startup the module reads the loaded playstyles, remembers
  each entry's `paceMs` by class and skill, and sets it to 0 in the loaded data. The engine then waits only its
  default beat (about 1.6–2.5 s) after any cast.
- **Puts it back on the one skill.** When a phantom casts a paced skill, that skill is disabled on that phantom for
  `paceMs`. The engine already skips a disabled skill and moves on to the next entry. The skill's own reuse still
  applies, so the longer of the two wins.
- **Phantoms only.** Field hunters, recruited party members and alt companions. A real player of the same class keeps
  normal reuse.
- **Follows reloads.** `//phantom playstyle` loads fresh data; the module notices within 2 seconds and applies itself
  again. The XML file itself is never changed.

The engine is not patched: this works from outside through the `ON_CREATURE_SKILL_USE` event and reflection on
`PhantomPlaystyleData`. If a future `GameServer.jar` changes those classes, the module logs a warning and stays off,
and the engine's stock behavior returns.

## Settings (`config/module.ini`)

| Key | Default | What |
|---|---|---|
| `Enabled` | `True` | The switch |
| `Debug` | `False` | Log each cooldown applied and each reload re-sync |

## Enable, disable, remove

- **Disable:** set `Enabled = False` and restart. The engine's stock `paceMs` behavior returns.
- **Remove:** delete this folder and restart.
- **Tune a skill's gap:** change its `paceMs` in `PhantomPlaystyles.xml`, then `//phantom playstyle` (no restart).
