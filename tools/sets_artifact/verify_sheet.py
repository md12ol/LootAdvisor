"""Check the page's character-sheet maths (app.js computeSheet) against the Python reference (compute_sheet).

    python tools/build_sets_artifact.py          # writes artifact/.cache/sheets_ref.json
    python tools/sets_artifact/verify_sheet.py   # every set at levels 5, 8 and 12 -> 0 differences expected

Headless Edge with a throw-away profile (same driver as screens.py). Exit code 1 on any difference.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screens import WS, BROWSERS, PAGE, ROOT, js  # noqa: E402

PORT = 9341


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s.%s missing on %s" % (path, k, "page" if k not in a else "reference"))
            else:
                out += diff(a[k], b[k], path + "." + str(k))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s: %d vs %d entries (%s | %s)" % (path, len(a), len(b), str(a)[:200], str(b)[:200]))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += diff(x, y, "%s[%d]" % (path, i))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 1e-6:
            out.append("%s: %s vs %s" % (path, a, b))
    elif a != b:
        out.append("%s: %r vs %r" % (path, a, b))
    return out


def main():
    ref = json.load(open(os.path.join(ROOT, "artifact", ".cache", "sheets_ref.json"), encoding="utf-8"))
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    prof = tempfile.mkdtemp(prefix="la_verify_")
    proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=%d" % PORT, "--user-data-dir=" + prof,
                             "--allow-file-access-from-files", "--no-first-run", "--disable-extensions", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bad = 0
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=2))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.3)
        ws = WS(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.navigate", url="file:///" + PAGE.replace("\\", "/"))
        for _ in range(100):
            time.sleep(0.2)
            if js(ws, "!!(window.LootAdvisorSets && window.LootAdvisorSets.sheetFor)"):
                break
        ids = list(ref.keys())
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            got = js(ws, "(function(ids){var o={};ids.forEach(function(id){o[id]={};[5,8,12].forEach(function(l){"
                         "o[id][String(l)]=window.LootAdvisorSets.sheetFor(id,l,true)})});return o})(%s)" % json.dumps(chunk))
            for sid in chunk:
                for lv in ("5", "8", "12"):
                    d = diff((got or {}).get(sid, {}).get(lv), ref[sid][lv])
                    if d:
                        bad += 1
                        if bad <= 15:
                            print("  %s level %s: %d differences, first: %s" % (sid, lv, len(d), "; ".join(d[:3])))
        print("checked %d sets x 3 levels: %d sheets differ" % (len(ids), bad))
    finally:
        proc.terminate()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
