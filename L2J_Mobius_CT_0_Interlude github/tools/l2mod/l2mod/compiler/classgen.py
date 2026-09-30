"""The class compiler: a whole class from source to package objects.

    gen = ClassGen(table, pkg, decl, Append(pkg, "interface"))   # add a new class to an editable package
    gen.declare()          # every object, bodies still empty
    gen.compile_bodies()   # function and state code, against the symbols of the declared class
    gen.write()            # into the package

`InPlace` instead maps every object onto the stock export of the same path, so a stock class compiled from its
own source can be compared object by object with the stock bytes (the stage-6 gate, `classoracle.py`).

The layout rules (child-chain order, flags, positions) are the UE2 compiler's, found from the stock packages;
see NOTES.md, "Class compiler (stage 6)".
"""
from ..symbols import (CPF_COERCE, CPF_OPTIONAL, CPF_OUT, CPF_PARM, CPF_RETURN, FUNC_DEFINED, FUNC_DELEGATE,
                       FUNC_EVENT, FUNC_EXEC, FUNC_FINAL, FUNC_ITERATOR, FUNC_LATENT, FUNC_NATIVE, FUNC_OPERATOR,
                       FUNC_PREOPERATOR, FUNC_PRIVATE, FUNC_SIMULATED, FUNC_SINGULAR, FUNC_STATIC, ClassSym,
                       EnumSym, StructSym)
import struct

from ..upk import bytecode, emit
from ..upk.compact import write_ci, write_fstring
from ..upk.package import Export, Import
from .codegen import CompileError, FunctionCompiler
from .decl import ConstDecl, EnumDecl, FuncDecl, StateDecl, StructDecl, VarDecl

CPF_EDIT = 0x1
CPF_CONST = 0x2
CPF_TRANSIENT = 0x2000
CPF_CONFIG = 0x4000
CPF_LOCALIZED = 0x8000
CPF_EDITCONST = 0x20000
CPF_GLOBALCONFIG = 0x40000
CPF_NEEDCTORLINK = 0x400000
FUNC_PUBLIC = 0x20000  # every stock script function carries it
FUNC_PROTECTED = 0x80000

OBJ_FLAGS = 0x70004  # RF_Public | RF_LoadForClient | RF_LoadForServer | RF_LoadForEdit
CLASS_OBJ_FLAGS = 0xF0004
TEXT_OBJ_FLAGS = 0x340000
CLASS_FLAGS = 0x12  # CLASS_Compiled | CLASS_Parsed
CLASS_MODIFIERS = {"dynamicrecompile": 0x400000}
# Probe functions: a state that defines one sets bit (engine name index - 300) in its ProbeMask.
PROBES = ["Spawned", "Destroyed", "GainedChild", "LostChild", "Probe4", "Probe5", "Trigger", "UnTrigger", "Timer",
          "HitWall", "Falling", "Landed", "ZoneChange", "Touch", "UnTouch", "Bump", "BeginState", "EndState",
          "BaseChange", "Attach", "Detach"]

SIMPLE_PROPERTIES = {"int": "IntProperty", "bool": "BoolProperty", "float": "FloatProperty", "name": "NameProperty",
                     "string": "StrProperty", "byte": "ByteProperty", "pointer": "PointerProperty"}
VAR_FLAGS = {"config": CPF_CONFIG, "globalconfig": CPF_GLOBALCONFIG | CPF_CONFIG, "localized": CPF_LOCALIZED,
             "const": CPF_CONST, "editconst": CPF_EDITCONST, "transient": CPF_TRANSIENT}
FUNC_MODIFIERS = {"final": FUNC_FINAL, "simulated": FUNC_SIMULATED, "static": FUNC_STATIC, "native": FUNC_NATIVE,
                  "exec": FUNC_EXEC, "latent": FUNC_LATENT, "iterator": FUNC_ITERATOR, "singular": FUNC_SINGULAR,
                  "private": FUNC_PRIVATE, "protected": FUNC_PROTECTED}
FUNC_KINDS = {"function": 0, "event": FUNC_EVENT, "delegate": FUNC_DELEGATE, "operator": FUNC_OPERATOR,
              "preoperator": FUNC_OPERATOR | FUNC_PREOPERATOR, "postoperator": FUNC_OPERATOR}


