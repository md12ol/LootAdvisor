"""Build the SHIPPABLE LootAdvisor Sets page: the same page as the online copy
(tools/build_sets_artifact.py + tools/sets_artifact/, all UX fixes), but with NO game art and NO game text inside.

    python tools/build_sets_ship.py            # -> LootAdvisor/Mods/LootAdvisor/Page/Sets.html + ShipManifest.lua
    python tools/build_sets_ship.py --check    # also print the leak report (game text left in the page)
    python tools/build_sets_ship.py --release [DIR]   # also write DIR/Page/Sets.html (player package copy)

What ships (our own data): set lists, scores, ids, our why / how-to texts, conditions, the sheet rules, the page code,
and a MANIFEST of game files (paths only) plus loca handles. What does NOT ship: icons, frames, portraits, UI art, the
game font, item names / descriptions / effect texts. Those are built on the player's own machine by the mod:
  - Shared/ShipManifest.lua (generated here) lists the game texture/font paths and the loca handles;
  - the mod reads them from the player's BG3 install (Ext.IO.LoadFile(path, "data"), Ext.Loca) and writes
    LootAdvisor_art_*.js / LootAdvisor_text.js next to Sets.html in the Script Extender folder;
  - the page (tools/sets_ship/ship.js) decodes the DDS textures in the browser (tools/sets_ship/dds.js), resolves the
    text tokens and polls LootAdvisor_state.js for the live game state.

Game text in the page data is replaced by tokens "\\x01<id>\\x02"; DATA.T[id] = [loca handle, [param texts]] (the
param texts are the values our pipeline put into the [1], [2] placeholders: numbers, dice, damage types).
"""
import argparse
import glob
import hashlib
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "sets_artifact"))
import build_sets_artifact as B  # noqa: E402

ROOT = B.ROOT
REPO = B.REPO
MOD = os.path.join(REPO, "LootAdvisor", "Mods", "LootAdvisor")
PAGE_DIR = os.path.join(MOD, "Page")
MANIFEST_LUA = os.path.join(MOD, "ScriptExtender", "Lua", "Shared", "ShipManifest.lua")
SHIP_SRC = os.path.join(HERE, "sets_ship")
CACHE = os.path.join(ROOT, "data", "cache")


# ------------------------------------------------------------------------------------------------ art manifest
def dds_dims(data):
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    h, w = struct.unpack_from("<II", data, 12)
    return w, h


