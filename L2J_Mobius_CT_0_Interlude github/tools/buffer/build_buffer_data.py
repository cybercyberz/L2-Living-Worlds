"""Build and check the data the Role Buffer module (game/modules/role-buffer) reads.

Reads the buff skills from game/data/stats/skills/*.xml and writes game/modules/role-buffer/data/buffs.tsv: one row
per buff the packages may use, at its highest normal level, with its stack type, whether it's a dance/song, and a
short summary of what it does ("P. Atk +15%, Atk. Spd +33%").

It also checks game/modules/role-buffer/data/packages.txt (hand-edited):
  - every skill id is in the catalog below;
  - no package holds two skills of the same stack type (abnormalType), since the second would replace the first;
  - no package goes over the buff slots (MaxBuffAmount, 20) or the dance/song slots (MaxDanceAmount, 12).

Run from anywhere:  python tools/buffer/build_buffer_data.py          (writes buffs.tsv, checks the packages)
                    python tools/buffer/build_buffer_data.py --check  (exits 1 if buffs.tsv would change)
                    python tools/buffer/build_buffer_data.py --dump   (prints the whole catalog, to pick buffs)
"""

import glob
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKILLS = os.path.join(ROOT, "game", "data", "stats", "skills")
PLAYER_INI = os.path.join(ROOT, "game", "config", "Player.ini")
OUT_DIR = os.path.join(ROOT, "game", "modules", "role-buffer", "data")
PACKAGES = os.path.join(OUT_DIR, "packages.txt")

# Every buff a player can get from another class in Interlude: Prophet, Elven Elder, Shillien Elder, Warcryer,
# Overlord, Bladedancer and Swordsinger, plus the 3rd-class ones. Only these can go in a package.
CATALOG = [
    # Prophet
    1035, 1036, 1040, 1043, 1044, 1045, 1048, 1062, 1068, 1077, 1078, 1085, 1086, 1087, 1204, 1240, 1242, 1243,
    1388, 1389, 1392, 1393,
    # Elven Elder
    1073, 1259, 1303, 1304, 1352, 1353, 1354, 1397,
    # Shillien Elder
    1032, 1033, 1059, 1182, 1189, 1191, 1257, 1268,
    # Warcryer
    1002, 1006, 1007, 1009, 1251, 1252, 1253, 1284, 1308, 1309, 1310, 1362, 1390, 1391,
    # Overlord
    1004, 1005, 1008, 1249, 1250, 1260, 1261, 1282, 1364, 1365, 1415, 1416,
    # Bladedancer dances
    271, 272, 273, 274, 275, 276, 277, 307, 309, 310, 311, 365, 366,
    # Swordsinger songs
    264, 265, 266, 267, 268, 269, 270, 304, 305, 306, 308, 349, 363, 364,
    # 3rd class and other
    1323, 1355, 1356, 1357, 1363, 1413, 1414, 1311,
]

# Stat names as the game shows them.
STAT_NAMES = {
    "pAtk": "P. Atk", "pDef": "P. Def", "mAtk": "M. Atk", "mDef": "M. Def",
    "pAtkSpd": "Atk. Spd", "mAtkSpd": "Casting Spd", "runSpd": "Speed",
    "maxHp": "Max HP", "maxMp": "Max MP", "maxCp": "Max CP",
    "regHp": "HP Regen", "regMp": "MP Regen", "regCp": "CP Regen",
    "accCombat": "Accuracy", "rEvas": "Evasion",
    "critRate": "Crit. Rate", "critDmg": "Crit. Dmg", "mCritRate": "M. Crit",
    "absorbDam": "HP Absorb", "reflectDam": "Reflect Dmg", "vengeanceMdam": "Reflect Magic",
    "debuffVuln": "Debuff Taken", "cancel": "Cast Interrupt",
    "magicalMpConsumeRate": "Spell MP Cost", "physicalMpConsumeRate": "Skill MP Cost",
    "danceMpConsumeRate": "Dance MP Cost",
    "sDef": "Shield Def", "rShld": "Shield Rate", "shieldDefenceRate": "Shield Rate",
    "holyPower": "Holy Atk", "breath": "Breath", "weightLimit": "Weight Limit", "weightPenalty": "Weight",
    "pSkillEvas": "Skill Evasion", "pvePhysicalAttackDmg": "PvE Dmg", "fallDamage": "Fall Dmg",
    "mReuse": "Spell Reuse", "pReuse": "Skill Reuse", "cAtk": "Crit. Dmg", "rCrit": "Crit. Rate",
    "gainHp": "Heal Received", "mpRegen": "MP Regen", "damageZoneVuln": "Terrain Dmg Taken",
}
# Stats whose flat "add" values are percentages.
PERCENT_STATS = {"absorbDam", "reflectDam", "vengeanceMdam", "debuffVuln", "cancel", "damageZoneVuln"}
# DefenceTrait tags as the game shows them.
TRAIT_NAMES = {
    "HOLD": "Hold", "SLEEP": "Sleep", "DERANGEMENT": "Mental", "SHOCK": "Stun", "BLEED": "Bleed",
    "POISON": "Poison", "PARALYZE": "Paralyze", "ROOT": "Root",
}
# Resistances: shown as "Stun Res" etc.
RESIST_NAMES = {
    "stun": "Stun", "sleep": "Sleep", "root": "Root", "paralyze": "Paralyze", "derangement": "Mental",
    "poison": "Poison", "bleed": "Bleed", "bleeding": "Bleed", "cancel": "Cancel", "debuff": "Debuff",
    "fire": "Fire", "water": "Water", "wind": "Wind", "earth": "Earth", "holy": "Holy", "dark": "Dark",
    "unholy": "Dark", "confusion": "Confusion", "mental": "Mental",
}


