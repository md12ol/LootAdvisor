"""Extract every BG3 weapon item (stats type "Weapon" used by a real item) -> data/items_all/weapons.jsonl.

Follows data/items_all/SCHEMA.md (group = "weapons"). Read-only on the game folder.

Inputs: data/cache/stats_resolved.json, roottemplates_*.json, loca_english.json, level_items_index.json
(built by build_cache.py / stats.py), plus small direct reads from the paks for: Honour-mode stats
(override flag), tag GUID -> name (Public/*/Tags/*.lsf), GoldValues.lsx + LevelMapValues.lsx (item value,
LevelMapValue() description params).

Which stats entries are included: type Weapon, name not starting with "_", and used by an item:
 - an item root template whose own or inherited `Stats` is the entry, or
 - a level placement that overrides `Stats` to the entry, or
 - the entry's own (not inherited) `RootTemplate` field naming an existing item root template.

Value: GoldValues.lsx chain (each parent step rounded to int) at ValueLevel, * ValueScale, then the
display rounding seen in game (<20 exact, <100 nearest 5, <1000 nearest 10, else nearest 50);
`ValueOverride` wins. Verified against bg3.wiki: Dagger 16, Longsword 40, Greatsword 65, Everburn 130,
Nyrulna 840.

  python extract_weapons.py [--out PATH] [--report]
"""
import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "data", "cache")
OUT_DEFAULT = os.path.join(ROOT, "data", "items_all", "weapons.jsonl")

GROUP = "weapons"
STATS_TYPES = ("Weapon",)

RAW_KEYS = ["Boosts", "DefaultBoosts", "BoostsOnEquipMainHand", "BoostsOnEquipOffHand", "PassivesOnEquip",
            "PassivesMainHand", "PassivesOffHand", "StatusOnEquip", "WeaponFunctors"]


# ----------------------------------------------------------------------------------------------- loading
def _load_json(name):
    with open(os.path.join(CACHE, name), encoding="utf-8") as f:
        return json.load(f)


def load_templates():
    out = []
    for f in sorted(glob.glob(os.path.join(CACHE, "roottemplates_*.json"))):
        mod = os.path.basename(f)[len("roottemplates_"):-5]
        for o in json.load(open(f, encoding="utf-8")):
            o["_module"] = mod
            out.append(o)
    return out


def _paks():
    from pak import Pak, GAME_DATA
    return Pak, GAME_DATA


def load_honour_names():
    """Names of stats entries (any type) that Honour mode redefines -> {name: data dict}."""
    import stats as st_mod
    Pak, GAME_DATA = _paks()
    out = {}
    p = Pak(os.path.join(GAME_DATA, "Gustav.pak"))
    for e in p.entries:
        n = e.name
        if n.startswith(("Public/Honour/", "Public/HonourX/")) and "/Stats/Generated/Data/" in n and n.endswith(".txt"):
            tmp = {}
            st_mod._parse(p.read(e).decode("utf-8", "replace"), "Honour", n, tmp)
            for k, v in tmp.items():
                out[k] = v["data"]
    p.close()
    return out


def load_tag_names():
    import lsf
    Pak, GAME_DATA = _paks()
    tags = {}
    for pk in ("Shared.pak", "Gustav.pak", "GustavX.pak"):
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            parts = e.name.split("/")
            if len(parts) == 4 and parts[0] == "Public" and parts[2] == "Tags" and e.name.endswith(".lsf"):
                res = lsf.load(p.read(e))
                stack = list(res.regions)
                while stack:
                    nd = stack.pop()
                    if nd.get("UUID") and nd.get("Name"):
                        tags[nd.get("UUID")] = nd.get("Name")
                    stack.extend(nd.children)
        p.close()
    return tags


def load_lsx_nodes(path_in_pak, node_id):
    Pak, GAME_DATA = _paks()
    p = Pak(os.path.join(GAME_DATA, "Shared.pak"))
    root = ET.fromstring(p.read(p.by_name[path_in_pak]))
    p.close()
    out = []
    for n in root.iter("node"):
        if n.get("id") == node_id:
            out.append({a.get("id"): a.get("value") for a in n.findall("attribute")})
    return out