class ShipAssets(B.Assets):
    """Records WHICH game file each image key comes from (and the display box) instead of embedding it.
    Picks the smallest variant of a texture that still covers the box: controller icons (144 px) for item / skill
    icons, AssetsLowRes (half size) for UI art with a box. The page decodes and scales them in the browser."""

    def __init__(self):
        super().__init__()
        self.man = {}        # key -> {"p": path, "b": [w, h] | None, "uv": [u1, v1, u2, v2] | None}
        self.fonts = {}
        self._dims = {}

    def dims(self, pakname, path):
        k = (pakname, path)
        if k not in self._dims:
            try:
                p = self.pak(pakname)
                e = p.by_name.get(path)
                self._dims[k] = dds_dims(p.read(e)[:148]) if e else None
            except OSError:
                self._dims[k] = None
        return self._dims[k]

    def _rec(self, key, pakname, path, size, uv=None):
        self.man[key] = {"p": path, "b": list(size) if size else None, "uv": uv, "pak": pakname}
        self.uris[key] = ""
        return key

    def _smallest(self, pakname, paths, size):
        """paths[0] = the full-size texture. With a box, the smallest existing variant that still covers what the
        full-size texture would be shrunk to (no visible loss); else paths[0]."""
        found = [(p, self.dims(pakname, p)) for p in paths if self.has(pakname, p)]
        if not found:
            return None
        if size and found[0][1]:
            w, h = found[0][1]
            f = min(1.0, size[0] / w, size[1] / h)
            tw, th = int(w * f), int(h * f)
            ok = [(d[0] * d[1], p) for p, d in found if d and d[0] >= tw and d[1] >= th]
            if ok:
                return min(ok)[1]
        return found[0][0]

    def game(self, key, path, size=None, pakname="Game.pak", **kw):
        if key in self.man:
            return key
        cands = [path]
        if size and "/GUI/Assets/" in path:
            cands.append(path.replace("/GUI/Assets/", "/GUI/AssetsLowRes/"))
        best = self._smallest(pakname, cands, size)
        if not best:
            self.missing.append(path)
            return None
        return self._rec(key, pakname, best, size)

    def icon(self, name, kind="item", size=96):
        if not name:
            return None
        key = "%s:%s:%d" % (kind, name, size)
        if key in self.man:
            return key
        G = "Public/Game/GUI/Assets/"
        if kind == "item":
            groups = [[G + "Tooltips/ItemIcons/%s.DDS" % name, G + "ControllerUIIcons/items_png/%s.DDS" % name]]
        else:
            groups = [[G + "Tooltips/Icons/%s.DDS" % name, G + "ControllerUIIcons/skills_png/%s.DDS" % name],
                      [G + "Tooltips/ItemIcons/%s.DDS" % name, G + "ControllerUIIcons/items_png/%s.DDS" % name]]
        for grp in groups:
            best = self._smallest("Game.pak", grp, (size, size))
            if best:
                return self._rec(key, "Game.pak", best, (size, size))
        hit = self._atlas_index().get(name)
        if hit:
            tex, uv = hit
            for pakname in ("Icons.pak", "Shared.pak", "GustavX.pak", "Gustav.pak"):
                if self.has(pakname, tex):
                    return self._rec(key, pakname, tex, (size, size), uv)
        self.missing.append(key)
        return None

    def font(self, path):
        if not self.has("Game.pak", path):
            self.missing.append(path)
            return None
        return path


def ship_portrait(A, char):
    tag = {"astarion": "Astarion", "gale": "Gale", "karlach": "Karlach", "laezel": "Laezel",
           "shadowheart": "Shadowheart", "wyll": "Wyll"}.get(char)
    if not tag:
        return None
    try:
        p = A.pak("Gustav_Textures.pak")
    except OSError:
        return None
    names = sorted((n for n in p.by_name if "/GUI/Assets/Portraits/" in n and "(Icon_Origin_%s)" % tag in n),
                   key=lambda n: (0 if n.startswith("Mods/Gustav/") else 1, n))
    if not names:
        return None
    return A._rec("portrait:" + char, "Gustav_Textures.pak", names[0], (152, 152))


# ------------------------------------------------------------------------------------------------ text tokens
def strip_markup(t):
    t = re.sub(r"<br\s*/?>", " ", t or "")
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def handle_of(v):
    if isinstance(v, dict):
        return v.get("handle")
    if isinstance(v, str) and v.startswith("h"):
        return v.split(";")[0]
    return None


