"""Patch files: UnrealScript (or bytecode listings) that replace function bodies in stock client packages.

A patch file (`*.l2patch`) looks like this:

    ; What the patch does. Lines starting with ; are comments.
    package interface.u

    replace QuestTreeWnd.OnClickButton
    {
        if (Left(strID, 4) == "root")
            RequestBypassToServer("_bbs_questnav step " $ strID);
    }

    asm SomeClass.SomeFunction
    {
        Virtual(#Foo)
        Return(Nothing)
    }

`replace` compiles UnrealScript against the function's existing parameters and locals. `asm` takes a bytecode
listing (see disasm.py).

For the window layout, use `package interface.xdat` and these lines:

    set QuestTreeWnd.btnClose.anchor_x = 120          ; change a field (int, float or "string")
    clone QuestTreeWnd.btnClose as btnNav             ; copy a control inside its window, then set fields:
    set QuestTreeWnd.btnNav.anchor_x = 170
    remove QuestTreeWnd.txt324                        ; delete a control

Patches always apply to the stock file, never to an already-patched one, so building is repeatable.
"""
import json
import os
import re
import shutil
import struct
import subprocess

from . import asm, disasm, load, stock
from .crypto import ver111
from .symbols import SymbolTable
from .upk import bytecode
from .upk.package import Package

MANIFEST = os.path.join(stock.BACKUP, "l2mod-installed.json")


class PatchError(Exception):
    pass


class Edit:
    def __init__(self, kind, target, body, source, line):
        self.kind = kind  # "replace" or "asm"
        self.target = target  # Class.Function or Class.State.Function
        self.body = body  # text between the braces
        self.source = source
        self.line = line


class XdatOp:
    def __init__(self, op, path, value, line):
        self.op = op  # set / clone / remove
        self.path = path
        self.value = value  # the value for set, the new name for clone
        self.line = line


class PatchFile:
    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.package = None
        self.edits = []
        self.xdat_ops = []
        self.description = []
        self._parse(open(path, encoding="utf-8").read())

    def _parse(self, text):
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if not s:
                i += 1
                continue
            if s.startswith(";"):
                if not self.edits and self.package is None:
                    self.description.append(s[1:].strip())
                i += 1
                continue
            m = re.fullmatch(r"package\s+(\S+)", s)
            if m:
                self.package = m.group(1)
                i += 1
                continue
            if self.package and self.package.lower().endswith(".xdat"):
                self.xdat_ops.append(self._parse_xdat_line(s.split(";", 1)[0].strip(), i + 1))
                i += 1
                continue
            m = re.fullmatch(r"(replace|asm)\s+([A-Za-z_][\w.]*)", s)
            if not m:
                raise PatchError("%s:%d: expected `package`, `replace` or `asm`, got %r" % (self.path, i + 1, s))
            kind, target = m.groups()
            start = i + 1
            while start < len(lines) and not lines[start].strip():
                start += 1
            if start >= len(lines) or lines[start].strip() != "{":
                raise PatchError("%s:%d: `%s %s` must be followed by a line with just `{`" % (
                    self.path, i + 1, kind, target))
            depth = 0
            j = start
            body = []
            while j < len(lines):
                t = lines[j]
                if j > start:
                    if t.strip() == "}" and depth == 0:
                        break
                    body.append(t)
                    if kind == "replace":
                        depth += t.count("{") - t.count("}")
                j += 1
            else:
                raise PatchError("%s:%d: missing the closing `}`" % (self.path, i + 1))
            self.edits.append(Edit(kind, target, "\n".join(body), self.path, start + 2))
            i = j + 1
        if self.package is None:
            raise PatchError("%s: no `package` line" % self.path)

    def _parse_xdat_line(self, s, line):
        m = re.fullmatch(r"set\s+([\w.]+)\s*=\s*(.+)", s)
        if m:
            path, raw = m.groups()
            raw = raw.strip()
            try:
                value = json.loads(raw)
            except ValueError:
                raise PatchError("%s:%d: can't read the value %s (use 12, 1.5 or \"text\")" % (self.path, line, raw))
            return XdatOp("set", path, value, line)
        m = re.fullmatch(r"clone\s+([\w.]+)\s+as\s+(\w+)", s)
        if m:
            return XdatOp("clone", m.group(1), m.group(2), line)
        m = re.fullmatch(r"remove\s+([\w.]+)", s)
        if m:
            return XdatOp("remove", m.group(1), None, line)
        raise PatchError("%s:%d: expected set, clone or remove, got %r" % (self.path, line, s))


# ------------------------------------------------------------------------------------------------------ building

