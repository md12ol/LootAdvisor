"""Score every equippable item for every origin character x build, pick best / runner-up per slot per act,
build synergy sets, and write data/scores/<char>.json, data/scores/SETS.md, data/scores/lua/LootData.lua.

Run:  python tools/match_research.py && python tools/score_items.py

SCORING FORMULA (per item, build, act) - simple general rules, no item-specific hacks
  total(act) = fit + consensus(act)          (only if the item is obtainable by that act and usable)

  usable   armour / shield / headwear / boots that need a proficiency the character lacks (race + start class
           + multiclass + subclass, see build_profiles.py) are excluded, unless the item makes its wearer
           proficient ("considered Proficient with this armour", e.g. Helldusk Armour, Elven Chain);
           weapons without proficiency are excluded; build "avoid" rules (Bladesong: no shield / medium /
           heavy, Monk: no shield) exclude too; heavy body armour is excluded for every build that rages (a class
           with the Rage feature: Barbarian levels), since heavy armour switches Rage off.
           Class / subclass proficiencies come from the game's Progressions.lsx (tools/class_progressions.py).

  fit = rarity + weapon/armour base + sum(effect rule value x build need weight)
    rarity       Common 0, Uncommon 1, Rare 2, Very rare 3, Legendary 4 (x 0.5)
    weapon base  attack-mode match (build.attacks weight of the best matching mode: ranged, handxbow,
                 melee2h, melee1h, finesse, light, thrown, unarmed, reach) + 0.25 x average damage dice
                 + 0.8 x enchantment (weapon builds only; casters value weapons by effects only);
                 throwers get +need(returning) for weapons that return when thrown
    armour base  body armour: (effective AC - 14) with the build's DEX (dex cap, full-DEX passives);
                 unarmoured builds compare with their Unarmoured Defence (CON/WIS) and a Monk loses
                 Martial Arts in armour (-6); shields: +1 per AC; stealth disadvantage costs need(stealth)
    effect rules every readable effect text of the item (boosts, passives, statuses, granted spells)
                 is matched against RULES below; each hit gives value x weight of the build's need
                 (build_profiles.needs, defaults in DEFAULT_NEEDS); conditional riders ("while", "when",
                 "against" ...) count 60% unless the condition is something the build does (concentrating,
                 hidden, obscured, illuminated, raging ...); race-locked effects (githyanki, drow, dwarf ...)
                 count only for that race; ability boosts are valued by the modifier gained over the build's
                 assumed level-12 score x build.statw

  consensus(act) = research mentions for this build (data/research/<char>.md, + same build in other
                 characters' files at 50%):  best 8, runner-up 5, set 3, item bullet 2, notes 1.5,
                 section-5 "BiS / consensus" 3, "niche / overrated" -2, BuildAdvisor gear line 3;
                 mentions tagged for all builds count 70%; act-specific mentions carry into later acts at 60%;
                 capped at 25.

  act = earliest act of a reliable game-data source (world / container / reward / trader with
        chance >= 25% / NPC loot; low-confidence and random treasure ignored); fallback: any gameplay
        source, then the act the research names. Sets and best lists are per act: an item counts in
        act N only when first act <= N <= the last act it can still be obtained in.

  effect-rule details: a status that repeats its passive counts once; riders that only fire on a
  crit / against some creatures / under a condition the build does not arrange are discounted; "while
  obscured / hidden / concentrating" style qualifiers add little and nothing when the build does not want
  the payload; weapon riders and weapon actions count only for a build that attacks with the weapon
  (proficient, fitting attack mode); ranged-only riders need a shooting build, unarmed triggers an unarmed
  build; Bonded weapons' bonuses need a Warlock pact weapon; GWM builds value the Heavy property; known
  Patch 8 bugs from the research (always-on, +1 to all attacks, doubled dice, 1/LR) are scored as the game
  behaves and named in the why text.

  sets   research seed sets (alternatives "A or B" only stand in for A), then generated: best-scored loadout
         and theme sets that reach 85% of its score; never a near-copy of another set. Every set is legal:
         two-handed / Duellist mains keep the off hand empty, dual wielding needs two Light weapons, the ranged
         off hand takes only a hand crossbow (and needs a hand crossbow main), "no armour / no shield" items never
         sit next to armour / a shield, and no two items whose story conditions exclude each other (conditions.md
         families).
         Items that cost an origin companion are left out. Conditioned items get a fallback; unique items and
         scarce materials get a party owner (owners.json) and a party alternative for the other characters.
"""
import collections
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_profiles as BP  # noqa: E402
from la_common import (DATA, PLAY_ACTS, RARITY_RANK, SCORES_DIR, NameIndex, build_display_names,  # noqa: E402
                       deaccent, load_builds_lua, load_items, load_levels, load_recipes, load_sources,
                       origin_of_source, short, source_act, split_rarity)
from la_research import ResearchParser, Scanner, segments  # noqa: E402
import tooltip_warn as TW  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sets_artifact"))
import playertext as PT  # noqa: E402  - player-facing wording (same filter as the Sets page)

try:
    import set_notes  # hand-written "why" texts for research seed sets
except ImportError:  # pragma: no cover
    set_notes = None

SLOT_ORDER = ["MainHand", "OffHand", "Ranged", "RangedOff", "Helmet", "Cloak", "Breast", "Gloves", "Boots",
              "Amulet", "Ring1", "Ring2", "Elixir"]
SLOT_LABEL = {"MainHand": "Main hand", "OffHand": "Off hand", "Ranged": "Ranged", "RangedOff": "Ranged off hand",
              "Helmet": "Head", "Cloak": "Cloak", "Breast": "Armour", "Gloves": "Gloves", "Boots": "Boots",
              "Amulet": "Amulet", "Ring1": "Ring 1", "Ring2": "Ring 2", "Elixir": "Elixir"}
ITEM_SLOT = {"Helmet": "Helmet", "Cloak": "Cloak", "Breast": "Breast", "Gloves": "Gloves", "Boots": "Boots",
             "Amulet": "Amulet", "Ring": "Ring"}

ROLE_W = {"best": 8, "runner": 5, "set": 3, "detail": 2, "note": 1.5, "ref": 0.5, "consensus": 3, "niche": -2,
          "note5": 1, "gear": 3}
CONS_CAP = 25
CARRY = 0.6
XFILE = 0.5

DEFAULT_NEEDS = {"ac": 1.0, "saves": 0.7, "crit_immune": 0.7, "dmg_reduction": 0.8, "temp_hp": 0.5,
                 "mobility": 0.6, "initiative": 0.5, "action": 1.0, "utility": 1.0, "stat": 1.0, "penalty": 1.0,
                 "retaliation": 0.5}

# ---------------------------------------------------------------- effect rules
DMG_TYPES = ["fire", "cold", "lightning", "thunder", "radiant", "necrotic", "psychic", "poison", "acid", "force",
             "piercing", "slashing", "bludgeoning"]
DICE = re.compile(r"(\d+)d(\d+)")
COND_WORDS = re.compile(r"\b(while|when|whenever|if|against|after|once per|as long as|targets that|creatures that|"
                        r"on a critical|at or below|with advantage)\b")
# conditions the build itself can arrange (only when the build needs that mechanic); "while attacking" in the
# crit-range texts is not a condition
COND_NEEDS = [("concentrat", "concentration"), ("hidden|hiding|invisib", "stealth"), ("obscured|shadow", "obscured"),
              ("illuminated|light", "illuminated"), ("rage|raging", "rage"), ("healed", "healed"),
              ("marked|hunter's mark", "hunters_mark"), ("with advantage", "adv"), ("surrounded", "weapon_atk"),
              ("50% hit points|half their hit points|50% of their", "weapon_dmg")]
COND_IGNORE = re.compile(r"while attacking|(?:as long as|while) (?:you are|they are|the wearer is|the wielder is) not "
                         r"wearing armour(?: or holding a shield)?")   # (armour conditions: see race_mult)
WIELD_NEEDS = {"weapon_dmg", "weapon_atk", "crit", "adv", "throw", "sneak_attack", "piercing_vuln", "smite", "daze",
               "reverberation", "radiating_orb", "kill_trigger"}
# outgoing damage wording (a damage type in a resistance / immunity / damage-taken text is not a damage bonus)
OUTGOING = re.compile(r"\b(?:deals?|dealing|dealt|additional|extra|inflicts?|takes? an additional|also deals?)\b")
NOT_OUTGOING = re.compile(r"\b(?:immune|immunity|resistan\w*|less \w+ damage|reduce\w* (?:all )?(?:incoming )?damage|"
                          r"damage (?:you|the wearer) take)")
# named mechanics that describe WHEN an effect works (a qualifier), not what it gives: when the same text has a
# payload (+spell DC, +attack ...), the qualifier adds little, and nothing when the build does not want the payload
QUALIFIER_NEEDS = {"obscured", "stealth", "illuminated", "concentration", "healed", "throw", "unarmed", "rage",
                   "kill_trigger", "hunters_mark", "lightning_charge"}
CREATURE_COND = re.compile(r"\b(undead|fiends?|beasts?|monstrosit\w*|goblins?|gnomes or dwarves|shapeshifters?|"
                           r"constructs?|plants|aberrations|dragons|elementals|insects|small creatures|wet creatures|"
                           r"burning targets|restrained targets|knocked out|sleeping|frightened creatures|"
                           r"large, huge|metal)\b")
CLASS_FEATURES = {"Monk": ["ki"], "Barbarian": ["rage"], "Druid": ["wildshape"], "Bard": ["bardic"],
                  "Cleric": ["channel", "shield_of_faith"], "Paladin": ["channel", "smite", "shield_of_faith"], "Rogue": ["sneak_attack"],
                  "Sorcerer": ["sorcery"], "Fighter": ["action_surge"]}
FEATURE_LOCK = [(r"patient defence|step of the wind|flurry of blows|\bki\b", "ki"),
                (r"\brage\b|\braging\b|when you rage", "rage"), (r"wild shape", "wildshape"),
                (r"bardic inspiration", "bardic"), (r"channel divinity|channel oath", "channel"),
                (r"sneak attack", "sneak_attack"), (r"\bsmites?\b", "smite"),
                (r"sorcery points?|tides of chaos|metamagic", "sorcery"), (r"action surge", "action_surge"),
                (r"manoeuvres?|superiority di", "manoeuvre")]
RACE_LOCK = [(re.compile(r"githyanki|\bgith\b|githborn"), "Githyanki"), (re.compile(r"\bdrow\b"), "Drow"),
             (re.compile(r"\ba dwarf\b|halflings and dwarves|gnomes are granted"), "Dwarf"),
             (re.compile(r"dragonborn"), "Dragonborn")]


def avg_dice(s):
    m = DICE.search(s)
    if m:
        return int(m.group(1)) * (int(m.group(2)) + 1) / 2
    m = re.search(r"\b(\d+)\b", s)
    return float(m.group(1)) if m else 0.0


def num(rx, t, default=1):
    m = re.search(rx, t)
    return int(m.group(1)) if m and m.group(1) else default


def effect_hits(t, attack_kind):
    """Apply RULES to one lower-cased effect text. -> list of (need, label, base value).
    attack_kind: what the rule should check damage riders against (weapon/unarmed/throw/spell)."""
    hits = []
    # effects that trigger when you heal / inspire someone buff THAT creature: only healers profit
    if re.search(r"when (?:you|the wearer) (?:heals?|inspires?)|heals? (?:a|another) creature|heal another|"
                 r"inspire an ally", t):
        return [("healer", "buffs the creatures you heal", 1.5)]
    # spell DC / spell attack
    if "spell save dc" in t:
        n = num(r"\+(\d)", t) if "+" in t else num(r"spell save dc (\d)", t)
        hits.append(("spell_dc", f"+{n} spell DC", 1.5 * n))
    if re.search(r"spell attack rolls?", t) and "penalty" not in t and "disadvantage" not in t:
        n = num(r"\+(\d)", t)
        hits.append(("spell_atk", f"+{n} spell attack", 1.0 * n))
    # weapon attack rolls
    m = re.search(r"\+(\d) (?:bonus )?to (?:attack and damage rolls with weapons|(?:melee |ranged |unarmed )?"
                  r"(?:weapon )?attack rolls|ranged attack rolls|melee attack rolls|attack rolls,)", t)
    if m and "spell attack" not in t[max(0, m.start() - 5):m.end() + 5]:
        n = int(m.group(1))
        q = "ranged" if "ranged" in t else "melee" if "melee" in t else "unarmed" if "unarmed" in t else ""
        hits.append(("weapon_atk" if q != "unarmed" else "unarmed", f"+{n} {q + ' ' if q else ''}attack rolls",
                     1.0 * n))
        if "damage rolls with weapons" in t:
            hits.append(("weapon_dmg", f"+{n} weapon damage", 0.5 * n * 2))
    elif re.search(r"\+1d4 bonus to (?:attack rolls|ranged weapon attacks|their ranged weapon attacks)", t):
        hits.append(("weapon_atk", "+1d4 attack rolls (conditional)", 1.25))
    # retaliation (damage to attackers) is a defensive effect, not a weapon rider
    retaliation = bool(re.search(r"attackers? (?:that|who) (?:hits?|miss)|the attacker (?:takes|must)|"
                                 r"(?:back )?at the attacker|creatures? (?:that|who) (?:hits?|damages?|miss(?:es)?) "
                                 r"(?:you|the wearer)|when (?:a|an) (?:foe|creature|enemy|melee attack) (?:hits|misses|"
                                 r"damages) (?:you|the wearer)|whenever a creature deals melee damage to the wearer|"
                                 r"damaged by a melee attack|struck by a melee attack|when you are hit|"
                                 r"that hit the wearer|hits you with a melee attack", t))
    if retaliation:
        hits.append(("retaliation", "damages attackers", 0.8))
    # damage riders
    if not retaliation and re.search(r"additional|extra|deal(?:s)? \d|\+\d+ (?:piercing|damage)|also deal", t) \
            and "damage" in t and "spell" not in t.split("damage")[0][-40:]:
        d = avg_dice(t)
        if THROW_RX.search(t):
            need, lab = "throw", "throw damage"
        elif "unarmed" in t and "weapon" not in t:
            need, lab = "unarmed", "unarmed damage"
        elif re.search(r"your weapon|weapon attacks?|infuses your weapon|with (?:a|your|this) weapon", t) and \
                "spell attack" not in t:
            need, lab = "weapon_dmg", "weapon damage"
        elif "cantrip" in t:
            need, lab = "cantrip", "cantrip damage"
        elif "ranged weapon" in t:
            need, lab = "weapon_dmg", "ranged weapon damage"
        elif "sneak attack" in t:
            need, lab = "sneak_attack", "Sneak Attack damage"
        elif re.search(r"spell|lightning charge", t):
            need, lab = None, None
        else:
            need, lab = "weapon_dmg", "weapon damage"
        if need and d:
            dm = DICE.search(t)
            hits.append((need, f"+{dm.group(0) if dm else int(d)} {lab}" + (" (on a crit)" if CRIT_ONLY.search(t)
                                                                               else ""), 0.5 * d))
    m = re.search(r"(?:damage equal to|double the damage from) (?:your|its|their) (strength|dexterity|constitution|"
                  r"intelligence|wisdom|charisma) modifier", t)
    if m and not retaliation:
        need = "cantrip" if "cantrip" in t else "unarmed" if "unarmed" in t and "weapon" not in t else "weapon_dmg"
        hits.append((need, f"adds your {m.group(1).capitalize()} modifier to damage", ("mod", ABILITY[m.group(1)], 0.6)))
    if re.search(r"cantrips deal additional damage|cantrips? deals? .*?add your spellcasting|"
                 r"add your spellcasting modifier to the damage", t):
        hits.append(("cantrip", "cantrips add your casting stat to damage", 2.0))
    if re.search(r"cantrips? that cost an action cost a bonus action|cantrips? targeting .*additional creature", t):
        hits.append(("cantrip", "extra cantrip casts / targets", 2.0))
    # crits
    if re.search(r"(?:need|needed) to roll a critical hit .*reduced by 1|critical hit when rolling a 19|"
                 r"reduce the number you need to roll a critical", t):
        hits.append(("crit", "crit range +1", 2.0))
    if re.search(r"next attack roll will be a critical hit", t):
        hits.append(("crit", "guaranteed crit after a kill", 2.0))
    if re.search(r"(?:score|land|lands|scoring) a critical hit|on a critical hit|whenever you score a crit", t) and \
            not any(h[1].endswith("(on a crit)") for h in hits):
        hits.append(("crit", "on-crit effect", 1.0))
    # advantage / accuracy
    if re.search(r"(?:enemies|foes|attackers)[^.]{0,30}disadvantage on attack rolls|disadvantage on attack rolls "
                 r"(?:that target|against) (?:you|the wearer)", t):
        hits.append(("ac", "attackers have disadvantage", 2.0))
    elif re.search(r"spell attack rolls against (?:you|the wearer) have disadvantage", t):
        hits.append(("saves", "spell attacks against you have disadvantage", 1.0))
    if re.search(r"(?<!dis)advantage on (?:all )?attack rolls", t) and not CREATURE_COND.search(t):
        cond = bool(re.search(r"while|when|against|if", t)) and "risky" not in t and "receive disadvantage" not in t
        hits.append(("adv", "advantage on attacks" + (" (conditional)" if cond else ""), 1.0 if cond else 2.0))
    elif re.search(r"(?<!dis)advantage on melee attack rolls", t):
        hits.append(("adv", "advantage on melee attacks (surrounded)", 1.0))
    m = re.search(r"disadvantage on (?:all )?saving throws", t)
    if m and not THIRD_PARTY.search(re.split(r"[.;]", t[:m.start()])[-1]):
        hits.append(("penalty", "disadvantage on your saving throws", -1.5))
    if "true strike" in t:
        hits.append(("adv", "True Strike rider", 0.7))
    # defence
    m = re.search(r"\+(\d) (?:bonus )?to (?:armour class|ac)\b|armour class increases by (\d)|^\+(\d) ac$|"
                  r"\+(\d) armour class|ac\((\d)\)|^ac \+(\d)$", t)
    if m:
        n = int(next(g for g in m.groups() if g))
        hits.append(("ac", f"+{n} AC", 1.0 * n))
    m = re.search(r"\+(\d) (?:bonus )?to (?:all )?(?:saving throws|savingthrow rolls)(?! against| when)", t)
    if m:
        hits.append(("saves", f"+{m.group(1)} saving throws", 0.8 * int(m.group(1))))
    elif re.search(r"advantage on saving throws against spells|bonus to saving throws against spells", t):
        hits.append(("saves", "better saves against spells", 1.0))
    if re.search(r"can't be critical hits|cannot be critical|no crits", t):
        hits.append(("crit_immune", "immune to critical hits", 1.5))
    m = re.search(r"(?:reduce all incoming damage by|all incoming damage is reduced by|take) (\d) less damage(?: from all)?|"
                  r"(?:reduce all incoming damage by|all incoming damage is reduced by) (\d)", t)
    if m:
        n = int(next(g for g in m.groups() if g))
        typed = re.search(r"less (piercing|slashing|bludgeoning) damage", t) and "from all" not in t
        hits.append(("dmg_reduction", f"-{n} damage taken" + (" (one type)" if typed else ""),
                     (0.3 if typed else 1.0) * n))
    if re.search(r"(?<!dis)advantage on (?:constitution saving throws|concentrat)|savingthrow constitution|"
                 r"concentrating saving", t):
        hits.append(("concentration", "advantage on Constitution / concentration saves", 1.5))
    if re.search(r"temporary hit points|regain \d|regain \dd|heals? (?:you|the wearer|the wielder)|"
                 r"hit points at the beginning|heal you", t) and "when you heal" not in t:
        hits.append(("temp_hp", "healing / temporary HP", 0.8))
    # mobility / action economy
    if re.search(r"misty step|dimension door|teleport|momentum|movement speed|freedom of movement|longstrider|"
                 r"\bfly\b|jump distance|dash", t) and not re.search(r"(?:target|enemy|foe|creature|entities)'?s? "
                                                                     r"movement|reduc\w* [^.]{0,30}movement|halved|"
                                                                     r"slow(?:s|ed)? (?:the|your|its) target", t):
        hits.append(("mobility", "mobility", 0.6))
    if re.search(r"extra action|additional action|additional bonus action|\bhasted?\b(?! spores)|bonus action to make "
                 r"an additional attack|extra attack|bonus-action attack|gains? [^.]{0,30}\band an action\b", t):
        hits.append(("action", "extra action / bonus-action attack", 1.0))
    m = re.search(r"\+(\d) (?:bonus )?to (?:[a-z ,]*?)initiative", t)
    if m:
        hits.append(("initiative", f"+{m.group(1)} initiative", 0.5 * int(m.group(1))))
    # named mechanics
    for need, rx, label in NAMED:
        if re.search(rx, t) and not any(h[0] == need for h in hits):
            if need == "stealth" and ("see invisib" in t or re.search(r"(?<!not impose )disadvantage on stealth", t)):
                continue          # detecting invisible enemies / a stealth penalty is not stealth for the wearer
            hits.append((need, label, 1.5))
    for dt in DMG_TYPES:
        if retaliation or not OUTGOING.search(t) or NOT_OUTGOING.search(t):
            break
        if re.search(r"\b" + dt + r"\b", re.sub(r"faerie fire", "", t)):
            if "resistance to " + dt in t or "resistant to " + dt in t:
                continue
            hits.append(("dmg_" + dt, dt.capitalize() + " damage", 1.0))
    if re.search(r"non-lethal damage", t):
        hits.append(("penalty", "non-lethal only", -4))
    if re.search(r"chance to stun the wielder|go mad|you take 1d4", t):
        hits.append(("penalty", "self-harm drawback", -1.5))
    return hits


