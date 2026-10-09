"""Game-data mechanics for the optimizer: a reader for the stats' condition language, every item's effects split
into what the character sheet already counts and what this model adds (conditional boosts, on-hit / on-cast
triggers, stacking statuses, item spells), and a spell reader.

Nothing here is item-specific: an item's effect comes from its Boosts / PassivesOnEquip / StatusOnEquip /
weapon TemplateStatus entries and the passives' StatsFunctorContext + Conditions + StatsFunctors in
data/cache/stats_resolved.json. Conditions are evaluated as probabilities for the attack / spell event they gate
(see PREDICATES); a predicate this model does not know counts 0.5 and is reported as a model gap.
"""
import math
import re

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sets_artifact"))
import build_sets_artifact as BSA  # noqa: E402  (pure helpers only: split_top, parse_boosts, safe_eval)

split_top = BSA.split_top
parse_boosts = BSA.parse_boosts

DICE = re.compile(r"(\d+)d(\d+)")
DMG_TYPES = ["Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison", "Psychic",
             "Radiant", "Slashing", "Thunder"]
ABIL = {"Strength": "STR", "Dexterity": "DEX", "Constitution": "CON", "Intelligence": "INT", "Wisdom": "WIS",
        "Charisma": "CHA"}


def avg_expr(expr, names=None):
    """'2d6+3' / '1d4' / 'StrengthModifier' / 'max(1,ProficiencyBonus)' / 'LevelMapValue(D10Cantrip)' -> average."""
    if expr is None:
        return 0.0
    e = str(expr).strip()
    names = names or {}
    e = re.sub(r"LevelMapValue\((\w+)\)", lambda m: str(names.get("LMV_" + m.group(1), "0")), e)
    tot = 0.0

    def dice(m):
        return "(%s)" % (int(m.group(1)) * (int(m.group(2)) + 1) / 2)
    e2 = DICE.sub(dice, e)
    v = BSA.safe_eval(e2.replace("/2", "*0.5") if "/" in e2 else e2, names)
    if v is None:
        try:
            v = float(eval(e2, {"__builtins__": {}}, {k: v_ for k, v_ in names.items()}))  # noqa: S307 - tiny arithmetic
        except Exception:  # noqa: BLE001
            v = 0.0
    tot += float(v)
    return tot


def dice_part(expr, names=None):
    """Average of only the dice of an expression (a crit doubles dice, not flat numbers)."""
    e = re.sub(r"LevelMapValue\((\w+)\)", lambda m: str((names or {}).get("LMVD_" + m.group(1), "0")), str(expr or ""))
    return sum(int(a) * (int(b) + 1) / 2 for a, b in DICE.findall(e))


def max_part(expr, names=None):
    e = re.sub(r"LevelMapValue\((\w+)\)", lambda m: str((names or {}).get("LMVX_" + m.group(1), "0")), str(expr or ""))
    return sum(int(a) * int(b) for a, b in DICE.findall(e))


# ===================================================================================== condition language
TOKEN = re.compile(r"\s*(?:(\()|(\))|(\bnot\b)|(\band\b)|(\bor\b)|([A-Za-z_][\w.]*)\s*(\()?|('[^']*'|\"[^\"]*\"|[^\s()]+))")


