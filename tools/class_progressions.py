"""Class / subclass proficiencies and display names from the game files (read-only).

  python tools/class_progressions.py        -> data/cache/class_progressions.json

Reads Progressions.lsx (Boosts + the Boosts of PassivesAdded, e.g. Hex Warrior) + ClassDescriptions.lsx from Shared.pak, Gustav.pak and GustavX.pak (later modules override
earlier ones by UUID, like the game) and the English loca cache for the names the game shows.

Output:
  classes  {Name: {"display", "uuid", "parent" (class Name for a subclass, else null),
                   "start": [proficiencies at level 1 as the first class],
                   "multi": [proficiencies at level 1 as a multiclass],
                   "levels": {"<class level>": [proficiencies gained at that level]}}}
           - for a subclass, "levels" are the proficiencies its own progression table grants per class level.
  by_display {"<class display>": {"<subclass display>": subclass Name}}
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pak import GAME_DATA, Pak  # noqa: E402

LA = os.path.dirname(HERE)
OUT = os.path.join(LA, "data", "cache", "class_progressions.json")
LOCA = os.path.join(LA, "data", "cache", "loca_english.json")
STATS = os.path.join(LA, "data", "cache", "stats_resolved.json")  # passives (Hex Warrior grants its proficiencies)
# module load order (later overrides earlier by UUID)
MODULES = [("Shared.pak", "Shared"), ("Shared.pak", "SharedDev"), ("Gustav.pak", "Gustav"),
           ("Gustav.pak", "GustavDev"), ("GustavX.pak", "GustavX")]
PROF_RX = re.compile(r"(?<!Bonus)\bProficiency\((\w+)\)")


def _nodes(xml_bytes, node_id):
    root = ET.fromstring(xml_bytes)
    for n in root.iter("node"):
        if n.get("id") == node_id:
            a = {}
            for at in n.findall("attribute"):
                a[at.get("id")] = at.get("value") if at.get("value") is not None else at.get("handle")
            yield a


def read_game(game_data=GAME_DATA):
    progs, descs = {}, {}
    paks = {}
    try:
        for pak, mod in MODULES:
            p = paks.get(pak) or paks.setdefault(pak, Pak(os.path.join(game_data, pak)))
            for kind, store, nid in (("Progressions/Progressions.lsx", progs, "Progression"),
                                     ("ClassDescriptions/ClassDescriptions.lsx", descs, "ClassDescription")):
                name = f"Public/{mod}/{kind}"
                if name in p.by_name:
                    for a in _nodes(p.read(p.by_name[name]), nid):
                        store[a["UUID"]] = a
    finally:
        for p in paks.values():
            p.close()
    return progs, descs


def build(progs, descs, loca, stats=None):
    by_uuid = {d["UUID"]: d for d in descs.values()}
    classes = {}
    table_owner = {}
    for d in descs.values():
        parent = by_uuid.get(d.get("ParentGuid") or "")
        classes[d["Name"]] = {"display": loca.get(d.get("DisplayName") or "", ""), "uuid": d["UUID"],
                              "parent": parent["Name"] if parent else None, "start": [], "multi": [], "levels": {}}
        if d.get("ProgressionTableUUID"):
            table_owner[d["ProgressionTableUUID"]] = d["Name"]
    for pr in progs.values():
        if pr.get("ProgressionType") not in ("0", "1"):
            continue
        owner = table_owner.get(pr.get("TableUUID"))
        if not owner:
            continue
        profs = PROF_RX.findall(pr.get("Boosts") or "")
        for pas in (pr.get("PassivesAdded") or "").split(";"):
            pd = (stats or {}).get(pas.strip())
            if isinstance(pd, dict) and not (pd.get("Boosts") or "").startswith("IF("):
                profs += PROF_RX.findall(pd.get("Boosts") or "")
        c = classes[owner]
        lv = int(pr.get("Level") or 0)
        if lv == 1 and c["parent"] is None:
            c["multi" if pr.get("IsMulticlass") == "true" else "start"] = sorted(profs)
        elif profs:
            c["levels"].setdefault(str(lv), [])
            c["levels"][str(lv)] = sorted(set(c["levels"][str(lv)]) | set(profs))
    by_display = {}
    for n, c in classes.items():
        if c["parent"]:
            by_display.setdefault(classes[c["parent"]]["display"], {})[c["display"]] = n
    return {"source": "game files: Progressions.lsx + ClassDescriptions.lsx (" +
                      ", ".join(f"{p}:{m}" for p, m in MODULES) + ")",
            "classes": classes, "by_display": by_display}


def main():
    with open(LOCA, encoding="utf-8") as f:
        loca = json.load(f)
    with open(STATS, encoding="utf-8") as f:
        stats = json.load(f)
    progs, descs = read_game()
    out = build(progs, descs, loca, stats)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(f"{len(out['classes'])} classes/subclasses -> {OUT}")


if __name__ == "__main__":
    main()
