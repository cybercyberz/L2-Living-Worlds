"""Symbol table across client packages: classes, variables, functions, operators, structs, enums and consts.

Everything comes from the compiled packages themselves, not from the source text, so types and flags are exactly what
the engine uses. Imports are followed into the package that defines them (Core, Engine, NWindow, ...).
"""
from . import load
from .upk import objects

# Property flags
CPF_OPTIONAL = 0x10
CPF_PARM = 0x80
CPF_OUT = 0x100
CPF_SKIP = 0x200
CPF_RETURN = 0x400
CPF_COERCE = 0x800

# Function flags
FUNC_FINAL = 0x1
FUNC_DEFINED = 0x2
FUNC_ITERATOR = 0x4
FUNC_LATENT = 0x8
FUNC_PREOPERATOR = 0x10
FUNC_SINGULAR = 0x20
FUNC_NET = 0x40
FUNC_SIMULATED = 0x100
FUNC_EXEC = 0x200
FUNC_NATIVE = 0x400
FUNC_EVENT = 0x800
FUNC_OPERATOR = 0x1000
FUNC_STATIC = 0x2000
FUNC_PRIVATE = 0x40000
FUNC_DELEGATE = 0x100000

PACKAGE_FILES = {}  # lowercase package name -> file name, filled from the stock list


def _package_file(name):
    if not PACKAGE_FILES:
        from . import stock
        for f in stock.stock_names():
            PACKAGE_FILES[f.rsplit(".", 1)[0].lower()] = f
    return PACKAGE_FILES[name.lower()]


class Type:
    """A variable's type. kind is one of: byte int bool float name string object class struct array delegate
    pointer map fixed vector rotator none."""
    __slots__ = ("kind", "cls", "struct", "inner", "enum", "meta")

    def __init__(self, kind, cls=None, struct=None, inner=None, enum=None, meta=None):
        self.kind = kind
        self.cls = cls  # ClassSym for object/class
        self.struct = struct  # StructSym
        self.inner = inner  # Type for arrays
        self.enum = enum  # EnumSym for bytes
        self.meta = meta  # ClassSym, the class a class<...> variable holds

    def __repr__(self):
        if self.kind == "object":
            return "object(%s)" % (self.cls.name if self.cls else "?")
        if self.kind == "struct":
            return "struct(%s)" % self.struct.name
        if self.kind == "array":
            return "array<%r>" % self.inner
        if self.kind == "class":
            return "class<%s>" % (self.meta.name if self.meta else "?")
        return self.kind

    def same(self, other):
        if other is None or self.kind != other.kind:
            return False
        if self.kind == "struct":
            return self.struct is other.struct
        if self.kind == "array":
            return self.inner.same(other.inner)
        return True


class Sym:
    def __init__(self, pkg, ref):
        self.pkg = pkg  # the package that defines it
        self.ref = ref
        self.name = pkg.names[pkg.exports[ref - 1].name]
        self.path = pkg.path(ref)


class VarSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self.flags = o["property_flags"]
        self.array_dim = o["array_dim"]
        self._table = table
        self._o = o
        self._type = None
        self.owner = None

    @property
    def type(self):
        if self._type is None:
            self._type = self._table.type_of(self.pkg, self.ref, self._o)
        return self._type

    @property
    def is_parm(self):
        return bool(self.flags & CPF_PARM)

    @property
    def is_return(self):
        return bool(self.flags & CPF_RETURN)

    @property
    def optional(self):
        return bool(self.flags & CPF_OPTIONAL)

    @property
    def out(self):
        return bool(self.flags & CPF_OUT)

    @property
    def coerce(self):
        return bool(self.flags & CPF_COERCE)

    def __repr__(self):
        return "Var(%s: %r)" % (self.path, self.type)


class FuncSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self.flags = o["function_flags"]
        self.native = o["native"]
        self.precedence = o["precedence"]
        self.friendly = pkg.names[o["friendly_name"]]
        self.super_ref = pkg.exports[ref - 1].super_ref
        self._table = table
        self._children = o["children"]
        self._params = None
        self.owner = None  # ClassSym or StateSym

    def _load(self):
        if self._params is None:
            self._params, self._locals, self._ret = [], [], None
            for v in self._table.field_chain(self.pkg, self._children):
                if not isinstance(v, VarSym):
                    continue
                if v.is_return:
                    self._ret = v
                elif v.is_parm:
                    self._params.append(v)
                else:
                    self._locals.append(v)

    @property
    def params(self):
        self._load()
        return self._params

    @property
    def locals(self):
        self._load()
        return self._locals

    @property
    def ret(self):
        self._load()
        return self._ret

    def has(self, flag):
        return bool(self.flags & flag)

    def __repr__(self):
        return "Func(%s%s)" % (self.path, " native %d" % self.native if self.native else "")


class StructSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self.super_ref = pkg.exports[ref - 1].super_ref
        self._table = table
        self._children = o["children"]
        self._fields = None
        self.order = []

    @property
    def fields(self):
        if self._fields is None:
            self._fields = {}
            for v in self._table.field_chain(self.pkg, self._children):
                if isinstance(v, VarSym):
                    self._fields[v.name.lower()] = v
                    self.order.append(v)
                    v.owner = self
        return self._fields

    @property
    def super(self):
        return self._table.resolve(self.pkg, self.super_ref) if self.super_ref else None

    def field(self, name):
        s = self
        while s is not None:
            v = s.fields.get(name.lower())
            if v:
                return v
            s = s.super
        return None


class ConstSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self.value = o["value"]


class EnumSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self.values = o["values"]


class ClassSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self.table = table
        self.o = o
        self.flags = o["class_flags"]
        self.super_ref = pkg.exports[ref - 1].super_ref
        self._super = None
        self._members = None

    def _load(self):
        if self._members is not None:
            return
        self._members = {k: {} for k in ("vars", "funcs", "structs", "consts", "enums", "states")}
        kinds = [(VarSym, "vars"), (FuncSym, "funcs"), (StructSym, "structs"), (ConstSym, "consts"),
                 (EnumSym, "enums"), (StateSym, "states")]
        for child in self.pkg.children(self.ref):
            s = self.table.sym(self.pkg, child)
            for k, attr in kinds:
                if isinstance(s, k):
                    self._members[attr][s.name.lower()] = s
                    s.owner = self

    def members(self, kind):
        self._load()
        return self._members[kind]

    @property
    def super(self):
        if self._super is None and self.super_ref:
            self._super = self.table.resolve(self.pkg, self.super_ref)
        return self._super

    def chain(self):
        c = self
        while c is not None:
            yield c
            c = c.super

    def is_a(self, other):
        return any(c is other for c in self.chain())

    def lookup(self, kind, name):
        for c in self.chain():
            if not isinstance(c, ClassSym):
                continue
            s = c.members(kind).get(name.lower())
            if s is not None:
                return s
        return None

    def __repr__(self):
        return "Class(%s)" % self.path


class StateSym(Sym):
    def __init__(self, table, pkg, ref, o):
        super().__init__(pkg, ref)
        self._table = table
        self._funcs = None

    @property
    def funcs(self):
        if self._funcs is None:
            self._funcs = {}
            for child in self.pkg.children(self.ref):
                s = self._table.sym(self.pkg, child)
                if isinstance(s, FuncSym):
                    self._funcs[s.name.lower()] = s
                    s.owner = self
        return self._funcs


class IntrinsicClass:
    """A class built into the engine with no script export (Core.Class, Core.Package, ...)."""

    def __init__(self, path):
        self.path = path
        self.name = path.rsplit(".", 1)[-1]
        self.pkg = None
        self.super = None

    def chain(self):
        yield self

    def is_a(self, other):
        return other is self

    def lookup(self, kind, name):
        return None

    def __repr__(self):
        return "Intrinsic(%s)" % self.path


