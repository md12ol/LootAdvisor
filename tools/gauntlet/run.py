"""Scripted gauntlet runs for set pairs, and the report.

    python tools/gauntlet/run.py specs.json --results results.jsonl [--scenarios boss,pack,defence,longday]
                                 [--haste] [--only 0,3] [--rounds 16] [--arena undercity_cistern] [--sides a]
    python tools/gauntlet/run.py --report results.jsonl --specs specs.json [--md report.md]
    python tools/gauntlet/run.py --rescore results.jsonl[,more.jsonl] --specs specs.json
    python tools/gauntlet/run.py specs.json --lanes undercity_lanes --char A_UUID --char-b B_UUID --repeats 3

Two lanes (--lanes, a "lanes" entry of arenas.json): both sets of a pair fight at once, each with its own character,
enemies and arena spot, in two separate combats. Both characters have the same build (two party members respecced to
it in the same test save). The lanes must lie farther apart than the farthest reach of any spell in either set plus
both lanes' radii and a margin; the sides swap lanes and the first lane alternates from one repeat to the next, so
neither set keeps the better spot or the head start. With one character (no --char-b) or lanes too close for the
pair's spells the sides run one after the other in lane A's spot, the first side alternating per repeat.
--respec real (the default) expects the character's own levels, as a real respec in a test save made them; emulated
rebuilds the sheet with boosts on whatever character runs.

specs.json comes from plan.py (one entry per pair, sets "a" and "b"). Both sets of a pair run the same scenarios with
the same script, enemies and buffs; every run appends one record to results.jsonl. Manual runs from the in-game
window are written as one JSON file each to the Script Extender folder's LootAdvisor_gauntlet/; append those records
to a results file by hand to include them in a report.

Validity: a run the game marks invalid (ended early, a cast never confirmed in a round, a reaction outside the plan,
...) or that never finished is kept in results.jsonl with its causes and left out of the report. Control gate: a
control pair (two sets the model rates alike) must measure alike in the game too; when its two sets differ by more
than twice --control-tol, or by more than --control-tol with the difference beyond the dice (the 95% bootstrap
interval of the ratio of the two means excludes 1), the whole report is marked INVALID, because the gap comes from
the harness, not the gear. Sixteen rounds of dice cannot resolve 15% on their own: two sets the model rates alike
differed by 17% over 12 rounds in the pilot, with an interval that holds 1.
Rounds are compared pairwise when both runs carry a per-round mask of fair rounds (--rescore).

--rescore re-judges older run records under the current rules where the record allows it: a round in which the
character was down or no action was confirmed is masked out instead of voiding the run, and a cast of an item spell
is not a cast outside the plan; every other cause (ended early, arena not clear, ...) still voids the run.
"""
import argparse
import json
import math
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine  # noqa: E402

R_SAT = 12.0
CONTROL_MODEL_EQ = 0.05   # a pair whose two sets the model rates within 5% (DPR) is a control
CONTROL_TOL = 0.15        # the control's two sets may differ in the game by at most this share of the larger mean
CONTROL_MIN_ROUNDS = 8    # fewer fair rounds on both sides: the control is not measured


