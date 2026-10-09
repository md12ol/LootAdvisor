"""Screenshots of artifact/_preview.html with headless Edge (Chrome DevTools Protocol, stdlib only).

    python tools/sets_artifact/screens.py            -> artifact/screens/*.png

Uses a throw-away browser profile in %TEMP%; never touches the user's own browser profile or the game.
"""
import base64
import json
import os
import random
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGE = os.path.join(ROOT, "artifact", "_preview.html")
OUT = os.path.join(ROOT, "artifact", "screens")
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
PORT = 9339


class WS:
    """Minimal RFC 6455 client (text frames, client masking)."""

    def __init__(self, url):
        assert url.startswith("ws://")
        hostport, path = url[5:].split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key))
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.id = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        data = text.encode()
        hdr = bytes([0x81])
        n = len(data)
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            op = b0 & 0x0F
            if op in (0x1, 0x0, 0x2):
                msg += payload
                if b0 & 0x80:
                    return msg.decode("utf-8", "replace")
            # ignore ping/pong/close

    def call(self, method, **params):
        self.id += 1
        mid = self.id
        self.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            r = json.loads(self.recv())
            if r.get("id") == mid:
                if "error" in r:
                    raise RuntimeError("%s: %s" % (method, r["error"]))
                return r.get("result", {})


def js(ws, expr):
    r = ws.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
    return (r.get("result") or {}).get("value")


def shot(ws, name, width, height, mobile=False, setup="", full=True, wait=0.6):
    ws.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=mobile)
    ws.call("Emulation.setTouchEmulationEnabled", enabled=mobile, maxTouchPoints=5)
    ws.call("Emulation.setEmulatedMedia", features=[{"name": "hover", "value": "none" if mobile else "hover"},
                                                   {"name": "pointer", "value": "coarse" if mobile else "fine"}])
    ws.call("Page.navigate", url="file:///" + PAGE.replace("\\", "/"))
    for _ in range(100):
        time.sleep(0.2)
        if js(ws, "document.readyState") == "complete" and js(ws, "!!document.querySelector('.sethead,.cmp')"):
            break
    if not js(ws, "!!window.LootAdvisorSets"):
        print("   ! page script did not start")
    if setup:
        js(ws, setup)
    time.sleep(wait)
    if full:
        h = js(ws, "Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)") or height
        ws.call("Emulation.setDeviceMetricsOverride", width=width, height=int(h), deviceScaleFactor=1, mobile=mobile)
        time.sleep(0.4)
        r = ws.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    else:
        r = ws.call("Page.captureScreenshot", format="png")
    js(ws, "try{localStorage.clear()}catch(e){}; 1")
    p = os.path.join(OUT, name + ".png")
    with open(p, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    print("  ", os.path.relpath(p, ROOT))


CLICK = "(function(sel){var e=document.querySelector(sel); if(e) e.click(); return !!e})(%s)"
HOVER = ("new Promise(function(ok){var e=document.querySelector(%s); if(!e) return ok(false); e.scrollIntoView({block:'center'});"
         "setTimeout(function(){e.dispatchEvent(new MouseEvent('mouseover',{bubbles:true})); ok(true)}, 400)})")


def main():
    os.makedirs(OUT, exist_ok=True)
    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not exe:
        sys.exit("no Edge/Chrome found")
    prof = tempfile.mkdtemp(prefix="la_shots_")
    proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=%d" % PORT, "--user-data-dir=" + prof,
                             "--allow-file-access-from-files", "--hide-scrollbars", "--no-first-run",
                             "--disable-extensions", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        q = json.dumps
        TAP = ("new Promise(function(ok){var e=document.querySelector(%s); if(!e) return ok(false); e.scrollIntoView({block:'center'});"
               "setTimeout(function(){e.click(); ok(true)}, 400)})")
        FILT = ("(function(){[['pf-durge','no'],['pf-grove','tieflings'],['pf-night','selune']].forEach(function(p){var s=document.getElementById(p[0]);"
                "s.value=p[1]; s.dispatchEvent(new Event('change',{bubbles:true}))}); return 1})()")
        # desktop 1440
        shot(ws, "desktop_astarion_act1", 1440, 900)
        shot(ws, "desktop_first_view", 1440, 900, full=False)
        shot(ws, "desktop_tooltip_item", 1440, 900, setup=HOVER % q('.doll .slot:not(.empty)'), full=False)
        shot(ws, "desktop_tooltip_formula", 1440, 900, setup=HOVER % q('.vit.ac'), full=False)
        shot(ws, "desktop_darkurge_act3", 1440, 900,
             setup=CLICK % q('[data-char="darkurge"]') + ";" + CLICK % q('[data-act="3"]'))
        shot(ws, "desktop_laezel_act3_weapon_tooltip", 1440, 900,
             setup=CLICK % q('[data-char="laezel"]') + ";" + CLICK % q('[data-act="3"]') + ";" +
             HOVER % q('.weap .slot:not(.empty)'), full=False)
        shot(ws, "desktop_playthrough_filters", 1440, 900,
             setup=CLICK % q('[data-char="karlach"]') + ";" + CLICK % q('[data-act="2"]') + ";" + FILT, full=False)
        shot(ws, "desktop_legend", 1440, 900, setup=CLICK % q('[data-legend]'), full=False)
        shot(ws, "desktop_compare", 1440, 900, setup=CLICK % q('[data-char="gale"]') + ";" + CLICK % q('#cmpToggle'))
        # tablet 768 (touch)
        shot(ws, "tablet_first_view", 768, 1024, mobile=True, full=False)
        shot(ws, "tablet_full", 768, 1024, mobile=True)
        shot(ws, "tablet_tooltip_tap", 768, 1024, mobile=True, setup=TAP % q('.doll .slot:not(.empty)'), full=False)
        # phone 390 (touch)
        shot(ws, "phone_astarion_act1", 390, 844, mobile=True)
        shot(ws, "phone_first_view", 390, 844, mobile=True, full=False)
        shot(ws, "phone_tooltip_tap", 390, 844, mobile=True, setup=TAP % q('.doll .slot:not(.empty)'), full=False)
        shot(ws, "phone_compare", 390, 844, mobile=True, setup=CLICK % q('#cmpToggle'))
        errs = js(ws, "window.__errs||[]")
        if errs:
            print("  page errors:", errs)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
