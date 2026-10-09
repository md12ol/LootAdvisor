"""Where does every item come from? (BG3 Patch 8, read-only on the game folder)

  python extract_sources.py [--out DIR]

Writes (default LootAdvisor/data/items_all/):
  sources.jsonl   one line per (item, source) - format: data/items_all/SCHEMA.md "Source records"
  recipes.jsonl   ItemCombos.txt combinations + Adamantine Forge / story forge recipes, with where each input is
  levels.json     level folder -> {act, region, main_level, notes}
Also refreshes data/cache/level_characters_index.json when it is missing (characters.py).

Inputs: data/cache/{level_items_index,stats_resolved,loca_english,roottemplates_*}.json, the character placements
(characters.py), Public/<module>/Stats/Generated/{TreasureTable,Equipment,ItemCombos}.txt (treasure.py),
Public/<module>/Factions/*.lsx, Public/<module>/DifficultyClasses/DifficultyClasses.lsx,
Mods/<module>/Levels/*/Triggers/_merged.lsf (item-ownership areas) and the Osiris goal sources
Mods/<module>/Story/RawFiles/Goals/*.txt (hotfix paks override base goals). Modules: Shared, SharedDev, Gustav,
GustavDev, GustavX; Honour/HonourX only as a flag (honour_override on treasure tables they redefine).

Source kinds produced:
  world          item placed in a level (not inside a container / NPC)
  container      item inside a container: explicit ItemList entry, or a container-specific treasure table
  npc_equipped   weapon/armour of an NPC equipment set (Equipment.txt via the character's Equipment field)
  npc_inventory  NPC ItemList item, NPC-specific Treasures (death loot) / TradeTreasures of non-traders (pickpocket)
  trader         TradeTreasures of a trader (gold-trader table or trade-ish name) or a story-set trade table
  treasure       random drop of a generic treasure table shared by many containers/NPCs (aggregated)
  reward         story-given: Osiris goal gives the template / moves the instance / generates a reward table
  combo          ItemCombos result     forge   Adamantine Forge (or other story forge) result
Extra keys beyond the schema: "confidence" (high|medium|low), "lootable" (false when the engine blocks looting).
"""
import collections
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsf  # noqa: E402
import treasure  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "data", "cache")
OUT_DEFAULT = os.path.join(ROOT, "data", "items_all")
# party (treasure) levels per act: TreasureTable StartLevel / EndLevel windows are evaluated at these levels
# (same windows as analysis/RESEARCH_VERDICTS.md #14); a trader / container / reward roll only uses the subtables
# that are open at the party's level
ACT_LEVELS = {1: (1, 5), 2: (4, 8), 3: (7, 12)}
PLAY_ACT = {"tutorial": 1}
PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak"]
HOTFIX_PAKS = ["Patch8_HotFix9.pak", "Patch8_HotFix10.pak"]
MODULES = ["Shared", "SharedDev", "Gustav", "GustavDev", "GustavX"]
NULL = "00000000-0000-0000-0000-000000000000"
GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
RE_NAMED_GUID = re.compile(r"([A-Za-z0-9_]+?)_(" + GUID + r")")
GENERIC_HOLDERS = 3          # a treasure table used by more holders than this is "generic" -> kind treasure

# --------------------------------------------------------------------------------------------- levels / regions
MAIN_LEVELS = {
    "TUT_Avernus_C": ("tutorial", "Nautiloid (prologue)"),
    "WLD_Main_A": (1, "Act 1 wilderness (Emerald Grove, Blighted Village, Goblin Camp, Risen Road, Underdark)"),
    "CRE_Main_A": (1, "Rosymorn Monastery / Crèche Y'llek"),
    "SCL_Main_A": (2, "Shadow-Cursed Lands (Last Light, Reithwin, Moonrise Towers, Gauntlet of Shar)"),
    "INT_Main_A": (2, "Act 2 -> 3 interlude"),
    "BGO_Main_A": (3, "Rivington / Wyrm's Crossing / Wyrm's Rock (Baldur's Gate outskirts)"),
    "CTY_Main_A": (3, "Lower City (Baldur's Gate)"),
    "IRN_Main_A": (3, "Iron Throne"),
    "END_Main": (3, "Upper City / Morphic Pool / Netherbrain (endgame)"),
    "EPI_Main_A": ("epilogue", "Epilogue"),
    "BG_Main_A": (3, "Baldur's Gate (global objects)"),
}
# folder prefix -> (act, main level, default region)
PREFIX = [
    ("TUT_", "tutorial", "TUT_Avernus_C", "Nautiloid (prologue)"),
    ("WLD_", 1, "WLD_Main_A", "Act 1 wilderness"),
    ("CRE_", 1, "CRE_Main_A", "Rosymorn Monastery / Crèche Y'llek"),
    ("Cre_", 1, "CRE_Main_A", "Crèche Y'llek"),
    ("SCL_", 2, "SCL_Main_A", "Shadow-Cursed Lands"),
    ("INT_", 2, "INT_Main_A", "Act 2 -> 3 interlude"),
    ("BGO_", 3, "BGO_Main_A", "Baldur's Gate outskirts"),
    ("BGH_", 3, "CTY_Main_A", "Lower City (building)"),
    ("CTY_", 3, "CTY_Main_A", "Lower City"),
    ("IRN_", 3, "IRN_Main_A", "Iron Throne"),
    ("END_CIN_GameFinale", "epilogue", "END_Main", "Ending"),
    ("END_", 3, "END_Main", "Upper City / endgame"),
    ("EPI_", "epilogue", "EPI_Main_A", "Epilogue"),
    ("CMP_", "camp", None, "Camp"),
    ("CAMP_", "camp", None, "Camp"),
    ("GLO_", "global", None, "Global (any act)"),
    ("CLT_", "global", None, "Cinematic level template"),
    ("SYS_", "system", None, "System level (character creation, icons) - not obtainable"),
    ("TestLevel", "test", None, "Test level - not obtainable"),
    ("VoiceOfTheAbsolute", "global", None, "Voice of the Absolute (dream)"),
]
# sub-level folder -> human region (more specific than the prefix default)
REGION_OVERRIDE = {
    "WLD_Chapel_H": "Overgrown Ruins / Dank Crypt", "WLD_Chapel_Push": "Overgrown Ruins / Dank Crypt",
    "WLD_Crashsite_D": "Nautiloid crash site", "WLD_DenSubs_B": "Emerald Grove (interiors)",
    "WLD_DruidSubs_B": "Emerald Grove - Druid Grove", "WLD_Forest_G": "Blighted Village / forest",
    "WLD_GoblinCamp_D": "Goblin Camp / Shattered Sanctum", "WLD_HagLair_D": "Auntie Ethel's lair",
    "WLD_Hag_C_Evil": "Riverside Teahouse", "WLD_Hag_C_Happy": "Riverside Teahouse",
    "WLD_NautiloidCockpit_A": "Nautiloid wreck (Act 1)", "WLD_OwlbearCave_B": "Owlbear Cave",
    "WLD_Plains_D": "Risen Road / Waukeen's Rest", "WLD_RangerCamp_I": "Ranger camp (Act 1 wilderness)",
    "WLD_UnderdarkShrine_A": "Underdark - Selûnite Outpost / shrine",
    "WLD_UnderdarkSubs_C": "Underdark (sub-areas)", "WLD_UnderdarkSubs_SharVista_A": "Underdark",
    "WLD_UnderdarkTransitions_B": "Underdark (transitions)", "WLD_UnderdarkTransitions_C": "Underdark (transitions)",
    "WLD_Underdark_C": "Underdark", "WLD_VillageSubs_C": "Blighted Village (interiors)",
    "WLD_ZhentarimBasement_B": "Zhentarim Hideout (Waukeen's Rest)",
    "WLD_SharTemple_E": "Gauntlet of Shar", "WLD_Campfire_E": "Camp (Act 1)",
    "CRE_GithDungeon_A": "Crèche Y'llek - dungeon / Inquisitor", "Cre_GithCreche_D": "Crèche Y'llek",
    "CRE_AstralPlane_E_Art": "Astral Plane (Crèche)",
    "SCL_RuinsBattlefield_G": "Reithwin Town / ruins", "SCL_VillageSubs_E": "Reithwin Town (interiors)",
    "SCL_MoonriseDungeon_E_ART": "Moonrise Towers prison", "SCL_Mausoleum_E": "Thorm Mausoleum (House of Grief)",
    "SCL_MindflayerColony_G": "Mind Flayer Colony (under Moonrise)", "SCL_Nightsong_A": "Shadowfell / Nightsong",
    "SCL_Campfire_A": "Camp (Act 2)", "SCL_KethericEntrance_A": "Moonrise Towers - Ketherick",
    "BGO_WyrmsCrossing_C": "Wyrm's Crossing", "BGO_Wyrmsway_C": "Wyrm's Rock", "BGO_WyrmRockDungeon_D_Art":
    "Wyrm's Rock prison", "BGO_HouseOfHope_C": "House of Hope (Avernus)", "BGO_RamazithTower_A_ART":
    "Ramazith's Tower (Lower City)", "BGO_Sharran_Grotto": "Lower City - Shar's grotto / Cloister of Sombre Embrace",
    "BGO_UC_GuildHall_A": "Undercity - Guildhall", "BGO_UC_Ruins_B": "Undercity Ruins (Bhaal temple)",
    "BGO_UC_Sewer_D_Backup": "Lower City sewers", "BGO_UC_CazadorChapel_A": "Cazador's palace chapel",
    "BGO_JungleOfChult_A": "Jungle of Chult (dream)", "BGO_MorphicPool_A": "Morphic Pool",
    "PLT_UND_AdamantineForge": "Grymforge - Adamantine Forge", "PLT_UND_AdamantineForgeAnvil":
    "Grymforge - Adamantine Forge", "PLT_CRE_BloodOfLathander_Ring": "Rosymorn Monastery - Blood of Lathander",
    "PLT_BGO_Circus_A": "Wyrm's Crossing - Circus of the Last Days",
    "PLT_BGO_CircusAftermath_A": "Wyrm's Crossing - Circus of the Last Days",
}
# area code in object names (S_<CODE>_<Sub>_...) -> region, per act
AREA_CODES = {
    "UND": "Underdark", "GOB": "Goblin Camp / Shattered Sanctum", "DEN": "Emerald Grove",
    "PLA": "Risen Road / Waukeen's Rest / Zhentarim hideout", "FOR": "Blighted Village / forest",
    "CHA": "Overgrown Ruins / Dank Crypt", "HAG": "Riverside Teahouse / Sunlit Wetlands",
    "CRA": "Nautiloid crash site", "CAMP": "Camp", "ORI": "Origin story (companion quest)",
    "TUT": "Nautiloid", "CRE": "Rosymorn Monastery / Crèche Y'llek", "SHA": "Gauntlet of Shar", "MOO": "Moonrise Towers",
    "HAV": "Last Light Inn", "SCL": "Shadow-Cursed Lands", "TWN": "Reithwin Town", "COL": "Mind Flayer Colony",
    "SCE": "Shadow-Cursed Lands", "WYR": "Rivington / Wyrm's Crossing / Wyrm's Rock", "LOW": "Lower City",
    "END": "Upper City / endgame", "IRN": "Iron Throne", "INT": "Interlude", "GLO": None,
}
SUBCODES = {("UND", "KC"): "Grymforge", ("LOW", "SWS"): "Steel Watch patrol streets"}
SUB_SKIP = {"Legendary", "Generic", "Trader", "Trade", "Guard", "Key", "Chest", "Door", "Main", "Debug", "Book", "Body"}
CODE_ACT = {"UND": 1, "GOB": 1, "DEN": 1, "PLA": 1, "FOR": 1, "CHA": 1, "HAG": 1, "CRA": 1, "TUT": "tutorial",
            "CRE": 1, "SHA": 2, "MOO": 2, "HAV": 2, "SCL": 2, "TWN": 2, "COL": 2, "SCE": 2, "WYR": 3, "LOW": 3,
            "BGO": 3, "BGH": 3, "CTY": 3, "END": 3, "IRN": 3, "INT": 2, "Cazador": 3, "MF": 3, "WYM": 3,
            "SewerRaft": 3, "Platform": 1}


