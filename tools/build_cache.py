"""Build the LootAdvisor cache dumps from the game's paks (read-only on the game folder).

  python build_cache.py [--out DIR] [--only loca,templates,levels]

Writes to LootAdvisor/data/cache/ (default):
  loca_english.json                       {handle: text}                      (english.loca)
  roottemplates_<pak>_<module>.json       item root templates of one module   (JSON array, one object per line)
  level_items_index.json                  every item placement in Mods/*/Levels/*/Items (JSON array, one per line)
Schemas: see PARSERS.md. Needs pak.py, lsf.py, loca.py next to this file.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loca  # noqa: E402
import lsf  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Patch8_HotFix10.pak"]
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
ROOT_TEMPLATES = re.compile(r"^Public/([^/]+)/RootTemplates/_merged\.lsf$")
LEVEL_ITEMS = re.compile(r"^Mods/([^/]+)/Levels/([^/]+)/Items/")
NULL_GUID = "00000000-0000-0000-0000-000000000000"

# attributes that carry no item/loot meaning (sound, physics, rendering, walkability ...)
SKIP_ATTRS = {
    "_OriginalFileVersion_", "VisualTemplate", "PhysicsTemplate", "PhysicsOpenTemplate", "PhysicsFollowAnimation",
    "PhysicsCollisionSound", "ReadinessFlags", "CanShootThrough", "WalkThrough", "CoverAmount", "WalkOn",
    "CanClimbOn", "LoopSound", "SoundInitEvent", "CanClickThrough", "SoundAttenuation", "IsPointerBlocker",
    "Wadable", "WadableSurfaceType", "GravityType", "RecieveDecal", "DropSound", "PickupSound",
    "InventoryMoveSound", "ImpactSound", "UseSound", "EquipSound", "UnequipSound", "ShootThroughType",
    "SeeThrough", "BloodSurfaceType", "BloodType", "AttackableWhenClickThrough", "CameraOffset", "ExamineRotation",
    "MeshProxy", "Fadeable", "HierarchyOnlyFade", "FadeIn", "FadeGroup", "Opacity", "CastShadow", "UseOcclusion",
    "CanShineThrough", "IsSurfaceCloudBlocker", "IsSurfaceBlocker", "IsBlocker", "RenderChannel", "LightChannel",
    "SoundObjectIndex", "IsShadowProxy", "HiddenFromMinimapRendering", "FreezeGravity", "Floating",
    "ConstellationConfigName", "AnubisConfigName", "MaterialPreset", "ColorPreset", "Flag", "Scale",
}
# child lists worth keeping: node name -> how to flatten
LIST_CHILDREN = {"Tags": "Tag", "InventoryList": "InventoryItem", "StatusList": "Status",
                 "OnlyInDifficulty": None, "ExcludeInDifficulty": None, "Labels": None}


def _jsonable(v):
    if isinstance(v, float):
        return round(v, 4)
    return v


def tstr(v, texts):
    """TranslatedString value -> {handle, text}."""
    h = v.get("handle")
    out = {"handle": h, "text": texts.get(h)}
    if v.get("arguments"):
        out["arguments"] = v["arguments"]
    return out


def flatten_list(node):
    vals = []
    for c in node.children:
        if len(c.attrs) == 1:
            vals.append(_jsonable(next(iter(c.attrs.values()))[1]))
        elif c.attrs or c.children:
            vals.append(lsf.to_json(c, typed=False))
    return vals


def item_list(node):
    out = []
    for it in node.children:
        rec = {k: _jsonable(v) for k, (t, v) in it.attrs.items()
               if k in ("ItemName", "TemplateID", "Amount", "Type", "UUID", "LevelName", "IsTradeable",
                        "CanBePickpocketed", "IsDroppedOnDeath", "Classic", "CasualExplorer",
                        "TacticianHardcore", "HonorHardcore")}
        out.append(rec)
    return out


def object_record(g, texts):
    rec = {}
    for k, (t, v) in g.attrs.items():
        if k in SKIP_ATTRS:
            continue
        if t in ("TranslatedString", "TranslatedFSString"):
            if v.get("handle") and v["handle"] != "ls::TranslatedStringRepository::s_HandleUnknown":
                rec[k] = tstr(v, texts)
            continue
        if v == "" or v == NULL_GUID:
            continue
        rec[k] = [_jsonable(x) for x in v] if isinstance(v, list) else _jsonable(v)
    for c in g.children:
        if c.name in LIST_CHILDREN:
            vals = flatten_list(c)
            if vals:
                rec[c.name] = vals
        elif c.name == "ItemList":
            vals = item_list(c)
            if vals:
                rec["ItemList"] = vals
    return rec


def build_loca(out):
    t = time.time()
    texts = loca.load_english()
    path = os.path.join(out, "loca_english.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=0)
    print(f"loca_english.json: {len(texts)} handles ({time.time() - t:.1f}s)")
    return texts


def load_all_templates(paks):
    """MapKey -> (pak, module, Node) for every root template of every type (later paks override)."""
    allt = {}
    order = []
    for pk in PAKS:
        p = paks[pk]
        for e in p.entries:
            m = ROOT_TEMPLATES.match(e.name)
            if m:
                res = lsf.load(p.read(e))
                gos = [g for reg in res.regions for g in reg.children]
                order.append((pk, m.group(1), gos))
                for g in gos:
                    allt[g.get("MapKey")] = (pk, m.group(1), g)
    return allt, order


INHERIT = ("Stats", "DisplayName", "Description", "Icon", "TechnicalDescription", "ShortDescription")


def resolve_inherited(g, allt):
    """Values the template lacks but inherits from its ParentTemplateId chain."""
    out = {}
    missing = [k for k in INHERIT if not _has(g, k)]
    seen = set()
    cur = g
    while missing:
        pid = cur.get("ParentTemplateId")
        if not pid or pid in seen or pid not in allt:
            break
        seen.add(pid)
        cur = allt[pid][2]
        for k in list(missing):
            if _has(cur, k):
                out[k] = (cur.get(k), pid)
                missing.remove(k)
    return out


def _has(g, k):
    v = g.get(k)
    if v is None or v == "":
        return False
    if isinstance(v, dict):
        return bool(v.get("handle")) and v["handle"] != "ls::TranslatedStringRepository::s_HandleUnknown"
    return True


def inherited_json(inh, texts):
    out = {}
    for k, (v, src) in inh.items():
        out[k] = tstr(v, texts) if isinstance(v, dict) else v
        out[k + "_from"] = src
    return out


def write_lines(path, records):
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, r in enumerate(records):
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            f.write(",\n" if i < len(records) - 1 else "\n")
        f.write("]\n")


def build_templates(out, paks, texts, allt, order):
    t = time.time()
    total = 0
    for pk, module, gos in order:
        recs = []
        for g in gos:
            if g.get("Type") != "item":
                continue
            rec = object_record(g, texts)
            inh = resolve_inherited(g, allt)
            if inh:
                rec["inherited"] = inherited_json(inh, texts)
            recs.append(rec)
        name = f"roottemplates_{os.path.splitext(pk)[0]}_{module}.json"
        write_lines(os.path.join(out, name), recs)
        total += len(recs)
        print(f"{name}: {len(recs)} item templates")
    print(f"root templates: {total} item templates ({time.time() - t:.1f}s)")


def build_levels(out, paks, texts, allt):
    t = time.time()
    recs = []
    files = 0
    for pk in PAKS:
        p = paks[pk]
        for e in p.entries:
            m = LEVEL_ITEMS.match(e.name)
            if not m:
                continue
            data = p.read(e)
            if data[:4] != b"LSOF":
                continue  # .lsx layer metadata etc.
            files += 1
            res = lsf.load(data)
            for reg in res.regions:
                for g in reg.children:
                    rec = {"pak": pk, "module": m.group(1), "level": m.group(2)}
                    if not e.name.endswith("/_merged.lsf"):
                        rec["file"] = e.name
                    rec.update(object_record(g, texts))
                    tr = g.child("Transform")
                    if tr is not None:
                        pos = tr.get("Position")
                        if pos is not None:
                            rec["position"] = [round(x, 3) for x in pos]
                        rot = tr.get("RotationQuat")
                        if rot is not None:
                            rec["rotation"] = [round(x, 4) for x in rot]
                    tpl = allt.get(g.get("TemplateName"))
                    if tpl is not None:
                        tg = tpl[2]
                        info = {"Name": tg.get("Name"), "module": tpl[1]}
                        for k in INHERIT:
                            if _has(tg, k):
                                v = tg.get(k)
                                info[k] = tstr(v, texts)["text"] if isinstance(v, dict) else v
                        for k, (v, src) in resolve_inherited(tg, allt).items():
                            info[k] = tstr(v, texts)["text"] if isinstance(v, dict) else v
                        info.pop("TechnicalDescription", None)
                        info.pop("ShortDescription", None)
                        info.pop("Description", None)
                        rec["template"] = info
                    else:
                        rec["template"] = None
                    recs.append(rec)
    path = os.path.join(out, "level_items_index.json")
    write_lines(path, recs)
    print(f"level_items_index.json: {len(recs)} placements from {files} files ({time.time() - t:.1f}s)")


def main(argv):
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT_DEFAULT
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else {"loca", "templates", "levels"}
    os.makedirs(out, exist_ok=True)
    paks = {n: Pak(os.path.join(GAME_DATA, n)) for n in PAKS}
    texts = build_loca(out) if "loca" in only else loca.load_english()
    allt, order = load_all_templates(paks)
    if "templates" in only:
        build_templates(out, paks, texts, allt, order)
    if "levels" in only:
        build_levels(out, paks, texts, allt)
    for p in paks.values():
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
