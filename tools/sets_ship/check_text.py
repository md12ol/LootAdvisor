"""Check the ship page's text tokens: resolve them like ship.js does (with the English loca) and compare every string
with the online page's data. Run after build_sets_ship.py:  python tools/sets_ship/check_text.py"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import build_sets_artifact as B  # noqa: E402

def page_data(path):
    s = open(path, encoding="utf-8").read()
    tag = '<script id="la-data" type="application/json">'
    i = s.index(tag) + len(tag)
    return json.loads(s[i:s.index("</script>", i)].replace(r"<\/", "</"))

def game_text(loca, e):
    raw = loca.get(e[0])
    if raw is None:
        return ""
    p = e[1]
    t = re.sub(r"<br\s*/?>", " ", raw, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    t = re.sub(r"\[(\d+)\]", lambda m: p[int(m.group(1)) - 1] if int(m.group(1)) - 1 < len(p) and p[int(m.group(1)) - 1] != "" else m.group(0), t)
    t = t.replace("turn(s)", "turns").replace("target(s)", "targets")
    return re.sub(r"\s+", " ", t).strip()

def resolve(o, T, loca):
    if isinstance(o, str):
        return re.sub(r"\x01([0-9a-f]+)\x02", lambda m: game_text(loca, T[int(m.group(1), 16)]), o)
    if isinstance(o, list):
        return [resolve(x, T, loca) for x in o]
    if isinstance(o, dict):
        return {k: resolve(v, T, loca) for k, v in o.items()}
    return o

def walk_pairs(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b:
                yield from walk_pairs(a[k], b[k], path + "/" + str(k))
    elif isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk_pairs(x, y, path + "/" + str(i))
    elif isinstance(a, str) and isinstance(b, str):
        yield path, a, b

if __name__ == "__main__":
    ship = page_data(os.path.join(B.REPO, "LootAdvisor", "Mods", "LootAdvisor", "Page", "Sets.html"))
    art = page_data(os.path.join(B.OUT_DIR, "_preview.html"))
    loca = json.load(open(os.path.join(B.DATA, "cache", "loca_english.json"), encoding="utf-8"))
    res = resolve({k: v for k, v in ship.items() if k not in ("T", "art", "artPaths", "fonts")}, ship["T"], loca)
    n = same = 0
    diffs = []
    for path, a, b in walk_pairs(res, art):
        if path.startswith("/generated"):
            continue
        n += 1
        if a == b or re.sub(r"\s+", " ", a).strip() == re.sub(r"\s+", " ", b).strip():
            same += 1
        else:
            diffs.append((path, a, b))
    print("strings compared: %d, identical: %d, different: %d" % (n, same, len(diffs)))
    for p, a, b in diffs[:int(sys.argv[1]) if len(sys.argv) > 1 else 15]:
        print(" ", p); print("    ship:", repr(a[:160])); print("    art: ", repr(b[:160]))