NAMED = [
        ("hunters_mark", r"hunter's mark|marked by", "Hunter's Mark synergy"),
        ("sneak_attack", r"sneak attack", "Sneak Attack synergy"),
        ("smite", r"\bsmites?\b", "smite synergy"),
        ("lightning_charge", r"lightning charge", "Lightning Charges"),
        ("reverberation", r"reverberat", "Reverberation"),
        ("daze", r"\bdazed?\b", "Daze"),
        ("radiating_orb", r"radiating orb", "Radiating Orb"),
        ("illuminated", r"illuminated|light source|shines with|glowing light|sheds? (?:holy )?light|"
                        r"light in a (?:\d+m )?radius|aura of light", "light / illuminated"),
        ("arcane_acuity", r"arcane acuity", "Arcane Acuity"),
        ("arcane_synergy", r"arcane synergy", "Arcane Synergy"),
        ("heat", r"\bheat\b", "Heat"),
        ("frost", r"encrusted with frost|chilled|frostbit|\bice\b", "frost / ice"),
        ("bardic", r"bardic inspiration", "Bardic Inspiration"),
        ("ki", r"patient defence|step of the wind|\bki\b", "Ki features"),
        ("rage", r"\brage\b|raging|\bwrath\b", "Rage / Wrath"),
        ("wildshape", r"wild shape|shapeshift", "Wild Shape"),
        ("channel", r"channel divinity|channel oath", "Channel Divinity / Oath"),
        ("spell_slot", r"spell slot|doesn't cost a spell slot|sorcery point", "spell slots"),
        ("healer", r"when (?:you|the wearer) heals?|heal another|heals a creature|inspire an ally", "on-heal effects"),
        ("weapon_spell", r"spell or cantrip that uses a weapon|spellcasting ability modifier to attack|booming blade",
         "weapon cantrip synergy"),
        ("magic_missile", r"magic missile", "Magic Missile"),
        ("bonus_enchant", r"illusion or enchantment spells as a bonus action", "bonus-action Hold Person"),
        ("reaction_atk", r"attack roll as a reaction|riposte|reaction attack", "reaction attacks"),
        ("manoeuvre", r"manoeuvre", "manoeuvres"),
        ("piercing_vuln", r"vulnerab\w* to piercing", "piercing vulnerability"),
        ("stealth", r"(?<!see )invisib|hiding|\bhidden\b|stealth", "stealth / invisibility"),
        ("obscured", r"obscured|in shadow|magical darkness", "obscured / darkness"),
        ("kill_trigger", r"when you kill|reduce a target to 0|killing a hostile|kill an enemy|slay", "on-kill effect"),
        ("healed", r"whenever (?:the wearer|you) (?:is|are) healed", "triggers when you are healed"),
        ("returning", r"return(?:s)? to (?:its owner|your hand|the wielder)|returns when thrown|bound weapon",
         "returns when thrown"),
        ("throw", r"(?<!saving )\bthrow(?:n|ing)? (?:attacks?|damage)|(?<!saving )throw damage|throwing attacks",
         "throw synergy"),
        ("unarmed", r"unarmed", "unarmed synergy"),
        ("concentration", r"while (?:you are )?concentrating|requires concentration", "concentration synergy"),
    ]
NAMED_LABELS = {label for _n, _r, label in NAMED}


THROW_RX = re.compile(r"(?<!saving )\bthrow(?:n|s|ing)?\b")
CRIT_ONLY = re.compile(r"on a critical hit|critical hit with|when you (?:land|score) a critical|whenever you score a crit")
THIRD_PARTY = re.compile(r"\b(?:enemies|foes|targets?|creatures?|attackers?|they|it|its|their)\b")

ABILITY = {"strength": "STR", "dexterity": "DEX", "constitution": "CON", "intelligence": "INT", "wisdom": "WIS",
           "charisma": "CHA"}


def ability_changes(t):
    """-> list of (stat, mode, value, cap): mode 'add' (+n, cap) or 'set' (becomes at least v)."""
    out = []
    for m in re.finditer(r"(strength|dexterity|constitution|intelligence|wisdom|charisma) (?:becomes at least|"
                         r"increased to|score (?:becomes|is set to)) (\d+)|increases? (strength|dexterity|constitution|"
                         r"intelligence|wisdom|charisma) to (\d+)", t):
        stat = ABILITY[m.group(1) or m.group(3)]
        out.append((stat, "set", int(m.group(2) or m.group(4)), None))
    for m in re.finditer(r"\+(\d) (strength|dexterity|constitution|intelligence|wisdom|charisma)(?: \(max (\d+)\))?|"
                         r"increase your (strength|dexterity|constitution|intelligence|wisdom|charisma) score by (\d),"
                         r" to a maximum (\d+)", t):
        if m.group(1):
            out.append((ABILITY[m.group(2)], "add", int(m.group(1)), int(m.group(3)) if m.group(3) else 30))
        else:
            out.append((ABILITY[m.group(4)], "add", int(m.group(5)), int(m.group(6))))
    return out


def mod(v):
    return (v - 10) // 2


# ---------------------------------------------------------------- item helpers
def hand_raws(rec):
    br = rec.get("boosts_raw") or {}
    main = set()
    off = set()
    for k in ("BoostsOnEquipMainHand", "PassivesMainHand"):
        main |= {x.strip() for x in (br.get(k) or "").split(";") if x.strip()}
    for k in ("BoostsOnEquipOffHand", "PassivesOffHand"):
        off |= {x.strip() for x in (br.get(k) or "").split(";") if x.strip()}
    return main, off


def effects_for(rec, hand):
    main, off = hand_raws(rec)
    out = []
    for e in rec.get("effects") or []:
        raw = (e.get("raw") or "").strip()
        if hand == "main" and raw in off and raw not in main:
            continue
        if hand == "off" and raw in main and raw not in off:
            continue
        txt = e.get("text") or ""
        if e.get("kind") == "status" and "hidden technical" in txt:
            continue
        if "hidden technical passive" in txt or txt.startswith("(unresolved"):
            continue
        out.append(e)
    return out


def weapon_modes(rec):
    w = rec.get("weapon") or {}
    props = set(w.get("properties") or [])
    prof = set(w.get("proficiency") or [])
    texts = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
    modes = set()
    if rec["slot"] == "Ranged Main Weapon":
        modes.add("handxbow" if "HandCrossbows" in prof else "ranged")
    else:
        if "Twohanded" in props:
            modes.add("melee2h")
        else:
            modes.add("melee1h")
            if "Versatile" in props:
                modes.add("melee2h")
        if "Finesse" in props:
            modes.add("finesse")
        if "Light" in props:
            modes.add("light")
        if "Reach" in props:
            modes.add("reach")
        if "Thrown" in props or "thrown property" in texts:
            modes.add("thrown")
        if "Quarterstaffs" in prof:
            modes.add("staff")
    returning = bool(re.search(r"return(?:s)? to (?:its owner|your hand|the wielder)|returns when thrown|"
                               r"automatically returns", texts))
    return modes, props, returning


# ---------------------------------------------------------------- scoring
class Scorer:
    def __init__(self, items, char_id, cfg, bid, prof):
        self.items = items
        self.char = char_id
        self.cfg = cfg
        self.bid = bid
        self.b = BP.BUILDS[bid]
        self.prof = prof
        self.race = cfg["race"]
        self.needs = dict(DEFAULT_NEEDS)
        weaponish = bool(self.b["attacks"])
        if weaponish:
            self.needs.update({"weapon_dmg": 1.0, "weapon_atk": 1.0, "adv": 1.0, "crit": 0.7})
        else:
            self.needs.update({"adv": 0.3})
        if self.b["caster"]:
            self.needs.update({"concentration": 0.6, "spell_dc": 0.8 if self.b["caster"] == 1 else 1.5})
        self.needs.update(self.b["needs"])
        self.weaponish = weaponish
        self.features = set()
        for cls in self.b["classes"]:
            self.features |= set(CLASS_FEATURES.get(cls, []))
        if "Battle Master" in self.b["name"]:
            self.features.add("manoeuvre")
        # the build rages when any of its classes has the Rage feature (Barbarian levels)
        self.rages = "rage" in self.features

    # proficiency / avoid
    def usable(self, rec):
        req = (rec.get("requirements") or {}).get("proficiency") or []
        texts = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
        selfprof = "considered proficient with this armour" in texts
        avoid = set(self.b.get("avoid", []))
        arm = rec.get("armour") or {}
        if arm.get("shield") and "shield" in avoid:
            return False, "build does not use a shield"
        if rec["slot"] == "Breast" and arm.get("category") in ("Medium", "Heavy") and arm["category"].lower() in avoid:
            return False, f"build avoids {arm['category'].lower()} armour"
        # general rule: heavy body armour switches Rage off - never for a build that rages
        if rec["slot"] == "Breast" and arm.get("category") == "Heavy" and self.rages:
            return False, "heavy armour switches Rage off"
        if rec.get("weapon"):
            allow = self.b.get("weapons")
            if allow and rec["slot"] == "Melee Main Weapon" and not any(p in allow for p in req):
                return False, "Bladesong needs " + "/".join(a.lower() for a in allow)
            if req and not any(p in self.prof for p in req):
                modes, _p, _r = weapon_modes(rec)
                if any(self.b["attacks"].get(m_, 0) > 0 for m_ in modes):
                    return False, "no proficiency: " + "/".join(req)
                # the build never attacks with it: it is only carried for its passive effects
                return True, "not proficient - carried for its passive effects only"
            return True, ""
        if req and not selfprof and not all(p in self.prof for p in req):
            return False, "no proficiency: " + "/".join(p for p in req if p not in self.prof)
        return True, ""

    def cond_mult(self, t):
        if re.search(r"critical hit|on a crit", t) and \
                not re.search(r"need to roll a critical|critical hit when|will be a critical hit", t):
            # riders that only fire on a critical hit: crits are rare unless the build stacks them
            return 0.45 if self.needs.get("crit", 0) >= 3 else 0.3
        if CREATURE_COND.search(t):
            return 0.4
        t = COND_IGNORE.sub("", t)
        if not COND_WORDS.search(t):
            return 1.0
        for rx, need in COND_NEEDS:
            if re.search(rx, t) and self.needs.get(need, 0) >= 1:
                return 0.9
        return 0.6

    def race_mult(self, t):
        """Effects locked to a race, a class feature or a situation the build does not have count 0 or less."""
        for rx, feat in FEATURE_LOCK:
            if re.search(rx, t) and feat not in self.features:
                return 0.0
        for rx, race in RACE_LOCK:
            if rx.search(t):
                return 1.0 if race.lower() in self.race.lower() else 0.0
        if re.search(r"absolute's brand", t):
            return 0.5
        if re.search(r"while (?:you are |the wearer is )?drunk", t):
            return 0.2
        if re.search(r"wild magic|tides of chaos|necromancy|summoned creature|jaheira|shillelagh", t):
            return 0.1
        if re.search(r"not wearing armour|no armour", t):
            return 1.0 if self.b["armour"] in ("unarmoured",) else (0.5 if self.b["armour"] == "clothing" and
                                                                     self.b["offhand"] != "shield" else 0.0)
        if re.search(r"off-hand is empty|nothing in your free hand|only holding one weapon", t):
            return 1.0 if self.b["offhand"] in ("none",) and "melee1h" in self.b["attacks"] else 0.2
        # triggered by unarmed hits (not "your weapon attacks ... your unarmed attacks ..." texts)
        if re.search(r"(?:on|after|with) (?:an? )?(?:dealing damage with an )?unarmed (?:hit|attack|strike)|"
                     r"unarmed attacks? (?:deal|deals|also)", t) and "weapon" not in t and \
                not self.b["attacks"].get("unarmed"):
            return 0.0
        # ranged weapon riders for a build that never shoots (spell attacks and throws excluded)
        if re.search(r"\branged\b", t) and not re.search(r"\bmelee\b|\bthrown?\b|\bspell", t) and \
                not (self.b["attacks"].get("ranged") or self.b["attacks"].get("handxbow")):
            return 0.0
        # works only under Shield of Faith: the item's own once-per-rest copy, unless the class casts it
        if re.search(r"shield of faith", t) and "shield_of_faith" not in self.features:
            return 0.3
        return 1.0

    def stat_value(self, t, comps):
        for stat, mode_, v, cap in ability_changes(t):
            cur = self.b["stats"].get(stat, 10)
            new = max(cur, v) if mode_ == "set" else min(cap or 30, cur + v)
            gain = mod(new) - mod(cur)
            w = self.b["statw"].get(stat, 1.0 if stat == "CON" else 0.0)
            if gain > 0 and w:
                comps.append(("stat", f"{stat} {new} (+{gain} mod)", round(gain * w, 2)))

    def score(self, rec, slot):
        """-> (fit, components) for the item in that build slot."""
        comps = []
        r = RARITY_RANK.get(rec["rarity"], 0) * 0.5
        comps.append(("rarity", rec["rarity"], r))
        hand = "off" if slot in ("OffHand", "RangedOff") else "main"
        w = rec.get("weapon")
        arm = rec.get("armour") or {}
        wields = False          # the build attacks with this weapon (proficient, fits its attack modes)
        if w:
            modes, props, returning = weapon_modes(rec)
            att = self.b["attacks"]
            mw = max([att.get(m_, 0) for m_ in modes] or [0])
            req = (rec.get("requirements") or {}).get("proficiency") or []
            wields = self.weaponish and mw > 0 and (not req or any(p in self.prof for p in req))
            if slot == "OffHand":
                mw *= 0.6
            if self.weaponish and mw == 0 and slot == "MainHand" and rec["slot"] == "Melee Main Weapon":
                comps.append(("weapon", "does not fit the build's attack style", -4.0))
            # a weapon of a side mode where the build's main mode uses the same slot (a longbow for a dual hand
            # crossbow build): it should not win the slot on rarity / consensus alone
            slot_modes = {"Ranged": ("handxbow", "ranged"), "RangedOff": ("handxbow", "ranged")}.get(
                slot, ("melee2h", "melee1h", "finesse", "light", "thrown", "reach"))
            top = max([att.get(m_, 0) for m_ in slot_modes] or [0])
            mw_raw = mw / 0.6 if slot == "OffHand" else mw
            if self.weaponish and 0 < mw_raw < 0.5 * top:
                comps.append(("weapon", "not the build's main weapon type", -(top - mw_raw)))
            if self.weaponish and mw > 0:
                dmg = w.get("versatile") if ("melee2h" in modes and "Versatile" in props
                                              and self.b["offhand"] == "none") else w.get("damage")
                comps.append(("weapon", "fits " + "/".join(sorted(modes & set(att) or modes)), mw))
                comps.append(("weapon", f"{dmg} base damage", round(0.25 * avg_dice(dmg or "0"), 2)))
                if self.needs.get("gwm") and "melee2h" in modes and slot == "MainHand":
                    if "Heavy" in props:
                        comps.append(("weapon", "Heavy: Great Weapon Master works", self.needs["gwm"]))
                    elif "Twohanded" not in props or "Thrown" in props:
                        comps.append(("weapon", "not Heavy: no Great Weapon Master", -self.needs["gwm"]))
                if w.get("enchantment"):
                    comps.append(("weapon", f"+{w['enchantment']} weapon", 0.8 * w["enchantment"]))
                for ed in w.get("extra_damage") or []:
                    comps.append(("weapon_dmg", f"+{ed}", round(0.5 * avg_dice(ed) * self.needs.get("weapon_dmg", 1), 2)))
                    dt = ed.split()[-1].lower()
                    if self.needs.get("dmg_" + dt):
                        comps.append(("dmg_" + dt, f"{dt} damage type", self.needs["dmg_" + dt]))
                dt = (w.get("damage_type") or "").lower()
                if self.needs.get("dmg_" + dt):
                    comps.append(("dmg_" + dt, f"{dt} weapon", self.needs["dmg_" + dt] * 0.5))
                if "thrown" in modes and returning and self.needs.get("returning"):
                    comps.append(("returning", "returns when thrown", 1.5 * self.needs["returning"]))
                if "thrown" in modes and not returning and self.needs.get("returning"):
                    comps.append(("returning", "thrown but does not return", -1.0))
            elif not self.weaponish and slot == "MainHand" and "staff" in modes:
                comps.append(("weapon", "caster staff", 0.5))
        if slot == "Breast":
            dexm = mod(self.b["stats"]["DEX"])
            texts = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
            ac_total = arm.get("ac_total") or arm.get("ac") or 10
            cat = arm.get("category")
            cap = None if "full dexterity modifier" in texts else arm.get("dex_cap")
            if arm.get("ac_ability") == "Dexterity":
                eff = ac_total + (dexm if cap is None else min(dexm, cap))
            else:
                eff = ac_total
            first = next(iter(self.b["classes"]))
            if self.b["armour"] == "unarmoured" or (cat is None and first in ("Barbarian", "Monk")):
                # Unarmoured Defence (Barbarian CON / Monk WIS) applies to any clothing
                other = mod(self.b["stats"]["CON"]) if "Barbarian" in self.b["classes"] else mod(self.b["stats"]["WIS"])
                unarm = 10 + dexm + other + (arm.get("ac_boost") or 0)
                if cat is None:
                    eff = unarm
                elif "Monk" in self.b["classes"]:
                    comps.append(("armour", "armour breaks Martial Arts / Unarmoured Movement", -6))
            comps.append(("armour", f"AC {eff} for this build", round(eff - 14, 2)))
            if arm.get("stealth_disadvantage"):
                comps.append(("stealth", "stealth disadvantage", -1.5 * max(self.needs.get("stealth", 0), 0.3) / 1.0))
        elif arm.get("shield"):
            comps.append(("armour", f"shield +{arm.get('ac_total') or arm.get('ac')} AC",
                          float(arm.get("ac_total") or arm.get("ac") or 2)))
        spells = 0
        seen = set()
        item_needs = set()      # needs already given by the item's passives / boosts

        def status_like(e):
            # a status the item applies repeats the text of the passive that applies it: never count it twice
            return e.get("kind") == "status" or (e.get("text") or "").lower().startswith("applies ")
        effs = sorted(effects_for(rec, hand), key=status_like)
        for e in effs:
            t = deaccent(e.get("text") or "").lower()
            if not t or t in seen:
                continue
            seen.add(t)
            if e.get("kind") == "boost" and e.get("id") in ("WeaponEnchantment", "WeaponProperty"):
                continue
            if (slot == "Breast" or arm.get("shield")) and e.get("kind") == "boost" and e.get("id") == "AC":
                continue          # already part of the armour / shield AC above
            if re.search(r"bonded|[a-z]bound_passive", e.get("id") or "", re.I) and "Warlock" not in self.b["classes"]:
                continue          # "Favoured Weapon" bonuses of the Bonded weapons need a Pact of the Blade weapon
            rm = self.race_mult(t)
            if rm == 0:
                continue
            if e.get("kind") == "spell":
                if w and not wields and "once per" not in t:
                    continue      # a weapon action of a weapon this build never attacks with
                spells += 1
                if spells <= 3:
                    comps.append(("utility", "grants " + (e.get("name") or e["id"]), 0.3))
                for need, label, val in effect_hits(t, "spell"):
                    if isinstance(val, tuple):
                        continue
                    if need in ("mobility", "action", "daze", "reverberation", "radiating_orb", "lightning_charge",
                                "hunters_mark", "smite", "stealth", "magic_missile", "illuminated") or \
                            need.startswith("dmg_") and not w:
                        wv = self.needs.get(need, 0)
                        if wv:
                            comps.append((need, label + " (spell)", round(val * wv * 0.5, 2)))
                continue
            self.stat_value(t, comps)
            bugs = BUG_FLAGS.get(rec["stats_id"], set())
            cm = 1.0 if "always" in bugs else self.cond_mult(t)
            bug_mult = (2.0 if "double" in bugs and CRIT_ONLY.search(t) else 1.0) * \
                (0.5 if "halve" in bugs and "once per short rest" in t else 1.0)
            item_thrown = not w and re.search(r"when thrown|returns? to (?:its|their) owner", t)
            hits = effect_hits(t, "weapon")
            quals = [h for h in hits if h[0] in QUALIFIER_NEEDS and h[1] in NAMED_LABELS]
            payload = [h for h in hits if h not in quals]
            if quals and payload:
                if not any(self.needs.get(h[0], 0) > 0 and (not isinstance(h[2], (int, float)) or h[2] > 0)
                           for h in payload):
                    hits = payload          # e.g. "+1 spell DC while obscured" for an archer: nothing
                else:
                    hits = payload + [(n_, l_, 0.5) for n_, l_, _v in quals]
            for need, label, val in hits:
                wv = self.needs.get(need, 0)
                if not wv:
                    continue
                if status_like(e) and need in item_needs:
                    continue
                if w and need == "returning":
                    continue          # counted in the weapon base
                if w and not wields and (need in WIELD_NEEDS or need.startswith("dmg_")):
                    continue          # weapon riders only work for a build that attacks with the weapon
                if item_thrown and need in ("throw", "returning", "weapon_dmg", "mobility") or \
                        item_thrown and need.startswith("dmg_"):
                    continue          # the item itself is the thrown object - nothing for the wearer's throws
                if isinstance(val, tuple):
                    val = val[2] * max(0, mod(self.b["stats"].get(val[1], 10)))
                    if not val:
                        continue
                if w and need == "weapon_dmg" and e.get("kind") == "status" and \
                        any(ed.split()[0] in label for ed in w.get("extra_damage") or []):
                    continue          # already counted from the weapon's extra damage
                if w and need.startswith("dmg_") and e.get("kind") == "status" and \
                        any(ed.split()[-1].lower() == need[4:] for ed in w.get("extra_damage") or []):
                    continue
                v = val * wv * rm
                if need not in ("penalty", "ac", "saves", "crit_immune", "dmg_reduction", "stat") and val > 0:
                    v *= cm
                elif need in ("ac", "saves") and COND_WORDS.search(COND_IGNORE.sub("", t)):
                    v *= cm       # "+1 AC while obscured / as long as you have Lightning Charges"
                if not status_like(e):
                    item_needs.add(need)
                comps.append((need, label + (" (Patch 8 bug)" if bug_mult != 1.0 else ""), round(v * bug_mult, 2)))
        if "all_attacks" in BUG_FLAGS.get(rec["stats_id"], set()) and self.needs.get("weapon_atk"):
            comps.append(("weapon_atk", "+1 to all attack rolls (Patch 8 bug)", self.needs["weapon_atk"]))
        # caps: avoid one item collecting the same need many times (a weapon's damage riders are its point)
        capped, per = [], collections.defaultdict(float)
        for need, label, v in comps:
            limit = 10 if need == "weapon" else 8 if need in ("armour", "stat", "rarity") or (w and need == "weapon_dmg") else 6
            if v > 0 and per[need] + v > limit:
                v = max(0.0, limit - per[need])
            per[need] += max(v, 0)
            if v:
                capped.append((need, label, round(v, 2)))
        fit = round(sum(v for _, _, v in capped), 2)
        return fit, capped


