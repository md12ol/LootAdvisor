"""Areas ("zones") and their entrances from the game's level data (read-only) -> data/cache/level_zones.json.

Why: many interiors (vaults, House of Hope, Guildhall, Murder Tribunal, Undercity ...) are stored far away from
the visible map of their region and are reached by a teleporting door / ladder / hatch / portal. A map marker on an
item inside such an interior points into nowhere; the marker belongs on the entrance instead (HANDOFF session 3
decision 4, user round 2: "the entrance closest to the player").

General method (no per-item or per-map rules):
 1. World positions. Sub-levels that are placed into their parent level as LevelTemplates (Levels/<parent>/
    LevelTemplates: Name "LT_<sublevel>[_NNN]", Transform Position + RotationQuat) store LOCAL coordinates; they
    are transformed (recursively, a parent can itself be a template) into world coordinates.
 2. Zones. Every placement of a region (items, characters, triggers) is put on a 2D grid (CELL m). Occupied cells
    that touch (8-neighbourhood) form one zone: the open map is one big zone, each far-away interior its own.
 3. Entrances. Every placed item with a teleport use-action (OnUsePeaceActions ActionType 3, Attributes Target =
    arrival trigger) is an edge "source zone -> target zone". Zone-crossing teleporters are the entrances.
At runtime the mod finds the player's zone (cell lookup), walks the entrance graph to the item's zone and marks
the first entrance on the shortest way (nearest to the player). See Mods/LootAdvisor/.../Shared/Zones.lua.

  python LootAdvisor/tools/level_links.py   (teleporters + triggers, run first)
  python LootAdvisor/tools/entrances.py
"""
import collections
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from pak import Pak, GAME_DATA  # noqa: E402
import lsf  # noqa: E402

CELL = 16.0
OUT = os.path.join(LA, "data", "cache", "level_zones.json")
REGIONS = ["WLD_Main_A", "CRE_Main_A", "SCL_Main_A", "INT_Main_A", "BGO_Main_A", "CTY_Main_A", "IRN_Main_A", "END_Main"]
MIN_ZONE_POINTS = 3


def qrot(q, p):
    x, y, z, w = q
    px, py, pz = p
    # v' = v + 2w(q x v) + 2 q x (q x v)
    cx, cy, cz = y * pz - z * py, z * px - x * pz, x * py - y * px
    cx2, cy2, cz2 = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return [px + 2 * (w * cx + cx2), py + 2 * (w * cy + cy2), pz + 2 * (w * cz + cz2)]


def load_templates(levels):
    low = {k.lower(): k for k in levels}
    for r in REGIONS:
        low.setdefault(r.lower(), r)
    lts = collections.defaultdict(list)
    for pk in ("Shared.pak", "Gustav.pak", "GustavX.pak"):
        p = Pak(os.path.join(GAME_DATA, pk))
        for n in p.by_name:
            if "/LevelTemplates/" not in n or not n.endswith(".lsf"):
                continue
            parent = n.split("/")[3]
            for g in lsf.load(p.read(p.by_name[n])).regions[0].children:
                base = re.sub(r"_\d{3}$", "", re.sub(r"^C?LT_", "", g.get("Name") or ""))
                key = low.get(base.lower())
                tr = [ch for ch in g.children if ch.name == "Transform"]
                if key and tr and key != parent:
                    lts[key].append((parent, tr[0].get("Position"), tr[0].get("RotationQuat") or [0, 0, 0, 1]))
    return lts


def make_world(levels, lts):
    """-> (region_of(level), to_world(level, pos)) using the LevelTemplate placements lts."""
    def region_of(level, depth=0):
        if level in REGIONS:
            return level
        ml = (levels.get(level) or {}).get("main_level")
        if ml:
            return ml
        if level in lts and depth < 6:
            return region_of(lts[level][0][0], depth + 1)
        for tok in level.split("_"):
            for reg in REGIONS:
                if reg.split("_")[0].upper() == tok.upper():
                    return reg
        return level

    def to_world(level, p, depth=0):
        if p is None:
            return None
        pl = lts.get(level)
        if not pl or depth > 6:
            return list(p)
        reg = region_of(level)
        cand = [x for x in pl if region_of(x[0]) == reg] or pl
        parent, t, q = cand[0]
        r = qrot(q, p)
        return to_world(parent, [r[0] + t[0], r[1] + t[1], r[2] + t[2]], depth + 1)

    return region_of, to_world


