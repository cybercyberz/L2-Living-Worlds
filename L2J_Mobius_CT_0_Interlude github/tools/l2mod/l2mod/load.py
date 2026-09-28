"""Load stock packages and walk their script objects."""
from . import stock
from .crypto import ver111
from .upk import bytecode, objects
from .upk.package import Package

_cache = {}


def package(name):
    """The stock package `name` (for example "interface.u"), parsed. Verified by hash."""
    if name not in _cache:
        raw = stock.stock_bytes(name)
        _cache[name] = (Package(ver111.decrypt(raw)), raw)
    return _cache[name][0]


def fresh_package(name):
    """A new, independent copy of the stock package, safe to edit."""
    raw = stock.stock_bytes(name)
    return Package(ver111.decrypt(raw)), raw


def script_walker(pkg):
    none = pkg.names.index("None")
    return lambda data, pos, size: bytecode.decode(data, pos, size, none)[1]


def parse(pkg, ref):
    return objects.parse(pkg, ref, script_walker(pkg))


def script(pkg, ref, o=None):
    """(statements, parsed object) for a Function, State, Class or Struct."""
    o = o or parse(pkg, ref)
    e = pkg.exports[ref - 1]
    stmts, _ = bytecode.decode(e.data, o["script_start"], o["script_size"], pkg.names.index("None"))
    return stmts, o


def struct_refs(pkg):
    return [i + 1 for i in range(len(pkg.exports)) if pkg.class_name(i + 1) in objects.STRUCT_CLASSES]


def owning_class(pkg, ref):
    """The Class export that contains `ref` (following outers)."""
    while ref > 0:
        if pkg.class_name(ref) == "Class":
            return ref
        ref = pkg.exports[ref - 1].outer
    return 0
