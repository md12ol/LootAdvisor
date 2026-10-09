"""Ways from one region (WLD_Main_A, CTY_Main_A, ...) to another, from the game's story scripts (read-only).

Used by entrances.py (round 3: an item in ANOTHER region gets its marker on the way out of the current region).
Two general sources in Story/RawFiles/Goals/*.txt:
 - region-swap teleporters: DB_GLO_LevelSwap_Teleporter(ITEM, "ReadyCheck_X") + DB_GLO_LevelSwap_Location(
   "ReadyCheck_X", arrival TRIGGER, ..., "DestinationLevel") - e.g. the Lower City <-> Wyrm's Crossing gate,
   the goblin camp <-> Creche portal, the Underdark <-> Shadow-Cursed Lands elevator;
 - waypoints: DB_WaypointInfo(group, id, ITEM, TRIGGER) - fast travel works between waypoints of all regions of an
   act, so the nearest waypoint is the fallback way out.
"""
import os
import re

from pak import Pak, GAME_DATA

PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Patch8_HotFix10.pak"]
GUID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"


def load_goals():
    goals = {}
    for pk in PAKS:
        fp = os.path.join(GAME_DATA, pk)
        if not os.path.exists(fp):
            continue
        p = Pak(fp)
        for n in p.by_name:
            if "/Story/RawFiles/Goals/" in n and n.endswith(".txt"):
                goals[n.split("/")[-1]] = p.read(p.by_name[n]).decode("utf-8", "ignore")
    return goals


def parse(goals):
    tele, loc, wps = {}, {}, []
    rx_t = re.compile(r"DB_GLO_LevelSwap_Teleporter\(\s*(?:\(ITEM\))?\s*(\w+?)_" + GUID + r"\s*,\s*\"([^\"]+)\"\s*\)")
    rx_l = re.compile(r"DB_GLO_LevelSwap_Location\(\s*\"([^\"]+)\"\s*,\s*(?:\(TRIGGER\))?\s*(\w+?)_" + GUID +
                      r"[^;]*?\"(\w+)\"\s*\)\s*;")
    rx_w = re.compile(r"DB_WaypointInfo\(\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"\s*,\s*\(ITEM\)\s*(\w+?)_" + GUID +
                      r"\s*,\s*\(TRIGGER\)\s*(\w+?)_" + GUID)
    for text in goals.values():
        for m in rx_t.finditer(text):
            tele[m.group(2)] = {"Name": m.group(1), "MapKey": m.group(2), "check": m.group(3)}
        for m in rx_l.finditer(text):
            loc[m.group(1)] = {"arrive": m.group(3), "arrive_name": m.group(2), "to_region": m.group(4)}
        for m in rx_w.finditer(text):
            wps.append({"group": m.group(1), "id": m.group(2), "Name": m.group(3), "MapKey": m.group(4),
                        "trigger": m.group(6)})
    exits = []
    for t in tele.values():
        lo = loc.get(t["check"])
        if lo:
            exits.append(dict(t, **lo))
    return exits, wps
