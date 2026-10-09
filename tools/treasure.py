"""BG3 treasure tables (Public/<module>/Stats/Generated/TreasureTable.txt) - parse + expand (read-only).

  from treasure import load_tables, expand
  tt = load_tables()                       # campaign modules Shared, SharedDev, Gustav, GustavDev, GustavX
  for r in expand("DEN_Weaponsmith_Trade", tt): r["kind"], r["id"], r["chance"], ...

  python treasure.py <table> [...]         print the expanded drops of tables
  python treasure.py --honour <table>      same with the Honour-mode tables merged on top

File format (one statement per line):
  new treasuretable "<name>"               starts a table; a later module re-defining it replaces it,
  CanMerge 1                               ... unless either definition says CanMerge 1 (then subtables are appended)
  new subtable "<amount>,<weight>;..."     how many rolls: pick one (amount, weight) pair by weight, roll `amount` times
  new subtable "-N"                        every entry of the subtable drops (N times)
  StartLevel "7" / EndLevel "8"            treasure-level window of the current subtable
  object category "I_<stats>",f,c,u,r,e,l,d,x   entry: an item (stats entry name) with roll frequency f
  object category "T_<table>",f,...        entry: a nested treasure table
  object category "<ObjectCategory>",f,... entry: random item of an ObjectCategory (stats field) - not expanded
  treasure itemtypes "Common",...          header (ignored)
Chance model (approximate): P(entry at least once per roll of its table) = sum_k w_k/W * (1 - (1 - f/F)^a_k);
a nested table picked n times on average is rolled n times: P = 1 - (1 - p)^n (n >= 1) or p * n (n < 1).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pak import Pak, GAME_DATA  # noqa: E402

MODULES = ["Shared", "SharedDev", "Gustav", "GustavDev", "GustavX"]
HONOUR_MODULES = ["Honour", "HonourX"]
PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak"]
_TT = re.compile(r"^Public/([^/]+)/Stats/Generated/TreasureTable\.txt$")
_RE_TABLE = re.compile(r'^\s*new treasuretable\s+"([^"]+)"')
_RE_SUB = re.compile(r'^\s*new subtable\s+"([^"]*)"')
_RE_OBJ = re.compile(r'^\s*object category\s+"([^"]+)"\s*,\s*(-?\d+)')
_RE_LVL = re.compile(r'^\s*(StartLevel|EndLevel)\s+"?(-?\d+)"?')
_RE_MERGE = re.compile(r'^\s*CanMerge\s+(\d+)')


def read_texts(modules):
    """{module: text} of TreasureTable.txt for the given modules."""
    out = {}
    for pk in PAKS:
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            m = _TT.match(e.name)
            if m and m.group(1) in modules:
                out[m.group(1)] = p.read(e).decode("utf-8", "replace")
        p.close()
    return out


def parse(text, module, tables):
    cur = None
    sub = None
    for line in text.splitlines():
        m = _RE_TABLE.match(line)
        if m:
            name = m.group(1)
            cur = {"name": name, "module": module, "can_merge": False, "subtables": []}
            prev = tables.get(name)
            cur["_prev"] = prev
            tables[name] = cur
            sub = None
            continue
        if cur is None:
            continue
        m = _RE_MERGE.match(line)
        if m:
            cur["can_merge"] = m.group(1) != "0"
            continue
        m = _RE_SUB.match(line)
        if m:
            sub = {"spec": m.group(1).strip(), "start": None, "end": None, "entries": []}
            cur["subtables"].append(sub)
            continue
        m = _RE_LVL.match(line)
        if m and sub is not None:
            sub["start" if m.group(1) == "StartLevel" else "end"] = int(m.group(2))
            continue
        m = _RE_OBJ.match(line)
        if m:
            if sub is None:  # entry without subtable header: behaves like "1,1"
                sub = {"spec": "1,1", "start": None, "end": None, "entries": []}
                cur["subtables"].append(sub)
            sub["entries"].append((m.group(1), int(m.group(2))))
    return tables


def _finish(tables):
    """Apply the merge rule for re-defined tables and drop the helper links."""
    for name, t in tables.items():
        prev = t.pop("_prev", None)
        chain = []
        while prev is not None:
            chain.append(prev)
            prev = prev.pop("_prev", None)
        if chain and (t["can_merge"] or any(p["can_merge"] for p in chain)):
            subs = []
            for p in reversed(chain):
                subs += p["subtables"]
            t["subtables"] = subs + t["subtables"]
            t["merged_from"] = [p["module"] for p in reversed(chain)]
        elif chain:
            t["overrides"] = [p["module"] for p in reversed(chain)]
    return tables


def load_tables(honour=False):
    modules = MODULES + (HONOUR_MODULES if honour else [])
    texts = read_texts(modules)
    tables = {}
    for mod in modules:
        if mod in texts:
            parse(texts[mod], mod, tables)
    return _finish(tables)


def subtable_rolls(spec):
    """-> (guaranteed_count or None, [(amount, weight), ...])"""
    spec = spec.replace(" ", "")
    if spec.startswith("-"):
        try:
            return abs(int(spec)), []
        except ValueError:
            return 1, []
    pairs = []
    for part in spec.split(";"):
        if not part:
            continue
        a, _, w = part.partition(",")
        try:
            pairs.append((int(a), float(w) if w else 1.0))
        except ValueError:
            continue
    return None, pairs


def entry_chance(sub, freq):
    """Probability that an entry with frequency `freq` drops at least once from subtable `sub`."""
    guaranteed, pairs = subtable_rolls(sub["spec"])
    if guaranteed is not None:
        return 1.0 if freq > 0 or len(sub["entries"]) == 1 else 0.0
    total_f = sum(max(f, 0) for _, f in sub["entries"])
    if freq <= 0 or total_f <= 0 or not pairs:
        return 0.0
    W = sum(w for _, w in pairs) or 1.0
    p = freq / total_f
    return sum(w / W * (1.0 - (1.0 - p) ** max(a, 0)) for a, w in pairs)


def expected_selections(sub, freq):
    """Expected number of times an entry is picked when its subtable is rolled once."""
    guaranteed, pairs = subtable_rolls(sub["spec"])
    if guaranteed is not None:
        return float(guaranteed) if (freq > 0 or len(sub["entries"]) == 1) else 0.0
    total_f = sum(max(f, 0) for _, f in sub["entries"])
    if freq <= 0 or total_f <= 0 or not pairs:
        return 0.0
    W = sum(w for _, w in pairs) or 1.0
    return sum(w / W * max(a, 0) for a, w in pairs) * freq / total_f


def _scale(c1, times):
    """P(at least once) after `times` (expected) independent expansions of a table."""
    if times >= 1.0:
        return 1.0 - (1.0 - c1) ** times
    return c1 * times


def expand(name, tables, times=1.0, path=None, min_level=None, max_level=None, _depth=0, level=None):
    """Flatten a table into drops: dicts {kind: item|category|missing_table, id, chance, path, min_level, max_level,
    count}. kind item -> id = stats entry name (from "I_<stats>"); category -> ObjectCategory name.
    `times` = expected number of times this table is rolled (nested tables picked k times are rolled k times).
    `level` = treasure (party) level: subtables whose StartLevel / EndLevel window excludes it do not roll at all
    (None = ignore the windows, every subtable counts - the old behaviour).
    The same id can appear several times (different paths); best_per_id() merges them."""
    t = tables.get(name)
    path = (path or []) + [name]
    if t is None:
        return [{"kind": "missing_table", "id": name, "chance": round(min(1.0, times), 4), "path": path}]
    if _depth > 25:
        return []
    out = []
    for sub in t["subtables"]:
        if level is not None and ((sub["start"] is not None and level < sub["start"]) or
                                  (sub["end"] is not None and sub["end"] >= 0 and level > sub["end"])):
            continue
        lo, hi = min_level, max_level
        if sub["start"] is not None:
            lo = sub["start"] if lo is None else max(lo, sub["start"])
        if sub["end"] is not None:
            hi = sub["end"] if hi is None else min(hi, sub["end"])
        guaranteed, _ = subtable_rolls(sub["spec"])
        for cat, freq in sub["entries"]:
            c1 = entry_chance(sub, freq)
            if c1 <= 0:
                continue
            if cat.startswith("T_"):
                out += expand(cat[2:], tables, times * expected_selections(sub, freq), path, lo, hi, _depth + 1,
                              level)
                continue
            c = round(min(1.0, _scale(c1, times)), 4)
            if cat.startswith("I_"):
                out.append({"kind": "item", "id": cat[2:], "chance": c, "path": path,
                            "min_level": lo, "max_level": hi, "count": guaranteed if guaranteed else 1})
            else:
                out.append({"kind": "category", "id": cat, "chance": c, "path": path,
                            "min_level": lo, "max_level": hi})
    return out


def best_per_id(drops):
    """Collapse expand() output to one entry per (kind, id): chance = 1 - prod(1 - c) over the paths."""
    acc = {}
    for d in drops:
        k = (d["kind"], d["id"])
        if k not in acc:
            acc[k] = dict(d, paths=[d["path"]])
            acc[k]["_miss"] = 1.0 - d["chance"]
        else:
            a = acc[k]
            a["_miss"] *= (1.0 - d["chance"])
            a["paths"].append(d["path"])
            if d.get("min_level") is None or (a.get("min_level") is not None and d["min_level"] < a["min_level"]):
                a["min_level"] = d.get("min_level")
    out = []
    for a in acc.values():
        a["chance"] = round(1.0 - a.pop("_miss"), 4)
        a.pop("path", None)
        out.append(a)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    honour = "--honour" in args
    args = [a for a in args if a != "--honour"]
    tt = load_tables(honour)
    print(f"{len(tt)} tables")
    for n in args:
        for d in sorted(best_per_id(expand(n, tt)), key=lambda d: -d["chance"]):
            lv = f" lvl {d.get('min_level')}-{d.get('max_level')}" if d.get("min_level") or d.get("max_level") else ""
            print(f"  {d['kind']:9s} {d['id']:60s} {d['chance']:.3f}{lv}  via {' > '.join(d['paths'][0])}")
