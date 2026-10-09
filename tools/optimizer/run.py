"""Loot Advisor gear optimizer: an "Optimized" set per build per act for each origin's first two Build Advisor
builds, compared with the research / generated sets under the same model, in two party-ownership variants:

  party  a unique item whose party owner is another character is not available (owners.json); the research
         sets are compared with their own party alternatives (party_alt) in those slots
  free   the owner gives the item up: every item available (research sets as they are)

  python tools/optimizer/run.py                 all origins, builds, acts, both variants (+ switch variants)
  python tools/optimizer/run.py --only gale     one character (or gale:tempestevoker, gale:tempestevoker:3)
  python tools/optimizer/run.py --jobs 8        worker processes, one job per (character, build, act); --jobs 1 runs
                                                everything in this process (same results)
  python tools/optimizer/run.py --resume        skip the jobs whose file in .cache/jobs/ is already written
  python tools/optimizer/run.py --merge-jobs    only the merge step: outputs + party assignment from the job files
  python tools/optimizer/run.py --write-scores  ALSO write data/scores/optimized.json (separate file; the
                                                <char>.json files and LootData.lua are never touched)
  python tools/optimizer/run.py --merge-into DIR  add the Optimized sets to DIR/<char>.json (a scratch copy of
                                                data/scores; refuses the real data/scores unless --yes-real)

Outputs (gitignored, game-derived) in tools/optimizer/.cache/: optimized.json (sets, comparisons, switch results),
report.md (the tables), test_plans.json (one machine-readable test plan per set for an in-game measurement, format
in gauntlet.py), jobs/<char>_<build>_a<act>.json (one per job, merged into the others).
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import odata  # noqa: E402
import model  # noqa: E402
import search  # noqa: E402
import gauntlet  # noqa: E402
import respec  # noqa: E402
import party  # noqa: E402

SI = odata.SI
PT = sys.modules.get("playertext") or __import__("playertext")
CACHE = os.path.join(HERE, ".cache")
OWNED_KEEP = 0.03          # an only-if-owned earlier-act item stays only when it is worth > 3% of the score
STRONG = 0.20              # optimizer ahead of the best research set by more than this -> "strong disagreement"


def research_loadouts(W, cid, bid, act, ownership="party"):
    """[(set, loadout)] of the research / generated sets. Under "party" ownership a slot holding an item owned by
    another character takes the set's own party alternative (party_alt), or stays empty."""
    out = []
    for s in W.research_sets(cid, bid, act):
        lo = {}
        for k, v in (s.get("items") or {}).items():
            if not v or not v.get("sid") or v["sid"] not in W.items:
                continue
            sid = v["sid"]
            if ownership == "party" and W.blocked(sid, cid):
                alt = (v.get("party_alt") or {}).get("sid")
                if not alt or alt not in W.items or W.blocked(alt, cid):
                    continue
                sid = alt
            lo[k] = sid
        out.append((s, lo))
    return out


def owned_pass(W, S, best):
    """Sets rule: an earlier-act item (keep it if you have it) stays only if it is clearly better than the best
    item obtainable now; otherwise it moves to owned_alt."""
    owned_alt = {}
    for slot, sid in list(best.items()):
        if W.obtainable(sid, S.act) != "owned":
            continue
        cur = S.score(best).score
        alt, alt_v = None, None
        for c in S.cands[slot]:
            if W.obtainable(c, S.act) != "now":
                continue
            t = dict(best)
            t[slot] = c
            if not search.legal(W, slot, c, {k: v for k, v in best.items() if k != slot}):
                continue
            v = S.score(t).score
            if alt_v is None or v > alt_v:
                alt, alt_v = c, v
        if alt is not None and alt_v >= cur * (1 - OWNED_KEEP):
            owned_alt[slot] = sid
            best = dict(best)
            best[slot] = alt
    # a later swap changes what an earlier one was weighed against: an item that is now clearly better goes back
    for slot, sid in list(owned_alt.items()):
        t = dict(best)
        t[slot] = sid
        if search.legal(W, slot, sid, {k: v for k, v in best.items() if k != slot}) and                 S.score(t).score * (1 - OWNED_KEEP) > S.score(best).score:
            best = t
            del owned_alt[slot]
    return best, owned_alt


def contributions(W, S, lo):
    """Score share of each item: score drop when the slot is emptied."""
    full = S.score(lo)
    out = {}
    for slot in lo:
        t = dict(lo)
        t.pop(slot)
        r = S.score(t)
        out[slot] = (full.score - r.score) / full.score if full.score else 0.0
    return out