def sat(r):
    return r / (1.0 + r / R_SAT)


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def boot_ci(xs, n=2000, seed=7):
    """95% bootstrap interval of the mean (rounds are the samples)."""
    if len(xs) < 2:
        return (mean(xs), mean(xs))
    rnd = random.Random(seed)
    ms = sorted(mean([xs[rnd.randrange(len(xs))] for _ in xs]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def boot_ratio(a, b, n=2000, seed=11):
    """95% bootstrap interval of mean(a) / mean(b)."""
    if len(a) < 2 or len(b) < 2:
        return None
    rnd = random.Random(seed)
    rs = []
    for _ in range(n):
        ma = mean([a[rnd.randrange(len(a))] for _ in a])
        mb = mean([b[rnd.randrange(len(b))] for _ in b])
        if mb > 0:
            rs.append(ma / mb)
    rs.sort()
    return (rs[int(0.025 * len(rs))], rs[int(0.975 * len(rs)) - 1]) if rs else None


def load_arenas():
    with open(os.path.join(HERE, "arenas.json"), encoding="utf-8") as f:
        return json.load(f)


def lane_gap(arenas, lanes, reaches):
    """Are a lanes entry's spots far enough apart for these sets? The farthest a spell of either set reaches, from
    anywhere inside its lane, must stay short of anything inside the other lane: centre distance > radius + reach +
    radius + margin. -> (ok, need, have) in metres."""
    LS = arenas.get(lanes) or {}
    spots = [arenas.get(x["arena"]) or {} for x in (LS.get("lanes") or {}).values()]
    if len(spots) < 2 or not all(sp.get("center") for sp in spots):
        return False, None, None
    reach = max([float(r or 0) for r in reaches] + [0.0])
    need, have = 0.0, None
    for x, y in [(x, y) for i, x in enumerate(spots) for y in spots[i + 1:]]:
        d = math.hypot(x["center"][0] - y["center"][0], x["center"][2] - y["center"][2])
        have = d if have is None else min(have, d)
        need = max(need, x["radius"] + reach + y["radius"] + float(LS.get("margin") or 0))
    return have > need, round(need, 1), round(have, 1)


def lane_schedule(k, lane_ids=("A", "B")):
    """Repeat k (from 0): which side fights in which lane and which lane starts first. The sides swap lanes and the
    first lane alternates every repeat. -> {"first": lane, "sides": {lane: side}}."""
    first = lane_ids[k % 2]
    sides = {lane_ids[0]: "a", lane_ids[1]: "b"} if k % 2 == 0 else {lane_ids[0]: "b", lane_ids[1]: "a"}
    return {"first": first, "sides": sides}


def sequential_order(k, sides=("a", "b")):
    """One lane only: the sides one after the other, the first side alternating per repeat."""
    return list(sides) if k % 2 == 0 else list(reversed(sides))


def lanes_possible(a, p, arenas):
    """-> (True, gap) when the pair can run in two lanes at once, else (False, why)."""
    if not getattr(a, "lanes", None):
        return False, "no lanes asked for"
    if not a.char or not a.char_b:
        return False, "only one character with the build (two lanes need --char and --char-b)"
    if a.char == a.char_b:
        return False, "the two lanes need two different characters"
    ok, need, have = lane_gap(arenas, a.lanes, [(p["specs"][s].get("reach") or {}).get("m") for s in ("a", "b")])
    if not ok:
        return False, f"lanes {have} m apart, the pair's spells need {need} m"
    return True, need


def do_runs(a):
    with open(a.specs, encoding="utf-8") as f:
        pairs = json.load(f)
    only = {int(x) for x in a.only.split(",")} if a.only else None
    scen = a.scenarios.split(",")
    arenas = load_arenas()
    print(engine.load())
    for i, p in enumerate(pairs):
        if only is not None and i not in only:
            continue
        got = {"a": [], "b": []}
        both, gap = lanes_possible(a, p, arenas)
        if a.lanes and not both:
            print(f"pair {i}: lanes one after the other: {gap}")
        for k in range(min(3, max(1, a.repeats))):
            if both:
                for side, dealt in run_lanes(a, i, p, scen, k, gap).items():
                    got[side] += dealt
            else:
                order = sequential_order(k, tuple(a.sides.split(",")))
                for side in order:
                    got[side] += run_side(a, i, p, side, scen, extra={"repeat": k, "order": order,
                                                                       "lanes_fallback": gap if a.lanes else None})
            stop, why = decisive(got["a"], got["b"], a.control_tol)
            print(f"  pair {i} after {k + 1} repeat(s): {why}")
            if stop:
                break


def decisive(xa, xb, tol=None):
    """Sequential stopping: -> (stop, why). The 95% interval of the ratio of the two sides' mean damage per round is
    decisive when it excludes 1 (one set is better) or lies inside 1 +- tol (the sets measure alike)."""
    tol = CONTROL_TOL if tol is None else tol
    if min(len(xa), len(xb)) < CONTROL_MIN_ROUNDS:
        return False, f"{min(len(xa), len(xb))} fair rounds on the shorter side, not decisive"
    ci = boot_ratio(xa, xb)
    if not ci:
        return False, "no interval"
    if ci[0] > 1 or ci[1] < 1:
        return True, f"decisive: ratio 95% interval {ci[0]:.2f}-{ci[1]:.2f} excludes 1"
    if ci[0] >= 1 - tol and ci[1] <= 1 + tol:
        return True, f"decisive: ratio 95% interval {ci[0]:.2f}-{ci[1]:.2f} within {tol:.0%}"
    return False, f"ratio 95% interval {ci[0]:.2f}-{ci[1]:.2f}, not decisive"


def _req(a, i, p, side, sc, haste, char):
    spec = p["specs"][side]
    arena = a.arena
    if not arena and getattr(a, "lanes", None):
        arena = ((load_arenas().get(a.lanes) or {}).get("lanes") or {}).get("A", {}).get("arena")
    return {"mode": "scripted", "scenario": sc, "act": spec["act"], "haste": haste, "rounds": a.rounds, "arena": arena,
            "char": char, "label": f"pair{i}:{side}", "respec": getattr(a, "respec", "real"),
            "retry_any_refusal": True if getattr(a, "retry_any_refusal", False) else None}


def _record(a, rec, i, side, t0, extra=None):
    rec["pair"], rec["side"], rec["secs"] = i, side, round(time.time() - t0, 1)
    rec.update({k: v for k, v in (extra or {}).items() if v is not None})
    rec["valid"], rec["invalid"] = run_validity(rec)
    if not rec["valid"]:
        print(f"  {side}: INVALID: " + "; ".join(rec["invalid"]))
    with open(a.results, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    s = (rec.get("results") or {}).get("summary") or {}
    tm = (rec.get("results") or {}).get("timing") or {}
    # summon damage is part of dpr; its share is shown apart
    summ = f" (summons {s['summon_damage'] / max(1, len(s.get('dealt') or [])):.1f})" if s.get("summon_damage") else ""
    print(f"  {side}: dpr {s.get('dpr', 0):.1f}{summ} taken/round {s.get('taken_per_round', 0):.1f} "
          f"not done {s.get('actions_not_done')} survived {s.get('rounds_survived')} ({rec['secs']} s; "
          f"prep {tm.get('prep_ms', 0) / 1000:.1f} s, fight {tm.get('fight_ms', 0) / 1000:.1f} s)")
    if rec.get("scenario") == "defence" or (rec.get("req") or {}).get("scenario") == "defence":
        return []
    ok, _causes, clean = rescore(rec)
    d = s.get("dealt") or []
    return [x for x, c in zip(d, clean) if c] if ok and len(d) == len(clean) else []


def run_lanes(a, i, p, scen, k, gap):
    """Repeat k of a pair in two lanes at once, per scenario. -> {side: damage per fair round}."""
    plan = lane_schedule(k)
    chars = {"A": a.char, "B": a.char_b}
    dealt = {"a": [], "b": []}
    for sc in scen:
        for haste in ([False, True] if a.haste else [False]):
            entries = [(lane, dict(_req(a, i, p, side, sc, haste, chars[lane]), arena=None), p["specs"][side])
                       for lane, side in sorted(plan["sides"].items())]
            print(f"pair {i} {p['char']} {p['build']} A{p['act']} {sc}{' haste' if haste else ''} in lanes: "
                  + ", ".join(f"{lane} = {side}" for lane, side in sorted(plan["sides"].items()))
                  + f", lane {plan['first']} first")
            t0 = time.time()
            try:
                recs = engine.run_lanes(a.lanes, entries, plan["first"], gap_need=gap)
            except Exception as e:
                recs = {lane: {"error": str(e), "req": req, "valid": False, "invalid": [str(e)]}
                        for lane, req, _s in entries}
                print("  ERROR", e)
            for lane, side in sorted(plan["sides"].items()):
                rec = recs.get(lane) or {"error": "no record from the lane", "valid": False,
                                         "invalid": ["no record from the lane"], "req": {"scenario": sc}}
                rec.setdefault("scenario", sc)
                dealt[side] += _record(a, rec, i, side, t0, {"repeat": k, "lane": lane, "first_lane": plan["first"],
                                                             "concurrent": True})
    return dealt


def run_side(a, i, p, side, scen, extra=None):
    """One side of a pair over the scenarios -> the damage per round of its usable runs, fair rounds only."""
    spec = p["specs"][side]
    dealt = []
    for sc in scen:
        for haste in ([False, True] if a.haste else [False]):
            req = _req(a, i, p, side, sc, haste, a.char)
            t0 = time.time()
            print(f"pair {i} {p['char']} {p['build']} A{p['act']} set {side} ({spec['set']}) {sc}"
                  f"{' haste' if haste else ''}")
            try:
                rec = engine.run(req, spec)
            except Exception as e:
                rec = {"error": str(e), "req": req, "valid": False, "invalid": [str(e)]}
                print("  ERROR", e)
            rec.setdefault("scenario", sc)
            dealt += _record(a, rec, i, side, t0, extra)
    return dealt


def run_validity(rec):
    """-> (valid, causes) of one run record: the game's own verdict, plus records without a result."""
    res = rec.get("results") or {}
    causes = list(rec.get("invalid") or res.get("invalid") or [])
    if "error" in rec and rec["error"] not in causes:
        causes.append(rec["error"])
    if not res.get("summary") and not causes:
        causes.append("no results in the record")
    valid = rec.get("valid", res.get("valid", True)) is not False and not causes
    return valid, causes


def is_control(p):
    """A control pair: marked so, or the model rates its two sets within CONTROL_MODEL_EQ of each other in damage per
    round and, where the pair records them, in damage taken per round and rounds survived (with real hit points a
    pair alike in damage only is no control: the set that takes more goes down sooner)."""
    if "control" in p:
        return bool(p["control"])
    m = p.get("model") or {}
    da, db = m.get("a_dpr"), m.get("b_dpr")
    if not (da and db):
        da, db = (p["specs"]["a"].get("expect") or {}).get("dpr"), (p["specs"]["b"].get("expect") or {}).get("dpr")
    if not (da and db) or abs(da / db - 1) > CONTROL_MODEL_EQ:
        return False
    for ka, kb in (("a_taken", "b_taken"), ("a_R", "b_R")):
        if m.get(ka) and m.get(kb) and abs(m[ka] / m[kb] - 1) > CONTROL_MODEL_EQ:
            return False
    return True


def paired(ea, eb):
    """The two sides' per-round damage on the rounds fair in both (masks from --rescore), else every round."""
    da, db = ea["dealt"], eb["dealt"]
    ca, cb = ea.get("clean"), eb.get("clean")
    if ca is not None and cb is not None and len(ca) == len(da) == len(cb) == len(db):
        idx = [i for i in range(len(da)) if ca[i] and cb[i]]
        return [da[i] for i in idx], [db[i] for i in idx]
    return da, db


def control_gate(pairs, by, tol=CONTROL_TOL):
    """The pilot is a measurement only if every control pair measures alike: per scenario its two sets' mean damage
    per round may differ by at most tol (share of the larger mean), or by up to twice tol when the dice explain the gap
    (the 95% interval of the ratio of the means contains 1). -> {valid: True | False | None, causes, controls}; None = no control pair."""
    causes, controls = [], []
    for i, p in enumerate(pairs):
        if not is_control(p):
            continue
        keys = sorted({(sc, h) for (j, _side, sc, h) in by if j == i})
        both = [(sc, h) for sc, h in keys if by.get((i, "a", sc, h)) and by.get((i, "b", sc, h))
                and sc != "defence"]
        if not both:
            causes.append(f"control pair {i} ({p['char']} {p['build']}) not measured on both sides")
            continue
        for sc, h in both:
            xa, xb = paired(by[(i, "a", sc, h)], by[(i, "b", sc, h)])
            name = f"control pair {i} ({p['char']} {p['build']}) {sc}{' haste' if h else ''}"
            if min(len(xa), len(xb)) < CONTROL_MIN_ROUNDS:
                causes.append(f"{name}: only {min(len(xa), len(xb))} fair rounds on both sides "
                              f"(needs {CONTROL_MIN_ROUNDS})")
                continue
            ma, mb = mean(xa), mean(xb)
            diff = abs(ma - mb) / max(ma, mb) if max(ma, mb) > 0 else 0.0
            ci = boot_ratio(xa, xb)
            beyond_dice = ci is None or not (ci[0] <= 1.0 <= ci[1])
            ea, eb = by[(i, "a", sc, h)], by[(i, "b", sc, h)]
            controls.append({"pair": i, "scenario": sc, "haste": h, "a": round(ma, 1), "b": round(mb, 1),
                             "survived_a": ea.get("survived"), "survived_b": eb.get("survived"),
                             "diff": round(diff, 3), "rounds": len(xa), "ratio_ci": ci and [round(x, 2) for x in ci]})
            if diff > 2 * tol or (diff > tol and beyond_dice):
                causes.append(f"{name}: a {ma:.1f} vs b {mb:.1f} damage per round differ by {diff:.0%} (tolerance "
                              f"{tol:.0%}; ratio 95% interval {ci and '%.2f-%.2f' % ci or '-'})")
    valid = None if not controls and not causes else not causes
    return {"valid": valid, "causes": causes, "controls": controls}


def fair_rounds(rec):
    """Per round of a run record: a fair measurement round? Not when the character was down at the start of its turn
    or no action was confirmed in it."""
    out = []
    for R in rec.get("rounds") or []:
        hp = R.get("char_hp_before")
        down = bool(R.get("downed")) or (hp is not None and hp <= 0)
        done = R.get("done") if isinstance(R.get("done"), dict) else {}
        out.append(not down and bool(done.get("action") or done.get("item")))
    return out


ITEM_SPELL = re.compile(r"_MAG_|_Legendary_")


def own_aoo(rec, spell):
    """Every cast of this weapon attack came in a round with the character's own Attack of Opportunity (fair)."""
    if not spell.endswith("HandAttack"):
        return False
    res = rec.get("results") or {}
    me = (res.get("char") or {}).get("uuid") if isinstance(res.get("char"), dict) else None
    rounds = {R.get("r"): R for R in rec.get("rounds") or []}
    hits = [f for f in res.get("foreign_casts") or [] if f.get("spell") == spell]
    if not hits:
        return False
    for f in hits:
        R = rounds.get(f.get("r")) or {}
        mine = [x for x in R.get("reactions_seen") or [] if "AttackOfOpportunity" in str(x.get("interrupt"))
                and (me is None or x.get("who") == me)]
        casters = {c.get("who") for c in R.get("casts") or [] if c.get("spell") == spell}
        if not any(x.get("who") in casters for x in mine):
            return False
    return True


def rescore(rec):
    """Re-judges one run record under the current rules. -> (valid, causes, fair-round mask): round-level faults (down,
    idle) are masked out, casts of item spells are not foreign; any other cause still voids the run."""
    _ok, causes = run_validity(rec)
    clean = fair_rounds(rec)
    left = []
    for c in causes:
        if c.startswith("the test character cast outside the plan: "):
            spells = [x.strip() for x in c.split(": ", 1)[1].split(",")]
            if all(ITEM_SPELL.search(x) or own_aoo(rec, x) for x in spells):
                continue
        left.append(c)
    # a run the character's down ended is short by its result, not by a fault: the minimum applies to the whole side
    downed = (rec.get("results") or {}).get("ended") == "downed"
    if not left and not downed and sum(clean) < CONTROL_MIN_ROUNDS:
        left.append(f"only {sum(clean)} fair rounds")
    return not left, left, clean


def rescore_report(files, pairs, tol=CONTROL_TOL, out=print):
    """The control gate over older run records, per file and over all files together. -> the gates in that order."""
    groups = [[f] for f in files] + ([files] if len(files) > 1 else [])
    gates = []
    for grp in groups:
        by = {}
        for fn in grp:
            with open(fn, encoding="utf-8") as f:
                recs = [json.loads(x) for x in f if x.strip()]
            for r in recs:
                ok, causes, clean = rescore(r)
                dealt = ((r.get("results") or {}).get("summary") or {}).get("dealt") or []
                if len(groups) == 1 or len(grp) == 1:
                    out(f"{os.path.basename(fn)} pair {r.get('pair')} {r.get('side')}: "
                        f"{'usable' if ok else 'void'}, {sum(clean)}/{len(clean)} fair rounds"
                        + (f" ({'; '.join(causes)})" if causes else ""))
                if not ok or len(dealt) != len(clean):
                    continue
                k = (r["pair"], r["side"], r.get("scenario"), bool(r.get("haste")))
                e = by.setdefault(k, {"dealt": [], "clean": []})
                e["dealt"] += dealt
                e["clean"] += clean
        g = control_gate(pairs, by, tol)
        verdict = {True: "PASS", False: "FAIL", None: "no control measured"}[g["valid"]]
        out(f"control gate over {', '.join(os.path.basename(f) for f in grp)}: {verdict} "
            f"{json.dumps(g['controls'])} {'; '.join(g['causes'])}")
        gates.append(g)
    return gates


def report(a):
    with open(a.specs, encoding="utf-8") as f:
        pairs = json.load(f)
    recs = [json.loads(x) for x in open(a.report, encoding="utf-8") if x.strip()]
    by, invalid = {}, []
    for r in recs:
        if r.get("mode") != "scripted" and "error" not in r:
            continue
        ok, causes = run_validity(r)
        if not ok:
            invalid.append(f"- pair {r.get('pair')} {r.get('side')} {r.get('scenario') or (r.get('req') or {}).get('scenario')}"
                           f": {'; '.join(causes)}")
            continue
        k = (r["pair"], r["side"], r.get("scenario"), bool(r.get("haste")))
        s = r["results"]["summary"]
        e = by.setdefault(k, {"dealt": [], "taken": [], "hp": s.get("max_hp"), "notdone": 0, "secs": 0, "clean": [],
                              "downed": 0, "survived": [], "went_down": 0})
        fair = fair_rounds(r)
        # rounds the character spent down stay in the numbers but are left out of the control comparison
        e["clean"] += fair if len(fair) == len(s.get("dealt") or []) else [True] * len(s.get("dealt") or [])
        e["downed"] += s.get("downed") or 0
        # survival is its own field: a down ends the run, the damage compared is over the rounds actually fought
        e["survived"].append(s.get("rounds_survived", len(s.get("dealt") or [])))
        e["went_down"] += 1 if s.get("went_down") else 0
        e["dealt"] += s.get("dealt") or []
        e["taken"] += s.get("taken") or []
        e["notdone"] += s.get("actions_not_done") or 0
        e["secs"] += r.get("secs") or 0
    L = ["| Pair | Set | Boss DPR | Pack DPR | Long-day DPR | Taken / round | Turns survived | In-game score | "
         "Model score | Script misses / rounds down |", "|---|---|---|---|---|---|---|---|---|---|"]
    summary = []
    for i, p in enumerate(pairs):
        row = {}
        for side in ("a", "b"):
            spec = p["specs"][side]
            g = lambda sc: by.get((i, side, sc, False))  # noqa: E731
            boss, pack, day, dfn = g("boss"), g("pack"), g("longday"), g("defence")
            off = [x for x in (boss, pack) if x]
            offence = mean([mean(x["dealt"]) for x in off]) if off else None
            taken = mean(dfn["taken"]) if dfn else None
            hp = (dfn or boss or {}).get("hp") or spec["sheet"]["hp"]
            R = hp / taken if taken else None
            score = offence * math.sqrt(sat(R)) if offence and R else offence
            row[side] = dict(boss=boss, pack=pack, day=day, dfn=dfn, offence=offence, R=R, score=score, spec=spec)

            def f(x, key="dealt"):
                if not x:
                    return "-"
                lo, hi = boot_ci(x[key])
                return f"{mean(x[key]):.1f} ({lo:.0f}-{hi:.0f})"
            nd = sum((x or {}).get("notdone", 0) for x in (boss, pack, day, dfn))
            dn = sum((x or {}).get("downed", 0) for x in (boss, pack, day, dfn))
            L.append(f"| {p['char']} {p['build']} A{p['act']} | {side}: {spec['set']} | {f(boss)} | {f(pack)} | "
                     f"{f(day)} | {f(dfn, 'taken')} | {R and f'{R:.1f}' or '-'} | {score and f'{score:.1f}' or '-'} | "
                     f"{spec['expect']['score']} (DPR {spec['expect']['dpr']}, R {spec['expect']['R']}) | {nd} / {dn} |")
        A_, B_ = row["a"], row["b"]
        ratio = A_["score"] / B_["score"] if A_["score"] and B_["score"] else None
        ci = None
        if A_["boss"] and B_["boss"]:
            ci = boot_ratio(A_["boss"]["dealt"] + (A_["pack"] or {"dealt": []})["dealt"],
                            B_["boss"]["dealt"] + (B_["pack"] or {"dealt": []})["dealt"])
        model = p["specs"]["a"]["expect"]["score"] / p["specs"]["b"]["expect"]["score"]
        summary.append(f"- {p['char']} {p['build']} A{p['act']}: in game {('%+.0f%%' % ((ratio - 1) * 100)) if ratio else '-'}"
                       f" (offence ratio 95% CI {ci and '%.2f-%.2f' % ci or '-'}), model {(model - 1) * 100:+.0f}%")
    gate = control_gate(pairs, by, getattr(a, "control_tol", CONTROL_TOL))
    if gate["valid"] is False:
        head = "**PILOT INVALID** (control gate): " + "; ".join(gate["causes"])
    elif gate["valid"] is None:
        head = "Control gate: no control pair measured - the result is unchecked."
    else:
        head = "Control gate passed: " + ", ".join(f"pair {c['pair']} {c['scenario']} {c['diff']:.0%}"
                                                   for c in gate["controls"])
    text = head + "\n\n" + "\n".join(L) + "\n\nOptimizer set (a) vs research set (b), combined score:\n" + \
        "\n".join(summary) + "\n"
    if invalid:
        text += "\nInvalid runs (left out):\n" + "\n".join(invalid) + "\n"
    print(text)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(text)
    return gate


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="?")
    ap.add_argument("--specs", dest="specs2")
    ap.add_argument("--results", default="gauntlet_results.jsonl")
    ap.add_argument("--scenarios", default="boss,pack,defence,longday")
    ap.add_argument("--haste", action="store_true", help="also run every scenario with Haste")
    ap.add_argument("--only")
    ap.add_argument("--repeats", type=int, default=1, help="up to this many runs per side (at most 3), stopping "
                    "early once the 95%% interval of the two sides' ratio is decisive")
    ap.add_argument("--rounds", type=int, default=16)
    ap.add_argument("--sides", default="a,b", help="a, b or a,b: one set of each pair only (e.g. a reload between)")
    ap.add_argument("--arena", help="a fixed spot from tools/gauntlet/arenas.json (default: where the character stands)")
    ap.add_argument("--char", help="uuid of the test character (default: the host); lane A's with --lanes")
    ap.add_argument("--char-b", help="uuid of lane B's character: a second party member with the same build")
    ap.add_argument("--lanes", help="a lanes entry of tools/gauntlet/arenas.json: both sides at once (see above)")
    ap.add_argument("--respec", choices=("real", "emulated"), default="real",
                    help="real: the characters were levelled to the build (test save per build); emulated: boosts")
    ap.add_argument("--retry-any-refusal", action="store_true",
                    help="ask again for any cast the engine refused, not only one an Attack of Opportunity interrupted "
                    "(off by default; the control passed without it)")
    ap.add_argument("--report")
    ap.add_argument("--rescore", help="older run records (comma-separated files): re-judge them and run the gate")
    ap.add_argument("--md")
    ap.add_argument("--control-tol", type=float, default=CONTROL_TOL,
                    help="largest difference allowed between a control pair's two sets (share, default 0.15)")
    a = ap.parse_args(argv)
    a.specs = a.specs or a.specs2
    if a.rescore:
        with open(a.specs, encoding="utf-8") as f:
            return rescore_report(a.rescore.split(","), json.load(f), a.control_tol)
    if a.report:
        return report(a)
    else:
        do_runs(a)


if __name__ == "__main__":
    main()
