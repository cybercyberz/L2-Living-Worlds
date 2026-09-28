"""Patch the Interlude client's Alt+U quest window so clicking a quest sends it to the server.

It adds one statement to QuestTreeWnd.OnClickButton, inside its `if (Left(strID, 4) == "root")` branch:

    RequestBypassToServer("_bbs_questnav step " $ strID);

The quest-navigator server module answers with a window listing the quest's NPCs and mobs; clicking one marks it on
the radar and map. There is no UnrealScript compiler for this client, so the tool edits the compiled bytecode.

Before writing anything, it checks that:
- the input is the exact stock interface.u (SHA-256), and the function's bytes are exactly what was decoded;
- re-serialising the untouched tables reproduces the original bytes;
- after patching, every other object is byte-identical and the new script's in-memory size matches its header.

    python patch_questtreewnd.py            # patch Client\\Interlude\\system\\interface.u from the backup
    python patch_questtreewnd.py --restore  # put the stock interface.u back
    python patch_questtreewnd.py --check    # build and verify the patch, write nothing
"""
import hashlib
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l2ver111  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CLIENT = os.path.join(ROOT, "Client", "Interlude", "system", "interface.u")
BACKUP = os.path.join(ROOT, "backup", "client", "interface.u.orig")
STOCK_SHA256 = "4ca40e2936138d9551412767c695b6e54e8f2843daf437536811705704b91019"

BYPASS = b"_bbs_questnav step "

# QuestTreeWnd.OnClickButton as shipped. The script body is 60 bytes in memory.
STOCK_FUNCTION = bytes.fromhex(
    "00 ca01 6542 00 6a2f 16 00"  # None props, Super, Next, ScriptText, Children (strID), FriendlyName, CppText
    " 31000000 f6030000 3c000000"  # Line, TextPos, ScriptSize=60
    " 05 00 006a2f"  # switch (strID)
    " 0a 1d00 1f 62746e436c6f736500"  # case "btnClose":
    " 1b 430f 16"  # HandleQuestCancel();
    " 06 2000"  # break;
    " 0a ffff"  # default:
    " 07 3a00 7a 80 006a2f 2c04 16 1f 726f6f7400 16"  # if (Left(strID, 4) == "root")
    " 1b 6705 16"  # UpdateTargetInfo();
    " 04 0b"  # return;
    " 0000 00 02000200"  # iNative, OperPrecedence, FunctionFlags
)
SCRIPT_START = 22  # offset of the script inside the function's serial data
SCRIPT_SIZE_AT = 18
JUMP_TARGET_AT = SCRIPT_START + 29  # the `3a00` of the JumpIfNot
RETURN_AT = STOCK_FUNCTION.index(bytes.fromhex("040b0000"), SCRIPT_START)

# RequestBypassToServer("_bbs_questnav step " $ strID);
#   1c <import -285 UIScript.RequestBypassToServer>  EX_FinalFunction
#   70                                               native 112: $ (string concat)
#   1f "..."\0                                       EX_StringConst
#   00 <export 3050 strID>                           EX_LocalVariable
#   16 16                                            end of $ args, end of call args
INSERT = b"\x1c\xdd\x04\x70\x1f" + BYPASS + b"\x00" + b"\x00\x6a\x2f" + b"\x16\x16"
INSERT_MEMORY = 1 + 4 + 1 + 1 + len(BYPASS) + 1 + 1 + 4 + 1 + 1  # object refs are 4 bytes in memory


# ----------------------------------------------------------------------------------------------------- package format

def read_ci(d, p):
    b = d[p]
    p += 1
    neg = b & 0x80
    v = b & 0x3F
    if b & 0x40:
        shift = 6
        while True:
            b = d[p]
            p += 1
            v |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
    return (-v if neg else v), p


def write_ci(v):
    neg = v < 0
    v = abs(v)
    out = bytearray([(0x80 if neg else 0) | (v & 0x3F) | (0x40 if v >= 0x40 else 0)])
    v >>= 6
    while v:
        out.append((v & 0x7F) | (0x80 if v >= 0x80 else 0))
        v >>= 7
    return bytes(out)


