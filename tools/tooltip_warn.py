"""Tooltip-length item warnings for the in-game item tooltip (the advice row under the item description).

The full warning (theft, kills, story-path costs, missable items) stays in the F6 list and on the Sets page; the
tooltip gets a short form of at most MAX_LINES lines at the tooltip's text width that keeps every name, number, act
and kind of cost of the full text. Shortening is done by wording rules first (merging repeated "Lost if ..." notes,
shorter stock phrases); the few warnings still too long after the rules have a hand-written short form in SHORT,
which tests/run.py checks against the full text like every other short form.
"""
import re

MAX_LINES = 3
# Width of the tooltip's advice text column in "units" (one unit = an average lowercase letter of the tooltip font),
# measured on in-game captures (about 12 px per unit at 1080p, text column about 520 px) and rounded down.
LINE_UNITS = 43.0
_NARROW = set("iljI.,:;!|'")
_SEMI = set("ftr()[]/-")


def char_units(ch):
    if ch in _NARROW:
        return 0.45
    if ch in _SEMI:
        return 0.62
    if ch == " ":
        return 0.5
    if ch in "mwMW":
        return 1.45
    return 1.3 if ch.isupper() else 1.0


def wrap(text, width=LINE_UNITS):
    """Greedy word wrap as the game's TextBlock does it: the lines the text takes at the tooltip width."""
    lines, cur = [], ""
    for word in text.split():
        nxt = word if not cur else cur + " " + word
        if cur and sum(map(char_units, nxt)) > width:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines


def fits(text):
    return len(wrap(text)) <= MAX_LINES


# Hand-written short forms for warnings the rules cannot bring under MAX_LINES (stats id -> text). Each keeps every
# fact of the full warning; tests/run.py checks that.
SHORT = {
    "ARM_BootsOfSpeed": 'Also stealable from Thulla. Missable reward: give them to Sergeant Thrinn ("Find the Missing '
                        'Boots") and loot them back from her.',
    "GOB_DrowCommander_Amulet": "Theft if friendly goblins see you open the owned chest in Gut's room. Missable: only "
                                "one copy, wherever you reach first.",
    "GOB_DrowCommander_Leather_Armor": 'Kill her (raid the goblin leaders: tiefling side, "save the Grove" path) or '
                                       "pickpocket her (theft). If you side with the goblins she joins you.",
    "MAG_BG_Darkfire_Shortbow": "Story path: tiefling side; Dammon stays only if the tieflings survive Act I. Lost if "
                                "Isobel dies or Shadowheart kills the Nightsong.",
    "MAG_Bhaalist_Armor": "Become Unholy Assassin (\"Impress the Murder Tribunal\"): murder list victims / Dolor's hand "
                          "bag, kill Valeria (neutral hollyphant).",
    "MAG_CKM_SerpenScale_Armor": "Lost if Isobel dies or on the Shar path; Talli dies if Isobel is kidnapped. Bug: "
                                 "no full Dex with Medium Armour Master or Magic Initiate: Cleric.",
    "MAG_ChargedLightning_Longbow": "Missable: Rescue the Grand Duke reward, 1 of 3 (Joltshooter / Spellsparkler / "
                                    "Sparky Points); Florrick must survive the inn fire.",
    "MAG_ChargedLightning_Quarterstaff": "Missable: Rescue the Grand Duke reward, one of three (Joltshooter / Sparky "
                                         "Points / Spellsparkler): pick the staff; fails if Florrick dies.",
    "MAG_CharismaCaster_Robe": "Alfira must live: tiefling side (Act I), Moonrise rescue (Lakrissa/all); Durge: "
                               "knock her out, Quil gives it. Lost if Isobel dies or on the Shar path.",
    "MAG_Fire_ArcaneAcuityOnFireDamage_Hat": 'Only by killing the neutral Strange Ox (then no ally in Act III "Gather '
                                             'Your Allies"). Lost if Isobel dies or Shadowheart kills the Nightsong.',
    "MAG_Frost_GenerateFrostOnDamage_Gloves": "Missable: \"Avenge Glut's Circle\" reward (Underdark), one copy of two; "
                                              "a 3rd copy is in Sorcerous Sundries (Act III).",
    "MAG_Infernal_Metal_Boots": "Take them before Gortash's coronation, or after a deal with Gortash once Orin is dead; "
                                "else Gortash and the Steel Watch on that floor turn hostile.",
    "MAG_Infernal_Plate_Armor": "Only by killing Raphael (he wears it). Freeing Hope or stealing sets off the alarm: "
                                "Raphael, 6 Vengeful Cambions, Korrilla (maybe Yurgir) at the exit.",
    "MAG_Lesser_Infernal_Metal_Gloves": "Story path: tiefling side. Missable: only before the Shadowfell. Lost if "
                                        "Isobel dies or Shadowheart kills the Nightsong.",
    "MAG_Lesser_Infernal_Plate_Armor": "Story path: tiefling side. Missable: crafting only before the Shadowfell. Lost "
                                       "if Isobel dies or Shadowheart kills the Nightsong.",
    "MAG_Paladin_MomentumOnConcentration_Boots": "Kill Minthara (story path: tiefling side, goblin leaders killed); "
                                                 "guides say she has a copy later too (Act II, Moonrise).",
    "MAG_Selunite_Isobel_Robe": "Story path: friendly Isobel dead (any cause): pickpocket (theft), kill her or loot "
                                "her body. Not for a clean playthrough.",
    "MAG_StrongString_Longbow": "Opening the strongbox / taking the Iron Flask turns the Zhentarim hostile and loses "
                                "the special stock (missable). Act II fallback: Lann Tarv, Moonrise.",
    "MAG_TheThorns_Trident": "Win by pickpocketing Akabi's Djinni Ring (theft), DC 15 Performance or DC 20 Perception. "
                             "Missable: only one character enters the jungle.",
    "MAG_TheWoundSeeker_Greatsword": "Kill or pickpocket Yeva (neutral Flaming Fist, theft); missable, she leaves "
                                     "with you. Act II: Tadpoling Centre (Colony); disarm her, she stays an ally.",
    "MAG_Throwable_Pike": "Missable: buy from Grat before attacking the goblin camp (he closes shop on alert / raid). "
                          "Bug: returns to the original dropper's hand.",
    "MAG_Thunder_Reverberation_Gloves": "The Inquisitor's Chamber is a restricted githyanki area: claim business with "
                                        "the Inquisitor and loot unseen, or loot once the githyanki are hostile.",
    "PLA_WPN_SwordOfJustice": "Story choice: side with Karlach and kill Anders' group, or kill Karlach for the \"Hunt "
                              'the Devil" reward (loses a companion).',
}