def read_int(path, key, default):
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            m = re.match(r"\s*%s\s*=\s*(\d+)" % re.escape(key), line)
            if m:
                return int(m.group(1))
    except OSError:
        pass
    return default


def load_skills():
    skills = {}
    for path in glob.glob(os.path.join(SKILLS, "*.xml")):
        for node in ET.parse(path).getroot().iter("skill"):
            skill_id = int(node.get("id"))
            if skill_id in CATALOG:
                skills[skill_id] = node
    return skills


def table_value(node, text, level):
    """Resolves "#table" to its value at this level (1-based); plain values pass through."""
    text = (text or "").strip()
    if not text.startswith("#"):
        return text
    for table in node.findall("table"):
        if table.get("name") == text:
            values = table.text.split()
            return values[min(level, len(values)) - 1]
    return ""


def child(node, tag, level):
    element = node.find(tag)
    return table_value(node, element.text, level) if element is not None else ""


def stat_label(stat):
    if stat in STAT_NAMES:
        return STAT_NAMES[stat]
    m = re.match(r"^(\w+?)(Vuln|Res|Resist|Power)$", stat)
    if m and m.group(1).lower() in RESIST_NAMES:
        return RESIST_NAMES[m.group(1).lower()] + (" Res" if m.group(2) != "Power" else " Atk")
    m = re.match(r"^(?:resist|vuln)(\w+)$", stat, re.I)
    if m and m.group(1).lower() in RESIST_NAMES:
        return RESIST_NAMES[m.group(1).lower()] + " Res"
    return stat


def describe_stat(op, stat, value):
    try:
        v = float(value)
    except ValueError:
        return stat_label(stat)
    label = stat_label(stat)
    # Vulnerability stats: lower is better, so show them as resistance.
    if stat.endswith("Vuln") and op == "mul":
        return "%s %+d%%" % (label if label.endswith("Res") else label, round((1 - v) * 100)) \
            if label.endswith("Res") else "%s %+d%%" % (label, round((v - 1) * 100))
    if op == "mul":
        return "%s %+d%%" % (label, round((v - 1) * 100))
    if op in ("add", "sub"):
        v = -v if op == "sub" else v
        if stat.endswith("Vuln") and label.endswith(" Res"):
            v = -v  # less vulnerability is more resistance
        return "%s %+g%s" % (label, v, "%" if stat in PERCENT_STATS else "")
    if op == "set":
        return "%s = %g" % (label, v)
    return label


def summarize(node, level):
    parts = []
    effects = node.find("effects")
    if effects is None:
        return ""
    for effect in effects.findall("effect"):
        name = effect.get("name")
        stats = [e for e in effect if e.tag in ("mul", "add", "sub", "set")]
        if stats:
            for e in stats:
                value_node = e.find("value")
                if value_node is not None:
                    # A conditional stat, e.g. crits only from behind.
                    text = describe_stat(e.tag, e.get("stat"), table_value(node, value_node.text, level))
                    if e.find(".//player[@behind='true']") is not None:
                        text += " from behind"
                    parts.append(text)
                else:
                    parts.append(describe_stat(e.tag, e.get("stat"), table_value(node, e.text, level)))
        elif name == "DefenceTrait":
            traits = [(TRAIT_NAMES.get(t.tag, t.tag.title()), table_value(node, t.text, level)) for t in effect]
            values = {v for _, v in traits}
            if len(values) == 1:
                parts.append("%s Res +%s%%" % ("/".join(n for n, _ in traits), values.pop()))
            else:
                parts.extend("%s Res +%s%%" % (n, v) for n, v in traits)
        elif name == "MaxHp":
            power = table_value(node, (effect.findtext("power") or ""), level)
            percent = (effect.findtext("type") or "").strip() == "PER"
            parts.append("Max HP +%s%s" % (power, "%" if percent else ""))
        elif name in ("CpHeal", "Heal", "ManaHeal"):
            continue  # the instant part of a buff; the lasting part is listed above
        elif name == "NoblesseBless":
            parts.append("Keep buffs on death")
        elif name:
            parts.append(re.sub(r"(?<!^)(?=[A-Z])", " ", name))
    return ", ".join(parts)