def _function_parts(pkg, ref):
    """(prefix bytes, script bytes, tail bytes, parsed object) of a Function export."""
    o = load.parse(pkg, ref)
    data = pkg.exports[ref - 1].data
    return data[:o["script_start"]], data[o["script_start"]:o["script_end"]], data[o["script_end"]:], o


def build_xdat(package_name, patches):
    """Apply layout edits to the stock interface.xdat. Returns (bytes, report lines)."""
    import copy
    from . import xdat
    stock_data = stock.stock_bytes(package_name)
    x = xdat.Xdat.read(stock_data)
    report = []
    touched = set()
    for pf in patches:
        if pf.package.lower() != package_name.lower():
            continue
        for op in pf.xdat_ops:
            where = "%s:%d" % (pf.path, op.line)
            parts = op.path.split(".")
            touched.add(parts[0])
            try:
                if op.op == "set":
                    ent = x.find(".".join(parts[:-1]))
                    field = parts[-1]
                    if field not in ent:
                        raise PatchError("%s: %s has no field %s (it has: %s)" % (
                            where, ent, field, ", ".join(k for k in ent if k != "children")))
                    old = ent[field]
                    if isinstance(old, list) or type(old) is not type(op.value) and not (
                            isinstance(old, float) and isinstance(op.value, int)):
                        raise PatchError("%s: %s.%s is %s, not %s" % (where, ent, field, type(old).__name__,
                                                                    type(op.value).__name__))
                    ent[field] = float(op.value) if isinstance(old, float) else op.value
                    report.append("%s: set %s = %r (was %r)" % (pf.name, op.path, op.value, old))
                elif op.op == "clone":
                    ent = x.find(op.path)
                    parent = x.find(".".join(parts[:-1])) if len(parts) > 1 else None
                    new = copy.deepcopy(ent)
                    new["name"] = op.value
                    new.raw_strings.pop("name", None)
                    if parent is None:
                        x.windows.append(new)
                    else:
                        if any(c.name == op.value for c in parent["children"]):
                            raise PatchError("%s: %s already has a %s" % (where, parent, op.value))
                        parent["children"].append(new)
                    report.append("%s: cloned %s as %s" % (pf.name, op.path, op.value))
                elif op.op == "remove":
                    parent = x.find(".".join(parts[:-1]))
                    child = parent.get_child(parts[-1])
                    parent["children"].remove(child)
                    report.append("%s: removed %s" % (pf.name, op.path))
            except KeyError as k:
                raise PatchError("%s: no window or control %s" % (where, k))
    out = x.to_bytes()
    # Verify: the result reads back, and every window we didn't touch is byte-identical.
    y = xdat.Xdat.read(out)
    orig = xdat.Xdat.read(stock_data)
    if len(y.windows) < len(orig.windows) - 0 and not touched:
        raise PatchError("verification failed: windows lost")
    for w in orig.windows:
        if w.name in touched:
            continue
        a = bytearray()
        b = bytearray()
        xdat._write_control(a, w)
        xdat._write_control(b, y.window(w.name))
        if a != b:
            raise PatchError("verification failed: untouched window %s changed" % w.name)
    report.append("%s: built and verified, %d windows" % (package_name, len(y.windows)))
    return out, report


def build(package_name, patches, table=None):
    """Apply every edit in `patches` (PatchFile list, in order) to the stock package. Returns (encrypted bytes,
    report lines). Raises PatchError on any problem, before anything is written."""
    if package_name.lower().endswith(".xdat"):
        return build_xdat(package_name, patches)
    from .compiler.codegen import CompileError, FunctionCompiler
    from .compiler.lexer import lex

    stock_pkg = load.package(package_name)  # the cached stock copy the symbol table reads
    pkg, raw = load.fresh_package(package_name)  # the copy we edit
    table = table or SymbolTable().load_all()
    table.package(package_name.rsplit(".", 1)[0])
    report = []
    touched = {}
    for pf in patches:
        if pf.package.lower() != package_name.lower():
            continue
        for ed in pf.edits:
            try:
                ref = stock_pkg.find(ed.target, "Function")
            except KeyError:
                raise PatchError("%s: no function %s in %s" % (pf.path, ed.target, package_name))
            if ref in touched:
                raise PatchError("%s: %s is already patched by %s" % (pf.path, ed.target, touched[ref]))
            touched[ref] = pf.name
            prefix, old_script, tail, o = _function_parts(stock_pkg, ref)
            if ed.kind == "replace":
                func = table.sym(stock_pkg, ref)
                table.owner_of(func)
                fc = FunctionCompiler(table, stock_pkg, func, table.pkg_names)
                fc.target_pkg = pkg
                try:
                    toks = lex(ed.body)
                    stmts, _ = fc.compile_body(toks)
                except CompileError as x:
                    raise PatchError("%s (%s): %s" % (pf.path, ed.target, x))
                script, mem = bytecode.encode(stmts)
            else:
                refs = disasm.RefNames(pkg)
                try:
                    _, script, mem = asm.assemble(ed.body, pkg, refs, add_names=True)
                except asm.AsmError as x:
                    raise PatchError("%s (%s): %s" % (pf.path, ed.target, x))
            body = bytearray(prefix + script + tail)
            struct.pack_into("<i", body, len(prefix) - 4, mem)  # ScriptSize is the last field before the script
            pkg.exports[ref - 1].data = bytes(body)
            report.append("%s: %s %s, script %d -> %d bytes" % (pf.name, ed.kind, ed.target, o["script_size"], mem))

    if not touched:
        raise PatchError("no patch applies to %s" % package_name)
    out = pkg.to_bytes()
    _verify(stock_pkg, out, touched)
    return ver111.encrypt(out, ver111.footer_of(raw)), report


