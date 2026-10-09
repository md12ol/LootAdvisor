"""Player-facing text for the sets page (UX audit F5/F17): every string that reaches the page goes through here.

The scoring data is written for the pipeline (file refs, quest/step ids, raw boost functions, story codes). These
helpers turn it into plain game language without changing the data files. Rules are general text rules (patterns),
not per-item fixes.
"""
import re

ROMAN = {"1": "I", "2": "II", "3": "III"}

# ------------------------------------------------------------------------------------------------ small helpers
SKILLS = ["SleightOfHand", "AnimalHandling", "Acrobatics", "Athletics", "Arcana", "Deception", "History", "Insight",
          "Intimidation", "Investigation", "Medicine", "Nature", "Perception", "Performance", "Persuasion", "Religion",
          "Stealth", "Survival"]
ABILITIES = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]


def split_camel(w):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", w)


def human_token(w):
    """SleightOfHand -> Sleight of Hand; SG_Frightened -> Frightened; MAG_FOO_BAR -> Foo Bar."""
    w = str(w).strip().strip("'\"")
    w = re.sub(r"^(SG|MAG|DamageType|Size|ObscuredState|SpellType|ConditionRollType)[._]", "", w)
    if re.fullmatch(r"[A-Z0-9_]+", w):
        w = w.replace("_", " ").title()
    else:
        w = split_camel(w.replace("_", " "))
    w = w.replace("Sleight Of Hand", "Sleight of Hand").replace("Armor", "Armour")
    return w.strip()


def cap(s):
    s = s.strip()
    return s[:1].upper() + s[1:] if s else s


def acts(s):
    """'Act 1' -> 'Act I' (one numbering everywhere, F17)."""
    s = re.sub(r"\bAct\s*([123])\s*(?:->|-|to)\s*([123])\b", lambda m: "Act %s-%s" % (ROMAN[m.group(1)], ROMAN[m.group(2)]), s)
    return re.sub(r"\b[Aa]ct\s*([123])\b", lambda m: "Act " + ROMAN[m.group(1)], s)


COORD_RE = re.compile(r"\(?\b([XxYyZz])\s*:?\s*(-?\d+(?:\.\d+)?)\s*[,;]?\s*([XxYyZz])\s*:?\s*(-?\d+(?:\.\d+)?)\)?")


def coords(s):
    """All coordinate spellings -> '(X 29, Y 405)'. Game x/z positions are the map's X/Y."""
    def rep(m):
        a, b = m.group(1).upper(), m.group(3).upper()
        if a != "X" or b not in ("Y", "Z"):
            return m.group(0)
        return "(X %d, Y %d)" % (round(float(m.group(2))), round(float(m.group(4))))
    s = COORD_RE.sub(rep, s)
    s = re.sub(r"\(\s*\((X -?\d+, Y -?\d+)\)\s*\)", r"(\1)", s)
    s = re.sub(r"\(([^()]*?)\s*\((X -?\d+, Y -?\d+)\)\)", r"(\1 \2)", s)   # (Area (X 1, Y 2)) -> (Area X 1, Y 2)
    return s


def tidy(s):
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s+([.,;:)])", r"\1", s)
    s = re.sub(r"(?<=[.!?])\s*\)\.?", "", s)          # "questline.)." -> "questline."
    s = re.sub(r"[;,]\s*\.", ".", s)
    s = re.sub(r"\.\s*\.", ".", s)
    s = re.sub(r";\s*$", ".", s)
    s = re.sub(r"^[\s,;:.)-]+", "", s)
    s = re.sub(r"\(([^()]*)$", r"\1", s)               # unbalanced "(" at the end
    if s.count(")") > s.count("("):
        s = re.sub(r"\)(?=[^)]*$)", "", s, count=1)
    return cap(s.strip())


