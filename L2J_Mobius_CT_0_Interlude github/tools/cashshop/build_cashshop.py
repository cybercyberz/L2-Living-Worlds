"""Build the Community Board cash shop: every tradeable, priced item, sold for Adena.

Reads the item definitions in game/data/stats/items/*.xml and writes:
  - game/data/multisell/custom/6001NN.xml         one multisell per category (split at MAX_PER_LIST entries)
  - game/data/html/CommunityBoard/Custom/cashshop/  main.html plus one page per group, linking to the lists

Run from anywhere:  python tools/cashshop/build_cashshop.py
Rerunning is safe: it deletes its own old 6001NN.xml lists and cashshop/*.html first.
The shop needs CustomCommunityBoard = True in game/config/Custom/CommunityBoard.ini.
"""

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ITEMS_DIR = os.path.join(ROOT, "game", "data", "stats", "items")
MULTISELL_DIR = os.path.join(ROOT, "game", "data", "multisell", "custom")
HTML_DIR = os.path.join(ROOT, "game", "data", "html", "CommunityBoard", "Custom", "cashshop")

ADENA = 57
PRICE_MULT = 1.0  # scales every price; 2.0 doubles the shop
MAX_PER_LIST = 300
FIRST_LIST_ID = 600100
LAST_LIST_ID = 600199

GRADES = ["NG", "D", "C", "B", "A", "S"]
JEWEL_SLOTS = {"rear;lear", "neck", "rfinger;lfinger"}
ACCESSORY_SLOTS = {"hair", "hairall", "underwear", "back", "alldress"}
# Items that would be sold by mistake: dummies, monster gear, event copies, unused ids.
JUNK_NAME = re.compile(r"not used|not in use|dummy|monster only|\(event\)|^event[ -]|l2day|battle tournament|\btest\b|^\d+$", re.I)
# Castle mercenary tickets only work for castle lords.
EXCLUDED_ETC_TYPES = {"CASTLE_GUARD"}

# group key -> (page file, page title, main page button); the order here is the order on the main page.
GROUPS = {
    "weapons": ("weapons", "Weapons", "Weapons"),
    "armor": ("armor", "Armor", "Armor"),
    "jewelry": ("jewelry", "Jewelry & Accessories", "Jewelry"),
    "consumables": ("consumables", "Consumables", "Consumables"),
    "crafting": ("crafting", "Crafting & Enchanting", "Crafting"),
    "other": ("other", "Fishing, Manor & Other", "Fishing/Other"),
}
BUTTON_WIDTH = 114  # the width the bigbutton2 texture is drawn for; wider buttons tile a stray sliver


def load_items():
    items = []
    for path in sorted(glob.glob(os.path.join(ITEMS_DIR, "*.xml"))):
        for node in ET.parse(path).getroot().iter("item"):
            sets = {s.get("name"): s.get("val") for s in node.findall("set")}
            items.append({
                "id": int(node.get("id")),
                "type": node.get("type"),
                "name": (node.get("name") or "").strip(),
                "sets": sets,
            })
    return items


def exclusion_reason(item):
    s = item["sets"]
    if item["id"] == ADENA:
        return "adena"
    if s.get("is_tradable") == "false":
        return "not tradable"
    if s.get("is_questitem") == "true":
        return "quest item"
    if not item["name"]:
        return "no name"
    if JUNK_NAME.search(item["name"]):
        return "junk name"
    if s.get("etcitem_type") in EXCLUDED_ETC_TYPES:
        return "castle ticket"
    if int(s.get("price") or 0) <= 1:
        return "no price"  # 1 Adena marks placeholders: Trash, dead recipe duplicates, event paper
    return None


def grade(item):
    return item["sets"].get("crystal_type") or "NG"


