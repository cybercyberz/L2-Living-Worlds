"""UnrealScript function bodies -> bytecode token trees.

The rules here copy what the original UE2 compiler emits, learned from the stock client and checked by the stage-3
gate (compile each stock function from its own source and compare the bytes). Anything the rules don't cover raises
`Unsupported` instead of guessing.
"""
import re
import struct

from ..symbols import (CPF_COERCE, CPF_OUT, CPF_SKIP, FUNC_FINAL, FUNC_ITERATOR, FUNC_NATIVE, FUNC_OPERATOR,
                       FUNC_PREOPERATOR, FUNC_STATIC, ClassSym, ConstSym, EnumSym, FuncSym, IntrinsicClass,
                       StateSym, StructSym, Type, VarSym)
from ..upk import bytecode
from .lexer import lex
from .parser import N, Parser


class CompileError(Exception):
    pass


class Unsupported(CompileError):
    pass


# PrimitiveCast codes (UE2), checked against the stock client.
CASTS = {
    ("rotator", "vector"): 0x39, ("byte", "int"): 0x3A, ("byte", "bool"): 0x3B, ("byte", "float"): 0x3C,
    ("int", "byte"): 0x3D, ("int", "bool"): 0x3E, ("int", "float"): 0x3F, ("bool", "byte"): 0x40,
    ("bool", "int"): 0x41, ("bool", "float"): 0x42, ("float", "byte"): 0x43, ("float", "int"): 0x44,
    ("float", "bool"): 0x45, ("object", "bool"): 0x47, ("name", "bool"): 0x48, ("string", "byte"): 0x49,
    ("string", "int"): 0x4A, ("string", "bool"): 0x4B, ("string", "float"): 0x4C, ("string", "vector"): 0x4D,
    ("string", "rotator"): 0x4E, ("vector", "bool"): 0x4F, ("vector", "rotator"): 0x50, ("rotator", "bool"): 0x51,
    ("byte", "string"): 0x52, ("int", "string"): 0x53, ("bool", "string"): 0x54, ("float", "string"): 0x55,
    ("object", "string"): 0x56, ("name", "string"): 0x57, ("vector", "string"): 0x58, ("rotator", "string"): 0x59,
}
# Which implicit conversions the compiler makes on its own (the rest need an explicit cast).
IMPLICIT = {("byte", "int"), ("int", "byte"), ("byte", "float"), ("int", "float"), ("float", "int"),
            ("float", "byte")}

T_INT, T_FLOAT, T_BOOL, T_BYTE, T_STRING, T_NAME = (Type(k) for k in ("int", "float", "bool", "byte", "string",
                                                                       "name"))
T_NONE_OBJ = Type("object")  # the type of None
T_VOID = Type("void")


def node(op, *args):
    n = bytecode.Node(op, bytecode.BY_NAME.get(op), 0, 0)
    n.args = list(args)
    return n


def native(index, args):
    n = bytecode.Node("Native", None, 0, 0)
    n.native = index
    n.args = [("params", list(args))]
    return n


def mem_size(n):
    return bytecode.encode([n])[1]


def type_kind(t):
    k = t.kind
    return "object" if k in ("object", "class") else k


def element_size(t, table=None):
    """Size in bytes of a value of type `t`, as the Context and Switch tokens record it."""
    k = t.kind
    if k in ("int", "float", "bool", "name", "object", "class", "delegate", "pointer"):
        return 4 if k != "delegate" else 8
    if k == "byte":
        return 1
    if k in ("string", "array"):
        return 12
    if k in ("vector", "rotator"):
        return 12
    if k == "struct":
        return struct_size(t.struct)
    raise Unsupported("size of %r" % t)


def struct_size(st):
    size = struct_size(st.super) if st.super is not None else 0
    bits = 0  # bools already packed into the current dword
    for v in _ordered_fields(st):
        if v.type.kind == "bool" and v.array_dim == 1:
            if bits == 0 or bits == 32:
                size = (size + 3) // 4 * 4 + 4
                bits = 0
            bits += 1
            continue
        bits = 0
        es = element_size(v.type)
        align = 1 if v.type.kind == "byte" else 4
        size = (size + align - 1) // align * align
        size += es * v.array_dim
    return (size + 3) // 4 * 4 if size else 0


def _ordered_fields(st):
    st.fields  # loads
    return st.order


def context_size(t, dim=1):
    if t is None or t.kind in ("void", "string", "array"):
        return 0
    return min(element_size(t) * dim, 255)


