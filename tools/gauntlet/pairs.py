"""Pick gauntlet pairs: the optimizer's set vs the best research set the optimizer compared it with.

    python tools/gauntlet/pairs.py --optimizer DIR --optimized optimized.json \
        --select shadowheart:lightcleric:3,wyll:lockadin:3 --out pairs.json
"""
import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimizer", required=True)
    ap.add_argument("--optimized", required=True, help="the optimizer's export (sets + compare rows)")
    ap.add_argument("--select", required=True, help="char:build:act,...")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.abspath(a.optimizer))
    import odata
    W = odata.World()
    with open(a.optimized, encoding="utf-8") as f:
        opt = json.load(f)
    out = []
    for key in a.select.split(","):
        cid, bid, act = key.split(":")
        act = int(act)
        oset = next(s for s in opt["sets"] if (s["char"], s["build"], s["act"]) == (cid, bid, act))
        comp = next(c for c in opt["compare"] if (c["char"], c["build"], c["act"]) == (cid, bid, act))
        ref = next((s for s in W.research_sets(cid, bid, act) if s.get("name") == comp["ref_set"]), None)
        if ref is None:
            print("no research set", key, comp["ref_set"])
            continue
        out.append({"char": cid, "build": bid, "act": act, "a": {"name": oset["name"], "id": oset["id"],
                                                                 "items": oset["items"]},
                    "b": {"name": ref.get("name"), "id": ref.get("id"), "items": ref.get("items")},
                    "model": {"a_score": comp["opt_score"], "b_score": comp["ref_score"], "a_dpr": comp["opt_dpr"],
                              "b_dpr": comp["ref_dpr"], "delta": comp["delta"]}})
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(len(out), "pairs ->", a.out)


if __name__ == "__main__":
    main()
