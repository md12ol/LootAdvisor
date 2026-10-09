"""Optimizer tests (decisions 30 / 41 / 69): every test can fail, expectations come from independent sources.

  python tests/test_optimizer.py              CI tests (pure code) + local-only tests (need the game-derived data)
  python tests/test_optimizer.py --ci         CI tests only (tracked files only; no data/items_all, data/cache)
  python tests/test_optimizer.py --mutate     break each guarded rule (monkeypatches / patched copies, nothing on
                                              disk is changed) and prove the matching test goes red
  pytest tests/test_optimizer.py              same tests; local-only ones skip cleanly when the data is missing

CI tests: the condition reader, the d20 maths (brute-force enumeration), stack averages (explicit simulation) and
Great Weapon Fighting / Savage Attacker gains (enumeration) - written here, not copied from the code under test.
Local-only tests read the optimizer output (tools/optimizer/.cache/optimized.json, written by
tools/optimizer/run.py) and check it against the game data and Builds.lua through tests/gamedata.py (own parsers):
one set per origin x first two Build Advisor builds x act, proficiency, Rage + heavy armour, hands, act
obtainability, story-path families, Dark-Urge-only items, local optimality (no single swap improves the score) and
the unverified-mechanics switches. A test with nothing to check fails.
"""
import itertools
import json
import os
import random
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
OPT = os.path.join(LA, "tools", "optimizer")
OUT = os.path.join(OPT, ".cache", "optimized.json")
BUILDS_LUA = os.path.join(os.path.dirname(LA), "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender", "Lua", "Shared",
                          "Builds.lua")
sys.path.insert(0, HERE)
sys.path.insert(0, OPT)


def local_data_present():
    return all(os.path.exists(p) for p in (os.path.join(LA, "data", "items_all", "weapons.jsonl"),
                                           os.path.join(LA, "data", "cache", "stats_resolved.json"),
                                           os.path.join(LA, "data", "scores", "gale.json")))


def need_local():
    if not local_data_present():
        raise unittest.SkipTest("local-only: needs the game-derived data (data/items_all, data/cache, data/scores)")


# ============================================================================================ CI tests (pure code)
def _mech():
    # mech.py imports odata (data layer) only for split helpers; import it without loading data
    import mech
    return mech


class FakeState:
    def __init__(self):
        self.unknown = set()
        self.raging = 1.0
        self.target_prone = 0.0
        self.self_uptime, self.target_uptime = {}, {}
        self.act = 3
        self.exposure = 1.0
        self.concentrating = 0.0
        self.obscured = 0.0
        self.armour_cat = "Heavy"
        self.shield = False
        self.offhand_used = False
        self.mods = {"CHA": 3}
        self.classes = {}

    def has_passive(self, p):
        return p == "Owned"

    def gwm_on(self, ev):
        return 0.0

    def ss_on(self, ev):
        return 0.0


def test_condition_reader():
    """Probabilities of boolean condition text: independent hand formulas per expression."""
    M = _mech()
    st = FakeState()
    ev = {"melee": True, "weapon": True, "spell": False, "dtypes": {"Fire"}}
    cases = [
        ("IsMeleeAttack()", 1.0),
        ("not IsMeleeAttack()", 0.0),
        ("IsSpell() or IsMeleeAttack()", 1.0),
        ("IsSpell() and IsMeleeAttack()", 0.0),
        ("IsDamageTypeFire() and not IsDamageTypeCold()", 1.0),
        ("HasDamageDoneForType(DamageType.Cold)", 0.0),
        ("HasPassive('Owned', context.Source) and (IsWeaponAttack() or IsSpell())", 1.0),
        ("not (IsSpell() or not IsWeaponAttack())", 1.0),
        ("Tagged('UNDEAD')", 0.15),
        ("Tagged('UNDEAD') or Tagged('FIEND')", 1 - (1 - 0.15) * (1 - 0.12)),
        ("not HasHeavyArmor(context.Source)", 0.0),
    ]
    fails = []
    for text, want in cases:
        got = M.cond_p(text, M.Ctx(st, ev, "boost"))
        if abs(got - want) > 1e-9:
            fails.append(f"{text!r}: {got} != {want}")
    c = M.Ctx(st, ev, "boost")
    got = M.cond_p("SomethingNobodyKnows(1) and IsMeleeAttack()", c)
    if abs(got - 0.5) > 1e-9 or "SomethingNobodyKnows" not in st.unknown:
        fails.append(f"unknown predicate: {got}, recorded {st.unknown}")
    assert not fails, fails


