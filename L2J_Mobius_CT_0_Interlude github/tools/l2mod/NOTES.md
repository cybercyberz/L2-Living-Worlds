# l2mod notes

A running log of what we've learned about the Interlude client formats and the results of every gate. Newest stage
last. Add to it whenever a tool learns something new.

## Package format (UE2, version 123, licensee 30)
- **Ver111 wrapper.** A 28-byte UTF-16LE header, `Lineage2Ver111`, then the payload XORed with `0xAC`, then a
  20-byte plain footer.
  - Footer bytes 12-15 are the CRC32 of the header plus the encrypted payload.
  - Footer bytes 0-11 differ per file (for example `…2d000000 64000000`) and are kept as they are.
  - Every client `.u` is Ver111.
- **Header.** The standard 36 bytes, then a 16-byte GUID, then the generation count and entries. All 22 packages
  have exactly one generation, and its counts equal the current name and export counts.
- **Stock layout.** It is the same in all 22 packages: header, name table (at 64), object data, import table, then
  the export table running to the end of the file. There's no slack between sections.
- **Names.** Each is a compact length (including the null), latin1 text, then 4 bytes of flags.
- **Object serialisation**, v123:
  - **Every non-Class object** starts with tagged properties. A StateFrame comes first only when `RF_HasStack` is
    set; this never happens in the stock files.
  - **Property:** Field (Super, Next), then ArrayDim int32, PropertyFlags uint32, Category name, and RepOffset
    uint16 if `CPF_Net`. Subclass extras:

    | Property | Extra fields |
    |---|---|
    | Object | PropertyClass |
    | Class | PropertyClass, MetaClass |
    | Struct | Struct |
    | Byte | Enum |
    | Array | Inner |
    | Delegate | Function |
  - **Struct:** Field, then ScriptText, Children, FriendlyName and **CppText** (all compact), then Line int32,
    TextPos int32, ScriptSize int32 (in-memory size), then bytecode.
  - **Function:** Struct, then iNative uint16, OperPrecedence uint8, FunctionFlags uint32, and RepOffset uint16 if
    `FUNC_Net`.
  - **State:** Struct, then ProbeMask uint64, IgnoreMask uint64, LabelTableOffset uint16, StateFlags uint32.
  - **Class:** State, then ClassFlags, a 16-byte ClassGuid, Dependencies[] (class, deep int32, CRC uint32),
    PackageImports[], ClassWithin, ConfigName, HideCategories[], then default properties as tagged properties.
    There are no leading tagged properties: the defaults come last.
  - **Const:** an FString. **Enum:** a list of names. **TextBuffer:** Pos, Top, then Text as an FString. Each class
    stores its full original source as a `ScriptText` TextBuffer.

## Bytecode
- **The stock UE2 token table covers everything.** No Lineage II licensee tokens were found in 9,362 scripts.
  Tokens used, beyond the classic 0x00-0x34: 0x36 StructMember, 0x37 DynArrayLength, 0x38 GlobalFunction,
  0x39 PrimitiveCast (u8 cast code, expr), 0x40/0x41 DynArrayInsert/Remove, 0x42-0x44 delegates.
- **Sizes.** In memory, object references and names are 4 bytes; on disk they're compact indices. `ScriptSize` and
  every jump offset count memory bytes.
- **Natives.** Calls to natives are one byte for index 0x70-0xFF, or `0x60 + hi, lo` for extended natives; the
  arguments end with 0x16.
- **Calls.** Native final functions defined in another package, such as `UIScript.RequestBypassToServer`, are
  called as `1C <import ref> args 16`. Virtual calls are `1B <name> args 16`.
- **Case.** `0A <u16 next>` followed by the case expression; `0A FFFF` is `default`.

## Gate results
- **Stage 1, 2026-09-28:**
  - 22 of 22 packages round-trip byte for byte (read → write → encrypt).
  - All 23,339 non-struct script objects, and all 9,362 Function, State, Class and Struct objects, parse to exactly
    their serial size.
  - The relocating writer moves only the edited object.
- **Stage 2, 2026-09-28:**
  - 9,362 of 9,362 scripts decode with no unknown tokens, match their `ScriptSize` exactly, and have every jump on a
    token boundary. Re-encoding gives identical bytes.
  - `asm(disasm(f)) == f` for 9,362 of 9,362.
  - **Fixed along the way:** names containing spaces are now written as `#"Bip01 L Hand"`, and a `;` inside a
    string is no longer taken for a comment.
