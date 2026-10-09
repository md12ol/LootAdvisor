"""Generates the LootAdvisor mod's derived data. Read-only on the data; writes only into the mod.

  python LootAdvisor/tools/gen_mod_data.py            -> LootAdvisor/Mods/LootAdvisor/...

Inputs (never edited here):
  data/scores/lua/LootData.lua   items (d = per-act display, l = locations) + per-character builds/sets
  data/scores/<char>.json        build class levels + profile (main stats, attack styles) for build matching
  data/items_all/sources.jsonl   item sources with the MapKeys the journal markers need
  data/items_all/levels.json     level -> main level (= the region a marker belongs to)
  data/cache/level_characters_index.json   NPC MapKeys for "is X dead" checks
  game paks Public/*/Flags/*.lsf  story flag names -> GUIDs (Osi.GetFlag needs "<Name>_<GUID>")
Outputs (in the mod source LootAdvisor/Mods/LootAdvisor/):
  ScriptExtender/Lua/Shared/LootData.lua   copy of the scorer's file
  ScriptExtender/Lua/Shared/ModData.lua    markers per item, build classes, flags, NPC uuids
  Story/Journal/Markers/<guid>.lsx         one journal marker per (item, source) target

Marker rule: an item gets markers in an act whose display char is 'm' (fixed
world / container / NPC sources with chance 1) or 't' (trader sources: marker on the trader). Random loot,
rewards (no placed holder) and forge/combo steps get none - the list window covers them.
"""
import json
import os
import re
import shutil
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
ROOT = LA                      # the repo root holds the mod source LootAdvisor/Mods/LootAdvisor
MOD = os.path.join(ROOT, "LootAdvisor", "Mods", "LootAdvisor")
SHARED = os.path.join(MOD, "ScriptExtender", "Lua", "Shared")
MARKERS = os.path.join(MOD, "Story", "Journal", "Markers")
sys.path.insert(0, HERE)

CHARS = ["astarion", "gale", "karlach", "laezel", "shadowheart", "wyll", "darkurge"]
# stable GUID per MarkerID (uuid5 in this namespace), so regenerating never creates new markers
NS = uuid.UUID("2e3407b4-e6ef-4cf7-9de7-25950e9f82f9")
# one journal map marker (.lsx), the same format as the game's own markers in Story/Journal/Markers
TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<save>
    <version major="4" minor="0" revision="9" build="319"/>
    <region id="Markers">
        <node id="root">
            <children>
                <node id="Marker">
                    <attribute id="DisplayText" type="TranslatedString" handle="{handle}" version="1"/>
                    <attribute id="Guid" type="guid" value="{guid}"/>
                    <attribute id="MarkerID" type="FixedString" value="{id}"/>
                    <attribute id="MarkerIcon" type="FixedString" value="{icon}"/>
                    <attribute id="MarkerLevel" type="FixedString" value="{level}"/>
                    <attribute id="MarkerTargetObjectType" type="FixedString" value="{target_type}"/>
                    <attribute id="MarkerTargetObjectUUID" type="FixedString" value="{target}"/>
                    <attribute id="Radius" type="int32" value="0"/>
                </node>
            </children>
        </node>
    </region>
