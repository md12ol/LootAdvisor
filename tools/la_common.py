"""Shared helpers for LootAdvisor step 3 (tools/match_research.py, tools/score_items.py).

- load_items / load_sources / load_levels: data/items_all
- NameIndex: research item name -> game stats ids (exact trimmed name, normalised name, fuzzy)
- ResearchParser: reads data/research/<char>.md into item mentions (table best/runner-up, detail bullets,
  synergy sets, consensus notes) plus per-item notes (WARNING / MISSABLE / Get text) and seed sets.
Pure Python 3.12, no game access.
"""
import collections
import difflib
import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ITEMS_DIR = os.path.join(DATA, "items_all")
RESEARCH_DIR = os.path.join(DATA, "research")
SCORES_DIR = os.path.join(DATA, "scores")

RARITY_RANK = {"Common": 0, "Uncommon": 1, "Rare": 2, "VeryRare": 3, "Legendary": 4, "Story": 2}
PLAY_ACTS = {1: 1, 2: 2, 3: 3, "tutorial": 1}

# names the research itself says are not real items (user list + research notes); "-> X" = alias
KNOWN_NON_ITEMS = {
    "Staff of Crones": None, "Ring of Fire": None, "Circlet of Fire": None, "Poisoner's Robe": None,
    "Cloak of Billowing": None, "Spellguard Shield": None, "Healing Pendant": None, "Hellrider Longsword": None,
    "Radiating Orb Gloves": None, "Elixir of Arcane Acuity": None, "Hat of Storms": None,
}
MANUAL_ALIASES = {
    "Gauntlets of Frost Giant Strength": "Gauntlets of Hill Giant Strength",
}


# ---------------------------------------------------------------- text helpers
def deaccent(s):
    """Same-length de-accenting (positions stay valid): each char -> its NFKD base char."""
    out = []
    for ch in s:
        if ord(ch) < 128:
            out.append(ch)
            continue
        if ch in "’‘ʼ":
            out.append("'")
        elif ch in "“”":
            out.append('"')
        elif ch in "–—":
            out.append("-")
        else:
            d = unicodedata.normalize("NFKD", ch)
            out.append(d[0] if d and ord(d[0]) < 128 else ch)
    return "".join(out)


