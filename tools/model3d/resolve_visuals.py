"""Resolve what a character looks like wearing a synergy set, down to the game files (read-only).

  python tools/model3d/resolve_visuals.py [char] [set_id]      default: astarion astarion.thx.a3.1
  -> data/cache/model3d/<set_id>.json  (manifest: pieces -> GR2 meshes -> materials -> textures, with sizes)

Chain (steps 1-2 of the 3D feasibility test, artifact/3D_RESULTS.md):
  origin root template (Gustav.pak RootTemplates, Name ORIGIN_<Char>) -> CharacterVisualResourceID
  -> CharacterVisualBank: BaseVisual (skeleton), BodySetVisual (naked body), Slots (Head, Hair, ...)
  equipped item -> root template (+ ParentTemplateId chain) -> Equipment/Visuals[equipment race] or VisualTemplate
  -> VisualBank: SourceFile (.GR2 in Models.pak) + Objects (mesh -> MaterialID per LOD)
  -> MaterialBank: Texture2DParameters (TextureBank -> .DDS in Textures*.pak), VirtualTextureParameters
     (VirtualTextureBank -> GTex hash -> VirtualTextures*.pak tiles)
Needs data/cache/model3d/banks.json (bank_index.py).
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import build_cache as bc  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

CACHE = os.path.join(ROOT, "data", "cache", "model3d")
NULL = "00000000-0000-0000-0000-000000000000"

# equipment race keys (Equipment/Visuals MapKey), derived from the visual names they map to (HUM_M, ELF_M ...)
EQUIP_RACES = {
    "7d73f501-f65e-46af-a13b-2cacf3985d05": "HUM_M", "71180b76-5752-4a97-b71f-911a69197f58": "HUM_F",
    "e39505f7-f576-4e70-a99e-8e29cd381a11": "HUM_MS", "47c0315c-7dc6-4862-b39b-8bf3a10f8b54": "HUM_FS",
    "f07faafa-0c6f-4f79-a049-70e96b23d51b": "GTY_M", "06aaae02-bb9e-4fa3-ac00-b08e13a5b0fa": "GTY_F",
    "abf674d2-2ea4-4a74-ade0-125429f69f83": "DWR_M", "b4a34ce7-41be-44d9-8486-938fe1472149": "DWR_F",
    "a933e2a8-aee1-4ecb-80d2-8f47b706f024": "HFL_M", "8f00cf38-4588-433a-8175-8acdbbf33f33": "HFL_F",
    "5640e766-aa53-428d-815b-6a0b4ef95aca": "GNO_M", "c491d027-4332-4fda-948f-4a3df6772baa": "GNO_F",
    "9a8bbeba-850c-402f-bac5-ff15696e6497": "DGB_M", "6d38f246-15cb-48b5-9b85-378016a7a78e": "DGB_F",
    "6dd3db4f-e2db-4097-b82e-12f379f94c2e": "HRC_M", "eb81b1de-985e-4e3a-8573-5717dc1fa15c": "HRC_F",
    "6503c830-9200-409a-bd26-895738587a4a": "TIF_M", "cf421f4e-107b-4ae6-86aa-090419c624a5": "TIF_F",
    "f625476d-29ec-4a6d-9086-42209af0cf6f": "TIF_MS", "a5789cd3-ecd6-411b-a53a-368b659bc04a": "TIF_FS",
    "7dd0aa66-5177-4f65-b7d7-187c02531b0b": "ELF_M", "ad21d837-2db5-4e46-8393-7d875dd71287": "ELF_F",
}
# per origin: equipment race keys to try in order (own race first, then the body it shares)
ORIGINS = {
    "astarion": {"template": "ORIGIN_Astarion", "races": ["ELF_M", "HUM_M"]},
    "gale": {"template": "ORIGIN_Gale", "races": ["HUM_M"]},
    "wyll": {"template": "ORIGIN_Wyll", "races": ["HUM_M"]},
    "shadowheart": {"template": "ORIGIN_Shadowheart", "races": ["ELF_F", "HUM_F"]},
    "laezel": {"template": "ORIGIN_Laezel", "races": ["GTY_F", "HUM_F"]},
    "karlach": {"template": "ORIGIN_Karlach", "races": ["TIF_FS", "HUM_FS"]},
}
RACE_KEY = {v: k for k, v in EQUIP_RACES.items()}
VISIBLE_SLOTS = ("MainHand", "OffHand", "Ranged", "RangedOff", "Helmet", "Cloak", "Breast", "Gloves", "Boots")


def gr2_info(data):
    """GR2 header -> (file size, sum of decompressed section sizes, compression types)."""
    try:
        # magic(16) headerSize(4) format(4) reserved(8) | FileInfo: version, totalSize, crc, sectionsOffset, nSections
        info = 0x20
        version, total, crc, sec_off, nsec = struct.unpack_from("<5I", data, info)
        if version >= 7:  # 64-bit file info layout keeps the same first 5 fields
            pass
        base = info + sec_off
        dsize, comps = 0, set()
        for i in range(nsec):
            comp, off, clen, dlen = struct.unpack_from("<4I", data, base + i * 44)
            dsize += dlen
            comps.add(comp)
        return dsize, sorted(comps)
    except struct.error:
        return None, []


def fsize(e):
    return None if e is None else (e.size or e.size_on_disk)


class Res:
    def __init__(self):
        self.banks = json.load(open(os.path.join(CACHE, "banks.json"), encoding="utf-8"))
        self.models = Pak(os.path.join(GAME_DATA, "Models.pak"))
        self.tex = Pak(os.path.join(GAME_DATA, "Textures.pak"))
        self.vt = Pak(os.path.join(GAME_DATA, "VirtualTextures.pak"))
        self.files = {}
        for p in (self.models, self.tex, self.vt):
            for e in p.entries:
                self.files[e.name.lower()] = (p, e)
        self.vt_by_hash = {}
        for e in self.vt.entries:
            b = os.path.basename(e.name)
            self.vt_by_hash.setdefault(os.path.splitext(b)[0].rsplit("_", 1)[-1].lower(), []).append(e)

    def file(self, path):
        for cand in (path, "Generated/" + path if not path.startswith("Generated/") else path):
            hit = self.files.get(cand.lower())
            if hit:
                return hit
        return None, None

    def material(self, mid):
        m = self.banks["MaterialBank"].get(mid)
        if not m:
            return {"id": mid, "missing": True}
        out = {"id": mid, "name": m["attributes"].get("Name"), "shader": m["attributes"].get("SourceFile"),
               "textures": [], "virtual_textures": [], "vectors": {}}
        for c in m.get("children", []):
            a = c["attributes"]
            if c["name"] == "Texture2DParameters" and a.get("Enabled") and a.get("ParameterName"):
                t = self.banks["TextureBank"].get(a["ID"])
                rec = {"param": a["ParameterName"], "id": a["ID"]}
                if t:
                    ta = t["attributes"]
                    p, e = self.file(ta.get("SourceFile", ""))
                    rec.update(file=ta.get("SourceFile"), w=ta.get("Width"), h=ta.get("Height"),
                               srgb=ta.get("SRGB"), pak=os.path.basename(p.path) if p else None,
                               bytes=fsize(e))
                out["textures"].append(rec)
            elif c["name"] == "VirtualTextureParameters" and a.get("Enabled"):
                t = self.banks["VirtualTextureBank"].get(a.get("ID"))
                g = t["attributes"].get("GTexFileName") if t else None
                hits = self.vt_by_hash.get((g or "").lower(), [])
                out["virtual_textures"].append({"param": a.get("ParameterName"), "id": a.get("ID"), "gtex": g,
                                                "vt_files": [h.name for h in hits][:6],
                                                "vt_bytes": sum(fsize(h) for h in hits)})
            elif c["name"] == "Vector3Parameters":   # disabled ones = the shader default (Value == BaseValue)
                out["vectors"][a.get("ParameterName") or a.get("Parameter")] = [round(x, 4) for x in a.get("Value", [])]
            elif c["name"] == "ScalarParameters":
                out.setdefault("scalars", {})[a.get("ParameterName") or a.get("Parameter")] = a.get("Value")
        return out

    def visual(self, vid, lod0_only=True):
        v = self.banks["VisualBank"].get(vid)
        if not v:
            return {"id": vid, "missing": True}
        a = v["attributes"]
        src = a.get("SourceFile")
        p, e = self.file(src) if src else (None, None)
        rec = {"id": vid, "name": a.get("Name"), "slot": a.get("Slot"), "gr2": src,
               "attach_bone": a.get("AttachBone") or None, "skeleton": a.get("SkeletonResource") or None,
               "gr2_bytes": fsize(e), "objects": []}
        if e is not None:
            dsize, comps = gr2_info(p.read(e)[:4096])
            rec["gr2_decompressed"] = dsize
            rec["gr2_compression"] = comps
        mats = {}
        for c in v.get("children", []):
            if c["name"] == "Objects":
                ca = c["attributes"]
                if lod0_only and ca.get("LOD", 0) != 0:
                    continue
                rec["objects"].append({"object": ca.get("ObjectID"), "lod": ca.get("LOD"),
                                       "material": ca.get("MaterialID")})
                if ca.get("MaterialID") and ca["MaterialID"] not in mats:
                    mats[ca["MaterialID"]] = self.material(ca["MaterialID"])
        rec["materials"] = list(mats.values())
        return rec


def template_chain(allt, key):
    seen = []
    while key and key in allt and key not in seen:
        seen.append(key)
        key = allt[key][2].get("ParentTemplateId")
    return [allt[k][2] for k in seen]


def visualset_tints(eq):
    """Equipment/VisualSet/MaterialOverrides: the item's own colour overrides (enabled Vector3 parameters)."""
    out = {}
    vs = eq.child("VisualSet")
    mo = vs.child("MaterialOverrides") if vs else None
    for c in (mo.children if mo else []):
        if c.name == "Vector3Parameters" and c.get("Enabled"):
            out[c.get("Parameter")] = [round(x, 4) for x in c.get("Value")]
    return out


