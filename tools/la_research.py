"""Research parsing for LootAdvisor step 3: data/research/<char>.md -> item mentions, per-item notes, seed sets.

Mention roles (used by score_items.py consensus):
  best / runner   item in a best / runner-up column of a section-3 table (or "X / Y" best / runner-up cells)
  note            item in a Notes column without build tags
  set             item in a section-4 synergy set loadout (alternatives "(or X)" get weight 0.6)
  detail          the subject of an item bullet / item table row (section 2 or catalogue tables)
  ref             another item named inside an item bullet
  consensus       item in a section-5 bullet that talks about BiS / consensus / widely used
  niche           item in a section-5 bullet that calls it niche / overrated / situational
Tags = build ids the mention applies to ("*" = all builds of that character).
"""
import collections
import os
import re

from la_common import RESEARCH_DIR, deaccent, short, strip_md

SLOT_WORDS = r"(?:Main hand|Main-hand|Off hand|Off-hand|Offhand|Main|Off|Ranged backup|Ranged|Head|Helmet|Chest|Armour|" \
             r"Body|Cloak|Gloves|Boots|Amulet|Rings?|Ring 1|Ring 2|Melee MH|Melee OH|Melee|Shield|Weapon|" \
             r"Throwing weapon|Consumable|Elixir|Loadout|Selune|Shar)"
SPLIT_RX = re.compile(r"\s*(?:\s/\s|/|;|\s\+\s|,|·|\||\bor\b|\s-\s|:|\.\s|=|->|→)\s*")
RARITY_WORD = re.compile(r"\b(?:Common|Uncommon|Rare|Very rare|Very Rare|VeryRare|Legendary|[Ss]tory [Ii]tem)\b")
ACT_RX = re.compile(r"\b(?:ACT|Act)\s*([123])\b")
GET_RX = re.compile(r"(?:\*\*Get:\*\*|\*Get:\*|\bGet:|\bHOW:|\bHow to get:)\s*", re.I)
WHY_RX = re.compile(r"\*?\b(?:Why|WHY)\b:?\*?:?")
SET_START = [
    re.compile(r'^\s*(\d+)\.\s+\*\*"?([^*"]+?)"?(?:\s*\(([^)]*)\))?\*\*'),     # 1. **"Name" (TAGS)**
    re.compile(r'^\s*\*\*(A\d-\d)\s+"([^"]+)"\*\*'),                          # **A1-2 "Name"**
]


PIECE_WORDS = r"(?:Armour|Armor|Helmet|Helm|Gloves|Gauntlets|Boots|Cloak|Hood|Robe)"
PIECES_RX = re.compile(r"\b((?:[A-Z][\w']+ ){1,3})(" + PIECE_WORDS + r"(?:/" + PIECE_WORDS + r")+)")


def segments(text):
    """Split a table cell / loadout text into candidate item-name segments."""
    t = strip_md(deaccent(text))
    inner = re.findall(r"\(([^()]*)\)", t)
    outer = re.sub(r"\([^()]*\)", " | ", t)
    out = []
    for part in [outer] + inner:
        for seg in SPLIT_RX.split(part):
            seg = re.sub(r"^\s*(?:keep|kept|any|with|then|plus|swap|use|the rest|rest|both|only|a|an|e\.g\.)\s+",
                         "", seg.strip(), flags=re.I)
            # "Ring 1 Caustic Band" / "Armour: X" -> X, but never "Armour of Devotion" -> "of Devotion"
            seg = re.sub(r"^" + SLOT_WORDS + r"\s+(?=[A-Z0-9])", "", seg).strip(" .\"'*")
            if 3 <= len(seg) <= 60 and re.match(r"[A-Z]", seg):
                out.append(seg)
    return out


RARITY_AFTER = re.compile(r"^[\s*_`]*[(|]\s*(Very rare|Uncommon|Rare|VR|Legendary)\b", re.I)
RARITY_NORM = {"very rare": "VeryRare", "vr": "VeryRare", "uncommon": "Uncommon", "rare": "Rare",
               "legendary": "Legendary"}


