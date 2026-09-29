# L2J Offline — Living World pack (Lineage II Interlude)

An offline L2JMobius Interlude server:
- the upstream "Living World" pack v0.1.25 (`Teravibes/L2-Living-Worlds`);
- a bundled JDK and MariaDB, and an Interlude client in `Client\`;
- fake players, phantoms, and an optional LLM chat "brain".

The user mods it for their own play.

## Read first
- `docs/README.md`: the index, an architecture sketch, and a "where do I change X" table. Every area has a page in
  `docs/`.
- `CHANGELOG.md`: what we've changed so far.
- `docs/id-registry.md`: take ids from here and record new ones.

## Rules
- **Every change gets a `CHANGELOG.md` entry and a commit** in this folder's own git repo. The entry says what
  changed, why, the files touched, and how to apply it.
- **Commits:** a plain summary line, then a body saying what changed and why. **No Claude/AI attribution** (no
  `Co-Authored-By`, no "Generated with").
- **Whitelist `.gitignore`.** A new top-level path is ignored until it's re-included there. Never commit `brain/.env`
  (it holds an API key). The client, `jre/`, `mariadb/` (the live DB) and `libs/` stay out.
- **Line endings.** `core.autocrlf=false` here, so each file keeps its own endings. Most stock files are CRLF, and the
  generators write CRLF.
- **Prefer additive mods:** `custom\` folders, new files, or a module in `game\modules\` over editing stock files.
- **Say how to apply a change:** restart, or which `//reload`. Ask before restarting: the user plays while we work.
  `Stop-Server.bat` leaves the client open.

## GitHub: upstream and our fork
Details: `docs/operations.md#the-github-fork`.

**The repos:**
- **Upstream** is `Teravibes/L2-Living-Worlds`. It's a source repo: the Java core is in
  `L2J_Mobius_CT_0_Interlude github/java/`, and the pack is in `…/dist/`. It publishes releases in pairs,
  `vX` and `vX-patch`, and `update.ps1` polls them. Newest seen: v0.1.25 = `ba8c9927` (checked 2026-09-29).
- **Our fork** is `cybercyberz/L2-Living-Worlds` (public; `gh` is logged in as `cybercyberz`):
  - `main` is an untouched copy of upstream. Never commit to it.
  - `living-world-mods` is the default branch: upstream v0.1.25 plus our mods, **one fork commit per local
    commit**, with the same message, author and date.
  - Tag `base-v0.1.25` marks the upstream commit we're built on, as the merge-base for updates.
- **This folder's own repo has no remote.** It's the source of truth; the fork mirrors it.

**How the layouts map** (`tools/forksync/forksync.py`, `PATH_MAP`):

| This install | In the fork |
|---|---|
| root (`game/`, `login/`, `db_installer/`, `launcher/`, `scripts/`, `*.bat`) | `L2J…/dist/` |
| `brain/` (`fpc_brain.py`, `requirements.txt`, `setup_brain.*`, `knowledge/`) | `L2J…/` |
| `tools/` | `L2J…/tools/` |
| `docs/` | `docs/mods/` |
| `CHANGELOG.md` | `CHANGELOG-mods.md` |
| `CLAUDE.md` | `CLAUDE.md` |

- **Never carried:** `.gitignore`, `brain/README.md` (written by the pack build), and new brain files until they get
  a `PATH_MAP` entry.
- **Different on purpose:** `launcher.ini`, both `Database.ini` files and `version.txt`. The installer writes
  install values into them (MariaDB paths, `StartBrain`, the version).

**After every local commit, carry it to the fork:**
1. Clone into the scratchpad with `git -c core.autocrlf=false -c core.longpaths=true clone
   https://github.com/cybercyberz/L2-Living-Worlds.git`. Without long paths the checkout fails.
2. Check out `living-world-mods`.
3. Run `python tools/forksync/forksync.py replay <fork-dir> <last-carried>..HEAD`. The last carried commit is the
   fork tip's subject matched here.
4. `git push`. The fork's `.gitattributes` normalizes line endings (`text=auto`), so CRLF-vs-LF isn't churn.

**Selective updates (only when the user asks):**
1. In the fork, `git fetch upstream`. Review the upstream commits since `base-v0.1.25`.
2. Cherry-pick or merge the chosen ones onto `living-world-mods`, and resolve conflicts there.
3. Bring them here with `forksync.py import <fork-dir> <rev-range>`, which writes into the working tree only.
4. Review with `git diff`, add a CHANGELOG entry, commit, and tell the user how to apply it.

Changes under `java/` (the core) aren't mapped. They need a rebuilt `libs/GameServer.jar`, either from a release
zip or from the fork's `build.xml` (there's no local build set up).

## Facts that trip you up
- **The core can't change.** `libs\GameServer.jar` has no source here. Its source is in the fork's `java/`, but
  there's no build set up. Datapack and module Java is compiled by the
  server at startup, so there's no local build. Compile errors land in `game\log\error*.log`.
- **Reading jar APIs.** `jre/bin/javap -cp libs/GameServer.jar <class>` shows what a class offers.
- **Updates overwrite files.** `launcher\update.ps1` overlays every file in `launcher\patch-manifest.txt`, including
  `handlers\MasterHandler.java`, `FakePlayers.ini`, `Olympiad.ini` and `AdminReload.java`. Don't run it; take
  updates through the fork (above). If it has been run anyway, check `git diff` and reapply our changes.
- **New handlers need registering.** They go through `MasterHandler` (patched on update) or a module's `ModuleHandlers`
  (preferred).
- **Community Board layout.** Buttons must be `width=114` (a wider button tiles a sliver). Keep pages small.
  Multisells opened from the board need `<npc>-1</npc>`.
- **The cash shop is generated.** Edit `tools\cashshop\build_cashshop.py` and rerun it; never hand-edit
  `multisell\custom\6001NN.xml`.
- **New ids have no client look.** A new item or NPC id shows nothing in the client without `displayId` (items and
  NPCs) or encrypted client `.dat` rows (`docs/client.md`).
- **Client `.u` packages.** Read and patch them only through `tools/l2mod`, and run
  `python tools/l2mod selftest` first. Its format notes and gate results are in `tools/l2mod/NOTES.md`; add to
  them as you learn.
- **Admin commands.** They're listed in `AdminCommands.xml` with a `description` attribute. `/loc` is a player
  command. There's no `//multisell`.
