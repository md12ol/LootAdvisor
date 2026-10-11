"""Pick gauntlet pairs: the optimizer's set vs the best research set the optimizer compared it with, and the control.

    python tools/gauntlet/pairs.py --optimizer DIR --optimized optimized.json \
        --select shadowheart:lightcleric:3,wyll:lockadin:3[:1] [--control] [--test-plans FILE] --out pairs.json
    python tools/gauntlet/pairs.py --optimizer DIR --optimized optimized.json \
        --find-control astarion:gloomassassin:3,shadowheart:lightcleric:3

A control pair is two sets the model rates alike on BOTH sides of the fight: damage per round within CONTROL_EQ, and
the same damage taken (AC, hit points, saving throws, resistances, damage reduction equal; damage taken per round and
rounds survived within CONTROL_EQ). With real hit points a pair alike in damage only is no control: the set that
takes more damage goes down sooner and fights fewer rounds. --find-control searches the optimizer's sets and the
research sets of the given builds for such pairs: a set against itself with one or two items swapped for items the
model values the same (each item adds damage, neither grants an action of its own, so both sets run the same round
plan). CONTROL is the pair chosen from that search; --control puts it first in the output, checked again against
the current model.

--select compares the optimizer's set with the research set the optimizer compared it with, or with the research set
named by a fourth field (its number, "1" for <char>.<build>.a<act>.1). Each side names its test plan ("respec"): the
optimizer tunes the ability scores, feats and fighting styles to each set, a test character is respecced to that
plan, and the model's numbers and the gauntlet's setup check follow the same respec (TEST_PLANS, --test-plans).
"""
import argparse
import itertools
import json
import os
import re
import sys

CONTROL_EQ = 0.05          # the model's two numbers (damage, damage taken, rounds survived) within this share
CONTROL_CLOSE = 0.02       # a swap this close in damage is preferred
MIN_VALUE = 1.0            # an item the control swaps adds at least this much damage per round in the model

# The control pair (chosen with --find-control from the optimizer run of 2026-10-10 06:36): Astarion, gloom stalker
# assassin, Act 3, the research set "Celestial Volley" against the same set with Caustic Band in place of the Strange
# Conduit Ring. Both rings add damage to weapon attacks and grant no action; everything defensive is the same.
CONTROL = {"char": "astarion", "build": "gloomassassin", "act": 3, "base": "Celestial Volley",
           "swaps": {"Ring2": "MAG_Acid_AcidDamageOnWeaponAttack_Ring"}}


TEST_PLANS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "optimizer", ".cache", "test_plans.json")


# ------------------------------------------------------------------------------------------------ respec
def load_test_plans(path=TEST_PLANS):
    """{test plan id: plan} from the optimizer's test plans; {} when the file is missing."""
    try:
        with open(path, encoding="utf-8") as f:
            return {p["id"]: p for p in json.load(f).get("plans") or []}
    except OSError:
        return {}


def tuned_respec(W, model, tune, plans, pid):
    """The respec of test plan pid as the model takes it (abilities, feats, fighting styles, cantrip), re-derived by
    the optimizer's tuner from the plan's gear; None when the plan keeps the build's own picks. The tuner is
    deterministic, but the data may have changed since the plans were written: the derived ability scores must equal
    the plan's, else SystemExit (a spec would check the character against a respec it was never given)."""
    p = plans.get(pid)
    if p is None:
        raise SystemExit(f"no test plan {pid!r}")
    rs = p.get("respec") or {}
    r = None
    if rs.get("tuned"):
        lo = {k: v["id"] for k, v in (p.get("gear") or {}).items() if v and v.get("id")}
        r = tune(W, p["char"], p["build"], p["act"], lo)["respec"]
    st = model.State(W, p["char"], p["build"], p["act"], {}, {}, respec=r)
    got, want = dict(st.sheet["abBase"]), rs.get("abilities")
    if want and got != want:
        raise SystemExit(f"test plan {pid}: the tuner now gives {got}, the plan says {want}")
    return r


