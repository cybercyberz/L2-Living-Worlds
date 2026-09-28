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

## Facts that trip you up
- **The core can't change.** `libs\GameServer.jar` has no source here. Datapack and module Java is compiled by the
  server at startup, so there's no local build. Compile errors land in `game\log\error*.log`.
- **Reading jar APIs.** `jre/bin/javap -cp libs/GameServer.jar <class>` shows what a class offers.
- **Updates overwrite files.** `launcher\update.ps1` overlays every file in `launcher\patch-manifest.txt`, including
  `handlers\MasterHandler.java`, `FakePlayers.ini`, `Olympiad.ini` and `AdminReload.java`. After an update, run
  `git diff` and reapply.
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