# ---------------------------------------------------------------- availability / sources / warnings
KIND_SCORE = {"world": 5, "container": 5, "reward": 4.5, "trader": 4, "forge": 4, "npc_equipped": 3,
              "npc_inventory": 3, "combo": 3, "treasure": 1, "other": 1}


PLACEHOLDER_RX = re.compile(r"^Camp\b|Placeholder|Cinematic|^System level")


def playable(s):
    """Gameplay act 1-3 and not a camp / dream / cinematic placeholder of a global character."""
    return bool(source_act(s)) and not PLACEHOLDER_RX.search(s.get("region") or "")


def reliable(s):
    if not playable(s) or s.get("confidence") == "low":
        return False
    if s["kind"] == "treasure" and (s.get("chance") or 0) < 0.5:
        return False
    if s["kind"] == "trader" and (s.get("chance") or 0) < 0.25:
        return False
    if s["kind"] == "other" and not s.get("position"):
        return False
    return True


def source_rank(s, avail):
    k = KIND_SCORE.get(s["kind"], 1)
    k += {"high": 1, "medium": 0, "low": -3}.get(s.get("confidence"), 0)
    if s.get("steal"):
        k -= 2
    h = s.get("holder") or {}
    if s["kind"] in ("npc_equipped", "npc_inventory") and h.get("neutral") and not h.get("boss"):
        k -= 1.5
    if s.get("position"):
        k += 1
    if (s.get("chance") or 1) < 0.5:
        k -= 2
    a = source_act(s) or 9
    k -= 2 * max(0, a - (avail or a))
    return k


def describe_source(s, levels, alias=None):
    h = s.get("holder") or {}
    c = s.get("container") or {}
    kind = s["kind"]
    who = h.get("name") or c.get("name") or ""
    lv = s.get("level")
    region = s.get("region") or (levels.get(lv) or {}).get("region") or lv
    verb = {"world": "lying in the world", "container": f"in {who}" if who else "in a container",
            "reward": "quest reward", "trader": f"sold by {who}", "npc_equipped": f"worn by {who}",
            "npc_inventory": f"carried by {who}", "combo": "crafted (combine)", "forge": "forged",
            "treasure": "random loot", "other": "found"}.get(kind, kind.replace("_", " "))
    pos = s.get("position")
    where = f"{region}" + (f" (x {pos[0]:.0f}, z {pos[2]:.0f})" if pos else "")
    req = s.get("requires")
    txt = f"{verb} - {where}" if kind != "other" else f"in {where}"
    if alias:
        txt += f" (found there under the name '{alias}')"
    if req and kind not in ("world",):
        txt += f"; {req}"
    return short(txt, 260)


def source_flags(s):
    flags = []
    req = (s.get("requires") or "").lower()
    h = s.get("holder") or {}
    if s.get("steal") and s["kind"] in ("world", "container"):
        flags.append("theft")
    if s["kind"] in ("npc_equipped", "npc_inventory") and h.get("neutral") and not h.get("boss"):
        flags.append("kill or pickpocket a neutral NPC")
    if "darkurge" in (req + (s.get("notes") or "").lower()).replace(" ", ""):
        flags.append("Dark Urge story")
    if s["kind"] == "reward" and req:
        flags.append("quest / story")
    return flags


# ---------------------------------------------------------------- campaign / origin / party / path conditions
# Codes per item (universe[sid]["cond"], Lua field c) - vocabulary and tables in data/research/conditions.md:
#   durge  origin:<char>  party:<char>  path:<x>  !path:<x>  timing:<x>  note:<x>  costs:<char>
# Sources (union): the conditions table (research catalogue checked against the game data) plus general game-data
# rules: every source is Dark Urge story -> durge; every source sits in one companion's origin quest ->
# origin:<char>; every reliable source is a Last Light Inn trader / container -> !path:isobel_kill; Shar / Selune
# wording in the item's own research text -> path:shar / path:selune (vetoed when the game data has a sure free
# source). origin:<char> implies party:<char>; a path that costs an origin companion adds costs:<char>.
# Use: conditions are stored and shown; a set never holds two items whose conditions
# exclude each other (general rule over the tags, see path_conflict); items with costs:<char> stay out of sets and
# best lists (the mod re-enables them live when that path already happened); every other conditioned set item
# gets an unconditioned fallback (Lua fb).
CHAR_NAMES = {"shadowheart": "Shadowheart", "laezel": "Lae'zel", "wyll": "Wyll", "karlach": "Karlach",
              "gale": "Gale", "astarion": "Astarion", "darkurge": "the Dark Urge", "jaheira": "Jaheira"}
PATH_TEXT = {"shar": "Shadowheart kills the Nightsong (Shar path)",
             "selune": "Shadowheart spares the Nightsong (Selune path)",
             "tieflings": "side with the tieflings (goblin leaders killed)", "goblins": "side with the goblins",
             "kagha_kill": "Kagha killed or knocked out", "nere_kill": "Nere killed",
             "tribunal": "Murder Tribunal: kill Investigator Valeria", "mizora_freed": "Mizora freed in Wyll's quest",
             "karlach_kill": "Karlach killed for Mizora", "emperor_betray": "turn on the Emperor",
             "isobel_kill": "Isobel killed / Last Light falls", "isobel_alive": "Isobel alive",
             "astarion_ascends": "Astarion ascends", "absolute_brand": "wearer bears the Absolute's brand",
             "ethel_spared": "Auntie Ethel spared", "orpheus": "the Orpheus route",
             "ravengard_rescued": "Duke Ravengard rescued", "anders_or_karlach_kill": "Anders (or Karlach) killed",
             "bhaal_accept": "accept Bhaal", "bhaal_refuse": "refuse Bhaal",
             "durge_alfira": "Alfira is the Dark Urge's camp-murder victim (knock her out first: Quil dies instead)",
             "prisoners_rescued": "the Moonrise prisoners rescued (Lakrissa returns, or all tieflings)",
             "isobel_dead": "Isobel dead (any cause; loot her body)", "nere_dead": "Nere dead (killed or suffocated)"}
COND_RX_DURGE = re.compile(r"durge[- ]only|dark urge only|dark urge origin only|only (?:for|in) (?:a|the) dark urge|"
                           r"dark urge campaigns? only", re.I)
COND_RX_PATH = {"path:shar": re.compile(r"\bshar path|(?:kills?|killing|killed) the nightsong|nightsong (?:is )?killed",
                                        re.I),
                "path:selune": re.compile(r"\bsel[u]ne path|spar(?:e|es|ing|ed) the nightsong|free(?:s|ing)? the "
                                          r"nightsong|nightsong (?:lives|survives)", re.I)}
# sentences that name a path without gating this item (trader refuses Shadowheart "unless", losses, both paths)
COND_RX_NOT = re.compile(r"\b(?:unless|trader?s?|refus\w*|sells?|lost|lose|loses|locks?|dies|kills every|both|either|"
                         r"any path|alternative|instead)\b", re.I)
COND = {}            # sid -> sorted condition codes (filled in main)
# known Patch 8 bugs from the research (the item's own text): what the game really does is scored
BUG_NOTE = {}        # sid -> the research sentence about the bug (shown in the why text)
BUG_FLAGS = {}       # sid -> {"always", "all_attacks", "double", "halve"}
BUG_RULES = [(re.compile(r"always on|always active|regardless|every weapon attack|any damage type", re.I), "always"),
             (re.compile(r"\+1 (?:to )?all attack", re.I), "all_attacks"),
             (re.compile(r"(?:effectively|bugged to) 2d6", re.I), "double"),
             (re.compile(r"1/LR|once per long rest", re.I), "halve")]
GENERIC_RX = re.compile(r"\+\d\s*$")
FIXED_KINDS = ("world", "container", "npc_equipped", "npc_inventory", "reward", "forge", "combo")


def display_mode(rec, srcs, window=None):
    """How the mod shows an item, per act:
    m = marker on the map + inventory frame + why text; t = the marker goes on the trader; l = list window only;
    - = not obtainable in that act. Random-chance loot is list-only (with its odds). A generic +1 / +2 item is normal
    in an act where 5 or fewer copies are obtainable (world placements + trader stock in that act), else list-only.
    -> {"acts": "mtl", "copies": {act: n}, "odds": {act: best chance}, "generic": bool, "reason": text}"""
    play = [s for s in srcs if playable(s)]
    generic = not rec.get("unique") and bool(GENERIC_RX.search(rec["name"]))
    acts, copies, odds, reasons = "", {}, {}, []
    if not play:
        acts = "".join("m" if not window or window[0] <= a <= window[1] else "-" for a in (1, 2, 3))
        return {"acts": acts, "copies": {}, "odds": {}, "generic": generic, "reason": "no game-data source"}
    for a in (1, 2, 3):
        here = [s for s in play if source_act(s) == a]
        # fixed = placed or guaranteed (a 100% treasure table drop counts too)
        fixed = [s for s in here if s["kind"] != "trader" and s.get("confidence") != "low" and
                 (s["kind"] in FIXED_KINDS and s.get("chance") is None or (s.get("chance") or 0) >= 0.99)]
        # trader stock is re-rolled on every restock: a trader that stocks it at least 25% of the time is a source
        traders = [s for s in here if s["kind"] == "trader" and (s.get("chance") or 0) >= 0.25]
        n = len({(s.get("level"), tuple(round(x) for x in s["position"]) if s.get("position") else s.get("template"),
                  (s.get("holder") or {}).get("name")) for s in fixed}) +             len({(t.get("holder") or {}).get("name") for t in traders})
        copies[a] = n
        odds[a] = round(max([s.get("chance") or 0 for s in here] or [0]), 4)
        if generic and n > 5:
            acts += "l"
            reasons.append(f"Act {a}: generic item, {n} copies")
        elif fixed:
            acts += "m"
        elif traders:
            acts += "t"
        elif here:
            acts += "l"
            if all(s.get("confidence") == "low" for s in here):
                reasons.append(f"Act {a}: only an unconfirmed (low-confidence) source")
            else:
                reasons.append(f"Act {a}: random loot only (best chance {odds[a]:.0%})")
        else:
            acts += "-"
    if window:            # act override (conditions.md): outside the real acts nothing, inside at least a marker
        acts = "".join("-" if not window[0] <= a <= window[1] else ("m" if ch == "-" else ch)
                       for a, ch in zip((1, 2, 3), acts))
    return {"acts": acts, "copies": copies, "odds": odds, "generic": generic, "reason": "; ".join(reasons)}


