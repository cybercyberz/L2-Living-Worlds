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

## Compiler rules (stage 3)
These are what the UE2 compiler that built this client does. Each one was found from a mismatch in the gate and
confirmed by the gate going green.
- **Required types.** A literal compiled with a required type converts at compile time:
  - an int literal becomes `FloatConst` for a float, or `ByteConst` for a byte **when 0 <= value < 255** (255
    itself stays an int and gets a cast);
  - a float literal becomes an int (truncated) for an int.

  Otherwise a conversion is a `PrimitiveCast`. Casts are never folded.
- **Where the required type flows.** It flows into assignment right-hand sides, arguments (the parameter type),
  return values and case labels. In a binary operator it flows into the **left operand only**.
- **Parentheses.** A parenthesised expression is compiled on its own against the required type: its result is
  converted straight away when the conversion is implicit (byte, int, float). So `(a % 12) + 1` into an int
  becomes `FloatToInt(a % 12) + 1`, but `f * g + 1` doesn't convert `f * g`.
- **Overloads.** Operators are chosen by the cost of converting the operands; the result type plays no part.
  Costs used: exact 0, byte→int 1, int→byte 2 (3 if not a constant), byte or int→float 3, float→int or byte 4;
  a coerce parameter accepts any cast at cost 10. The byte `==` has no overload of its own: both sides go through
  `ByteToInt`.
- **Bools.** Every read of a bool variable is wrapped in `BoolVariable`, and every assignment to one is
  `LetBool(BoolVariable(var), value)`.
- **`&&` and `||`.** The second operand is `Skip(size + 1, expr)`. The +1 covers the operator's closing
  `EndFunctionParms`, which the short-circuit also jumps over.
- **Calls.**
  - Final natives with an index become the native token. Other final functions are `Final(ref)`; everything
    else is `Virtual(#name)`.
  - `class'X'.static.F()` becomes `ClassContext(ObjectConst X, skip, size, call)`, and `obj.F()` becomes
    `Context(obj, skip, size, call)`.
  - `size` is the result's in-memory size times its array dimension, capped at 255. Strings, dynamic arrays and
    void use 0.
  - A skipped optional argument in the middle is `Nothing`; trailing ones are dropped.
  - A string result used as a statement is wrapped in `EatString`.
- **Structs.** A struct's size aligns every field to 4 bytes except bytes. **Adjacent bools share one 32-bit
  word.**
- **Constants.** A `const` is inlined from its source text. `obj.CONST` and `obj.EnumValue` keep the object:
  `Context(obj, skip, size, ByteConst/IntConst)`. `Enum.Value` is a `ByteConst`, and `EnumName(x)` is an explicit
  `IntToByte` cast.