# ------------------------------------------------------------------------------------------------ scrubbing
SCRUB = [
    (r"\s*\((?:see\s+)?[\w./-]+\.md(?::[\d,-]+)?[^)]*\)", ""),          # (see crafted.md:22) / (crafted.md §18)
    (r"\s*(?:-|;|,)?\s*see\s+[\w./-]+\.md(?::[\d,-]+)?(?:\s*§\s*\d+)?", ""),
    (r"\b[\w./-]+\.md(?::[\d,-]+)?(?:\s*§\s*\d+)?:?\s*", ""),
    (r"\s*§\s*\d+", ""),
    (r"\s*\((?:[A-Z]{2,}_[A-Za-z0-9_]+)\)", ""),                     # (PLA_ZhentShipment)
    (r",?\s*\bstep\s+[A-Z][A-Za-z0-9_]+", ""),                         # step Rewarded_ZhentReturned
    (r";?\s*\bkey id\s+\S+", ""),
    (r"\s*The user's [^.]*\.", ""),
    (r"\s*Same (?:missable )?condition as above\.?", ""),
    (r"\s*\(verify in-game\)", ""),
    (r"(:\s*)\?\s+", r"\1"),                                          # "Missable: ? Moonrise vendor" (unsure mark)
    (r"\s*\((?:[^()]*\b(?:Gamestegy|Fextralife|reddit|research)\b[^()]*)\)", ""),
    (r"\bbg3\.wiki bug note:", "Bug note:"),
    (r"\bLLI\b", "Last Light Inn"),
    (r"\bLaezel\b", "Lae'zel"),
    (r"\bnpc\b", "NPC"),
    (r"\bTHEFT\b", "Theft"), (r"\bSTORY CHOICE\b", "Story choice"), (r"\bKILLS A NEUTRAL CREATURE\b", "Kills a neutral creature"),
    (r"\bHeavyArmor\b", "Heavy Armour"), (r"\bMediumArmor\b", "Medium Armour"), (r"\bLightArmor\b", "Light Armour"),
    (r"\bMartialWeapons\b", "martial weapons"), (r"\bSimpleWeapons\b", "simple weapons"),
]
KILL_RE = re.compile(r"Kill or pickpocket a neutral NPC:\s*(kill/loot|kill or pickpocket|kill)\s+(.+?)\s*"
                     r"\(neutral/friendly: crime or story cost\)\.?", re.I)
QUEST_RE = re.compile(r"Quest / story:\s*quest\s+'([^']+)'\s*(\([^)]*\))?\.?", re.I)
TIMING = {"goblin camp raid": "Get it before the goblin camp raid.",
          "gortash deal": "Mind the timing around Gortash's coronation.",
          "ferg selune shadowheart": "Mind the timing of Shadowheart's Selûne choice."}


def scrub(s):
    if not s:
        return ""
    s = str(s)
    for p, r in SCRUB:
        s = re.sub(p, r, s)
    s = KILL_RE.sub(lambda m: ("Loot %s (killing or robbing a neutral is a crime)." if m.group(1).lower() == "kill/loot"
                               else "Kill or pickpocket %s (a crime against a neutral)." if "pickpocket" in m.group(1).lower()
                               else "Kill %s (a neutral: a crime or a story cost).") % m.group(2), s)
    s = QUEST_RE.sub(lambda m: "Quest reward: %s." % m.group(1), s)
    s = re.sub(r"Quest / story:\s*a story event\.?", "Story reward.", s)
    s = re.sub(r"Timing:\s*([a-z ]+)\.", lambda m: TIMING.get(m.group(1).strip(), "Mind the timing (%s)." % m.group(1).strip()), s)
    s = re.sub(r"\bcheesy\b\)?", "", s)
    return tidy(coords(acts(s)))


