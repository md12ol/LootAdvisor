"""Resolve EVERY set of every origin down to the game's visual resources (step 1 of the all-sets build, 3D_ALL.md).

  python tools/model3d/catalog.py            -> data/cache/model3d/catalog.json

For each origin: the character visual (head / hair / body / private parts slots, skeleton, material presets) and the
equipment race chain from EquipmentSettings/EquipmentRaces.lsx (own race first, then its DefaultParent, like the
game). For each set in data/scores/<char>.json: every visible slot -> item root template (stats RootTemplate, then
the template Name) -> Equipment/Visuals[race chain] or VisualTemplate -> VisualBank records (resolve_visuals.Res).
Weapons also get their stats (Proficiency Group, Weapon Properties, Slot) so the builder can pick the stance.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import build_cache as bc  # noqa: E402
import resolve_visuals as rv  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

ROOT = rv.ROOT
CACHE = rv.CACHE
NULL = rv.NULL
CHARS = ["astarion", "darkurge", "gale", "karlach", "laezel", "shadowheart", "wyll"]
# origin template + equipment race (EquipmentRaces.lsx Name). The Dark Urge uses the game's default Dark Urge
# (white dragonborn male), the race the scores use too.
ORIGINS = {
    "astarion": ("ORIGIN_Astarion", "Elf/Drow Male"),
    "darkurge": ("Dragonborn_Male_Player_DarkUrge", "Dragonborn Male"),
    "gale": ("ORIGIN_Gale", "Human Male"),
    "karlach": ("ORIGIN_Karlach", "Tiefling Karlach"),
    "laezel": ("ORIGIN_Laezel", "Githyanki Female"),
    "shadowheart": ("ORIGIN_Shadowheart", "Half-Elf Female"),
    "wyll": ("ORIGIN_Wyll", "Human Male"),
}
VISIBLE = rv.VISIBLE_SLOTS


def equipment_races():
    """EquipmentRaces.lsx (SharedDev overrides Shared) -> {name: (guid, parent guid)}."""
    p = Pak(os.path.join(GAME_DATA, "Shared.pak"))
    out = {}
    for path in ("Mods/Shared/EquipmentSettings/EquipmentRaces.lsx", "Mods/SharedDev/EquipmentSettings/EquipmentRaces.lsx"):
        e = p.by_name.get(path)
        if not e:
            continue
        t = p.read(e).decode("utf-8", "replace")
        for n in re.findall(r'<node id="EquipmentRace">(.*?)</node>', t, re.S):
            a = dict(re.findall(r'id="(\w+)" value="([^"]*)"', n))
            out[a["Name"]] = (a["Guid"], a.get("DefaultParent"))
    return out


def race_chain(races, name):
    by_guid = {g: (n, par) for n, (g, par) in races.items()}
    g = races[name][0]
    chain = []
    while g and g not in chain:
        chain.append(g)
        g = by_guid.get(g, (None, None))[1]
    return chain


def visualset_overrides(eq):
    """Equipment/VisualSet/MaterialOverrides -> enabled Vector3/Scalar parameters + material presets per group
    (the "02 Colour" dye presets most items use) + the ColorPreset."""
    out = {"vectors": {}, "scalars": {}, "presets": {}, "color_preset": None}
    vs = eq.child("VisualSet") if eq else None
    mo = vs.child("MaterialOverrides") if vs else None
    for c in (mo.children if mo else []):
        if c.name == "Vector3Parameters" and c.get("Enabled"):
            out["vectors"][c.get("Parameter")] = [round(x, 5) for x in c.get("Value")]
        elif c.name == "ScalarParameters" and c.get("Enabled"):
            out["scalars"][c.get("Parameter")] = c.get("Value")
        elif c.name == "MaterialPresets":
            for o in c.children:
                if o.get("MaterialPresetResource"):
                    out["presets"][o.get("GroupName") or o.get("MapKey")] = o.get("MaterialPresetResource")
        elif c.name == "ColorPreset" and c.get("MaterialPresetResource"):
            out["color_preset"] = c.get("MaterialPresetResource")
    return out


def item_visuals(allt, keys, chain):
    """Template keys -> first hit of Equipment/Visuals for the race chain, else VisualTemplate (rv.item_visuals)."""
    for k in keys:
        chain_t = rv.template_chain(allt, k)
        ov = {"vectors": {}, "scalars": {}, "presets": {}, "color_preset": None}
        for g in chain_t:     # the most specific template with any colour override wins (child before parent)
            o = visualset_overrides(g.child("Equipment"))
            if o["vectors"] or o["scalars"] or o["presets"] or o["color_preset"]:
                ov = o
                break
        for g in chain_t:
            eq = g.child("Equipment")
            vis = eq.child("Visuals") if eq else None
            if vis and vis.children:
                for race in chain:
                    for o in vis.children:
                        if o.get("MapKey") == race:
                            ids = [mv.get("Object") for mv in o.children if mv.get("Object")]
                            if ids:
                                return {"template": g.get("Name"), "race": race, "kind": "equipment", "visuals": ids,
                                        "tints": ov,
                                        "equip_slots": [c.get("Object") for c in eq.children_named("Slot")]}
            vt = g.get("VisualTemplate")
            if vt and vt != NULL:
                return {"template": g.get("Name"), "race": None, "kind": "visual_template", "visuals": [vt],
                        "tints": ov, "equip_slots": []}
    return None


def template_icon(allt, keys):
    for k in keys:
        for g in rv.template_chain(allt, k):
            if g.get("Icon"):
                return g.get("Icon")
    return None


def main(argv):
    t0 = time.time()
    paks = {pk: Pak(os.path.join(GAME_DATA, pk)) for pk in bc.PAKS}
    allt, _ = bc.load_all_templates(paks)
    by_name = {}
    for k, (pk, mod, g) in allt.items():
        by_name.setdefault(g.get("Name"), []).append(k)
    stats = json.load(open(os.path.join(ROOT, "data", "cache", "stats_resolved.json"), encoding="utf-8"))
    races = equipment_races()
    R = rv.Res()
    print("loaded %.0fs" % (time.time() - t0))
    visuals = {}

    def vis(vid):
        if vid and vid not in visuals:
            visuals[vid] = R.visual(vid)
        return vid

    chars, sets, unresolved = {}, {}, {}
    for char in CHARS:
        tname, race = ORIGINS[char]
        tk = [k for k in by_name.get(tname, []) if allt[k][2].get("Type") == "character"][0]
        cvr = allt[tk][2].get("CharacterVisualResourceID")
        cv = R.banks["CharacterVisualBank"][cvr]
        ca = cv["attributes"]
        base = R.banks["VisualBank"].get(ca.get("BaseVisual"), {}).get("attributes", {})
        skel = R.banks["SkeletonBank"].get(base.get("SkeletonResource"), {}).get("attributes", {})
        slots = []
        presets = {}
        for c in cv.get("children", []):
            if c["name"] == "Slots":
                sa = c["attributes"]
                slots.append({"slot": sa.get("Slot"), "bone": sa.get("Bone") or None, "visual": vis(sa.get("VisualResource"))})
            if c["name"] == "MaterialOverrides":
                for mp in c.get("children", []):
                    for ob in mp.get("children", []) if mp["name"] == "MaterialPresets" else []:
                        presets[ob["attributes"].get("GroupName")] = ob["attributes"].get("MaterialPresetResource")
        chars[char] = {"template": tname, "template_id": tk, "character_visual": cvr, "name": ca.get("Name"),
                       "equipment_race": race, "race_chain": race_chain(races, race),
                       "base_visual": base.get("Name"), "skeleton": skel.get("SourceFile"),
                       "body": vis(ca.get("BodySetVisual")), "slots": slots, "material_presets": presets}
        scores = json.load(open(os.path.join(ROOT, "data", "scores", f"{char}.json"), encoding="utf-8"))
        for build, bd in scores["builds"].items():
            for act, lst in bd["sets"].items():
                for st in lst:
                    pieces = []
                    for slot, it in st["items"].items():
                        if slot not in VISIBLE:
                            continue
                        sid = it["sid"]
                        s = stats.get(sid) or {}
                        keys = [s["RootTemplate"]] if s.get("RootTemplate") in allt else []
                        keys += [k for k in by_name.get(sid, []) if k not in keys]
                        hit = item_visuals(allt, keys, chars[char]["race_chain"])
                        rec = {"slot": slot, "sid": sid, "name": it["name"], "icon": template_icon(allt, keys)}
                        if s.get("Slot") in ("Melee Main Weapon", "Melee Offhand Weapon", "Ranged Main Weapon",
                                             "Ranged Offhand Weapon") or s.get("Proficiency Group"):
                            rec["weapon"] = {"slot": s.get("Slot"), "prof": s.get("Proficiency Group"),
                                             "props": s.get("Weapon Properties"), "group": s.get("Weapon Group")}
                        if hit:
                            rec.update(kind=hit["kind"], race=hit["race"], template=hit["template"],
                                       tints=hit["tints"], equip_slots=hit["equip_slots"],
                                       visuals=[vis(v) for v in hit["visuals"]])
                        else:
                            rec["unresolved"] = True
                            unresolved.setdefault(sid, []).append(st["id"])
                        pieces.append(rec)
                    sets[st["id"]] = {"char": char, "build": build, "act": int(act), "name": st["name"],
                                      "pieces": pieces}
    missing = sorted(v for v, r in visuals.items() if r.get("missing") or not r.get("gr2"))
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "chars": chars, "sets": sets, "visuals": visuals,
           "unresolved": unresolved, "missing_visuals": missing}
    path = os.path.join(CACHE, "catalog.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    n_items = len({(s["char"], p["sid"]) for s in sets.values() for p in s["pieces"]})
    print(f"{len(sets)} sets, {n_items} (char, item) pieces, {len(visuals)} visuals, unresolved items "
          f"{len(unresolved)}: {sorted(unresolved)[:10]}, visuals without mesh {len(missing)}")
    print("-> %s (%.1f MB, %.0fs)" % (path, os.path.getsize(path) / 1e6, time.time() - t0))


if __name__ == "__main__":
    main(sys.argv)