- **Control flow.**
  - `if`: `JumpIfNot(else)`, then the then-branch, then `Jump(end)` (only when there's an else).
  - `while`: `continue` jumps to the loop's back-jump, not to the top.
  - `switch` without a `default:` still gets a `Case(default)` at the end.
  - Every function ends with an implicit `Return(Nothing)`.
  - `foreach` is `Iterator(call, @end)`, the body, `IteratorNext`, then `@end: IteratorPop`. A `return` inside
    it pops the iterator first.
- **`super` in a state** resolves to the same state in the parent class first.

## Gate results, stage 3 (2026-09-28)
Each stock function was compiled from its own embedded source and compared byte for byte:

| Package | Match | Notes |
|---|---|---|
| interface.u | **1,641 / 1,641** | The UI package, and the target for mods. Enforced by `selftest`. |
| UWindow.u | 670 / 699 | Remaining gaps are listed below. |
| Engine.u | 1,288 / 1,441 | Remaining gaps are listed below. |
| Core.u | 4 / 4 | |
| nwindow.u | none to compile | All native. |

- **The Quest Navigator,** written as source (`patches/quest-navigator.l2patch`), builds to exactly the file
  that was hand-patched and tested in game (sha256 `144a2f5d…8638`).
- **Not yet supported** (engine code only; the UI package doesn't use any of it). This is stage 6's list:
  - casts to engine-intrinsic classes (`Viewport(x)`, `Class(x)`, `vector(x)`, `rotator(x)`);
  - object literals for a package's own exported textures;
  - `obj.default.Var`;
  - struct `==` / `!=` (`StructCmpEq`/`Ne`);
  - enums reached through an object inside an argument (`C.DE_Created`);
  - empty name literals `''`;
  - variables of intrinsic classes (`Viewport.Actor`);
  - one `foreach` + `break` pattern.

## interface.xdat (stage 4)
- **Encryption.** None.
- **Layout:**
  1. Window count (int32), then each top-level `Window`, with no type prefix.
  2. Shortcut count, then each shortcut.
  3. An int32, always 1.
  4. The default-position count, then each position.
  5. A 20-byte tail.
- **Every control** starts with the common DefaultProperty block:
  - name, superName, two ints, three strings, an int;
  - `size`, and if set: `size_absolute_values`, then (if 0) a compact 0 and two percent floats, then width and
    height;
  - `anchor`, and if set: parent and this alignment, the control, x and y;
  - three ints, popupType and popupValue.

  Then come the control type's own fields.
- **Children.** A Window's (or ScrollArea's) children are a list: an int32 count, then per child its type name as
  an FString, then the control.
- **Types.** Bools, enums and colours are int32. Strings are FStrings.
- **Field lists** come from acmi's MIT-licensed xdat_editor schema, `ct0` (Interlude). All 31 control types that
  appear in the stock file are covered.
- **Gate (2026-09-28).** The stock `interface.xdat` round-trips byte for byte: 140 windows, 2,229 windows plus
  controls, 8 shortcuts and 56 default positions. Layout patches check that untouched windows are byte-identical.
- **Button labels** are `buttonName` sysstring ids, and text boxes use `sysstring`. Reading their text needs
  `sysstring-e.dat` (stage 5).

## .dat tables (stage 5)
- **Format.** Every `.dat` (and `l2.ini`, `user.ini`) is `Lineage2Ver413`:
  - a 28-byte header;
  - 128-byte RSA blocks, textbook RSA with no padding. Each decrypted block holds up to 124 data bytes: byte 3 is
    the count, and the data ends at a 4-byte boundary;
  - a 20-byte footer: 12 zero bytes, the CRC32 of everything before the footer, and 4 zero bytes. `decrypt` checks
    the CRC field (bytes 12-15) first.
    - Checked 2026-09-29: all 43 Ver41x client files pass.
    - The two `Lineage2Ver111` files (`Localization.ini`, `ttfontinfo.ini`) are a different format that
      `ver41x` doesn't read. Their footers have data in bytes 4-11, but the CRC sits in the same place.

  The joined data is a 4-byte uncompressed size and a zlib stream.
- **The key.** This client uses the community **l2encdec** key, not the official 413 key:
  - every stock `.dat` decrypts with the l2encdec modulus (exponent 0x1D);
  - `L2.bin` carries the l2encdec modulus (`Engine.dll` and `Core.dll` still have the official one).

  The l2encdec encryption exponent is public. **Re-encrypting a stock file's own data stream rebuilds the stock
  file byte for byte**, footer included. So we can write `.dat` files this client reads, without patching any
  binary.
- **Compression.** Python's zlib doesn't reproduce the stock compressed streams byte for byte (a different
  deflate implementation). An edited table therefore differs inside the compressed stream, which is still valid
  zlib. An unedited table is written back as the original file.
- **Tables.** Each is a uint32 row count, then the rows, then the FString `"SafePackage"`.
  - Field layouts follow the L2ClientDat Interlude/SoD definitions (format only).
  - The `CNTR` count type is a compact index.
  - `UNICODE` is an int32 byte length plus UTF-16LE with no terminator. `ASCF` is an FString.
- **Gate (2026-09-28).** Six tables round-trip byte for byte:

  | Table | Rows |
  |---|---|
  | sysstring | 2,083 |
  | npcname | 6,519 |
  | itemname | 9,208 |
  | questname | 2,050 |
  | skillname | 29,812 |
  | systemmsg | 2,083 |

  Patches check that untouched rows are unchanged.
- **Not yet confirmed in game:** that the client loads a table we re-compressed. Test it with
  `patches/examples/rename-adena.l2patch`.