def parse_cond(s):
    """'not IsSpell() and (HasStatus('X') or Tagged('UNDEAD'))' -> nested tuples ('and', a, b) / ('not', a) /
    ('call', name, [args])."""
    s = (s or "").strip().rstrip(";")
    pos = 0
    toks = []
    while pos < len(s):
        m = TOKEN.match(s, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1):
            toks.append(("(",))
        elif m.group(2):
            toks.append((")",))
        elif m.group(3):
            toks.append(("not",))
        elif m.group(4):
            toks.append(("and",))
        elif m.group(5):
            toks.append(("or",))
        elif m.group(6) and m.group(7):
            # a call: read raw args up to the matching parenthesis
            depth, j = 1, pos
            while j < len(s) and depth:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                j += 1
            raw = s[pos:j - 1]
            pos = j
            toks.append(("call", m.group(6), [a.strip().strip("'\"") for a in split_top(raw, ",")]))
        elif m.group(6):
            toks.append(("name", m.group(6)))
        else:
            toks.append(("lit", m.group(8)))
    i = [0]

    def peek():
        return toks[i[0]] if i[0] < len(toks) else None

    def expr_or():
        a = expr_and()
        while peek() and peek()[0] == "or":
            i[0] += 1
            a = ("or", a, expr_and())
        return a

    def expr_and():
        a = expr_not()
        while peek() and peek()[0] == "and":
            i[0] += 1
            a = ("and", a, expr_not())
        return a

    def expr_not():
        if peek() and peek()[0] == "not":
            i[0] += 1
            return ("not", expr_not())
        return atom()

    def atom():
        t = peek()
        if t is None:
            return ("true",)
        i[0] += 1
        if t[0] == "(":
            a = expr_or()
            if peek() and peek()[0] == ")":
                i[0] += 1
            return a
        if t[0] == "call":
            return t
        return ("unknown", str(t))
    if not toks:
        return ("true",)
    return expr_or()


class Ctx:
    """What a condition is evaluated against: the event (an attack, a spell's damage on one target, a throw) and
    the character's state (build, loadout, statuses the loadout keeps up). Values are probabilities."""

    def __init__(self, state, ev=None, phase="boost"):
        self.st = state          # model.State
        self.ev = ev or {}
        self.phase = phase       # "boost" (an IF() on a boost) or "trigger" (a passive's Conditions / functor IF)
        self.unknown = state.unknown if state is not None else set()


def _dtype(arg):
    return arg.split(".")[-1] if arg else ""


def _ev(c, k, default=0.0):
    return 1.0 if c.ev.get(k) else default if k not in c.ev else 0.0


def _status_p(c, args):
    name = args[0] if args else ""
    who = args[1] if len(args) > 1 else ""
    st = c.st
    if name in ("SG_Rage", "RAGE", "RAGE_2", "RAGE_FRENZY", "RAGE_GIANT") or name.startswith("RAGE"):
        return st.raging
    if name in ("SG_Prone", "PRONE"):
        return st.target_prone if "Source" not in who else 0.0
    if name in ("SG_Incapacitated", "SG_Stunned", "SG_Paralyzed"):
        return 0.08
    if name in ("SG_Polymorph_BeastShape", "WILDSHAPE_TECHNICAL", "SG_Invisible", "INVISIBILITY"):
        return 0.0
    if name in ("SG_Blinded", "BLINDED"):
        return 0.05
    # a status this loadout keeps up on itself / the target
    if "Source" in who or c.phase == "boost":
        if name in st.self_uptime:
            return st.self_uptime[name]
    if name in st.target_uptime:
        return st.target_uptime[name]
    if name in st.self_uptime:
        return st.self_uptime[name]
    return 0.1


def _passive_p(c, args):
    p = args[0] if args else ""
    return 1.0 if c.st.has_passive(p) else 0.0


def _hp_le(c, args):
    try:
        pct = float(args[0])
    except (ValueError, IndexError):
        return 0.5
    who = args[1] if len(args) > 1 else "context.Target"
    if "Source" in who:
        return 0.25 if pct <= 50 else 0.5          # the character at half HP or less
    return 0.99 if pct >= 99 else max(0.05, min(0.95, pct / 100 * 0.8))


