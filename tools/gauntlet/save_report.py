"""The boss's saving throws in gauntlet fight records: rows with no outcome, and the failure share against the dice.

    python tools/gauntlet/save_report.py RECORD_OR_FOLDER [...] [--json OUT]

A folder stands for its run_*.json records. Records below harness version 14 are skipped with a warning: their save
rows were built differently (outcomes guessed from status timing) and cannot be counted by die.

Rows with no outcome: per record and in total, the save rows whose `success` is empty, by how the row was built
(the cast-start component, the Osiris roll, the roller taken from the component's Source, rows still waiting
for an Osiris roll in saves_unclaimed).

Failure share: one row per save that decides its cast (`deciding` not false; Piercing Shot's second condition left
out), concentration saves and rows with no outcome left out. Each row's chance to fail is strategy.save_fails with
the bonus the engine used (`bonus_used`: the total less the d20), or the modelled bonus when the row has none. Per
ability and per spell and status: rows, failed, expected, sd, z. Last, every row whose `bonus_used` differs from
the modelled bonus for its ability: the enemy's `saves` from the run request, else its `save` plus the template's
proficiency (catalog.TEMPLATE_SAVE_PROF).
"""
import argparse
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "optimizer"))
from catalog import TEMPLATE_SAVE_PROF  # noqa: E402
from strategy import save_fails  # noqa: E402

MIN_VERSION = 14
# the harness's forced save bonus when the run request names no enemy (the spec's enemy `save`)
DEFAULT_SAVE = 4
ABILITY = {"Strength": "STR", "Dexterity": "DEX", "Constitution": "CON", "Intelligence": "INT", "Wisdom": "WIS",
           "Charisma": "CHA"}


def record_files(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "run_*.json")))
        else:
            out.append(p)
    return out


def ability_key(a):
    return ABILITY.get(a, a) if a else "?"


def modelled_bonus(rec, ability):
    """The save bonus the model gives the record's enemy for one ability ("WIS", ...)."""
    E = (rec.get("req") or {}).get("enemy") or {}
    saves = E.get("saves") or {}
    if ability in saves:
        return int(saves[ability])
    return int(E.get("save", DEFAULT_SAVE)) + TEMPLATE_SAVE_PROF.get(ability, 0)


def built_by(row, unclaimed):
    """How a row was built: its sources joined with '+' (component, osiris), then swapped / unclaimed."""
    parts = [k for k in ("component", "osiris") if row.get(k)] or ["neither"]
    key = "+".join(parts)
    if row.get("swapped"):
        key += " swapped"
    if unclaimed:
        key += " unclaimed"
    return key


def rows_of(rec):
    """-> [(round number, row, unclaimed)] over every round's saves and saves_unclaimed."""
    out = []
    for i, R in enumerate(rec.get("rounds") or [], 1):
        for key in ("saves", "saves_unclaimed"):
            for row in R.get(key) or []:
                out.append((i, row, key == "saves_unclaimed"))
    return out


def is_concentration(row):
    return any("concentration" in str(row.get(k) or "").lower() for k in ("roll_type", "save_type"))


def outcome_missing(rec):
    """Rows with no `success`, counted by how they were built: {key: [missing, rows]}."""
    out = {}
    for _, row, unclaimed in rows_of(rec):
        c = out.setdefault(built_by(row, unclaimed), [0, 0])
        c[1] += 1
        c[0] += row.get("success") is None
    return out


def pool_rows(rec, name):
    """The rows the failure share counts, each with its chance to fail, and the counts of rows left out."""
    kept, skipped = [], {"not deciding": 0, "concentration": 0, "no outcome": 0, "unclaimed": 0, "no dc": 0}
    for rnd, row, unclaimed in rows_of(rec):
        if unclaimed:
            skipped["unclaimed"] += 1
        elif row.get("deciding") is False:
            skipped["not deciding"] += 1
        elif is_concentration(row):
            skipped["concentration"] += 1
        elif row.get("success") is None:
            skipped["no outcome"] += 1
        elif not isinstance(row.get("dc"), (int, float)):
            skipped["no dc"] += 1
        else:
            ab = ability_key(row.get("ability"))
            model = modelled_bonus(rec, ab)
            used = row.get("bonus_used")
            bonus = used if isinstance(used, (int, float)) else model
            kept.append({"record": name, "round": rnd, "ability": ab, "spell": row.get("spell") or "?",
                         "status": row.get("save_status") or row.get("status") or "-", "roll": row.get("roll"),
                         "dc": row["dc"], "bonus_used": used, "bonus_model": model,
                         "failed": row["success"] is False, "p": save_fails(bonus, row["dc"]),
                         "condition": row.get("condition")})
    return kept, skipped


