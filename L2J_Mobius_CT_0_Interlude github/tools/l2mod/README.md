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
| `python tools/l2mod selftest [--quick]` | Runs every safety gate. `--quick` checks `interface.u` only. |

The tools only ever read **stock** packages. They're checked by SHA-256 (`l2mod/stock.py`), and the stock copy is
kept in `backup\client\<name>.orig`. A package that isn't stock is refused unless its stock backup exists.

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
3. A subset UnrealScript compiler for function bodies, with a gate: compile stock functions and get the stock bytes.
   The Quest Navigator patch will be rebuilt with it.
4. `interface.xdat` window layout.
5. `.dat` game data (Ver413).
6. A full class compiler.
