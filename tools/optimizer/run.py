"""Loot Advisor gear optimizer (decisions 30 / 41): an "Optimized" set per build per act for each origin's first
two Build Advisor builds, compared with the research / generated sets under the same model.

  python tools/optimizer/run.py                 all origins, builds, acts (+ switch variants), ~10 min
  python tools/optimizer/run.py --only gale     one character (or gale:tempestevoker, gale:tempestevoker:3)
  python tools/optimizer/run.py --write-scores  ALSO write data/scores/optimized.json (separate file; the
                                                <char>.json files and LootData.lua are never touched)
  python tools/optimizer/run.py --merge-into DIR  add the Optimized sets to DIR/<char>.json (a scratch copy of
                                                data/scores; refuses the real data/scores unless --yes-real)

Outputs (gitignored, game-derived): tools/optimizer/.cache/optimized.json (sets, comparisons, switch results)
and tools/optimizer/.cache/report.md (the tables quoted in .claude/LootAdvisor/OPTIMIZER.md).
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import odata  # noqa: E402
import model  # noqa: E402
import search  # noqa: E402

SI = odata.SI
PT = sys.modules.get("playertext") or __import__("playertext")
CACHE = os.path.join(HERE, ".cache")
OWNED_KEEP = 0.03          # an only-if-owned earlier-act item stays only when it is worth > 3% of the score
STRONG = 0.20              # optimizer ahead of the best research set by more than this -> "strong disagreement"


def research_loadouts(W, cid, bid, act):
    out = []
    for s in W.research_sets(cid, bid, act):
        lo = {k: v["sid"] for k, v in (s.get("items") or {}).items() if v and v.get("sid") and v["sid"] in W.items}
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
    own = (W.owners.get(sid) or {}).get("owners") or []
    if own and cid not in own:
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
    if r.choice:
        el = [v.split("_")[-1].title() for v in r.choice.values()]
        t += " Attune Markoheshkir to " + ", ".join(el) + "." if any("CHROMATIC" in v for v in r.choice.values()) \
            else ""
    return PT.scrub(t)


def validate(W, cid, bid, act, lo):
    """The set builder's rules applied to the finished set (independent re-check of every slot)."""
    issues = []
    scorer = W.scorer(cid, bid)
    for slot, sid in lo.items():
        ok, why = search.allowed(W, cid, bid, sid, scorer)
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