# ------------------------------------------------------------------------------------------------ model numbers
def numbers(r):
    """The model's numbers of one evaluated set: damage dealt and everything that decides the damage taken."""
    d = r.dur
    return {"dpr": round(r.dpr, 2), "taken": round(d["incoming"], 3), "R": round(d["R"], 2), "ac": d["ac"],
            "hp": d["hp"], "saves": {k: round(float(v), 1) for k, v in sorted((d.get("saves") or {}).items())},
            "dr": round(float(d.get("dr") or 0), 2), "resist": dict(sorted((d.get("mult") or {}).items())),
            "lost": round(getattr(r, "lost", 0.0) or 0.0, 3)}


def _rel(x, y):
    return abs(x / y - 1) if y else (0.0 if not x else 1.0)


def control_check(na, nb, tol=CONTROL_EQ):
    """Does the model rate the two sets alike on both sides of the fight? -> (ok, [reasons it does not])."""
    why = []
    if _rel(na["dpr"], nb["dpr"]) > tol:
        why.append(f"damage per round {na['dpr']} vs {nb['dpr']}")
    for k in ("ac", "hp", "dr"):
        if na[k] != nb[k]:
            why.append(f"{k} {na[k]} vs {nb[k]}")
    if na["saves"] != nb["saves"]:
        why.append(f"saving throws {na['saves']} vs {nb['saves']}")
    if na["resist"] != nb["resist"]:
        why.append(f"resistances {na['resist']} vs {nb['resist']}")
    if _rel(na["taken"], nb["taken"]) > tol:
        why.append(f"damage taken per round {na['taken']} vs {nb['taken']}")
    if _rel(na["R"], nb["R"]) > tol:
        why.append(f"rounds survived {na['R']} vs {nb['R']}")
    return not why, why


def find_controls(score, bases, alternatives, has_action, tol=CONTROL_EQ, max_swaps=2, idle_slots=(),
                  legal=lambda lo: True):
    """Control candidates: each base set against itself with one or two items swapped. score(loadout) evaluates a set;
    bases = [(name, loadout)]; alternatives(slot) = the items that may go in a slot; has_action(item) = the item grants
    an action of its own (left out: the two sets would run different round plans); idle_slots = slots the round plan
    never uses (the melee weapons of a ranged build: a swap there tests nothing); legal(loadout) = the game lets the
    set be worn (no two-handed weapon beside an off-hand). A swap counts when both items add at least MIN_VALUE damage
    per round to the set and the defence is unchanged. -> candidates, best first."""
    out = []
    for name, lo in bases:
        r0 = score(lo)
        n0 = numbers(r0)
        singles = []
        for slot, cur in sorted(lo.items()):
            if slot in idle_slots or has_action(cur):
                continue
            empty = dict(lo)
            empty.pop(slot)
            base_value = r0.dpr - score(empty).dpr
            if base_value < MIN_VALUE:
                continue
            for alt in alternatives(slot):
                if alt == cur or alt in lo.values() or has_action(alt):
                    continue
                lo2 = dict(lo, **{slot: alt})
                r = score(lo2)
                if getattr(r, "unknown", None):
                    continue
                n = numbers(r)
                ok, _why = control_check(n0, n, tol)
                if ok and r.dpr - (r0.dpr - base_value) >= MIN_VALUE:
                    singles.append((slot, cur, alt, n))
        combos = [[s] for s in singles]
        if max_swaps >= 2:
            close = sorted(singles, key=lambda s: _rel(s[3]["dpr"], n0["dpr"]))[:12]
            for x, y in itertools.combinations(close, 2):
                if x[0] != y[0] and x[2] != y[2]:
                    combos.append([x, y])
        for c in combos:
            lo2 = dict(lo, **{s[0]: s[2] for s in c})
            if not legal(lo2):
                continue
            n = numbers(score(lo2)) if len(c) > 1 else c[0][3]
            ok, _why = control_check(n0, n, tol)
            if ok:
                out.append({"base": name, "swaps": {s[0]: s[2] for s in c}, "replaced": {s[0]: s[1] for s in c},
                            "a": n0, "b": n, "d_dpr": round(_rel(n["dpr"], n0["dpr"]), 4),
                            "d_taken": round(_rel(n["taken"], n0["taken"]), 4)})
    out.sort(key=lambda c: (c["d_dpr"] > CONTROL_CLOSE, -len(c["swaps"]), c["d_dpr"] + c["d_taken"]))
    return out


