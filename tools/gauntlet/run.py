"""Scripted gauntlet runs for set pairs, and the report.

    python tools/gauntlet/run.py specs.json --results results.jsonl [--only 0,3] [--sides a] [--repeats 4]
                                 [--rounds 16] [--arena NAME] [--char UUID]
    python tools/gauntlet/run.py --report results.jsonl --specs specs.json [--md report.md]
    python tools/gauntlet/run.py --turns results.jsonl [--md turns.md]      # what the character did, turn by turn

The method (one boss fight of 16 rounds, fixed repeats, one statistic, the model's boss scenario part by part):
- every run goes through the F11 test popup's Start (engine.run): the script sets the popup to Automatic as its first
  step after loading the harness, then each run is the popup's setup, setup check and fight, with the same record;
- a side runs until it has --repeats valid runs (default 4; the valid ones already in --results count), at most
  twice that many tries; a side whose first run failed for a reason every run would meet is not repeated;
- after every run the turn list (round by round: the spell or attack, its target and its result) is written next to
  the results, <results>_turns/<run id>.md, for a person to replay the run by hand;
- --report compares each set with the model's BOSS scenario (expect.boss from plan.py, not the day numbers): first
  part by part, counted per attack roll (attack rolls, landed rolls and critical hits per round, hit and critical
  rates, rolls with net Advantage and with Disadvantage, damage per landed roll with and without Sneak Attack, the
  riders) in the character's own turn, then its reactions in the enemies' turns (a riposte: its rolls, landed rolls,
  critical hits, damage and Sneak Attack per round) apart, then damage per round (own turn and in all). A part is flagged when the model's value lies outside the game's 95% interval
  (exact binomial for rates, Student t for means); the +-10% band around the model is shown beside it. One statistic
  for the sets: the 95% t-interval of the mean of the run means (on their logarithms), per side and for the ratio of a
  pair's two sides. Runs from the popup's Manual mode
  (test_mode "manual") are listed apart and compared with the side's automatic runs.

No buff comes from outside the set: the build, the set, the planned actions and the consumables give everything.

Legacy (the first method, kept for its records): --v1 runs with sequential early stopping, the control gate and the
day-score report; --lanes (two fights at once) implies it; --rescore re-judges its records.
    python tools/gauntlet/run.py specs.json --v1 --results results.jsonl [--scenarios boss,pack,defence,longday]
    python tools/gauntlet/run.py --report results.jsonl --specs specs.json --v1
    python tools/gauntlet/run.py --rescore results.jsonl[,more.jsonl] --specs specs.json
    python tools/gauntlet/run.py specs.json --lanes undercity_lanes --char A_UUID --char-b B_UUID --repeats 3
    python tools/gauntlet/run.py specs.json --sides a --lanes undercity_lanes --chars laezel=UUID,shadowheart=UUID

The rest of this text describes the legacy method.

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

Cast path: scripted casts go to the game as a player's click does, so the game checks and pays the costs (the off-hand
half of a dual-wield attack takes the bonus action), range and line of sight. A cast refused for range or sight makes
the run invalid (its movement was wrong), and so does a cast that spent other than its costs. --old-cast-path casts
through Osiris instead, with the checks skipped and the costs paid by the harness, for comparison.

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
REPEATS = 4               # valid runs per side
PART_TOL = 0.10           # a part outside model x (1 +- this) is flagged


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
    (run: [(round key, damage)]). Runs a person played from the popup's Manual mode do not count."""
    out = {"a": [], "b": []}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(x) for x in f if x.strip()]
    for r in recs:
        if r.get("pair") != i or r.get("side") not in out or r.get("side") not in p["specs"] or is_manual(r):
            continue
        if r.get("scenario") not in scen or not same_set(r, p, r["side"]):
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
    if getattr(a, "v1", False) or getattr(a, "lanes", None):
        return do_runs_v1(a)
    return do_runs_v2(a)


def do_runs_v1(a):
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
        for haste in (False,):
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
    return {"mode": "scripted", "scenario": sc, "act": spec["act"], "haste": False, "rounds": a.rounds, "arena": arena,
            "char": char, "label": f"pair{i}:{side}", "pair": i, "side": side, "respec": getattr(a, "respec", "real"),
            "retry_any_refusal": True if getattr(a, "retry_any_refusal", False) else None,
            "real_rolls": not getattr(a, "no_real_rolls", False), "boss": getattr(a, "boss", None),
            "player_cast": False if getattr(a, "old_cast_path", False) else None}


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
        for haste in (False,):
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
        for haste in (False,):
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
    if getattr(a, "v1", False):
        return report_v1(a)
    return report_v2(a)


def report_v1(a):
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


# ============================================================================================ method v2
# 97.5% quantiles of Student's t by degrees of freedom; between two keys the smaller one's (the wider interval).
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042}


def t975(df):
    if df >= 60:
        return 1.96
    keys = [k for k in sorted(T975) if k <= df]
    return T975[keys[-1]] if keys else T975[1]


def _logs(xs):
    return [math.log(x) for x in xs if x and x > 0]


def _var(ls):
    m = mean(ls)
    return sum((x - m) ** 2 for x in ls) / (len(ls) - 1)


def mean_interval(xs):
    """The one statistic: 95% t-interval of the mean of run means, computed on their logarithms (a ratio scale: a set
    twice as strong spreads twice as wide). -> (geometric mean, (lo, hi)) or (mean, None) below two positive runs."""
    ls = _logs(xs)
    if len(ls) < 2:
        return (mean(xs) if xs else None), None
    m, h = mean(ls), t975(len(ls) - 1) * math.sqrt(_var(ls) / len(ls))
    return math.exp(m), (math.exp(m - h), math.exp(m + h))


def ratio_interval(xa, xb):
    """The same statistic for a pair: ratio of the two sides' geometric means with its 95% interval (Welch on the
    logarithms). -> (ratio, (lo, hi)) or (ratio, None) below two positive runs a side."""
    la, lb = _logs(xa), _logs(xb)
    if not la or not lb:
        return None, None
    d = mean(la) - mean(lb)
    if len(la) < 2 or len(lb) < 2:
        return math.exp(d), None
    va, vb = _var(la) / len(la), _var(lb) / len(lb)
    se = math.sqrt(va + vb)
    if se == 0:
        return math.exp(d), (math.exp(d), math.exp(d))
    df = (va + vb) ** 2 / ((va ** 2 / (len(la) - 1)) + (vb ** 2 / (len(lb) - 1)))
    h = t975(int(df)) * se
    return math.exp(d), (math.exp(d - h), math.exp(d + h))


