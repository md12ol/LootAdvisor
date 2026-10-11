"""Scripted gauntlet runs for set pairs, and the report.

    python tools/gauntlet/run.py specs.json --results results.jsonl [--scenarios boss,pack,defence,longday]
                                 [--haste] [--only 0,3] [--rounds 16] [--arena undercity_cistern] [--sides a]
    python tools/gauntlet/run.py --report results.jsonl --specs specs.json [--md report.md]
    python tools/gauntlet/run.py --rescore results.jsonl[,more.jsonl] --specs specs.json
    python tools/gauntlet/run.py specs.json --lanes undercity_lanes --char A_UUID --char-b B_UUID --repeats 3
    python tools/gauntlet/run.py specs.json --sides a --lanes undercity_lanes --chars laezel=UUID,shadowheart=UUID

Two lanes (--lanes, a "lanes" entry of arenas.json): both sets of a pair fight at once, each with its own character,
enemies and arena spot, in two separate combats. Both characters have the same build (two party members respecced to
it in the same test save). The lanes must lie farther apart than the farthest reach of any spell in either set plus
both lanes' radii and a margin; the sides swap lanes and the first lane alternates from one repeat to the next, so
neither set keeps the better spot or the head start. With one character (no --char-b) or lanes too close for the
pair's spells the sides run one after the other in lane A's spot, the first side alternating per repeat.
--respec real (the default) expects the character's own levels, as a real respec in a test save made them; emulated
rebuilds the sheet with boosts on whatever character runs.

Lanes across pairs: when a save holds one character per build (the two sides of a pair come from two saves), the
lanes take the same side of two different pairs at once instead (--chars names each pair's character by its "char";
--char is the default). Two sides share a repeat only when their characters differ and the lanes lie far enough apart
for both sets' spells; the rest run one after the other in lane A's spot. The lanes swap from one repeat to the next.

Repeats and early stopping: --repeats is the most usable runs a side gets, counting the ones already in --results for
the same pair, set and scenario; so the side of a pair run from the other save first (--sides b after --sides a) sees
the other side's runs, and a pair already decided is not run again. After every run the pair is decisive when the 95%
interval of the ratio of the two sides' damage per round excludes 1 or lies within +-control-tol; the interval compares
rounds by their number (each round's mean over both sides is taken out and the rest resampled per side), because a
round's damage depends on its number far more than on the dice (round 1's Action Surge, item spells, slots running out).
A side whose first run failed for a reason that would fail every run (a setup mismatch at the start, a bad request, a
combat that ended) is not repeated; the record says why.

specs.json comes from plan.py (one entry per pair, sets "a" and "b"). Both sets of a pair run the same scenarios with
the same script, enemies and buffs; every run appends one record to results.jsonl. Manual runs from the in-game
window are written as one JSON file each to the Script Extender folder's LootAdvisor_gauntlet/; append those records
to a results file by hand to include them in a report.

Rolls: scripted casts roll like a player's (attack rolls miss and crit, saving throws are made, and what hangs on a
roll applies: Sharpshooter's +10, Hunter's Mark, Sneak Attack); --no-real-rolls keeps the older casts that always hit
and skip saves, for comparison. Every record carries real_rolls (older records without it ran without rolls); runs of
the other kind are not counted for --repeats and are left out of the report, since the two are not comparable.

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


# Causes that would fail every run of the side the same way: the side is not repeated after its first run fails so.
DETERMINISTIC = ("setup mismatch at the start", "ended: setup mismatch at the start", "ended: bad request",
                 "ended: unknown arena", "ended: unknown scenario", "ended: no enemy stats",
                 "ended: the combat ended or never started")


def deterministic(rec):
    """The cause of an invalid run that would fail every repeat of the side the same way, or None."""
    _ok, causes = run_validity(rec)
    for c in causes:
        if str(c).startswith(DETERMINISTIC):
            return c
    return None


def same_set(rec, p, side):
    """Is the record a run of this pair's side with the same set (the spec ids the game wrote back)?"""
    sid = rec.get("spec_id") or {}
    spec = p["specs"][side]
    return sid.get("set_name") == spec.get("set") and sid.get("build") == p.get("build") and \
        str(sid.get("act")) == str(p.get("act"))


def rolls_of(rec):
    """Did the run roll like a player? Records older than the field ran without rolls."""
    return rec.get("real_rolls", (rec.get("req") or {}).get("real_rolls", False)) is not False