class TextTable:
    """Finds the game texts (loca strings) inside the page data and replaces them with tokens."""

    def __init__(self, D):
        self.D = D
        self.loca = B.load_json(os.path.join(CACHE, "loca_english.json"), {})
        self.tpl = {}
        for f in glob.glob(os.path.join(CACHE, "roottemplates_*.json")):
            for t in B.load_json(f, []) or []:
                if t.get("MapKey"):
                    self.tpl[t["MapKey"]] = t
        self.cands = {}       # handle -> kind ("name" | "desc")
        self.T, self.Tidx = [], {}

    def add(self, h, kind):
        if h and h in self.loca and self.loca[h] and h not in self.cands:
            self.cands[h] = kind

    def add_stats(self, sid, seen=None, depth=0):
        seen = seen if seen is not None else set()
        if not sid or sid in seen or depth > 3:
            return
        seen.add(sid)
        st = self.D.stats.get(sid) or {}
        self.add(handle_of(st.get("DisplayName")), "name")
        self.add(handle_of(st.get("Description")), "desc")
        for k in ("Passives", "PassivesOnEquip", "StatusOnEquip"):
            for x in B.split_top(st.get(k) or ""):
                self.add_stats(x.strip(), seen, depth + 1)
        # every status / spell / passive the entry refers to (boosts, spell properties, functors, tooltips)
        for k, v in st.items():
            if not isinstance(v, str) or k in ("DisplayName", "Description", "Icon"):
                continue
            for m in re.finditer(r"\b(?:UnlockSpell|UnlockInterrupt|ApplyStatus|ApplyEquipmentStatus|SetStatusDuration)"
                                 r"\((?:\w+,\s*)?([A-Z][A-Za-z0-9_]+)", v):
                self.add_stats(m.group(1), seen, depth + 1)

    def collect(self, items):
        for sid in items:
            rec = self.D.items.get(sid) or {}
            for mk in rec.get("templates") or []:
                t = self.tpl.get(mk) or {}
                inh = t.get("inherited") or {}
                self.add(handle_of(t.get("DisplayName") or inh.get("DisplayName")), "name")
                self.add(handle_of(t.get("Description") or inh.get("Description")), "desc")
            self.add_stats(sid)
            for e in rec.get("effects") or []:
                self.add_stats(e.get("id"))
                for p in e.get("passives") or []:
                    self.add_stats(p.get("id"))

    def add_item_names(self):
        """names of ALL items (our how-to texts mention items that are not on the page), multi-word ones only"""
        for t in self.tpl.values():
            inh = t.get("inherited") or {}
            h = handle_of(t.get("DisplayName") or inh.get("DisplayName"))
            txt = strip_markup(self.loca.get(h) or "")
            if h and len(txt) >= 12 and " " in txt and h not in self.cands:
                self.cands[h] = "name"

    def token(self, h, params):
        k = (h, tuple(params))
        if k not in self.Tidx:
            self.Tidx[k] = len(self.T)
            self.T.append([h, list(params)])
        return "\x01%s\x02" % format(self.Tidx[k], "x")

    def patterns(self, kinds, min_len):
        out = []
        for h, kind in self.cands.items():
            if kind not in kinds:
                continue
            txt = strip_markup(self.loca[h])
            parts = re.split(r"\[(\d+)\]", txt)
            lits = parts[0::2]
            litlen = sum(len(x) for x in lits)
            if litlen < min_len:
                continue
            if txt.startswith("%%%") or not re.search(r"[A-Za-z]", txt):
                continue
            rx = ""
            for i, p in enumerate(parts):
                if i % 2 == 0:
                    # playertext turns "turn(s)" / "target(s)" into plurals - accept both
                    rx += re.escape(p).replace(r"\(s\)", r"(?:\(s\)|s)")
                elif i == len(parts) - 2 and parts[-1] == "":
                    rx += r"(?P<p%d_%d>.{1,80}?)(?=$|[.;,]\s|\s\[|\n)" % (int(p), i)
                else:
                    rx += "(?P<p%d_%d>.{1,80}?)" % (int(p), i)
            # whole words only for names (no "Dagger" inside "Daggerfall"); placeholders need a following literal
            rx = (r"(?<![\w])" if txt[:1].isalnum() else "") + rx + (r"(?![\w])" if txt[-1:].isalnum() else "")
            longest = max((x for lit in lits for x in lit.split("(s)")), key=len)
            out.append((len(txt), h, re.compile(rx), longest, [int(p) for p in parts[1::2]]))
        out.sort(key=lambda x: -x[0])
        return out

    def apply(self, s, pats):
        for _, h, rx, longest, idxs in pats:
            if longest not in s:
                continue

            def sub(m, h=h, idxs=idxs):
                gd = m.groupdict()
                params = {}
                for k, v in gd.items():
                    params[int(k[1:].split("_")[0])] = v
                plist = [params.get(i, "") for i in range(1, (max(idxs) if idxs else 0) + 1)]
                return self.token(h, plist)
            s = rx.sub(sub, s)
        return s


