"""Teleporters and triggers from the game's level files (read-only) -> data/cache/level_links.json.

Teleporter = a placed item whose OnUsePeaceActions has an Action with ActionType 3 (teleport): Attributes Target =
the trigger (or object) the user arrives at. Doors/ladders/hatches into interiors that sit elsewhere in the level use
this. Output: {"teleporters": [{MapKey, Name, level, pos, target, target_pos, target_level}], "triggers": {MapKey:
{Name, level, pos}}}  (positions [x, y, z]).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pak import Pak, GAME_DATA  # noqa: E402
import lsf  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "data", "cache", "level_links.json")
PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Patch8_HotFix10.pak"]


def pos_of(node):
    t = node.child("Transform") if hasattr(node, "child") else None
    if t is None:
        for ch in node.children:
            if ch.name == "Transform":
                t = ch
    if t is None:
        return None
    p = t.get("Position") or t.get("Translate")
    return [round(float(v), 2) for v in p] if p else None


SPLIT = r"\n(?=IF\b|PROC\b|QRY\b)"
OBJ_RX = (r"\b(?:\((?:ITEM|TRIGGER|CHARACTER|GUIDSTRING)\))?([A-Za-z0-9_]+_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
          r"[0-9a-f]{4}-[0-9a-f]{12}))")
LINK_WORDS = re.compile(r"(Portal|Teleport|Door|Ladder|Hatch|Stair|Entrance|Exit|Travel|Elevator|Lift|Rope|Hole|Tunnel)",
                        re.I)
OBJ = re.compile(OBJ_RX)


def osiris_links(objects, triggers):
    """Scripted entrances in the story goals (Story/RawFiles/Goals/*.txt), two general shapes:
    - a database fact naming a placed item and a destination, e.g. DB_LOW_DevilsFee_Portals(S_..._PortalToHouseOfHope,
      S_LOW_HouseOfHopeEntrance, ...): DB name or item name says portal/teleport/door/ladder/..., the item is placed
      and the other object is a placed trigger/object;
    - a rule whose condition names such an item and whose action teleports to a placed trigger/object
      (TeleportTo(_x, S_target) / PROC_TeleportPartiesTo(S_target ...))."""
    out = []
    goals = {}
    for pk in PAKS:
        fp = os.path.join(GAME_DATA, pk)
        if not os.path.exists(fp):
            continue
        p = Pak(fp)
        for n in p.by_name:
            if "/Story/RawFiles/Goals/" in n and n.endswith(".txt"):
                goals[n.split("/")[-1]] = p.read(p.by_name[n]).decode("utf-8", "ignore")  # later paks override
    placed = lambda g: g in objects or g in triggers  # noqa: E731
    for name, text in goals.items():
        for m in re.finditer(r"^\s*(DB_\w+)\((.*?)\);", text, re.M):
            db, args = m.group(1), m.group(2)
            objs = [(o.group(1), o.group(2)) for o in OBJ.finditer(args)]
            if len(objs) < 2:
                continue
            src = objs[0]
            if src[1] not in objects or not (LINK_WORDS.search(db) or LINK_WORDS.search(src[0])):
                continue
            for dst in objs[1:]:
                if placed(dst[1]) and dst[1] != src[1]:
                    out.append({"MapKey": src[1], "Name": src[0][:-37], "level": objects[src[1]]["level"],
                                "pos": objects[src[1]]["pos"], "target": dst[1], "via": "osiris:" + db})
                    break
        for blk in re.split(SPLIT, text):
            if "THEN" not in blk:
                continue
            cond, act = blk.split("THEN", 1)
            items = [(o.group(1), o.group(2)) for o in OBJ.finditer(cond) if o.group(2) in objects
                     and LINK_WORDS.search(o.group(1))]
            if not items:
                continue
            for t in re.finditer(r"(?:TeleportTo|PROC_TeleportPartiesTo|PROC_Helper_SafeTeleportTo)\(([^;]*)\);", act):
                tg = [(o.group(1), o.group(2)) for o in OBJ.finditer(t.group(1)) if placed(o.group(2))]
                for it in items[:1]:
                    for dst in tg[:1]:
                        if dst[1] != it[1]:
                            out.append({"MapKey": it[1], "Name": it[0][:-37], "level": objects[it[1]]["level"],
                                        "pos": objects[it[1]]["pos"], "target": dst[1], "via": "osiris:rule:" + name})
    return out


def main():
    teleporters, triggers, objects = [], {}, {}
    for pk in PAKS:
        fp = os.path.join(GAME_DATA, pk)
        if not os.path.exists(fp):
            continue
        p = Pak(fp)
        for name in p.by_name:
            parts = name.split("/")
            # Levels/<level>/... and Globals/<level>/... (global objects: waypoints, global NPCs and items)
            if len(parts) < 6 or parts[2] not in ("Levels", "Globals") or parts[0] != "Mods":
                continue
            level, kind = parts[3], parts[4]
            if kind not in ("Items", "Triggers", "Characters") or not name.endswith(".lsf"):
                continue
            try:
                res = lsf.load(p.read(p.by_name[name]))
            except Exception:
                continue
            for reg in res.regions:
                for g in reg.children:
                    mk = g.get("MapKey")
                    if not mk:
                        continue
                    ps = pos_of(g)
                    if kind == "Triggers":
                        triggers[mk] = {"Name": g.get("Name"), "level": level, "pos": ps}
                        continue
                    objects[mk] = {"Name": g.get("Name"), "level": level, "pos": ps}
                    if kind != "Items":
                        continue
                    for ch in g.children:
                        if ch.name != "OnUsePeaceActions":
                            continue
                        for a in ch.children:
                            if a.get("ActionType") != 3:
                                continue
                            at = {}
                            for sub in a.children:
                                if sub.name == "Attributes":
                                    at = {k: v for k, (_t, v) in sub.attrs.items()}
                            teleporters.append({"MapKey": mk, "Name": g.get("Name"), "level": level, "pos": ps,
                                                "target": at.get("Target"), "source": at.get("Source"),
                                                "type": at.get("Type"), "stype": at.get("SourceType")})
    teleporters += osiris_links(objects, triggers)
    for t in teleporters:
        tg = triggers.get(t["target"]) or objects.get(t["target"])
        t["target_pos"] = tg and tg["pos"]
        t["target_level"] = tg and tg["level"]
        t["target_name"] = tg and tg["Name"]
    json.dump({"teleporters": teleporters, "triggers": triggers, "objects": objects}, open(OUT, "w", encoding="utf-8"))
    ok = sum(1 for t in teleporters if t["target_pos"])
    print("teleporters %d (%d with a resolved target), triggers %d" % (len(teleporters), ok, len(triggers)))


if __name__ == "__main__":
    main()