def existing_entry(W, sid):
    """How-to / warning fields of an item from any scored set slot (same texts the pages show)."""
    for cid in odata.CHARS:
        for b in W.scores[cid]["builds"].values():
            for sets in (b.get("sets") or {}).values():
                for st in sets:
                    for it in (st.get("items") or {}).values():
                        if it and it.get("sid") == sid:
                            return it
    return None


def slot_entry(W, cid, act, sid, core, owned_alt=None):
    u = W.universe[sid]
    ex = existing_entry(W, sid)
    if ex:
        e = {k: ex.get(k) for k in ("how", "warning", "severity", "warn_types", "best_source")}
    else:
        srcs = u.get("sources") or []
        e = {"how": PT.scrub(SI.describe_source(srcs[0], W.levels)) if srcs else "",
             "warning": "", "severity": None, "warn_types": [],
             "best_source": ({k: srcs[0].get(k) for k in ("kind", "level", "region", "position", "requires")}
                             if srcs else None)}
    e.update({"sid": sid, "name": W.items[sid]["name"], "core": core, "act": u["act"], "cond": list(u["cond"]),
              "owned_only": W.obtainable(sid, act) == "owned", "fallback": None,
              "owned_alt": ({"sid": owned_alt, "name": W.items[owned_alt]["name"]} if owned_alt else None),
              "cond_alt": None})
    own = W.blocked(sid, cid)
    if own:
        e["owner"] = own
    return e


def fallback_for(W, S, lo, slot, cid):
    """Best item for the slot with no condition this character must meet (the sets' fb)."""
    best, bv = None, None
    for c in S.cands[slot]:
        if c == lo.get(slot) or SI.cond_relevant(c, cid) or W.obtainable(c, S.act) != "now":
            continue
        if not search.legal(W, slot, c, {k: v for k, v in lo.items() if k != slot}):
            continue
        t = dict(lo)
        t[slot] = c
        v = S.score(t).score
        if bv is None or v > bv:
            best, bv = c, v
    return best


def why_text(W, cid, bid, act, r, contrib, lo, ref):
    b = W.build_entry(cid, bid)
    lvl = odata.ACT_LEVEL[act]
    top = sorted(((v, s) for s, v in contrib.items() if v > 0.02), reverse=True)[:4]
    parts = ", ".join(f"{W.items[lo[s]]['name']} (-{min(v, 0.99) * 100:.0f}% without it)" for v, s in top)
    t = (f"Picked by the damage and survival model for {b['name']} at level {lvl}: about {r.dpr:.0f} damage a round "
         f"against Act {act} enemies, AC {r.dur['ac']:.0f}, {r.dur['hp']:.0f} HP.")
    if ref:
        t += f" Compared with the best community set it is {(r.score / ref - 1) * 100:+.0f}% under the same model."
    if parts:
        t += f" The pieces that matter most: {parts}."
    if r.choice and any("CHROMATIC" in v for v in r.choice.values()):
        t += " Attune Markoheshkir to " + ", ".join(v.split("_")[-1].title() for v in r.choice.values()) + "."
    return PT.scrub(t)


def validate(W, cid, bid, act, lo, ownership="party"):
    """The set builder's rules applied to the finished set (independent re-check of every slot)."""
    issues = []
    scorer = W.scorer(cid, bid)
    for slot, sid in lo.items():
        ok, why = search.allowed(W, cid, bid, sid, scorer, ownership)
        if not ok:
            issues.append(f"{slot}: {W.items[sid]['name']} not allowed ({why})")
        if not W.obtainable(sid, act):
            issues.append(f"{slot}: {W.items[sid]['name']} not obtainable by Act {act}")
        if not SI.slot_ok(sid, slot, {k: {"sid": v} for k, v in lo.items() if k != slot}, W.items):
            issues.append(f"{slot}: {W.items[sid]['name']} clashes with the rest of the set")
        if not search.ranged_off_ok(W, slot, sid):
            issues.append(f"{slot}: {W.items[sid]['name']} is not a hand crossbow")
        if slot not in W.universe[sid]["slots"]:
            issues.append(f"{slot}: {W.items[sid]['name']} does not fit this slot")
    sids = [s for s in lo.values()]
    for s in set(sids):
        if sids.count(s) > 1 and W.items[s].get("unique"):
            issues.append(f"{W.items[s]['name']} twice (unique)")
    return issues