def humanize(name):
    s = re.sub(r"^(PLT|LT)_", "", name)
    s = re.sub(r"^[A-Z][A-Za-z]{1,3}_", "", s)
    s = re.sub(r"(_(A|B|C|D|E|F|G|H|I|Art|ART|Backup|Push|\d+))+$", "", s)
    s = s.replace("_", " ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    return s.strip()


def level_info(name):
    if name in MAIN_LEVELS:
        act, region = MAIN_LEVELS[name]
        return {"act": act, "region": region, "main_level": name, "notes": "main level"}
    if name.startswith(("PLT_", "LT_")):
        toks = re.sub(r"^(PLT|LT)_", "", name).split("_")
        code = toks[0]
        act = None
        for t in toks:
            act = CODE_ACT.get(t) or CODE_ACT.get(t.upper()) or {"CMP": "camp", "SYS": "system"}.get(t.upper())
            if act is not None:
                code = t.upper() if t.upper() in AREA_CODES else t
                break
        reg = REGION_OVERRIDE.get(name) or ((AREA_CODES.get(code) or "") + " - " + humanize(name)).strip(" -")
        return {"act": act, "region": reg, "main_level": None,
                "notes": "platform / level template (dynamic geometry); act guessed from area code"}
    for pre, act, main, default in PREFIX:
        if name.startswith(pre):
            reg = REGION_OVERRIDE.get(name)
            if reg is None:
                h = humanize(name)
                reg = f"{default} - {h}" if h and h.lower() not in default.lower() else default
            note = "sub-level of " + main if main else ""
            if "_CIN_" in name or name.startswith("CLT_"):
                note = (note + "; cinematic set").strip("; ")
            if name == "WLD_SharTemple_E":
                act, note = 2, "Gauntlet of Shar (reached from the Shadow-Cursed Lands; WLD_ prefix is historic)"
            return {"act": act, "region": reg, "main_level": main, "notes": note}
    return {"act": None, "region": humanize(name), "main_level": None, "notes": "unknown prefix"}


def name_region(obj_name, level_act):
    """Region from an S_<CODE>_<Sub>_ object name, or None."""
    n = re.sub(r"^S_", "", obj_name or "")
    parts = n.split("_")
    if len(parts) < 2:
        return None
    code = parts[0]
    area = AREA_CODES.get(code)
    if not area:
        return None
    sub = parts[1]
    if (code, sub) in SUBCODES:
        return f"{area}: {SUBCODES[(code, sub)]}"
    if (len(sub) >= 4 and sub.isalpha() and sub not in SUB_SKIP and not sub.isupper()
            and len(parts) > 2):
        return f"{area}: {humanize(sub)}"
    return area


# --------------------------------------------------------------------------------------------- game text files
def read_files(paks, pred):
    """{path: text} for pak entries matching pred(path); later paks override (hotfixes last)."""
    out = {}
    for pk in paks:
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            if pred(e.name):
                out[e.name] = p.read(e).decode("utf-8", "replace")
        p.close()
    return out


def module_of(path):
    parts = path.split("/")
    return parts[1] if len(parts) > 1 else None


def load_lsx_nodes(text, node_id):
    root = ET.fromstring(text)
    out = []
    for n in root.iter("node"):
        if n.get("id") == node_id:
            out.append({a.get("id"): a.get("value") for a in n.findall("attribute")})
    return out


class Factions:
    def __init__(self):
        files = read_files(PAKS, lambda n: n.startswith("Public/") and "/Factions/" in n and n.endswith(".lsx")
                           and module_of(n) in MODULES)
        self.by_guid = {}
        self.rel = {}
        for path in sorted(files, key=lambda p: MODULES.index(module_of(p))):
            t = files[path]
            if path.endswith("Factions.lsx"):
                for a in load_lsx_nodes(t, "Faction"):
                    self.by_guid[a.get("UUID")] = {"name": a.get("Faction"), "parent": a.get("ParentGuid")}
            elif path.endswith("Relations.lsx"):
                for a in load_lsx_nodes(t, "Relation"):
                    try:
                        self.rel[(a.get("Source"), a.get("Target"))] = int(a.get("Value"))
                    except (TypeError, ValueError):
                        pass
        self.hero = [g for g, f in self.by_guid.items() if f["name"] in ("Hero", "Hero Player1")]

    def name(self, guid):
        f = self.by_guid.get(guid)
        return f["name"] if f else None

    def chain(self, guid):
        out, seen = [], set()
        while guid and guid != NULL and guid not in seen and guid in self.by_guid:
            seen.add(guid)
            out.append(guid)
            guid = self.by_guid[guid]["parent"]
        return out

    def relation_to_player(self, guid):
        for g in self.chain(guid):
            for h in self.hero:
                for hh in self.chain(h):
                    for k in ((g, hh), (hh, g)):
                        if k in self.rel:
                            return self.rel[k]
        return None


def load_dcs():
    files = read_files(PAKS, lambda n: n.endswith("DifficultyClasses/DifficultyClasses.lsx")
                       and module_of(n) in MODULES)
    out = {}
    for path in sorted(files, key=lambda p: MODULES.index(module_of(p))):
        for a in load_lsx_nodes(files[path], "DifficultyClass"):
            d = (a.get("Difficulties") or "").split(",")[0]
            out[a.get("UUID")] = {"name": a.get("Name"), "dc": int(d) if d.strip().lstrip("-").isdigit() else None}
    return out


def load_equipment():
    files = read_files(PAKS, lambda n: n.endswith("/Stats/Generated/Equipment.txt") and module_of(n) in MODULES)
    sets = {}
    for path in sorted(files, key=lambda p: MODULES.index(module_of(p))):
        cur = None
        for line in files[path].splitlines():
            m = re.match(r'\s*new equipment\s+"([^"]+)"', line)
            if m:
                cur = {"groups": [], "weaponset": None, "module": module_of(path)}
                sets[m.group(1)] = cur
                continue
            if cur is None:
                continue
            if re.match(r"\s*add equipmentgroup", line):
                cur["groups"].append([])
                continue
            m = re.match(r'\s*add equipment entry\s+"([^"]+)"', line)
            if m:
                if not cur["groups"]:
                    cur["groups"].append([])
                cur["groups"][-1].append(m.group(1))
                continue
            m = re.match(r'\s*add initialweaponset\s+"([^"]+)"', line)
            if m:
                cur["weaponset"] = m.group(1)
    return sets


def load_goals():
    """{goal name: text} - campaign modules, hotfix paks override the same path."""
    pred = (lambda n: "/Story/RawFiles/Goals/" in n and n.endswith(".txt") and module_of(n) in MODULES)
    files = read_files(PAKS + HOTFIX_PAKS, pred)
    return {os.path.basename(p)[:-4]: (module_of(p), t) for p, t in files.items()}


def load_quests():
    """Quest steps with rewards from Mods/<module>/Story/Journal/quest_prototypes.lsx, plus all objective ids."""
    files = read_files(PAKS, lambda n: n.endswith("/Story/Journal/quest_prototypes.lsx") or
                       n.endswith("/Story/Journal/objective_prototypes.lsx"))
    steps, objectives = [], set()

    def attrs(n):
        return {a.get("id").strip(): (a.get("value") if a.get("value") is not None else a.get("handle"))
                for a in n.findall("attribute")}
    for path, text in files.items():
        if module_of(path) not in MODULES:
            continue
        root = ET.fromstring(text)
        if path.endswith("objective_prototypes.lsx"):
            for n in root.iter("node"):
                if n.get("id") == "Objective":
                    objectives.add(attrs(n).get("ObjectiveID"))
            continue
        for q in root.iter("node"):
            if q.get("id") != "Quest":
                continue
            qa = attrs(q)
            for st in q.iter("node"):
                if st.get("id") != "QuestStep":
                    continue
                sa = attrs(st)
                rec = {"quest": qa.get("QuestID"), "title": qa.get("QuestTitle"), "step": sa.get("ID"),
                       "objective": sa.get("Objective"), "dev": sa.get("DevComment"), "tables": [],
                       "optional": [], "templates": [], "module": module_of(path)}
                if sa.get("RewardAdditionalTreasureTable"):
                    rec["tables"].append(sa["RewardAdditionalTreasureTable"])
                for k in st.iter("node"):
                    ka = attrs(k)
                    if k.get("id") == "QuestRewardTables" and ka.get("QuestRewardTables"):
                        rec["tables"].append(ka["QuestRewardTables"])
                    elif k.get("id") == "QuestRewardOptionalTables" and ka.get("QuestRewardOptionalTables"):
                        rec["optional"].append(ka["QuestRewardOptionalTables"])
                    elif k.get("id") == "RewardTemplateDescription" and ka.get("RewardTemplateDescriptionGUID"):
                        rec["templates"].append((ka["RewardTemplateDescriptionGUID"],
                                                 str(ka.get("RewardTemplateDescriptionIsRootTemplate")).lower()
                                                 == "true"))
                objectives.add(sa.get("Objective"))
                objectives.add(sa.get("ID"))
                steps.append(rec)
    objectives.discard(None)
    return steps, objectives


def load_item_combos():
    files = read_files(PAKS, lambda n: n.endswith("/Stats/Generated/ItemCombos.txt") and module_of(n) in MODULES)
    combos, results = {}, {}
    for path in sorted(files, key=lambda p: MODULES.index(module_of(p))):
        cur = None
        for line in files[path].splitlines():
            m = re.match(r'\s*new (ItemCombination|ItemCombinationResult)\s+"([^"]+)"', line)
            if m:
                cur = {"name": m.group(2), "module": module_of(path), "data": {}}
                (combos if m.group(1) == "ItemCombination" else results)[m.group(2)] = cur
                continue
            m = re.match(r'\s*data\s+"([^"]+)"\s+"([^"]*)"', line)
            if m and cur is not None:
                cur["data"][m.group(1)] = m.group(2)
    return combos, results


# --------------------------------------------------------------------------------------------- triggers (ownership)
def load_triggers(wanted):
    """{trigger MapKey: shape} for the wanted trigger GUIDs (Mods/*/Levels/*/Triggers/_merged.lsf)."""
    out = {}
    rx = re.compile(r"^Mods/([^/]+)/(?:Levels|Globals)/([^/]+)/Triggers/_merged\.lsf$")
    for pk in PAKS:
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            m = rx.match(e.name)
            if not m or m.group(1) not in MODULES:
                continue
            res = lsf.load(p.read(e))
            for reg in res.regions:
                for g in reg.children:
                    mk = g.get("MapKey")
                    if mk not in wanted:
                        continue
                    tr = g.child("Transform")
                    shape = {"level": m.group(2), "name": g.get("Name"),
                             "pos": tr.get("Position") if tr is not None else None,
                             "rot": tr.get("RotationQuat") if tr is not None else None}
                    pts = [c.get("Object") for c in g.children if c.name == "Points" and c.get("Object")]
                    if pts:
                        shape.update(kind="poly", points=pts, height=g.get("Height") or 10.0)
                    elif g.get("Extents"):
                        shape.update(kind="box", extents=g.get("Extents"))
                    elif g.get("Radius"):
                        shape.update(kind="sphere", radius=g.get("Radius"))
                    elif shape["pos"] is not None:
                        shape.update(kind="point")          # a point trigger (spawn / teleport target): position only
                    else:
                        continue
                    out[mk] = shape
        p.close()
    return out


def _qrot_inv(q, v):
    x, y, z, w = q
    # rotate v by the conjugate quaternion
    qx, qy, qz, qw = -x, -y, -z, w
    tx = 2 * (qy * v[2] - qz * v[1])
    ty = 2 * (qz * v[0] - qx * v[2])
    tz = 2 * (qx * v[1] - qy * v[0])
    return [v[0] + qw * tx + (qy * tz - qz * ty), v[1] + qw * ty + (qz * tx - qx * tz),
            v[2] + qw * tz + (qx * ty - qy * tx)]


def _in_poly(x, z, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, zi = pts[i]
        xj, zj = pts[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / ((zj - zi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def in_trigger(pos, s):
    if not pos or not s.get("pos"):
        return False
    d = [pos[i] - s["pos"][i] for i in range(3)]
    if s["kind"] == "sphere":
        return math.sqrt(sum(x * x for x in d)) <= s["radius"]
    if s["kind"] == "box":
        loc = _qrot_inv(s["rot"], d) if s.get("rot") else d
        return all(abs(loc[i]) <= s["extents"][i] / 2 + 0.25 for i in range(3))
    if s["kind"] == "poly":
        loc = _qrot_inv(s["rot"], d) if s.get("rot") else d
        return -2.0 <= loc[1] <= s["height"] + 2.0 and _in_poly(loc[0], loc[2], s["points"])
    return False


# --------------------------------------------------------------------------------------------- items
class Items:
    def __init__(self, stats):
        self.stats = stats
        self.tmpl = {}
        for fn in sorted(os.listdir(CACHE)):
            if not fn.startswith("roottemplates_") or "Honour" in fn:
                continue
            for r in json.load(open(os.path.join(CACHE, fn), encoding="utf-8")):
                inh = r.get("inherited") or {}
                st = r.get("Stats") or inh.get("Stats")
                dn = (r.get("DisplayName") or inh.get("DisplayName") or {}).get("text")
                self.tmpl[r["MapKey"]] = {"name": r.get("Name"), "stats": st, "display": dn,
                                          "story": bool(r.get("StoryItem")), "is_key": bool(r.get("IsKey")),
                                          "key": r.get("Key"), "parent": r.get("ParentTemplateId"),
                                          "inv": r.get("InventoryList"), "items": r.get("ItemList")}
        self.by_stats = collections.defaultdict(list)
        for mk, t in self.tmpl.items():
            if t["stats"]:
                self.by_stats[t["stats"]].append(mk)
        self.extra = set()          # stats ids that are recipe / forge inputs (always relevant)
        self.by_name = {}
        for mk, t in self.tmpl.items():
            self.by_name.setdefault(t["name"], mk)

    def contents(self, mk):
        """(InventoryList, ItemList) a placement of template mk inherits: nearest InventoryList in the
        parent chain, ItemList entries of the whole chain."""
        inv, items, seen = None, [], set()
        while mk and mk in self.tmpl and mk not in seen:
            seen.add(mk)
            t = self.tmpl[mk]
            if inv is None and t["inv"]:
                inv = t["inv"]
            items += t["items"] or []
            mk = t["parent"]
        return inv or [], items

    def template_for(self, stats_id):
        e = self.stats.get(stats_id) or {}
        rt = e.get("RootTemplate")
        if rt and rt in self.tmpl:
            return rt
        lst = self.by_stats.get(stats_id)
        return lst[0] if lst else (rt or None)

    def stats_of(self, mk):
        t = self.tmpl.get(mk)
        return t["stats"] if t else None

    def type_of(self, stats_id):
        e = self.stats.get(stats_id)
        return e.get("_type") if e else None

    def name_of(self, stats_id=None, mk=None):
        if mk and mk in self.tmpl and self.tmpl[mk]["display"]:
            return self.tmpl[mk]["display"]
        mk2 = self.template_for(stats_id) if stats_id else None
        if mk2 and mk2 in self.tmpl:
            return self.tmpl[mk2]["display"]
        return stats_id

    def relevant(self, stats_id, template=None):
        """Loot-worthy item: weapons, armour/accessories and pick-up-able objects (not scenery / containers)."""
        e = self.stats.get(stats_id)
        if not e:
            return False
        t = e.get("_type")
        if t in ("Weapon", "Armor"):
            return True
        if t != "Object":
            return False
        tab = e.get("InventoryTab")
        if tab in ("Magical", "Consumable", "BooksAndKeys", "Equipment"):
            return True
        if tab == "Misc" and not stats_id.startswith("OBJ_"):
            return True
        if template and template in self.tmpl and (self.tmpl[template]["story"] or self.tmpl[template]["is_key"]):
            return True
        if stats_id in self.extra and not stats_id.startswith("OBJ_Generic"):
            return True
        return bool(e.get("Unique") == "1")


# --------------------------------------------------------------------------------------------- main build
class Builder:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.t0 = time.time()
        self.log("loading caches")
        self.texts = json.load(open(os.path.join(CACHE, "loca_english.json"), encoding="utf-8"))
        self.stats = json.load(open(os.path.join(CACHE, "stats_resolved.json"), encoding="utf-8"))
        self.items = Items(self.stats)
        self.places = json.load(open(os.path.join(CACHE, "level_items_index.json"), encoding="utf-8"))
        gpath = os.path.join(CACHE, "global_items_index.json")
        if not os.path.exists(gpath):
            import global_items
            global_items.build(CACHE, self.texts)
        self.places += json.load(open(gpath, encoding="utf-8"))
        self.places = [p for p in self.places if p.get("module") in MODULES]
        cpath = os.path.join(CACHE, "level_characters_index.json")
        if not os.path.exists(cpath):
            import characters
            characters.build(CACHE, self.texts)
        self.chars = json.load(open(cpath, encoding="utf-8"))
        self.place_by_mk = {p["MapKey"]: p for p in self.places}
        self.char_by_mk = {c["MapKey"]: c for c in self.chars}
        self.log("loading game text files")
        self.tables = treasure.load_tables()
        self.honour_tables = {n for n, t in treasure.load_tables(honour=True).items()
                              if t["module"] in treasure.HONOUR_MODULES}
        self.factions = Factions()
        self.dcs = load_dcs()
        self.equipment = load_equipment()
        self.goals = load_goals()
        self.combos, self.combo_results = load_item_combos()
        self.quests, self.objectives = load_quests()
        self.records = []
        self.levels = {}
        self._expand_cache = {}
        self.keys_by_name = collections.defaultdict(list)
        for p in self.places:
            if p.get("IsKey") and p.get("Key"):
                self.keys_by_name[p["Key"]].append(p)
        self.contained = {}          # instance item MapKey -> ("container"|"npc", holder record, ItemList entry)

    def log(self, msg):
        print(f"[{time.time() - self.t0:6.1f}s] {msg}", flush=True)

    # ---------------------------------------------------------------- helpers
    def lvl(self, name):
        if name not in self.levels:
            self.levels[name] = level_info(name)
        return self.levels[name]

    def expand(self, table, level=None):
        key = (table, level)
        if key not in self._expand_cache:
            self._expand_cache[key] = treasure.best_per_id(treasure.expand(table, self.tables, level=level))
        return self._expand_cache[key]

    def expand_act(self, table, act):
        """Table drops for the party levels of one act (ACT_LEVELS): per item the best chance over those levels and
        the levels at which it can drop. act None -> every subtable (no level filter)."""
        rng = ACT_LEVELS.get(act)
        if not rng:
            return [dict(d, levels=None) for d in self.expand(table)]
        best = {}
        for lv in range(rng[0], rng[1] + 1):
            for d in self.expand(table, lv):
                k = (d["kind"], d["id"])
                if k not in best:
                    best[k] = dict(d, levels=[lv])
                else:
                    best[k]["levels"].append(lv)
                    if d["chance"] > best[k]["chance"]:
                        best[k].update({"chance": d["chance"], "paths": d["paths"]})
        return list(best.values())

    def add(self, stats_id, template, kind, level=None, position=None, holder=None, container=None,
            treasure_table=None, chance=1.0, steal=False, requires=None, notes=None, confidence="high",
            region=None, lootable=True, **extra):
        li = self.lvl(level) if level else {"act": None, "region": None}
        rec = {"stats_id": stats_id, "template": template, "kind": kind, "level": level, "act": li["act"],
               "region": region or li["region"], "position": position, "holder": holder, "container": container,
               "treasure_table": treasure_table, "chance": round(chance, 4) if chance is not None else None,
               "steal": bool(steal), "requires": requires, "notes": notes, "confidence": confidence}
        if not lootable:
            rec["lootable"] = False
        rec.update(extra)
        self.records.append(rec)
        return rec

    def char_name(self, c):
        return c.get("display_name") or c.get("Name")

    def holder_of(self, c):
        rel = self.factions.relation_to_player(c.get("Faction"))
        neutral = rel is None or rel > 0
        h = {"name": self.char_name(c), "MapKey": c["MapKey"], "template": c.get("TemplateName"),
             "faction": self.factions.name(c.get("Faction")), "neutral": neutral}
        if c.get("title"):
            h["title"] = c["title"]
        if c.get("IsBoss"):
            h["boss"] = True
        if c.get("CombatGroupID"):
            h["combat_group"] = c["CombatGroupID"]
        if c.get("Name"):
            h["object_name"] = c["Name"]
        return h

    # ---------------------------------------------------------------- regions
    def build_region_index(self):
        """Per main-level folder: list of (pos, region) of objects whose name carries an area code."""
        self.region_pts = collections.defaultdict(list)
        for c in self.chars:
            r = name_region(c.get("Name"), None)
            if r and c.get("position"):
                self.region_pts[c["level"]].append((c["position"], r))
        for p in self.places:
            r = name_region(p.get("Name"), None)
            if r and p.get("position"):
                self.region_pts[p["level"]].append((p["position"], r))

    def region_for(self, level, name, pos):
        li = self.lvl(level)
        if level not in MAIN_LEVELS:
            return li["region"]
        r = name_region(name, li["act"])
        if r:
            return r
        best, bd = None, 45.0 ** 2
        if pos:
            for q, rr in self.region_pts.get(level, ()):
                d = (q[0] - pos[0]) ** 2 + (q[1] - pos[1]) ** 2 + (q[2] - pos[2]) ** 2
                if d < bd:
                    best, bd = rr, d
        return best or li["region"]

    # ---------------------------------------------------------------- ownership areas
    def build_ownership(self):
        facts = []
        for gname, (mod, text) in self.goals.items():
            for m in re.finditer(r'DB_ItemOwnerShipTriggers(?:Fallback)?\(\s*"([^"]*)"\s*,\s*(?:\([A-Z]+\))?\s*'
                                 r'[A-Za-z0-9_]*?_(' + GUID + r')\s*,\s*(?:\([A-Z]+\))?\s*[A-Za-z0-9_]*?_(' + GUID
                                 + r')', text):
                facts.append((m.group(1), m.group(2), m.group(3), gname))
        shapes = load_triggers({f[1] for f in facts})
        self.owner_areas = []
        for lev, trig, owner, gname in facts:
            s = shapes.get(trig)
            if s:
                c = self.char_by_mk.get(owner)
                self.owner_areas.append((s, owner, self.char_name(c) if c else owner, gname))
        self.log(f"ownership areas: {len(facts)} facts, {len(self.owner_areas)} trigger shapes resolved")

    def area_owner(self, place):
        pos = place.get("position")
        if not pos:
            return None
        act = self.lvl(place["level"])["act"]
        for s, owner, oname, g in self.owner_areas:
            lact = self.lvl(s["level"])["act"]
            if lact != act:
                continue
            if in_trigger(pos, s):
                return oname
        return None

    # ---------------------------------------------------------------- goal references
    def scan_goals(self):
        """Collect item template / instance references in Osiris goals."""
        give = re.compile(r"TemplateAddTo\(|ToInventory\(|GiveItem|Reward|CreateAt|CreateItem|SpawnItem|"
                          r"ItemMoveTo\(|_Result\(|GiveEquipment|Equip\(|AddToInventory|MoveItem", re.I)
        check = re.compile(r"IsInInventory|TemplateIsInInventory|HasTemplate|PlayerHasTemplateItem|GetItemByTemplate|"
                           r"TemplateRemoveFrom|TemplateAddedTo|TemplateRemovedFrom|Destroy|GetTemplate|"
                           r"CountInMagicPockets|TemplateUse|Unequip|Equipped\(|IsEquipped|Removed", re.I)
        self.goal_template_refs = collections.defaultdict(list)    # template -> [(goal, line, strong)]
        self.goal_instance_refs = collections.defaultdict(list)    # instance -> [(goal, line, strong)]
        self.goal_trade = []                                          # (goal, char MapKey, table)
        self.goal_tables = []                                         # (goal, table, line)
        self.forge = []                                               # (goal, result tmpl, input tmpls, line)
        table_names = set(self.tables)
        for gname, (mod, text) in sorted(self.goals.items()):
            for raw in text.splitlines():
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                m = re.search(r"(?:PROC_)?SetCustomTradeTreasure\(\s*(?:\([A-Z]+\))?\s*[A-Za-z0-9_]*?_(" + GUID
                              + r")\s*,\s*\"([^\"]+)\"", line)
                if m:
                    self.goal_trade.append((gname, m.group(1), m.group(2), line))
                    continue
                for q in re.findall(r'"([A-Za-z0-9_]+)"', line):
                    if q in table_names and q != "Empty" and re.search(r"Treasure|Reward|Loot|Generate", line, re.I):
                        self.goal_tables.append((gname, q, line))
                refs = RE_NAMED_GUID.findall(line)
                if not refs:
                    continue
                bare = RE_NAMED_GUID.sub("<ref>", line)
                strong = bool(give.search(bare)) and not check.search(bare)
                tmpl_refs = [g for _, g in refs if g in self.items.tmpl]
                if re.match(r"DB_[A-Za-z0-9_]*Forge[A-Za-z0-9_]*_Result\(", line) and len(tmpl_refs) >= 2:
                    self.forge.append((gname, tmpl_refs[0], tmpl_refs[1:], line))
                    continue
                for g in tmpl_refs:
                    self.goal_template_refs[g].append((gname, line, strong, bare))
                for _, g in refs:
                    if g in self.place_by_mk:
                        self.goal_instance_refs[g].append((gname, line, strong, bare))
        self.log(f"goals: {len(self.goals)} files, {len(self.goal_template_refs)} item templates and "
                 f"{len(self.goal_instance_refs)} item instances referenced, {len(self.goal_trade)} trade-table "
                 f"switches, {len(self.goal_tables)} treasure-table refs, {len(self.forge)} forge results")

    # ---------------------------------------------------------------- treasure helpers
    def holders_per_table(self):
        cnt = collections.Counter()
        for p in self.places:
            for t in p.get("InventoryList") or self.items.contents(p.get("TemplateName"))[0]:
                cnt[t] += 1
        for c in self.chars:
            for t in (c.get("Treasures") or []) + (c.get("TradeTreasures") or []):
                cnt[t] += 1
        return cnt

    def is_trader_table(self, table, char=None):
        if re.search(r"Trade|Trader|Vendor|Merchant|Quarter ?master|Barkeep|Bartender|Shop", table, re.I):
            return True
        return any("Gold_Trader" in " ".join(p) for d in self.expand(table) for p in d.get("paths", []))

    def emit_table(self, table, kind, base, chance_note=""):
        """Expanded table -> one record per item (base = kwargs for add)."""
        n = 0
        act = self.lvl(base["level"])["act"] if base.get("level") else None
        act = PLAY_ACT.get(act, act)
        for d in self.expand_act(table, act):
            if d["kind"] != "item" or d["chance"] <= 0:
                continue
            sid = d["id"]
            if sid not in self.stats:
                continue
            tm = self.items.template_for(sid)
            lv = ""
            if d.get("levels"):
                lv = f"party level {min(d['levels'])}-{max(d['levels'])} (act window {ACT_LEVELS[act][0]}-"                      f"{ACT_LEVELS[act][1]})"
            elif d.get("min_level") or d.get("max_level"):
                lv = f"treasure level {d.get('min_level') or 1}-{d.get('max_level') or ''}".rstrip("-")
            notes = "; ".join(x for x in [base.get("notes"), lv, "via " + " > ".join(d["paths"][0])] if x)
            kw = dict(base)
            kw["notes"] = notes
            if table in self.honour_tables:
                kw["honour_override"] = True
            self.add(sid, tm, kind, treasure_table=table, chance=d["chance"], **kw)
            n += 1
        return n

    # ---------------------------------------------------------------- sources: world + containers
    def do_world_and_containers(self):
        # instance items inside containers / NPC ItemLists
        for p in self.places:
            for e in p.get("ItemList", []) or []:
                if e.get("Type") == 2 and e.get("UUID"):
                    self.contained[e["UUID"]] = ("container", p, e)
        for c in self.chars:
            for e in c.get("ItemList", []) or []:
                if e.get("Type") == 2 and e.get("UUID"):
                    self.contained[e["UUID"]] = ("npc", c, e)
        holders = self.holders_per_table()
        self.generic = collections.defaultdict(list)   # table -> [(holder kind, level, name)]
        nworld = ncont = 0
        for p in self.places:
            sid = p.get("Stats") or (p.get("template") or {}).get("Stats")
            tm = p.get("TemplateName")
            level = p["level"]
            # --- the placement itself as an item
            if sid and self.items.relevant(sid, tm) and p["MapKey"] not in self.contained:
                owner = self.owner_name(p)
                area = None if owner else self.area_owner(p)
                req, notes, conf = [], [], "high"
                if owner or area:
                    req.append(f"owned by {owner or area} (stealing is a crime)")
                refs = self.goal_instance_refs.get(p["MapKey"])
                if refs:
                    notes.append("referenced by story goal " + ", ".join(sorted({r[0] for r in refs})[:4]))
                    conf = "medium"
                if p.get("StoryItem"):
                    notes.append("story item")
                if p.get("Amount"):
                    notes.append(f"amount {p['Amount']}")
                if self.lvl(level)["act"] in ("system", "test") or "_CIN_" in level or level.startswith("CLT_"):
                    notes.append("non-gameplay or cinematic level (props, usually not lootable)")
                    conf = "low"
                nm = (p.get("DisplayName") or {}).get("text")
                if nm:
                    notes.append(f"placed as '{nm}' ({p.get('Name')})")
                else:
                    notes.append(f"object {p.get('Name')}")
                self.add(sid, tm, "world", level=level, position=p.get("position"), steal=bool(owner or area),
                         requires="; ".join(req) or None, notes="; ".join(notes) or None, confidence=conf,
                         region=self.region_for(level, p.get("Name"), p.get("position")), instance=p["MapKey"])
                nworld += 1
            # --- the placement as a container
            tinv, titems = self.items.contents(tm)
            inv = [t for t in (p.get("InventoryList") or tinv) if t and t != "Empty"]
            ilist = (p.get("ItemList") or []) + [e for e in titems if e.get("Type") != 2]
            if not inv and not ilist:
                continue
            cont = self.container_info(p)
            region = self.region_for(level, p.get("Name"), p.get("position"))
            req = self.container_requires(cont)
            for e in ilist:
                if e.get("Type") == 2:
                    continue      # instance: emitted from its own placement below
                sid2, tm2 = self.itemlist_entry(e)
                if not sid2:
                    continue
                self.add(sid2, tm2, "container", level=level, position=p.get("position"), container=cont,
                         steal=bool(cont.get("owner")), requires=req, region=region,
                         notes=f"amount {e.get('Amount', 1)}" if e.get("Amount", 1) != 1 else None)
                ncont += 1
            for t in inv:
                if holders[t] > GENERIC_HOLDERS:
                    self.generic[t].append(("container", level, cont["name"]))
                    continue
                ncont += self.emit_table(t, "container", dict(level=level, position=p.get("position"),
                                                             container=cont, steal=bool(cont.get("owner")),
                                                             requires=req, region=region))
        # instance items that sit inside containers / NPC inventories
        for mk, (hk, h, e) in self.contained.items():
            p = self.place_by_mk.get(mk)
            if not p:
                continue
            sid = p.get("Stats") or (p.get("template") or {}).get("Stats")
            if not sid or sid not in self.stats:
                continue
            refs = self.goal_instance_refs.get(mk)
            note = ("referenced by story goal " + ", ".join(sorted({r[0] for r in refs})[:4])) if refs else None
            if hk == "container":
                cont = self.container_info(h)
                self.add(sid, p.get("TemplateName"), "container", level=h["level"], position=h.get("position"),
                         container=cont, steal=bool(cont.get("owner")), requires=self.container_requires(cont),
                         region=self.region_for(h["level"], h.get("Name"), h.get("position")), notes=note,
                         instance=mk)
            else:
                self.npc_item_record(h, sid, p.get("TemplateName"), e, instance=mk, extra_note=note)
            ncont += 1
        self.log(f"world: {nworld} placements, container: {ncont} records")

    def owner_name(self, p):
        o = p.get("owner")
        if not o:
            return None
        c = self.char_by_mk.get(o)
        return self.char_name(c) if c else o

    def container_info(self, p):
        nm = (p.get("DisplayName") or {}).get("text") or (p.get("template") or {}).get("DisplayName") or p.get("Name")
        dc = self.dcs.get(p.get("LockDifficultyClassID")) if p.get("LockDifficultyClassID") else None
        info = {"name": nm, "MapKey": p["MapKey"], "locked": bool(p.get("LockDifficultyClassID")),
                "owner": self.owner_name(p) or self.area_owner(p), "object_name": p.get("Name")}
        if dc:
            info["lock_dc"] = dc["dc"]
        if p.get("Key"):
            info["key"] = p["Key"]
            ks = self.keys_by_name.get(p["Key"])
            if ks:
                k = ks[0]
                info["key_item"] = {"name": (k.get("DisplayName") or {}).get("text") or
                                    (k.get("template") or {}).get("DisplayName"), "MapKey": k["MapKey"],
                                    "level": k["level"], "position": k.get("position")}
        if p.get("DisarmDifficultyClassID") or p.get("IsTrap"):
            info["trapped"] = True
        return info

    def container_requires(self, cont):
        req = []
        if cont.get("locked"):
            s = "locked"
            if cont.get("lock_dc"):
                s += f" (DC {cont['lock_dc']})"
            if cont.get("key_item"):
                s += f"; key: {cont['key_item']['name']}"
            elif cont.get("key"):
                s += f"; key id {cont['key']}"
            req.append(s)
        if cont.get("owner"):
            req.append(f"owned by {cont['owner']} (stealing is a crime)")
        if cont.get("trapped"):
            req.append("trapped")
        return "; ".join(req) or None

    def itemlist_entry(self, e):
        if e.get("Type") == 0:
            sid = e.get("ItemName")
            return (sid, self.items.template_for(sid)) if sid in self.stats else (None, None)
        tm = e.get("TemplateID")
        sid = self.items.stats_of(tm) if tm else None
        if not sid and e.get("ItemName") in self.stats:
            sid = e["ItemName"]
        return (sid, tm) if sid else (None, None)

    # ---------------------------------------------------------------- sources: NPCs
    def npc_item_record(self, c, sid, tm, e, instance=None, extra_note=None):
        notes = []
        lootable = c.get("IsLootable", True) is not False
        if e is not None:
            if e.get("IsDroppedOnDeath") is False:
                notes.append("not dropped on death")
            if e.get("CanBePickpocketed"):
                notes.append("pickpocketable")
            if e.get("IsTradable"):
                notes.append("tradable")
            if e.get("Amount", 1) != 1:
                notes.append(f"amount {e['Amount']}")
        if extra_note:
            notes.append(extra_note)
        h = self.holder_of(c)
        self.add(sid, tm, "npc_inventory", level=c["level"], position=c.get("position"), holder=h,
                 steal=h["neutral"], requires=self.npc_requires(h), notes="; ".join(notes) or None,
                 region=self.region_for(c["level"], c.get("Name"), c.get("position")), lootable=lootable,
                 instance=instance)

    def npc_requires(self, h, how="kill or pickpocket"):
        if h.get("neutral"):
            return f"{how} {h['name']} (neutral/friendly: crime or story cost)"
        return f"{how} {h['name']}" + (" (boss)" if h.get("boss") else "")

    def do_npcs(self):
        holders = self.holders_per_table()
        neq = ninv = ntr = 0
        trade_chars = collections.defaultdict(set)
        for c in self.chars:
            lv = self.lvl(c["level"])
            if lv["act"] in ("system", "test"):
                continue
            h = self.holder_of(c)
            region = self.region_for(c["level"], c.get("Name"), c.get("position"))
            pos = c.get("position")
            lootable = c.get("IsLootable", True) is not False
            eq_loot = c.get("IsEquipmentLootable", True) is not False and lootable
            # equipment set
            es = self.equipment.get(c.get("Equipment") or "")
            if es:
                for grp in es["groups"]:
                    grp = [s for s in grp if s in self.stats]
                    for sid in grp:
                        t = self.items.type_of(sid)
                        kind = "npc_equipped" if t in ("Weapon", "Armor") else "npc_inventory"
                        notes = [f"equipment set {c['Equipment']}"]
                        if len(grp) > 1:
                            notes.append(f"one of {len(grp)} alternatives")
                        if not eq_loot:
                            notes.append("equipment not lootable (IsEquipmentLootable/IsLootable false)")
                        self.add(sid, self.items.template_for(sid), kind, level=c["level"], position=pos, holder=h,
                                 chance=1.0 / len(grp), steal=h["neutral"],
                                 requires=self.npc_requires(h, "kill" if kind == "npc_equipped" else
                                                           "kill or pickpocket"),
                                 notes="; ".join(notes), region=region, lootable=eq_loot,
                                 confidence="high" if len(grp) == 1 else "medium")
                        neq += 1
            # explicit ItemList (template / stats entries; instances handled with placements)
            for e in c.get("ItemList", []) or []:
                if e.get("Type") == 2:
                    continue
                sid, tm = self.itemlist_entry(e)
                if sid:
                    self.npc_item_record(c, sid, tm, e)
                    ninv += 1
            # treasures (death loot)
            for t in c.get("Treasures") or []:
                if t == "Empty":
                    continue
                if holders[t] > GENERIC_HOLDERS:
                    self.generic[t].append(("npc", c["level"], self.char_name(c)))
                    continue
                tl, tp, tr, tn = self.table_place(c, t, pos, region)
                ninv += self.emit_table(t, "npc_inventory", dict(
                    level=tl, position=tp, holder=h, steal=h["neutral"],
                    requires=self.npc_requires(h, "kill/loot"), region=tr, lootable=lootable,
                    notes="; ".join(x for x in ["death treasure", tn] if x), confidence="medium"))
            # trade treasures
            for t in c.get("TradeTreasures") or []:
                if t == "Empty":
                    continue
                tl, tp, tr, tn = self.table_place(c, t, pos, region)
                if self.is_trader_table(t, c):
                    trade_chars[t].add(c["MapKey"])
                    ntr += self.emit_table(t, "trader", dict(
                        level=tl, position=tp, holder=h, steal=False,
                        requires=f"buy from {h['name']}", region=tr,
                        notes="; ".join(x for x in ["trade stock (re-rolled on restock; chance per restock)", tn]
                                        if x), confidence="medium"))
                elif holders[t] > GENERIC_HOLDERS:
                    self.generic[t].append(("npc", c["level"], self.char_name(c)))
                else:
                    ninv += self.emit_table(t, "npc_inventory", dict(
                        level=tl, position=tp, holder=h, steal=h["neutral"],
                        requires=self.npc_requires(h), region=tr, lootable=lootable,
                        notes="; ".join(x for x in ["trade-treasure inventory (pickpocket / loot)", tn] if x),
                        confidence="medium"))
        # story-switched trade tables
        for gname, cmk, table, line in self.goal_trade:
            c = self.char_by_mk.get(cmk)
            if not c or table not in self.tables:
                continue
            h = self.holder_of(c)
            lev = self.code_level(table) or self.goal_level(gname) or c["level"]
            same = lev == c["level"]
            ntr += self.emit_table(table, "trader", dict(
                level=lev, position=c.get("position") if same else None, holder=h,
                requires=f"buy from {h['name']} after story goal {gname}",
                region=self.region_for(c["level"], c.get("Name"), c.get("position")) if same else
                self.code_region(table), notes=f"trade table set by {gname}", confidence="medium"))
        self.log(f"npc_equipped: {neq}, npc_inventory: {ninv}, trader: {ntr} records")

    def table_place(self, c, table, pos, region):
        """(level, position, region, note) for loot of NPC c from `table`. Global characters travel between acts:
        when the table's area code (LOW_..., WYR_...) points to another act, use that act's main level."""
        lev = c["level"]
        tlev = self.code_level(table)
        if c.get("scope") == "Globals" and tlev and self.lvl(tlev)["act"] != self.lvl(lev)["act"]:
            return tlev, None, name_region(table, None) or self.code_region(table),                 f"global character placed in {lev}; table name implies {tlev}"
        nr = name_region(table, None)
        if nr and ":" in nr and region and ":" not in region and nr.startswith(region):
            region = nr
        return lev, pos, region, None

    # ---------------------------------------------------------------- generic tables -> kind treasure
    def do_generic(self):
        n = 0
        for t, hs in sorted(self.generic.items()):
            lv = collections.Counter(h[1] for h in hs)
            kinds = collections.Counter(h[0] for h in hs)
            acts = sorted({str(self.lvl(l)["act"]) for l in lv})
            top = ", ".join(f"{l} x{k}" for l, k in lv.most_common(4))
            names = collections.Counter(h[2] for h in hs).most_common(3)
            notes = (f"generic table on {len(hs)} holders ({', '.join(f'{k} {v}' for k, v in kinds.items())}); "
                     f"acts {'/'.join(acts)}; levels {top}; e.g. {', '.join(x for x, _ in names)}")
            n += self.emit_table(t, "treasure", dict(level=lv.most_common(1)[0][0], notes=notes,
                                                    confidence="medium", holders=len(hs)))
        self.log(f"treasure (generic tables): {len(self.generic)} tables, {n} records")

    # ---------------------------------------------------------------- story rewards
    def do_rewards(self):
        n = 0
        seen = set()
        for tm, refs in self.goal_template_refs.items():
            strong = [r for r in refs if r[2]]
            if not strong:
                continue
            sid = self.items.stats_of(tm)
            if not sid or not self.items.relevant(sid, tm):
                continue
            goals = sorted({r[0] for r in strong})
            for g in goals:
                if (tm, g) in seen:
                    continue
                seen.add((tm, g))
                line, bare = next((r[1], r[3]) for r in strong if r[0] == g)
                conf = "medium" if re.search(r"TemplateAddTo\(|GiveItem|Reward", bare) else "low"
                level = self.goal_level(g)
                self.add(sid, tm, "reward", level=level, requires=f"story goal {g}", notes=line[:220],
                         confidence=conf, chance=None)
                n += 1
        for mk, refs in self.goal_instance_refs.items():
            strong = [r for r in refs if r[2] and re.search(r"ToInventory\(|GiveItem|Reward|Equip\(", r[3])]
            if not strong:
                continue
            p = self.place_by_mk[mk]
            sid = p.get("Stats") or (p.get("template") or {}).get("Stats")
            if not sid or not self.items.relevant(sid, p.get("TemplateName")):
                continue
            for g in sorted({r[0] for r in strong}):
                line = next(r[1] for r in strong if r[0] == g)
                self.add(sid, p.get("TemplateName"), "reward", level=p["level"], position=p.get("position"),
                         requires=f"story goal {g}", notes="placed instance handed over by script: " + line[:200],
                         confidence="medium", chance=None, instance=mk,
                         region=self.region_for(p["level"], p.get("Name"), p.get("position")))
                n += 1
        for g, table, line in self.goal_tables:
            n += self.emit_table(table, "reward", dict(level=self.goal_level(g), requires=f"story goal {g}",
                                                      notes=line[:160], confidence="low"))
        for g, res, inputs, line in self.forge:
            sid = self.items.stats_of(res)
            if sid:
                ins = [self.items.tmpl[i]["display"] or self.items.tmpl[i]["name"] for i in inputs]
                self.add(sid, res, "forge", level=self.goal_level(g),
                         requires="forge with " + " + ".join(ins) + " + Mithral Ore (Adamantine Forge, Grymforge)"
                         if "Adamantine" in line else "forge with " + " + ".join(ins),
                         notes=f"{g}: {line[:160]}", confidence="high", chance=1.0,
                         region="Grymforge - Adamantine Forge" if "Adamantine" in line else None)
                n += 1
        self.log(f"reward/forge: {n} records")

    def code_region(self, name):
        m = re.match(r"(?:Act\d[a-z]?_)?([A-Z]{3})_", name or "")
        return AREA_CODES.get(m.group(1)) if m else None

    def code_level(self, name):
        """Main level implied by an area-code prefix (LOW_..., WYR_..., Act3_LOW_...) or None."""
        m = re.match(r"(?:Act\d[a-z]?_)?([A-Z]{3})_", name or "")
        return self.CODE_MAIN.get(m.group(1)) if m else None

    CODE_MAIN = {"UND": "WLD_Main_A", "GOB": "WLD_Main_A", "DEN": "WLD_Main_A", "PLA": "WLD_Main_A",
                 "FOR": "WLD_Main_A", "CHA": "WLD_Main_A", "HAG": "WLD_Main_A", "CRA": "WLD_Main_A",
                 "CRE": "CRE_Main_A", "SHA": "SCL_Main_A", "MOO": "SCL_Main_A", "HAV": "SCL_Main_A",
                 "SCL": "SCL_Main_A", "TWN": "SCL_Main_A", "COL": "SCL_Main_A", "WYR": "BGO_Main_A",
                 "LOW": "CTY_Main_A", "END": "END_Main", "IRN": "IRN_Main_A", "TUT": "TUT_Avernus_C"}

    def do_quests(self):
        n = 0
        self.quest_tables = set()
        for q in self.quests:
            title = self.texts.get(q["title"]) or q["quest"]
            lev = self.code_level(q["quest"]) or self.code_level(q["objective"])
            req = f"quest '{title}' ({q['quest']}), step {q['step']}"
            dev = q["dev"] or None
            for t in q["tables"]:
                self.quest_tables.add(t)
                n += self.emit_table(t, "reward", dict(level=lev, requires=req, notes=dev, confidence="high",
                                                      quest=q["quest"]))
            for t in q["optional"]:
                self.quest_tables.add(t)
                n += self.emit_table(t, "reward", dict(level=lev, requires=req + " (choose one)", notes=dev,
                                                      confidence="high", quest=q["quest"]))
            for mk, is_root in q["templates"]:
                p = None if is_root else self.place_by_mk.get(mk)
                tm = p["TemplateName"] if p else mk
                sid = (p.get("Stats") or (p.get("template") or {}).get("Stats")) if p else self.items.stats_of(mk)
                if sid:
                    self.add(sid, tm, "reward", level=lev, requires=req, notes=dev, confidence="high",
                             chance=1.0, quest=q["quest"], instance=mk if p else None)
                    n += 1
        # treasure tables named after a quest objective / step (reward handed out by the quest system)
        used = self.used_tables()
        for t in self.tables:
            if t in used or t not in self.objectives:
                continue
            self.quest_tables.add(t)
            n += self.emit_table(t, "reward", dict(level=self.code_level(t), requires=f"quest objective {t}",
                                                  notes="treasure table named after a quest objective",
                                                  confidence="medium"))
        self.log(f"quest rewards: {len(self.quests)} quest steps, {n} records")

    def used_tables(self):
        used = set(self.holders_per_table())
        used |= {t for _, _, t, _ in self.goal_trade} | {t for _, t, _ in self.goal_tables}
        used |= getattr(self, "quest_tables", set())
        stack = list(used)
        while stack:
            t = self.tables.get(stack.pop())
            if not t:
                continue
            for sub in t["subtables"]:
                for cat, _ in sub["entries"]:
                    if cat.startswith("T_") and cat[2:] not in used:
                        used.add(cat[2:])
                        stack.append(cat[2:])
        return used

    def do_unreferenced(self):
        """Area-specific tables nobody references (as far as these files show): kind other, low confidence."""
        used = self.used_tables()
        n = 0
        for t in sorted(self.tables):
            if t in used or t == "Empty" or not self.code_level(t):
                continue
            n += self.emit_table(t, "other", dict(level=self.code_level(t), region=self.code_region(t),
                                                 notes="treasure table not referenced by any placement, NPC, goal "
                                                       "or quest found (likely dialog/script-given or cut)",
                                                 confidence="low"))
        self.log(f"unreferenced area tables: {n} records")

    def goal_level(self, gname):
        m = re.match(r"(?:Act\d[a-z]?_)?([A-Z]{3})_", gname)
        code = m.group(1) if m else None
        act_guess = {"UND": "WLD_Main_A", "GOB": "WLD_Main_A", "DEN": "WLD_Main_A", "PLA": "WLD_Main_A",
                     "FOR": "WLD_Main_A", "CHA": "WLD_Main_A", "HAG": "WLD_Main_A", "CRA": "WLD_Main_A",
                     "CRE": "CRE_Main_A", "SHA": "SCL_Main_A", "MOO": "SCL_Main_A", "HAV": "SCL_Main_A",
                     "SCL": "SCL_Main_A", "TWN": "SCL_Main_A", "COL": "SCL_Main_A", "WYR": "BGO_Main_A",
                     "LOW": "CTY_Main_A", "END": "END_Main", "IRN": "IRN_Main_A", "TUT": "TUT_Avernus_C"}
        if code in act_guess:
            return act_guess[code]
        m = re.match(r"Act(\d)", gname)
        if m:
            return {"1": "WLD_Main_A", "2": "SCL_Main_A", "3": "CTY_Main_A"}.get(m.group(1))
        return None

    # ---------------------------------------------------------------- combos + recipes
    def where_found(self, sid, limit=5):
        srcs = self.by_stats.get(sid, [])
        out = []
        for r in sorted(srcs, key=lambda r: (r["act"] not in (1, 2, 3) or "_CIN_" in str(r["level"]), r["kind"] in ("treasure", "other"), -(r["chance"] or 0)))[:limit]:
            s = r["kind"]
            if r.get("holder"):
                s += f" {r['holder']['name']}"
            if r.get("container"):
                s += f" in {r['container']['name']}"
            s += f" @ {r['level']}"
            if r.get("region"):
                s += f" ({r['region']})"
            if r.get("chance") is not None and r["chance"] < 1:
                s += f" p={r['chance']}"
            out.append(s)
        if len(srcs) > limit:
            out.append(f"... {len(srcs)} sources total")
        return out

    def category_members(self, cat):
        out = []
        for sid, e in self.stats.items():
            cats = ";".join([e.get("ComboCategory") or "", e.get("ObjectCategory") or ""]).split(";")
            if cat in cats:
                out.append(sid)
        return out

    def do_combos(self):
        self.by_stats = collections.defaultdict(list)
        for r in self.records:
            self.by_stats[r["stats_id"]].append(r)
        recipes = []
        ncombo = 0
        for name, c in self.combos.items():
            d = c["data"]
            inputs = []
            i = 1
            while f"Object {i}" in d:
                typ, obj, tr = d.get(f"Type {i}"), d.get(f"Object {i}"), d.get(f"Transform {i}")
                inp = {"type": typ, "id": obj, "transform": tr}
                if typ == "Object":
                    inp["name"] = self.items.name_of(obj)
                    inp["template"] = self.items.template_for(obj)
                    inp["found"] = self.where_found(obj)
                else:
                    mem = self.category_members(obj)
                    inp["members"] = len(mem)
                    inp["examples"] = mem[:8]
                inputs.append(inp)
                i += 1
            res = self.combo_results.get(name + "_1") or {"data": {}}
            results = []
            j = 1
            while f"Result {j}" in res["data"]:
                rid = res["data"][f"Result {j}"]
                results.append({"id": rid, "name": self.items.name_of(rid), "template": self.items.template_for(rid),
                                "amount": int(res["data"].get(f"ResultAmount {j}", "1") or 1)})
                j += 1
            kind = "dye" if any(t.get("transform") == "Dye" for t in inputs) else (
                "alchemy" if d.get("AlchemyCombinationType") or name.startswith("ALCH_") else "combine")
            rec = {"recipe": name, "kind": kind, "station": "inventory combine (ItemCombos.txt)",
                   "inputs": inputs, "results": results, "module": c["module"], "confidence": "high"}
            if d.get("Combine"):
                rec["combine_mode"] = d["Combine"]
            recipes.append(rec)
            for r in results:
                if r["id"] in self.stats and kind != "dye":
                    self.add(r["id"], r["template"], "combo", requires="combine: " + " + ".join(
                        (x.get("name") or x["id"]) for x in inputs), notes=f"ItemCombos {name}",
                        confidence="high", chance=1.0, recipe=name)
                    ncombo += 1
        # forge recipes from goals (Adamantine Forge and similar *Forge*_Result facts)
        for g, res, inputs, line in self.forge:
            sid = self.items.stats_of(res)
            ins = []
            for i in inputs:
                isid = self.items.stats_of(i)
                ins.append({"type": "Template", "id": i, "stats_id": isid, "name": self.items.tmpl[i]["display"],
                            "found": self.where_found(isid) if isid else []})
            if "Adamantine" in line:
                ore = [mk for mk, t in self.items.tmpl.items() if t["name"] and "Mithral" in t["name"]
                       and "Ore" in (t["name"] + (t["display"] or ""))]
                for mk in ore[:1]:
                    isid = self.items.stats_of(mk)
                    ins.append({"type": "Template", "id": mk, "stats_id": isid, "name": self.items.tmpl[mk]["display"],
                                "found": self.where_found(isid) if isid else []})
            recipes.append({"recipe": f"{g}:{self.items.tmpl[res]['name']}", "kind": "forge",
                            "station": "Adamantine Forge (Grymforge)" if "Adamantine" in line else g,
                            "inputs": ins, "results": [{"id": sid, "name": self.items.tmpl[res]["display"],
                                                        "template": res, "amount": 1}],
                            "module": self.goals[g][0], "confidence": "high", "source_line": line[:240]})
        # story multi-step chains seen in goals: masterwork / Sussur weapons
        for g, (mod, text) in self.goals.items():
            m = re.findall(r"DB_[A-Za-z_]*IncompleteMasterwork_WeaponTemplates\(\s*(?:\([A-Z]+\))?\s*([A-Za-z0-9_]+?)_("
                           + GUID + r")", text)
            for _, tm in m:
                if tm in self.items.tmpl:
                    sid = self.items.stats_of(tm)
                    recipes.append({"recipe": f"{g}:{self.items.tmpl[tm]['name']}", "kind": "forge",
                                    "station": "Blighted Village forge (Incomplete Masterwork)",
                                    "inputs": [{"type": "Object", "id": "QUEST_FOR_SussurBark",
                                                "name": "Sussur Bark",
                                                "found": self.where_found("QUEST_FOR_SussurBark")},
                                               {"type": "Category", "id": "Masterwork weapon (ItemCombos "
                                                "FOR_IncompleteMasterwork_*)"}],
                                    "results": [{"id": sid, "name": self.items.tmpl[tm]["display"], "template": tm,
                                                 "amount": 1}],
                                    "module": mod, "confidence": "medium",
                                    "notes": "Sussur Bark + masterwork weapon combined (ItemCombos) then forged at "
                                             "the Blighted Village forge (Act1_FOR_IncompleteMasterwork goal)"})
                    self.add(sid, tm, "forge", level="WLD_Main_A", region="Blighted Village forge",
                             requires="Sussur Bark + masterwork weapon, forge in the Blighted Village "
                                      "(Incomplete Masterwork)", notes=g, confidence="medium", chance=1.0)
        self.recipes = recipes
        self.log(f"recipes: {len(recipes)} ({ncombo} combo source records)")

    # ---------------------------------------------------------------- output
    # ---------------------------------------------------------------- positions for records without one
    GUID_RX = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
    PAIR_RX = re.compile(r"(\w+)\(\s*(?:\(\w+\))?S_\w+?_([0-9a-f]{8}-[0-9a-f-]{27})\s*,\s*(?:\(\w+\))?"
                         r"S_\w+?_([0-9a-f]{8}-[0-9a-f-]{27})")

    def fill_positions(self):
        """Records with a holder / GUID but no position (global traders moved by script between acts, script rewards
        handed over by an NPC, forge results) get the position of where the game puts that NPC / object in the
        record's act:
          - goal facts pairing the NPC with a placed point / item / trigger (TeleportTo(Dammon, S_LOW_WeaponsmithPos),
            DB_..._Move(npc, point) ...), TeleportTo preferred;
          - a GUID in the record's notes (TemplateAddTo(item, S_HAG_Hag_<guid>), DB_UND_AdamantineForge_Result(...,
            (TRIGGER)S_..._<guid>)) that resolves to a placed character, item or trigger;
          - the NPC's own level placement when it is in the same act.
        The filled record gets position_from = how the position was found."""
        holders = {r["holder"]["MapKey"] for r in self.records if not r.get("position") and r.get("holder")
                   and r["holder"].get("MapKey")}
        holders |= {g for r in self.records if not r.get("position")
                    for g in self.GUID_RX.findall((r.get("notes") or "") + " " + (r.get("requires") or ""))
                    if g in self.char_by_mk}
        pairs = collections.defaultdict(list)          # npc guid -> [(rank, how, target guid or name)]
        by_name = {}
        for c in self.chars:
            if c.get("Name") and c.get("position"):
                by_name.setdefault(c["Name"], c)
        for name, (_mod, txt) in self.goals.items():
            for line in txt.splitlines():
                gs = self.GUID_RX.findall(line)
                hs = [g for g in gs if g in holders]
                if not hs:
                    continue
                fn = (re.match(r"\s*(?:NOT\s+)?(\w+)", line) or [None, ""])[1]
                for h in hs:
                    for t in gs:
                        if t == h:
                            continue
                        tn = (re.search(r"(S_\w+?)_" + t, line) or [None, ""])[1]
                        # TeleportTo first, then a "...Default..." point, other points / positions, DB facts, checks
                        rank = 0 if "Teleport" in fn else 0.5 if "Default" in tn else \
                            1 if re.search(r"Pos|Point|Spot|Position", tn + fn) else \
                            3 if re.match(r"QRY_|Is|Entered|Trigger|Left|Char", fn) else 2
                        pairs[h].append((rank, "goal " + fn, t))
                    for q in re.findall(r'"(\w+)"', line):       # DB_GLO_LevelTraveler(npc, level, "<placed copy>")
                        if q in by_name and "LevelTraveler" in fn:
                            pairs[h].append((1, "goal " + fn, by_name[q]["MapKey"]))
        # lines that name an item template without a placed position (script rewards, forge results): the other
        # placed GUIDs on the same line (the NPC handing it over, the forge trigger)
        tmpl_lines = collections.defaultdict(list)
        need_t = {r.get("template") for r in self.records if not r.get("position") and not r.get("holder")
                  and r.get("template")}
        for name, (_mod, txt) in self.goals.items():
            for line in txt.splitlines():
                for g in self.GUID_RX.findall(line):
                    if g in need_t:
                        tmpl_lines[g] += [t for t in self.GUID_RX.findall(line) if t != g]
        wanted = {t for lst in pairs.values() for _r, _f, t in lst} | {t for v in tmpl_lines.values() for t in v}
        for r in self.records:
            if not r.get("position"):
                wanted |= set(self.GUID_RX.findall((r.get("notes") or "") + " " + (r.get("requires") or "")))
        triggers = load_triggers(wanted)

        def where(guid):
            pl = self.place_by_mk.get(guid)
            if pl and pl.get("position"):
                return pl["level"], pl["position"]
            ch = self.char_by_mk.get(guid)
            if ch and ch.get("position"):
                return ch["level"], ch["position"]
            tr = triggers.get(guid)
            if tr and tr.get("pos"):
                return tr["level"], list(tr["pos"])
            return None, None

        n = collections.Counter()
        for r in self.records:
            if r.get("position"):
                continue
            act = r.get("act")
            cands = []
            h = (r.get("holder") or {}).get("MapKey")
            if h:
                lv, pos = where(h)
                if pos and self.lvl(lv)["act"] == act:
                    cands.append((-1, "holder placement", lv, pos))
                for rank, how, t in pairs.get(h, []):
                    lv, pos = where(t)
                    if pos and self.lvl(lv)["act"] == act:
                        cands.append((rank, how, lv, pos))
            extra = tmpl_lines.get(r.get("template"), []) if not h else []
            for g in self.GUID_RX.findall((r.get("notes") or "") + " " + (r.get("requires") or "")) + extra:
                if g == r.get("template"):
                    continue
                lv, pos = where(g)
                found = bool(pos and (act is None or self.lvl(lv)["act"] == act))
                if found:
                    cands.append((3, "guid in notes", lv, pos))
                if self.char_by_mk.get(g):
                    for rank, how, t in pairs.get(g, []):
                        lv2, pos2 = where(t)
                        if pos2 and self.lvl(lv2)["act"] == act:
                            cands.append((4 + rank, how + " (npc in notes)", lv2, pos2))
                            found = True
                    if found and not h:
                        r["holder"] = {"name": self.char_name(self.char_by_mk[g]), "MapKey": g}
            # weak candidates (checks such as QRY_IsInRange, region triggers) must lie in the record's region
            reg0 = (r.get("region") or "").split(":")[0].split("(")[0].strip()
            # only world positions (sub-levels use local coordinates); weak candidates must lie in the record's region
            cands = [c for c in cands if c[2] in MAIN_LEVELS and
                     (c[0] <= 0 or not reg0 or reg0 in (self.region_for(c[2], "", c[3]) or ""))]
            if cands:
                cands.sort(key=lambda c: c[0])
                _k, how, lv, pos = cands[0]
                r["position"] = [round(float(x), 3) for x in pos]
                r["position_from"] = how
                if not r.get("level"):
                    r["level"] = lv
                n[how.split()[0]] += 1
        self.log(f"positions filled: {dict(n)}")

    def write(self):
        os.makedirs(self.out_dir, exist_ok=True)
        keys = ["stats_id", "template", "kind", "level", "act", "region", "position", "holder", "container",
                "treasure_table", "chance", "steal", "requires", "notes", "confidence"]
        recs = []
        for r in self.records:
            o = {k: r.get(k) for k in keys}
            for k, v in r.items():
                if k not in o and v is not None:
                    o[k] = v
            if o["template"] is None:
                o["template"] = self.items.template_for(o["stats_id"])
            recs.append(o)
        recs.sort(key=lambda r: (r["stats_id"], r["kind"], str(r["level"])))
        with open(os.path.join(self.out_dir, "sources.jsonl"), "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(os.path.join(self.out_dir, "recipes.jsonl"), "w", encoding="utf-8") as f:
            for r in self.recipes:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        for p in self.places:
            self.lvl(p["level"])
        for c in self.chars:
            self.lvl(c["level"])
        with open(os.path.join(self.out_dir, "levels.json"), "w", encoding="utf-8") as f:
            json.dump(dict(sorted(self.levels.items())), f, ensure_ascii=False, indent=1)
        cnt = collections.Counter(r["kind"] for r in recs)
        conf = collections.Counter((r["kind"], r["confidence"]) for r in recs)
        self.log(f"wrote {len(recs)} source records {dict(cnt)}; {len(self.recipes)} recipes; "
                 f"{len(self.levels)} levels")
        self.log("confidence: " + ", ".join(f"{k[0]}/{k[1]}={v}" for k, v in sorted(conf.items())))

    def mark_recipe_inputs(self):
        for c in self.combos.values():
            d = c["data"]
            for k, v in d.items():
                if k.startswith("Object ") and d.get("Type " + k.split()[1]) == "Object":
                    self.items.extra.add(v)
        for g, res, inputs, line in self.forge:
            for i in inputs:
                if self.items.stats_of(i):
                    self.items.extra.add(self.items.stats_of(i))
        for mk, t in self.items.tmpl.items():
            if t["name"] and "Mithral" in t["name"] and t["stats"]:
                self.items.extra.add(t["stats"])

    def run(self):
        self.build_region_index()
        self.scan_goals()
        self.mark_recipe_inputs()
        self.build_ownership()
        self.do_world_and_containers()
        self.do_npcs()
        self.do_generic()
        self.do_rewards()
        self.do_quests()
        self.do_unreferenced()
        self.do_combos()
        self.fill_positions()
        self.write()


if __name__ == "__main__":
    out = OUT_DEFAULT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    Builder(out).run()