PREDICATES = {
    # attack kind (event)
    "IsMeleeAttack": lambda c, a: _ev(c, "melee"),
    "IsRangedAttack": lambda c, a: _ev(c, "ranged"),
    "IsWeaponAttack": lambda c, a: _ev(c, "weapon"),
    "IsMeleeWeaponAttack": lambda c, a: 1.0 if c.ev.get("weapon") and c.ev.get("melee") else 0.0,
    "IsRangedWeaponAttack": lambda c, a: 1.0 if c.ev.get("weapon") and c.ev.get("ranged") else 0.0,
    "AttackingWithMeleeWeapon": lambda c, a: 1.0 if c.ev.get("weapon") and c.ev.get("melee") else 0.0,
    "AttackingWithRangedWeapon": lambda c, a: 1.0 if c.ev.get("weapon") and c.ev.get("ranged") else 0.0,
    "IsUnarmedAttack": lambda c, a: _ev(c, "unarmed"),
    "IsMeleeUnarmedAttack": lambda c, a: 1.0 if c.ev.get("unarmed") and c.ev.get("melee") else 0.0,
    "IsRangedUnarmedAttack": lambda c, a: 1.0 if c.ev.get("unarmed") and c.ev.get("ranged") else 0.0,
    "IsSpell": lambda c, a: _ev(c, "spell"),
    "IsCantrip": lambda c, a: _ev(c, "cantrip"),
    "IsClericCantrip": lambda c, a: _ev(c, "cleric_cantrip"),
    "IsSpellAttack": lambda c, a: 1.0 if c.ev.get("spell") and c.ev.get("attack_roll") else 0.0,
    "SpellAttackCheck": lambda c, a: 1.0 if c.ev.get("spell") and c.ev.get("attack_roll") else 0.0,
    "IsSavingThrow": lambda c, a: 1.0 if c.ev.get("save") else 0.0,
    "IsAttack": lambda c, a: 1.0 if c.ev.get("attack_roll") else 0.0,
    "IsAttackType": lambda c, a: 1.0 if (a and a[0].split(".")[-1] == c.ev.get("attack_type")) else 0.0,
    "IsSpellSchool": lambda c, a: 1.0 if (a and a[0].split(".")[-1] == c.ev.get("school")) else 0.0,
    "IsSpellLevel": lambda c, a: 1.0 if (a and str(c.ev.get("spell_level")) == a[0]) else 0.0,
    "SpellId": lambda c, a: 1.0 if (a and a[0] == c.ev.get("spell_id")) else 0.0,
    "SpellTypeIs": lambda c, a: 1.0 if (a and a[0].split(".")[-1] == c.ev.get("spell_type")) else 0.0,
    "SpellCategoryIs": lambda c, a: 0.5 if c.ev.get("spell") else 0.0,
    "HasSpellFlag": lambda c, a: (1.0 if c.ev.get("spell") else 0.0) if a and "IsSpell" in a[0] else
    (0.6 if c.ev.get("spell") else 0.0),
    "SpellDamageTypeIs": lambda c, a: 1.0 if c.ev.get("spell") and _dtype(a[0] if a else "") in c.ev.get("dtypes", ()) else 0.0,
    "MainDamageTypeIs": lambda c, a: 1.0 if _dtype(a[0] if a else "") == c.ev.get("main_dtype") else 0.0,
    "HasDamageDoneForType": lambda c, a: 1.0 if _dtype(a[0] if a else "") in c.ev.get("dtypes", ()) else 0.0,
    "IsEnergyDamage": lambda c, a: 1.0 if set(c.ev.get("dtypes", ())) & {"Fire", "Cold", "Lightning", "Thunder",
                                                                          "Acid", "Poison"} else 0.0,
    "AttackedWithPassiveSourceWeapon": lambda c, a: 1.0 if c.ev.get("slot") and c.ev.get("slot") == c.ev.get(
        "_item_slot") else 0.0,
    "IsHit": lambda c, a: 1.0,
    "HasDamageEffectFlag": lambda c, a: 0.0 if a and "Miss" in a[0] else (c.ev.get("crit_given_hit", 0.05) if a and
                                                                          "Critical" in a[0] else c.ev.get("hit_flag", 1.0)),
    "IsRangedSpellAttack": lambda c, a: 1.0 if c.ev.get("attack_type") == "RangedSpellAttack" else 0.0,
    "IsMeleeSpellAttack": lambda c, a: 1.0 if c.ev.get("attack_type") == "MeleeSpellAttack" else 0.0,
    "IsDischargingLightning": lambda c, a: 0.2,
    "IsMainHandWeaponAttack": lambda c, a: 1.0 if c.ev.get("slot") in ("MainHand", "Ranged") else 0.0,
    "IsOffHandWeaponAttack": lambda c, a: 1.0 if c.ev.get("slot") in ("OffHand", "RangedOff") else 0.0,
    "FightingStyle_GreatWeapon": lambda c, a: 1.0 if c.ev.get("melee") and c.ev.get("weapon") and c.ev.get("heavy")
    else 0.0,
    "HasMaximumLightningCharge": lambda c, a: 0.3,
    "ArcaneAcuityGlovesCondition": lambda c, a: 1.0 if c.ev.get("spell") and c.ev.get("weapon_spell") else 0.0,
    "HasSavingThrowWithAbility": lambda c, a: 1.0 if c.ev.get("save_abil") and a and
    a[0].split(".")[-1] == c.ev.get("save_abil") else 0.0,
    "InSurface": lambda c, a: 0.05,
    "IsDowned": lambda c, a: 0.0,
    "IsMiss": lambda c, a: 0.0,
    "IsCritical": lambda c, a: c.ev.get("crit_given_hit", 0.05),
    "IsCriticalMiss": lambda c, a: 0.05,
    "IsKillingBlow": lambda c, a: 0.15,
    "HasAdvantage": lambda c, a: c.ev.get("adv", 0.0),
    "HasDisadvantage": lambda c, a: 0.05,
    "IsReactionAttack": lambda c, a: 0.0,
    "IsLastConditionRollSuccess": lambda c, a: 0.5,
    "SavingThrow": lambda c, a: c.ev.get("p_fail", 0.4),
    "HasUseCosts": lambda c, a: 0.8,
    # who / what the target is
    "Enemy": lambda c, a: 1.0,
    "Ally": lambda c, a: 0.0,
    "Character": lambda c, a: 1.0,
    "Item": lambda c, a: 0.0,
    "Player": lambda c, a: 1.0,
    "Summon": lambda c, a: 0.0,
    "Dead": lambda c, a: 0.0,
    "Combat": lambda c, a: 1.0,
    "HadTurnInCombat": lambda c, a: 1.0,
    "Tagged": lambda c, a: {"HUMANOID": 0.6, "UNDEAD": 0.15, "FIEND": 0.12, "CONSTRUCT": 0.05, "BEAST": 0.1,
                            "MONSTROSITY": 0.08, "ABERRATION": 0.08, "PLANT": 0.02, "DRAGON": 0.02, "GIANT": 0.03,
                            "ELEMENTAL": 0.03, "GOBLIN": 0.15 if c.st.act == 1 else 0.03}.get((a[0] if a else "").upper(),
                                                                                              0.1),
    "TargetSizeEqualOrSmaller": lambda c, a: 0.85,
    "SizeEqualOrGreater": lambda c, a: 0.3,
    "HasMetalArmor": lambda c, a: 0.35,
    "IsMetalCharacter": lambda c, a: 0.05,
    "HasMaxHP": lambda c, a: 0.3,
    "HasHPPercentageEqualOrLessThan": _hp_le,
    "HasHPPercentageLessThan": _hp_le,
    "HasHPPercentageWithoutTemporaryHPEqualOrLessThan": _hp_le,
    "HasHPPercentageWithoutTemporaryHPLessThan": _hp_le,
    "HasHPLessThan": lambda c, a: 0.15,
    "DistanceToTargetGreaterThan": lambda c, a: 0.0 if c.ev.get("melee") else 0.6,
    "HasEnemyWithinRange": lambda c, a: 1.0 if c.st.exposure >= 1.25 else 0.5,
    # the character's own state
    "Self": lambda c, a: 1.0 if c.phase == "boost" else (1.0 if any("Source" in x for x in a) and
                                                          any("Observer" in x for x in a) else 0.0),
    "HasStatus": _status_p,
    "HasPassive": _passive_p,
    "IsConcentrating": lambda c, a: c.st.concentrating,
    # HasObscuredState(ObscuredState.Clear) = standing in the open; Lightly / Heavily = in shadow / darkness
    "HasObscuredState": lambda c, a: (1.0 - c.st.obscured) if a and a[0].endswith("Clear") else c.st.obscured,
    "WearingArmor": lambda c, a: 1.0 if c.st.armour_cat else 0.0,
    "HasHeavyArmor": lambda c, a: 1.0 if c.st.armour_cat == "Heavy" else 0.0,
    "HasShieldEquipped": lambda c, a: 1.0 if c.st.shield else 0.0,
    "IsOffHandSlotEmpty": lambda c, a: 0.0 if c.st.offhand_used else 1.0,
    "Dueling": lambda c, a: 0.0 if c.st.offhand_used else 1.0,
    "IsCharismaModifierPositive": lambda c, a: 1.0 if c.st.mods.get("CHA", 0) > 0 else 0.0,
    "GreatWeaponMaster": lambda c, a: c.st.gwm_on(c.ev),
    "Sharpshooter": lambda c, a: c.st.ss_on(c.ev),
    "HasActionResource": lambda c, a: 0.5,
    "ClassLevelHigherOrEqualThan": lambda c, a: 1.0 if c.st.classes.get(a[1] if len(a) > 1 else "", 0) >= int(a[0] or 0)
    else 0.0,
    "IsProficientWith": lambda c, a: 1.0,
    "HasMarkingStatusCondition": lambda c, a: 0.3,
    "AnyEntityIsItem": lambda c, a: 0.0,
    "StatusDoesNotInvokeOnStatusApply": lambda c, a: 0.0,
}
# OnStatusApply-style contexts: the status being applied (decided by the trigger code)
DTYPE_PRED = re.compile(r"^IsDamageType(\w+)$")
STATUS_PREDICATES = {"StatusId", "StatusHasStatusGroup", "HasStatusWithGroup"}


