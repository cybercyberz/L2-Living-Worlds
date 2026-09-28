"""UnrealScript bytecode (UE2, package version 123) as a token tree.

`decode(data, pos, memory_size)` reads one function's script and returns a list of statement nodes. Every node records
its serial and in-memory offsets. The in-memory size is what `ScriptSize` counts and what jump offsets refer to: object
references and names are compact indices on disk but 4 bytes in memory.

The table is checked against every function in every client package: the decoded memory size must equal
`ScriptSize` exactly, and every jump must land on a token boundary.
"""
import struct

from .compact import read_ci, write_ci

# Operand kinds: (serial reader, memory size)
#   obj   object reference     ci / 4
#   name  name index           ci / 4
#   u8 / u16 / i32 / f32       fixed
#   cstr  null-terminated latin1, wstr null-terminated UTF-16
#   expr  one expression, params  expressions up to EX_EndFunctionParms (0x16)

TOKENS = {
    0x00: ("LocalVariable", ["obj"]),
    0x01: ("InstanceVariable", ["obj"]),
    0x02: ("DefaultVariable", ["obj"]),
    0x04: ("Return", ["expr"]),
    0x05: ("Switch", ["u8", "expr"]),
    0x06: ("Jump", ["u16"]),
    0x07: ("JumpIfNot", ["u16", "expr"]),
    0x08: ("Stop", []),
    0x09: ("Assert", ["u16", "expr"]),
    0x0A: ("Case", ["case"]),
    0x0B: ("Nothing", []),
    0x0C: ("LabelTable", ["labels"]),
    0x0D: ("GotoLabel", ["expr"]),
    0x0E: ("EatString", ["expr"]),
    0x0F: ("Let", ["expr", "expr"]),
    0x10: ("DynArrayElement", ["expr", "expr"]),
    0x11: ("New", ["expr", "expr", "expr", "expr"]),
    0x12: ("ClassContext", ["expr", "u16", "u8", "expr"]),
    0x13: ("MetaCast", ["obj", "expr"]),
    0x14: ("LetBool", ["expr", "expr"]),
    0x16: ("EndFunctionParms", []),
    0x17: ("Self", []),
    0x18: ("Skip", ["u16", "expr"]),
    0x19: ("Context", ["expr", "u16", "u8", "expr"]),
    0x1A: ("ArrayElement", ["expr", "expr"]),
    0x1B: ("VirtualFunction", ["name", "params"]),
    0x1C: ("FinalFunction", ["obj", "params"]),
    0x1D: ("IntConst", ["i32"]),
    0x1E: ("FloatConst", ["f32"]),
    0x1F: ("StringConst", ["cstr"]),
    0x20: ("ObjectConst", ["obj"]),
    0x21: ("NameConst", ["name"]),
    0x22: ("RotationConst", ["i32", "i32", "i32"]),
    0x23: ("VectorConst", ["f32", "f32", "f32"]),
    0x24: ("ByteConst", ["u8"]),
    0x25: ("IntZero", []),
    0x26: ("IntOne", []),
    0x27: ("True", []),
    0x28: ("False", []),
    0x29: ("NativeParm", ["obj"]),
    0x2A: ("NoObject", []),
    0x2C: ("IntConstByte", ["u8"]),
    0x2D: ("BoolVariable", ["expr"]),
    0x2E: ("DynamicCast", ["obj", "expr"]),
    0x2F: ("Iterator", ["expr", "u16"]),
    0x30: ("IteratorPop", []),
    0x31: ("IteratorNext", []),
    0x32: ("StructCmpEq", ["obj", "expr", "expr"]),
    0x33: ("StructCmpNe", ["obj", "expr", "expr"]),
    0x34: ("UnicodeStringConst", ["wstr"]),
    0x36: ("StructMember", ["obj", "expr"]),
    0x37: ("DynArrayLength", ["expr"]),
    0x38: ("GlobalFunction", ["name", "params"]),
    0x39: ("PrimitiveCast", ["u8", "expr"]),
    0x40: ("DynArrayInsert", ["expr", "expr", "expr"]),
    0x41: ("DynArrayRemove", ["expr", "expr", "expr"]),
    0x42: ("DelegateFunction", ["obj", "name", "params"]),
    0x43: ("DelegateProperty", ["name"]),
    0x44: ("LetDelegate", ["expr", "expr"]),
}
BY_NAME = {v[0]: k for k, v in TOKENS.items()}

FIXED = {"u8": (1, "<B"), "u16": (2, "<H"), "i32": (4, "<i"), "f32": (4, "<f")}
JUMP_TOKENS = {"Jump", "JumpIfNot", "Case", "Skip", "Iterator", "Assert"}  # u16 operands that are code offsets
CODE_OFFSET_OPERAND = {"Jump": 0, "JumpIfNot": 0, "Iterator": 1}


class DecodeError(Exception):
    pass


class Node:
    __slots__ = ("op", "code", "native", "args", "ser", "mem", "ser_end", "mem_end")

    def __init__(self, op, code, ser, mem):
        self.op = op
        self.code = code
        self.native = None
        self.args = []
        self.ser = ser
        self.mem = mem
        self.ser_end = None
        self.mem_end = None

    def __repr__(self):
        return "Node(%s @%d)" % (self.op, self.mem)