def tally(rows):
    n = len(rows)
    failed = sum(r["failed"] for r in rows)
    exp = sum(r["p"] for r in rows)
    sd = math.sqrt(sum(r["p"] * (1 - r["p"]) for r in rows))
    return {"rows": n, "failed": failed, "expected": round(exp, 2), "sd": round(sd, 2),
            "z": round((failed - exp) / sd, 2) if sd > 0 else None}


def grouped(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    return {k: tally(v) for k, v in sorted(groups.items())}


def analyse(paths):
    out = {"skipped_records": [], "records": [], "missing_total": {}, "pool": [], "pool_skipped": {}}
    for path in record_files(paths):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        v = rec.get("version")
        if not isinstance(v, int) or v < MIN_VERSION:
            out["skipped_records"].append({"record": name, "version": v})
            continue
        miss = outcome_missing(rec)
        out["records"].append({"record": name, "version": v, "valid": rec.get("valid"),
                               "difficulty": (rec.get("difficulty") or {}).get("name"),
                               "karmic_dice": (rec.get("difficulty") or {}).get("karmic_dice"), "missing": miss})
        for k, (m, n) in miss.items():
            t = out["missing_total"].setdefault(k, [0, 0])
            t[0] += m
            t[1] += n
        kept, skipped = pool_rows(rec, name)
        out["pool"] += kept
        for k, n in skipped.items():
            out["pool_skipped"][k] = out["pool_skipped"].get(k, 0) + n
    rows = out["pool"]
    out["share"] = {"all": tally(rows), "by_ability": grouped(rows, lambda r: r["ability"]),
                    "by_spell_status": grouped(rows, lambda r: f"{r['spell']} / {r['status']}"),
                    "later_conditions": sum(1 for r in rows if (r["condition"] or 1) > 1),
                    "bonus_from_model": sum(1 for r in rows if not isinstance(r["bonus_used"], (int, float)))}
    out["bonus_differs"] = [r for r in rows if isinstance(r["bonus_used"], (int, float))
                            and r["bonus_used"] != r["bonus_model"]]
    return out


def fmt_tally(t):
    z = "-" if t["z"] is None else f"{t['z']:+.2f}"
    return f"{t['rows']:5} {t['failed']:6} {t['expected']:8.2f} {t['sd']:5.2f} {z:>6}"


def lines(out):
    L = []
    for s in out["skipped_records"]:
        L.append(f"WARNING {s['record']}: harness version {s['version']}, below {MIN_VERSION}: skipped")
    L += ["", "Rows with no outcome (success empty), by how the row was built: missing / rows"]
    for r in out["records"]:
        parts = ", ".join(f"{k} {m}/{n}" for k, (m, n) in sorted(r["missing"].items())) or "no save rows"
        L.append(f"  {r['record']} (v{r['version']}, {r['difficulty'] or '?'}, karmic dice {r['karmic_dice']}, "
                 f"valid {r['valid']}): {parts}")
    tot = out["missing_total"]
    L.append(f"  total: {sum(m for m, _ in tot.values())}/{sum(n for _, n in tot.values())}"
             + "".join(f"; {k} {m}/{n}" for k, (m, n) in sorted(tot.items())))
    sh = out["share"]
    L += ["", "Boss saves that decide their cast, failed against strategy.save_fails(bonus the engine used, dc)",
          "  left out: " + ", ".join(f"{k} {n}" for k, n in sorted(out["pool_skipped"].items())),
          f"  kept rows from a later condition of their cast: {sh['later_conditions']}; "
          f"rows with no bonus_used (modelled bonus taken): {sh['bonus_from_model']}",
          f"  {'':32} {'rows':>5} {'failed':>6} {'expected':>8} {'sd':>5} {'z':>6}",
          f"  {'all':32} {fmt_tally(sh['all'])}"]
    for k, t in sh["by_ability"].items():
        L.append(f"  {k:32} {fmt_tally(t)}")
    L.append("  per spell / status")
    for k, t in sh["by_spell_status"].items():
        L.append(f"  {k[:32]:32} {fmt_tally(t)}")
    L += ["", f"bonus_used differs from the modelled bonus: {len(out['bonus_differs'])} rows"]
    for r in out["bonus_differs"]:
        L.append(f"  {r['record']} r{r['round']} {r['ability']} {r['spell']}: d20 {r['roll']}, "
                 f"used {r['bonus_used']:+}, model {r['bonus_model']:+}, dc {r['dc']}")
    return L


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="fight records (run_*.json) or folders of them")
    ap.add_argument("--json", help="also write the counts and the kept rows to this file")
    a = ap.parse_args()
    out = analyse(a.paths)
    print("\n".join(lines(out)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