def is_manual(rec):
    """A run the player played from the popup's Manual mode (not one of the automatic runs the statistic counts)."""
    return rec.get("test_mode") == "manual"


def rec_pair_side(rec):
    req = rec.get("req") or {}
    return rec.get("pair", req.get("pair")), rec.get("side", req.get("side"))


T975_ALL = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
            11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
            20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
            29: 2.045, 30: 2.042}


def t_quantile975(df):
    """97.5% quantile of Student's t: the table to 30 degrees of freedom, beyond it the Cornish-Fisher expansion
    around the normal quantile (within 0.001 of the exact value from 30 on)."""
    if df < 1:
        return None
    if df <= 30:
        return T975_ALL[int(df)]
    z, v = 1.959964, float(df)
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160
    return z + g1 / v + g2 / v ** 2 + g3 / v ** 3 + g4 / v ** 4


def t_interval(xs):
    """95% Student t interval of the mean of xs -> (lo, hi), None below two values; never below 0 for samples that
    cannot be negative (damage, counts)."""
    if len(xs) < 2:
        return None
    m = mean(xs)
    h = t_quantile975(len(xs) - 1) * math.sqrt(_var(xs) / len(xs))
    return (max(0.0, m - h) if min(xs) >= 0 else m - h), m + h


def _binom_cdf(k, n, p):
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq, c = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    return min(1.0, sum(math.exp(c - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(k + 1)))


def binom_interval(k, n, alpha=0.05):
    """Exact (Clopper-Pearson) 95% interval of a rate k / n -> (lo, hi), None for n = 0. Found by bisection on the
    binomial distribution, so no beta quantile is needed."""
    if not n:
        return None

    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    lower = 0.0 if k <= 0 else solve(lambda p: 1.0 - _binom_cdf(k - 1, n, p) >= alpha / 2)
    upper = 1.0 if k >= n else solve(lambda p: _binom_cdf(k, n, p) <= alpha / 2)
    return lower, upper


def _poisson_cdf(k, mu):
    """P(X <= k) for X ~ Poisson(mu)."""
    if k < 0:
        return 0.0
    if mu <= 0.0:
        return 1.0
    return min(1.0, sum(math.exp(-mu + i * math.log(mu) - math.lgamma(i + 1)) for i in range(k + 1)))


def poisson_interval(k, n, alpha=0.05):
    """Exact (Garwood) 95% interval of a count per unit, k events over n units -> (lo, hi), None for n = 0. Unlike a
    t interval over the units it has width when every unit counted 0, so a rare event (a critical hit) seen in no
    round still leaves the model's small rate inside."""
    if not n:
        return None

    def solve(f, hi):
        lo = 0.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    top = k + 20.0 * math.sqrt(k + 1) + 20.0
    lower = 0.0 if k <= 0 else solve(lambda mu: 1.0 - _poisson_cdf(k - 1, mu) >= alpha / 2, top)
    upper = solve(lambda mu: _poisson_cdf(k, mu) <= alpha / 2, top)
    return lower / n, upper / n


def count_interval(xs):
    """95% interval of the mean count per round: Student t, but exact Poisson on the total when every round counted
    the same (a t interval of zero width would flag any other model value)."""
    if len(xs) < 2:
        return None
    if min(xs) == max(xs):
        return poisson_interval(int(round(sum(xs))), len(xs))
    return t_interval(xs)


def _round_rolls(rec):
    """The run's per-round roll records (G.rollTally), or None for a record from before they were counted."""
    rs = [(r.get("r"), r.get("rolls")) for r in rec.get("rounds") or [] if isinstance(r, dict)]
    if not any(isinstance(x, dict) and "n" in x for _r, x in rs):
        return None
    return rs


GAME_ROLL_CAUSES = ("Attack", "Offhand")
REACTION_MERGE_MS = 150    # damage rows this close after a roll's first row are that roll's (gauntlet.lua ROLL_MERGE_MS)
REACTION_HIT_MS = (300, 100)   # a hit-log row up to this much before / after a roll's first row is its roll's
SNEAK_GAP_MS = 20          # Sneak Attack's row comes this much or more after its roll's first row (gauntlet.lua)


def reaction_parts(rec):
    """The character's reactions in the enemies' turns, from the record's damage and hit rows: every row the character
    dealt after its own turn was released (the round's tm.released) or before its first turn (round 0). Attack rolls
    the way gauntlet.lua counts its own turn's (G.rollTally): a row of cause Attack / Offhand starts a roll unless it
    falls within REACTION_MERGE_MS of the last roll's first row, a 0-damage one is a miss; a roll is a critical hit when
    a hit-log row of the character near it says so; its Sneak Attack is its rows of the weapon's damage type (the type
    with the most damage among its rows within SNEAK_GAP_MS of the first) coming later than that, when a Sneak Attack
    reaction of the character came in that enemy turn (gauntlet.lua G.sneakPart). Per round lists, the damage being all
    the
    character's rows in those turns (the riders of cause Passive too). -> {rounds: {r: {n, landed, crit, dmg,
    sneak}}} or None when the record cannot tell the turns apart (no tm.released) or the character's rows."""
    rounds = [r for r in rec.get("rounds") or [] if isinstance(r, dict)]
    rel = {r.get("r"): (r.get("tm") or {}).get("released") for r in rounds}
    if not rounds or not all(rel.get(r.get("r")) is not None or r is rounds[-1] for r in rounds):
        return None
    dmg = rec.get("dmg") or []
    # the character: the source of the damage rows its own turns' rolls came from
    own_t = {(r.get("r"), p.get("t")) for r in rounds for p in ((r.get("rolls") or {}).get("per_roll") or [])}
    srcs = [d.get("source") for d in dmg if (d.get("r"), d.get("t")) in own_t and d.get("source")]
    if not srcs:
        return None
    me = max(set(srcs), key=srcs.count)

    def enemy_turn(d):
        r = d.get("r")
        return r == 0 or (rel.get(r) is not None and (d.get("t") or 0) > rel[r])
    rows = sorted((d for d in dmg if d.get("source") == me and d.get("target") != me and enemy_turn(d)),
                  key=lambda d: d.get("t") or 0)
    sneak_t = {}
    for r in rounds:
        for x in r.get("reactions_seen") or []:
            if x.get("who") == me and "SneakAttack" in str(x.get("interrupt")) and \
                    rel.get(r.get("r")) is not None and (x.get("t") or 0) > rel[r.get("r")]:
                sneak_t.setdefault(r.get("r"), []).append(x.get("t") or 0)
    hits = [h for h in rec.get("hits") or [] if h.get("source") == me]
    out = {}
    last = None
    for d in rows:
        R = out.setdefault(d.get("r"), {"n": 0, "landed": 0, "crit": 0, "dmg": 0, "sneak": 0})
        R["dmg"] += d.get("amount") or 0
        if d.get("cause") not in GAME_ROLL_CAUSES:
            continue
        t, amt = d.get("t") or 0, d.get("amount") or 0
        if last and last["r"] == d.get("r") and t - last["t"] <= REACTION_MERGE_MS:
            ty = d.get("type") or ""
            if t - last["t"] < SNEAK_GAP_MS:
                last["types"][ty] = last["types"].get(ty, 0) + amt
            elif amt > 0 and sneak_t.get(d.get("r")):
                wtype = max(sorted(last["types"]), key=lambda k: last["types"][k]) if last["types"] else ""
                if not wtype or not ty or ty == wtype:
                    R["sneak"] += amt
            continue
        last = {"r": d.get("r"), "t": t, "types": {d.get("type") or "": amt}}
        R["n"] += 1
        if amt > 0:
            R["landed"] += 1
            if any(h.get("crit") and -REACTION_HIT_MS[1] <= t - (h.get("t") or 0) <= REACTION_HIT_MS[0] for h in hits):
                R["crit"] += 1
        else:
            last = None
    return {"rounds": out}


def game_parts(rec):
    """One run's parts as the report compares them, counted per attack roll (a two-weapon shot rolls twice): rolls,
    landed rolls (critical hits included), critical hits, rolls with Advantage net of Disadvantage and with
    Disadvantage (of the rolls whose state the hit log gave: landed ones only so far, which leans towards
    Advantage), the character's own damage (summons left out), Sneak
    Attack's damage, the riders, and the samples the intervals are taken over: damage per landed roll and per round.
    The rolls are the character's own turn's (gauntlet.lua counts them as the turn ends); its reactions in the enemies'
    turns are counted apart (reaction_parts: react_* per round) and their damage taken out of the own turn's ("own"),
    so each part compares like with like with the model's split (model.attack_parts). A record from before rolls were
    counted falls back to its per-action outcomes, with no samples but the rounds'."""
    res = rec.get("results") or {}
    s = res.get("summary") or {}
    rounds = len(s.get("dealt") or []) or s.get("rounds") or 0
    dealt = list(s.get("dealt") or [])
    summon = list(s.get("summon_dealt") or [])
    own_r = [d - (summon[i] if i < len(summon) else 0) for i, d in enumerate(dealt)]
    own = sum(dealt) - (s.get("summon_damage") or 0)
    total = own
    rp = reaction_parts(rec)
    react = {"split": False}
    if rp is not None:
        order0 = [r.get("r") for r in rec.get("rounds") or [] if isinstance(r, dict)]
        per_r = [rp["rounds"].get(r) or {} for r in order0]
        # an enemy turn before round 1 counts with round 1
        pre = rp["rounds"].get(0) or {}
        if per_r and pre:
            per_r[0] = {k: (per_r[0].get(k) or 0) + (pre.get(k) or 0) for k in ("n", "landed", "crit", "dmg", "sneak")}
        react = {"split": True, "react_n": sum(x.get("n") or 0 for x in per_r),
                 "react_landed": sum(x.get("landed") or 0 for x in per_r),
                 "react_crit": sum(x.get("crit") or 0 for x in per_r),
                 "react_dmg": sum(x.get("dmg") or 0 for x in per_r),
                 "react_sneak": sum(x.get("sneak") or 0 for x in per_r),
                 "react_n_round": [x.get("n") or 0 for x in per_r],
                 "react_landed_round": [x.get("landed") or 0 for x in per_r],
                 "react_crit_round": [x.get("crit") or 0 for x in per_r],
                 "react_dmg_round": [x.get("dmg") or 0 for x in per_r],
                 "react_sneak_round": [x.get("sneak") or 0 for x in per_r]}
        own -= react["react_dmg"]
        own_r = [d - (per_r[i].get("dmg") or 0 if i < len(per_r) else 0) for i, d in enumerate(own_r)]
    hr = res.get("hit_riders") or {}
    hm, sa = hr.get("hunters_mark") or {}, hr.get("sneak_attack") or {}
    out = {"rounds": rounds, "own": own, "dpr": s.get("dpr") or 0.0, "hm_hits": hm.get("hits") or 0,
           "hm_rider": hm.get("rider") or 0, "sa_rider": sa.get("rider") or 0, "sa_all_turns": sa.get("turns") or 0,
           # a record from before the per-turn count has turns with Advantage only, under "turns"
           "sa_turns": sa.get("adv_turns", sa.get("turns")) or 0,
           "sa_rider_adv": sa.get("rider_adv", sa.get("rider")) or 0,
           "runs": 1, "run_dpr": [total / rounds if rounds else 0.0], "own_round": own_r, "total": total,
           "total_round": [d - (summon[i] if i < len(summon) else 0) for i, d in enumerate(dealt)], **react}
    rr = _round_rolls(rec)
    if rr is None:
        a = s.get("attacks") or {}
        n = (a.get("hit") or 0) + (a.get("crit") or 0) + (a.get("miss") or 0)
        out.update({"per_roll": False, "attacks": n, "landed": (a.get("hit") or 0) + (a.get("crit") or 0),
                    "crits": a.get("crit") or 0, "known": 0, "net_adv": 0, "dis": 0, "net_dis": 0, "sneak_dmg": 0,
                    "roll_dmg": 0})
        return out
    by_r = {r: x or {} for r, x in rr}
    order = [r for r, _x in rr]
    per = [by_r[r] for r in order]
    landed_dmg, landed_dmg_ns = [], []
    for x in per:
        for p in x.get("per_roll") or []:
            if p.get("hit"):
                landed_dmg.append(p.get("dmg") or 0)
                landed_dmg_ns.append((p.get("dmg") or 0) - (p.get("sneak") or 0))
    out.update({"per_roll": True, "attacks": sum(x.get("n") or 0 for x in per),
                "landed": sum(x.get("landed") or 0 for x in per), "crits": sum(x.get("crit") or 0 for x in per),
                "known": sum(x.get("known") or 0 for x in per), "net_adv": sum(x.get("net_adv") or 0 for x in per),
                "dis": sum(x.get("dis") or 0 for x in per),
                # net Disadvantage: Disadvantage with no Advantage to cancel it, of the rolls whose state is known
                "net_dis": sum(1 for x in per for p in x.get("per_roll") or []
                               if p.get("adv") is False and p.get("dis")),
                "sneak_dmg": sum(x.get("sneak_dmg") or 0 for x in per),
                "roll_dmg": sum(x.get("dmg") or 0 for x in per),
                "n_round": [x.get("n") or 0 for x in per], "landed_round": [x.get("landed") or 0 for x in per],
                "crit_round": [x.get("crit") or 0 for x in per],
                "sneak_round": [x.get("sneak_dmg") or 0 for x in per],
                "landed_dmg": landed_dmg, "landed_dmg_ns": landed_dmg_ns})
    return out


def _shifted(ci, d):
    return (ci[0] + d, ci[1] + d) if ci else None


def pooled(parts):
    """Runs' parts pooled: totals and samples over every run, then the values and their 95% intervals ("_ci"): exact
    binomial for the rates; exact Poisson for critical hits per round, and for the other rolls per round when every
    round counted the same; Student t for the means, over the landed rolls' damage for damage per hit (the damage of
    no roll, a status ticking, taken as fixed) and over the rounds for the per-round numbers, or over the run means
    for damage per round once there are three runs or more."""
    t, xs = {}, {}
    for p in parts:
        for k, v in p.items():
            if isinstance(v, list):
                xs.setdefault(k, []).extend(v)
            elif isinstance(v, bool):
                t[k] = t.get(k, True) and v
            else:
                t[k] = t.get(k, 0) + v
    r = t.get("rounds") or 0
    att, landed, known = t.get("attacks") or 0, t.get("landed") or 0, t.get("known") or 0
    own, sneak = t.get("own") or 0, t.get("sneak_dmg") or 0
    split = bool(t.get("split"))
    v = {"attacks": att / r if r else None, "hits": landed / r if r else None,
         "crits": (t.get("crits") or 0) / r if r else None,
         "hit_rate": landed / att if att else None, "crit_rate": (t.get("crits") or 0) / att if att else None,
         "adv_rate": (t.get("net_adv") or 0) / known if known else None,
         "dis_rate": (t.get("dis") or 0) / known if known else None,
         "net_dis_rate": (t.get("net_dis") or 0) / known if known else None,
         "dmg_per_hit": own / landed if landed else None,
         "dmg_per_hit_no_sneak": (own - sneak) / landed if landed and t.get("per_roll") else None,
         "sneak": sneak / r if r and t.get("per_roll") else None,
         "hm_share": t["hm_rider"] / t["hm_hits"] if t.get("hm_hits") else None,
         "sa_share": t["sa_rider_adv"] / t["sa_turns"] if t.get("sa_turns") else None,
         "dpr": (t.get("total") or 0) / r if r else None,
         "own_dpr": own / r if r and split else None,
         "split": split,
         "sa_counts": (t.get("sa_rider") or 0, t.get("sa_turns") or 0, t.get("sa_all_turns") or 0)}
    for key in ("n", "landed", "crit", "dmg", "sneak"):
        v["react_" + {"n": "attacks", "landed": "hits", "crit": "crits"}.get(key, key)] = \
            (t.get("react_" + key) or 0) / r if r and split else None
    ci = {}
    if att:
        ci["hit_rate"] = binom_interval(landed, att)
        ci["crit_rate"] = binom_interval(t.get("crits") or 0, att)
    if known:
        ci["adv_rate"] = binom_interval(t.get("net_adv") or 0, known)
        ci["dis_rate"] = binom_interval(t.get("dis") or 0, known)
        ci["net_dis_rate"] = binom_interval(t.get("net_dis") or 0, known)
    ci["hm_share"] = binom_interval(t.get("hm_rider") or 0, t.get("hm_hits") or 0)
    ci["sa_share"] = binom_interval(t.get("sa_rider_adv") or 0, t.get("sa_turns") or 0)
    for key, sample in (("attacks", "n_round"), ("hits", "landed_round"), ("react_attacks", "react_n_round"),
                        ("react_hits", "react_landed_round")):
        ci[key] = count_interval(xs.get(sample) or [])
    # critical hits are rare enough that a few rounds with one give a t interval far too narrow
    for key, sample in (("crits", "crit_round"), ("react_crits", "react_crit_round")):
        rs = xs.get(sample) or []
        ci[key] = poisson_interval(int(round(sum(rs))), len(rs)) if len(rs) >= 2 else None
    for key, sample in (("sneak", "sneak_round"), ("react_dmg", "react_dmg_round"),
                        ("react_sneak", "react_sneak_round")):
        ci[key] = t_interval(xs.get(sample) or [])
    if landed and xs.get("landed_dmg"):
        # the damage of no roll (a status ticking, a surface) per landed roll, added to the rolls' own interval
        extra = (own - (t.get("roll_dmg") or 0)) / landed
        ci["dmg_per_hit"] = _shifted(t_interval(xs["landed_dmg"]), extra)
        ci["dmg_per_hit_no_sneak"] = _shifted(t_interval(xs.get("landed_dmg_ns") or []), extra)
    runs = xs.get("run_dpr") or []
    ci["dpr"] = t_interval(runs) if len(runs) >= 3 else t_interval(xs.get("total_round") or xs.get("own_round") or [])
    if split:
        ci["own_dpr"] = t_interval(xs.get("own_round") or [])
    v["_ci"] = ci
    return v


PARTS = [("attacks", "own turn: attack rolls per round", "attacks", "{:.2f}"),
         ("hits", "own turn: landed rolls per round", "hits", "{:.2f}"),
         ("crits", "own turn: critical hits per round", "crits", "{:.2f}"),
         ("hit_rate", "own turn: hit rate (per roll)", "hit_rate", "{:.0%}"),
         ("crit_rate", "own turn: critical hits per roll", "crit_rate", "{:.1%}"),
         ("adv_rate", "own turn: rolls with net Advantage (logged rolls)", "adv_rate", "{:.0%}"),
         ("dis_rate", "own turn: rolls with Disadvantage, cancelled or not (logged rolls)", "dis_any_rate", "{:.0%}"),
         ("net_dis_rate", "own turn: rolls with net Disadvantage (logged rolls)", "dis_rate", "{:.0%}"),
         ("dmg_per_hit", "own turn: damage per landed roll", "dmg_per_hit", "{:.1f}"),
         ("dmg_per_hit_no_sneak", "own turn: damage per landed roll, no Sneak Attack", "dmg_per_hit_no_sneak",
          "{:.1f}"),
         ("sneak", "own turn: Sneak Attack damage per round", "sneak", "{:.2f}"),
         ("own_dpr", "own turn: damage per round", "own_dpr", "{:.1f}"),
         ("react_attacks", "reactions: attack rolls per round", "react_attacks", "{:.2f}"),
         ("react_hits", "reactions: landed rolls per round", "react_hits", "{:.2f}"),
         ("react_crits", "reactions: critical hits per round", "react_crits", "{:.2f}"),
         ("react_dmg", "reactions: damage per round", "react_dmg", "{:.2f}"),
         ("react_sneak", "reactions: Sneak Attack damage per round", "react_sneak", "{:.2f}"),
         ("hm_share", "Hunter's Mark on landed hits", None, "{:.0%}"),
         ("sa_share", "Sneak Attack in turns with the charge and net Advantage", None, "{:.0%}"),
         ("dpr", "damage per round (own turn and reactions)", "dpr", "{:.1f}")]
# parts the model counts with the reactions in when its numbers come from before the split (no "split" in expect.boss):
# not compared, the game's being the own turn's alone
SPLIT_PARTS = {"attacks", "hits", "crits", "hit_rate", "crit_rate", "adv_rate", "dis_rate", "net_dis_rate",
               "dmg_per_hit", "dmg_per_hit_no_sneak", "sneak", "own_dpr", "react_attacks", "react_hits", "react_crits", "react_dmg",
               "react_sneak"}


def compare_parts(game, model, tol=PART_TOL):
    """Rows [(key, label, game, model, ratio, flag, interval, band)] in PARTS order. flag "OUTSIDE" when the model's
    value lies outside the game's 95% interval (a single run's noise is no gap); a part with no interval (a record
    from before rolls were counted) falls back to the +-tol band. band: "in" / "out", whether the game lies within the
    model x (1 +- tol), shown beside it. A part the model does not give is shown, not compared."""
    out = []
    ci_all = game.get("_ci") or {}
    # like with like: both sides split into own turn and reactions, or neither compared
    split = bool((model or {}).get("split")) and bool(game.get("split"))
    for key, label, mkey, _fmt in PARTS:
        g, m = game.get(key), (model or {}).get(mkey) if mkey else None
        if key in SPLIT_PARTS and not split:
            m = None
        ratio = g / m if g is not None and m else None
        ci = ci_all.get(key)
        band = ("in" if abs(ratio - 1) <= tol else "out") if ratio is not None else ""
        if m is None or g is None:
            flag = ""
        elif ci:
            flag = "OUTSIDE" if not (ci[0] - 1e-12 <= m <= ci[1] + 1e-12) else ""
        else:
            flag = "OUTSIDE" if band == "out" else ""
        out.append((key, label, g, m, ratio, flag, ci, band))
    return out


def _band(fmt, m, tol=PART_TOL):
    return f"{_f(fmt, m * (1 - tol))}-{_f(fmt, m * (1 + tol))}" if m else "-"


def _ci(fmt, ci):
    return f"{_f(fmt, ci[0])}-{_f(fmt, ci[1])}" if ci else "-"


def _f(fmt, v):
    return fmt.format(v) if v is not None else "-"


def report_v2(a):
    with open(a.specs, encoding="utf-8") as f:
        pairs = json.load(f)
    recs = [json.loads(x) for x in open(a.report, encoding="utf-8") if x.strip()]
    want_rolls = not getattr(a, "no_real_rolls", False)
    auto, manual, invalid, other_rolls = {}, {}, [], 0
    for r in recs:
        if r.get("mode") != "scripted" and "error" not in r:
            continue
        if rolls_of(r) != want_rolls:
            other_rolls += 1
            continue
        i, side = rec_pair_side(r)
        ok, causes = run_validity(r)
        tag = "manual" if is_manual(r) else "automatic"
        if not ok:
            invalid.append(f"- pair {i} {side} ({tag}) {r.get('run_id') or ''}: {'; '.join(causes)}")
            continue
        if r.get("scenario", "boss") != "boss":
            continue
        (manual if is_manual(r) else auto).setdefault((i, side), []).append(r)
    L, out = [], {"sides": {}, "pairs": {}}
    for i, p in enumerate(pairs):
        means = {}
        for side in ("a", "b"):
            runs = auto.get((i, side)) or []
            man = manual.get((i, side)) or []
            if not runs and not man:
                continue
            spec = p["specs"][side]
            boss = (spec.get("expect") or {}).get("boss")
            xs = [game_parts(r)["dpr"] for r in runs]
            means[side] = xs
            gm, ci = mean_interval(xs)
            L.append(f"### Pair {i} side {side}: {p.get('char')} {p.get('build')} A{p.get('act')}, set {spec.get('set')}")
            if not boss:
                L.append("Model boss numbers missing in the spec (plan.py before the boss scenario was exported): "
                         "re-run plan.py. Day numbers are not compared.")
            ratio_ci = ci and boss and boss.get("dpr") and (ci[0] / boss["dpr"], ci[1] / boss["dpr"])
            L.append(f"{len(runs)} valid automatic run(s) (wanted {getattr(a, 'repeats', REPEATS)}): damage per round "
                     f"{_f('{:.1f}', gm)}" + (f" (95% {ci[0]:.1f}-{ci[1]:.1f})" if ci else "") +
                     (f", model boss {boss['dpr']:.1f}" if boss and boss.get("dpr") else "") +
                     (f", game/model 95% {ratio_ci[0]:.2f}-{ratio_ci[1]:.2f}" if ratio_ci else ""))
            L.append("run means: " + ", ".join(f"{x:.1f}" for x in xs))
            gp = pooled([game_parts(r) for r in runs]) if runs else {}
            rows = compare_parts(gp, boss) if runs else []
            if rows:
                L += ["", f"| Part | Game | Game 95% | Model (boss) | Game / model | Model +-{PART_TOL:.0%} | |",
                      "|---|---|---|---|---|---|---|"]
                for key, label, g, m, ratio, flag, pci, band in rows:
                    fmt = dict((k, f_) for k, _l, _m, f_ in PARTS)[key]
                    L.append(f"| {label} | {_f(fmt, g)} | {_ci(fmt, pci)} | {_f(fmt, m)} | {_f('{:.2f}', ratio)} | "
                             f"{_band(fmt, m)}{' (game ' + band + ')' if band else ''} | {flag} |")
                if not (boss or {}).get("split") or not gp.get("split"):
                    L.append("\nOwn-turn and reaction parts not compared: " + (
                        "the model's numbers count the reactions with the own turn (a spec from before the split): "
                        "re-run plan.py." if not (boss or {}).get("split") else
                        "the record cannot tell the enemies' turns from the character's (no turn end times)."))
                sa_n, sa_adv, sa_all = gp.get("sa_counts") or (0, 0, 0)
                L.append(f"\nSneak Attack: {sa_n} trigger(s) / {sa_adv} turn(s) with net Advantage / {sa_all} turn(s). "
                         "OUTSIDE: the model's value is outside the game's 95% interval (exact binomial for rates, "
                         "exact Poisson for critical hits per round and for any count the same every round, Student t "
                         "for the other means).")
            out["sides"][(i, side)] = {"n": len(runs), "mean": gm, "ci": ci, "rows": rows,
                                       "outside": [r_[0] for r_ in rows if r_[5]]}
            for r in runs:
                rl = round_lines(r)
                if rl:
                    L += ["", f"Run {r.get('run_id')}, per round against the strategy (the expectation for the state "
                              "each turn started in; a round cut short compared on its own turn only):", ""] + rl
            if man:
                L += ["", f"Manual runs (played by hand from the popup), against the {len(runs)} automatic run(s):"]
                base = pooled([game_parts(r) for r in runs]) if runs else {}
                for r in man:
                    gp = pooled([game_parts(r)])
                    cmp_ = compare_parts(gp, base)
                    L.append(f"- {r.get('run_id')}: " + ", ".join(
                        f"{label} {_f(dict((k, f_) for k, _l, _m, f_ in PARTS)[key], g)}"
                        + (f" (x{ratio:.2f}{' OUTSIDE' if flag else ''})" if ratio else "")
                        for key, label, g, _m, ratio, flag, _ci_, _b in cmp_))
            L.append("")
        if means.get("a") and means.get("b"):
            rr, rci = ratio_interval(means["a"], means["b"])
            ba = ((p["specs"]["a"].get("expect") or {}).get("boss") or {}).get("dpr")
            bb = ((p["specs"]["b"].get("expect") or {}).get("boss") or {}).get("dpr")
            model = ba / bb if ba and bb else None
            out["pairs"][i] = {"ratio": rr, "ci": rci, "model": model}
            L.append(f"Pair {i} a / b damage per round: {_f('{:.2f}', rr)}" +
                     (f" (95% {rci[0]:.2f}-{rci[1]:.2f})" if rci else "") +
                     (f", model boss {model:.2f}" if model else "") +
                     (" - the model's ratio is inside the interval" if rci and model and rci[0] <= model <= rci[1]
                      else " - the model's ratio is OUTSIDE the interval" if rci and model else ""))
            L.append("")
    text = "\n".join(L).rstrip() + "\n"
    if invalid:
        text += "\nInvalid runs (left out):\n" + "\n".join(invalid) + "\n"
    if other_rolls:
        text += (f"\n{other_rolls} run(s) {'without' if want_rolls else 'with'} real rolls left out (not comparable; "
                 f"{'drop' if want_rolls else 'use'} --no-real-rolls to report them).\n")
    print(text)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(text)
    return out


def round_rows(rec):
    """Per round of one run, the game against the strategy (expect.strategy from plan.py --strategy, the record's
    expect): [{r, own, react, total, cut, state, decision, outside, st_own, st_own_sd, st_round, st_round_sd, mean,
    mean_sd, likely, likely_sd, game, model, model_sd, z}]. own / react / total: the game's damage in the character's
    turn, in the enemies' turn after it (reaction_parts) and both. A round with no released turn (the run ended
    after its own turn: fail-fast) is cut: its enemies' turn never came. st_*: the strategy's expectation for the
    state the turn started in (the policy's own turn and round), when the run followed a policy; mean: the round's
    expectation over every course of the fight, likely: on the most likely course. The comparison (game, model,
    model_sd, z) is the whole round against the state's round expectation, or the own turn against the state's own
    one when the round was cut; without a policy against mean (own turn only when cut: none). [] when the record
    has no rounds."""
    rounds = [R for R in rec.get("rounds") or [] if isinstance(R, dict)]
    if not rounds:
        return []
    s = (rec.get("results") or {}).get("summary") or {}
    dealt = s.get("dealt") or []
    rp = reaction_parts(rec)
    strat = ((rec.get("expect") or {}).get("strategy") or {})
    by_round = {x.get("round"): x for x in strat.get("rounds") or []}
    out = []
    for i, R in enumerate(rounds):
        r = R.get("r")
        total = dealt[i] if i < len(dealt) else None
        react = ((rp or {}).get("rounds") or {}).get(r, {}).get("dmg", 0) if rp else None
        if i == 0 and rp and (rp.get("rounds") or {}).get(0):
            react = (react or 0) + (rp["rounds"][0].get("dmg") or 0)
        own = total - react if total is not None and react is not None else None
        cut = not (R.get("tm") or {}).get("released")
        pol = R.get("policy") or {}
        ex = by_round.get(r) or {}
        row = {"r": r, "own": own, "react": react, "total": total, "cut": cut, "state": pol.get("key"),
               "decision": pol.get("decision"), "outside": bool(pol.get("outside")), "st_own": pol.get("own"),
               "st_own_sd": pol.get("own_sd"), "st_round": pol.get("round"), "st_round_sd": pol.get("round_sd"),
               "mean": ex.get("mean"), "mean_sd": ex.get("mean_sd"),
               # a spec from before "likely": its dmg / sd were the most likely course's
               "likely": ex.get("likely", ex.get("dmg")), "likely_sd": ex.get("likely_sd", ex.get("sd")),
               "game": None, "model": None, "model_sd": None, "z": None}
        if pol.get("own") is not None:
            if cut:
                row.update(game=own, model=pol["own"], model_sd=pol.get("own_sd"))
            else:
                row.update(game=total, model=pol.get("round"), model_sd=pol.get("round_sd"))
        elif ex.get("mean") is not None and not cut:
            row.update(game=total, model=ex["mean"], model_sd=ex.get("mean_sd"))
        if row["game"] is not None and row["model"] is not None and row["model_sd"]:
            row["z"] = (row["game"] - row["model"]) / row["model_sd"]
        out.append(row)
    return out


def round_lines(rec):
    """round_rows as a markdown table and the run's total against the expectation, for the report and the turn list.
    -> lines ([] when the record has no strategy expectation and followed no policy)."""
    rows = round_rows(rec)
    strat = (rec.get("expect") or {}).get("strategy") or {}
    if not rows or not (strat or any(x["state"] for x in rows)):
        return []
    L = ["| Round | Game: own turn / reactions / round | State the turn started in -> decision | Compared: game / "
         "model for that state (sd), z | Round expectation, every course (sd) | Most likely course (sd) |",
         "|---|---|---|---|---|---|"]

    def f(v, fmt="{:.1f}"):
        return fmt.format(v) if v is not None else "-"
    for x in rows:
        state = ("OUTSIDE the policy table: " + x["state"]) if x["outside"] else \
            (f"{x['state']} -> {x['decision']}" if x["state"] else "no policy")
        what = "own turn" if x["cut"] else "round"
        cmp_ = (f"{what}: {f(x['game'], '{:.0f}')} / {f(x['model'])} ({f(x['model_sd'])}), z {f(x['z'], '{:+.2f}')}"
                if x["game"] is not None and x["model"] is not None else "-")
        game = (f"{f(x['own'], '{:.0f}')} / {'cut (no enemy turn)' if x['cut'] else f(x['react'], '{:.0f}')} / "
                f"{f(x['total'], '{:.0f}')}")
        L.append(f"| {x['r']} | {game} | {state} | {cmp_} | {f(x['mean'])} ({f(x['mean_sd'])}) | "
                 f"{f(x['likely'])} ({f(x['likely_sd'])}) |")
    full = [x for x in rows if not x["cut"] and x["total"] is not None]
    L.append("")
    if full:
        st = [x["st_round"] for x in full if x["st_round"] is not None]
        means = [x["mean"] for x in full if x["mean"] is not None]
        L.append(f"Full rounds ({', '.join(str(x['r']) for x in full)}): game {sum(x['total'] for x in full):.0f}" +
                 (f"; expectation for the states the turns started in {sum(st):.1f}" if len(st) == len(full) else "") +
                 (f"; the rounds' expectation over every course {sum(means):.1f}" if len(means) == len(full) else "") +
                 ".")
    for x in rows:
        if x["cut"]:
            L.append(f"Round {x['r']} cut short after its own turn (no enemy turn): own turn {f(x['own'], '{:.0f}')}" +
                     (f" against {f(x['st_own'])} (sd {f(x['st_own_sd'])}) for its state" if x["st_own"] is not None
                      else "") + ".")
    if strat.get("total") is not None:
        L.append(f"The fight's expectation: {strat['total']} (sd {strat.get('sd')}) over "
                 f"{len(strat.get('rounds') or [])} rounds.")
    return L


def _short(u):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", str(u or ""))
    return m.group(1) if m else (u or None)


def _roll_text(i, x):
    adv = " Advantage" if x.get("adv") and not x.get("dis") else " Disadvantage" if x.get("dis") and not x.get("adv") \
        else " Advantage + Disadvantage" if x.get("adv") and x.get("dis") else ""
    nat = f" {x.get('nat')}" + (f"/{x.get('nat2')}" if x.get("nat2") else "") + \
        (f" -> {x.get('total')}" if x.get("total") is not None else "") if x.get("nat") is not None else ""
    return f"{'main' if i == 0 else 'off-hand'} {x.get('outcome')}{nat}{adv}"


def turn_list(rec):
    """What the character did, turn by turn, for a person to replay the run by hand: per round the state the turn
    started in and the policy's decision (a run that followed one), the spell or attack, its target and its result
    with each attack roll (a toggled attack's off-hand half is a roll of its own: natural roll, total, Advantage /
    Disadvantage), a scripted turn's planned actions with their outcome or a player's turn its casts and the hits they
    made, the enemies' attack rolls, then the round's damage; last the rounds against the strategy (round_lines).
    -> lines (markdown)."""
    res = rec.get("results") or {}
    me = _short((rec.get("req") or {}).get("char"))
    dealt = (res.get("summary") or {}).get("dealt") or []
    sid = rec.get("spec_id") or {}
    L = [f"## Run {rec.get('run_id') or rec.get('run')} - {sid.get('set_name') or ''} "
         f"({rec.get('test_mode') or rec.get('mode')}, {'valid' if rec.get('valid') else 'INVALID'})"]
    hits = rec.get("hits") or []
    for R in rec.get("rounds") or []:
        r = R.get("r")
        L.append(f"Round {r}" + (f" - {dealt[r - 1]:.0f} damage" if r and r - 1 < len(dealt) else "") +
                 (" (down)" if R.get("downed") else ""))
        pol = R.get("policy") or {}
        if pol.get("key"):
            L.append(f"  state: {pol['key']}" + (" - OUTSIDE the policy table" if pol.get("outside") else
                                                  f" -> {pol.get('decision')}"))
        acts = R.get("actions") or []
        k = 0
        for x in acts:
            if str(x.get("result", "")).startswith("skipped"):
                continue
            k += 1
            res_ = x.get("result") or "?"
            out_ = x.get("outcome")
            rolls = x.get("rolls") or []
            L.append(f"  {k}. {x.get('spell')} -> {x.get('target') or '-'}: "
                     f"{out_ if out_ and res_ == 'done' else res_}" + (f" ({x.get('why')})" if x.get("why") else "") +
                     (" - rolls: " + ", ".join(_roll_text(i, y) for i, y in enumerate(rolls)) if rolls else ""))
        if not acts:
            for c in R.get("casts") or []:
                if me and _short(c.get("who")) != me:
                    continue
                k += 1
                L.append(f"  {k}. {c.get('spell')}")
            mine = [h for h in hits if h.get("r") == r and (not me or _short(h.get("source")) == me)]
            if mine:
                L.append("     hits: " + ", ".join(
                    ("crit" if h.get("crit") else "miss" if h.get("miss") else "hit") +
                    (f" {h.get('total')}" if h.get("total") is not None else "") +
                    (f" ({h.get('spell')})" if h.get("spell") else "") for h in mine))
        if k == 0:
            L.append("  (nothing)")
        foe = [x for x in (((res.get("summary") or {}).get("enemy_rolls") or {}).get("per_roll") or [])
               if x.get("r") == r]
        if foe:
            L.append("  enemies' attack rolls: " + ", ".join(
                f"{x.get('outcome')}" + (f" {x.get('nat')}" + (f"/{x.get('nat2')}" if x.get("nat2") else "") +
                                         (f" -> {x.get('total')}" if x.get("total") is not None else "")
                                         if x.get("nat") is not None else "") +
                (" Disadvantage" if x.get("dis") else "") + (" Advantage" if x.get("adv") else "") for x in foe))
    rl = round_lines(rec)
    if rl:
        L += ["", "Rounds against the strategy:", ""] + rl
    return L


def turns_path(results, rec):
    stem = os.path.splitext(results)[0]
    rid = re.sub(r"[^\w.-]", "_", str(rec.get("run_id") or rec.get("run") or "run"))
    return os.path.join(stem + "_turns", rid + ".md")


def write_turns(results, rec):
    if not rec.get("rounds"):
        return None
    path = turns_path(results, rec)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(turn_list(rec)) + "\n")
    return path