def prior_runs(path, i, p, scen, real_rolls=True):
    """The usable runs already in the results file with the same rolls, per side of pair i: {side: [run]}
    (run: [(round key, damage)])."""
    out = {"a": [], "b": []}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(x) for x in f if x.strip()]
    for r in recs:
        if r.get("pair") != i or r.get("side") not in out or r.get("scenario") not in scen or not same_set(r, p, r["side"]):
            continue
        if rolls_of(r) != real_rolls:
            continue
        run = usable_run(r)
        if run:
            out[r["side"]].append(run)
    return out


def usable_run(rec):
    """A record's fair rounds as [((scenario, haste, round), damage)], or [] when the record is no measurement."""
    if rec.get("scenario") == "defence" or (rec.get("req") or {}).get("scenario") == "defence":
        return []
    ok, _causes, clean = rescore(rec)
    d = ((rec.get("results") or {}).get("summary") or {}).get("dealt") or []
    if not ok or len(d) != len(clean):
        return []
    key = (rec.get("scenario"), bool(rec.get("haste")))
    return [(key + (r + 1,), x) for r, (x, c) in enumerate(zip(d, clean)) if c]


def char_for(a, p):
    """The character that runs this pair (--chars by the pair's "char", else --char)."""
    m = dict(x.split("=", 1) for x in (getattr(a, "chars", None) or "").split(",") if "=" in x)
    return m.get(p.get("char")) or a.char


def lane_batches(a, pairs, todo, arenas, k):
    """One repeat's runs: [(pair, side)] in order -> batches of one (one after the other) or two (two lanes at once:
    two different pairs' sides with different characters, the lanes far enough apart for both sets). Repeat k decides
    which side of a batch takes lane A. -> [[(pair, side)]], with the spacing two lanes need per batch."""
    out, left = [], list(todo)
    while left:
        i, side = left.pop(0)
        mate = None
        if getattr(a, "lanes", None):
            for j, (i2, side2) in enumerate(left):
                if i2 == i or char_for(a, pairs[i]) == char_for(a, pairs[i2]) or not char_for(a, pairs[i]):
                    continue
                ok, need, _have = lane_gap(arenas, a.lanes, [(pairs[x]["specs"][s].get("reach") or {}).get("m")
                                                             for x, s in ((i, side), (i2, side2))])
                if ok:
                    mate = (left.pop(j), need)
                    break
        if mate:
            pair_ = [(i, side), mate[0]]
            out.append((pair_ if k % 2 == 0 else pair_[::-1], mate[1]))
        else:
            out.append(([(i, side)], None))
    return out


def do_runs(a):
    with open(a.specs, encoding="utf-8") as f:
        pairs = json.load(f)
    only = {int(x) for x in a.only.split(",")} if a.only else None
    scen = a.scenarios.split(",")
    sides = tuple(a.sides.split(","))
    arenas = load_arenas()
    print(engine.load())
    todo = [i for i in range(len(pairs)) if only is None or i in only]
    got = {i: prior_runs(a.results, i, pairs[i], scen, not a.no_real_rolls) for i in todo}
    for i in todo:
        if got[i]["a"] or got[i]["b"]:
            print(f"pair {i}: usable runs in the results already: a {len(got[i]['a'])}, b {len(got[i]['b'])}")
    done, skip = {}, {}
    same_pair = {i: lanes_possible(a, pairs[i], arenas) for i in todo}
    for i in todo:
        if a.lanes and not same_pair[i][0]:
            print(f"pair {i}: no two lanes for its own sides: {same_pair[i][1]}")

    def settle(i):
        if i in done:
            return
        stop, why = decisive(got[i]["a"], got[i]["b"], a.control_tol)
        print(f"  pair {i} ({len(got[i]['a'])} + {len(got[i]['b'])} usable runs): {why}")
        if stop:
            done[i] = why
    for i in todo:
        if got[i]["a"] and got[i]["b"]:
            settle(i)
    for k in range(min(3, max(1, a.repeats))):
        queue = []
        for i in todo:
            if i in done:
                continue
            if same_pair[i][0]:
                if min(len(got[i]["a"]), len(got[i]["b"])) <= k:
                    for side, run in run_lanes(a, i, pairs[i], scen, k, same_pair[i][1]).items():
                        got[i][side] += run
                    settle(i)
                continue
            for side in sequential_order(k, sides):
                if (i, side) in skip:
                    continue
                if len(got[i][side]) > k:
                    continue
                queue.append((i, side))
        for batch, need in lane_batches(a, pairs, queue, arenas, k):
            batch = [(i, s_) for i, s_ in batch if i not in done]
            if len(batch) == 2:
                results = run_cross(a, pairs, batch, scen, k, need)
            else:
                results = {}
                for i, side in batch:
                    results[(i, side)] = run_side(a, i, pairs[i], side, scen,
                                                  extra={"repeat": k, "lanes_fallback": a.lanes and "one after the "
                                                         "other" or None})
            for (i, side), (runs, recs) in results.items():
                got[i][side] += runs
                if not runs and (i, side) not in skip and len(got[i][side]) == 0:
                    why = next((deterministic(r) for r in recs if deterministic(r)), None)
                    if why and k == 0:
                        skip[(i, side)] = why
                        print(f"  pair {i} {side}: not repeated, its first run failed for a reason every run would "
                              f"meet: {why}")
                        not_repeated(a, i, side, scen, why)
                settle(i)