def _enum_hit(bonus, ac, adv):
    """Brute force over the d20 (two dice for advantage): natural 1 misses, natural 20 hits."""
    tot = 0
    rolls = itertools.product(range(1, 21), repeat=2 if adv else 1)
    n = 0
    for r in rolls:
        d = max(r)
        n += 1
        tot += (d == 20) or (d != 1 and d + bonus >= ac)
    return tot / n


def test_d20_maths():
    M = _mech()
    fails = []
    for bonus in range(-2, 16, 3):
        for ac in (10, 15, 19, 25):
            for adv in (0.0, 1.0):
                want = _enum_hit(bonus, ac, adv)
                got = M.p_hit(bonus, ac, adv)
                if abs(got - want) > 1e-9:
                    fails.append(f"p_hit({bonus},{ac},adv={adv}) {got} != {want}")
    for thr in (18, 19, 20):
        for adv in (0.0, 1.0):
            n = c = 0
            for r in itertools.product(range(1, 21), repeat=2 if adv else 1):
                n += 1
                c += max(r) >= thr
            if abs(M.p_crit(thr, adv) - c / n) > 1e-9:
                fails.append(f"p_crit({thr},{adv})")
    for dc in (10, 15, 20):
        for sv in (0, 5):
            want = sum(1 for d in range(1, 21) if d + sv < dc) / 20
            want = min(0.95, max(0.05, want))
            if abs(M.p_fail(dc, sv) - want) > 1e-9:
                fails.append(f"p_fail({dc},{sv}) {M.p_fail(dc, sv)} != {want}")
    assert not fails, fails[:5]


def test_stack_average():
    """Stacks over a 4-round fight, closed forms worked out by hand from the status rules (add N turns a round,
    attacks see the mean of before / after, 1 turn runs out each round)."""
    M = _mech()
    cases = [((0.0,), 0.0),                       # nothing generates it
             ((0.0, 1.0, 10.0, 4, 0.0, 3.0), 3.0),  # floor 3 (Elixir of Battlemage's Power) and no generator
             ((2.0,), 2 * 2.0 - 1.5),             # uncapped, a >= 1: mean = 2a - 1.5
             ((3.0,), 2 * 3.0 - 1.5),
             ((5.0, 1.0, 3.0), (1.5 + 2.5 + 2.5 + 2.5) / 4),   # capped at 3: 0->3, then 2->3 each round
             ((1.0,), (0.5 + 0.5 + 0.5 + 0.5) / 4)]           # gain 1, lose 1: always 0 -> 1
    fails = []
    for args, want in cases:
        got = M.stack_average(*args)
        if abs(got - want) > 1e-9:
            fails.append(f"stack_average{args} = {got}, expected {want}")
    assert not fails, fails


def test_die_gains():
    model = _mech()
    fails = []
    for sides in (4, 6, 8, 10, 12):
        base = (sides + 1) / 2
        gwf = sum((sum(range(1, sides + 1)) / sides) if r <= 2 else r for r in range(1, sides + 1)) / sides - base
        if abs(model.die_gain(sides, reroll=2) - gwf) > 1e-9:
            fails.append(f"GWF d{sides}: {model.die_gain(sides, reroll=2)} != {gwf}")
        sav = sum(max(a, b) for a in range(1, sides + 1) for b in range(1, sides + 1)) / sides ** 2 - base
        if abs(model.die_gain(sides, savage=True) - sav) > 1e-9:
            fails.append(f"Savage d{sides}: {model.die_gain(sides, savage=True)} != {sav}")
    assert not fails, fails


