"""Load BG3 stats .txt files (Stats/Generated/Data/*.txt) from the game paks, with `using` inheritance.

Module load order (campaign, not Honour mode): Shared, SharedDev, Gustav, GustavDev, GustavX.
A later module's `new entry` with the same name replaces the earlier entry (Larian's override rule);
an override that says `using "<its own name>"` extends the earlier definition instead;
`using X` copies X's resolved fields first, then the entry's own `data` lines win.

  from stats import load_stats
  st = load_stats()                # {name: {"type":..., "using":..., "module":..., "file":..., "data": {...}}}
  st.resolved("WPN_Longsword")     # dict of all fields after inheritance (+ "_type", "_chain")

CLI:  python stats.py <entry name> [...]     print resolved entries
      python stats.py --dump <out.json>       dump every resolved entry
"""
import json
import os
import re
import sys

from pak import Pak, GAME_DATA

MODULES = ["Shared", "SharedDev", "Gustav", "GustavDev", "GustavX"]
PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak"]
_LINE = re.compile(r'^\s*(new entry|type|using|data)\s+"([^"]*)"(?:\s+"(.*)")?\s*$')


def _parse(text, module, fname, out):
    cur = None
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        kw, a, b = m.groups()
        if kw == "new entry":
            cur = {"type": None, "using": None, "module": module, "file": fname, "data": {}, "prior": out.get(a)}
            out[a] = cur
        elif cur is None:
            continue
        elif kw == "type":
            cur["type"] = a
        elif kw == "using":
            cur["using"] = a
        elif kw == "data":
            cur["data"][a] = b if b is not None else ""


class Stats(dict):
    def resolved(self, name, _seen=None, _entry=None):
        e = _entry or self.get(name)
        if e is None:
            return None
        _seen = _seen or set()
        if id(e) in _seen:
            raise ValueError(f"using-cycle at {name}")
        _seen.add(id(e))
        base = {}
        chain = [name]
        if e["using"]:
            if e["using"] == name:  # override that extends its own earlier definition
                parent = self.resolved(name, _seen, e["prior"]) if e["prior"] else None
            else:
                parent = self.resolved(e["using"], _seen)
            if parent:
                chain += parent.pop("_chain")
                parent.pop("_type", None)
                base.update(parent)
        base.update(e["data"])
        base["_type"] = e["type"]
        base["_chain"] = chain
        return base


def load_stats():
    by_module = {m: [] for m in MODULES}
    for pk in PAKS:
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            n = e.name
            if not (n.startswith("Public/") and "/Stats/Generated/Data/" in n and n.endswith(".txt")):
                continue
            mod = n.split("/")[1]
            if mod in by_module:
                by_module[mod].append((n, p.read(e).decode("utf-8", "replace")))
        p.close()
    st = Stats()
    for mod in MODULES:
        for fname, text in sorted(by_module[mod]):
            _parse(text, mod, fname, st)
    return st


if __name__ == "__main__":
    st = load_stats()
    if len(sys.argv) > 2 and sys.argv[1] == "--dump":
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump({k: st.resolved(k) for k in st}, f, ensure_ascii=False)
        print(f"dumped {len(st)} entries")
    else:
        for n in sys.argv[1:]:
            print(json.dumps(st.resolved(n), indent=1, ensure_ascii=False))