FAMILIES = []        # [set of path names] - alternatives of one story choice (conditions.md)
PATH_COSTS = {}      # path -> origin companion lost on it (conditions.md)
MATERIALS = []       # [{"name", "cap", "items", "note"}] scarce materials (conditions.md)
TRADER_LOSS = []     # [(region part, holder name or "", codes)] traders lost on a path (conditions.md)
ACT_OVERRIDE = {}    # sid -> (first act, last act, reason) (conditions.md "Act overrides")


def load_condition_table(items):
    """data/research/conditions.md -> {sid: set(codes)}; fills FAMILIES, PATH_COSTS, MATERIALS."""
    out = {}
    path = os.path.join(DATA, "research", "conditions.md")
    if not os.path.exists(path):
        return out
    section = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("## "):
                section = line[3:].strip().lower()
                continue
            if not line.startswith("|") or re.match(r"^\|[\s:|-]+\|?\s*$", line):
                continue
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if section.startswith("exclusive") and len(cells) >= 2 and cells[0] != "Family":
                FAMILIES.append({p.strip() for p in cells[1].split(",") if p.strip()})
            elif section.startswith("paths that cost") and len(cells) >= 2 and cells[0] != "Path":
                PATH_COSTS[cells[0]] = cells[1]
            elif section.startswith("traders lost") and len(cells) >= 3 and not cells[0].startswith("Place"):
                TRADER_LOSS.append((cells[0], cells[1], [c.strip() for c in cells[2].split(",") if c.strip()]))
            elif section.startswith("act overrides") and len(cells) >= 4 and cells[0] in items:
                ACT_OVERRIDE[cells[0]] = (int(cells[2]), int(cells[3]), cells[4] if len(cells) > 4 else "")
            elif section.startswith("scarce") and len(cells) >= 3 and cells[0] != "Material":
                MATERIALS.append({"name": cells[0], "cap": int(cells[1]),
                                  "items": [x.strip() for x in cells[2].split(",") if x.strip() in items],
                                  "note": cells[3] if len(cells) > 3 else "",
                                  "copies": int(cells[4]) if len(cells) > 4 and cells[4].isdigit() else 1})
            elif section == "items" and len(cells) >= 3 and cells[0] in items:
                out[cells[0]] = {c.strip().strip("`") for c in cells[2].split(",") if c.strip()}
    return out


def cond_text(codes):
    out = []
    if "durge" in codes:
        out.append("Only exists in a Dark Urge campaign")
    paths = [c[5:] for c in codes if c.startswith("path:")]
    for p in paths:
        out.append("Needs story path: " + PATH_TEXT.get(p, p.replace("_", " ")))
    for c in codes:
        if c.startswith("origin:") and not (c == "origin:shadowheart" and {"shar", "selune"} & set(paths)):
            out.append(f"Companion quest reward: {CHAR_NAMES.get(c[7:], c[7:])}'s quest")
    origins = {c[7:] for c in codes if c.startswith("origin:")}
    for c in codes:
        if c.startswith("party:") and c[6:] not in origins:
            out.append(f"Needs {CHAR_NAMES.get(c[6:], c[6:])} in the party")
    for c in codes:
        if c.startswith("costs:"):
            out.append(f"Costs {CHAR_NAMES.get(c[6:], c[6:])} (companion lost) - left out of sets unless that "
                       f"already happened")
    for c in codes:
        if c.startswith("!path:"):
            out.append("Lost if " + PATH_TEXT.get(c[6:], c[6:].replace("_", " ")) + " - get it first")
        elif c.startswith("timing:"):
            out.append("Timing: " + c[7:].replace("_", " "))
    return ". ".join(out) + ("." if out else "")


def item_conditions(sid, srcs, flags, nt, table):
    """-> sorted condition codes for one item from the condition table, its game-data sources and its own
    research texts."""
    codes = set(table.get(sid, ()))
    if "Dark Urge campaigns only" in flags:
        codes.add("durge")
    known = [s for s in srcs if s.get("region") or s.get("requires")]
    owners = {origin_of_source(s) for s in known}
    if known and len(owners) == 1 and None not in owners:
        o = owners.pop()
        if o == "darkurge":
            codes.add("durge")
        elif o in CHAR_NAMES:
            codes.add(f"origin:{o}")
    rel = [s for s in srcs if reliable(s)]
    # every reliable source is a trader / place that is lost on a path (Last Light Inn, Roah / Araj at Moonrise)
    for rule_codes in {tuple(r[2]) for r in TRADER_LOSS}:
        rules = [r for r in TRADER_LOSS if tuple(r[2]) == rule_codes]
        stock = [s for s in rel if s["kind"] != "npc_equipped"]      # a person's worn gear is not shop stock
        if stock and len(stock) == len(rel) and all(any(r[0] in (s.get("region") or "") and
                           (not r[1] or r[1] == (s.get("holder") or {}).get("name")) for r in rules) for s in rel):
            codes.update(rule_codes)
    texts = [t for _f, t in (nt.get("texts", []) + nt.get("warnings", []) + nt.get("get", []) +
                             nt.get("missable", []))]
    if COND_RX_DURGE.search(" || ".join(texts)):
        codes.add("durge")
    # a path from the research wording counts only when the game data has no sure free source for the item
    free = any(s.get("confidence") == "high" and playable(s) and not origin_of_source(s) and
               s["kind"] in ("world", "container", "trader", "npc_equipped", "npc_inventory") for s in srcs)
    if not free and not ({"path:shar", "path:selune"} & codes):
        n = collections.Counter()
        for t in texts:
            for sent in re.split(r"(?<=[.;!?])\s+|\s\|\s", t):
                if COND_RX_NOT.search(sent):
                    continue
                for code, rx in COND_RX_PATH.items():
                    n[code] += len(rx.findall(sent))
        a, b = "path:shar", "path:selune"
        if n[a] and n[a] >= 2 * n[b]:
            codes.add(a)
        elif n[b] and n[b] >= 2 * n[a]:
            codes.add(b)
    if codes & {"path:shar", "path:selune"}:
        codes.add("origin:shadowheart")          # the Nightsong choice is Shadowheart's quest
    for c in list(codes):
        if c.startswith("origin:"):
            codes.add("party:" + c[7:])
        if c.startswith("path:") and c[5:] in PATH_COSTS:
            codes.add("costs:" + PATH_COSTS[c[5:]])
    return sorted(codes)


ACTS = {}            # sid -> (first act, last act) (filled in main)
UNIVERSE = {}        # sid -> universe record (filled in main)


def conflicting(a, b, act_a=None, act_b=None):
    """Two condition-code sets that cannot both be true in one playthrough: two paths of one family, or a path
    item and an item lost on that path that only becomes obtainable in a later act (same or earlier act: buy it
    first - a timing note, not an exclusion). act_a / act_b = first obtainable acts (None: treat as exclusive)."""
    pa = {c[5:] for c in a if c.startswith("path:")}
    pb = {c[5:] for c in b if c.startswith("path:")}
    la = {c[6:] for c in a if c.startswith("!path:")}
    lb = {c[6:] for c in b if c.startswith("!path:")}
    if pa & lb and (act_a is None or act_b is None or act_b > act_a):
        return True
    if pb & la and (act_a is None or act_b is None or act_a > act_b):
        return True
    for fam in FAMILIES:
        x, y = pa & fam, pb & fam
        if x and y and x != y:
            return True
    return False


def path_conflict(sid, chosen_sids):
    mine = set(COND.get(sid, ()))
    if not mine:
        return False
    return any(conflicting(mine, set(COND.get(s, ())), ACTS.get(sid, (None,))[0], ACTS.get(s, (None,))[0])
               for s in chosen_sids if s != sid)


def cond_relevant(sid, cid):
    """Conditions that need a fallback for this character: durge (not for the Dark Urge), party / path codes
    (a character's own companion-quest rewards and party presence are always met for them)."""
    out = []
    for c in COND.get(sid, ()):
        if c in (f"origin:{cid}", f"party:{cid}") or (c == "durge" and cid == "darkurge"):
            continue
        if c.startswith(("timing:", "note:", "origin:")) or c == "unobtainable":
            continue
        out.append(c)
    return out


