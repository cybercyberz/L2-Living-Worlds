"""Build the data the Adventurer's Guide module (game/modules/adventurer-guide) reads.

Reads the client's questname-e.dat (through tools/l2mod) and the server datapack, and writes
game/modules/adventurer-guide/data/:
  - quests.tsv     one row per quest: level range, allowed classes, type, start NPC and where it stands, intro
  - teleports.tsv  every gatekeeper destination that costs Adena, with its cheapest fee
  - areas.tsv      hunting spots: monster spawns grouped by the nearest gatekeeper destination
  - area_mobs.tsv  the monsters of each spot, with level, exp/sp, aggression and where they spawn
  - services.tsv   town NPCs a new player needs: gatekeepers, warehouses, shops, class and skill masters

Run from anywhere:  python tools/guide/build_guide_data.py          (writes the files)
                    python tools/guide/build_guide_data.py --check  (exits 1 if the files would change)
Rerunning is safe: it only rewrites these five files. The server reads them when the module starts.
"""

import glob
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "game", "data")
OUT_DIR = os.path.join(ROOT, "game", "modules", "adventurer-guide", "data")
sys.path.insert(0, os.path.join(ROOT, "tools", "l2mod"))

ADENA = 57
# A spawn this close to a gatekeeper destination is named after it; farther ones are named after their file.
SPOT_RADIUS = 9000
# Spawn folders that aren't open hunting grounds: castles, Seven Signs catacombs, festival and rift.
SKIP_SPAWN_DIRS = {"Castles", "Catacombs", "SevenSigns"}
# Spawn files that aren't hunting spots: scattered level-1 gremlins, fake players, chests, raid guards.
SKIP_SPAWN_FILES = {"Gremlins", "FakePlayers", "TreasureBoxes", "QueenAntGuards"}
# Readable names for spots named after their spawn file.
AREA_ALIASES = {
    "Crypts Of Discrace": "Crypts of Disgrace",
    "Forge Of Gods": "Forge of the Gods",
    "Garden Of Beasts": "Garden of Beasts",
    "Plains Of Glory": "Plains of Glory",
    "Hardins Academy": "Hardin's Academy",
    "Varka Slenos Outpost": "Varka Silenos Outpost",
    "Dark Elf Starting": "Dark Elf Starting Area",
    "Dwarven Starting": "Dwarven Starting Area",
    "Elven Starting": "Elven Starting Area",
    "Orc Starting": "Orc Starting Area",
    "Orc Village Quest": "Orc Village Outskirts",
    "Pavel Archaic": "Pavel Ruins",
    "Turek Orcs": "Turek Orc Camp",
    "Talking Island": "Talking Island Fields",
}
TOWN_ALIASES = {"Hunters": "Hunters Village", "Talking Island": "Talking Island Village"}
# Town spawn files (<Town>NPCs.xml) that aren't towns.
SKIP_TOWN_FILES = {"CatacombsNPCs", "NecropolisNPCs", "RiftNPCs", "MonsterRaceTrackNPCs"}
MAX_POINTS = 8  # spawn centres kept per mob per spot
INTRO_MAX = 360