</save>
"""
MAX_MARKERS_PER_ITEM = 6
BOX_MARGIN = 25
BOX_FILTER = False  # off: item boxes cannot tell interiors from real areas (Emerald Grove fell outside)
REGION_ACT = {"WLD_Main_A": 1, "CRE_Main_A": 1, "SCL_Main_A": 2, "INT_Main_A": 2, "BGO_Main_A": 3,
              "CTY_Main_A": 3, "IRN_Main_A": 3, "END_Main": 3}
# player-facing region names (the names the game's map / waypoint list uses)
REGION_NAME = {"WLD_Main_A": "Wilderness", "CRE_Main_A": "Rosymorn Monastery", "SCL_Main_A": "Shadow-Cursed Lands",
               "INT_Main_A": "Road to Baldur's Gate", "BGO_Main_A": "Wyrm's Crossing", "CTY_Main_A": "Baldur's Gate",
               "IRN_Main_A": "Iron Throne", "END_Main": "Upper City"}

# condition path -> flags that say it HAPPENED / that it can no longer happen (names; resolved to GUIDs below).
# Companion deaths and NPC deaths are checked with Osi.IsDead on the NPC (NPCS) as well.
PATHS = {
    "shar": {"yes": ["SHA_NightsongPrison_State_ShadowheartKilledNightsong",
                     "ORI_DarkUrge_KilledIsobel_State_KilledIsobelByKillingNightsong"],
             "no": ["SHA_NightsongPrison_State_NightsongFreed"]},
    "selune": {"yes": ["SHA_NightsongPrison_State_NightsongFreed"],
               "no": ["SHA_NightsongPrison_State_ShadowheartKilledNightsong",
                      "ORI_DarkUrge_KilledIsobel_State_KilledIsobelByKillingNightsong"]},
    "goblins": {"yes": ["DEN_AttackOnDen_State_RaiderVictory", "DEN_AttackOnDen_State_DenLost",
                        "DEN_AttackOnDen_State_DruidsAreDefeated"],
                "no": ["DEN_AttackOnDen_State_DenVictory", "DEN_AttackOnDen_State_Victorious"]},
    "tieflings": {"yes": ["DEN_AttackOnDen_State_DenVictory", "DEN_AttackOnDen_State_Victorious"],
                  "no": ["DEN_AttackOnDen_State_RaiderVictory", "DEN_AttackOnDen_State_DenLost",
                         "DEN_AttackOnDen_State_DruidsAreDefeated"]},
    # isobel_kill = Last Light falls (its traders die): Isobel killed, abducted or knocked out -> the siege runs
    # without protection (research verdict 5). Verified in game: a Durge save has NoProtection=1 while
    # HAV_Isobel_State_IsDead=0 (the Durge's kill sets ORI_DarkUrge_KilledIsobel_Requirement).
    "isobel_kill": {"yes": ["HAV_Isobel_State_IsDead", "ORI_DarkUrge_State_KilledIsobel",
                            "HAV_TakingIsobel_State_KilledIsobel", "HAV_Siege_State_NoProtection",
                            "ORI_DarkUrge_KilledIsobel_Requirement"], "dead": ["S_GLO_Isobel"]},
    "isobel_dead": {"yes": ["HAV_Isobel_State_IsDead", "ORI_DarkUrge_State_KilledIsobel",
                            "HAV_TakingIsobel_State_KilledIsobel", "ORI_DarkUrge_KilledIsobel_Requirement"],
                    "dead": ["S_GLO_Isobel"]},
    "isobel_alive": {"no": ["HAV_Isobel_State_IsDead", "ORI_DarkUrge_State_KilledIsobel",
                            "HAV_TakingIsobel_State_KilledIsobel", "ORI_DarkUrge_KilledIsobel_Requirement"],
                     "deadno": ["S_GLO_Isobel"]},
    "bhaal_accept": {"yes": ["ORI_DarkUrge_State_BhaalAccepted"], "no": ["ORI_DarkUrge_State_BhaalResisted"]},
    "bhaal_refuse": {"yes": ["ORI_DarkUrge_State_BhaalResisted"], "no": ["ORI_DarkUrge_State_BhaalAccepted"]},
    "mizora_freed": {"yes": ["COL_MizorasRescue_State_SavedMizora"],
                     "no": ["COL_MizorasRescue_State_KilledMizora", "MOO_MizorasRescue_Event_WalkedAway"]},
    "ravengard_rescued": {"yes": ["IRN_Ravengard_State_Saved"], "no": ["GLO_Ravengard_State_PermaDefeated"]},
    "astarion_ascends": {"yes": ["ORI_Astarion_State_BecameVampireLord"]},
    "kagha_kill": {"yes": ["DEN_ShadowDruid_State_KaghaIsDead", "DEN_ShadowDruid_State_KaghaKilled"]},
    # (UND_TheDrowNere_Event_Leave is also set in saves where Nere died - not used as "closed")
    "nere_kill": {"yes": [], "dead": ["S_UND_TheDrowNere"]},
    "nere_dead": {"yes": [], "dead": ["S_UND_TheDrowNere"]},
    "tribunal": {"yes": ["LOW_MurderTribunal_State_BecameUnholyAssassin"]},
    "prisoners_rescued": {"yes": ["HAV_SavingPrisoners_State_FlirtyReturned",
                                  "HAV_SavingPrisoners_State_AllTieflingsReturned"]},
    "durge_alfira": {"yes": ["NIGHT_DarkUrge_MurderOfAlfira", "ORI_DarkUrge_MurderOfAlfira_Alternative"]},
    # companion-cost paths: happened = that companion is dead
    "karlach_kill": {"yes": ["GLO_Karlach_State_Dead", "GLO_Karlach_State_PermaDefeated"], "dead": ["S_Player_Karlach"]},
    "shadowheart_kill": {"yes": ["GLO_Shadowheart_State_Dead"], "dead": ["S_Player_ShadowHeart"]},
    "laezel_kill": {"yes": ["GLO_Laezel_State_PermaDefeated"], "dead": ["S_Player_Laezel"]},
    "astarion_kill": {"yes": ["ORI_Astarion_State_Dead"], "dead": ["S_Player_Astarion"]},
    "wyll_kill": {"yes": [], "dead": ["S_Player_Wyll"]},
    "gale_kill": {"yes": [], "dead": ["S_Player_Gale"]},
}
# companion state: in the team (party or camp) / dead
COMPANIONS = {
    "astarion": ("S_Player_Astarion", "GLO_Origin_PartOfTheTeam_Astarion", ["ORI_Astarion_State_Dead"]),
    "gale": ("S_Player_Gale", "GLO_Origin_PartOfTheTeam_Gale", []),
    "karlach": ("S_Player_Karlach", "GLO_Origin_PartOfTheTeam_Karlach",
                ["GLO_Karlach_State_Dead", "GLO_Karlach_State_PermaDefeated"]),
    "laezel": ("S_Player_Laezel", "GLO_Origin_PartOfTheTeam_Laezel", ["GLO_Laezel_State_PermaDefeated"]),
    "shadowheart": ("S_Player_ShadowHeart", "GLO_Origin_PartOfTheTeam_Shadowheart", ["GLO_Shadowheart_State_Dead"]),
    "wyll": ("S_Player_Wyll", "GLO_Origin_PartOfTheTeam_Wyll", []),
    "darkurge": (None, "GLO_Origin_PartOfTheTeam_DarkUrge", []),
    "halsin": ("S_GLO_Halsin", "GLO_Origin_PartOfTheTeam_Halsin", ["GLO_Halsin_State_PermaDefeated"]),
    "jaheira": ("S_Player_Jaheira", "GLO_Origin_PartOfTheTeam_Jaheira", ["GLO_Jaheira_State_PermaDefeated"]),
    "minsc": ("S_Player_Minsc", "GLO_Origin_PartOfTheTeam_Minsc", ["GLO_Minsc_State_PermaDefeated"]),
    "minthara": ("S_Player_Minthara", "GLO_Origin_PartOfTheTeam_Minthara", ["GLO_DrowCommander_State_Dead"]),
}


def lua_str(s):
    s = "" if s is None else str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "") + '"'


def handle_of(text_id):
    s = uuid.uuid5(NS, "handle:" + text_id).hex
    return "h%sg%sg%sg%sg%s" % (s[0:8], s[8:12], s[12:16], s[16:20], s[20:32])


def load_lootdata(path):
    import lupa
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(open(path, encoding="utf-8").read())
    return L.eval("LA.Data")


def flag_index():
    cache = os.path.join(LA, "data", "cache", "flags_index.json")
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    from pak import Pak, GAME_DATA
    import lsf
    out = {}
    for pk in ("Shared.pak", "Gustav.pak", "GustavX.pak"):
        p = Pak(os.path.join(GAME_DATA, pk))
        for n in p.by_name:
            if n.startswith("Public/") and "/Flags/" in n and n.endswith(".lsf"):
                try:
                    node = lsf.load(p.read(p.by_name[n])).regions[0]
                    if node.get("Name") and node.get("UUID"):
                        out[node.get("Name")] = node.get("UUID")
                except Exception:
                    pass
    json.dump(out, open(cache, "w", encoding="utf-8"))
    return out


def main():
    src_lua = os.path.join(LA, "data", "scores", "lua", "LootData.lua")
    os.makedirs(SHARED, exist_ok=True)
    shutil.copyfile(src_lua, os.path.join(SHARED, "LootData.lua"))
    D = load_lootdata(src_lua)
    items = D["items"]
    n_items = len(items)
    levels = json.load(open(os.path.join(LA, "data", "items_all", "levels.json"), encoding="utf-8"))

    # world positions (sub-levels placed as LevelTemplates store local coordinates), zones, entrances:
    # tools/level_links.py + tools/entrances.py (marker on the area's entrance)
    import math
    import entrances as ent_mod
    Z = json.load(open(os.path.join(LA, "data", "cache", "level_zones.json"), encoding="utf-8"))
    _region_w, to_world = ent_mod.make_world(levels, {k: [tuple(x) for x in v] for k, v in Z["templates"].items()})
    CELLZ = Z["cell"]
    cellzone = {}
    for reg, rz in Z["regions"].items():
        cz = {}
        for z, runs in rz["runs"].items():
            for row, a, b in runs:
                for x in range(a, b + 1):
                    cz[(x, row)] = int(z)
        cellzone[reg] = cz

    def zone_at(reg, pos):
        cz = cellzone.get(reg) or {}
        c = (math.floor(pos[0] / CELLZ), math.floor(pos[2] / CELLZ))
        if c in cz:
            return cz[c]
        for r in range(1, 4):
            best, bd = None, 1e9
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    z = cz.get((c[0] + dx, c[1] + dz))
                    if z and dx * dx + dz * dz < bd:
                        best, bd = z, dx * dx + dz * dz
            if best:
                return best
        return None

    links = json.load(open(os.path.join(LA, "data", "cache", "level_links.json"), encoding="utf-8"))
    trig_grid = {}
    for mk, t in links["triggers"].items():
        if t.get("pos"):
            w = to_world(t["level"], t["pos"])
            trig_grid.setdefault((math.floor(w[0] / 8), math.floor(w[2] / 8)), []).append((mk, w, t["level"]))

    # fallback anchor for a trader without a trigger nearby: the nearest placed item (a stall, a counter...)
    item_grid = {}
    for pl in json.load(open(os.path.join(LA, "data", "cache", "level_items_index.json"), encoding="utf-8")):
        if pl.get("position") and pl.get("MapKey"):
            w = to_world(pl.get("level") or "", pl["position"])
            item_grid.setdefault((math.floor(w[0] / 8), math.floor(w[2] / 8)), []).append(
                (pl["MapKey"], w, pl.get("level") or ""))

    def nearest_in(grid, w, region, maxd):
        best, bd = None, maxd
        c = (math.floor(w[0] / 8), math.floor(w[2] / 8))
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for mk, tw, lvl in grid.get((c[0] + dx, c[1] + dz), []):
                    d = math.dist((w[0], w[1], w[2]), (tw[0], tw[1], tw[2]))
                    if d < bd and region_of(lvl) == region:
                        best, bd = (mk, tw), d
        return best

    def nearest_trigger(w, region, maxd=12.0):
        best, bd = None, maxd
        c = (math.floor(w[0] / 8), math.floor(w[2] / 8))
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for mk, tw, lvl in trig_grid.get((c[0] + dx, c[1] + dz), []):
                    d = math.dist((w[0], w[1], w[2]), (tw[0], tw[1], tw[2]))
                    if d < bd and region_of(lvl) == region:
                        best, bd = (mk, tw), d
        return best

    def region_of(level):
        if level in REGION_ACT:
            return level
        ml = (levels.get(level) or {}).get("main_level")
        if ml:
            return ml
        for tok in level.split("_"):  # platform / template levels: PLT_BGO_Circus_A -> BGO_Main_A
            for reg in REGION_ACT:
                if reg.split("_")[0].upper() == tok.upper():
                    return reg
        return level

    # playable box per region = where its sub-levels' placements are (1st-99th percentile + margin). Interiors are
    # stored elsewhere in the main level's own coordinates (e.g. the Counting House vault at x -966 z 759 while the
    # Lower City is x -255..162): a marker there would sit off the map, so those sources get no marker.
    boxes = {}
    pts = {}
    for pl in json.load(open(os.path.join(LA, "data", "cache", "level_items_index.json"), encoding="utf-8")):
        lvn = pl.get("level") or ""
        reg = region_of(lvn)
        if reg in REGION_ACT and lvn != reg and pl.get("position"):
            pts.setdefault(reg, []).append(pl["position"])
    for reg, ps in pts.items():
        xs = sorted(q[0] for q in ps)
        zs = sorted(q[2] for q in ps)
        lo, hi = int(0.01 * (len(xs) - 1)), int(0.99 * (len(xs) - 1))
        boxes[reg] = (xs[lo] - BOX_MARGIN, xs[hi] + BOX_MARGIN, zs[lo] - BOX_MARGIN, zs[hi] + BOX_MARGIN)
    print("boxes", {k: tuple(round(v) for v in b) for k, b in boxes.items()})

    def on_map(region, p):
        b = boxes.get(region)
        return b is None or (b[0] <= p[0] <= b[1] and b[2] <= p[2] <= b[3])

    # sources by stats id
    want = {}
    for i in range(1, n_items + 1):
        it = items[i]
        d = it["d"] or "---"
        if "m" in d or "t" in d:
            want[it["id"]] = i
    sources = {}
    with open(os.path.join(LA, "data", "items_all", "sources.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["stats_id"] in want:
                sources.setdefault(r["stats_id"], []).append(r)

    if os.path.isdir(MARKERS):
        shutil.rmtree(MARKERS)
    os.makedirs(MARKERS)

    marker_lua = []
    interior = []
    n_markers = 0
    no_marker = []
    for sid, idx in sorted(want.items(), key=lambda kv: kv[1]):
        it = items[idx]
        d = it["d"]
        cands = []
        for r in sources.get(sid, []):
            act = r.get("act")
            if not isinstance(act, int) or act < 1 or act > 3:
                act = REGION_ACT.get(region_of(r.get("level") or ""), None)
            if not act:
                continue
            mode = d[act - 1] if len(d) >= act else "-"
            k = r["kind"]
            target = ttype = None
            if mode == "t" and k == "trader" and r.get("holder") and r["holder"].get("MapKey"):
                if (r.get("chance") or 0) < 0.25:
                    continue
                target, ttype = r["holder"]["MapKey"], "Character"
                # round 2 (B): a FIXED marker at the trader's usual spot = the nearest trigger to the trader's
                # placement (a Character marker follows the NPC and the game draws it only when the NPC is near)
                if r.get("position"):
                    nt = nearest_trigger(to_world(r.get("level") or "", r["position"]), region_of(r.get("level") or ""))
                    if nt:
                        target, ttype = nt[0], "Trigger"
                    else:
                        ni = nearest_in(item_grid, to_world(r.get("level") or "", r["position"]),
                                        region_of(r.get("level") or ""), 8.0)
                        if ni:
                            target, ttype = ni[0], "Item"
            elif mode == "m" and (r.get("chance") or 0) >= 0.99:
                if k == "world" and r.get("instance"):
                    target, ttype = r["instance"], "Item"
                elif k == "container" and r.get("container") and r["container"].get("MapKey"):
                    target, ttype = r["container"]["MapKey"], "Item"
                elif k in ("npc_equipped", "npc_inventory") and r.get("holder") and r["holder"].get("MapKey"):
                    target, ttype = r["holder"]["MapKey"], "Character"
                elif k == "trader" and r.get("holder") and r["holder"].get("MapKey"):
                    target, ttype = r["holder"]["MapKey"], "Character"
            if not target or not r.get("position"):
                continue
            if BOX_FILTER and not on_map(region_of(r.get("level") or ""), r["position"]):
                interior.append((sid, r.get("region"), r.get("level")))
                continue
            cands.append((-(r.get("chance") or 0), act, target, ttype, r))
        cands.sort(key=lambda c: (c[0], c[1]))
        seen, rows = set(), []
        for _, act, target, ttype, r in cands:
            if target in seen or len(rows) >= MAX_MARKERS_PER_ITEM:
                continue
            seen.add(target)
            mid = "LA_%s_%d" % (sid, len(rows) + 1)
            guid = str(uuid.uuid5(NS, mid))
            h = handle_of(mid)
            region = region_of(r.get("level") or "")
            with open(os.path.join(MARKERS, guid + ".lsx"), "w", encoding="utf-8", newline="\n") as f:
                f.write(TEMPLATE.format(guid=guid, id=mid, target=target, target_type=ttype, level=region,
                                        handle=h, icon="QuestMarker"))
            p = to_world(r.get("level") or "", r["position"])
            zone = zone_at(region, p)
            who = (r.get("holder") or r.get("container") or {}).get("name") or ""
            rows.append("{m=%s,h=%s,r=%s,a=%d,k=%s,tt=%s,t=%s,x=%.1f,y=%.1f,z=%.1f,zn=%s,w=%s,rg=%s,lv=%s}" % (
                lua_str(mid), lua_str(h), lua_str(region), act, lua_str(r["kind"]), lua_str(ttype),
                lua_str(target), p[0], p[1], p[2], zone or "nil", lua_str(who[:40]),
                lua_str((r.get("region") or "")[:48]), lua_str(r.get("level") or "")))
            n_markers += 1
        if rows:
            marker_lua.append("  [%s] = { %s }," % (lua_str(sid), ", ".join(rows)))
        else:
            no_marker.append(sid)

    # entrance markers (one journal marker per zone-crossing link; label written at runtime)
    ent_lua = {}
    n_ent = 0
    for e in Z["entrances"]:
        mid = "LAE_%s_%d_%d" % (e["MapKey"][:8], e["zfrom"], e["zto"])
        guid = str(uuid.uuid5(NS, mid))
        h = handle_of(mid)
        with open(os.path.join(MARKERS, guid + ".lsx"), "w", encoding="utf-8", newline="\n") as f:
            f.write(TEMPLATE.format(guid=guid, id=mid, target=e["MapKey"], target_type=e.get("type", "Item"),
                                    level=e["region"], handle=h, icon="QuestMarker"))
        ent_lua.setdefault(e["region"], []).append(
            "{m=%s,h=%s,zf=%d,zt=%d,x=%.1f,z=%.1f,tx=%.1f,tz=%.1f,n=%s}" % (
                lua_str(mid), lua_str(h), e["zfrom"], e["zto"], e["pos"][0], e["pos"][2], e["to"][0], e["to"][2],
                lua_str((e.get("Name") or "")[:48])))
        n_ent += 1
    # ways to other regions (round 3): region-swap teleporters and waypoints, one journal marker each
    def way_rows(items, prefix):
        rows = {}
        for e in items:
            mid = "%s_%s" % (prefix, e["MapKey"][:8])
            guid = str(uuid.uuid5(NS, mid))
            h = handle_of(mid)
            with open(os.path.join(MARKERS, guid + ".lsx"), "w", encoding="utf-8", newline="\n") as f:
                f.write(TEMPLATE.format(guid=guid, id=mid, target=e["MapKey"], target_type=e.get("type", "Item"),
                                        level=e["region"], handle=h, icon="QuestMarker"))
            rows.setdefault(e["region"], []).append("{m=%s,h=%s,to=%s,x=%.1f,z=%.1f,zn=%s,n=%s}" % (
                lua_str(mid), lua_str(h), lua_str(e.get("to_region") or ""), e["pos"][0], e["pos"][2],
                e.get("zone") or "nil", lua_str(e.get("Name") or "")))
        return rows
    exit_rows = way_rows(Z.get("exits", []), "LAX")
    wayp_rows = way_rows(Z.get("waypoints", []), "LAW")
    print("region exits %d, waypoints %d" % (len(Z.get("exits", [])), len(Z.get("waypoints", []))))
    zone_lua = []
    for reg, rz in Z["regions"].items():
        parts = []
        for z, runs in rz["runs"].items():
            parts.append("[%s]=%s" % (z, lua_str(";".join("%d,%d,%d" % tuple(r) for r in runs))))
        zone_lua.append("  %s = { %s }," % (reg, ", ".join(parts)))
    print("entrance markers %d" % n_ent)

    # builds
    build_lua = []
    for c in CHARS:
        fn = os.path.join(LA, "data", "scores", c + ".json")
        if not os.path.exists(fn):
            continue
        j = json.load(open(fn, encoding="utf-8"))
        rows = []
        for bid, b in j["builds"].items():
            cl = ",".join("%s=%d" % (k, v) for k, v in (b.get("classes") or {}).items())
            prof = b.get("profile") or {}
            stats = prof.get("stats") or {}
            main = max(stats, key=lambda k: stats[k]) if stats else ""
            att = prof.get("attacks") or {}
            atk = max(att, key=lambda k: att[k]) if att else ""
            rows.append("%s={cl={%s},main=%s,atk=%s,caster=%s}" % (bid, cl, lua_str(main), lua_str(atk),
                                                                    lua_str(prof.get("caster") or 0)))
        build_lua.append("  %s = { %s }," % (c, ", ".join(rows)))

    # flags + npcs
    F = flag_index()
    names = set()
    for p in PATHS.values():
        for k in ("yes", "no"):
            names.update(p.get(k, []))
    for _, team, dead in COMPANIONS.values():
        names.add(team)
        names.update(dead)
    flag_lua, missing = [], []
    for nm in sorted(names):
        if nm in F:
            flag_lua.append("  %s = %s," % (nm, lua_str("%s_%s" % (nm, F[nm]))))
        else:
            missing.append(nm)
    chars_idx = json.load(open(os.path.join(LA, "data", "cache", "level_characters_index.json"), encoding="utf-8"))
    npc_names = set()
    for p in PATHS.values():
        npc_names.update(p.get("dead", []))
        npc_names.update(p.get("deadno", []))
    for u, _, _ in COMPANIONS.values():
        if u:
            npc_names.add(u)
    npc = {}
    for r in chars_idx:
        if r.get("Name") in npc_names and r.get("MapKey"):
            npc.setdefault(r["Name"], r["MapKey"])
    npc_lua = ["  %s = %s," % (k, lua_str(v)) for k, v in sorted(npc.items())]

    def lua_list(xs):
        return "{" + ",".join(lua_str(x) for x in xs) + "}"
    path_lua = []
    for k, p in PATHS.items():
        path_lua.append("  %s = {yes=%s,no=%s,dead=%s,deadno=%s}," % (
            k, lua_list([x for x in p.get("yes", []) if x in F]), lua_list([x for x in p.get("no", []) if x in F]),
            lua_list(p.get("dead", [])), lua_list(p.get("deadno", []))))
    comp_lua = []
    for k, (u, team, dead) in COMPANIONS.items():
        comp_lua.append("  %s = {npc=%s,team=%s,dead=%s}," % (k, lua_str(u or ""), lua_str(team if team in F else ""),
                                                              lua_list([x for x in dead if x in F])))
    region_lua = ["  %s = %d," % (k, v) for k, v in REGION_ACT.items()]

    out = ["-- LootAdvisor derived data (generated, do not edit).",
           "-- markers[stats id] = { {m=MarkerID, h=DisplayText handle, r=region (MarkerLevel), a=act, k=source kind,",
           "--   tt=target type, t=target MapKey, x,y,z, w=holder/container name, rg=area name, lv=level}, ... }",
           "LA = LA or {}", "LA.Mod = {}", "LA.Mod.markers = {"] + marker_lua + ["}",
           "-- builds[char][build id] = { cl={Class=levels}, main=main ability, atk=main attack style, caster }",
           "LA.Mod.builds = {"] + build_lua + ["}",
           "-- story flag name -> Osiris flag string (Name_GUID)", "LA.Mod.flags = {"] + flag_lua + ["}",
           "-- NPC name -> MapKey (global characters, for Osi.IsDead)", "LA.Mod.npcs = {"] + npc_lua + ["}",
           "-- condition paths: yes = happened when any flag set (or any 'dead' NPC dead); no = can no longer happen",
           "LA.Mod.paths = {"] + path_lua + ["}",
           "LA.Mod.companions = {"] + comp_lua + ["}",
           "LA.Mod.regionAct = {"] + region_lua + ["}",
           "-- zones: cell size; per region [zone] = 'row,x0,x1;...' runs of occupied %d m grid cells"
           % CELLZ, "LA.Mod.zoneCell = %s" % CELLZ, "LA.Mod.zones = {"] + zone_lua + ["}",
           "-- entrances[region] = { {m, h, zf=from zone, zt=to zone, x,z=marker spot, tx,tz=arrival, n=object name} }",
           "LA.Mod.entrances = {"] + ["  %s = { %s }," % (k, ", ".join(v)) for k, v in ent_lua.items()] + ["}",
           "-- exits[region] = region-swap teleporters { {m, h, to=destination region, x, z, zn, n} }",
           "LA.Mod.exits = {"] + ["  %s = { %s }," % (k, ", ".join(v)) for k, v in exit_rows.items()] + ["}",
           "-- waypoints[region] = fast-travel waypoints { {m, h, x, z, zn, n} } (fallback way to another region)",
           "LA.Mod.waypoints = {"] + ["  %s = { %s }," % (k, ", ".join(v)) for k, v in wayp_rows.items()] + ["}",
           "LA.Mod.regionName = {"] + ["  %s = %s," % (k, lua_str(v)) for k, v in REGION_NAME.items()] + ["}"]
    with open(os.path.join(SHARED, "ModData.lua"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("items %d, marker items %d, markers %d, items without marker %d" % (n_items, len(marker_lua), n_markers,
                                                                          len(no_marker)))
    print("flags %d resolved, missing: %s" % (len(flag_lua), missing))
    print("npcs %s" % npc)
    print("sources skipped as off-map interiors: %d" % len(interior))
    json.dump({"no_marker": no_marker, "missing_flags": missing, "interior": interior},
              open(os.path.join(LA, "data", "cache", "mod_gen_report.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
