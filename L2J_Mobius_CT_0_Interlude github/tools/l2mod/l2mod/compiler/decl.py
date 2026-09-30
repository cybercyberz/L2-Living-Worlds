"""Class declarations: everything in a class source except function bodies.

`parse_class_decl(text)` returns a `ClassDecl`. It covers the class header, `const`, `var`, `enum`, `struct`,
functions (header, parameters, `local` declarations and the body tokens), `state` blocks and `defaultproperties`.
Every item keeps its source line and character position, because the compiled objects record them.

Types stay as source text (`int`, `WindowHandle`, `("array", "ItemInfo")`, `("class", "Actor")`); the class
generator resolves them against the symbol table.
"""
from .lexer import Tok, lex
from .parser import FUNCTION_WORDS, MODIFIERS, ParseError, _skip_braces

VAR_MODIFIERS = {
    "config", "globalconfig", "localized", "const", "editconst", "private", "protected", "public", "transient",
    "native", "input", "export", "noexport", "editinline", "edfindable", "deprecated", "editinlineuse",
    "editinlinenotify", "automated", "noimport", "cache",
}
PARAM_MODIFIERS = {"optional", "out", "coerce", "skip", "const"}


class VarDecl:
    def __init__(self, type_, name, dim, modifiers, category, line, pos):
        self.type = type_
        self.name = name
        self.dim = dim  # None, an int, or a const name
        self.modifiers = modifiers
        self.category = category  # None for `var`, "" for `var()`, else the name in var(...)
        self.line = line
        self.pos = pos

    def __repr__(self):
        return "Var(%s %s%s)" % (self.type, self.name, "[%s]" % self.dim if self.dim is not None else "")


class ConstDecl:
    def __init__(self, name, value, line, pos):
        self.name = name
        self.value = value  # the raw source text after `=`, as the compiler stores it (" 12")
        self.line = line
        self.pos = pos


class EnumDecl:
    def __init__(self, name, values, line, pos):
        self.name = name
        self.values = values
        self.line = line
        self.pos = pos


class StructDecl:
    def __init__(self, name, parent, modifiers, fields, line, pos):
        self.name = name
        self.parent = parent
        self.modifiers = modifiers
        self.fields = fields  # [VarDecl]
        self.line = line
        self.pos = pos


class FuncDecl:
    def __init__(self, name, kind, modifiers, ret, params, locals_, body, state, line, pos, operator_precedence):
        self.name = name
        self.kind = kind  # function / event / operator / preoperator / postoperator / delegate
        self.modifiers = modifiers
        self.ret = ret  # type or None
        self.params = params  # [VarDecl], modifiers hold optional/out/coerce
        self.locals = locals_  # [VarDecl]
        self.body = body  # body tokens ending with eof, or None for a declaration
        self.body_line = 0  # the line and position of the first body token (what the compiler records)
        self.body_pos = 0
        self.state = state
        self.line = line
        self.pos = pos
        self.operator_precedence = operator_precedence

    def __repr__(self):
        return "Func(%s%s)" % (self.state + "." if self.state else "", self.name)


class StateDecl:
    def __init__(self, name, parent, modifiers, ignores, funcs, code, line, pos, end_line, end_pos):
        self.name = name
        self.parent = parent
        self.modifiers = modifiers
        self.ignores = ignores
        self.funcs = funcs
        self.code = code  # tokens of state code (labels and statements), or []
        self.line = line
        self.pos = pos
        self.end_line = end_line  # the closing brace
        self.end_pos = end_pos


class DefaultDecl:
    def __init__(self, name, index, value, line):
        self.name = name
        self.index = index  # None, or the array index
        self.value = value  # tokens of the value
        self.line = line


class ClassDecl:
    def __init__(self):
        self.name = None
        self.parent = None
        self.modifiers = []  # [(name, [argument tokens])]
        self.items = []  # every declaration in source order
        self.defaults = []
        self.text = ""

    def of(self, kind):
        return [i for i in self.items if isinstance(i, kind)]

    @property
    def consts(self):
        return self.of(ConstDecl)

    @property
    def vars(self):
        return self.of(VarDecl)

    @property
    def enums(self):
        return self.of(EnumDecl)

    @property
    def structs(self):
        return self.of(StructDecl)

    @property
    def funcs(self):
        return self.of(FuncDecl)

    @property
    def states(self):
        return self.of(StateDecl)