def turns_report(a):
    recs = [json.loads(x) for x in open(a.turns, encoding="utf-8") if x.strip()]
    L = []
    for r in recs:
        if a.run and str(r.get("run_id")) != a.run:
            continue
        if r.get("rounds"):
            L += turn_list(r) + [""]
    text = "\n".join(L)
    print(text)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(text)
    return L


def do_runs_v2(a):
    """Every asked side until it has --repeats valid runs (those already in --results count), at most twice as many
    tries, one run after the other, each through the popup's Start in Automatic mode."""
    with open(a.specs, encoding="utf-8") as f:
        pairs = json.load(f)
    only = {int(x) for x in a.only.split(",")} if a.only else None
    scen = ["boss"]
    sides = tuple(a.sides.split(","))
    print(engine.load())
    # the popup's mode, as the first step after loading (engine.run sets it with every Start as well)
    print("popup mode:", engine.set_mode("automatic"))
    want = max(1, a.repeats)
    for i in [i for i in range(len(pairs)) if only is None or i in only]:
        for side in [x for x in sides if x in pairs[i]["specs"]]:
            have = len(prior_runs(a.results, i, pairs[i], scen, not a.no_real_rolls)[side])
            if have:
                print(f"pair {i} {side}: {have} valid run(s) in the results already")
            tries = 0
            while have < want and tries < 2 * want:
                tries += 1
                runs, recs = run_side(a, i, pairs[i], side, scen, {"repeat": have})
                for r in recs:
                    path = write_turns(a.results, r)
                    if path:
                        print(f"  turns: {path}")
                have += len(runs)
                why = next((deterministic(r) for r in recs if deterministic(r)), None)
                if not runs and why:
                    print(f"  pair {i} {side}: not repeated, the run failed for a reason every run would meet: {why}")
                    not_repeated(a, i, side, scen, why)
                    break
            if have < want:
                print(f"  pair {i} {side}: {have} of {want} valid runs after {tries} tries")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="?")
    ap.add_argument("--specs", dest="specs2")
    ap.add_argument("--results", default="gauntlet_results.jsonl")
    ap.add_argument("--scenarios", default="boss", help="legacy (--v1): boss,pack,defence,longday")
    ap.add_argument("--only")
    ap.add_argument("--repeats", type=int, default=REPEATS, help="valid runs per side (default 4; the ones already "
                    "in --results count; at most twice as many tries). --v1: up to this many, at most 3, stopping "
                    "early once the 95%% interval of the two sides' ratio is decisive")
    ap.add_argument("--v1", action="store_true", help="the legacy method: early stopping, control gate, day report")
    ap.add_argument("--rounds", type=int, default=16)
    ap.add_argument("--sides", default="a,b", help="a, b or a,b: one set of each pair only (e.g. a reload between)")
    ap.add_argument("--arena", help="a fixed spot from tools/gauntlet/arenas.json (default: where the character stands)")
    ap.add_argument("--boss", help="uuid of the save's own boss in the arena (re-forced every run, never deleted); "
                    "default: a new enemy every run")
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
    ap.add_argument("--old-cast-path", action="store_true",
                    help="cast through Osiris with the engine's cost, range and sight checks skipped and the costs paid "
                    "by the harness, as runs before the player cast path did; only for comparison")
    ap.add_argument("--report")
    ap.add_argument("--turns", help="a results file: the turn list of every run in it (or --run RUN_ID only)")
    ap.add_argument("--run", help="with --turns: one run id")
    ap.add_argument("--rescore", help="older run records (comma-separated files): re-judge them and run the gate")
    ap.add_argument("--md")
    ap.add_argument("--control-tol", type=float, default=CONTROL_TOL,
                    help="largest difference allowed between a control pair's two sets (share, default 0.15)")
    a = ap.parse_args(argv)
    a.specs = a.specs or a.specs2
    if a.rescore:
        with open(a.specs, encoding="utf-8") as f:
            return rescore_report(a.rescore.split(","), json.load(f), a.control_tol)
    if a.turns:
        return turns_report(a)
    if a.report:
        return report(a)
    else:
        do_runs(a)


if __name__ == "__main__":
    main()
