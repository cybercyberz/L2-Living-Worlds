"""Bytecode listing: token trees as text, and text back into token trees.

One statement per line, each prefixed by its memory offset as a label:

    L0000: Switch(0, Local(&QuestTreeWnd.OnClickButton.strID))
    L0007: Case(@L001D, "btnClose")
    L0014: Virtual(#HandleQuestCancel)
    L001A: Jump(@L0020)
    L001D: Case(default)
    L0020: JumpIfNot(@L003A, N122(N128(Local(&QuestTreeWnd.OnClickButton.strID), IntConstByte(4)), "root"))

Operands:
- `&Path`: an object reference, resolved by path. An ambiguous path gets a `~ref` suffix.
- `#Name`: a name (`#"Bip01 L Hand"` if it has spaces). `@Lxxxx`: a code offset (a label).
- `123`, `1.5f`, `"text"` (JSON escapes), `w"text"` (UTF-16).
- `NNNN(...)`: a native function by index.

`parse` (in asm.py) turns the text back into nodes; `encode` then gives the original bytes exactly.
"""
import json
import re
import struct

from .upk import bytecode

SHORT = {
    "LocalVariable": "Local", "InstanceVariable": "Instance", "DefaultVariable": "Default",
    "VirtualFunction": "Virtual", "FinalFunction": "Final", "GlobalFunction": "Global",
    "StringConst": "Str", "UnicodeStringConst": "WStr", "EndFunctionParms": "End",
}
LONG = {v: k for k, v in SHORT.items()}


class RefNames:
    """Symbolic names for object references, unique within a package."""

    def __init__(self, pkg):
        self.pkg = pkg
        self.by_path = {}
        count = {}
        refs = [-(i + 1) for i in range(len(pkg.imports))] + [i + 1 for i in range(len(pkg.exports))]
        paths = {r: pkg.path(r) for r in refs}
        for r, p in paths.items():
            count[p] = count.get(p, 0) + 1
        self.text = {}
        for r, p in paths.items():
            t = p if count[p] == 1 else "%s~%d" % (p, r)
            self.text[r] = t
            self.by_path[t] = r
        self.text[0] = "None"
        self.by_path["None"] = 0

    def ref_text(self, ref):
        return "&" + self.text[ref]

    def resolve(self, text):
        return self.by_path[text]


def name_text(name):
    """`#Name`, or `#"Name with spaces"` when it isn't a plain identifier."""
    if re.fullmatch(r"[A-Za-z0-9_]+", name):
        return "#" + name
    return "#" + json.dumps(name)


def _float(v):
    s = repr(v)
    if struct.pack("<f", float(s)) == struct.pack("<f", v):
        return s + "f"
    return "f32bits(0x%08X)" % struct.unpack("<I", struct.pack("<f", v))[0]


class Lister:
    def __init__(self, pkg, refs=None):
        self.pkg = pkg
        self.refs = refs or RefNames(pkg)

    def expr(self, n, labels):
        if n.op == "Native":
            return "N%d(%s)" % (n.native, ", ".join(self.expr(a, labels) for a in n.args[0][1]))
        name = SHORT.get(n.op, n.op)
        parts = []
        for i, a in enumerate(n.args):
            parts.append(self.operand(n, i, a, labels))
        if not parts:
            return name
        return "%s(%s)" % (name, ", ".join(p for p in parts if p is not None))

    def operand(self, n, i, a, labels):
        kind = a[0]
        if kind == "obj":
            return self.refs.ref_text(a[1])
        if kind == "name":
            return name_text(self.pkg.names[a[1]])
        if kind == "u16" and bytecode.CODE_OFFSET_OPERAND.get(n.op) == i:
            return labels.get(a[1], str(a[1]))
        if kind in ("u8", "u16", "i32"):
            return str(a[1])
        if kind == "f32":
            return _float(a[1])
        if kind == "cstr":
            return json.dumps(a[1])
        if kind == "wstr":
            return "w" + json.dumps(a[1])
        if kind == "expr":
            return self.expr(a[1], labels)
        if kind == "params":
            return ", ".join(self.expr(x, labels) for x in a[1]) if a[1] else None
        if kind == "case":
            if a[1] == 0xFFFF:
                return "default"
            return "%s, %s" % (labels.get(a[1], str(a[1])), self.expr(a[2], labels))
        if kind == "labels":
            return ", ".join("%s=%d" % (name_text(self.pkg.names[nm]), off) for nm, off in a[1])
        raise ValueError(kind)

    def listing(self, stmts, script_size):
        starts = {s.mem for s in stmts}
        for s in stmts:
            for x in bytecode.walk(s):
                starts.add(x.mem)
        targets = {off for _, off in bytecode.code_offsets(stmts)}
        labels = {off: "@L%04X" % off for off in targets if off in starts or off == script_size}
        lines = ["L%04X: %s" % (s.mem, self.expr(s, labels)) for s in stmts]
        if script_size in targets:
            lines.append("L%04X: .end" % script_size)
        return lines


def function_header(pkg, ref, o):
    e = pkg.exports[ref - 1]
    head = "%s %s" % (o["class"].lower(), pkg.path(ref))
    info = ["export %d" % ref, "ScriptSize %d" % o["script_size"]]
    if o.get("native"):
        info.append("native %d" % o["native"])
    if "function_flags" in o:
        info.append("flags 0x%08X" % o["function_flags"])
    info.append("objflags 0x%08X" % e.flags)
    return "%s    ; %s" % (head, ", ".join(info))