def optimize(W, cid, bid, act, switches=None, ownership="party", log=print):
    t0 = time.time()
    S = search.Searcher(W, cid, bid, act, switches, ownership=ownership)
    rs = research_loadouts(W, cid, bid, act, ownership)
    best, r = S.run([lo for _s, lo in rs] + [{}])
    best, owned_alt = owned_pass(W, S, best)
    r = model.score(W, cid, bid, act, best, switches, detail=True)
    comp = []
    for st, lo in rs:
        lo2 = search.drop_illegal(W, lo)
        rr = S.score(lo2)
        comp.append({"id": st.get("id"), "name": st.get("name"), "origin": st.get("origin"), "score": round(rr.score, 2),
                     "dpr": round(rr.dpr, 1), "R": round(rr.R, 2), "ac": rr.dur["ac"], "lost": round(rr.lost, 3),
                     "dropped": sorted(set(lo) - set(lo2)), "loadout": lo2})
    ref = max(comp, key=lambda c: c["score"]) if comp else None
    contrib = contributions(W, S, best)
    return dict(cid=cid, bid=bid, act=act, switches=switches or {}, ownership=ownership, loadout=best,
                owned_alt=owned_alt, result=r, contrib=contrib, comp=comp, ref=ref, evals=S.evals,
                secs=time.time() - t0, S=S)


def set_id(cid, bid, act, switches, ownership):
    sw = {k: v for k, v in (switches or {}).items() if v != model.SWITCHES[k]["default"]}
    return (f"{cid}.{bid}.a{act}.opt" + ("" if ownership == "party" else ".free") +
            ("" if not sw else "." + ".".join(sorted(sw))))


def to_set(W, o):
    cid, bid, act, lo, r = o["cid"], o["bid"], o["act"], o["loadout"], o["result"]
    S = o["S"]
    items = {}
    for slot in odata.SLOTS:
        sid = lo.get(slot)
        if not sid:
            continue
        e = slot_entry(W, cid, act, sid, o["contrib"].get(slot, 0) >= 0.05, o["owned_alt"].get(slot))
        if SI.cond_relevant(sid, cid):
            fb = fallback_for(W, S, lo, slot, cid)
            if fb:
                e["fallback"] = {"sid": fb, "name": W.items[fb]["name"], "act": W.universe[fb]["act"]}
        items[slot] = e
    ref = o["ref"]["score"] if o["ref"] else None
    st = {"id": set_id(cid, bid, act, o["switches"], o["ownership"]), "name": "Optimized", "origin": "optimizer",
          "build": bid, "act": act, "ownership": o["ownership"],
          "items": items, "validation": validate(W, cid, bid, act, lo, o["ownership"]),
          "why": why_text(W, cid, bid, act, r, o["contrib"], lo, ref),
          "fallback": {s: e["fallback"]["sid"] for s, e in items.items() if e.get("fallback")},
          "owned_alt": {s: v for s, v in o["owned_alt"].items()},
          "cond_alt": {}, "warnings": [f"{e['name']}: {e['warning']}" for e in items.values() if e.get("warning")],
          "model": {"score": round(r.score, 2), "dpr": round(r.dpr, 1), "offence": round(r.offence, 1),
                    "control": round(r.control, 1), "R": round(r.R, 2), "ac": r.dur["ac"], "hp": r.dur["hp"],
                    "turns_lost": round(r.lost, 3), "threats": r.dur["threats"], "stealth_open": round(r.st.p_open, 3),
                    "concentrating": round(r.st.concentrating, 3), "choice": r.choice,
                    "unknown_predicates": sorted(r.unknown), "events": r.events, "switches": o["switches"],
                    "ownership": o["ownership"]}}
    return st


def affected_switches(W, o):
    """Switches that change this build's score with the optimized loadout (others cannot matter for it)."""
    out = []
    base = o["result"].score
    for k, spec in model.SWITCHES.items():
        sw = dict(o["switches"], **{k: not spec["default"]})
        v = model.score(W, o["cid"], o["bid"], o["act"], o["loadout"], sw).score
        if abs(v - base) > 1e-6 * max(1.0, base):
            out.append((k, v))
    return out


def diff_slots(W, a, b):
    out = []
    for s in odata.SLOTS:
        if a.get(s) != b.get(s):
            out.append((s, W.items[a[s]]["name"] if a.get(s) else "-", W.items[b[s]]["name"] if b.get(s) else "-"))
    return out


