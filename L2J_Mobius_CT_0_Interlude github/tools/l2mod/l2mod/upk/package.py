"""Unreal Engine 2 package (version 123, Lineage II licensee 30): read, edit and write.

The writer never moves an untouched object. Every client package is laid out as:

    header | generations | name table | object data | import table | export table

When something changes, the changed or new objects' data is appended after the original data region, followed by a
new name table (only if names were added), the import table and the export table. The original bytes stay where they
were, so absolute offsets inside untouched objects (lazy arrays in texture and sound data) stay valid. Saving an
unmodified package gives back identical bytes.
"""
import struct

from .compact import Reader, read_ci, write_ci

TAG = 0x9E2A83C1
HEADER = struct.Struct("<IHHIiiiiii")  # tag, version, licensee, flags, names, name@, exports, export@, imports, import@


class Import:
    __slots__ = ("class_package", "class_name", "package", "object_name")

    def __init__(self, class_package, class_name, package, object_name):
        self.class_package = class_package  # name index
        self.class_name = class_name  # name index
        self.package = package  # object reference (usually an import, negative)
        self.object_name = object_name  # name index

    def serialize(self):
        return (write_ci(self.class_package) + write_ci(self.class_name) + struct.pack("<i", self.package)
                + write_ci(self.object_name))


class Export:
    __slots__ = ("class_ref", "super_ref", "outer", "name", "flags", "size", "offset", "_data", "dirty")

    def __init__(self, class_ref, super_ref, outer, name, flags, size, offset):
        self.class_ref = class_ref  # object reference: 0 = Class, <0 import, >0 export
        self.super_ref = super_ref
        self.outer = outer  # object reference (0 = the package itself)
        self.name = name  # name index
        self.flags = flags
        self.size = size
        self.offset = offset
        self._data = None
        self.dirty = False

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = bytes(value)
        self.dirty = True

    def serialize(self):
        out = (write_ci(self.class_ref) + write_ci(self.super_ref) + struct.pack("<i", self.outer)
               + write_ci(self.name) + struct.pack("<I", self.flags) + write_ci(self.size))
        if self.size > 0:
            out += write_ci(self.offset)
        return out