# ----------------------------------------------------------------------------------------------- value
class GoldValues:
    def __init__(self):
        self.g = {a["UUID"]: a for a in load_lsx_nodes("Public/Shared/Levelmaps/GoldValues.lsx", "GoldValue")}

    def base(self, uuid, level):
        a = self.g.get(uuid)
        if a is None:
            return None
        v = a.get(f"Level{level}")
        if v is not None:
            return float(v)
        if not a.get("ParentUUID"):
            # flat tables (ZeroValue, Tools, ...) only define Level1
            return float(a["Level1"]) if a.get("Level1") is not None else None
        pv = self.base(a["ParentUUID"], level)
        return None if pv is None else float(round(pv * float(a.get("ParentScale", 1))))

    @staticmethod
    def display_round(v):
        if v < 20:
            return int(round(v))
        step = 5 if v < 100 else 10 if v < 1000 else 50
        return int(step * round(v / step))

    def value(self, s):
        if s.get("ValueOverride") not in (None, ""):
            try:
                return int(float(s["ValueOverride"]))
            except ValueError:
                pass
        try:
            lvl = int(s.get("ValueLevel") or 1)
            b = self.base(s.get("ValueUUID"), lvl)
            if b is None:
                return None
            return self.display_round(b * float(s.get("ValueScale") or 1))
        except (TypeError, ValueError):
            return None


# ----------------------------------------------------------------------------------------------- text helpers
def split_top(s, sep=";", keep_empty=False):
    """Split on `sep` outside parentheses/quotes."""
    out, depth, cur, q = [], 0, [], None
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return out if keep_empty else [x for x in out if x]


def parse_call(s):
    """'Func(a, b)' -> ('Func', ['a','b']); plain -> (s, None)."""
    m = re.match(r"^\s*([A-Za-z_][\w.]*)\s*\((.*)\)\s*$", s, re.S)
    if not m:
        return s.strip(), None
    return m.group(1), [a.strip() for a in split_top(m.group(2), ",", keep_empty=True)] if m.group(2).strip() else []


def split_condition(b):
    """'IF(cond):Boost(...)' -> (cond, 'Boost(...)')."""
    if b.startswith("IF(") or b.startswith("IF ("):
        i = b.index("(")
        depth = 0
        for j in range(i, len(b)):
            if b[j] == "(":
                depth += 1
            elif b[j] == ")":
                depth -= 1
                if depth == 0:
                    rest = b[j + 1:].lstrip()
                    if rest.startswith(":"):
                        return b[i + 1:j], rest[1:].strip()
                    break
    return None, b


def humanize(name):
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name))
    return s.replace("_", " ").strip()


class Texts:
    def __init__(self, loca, stats, levelmaps):
        self.loca, self.stats, self.levelmaps = loca, stats, levelmaps

    def loc(self, ref):
        if not ref:
            return None
        h = ref.split(";")[0].strip()
        t = self.loca.get(h)
        if t is None or t.startswith("%%%") or t.strip() in ("", "|Placeholder|"):
            return None
        return t

    @staticmethod
    def clean(t):
        if t is None:
            return None
        t = re.sub(r"<br\s*/?>", " ", t)
        t = re.sub(r"<[^>]+>", "", t)
        t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        t = re.sub(r"\bdamage(\s+damage)+\b", "damage", t)
        return re.sub(r"\s+", " ", t).strip()

    def param_text(self, p):
        f, args = parse_call(p)
        if args is None:
            return p.strip()
        a = args + ["", "", ""]
        if f == "DealDamage":
            amt = self.expr(a[0])
            typ = a[1] if a[1] and a[1] not in ("Base",) else ""
            return f"{amt} {typ} damage".replace("  ", " ")
        if f == "Distance":
            return f"{a[0]}m"
        if f == "RegainHitPoints":
            return f"{self.expr(a[0])} hit points"
        if f == "GainTemporaryHitPoints":
            return f"{self.expr(a[0])} temporary hit points"
        if f == "LevelMapValue":
            lm = self.levelmaps.get(a[0])
            return lm.get("Level1", a[0]) if lm else a[0]
        if f == "ApplyStatus":
            st = self.stats.get(a[0])
            return (self.loc(st.get("DisplayName")) if st else None) or humanize(a[0])
        return ", ".join(self.expr(x) for x in args if x)

    def expr(self, x):
        x = x.strip()
        x = re.sub(r"LevelMapValue\((\w+)\)",
                   lambda m: (self.levelmaps.get(m.group(1)) or {}).get("Level1", m.group(1)), x)
        repl = {"MainMeleeWeapon": "weapon", "MainRangedWeapon": "weapon", "MainWeapon": "weapon",
                "OffhandMeleeWeapon": "off-hand weapon", "SpellcastingAbilityModifier": "spellcasting modifier",
                "StrengthModifier": "Strength modifier", "DexterityModifier": "Dexterity modifier",
                "ProficiencyBonus": "proficiency bonus"}
        for k, v in repl.items():
            x = x.replace(k, v)
        return x

    def described(self, entry, kind, ident):
        """(name, text) for a passive/spell/status stats entry; params substituted."""
        name = self.clean(self.loc(entry.get("DisplayName")))
        desc = self.loc(entry.get("Description"))
        if desc:
            params = split_top(entry.get("DescriptionParams", "") or "")
            def sub(m):
                i = int(m.group(1)) - 1
                return self.param_text(params[i]) if 0 <= i < len(params) else m.group(0)
            desc = re.sub(r"\[(\d+)\]", sub, desc)
        extra = self.loc(entry.get("ExtraDescription"))
        if extra:
            eparams = split_top(entry.get("ExtraDescriptionParams", "") or "")
            extra = re.sub(r"\[(\d+)\]", lambda m: self.param_text(eparams[int(m.group(1)) - 1])
                           if 0 < int(m.group(1)) <= len(eparams) else m.group(0), extra)
            desc = f"{desc} {extra}" if desc else extra
        return name, self.clean(desc)


