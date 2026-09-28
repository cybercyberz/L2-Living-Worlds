"""Assemble a bytecode listing (see disasm.py) back into a token tree and bytes.

Labels are resolved from the `Lxxxx:` prefixes, which are recomputed from the tokens themselves: the listing's own
numbers are only checked, not trusted. Code written by hand can use any label names (`@loop`, `@done`) and leave the
line prefixes off; `assemble` works out every memory offset.
"""
import json
import re
import struct

from .disasm import LONG
from .upk import bytecode

_TOKEN = re.compile(r"""
    \s*(?:
      (?P<str>w?"(?:[^"\\]|\\.)*")
    | (?P<f32bits>f32bits\(0x[0-9A-Fa-f]{8}\))
    | (?P<float>-?\d+\.\d*(?:[eE][-+]?\d+)?f|-?\d+(?:[eE][-+]?\d+)f|-?(?:inf|nan)f)
    | (?P<int>-?\d+)
    | (?P<ref>&[^,()\s]+)
    | (?P<name>\#"(?:[^"\\]|\\.)*"|\#[^,()=\s"]+)
    | (?P<label>@[A-Za-z0-9_]+)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<punct>[(),=])
    )""", re.VERBOSE)


class AsmError(Exception):
    pass


def _lex(text):
    pos = 0
    out = []
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise AsmError("cannot read %r" % text[pos:pos + 30])
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def _strip_comment(line):
    """Drop a `;` comment, but not a `;` inside a string."""
    in_str = False
    esc = False
    for i, c in enumerate(line):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == ";":
            return line[:i]
    return line


class _Parser:
    def __init__(self, toks, ctx):
        self.t = toks
        self.i = 0
        self.ctx = ctx

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, kind=None, value=None):
        tok = self.peek()
        if tok[0] is None or (kind and tok[0] != kind) or (value and tok[1] != value):
            raise AsmError("expected %s %s, got %r" % (kind or "", value or "", tok[1]))
        self.i += 1
        return tok

    def args(self):
        out = []
        if self.peek() == ("punct", "("):
            self.take()
            if self.peek() != ("punct", ")"):
                while True:
                    out.append(self.atom())
                    if self.peek() == ("punct", ","):
                        self.take()
                        continue
                    break
            self.take("punct", ")")
        return out

    def atom(self):
        kind, v = self.peek()
        if kind == "ident":
            if v == "default":
                self.take()
                return ("default",)
            return ("node", self.node())
        self.take()
        if kind == "str":
            if v.startswith("w"):
                return ("wstr", json.loads(v[1:]))
            return ("cstr", json.loads(v))
        if kind == "int":
            if self.peek() == ("punct", "="):
                raise AsmError("unexpected =")
            return ("int", int(v))
        if kind == "float":
            return ("f32", float(v[:-1]))
        if kind == "f32bits":
            bits = int(v[len("f32bits("):-1], 16)
            return ("f32", struct.unpack("<f", struct.pack("<I", bits))[0])
        if kind == "ref":
            return ("obj", self.ctx.resolve_ref(v[1:]))
        if kind == "name":
            name = self.ctx.name_index(json.loads(v[1:]) if v.startswith('#"') else v[1:])
            if self.peek() == ("punct", "="):
                self.take()
                return ("labelentry", name, int(self.take("int")[1]))
            return ("name", name)
        if kind == "label":
            return ("label", v)
        raise AsmError("unexpected %r" % v)

    def node(self):
        _, ident = self.take("ident")
        op = LONG.get(ident, ident)
        if re.fullmatch(r"N\d+", op):
            n = bytecode.Node("Native", None, 0, 0)
            n.native = int(op[1:])
            n.args = [("params", [self._as_node(a) for a in self.args()])]
            return n
        code = bytecode.BY_NAME.get(op)
        if code is None:
            raise AsmError("unknown token %s" % ident)
        n = bytecode.Node(op, code, 0, 0)
        spec = bytecode.TOKENS[code][1]
        args = self.args()
        n.args = self._bind(op, spec, args)
        return n

    def _as_node(self, a):
        if a[0] == "node":
            return a[1]
        if a[0] == "cstr":  # a bare string is a StringConst
            n = bytecode.Node("StringConst", 0x1F, 0, 0)
            n.args = [("cstr", a[1])]
            return n
        if a[0] == "wstr":
            n = bytecode.Node("UnicodeStringConst", 0x34, 0, 0)
            n.args = [("wstr", a[1])]
            return n
        raise AsmError("expected an expression, got %r" % (a,))

    def _bind(self, op, spec, args):
        out = []
        k = 0
        for kind in spec:
            if kind == "params":
                out.append(("params", [self._as_node(a) for a in args[k:]]))
                k = len(args)
                continue
            if kind == "labels":
                out.append(("labels", [(a[1], a[2]) for a in args[k:]]))
                k = len(args)
                continue
            if k >= len(args):
                raise AsmError("%s: missing operand %s" % (op, kind))
            a = args[k]
            k += 1
            if kind == "case":
                if a[0] == "default":
                    out.append(("case", 0xFFFF, None))
                else:
                    target = a[1] if a[0] == "int" else a
                    out.append(("case", target, self._as_node(args[k])))
                    k += 1
            elif kind in ("obj", "name"):
                if a[0] != kind:
                    raise AsmError("%s: expected %s, got %r" % (op, kind, a))
                out.append(a)
            elif kind in ("u8", "u16", "i32"):
                if a[0] == "label":
                    out.append((kind, a))  # resolved later
                elif a[0] == "int":
                    out.append((kind, a[1]))
                else:
                    raise AsmError("%s: expected a number, got %r" % (op, a))
            elif kind == "f32":
                out.append(("f32", float(a[1]) if a[0] in ("f32", "int") else _bad(op, a)))
            elif kind in ("cstr", "wstr"):
                if a[0] != kind:
                    raise AsmError("%s: expected a string" % op)
                out.append(a)
            elif kind == "expr":
                out.append(("expr", self._as_node(a)))
        if k != len(args):
            raise AsmError("%s: too many operands" % op)
        return out


