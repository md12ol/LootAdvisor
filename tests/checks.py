"""Loot Advisor regression checks. Each check reads the REAL pipeline outputs (data/scores/*.json,
data/scores/lua/LootData.lua) and/or runs the mod's own Lua (LootAdvisor/Mods/LootAdvisor, read-only through lupa), and
compares them with facts taken from independent sources (game files via tests/gamedata.py, Builds.lua parsed here).
A check that finds nothing to check FAILS (no empty passes).

Every check is a function check_x(env) -> list of failure strings; run.py adds the case counts.
"""
import glob
import json
import os
import re
import shutil
import tempfile

import gamedata

ACTS = (1, 2, 3)


class Env:
    """Where to read from. root = a LootAdvisor folder (the real one, or a scratch copy for --mutate)."""

    def __init__(self, root, mods_lua, builds_lua, lua_patches=None, bp_module=None):
        self.root = root
        self.mods_lua = mods_lua
        self.builds_lua = builds_lua
        self.lua_patches = lua_patches or {}   # file name -> [(old, new)] source replacements (mutations / fixes)
        self.bp_module = bp_module             # build_profiles module to test (default: root/tools)
        self._lua = None
        self.counts = {}

    # ---------------------------------------------------------------- outputs
    def scores(self):
        out = {}
        for p in sorted(glob.glob(os.path.join(self.root, "data", "scores", "*.json"))):
            name = os.path.basename(p)[:-5]
            if name.startswith("_") or name in ("owners", "name_matches"):
                continue
            with open(p, encoding="utf-8") as f:
                out[name] = json.load(f)
        return out

    def items_all(self):
        out = {}
        for p in glob.glob(os.path.join(self.root, "data", "items_all", "*.jsonl")):
            if os.path.basename(p) in ("sources.jsonl", "recipes.jsonl"):
                continue
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        if "stats_id" in r:
                            out[r["stats_id"]] = r
        return out

    def build_profiles(self):
        if self.bp_module is not None:
            return self.bp_module
        import importlib.util
        import sys
        tools = os.path.join(self.root, "tools")
        spec = importlib.util.spec_from_file_location("bp_under_test_" + str(abs(hash(tools))),
                                                      os.path.join(tools, "build_profiles.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, tools)
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(tools)
        self.bp_module = mod
        return mod

    # ---------------------------------------------------------------- the mod's Lua (read-only) + LootData output
    def lua(self):
        if self._lua is None:
            from lupa import LuaRuntime
            L = LuaRuntime(unpack_returned_tuples=True)
            L.execute("""
              Ext = { Utils = { MonotonicTime = function() return 0 end }, IO = {}, Json = {}, Loca = {},
                      Entity = {}, Net = {} }
              setmetatable(Ext.IO, { __index = function() return function() return nil end end })
            """)
            files = [os.path.join(self.mods_lua, "Shared", "Common.lua"),
                     os.path.join(self.root, "data", "scores", "lua", "LootData.lua"),
                     os.path.join(self.mods_lua, "Shared", "ModData.lua"),
                     os.path.join(self.mods_lua, "Shared", "Logic.lua"),
                     os.path.join(self.mods_lua, "Client", "Tooltip.lua")]
            for fp in files:
                with open(fp, encoding="utf-8") as f:
                    src = f.read()
                for old, new in self.lua_patches.get(os.path.basename(fp), []):
                    if old not in src:
                        raise RuntimeError(f"lua patch target not found in {os.path.basename(fp)}: {old[:60]!r}")
                    src = src.replace(old, new)
                L.execute(src)
            self._lua = L
        return self._lua


def lua_list(t):
    if t is None:
        return []
    return [t[i] for i in range(1, len(t) + 1)]


def lua_dict(t):
    return {} if t is None else dict(t.items())


def ctx_for(L, char, b):
    """Selection context whose live classes are exactly the build's classes / subclasses."""
    cl, sc = lua_dict(b.cl), lua_dict(b.sc)
    classes = [{"name": c, "sub": sc.get(c), "level": lv} for c, lv in cl.items()]
    return L.table_from({"name": char, "classes": classes}, recursive=True)


def state_for(L, chars, act, durge, comp_override=None):
    comp = {c: {"team": True, "party": True, "dead": False} for c in chars}
    comp.update(comp_override or {})
    return L.table_from({"act": act, "region": "", "durge": durge, "paths": {}, "comp": comp, "owned": {},
                         "markerPos": {}}, recursive=True)


# ==================================================================== 1. no heavy body armour for raging builds
def check_no_heavy_armour_raging(env):
    gd = gamedata.load()
    if not gd.rage_classes:
        return ["game data: no class with a Rage resource found (Progressions.lsx) - cannot check"]
    fails, n_builds, n_slots = [], 0, 0

    def heavy(sid):
        return sid and gd.armour_group(sid) == "HeavyArmor" and gd.slot(sid) == "Breast"

    # JSON outputs: every raging build, every act, the best/runner/top table and every set's chest (+ alternatives)
    for char, d in env.scores().items():
        for bid, b in d["builds"].items():
            if not set(b["classes"]) & gd.rage_classes:
                continue
            n_builds += 1
            for act, slots in (b.get("best") or {}).items():
                br = slots.get("Breast") or {}
                for sid in [br.get("best"), br.get("runner")] + [t[0] for t in br.get("top") or []]:
                    if sid:
                        n_slots += 1
                        if heavy(sid):
                            fails.append(f"{char}.{bid} act {act} best/runner/top Breast = {sid} (heavy)")
            for act, sts in (b.get("sets") or {}).items():
                for st in sts:
                    it = (st.get("items") or {}).get("Breast")
                    if not it:
                        continue
                    for key in ("sid", "fallback", "owned_alt", "cond_alt"):
                        sid = it.get(key)
                        if isinstance(sid, dict):
                            sid = sid.get("sid")
                        if sid:
                            n_slots += 1
                            if heavy(sid):
                                fails.append(f"{char}.{bid} act {act} set '{st['name']}' Breast {key} = {sid}")
    # LootData.lua (what the mod reads): best pairs, pb, every set's it / fb / pa / oa / ca
    L = env.lua()
    items = L.globals().LA.Data["items"]
    for char, cd in lua_dict(L.globals().LA.Data.chars).items():
        for b in lua_list(cd.b):
            if not set(lua_dict(b.cl)) & gd.rage_classes:
                continue
            n_builds += 1
            for act in ACTS:
                a = b.a[act] if b.a is not None else None
                if a is None:
                    continue
                idxs = []
                pair = a.best["Breast"] if a.best is not None else None
                idxs += lua_list(pair) if pair is not None else []
                if a.pb is not None and a.pb["Breast"]:
                    idxs.append(a.pb["Breast"])
                for st in lua_list(a.sets):
                    for fld in ("it", "fb", "pa", "oa", "ca"):
                        t = st[fld]
                        if t is not None and t["Breast"]:
                            idxs.append(t["Breast"])
                for i in idxs:
                    if not i:
                        continue
                    n_slots += 1
                    sid = items[i].id
                    if heavy(sid):
                        fails.append(f"LootData {char}.{b.id} act {act} Breast = {sid} (heavy)")
    env.counts["raging builds"] = n_builds
    env.counts["raging chest slots"] = n_slots
    if n_builds == 0 or n_slots == 0:
        fails.append(f"nothing checked: {n_builds} raging builds, {n_slots} chest slots")
    return fails


# ==================================================================== 2. every Builds.lua build has a profile
def check_profiles_cover_builds_lua(env):
    fails = []
    builds, origins = gamedata.builds_lua(env.builds_lua)
    ids = [b[0] for b in builds]
    if not ids:
        return ["no builds read from Builds.lua"]
    BP = env.build_profiles()
    missing = [i for i in ids if i not in BP.BUILDS]
    fails += [f"Builds.lua build without a profile: {i}" for i in missing]
    # each origin character the pipeline covers gets every BA.Origins build of its own in the outputs
    scores = env.scores()
    L = env.lua()
    chars = lua_dict(L.globals().LA.Data.chars)
    n_origin = 0
    for char, blist in origins.items():
        if char not in scores:
            continue
        n_origin += 1
        out_json = set(scores[char]["builds"])
        out_lua = {b.id for b in lua_list(chars[char].b)} if char in chars else set()
        for bid in blist:
            if bid not in out_json:
                fails.append(f"{char}: BA.Origins build {bid} missing in data/scores/{char}.json")
            if bid not in out_lua:
                fails.append(f"{char}: BA.Origins build {bid} missing in LootData.lua")
    if n_origin == 0:
        fails.append("no BA.Origins character found in the outputs")
    # the sync must fail loudly on an unknown build: a scratch copy of Builds.lua with one extra build
    src = open(env.builds_lua, encoding="utf-8").read()
    fake = "zz_regression_unknown_build"
    block = ('  {\n    id = "%s", name = "Regression probe", tier = "C",\n    classes = { "Fighter" }, start = "Fighter",\n'
             '    base = { STR = 15, DEX = 14, CON = 15, INT = 8, WIS = 10, CHA = 8 }, plus2 = "STR", plus1 = "CON",\n'
             '    levels = {\n      L("Fighter", { "Fighting Style: Defence" }, { "Defence" }),\n    },\n    gear = "",\n  },\n'
             % fake)
    i = src.index("BA.Builds = {") + len("BA.Builds = {\n")
    tmpd = tempfile.mkdtemp(prefix="la_probe_")
    probe = os.path.join(tmpd, "Builds.lua")
    with open(probe, "w", encoding="utf-8") as f:
        f.write(src[:i] + block + src[i:])
    try:
        BP.sync_with_builds_lua(probe)
        fails.append("sync_with_builds_lua accepted an unknown Builds.lua build (must raise)")
    except Exception as e:  # noqa: BLE001 - any loud failure is fine, it must name the build
        if fake not in str(e):
            fails.append(f"sync_with_builds_lua raised but did not name the unknown build: {e}")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    env.counts["Builds.lua builds"] = len(ids)
    env.counts["origins checked"] = n_origin
    return fails


# ==================================================================== 3. class proficiencies (Cleric Morningstar/Flail)
def check_class_proficiencies(env):
    gd = gamedata.load()
    builds, _o = gamedata.builds_lua(env.builds_lua)
    start_of = {b[0]: b[1] for b in builds}
    items = env.items_all()
    fails, n_builds, n_items, n_cleric, n_mf = [], 0, 0, 0, 0
    for char, d in env.scores().items():
        for bid, b in d["builds"].items():
            classes = b["classes"]
            start = start_of.get(bid) or next(iter(classes))
            exp = gd.expected_profs(classes, start, b.get("subclasses") or {})
            have = set(b.get("proficiencies") or [])
            n_builds += 1
            lacking = sorted(exp - have)
            if lacking:
                fails.append(f"{char}.{bid}: game grants {lacking} but the build's proficiencies lack them")
            if start == "Cleric":
                n_cleric += 1
            # no item may be marked "no proficiency" / "not proficient" for a proficiency the game grants
            for sid, it in (b.get("items") or {}).items():
                req = set(((items.get(sid) or {}).get("requirements") or {}).get("proficiency") or [])
                if not req:
                    continue
                n_items += 1
                if start == "Cleric" and req & {"Morningstars", "Flails"}:
                    n_mf += 1
                if req & exp and "proficien" in (it.get("why_not") or ""):
                    fails.append(f"{char}.{bid}: {it.get('name') or sid} marked '{it['why_not']}' although the game "
                                 f"grants {sorted(req & exp)}")
    env.counts["builds"] = n_builds
    env.counts["items with a proficiency requirement"] = n_items
    env.counts["Cleric-start builds"] = n_cleric
    env.counts["Morningstar/Flail items on Cleric-start builds"] = n_mf
    if n_builds == 0 or n_items == 0 or n_cleric == 0 or n_mf == 0:
        fails.append(f"nothing (or no Cleric case) checked: builds {n_builds}, items {n_items}, Cleric-start "
                     f"{n_cleric}, Morningstar/Flail items {n_mf}")
    return fails


# ==================================================================== 4. subclass names as the game shows them
def check_subclass_names(env):
    gd = gamedata.load()
    fails, n = [], 0

    def ok(cls, name):
        return name in gd.subclass_names.get(cls, {})
    for char, d in env.scores().items():
        for bid, b in d["builds"].items():
            for cls, name in (b.get("subclasses") or {}).items():
                n += 1
                if not ok(cls, name):
                    fails.append(f"{char}.{bid} json: {cls} subclass {name!r} is not a game name "
                                 f"({sorted(gd.subclass_names.get(cls, {}))})")
    L = env.lua()
    for char, cd in lua_dict(L.globals().LA.Data.chars).items():
        for b in lua_list(cd.b):
            for cls, name in lua_dict(b.sc).items():
                n += 1
                if not ok(cls, name):
                    fails.append(f"LootData {char}.{b.id}: {cls} subclass {name!r} is not a game name")
    env.counts["subclass entries"] = n
    if n == 0:
        fails.append("no subclass entries found")
    return fails


# ==================================================================== 5. list-only items: no frame, no tooltip text
def check_list_only_no_frame_no_text(env):
    L = env.lua()
    G = L.globals()
    chars = lua_dict(G.LA.Data.chars)
    fails, n_runs, n_list, n_rows = [], 0, 0, 0
    for char, cd in chars.items():
        for b in lua_list(cd.b):
            for act in ACTS:
                if b.a is None or b.a[act] is None:
                    continue
                for durge in (False, True):
                    res = G.LA.Logic.Recommend(char, ctx_for(L, char, b), state_for(L, chars, act, durge), b.id, None)
                    if res is None or res.rows is None:
                        continue
                    n_runs += 1
                    G.LA.Tip.Apply(res)
                    advice = G.LA.Tip.advice
                    frames = res.frames
                    by_id = {}
                    for r in lua_list(res.rows):
                        n_rows += 1
                        by_id.setdefault(r.id, []).append(r)
                    for sid, rows in by_id.items():
                        if all(r.mode == "l" and r.s != "owned" for r in rows):
                            n_list += 1
                            if frames[sid]:
                                fails.append(f"{char}.{b.id} act {act}: list-only {sid} gets a frame")
                            if advice[sid] is not None:
                                fails.append(f"{char}.{b.id} act {act}: list-only {sid} gets tooltip text")
    env.counts["Recommend runs"] = n_runs
    env.counts["rows"] = n_rows
    env.counts["list-only items checked"] = n_list
    if n_runs == 0 or n_list == 0:
        fails.append(f"nothing checked: {n_runs} runs, {n_list} list-only items")
    return sorted(set(fails))


# ============================================================ 6. contested owners: chosen among the ACTIVE party only
def check_owner_active_party_only(env):
    """Owner `o` of a unique item is in camp (team, not in the active party): the viewer must NOT see "better on
    <owner>". Positive control: the same owner in the active party -> "better on <owner>" must appear."""
    L = env.lua()
    G = L.globals()
    chars = lua_dict(G.LA.Data.chars)
    items = G.LA.Data["items"]
    # where each item index is recommended: (char, build, act)
    where = {}
    for char, cd in chars.items():
        for b in lua_list(cd.b):
            for act in ACTS:
                a = b.a[act] if b.a is not None else None
                if a is None or a.best is None:
                    continue
                for slot, pair in lua_dict(a.best).items():
                    for i in lua_list(pair):
                        if i:
                            where.setdefault(i, []).append((char, b, act))
    fails, n_cases, n_control = [], 0, 0
    for i in range(1, len(items) + 1):
        it = items[i]
        owners = lua_list(it.o)
        if not owners or lua_list(it.ot) or owners[0] == "darkurge":
            continue
        owner = owners[0]
        viewer = next(((c, b, act) for c, b, act in where.get(i, []) if c not in owners), None)
        if not viewer:
            continue
        c, b, act = viewer
        durge = c == "darkurge"

        def rows_for(comp):
            res = G.LA.Logic.Recommend(c, ctx_for(L, c, b), state_for(L, chars, act, durge, comp), b.id, None)
            return [r for r in lua_list(res.rows) if r.i == i] if res is not None and res.rows is not None else []
        camp = rows_for({owner: {"team": True, "party": False, "dead": False}})
        if not camp:
            continue
        n_cases += 1
        if any(r.s == "better" and r.better == owner for r in camp):
            fails.append(f"{it.id}: {owner} is in camp, yet {c} ({b.id}, act {act}) sees 'better on {owner}'")
        party = rows_for({owner: {"team": True, "party": True, "dead": False}})
        if any(r.s == "better" and r.better == owner for r in party):
            n_control += 1
    env.counts["contested items checked"] = n_cases
    env.counts["positive controls (owner in party -> better on X)"] = n_control
    if n_cases == 0 or n_control == 0:
        fails.append(f"nothing checked: {n_cases} cases, {n_control} positive controls")
    return fails


# ==================================================================== 7-9. Sets page sheet + set validator
def tool_module(env, name):
    """tools/<name>.py of the root under test, imported fresh (a scratch copy may carry a mutation)."""
    cache = env.__dict__.setdefault("_tool_modules", {})
    if name not in cache:
        import importlib.util
        import sys
        tools = os.path.join(env.root, "tools")
        spec = importlib.util.spec_from_file_location(f"{name}_under_test_{abs(hash(tools))}",
                                                      os.path.join(tools, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, tools)
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(tools)
        cache[name] = mod
    return cache[name]


def sheet_data(env):
    """(build_sets_artifact module, its Data) for the root under test."""
    B = tool_module(env, "build_sets_artifact")
    if "_sheet_D" not in env.__dict__:
        B.BUILDS_LUA = env.builds_lua
        env._sheet_D = B.Data()
    return B, env._sheet_D


def set_sheets(B, D, char, bk, b, BI, level=12):
    """-> [(set label, sheet)] for every set of a build (same inputs as the page generator)."""
    out = []
    for act, sets in (b.get("sets") or {}).items():
        for i, s in enumerate(sets):
            its = {k: v for k, v in (s.get("items") or {}).items() if v and v.get("sid")}
            IB = {v["sid"]: B.item_boosts(D, v["sid"]) for v in its.values()}
            out.append((f"{char}.{bk} act {act} set {i + 1}", B.compute_sheet(D, BI, its, IB, level)))
    return out


def check_sheet_subclass_features(env):
    """Sets page sheet: every build's subclasses carry the game's names, and the subclass features the sheet models
    switch on for them (Hexblade: Hex Warrior attacks with CHA; Draconic Bloodline: Draconic Resilience HP;
    College of Swords / Bladesinging 6: Extra Attack; Eldritch Knight / Arcane Trickster 3: INT spellcasting)."""
    gd = gamedata.load()
    B, D = sheet_data(env)
    fails, n_subs, n_feat = [], 0, 0
    for cls, key in getattr(B, "SHEET_SUB", {}).values():
        if key not in gd.subclass_names.get(cls, {}).values():
            fails.append(f"sheet rule names {cls} subclass {key!r}, not a game subclass of {cls}")
    with open(os.path.join(env.root, "tools", "sets_artifact", "app.js"), encoding="utf-8") as f:
        for m in re.finditer(r'subCls\.(\w+)\s*===\s*"([^"]+)"', f.read()):
            fails.append(f"app.js compares the {m.group(1)} subclass with the literal {m.group(2)!r} "
                         "(use RULES.subs: the game's internal subclass names)")
    for char, d in env.scores().items():
        for bk, b in d["builds"].items():
            BI = B.build_input(D, char, d.get("race"), bk, b)
            internal = {}
            for s_ in BI["subs"]:
                n_subs += 1
                game = gd.subclass_names.get(s_["cls"], {})
                if s_["n"] not in game:
                    fails.append(f"{char}.{bk}: sheet subclass {s_['cls']} {s_['n']!r} is not a game name "
                                 f"({sorted(game)})")
                else:
                    internal[s_["cls"]] = game[s_["n"]]
            lv = dict(b.get("classes") or {})
            want = {"hexblade": internal.get("Warlock") == "Hexblade",
                    "draconic": internal.get("Sorcerer") == "DraconicBloodline",
                    "extra_attack": (internal.get("Bard") == "SwordsCollege" and lv.get("Bard", 0) >= 6) or
                                    (internal.get("Wizard") == "BladesingingSchool" and lv.get("Wizard", 0) >= 6),
                    "int_caster": (internal.get("Fighter") == "EldritchKnight" and lv.get("Fighter", 0) >= 3) or
                                  (internal.get("Rogue") == "ArcaneTrickster" and lv.get("Rogue", 0) >= 3)}
            if not any(want.values()):
                continue
            for label, sh in set_sheets(B, D, char, bk, b, BI):
                n_feat += 1
                if want["draconic"] and not any("Draconic Resilience" in x for x in sh["F"]["hp"]):
                    fails.append(f"{label}: Draconic Bloodline but no Draconic Resilience in the HP ({sh['F']['hp']})")
                if want["extra_attack"] and sh["nAtt"] < 2:
                    fails.append(f"{label}: subclass Extra Attack missing ({sh['nAttF']})")
                if want["int_caster"] and not (sh.get("spell") and "INT" in json.dumps(sh["spell"])):
                    fails.append(f"{label}: INT spellcasting subclass but no INT spell row")
                if want["hexblade"]:
                    M = sh["mods"]
                    for a in sh["attacks"]:
                        rec = D.items.get(a["sid"]) or {}
                        props = (rec.get("weapon") or {}).get("properties") or []
                        own = M["DEX"] if a["ranged"] else max(M["STR"], M["DEX"]) if "Finesse" in props else M["STR"]
                        proficient = any(x.startswith("proficiency") for x in a["hitf"])
                        if proficient and M["CHA"] > own and not a["hitf"][0].startswith("CHA"):
                            fails.append(f"{label}: Hexblade, CHA {M['CHA']:+d} > {own:+d}, yet {a['n']} attacks "
                                         f"with {a['hitf'][0]!r} (Hex Warrior)")
    env.counts["build subclasses"] = n_subs
    env.counts["sets with a modelled subclass feature"] = n_feat
    if n_subs == 0 or n_feat == 0:
        fails.append(f"nothing checked: {n_subs} subclasses, {n_feat} sets with a modelled subclass feature")
    return fails


def _weapon_riders(gd, rec):
    """The weapon's own unconditional damage riders [(amount, type)] from the game stats: WeaponDamage(...) in the
    weapon's boosts and in its root templates' statuses (Balduran's Giantslayer: StrengthModifier Slashing)."""
    st = gd.stats.get(rec["stats_id"]) or {}
    texts = [st.get("DefaultBoosts") or "", st.get("Boosts") or ""]
    for status in ((rec.get("boosts_raw") or {}).get("TemplateStatusList") or "").split(";"):
        texts.append((gd.stats.get(status.strip()) or {}).get("Boosts") or "")
    out = []
    for t in texts:
        for part in t.split(";"):
            m = re.fullmatch(r"\s*WeaponDamage\(\s*([^,()]+?)\s*,\s*(\w+)[^()]*\)\s*", part)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def check_sheet_weapon_riders(env):
    """Sets page sheet: each weapon's own damage riders count exactly once in its attack row - dice riders and
    stat / number riders (Balduran's Giantslayer adds the Strength modifier). Every weapon with a rider, held alone
    by the first build."""
    gd = gamedata.load()
    B, D = sheet_data(env)
    char, d = next(iter(env.scores().items()))
    bk, b = next(iter(d["builds"].items()))
    BI = B.build_input(D, char, d.get("race"), bk, b)
    abil = {"Strength": "STR", "Dexterity": "DEX", "Constitution": "CON", "Intelligence": "INT", "Wisdom": "WIS",
            "Charisma": "CHA"}
    fails, n_w, n_stat = [], 0, 0
    for sid, rec in sorted(D.items.items()):
        if not rec.get("weapon"):
            continue
        riders = _weapon_riders(gd, rec)
        if not riders:
            continue
        n_w += 1
        slot = "Ranged" if rec.get("slot") == "Ranged Main Weapon" else "MainHand"
        sh = B.compute_sheet(D, BI, {slot: {"sid": sid}}, {sid: B.item_boosts(D, sid)}, 12)
        row = next((a for a in sh["attacks"] if a["slot"] == slot), None)
        if not row:
            fails.append(f"{sid}: no attack row")
            continue
        for amount, typ in riders:
            if re.fullmatch(r"\d+d\d+", amount):
                hits = [x for x in row["dmgf"] if x.startswith(f"{amount} {typ} ")]
                what = f"{amount} {typ}"
            else:
                m = re.fullmatch(r"(\w+?)Modifier", amount)
                n = sh["mods"][abil[m.group(1)]] if m and m.group(1) in abil else \
                    int(amount) if re.fullmatch(r"-?\d+", amount) else None
                if n is None:
                    continue
                n_stat += 1
                if n == 0:
                    continue
                hits = [x for x in row["dmgf"] if x.startswith("%+d %s" % (n, typ))]
                what = "%+d %s (%s)" % (n, typ, amount)
            if len(hits) != 1:
                fails.append(f"{rec.get('name') or sid}: rider {what} counted {len(hits)} times ({row['dmgf']})")
    env.counts["weapons with riders"] = n_w
    env.counts["stat / number riders"] = n_stat
    if n_w == 0 or n_stat == 0:
        fails.append(f"nothing checked: {n_w} weapons with riders, {n_stat} stat / number riders")
    return fails


def check_ranged_offhand_hand_crossbow(env):
    """Only hand crossbows can be dual-wielded as ranged weapons: the set validator (score_items.slot_ok) refuses any
    other ranged weapon in the ranged off hand, and every current set's ranged off hand (and its main) is one.
    Hand crossbow = the game's weapon Proficiency Group HandCrossbows."""
    gd = gamedata.load()
    S = tool_module(env, "score_items")
    items = env.items_all()

    def handxbow(sid):
        return "HandCrossbows" in str((gd.stats.get(sid) or {}).get("Proficiency Group") or "")
    ranged = sorted(sid for sid, r in items.items() if r.get("slot") == "Ranged Main Weapon" and r.get("weapon"))
    hx = [s for s in ranged if handxbow(s)]
    other = [s for s in ranged if not handxbow(s)]
    fails, n_val, n_sets = [], 0, 0
    if hx:
        for sid in hx + other:
            for chosen in ({}, {"Ranged": {"sid": hx[0]}}):
                n_val += 1
                ok = S.slot_ok(sid, "RangedOff", dict(chosen), items)
                if ok != handxbow(sid):
                    fails.append(f"validator: {items[sid].get('name') or sid} in the ranged off hand "
                                 f"{'allowed' if ok else 'refused'} (next to {chosen or 'nothing'})")
    for char, d in env.scores().items():
        for bk, b in d["builds"].items():
            for act, sets in (b.get("sets") or {}).items():
                for i, s in enumerate(sets):
                    its = s.get("items") or {}
                    if not (its.get("RangedOff") or {}).get("sid"):
                        continue
                    n_sets += 1
                    for slot in ("RangedOff", "Ranged"):
                        sid = (its.get(slot) or {}).get("sid")
                        if sid and not handxbow(sid):
                            fails.append(f"{char}.{bk} act {act} set {i + 1}: {slot} {sid} is not a hand crossbow "
                                         "but the ranged off hand is used")
    env.counts["validator cases"] = n_val
    env.counts["sets with a ranged off hand"] = n_sets
    if not hx or not other or n_val == 0:
        fails.append(f"nothing checked: {len(hx)} hand crossbows, {len(other)} other ranged weapons")
    return fails



# ==================================================================== 10. first builds follow Build Advisor; ruled owners
# Destructive Wrath maximises every Chain Lightning target and Markoheshkir's item spells, so Gale's kit.
RULED_OWNERS = {"MAG_TheChromatic_Staff": "gale", "MAG_EndGameCaster_Hood": "gale", "MAG_EndGameCaster_Cloak": "gale"}


def check_first_builds_and_ruled_owners(env):
    """Each origin's first build in LootData is Build Advisor's first build for that origin (when Loot Advisor
    profiles it), and every item in RULED_OWNERS has exactly that owner."""
    G = env.lua().globals()
    chars = lua_dict(G.LA.Data.chars)
    _builds, origins = gamedata.builds_lua(env.builds_lua)
    fails, n_first = [], 0
    for char, cd in chars.items():
        ids = [b.id for b in lua_list(cd.b)]
        want = next((b for b in origins.get(char, []) if b in ids), None)
        if want is None:
            continue
        n_first += 1
        if ids[0] != want:
            fails.append(f"{char}: first build {ids[0]}, Build Advisor's first is {want}")
    items = G.LA.Data["items"]
    owners = {items[i].id: lua_list(items[i].o) for i in range(1, len(items) + 1)}
    for sid, who in RULED_OWNERS.items():
        if owners.get(sid) != [who]:
            fails.append(f"{sid}: owners {owners.get(sid)}, ruled {who}")
    env.counts["origins with a Build Advisor first build"] = n_first
    env.counts["ruled owners"] = len(RULED_OWNERS)
    if n_first == 0:
        fails.append("nothing checked: no origin has a Build Advisor build")
    return fails

CHECKS = [
    ("no heavy body armour for raging builds", check_no_heavy_armour_raging, False),
    ("every Builds.lua build has a profile; sync fails loudly", check_profiles_cover_builds_lua, False),
    ("class proficiencies from the game (Cleric Morningstar/Flail)", check_class_proficiencies, False),
    ("subclass names as the game shows them", check_subclass_names, False),
    ("list-only items: no frame, no tooltip text", check_list_only_no_frame_no_text, False),
    # Logic.lua ownerAvailable counts only the active party (State.lua party flag): must pass
    ("contested owners: active party only (page = F6)", check_owner_active_party_only, False),
    ("sets page sheet: subclass features under the game's subclass names", check_sheet_subclass_features, False),
    ("sets page sheet: weapon damage riders (dice and stat) counted once", check_sheet_weapon_riders, False),
    ("ranged off hand: hand crossbows only (validator + sets)", check_ranged_offhand_hand_crossbow, False),
    ("first builds follow Build Advisor; Weave kit owned by Gale", check_first_builds_and_ruled_owners, False),
]
