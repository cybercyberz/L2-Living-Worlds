# Living World: fake players, phantoms, and the brain

The pack fills the world with bot characters.
- **FPCs** ("fake player characters") are NPC-backed players that walk, fight, trade and chat.
- **Phantoms** are fuller bot players. They hunt with playstyles, form parties and clans, PvP by rules, and take part
  in the Olympiad.
- **The brain** optionally gives both of them in-character chat through an LLM.

The engine for all of this is in the jar: the `FakePlayer*` and `Phantom*` managers. Everything you can tune is
config and data.

## Configs

| File | What |
|---|---|
| `game\config\Custom\FakePlayers.ini` | The master switches and the bulk of the tuning (see below) |
| `game\config\Custom\PhantomOlympiad.ini` | Phantom nobles in the Olympiad: roster size (40), levels (76–80) |
| `game\config\Rates.ini` → `FakePlayerStorePriceMultiplier` | Prices in bot private stores |

Key `FakePlayers.ini` groups (values as installed):
- **Master switches:** `EnableFakePlayers`, `FakePlayerChat`, `FakePlayerBehavior`, `PhantomAutoHuntingZones`,
  `PhantomHunterPlaystyles` (all True). `FakePlayerDeployCount = 0`.
- **Behaviour:**
  - `FakePlayerUseShots`, `FakePlayerAggroMonsters` (True)
  - `FakePlayerAggroPlayers`, `FakePlayerAggroFPC` (False)
  - `FakePlayerCanPickup`, `FakePlayerCanDropItems`
  - `FakePlayerRecruitEnchantMin/Max` (0–3)
- **Parties with bots:** `FakePlayerPartyQuestCredit` (True, range 1500), `FakePlayerPartyExpShare`,
  `FakePlayerPartyLootShare` (False).
- **Ambient chat:** `FakePlayerAmbientTradeIntervalSeconds` (90), `…ShoutIntervalSeconds` (120),
  `FakePlayerMaxPublicChatsPerMinute` (8), `FakePlayerBotChatReplyChance` (15), `FakePlayerBotChatChainDepth` (2).
- **Phantom PvP:**
  - `PhantomPvpEnabled`, `…SelfDefense`, `…ReactToFlagged`, `…Duels`, `…PartyDefense`, `…ClanDefense` (True)
  - `PhantomPvpOpenWorldGank` (False)
  - `PhantomPvpAggressorPercent` (15), `…ReactChancePercent` (25), `…FleeHpPercent` (30),
    `…EngageCooldownSeconds` (300), `…MaxLevelGapAbovePlayer` (6)

`FakePlayers.ini` is in the update patch list. After an update, run `git diff` to see if your tuning was reset.

## Data files (`game\data\`)

| File | What | Apply with |
|---|---|---|
| `PhantomPlaystyles.xml` (+ `xsd\PhantomPlaystyles.xsd`) | How phantoms of each class fight, buff and move | `//phantom playstyle` |
| `PhantomPopulations.xml` | Where phantoms live and hunt, and how many. **Generated** by `tools/build_populations.py` in the upstream dev repo; edit with care or with the Control Panel's population editor | restart |
| `BotClans.xml` (+ `crests\`) | Bot clans and their crests | restart |
| `FakePlayerBehavior.xml` | FPC behaviour rules | restart |
| `FakePlayerChatData.xml` | Canned chat lines (used when the brain is off) | `//reload fakeplayerchat` |
| `fpc-map-images.json` | Map data for the Control Panel's population map | — |
| `stats\npcs\custom\fpc_passive.xml` (80000), `fpc_combat.xml` (81001) | NPC templates the FPCs use | restart |

**Playstyle pacing.** Each combat tick the engine casts the first listed skill whose checks pass, then waits a beat
of about 1.6–2.5 s. On its own, the jar's engine uses an entry's `paceMs` as that beat for every skill, so a paced
skill stalls the whole rotation. The `phantom-skill-pacing` module
([MODULE.md](../game/modules/phantom-skill-pacing/MODULE.md)) turns `paceMs` into a per-skill cooldown instead. The
XML header lists what each `use` and `when` actually does.
| `spawns\Others\FakePlayers.xml` | Fixed FPC spawn (NPC 80000 "Evi" in Giran) | restart |

The **Control Panel** (`LivingWorld.exe` → config editor, which is `tools\l2admin\index.html`) has editors for
playstyles, bot clans and crests, and populations. Use it rather than hand-editing the big XMLs.

## Admin commands

| Command | What |
|---|---|
| `//phantom spawn` / `count` / `clear` / `reload` / `playstyle` / `debug` | Manage phantoms |
| `//reloadfakeplayers`, `//reload fakeplayerchat` | Reload FPC data or chat lines |
| `//fakechat` | Test bot chat |
| `//debug_on` / `//debug_off` | Bot debug output |
| `//record_route` / `//stop_route` / `//list_routes` | Record walking routes for FPCs |

## The brain (optional AI chat)
- **What it is:** `brain\fpc_brain.py` is a Flask service on `127.0.0.1:5000`.
- **Endpoint:** `POST /chat`. The body is the chat message; context comes in `X-…` headers (`X-FPC`, `X-Mode`,
  `X-Player`, `X-Location`, `X-Bot-Level/Class/Race/Gear`, `X-Deal-*`, `X-Buddy-*`…).
- **Reply:** plain text.
- **How the server calls it:** through `FakePlayerChatManager` in the jar, with a 45 s timeout. The URL is fixed in
  the jar.

| Topic | Detail |
|---|---|
| Modes | WHISPER, SAY, SHOUT, SHOUTAMBIENT, AMBIENT, TRADE, ITEM, LFP, OFFER, NOSELL, PARTY, PARTYEVENT, BUDDY, BUDDYCHAT, FRIEND |
| Providers | Any OpenAI-compatible provider: ollama (local, free), deepseek, openai, groq, openrouter, mistral |
| `brain\.env` keys | `PROVIDER`, `MODEL`, one `<PROVIDER>_API_KEY`, `OLLAMA_MODEL`, `BRAIN_LLM_TIMEOUT` (40), `BRAIN_LLM_RETRIES` (0), `BRAIN_LOG_CONTENT/ALL/PRIVATE`. **Holds a secret; never commit it** (git ignores it). |
| Knowledge | `brain\knowledge\*.txt`: one `[space separated tags] fact` per line, loaded at boot. A fact is added to the bot's prompt when its tags match the message. `00`–`50` are hand-written. `*_generated.txt` come from the upstream `tools/build_knowledge.py`, so don't hand-edit them. Restart the brain after editing. |
| Memory | `brain\memory\fpc_memory.json` (created at runtime, not in git) |
| Setup | `scripts\Configure-Brain.bat` (`setup_brain.bat --reconfigure`). Other flags: `--reset` (wipe `.env`), `--auto` (non-interactive start, used by the launcher). It installs Python 3.12 and Ollama with winget if needed. |
| Autostart | `launcher.ini` → `[servers] StartBrain=true` (currently on) |

To give the bots new world knowledge (a custom NPC, a new shop), add a line to a hand-written knowledge file. For
example:

```
[shop cash buy community board] Press Alt+B and open Cash Shop to buy any tradeable item for adena.
```

Add it to `00_general.txt`, then restart the brain.
