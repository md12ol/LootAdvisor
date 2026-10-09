"""Build the LootAdvisor sets artifact (PLAN step 6): artifact/sets.html, one self-contained page.

    python tools/build_sets_artifact.py            # re-run any time; ~10-20 s cold, a few s with the icon cache
    python tools/build_sets_artifact.py --no-fonts # skip the embedded game fonts (smaller page)

Reads the CURRENT data (read-only, never edited here):
  data/scores/<char>.json          builds, sets, per-item scores (tools/score_items.py)
  data/scores/owners.json          unique-item owners (only used for the "better on X" text if a set lacks it)
  data/scores/lua/LootData.lua     la = last act an item can be obtained in
  data/items_all/*.jsonl           every item: stats, effects, description (loca), icon
  data/research/conditions.md      condition codes (labels only)
  data/cache/stats_resolved.json   spells / passives / statuses (icons, boosts)
  Mods/BuildAdvisor/.../Builds.lua feats and fighting styles of the BuildAdvisor builds
  game paks (read-only, tools/pak.py): icons, UI art, fonts
  shots/sets/<char>_<act>_<setid>_{model,sheet}.png   in-game captures, picked up when present

Writes: artifact/sets.html (+ artifact/.cache/ icon cache, safe to delete).
The page template lives in tools/sets_artifact/ (shell.html, page.css, app.js).
The character sheet numbers are COMPUTED here (compute_sheet) from the game data at level 12; every number carries
its formula so it can be checked against the in-game sheet captures.
"""
import argparse
import ast
import base64
import glob
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # LootAdvisor/
REPO = ROOT                                        # LootAdvisor/ (holds Mods/LootAdvisor since the 2026-10 restructure)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "sets_artifact"))
import playertext as P  # noqa: E402  (player-facing text rules, UX audit F5)

DATA = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "artifact")
CACHE = os.path.join(OUT_DIR, ".cache")
SHOTS = os.path.join(ROOT, "shots", "sets")
TEMPLATE = os.path.join(HERE, "sets_artifact")
BUILDS_LUA = os.path.join(os.path.dirname(ROOT), "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender", "Lua", "Shared",
                          "Builds.lua")

CHARS = ["astarion", "gale", "karlach", "laezel", "shadowheart", "wyll", "darkurge"]
SLOTS = ["Helmet", "Cloak", "Breast", "Gloves", "Boots", "Amulet", "Ring1", "Ring2",
         "MainHand", "OffHand", "Ranged", "RangedOff", "Elixir"]
LEVEL = 12
PROF = 4  # proficiency bonus at level 12

ABIL = {"Strength": "STR", "Dexterity": "DEX", "Constitution": "CON", "Intelligence": "INT", "Wisdom": "WIS",
        "Charisma": "CHA"}
ABIL_NAMES = {v: k for k, v in ABIL.items()}
HIT_DIE = {"Barbarian": 12, "Fighter": 10, "Paladin": 10, "Ranger": 10, "Bard": 8, "Cleric": 8, "Druid": 8,
           "Monk": 8, "Rogue": 8, "Warlock": 8, "Sorcerer": 6, "Wizard": 6}
CAST_ABIL = {"Wizard": "INT", "Cleric": "WIS", "Druid": "WIS", "Ranger": "WIS", "Paladin": "CHA", "Sorcerer": "CHA",
             "Warlock": "CHA", "Bard": "CHA"}
# subclass keyword (in build names / Builds.lua picks) -> (class, game ClassIcons file or None)
SUBCLASSES = [
    ("Gloom Stalker", "Ranger", "GloomStalker"), ("Hunter", "Ranger", "Hunter"),
    ("Beast Master", "Ranger", "BeastMaster"), ("Assassin", "Rogue", "Assassin"), ("Thief", "Rogue", "Thief"),
    ("Arcane Trickster", "Rogue", "ArcaneTrickster"), ("Battle Master", "Fighter", "BattleMaster"),
    ("Champion", "Fighter", "Champion"), ("Eldritch Knight", "Fighter", "EldritchKnight"),
    ("Berserker", "Barbarian", "BerserkerPath"), ("Wildheart", "Barbarian", "TotemWarriorPath"),
    ("Bear", "Barbarian", "TotemWarriorPath"), ("Path of Giants", "Barbarian", None), ("Giant", "Barbarian", None),
    ("Evocation", "Wizard", "EvocationSchool"), ("Evoker", "Wizard", "EvocationSchool"),
    ("Abjuration", "Wizard", "AbjurationSchool"), ("Bladesinging", "Wizard", None), ("Bladesinger", "Wizard", None),
    ("Storm Sorcer", "Sorcerer", "StormSorcery"), ("Draconic", "Sorcerer", "DraconicBloodline"),
    ("Shadow Sorcerer", "Sorcerer", None), ("Shadow Magic", "Sorcerer", None),
    ("Tempest", "Cleric", "TempestDomain"), ("Light Domain", "Cleric", "LightDomain"),
    ("Life Domain", "Cleric", "LifeDomain"), ("Trickery", "Cleric", "TrickeryDomain"),
    ("Vengeance", "Paladin", "Vengeance"), ("Oathbreaker", "Paladin", "Oathbreaker"),
    ("Hexblade", "Warlock", None), ("Fiend", "Warlock", "Fiend"), ("Swords", "Bard", "SwordsCollege"),
]
RACE_ICON = {"High Elf": "Elf_HighElf", "Human": "Human", "Zariel Tiefling": "Tiefling_Zariel",
             "Githyanki": "Githyanki", "High Half-Elf": "HalfElf_High", "White Dragonborn": "Dragonborn_White"}
RACE_RESIST = {"Zariel Tiefling": [("Fire", "Resistant", "Hellish Resistance (Tiefling)")],
               "White Dragonborn": [("Cold", "Resistant", "Draconic Ancestry (White)")]}
ORIGIN_BG = {"astarion": "Astarion", "gale": "Gale", "karlach": "Karlach", "laezel": "Laezel",
             "shadowheart": "Shadowheart", "wyll": "Wyll", "darkurge": "HauntedOne"}
RARITY_LABEL = {"Common": "Common", "Uncommon": "Uncommon", "Rare": "Rare", "VeryRare": "Very Rare",
                "Legendary": "Legendary", "Story": "Story"}
DMG_TYPES = ["Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison",
             "Psychic", "Radiant", "Slashing", "Thunder"]


# ------------------------------------------------------------------------------------------------ helpers
def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("  ! could not read", os.path.relpath(path, ROOT), "-", e)
        return default


def clean(t):
    """Game text -> plain text (drop LSTag markup, keep line breaks)."""
    if not t:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", str(t))
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


def split_top(s, sep=";"):
    """Split on sep at parenthesis depth 0."""
    out, depth, cur = [], 0, []
    for ch in s or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return [x for x in out if x]


BOOST_RE = re.compile(r"^([A-Za-z]+)\s*\((.*)\)$", re.S)