def categorize(item):
    """Returns (group, category label, sort position of the category within its group)."""
    s = item["sets"]
    name = item["name"]
    etc = s.get("etcitem_type")
    action = s.get("default_action")
    slot = s.get("bodypart")

    if item["type"] == "Weapon":
        if s.get("weapon_type") == "FISHINGROD":
            return "other", "Fishing", 0
        return "weapons", grade(item) + "-grade", GRADES.index(grade(item))
    if item["type"] == "Armor":
        if slot in JEWEL_SLOTS:
            return "jewelry", grade(item) + "-grade", GRADES.index(grade(item))
        if slot in ACCESSORY_SLOTS:
            return "jewelry", "Accessories", 10
        return "armor", grade(item) + "-grade", GRADES.index(grade(item))

    # EtcItem
    if etc == "RECIPE":
        return "crafting", "Recipes", 0
    if etc == "MATERIAL":
        return "crafting", "Materials", 1
    if etc in ("SCRL_ENCHANT_WP", "SCRL_ENCHANT_AM", "BLESS_SCRL_ENCHANT_WP", "BLESS_SCRL_ENCHANT_AM"):
        return "crafting", "Enchant Scrolls", 2
    if "Soul Crystal" in name or "Life Stone" in name:
        return "crafting", "Crystals & Stones", 3
    if etc == "DYE":
        return "crafting", "Dyes", 4
    if etc in ("ARROW",) or action in ("SOULSHOT", "SPIRITSHOT", "SUMMON_SOULSHOT", "SUMMON_SPIRITSHOT") \
            or "Compressed Package of" in name:
        return "consumables", "Shots & Arrows", 0
    if etc in ("POTION", "ELIXIR") or "Potion" in name or "Elixir" in name:
        return "consumables", "Potions", 1
    if etc == "SCROLL" or name.startswith("Scroll") or "Scroll of" in name:
        return "consumables", "Scrolls", 2
    if re.match(r"(Spellbook|Amulet|Book of|Ancient Tactical Manual|Forgotten Scroll)", name):
        return "consumables", "Spellbooks", 3
    if etc == "PET_COLLAR" or re.search(r"\bPet\b|Food for", name):
        return "consumables", "Pet Items", 4
    if etc in ("LURE",) or action == "FISHINGSHOT" or "Fish" in name or "Treasure Chest" in name:
        return "other", "Fishing", 0
    if etc in ("SEED", "SEED2", "CROP", "MATURECROP", "HARVEST"):
        return "other", "Manor", 1
    return "other", "Other", 2