def main():
    levels = json.load(open(os.path.join(LA, "data", "items_all", "levels.json"), encoding="utf-8"))
    lts = load_templates(levels)

    region_of, to_world = make_world(levels, lts)

    # 1) all placements in world coordinates, per region
    pts = collections.defaultdict(list)
    for fn in ("level_items_index.json", "level_characters_index.json"):
        for pl in json.load(open(os.path.join(LA, "data", "cache", fn), encoding="utf-8")):
            lvn = pl.get("level") or ""
            reg = region_of(lvn)
            if reg in REGIONS and pl.get("position"):
                pts[reg].append(to_world(lvn, pl["position"]))
    links = json.load(open(os.path.join(LA, "data", "cache", "level_links.json"), encoding="utf-8"))
    for t in links["triggers"].values():
        reg = region_of(t["level"])
        if reg in REGIONS and t.get("pos"):
            pts[reg].append(to_world(t["level"], t["pos"]))

    # 2) zones = connected occupied grid cells
    zones = {}
    cellzone = {}
    for reg, ps in pts.items():
        cells = collections.Counter((math.floor(p[0] / CELL), math.floor(p[2] / CELL)) for p in ps)
        seen = {}
        zid = 0
        for c in cells:
            if c in seen:
                continue
            zid += 1
            stack = [c]
            seen[c] = zid
            while stack:
                cx, cz = stack.pop()
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        n = (cx + dx, cz + dz)
                        if n in cells and n not in seen:
                            seen[n] = zid
                            stack.append(n)
        size = collections.Counter()
        for c, z in seen.items():
            size[z] += cells[c]
        keep = {z for z, n in size.items() if n >= MIN_ZONE_POINTS}
        cellzone[reg] = {c: z for c, z in seen.items() if z in keep}
        zones[reg] = {z: size[z] for z in keep}

    def zone_at(reg, p):
        cz = cellzone.get(reg) or {}
        c = (math.floor(p[0] / CELL), math.floor(p[2] / CELL))
        if c in cz:
            return cz[c]
        best, bd = None, 1e18
        for r in range(1, 4):  # nearest occupied cell within 3 cells
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    z = cz.get((c[0] + dx, c[1] + dz))
                    if z and dx * dx + dz * dz < bd:
                        best, bd = z, dx * dx + dz * dz
            if best:
                return best
        return None

    # 3) entrances
    ents = []
    for t in links["teleporters"]:
        if not (t.get("pos") and t.get("target_pos")):
            continue
        reg = region_of(t["level"])
        treg = region_of(t["target_level"] or t["level"])
        if reg not in REGIONS or treg != reg:
            continue
        a = to_world(t["level"], t["pos"])
        b = to_world(t["target_level"], t["target_pos"])
        za, zb = zone_at(reg, a), zone_at(reg, b)
        if za and zb and za != zb:
            ents.append({"MapKey": t["MapKey"], "Name": t["Name"], "region": reg, "pos": [round(v, 1) for v in a],
                         "to": [round(v, 1) for v in b], "zfrom": za, "zto": zb, "type": "Item",
                         "arrive": t["target"], "arrive_name": t.get("target_name")})
    # one-way links (an exit with no listed way in, e.g. the House of Hope portal back to the Devil's Fee): the way
    # in is the same link reversed; its marker goes on the exit's arrival trigger, which sits at the entrance side
    # (only for zones with no way in at all - a real one-way link, e.g. a hole you drop through, must not become a
    # shortcut into an area that has its own entrance)
    inbound = {(e["region"], e["zto"]) for e in ents}
    for e in list(ents):
        if (e["region"], e["zfrom"]) not in inbound and e.get("arrive"):
            ents.append({"MapKey": e["arrive"], "Name": e.get("arrive_name"), "region": e["region"], "pos": e["to"],
                         "to": e["pos"], "zfrom": e["zto"], "zto": e["zfrom"], "reverse": True,
                         "type": "Trigger" if e["arrive"] in links["triggers"] else "Item"})

    # 4) ways to OTHER regions (round 3): region-swap teleporters + waypoints from the story scripts
    import region_exits
    placed = {}
    for pl in json.load(open(os.path.join(LA, "data", "cache", "level_items_index.json"), encoding="utf-8")):
        if pl.get("MapKey") and pl.get("position"):
            placed[pl["MapKey"]] = (pl.get("level") or "", pl["position"])
    for mk, o in links.get("objects", {}).items():  # includes Globals/<level>/Items (waypoints)
        if o.get("pos") and mk not in placed:
            placed[mk] = (o.get("level") or "", o["pos"])
    rx, wps = region_exits.parse(region_exits.load_goals())
    exits, ways = [], []
    for e in rx:
        if e["MapKey"] not in placed:
            continue
        lvl, ps = placed[e["MapKey"]]
        reg = region_of(lvl)
        w = to_world(lvl, ps)
        if reg in REGIONS and e["to_region"] in REGIONS and reg != e["to_region"]:
            exits.append({"MapKey": e["MapKey"], "Name": e["Name"], "region": reg, "to_region": e["to_region"],
                          "pos": [round(v, 1) for v in w], "zone": zone_at(reg, w), "type": "Item"})
    for wp in wps:
        if wp["MapKey"] not in placed:
            continue
        lvl, ps = placed[wp["MapKey"]]
        reg = region_of(lvl)
        w = to_world(lvl, ps)
        if reg in REGIONS:
            ways.append({"MapKey": wp["MapKey"], "Name": wp["id"], "group": wp["group"], "region": reg,
                         "pos": [round(v, 1) for v in w], "zone": zone_at(reg, w), "type": "Item"})
    print("region exits %d, waypoints %d" % (len(exits), len(ways)))

    out = {"cell": CELL, "regions": {}, "entrances": ents, "templates": {k: v for k, v in lts.items()},
           "exits": exits, "waypoints": ways}
    for reg, cz in cellzone.items():
        # compact cell list per zone: rows of [z-row, x-start, x-end] runs
        runs = collections.defaultdict(list)
        for (cx, czz), z in sorted(cz.items(), key=lambda kv: (kv[1], kv[0][1], kv[0][0])):
            r = runs[z]
            if r and r[-1][0] == czz and r[-1][2] == cx - 1:
                r[-1][2] = cx
            else:
                r.append([czz, cx, cx])
        out["regions"][reg] = {"zones": zones[reg], "runs": runs}
    json.dump(out, open(OUT, "w", encoding="utf-8"))
    for reg in REGIONS:
        if reg in zones:
            big = sorted(zones[reg].items(), key=lambda kv: -kv[1])[:3]
            nruns = sum(len(v) for v in out["regions"][reg]["runs"].values())
            print("%-11s zones %4d  biggest %s  runs %d  entrances %d" % (
                reg, len(zones[reg]), big, nruns, sum(1 for e in ents if e["region"] == reg)))
    print("entrances total", len(ents))


if __name__ == "__main__":
    main()
