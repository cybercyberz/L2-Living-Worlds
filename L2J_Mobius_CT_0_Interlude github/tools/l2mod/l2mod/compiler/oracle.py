"""The stage-3 gate: compile stock functions from their own embedded source and compare with the stock bytecode.

    result = run("interface.u")
    result.matched, result.mismatched, result.unsupported, result.errors
"""
import collections

from .. import disasm, load
from ..symbols import SymbolTable
from ..upk import bytecode, objects
from .codegen import CompileError, Unsupported, compile_function
from .parser import parse_class


class Result:
    def __init__(self):
        self.matched = []
        self.mismatched = []  # (path, stock listing, compiled listing)
        self.unsupported = collections.Counter()
        self.unsupported_examples = {}
        self.errors = collections.Counter()
        self.error_examples = {}

    def summary(self):
        total = len(self.matched) + len(self.mismatched) + sum(self.unsupported.values()) + sum(
            self.errors.values())
        return ("%d functions: %d match, %d differ, %d unsupported, %d errors" % (
            total, len(self.matched), len(self.mismatched), sum(self.unsupported.values()),
            sum(self.errors.values())))


def class_sources(pkg):
    """{class ref: source text} for classes that embed their source."""
    out = {}
    for ref in range(1, len(pkg.exports) + 1):
        if pkg.class_name(ref) != "Class":
            continue
        for c in pkg.children(ref):
            if pkg.class_name(c) == "TextBuffer" and pkg.names[pkg.exports[c - 1].name] == "ScriptText":
                out[ref] = objects.parse(pkg, c)["text"]
    return out


def run(package_name="interface.u", table=None, only=None):
    table = table or SymbolTable().load_all()
    pkg = load.package(package_name)
    table.package(package_name.rsplit(".", 1)[0])
    lister = disasm.Lister(pkg)
    res = Result()
    for cref, text in class_sources(pkg).items():
        cname = pkg.names[pkg.exports[cref - 1].name]
        try:
            funcs = parse_class(text)
        except Exception as x:
            k = "class parse: %s" % str(x)[:60]
            res.errors[k] += 1
            res.error_examples.setdefault(k, cname)
            continue
        for fs in funcs:
            if fs.body is None:
                continue
            path = "%s.%s%s" % (cname, fs.state + "." if fs.state else "", fs.name)
            if only and path not in only:
                continue
            try:
                ref = pkg.find(path, "Function")
            except KeyError:
                res.errors["no export"] += 1
                res.error_examples.setdefault("no export", path)
                continue
            stmts, o = load.script(pkg, ref)
            stock = pkg.exports[ref - 1].data[o["script_start"]:o["script_end"]]
            try:
                cstmts, data, mem = compile_function(table, pkg, ref, fs.body)
            except Unsupported as x:
                k = str(x)[:60]
                res.unsupported[k] += 1
                res.unsupported_examples.setdefault(k, path)
                continue
            except (CompileError, Exception) as x:
                k = "%s: %s" % (type(x).__name__, str(x)[:70])
                res.errors[k] += 1
                res.error_examples.setdefault(k, path)
                continue
            if data == stock and mem == o["script_size"]:
                res.matched.append(path)
            else:
                try:  # list the compiled bytes as decoded, so labels line up with the stock listing
                    cstmts, _ = bytecode.decode(data, 0, mem, pkg.names.index("None"))
                except bytecode.DecodeError:
                    pass
                res.mismatched.append((path, lister.listing(stmts, o["script_size"]),
                                       lister.listing(cstmts, mem)))
    return res