def eval_cond(node, c):
    if node is None:
        return 1.0
    k = node[0]
    if k == "true":
        return 1.0
    if k == "not":
        return 1.0 - eval_cond(node[1], c)
    if k == "and":
        return eval_cond(node[1], c) * eval_cond(node[2], c)
    if k == "or":
        a, b = eval_cond(node[1], c), eval_cond(node[2], c)
        return 1.0 - (1.0 - a) * (1.0 - b)
    if k == "call":
        name, args = node[1], node[2]
        mt = DTYPE_PRED.match(name)
        if mt:
            return 1.0 if mt.group(1) in c.ev.get("dtypes", ()) else 0.0
        if name in STATUS_PREDICATES:
            return c.ev.get("status_match", lambda n, a: 0.3)(name, args)
        fn = PREDICATES.get(name)
        if fn is None:
            c.unknown.add(name)
            return 0.5
        try:
            return float(fn(c, args))
        except Exception:  # noqa: BLE001
            c.unknown.add(name)
            return 0.5
    c.unknown.add(str(node)[:40])
    return 0.5


_COND_CACHE = {}


def cond_p(text, c):
    if not text:
        return 1.0
    node = _COND_CACHE.get(text)
    if node is None:
        node = _COND_CACHE[text] = parse_cond(text)
    return eval_cond(node, c)