# ------------------------------------------------------------------------------------------------ story conditions
STORY = {
    "path:tieflings": "Only if you side with the tieflings (goblin leaders killed).",
    "path:goblins": "Only if you side with the goblins.",
    "!path:goblins": "Lost if you side with the goblins - get it first.",
    "path:shar": "Only if Shadowheart kills the Nightsong (Shar path).",
    "path:selune": "Only if Shadowheart spares the Nightsong (Selûne path).",
    "!path:shar": "Lost if Shadowheart kills the Nightsong (Shar path) - get it first.",
    "!path:selune": "Lost if Shadowheart spares the Nightsong - get it first.",
    "!path:isobel_kill": "Lost if Isobel is killed and Last Light falls - get it first.",
    "durge": "Dark Urge playthrough only.",
    "path:kagha_kill": "Only if Kagha is killed or knocked out.",
    "path:tribunal": "Only by killing Investigator Valeria (Murder Tribunal).",
    "path:ethel_spared": "Only if Auntie Ethel is spared.",
    "!path:durge_alfira": "Lost if Alfira is the Dark Urge's camp victim - get it first.",
    "path:prisoners_rescued": "Only if the Moonrise prisoners are rescued.",
    "path:mizora_freed": "Only if Mizora is freed.",
    "path:anders_or_karlach_kill": "Only by killing Anders' group (or Karlach).",
    "path:absolute_brand": "Only if you accept the Absolute's brand.",
}
# sentences the scorer already wrote into the warning for a code (dropped there: the code is shown once, F3/F5)
STORY_DUP = {
    "path": r"Needs story path:[^.]*?(?:\([^)]*\))?[^.]*\.",
    "!path": r"Lost if [^.]*?(?:\([^)]*\))?[^.]*?- get it first\.",
    "durge": r"(?:Missable:\s*)?[Ii]t only exists in a Dark Urge campaign\.?",
    "origin": r"Companion quest reward:[^.]*\.",
}


def char_name(cid):
    return {"laezel": "Lae'zel", "darkurge": "The Dark Urge"}.get(cid, cid.replace("_", " ").title())


def cond_sentence(code):
    if code in STORY:
        return STORY[code]
    neg = code.startswith("!")
    kind, _, arg = code.lstrip("!").partition(":")
    arg_h = arg.replace("_", " ")
    if kind == "party":
        return "%s must be in your party." % char_name(arg)
    if kind == "origin":
        return "Companion quest reward (%s)." % char_name(arg)
    if kind == "path":
        return ("Lost on the story path: %s - get it first." if neg else "Story: only on the path: %s.") % arg_h
    if kind == "timing":
        return TIMING.get(arg_h, "Mind the timing (%s)." % arg_h)
    if kind == "note":
        return cap(arg_h) + "."
    return cap(code.replace("_", " ")) + "."


def drop_dups(warn, codes):
    """Remove sentences of a warning that repeat a story code shown on its own line."""
    w = warn or ""
    kinds = set()
    for c in codes:
        k = c.split(":")[0]
        kinds.add(k)
    for k in kinds:
        if k in STORY_DUP:
            w = re.sub(STORY_DUP[k], "", w)
    return w


# ------------------------------------------------------------------------------------------------ item "why"
FITS = {"melee2h": "two-handed melee", "melee1h": "one-handed melee", "reach": "reach weapons", "thrown": "throwing",
        "finesse": "finesse weapons", "light": "light weapons", "handxbow": "hand crossbows", "ranged": "ranged attacks",
        "shield": "a shield", "dual": "dual wielding"}


def why_text(s):
    """'+2 weapon; fits melee2h - community best pick, in 3 research sets, called BiS / consensus Patch 8 bug: x'
    -> '+2 weapon, suits two-handed melee. Community favourite (3 community builds, often called best in slot).
    Patch 8 bug: x'"""
    if not s:
        return ""
    s = str(s)
    bug = ""
    m = re.search(r"\s*Patch 8 bug:\s*(.*)$", s)
    if m:
        bug, s = m.group(1), s[:m.start()]
    left, _, right = s.partition(" - ")
    if not right and re.match(r"^(community|in \d+ research|called BiS)", left):
        left, right = "", left
    left = re.sub(r"\bfits ([\w/]+)", lambda m: "suits " + " / ".join(FITS.get(x, x) for x in m.group(1).split("/")), left)
    left = left.replace("; ", ", ")
    parts = [p.strip() for p in right.split(",") if p.strip()]
    head, extra = "", []
    for p in parts:
        if p == "community best pick":
            head = "Community favourite"
        elif p == "community runner-up":
            head = "Community second choice"
        elif re.match(r"in (\d+) research sets?", p):
            n = re.match(r"in (\d+)", p).group(1)
            extra.append("used in %s community build%s" % (n, "" if n == "1" else "s"))
        elif p == "called BiS / consensus":
            extra.append("often called best in slot")
        else:
            extra.append(p)
    comm = (head or ("Used by the community" if extra else ""))
    if extra:
        comm = (comm + " (" + ", ".join(extra) + ")") if head else cap(", ".join(extra))
    out = [scrub(left)] if left.strip() else []
    if comm:
        out.append(comm + ".")
    if bug:
        b = scrub(bug)
        if b and b not in ("Bugged", "Bugged."):
            out.append("Patch 8 bug: " + b)
    txt = " ".join(x if x.endswith((".", "!", "?")) else x + "." for x in out if x)
    return tidy(txt)