def optimize(W, cid, bid, act, switches=None, log=print):
    t0 = time.time()
    S = search.Searcher(W, cid, bid, act, switches)
    rs = research_loadouts(W, cid, bid, act)
    best, r = S.run([lo for _s, lo in rs] + [{}])
    best, owned_alt = owned_pass(W, S, best)
    r = model.score(W, cid, bid, act, best, switches, detail=True)
    comp = []
    for st, lo in rs:
        lo2 = search.drop_illegal(W, lo)
        rr = S.score(lo2)
        comp.append({"id": st.get("id"), "name": st.get("name"), "origin": st.get("origin"), "score": round(rr.score, 2),
                     "dpr": round(rr.dpr, 1), "R": round(rr.R, 2), "ac": rr.dur["ac"],
                     "dropped": sorted(set(lo) - set(lo2))})
    ref = max(comp, key=lambda c: c["score"]) if comp else None
    contrib = contributions(W, S, best)
    return dict(cid=cid, bid=bid, act=act, switches=switches or {}, loadout=best, owned_alt=owned_alt, result=r,
                contrib=contrib, comp=comp, ref=ref, evals=S.evals, secs=time.time() - t0, S=S)


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
    sw = {k: v for k, v in o["switches"].items() if v != model.SWITCHES[k]["default"]}
    sid_ = f"{cid}.{bid}.a{act}.opt" + ("" if not sw else "." + ".".join(sorted(sw)))
    st = {"id": sid_, "name": "Optimized", "origin": "optimizer", "build": bid, "act": act,
          "items": items, "validation": validate(W, cid, bid, act, lo),
          "why": why_text(W, cid, bid, act, r, o["contrib"], lo, ref),
          "fallback": {s: e["fallback"]["sid"] for s, e in items.items() if e.get("fallback")},
          "owned_alt": {s: v for s, v in o["owned_alt"].items()},
          "cond_alt": {}, "warnings": [f"{e['name']}: {e['warning']}" for e in items.values() if e.get("warning")],
          "model": {"score": round(r.score, 2), "dpr": round(r.dpr, 1), "offence": round(r.offence, 1),
                    "control": round(r.control, 1), "R": round(r.R, 2), "ac": r.dur["ac"], "hp": r.dur["hp"],
                    "choice": r.choice, "unknown_predicates": sorted(r.unknown), "events": r.events,
                    "switches": o["switches"]}}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--write-scores", action="store_true")
    ap.add_argument("--merge-into", default="")
    ap.add_argument("--yes-real", action="store_true")
    ap.add_argument("--no-switches", action="store_true")
    a = ap.parse_args()
    if not odata.latest_scores_ready():
        print("note: data/scores/READY_FOR_MOD.txt missing - the pipeline may be mid-run")
    W = odata.World()
    want = [x.split(":") for x in a.only.split(",") if x]
    os.makedirs(CACHE, exist_ok=True)
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "switches": {k: v["text"] for k, v in model.SWITCHES.items()},
           "sets": [], "compare": [], "switch_results": []}
    lines = []
    for cid in odata.CHARS:
        for bid in W.origin_builds(cid):
            for act in (1, 2, 3):
                if want and not any(w[0] == cid and (len(w) < 2 or w[1] == bid) and (len(w) < 3 or int(w[2]) == act)
                                    for w in want):
                    continue
                o = optimize(W, cid, bid, act)
                st = to_set(W, o)
                out["sets"].append({"char": cid, **st})
                ref = o["ref"]
                ref_lo = next((lo for s, lo in research_loadouts(W, cid, bid, act) if ref and s.get("id") == ref["id"]),
                              {})
                in_sets = {v["sid"] for s in W.research_sets(cid, bid, act) for v in (s.get("items") or {}).values()
                           if v and v.get("sid")}
                finds = [W.items[s]["name"] for s in o["loadout"].values() if s not in in_sets]
                delta = (o["result"].score / ref["score"] - 1) if ref and ref["score"] else None
                row = {"char": cid, "build": bid, "act": act, "opt_score": round(o["result"].score, 1),
                       "opt_dpr": round(o["result"].dpr, 1), "opt_R": round(o["result"].R, 1),
                       "opt_ac": o["result"].dur["ac"], "ref_set": ref["name"] if ref else None,
                       "ref_score": ref["score"] if ref else None, "ref_dpr": ref["dpr"] if ref else None,
                       "delta": round(delta, 3) if delta is not None else None, "finds": finds,
                       "diff": diff_slots(W, ref_lo, o["loadout"]), "strong": bool(delta is not None and
                                                                                   delta > STRONG),
                       "validation": st["validation"], "evals": o["evals"], "secs": round(o["secs"], 1)}
                out["compare"].append(row)
                print(f"{cid:11} {bid:20} A{act} opt {row['opt_score']:7.1f} (dpr {row['opt_dpr']:6.1f} R "
                      f"{row['opt_R']:5.1f}) best set {row['ref_score']} {row['ref_set']!s:32.32} "
                      f"{(delta or 0) * 100:+6.1f}%  {o['secs']:.0f}s {'VALIDATION: ' + str(st['validation']) if st['validation'] else ''}")
                if not a.no_switches:
                    for k, v in affected_switches(W, o):
                        sw = {k: not model.SWITCHES[k]["default"]}
                        o2 = optimize(W, cid, bid, act, sw)
                        st2 = to_set(W, o2)
                        changed = diff_slots(W, o["loadout"], o2["loadout"])
                        out["switch_results"].append({"char": cid, "build": bid, "act": act, "switch": k,
                                                      "default": model.SWITCHES[k]["default"],
                                                      "score_default": round(o["result"].score, 1),
                                                      "score_flipped_same_gear": round(v, 1),
                                                      "score_flipped_reoptimized": round(o2["result"].score, 1),
                                                      "gear_changes": changed, "set": st2})
                        print(f"    switch {k}={not model.SWITCHES[k]['default']}: same gear {v:.1f}, re-optimized "
                              f"{o2['result'].score:.1f}, {len(changed)} slot(s) change")
    with open(os.path.join(CACHE, "optimized.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    write_report(out, os.path.join(CACHE, "report.md"))
    if a.write_scores:
        p = os.path.join(odata.SCORES, "optimized.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"generated": out["generated"], "sets": out["sets"]}, f, indent=1, default=str)
        print("wrote", p, "(separate file; <char>.json and LootData.lua untouched)")
    if a.merge_into:
        merge_into(a.merge_into, out["sets"], a.yes_real)
    bad = [s for s in out["sets"] if s["validation"]]
    print(f"\n{len(out['sets'])} optimized sets, {len(bad)} with validation issues; report {CACHE}\\report.md")
    return 1 if bad else 0


def merge_into(d, sets, yes_real):
    d = os.path.abspath(d)
    if os.path.normcase(d) == os.path.normcase(os.path.abspath(odata.SCORES)) and not yes_real:
        raise SystemExit("refusing to merge into the real data/scores without --yes-real (decision: behind a flag)")
    by = {}
    for s in sets:
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
    L = ["| Character | Build | Act | Optimized score | DPR | AC | Best research set | Its score | Delta | New items |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["compare"]:
        L.append(f"| {r['char']} | {r['build']} | {r['act']} | {r['opt_score']} | {r['opt_dpr']} | {r['opt_ac']} | "
                 f"{r['ref_set']} | {r['ref_score']} | {(r['delta'] or 0) * 100:+.0f}% | {', '.join(r['finds'][:4])} |")
    L += ["", "Switches (unverified mechanics):", "",
          "| Character | Build | Act | Switch -> flipped | Default score | Flipped, same gear | Flipped, re-optimized | Gear changes |",
          "|---|---|---|---|---|---|---|---|"]
    for r in out["switch_results"]:
        ch = "; ".join(f"{s}: {a} -> {b}" for s, a, b in r["gear_changes"]) or "none"
        L.append(f"| {r['char']} | {r['build']} | {r['act']} | {r['switch']} -> {not r['default']} | "
                 f"{r['score_default']} | {r['score_flipped_same_gear']} | {r['score_flipped_reoptimized']} | {ch} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
