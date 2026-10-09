"""Headless renders of built sets (before/after proofs, 3D_ALL.md). Edge headless + a local HTTP server on 127.0.0.1.

  python tools/model3d/render3d.py <out dir with manifest.json> <png prefix> set_id[:view,view] [...]

Writes <out>/preview3d.html (viewer3d.js + import map; also usable by hand) and <png prefix>_<set>_<view>.png
(1000 x 1250). three.js comes from cdn.jsdelivr.net (network needed).
"""
import base64
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "sets_artifact"))
import screens as S  # noqa: E402

THREE = "0.170.0"
IMPORTMAP = json.dumps({"imports": {
    "three": f"https://cdn.jsdelivr.net/npm/three@{THREE}/build/three.module.js",
    "three/addons/": f"https://cdn.jsdelivr.net/npm/three@{THREE}/examples/jsm/"}})


def preview_html():
    return ("<!doctype html><html><head><meta charset='utf-8'><title>3D preview</title><style>html,body{margin:0;"
            "height:100%;background:radial-gradient(ellipse at 50% 38%,#3a2c20 0%,#1d1611 45%,#0b0806 100%)}#st{position:"
            "absolute;inset:0}</style></head><body><div id='st'></div><script>window.LA3D_BASE='./';window.__errs=[];"
            "addEventListener('error',e=>__errs.push(String(e.message)));addEventListener('unhandledrejection',"
            "e=>__errs.push(String(e.reason)));</script><script type='importmap'>" + IMPORTMAP + "</script>"
            "<script type='module' src='viewer3d.js'></script><script type='module'>"
            "const q=new URLSearchParams(location.search);window.LA3D_BARE=!!q.get('bare');document.addEventListener('la3d-ready',()=>{});"
            "const go=()=>window.LootAdvisor3D?window.LootAdvisor3D.mount(document.getElementById('st'),"
            "q.get('set'),q.get('view')||'front').catch(e=>__errs.push(String(e))):setTimeout(go,100);go();"
            "</script></body></html>")


def main(argv):
    out = os.path.abspath(argv[1])
    prefix = os.path.abspath(argv[2])
    jobs = []
    for a in argv[3:]:
        sid, _, views = a.partition(":")
        jobs.append((sid, (views or "front").split(",")))
    bare = os.environ.get("LA3D_BARE") == "1"
    shutil.copy(os.path.join(HERE, "viewer3d.js"), os.path.join(out, "viewer3d.js"))
    with open(os.path.join(out, "preview3d.html"), "w", encoding="utf-8") as f:
        f.write(preview_html())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=out)
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    exe = next((b for b in S.BROWSERS if os.path.exists(b)), None)
    prof = tempfile.mkdtemp(prefix="la_3d_")
    dbg = 9351
    proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=%d" % dbg, "--user-data-dir=" + prof,
                             "--hide-scrollbars", "--no-first-run", "--disable-extensions", "--enable-unsafe-swiftshader",
                             "--ignore-gpu-blocklist", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % dbg, timeout=2))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.3)
        ws = S.WS(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Emulation.setDeviceMetricsOverride", width=1000, height=1250, deviceScaleFactor=1, mobile=False)
        for sid, views in jobs:
            ws.call("Page.navigate", url=f"http://127.0.0.1:{port}/preview3d.html?set={sid}&view={views[0]}" + ("&bare=1" if bare else ""))
            t = time.time()
            ok = False
            while time.time() - t < 120:
                time.sleep(0.5)
                if S.js(ws, "window.LA3D_READY") == sid:
                    ok = True
                    break
            if not ok:
                print("  ! not ready", sid, S.js(ws, "JSON.stringify(window.__errs||[])"))
                continue
            time.sleep(2.5)
            for view in views:
                S.js(ws, f"window.LootAdvisor3D.setView('{view}'); 1")
                time.sleep(1.5)
                r = ws.call("Page.captureScreenshot", format="png")
                p = f"{prefix}_{sid}_{view}.png"
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(base64.b64decode(r["data"]))
                print("  ", p)
            errs = S.js(ws, "JSON.stringify(window.__errs||[])")
            if errs and errs != "[]":
                print("  page errors:", errs)
    finally:
        proc.terminate()
        srv.shutdown()


if __name__ == "__main__":
    main(sys.argv)