def build_catalog(skills):
    rows = []
    missing = [i for i in CATALOG if i not in skills]
    for skill_id in CATALOG:
        node = skills.get(skill_id)
        if node is None:
            continue
        level = int(node.get("levels") or 1)
        kind = "dance" if child(node, "isMagic", level) == "3" else "buff"
        icon = child(node, "icon", level) or "icon.skill%04d" % skill_id
        rows.append(OrderedDict([
            ("id", skill_id),
            ("level", level),
            ("name", node.get("name")),
            ("kind", kind),
            ("type", child(node, "abnormalType", level)),
            ("typeLevel", child(node, "abnormalLevel", level) or "0"),
            ("time", child(node, "abnormalTime", level) or "0"),
            ("icon", icon),
            ("effect", summarize(node, level)),
        ]))
    return rows, missing


def parse_packages(path):
    """Returns [(key, name, purpose, icon, [skill ids], line of header)]."""
    packages = []
    current = None
    for number, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(\w+)\]\s*(.*)$", line)
        if m:
            fields = [f.strip() for f in m.group(2).split("|")]
            icon = 0
            for f in fields[2:]:
                im = re.match(r"icon\s*=\s*(\d+)", f)
                if im:
                    icon = int(im.group(1))
            current = [m.group(1), fields[0] if fields else m.group(1), fields[1] if len(fields) > 1 else "", icon, [], number]
            packages.append(current)
            continue
        m = re.match(r"^(\d+)\b", line)
        if m and current is not None:
            current[4].append((int(m.group(1)), number))
        else:
            raise SystemExit("%s:%d: can't read '%s'" % (path, number, raw.rstrip()))
    return packages


def check_packages(packages, catalog, max_buffs, max_dances):
    by_id = {row["id"]: row for row in catalog}
    errors = []
    report = []
    for key, name, _purpose, icon, entries, header_line in packages:
        if icon and icon not in by_id:
            errors.append("packages.txt:%d: [%s] icon=%d isn't in the catalog" % (header_line, key, icon))
        seen_types = {}
        seen_ids = set()
        buffs = dances = 0
        for skill_id, line in entries:
            row = by_id.get(skill_id)
            if row is None:
                errors.append("packages.txt:%d: [%s] skill %d isn't in the catalog" % (line, key, skill_id))
                continue
            if skill_id in seen_ids:
                errors.append("packages.txt:%d: [%s] %s is listed twice" % (line, key, row["name"]))
                continue
            seen_ids.add(skill_id)
            if row["type"] in seen_types:
                errors.append("packages.txt:%d: [%s] %s and %s are both %s; only one would stay on"
                              % (line, key, seen_types[row["type"]], row["name"], row["type"]))
            seen_types[row["type"]] = row["name"]
            if row["kind"] == "dance":
                dances += 1
            else:
                buffs += 1
        if buffs > max_buffs:
            errors.append("packages.txt:%d: [%s] has %d buffs, over the %d slots" % (header_line, key, buffs, max_buffs))
        if dances > max_dances:
            errors.append("packages.txt:%d: [%s] has %d dances/songs, over the %d slots" % (header_line, key, dances, max_dances))
        report.append("  %-9s %-16s %2d buffs, %2d dances/songs" % (key, name, buffs, dances))
    return errors, report


def render(rows):
    header = "#id\tlevel\tname\tkind\ttype\ttypeLevel\ttime\ticon\teffect"
    lines = [header] + ["\t".join(str(v) for v in row.values()) for row in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def main():
    args = sys.argv[1:]
    skills = load_skills()
    catalog, missing = build_catalog(skills)
    if missing:
        print("not in this datapack (skipped): " + ", ".join(str(i) for i in missing))

    if "--dump" in args:
        for row in sorted(catalog, key=lambda r: (r["type"], r["id"])):
            print("%-5d L%-2s %-5s %-24s %-32s %s" % (row["id"], row["level"], row["kind"], row["type"], row["name"], row["effect"]))
        return 0

    status = 0
    data = render(catalog)
    path = os.path.join(OUT_DIR, "buffs.tsv")
    old = open(path, "rb").read() if os.path.exists(path) else None
    if old != data:
        if "--check" in args:
            print("out of date: buffs.tsv")
            status = 1
        else:
            os.makedirs(OUT_DIR, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
    print("buffs.tsv      %3d buffs%s" % (len(catalog), "  (changed)" if old != data else ""))

    max_buffs = read_int(PLAYER_INI, "MaxBuffAmount", 20)
    max_dances = read_int(PLAYER_INI, "MaxDanceAmount", 12)
    errors, report = check_packages(parse_packages(PACKAGES), catalog, max_buffs, max_dances)
    print("packages.txt (slots: %d buffs, %d dances/songs)" % (max_buffs, max_dances))
    print("\n".join(report))
    for error in errors:
        print("ERROR " + error)
    return 1 if errors else status


if __name__ == "__main__":
    sys.exit(main())