# ===================================================================================== item effects
SHEET_NAMES = {"Ability", "AbilityOverrideMinimum", "IncreaseMaxHP", "AC", "Initiative", "Resistance", "SpellSaveDC",
               "WeaponEnchantment", "WeaponProperty"}
SIMPLE_KIND = re.compile(r"\s*(not\s+)?Is(Ranged|Melee)(Weapon)?Attack\(\)\s*")


def sheet_counts(b):
    """Does BSA.compute_sheet already count this boost (so this model must not add it again)?
    b = an entry of BSA.collect_boosts."""
    n, cond = b["name"], b["cond"]
    if not cond:
        if n in SHEET_NAMES or n in ("DamageBonus", "CharacterWeaponDamage"):
            return True
        if n == "WeaponDamage" and b.get("scope"):
            return True
        if n == "RollBonus" and b["args"] and b["args"][0] in ("Attack", "WeaponAttack", "MeleeWeaponAttack",
                                                                "RangedWeaponAttack", "SpellAttack",
                                                                "MeleeSpellAttack", "RangedSpellAttack"):
            return True
        if n == "ActionResource" and b["args"] and b["args"][0] == "Movement":
            return True
        return False
    # conditional: the sheet adds simple melee / ranged riders to the matching weapon rows
    if n in ("DamageBonus", "WeaponDamage", "CharacterWeaponDamage", "RollBonus") and SIMPLE_KIND.fullmatch(cond):
        return True
    return False