class Package:
    def __init__(self, plain):
        """Parse decrypted package bytes."""
        self.raw = bytes(plain)
        d = self.raw
        (tag, self.version, self.licensee, self.package_flags, name_count, self.name_offset, export_count,
         self.export_offset, import_count, self.import_offset) = HEADER.unpack_from(d, 0)
        if tag != TAG:
            raise ValueError("not an Unreal package")
        self.guid = d[36:52]
        gen_count = struct.unpack_from("<i", d, 52)[0]
        self.generations = [struct.unpack_from("<ii", d, 56 + 8 * i) for i in range(gen_count)]
        header_end = 56 + 8 * gen_count

        self.names = []
        self.name_flags = []
        r = Reader(d, self.name_offset)
        for _ in range(name_count):
            n = r.ci()
            self.names.append(r.raw(n)[:-1].decode("latin1"))
            self.name_flags.append(r.u32())
        self.names_end = r.p

        self.imports = []
        r = Reader(d, self.import_offset)
        for _ in range(import_count):
            cp = r.ci()
            cn = r.ci()
            pk = r.i32()
            on = r.ci()
            self.imports.append(Import(cp, cn, pk, on))
        self.imports_end = r.p

        self.exports = []
        r = Reader(d, self.export_offset)
        for _ in range(export_count):
            cls = r.ci()
            sup = r.ci()
            outer = r.i32()
            name = r.ci()
            flags = r.u32()
            size = r.ci()
            offset = r.ci() if size > 0 else 0
            e = Export(cls, sup, outer, name, flags, size, offset)
            e._data = d[offset:offset + size]
            self.exports.append(e)
        self.exports_end = r.p

        # The layout the writer relies on.
        with_data = [e for e in self.exports if e.size > 0]
        self.data_start = min((e.offset for e in with_data), default=self.names_end)
        self.data_end = max((e.offset + e.size for e in with_data), default=self.names_end)
        # Stock files have the name table first; files this writer made may have it after the data.
        names_ok = self.names_end <= self.data_start or self.name_offset >= self.data_end
        layout_ok = (self.name_offset >= header_end and names_ok and self.data_end <= self.import_offset
                     and self.imports_end <= self.export_offset and self.exports_end == len(d))
        if not layout_ok:
            raise ValueError("unexpected package layout")
        self._orig_name_count = name_count

    # ------------------------------------------------------------------------------------------------ references

    def obj(self, ref):
        """The Import or Export an object reference points at (None for 0)."""
        if ref < 0:
            return self.imports[-ref - 1]
        if ref > 0:
            return self.exports[ref - 1]
        return None

    def obj_name(self, ref):
        if ref == 0:
            return "None"
        o = self.obj(ref)
        return self.names[o.object_name if ref < 0 else o.name]

    def class_name(self, ref):
        """The class of the object that `ref` points at, as a name."""
        if ref < 0:
            return self.names[self.imports[-ref - 1].class_name]
        e = self.exports[ref - 1]
        return "Class" if e.class_ref == 0 else self.obj_name(e.class_ref)

    def outer_of(self, ref):
        if ref < 0:
            return self.imports[-ref - 1].package
        return self.exports[ref - 1].outer

    def path(self, ref):
        """Dotted path of an object: `QuestTreeWnd.OnClickButton` or, for imports, `Core.Object.Log`."""
        parts = []
        while ref != 0:
            parts.append(self.obj_name(ref))
            ref = self.outer_of(ref)
        return ".".join(reversed(parts))

    def find(self, path, class_name=None):
        """The export reference (1-based) whose path is `path` (case-insensitive, like the engine)."""
        index = getattr(self, "_path_index", None)
        if index is None or index[0] != len(self.exports):
            by_path = {}
            for i in range(len(self.exports)):
                by_path.setdefault(self.path(i + 1).lower(), []).append(i + 1)
            index = self._path_index = (len(self.exports), by_path)
        for ref in index[1].get(path.lower(), []):
            if class_name is None or self.class_name(ref) == class_name:
                return ref
        raise KeyError(path)

    def find_import(self, path):
        for i in range(len(self.imports)):
            if self.path(-(i + 1)) == path:
                return -(i + 1)
        raise KeyError(path)

    def children(self, ref):
        return [i + 1 for i, e in enumerate(self.exports) if e.outer == ref]

    # ---------------------------------------------------------------------------------------------------- editing

    def name_index(self, name, add=False):
        try:
            return self.names.index(name)
        except ValueError:
            if not add:
                raise
        self.names.append(name)
        self.name_flags.append(0x00070010)  # RF_TagImp | RF_LoadForClient | RF_LoadForServer | RF_LoadForEdit
        return len(self.names) - 1

    def add_export(self, export, data):
        export.data = data
        self.exports.append(export)
        return len(self.exports)

    def add_import(self, imp):
        self.imports.append(imp)
        return -len(self.imports)

    # ---------------------------------------------------------------------------------------------------- writing

    def modified(self):
        return (len(self.names) != self._orig_name_count or any(e.dirty for e in self.exports)
                or self._import_table() != self.raw[self.import_offset:self.imports_end]
                or self._export_table_unchanged() is False)

    def _import_table(self):
        return b"".join(i.serialize() for i in self.imports)

    def _export_table_unchanged(self):
        return b"".join(e.serialize() for e in self.exports) == self.raw[self.export_offset:self.exports_end]

    def to_bytes(self):
        d = self.raw
        names_changed = len(self.names) != self._orig_name_count
        dirty = [e for e in self.exports if e.dirty]
        if not names_changed and not dirty:
            imports = self._import_table()
            exports = b"".join(e.serialize() for e in self.exports)
            if (imports == d[self.import_offset:self.imports_end]
                    and exports == d[self.export_offset:self.exports_end]):
                return d  # untouched: identical bytes

        out = bytearray(d[:self.import_offset])  # header, names, all original data (and any slack before imports)
        for e in dirty:
            e.size = len(e.data)
            e.offset = len(out) if e.size else 0
            out += e.data
        name_offset = self.name_offset
        if names_changed:
            name_offset = len(out)
            for n, f in zip(self.names, self.name_flags):
                raw = n.encode("latin1") + b"\0"
                out += write_ci(len(raw)) + raw + struct.pack("<I", f)
        import_offset = len(out)
        out += self._import_table()
        export_offset = len(out)
        out += b"".join(e.serialize() for e in self.exports)

        HEADER.pack_into(out, 0, TAG, self.version, self.licensee, self.package_flags, len(self.names), name_offset,
                         len(self.exports), export_offset, len(self.imports), import_offset)
        if self.generations:
            # The last generation records the counts the package was saved with.
            struct.pack_into("<ii", out, 56 + 8 * (len(self.generations) - 1), len(self.exports), len(self.names))
        return bytes(out)


def ref_bytes(ref):
    return write_ci(ref)


def read_ref(d, p):
    return read_ci(d, p)