def item_visuals(allt, by_name, sid, races):
    """Item stat id -> list of VisualBank ids for this body (armour) or the item's own visual (weapons)."""
    for k in by_name.get(sid, []):
        chain = template_chain(allt, k)
        for g in chain:
            eq = g.child("Equipment")
            vis = eq.child("Visuals") if eq else None
            if vis and vis.children:
                for race in races:
                    for o in vis.children:
                        if o.get("MapKey") == RACE_KEY[race]:
                            ids = [mv.get("Object") for mv in o.children if mv.get("Object")]
                            if ids:
                                return {"template": g.get("Name"), "race": race, "kind": "equipment", "visuals": ids,
                                        "tints": visualset_tints(eq),
                                        "equip_slots": [c.get("Object") for c in eq.children_named("Slot")]}
            vt = g.get("VisualTemplate")
            if vt and vt != NULL:
                return {"template": g.get("Name"), "race": None, "kind": "visual_template", "visuals": [vt]}
    return None


def main(argv):
    char = argv[1] if len(argv) > 1 else "astarion"
    set_id = argv[2] if len(argv) > 2 else "astarion.thx.a3.1"
    o = ORIGINS[char]
    paks = {pk: Pak(os.path.join(GAME_DATA, pk)) for pk in bc.PAKS}
    allt, _ = bc.load_all_templates(paks)
    by_name = {}
    stat_of = {}
    for k, (pk, mod, g) in allt.items():
        by_name.setdefault(g.get("Name"), []).append(k)
    # stats id -> template: prefer the template whose Name == stats id, else one whose Stats == stats id
    for k, (pk, mod, g) in allt.items():
        s = g.get("Stats")
        if s and g.get("Type") == "item":
            stat_of.setdefault(s, []).append(k)
    R = Res()

    # 1. character visual
    tk = [k for k in by_name.get(o["template"], []) if allt[k][2].get("Type") == "character"][0]
    cvr = allt[tk][2].get("CharacterVisualResourceID")
    cv = R.banks["CharacterVisualBank"][cvr]
    ca = cv["attributes"]
    character = {"template": o["template"], "template_id": tk, "character_visual": cvr, "name": ca.get("Name"),
                 "base_visual": R.visual(ca.get("BaseVisual")), "body": R.visual(ca.get("BodySetVisual")),
                 "slots": []}
    for c in cv.get("children", []):
        if c["name"] == "Slots":
            sa = c["attributes"]
            character["slots"].append({"slot": sa.get("Slot"), "bone": sa.get("Bone") or None,
                                       **R.visual(sa.get("VisualResource"))})
    presets = {}
    for c in cv.get("children", []):
        if c["name"] == "MaterialOverrides":
            for mp in c.get("children", []):
                for ob in mp.get("children", []) if mp["name"] == "MaterialPresets" else []:
                    presets[ob["attributes"].get("GroupName")] = ob["attributes"].get("MaterialPresetResource")
    character["material_presets"] = presets

    # 2. the set's items
    scores = json.load(open(os.path.join(ROOT, "data", "scores", f"{char}.json"), encoding="utf-8"))
    st = None
    _, build, act, n = set_id.split(".")
    st = scores["builds"][build]["sets"][act[1:]][int(n) - 1]
    pieces = []
    for slot, it in st["items"].items():
        sid = it["sid"]
        rec = {"slot": slot, "sid": sid, "name": it["name"], "visible": slot in VISIBLE_SLOTS}
        if rec["visible"]:
            hit = item_visuals(allt, by_name, sid, o["races"])
            if hit is None:
                for k in stat_of.get(sid, []):
                    hit = item_visuals(allt, {sid: [k]}, sid, o["races"])
                    if hit:
                        break
            if hit:
                rec.update(template=hit["template"], race=hit["race"], kind=hit["kind"], tints=hit.get("tints", {}), equip_slots=hit.get("equip_slots", []),
                           visuals=[R.visual(v) for v in hit["visuals"]])
            else:
                rec["unresolved"] = True
        pieces.append(rec)

    out = {"character": char, "set_id": set_id, "set_name": st["name"], "char_visual": character, "pieces": pieces}
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{set_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # summary
    def vsum(v):
        tex = sum((t.get("bytes") or 0) for m in v.get("materials", []) for t in m.get("textures", []))
        vtn = sum(len(m.get("virtual_textures", [])) for m in v.get("materials", []))
        return v.get("gr2_bytes") or 0, v.get("gr2_decompressed") or 0, tex, vtn
    print(f"{set_id}: {st['name']}  -> {path}")
    print("character", character["name"])
    for label, v in [("base", character["base_visual"]), ("body", character["body"])] + \
            [(s["slot"], s) for s in character["slots"]]:
        g, d, t, n = vsum(v)
        print(f"  {label:14s} {v.get('name')!s:42s} gr2 {g/1e3:8.0f} kB (raw {d/1e3:7.0f}) dds {t/1e6:5.1f} MB vt {n}")
    for p in pieces:
        if not p["visible"]:
            print(f"  {p['slot']:14s} {p['sid']} (not visible)")
            continue
        if p.get("unresolved"):
            print(f"  {p['slot']:14s} {p['sid']} UNRESOLVED")
            continue
        for v in p["visuals"]:
            g, d, t, n = vsum(v)
            print(f"  {p['slot']:14s} {v.get('name')!s:42s} gr2 {g/1e3:8.0f} kB (raw {d/1e3:7.0f}) dds {t/1e6:5.1f} MB vt {n}"
                  f"  [{p['kind']} {p['race']}]")


if __name__ == "__main__":
    main(sys.argv)
