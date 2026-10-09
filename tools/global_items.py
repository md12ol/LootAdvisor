"""Index the *global* item placements (Mods/<module>/Globals/<level>/Items/_merged.lsf).

level_items_index.json (build_cache.py) only covers Mods/*/Levels/*/Items. Global items are objects that exist
independently of a single level load (many unique / story items, e.g. Nere's Night Walkers) - same record format,
plus "scope": "Globals".

  python global_items.py [--out DIR]    writes <DIR>/global_items_index.json (default LootAdvisor/data/cache)
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_cache as bc  # noqa: E402
import lsf  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

GLOBAL_ITEMS = re.compile(r"^Mods/([^/]+)/Globals/([^/]+)/Items/")


def build(out=bc.OUT_DEFAULT, texts=None):
    t = time.time()
    paks = {n: Pak(os.path.join(GAME_DATA, n)) for n in bc.PAKS}
    if texts is None:
        texts = bc.loca.load_english()
    allt, _ = bc.load_all_templates(paks)
    recs = []
    for pk in bc.PAKS:
        p = paks[pk]
        for e in p.entries:
            m = GLOBAL_ITEMS.match(e.name)
            if not m:
                continue
            data = p.read(e)
            if data[:4] != b"LSOF":
                continue
            res = lsf.load(data)
            for reg in res.regions:
                for g in reg.children:
                    rec = {"pak": pk, "module": m.group(1), "level": m.group(2), "scope": "Globals"}
                    rec.update(bc.object_record(g, texts))
                    tr = g.child("Transform")
                    if tr is not None:
                        if tr.get("Position") is not None:
                            rec["position"] = [round(x, 3) for x in tr.get("Position")]
                        if tr.get("RotationQuat") is not None:
                            rec["rotation"] = [round(x, 4) for x in tr.get("RotationQuat")]
                    tpl = allt.get(g.get("TemplateName"))
                    if tpl is not None:
                        tg = tpl[2]
                        info = {"Name": tg.get("Name"), "module": tpl[1]}
                        for k in bc.INHERIT:
                            if bc._has(tg, k):
                                v = tg.get(k)
                                info[k] = bc.tstr(v, texts)["text"] if isinstance(v, dict) else v
                        for k, (v, src) in bc.resolve_inherited(tg, allt).items():
                            info[k] = bc.tstr(v, texts)["text"] if isinstance(v, dict) else v
                        for k in ("TechnicalDescription", "ShortDescription", "Description"):
                            info.pop(k, None)
                        rec["template"] = info
                    else:
                        rec["template"] = None
                    recs.append(rec)
    for p in paks.values():
        p.close()
    bc.write_lines(os.path.join(out, "global_items_index.json"), recs)
    print(f"global_items_index.json: {len(recs)} global item placements ({time.time() - t:.1f}s)")
    return recs


if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else bc.OUT_DEFAULT
    build(out)