# ------------------------------------------------------------------------------------------------ the optimizer's data
def _loadout(W, items):
    return {k: v["sid"] for k, v in (items or {}).items() if v and v.get("sid") and v["sid"] in W.items}


def _items(W, lo):
    return {slot: {"sid": sid, "name": W.items[sid].get("name")} for slot, sid in lo.items()}


def grants_action(stats, sid):
    """The item grants a spell or action (its own Boosts or an equip passive's): its set would run another plan."""
    st = stats.get(sid) or {}
    txt = st.get("Boosts") or ""
    for p in [x.strip() for x in (st.get("PassivesOnEquip") or "").split(";") if x.strip()]:
        txt += ";" + ((stats.get(p) or {}).get("Boosts") or "")
    return re.search(r"UnlockSpell\(", txt) is not None


TWO_HANDED = re.compile(r"Twohanded|TwoHanded", re.I)
IDLE_SLOTS = {"ranged": ("MainHand", "OffHand"), "melee": ("Ranged", "RangedOff"), "throw": ("Ranged", "RangedOff"),
              "caster": ()}


def wearable(stats, lo):
    """No two-handed weapon beside an item in the same weapon set's off-hand."""
    for main, off in (("MainHand", "OffHand"), ("Ranged", "RangedOff")):
        if lo.get(main) and lo.get(off) and TWO_HANDED.search((stats.get(lo[main]) or {}).get("Weapon Properties") or ""):
            return False
        if lo.get(off) and TWO_HANDED.search((stats.get(lo[off]) or {}).get("Weapon Properties") or ""):
            return False
    return True


def build_sets(W, opt, cid, bid, act):
    """The optimizer's sets (owned by the party) and the research sets of one build and act: [(name, loadout)]."""
    out = [(s["name"], _loadout(W, s["items"])) for s in opt.get("sets") or []
           if (s["char"], s["build"], s["act"]) == (cid, bid, act) and s.get("ownership") != "free"]
    out += [(r.get("name"), _loadout(W, r.get("items"))) for r in W.research_sets(cid, bid, act)]
    return out


