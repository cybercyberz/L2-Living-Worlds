"""The stage-6 gate: compile every stock class from its own embedded source and compare every object it produces
with the stock export of the same path, byte for byte.

    result = run("interface.u")
    result.classes_matched, result.mismatches, result.errors

The embedded ScriptText leaves out `defaultproperties`, so the gate writes the stock class's defaults back out as a
`defaultproperties` block, appends it to the source, and compiles that too. The one thing taken from the stock class
is its Dependencies list (script CRCs the engine doesn't check at load; see NOTES.md).
"""
import collections
import struct

from .. import load
from ..symbols import SymbolTable
from ..upk import objects
from ..upk.compact import Reader
from .classgen import ClassGen, ClassGenError, InPlace
from .decl import parse_class_decl
from .oracle import class_sources


class Result:
    def __init__(self):
        self.classes_matched = []
        self.objects_matched = 0
        self.mismatches = []  # (path, class, {field: (stock, ours)})
        self.missing = []  # stock children the compiler didn't produce
        self.errors = []  # (class, message)
        self.kinds = collections.Counter()

    def summary(self):
        total = len(self.classes_matched) + len({m[0].split(".")[0] for m in self.mismatches} | {
            e[0] for e in self.errors} | {m.split(".")[0] for m in self.missing})
        return ("%d classes: %d match every object; %d objects match, %d differ, %d missing, %d class errors" % (
            total, len(self.classes_matched), self.objects_matched, len(self.mismatches), len(self.missing),
            len(self.errors)))


def _diff(pkg, walker, ref, ours):
    """{field: (stock, ours)} between the stock object and our bytes."""
    stock = objects.parse(pkg, ref, walker)
    e = pkg.exports[ref - 1]
    saved = e._data
    try:
        e._data = ours
        mine = objects.parse(pkg, ref, walker)
    except Exception as x:
        return {"parse": (None, str(x))}
    finally:
        e._data = saved
    out = {}
    for k in set(stock) | set(mine):
        if k in ("_end", "script_end", "script_start"):
            continue
        if stock.get(k) != mine.get(k):
            out[k] = (stock.get(k), mine.get(k))
    if not out:
        out["script"] = ("bytes differ", "")
    return out


def render_defaults(pkg, defaults):
    """Stock tagged defaults as `defaultproperties` source."""
    lines = []
    for d in defaults:
        v = d["value"]
        if d["type"] == "Int":
            text = str(struct.unpack("<i", v)[0])
        elif d["type"] == "Float":
            text = repr(struct.unpack("<f", v)[0])
        elif d["type"] == "Bool":
            text = "True" if d["bool"] else "False"
        elif d["type"] == "Byte":
            text = str(v[0])
        elif d["type"] == "Str":
            text = '"%s"' % Reader(v).fstring().replace("\\", "\\\\").replace('"', '\\"')
        elif d["type"] == "Name":
            text = "'%s'" % pkg.names[Reader(v).ci()]
        else:
            raise ValueError("can't render a %s default" % d["type"])
        index = "(%d)" % d["index"] if d["index"] else ""
        lines.append("\t%s%s=%s" % (d["name"], index, text))
    nl = "\r\n"
    return nl + "defaultproperties" + nl + "{" + nl + nl.join(lines) + nl + "}" + nl


def run(package_name="interface.u", table=None, only=None):
    table = table or SymbolTable().load_all()
    pkg = load.package(package_name)
    table.package(package_name.rsplit(".", 1)[0])
    walker = load.script_walker(pkg)
    res = Result()
    for cref, text in class_sources(pkg).items():
        cname = pkg.names[pkg.exports[cref - 1].name]
        if only and cname not in only:
            continue
        stock_class = objects.parse(pkg, cref, walker)
        try:
            decl = parse_class_decl(text + render_defaults(pkg, stock_class["defaults"]))
            decl.text = text  # the embedded text never has the block
            gen = ClassGen(table, pkg, decl, InPlace(pkg))
            gen.declare()
            gen.write_declarations()
            gen.objs[0].o["defaults"] = gen.compile_defaults()
            gen.objs[0].o["dependencies"] = stock_class["dependencies"]
            gen.compile_bodies()
            data = gen.serialized()
        except (ClassGenError, Exception) as x:
            res.errors.append((cname, "%s: %s" % (type(x).__name__, x)))
            continue
        ok = True
        for o in gen.objs:
            if data[o.ref] == pkg.exports[o.ref - 1].data:
                res.objects_matched += 1
            else:
                ok = False
                res.kinds[o.cls] += 1
                res.mismatches.append((o.path, o.cls, _diff(pkg, walker, o.ref, data[o.ref])))
        produced = {o.ref for o in gen.objs}
        stack = [cref]
        while stack:
            r = stack.pop()
            for c in pkg.children(r):
                stack.append(c)
                if c not in produced:
                    ok = False
                    res.missing.append(pkg.path(c))
        if ok:
            res.classes_matched.append(cname)
    return res
