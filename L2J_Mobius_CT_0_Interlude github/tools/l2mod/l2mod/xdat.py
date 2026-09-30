"""interface.xdat (Interlude): the layout of every UI window and control.

The field layout follows acmi's MIT-licensed xdat_editor schema for Interlude ("ct0"). It was read for the format
only; nothing of it is used or run. It is checked by a byte-for-byte round trip of the stock file.

The file isn't encrypted. Scalars are 4-byte little-endian ints (bools and enums are ints too) or floats; strings
are FStrings (compact length, then null-terminated text; a negative length means UTF-16).

    x = Xdat.read(data)
    w = x.window("QuestTreeWnd")
    w.get_child("chkNpcPosBox")["anchor_x"]
    x.to_bytes()
"""
import struct

from .upk.compact import Reader, write_ci, write_fstring

# Field kinds: s = string, i = int, f = float, b = bool (int), e = enum (int), c = colour (int)
DEFAULT_PROPERTY = "DEFAULT"  # custom layout, see _read_default
SCHEMA = {
    "Window": [("s", "unk100"), ("s", "backTex"), ("s", "script"), ("s", "state")]
    + [("i", "unk%d" % n) for n in range(104, 120)] + [("f", "unk120"), ("f", "unk121")]
    + [("i", "unk%d" % n) for n in range(122, 129)] + [("s", "unk129")]
    + [("i", "unk%d" % n) for n in range(130, 136)] + [("s", "unk136"), ("i", "unk137"), ("i", "unk138"),
                                                       ("s", "unk139"), ("children", "children")],
    "BarCtrl": [("s", "foreTexture"), ("s", "backTexture"), ("i", "uSize"), ("i", "vSize")],
    "Button": [("s", "normalTex"), ("s", "pushedTex"), ("s", "highlightTex"), ("s", "dropTex"), ("i", "buttonName"),
               ("i", "noHighlight"), ("i", "defaultSoundOn"), ("i", "disableTime")],
    "ChatWindow": [("i", "lineGap")],
    "CheckBox": [("i", "titleIndex"), ("b", "checked"), ("b", "leftAligned"), ("i", "maxWidth"),
                 ("s", "checkTexture"), ("s", "unCheckTexture"), ("s", "disableTexture"),
                 ("s", "disableCheckTexture")],
    "ComboBox": [("list:ComboBoxElement", "values")],
    "EditBox": [("e", "type"), ("i", "maxLength"), ("i", "showCursor"), ("b", "chatMarkOn")],
    "EffectButton": [("i", "type"), ("s", "normalTex"), ("s", "pushedTex"), ("s", "highlightTex"),
                     ("s", "effectTex1"), ("s", "effectTex2")],
    "FishViewportWindow": [("s", n) for n in ("texBack", "texClock", "texFishHPBar", "texFishHPBarBack",
                                              "texFishFakeHPBarWarning", "texFishingEffect", "texIconPumping",
                                              "texIconReeling")],
    "HtmlCtrl": [("s", "viewType")],
    "InvenWeight": [],
    "ItemWindow": [("i", n) for n in ("col", "row", "maxItemNum", "iconWidth", "iconHeight", "gapX", "gapY",
                                      "offsetX", "offsetY", "backgroundItemWidth", "backgroundItemHeight")]
    + [("s", "backgroundItemTex"), ("i", "selectedItemWidth"), ("i", "selectedItemHeight"),
       ("s", "selectedItemTex"), ("i", "unselectedItemWidth"), ("i", "unselectedItemHeight"),
       ("s", "unselectedItemTex"), ("i", "noSelectItem"), ("i", "noItemDrag"), ("i", "buttonClick"),
       ("i", "useCoolTime"), ("i", "noScroll"), ("s", "outLineUp"), ("s", "outLineDown")],
    "ListCtrl": [("i", "unk100"), ("i", "unk101"), ("i", "unk102"), ("i", "unk103"), ("i", "unk104"),
                 ("list:ListElement", "values")],
    "MinimapCtrl": [("b", n) for n in ("showTime", "showTown", "showGrid", "showMyLocMark", "showMyLocText",
                                       "showSSQText")],
    "MultiEdit": [("i", "unk100"), ("i", "unk101")],
    "MultiSellItemInfo": [],
    "MultiSellNeededItem": [],
    "NameCtrl": [],
    "Progress": [("s", "backTexture"), ("s", "barTexture"), ("i", "gap")],
    "Radar": [],
    "RadioButton": [("i", "sysstring"), ("i", "radioGroupID"), ("i", "isChecked")],
    "ScrollArea": [("i", "areaHeight"), ("children", "children")],
    "ShortcutItemWindow": [("b", "alwaysShowOutline")],
    "SliderCtrl": [("i", "numOfTick"), ("i", "currTick"), ("i", "thumbBtnWidth"), ("i", "thumbBtnHeight"),
                   ("s", "backTexture"), ("s", "disableBackTexture"), ("s", "thumbBtnNormalTexture"),
                   ("s", "thumbBtnDownTexture"), ("i", "pushBtnWidth"), ("i", "pushBtnHeight"),
                   ("i", "pushBtnAutoHitTime"), ("i", "unk111"), ("s", "tickTexture")],
    "StatusBar": [("s", "title"), ("i", "textureWidth"), ("i", "textureHeight"), ("s", "foreTexture"),
                  ("s", "backTexture"), ("s", "warnTexture"), ("s", "regenTexture")],
    "StatusIconCtrl": [("b", "noClip"), ("b", "noTooltip")],
    "Tab": [("list:TabElement", "tabs")],
    "TextBox": [("s", "text"), ("e", "textAlign"), ("i", "offsetY"), ("s", "backTex"), ("i", "fontType"),
                ("i", "sysstring"), ("i", "systemMsg"), ("c", "textColor"), ("i", "emoticon"), ("i", "autosize")],
    "TextListBox": [("i", "maxRow"), ("i", "showRow"), ("i", "lineGap"), ("i", "isShowScroll")],
    "Texture": [("s", "file"), ("e", "type"), ("e", "layer"), ("f", "u"), ("f", "v"), ("f", "uSize"),
                ("f", "vSize"), ("i", "alpha"), ("i", "isAnimTex")],
    "TreeCtrl": [("b", "saveExpandedNode"), ("i", "multiExpand")],
}
# Plain (not polymorphic) element classes.
ELEMENTS = {
    "ComboBoxElement": [("i", "sysString"), ("i", "systemMsg"), ("s", "text"), ("i", "reserved")],
    "ListElement": [("i", "textStringId"), ("i", "width"), ("b", "unk108"), ("b", "unk109"), ("b", "unk110")],
    "TabElement": [("i", "buttonName"), ("s", "target"), ("i", "width"), ("i", "height"), ("s", "normalTex"),
                   ("s", "pushedTex"), ("b", "movable"), ("i", "gap"), ("i", "tooltip"), ("i", "noHighlight")],
    "Action": [("e", "key_1"), ("e", "key_2"), ("e", "key_3"), ("s", "action")],
    "Shortcut": [("s", "name"), ("s", "state"), ("list:Action", "actions")],
    "WndDefPos": [("s", "wnd"), ("e", "alignment"), ("i", "x"), ("i", "y"), ("b", "moveParent"), ("i", "width"),
                  ("i", "height")],
}
ALIGNMENT = ["NONE", "TOP_LEFT", "TOP_CENTER", "TOP_RIGHT", "CENTER_LEFT", "CENTER", "CENTER_RIGHT", "BOTTOM_LEFT",
             "BOTTOM_CENTER", "BOTTOM_RIGHT"]


