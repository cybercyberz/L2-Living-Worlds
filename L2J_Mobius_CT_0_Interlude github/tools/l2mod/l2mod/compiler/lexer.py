"""UnrealScript tokens."""
import re


class Tok:
    __slots__ = ("kind", "text", "value", "line", "pos")

    def __init__(self, kind, text, value, line, pos):
        self.kind = kind  # ident int float string name op eof
        self.text = text
        self.value = value
        self.line = line
        self.pos = pos

    def __repr__(self):
        return "%s(%r)@%d" % (self.kind, self.text, self.line)

    def is_(self, text):
        return self.kind in ("ident", "op") and self.text.lower() == text.lower()


class LexError(Exception):
    pass


# Longest first.
OPERATORS = sorted([
    ">>>", "<<", ">>", "**", "~=", "==", "!=", "<=", ">=", "&&", "||", "^^", "++", "--", "+=", "-=", "*=", "/=",
    "$=", "@=", "$", "@", "!", "~", "+", "-", "*", "/", "%", "<", ">", "&", "|", "^", "=", "?", ":", ".", ",",
    ";", "(", ")", "{", "}", "[", "]", "#",
], key=len, reverse=True)
_OP_RE = "|".join(re.escape(o) for o in OPERATORS)
_RE = re.compile(r"""
    (?P<ws>[ \t\r\f\v]+)
  | (?P<nl>\n)
  | (?P<directive>\#[A-Za-z][^\n]*)
  | (?P<line_comment>//[^\n]*)
  | (?P<block_comment>/\*.*?\*/)
  | (?P<float>(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?f?|\d+[eE][-+]?\d+f?|\d+f\b)
  | (?P<hex>0[xX][0-9A-Fa-f]+)
  | (?P<int>\d+)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<name>'[^'\n]*')
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>%s)
""" % _OP_RE, re.VERBOSE | re.DOTALL)


def _unescape(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 1
            c = s[i]  # UnrealScript: a backslash escapes the next character literally
        out.append(c)
        i += 1
    return "".join(out)


def lex(text):
    toks = []
    pos = 0
    line = 1
    n = len(text)
    while pos < n:
        m = _RE.match(text, pos)
        if not m:
            raise LexError("line %d: cannot read %r" % (line, text[pos:pos + 20]))
        kind = m.lastgroup
        s = m.group(kind)
        if kind == "nl":
            line += 1
        elif kind in ("ws", "line_comment", "directive"):  # #exec and friends are editor-only
            pass
        elif kind == "block_comment":
            line += s.count("\n")
        elif kind == "float":
            toks.append(Tok("float", s, float(s.rstrip("fF")), line, pos))
        elif kind == "hex":
            toks.append(Tok("int", s, int(s, 16), line, pos))
        elif kind == "int":
            toks.append(Tok("int", s, int(s), line, pos))
        elif kind == "string":
            toks.append(Tok("string", s, _unescape(s[1:-1]), line, pos))
        elif kind == "name":
            toks.append(Tok("name", s, s[1:-1], line, pos))
        elif kind == "ident":
            toks.append(Tok("ident", s, s, line, pos))
        else:
            toks.append(Tok("op", s, s, line, pos))
        pos = m.end()
    toks.append(Tok("eof", "", None, line, pos))
    return toks