def _verify(stock_pkg, out, touched):
    new = Package(out)
    if len(new.exports) != len(stock_pkg.exports) or new.names[:len(stock_pkg.names)] != stock_pkg.names:
        raise PatchError("verification failed: tables changed shape")
    none = new.names.index("None")
    for i, e in enumerate(new.exports):
        ref = i + 1
        old = stock_pkg.exports[i]
        if ref in touched:
            o = load.objects.parse(new, ref, lambda d, p, s: bytecode.decode(d, p, s, none)[1])
            if o["_end"] != e.size:
                raise PatchError("verification failed: patched %s does not parse cleanly" % new.path(ref))
        elif e.data != old.data or e.offset != old.offset:
            raise PatchError("verification failed: %s changed" % new.path(ref))


# ------------------------------------------------------------------------------------------------ install/restore

CLIENT_PROCESSES = ("l2.exe", "l2.bin")  # the launcher starts L2.exe, which runs the game as L2.bin


def client_running():
    try:
        out = subprocess.run(["tasklist", "/NH"], capture_output=True, text=True, timeout=20).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return True  # can't tell: assume it is, and refuse to write
    return any(line.split(" ", 1)[0] in CLIENT_PROCESSES for line in out.splitlines())


def read_manifest():
    if os.path.exists(MANIFEST):
        return json.load(open(MANIFEST, encoding="utf-8"))
    return {}


def install(patch_paths, dry_run=False):
    patches = [PatchFile(p) for p in patch_paths]
    by_pkg = {}
    for pf in patches:
        by_pkg.setdefault(pf.package, []).append(pf)
    built = {}
    lines = []
    for name, pfs in by_pkg.items():
        data, report = build(name, pfs)
        built[name] = data
        lines += report
        lines.append("%s: built and verified, sha256 %s" % (name, stock.sha256(data)))
    if dry_run:
        return lines + ["dry run: nothing written"]
    manifest = read_manifest()
    to_write = {n: d for n, d in built.items()
                if open(stock.client_path(n), "rb").read() != d}
    if to_write and client_running():
        raise PatchError("the client (L2.exe / L2.bin) is running; close it first")
    for name, data in built.items():
        stock.stock_bytes(name)  # makes sure the stock backup exists before we overwrite
        if name in to_write:
            with open(stock.client_path(name), "wb") as f:
                f.write(data)
            lines.append("installed %s" % stock.client_path(name))
        else:
            lines.append("%s is already this build; recorded it, wrote nothing" % name)
        manifest[name] = {"sha256": stock.sha256(data),
                          "patches": [os.path.relpath(p.path, stock.ROOT) for p in by_pkg[name]]}
    os.makedirs(stock.BACKUP, exist_ok=True)
    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"), indent=2)
    return lines


def restore(names=None):
    if client_running():
        raise PatchError("the client (L2.exe / L2.bin) is running; close it first")
    manifest = read_manifest()
    names = names or list(manifest)
    lines = []
    for name in names:
        bp = stock.backup_path(name)
        if not os.path.exists(bp):
            raise PatchError("no stock backup for %s" % name)
        stock.stock_bytes(name)  # verifies the backup's hash
        shutil.copy2(bp, stock.client_path(name))
        manifest.pop(name, None)
        lines.append("restored stock %s" % name)
    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"), indent=2)
    return lines


def status():
    manifest = read_manifest()
    lines = []
    for name in sorted(stock.STOCK_SHA256):
        cur = stock.sha256(open(stock.client_path(name), "rb").read())
        if cur == stock.STOCK_SHA256[name]:
            state = "stock"
        elif name in manifest and manifest[name]["sha256"] == cur:
            state = "patched: " + ", ".join(manifest[name]["patches"])
        else:
            state = "MODIFIED outside l2mod"
        if state != "stock":
            lines.append("%-18s %s" % (name, state))
    return lines or ["all client packages are stock"]