def not_repeated(a, i, side, scen, why):
    """Records that a side is not repeated, and why (the report lists it with the invalid runs)."""
    rec = {"mode": "scripted", "pair": i, "side": side, "scenario": scen[0], "not_repeated": True, "valid": False,
           "invalid": [f"not repeated: the first run failed for a reason every run would meet ({why})"]}
    with open(a.results, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def run_cross(a, pairs, batch, scen, k, need):
    """Two sides of different pairs at once, one per lane (the first of the batch in lane A). -> {(pair, side): (usable
    runs, records)}."""
    lanes = ("A", "B")
    first = lanes[k % 2]
    out = {(i, s_): ([], []) for i, s_ in batch}
    for sc in scen:
        for haste in ([False, True] if a.haste else [False]):
            entries = []
            for lane, (i, side) in zip(lanes, batch):
                req = dict(_req(a, i, pairs[i], side, sc, haste, char_for(a, pairs[i])), arena=None)
                entries.append((lane, req, pairs[i]["specs"][side]))
            print("lanes across pairs: " + ", ".join(f"{lane} = pair {i} {pairs[i]['char']} {side}"
                                                      for lane, (i, side) in zip(lanes, batch))
                  + f" {sc}{' haste' if haste else ''}, lane {first} first")
            t0 = time.time()
            try:
                recs = engine.run_lanes(a.lanes, entries, first, gap_need=need)
            except Exception as e:
                recs = {lane: {"error": str(e), "req": req, "valid": False, "invalid": [str(e)]}
                        for lane, req, _s in entries}
                print("  ERROR", e)
            for lane, (i, side) in zip(lanes, batch):
                rec = recs.get(lane) or {"error": "no record from the lane", "valid": False,
                                         "invalid": ["no record from the lane"], "req": {"scenario": sc}}
                rec.setdefault("scenario", sc)
                run = _record(a, rec, i, side, t0, {"repeat": k, "lane": lane, "first_lane": first, "concurrent": True,
                                                    "lanes_across_pairs": True})
                if run:
                    out[(i, side)][0].append(run)
                out[(i, side)][1].append(rec)
    return out


def _keyed(run):
    """A run as [(round key, damage)]: a plain list of numbers is keyed by its position."""
    return [x if isinstance(x, (tuple, list)) else (i + 1, x) for i, x in enumerate(run)]


def _runs(runs):
    """A list of runs; a plain list of numbers is one run."""
    return runs if runs and isinstance(runs[0], list) else [runs]


def round_ratio(runs_a, runs_b, n=2000, seed=13):
    """95% interval of the ratio of the two sides' mean damage per round, rounds compared by their number: each round
    key's mean over both sides is taken out, the residuals are resampled per side and the means rebuilt. Only round
    keys both sides have count. -> ((lo, hi), rounds on the shorter side) or (None, rounds)."""
    ka = [kv for r in _runs(runs_a) for kv in _keyed(r)]
    kb = [kv for r in _runs(runs_b) for kv in _keyed(r)]
    both = {k for k, _v in ka} & {k for k, _v in kb}
    ka, kb = [kv for kv in ka if kv[0] in both], [kv for kv in kb if kv[0] in both]
    m = min(len(ka), len(kb))
    if min(len(ka), len(kb)) < 2:
        return None, m
    pool = {}
    for k, v in ka + kb:
        pool.setdefault(k, []).append(v)
    mk = {k: mean(v) for k, v in pool.items()}
    base_a, base_b = mean([mk[k] for k, _v in ka]), mean([mk[k] for k, _v in kb])
    ra, rb = [v - mk[k] for k, v in ka], [v - mk[k] for k, v in kb]
    rnd = random.Random(seed)
    rs = []
    for _ in range(n):
        a_ = base_a + mean([ra[rnd.randrange(len(ra))] for _ in ra])
        b_ = base_b + mean([rb[rnd.randrange(len(rb))] for _ in rb])
        if b_ > 0:
            rs.append(a_ / b_)
    rs.sort()
    return ((rs[int(0.025 * len(rs))], rs[int(0.975 * len(rs)) - 1]) if rs else None), m


def decisive(runs_a, runs_b, tol=None):
    """Sequential stopping: -> (stop, why). runs_x: the side's usable runs, each [(round key, damage)] of its fair
    rounds (round_ratio). The 95% interval of the ratio of the two sides' damage per round is decisive when it excludes
    1 (one set is better) or lies inside 1 +- tol (the sets measure alike)."""
    tol = CONTROL_TOL if tol is None else tol
    ci, m = round_ratio(runs_a, runs_b)
    if m < CONTROL_MIN_ROUNDS:
        return False, f"{m} fair rounds on the shorter side, not decisive"
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
            "retry_any_refusal": True if getattr(a, "retry_any_refusal", False) else None,
            "real_rolls": not getattr(a, "no_real_rolls", False)}