class ClassGenError(Exception):
    pass


class Obj:
    """One object the class compiles to."""

    def __init__(self, path, cls, outer, name):
        self.path = path
        self.cls = cls  # "Function", "IntProperty", ...
        self.outer = outer  # Obj or None (the class itself)
        self.name = name
        self.ref = 0
        self.super_ref = 0  # the export's super (a Function's overridden parent, a Class's parent)
        self.flags = OBJ_FLAGS
        self.o = None  # the dict for emit.serialize
        self.script = b""
        self.decl = None


# ---------------------------------------------------------------------------------------------------- targets

class InPlace:
    """Every object is the stock export of the same path (the gate)."""

    def __init__(self, pkg):
        self.pkg = pkg

    def alloc(self, obj):
        try:
            return self.pkg.find(obj.path, obj.cls)
        except KeyError:
            raise ClassGenError("%s: no stock %s export" % (obj.path, obj.cls))

    def import_ref(self, pkg_name, path, cls):
        return _find_import(self.pkg, pkg_name + "." + path)


class Append:
    """New exports, and new imports and names as needed (a patch adding a class)."""

    def __init__(self, pkg):
        self.pkg = pkg

    def alloc(self, obj):
        pkg = self.pkg
        if obj.cls == "Class":
            class_ref = 0
        else:
            class_ref = _class_import(pkg, obj.cls)
        outer = obj.outer.ref if obj.outer is not None else 0
        e = Export(class_ref, obj.super_ref, outer, _name(pkg, obj.name, add=True), obj.flags, 0, 0)
        return pkg.add_export(e, b"")

    def import_ref(self, pkg_name, path, cls):
        r = _find_import(self.pkg, pkg_name + "." + path)
        if r:
            return r
        # Import the object and every outer it needs: Package, then Package.Class, then Package.Class.Member.
        parts = [pkg_name] + path.split(".")
        outer = 0
        for i in range(1, len(parts) + 1):
            sub = ".".join(parts[:i])
            r = _find_import(self.pkg, sub)
            if not r:
                if i == 1:
                    kind = ("Core", "Package")
                elif i == len(parts):
                    kind = ("Core", cls)
                else:
                    kind = ("Core", "Class")
                r = self.pkg.add_import(Import(_name(self.pkg, kind[0], add=True), _name(self.pkg, kind[1], add=True),
                                               outer, _name(self.pkg, parts[i - 1], add=True)))
            outer = r
        return outer


def _find_import(pkg, path):
    index = getattr(pkg, "_import_index", None)
    if index is None or index[0] != len(pkg.imports):
        index = (len(pkg.imports), {pkg.path(-(i + 1)).lower(): -(i + 1) for i in range(len(pkg.imports))})
        pkg._import_index = index
    return index[1].get(path.lower(), 0)


def _class_import(pkg, cls):
    for i, imp in enumerate(pkg.imports):
        if pkg.names[imp.class_name] == "Class" and pkg.names[imp.object_name] == cls:
            return -(i + 1)
    raise ClassGenError("the package has no import of Core.%s" % cls)


def _name(pkg, text, add=False):
    """A name's index the way FName finds it: case-insensitive, the first entry wins."""
    try:
        return pkg.names.index(text)
    except ValueError:
        pass
    low = text.lower()
    for i, n in enumerate(pkg.names):
        if n.lower() == low:
            return i
    if add:
        return pkg.name_index(text, add=True)
    raise ClassGenError("name %s is not in the package" % text)


# ---------------------------------------------------------------------------------------------------- the class

