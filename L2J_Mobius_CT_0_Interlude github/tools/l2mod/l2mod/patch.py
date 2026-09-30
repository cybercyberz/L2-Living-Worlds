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

A patch can also add a whole new class, from a source file next to the patch or inline:

    class PartyCmdWnd from PartyCmdWnd.uc

    class PartyCmdWnd
    {
    class PartyCmdWnd extends UICommonAPI;
    ...
    }

For the window layout, use `package interface.xdat` and these lines:

    set QuestTreeWnd.btnClose.anchor_x = 120          ; change a field (int, float or "string")
    clone QuestTreeWnd.btnClose as btnNav             ; copy a control inside its window, then set fields:
    set QuestTreeWnd.btnNav.anchor_x = 170
    remove QuestTreeWnd.txt324                        ; delete a control
    add window PartyCmdWnd from PartyWndOption        ; a new top-level window, scripted by class PartyCmdWnd
    copy QuestTreeWnd.btnClose to PartyCmdWnd as btnClose   ; a control from any window into another
    shortcut GamingState Alt+L = "ShowPartyCmdWnd"    ; a hotkey; scripts get it as EV_ShortcutCommand

For a .dat table (sysstring, npcname, itemname, questname, skillname, systemmsg), rows are picked by their key:
the id, or id/level for questname and skillname.

    package itemname-e.dat
    set 57 name = "Gold"                              ; change a field
    clone 57 as 60000                                 ; copy a row under a new id, then set its fields
    set 60000 description = "A token from the module."
    remove 60001

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


class ClassAdd:
    def __init__(self, name, source, where):
        self.name = name  # the class the patch adds
        self.source = source  # its full UnrealScript source
        self.where = where  # "file:line", for messages


class XdatOp:
    def __init__(self, op, path, value, line, extra=None):
        self.op = op  # set / clone / remove / add_window / copy / shortcut
        self.path = path
        self.value = value  # the value for set, the new name for clone, add_window and copy
        self.line = line
        self.extra = extra  # copy: the destination window; shortcut: the action text