class XdatError(Exception):
    pass


class Entity(dict):
    """One window, control or element: its fields in file order. `kind` is the class name (Window, Button, ...)."""

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.raw_strings = {}  # field -> original bytes, when the string's encoding isn't the canonical one

    @property
    def name(self):
        return self.get("name")

    def get_child(self, name):
        for c in self.get("children", []):
            if c.name == name:
                return c
        raise KeyError(name)

    def walk(self):
        yield self
        for c in self.get("children", []):
            yield from c.walk()

    def __repr__(self):
        return "%s(%s)" % (self.kind, self.get("name", ""))


def _read_string(r, ent, field):
    start = r.p
    s = r.fstring()
    raw = r.d[start:r.p]
    if write_fstring(s) != raw:
        ent.raw_strings[field] = (s, raw)
    return s


def _write_string(out, ent, field):
    s = ent[field]
    orig = ent.raw_strings.get(field)
    if orig is not None and orig[0] == s:
        out += orig[1]
    else:
        out += write_fstring(s)


def _read_fields(r, ent, spec):
    for kind, field in spec:
        if kind == "s":
            ent[field] = _read_string(r, ent, field)
        elif kind in ("i", "b", "e", "c"):
            ent[field] = r.i32()
        elif kind == "f":
            ent[field] = r.f32()
        elif kind == "children":
            ent[field] = [_read_ui(r) for _ in range(r.i32())]
        elif kind.startswith("list:"):
            cls = kind[5:]
            ent[field] = [_read_element(r, cls) for _ in range(r.i32())]
        else:
            raise AssertionError(kind)


def _write_fields(out, ent, spec):
    for kind, field in spec:
        v = ent[field]
        if kind == "s":
            _write_string(out, ent, field)
        elif kind in ("i", "b", "e", "c"):
            out += struct.pack("<i", v)
        elif kind == "f":
            out += struct.pack("<f", v)
        elif kind == "children":
            out += struct.pack("<i", len(v))
            for c in v:
                _write_ui(out, c)
        elif kind.startswith("list:"):
            out += struct.pack("<i", len(v))
            for c in v:
                _write_fields(out, c, ELEMENTS[c.kind])


