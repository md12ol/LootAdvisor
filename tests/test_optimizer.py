"""Optimizer tests: every test can fail, expectations come from independent sources.

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
the unverified-mechanics switches, party ownership (owners.json read here), defensive value (status immunities
read from the game stats here), creature-type / wearer conditions, stealth openers, the action economy of per-rest
item spells, The Dead Shot's crit range, a weapon's ability-modifier rider counted once, the boss scenario, the
respec tuning (re-scored and re-checked against the point-buy rules here) and the test-plan export, with the
toggles it assumes. A test with nothing to check fails.
"""
import contextlib
import itertools
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
OPT = os.path.join(LA, "tools", "optimizer")
OUT = os.path.join(OPT, ".cache", "optimized.json")
BUILDS_LUA = os.path.join(os.path.dirname(LA), "BuildAdvisor", "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender",
                          "Lua", "Shared", "Builds.lua")
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
        self.tags = {"GITHYANKI", "HUMANOID"}
        self.enemy_types = {"UNDEAD": 0.15, "FIEND": 0.12, "HUMANOID": 0.6}

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
        # the wearer's own tags (context.Source) vs the enemy's creature-type share
        ("Tagged('GITHYANKI', context.Source)", 1.0),
        ("Tagged('GITHYANKI')", 0.0),
        ("Tagged('ABERRATION')", 0.0),
        ("Tagged('HUMANOID', context.Target)", 0.6),
    ]
    fails = []
    for text, want in cases:
        got = M.cond_p(text, M.Ctx(st, ev, "boost"))
        if abs(got - want) > 1e-9:
            fails.append(f"{text!r}: {got} != {want}")
    # being attacked: context.Source is the attacker, an enemy
    got = M.cond_p("Tagged('UNDEAD', context.Source)", M.Ctx(st, {"defence": True}, "boost"))
    if abs(got - 0.15) > 1e-9:
        fails.append(f"defence Tagged(UNDEAD, Source): {got} != 0.15")
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


def test_roll_mix():
    """Advantage and Disadvantage at once cancel to a straight roll; with chances of each (independent) the hit and
    crit chances are the mix of the four cases, each enumerated over the d20s here."""
    M = _mech()
    fails = []

    def enum_crit(thr, mode):
        rolls = list(itertools.product(range(1, 21), repeat=1 if mode == 0 else 2))
        pick = (lambda r: r[0]) if mode == 0 else max if mode == 1 else min
        return sum(pick(r) >= thr for r in rolls) / len(rolls)

    def enum_dis(bonus, ac):
        rolls = list(itertools.product(range(1, 21), repeat=2))
        return sum((min(r) == 20) or (min(r) != 1 and min(r) + bonus >= ac) for r in rolls) / len(rolls)
    for a, d in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 15 / 16), (0.5, 0.25), (0.3, 0.9)):
        an, dn = M.roll_mix(a, d)
        w = {"adv": a * (1 - d), "dis": d * (1 - a), "straight": a * d + (1 - a) * (1 - d)}
        if abs(an - w["adv"]) > 1e-12 or abs(dn - w["dis"]) > 1e-12:
            fails.append(f"roll_mix({a},{d}) = {an},{dn}")
        for bonus, ac in ((5, 15), (11, 19), (-1, 25)):
            want = w["adv"] * _enum_hit(bonus, ac, 1) + w["dis"] * enum_dis(bonus, ac) + \
                w["straight"] * _enum_hit(bonus, ac, 0)
            if abs(M.p_hit_mix(bonus, ac, an, dn) - want) > 1e-9:
                fails.append(f"p_hit_mix({bonus},{ac},{a},{d}) {M.p_hit_mix(bonus, ac, an, dn)} != {want}")
        for thr in (19, 20):
            want = w["adv"] * enum_crit(thr, 1) + w["dis"] * enum_crit(thr, 2) + w["straight"] * enum_crit(thr, 0)
            if abs(M.p_crit(thr, an, dn) - want) > 1e-9:
                fails.append(f"p_crit({thr},{a},{d}) {M.p_crit(thr, an, dn)} != {want}")
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


def test_float_averages():
    """Dice averages are not whole numbers: 1d4 = 2.5 (hand values)."""
    M = _mech()
    cases = [("1d4", 2.5), ("1d10", 5.5), ("3d4+3", 10.5), ("2d6+StrengthModifier", 12.0),
             ("max(1,StrengthModifier)", 5.0), ("1d6/2", 1.75)]
    fails = [f"{e}: {M.avg_expr(e, {'StrengthModifier': 5})} != {w}" for e, w in cases
             if abs(M.avg_expr(e, {"StrengthModifier": 5}) - w) > 1e-9]
    assert not fails, fails


def _model():
    import model
    return model


def test_situational_uptimes():
    """Stealth check vs d20 enumeration (Advantage / Disadvantage), concentration uptime vs enumerating every
    break sequence, the until-rest uptime vs numerical integration of the Poisson first-arrival time."""
    m = _model()
    fails = []
    for bonus in (3, 7, 11):
        for dc in (12, 15):
            for adv, dis in ((0, 0), (1, 0), (0, 1), (1, 1)):
                rolls = list(itertools.product(range(1, 21), repeat=2))
                ok = 0
                for a, b in rolls:
                    d = max(a, b) if adv and not dis else min(a, b) if dis and not adv else a
                    ok += d + bonus >= dc
                want = ok / len(rolls)
                got = m.stealth_p(bonus, dc, adv, dis)
                if abs(got - want) > 1e-9:
                    fails.append(f"stealth_p({bonus},{dc},{adv},{dis}) {got} != {want}")
    for q in (0.0, 0.2, 0.5):
        # rounds 2..4 up while not broken; broken in a round with probability q, round 1 is the cast
        tot = 0.0
        for seq in itertools.product((0, 1), repeat=3):
            pr, up, alive = 1.0, 0, True
            for b in seq:
                pr *= q if b else 1 - q
                alive = alive and not b
                up += alive
            tot += pr * up
        want = tot / 4
        if abs(m.conc_uptime(q, 4) - want) > 1e-9:
            fails.append(f"conc_uptime({q}) {m.conc_uptime(q, 4)} != {want}")
    import math as _m
    for rate in (0.05, 0.3, 1.0):
        T, N = 16, 20000
        integ = sum(1 - _m.exp(-rate * (i + 0.5) * T / N) for i in range(N)) / N
        if abs(m.persist_uptime(rate, T) - integ) > 1e-4:
            fails.append(f"persist_uptime({rate}) {m.persist_uptime(rate, T)} != {integ}")
    assert not fails, fails[:5]


class _FakeW:
    def __init__(self, stats):
        self.stats = stats


def test_projectile_totals():
    """A tooltip that lists all projectiles' damage counts once; a per-beam tooltip counts per beam (worked by hand
    from two stats entries written here)."""
    M = _mech()
    W = _FakeW({
        "RayAll": {"Level": "2", "TooltipDamageList": "DealDamage(8d6,Fire)", "SpellSuccess": "DealDamage(2d6,Fire,Magical)",
                   "SpellRoll": "Attack(AttackType.RangedSpellAttack)", "AmountOfTargets": "4", "SpellFlags": "IsSpell"},
        "Beam": {"Level": "0", "TooltipDamageList": "DealDamage(1d10,Force)", "SpellSuccess": "DealDamage(1d10,Force,Magical)",
                 "SpellRoll": "Attack(AttackType.RangedSpellAttack)", "AmountOfTargets": "LevelMapValue(EldritchBlast)"},
        "Darts": {"Level": "1", "TooltipDamageList": "DealDamage(3d4+3,Force)", "AmountOfTargets": "3"}})
    fails = []
    for sid, lvl, want in (("RayAll", 5, 28.0), ("Beam", 5, 11.0), ("Beam", 10, 16.5), ("Darts", 5, 10.5)):
        sp = M.read_spell(W, sid, lvl)
        tot = sum(M.avg_expr(e) for e, _t in sp["dmg"]) * sp["beams"]
        if abs(tot - want) > 1e-9:
            fails.append(f"{sid} level {lvl}: {tot} != {want}")
    assert not fails, fails


def _party():
    import party
    return party


def _brute_force(claims, table):
    """Best party value over every assignment, enumerated here (independent of party.py)."""
    items = sorted(claims)
    chars = sorted({c for cs in claims.values() for c in cs})
    best = None
    for pick in itertools.product(*(claims[i] for i in items)):
        v = sum(table[c][frozenset(i for i, w in zip(items, pick) if w == c)] for c in chars)
        best = v if best is None else max(best, v)
    return best


def _value_of(assign, claims, table):
    chars = sorted({c for cs in claims.values() for c in cs})
    return sum(table[c][frozenset(i for i, w in assign.items() if w == c)] for c in chars)