TEXT_KEYS = {"n", "d", "t", "why", "how", "warn", "fb", "about", "note", "notes", "type", "extraT", "s"}
ID_RE = re.compile(r"^[A-Za-z0-9_:.\-|]+$")


def tokenize(payload, TT, check=False):
    """Replace game text in the page data. Effect / item fields: every candidate; our own texts: item names and
    long descriptions only (no short spell or passive names inside our sentences)."""
    p_all = TT.patterns({"name", "desc"}, 3)
    p_free = [p for p in p_all if TT.cands[p[1]] == "name" or p[0] >= 40]
    n_tok = [0]

    def walk(o, key=None, scope="free"):
        if isinstance(o, dict):
            for k in list(o.keys()):
                sc = scope
                if k in ("eff", "items"):
                    sc = "game"
                o[k] = walk(o[k], k, sc)
            return o
        if isinstance(o, list):
            return [walk(x, key, scope) for x in o]
        if isinstance(o, str):
            if not o or (ID_RE.match(o) and key not in ("n", "d", "t")):
                return o
            if key in ("icon", "i", "sid", "id", "b", "o", "pa", "oa", "ca", "c", "r", "rarity"):
                return o
            out = TT.apply(o, p_all if scope == "game" and key in ("n", "d", "t") else p_free)
            if out != o:
                n_tok[0] += 1
            return out
        return o

    # items (game text fields) first, then everything else
    payload["items"] = {sid: walk(v, None, "game") for sid, v in payload["items"].items()}
    for k in list(payload.keys()):
        if k not in ("items", "ui", "rules", "rarityColor", "slots", "actLevel"):
            payload[k] = walk(payload[k], k, "free")
    return n_tok[0]


def tokenize_with(payload, TT, pats):
    n = [0]

    def walk(o, key=None):
        if isinstance(o, dict):
            for k in list(o.keys()):
                if k in ("ui", "rules", "rarityColor", "slots", "actLevel", "art", "artPaths", "fonts", "T"):
                    continue
                o[k] = walk(o[k], k)
            return o
        if isinstance(o, list):
            return [walk(x, key) for x in o]
        if isinstance(o, str) and o and not (ID_RE.match(o) and key not in ("n", "d", "t")):
            if key in ("icon", "i", "sid", "id", "b", "o", "pa", "oa", "ca", "c", "r", "rarity"):
                return o
            out = TT.apply(o, pats)
            if out != o:
                n[0] += 1
            return out
        return o
    walk(payload)
    return n[0]


def leak_report(payload, TT, n=30):
    """Game text still in the page: any 30-char prefix of an English loca string (>= 30 chars) found in the data."""
    pref = {}
    for h, t in TT.loca.items():
        t2 = strip_markup(t)
        if len(t2) >= 30 and not t2.startswith("%%%"):
            pref.setdefault(t2[:30], []).append(h)
    hits = {}
    for s in iter_strings(payload):
        s2 = re.sub(r"\s+", " ", s)
        for i in range(0, max(0, len(s2) - 29)):
            w = s2[i:i + 30]
            if w in pref:
                for h in pref[w]:
                    hits.setdefault(h, s2[i:i + 70])
    return hits


def iter_strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from iter_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from iter_strings(v)
    elif isinstance(o, str):
        yield o


# ------------------------------------------------------------------------------------------------ header
# Gilded Panel header (branding option 1): our lockup image + CSS panel; the inventory strip
# on the right is filled at runtime from the player's own game icons (7 columns x 3 rows, the third row cut by the panel
# like in branding/LootAdvisor/option1_sets.png; one row on phones).
# What goes in (user 2026-10-09): only the best and rarest items - Legendary and Very Rare page items, ranked by how
# often the sets pick them: main picks first (rank-1 set of each character's main build, per act), then picks in all
# sets, then the item id (deterministic). One cell per icon. The list is longer than the strip: the page skips items
# whose icon the player's install does not have and takes the next one. Every cell gets our rainbow frame (the
# in-game mark of a recommended item - they are all recommended picks; user 2026-10-09).
HDR_COLS, HDR_ROWS, HDR_PHONE, HDR_SPARE = 7, 3, 8, 14
HDR_LA = HDR_COLS * HDR_ROWS + HDR_SPARE   # how many of the ranked items get the rainbow frame: all of them
HDR_RARITY = {"Legendary": "legendary", "VeryRare": "veryrare"}