def _read_default(r, ent):
    """DefaultProperty: the fields every window and control starts with."""
    for f in ("name", "superName"):
        ent[f] = _read_string(r, ent, f)
    ent["unk2"] = r.i32()
    ent["unk3"] = r.i32()
    for f in ("ownerWnd", "unk5", "unk6"):
        ent[f] = _read_string(r, ent, f)
    ent["unk7"] = r.i32()
    ent["size"] = r.i32()
    if ent["size"]:
        ent["size_absolute_values"] = r.i32()
        if not ent["size_absolute_values"]:
            ent["size_percent_count"] = r.ci()
            if ent["size_percent_count"] != 0:
                raise XdatError("%s: unknown size array" % ent["name"])
            ent["size_percent_width"] = r.f32()
            ent["size_percent_height"] = r.f32()
        ent["size_absolute_width"] = r.i32()
        ent["size_absolute_height"] = r.i32()
    ent["anchor"] = r.i32()
    if ent["anchor"]:
        ent["anchor_parent"] = r.i32()
        ent["anchor_this"] = r.i32()
        ent["anchor_ctrl"] = _read_string(r, ent, "anchor_ctrl")
        ent["anchor_x"] = r.i32()
        ent["anchor_y"] = r.i32()
    for f in ("unk22", "unk23", "unk24"):
        ent[f] = r.i32()
    ent["popupType"] = _read_string(r, ent, "popupType")
    ent["popupValue"] = r.i32()


def _write_default(out, ent):
    for f in ("name", "superName"):
        _write_string(out, ent, f)
    out += struct.pack("<ii", ent["unk2"], ent["unk3"])
    for f in ("ownerWnd", "unk5", "unk6"):
        _write_string(out, ent, f)
    out += struct.pack("<ii", ent["unk7"], ent["size"])
    if ent["size"]:
        out += struct.pack("<i", ent["size_absolute_values"])
        if not ent["size_absolute_values"]:
            out += write_ci(ent.get("size_percent_count", 0))
            out += struct.pack("<ff", ent["size_percent_width"], ent["size_percent_height"])
        out += struct.pack("<ii", ent["size_absolute_width"], ent["size_absolute_height"])
    out += struct.pack("<i", ent["anchor"])
    if ent["anchor"]:
        out += struct.pack("<ii", ent["anchor_parent"], ent["anchor_this"])
        _write_string(out, ent, "anchor_ctrl")
        out += struct.pack("<ii", ent["anchor_x"], ent["anchor_y"])
    out += struct.pack("<iii", ent["unk22"], ent["unk23"], ent["unk24"])
    _write_string(out, ent, "popupType")
    out += struct.pack("<i", ent["popupValue"])


def _read_control(r, kind):
    if kind not in SCHEMA:
        raise XdatError("unknown control type %r at offset %d" % (kind, r.p))
    ent = Entity(kind)
    _read_default(r, ent)
    _read_fields(r, ent, SCHEMA[kind])
    return ent


def _read_ui(r):
    """A polymorphic child: its class name, then the control."""
    return _read_control(r, r.fstring())


def _write_ui(out, ent):
    out += write_fstring(ent.kind)
    _write_control(out, ent)


def _write_control(out, ent):
    _write_default(out, ent)
    _write_fields(out, ent, SCHEMA[ent.kind])


def _read_element(r, cls):
    ent = Entity(cls)
    _read_fields(r, ent, ELEMENTS[cls])
    return ent


class Xdat:
    def __init__(self):
        self.windows = []
        self.shortcuts = []
        self.unk = 1
        self.wnd_def_pos = []
        self.tail = b""

    @classmethod
    def read(cls, data):
        x = cls()
        r = Reader(data)
        x.windows = [_read_control(r, "Window") for _ in range(r.i32())]
        x.shortcuts = [_read_element(r, "Shortcut") for _ in range(r.i32())]
        x.unk = r.i32()
        x.wnd_def_pos = [_read_element(r, "WndDefPos") for _ in range(r.i32())]
        x.tail = data[r.p:]
        if len(x.tail) not in (0, 20):
            raise XdatError("unexpected %d bytes after the window positions" % len(x.tail))
        return x

    def to_bytes(self):
        out = bytearray(struct.pack("<i", len(self.windows)))
        for w in self.windows:
            _write_control(out, w)
        out += struct.pack("<i", len(self.shortcuts))
        for s in self.shortcuts:
            _write_fields(out, s, ELEMENTS["Shortcut"])
        out += struct.pack("<ii", self.unk, len(self.wnd_def_pos))
        for p in self.wnd_def_pos:
            _write_fields(out, p, ELEMENTS["WndDefPos"])
        out += self.tail
        return bytes(out)

    def window(self, name):
        for w in self.windows:
            if w.name == name:
                return w
        raise KeyError(name)

    def find(self, path):
        """`QuestTreeWnd.chkNpcPosBox` -> the control."""
        parts = path.split(".")
        ent = self.window(parts[0])
        for p in parts[1:]:
            ent = ent.get_child(p)
        return ent