def _brace_delta(line):
    """Braces opened minus closed on a source line, ignoring strings, names and // comments."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"|\'[^\'\n]*\'', "", line).split("//", 1)[0]
    return line.count("{") - line.count("}")


KEY_NAMES = {"alt": 18, "ctrl": 17, "shift": 16, "enter": 13, "esc": 27, "tab": 9, "space": 32, "pageup": 33,
             "pagedown": 34, "minus": 189, "equals": 187}


def parse_keys(text):
    """`Alt+L` -> [76, 18, 0]: the key first, then up to two modifiers, as the shortcut table stores them."""
    parts = [p.strip().lower() for p in text.split("+")]
    codes = []
    for p in parts:
        if p in KEY_NAMES:
            codes.append(KEY_NAMES[p])
        elif re.fullmatch(r"f([1-9]|1[0-2])", p):
            codes.append(111 + int(p[1:]))
        elif re.fullmatch(r"[a-z0-9]", p):
            codes.append(ord(p.upper()))
        else:
            raise ValueError("unknown key %r" % p)
    mods = [c for c in codes if c in (16, 17, 18)]
    keys = [c for c in codes if c not in (16, 17, 18)]
    if len(keys) != 1 or len(mods) > 2:
        raise ValueError("a shortcut is one key plus up to two of Alt, Ctrl and Shift")
    return keys + mods + [0] * (2 - len(mods))


class PatchFile:
    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.package = None
        self.edits = []
        self.classes = []
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
            if self.package and self.package.lower().endswith(".dat"):
                self.xdat_ops.append(self._parse_dat_line(s.split(";", 1)[0].strip(), i + 1))
                i += 1
                continue
            if self.package and self.package.lower().endswith(".xdat"):
                self.xdat_ops.append(self._parse_xdat_line(s.split(";", 1)[0].strip(), i + 1))
                i += 1
                continue
            m = re.fullmatch(r"class\s+([A-Za-z_]\w*)\s+from\s+(.+)", s)
            if m:
                name, rel = m.group(1), m.group(2).strip().strip('"')
                src = os.path.join(os.path.dirname(os.path.abspath(self.path)), rel)
                if not os.path.exists(src):
                    raise PatchError("%s:%d: no file %s" % (self.path, i + 1, src))
                with open(src, encoding="utf-8") as f:
                    self.classes.append(ClassAdd(name, f.read(), "%s:%d" % (self.path, i + 1)))
                i += 1
                continue
            m = re.fullmatch(r"class\s+([A-Za-z_]\w*)", s)
            if m:
                start = i + 1
                while start < len(lines) and not lines[start].strip():
                    start += 1
                if start >= len(lines) or lines[start].strip() != "{":
                    raise PatchError("%s:%d: `class %s` must be followed by a line with just `{`, or use "
                                     "`class %s from <file.uc>`" % (self.path, i + 1, m.group(1), m.group(1)))
                depth = 0
                body = []
                j = start + 1
                while j < len(lines):
                    if lines[j].strip() == "}" and depth == 0:
                        break
                    body.append(lines[j])
                    depth += _brace_delta(lines[j])
                    j += 1
                else:
                    raise PatchError("%s:%d: missing the closing `}`" % (self.path, i + 1))
                self.classes.append(ClassAdd(m.group(1), "\n".join(body) + "\n", "%s:%d" % (self.path, i + 1)))
                i = j + 1
                continue
            m = re.fullmatch(r"(replace|asm)\s+([A-Za-z_][\w.]*)", s)
            if not m:
                raise PatchError("%s:%d: expected `package`, `class`, `replace` or `asm`, got %r" % (
                    self.path, i + 1, s))
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

    def _parse_dat_line(self, s, line):
        m = re.fullmatch(r"set\s+([\d/]+)\s+(\w+)\s*=\s*(.+)", s)
        if m:
            key, field, raw = m.groups()
            try:
                value = json.loads(raw.strip())
            except ValueError:
                raise PatchError("%s:%d: can't read the value %s (use 12, 1.5 or \"text\")" % (self.path, line, raw))
            return XdatOp("set", (key, field), value, line)
        m = re.fullmatch(r"clone\s+([\d/]+)\s+as\s+([\d/]+)", s)
        if m:
            return XdatOp("clone", m.group(1), m.group(2), line)
        m = re.fullmatch(r"remove\s+([\d/]+)", s)
        if m:
            return XdatOp("remove", m.group(1), None, line)
        raise PatchError("%s:%d: expected set, clone or remove, got %r" % (self.path, line, s))

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
        m = re.fullmatch(r"add\s+window\s+(\w+)\s+from\s+(\w+)", s)
        if m:
            return XdatOp("add_window", m.group(2), m.group(1), line)
        m = re.fullmatch(r"copy\s+([\w.]+)\s+to\s+([\w.]+)\s+as\s+(\w+)", s)
        if m:
            return XdatOp("copy", m.group(1), m.group(3), line, m.group(2))
        m = re.fullmatch(r"shortcut\s+(\w+)\s+([\w+]+)\s*=\s*(\".*\")", s)
        if m:
            try:
                keys = parse_keys(m.group(2))
                action = json.loads(m.group(3))
            except ValueError as x:
                raise PatchError("%s:%d: %s" % (self.path, line, x))
            return XdatOp("shortcut", m.group(1), keys, line, action)
        raise PatchError("%s:%d: expected set, clone, remove, add window, copy or shortcut, got %r" % (
            self.path, line, s))


# ------------------------------------------------------------------------------------------------------ building

def _function_parts(pkg, ref):
    """(prefix bytes, script bytes, tail bytes, parsed object) of a Function export."""
    o = load.parse(pkg, ref)
    data = pkg.exports[ref - 1].data
    return data[:o["script_start"]], data[o["script_start"]:o["script_end"]], data[o["script_end"]:], o


def _rename_window(win, old, new):
    """A copied top-level window under a new name: every control names its owning window."""
    win["name"] = new
    win.raw_strings.pop("name", None)
    for c in win.walk():
        if c is not win and c.get("ownerWnd") == old:
            c["ownerWnd"] = new
            c.raw_strings.pop("ownerWnd", None)


def build_xdat(package_name, patches):
    """Apply layout edits to the stock interface.xdat. Returns (bytes, report lines)."""
    import copy
    from . import xdat
    stock_data = stock.stock_bytes(package_name)
    x = xdat.Xdat.read(stock_data)
    report = []
    touched = set()
    shortcut_states = set()
    for pf in patches:
        if pf.package.lower() != package_name.lower():
            continue
        for op in pf.xdat_ops:
            where = "%s:%d" % (pf.path, op.line)
            parts = op.path.split(".")
            if op.op in ("set", "clone", "remove"):
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
                elif op.op == "add_window":
                    if any(w.name == op.value for w in x.windows):
                        raise PatchError("%s: there's already a window %s" % (where, op.value))
                    new = copy.deepcopy(x.window(op.path))
                    _rename_window(new, op.path, op.value)
                    new["script"] = op.value  # the class a patch adds under the same name
                    x.windows.append(new)
                    touched.add(op.value)
                    report.append("%s: added window %s (from %s)" % (pf.name, op.value, op.path))
                elif op.op == "copy":
                    ent = x.find(op.path)
                    dest = x.find(op.extra)
                    if "children" not in dest:
                        raise PatchError("%s: %s can't hold controls" % (where, dest))
                    if any(c.name == op.value for c in dest["children"]):
                        raise PatchError("%s: %s already has a %s" % (where, dest, op.value))
                    new = copy.deepcopy(ent)
                    new["name"] = op.value
                    new.raw_strings.pop("name", None)
                    owner = op.extra.split(".")[0]
                    for c in new.walk():
                        c["ownerWnd"] = owner
                        c.raw_strings.pop("ownerWnd", None)
                    dest["children"].append(new)
                    touched.add(owner)
                    report.append("%s: copied %s to %s as %s" % (pf.name, op.path, op.extra, op.value))
                elif op.op == "shortcut":
                    sets = [sc for sc in x.shortcuts if sc["state"] == op.path]
                    if not sets:
                        raise PatchError("%s: no shortcut state %s (there are: %s)" % (
                            where, op.path, ", ".join(sc["state"] for sc in x.shortcuts)))
                    acts = sets[0]["actions"]
                    for a in acts:
                        if [a["key_1"], a["key_2"], a["key_3"]] == op.value:
                            raise PatchError("%s: that key already runs %r in %s" % (where, a["action"], op.path))
                    act = copy.deepcopy(acts[0])
                    act["key_1"], act["key_2"], act["key_3"] = op.value
                    act["action"] = op.extra
                    act.raw_strings.pop("action", None)
                    acts.append(act)
                    shortcut_states.add(op.path)
                    report.append("%s: shortcut %s %s -> %r" % (pf.name, op.path, op.value, op.extra))
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
    for sc in orig.shortcuts:  # shortcut sets we didn't add to are unchanged, and ours only grew
        mine = [t for t in y.shortcuts if t["name"] == sc["name"]][0]
        n = len(sc["actions"])
        if mine["actions"][:n] != sc["actions"] or (sc["state"] not in shortcut_states and len(mine["actions"]) != n):
            raise PatchError("verification failed: shortcuts of %s changed" % sc["state"])
    stock_names = {o.name for o in orig.windows}
    for w in y.windows:
        if w.name not in stock_names:
            for c in w.walk():
                if c is not w and c["ownerWnd"] in stock_names:
                    raise PatchError("verification failed: %s in new window %s belongs to %s" % (
                        c.name, w.name, c["ownerWnd"]))
    report.append("%s: built and verified, %d windows" % (package_name, len(y.windows)))
    return out, report


def build_dat(package_name, patches):
    """Apply row edits to a stock .dat table. Returns (encrypted bytes, report lines)."""
    import copy
    from . import dat
    raw = stock.stock_bytes(package_name)
    plain = dat.decrypt(raw)
    try:
        t = dat.Table.read(package_name, plain)
    except dat.DatError as x:
        raise PatchError(str(x))
    report = []

    def key_of(text, where):
        parts = [int(p) for p in text.split("/")]
        if len(parts) != len(t.key):
            raise PatchError("%s: %s rows are keyed by %s" % (where, t.name, "/".join(t.key)))
        return tuple(parts)

    def find(key, where):
        try:
            return t.find(*key)
        except KeyError:
            raise PatchError("%s: no %s row %s" % (where, t.name, "/".join(map(str, key))))

    touched = set()
    for pf in patches:
        if pf.package.lower() != package_name.lower():
            continue
        for op in pf.xdat_ops:
            where = "%s:%d" % (pf.path, op.line)
            if op.op == "set":
                key = key_of(op.path[0], where)
                field = op.path[1]
                row = find(key, where)
                if field not in row or field in t.key:
                    raise PatchError("%s: %s has no editable field %s (fields: %s)" % (
                        where, t.name, field, ", ".join(f for f, _ in t.fields if f not in t.key)))
                kind = t.kind_of(field)
                v = op.value
                if kind in ("ascf", "unicode") and not isinstance(v, str) or \
                        kind in ("u32", "i32", "u8", "rgba") and not isinstance(v, int) or \
                        kind == "f32" and not isinstance(v, (int, float)) or isinstance(kind, tuple) and \
                        not isinstance(v, list):
                    raise PatchError("%s: %s.%s needs a %s value" % (where, t.name, field, kind))
                old = row[field]
                row[field] = float(v) if kind == "f32" else v
                touched.add(key)
                report.append("%s: %s %s.%s = %r (was %r)" % (pf.name, t.name, "/".join(map(str, key)), field, v,
                                                              dat.float_of(old)))
            elif op.op == "clone":
                src = find(key_of(op.path, where), where)
                new_key = key_of(op.value, where)
                try:
                    t.find(*new_key)
                    raise PatchError("%s: %s row %s already exists" % (where, t.name, op.value))
                except KeyError:
                    pass
                row = copy.deepcopy(src)
                for k, v in zip(t.key, new_key):
                    row[k] = v
                t.rows.append(row)
                touched.add(new_key)
                report.append("%s: %s cloned %s as %s" % (pf.name, t.name, op.path, op.value))
            elif op.op == "remove":
                key = key_of(op.path, where)
                t.rows.remove(find(key, where))
                touched.add(key)
                report.append("%s: %s removed %s" % (pf.name, t.name, op.path))
    new_plain = t.to_bytes()
    out = dat.encrypt(new_plain, raw)
    # Verify: decrypts, parses, and every row we didn't touch is unchanged.
    check = dat.Table.read(package_name, dat.decrypt(out))
    before = {tuple(r[k] for k in t.key): r for r in dat.Table.read(package_name, plain).rows}
    for r in check.rows:
        key = tuple(r[k] for k in t.key)
        if key not in touched and before.get(key) != r:
            raise PatchError("verification failed: %s row %s changed" % (t.name, key))
    report.append("%s: built and verified, %d rows" % (package_name, len(check.rows)))
    return out, report


def build(package_name, patches, table=None):
    """Apply every edit in `patches` (PatchFile list, in order) to the stock package. Returns (encrypted bytes,
    report lines). Raises PatchError on any problem, before anything is written."""
    if package_name.lower().endswith(".xdat"):
        return build_xdat(package_name, patches)
    if package_name.lower().endswith(".dat"):
        return build_dat(package_name, patches)
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

    added = {}
    for pf in patches:
        if pf.package.lower() != package_name.lower():
            continue
        for ca in pf.classes:
            if ca.name.lower() in added:
                raise PatchError("%s: class %s is already added by %s" % (ca.where, ca.name, added[ca.name.lower()]))
            added[ca.name.lower()] = pf.name
            from .compiler.classgen import ClassGenError, add_class
            from .compiler.decl import ParseError
            source = ca.source.replace("\r\n", "\n").replace("\n", "\r\n")  # stock ScriptText is CRLF
            try:
                gen = add_class(table, pkg, source, package_name.rsplit(".", 1)[0])
            except (ClassGenError, CompileError, ParseError) as x:
                raise PatchError("%s (class %s): %s" % (ca.where, ca.name, x))
            if gen.decl.name.lower() != ca.name.lower():
                raise PatchError("%s: the source declares class %s, not %s" % (ca.where, gen.decl.name, ca.name))
            report.append("%s: added class %s (%d objects, %d functions)" % (
                pf.name, gen.decl.name, len(gen.objs), sum(1 for _ in gen.functions())))

    if not touched and not added:
        raise PatchError("no patch applies to %s" % package_name)
    out = pkg.to_bytes()
    _verify(stock_pkg, out, touched)
    return ver111.encrypt(out, ver111.footer_of(raw)), report


def _verify(stock_pkg, out, touched):
    """The package reads back; stock objects are unchanged except the patched functions; stock names and imports
    are unchanged (new ones only appended); every patched or added object parses to its exact size."""
    new = Package(out)
    n = len(stock_pkg.exports)
    if (len(new.exports) < n or new.names[:len(stock_pkg.names)] != stock_pkg.names
            or [i.serialize() for i in new.imports[:len(stock_pkg.imports)]]
            != [i.serialize() for i in stock_pkg.imports]):
        raise PatchError("verification failed: tables changed shape")
    none = new.names.index("None")
    for i, e in enumerate(new.exports):
        ref = i + 1
        old = stock_pkg.exports[i] if i < n else None
        if old is None or ref in touched:
            o = load.objects.parse(new, ref, lambda d, p, s: bytecode.decode(d, p, s, none)[1])
            if o["_end"] != e.size:
                raise PatchError("verification failed: patched %s does not parse cleanly" % new.path(ref))
        elif (e.data, e.offset, e.name, e.outer, e.class_ref, e.super_ref) != (
                old.data, old.offset, old.name, old.outer, old.class_ref, old.super_ref):
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