def compare_row(W, o, st):
    cid, bid, act = o["cid"], o["bid"], o["act"]
    ref = o["ref"]
    in_sets = {v["sid"] for s in W.research_sets(cid, bid, act) for v in (s.get("items") or {}).values()
               if v and v.get("sid")}
    delta = (o["result"].score / ref["score"] - 1) if ref and ref["score"] else None
    return {"char": cid, "build": bid, "act": act, "ownership": o["ownership"],
            "opt_score": round(o["result"].score, 1), "opt_dpr": round(o["result"].dpr, 1),
            "opt_R": round(o["result"].R, 1), "opt_ac": o["result"].dur["ac"], "opt_lost": round(o["result"].lost, 3),
            "ref_set": ref["name"] if ref else None, "ref_score": ref["score"] if ref else None,
            "ref_dpr": ref["dpr"] if ref else None, "ref_lost": ref["lost"] if ref else None,
            "delta": round(delta, 3) if delta is not None else None,
            "finds": [W.items[s]["name"] for s in o["loadout"].values() if s not in in_sets],
            "diff": diff_slots(W, ref["loadout"] if ref else {}, o["loadout"]),
            "strong": bool(delta is not None and delta > STRONG), "validation": st["validation"],
            "owned_by_others": [(s, W.items[sid]["name"], W.blocked(sid, cid)) for s, sid in o["loadout"].items()
                                if W.blocked(sid, cid)],
            "evals": o["evals"], "secs": round(o["secs"], 1)}


def picks_summary(BI, level, cantrip):
    """Short text of a build's abilities (level 12 plan), feat / ASI picks up to the level, styles, cantrip."""
    ab = " ".join(f"{k} {v}" for k, v in BI["base"].items())
    feats = ", ".join(f"{f['n']} (L{f['lv']})" for f in BI["feats"] if f.get("lv") and f["lv"] <= level)
    t = f"{ab}; {feats or 'no feats yet'}"
    if BI["styles"]:
        t += "; " + ", ".join(BI["styles"])
    if cantrip:
        t += "; " + cantrip
    return t


def tuned_plan(W, cid, bid, act, loadout, set_id, source, ownership=None):
    """Tune the respec to this set's gear, then the test plan with the tuned build. -> (plan, tuning row)"""
    tu = respec.tune(W, cid, bid, act, loadout)
    r = model.score(W, cid, bid, act, loadout, detail=True, respec=tu["respec"])
    plan = gauntlet.test_plan(W, r, set_id, loadout, source, ownership, tu)
    lvl = odata.ACT_LEVEL[act]
    BI0 = W.build_input(cid, bid)
    planned = picks_summary(BI0, lvl, model.PLANS.get(bid, {}).get("cantrip"))
    tuned = picks_summary(dict(BI0, **{k: tu["respec"][k] for k in ("base", "feats", "styles")}), lvl,
                          tu["respec"]["cantrip"]) if tu["respec"] else "= planned"
    row = {"id": set_id, "source": source, "char": cid, "build": bid, "act": act, "planned": planned,
           "tuned": tuned, "untuned_score": round(tu["untuned"], 2), "tuned_score": round(tu["tuned"], 2),
           "gain": round(tu["tuned"] / tu["untuned"] - 1, 4) if tu["untuned"] else 0.0, "evals": tu["evals"],
           "note": tu["note"]}
    return plan, row


def party_conflicts(W, sets):
    """Unique items with no party owner in owners.json that several characters' party sets use in the same act
    (one copy exists: the party has to choose)."""
    by = {}
    for s in sets:
        if s.get("ownership") != "party" or "." in s["id"].split(".opt")[-1]:
            continue
        for slot, e in s["items"].items():
            sid = e["sid"]
            if W.items[sid].get("unique") and not W.blocked(sid, s["char"]):
                by.setdefault((s["act"], sid), set()).add(s["char"])
    return [{"act": a, "sid": sid, "name": W.items[sid]["name"], "chars": sorted(c)} for (a, sid), c in sorted(by.items())
            if len(c) > 1]


def party_assignment(W, objs):
    """Per ownership variant and act: who keeps each unique item several characters' sets use (party.py), in this
    process. objs = {(ownership, act, cid, bid): {"loadout", "act", "switches", "ownership"}} (optimize() results
    will do). The repaired loadouts stay in optimized.json only (model output, like the sets themselves)."""
    out = []
    for own in search.OWNERSHIP:
        for act in (1, 2, 3):
            sub = {(c, b): o for (ow, ac, c, b), o in objs.items() if ow == own and ac == act}
            if len({c for c, _b in sub}) >= 2:
                out.append(_party_one(W, own, act, sub))
                show_party(out[-1])
    return out


def show_party(res):
    lost = [b for b in res["builds"] if b["lost"]]
    print(f"party {res['ownership']:5} A{res['act']}: {len(res['claims'])} contested items, {len(lost)} sets give "
          f"something up, party value {res['total_before']} -> {res['total']} ({res['methods']}, {res['rounds']} "
          f"round(s), {res['valuations']} repairs, {res['evals']} model evaluations, {res['secs']:.0f}s, peak "
          f"{res['peak_mb']} MB)", flush=True)


