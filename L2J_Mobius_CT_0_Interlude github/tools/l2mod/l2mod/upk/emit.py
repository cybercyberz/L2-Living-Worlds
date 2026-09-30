"""Write script objects: the inverse of `objects.parse`.

`serialize(pkg, o, script=b"")` takes the dict `objects.parse` returns (or one built the same way) and gives back the
object's serial data. Struct objects (Function, State, Class, Struct) take their bytecode as `script`; `o["script_size"]`
must already be its in-memory size.

Checked by a round trip of every script object in every client package (`tests/test_gates.py`), so the class compiler
can build new objects from dicts and trust the bytes.
"""
import struct

from .compact import write_ci, write_fstring
from .objects import CPF_NET, FUNC_NET, PROPERTY_CLASSES, RF_HAS_STACK

PROP_TYPE_CODES = {v: k for k, v in {
    1: "Byte", 2: "Int", 3: "Bool", 4: "Float", 5: "Object", 6: "Name", 7: "String", 8: "Class", 9: "Array",
    10: "Struct", 11: "Vector", 12: "Rotator", 13: "Str", 14: "Map", 15: "FixedArray",
}.items()}
FIXED_SIZES = {1: 0, 2: 1, 4: 2, 12: 3, 16: 4}


def _size_type(size):
    if size in FIXED_SIZES:
        return FIXED_SIZES[size]
    if size <= 0xFF:
        return 5
    if size <= 0xFFFF:
        return 6
    return 7


def tagged_properties(pkg, props):
    """Tagged properties, closed with `None`. Each prop is a dict as `read_tagged_properties` returns it; a missing
    `size_type` means the smallest encoding."""
    out = bytearray()
    for p in props:
        ptype = p["type"] if isinstance(p["type"], int) else PROP_TYPE_CODES[p["type"]]
        value = p["value"]
        size_type = p.get("size_type")
        if size_type is None:
            size_type = _size_type(len(value))
        is_array = p["bool"] if ptype == 3 else p.get("index", 0) != 0
        out += write_ci(pkg.name_index(p["name"]))
        out.append(ptype | (size_type << 4) | (0x80 if is_array else 0))
        if ptype == 10:
            out += write_ci(p["struct"])
        if size_type == 5:
            out.append(len(value))
        elif size_type == 6:
            out += struct.pack("<H", len(value))
        elif size_type == 7:
            out += struct.pack("<i", len(value))
        if is_array and ptype != 3:
            index = p["index"]
            if index < 0x80:
                out.append(index)
            elif index < 0x4000:
                out += struct.pack(">H", index | 0x8000)
            else:
                out += struct.pack(">I", index | 0xC0000000)
        out += value
    out += write_ci(pkg.name_index("None"))
    return bytes(out)


def _state_frame(o, flags):
    f = o.get("state_frame")
    if not flags & RF_HAS_STACK:
        return b""
    out = write_ci(f["node"]) + write_ci(f["state_node"]) + struct.pack("<Qi", f["probe_mask"], f["latent_action"])
    if f["node"] != 0:
        out += write_ci(f["offset"])
    return out


def serialize(pkg, o, script=b"", object_flags=0):
    """Serial data for the script object `o`. `object_flags` matters only for `RF_HasStack` (never set in stock)."""
    cls = o["class"]
    out = bytearray(_state_frame(o, object_flags))
    if cls != "Class":
        out += tagged_properties(pkg, o.get("props", []))

    if cls in PROPERTY_CLASSES:
        out += write_ci(o["super"]) + write_ci(o["next"])
        out += struct.pack("<iI", o["array_dim"], o["property_flags"])
        out += write_ci(o["category"])
        if o["property_flags"] & CPF_NET:
            out += struct.pack("<H", o["rep_offset"])
        if cls in ("ObjectProperty", "ClassProperty"):
            out += write_ci(o["property_class"])
            if cls == "ClassProperty":
                out += write_ci(o["meta_class"])
        elif cls == "StructProperty":
            out += write_ci(o["struct"])
        elif cls == "ByteProperty":
            out += write_ci(o["enum"])
        elif cls in ("ArrayProperty", "FixedArrayProperty"):
            out += write_ci(o["inner"])
            if cls == "FixedArrayProperty":
                out += struct.pack("<i", o["count"])
        elif cls == "DelegateProperty":
            out += write_ci(o["function"])
        elif cls == "MapProperty":
            out += write_ci(o["key"]) + write_ci(o["value"])
    elif cls == "Const":
        out += write_ci(o["super"]) + write_ci(o["next"]) + write_fstring(o["value"])
    elif cls == "Enum":
        out += write_ci(o["super"]) + write_ci(o["next"]) + write_ci(len(o["values"]))
        for v in o["values"]:
            out += write_ci(pkg.name_index(v))
    elif cls == "TextBuffer":
        out += struct.pack("<ii", o["pos"], o["top"]) + write_fstring(o["text"])
    elif cls in ("Function", "State", "Class", "Struct"):
        for k in ("super", "next", "script_text", "children", "friendly_name", "cpp_text"):
            out += write_ci(o[k])
        out += struct.pack("<iii", o["line"], o["text_pos"], o["script_size"])
        out += script
        if cls == "Function":
            out += struct.pack("<HBI", o["native"], o["precedence"], o["function_flags"])
            if o["function_flags"] & FUNC_NET:
                out += struct.pack("<H", o["rep_offset"])
        elif cls in ("State", "Class"):
            out += struct.pack("<QQHI", o["probe_mask"], o["ignore_mask"], o["label_table_offset"], o["state_flags"])
            if cls == "Class":
                out += struct.pack("<I", o["class_flags"]) + o["class_guid"]
                out += write_ci(len(o["dependencies"]))
                for dep, deep, crc in o["dependencies"]:
                    out += write_ci(dep) + struct.pack("<iI", deep, crc)
                out += write_ci(len(o["package_imports"]))
                for p in o["package_imports"]:
                    out += write_ci(p)
                out += write_ci(o["class_within"]) + write_ci(o["config_name"])
                out += write_ci(len(o["hide_categories"]))
                for h in o["hide_categories"]:
                    out += write_ci(h)
                out += tagged_properties(pkg, o["defaults"])
    else:
        raise ValueError("can't serialize a %s" % cls)
    return bytes(out)