class _Decoder:
    def __init__(self, data, pos):
        self.d = data
        self.p = pos
        self.start = pos
        self.m = 0

    def token(self):
        d = self.d
        if self.p >= len(d):
            raise DecodeError("ran off the end of the object")
        code = d[self.p]
        node = Node(None, code, self.p - self.start, self.m)
        self.p += 1
        self.m += 1
        if code >= 0x60:
            node.op = "Native"
            if code < 0x70:
                node.native = ((code - 0x60) << 8) | d[self.p]
                self.p += 1
                self.m += 1
            else:
                node.native = code
            node.args = [("params", self.params())]
        else:
            spec = TOKENS.get(code)
            if spec is None:
                raise DecodeError("unknown token 0x%02X at serial %d" % (code, node.ser))
            node.op = spec[0]
            for kind in spec[1]:
                node.args.append(self.operand(kind, node))
        node.ser_end = self.p - self.start
        node.mem_end = self.m
        return node

    def params(self):
        out = []
        while True:
            if self.d[self.p] == 0x16:
                self.p += 1
                self.m += 1
                return out
            out.append(self.token())

    def operand(self, kind, node):
        d = self.d
        if kind in ("obj", "name"):
            v, self.p = read_ci(d, self.p)
            self.m += 4
            return (kind, v)
        if kind in FIXED:
            size, fmt = FIXED[kind]
            v = struct.unpack_from(fmt, d, self.p)[0]
            self.p += size
            self.m += size
            return (kind, v)
        if kind == "cstr":
            end = d.index(b"\0", self.p)
            s = d[self.p:end].decode("latin1")
            self.m += end + 1 - self.p
            self.p = end + 1
            return ("cstr", s)
        if kind == "wstr":
            q = self.p
            while d[q:q + 2] != b"\0\0":
                q += 2
            s = d[self.p:q].decode("utf-16-le")
            self.m += q + 2 - self.p
            self.p = q + 2
            return ("wstr", s)
        if kind == "expr":
            return ("expr", self.token())
        if kind == "params":
            return ("params", self.params())
        if kind == "case":
            v = struct.unpack_from("<H", d, self.p)[0]
            self.p += 2
            self.m += 2
            if v == 0xFFFF:
                return ("case", v, None)
            return ("case", v, self.token())
        if kind == "labels":
            labels = []
            while True:
                name, self.p = read_ci(d, self.p)
                offset = struct.unpack_from("<I", d, self.p)[0]
                self.p += 4
                self.m += 8
                labels.append((name, offset))
                if name == self.none_index:
                    return ("labels", labels)
        raise DecodeError("unknown operand kind %s" % kind)

    none_index = 0


def decode(data, pos, memory_size, none_index=0):
    """Decode statements from `pos` until `memory_size` bytes of memory are covered.

    Returns (statements, serial end position)."""
    dec = _Decoder(data, pos)
    dec.none_index = none_index
    stmts = []
    while dec.m < memory_size:
        stmts.append(dec.token())
    if dec.m != memory_size:
        raise DecodeError("script memory size %d overshoots ScriptSize %d" % (dec.m, memory_size))
    return stmts, dec.p


def walk(node):
    """Every node in a tree, depth first."""
    yield node
    for a in node.args:
        if a[0] == "expr":
            yield from walk(a[1])
        elif a[0] == "params":
            for n in a[1]:
                yield from walk(n)
        elif a[0] == "case" and a[2] is not None:
            yield from walk(a[2])


def code_offsets(stmts):
    """(node, offset) for every operand that is a code offset."""
    out = []
    for s in stmts:
        for n in walk(s):
            if n.op in ("Jump", "JumpIfNot"):
                out.append((n, n.args[0][1]))
            elif n.op == "Iterator":
                out.append((n, n.args[1][1]))
            elif n.op == "Case" and n.args[0][1] != 0xFFFF:
                out.append((n, n.args[0][1]))
    return out


# ------------------------------------------------------------------------------------------------------- encoding

def encode(stmts):
    """Serialise a token tree back to bytes. Returns (bytes, memory size)."""
    out = bytearray()
    mem = [0]

    def tok(n):
        if n.op == "Native":
            if n.native < 0x70:
                raise ValueError("native index %d is below 0x70 and has no direct token" % n.native)
            if n.native < 0x100:
                out.append(n.native)
                mem[0] += 1
            else:
                out.append(0x60 + (n.native >> 8))
                out.append(n.native & 0xFF)
                mem[0] += 2
            for a in n.args:
                operand(a)
            return
        out.append(BY_NAME[n.op])
        mem[0] += 1
        for a in n.args:
            operand(a)

    def operand(a):
        kind = a[0]
        if kind in ("obj", "name"):
            out.extend(write_ci(a[1]))
            mem[0] += 4
        elif kind in FIXED:
            size, fmt = FIXED[kind]
            out.extend(struct.pack(fmt, a[1]))
            mem[0] += size
        elif kind == "cstr":
            raw = a[1].encode("latin1") + b"\0"
            out.extend(raw)
            mem[0] += len(raw)
        elif kind == "wstr":
            raw = a[1].encode("utf-16-le") + b"\0\0"
            out.extend(raw)
            mem[0] += len(raw)
        elif kind == "expr":
            tok(a[1])
        elif kind == "params":
            for n in a[1]:
                tok(n)
            out.append(0x16)
            mem[0] += 1
        elif kind == "case":
            out.extend(struct.pack("<H", a[1]))
            mem[0] += 2
            if a[2] is not None:
                tok(a[2])
        elif kind == "labels":
            for name, offset in a[1]:
                out.extend(write_ci(name))
                out.extend(struct.pack("<I", offset))
                mem[0] += 8
        else:
            raise ValueError(kind)

    for s in stmts:
        tok(s)
    return bytes(out), mem[0]