class Value:
    """A compiled expression: its token, type, and what kind of thing it is."""

    def __init__(self, tok, typ, lvalue=False, var=None, const=None):
        self.tok = tok
        self.type = typ
        self.lvalue = lvalue
        self.var = var  # VarSym for variables
        self.const = const  # Python value for literals (for constant folding)


class FunctionCompiler:
    def __init__(self, table, pkg, func, pkg_names):
        self.table = table
        self.pkg = pkg  # the package being compiled into
        self.func = func  # FuncSym of the function being compiled
        self.owner = func.owner
        self.cls = func.owner if isinstance(func.owner, ClassSym) else self._class_of_state(func.owner)
        self.state = func.owner if isinstance(func.owner, StateSym) else None
        self.pkg_names = pkg_names  # id(pkg) -> package name, for import paths
        self._imports = None
        self.code = []
        self.iterators = 0
        self.breaks = []
        self.continues = []
        prec = {}
        for (name, kind), fs in table.operators().items():
            if kind == "bin":
                prec[name.lower() if name.isalpha() else name] = fs[0].precedence
        self.prec = prec

    def _class_of_state(self, state):
        ref = state.pkg.exports[state.ref - 1].outer
        return self.table.sym(state.pkg, ref)

    # --------------------------------------------------------------------------------------------- references

    def ref(self, sym):
        if sym.pkg is self.pkg or (sym.pkg is not None and self.pkg_names.get(id(sym.pkg)) is not None
                                   and self.pkg_names.get(id(sym.pkg)) == self.pkg_names.get(id(self.pkg))):
            return sym.ref  # our package, or the stock copy of it (same export indices)
        if self._imports is None:
            self._imports = {self.pkg.path(-(i + 1)).lower(): -(i + 1) for i in range(len(self.pkg.imports))}
        path = (self.pkg_names[id(sym.pkg)] + "." + sym.path).lower()
        r = self._imports.get(path)
        if r is None:
            raise Unsupported("no import for %s" % path)
        return r

    target_pkg = None  # when patching: the editable copy of the package, which may gain new names

    def name(self, text):
        names = (self.target_pkg or self.pkg).names
        try:
            return names.index(text)
        except ValueError:
            for i, n in enumerate(names):
                if n.lower() == text.lower():
                    return i
            if self.target_pkg is not None:
                return self.target_pkg.name_index(text, add=True)
            raise Unsupported("name %s is not in the package" % text)

    # ------------------------------------------------------------------------------------------------ program

    def compile_body(self, body_tokens):
        stmts = Parser(body_tokens, self.prec).body()
        out = []
        for s in stmts:
            self.statement(s, out)
        out.append(("stmt", node("Return", ("expr", node("Nothing")))))
        return self._assemble(out)

    def _assemble(self, items):
        """items: ("stmt", Node) | ("label", key) | ("jump", op, key, ...). Resolve labels to memory offsets."""
        # First pass: offsets.
        offsets = {}
        m = 0
        for it in items:
            if it[0] == "label":
                offsets[it[1]] = m
            else:
                m += mem_size(self._materialise(it, {}, placeholder=True))
        final = []
        for it in items:
            if it[0] != "label":
                final.append(self._materialise(it, offsets))
        return final, m

    def _materialise(self, it, offsets, placeholder=False):
        if it[0] == "stmt":
            return it[1]
        kind = it[0]
        target = 0 if placeholder else offsets[it[1]]
        if kind == "jump":
            return node("Jump", ("u16", target))
        if kind == "jumpifnot":
            return node("JumpIfNot", ("u16", target), ("expr", it[2]))
        if kind == "case":
            return node("Case", ("case", target, it[2]))
        if kind == "iterator":
            return node("Iterator", ("expr", it[2]), ("u16", target))
        raise AssertionError(kind)

    def new_label(self):
        self._label = getattr(self, "_label", 0) + 1
        return self._label

    # ----------------------------------------------------------------------------------------------- statements

    def statement(self, s, out):
        k = s.kind
        if k == "Local":
            return
        if k == "Block":
            for x in s.stmts:
                self.statement(x, out)
        elif k == "ExprStmt":
            v = self.expr(s.expr)
            tok = v.tok
            if v.type.kind == "string" and s.expr.kind in ("Call", "SuperCall", "GlobalCall"):
                tok = node("EatString", ("expr", tok))
            out.append(("stmt", tok))
        elif k == "Assign":
            out.append(("stmt", self.assign(s.target, s.value)))
        elif k == "If":
            else_l = self.new_label()
            out.append(("jumpifnot", else_l, self.condition(s.cond)))
            self.statement(s.then, out)
            if s.other is not None:
                end_l = self.new_label()
                out.append(("jump", end_l))
                out.append(("label", else_l))
                self.statement(s.other, out)
                out.append(("label", end_l))
            else:
                out.append(("label", else_l))
        elif k == "Return":
            for _ in range(self.iterators):
                out.append(("stmt", node("IteratorPop")))
            if s.value is None:
                out.append(("stmt", node("Return", ("expr", node("Nothing")))))
            else:
                want = self.func.ret.type if self.func.ret else None
                v = self.expr(s.value, want)
                v = self.convert(v, want) if want is not None else v
                out.append(("stmt", node("Return", ("expr", v.tok))))
        elif k == "While":
            top = self.new_label()
            end = self.new_label()
            back = self.new_label()
            out.append(("label", top))
            out.append(("jumpifnot", end, self.condition(s.cond)))
            self._loop(s.body, out, brk=end, cont=back)
            out.append(("label", back))
            out.append(("jump", top))
            out.append(("label", end))
        elif k == "ForEach":
            it = self.expr(s.iterator)
            end = self.new_label()
            nxt = self.new_label()
            out.append(("iterator", end, it.tok))
            self.iterators += 1
            self._loop(s.body, out, brk=end, cont=nxt)
            self.iterators -= 1
            out.append(("label", nxt))
            out.append(("stmt", node("IteratorNext")))
            out.append(("label", end))
            out.append(("stmt", node("IteratorPop")))
        elif k == "Assert":
            out.append(("stmt", node("Assert", ("u16", s.line), ("expr", self.condition(s.cond)))))
        elif k == "For":
            if s.init is not None:
                self.statement(s.init, out)
            top = self.new_label()
            step = self.new_label()
            end = self.new_label()
            out.append(("label", top))
            if s.cond is not None:
                out.append(("jumpifnot", end, self.condition(s.cond)))
            self._loop(s.body, out, brk=end, cont=step)
            out.append(("label", step))
            if s.step is not None:
                self.statement(s.step, out)
            out.append(("jump", top))
            out.append(("label", end))
        elif k == "DoUntil":
            top = self.new_label()
            end = self.new_label()
            cont = self.new_label()
            out.append(("label", top))
            self._loop(s.body, out, brk=end, cont=cont)
            out.append(("label", cont))
            out.append(("jumpifnot", top, self.condition(s.cond)))
            out.append(("label", end))
        elif k == "Break":
            if not self.breaks:
                raise CompileError("break outside a loop or switch")
            out.append(("jump", self.breaks[-1]))
        elif k == "Continue":
            if not self.continues:
                raise CompileError("continue outside a loop")
            out.append(("jump", self.continues[-1]))
        elif k == "Switch":
            self.switch(s, out)
        else:
            raise Unsupported("statement %s" % k)

    def _loop(self, body, out, brk, cont):
        self.breaks.append(brk)
        self.continues.append(cont)
        self.statement(body, out)
        self.breaks.pop()
        self.continues.pop()

    def switch(self, s, out):
        v = self.expr(s.value)
        size = context_size(v.type) if v.type.kind != "bool" else 4
        out.append(("stmt", node("Switch", ("u8", size), ("expr", v.tok))))
        end = self.new_label()
        self.breaks.append(end)
        pending = None
        has_default = False
        for item in s.items:
            if item.kind in ("Case", "Default"):
                nxt = self.new_label()
                if pending is not None:
                    out.append(("label", pending))
                if item.kind == "Case":
                    cv = self.convert(self.expr(item.value, v.type), v.type)
                    out.append(("case", nxt, cv.tok))
                    pending = nxt
                else:
                    out.append(("stmt", node("Case", ("case", 0xFFFF, None))))
                    pending = None
                    has_default = True
            else:
                self.statement(item, out)
        if pending is not None:
            out.append(("label", pending))
        if not has_default:  # the UE2 compiler always ends a switch with a default case
            out.append(("stmt", node("Case", ("case", 0xFFFF, None))))
        self.breaks.pop()
        out.append(("label", end))

    def condition(self, e):
        v = self.expr(e, T_BOOL)
        return self.convert(v, T_BOOL).tok

    def assign(self, target, value):
        t = self.expr(target)
        if not t.lvalue:
            raise CompileError("line %d: can't assign to that" % target.line)
        v = self.convert(self.expr(value, t.type), t.type)
        if t.type.kind == "bool":
            return node("LetBool", ("expr", t.tok), ("expr", v.tok))
        return node("Let", ("expr", t.tok), ("expr", v.tok))

    # ---------------------------------------------------------------------------------------------- conversion

    def convert(self, v, want, explicit=False):
        if want is None or want.kind == "void":
            return v
        have = v.type
        hk, wk = type_kind(have), type_kind(want)
        if hk == wk:
            if hk == "struct" and not have.same(want):
                raise CompileError("struct type mismatch %r -> %r" % (have, want))
            return v
        if hk == "none" and wk in ("object", "delegate"):
            return v
        code = CASTS.get((hk, wk))
        if code is None or (not explicit and (hk, wk) not in IMPLICIT and not self._coerce):
            raise CompileError("can't convert %r to %r" % (have, want))
        return Value(node("PrimitiveCast", ("u8", code), ("expr", v.tok)), want)

    _coerce = False

    def float_literal_as(self, value, want):
        """A float literal compiled with a required int or byte type is truncated at compile time."""
        if want is not None and want.kind == "int":
            return self.literal_int(int(value))
        if want is not None and want.kind == "byte" and 0 <= int(value) < 255:
            return Value(node("ByteConst", ("u8", int(value))), Type("byte", enum=want.enum), const=int(value))
        return self.literal_float(value)

    def int_literal_as(self, value, want):
        """An integer literal compiled with a required type. The UE2 compiler converts it at compile time to a
        float, or to a byte when 0 <= value < 255; otherwise it stays an int and gets a cast later."""
        if want is not None and want.kind == "float":
            return self.literal_float(float(value))
        if want is not None and want.kind == "byte" and 0 <= value < 255:
            return Value(node("ByteConst", ("u8", value)), Type("byte", enum=want.enum), const=value)
        return self.literal_int(value)

    # --------------------------------------------------------------------------------------------- literals

    def literal_int(self, value):
        if value == 0:
            tok = node("IntZero")
        elif value == 1:
            tok = node("IntOne")
        elif 0 <= value <= 255:
            tok = node("IntConstByte", ("u8", value))
        else:
            tok = node("IntConst", ("i32", value))
        return Value(tok, T_INT, const=value)

    def literal_float(self, value):
        return Value(node("FloatConst", ("f32", value)), T_FLOAT, const=value)

    def literal_string(self, value):
        try:
            value.encode("latin1")
            return Value(node("StringConst", ("cstr", value)), T_STRING, const=value)
        except UnicodeEncodeError:
            return Value(node("UnicodeStringConst", ("wstr", value)), T_STRING, const=value)

    def const_value(self, c, want=None):
        text = c.value.strip()
        try:
            toks = lex(text)
        except Exception:
            raise Unsupported("const %s = %s" % (c.name, text))
        e = Parser(toks, self.prec).expr()
        return self.expr(e, want)

    # ------------------------------------------------------------------------------------------ expressions

    def expr(self, e, want=None):
        k = e.kind
        if k == "Int":
            return self.int_literal_as(e.value, want)
        if k == "Float":
            return self.float_literal_as(e.value, want)
        if k == "String":
            return self.literal_string(e.value)
        if k == "NameLit":
            return Value(node("NameConst", ("name", self.name(e.value))), T_NAME, const=e.value)
        if k == "Bool":
            return Value(node("True" if e.value else "False"), T_BOOL, const=e.value)
        if k == "None":
            return Value(node("NoObject"), Type("none"), const=None)
        if k == "Self":
            return Value(node("Self"), Type("object", cls=self.cls))
        if k == "Paren":
            # A parenthesised expression is compiled on its own against the required type, so its result is
            # converted straight away when that conversion is implicit (byte, int, float).
            v = self.expr(e.expr, want)
            if want is not None and v.type.kind != "void" and (type_kind(v.type), type_kind(want)) in IMPLICIT:
                v = self.convert(v, want)
            return v
        if k == "Ident":
            return self.ident(e, want)
        if k == "Member":
            return self.member(e)
        if k == "Index":
            return self.index(e)
        if k == "Call":
            return self.call(e, want)
        if k == "Binary":
            return self.binary(e, want)
        if k == "Unary":
            return self.unary(e, want)
        if k == "Postfix":
            return self.operator_call(e.op, "post", [e.operand], e)
        if k == "ClassLit":
            c = self.table.cls(e.name)
            if c is None:
                raise CompileError("unknown class %s" % e.name)
            return Value(node("ObjectConst", ("obj", self.ref(c))), Type("class", meta=c), const=None)
        if k == "DefaultVar":
            v = self.cls.lookup("vars", e.name)
            if v is None:
                raise CompileError("unknown default.%s" % e.name)
            return self.variable_value(node("DefaultVariable", ("obj", self.ref(v))), v)
        if k == "SuperCall":
            return self.super_call(e)
        if k == "GlobalCall":
            f = self.cls.lookup("funcs", e.name)
            if f is None:
                raise CompileError("line %d: no global function %s" % (e.line, e.name))
            call = self.emit_call(f, e.args)
            return Value(node("GlobalFunction", *call.tok.args[1:] if False else ()), call.type) if False else \
                self._as_global(f, call)
        if k == "New":
            parts = []
            for x in (e.outer, e.obj_name, e.flags):
                parts.append(("expr", self.expr(x).tok if x is not None else node("Nothing")))
            cls_v = self.expr(e.cls)
            result_cls = cls_v.type.meta if cls_v.type.kind == "class" else None
            return Value(node("New", *parts, ("expr", cls_v.tok)), Type("object", cls=result_cls))
        if k == "ObjectLit":
            return self.object_literal(e)
        if k == "MetaCast":
            c = self.table.cls(e.meta)
            if c is None:
                raise CompileError("line %d: unknown class %s" % (e.line, e.meta))
            v = self.expr(e.expr)
            return Value(node("MetaCast", ("obj", self.ref(c)), ("expr", v.tok)), Type("class", meta=c))
        raise Unsupported("expression %s" % k)

    def variable_value(self, tok, var, lvalue=True):
        if var.type.kind == "bool":
            tok = node("BoolVariable", ("expr", tok))
        return Value(tok, var.type, lvalue=lvalue, var=var)

    def local(self, name):
        low = name.lower()
        for v in self.func.params + self.func.locals:
            if v.name.lower() == low:
                return v
        return None

    def ident(self, e, want):
        v = self.local(e.name)
        if v is not None:
            return self.variable_value(node("LocalVariable", ("obj", self.ref(v))), v)
        v = self.cls.lookup("vars", e.name)
        if v is not None:
            return self.variable_value(node("InstanceVariable", ("obj", self.ref(v))), v)
        c = self.cls.lookup("consts", e.name)
        if c is not None:
            return self.const_value(c, want)
        ev = self.enum_value(e.name)
        if ev is not None:
            return ev
        raise CompileError("line %d: unknown identifier %s" % (e.line, e.name))

    def enum_value_in(self, cls, name):
        low = name.lower()
        for c in cls.chain():
            if not isinstance(c, ClassSym):
                continue
            for en in c.members("enums").values():
                for i, val in enumerate(en.values):
                    if val.lower() == low:
                        return Value(node("ByteConst", ("u8", i)), Type("byte", enum=en), const=i)
        return None

    def enum_value(self, name):
        low = name.lower()
        for c in self.cls.chain():
            if not isinstance(c, ClassSym):
                continue
            for en in c.members("enums").values():
                for i, val in enumerate(en.values):
                    if val.lower() == low:
                        return Value(node("ByteConst", ("u8", i)), Type("byte", enum=en), const=i)
        for en in self.table.all_enums():
            for i, val in enumerate(en.values):
                if val.lower() == low:
                    return Value(node("ByteConst", ("u8", i)), Type("byte", enum=en), const=i)
        return None

    def find_enum(self, name):
        low = name.lower()
        for c in self.cls.chain():
            if isinstance(c, ClassSym):
                en = c.members("enums").get(low)
                if en is not None:
                    return en
        for en in self.table.all_enums():
            if en.name.lower() == low:
                return en
        return None

    def resolves_as_value(self, name):
        return (self.local(name) is not None or self.cls.lookup("vars", name) is not None
                or self.cls.lookup("consts", name) is not None)

    def member(self, e):
        # EnumName.Value
        if e.target.kind == "Ident" and not self.resolves_as_value(e.target.name):
            en = self.find_enum(e.target.name)
            if en is not None:
                for i, val in enumerate(en.values):
                    if val.lower() == e.name.lower():
                        return Value(node("ByteConst", ("u8", i)), Type("byte", enum=en), const=i)
                raise CompileError("line %d: %s has no value %s" % (e.line, en.name, e.name))
        # Dynamic array length
        if e.name.lower() == "length":
            base = self.expr(e.target)
            if base.type.kind == "array":
                return Value(node("DynArrayLength", ("expr", base.tok)), T_INT, lvalue=True)
        base = self.expr(e.target)
        t = base.type
        if t.kind == "classdefault":  # class'X'.default.Var -> ClassContext(class, skip, size, Default(Var))
            v = t.meta.lookup("vars", e.name)
            if v is None:
                raise CompileError("line %d: no default %s in %s" % (e.line, e.name, t.meta.name))
            inner = self.variable_value(node("DefaultVariable", ("obj", self.ref(v))), v)
            return Value(self.context(base.tok, inner.tok, v.type, v.array_dim, class_context=True), v.type,
                         lvalue=True, var=v)
        if t.kind in ("struct", "vector", "rotator"):
            f = t.struct.field(e.name)
            if f is None:
                raise CompileError("line %d: %r has no field %s" % (e.line, t, e.name))
            tok = node("StructMember", ("obj", self.ref(f)), ("expr", base.tok))
            return self.variable_value(tok, f, lvalue=base.lvalue)
        if t.kind in ("object", "class"):
            cls = t.cls if t.kind == "object" else t.meta
            if t.kind == "class" and e.name.lower() == "default":
                return Value(base.tok, Type("classdefault", meta=t.meta), const=None)
            v = cls.lookup("vars", e.name) if cls is not None else None
            if v is None:
                c = cls.lookup("consts", e.name) if cls is not None else None
                if c is not None:  # obj.CONST keeps the object: Context(obj, skip, size, const)
                    cv = self.const_value(c)
                    return Value(self.context(base.tok, cv.tok, cv.type), cv.type, const=None)
                ev = self.enum_value_in(cls, e.name) if isinstance(cls, ClassSym) else None
                if ev is not None:
                    return Value(self.context(base.tok, ev.tok, ev.type), ev.type, const=None)
                raise CompileError("line %d: no variable %s in %r" % (e.line, e.name, t))
            inner = self.variable_value(node("InstanceVariable", ("obj", self.ref(v))), v)
            return Value(self.context(base.tok, inner.tok, v.type, v.array_dim, class_context=False), v.type,
                         lvalue=True, var=v)
        raise CompileError("line %d: can't take .%s of %r" % (e.line, e.name, t))

    def context(self, obj_tok, member_tok, typ, dim=1, class_context=False):
        op = "ClassContext" if class_context else "Context"
        size = context_size(typ, dim) if typ is not None and typ.kind != "bool" else (4 if typ is not None else 0)
        return node(op, ("expr", obj_tok), ("u16", mem_size(member_tok)), ("u8", size), ("expr", member_tok))

    def index(self, e):
        base = self.expr(e.target)
        idx = self.convert(self.expr(e.index, T_INT), T_INT)
        if base.type.kind == "array":
            inner = base.type.inner
            tok = node("DynArrayElement", ("expr", idx.tok), ("expr", base.tok))
            if inner.kind == "bool":
                tok = node("BoolVariable", ("expr", tok))
            return Value(tok, inner, lvalue=True)
        if base.var is not None and base.var.array_dim > 1:
            tok = base.tok
            if tok.op == "BoolVariable":
                raise Unsupported("static bool array")
            return Value(node("ArrayElement", ("expr", idx.tok), ("expr", tok)), base.type, lvalue=True, var=base.var)
        raise CompileError("line %d: can't index %r" % (e.line, base.type))

    # ------------------------------------------------------------------------------------------- operators

    def binary(self, e, want):
        return self.operator_call(e.op, "bin", [e.left, e.right], e, want)

    def unary(self, e, want):
        if e.op == "-" and e.operand.kind in ("Int", "Float"):
            if e.operand.kind == "Int":
                return self.int_literal_as(-e.operand.value, want)
            return self.float_literal_as(-e.operand.value, want)
        return self.operator_call(e.op, "pre", [e.operand], e, want)

    def operator_call(self, op, kind, operands, e, want=None):
        cands = self.table.operator(op, kind)
        if not cands:
            raise CompileError("line %d: no operator %s" % (e.line, op))
        # The UE2 compiler passes the required type to the first operand only.
        vals = [self.expr(x, want if i == 0 else None) for i, x in enumerate(operands)]
        best = self.pick_overload(cands, vals)
        if best is None:
            raise CompileError("line %d: no %s %s for %s" % (e.line, kind, op, [v.type for v in vals]))
        return self.emit_call(best, vals, operands_are_values=True)

    def pick_overload(self, cands, vals):
        best = None
        best_cost = None
        for f in cands:
            if len(f.params) != len(vals):
                continue
            cost = 0
            ok = True
            for p, v in zip(f.params, vals):
                c = self.conv_cost(v, p)
                if c is None:
                    ok = False
                    break
                cost += c
            if ok and (best_cost is None or cost < best_cost):
                best, best_cost = f, cost
        return best

    def conv_cost(self, v, p):
        have, want = v.type, p.type
        hk, wk = type_kind(have), type_kind(want)
        if p.out and hk != wk:
            return None
        if hk == wk:
            if hk == "struct" and not have.same(want):
                return None
            if hk == "object" and want.cls is not None and have.cls is not None and have.kind == want.kind:
                if isinstance(have.cls, ClassSym) and not have.cls.is_a(want.cls):
                    return None
            return 0
        if hk == "none" and wk == "object":
            return 0
        if (hk, wk) == ("byte", "int"):
            return 1
        if (hk, wk) == ("int", "byte"):
            return 2 if v.const is not None else 3
        if (hk, wk) in (("byte", "float"), ("int", "float")):
            return 3
        if (hk, wk) in (("float", "int"), ("float", "byte")):
            return 4
        if p.coerce and (hk, wk) in CASTS:
            return 10
        return None

    # ----------------------------------------------------------------------------------------------- calls

    def find_function(self, name, cls=None):
        if cls is None:
            if self.state is not None:
                f = self.state.funcs.get(name.lower())
                if f is not None:
                    return f
            cls = self.cls
        return cls.lookup("funcs", name)

    def call(self, e, want):
        name = e.name
        low = name.lower()
        target = e.target
        # Dynamic arrays
        if target is not None and low in ("remove", "insert"):
            base = self.expr(target)
            if base.type.kind == "array":
                args = [self.convert(self.expr(a, T_INT), T_INT).tok for a in e.args]
                op = "DynArrayRemove" if low == "remove" else "DynArrayInsert"
                return Value(node(op, ("expr", base.tok), ("expr", args[0]), ("expr", args[1])), T_VOID)
        if target is None and not getattr(e, "static", False):
            # Casts: int(x), string(x), ClassName(x)
            prim = {"int": T_INT, "float": T_FLOAT, "bool": T_BOOL, "byte": T_BYTE, "string": T_STRING,
                    "name": T_NAME}
            if low in prim and len(e.args) == 1:
                v = self.expr(e.args[0])
                return self.convert(v, prim[low], explicit=True)
            if low in ("vect", "rot"):
                return self.vect_rot(e)
            if low == "arraycount" and len(e.args) == 1:
                v = self.expr(e.args[0])
                if v.var is None or v.var.array_dim <= 1:
                    raise CompileError("line %d: ArrayCount of a non-array" % e.line)
                return self.literal_int(v.var.array_dim)
            f = self.find_function(name)
            if f is None and len(e.args) == 1:
                en = self.find_enum(name)
                if en is not None:
                    return self.convert(self.expr(e.args[0]), Type("byte", enum=en), explicit=True)
            if f is None:
                c = self.table.cls(name)
                if c is not None and len(e.args) == 1:
                    v = self.expr(e.args[0])
                    return Value(node("DynamicCast", ("obj", self.ref(c)), ("expr", v.tok)), Type("object", cls=c))
                raise CompileError("line %d: unknown function %s" % (e.line, name))
            return self.emit_call(f, e.args)
        if target is None:  # static.F()
            f = self.find_function(name)
            return self.emit_call(f, e.args)
        # target.F() or class'X'.static.F()
        static = False
        if target.kind == "Member" and target.name.lower() == "static":
            static = True
            target = target.target
        base = self.expr(target)
        t = base.type
        if t.kind == "class":
            cls = t.meta
            f = cls.lookup("funcs", name) if cls is not None else None
            if f is None:
                raise CompileError("line %d: unknown static function %s" % (e.line, name))
            call = self.emit_call(f, e.args)
            size = context_size(f.ret.type) if f.ret is not None and f.ret.type.kind != "bool" else (
                4 if f.ret is not None else 0)
            tok = node("ClassContext", ("expr", base.tok), ("u16", mem_size(call.tok)), ("u8", size),
                       ("expr", call.tok))
            return Value(tok, call.type)
        if t.kind == "object":
            cls = t.cls
            f = cls.lookup("funcs", name) if isinstance(cls, ClassSym) else None
            if f is None:
                raise CompileError("line %d: unknown function %s in %r" % (e.line, name, t))
            call = self.emit_call(f, e.args)
            size = context_size(f.ret.type) if f.ret is not None and f.ret.type.kind != "bool" else (
                4 if f.ret is not None else 0)
            tok = node("Context", ("expr", base.tok), ("u16", mem_size(call.tok)), ("u8", size), ("expr", call.tok))
            return Value(tok, call.type)
        raise CompileError("line %d: can't call %s on %r" % (e.line, name, t))

    def _as_global(self, f, call):
        """global.F(): the same arguments as a virtual call, under EX_GlobalFunction."""
        args = call.tok.args[-1]
        return Value(node("GlobalFunction", ("name", self.name(f.name)), args), call.type)

    def object_literal(self, e):
        """Texture'Package.Name' -> ObjectConst of an import (or export) with that path."""
        path = e.value.lower()
        for i in range(len(self.pkg.imports)):
            p = self.pkg.path(-(i + 1)).lower()
            if (p == path or p.endswith("." + path)) and self.pkg.class_name(-(i + 1)).lower() == e.cls.lower():
                return Value(node("ObjectConst", ("obj", -(i + 1))), Type("object", cls=self.table.cls(e.cls)))
        try:
            ref = self.pkg.find(e.value)
            return Value(node("ObjectConst", ("obj", ref)), Type("object", cls=self.table.cls(e.cls)))
        except KeyError:
            raise Unsupported("object literal %s'%s' has no import" % (e.cls, e.value))

    def super_call(self, e):
        if e.cls is not None:
            start = self.table.cls(e.cls)
        else:
            start = self.cls.super
        f = None
        if self.state is not None and e.cls is None:
            for c in (start.chain() if start is not None else []):
                if isinstance(c, ClassSym):
                    st = c.members("states").get(self.state.name.lower())
                    if st is not None and e.name.lower() in st.funcs:
                        f = st.funcs[e.name.lower()]
                        break
        if f is None:
            f = start.lookup("funcs", e.name) if start is not None else None
        if f is None:
            raise CompileError("line %d: no super.%s" % (e.line, e.name))
        return self.emit_call(f, e.args, force_final=True)

    def vect_rot(self, e):
        vals = [self.expr(a) for a in e.args]
        if len(vals) == 3 and all(v.const is not None for v in vals):
            if e.name.lower() == "vect":
                return Value(node("VectorConst", *[("f32", float(v.const)) for v in vals]), Type("vector"))
            return Value(node("RotationConst", *[("i32", int(v.const)) for v in vals]), Type("rotator"))
        raise Unsupported("vect/rot with non-constant parts")

    def emit_call(self, f, args, operands_are_values=False, force_final=False):
        params = f.params
        if len(args) > len(params):
            raise CompileError("too many arguments to %s" % f.name)
        toks = []
        for i, p in enumerate(params):
            a = args[i] if i < len(args) else None
            if a is None:
                if not p.optional:
                    raise CompileError("missing argument %s to %s" % (p.name, f.name))
                if i < len(args):
                    toks.append(node("Nothing"))
                continue
            v = a if operands_are_values else self.expr(a, p.type)
            if p.out:
                if not v.lvalue:
                    raise CompileError("argument %s to %s must be a variable" % (p.name, f.name))
            else:
                self._coerce = p.coerce
                try:
                    v = self.convert(v, p.type)
                finally:
                    self._coerce = False
            tok = v.tok
            if p.flags & CPF_SKIP:
                # The skip also jumps over the operator's closing EndFunctionParms.
                tok = node("Skip", ("u16", mem_size(tok) + 1), ("expr", tok))
            toks.append(tok)
        # Trailing skipped optionals are dropped.
        ret = f.ret.type if f.ret is not None else T_VOID
        if f.native and f.has(FUNC_FINAL) or (f.native and f.has(FUNC_OPERATOR)):
            return Value(native(f.native, toks), ret)
        if f.has(FUNC_FINAL) or force_final:
            return Value(node("FinalFunction", ("obj", self.ref(f)), ("params", toks)), ret)
        return Value(node("VirtualFunction", ("name", self.name(f.name)), ("params", toks)), ret)


def compile_function(table, pkg, ref, body_tokens):
    func = table.sym(pkg, ref)
    table.owner_of(func)
    fc = FunctionCompiler(table, pkg, func, table.pkg_names)
    stmts, size = fc.compile_body(body_tokens)
    data, mem = bytecode.encode(stmts)
    return stmts, data, mem
