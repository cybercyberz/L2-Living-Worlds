"""UnrealScript parser.

`parse_class(text)` finds every function in a class source (top level and inside states) with its body tokens.
`Parser(tokens).body()` parses a function body into statements. Binary operator precedence comes from the compiled
operator functions (lower binds tighter), passed in as `binary_precedence`.
"""
from .lexer import lex


class ParseError(Exception):
    pass


class N:
    """An AST node: N(kind, **fields)."""

    def __init__(self, kind, line=0, **kw):
        self.kind = kind
        self.line = line
        self.__dict__.update(kw)

    def __repr__(self):
        fields = ", ".join("%s=%r" % (k, v) for k, v in self.__dict__.items() if k not in ("kind", "line"))
        return "%s(%s)" % (self.kind, fields)


FUNCTION_WORDS = {"function", "event", "operator", "preoperator", "postoperator", "delegate"}
MODIFIERS = {
    "native", "final", "static", "simulated", "singular", "latent", "iterator", "exec", "private", "protected",
    "public", "const", "reliable", "unreliable", "invariant", "noexport", "transient",
}


class FunctionSource:
    def __init__(self, name, state, header, body, line):
        self.name = name
        self.state = state  # state name or None
        self.header = header  # tokens from the modifiers to the ')'
        self.body = body  # tokens between the braces, or None for a declaration
        self.line = line

    def __repr__(self):
        return "FunctionSource(%s%s)" % (self.state + "." if self.state else "", self.name)


def _skip_braces(toks, i):
    """toks[i] is '{'. Returns the index after the matching '}'."""
    depth = 0
    while True:
        t = toks[i]
        if t.kind == "eof":
            raise ParseError("unbalanced braces")
        if t.kind == "op" and t.text == "{":
            depth += 1
        elif t.kind == "op" and t.text == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def parse_class(text):
    """Every function in a class source: [FunctionSource]."""
    toks = lex(text)
    funcs = []
    _scan(toks, 0, len(toks), None, funcs)
    return funcs


def _scan(toks, i, end, state, funcs):
    while i < end and toks[i].kind != "eof":
        t = toks[i]
        low = t.text.lower() if t.kind == "ident" else None
        if t.kind == "op" and t.text == "{":
            i = _skip_braces(toks, i)
        elif low in ("defaultproperties", "replication", "cpptext", "structdefaultproperties"):
            i += 1
            while not (toks[i].kind == "op" and toks[i].text == "{"):
                i += 1
            i = _skip_braces(toks, i)
        elif low == "state" or (low in ("auto", "simulated") and toks[i + 1].is_("state")):
            while not toks[i].is_("state"):
                i += 1
            i += 1
            if toks[i].kind == "op" and toks[i].text == "(":
                while not (toks[i].kind == "op" and toks[i].text == ")"):
                    i += 1
                i += 1
            name = toks[i].text
            while not (toks[i].kind == "op" and toks[i].text == "{"):
                i += 1
            close = _skip_braces(toks, i)
            _scan(toks, i + 1, close - 1, name, funcs)
            i = close
        elif low in FUNCTION_WORDS:
            start = i
            while start > 0 and toks[start - 1].kind == "ident" and toks[start - 1].text.lower() in MODIFIERS:
                start -= 1
            j = i + 1
            # Operators may have a precedence: operator(24)
            if toks[j].kind == "op" and toks[j].text == "(":
                while not (toks[j].kind == "op" and toks[j].text == ")"):
                    j += 1
                j += 1
            # Up to the '(' of the parameter list; the name is the token just before it.
            while not (toks[j].kind == "op" and toks[j].text == "("):
                j += 1
            name = toks[j - 1].text
            depth = 0
            while True:
                if toks[j].kind == "op" and toks[j].text == "(":
                    depth += 1
                elif toks[j].kind == "op" and toks[j].text == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            header = toks[start:j + 1]
            j += 1
            while toks[j].kind == "ident" and toks[j].text.lower() in MODIFIERS:
                j += 1
            if toks[j].kind == "op" and toks[j].text == "{":
                close = _skip_braces(toks, j)
                funcs.append(FunctionSource(name, state, header, toks[j + 1:close - 1] + [_eof(toks[close - 1])],
                                            toks[i].line))
                i = close
            else:
                funcs.append(FunctionSource(name, state, header, None, toks[i].line))
                i = j + 1
        else:
            i += 1


def _eof(after):
    from .lexer import Tok
    return Tok("eof", "", None, after.line, after.pos)


# ------------------------------------------------------------------------------------------------ statements