def costs_origin(sid):
    return any(c.startswith("costs:") for c in COND.get(sid, ()))


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    items = load_items()
    sources = load_sources()
    levels = load_levels()
    recipes = load_recipes()
    dnames = build_display_names(items)
    idx = NameIndex(items, sources, dnames)
    with open(os.path.join(SCORES_DIR, "name_matches.json"), encoding="utf-8") as f:
        nm = json.load(f)
    aliases = nm["aliases"]
    # names shared by several rarities (Dark Justiciar Gauntlets Uncommon / Rare): a rarity written right after
    # the name in the research picks that variant
    variants = {}
    for rn, m in nm["matches"].items():
        rar = {}
        for i in m["stats_ids"]:
            rar.setdefault(items[i]["rarity"], i)
        if len(rar) > 1:
            for a in (rn, split_rarity(rn)[0], deaccent(m["game_name"])):
                if aliases.get(a) == m["chosen"]:
                    variants.setdefault(a, rar)
    # short forms used in loadout lines ("Rings: Strange Conduit + Callous Glow"): a name of 3+ words ending in its
    # item-type word also matches without that word, when the short form is unique and not another alias
    shorts = collections.defaultdict(set)
    for a, sid in aliases.items():
        mm = re.match(r"^(.+?) (?:Ring|Amulet|Cloak|Gloves|Boots|Helmet|Helm|Armour|Shield|Hat|Circlet)$", a)
        if mm and len(a.split()) >= 3 and not mm.group(1).lower().startswith(("the ", "a ")):
            shorts[mm.group(1)].add(sid)
    aliases = dict(aliases)
    for sh, sids in list(shorts.items()):
        if len(sids) == 1 and sh not in aliases and len(sh.split()) >= 2:
            aliases[sh] = next(iter(sids))
    scanner = Scanner(aliases, variants)
    # in-game name per item: several stats ids have more than one in-game name (templates); use the name the
    # research uses whose templates actually appear in gameplay sources, then the most-cited one
    name_votes = collections.defaultdict(collections.Counter)
    for rn, m in nm["matches"].items():
        name_votes[m["chosen"]][m["game_name"]] += len(m["files"])
    research_name = {}
    for sid, votes in name_votes.items():
        def name_key(n, sid=sid, votes=votes):
            tm = set(idx.name_templates.get((sid, n)) or [])
            nsrc = sum(1 for s in sources.get(sid, []) if s.get("template") in tm and source_act(s))
            return (nsrc > 0, votes[n], nsrc)
        research_name[sid] = max(votes, key=name_key)
    gear, ba_origins = load_builds_lua(BP.BUILDS_LUA)
    LEVEL_REGION.update({k: (v.get("region") or k) for k, v in levels.items() if isinstance(v, dict)})
    # every Builds.lua build is a BuildAdvisor build: stats / feats / fighting styles come from Builds.lua
    for bid_, old, new in BP.sync_with_builds_lua():   # raises on a Builds.lua build without a profile
        print(f"profile {bid_}: stats synced with Builds.lua {old} -> {new}")
    BP.check_subclass_names()                         # raises on a subclass name the game does not show

    # ---- research parsing (all characters + crafted)
    parsers = {}
    for cid, cfg in BP.CHARACTERS.items():
        parsers[cid] = ResearchParser(cid, cfg, cfg["builds"], scanner).parse()
    crafted = ResearchParser("crafted", {"research": "crafted.md", "tags": {}, "default_tags": "*"}, [], scanner).parse()
    # same in-game name, several copies (Sentient Amulet: Act 1 Rare / Act 3 Very rare): a mention in an act
    # section means the copy that exists by then
    same_name = collections.defaultdict(set)
    for rn, m in nm["matches"].items():
        grp = [i for i in m["stats_ids"] if items[i]["name"] == items[m["chosen"]]["name"]
               and items[i]["slot"] == items[m["chosen"]]["slot"]]
        same_name[m["chosen"]].update(grp)
    first_act = {sid: idx.play[sid][1] for sid in items}

    def act_copy(sid, act):
        if not act or first_act.get(sid, 9) <= act:
            return sid
        alts = [i for i in same_name.get(sid, ()) if first_act.get(i, 9) <= act]
        return max(alts, key=lambda i: RARITY_RANK.get(items[i]["rarity"], 0)) if alts else sid
    for p in list(parsers.values()):
        for m in p.mentions:
            m["sid"] = act_copy(m["sid"], m["act"])
        for sd in p.seeds:
            for it in sd["items"]:
                it["sid"] = act_copy(it["sid"], sd["act"])
                if it.get("alt_of"):
                    it["alt_of"] = act_copy(it["alt_of"], sd["act"])
    notes = collections.defaultdict(lambda: {"warnings": [], "missable": [], "get": [], "do": [], "texts": []})
    for p in list(parsers.values()) + [crafted]:
        for sid, nt in p.notes.items():
            for k in nt:
                notes[sid][k] += nt[k]
    research_acts = collections.defaultdict(set)
    for p in parsers.values():
        for m in p.mentions:
            if m["act"]:
                research_acts[m["sid"]].add(m["act"])

    # ---- the item universe: equippable groups + elixirs
    def candidate_slots(rec):
        s = rec["slot"]
        if s == "Melee Main Weapon":
            return ["MainHand", "OffHand"]
        if s == "Ranged Main Weapon":
            return ["Ranged", "RangedOff"]
        if s == "Melee Offhand Weapon":
            return ["OffHand"]
        if s in ITEM_SLOT:
            return ["Ring1"] if s == "Ring" else [ITEM_SLOT[s]]
        if s == "Consumable" and rec["name"].startswith("Elixir"):
            return ["Elixir"]
        return []

    tname = {}
    for (sid_, n_), ts in idx.name_templates.items():
        for t_ in ts:
            tname.setdefault((sid_, t_), n_)

    def src_alias(sid, s):
        """In-game name of the source's template when it differs from the name we recommend."""
        n_ = tname.get((sid, s.get("template")))
        return n_ if n_ and n_ != (research_name.get(sid) or items[sid]["name"]) else None

    cond_table = load_condition_table(items)
    universe = {}
    for sid, rec in items.items():
        slots = candidate_slots(rec)
        if not slots:
            continue
        srcs = sources.get(sid, [])
        nm_tm = set(idx.name_templates.get((sid, research_name.get(sid, rec["name"]))) or [])
        named = [s for s in srcs if s.get("template") in nm_tm and playable(s)]
        if named:
            srcs = named          # locations of the template that carries this in-game name
        rel = [s for s in srcs if reliable(s)]
        anyp = [s for s in srcs if playable(s)]
        # last act in which the item can still be obtained (sets are per act: later acts leave earlier-only items out)
        last = max(source_act(s) for s in (rel or [s for s in srcs if playable(s)])) if (rel or any(
            playable(s) for s in srcs)) else 3
        if rel:
            avail, basis = min(source_act(s) for s in rel), "game data"
        elif anyp:
            avail, basis = min(source_act(s) for s in anyp), "game data (random / low-confidence source only)"
        elif research_acts.get(sid):
            avail, basis = min(research_acts[sid]), "research (no game-data source found)"
        else:
            continue
        # plain Common gear is never recommended, but it is the last-resort fallback of a conditional slot (an Act 1
        # cloak when the only magic one is the Dark Urge's Mantle)
        fallback_only = rec["rarity"] == "Common" and sid not in research_name
        if fallback_only and not rel:
            continue
        ranked = sorted(srcs if rel == [] else rel, key=lambda s: -source_rank(s, avail))
        best_srcs = []
        seenpos = set()
        for s in ranked:
            key = (s.get("level"), tuple(round(x) for x in s["position"]) if s.get("position") else s["kind"])
            if key in seenpos or not playable(s):
                continue
            seenpos.add(key)
            best_srcs.append(s)
            if len(best_srcs) >= 3:
                break
        flags = set()
        if best_srcs:
            flags |= set(source_flags(best_srcs[0]))
            if all("theft" in source_flags(s) or "kill or pickpocket a neutral NPC" in source_flags(s)
                   for s in (rel or anyp)):
                flags |= set(source_flags(best_srcs[0]))
            if all("Dark Urge story" in source_flags(s) for s in (rel or anyp)):
                flags.add("Dark Urge campaigns only")
        nt = notes.get(sid) or {}
        if nt.get("missable"):
            flags.add("missable")
        if nt.get("warnings"):
            flags.add("research warning")
        cond = item_conditions(sid, sources.get(sid, []), flags, nt, cond_table)
        if "durge" in cond:
            flags.add("Dark Urge campaigns only")
        if cond:
            COND[sid] = cond
        name = research_name.get(sid) or rec["name"]
        tm = idx.name_templates.get((sid, name)) or rec.get("templates") or []
        recipe = [r for r in recipes if any(x.get("id") == sid for x in r.get("results") or [])]
        universe[sid] = {
            "sid": sid, "name": name, "rarity": rec["rarity"], "slots": slots, "item_slot": rec["slot"],
            "act": ACT_OVERRIDE[sid][0] if sid in ACT_OVERRIDE else avail,
            "act_basis": ("override: " + ACT_OVERRIDE[sid][2]) if sid in ACT_OVERRIDE else basis,
            "last_act": ACT_OVERRIDE[sid][1] if sid in ACT_OVERRIDE else max(last, avail), "templates": list(tm) + [t for t in rec.get("templates") or []
                                                                     if t not in tm],
            "sources": best_srcs, "flags": sorted(flags), "notes": nt, "recipe": recipe[:1], "cond": cond,
            "fallback_only": fallback_only,
            "research_acts": sorted(research_acts.get(sid, [])),
        }
    # display mode (marker / trader / list only) and Patch 8 bug notes
    for sid, u in universe.items():
        u["display"] = display_mode(items[sid], sources.get(sid, []),
                                    ACT_OVERRIDE[sid][:2] if sid in ACT_OVERRIDE else None)
        for _f, t in u["notes"].get("texts", []) + u["notes"].get("warnings", []):
            for sent in re.split(r"(?<=[.;!?])\s+|\s\|\s|\s-\s", t):
                if not re.search(r"\bbug(?:ged|gy|s)?\b", sent, re.I):
                    continue
                named = {x[2] for x in scanner.find(sent)}
                if named and sid not in named:
                    continue          # the sentence is about another item of the same row
                BUG_NOTE.setdefault(sid, short(sent.strip(" .;|"), 170))
                BUG_FLAGS.setdefault(sid, set()).update(f for rx, f in BUG_RULES if rx.search(sent))
    UNIVERSE.update(universe)
    for sid, u in universe.items():
        ACTS[sid] = (u["act"], u["last_act"])
    print(f"universe: {len(universe)} items ({time.time() - t0:.1f}s)")

    file_char = {cfg["research"]: cid for cid, cfg in BP.CHARACTERS.items()}

    # ---- per item text helpers
    def own_first(lst, char_file):
        # this character's file, then the crafted-items file, then the other characters' files
        a = [t for f, t in lst if f == char_file] + [t for f, t in lst if f == "crafted.md" != char_file]
        b = [t for f, t in lst if f not in (char_file, "crafted.md")]
        out = []
        for t in a + b:
            if t not in out:
                out.append(t)
        return out

    def warning_text(sid, char_file):
        return clean_text(_warning_text(sid, char_file))

    def how_text(sid, char_file):
        return clean_text(_how_text(sid, char_file))

    def _warning_text(sid, char_file):
        """Theft / kill / story / missable / Dark-Urge-only warning: research text first, else the source data."""
        u = universe[sid]
        parts = []
        nt = u["notes"]
        w = own_first(nt.get("warnings", []), char_file)
        if w:
            parts.append(short(w[0], 180).rstrip(".") + ".")
        if u["sources"]:
            s = u["sources"][0]
            fl = [f for f in source_flags(s) if f != "Dark Urge story"]
            if fl and not w:
                parts.append(short(f"{', '.join(fl).capitalize()}: {s.get('requires') or ''}", 160).rstrip(".") + ".")
        # campaign / origin / path conditions (data/research/conditions.md + game-data rules); a character's own
        # origin quest and, for the Dark Urge, the Durge-only items need no note
        cid_ = file_char.get(char_file)
        codes = [c for c in COND.get(sid, []) if not (cid_ and (c == f"party:{cid_}" or
                                                                (c == "durge" and cid_ == "darkurge")))]
        said = " ".join(parts).lower()
        for sent in [x for x in cond_text(codes).split(". ") if x]:
            key = {"Only exists in a Dark Urge": "dark urge", "Needs story path: Shadowheart": "nightsong",
                   "Needs story path: Murder Tribunal": "valeria"}
            if not any(sent.startswith(k) and v in said for k, v in key.items()):
                parts.append(sent.rstrip(".") + ".")
        ms = own_first(nt.get("missable", []), char_file)
        if ms:
            m0 = short(ms[0], 140)
            if m0[:40].lower() not in " ".join(parts).lower():
                parts.append("Missable: " + m0.rstrip(".") + ".")
        return " ".join(parts)

    def _how_text(sid, char_file):
        u = universe[sid]
        parts = []
        g = own_first(u["notes"].get("get", []), char_file)
        if g:
            parts.append(short(g[0], 260))
        elif u["sources"]:
            parts.append(describe_source(u["sources"][0], levels, src_alias(sid, u["sources"][0])))
        do = own_first(u["notes"].get("do", []), "crafted.md")
        if do:
            parts.append("Steps: " + short(do[0], 220))
        if u["recipe"]:
            r = u["recipe"][0]
            ins = []
            for x in r.get("inputs") or []:
                if x.get("type") == "Category":
                    ins.append("any " + x.get("id", "").replace("ALCH_Affinity_", "").lower() + " extract")
                elif x.get("name") and x.get("name") != x.get("id"):
                    ins.append(x["name"])
            if ins:
                parts.append("Combine: " + " + ".join(ins) + ".")
        return " ".join(parts)

    # ---- character loop
    all_chars = {}
    lua_items = {}
    md_sets = []
    contradictions = []
    for cid, cfg in BP.CHARACTERS.items():
        parser = parsers[cid]
        char_file = cfg["research"]
        builds_out = {}
        for bid in cfg["builds"]:
            b = BP.BUILDS[bid]
            # every build that exists in Builds.lua is a BuildAdvisor build (not only the origin's listed ones)
            origin = "campaign" if b["origin"] == "campaign" else \
                ("BuildAdvisor" if bid in gear or bid in ba_origins.get(cid, []) else "community")
            prof = BP.proficiencies(cid, cfg["race"], b)
            # level-by-level plan: Builds.lua for BuildAdvisor builds, else research + rules (marked inferred)
            plan = b.get("plan") if origin == "BuildAdvisor" and b.get("plan") else \
                BP.level_plan(bid, research_build_text(cid, bid))
            if origin != "BuildAdvisor":
                b["feats"], b["styles"] = plan["feats"], plan["styles"]
            sc = Scorer(items, cid, cfg, bid, prof)
            # consensus mentions for this build
            ments = []
            for pid, p in parsers.items():
                wfile = 1.0 if pid == cid else XFILE
                for m in p.mentions:
                    tg = m["tags"]
                    if pid == cid:
                        if tg == "*":
                            ments.append((m, 0.7))
                        elif bid in tg:
                            ments.append((m, 1.0))
                        else:
                            # a build without its own research section borrows its closest researched build's
                            for xc, xb, xw in BP.XREFS.get(bid, []):
                                if pid == xc and xb in tg:
                                    ments.append((m, xw))
                                    break
                    else:
                        if tg != "*" and bid in tg:
                            ments.append((m, wfile))
                        for xc, xb, xw in BP.XREFS.get(bid, []):
                            if pid == xc and tg != "*" and xb in tg:
                                ments.append((m, xw))
            if bid in gear:
                for s_ in segments(gear[bid]):
                    for st, en, sid, _ in scanner.find(s_):
                        ments.append(({"sid": sid, "role": "gear", "act": None, "w": 1.0, "file": "Builds.lua",
                                       "line": 0, "text": gear[bid]}, 1.0))
            cons_act = collections.defaultdict(lambda: collections.defaultdict(float))
            cons_any = collections.defaultdict(float)
            cons_detail = collections.defaultdict(list)
            for m, wf in ments:
                v = ROLE_W[m["role"]] * m["w"] * wf
                if m["act"]:
                    cons_act[m["sid"]][m["act"]] += v
                else:
                    cons_any[m["sid"]] += v
                cons_detail[m["sid"]].append(f'{m["role"]}{"/A" + str(m["act"]) if m["act"] else ""} '
                                             f'{m["file"]}:{m["line"]} x{round(m["w"] * wf, 2)}')

            def consensus(sid):
                out, prev = {}, 0.0
                for a in (1, 2, 3):
                    spec = max(cons_act[sid].get(a, 0.0), CARRY * prev)
                    prev = spec
                    out[a] = round(min(CONS_CAP, spec + cons_any.get(sid, 0.0)), 2)
                return out

            scored = {}
            for sid, u in universe.items():
                rec = items[sid]
                ok, why_not = sc.usable(rec)
                per_slot = {}
                for slot in u["slots"]:
                    if slot == "OffHand" and rec["slot"] == "Melee Main Weapon":
                        modes, props, _r = weapon_modes(rec)
                        if b["offhand"] not in ("dual", "any") or "light" not in modes or "melee2h" in modes and \
                                "Versatile" not in props or "NoDualWield" in props:
                            continue
                    if slot == "OffHand" and rec["slot"] == "Melee Offhand Weapon" and b["offhand"] in ("none", "dual"):
                        continue
                    if slot == "RangedOff":
                        modes, props, _r = weapon_modes(rec)
                        if not b.get("dual_ranged") or "handxbow" not in modes:
                            continue
                    per_slot[slot] = sc.score(rec, slot)
                if not per_slot:
                    continue
                cons = consensus(sid)
                scored[sid] = {"usable": ok, "why_not": why_not, "slots": per_slot, "cons": cons,
                               "cons_detail": cons_detail.get(sid, [])[:12]}

            def total(sid, slot, act, scored=scored, owned=True, unusual=False, cid=cid):  # bound per build (REG)
                s = scored.get(sid)
                u = universe[sid]
                if not unusual and is_unusual(sid, cid):
                    return None       # Dark-Urge-only item for another origin: a conditional alternative only
                if not s or not s["usable"] or slot not in s["slots"] or u["act"] > act or u["fallback_only"]:
                    return None       # not obtainable yet (or plain gear: fallback only)
                if u["last_act"] < act and not owned:
                    return None       # no longer obtainable: counts only when the party owns it ("only if owned")
                if costs_origin(sid):
                    return None       # costs an origin companion: only when that already happened (mod, live)
                if "unobtainable" in COND.get(sid, ()):
                    return None       # research: cannot be obtained in Patch 8
                fit, comps = s["slots"][slot]
                if fit - sum(v for n_, _l, v in comps if n_ == "rarity") <= 0 and s["cons"][act] <= 0:
                    return None          # rarity alone does not make an item a recommendation
                return round(fit + s["cons"][act], 2)

            # best / runner per slot per act
            slots_for = [x for x in SLOT_ORDER if x != "Ring2"]
            if b["offhand"] == "none":
                slots_for.remove("OffHand")
            if not b.get("dual_ranged"):
                slots_for.remove("RangedOff")
            best = {}
            pair_of = {"OffHand": "MainHand", "RangedOff": "Ranged"}
            for act in (1, 2, 3):
                best[act] = {}
                for slot in slots_for:
                    ranked = sorted(((total(sid, slot, act), sid) for sid in scored), key=lambda x: -(x[0] or -99))
                    ranked = [(t_, s_) for t_, s_ in ranked if t_ is not None and t_ > 0]
                    if slot in pair_of and best[act].get(pair_of[slot], {}).get("best"):
                        # one item cannot fill both hands: the off-hand table skips the main-hand pick
                        mainpick = best[act][pair_of[slot]]["best"]
                        pair = {pair_of[slot]: {"sid": mainpick}}
                        ranked = [(t_, s_) for t_, s_ in ranked if s_ != mainpick and slot_ok(s_, slot, pair, items)]
                    if slot == "Ring1":
                        best[act]["Ring1"] = {"best": ranked[0][1] if ranked else None,
                                              "runner": ranked[2][1] if len(ranked) > 2 else None,
                                              "top": [[s_, t_] for t_, s_ in ranked[:6]]}
                        best[act]["Ring2"] = {"best": ranked[1][1] if len(ranked) > 1 else None,
                                              "runner": ranked[3][1] if len(ranked) > 3 else None, "top": []}
                    else:
                        best[act][slot] = {"best": ranked[0][1] if ranked else None,
                                           "runner": ranked[1][1] if len(ranked) > 1 else None,
                                           "top": [[s_, t_] for t_, s_ in ranked[:5]]}

            # ---- item why text (per build)
            def item_why(sid):
                s = scored[sid]
                slot = max(s["slots"], key=lambda k: s["slots"][k][0])
                comps = sorted((c for c in s["slots"][slot][1] if c[0] not in ("rarity",) and c[2] > 0),
                               key=lambda c: -c[2])
                labels = []
                for need, label, v in comps:
                    if label not in labels:
                        labels.append(label)
                    if len(labels) >= 3:
                        break
                roles = collections.Counter(d.split()[0].split("/")[0] for d in s["cons_detail"])
                cons_txt = []
                if roles.get("best"):
                    cons_txt.append("community best pick")
                elif roles.get("runner"):
                    cons_txt.append("community runner-up")
                if roles.get("set"):
                    cons_txt.append(f"in {roles['set']} research set{'s' if roles['set'] > 1 else ''}")
                if roles.get("consensus"):
                    cons_txt.append("called BiS / consensus")
                txt = short("; ".join(labels), 100)   # cut the labels, never the community part (player text)
                if cons_txt:
                    txt += (" - " if txt else "") + ", ".join(cons_txt)
                bug = f" Patch 8 bug: {short(clean_text(BUG_NOTE[sid]), 110).rstrip('.')}." if BUG_NOTE.get(sid) else ""
                return clean_text(txt + bug)

            # ---- synergy sets
            sets = {}
            seeds_all = [(sd, 1.0, cid) for sd in parser.seeds]
            for pid, p in parsers.items():
                if pid == cid:
                    continue
                for sd in p.seeds:
                    if sd["tags"] != "*" and (bid in sd["tags"] or any(
                            pid == xc and xb in sd["tags"] for xc, xb, _ in BP.XREFS.get(bid, []))):
                        seeds_all.append((sd, XFILE, pid))
            for act in (1, 2, 3):
                out_sets = []
                own = [(sd, w, pid) for sd, w, pid in seeds_all if sd["act"] == act and pid == cid and
                       (sd["tags"] == "*" or bid in sd["tags"])]
                xs = [(sd, w, pid) for sd, w, pid in seeds_all if sd["act"] == act and pid != cid]
                for sd, w, pid in own + (xs if len(own) < 3 else []):
                    st = build_seed_set(sd, cid, bid, act, scored, universe, items, total, slots_for, b)
                    if st and not any(overlap(st, o) > 0.85 for o in out_sets):
                        out_sets.append(st)
                    if len(out_sets) >= 5:
                        break
                if len(out_sets) < 3:
                    for st in auto_sets(bid, act, scored, universe, items, total, slots_for, sc, out_sets):
                        out_sets.append(st)
                        if len(out_sets) >= 3:
                            break
                for k, st in enumerate(out_sets, 1):
                    st["id"] = f"{cid}.{bid}.a{act}.{k}"
                    st["build"] = bid
                    st["act"] = act
                    st["fallback"] = fallbacks(st, cid, act, scored, total, items)
                    # main picks obtainable in this act when an earlier-act item wins by only a little
                    st["owned_alt"] = prefer_obtainable(st, act, total)
                    if st["owned_alt"]:
                        st["fallback"] = fallbacks(st, cid, act, scored, total, items)
                    st["cond_alt"] = unusual_alternatives(st, cid, act, scored, total, items)
                    finish_set(st, cid, universe, warning_text, how_text, char_file)
                sets[act] = out_sets

            # ---- research act contradictions (game data says later than research)
            for sid in scored:
                u = universe[sid]
                ra = [m["act"] for m, _w in ments if m["sid"] == sid and m["act"] and m["role"] in ("best", "runner", "set")]
                if ra and min(ra) < u["act"] and u["act_basis"].startswith("game data"):
                    contradictions.append({"char": cid, "build": bid, "item": u["name"], "sid": sid,
                                           "research_act": min(ra), "game_act": u["act"],
                                           "source": describe_source(u["sources"][0], levels, src_alias(sid, u["sources"][0])) if u["sources"] else ""})

            # keep the useful part of the score table
            keep = set()
            for act in best:
                for slot, v in best[act].items():
                    keep |= {x[0] for x in v["top"]}
            for act in sets:
                for st in sets[act]:
                    keep |= {it["sid"] for it in st["items"].values()}
                    keep |= {x["sid"] for it in st["items"].values() for x in (it.get("fallback"), it.get("owned_alt"),
                                                                               it.get("cond_alt")) if x and x.get("sid")}
            keep |= {sid for sid in scored if scored[sid]["cons_detail"]}
            item_scores = {}
            for sid in sorted(keep):
                s = scored[sid]
                u = universe[sid]
                item_scores[sid] = {
                    "name": u["name"], "slots": {k: {"fit": v[0], "components": v[1]} for k, v in s["slots"].items()},
                    "usable": s["usable"], "why_not": s["why_not"], "act": u["act"], "consensus": s["cons"],
                    "consensus_detail": s["cons_detail"],
                    "total": {a: max([t_ for t_ in (total(sid, sl, a) for sl in s["slots"]) if t_ is not None],
                                     default=None) for a in (1, 2, 3)},
                    "why": item_why(sid) if s["usable"] else "",
                }
            REG[(cid, bid)] = {"scored": scored, "total": total, "slots_for": slots_for}
            builds_out[bid] = {
                "name": b["name"], "origin": origin, "about": b.get("why", ""), "note": b.get("note", ""),
                "classes": b["classes"], "proficiencies": sorted(prof),
                "feats": b.get("feats", []), "styles": b.get("styles", []),
                "subclasses": BP.SUBCLASSES.get(bid, {}),
                "plan": plan,
                "profile": {k: b[k] for k in ("stats", "statw", "attacks", "offhand", "armour", "caster", "needs")},
                "best": {a: {sl: {"best": v["best"], "runner": v["runner"], "top": v["top"]}
                             for sl, v in best[a].items()} for a in best},
                "sets": sets, "items": item_scores,
            }
        all_chars[cid] = {"character": cid, "name": cfg["name"], "race": cfg["race"], "research": char_file,
                          "builds": builds_out}

    # ---- party level: unique items and scarce materials go to the best-fit character; the others see "better on X" and their next pick moves up. Every character keeps its own lists.
    owners = party_owners(all_chars, items, ba_origins, universe)
    party_alternatives(all_chars, owners, items, universe, warning_text, how_text)
    with open(os.path.join(SCORES_DIR, "owners.json"), "w", encoding="utf-8") as f:
        json.dump(owners, f, indent=1, ensure_ascii=False)
    item_owners = {}
    for g in owners.values():
        for sid in g["items"]:
            own = g["owners"] if g["kind"] == "unique" else sorted({c_ for c_, i_ in g["pairs"] if i_ == sid})
            if own:
                item_owners[sid] = own

    # ---- item info (shared) for every item that is recommended anywhere
    used = set()
    for cid, c in all_chars.items():
        for bid, bo in c["builds"].items():
            for a, sl in bo["best"].items():
                for v in sl.values():
                    used |= {x for x in (v["best"], v["runner"]) if x}
            for a, sts in bo["sets"].items():
                for st in sts:
                    used |= {it["sid"] for it in st["items"].values()}
                    used |= {x["sid"] for it in st["items"].values() for x in (it.get("fallback"), it.get("owned_alt"),
                                                                               it.get("cond_alt")) if x and x.get("sid")}
                    used |= {it["party_alt"]["sid"] for it in st["items"].values() if it.get("party_alt")}
            for a, sl in bo["best"].items():
                used |= {v["party"] for v in sl.values() if v.get("party")}
    item_info = {}
    for sid in sorted(used):
        u = universe[sid]
        item_info[sid] = {
            "name": u["name"], "game_record_name": items[sid]["name"], "rarity": u["rarity"],
            "slot": u["item_slot"], "act": u["act"], "act_basis": u["act_basis"], "templates": u["templates"],
            "flags": u["flags"], "cond": u["cond"], "display": u["display"], "bug": BUG_NOTE.get(sid, ""),
            "last_act": u["last_act"], "owners": item_owners.get(sid, []),
            "owner_exact_tie": next((g.get("tied", []) for g in owners.values()
                                     if sid in g["items"] and g.get("exact_tie")), []),
            "owner_ranking": [r for g in owners.values() if sid in g["items"] for r in g["ranking"]
                              if g["kind"] == "unique" or r["item"] == sid],
            "sources": [{"kind": s["kind"], "level": s.get("level"), "act": source_act(s), "region": s.get("region"),
                         "position": s.get("position"), "holder": (s.get("holder") or {}).get("name"),
                         "container": (s.get("container") or {}).get("name"), "requires": s.get("requires"),
                         "steal": s.get("steal"), "confidence": s.get("confidence"),
                         "text": describe_source(s, levels, src_alias(sid, s))} for s in u["sources"]],
            "research_warnings": [t for f, t in u["notes"].get("warnings", [])][:3],
            "research_missable": [t for f, t in u["notes"].get("missable", [])][:2],
            "research_get": [f"{f}: {t}" for f, t in u["notes"].get("get", [])][:3],
            "steps": [t for f, t in u["notes"].get("do", [])][:1],
        }
    for cid, c in all_chars.items():
        mine = set()
        for bo in c["builds"].values():
            mine |= set(bo["items"])
            for sts in bo["sets"].values():
                for st in sts:
                    mine |= {x["sid"] for it in st["items"].values() for x in (it.get("party_alt"), it.get("fallback"),
                             it.get("owned_alt"), it.get("cond_alt")) if x and x.get("sid")
                             if x}
            for sl in bo["best"].values():
                mine |= {v["party"] for v in sl.values() if v.get("party")}
        c["item_info"] = {sid: item_info[sid] for sid in item_info if sid in mine}
        c["formula"] = __doc__.split("SCORING FORMULA")[1].strip()
        with open(os.path.join(SCORES_DIR, f"{cid}.json"), "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1, ensure_ascii=False)
    write_sets_md(all_chars, item_info)
    write_lua(all_chars, item_info, universe, warning_text, how_text)
    cpath = os.path.join(SCORES_DIR, "_contradictions.json")
    if contradictions:      # research act earlier than every game-data source (for review)
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(contradictions, f, indent=1, ensure_ascii=False)
    elif os.path.exists(cpath):
        os.remove(cpath)
    # summary
    nsets = sum(len(sts) for c in all_chars.values() for bo in c["builds"].values() for sts in bo["sets"].values())
    print(f"characters {len(all_chars)}, builds {sum(len(c['builds']) for c in all_chars.values())}, "
          f"sets {nsets}, recommended items {len(item_info)}, act contradictions {len(contradictions)}, "
          f"{time.time() - t0:.1f}s")


# ---------------------------------------------------------------- player-facing text
LEVEL_REGION = {}    # level id -> the game's region display name (data/items_all/levels.json; filled in main)
_LEVEL_RX = [None]


def clean_text(t):
    """Player-facing texts (how to get / why / warnings) never show research-file references or internal ids:
    "(see crafted.md §24)", "astarion.md:122", level ids (CTY_Main_A -> Lower City), story goal / quest step ids."""
    if not t:
        return t
    t = re.sub(r"\s*[-,;]?\s*\(?\bsee\s+(?:\w+\.md)?\s*(?:§\s*\d+)?[^().;|]*?(?:\.md|§\s*\d+)[^().;|]*\)?", "", t)
    t = re.sub(r"\s*\(?\bsee\s+§\s*\d+\)?", "", t)
    t = re.sub(r"\b\w+\.md(?::\d+(?:-\d+)?)?(?:\s*§\s*\d+)?", "", t)
    t = re.sub(r"§\s*\d+", "", t)
    t = re.sub(r"\bstory goal \w+", "a story event", t)
    t = re.sub(r"\s*\((?:[A-Z][A-Za-z0-9]*_)+[A-Za-z0-9_]*\)(?:,\s*step \w+)?", "", t)
    t = re.sub(r",?\s*\bstep [A-Z]\w+", "", t)
    if _LEVEL_RX[0] is None and LEVEL_REGION:
        _LEVEL_RX[0] = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(LEVEL_REGION, key=len, reverse=True))
                                  + r")\b")
    if _LEVEL_RX[0] is not None:
        t = _LEVEL_RX[0].sub(lambda m: LEVEL_REGION[m.group(1)], t)
    # pipeline wording (warnings are built from source records)
    t = re.sub(r"(?:Quest / story|Quest|Story):\s*a story event\.?", "", t)
    t = re.sub(r"Kill or pickpocket a neutral npc:\s*(?:kill(?:/loot)? or pickpocket |kill(?:/loot)? )?([^.;(]+?)\s*"
               r"\(neutral/friendly: crime or story cost\)", r"Taking it from \1 means killing or pickpocketing them "
               r"(a crime or a story cost)", t, flags=re.I)
    t = re.sub(r"\(neutral/friendly: crime or story cost\)", "(a crime or a story cost)", t)
    t = re.sub(r";?\s*key id [\w-]+", "", t)
    t = re.sub(r"[^.]*\bThe user's\b[^.]*\.?", "", t)
    t = re.sub(r"\s*\((?:verify|to verify|unverified)[^)]*\)", "", t, flags=re.I)
    t = re.sub(r"\bLaezel\b", "Lae'zel", t)
    t = re.sub(r"\bLLI\b", "Last Light Inn", t)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\)\(", ") (", t)
    t = re.sub(r"\s+([.,;:])", r"\1", t)
    t = re.sub(r"([.;:])\1+", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


# ---------------------------------------------------------------- party-level owners
REG = {}             # (char, build) -> {"scored", "total", "slots_for"} of that build (filled in main)


CAST_STAT = {"Wizard": "INT", "Sorcerer": "CHA", "Warlock": "CHA", "Bard": "CHA", "Paladin": "CHA", "Cleric": "WIS",
             "Druid": "WIS", "Ranger": "WIS"}


def build_numbers(bid):
    """Per-build numbers for the numeric tie model (level 12, Builds.lua stats): attacks per round A, hit chance p
    against AC 16, damage per hit D, casting DC / spells per round. Same idea as analysis/astarion_dpr.py."""
    b = BP.BUILDS[bid]
    st, cls, att = b["stats"], b["classes"], b["attacks"]
    subs = BP.SUBCLASSES.get(bid, {})
    if subs.get("Warlock") == "The Hexblade" and att:
        ab = "CHA"
    elif any(att.get(m_, 0) >= 2 for m_ in ("ranged", "handxbow", "finesse")):
        ab = "DEX"
    else:
        ab = "STR" if st["STR"] >= st["DEX"] else "DEX"
    m = mod(st[ab])
    pb = 4
    extra = 3 if cls.get("Fighter", 0) >= 11 else 2 if (cls.get("Fighter", 0) >= 5 or
                                                          any(cls.get(c_, 0) >= 5 for c_ in ("Barbarian", "Ranger",
                                                                                              "Paladin", "Monk")) or
                                                          (cls.get("Warlock", 0) >= 5 and subs.get("Warlock") ==
                                                           "The Hexblade")) else 1
    bonus = 0
    if b["offhand"] == "dual" or b.get("dual_ranged"):
        bonus += 1
        if subs.get("Rogue") == "Thief":
            bonus += 1                       # Fast Hands: a second bonus action
    if "Monk" in cls:
        bonus += 2                           # Flurry of Blows
    if subs.get("Barbarian") == "Berserker":
        bonus += 1                           # Frenzy
    A = (extra + bonus) if att else 0
    p = min(0.95, max(0.05, (21 - (16 - (m + pb))) / 20))
    cast = None
    if b["caster"]:
        cast = max((CAST_STAT[c_] for c_ in cls if c_ in CAST_STAT), key=lambda a_: st.get(a_, 10))
    # exposure: how often the character is attacked (front line > thrower > archer > caster); movement matters most
    # to melee builds
    melee = max([att.get(m_, 0) for m_ in ("melee2h", "melee1h", "unarmed", "reach")] or [0])
    ranged = max([att.get(m_, 0) for m_ in ("ranged", "handxbow")] or [0])
    if melee >= 2 or b["armour"] == "heavy" or b["offhand"] == "shield" and att:
        exposure = 1.5
    elif att.get("thrown", 0) >= 2:
        exposure = 1.25
    elif ranged >= 2:
        exposure = 1.0
    else:
        exposure = 0.85
    return {"A": A, "p": p, "D": 6.5 + m, "ab": ab, "m": m, "cast": cast, "st": st, "exposure": exposure,
            "move": 1.5 if melee >= 2 else 1.2 if att.get("thrown", 0) >= 2 else 1.0,
            "spells": 1.0 if b["caster"] == 2 else 0.5 if b["caster"] else 0.0}


def numeric_value(bid, rec, slot, comps):
    """Sustained value per round of one item for one build (finer than the fit: it uses attacks per round, hit
    chance and damage of THAT build). Used only to break ownership ties between characters."""
    N = build_numbers(bid)
    b = BP.BUILDS[bid]
    needs = dict(DEFAULT_NEEDS, **b["needs"])
    A, p, D = N["A"], N["p"], N["D"]
    hand_A = 1 if slot in ("OffHand", "RangedOff") else A
    v = 0.0
    w = rec.get("weapon")
    if w:
        ench = w.get("enchantment") or 0
        riders = sum(avg_dice(x) for x in w.get("extra_damage") or [])
        if any(c[0] == "weapon" and c[2] > 0 for c in comps):
            dmg = avg_dice(w.get("damage") or "0") + N["m"] + ench + riders
            v += hand_A * (p + 0.05 * ench) * dmg
        else:
            # a backup weapon (a bow on a melee build): one attack with its own ability
            texts = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
            abil = "DEX" if rec["slot"] == "Ranged Main Weapon" or "Finesse" in (w.get("properties") or []) else "STR"
            am = max(mod(N["st"]["STR"]), mod(N["st"]["DEX"])) if abil == "DEX" and "Finesse" in (
                w.get("properties") or []) else mod(N["st"][abil])
            if "strength modifier" in texts:
                am += max(0, mod(N["st"]["STR"]))
            pp = min(0.95, max(0.05, (21 - (16 - (am + 4 + ench))) / 20))
            v += 0.5 * pp * (avg_dice(w.get("damage") or "0") + am + ench + riders)
    for need, label, val in comps:
        if need in ("weapon", "rarity", "armour"):
            continue
        wt = needs.get(need, 0) or 1.0
        raw = val / wt
        if need == "weapon_dmg":
            v += hand_A * p * 2 * raw
        elif need == "weapon_atk":
            v += A * 0.05 * raw * D
        elif need == "adv":
            v += A * 0.2 * D * raw / 2
        elif need == "crit":
            v += A * 0.05 * (D - N["m"]) * raw / 2
        elif need in ("ac", "dmg_reduction"):
            v += 1.8 * raw * N["exposure"]
        elif need in ("saves", "crit_immune"):
            v += 0.6 * raw * N["exposure"]
        elif need == "temp_hp":
            v += 3 * raw * N["exposure"]
        elif need == "mobility":
            v += 0.5 * raw * N["move"]
        elif need == "initiative":
            v += raw * (0.3 * A * D / 10 + N["spells"])
        elif need in ("spell_dc", "spell_atk"):
            v += N["spells"] * 0.05 * (raw / (1.5 if need == "spell_dc" else 1.0)) * 25
        elif need == "stat":
            mm = re.match(r"(STR|DEX|CON|INT|WIS|CHA) \d+ \(\+(\d+) mod\)", label)
            if mm:
                gain = int(mm.group(2))
                if mm.group(1) == N["ab"]:
                    v += A * (0.05 * D + p) * gain
                elif mm.group(1) == N["cast"]:
                    v += N["spells"] * 0.05 * 25 * gain
                elif mm.group(1) == "CON":
                    v += 1.2 * gain * N["exposure"]
        else:
            v += 0.5 * raw
    if rec.get("armour") and (slot == "Breast" or (rec.get("armour") or {}).get("shield")):
        for c in comps:
            if c[0] == "armour":
                v += 1.8 * c[2] * N["exposure"]     # AC over 14 for this build / shield AC
    return round(v, 4)


def research_build_text(cid, bid):
    """The build's own bullets in section 1 ("Builds covered") of the character's research file (by its tag codes
    or words), for the level plan of community builds."""
    cfg = BP.CHARACTERS[cid]
    path = os.path.join(DATA, "research", cfg["research"])
    try:
        txt = deaccent(open(path, encoding="utf-8").read())
    except OSError:
        return ""
    m = re.search(r"^## 1\..*?(?=^## 2\.)", txt, re.M | re.S)
    if not m:
        return ""
    codes = [c for c, bids in list(cfg.get("tags", {}).items()) + list(cfg.get("word_tags", {}).items())
             if bids != "*" and bid in bids]
    out = []
    for block in re.split(r"\n(?=\s*(?:- |\d+\. |\| ))", m.group(0)):
        if any(re.search(r"(?<![A-Za-z])" + re.escape(c) + r"(?![a-z])", block) for c in codes):
            out.append(block)
    return " ".join(out)


def primary_build(cid, cfg, ba_origins):
    """The build the character most likely plays: BuildAdvisor's pick for that origin, else the campaign build."""
    ba = [b for b in ba_origins.get(cid, []) if b in cfg["builds"]]
    return ba[0] if ba else cfg["builds"][0]


def party_owners(all_chars, items, ba_origins, universe):
    """-> {key: {"name", "kind", "cap", "owners", "ranking": [...]}} for every unique item (game Unique flag) or
    scarce-material group that appears in the sets of two or more characters. Ranking per character: the best
    game-data FIT (no research / consensus weight) of the item in that character's PRIMARY
    build sets (other builds only when the primary build never uses
    it; marked primary=False and ranked after). Owner = rank 1 (a material group: the top `cap` characters)."""
    occ = collections.defaultdict(list)
    for cid, c in all_chars.items():
        prim = primary_build(cid, BP.CHARACTERS[cid], ba_origins)
        for bid, bo in c["builds"].items():
            reg = REG[(cid, bid)]
            for act, sts in bo["sets"].items():
                for st in sts:
                    for slot, it in st["items"].items():
                        key = "Ring1" if slot == "Ring2" else slot
                        # ownership compares game-data build fit only (no research / consensus weight)
                        sl_ = reg["scored"].get(it["sid"], {}).get("slots", {}).get(key)
                        sc_ = sl_[0] if sl_ else 0.0
                        occ[it["sid"]].append({"char": cid, "build": bid, "set": st["id"], "act": int(act),
                                               "slot": slot, "score": round(sc_, 2), "primary": bid == prim})
    groups = {}
    for sid, lst in occ.items():
        if items[sid].get("unique"):
            groups[sid] = {"name": universe[sid]["name"], "kind": "unique", "cap": 1, "items": [sid], "occ": lst}
    for m in MATERIALS:
        lst = [dict(o, item=sid) for sid in m["items"] for o in occ.get(sid, [])]
        if lst:
            for sid in m["items"]:
                groups.pop(sid, None)
            groups["material:" + m["name"]] = {"name": m["name"], "kind": "material", "cap": m["cap"],
                                               "items": m["items"], "occ": lst, "note": m["note"],
                                               "copies": m["copies"]}
    out = {}
    for key, g in groups.items():
        if g["kind"] == "material":
            # best occurrence per (character, item); greedy: capacity and copies per item
            bp = {}
            for o in g["occ"]:
                k = (o["char"], o["item"])
                if k not in bp or (o["primary"], o["score"]) > (bp[k]["primary"], bp[k]["score"]):
                    bp[k] = o
            ranking = sorted(bp.values(), key=lambda o: (not o["primary"], -o["score"]))
            pairs, per_item = [], collections.Counter()
            for o in ranking:
                if len(pairs) < g["cap"] and per_item[o["item"]] < g["copies"]:
                    pairs.append([o["char"], o["item"]])
                    per_item[o["item"]] += 1
            out[key] = {"name": g["name"], "kind": "material", "cap": g["cap"], "items": g["items"],
                        "owners": sorted({c_ for c_, _i in pairs}), "pairs": pairs,
                        "ranking": [{k_: o[k_] for k_ in ("char", "build", "set", "act", "slot", "score", "primary",
                                                          "item")} for o in ranking], "note": g.get("note", "")}
            continue
        best = {}
        for o in g["occ"]:
            o.setdefault("item", key if g["kind"] == "unique" else o.get("item"))
            k = (o["primary"], o["score"])
            if o["char"] not in best or k > (best[o["char"]]["primary"], best[o["char"]]["score"]):
                best[o["char"]] = o
        if len(best) < 2 and g["kind"] == "unique":
            continue          # only one character wants it: no party conflict
        ranking = sorted(best.values(), key=lambda o: (not o["primary"], -o["score"]))
        tie = len(ranking) > 1 and (ranking[0]["primary"], ranking[0]["score"]) ==             (ranking[1]["primary"], ranking[1]["score"])
        out[key] = {"name": g["name"], "kind": g["kind"], "cap": g["cap"], "items": g["items"], "tie": tie,
                    "owners": [o["char"] for o in ranking[:g["cap"]]],
                    "ranking": [{k_: o[k_] for k_ in ("char", "build", "set", "act", "slot", "score", "primary", "item")}
                                for o in ranking], "note": g.get("note", "")}
        for x in out[key]["ranking"]:
            x.setdefault("item", key)
    # ties (same main-build fit): the finer numeric model decides (sustained value per round for that character's
    # build: attacks per round, hit chance, damage, AC / HP, DC); equal numbers stay marked as an exact tie
    for key, v in out.items():
        if v["kind"] != "unique" or not v["tie"]:
            continue
        r = v["ranking"]
        top = (r[0]["primary"], r[0]["score"])
        tied = [x for x in r if (x["primary"], x["score"]) == top]
        for x in tied:
            sl_ = "Ring1" if x["slot"] == "Ring2" else x["slot"]
            comps = REG[(x["char"], x["build"])]["scored"][x["item"]]["slots"][sl_][1]
            x["numeric"] = numeric_value(x["build"], items[x["item"]], sl_, comps)
        tied.sort(key=lambda x: -x["numeric"])
        v["owners"] = [tied[0]["char"]]
        v["tied"] = [x["char"] for x in tied]
        v["tie_break"] = {x["char"]: x["numeric"] for x in tied}
        v["exact_tie"] = len(tied) > 1 and abs(tied[0]["numeric"] - tied[1]["numeric"]) < 1e-6
        rk = {x["char"]: x for x in r}
        v["ranking"] = [rk[x["char"]] for x in tied] + [x for x in r if x not in tied]
    return out


def blocked_for(sid, cid, owners):
    """-> owner list when this item belongs to other characters at party level, else None."""
    for key, g in owners.items():
        if sid not in g["items"]:
            continue
        if g["kind"] == "material":
            if [cid, sid] not in g["pairs"]:
                return sorted({c_ for c_, i_ in g["pairs"] if i_ == sid}) or g["owners"]
        elif cid not in g["owners"]:
            return g["owners"]
    return None


def party_alternatives(all_chars, owners, items, universe, warning_text=None, how_text=None):
    """Sets: an item owned by another character gets owner + party_alt (the best item for that slot that is not
    owned elsewhere and fits the set). Best tables: party = the first pick not owned elsewhere."""
    for cid, c in all_chars.items():
        for bid, bo in c["builds"].items():
            reg = REG[(cid, bid)]
            for act, sts in bo["sets"].items():
                a = int(act)
                for st in sts:
                    for slot, it in st["items"].items():
                        own = blocked_for(it["sid"], cid, owners)
                        if not own:
                            continue
                        it["owner"] = own
                        it.setdefault("warn_types", [])
                        if "party conflict" not in it["warn_types"]:
                            it["warn_types"].append("party conflict")
                        it["severity"] = next(t for t in WARN_ORDER if t in it["warn_types"])
                        key = "Ring1" if slot == "Ring2" else slot
                        rest = {k: x for k, x in st["items"].items() if k != slot}
                        used = {x["sid"] for x in st["items"].values()}
                        ranked = sorted(((reg["total"](x, key, a), x) for x in reg["scored"] if x not in used),
                                        key=lambda t: -(t[0] or -99))
                        for t_, x in ranked:
                            if t_ is None or t_ <= 0:
                                break
                            if not blocked_for(x, cid, owners) and slot_ok(x, slot, rest, items):
                                it["party_alt"] = alt_info(x, cid, universe, warning_text, how_text,
                                                           BP.CHARACTERS[cid]["research"], a) if warning_text else \
                                    {"sid": x, "name": universe[x]["name"]}
                                break
            for act, sl in bo["best"].items():
                a = int(act)
                for slot, v in sl.items():
                    if not v.get("best") or not blocked_for(v["best"], cid, owners):
                        continue
                    key = "Ring1" if slot == "Ring2" else slot
                    ranked = sorted(((reg["total"](x, key, a), x) for x in reg["scored"]), key=lambda t: -(t[0] or -99))
                    taken = {sl[o]["best"] for o in sl if o != slot and sl[o].get("best")}
                    for t_, x in ranked:
                        if t_ is None or t_ <= 0:
                            break
                        if x not in taken and not blocked_for(x, cid, owners):
                            v["party"] = x
                            break


# ---------------------------------------------------------------- sets
_TRAITS = {}


def traits(rec):
    """Equip-relevant facts of one item (cached): two-handed, light, hand crossbow, shield, body armour,
    needs an empty off hand, works only without armour / shield."""
    sid = rec["stats_id"]
    if sid in _TRAITS:
        return _TRAITS[sid]
    w = rec.get("weapon")
    arm = rec.get("armour") or {}
    texts = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
    tr = {"weapon": bool(w), "two": False, "light": False, "handxbow": False,
          "shield": bool(arm.get("shield")), "armour": rec["slot"] == "Breast" and bool(arm.get("category")),
          "empty_off": bool(re.search(r"off-hand is empty|nothing in your free hand|only holding one weapon", texts)),
          "no_armour": bool(re.search(r"not wearing armour", texts)),
          "no_shield": bool(re.search(r"(?:not|or) holding a shield", texts))}
    if w:
        modes, props, _r = weapon_modes(rec)
        tr["two"] = "Twohanded" in props or ("melee2h" in modes and "Versatile" not in props and
                                             rec["slot"] == "Melee Main Weapon")
        tr["light"] = "Light" in props
        tr["handxbow"] = "handxbow" in modes
    _TRAITS[sid] = tr
    return tr


def slot_ok(sid, slot, chosen, items):
    """Can this item go into this slot next to the items already chosen? (one set = one character's gear)"""
    other = {k: items[v["sid"]] for k, v in chosen.items() if k != slot}
    if path_conflict(sid, [v["sid"] for v in chosen.values()]):
        return False          # e.g. a Shar-path and a Selune-path reward
    me = traits(items[sid])
    main, off = other.get("MainHand"), other.get("OffHand")
    if slot == "OffHand" and main:
        tm = traits(main)
        if tm["two"] or tm["empty_off"]:
            return False
        if me["weapon"] and not (tm["light"] and me["light"]):
            return False      # two-weapon fighting needs two light weapons (no Dual Wielder feat modelled)
    if slot == "MainHand" and off:
        to = traits(off)
        if me["two"] or me["empty_off"]:
            return False
        if to["weapon"] and not (me["light"] and to["light"]):
            return False
    if slot == "RangedOff" and not me["handxbow"]:
        return False          # only hand crossbows can be dual-wielded as ranged weapons
    if slot == "RangedOff" and other.get("Ranged") and not traits(other["Ranged"])["handxbow"]:
        return False
    if slot == "Ranged" and other.get("RangedOff") and not me["handxbow"]:
        return False
    # "+2 AC while not wearing armour or holding a shield" next to armour / a shield
    if me["no_armour"] and (any(traits(r)["armour"] for r in other.values()) or
                            me["no_shield"] and any(traits(r)["shield"] for r in other.values())):
        return False
    for r in other.values():
        tr = traits(r)
        if tr["no_armour"] and (me["armour"] or tr["no_shield"] and me["shield"]):
            return False
    return True


def slot_for(rec, taken, b):
    s = rec["slot"]
    if s == "Ring":
        return "Ring1" if "Ring1" not in taken else ("Ring2" if "Ring2" not in taken else None)
    if s in ITEM_SLOT:
        return ITEM_SLOT[s] if ITEM_SLOT[s] not in taken else None
    if s == "Consumable":
        return "Elixir" if "Elixir" not in taken else None
    if s == "Melee Offhand Weapon":
        return "OffHand" if "OffHand" not in taken and b["offhand"] in ("shield", "any") else None
    modes, props, _r = weapon_modes(rec)
    if s == "Ranged Main Weapon":
        if "Ranged" not in taken:
            return "Ranged"
        if b.get("dual_ranged") and "handxbow" in modes and "RangedOff" not in taken:
            return "RangedOff"
        return None
    if "MainHand" not in taken:
        return "MainHand"
    if "OffHand" not in taken and "light" in modes and b["offhand"] in ("dual", "any") and "melee2h" not in modes - (
            {"melee2h"} if "Versatile" in props else set()):
        return "OffHand"
    return None


def build_seed_set(sd, cid, bid, act, scored, universe, items, total, slots_for, b):
    chosen, notes_ = {}, []
    core = 0
    order = [it for it in sd["items"] if not it["alt"]] + [it for it in sd["items"] if it["alt"]]
    seen = set()
    for it in order:
        sid = it["sid"]
        if sid in seen:
            continue
        if it["alt"] and it.get("alt_of") and any(v["sid"] == it["alt_of"] for v in chosen.values()):
            continue          # "A or B": B only stands in when A could not be used
        seen.add(sid)
        u = universe.get(sid)
        nm_ = (u or {}).get("name") or it["text"]
        if not u:
            notes_.append(f"{nm_}: not an equippable item in game data")
            continue
        if sid not in scored:
            notes_.append(f"{nm_}: dropped (this build does not use that slot)")
            continue
        s = scored[sid]
        if not s["usable"]:
            notes_.append(f"{nm_}: dropped ({s['why_not']})")
            continue
        if u["act"] > act:
            notes_.append(f"{nm_}: dropped (first obtainable in Act {u['act']})")
            continue
        if costs_origin(sid):
            notes_.append(f"{nm_}: dropped (costs an origin companion; the mod re-enables it when that happened)")
            continue
        if is_unusual(sid, cid):
            notes_.append(f"{nm_}: moved to the conditional alternative (Dark Urge campaign only)")
            continue
        slot = slot_for(items[sid], chosen, b)
        if slot is None or slot not in slots_for + ["Ring2"]:
            if not it["alt"]:
                notes_.append(f"{nm_}: slot already filled (alternative)")
            continue
        key = "Ring1" if slot == "Ring2" else slot
        if key in s["slots"] and any(c[0] == "weapon" and c[2] < 0 for c in s["slots"][key][1]):
            notes_.append(f"{nm_}: dropped (does not fit this build's weapon style)")
            continue
        if not slot_ok(sid, slot, chosen, items):
            notes_.append(f"{nm_}: dropped (cannot be equipped together with the set's other items)")
            continue
        chosen[slot] = {"sid": sid, "core": True, "alt": it["alt"]}
        core += 1
    main = chosen.get("MainHand")
    if main and "OffHand" in chosen:
        modes, props, _r = weapon_modes(items[main["sid"]])
        if "melee2h" in modes and "Versatile" not in props:
            off = chosen.pop("OffHand")
            notes_.append(f"{universe[off['sid']]['name']}: off hand needs a one-handed main weapon (moved to notes)")
    if core < 2:
        return None
    fill(chosen, act, scored, total, slots_for, items, b)
    name = sd["name"] if cid == sd["char"] else f"{sd['name']} ({BP.CHARACTERS[sd['char']]['name']} research)"
    return {"name": name, "origin": "research",
            "seed": f'{sd["file"]}:{sd["line"]}', "seed_key": f'{sd["char"]}:{sd["act"]}:{sd["idx"]}',
            "items": chosen, "validation": notes_, "adapted_from": None if cid == sd["char"] else sd["char"]}


def fill(chosen, act, scored, total, slots_for, items, b, exclude=()):
    used = {v["sid"] for v in chosen.values()} | set(exclude)
    main = chosen.get("MainHand")
    twoh = False
    if main:
        modes, props, _r = weapon_modes(items[main["sid"]])
        twoh = "melee2h" in modes and "Versatile" not in props
    for slot in slots_for + ["Ring2"]:
        if slot in chosen:
            continue
        if slot == "OffHand" and twoh:
            continue
        key = "Ring1" if slot == "Ring2" else slot
        ranked = sorted(((total(sid, key, act), sid) for sid in scored if sid not in used),
                        key=lambda x: -(x[0] or -99))
        for t_, sid in ranked:
            if t_ is None or t_ <= 0:
                break
            if not slot_ok(sid, slot, chosen, items):
                continue
            chosen[slot] = {"sid": sid, "core": False, "alt": False}
            used.add(sid)
            if slot == "MainHand":
                modes, props, _r = weapon_modes(items[sid])
                twoh = "melee2h" in modes and "Versatile" not in props
            break


def overlap(a, b):
    sa = {v["sid"] for v in a["items"].values()}
    sb = {v["sid"] for v in b["items"].values()}
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


THEME_NAMES = {
    "hunters_mark": "Hunter's Mark Focus", "sneak_attack": "Sneak Attack Focus", "crit": "Crit Fisher",
    "adv": "Always Advantage", "initiative": "First Strike", "stealth": "Shadow Step", "obscured": "Darkness Fighter",
    "throw": "Throwing Arsenal", "returning": "Returning Throws", "weapon_dmg": "Damage Riders",
    "weapon_atk": "Accuracy Stack", "spell_dc": "Spell DC Stack", "spell_atk": "Spell Attack Stack",
    "cantrip": "Cantrip Battery", "lightning_charge": "Lightning Charge Battery", "reverberation": "Reverberation Chain",
    "daze": "Daze Lock", "radiating_orb": "Radiating Orb Lockdown", "illuminated": "Light Bringer",
    "arcane_acuity": "Arcane Acuity Engine", "arcane_synergy": "Arcane Synergy Loop", "smite": "Smite Engine",
    "rage": "Rage Engine", "unarmed": "Iron Fist", "healer": "Healing Engine", "ac": "Iron Wall",
    "dmg_reduction": "Damage Soak", "concentration": "Unbroken Concentration", "frost": "Deep Freeze",
    "heat": "Heat Engine", "piercing_vuln": "Piercing Vulnerability", "kill_trigger": "Chain Kills",
    "dmg_fire": "Fire Focus", "dmg_lightning": "Lightning Focus", "dmg_thunder": "Thunder Focus",
    "dmg_radiant": "Radiant Focus", "dmg_cold": "Cold Focus", "weapon_spell": "Spellblade", "channel": "Channel Divinity",
    "bonus_enchant": "Hold and Smite", "manoeuvre": "Manoeuvre Master", "spell_slot": "Slot Battery",
    "saves": "Save Wall", "temp_hp": "Sustain", "crit_immune": "No Crits",
}
NEED_LABEL = {k: v.lower() for k, v in THEME_NAMES.items()}


def theme_set(need, act, scored, universe, items, total, slots_for, b):
    chosen, hooks = {}, []
    for slot in slots_for + ["Ring2"]:
        key = "Ring1" if slot == "Ring2" else slot
        cand = []
        slot_best = max([t_ for t_ in (total(sid, key, act) for sid in scored) if t_ is not None] or [0])
        for sid, s in scored.items():
            t_ = total(sid, key, act)
            if t_ is None or t_ <= 0 or key not in s["slots"] or t_ < 0.6 * slot_best:
                continue          # a hook must still be a good item for the slot
            if any(c[0] == "weapon" and c[2] < 0 for c in s["slots"][key][1]):
                continue          # a theme never overrides the build's weapon style
            comp = [c for c in s["slots"][key][1] if c[0] == need and c[2] >= 1.5]
            if comp:
                cand.append((t_ + 2 * sum(c[2] for c in comp), sid, comp[0][1]))
        cand.sort(key=lambda x: -x[0])
        for _v, sid, lab in cand:
            if all(v["sid"] != sid for v in chosen.values()) and slot_ok(sid, slot, chosen, items):
                chosen[slot] = {"sid": sid, "core": True, "alt": False}
                hooks.append((sid, lab))
                break
    main = chosen.get("MainHand")
    if main and "OffHand" in chosen:
        modes, props, _r = weapon_modes(items[main["sid"]])
        if "melee2h" in modes and "Versatile" not in props:
            chosen.pop("OffHand")
            hooks = [h for h in hooks if any(v["sid"] == h[0] for v in chosen.values())]
    if len(hooks) < 3:
        return None
    fill(chosen, act, scored, total, slots_for, items, b)
    return {"name": THEME_NAMES[need], "origin": "generated", "theme": need, "seed": None, "seed_key": None,
            "items": chosen, "validation": [], "adapted_from": None,
            "auto_why": f"{len(hooks)} pieces feed {NEED_LABEL.get(need, need)}: " +
                        "; ".join(f"{universe[s]['name']} ({lab})" for s, lab in hooks[:5]) +
                        f". The other slots hold the highest-scoring Act {act} items for this build."}


def auto_sets(bid, act, scored, universe, items, total, slots_for, sc, existing):
    """Generated sets when the research has fewer than 3 for this build and act: the best-scored loadout, then
    theme sets around the build's strongest needs (needs weight >= 1.5, 3+ hooks that are good items for their
    slot). A theme set is kept only when its total score reaches 85% of the best-scored loadout (weak themes are
    dropped, so a build can have fewer than 3 sets). The old "Alternative loadout" (second-best everywhere) is gone:
    per-slot fallbacks (conditions) and party alternatives (unique items) replace it."""
    b = BP.BUILDS[bid]
    cands = []
    for need, w in sorted(b["needs"].items(), key=lambda x: -x[1]):
        if w >= 1.5 and need in THEME_NAMES:
            st = theme_set(need, act, scored, universe, items, total, slots_for, b)
            if st:
                cands.append(st)
    top = {}
    fill(top, act, scored, total, slots_for, items, b)
    best_set = {"name": "Best scored loadout", "origin": "generated", "theme": "top", "seed": None,
                "seed_key": None, "items": top, "validation": [], "adapted_from": None,
                "auto_why": f"The highest-scoring usable item in every slot for Act {act} (how well it fits this "
                            f"build, plus community favourites); a safe default when no other set fits your "
                            f"playthrough."}

    def set_score(st):
        return sum(total(v["sid"], "Ring1" if k == "Ring2" else k, act) or 0 for k, v in st["items"].items())
    floor = 0.85 * set_score(best_set)
    cands = [best_set] + sorted((st for st in cands if set_score(st) >= floor), key=lambda st: -set_score(st))
    out = []
    for limit in (0.75, 0.85):          # never a near-copy of another set
        for st in cands:
            if len(existing) + len(out) >= 3:
                return out
            if st in out:
                continue
            if not any(overlap(st, o) > limit for o in existing + out):
                out.append(st)
    return out


# An earlier-act ("only if owned") main pick is kept only when it beats the best item obtainable in the act by more
# than the smallest unit of community evidence: one research-set mention (ROLE_W["set"] = 3 points), or 20% of its
# total (3 points = 21% of the median best-pick total 14.2). Data (round 5): 525 earlier-act main picks, median gap
# 4.4 points; this rule swaps 41% of them. See SETS_AUDIT.md Round 5.
OWNED_GAP = 0.2
OWNED_GAP_POINTS = ROLE_W["set"]


def is_unusual(sid, cid):
    """A campaign condition that is unusual for this character: Dark-Urge-only items for the other six origins
    (most campaigns have no Dark Urge). Companion-quest rewards (origin:X) are a normal party condition and
    stay main picks with a fallback."""
    return "durge" in COND.get(sid, ()) and cid != "darkurge"


GAPS = []           # (relative gap, owned total, obtainable total, ...) of every earlier-act main pick (audit)


def prefer_obtainable(st, act, total):
    """Swap an "only if owned" (earlier-act) main pick for its obtainable fallback when the fallback's total is
    within OWNED_GAP of it. -> {slot: earlier-act sid now kept as the alternative}."""
    out = {}
    for slot, v in list(st["items"].items()):
        a0, a1 = ACTS.get(v["sid"], (1, 3))
        fb = (st.get("fallback") or {}).get(slot)
        if a1 >= act or not fb:
            continue
        key = "Ring1" if slot == "Ring2" else slot
        t_own = total(v["sid"], key, act) or 0
        t_fb = total(fb, key, act, owned=False) or 0
        GAPS.append(((t_own - t_fb) / t_own if t_own > 0 else 0, t_own, t_fb, v["sid"], fb, act))
        if t_own <= 0 or (t_own - t_fb) / t_own <= OWNED_GAP or t_own - t_fb <= OWNED_GAP_POINTS:
            out[slot] = v["sid"]
            st["items"][slot] = {"sid": fb, "core": v.get("core", False), "alt": False}
    return out


def unusual_alternatives(st, cid, act, scored, total, items):
    """Per slot: the best item with an unusual campaign condition (is_unusual) that would beat the set's item,
    as a conditional alternative ("in a Dark Urge campaign: X") - the mirror image of the fallback."""
    out = {}
    if cid == "darkurge":
        return out
    for slot, v in st["items"].items():
        key = "Ring1" if slot == "Ring2" else slot
        cur = total(v["sid"], key, act) or 0
        rest = {k: x for k, x in st["items"].items() if k != slot}
        used = {x["sid"] for x in st["items"].values()}
        best = None
        for sid in scored:
            if sid in used or not is_unusual(sid, cid):
                continue
            t_ = total(sid, key, act, unusual=True)
            if t_ is not None and t_ > cur and (best is None or t_ > best[0]) and slot_ok(sid, slot, rest, items):
                best = (t_, sid)
        if best:
            out[slot] = best[1]
    return out


WARN_ORDER = ["story lock", "theft-kill", "missable", "party conflict", "tip"]


def warn_meta(sid, cid, text, u):
    """-> (severity, [types]) for a set item's note: story lock (a story path, Dark Urge campaign, a companion that
    must be in the party, a companion lost), theft-kill (stealing or killing / pickpocketing someone), missable
    (can be lost by moving on or by timing), tip (anything else). "party conflict" is added by the party pass."""
    types = []
    codes = cond_relevant(sid, cid)
    if any(c.startswith(("path:", "!path:", "party:", "costs:")) or c == "durge" for c in codes):
        types.append("story lock")
    srcs = u.get("sources") or []
    fl = set(source_flags(srcs[0])) if srcs else set()
    low = (text or "").lower()
    if fl & {"theft", "kill or pickpocket a neutral NPC"} or re.search(r"\b(?:steal\w*|theft|crime|pickpocket\w*|"
                                                                        r"kill(?:ing|s)? (?:\w+ ){0,3}(?:neutral|"
                                                                        r"friendly)|murder)\b", low):
        types.append("theft-kill")
    if (u.get("notes") or {}).get("missable") or "missable" in low or any(c.startswith("timing:") for c in
                                                                           COND.get(sid, ())):
        types.append("missable")
    if text and not types:
        types.append("tip")
    sev = next((t for t in WARN_ORDER if t in types), None)
    return sev, types


def alt_info(sid, cid, universe, warning_text, how_text, char_file, act):
    """Everything a set item shows, for an alternative (fallback / party / earlier-act / conditional)."""
    if not sid:
        return None
    u = universe[sid]
    w = warning_text(sid, char_file)
    sev, types = warn_meta(sid, cid, w, u)
    return {"sid": sid, "name": u["name"], "act": u["act"], "last_act": u["last_act"],
            "owned_only": u["last_act"] < act, "how": how_text(sid, char_file), "warning": w,
            "severity": sev, "warn_types": types, "cond": cond_relevant(sid, cid),
            "best_source": best_source_of(u)}


def best_source_of(u):
    if not u["sources"]:
        return None
    s0 = u["sources"][0]
    return ({k: s0.get(k) for k in ("kind", "level", "region", "position", "requires")}
            | {"holder": (s0.get("holder") or {}).get("name"), "container": (s0.get("container") or {}).get("name")})


def fallbacks(st, cid, act, scored, total, items):
    """For every set item with a campaign / party / path condition that matters for this character: the best
    unconditioned item for that slot that fits the rest of the set (Lua fb). The mod hides closed-path items live
    and swaps in the fallback; the data keeps both (test saves spawn closed-path items anyway)."""
    out = {}
    for slot, v in st["items"].items():
        if not cond_relevant(v["sid"], cid) and ACTS.get(v["sid"], (1, 3))[1] >= act:
            continue
        key = "Ring1" if slot == "Ring2" else slot
        rest = {k: x for k, x in st["items"].items() if k != slot}
        used = {x["sid"] for x in st["items"].values()}
        # candidates: obtainable in this act (no owned-only), no condition or only "lost on path x" ones
        # (obtainable while that path is not taken), never unobtainable / companion-cost items. Best total first;
        # when no candidate has a positive total, the best game-data fit still gives the slot a fallback.
        cands = []
        for sid in scored:
            if sid in used or not all(c.startswith("!path:") for c in cond_relevant(sid, cid)):
                continue
            t_ = total(sid, key, act, owned=False)
            if t_ is None:
                s_ = scored[sid]
                a0, a1 = ACTS.get(sid, (9, 0))
                if not (s_["usable"] and key in s_["slots"] and a0 <= act <= a1) or costs_origin(sid) or                         "unobtainable" in COND.get(sid, ()):
                    continue
                if any(c[0] == "weapon" and c[2] < 0 for c in s_["slots"][key][1]):
                    continue
                cands.append((0, s_["slots"][key][0] + 0.01 * min(len(UNIVERSE[sid]["sources"]), 3), sid))
            else:
                cands.append((1, t_, sid))
        for _k, _v, sid in sorted(cands, key=lambda x: (-x[0], -x[1])):
            if slot_ok(sid, slot, rest, items):
                out[slot] = sid
                break
        else:
            out[slot] = None      # nothing else obtainable for this slot in this act: the fallback is an empty slot
    return out


def finish_set(st, cid, universe, warning_text, how_text, char_file):
    why = None
    if st.get("seed_key") and set_notes:
        why = set_notes.WHY.get(st["seed_key"])
    if not why and st.get("seed_key"):
        core = [universe[v["sid"]]["name"] for v in st["items"].values() if v["core"]]
        why = "Research set built around " + ", ".join(core[:5]) + "."
    st["why"] = clean_text(why or st.get("auto_why", ""))
    items_out = {}
    warns = []
    for slot in SLOT_ORDER:
        v = st["items"].get(slot)
        if not v:
            continue
        sid = v["sid"]
        u = universe[sid]
        w = warning_text(sid, char_file)
        sev, types = warn_meta(sid, cid, w, u)
        has_fb = slot in (st.get("fallback") or {})
        fb = (st.get("fallback") or {}).get(slot)
        ai = lambda x: alt_info(x, cid, universe, warning_text, how_text, char_file, st["act"])  # noqa: E731
        items_out[slot] = {"sid": sid, "name": u["name"], "core": v["core"], "act": u["act"],
                           "how": how_text(sid, char_file), "warning": w, "severity": sev, "warn_types": types,
                           "cond": cond_relevant(sid, cid),
                           "owned_only": u["last_act"] < st["act"],
                           "fallback": ai(fb) if fb else (
                               {"sid": None, "empty": True, "name": f"leave it empty: no other {SLOT_LABEL[slot].lower()} "
                                                                    f"item can be obtained in Act {st['act']}"}
                               if has_fb else None),
                           # an earlier-act item that would be a little better if the party still has it
                           "owned_alt": ai((st.get("owned_alt") or {}).get(slot)),
                           # a Dark-Urge-only item that beats the pick in a Dark Urge campaign
                           "cond_alt": ai((st.get("cond_alt") or {}).get(slot)),
                           "best_source": best_source_of(u)}
        if w:
            warns.append(f"{u['name']}: {w}")
    st["items"] = items_out
    st["warnings"] = warns


# ---------------------------------------------------------------- writers
def write_sets_md(all_chars, item_info):
    L = ["# LootAdvisor - synergy sets (generated by tools/score_items.py)", "",
         "One block per origin character, build and act. **Core** items come from the research set (or the "
         "theme of a generated set); the other slots are filled with the highest-scoring item for that build "
         "and act. Warnings mark theft, killing neutral NPCs, story choices, missable or Dark-Urge-only items. "
         "Scores and their components are in `<character>.json`; the scoring formula is at the end.", ""]
    for cid, c in all_chars.items():
        L.append(f"## {c['name']} ({c['race']})")
        L.append("")
        for bid, bo in c["builds"].items():
            L.append(f"### {bo['name']}  `{bid}` - {bo['origin']}")
            if bo.get("note"):
                L.append(f"_{bo['note']}_")
            L.append("")
            for act in (1, 2, 3):
                for st in bo["sets"].get(act, []):
                    src = f"research {st['seed']}" if st.get("seed") else "generated"
                    if st.get("adapted_from"):
                        src += f" (adapted from {st['adapted_from']})"
                    L.append(f"#### Act {act} - {st['name']}  `{st['id']}`  ({src})")
                    L.append(f"**Why:** {st['why']}")
                    L.append("")
                    L.append("| Slot | Item | Act | How to get | Warning |")
                    L.append("|---|---|---|---|---|")
                    for slot, it in st["items"].items():
                        nm_ = ("**" + it["name"] + "**") if it["core"] else it["name"]
                        dm = item_info[it["sid"]]["display"]["acts"][act - 1] if it["sid"] in item_info else "m"
                        tag = {"l": "[list only] ", "t": "[marker on the trader] "}.get(dm, "")
                        L.append(f"| {SLOT_LABEL[slot]} | {nm_} | {it['act']} | {tag}{it['how'].replace('|', '/')} | "
                                 f"{it['warning'].replace('|', '/')} |")
                    pas = [f"{it['name']} is better on {', '.join(CHAR_NAMES.get(o, o) for o in it['owner'])}"
                           + (f" -> {it['party_alt']['name']}" if it.get("party_alt") else "")
                           for sl, it in st["items"].items() if it.get("owner")]
                    if pas:
                        L.append("")
                        L.append("Party (unique items / scarce materials): " + "; ".join(pas))
                    fbs = [f"{SLOT_LABEL[sl]} {it['name']} -> {it['fallback']['name']}"
                           for sl, it in st["items"].items() if it.get("fallback")]
                    if fbs:
                        L.append("")
                        L.append("If a condition is not met (campaign / origin / story path): " + "; ".join(fbs))
                    if st["validation"]:
                        L.append("")
                        L.append("Validation: " + "; ".join(st["validation"]))
                    L.append("")
    L.append("## Scoring formula")
    L.append("")
    L.append("```")
    L.append(__doc__.split("SCORING FORMULA")[1].strip())
    L.append("```")
    with open(os.path.join(SCORES_DIR, "SETS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def lua_str(s):
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return '"' + s + '"'


def write_lua(all_chars, item_info, universe, warning_text, how_text):
    """Compact Lua data for the mod. Items are an array; everything else refers to items by array index."""
    order = sorted(item_info)
    ix = {sid: k for k, sid in enumerate(order, 1)}
    out = ["-- LootAdvisor data (generated, do not edit).",
           "-- LA.Data.items[i] = { id=stats_id, n=name, r=rarity, s=item slot, a=first act, t={root templates},",
           "--   w=warning (theft / kill / story / missable / Dark Urge only; full text, shown in the F6 list),",
           "--   tw=the same warning in at most 3 tooltip lines (item tooltip), g=how to get,",
           "--   d=display per act (3 chars, act 1-3): m marker+frame+text, t marker on the trader, l list window only,",
           "--     - not obtainable in that act; cp={copies per act}; od={best drop chance per act} (list-only odds);",
           "--   o={party owners}: a unique / scarce-material item belongs to these characters; others show 'better on X',",
           "--   ot={characters tied exactly with the owner (same fit and same numeric value): any of them may take it},",
           "--   la=last act the item can be obtained in (a later act: 'only if owned', never a marker),",
           "--   c=campaign conditions, comma list: durge (Dark Urge campaign only), origin:<char> (needs that origin",
           "--     companion), path:<x> (needs story path x), !path:<x> (lost on path x)",
           "--   l={ {lv=level, k=source kind, x=,y=,z= world position, h=holder or container, rg=region}, ... } }",
           "-- LA.Data.chars[char].b[k] = { id=build id, n=name, o=origin (BuildAdvisor/community/campaign),",
           "--   cl={[class]=levels}, sc={[class]=subclass (game name; a missing class = any subclass)},",
           "--   why={[item index]=why text},",
           "--   a={ [act]={ best={[slot]={best index, runner-up index}}, sets={ {id,n,why,w={item indices with warnings},",
           "--   it={[slot]=item index}, fb={[slot]=item index to use when that slot's item condition is not met;",
           "--     0 = leave the slot empty, nothing else is obtainable in that act},",
           "--   pa={[slot]=item index to use because the set's item belongs to another character (o)},",
           "--   ow={slots whose item is no longer obtainable in this act: counts only if the party owns it, no marker;",
           "--   fb holds the obtainable replacement}, oa={[slot]=earlier-act item that is a little better if owned},",
           "--   ca={[slot]=Dark-Urge-only item that beats the pick in a Dark Urge campaign},",
           "--   sv={[slot]=note severity: story lock / theft-kill / missable / party conflict / tip}} },",
           "--   pb={[slot]=party-level best pick when the own best belongs to another character} } } }",
           "-- slots: MainHand OffHand Ranged RangedOff Helmet Cloak Breast Gloves Boots Amulet Ring1 Ring2 Elixir",
           "LA = LA or {}", "LA.Data = {", "  items = {"]
    for sid in order:
        ii = item_info[sid]
        locs = []
        for s in ii["sources"][:2]:
            p = s.get("position")
            parts = [f"lv={lua_str(s.get('level'))}", f"k={lua_str(s['kind'])}"]
            if p:
                parts += [f"x={p[0]:.1f}", f"y={p[1]:.1f}", f"z={p[2]:.1f}"]
            hc = s.get("holder") or s.get("container")
            if hc:
                parts.append(f"h={lua_str(short(hc, 40))}")
            if s.get("region"):
                parts.append(f"rg={lua_str(short(s['region'], 48))}")
            locs.append("{" + ",".join(parts) + "}")
        warn = PT.scrub(warning_text(sid, ""))
        how = PT.scrub(how_text(sid, ""))
        out.append(f"    {{id={lua_str(sid)},n={lua_str(ii['name'])},r={lua_str(ii['rarity'])},s={lua_str(ii['slot'])},"
                   f"a={ii['act']},la={ii['last_act']},t={{{','.join(lua_str(t) for t in ii['templates'][:2])}}},"
                   f"c={lua_str(','.join(ii.get('cond') or []))},"
                   f"d={lua_str(ii['display']['acts'])},"
                   f"cp={{{','.join(str(ii['display']['copies'].get(a, ii['display']['copies'].get(str(a), 0))) for a in (1, 2, 3))}}},"
                   f"od={{{','.join(str(ii['display']['odds'].get(a, ii['display']['odds'].get(str(a), 0))) for a in (1, 2, 3))}}},"
                   f"o={{{','.join(lua_str(x) for x in ii.get('owners') or [])}}},"
                   f"ot={{{','.join(lua_str(x) for x in ii.get('owner_exact_tie') or [])}}},"
                   f"w={lua_str(warn)},tw={lua_str(TW.shorten(sid, warn))},g={lua_str(short(how, 170))},"
                   f"l={{{','.join(locs)}}}}},")
    out.append("  },")
    out.append("  chars = {")
    for cid, c in all_chars.items():
        out.append(f"    {cid} = {{ n={lua_str(c['name'])}, b = {{")
        for bid, bo in c["builds"].items():
            used = set()
            acts = []
            for act in (1, 2, 3):
                bl = []
                for slot in SLOT_ORDER:
                    v = bo["best"][act].get(slot)
                    if not v or not v["best"]:
                        continue
                    ids = [x for x in (v["best"], v["runner"]) if x]
                    used |= set(ids)
                    bl.append(f"{slot}={{{','.join(str(ix[x]) for x in ids)}}}")
                sl = []
                for st in bo["sets"][act]:
                    it = ",".join(f"{k}={ix[v['sid']]}" for k, v in st["items"].items())
                    used |= {v["sid"] for v in st["items"].values()}
                    wl = ",".join(str(ix[v["sid"]]) for v in st["items"].values() if v["warning"])
                    fb = ",".join(f"{k}={ix[v['fallback']['sid']] if v['fallback'].get('sid') else 0}"
                                  for k, v in st["items"].items() if v.get("fallback"))
                    pa = ",".join(f"{k}={ix[v['party_alt']['sid']]}" for k, v in st["items"].items() if v.get("party_alt"))
                    used |= {v["party_alt"]["sid"] for v in st["items"].values() if v.get("party_alt")}
                    used |= {x["sid"] for v in st["items"].values() for x in (v.get("fallback"), v.get("owned_alt"),
                                                                              v.get("cond_alt")) if x and x.get("sid")}
                    oa = ",".join(f"{k}={ix[v['owned_alt']['sid']]}" for k, v in st["items"].items() if v.get("owned_alt"))
                    ca = ",".join(f"{k}={ix[v['cond_alt']['sid']]}" for k, v in st["items"].items() if v.get("cond_alt"))
                    sv = ",".join(f"{k}={lua_str(v['severity'])}" for k, v in st["items"].items() if v.get("severity"))
                    ow = ",".join(lua_str(k) for k, v in st["items"].items() if v.get("owned_only"))
                    sl.append(f"{{id={lua_str(st['id'])},n={lua_str(PT.set_name(st['name']))},"
                              f"why={lua_str(short(PT.set_why(st['why']), 200))},"
                              f"w={{{wl}}},it={{{it}}},fb={{{fb}}},pa={{{pa}}},ow={{{ow}}},oa={{{oa}}},ca={{{ca}}},"
                              f"sv={{{sv}}}}}")
                pb = []
                for slot in SLOT_ORDER:
                    v = bo["best"][act].get(slot)
                    if v and v.get("party"):
                        pb.append(f"{slot}={ix[v['party']]}")
                        used.add(v["party"])
                acts.append(f"[{act}]={{best={{{','.join(bl)}}},pb={{{','.join(pb)}}},sets={{{','.join(sl)}}}}}")
            why = ",".join(f"[{ix[s]}]={lua_str(short(PT.why_text(bo['items'][s]['why']), 220))}" for s in sorted(used)
                           if s in bo["items"] and bo["items"][s]["why"])
            cl = ",".join(f"{k}={v}" for k, v in bo["classes"].items())
            scl = ",".join(f"{k}={lua_str(v)}" for k, v in BP.SUBCLASSES.get(bid, {}).items())
            out.append(f"      {{id={lua_str(bid)},n={lua_str(bo['name'])},o={lua_str(bo['origin'])},"
                       f"cl={{{cl}}},sc={{{scl}}},"
                       f"why={{{why}}},a={{{','.join(acts)}}}}},")
        out.append("    } },")
    out.append("  },")
    out.append("}")
    os.makedirs(os.path.join(SCORES_DIR, "lua"), exist_ok=True)
    path = os.path.join(SCORES_DIR, "lua", "LootData.lua")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"LootData.lua: {os.path.getsize(path) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