class ItemMech:
    """Per item: triggers (passives that act on attack / damage / cast / status events) and item spells."""

    def __init__(self, W, sid):
        rec = W.items[sid]
        self.sid = sid
        self.name = rec.get("name")
        br = rec.get("boosts_raw") or {}
        self.triggers = []          # {"ctx", "cond", "functors", "once", "hand", "via"}
        self.spells = []            # (spell id, hand)
        self.self_status = []       # statuses kept up from equipping / drinking (with their own functors)
        stats = W.stats
        hands = (("a", "PassivesOnEquip"), ("m", "PassivesMainHand"), ("o", "PassivesOffHand"))
        for hand, field in hands:
            for p in split_top(br.get(field, "")):
                st = stats.get(p) or {}
                ctx = st.get("StatsFunctorContext") or ""
                if st.get("StatsFunctors") and ctx:
                    self.triggers.append({"ctx": ctx, "cond": (st.get("Conditions") or "").strip(),
                                          "functors": st["StatsFunctors"], "props": st.get("Properties") or "",
                                          "hand": hand, "via": p})
        for hand, field in (("a", "Boosts"), ("a", "DefaultBoosts"), ("m", "BoostsOnEquipMainHand"),
                            ("o", "BoostsOnEquipOffHand")):
            for cond, name, args in parse_boosts(br.get(field, "")):
                if name == "UnlockSpell" and args:
                    self.spells.append((args[0], hand))
        # passives' own UnlockSpell boosts (Markoheshkir's attunement spells come through passives / statuses)
        for hand, field in hands:
            for p in split_top(br.get(field, "")):
                st = stats.get(p) or {}
                for cond, name, args in parse_boosts(st.get("Boosts") or ""):
                    if name == "UnlockSpell" and args:
                        self.spells.append((args[0], hand))
        # choice spells (Markoheshkir's attunement): a container whose variants each put a lasting status on the
        # wearer; the model tries every variant and keeps the best (options = [(variant spell, status)])
        self.options = []
        for spid, hand in self.spells:
            sd = stats.get(spid) or {}
            for v in split_top(sd.get("ContainerSpells") or ""):
                vd = stats.get(v) or {}
                for cond, name, args in parse_boosts(vd.get("SpellProperties") or ""):
                    if name == "ApplyStatus" and len(args) >= 3 and args[-1].strip() == "-1" and args[0] != "SELF":
                        self.options.append((v, args[0]))
        if rec.get("slot") == "Consumable":
            for e in rec.get("effects") or []:
                if e.get("kind") == "status" and str(e.get("source", "")).startswith("OnUse"):
                    self.self_status.append(e.get("id"))
        for s in split_top(br.get("StatusOnEquip", "")):
            self.self_status.append(s)


def add_status(W, im, status, hand="a"):
    """Put a lasting self status's effects onto an ItemMech: its Boosts (-> boosts list returned), its Passives'
    triggers and UnlockSpell entries."""
    sd = W.stats.get(status) or {}
    boosts = []
    for cond, name, args in parse_boosts(sd.get("Boosts") or ""):
        if name == "UnlockSpell" and args:
            im.spells.append((args[0], hand))
        else:
            boosts.append((cond, name, args))
    for p in split_top(sd.get("Passives") or ""):
        st = W.stats.get(p) or {}
        if st.get("StatsFunctors") and st.get("StatsFunctorContext"):
            im.triggers.append({"ctx": st["StatsFunctorContext"], "cond": (st.get("Conditions") or "").strip(),
                                "functors": st["StatsFunctors"], "props": st.get("Properties") or "", "hand": hand,
                                "via": p})
        for cond, name, args in parse_boosts(st.get("Boosts") or ""):
            boosts.append((cond, name, args))
    return boosts