def header_rank(payload):
    """[(sid, main picks, all picks)] of the Legendary / Very Rare items the sets pick, best first."""
    E, items = payload["E"], payload["items"]
    main, picks = {}, {}
    for ch in payload["chars"]:
        for sets in (ch.get("sets") or {}).values():
            for st in sets:
                is_main = st.get("b") == ch.get("main") and str(st.get("rank")) == "1"
                for idx in (st.get("slots") or {}).values():
                    sid = E[idx].get("sid") if isinstance(idx, int) and idx < len(E) else None
                    if not sid:
                        continue
                    picks[sid] = picks.get(sid, 0) + 1
                    if is_main:
                        main[sid] = main.get(sid, 0) + 1
    ranked = [(sid, main.get(sid, 0), n) for sid, n in picks.items()
              if (items.get(sid) or {}).get("r") in HDR_RARITY and (items.get(sid) or {}).get("icon")]
    ranked.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return ranked


def header_cells(A, payload):
    """DATA.hdr: the ranked item list for the strip (icon art keys already in the page's art list - no extra art)."""
    out, seen = [], set()
    for sid, _m, _n in header_rank(payload):
        it = payload["items"][sid]
        if it["icon"] in seen:
            continue
        seen.add(it["icon"])
        out.append([it["icon"], HDR_RARITY[it["r"]], 0])
        if len(out) >= HDR_COLS * HDR_ROWS + HDR_SPARE:
            break
    missing = [] if len(out) >= HDR_COLS * HDR_ROWS else ["only %d ranked items" % len(out)]
    return {"cols": HDR_COLS, "rows": HDR_ROWS, "phone": HDR_PHONE, "la": HDR_LA, "items": out}, missing


LOCKUP = os.path.join(SHIP_SRC, "brand_lockup.webp")   # tools/sets_ship/render_lockup.py (our own art)


LOCKUP_PRIVATE = os.path.join(SHIP_SRC, "brand_lockup_private.webp")   # the online copy (does not follow the game)
ALT_SHIP = "Loot Advisor: Synergy Sets - full loadouts for your build, follows your game live"
ALT_PRIVATE = "Loot Advisor: Synergy Sets - full loadouts for every origin, act by act"
# under the header: the same sentence as the README, INSTALL.md, the Nexus page, the handbook and the F6 notice
SPOILER = ("Loot Advisor names items, where they are and who carries them, and its notes reveal story outcomes "
           "(who can die, which side you take, endings).")


def header_html(shell, lockup=LOCKUP, alt=ALT_SHIP):
    """The Gilded Panel header in place of shell.html's text brand (also used by build_sets_artifact.gilded_header),
    with the spoiler warning under it."""
    import base64
    lock = base64.b64encode(open(lockup, "rb").read()).decode("ascii")
    old = re.search(r'<div class="brand">.*?</div>', shell, re.S)
    if not old:
        raise SystemExit("shell.html brand block not found - update build_sets_ship.header_html")
    new = ('<div class="brand gship">\n      <h1 class="brand-title"><span class="gp-wrap"><span class="gp">'
           '<span class="gp-frame" aria-hidden="true"><i class="c" style="left:0;top:0"></i><i class="c" style="left:100%;top:0"></i>'
           '<i class="c" style="left:0;top:100%"></i><i class="c" style="left:100%;top:100%"></i>'
           '<i class="m" style="left:50%;top:0"></i><i class="m" style="left:50%;top:100%"></i></span>'
           '<img class="gp-lock" src="data:image/webp;base64,@LOCK@" width="659" height="240" '
           'alt="@ALT@">'
           '<span class="gp-strip" id="gpStrip" aria-hidden="true"></span><span class="gp-row" id="gpRow" aria-hidden="true"></span>'
           '</span></span></h1>\n    </div>\n    <p class="spoil" role="note"><b>Spoiler warning:</b> @SPOIL@</p>')
    new = new.replace("@LOCK@", lock).replace("@ALT@", alt).replace("@SPOIL@", SPOILER)
    return shell[:old.start()] + new + shell[old.end():]