class Parser:
    def __init__(self, toks, binary_precedence):
        self.t = toks
        self.i = 0
        self.prec = binary_precedence  # {"==": 24, ...}

    # helpers
    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def at(self, text, k=0):
        return self.peek(k).is_(text)

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, text):
        tok = self.next()
        if not tok.is_(text):
            raise ParseError("line %d: expected %r, got %r" % (tok.line, text, tok.text))
        return tok

    def accept(self, text):
        if self.at(text):
            return self.next()
        return None

    def ident(self):
        tok = self.next()
        if tok.kind != "ident":
            raise ParseError("line %d: expected a name, got %r" % (tok.line, tok.text))
        return tok.text

    # body
    def body(self):
        stmts = []
        while self.peek().kind != "eof":
            s = self.statement()
            if s is not None:
                stmts.append(s)
        return stmts

    def block_or_statement(self):
        if self.at("{"):
            self.next()
            stmts = []
            while not self.at("}"):
                s = self.statement()
                if s is not None:
                    stmts.append(s)
            self.next()
            return N("Block", stmts=stmts)
        s = self.statement()
        return s if s is not None else N("Block", stmts=[])

    def statement(self):
        tok = self.peek()
        line = tok.line
        if tok.is_(";"):
            self.next()
            return None
        if tok.is_("{"):
            return self.block_or_statement()
        if tok.is_("local"):
            self.next()
            typ = self.type_spec()
            names = [self.var_name()]
            while self.accept(","):
                names.append(self.var_name())
            self.expect(";")
            return N("Local", line, type=typ, names=names)
        if tok.is_("if"):
            self.next()
            self.expect("(")
            cond = self.expr()
            self.expect(")")
            then = self.block_or_statement()
            other = None
            if self.accept("else"):
                other = self.block_or_statement()
            return N("If", line, cond=cond, then=then, other=other)
        if tok.is_("while"):
            self.next()
            self.expect("(")
            cond = self.expr()
            self.expect(")")
            return N("While", line, cond=cond, body=self.block_or_statement())
        if tok.is_("do"):
            self.next()
            body = self.block_or_statement()
            self.expect("until")
            self.expect("(")
            cond = self.expr()
            self.expect(")")
            self.accept(";")
            return N("DoUntil", line, body=body, cond=cond)
        if tok.is_("for"):
            self.next()
            self.expect("(")
            init = None if self.at(";") else self.simple_statement()
            self.expect(";")
            cond = None if self.at(";") else self.expr()
            self.expect(";")
            step = None if self.at(")") else self.simple_statement()
            self.expect(")")
            return N("For", line, init=init, cond=cond, step=step, body=self.block_or_statement())
        if tok.is_("foreach"):
            self.next()
            it = self.expr()
            return N("ForEach", line, iterator=it, body=self.block_or_statement())
        if tok.is_("switch"):
            self.next()
            self.expect("(")
            value = self.expr()
            self.expect(")")
            self.expect("{")
            items = []
            while not self.at("}"):
                if self.accept("case"):
                    e = self.expr()
                    self.expect(":")
                    items.append(N("Case", self.peek().line, value=e))
                elif self.accept("default"):
                    self.expect(":")
                    items.append(N("Default", self.peek().line))
                else:
                    s = self.statement()
                    if s is not None:
                        items.append(s)
            self.next()
            return N("Switch", line, value=value, items=items)
        if tok.is_("break"):
            self.next()
            self.accept(";")
            return N("Break", line)
        if tok.is_("continue"):
            self.next()
            self.accept(";")
            return N("Continue", line)
        if tok.is_("return"):
            self.next()
            value = None if self.at(";") else self.expr()
            self.accept(";")
            return N("Return", line, value=value)
        if tok.is_("goto"):
            self.next()
            target = self.expr()
            self.accept(";")
            return N("Goto", line, target=target)
        if tok.is_("stop"):
            self.next()
            self.accept(";")
            return N("Stop", line)
        if tok.is_("assert"):
            self.next()
            self.expect("(")
            cond = self.expr()
            self.expect(")")
            self.accept(";")
            return N("Assert", line, cond=cond)
        if tok.kind == "ident" and self.peek(1).is_(":") and not self.peek(2).is_(":"):
            name = self.next().text
            self.next()
            return N("Label", line, name=name)
        s = self.simple_statement()
        self.accept(";")
        return s

    def simple_statement(self):
        line = self.peek().line
        lhs = self.expr()
        if self.accept("="):
            rhs = self.expr()
            return N("Assign", line, target=lhs, value=rhs)
        return N("ExprStmt", line, expr=lhs)

    def var_name(self):
        name = self.ident()
        dim = None
        if self.accept("["):
            dim = self.expr()
            self.expect("]")
        return (name, dim)

    def type_spec(self):
        name = self.ident()
        if name.lower() in ("array", "class") and self.accept("<"):
            inner = self.type_spec()
            self.expect(">")
            return (name.lower(), inner)
        return name

    # expressions
    def expr(self, max_prec=100):
        left = self.unary()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.text == "?" :
                break
            op = self._binop(tok)
            if op is None:
                break
            prec = self.prec[op]
            if prec >= max_prec:
                break
            self.next()
            if op == ">" and self.at(">"):  # '>' '>' tokenised apart inside class<...> is not an issue here
                pass
            right = self.expr(prec)
            left = N("Binary", tok.line, op=op, left=left, right=right)
        return left

    def _binop(self, tok):
        if tok.kind == "op" and tok.text in self.prec:
            return tok.text
        if tok.kind == "ident" and tok.text.lower() in self.prec:  # word operators like `dot`, `cross`, `ClockwiseFrom`
            return tok.text.lower()
        return None

    def unary(self):
        tok = self.peek()
        if tok.kind == "op" and tok.text in ("!", "-", "~", "++", "--", "+"):
            self.next()
            return N("Unary", tok.line, op=tok.text, operand=self.unary())
        e = self.postfix(self.primary())
        while self.peek().kind == "op" and self.peek().text in ("++", "--"):
            op = self.next().text
            e = N("Postfix", tok.line, op=op, operand=e)
        return e

    def postfix(self, e):
        while True:
            tok = self.peek()
            if tok.is_("."):
                self.next()
                name = self.ident()
                if self.at("("):
                    e = N("Call", tok.line, target=e, name=name, args=self.call_args())
                else:
                    e = N("Member", tok.line, target=e, name=name)
            elif tok.is_("["):
                self.next()
                index = self.expr()
                self.expect("]")
                e = N("Index", tok.line, target=e, index=index)
            else:
                return e

    def call_args(self):
        self.expect("(")
        args = []
        if self.accept(")"):
            return args
        while True:
            if self.at(",") or self.at(")"):
                args.append(None)  # skipped optional parameter
            else:
                args.append(self.expr())
            if self.accept(","):
                continue
            self.expect(")")
            return args

    def primary(self):
        tok = self.next()
        line = tok.line
        if tok.kind == "int":
            return N("Int", line, value=tok.value)
        if tok.kind == "float":
            return N("Float", line, value=tok.value)
        if tok.kind == "string":
            return N("String", line, value=tok.value)
        if tok.kind == "name":
            return N("NameLit", line, value=tok.value)
        if tok.is_("("):
            e = self.expr()
            self.expect(")")
            return N("Paren", line, expr=e)
        if tok.kind != "ident":
            raise ParseError("line %d: unexpected %r" % (line, tok.text))
        low = tok.text.lower()
        if low in ("true", "false"):
            return N("Bool", line, value=low == "true")
        if low == "none":
            return N("None", line)
        if low == "self":
            return N("Self", line)
        if low == "class" and self.peek().kind == "name":
            return N("ClassLit", line, name=self.next().value)
        if low == "default" and self.at("."):
            self.next()
            return N("DefaultVar", line, name=self.ident())
        if low == "static" and self.at("."):
            self.next()
            name = self.ident()
            return N("Call", line, target=None, name=name, args=self.call_args(), static=True)
        if low == "super":
            cls = None
            if self.accept("("):
                cls = self.ident()
                self.expect(")")
            self.expect(".")
            name = self.ident()
            return N("SuperCall", line, cls=cls, name=name, args=self.call_args())
        if low == "global" and self.at("."):
            self.next()
            name = self.ident()
            return N("GlobalCall", line, name=name, args=self.call_args())
        if low == "new":
            outer = name = flags = None
            if self.accept("("):
                args = self.call_args_after_paren()
                outer = args[0] if args else None
                name = args[1] if len(args) > 1 else None
                flags = args[2] if len(args) > 2 else None
            cls = self.postfix(self.primary())
            return N("New", line, outer=outer, obj_name=name, flags=flags, cls=cls)
        if low in ("vect", "rot") and self.at("("):
            return N("Call", line, target=None, name=tok.text, args=self.call_args())
        if self.at("("):
            return N("Call", line, target=None, name=tok.text, args=self.call_args())
        if low == "class" and self.at("<"):  # class<X>(expr): a metaclass cast
            self.next()
            meta = self.ident()
            self.expect(">")
            self.expect("(")
            inner = self.expr()
            self.expect(")")
            return N("MetaCast", line, meta=meta, expr=inner)
        if self.peek().kind == "name":  # Texture'Package.Name'
            return N("ObjectLit", line, cls=tok.text, value=self.next().value)
        return N("Ident", line, name=tok.text)

    def call_args_after_paren(self):
        args = []
        if self.accept(")"):
            return args
        while True:
            args.append(self.expr())
            if self.accept(","):
                continue
            self.expect(")")
            return args
