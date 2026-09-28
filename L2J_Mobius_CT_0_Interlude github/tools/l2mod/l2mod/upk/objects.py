"""Parse the script objects of a v123 / licensee 30 package.

Every parser returns a dict of fields plus `_end`, the position where parsing stopped. A parse is only trusted when
`_end` equals the object's size: the stage-1 gate checks that for every script object in every client package.
"""
from .compact import Reader

# Object flags
RF_HAS_STACK = 0x02000000

# Property flags
CPF_NET = 0x00000020

# Function flags
FUNC_NET = 0x00000040

PROPERTY_CLASSES = {
    "ByteProperty", "IntProperty", "BoolProperty", "FloatProperty", "ObjectProperty", "NameProperty",
    "StringProperty", "ClassProperty", "ArrayProperty", "StructProperty", "StrProperty", "MapProperty",
    "FixedArrayProperty", "DelegateProperty", "PointerProperty",
}
STRUCT_CLASSES = {"Function", "State", "Class", "Struct"}
SCRIPT_CLASSES = PROPERTY_CLASSES | STRUCT_CLASSES | {"Const", "Enum", "TextBuffer"}

# Tagged property types (low nibble of the info byte)
PROP_TYPES = {
    1: "Byte", 2: "Int", 3: "Bool", 4: "Float", 5: "Object", 6: "Name", 7: "String", 8: "Class", 9: "Array",
    10: "Struct", 11: "Vector", 12: "Rotator", 13: "Str", 14: "Map", 15: "FixedArray",
}


def read_state_frame(r, flags):
    if not flags & RF_HAS_STACK:
        return None
    frame = {"node": r.ci(), "state_node": r.ci(), "probe_mask": r.u64(), "latent_action": r.i32()}
    if frame["node"] != 0:
        frame["offset"] = r.ci()
    return frame


def read_tagged_properties(r, pkg):
    """Tagged properties up to `None`. Values are kept raw."""
    props = []
    while True:
        name = r.ci()
        if pkg.names[name] == "None":
            return props
        info = r.u8()
        ptype = info & 0x0F
        size_type = (info >> 4) & 0x07
        is_array = bool(info & 0x80)
        struct_name = r.ci() if ptype == 10 else None
        size = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}.get(size_type)
        if size is None:
            size = {5: r.u8, 6: r.u16, 7: r.i32}[size_type]()
        index = 0
        if is_array and ptype != 3:
            b = r.u8()
            if b & 0x80 == 0:
                index = b
            elif b & 0xC0 == 0x80:
                index = ((b & 0x7F) << 8) | r.u8()
            else:
                index = ((b & 0x3F) << 24) | (r.u8() << 16) | (r.u8() << 8) | r.u8()
        value = r.raw(size)
        props.append({"name": pkg.names[name], "type": PROP_TYPES.get(ptype, ptype), "struct": struct_name,
                      "index": index, "bool": is_array if ptype == 3 else None, "value": value})


def _field(r, o):
    o["super"] = r.ci()
    o["next"] = r.ci()


def _struct(r, o):
    _field(r, o)
    o["script_text"] = r.ci()
    o["children"] = r.ci()
    o["friendly_name"] = r.ci()
    o["cpp_text"] = r.ci()
    o["line"] = r.i32()
    o["text_pos"] = r.i32()
    o["script_size"] = r.i32()
    o["script_start"] = r.p


def parse(pkg, ref, walk_script=None):
    """Parse export `ref`. `walk_script(data, pos, memory_size)` must return the position after the bytecode; without
    it, the rest of a struct is not parsed and `_end` is where the script starts."""
    e = pkg.exports[ref - 1]
    cls = pkg.class_name(ref)
    r = Reader(e.data)
    o = {"class": cls, "name": pkg.names[e.name]}
    o["state_frame"] = read_state_frame(r, e.flags)
    if cls != "Class":
        o["props"] = read_tagged_properties(r, pkg)

    if cls in PROPERTY_CLASSES:
        _field(r, o)
        o["array_dim"] = r.i32()
        o["property_flags"] = r.u32()
        o["category"] = r.ci()
        if o["property_flags"] & CPF_NET:
            o["rep_offset"] = r.u16()
        if cls in ("ObjectProperty", "ClassProperty"):
            o["property_class"] = r.ci()
            if cls == "ClassProperty":
                o["meta_class"] = r.ci()
        elif cls == "StructProperty":
            o["struct"] = r.ci()
        elif cls == "ByteProperty":
            o["enum"] = r.ci()
        elif cls in ("ArrayProperty", "FixedArrayProperty"):
            o["inner"] = r.ci()
            if cls == "FixedArrayProperty":
                o["count"] = r.i32()
        elif cls == "DelegateProperty":
            o["function"] = r.ci()
        elif cls == "MapProperty":
            o["key"] = r.ci()
            o["value"] = r.ci()
    elif cls == "Const":
        _field(r, o)
        o["value"] = r.fstring()
    elif cls == "Enum":
        _field(r, o)
        o["values"] = [pkg.names[r.ci()] for _ in range(r.ci())]
    elif cls == "TextBuffer":
        o["pos"] = r.i32()
        o["top"] = r.i32()
        o["text"] = r.fstring()
    elif cls in STRUCT_CLASSES:
        _struct(r, o)
        if walk_script is None:
            o["_end"] = r.p
            o["_partial"] = True
            return o
        r.p = walk_script(e.data, r.p, o["script_size"])
        o["script_end"] = r.p
        if cls == "Function":
            o["native"] = r.u16()
            o["precedence"] = r.u8()
            o["function_flags"] = r.u32()
            if o["function_flags"] & FUNC_NET:
                o["rep_offset"] = r.u16()
        elif cls in ("State", "Class"):
            o["probe_mask"] = r.u64()
            o["ignore_mask"] = r.u64()
            o["label_table_offset"] = r.u16()
            o["state_flags"] = r.u32()
            if cls == "Class":
                o["class_flags"] = r.u32()
                o["class_guid"] = r.raw(16)
                o["dependencies"] = [(r.ci(), r.i32(), r.u32()) for _ in range(r.ci())]
                o["package_imports"] = [r.ci() for _ in range(r.ci())]
                o["class_within"] = r.ci()
                o["config_name"] = r.ci()
                o["hide_categories"] = [r.ci() for _ in range(r.ci())]
                o["defaults"] = read_tagged_properties(r, pkg)
    o["_end"] = r.p
    return o