SETWHY_RE = re.compile(r"^(\d+) pieces feed ([^:]+):\s*(.*?)\.\s*The other slots hold (.*)$", re.S)


def set_why(s):
    """'5 pieces feed damage riders: A (x); B (y). The other slots hold ...' -> sentences (F17)."""
    if not s:
        return ""
    m = SETWHY_RE.match(s.strip())
    if m:
        parts = [p.strip() for p in m.group(3).split(";") if p.strip()]
        s = "%s pieces work together on %s: %s. The other slots hold %s" % (m.group(1), m.group(2), ", ".join(parts), m.group(4))
    return scrub(s)


SET_RESEARCH_RE = re.compile(r"\s*\(([^()]+?) research\)")


def set_name(n):
    n = re.sub(r"^Best scored loadout", "Best overall", n or "")
    return SET_RESEARCH_RE.sub(lambda m: " (adapted from %s's build)" % (m.group(1) if m.group(1) != "The Dark Urge"
                                                                         else "the Dark Urge"), n or "")


def validation(v):
    """'Adamantine Splint Armour: dropped (no proficiency: HeavyArmor)' -> 'Left out: ... (needs Heavy Armour proficiency).'"""
    v = scrub(v)
    m = re.match(r"^(.+?):\s*dropped\s*\((.*)\)\.?$", v)
    if m:
        why = re.sub(r"^no proficiency:\s*(.+)$", r"needs \1 proficiency", m.group(2))
        return "Left out: %s (%s)." % (m.group(1), why)
    m = re.match(r"^(.+?):\s*slot already filled \(alternative\)\.?$", v)
    if m:
        return "%s is an alternative for a slot that is already filled." % m.group(1)
    return v


# ------------------------------------------------------------------------------------------------ effect texts
BRACKET = {"OncePerRestPerItem": "once per rest", "OncePerRest": "once per rest", "OncePerShortRestPerItem": "once per short rest",
           "OncePerShortRest": "once per short rest", "OncePerTurn": "once per turn", "OncePerCombat": "once per combat",
           "OncePerLongRest": "once per long rest", "OncePerLongRestPerItem": "once per long rest"}


def _bracket(m):
    out = []
    for p in m.group(1).split(", "):
        p = p.strip()
        if p in BRACKET:
            out.append(BRACKET[p])
        elif re.fullmatch(r"ActionPoint:\d+", p):
            out.append("action")
        elif re.fullmatch(r"BonusActionPoint:\d+", p):
            out.append("bonus action")
        elif re.fullmatch(r"ReactionActionPoint:\d+", p):
            out.append("reaction")
        elif re.fullmatch(r"level 0", p):
            out.append("cantrip")
        elif re.fullmatch(r"level \d+", p):
            out.append(p + " spell")
        elif re.match(r"\w+:\d", p):
            continue
        else:
            out.append(effect_text(p))
    return "(" + ", ".join(x for x in out if x) + ")"


