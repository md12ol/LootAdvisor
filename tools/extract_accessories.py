"""Extract every BG3 accessory (rings, amulets, musical instruments) plus build-relevant consumables
(elixirs, potions, oils, permanent-boost items) into data/items_all/accessories.jsonl (schema: data/items_all/SCHEMA.md).

  python extract_accessories.py [--out PATH] [--check NAME ...]

Inputs (read-only): data/cache/{stats_resolved,loca_english,roottemplates_*,level_items_index}.json, plus the game paks
(read-only) for the root templates' use actions, Honour-mode stats, GoldValues and Tags.

Selection
 - Armor stats entries whose Slot is Amulet / Ring / MusicalInstrument and that a real item uses
   (named by an item root template's own or inherited Stats, by a level placement's Stats override, or by the
   entry's RootTemplate field). Abstract "_..." bases are skipped (their fields are inherited anyway).
 - Object stats entries used by item templates whose OnUsePeaceActions consume a status (ActionType 7) and which are
   potions/elixirs/oils (ItemUseType Potion) or grant permanent / long-rest boosts (Ethel's hair, Volo's eye,
   tadpole jars, Necromancy of Thay ...). Drinks/food/soap and the "Gale eats a magic item" action are skipped.
   One record per (stats id, consumed status set); when a generic stats id is shared by several different
   consumables the record key becomes "<stats id>@<STATUS>" (see "notes").
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lsf  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402
import stats as stats_mod  # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(ROOT, "data", "cache")
OUT_DEFAULT = os.path.join(ROOT, "data", "items_all", "accessories.jsonl")
GROUP = "accessories"
ACCESSORY_SLOTS = {"Amulet", "Ring", "MusicalInstrument"}
NULL_GUID = "00000000-0000-0000-0000-000000000000"
BOOST_FIELDS = ["Boosts", "DefaultBoosts", "BoostsOnEquipMainHand", "BoostsOnEquipOffHand", "PassivesOnEquip",
                "PassivesMainHand", "PassivesOffHand", "StatusOnEquip"]
OBJECT_DEFAULT_BOOST = re.compile(r"^CriticalHit\(AttackTarget,\s*(Success|Failure),\s*Never\)$")
ABILITIES = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]
ABBR = {a[:3].lower(): a for a in ABILITIES}
# consumed statuses that are not build relevant (drinking, eating, washing, Gale's item-eating)
SKIP_STATUS_PREFIX = ("DRINK_", "FOOD", "SOAP_", "ORI_GALE_AVATAR_CONSUMEITEM", "WYR_FACEPAINT", "GOB_ROASTINGDWARF",
                      "HAG_UPSETSTOMACH", "HAG_DETOX", "DRUG_", "CONS_DRUG")
# non-potion consumables that still matter for builds (status id prefixes / stats ids)
EXTRA_STATUS_PREFIX = ("HAG_HAIR_",)
EXTRA_STATS = {"UNI_Volo_ErsatzEye", "FOR_DangerousBook", "OBJ_TadpolePowerJar"}
# effects applied by story scripts (not by the template's use action): stats id -> [(kind, id)] + note
SCRIPTED = {
    "UNI_Volo_ErsatzEye": ([("status", "CAMP_VOLO_ERSATZEYE")], "eye is implanted by Volo (story); permanent"),
    "FOR_DangerousBook": ([("passive", "CTY_NecromancyOfThay_ForbiddenKnowledge_Passive")],
                          "reading the book (story checks) can grant the Forbidden Knowledge passive; permanent"),
    "OBJ_TadpolePowerJar": ([], "consuming the specimen unlocks one illithid power (tadpole point); permanent"),
}


# ---------------------------------------------------------------- loading
def load_json(name):
    with open(os.path.join(CACHE, name), encoding="utf-8") as f:
        return json.load(f)


def load_templates():
    """MapKey -> template dict (from the cache), plus effective Stats."""
    tm = {}
    for fn in sorted(glob.glob(os.path.join(CACHE, "roottemplates_*.json"))):
        mod = os.path.basename(fn)[len("roottemplates_"):-5]
        with open(fn, encoding="utf-8") as f:
            for t in json.load(f):
                t["_module"] = mod
                tm[t["MapKey"]] = t
    return tm


def tget(t, field):
    v = t.get(field)
    if v is None:
        v = (t.get("inherited") or {}).get(field)
    return v


def load_template_actions():
    """MapKey -> {"parent", "use": [(ActionType, attrs)], "script": {param: value}} from the root template LSFs."""
    out = {}
    for pk in ["Shared.pak", "Gustav.pak", "GustavX.pak"]:
        p = Pak(os.path.join(GAME_DATA, pk))
        for n in p.by_name:
            if not re.match(r"^Public/[^/]+/RootTemplates/_merged\.lsf$", n):
                continue
            res = lsf.load(p.read(p.by_name[n]))
            for go in res.regions[0].children:
                if go.get("Type") != "item":
                    continue
                use, script = [], {}
                for c in go.children:
                    if c.name == "OnUsePeaceActions":
                        for a in c.children:
                            attrs = {}
                            for at in a.children:
                                attrs.update({k: v for k, (_t, v) in at.attrs.items()})
                            use.append((a.get("ActionType"), attrs))
                    elif c.name == "Scripts":
                        for sc in c.children:
                            for pars in sc.children:
                                for par in pars.children:
                                    script[par.get("MapKey")] = par.get("Value")
                out[go.get("MapKey")] = {"parent": go.get("ParentTemplateId"), "use": use, "script": script}
        p.close()
    return out


def inherited_action(acts, key, field):
    seen = 0
    while key in acts and seen < 40:
        v = acts[key][field]
        if v:
            return v
        key = acts[key]["parent"]
        seen += 1
    return None


def load_honour_stats():
    """Names of stats entries redefined by the Honour / HonourX modules."""
    names = {}
    for pk in ["Gustav.pak", "GustavX.pak"]:
        p = Pak(os.path.join(GAME_DATA, pk))
        for n in p.by_name:
            parts = n.split("/")
            if len(parts) > 2 and parts[1] in ("Honour", "HonourX") and "/Stats/Generated/Data/" in n \
                    and n.endswith(".txt"):
                stats_mod._parse(p.read(p.by_name[n]).decode("utf-8", "replace"), parts[1], n, names)
        p.close()
    return names


def load_gold_values():
    p = Pak(os.path.join(GAME_DATA, "Shared.pak"))
    txt = p.read(p.by_name["Public/Shared/Levelmaps/GoldValues.lsx"]).decode("utf-8")
    p.close()
    nodes = {}
    for m in re.finditer(r'<node id="GoldValue">(.*?)</node>', txt, re.S):
        attrs = dict(re.findall(r'<attribute id="([^"]+)" type="[^"]+" value="([^"]*)"', m.group(1)))
        nodes[attrs.get("UUID")] = attrs
    return nodes


def gold_value(nodes, uuid, level, _depth=0):
    n = nodes.get(uuid)
    if not n or _depth > 20:
        return None
    lv = n.get(f"Level{level}")
    if lv is not None:
        return float(lv)
    if n.get("ParentUUID"):
        base = gold_value(nodes, n["ParentUUID"], level, _depth + 1)
        return None if base is None else base * float(n.get("ParentScale", 1))
    return None


def load_tags():
    tags = {}
    for pk in ["Shared.pak", "Gustav.pak", "GustavX.pak"]:
        p = Pak(os.path.join(GAME_DATA, pk))
        for n in p.by_name:
            if n.startswith("Public/") and "/Tags/" in n and n.endswith(".lsf"):
                try:
                    r = lsf.load(p.read(p.by_name[n]))
                    a = r.regions[0]
                    tags[a.get("UUID")] = a.get("Name")
                except Exception:  # noqa: BLE001 - a broken tag file only loses a name
                    pass
        p.close()
    return tags


# ---------------------------------------------------------------- text helpers
class Ctx:
    def __init__(self):
        self.st = load_json("stats_resolved.json")
        self.loca = load_json("loca_english.json")


def loca_text(ctx, val):
    if not val:
        return None
    if isinstance(val, dict):
        return val.get("text") or ctx.loca.get(val.get("handle"))
    return ctx.loca.get(val.split(";")[0])


def split_top(s, sep=";"):
    """Split on sep outside parentheses."""
    out, depth, cur = [], 0, []
    for ch in s:
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


def call_parts(s):
    m = re.match(r"^\s*([A-Za-z_][\w.]*)\s*\((.*)\)\s*$", s, re.S)
    if not m:
        return s.strip(), None
    return m.group(1), split_top(m.group(2), ",")


def fmt_param(p):
    fn, args = call_parts(p)
    if args is None:
        return p.strip()
    if fn == "DealDamage" and args:
        dmg = {"MainMeleeWeapon": "weapon", "MainRangedWeapon": "ranged weapon", "OffhandMeleeWeapon": "off-hand weapon"}
        typ = args[1] if len(args) > 1 else ""
        typ = "" if typ.endswith("DamageType") else typ
        return f"{dmg.get(args[0], args[0])} {typ} damage".replace("  ", " ")
    if fn == "Distance" and args:
        return f"{args[0]}m"
    if fn == "RegainHitPoints" and args:
        return f"{args[0]} hit points"
    if fn == "GainTemporaryHitPoints" and args:
        return f"{args[0]} temporary hit points"
    if fn in ("LevelMapValue",) and args:
        return args[0]
    return ", ".join(args) if args else fn


def clean_markup(text, params=None):
    if text is None:
        return None
    if params:
        ps = split_top(params, ";")

        def sub(m):
            i = int(m.group(1)) - 1
            return fmt_param(ps[i]) if 0 <= i < len(ps) else m.group(0)
        text = re.sub(r"\[(\d+)\]", sub, text)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def entry_text(ctx, e):
    """(name, description) of a stats entry; technical "%%% ..." names count as no name."""
    if not e:
        return None, None
    nm = clean_markup(loca_text(ctx, e.get("DisplayName")))
    if nm and nm.startswith("%%%"):
        nm = None
    return nm, clean_markup(loca_text(ctx, e.get("Description")), e.get("DescriptionParams"))


# ---------------------------------------------------------------- boost formatting
def _sign(v):
    v = v.strip()
    return v if v.startswith("-") else "+" + v


def boost_text(b):
    """One Boosts element -> short readable text (falls back to the raw string)."""
    cond = None
    m = re.match(r"^IF\((.*)\):(.*)$", b.strip(), re.S)
    if m:
        cond, b = m.group(1).strip(), m.group(2).strip()
    fn, a = call_parts(b)
    a = a or []
    t = None
    try:
        if fn == "AC":
            t = f"AC {_sign(a[0])}"
        elif fn == "Ability":
            t = f"{a[0]} {_sign(a[1])}" + (f" (max {a[2]})" if len(a) > 2 else "")
        elif fn == "AbilityOverrideMinimum":
            t = f"{a[0]} becomes at least {a[1]}"
        elif fn == "Advantage":
            t = "Advantage on " + " ".join(a)
        elif fn == "Disadvantage":
            t = "Disadvantage on " + " ".join(a)
        elif fn == "Resistance":
            t = f"{a[1]} to {a[0]} damage"
        elif fn == "StatusImmunity":
            t = f"Immune to status {a[0]}"
        elif fn == "UnlockSpell":
            t = f"Grants spell {a[0]}"
        elif fn == "UnlockInterrupt":
            t = f"Grants reaction {a[0]}"
        elif fn == "RollBonus":
            t = f"{_sign(a[1])} to {a[0]} rolls" + (f" ({a[2]})" if len(a) > 2 else "")
        elif fn == "SpellSaveDC":
            t = f"Spell save DC {_sign(a[0])}"
        elif fn == "Initiative":
            t = f"Initiative {_sign(a[0])}"
        elif fn == "WeaponEnchantment":
            t = f"Weapon enchantment {_sign(a[0])}"
        elif fn == "DamageBonus":
            t = f"{_sign(a[0])} {a[1] if len(a) > 1 else ''} damage".replace("  ", " ")
        elif fn == "IncreaseMaxHP":
            t = f"Max HP {_sign(a[0])}"
        elif fn == "Skill":
            t = f"{a[0]} {_sign(a[1])}"
        elif fn == "ProficiencyBonus":
            t = f"Proficiency in {' '.join(a)}"
        elif fn == "Proficiency":
            t = f"Proficiency with {a[0]}"
        elif fn == "ExpertiseBonus":
            t = f"Expertise in {a[0]}"
        elif fn == "ActionResource":
            t = f"{_sign(a[1])} {a[0]}" + (f" (level {a[2]})" if len(a) > 2 and a[2] not in ("0",) else "")
        elif fn == "ActionResourceMultiplier":
            t = f"{a[0]} x{int(a[1]) / 100:g}" if a[1].isdigit() else b
        elif fn == "ActionResourceOverride":
            t = f"{a[0]} set to {a[1]}"
        elif fn == "ReduceCriticalAttackThreshold":
            t = f"Critical hit range +{a[0]}"
        elif fn == "CriticalHit":
            t = f"Critical hit {a[0]} {a[1]}: {a[2]}"
        elif fn == "DarkvisionRangeMin":
            t = f"Darkvision {a[0]}m"
        elif fn == "DarkvisionRange":
            t = f"Darkvision range {_sign(a[0])}m"
        elif fn == "SavingThrow":
            t = f"{a[0]} saving throws {_sign(a[1])}"
        elif fn == "ACOverrideFormula":
            t = f"AC becomes {a[0]}" + (" + Dex" if len(a) > 1 and a[1].lower() == "true" else "")
        elif fn == "MinimumRollResult":
            t = f"Minimum {a[0]} roll {a[1]}"
        elif fn == "TemporaryHP":
            t = f"{a[0]} temporary HP"
        elif fn == "Tag":
            t = f"Tag {a[0]}"
        elif fn == "Reroll":
            t = f"Reroll {a[0]} rolls of {a[1]} or lower"
        elif fn == "CharacterWeaponDamage" or fn == "CharacterUnarmedDamage":
            t = f"{'Weapon' if fn == 'CharacterWeaponDamage' else 'Unarmed'} attacks +{a[0]} {a[1] if len(a) > 1 else ''}".strip()
        elif fn == "SpellResistance":
            t = f"{a[0]} against spells"
        elif fn == "MovementSpeedBonus" or fn == "ObjectSize" or fn == "ObjectSizeOverride":
            t = f"{fn} {_sign(a[0])}" if fn == "MovementSpeedBonus" else f"{fn} {a[0]}"
        elif fn == "JumpMaxDistanceMultiplier":
            t = f"Jump distance x{a[0]}"
        elif fn == "JumpMaxDistanceBonus":
            t = f"Jump distance {_sign(a[0])}m"
        elif fn == "HalveWeaponDamage":
            t = "Halve weapon damage"
        elif fn == "Invulnerable":
            t = "Invulnerable"
        elif fn == "NonLethal":
            t = "Attacks are non-lethal"
        elif fn == "DamageReduction":
            t = f"Reduce {a[0]} damage by {a[2] if len(a) > 2 else a[1]}"
        elif fn == "IgnoreResistance":
            t = f"Ignore {a[1]} to {a[0]}"
        elif fn == "Weight" or fn == "CarryCapacityMultiplier":
            t = f"{fn} {a[0]}"
        elif fn == "BlockRegainHP":
            t = "Cannot regain HP"
        elif fn == "UnlockSpellVariant":
            t = "Spell variant: " + ", ".join(a)
        elif fn == "ActiveCharacterLight":
            t = "Emits light"
        elif fn == "Attribute":
            t = f"Attribute {a[0]}"
    except (IndexError, ValueError):
        t = None
    t = t or b.strip()
    if cond:
        t = f"{t} (if {cond})"
    return t


def boost_effects(ctx, s, field, seen=None):
    effects = []
    for b in split_top(s or ""):
        inner = re.sub(r"^IF\(.*?\):", "", b)
        fn, a = call_parts(inner)
        if fn == "UnlockSpell" and a:
            effects.append(spell_effect(ctx, a[0], raw=b, field=field))
        elif fn == "UnlockInterrupt" and a:
            e = ctx.st.get(a[0])
            nm, desc = entry_text(ctx, e)
            effects.append({"kind": "spell", "id": a[0], "name": nm or a[0], "text": desc or boost_text(b),
                            "raw": b, "source": field, "reaction": True})
        else:
            effects.append({"kind": "boost", "id": fn, "name": fn, "text": boost_text(b), "raw": b, "source": field})
    return effects


def spell_effect(ctx, sid, raw=None, field=None):
    e = ctx.st.get(sid)
    nm, desc = entry_text(ctx, e)
    extra = []
    if e:
        if e.get("TooltipDamageList"):
            extra.append("; ".join(fmt_param(x) for x in split_top(e["TooltipDamageList"])))
        lvl = e.get("Level")
        if lvl and lvl != "0":
            extra.append(f"level {lvl}")
        if e.get("Cooldown"):
            extra.append(e["Cooldown"])
        cost = e.get("UseCosts")
        if cost:
            extra.append(cost)
    text = (desc or "") + (f" [{', '.join(x for x in extra if x)}]" if extra else "")
    return {"kind": "spell", "id": sid, "name": nm or sid, "text": text.strip() or None, "raw": raw or sid,
            "source": field}


def passive_effect(ctx, pid, field=None):
    e = ctx.st.get(pid)
    nm, desc = entry_text(ctx, e)
    raw_bits = [pid]
    if e:
        for k in ("Boosts", "StatsFunctors", "Properties"):
            if e.get(k):
                raw_bits.append(f"{k}: {e[k]}")
    text = desc
    if not text and e and e.get("Boosts"):
        text = "; ".join(boost_text(b) for b in split_top(e["Boosts"]))
    hidden = bool(e and ("IsHidden" in (e.get("Properties") or "") or not nm))
    out = {"kind": "passive", "id": pid, "name": nm or pid, "text": text, "raw": " | ".join(raw_bits),
           "source": field}
    if hidden:
        out["hidden"] = True
    if e is None:
        out["unresolved"] = True
    # passives that unlock spells through their boosts
    if e and e.get("Boosts"):
        sp = [call_parts(re.sub(r"^IF\(.*?\):", "", b))[1][0] for b in split_top(e["Boosts"])
              if call_parts(re.sub(r"^IF\(.*?\):", "", b))[0] == "UnlockSpell"]
        if sp:
            out["spells"] = sp
    return out


def status_effect(ctx, sid, field=None, depth=0):
    e = ctx.st.get(sid)
    nm, desc = entry_text(ctx, e)
    parts = []
    raw_bits = [sid]
    sub = []
    if e:
        if e.get("Boosts"):
            parts.append("; ".join(boost_text(b) for b in split_top(e["Boosts"])))
            raw_bits.append(f"Boosts: {e['Boosts']}")
        if e.get("Passives") and depth < 2:
            for pid in split_top(e["Passives"]):
                pe = passive_effect(ctx, pid, field)
                sub.append(pe)
            raw_bits.append(f"Passives: {e['Passives']}")
        for k in ("OnApplyFunctors", "TickFunctors"):
            if e.get(k):
                raw_bits.append(f"{k}: {e[k]}")
    text = desc or ""
    if parts and not desc:
        text = parts[0]
    if not text and sub:
        text = "; ".join(p["text"] for p in sub if p.get("text"))
    if not text and e:
        fx = [f"{k}: {e[k]}" for k in ("OnApplyFunctors", "TickFunctors") if e.get(k)]
        text = " | ".join(fx) or None
    if not nm and sub and sub[0].get("name") and sub[0]["name"] != sub[0]["id"]:
        nm_show = sub[0]["name"]
    else:
        nm_show = nm or sid
    out = {"kind": "status", "id": sid, "name": nm_show, "text": text or None, "raw": " | ".join(raw_bits),
           "source": field}
    if not nm:
        out["hidden"] = True
    if e:
        out["status_type"] = e.get("StatusType")
        if e.get("Boosts"):
            out["boosts"] = parts[0]
    else:
        out["unresolved"] = True
    if sub:
        out["passives"] = [{"id": p["id"], "name": p["name"], "text": p["text"]} for p in sub]
    return out


def item_effects(ctx, f):
    effects = []
    for fld in ("Boosts", "DefaultBoosts", "BoostsOnEquipMainHand", "BoostsOnEquipOffHand"):
        val = f.get(fld)
        if fld == "DefaultBoosts" and val:
            # the item-as-object defaults (it cannot be crit / crit-fail when attacked) are not wearer effects
            val = ";".join(b for b in split_top(val) if not OBJECT_DEFAULT_BOOST.match(b))
        if val:
            effects += boost_effects(ctx, val, fld)
    for fld in ("PassivesOnEquip", "PassivesMainHand", "PassivesOffHand"):
        for pid in split_top(f.get(fld) or ""):
            effects.append(passive_effect(ctx, pid, fld))
    for sid in split_top(f.get("StatusOnEquip") or ""):
        effects.append(status_effect(ctx, sid, "StatusOnEquip"))
    return effects


def granted_spells(effects):
    out = []
    for e in effects:
        if e["kind"] == "spell" and not e.get("reaction"):
            out.append(e["id"])
        out += e.get("spells", [])
    return list(dict.fromkeys(out))


def requirements(f):
    req = {a[:3].lower(): 0 for a in ABILITIES}
    for m in re.finditer(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+(\d+)",
                         f.get("Requirements") or ""):
        req[m.group(1)[:3].lower()] = int(m.group(2))
    prof = [x for x in split_top(f.get("Proficiency Group") or "") if x and x != "None"]
    req["proficiency"] = prof
    return req


# ---------------------------------------------------------------- main build
def build(ctx, verbose=True):
    st = ctx.st
    tm = load_templates()
    acts = load_template_actions()
    honour = load_honour_stats()
    gold = load_gold_values()
    tagnames = load_tags()
    levels = load_json("level_items_index.json")

    # stats id -> templates (own / inherited Stats), plus level overrides and the RootTemplate field
    by_stats = defaultdict(list)
    for mk, t in tm.items():
        s = tget(t, "Stats")
        if s:
            by_stats[s].append(mk)
    placed_override = defaultdict(set)
    placed_templates = Counter()
    for pl in levels:
        placed_templates[pl.get("TemplateName")] += 1
        if pl.get("Stats"):
            placed_override[pl["Stats"]].add(pl.get("TemplateName"))

    def templates_for(sid, f):
        ts = list(by_stats.get(sid, []))
        for t in placed_override.get(sid, ()):
            if t not in ts:
                ts.append(t)
        rt = f.get("RootTemplate")
        if rt and rt != NULL_GUID and rt in tm and rt not in ts:
            ts.append(rt)
        return ts

    def pick_template(sid, f, ts):
        rt = f.get("RootTemplate")
        named = [t for t in ts if t in tm and loca_text(ctx, tget(tm[t], "DisplayName"))]
        if rt in named:
            return rt
        if named:  # most placed, then most common name
            return max(named, key=lambda t: placed_templates[t])
        return ts[0] if ts else None

    def value_of(f):
        vo = f.get("ValueOverride")
        if vo and vo.strip() not in ("", "0"):
            try:
                return int(float(vo))
            except ValueError:
                pass
        try:
            base = gold_value(gold, f.get("ValueUUID"), int(f.get("ValueLevel") or 1))
        except ValueError:
            base = None
        if base is None:
            return None
        v = base * float(f.get("ValueScale") or 1)
        # ValueRounding 1: the game shows prices rounded to the nearest 5 gold (checked on bg3.wiki:
        # 42->40, 63->65, 192->190, 32->30); tiny values stay as they are
        if (f.get("ValueRounding") or "0") != "0" and v >= 10:
            return int(5 * round(v / 5))
        return int(round(v))

    records = []

    def common(sid, f, ts, stats_type, slot):
        main = pick_template(sid, f, ts)
        t = tm.get(main, {})
        name = loca_text(ctx, tget(t, "DisplayName")) if t else None
        desc = loca_text(ctx, tget(t, "Description")) if t else None
        if not name:
            name, desc2 = entry_text(ctx, f)
            desc = desc or desc2
        names = sorted({loca_text(ctx, tget(tm[x], "DisplayName")) for x in ts if x in tm} - {None, name})
        tags = []
        for x in ts:
            for g in (tm.get(x, {}).get("Tags") or []):
                tags.append(tagnames.get(g, g))
        notes = []
        if names:
            notes.append("other template names: " + "; ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
        rec = {
            "stats_id": sid, "group": GROUP, "stats_type": stats_type,
            "name": clean_markup(name), "description": clean_markup(desc),
            "templates": ts, "icon": tget(t, "Icon") if t else None,
            "rarity": f.get("Rarity") or "Common", "unique": f.get("Unique") == "1",
            "slot": slot,
            "weight": float(f["Weight"]) if f.get("Weight") not in (None, "") else None,
            "value": value_of(f),
            "weapon": None, "armour": None,
            "boosts_raw": {k: f.get(k, "") for k in BOOST_FIELDS},
            "effects": [], "grants_spells": [], "requirements": requirements(f),
            "tags": sorted(set(tags)),
            "honour_override": sid in honour,
            "notes": "",
        }
        tech = loca_text(ctx, tget(t, "TechnicalDescription")) if t else None
        if tech:
            rec["technical_description"] = clean_markup(tech)
        return rec, notes

    # ---- equippable accessories
    n_acc = 0
    for sid, f in st.items():
        if f.get("_type") != "Armor" or sid.startswith("_"):
            continue
        slot = f.get("Slot")
        if slot not in ACCESSORY_SLOTS:
            continue
        ts = templates_for(sid, f)
        if not ts:
            continue
        rec, notes = common(sid, f, ts, "Armor", slot)
        rec["effects"] = item_effects(ctx, f)
        rec["grants_spells"] = granted_spells(rec["effects"])
        if f.get("InstrumentType"):
            notes.append(f"instrument: {f['InstrumentType']}")
        if f.get("MaxCharges"):
            notes.append(f"charges: {f.get('MaxCharges')}")
        if sid in honour:
            diff = {k: v for k, v in honour[sid]["data"].items() if f.get(k) != v}
            if diff:
                notes.append("Honour mode overrides: " + "; ".join(f"{k}={v}" for k, v in diff.items()))
        hp = [e["id"] for e in rec["effects"] if e["kind"] == "passive" and e["id"] in honour]
        if hp:
            notes.append("Honour mode changes passive(s): " + ", ".join(hp))
        if any(e.get("unresolved") for e in rec["effects"]):
            notes.append("some effects unresolved")
        rec["notes"] = "; ".join(notes)
        records.append(rec)
        n_acc += 1

    # ---- consumables
    groups = defaultdict(lambda: defaultdict(list))  # stats -> status tuple -> [template]
    for mk, t in tm.items():
        sid = tget(t, "Stats")
        f = st.get(sid)
        if not f or f.get("_type") != "Object":
            continue
        use = inherited_action(acts, mk, "use") or []
        statuses = tuple(a.get("StatsId") for ty, a in use if ty == 7 and a.get("StatsId"))
        special = sid in EXTRA_STATS and any(ty in (7, 12, 19, 31, 33) for ty, _ in use)
        if not statuses and not special:
            continue
        if statuses and all(s.startswith(SKIP_STATUS_PREFIX) for s in statuses):
            continue
        potion = f.get("ItemUseType") == "Potion"
        extra = any(s.startswith(EXTRA_STATUS_PREFIX) for s in statuses) or special
        if not (potion or extra):
            continue
        groups[sid][statuses].append(mk)

    n_cons = 0
    for sid, by_status in groups.items():
        f = st[sid]
        multi = len(by_status) > 1
        for statuses, ts in by_status.items():
            key = f"{sid}@{'+'.join(statuses)}" if multi and statuses else sid
            rec, notes = common(sid, f, ts, "Object", "Consumable")
            rec["stats_id"] = key
            if multi:
                notes.append(f"stats id {sid} is shared by different consumables; key suffixed with the consumed status")
            effects = []
            use_info = []
            for mk in ts[:1]:
                for ty, a in inherited_action(acts, mk, "use") or []:
                    if ty == 7:
                        e = status_effect(ctx, a["StatsId"], "OnUse:Consume")
                        dur = a.get("StatusDuration")
                        e["duration"] = dur
                        effects.append(e)
                        use_info.append({"action": "Consume", "status": a["StatsId"], "duration": dur,
                                         "consumed": a.get("Consume")})
                    elif ty in (12, 33):
                        spid = a.get("SpellId") or a.get("SkillID")
                        e = spell_effect(ctx, spid, field="OnUse:CastSpell")
                        effects.append(e)
                        use_info.append({"action": "UseSpell", "spell": spid, "consumed": a.get("Consume")})
                    elif ty == 19:
                        use_info.append({"action": "LearnOrScript (ActionType 19)"})
                    elif ty == 31:
                        use_info.append({"action": "Tadpole (ActionType 31)"})
                proj = (inherited_action(acts, mk, "script") or {}).get("ProjectileSpell")
                if proj:
                    use_info.append({"action": "Throw", "spell": proj})
            # (the Object's own Boosts/DefaultBoosts describe the item as a world object, not its user)
            if sid in SCRIPTED:
                for kind, eid in SCRIPTED[sid][0]:
                    e = (status_effect if kind == "status" else passive_effect)(ctx, eid, "Scripted")
                    effects.append(e)
                notes.append(SCRIPTED[sid][1])
            rec["effects"] = effects
            rec["grants_spells"] = granted_spells(effects)
            rec["consumable"] = {"use": use_info, "item_use_type": f.get("ItemUseType"),
                                 "object_category": f.get("ObjectCategory"), "use_costs": f.get("UseCosts")}
            perm = [e for e in effects if e["kind"] == "status" and (e.get("id", "").startswith(EXTRA_STATUS_PREFIX)
                                                                        or "permanent" in (e.get("text") or ""))]
            if perm and "permanent" not in " ".join(notes):
                notes.append("permanent boost")
            if any(e.get("unresolved") for e in effects):
                notes.append("some effects unresolved")
            if sid in EXTRA_STATS:
                notes.append("effect is applied by story scripts (Osiris), not by stats")
            rec["notes"] = "; ".join(notes)
            records.append(rec)
            n_cons += 1

    records.sort(key=lambda r: ({"Amulet": 0, "Ring": 1, "MusicalInstrument": 2, "Consumable": 3}[r["slot"]],
                                r["name"] or "", r["stats_id"]))
    if verbose:
        print(f"accessories: {n_acc}  consumables: {n_cons}  total: {len(records)}")
        print(Counter(r["slot"] for r in records))
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--check", nargs="*", default=[], help="print records whose name contains these strings")
    args = ap.parse_args()
    ctx = Ctx()
    recs = build(ctx)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(recs)} records -> {args.out}")
    for q in args.check:
        for r in recs:
            if r["name"] and q.lower() in r["name"].lower():
                print(json.dumps({k: r[k] for k in ("stats_id", "name", "slot", "rarity", "value", "effects")},
                                 ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