def functor_list(text):
    """'IF(c):DealDamage(1d4,Fire);ApplyStatus(SELF,X,100,2)' -> [(cond|None, name, [args])]."""
    return parse_boosts(text or "")


# ===================================================================================== spells
LMV = {  # LevelMapValues used by the spells this model casts (Levelmaps/LevelMapValues.lsx; cantrips scale at 5 / 10)
    "D10Cantrip": lambda lv: "%dd10" % (1 if lv < 5 else 2 if lv < 10 else 3),
    "D8Cantrip": lambda lv: "%dd8" % (1 if lv < 5 else 2 if lv < 10 else 3),
    "D12Cantrip": lambda lv: "%dd12" % (1 if lv < 5 else 2 if lv < 10 else 3),
    "D6Cantrip": lambda lv: "%dd6" % (1 if lv < 5 else 2 if lv < 10 else 3),
    "D4Cantrip": lambda lv: "%dd4" % (1 if lv < 5 else 2 if lv < 10 else 3),
    "EldritchBlast": lambda lv: str(1 if lv < 5 else 2 if lv < 10 else 3),
    "RageDamage": lambda lv: "2",   # replaced per Barbarian level in model.py
}


def lmv_names(level):
    out = {}
    for k, f in LMV.items():
        v = f(level)
        out["LMV_" + k] = avg_expr(v) if "d" in v else float(v)
        out["LMVD_" + k] = v if "d" in v else "0"
        out["LMVX_" + k] = v if "d" in v else "0"
    # dice_part / max_part take the dice text; avg_expr takes numbers
    return out


def area_targets(sp, enemies=4):
    """Enemies hit by one cast (assumption, same table as the companion analyses: 4 enemies per fight)."""
    r = 0.0
    for f in ("AreaRadius", "ExplodeRadius"):
        try:
            r = max(r, float(sp.get(f) or 0))
        except ValueError:
            pass
    if sp.get("_id", "").startswith("Zone_"):
        return 2.5                       # line / cone
    if r >= 6:
        return 3.0
    if r >= 4:
        return 3.0
    if r >= 3:
        return 2.5
    if r >= 2:
        return 1.5
    return 1.0