class Package:
    HEADER = struct.Struct("<IHHIiiiiii")

    def __init__(self, d):
        self.d = d
        (self.tag, self.ver, self.lic, self.flags, self.name_count, self.name_offset, self.export_count,
         self.export_offset, self.import_count, self.import_offset) = self.HEADER.unpack_from(d, 0)
        if self.tag != 0x9E2A83C1:
            raise SystemExit("not an Unreal package")

        self.names = []
        p = self.name_offset
        for _ in range(self.name_count):
            n, p = read_ci(d, p)
            self.names.append(d[p:p + n - 1].decode("latin1"))
            p += n + 4  # string, then flags
        self.names_end = p

        self.imports = []
        p = self.import_offset
        for _ in range(self.import_count):
            class_package, p = read_ci(d, p)
            class_name, p = read_ci(d, p)
            package = struct.unpack_from("<i", d, p)[0]
            p += 4
            object_name, p = read_ci(d, p)
            self.imports.append([class_package, class_name, package, object_name])
        self.imports_end = p

        self.exports = []
        p = self.export_offset
        for _ in range(self.export_count):
            cls, p = read_ci(d, p)
            sup, p = read_ci(d, p)
            outer = struct.unpack_from("<i", d, p)[0]
            p += 4
            name, p = read_ci(d, p)
            flags = struct.unpack_from("<I", d, p)[0]
            p += 4
            size, p = read_ci(d, p)
            offset = 0
            if size > 0:
                offset, p = read_ci(d, p)
            self.exports.append([cls, sup, outer, name, flags, size, offset])
        self.exports_end = p

    def import_table(self):
        return b"".join(write_ci(a) + write_ci(b) + struct.pack("<i", c) + write_ci(o) for a, b, c, o in self.imports)

    def export_table(self):
        out = bytearray()
        for cls, sup, outer, name, flags, size, offset in self.exports:
            out += write_ci(cls) + write_ci(sup) + struct.pack("<i", outer) + write_ci(name) + struct.pack("<I", flags)
            out += write_ci(size)
            if size > 0:
                out += write_ci(offset)
        return bytes(out)

    def find_export(self, name, outer_name):
        for i, e in enumerate(self.exports):
            if self.names[e[3]] == name and e[2] > 0 and self.names[self.exports[e[2] - 1][3]] == outer_name:
                return i
        raise SystemExit("export %s.%s not found" % (outer_name, name))

    def data(self, i):
        e = self.exports[i]
        return self.d[e[6]:e[6] + e[5]]


# ------------------------------------------------------------------------------------------------ bytecode checker

def walk_script(script):
    """Walk the tokens this function uses. Returns (memory size, set of statement memory offsets)."""
    pos = 0
    mem = 0
    starts = set()

    def expr():
        nonlocal pos, mem
        tok = script[pos]
        pos += 1
        mem += 1
        if tok == 0x00:  # EX_LocalVariable <object>
            _, pos = read_ci(script, pos)
            mem += 4
        elif tok in (0x1B, 0x1C):  # EX_VirtualFunction <name> / EX_FinalFunction <object>, args, 0x16
            _, pos = read_ci(script, pos)
            mem += 4
            args()
        elif tok >= 0x70:  # a native function by index, args, 0x16
            args()
        elif tok == 0x1F:  # EX_StringConst
            end = script.index(b"\x00", pos)
            mem += end + 1 - pos
            pos = end + 1
        elif tok == 0x2C:  # EX_IntConstByte
            pos += 1
            mem += 1
        elif tok == 0x0B:  # EX_Nothing
            pass
        else:
            raise SystemExit("unexpected expression token %02x at %d" % (tok, pos - 1))

    def args():
        nonlocal pos, mem
        while script[pos] != 0x16:
            expr()
        pos += 1
        mem += 1

    while pos < len(script):
        starts.add(mem)
        tok = script[pos]
        if tok == 0x05:  # EX_Switch <size byte> <expr>
            pos += 2
            mem += 2
            expr()
        elif tok == 0x0A:  # EX_Case <offset word> [<expr>]
            offset = struct.unpack_from("<H", script, pos + 1)[0]
            pos += 3
            mem += 3
            if offset != 0xFFFF:
                expr()
        elif tok == 0x06:  # EX_Jump <offset>
            pos += 3
            mem += 3
        elif tok == 0x07:  # EX_JumpIfNot <offset> <expr>
            pos += 3
            mem += 3
            expr()
        elif tok == 0x04:  # EX_Return <expr>
            pos += 1
            mem += 1
            expr()
        else:
            expr()
    return mem, starts


