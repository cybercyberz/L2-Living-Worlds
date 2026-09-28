# l2mod

Tools to read, verify and patch the Interlude client's UnrealScript packages (`Client\Interlude\system\*.u`). They
are pure Python (3.8+) and need no installs.

The tools are only trusted because they reproduce the stock client exactly. `selftest` checks all of this on all 22
client packages in about 10 seconds; see [NOTES.md](NOTES.md) for the results and the format details:
- every package reads and writes back byte for byte;
- every script decodes;
- every listing reassembles to identical bytes.

## Commands
Run these from the pack root.

| Command | What |
|---|---|
| `python tools/l2mod decompile interface.u` | For every class, writes its original source (`Class.uc`, embedded in the package) and a bytecode listing (`Class.asm`) to `tools/l2mod/out/interface/`. |
| `python tools/l2mod disasm interface.u QuestTreeWnd.OnClickButton` | Prints one function's listing. |
| `python tools/l2mod info interface.u` | Prints object counts. |
| `python tools/l2mod build patches/x.l2patch` | Compiles and verifies a patch, and shows the resulting bytecode. Writes nothing. |
| `python tools/l2mod install patches/x.l2patch ...` | Builds, verifies and installs patches into the client. Refuses while the game runs. |
| `python tools/l2mod restore [interface.u]` | Puts the stock package back. |
| `python tools/l2mod status` | Shows which packages are stock, patched by l2mod, or changed by something else. |
| `python tools/l2mod selftest [--quick]` | Runs every safety gate. `--quick` checks `interface.u` only. |

The tools only ever read **stock** packages. They're checked by SHA-256 (`l2mod/stock.py`), and the stock copy is
kept in `backup\client\<name>.orig`. A package that isn't stock is refused unless its stock backup exists.

## Writing a patch
A patch is a `.l2patch` file in `tools/l2mod/patches/`. It holds UnrealScript that replaces whole function bodies.
The function keeps its existing parameters and locals.

```
; Quest Navigator: clicking a quest in Alt+U asks the server for its NPCs.
package interface.u

replace QuestTreeWnd.OnClickButton
{
	switch( strID )
	{
	case "btnClose":
		HandleQuestCancel();
		break;
	}
	if (Left(strID, 4) == "root")
	{
		UpdateTargetInfo();
		RequestBypassToServer("_bbs_questnav step " $ strID);
	}
}
```

To make one:
1. **Start from the stock body.** Run `python tools/l2mod decompile interface.u`, open
   `out/interface/<Class>.uc`, and copy the function you want.
2. **Edit it** and save it as a `.l2patch`.
3. **Check it.** Run `python tools/l2mod build patches/<name>.l2patch` and read the listing.
4. **Install it.** Close the client, then run `python tools/l2mod install patches/<name>.l2patch`.

Several patches can be installed at once, as long as each function is changed by only one of them.

Patches build from the stock package every time. The result is re-read and every object you didn't change is
checked to be byte-identical. `asm Class.Function { ... }` blocks take a bytecode listing instead of source, for
anything the compiler doesn't cover.

**Window layout** patches use `package interface.xdat` and three kinds of line:

```
package interface.xdat
clone QuestTreeWnd.btnClose as btnQuestNav     ; copy a control inside its window
set QuestTreeWnd.btnQuestNav.anchor_x = 170     ; change any field: int, float or "string"
remove QuestTreeWnd.txt324                      ; delete a control
```

To see a window's controls and fields, run `python tools/l2mod xdat QuestTreeWnd`. A new control that should do
something needs a script patch too. For example, add a `case "btnQuestNav":` to that window's `OnClickButton`.

**Game data** patches edit `.dat` tables by row. The tables are sysstring, npcname, itemname, questname,
skillname and systemmsg. Rows are picked by id, or by `id/level` for quests and skills:

```
package itemname-e.dat
set 57 name = "Gold"
clone 57 as 60000                    ; a client row for a custom item id
set 60000 description = "A token."
```

`python tools/l2mod dat itemname-e.dat 57` shows a row. `python tools/l2mod dat npcname-e.dat Gremlin` searches the
text fields.

The compiler matches the original UE2 compiler exactly for everything in `interface.u` (every stock function
compiles to its stock bytes). The rules it follows, and what it doesn't support yet, are in [NOTES.md](NOTES.md).

## Reading a listing
```
function QuestTreeWnd.OnClickButton    ; export 4262, ScriptSize 60, ...
    L0000: Switch(0, Local(&QuestTreeWnd.OnClickButton.strID))
    L0007: Case(@L001D, Str("btnClose"))
    L0014: Virtual(#HandleQuestCancel)
    L001A: Jump(@L0020)
    L001D: Case(default)
    L0020: JumpIfNot(@L003A, N122(N128(Local(&QuestTreeWnd.OnClickButton.strID), IntConstByte(4)), Str("root")))
    L0034: Virtual(#UpdateTargetInfo)
    L003A: Return(Nothing)
```
- `Lxxxx`: a statement's memory offset, the unit jumps use. `@Lxxxx` is a jump target.
- `&Path`: an object reference. `#Name`: a name.
- `N122(...)`: native function 122 (here, string `==`), and `N128` is `Left`.

`l2mod.asm.assemble` turns a listing back into bytes. Hand-written code can use its own labels (`done:` …
`Jump(@done)`) and leave the offsets off; the assembler works them out.

## Roadmap
Each stage ships only when its gate passes; see the plan in NOTES.md.
1. Package reader and writer. **Done.**
2. Decompiler, disassembler and assembler. **Done.**
3. The UnrealScript compiler for function bodies, patch files, and install/restore. **Done:** every stock
   `interface.u` function compiles to its stock bytes, and the Quest Navigator is now a source patch.
4. `interface.xdat` window layout: exact read and write, plus `set`/`clone`/`remove` patches. **Done.**
5. `.dat` game data: decrypt, six table schemas, row patches, re-encryption with this client's key. **Done**
   (in-game check pending).
6. A full class compiler.
