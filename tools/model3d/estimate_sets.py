"""Size estimate for 3D models of every set on the sets page (dedupes shared pieces).

  python tools/model3d/estimate_sets.py   -> data/cache/model3d/estimate.json + printed summary

Resolves every visible equipped item of every set id in artifact/sets.html to its visual resources for the
character's body (resolve_visuals.py chain) and sums the game-file sizes of the UNIQUE meshes and textures.
Raw GR2 = decompressed GR2 section bytes (vertex + index data, LOD0 file), a good proxy for an unquantized glTF.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import resolve_visuals as rv  # noqa: E402
import build_cache as bc  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

ROOT = rv.ROOT
# Dark Urge: the player's own body; the race is read from the save later - HUM_M as a placeholder here
RACES = {k: v["races"] for k, v in rv.ORIGINS.items()}
RACES["darkurge"] = ["HUM_M"]


def main():
    html = open(os.path.join(ROOT, "artifact", "sets.html"), encoding="utf-8").read()
    ids = sorted(set(re.findall(r'"id":"([a-z_]+\.[a-z0-9_]+\.a[123]\.[0-9]+)"', html)))
    paks = {pk: Pak(os.path.join(GAME_DATA, pk)) for pk in bc.PAKS}
    allt, _ = bc.load_all_templates(paks)
    by_name, stat_of = {}, {}
    for k, (pk, mod, g) in allt.items():
        by_name.setdefault(g.get("Name"), []).append(k)
        if g.get("Stats") and g.get("Type") == "item":
            stat_of.setdefault(g.get("Stats"), []).append(k)
    R = rv.Res()
    scores = {}
    vis_cache = {}
    per_char = {}
    unresolved = set()
    sets_out = {}
    for sid_set in ids:
        char, build, act, n = sid_set.split(".")
        if char not in scores:
            scores[char] = json.load(open(os.path.join(ROOT, "data", "scores", f"{char}.json"), encoding="utf-8"))
        try:
            st = scores[char]["builds"][build]["sets"][act[1:]][int(n) - 1]
        except (KeyError, IndexError):
            continue
        pc = per_char.setdefault(char, {"items": set(), "visuals": set()})
        vis_ids = []
        for slot, it in st["items"].items():
            if slot not in rv.VISIBLE_SLOTS:
                continue
            key = (char, it["sid"])
            if key not in vis_cache:
                hit = rv.item_visuals(allt, by_name, it["sid"], RACES[char])
                if hit is None:
                    for k in stat_of.get(it["sid"], []):
                        hit = rv.item_visuals(allt, {it["sid"]: [k]}, it["sid"], RACES[char])
                        if hit:
                            break
                vis_cache[key] = hit["visuals"] if hit else []
                if not hit:
                    unresolved.add(it["sid"])
            pc["items"].add(it["sid"])
            pc["visuals"].update(vis_cache[key])
            vis_ids += vis_cache[key]
        sets_out[sid_set] = vis_ids

    vinfo = {}
    allv = set().union(*[p["visuals"] for p in per_char.values()])
    for v in allv:
        r = R.visual(v)
        tex = {}
        for m in r.get("materials", []):
            for t in m.get("textures", []):
                if t.get("file"):
                    tex[t["file"]] = (t.get("bytes") or 0, t.get("w") or 0, t.get("h") or 0)
            for t in m.get("virtual_textures", []):
                if t.get("gtex"):
                    tex["VT:" + t["gtex"]] = (t.get("vt_bytes") or 0, 0, 0)
        vinfo[v] = {"name": r.get("name"), "raw": r.get("gr2_decompressed") or 0, "gr2": r.get("gr2_bytes") or 0,
                    "mats": len(r.get("materials", [])), "tex": tex}

    def summarize(vs):
        raw = sum(vinfo[v]["raw"] for v in vs)
        mats = sum(vinfo[v]["mats"] for v in vs)
        tex = {}
        for v in vs:
            tex.update(vinfo[v]["tex"])
        return raw, mats, len(tex)

    out = {"sets": len(sets_out), "unresolved_items": sorted(unresolved), "per_char": {}}
    print(f"{len(sets_out)} sets, {len(allv)} unique item visuals, unresolved items: {len(unresolved)}")
    tot_raw = tot_mats = 0
    for char, pc in sorted(per_char.items()):
        raw, mats, ntex = summarize(pc["visuals"])
        tot_raw += raw
        tot_mats += mats
        out["per_char"][char] = {"items": len(pc["items"]), "visuals": len(pc["visuals"]), "raw_mesh_bytes": raw,
                                 "materials": mats, "texture_sets": ntex}
        print(f"  {char:12s} items {len(pc['items']):3d}  visuals {len(pc['visuals']):3d}  raw mesh {raw/1e6:6.1f} MB"
              f"  materials {mats:4d}  texture sets {ntex}")
    graw, gmats, gtex = summarize(allv)
    out.update(global_unique_visuals=len(allv), global_raw_mesh_bytes=graw, global_materials=gmats)
    print(f"  deduped across characters: {len(allv)} visuals, raw mesh {graw/1e6:.1f} MB, materials {gmats}")
    per_set = [sum(vinfo[v]["raw"] for v in vs) for vs in sets_out.values()]
    out.update(total_raw_mesh=tot_raw, total_materials=tot_mats,
               per_set_raw_mesh_avg=sum(per_set) / max(1, len(per_set)), per_set_raw_mesh_max=max(per_set))
    print(f"  total raw mesh {tot_raw/1e6:.1f} MB, materials {tot_mats}; per set avg "
          f"{out['per_set_raw_mesh_avg']/1e6:.2f} MB max {out['per_set_raw_mesh_max']/1e6:.2f} MB (items only)")
    with open(os.path.join(rv.CACHE, "estimate.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
