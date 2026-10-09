"""Leak scanner: finds internal project notes in everything a player can see.

  python tools/leak_scan.py              # static scan (Lua strings, meta.lsx, mod data texts, page data + page code)
  python tools/leak_scan.py --render     # + open the sets page headless (Edge) and scan the visible text and tooltips
  python tools/leak_scan.py -v           # also list the private Autopilot hits and the allowed ones

Exit code 1 when a shipped string leaks (Autopilot is the user's private bot: reported, never fails the run).
A "leak" is: our file names / paths (*.md, *.py, data/..., tools/...), research refs (crafted.md §24, x.md:298),
internal ids (level / flag / stats ids, template UUIDs, loca handles, set ids, raw build ids, data field names),
developer wording (pipeline, scorer, seed, theme, research file, the user's campaign, agent, generated ...),
debug lines, raw boost / condition code, TODO/FIXME. Game names and plain explanations are fine.

Lua: a string literal on a line with "leak-ok" (in a comment) is skipped - only for text that is never shown to a
player (dev-only output, internal keys). Comments are not scanned (they never reach the screen).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
ROOT = os.path.dirname(LA)                     # Desktop (restructure 2026-10: one folder per mod)
MODS = os.path.join(LA, "Mods")                 # LootAdvisor's own Mods/
MOD_DIRS = {"LootAdvisor": os.path.join(LA, "Mods", "LootAdvisor"),
            "BuildAdvisor": os.path.join(ROOT, "BuildAdvisor", "Mods", "BuildAdvisor"),
            "Autopilot": os.path.join(ROOT, "Autopilot", "Mods", "Autopilot")}
SHIPPED_MODS = ["LootAdvisor", "BuildAdvisor"]
PRIVATE_MODS = ["Autopilot"]
GENERATED_LUA = {"LootData.lua", "ModData.lua", "ShipManifest.lua"}   # scanned field by field below
PAGES = [os.path.join(MODS, "LootAdvisor", "Page", "Sets.html"), os.path.join(LA, "artifact", "sets.html")]

# ------------------------------------------------------------------------------------------------ patterns
# "hard" patterns hold for every visible string (game text never contains them)
HARD = [
    ("file name", r"(?<![\w$])[\w./\\-]*\w\.(?:md|py|lua|jsonl?|lsx|lsf|sh|ps1|js|txt|csv|xaml|pak|loca)\b(?::\d+)?"),
    ("research ref", r"§\s*\d+"),
    ("project path", r"\b(?:data|tools|analysis|artifact|spike|design|shots|third_party|dist|Mods)[/\\][\w./\\-]+"),
    ("level / story id", r"\b(?:WLD|CRE|SCL|INT|BGO|CTY|IRN|END|TUT|SYS|GLO|LOW|UND|HAV|DEN|GOB|PLA|MOO|SHA|TWN|WYR|"
                         r"CHA|HAG|ORI|COL|FOR|BAS|HOS|UPP|SCO|DAR|CRA|LOW|RIV|GUI|TOW|EVR|RIV|MAG|UNI|ALCH|ARM|WPN|"
                         r"OBJ|CONS|LOOT|WAYP|LAE|LAX|LAW|LA|BOOK|QUEST|DLC|PAS|CAMP|TEC)_\w+"),
    ("internal id", r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9]+_[A-Za-z0-9_]+\b"),
    ("internal id", r"\bS_[A-Z]\w+"),
    ("uuid", r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    ("loca handle", r"\bh[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g"),
    ("set id", r"\b[a-z]+\.[a-z0-9_]+\.a[123](?:\.\w+)?\b"),
    ("data field", r"(?<![\w.])(?:fb|oa|ca|sv|ow|pb|pa|cl|sc|ot|la|od|cp|lv)\s*(?:=|:)\s*[\w{\"'\[]"),
    ("data field", r"`\w+`"),
    ("raw boost", r"\b(?:RollBonus|StatusImmunity|HasPassive|HasStatus|IsSpell|ActionResource|DamageBonus|"
                  r"CharacterWeaponDamage|WeaponDamage|ReduceCriticalAttackThreshold|UnlockSpell|ApplyStatus|"
                  r"SpellCastingAbilityModifier|ProficiencyBonus|OncePer\w+|ActionPoint:\d|context\.(?:Source|Target))\b"
                  r"|\b(?:Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)Modifier\b|\bIF\("),
    ("dev wording", r"\b(?:TODO|FIXME|XXX)\b|\[dev\]|\[debug\]"),
    ("internal tag", r"\b(?:melee[12]h|handxbow)\b|\bfits [\w/]+/[\w/]+"),
    ("mod name", r"\b(?:LootAdvisor|BuildAdvisor)\b"),   # shown as "Loot Advisor" / "Build Advisor"
    ("user's campaign", r"\b(?:White Urge|Ryzen|Micah)\b|\bSeen in game\b"),
]
# "soft" patterns: developer wording. Only for OUR text (not game text, which may say "seed" or "agent")
SOFT = [
    ("dev wording", r"\b(?:pipeline|scorer|scoring data|research (?:file|ref|refs|set|sets|weight|data)|"
                    r"the user'?s|our (?:data|scorer|files?)|sub-?agents?|agents?|seed(?:ed|s)?|"
                    r"(?:a|per|by|set|no) themes?|themed|generated\s*·|weapon_dmg|validator|fallback slot|handoff|"
                    r"session \d|decision \d+|round \d|game-data fit|stats? ids?|template|placeholder|"
                    r"capture pending|debug|probe|BiS|consensus|\d{4}-\d\d-\d\d)\b"),
    ("dev wording", r"\b(?:BuildAdvisor plan|your campaign)\b"),
]
HARD_RE = [(n, re.compile(p)) for n, p in HARD]
SOFT_RE = [(n, re.compile(p, re.I)) for n, p in SOFT]

# exact strings that may show (player instructions naming the files the mod itself writes / reads)
ALLOW = [
    r"Sets\.html", r"LootAdvisor_settings\.json", r"BuildAdvisor_settings\.json", r"Script Extender[\\/]+LootAdvisor",
]
ALLOW_RE = re.compile("|".join(ALLOW))


def hits(text, soft=True):
    out = []
    t = ALLOW_RE.sub(" ", text)
    for name, rx in HARD_RE + (SOFT_RE if soft else []):
        for m in rx.finditer(t):
            out.append((name, m.group(0)))
    return out


# ------------------------------------------------------------------------------------------------ Lua literals
def lua_tokens(src):
    """("str" | "comment", line, text) for every string literal and comment."""
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if src.startswith("--", i):
            m = re.match(r"--\[(=*)\[", src[i:])
            if m:
                end = src.find("]" + m.group(1) + "]", i)
                end = n if end < 0 else end + len(m.group(1)) + 2
            else:
                end = src.find("\n", i)
                end = n if end < 0 else end
            yield "comment", line, src[i:end]
            line += src.count("\n", i, end); i = end; continue
        m = re.match(r"\[(=*)\[", src[i:i + 20]) if c == "[" else None
        if m:
            close = "]" + m.group(1) + "]"
            end = src.find(close, i)
            end = n if end < 0 else end
            yield "str", line, src[i + len(m.group(0)):end]
            line += src.count("\n", i, end); i = end + len(close); continue
        if c in "\"'":
            j, buf = i + 1, []
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2]); j += 2; continue
                buf.append(src[j]); j += 1
            yield "str", line, "".join(buf)
            i = j + 1; continue
        i += 1


def lua_strings(src):
    """(line, text) for every string literal; comments are skipped."""
    return [(ln, t) for k, ln, t in lua_tokens(src) if k == "str"]


def is_prose(s):
    return " " in s.strip() or re.search(r"[.!?:]\s*$", s) is not None


def scan_lua(path, report, private):
    src = open(path, encoding="utf-8", errors="replace").read()
    lines = src.split("\n")
    rel = os.path.relpath(path, ROOT)
    for ln, s in lua_strings(src):
        if "leak-ok" in lines[ln - 1]:
            continue
        if not is_prose(s):
            continue   # keys, ids, file names the mod reads / writes: never shown as text
        for name, hit in hits(s):
            report.append(("private" if private else "fail", "%s:%d" % (rel, ln), name, hit, s))


# comments ship inside the pak (readable when unpacked): no references to our own docs, tools or work notes
COMMENT_RE = re.compile(r"[\w./-]+\.md\b|\b\w+\.py\b|\b(?:tools|analysis|artifact|design|spike|data/research|"
                        r"data/scores)/|HANDOFF|\bdecision \d+|\bsession \d+|\bround \d\b|MOD_STATUS|FEASIBILITY|"
                        r"UX_AUDIT|IMAGES_RESULTS|\bTODO\b|\bFIXME\b")


def scan_lua_comments(path, report, private):
    src = open(path, encoding="utf-8", errors="replace").read()
    rel = os.path.relpath(path, ROOT)
    for k, ln, c in lua_tokens(src):
        if k != "comment":
            continue
        for m in COMMENT_RE.finditer(c):
            report.append(("private" if private else "fail", "%s:%d (comment)" % (rel, ln), "internal note",
                           m.group(0), c.strip()))


# ------------------------------------------------------------------------------------------------ meta.lsx
def scan_meta(path, report, private):
    src = open(path, encoding="utf-8").read()
    for m in re.finditer(r'id="(Name|Description|Author)"[^>]*value="([^"]*)"', src):
        for name, hit in hits(m.group(2)):
            report.append(("private" if private else "fail", os.path.relpath(path, ROOT) + " " + m.group(1), name, hit, m.group(2)))


# ------------------------------------------------------------------------------------------------ mod data (lupa)
def lua_table(path, root):
    import lupa
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("LA = {}")
    L.execute(open(path, encoding="utf-8").read())
    return L.eval(root)


def py(o, depth=0):
    if depth > 12:
        return None
    if hasattr(o, "items") and not isinstance(o, (dict, str)):
        d = {k: py(v, depth + 1) for k, v in o.items()}
        if d and all(isinstance(k, int) for k in d):
            return [d[k] for k in sorted(d)]
        return d
    return o


def scan_mod_data(report):
    shared = os.path.join(MODS, "LootAdvisor", "ScriptExtender", "Lua", "Shared")
    D = py(lua_table(os.path.join(shared, "LootData.lua"), "LA.Data"))
    texts = []   # (where, text) - every field the list window, tooltips or map labels show
    for k, it in enumerate(D.get("items") or [], 1):
        sid = it.get("id")
        for f in ("n", "w", "g"):
            texts.append(("LootData item %s .%s" % (sid, f), it.get(f)))
        for loc in it.get("l") or []:
            texts.append(("LootData item %s .l.h" % sid, loc.get("h")))
            texts.append(("LootData item %s .l.rg" % sid, loc.get("rg")))
    for ck, c in (D.get("chars") or {}).items():
        for b in c.get("b") or []:
            texts.append(("LootData %s build %s .n" % (ck, b.get("id")), b.get("n")))
            for idx, w in (b.get("why") or {}).items() if isinstance(b.get("why"), dict) else enumerate(b.get("why") or []):
                texts.append(("LootData %s build %s .why[%s]" % (ck, b.get("id"), idx), w))
            acts = b.get("a") or {}
            for act, a in (acts.items() if isinstance(acts, dict) else enumerate(acts, 1)):
                for s in (a or {}).get("sets") or []:
                    texts.append(("LootData set %s .n" % s.get("id"), s.get("n")))
                    texts.append(("LootData set %s .why" % s.get("id"), s.get("why")))
    M = py(lua_table(os.path.join(shared, "ModData.lua"), "LA.Mod"))
    for r, nm in (M.get("regionName") or {}).items():
        texts.append(("ModData regionName %s" % r, nm))
    for sid, ms in (M.get("markers") or {}).items():
        for m in ms or []:
            texts.append(("ModData marker %s .w" % m.get("m"), m.get("w")))
            texts.append(("ModData marker %s .rg" % m.get("m"), m.get("rg")))
    seen = set()
    for where, t in texts:
        if not isinstance(t, str) or not t or (where.split(" .")[-1], t) in seen:
            continue
        seen.add((where.split(" .")[-1], t))
        # item names / holder names are game text: hard patterns only
        soft = not re.search(r"\.(n|l\.h|w)$", where) or "build" in where or "set " in where
        for name, hit in hits(t, soft=soft):
            report.append(("fail", where, name, hit, t))
    return len(seen)


# ------------------------------------------------------------------------------------------------ pages
GAME_KEYS = {"d", "t", "icon", "art", "artPaths", "fonts", "T", "portrait", "id", "sid", "b", "i", "ship", "generated",
             "rarityColor"}


def page_data(src):
    tag = '<script id="la-data" type="application/json">'
    i = src.find(tag)
    if i < 0:
        return None
    i += len(tag)
    return json.loads(src[i:src.index("</script>", i)].replace(r"<\/", "</"))


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, path + "/" + str(k))
    elif isinstance(o, list):
        for k, v in enumerate(o):
            yield from walk(v, path + "/" + str(k))
    elif isinstance(o, str):
        yield path, o


def js_strings(src):
    """String literals of a script (approximate tokenizer: comments skipped, regex literals tolerated)."""
    i, n = 0, len(src)
    prev = ""
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i); i = n if j < 0 else j + 2; continue
        if c == "/" and prev in "(,=:[!&|?{};+-*%<>~^" :
            j = i + 1
            while j < n and src[j] not in "/\n":
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    while j < n and src[j] != "]":
                        j += 2 if src[j] == "\\" else 1
                j += 1
            i = j + 1; prev = "x"; continue
        if c in "\"'`":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1]); j += 2; continue
                if src[j] == "\n" and c != "`":
                    break
                buf.append(src[j]); j += 1
            yield "".join(buf)
            i = j + 1; prev = "x"; continue
        if not c.isspace():
            prev = c
        i += 1


def visible_html(src):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", src)
    attrs = re.findall(r'(?:title|aria-label|placeholder|alt)="([^"]*)"', s)
    s = re.sub(r"<[^>]+>", " ", s)
    return [x for x in [s] + attrs if x.strip()]


def strip_markup(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return s.replace("&middot;", "·").replace("&amp;", "&").replace("&nbsp;", " ")


def scan_page(path, report):
    src = open(path, encoding="utf-8").read()
    rel = os.path.relpath(path, ROOT)
    D = page_data(src)
    n = 0
    if D is not None:
        for p, s in walk({k: v for k, v in D.items() if k not in ("art", "artPaths", "fonts", "T")}):
            last = p.rsplit("/", 1)[-1]
            parts = p.split("/")
            if p.startswith("/items/"):
                # item records: game names / descriptions (hard patterns only); raw boosts and conditions are
                # inputs for the page's own text (checked rendered, --render)
                if len(parts) != 4 or last not in ("n", "type", "slot", "d"):
                    continue
                soft = False
            else:
                if last in GAME_KEYS or not is_prose(s) and last not in ("n", "tl"):
                    continue
                soft = True
            n += 1
            for name, hit in hits(strip_markup(s), soft=soft):
                report.append(("fail", "%s data%s" % (rel, p), name, hit, s))
    scripts = re.findall(r"(?is)<script(?![^>]*application/json)[^>]*>(.*?)</script>", src)
    for code in scripts:
        for s in js_strings(code):
            if not is_prose(s):
                continue
            n += 1
            txt = strip_markup(s)
            for name, hit in hits(txt):
                if name == "internal id" and re.fullmatch(r"[\w.-]+", hit) and hit not in txt.split():
                    continue
                report.append(("fail", "%s script" % rel, name, hit, s))
    for t in visible_html(src):
        n += 1
        for name, hit in hits(t):
            report.append(("fail", "%s html" % rel, name, hit, t[:200]))
    return n


# ------------------------------------------------------------------------------------------------ rendered page
RENDER_JS = r"""
(async function(){
  var out = [], D = window.LootAdvisorSets.data, sleep = ms => new Promise(r => setTimeout(r, ms));
  function grab(where){
    out.push([where, document.body.innerText]);
    document.querySelectorAll('[title],[aria-label],[placeholder],[alt]').forEach(function(e){
      ['title','aria-label','placeholder','alt'].forEach(function(a){ var v=e.getAttribute(a); if(v) out.push([where+' @'+a, v]); });
    });
  }
  var lg = document.getElementById('legend'); if (lg) out.push(['legend', lg.textContent]);
  var ids = [];
  D.chars.forEach(function(c){ ['1','2','3'].forEach(function(a){ (c.sets[a]||[]).forEach(function(s){ ids.push(s.id); }); }); });
  for (var k = 0; k < ids.length; k++) {
    location.hash = ids[k]; await sleep(30);
    grab('#' + ids[k]);
    var tips = document.querySelectorAll('[data-tip]');
    for (var t = 0; t < tips.length; t++) {
      tips[t].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
      var tt = document.getElementById('tt'); if (tt && !tt.hidden) out.push(['#' + ids[k] + ' tooltip', tt.innerText]);
    }
  }
  return out;
})()
"""


def scan_rendered(report):
    sys.path.insert(0, os.path.join(LA, "artifact", "ux_audit", "scripts"))
    import drv
    page = os.path.join(LA, "artifact", "_preview.html")
    b = drv.B()
    try:
        b.load(1440, 900, url="file:///" + page.replace("\\", "/"))
        res = b.js(RENDER_JS) or []
    finally:
        b.close()
    if isinstance(res, dict):
        raise RuntimeError(res)
    seen = set()
    for where, text in res:
        for line in (text or "").split("\n"):
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            # rendered text mixes game text in: hard patterns only, plus a few dev phrases
            extra = [("dev wording", m.group(0)) for m in RENDER_SOFT.finditer(line)]
            extra += [("raw game id", m.group(0)) for m in RENDER_CAMEL.finditer(line) if m.group(0) not in CAMEL_OK]
            for name, hit in hits(line, soft=False) + extra:
                report.append(("fail", "rendered " + where, name, hit, line[:200]))
    dump = os.environ.get("LEAK_SCAN_DUMP")
    if dump:   # all distinct rendered lines, for a manual read-through
        with open(dump, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(seen)))
    return len(seen)


# rendered text mixes in game text: only developer phrases that game text never uses
RENDER_SOFT = re.compile(r"\b(?:pipeline|scorer|research (?:file|set|sets|ref)|the user'?s|generated\s*·|weapon_dmg|"
                         r"your campaign|a theme|themed|test save|not captured|BiS|consensus|game-data fit|"
                         r"seed set|placeholder|capture pending|\d{4}-\d\d-\d\d)\b", re.I)
# CamelCase words are raw game ids (HandCrossbows, SpellSlot); real names that look like that are listed here
RENDER_CAMEL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")
CAMEL_OK = {"DeVir"}


# ------------------------------------------------------------------------------------------------ main
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    verbose = "-v" in sys.argv
    report = []
    counts = {}
    for mod in SHIPPED_MODS + PRIVATE_MODS:
        private = mod in PRIVATE_MODS
        base = MOD_DIRS.get(mod, os.path.join(MODS, mod))
        if private and not os.path.isdir(base):
            counts[mod] = "not checked out"   # private repo, absent in public CI
            continue
        nlua = 0
        for dp, _, fs in os.walk(os.path.join(base, "ScriptExtender")):
            for f in fs:
                if f.endswith(".lua"):
                    scan_lua_comments(os.path.join(dp, f), report, private)
                if f.endswith(".lua") and f not in GENERATED_LUA:
                    scan_lua(os.path.join(dp, f), report, private); nlua += 1
        scan_meta(os.path.join(base, "meta.lsx"), report, private)
        counts[mod] = nlua
    counts["mod data texts"] = scan_mod_data(report)
    for p in PAGES:
        if os.path.exists(p):
            counts[os.path.relpath(p, ROOT)] = scan_page(p, report)
    if "--render" in sys.argv:
        counts["rendered lines"] = scan_rendered(report)
    fails = [r for r in report if r[0] == "fail"]
    priv = [r for r in report if r[0] == "private"]
    print("scanned: " + ", ".join("%s %s" % (k, v) for k, v in counts.items()))
    seen = set()
    for kind, where, name, hit, s in fails + (priv if verbose else []):
        key = (kind, where.split(":")[0], name, hit)
        if key in seen:
            continue
        seen.add(key)
        print("%s  %-9s %-60s %-16s %r  <- %r" % ("LEAK" if kind == "fail" else "priv", "", where[:60], name, hit, s[:140]))
    print("leaks: %d shipped, %d private (Autopilot, not failing)" % (len(fails), len(priv)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