# ----------------------------------------------------------------------------------------------- boosts
ABIL = {"Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"}


def boost_text(b):
    """Readable text for one boost call (no IF prefix). Returns None for cosmetic/technical boosts."""
    f, a = parse_call(b)
    a = a or []
    g = a + ["", "", "", ""]
    if f in ("HiddenDuringCinematic",):
        return None
    if f == "WeaponEnchantment":
        return f"+{g[0]} to attack and damage rolls (weapon enchantment)"
    if f == "WeaponProperty":
        return {"Magical": "Magical weapon (overcomes non-magical resistance)"}.get(g[0], f"Weapon property: {g[0]}")
    if f in ("WeaponDamage", "CharacterWeaponDamage"):
        who = "" if f == "WeaponDamage" else " to weapon attacks"
        return f"+{GoldlessExpr(g[0])} {g[1]} damage{who}".replace("  ", " ")
    if f == "DamageBonus":
        return f"+{GoldlessExpr(g[0])} {g[1]} damage".replace("  ", " ")
    if f == "AC":
        return f"{_sign(g[0])} Armour Class"
    if f == "Ability":
        cap = f" (max {g[2]})" if g[2] else ""
        return f"{_sign(g[1])} {g[0]}{cap}"
    if f == "AbilityOverrideMinimum":
        return f"{g[0]} becomes at least {g[1]}"
    if f == "RollBonus":
        return f"{_sign(g[1])} to {humanize(g[0])} rolls" + (f" ({g[2]})" if g[2] else "")
    if f == "Skill":
        return f"{_sign(g[1])} {humanize(g[0])}"
    if f == "Advantage":
        return "Advantage on " + " ".join(humanize(x) for x in a if x)
    if f == "Disadvantage":
        return "Disadvantage on " + " ".join(humanize(x) for x in a if x)
    if f == "Resistance":
        lvl = {"Resistant": "Resistance", "Immune": "Immunity", "Vulnerable": "Vulnerability"}.get(g[1], g[1])
        return f"{lvl} to {g[0]} damage"
    if f == "IgnoreResistance":
        return f"Ignores {g[0]} resistance"
    if f == "Proficiency":
        return f"Proficiency: {humanize(g[0])}"
    if f == "ProficiencyBonus":
        return f"Proficiency bonus: {humanize(g[0])} {g[1]}".strip()
    if f == "CannotBeDisarmed":
        return "Cannot be disarmed"
    if f == "ItemReturnToOwner":
        return "Returns to the wielder when thrown"
    if f == "ActionResource":
        if g[0] == "Movement":
            return f"{_sign(g[1])}m movement speed"
        return f"{_sign(g[1])} {humanize(g[0])}"
    if f == "JumpMaxDistanceBonus":
        return f"{_sign(g[0])}m jump distance"
    if f == "IgnoreFallDamage":
        return "Immune to falling damage"
    if f == "SpellSaveDC":
        return f"{_sign(g[0])} spell save DC"
    if f == "Initiative":
        return f"{_sign(g[0])} Initiative"
    if f == "StatusImmunity":
        return f"Immune to {humanize(g[0])}"
    if f == "DarkvisionRangeMin":
        return f"Darkvision {g[0]}m"
    if f == "ReduceCriticalAttackThreshold":
        return f"Critical hit range +{g[0]}"
    if f == "UnlockSpellVariant":
        return f"Spell variant: {b}"
    if f == "Tag":
        return None
    if f in ("Reroll",):
        return f"Reroll {humanize(g[0])} rolls of {g[1]} or lower"
    if f == "MinimumRollResult":
        return f"Minimum {humanize(g[0])} roll {g[1]}"
    if f == "Attribute":
        return humanize(g[0])
    if f == "AttackSpellOverride":
        return f"Basic attack replaced by {g[0]}"
    return None