CI_TESTS = [test_condition_reader, test_d20_maths, test_stack_average, test_die_gains]


# ============================================================================================ local-only tests
_CACHE = {}


def _world():
    if "W" not in _CACHE:
        import odata
        _CACHE["W"] = odata.World(quiet=True)
    return _CACHE["W"]


def _output(path=OUT):
    need_local()
    if not os.path.exists(path):
        raise AssertionError(f"no optimizer output at {path} - run python tools/optimizer/run.py first")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _items():
    import gamedata  # noqa: F401  (tests/gamedata.py: independent readers)
    out = {}
    for g in ("weapons", "armour", "accessories"):
        with open(os.path.join(LA, "data", "items_all", g + ".jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[r["stats_id"]] = r
    return out


def _conditions_md():
    fam, items, over = [], {}, {}
    section = ""
    with open(os.path.join(LA, "data", "research", "conditions.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("## "):
                section = line[3:].strip().lower()
                continue
            if not line.startswith("|") or re.match(r"^\|[\s:|-]+\|?\s*$", line):
                continue
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if section.startswith("exclusive") and cells[0] != "Family" and len(cells) >= 2:
                fam.append({p.strip() for p in cells[1].split(",") if p.strip()})
            elif section == "items" and len(cells) >= 3:
                items[cells[0]] = {c.strip() for c in cells[2].split(",") if c.strip()}
            elif section.startswith("act overrides") and len(cells) >= 4 and cells[2].isdigit():
                over[cells[0]] = int(cells[2])
    return fam, items, over


def _scored_info():
    info = {}
    for p in os.listdir(os.path.join(LA, "data", "scores")):
        if p.endswith(".json") and not p.startswith("_") and p not in ("owners.json", "name_matches.json",
                                                                       "optimized.json"):
            with open(os.path.join(LA, "data", "scores", p), encoding="utf-8") as f:
                for sid, v in json.load(f).get("item_info", {}).items():
                    info.setdefault(sid, v)
    return info


def check_coverage(out):
    """One Optimized set per origin x first two BA.Origins builds x act (Builds.lua parsed independently)."""
    import gamedata
    builds, origins = gamedata.builds_lua(BUILDS_LUA)
    with open(os.path.join(LA, "data", "scores", "gale.json"), encoding="utf-8"):
        pass
    have = {(s["char"], s["build"], s["act"]) for s in out["sets"]}
    fails = []
    chars = [c for c in origins if os.path.exists(os.path.join(LA, "data", "scores", c + ".json"))]
    n = 0
    for c in chars:
        with open(os.path.join(LA, "data", "scores", c + ".json"), encoding="utf-8") as f:
            scored = set(json.load(f)["builds"])
        for b in [x for x in origins[c] if x in scored][:2]:
            for act in (1, 2, 3):
                n += 1
                if (c, b, act) not in have:
                    fails.append(f"missing optimized set {c}.{b} act {act}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


_RACE = {}


def race_profs(race_name):
    """Proficiencies a race grants (Races.lsx -> its progression table at level 1 -> boosts and passives, the parent
    race included: High Elf gets Elf Weapon Training, Human Civil Militia). Own reader over tests/gamedata's pak
    access; nothing from the code under test."""
    import gamedata as G
    if not _RACE:
        Pak = G._pak_reader()
        with open(os.path.join(LA, "data", "cache", "loca_english.json"), encoding="utf-8") as f:
            loca = json.load(f)
        races, progs = {}, []
        for pak, mod in G.MODULES:
            p = Pak(os.path.join(G.GAME_DATA, pak))
            for path, kind in ((f"Public/{mod}/Races/Races.lsx", "Race"),
                               (f"Public/{mod}/Progressions/Progressions.lsx", "Progression")):
                if path in p.by_name:
                    rows = list(G._rows(p.read(p.by_name[path]), kind))
                    if kind == "Race":
                        races.update({r["UUID"]: r for r in rows})
                    else:
                        progs += rows
            p.close()
        stats = G.load().stats
        own = {}
        for u, r in races.items():
            got = set()
            for x in progs:
                if x.get("TableUUID") == r.get("ProgressionTableUUID") and x.get("Level") == "1":
                    got |= set(G.PROF.findall(x.get("Boosts") or ""))
                    for ps in (x.get("PassivesAdded") or "").split(";"):
                        got |= set(G.PROF.findall((stats.get(ps.strip()) or {}).get("Boosts") or ""))
            own[u] = got
        for u, r in races.items():
            tot, cur, seen = set(), u, set()
            while cur in races and cur not in seen:
                seen.add(cur)
                tot |= own.get(cur, set())
                cur = races[cur].get("ParentGuid")
            name = loca.get(races[u].get("DisplayName") or "", "")
            _RACE.setdefault(name, set()).update(tot)
    return _RACE.get(race_name, set())


def check_set_rules(out):
    """Every slot of every optimized set against the game data, independently of the optimizer code."""
    import gamedata
    gd = gamedata.load()
    items = _items()
    fam, cond_md, over = _conditions_md()
    info = _scored_info()
    srcs = {}
    with open(os.path.join(LA, "data", "items_all", "sources.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                if s.get("act") in (1, 2, 3) and s.get("confidence") != "low":
                    srcs.setdefault(s["stats_id"], set()).add(s["act"])
    builds, _o = gamedata.builds_lua(BUILDS_LUA)
    start = {b[0]: b[1] for b in builds}
    fails, n = [], 0
    for st in out["sets"]:
        cid, bid, act = st["char"], st["build"], st["act"]
        with open(os.path.join(LA, "data", "scores", cid + ".json"), encoding="utf-8") as f:
            b = json.load(f)["builds"][bid]
        lvl = {1: 5, 2: 8, 3: 12}[act]
        cls_full = b["classes"]
        with open(os.path.join(LA, "data", "scores", cid + ".json"), encoding="utf-8") as f:
            race = json.load(f).get("race") or ""
        profs = gd.expected_profs(cls_full, start.get(bid) or next(iter(cls_full)), b.get("subclasses") or {}) |             race_profs(race)
        rages = bool(set(cls_full) & gd.rage_classes)
        sl = {k: v["sid"] for k, v in st["items"].items()}
        for slot, sid in sl.items():
            n += 1
            rec = items.get(sid)
            if not rec:
                fails.append(f"{st['id']} {slot}: unknown item {sid}")
                continue
            name = rec["name"]
            texts = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
            # proficiency (armour / shields always; weapons in the hands the build attacks with)
            req = set((rec.get("requirements") or {}).get("proficiency") or [])
            if rec.get("armour") and req and not req <= profs and "considered proficient" not in texts:
                fails.append(f"{st['id']} {slot}: {name} needs {sorted(req - profs)}")
            # weapons need proficiency in the hands the build attacks with (its profile's attack modes, from the
            # scores data); a weapon in another hand is carried for its passives / item spells only
            att = (b.get("profile") or {}).get("attacks") or {}
            shoots = max(att.get("ranged", 0), att.get("handxbow", 0)) >= 2
            hits = max(att.get("melee2h", 0), att.get("melee1h", 0), att.get("thrown", 0), att.get("finesse", 0)) >= 2
            attacking = (slot in ("Ranged", "RangedOff") and shoots) or (slot in ("MainHand",) and hits) or                 (slot == "OffHand" and hits and b.get("profile", {}).get("offhand") == "dual")
            if rec.get("weapon") and attacking and req and not (req & profs):
                fails.append(f"{st['id']} {slot}: weapon {name} without proficiency {sorted(req)}")
            # Rage switches off in heavy armour
            if slot == "Breast" and rages and gd.armour_group(sid) == "HeavyArmor":
                fails.append(f"{st['id']}: raging build in heavy armour {name}")
            # slots / hands
            gslot = gd.slot(sid)
            if slot in ("Ring1", "Ring2") and gslot != "Ring" or slot in ("Helmet", "Cloak", "Breast", "Gloves",
                                                                          "Boots", "Amulet") and gslot != slot:
                fails.append(f"{st['id']} {slot}: {name} is a {gslot}")
            props = set((rec.get("weapon") or {}).get("properties") or [])
            if slot == "RangedOff" and "HandCrossbows" not in ((rec.get("weapon") or {}).get("proficiency") or []):
                fails.append(f"{st['id']}: off-hand ranged {name} is not a hand crossbow")
            if slot == "MainHand" and "Twohanded" in props and sl.get("OffHand"):
                fails.append(f"{st['id']}: two-handed {name} with an off-hand item")
            if slot == "OffHand" and rec.get("weapon") and not ("Light" in props and "Light" in set(
                    ((items.get(sl.get("MainHand") or "") or {}).get("weapon") or {}).get("properties") or [])):
                fails.append(f"{st['id']}: off-hand weapon {name} without two Light weapons")
            # act: obtainable by this act (scored first act, else the first act of a confident game source)
            first = [over[sid]] if sid in over else []
            if not first:
                if sid in info and info[sid].get("act"):
                    first.append(info[sid]["act"])
                if srcs.get(sid):
                    first.append(min(srcs[sid]))
            if not first:
                fails.append(f"{st['id']} {slot}: {name} has no game-data source")
            elif min(first) > act:
                fails.append(f"{st['id']} {slot}: {name} first obtainable in Act {min(first)}, set is Act {act}")
            codes = set(cond_md.get(sid, set())) | set((info.get(sid) or {}).get("cond") or [])
            if "durge" in codes and cid != "darkurge":
                fails.append(f"{st['id']} {slot}: Dark-Urge-only {name}")
            if any(c.startswith("costs:") for c in codes):
                fails.append(f"{st['id']} {slot}: {name} costs a companion")
        # unique items once
        vals = list(sl.values())
        for sid in set(vals):
            if vals.count(sid) > 1 and (items.get(sid) or {}).get("unique"):
                fails.append(f"{st['id']}: unique {items[sid]['name']} twice")
        # story-path families: two different paths of one family in one set
        paths = {}
        for sid in vals:
            codes = set(cond_md.get(sid, set())) | set((info.get(sid) or {}).get("cond") or [])
            for c in codes:
                if c.startswith("path:"):
                    paths.setdefault(c[5:], []).append(sid)
        for f_ in fam:
            hit = [p for p in f_ if p in paths]
            if len(hit) > 1:
                fails.append(f"{st['id']}: exclusive story paths {hit}")
        del lvl
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_local_optimum(out, sample=None, seed=7):
    """No single-slot swap (any legal candidate or empty) improves an optimized set's score: the definition of the
    search's end point, checked with the candidate lists and the model."""
    import model
    import search
    W = _world()
    fails, n = [], 0
    sets = [s for s in out["sets"]]
    if sample:
        random.Random(seed).shuffle(sets)
        sets = sets[:sample]
    for st in sets:
        cid, bid, act = st["char"], st["build"], st["act"]
        sw = (st.get("model") or {}).get("switches") or {}
        lo = {k: v["sid"] for k, v in st["items"].items()}
        S = search.Searcher(W, cid, bid, act, sw)
        cur = S.score(lo).score
        for slot in search.ORDER:
            for sid in S.cands[slot] + [None]:
                if sid == lo.get(slot):
                    continue
                t = dict(lo)
                if sid is None:
                    t.pop(slot, None)
                elif not search.legal(W, slot, sid, {k: v for k, v in lo.items() if k != slot}):
                    continue
                else:
                    t[slot] = sid
                n += 1
                v = S.score(t).score
                # the owned-item pass may keep an earlier-act item that is up to 3% weaker (sets rule)
                if v > cur * 1.031 + 1e-6:
                    fails.append(f"{st['id']} {slot}: {W.items[sid]['name'] if sid else '(empty)'} scores {v:.1f} "
                                 f"> {cur:.1f}")
                    break
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_research_not_better(out):
    """The research sets were search seeds: none may beat the optimized set under the same model."""
    fails, n = [], 0
    for r in out["compare"]:
        if r.get("ref_score") is None:
            continue
        n += 1
        if r["ref_score"] > r["opt_score"] + 1e-6:
            fails.append(f"{r['char']}.{r['build']} act {r['act']}: research '{r['ref_set']}' {r['ref_score']} > "
                         f"optimized {r['opt_score']}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_switches(out=None):
    """Each unverified mechanic switch moves the score of a build that uses that mechanic in the right direction,
    with an independent rough expectation of the size (Builds.lua + game numbers, not the model)."""
    import model
    W = _world()
    fails, n = [], 0
    cases = [  # (char, build, act, switch, expected sign of (flipped - default) offence)
        ("astarion", "thx", 3, "twf_offhand_xbow", -1),          # off-hand shots lose DEX
        ("darkurge", "throw_zerk5_thief4", 3, "enraged_throw_each_ba", -1),   # one Enraged Throw instead of two
        ("gale", "tempestevoker", 3, "dw_chain_all", -1),        # only the main Chain Lightning target maximised
        ("shadowheart", "lightquick", 3, "rotd_char_level", -1),  # Radiance of the Dawn + Cleric level 9 (< 12)
    ]
    outsets = {(s["char"], s["build"], s["act"]): s for s in (out or {}).get("sets", [])}
    for cid, bid, act, k, sign in cases:
        st = outsets.get((cid, bid, act))
        if st is None:
            fails.append(f"no optimized set for {cid}.{bid} act {act}")
            continue
        lo = {s: v["sid"] for s, v in st["items"].items()}
        a = model.score(W, cid, bid, act, lo).offence
        b = model.score(W, cid, bid, act, lo, {k: not model.SWITCHES[k]["default"]}).offence
        n += 1
        if (b - a) * sign <= 0:
            fails.append(f"{cid}.{bid} act {act} switch {k}: offence {a:.1f} -> {b:.1f} (expected sign {sign})")
        if k == "twf_offhand_xbow":
            # off-hand shots per round (Fast Hands: 2 bonus actions) x hit chance (>= 5%) x DEX modifier (+5 at 20)
            if not (0.05 * 1 * 5 * 0.5 <= a - b <= 2 * 0.95 * 5 + 1e-6):
                fails.append(f"thx TWF switch changes offence by {a - b:.1f} (expected 0.1-9.5)")
        if k == "rotd_char_level":
            # (12 - 9) more damage per target, <= 4 targets, a few uses per fight -> 0 < diff < 3 * 4 * 1
            if not (0 < a - b <= 12):
                fails.append(f"lightquick RotD switch changes offence by {a - b:.2f} (expected 0-12)")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_why_text(out):
    """Why texts go through the player-text filter: no leak (tools/leak_scan.py patterns)."""
    sys.path.insert(0, os.path.join(LA, "tools"))
    import leak_scan
    fails, n = [], 0
    for st in out["sets"]:
        n += 1
        for kind, pat in leak_scan.hits(st.get("why") or ""):
            fails.append(f"{st['id']}: why text leaks {kind}: {pat!r}")
        if not (st.get("why") or "").strip():
            fails.append(f"{st['id']}: empty why text")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


LOCAL_CHECKS = [("coverage", check_coverage), ("set rules vs game data", check_set_rules),
                ("research sets never beat the optimizer", check_research_not_better),
                ("why text has no leaks", check_why_text), ("switches", check_switches),
                ("local optimum (sample of 6 sets)", lambda o: check_local_optimum(o, sample=6))]


def _as_test(fn):
    def t():
        out = _output()
        fails, _n = fn(out)
        assert not fails, fails[:8]
    return t


for _name, _fn in LOCAL_CHECKS:
    globals()["test_local_" + re.sub(r"\W+", "_", _name).strip("_")] = _as_test(_fn)


# ============================================================================================ runner + mutations
def run_ci():
    bad = 0
    for t in CI_TESTS:
        try:
            t()
            print(f"[PASS ] {t.__name__} (CI)")
        except AssertionError as e:
            bad += 1
            print(f"[FAIL ] {t.__name__} (CI): {str(e)[:300]}")
    return bad


def run_local(out=None, checks=None):
    if not local_data_present():
        print("[SKIP ] local-only tests: game-derived data missing")
        return 0
    out = out or _output()
    bad = 0
    for name, fn in checks or LOCAL_CHECKS:
        fails, n = fn(out)
        print(f"[{'FAIL' if fails else 'PASS':5}] {name} ({n} cases)")
        for f in fails[:6]:
            print("         - " + str(f)[:220])
        bad += bool(fails)
    return bad


def _optimize_set(cid, bid, act, switches=None):
    import run as R
    W = _world()
    o = R.optimize(W, cid, bid, act, switches)
    st = R.to_set(W, o)
    return {"char": cid, **st}


def mutations():
    """-> [(description, test function, expect 'red')]. Each mutation is undone after its check."""
    import mech
    import model
    import odata
    import search
    out = []

    def m_cond_not():
        old = mech.eval_cond

        def bad(node, c):
            if node and node[0] == "not":
                return old(node[1], c)          # 'not' ignored
            return old(node, c)
        mech.eval_cond = bad
        try:
            test_condition_reader()
            return []
        except AssertionError as e:
            return [str(e)]
        finally:
            mech.eval_cond = old
    out.append(("condition reader: 'not' ignored", m_cond_not))

    def m_phit():
        old = mech.p_hit
        mech.p_hit = lambda bonus, ac, adv=0.0, dis=0.0: old(bonus + 1, ac, adv, dis)
        try:
            test_d20_maths()
            return []
        except AssertionError as e:
            return [str(e)]
        finally:
            mech.p_hit = old
    out.append(("p_hit off by one", m_phit))

    def m_gwf():
        old = mech.die_gain
        mech.die_gain = lambda sides, reroll=None, savage=False: old(sides, reroll + 1 if reroll else None, savage)
        try:
            test_die_gains()
            return []
        except AssertionError as e:
            return [str(e)]
        finally:
            mech.die_gain = old
    out.append(("Great Weapon Fighting rerolls 1-3", m_gwf))

    if not local_data_present():
        return out
    W = _world()

    def m_rage():
        # the Rage rule is guarded twice (Scorer.usable and the model's "heavy armour switches Rage off"), so the
        # optimizer never picks it even with one guard removed; break the OUTPUT instead: a raging build's chest
        # becomes the first heavy body armour the game data has
        o2 = _output()
        import gamedata
        gd = gamedata.load()
        st = json.loads(json.dumps(next(x for x in o2["sets"] if x["char"] == "karlach")))
        heavy = next(sid for sid in sorted(_items()) if gd.slot(sid) == "Breast" and
                     gd.armour_group(sid) == "HeavyArmor")
        st["items"]["Breast"] = {"sid": heavy}
        return [f for f in check_set_rules({"sets": [st]})[0] if "heavy armour" in f]
    out.append(("raging build in heavy body armour (Karlach set, chest replaced)", m_rage))

    def m_prof():
        # armour the build has no proficiency for (Wyll's Sorlock: light armour only) - the first medium body armour
        o2 = _output()
        import gamedata
        gd = gamedata.load()
        st = json.loads(json.dumps(next(x for x in o2["sets"] if x["build"] == "sorlock")))
        st["items"]["Breast"] = {"sid": next(sid for sid, r in sorted(_items().items()) if gd.slot(sid) == "Breast"
                                             and gd.armour_group(sid) == "MediumArmor" and
                                             (r.get("requirements") or {}).get("proficiency"))}
        return [f for f in check_set_rules({"sets": [st]})[0] if "needs" in f]
    out.append(("sorlock in medium armour it is not proficient with", m_prof))

    def m_legal():
        old = search.legal
        search.legal = lambda W_, slot, sid, lo: True
        try:
            st = _optimize_set("astarion", "thx", 3)
        finally:
            search.legal = old
        return check_set_rules({"sets": [st]})[0]
    out.append(("set legality off (astarion thx Act 3 re-optimized)", m_legal))

    def m_act():
        old = W.obtainable
        W.obtainable = lambda sid, act: old(sid, 3)
        try:
            st = _optimize_set("laezel", "bmgiant", 1)
        finally:
            W.obtainable = old
        return check_set_rules({"sets": [st]})[0]
    out.append(("act gate off (laezel bmgiant Act 1 sees Act 3 items)", m_act))

    def m_descent():
        old = search.Searcher.run

        def lazy(self, starts):
            lo = search.drop_illegal(self.W, min(starts, key=lambda s: len(s)))   # the empty loadout, no search
            return lo, self.score(lo)
        search.Searcher.run = lazy
        try:
            st = _optimize_set("wyll", "sorlock", 2)
        finally:
            search.Searcher.run = old
        return check_local_optimum({"sets": [st]})[0]
    out.append(("search disabled (wyll sorlock Act 2)", m_descent))

    def m_switch():
        old = model.SWITCHES["twf_offhand_xbow"]
        o2 = _output()
        src = open(os.path.join(OPT, "model.py"), encoding="utf-8").read()
        del src
        orig = model.make_weapon_events

        def no_switch(st):
            st.sw["twf_offhand_xbow"] = True        # the switch is ignored
            return orig(st)
        model.make_weapon_events = no_switch
        try:
            return check_switches(o2)[0]
        finally:
            model.make_weapon_events = orig
            model.SWITCHES["twf_offhand_xbow"] = old
    out.append(("TWF off-hand switch ignored", m_switch))

    def m_leak():
        o2 = _output()
        o3 = {"sets": [dict(o2["sets"][0], why=o2["sets"][0]["why"] + " (MAG_TheChromatic_Staff, gale.md:12)")]}
        return check_why_text(o3)[0]
    out.append(("an internal id in a why text", m_leak))

    def m_path():
        o2 = _output()
        fam, cond_md, _o = _conditions_md()
        info = _scored_info()
        by_path = {}
        for sid, v in list(info.items()):
            for c in set(v.get("cond") or []) | cond_md.get(sid, set()):
                if c.startswith("path:"):
                    by_path.setdefault(c[5:], sid)
        pair = next(((by_path[a], by_path[b]) for f_ in fam for a in f_ for b in f_ if a < b and a in by_path
                     and b in by_path), None)
        if not pair:
            return ["no exclusive pair found in the data to build the mutation"]
        st = json.loads(json.dumps(o2["sets"][0]))
        st["items"]["Ring1"] = {"sid": pair[0]}
        st["items"]["Ring2"] = {"sid": pair[1]}
        return [f for f in check_set_rules({"sets": [st]})[0] if "exclusive" in f]
    out.append(("two items of exclusive story paths in one set", m_path))
    return out


def run_mutations():
    ok = 0
    muts = mutations()
    for desc, fn in muts:
        try:
            fails = fn()
        except Exception as e:  # noqa: BLE001
            fails = [f"crash: {e!r}"]
        red = bool(fails) and not any(str(f).startswith("crash") for f in fails)
        ok += red
        print(f"[{'OK ' if red else 'BAD'}] {desc} -> {'caught (red)' if red else 'NOT caught'}; "
              f"{len(fails)} line(s){': ' + str(fails[0])[:160] if fails else ''}")
    print(f"\n{ok}/{len(muts)} mutations caught")
    return 0 if ok == len(muts) else 1


def main():
    if "--mutate" in sys.argv:
        sys.exit(run_mutations())
    bad = run_ci()
    if "--ci" not in sys.argv:
        bad += run_local()
    print("FAILED" if bad else "all passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