_LOST_RX = re.compile(r"Lost if (.+?) - get it first\.\s*")
_RULES = [
    # stock phrases of the pipeline -> shorter, same facts
    (r"Taking (it|them) from (.+?) means killing or pickpocketing them \(a crime or a story cost\)\.",
     r"Kill or pickpocket \2 (a crime or a story cost)."),
    (r"(Theft\b.*?) \(stealing is a crime\)", r"\1"),
    (r"\bYou (?:must|have to) (\w)", lambda m: m.group(1).upper()),
    (r"Needs story path: side with the tieflings \(goblin leaders killed\)\.",
     "Story path: tiefling side (goblin leaders killed)."),
    (r"Needs story path: ", "Story path: "),
    (r"Companion quest reward: (\S+) quest\.", r"Reward of \1 quest."),
    (r"Isobel killed / Last Light falls", "Isobel dies / Last Light falls"),
]


def _merge_lost(text):
    """'Lost if A - get it first. Lost if B - get it first.' -> 'Get it first: lost if A, or if B.' (same facts)"""
    found = _LOST_RX.findall(text)
    if not found:
        return text
    rest = _LOST_RX.sub("", text).strip()
    shar = "Shadowheart kills the Nightsong (Shar path)"
    if shar in found and len(found) > 1:
        found.remove(shar)
        merged = "Lost if " + ", or if ".join(found) + ", or on the Shar path (Shadowheart kills the Nightsong)."
    else:
        merged = "Lost if " + ", or if ".join(found) + ": get it first."
    return (rest + " " + merged).strip() if rest else merged


def shorten(sid, full):
    """The tooltip form of an item's full warning ('' stays '')."""
    full = re.sub(r"\s+", " ", (full or "")).strip()
    if not full:
        return ""
    if SHORT.get(sid):
        return SHORT[sid]
    out = full
    for rx, rep in _RULES:
        out = re.sub(rx, rep, out)
    out = _merge_lost(out)
    return re.sub(r"\s+", " ", out).strip()