def test_party_solver():
    """Party assignment of contested unique items: a hand-worked case where giving each item to the character that
    loses most without it is wrong, independent components, and random instances against brute-force enumeration
    (exact path) and a neighbourhood check written here (local-search path)."""
    P = _party()
    fails, n = [], 0
    # hand-worked: x and y are substitutes for A (same slot), complements for B.
    # marginal losses: x -> A 6-5=1, B 8-4=4; y the same -> greedy gives B both: 0 + 8 = 8.
    # best: one item each, 5 + 4 = 9 (either way round).
    fs = frozenset
    table = {"A": {fs(): 0, fs("x"): 5, fs("y"): 5, fs("xy"): 6},
             "B": {fs(): 0, fs("x"): 4, fs("y"): 4, fs("xy"): 8}}
    claims = {"x": ["A", "B"], "y": ["A", "B"]}
    for budget in (P.EXACT_BUDGET, 0):
        n += 1
        r = P.solve(claims, lambda c, k: table[c][k], exact_budget=budget)
        got = _value_of(r["assign"], claims, table)
        if abs(got - 9) > 1e-9 or abs(r["total"] - 9) > 1e-9:
            fails.append(f"hand case (budget {budget}): {r['assign']} worth {got}, reported {r['total']}, want 9")
    # two independent conflicts: C/D share z (C loses 3, D loses 1), E/F share w (E loses 1, F loses 2)
    t2 = {"C": {fs(): 1, fs("z"): 4}, "D": {fs(): 1, fs("z"): 2}, "E": {fs(): 0, fs("w"): 1},
          "F": {fs(): 0, fs("w"): 2}}
    c2 = {"z": ["C", "D"], "w": ["E", "F"]}
    r = P.solve(c2, lambda c, k: t2[c][k])
    n += 1
    if r["assign"] != {"z": "C", "w": "F"} or r["methods"]["exact"] != 2:
        fails.append(f"two components: {r['assign']} {r['methods']}, want z->C, w->F, 2 exact")
    rng = random.Random(11)
    for case in range(40):
        chars = ["c%d" % k for k in range(rng.randint(2, 4))]
        items = ["i%d" % k for k in range(rng.randint(1, 5))]
        claims = {i: sorted(rng.sample(chars, rng.randint(2, len(chars)))) for i in items}
        wants = {c: [i for i in items if c in claims[i]] for c in chars}
        table = {}
        for c in chars:
            table[c] = {}
            for m in range(len(wants[c]) + 1):
                for sub in itertools.combinations(wants[c], m):
                    table[c][frozenset(sub)] = rng.randint(0, 20) + 5 * m
        best = _brute_force(claims, table)
        for budget in (10 ** 6, 0):
            n += 1
            r = P.solve(claims, lambda c, k, t=table: t[c][k], exact_budget=budget)
            a = r["assign"]
            if set(a) != set(items) or any(a[i] not in claims[i] for i in items):
                fails.append(f"case {case}: {a} does not give each item to one of its claimants {claims}")
                continue
            got = _value_of(a, claims, table)
            if abs(got - r["total"]) > 1e-9:
                fails.append(f"case {case}: reported {r['total']} but the assignment is worth {got}")
            if budget and abs(got - best) > 1e-9:
                fails.append(f"case {case}: exact path {got} < brute force {best}")
            if not budget:
                for i in items:
                    for c in claims[i]:
                        if _value_of(dict(a, **{i: c}), claims, table) > got + 1e-9:
                            fails.append(f"case {case}: moving {i} to {c} improves the local-search result")
                for i, j in itertools.combinations(items, 2):
                    if a[i] != a[j] and a[j] in claims[i] and a[i] in claims[j] and \
                            _value_of(dict(a, **{i: a[j], j: a[i]}), claims, table) > got + 1e-9:
                        fails.append(f"case {case}: swapping {i} and {j} improves the local-search result")
    assert n and not fails, fails[:6]


def test_party_threshold():
    """The 10% rule on hand-built tables: O is the owner of x, the plain solver prefers X. X's gain over O's gain:
    +5% keeps x with O, +15% moves it, exactly +10% moves it, +9.9% keeps it; when x stays with O, X takes the
    item y the plain solver gave to Y (the rest is solved again)."""
    P = _party()
    fs = frozenset
    fails = []
    for gain_x, want in ((10.5, "O"), (11.5, "X"), (11.0, "X"), (10.99, "O")):
        table = {"O": {fs(): 10, fs("x"): 20}, "X": {fs(): 10, fs("x"): 10 + gain_x}}
        claims = {"x": ["O", "X"]}
        value = lambda c, k, t=table: t[c][k]   # noqa: E731
        plain = P.solve(claims, value)["assign"]["x"]
        r = P.solve_rule(claims, value, {"x": "O"})
        rule = "kept_by_threshold" if want == "O" else "moved"
        other = "moved" if want == "O" else "kept_by_threshold"
        if plain != "X":
            fails.append(f"gain {gain_x}: the plain solver gave x to {plain}, the case needs X")
        if r["assign"]["x"] != want or "x" not in r[rule] or "x" in r[other]:
            fails.append(f"gain {gain_x}: x -> {r['assign']['x']} kept {sorted(r['kept_by_threshold'])} moved "
                         f"{sorted(r['moved'])}, want x -> {want} ({rule})")
        want_m = (gain_x - 10) / 10
        got = r[rule].get("x", {}).get("margin")
        if got is None or abs(got - want_m) > 1e-9:
            fails.append(f"gain {gain_x}: margin {got}, want {want_m}")
        if abs(r["total"] - (20 + 10 if want == "O" else 10 + 10 + gain_x)) > 1e-9:
            fails.append(f"gain {gain_x}: total {r['total']}")
    # x: O 10, X 10.5 (+5%); X uses only one of x / y (10.5 either way); y: X 10.5, Y 10.2.
    # plain best: x -> X, y -> Y (10.5 + 10.2 + O's 0 = 20.7). The rule keeps x with O; solved again,
    # y -> X (10 + 10.5 = 20.5 beats 10 + 10.2). y has no owner, so it is not checked.
    t3 = {"O": {fs(): 0, fs("x"): 10}, "X": {fs(): 0, fs("x"): 10.5, fs("y"): 10.5, fs("xy"): 10.5},
          "Y": {fs(): 0, fs("y"): 10.2}}
    c3 = {"x": ["O", "X"], "y": ["X", "Y"]}
    v3 = lambda c, k: t3[c][k]   # noqa: E731
    plain = P.solve(c3, v3)["assign"]
    r = P.solve_rule(c3, v3, {"x": "O"})
    if plain != {"x": "X", "y": "Y"}:
        fails.append(f"re-solve case: plain {plain}, the case needs x -> X, y -> Y")
    if r["assign"] != {"x": "O", "y": "X"} or set(r["kept_by_threshold"]) != {"x"} or abs(r["total"] - 20.5) > 1e-9:
        fails.append(f"re-solve case: {r['assign']} kept {sorted(r['kept_by_threshold'])} total {r['total']}, want "
                     "x -> O (kept), y -> X, 20.5")
    # an owner that gains nothing loses the item to any pick that gains something
    t4 = {"O": {fs(): 5, fs("x"): 5}, "X": {fs(): 5, fs("x"): 5.1}}
    r = P.solve_rule({"x": ["O", "X"]}, lambda c, k: t4[c][k], {"x": "O"})
    if r["assign"]["x"] != "X" or r["moved"].get("x", {}).get("margin") != math.inf:
        fails.append(f"owner gains nothing: {r['assign']} moved {r['moved']}")
    assert not fails, fails


def test_target_hp():
    """The target's hit points in a condition: a day's share below the percentage, while in the boss scenario the
    gauntlet resets the enemy to 99% at each of our turns, so "hurt" (99 or less) is true and "below half" or "below
    99" false; the character's own hit points are not the target's; the day comes back after the block."""
    M = _mech()
    import model
    st, ev = FakeState(), {"weapon": True}

    def p(text):
        return M.cond_p(text, M.Ctx(st, ev, "boost"))
    fails = []
    day = (p("HasHPPercentageEqualOrLessThan(99, context.Target)"), p("HasHPPercentageLessThan(50, context.Target)"))
    if abs(day[0] - 0.99) > 1e-9 or abs(day[1] - 0.4) > 1e-9:
        fails.append(f"day {day}")
    with model.scenario("boss"):
        got = {t: p(t) for t in ("HasHPPercentageEqualOrLessThan(99, context.Target)",
                                 "HasHPPercentageLessThan(99, context.Target)",
                                 "HasHPPercentageLessThan(100, context.Target)",
                                 "HasHPPercentageEqualOrLessThan(50, context.Target)",
                                 "HasHPPercentageWithoutTemporaryHPLessThan(99, context.Target)",
                                 "HasHPPercentageEqualOrLessThan(50, context.Source)")}
    want = [1.0, 0.0, 1.0, 0.0, 0.0, 0.25]
    if list(got.values()) != want:
        fails.append(f"boss {got}")
    if M.TARGET_HP_PCT is not None:
        fails.append("the boss's hit points left in the day model")
    assert not fails, fails


def test_buff_spells():
    """Buff item spells (Gontr Mael's Haste, Giantslayer's Enlarge): the status a spell puts on and what it gives, read
    from stats written here; a status with a lethargy (OnRemoveFunctors) is no buff. Worth: an extra action a turn on
    the turns after the cast plus weapon dice on every hit, less the action the cast takes, less a concentration mark's
    turns (hand formulas); dropped when not positive."""
    M = _mech()
    import model
    S = {"Shout_H": {"SpellProperties": "ApplyStatus(H1,100, 5)", "SpellFlags": "IsConcentration;IsSpell",
                     "UseCosts": "ActionPoint:1", "Cooldown": "OncePerRestPerItem"},
         "H1": {"Boosts": "ActionResource(Movement,9,0);AC(2);ActionResource(ActionPoint,1,0)", "OnRemoveFunctors": ""},
         "Shout_E": {"SpellProperties": "ApplyStatus(E1,100,10)", "UseCosts": "ActionPoint:1"},
         "E1": {"Boosts": "CharacterWeaponDamage(1d6);ObjectSize(+1)", "StackId": "SIZE"},
         "Shout_L": {"SpellProperties": "ApplyStatus(L1,100,3)"},
         "L1": {"Boosts": "ActionResource(ActionPoint,1,0)", "OnRemoveFunctors": "ApplyStatus(LETHARGIC,100,1)"},
         "Shout_N": {"SpellProperties": "DealDamage(1d6,Fire)"}}
    fails = []
    h, e = M.item_buff(S, "Shout_H"), M.item_buff(S, "Shout_E")
    if not h or (h["status"], h["turns"], h["actions"], h["wdmg"], h["conc"]) != ("H1", 5, 1, 0, True):
        fails.append(f"haste {h}")
    if not e or (e["status"], e["turns"], e["actions"], e["wdmg"], e["stack"]) != ("E1", 10, 0, 3.5, "SIZE"):
        fails.append(f"enlarge {e}")
    if M.item_buff(S, "Shout_L") is not None or M.item_buff(S, "Shout_N") is not None:
        fails.append("a lethargy or a plain damage spell read as a buff")
    st = type("St", (), {})()
    st.sheet = {"nAtt": 3}
    evs = [{"name": "attack", "n": 3.0}]
    res = [{"dmg": 90.0}]
    old = model._buff_spells
    try:
        model._buff_spells = lambda _st: [("Shout_H", "Bow", h, 1), ("Shout_E", "Sword", e, 3)]
        with model.scenario("boss"):
            out = model.buff_events(st, evs, res, {"mark": 2.0}, 2.7)
        # haste: 4 extra actions of 90, less the cast's 90, less the mark (2 per hit, 2.7 hits, 5 turns)
        want_h = 4 * 90 - 90 - 2.0 * 2.7 * 5
        # enlarge: 3.5 a hit, 2.7 hits a round, 10 turns, less the cast's 90; negative -> dropped
        want_e = 3.5 * 2.7 * 10 - 90
        got = {ev["spell_id"]: (ev["gain_per_cast"], ev["dropped"], r["dmg"]) for ev, r in out}
        if abs(got["Shout_H"][0] - round(want_h, 2)) > 1e-6 or got["Shout_H"][1] or \
                abs(got["Shout_H"][2] - want_h / 16) > 1e-6:
            fails.append(f"haste worth {got['Shout_H']}, want {want_h}")
        if abs(got["Shout_E"][0] - round(want_e, 2)) > 1e-6 or got["Shout_E"][1] is not (want_e <= 0):
            fails.append(f"enlarge worth {got['Shout_E']}, want {want_e}")
    finally:
        model._buff_spells = old
    assert not fails, fails


