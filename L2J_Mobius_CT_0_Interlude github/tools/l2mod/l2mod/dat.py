"""Client .dat tables (Interlude): read, edit and write.

Every table is a uint32 row count, the rows, then the string "SafePackage". Field layouts were worked out from the
published L2ClientDat structure definitions (format only) and are proven by an exact round trip of every stock
table they cover.

Field kinds:
    u32 / i32 / f32   4 bytes, little endian
    u8                1 byte
    ascf              FString: compact length (negative = UTF-16), null-terminated text
    unicode           int32 byte length, then UTF-16LE text (no terminator)
    rgba              uint32 colour
    ("list", kind)    compact count, then that many values
"""
import struct

from .crypto import ver41x
from .upk.compact import Reader, write_ci, write_fstring

TABLES = {
    "sysstring": {"key": ("id",), "fields": [("id", "u32"), ("text", "ascf")]},
    "npcname": {"key": ("id",), "fields": [("id", "u32"), ("name", "ascf"), ("title", "ascf"),
                                           ("title_color", "rgba")]},
    "itemname": {"key": ("id",), "fields": [
        ("id", "u32"), ("name", "unicode"), ("additional_name", "unicode"), ("description", "ascf"),
        ("popup", "i32"), ("set_ids", "ascf"), ("set_bonus_desc", "ascf"), ("set_extra_id", "ascf"),
        ("set_extra_desc", "ascf"), ("unknown_1", "u8"), ("unknown_2", "u8"), ("set_enchant_count", "u32"),
        ("set_enchant_effect", "ascf")]},
    "questname": {"key": ("id", "level"), "fields": [
        ("tag", "u32"), ("id", "u32"), ("level", "u32"), ("title", "ascf"), ("sub_name", "ascf"),
        ("desc", "ascf"), ("goal_ids", ("list", "u32")), ("goal_nums", ("list", "u32")),
        ("target_x", "f32"), ("target_y", "f32"), ("target_z", "f32"), ("lvl_min", "u32"), ("lvl_max", "u32"),
        ("quest_type", "u32"), ("entity_name", "ascf"), ("get_item_in_quest", "u32"), ("unk_1", "u32"),
        ("unk_2", "u32"), ("start_npc_id", "u32"), ("start_npc_x", "f32"), ("start_npc_y", "f32"),
        ("start_npc_z", "f32"), ("requirement", "ascf"), ("intro", "ascf"), ("class_limit", ("list", "i32")),
        ("have_item", ("list", "i32")), ("clan_pet_quest", "u32"), ("req_quest_complete", "u32"),
        ("unk_3", "u32"), ("area_id", "u32")]},
    "skillname": {"key": ("id", "level"), "fields": [
        ("id", "u32"), ("level", "u32"), ("name", "ascf"), ("desc", "ascf"), ("enchant_name", "ascf"),
        ("enchant_desc", "ascf")]},
    "systemmsg": {"key": ("id",), "fields": [
        ("id", "u32"), ("unk_0", "u32"), ("message", "ascf"), ("group", "u32"), ("color", "rgba"),
        ("sound", "ascf"), ("voice", "ascf"), ("win", "u32"), ("font", "u32"), ("lftime", "u32"),
        ("bkg", "u32"), ("anim", "u32"), ("scrnmsg", "ascf"), ("type", "ascf")]},
}
TRAILER = write_fstring("SafePackage")


class DatError(Exception):
    pass


def table_of(filename):
    """sysstring-e.dat -> "sysstring"."""
    base = filename.lower().rsplit(".", 1)[0]
    base = base.rsplit("-", 1)[0] if "-" in base else base
    if base not in TABLES:
        raise DatError("no schema for %s (known: %s)" % (filename, ", ".join(sorted(TABLES))))
    return base


class _Str(str):
    """A string that remembers its original encoding, so unchanged strings write back identically."""
    raw = None


def _read(r, kind):
    if kind in ("u32", "rgba"):
        return r.u32()
    if kind == "i32":
        return r.i32()
    if kind == "f32":
        return r.raw(4)  # kept as bytes so every float round-trips exactly; see Row.get
    if kind == "u8":
        return r.u8()
    if kind == "ascf":
        start = r.p
        s = _Str(r.fstring())
        s.raw = r.d[start:r.p]
        return s
    if kind == "unicode":
        n = r.i32()
        return r.raw(n).decode("utf-16-le")
    if isinstance(kind, tuple) and kind[0] == "list":
        return [_read(r, kind[1]) for _ in range(r.ci())]
    raise AssertionError(kind)


def _write(out, kind, v):
    if kind in ("u32", "rgba"):
        out += struct.pack("<I", v)
    elif kind == "i32":
        out += struct.pack("<i", v)
    elif kind == "f32":
        out += v if isinstance(v, (bytes, bytearray)) else struct.pack("<f", v)
    elif kind == "u8":
        out.append(v)
    elif kind == "ascf":
        raw = getattr(v, "raw", None)
        out += raw if raw is not None and isinstance(v, _Str) else write_fstring(v)
    elif kind == "unicode":
        b = v.encode("utf-16-le")
        out += struct.pack("<i", len(b)) + b
    elif isinstance(kind, tuple) and kind[0] == "list":
        out += write_ci(len(v))
        for x in v:
            _write(out, kind[1], x)
    else:
        raise AssertionError(kind)


class Table:
    def __init__(self, name, rows, fields, key):
        self.name = name
        self.rows = rows  # list of dicts
        self.fields = fields
        self.key = key

    @classmethod
    def read(cls, filename, plain):
        name = table_of(filename)
        spec = TABLES[name]
        r = Reader(plain)
        rows = []
        for _ in range(r.u32()):
            rows.append({f: _read(r, k) for f, k in spec["fields"]})
        tail = plain[r.p:]
        if tail != TRAILER:
            raise DatError("%s: %d unexpected bytes after the rows (schema wrong?)" % (filename, len(tail)))
        return cls(name, rows, spec["fields"], spec["key"])

    def to_bytes(self):
        out = bytearray(struct.pack("<I", len(self.rows)))
        for row in self.rows:
            for f, k in self.fields:
                _write(out, k, row[f])
        return bytes(out + TRAILER)

    def find(self, *key):
        for row in self.rows:
            if tuple(row[k] for k in self.key) == tuple(key):
                return row
        raise KeyError(key)

    def kind_of(self, field):
        for f, k in self.fields:
            if f == field:
                return k
        raise KeyError(field)


def float_of(v):
    return struct.unpack("<f", v)[0] if isinstance(v, (bytes, bytearray)) else v


# ---------------------------------------------------------------------------------------------------- files

def decrypt(raw):
    """This client's .dat files use the community l2encdec key (the one its L2.bin carries)."""
    return ver41x.decrypt(raw, ver41x.L2ENCDEC_MODULUS, ver41x.L2ENCDEC_DECRYPT_EXPONENT)


def encrypt(plain, original_raw=None):
    """Encrypt for this client. If `plain` is unchanged, the original file is returned as is."""
    if original_raw is not None and decrypt(original_raw) == plain:
        return original_raw
    return ver41x.encrypt(plain, ver41x.L2ENCDEC_MODULUS, ver41x.L2ENCDEC_ENCRYPT_EXPONENT)