class ClassGen:
    def __init__(self, table, pkg, decl, target, pkg_name="interface"):
        self.table = table
        self.pkg = pkg
        self.decl = decl
        self.target = target
        self.pkg_name = pkg_name
        self.objs = []
        self.by_path = {}
        self.cls = None  # the ClassSym, once declared
        self.parent = table.cls(decl.parent) if decl.parent else None
        if decl.parent and self.parent is None:
            raise ClassGenError("unknown parent class %s" % decl.parent)

    # --------------------------------------------------------------------------------------------- references

    def ref_of(self, sym):
        """The reference to a symbol from our package: an export of ours, or an import."""
        if sym.pkg is self.pkg or self.table.pkg_names.get(id(sym.pkg)) == self.pkg_name:
            return sym.ref
        owner = self.table.pkg_names[id(sym.pkg)]
        return self.target.import_ref(owner, sym.path, sym.pkg.class_name(sym.ref))

    def new(self, path, cls, outer, name):
        o = Obj(path, cls, outer, name)
        self.objs.append(o)
        self.by_path[path.lower()] = o
        return o

    # ---------------------------------------------------------------------------------------------- lookups

    def own_struct(self, name):
        for s in self.decl.structs:
            if s.name.lower() == name.lower():
                return s
        return None

    def own_enum(self, name):
        for e in self.decl.enums:
            if e.name.lower() == name.lower():
                return e
        return None

    def lookup(self, kind, name):
        """A struct or enum visible from this class: its own, then its parents', then any loaded one."""
        chain = list(self.parent.chain()) if self.parent is not None else []
        for c in chain:
            if isinstance(c, ClassSym):
                s = c.members(kind).get(name.lower())
                if s is not None:
                    return s
        if kind == "enums":
            for en in self.table.all_enums():
                if en.name.lower() == name.lower():
                    return en
        return None

    def struct_needs_ctor_link(self, st):
        if isinstance(st, StructDecl):
            return any(self.var_needs_ctor_link(f) for f in st.fields)
        if st.name.lower() in ("vector", "rotator", "plane", "coords", "color", "box", "scale", "sphere"):
            return False
        return any(v.flags & CPF_NEEDCTORLINK for v in st.fields.values()) or (
            st.super is not None and self.struct_needs_ctor_link(st.super))

    def var_needs_ctor_link(self, v):
        t = v.type
        if isinstance(t, tuple):
            return t[0] == "array"
        low = t.lower()
        if low == "string":
            return True
        st = self.own_struct(t) or (None if low in SIMPLE_PROPERTIES else self.lookup("structs", t))
        return st is not None and self.struct_needs_ctor_link(st)

    # ------------------------------------------------------------------------------------------- declaration

    def declare(self):
        d = self.decl
        cls = self.new(d.name, "Class", None, d.name)
        cls.flags = CLASS_OBJ_FLAGS
        cls.super_ref = self.ref_of(self.parent) if self.parent is not None else 0
        text = self.new(d.name + ".ScriptText", "TextBuffer", cls, "ScriptText")
        text.flags = TEXT_OBJ_FLAGS

        members = []  # the class's direct children in source order
        for item in d.items:
            if isinstance(item, ConstDecl):
                members.append(self._const(cls, item))
            elif isinstance(item, EnumDecl):
                members.append(self._enum(cls, item))
            elif isinstance(item, StructDecl):
                members.append(self._struct(cls, item))
            elif isinstance(item, VarDecl):
                members.append(self._var(cls, d.name + "." + item.name, item))
            elif isinstance(item, FuncDecl):
                members.append(self._func(cls, d.name, item))
            elif isinstance(item, StateDecl):
                members.append(self._state(cls, item))
        for o in self.objs:
            o.ref = self.target.alloc(o)
        self._members = members
        return self

    def _const(self, outer, c):
        o = self.new(outer.path + "." + c.name, "Const", outer, c.name)
        o.o = {"class": "Const", "props": [], "super": 0, "value": c.value}
        o.decl = c
        return o

    def _enum(self, outer, e):
        o = self.new(outer.path + "." + e.name, "Enum", outer, e.name)
        o.o = {"class": "Enum", "props": [], "super": 0, "values": list(e.values)}
        o.decl = e
        return o

    def _struct(self, outer, s):
        o = self.new(outer.path + "." + s.name, "Struct", outer, s.name)
        o.decl = s
        o.fields = [self._var(o, o.path + "." + f.name, f) for f in s.fields]
        return o

    def _var(self, outer, path, v, extra_flags=0):
        o = self.new(path, None, outer, v.name)
        o.decl = v
        o.extra_flags = extra_flags
        o.cls, o.inner = self._property_class(o, v)
        return o

    def _property_class(self, o, v):
        """(property class, inner Obj or None). Resolving the referenced class, struct or enum waits for
        `write`, when every export has a reference."""
        t = v.type
        if isinstance(t, tuple):
            if t[0] == "array":
                inner = self.new(o.path + "." + v.name, None, o, v.name)
                inner.decl = VarDecl(t[1], v.name, None, [], None, v.line, v.pos)
                inner.extra_flags = 0
                inner.cls, inner.inner = self._property_class(inner, inner.decl)
                return "ArrayProperty", inner
            return "ClassProperty", None
        low = t.lower()
        if low in SIMPLE_PROPERTIES:
            return SIMPLE_PROPERTIES[low], None
        if self.own_enum(t) or self.lookup("enums", t):
            return "ByteProperty", None
        if self.own_struct(t) or self.lookup("structs", t):
            return "StructProperty", None
        if self.table.cls(t) is not None or t.lower() == self.decl.name.lower():
            return "ObjectProperty", None
        raise ClassGenError("line %d: unknown type %s" % (v.line, t))

    def _func(self, outer, prefix, f):
        o = self.new(outer.path + "." + f.name, "Function", outer, f.name)
        o.decl = f
        o.params = [self._var(o, o.path + "." + p.name, p, CPF_PARM) for p in f.params]
        o.ret = None
        if f.ret is not None:
            rv = VarDecl(f.ret, "ReturnValue", None, [], None, f.line, f.pos)
            o.ret = self._var(o, o.path + ".ReturnValue", rv, CPF_PARM | CPF_OUT | CPF_RETURN)
        o.locals = [self._var(o, o.path + "." + v.name, v) for v in f.locals]
        return o

    def _state(self, outer, s):
        o = self.new(outer.path + "." + s.name, "State", outer, s.name)
        o.decl = s
        o.funcs = [self._func(o, o.path, f) for f in s.funcs]
        return o

    # ------------------------------------------------------------------------------------------------ writing

    def _chain(self, objs):
        """Links objs in order through `next`; returns the first ref."""
        for a, b in zip(objs, objs[1:] + [None]):
            a.next_ref = b.ref if b is not None else 0
        return objs[0].ref if objs else 0

    def _type_ref(self, t, v):
        """The ref a property's class/struct/enum field points at."""
        if isinstance(t, tuple):
            t = t[1]
        own = self.own_struct(t) or self.own_enum(t)
        if own is not None:
            return self.by_path[(self.decl.name + "." + own.name).lower()].ref
        low = t.lower()
        if low == self.decl.name.lower():
            return self.by_path[low].ref
        for kind in ("structs", "enums"):
            s = self.lookup(kind, t)
            if s is not None:
                return self.ref_of(s)
        c = self.table.cls(t)
        if c is not None:
            return self.ref_of(c)
        raise ClassGenError("line %d: unknown type %s" % (v.line, t))

    def _property(self, o):
        v = o.decl
        flags = o.extra_flags
        if v.category is not None:
            flags |= CPF_EDIT
        for m in v.modifiers:
            flags |= VAR_FLAGS.get(m, 0)
            if o.extra_flags & CPF_PARM:
                flags |= {"optional": CPF_OPTIONAL, "out": CPF_OUT, "coerce": CPF_COERCE}.get(m, 0)
        if self.var_needs_ctor_link(v):
            flags |= CPF_NEEDCTORLINK
        dim = 1
        if v.dim is not None:
            dim = v.dim if isinstance(v.dim, int) else self._const_int(v.dim, v)
        category = _name(self.pkg, "None")
        if v.category:
            category = _name(self.pkg, v.category, add=True)
        elif v.category == "":
            category = _name(self.pkg, self.decl.name, add=True)
        r = {"class": o.cls, "props": [], "super": 0, "next": getattr(o, "next_ref", 0), "array_dim": dim,
             "property_flags": flags, "category": category}
        if o.cls == "ObjectProperty":
            r["property_class"] = self._type_ref(v.type, v)
        elif o.cls == "ClassProperty":
            r["property_class"] = self.ref_of(self.table.cls("Class"))
            r["meta_class"] = self._type_ref(v.type, v)
        elif o.cls == "StructProperty":
            r["struct"] = self._type_ref(v.type, v)
        elif o.cls == "ByteProperty":
            r["enum"] = 0 if v.type.lower() == "byte" else self._type_ref(v.type, v)
        elif o.cls == "ArrayProperty":
            r["inner"] = o.inner.ref
            self._property(o.inner)
        o.o = r

    def _const_int(self, name, v):
        for c in self.decl.consts:
            if c.name.lower() == name.lower():
                return int(c.value.strip())
        cs = self.parent.lookup("consts", name) if self.parent is not None else None
        if cs is not None:
            return int(cs.value.strip())
        raise ClassGenError("line %d: unknown array size %s" % (v.line, name))

    def _overridden(self, f, state):
        """The function this one overrides: the same name further up (in a state: the class's own first)."""
        name = f.name.lower()
        if state is not None:
            for fo in self._members:
                if fo.cls == "Function" and fo.name.lower() == name:
                    return fo.ref
        if self.parent is not None:
            if state is not None:
                for c in self.parent.chain():
                    if isinstance(c, ClassSym):
                        st = c.members("states").get(state.name.lower())
                        if st is not None and name in st.funcs:
                            return self.ref_of(st.funcs[name])
            s = self.parent.lookup("funcs", f.name)
            if s is not None:
                return self.ref_of(s)
        return 0

    def _function(self, o, state):
        f = o.decl
        for v in o.params + ([o.ret] if o.ret else []) + o.locals:
            pass
        children = o.params + ([o.ret] if o.ret else []) + o.locals
        first = self._chain(children)
        for v in children:
            self._property(v)
        flags = FUNC_PUBLIC | FUNC_KINDS.get(f.kind, 0)
        for m in f.modifiers:
            if isinstance(m, tuple):
                m = m[0]
            flags |= FUNC_MODIFIERS.get(m, 0)
        if f.body is not None:
            flags |= FUNC_DEFINED
        native = 0
        for m in f.modifiers:
            if isinstance(m, tuple) and m[0] == "native" and m[1]:
                native = m[1]
        o.super_ref = self._overridden(f, state)
        o.o = {"class": "Function", "props": [], "super": o.super_ref, "next": getattr(o, "next_ref", 0),
               "script_text": 0, "children": first, "friendly_name": _name(self.pkg, f.name, add=True),
               "cpp_text": 0, "line": f.body_line, "text_pos": f.body_pos, "script_size": 0, "native": native,
               "precedence": f.operator_precedence or 0, "function_flags": flags}

    def write_declarations(self, defaults=None):
        """Fill every object's dict (bodies still empty). `defaults` are the class's tagged defaults."""
        d = self.decl
        cls = self.objs[0]
        members = self._members
        # The class's children chain, as the two-pass UE2 compiler builds it. First pass, in source order: a
        # const, enum or struct goes in front; a variable goes right after the last variable added (or in front
        # if it's the first). Second pass: each function and state goes in front, in source order.
        chain = []
        last_var = -1
        for m in members:
            if m.cls in ("Function", "State"):
                continue
            if m.cls in ("Const", "Enum", "Struct"):
                chain.insert(0, m)
                if last_var >= 0:
                    last_var += 1
            else:  # a variable goes right after the last variable added, or first
                last_var += 1
                chain.insert(last_var, m)
        for m in members:
            if m.cls in ("Function", "State"):
                chain.insert(0, m)
        members = chain
        self._chain(members)
        self._chain_order = members
        for m in members:
            if m.cls == "Const" or m.cls == "Enum":
                m.o["next"] = m.next_ref
            elif m.cls == "Struct":
                first = self._chain(m.fields)
                for fo in m.fields:
                    self._property(fo)
                m.o = {"class": "Struct", "props": [], "super": 0, "next": m.next_ref, "script_text": 0,
                       "children": first, "friendly_name": _name(self.pkg, m.name, add=True), "cpp_text": 0,
                       "line": 0, "text_pos": 0, "script_size": 0}
            elif m.cls == "Function":
                self._function(m, None)
            elif m.cls == "State":
                funcs = list(reversed(m.funcs))
                first = self._chain(funcs)
                for fo in m.funcs:
                    self._function(fo, m.decl)
                sd = m.decl
                m.o = {"class": "State", "props": [], "super": 0, "next": m.next_ref, "script_text": 0,
                       "children": first, "friendly_name": _name(self.pkg, m.name, add=True), "cpp_text": 0,
                       "line": sd.end_line, "text_pos": sd.end_pos, "script_size": 0,
                       "probe_mask": self._probe_mask(m.funcs), "ignore_mask": 0xFFFFFFFFFFFFFFFF,
                       "label_table_offset": 0xFFFF, "state_flags": 0}
            else:
                self._property(m)
        text = self.objs[1]
        text.o = {"class": "TextBuffer", "props": [], "pos": 0, "top": 0, "text": d.text}
        cls.o = {"class": "Class", "super": cls.super_ref, "next": 0, "script_text": text.ref,
                 "children": members[0].ref if members else 0, "friendly_name": _name(self.pkg, d.name, add=True),
                 "cpp_text": 0, "line": -1, "text_pos": -1, "script_size": 0, "probe_mask": 0,
                 "ignore_mask": 0xFFFFFFFFFFFFFFFF, "label_table_offset": 0xFFFF, "state_flags": 0,
                 "class_flags": self._class_flags(), "class_guid": b"\0" * 16,
                 "dependencies": [(cls.ref, 1, 0)] + ([(cls.super_ref, 1, 0)] if cls.super_ref else []),
                 "package_imports": [_name(self.pkg, n, add=True) for n in ("Interface", "NWindow", "Engine", "Core")],
                 "class_within": self.target.import_ref("Core", "Object", "Class"),
                 "config_name": _name(self.pkg, "System", add=True), "hide_categories": [],
                 "defaults": defaults or []}
        return self

    @staticmethod
    def _probe_mask(funcs):
        mask = 0
        low = [p.lower() for p in PROBES]
        for f in funcs:
            if f.name.lower() in low:
                mask |= 1 << low.index(f.name.lower())
        return mask

    def _class_flags(self):
        flags = CLASS_FLAGS
        for m, _ in self.decl.modifiers:
            if m not in CLASS_MODIFIERS:
                raise ClassGenError("class modifier %s isn't supported" % m)
            flags |= CLASS_MODIFIERS[m]
        return flags

    # ---------------------------------------------------------------------------------------------- defaults

    def compile_defaults(self):
        """The class's `defaultproperties` as tagged properties, in field order (this class's variables in chain
        order, then each parent's), each property's elements by index."""
        order = {}
        for m in self._chain_order:
            if m.cls not in ("Function", "State", "Const", "Enum", "Struct"):
                order[m.name.lower()] = (0, len(order))
        depth = 1
        for c in (self.parent.chain() if self.parent is not None else []):
            if isinstance(c, ClassSym):
                for i, v in enumerate(self.table.field_chain(c.pkg, c.o["children"])):
                    if v is not None and hasattr(v, "flags") and not hasattr(v, "params"):
                        order.setdefault(v.name.lower(), (depth, i))
                depth += 1
        props = []
        for dd in self.decl.defaults:
            key = dd.name.lower()
            if key not in order:
                raise ClassGenError("line %d: defaultproperties: no variable %s" % (dd.line, dd.name))
            props.append((order[key], dd.index or 0, self._default_value(dd)))
        props.sort(key=lambda p: (p[0], p[1]))
        return [p[2] for p in props]

    def _var_type(self, name):
        """(property class, enum symbol or decl) for a variable of this class or a parent."""
        for m in self._chain_order:
            if m.name.lower() == name.lower() and m.decl is not None and isinstance(m.decl, VarDecl):
                t = m.decl.type
                en = None
                if m.cls == "ByteProperty" and isinstance(t, str) and t.lower() != "byte":
                    en = self.own_enum(t) or self.lookup("enums", t)
                return m.cls, en, m.name
        v = self.parent.lookup("vars", name) if self.parent is not None else None
        if v is None:
            return None, None, name
        return v.pkg.class_name(v.ref), (v.type.enum if v.type.kind == "byte" else None), v.name

    def _default_value(self, dd):
        cls, enum, name = self._var_type(dd.name)
        toks = dd.value
        text = "".join(t.text for t in toks)
        p = {"name": name, "index": dd.index or 0, "struct": None, "bool": None}
        neg = len(toks) == 2 and toks[0].is_("-")
        num = toks[-1].value if toks and toks[-1].kind in ("int", "float") else None
        if num is not None and neg:
            num = -num
        if cls == "IntProperty" and num is not None:
            p.update(type="Int", value=struct.pack("<i", int(num)))
        elif cls == "FloatProperty" and num is not None:
            p.update(type="Float", value=struct.pack("<f", float(num)))
        elif cls == "BoolProperty" and text.lower() in ("true", "false"):
            p.update(type="Bool", value=b"", bool=text.lower() == "true")
        elif cls == "ByteProperty" and (num is not None or enum is not None):
            if num is None:
                values = [v.lower() for v in enum.values]
                if text.lower() not in values:
                    raise ClassGenError("line %d: %s has no value %s" % (dd.line, enum.name, text))
                num = values.index(text.lower())
            p.update(type="Byte", value=bytes([int(num)]))
        elif cls == "StrProperty" and len(toks) == 1 and toks[0].kind == "string":
            p.update(type="Str", value=write_fstring(toks[0].value))
        elif cls == "NameProperty" and len(toks) == 1 and toks[0].kind in ("name", "ident", "string"):
            n = toks[0].value if toks[0].kind != "ident" else toks[0].text
            p.update(type="Name", value=write_ci(_name(self.pkg, n, add=True)))
        else:
            raise ClassGenError("line %d: defaultproperties: can't set %s (%s) to %s" % (dd.line, dd.name, cls, text))
        return p

    # ------------------------------------------------------------------------------------------------ bodies

    def functions(self):
        for m in self._members:
            if m.cls == "Function":
                yield m
            elif m.cls == "State":
                yield from m.funcs

    def compile_bodies(self, sym_pkg=None):
        """Compile every body against the symbol table. `sym_pkg` is the package the table reads the class from
        (the stock package in place, or the edited one when appending)."""
        sym_pkg = sym_pkg or self.pkg
        for f in self.functions():
            if f.decl.body is None:
                if not f.o["function_flags"] & FUNC_NATIVE:  # a plain declaration still gets `return;`
                    f.script, f.o["script_size"] = b"\x04\x0b", 2  # EX_Return(EX_Nothing)
                continue
            func = self.table.sym(sym_pkg, f.ref)
            self.table.owner_of(func)
            fc = FunctionCompiler(self.table, sym_pkg, func, self.table.pkg_names)
            if sym_pkg is not self.pkg or isinstance(self.target, Append):
                fc.target_pkg = self.pkg  # new names may be added
            try:
                stmts, _ = fc.compile_body(f.decl.body)
            except CompileError as x:
                raise ClassGenError("%s: %s" % (f.path, x))
            f.script, f.o["script_size"] = bytecode.encode(stmts)
        for m in self._members:
            if m.cls == "State":
                m.script, m.o["script_size"] = self._state_code(m)
        return self

    def _state_code(self, m):
        if m.decl.code:
            raise ClassGenError("%s: state code (labels) isn't supported yet" % m.path)
        return b"\x08", 1  # EX_Stop: a state with no code of its own

    def serialized(self):
        """{ref: bytes} for every object."""
        return {o.ref: emit.serialize(self.pkg, o.o, o.script) for o in self.objs}

    def write(self):
        """Store every object into its export (Append mode)."""
        for o in self.objs:
            e = self.pkg.exports[o.ref - 1]
            e.super_ref = o.super_ref
            e.data = emit.serialize(self.pkg, o.o, o.script)
        return self


def add_class(table, pkg, source, pkg_name="interface"):
    """Compile `source` as a new class into the editable package `pkg`. Returns the ClassGen."""
    from .decl import parse_class_decl
    decl = parse_class_decl(source)
    for i, e in enumerate(pkg.exports):
        if e.class_ref == 0 and e.outer == 0 and pkg.names[e.name].lower() == decl.name.lower():
            raise ClassGenError("%s already has a class %s" % (pkg_name, decl.name))
    gen = ClassGen(table, pkg, decl, Append(pkg), pkg_name)
    gen.declare()
    gen.write_declarations()
    gen.objs[0].o["defaults"] = gen.compile_defaults()
    gen.write()  # declarations first, so the symbol table can read the new class
    table.adopt(pkg, pkg_name, gen.objs[0].ref)
    gen.compile_bodies(sym_pkg=pkg)
    return gen.write()