def effect_text(t):
    if not t:
        return ""
    t = str(t)
    t = re.sub(r"\[([^\]]*)\]", _bracket, t)
    # action resources written out by the game data ("+1 SpellSlot (level 1)") -> "+1 spell slot (level 1)"
    t = re.sub(r"\b(SpellSlot|WarlockSpellSlot|BonusActionPoint|ReactionActionPoint|ActionPoint|KiPoint|SorceryPoint|"
               r"SuperiorityDie|ChannelDivinity|ChannelOath|BardicInspiration|WildShape|LayOnHandsCharge|"
               r"ArcaneRecoveryPoint|NaturalRecoveryPoint)\b", lambda m: split_camel(m.group(1)).lower(), t)
    t = re.sub(r";?\s*applies [A-Z][A-Z0-9_]{4,}\b:?", "", t)
    t = re.sub(r"\(if (not )?HasPassive\('FightingStyle_(\w+)'[^)]*\)\)", lambda m: "(%s the %s fighting style)" % (
        "without" if m.group(1) else "with", split_camel(m.group(2)).replace("Defense", "Defence")), t)
    t = re.sub(r"\(if not HasPassive\('MediumArmorMaster'[^)]*\)\)", "(unless you have Medium Armour Master)", t)
    t = re.sub(r"\(if [^()]*(?:\([^()]*\)[^()]*)*\)", "(in some situations)", t)
    t = re.sub(r"Main(?:Melee|Ranged)?WeaponDamageType", "weapon damage type", t)
    t = re.sub(r"SpellCastingAbilityModifier", " spellcasting modifier", t)
    t = re.sub(r"max\(1,\s*(\w+) ?[Mm]odifier\)", lambda m: "%s modifier" % split_camel(m.group(1)), t)
    t = re.sub(r"\b(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)Modifier\b", r"\1 modifier", t)
    t = re.sub(r"\bProficiencyBonus\b", "proficiency bonus", t)
    t = re.sub(r"Advantage on SavingThrow (\w+)", r"Advantage on \1 saving throws", t)
    t = re.sub(r"to SavingThrow rolls", "to saving throws", t)
    t = re.sub(r"\b(" + "|".join(SKILLS) + r")\b", lambda m: human_token(m.group(1)), t)
    t = re.sub(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]{3,}\b", lambda m: human_token(m.group(0)), t)
    t = t.replace("target(s)", "targets").replace("turn(s)", "turns")
    return tidy(t)


def effect_name(n):
    n = re.sub(r"\s*\(hidden\)", "", n or "")
    if re.fullmatch(r"[A-Z0-9_]{6,}", n):
        return ""
    return n.strip()


# ------------------------------------------------------------------------------------------------ boosts (sheet "More effects")
ROLL_KIND = {"SavingThrow": "saving throws", "Attack": "attack rolls", "MeleeWeaponAttack": "melee weapon attacks",
             "RangedWeaponAttack": "ranged weapon attacks", "MeleeSpellAttack": "melee spell attacks",
             "RangedSpellAttack": "ranged spell attacks", "SpellAttack": "spell attacks", "WeaponAttack": "weapon attacks",
             "SkillCheck": "skill checks", "Skill": "skill checks", "Ability": "ability checks", "Damage": "damage",
             "DeathSavingThrow": "death saving throws", "MeleeUnarmedAttack": "unarmed attacks",
             "RangedUnarmedAttack": "ranged unarmed attacks", "MeleeOffHandWeaponAttack": "off-hand attacks",
             "RangedOffHandWeaponAttack": "off-hand ranged attacks", "Concentration": "Concentration saves",
             "AllSavingThrows": "all saving throws", "AttackRoll": "attack rolls", "AttackTarget": "attacks against you",
             "AllAbilities": "all ability checks", "AllSkills": "all skill checks"}


def _kind(args):
    k = args[0] if args else ""
    rest = [human_token(a) for a in args[1:] if a and not re.fullmatch(r"-?\d+|true|false", a, re.I)]
    if k in ("SavingThrow",) and rest:
        return "%s saving throws" % rest[0]
    if k in ("Ability",) and rest:
        return "%s checks" % rest[0]
    if k in ("Skill",) and rest:
        return "%s checks" % rest[0]
    return ROLL_KIND.get(k, human_token(k).lower())


