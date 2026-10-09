"""Screenshots of the 3D test page with headless Edge (reuses tools/sets_artifact/screens.py's CDP client).

  python tools/model3d/screens3d.py   -> artifact/screens/3d_*.png

Throw-away browser profile in %TEMP%; WebGL via the GPU or SwiftShader. Needs network for cdn.jsdelivr.net (three.js).
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "sets_artifact"))
import screens as S  # noqa: E402

OUT = os.path.join(ROOT, "artifact", "screens")
PORT = 9341


def save(ws, name):
    r = ws.call("Page.captureScreenshot", format="png")
    p = os.path.join(OUT, name + ".png")
    with open(p, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    print("  ", os.path.relpath(p, ROOT))


def open_page(ws, page, w, h, ready_js, timeout=90):
    ws.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
    ws.call("Page.navigate", url="file:///" + page.replace("\\", "/"))
    t = time.time()
    while time.time() - t < timeout:
        time.sleep(0.5)
        if S.js(ws, ready_js):
            return True
    print("   ! not ready:", page, S.js(ws, "JSON.stringify(window.__errs||[])"))
    return False


def main():
    os.makedirs(OUT, exist_ok=True)
    exe = next((b for b in S.BROWSERS if os.path.exists(b)), None)
    prof = tempfile.mkdtemp(prefix="la_3d_")
    proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=%d" % PORT, "--user-data-dir=" + prof,
                             "--allow-file-access-from-files", "--hide-scrollbars", "--no-first-run",
                             "--disable-extensions", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=2))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.3)
        ws = S.WS(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.addScriptToEvaluateOnNewDocument", source=(
            "window.__errs=[];addEventListener('error',e=>__errs.push(String(e.message)));"
            "addEventListener('unhandledrejection',e=>__errs.push(String(e.reason)));"))
        p3d = os.path.join(ROOT, "artifact", "_3d_preview.html")
        if open_page(ws, p3d, 1440, 900, "!!window.LA3D_READY"):
            info = S.js(ws, "JSON.stringify({gl: (()=>{const c=document.querySelector('canvas');const g=c&&c.getContext('webgl2');"
                            "const d=g&&g.getExtension('WEBGL_debug_renderer_info');return d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):'?'})()})")
            print("   renderer:", info)
            for view, name in (("front", "3d_front"), ("side", "3d_side"), ("threequarter", "3d_threequarter"),
                               ("back", "3d_back"), ("armour", "3d_closeup_armour"), ("head", "3d_closeup_head")):
                S.js(ws, f"document.querySelector('[data-view={view}]').click(); 1")
                time.sleep(2.5)
                save(ws, name)
            ws.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
            time.sleep(1.5)
            S.js(ws, "document.querySelector('[data-view=front]').click(); 1")
            time.sleep(2)
            save(ws, "3d_phone")
        # sets page with the adapter: Astarion, Act 3, the THX set
        ps = os.path.join(ROOT, "artifact", "_sets_3d_preview.html")
        if open_page(ws, ps, 1440, 900, "!!window.LootAdvisorSets && !!document.querySelector('.sethead,.cmp')"):
            S.js(ws, S.CLICK % json.dumps('[data-char="astarion"]'))
            S.js(ws, S.CLICK % json.dumps('[data-act="3"]'))
            time.sleep(1)
            S.js(ws, "(function(){var e=document.querySelector('[data-set-id=\"astarion.thx.a3.1\"],[data-set=\"astarion.thx.a3.1\"]');"
                     "if(e&&!e.matches('figure')) e.click(); return !!e})()")
            t = time.time()
            while time.time() - t < 60 and S.js(ws, "window.LA3D_READY") != "astarion.thx.a3.1":
                time.sleep(0.5)
            S.js(ws, "(function(){var f=document.querySelector('figure.capture[data-capture=model]');"
                     "if(f) f.scrollIntoView({block:'center'}); return 1})()")
            time.sleep(3)
            print("   sets slot model:", S.js(ws, "window.LA3D_READY"),
                  S.js(ws, "document.querySelector('figure.capture[data-capture=model]')?.dataset.set"))
            save(ws, "3d_sets_page_slot")
        errs = S.js(ws, "JSON.stringify(window.__errs||[])")
        if errs and errs != "[]":
            print("  page errors:", errs)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
