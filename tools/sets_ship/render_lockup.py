"""Renders the shipped Sets page's header lockup (branding option 1 "Gilded Panel": plate + gem, eyebrow, title,
tagline) as a transparent WebP from the branding sources - OUR OWN art, no game art. The page draws the panel, frame
and the inventory-icon strip itself (CSS + the player's own game icons, decoded at runtime).

    python tools/sets_ship/render_lockup.py            -> tools/sets_ship/brand_lockup.webp (720x240 CSS px drawn at 2x)
    python tools/sets_ship/render_lockup.py private    -> brand_lockup_private.webp for the online copy (it does
                                                          not follow the game: tagline "Full loadouts for every origin...")

Needs BuildAdvisor/branding/src (sibling repo) and Edge/Chrome; fonts come from Google Fonts at render time, like
branding/src/render.py. The branding sources are copied to a temp folder and patched there (nothing in src changes).
"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sets_artifact"))
from screens import WS, js  # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "BuildAdvisor", "branding", "src")
PRIVATE = sys.argv[1:2] == ["private"]
OUT = os.path.join(HERE, "brand_lockup_private.webp" if PRIVATE else "brand_lockup.webp")
# the shipped page syncs with the game; the private online copy does not (branding option1_sets_private.png)
TAG = "Full loadouts for every origin, act by act" if PRIVATE else "Full loadouts for your build · follows your game live"
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
W, H, SCALE, PORT = 720, 240, 2, 9347

# the "sets" layout of option1.html without the frame, the background and the (game art) screenshot
LOCK_T = """
  setslock() {
    document.body.classList.add("transparent"); S.style.background = "none"; S.classList.remove("grain");
    S.innerHTML = `<div class="abs" style="left:52px;top:0;bottom:0;display:flex;align-items:center;gap:30px">${plate(132)}
      <div><div class="eyebrow" style="font-size:15px;margin-bottom:8px">Loot Advisor</div>
      <div class="title" style="font-size:72px">Synergy Sets</div>
      <div class="tag" style="font-size:22px;margin-top:8px">%s</div></div></div>`;
  },
"""


def main():
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        sys.exit("no Edge/Chrome found")
    tmp = tempfile.mkdtemp(prefix="la_lockup_")
    for f in ("common.css", "common.js", "option1.html"):
        shutil.copy(os.path.join(SRC, f), tmp)
    p = os.path.join(tmp, "option1.html")
    s = open(p, encoding="utf-8").read()
    s2 = s.replace("  mark(small) {", (LOCK_T % TAG) + "  mark(small) {", 1)
    assert s2 != s, "option1.html layout changed - update render_lockup.py"
    open(p, "w", encoding="utf-8").write(s2)
    prof = tempfile.mkdtemp(prefix="la_lockup_prof_")
    proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=%d" % PORT, "--user-data-dir=" + prof,
                             "--allow-file-access-from-files", "--hide-scrollbars", "--no-first-run",
                             "--disable-extensions", "--force-color-profile=srgb", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=2))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.3)
        ws = WS(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=SCALE, mobile=False)
        ws.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
        ws.call("Page.navigate", url="file:///%s?mod=la&fmt=setslock" % p.replace("\\", "/"))
        t0 = time.time()
        while time.time() - t0 < 30:
            time.sleep(0.2)
            if js(ws, "window.__ready === true"):
                break
        else:
            sys.exit("page not ready")
        r = ws.call("Page.captureScreenshot", format="png")
    finally:
        proc.terminate()
    im = Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGBA")
    # crop to the drawn content (+ a margin for the plate's shadow), keep the left edge at x=0 for the page's layout
    bb = im.getchannel("A").point(lambda a: 255 if a > 2 else 0).getbbox()
    right = min(im.width, bb[2] + 8 * SCALE)
    im = im.crop((0, 0, right, im.height))
    im.save(OUT, "WEBP", quality=90, method=6)
    print("  %s  %dx%d  %.1f KB" % (os.path.relpath(OUT, HERE), im.width, im.height, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
