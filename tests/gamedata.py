"""Independent game-data facts for the regression suite.

Read straight from the game's paks (Progressions.lsx, ClassDescriptions.lsx) and the game-derived caches
(data/cache/loca_english.json = the English .loca, data/cache/stats_resolved.json = the resolved stats .txt files).
Deliberately NOT using tools/class_progressions.py or tools/build_profiles.py (the code under test): this file has
its own small parser so a bug there cannot make a test pass.

Only the pak *container* reader (tools/pak.py: LSPK v18 + lz4/zstd) is shared - it just returns file bytes.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

LA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(LA, "tools"))
from game_paths import GAME_DATA  # noqa: E402  install location only (env BG3_DIR), no game logic
# load order of the game modules that define classes (a later definition with the same UUID replaces the earlier)
MODULES = [("Shared.pak", "Shared"), ("Shared.pak", "SharedDev"), ("Gustav.pak", "Gustav"),
           ("Gustav.pak", "GustavDev"), ("GustavX.pak", "GustavX")]
PROF = re.compile(r"(?<![A-Za-z])Proficiency\((\w+)\)")


def _pak_reader():
    sys.path.insert(0, os.path.join(LA, "tools"))
    from pak import Pak  # container reader only
    return Pak


def _rows(data, node_id):
    for n in ET.fromstring(data).iter("node"):
        if n.get("id") == node_id:
            yield {a.get("id"): (a.get("value") if a.get("value") is not None else a.get("handle"))
                   for a in n.findall("attribute")}


_GD = None


def load(game_data=GAME_DATA):
    """-> GameFacts (cached per process)."""
    global _GD
    if _GD is None:
        _GD = GameFacts(game_data)
    return _GD


class GameFacts:
    def __init__(self, game_data):
        Pak = _pak_reader()
        progs, descs = {}, {}
        opened = {}
        for pak, mod in MODULES:
            p = opened.get(pak) or opened.setdefault(pak, Pak(os.path.join(game_data, pak)))
            for path, store, nid in ((f"Public/{mod}/Progressions/Progressions.lsx", progs, "Progression"),
                                     (f"Public/{mod}/ClassDescriptions/ClassDescriptions.lsx", descs,
                                      "ClassDescription")):
                if path in p.by_name:
                    for r in _rows(p.read(p.by_name[path]), nid):
                        store[r["UUID"]] = r
        for p in opened.values():
            p.close()
        with open(os.path.join(LA, "data", "cache", "loca_english.json"), encoding="utf-8") as f:
            loca = json.load(f)
        with open(os.path.join(LA, "data", "cache", "stats_resolved.json"), encoding="utf-8") as f:
            self.stats = json.load(f)
        by_uuid = {d["UUID"]: d for d in descs.values()}
        self.display = {}        # internal ClassDescription Name -> shown name
        self.parent = {}         # subclass Name -> class Name
        self.subclass_names = {}  # class Name -> {shown subclass name: subclass Name}
        table = {}
        for d in descs.values():
            self.display[d["Name"]] = loca.get(d.get("DisplayName") or "", "")
            par = by_uuid.get(d.get("ParentGuid") or "")
            if par:
                self.parent[d["Name"]] = par["Name"]
            if d.get("ProgressionTableUUID"):
                table[d["ProgressionTableUUID"]] = d["Name"]
        for sub, cls in self.parent.items():
            self.subclass_names.setdefault(cls, {})[self.display[sub]] = sub
        # proficiencies: level 1 of a class (first class / IsMulticlass), every level of class + subclass tables
        self.start, self.multi, self.at_level = {}, {}, {}
        self.rage_classes = set()
        for pr in progs.values():
            owner = table.get(pr.get("TableUUID"))
            if not owner or pr.get("ProgressionType") not in ("0", "1"):
                continue
            boosts = pr.get("Boosts") or ""
            profs = set(PROF.findall(boosts))
            for pas in (pr.get("PassivesAdded") or "").split(";"):
                st = self.stats.get(pas.strip())
                if isinstance(st, dict) and "IF(" not in (st.get("Boosts") or ""):
                    profs |= set(PROF.findall(st.get("Boosts") or ""))
            if "ActionResource(Rage," in boosts:
                self.rage_classes.add(self.parent.get(owner, owner))
            lv = int(pr.get("Level") or 0)
            if lv == 1 and owner not in self.parent:
                (self.multi if pr.get("IsMulticlass") == "true" else self.start)[owner] = profs
            elif profs:
                self.at_level.setdefault(owner, {}).setdefault(lv, set()).update(profs)

    def expected_profs(self, classes, start, subclasses):
        """Weapon/armour proficiencies the game grants a build: classes {class: levels}, start = first class,
        subclasses {class: shown subclass name}."""
        out = set()
        for cls, lv in classes.items():
            out |= self.start.get(cls, set()) if cls == start else self.multi.get(cls, set())
            names = [cls]
            sub = self.subclass_names.get(cls, {}).get((subclasses or {}).get(cls))
            if sub:
                names.append(sub)
            for n in names:
                for at, ps in self.at_level.get(n, {}).items():
                    if at <= lv:
                        out |= ps
        return out

    def armour_group(self, stats_id):
        """HeavyArmor / MediumArmor / LightArmor of an armour stats entry. Items that make their wearer proficient
        (Helldusk Armour) have an empty Proficiency Group, so the category comes from the ArmorType: the group every
        other stats entry of that ArmorType carries in the game's own stats (e.g. Plate -> HeavyArmor)."""
        st = self.stats.get(stats_id)
        if not isinstance(st, dict):
            return None
        if st.get("Proficiency Group") in ("HeavyArmor", "MediumArmor", "LightArmor"):
            return st["Proficiency Group"]
        return self.type_group().get(st.get("ArmorType"))

    def type_group(self):
        if getattr(self, "_tg", None) is None:
            votes = {}
            for st in self.stats.values():
                if isinstance(st, dict) and st.get("Slot") == "Breast" and st.get("ArmorType") and \
                        st.get("Proficiency Group") in ("HeavyArmor", "MediumArmor", "LightArmor"):
                    v = votes.setdefault(st["ArmorType"], {})
                    v[st["Proficiency Group"]] = v.get(st["Proficiency Group"], 0) + 1
            self._tg = {t: max(v, key=v.get) for t, v in votes.items()}
        return self._tg

    def slot(self, stats_id):
        st = self.stats.get(stats_id)
        return st.get("Slot") if isinstance(st, dict) else None


def builds_lua(path):
    """Independent Builds.lua reader: [(id, start class, [classes]), ...] in file order + BA.Origins."""
    src = open(path, encoding="utf-8").read()
    head = src.split("BA.BuildById", 1)[0]
    builds = []
    for m in re.finditer(r'\bid\s*=\s*"([^"]+)"', head):
        blk = head[m.start(): m.start() + 3000]
        st = re.search(r'\bstart\s*=\s*"([^"]+)"', blk)
        cl = re.search(r'\bclasses\s*=\s*\{([^}]*)\}', blk)
        builds.append((m.group(1), st.group(1) if st else None, re.findall(r'"([^"]+)"', cl.group(1)) if cl else []))
    origins = {}
    tail = src.split("BA.Origins", 1)[1] if "BA.Origins" in src else ""
    for m in re.finditer(r'^\s*(\w+)\s*=\s*\{\s*builds\s*=\s*\{([^}]*)\}', tail, re.M):
        origins[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    return builds, origins