class SymbolTable:
    def __init__(self):
        self._syms = {}
        self._classes = {}  # lowercase class name -> ClassSym (first package wins, like the engine)
        self._loaded = set()
        self._operators = None
        self._intrinsic = {}
        self.pkg_names = {}  # id(Package) -> package name as imports spell it ("Core", "NWindow")
        self._enums = None

    # ------------------------------------------------------------------------------------------------- loading

    def package(self, name):
        pkg = load.package(_package_file(name))
        self.pkg_names.setdefault(id(pkg), _package_file(name).rsplit(".", 1)[0])
        if name.lower() not in self._loaded:
            self._loaded.add(name.lower())
            for i, e in enumerate(pkg.exports):
                if e.class_ref == 0 and e.outer == 0:
                    self._classes.setdefault(pkg.names[e.name].lower(), (pkg, i + 1))
        return pkg

    def load_all(self, names=("Core", "Engine", "NWindow", "interface")):
        for n in names:
            self.package(n)
        return self

    def sym(self, pkg, ref):
        key = (id(pkg), ref)
        if key in self._syms:
            return self._syms[key]
        self._syms[key] = None  # breaks cycles; filled below
        cls = pkg.class_name(ref)
        o = load.parse(pkg, ref)
        s = None
        if cls in objects.PROPERTY_CLASSES:
            s = VarSym(self, pkg, ref, o)
        elif cls == "Function":
            s = FuncSym(self, pkg, ref, o)
        elif cls == "Struct":
            s = StructSym(self, pkg, ref, o)
        elif cls == "Const":
            s = ConstSym(self, pkg, ref, o)
        elif cls == "Enum":
            s = EnumSym(self, pkg, ref, o)
        elif cls == "Class":
            s = ClassSym(self, pkg, ref, o)
        elif cls == "State":
            s = StateSym(self, pkg, ref, o)
        self._syms[key] = s
        return s

    def resolve(self, pkg, ref):
        """The symbol a reference in `pkg` points at, following imports into their own packages."""
        if ref > 0:
            return self.sym(pkg, ref)
        if ref == 0:
            return None
        path = pkg.path(ref)
        parts = path.split(".")
        other = self.package(parts[0])
        try:
            target = other.find(".".join(parts[1:]))
        except KeyError:
            if path not in self._intrinsic:
                self._intrinsic[path] = IntrinsicClass(path)
            return self._intrinsic[path]
        return self.sym(other, target)

    def cls(self, name):
        hit = self._classes.get(name.lower())
        if hit is None:
            return None
        return self.sym(*hit)

    def all_enums(self):
        if self._enums is None:
            self._enums = []
            for pkg_name in sorted(self._loaded):
                pkg = self.package(pkg_name)
                for i in range(len(pkg.exports)):
                    if pkg.class_name(i + 1) == "Enum":
                        self._enums.append(self.sym(pkg, i + 1))
        return self._enums

    def owner_of(self, sym):
        """Make sure `sym.owner` is set, by loading its outer's members."""
        if getattr(sym, "owner", None) is None and sym.pkg is not None:
            outer = sym.pkg.exports[sym.ref - 1].outer
            if outer:
                o = self.sym(sym.pkg, outer)
                if isinstance(o, ClassSym):
                    o.members("funcs")
                elif isinstance(o, StateSym):
                    o.funcs
        return sym.owner

    def field_chain(self, pkg, first):
        out = []
        ref = first
        while ref:
            s = self.resolve(pkg, ref)
            out.append(s)
            e = pkg.exports[ref - 1] if ref > 0 else None
            if e is None:
                break
            o = load.parse(pkg, ref)
            ref = o["next"]
        return out

    # --------------------------------------------------------------------------------------------------- types

    def type_of(self, pkg, ref, o):
        cls = o["class"]
        simple = {"IntProperty": "int", "BoolProperty": "bool", "FloatProperty": "float", "NameProperty": "name",
                  "StrProperty": "string", "StringProperty": "string", "PointerProperty": "pointer"}
        if cls in simple:
            return Type(simple[cls])
        if cls == "ByteProperty":
            return Type("byte", enum=self.resolve(pkg, o["enum"]) if o["enum"] else None)
        if cls == "ObjectProperty":
            return Type("object", cls=self.resolve(pkg, o["property_class"]))
        if cls == "ClassProperty":
            return Type("class", cls=self.resolve(pkg, o["property_class"]), meta=self.resolve(pkg, o["meta_class"]))
        if cls == "StructProperty":
            st = self.resolve(pkg, o["struct"])
            kind = {"vector": "vector", "rotator": "rotator"}.get(st.name.lower(), "struct")
            return Type(kind, struct=st)
        if cls == "ArrayProperty":
            inner_o = load.parse(pkg, o["inner"]) if o["inner"] > 0 else None
            inner = self.type_of(pkg, o["inner"], inner_o) if inner_o else Type("none")
            return Type("array", inner=inner)
        if cls == "DelegateProperty":
            return Type("delegate")
        return Type(cls)

    # ----------------------------------------------------------------------------------------------- operators

    def operator(self, name, kind):
        ops = self.operators()
        hit = ops.get((name, kind))
        if hit is None:
            low = name.lower()
            for (n, k), fs in ops.items():
                if k == kind and n.lower() == low:
                    return fs
        return hit

    def operators(self):
        """{(friendly name, arity): [FuncSym]} for every operator in Object and its subclasses we loaded."""
        if self._operators is None:
            ops = {}
            for pkg_name in list(self._loaded):
                pkg = self.package(pkg_name)
                for i, e in enumerate(pkg.exports):
                    if pkg.class_name(i + 1) != "Function":
                        continue
                    o = load.parse(pkg, i + 1)
                    if not o["function_flags"] & FUNC_OPERATOR:
                        continue
                    f = self.sym(pkg, i + 1)
                    arity = len(f.params)
                    kind = "pre" if f.has(FUNC_PREOPERATOR) else ("post" if arity == 1 else "bin")
                    ops.setdefault((f.friendly, kind), []).append(f)
            self._operators = ops
        return self._operators