def _bad(op, a):
    raise AsmError("%s: bad operand %r" % (op, a))


class Context:
    """What the assembler needs from a package: names and references."""

    def __init__(self, pkg, refs, add_names=False):
        self.pkg = pkg
        self.refs = refs
        self.add_names = add_names

    def resolve_ref(self, text):
        try:
            return self.refs.resolve(text)
        except KeyError:
            raise AsmError("unknown object %s" % text)

    def name_index(self, name):
        try:
            return self.pkg.names.index(name)
        except ValueError:
            if self.add_names:
                return self.pkg.name_index(name, add=True)
            raise AsmError("unknown name %s" % name)


def _mem_layout(stmts):
    """Memory offset of every statement, from the tokens' own sizes."""
    offsets = []
    m = 0
    for s in stmts:
        offsets.append(m)
        _, size = bytecode.encode([_strip_labels(s)])
        m += size
    return offsets, m


def _strip_labels(node):
    """A copy-free view: label operands count as 2 bytes whatever their value, so a placeholder is enough."""
    return _map_labels(node, lambda a: 0)


def _map_labels(node, fn):
    n = bytecode.Node(node.op, node.code, 0, 0)
    n.native = node.native
    for a in node.args:
        kind = a[0]
        if kind == "u16" and isinstance(a[1], tuple):
            n.args.append(("u16", fn(a[1])))
        elif kind == "case" and isinstance(a[1], tuple):
            n.args.append(("case", fn(a[1]), _map_labels(a[2], fn)))
        elif kind == "case":
            n.args.append(("case", a[1], _map_labels(a[2], fn) if a[2] is not None else None))
        elif kind == "expr":
            n.args.append(("expr", _map_labels(a[1], fn)))
        elif kind == "params":
            n.args.append(("params", [_map_labels(x, fn) for x in a[1]]))
        else:
            n.args.append(a)
    return n


def assemble(text, pkg, refs, add_names=False):
    """Assemble a listing. Returns (statements, bytes, memory size)."""
    ctx = Context(pkg, refs, add_names)
    stmts = []
    declared = []  # (label names defined on this line, listing's own offset or None)
    pending = []
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        names = []
        while True:
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*):\s*", line)
            if not m or line[m.end():m.end() + 1] == ":":
                break
            names.append(m.group(1))
            line = line[m.end():]
        if line == ".end":
            pending.extend(names)
            continue
        if not line:
            pending.extend(names)
            continue
        p = _Parser(_lex(line), ctx)
        node = p.node()
        if p.i != len(p.t):
            raise AsmError("trailing text: %r" % raw)
        stmts.append(node)
        declared.append(pending + names)
        pending = []

    offsets, size = _mem_layout(stmts)
    labels = {}
    for names, off in zip(declared, offsets):
        for nm in names:
            labels["@" + nm] = off
    for nm in pending:  # labels after the last statement mark the end of the script
        labels["@" + nm] = size
    # Listing prefixes like L003A must agree with the computed offsets.
    for nm, off in labels.items():
        m = re.fullmatch(r"@L([0-9A-F]{4})", nm)
        if m and int(m.group(1), 16) != off:
            raise AsmError("label %s is at offset %d" % (nm, off))

    def resolve(label):
        try:
            return labels[label[1]]
        except KeyError:
            raise AsmError("undefined label %s" % label[1])

    final = [_map_labels(s, resolve) for s in stmts]
    data, mem = bytecode.encode(final)
    return final, data, mem