def _party_one(W, own, act, sub):
    t0 = time.time()
    model.reset_caches()                 # the result must not depend on what this process evaluated before
    res = party.resolve(W, sub, owned_pass)
    for b in res["builds"]:
        b["validation"] = validate(W, b["char"], b["build"], act, b["loadout"], own)
        b["changed"] = [(s, W.items[x]["name"] if x else "-", W.items[y]["name"] if y else "-")
                        for s, x, y in b["changed"]]
    res.update(ownership=own, act=act, secs=round(time.time() - t0, 1), peak_mb=peak_mb(), pid=os.getpid(),
               names={s: W.items[s]["name"] for s in res["claims"]})
    return res


# ============================================================================================ jobs
# One job = one (character, build, act) with all its variants (ownership, switches, tuning, test plans). Each job
# writes its own file, so a crash loses only that job and --resume skips the finished ones; the merge step then
# assembles optimized.json / report.md / test_plans.json and runs the party assignment once over all jobs.
JOBS = os.path.join(CACHE, "jobs")
_WORKER = {}


def job_path(cid, bid, act):
    return os.path.join(JOBS, f"{cid}_{bid}_a{act}.json")


def job_list(W, only=""):
    want = [x.split(":") for x in only.split(",") if x]
    out = []
    for cid in odata.CHARS:
        for bid in W.origin_builds(cid):
            for act in (1, 2, 3):
                if want and not any(w[0] == cid and (len(w) < 2 or w[1] == bid) and (len(w) < 3 or int(w[2]) == act)
                                    for w in want):
                    continue
                out.append((cid, bid, act))
    return out


def run_job(W, cid, bid, act, params):
    """Every variant of one (character, build, act). -> dict with the rows of each output table, the party
    inputs and the log lines."""
    t0 = time.time()
    model.reset_caches()                 # the result must not depend on what this process evaluated before
    out = {"char": cid, "build": bid, "act": act, "params": params, "sets": [], "compare": [], "switch_results": [],
           "plans": [], "tuning": [], "party_input": [], "log": []}
    tuning = not params["no_tuning"]
    for own in params["variants"]:
        o = optimize(W, cid, bid, act, ownership=own)
        out["party_input"].append({"ownership": own, "act": act, "switches": o["switches"], "loadout": o["loadout"]})
        st = to_set(W, o)
        out["sets"].append({"char": cid, **st})
        if own == "party" and tuning:
            plan, trow = tuned_plan(W, cid, bid, act, o["loadout"], st["id"], "optimizer", own)
            out["plans"].append(plan)
            out["tuning"].append(trow)
            st["model"]["respec_gain"] = trow["gain"]
        row = compare_row(W, o, st)
        out["compare"].append(row)
        out["log"].append(f"{cid:11} {bid:20} A{act} {own:5} opt {row['opt_score']:7.1f} (dpr {row['opt_dpr']:6.1f} "
                          f"lost {row['opt_lost']:.2f}) best set {row['ref_score']} {row['ref_set']!s:28.28} "
                          f"{(row['delta'] or 0) * 100:+6.1f}%  {o['secs']:.0f}s "
                          f"{'VALIDATION: ' + str(st['validation']) if st['validation'] else ''}")
        if own == "party" and tuning:
            # the research sets as published (the in-game test equips them as they are)
            for rs, lo in research_loadouts(W, cid, bid, act, "free"):
                lo2 = search.drop_illegal(W, lo)
                plan, trow = tuned_plan(W, cid, bid, act, lo2, rs.get("id") or rs.get("name"), "research")
                out["plans"].append(plan)
                out["tuning"].append(trow)
        if params["no_switches"] or own != "party":
            continue
        for k, v in affected_switches(W, o):
            sw = {k: not model.SWITCHES[k]["default"]}
            o2 = optimize(W, cid, bid, act, sw, ownership=own)
            st2 = to_set(W, o2)
            changed = diff_slots(W, o["loadout"], o2["loadout"])
            out["switch_results"].append({"char": cid, "build": bid, "act": act, "switch": k,
                                          "default": model.SWITCHES[k]["default"],
                                          "score_default": round(o["result"].score, 1),
                                          "score_flipped_same_gear": round(v, 1),
                                          "score_flipped_reoptimized": round(o2["result"].score, 1),
                                          "gear_changes": changed, "set": st2})
            out["log"].append(f"    switch {k}={not model.SWITCHES[k]['default']}: same gear {v:.1f}, re-optimized "
                              f"{o2['result'].score:.1f}, {len(changed)} slot(s) change")
    out["secs"] = round(time.time() - t0, 1)
    out["peak_mb"] = peak_mb()
    return out