# ------------------------------------------------------------------------------------------------ build
def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build(args):
    t0 = time.time()
    A = ShipAssets()
    B.origin_portrait = ship_portrait
    payload, A, meta = B.build_payload(args, A)
    D = meta["D"]
    # unique-item owners + exact ties per item (LootData o / ot): the live page gives contested items to whoever
    # is in the party (both in the party -> "shared pick")
    try:
        ld = open(os.path.join(ROOT, "data", "scores", "lua", "LootData.lua"), encoding="utf-8").read()
        for m in re.finditer(r'\{id="([^"]+)",[^\n]*?\bo=\{([^}]*)\},ot=\{([^}]*)\}', ld):
            it = payload["items"].get(m.group(1))
            if it is not None:
                o = re.findall(r'"(\w+)"', m.group(2))
                ot = re.findall(r'"(\w+)"', m.group(3))
                if o:
                    it["o"] = o
                if ot:
                    it["ot"] = ot
    except OSError:
        pass

    # ---- header strip icons (before the manifest, so the mod writes them with the other art)
    payload["hdr"], hdr_missing = header_cells(A, payload)
    if hdr_missing:
        print("  ! header strip: %s (the rest stays empty slots)" % ", ".join(hdr_missing))

    # ---- art manifest: keys -> path index + box (the page builds IMG[key] from the decoded textures)
    paths, pidx = [], {}

    def pi(p):
        if p not in pidx:
            pidx[p] = len(paths)
            paths.append(p)
        return pidx[p]
    art = {}
    for key, m in A.man.items():
        art[key] = [pi(m["p"]), (m["b"] or [0, 0])[0], (m["b"] or [0, 0])[1]] + ([m["uv"]] if m["uv"] else [])
    fonts = {}
    for k, p in B.FONTS.items():
        if A.font(p):
            fonts[k] = pi(p)
    payload["art"] = art
    payload["artPaths"] = paths
    payload["fonts"] = fonts

    # ---- text tokens
    TT = TextTable(D)
    TT.collect(payload["items"].keys())
    TT.add_item_names()
    n_tok = tokenize(payload, TT)
    # second pass: game strings the leak check still finds (recipe texts, quest names, deeper statuses)
    for _ in range(3):
        leaks = leak_report(payload, TT)
        new = [h for h in leaks if h not in TT.cands]
        if not new:
            break
        for h in new:
            TT.cands[h] = "extra"
        pats = [p for p in TT.patterns({"extra"}, 3)]
        n_tok += tokenize_with(payload, TT, pats)
    payload["T"] = TT.T
    leaks = leak_report(payload, TT) if args.check else {}

    # ---- page
    shell = open(os.path.join(B.TEMPLATE, "shell.html"), encoding="utf-8").read()
    css = open(os.path.join(B.TEMPLATE, "page.css"), encoding="utf-8").read()
    app = open(os.path.join(B.TEMPLATE, "app.js"), encoding="utf-8").read()
    dds = open(os.path.join(SHIP_SRC, "dds.js"), encoding="utf-8").read()
    ship = open(os.path.join(SHIP_SRC, "ship.js"), encoding="utf-8").read()
    hdr_js = open(os.path.join(SHIP_SRC, "header.js"), encoding="utf-8").read()
    css += "\n" + open(os.path.join(SHIP_SRC, "header.css"), encoding="utf-8").read()
    shell = header_html(shell)
    payload["generated"] = time.strftime("%Y-%m-%d %H:%M")
    payload["ship"] = 1
    data_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    shell = shell.replace('<div class="tools">', '<div class="tools"><span class="live" id="live" role="status" aria-live="polite">'
                          '<span class="dot"></span><span class="lt">Looking for the game...</span></span>')
    html = (shell.replace("/*@FONTS@*/", "")
                 .replace("/*@CSS@*/", css)
                 .replace("@IMAGES@", "{}")
                 .replace("@DATA@", data_json)
                 .replace("/*@JS@*/", "window.LA_APP = function () {\n" + app + "\n};\n" + dds + "\n" + hdr_js + "\n" + ship))
    html = html.replace("@LOADING@", '<span class="prep" id="prep">Preparing the page from your game files...'
                        '<span class="bar"><i></i></span></span>')
    page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>\n' + html + "\n</body></html>\n")
    # the online shell has no doctype (its host adds it); the local page needs one
    os.makedirs(PAGE_DIR, exist_ok=True)
    with open(os.path.join(PAGE_DIR, "Sets.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    ver = hashlib.md5(page.encode("utf-8")).hexdigest()[:12]
    if args.release:
        # player-package copy: the same single file - header, logo and our art are inside it; opened
        # there (no game files next to it) it shows the "load a save once, then open the live page" card
        rel = os.path.join(args.release, "Page")
        os.makedirs(rel, exist_ok=True)
        with open(os.path.join(rel, "Sets.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(page)
        print("  release copy: %s" % os.path.join(rel, "Sets.html"))

    # ---- Lua manifest for the mod
    handles = sorted({h for h, _ in TT.T})
    L = ["-- LootAdvisor (generated, do not edit).",
         "-- What the local Sets page needs from the player's own game install (no game art or text ships with the mod):",
         "--   art = game texture / font paths (read with Ext.IO.LoadFile(path, \"data\"), written as base64 .js),",
         "--   text = loca handles (Ext.Loca.GetTranslatedString), page = files copied from the pak (Mods/LootAdvisor/Page).",
         "LA = LA or {}",
         "LA.Ship = {",
         "  version = %s," % lua_str(ver),
         "  artVersion = %s," % lua_str(hashlib.md5("|".join(paths).encode("utf-8")).hexdigest()[:12]),
         "  page = { \"Sets.html\" },",
         "  art = {"]
    for p in paths:
        L.append("    %s," % lua_str(p))
    L.append("  },")
    L.append("  items = {")
    ids = sorted(payload["items"].keys())
    for i in range(0, len(ids), 4):
        L.append("    " + " ".join(lua_str(x) + "," for x in ids[i:i + 4]))
    L.append("  },")
    L.append("  text = {")
    for i in range(0, len(handles), 4):
        L.append("    " + " ".join(lua_str(h) + "," for h in handles[i:i + 4]))
    L.append("  },")
    L.append("}")
    with open(MANIFEST_LUA, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")

    print("  ship page: %s  %.2f MB  version %s" % (os.path.relpath(os.path.join(PAGE_DIR, "Sets.html"), REPO),
                                                     len(page.encode("utf-8")) / 1e6, ver))
    print("  art: %d image keys from %d game files (+%d fonts); text: %d tokens, %d loca handles, %d strings changed"
          % (len(art), len(paths) - len(fonts), len(fonts), len(TT.T), len(handles), n_tok))
    print("  manifest: %s (%.1f s)" % (os.path.relpath(MANIFEST_LUA, REPO), time.time() - t0))
    if args.check:
        print("  leak check: %d game strings still in the page data" % len(leaks))
        for h, s in list(leaks.items())[:40]:
            print("    %s  %r" % (h, s))
    return payload, TT, A


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-fonts", action="store_true")
    ap.add_argument("--release", metavar="DIR", nargs="?", const=os.path.join(REPO, "dist", "LootAdvisor"),
                    help="also write DIR/Page/Sets.html (default DIR: the local player package dist/LootAdvisor)")
    build(ap.parse_args())