def boost_text(name, args):
    a = [str(x).strip() for x in args]
    n0 = a[0] if a else ""
    if name == "StatusImmunity":
        if not n0:
            return "Status immunity"
        st = human_token(n0)
        for base in ("Difficult Terrain", "Prone", "Blinded", "Ensnaring Strike", "Ensnared"):
            if st.startswith(base + " ") and st != base:
                st = "%s (%s)" % (base, st[len(base) + 1:].lower())
                break
        return "Immune to " + st
    if name == "AC":
        return "%s%s AC" % ("" if n0.startswith("-") else "+", n0)
    if name == "ActionResource":
        res = {"Movement": "m movement", "ReactionActionPoint": "reaction", "BonusActionPoint": "bonus action",
               "ActionPoint": "action", "SpellSlot": "spell slot"}.get(n0, human_token(n0).lower())
        return "+%s %s" % (a[1] if len(a) > 1 else "1", res)
    if name in ("Advantage", "Disadvantage"):
        if n0 == "AttackTarget":
            return "Attacks against you have %s" % name.lower()
        k = n0
        rest = [human_token(x) for x in a[1:] if x]
        if k == "SavingThrow" and rest:
            what = "%s saving throws" % rest[0]
        elif k in ("Ability", "Skill") and rest:
            what = "%s checks" % rest[0]
        else:
            what = ROLL_KIND.get(k, human_token(k).lower())
        return "%s on %s" % (name, what)
    if name == "RollBonus":
        v = a[1] if len(a) > 1 else ""
        sign = "" if v.startswith(("-", "+")) else "+"
        k = [a[0]] + a[2:]
        return "%s%s to %s" % (sign, human_token(v) if not re.fullmatch(r"-?\d+(d\d+)?", v) else v, _kind(k))
    if name == "DamageReduction":
        t = human_token(n0) if n0 and n0 != "All" else "all sources"
        if len(a) > 2 and a[1] == "Flat":
            return "Take %s less damage from %s" % (a[2], t if n0 == "All" else t + " damage")
        if len(a) > 1 and a[1] == "Half":
            return "Take half damage from %s" % (t if n0 == "All" else t)
        return "Less damage from %s" % t
    if name in ("CharacterUnarmedDamage",):
        return "Unarmed attacks deal +%s%s" % (n0, " " + a[1] if len(a) > 1 else "")
    if name in ("CharacterWeaponDamage", "WeaponDamage"):
        return "+%s %sweapon damage" % (n0, (a[1] + " ") if len(a) > 1 else "")
    if name == "DamageBonus":
        t = a[1] if len(a) > 1 and a[1].lower() not in ("true", "false") else ""
        v = effect_text(n0)
        return "%s%s %sdamage" % ("" if v.startswith("-") else "+", v, (t + " ") if t else "")
    if name == "ReduceCriticalAttackThreshold":
        return "Critical hits on a roll %s lower" % n0
    if name == "Skill":
        return "%s%s %s" % ("" if (a[1:2] or ["+"])[0].startswith("-") else "+", a[1] if len(a) > 1 else "", human_token(n0))
    if name == "Attribute":
        return {"Grounded": "Can't be moved or knocked prone", "ForceMainhandOnlyIfOffhandEmpty": ""}.get(n0, human_token(n0))
    if name == "Proficiency":
        return "Proficiency: %s" % human_token(n0)
    if name == "EntityThrowDamage":
        return "+%s damage with thrown objects" % n0
    if name == "MaximizeHealing":
        return "Healing you %s is maximised" % ("receive" if "Target" in ",".join(a) else "give")
    if name == "DarkvisionRange" or name == "DarkvisionRangeMin":
        return "Darkvision %s m" % n0
    if name == "JumpMaxDistanceBonus":
        return "+%s m jump distance" % n0
    if name == "IgnoreFallDamage":
        return "No fall damage"
    if name == "IgnoreResistance":
        return "Ignores %s resistance" % human_token(n0)
    if name == "TwoWeaponFighting":
        return "Add your ability modifier to off-hand damage"
    if name == "WeaponDamageResistance":
        return "Resistant to %s weapon damage" % ", ".join(human_token(x).lower() for x in a if x)
    if name == "IgnoreSurfaceCover":
        return "Not hindered by %s" % human_token(n0).lower()
    if name == "ActionResourcePreventReduction":
        return "%s is not used up" % human_token(n0)
    if name == "UnlockSpellVariant":
        return "Changes how some spells work"
    if name == "Reroll":
        return "Reroll %ss on %s" % (a[1] if len(a) > 1 else "low roll", _kind(a[:1]))
    if name == "Tag":
        return ""
    if name == "Resistance":
        lvl = a[1] if len(a) > 1 else "Resistant"
        return ("Immune to %s damage" if lvl == "Immune" else "Resistant to %s damage") % human_token(n0)
    return ("%s %s" % (split_camel(name), ", ".join(human_token(x) for x in a))).strip()


