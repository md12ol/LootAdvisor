"""Extract every armour / clothing / shield item of BG3 (Patch 8) -> data/items_all/armour.jsonl.

Follows data/items_all/SCHEMA.md (group = "armour"). Read-only on the game folder; uses the caches built by
build_cache.py (stats_resolved.json, roottemplates_*.json, loca_english.json, level_items_index.json) plus a
few small files read straight from the paks (Honour-mode Armor/Passive overrides, GoldValues.lsx, Tags/*.lsf).

Scope: stats entries of type Armor whose Slot is Breast, Helmet, Cloak, Gloves, Boots, Melee Offhand Weapon
(shields), VanityBody, VanityBoots or Underwear (NOT Amulet / Ring / MusicalInstrument), that a real item uses:
named by an item root template's Stats (own or inherited) or carrying a RootTemplate field. Names starting
with "_" (abstract bases) are skipped; their fields arrive through `using` inheritance.

  python extract_armour.py [--out PATH] [--report]
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "data", "cache")
OUT = os.path.join(ROOT, "data", "items_all", "armour.jsonl")
sys.path.insert(0, HERE)

SLOTS = {"Breast", "Helmet", "Cloak", "Gloves", "Boots", "Melee Offhand Weapon",
         "VanityBody", "VanityBoots", "Underwear"}

# 5e armour categories (dex cap: light none, medium 2, heavy 0)
ARMOUR_CATEGORY = {
    "Padded": "Light", "Leather": "Light", "StuddedLeather": "Light",
    "Hide": "Medium", "ChainShirt": "Medium", "ScaleMail": "Medium", "BreastPlate": "Medium", "HalfPlate": "Medium",
    "RingMail": "Heavy", "ChainMail": "Heavy", "Splint": "Heavy", "Plate": "Heavy",
}
DEX_CAP = {"Light": None, "Medium": 2, "Heavy": 0}

# ---------------------------------------------------------------- loading


def _load_json(name):
    with open(os.path.join(CACHE, name), encoding="utf-8") as f:
        return json.load(f)


def load_templates():
    """{MapKey: template} over every roottemplates_*.json cache (module stored in '_module')."""
    out = {}
    for fn in sorted(glob.glob(os.path.join(CACHE, "roottemplates_*.json"))):
        mod = os.path.basename(fn)[len("roottemplates_"):-5]
        with open(fn, encoding="utf-8") as f:
            for t in json.load(f):
                t["_module"] = mod
                out[t["MapKey"]] = t
    return out


def _pak_texts(paths_by_pak):
    from pak import Pak, GAME_DATA
    out = {}
    for pk, names in paths_by_pak.items():
        p = Pak(os.path.join(GAME_DATA, pk))
        for n in names:
            if n in p.by_name:
                out[n] = p.read(p.by_name[n])
        p.close()
    return out


_ENTRY = re.compile(r'^\s*(new entry|type|using|data)\s+"([^"]*)"(?:\s+"(.*)")?\s*$')


def parse_stats_txt(text):
    """Minimal stats .txt parser -> {name: {field: value}} (own data lines only)."""
    out, cur = {}, None
    for line in text.splitlines():
        m = _ENTRY.match(line)
        if not m:
            continue
        kw, a, b = m.groups()
        if kw == "new entry":
            cur = out[a] = {}
        elif kw == "data" and cur is not None:
            cur[a] = b if b is not None else ""
    return out


def load_honour():
    files = _pak_texts({"Gustav.pak": ["Public/Honour/Stats/Generated/Data/Armor.txt",
                                       "Public/Honour/Stats/Generated/Data/Passive.txt",
                                       "Public/Honour/Stats/Generated/Data/Status_BOOST.txt"]})
    arm = parse_stats_txt(files.get("Public/Honour/Stats/Generated/Data/Armor.txt", b"").decode("utf-8", "replace"))
    pas = parse_stats_txt(files.get("Public/Honour/Stats/Generated/Data/Passive.txt", b"").decode("utf-8", "replace"))
    st = parse_stats_txt(files.get("Public/Honour/Stats/Generated/Data/Status_BOOST.txt", b"").decode("utf-8", "replace"))
    return arm, pas, st


def load_gold_values():
    """GoldValues.lsx -> {uuid: {"name", "levels": {n: gold}, "parent", "scale"}}."""
    t = _pak_texts({"Shared.pak": ["Public/Shared/Levelmaps/GoldValues.lsx"]})
    text = t.get("Public/Shared/Levelmaps/GoldValues.lsx", b"").decode("utf-8", "replace")
    out = {}
    for blk in re.findall(r'<node id="GoldValue">(.*?)</node>', text, re.S):
        a = dict(re.findall(r'id="(\w+)" type="\w+" value="([^"]*)"', blk))
        lv = {int(k[5:]): int(v) for k, v in a.items() if re.fullmatch(r"Level\d+", k)}
        out[a["UUID"]] = {"name": a.get("Name"), "levels": lv, "parent": a.get("ParentUUID"),
                          "scale": float(a.get("ParentScale", 1))}
    return out


def load_refs():
    """Count references of stats ids in TreasureTable.txt ("I_<id>") and Equipment.txt (campaign modules)."""
    names = {"Shared.pak": [], "Gustav.pak": [], "GustavX.pak": []}
    for mod, pk in (("Shared", "Shared.pak"), ("SharedDev", "Shared.pak"), ("Gustav", "Gustav.pak"),
                    ("GustavDev", "Gustav.pak"), ("GustavX", "GustavX.pak")):
        for f in ("TreasureTable.txt", "Equipment.txt"):
            names[pk].append(f"Public/{mod}/Stats/Generated/{f}")
    texts = _pak_texts(names)
    tt, eq = collections.Counter(), collections.Counter()
    for n, b in texts.items():
        t = b.decode("utf-8", "replace")
        if n.endswith("TreasureTable.txt"):
            for m in re.finditer(r'object category "I_([^"]+)"', t):
                tt[m.group(1)] += 1
        else:
            for m in re.finditer(r'add equipment entry "([^"]+)"', t):
                eq[m.group(1)] += 1
    return {"treasure": tt, "equipment": eq}


def gold_value(gv, uuid, level):
    """Base gold of a value table at a level: walk ParentUUID up to a table with levels, multiplying scales."""
    mult, cur, seen = 1.0, gv.get(uuid), set()
    while cur and not cur["levels"] and cur["parent"] and cur["parent"] not in seen:
        seen.add(cur["parent"])
        mult *= cur["scale"]
        cur = gv.get(cur["parent"])
    if not cur or not cur["levels"]:
        return None
    lv = cur["levels"]
    lvl = max(min(level, max(lv)), min(lv))
    while lvl not in lv and lvl > 1:
        lvl -= 1
    return lv.get(lvl, 0) * mult


def round_sig(x, sig=2):
    if x < 100:
        return int(x + 0.5)
    import math
    f = 10 ** (int(math.floor(math.log10(x))) - sig + 1)
    return int(math.floor(x / f + 0.5) * f)


def item_value(gv, e):
    """Approximate gold value. Checked against bg3.wiki: exact for 8000/1600/90/40/190/290/3800/2900/2000,
    within ~2% otherwise (e.g. 1440 -> wiki 1450, 750 -> wiki 760)."""
    if e.get("ValueOverride"):
        return num(e["ValueOverride"], int)
    if not e.get("ValueUUID"):
        return None
    base = gold_value(gv, e["ValueUUID"], num(e.get("ValueLevel"), int) or 1)
    if base is None:
        return None
    return round_sig(base * (num(e.get("ValueScale")) or 1))


class TagNames:
    """Tag GUID -> tag Name, read lazily from Public/<module>/Tags/<uuid>.lsf."""

    def __init__(self):
        from pak import Pak, GAME_DATA
        self._paks, self._where, self._cache = {}, {}, {}
        for pk in ("Shared.pak", "Gustav.pak", "GustavX.pak"):
            p = Pak(os.path.join(GAME_DATA, pk))
            self._paks[pk] = p
            for e in p.entries:
                n = e.name
                if "/Tags/" in n and n.endswith(".lsf") and n.startswith("Public/"):
                    self._where[os.path.basename(n)[:-4]] = (pk, n)

    def get(self, uuid):
        if uuid in self._cache:
            return self._cache[uuid]
        name = None
        if uuid in self._where:
            import lsf
            pk, n = self._where[uuid]
            p = self._paks[pk]
            try:
                res = lsf.load(p.read(p.by_name[n]))
                name = res.regions[0].get("Name")
            except Exception:
                name = None
        self._cache[uuid] = name
        return name

    def close(self):
        for p in self._paks.values():
            p.close()


# ---------------------------------------------------------------- text helpers

def split_top(s, sep=";"):
    """Split on `sep` outside parentheses."""
    out, depth, cur = [], 0, []
    for ch in s or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def parse_call(s):
    """'Fn(a, b)' -> ('Fn', ['a','b']); 'IF(c):Fn(a)' -> ('Fn', ['a']) with cond via split_cond."""
    m = re.match(r"^\s*([A-Za-z_]\w*)\s*\((.*)\)\s*$", s, re.S)
    if not m:
        return s.strip(), None
    return m.group(1), split_top(m.group(2), ",")


def split_cond(s):
    """'IF(cond):Boost' -> (cond, boost); plain -> (None, s)."""
    s = s.strip()
    if s.startswith("IF("):
        depth = 0
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    rest = s[i + 1:].lstrip()
                    if rest.startswith(":"):
                        return s[3:i], rest[1:].strip()
                    break
    return None, s


def clean_markup(t):
    if t is None:
        return None
    t = re.sub(r"<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def param_text(p):
    """One DescriptionParams element -> display text."""
    p = p.strip()
    fn, args = parse_call(p)
    if args is None:
        return p
    a = args
    if fn == "DealDamage" and a:
        dmg = a[0]
        typ = a[1] if len(a) > 1 else ""
        return f"{dmg} {typ} damage".replace("  ", " ") if typ else f"{dmg} damage"
    if fn == "Distance" and a:
        return f"{a[0]}m"
    if fn == "RegainHitPoints" and a:
        return f"{a[0]} hit points"
    if fn == "GainTemporaryHitPoints" and a:
        return f"{a[0]} temporary hit points"
    if fn == "LevelMapValue" and a:
        return f"(level-scaled {a[0]})"
    if fn == "ApplyStatus" and a:
        return a[0]
    if fn in ("DamageBonus",) and a:
        return f"{a[0]} {a[1] if len(a) > 1 else ''} damage".replace("  ", " ")
    return p


def applied_statuses(functors):
    """Status ids applied by ApplyStatus(...) calls in a functor string (skips SELF/SWAP/... target prefix)."""
    out = []
    for m in re.finditer(r"ApplyStatus\(", functors or ""):
        depth, j = 1, m.end()
        while j < len(functors) and depth:
            depth += {"(": 1, ")": -1}.get(functors[j], 0)
            j += 1
        args = split_top(functors[m.end():j - 1], ",")
        if args and args[0].isupper() and args[0] in ("SELF", "SWAP", "OBSERVER_OBSERVER", "OBSERVER_TARGET",
                                                        "OBSERVER_SOURCE", "TARGET", "SOURCE") and len(args) > 1:
            args = args[1:]
        if args and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args[0]) and args[0] not in out:
            out.append(args[0])
    return out


# ---------------------------------------------------------------- resolver

ABIL = {"Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"}
ROLL = {"Attack": "attack rolls", "MeleeWeaponAttack": "melee weapon attack rolls",
        "RangedWeaponAttack": "ranged weapon attack rolls", "MeleeSpellAttack": "melee spell attack rolls",
        "RangedSpellAttack": "ranged spell attack rolls", "SpellAttack": "spell attack rolls",
        "MeleeAttack": "melee attack rolls", "RangedAttack": "ranged attack rolls",
        "WeaponAttack": "weapon attack rolls", "MeleeUnarmedAttack": "unarmed attack rolls",
        "RangedUnarmedAttack": "ranged unarmed attack rolls", "UnarmedAttack": "unarmed attack rolls",
        "SavingThrow": "saving throws", "AllSavingThrows": "all saving throws", "SkillCheck": "skill checks",
        "Skill": "skill checks", "RawAbility": "ability checks", "Ability": "ability checks",
        "AllAbilities": "all ability checks", "AllSkills": "all skill checks", "Damage": "damage rolls",
        "DeathSavingThrow": "death saving throws", "AttackTarget": "attack rolls against you",
        "Concentration": "Concentration saving throws", "MeleeOffHandWeaponAttack": "off-hand attack rolls",
        "Initiative": "Initiative"}


class Resolver:
    def __init__(self, stats, loca, honour_passives):
        self.st, self.loca, self.honour_passives = stats, loca, honour_passives
        self.unknown_boosts = collections.Counter()
        self.missing = collections.Counter()

    # -- names
    def loc(self, v):
        if not v:
            return None
        h = v.split(";")[0].strip()
        return self.loca.get(h)

    def name_of(self, sid):
        e = self.st.get(sid)
        if not e:
            return None
        n = self.loc(e.get("DisplayName"))
        if n and n.startswith("%%%"):
            return None
        return clean_markup(n)

    def desc_of(self, sid):
        e = self.st.get(sid)
        if not e:
            return None
        d = self.loc(e.get("Description"))
        if not d or d.startswith("%%%"):
            return None
        params = split_top(e.get("DescriptionParams") or "")
        def sub(m):
            i = int(m.group(1)) - 1
            return param_text(params[i]) if 0 <= i < len(params) else m.group(0)
        d = re.sub(r"\[(\d+)\]", sub, d)
        return clean_markup(d)

    # -- boosts
    def boost_text(self, raw):
        cond, b = split_cond(raw)
        fn, a = parse_call(b)
        t = self._boost(fn, a or [], b)
        if t is None:
            self.unknown_boosts[fn] += 1
            t = b
        if cond:
            t = f"{t} (if {cond.strip()})"
        return t

    def _boost(self, fn, a, b):
        g = lambda i, d="": a[i] if len(a) > i else d
        sign = lambda v: v if str(v).startswith("-") else f"+{v}"
        if fn == "AC":
            return f"{sign(g(0))} AC"
        if fn == "Ability":
            t = f"{sign(g(1))} {g(0)}"
            return t + (f" (max {g(2)})" if g(2) else "")
        if fn == "AbilityOverrideMinimum":
            return f"{g(0)} becomes at least {g(1)}"
        if fn == "RollBonus":
            what = ROLL.get(g(0), g(0))
            if g(2) and g(0) in ("SavingThrow", "SkillCheck", "Skill", "RawAbility", "Ability"):
                return f"{sign(g(1))} to {g(2)} {what}"
            return f"{sign(g(1))} to {what}" + (f" ({g(2)})" if g(2) else "")
        if fn in ("Advantage", "Disadvantage"):
            what = ROLL.get(g(0), g(0))
            if g(1):
                what = f"{g(1)} {what}" if g(0) in ("SavingThrow", "Ability", "Skill", "SkillCheck") else f"{what} ({g(1)})"
            return f"{fn} on {what}"
        if fn == "Skill":
            return f"{sign(g(1))} {g(0)}"
        if fn == "Resistance":
            kind = {"Resistant": "Resistance to", "Immune": "Immunity to", "Vulnerable": "Vulnerability to",
                    "ImmuneToMagical": "Immunity to magical", "ResistantToNonMagical": "Resistance to non-magical",
                    "ImmuneToNonMagical": "Immunity to non-magical", "ResistantToMagical": "Resistance to magical"}.get(g(1), g(1))
            return f"{kind} {g(0)} damage"
        if fn == "CriticalHit":
            if g(0) == "AttackTarget" and g(2) == "Never":
                return "Attacks against you can't be critical hits"
            return f"Critical hit rule: {', '.join(a)}"
        if fn == "ProficiencyBonus":
            return f"Proficiency in {g(1)} {ROLL.get(g(0), g(0))}".rstrip()
        if fn == "Proficiency":
            return f"Proficiency with {', '.join(a)}"
        if fn == "UnlockSpell":
            return f"Grants spell: {self.name_of(g(0)) or g(0)}"
        if fn == "UnlockInterrupt":
            return f"Grants reaction: {self.name_of(g(0)) or g(0)}"
        if fn == "UnlockSpellVariant":
            return "Modifies a spell variant: " + ", ".join(a)
        if fn == "StatusImmunity":
            return f"Immune to {self.name_of(g(0)) or g(0)}"
        if fn == "DamageReduction":
            return f"Reduce {g(0)} damage taken by {g(2)}" if g(1) == "Flat" else f"Damage reduction: {', '.join(a)}"
        if fn == "Initiative":
            return f"{sign(g(0))} Initiative"
        if fn == "SpellSaveDC":
            return f"{sign(g(0))} spell save DC"
        if fn in ("CharacterWeaponDamage", "WeaponDamage"):
            return f"Weapon attacks deal an extra {g(0)} {g(1)} damage".rstrip()
        if fn == "CharacterUnarmedDamage":
            return f"Unarmed attacks deal an extra {g(0)} {g(1)} damage".rstrip()
        if fn == "DamageBonus":
            return f"+{g(0)} {g(1)} damage".rstrip()
        if fn == "ActionResource":
            res = {"Movement": "m movement speed"}.get(g(0))
            return f"{sign(g(1))}{res}" if res else f"{sign(g(1))} {g(0)}" + (f" (level {g(2)})" if g(2) not in ("", "0") else "")
        if fn == "ActionResourceMultiplier":
            return f"{g(0)} x{float(g(1) or 100) / 100:g}"
        if fn == "ActionResourcePreventReduction":
            return f"{g(0)} can't be reduced"
        if fn == "ActionResourceOverride":
            return f"{g(0)} set to {g(1)}"
        if fn in ("DarkvisionRange", "DarkvisionRangeMin"):
            return f"Darkvision {g(0)}m" + (" (minimum)" if fn.endswith("Min") else " bonus")
        if fn == "JumpMaxDistanceBonus":
            return f"+{g(0)}m jump distance"
        if fn == "JumpMaxDistanceMultiplier":
            return f"Jump distance x{g(0)}"
        if fn == "IncreaseMaxHP":
            return f"{sign(g(0))} maximum hit points"
        if fn == "Tag":
            return f"Tag {g(0)}"
        if fn == "ItemReturnToOwner":
            return "Returns to its owner when thrown"
        if fn == "WeaponDamageResistance":
            return "Resistance to non-magical " + "/".join(a) + " damage"
        if fn == "IgnoreResistance":
            return f"Ignore {g(1)} {g(0)} resistance"
        if fn == "EntityThrowDamage":
            return f"{sign(g(0))} damage dice when throwing creatures/objects"
        if fn == "Attribute":
            return {"Grounded": "Cannot be pushed/knocked prone by forced movement (Grounded)"}.get(g(0), f"Attribute {g(0)}")
        if fn == "Reroll":
            return f"Reroll {ROLL.get(g(0), g(0))} of {g(1)} or lower"
        if fn == "FallDamageMultiplier":
            return f"Fall damage x{g(0)}"
        if fn == "TwoWeaponFighting":
            return "Add ability modifier to off-hand attack damage"
        if fn == "ReduceCriticalAttackThreshold":
            return f"Critical hit on {20 - int(g(0) or 0)}-20" if (g(0) or "").lstrip("-").isdigit() else f"Critical threshold -{g(0)}"
        if fn == "IgnoreSurfaceCover":
            return f"Sees through {g(0)}"
        if fn == "ACOverrideFormula":
            return f"Base AC becomes {g(0)}" + (" + Dexterity" if len(a) > 2 else "")
        if fn == "CarryCapacityMultiplier":
            return f"Carrying capacity x{g(0)}"
        if fn == "ActiveCharacterLight":
            return "Emits light"
        if fn == "MinimumRollResult":
            return f"Minimum {g(1)} on {ROLL.get(g(0), g(0))}"
        if fn == "SavantBoost" or fn == "NonLethal":
            return fn
        if fn == "Invisibility":
            return "Invisible"
        if fn == "TemporaryHP":
            return f"{g(0)} temporary hit points"
        if fn == "MovementSpeedLimit":
            return f"Movement speed limited ({g(0)})"
        if fn == "UnarmedMagicalProperty":
            return "Unarmed attacks count as magical"
        if fn == "SightRangeAdditive":
            return f"{sign(g(0))}m sight range"
        if fn == "Weight":
            return f"Weight {g(0)}"
        if fn == "HalveWeaponDamage":
            return "Weapon damage halved"
        if fn == "CannotHarmCauseEntity":
            return "Cannot harm the causing entity"
        if fn == "GameplayLight":
            return f"Light radius {g(0)}m"
        if fn == "Detach":
            return "Detached"
        if fn == "CriticalHitExtraDice":
            return f"+{g(0)} extra critical hit dice"
        if fn == "AddProficiencyToDamage":
            return "Add proficiency bonus to damage"
        if fn == "NullifyHealing":
            return "Cannot be healed"
        if fn == "SpellResistance":
            return "Advantage on saving throws against spells" if g(0) == "Resistant" else f"Spell resistance {g(0)}"
        if fn == "ExpertiseBonus":
            return f"Expertise in {g(0)}"
        if fn == "DownedStatus":
            return f"Downed status {g(0)}"
        if fn == "Lootable" or fn == "BlockRegainHP" or fn == "BlockVerbalComponent" or fn == "BlockSomaticComponent":
            return fn
        return None

    def boosts_list(self, s):
        return [(b, self.boost_text(b)) for b in split_top(s)]

    def grants(self, s):
        out = []
        for b in split_top(s):
            _, bb = split_cond(b)
            fn, a = parse_call(bb)
            if fn == "UnlockSpell" and a:
                out.append(a[0])
        return out

    # -- passives / spells / statuses
    def spell_effect(self, sid, raw):
        e = self.st.get(sid)
        if not e:
            self.missing[("spell", sid)] += 1
            return {"kind": "spell", "id": sid, "name": None, "text": f"(unresolved spell {sid})", "raw": raw}
        name = self.name_of(sid)
        desc = self.desc_of(sid) or ""
        bits = []
        uc = e.get("UseCosts") or ""
        if "ReactionActionPoint" in uc:
            bits.append("reaction")
        elif "BonusActionPoint" in uc:
            bits.append("bonus action")
        elif "ActionPoint" in uc:
            bits.append("action")
        for m in re.findall(r"SpellSlot\w*:(\d+):(\d+)", uc):
            bits.append(f"uses a level {m[1]} spell slot" if m[1] != "0" else "uses a spell slot")
        cd = e.get("Cooldown") or ""
        cd_txt = {"OncePerTurn": "once per turn", "OncePerCombat": "once per combat",
                  "OncePerShortRest": "once per short rest", "OncePerRest": "once per long rest",
                  "OncePerShortRestPerItem": "once per short rest", "OncePerRestPerItem": "once per long rest"}.get(cd)
        if cd_txt:
            bits.append(cd_txt)
        cont = e.get("ContainerSpells")
        if cont:
            kids = [self.name_of(c) or c for c in cont.split(";") if c.strip()]
            desc = (desc + " Options: " + ", ".join(kids)).strip()
        text = desc + (f" ({', '.join(bits)})" if bits else "")
        return {"kind": "spell", "id": sid, "name": name, "text": text.strip(), "raw": raw}

    def passive_effect(self, pid):
        e = self.st.get(pid)
        if not e or e.get("_type") != "PassiveData":
            self.missing[("passive", pid)] += 1
            return {"kind": "passive", "id": pid, "name": None, "text": f"(unresolved passive {pid})", "raw": pid}
        hidden = "IsHidden" in (e.get("Properties") or "")
        name = self.name_of(pid)
        boosts = e.get("Boosts") or ""
        rawbits = [f"{k}={e[k]}" for k in ("Boosts", "BoostConditions", "StatsFunctorContext", "Conditions",
                                             "StatsFunctors", "ToggleOnFunctors") if e.get(k)]
        if hidden or not self.desc_of(pid):
            parts = [t for _, t in self.boosts_list(boosts)]
            fx = e.get("StatsFunctors") or e.get("ToggleOnFunctors") or ""
            for st in applied_statuses(fx):
                sn = self.name_of(st)
                sd = self.desc_of(st)
                parts.append(f"applies {sn or st}" + (f": {sd}" if sd else ""))
            text = "; ".join(parts) or (self.desc_of(pid) or "")
            if e.get("BoostConditions"):
                text += f" (if {e['BoostConditions']})"
            if hidden:
                name = (name + " (hidden)") if name else "(hidden passive)"
        else:
            text = self.desc_of(pid)
        if not text:
            text = "technical passive (no effect of its own; supports the item's other effects)"
        out = {"kind": "passive", "id": pid, "name": name, "text": text, "raw": "; ".join(rawbits) or pid}
        if pid in self.honour_passives:
            out["honour_override"] = True
        return out

    def status_effect(self, sid, depth=0):
        e = self.st.get(sid)
        if not e or e.get("_type") != "StatusData":
            self.missing[("status", sid)] += 1
            return {"kind": "status", "id": sid, "name": None, "text": f"(unresolved status {sid})", "raw": sid}
        name, desc = self.name_of(sid), self.desc_of(sid)
        rawbits = [f"{k}={e[k]}" for k in ("Boosts", "Passives", "OnApplyFunctors", "TickFunctors",
                                             "AuraStatuses") if e.get(k)]
        if desc and name:
            text = desc
        else:  # technical status: describe what it does
            parts = [t for _, t in self.boosts_list(e.get("Boosts") or "")]
            for p in split_top(e.get("Passives") or ""):
                pe = self.passive_effect(p)
                parts.append(f"{pe['name'] or p}: {pe['text']}")
            fx = " ".join(e.get(k) or "" for k in ("OnApplyFunctors", "TickFunctors", "AuraStatuses"))
            for st in applied_statuses(fx):
                if st == sid:
                    continue
                if depth < 2:
                    se = self.status_effect(st, depth + 1)
                    parts.append(f"applies {se['name'] or st}" + (f": {se['text']}" if se["text"] else ""))
                else:
                    parts.append(f"applies {self.name_of(st) or st}")
            text = "; ".join(parts) or desc or ""
            if not text:
                text = "technical marker status (no effect of its own; supports the item's passives)"
        return {"kind": "status", "id": sid, "name": name, "text": text, "raw": "; ".join(rawbits) or sid}


# ---------------------------------------------------------------- main build

def num(v, typ=float):
    try:
        return typ(v)
    except (TypeError, ValueError):
        return None


def tmpl_text(t, field):
    v = t.get(field) or t.get("inherited", {}).get(field)
    return v.get("text") if isinstance(v, dict) else None


def build(report=False):
    stats = _load_json("stats_resolved.json")
    loca = _load_json("loca_english.json")
    T = load_templates()
    honour_arm, honour_pas, _ = load_honour()
    gv = load_gold_values()
    tags = TagNames()
    R = Resolver(stats, loca, set(honour_pas))

    by_stats = collections.defaultdict(list)
    for t in T.values():
        s = t.get("Stats") or t.get("inherited", {}).get("Stats")
        if s:
            by_stats[s].append(t)
    placements = collections.Counter()
    for x in _load_json("level_items_index.json"):
        if x.get("Stats"):
            placements[x["Stats"]] += 1

    recs, problems, dead = [], [], []
    refs = load_refs()
    for sid, e in stats.items():
        if e.get("_type") != "Armor" or e.get("Slot") not in SLOTS or sid.startswith("_"):
            continue
        own_t = sorted(by_stats.get(sid, []), key=lambda t: (t["MapKey"] != e.get("RootTemplate"), t["MapKey"]))
        rt = e.get("RootTemplate")
        if not own_t and rt not in T:
            if rt:
                dead.append(sid)
            continue
        notes = []
        if own_t:
            templates = [t["MapKey"] for t in own_t]
            name_t = [t for t in own_t if tmpl_text(t, "DisplayName")]
        else:
            templates = [rt] if rt in T else []
            name_t = [T[rt]] if rt in T and tmpl_text(T[rt], "DisplayName") else []
            if rt in T:
                base = T[rt].get("Stats") or T[rt].get("inherited", {}).get("Stats")
                notes.append(f"no root template names this stats id; spawned via stats RootTemplate "
                             f"{rt} (a template of '{base}'), e.g. from treasure tables")
        name = tmpl_text(name_t[0], "DisplayName") if name_t else None
        desc = None
        for t in (name_t or own_t):
            desc = tmpl_text(t, "Description")
            if desc:
                break
        if not name:
            name = R.name_of(sid)
            if name:
                notes.append("name from stats DisplayName")
        if not desc:
            desc = R.desc_of(sid)
        alt = sorted({tmpl_text(t, "DisplayName") for t in name_t} - {name, None})
        if alt:
            notes.append("other template names: " + " | ".join(alt))
        icon = None
        for t in (own_t or ([T[rt]] if rt in T else [])):
            icon = t.get("Icon") or t.get("inherited", {}).get("Icon")
            if icon:
                break
        tag_ids = []
        for t in (own_t or ([T[rt]] if rt in T else [])):
            for g in t.get("Tags", []):
                if g not in tag_ids:
                    tag_ids.append(g)
        tag_names = [tags.get(g) or g for g in tag_ids]
        if any(t.get("StoryItem") for t in own_t):
            notes.append("story item template")
        tt, eq = refs["treasure"].get(sid, 0), refs["equipment"].get(sid, 0)
        if tt or eq:
            notes.append(f"referenced by {tt} treasure-table line(s), {eq} equipment-set entry(ies)")
        elif not own_t and not placements.get(sid):
            notes.append("possibly unused: not referenced by any root template, treasure table, equipment set "
                         "or level placement (could still be granted by story scripts)")
        if placements.get(sid):
            notes.append(f"{placements[sid]} level placement(s) override Stats to this id")

        rarity = e.get("Rarity") or "Common"
        slot = e.get("Slot")
        boosts = e.get("Boosts") or ""
        dboosts = e.get("DefaultBoosts") or ""
        passives = split_top(e.get("PassivesOnEquip") or "")
        statuses = split_top(e.get("StatusOnEquip") or "")

        # effects
        effects, grants = [], []
        for src in (boosts, dboosts):
            for b in split_top(src):
                cond, bb = split_cond(b)
                fn, a = parse_call(bb)
                if fn == "UnlockSpell" and a:
                    eff = R.spell_effect(a[0], b)
                    if cond:
                        eff["text"] += f" (if {cond})"
                    effects.append(eff)
                    grants.append(a[0])
                else:
                    effects.append({"kind": "boost", "id": fn, "name": None, "text": R.boost_text(b), "raw": b})
        for p in passives:
            effects.append(R.passive_effect(p))
            pe = stats.get(p) or {}
            for s in R.grants(pe.get("Boosts") or ""):
                if s not in grants:
                    grants.append(s)
                    effects.append(R.spell_effect(s, f"via passive {p}"))
        for s in statuses:
            effects.append(R.status_effect(s))
            se = stats.get(s) or {}
            for sp in R.grants(se.get("Boosts") or ""):
                if sp not in grants:
                    grants.append(sp)
                    effects.append(R.spell_effect(sp, f"via status {s}"))
        for ef in effects:
            if ef["text"] and ef["text"].startswith("(unresolved"):
                problems.append((sid, ef["text"]))

        # armour block
        at = e.get("ArmorType")
        cat = ARMOUR_CATEGORY.get(at)
        is_shield = e.get("Shield") == "Yes"
        ac = num(e.get("ArmorClass"), int)
        ac_boost = 0
        ac_cond = []
        for b in split_top(boosts):
            cond, bb = split_cond(b)
            fn, a = parse_call(bb)
            if fn == "AC" and a and num(a[0], int) is not None:
                if cond:
                    ac_cond.append(b)
                else:
                    ac_boost += int(a[0])
        for p in passives:  # conditional AC from passives (e.g. Defence-style bonus)
            pe = stats.get(p) or {}
            for b in split_top(pe.get("Boosts") or ""):
                cond, bb = split_cond(b)
                if parse_call(bb)[0] == "AC":
                    ac_cond.append(f"{p}: {b}" + (f" if {pe['BoostConditions']}" if pe.get("BoostConditions") else ""))
        stealth = any("Disadvantage(Skill,Stealth)" in b.replace(" ", "") for b in split_top(boosts))
        prof_group = e.get("Proficiency Group") or ""
        prof = [p for p in prof_group.split(";") if p]
        aca = e.get("Armor Class Ability")
        cap_field = num(e.get("Ability Modifier Cap"), int)
        if slot == "Breast" and ac is not None:
            if aca == "None":
                dex_cap = 0
            elif cap_field is not None:
                dex_cap = cap_field
            elif e.get("Ability Modifier Cap") == "" and cat == "Medium":
                dex_cap = None  # entry clears the medium-armour cap (Exotic Material)
                notes.append("no Dexterity cap: entry clears 'Ability Modifier Cap' (medium armour)")
            else:
                dex_cap = DEX_CAP.get(cat) if cat else None
        else:
            dex_cap = None
        if at in ("Cloth", "None", None):
            armor_type = "Clothing" if slot in ("Breast", "VanityBody", "Underwear") else (at or "None")
        else:
            armor_type = at
        armour = {
            "ac": ac, "ac_boost": ac_boost or 0,
            "ac_total": (ac or 0) + ac_boost if (ac is not None or ac_boost) else None,
            "ac_conditional": ac_cond,
            "armor_type": armor_type, "armor_type_raw": at, "category": cat or ("Shield" if is_shield else None),
            "dex_cap": dex_cap, "ac_ability": aca, "shield": is_shield, "stealth_disadvantage": stealth,
            "proficiency": prof,
        }
        if not prof and (cat or is_shield):
            notes.append("no proficiency requirement (Proficiency Group empty)")

        # value (gold): GoldValues table chain at ValueLevel x ValueScale, shown to 2 significant digits
        value = item_value(gv, e)
        honour = sid in honour_arm
        if honour:
            hv = item_value(gv, {**e, **honour_arm[sid]})
            notes.append("Honour mode overrides: " + ", ".join(f"{k}={v}" for k, v in honour_arm[sid].items())
                         + (f" (Honour value ~{hv})" if hv != value else ""))
        if not name:
            problems.append((sid, "no name"))

        rec = {
            "stats_id": sid, "group": "armour", "stats_type": "Armor",
            "name": name, "description": clean_markup(desc),
            "templates": templates, "icon": icon,
            "rarity": rarity, "unique": e.get("Unique") == "1",
            "slot": slot, "weight": num(e.get("Weight")), "value": value,
            "weapon": None, "armour": armour,
            "boosts_raw": {k: e[k] for k in ("Boosts", "DefaultBoosts", "BoostsOnEquipMainHand",
                                              "BoostsOnEquipOffHand", "PassivesOnEquip", "PassivesMainHand",
                                              "PassivesOffHand", "StatusOnEquip") if e.get(k)},
            "effects": effects,
            "grants_spells": grants,
            "requirements": {"proficiency": prof},
            "tags": tag_names,
            "honour_override": honour,
            "notes": "; ".join(notes),
        }
        recs.append(rec)
    tags.close()
    for sid in dead:
        problems.append((sid, f"skipped: RootTemplate {stats[sid].get('RootTemplate')} is not an item root template"))
    return recs, problems, R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    recs, problems, R = build()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in sorted(recs, key=lambda r: (r["slot"], r["stats_id"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(recs)} records -> {args.out}")
    c = collections.Counter((r["slot"], r["rarity"]) for r in recs)
    rar = ["Common", "Uncommon", "Rare", "VeryRare", "Legendary"]
    print("slot".ljust(22) + "".join(x[:8].rjust(9) for x in rar) + "    total")
    for s in sorted({r["slot"] for r in recs}):
        print(s.ljust(22) + "".join(str(c[(s, x)]).rjust(9) for x in rar) + str(sum(c[(s, x)] for x in rar)).rjust(9))
    print("by rarity:", dict(collections.Counter(r["rarity"] for r in recs)))
    print("problems:", len(problems))
    for p in problems[:50]:
        print("  ", p)
    print("unknown boost functions:", dict(R.unknown_boosts))
    print("missing refs:", dict(R.missing))


if __name__ == "__main__":
    main()