class _Decl:
    def __init__(self, text):
        self.text = text
        self.t = lex(text)
        self.i = 0

    # ------------------------------------------------------------------------------------------------- helpers

    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def at(self, text, k=0):
        return self.peek(k).is_(text)

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def fail(self, what):
        tok = self.peek()
        raise ParseError("line %d: expected %s, got %r" % (tok.line, what, tok.text))

    def expect(self, text):
        if not self.at(text):
            self.fail(repr(text))
        return self.next()

    def accept(self, text):
        return self.next() if self.at(text) else None

    def ident(self):
        tok = self.peek()
        if tok.kind != "ident":
            self.fail("a name")
        return self.next().text

    def low(self, k=0):
        tok = self.peek(k)
        return tok.text.lower() if tok.kind == "ident" else None

    def paren_args(self):
        """After a `(`: the tokens up to the matching `)`."""
        depth = 1
        out = []
        while True:
            tok = self.next()
            if tok.kind == "eof":
                self.fail("')'")
            if tok.is_("("):
                depth += 1
            elif tok.is_(")"):
                depth -= 1
                if depth == 0:
                    return out
            out.append(tok)

    def type_spec(self):
        name = self.ident()
        if name.lower() in ("array", "class") and self.accept("<"):
            inner = self.type_spec()
            self.expect(">")
            return (name.lower(), inner)
        return name

    def dim(self):
        if not self.accept("["):
            return None
        tok = self.next()
        self.expect("]")
        return tok.value if tok.kind == "int" else tok.text

    # ------------------------------------------------------------------------------------------------- class

    def parse(self):
        d = ClassDecl()
        d.text = self.text
        self.expect("class")
        d.name = self.ident()
        if self.accept("extends"):
            d.parent = self.ident()
            while self.accept("."):  # extends Package.Class
                d.parent = self.ident()
        while not self.at(";"):
            m = self.ident()
            args = self.paren_args() if self.accept("(") else []
            d.modifiers.append((m.lower(), args))
        self.expect(";")
        while self.peek().kind != "eof":
            self.item(d, d.items, None)
        return d

    def item(self, d, items, state):
        low = self.low()
        tok = self.peek()
        if tok.is_(";"):
            self.next()
        elif low == "const":
            items.append(self.const())
        elif low == "var":
            items.extend(self.var())
        elif low == "enum":
            items.append(self.enum())
        elif low == "struct":
            items.append(self.struct())
        elif low in ("defaultproperties", "structdefaultproperties"):
            self.next()
            d.defaults.extend(self.defaults())
        elif low in ("replication", "cpptext"):
            self.next()
            while not self.at("{"):
                self.next()
            self.i = _skip_braces(self.t, self.i)
        elif low == "state" or (low in ("auto", "simulated") and self._state_ahead()):
            items.append(self.state(d))
        elif low in FUNCTION_WORDS or (low in MODIFIERS and self._function_ahead()):
            items.append(self.function(state))
        else:
            self.fail("a declaration")

    def _state_ahead(self):
        k = 0
        while self.low(k) in ("auto", "simulated"):
            k += 1
        return self.low(k) == "state"

    def _function_ahead(self):
        k = 0
        while self.low(k) in MODIFIERS:
            k += 1
            if self.peek(k).is_("("):  # native(123)
                while not self.peek(k).is_(")"):
                    k += 1
                k += 1
        return self.low(k) in FUNCTION_WORDS

    def const(self):
        tok = self.expect("const")
        name = self.ident()
        eq = self.expect("=")
        while not self.at(";"):
            self.next()
        end = self.peek().pos
        self.next()
        return ConstDecl(name, self.text[eq.pos + 1:end], tok.line, tok.pos)

    def var(self, in_struct=False):
        tok = self.expect("var")
        category = None
        if self.accept("("):
            args = self.paren_args()
            category = args[0].text if args else ""
        mods = []
        while self.low() in VAR_MODIFIERS:
            mods.append(self.next().text.lower())
            if self.at("("):  # config(Section) and friends
                self.next()
                self.paren_args()
        type_ = self.type_spec()
        out = []
        while True:
            name_tok = self.peek()
            name = self.ident()
            out.append(VarDecl(type_, name, self.dim(), mods, category, name_tok.line, name_tok.pos))
            if not self.accept(","):
                break
        self.expect(";")
        return out

    def enum(self):
        tok = self.expect("enum")
        name = self.ident()
        self.expect("{")
        values = []
        while not self.at("}"):
            values.append(self.ident())
            self.accept(",")
        self.expect("}")
        self.accept(";")
        return EnumDecl(name, values, tok.line, tok.pos)

    def struct(self):
        tok = self.expect("struct")
        mods = []
        while self.peek(1).kind == "ident" and not self.at("extends", 1):
            mods.append(self.next().text.lower())
        name = self.ident()
        parent = self.ident() if self.accept("extends") else None
        self.expect("{")
        fields = []
        while not self.at("}"):
            if self.low() == "var":
                fields.extend(self.var(True))
            elif self.low() == "structdefaultproperties":
                self.next()
                self.defaults()
            else:
                self.fail("a struct member")
        self.expect("}")
        self.accept(";")
        return StructDecl(name, parent, mods, fields, tok.line, tok.pos)

    def function(self, state):
        start = self.peek()
        mods = []
        while self.low() in MODIFIERS:
            m = self.next().text.lower()
            if self.accept("("):
                args = self.paren_args()
                m = (m, args[0].value if args else None)
            mods.append(m)
        kind = self.next().text.lower()
        precedence = None
        if kind in ("operator", "preoperator", "postoperator") and self.accept("("):
            precedence = self.paren_args()[0].value
        # [return type] name (
        names = []
        while not self.at("("):
            tok = self.next()
            if tok.kind == "eof":
                self.fail("'('")
            names.append(tok)
        if not names:
            self.fail("a function name")
        name = names[-1].text
        ret = None
        if len(names) > 1:
            ret = self._type_from(names[:-1])
        self.expect("(")
        params = []
        while not self.at(")"):
            pmods = []
            while self.low() in PARAM_MODIFIERS:
                pmods.append(self.next().text.lower())
            ptype = self.type_spec()
            ptok = self.peek()
            pname = self.ident()
            params.append(VarDecl(ptype, pname, self.dim(), pmods, None, ptok.line, ptok.pos))
            self.accept(",")
        self.expect(")")
        while self.low() in MODIFIERS:
            mods.append(self.next().text.lower())
        f = FuncDecl(name, kind, mods, ret, params, [], None, state, start.line, start.pos, precedence)
        semi = self.accept(";")
        if semi:
            f.body_line, f.body_pos = semi.line, semi.pos  # a declaration: the compiler records its `;`
            return f
        self.expect("{")
        open_i = self.i - 1
        close = _skip_braces(self.t, open_i)
        body = self.t[self.i:close - 1]
        # Leading `local` declarations become the function's locals.
        j = 0
        while j < len(body) and body[j].is_("local"):
            k = j + 1
            sub = _Decl.__new__(_Decl)
            sub.text, sub.t, sub.i = self.text, body[k:] + [Tok("eof", "", None, 0, 0)], 0
            ltype = sub.type_spec()
            while True:
                ntok = sub.peek()
                lname = sub.ident()
                f.locals.append(VarDecl(ltype, lname, sub.dim(), [], None, ntok.line, ntok.pos))
                if not sub.accept(","):
                    break
            sub.expect(";")
            j = k + sub.i
        first = body[j] if j < len(body) else self.t[close - 1]  # the first statement after the locals
        f.body_line, f.body_pos = first.line, first.pos
        f.body = body + [Tok("eof", "", None, self.t[close - 1].line, self.t[close - 1].pos)]
        self.i = close
        return f

    def _type_from(self, toks):
        sub = _Decl.__new__(_Decl)
        sub.text, sub.t, sub.i = self.text, toks + [Tok("eof", "", None, 0, 0)], 0
        t = sub.type_spec()
        if sub.peek().kind != "eof":
            raise ParseError("line %d: bad return type" % toks[0].line)
        return t

    def state(self, d):
        start = self.peek()
        mods = []
        while self.low() in ("auto", "simulated"):
            mods.append(self.next().text.lower())
        self.expect("state")
        if self.accept("("):
            self.paren_args()
        name = self.ident()
        parent = self.ident() if self.accept("extends") else None
        self.expect("{")
        ignores = []
        funcs = []
        code = []
        while not self.at("}"):
            low = self.low()
            if low == "ignores":
                self.next()
                while not self.at(";"):
                    ignores.append(self.ident())
                    self.accept(",")
                self.next()
            elif low in FUNCTION_WORDS or (low in MODIFIERS and self._function_ahead()):
                funcs.append(self.function(name))
            elif self.at(";"):
                self.next()
            else:
                # State code: labels and statements up to the closing brace.
                while not self.at("}") or self._depth_of_code(code):
                    code.append(self.next())
                break
        end = self.expect("}")
        return StateDecl(name, parent, mods, ignores, funcs, code, start.line, start.pos, end.line, end.pos)

    @staticmethod
    def _depth_of_code(code):
        return sum(1 for t in code if t.is_("{")) - sum(1 for t in code if t.is_("}"))

    def defaults(self):
        self.expect("{")
        out = []
        while not self.at("}"):
            if self.at(";") or self.at(","):
                self.next()
                continue
            tok = self.peek()
            name = self.ident()
            index = None
            if self.accept("("):
                index = self.paren_args()[0].value
            elif self.accept("["):
                index = self.next().value
                self.expect("]")
            self.expect("=")
            value = []
            depth = 0
            while True:
                t = self.peek()
                if t.kind == "eof":
                    self.fail("'}'")
                if depth == 0 and (t.line != tok.line and value or t.is_("}") or t.is_(";")):
                    break
                if t.is_("(") or t.is_("{"):
                    depth += 1
                elif t.is_(")") or t.is_("}"):
                    depth -= 1
                value.append(self.next())
            out.append(DefaultDecl(name, index, value, tok.line))
        self.expect("}")
        return out


def parse_class_decl(text):
    return _Decl(text).parse()