def split_camel(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").strip()


def clean_text(text, limit=None):
    text = (text or "").replace("\\n", " ").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;") + "..."
    return text


def load_npcs():
    npcs = {}
    for path in sorted(glob.glob(os.path.join(DATA, "stats", "npcs", "*.xml")) + glob.glob(os.path.join(DATA, "stats", "npcs", "custom", "*.xml"))):
        for node in ET.parse(path).getroot().iter("npc"):
            acquire = node.find("acquire")
            ai = node.find("ai")
            npcs[int(node.get("id"))] = {
                "type": node.get("type") or "",
                "title": node.get("title") or "",
                "name": clean_text(node.get("name")),
                "level": int(node.get("level") or 0),
                "exp": int(float(acquire.get("exp") or 0)) if acquire is not None else 0,
                "sp": int(float(acquire.get("sp") or 0)) if acquire is not None else 0,
                "aggro": (ai is not None) and (ai.get("isAggressive") == "true"),
            }
    return npcs


def f32(value):
    """l2mod keeps floats as their 4 raw bytes so tables round-trip exactly."""
    if isinstance(value, (bytes, bytearray)):
        value = struct.unpack("<f", value)[0]
    return 0 if math.isnan(value) else int(value)


def build_quests(npcs):
    from l2mod import dat, stock
    table = dat.Table.read("questname-e.dat", dat.decrypt(stock.stock_bytes("questname-e.dat")))
    first = {}
    for row in table.rows:
        qid = row["id"]
        if (qid not in first) or (row["level"] < first[qid]["level"]):
            first[qid] = row
    rows = []
    for qid in sorted(first):
        r = first[qid]
        start = r["start_npc_id"]
        rows.append([
            qid, clean_text(r["title"]), r["lvl_min"], r["lvl_max"], r["quest_type"], start,
            npcs.get(start, {}).get("name", ""),
            f32(r["start_npc_x"]), f32(r["start_npc_y"]), f32(r["start_npc_z"]),
            clean_text(r["requirement"]), ",".join(str(c) for c in r["class_limit"]), r["req_quest_complete"],
            clean_text(r["intro"], INTRO_MAX), clean_text(r["desc"], INTRO_MAX),
        ])
    header = "#id\ttitle\tlvlMin\tlvlMax\ttype\tstartNpc\tstartNpcName\tx\ty\tz\trequirement\tclassLimit\treqQuest\tintro\tfirstStep"
    return header, rows


def build_teleports():
    best = {}
    files = glob.glob(os.path.join(DATA, "teleporters", "**", "*.xml"), recursive=True)
    for path in sorted(files):
        for tele in ET.parse(path).getroot().iter("teleport"):
            if (tele.get("type") or "").startswith("NOBLES"):
                continue
            for loc in tele.iter("location"):
                if int(loc.get("feeId") or ADENA) != ADENA:
                    continue
                name = clean_text(loc.get("name"))
                if not name:
                    continue
                fee = int(loc.get("feeCount") or 0)
                point = (int(loc.get("x")), int(loc.get("y")), int(loc.get("z")))
                if (name not in best) or (fee < best[name][3]):
                    best[name] = point + (fee,)
    rows = [[i, name] + list(best[name]) for i, name in enumerate(sorted(best))]
    return "#idx\tname\tx\ty\tz\tfee", rows


def nearest(point, teleports):
    best, best_d = None, float("inf")
    for t in teleports:
        d = math.hypot(point[0] - t[2], point[1] - t[3])
        if d < best_d:
            best, best_d = t, d
    return best, best_d


def spawn_points(spawn):
    """Yields (npc node, (x, y, z)) for each npc of a <spawn>, using the territory centre when it has no point."""
    territory = spawn.find("territory")
    centre = None
    if territory is not None:
        nodes = territory.findall("node")
        if nodes:
            cx = sum(int(n.get("x")) for n in nodes) // len(nodes)
            cy = sum(int(n.get("y")) for n in nodes) // len(nodes)
            cz = (int(territory.get("minZ") or 0) + int(territory.get("maxZ") or 0)) // 2
            centre = (cx, cy, cz)
    for npc in spawn.findall("npc"):
        if npc.get("x") is not None:
            yield npc, (int(npc.get("x")), int(npc.get("y")), int(npc.get("z") or 0))
        elif centre is not None:
            yield npc, centre


def build_hunting(npcs, teleports):
    # spot name -> {npcId -> {"count": n, "points": [..]}}
    spots = defaultdict(lambda: defaultdict(lambda: {"count": 0, "points": []}))
    spot_region = {}
    # "Brekas Stronghold" (a file) and "Breka's Stronghold" (a gatekeeper) are the same place.
    by_key = {re.sub(r"[^a-z]", "", t[1].lower()): t[1] for t in teleports}
    for path in sorted(glob.glob(os.path.join(DATA, "spawns", "*", "*.xml"))):
        region = os.path.basename(os.path.dirname(path))
        base = os.path.splitext(os.path.basename(path))[0]
        if (region in SKIP_SPAWN_DIRS) or (base in SKIP_SPAWN_FILES) or base.endswith("NPCs"):
            continue
        root = ET.parse(path).getroot()
        if root.get("enabled") == "false":
            continue
        for spawn in root.iter("spawn"):
            for npc, point in spawn_points(spawn):
                tmpl = npcs.get(int(npc.get("id")))
                if (tmpl is None) or (tmpl["type"] != "Monster") or (point[0] == 0 and point[1] == 0):
                    continue
                tele, dist = nearest(point, teleports)
                if dist <= SPOT_RADIUS:
                    spot = tele[1]
                elif re.fullmatch(r"\d+_\d+", base):
                    spot = "Wilds near " + tele[1]
                else:
                    spot = split_camel(re.sub(r"Monsters$", "", base)) or split_camel(region)
                    spot = AREA_ALIASES.get(spot, spot)
                    spot = by_key.get(re.sub(r"[^a-z]", "", spot.lower()), spot)
                entry = spots[spot][int(npc.get("id"))]
                entry["count"] += int(npc.get("count") or 1)
                if point not in entry["points"]:
                    entry["points"].append(point)
                spot_region.setdefault(spot, split_camel(region))

    area_rows, mob_rows = [], []
    for idx, spot in enumerate(sorted(spots)):
        mobs = spots[spot]
        # The spot's centre is the spawn-weighted mean of its mobs' points; its gatekeeper is the one nearest that.
        all_points = [p for m in mobs.values() for p in m["points"]]
        cx = sum(p[0] for p in all_points) // len(all_points)
        cy = sum(p[1] for p in all_points) // len(all_points)
        cz = sum(p[2] for p in all_points) // len(all_points)
        tele, _ = nearest((cx, cy, cz), teleports)
        levels = sorted(npcs[n]["level"] for n in mobs)
        area_rows.append([idx, spot, spot_region[spot], cx, cy, cz, tele[0], levels[0], levels[-1], sum(m["count"] for m in mobs.values())])
        for npc_id in sorted(mobs, key=lambda n: (npcs[n]["level"], n)):
            m = mobs[npc_id]
            t = npcs[npc_id]
            points = ";".join("%d,%d,%d" % p for p in m["points"][:MAX_POINTS])
            mob_rows.append([idx, npc_id, t["name"], t["level"], t["exp"], t["sp"], 1 if t["aggro"] else 0, m["count"], points])
    return ("#idx\tname\tregion\tx\ty\tz\tteleIdx\tminLv\tmaxLv\tspawns", area_rows), ("#areaIdx\tnpcId\tname\tlevel\texp\tsp\taggro\tcount\tpoints", mob_rows)


def load_item_kinds():
    kinds = {}
    for path in glob.glob(os.path.join(DATA, "stats", "items", "*.xml")):
        for node in ET.parse(path).getroot().iter("item"):
            kinds[int(node.get("id"))] = node.get("type")
    return kinds


def merchant_kinds():
    """npcId -> Weapons, Armor or Grocer, by the most common item type across its buylists."""
    items = load_item_kinds()
    counts = defaultdict(Counter)
    for path in glob.glob(os.path.join(DATA, "buylists", "*.xml")):
        root = ET.parse(path).getroot()
        owners = [int(n.text) for n in root.iter("npc") if (n.text or "").strip().isdigit()]
        if not owners:
            owners = [int(os.path.splitext(os.path.basename(path))[0]) // 10]
        for item in root.iter("item"):
            kind = items.get(int(item.get("id")))
            if kind:
                for owner in owners:
                    counts[owner][kind] += 1
    names = {"Weapon": "Weapons", "Armor": "Armor", "EtcItem": "Grocer"}
    return {npc: names[c.most_common(1)[0][0]] for npc, c in counts.items() if c}


def service_category(tmpl, shops, npc_id):
    t, title = tmpl["type"], tmpl["title"]
    if t == "Teleporter":
        return "Gatekeeper"
    if t == "Warehouse":
        return "Warehouse"
    if t.startswith("VillageMaster"):
        return "Class Master"
    if t == "Trainer":
        return "Skill Trainer"
    if t == "Merchant":
        if title in ("Spellbook Seller", "Blueprint Seller", "Mineral Trader", "Amulet Seller", "Magic Trader", "Wharf Manager"):
            return None
        return shops.get(npc_id, "Grocer")
    if t == "PetManager":
        return "Pet Manager"
    if title == "Symbol Maker":
        return "Symbol Maker"
    return None


SERVICE_ORDER = ["Gatekeeper", "Warehouse", "Grocer", "Weapons", "Armor", "Class Master", "Skill Trainer", "Pet Manager", "Symbol Maker"]


def build_services(npcs):
    shops = merchant_kinds()
    rows = []
    towns = []
    for path in sorted(glob.glob(os.path.join(DATA, "spawns", "*", "*NPCs.xml"))):
        base = os.path.splitext(os.path.basename(path))[0]
        if base in SKIP_TOWN_FILES:
            continue
        town = split_camel(base[:-len("NPCs")])
        town = TOWN_ALIASES.get(town, town)
        entries = []
        for npc in ET.parse(path).getroot().iter("npc"):
            npc_id = int(npc.get("id"))
            tmpl = npcs.get(npc_id)
            if (tmpl is None) or (npc.get("x") is None):
                continue
            cat = service_category(tmpl, shops, npc_id)
            if cat:
                name = tmpl["name"] + ((" (" + tmpl["title"] + ")") if tmpl["title"] and cat in ("Class Master", "Skill Trainer") else "")
                entries.append((SERVICE_ORDER.index(cat), cat, name, npc_id, int(npc.get("x")), int(npc.get("y")), int(npc.get("z") or 0)))
        if entries:
            towns.append((town, sorted(set(entries))))
    for idx, (town, entries) in enumerate(towns):
        for _, cat, name, npc_id, x, y, z in entries:
            rows.append([idx, town, cat, npc_id, name, x, y, z])
    return "#townIdx\ttown\tcategory\tnpcId\tname\tx\ty\tz", rows


def render(header, rows):
    lines = [header] + ["\t".join(str(c) for c in row) for row in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def main():
    check = "--check" in sys.argv[1:]
    npcs = load_npcs()
    quests = build_quests(npcs)
    teleports = build_teleports()
    areas, area_mobs = build_hunting(npcs, teleports[1])
    services = build_services(npcs)
    outputs = {
        "quests.tsv": quests,
        "teleports.tsv": teleports,
        "areas.tsv": areas,
        "area_mobs.tsv": area_mobs,
        "services.tsv": services,
    }
    changed = []
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, (header, rows) in outputs.items():
        path = os.path.join(OUT_DIR, name)
        data = render(header, rows)
        old = open(path, "rb").read() if os.path.exists(path) else None
        if old != data:
            changed.append(name)
            if not check:
                with open(path, "wb") as f:
                    f.write(data)
        print("%-14s %5d rows%s" % (name, len(rows), "  (changed)" if old != data else ""))
    if check and changed:
        print("out of date: " + ", ".join(changed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