class Scanner:
    """Finds known item aliases in free text (case-insensitive, the match must start with a capital).
    variants: {alias: {rarity: stats id}} for names shared by several rarities (Dark Justiciar Gauntlets
    Uncommon / Rare): a rarity written right after the name ("**Name** (Rare)", "| Name | Uncommon |") picks
    that variant."""

    def __init__(self, alias_to_sid, variants=None):
        self.alias = {deaccent(a).lower(): sid for a, sid in alias_to_sid.items()}
        self.variants = {deaccent(a).lower(): v for a, v in (variants or {}).items()}
        keys = sorted(self.alias, key=len, reverse=True)
        self.rx = re.compile(r"(?<![\w'])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w'])", re.I)

    def find(self, text):
        out = []
        t = deaccent(text)
        for m in self.rx.finditer(t):
            if m.group(1)[0].isupper() or m.group(1)[0].isdigit():
                key = m.group(1).lower()
                sid = self.alias[key]
                var = self.variants.get(key)
                if var:
                    rm = RARITY_AFTER.match(t[m.end():m.end() + 30])
                    if rm:
                        sid = var.get(RARITY_NORM[rm.group(1).lower()], sid)
                out.append((m.start(), m.end(), sid, m.group(1)))
        return out


def paren_depth_at(text, pos):
    d = 0
    for ch in text[:pos]:
        if ch == "(":
            d += 1
        elif ch == ")":
            d = max(0, d - 1)
    return d


def split_top(text, sep=" / "):
    """Split on sep outside parentheses."""
    parts, d, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            d += 1
        elif ch == ")":
            d = max(0, d - 1)
        if d == 0 and text.startswith(sep, i):
            parts.append(cur)
            cur, i = "", i + len(sep)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return parts


def _note():
    # texts = the item's own research bullet / item-table row (used for campaign conditions in score_items.py)
    return {"warnings": [], "missable": [], "get": [], "do": [], "texts": []}


