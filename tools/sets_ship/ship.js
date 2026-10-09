/* LootAdvisor - loader of the local Sets page (shipped with the mod, written by it into
   %LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor\Sets.html).
   The page carries no game art or text. The mod writes, next to this page, from the player's own game install:
     LootAdvisor_text.js       LA_TEXT_CB({sig, h: {handle: text}})          names / descriptions in the game language
     LootAdvisor_art_index.js  LA_ART_INDEX({sig, files: [[name, n]], missing: [paths]})
     LootAdvisor_art_<n>.js    LA_ART_CB({path: base64, ...})                 the game's own DDS textures and fonts
     LootAdvisor_state.js      LA_STATE_CB({t, seq, act, party, owned, ...})  the running game, rewritten on changes
   This loader decodes the textures (dds.js), builds the image map, resolves the text tokens in the page data, starts
   the page (window.LA_APP = app.js) and then re-loads LootAdvisor_state.js every 3 s with a fresh <script> tag
   (file:// pages may load scripts but not fetch files). */
(function () {
  "use strict";
  var DATA_EL = document.getElementById("la-data"), IMG_EL = document.getElementById("la-img");
  var DATA = JSON.parse(DATA_EL.textContent);
  var TEXT = null, ARTIDX = null, ART = {}, STATE = null, lastSig = null, lastSeenMs = 0, started = false;
  var POLL_MS = 3000, LIVE_S = 25;
  window.LA_TEXT_CB = function (t) { if (t && t.h) TEXT = t; };
  window.LA_ART_INDEX = function (x) { if (x && x.files) ARTIDX = x; };
  window.LA_ART_CB = function (o) { for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ART[k] = o[k]; };
  window.LA_STATE_CB = function (st) { onState(st); };

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  // yield to the browser without a timer: hidden / background tabs clamp timers to 1 s or more, which made the icon
  // build crawl when the page sat waiting for the game files in a tab behind the game
  function yieldNow() { return new Promise(function (r) { var c = new MessageChannel(); c.port1.onmessage = function () { c.port1.close(); r(); }; c.port2.postMessage(0); }); }
  function loadScript(src) {
    return new Promise(function (resolve) {
      var s = document.createElement("script");
      s.src = src + (src.indexOf("?") < 0 ? "?t=" : "&t=") + Date.now();
      s.onload = function () { s.remove(); resolve(true); };
      s.onerror = function () { s.remove(); resolve(false); };
      document.head.appendChild(s);
    });
  }
  function prep(msg, frac) {
    var el = document.getElementById("prep");
    if (!el) return;
    el.firstChild.nodeValue = msg;
    var bar = el.querySelector(".bar i");
    if (bar && frac != null) bar.style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + "%";
  }
  function b64bytes(s) {
    var bin = atob(s), n = bin.length, u8 = new Uint8Array(n);
    for (var i = 0; i < n; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  }

  // ---- game text: tokens "\x01<hex id>\x02" -> DATA.T[id] = [loca handle, [param texts]]
  function gameText(id) {
    var e = DATA.T[id], raw = e && TEXT && TEXT.h[e[0]];
    if (raw == null) return "";
    var p = e[1] || [];
    var t = String(raw).replace(/<br\s*\/?>/gi, " ").replace(/<[^>]+>/g, "")
      .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")
      .replace(/\[(\d+)\]/g, function (m, n) { var v = p[+n - 1]; return v != null && v !== "" ? v : m; });
    return t.replace(/turn\(s\)/g, "turns").replace(/target\(s\)/g, "targets").replace(/\s+/g, " ").trim();
  }
  var TOK = /\x01([0-9a-f]+)\x02/g;
  function resolve(o) {
    if (typeof o === "string") return o.indexOf("\x01") < 0 ? o : o.replace(TOK, function (m, id) { return gameText(parseInt(id, 16)); });
    if (Array.isArray(o)) { for (var i = 0; i < o.length; i++) o[i] = resolve(o[i]); return o; }
    if (o && typeof o === "object") { for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) o[k] = resolve(o[k]); return o; }
    return o;
  }

  // ---- game art: decode each texture once, then crop / scale per key into a PNG object URL
  function toCanvas(img) {
    var c = document.createElement("canvas"); c.width = img.w; c.height = img.h;
    c.getContext("2d").putImageData(new ImageData(img.data, img.w, img.h), 0, 0);
    return c;
  }
  function scaled(src, sx, sy, sw, sh, bw, bh) {
    var f = (bw && bh) ? Math.min(1, bw / sw, bh / sh) : 1, tw = Math.max(1, Math.round(sw * f)), th = Math.max(1, Math.round(sh * f));
    var cur = src, cx = sx, cy = sy, cw = sw, ch = sh;
    // halve step by step for a clean downscale (like the generator's Lanczos thumbnails)
    while (cw / 2 >= tw && ch / 2 >= th) {
      var h = document.createElement("canvas"); h.width = Math.round(cw / 2); h.height = Math.round(ch / 2);
      var hx = h.getContext("2d"); hx.imageSmoothingQuality = "high"; hx.drawImage(cur, cx, cy, cw, ch, 0, 0, h.width, h.height);
      cur = h; cx = 0; cy = 0; cw = h.width; ch = h.height;
    }
    var out = document.createElement("canvas"); out.width = tw; out.height = th;
    var ox = out.getContext("2d"); ox.imageSmoothingQuality = "high"; ox.drawImage(cur, cx, cy, cw, ch, 0, 0, tw, th);
    return out;
  }
  function blobUrl(canvas) {
    return new Promise(function (resolve) {
      try { canvas.toBlob(function (b) { resolve(b ? URL.createObjectURL(b) : canvas.toDataURL()); }, "image/png"); }
      catch (e) { resolve(""); }
    });
  }

  async function loadArt() {
    var tStart = Date.now();
    var files = ARTIDX.files || [];
    for (var i = 0; i < files.length; i++) {
      prep("Reading the icons from your game files (" + (i + 1) + "/" + files.length + ")...", 0.1 + 0.3 * i / files.length);
      await loadScript(files[i][0]);
    }
    var paths = DATA.artPaths, canv = {}, fontIdx = {}, IMG = {}, keys = Object.keys(DATA.art), t0 = Date.now(), jobs = [], tDec = 0, tScale = 0, tLoad = Date.now() - tStart;
    Object.keys(DATA.fonts || {}).forEach(function (k) { fontIdx[DATA.fonts[k]] = k; });
    // fonts: the game's own Quadraat from the player's install
    var FONT = { "q-reg": ["400", "normal"], "q-bold": ["700", "normal"], "q-it": ["400", "italic"] };
    Object.keys(fontIdx).forEach(function (pi) {
      var b = ART[paths[pi]], f = FONT[fontIdx[pi]];
      if (!b || !f || !window.FontFace) return;
      try { var ff = new FontFace("Quadraat", b64bytes(b), { weight: f[0], style: f[1] }); ff.load().then(function () { document.fonts.add(ff); }, function () {}); } catch (e) {}
    });
    for (var k = 0; k < keys.length; k++) {
      var key = keys[k], a = DATA.art[key], pi = a[0], p = paths[pi];
      if (k % 20 === 0) { prep("Building the icons (" + k + "/" + keys.length + ")...", 0.4 + 0.6 * k / keys.length); await yieldNow(); }
      if (canv[pi] === undefined) {
        canv[pi] = null;
        var td = Date.now();
        if (ART[p]) { try { canv[pi] = toCanvas(window.LADDS.decode(b64bytes(ART[p]))); } catch (e) { console.warn("Loot Advisor: cannot decode", p, e); } }
        tDec += Date.now() - td;
      }
      var c = canv[pi];
      if (!c) continue;
      var uv = a[3], sx = 0, sy = 0, sw = c.width, sh = c.height;
      if (uv) { sx = Math.round(uv[0] * c.width); sy = Math.round(uv[1] * c.height); sw = Math.round(uv[2] * c.width) - sx; sh = Math.round(uv[3] * c.height) - sy; }
      var ts = Date.now(), sc = scaled(c, sx, sy, sw, sh, a[1], a[2]); tScale += Date.now() - ts;
      jobs.push(blobUrl(sc).then((function (k2) { return function (u) { IMG[k2] = u; }; })(key)));
    }
    await Promise.all(jobs);
    ART = {};   // free the base64 strings
    return { IMG: IMG, ms: Date.now() - t0, load: tLoad, decode: tDec, scale: tScale };
  }

  // ---- not live (yet): the copy in the mod's install folder, or the live copy before the mod wrote the game files
  var LIVE_PATH = "%LOCALAPPDATA%\\Larian Studios\\Baldur's Gate 3\\Script Extender\\LootAdvisor\\Sets.html";
  var IS_LIVE_COPY = (function () {
    var p = location.pathname || "";
    try { p = decodeURIComponent(p); } catch (e) {}
    return /script extender[\/\\]lootadvisor[\/\\][^\/\\]*$/i.test(p);
  })();
  function offline() {
    var main = document.getElementById("main");
    if (!main || document.getElementById("offline")) return;
    var steps = IS_LIVE_COPY
      ? "<li>Start Baldur's Gate 3 with Loot Advisor enabled (it needs Script Extender).</li>" +
        "<li><b>Load a save once.</b> The mod then writes your game's icons and texts next to this page (about 10 seconds the first time).</li>" +
        "<li>This page notices it by itself and starts - no reload needed. Later you can open it from the game with <b>F6 &gt; Open Sets page</b>.</li>"
      : "<li>Start Baldur's Gate 3 with Loot Advisor enabled (it needs Script Extender).</li>" +
        "<li><b>Load a save once.</b> The mod writes the live page, with your game's own icons and texts, into the Script Extender folder.</li>" +
        "<li><b>Then open the live page:</b> in the game press <b>F6 &gt; Open Sets page</b>, or open the path below in your browser (bookmark it). " +
        "It follows your game while it runs and shows the last state when it doesn't.</li>";
    main.innerHTML = '<section class="offline" id="offline" aria-labelledby="offT">' +
      '<h2 id="offT">' + (IS_LIVE_COPY ? "Load a save once - then this page comes alive" : "Load a save once - then open the live page") + "</h2>" +
      "<p>Synergy Sets shows full loadouts for every origin and build, act by act, and ticks off what you already carry. " +
      "It uses the item icons and texts from <em>your own</em> game install, so " +
      (IS_LIVE_COPY ? "it waits until the mod has written them." : "this copy from the mod's download cannot show them.") + "</p>" +
      "<ol>" + steps + "</ol>" +
      '<p class="off-lab">The live page:</p>' +
      '<div class="off-path"><input id="offPath" type="text" readonly value="' + esc(LIVE_PATH) + '" aria-label="Path of the live page" spellcheck="false">' +
      '<button type="button" class="btn-pill" id="offCopy">Copy path</button></div>' +
      '<p class="off-hint">Paste it into the address bar of the File Explorer or the Run box (Windows key + R) - the page opens in your browser; ' +
      "bookmark it there. The game console prints the full path when the mod writes the page.</p>" +
      '<p class="off-wait" role="status"><span class="dot"></span>' + (IS_LIVE_COPY ? "Waiting for the game files..." : "This is the copy from the mod's download - it has no game files next to it.") + "</p>" +
      "</section>";
    var inp = document.getElementById("offPath"), btn = document.getElementById("offCopy");
    btn.addEventListener("click", function () {
      var done = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy path"; }, 2000); };
      var legacy = function () { inp.focus(); inp.select(); try { document.execCommand("copy"); done(); } catch (e) { btn.textContent = "Press Ctrl+C"; } };
      try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(LIVE_PATH).then(done, legacy); else legacy(); } catch (e) { legacy(); }
    });
    inp.addEventListener("focus", function () { inp.select(); });
  }

  async function boot() {
    var t0 = Date.now();
    prep("Reading the texts from your game files...", 0.02);
    while (!(await loadScript("LootAdvisor_text.js")) || !TEXT) {
      offline();
      await sleep(POLL_MS);
    }
    var off = document.getElementById("offline");
    if (off) off.parentNode.innerHTML = '<p class="loading" role="status"><span class="prep" id="prep">Preparing the page from your game files...<span class="bar"><i></i></span></span></p>';
    while (!(await loadScript("LootAdvisor_art_index.js")) || !ARTIDX) {
      prep("Waiting for the game icons (the mod is still writing them)...", 0.05);
      await sleep(POLL_MS);
    }
    var art = await loadArt();
    if (window.LA_HEADER) { try { window.LA_HEADER(art.IMG); } catch (e) { console.warn("Loot Advisor: header strip", e); } }
    resolve(DATA);
    DATA_EL.textContent = JSON.stringify(DATA);
    IMG_EL.textContent = JSON.stringify(art.IMG);
    window.LA_SHIP_INFO = { textHandles: Object.keys(TEXT.h).length, images: Object.keys(art.IMG).length, artMs: art.ms, loadMs: art.load, decodeMs: art.decode, scaleMs: art.scale, bootMs: Date.now() - t0 };
    window.LA_APP();
    started = true;
    if (STATE) applyState(STATE, true);
    poll();
  }

  // ---- live state
  function onState(st) {
    if (!st || typeof st !== "object") return;
    STATE = st; lastSeenMs = Date.now();
    if (started) applyState(st, false);
    paint();
  }
  function applyState(st, force) {
    var sig = String(st.seq) + "|" + String(st.sig || "");
    if (!force && sig === lastSig) return;
    lastSig = sig;
    if (window.LootAdvisorSets && window.LootAdvisorSets.live) window.LootAdvisorSets.live(st);
    document.title = "Loot Advisor Sets - " + (st.selected && st.selected.name ? st.selected.name + " - " : "") + "live #" + st.seq;
  }
  function poll() { loadScript("LootAdvisor_state.js"); }
  var ROMAN = { 1: "I", 2: "II", 3: "III" };
  function paint() {
    var el = document.getElementById("live");
    if (!el) return;
    var lt = el.querySelector(".lt"), st = STATE, now = Date.now() / 1000;
    if (!st) { el.className = "live"; lt.textContent = IS_LIVE_COPY ? "Waiting for the game (start Baldur's Gate 3 with Loot Advisor)" : "Not the live page · load a save once, then press F6 > Open Sets page"; return; }
    var age = Math.max(0, Math.round(now - (st.t || 0)));
    var where = (st.act ? "Act " + ROMAN[st.act] : "") + (st.regionName ? " · " + st.regionName : "") + (st.area ? " · " + st.area : "");
    var who = st.selected && st.selected.name ? " · " + st.selected.name : "";
    if (age <= LIVE_S) {
      el.className = "live on";
      var ch = Math.max(0, Math.round(now - (st.changed || st.t || 0)));
      lt.innerHTML = "<b>Live</b> · connected · last change " + (ch < 60 ? ch + " s" : Math.round(ch / 60) + " min") + " ago · " + esc(where + who);
      el.title = "Synced with your running game. The page checks for changes every 3 seconds.";
    } else {
      el.className = "live off";
      var d = new Date((st.t || 0) * 1000);
      lt.innerHTML = "<b>Game not running</b> · last update " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + (age > 86400 ? " " + d.toLocaleDateString() : "") + " · " + esc(where + who);
      el.title = "No update from the game for " + age + " s. The page shows the last state it saw.";
    }
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  setInterval(poll, POLL_MS);
  setInterval(paint, 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  window.addEventListener("focus", poll);
  poll();
  boot();
})();