COND_ATOMS = [
    (r"IsSpell\(\)", "with spells"), (r"IsCantrip\(\)", "with cantrips"),
    (r"IsRangedWeaponAttack\(\)", "with ranged weapon attacks"), (r"IsMeleeWeaponAttack\(\)", "with melee weapon attacks"),
    (r"IsMeleeAttack\(\)", "with melee attacks"), (r"IsWeaponAttack\(\)", "with weapon attacks"),
    (r"IsUnarmedAttack\(\)", "with unarmed attacks"), (r"IsReactionAttack\(\)", "with reaction attacks"),
    (r"IsCritical\(\)", "on critical hits"), (r"SpellAttackCheck\(\)", "with spell attacks"),
    (r"IsConcentrating\([^)]*\)", "while concentrating"),
    (r"not HasPassive\('MediumArmorMaster'[^)]*\)", "without Medium Armour Master"),
    (r"HasPassive\('FightingStyle_(\w+)'[^)]*\)", lambda m: "with the %s fighting style" % split_camel(m.group(1)).replace("Defense", "Defence")),
    (r"not HasObscuredState\(ObscuredState\.Clear\)", "while you are obscured"),
    (r"HasObscuredState\(ObscuredState\.Clear, context\.Target\)", "against targets in light"),
    (r"AttackingWithMeleeWeapon\([^)]*\)", "with a melee weapon"),
    (r"HasHPPercentage(?:EqualOr)?LessThan\((\d+), context\.Target\)", lambda m: "against targets at %s%% HP or less" % m.group(1)),
    (r"HasHPPercentageWithoutTemporaryHPLessThan\((\d+), context\.Source\)", lambda m: "while you are below %s%% HP" % m.group(1)),
    (r"HasEnemyWithinRange\([^)]*\)", "with enemies close by"),
    (r"SizeEqualOrGreater\(Size\.(\w+)\)", lambda m: "against %s or bigger creatures" % m.group(1)),
    (r"Tagged\('SHADOW', context\.Target\)", "against shadow creatures"),
    (r"HasMarkingStatusCondition\(\)", "against marked targets"),
    (r"HasDamageDoneForType\(DamageType\.(\w+)\)", lambda m: "when dealing %s damage" % m.group(1)),
    (r"SpellDamageTypeIs\(DamageType\.(\w+)\)", lambda m: "with %s spells" % m.group(1)),
    (r"Combat\(context\.Source\) and Combat\(\) and not HadTurnInCombat\(\)", "in your first turn of combat"),
    (r"not HasDisadvantage\(\)", "without disadvantage"), (r"not HasMaxHP\(\)", "while not at full HP"),
    (r"SpellTypeIs\(SpellType\.Throw\)", "with throws"),
    (r"HasStatus\('(\w*TECHNICAL\w*)'[^)]*\)", lambda m: ""),
    (r"HasStatus\('(\w+)'[^)]*\)", lambda m: "while %s" % human_token(m.group(1)).lower()),
    (r"toggled passive", "while switched on"),
]


def cond_human(c):
    """A game condition string -> short plain text; unknown parts -> 'in some situations'."""
    c = (c or "").strip()
    if not c:
        return ""
    out, rest = [], c
    for p, r in COND_ATOMS:
        def sub(m, r=r):
            out.append(r(m) if callable(r) else r)
            return " "
        rest = re.sub(p, sub, rest)
    rest = re.sub(r"\b(and|or|not|context\.\w+)\b|[()]", " ", rest).strip()
    if not out:
        return "in some situations"
    seen = []
    for x in out:
        if x and x not in seen:
            seen.append(x)
    txt = ", ".join(seen)
    return txt + (" (and more)" if re.search(r"\w", rest) else "")