def GoldlessExpr(x):
    return x.replace("StrengthModifier", "Strength modifier").replace("DexterityModifier", "Dexterity modifier") \
        .replace("SpellcastingAbilityModifier", "spellcasting modifier").replace("ProficiencyBonus", "proficiency bonus")


def _sign(v):
    v = str(v).strip()
    return v if v.startswith(("-", "+")) else f"+{v}"


def cond_text(c):
    c = c.strip()
    m = re.match(r"^not\s+SavingThrow\(Ability\.(\w+),\s*(\d+)\)$", c)
    if m:
        return f"on a failed DC {m.group(2)} {m.group(1)} save"
    m = re.match(r"^HasHPPercentageEqualOrLessThan\((\d+)", c)
    if m:
        return f"while at or below {m.group(1)}% HP"
    return f"if {c}"


# ----------------------------------------------------------------------------------------------- extractor
class Extractor:
    def __init__(self):
        self.stats = _load_json("stats_resolved.json")
        self.loca = _load_json("loca_english.json")
        self.templates = load_templates()
        self.levels = _load_json("level_items_index.json")
        self.honour = load_honour_names()
        self.tags = load_tag_names()
        self.gold = GoldValues()
        lm = {a["Name"]: a for a in load_lsx_nodes("Public/Shared/Levelmaps/LevelMapValues.lsx", "LevelMapSeries")}
        self.tx = Texts(self.loca, self.stats, lm)
        self.unresolved = Counter()
        self.hidden = Counter()
        self.tpl_by_key = {t["MapKey"]: t for t in self.templates}
        # basic weapon actions = spells unlocked by plain WPN_ base entries
        self.basic_actions = set()
        for k, v in self.stats.items():
            if v.get("_type") == "Weapon" and k.startswith("WPN_"):
                for f in ("BoostsOnEquipMainHand", "BoostsOnEquipOffHand"):
                    self.basic_actions.update(re.findall(r"UnlockSpell\((\w+)", v.get(f, "")))

    # -- which entries are items
    def item_entries(self):
        uses = defaultdict(list)
        for t in self.templates:
            s = t.get("Stats") or (t.get("inherited") or {}).get("Stats")
            if s:
                uses[s].append(t)
        placement = defaultdict(list)
        for p in self.levels:
            if p.get("Stats"):
                placement[p["Stats"]].append(p)
        out = {}
        for name, s in self.stats.items():
            if s.get("_type") not in STATS_TYPES or name.startswith("_"):
                continue
            tpls = list(uses.get(name, []))
            own_rt = self._own_field(name, "RootTemplate")
            if own_rt and own_rt in self.tpl_by_key and own_rt not in {t["MapKey"] for t in tpls}:
                tpls.append(self.tpl_by_key[own_rt])
            if tpls or placement.get(name):
                out[name] = (tpls, placement.get(name, []))
        return out

    def _own_field(self, name, field):
        """Field value only if set by the entry itself (not inherited through `using`)."""
        s = self.stats.get(name)
        if not s:
            return None
        chain = s.get("_chain", [name])
        if len(chain) > 1:
            parent = self.stats.get(chain[1])
            if parent and parent.get(field) == s.get(field):
                return None
        return s.get(field)

    # -- effects
    def spell_effect(self, spell, raw, weapon_action=False):
        e = self.stats.get(spell)
        eff = {"kind": "spell", "id": spell, "name": None, "text": None, "raw": raw}
        if e is None:
            self.unresolved[f"spell:{spell}"] += 1
            eff["name"] = humanize(spell)
        else:
            n, d = self.tx.described(e, "spell", spell)
            eff["name"], eff["text"] = n or humanize(spell), d
            if not n:
                self.unresolved[f"spell-name:{spell}"] += 1
        if weapon_action:
            eff["weapon_action"] = True
        return eff

    def status_effect(self, status, raw, extra=None):
        e = self.stats.get(status)
        eff = {"kind": "status", "id": status, "name": None, "text": None, "raw": raw}
        if e is None:
            self.unresolved[f"status:{status}"] += 1
            eff["name"] = humanize(status)
            return eff
        n, d = self.tx.described(e, "status", status)
        btexts = [t for t in (self._boost_list_text(e.get("Boosts", ""))) if t]
        for p in split_top(e.get("Passives", "") or ""):
            pe = self.stats.get(p)
            if pe:
                pn, pd = self.tx.described(pe, "passive", p)
                btexts.append(f"{pn}: {pd}" if pn and pd else (pn or pd or humanize(p)))
        if not d and btexts:
            d = "; ".join(btexts)
        if extra:
            d = f"{d} ({extra})" if d else extra
        technical = not n
        eff["name"] = n or humanize(status)
        eff["text"] = d
        if technical:
            eff["technical"] = True
            if not d:
                # marker status: no boosts/text; the item's passives/spells check for it
                eff["hidden"] = True
                eff["text"] = "hidden technical marker (effect carried by the item's other passives/spells)"
                self.hidden[f"status:{status}"] += 1
        return eff

    def _boost_list_text(self, s):
        out = []
        for b in split_top(s or ""):
            cond, body = split_condition(b)
            t = boost_text(body)
            if t and cond:
                t = f"{t} {cond_text(cond)}"
            out.append(t)
        return out

    def passive_effect(self, pid, raw):
        e = self.stats.get(pid)
        eff = {"kind": "passive", "id": pid, "name": None, "text": None, "raw": raw}
        if e is None:
            self.unresolved[f"passive:{pid}"] += 1
            eff["name"] = humanize(pid)
            return eff
        n, d = self.tx.described(e, "passive", pid)
        if not d:
            bt = [t for t in self._boost_list_text(e.get("Boosts", "")) if t]
            d = "; ".join(bt) if bt else None
        hidden = "IsHidden" in (e.get("Properties") or "")
        if not n or hidden:
            eff["technical"] = True
            if not d:
                eff["hidden"] = True
                d = "hidden technical passive (bookkeeping for the item's other effects)"
                self.hidden[f"passive:{pid}"] += 1
        eff["name"], eff["text"] = n or humanize(pid), d
        return eff

    def boosts_effects(self, s, field, effects, spells):
        for b in split_top(s.get(field, "") or ""):
            cond, body = split_condition(b)
            f, args = parse_call(body)
            if f == "UnlockSpell" and args:
                sp = args[0]
                spells.append(sp)
                eff = self.spell_effect(sp, b, weapon_action=sp in self.basic_actions)
                if cond:
                    eff["condition"] = cond_text(cond)
                if field == "BoostsOnEquipOffHand":
                    eff["hand"] = "off"
                effects.append(eff)
                continue
            t = boost_text(body)
            if t is None and f in ("HiddenDuringCinematic", "Tag"):
                continue
            if t is None:
                self.unresolved[f"boost:{f}"] += 1
                t = body
            if cond:
                t = f"{t} {cond_text(cond)}"
            eff = {"kind": "boost", "id": f, "name": humanize(f), "text": t, "raw": b}
            if field == "BoostsOnEquipOffHand":
                eff["hand"] = "off"
            effects.append(eff)

    def functor_effects(self, s, effects):
        for fn in split_top(s.get("WeaponFunctors", "") or ""):
            cond, body = split_condition(fn)
            if body.startswith("GROUND:"):
                if "SurfaceChange(Ignite)" in body:
                    effects.append({"kind": "boost", "id": "WeaponFunctors", "name": "Ignites surfaces",
                                    "text": "Ignites flammable surfaces when burning (torch-like)", "raw": fn})
                continue
            f, args = parse_call(body)
            args = (args or []) + [""] * 7
            if f == "ApplyStatus":
                c = args[6] or cond
                dur = args[2]
                extra = "on hit" + (f", {dur} turns" if dur and dur not in ("-1", "1") else
                                    ", 1 turn" if dur == "1" else "") + (f", {cond_text(c)}" if c else "")
                eff = self.status_effect(args[0], fn, extra=extra)
                eff["on_hit"] = True
                effects.append(eff)
            elif f == "DealDamage":
                t = f"On hit: +{args[0]} {args[1]} damage" + (f" {cond_text(cond)}" if cond else "")
                effects.append({"kind": "boost", "id": "WeaponFunctors", "name": "Extra damage on hit",
                                "text": t, "raw": fn})
            elif f == "RemoveStatus":
                effects.append({"kind": "boost", "id": "WeaponFunctors", "name": "Removes status on hit",
                                "text": f"On hit removes {humanize(args[0])}" + (f" {cond_text(cond)}" if cond else ""),
                                "raw": fn})
            else:
                self.unresolved[f"functor:{f}"] += 1
                effects.append({"kind": "boost", "id": "WeaponFunctors", "name": "On-hit effect", "text": fn, "raw": fn})

    # -- record
    def record(self, name, tpls, placements):
        s = self.stats[name]
        notes = []
        # pick the primary template: the entry's RootTemplate if used, else first with a DisplayName
        def dn(t):
            v = t.get("DisplayName") or (t.get("inherited") or {}).get("DisplayName")
            return (v or {}).get("text")
        def ds(t):
            v = t.get("Description") or (t.get("inherited") or {}).get("Description")
            return (v or {}).get("text")
        primary = None
        rt = s.get("RootTemplate")
        for t in tpls:
            if t["MapKey"] == rt and dn(t):
                primary = t
        if primary is None:
            named = [t for t in tpls if dn(t)]
            if named:
                c = Counter(dn(t) for t in named)
                top = c.most_common(1)[0][0]
                primary = next(t for t in named if dn(t) == top)
            elif tpls:
                primary = tpls[0]
        nm = dn(primary) if primary else None
        de = ds(primary) if primary else None
        if not nm:
            nm = self.tx.clean(self.tx.loc(s.get("DisplayName")))
        if not de:
            de = self.tx.clean(self.tx.loc(s.get("Description")))
        if not nm and placements:
            for p in placements:
                if p.get("DisplayName"):
                    nm = (p["DisplayName"] or {}).get("text") if isinstance(p["DisplayName"], dict) else p["DisplayName"]
                    break
        if not nm:
            self.unresolved[f"name:{name}"] += 1
        alt = sorted({dn(t) for t in tpls if dn(t)} - {nm})
        icon = None
        if primary:
            icon = primary.get("Icon") or (primary.get("inherited") or {}).get("Icon")
        rarity = s.get("Rarity") or "Common"
        # weapon block
        props = [p for p in (s.get("Weapon Properties") or "").split(";") if p]
        profs = [p for p in (s.get("Proficiency Group") or "").split(";") if p]
        effects, spells = [], []
        for f in ("DefaultBoosts", "Boosts", "BoostsOnEquipMainHand", "BoostsOnEquipOffHand"):
            self.boosts_effects(s, f, effects, spells)
        for f in ("PassivesOnEquip", "PassivesMainHand", "PassivesOffHand"):
            for p in split_top(s.get(f, "") or ""):
                eff = self.passive_effect(p, p)
                if f == "PassivesOffHand":
                    eff["hand"] = "off"
                elif f == "PassivesMainHand":
                    eff["hand"] = "main"
                effects.append(eff)
        for st in split_top(s.get("StatusOnEquip", "") or ""):
            effects.append(self.status_effect(st, st))
        # root-template StatusList (permanent item statuses, e.g. Everburn's fire)
        tstat = Counter()
        for t in tpls:
            for st in (t.get("StatusList") or []):
                tstat[st] += 1
        for st in tstat:
            eff = self.status_effect(st, st)
            eff["source"] = "template StatusList"
            if tstat[st] < len(tpls):
                eff["templates_partial"] = True
            effects.append(eff)
        self.functor_effects(s, effects)
        enchant = None
        extra_dmg = []
        for e in effects:
            if e["kind"] == "boost" and e["id"] == "WeaponEnchantment":
                enchant = int(parse_call(e["raw"])[1][0])
            if e["kind"] == "boost" and e["id"] == "WeaponDamage" and not e["raw"].startswith("IF("):
                a = parse_call(e["raw"])[1]
                extra_dmg.append(f"{a[0]} {a[1]}")
            if e["kind"] == "status" and e.get("source") == "template StatusList":
                st = self.stats.get(e["id"]) or {}
                for b in split_top(st.get("Boosts", "") or ""):
                    f, a = parse_call(b)
                    if f == "WeaponDamage" and a and len(a) > 1:
                        extra_dmg.append(f"{a[0]} {a[1]}")
        weapon = None
        if s.get("Damage"):
            rng = s.get("WeaponRange")
            weapon = {
                "damage": s.get("Damage"),
                "versatile": s.get("VersatileDamage") or None,
                "damage_type": s.get("Damage Type"),
                "range": float(rng) / 100 if rng else None,
                "long_range": float(s["Damage Range"]) / 100 if s.get("Damage Range") else None,
                "properties": props,
                "proficiency": profs,
                "group": s.get("Weapon Group"),
                "enchantment": enchant,
                "extra_damage": extra_dmg,
            }
        boosts_raw = {k: s[k] for k in RAW_KEYS if s.get(k)}
        if tstat:
            boosts_raw["TemplateStatusList"] = ";".join(tstat)
        tags = sorted({self.tags.get(g, g) for t in tpls for g in (t.get("Tags") or [])})
        # honour
        hon = name in self.honour
        hon_bits = []
        if hon:
            hon_bits.append("stats entry: " + ", ".join(sorted(self.honour[name].keys())))
        for f in ("PassivesOnEquip", "PassivesMainHand", "PassivesOffHand", "StatusOnEquip"):
            for p in split_top(s.get(f, "") or ""):
                if p in self.honour:
                    hon = True
                    hon_bits.append(f"{p} changed")
        for sp in spells:
            if sp in self.honour and sp not in self.basic_actions:
                hon = True
                hon_bits.append(f"{sp} changed")
        if hon_bits:
            notes.append("Honour mode differs: " + "; ".join(hon_bits))
        chain = s.get("_chain", [])
        if "_SummonWeapons" in chain or "_PactWeapon" in chain or re.search(
                r"_Pact$|Conjure|Wildshape|WildShape|Myrmidon|FlameBlade|ShadowBlade|GuardianOfFaith|AnimateDead|"
                r"PlanarAlly", name):
            notes.append("summoned/conjured weapon (not normal loot)")
        if placements and not tpls:
            notes.append("only used via level placement Stats override")
        if s.get("UseConditions"):
            notes.append(f"UseConditions: {s['UseConditions']}")
        if not s.get("Slot"):
            notes.append("no Slot in stats")
        try:
            weight = float(s["Weight"]) if s.get("Weight") not in (None, "") else None
        except ValueError:
            weight = None
        rec = {
            "stats_id": name,
            "group": GROUP,
            "stats_type": s.get("_type"),
            "name": nm,
            "description": self.tx.clean(de),
            "templates": sorted({t["MapKey"] for t in tpls}),
            "icon": icon,
            "rarity": rarity,
            "unique": s.get("Unique") == "1",
            "slot": s.get("Slot"),
            "weight": weight,
            "value": self.gold.value(s),
            "weapon": weapon,
            "armour": None,
            "boosts_raw": boosts_raw,
            "effects": effects,
            "grants_spells": spells,
            "requirements": {"proficiency": profs},
            "tags": tags,
            "honour_override": hon,
            "notes": "; ".join(notes) if notes else None,
        }
        if alt:
            rec["alt_names"] = alt
        if placements:
            rec["placement_overrides"] = len(placements)
        rec["stats_chain"] = chain
        return rec

    def run(self):
        items = self.item_entries()
        return [self.record(n, *items[n]) for n in sorted(items)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    ex = Extractor()
    recs = ex.run()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(recs)} records -> {a.out}")
    print("by rarity:", dict(Counter(r["rarity"] for r in recs)))
    print("by slot:", dict(Counter(r["slot"] for r in recs)))
    print("unique:", sum(r["unique"] for r in recs), " honour_override:", sum(r["honour_override"] for r in recs))
    print("hidden technical passives/statuses (not failures):", len(ex.hidden))
    if a.report or ex.unresolved:
        print("unresolved:", len(ex.unresolved))
        for k, v in sorted(ex.unresolved.items()):
            print(f"  {k}  x{v}")


if __name__ == "__main__":
    main()