def _record(a, rec, i, side, t0, extra=None):
    rec["pair"], rec["side"], rec["secs"] = i, side, round(time.time() - t0, 1)
    rec.update({k: v for k, v in (extra or {}).items() if v is not None})
    rec.setdefault("real_rolls", (rec.get("req") or {}).get("real_rolls", True) is not False)
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
    return usable_run(rec)


def run_lanes(a, i, p, scen, k, gap):
    """Repeat k of a pair in two lanes at once, per scenario. -> {side: [usable run]}."""
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
                run = _record(a, rec, i, side, t0, {"repeat": k, "lane": lane, "first_lane": plan["first"],
                                                    "concurrent": True})
                if run:
                    dealt[side].append(run)
    return dealt


def run_side(a, i, p, side, scen, extra=None):
    """One side of a pair over the scenarios -> ([usable run], [record]) (run: its fair rounds, keyed)."""
    spec = p["specs"][side]
    runs, recs = [], []
    for sc in scen:
        for haste in ([False, True] if a.haste else [False]):
            req = _req(a, i, p, side, sc, haste, char_for(a, p))
            t0 = time.time()
            print(f"pair {i} {p['char']} {p['build']} A{p['act']} set {side} ({spec['set']}) {sc}"
                  f"{' haste' if haste else ''}")
            try:
                rec = engine.run(req, spec)
            except Exception as e:
                rec = {"error": str(e), "req": req, "valid": False, "invalid": [str(e)]}
                print("  ERROR", e)
            rec.setdefault("scenario", sc)
            run = _record(a, rec, i, side, t0, extra)
            if run:
                runs.append(run)
            recs.append(rec)
    return runs, recs


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
    by, invalid, other_rolls = {}, [], 0
    want_rolls = not getattr(a, "no_real_rolls", False)
    for r in recs:
        if r.get("mode") != "scripted" and "error" not in r:
            continue
        if rolls_of(r) != want_rolls:
            other_rolls += 1
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
    if other_rolls:
        text += (f"\n{other_rolls} run(s) {'without' if want_rolls else 'with'} real rolls left out (not comparable; "
                 f"{'drop' if want_rolls else 'use'} --no-real-rolls to report them).\n")
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
    ap.add_argument("--repeats", type=int, default=1, help="up to this many usable runs per side (at most 3; the "
                    "ones already in --results count), stopping early once the 95%% interval of the two sides' ratio "
                    "is decisive")
    ap.add_argument("--rounds", type=int, default=16)
    ap.add_argument("--sides", default="a,b", help="a, b or a,b: one set of each pair only (e.g. a reload between)")
    ap.add_argument("--arena", help="a fixed spot from tools/gauntlet/arenas.json (default: where the character stands)")
    ap.add_argument("--char", help="uuid of the test character (default: the host); lane A's with --lanes")
    ap.add_argument("--chars", help="the character per pair, by the pair's char: laezel=UUID,gale=UUID (default --char); "
                    "with --lanes two pairs' sides with different characters run at once")
    ap.add_argument("--char-b", help="uuid of lane B's character: a second party member with the same build")
    ap.add_argument("--lanes", help="a lanes entry of tools/gauntlet/arenas.json: both sides at once (see above)")
    ap.add_argument("--respec", choices=("real", "emulated"), default="real",
                    help="real: the characters were levelled to the build (test save per build); emulated: boosts")
    ap.add_argument("--retry-any-refusal", action="store_true",
                    help="ask again for any cast the engine refused, not only one an Attack of Opportunity interrupted "
                    "(off by default; the control passed without it)")
    ap.add_argument("--no-real-rolls", action="store_true",
                    help="scripted casts never roll (always hit, saves skipped), as runs before rolls did; only for "
                    "comparison with those runs. Also picks which runs --report and --repeats count")
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