def read_spell(W, sid, level, slot_level=None):
    """-> {"id", "dmg": [(expr, type)], "roll": "attack"|"save"|"auto", "save_abil", "half", "targets", "beams",
    "school", "level", "conc", "cantrip"} or None (no damage). Reads TooltipDamageList / SpellSuccess, upcast
    variants (<id>_<slot>) and chained projectiles (SpawnExtraProjectiles)."""
    S = W.stats
    base = S.get(sid)
    if not isinstance(base, dict):
        return None
    sp = base
    if slot_level and isinstance(S.get(f"{sid}_{slot_level}"), dict):
        sp = S[f"{sid}_{slot_level}"]
    txt = sp.get("TooltipDamageList") or base.get("TooltipDamageList") or ""
    dmg = []
    if txt:
        for m in re.finditer(r"DealDamage\(([^,]+),\s*(\w+)", txt):
            expr, t = m.group(1).strip(), m.group(2)
            if t in DMG_TYPES and "Weapon" not in expr:
                dmg.append((expr, t))
    else:
        # no tooltip list: unconditional DealDamage entries add up; IF(...) branches are alternatives (take the best)
        succ = (sp.get("SpellSuccess") or "") + ";" + (sp.get("SpellProperties") or "")
        alts = []
        for cond, name, args in parse_boosts(succ.replace("TARGET:", "").replace("GROUND:", "")):
            if name == "DealDamage" and len(args) >= 2 and args[1] in DMG_TYPES and "Weapon" not in args[0]:
                (alts if cond else dmg).append((args[0], args[1]))
        if alts:
            dmg.append(max(alts, key=lambda x: avg_expr(x[0])))
    if not dmg:
        return None
    roll = sp.get("SpellRoll") or base.get("SpellRoll") or ""
    kind = "save" if "SavingThrow" in roll else "attack" if "Attack(" in roll else "save" if roll.strip() else "auto"
    ab = re.search(r"Ability\.(\w+)", roll)
    fail = sp.get("SpellFail") or base.get("SpellFail") or ""
    beams = 1.0
    ta = str(sp.get("AmountOfTargets") or base.get("AmountOfTargets") or "")
    if ta.startswith("LevelMapValue("):
        beams = float(LMV.get(ta[14:-1], lambda lv: "1")(level))
    elif ta.isdigit():
        beams = float(ta)
    tg = area_targets(dict(base, _id=sid))
    extra = re.search(r"SpawnExtraProjectiles\((\w+)\)", (sp.get("SpellSuccess") or "") + (base.get("SpellSuccess") or ""))
    chain = 0.0
    if extra and isinstance(S.get(extra.group(1)), dict):
        try:
            chain = min(3.0, float(S[extra.group(1)].get("ProjectileCount") or 0))
        except ValueError:
            chain = 0.0
    lvl = int(base.get("Level") or 0)
    flags = (base.get("SpellFlags") or "")
    return {"id": sid, "dmg": dmg, "roll": kind, "save_abil": ab.group(1) if ab else None,
            "half": "/2" in fail, "targets": tg, "chain": chain, "beams": beams,
            "school": base.get("SpellSchool") or "", "level": lvl, "slot": slot_level or lvl,
            "conc": "IsConcentration" in flags, "cantrip": lvl == 0, "is_spell": "IsSpell" in flags or lvl > 0,
            "uses": (base.get("UseCosts") or ""), "cooldown": base.get("Cooldown") or ""}


def p_hit(bonus, ac, adv=0.0, dis=0.0):
    need = max(2, min(20, ac - bonus))
    p = (21 - need) / 20
    pa = 1 - (1 - p) ** 2
    pd = p * p
    adv_eff = max(0.0, adv - dis)
    dis_eff = max(0.0, dis - adv)
    return adv_eff * pa + dis_eff * pd + (1 - adv_eff - dis_eff) * p


def p_crit(thr, adv=0.0):
    p = max(0.05, (21 - thr) / 20)
    return adv * (1 - (1 - p) ** 2) + (1 - adv) * p


def p_fail(dc, save_bonus, adv=0.0):
    p = min(0.95, max(0.05, (dc - save_bonus - 1) / 20))
    return p * (1 - adv) + adv * p * p


def stack_average(add_per_round, decay=1.0, cap=10.0, rounds=4, start=0.0, floor=0.0):
    """Average stacks of an Additive, MultiplyEffectsByDuration status over a fight: each round the loadout adds
    add_per_round turns (capped), the round's attacks see the mean of the stacks before and after the gain, then one
    turn runs out (decay). Used for Arcane Acuity, Radiating Orb, Reverberation, Lightning Charges."""
    s, tot = max(start, floor), 0.0
    for _r in range(rounds):
        after = min(cap, s + add_per_round)
        tot += max(floor, (s + after) / 2)
        s = max(floor, after - decay)
    return tot / rounds


def die_gain(sides, reroll=None, savage=False):
    """Average gain per weapon die from Great Weapon Fighting (reroll results <= reroll once, keep the new roll) /
    Savage Attacker (roll twice, keep the higher)."""
    base = (sides + 1) / 2
    g = 0.0
    if reroll:
        k = min(reroll, sides)
        g += (k / sides) * (base - (k + 1) / 2)
    if savage:
        e = sum(v * (2 * v - 1) for v in range(1, sides + 1)) / sides ** 2
        g = max(g, e - base) + (0.5 * g if reroll else 0)
    return g


def ceil_half(n):
    return int(math.ceil(n / 2))