def parse_boosts(s):
    """'IF(c):AC(1);Ability(Strength,2)' -> [(cond|None, name, [args])]."""
    res = []
    for part in split_top(s):
        cond = None
        m = re.match(r"^IF\((.*)\):(.*)$", part, re.S)
        if m:
            # the condition may itself contain '):' - find the matching parenthesis
            depth, i = 0, 2
            for i in range(2, len(part)):
                if part[i] == "(":
                    depth += 1
                elif part[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
            cond, part = part[3:i], part[i + 2:]
        m = BOOST_RE.match(part.strip())
        if not m:
            continue
        args = [a.strip() for a in split_top(m.group(2), ",")]
        res.append((cond, m.group(1), args))
    return res


def safe_eval(expr, names):
    """Evaluate a tiny arithmetic expression like max(1,StrengthModifier)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name) and n.id in names:
            return names[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = ev(n.left), ev(n.right)
            return a + b if isinstance(n.op, ast.Add) else a - b if isinstance(n.op, ast.Sub) else a * b
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("max", "min"):
            vals = [ev(a) for a in n.args]
            return max(vals) if n.func.id == "max" else min(vals)
        raise ValueError(ast.dump(n))
    try:
        v = ev(tree)
        return int(v) if isinstance(v, (int, float)) else None
    except (ValueError, TypeError, KeyError):
        return None


DICE_RE = re.compile(r"^(\d+)d(\d+)$")


def dice_avg(d):
    m = DICE_RE.match(d.strip())
    if not m:
        return 0
    return int(m.group(1)) * (int(m.group(2)) + 1) / 2


def mod(score):
    return (score - 10) // 2


def fmt_mod(v):
    return ("+" if v >= 0 else "") + str(v)


# ------------------------------------------------------------------------------------------------ data
class Data:
    def __init__(self):
        t = time.time()
        self.items = {}
        for g in ("weapons", "armour", "accessories"):
            p = os.path.join(DATA, "items_all", g + ".jsonl")
            try:
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            r = json.loads(line)
                            self.items[r["stats_id"]] = r
            except OSError as e:
                print("  ! missing", p, e)
        self.stats = load_json(os.path.join(DATA, "cache", "stats_resolved.json"), {})
        self.chars = {}
        for c in CHARS:
            d = load_json(os.path.join(DATA, "scores", c + ".json"))
            if d:
                self.chars[c] = d
        self.owners = load_json(os.path.join(DATA, "scores", "owners.json"), {}) or {}
        self.lastact = self._lootdata_last_act()
        self.ba = parse_builds_lua(BUILDS_LUA)
        self.cond_labels = parse_conditions(os.path.join(DATA, "research", "conditions.md"))
        print("  data loaded in %.1f s: %d items, %d characters, %d BuildAdvisor builds, main builds %s"
              % (time.time() - t, len(self.items), len(self.chars), len(self.ba) - 1, self.ba.get("_origins")))

    def _lootdata_last_act(self):
        p = os.path.join(DATA, "scores", "lua", "LootData.lua")
        res = {}
        try:
            with open(p, encoding="utf-8") as f:
                for m in re.finditer(r'\{id="([^"]+)",[^\n]*?\bla=(\d)', f.read()):
                    res[m.group(1)] = int(m.group(2))
        except OSError:
            pass
        return res

    def stat_name(self, sid):
        st = self.stats.get(sid) or {}
        return st


ALT_INFO = {}        # sid -> where-to-get entry for alternatives (fallback / party / earlier-act / Dark-Urge-only)


def parse_builds_lua(path):
    """Builds.lua -> {id: {name, classes_in_order, picks:[str], base, plus2, plus1}} (read-only, defensive)."""
    res = {}
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return res
    starts = [m.start() for m in re.finditer(r'\bid\s*=\s*"', src)]
    for i, s in enumerate(starts):
        block = src[s: starts[i + 1] if i + 1 < len(starts) else len(src)]
        m = re.match(r'id\s*=\s*"([^"]+)"', block)
        if not m:
            continue
        bid = m.group(1)
        nm = re.search(r'name\s*=\s*"([^"]*)"', block)
        levels = re.findall(r'L\("([A-Za-z]+)",\s*\{([^}]*)\}', block)
        picks = []
        order = []
        lv = []
        for cls, p in levels:
            order.append(cls)
            pp = re.findall(r'"([^"]*)"', p)
            picks += pp
            lv.append((cls, pp))
        res[bid] = {"name": nm.group(1) if nm else bid, "order": order, "picks": picks, "levels": lv}
    # BA.Origins = { astarion = { builds = { "thx", "gloomassassin" }, ... } -> the main (first) build per origin
    res["_origins"] = {}
    mo = re.search(r"BA\.Origins\s*=\s*\{(.*?)\n\}", src, re.S)
    if mo:
        for m in re.finditer(r'(\w+)\s*=\s*\{\s*builds\s*=\s*\{([^}]*)\}', mo.group(1)):
            ids = re.findall(r'"([^"]+)"', m.group(2))
            if ids:
                res["_origins"][m.group(1)] = ids[0]
    return res


def parse_conditions(path):
    labels = {}
    try:
        txt = open(path, encoding="utf-8").read()
    except OSError:
        return labels
    for m in re.finditer(r"^- `([^`]+)` - (.+)$", txt, re.M):
        labels[m.group(1).split("<")[0].rstrip(":")] = m.group(2).strip()
    return labels


def cond_text(code):
    return P.cond_sentence(code)


# ------------------------------------------------------------------------------------------------ assets
class Assets:
    """Extracts game textures from the paks, converts to WebP, caches on disk, dedupes by content."""

    def __init__(self):
        os.makedirs(CACHE, exist_ok=True)
        self._paks = {}
        self.uris = {}       # key -> data URI
        self.missing = []
        self._atlas = None
        self.bytes = 0

    def pak(self, name):
        if name not in self._paks:
            from pak import Pak, GAME_DATA
            self._paks[name] = Pak(os.path.join(GAME_DATA, name))
        return self._paks[name]

    def has(self, pakname, path):
        try:
            return path in self.pak(pakname).by_name
        except OSError:
            return False

    def _decode(self, pakname, path):
        from PIL import Image
        p = self.pak(pakname)
        return Image.open(io.BytesIO(p.read(p.by_name[path]))).convert("RGBA")

    def add_image(self, key, loader, size=None, quality=82, fit="box", lossless=False):
        """loader() -> PIL image (only called on a cache miss). size = (w,h) max box. Returns key or None."""
        if key in self.uris:
            return key
        tag = hashlib.md5(("%s|%s|%s|%s|%s" % (key, size, quality, fit, lossless)).encode()).hexdigest()[:16]
        cp = os.path.join(CACHE, tag + ".webp")
        if not os.path.exists(cp):
            try:
                im = loader()
            except Exception as e:  # missing texture / decode problem -> drawn fallback in the page
                self.missing.append("%s (%s)" % (key, e))
                return None
            if im is None:
                self.missing.append(key)
                return None
            from PIL import Image
            if size:
                im = im.copy()
                im.thumbnail(size, Image.LANCZOS)
            im.save(cp, "WEBP", quality=quality, method=6, lossless=lossless)
        data = open(cp, "rb").read()
        self.bytes += len(data)
        self.uris[key] = "data:image/webp;base64," + base64.b64encode(data).decode()
        return key

    def game(self, key, path, size=None, pakname="Game.pak", **kw):
        if not self.has(pakname, path):
            self.missing.append(path)
            return None
        return self.add_image(key, lambda: self._decode(pakname, path), size, **kw)

    # ---- atlas fallback (Icons.pak + Shared/GustavX .lsx UV maps)
    def _atlas_index(self):
        if self._atlas is not None:
            return self._atlas
        self._atlas = {}
        maps = [("Shared.pak", "Public/Shared/GUI/Icons_Items.lsx"), ("Shared.pak", "Public/Shared/GUI/Icons_Items_2.lsx"),
                ("Shared.pak", "Public/Shared/GUI/Icons_Items_3.lsx"), ("Shared.pak", "Public/Shared/GUI/Icons_Items_4.lsx"),
                ("Shared.pak", "Public/Shared/GUI/Icons_Items_5.lsx"), ("Shared.pak", "Public/Shared/GUI/Icons_Items_6.lsx"),
                ("Shared.pak", "Public/Shared/GUI/Icons_Skills.lsx"), ("Shared.pak", "Public/SharedDev/GUI/Icons_Skills.lsx"),
                ("Shared.pak", "Public/SharedDev/GUI/Icons_Items_Dev.lsx"), ("GustavX.pak", "Public/GustavX/GUI/Icons.lsx")]
        for pakname, lsx in maps:
            try:
                p = self.pak(pakname)
                if lsx not in p.by_name:
                    continue
                xml = p.read(p.by_name[lsx]).decode("utf-8", "replace")
            except OSError:
                continue
            tex = None
            mt = re.search(r'id="Path"[^>]*value="([^"]+)"', xml)
            if mt:
                tex = mt.group(1)
            else:  # Public/Shared/GUI/Icons_Items.lsx -> Public/Shared/Assets/Textures/Icons/Icons_Items.dds
                mod_ = lsx.split("/")[1]
                tex = "Public/%s/Assets/Textures/Icons/%s.dds" % (mod_, os.path.basename(lsx)[:-4])
            for node in re.finditer(r'<node id="IconUV">(.*?)</node>', xml, re.S):
                attrs = dict(re.findall(r'id="(\w+)"[^>]*value="([^"]*)"', node.group(1)))
                if "MapKey" in attrs:
                    self._atlas.setdefault(attrs["MapKey"], (tex, [float(attrs.get(k, 0)) for k in ("U1", "V1", "U2", "V2")]))
        return self._atlas

    def _from_atlas(self, name):
        hit = self._atlas_index().get(name)
        if not hit:
            return None
        tex, (u1, v1, u2, v2) = hit
        for pakname in ("Icons.pak", "Shared.pak", "GustavX.pak", "Gustav.pak"):
            if self.has(pakname, tex):
                im = self._decode(pakname, tex)
                W, H = im.size
                return im.crop((round(u1 * W), round(v1 * H), round(u2 * W), round(v2 * H)))
        return None

    def icon(self, name, kind="item", size=96):
        """Item / skill icon by game icon name: tooltip art (380px) -> controller (144px) -> atlas (64px)."""
        if not name:
            return None
        key = "%s:%s:%d" % (kind, name, size)
        if key in self.uris:
            return key
        if kind == "item":
            cands = ["Public/Game/GUI/Assets/Tooltips/ItemIcons/%s.DDS" % name,
                     "Public/Game/GUI/Assets/ControllerUIIcons/items_png/%s.DDS" % name]
        else:
            cands = ["Public/Game/GUI/Assets/Tooltips/Icons/%s.DDS" % name,
                     "Public/Game/GUI/Assets/ControllerUIIcons/skills_png/%s.DDS" % name,
                     "Public/Game/GUI/Assets/Tooltips/ItemIcons/%s.DDS" % name,
                     "Public/Game/GUI/Assets/ControllerUIIcons/items_png/%s.DDS" % name]
        for c in cands:
            if self.has("Game.pak", c):
                return self.add_image(key, lambda c=c: self._decode("Game.pak", c), (size, size), quality=ICON_Q)
        return self.add_image(key, lambda: self._from_atlas(name), (size, size), quality=ICON_Q)

    def font(self, path):
        p = self.pak("Game.pak")
        if path not in p.by_name:
            self.missing.append(path)
            return None
        data = p.read(p.by_name[path])
        self.bytes += len(data)
        return "data:font/ttf;base64," + base64.b64encode(data).decode()


ICON_Q = 72   # item / skill icon WebP quality (F16: 82 -> 72 saves ~0.6 MB, no visible change at 64-96 px)
# fixed UI art: key -> (pak path under Public/Game/GUI/Assets/, max size)
UI_ART = {
    "pane": ("CharacterPanel/pane_body_bg_9s", None),
    "tt_bg": ("Tooltips/TT_full_bg", None),
    "divider": ("Shared/divider", None),
    "hex": ("CharacterPanel/mainStats_ability_single", (88, 102)),
    "ac_shield": ("CharacterPanel/EQSlots_AC", (84, 102)),
    "ico_hp": ("CharacterPanel/ico_hp", None), "ico_init": ("CharacterPanel/ico_initiative", None),
    "ico_speed": ("CharacterPanel/ico_speed", None), "ico_prof": ("Tooltips/ico_proficiency", None),
    "ico_ac": ("Tooltips/ico_AC", None), "ico_coin": ("Tooltips/ico_coin", None),
    "ico_wlight": ("Tooltips/ico_lightWeight", None), "ico_wheavy": ("Tooltips/ico_heavyWeight", None),
    "ico_finesse": ("Tooltips/ico_finesse", None), "ico_range": ("Tooltips/ico_range", None),
    "ico_reach": ("Tooltips/ico_reach", None), "ico_hand": ("Tooltips/ico_handedness", None),
    "ico_throw": ("Tooltips/ico_throwable", None), "ico_dip": ("Tooltips/ico_dippable", None),
    "ico_ammo": ("Tooltips/ico_ammunitionType", None), "ico_magic": ("Tooltips/ico_magicalProperties", None),
    "ico_type": ("Tooltips/ico_type", None),
    "ico_warn": ("Tooltips/ico_warning", None), "ico_warnsoft": ("Tooltips/ico_warningSoft", None),
    "ico_warngrey": ("Tooltips/ico_warningGrey", None), "ico_warnguest": ("Tooltips/ico_warningGuest", None),
    "ico_quote": ("Tooltips/ico_quote", None),
    "ico_party": ("CharacterPanel/ico_party_h", None),
    "ico_chest": ("Shared/ico_search_container_c", (60, 48)),
    "ico_lock": ("CharacterPanel/ico_lock_enabled_d", None),
    "ico_camera": ("CharacterPanel/btn_director", None),
    "num_1": ("Tooltips/num_01", None), "num_2": ("Tooltips/num_02", None), "num_3": ("Tooltips/num_03", None),
    "btn_round": ("CharacterPanel/btn_round_d", None), "btn_round_h": ("CharacterPanel/btn_round_h", None),
    "bg": ("Shared/standardBG", (1600, 900)),
}
# UX audit F16: only the art the page really uses is embedded (unused tab / diamond / tooltip-roll art dropped)
for _r in ("uncommon", "rare", "veryrare", "legendary", "story"):
    UI_ART["rf_%s_back" % _r] = ("Shared/rarityFrame_%s_back" % _r, None)
    UI_ART["rf_%s_front" % _r] = ("Shared/rarityFrame_%s_front" % _r, None)
for _s, _f in (("Helmet", "head"), ("Cloak", "cloak"), ("Breast", "chest"), ("Gloves", "gloves"), ("Boots", "feet"),
               ("Amulet", "amulet"), ("Ring1", "ring01"), ("Ring2", "ring02"), ("MainHand", "melee_mainhand"),
               ("OffHand", "melee_offhand"), ("Ranged", "ranged_mainhand"), ("RangedOff", "ranged_offhand"),
               ("Elixir", "blank")):
    UI_ART["eq_" + _s] = ("CharacterPanel/EquipSlots/EQ_" + _f, (100, 100))
for _d in ("d4", "d6", "d8", "d10", "d12", "d20"):
    UI_ART["die_" + _d] = ("Tooltips/ico_" + _d, (56, 56))
for _t in DMG_TYPES:
    _g = {"Bludgeoning": "blunt"}.get(_t, _t.lower())
    UI_ART["dmg_" + _t] = ("Shared/ico_dmg_" + _g, None)
    UI_ART["res_" + _t] = ("Shared/ico_resistance_" + _g, None)
UI_ART["res_immune"] = ("Shared/ico_resistance_immune", (56, 66))

FONTS = {"q-reg": "Public/Game/GUI/Assets/Fonts/QuadraatOffcPro/QuadraatOffcPro.ttf",
         "q-bold": "Public/Game/GUI/Assets/Fonts/QuadraatOffcPro/QuadraatOffcPro-Bold.ttf",
         "q-it": "Public/Game/GUI/Assets/Fonts/QuadraatOffcPro/QuadraatOffcPro-Italic.ttf"}


def origin_portrait(assets, char):
    """152px origin portrait from Gustav_Textures (Mods/Gustav first); the Dark Urge has none -> None."""
    tag = {"astarion": "Astarion", "gale": "Gale", "karlach": "Karlach", "laezel": "Laezel",
           "shadowheart": "Shadowheart", "wyll": "Wyll"}.get(char)
    if not tag:
        return None
    try:
        p = assets.pak("Gustav_Textures.pak")
    except OSError:
        return None
    names = sorted((n for n in p.by_name if "/GUI/Assets/Portraits/" in n and "(Icon_Origin_%s)" % tag in n),
                   key=lambda n: (0 if n.startswith("Mods/Gustav/") else 1, n))
    if not names:
        return None
    return assets.add_image("portrait:" + char, lambda: assets._decode("Gustav_Textures.pak", names[0]), (152, 152))


# ------------------------------------------------------------------------------------------------ item view
def weapon_type_label(rec):
    chain = rec.get("stats_chain") or []
    for c in reversed(chain):
        if c.startswith("WPN_") and not c.startswith("_"):
            base = re.sub(r"_\d+$", "", c[4:])
            base = base.replace("_", " ")
            return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).strip()
    prof = (rec.get("weapon") or {}).get("proficiency") or []
    for p in prof:
        if not p.endswith("Weapons"):
            return re.sub(r"s$", "", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", p))
    return "Weapon"


ARMOUR_LABEL = {"StuddedLeather": "Studded Leather Armour", "HalfPlate": "Half Plate Armour",
                "ChainMail": "Chain Mail", "ChainShirt": "Chain Shirt", "ScaleMail": "Scale Mail",
                "SplintMail": "Splint Armour", "Plate": "Plate Armour", "Leather": "Leather Armour",
                "Padded": "Padded Armour", "Hide": "Hide Armour", "BreastPlate": "Breastplate", "RingMail": "Ring Mail",
                "Clothing": "Clothing", "Cloth": "Clothing"}
SLOT_LABEL = {"Helmet": "Headwear", "Cloak": "Cloak", "Gloves": "Handwear", "Boots": "Footwear", "Amulet": "Amulet",
              "Ring": "Ring", "Breast": "Armour", "Consumable": "Elixir"}


def item_type_label(rec):
    if rec.get("weapon"):
        return weapon_type_label(rec)
    a = rec.get("armour") or {}
    if a.get("shield"):
        return "Shield"
    if rec.get("slot") == "Breast":
        return ARMOUR_LABEL.get(a.get("armor_type"), "Armour")
    return SLOT_LABEL.get(rec.get("slot"), rec.get("slot") or "Item")


PROP_ICON = {"Finesse": "ico_finesse", "Twohanded": "ico_hand", "Versatile": "ico_hand", "Light": "ico_wlight",
             "Heavy": "ico_wheavy", "Reach": "ico_reach", "Thrown": "ico_throw", "Dippable": "ico_dip",
             "Ammunition": "ico_ammo", "Magical": "ico_magic"}
PROP_LABEL = {"Twohanded": "Two-Handed", "Versatile": "Versatile", "Ammunition": "Ammunition"}


def item_view(D, A, sid):
    """Everything the game's item tooltip shows, for one stats id."""
    rec = D.items.get(sid)
    if not rec:
        return {"n": sid, "r": "Common", "type": "Unknown item", "missing": True}
    v = {"n": rec.get("name") or sid, "r": rec.get("rarity") or "Common", "type": item_type_label(rec),
         "slot": rec.get("slot"), "w": rec.get("weight"), "v": rec.get("value"),
         "d": clean(rec.get("description")), "u": bool(rec.get("unique")),
         "icon": A.icon(rec.get("icon"), "item", 96)}
    if rec.get("slot") == "Ranged Main Weapon":
        v["rng"] = 1
    if rec.get("act"):
        v["act"] = rec.get("act")
    la = D.lastact.get(sid)
    if la:
        v["la"] = la
    w = rec.get("weapon")
    if w:
        die = None
        m = re.match(r"\d+(d\d+)", w.get("damage") or "")
        if m:
            die = "die_" + m.group(1)
        v["wpn"] = {"dmg": w.get("damage"), "ver": w.get("versatile"), "dt": w.get("damage_type"),
                    "ench": w.get("enchantment") or 0, "extra": w.get("extra_damage") or [],
                    "extraT": [P.effect_text(x) for x in (w.get("extra_damage") or [])],
                    "range": w.get("range"), "lrange": w.get("long_range"),
                    "props": [p for p in (w.get("properties") or []) if p not in ("Melee",)],
                    "prof": [p for p in (w.get("proficiency") or [])], "die": die}
    a = rec.get("armour")
    if a and (a.get("ac") is not None or a.get("ac_boost") or a.get("shield")):
        v["arm"] = {"ac": a.get("ac"), "boost": a.get("ac_boost") or 0, "tot": a.get("ac_total"),
                    "cat": a.get("category"), "cap": a.get("dex_cap"), "sh": bool(a.get("shield")),
                    "stealth": bool(a.get("stealth_disadvantage")), "prof": a.get("proficiency") or []}
    effs = []
    for e in rec.get("effects") or []:
        k = e.get("kind")
        name = e.get("name")
        text = clean(e.get("text"))
        # drop the game's hidden technical markers (no effect of their own), keep the readable parts
        if "TECHNICAL" in str(name or "").upper() or "hidden technical marker" in text:
            continue
        text = "; ".join(p for p in re.split(r";\s+(?=applies )", text) if "technical marker" not in p).strip()
        if not text and not name:
            continue
        if k == "boost" and e.get("id") in ("WeaponEnchantment", "WeaponProperty"):
            continue  # shown in the damage line / properties, like the game
        if k == "status" and not name:
            # technical status: keep the readable text without the "applies X:" prefix
            if not text or text.startswith("applies ") and ":" not in text:
                continue
        icon = None
        st = D.stats.get(e.get("id") or "") or {}
        if k in ("spell", "status", "passive") and st.get("Icon"):
            icon = A.icon(st.get("Icon"), "skill", 64)
        nm_, text = P.effect_name(clean(name)), P.effect_text(text)
        if not nm_ and not text:
            continue
        ent = {"k": k, "n": nm_, "t": text}
        if icon:
            ent["i"] = icon
        if e.get("weapon_action"):
            ent["wa"] = 1
        if e.get("hand"):
            ent["h"] = e.get("hand")
        if e.get("source", "").startswith("OnUse"):
            ent["use"] = 1
        effs.append(ent)
    v["eff"] = effs
    req = rec.get("requirements") or {}
    reqs = ["%s %d" % (k.upper(), n) for k, n in req.items() if k != "proficiency" and isinstance(n, int) and n > 0]
    if reqs:
        v["req"] = reqs
    return v


# ------------------------------------------------------------------------------------------------ the sheet
# The page computes the sheet in the browser (tools/sets_artifact/app.js, sheetFor) so the "My playthrough" filters,
# the party-friendly alternatives and the act level can change the items/level live. This Python version is the
# REFERENCE: same inputs (build_input + item_boosts), same rules, same output. The generator writes its results to
# artifact/.cache/sheets_ref.json and tools/sets_artifact/verify_sheet.py checks the page against it (all sets, levels
# 5/8/12). Change both together.
ASI_LEVELS = {"Fighter": (4, 6, 8, 12), "Rogue": (4, 8, 10, 12)}
ACT_LEVEL = {1: 5, 2: 8, 3: 12}


def plan_ba(b):
    """A community build's level plan from the scores data (round 5) in the Builds.lua shape (levels, picks)."""
    pl = b.get("plan") or {}
    lv = pl.get("levels") or []
    if not lv:
        return None
    return {"name": b.get("name") or "", "order": [x["class"] for x in lv],
            "picks": [p_ for x in lv for p_ in x.get("picks") or []],
            "levels": [(x["class"], list(x.get("picks") or [])) for x in lv], "inferred": bool(pl.get("inferred"))}


def build_features(D, build_key, b):
    """Subclasses (with game icons), feats and fighting styles we can know for a build."""
    text = b.get("name", "") + " " + b.get("about", "")
    ba = D.ba.get(build_key) or plan_ba(b)
    picks = ba["picks"] if ba else []
    blob = text + " " + (ba["name"] if ba else "") + " " + " ".join(picks) + " " + " ".join(
        (b.get("subclasses") or {}).values())
    subs, seen = [], set()
    # the scores data names each class's subclass as the game shows it ("Evocation", "Giant"); keywords below only
    # fill classes it does not name (icons from the keyword table: only files known to exist)
    for cls, name in (b.get("subclasses") or {}).items():
        if cls in b.get("classes", {}) and cls not in seen:
            icon = next((ic for kw, c_, ic in SUBCLASSES if c_ == cls and ic and kw.lower() in name.lower()), None)
            subs.append({"n": name, "cls": cls, "icon": icon})
            seen.add(cls)
    for kw, cls, icon in SUBCLASSES:
        if re.search(r"\b" + re.escape(kw), blob, re.I) and cls in b.get("classes", {}) and cls not in seen:
            subs.append({"n": kw if kw not in ("Evoker", "Bear", "Giants", "Bladesinger", "Storm Sorcer")
                         else {"Evoker": "Evocation", "Bear": "Wildheart", "Giants": "Giant",
                               "Bladesinger": "Bladesinging", "Storm Sorcer": "Storm Sorcery"}[kw],
                         "cls": cls, "icon": icon})
            seen.add(cls)
    feats, styles = [], []
    for p in picks:
        m = re.match(r"Feat:\s*([^(]+)", p)
        if m:
            feats.append(m.group(1).strip())
        m = re.match(r"Fighting Style:\s*([^(]+)", p)
        if m:
            styles.append(m.group(1).strip())
    # the scores data carries feats / styles for every build now (round 4); union, Builds.lua order first
    for f in b.get("feats") or []:
        if f not in feats:
            feats.append(f)
    for s in b.get("styles") or []:
        if s not in styles:
            styles.append(s)
    return {"subs": subs, "feats": feats, "styles": styles, "has_ba": bool(D.ba.get(build_key)),
            "planInferred": bool(ba and ba.get("inferred")),
            "thirsting": any("Thirsting Blade" in p for p in picks) or bool(re.search(r"Pact of the Blade|Bladelock",
                                                                                         blob))}


def parse_asi(name):
    """'Ability Improvement +2 STR' / '+1 WIS +1 CON' -> {'STR': 2}; other feats -> {} (unknown which ability)."""
    if not re.match(r"\s*Ability Improvement", name or ""):
        return {}
    return {k: int(v) for v, k in re.findall(r"\+(\d)\s*(STR|DEX|CON|INT|WIS|CHA)", name)}


def build_input(D, char, race, build_key, b):
    """Everything about the build the sheet needs (shipped to the page as-is)."""
    feats = build_features(D, build_key, b)
    classes = b.get("classes") or {}
    ba = D.ba.get(build_key) or plan_ba(b)
    # class taken at each character level: Builds.lua level list when it matches the build, else main class first
    seq = []
    if ba and ba.get("levels"):
        seq = [c for c, _ in ba["levels"]]
        cnt = {}
        for c in seq:
            cnt[c] = cnt.get(c, 0) + 1
        if cnt != classes:
            seq = []
    if not seq:
        for c, n in classes.items():
            seq += [c] * n
    # feat levels: Builds.lua "Feat:" picks give the exact level; otherwise the feats fill the ASI levels in order
    flv = {}
    if ba and ba.get("levels"):
        for i, (_, picks) in enumerate(ba["levels"]):
            for p in picks:
                m = re.match(r"Feat:\s*([^(]+)", p)
                if m:
                    flv.setdefault(m.group(1).strip(), i + 1)
    asi_slots, cnt = [], {}
    for i, c in enumerate(seq):
        cnt[c] = cnt.get(c, 0) + 1
        if cnt[c] in ASI_LEVELS.get(c, (4, 8, 12)):
            asi_slots.append(i + 1)
    flist, used = [], set()
    for f in feats["feats"]:
        lv = flv.get(f)
        if lv is None:
            free = [x for x in asi_slots if x not in used]
            lv = free[0] if free else None
        if lv:
            used.add(lv)
        flist.append({"n": f, "lv": lv, "asi": parse_asi(f)})
    return {"id": build_key, "race": race, "classes": [[c, n] for c, n in classes.items()], "seq": seq,
            "prof": sorted(set(b.get("proficiencies") or [])),
            "base": dict((b.get("profile") or {}).get("stats") or {"STR": 10, "DEX": 10, "CON": 10, "INT": 10,
                                                                     "WIS": 10, "CHA": 10}),
            "feats": flist, "styles": feats["styles"], "subs": feats["subs"], "hasBA": feats["has_ba"],
            "planInferred": feats.get("planInferred", False),
            "thirsting": feats["thirsting"]}


def _entry(cond, name, args, via, scoped):
    return {"c": cond, "n": name, "g": args, "v": via, "s": 1 if scoped else 0,
            "h": P.boost_text(name, args), "ch": P.cond_human(cond) if cond else ""}


def item_boosts(D, sid):
    """All boosts an item gives, split by the hand it is held in: {'a': always, 'm': main hand only, 'o': off hand}."""
    rec = D.items.get(sid)
    out = {"a": [], "m": [], "o": []}
    if not rec:
        return out
    br = rec.get("boosts_raw") or {}
    is_wpn = bool(rec.get("weapon"))

    def add(key, s, weapon_scope=False, via=None, cond0=None):
        for cond, name, args in parse_boosts(s):
            scoped = weapon_scope and name in ("WeaponEnchantment", "WeaponProperty", "WeaponDamage")
            out[key].append(_entry(cond or cond0, name, args, via, scoped))

    if rec.get("slot") == "Consumable":
        for e in rec.get("effects") or []:
            if e.get("kind") == "status" and str(e.get("source", "")).startswith("OnUse"):
                st = D.stats.get(e.get("id")) or {}
                add("a", st.get("Boosts") or "", via=e.get("name"))
        return out
    add("a", br.get("Boosts", ""), is_wpn)
    add("a", br.get("DefaultBoosts", ""), is_wpn)
    add("m", br.get("BoostsOnEquipMainHand", ""), is_wpn)
    add("o", br.get("BoostsOnEquipOffHand", ""), is_wpn)
    for key, field in (("a", "PassivesOnEquip"), ("m", "PassivesMainHand"), ("o", "PassivesOffHand")):
        for p in split_top(br.get(field, "")):
            st = D.stats.get(p) or {}
            toggled = bool(st.get("ToggleOnFunctors")) or "IsToggled" in str(st.get("Properties") or "")
            # BoostConditions gate every boost of the passive (Helldusk: AC(1) only with the Defence style)
            c0 = (st.get("BoostConditions") or "").strip() or ("toggled passive" if toggled else None)
            add(key, st.get("Boosts") or "", via=p, cond0=c0)
    for s in split_top(br.get("StatusOnEquip", "")):
        st = D.stats.get(s) or {}
        add("a", st.get("Boosts") or "", via=s)
    return out


def collect_boosts(D, set_items, IB):
    """IB = {sid: item_boosts}. -> list of {cond, name, args, src, via, scope, h, ch}."""
    out = []
    for slot in SLOTS:
        it = set_items.get(slot)
        if not it or not it.get("sid") or it["sid"] not in IB:
            continue
        rec = D.items.get(it["sid"]) or {}
        src = rec.get("name") or it["sid"]
        hand = "m" if slot in ("MainHand", "Ranged") else "o" if slot in ("OffHand", "RangedOff") else None
        lst = IB[it["sid"]]["a"] + (IB[it["sid"]][hand] if hand else [])
        for e in lst:
            out.append({"cond": e["c"], "name": e["n"], "args": e["g"], "src": src, "via": e["v"],
                        "scope": slot if e["s"] else None, "h": e["h"], "ch": e["ch"]})
    return out


def num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _letters(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


STYLE_RE = re.compile(r"^\s*(not\s+)?HasPassive\('([A-Za-z_]+)'(?:,\s*context\.Source)?\)\s*$")


def resolve_cond(cond, styles, feats):
    """A single HasPassive('FightingStyle_X' / '<Feat>') condition is decided by the build: True / False / None."""
    m = STYLE_RE.match(cond or "")
    if not m:
        return None
    neg, p = bool(m.group(1)), m.group(2)
    if p.startswith("FightingStyle_"):
        want = P.split_camel(p[len("FightingStyle_"):]).replace("Defense", "Defence").replace("Dueling", "Duelling")
        has = any(_letters(s).startswith(_letters(want)[:6]) for s in styles)
    else:
        want = _letters(P.split_camel(p).replace("Armor", "Armour"))
        has = any(_letters(f.replace("Armor", "Armour")).startswith(want) for f in feats)
    return has != neg


def compute_sheet(D, BI, set_items, IB, level=LEVEL):
    """BI = build_input(...), IB = {sid: item_boosts}. Same rules as sheetFor() in app.js."""
    seq = BI["seq"][:level]
    classes = {}
    for c in seq:
        classes[c] = classes.get(c, 0) + 1
    cls_order = []
    for c in seq:
        if c not in cls_order:
            cls_order.append(c)
    prof_b = 2 + (level - 1) // 4
    prof_set = set(BI["prof"])
    feats_on = [f for f in BI["feats"] if f["lv"] is None or f["lv"] <= level]
    feat_names = [f["n"] for f in feats_on]
    styles = list(BI["styles"])
    base = dict(BI["base"])
    later = [f for f in BI["feats"] if f["lv"] is not None and f["lv"] > level and f["asi"]]
    boosts = collect_boosts(D, set_items, IB)
    for x in boosts:
        r = resolve_cond(x["cond"], styles, feat_names) if x["cond"] else None
        if r is True:
            x["cond"] = None
        elif r is False:
            x["never"] = True
    uncond = [x for x in boosts if not x["cond"]]
    cond = [x for x in boosts if x["cond"] and not x.get("never")]
    F = {}

    # ---- abilities
    ab_f = {}
    for k in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        v = BI["base"][k]
        minus = sum(f["asi"].get(k, 0) for f in later)
        base[k] = v - minus
        ab_f[k] = (["%d planned for level %d (build plan)" % (v, LEVEL)] if not minus else
                   ["%d planned for level %d, minus %d from ability improvements after level %d = %d" % (
                       v, LEVEL, minus, level, v - minus)])
    ab = dict(base)
    for x in uncond:
        if x["name"] == "Ability" and x["args"] and x["args"][0] in ABIL:
            k = ABIL[x["args"][0]]
            n = num(x["args"][1]) if len(x["args"]) > 1 else None
            cap = num(x["args"][2]) if len(x["args"]) > 2 else 30
            if n:
                new = min(ab[k] + n, max(cap or 30, ab[k]))
                ab_f[k].append("%+d %s -> %d%s" % (n, x["src"], new, " (max %d)" % cap if len(x["args"]) > 2 else ""))
                ab[k] = new
    for x in uncond:
        if x["name"] == "AbilityOverrideMinimum" and x["args"] and x["args"][0] in ABIL:
            k = ABIL[x["args"][0]]
            n = num(x["args"][1]) if len(x["args"]) > 1 else None
            if n and n > ab[k]:
                ab_f[k].append("%s sets it to %d" % (x["src"], n))
                ab[k] = n
            elif n:
                ab_f[k].append("%s (at least %d) - no change" % (x["src"], n))
    M = {k: mod(v) for k, v in ab.items()}
    names = {ABIL_NAMES[k] + "Modifier": v for k, v in M.items()}
    names.update({"ProficiencyBonus": prof_b, "Level": level, "CharacterLevel": level})

    def val(expr):
        n_ = num(expr)
        return n_ if n_ is not None and re.fullmatch(r"-?\d+(\.\d+)?", expr.strip()) else safe_eval(expr, names)

    sub_cls = {s["cls"]: s["n"] for s in BI["subs"]}
    hexblade = sub_cls.get("Warlock") == "Hexblade" and classes.get("Warlock", 0) > 0
    draconic = sub_cls.get("Sorcerer") == "Draconic" and classes.get("Sorcerer", 0) > 0

    # ---- HP
    hp = 0
    hp_f = []
    first = True
    for c in cls_order:
        die = HIT_DIE.get(c, 8)
        lv = classes[c]
        if first:
            hp += die + M["CON"] + (lv - 1) * (die // 2 + 1 + M["CON"])
            hp_f.append("%s 1: d%d max %d + CON %s; %s 2-%d: %d x (%d + CON %s)" % (
                c, die, die, fmt_mod(M["CON"]), c, lv, lv - 1, die // 2 + 1, fmt_mod(M["CON"])) if lv > 1 else
                "%s 1: d%d max %d + CON %s" % (c, die, die, fmt_mod(M["CON"])))
            first = False
        else:
            hp += lv * (die // 2 + 1 + M["CON"])
            hp_f.append("%s x%d: %d x (%d + CON %s)" % (c, lv, lv, die // 2 + 1, fmt_mod(M["CON"])))
    if draconic:
        hp += classes.get("Sorcerer", 0)
        hp_f.append("Draconic Resilience +%d" % classes.get("Sorcerer", 0))
    if any(f.startswith("Tough") for f in feat_names):
        hp += 2 * level
        hp_f.append("Tough +%d" % (2 * level))
    for x in uncond:
        if x["name"] == "IncreaseMaxHP" and x["args"]:
            n = val(x["args"][0])
            if n:
                hp += n
                hp_f.append("%+d %s" % (n, x["src"]))
    F["hp"] = hp_f

    # ---- AC
    body = set_items.get("Breast") or {}
    brec = D.items.get(body.get("sid") or "") or {}
    ba_ = brec.get("armour") or {}
    cat = ba_.get("category")
    ac_f = []
    if cat in ("Light", "Medium", "Heavy") and ba_.get("ac") is not None:
        cap = ba_.get("dex_cap")
        if cat == "Light":
            dx = M["DEX"]
        elif cat == "Medium":
            dx = min(M["DEX"], cap if cap is not None else 2)
        else:
            dx = 0
        ac = ba_["ac"] + dx
        ac_f.append("%s %s armour %d + DEX %s%s" % (brec.get("name"), cat.lower(), ba_["ac"], fmt_mod(dx),
                                                    " (max %s)" % (cap if cap is not None else 2) if cat == "Medium" else
                                                    " (none)" if cat == "Heavy" else ""))
        armoured = True
    else:
        armoured = False
        opts = [(10 + M["DEX"], "10 + DEX %s (no armour)" % fmt_mod(M["DEX"]))]
        if "Barbarian" in classes:
            opts.append((10 + M["DEX"] + M["CON"], "Unarmoured Defence 10 + DEX %s + CON %s" % (fmt_mod(M["DEX"]),
                                                                                                fmt_mod(M["CON"]))))
        if "Monk" in classes:
            opts.append((10 + M["DEX"] + M["WIS"], "Unarmoured Defence 10 + DEX + WIS"))
        if draconic:
            opts.append((13 + M["DEX"], "Draconic Resilience 13 + DEX %s" % fmt_mod(M["DEX"])))
        ac, txt = max(opts)
        ac_f.append(txt + (" (%s is clothing)" % brec.get("name") if brec else ""))
    off = set_items.get("OffHand") or {}
    orec = D.items.get(off.get("sid") or "") or {}
    oa = orec.get("armour") or {}
    if oa.get("shield"):
        ac += oa.get("ac") or 2
        ac_f.append("%+d shield %s" % (oa.get("ac") or 2, orec.get("name")))
    for x in uncond:
        if x["name"] == "AC" and x["args"]:
            n = val(x["args"][0])
            if n:
                ac += n
                ac_f.append("%+d %s" % (n, x["src"]))
    if armoured and any(s.startswith("Defence") for s in styles):
        ac += 1
        ac_f.append("+1 Fighting Style: Defence")
    F["ac"] = ac_f

    # ---- initiative, speed
    ini = M["DEX"]
    ini_f = ["DEX %s" % fmt_mod(M["DEX"])]
    if any(f.startswith("Alert") for f in feat_names):
        ini += 5
        ini_f.append("+5 Alert (feat in the build plan)")
    for x in uncond:
        if x["name"] == "Initiative" and x["args"]:
            n = val(x["args"][0])
            if n:
                ini += n
                ini_f.append("%+d %s" % (n, x["src"]))
    F["init"] = ini_f
    spd = 9.0
    spd_f = ["9 m base (all origin races)"]
    if classes.get("Barbarian", 0) >= 5 and cat != "Heavy":
        spd += 3
        spd_f.append("+3 m Fast Movement (Barbarian 5)")
    for x in uncond:
        if x["name"] == "ActionResource" and x["args"] and x["args"][0] == "Movement":
            try:
                n = float(x["args"][1])
            except (IndexError, ValueError):
                n = 0
            if n:
                spd += n
                spd_f.append("%+g m %s" % (n, x["src"]))
    F["speed"] = spd_f

    # ---- resistances (one row per damage type; every source listed)
    res = []

    def add_res(t, lvl, src):
        for r in res:
            if r["t"] == t:
                if src not in r["src"].split("; "):
                    r["src"] += "; " + src
                if lvl == "Immune":
                    r["l"] = "Immune"
                return
        res.append({"t": t, "l": lvl, "src": src})
    for t, lvl, src in RACE_RESIST.get(BI["race"], []):
        add_res(t, lvl, src)
    for x in uncond:
        if x["name"] == "Resistance" and len(x["args"]) >= 2:
            types = [t.strip() for t in re.split(r"[|,]", x["args"][0])]
            for t in types:
                if t in DMG_TYPES or t in ("All", "Physical"):
                    add_res(t, x["args"][1], x["src"])
    cres = []
    for x in cond:
        if x["name"] == "Resistance" and len(x["args"]) >= 2:
            cres.append({"t": x["args"][0], "l": x["args"][1], "src": x["src"], "cond": x["ch"] or "in some situations"})
    if "Barbarian" in classes:
        cres.append({"t": "Bludgeoning, Piercing, Slashing", "l": "Resistant", "src": "Rage (Barbarian)",
                     "cond": "while raging"})

    # ---- attack rolls
    roll_all = [x for x in uncond if x["name"] == "RollBonus" and x["args"]]
    flat_dmg = [x for x in uncond if x["name"] == "DamageBonus" and x["args"]]
    char_dice = [x for x in uncond if x["name"] in ("CharacterWeaponDamage",) and x["args"]]

    def attack_row(slot):
        it = set_items.get(slot) or {}
        rec = D.items.get(it.get("sid") or "")
        if not rec or not rec.get("weapon"):
            return None
        w = rec["weapon"]
        props = w.get("properties") or []
        ranged = rec.get("slot") == "Ranged Main Weapon"
        offhand = slot in ("OffHand", "RangedOff")
        wprof = set(w.get("proficiency") or [])
        proficient = bool(wprof & prof_set) or not wprof
        if ranged:
            ak, ak_txt = "DEX", "DEX (ranged)"
        elif "Finesse" in props:
            ak = "DEX" if M["DEX"] >= M["STR"] else "STR"
            ak_txt = "%s (finesse, higher of STR/DEX)" % ak
        else:
            ak, ak_txt = "STR", "STR (melee)"
        if hexblade and proficient and M["CHA"] > M[ak]:
            ak, ak_txt = "CHA", "CHA (Hex Warrior, Hexblade)"
        am = M[ak]
        ench = w.get("enchantment") or 0
        hit = am + (prof_b if proficient else 0) + ench
        f = ["%s %s" % (ak_txt, fmt_mod(am)), ("proficiency +%d" % prof_b) if proficient else "not proficient (+0)"]
        if ench:
            f.append("enchantment %+d" % ench)
        kinds = {"Attack", "WeaponAttack", "MeleeWeaponAttack" if not ranged else "RangedWeaponAttack"}
        dice_bonus = []
        for x in roll_all:
            if x["args"][0] in kinds:
                n = val(x["args"][1]) if len(x["args"]) > 1 else None
                if n is not None and n != 0:
                    hit += n
                    f.append("%+d %s" % (n, x["src"]))
                elif len(x["args"]) > 1 and DICE_RE.match(x["args"][1].lstrip("+-")):
                    dice_bonus.append(x["args"][1] + " " + x["src"])
        if ranged and any(s.startswith("Archery") for s in styles):
            hit += 2
            f.append("+2 Fighting Style: Archery")
        two_h = "Twohanded" in props
        use_ver = w.get("versatile") and not two_h and not offhand and not (set_items.get("OffHand") or {}).get("sid")
        dice = w.get("versatile") if use_ver else w.get("damage")
        dparts = [(dice, w.get("damage_type"))]
        flat = ench
        df = ["%s %s%s" % (dice, w.get("damage_type"), " (versatile, two hands)" if use_ver else "")]
        if not offhand or am < 0 or any(s.startswith("Two-Weapon") for s in styles):
            flat += am
            df.append("%s %s" % (ak, fmt_mod(am)))
        else:
            df.append("off hand: no ability modifier (no Two-Weapon Fighting style)")
        if ench:
            df.append("enchantment %+d" % ench)
        if (not ranged and not offhand and not two_h and not use_ver and any(s.startswith("Duel") for s in styles)
                and not D.items.get((set_items.get("OffHand") or {}).get("sid") or "", {}).get("weapon")):
            flat += 2
            df.append("+2 Fighting Style: Duelling")
        for e in w.get("extra_damage") or []:
            m = re.match(r"(\d+d\d+)\s+(\w+)", str(e))
            if m:
                dparts.append((m.group(1), m.group(2)))
                df.append("%s %s (weapon)" % (m.group(1), m.group(2)))
        for x in flat_dmg:
            n = val(x["args"][0])
            t = x["args"][1] if len(x["args"]) > 1 else None
            if n:
                flat += n
                df.append("%+d %s%s" % (n, x["src"], " " + t if t else ""))
        for x in char_dice + [y for y in uncond if y["name"] == "WeaponDamage" and y["scope"] == slot]:
            d0 = x["args"][0]
            t = x["args"][1] if len(x["args"]) > 1 else w.get("damage_type")
            if DICE_RE.match(d0):
                dparts.append((d0, t))
                df.append("%s %s %s" % (d0, t, x["src"]))
        cnotes = []
        for x in cond:
            c = x["cond"] or ""
            if x["name"] not in ("DamageBonus", "WeaponDamage", "CharacterWeaponDamage", "RollBonus") or \
                    x["scope"] not in (None, slot):
                continue
            simple = re.fullmatch(r"\s*(not\s+)?Is(Ranged|Melee)(Weapon)?Attack\(\)\s*", c)
            if simple:
                kind_ranged = simple.group(2) == "Ranged"
                applies = (kind_ranged == ranged) != bool(simple.group(1))
                if not applies:
                    continue
                where = "only %s attacks" % ("ranged" if ranged else "melee")
                a0 = x["args"][0] if x["args"] else ""
                if x["name"] == "RollBonus":
                    if a0 in kinds and len(x["args"]) > 1 and val(x["args"][1]):
                        hit += val(x["args"][1])
                        f.append("%+d %s (%s)" % (val(x["args"][1]), x["src"], where))
                        continue
                elif DICE_RE.match(a0):
                    t = x["args"][1] if len(x["args"]) > 1 else w.get("damage_type")
                    dparts.append((a0, t))
                    df.append("%s %s %s (%s)" % (a0, t, x["src"], where))
                    continue
                elif val(a0):
                    flat += val(a0)
                    df.append("%+d %s (%s)" % (val(a0), x["src"], where))
                    continue
            cnotes.append("%s (%s) - %s" % (x["h"], x["ch"] or "in some situations", x["src"]))
        avg = sum(dice_avg(d) for d, _ in dparts) + flat
        dmg_txt = " + ".join([dparts[0][0] + ("%+d" % flat if flat else "") + " " + (dparts[0][1] or "")] +
                             ["%s %s" % (d, t) for d, t in dparts[1:]])
        return {"slot": slot, "n": rec.get("name"), "sid": it.get("sid"), "hit": hit, "hitf": f, "dmg": dmg_txt,
                "avg": round(avg, 1), "dmgf": df, "dt": dparts[0][1], "cond": cnotes, "dice": dice_bonus,
                "ranged": bool(ranged), "off": offhand}

    attacks = [r for r in (attack_row(s) for s in ("MainHand", "OffHand", "Ranged", "RangedOff")) if r]
    n_att, att_f = 1, "1 attack per action"
    if classes.get("Fighter", 0) >= 11:
        n_att, att_f = 3, "Fighter 11: Improved Extra Attack"
    elif any(classes.get(c, 0) >= 5 for c in ("Fighter", "Barbarian", "Paladin", "Ranger", "Monk")):
        n_att, att_f = 2, "Extra Attack (level 5 of a martial class)"
    elif classes.get("Warlock", 0) >= 5 and (BI["thirsting"] or hexblade):
        n_att, att_f = 2, "Thirsting Blade / Pact of the Blade (Warlock 5+, assumed for blade builds)"
    elif classes.get("Bard", 0) >= 6 and sub_cls.get("Bard") == "Swords":
        n_att, att_f = 2, "Extra Attack (College of Swords 6)"
    elif classes.get("Wizard", 0) >= 6 and sub_cls.get("Wizard") == "Bladesinging":
        n_att, att_f = 2, "Extra Attack (Bladesinging 6)"

    # ---- spellcasting: a ranged and a melee spell attack (items often give both; each counts once)
    casters = [(c, CAST_ABIL[c]) for c in cls_order if c in CAST_ABIL]
    if sub_cls.get("Fighter") == "Eldritch Knight" and classes.get("Fighter", 0) >= 3:
        casters.append(("Fighter", "INT"))
    if sub_cls.get("Rogue") == "Arcane Trickster" and classes.get("Rogue", 0) >= 3:
        casters.append(("Rogue", "INT"))
    spell = None
    if casters:
        c, ak = max(casters, key=lambda t: (classes.get(t[0], 0), M[t[1]]))
        dc = 8 + prof_b + M[ak]
        dcf = ["8 + proficiency %d + %s %s (%s)" % (prof_b, ak, fmt_mod(M[ak]), c)]
        sa = {"r": prof_b + M[ak], "m": prof_b + M[ak]}
        saf = {"r": ["proficiency %d + %s %s" % (prof_b, ak, fmt_mod(M[ak]))],
               "m": ["proficiency %d + %s %s" % (prof_b, ak, fmt_mod(M[ak]))]}
        for x in uncond:
            if x["name"] == "SpellSaveDC" and x["args"]:
                n = val(x["args"][0])
                if n:
                    dc += n
                    dcf.append("%+d %s" % (n, x["src"]))
            if x["name"] == "RollBonus" and x["args"] and x["args"][0] in ("SpellAttack", "MeleeSpellAttack",
                                                                           "RangedSpellAttack", "Attack"):
                n = val(x["args"][1]) if len(x["args"]) > 1 else None
                if n:
                    k = x["args"][0]
                    for hand in (("r", "m") if k in ("SpellAttack", "Attack") else
                                 ("r",) if k == "RangedSpellAttack" else ("m",)):
                        sa[hand] += n
                        saf[hand].append("%+d %s" % (n, x["src"]))
        spell = {"abil": ak, "cls": c, "dc": dc, "dcf": dcf, "atk": sa["r"], "atkf": saf["r"], "atkM": sa["m"],
                 "atkMf": saf["m"]}

    # ---- everything else, in plain words (not added to the numbers)
    other = []
    for x in uncond:
        if x["name"] in ("Ability", "AbilityOverrideMinimum", "IncreaseMaxHP", "AC", "Initiative", "Resistance",
                         "SpellSaveDC", "WeaponEnchantment", "WeaponProperty", "UnlockSpell", "UnlockInterrupt",
                         "ActionResource", "DamageBonus", "CharacterWeaponDamage", "WeaponDamage", "CriticalHit",
                         "HiddenDuringCinematic", "ItemReturnToOwner", "CannotBeDisarmed", "ObjectSize",
                         "ScaleMultiplier", "CarryCapacityMultiplier", "WeightCategory", "Weight"):
            continue
        if x["name"] == "RollBonus" and x["args"] and x["args"][0] in ("Attack", "WeaponAttack", "MeleeWeaponAttack",
                                                                       "RangedWeaponAttack", "SpellAttack",
                                                                       "MeleeSpellAttack", "RangedSpellAttack"):
            continue
        if x["h"]:
            other.append("%s - %s" % (x["h"], x["src"]))
    conds = []
    for x in cond:
        if x["h"]:
            conds.append("%s (%s) - %s" % (x["h"], x["ch"] or "in some situations", x["src"]))

    return {
        "level": level, "prof": prof_b,
        "ab": ab, "abBase": base, "abF": ab_f, "mods": M,
        "hp": hp, "ac": ac, "init": ini, "speed": spd, "F": F,
        "attacks": attacks, "nAtt": n_att, "nAttF": att_f, "spell": spell,
        "res": res, "cres": cres, "other": sorted(set(other)), "conds": sorted(set(conds)),
        "feats": feat_names, "styles": styles, "classes": [[c, classes[c]] for c in cls_order],
    }


# ------------------------------------------------------------------------------------------------ captures
def find_captures(set_id, char, act):
    """shots/sets/<char>_<act>_<setid>_{model,sheet}.png (setid = full id, or without the '<char>.' prefix,
    dots or underscores)."""
    found = {}
    if not os.path.isdir(SHOTS):
        return found
    short = set_id.split(".", 1)[1] if set_id.startswith(char + ".") else set_id
    variants = {set_id, short, set_id.replace(".", "_"), short.replace(".", "_")}
    for kind in ("model", "sheet"):
        for v in variants:
            for ext in ("png", "jpg", "webp"):
                p = os.path.join(SHOTS, "%s_%s_%s_%s.%s" % (char, act, v, kind, ext))
                if os.path.exists(p):
                    found[kind] = p
                    break
            if kind in found:
                break
    return found


CAP_STEPS = [(1.0, 72), (0.8, 66), (0.65, 60), (0.5, 55), (0.4, 50), (0.3, 45)]
CAP_BOX = {"model": (520, 700), "sheet": (900, 1000)}


def embed_captures(A, jobs, budget):
    """jobs = [(set_dict, kind, path)]. Picks the largest size/quality step whose total fits the byte budget
    (base64 counted), then registers the images. Returns (step, bytes)."""
    from PIL import Image
    if not jobs:
        return None, 0
    for scale, q in CAP_STEPS:
        total = 0
        enc = []
        for sd, kind, path in jobs:
            st = os.stat(path)
            box = tuple(int(v * scale) for v in CAP_BOX[kind])
            key = "cap:%s:%d:%d:%s:%d" % (os.path.basename(path), st.st_size, int(st.st_mtime), box, q)
            k = A.add_image(key, lambda path=path: Image.open(path).convert("RGBA"), box, quality=q)
            if k:
                total += len(A.uris[k])
                enc.append((sd, kind, k))
        if total <= budget or (scale, q) == CAP_STEPS[-1]:
            for sd, kind, k in enc:
                sd["cap"][kind] = k
            # forget the larger attempts so they are not embedded
            keep = {k for _, _, k in enc}
            for k in [k for k in A.uris if k.startswith("cap:") and k not in keep]:
                del A.uris[k]
            return (scale, q), total
    return None, 0


# ------------------------------------------------------------------------------------------------ page helpers
THEME_LABEL = {"top": "best overall", "weapon_dmg": "damage", "spell_dc": "spell DC", "ac": "defence",
               "crit": "critical hits", "stealth": "stealth", "reverberation": "Reverberation",
               "initiative": "initiative", "weapon_atk": "accuracy", "spell_slot": "spell slots", "throw": "throwing",
               "frost": "frost"}


def theme_label(t):
    if not t:
        return ""
    if t in THEME_LABEL:
        return THEME_LABEL[t]
    m = re.match(r"dmg_(\w+)", t)
    if m:
        return m.group(1) + " damage"
    return t.replace("_", " ")


def build_short(name):
    """'Throwzerker (Berserker Barbarian 10 / Fighter 2)' -> 'Throwzerker'; class levels dropped."""
    n = re.split(r" \(| - ", name or "")[0]
    n = re.sub(r"\s*\b\d+\b", "", n)
    return re.sub(r"\s+", " ", n).strip(" /")


def unique_names(lst, builds):
    """F9: a set name is unique within a character and act ('Shadow Step - Thief Rogue')."""
    def groups():
        g = {}
        for s_ in lst:
            g.setdefault(s_["n"].lower(), []).append(s_)
        return [v for v in g.values() if len(v) > 1]
    for grp in groups():
        for s_ in grp:
            s_["n"] = "%s · %s" % (s_["n"], (builds.get(s_["b"]) or {}).get("short") or s_["b"])
    for grp in groups():
        for s_ in grp:
            s_["n"] = "%s · %s" % (s_["n"], s_.get("tl") or ("community" if s_["o"] == "research" else "auto"))
    for grp in groups():
        for i, s_ in enumerate(grp[1:], 2):
            s_["n"] = "%s %s" % (s_["n"], "I" * i if i < 4 else i)


# route through each act (general order of the regions in a playthrough); label shown in the shopping list
ROUTE = [("Nautiloid", 1, "Nautiloid"), ("Emerald Grove", 1, "Emerald Grove"),
         ("wilderness", 1, "Around the Emerald Grove"), ("Blighted Village", 1, "Blighted Village"),
         ("Risen Road|Waukeen|Zhentarim", 1, "Risen Road and Waukeen's Rest"),
         ("Goblin Camp|Shattered Sanctum", 1, "Goblin Camp"), ("Underdark", 1, "Underdark"),
         ("Grymforge", 1, "Grymforge"), ("Rosymorn|Cr[eè]che", 1, "Mountain pass and the Crèche"),
         ("Origin story", 0, "Companion quests"),
         ("Shadow-Cursed", 2, "Shadow-Cursed Lands"), ("Last Light", 2, "Last Light Inn"),
         ("Reithwin", 2, "Reithwin Town"), ("Moonrise", 2, "Moonrise Towers"), ("Gauntlet of Shar", 2, "Gauntlet of Shar"),
         ("Rivington|Wyrm|outskirts|Smugglers", 3, "Rivington and Wyrm's Crossing"), ("Chult", 3, "Jungle of Chult (dream)"),
         ("Lower City|Baldur's Gate|Sorcerous Sundries|Catacombs", 3, "Lower City"),
         ("Upper City|High Hall", 3, "Upper City and the High Hall")]


def region_of(src, how, act):
    """-> [route index, label]. The best source's region; when that lies in a later act than the set (an
    alternative source), the first route place named in the how-to text that fits the act."""
    reg = ((src or {}).get("region") or "").split(":")[0]
    for i, (rx, a, label) in enumerate(ROUTE):
        if re.search(rx, reg) and (a == 0 or a <= act):
            return [i, label]
    best = None
    for i, (rx, a, label) in enumerate(ROUTE):
        if a and a <= act:
            m = re.search(rx, how or "")
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), i, label)
    if best:
        return [best[1], best[2]]
    return [99, "Other places"]


CRIME_RE = re.compile(r"\btheft\b|\bsteal|pickpocket|non-hostile|\bneutral\b|has to die|must kill|requires killing|"
                      r"\bmurder\b|kills a neutral", re.I)
MISS_RE = re.compile(r"missable|get it first|buy before|before (?:the |assaulting |raiding |siding )|despawns|"
                     r"only one copy|choose one|one of three|1 of 3|mutually exclusive|closes shop", re.I)


WT_TAG = {"story lock": "story", "theft-kill": "crime", "missable": "miss", "party conflict": "party"}


def wt_tags(types):
    """Scorer warn_types -> page tags (story / crime / miss / party); 'tip' is a mild note, not counted."""
    return sorted({WT_TAG[t] for t in (types or []) if t in WT_TAG})


def entry_tags(codes, warn):
    """Severity of a slot's notes (F6): story = needs a story choice, crime = theft / killing a neutral,
    miss = missable or lost on a later choice. Everything else is a mild tip (not counted)."""
    t = set()
    for c in codes:
        if c == "durge" or c.startswith(("path:", "origin:", "party:")):
            t.add("story")
        if c.startswith("!path:") or c.startswith("timing:"):
            t.add("miss")
    if CRIME_RE.search(warn or ""):
        t.add("crime")
    if MISS_RE.search(warn or ""):
        t.add("miss")
    if re.search(r"story choice", warn or "", re.I):
        t.add("story")
    return sorted(t)


# ------------------------------------------------------------------------------------------------ main build
def build_payload(args, A=None):
    """Everything the page shows (no html yet). A = the asset collector (Assets: embedded WebP; the ship build passes
    its own collector that only records which game files to read). Returns (payload, A, meta)."""
    t0 = time.time()
    D = Data()
    A = A or Assets()
    ui = {}
    for k, (path, size) in UI_ART.items():
        q = 62 if k == "bg" else 90 if k in ("pane", "tt_bg") else 85
        key = A.game("ui:" + k, "Public/Game/GUI/Assets/%s.DDS" % path, size, quality=q)
        if key:
            ui[k] = key
    # race icons (class icons: after the sets, only the used ones)
    for race, icon in RACE_ICON.items():
        if A.game("race:" + icon, "Public/Game/GUI/Assets/CC/icons_races/%s.DDS" % icon, (72, 72)):
            ui["race_" + race] = "race:" + icon
    for ch, bg in ORIGIN_BG.items():
        if A.game("bgicon:" + bg, "Public/Game/GUI/Assets/CC/icons_backgrounds/%s.DDS" % bg, (96, 96)):
            ui["bgicon_" + ch] = "bgicon:" + bg

    items = {}

    def need(sid):
        if sid and sid not in items:
            items[sid] = item_view(D, A, sid)

    chars = []
    ITEM_TAGS = {}
    n_sets = 0
    cap_jobs = []
    ref_sheets = {}
    IB = {}
    for c in CHARS:
        d = D.chars.get(c)
        if not d:
            continue
        cv = {"id": c, "n": d.get("name") or c, "race": d.get("race"), "portrait": origin_portrait(A, c),
              "builds": [], "sets": {"1": [], "2": [], "3": []}}
        ba_pick = D.ba.get("_origins", {}).get(c)
        if ba_pick not in (d.get("builds") or {}):
            ba_pick = None
        for bk, b in (d.get("builds") or {}).items():
            BI = build_input(D, c, d.get("race"), bk, b)
            cv["builds"].append({"id": bk, "n": b.get("name") or bk, "o": b.get("origin"),
                                 "about": P.scrub(b.get("about")), "note": P.scrub(b.get("note")),
                                 "classes": b.get("classes") or {}, "subs": BI["subs"], "short": build_short(b.get("name") or bk),
                                 "bi": BI})
            if ba_pick is None and b.get("origin") in ("BuildAdvisor", "campaign"):
                ba_pick = bk
            bitems = b.get("items") or {}
            for act, sets in (b.get("sets") or {}).items():
                for s in sets:
                    its = s.get("items") or {}
                    score = 0.0
                    slots = {}
                    for sl, it in its.items():
                        if not it or not it.get("sid"):
                            continue
                        need(it["sid"])
                        tot = ((bitems.get(it["sid"]) or {}).get("total") or {}).get(str(act))
                        if isinstance(tot, (int, float)):
                            score += tot
                        fb = it.get("fallback")
                        fb_sid = fb.get("sid") if isinstance(fb, dict) else fb if isinstance(fb, str) else None
                        pa = it.get("party_alt")
                        pa_sid = pa.get("sid") if isinstance(pa, dict) else pa if isinstance(pa, str) else None
                        need(fb_sid)
                        fb_empty = isinstance(fb, dict) and bool(fb.get("empty"))
                        if fb_empty:
                            fb_sid = P.scrub(fb.get("name"))   # "leave it empty: ..." (text, the slot stays empty)
                        need(pa_sid)
                        codes = list(it.get("cond") or [])
                        warn = P.scrub(P.drop_dups(clean(it.get("warning")), codes))
                        e = {"sid": it["sid"], "core": bool(it.get("core")), "act": it.get("act"),
                             "how": P.scrub(clean(it.get("how"))), "warn": warn,
                             "cond": [{"c": x, "t": cond_text(x)} for x in codes],
                             "own": bool(it.get("owned_only")), "fb": fb_sid, "pa": pa_sid,
                             "owner": it.get("owner") or [],
                             "reg": region_of(it.get("best_source"), it.get("how"), int(act)),
                             "tags": entry_tags(codes, clean(it.get("warning"))),
                             "why": P.why_text(clean((bitems.get(it["sid"]) or {}).get("why")))}
                        if fb_empty:
                            e["fbE"] = 1
                        # round 5 data: note severity / types, earlier-act and Dark-Urge-only alternatives
                        if it.get("severity"):
                            e["sev"] = it["severity"]
                            e["wt"] = list(it.get("warn_types") or [])
                        if "warn_types" in it:   # the scorer's severity types replace the text matching (round 5)
                            e["tags"] = wt_tags(it.get("warn_types"))
                        for k_alt, f_alt in (("owned_alt", "oa"), ("cond_alt", "ca")):
                            x_alt = it.get(k_alt)
                            if isinstance(x_alt, dict) and x_alt.get("sid"):
                                e[f_alt] = x_alt["sid"]
                                need(x_alt["sid"])
                                if f_alt == "oa":   # how much better the owned item scores here ("+N")
                                    t_o = ((bitems.get(x_alt["sid"]) or {}).get("total") or {}).get(str(act))
                                    t_m = ((bitems.get(it["sid"]) or {}).get("total") or {}).get(str(act))
                                    if isinstance(t_o, (int, float)) and isinstance(t_m, (int, float)) and t_o > t_m:
                                        e["oaGain"] = round(t_o - t_m, 1)
                        # where-to-get info for every alternative (the page looks it up by item in DATA.E)
                        for k_alt in ("fallback", "party_alt", "owned_alt", "cond_alt"):
                            x_alt = it.get(k_alt)
                            if isinstance(x_alt, dict) and x_alt.get("sid") and x_alt["sid"] not in ALT_INFO:
                                codes_a = list(x_alt.get("cond") or [])
                                ALT_INFO[x_alt["sid"]] = {
                                    "sid": x_alt["sid"], "core": False, "act": x_alt.get("act"),
                                    "how": P.scrub(clean(x_alt.get("how"))),
                                    "warn": P.scrub(P.drop_dups(clean(x_alt.get("warning")), codes_a)),
                                    "cond": [{"c": y, "t": cond_text(y)} for y in codes_a],
                                    "own": bool(x_alt.get("owned_only")), "fb": None, "pa": None, "owner": [],
                                    "reg": region_of(x_alt.get("best_source"), x_alt.get("how"), int(act)),
                                    "tags": (wt_tags(x_alt.get("warn_types")) if "warn_types" in x_alt
                                             else entry_tags(codes_a, clean(x_alt.get("warning")))),
                                    "sev": x_alt.get("severity"), "wt": list(x_alt.get("warn_types") or []),
                                    "why": ""}
                        # pass through any new simple fields the scorer adds later
                        for k2, v2 in it.items():
                            if k2 not in ("sid", "name", "core", "act", "how", "warning", "cond", "owned_only",
                                          "fallback", "party_alt", "owner", "best_source", "severity", "warn_types",
                                          "owned_alt", "cond_alt") and isinstance(
                                    v2, (str, int, float, bool)) and v2 not in ("", None):
                                e.setdefault("x", {})[k2] = v2
                        slots[sl] = e
                        ITEM_TAGS.setdefault(it["sid"], {"cc": set(), "tg": set()})
                        ITEM_TAGS[it["sid"]]["cc"].update(codes)
                        ITEM_TAGS[it["sid"]]["tg"].update(e["tags"])
                    sid_ = s.get("id") or "%s.%s.a%s.%d" % (c, bk, act, len(cv["sets"][str(act)]) + 1)
                    for sid2 in [x["sid"] for x in its.values() if x and x.get("sid")]:
                        if sid2 not in IB:
                            IB[sid2] = item_boosts(D, sid2)
                    ref_sheets[sid_] = {str(lv): compute_sheet(D, BI, its, IB, lv) for lv in (5, 8, 12)}
                    caps = {}
                    cap_paths = find_captures(sid_, c, act)
                    set_fb = s.get("fallback") or {}
                    for v_ in set_fb.values():
                        need(v_ if isinstance(v_, str) else (v_ or {}).get("sid"))
                    item_names = {(D.items.get(x["sid"]) or {}).get("name") for x in its.values() if x and x.get("sid")}
                    notes = [P.validation(clean(w)) for w in (s.get("validation") or [])]
                    # set warnings repeat the per-item ones ("Item: text"); keep only the others
                    notes += [P.scrub(clean(w)) for w in (s.get("warnings") or [])
                              if clean(w).split(":")[0].strip() not in item_names]
                    cv["sets"][str(act)].append({
                        "id": sid_, "n": P.set_name(s.get("name") or sid_), "b": bk, "act": int(act),
                        "o": s.get("origin"), "theme": s.get("theme"), "tl": theme_label(s.get("theme")),
                        "why": P.set_why(clean(s.get("why") or s.get("auto_why"))),
                        "notes": [x for x in notes if x],
                        "fallback": {k: (v_ if isinstance(v_, str) else (v_ or {}).get("sid")) for k, v_ in set_fb.items()},
                        "slots": slots, "score": round(score, 2), "cap": caps,
                    })
                    for kind, p in cap_paths.items():
                        cap_jobs.append((cv["sets"][str(act)][-1], kind, p))
                    n_sets += 1
        cv["main"] = ba_pick
        # order: main build first, then community sets, then the summed item score (the page labels the first
        # three "Main pick / Alternative 1 / 2" - an ordering rule, explained in its legend)
        for act, lst in cv["sets"].items():
            lst.sort(key=lambda s: (0 if s["b"] == ba_pick else 1, 0 if s["o"] == "research" else 1, -s["score"]))
            for i, s in enumerate(lst):
                s["rank"] = i + 1
            unique_names(lst, {b_["id"]: b_ for b_ in cv["builds"]})
        chars.append(cv)
    for sid, t in ITEM_TAGS.items():
        if sid in items:
            items[sid]["cc"] = sorted(t["cc"])
            items[sid]["tg"] = sorted(t["tg"])
    for sid, bz in IB.items():
        if sid in items:
            items[sid]["bz"] = {k: v for k, v in bz.items() if v}
    # the alternatives (fallback / party) need their boosts too: the page swaps them in
    for sid in list(items):
        if sid not in IB and sid in D.items:
            bz = item_boosts(D, sid)
            items[sid]["bz"] = {k: v for k, v in bz.items() if v}
    # class / subclass icons: only the ones a build uses
    used_cls = set()
    for cv in chars:
        for b_ in cv["builds"]:
            used_cls.update(b_["classes"].keys())
            used_cls.update(s_["icon"] for s_ in b_["subs"] if s_.get("icon"))
    for c_ in sorted(used_cls):
        if A.game("cls:" + c_, "Public/Game/GUI/Assets/ClassIcons/%s.DDS" % c_, (72, 72)):
            ui["cls_" + c_] = "cls:" + c_
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "sheets_ref.json"), "w", encoding="utf-8") as f:
        json.dump(ref_sheets, f, ensure_ascii=False, separators=(",", ":"))

    # dedupe the per-slot entries (the same item + text repeats across many sets): sets point into DATA.E
    etab, eidx = [], {}
    for cv in chars:
        for lst in cv["sets"].values():
            for s in lst:
                for sl, e in list(s["slots"].items()):
                    k = json.dumps(e, sort_keys=True, ensure_ascii=False)
                    if k not in eidx:
                        eidx[k] = len(etab)
                        etab.append(e)
                    s["slots"][sl] = eidx[k]
    # info-only entries for alternatives that are never a main pick (INFO in app.js is built from DATA.E)
    have = {e["sid"] for e in etab}
    for sid_a, e_a in sorted(ALT_INFO.items()):
        if sid_a not in have:
            etab.append(e_a)
    payload = {"generated": time.strftime("%Y-%m-%d %H:%M"), "level": LEVEL, "actLevel": ACT_LEVEL, "chars": chars,
               "items": items, "E": etab, "ui": ui, "slots": SLOTS,
               "rules": {"hitDie": HIT_DIE, "castAbil": CAST_ABIL, "raceRes": RACE_RESIST, "dmgTypes": DMG_TYPES,
                         "abil": ABIL, "asiLevels": ASI_LEVELS},
               "rarityColor": {"Common": "#E6DBC2", "Uncommon": "#00be3a", "Rare": "#00c0ff",
                               "VeryRare": "#d1007c", "Legendary": "#d18f00", "Story": "#ff5a00"}}
    return payload, A, {"t0": t0, "n_sets": n_sets, "cap_jobs": cap_jobs, "chars": chars, "items": items, "D": D}


BRAND_DIR = os.path.join(TEMPLATE, "brand")   # branding option 1 "Gilded Panel" (copied from BuildAdvisor/branding)
GILDED_CSS = """
/* ---- branding option 1 "Gilded Panel" header (private artifact only; the shipped page keeps the text brand) */
.brand.gilded { flex: 1 1 100%; }
.brand.gilded .brand-title { font-size: 0; line-height: 0; text-shadow: none; }
.brand.gilded .mast-wide { display: block; width: 100%; max-width: 1440px; height: auto; aspect-ratio: 6 / 1; margin: 0 auto;
  border-radius: 3px; box-shadow: 0 6px 22px rgba(0,0,0,.55); }
.brand.gilded .mast-narrow { display: none; }
@media (max-width: 860px) {
  .brand.gilded .mast-wide { display: none; }
  .brand.gilded .mast-narrow { display: flex; align-items: center; gap: 14px; padding: 12px 14px; border: 1px solid #8a6a3e;
    border-radius: 3px; box-shadow: inset 0 0 0 4px #1a140f, inset 0 0 0 5px rgba(175,135,104,.45), 0 6px 18px rgba(0,0,0,.5);
    background: radial-gradient(ellipse at 20% 0%, rgba(175,135,104,.18), transparent 70%), linear-gradient(#211a14, #15100c); }
  .brand.gilded .mast-narrow img { width: 56px; height: 56px; flex: none; }
  .brand.gilded .mast-narrow .brand-kicker { display: block; line-height: 1.4; }
  .brand.gilded .mast-narrow .mt { display: block; font-size: var(--fs-xl); line-height: 1.1; color: var(--title); letter-spacing: .02em;
    text-shadow: 0 2px 8px rgba(0,0,0,.8); }
}
"""


def gilded_header(shell, css, js=None, payload=None):
    """Swap the text brand of the claude.ai artifact for the Gilded Panel header. Same header as the shipped page
    (build_sets_ship.header_html + tools/sets_ship/header.css/.js, private tagline): the icon strip shows the best
    Legendary / Very Rare set picks, from the icons embedded in this page. Falls back to the static banner image."""
    if js is not None and payload is not None:
        try:
            import build_sets_ship as S
            payload["hdr"], miss = S.header_cells(None, payload)
            if miss:
                print("  ! header strip: %s" % ", ".join(miss))
            shell = S.header_html(shell, S.LOCKUP_PRIVATE, S.ALT_PRIVATE)
            css += "\n" + open(os.path.join(S.SHIP_SRC, "header.css"), encoding="utf-8").read()
            js = open(os.path.join(S.SHIP_SRC, "header.js"), encoding="utf-8").read() + "\n" + js
            return shell, css, js
        except (OSError, SystemExit, ImportError) as e:
            print("  ! gilded header with the icon strip failed (%s) - static banner kept" % e)
    shell, css = _gilded_banner(shell, css)
    return (shell, css, js) if js is not None else (shell, css)


def _gilded_banner(shell, css):
    """The older static header: wide banner image (option1_sets_private.png), compact panel on phones."""
    try:
        wide = open(os.path.join(BRAND_DIR, "sets_header.webp"), "rb").read()
        mark = open(os.path.join(BRAND_DIR, "mark128.webp"), "rb").read()
    except OSError:
        print("  ! branding images missing in %s - text header kept" % BRAND_DIR)
        return shell, css
    u = lambda b: "data:image/webp;base64," + base64.b64encode(b).decode("ascii")
    old = re.search(r'<div class="brand">.*?</div>', shell, re.S)
    if not old:
        print("  ! shell.html brand block not found - text header kept")
        return shell, css
    new = ('<div class="brand gilded">\n      <h1 class="brand-title">'
           '<img class="mast-wide" src="%s" width="1440" height="240" alt="Loot Advisor: Synergy Sets">'
           '<span class="mast-narrow"><img src="%s" width="56" height="56" alt="">'
           '<span><span class="brand-kicker">Loot Advisor</span><span class="mt">Synergy Sets</span></span></span>'
           '</h1>\n    </div>' % (u(wide), u(mark)))
    return shell[:old.start()] + new + shell[old.end():], css + GILDED_CSS


def build(args):
    payload, A, meta = build_payload(args)
    t0, n_sets, cap_jobs, chars, items = meta["t0"], meta["n_sets"], meta["cap_jobs"], meta["chars"], meta["items"]
    # captures: fit them into what is left of the 16 MB artifact limit (keep 1 MB headroom)
    base = (len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False)) + sum(len(u) for u in A.uris.values())
            + (0 if args.no_fonts else 760_000) + 120_000)
    step, cap_bytes = embed_captures(A, cap_jobs, max(0, 15_000_000 - base))
    n_caps = len(cap_jobs)
    if cap_jobs:
        print("  captures: %d embedded at scale %s, quality %s (%.1f MB)" % (n_caps, step[0], step[1], cap_bytes / 1e6))
    fonts = {}
    if not args.no_fonts:
        for k, p in FONTS.items():
            u = A.font(p)
            if u:
                fonts[k] = u

    shell = open(os.path.join(TEMPLATE, "shell.html"), encoding="utf-8").read()
    css = open(os.path.join(TEMPLATE, "page.css"), encoding="utf-8").read()
    js = open(os.path.join(TEMPLATE, "app.js"), encoding="utf-8").read()
    font_css = ""
    for fam_key, (fam, weight, style) in {"q-reg": ("Quadraat", 400, "normal"), "q-bold": ("Quadraat", 700, "normal"),
                                          "q-it": ("Quadraat", 400, "italic")}.items():
        if fam_key in fonts:
            font_css += ("@font-face{font-family:'%s';src:url(%s) format('truetype');font-weight:%d;font-style:%s;"
                         "font-display:swap}\n" % (fam, fonts[fam_key], weight, style))
    # image CSS variables (each image once) - the page uses var(--img-<key>) or the IMG map
    img_json = json.dumps({k: A.uris[k] for k in A.uris}, separators=(",", ":"))
    shell, css, js = gilded_header(shell, css, js, payload)   # adds payload["hdr"] (the header's icon strip)
    data_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    n_items = len(items)
    html = (shell.replace("/*@FONTS@*/", font_css)
                 .replace("/*@CSS@*/", css)
                 .replace("@IMAGES@", img_json.replace("</", "<\\/"))
                 .replace("@DATA@", data_json)
                 .replace("/*@JS@*/", js))
    html = html.replace("@LOADING@", "Loading %d sets and %d items with their game icons (%.1f MB)..." % (
        n_sets, n_items, len(html.encode("utf-8")) / 1e6))
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "sets.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    # local preview with a document skeleton (the artifact publisher adds its own; screenshots use this one)
    prev = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1, viewport-fit=cover\"></head><body>" + html + "</body></html>")
    with open(os.path.join(OUT_DIR, "_preview.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(prev)
    # 3D models are game meshes/textures built from the local game install: they stay on this PC and are only
    # mounted in a LOCAL viewer copy (sets_local.html, opened from disk), never in the published sets.html
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from model3d.sets_adapter import inject_3d  # artifact/3d/, built by model3d/build_parts.py
    local = inject_3d(prev)
    if local != prev:
        with open(os.path.join(OUT_DIR, "sets_local.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(local)
    size = os.path.getsize(out)
    print("  %d characters, %d sets, %d items, %d images (%.0f KB webp), %d captures" % (
        len(chars), n_sets, len(items), len(A.uris), A.bytes / 1024, n_caps))
    if A.missing:
        miss = sorted(set(A.missing))
        print("  %d assets not found (the page shows a drawn placeholder): %s" % (len(miss), ", ".join(miss[:12])))
    print("  wrote %s  %.2f MB  (%.1f s)" % (os.path.relpath(out, ROOT), size / 1e6, time.time() - t0))
    if size > 15.5e6:
        print("  ! WARNING: page is over the 16 MB artifact limit")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fonts", action="store_true")
    build(ap.parse_args())