def test_riposte():
    """Riposte: per round min(dice kept, enemy misses in a fight) / rounds, each one attack's damage plus a die on a hit
    (hand formula); none without dice kept for it or for a ranged build."""
    import model
    st = type("St", (), {})()
    st.plan = {"mode": "melee"}
    evs, res = [{"name": "attack", "n": 3.0}], [{"dmg": 90.0, "ph": 0.9, "pc": 0.05}]
    fails = []
    with model.scenario("boss"):
        ev, r = model.riposte_event(st, evs, res, {"riposte_dice": 10.0, "die": 5.5},
                                    {"enemy_attacks": 1.0, "enemy_ph": 0.6})
        few = model.riposte_event(st, evs, res, {"riposte_dice": 2.0, "die": 5.5}, {"enemy_attacks": 1.0, "enemy_ph": 0.6})
    misses = 16 * 1.0 * 0.4
    want = min(10.0, misses) / 16 * (30.0 + 0.9 * 5.5)
    if abs(r["dmg"] - want) > 1e-9:
        fails.append(f"riposte {r['dmg']} want {want}")
    if abs(few[0]["n"] - 2.0 / 16) > 1e-9:
        fails.append(f"dice cap {few[0]['n']}")
    if model.riposte_event(st, evs, res, {}, {"enemy_attacks": 1.0, "enemy_ph": 0.6}) is not None:
        fails.append("riposte without dice kept")
    st.plan = {"mode": "ranged"}
    if model.riposte_event(st, evs, res, {"riposte_dice": 5.0}, {"enemy_attacks": 1.0, "enemy_ph": 0.6}) is not None:
        fails.append("riposte for a ranged build")
    assert not fails, fails


def test_wrath_storm():
    """Wrath of the Storm: casts per round min(1, enemy attacks x the share in reach x their hit chance), the share
    15/16 in the boss fight, REACH_SHARE["day"] in a day's fights and 1 for a melee build; the save DC on Wisdom with
    the gear's DC bonus kept; the better of the two interrupts' spells; none without the passive (hand formulas,
    stats written here)."""
    import model
    S = {"WrathOfTheStorm": {"Boosts": "UnlockInterrupt(I_L);UnlockInterrupt(I_T)"},
         "I_L": {"Properties": "UseSpell(OBSERVER_SOURCE,T_L,true,true,true)"},
         "I_T": {"Properties": "UseSpell(OBSERVER_SOURCE,T_T,true,true,true)"},
         "T_L": {"SpellType": "Target", "SpellRoll": "not SavingThrow(Ability.Dexterity, SourceSpellDC())",
                 "SpellSuccess": "DealDamage(2d8,Lightning,Magical)", "SpellFail": "DealDamage((2d8)/2,Lightning,Magical)"},
         "T_T": {"SpellType": "Target", "SpellRoll": "not SavingThrow(Ability.Dexterity, SourceSpellDC())",
                 "SpellSuccess": "DealDamage(3d8,Thunder,Magical)", "SpellFail": "DealDamage((3d8)/2,Thunder,Magical)"}}
    st = type("St", (), {})()
    st.W = type("W", (), {})()
    st.W.stats = S
    st.class_passives = ["WrathOfTheStorm"]
    st.plan = {"mode": "caster"}
    st.prof, st.level, st.unknown = 4, 12, set()
    st.mods = {"INT": 5, "WIS": 3}
    st.sheet = {"spell": {"abil": "INT", "dc": 18}}           # 8 + 4 + INT 5 + an item's +1
    E, tgt, dur = {"save": 4}, {"save_pen": 0.0}, {"enemy_attacks": 1.0, "enemy_ph": 0.5}
    fails = []
    pf = (8 + 4 + 3 + 1 - 4 - 1) / 20                         # DC 16 on Wisdom against save +4
    per = pf * 13.5 + (1 - pf) * 6.75                         # Thunder 3d8 beats Lightning 2d8
    with model.scenario("boss"):
        ev, r = model.wrath_event(st, E, [], {}, tgt, dur)
    want = 15 / 16 * 0.5 * per
    if abs(r["dmg"] - want) > 1e-9 or ev["spell_id"] != "T_T" or ev["kind"] != "reaction":
        fails.append(f"boss {ev['spell_id']} {r['dmg']} want T_T {want}")
    ev, r = model.wrath_event(st, E, [], {}, tgt, dur)
    if abs(ev["n"] - model.REACH_SHARE["day"] * 0.5) > 1e-9:
        fails.append(f"day casts {ev['n']}")
    st.plan = {"mode": "melee"}
    ev, r = model.wrath_event(st, E, [], {}, tgt, dict(dur, enemy_attacks=3.0))
    if abs(ev["n"] - 1.0) > 1e-9:
        fails.append(f"one reaction a round: {ev['n']}")
    st.class_passives = []
    if model.wrath_event(st, E, [], {}, tgt, dur) is not None:
        fails.append("wrath without the passive")
    assert not fails, fails


CI_TESTS = [test_condition_reader, test_d20_maths, test_roll_mix, test_stack_average, test_die_gains, test_float_averages,
            test_situational_uptimes, test_projectile_totals, test_party_solver, test_party_threshold, test_target_hp,
            test_buff_spells, test_riposte, test_wrath_storm]


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


def check_local_optimum(out, sample=None, seed=7, always=()):
    """No single-slot change improves an optimized set's score: the definition of the search's end point, checked
    with the candidate lists and the model. A candidate that clashes with another slot replaces that slot's item too
    (two-handed weapon for weapon + shield). An item obtainable now must not improve it at all (the search runs again
    after the owned pass); an earlier-act item may by up to 3% (sets rule: keep it only if it is clearly better)."""
    import search
    W = _world()
    fails, n = [], 0
    sets = [s for s in out["sets"]]
    if sample:
        random.Random(seed).shuffle(sets)
        sets = sets[:sample] + [s for s in sets[sample:] if s["id"] in always]
    for st in sets:
        cid, bid, act = st["char"], st["build"], st["act"]
        sw = (st.get("model") or {}).get("switches") or {}
        lo = {k: v["sid"] for k, v in st["items"].items()}
        S = search.Searcher(W, cid, bid, act, sw, ownership=st.get("ownership", "party"))
        cur = S.score(lo).score
        for slot in search.ORDER:
            for sid in S.cands[slot] + [None]:
                if sid == lo.get(slot):
                    continue
                t = dict(lo)
                if sid is None:
                    t.pop(slot, None)
                else:
                    t = search.place(W, lo, slot, sid)
                    if t is None:
                        continue
                n += 1
                v = S.score(t).score
                owned = sid is not None and W.obtainable(sid, act) == "owned"
                if v > (cur * 1.031 if owned else cur) + 1e-6:
                    fails.append(f"{st['id']} {slot}: {W.items[sid]['name'] if sid else '(empty)'} scores {v:.2f} "
                                 f"> {cur:.2f}")
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
        ("astarion", "thx", 3, "offhand_shot_with_main", 1),     # the off-hand crossbow fires with each main shot
    ]
    outsets = {(s["char"], s["build"], s["act"]): s for s in (out or {}).get("sets", [])
               if s.get("ownership", "party") == "party" and s["id"].endswith(".opt")}
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
        if k == "offhand_shot_with_main":
            # one off-hand shot per main-hand attack (Extra Attack 2, Action Surge a few times) x hit chance x a
            # hand crossbow shot's damage (1d6 + DEX + riders, under 60)
            if not (0 < b - a <= 2.5 * 0.95 * 60):
                fails.append(f"thx CastOffhand switch changes offence by {b - a:.1f} (expected 0-142)")
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


def _stats():
    if "S" not in _CACHE:
        with open(os.path.join(LA, "data", "cache", "stats_resolved.json"), encoding="utf-8") as f:
            _CACHE["S"] = json.load(f)
    return _CACHE["S"]


def _owners():
    with open(os.path.join(LA, "data", "scores", "owners.json"), encoding="utf-8") as f:
        return json.load(f)