def write_job(res):
    """Written through a temporary file, so a half-written file never counts as a finished job."""
    p = job_path(res["char"], res["build"], res["act"])
    os.makedirs(JOBS, exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    os.replace(p + ".tmp", p)


def read_job(cid, bid, act):
    try:
        with open(job_path(cid, bid, act), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def peak_mb():
    """Peak memory of this process in MB (peak working set on Windows, max RSS elsewhere)."""
    if sys.platform != "win32":
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                           "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                           "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    c = Counters()
    c.cb = ctypes.sizeof(Counters)
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    get = ctypes.windll.psapi.GetProcessMemoryInfo
    get.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.PeakWorkingSetSize / 2 ** 20)


def set_cache(d):
    global CACHE, JOBS
    CACHE, JOBS = d, os.path.join(d, "jobs")


def _init_worker(cache):
    """Worker initializer: the world data is loaded once per process, never pickled per task."""
    set_cache(cache)
    _WORKER["W"] = odata.World(quiet=True)


def _job_task(args):
    cid, bid, act, params = args
    res = run_job(_WORKER["W"], cid, bid, act, params)
    write_job(res)
    return cid, bid, act, res["secs"], res["peak_mb"], os.getpid(), res["log"]


def _party_task(args):
    return _party_one(_WORKER["W"], *args)


def pool(n):
    import concurrent.futures
    return concurrent.futures.ProcessPoolExecutor(max_workers=n, initializer=_init_worker, initargs=(CACHE,))


def run_all(W, jobs, params, n, resume=False, party_step=True, run_jobs=True):
    """Run the jobs and the party solves in one pool of n worker processes (n <= 1: in this process), then merge.
    Act 3 jobs go first, and each act's two party solves (one per ownership variant) start as soon as that act's
    jobs are written, so the longest solves overlap the remaining jobs. Finished job files are kept with --resume;
    run_jobs=False (--merge-jobs) only solves and merges what is on disk."""
    todo = []
    for cid, bid, act in (jobs if run_jobs else []):
        old = read_job(cid, bid, act) if resume else None
        if old is not None and old.get("params") == params:
            print(f"{cid}:{bid}:{act} done before, skipped (--resume)", flush=True)
            continue
        todo.append((cid, bid, act, params))
    todo.sort(key=lambda t: -t[2])
    left = {act: sum(1 for t in todo if t[2] == act) for act in {j[2] for j in jobs}}
    check = params if run_jobs else None
    t0 = time.time()
    peaks, solved = {}, {}

    def job_done(cid, bid, act, secs, peak, pid, log):
        peaks[pid] = max(peaks.get(pid, 0), peak)
        print("\n".join(log) + f"\n    [{cid}:{bid}:{act} {secs:.0f}s, process {pid} peak {peak} MB]", flush=True)
        left[act] -= 1
        return party_tasks(W, jobs, act, check) if party_step and left[act] == 0 else []

    def solve_done(res):
        solved[(res["ownership"], res["act"])] = res
        pid = res.pop("pid")
        peaks[pid] = max(peaks.get(pid, 0), res["peak_mb"])
        show_party(res)

    ready = [t for act in sorted(left, reverse=True) if left[act] == 0 and party_step
             for t in party_tasks(W, jobs, act, check)]
    if n <= 1:
        for t in ready:
            solve_done(_party_one(W, *t))
        for cid, bid, act, _p in todo:
            res = run_job(W, cid, bid, act, params)
            write_job(res)
            for t in job_done(cid, bid, act, res["secs"], res["peak_mb"], os.getpid(), res["log"]):
                solve_done(_party_one(W, *t))
    elif todo or ready:
        import concurrent.futures as cf
        with pool(n) as ex:
            pending = {ex.submit(_party_task, t): "party" for t in ready}
            pending.update({ex.submit(_job_task, t): "job" for t in todo})
            while pending:
                done, _rest = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                for f in done:
                    kind = pending.pop(f)
                    if kind == "party":
                        solve_done(f.result())
                    else:
                        pending.update({ex.submit(_party_task, t): "party" for t in job_done(*f.result())})
    print(f"{len(todo)} job(s) and {len(solved)} party solve(s) in {time.time() - t0:.0f}s with {max(1, n)} "
          f"process(es); peak memory per process (MB): {sorted(peaks.values(), reverse=True)}", flush=True)
    out = merge_jobs(W, jobs, check)
    out["party"] = [solved[(own, act)] for own in search.OWNERSHIP for act in (1, 2, 3) if (own, act) in solved]
    return out


def party_tasks(W, jobs, act, params=None):
    """The party solves of one act, from its job files: [(ownership, act, {(cid, bid): party input})] for each
    variant with at least two characters."""
    sub = {}
    for cid, bid, a in jobs:
        if a != act:
            continue
        res = read_job(cid, bid, a)
        if res is None or (params is not None and res.get("params") != params):
            raise SystemExit(f"job file missing or written with other options (run it first): {cid}:{bid}:{a}")
        for pi in res["party_input"]:
            sub.setdefault(pi["ownership"], {})[(cid, bid)] = pi
    return [(own, act, sub[own]) for own in search.OWNERSHIP
            if own in sub and len({c for c, _b in sub[own]}) >= 2]


def merge_jobs(W, jobs, params=None):
    """Assemble the outputs from the job files, in job order."""
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "switches": {k: v["text"] for k, v in model.SWITCHES.items()},
           "sets": [], "compare": [], "switch_results": [], "plans": [], "tuning": [], "party": []}
    missing = []
    for cid, bid, act in jobs:
        res = read_job(cid, bid, act)
        if res is None or (params is not None and res.get("params") != params):
            missing.append(f"{cid}:{bid}:{act}")
            continue
        for k in ("sets", "compare", "switch_results", "plans", "tuning"):
            out[k] += res[k]
    if missing:
        raise SystemExit("job files missing or written with other options (run them first): " + ", ".join(missing))
    out["party_conflicts"] = party_conflicts(W, out["sets"])
    return out