def build_lists(items):
    """Groups items into ordered, size-limited multisell lists."""
    buckets = defaultdict(list)  # (group, order, label) -> items
    for item in items:
        group, label, order = categorize(item)
        buckets[(group, order, label)].append(item)

    lists = []
    group_order = list(GROUPS)
    for group, order, label in sorted(buckets, key=lambda k: (group_order.index(k[0]), k[1], k[2])):
        entries = sorted(buckets[(group, order, label)], key=lambda i: (
            GRADES.index(grade(i)),
            i["sets"].get("weapon_type") or i["sets"].get("bodypart") or "",
            int(i["sets"]["price"]),
            i["name"],
        ))
        size = -(-len(entries) // -(-len(entries) // MAX_PER_LIST))  # even chunks of at most MAX_PER_LIST
        chunks = [entries[i:i + size] for i in range(0, len(entries), size)]
        for n, chunk in enumerate(chunks, 1):
            lists.append({
                "group": group,
                "label": label if len(chunks) == 1 else f"{label} ({n})",
                "items": chunk,
            })

    if len(lists) > LAST_LIST_ID - FIRST_LIST_ID + 1:
        sys.exit(f"{len(lists)} lists do not fit in ids {FIRST_LIST_ID}-{LAST_LIST_ID}")
    for n, lst in enumerate(lists):
        lst["id"] = FIRST_LIST_ID + n
    return lists


def price(item):
    return max(1, round(int(item["sets"]["price"]) * PRICE_MULT))


def xml_comment(text):
    return text.replace("--", "- -")


def write_multisell(lst):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!-- Generated by tools/cashshop/build_cashshop.py; edit the script, not this file. -->',
        '<list xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="../../xsd/multisell.xsd">',
        '\t<npcs>',
        '\t\t<npc>-1</npc> <!-- CB -->',
        '\t</npcs>',
    ]
    for item in lst["items"]:
        lines += [
            '\t<item>',
            f'\t\t<!-- {xml_comment(item["name"])} -->',
            f'\t\t<ingredient count="{price(item)}" id="{ADENA}" />',
            f'\t\t<production count="1" id="{item["id"]}" />',
            '\t</item>',
        ]
    lines.append('</list>')
    with open(os.path.join(MULTISELL_DIR, f'{lst["id"]}.xml'), "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


BUTTON = ('<button value="{value}" action="{action}" width={width} height=30 '
          'back="L2UI_CH3.Button.bigbutton2_down" fore="L2UI_CH3.Button.bigbutton2">')


def page(title, body):
    return f"""<html><body>
<table width=700><tr><td height=10></td></tr></table>
<table width=20><tr><td>%navigation%</td><td><center>
<table bgcolor="000000" width=500 height=415>
<tr><td height=15></td></tr>
<tr><td height=25 align="center"><font color="CDB67F">{title}</font></td></tr>
<tr><td height=15></td></tr>
<tr><td><center><img src="L2UI.SquareGray" width=500 height=1></center></td></tr>
<tr><td height=20></td></tr>
<tr><td align="center">
{body}
</td></tr></table>
<table border=0 cellpadding=0 cellspacing=0 width=500>
<tr><td height=10></td></tr></table>
<table border=0 bgcolor="000000" cellpadding=0 cellspacing=0 width=500>
<tr><td height=50 align=center><font color=696969><br>LINEAGE II - COMMUNITY BOARD</font></td></tr>
</table></center></td></tr></table></body></html>
"""


def grid(cells, columns=3):
    rows = []
    for i in range(0, len(cells), columns):
        rows.append("<tr>" + "".join(f"<td align=center width=160>{c}</td>" for c in cells[i:i + columns]) + "</tr>")
    return "<table align=center border=0>\n" + "\n".join(rows) + "\n</table>"


def write_html(lists):
    cells = []
    for group, (file, title, button) in GROUPS.items():
        count = sum(len(l["items"]) for l in lists if l["group"] == group)
        if not count:
            continue
        cells.append(BUTTON.format(value=button, width=BUTTON_WIDTH,
                                   action=f"bypass _bbstop;cashshop/{file}.html")
                     + f"<br><font color=808080>{count} items</font><br1>")
    total = sum(len(l["items"]) for l in lists)
    body = (grid(cells) + f"<br><font color=808080>Everything costs Adena. {total} items in {len(lists)} lists.<br1>"
            "Stackable items can be bought in any amount.</font>")
    pages = {"main": page("Cash Shop", body)}

    for group, (file, title, _) in GROUPS.items():
        group_lists = [l for l in lists if l["group"] == group]
        if not group_lists:
            continue
        cells = [BUTTON.format(value=l["label"], width=BUTTON_WIDTH, action=f'bypass _bbsmultisell;{l["id"]},cashshop/{file}')
                 + f'<br><font color=808080>{len(l["items"])} items</font><br1>' for l in group_lists]
        back = BUTTON.format(value="Back", width=BUTTON_WIDTH, action="bypass _bbstop;cashshop/main.html")
        pages[file] = page(f"Cash Shop - {title}", grid(cells) + "<br>" + back)

    for name, html in pages.items():
        with open(os.path.join(HTML_DIR, f"{name}.html"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(html)
    return pages


def clean_old_output():
    for n in range(FIRST_LIST_ID, LAST_LIST_ID + 1):
        path = os.path.join(MULTISELL_DIR, f"{n}.xml")
        if os.path.exists(path):
            os.remove(path)
    os.makedirs(HTML_DIR, exist_ok=True)
    for path in glob.glob(os.path.join(HTML_DIR, "*.html")):
        os.remove(path)


def main():
    items = load_items()
    excluded = Counter()
    sellable = []
    for item in items:
        reason = exclusion_reason(item)
        if reason:
            excluded[reason] += 1
        else:
            sellable.append(item)

    lists = build_lists(sellable)
    clean_old_output()
    for lst in lists:
        write_multisell(lst)
    pages = write_html(lists)

    print(f"{len(items)} items read, {len(sellable)} for sale, {sum(excluded.values())} excluded:")
    for reason, n in excluded.most_common():
        print(f"  {n:5}  {reason}")
    print(f"\n{len(lists)} multisells ({FIRST_LIST_ID}-{lists[-1]['id']}):")
    for lst in lists:
        print(f"  {lst['id']}  {GROUPS[lst['group']][1]:24} {lst['label']:20} {len(lst['items']):4} items")
    print("\nPages: " + ", ".join(f"{name}.html ({len(html)} chars)" for name, html in pages.items()))


if __name__ == "__main__":
    main()