class ResearchParser:
    def __init__(self, char_id, cfg, all_builds, scanner=None):
        self.char = char_id
        self.cfg = cfg
        self.builds = list(all_builds)
        self.scanner = scanner
        self.path = os.path.join(RESEARCH_DIR, cfg["research"])
        with open(self.path, encoding="utf-8") as f:
            self.text = deaccent(f.read()).replace("CLE/SOR", "CLESOR")
        self.lines = self.text.splitlines()
        self.mentions = []
        self.notes = collections.defaultdict(_note)
        self.seeds = []
        self.candidates = []     # (text, kind, line) for match_research

    # ---- tags
    def tags_in(self, text, soft=False):
        found = set()
        for code, bids in self.cfg.get("tags", {}).items():
            if code == "all":
                if "[all]" in text:
                    return "*"
                continue
            if re.search(r"(?<![A-Za-z])" + re.escape(code) + r"(?![A-Za-z])", text):
                if bids == "*":
                    return "*"
                found |= set(bids)
        for word, bids in self.cfg.get("word_tags", {}).items():
            if re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![a-z])", text):
                found |= set(bids)
        if soft:
            for word, bids in self.cfg.get("soft_tags", {}).items():
                if re.search(r"\b" + re.escape(word) + r"\b", text, re.I):
                    found |= set(bids)
        return sorted(found & set(self.builds)) if found else []

    def default_tags(self):
        d = self.cfg.get("default_tags", "*")
        return "*" if d == "*" else list(d)

    def ctx_or_default(self, ctx_tags):
        """Heading tags; an empty list means the heading names only builds we do not cover -> no builds."""
        if ctx_tags is None:
            return self.default_tags()
        return ctx_tags

    def wordtag_names(self, text):
        return any(re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![a-z])", text)
                   for w in self.cfg.get("word_tags", {}))

    # ---- main loop
    def parse(self):
        section, levels_tags, levels_act = None, {}, {}
        i, n = 0, len(self.lines)
        while i < n:
            line = self.lines[i]
            hm = re.match(r"^(#+)\s+(.*)$", line)
            if hm:
                lvl, title = len(hm.group(1)), hm.group(2)
                sm = re.match(r"^(\d+)", title)
                if lvl == 2:
                    section = int(sm.group(1)) if sm else None
                    levels_tags, levels_act = {}, {}
                for d in (levels_tags, levels_act):
                    for k in [k for k in d if k >= lvl]:
                        del d[k]
                t = self.tags_in(title)
                if t or self.wordtag_names(title):
                    levels_tags[lvl] = t
                am = ACT_RX.search(title)
                if am:
                    levels_act[lvl] = int(am.group(1))
                i += 1
                continue
            bm = re.match(r"^\*\*Act\s*([123])\*\*\s*$", line.strip())
            if bm:
                levels_act[9] = int(bm.group(1))
                i += 1
                continue
            ctx_tags = levels_tags[max(levels_tags)] if levels_tags else None
            ctx_act = levels_act[max(levels_act)] if levels_act else None
            if line.startswith("|"):
                j = i
                while j < n and self.lines[j].startswith("|"):
                    j += 1
                self._table(self.lines[i:j], i + 1, section, ctx_tags, ctx_act)
                i = j
                continue
            if section == 4 and any(rx.match(line) for rx in SET_START):
                j = i + 1
                while j < n and not any(rx.match(self.lines[j]) for rx in SET_START) \
                        and not self.lines[j].startswith("#") and not self.lines[j].startswith("---"):
                    j += 1
                self._set_block(self.lines[i:j], i + 1, ctx_act)
                i = j
                continue
            if re.match(r"^- ", line):
                j = i + 1
                while j < n and re.match(r"^\s{2,}\S", self.lines[j]) and not re.match(r"^\s*- ", self.lines[j]):
                    j += 1
                block = " ".join(x.strip() for x in self.lines[i:j])
                if section == 5:
                    self._consensus(block, i + 1)
                    k = j
                    while k < n and re.match(r"^\s+- ", self.lines[k]):
                        self._consensus(block.split(":")[0] + ": " + self.lines[k].strip(), k + 1)
                        k += 1
                    i = k
                    continue
                if re.match(r"^- \*\*", line):
                    self._detail(block, i + 1, section, ctx_tags, ctx_act)
                i = j
                continue
            i += 1
        return self

    # ---- pieces
    def _add(self, sid, role, line, act, tags, weight=1.0, section=None, text=""):
        self.mentions.append({"sid": sid, "role": role, "line": line, "act": act, "tags": tags, "w": weight,
                              "section": section, "file": self.cfg["research"], "char": self.char,
                              "text": short(text, 160)})

    def _items(self, text):
        return self.scanner.find(text) if self.scanner else []

    def _table(self, rows, line0, section, ctx_tags, ctx_act):
        cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
        if len(cells) < 2:
            return
        header = [strip_md(h) for h in cells[0]]
        body = [c for c in cells[1:] if not all(re.match(r"^:?-+:?$", x) or not x for x in c)]
        cols, last_best_tags = [], None
        for h in header:
            hl = h.lower()
            ht = self.tags_in(h)
            am = ACT_RX.search(h)
            role = None
            if hl == "slot":
                role = "slot"
            elif hl == "act":
                role = "act"
            elif hl in ("build", "key"):
                role = "build"
            elif hl in ("item", "name") or hl.startswith("result") or hl.startswith("elixir"):
                role = "item"
            elif "best" in hl and "runner" in hl:
                role = "combined"
            elif "best" in hl:
                role = "best"
            elif "runner" in hl:
                role = "runner"
            elif hl.startswith("note"):
                role = "note"
            elif "get" in hl or "source" in hl:
                role = "get"
            elif "flag" in hl or "cost" in hl or "story choice" in hl:
                role = "flags"
            if role in ("best", "combined"):
                last_best_tags = ht or None
            if role == "runner" and not ht:
                ht = last_best_tags or []
            cols.append({"role": role, "tags": ht, "act": int(am.group(1)) if am else None})
        roles = {c["role"] for c in cols}
        ranking = bool(roles & {"best", "runner", "combined"})
        last_warn = None
        for ri, row in enumerate(body):
            ln = line0 + 1 + ri
            row_act, row_tags = ctx_act, None
            for c, val in zip(cols, row):
                if c["role"] == "act":
                    m = re.search(r"([123])", val)
                    row_act = int(m.group(1)) if m else row_act
                if c["role"] == "build":
                    row_tags = self.tags_in(val) or row_tags
            if ranking:
                for c, val in zip(cols, row):
                    if c["role"] not in ("best", "runner", "combined", "note"):
                        continue
                    self.candidates += [(s, "table", ln) for s in segments(val)]
                    act = c["act"] or row_act
                    base_tags = c["tags"] or row_tags or self.ctx_or_default(ctx_tags)
                    if c["role"] == "combined":
                        parts = split_top(val)
                        pieces = [(parts[0], "best")] + [(p, "runner") for p in parts[1:]]
                    else:
                        pieces = [(val, c["role"])]
                    for txt, role in pieces:
                        self._cell_items(txt, role, ln, act, base_tags, section)
            else:
                item_col = next((k for k, c in enumerate(cols) if c["role"] == "item"), 0)
                if item_col >= len(row):
                    continue
                rowtxt = " | ".join(row)
                kind = "table-item" if RARITY_WORD.search(rowtxt) else "table-row"
                segs = segments(row[item_col])
                self.candidates += [(s, kind, ln) for s in (segs if "/" in strip_md(row[item_col]) else segs[:1])]
                found = self._items(row[item_col])
                if not found:
                    continue
                # "**A** / **B** / **C**" in the item cell: the row describes all of them
                sids = list(dict.fromkeys(f[2] for f in found)) if "/" in strip_md(row[item_col]) else [found[0][2]]
                for sid in sids:
                    self._table_row(sid, cols, row, rowtxt, ln, row_act, section, ctx_tags, last_warn)
                    if self.notes[sid]["warnings"]:
                        last_warn = self.notes[sid]["warnings"][-1][1]

    def _table_row(self, sid, cols, row, rowtxt, ln, row_act, section, ctx_tags, last_warn):
        tags = self.tags_in(rowtxt) or self.ctx_or_default(ctx_tags)
        self._add(sid, "detail", ln, row_act, tags, 1.0, section, rowtxt)
        note = self.notes[sid]
        note["texts"].append((self.cfg["research"], strip_md(rowtxt)))
        for c, val in zip(cols, row):
            if c["role"] == "get" and val.strip("- "):
                note["get"].append((self.cfg["research"], short(strip_md(val), 400)))
            if "WARNING" in val:
                self._warn(sid, val)
            elif c["role"] == "flags" and last_warn and re.match(r"^\W*(?:same|as above)\b.*\bwarning", val,
                                                                   re.I):
                note["warnings"].append((self.cfg["research"], last_warn))   # "Same Valeria warning"
            if "MISSABLE" in val:
                self._missable(sid, val[val.find("MISSABLE"):])
            elif c["role"] == "flags" and "WARNING" not in val and \
                    re.search(r"\blost\b|leaves|only (?:on|in|until)|before you|closes", val, re.I):
                self._missable(sid, val)

    def _cell_items(self, txt, role, ln, act, base_tags, section):
        for k, (s, e, sid, _m) in enumerate(self._items(txt)):
            pm = re.match(r"\s*\(([^)]*)\)", txt[e:e + 80])
            tags, r = base_tags, role
            if pm:
                t = self.tags_in(pm.group(1), soft=True)
                if t:
                    tags = t
            if role == "note":
                t = self.tags_in(txt[max(0, s - 30):s])
                if t:
                    tags, r = t, "best"
            w = 1.0 if k == 0 else 0.75
            if role == "note" and r == "best":
                w = 0.75
            self._add(sid, r, ln, act, tags, w, section, txt)

    def _warn(self, sid, text):
        t = re.sub(r"WARNING\s*/\s*MISSABLE", "WARNING", strip_md(text))
        k = t.find("WARNING")
        seg = t[k:] if k >= 0 else t
        seg = re.split(r"(?:MISSABLE|\bGet:|\bHOW:)", seg)[0]
        seg = re.sub(r"^WARNING:?\s*", "", seg).strip(" .;:-/|")
        if len(re.findall(r"[A-Za-z]", seg)) < 4 or re.match(r"^(?:none|no (?:extra )?cost|n/a)\b", seg, re.I) \
                or re.search(r"\bno extra cost\b", seg, re.I):
            return
        if re.match(r"^(?:as |same |see )", seg, re.I) and len(seg) < 60:
            return            # refers to another row ("as above", "same as ...") - no information of its own
        self.notes[sid]["warnings"].append((self.cfg["research"], short(seg, 260)))

    def _missable(self, sid, text):
        seg = strip_md(text)
        seg = re.split(r"(?:\bGet:|\bHOW:|WARNING)", seg)[0]
        seg = re.sub(r"^MISSABLE\s*(?:\([^)]*\))?\s*:?\s*", "", seg).strip(" .;:-/|+")
        if len(re.findall(r"[A-Za-z]", seg)) >= 20:
            self.notes[sid]["missable"].append((self.cfg["research"], short(seg, 240)))

    def _detail(self, block, ln, section, ctx_tags, ctx_act):
        m = re.match(r"^- \*\*([^*]+)\*\*", block)
        if not m:
            return
        kind = "bullet-item" if RARITY_WORD.search(block[m.end():m.end() + 120]) else "bullet"
        for seg in (segments(m.group(1)) if re.search(r"[/+]", m.group(1)) else [m.group(1)]):
            self.candidates.append((seg, kind, ln))
        found = self._items(m.group(0))
        if not found:
            return
        sid = found[0][2]
        tags = self.tags_in(block) or self.ctx_or_default(ctx_tags)
        self._add(sid, "detail", ln, ctx_act, tags, 1.0, section, block)
        self.notes[sid]["texts"].append((self.cfg["research"], strip_md(block)))
        for s, e, other, _ in self._items(block[m.end():]):
            if other != sid:
                self._add(other, "ref", ln, ctx_act, tags, 0.5, section, block)
        if "WARNING" in block:
            self._warn(sid, block)
        if "MISSABLE" in block:
            self._missable(sid, block[block.find("MISSABLE"):])
        gm = GET_RX.search(block)
        get = None
        if gm:
            get = re.split(r"`?(?:WARNING|MISSABLE)", block[gm.end():])[0]
        elif block.count(" | ") >= 3:
            fields = block.split(" | ")
            coord = [f for f in fields if re.search(r"X[: ]+-?\d", f)]
            get = coord[0] if coord else max(fields[1:], key=len)
        if get and get.strip():
            self.notes[sid]["get"].append((self.cfg["research"], short(strip_md(get), 400)))
        dm = re.search(r"\*\*Do:\*\*\s*(.+)", block)
        if dm:
            self.notes[sid]["do"].append((self.cfg["research"], short(strip_md(dm.group(1)), 300)))

    def _consensus(self, block, ln):
        low = block.lower()
        if re.search(r"error|not verified|could not|do not match|does not exist|unverified|wrong|not a real", low):
            return
        if re.search(r"niche|overrated|overstated|situational", low):
            role = "niche"
        elif re.search(r"\bbis\b|best in slot|consensus|near-universal|undisputed|widely|most-cited|standard", low):
            role = "consensus"
        else:
            role = "note5"
        # an untagged community statement applies to every build of the character (not only the default build)
        tags = self.tags_in(block) or "*"
        for s, e, sid, _ in self._items(block):
            self._add(sid, role, ln, None, tags, 1.0, 5, block)

    def _set_block(self, lines, ln, ctx_act):
        first = lines[0].strip()
        m = SET_START[0].match(first) or SET_START[1].match(first)
        idx, name = m.group(1), m.group(2).strip()
        text = " ".join(x.strip() for x in lines)
        body = text[m.end():]
        # header = first line up to the first item name (the build tags live there)
        first_items = self._items(first[m.end():])
        hdr = first[:m.end() + (first_items[0][0] if first_items else len(first) - m.end())]
        tags = self.tags_in(hdr)
        if not tags and self.cfg.get("word_tags") and self.wordtag_names(hdr):
            tags = []            # names only builds we do not cover (e.g. Bardadin, Monk)
        elif not tags:
            tags = self.default_tags()
        wm = WHY_RX.search(body)
        if wm:
            loadout = body[:wm.start()]
        else:
            k = body.find(". ")
            loadout = body if k < 0 else body[:k]
        # "Flawed Helldusk Armour/Helmet/Gloves" -> three names
        loadout = PIECES_RX.sub(lambda mm: " / ".join(mm.group(1).rstrip() + " " + p_ for p_ in mm.group(2).split("/")),
                             loadout)
        self.candidates += [(s_, "set", ln) for s_ in segments(loadout)]
        items = []
        last_core = None
        for s0, e0, sid, mt in self._items(loadout):
            before = loadout[max(0, s0 - 6):s0].lower()
            alt = paren_depth_at(loadout, s0) > 0 or before.rstrip().endswith("or")
            # an alternative ("A or B", "A (or B)") only stands in for the item it follows
            items.append({"sid": sid, "alt": alt, "text": mt, "alt_of": last_core if alt else None})
            if not alt:
                last_core = sid
        self.seeds.append({"file": self.cfg["research"], "char": self.char, "act": ctx_act, "idx": idx,
                           "name": name, "tags": tags, "line": ln, "items": items,
                           "loadout": short(strip_md(loadout), 600)})
        for it in items:
            self._add(it["sid"], "set", ln, ctx_act, tags, 0.6 if it["alt"] else 1.0, 4, name)