def write_outputs(out, a):
    with open(os.path.join(CACHE, "optimized.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in out.items() if k != "plans"}, f, indent=1, default=str)
    with open(os.path.join(CACHE, "test_plans.json"), "w", encoding="utf-8") as f:
        json.dump(gauntlet.envelope(out["plans"], out["generated"]), f, indent=1, default=str)
    write_report(out, os.path.join(CACHE, "report.md"))
    if a.write_scores:
        p = os.path.join(odata.SCORES, "optimized.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"generated": out["generated"], "sets": out["sets"]}, f, indent=1, default=str)
        print("wrote", p, "(separate file; <char>.json and LootData.lua untouched)")
    if a.merge_into:
        merge_into(a.merge_into, out["sets"], a.yes_real)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--write-scores", action="store_true")
    ap.add_argument("--merge-into", default="")
    ap.add_argument("--yes-real", action="store_true")
    ap.add_argument("--no-switches", action="store_true")
    ap.add_argument("--ownership", default="party,free", help="variants to run: party, free or both")
    ap.add_argument("--no-tuning", action="store_true", help="skip the respec tuning and the test plans")
    ap.add_argument("--no-party", action="store_true", help="skip the party assignment of contested unique items")
    ap.add_argument("--plans-only", action="store_true",
                    help="re-tune and re-export the test plans for the sets in .cache/optimized.json")
    ap.add_argument("--jobs", type=int, default=8, help="worker processes (1 = everything in this process)")
    ap.add_argument("--resume", action="store_true", help="skip jobs whose file in .cache/jobs/ is already written")
    ap.add_argument("--merge-jobs", action="store_true",
                    help="only the merge step: outputs and party assignment from the job files in .cache/jobs/")
    ap.add_argument("--cache", default=CACHE, help="output directory (default tools/optimizer/.cache)")
    a = ap.parse_args(argv)
    set_cache(os.path.abspath(a.cache))
    if a.plans_only:
        return plans_only()
    if not odata.latest_scores_ready():
        print("note: data/scores/READY_FOR_MOD.txt missing - the pipeline may be mid-run")
    t0 = time.time()
    W = odata.World()
    os.makedirs(CACHE, exist_ok=True)
    jobs = job_list(W, a.only)
    params = {"variants": [v for v in a.ownership.split(",") if v in search.OWNERSHIP],
              "no_tuning": a.no_tuning, "no_switches": a.no_switches}
    out = run_all(W, jobs, params, a.jobs, a.resume, not a.no_party, not a.merge_jobs)
    write_outputs(out, a)
    bad = [s for s in out["sets"] if s["validation"]]
    print(f"\n{len(out['sets'])} optimized sets, {len(bad)} with validation issues; report {CACHE}/report.md "
          f"({time.time() - t0:.0f}s)")
    return 1 if bad else 0


def plans_only():
    """Respec tuning + test plans for the party optimizer sets and the research sets of an earlier run."""
    W = odata.World()
    with open(os.path.join(CACHE, "optimized.json"), encoding="utf-8") as f:
        out = json.load(f)
    out["plans"], out["tuning"] = [], []
    for st in out["sets"]:
        if st.get("ownership") != "party" or not st["id"].endswith(".opt"):
            continue
        cid, bid, act = st["char"], st["build"], st["act"]
        lo = {k: v["sid"] for k, v in st["items"].items()}
        plan, trow = tuned_plan(W, cid, bid, act, lo, st["id"], "optimizer", "party")
        out["plans"].append(plan)
        out["tuning"].append(trow)
        st["model"]["respec_gain"] = trow["gain"]
        for rs, rlo in research_loadouts(W, cid, bid, act, "free"):
            plan, trow = tuned_plan(W, cid, bid, act, search.drop_illegal(W, rlo), rs.get("id") or rs.get("name"),
                                    "research")
            out["plans"].append(plan)
            out["tuning"].append(trow)
        print(st["id"], "tuned", flush=True)
    with open(os.path.join(CACHE, "optimized.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in out.items() if k != "plans"}, f, indent=1, default=str)
    with open(os.path.join(CACHE, "test_plans.json"), "w", encoding="utf-8") as f:
        json.dump(gauntlet.envelope(out["plans"], out["generated"]), f, indent=1, default=str)
    write_report(out, os.path.join(CACHE, "report.md"))
    return 0


def merge_into(d, sets, yes_real):
    d = os.path.abspath(d)
    if os.path.normcase(d) == os.path.normcase(os.path.abspath(odata.SCORES)) and not yes_real:
        raise SystemExit("refusing to merge into the real data/scores without --yes-real")
    by = {}
    for s in sets:
        if s.get("ownership") == "party":
            by.setdefault(s["char"], []).append(s)
    for cid, lst in by.items():
        p = os.path.join(d, cid + ".json")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for s in lst:
            b = data["builds"][s["build"]]
            acts = b.setdefault("sets", {}).setdefault(str(s["act"]), [])
            acts[:] = [x for x in acts if x.get("origin") != "optimizer"] + [{k: v for k, v in s.items()
                                                                              if k not in ("char", "model")}]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    print("merged optimized sets into", d)


def write_report(out, path):
    L = []
    for own, title in (("party", "Party ownership respected (own nothing extra)"),
                       ("free", "Owner gives it up (every item available)")):
        rows = [r for r in out["compare"] if r["ownership"] == own]
        if not rows:
            continue
        ds = sorted(r["delta"] for r in rows if r["delta"] is not None)
        med = ds[len(ds) // 2] if ds else 0
        L += [f"## {title}", "", f"median {med * 100:+.0f}%, {sum(1 for d in ds if d > STRONG)} of {len(ds)} above "
              f"+{STRONG * 100:.0f}%", "",
              "| Character | Build | Act | Optimized score | DPR | AC | Turns lost | Best research set | Its score | "
              "Delta | New items | Owned by others |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['char']} | {r['build']} | {r['act']} | {r['opt_score']} | {r['opt_dpr']} | {r['opt_ac']} | "
                     f"{r['opt_lost']:.2f} | {r['ref_set']} | {r['ref_score']} | {(r['delta'] or 0) * 100:+.0f}% | "
                     f"{', '.join(r['finds'][:4])} | {', '.join(f'{n} ({o[0]})' for _s, n, o in r['owned_by_others'])} |")
        L.append("")
    if out.get("tuning"):
        gains = sorted(t["gain"] for t in out["tuning"])
        L += ["## Respec tuned to each set (gauntlet sets: optimizer party sets + research sets)", "",
              f"{len(gains)} sets, gain from tuning alone: median {gains[len(gains) // 2] * 100:+.1f}%, max "
              f"{gains[-1] * 100:+.1f}%, {sum(1 for g in gains if g > 1e-9)} sets changed", "",
              "| Set | Source | Planned (abilities L12; feats to this level; styles; cantrip) | Tuned | Untuned score | "
              "Tuned score | Gain |", "|---|---|---|---|---|---|---|"]
        for t in out["tuning"]:
            L.append(f"| {t['id']} | {t['source']} | {t['planned']} | {t['tuned']} | {t['untuned_score']} | "
                     f"{t['tuned_score']} | {t['gain'] * 100:+.1f}% |")
        L.append("")
    L += ["## Unique items without a party owner that several party sets use", "",
          "| Act | Item | Characters |", "|---|---|---|"]
    for c in out.get("party_conflicts") or []:
        L.append(f"| {c['act']} | {c['name']} | {', '.join(c['chars'])} |")
    L += ["", "## Switches (unverified mechanics, party variant)", "",
          "| Character | Build | Act | Switch -> flipped | Default score | Flipped, same gear | Flipped, re-optimized | "
          "Gear changes |", "|---|---|---|---|---|---|---|---|"]
    for r in out["switch_results"]:
        ch = "; ".join(f"{s}: {a} -> {b}" for s, a, b in r["gear_changes"]) or "none"
        L.append(f"| {r['char']} | {r['build']} | {r['act']} | {r['switch']} -> {not r['default']} | "
                 f"{r['score_default']} | {r['score_flipped_same_gear']} | {r['score_flipped_reoptimized']} | {ch} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