def norm(name):
    s = deaccent(name or "").lower().strip()
    s = s.replace("armor", "armour").replace("&", " and ")
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"'s\b", "s", s)
    s = re.sub(r"[^a-z0-9+ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


RARITY_SUFFIX = re.compile(r"\s*\((Common|Uncommon|Rare|Very rare|Very Rare|VeryRare|Legendary)\)\s*$", re.I)


def split_rarity(name):
    m = RARITY_SUFFIX.search(name)
    if not m:
        return name.strip(), None
    r = m.group(1).replace(" ", "").lower()
    r = {"common": "Common", "uncommon": "Uncommon", "rare": "Rare", "veryrare": "VeryRare",
         "legendary": "Legendary"}[r]
    return name[:m.start()].strip(), r


def short(text, n=200):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    p = max(cut.rfind(". "), cut.rfind("; "))
    if p > n * 0.5:
        return cut[:p + 1]
    return cut.rsplit(" ", 1)[0] + "..."


def strip_md(s):
    return re.sub(r"[*`_]", "", s)


# ---------------------------------------------------------------- data loaders
def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_items():
    items = {}
    for g in ("weapons", "armour", "accessories"):
        for r in _jsonl(os.path.join(ITEMS_DIR, g + ".jsonl")):
            r["name"] = (r.get("name") or r["stats_id"]).strip()
            items[r["stats_id"]] = r
    return items


def load_sources():
    src = collections.defaultdict(list)
    for r in _jsonl(os.path.join(ITEMS_DIR, "sources.jsonl")):
        src[r["stats_id"]].append(r)
    return src


def load_levels():
    with open(os.path.join(ITEMS_DIR, "levels.json"), encoding="utf-8") as f:
        return json.load(f)


def load_recipes():
    return _jsonl(os.path.join(ITEMS_DIR, "recipes.jsonl"))


COMPANION_KEYS = {"shadowheart": "shadowheart", "laezel": "laezel", "lae'zel": "laezel", "wyll": "wyll",
                  "karlach": "karlach", "gale": "gale", "astarion": "astarion", "dark": "darkurge",
                  "darkurge": "darkurge"}
ORIGIN_REGION = re.compile(r"^Origin story \(companion quest\)(?::\s*([\w']+))?")
ORIGIN_QUEST = re.compile(r"\(ORI_(?:COM|Avatar)_(\w+)\)")


def origin_of_source(s):
    """Character key of the origin companion whose own quest / person this source belongs to, else None
    ("Origin story (companion quest): Shadowheart" placements, items Shadowheart herself wears, rewards of
    Wyll's quest 'The Blade of Frontiers' (ORI_COM_Wyll) ...)."""
    m = ORIGIN_REGION.match(s.get("region") or "")
    if m:
        who = (m.group(1) or ((s.get("holder") or {}).get("name") or "").split(" ")[0]).lower()
        return COMPANION_KEYS.get(who, "origin")
    q = ORIGIN_QUEST.search(s.get("requires") or "")
    if q:
        return COMPANION_KEYS.get(q.group(1).lower(), "origin")
    return None


def source_act(s):
    """Gameplay act of a source record (1-3) or None (epilogue, system, camp templates, unknown)."""
    return PLAY_ACTS.get(s.get("act"))


def build_display_names(items, refresh=False):
    """{stats_id: {display name: [template MapKeys]}} from every root template that uses the stats id
    (own or inherited DisplayName) and every level/global placement that overrides DisplayName.
    Several items have more than one in-game name (e.g. the Flawed Helldusk pieces are quest-reward
    templates of the 'Hellgloom' stats, Crusher's Ring is a template of ARM_DrunkGoblinRing).
    Cached in data/cache/item_display_names.json."""
    cache = os.path.join(DATA, "cache", "item_display_names.json")
    if os.path.exists(cache) and not refresh:
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    import glob
    tmpl = {}
    for p in glob.glob(os.path.join(DATA, "cache", "roottemplates_*.json")):
        with open(p, encoding="utf-8") as f:
            for o in json.load(f):
                inh = o.get("inherited") or {}
                stats = o.get("Stats") or inh.get("Stats")
                dn = o.get("DisplayName") or inh.get("DisplayName") or {}
                tmpl[o["MapKey"]] = (stats, (dn.get("text") or "").strip())
    out = collections.defaultdict(lambda: collections.defaultdict(set))
    for mk, (stats, name) in tmpl.items():
        if stats in items and name:
            out[stats][name].add(mk)
    for fn in ("level_items_index.json", "global_items_index.json"):
        with open(os.path.join(DATA, "cache", fn), encoding="utf-8") as f:
            rows = json.load(f)
        for r in rows:
            dn = (r.get("DisplayName") or {}).get("text")
            if not dn:
                continue
            tn = r.get("TemplateName")
            stats = r.get("Stats") or (tmpl.get(tn) or (None, None))[0]
            if stats in items:
                out[stats][dn.strip()].add(tn)
    res = {sid: {n: sorted(t for t in ts if t) for n, ts in names.items()} for sid, names in out.items()}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res


def load_builds_lua(path):
    """Parse BA.Builds gear lines and BA.Origins from BuildAdvisor's Builds.lua (read-only)."""
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    gear = {}
    for m in re.finditer(r'id\s*=\s*"([^"]+)".*?gear\s*=\s*"([^"]*)"', txt, re.S):
        gear[m.group(1)] = m.group(2)
    origins = {}
    for m in re.finditer(r'^\s*(\w+)\s*=\s*\{\s*builds\s*=\s*\{([^}]*)\}', txt, re.M):
        origins[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    return gear, origins


# ---------------------------------------------------------------- name index
class NameIndex:
    def __init__(self, items, sources, display_names=None):
        self.items = items
        self.by_exact = collections.defaultdict(list)
        self.by_norm = collections.defaultdict(list)
        self.by_alt = collections.defaultdict(list)
        self.name_templates = {}      # (sid, in-game name) -> templates carrying that name
        self.norm_names = collections.defaultdict(set)
        dn = display_names or {}
        for sid, r in items.items():
            names = {r["name"]: r.get("templates") or []}
            for n, ts in (dn.get(sid) or {}).items():
                if n not in names:
                    names[n] = ts
            for n, ts in names.items():
                self.by_exact[n].append(sid)
                self.by_norm[norm(n)].append(sid)
                self.norm_names[norm(n)].add(n)
                self.name_templates[(sid, n)] = ts
            for a in r.get("alt_names") or []:
                self.by_alt[norm(a)].append(sid)
        self.play = {}
        for sid in items:
            srcs = [s for s in sources.get(sid, []) if source_act(s)]
            acts = [source_act(s) for s in srcs]
            # every gameplay source sits inside one companion's origin quest (e.g. the Rare Dark Justiciar
            # Gauntlets of Shadowheart's Shar path): an ambiguous name means the ungated variant
            gated = bool(srcs) and all(origin_of_source(s) for s in srcs)
            self.play[sid] = (len(acts) > 0, min(acts) if acts else 9, len(acts), gated)
        self.norm_keys = list(self.by_norm)

    def rank_key(self, sid):
        has_play, act, n, gated = self.play[sid]
        r = self.items[sid]
        # same rarity: the variant with its own passives (Sarth Baretha's psionic Githyanki Greatsword) before the
        # plain one
        own = sum(1 for e in r.get("effects") or [] if e.get("kind") in ("passive", "status")
                  and "hidden technical" not in (e.get("text") or ""))
        return (0 if has_play else 1, gated, -RARITY_RANK.get(r["rarity"], 0), -min(own, 1), act, -n, len(sid), sid)

    def choose(self, ids, rarity=None, name=None):
        # an item whose own record name is the name beats one that only carries it as a template display name
        # (Spidersilk Armour = Minthara's GOB_DrowCommander_Leather_Armor, not a template of Drow Studded Leather)
        own = {i for i in ids if name and norm(self.items[i]["name"]) == norm(name)}
        ids = sorted(set(ids), key=lambda i: (self.rank_key(i)[0], i not in own) + self.rank_key(i)[1:])
        if rarity:
            sel = [i for i in ids if self.items[i]["rarity"] == rarity]
            if sel:
                ids = sel + [i for i in ids if i not in sel]
        return ids

    def match(self, raw):
        """-> {"method", "ids", "chosen", "ratio", "game_name", "templates"} or None."""
        name = deaccent(raw).strip().strip(".,;:")
        if name in KNOWN_NON_ITEMS:
            return None
        if name in MANUAL_ALIASES:
            tgt = MANUAL_ALIASES[name]
            ids = [tgt] if tgt in self.items else self.choose(self.by_exact.get(tgt, []))
            if ids:
                return self._res("manual", ids, name)
        base, rarity = split_rarity(name)
        for cand in (name, base):
            ids = self.by_exact.get(cand)
            if ids:
                return self._res("exact", self.choose(ids, rarity, cand), cand)
        for cand in (name, base, re.sub(r"\s*\([^)]*\)\s*$", "", base)):
            key = norm(cand)
            ids = self.by_norm.get(key)
            if ids:
                return self._res("normalized", self.choose(ids, rarity, cand), key=key)
        ids = self.by_alt.get(norm(base))
        if ids and len(set(self.items[i]["name"] for i in ids)) == 1:
            return self._res("alt_name", self.choose(ids, rarity))
        return None

    def fuzzy(self, raw, cutoff=0.86):
        base, rarity = split_rarity(deaccent(raw).strip())
        n = norm(base)
        if len(n) < 6:
            return None
        best = difflib.get_close_matches(n, self.norm_keys, n=1, cutoff=cutoff)
        if not best:
            return None
        ratio = difflib.SequenceMatcher(None, n, best[0]).ratio()
        res = self._res("fuzzy", self.choose(self.by_norm[best[0]], rarity))
        res["ratio"] = round(ratio, 3)
        return res

    def _res(self, method, ids, name=None, key=None):
        sid = ids[0]
        if key is not None:
            cands = [n for n in self.norm_names.get(key, ()) if (sid, n) in self.name_templates]
            name = cands[0] if cands else None
        if name is None or (sid, name) not in self.name_templates:
            name = self.items[sid]["name"]
        tm = self.name_templates.get((sid, name)) or self.items[sid].get("templates") or []
        return {"method": method, "ids": ids, "chosen": sid, "ratio": 1.0, "game_name": name, "templates": tm}
