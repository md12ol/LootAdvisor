(function () {
  "use strict";
  var IMG = JSON.parse(document.getElementById("la-img").textContent);
  var DATA = JSON.parse(document.getElementById("la-data").textContent);
  var UI = DATA.ui, ITEMS = DATA.items, RULES = DATA.rules;
  // slot entries are stored once in DATA.E; sets hold indices
  DATA.chars.forEach(function (c) { ["1", "2", "3"].forEach(function (a) { (c.sets[a] || []).forEach(function (s) {
    Object.keys(s.slots).forEach(function (sl) { if (typeof s.slots[sl] === "number") s.slots[sl] = DATA.E[s.slots[sl]]; }); }); }); });
  // where-to-get info for any item that is somewhere a recommended pick (used when an alternative is swapped in)
  var INFO = {};
  DATA.E.forEach(function (e) { if (!INFO[e.sid]) INFO[e.sid] = e; });
  var SLOT_LABEL = { Helmet: "Head", Cloak: "Cloak", Breast: "Armour", Gloves: "Hands", Boots: "Feet", Amulet: "Amulet",
    Ring1: "Ring", Ring2: "Ring", MainHand: "Main hand", OffHand: "Off hand", Ranged: "Ranged", RangedOff: "Ranged off hand", Elixir: "Elixir" };
  var RAR = { Common: "Common", Uncommon: "Uncommon", Rare: "Rare", VeryRare: "Very Rare", Legendary: "Legendary", Story: "Story" };
  var ROMAN = { 1: "I", 2: "II", 3: "III" };
  var CHAR_NAME = {};
  DATA.chars.forEach(function (c) { CHAR_NAME[c.id] = c.n; });
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- image helpers: UI art as CSS variables (each data URI once), item / skill icons by key
  (function () {
    var css = ":root{";
    Object.keys(UI).forEach(function (k) { if (IMG[UI[k]]) css += "--ui-" + k.replace(/[^A-Za-z0-9_-]/g, "_") + ":url(\"" + IMG[UI[k]] + "\");"; });
    var st = document.createElement("style"); st.textContent = css + "}"; document.head.appendChild(st);
  })();
  function src(key) { return key && IMG[key] ? IMG[key] : ""; }
  function ui(k) { return src(UI[k]); }
  function img(key, cls, alt) { var s = src(key); return s ? '<img src="' + s + '" decoding="async"' + (cls ? ' class="' + cls + '"' : "") + ' alt="' + esc(alt || "") + '">' : ""; }
  function uimg(k, cls, alt) { return img(UI[k], cls, alt); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function sgn(n) { return (n >= 0 ? "+" : "") + n; }
  function rk(r) { return String(r || "Common").toLowerCase(); }
  function itemOf(sid) { return ITEMS[sid] || { n: sid, r: "Common" }; }
  function capf(t) { return t.charAt(0).toUpperCase() + t.slice(1); }
  function names(ids) { return (ids || []).map(function (o) { return CHAR_NAME[o] || o; }).join(" and ") || "another companion"; }

  // ---- per-viewer memory (works without storage: private windows, previews)
  var store = {
    get: function (k) { try { return localStorage.getItem("la-sets-" + k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem("la-sets-" + k, v); } catch (e) {} },
    json: function (k, d) { try { var v = JSON.parse(localStorage.getItem("la-sets-" + k)); return v && typeof v === "object" ? v : d; } catch (e) { return d; } }
  };
  var DEF_F = { durge: "any", grove: "any", night: "any", isobel: "any", crime: "any", gone: false, party: false };
  var F = Object.assign({}, DEF_F, store.json("filters", {}));
  var HAVE_M = store.json("have", {}), HAVE = Object.assign({}, HAVE_M);
  var S = { char: store.get("char") || DATA.chars[0].id, act: +(store.get("act") || 1), set: null, cmp: false, cmpA: null, cmpB: null,
    lvl: store.get("lvl") === "12" ? "12" : "act", showHidden: false };
  if (!(S.act >= 1 && S.act <= 3)) S.act = 1;

  // ================================================================= live sync (local Sets page shipped with the mod)
  // The mod writes the running game's state; the page loader passes it to LootAdvisorSets.live(state). In the
  // claude.ai artifact LIVE stays null and nothing below changes the page.
  var LIVE = null, LIVE_HAVE = {}, LIVE_PLAY = {}, OVR = store.json("ovr", {}), liveSel = null, liveAct = null;
  var PLAY_KEYS = ["durge", "grove", "night", "isobel"];
  var LIVE_SKIP = { shar: 1, selune: 1, goblins: 1, tieflings: 1, isobel_kill: 1, isobel_dead: 1, isobel_alive: 1 };
  function recomputeHave() { HAVE = Object.assign({}, HAVE_M, LIVE_HAVE); }
  function liveF() {
    if (!LIVE) return;
    PLAY_KEYS.forEach(function (k) { F[k] = OVR[k] != null ? OVR[k] : (LIVE_PLAY[k] || "any"); });
    F.party = false;   // contested items follow the real party instead
  }
  function inParty(ch) { return !!(LIVE && LIVE.inParty && LIVE.inParty[ch]); }
  function setChar(set) { return String(set.id).split(".")[0]; }
  // a contested item in the live game: "give" = an owner who gets more from it is in the party (use the alternative),
  // "shared" = tied exactly with a party member, "free" = nobody with a better claim is in the party
  function liveContest(set, e) {
    var me = setChar(set), it = ITEMS[e.sid] || {}, tie = it.ot || [], owners = (e.owner && e.owner.length ? e.owner : it.o) || [];
    if (tie.indexOf(me) >= 0) {
      var sh = tie.filter(function (c) { return c !== me && inParty(c); });
      return sh.length ? { k: "shared", who: sh } : { k: "free", who: [] };
    }
    var pr = owners.filter(function (c) { return c !== me && inParty(c); });
    return pr.length ? { k: "give", who: pr } : { k: "free", who: owners.filter(function (c) { return c !== me; }) };
  }
  function liveLevel(set) {
    if (!LIVE || set.act !== LIVE.act) return 0;
    var ch = (LIVE.chars || {})[setChar(set)];
    return ch && ch.level ? Math.min(DATA.level, Math.max(1, ch.level)) : 0;
  }
  function liveBuild(c) { var ch = LIVE && (LIVE.chars || {})[c.id]; return ch && ch.build || null; }
  function playFromGame(st) {
    var p = st.paths || {}, out = {};
    out.durge = st.durge ? "yes" : "no";
    out.grove = p.tieflings === "yes" ? "tieflings" : p.goblins === "yes" ? "goblins" : "any";
    out.night = p.shar === "yes" ? "shar" : p.selune === "yes" ? "selune" : "any";
    out.isobel = (p.isobel_kill === "yes" || p.isobel_dead === "yes") ? "killed" : p.isobel_alive === "yes" ? "alive" : "any";
    return out;
  }
  // story codes the playthrough bar does not cover, checked against the game's state
  function liveBlock(codes) {
    if (!LIVE) return null;
    for (var i = 0; i < codes.length; i++) {
      var c = codes[i], neg = c.charAt(0) === "!", body = neg ? c.slice(1) : c, m = /^(\w+):(.+)$/.exec(body), kind = m ? m[1] : "path", arg = m ? m[2] : body;
      if (kind === "path" && !LIVE_SKIP[arg]) {
        var st = (LIVE.paths || {})[arg];
        if (neg && st === "yes") return "lost in your game (" + arg.replace(/_/g, " ") + ")";
        if (!neg && st === "no") return "that story path is closed in your game";
      } else if ((kind === "origin" || kind === "party") && !neg) {
        var cs = (LIVE.comp || {})[arg];
        if (cs && cs.dead) return (CHAR_NAME[arg] || arg) + " is dead in your game";
      }
    }
    return null;
  }

  function charById(id) { for (var i = 0; i < DATA.chars.length; i++) if (DATA.chars[i].id === id) return DATA.chars[i]; return null; }
  function buildOf(c, bid) { for (var i = 0; i < c.builds.length; i++) if (c.builds[i].id === bid) return c.builds[i]; return null; }
  function allSets(c) { return [].concat(c.sets["1"] || [], c.sets["2"] || [], c.sets["3"] || []); }
  function setById(c, id) { var a = allSets(c); for (var i = 0; i < a.length; i++) if (a[i].id === id) return a[i]; return null; }
  function findSet(id) { for (var i = 0; i < DATA.chars.length; i++) { var s = setById(DATA.chars[i], id); if (s) return { c: DATA.chars[i], s: s }; } return null; }
  function curChar() { return charById(S.char); }
  function charVisible(c) { return !(c.id === "darkurge" && F.durge === "no"); }

  // ================================================================= "My playthrough" model (F1)
  // why an item cannot be had in this playthrough (null = it can). codes = story codes, tags = severity tags
  function blockReason(codes, tags) {
    codes = codes || []; tags = tags || [];
    function has(c) { return codes.indexOf(c) >= 0; }
    if (has("durge") && F.durge === "no") return "Dark Urge playthrough only";
    if (has("path:tieflings") && F.grove === "goblins") return "needs the tiefling side of the grove fight";
    if (has("path:goblins") && F.grove === "tieflings") return "needs the goblin side of the grove fight";
    if (has("!path:goblins") && F.grove === "goblins") return "lost when you sided with the goblins";
    if (has("path:shar") && F.night === "selune") return "needs the Shar path (Nightsong killed)";
    if (has("path:selune") && F.night === "shar") return "needs the Selûne path (Nightsong spared)";
    if (has("!path:shar") && F.night === "shar") return "lost once the Nightsong is killed";
    if (has("!path:selune") && F.night === "selune") return "lost once the Nightsong is spared";
    if (has("!path:isobel_kill") && F.isobel === "killed") return "lost once Isobel is killed";
    if (tags.indexOf("crime") >= 0 && F.crime === "no") return "needs theft or killing a neutral";
    return liveBlock(codes);
  }
  function itemBlock(sid) { var it = ITEMS[sid]; return it ? blockReason(it.cc, it.tg) : null; }
  // the item actually shown in a slot under the current playthrough settings
  function resolveSlot(set, sl) {
    var e = set.slots[sl];
    if (!e) return null;
    var r = { e: e, sid: e.sid, swap: null };
    function alt(kind, why) {
      var to = kind === "pa" ? e.pa : kind === "ca" ? e.ca : kind === "oa" ? e.oa : (e.fbE ? null : e.fb);
      if (to && ITEMS[to]) {
        var b2 = itemBlock(to);
        if (b2) { r.sid = null; r.swap = { kind: "empty", why: why + "; the alternative " + itemOf(to).n + " is out too (" + b2 + ")" }; }
        else { r.sid = to; r.swap = { kind: kind, why: why }; }
      } else { r.sid = null; r.swap = { kind: "empty", why: why + (e.fbE && e.fb ? "; " + e.fb : "; no alternative for this slot") }; }
    }
    var br = blockReason((e.cond || []).map(function (x) { return x.c; }), e.tags);
    var caB = e.ca && ITEMS[e.ca] ? blockReason(((ITEMS[e.ca].cc) || []).filter(function (c) { return c !== "durge"; }), ITEMS[e.ca].tg) : "x";
    if (br) alt("fb", br);
    else if (e.ca && F.durge === "yes" && !caB) alt("ca", "Dark Urge playthrough: " + itemOf(e.ca).n + " is better here");
    else if (e.oa && HAVE[e.oa] && ITEMS[e.oa]) { r.sid = e.oa; r.swap = { kind: "oa", why: "you have " + itemOf(e.oa).n + ", which beats it" + (e.oaGain ? " (+" + e.oaGain + ")" : "") }; }
    else if (LIVE && e.pa && liveContest(set, e).k === "give") alt("pa", names(liveContest(set, e).who) + " is in your party and gets more from " + itemOf(e.sid).n);
    else if (!LIVE && F.party && e.pa) alt("pa", names(e.owner) + " gets more from " + itemOf(e.sid).n);
    else if (e.own && F.gone && !HAVE[e.sid]) alt("fb", "an Act " + ROMAN[e.act] + " item you don't have");
    return r;
  }
  function viewOf(set) {
    if (set._v && set._v.key === fkey()) return set._v;
    var v = { key: fkey(), slots: {}, items: {}, hidden: null, nSwap: 0, total: 0, ready: 0 }, used = {};
    DATA.slots.forEach(function (sl) {
      var r = resolveSlot(set, sl); if (!r) return;
      // a promoted item (owned / Dark Urge alternative) can fill only one slot of a set
      if (r.swap && (r.swap.kind === "oa" || r.swap.kind === "ca") && used[r.sid]) { r.sid = r.e.sid; r.swap = null; }
      if (r.sid) used[r.sid] = 1;
      v.slots[sl] = r; v.total++;
      if (r.sid) v.items[sl] = { sid: r.sid };
      if (r.swap) { v.nSwap++; if (r.swap.kind === "ca" || r.swap.kind === "oa") v.nUp = (v.nUp || 0) + 1; }
      if (r.e.core && r.swap && ["pa", "ca", "oa"].indexOf(r.swap.kind) < 0 && !(r.e.own && F.gone)) v.hidden = v.hidden || (itemOf(r.e.sid).n + ": " + r.swap.why.split(";")[0]);
      if (r.sid && !(r.sid === r.e.sid && r.e.own && !HAVE[r.e.sid])) v.ready++;
    });
    v.tags = setTags(set, v);
    set._v = v;
    return v;
  }
  function fkey() { return JSON.stringify(F) + "|" + JSON.stringify(HAVE) + (LIVE ? "|" + JSON.stringify([LIVE.inParty, LIVE.paths, LIVE.comp]) : ""); }
  // severity per shown slot (F6): story locks, theft / kills, missable, earlier act, party conflict. Mild tips not counted.
  function slotTags(set, r) {
    var t = {};
    if (!r || !r.sid) return t;
    var base = r.sid === r.e.sid ? (r.e.tags || []) : ((ITEMS[r.sid] || {}).tg || []);
    base.forEach(function (x) { t[x] = 1; });
    if (r.sid === r.e.sid && r.e.own) t.own = 1;
    if (r.sid === r.e.sid && r.e.pa) t.party = 1;
    // live: a contested item whose better owner is not in the party is no conflict
    if (LIVE && t.party && r.sid === r.e.sid && liveContest(set, r.e).k === "free") delete t.party;
    return t;
  }
  function setTags(set, v) {
    var n = { story: 0, crime: 0, miss: 0, own: 0, party: 0 };
    Object.keys(v.slots).forEach(function (sl) { var t = slotTags(set, v.slots[sl]); Object.keys(n).forEach(function (k) { if (t[k]) n[k]++; }); });
    return n;
  }
  var TAG_TXT = { story: ["story lock", "story locks", "Needs a story choice"], crime: ["theft / kill", "thefts / kills", "Needs theft or killing a neutral"],
    miss: ["missable", "missable", "Can be missed: get it before a later choice or the end of the act"],
    own: ["from an earlier act", "from earlier acts", "Earlier-act item: only if you kept it"], party: ["party conflict", "party conflicts", "Another companion gets more from it"] };
  function pills(n, compact) {
    var h = "";
    ["story", "crime", "miss", "own", "party"].forEach(function (k) {
      if (!n[k]) return;
      var t = TAG_TXT[k], full = n[k] + " " + (n[k] === 1 ? t[0] : t[1]);
      h += '<span class="pill p-' + k + '" title="' + esc(t[2]) + '" aria-label="' + esc(full) + '">' + (compact ? n[k] + " " + ({ story: "story", crime: "crime", miss: "missable", own: "earlier", party: "party" })[k] : esc(full)) + "</span>";
    });
    return h;
  }
  function visibleSets(c, act) {
    var all = c.sets[String(act)] || [], vis = [], hid = [];
    all.forEach(function (s) { (viewOf(s).hidden ? hid : vis).push(s); });
    return { vis: vis, hid: hid, all: all };
  }
  function rankLabel(i) { return i === 0 ? "Main pick" : i < 3 ? "Alternative " + i : "Option " + (i + 1); }
  function rankOf(c, s) { var l = visibleSets(c, s.act).vis, i = l.indexOf(s); return i < 0 ? "Hidden by your playthrough" : rankLabel(i); }
  function curSets() { var v = visibleSets(curChar(), S.act); return S.showHidden ? v.vis.concat(v.hid) : v.vis; }
  function curSet() {
    var c = curChar(), s = S.set && setById(c, S.set);
    if (!s || s.act !== S.act) {
      var rem = store.get("set:" + c.id + ":" + S.act), l = curSets();
      s = (rem && setById(c, rem)) || l[0] || (c.sets[String(S.act)] || [])[0] || null;
      S.set = s && s.id;
    }
    return s;
  }

  // ================================================================= character sheet (computed here; reference in Python)
  // Same rules as compute_sheet() in tools/build_sets_artifact.py (verified by tools/sets_artifact/verify_sheet.py).
  var ABS = ["STR", "DEX", "CON", "INT", "WIS", "CHA"];
  var ABN = { STR: "Strength", DEX: "Dexterity", CON: "Constitution", INT: "Intelligence", WIS: "Wisdom", CHA: "Charisma" };
  var DICE_RE = /^(\d+)d(\d+)$/;
  function pyStr(v) { return v == null ? "None" : String(v); }
  function num(x) {
    if (typeof x === "number") return isFinite(x) ? Math.trunc(x) : null;
    var t = String(x == null ? "" : x).trim();
    return /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(t) ? Math.trunc(Number(t)) : null;
  }
  function safeEval(expr, nm) {
    var toks = String(expr).match(/\d+(?:\.\d+)?|[A-Za-z_]\w*|[-+*(),]|\S/g) || [], i = 0;
    function peek() { return toks[i]; }
    function expr_() { var v = term(); while (peek() === "+" || peek() === "-") { var o = toks[i++], r = term(); v = o === "+" ? v + r : v - r; } return v; }
    function term() { var v = unary(); while (peek() === "*") { i++; v = v * unary(); } return v; }
    function unary() { if (peek() === "-") { i++; return -unary(); } return atom(); }
    function atom() {
      var t = toks[i++];
      if (t === undefined) throw 0;
      if (/^\d/.test(t)) return Number(t);
      if (t === "(") { var v = expr_(); if (toks[i++] !== ")") throw 0; return v; }
      if ((t === "max" || t === "min") && peek() === "(") {
        i++; var args = [expr_()]; while (peek() === ",") { i++; args.push(expr_()); }
        if (toks[i++] !== ")") throw 0; return t === "max" ? Math.max.apply(null, args) : Math.min.apply(null, args);
      }
      if (Object.prototype.hasOwnProperty.call(nm, t)) return nm[t];
      throw 0;
    }
    try { var v = expr_(); if (i !== toks.length) return null; return typeof v === "number" && isFinite(v) ? Math.trunc(v) : null; } catch (e) { return null; }
  }
  function diceAvg(d) { var m = DICE_RE.exec(String(d).trim()); return m ? (+m[1]) * ((+m[2]) + 1) / 2 : 0; }
  function mod(v) { return Math.floor((v - 10) / 2); }
  function pctd(n) { return (n >= 0 ? "+" : "") + n; }
  function letters(s) { return String(s).toLowerCase().replace(/[^a-z]/g, ""); }
  function splitCamel(w) { return String(w).replace(/([a-z])(?=[A-Z])/g, "$1 "); }
  function resolveCond(cond, styles, feats) {
    var m = /^\s*(not\s+)?HasPassive\('([A-Za-z_]+)'(?:,\s*context\.Source)?\)\s*$/.exec(cond || "");
    if (!m) return null;
    var neg = !!m[1], p = m[2], has;
    if (p.indexOf("FightingStyle_") === 0) {
      var want = splitCamel(p.slice(14)).replace("Defense", "Defence").replace("Dueling", "Duelling");
      has = styles.some(function (s) { return letters(s).indexOf(letters(want).slice(0, 6)) === 0; });
    } else {
      var w2 = letters(splitCamel(p).replace("Armor", "Armour"));
      has = feats.some(function (f) { return letters(f.replace("Armor", "Armour")).indexOf(w2) === 0; });
    }
    return has !== neg;
  }
  function collectBoosts(items) {
    var out = [];
    DATA.slots.forEach(function (slot) {
      var it = items[slot]; if (!it || !it.sid) return;
      var rec = ITEMS[it.sid]; if (!rec) return;
      var bz = rec.bz || {}, hand = (slot === "MainHand" || slot === "Ranged") ? "m" : (slot === "OffHand" || slot === "RangedOff") ? "o" : null;
      var lst = (bz.a || []).concat(hand ? (bz[hand] || []) : []);
      lst.forEach(function (e) { out.push({ cond: e.c, name: e.n, args: e.g, src: rec.n || it.sid, via: e.v, scope: e.s ? slot : null, h: e.h, ch: e.ch }); });
    });
    return out;
  }
  function computeSheet(BI, items, level) {
    var seq = BI.seq.slice(0, level), classes = {}, clsOrder = [];
    seq.forEach(function (c) { classes[c] = (classes[c] || 0) + 1; if (clsOrder.indexOf(c) < 0) clsOrder.push(c); });
    var profB = 2 + Math.floor((level - 1) / 4), profSet = {};
    BI.prof.forEach(function (p) { profSet[p] = 1; });
    var featsOn = BI.feats.filter(function (f) { return f.lv == null || f.lv <= level; });
    var featNames = featsOn.map(function (f) { return f.n; }), styles = BI.styles.slice();
    var later = BI.feats.filter(function (f) { return f.lv != null && f.lv > level && Object.keys(f.asi || {}).length; });
    var boosts = collectBoosts(items);
    boosts.forEach(function (x) { var r = x.cond ? resolveCond(x.cond, styles, featNames) : null; if (r === true) x.cond = null; else if (r === false) x.never = true; });
    var uncond = boosts.filter(function (x) { return !x.cond; }), cond = boosts.filter(function (x) { return x.cond && !x.never; });
    var F_ = {}, base = {}, abF = {}, L12 = DATA.level;
    ABS.forEach(function (k) {
      var v = BI.base[k], minus = 0;
      later.forEach(function (f) { minus += (f.asi[k] || 0); });
      base[k] = v - minus;
      abF[k] = !minus ? [v + " planned for level " + L12 + " (build plan)"] :
        [v + " planned for level " + L12 + ", minus " + minus + " from ability improvements after level " + level + " = " + (v - minus)];
    });
    var ab = Object.assign({}, base);
    uncond.forEach(function (x) {
      if (x.name === "Ability" && x.args.length && RULES.abil[x.args[0]]) {
        var k = RULES.abil[x.args[0]], n = x.args.length > 1 ? num(x.args[1]) : null, cap = x.args.length > 2 ? num(x.args[2]) : 30;
        if (n) { var nw = Math.min(ab[k] + n, Math.max(cap || 30, ab[k])); abF[k].push(pctd(n) + " " + x.src + " -> " + nw + (x.args.length > 2 ? " (max " + cap + ")" : "")); ab[k] = nw; }
      }
    });
    uncond.forEach(function (x) {
      if (x.name === "AbilityOverrideMinimum" && x.args.length && RULES.abil[x.args[0]]) {
        var k = RULES.abil[x.args[0]], n = x.args.length > 1 ? num(x.args[1]) : null;
        if (n && n > ab[k]) { abF[k].push(x.src + " sets it to " + n); ab[k] = n; }
        else if (n) abF[k].push(x.src + " (at least " + n + ") - no change");
      }
    });
    var M = {}; ABS.forEach(function (k) { M[k] = mod(ab[k]); });
    var nm = { ProficiencyBonus: profB, Level: level, CharacterLevel: level };
    ABS.forEach(function (k) { nm[ABN[k] + "Modifier"] = M[k]; });
    function val(expr) { var n = num(expr); return n !== null && /^-?\d+(\.\d+)?$/.test(String(expr).trim()) ? n : safeEval(expr, nm); }
    var subCls = {}; BI.subs.forEach(function (s) { subCls[s.cls] = s.n; });
    var hexblade = subCls.Warlock === "Hexblade" && (classes.Warlock || 0) > 0;
    var draconic = subCls.Sorcerer === "Draconic" && (classes.Sorcerer || 0) > 0;
    // HP
    var hp = 0, hpF = [], first = true;
    clsOrder.forEach(function (c) {
      var die = RULES.hitDie[c] || 8, lv = classes[c], half = Math.floor(die / 2) + 1;
      if (first) {
        hp += die + M.CON + (lv - 1) * (half + M.CON);
        hpF.push(lv > 1 ? c + " 1: d" + die + " max " + die + " + CON " + pctd(M.CON) + "; " + c + " 2-" + lv + ": " + (lv - 1) + " x (" + half + " + CON " + pctd(M.CON) + ")"
          : c + " 1: d" + die + " max " + die + " + CON " + pctd(M.CON));
        first = false;
      } else { hp += lv * (half + M.CON); hpF.push(c + " x" + lv + ": " + lv + " x (" + half + " + CON " + pctd(M.CON) + ")"); }
    });
    if (draconic) { hp += classes.Sorcerer || 0; hpF.push("Draconic Resilience +" + (classes.Sorcerer || 0)); }
    if (featNames.some(function (f) { return f.indexOf("Tough") === 0; })) { hp += 2 * level; hpF.push("Tough +" + 2 * level); }
    uncond.forEach(function (x) { if (x.name === "IncreaseMaxHP" && x.args.length) { var n = val(x.args[0]); if (n) { hp += n; hpF.push(pctd(n) + " " + x.src); } } });
    F_.hp = hpF;
    // AC
    var body = items.Breast || {}, brec = body.sid ? ITEMS[body.sid] : null, ba = (brec && brec.arm) || {}, cat = ba.cat, acF = [], ac, armoured;
    if ((cat === "Light" || cat === "Medium" || cat === "Heavy") && ba.ac != null) {
      var cap = ba.cap, dx = cat === "Light" ? M.DEX : cat === "Medium" ? Math.min(M.DEX, cap != null ? cap : 2) : 0;
      ac = ba.ac + dx;
      acF.push(brec.n + " " + cat.toLowerCase() + " armour " + ba.ac + " + DEX " + pctd(dx) + (cat === "Medium" ? " (max " + (cap != null ? cap : 2) + ")" : cat === "Heavy" ? " (none)" : ""));
      armoured = true;
    } else {
      armoured = false;
      var opts = [[10 + M.DEX, "10 + DEX " + pctd(M.DEX) + " (no armour)"]];
      if (classes.Barbarian) opts.push([10 + M.DEX + M.CON, "Unarmoured Defence 10 + DEX " + pctd(M.DEX) + " + CON " + pctd(M.CON)]);
      if (classes.Monk) opts.push([10 + M.DEX + M.WIS, "Unarmoured Defence 10 + DEX + WIS"]);
      if (draconic) opts.push([13 + M.DEX, "Draconic Resilience 13 + DEX " + pctd(M.DEX)]);
      opts.sort(function (a, b) { return a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0); });
      var best = opts[opts.length - 1]; ac = best[0];
      acF.push(best[1] + (brec ? " (" + brec.n + " is clothing)" : ""));
    }
    var off = items.OffHand || {}, orec = off.sid ? ITEMS[off.sid] : null, oa = (orec && orec.arm) || {};
    if (oa.sh) { ac += oa.ac || 2; acF.push(pctd(oa.ac || 2) + " shield " + orec.n); }
    uncond.forEach(function (x) { if (x.name === "AC" && x.args.length) { var n = val(x.args[0]); if (n) { ac += n; acF.push(pctd(n) + " " + x.src); } } });
    if (armoured && styles.some(function (s) { return s.indexOf("Defence") === 0; })) { ac += 1; acF.push("+1 Fighting Style: Defence"); }
    F_.ac = acF;
    // initiative, speed
    var ini = M.DEX, iniF = ["DEX " + pctd(M.DEX)];
    if (featNames.some(function (f) { return f.indexOf("Alert") === 0; })) { ini += 5; iniF.push("+5 Alert (feat in the build plan)"); }
    uncond.forEach(function (x) { if (x.name === "Initiative" && x.args.length) { var n = val(x.args[0]); if (n) { ini += n; iniF.push(pctd(n) + " " + x.src); } } });
    F_.init = iniF;
    var spd = 9, spdF = ["9 m base (all origin races)"];
    if ((classes.Barbarian || 0) >= 5 && cat !== "Heavy") { spd += 3; spdF.push("+3 m Fast Movement (Barbarian 5)"); }
    uncond.forEach(function (x) {
      if (x.name === "ActionResource" && x.args.length && x.args[0] === "Movement") {
        var n = x.args.length > 1 ? parseFloat(x.args[1]) : 0; if (!/^\s*[-+]?(\d+\.?\d*|\.\d+)\s*$/.test(x.args[1] || "")) n = 0;
        if (n) { spd += n; spdF.push(pctd(n) + " m " + x.src); }
      }
    });
    F_.speed = spdF;
    // resistances: one row per type
    var res = [];
    function addRes(t, l, s) {
      for (var i = 0; i < res.length; i++) if (res[i].t === t) { if (res[i].src.split("; ").indexOf(s) < 0) res[i].src += "; " + s; if (l === "Immune") res[i].l = "Immune"; return; }
      res.push({ t: t, l: l, src: s });
    }
    (RULES.raceRes[BI.race] || []).forEach(function (r) { addRes(r[0], r[1], r[2]); });
    uncond.forEach(function (x) {
      if (x.name === "Resistance" && x.args.length >= 2) x.args[0].split(/[|,]/).forEach(function (t) { t = t.trim(); if (RULES.dmgTypes.indexOf(t) >= 0 || t === "All" || t === "Physical") addRes(t, x.args[1], x.src); });
    });
    var cres = [];
    cond.forEach(function (x) { if (x.name === "Resistance" && x.args.length >= 2) cres.push({ t: x.args[0], l: x.args[1], src: x.src, cond: x.ch || "in some situations" }); });
    if (classes.Barbarian) cres.push({ t: "Bludgeoning, Piercing, Slashing", l: "Resistant", src: "Rage (Barbarian)", cond: "while raging" });
    // attacks
    var rollAll = uncond.filter(function (x) { return x.name === "RollBonus" && x.args.length; });
    var flatDmg = uncond.filter(function (x) { return x.name === "DamageBonus" && x.args.length; });
    var charDice = uncond.filter(function (x) { return x.name === "CharacterWeaponDamage" && x.args.length; });
    function attackRow(slot) {
      var it = items[slot] || {}, rec = it.sid ? ITEMS[it.sid] : null;
      if (!rec || !rec.wpn) return null;
      var w = rec.wpn, props = w.props || [], ranged = !!rec.rng, offhand = slot === "OffHand" || slot === "RangedOff";
      var wprof = w.prof || [], proficient = wprof.some(function (p) { return profSet[p]; }) || !wprof.length, ak, akTxt;
      if (ranged) { ak = "DEX"; akTxt = "DEX (ranged)"; }
      else if (props.indexOf("Finesse") >= 0) { ak = M.DEX >= M.STR ? "DEX" : "STR"; akTxt = ak + " (finesse, higher of STR/DEX)"; }
      else { ak = "STR"; akTxt = "STR (melee)"; }
      if (hexblade && proficient && M.CHA > M[ak]) { ak = "CHA"; akTxt = "CHA (Hex Warrior, Hexblade)"; }
      var am = M[ak], ench = w.ench || 0, hit = am + (proficient ? profB : 0) + ench;
      var f = [akTxt + " " + pctd(am), proficient ? "proficiency +" + profB : "not proficient (+0)"];
      if (ench) f.push("enchantment " + pctd(ench));
      var kinds = { Attack: 1, WeaponAttack: 1 }; kinds[ranged ? "RangedWeaponAttack" : "MeleeWeaponAttack"] = 1;
      var diceB = [];
      rollAll.forEach(function (x) {
        if (kinds[x.args[0]]) {
          var n = x.args.length > 1 ? val(x.args[1]) : null;
          if (n !== null && n !== 0) { hit += n; f.push(pctd(n) + " " + x.src); }
          else if (x.args.length > 1 && DICE_RE.test(x.args[1].replace(/^[+-]+/, ""))) diceB.push(x.args[1] + " " + x.src);
        }
      });
      if (ranged && styles.some(function (s) { return s.indexOf("Archery") === 0; })) { hit += 2; f.push("+2 Fighting Style: Archery"); }
      var twoH = props.indexOf("Twohanded") >= 0, useVer = !!(w.ver && !twoH && !offhand && !((items.OffHand || {}).sid));
      var dice = useVer ? w.ver : w.dmg, dparts = [[dice, w.dt]], flat = ench;
      var df = [pyStr(dice) + " " + pyStr(w.dt) + (useVer ? " (versatile, two hands)" : "")];
      if (!offhand || am < 0 || styles.some(function (s) { return s.indexOf("Two-Weapon") === 0; })) { flat += am; df.push(ak + " " + pctd(am)); }
      else df.push("off hand: no ability modifier (no Two-Weapon Fighting style)");
      if (ench) df.push("enchantment " + pctd(ench));
      var offSid = (items.OffHand || {}).sid;
      if (!ranged && !offhand && !twoH && !useVer && styles.some(function (s) { return s.indexOf("Duel") === 0; }) && !(offSid && ITEMS[offSid] && ITEMS[offSid].wpn)) { flat += 2; df.push("+2 Fighting Style: Duelling"); }
      (w.extra || []).forEach(function (e) { var m = /^(\d+d\d+)\s+(\w+)/.exec(String(e)); if (m) { dparts.push([m[1], m[2]]); df.push(m[1] + " " + m[2] + " (weapon)"); } });
      flatDmg.forEach(function (x) { var n = val(x.args[0]), t = x.args.length > 1 ? x.args[1] : null; if (n) { flat += n; df.push(pctd(n) + " " + x.src + (t ? " " + t : "")); } });
      charDice.concat(uncond.filter(function (y) { return y.name === "WeaponDamage" && y.scope === slot; })).forEach(function (x) {
        var d0 = x.args[0], t = x.args.length > 1 ? x.args[1] : w.dt;
        if (DICE_RE.test(d0)) { dparts.push([d0, t]); df.push(d0 + " " + pyStr(t) + " " + x.src); }
      });
      var cnotes = [];
      cond.forEach(function (x) {
        var c = x.cond || "";
        if (["DamageBonus", "WeaponDamage", "CharacterWeaponDamage", "RollBonus"].indexOf(x.name) < 0 || (x.scope !== null && x.scope !== slot)) return;
        var simple = /^\s*(not\s+)?Is(Ranged|Melee)(Weapon)?Attack\(\)\s*$/.exec(c);
        if (simple) {
          var kr = simple[2] === "Ranged", applies = (kr === ranged) !== !!simple[1];
          if (!applies) return;
          var where = "only " + (ranged ? "ranged" : "melee") + " attacks", a0 = x.args.length ? x.args[0] : "";
          if (x.name === "RollBonus") {
            if (kinds[a0] && x.args.length > 1 && val(x.args[1])) { hit += val(x.args[1]); f.push(pctd(val(x.args[1])) + " " + x.src + " (" + where + ")"); return; }
          } else if (DICE_RE.test(a0)) {
            var t2 = x.args.length > 1 ? x.args[1] : w.dt; dparts.push([a0, t2]); df.push(a0 + " " + pyStr(t2) + " " + x.src + " (" + where + ")"); return;
          } else if (val(a0)) { flat += val(a0); df.push(pctd(val(a0)) + " " + x.src + " (" + where + ")"); return; }
        }
        cnotes.push(x.h + " (" + (x.ch || "in some situations") + ") - " + x.src);
      });
      var avg = flat; dparts.forEach(function (d) { avg += diceAvg(d[0]); });
      var dmgTxt = [dparts[0][0] + (flat ? pctd(flat) : "") + " " + (dparts[0][1] || "")].concat(dparts.slice(1).map(function (d) { return d[0] + " " + pyStr(d[1]); })).join(" + ");
      return { slot: slot, n: rec.n, sid: it.sid, hit: hit, hitf: f, dmg: dmgTxt, avg: Math.round(avg * 10) / 10, dmgf: df, dt: dparts[0][1],
        cond: cnotes, dice: diceB, ranged: ranged, off: offhand };
    }
    var attacks = ["MainHand", "OffHand", "Ranged", "RangedOff"].map(attackRow).filter(Boolean);
    var nAtt = 1, attF = "1 attack per action";
    if ((classes.Fighter || 0) >= 11) { nAtt = 3; attF = "Fighter 11: Improved Extra Attack"; }
    else if (["Fighter", "Barbarian", "Paladin", "Ranger", "Monk"].some(function (c) { return (classes[c] || 0) >= 5; })) { nAtt = 2; attF = "Extra Attack (level 5 of a martial class)"; }
    else if ((classes.Warlock || 0) >= 5 && (BI.thirsting || hexblade)) { nAtt = 2; attF = "Thirsting Blade / Pact of the Blade (Warlock 5+, assumed for blade builds)"; }
    else if ((classes.Bard || 0) >= 6 && subCls.Bard === "Swords") { nAtt = 2; attF = "Extra Attack (College of Swords 6)"; }
    else if ((classes.Wizard || 0) >= 6 && subCls.Wizard === "Bladesinging") { nAtt = 2; attF = "Extra Attack (Bladesinging 6)"; }
    // spellcasting
    var casters = clsOrder.filter(function (c) { return RULES.castAbil[c]; }).map(function (c) { return [c, RULES.castAbil[c]]; });
    if (subCls.Fighter === "Eldritch Knight" && (classes.Fighter || 0) >= 3) casters.push(["Fighter", "INT"]);
    if (subCls.Rogue === "Arcane Trickster" && (classes.Rogue || 0) >= 3) casters.push(["Rogue", "INT"]);
    var spell = null;
    if (casters.length) {
      var bestC = casters[0];
      casters.forEach(function (t) { var a = [classes[t[0]] || 0, M[t[1]]], b = [classes[bestC[0]] || 0, M[bestC[1]]]; if (a[0] > b[0] || (a[0] === b[0] && a[1] > b[1])) bestC = t; });
      var c0 = bestC[0], ak0 = bestC[1], dc = 8 + profB + M[ak0], dcf = ["8 + proficiency " + profB + " + " + ak0 + " " + pctd(M[ak0]) + " (" + c0 + ")"];
      var sa = { r: profB + M[ak0], m: profB + M[ak0] }, saf = { r: ["proficiency " + profB + " + " + ak0 + " " + pctd(M[ak0])], m: ["proficiency " + profB + " + " + ak0 + " " + pctd(M[ak0])] };
      uncond.forEach(function (x) {
        if (x.name === "SpellSaveDC" && x.args.length) { var n = val(x.args[0]); if (n) { dc += n; dcf.push(pctd(n) + " " + x.src); } }
        if (x.name === "RollBonus" && x.args.length && ["SpellAttack", "MeleeSpellAttack", "RangedSpellAttack", "Attack"].indexOf(x.args[0]) >= 0) {
          var n2 = x.args.length > 1 ? val(x.args[1]) : null;
          if (n2) {
            var k = x.args[0], hands = (k === "SpellAttack" || k === "Attack") ? ["r", "m"] : k === "RangedSpellAttack" ? ["r"] : ["m"];
            hands.forEach(function (hh) { sa[hh] += n2; saf[hh].push(pctd(n2) + " " + x.src); });
          }
        }
      });
      spell = { abil: ak0, cls: c0, dc: dc, dcf: dcf, atk: sa.r, atkf: saf.r, atkM: sa.m, atkMf: saf.m };
    }
    var SKIP = ["Ability", "AbilityOverrideMinimum", "IncreaseMaxHP", "AC", "Initiative", "Resistance", "SpellSaveDC", "WeaponEnchantment", "WeaponProperty",
      "UnlockSpell", "UnlockInterrupt", "ActionResource", "DamageBonus", "CharacterWeaponDamage", "WeaponDamage", "CriticalHit", "HiddenDuringCinematic",
      "ItemReturnToOwner", "CannotBeDisarmed", "ObjectSize", "ScaleMultiplier", "CarryCapacityMultiplier", "WeightCategory", "Weight"];
    var RB = ["Attack", "WeaponAttack", "MeleeWeaponAttack", "RangedWeaponAttack", "SpellAttack", "MeleeSpellAttack", "RangedSpellAttack"];
    var other = {}, conds = {};
    uncond.forEach(function (x) {
      if (SKIP.indexOf(x.name) >= 0) return;
      if (x.name === "RollBonus" && x.args.length && RB.indexOf(x.args[0]) >= 0) return;
      if (x.h) other[x.h + " - " + x.src] = 1;
    });
    cond.forEach(function (x) { if (x.h) conds[x.h + " (" + (x.ch || "in some situations") + ") - " + x.src] = 1; });
    return { level: level, prof: profB, ab: ab, abBase: base, abF: abF, mods: M, hp: hp, ac: ac, init: ini, speed: spd, F: F_,
      attacks: attacks, nAtt: nAtt, nAttF: attF, spell: spell, res: res, cres: cres, other: Object.keys(other).sort(), conds: Object.keys(conds).sort(),
      feats: featNames, styles: styles, classes: clsOrder.map(function (c) { return [c, classes[c]]; }) };
  }
  var SHEETS = {};
  function levelFor(set) { return S.lvl === "12" ? DATA.level : (liveLevel(set) || DATA.actLevel[set.act] || DATA.level); }
  function sheetFor(c, set, opt) {
    opt = opt || {};
    var b = buildOf(c, set.b), level = opt.level || levelFor(set), items;
    if (opt.asListed) { items = {}; Object.keys(set.slots).forEach(function (sl) { items[sl] = { sid: set.slots[sl].sid }; }); }
    else items = viewOf(set).items;
    var key = set.id + "|" + level + "|" + DATA.slots.map(function (sl) { return (items[sl] || {}).sid || ""; }).join(",");
    if (!SHEETS[key]) SHEETS[key] = computeSheet(b.bi, items, level);
    return SHEETS[key];
  }

  // ---- tooltip registry: elements carry data-tip="<index>"; content built on demand
  var TIPS = [];
  function tip(fn) { TIPS.push(fn); return ' data-tip="' + (TIPS.length - 1) + '"'; }

  // ================================================================= header, playthrough bar, rail, list
  function renderActs() {
    var el = document.getElementById("acts"), h = '<span class="lab" aria-hidden="true">Act</span>';
    [1, 2, 3].forEach(function (a) {
      h += '<button type="button" class="act-btn" data-act="' + a + '" aria-pressed="' + (S.act === a) + '" title="Act ' + ROMAN[a] + '" aria-label="Act ' + ROMAN[a] + '">' +
        (ui("num_" + a) ? uimg("num_" + a, "", "") : ROMAN[a]) + "</button>";
    });
    el.innerHTML = h;
  }
  var PLAY = [
    ["durge", "Dark Urge playthrough", [["any", "Not set"], ["yes", "Yes"], ["no", "No"]]],
    ["grove", "Grove fight", [["any", "Not decided"], ["tieflings", "Sided with the tieflings"], ["goblins", "Sided with the goblins"]]],
    ["night", "Shadowheart and the Nightsong", [["any", "Not decided"], ["shar", "Nightsong killed (Shar)"], ["selune", "Nightsong spared (Selûne)"]]],
    ["isobel", "Isobel at Last Light", [["any", "Not decided"], ["alive", "Alive"], ["killed", "Killed"]]],
    ["crime", "Theft and killing neutrals", [["any", "Allowed"], ["no", "Avoid"]]]
  ];
  function activeFilters() { var n = 0; Object.keys(DEF_F).forEach(function (k) { if (F[k] !== DEF_F[k]) n++; }); return n; }
  function renderPlay() {
    var el = document.getElementById("play"), h = "";
    var nHid = 0, nSwap = 0;
    DATA.chars.forEach(function (c) { if (!charVisible(c)) return; allSets(c).forEach(function (s) { var v = viewOf(s); if (v.hidden) nHid++; nSwap += v.nSwap; }); });
    var act = activeFilters();
    var open = el.querySelector("details") ? el.querySelector("details").open : (store.get("playOpen") !== "0" && window.innerWidth > 560);
    var nOvr = LIVE ? Object.keys(OVR).length : 0;
    function optLabel(p, v) { var o = p[2].filter(function (x) { return x[0] === v; })[0]; return o ? o[1] : v; }
    var sum = LIVE ? "From your game: " + PLAY.filter(function (p) { return PLAY_KEYS.indexOf(p[0]) >= 0 && LIVE_PLAY[p[0]] && LIVE_PLAY[p[0]] !== "any"; })
        .map(function (p) { return p[0] === "durge" ? (LIVE_PLAY.durge === "yes" ? "Dark Urge run" : "not a Dark Urge run") : optLabel(p, LIVE_PLAY[p[0]]); }).join(" &middot; ") +
        (nOvr ? " &middot; " + nOvr + " changed by you" : "") + " &middot; " + nHid + " sets hidden &middot; " + nSwap + " items swapped"
      : (act ? act + " setting" + (act > 1 ? "s" : "") + " on &middot; " + nHid + " sets hidden &middot; " + nSwap + " items swapped" : "Tell the page what happened in your game: sets and items that no longer fit are hidden or swapped for their alternatives.");
    h += '<details class="playbox"' + (open ? " open" : "") + '><summary><span class="pt">My playthrough</span><span class="ps">' + sum +
      "</span></summary><div class=\"pgrid\">";
    PLAY.forEach(function (p) {
      var live = LIVE && PLAY_KEYS.indexOf(p[0]) >= 0;
      h += '<label class="pf' + (live && OVR[p[0]] == null ? " fromgame" : "") + '"><span>' + esc(p[1]) + '</span><select id="pf-' + p[0] + '" data-f="' + p[0] + '">' +
        (live ? '<option value="@game"' + (OVR[p[0]] == null ? " selected" : "") + ">From your game: " + esc(optLabel(p, LIVE_PLAY[p[0]] || "any")) + "</option>" : "") +
        p[2].map(function (o) { return '<option value="' + o[0] + '"' + ((live ? OVR[p[0]] === o[0] : F[p[0]] === o[0]) ? " selected" : "") + ">" + esc(live ? "Set by hand: " + o[1] : o[1]) + "</option>"; }).join("") + "</select></label>";
    });
    h += '<label class="pc"><input type="checkbox" id="pf-gone" data-f="gone"' + (F.gone ? " checked" : "") + '><span>Hide earlier-act items I don\'t have <small>(' + (LIVE ? "your party and camp chest count automatically" : 'tick "Have it" in the shopping list to keep one') + ')</small></span></label>';
    if (LIVE) h += '<p class="pc livenote">Contested items follow your real party: whoever gets more from an item and is in your party gets it; an exact tie with a party member is a shared pick.</p>';
    else h += '<label class="pc"><input type="checkbox" id="pf-party" data-f="party"' + (F.party ? " checked" : "") + '><span>Give contested items to the companion who gets more from them <small>(the sheet uses the alternatives)</small></span></label>';
    h += '<div class="pbtns"><button type="button" class="btn-pill sm" id="pfReset"' + (act || nOvr ? "" : " disabled") + '>' + (LIVE ? "Use my game for everything" : "Reset") + '</button></div></div></details>';
    el.innerHTML = h;
  }
  function face(c) {
    if (c.portrait) return img(c.portrait, "", "");
    return '<img class="bgicon" src="' + ui("bgicon_" + c.id) + '" alt="">';
  }
  function renderRail() {
    var h = "";
    DATA.chars.forEach(function (c) {
      if (!charVisible(c)) return;
      h += '<button type="button" class="who" data-char="' + c.id + '" aria-pressed="' + (c.id === S.char) + '"><span class="face">' + face(c) +
        '</span><span class="nm">' + esc(c.n) + "</span></button>";
    });
    if (!charVisible(charById("darkurge") || { id: "x" })) h += '<p class="railnote">The Dark Urge is hidden: not a Dark Urge playthrough.</p>';
    document.getElementById("rail").innerHTML = h;
  }
  function classIcons(b) {
    var h = "";
    (b.subs || []).forEach(function (s) { if (s.icon && UI["cls_" + s.icon]) h += uimg("cls_" + s.icon, "", s.n); });
    Object.keys(b.classes || {}).forEach(function (cl) {
      var covered = (b.subs || []).some(function (s) { return s.cls === cl && s.icon && UI["cls_" + s.icon]; });
      if (!covered && UI["cls_" + cl]) h += uimg("cls_" + cl, "", cl);
    });
    return h;
  }
  function originLabel(c, b) {
    if (LIVE && liveBuild(c) === b.id) return '<span class="bo main">Closest to your character in your game</span>' + originLabel0(c, b);
    return originLabel0(c, b);
  }
  function originLabel0(c, b) {
    if (b.id === c.main) return '<span class="bo main">Main build &middot; ' + (b.o === "campaign" ? "from a real Dark Urge playthrough" : "Build Advisor's build") + "</span>";
    return '<span class="bo">' + esc(b.o === "BuildAdvisor" ? "Build Advisor's build" : b.o === "campaign" ? "From a real Dark Urge playthrough" : "Community build") + "</span>";
  }
  function sourceChip(s) { return s.o === "research" ? '<span class="chip">Community build</span>' : '<span class="chip gen">Auto-picked' + (s.tl ? " &middot; " + esc(s.tl) : "") + "</span>"; }
  function renderList() {
    var c = curChar(), vs = visibleSets(c, S.act), sets = S.showHidden ? vs.vis.concat(vs.hid) : vs.vis.slice(), cur = curSet(), h = "";
    if (cur && sets.indexOf(cur) < 0 && cur.act === S.act) sets.push(cur);   // a deep-linked set that the filters hide stays listed
    var byB = {}, order = [];
    sets.forEach(function (s) { (byB[s.b] = byB[s.b] || []).push(s); if (order.indexOf(s.b) < 0) order.push(s.b); });
    h += '<div class="pickm"><label for="setPick">Set (' + sets.length + ')</label><select id="setPick">' + order.map(function (bid) {
      var b = buildOf(c, bid) || { n: bid };
      return '<optgroup label="' + esc(b.n) + '">' + byB[bid].map(function (s) {
        return '<option value="' + esc(s.id) + '"' + (cur && s.id === cur.id ? " selected" : "") + ">" + esc(s.n) + " - " + esc(rankOf(c, s)) + "</option>";
      }).join("") + "</optgroup>";
    }).join("") + "</select></div>";
    if (!vs.all.length) h += '<p class="note">No sets for ' + esc(c.n) + " in Act " + ROMAN[S.act] + ".</p>";
    else if (!sets.length) h += '<p class="note">Every set for ' + esc(c.n) + " in Act " + ROMAN[S.act] + " needs something your playthrough rules out.</p>";
    h += '<div class="sl-groups">';
    order.forEach(function (bid) {
      var b = buildOf(c, bid) || { id: bid, n: bid, classes: {} };
      h += '<div class="bgroup"><div class="bhead"><span class="icons">' + classIcons(b) + '</span><span class="t"><span class="bn">' + esc(b.n) + "</span>" + originLabel(c, b) + "</span></div>";
      byB[bid].forEach(function (s) {
        var v = viewOf(s), rl = rankOf(c, s);
        var pressed = S.cmp ? (s.id === S.cmpA || s.id === S.cmpB) : (cur && s.id === cur.id);
        var ab = S.cmp ? (s.id === S.cmpA ? "A" : s.id === S.cmpB ? "B" : "") : "";
        h += '<div class="srow-wrap' + (v.hidden ? " is-hidden" : "") + (S.cmp ? " has-ab" : "") + '"><button type="button" class="srow" data-set="' + esc(s.id) + '" aria-pressed="' + pressed + '"' + (ab ? ' data-cmp="' + ab + '"' : "") + '>' +
          '<span class="sn">' + (ab ? '<span class="abtag t' + ab + '" aria-label="Set ' + ab + '">' + ab + "</span>" : "") + esc(s.n) + "</span>" +
          '<span class="flags">' + (s.cap && (s.cap.model || s.cap.sheet) ? uimg("ico_camera", "", "has an in-game capture") : "") + "</span>" +
          '<span class="meta"><span class="chip' + (rl === "Main pick" ? " top" : "") + '">' + esc(rl) + "</span>" + sourceChip(s) +
          '<span class="chip ready" title="Items you can get with your playthrough settings">' + v.ready + "/" + v.total + " available</span>" +
          pills(v.tags, true) + "</span></button>" +
          (S.cmp ? '<span class="abbtns"><button type="button" class="abb" data-cmpset="A" data-sid="' + esc(s.id) + '" aria-label="Compare as set A: ' + esc(s.n) + '">A</button><button type="button" class="abb b" data-cmpset="B" data-sid="' + esc(s.id) + '" aria-label="Compare as set B: ' + esc(s.n) + '">B</button></span>' : "") +
          (v.hidden ? '<span class="hidwhy">Hidden: ' + esc(v.hidden) + "</span>" : "") + "</div>";
      });
      h += "</div>";
    });
    h += "</div>";
    if (vs.hid.length) h += '<button type="button" class="btn-pill sm showhid" id="showHid" aria-pressed="' + S.showHidden + '">' + (S.showHidden ? "Hide the " + vs.hid.length + " sets that don't fit" : "Show " + vs.hid.length + " hidden set" + (vs.hid.length > 1 ? "s" : "")) + "</button>";
    document.getElementById("setlist").innerHTML = h;
  }

  // ================================================================= paperdoll
  function emptyWhy(set, sl, r) {
    if (r && r.swap) return r.swap.why;
    var mh = set.slots.MainHand && itemOf(set.slots.MainHand.sid);
    if (sl === "OffHand" && mh && mh.wpn && (mh.wpn.props || []).indexOf("Twohanded") >= 0) return "the main-hand weapon is two-handed";
    var rh = set.slots.Ranged && itemOf(set.slots.Ranged.sid);
    if (sl === "RangedOff" && rh && rh.wpn && (rh.wpn.props || []).indexOf("Twohanded") >= 0) return "the ranged weapon is two-handed";
    return "nothing recommended for this slot";
  }
  function slotHTML(set, sl, opts) {
    var v = (opts && opts.view) || viewOf(set), r = v.slots[sl], cls = "slot";
    if (opts && opts.diff && opts.diff[sl]) cls += " diff";
    if (!r || !r.sid) {
      var why = emptyWhy(set, sl, r), lab = SLOT_LABEL[sl] + ": empty (" + why + ")";
      return '<button type="button" class="' + cls + ' empty' + (r && r.swap ? " swapped" : "") + '" style="--slotbg:var(--ui-eq_' + sl + ')" aria-label="' + esc(lab) + '"' +
        tip(emptyTip(set, sl, r, why)) + ">" + (r && r.swap ? '<span class="bdg s" aria-hidden="true">&#8644;</span>' : "") + "</button>";
    }
    var it = itemOf(r.sid), rr = rk(it.r), t = slotTags(set, r);
    var back = ui("rf_" + rr + "_back"), front = ui("rf_" + rr + "_front"), bd = "", say = [];
    var severe = t.story || t.crime;
    if (severe || t.miss || (r.sid === r.e.sid && r.e.warn)) {
      bd += '<span class="bdg w" aria-hidden="true">' + uimg(severe ? "ico_warn" : "ico_warnsoft", "", "") + "</span>";
      say.push(severe ? (t.story ? "Story lock" : "Theft or kill") : t.miss ? "Missable" : "Tip");
    }
    if (t.own) { bd += '<span class="bdg o" aria-hidden="true">&#8635;</span>'; say.push("From Act " + ROMAN[r.e.act] + ", only if you kept it"); }
    if (t.party) { bd += '<span class="bdg p" aria-hidden="true">' + uimg("ico_party", "", "") + "</span>"; say.push(capf(names(r.e.owner)) + " gets more from it"); }
    if (r.swap) { bd += '<span class="bdg s" aria-hidden="true">&#8644;</span>'; say.push((r.swap.kind === "oa" || r.swap.kind === "ca" ? "Better option, replaces " : "Swapped in for ") + itemOf(r.e.sid).n); }
    else if ((r.e.oa && ITEMS[r.e.oa]) || (r.e.ca && ITEMS[r.e.ca])) say.push(r.e.oa ? "An earlier-act item you may own beats it" : "A Dark Urge item beats it");
    if (HAVE[r.sid]) say.push("You have it");
    var label = SLOT_LABEL[sl] + ": " + it.n + (say.length ? ". " + say.join(". ") + "." : "");
    return '<button type="button" class="' + cls + (HAVE[r.sid] ? " have" : "") + '" style="--slotbg:var(--ui-eq_' + sl + ')" aria-label="' + esc(label) + '"' +
      tip(function () { return itemTip(r.sid, set, sl, r); }) + ">" +
      (back ? '<span class="rb" style="background-image:url(' + back + ')"></span>' : "") +
      (it.icon ? img(it.icon, "ic", "") : "") +
      (front ? '<span class="rf" style="background-image:url(' + front + ')"></span>' : "") + bd + "</button>";
  }
  function captureHTML(c, set, kind) {
    var key = set.cap && set.cap[kind];
    var file = "shots/sets/" + c.id + "_" + set.act + "_" + set.id + "_" + kind + ".png";
    var inner = key ? img(key, "", (kind === "model" ? "In-game capture of " : "In-game character sheet of ") + c.n + " wearing " + set.n)
      : (c.portrait ? img(c.portrait, "ghost", "") : uimg("bgicon_" + c.id, "ghost", ""));
    return '<figure class="capture' + (kind === "sheet" ? " sheetcap" : "") + (key ? " has" : "") + '" data-capture="' + kind + '" data-set="' + esc(set.id) + '" data-capture-file="' + esc(file) + '">' +
      '<div class="media">' + inner + "</div>" + "" + "</figure>";
  }
  function dollHTML(c, set, opts) {
    var L = ["Helmet", "Cloak", "Breast", "Gloves", "Boots"], R = ["Amulet", "Ring1", "Ring2", "Elixir"];
    return '<div class="doll"><div class="col">' + L.map(function (s) { return slotHTML(set, s, opts); }).join("") + "</div>" +
      captureHTML(c, set, "model") +
      '<div class="col">' + R.map(function (s) { return slotHTML(set, s, opts); }).join("") + "</div>" +
      '<div class="weap"><div class="pair"><span class="lbl">Melee</span>' + slotHTML(set, "MainHand", opts) + slotHTML(set, "OffHand", opts) + "</div>" +
      '<div class="pair">' + slotHTML(set, "Ranged", opts) + slotHTML(set, "RangedOff", opts) + '<span class="lbl">Ranged</span></div></div></div>';
  }

  // ================================================================= character sheet view
  function formulaTip(title, total, lines, note) {
    return function () {
      return '<div class="tt r-Common"><div class="tt-name">' + esc(title) + '</div><div class="tt-sub">How it is computed</div>' +
        '<div class="tt-sep"></div><ul class="tt-f">' + lines.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") +
        (total != null ? '<li class="res">= ' + esc(total) + "</li>" : "") + "</ul>" + (note ? '<p class="note">' + esc(note) + "</p>" : "") + "</div>";
    };
  }
  function grantedEffects(items) {
    var acts = [], pas = [], seen = {};
    DATA.slots.forEach(function (sl) {
      var x = items[sl], it = x && ITEMS[x.sid]; if (!it || !it.eff) return;
      it.eff.forEach(function (f) {
        if (!f.n) return;
        var key = (f.k === "spell" ? "a|" : "p|") + f.n.toLowerCase(); if (seen[key]) return; seen[key] = 1;   // F2: one row per name
        if (f.k === "spell") acts.push({ f: f, it: it });
        else if (f.k === "passive" || f.k === "status") pas.push({ f: f, it: it });
      });
    });
    return { acts: acts, pas: pas };
  }
  function effectTip(f, it) {
    return function () {
      return '<div class="tt r-Common"><div class="tt-head"><div><div class="tt-name">' + esc(f.n || "Effect") + '</div><div class="tt-sub">' +
        (f.k === "spell" ? (f.wa ? "Weapon action" : "Action / spell") : f.k === "status" ? "Condition" : "Passive") + "</div></div>" +
        '<div class="tt-icon">' + (f.i ? img(f.i, "", "") : "") + '</div></div><div class="tt-sep"></div><p class="tt-p">' + esc(f.t) + "</p>" +
        '<div class="tt-la"><span class="y">From <span class="nm-' + rk(it.r) + '">' + esc(it.n) + "</span>" + (f.use ? " (when drunk)" : "") + "</span></div></div>";
    };
  }
  function lvlNote(set, sh) {
    if (S.lvl !== "12" && liveLevel(set)) return "Level " + sh.level + ": " + (CHAR_NAME[setChar(set)] || "this character") + "'s level in your game. The numbers follow this build's plan at that level (classes and ability scores of the plan, not your character's).";
    if (sh.level === DATA.level) return "End-game numbers (level " + sh.level + ")" + (set.act < 3 ? ". Your Act " + ROMAN[set.act] + " character will be lower; use them to compare sets." : ".");
    var bi = (buildOf(curChar(), set.b) || {}).bi || { feats: [] }, planned = bi.feats.some(function (f) { return f.lv; });
    return "Level " + sh.level + ", typical at the end of Act " + ROMAN[set.act] + ". " + (planned ? "Ability scores follow the build's level-12 plan minus later ability improvements" + (bi.planInferred ? " (a typical level plan for this community build)." : ".")
      : "Ability scores are the build's level-12 plan (no level-by-level plan known), so they can be 1-2 points high.");
  }
  function sheetHTML(c, set, compact) {
    var sh = sheetFor(c, set), b = buildOf(c, set.b) || { classes: {} }, wide = window.innerWidth > 560;
    var clsTxt = sh.classes.map(function (x) { var sub = (b.subs || []).filter(function (s) { return s.cls === x[0]; })[0]; return (sub ? sub.n + " " : "") + x[0] + " " + x[1]; }).join(" / ");
    var h = '<section class="panel sheet" aria-label="Character sheet"><div class="hdr">' + uimg("race_" + c.race, "", "") + classIcons(b) +
      '<span class="cl">' + esc(c.race) + " &middot; " + esc(clsTxt) + '</span><span class="lvsw" role="group" aria-label="Sheet level">' +
      '<button type="button" class="lvb" data-lvl="act" aria-pressed="' + (S.lvl === "act") + '">' + (liveLevel(set) ? "Your level (" + liveLevel(set) + ")" : "Act level (" + (DATA.actLevel[set.act] || 12) + ")") + '</button>' +
      '<button type="button" class="lvb" data-lvl="12" aria-pressed="' + (S.lvl === "12") + '">Level 12</button></span></div>' +
      '<p class="lvnote">' + esc(lvlNote(set, sh)) + "</p>";
    h += '<div class="abil">';
    ABS.forEach(function (a) {
      var v = sh.ab[a], up = v > sh.abBase[a];
      h += '<button type="button" class="hexb' + (up ? " up" : "") + '" aria-label="' + ABN[a] + " " + v + ", modifier " + sgn(sh.mods[a]) + (up ? ", raised by an item" : "") + '"' +
        tip(formulaTip(ABN[a] + " " + v, v + " (modifier " + sgn(sh.mods[a]) + ")", sh.abF[a])) +
        '><span class="ab">' + a + '</span><span class="hx"><span class="sc">' + v + '</span></span><span class="md">' + sgn(sh.mods[a]) + "</span></button>";
    });
    h += "</div>";
    h += '<div class="vitals">' +
      '<button type="button" class="vit ac" aria-label="Armour Class ' + sh.ac + '"' + tip(formulaTip("Armour Class", sh.ac, sh.F.ac, "Feats and fighting styles come from the build plan. Spells such as Mage Armour or Shield are not counted.")) + '><span class="shield"><span class="v">' + sh.ac + '</span></span><span class="k">Armour Class</span></button>' +
      '<button type="button" class="vit" aria-label="Hit Points ' + sh.hp + '"' + tip(formulaTip("Hit Points", sh.hp, sh.F.hp, "Game rule: full hit die at level 1, then half the die + 1 per level, plus CON each level.")) + ">" + uimg("ico_hp", "ik", "") + '<span class="v">' + sh.hp + '</span><span class="k">Hit Points</span></button>' +
      '<button type="button" class="vit" aria-label="Initiative ' + sgn(sh.init) + '"' + tip(formulaTip("Initiative", sgn(sh.init), sh.F.init)) + ">" + uimg("ico_init", "ik", "") + '<span class="v">' + sgn(sh.init) + '</span><span class="k">Initiative</span></button>' +
      '<button type="button" class="vit" aria-label="Speed ' + sh.speed + ' metres"' + tip(formulaTip("Movement Speed", sh.speed + " m", sh.F.speed)) + ">" + uimg("ico_speed", "ik", "") + '<span class="v">' + sh.speed + 'm</span><span class="k">Speed</span></button>' +
      '<button type="button" class="vit" aria-label="Proficiency bonus +' + sh.prof + '"' + tip(formulaTip("Proficiency Bonus", "+" + sh.prof, ["Character level " + sh.level + ": +" + sh.prof])) + ">" + uimg("ico_prof", "ik", "") + '<span class="v">+' + sh.prof + '</span><span class="k">Proficiency</span></button></div>';
    if (sh.attacks.length) {
      h += '<div class="sec"><h4>Weapon attacks &middot; ' + sh.nAtt + " per action</h4>";
      sh.attacks.forEach(function (a) {
        var it = itemOf(a.sid);
        h += '<button type="button" class="atk" aria-label="' + esc(a.n + ", " + SLOT_LABEL[a.slot] + ": attack " + sgn(a.hit) + ", damage " + a.dmg + ", average " + a.avg) + '"' + tip(formulaTip(a.n + " (" + SLOT_LABEL[a.slot] + ")", null,
          ["Attack roll " + sgn(a.hit) + ":"].concat(a.hitf.map(function (x) { return "  " + x; }), ["Damage " + a.dmg + " (average " + a.avg + "):"],
            a.dmgf.map(function (x) { return "  " + x; }), a.cond.length ? ["Only in some situations (not counted):"].concat(a.cond.map(function (x) { return "  " + x; })) : [],
            a.dice.length ? ["Dice bonuses (not counted in the number): " + a.dice.join(", ")] : [], ["Attacks per action: " + sh.nAtt + " - " + sh.nAttF]))) +
          ">" + img(it.icon, "", "") + '<span class="an"><span class="nm-' + rk(it.r) + '">' + esc(a.n) + "</span><small>" + esc(SLOT_LABEL[a.slot]) + "</small></span>" +
          '<span class="hit">' + sgn(a.hit) + '</span><span class="dm"><b>' + esc(a.dmg) + "</b>avg " + a.avg + "</span></button>";
      });
      h += "</div>";
    }
    if (sh.spell) {
      var sp = sh.spell, split = sp.atk !== sp.atkM;
      h += '<div class="sec"><h4>Spellcasting &middot; ' + esc(sp.cls) + " (" + sp.abil + ')</h4><div class="kv">' +
        '<button type="button" class="row-tip"' + tip(formulaTip("Spell Save DC", sp.dc, sp.dcf)) + '><span class="v">' + sp.dc + '</span><span class="k">Spell save DC</span></button>' +
        '<button type="button" class="row-tip"' + tip(formulaTip(split ? "Ranged spell attack" : "Spell attack", sgn(sp.atk), sp.atkf, split ? "Melee spell attacks: " + sgn(sp.atkM) + " (" + sp.atkMf.join(", ") + ")." : "Counts each item once, for ranged and melee spell attacks alike.")) + '><span class="v">' + sgn(sp.atk) + '</span><span class="k">Spell attack' + (split ? " (ranged; melee " + sgn(sp.atkM) + ")" : "") + "</span></button></div></div>";
    }
    h += '<div class="sec"><h4>Resistances</h4><div class="res">';
    if (!sh.res.length && !sh.cres.length) h += '<span class="resi none">none</span>';
    sh.res.forEach(function (r) {
      var key = r.l === "Immune" ? "res_immune" : "res_" + r.t;
      h += '<button type="button" class="resi"' + tip(formulaTip(r.t + " " + (r.l === "Immune" ? "immunity" : "resistance"), null, ["Source: " + r.src])) + ">" + uimg(key, "", "") + esc(r.t) + (r.l === "Immune" ? " (immune)" : "") + "</button>";
    });
    sh.cres.forEach(function (r) {
      h += '<button type="button" class="resi cond" aria-label="' + esc(r.t + " resistance, only " + r.cond) + '"' + tip(formulaTip(r.t + " resistance (only sometimes)", null, ["Source: " + r.src, "Only " + r.cond])) + ">" + uimg("res_" + r.t.split(",")[0].trim(), "", "") + esc(r.t) + " *</button>";
    });
    h += "</div></div>";
    if (!compact) {
      var g = grantedEffects(viewOf(set).items);
      if (g.acts.length) {
        h += '<details class="sec fold"' + (wide ? " open" : "") + '><summary><h4>Actions and spells from the items (' + g.acts.length + ")</h4></summary><div class=\"grants\">";
        g.acts.forEach(function (x) { h += '<button type="button" class="gr" aria-label="' + esc(x.f.n + " (from " + x.it.n + ")") + '"' + tip(effectTip(x.f, x.it)) + ">" + (x.f.i ? img(x.f.i, "", "") : '<span class="ph">&#10022;</span>') + "</button>"; });
        h += "</div></details>";
      }
      if (g.pas.length) {
        h += '<details class="sec fold"' + (wide ? " open" : "") + '><summary><h4>Passives from the items (' + g.pas.length + ")</h4></summary><ul class=\"pas\">";
        g.pas.forEach(function (x) { h += '<li><button type="button" class="pasb"' + tip(effectTip(x.f, x.it)) + "><b>" + esc(x.f.n) + "</b> " + esc(x.f.t) + " <i>" + esc(x.it.n) + "</i></button></li>"; });
        h += "</ul></details>";
      }
      if (sh.other.length || sh.conds.length) {
        h += '<details class="more"><summary>More effects (' + (sh.other.length + sh.conds.length) + ")</summary><ul>" +
          sh.other.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") +
          sh.conds.map(function (x) { return '<li class="c">' + esc(x) + "</li>"; }).join("") + "</ul></details>";
      }
      h += '<p class="note">Computed from the game files with the build\'s planned ability scores' +
        (sh.feats.length || sh.styles.length ? ", feats and fighting styles (" + esc(sh.feats.concat(sh.styles).join(", ")) + ")" : "") +
        ". Effects that only work in some situations are listed, not added. Hover or tap any number for its formula.</p>";
    }
    return h + "</section>";
  }

  // ================================================================= item tooltip (mirrors the game's; LootAdvisor advice first, F4)
  function wpnLine(w) {
    var dmg = w.dmg + (w.ench ? " + " + w.ench : "");
    return '<div class="tt-main">' + (w.die && ui(w.die) ? uimg(w.die) : "") + '<span class="big">' + esc(dmg) + '</span><span class="dt">' +
      (ui("dmg_" + w.dt) ? uimg("dmg_" + w.dt) : "") + esc(w.dt || "") + "</span></div>" +
      (w.extra && w.extra.length ? '<div class="tt-alt">+ ' + esc((w.extraT || w.extra).join(" + ")) + "</div>" : "") +
      (w.ver ? '<div class="tt-alt">Versatile: ' + esc(w.ver + (w.ench ? " + " + w.ench : "")) + " two-handed</div>" : "");
  }
  var PROP_ICON = { Finesse: "ico_finesse", Twohanded: "ico_hand", Versatile: "ico_hand", Light: "ico_wlight", Heavy: "ico_wheavy", Reach: "ico_reach",
    Thrown: "ico_throw", Dippable: "ico_dip", Ammunition: "ico_ammo", Magical: "ico_magic" };
  var PROP_LABEL = { Twohanded: "Two-Handed" };
  function itemName(sid) { var it = ITEMS[sid]; return it ? '<span class="nm-' + rk(it.r) + '">' + esc(it.n) + "</span>" : esc(sid); }
  function adviceHTML(sid, set, sl, r) {
    var e = r ? r.e : null, isOrig = !r || r.sid === r.e.sid, info = isOrig ? e : INFO[sid];
    var it = itemOf(sid), h = '<div class="tt-la" role="note"><span class="h">Loot Advisor &middot; ' + esc(SLOT_LABEL[sl] || sl) + " &middot; " + esc(set.n) + "</span>";
    if (r && r.swap) {
      h += '<span class="s">Swapped in for ' + itemName(r.e.sid) + ": " + esc(r.swap.why) + ".</span>";
    }
    if (isOrig && e && e.why) h += '<span class="y">Why: ' + esc(e.why) + "</span>";
    if (info && info.how) h += '<span class="y">How to get it: ' + esc(info.how) + (info !== e && info.act ? " (Act " + ROMAN[info.act] + ")" : "") + "</span>";
    else if (!isOrig) h += '<span class="y">No location notes for this alternative.</span>';
    if (isOrig && e) {
      if (e.own) h += '<span class="o">Act ' + ROMAN[e.act] + " item - no longer obtainable in Act " + ROMAN[set.act] + ". Have it? Use it." + (e.fb ? (e.fbE ? " Otherwise " + esc(e.fb) + "." : " Otherwise: " + itemName(e.fb) + ".") : "") + "</span>";
      (e.cond || []).forEach(function (cd) { h += '<span class="c">' + esc(cd.t) + "</span>"; });
      if (e.warn) h += '<span class="w">' + esc(e.warn) + "</span>";
      if (e.oa && ITEMS[e.oa]) h += '<span class="s">If you already have ' + itemName(e.oa) + ": use it instead" + (e.oaGain ? " (+" + esc(e.oaGain) + ")" : "") + ". Mark it \"Have it\" in the shopping list to switch.</span>";
      if (e.ca && ITEMS[e.ca]) h += '<span class="s">In a Dark Urge campaign: ' + itemName(e.ca) + ".</span>";
      var lc = LIVE && e.pa ? liveContest(set, e) : null;
      if (lc && lc.k === "shared") h += '<span class="o">Shared pick: ' + esc(names(lc.who)) + " is in your party and gets exactly as much from it. Decide who wears it.</span>";
      else if (lc && lc.k === "free") h += '<span class="y">' + (lc.who.length ? esc(capf(names(lc.who))) + " would get more from it, but is not in your party right now." : "Nobody else in your party needs it more.") + "</span>";
      else if (lc) h += '<span class="o">' + esc(capf(names(lc.who))) + " is in your party and gets more from it: use " + itemName(e.pa) + " here.</span>";
      else if (e.pa) h += '<span class="o">Party conflict: ' + esc(names(e.owner)) + " gets more from it. With " + esc(names(e.owner)) + " in your party, use " + itemName(e.pa) + " here instead. (The character sheet assumes " + esc(it.n) + "; switch on \"Give contested items\" in My playthrough to use the alternative.)</span>";
      else if (e.fb && !e.own) h += '<span class="o">Can\'t get it? ' + (e.fbE ? esc(e.fb) : "Use " + itemName(e.fb)) + ".</span>";
    } else if (info && info !== e) {
      (info.cond || []).forEach(function (cd) { h += '<span class="c">' + esc(cd.t) + "</span>"; });
      if (info.warn) h += '<span class="w">' + esc(info.warn) + "</span>";
    }
    if (it.la && it.la < 3 && it.la >= set.act) h += '<span class="y">Last chance: Act ' + ROMAN[it.la] + ".</span>";
    if (LIVE_HAVE[sid]) h += '<span class="ok">In your game: ' + esc(((LIVE.owned || {})[sid] || []).join(", ")) + ".</span>";
    else if (HAVE[sid]) h += '<span class="ok">You marked it "Have it".</span>';
    return h + "</div>";
  }
  function itemTip(sid, set, sl, r) {
    var it = itemOf(sid), rc = DATA.rarityColor[it.r] || "#E6DBC2";
    var h = '<div class="tt r-' + esc(it.r) + '" style="--rc:' + rc + '">';
    h += '<div class="tt-head"><div><div class="tt-name">' + esc(it.n) + '</div><div class="tt-sub">' + esc((it.r && it.r !== "Common" ? RAR[it.r] + " " : "") + (it.type || "")) + "</div></div>" +
      '<div class="tt-icon">' + (ui("rf_" + rk(it.r) + "_back") ? '<img src="' + ui("rf_" + rk(it.r) + "_back") + '" alt="">' : "") + img(it.icon, "", "") +
      (ui("rf_" + rk(it.r) + "_front") ? '<img src="' + ui("rf_" + rk(it.r) + "_front") + '" alt="">' : "") + "</div></div>";
    if (set) h += adviceHTML(sid, set, sl, r);
    if (it.wpn) h += wpnLine(it.wpn);
    if (it.arm) {
      var a = it.arm, acv = a.sh ? "+" + (a.ac || 2) : (a.ac != null ? (a.ac + (a.boost || 0)) : sgn(a.boost));
      h += '<div class="tt-main">' + uimg("ico_ac") + '<span class="big">' + esc(acv) + '</span><span class="dt">Armour Class' +
        (a.cat === "Medium" ? " (+ DEX max " + (a.cap != null ? a.cap : 2) + ")" : a.cat === "Light" ? " (+ DEX)" : "") + "</span></div>";
    }
    var props = [];
    if (it.wpn) {
      (it.wpn.props || []).forEach(function (p) { props.push((PROP_ICON[p] ? uimg(PROP_ICON[p]) : "") + esc(PROP_LABEL[p] || p)); });
      if (it.wpn.range) props.push(uimg("ico_range") + esc(it.wpn.range + (it.wpn.lrange ? "/" + it.wpn.lrange : "") + "m"));
      var pf = (it.wpn.prof || []).filter(function (p) { return !/Weapons$/.test(p); });
      if (pf.length) props.push(uimg("ico_prof") + esc(pf.map(splitCamel).join(", ")));
    }
    if (it.arm) {
      if (it.arm.cat) props.push(uimg("ico_type") + esc(it.arm.cat + " armour"));
      if (it.arm.stealth) props.push(uimg("ico_warngrey") + "Stealth disadvantage");
      if (it.arm.prof && it.arm.prof.length) props.push(uimg("ico_prof") + esc(it.arm.prof.join(", ").replace(/Armor/g, " Armour")));
    }
    if (props.length) h += '<div class="tt-props">' + props.map(function (p) { return "<span>" + p + "</span>"; }).join("") + "</div>";
    var boosts = [], pas = [], acts = [];
    (it.eff || []).forEach(function (f) { if (f.k === "spell") acts.push(f); else if (f.k === "boost") boosts.push(f); else pas.push(f); });
    if (boosts.length || pas.length) {
      h += '<div class="tt-sep"></div><ul class="tt-eff">';
      boosts.forEach(function (f) { h += '<li class="boost">' + esc(f.t) + "</li>"; });
      pas.forEach(function (f) {
        h += f.i ? '<li class="act">' + img(f.i, "", "") + "<span><b>" + esc(f.n || "") + "</b> " + esc(f.t) + "</span></li>"
          : "<li>" + (f.n ? "<b>" + esc(f.n) + "</b> " : "") + esc(f.t) + (f.h ? ' <span class="hand">(' + esc(f.h) + " hand)</span>" : "") + (f.use ? ' <span class="hand">(when drunk)</span>' : "") + "</li>";
      });
      h += "</ul>";
    }
    if (acts.length) {
      var wa = acts.filter(function (f) { return f.wa; }), sp = acts.filter(function (f) { return !f.wa; });
      [[wa, "Weapon actions"], [sp, "Grants"]].forEach(function (g) {
        if (!g[0].length) return;
        h += '<div class="tt-h">' + g[1] + '</div><ul class="tt-eff">';
        g[0].forEach(function (f) { h += '<li class="act">' + (f.i ? img(f.i, "", "") : "<span></span>") + "<span><b>" + esc(f.n) + "</b> " + esc(f.t) + "</span></li>"; });
        h += "</ul>";
      });
    }
    if (it.d) h += '<div class="tt-lore">' + uimg("ico_quote") + "<span>" + esc(it.d) + "</span></div>";
    h += '<div class="tt-foot">' + (it.w != null ? "<span>" + uimg(it.w >= 4 ? "ico_wheavy" : "ico_wlight") + esc(it.w) + " kg</span>" : "") +
      (it.v != null ? "<span>" + uimg("ico_coin") + esc(it.v) + "</span>" : "") + (it.req ? "<span>" + esc(it.req.join(", ")) + "</span>" : "") +
      (it.u ? '<span class="u">Unique</span>' : "") + "</div>";
    return h + "</div>";
  }
  function emptyTip(set, sl, r, why) {
    return function () {
      var h = '<div class="tt r-Common"><div class="tt-name">' + esc(SLOT_LABEL[sl]) + ': empty</div><div class="tt-sub">' + esc(why) + "</div>";
      if (r && r.swap) h += '<div class="tt-la"><span class="s">' + itemName(r.e.sid) + " is recommended here, but it " + esc(r.swap.why) + ".</span></div>";
      return h + "</div>";
    };
  }

  // ================================================================= set view
  function setHead(c, s) {
    var b = buildOf(c, s.b) || { n: s.b, classes: {} }, v = viewOf(s), rl = rankOf(c, s), nPa = v.tags.party;
    return '<section class="panel" aria-label="Set summary"><div class="sethead"><div class="crest">' + face(c) + "</div><div>" +
      "<h2>" + esc(s.n) + "</h2>" +
      '<div class="build">' + classIcons(b) + "<span>" + esc(b.n) + "</span></div>" +
      '<div class="chips"><span class="chip">Act ' + ROMAN[s.act] + '</span><span class="chip' + (rl === "Main pick" ? " top" : "") + '" title="Order on this page: main build first, then community builds, then auto-picked sets">' + esc(rl) + "</span>" +
      sourceChip(s) + (b.id === c.main ? '<span class="chip top">Main build</span>' : "") +
      '<span class="chip ready" title="Items you can get with your playthrough settings">' + v.ready + " of " + v.total + " items available</span>" + pills(v.tags, false) +
      '<button type="button" class="legend-btn" data-legend="1" aria-label="What the badges mean">?</button></div></div>' +
      (s.why ? '<p class="why">' + esc(s.why) + "</p>" : "") +
      (v.hidden ? '<p class="hidnote">' + uimg("ico_warn", "", "") + "This set doesn't fit your playthrough (" + esc(v.hidden) + "). It is shown because you asked for hidden sets.</p>" : "") +
      (!LIVE && (nPa || (F.party && v.nSwap)) ? '<p class="assume">' + (F.party ? "The sheet uses the party-friendly alternatives." : "Numbers assume the items as listed; " + nPa + " of them " + (nPa > 1 ? "are" : "is") + " better on another companion.") +
        ' <button type="button" class="btn-pill sm" id="partyBtn" aria-pressed="' + F.party + '">' + (F.party ? "Use the items as listed" : "Use party-friendly alternatives") + "</button></p>" : "") +
      "</div></section>";
  }
  function noteLines(set, r) {
    var out = [], e = r.e, orig = r.sid === e.sid, t = slotTags(set, r), info = orig ? e : INFO[r.sid];
    if (r.swap && r.swap.kind !== "oa" && r.swap.kind !== "ca") out.push(['s', "Instead of " + itemOf(e.sid).n + ": " + r.swap.why + "."]);
    if (info) {
      (info.cond || []).forEach(function (cd) { out.push([/^Lost if|get it first/.test(cd.t) ? "miss" : "story", cd.t]); });
      if (info.warn) out.push([t.crime ? "crime" : t.miss ? "miss" : "tip", info.warn]);
    }
    if (orig && e.own) out.push(["own", "Act " + ROMAN[e.act] + " item: only if you kept it." + (e.fb ? (e.fbE ? " Otherwise " + e.fb + "." : " Otherwise: " + itemOf(e.fb).n + ".") : "")]);
    if (r.swap && r.swap.kind === "oa") out.push(["up", "You marked " + itemOf(e.oa).n + " \"Have it\": it replaces " + itemOf(e.sid).n + " here" + (e.oaGain ? " (+" + e.oaGain + ")" : "") + "."]);
    else if (e.oa && ITEMS[e.oa]) out.push(["up", "If you already have " + itemOf(e.oa).n + " (Act " + ROMAN[(INFO[e.oa] || {}).act || 1] + "): use it instead" + (e.oaGain ? " (+" + e.oaGain + ")" : "") + ". Tick \"I have it\" to switch.", e.oa]);
    if (r.swap && r.swap.kind === "ca") out.push(["up", "Dark Urge playthrough: " + itemOf(e.ca).n + " replaces " + itemOf(e.sid).n + " here."]);
    else if (e.ca && ITEMS[e.ca]) out.push(["up", "In a Dark Urge campaign: " + itemOf(e.ca).n + " (set \"Dark Urge playthrough\" to Yes to use it)."]);
    var lc = LIVE && orig && e.pa ? liveContest(set, e) : null;
    if (lc && lc.k === "shared") out.push(["party", "Shared pick with " + names(lc.who) + " (in your party, gets exactly as much from it)."]);
    else if (lc && lc.k === "free") { if (lc.who.length) out.push(["tip", capf(names(lc.who)) + " would get more from it, but is not in your party right now."]); }
    else if (orig && e.pa) out.push(["party", capf(names(e.owner)) + " needs it more: use " + itemOf(e.pa).n + " here if " + names(e.owner) + " is with you."]);
    else if (orig && e.fb && !e.own && (e.cond.length || e.tags.length)) out.push(["alt", "Can't get it? " + (e.fbE ? e.fb : "Use " + itemOf(e.fb).n) + "."]);
    return out;
  }
  var NOTE_ICON = { story: "ico_warn", crime: "ico_warn", miss: "ico_warnsoft", tip: "ico_warngrey", own: "ico_warnguest", party: "ico_party", alt: "", s: "", up: "" };
  var NOTE_LAB = { story: "Story", crime: "Theft / kill", miss: "Missable", tip: "Tip", own: "Earlier act", party: "Party", alt: "Alternative", s: "Swapped", up: "Better option" };
  function shopHTML(c, s) {
    var v = viewOf(s), groups = {}, nGet = 0, nHave = 0;
    DATA.slots.forEach(function (sl) {
      var r = v.slots[sl]; if (!r || !r.sid) return;
      var orig = r.sid === r.e.sid, info = orig ? r.e : INFO[r.sid], t = slotTags(s, r);
      var g = orig && r.e.own ? [-1, "From earlier acts (only if you kept them)"] : t.miss ? [-2, "Missable - get these first"] : (info && info.reg) || [99, "Other places"];
      var k = g[0] + "|" + g[1]; (groups[k] = groups[k] || { o: g[0], n: g[1], rows: [] }).rows.push({ sl: sl, r: r, t: t, info: info });
      if (HAVE[r.sid]) nHave++; else nGet++;
    });
    var keys = Object.keys(groups).sort(function (a, b) { var A = groups[a], B = groups[b]; return (A.o === -1 ? 1000 : A.o) - (B.o === -1 ? 1000 : B.o) || (A.n < B.n ? -1 : 1); });
    var h = '<section class="panel shop" id="shop" aria-labelledby="shopH"><div class="ph"><h3 id="shopH">Shopping list</h3><span class="sub">' + nGet + " to get &middot; " + nHave + ' marked "Have it" &middot; grouped along the Act ' + ROMAN[s.act] + ' route, missable items first. Map coordinates as on the in-game map (X, Y).</span></div>';
    keys.forEach(function (k) {
      var g = groups[k];
      h += '<div class="sgrp' + (g.o === -2 ? " miss" : "") + '"><h4>' + (g.o === -2 ? '<span class="pill p-miss">Missable</span> ' : g.o === -1 ? "" : uimg("ico_chest", "gi", "")) + esc(g.n) + "</h4><ul class=\"shoplist\">";
      g.rows.sort(function (a, b) { return DATA.slots.indexOf(a.sl) - DATA.slots.indexOf(b.sl); });
      g.rows.forEach(function (row) {
        var r = row.r, it = itemOf(r.sid), have = !!HAVE[r.sid], id = "have-" + s.id.replace(/[^A-Za-z0-9_-]/g, "_") + "-" + row.sl;
        var notes = noteLines(s, r);
        var gHave = LIVE_HAVE[r.sid], gWho = gHave ? ((LIVE.owned || {})[r.sid] || []).join(", ") : "";
        h += '<li class="srow2' + (have ? " have" : "") + '"><label class="haveb' + (gHave ? " game" : "") + '" for="' + id + '"' + (gHave ? ' title="In your game: ' + esc(gWho) + '"' : "") + '><input type="checkbox" id="' + id + '" data-have="' + esc(r.sid) + '"' + (have ? " checked" : "") + (gHave ? " disabled" : "") + '><span>' + (gHave ? "In your game" : "Have it") + '</span></label>' +
          '<div class="si"><span class="slotname">' + esc(SLOT_LABEL[row.sl]) + (r.e.core && r.sid === r.e.sid ? ' &middot; <span title="Core item of the set">&#9670; core</span>' : "") + '</span><button type="button" class="itb"' + tip(function () { return itemTip(r.sid, s, row.sl, r); }) + ">" + img(it.icon, "", "") +
          '<span class="nm-' + rk(it.r) + '">' + esc(it.n) + "</span></button></div>" +
          '<div class="how">' + (row.info && row.info.how ? esc(row.info.how) : '<span class="muted">No location notes for this alternative; see the item tooltip.</span>') +
          (notes.length ? '<ul class="nl">' + notes.map(function (n) {
            var tick = n[2] ? ' <label class="haveb in" for="' + id + '-oa"><input type="checkbox" id="' + id + '-oa" data-have="' + esc(n[2]) + '"' + (HAVE[n[2]] ? " checked" : "") + "><span>I have " + esc(itemOf(n[2]).n) + "</span></label>" : "";
            return '<li class="n-' + n[0] + '">' + (NOTE_ICON[n[0]] ? uimg(NOTE_ICON[n[0]], "", "") : '<span class="ni"></span>') + '<span><b>' + NOTE_LAB[n[0]] + ":</b> " + esc(n[1]) + tick + "</span></li>"; }).join("") + "</ul>" : "") +
          "</div></li>";
      });
      h += "</ul></div>";
    });
    return h + "</section>";
  }
  function notesHTML(s) {
    if (!s.notes || !s.notes.length) return "";
    return '<details class="panel setnotes"><summary><h3>About this set</h3><span class="sub">' + s.notes.length + " note" + (s.notes.length > 1 ? "s" : "") + " from building it</span></summary><ul>" +
      s.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul></details>";
  }
  function renderSet() {
    TIPS = [];
    var c = curChar(), s = curSet(), m = document.getElementById("main");
    if (!s) { m.innerHTML = '<section class="panel"><p>No sets in this act.</p></section>'; return; }
    m.innerHTML = setHead(c, s) + shopHTML(c, s) +
      '<div class="equip" id="equip" tabindex="-1"><section class="panel" aria-labelledby="eqH"><div class="ph"><h3 id="eqH">Equipment</h3><span class="sub">' + (isTouch ? "tap" : "hover or click") + " an item for details</span></div>" + dollHTML(c, s) + "</section>" + sheetHTML(c, s) + "</div>" +
      notesHTML(s) +
      (s.cap && s.cap.sheet ? '<section class="panel"><div class="ph"><h3>In-game character sheet</h3><span class="sub">captured in the game</span></div>' + captureHTML(c, s, "sheet") + "</section>" : "");
  }

  // ================================================================= compare (F7)
  function bestAtk(sh, ranged) { return sh.attacks.filter(function (a) { return a.ranged === ranged; }).sort(function (x, y) { return y.avg - x.avg; })[0]; }
  function cmpRows(c, s) {
    var sh = sheetFor(c, s), v = viewOf(s), r = [];
    r.push(["Armour Class", sh.ac, 1], ["Hit Points", sh.hp, 1], ["Initiative", sh.init, 1, 1], ["Speed (m)", sh.speed, 1]);
    ABS.forEach(function (a) { r.push([ABN[a], sh.ab[a], 1]); });
    var me = bestAtk(sh, false), ra = bestAtk(sh, true);
    r.push(["Melee attack roll", me ? me.hit : null, 1, 1], ["Melee damage per hit (avg)", me ? me.avg : null, 1], ["Melee damage per action (avg)", me ? +(me.avg * sh.nAtt).toFixed(1) : null, 1]);
    r.push(["Ranged attack roll", ra ? ra.hit : null, 1, 1], ["Ranged damage per hit (avg)", ra ? ra.avg : null, 1], ["Ranged damage per action (avg)", ra ? +(ra.avg * sh.nAtt).toFixed(1) : null, 1]);
    r.push(["Spell save DC", sh.spell ? sh.spell.dc : null, 1], ["Spell attack", sh.spell ? sh.spell.atk : null, 1, 1]);
    r.push(["Resistances (damage types)", sh.res.length, 1]);
    r.push(["Items available", v.ready + "/" + v.total, 0, 0, v.ready], ["Story locks", v.tags.story, -1], ["Theft / kills", v.tags.crime, -1], ["Missable", v.tags.miss, -1],
      ["From earlier acts", v.tags.own, -1], ["Party conflicts", v.tags.party, -1]);
    return r;
  }
  function delta(a, b, dir) {
    if (a == null || b == null || typeof a !== "number" || typeof b !== "number" || a === b || !dir) return { t: a === b ? "same" : "", c: "same" };
    var d = +(b - a).toFixed(1), better = dir > 0 ? d > 0 : d < 0;
    return { t: (d > 0 ? "+" : "−") + Math.abs(d) + (better ? " ▲" : " ▼"), c: better ? "up" : "down", d: d };
  }
  function renderCompare() {
    TIPS = [];
    var c = curChar(), all = allSets(c);
    if (!S.cmpA || !setById(c, S.cmpA)) S.cmpA = (curSet() || all[0]).id;
    if (!S.cmpB || !setById(c, S.cmpB) || S.cmpB === S.cmpA) {
      var aSet = setById(c, S.cmpA), vis = visibleSets(c, aSet.act).vis;
      var o = vis.filter(function (x) { return x.id !== S.cmpA; })[0] || all.filter(function (x) { return x.id !== S.cmpA && x.act === aSet.act; })[0] || all.filter(function (x) { return x.id !== S.cmpA; })[0];
      S.cmpB = o ? o.id : S.cmpA;
    }
    var A = setById(c, S.cmpA), B = setById(c, S.cmpB), vA = viewOf(A), vB = viewOf(B);
    function opts(sel) {
      return [1, 2, 3].map(function (a) {
        return '<optgroup label="Act ' + ROMAN[a] + '">' + (c.sets[String(a)] || []).map(function (s) {
          return '<option value="' + esc(s.id) + '"' + (s.id === sel ? " selected" : "") + ">" + esc(s.n) + (viewOf(s).hidden ? " (doesn't fit your playthrough)" : "") + "</option>";
        }).join("") + "</optgroup>";
      }).join("");
    }
    var diff = {}; DATA.slots.forEach(function (sl) { var a = vA.items[sl], b = vB.items[sl]; if ((a && a.sid) !== (b && b.sid)) diff[sl] = 1; });
    var ra = cmpRows(c, A), rb = cmpRows(c, B), verdict = [];
    var t = '<div class="ctab-wrap"><table class="ctab"><caption class="sr">Set A against set B</caption><thead><tr><th scope="col">Stat</th><th scope="col" class="ca"><span class="abtag tA">A</span> ' + esc(A.n) +
      '</th><th scope="col" class="cb"><span class="abtag tB">B</span> ' + esc(B.n) + '</th><th scope="col">B vs A</th></tr></thead><tbody>';
    ra.forEach(function (row, i) {
      var other = rb[i], av = row[1], bv = other[1];
      if (av == null && bv == null) return;
      var fa = av == null ? "-" : row[3] ? sgn(av) : av, fb = bv == null ? "-" : row[3] ? sgn(bv) : bv;
      var d = row[4] != null ? delta(row[4], other[4], 1) : delta(av, bv, row[2]);
      if (row[0] === "Items available" && d.c !== "same") d.t = (d.d > 0 ? "+" : "−") + Math.abs(d.d) + (d.c === "up" ? " ▲" : " ▼");
      if (d.d && (row[0] === "Armour Class" || row[0] === "Hit Points" || /per action|Spell save|Story|Theft|Missable/.test(row[0]))) verdict.push((d.d > 0 ? "+" : "−") + Math.abs(d.d) + " " + row[0].replace(" (avg)", "").toLowerCase());
      t += '<tr class="' + (row[2] < 0 ? "dec" : "") + '"><th scope="row">' + esc(row[0]) + "</th><td>" + esc(fa) + "</td><td>" + esc(fb) + '</td><td class="' + d.c + '">' + esc(d.t || "") + "</td></tr>";
    });
    t += "</tbody></table></div>";
    var col = function (S_, tag, cls, id, v) {
      return '<section class="panel"><div class="ph"><h3><span class="abtag t' + tag + '">' + tag + "</span> " + esc(S_.n) + '</h3><span class="sub">Act ' + ROMAN[S_.act] + " &middot; " + esc((buildOf(c, S_.b) || {}).n || S_.b) + " &middot; " + esc(rankOf(c, S_)) + "</span></div>" +
        dollHTML(c, S_, { diff: diff, view: v }) + "</section>";
    };
    var cross = A.act !== B.act ? '<p class="hidnote">' + uimg("ico_warnsoft", "", "") + "Different acts: A is an Act " + ROMAN[A.act] + " set, B an Act " + ROMAN[B.act] + " set. Items and the sheet level differ for that reason too.</p>" : "";
    document.getElementById("main").innerHTML = '<div class="cmpbar" role="group" aria-label="Sets to compare"><label class="pick"><span class="abtag tA">A</span><select id="cmpA" aria-label="Set A">' + opts(A.id) + '</select></label>' +
      '<button type="button" class="btn-pill sm" id="cmpSwap" aria-label="Swap set A and set B">&#8644; Swap</button>' +
      '<label class="pick"><span class="abtag tB">B</span><select id="cmpB" aria-label="Set B">' + opts(B.id) + "</select></label></div>" + cross +
      '<section class="panel"><div class="ph"><h3>Side by side</h3><span class="sub">Last column: B against A. &#9650; green = B is better, &#9660; red = B is worse. For story locks, thefts and missables fewer is better. Slots that differ are outlined.</span></div>' +
      '<p class="verdict"><b>B against A:</b> ' + esc(verdict.length ? verdict.join(", ") : "no difference in the main numbers") + ".</p>" + t + "</section>" +
      '<div class="cmp">' + col(A, "A", "", "cmpA", vA) + col(B, "B", "b", "cmpB", vB) + '<div class="cmp-full cmp">' + sheetHTML(c, A, true) + sheetHTML(c, B, true) + "</div></div>";
  }

  // ================================================================= legend (F6)
  function legendHTML() {
    var row = function (ico, t, d) { return "<li><span class=\"lg-i\">" + ico + "</span><span><b>" + t + "</b> " + d + "</span></li>"; };
    return '<div class="legend-card" role="dialog" aria-modal="true" aria-labelledby="lgH" tabindex="-1"><button type="button" class="tt-close lg-close" aria-label="Close">&times;</button>' +
      '<h3 id="lgH">What the badges mean</h3><div class="lg-cols"><div><h4>On an equipment slot</h4><ul>' +
      row('<span class="bdg-demo">' + uimg("ico_warn") + "</span>", "Red triangle:", "needs a story choice, theft or killing a neutral.") +
      row('<span class="bdg-demo">' + uimg("ico_warnsoft") + "</span>", "Orange triangle:", "missable (get it before a later choice or the end of the act), or a tip.") +
      row('<span class="bdg-demo o">&#8635;</span>', "Earlier act:", "an item from an earlier act. Only if you kept it; the tooltip names the alternative.") +
      row('<span class="bdg-demo">' + uimg("ico_party") + "</span>", "Party conflict:", "another companion gets more from it. The tooltip names the alternative for this character.") +
      row('<span class="bdg-demo s">&#8644;</span>', "Swapped:", "your playthrough settings replaced the recommended item: with its alternative (or an empty slot) when it can't be had, with a Dark Urge item when \"Dark Urge playthrough\" is Yes, or with an earlier-act item you marked \"Have it\".") +
      row('<span class="bdg-demo dash"></span>', "Dashed outline (compare):", "the two sets use different items in this slot.") +
      "</ul></div><div><h4>On a set</h4><ul>" +
      row('<span class="chip top">Main pick</span>', "", "first set in this page's order: your main build, then community builds, then auto-picked sets. Not a judgement of your game. Alternatives 1 and 2 follow; the rest are options.") +
      row('<span class="chip">Community build</span>', "", "taken from a popular community build guide.") +
      row('<span class="chip gen">Auto-picked</span>', "", "Loot Advisor chose the highest-scoring item per slot for one goal (damage, defence...).") +
      row('<span class="chip ready">9/12 available</span>', "", "items you can still get with your playthrough settings.") +
      row('<span class="pill p-story">story</span>', "", "items that need a story choice.") +
      row('<span class="pill p-crime">crime</span>', "", "items that need theft or killing a neutral.") +
      row('<span class="pill p-miss">missable</span>', "", "items you can miss.") +
      row('<span class="pill p-own">earlier</span>', "", "items from an earlier act.") +
      row('<span class="pill p-party">party</span>', "", "items another companion gets more from.") +
      row("&#9670; core", "", "the item the set is built around.") +
      "</ul><h4>Colours</h4><ul>" +
      row('<span class="nm-uncommon">Uncommon</span> <span class="nm-rare">Rare</span> <span class="nm-veryrare">Very Rare</span> <span class="nm-legendary">Legendary</span>', "", "item rarity, as in the game.") +
      row('<span class="lg-up">17</span>', "", "a green ability score is raised by an item.") +
      row('<span class="lg-up">+3 &#9650;</span> <span class="lg-down">&minus;1 &#9660;</span>', "", "compare: B is better / worse than A.") +
      "</ul></div></div></div>";
  }
  var lastFocus = null;
  function openLegend() {
    var el = document.getElementById("legend");
    lastFocus = document.activeElement;
    el.innerHTML = legendHTML(); el.hidden = false;
    var card = el.querySelector(".legend-card"); if (card) card.focus();
  }
  function closeLegend() { var el = document.getElementById("legend"); if (el.hidden) return; el.hidden = true; el.innerHTML = ""; if (lastFocus && lastFocus.focus) lastFocus.focus(); }

  // ================================================================= footer
  function renderFoot() {
    var n = 0; DATA.chars.forEach(function (c) { n += allSets(c).length; });
    var d = DATA.generated.split(" ")[0].split("-"), mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+d[1] - 1];
    document.getElementById("foot").innerHTML = "<p>" + n + " sets for " + DATA.chars.length + " origin characters. Made by Loot Advisor from the game files on " + (+d[2]) + " " + mon + " " + d[0] +
      ". Icons, frames, fonts and item texts are the game's own (Baldur's Gate 3, Larian Studios), for private use.</p>" +
      "<p>Character sheets are computed for each build's plan at the act's typical level (or level " + DATA.level + "); effects that only work in some situations are listed, not added.</p>";
  }

  // ================================================================= deep links (F12): #<set id> or #cmp~A~B (only plain tokens survive in an artifact link)
  function readHash() {
    var h = decodeURIComponent((location.hash || "").replace(/^#/, ""));
    if (!h) return false;
    var m = /^cmp[~/](.+?)[~/](.+)$/.exec(h);
    if (m) { var a = findSet(m[1]), b = findSet(m[2]); if (a) { S.char = a.c.id; S.act = a.s.act; S.set = a.s.id; S.cmp = true; S.cmpA = a.s.id; S.cmpB = b && b.c === a.c ? b.s.id : null; return true; } }
    S.cmp = false;
    var parts = h.split("/");
    if (parts.length === 3 && charById(parts[0])) { var f = findSet(parts[2]); S.char = parts[0]; S.act = +parts[1] || S.act; if (f && f.c.id === parts[0]) { S.act = f.s.act; S.set = f.s.id; } return true; }
    var fs = findSet(h);
    if (fs) { S.char = fs.c.id; S.act = fs.s.act; S.set = fs.s.id; return true; }
    if (charById(h)) { S.char = h; return true; }
    return false;
  }
  function writeHash() {
    var tok = S.cmp ? "cmp~" + S.cmpA + "~" + S.cmpB : (S.set || S.char);
    try { if (("#" + tok) !== location.hash) history.replaceState(null, "", "#" + tok); } catch (e) {}
  }

  // ================================================================= events
  function render() {
    if (!charVisible(curChar())) { S.char = DATA.chars.filter(charVisible)[0].id; S.set = null; }
    renderActs(); renderPlay(); renderRail();
    curSet();
    renderList();
    var tg = document.getElementById("cmpToggle"); tg.setAttribute("aria-pressed", String(S.cmp)); tg.textContent = S.cmp ? "Back to one set" : "Compare two sets";
    if (S.cmp) renderCompare(); else renderSet();
    hideTip(true);
    if (S.set) store.set("set:" + S.char + ":" + S.act, S.set);
    store.set("char", S.char); store.set("act", S.act);
    writeHash();
  }
  function saveF() { store.set("filters", JSON.stringify(F)); }
  function scrollMain() {
    if (window.innerWidth < 860) document.getElementById("main").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
  }
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest("[data-act],[data-char],[data-set].srow,[data-cmpset],#cmpToggle,.tt-close,#pfReset,#partyBtn,#showHid,#cmpSwap,[data-lvl],[data-legend],#ttb");
    if (t) {
      if (t.classList.contains("lg-close")) { closeLegend(); return; }
      if (t.classList.contains("tt-close") || t.id === "ttb") { hideTip(true); return; }
      if (t.dataset.legend) { openLegend(); return; }
      if (t.id === "cmpToggle") { S.cmp = !S.cmp; if (S.cmp) { S.cmpA = (curSet() || {}).id; S.cmpB = null; } render(); return; }
      if (t.id === "pfReset") { F = Object.assign({}, DEF_F); OVR = {}; store.set("ovr", "{}"); liveF(); saveF(); render(); return; }
      if (t.id === "partyBtn") { F.party = !F.party; saveF(); render(); return; }
      if (t.id === "showHid") { S.showHidden = !S.showHidden; render(); return; }
      if (t.id === "cmpSwap") { var x = S.cmpA; S.cmpA = S.cmpB; S.cmpB = x; render(); return; }
      if (t.dataset.lvl) { S.lvl = t.dataset.lvl; store.set("lvl", S.lvl); render(); return; }
      if (t.dataset.cmpset) { if (t.dataset.cmpset === "A") { if (S.cmpB === t.dataset.sid) S.cmpB = S.cmpA; S.cmpA = t.dataset.sid; } else { if (S.cmpA === t.dataset.sid) S.cmpA = S.cmpB; S.cmpB = t.dataset.sid; } render(); return; }
      if (t.dataset.act) { S.act = +t.dataset.act; S.set = null; store.set("act", S.act); }
      else if (t.dataset.char) { S.char = t.dataset.char; S.set = null; S.cmpA = S.cmpB = null; store.set("char", S.char); }
      else if (t.dataset.set) {
        // compare: a list click fills B (A stays where it is); the A/B buttons pick a side explicitly
        if (S.cmp) { if (t.dataset.set === S.cmpA) return; S.cmpB = t.dataset.set; }
        else S.set = t.dataset.set;
      }
      render();
      if (t.dataset.set) scrollMain();
      return;
    }
    var tp = ev.target.closest("[data-tip]");
    if (tp && (isTouch || pinned !== tp)) { showTip(tp, true); ev.preventDefault(); return; }
    if (tp && pinned === tp) { hideTip(true); return; }
    if (!ev.target.closest(".tt-layer")) hideTip(true);
    if (ev.target.id === "legend") closeLegend();
  });
  document.addEventListener("change", function (ev) {
    var t = ev.target;
    if (t.id === "cmpA") { S.cmpA = t.value; if (S.cmpB === S.cmpA) S.cmpB = null; render(); }
    else if (t.id === "cmpB") { S.cmpB = t.value; render(); }
    else if (t.id === "setPick") { if (S.cmp) S.cmpB = t.value; else S.set = t.value; render(); }
    else if (t.dataset.f) {
      if (LIVE && PLAY_KEYS.indexOf(t.dataset.f) >= 0) { if (t.value === "@game") delete OVR[t.dataset.f]; else OVR[t.dataset.f] = t.value; store.set("ovr", JSON.stringify(OVR)); liveF(); }
      else F[t.dataset.f] = t.type === "checkbox" ? t.checked : t.value;
      saveF(); render(); var back = document.getElementById(t.id); if (back) back.focus();
    }
    else if (t.dataset.have) { if (t.checked) HAVE_M[t.dataset.have] = 1; else delete HAVE_M[t.dataset.have]; store.set("have", JSON.stringify(HAVE_M)); recomputeHave(); var id = t.id; render(); var b2 = document.getElementById(id); if (b2) b2.focus(); }
  });
  document.addEventListener("toggle", function (ev) { if (ev.target.classList && ev.target.classList.contains("playbox")) store.set("playOpen", ev.target.open ? "1" : "0"); }, true);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { if (!document.getElementById("legend").hidden) closeLegend(); else hideTip(true); }
  });

  // ---- tooltip: follows the hovered element on desktop (reachable with the mouse), bottom sheet on phones (F4, F13, F15)
  var layer = document.getElementById("tt"), backdrop = document.getElementById("ttb"), pinned = null, cur = null, hideTimer = null;
  var isTouch = window.matchMedia && window.matchMedia("(hover: none)").matches;
  function showTip(el, pin) {
    var fn = TIPS[+el.getAttribute("data-tip")]; if (!fn) return;
    clearTimeout(hideTimer);
    if (cur === el && !pin) return;
    if (cur && cur !== el) cur.removeAttribute("aria-describedby");
    cur = el; pinned = pin ? el : null;
    document.querySelectorAll(".slot.on").forEach(function (x) { x.classList.remove("on"); });
    if (el.classList.contains("slot")) el.classList.add("on");
    var narrow = window.innerWidth <= 560;
    layer.className = "tt-layer" + (pin ? " pinned" : "") + (narrow ? " sheetmode" : "") + (isTouch ? " touch" : "");
    layer.innerHTML = fn() + (pin || isTouch ? '<button type="button" class="tt-close" aria-label="Close details">&times;</button>' : "") +
      (!isTouch ? '<div class="tt-hint">' + (pin ? "Pinned &middot; Esc or click elsewhere to close" : "Click to pin &middot; Esc to close") + "</div>" : "");
    layer.hidden = false;
    el.setAttribute("aria-describedby", "tt");
    backdrop.hidden = !(narrow && pin);
    if (narrow) { layer.style.left = ""; layer.style.top = ""; return; }
    // beside the whole doll / sheet when there is room, so the mouse can reach the tooltip without covering the
    // neighbouring slots and numbers; otherwise beside the element itself
    var r = el.getBoundingClientRect(), w = layer.offsetWidth, hh = layer.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    var grp = el.closest(".doll, .sheet"), g = grp ? grp.getBoundingClientRect() : r, x;
    if (g.right + 8 + w <= vw - 8) x = g.right + 8;
    else if (g.left - w - 8 >= 8) x = g.left - w - 8;
    else { x = r.right + 8; if (x + w > vw - 8) x = r.left - w - 8; if (x < 8) x = Math.max(8, Math.min(vw - w - 8, r.left)); }
    var y = r.top - 10; if (y + hh > vh - 8) y = vh - hh - 8; if (y < 8) y = 8;
    layer.style.left = x + "px"; layer.style.top = y + "px";
  }
  function hideTip(force) {
    clearTimeout(hideTimer);
    if (pinned && !force) return;
    layer.hidden = true; backdrop.hidden = true;
    if (cur) cur.removeAttribute("aria-describedby");
    cur = null; pinned = null;
    document.querySelectorAll(".slot.on").forEach(function (x) { x.classList.remove("on"); });
  }
  function hideSoon() { clearTimeout(hideTimer); hideTimer = setTimeout(function () { hideTip(false); }, 250); }
  if (!isTouch) {
    document.addEventListener("mouseover", function (ev) {
      if (ev.target.closest(".tt-layer")) { clearTimeout(hideTimer); return; }
      var t = ev.target.closest("[data-tip]"); if (t && !pinned) showTip(t, false);
    });
    document.addEventListener("mouseout", function (ev) {
      if (pinned) return;
      var from = ev.target.closest("[data-tip],.tt-layer"); if (!from) return;
      if (ev.relatedTarget && (from.contains(ev.relatedTarget) || (ev.relatedTarget.closest && ev.relatedTarget.closest(".tt-layer")))) return;
      hideSoon();
    });
  }
  document.addEventListener("focusin", function (ev) {
    var t = ev.target.closest("[data-tip]");
    if (layer.contains(ev.target)) return;
    if (t && (!pinned || pinned !== t)) { if (pinned) hideTip(true); if (!isTouch) showTip(t, false); return; }
    if (cur && !t) hideTip(true);   // focus moved elsewhere: no stale tooltip (F13)
  });
  window.addEventListener("scroll", function () { if (!pinned || (isTouch && window.innerWidth > 560)) hideTip(!!pinned); }, { passive: true });
  window.addEventListener("resize", function () { hideTip(true); });

  // ---- hook for a future 3D model viewer: window.LootAdvisorSets.mountModel(fn(container, setId, charId))
  var mounters = [];
  function runMounters() {
    mounters.forEach(function (fn) {
      document.querySelectorAll('figure.capture[data-capture="model"]').forEach(function (f) { var m = f.querySelector(".media"); fn(m, f.dataset.set, S.char); f.classList.add("has"); });
    });
  }
  var render0 = render;
  render = function () { render0(); runMounters(); };
  window.LootAdvisorSets = {
    data: DATA,
    sheetFor: function (setId, level, asListed) { var f = findSet(setId); return f ? sheetFor(f.c, f.s, { level: level, asListed: asListed !== false }) : null; },
    filters: function () { return Object.assign({}, F); },
    mountModel: function (fn) { mounters.push(fn); runMounters(); },
    // local page only: the running game's state (written by the mod, passed in by the page loader)
    live: function (st) { applyLive(st); }
  };
  function applyLive(st) {
    var first = !LIVE;
    LIVE = st || null;
    if (!LIVE) { LIVE_HAVE = {}; recomputeHave(); render(); return; }
    LIVE.inParty = {}; LIVE.chars = {};
    (st.party || []).forEach(function (p) { if (!p.key) return; LIVE.chars[p.key] = p; if (p.inParty) LIVE.inParty[p.key] = true; });
    LIVE_HAVE = {};
    Object.keys(st.owned || {}).forEach(function (sid) { if (ITEMS[sid]) LIVE_HAVE[sid] = 1; });
    recomputeHave();
    LIVE_PLAY = playFromGame(st); liveF();
    var sel = st.selected && st.selected.key, moved = false;
    if (sel && sel !== liveSel && charById(sel) && charVisible(charById(sel))) { S.char = sel; S.set = null; S.cmp = false; moved = true; }
    if (sel) liveSel = sel;
    if (st.act && (st.act !== liveAct || moved || first)) { if (st.act !== S.act) { S.act = st.act; S.set = null; } liveAct = st.act; }
    if (moved && S.act) {
      // open the best set of the build that matches the character in the game
      var cc = charById(sel), lb = liveBuild(cc), vs = visibleSets(cc, S.act).vis.filter(function (s) { return s.b === lb; });
      if (vs[0]) S.set = vs[0].id;
    }
    render();
  }

  readHash();
  if (!charById(S.char)) S.char = DATA.chars[0].id;
  render(); renderFoot();
  var tgl = document.getElementById("cmpToggle"); tgl.disabled = false; tgl.removeAttribute("aria-disabled");
  window.addEventListener("hashchange", function () { if (readHash()) render(); });
})();
