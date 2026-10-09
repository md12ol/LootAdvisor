"""BG3 character placements (NPCs) with their loot-relevant fields, resolved through the root-template chain.

  python characters.py [--out DIR]     writes <DIR>/level_characters_index.json (default LootAdvisor/data/cache)

Reads (read-only) Mods/<module>/Levels/<level>/Characters/_merged.lsf and Mods/<module>/Globals/<level>/Characters/
_merged.lsf of the campaign modules (Shared, SharedDev, Gustav, GustavDev, GustavX) and every character root template
(Public/<module>/RootTemplates/_merged.lsf, Type == "character"). Honour / HonourX are skipped.

Record per placement (JSON array, one object per line):
  pak, module, level (folder), scope ("Levels"|"Globals"), LevelName, MapKey, Name, TemplateName, position
  display_name / title (English), Stats, Equipment (Equipment.txt set name), Faction (GUID), CombatGroupID,
  IsBoss, IsLootable, IsEquipmentLootable, Treasures [...], TradeTreasures [...],
  ItemList [{ItemName, TemplateID, Amount, Type, UUID, IsTradable, CanBePickpocketed, IsDroppedOnDeath}],
  template_chain [MapKeys], from_template {field: MapKey that supplied it}
Inheritance: a field the placement does not set comes from the nearest template in the chain
(TemplateName -> ParentTemplateId ...); ItemList = union of placement + chain (template items first).
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsf  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak"]
MODULES = ["Shared", "SharedDev", "Gustav", "GustavDev", "GustavX"]
CHARS = re.compile(r"^Mods/([^/]+)/(Levels|Globals)/([^/]+)/Characters/_merged\.lsf$")
ROOT_TEMPLATES = re.compile(r"^Public/([^/]+)/RootTemplates/_merged\.lsf$")
NULL = "00000000-0000-0000-0000-000000000000"
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")

SCALARS = ["Stats", "Equipment", "Faction", "CombatGroupID", "IsBoss", "IsLootable", "IsEquipmentLootable",
           "Race", "Archetype", "IsTradable", "DefaultDialog", "LevelOverride", "SpellSet", "CanFight",
           "InfluenceTreasureLevel", "IsPlayer"]
TSTRINGS = ["DisplayName", "Title"]
LISTS = ["Treasures", "TradeTreasures"]
ITEM_KEYS = ("ItemName", "TemplateID", "Amount", "Type", "UUID", "IsTradable", "CanBePickpocketed",
             "IsDroppedOnDeath", "LevelName")


def _val(v):
    return round(v, 3) if isinstance(v, float) else v


def _list(node, name):
    c = node.child(name)
    if c is None:
        return None
    vals = [x.get("Object") for x in c.children if x.get("Object")]
    return vals


def _items(node):
    c = node.child("ItemList")
    if c is None:
        return []
    out = []
    for it in c.children:
        rec = {k: _val(it.get(k)) for k in ITEM_KEYS if it.get(k) not in (None, "", NULL)}
        if rec:
            out.append(rec)
    return out


def _own(node):
    """Fields set on this node itself (empty strings / null GUIDs count as unset)."""
    out = {}
    for k in SCALARS:
        v = node.get(k)
        if v is not None and v != "" and v != NULL:
            out[k] = _val(v)
    for k in TSTRINGS:
        v = node.get(k)
        if isinstance(v, dict) and v.get("handle") and v["handle"] != "ls::TranslatedStringRepository::s_HandleUnknown":
            out[k] = v["handle"]
    for k in LISTS:
        v = _list(node, k)
        if v:
            out[k] = v
    tags = _list(node, "Tags")
    if tags:
        out["Tags"] = tags
    return out


def load_char_templates(paks):
    tmpl = {}
    for pk in PAKS:
        p = paks[pk]
        for e in p.entries:
            m = ROOT_TEMPLATES.match(e.name)
            if not m or m.group(1) not in MODULES:
                continue
            res = lsf.load(p.read(e))
            for reg in res.regions:
                for g in reg.children:
                    if g.get("Type") == "character":
                        tmpl[g.get("MapKey")] = {"node": g, "module": m.group(1)}
    return tmpl


def resolve(own, items, start_template, tmpl):
    rec = dict(own)
    src = {}
    all_items = list(items)
    chain = []
    cur = start_template
    seen = set()
    while cur and cur != NULL and cur not in seen and cur in tmpl:
        seen.add(cur)
        chain.append(cur)
        node = tmpl[cur]["node"]
        town = _own(node)
        for k, v in town.items():
            if k not in rec:
                rec[k] = v
                src[k] = cur
        all_items = _items(node) + all_items
        cur = node.get("ParentTemplateId") or node.get("TemplateName")
    return rec, src, chain, all_items


def build(out_dir=OUT_DEFAULT, texts=None):
    t0 = time.time()
    if texts is None:
        with open(os.path.join(out_dir, "loca_english.json"), encoding="utf-8") as f:
            texts = json.load(f)
    paks = {pk: Pak(os.path.join(GAME_DATA, pk)) for pk in PAKS}
    tmpl = load_char_templates(paks)
    records = []
    for pk in PAKS:
        p = paks[pk]
        for e in p.entries:
            m = CHARS.match(e.name)
            if not m or m.group(1) not in MODULES:
                continue
            module, scope, level = m.groups()
            res = lsf.load(p.read(e))
            for reg in res.regions:
                for g in reg.children:
                    if g.get("Type") != "character":
                        continue
                    own = _own(g)
                    rec, src, chain, items = resolve(own, _items(g), g.get("TemplateName"), tmpl)
                    tr = g.child("Transform")
                    pos = [round(x, 3) for x in tr.get("Position")] if tr is not None and tr.get("Position") else None
                    out = {"pak": pk, "module": module, "level": level, "scope": scope,
                           "LevelName": g.get("LevelName"), "MapKey": g.get("MapKey"), "Name": g.get("Name"),
                           "TemplateName": g.get("TemplateName"), "position": pos}
                    for k in TSTRINGS:
                        h = rec.pop(k, None)
                        if h:
                            out[k.lower() if k == "Title" else "display_name"] = texts.get(h)
                            out[k + "_handle"] = h
                    out.update(rec)
                    if items:
                        out["ItemList"] = items
                    out["template_chain"] = chain
                    if src:
                        out["from_template"] = src
                    records.append(out)
    for p in paks.values():
        p.close()
    path = os.path.join(out_dir, "level_characters_index.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in records))
        f.write("\n]\n")
    print(f"level_characters_index.json: {len(records)} characters, {len(tmpl)} character templates "
          f"({time.time() - t0:.1f}s)")
    return records


if __name__ == "__main__":
    out = OUT_DEFAULT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    build(out)