def check_ownership(out):
    """Party variant: no item a party owner other than this character holds (owners.json read here: unique items
    by "owners", scarce-material items by their (character, item) pairs)."""
    own = _owners()
    other = {}
    for g in own.values():
        for sid in g["items"]:
            if g["kind"] == "material":
                ok = {c for c, i in g["pairs"] if i == sid}
            else:
                ok = set(g["owners"])
            other.setdefault(sid, set()).update(ok)
    fails, n = [], 0
    for st in out["sets"]:
        if st.get("ownership") != "party":
            continue
        for slot, e in st["items"].items():
            n += 1
            if e["sid"] in other and st["char"] not in other[e["sid"]]:
                fails.append(f"{st['id']} {slot}: {e['name']} belongs to {sorted(other[e['sid']])}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def _passive_boosts(rec):
    S = _stats()
    br = rec.get("boosts_raw") or {}
    txt = br.get("Boosts", "") + ";" + br.get("DefaultBoosts", "")
    for p in (br.get("PassivesOnEquip") or "").split(";"):
        txt += ";" + ((S.get(p.strip()) or {}).get("Boosts") or "")
    return txt


def check_defence(out=None):
    """Boots whose game data makes the wearer immune to Prone / forced movement (StatusImmunity(SG_Prone),
    Attribute(Grounded), read here) take those threats to 0 for a front-liner; boots without them leave them."""
    import model
    W = _world()
    items = _items()
    fails, n = [], 0
    for sid, rec in sorted(items.items()):
        if rec.get("slot") != "Boots" or sid not in W.universe:
            continue
        txt = _passive_boosts(rec)
        prone = "StatusImmunity(SG_Prone)" in txt
        grounded = "Attribute(Grounded)" in txt
        r = model.score(W, "laezel", "bmgiant", 3, {"Boots": sid})
        th = r.dur.get("threats") or {}
        if "knocked prone" not in th:
            fails.append("no threat table in the model")
            break
        n += 1
        if prone != (th["knocked prone"] == 0):
            fails.append(f"{rec['name']}: prone immunity {prone}, model chance {th['knocked prone']}")
        fm = next(v for k, v in th.items() if k.startswith("forced movement"))
        if grounded != (fm == 0):
            fails.append(f"{rec['name']}: Grounded {grounded}, model forced-movement chance {fm}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_wearer_conditions(out=None):
    """A passive gated by BoostConditions on the wearer (Aberration Hunter: githyanki only, read here) works for
    Lae'zel (Githyanki) and not for Gale (Human)."""
    import model
    W = _world()
    S = _stats()
    fails, n = [], 0
    for sid, rec in sorted(_items().items()):
        br = rec.get("boosts_raw") or {}
        for p in (br.get("PassivesOnEquip") or "").split(";"):
            ps = S.get(p.strip()) or {}
            bc = ps.get("BoostConditions") or ""
            if "Tagged('GITHYANKI', context.Source)" not in bc or "Disadvantage(AttackTarget)" not in (ps.get("Boosts")
                                                                                                     or ""):
                continue
            slot = {"Amulet": "Amulet", "Melee Main Weapon": "MainHand"}.get(rec.get("slot"))
            if not slot:
                continue
            n += 1
            g = model.score(W, "gale", "tempestevoker", 1, {slot: sid}).dur["dis"]
            lz = model.score(W, "laezel", "bmgiant", 1, {slot: sid}).dur["dis"]
            if g != 0 or lz <= 0:
                fails.append(f"{rec['name']}: attacker disadvantage Gale {g}, Lae'zel {lz}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_stealth(out=None):
    """Body armour with stealth disadvantage (item data) lowers a Gloom Stalker's chance to open from stealth;
    builds without a stealth subclass never open from stealth."""
    import model
    W = _world()
    items = _items()
    heavy = next(sid for sid, r in sorted(items.items()) if r.get("slot") == "Breast" and
                 (r.get("armour") or {}).get("stealth_disadvantage"))
    light = next(sid for sid, r in sorted(items.items()) if r.get("slot") == "Breast" and r.get("armour") and
                 not (r.get("armour") or {}).get("stealth_disadvantage") and (r["armour"].get("category") == "Light"))
    fails = []
    a = model.score(W, "astarion", "gloomassassin", 3, {"Breast": light}).st.p_open
    b = model.score(W, "astarion", "gloomassassin", 3, {"Breast": heavy}).st.p_open
    if not (0 < b < a):
        fails.append(f"stealth opener: {items[light]['name']} {a}, {items[heavy]['name']} {b}")
    for cid, bid in (("laezel", "bmgiant"), ("gale", "tempestevoker")):
        if model.score(W, cid, bid, 3, {"Breast": light}).st.p_open != 0:
            fails.append(f"{cid}.{bid} opens from stealth")
    return fails, 3


def check_action_economy(out):
    """Optimized caster sets: a per-rest item spell is cast at most its per-rest uses (Cooldown read here: once per
    short rest = 3 windows, once per rest = 1) over the 16 rounds of a long rest, and the round's action spells
    (item spells, levelled spells, Radiance of the Dawn) fit in one action."""
    import model
    W = _world()
    S = _stats()
    fails, n = [], 0
    for st in out["sets"]:
        if model.PLANS.get(st["build"], {}).get("mode") != "caster" or st.get("ownership") != "party":
            continue
        lo = {k: v["sid"] for k, v in st["items"].items()}
        r = model.score(W, st["char"], st["build"], st["act"], lo, detail=True)
        acts = 0.0
        for e in r.plan_events:
            n += 1
            if e["name"].startswith("item spell"):
                cd = (S.get(e["spell"]) or {}).get("Cooldown") or ""
                uses = 3 if "ShortRest" in cd else 1
                if e["n"] > uses / 16 + 1e-9:
                    fails.append(f"{st['id']} {e['name']} {e['spell']}: {e['n']:.3f} casts a round > {uses}/16")
                if e.get("cost") == "action":
                    acts += e["n"]
            elif e["name"] in ("levelled spell", "Radiance of the Dawn"):
                acts += e["n"]
        if acts > 1 + 1e-9:
            fails.append(f"{st['id']}: {acts:.2f} action spells a round")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_dead_shot(out=None):
    """The Dead Shot's crit-range passive has no condition in the game data (read here), so it applies to every
    attack roll of the wearer - a melee attack included."""
    import model
    W = _world()
    S = _stats()
    rec = next(r for r in _items().values() if r.get("name") == "The Dead Shot")
    ps = [S.get(p.strip()) or {} for p in (rec["boosts_raw"].get("PassivesOnEquip") or "").split(";")]
    crit = [p for p in ps if "ReduceCriticalAttackThreshold" in (p.get("Boosts") or "")]
    fails = []
    if not crit or "IF(" in crit[0]["Boosts"] or crit[0].get("BoostConditions"):
        return ["The Dead Shot's crit passive is conditional in the data - expectation changed"], 1
    st = model.State(W, "laezel", "bmgiant", 3, {"Ranged": rec["stats_id"]}, None)
    ev = dict(kind="weapon", weapon=True, melee=True, ranged=False, attack_roll=True, slot="MainHand",
              attack_type="MeleeWeaponAttack", dtypes={"Slashing"})
    m = model.event_mods(st, ev, model.all_extra_boosts(st, []), model.lmv_names(st))
    if abs(m["crit_red"] - 1.0) > 1e-9:
        fails.append(f"melee attack with The Dead Shot in the ranged slot: crit range -{m['crit_red']}")
    return fails, 1


def check_weapon_riders(out=None):
    """An ability-modifier rider counts once per hit: Balduran's Giantslayer (its "StrengthModifier Slashing" rider
    read here from the item record) hits for its dice + enchantment + the STR modifier twice, no more."""
    import model
    W = _world()
    rec = next(r for r in _items().values() if r.get("name") == "Balduran's Giantslayer")
    w = W.items[rec["stats_id"]]["weapon"]
    if "StrengthModifier Slashing" not in (w.get("extra_damage") or []):
        return ["Balduran's Giantslayer has no StrengthModifier rider in the data - expectation changed"], 1
    nd, sides = (int(x) for x in w["damage"].split("d"))
    st = model.State(W, "laezel", "bmgiant", 3, {"MainHand": rec["stats_id"]}, None)
    evs, _special = model.make_weapon_events(st)
    main = next(e for e in evs if e.get("name") == "attack")
    want = nd * (sides + 1) / 2 + w["enchantment"] + 2 * st.mods["STR"]
    if abs(main["base_dmg"] - want) > 1e-9:
        return [f"Giantslayer hit before conditional boosts: {main['base_dmg']}, want {want} (STR {st.mods['STR']:+d} "
                f"twice)"], 1
    return [], 1


def check_plan_toggles(out=None):
    """A test plan lists the toggled passives its attacks assume (the harness sets them; a character can have them
    off): each is a toggle in the game stats (read here) and is listed exactly when the model's attacks used it.
    Lae'zel with Balduran's Giantslayer swings with Great Weapon Master's -5 / +10; Gale has no such passive."""
    import gauntlet
    import model
    W = _world()
    S = _stats()
    gs = next(r for r in _items().values() if r.get("name") == "Balduran's Giantslayer")["stats_id"]
    fails = []
    for cid, bid, lo, want in (("laezel", "bmgiant", {"MainHand": gs}, ["GreatWeaponMaster_BonusDamage"]),
                               ("gale", "tempestevoker", {}, [])):
        r = model.score(W, cid, bid, 3, lo, None, detail=True)
        got = gauntlet.test_plan(W, r, "check", lo, "research")["toggles"]
        if got != want:
            fails.append(f"{cid} {bid}: toggles {got}, want {want}")
        for t in got:
            if "IsToggled" not in ((S.get(t) or {}).get("Properties") or ""):
                fails.append(f"{cid} {bid}: {t} is not a toggled passive in the game stats")
    return fails, 2


def check_scenario(out=None):
    """model.scenario("boss") scores the gauntlet's boss fight (expectations from its rules, not the code): one
    enemy, so an area spell (Fireball, radius read here from the stats) hits one target and nothing chains; one
    16-round fight with no short rest, so a Fighter 12's Action Surge adds its 3 attacks once in 16 rounds; Scabby
    Pugilist Circlet's "2 enemies within 3 m" never holds; the enemy attacks once a round at half damage (17 -> 9,
    one d20 enumerated here vs the model's AC); Markoheshkir's once-per-short-rest spells (cooldown read here) once
    in 16 rounds; and the day's numbers are the same before and after the block."""
    import mech
    import model
    W = _world()
    S = _stats()
    gs = next(r for r in _items().values() if r.get("name") == "Balduran's Giantslayer")["stats_id"]
    scabby = next(r for r in _items().values() if r.get("name") == "Scabby Pugilist Circlet")["stats_id"]
    fails, n = [], 0
    lo = {"MainHand": gs, "Helmet": scabby}

    def numbers():
        st = model.State(W, "laezel", "bmgiant", 3, lo, None)
        evs, _sp = model.make_weapon_events(st)
        main = next(e for e in evs if e.get("name") == "attack")
        mods = model.event_mods(st, main, model.all_extra_boosts(st, []), model.lmv_names(st))
        fb = mech.read_spell(W, "Projectile_Fireball", 12)
        r = model.score(W, "laezel", "bmgiant", 3, lo, None)
        gale = model.State(W, "gale", "tempestevoker", 3, {"MainHand": "MAG_TheChromatic_Staff"}, None,
                           {"MainHand": "MAG_LEGENDARY_CHROMATIC_ATTUNEMENT_LIGHTNING"})
        sr = [e["n"] for e in model.item_spell_events(gale)
              if S[e["spell_id"]].get("Cooldown") == "OncePerShortRest"]
        return main["n"], mods["flat"], fb["targets"] + fb["chain"], r, sr
    day = numbers()
    with model.scenario("boss"):
        boss = numbers()
    again = numbers()
    if float(S["Projectile_Fireball"].get("ExplodeRadius") or 0) > 1 and day[2] <= 1:
        fails.append(f"day: Fireball hits {day[2]} targets")
    want = {"attacks a round (3 + Action Surge once)": (boss[0], 3 + 3 / 16),
            "Scabby Pugilist +2": (boss[1], 0.0), "Fireball targets": (boss[2], 1.0)}
    for k, (got, w) in want.items():
        n += 1
        if abs(got - w) > 1e-9:
            fails.append(f"boss {k}: {got}, want {w}")
    n += 1
    if not boss[4] or any(abs(x - 1 / 16) > 1e-9 for x in boss[4]):
        fails.append(f"boss: Markoheshkir's once-per-short-rest spells {boss[4]} a round, want 1/16 each")
    if day[1] < 2.0 - 1e-9:
        fails.append(f"day: Scabby Pugilist +2 read as {day[1]} for a melee build")
    ac = boss[3].dur["ac"]
    want_taken = _enum_hit(model.ENEMY[3]["atk"], ac, 0) * 9 + 0.05 * 9 * 0.5
    if abs(boss[3].dur["incoming"] - want_taken) > 1e-6:
        fails.append(f"boss damage taken {boss[3].dur['incoming']:.3f}, want {want_taken:.3f} (AC {ac})")
    if (day[0], day[1], day[2], day[3].dpr, day[3].score, day[4]) != (again[0], again[1], again[2], again[3].dpr,
                                                                       again[3].score, again[4]):
        fails.append(f"day numbers changed by the boss block: {day[3].dpr} -> {again[3].dpr}")
    return fails, n + 2


_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}


def check_respec(out, sample=None, plans=None):
    """Tuned respecs: re-scored here, never below the planned build with the same gear; the exported per-level
    picks obey the point-buy rules (27 points, 8-15, racial +2 / +1 on two abilities) and keep the build's class
    sequence (Builds.lua parsed here)."""
    import model
    import gamedata
    W = _world()
    plans = plans or _plans()
    builds, _o = gamedata.builds_lua(BUILDS_LUA)
    fails, n = [], 0
    ps = plans["plans"] if not sample else plans["plans"][:sample]
    for p in ps:
        n += 1
        lo = {k: v["id"] for k, v in p["gear"].items()}
        rs = p["respec"]
        pl = rs["per_level"]
        if not pl or pl[0]["level"] != 0:
            fails.append(f"{p['id']}: no point buy")
            continue
        pb = {}
        rac = {}
        for x in pl[0]["picks"]:
            m = re.match(r"Point buy (\d+) (\w+)", x)
            if m:
                pb[m.group(2)] = int(m.group(1))
            m = re.match(r"Racial \+(\d) (\w+)", x)
            if m:
                rac[m.group(2)] = int(m.group(1))
        if len(pb) != 6 or any(not 8 <= v <= 15 for v in pb.values()) or sum(_COST[v] for v in pb.values()) > 27:
            fails.append(f"{p['id']}: point buy {pb}")
        if sorted(rac.values()) != [1, 2]:
            fails.append(f"{p['id']}: racial bonus {rac}")
        seq = [x["class"] for x in pl[1:]][:p["level"]]
        if seq != p["level_sequence"]:
            fails.append(f"{p['id']}: class sequence changed")
        if rs["tuned"]:
            # rebuild the respec from the export alone and score it
            base = {k: pb[k] + rac.get(k, 0) for k in pb}
            feats = []
            for x in pl[1:]:
                for pk in x["picks"]:
                    m = re.match(r"Feat: Ability Improvement (.*)", pk)
                    if m:
                        asi = {k: int(v) for v, k in re.findall(r"\+(\d) (\w+)", m.group(1))}
                        feats.append({"n": "Ability Improvement " + m.group(1), "lv": x["level"], "asi": asi})
                    elif pk.startswith("Feat: "):
                        m2 = re.match(r"Feat: ([^(]+?)(?: \(\+1 (\w+)\))?$", pk)
                        asi = {m2.group(2): 1} if m2.group(2) else {}
                        feats.append({"n": m2.group(1), "lv": x["level"], "asi": asi})
            BI = W.build_input(p["char"], p["build"])
            for f in feats:
                for k, v in f["asi"].items():
                    base[k] += v
            styles = [pk.split(": ", 1)[1] for x in pl[1:] for pk in x["picks"] if pk.startswith("Fighting Style: ")]
            cant = next((pk.split(": ", 1)[1] for x in pl[1:] for pk in x["picks"] if pk.startswith("Cantrip: ")),
                        None)
            r = {"base": base, "feats": feats, "styles": styles or list(BI["styles"]), "cantrip": cant,
                 "key": "test:" + p["id"]}
            tuned = model.score(W, p["char"], p["build"], p["act"], lo, respec=r).score
        else:
            tuned = model.score(W, p["char"], p["build"], p["act"], lo).score
        untuned = model.score(W, p["char"], p["build"], p["act"], lo).score
        if tuned < untuned - 1e-6:
            fails.append(f"{p['id']}: tuned {tuned:.2f} < planned {untuned:.2f}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def _plans(path=None):
    path = path or os.path.join(OPT, ".cache", "test_plans.json")
    if "P" not in _CACHE or path != _CACHE.get("P_path"):
        with open(path, encoding="utf-8") as f:
            _CACHE["P"] = json.load(f)
        _CACHE["P_path"] = path
    return _CACHE["P"]


def check_test_plans(out):
    """Every party optimized set and every research set has a test plan; every action id is a spell in the game
    stats (read here); gear ids are items."""
    S = _stats()
    items = _items()
    P = _plans()
    ids = {p["id"] for p in P["plans"]}
    fails, n = [], 0
    for st in out["sets"]:
        if st.get("ownership") == "party" and ".opt." not in st["id"] + "." and st["id"] not in ids:
            fails.append(f"no test plan for {st['id']}")
    for p in P["plans"]:
        n += 1
        for rd in p["rounds"]:
            for a in rd["actions"]:
                if a["id"] not in S:
                    fails.append(f"{p['id']} round {rd['round']}: unknown action {a['id']}")
        for slot, g in p["gear"].items():
            if g["id"] not in items:
                fails.append(f"{p['id']} {slot}: unknown item {g['id']}")
    if P.get("format") != "loot-advisor-test-plan/1":
        fails.append(f"format {P.get('format')}")
    if n == 0:
        fails.append("nothing to check")
    return fails, n


def check_party(out):
    """Party assignment (out["party"]): per ownership variant and act, no unique item (data/items_all read here) in
    two characters' final loadouts; every unique item that several characters' optimized sets use (counted here
    from out["sets"]) was assigned to one of them; every final loadout passes the set rules and, for the party
    variant, the owner rulings; scores re-computed with the model; nobody gains from losing an item (beyond the
    keep-it-if-owned margin), and the party total is the sum of the per-character means."""
    import model
    items = _items()
    W = _world()
    fails, n = [], 0
    for r in out.get("party") or []:
        own, act = r["ownership"], r["act"]
        sets = [s for s in out["sets"] if s.get("ownership") == own and s["act"] == act and
                s["id"].endswith(".opt" + ("" if own == "party" else ".free"))]
        users = {}
        for st in sets:
            for e in st["items"].values():
                if items.get(e["sid"], {}).get("unique"):
                    users.setdefault(e["sid"], set()).add(st["char"])
        for sid, cs in users.items():
            if len(cs) > 1 and r["assign"].get(sid) not in cs:
                fails.append(f"{own} A{act}: {sid} used by {sorted(cs)} assigned to {r['assign'].get(sid)}")
        # the last pass only settles items repaired sets picked up later; an assigned item still shared means the
        # losers kept it
        for sid in set(r.get("settled_last") or []) & set(r["assign"]):
            fails.append(f"{own} A{act}: assigned item {sid} still shared after the rounds")
        th = r.get("threshold")
        for sid, k in (r.get("kept_by_threshold") or {}).items():
            if r["assign"].get(sid) != k["owner"] or k["margin"] is None or k["margin"] >= th:
                fails.append(f"{own} A{act}: {sid} kept by threshold but {r['assign'].get(sid)} / margin "
                             f"{k['margin']} (owner {k['owner']})")
        for sid, (o, _basis) in (r.get("owner_rule") or {}).items():
            if o is not None and r["assign"].get(sid) != o:
                k = (r.get("moved") or {}).get(sid)
                if not k or k["pick"] != r["assign"][sid] or (k["margin"] is not None and k["margin"] < th):
                    fails.append(f"{own} A{act}: {sid} left its owner {o} for {r['assign'][sid]} without a "
                                 f"margin of {th}: {k}")
        final, pseudo, per_char = {}, [], {}
        for b in r["builds"]:
            n += 1
            for sid in b["loadout"].values():
                if items.get(sid, {}).get("unique"):
                    final.setdefault(sid, set()).add(b["char"])
            pseudo.append({"id": f"party.{own}.{b['char']}.{b['build']}.a{act}", "char": b["char"],
                           "build": b["build"], "act": act, "ownership": own,
                           "items": {k: {"sid": v, "name": items.get(v, {}).get("name", v)}
                                     for k, v in b["loadout"].items()}})
            sw = next(((s.get("model") or {}).get("switches") or {} for s in sets
                       if s["char"] == b["char"] and s["build"] == b["build"]), {})
            v = model.score(W, b["char"], b["build"], act, b["loadout"], sw).score
            if abs(v - b["score_after"]) > 0.01 + 1e-4 * v:
                fails.append(f"{own} A{act} {b['char']} {b['build']}: model {v:.2f} != reported {b['score_after']}")
            # the keep-it-if-owned rule may leave an optimized set up to 3% short of its best single swap (the same
            # margin as the local-optimum check), so a repair can come out that much ahead; more is a solver bug
            if b["score_after"] > b["score_before"] * 1.031 + 0.01:
                fails.append(f"{own} A{act} {b['char']} {b['build']}: gains by losing ({b['score_before']} -> "
                             f"{b['score_after']})")
            per_char.setdefault(b["char"], []).append(b["score_after"])
        for sid, cs in final.items():
            if len(cs) > 1:
                fails.append(f"{own} A{act}: unique {items[sid]['name']} still with {sorted(cs)}")
        tot = sum(sum(v) / len(v) for v in per_char.values())
        if abs(tot - r["total"]) > 0.05:
            fails.append(f"{own} A{act}: total {r['total']} != sum of character means {tot:.2f}")
        fails += [f"{own} A{act} " + f for f in check_set_rules({"sets": pseudo})[0]]
        if own == "party":
            fails += [f"A{act} " + f for f in check_ownership({"sets": pseudo})[0]]
    if n == 0:
        fails.append("nothing to check")
    return fails, n


PARALLEL_SUBSET = "karlach:giants:1,wyll:lockadin:1,laezel:bmgiant:1"


def _strip_timing(x):
    if isinstance(x, dict):
        return {k: _strip_timing(v) for k, v in x.items() if k not in ("secs", "generated", "peak_mb")}
    if isinstance(x, list):
        return [_strip_timing(v) for v in x]
    return x


def check_jobs_parallel(_out=None, only=PARALLEL_SUBSET):
    """run.py --jobs 1 and --jobs 2 on a small subset (three Act 1 builds that contest unique items, both ownership
    variants so the party step also runs in workers) write the same optimized.json and test_plans.json, timings
    aside; each run goes to its own scratch cache directory."""
    import contextlib
    import io
    import run as R
    got, fails = {}, []
    for n in (1, 2):
        d = tempfile.mkdtemp(prefix=f"opt_jobs{n}_")
        old = R.CACHE
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                R.main(["--only", only, "--jobs", str(n), "--no-switches", "--cache", d])
            got[n] = {}
            for name in ("optimized.json", "test_plans.json"):
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    got[n][name] = _strip_timing(json.load(f))
            got[n]["jobs"] = sorted(os.listdir(os.path.join(d, "jobs")))
        finally:
            R.set_cache(old)
            shutil.rmtree(d, ignore_errors=True)
    for k in got[1]:
        if got[1][k] != got[2][k]:
            fails.append(f"{k}: --jobs 1 and --jobs 2 differ")
    if len(got[1]["jobs"]) != len(only.split(",")):
        fails.append(f"job files {got[1]['jobs']}")
    if not got[1]["optimized.json"].get("party"):
        fails.append("no party assignment in the subset")
    return fails, len(got[1]["optimized.json"].get("sets") or [])


def check_plan_gaps(out=None):
    """The plan gaps in the boss fight (expectations from the game data and the gauntlet's rules): a Gloom Stalker
    with a melee off-hand weapon attacks with it in a free bonus action once the boss stands in reach (not in the
    day's fights: a ranged build keeps its distance); Gale (Tempest Evoker) with every slot of one fight spends the
    level 1-2 slots too, holds Wall of Fire when its ticks beat one nuke and answers the boss's hits with Wrath of the
    Storm; a Battle Master whose every attack has
    Advantage (Risky Ring) plans no Trip and ripostes instead. The day's numbers are the same before and after."""
    import model
    W = _world()
    fails, n = [], 0
    names = {r.get("name"): r["stats_id"] for r in _items().values()}
    ast = {"Ranged": names["Gontr Mael"], "MainHand": names["Ambusher"], "OffHand": names["Blade of the First Blood"]}
    gale = {"MainHand": "MAG_TheChromatic_Staff"}
    risky = {"MainHand": names["Balduran's Giantslayer"], "Ring1": names["Risky Ring"]}

    def ev(cid, bid, lo, boss):
        if boss:
            with model.scenario("boss"):
                r = model._evaluate(W, cid, bid, 3, lo, None, True, None)
        else:
            r = model._evaluate(W, cid, bid, 3, lo, None, True, None)
        return {e["name"]: e for e in r.plan_events}, r.dpr
    day_before = ev("astarion", "gloomassassin", ast, False)[1]
    a_boss, _ = ev("astarion", "gloomassassin", ast, True)
    a_day, day_after = ev("astarion", "gloomassassin", ast, False)
    n += 3
    if not (a_boss.get("off-hand attack") or {}).get("n"):
        fails.append("boss: no off-hand attack for a ranged build in reach of the boss")
    if (a_day.get("off-hand attack") or {}).get("n"):
        fails.append("day: a ranged build's off-hand melee attack counted")
    if abs(day_before - day_after) > 1e-9:
        fails.append(f"day changed by the boss block: {day_before} -> {day_after}")
    buff = next((e for e in a_boss.values() if e.get("spell") == "Shout_MAG_Victory_Longbow_Haste"), None)
    n += 1
    if not buff or buff.get("dropped") or not buff.get("n"):
        fails.append(f"boss: Gontr Mael's Haste not kept: {buff}")
    g_boss, _ = ev("gale", "tempestevoker", gale, True)
    n += 2
    if not (g_boss.get("concentration damage") or {}).get("n"):
        fails.append("boss: no concentration damage zone for Gale")
    if not (g_boss.get("filler spell") or {}).get("n"):
        fails.append("boss: Gale's level 1-2 slots unspent")
    n += 1
    if not (g_boss.get("Wrath of the Storm") or {}).get("dmg"):
        fails.append("boss: no Wrath of the Storm for a Tempest Cleric")
    l_boss, _ = ev("laezel", "bmgiant", risky, True)
    n += 2
    if (l_boss.get("attack") or {}).get("adv", 0) < model.ADV_SURE:
        fails.append(f"Risky Ring: Advantage {l_boss.get('attack')}")
    if not (l_boss.get("Riposte") or {}).get("n"):
        fails.append("boss: no Riposte with every attack's Advantage sure")
    return fails, n


def check_boss_tactics(out=None):
    """The boss fight's reach rules (expectations from the game's rules, not the code), on Astarion thx Act 3 set 1
    (Risky Ring's Advantage on every attack, a Thief with two bonus actions, Hunter's Mark, dual hand crossbows):
    standing, every ranged roll has Disadvantage in the 15 of 16 turns the boss is in reach, which cancels the ring's
    Advantage there (net Advantage 1/16 of the rolls), and Sneak Attack, with no ally, needs that net Advantage, so it
    stays under the dice on each turn with an advantaged roll; leaving (Disengage and a move out of reach in those
    turns; no Hide, which the lit arena in the boss's sight does not allow) takes one bonus action there, leaving
    2 - 1/16 (Hunter's Mark) - 15/16 off-hand shots a round, and no roll has Disadvantage; the evaluation keeps the
    better of the two, which here is leaving (three shots with Advantage and Sneak Attack beat four straight ones),
    also with the off-hand-shot switch on (each main-hand shot fires the off-hand crossbow for free). The elixir's 1d4 (Elixir of the Colossus) doubles on a critical
    hit; Hunter's Mark's 1d6 from round 2 on every hit, twice on a critical one. In a day's fights no Disadvantage, and
    the day is the same before and after the boss block."""
    import model
    W = _world()
    fails, n = [], 0
    ref = next((s_ for s_ in W.research_sets("astarion", "thx", 3) if s_.get("id") == "astarion.thx.a3.1"), None)
    if not ref:
        return ["astarion.thx.a3.1 not found"], 1
    lo = {k: v["sid"] for k, v in (ref.get("items") or {}).items() if v and v.get("sid") and v["sid"] in W.items}

    def tac(t, sw=None):
        with model.scenario("boss"):
            return model._evaluate_tactic(W, "astarion", "thx", 3, lo, sw, True, None, None, t)
    day0 = model._evaluate(W, "astarion", "thx", 3, lo, None, True, None)
    stand, evade = tac("stand"), tac("evade")
    with model.scenario("boss"):
        best = model._evaluate(W, "astarion", "thx", 3, lo, None, True, None)
        on = model._evaluate(W, "astarion", "thx", 3, lo, {"offhand_shot_with_main": True}, True, None)
    day1 = model._evaluate(W, "astarion", "thx", 3, lo, None, True, None)
    ps, pe = stand.parts, evade.parts
    n += 4
    if abs(ps["dis_any_rate"] - 15 / 16) > 1e-3 or abs(ps["adv_rate"] - 1 / 16) > 1e-3:
        fails.append(f"stand: Disadvantage {ps['dis_any_rate']}, net Advantage {ps['adv_rate']}, want 15/16, 1/16")
    sad = 7.0                                        # Rogue 4: 2d6
    bound = sad * 2 * (1 - (1 - ps["adv_rate"]) ** ps["attacks"])
    if stand.sneak > bound + 1e-6:
        fails.append(f"stand: Sneak Attack {stand.sneak:.2f} above {bound:.2f} (needs net Advantage, no ally)")
    if pe["dis_any_rate"] > 1e-9 or pe["adv_rate"] < 1 - 1e-9:
        fails.append(f"evade: Disadvantage {pe['dis_any_rate']}, Advantage {pe['adv_rate']}")
    off = {e["name"]: e for e in evade.plan_events}
    if abs((off.get("off-hand shot") or {}).get("n", -1) - (2 - 1 / 16 - 15 / 16)) > 1e-3 or \
            "evade" not in off or off["evade"].get("hide"):
        fails.append(f"evade: off-hand shots {(off.get('off-hand shot') or {}).get('n')}, evade {off.get('evade')}")
    n += 2
    if abs(best.dpr - max(stand.dpr, evade.dpr)) > 1e-9 or best.tactic != "evade":
        fails.append(f"tactic: {best.dpr:.2f} kept of stand {stand.dpr:.2f} / evade {evade.dpr:.2f}")
    on_ev = {e["name"]: e for e in on.plan_events}
    att = (on_ev.get("attack") or {}).get("n")
    if on.tactic != "evade" or abs((on_ev.get("off-hand shot with the main hand") or {}).get("n", -1) - (att or 0)) > 1e-9 \
            or "off-hand shot with the main hand" in {e["name"] for e in best.plan_events}:
        fails.append(f"switch: tactic {on.tactic}, main-hand off-hand shots {on_ev.get('off-hand shot with the main hand')}")
    n += 2
    st = model.State(W, "astarion", "thx", 3, lo, None)
    evs, _sp = model.make_weapon_events(st)
    main = next(e for e in evs if e.get("name") == "attack")
    m = model.event_mods(st, main, model.all_extra_boosts(st, []), model.lmv_names(st))
    elixir = (W.items.get(lo.get("Elixir") or "") or {}).get("name") or ""
    if "Colossus" in elixir and abs(m["sheet_dice"] - 2.5) > 1e-9:
        fails.append(f"crit dice: the elixir's 1d4 on a critical hit {m['sheet_dice']}, want 2.5 ({elixir})")
    elif "Colossus" not in elixir:
        fails.append(f"crit dice: set 1 has no Elixir of the Colossus ({elixir})")
    rest = stand.dpr - sum(e["dmg"] for e in stand.plan_events) - stand.extra - stand.sneak - stand.tgt["dot"]
    want = 15 / 16 * 3.5 * (ps["hits"] + ps["crits"])
    if abs(rest - want) > 0.1:
        fails.append(f"Hunter's Mark {rest:.2f}, want {want:.2f} (1d6 a hit, twice on a critical one)")
    n += 2
    if (day0.parts or {}).get("dis_any_rate"):
        fails.append(f"day: Disadvantage {day0.parts}")
    if (day0.dpr, day0.score) != (day1.dpr, day1.score):
        fails.append(f"day changed by the boss block: {day0.dpr} -> {day1.dpr}")
    return fails, n


# a weapon + shield set that could not become two-handed, and a chest picked around gloves the owned pass removed
LOCAL_OPT_ALWAYS = ("wyll.lockadin.a2.opt", "gale.tempestevoker.a3.opt.free")

LOCAL_CHECKS = [("coverage", check_coverage), ("set rules vs game data", check_set_rules),
                ("research sets never beat the optimizer", check_research_not_better),
                ("why text has no leaks", check_why_text), ("switches", check_switches),
                ("local optimum (sample of 6 sets + two that once missed one)",
                 lambda o: check_local_optimum(o, sample=6, always=LOCAL_OPT_ALWAYS)),
                ("party ownership", check_ownership), ("defensive value (status immunities)", check_defence),
                ("wearer conditions (BoostConditions)", check_wearer_conditions),
                ("stealth openers", check_stealth), ("action economy of item spells", check_action_economy),
                ("The Dead Shot crit range", check_dead_shot),
                ("weapon ability-modifier rider counted once", check_weapon_riders),
                ("test plans list the toggles the model assumes", check_plan_toggles),
                ("boss scenario: one target, one fight, half-damage attacks", check_scenario),
                ("plan gaps in the boss fight (off-hand, buffs, slots, Wall of Fire, Riposte, Wrath of the Storm)", check_plan_gaps),
                ("boss fight reach: Disadvantage, evading, Sneak Attack alone, crit dice, CastOffhand switch",
                 check_boss_tactics),
                ("respec tuning (re-scored, point-buy rules)", lambda o: check_respec(o, sample=40)),
                ("test plans", check_test_plans), ("party assignment of unique items", check_party),
                ("--jobs 1 and --jobs 2 give the same outputs", check_jobs_parallel)]


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


def _optimize_set(cid, bid, act, switches=None, ownership="party"):
    import run as R
    W = _world()
    o = R.optimize(W, cid, bid, act, switches, ownership=ownership)
    st = R.to_set(W, o)
    return {"char": cid, **st}


def mutations():
    """-> [(description, test function, expect 'red')]. Each mutation is undone after its check."""
    import mech
    import model
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

    def m_float():
        old = mech.float_eval
        mech.float_eval = lambda e, n: (lambda v: None if v is None else float(int(v)))(old(e, n))
        try:
            test_float_averages()
            return []
        except AssertionError as e:
            return [str(e)]
        finally:
            mech.float_eval = old
    out.append(("dice averages rounded down", m_float))

    def m_beams():
        old = mech.parse_boosts
        src = mech.read_spell

        def no_total(W_, sid, level, slot_level=None):
            r = src(W_, sid, level, slot_level)
            sp = W_.stats.get(sid) or {}
            ta = str(sp.get("AmountOfTargets") or "")
            if r and ta.isdigit():
                r["beams"] = float(ta)               # every tooltip read per projectile
            return r
        mech.read_spell = no_total
        try:
            test_projectile_totals()
            return []
        except AssertionError as e:
            return [str(e)]
        finally:
            mech.read_spell = src
            mech.parse_boosts = old
    out.append(("all-projectile tooltips counted per projectile", m_beams))

    def m_uptime():
        m = _model()
        old = m.persist_uptime
        m.persist_uptime = lambda rate, horizon=16: min(1.0, rate * horizon)
        try:
            test_situational_uptimes()
            return []
        except AssertionError as e:
            return [str(e)]
        finally:
            m.persist_uptime = old
    out.append(("until-rest uptime as min(1, rate x day)", m_uptime))

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

    def m_owner():
        old = W.blocked
        W.blocked = lambda sid, cid: None            # ownership ignored
        try:
            st = _optimize_set("astarion", "thx", 3)
        finally:
            W.blocked = old
        return check_ownership({"sets": [st]})[0]
    out.append(("party ownership ignored (astarion thx Act 3 re-optimized)", m_owner))

    def m_immunity():
        old = model.THREATS
        model.THREATS = [(t[0], (), *t[2:]) for t in old]   # status immunities no longer read
        model._R0.clear()
        try:
            return check_defence()[0]
        finally:
            model.THREATS = old
            model._R0.clear()
    out.append(("status immunities ignored by the defence model", m_immunity))

    def m_wearer():
        old = mech._tagged
        mech._tagged = lambda c, a: float(getattr(c.st, "enemy_types", {}).get((a[0] if a else "").upper(), 0.0))
        try:
            return check_wearer_conditions()[0]
        finally:
            mech._tagged = old
    out.append(("Tagged(.., context.Source) read as the enemy", m_wearer))

    def m_stealth():
        old = model.stealth_p
        model.stealth_p = lambda bonus, dc, adv=0.0, dis=0.0: old(bonus, dc, adv, 0.0)
        try:
            return check_stealth()[0]
        finally:
            model.stealth_p = old
    out.append(("armour stealth disadvantage ignored", m_stealth))

    def m_items():
        old = model.item_spell_events

        def per_round(st):
            evs = old(st)
            for ev in evs:
                ev["n"] *= 16 / 3                    # per-rest spell counted every round
            return evs
        model.item_spell_events = per_round
        model._CHOICE.clear()
        try:
            return check_action_economy(_output())[0]
        finally:
            model.item_spell_events = old
            model._CHOICE.clear()
    out.append(("per-rest item spells counted per round", m_items))

    def m_deadshot():
        old = model.all_extra_boosts

        def scoped(st, dyn):
            return [b if b[2] != "ReduceCriticalAttackThreshold" else b[:5] + ("Ranged",) + b[6:] for b in old(st, dyn)]
        model.all_extra_boosts = scoped
        try:
            return check_dead_shot()[0]
        finally:
            model.all_extra_boosts = old
    out.append(("The Dead Shot's crit range only on its own weapon", m_deadshot))

    def m_rider_twice():
        old = model.make_weapon_events

        def twice(st):
            evs, special = old(st)
            for ev in evs:
                if ev.get("slot") == "MainHand":
                    ev["base_dmg"] += max(0, st.mods.get("STR", 0))     # the sheet's rider added again
            return evs, special
        model.make_weapon_events = twice
        try:
            return check_weapon_riders()[0]
        finally:
            model.make_weapon_events = old
    out.append(("weapon ability-modifier rider counted twice", m_rider_twice))

    def m_no_toggles():
        import gauntlet
        old = gauntlet.TOGGLES
        gauntlet.TOGGLES = ()
        try:
            return check_plan_toggles()[0]
        finally:
            gauntlet.TOGGLES = old
    out.append(("test plans drop the toggles the model assumes", m_no_toggles))

    def m_scenario_targets():
        old = model.SCENARIOS["boss"]["enemies"]
        model.SCENARIOS["boss"]["enemies"] = 4                 # area spells still hit the day's enemies
        try:
            return check_scenario()[0]
        finally:
            model.SCENARIOS["boss"]["enemies"] = old
    out.append(("boss scenario keeps the day's enemy count", m_scenario_targets))

    def _ci(t):
        try:
            t()
            return []
        except AssertionError as e:
            return [str(e)]

    def m_target_hp():
        old = model.SCENARIOS["boss"]["target_hp_pct"]
        model.SCENARIOS["boss"]["target_hp_pct"] = None       # the boss treated as a day's enemy
        try:
            return _ci(test_target_hp)
        finally:
            model.SCENARIOS["boss"]["target_hp_pct"] = old
    out.append(("boss scenario: the enemy's 99% not assumed", m_target_hp))

    def m_strict():
        old = mech.PREDICATES["HasHPPercentageLessThan"]
        mech.PREDICATES["HasHPPercentageLessThan"] = mech._hp_le     # "less than 99" read as "99 or less"
        try:
            return _ci(test_target_hp)
        finally:
            mech.PREDICATES["HasHPPercentageLessThan"] = old
    out.append(("target hit points: less than read as equal or less", m_strict))

    def m_buff_cost():
        old = model.buff_events

        def bad(st, evs, results, special, hits):
            out_ = old(st, evs, results, special, hits)
            for ev, r in out_:                      # the cast's action not paid
                a = st.sheet["nAtt"] * results[0]["dmg"] / evs[0]["n"]
                ev["gain_per_cast"] = round(ev["gain_per_cast"] + a, 2)
            return out_
        model.buff_events = bad
        try:
            return _ci(test_buff_spells)
        finally:
            model.buff_events = old
    out.append(("buff spells: the cast's action not paid", m_buff_cost))

    def m_lethargy():
        old = mech.item_buff

        def bad(S, sid):
            s2 = {k: (dict(v, OnRemoveFunctors="") if isinstance(v, dict) else v) for k, v in S.items()}
            return old(s2, sid)
        mech.item_buff = bad
        try:
            return _ci(test_buff_spells)
        finally:
            mech.item_buff = old
    out.append(("buff spells: a lethargy ignored", m_lethargy))

    def m_riposte_cap():
        old = model.riposte_event

        def bad(st, evs, results, special, dur):
            return old(st, evs, results, special, dict(dur, enemy_ph=0.0))     # every enemy attack a miss
        model.riposte_event = bad
        try:
            return _ci(test_riposte)
        finally:
            model.riposte_event = old
    out.append(("riposte: not capped by the enemy's misses", m_riposte_cap))

    def m_wrath_dc():
        old = model.wrath_event

        def bad(st, E, boosts, names, tgt, dur):
            sp = st.sheet["spell"]
            st2 = type("St", (), dict(vars(st), mods=dict(st.mods, WIS=st.mods[sp["abil"]])))()
            return old(st2, E, boosts, names, tgt, dur)       # the sheet's casting ability for the DC
        model.wrath_event = bad
        try:
            return _ci(test_wrath_storm)
        finally:
            model.wrath_event = old
    out.append(("Wrath of the Storm: DC on the sheet's casting ability", m_wrath_dc))

    def m_wrath_reach():
        old = dict(model.REACH_SHARE)
        model.REACH_SHARE["boss"] = model.REACH_SHARE["day"]   # the boss fight's reach share not swapped in
        try:
            return _ci(test_wrath_storm)
        finally:
            model.REACH_SHARE.update(old)
    out.append(("Wrath of the Storm: the boss fight's reach share ignored", m_wrath_reach))

    def m_adv_sure():
        old = model.ADV_SURE
        model.ADV_SURE = 1.5                        # never sure: Trip planned, no Riposte
        try:
            return check_plan_gaps()[0]
        finally:
            model.ADV_SURE = old
    out.append(("plan gaps: Advantage never sure (Trip instead of Riposte)", m_adv_sure))

    def m_contact():
        old = model.SCENARIOS["boss"]["melee_contact"]
        model.SCENARIOS["boss"]["melee_contact"] = 0.0
        try:
            return check_plan_gaps()[0]
        finally:
            model.SCENARIOS["boss"]["melee_contact"] = old
    out.append(("plan gaps: a ranged build never in reach of the boss", m_contact))

    def m_boss(patch):
        def run():
            undo = patch()
            try:
                return check_boss_tactics()[0]
            finally:
                undo()
        return run

    def p_no_dis():
        old = set(model.RANGED_DIS_TYPES)
        model.RANGED_DIS_TYPES.clear()
        return lambda: model.RANGED_DIS_TYPES.update(old)
    out.append(("boss reach: no Disadvantage for ranged attacks", m_boss(p_no_dis)))

    def p_no_evade():
        old = model.State.can_evade
        model.State.can_evade = lambda self: False
        return lambda: setattr(model.State, "can_evade", old)
    out.append(("boss reach: evading never weighed", m_boss(p_no_evade)))

    def p_hide():
        old = model.HIDE_LEGAL
        model.HIDE_LEGAL = True
        return lambda: setattr(model, "HIDE_LEGAL", old)
    out.append(("boss reach: Hide planned in the boss's sight in a lit room", m_boss(p_hide)))

    def p_allies():
        old = model.SCENARIOS["boss"]["allies"]
        model.SCENARIOS["boss"]["allies"] = True
        return lambda: model.SCENARIOS["boss"].__setitem__("allies", old)
    out.append(("boss reach: Sneak Attack as if an ally stood by", m_boss(p_allies)))

    def p_sheet_dice():
        old = model.event_mods

        def em(*a, **k):
            m = old(*a, **k)
            m["sheet_dice"] = 0.0
            return m
        model.event_mods = em
        return lambda: setattr(model, "event_mods", old)
    out.append(("crit dice: the sheet's weapon dice not doubled", m_boss(p_sheet_dice)))

    def p_switch():
        old = model.make_weapon_events

        def mk(st):
            evs, sp = old(st)
            return [e for e in evs if e.get("name") != "off-hand shot with the main hand"], sp
        model.make_weapon_events = mk
        return lambda: setattr(model, "make_weapon_events", old)
    out.append(("CastOffhand switch ignored", m_boss(p_switch)))

    def m_mix():
        old = mech.roll_mix
        mech.roll_mix = lambda a, d: (max(0.0, a - d), max(0.0, d - a))
        try:
            return _ci(test_roll_mix)
        finally:
            mech.roll_mix = old
    out.append(("Advantage and Disadvantage subtracted, not cancelled per roll", m_mix))

    def m_slots():
        old = model.SCENARIOS["boss"]["slot_share"]
        model.SCENARIOS["boss"]["slot_share"] = (2 / 3, 0.0)
        try:
            return check_plan_gaps()[0]
        finally:
            model.SCENARIOS["boss"]["slot_share"] = old
    out.append(("plan gaps: the boss fight leaves the low slots unspent", m_slots))

    def m_scenario_rests():
        old = model.SCENARIOS["boss"]["sr_windows"]
        model.SCENARIOS["boss"]["sr_windows"] = 3              # three short-rest windows in one fight
        try:
            return check_scenario()[0]
        finally:
            model.SCENARIOS["boss"]["sr_windows"] = old
    out.append(("boss scenario credits per-short-rest features 3 times", m_scenario_rests))

    def m_scenario_leak():
        old = model.scenario

        @contextlib.contextmanager
        def leaky(name):
            with old(name) as s:
                yield s
            model.ENEMY_HP[3] = 5000.0                          # the boss's HP left behind
        model.scenario = leaky
        try:
            return check_scenario()[0]
        finally:
            model.scenario = old
            model.ENEMY_HP[3] = 70.0
    out.append(("boss scenario leaves its enemy HP in the day model", m_scenario_leak))

    def m_respec():
        import respec
        old = respec.tune

        def worse(W_, cid, bid, act, loadout, switches=None, max_evals=0):
            r = old(W_, cid, bid, act, loadout, switches, max_evals=1)
            sp = r["space"]
            s0 = sp.initial()
            if s0:
                t = next(t for t in sp.neighbours(s0, 12) if t["picks"] != s0["picks"] or t["pb"] != s0["pb"])
                t["pb"] = dict(s0["pb"])
                k = max(t["pb"], key=t["pb"].get)    # take points out of the main ability
                lo_ = min(t["pb"], key=t["pb"].get)
                t["pb"][k] -= 2                     # two points: one can stay inside the same modifier
                t["pb"][lo_] += 2
                r.update(respec=sp.respec(t), state=t, tuned=r["untuned"] * 1.01)
            return r
        import run as R
        respec.tune = worse
        try:
            # a caster: an Elixir of Cloud Giant Strength in a STR build's set makes the main ability moot
            plan, _row = R.tuned_plan(W, "gale", "tempestevoker", 3,
                                      {k: v["sid"] for k, v in next(s for s in _output()["sets"] if s["id"] ==
                                                                    "gale.tempestevoker.a3.opt")["items"].items()},
                                      "gale.tempestevoker.a3.opt", "optimizer", "party")
        finally:
            respec.tune = old
        import tempfile
        tmp = os.path.join(tempfile.mkdtemp(), "plans.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"format": "loot-advisor-test-plan/1", "plans": [plan]}, f)
        _CACHE.pop("P", None)
        try:
            return check_respec({"sets": []}, plans=_plans(tmp))[0]     # _plans() alone reloads the real file
        finally:
            _CACHE.pop("P", None)
            _CACHE.pop("P_path", None)
    out.append(("respec tuning returns a respec worse than the plan", m_respec))

    import party

    def _ci_red(test):
        try:
            test()
            return []
        except AssertionError as e:
            return [str(e)]

    def m_party_greedy():
        old = party._local

        def greedy(chars, items, claims, value, start=None):
            wants = {c: frozenset(i for i in items if c in claims[i]) for c in chars}
            return {i: max(claims[i], key=lambda c: (value(c, wants[c]) - value(c, wants[c] - {i}), c)) for i in items}
        party._local = greedy                        # no local search after the greedy start
        try:
            return _ci_red(test_party_solver)
        finally:
            party._local = old
    out.append(("party assignment: greedy only, no local search", m_party_greedy))

    def m_party_exact():
        old = party._exact
        party._exact = lambda chars, items, claims, value: {i: claims[i][0] for i in items}   # first claimant
        try:
            return _ci_red(test_party_solver)
        finally:
            party._exact = old
    out.append(("party assignment: exact path takes the first claimant", m_party_exact))

    def m_party_threshold():
        old = party.THRESHOLD
        party.THRESHOLD = -math.inf                  # the 10% rule removed: every solver move stands
        try:
            return _ci_red(test_party_threshold)
        finally:
            party.THRESHOLD = old
    out.append(("party assignment: 10% rule removed", m_party_threshold))

    def m_party_keep():
        import run as R
        W = _world()
        old = party.Act.deny
        party.Act.deny = lambda self, cid, kept: frozenset()      # losers keep the item
        try:
            objs, sets = {}, []
            for cid, bid in (("karlach", "giants"), ("wyll", "lockadin"), ("laezel", "bmgiant")):
                o = R.optimize(W, cid, bid, 1)
                objs[("party", 1, cid, bid)] = o
                sets.append({"char": cid, **R.to_set(W, o)})
            res = R.party_assignment(W, objs)
        finally:
            party.Act.deny = old
        return check_party({"sets": sets, "party": res})[0]
    out.append(("party assignment: losers keep the contested item (Act 1, three builds)", m_party_keep))
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