def check_function(body, expect_size):
    script_size = struct.unpack_from("<i", body, SCRIPT_SIZE_AT)[0]
    script = body[SCRIPT_START:len(body) - 7]
    mem, starts = walk_script(script)
    if mem != script_size or mem != expect_size:
        raise SystemExit("script memory size %d, header says %d, expected %d" % (mem, script_size, expect_size))
    # Every jump and case offset must land on a statement.
    for off in (struct.unpack_from("<H", body, SCRIPT_START + k)[0] for k in (6, 23, 29)):
        if off != 0xFFFF and off not in starts:
            raise SystemExit("jump offset %d is not a statement start" % off)


# ------------------------------------------------------------------------------------------------------------ patch

def build(stock_raw):
    if hashlib.sha256(stock_raw).hexdigest() != STOCK_SHA256:
        raise SystemExit("input is not the stock interface.u (SHA-256 mismatch); refusing to patch")
    d = l2ver111.decrypt(stock_raw)
    pkg = Package(d)

    # The layout this tool relies on: object data, then imports, then exports, then end of file.
    if pkg.import_table() != d[pkg.import_offset:pkg.imports_end]:
        raise SystemExit("import table does not re-serialise identically")
    if pkg.export_table() != d[pkg.export_offset:pkg.exports_end]:
        raise SystemExit("export table does not re-serialise identically")
    data_end = max(e[6] + e[5] for e in pkg.exports if e[5] > 0)
    if not (data_end == pkg.import_offset and pkg.imports_end == pkg.export_offset and pkg.exports_end == len(d)):
        raise SystemExit("unexpected package layout")

    i = pkg.find_export("OnClickButton", "QuestTreeWnd")
    old = pkg.data(i)
    if old != STOCK_FUNCTION:
        raise SystemExit("QuestTreeWnd.OnClickButton is not the expected bytecode")
    check_function(old, 60)
    strid = pkg.exports[3049]
    if pkg.names[strid[3]] != "strID" or strid[2] != i + 1 or pkg.imports[284][3] != pkg.names.index("RequestBypassToServer"):
        raise SystemExit("strID or RequestBypassToServer reference is not where expected")

    new_script_size = 60 + INSERT_MEMORY
    new_return = 58 + INSERT_MEMORY
    body = bytearray(old[:RETURN_AT] + INSERT + old[RETURN_AT:])
    struct.pack_into("<i", body, SCRIPT_SIZE_AT, new_script_size)
    struct.pack_into("<H", body, JUMP_TARGET_AT, new_return)  # non-root clicks still skip to `return`
    body = bytes(body)
    check_function(body, new_script_size)

    # The new body goes where the import table was; the tables move up behind it.
    new_offset = pkg.import_offset
    pkg.exports[i][5] = len(body)
    pkg.exports[i][6] = new_offset
    imports = pkg.import_table()
    import_offset = new_offset + len(body)
    export_offset = import_offset + len(imports)

    header = bytearray(d[:pkg.name_offset])
    struct.pack_into("<i", header, 24, export_offset)
    struct.pack_into("<i", header, 32, import_offset)
    out = bytes(header) + d[pkg.name_offset:new_offset] + body + imports + pkg.export_table()

    # Verify: re-read, every other object unchanged, the patched function where we put it.
    new = Package(out)
    if new.names != pkg.names or len(new.exports) != len(pkg.exports):
        raise SystemExit("verification failed: tables differ")
    old_pkg = Package(d)
    for k in range(len(new.exports)):
        if k == i:
            if new.data(k) != body:
                raise SystemExit("verification failed: patched function not found")
        elif new.data(k) != old_pkg.data(k) or new.exports[k][:5] != old_pkg.exports[k][:5]:
            raise SystemExit("verification failed: export %d changed" % (k + 1))
    return l2ver111.encrypt(out, l2ver111.footer_of(stock_raw)), len(old), len(body)


def main(argv):
    if "--restore" in argv:
        shutil.copy2(BACKUP, CLIENT)
        print("restored stock interface.u from %s" % BACKUP)
        return 0

    if not os.path.exists(BACKUP):
        os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
        shutil.copy2(CLIENT, BACKUP)
        print("backed up stock interface.u to %s" % BACKUP)
    patched, old_size, new_size = build(open(BACKUP, "rb").read())
    print("OnClickButton %d -> %d bytes; verification OK" % (old_size, new_size))
    if "--check" in argv:
        print("--check: nothing written")
        return 0
    open(CLIENT, "wb").write(patched)
    print("wrote patched %s (sha256 %s)" % (CLIENT, hashlib.sha256(patched).hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