def control_pair(W, model, opt, ctl=None, tol=CONTROL_EQ, respec=None):
    """The control pair record from CONTROL (or ctl), with the model's numbers for both sets checked again. respec =
    (test plan id, respec) of the test character, the same on both sides: the base set's research plan."""
    ctl = ctl or CONTROL
    cid, bid, act = ctl["char"], ctl["build"], ctl["act"]
    base = next((lo for n, lo in build_sets(W, opt, cid, bid, act) if n == ctl["base"]), None)
    if base is None:
        raise SystemExit(f"control base set {ctl['base']!r} not found for {cid} {bid} act {act}")
    lob = dict(base, **ctl["swaps"])
    pid, r = respec or (None, None)
    na = numbers(model.score(W, cid, bid, act, base, None, respec=r))
    nb = numbers(model.score(W, cid, bid, act, lob, None, respec=r))
    ok, why = control_check(na, nb, tol)
    swapped = ", ".join(f"{W.items[s].get('name')} in {k}" for k, s in ctl["swaps"].items())
    return {"char": cid, "build": bid, "act": act, "control": True, "control_check": {"ok": ok, "why": why},
            "a": {"name": ctl["base"], "id": None, "items": _items(W, base), "respec": pid},
            "b": {"name": f"{ctl['base']} ({swapped})", "id": None, "items": _items(W, lob), "respec": pid},
            "model": {"a_dpr": na["dpr"], "b_dpr": nb["dpr"], "a_taken": na["taken"], "b_taken": nb["taken"],
                      "a_R": na["R"], "b_R": nb["R"], "a": na, "b": nb,
                      "delta": round(nb["dpr"] / na["dpr"] - 1, 4) if na["dpr"] else None}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimizer", required=True)
    ap.add_argument("--optimized", required=True, help="the optimizer's export (sets + compare rows)")
    ap.add_argument("--select", default="", help="char:build:act[:research set number],...")
    ap.add_argument("--test-plans", default=TEST_PLANS, help="the optimizer's test plans (each side's respec)")
    ap.add_argument("--control", action="store_true", help="put the control pair (CONTROL) first")
    ap.add_argument("--find-control", help="char:build:act,...: list control candidates of these builds")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.abspath(a.optimizer))
    import model
    import odata
    import respec as RS
    W = odata.World()
    plans = load_test_plans(a.test_plans)
    with open(a.optimized, encoding="utf-8") as f:
        opt = json.load(f)
    if a.find_control:
        by_slot = {}
        for sid in W.universe:
            for s in odata.item_slots(W.items[sid]):
                by_slot.setdefault(s, []).append(sid)
        for key in a.find_control.split(","):
            cid, bid, act = key.split(":")
            act = int(act)
            mode = model.State(W, cid, bid, act, {}, {}).plan["mode"]
            cands = find_controls(lambda lo: model.score(W, cid, bid, act, lo, None), build_sets(W, opt, cid, bid, act),
                                  lambda s: [x for x in by_slot.get(s, []) if W.obtainable(x, act)],
                                  lambda sid: grants_action(W.stats, sid), idle_slots=IDLE_SLOTS.get(mode, ()),
                                  legal=lambda lo: wearable(W.stats, lo))
            print(f"{cid} {bid} A{act}: {len(cands)} candidates")
            for c in cands[:8]:
                print("  ", c["base"], {k: W.items[v].get("name") for k, v in c["swaps"].items()}, "replacing",
                      {k: W.items[v].get("name") for k, v in c["replaced"].items()}, f"dpr {c['a']['dpr']} vs "
                      f"{c['b']['dpr']}, taken {c['a']['taken']} vs {c['b']['taken']}, R {c['a']['R']} vs {c['b']['R']}")
        return
    out = []
    if a.control:
        rid = next((r.get("id") for r in W.research_sets(CONTROL["char"], CONTROL["build"], CONTROL["act"])
                    if r.get("name") == CONTROL["base"]), None)
        rr = (rid, tuned_respec(W, model, RS.tune, plans, rid)) if rid in plans else None
        p = control_pair(W, model, opt, respec=rr)
        if not p["control_check"]["ok"]:
            print("WARNING: the model no longer rates the control's sets alike:", "; ".join(p["control_check"]["why"]))
        out.append(p)
    for key in [k for k in a.select.split(",") if k]:
        cid, bid, act, *num = key.split(":")
        act = int(act)
        oset = next(s for s in opt["sets"] if (s["char"], s["build"], s["act"]) == (cid, bid, act))
        comp = next(c for c in opt["compare"] if (c["char"], c["build"], c["act"]) == (cid, bid, act))
        ref_id = f"{cid}.{bid}.a{act}.{num[0]}" if num else None
        ref = next((s for s in W.research_sets(cid, bid, act)
                    if (s.get("id") == ref_id if ref_id else s.get("name") == comp["ref_set"])), None)
        if ref is None:
            print("no research set", key, comp["ref_set"])
            continue
        pa = oset.get("id") if oset.get("id") in plans else None
        pb = ref.get("id") if ref.get("id") in plans else None
        sa = model.score(W, cid, bid, act, _loadout(W, oset["items"]), None,
                         respec=pa and tuned_respec(W, model, RS.tune, plans, pa))
        sb = model.score(W, cid, bid, act, _loadout(W, ref.get("items")), None,
                         respec=pb and tuned_respec(W, model, RS.tune, plans, pb))
        na, nb = numbers(sa), numbers(sb)
        out.append({"char": cid, "build": bid, "act": act,
                    "a": {"name": oset["name"], "id": oset["id"], "items": oset["items"], "respec": pa},
                    "b": {"name": ref.get("name"), "id": ref.get("id"), "items": ref.get("items"), "respec": pb},
                    "model": {"a_score": round(sa.score, 2), "b_score": round(sb.score, 2), "a_dpr": na["dpr"],
                              "b_dpr": nb["dpr"], "delta": round(sa.score / sb.score - 1, 4) if sb.score else None,
                              "a_taken": na["taken"], "b_taken": nb["taken"], "a_R": na["R"], "b_R": nb["R"]}})
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
    print(len(out), "pairs ->", a.out)


if __name__ == "__main__":
    main()
