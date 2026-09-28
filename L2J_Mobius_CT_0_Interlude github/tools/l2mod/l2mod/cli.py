"""Command line: python tools/l2mod <command> ...

    decompile <package> [outdir]      each class's source (.uc) and bytecode listing (.asm)
    disasm <package> <Class.Function> one listing to stdout
    info <package>                    object counts
    selftest [--quick]                run the safety gates (--quick: interface.u only)
"""
import collections
import os
import sys
import time

from . import disasm, load, stock
from .upk import objects


def cmd_decompile(args):
    name = args[0]
    out = args[1] if len(args) > 1 else os.path.join(stock.TOOLS, "out", name.rsplit(".", 1)[0])
    pkg = load.package(name)
    lister = disasm.Lister(pkg)
    os.makedirs(out, exist_ok=True)
    listings = collections.defaultdict(list)
    for ref in load.struct_refs(pkg):
        stmts, o = load.script(pkg, ref)
        cls = load.owning_class(pkg, ref)
        body = [disasm.function_header(pkg, ref, o)]
        body += ["    " + line for line in lister.listing(stmts, o["script_size"])]
        listings[cls].append("\n".join(body))
    count = 0
    for ref in range(1, len(pkg.exports) + 1):
        if pkg.class_name(ref) != "Class":
            continue
        cname = pkg.names[pkg.exports[ref - 1].name]
        for child in pkg.children(ref):
            if pkg.class_name(child) == "TextBuffer" and pkg.names[pkg.exports[child - 1].name] == "ScriptText":
                text = objects.parse(pkg, child)["text"]
                with open(os.path.join(out, cname + ".uc"), "w", encoding="utf-8", newline="") as f:
                    f.write(text)
        with open(os.path.join(out, cname + ".asm"), "w", encoding="utf-8", newline="\n") as f:
            f.write("; %s from %s. Reassembles to identical bytes with l2mod.asm.\n\n" % (cname, name))
            f.write("\n\n".join(listings.get(ref, [])) + "\n")
        count += 1
    print("wrote %d classes to %s" % (count, out))


def cmd_disasm(args):
    pkg = load.package(args[0])
    ref = pkg.find(args[1])
    stmts, o = load.script(pkg, ref)
    print(disasm.function_header(pkg, ref, o))
    for line in disasm.Lister(pkg).listing(stmts, o["script_size"]):
        print("    " + line)


def cmd_info(args):
    pkg = load.package(args[0])
    kinds = collections.Counter(pkg.class_name(i + 1) for i in range(len(pkg.exports)))
    print("%s: version %d licensee %d, %d names, %d imports, %d exports" % (
        args[0], pkg.version, pkg.licensee, len(pkg.names), len(pkg.imports), len(pkg.exports)))
    for k, v in kinds.most_common():
        print("  %6d %s" % (v, k))


def cmd_selftest(args):
    import unittest
    if "--quick" in args:
        os.environ["L2MOD_QUICK"] = "1"
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    t = time.time()
    suite = unittest.defaultTestLoader.discover(os.path.join(here, "tests"), top_level_dir=here)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("selftest %s in %.0fs" % ("PASSED" if result.wasSuccessful() else "FAILED", time.time() - t))
    return 0 if result.wasSuccessful() else 1


COMMANDS = {"decompile": cmd_decompile, "disasm": cmd_disasm, "info": cmd_info, "selftest": cmd_selftest}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:]) or 0
