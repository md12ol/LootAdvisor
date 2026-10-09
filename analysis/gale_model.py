"""Gale build model (BG3 Patch 8). Run: python analysis/gale_model.py

Compares Gale builds at level 12 with Act 3 gear, and at levels 5 (end of Act 1), 8 (Act 2) and 10 (early Act 3).
Read from the game data at run time (data/cache/stats_resolved.json):
  - every spell's damage dice, damage type, school, save / attack roll, dart / beam count and upcast variant
    (Projectile_Fireball_6, Projectile_MagicMissile_6 ...);
  - every gear item's Spell Save DC / spell attack / AC boosts (item Boosts + its passives' and statuses' Boosts);
  - class features: Empowered Evocation = DamageBonus(INT mod) on every Evocation damage instance (each dart,
    beam and target); Destructive Wrath = Channel Divinity, maximises every Lightning/Thunder damage roll of one
    cast (status DESTRUCTIVE_WRATH, removed OnCastResolved); Heart of the Storm = Sorcerer level / 2 Lightning to
    enemies within 6 m; Elemental Affinity (Blue) = DamageBonus(CHA mod) on Lightning spells; Markoheshkir's
    Kereska's Favour = +proficiency bonus to one element and that element's two free item spells, each once per
    short rest (Chain Lightning 10d8 + Lightning Bolt 8d6, or Fireball 8d6, both Evocation, no slot);
    Ne'er Misser = 5-dart Magic Missile (3rd level, Evocation) once per short rest; Helldusk Gloves = Rays of Fire
    3 x 3d6 once per short rest; Quickened Spell costs 3 Sorcery Points.
Assumptions (not in the data): pack fight = 4 enemies, Fireball / Ice Storm / Cone of Cold / Circle of Death hit 3,
Lightning Bolt 2.5, Shatter / Thunderwave 2, Chain Lightning 4 (main target + 3 jumps); boss fight = 1 target.
Enemy AC / saves per act below. A day = 3 fights x 4 rounds with a short rest before each fight (3 short-rest
windows); "long day" = 5 fights. Damage bonuses are halved with the damage on a successful save. Every slot is
spent on damage (no buffs), so absolute numbers are a ceiling; the comparison between builds is the point.
Arcane Acuity from the Elixir of Battlemage's Power = +3 DC / spell attack (never drops below 3, game data:
SetStatusDuration(...,3,SetMinimum) each turn; one stack = +1)."""
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = json.load(open(os.path.join(ROOT, "data", "cache", "stats_resolved.json"), encoding="utf-8"))

# ------------------------------------------------------------------ game-data readers
def dice(expr):
    """'10d8' / '1d4+1' / '10d6+40' -> (average, maximum, dice average part)."""
    avg = mx = dav = 0.0
    for sign, term in re.findall(r"([+-]?)\s*([0-9]+d[0-9]+|[0-9]+)", expr):
        k = -1 if sign == "-" else 1
        if "d" in term:
            n, f = map(int, term.split("d"))
            avg += k * n * (f + 1) / 2; mx += k * n * f; dav += k * n * (f + 1) / 2
        else:
            avg += k * int(term); mx += k * int(term)
    return avg, mx, dav


def cantrip_dice(level, die):
    n = 1 if level < 5 else 2 if level < 10 else 3          # BG3 cantrips scale at 5 and 10
    return f"{n}d{die}"


def spell(sid, lvl=None):
    """Damage spell from the stats: returns dict(expr, type, school, roll, darts, level)."""
    base = S[sid]
    v = S.get(f"{sid}_{lvl}", base) if lvl and lvl > int(base.get("Level") or 0) else base
    txt = (v.get("SpellSuccess") or "") + ";" + (v.get("SpellProperties") or "")
    m = re.search(r"DealDamage\(([^,]+),\s*(\w+)", txt)
    expr, dtype = m.group(1), m.group(2)
    roll = v.get("SpellRoll") or base.get("SpellRoll") or ""
    kind = "save" if "SavingThrow" in roll else "attack" if "Attack(" in roll else "auto"
    half = "/2" in (v.get("SpellFail") or base.get("SpellFail") or "")
    return dict(expr=expr, type=dtype, school=base.get("SpellSchool") or "", kind=kind, half=half,
                darts=int(v.get("AmountOfTargets") or 1), level=int(base.get("Level") or 0), sid=sid)


def boosts_of(sid):
    v = S.get(sid, {})
    out = [v.get("Boosts") or "", v.get("DefaultBoosts") or ""]
    for p in (v.get("PassivesOnEquip") or "").split(";"):
        if p.strip() in S and not S[p.strip()].get("BoostConditions"):   # skip e.g. "+1 AC with the Defence style"
            out.append(S[p.strip()].get("Boosts") or "")
    for st in (v.get("StatusOnEquip") or "").split(";"):
        if st.strip() in S:
            out.append(S[st.strip()].get("Boosts") or "")
    return ";".join(out)


ITEM_IDS = {   # display name -> stats id (data/items_all)
    "Markoheshkir": "MAG_TheChromatic_Staff", "Staff of Spell Power": "MAG_OfSpellPower_Quarterstaff",
    "Melf's First Staff": "MAG_BasicEnchanted_Quarterstaff", "The Spellsparkler": "MAG_ChargedLightning_Quarterstaff",
    "Ketheric's Shield": "MAG_Ketheric_Shield", "Adamantine Shield": "MAG_MeleeDebuff_AttackDebuff1_OnDamage_Shield",
    "Hood of the Weave": "MAG_EndGameCaster_Hood", "Hat of Fire Acuity": "MAG_Fire_ArcaneAcuityOnFireDamage_Hat",
    "Fistbreaker Helm": "MAG_BarbMonk_Cloth_Hat_A_1_Late", "Birthright": "MAG_GleamingSorcery_Hat",
    "Robe of the Weave": "MAG_EndGameCaster_Robe", "Armour of Landfall": "MAG_Druid_Land_Magic_Leather_Armor",
    "Helldusk Armour": "MAG_Infernal_Plate_Armor", "The Protecty Sparkswall": "MAG_ChargedLightning_BonusAC_Robe",
    "Robe of Exquisite Focus": "MAG_OfArcanicAssault_Robe", "Plate Armour": "ARM_Plate_Body",
    "Potent Robe": "MAG_CharismaCaster_Robe",
    "Cloak of the Weave": "MAG_EndGameCaster_Cloak", "Cloak of Protection": "MAG_PHB_CloakOfProtection_Cloak",
    "Helldusk Gloves": "MAG_Infernal_Metal_Gloves", "Spellmight Gloves": "MAG_Arcanist_Gloves",
    "Gloves of Belligerent Skies": "MAG_Thunder_Reverberation_Gloves",
    "Amulet of the Devout": "MAG_OfTheDevout_Amulet", "Amulet of Greater Health": "MAG_ofGreaterHealth_Amulet",
    "Necklace of Elemental Augmentation": "MAG_ElementalGish_CantripBooster_Amulet",
    "Spellcrux Amulet": "MAG_Restoration_SpellSlotRestoration_Amulet",
    "Ring of Feywild Sparks": "MAG_OfFeywildSparks_Ring", "Callous Glow Ring": "MAG_Radiant_DamageBonusOnIlluminatedTarget_Ring",
    "Ring of Free Action": "MAG_PHB_OfFreeAction_Ring", "Ring of Protection": "MAG_PHB_Ring_Of_Protection",
    "Ne'er Misser": "MAG_MagicMissile_HandCrossbow", "Hellrider Longbow": "MAG_WYR_Hellrider_Longbow",
    "Helldusk Boots": "MAG_Infernal_Metal_Boots", "Armour of Persistence": "MAG_EndGame_Plate_Armor", "Rhapsody": "UNI_Cazador_RitualDagger",
}


def item_numbers(name):
    b = boosts_of(ITEM_IDS[name])
    dc = sum(int(x) for x in re.findall(r"SpellSaveDC\((\d+)\)", b))
    atk = re.findall(r"RollBonus\((?:RangedSpellAttack|Attack),\s*(\d+)\)", b)
    ac = sum(int(x) for x in re.findall(r"(?<![A-Za-z])AC\((\d+)\)", b))
    v = S[ITEM_IDS[name]]
    return dict(dc=dc, atk=int(atk[0]) if atk else 0, ac=ac, base_ac=int(v.get("ArmorClass") or 0),
                shield=v.get("Shield") == "Yes" or "Offhand" in (v.get("Slot") or ""),
                dexcap=v.get("Armor Class Ability"), con_adv="Advantage(SavingThrow, Constitution)" in b)


# ------------------------------------------------------------------ rules
SLOTS = {1: [2], 2: [3], 3: [4, 2], 4: [4, 3], 5: [4, 3, 2], 6: [4, 3, 3], 7: [4, 3, 3, 1], 8: [4, 3, 3, 2],
         9: [4, 3, 3, 3, 1], 10: [4, 3, 3, 3, 2], 11: [4, 3, 3, 3, 2, 1], 12: [4, 3, 3, 3, 2, 1]}
ENEMY = {5: dict(ac=14, save=2), 8: dict(ac=15, save=3), 10: dict(ac=16, save=4), 12: dict(ac=17, save=4)}
BOSS = {5: dict(ac=16, save=4), 8: dict(ac=17, save=5), 10: dict(ac=18, save=6), 12: dict(ac=19, save=7)}
PACK_TARGETS = {"Projectile_Fireball": 3, "Target_IceStorm": 3, "Zone_ConeOfCold": 3, "Target_CircleOfDeath": 3,
                "Zone_LightningBolt": 2.5, "Target_Shatter": 2, "Zone_Thunderwave": 2, "Projectile_ChainLightning": 4,
                "Projectile_MAG_Legendary_Chromatic_ChainLightning": 4, "Zone_MAG_Legendary_Chromatic_LightningBolt": 2.5,
                "Projectile_MAG_Legendary_Chromatic_Fireball": 3, "Target_MAG_Legendary_Chromatic_IceStorm": 3,
                "Zone_MAG_Legendary_Chromatic_ConeOfCold": 3}
# Sensitivity switches (both unverified in game):
DW_ALL_TARGETS = True    # Destructive Wrath maximises every target / chain jump of the cast (status lasts the whole cast)
DW_ITEM_SPELLS = True    # Destructive Wrath triggers on Markoheshkir's item spells ("not AnyEntityIsItem()")
prof_of = lambda lvl: 2 + (lvl - 1) // 4
mod_of = lambda score: (score - 10) // 2
clamp = lambda p: min(0.95, max(0.05, p))


def p_fail(dc, save):
    return clamp((dc - 1 - save) / 20)


def p_hit(atk, ac):
    return clamp((21 - (ac - atk)) / 20)


class Build:
    def __init__(self, key, name, level, cls, stats, cast, gear, element=None, feats=(), start=None, notes=""):
        self.key, self.name, self.level, self.cls, self.stats, self.cast = key, name, level, cls, stats, cast
        self.gear, self.element, self.feats, self.start, self.notes = gear, element, feats, start or list(cls)[0], notes
        g = [item_numbers(n) for n in gear if n in ITEM_IDS]
        self.mod = mod_of(stats[cast])
        self.prof = prof_of(level)
        acuity = 3 if "Elixir of Battlemage's Power" in gear else 0
        self.dc = 8 + self.prof + self.mod + sum(x["dc"] for x in g) + acuity
        self.atk = self.prof + self.mod + sum(x["atk"] for x in g) + acuity
        wiz, sor, cle, bsw = cls.get("Wizard", 0), cls.get("Sorcerer", 0), cls.get("Cleric", 0), cls.get("Bladesinger", 0)
        self.wiz = wiz + bsw
        self.sub = notes
        self.caster_level = self.wiz + sor + cle
        self.slots = list(SLOTS[self.caster_level])
        # spells known: wizard / sorcerer max spell level from their own class level
        self.max_known = max(min(6, (self.wiz + 1) // 2), min(6, (sor + 1) // 2), 1 if cle else 0)
        self.ee = "Evocation" in notes and self.wiz >= 10
        self.dw_per_window = 1 if cle >= 2 else 0
        self.dw_extra = 1 if (cle >= 2 and "Amulet of the Devout" in gear) else 0
        self.hots = sor // 2 if ("Storm" in notes and sor >= 6) else 0
        self.affinity = self.mod if ("Draconic" in notes and sor >= 6) else 0
        self.sp = 0 if sor < 2 else 2 + (sor - 2) + 0  # Sorc 2: 2 points, +1 per level 3..
        self.quicken = sor >= 2
        ar_points = sum(1 for l in (1, 3, 5, 7, 9, 11) if self.wiz >= l)
        self.extra = []                                  # extra slots per long rest
        if self.wiz:
            pts = ar_points
            for l in (5, 4, 3, 2, 1):
                while pts >= l and l <= len(self.slots):
                    self.extra.append(l); pts -= l
        if "Markoheshkir" in gear or "Staff of Spell Power" in gear:
            self.extra.append(len(self.slots))           # Arcane Battery: one free cast per long rest
        if "Spellcrux Amulet" in gear:
            self.extra.append(len(self.slots))
        if "Amulet of the Devout" in gear:
            self.extra.append(1)
        self.callous = 0.8 * 2 if "Callous Glow Ring" in gear else 0   # illuminated ~80% of the time
        self.sparks = 1 if "The Spellsparkler" in gear else 0
        self.spellmight = "Spellmight Gloves" in gear
        self.necklace = "Necklace of Elemental Augmentation" in gear
        self.psychic = "Psychic Spark" in gear
        ac_items = [x for x in g]
        body = [x for n, x in zip([n for n in gear if n in ITEM_IDS], g) if S[ITEM_IDS[n]].get("Slot") == "Breast"]
        dex = mod_of(stats["DEX"])
        if body:
            bx = body[0]
            base = bx["base_ac"] + (dex if bx["dexcap"] == "Dexterity" else 0)
        else:
            base = 10 + dex
        self.ac = base + sum(x["ac"] for x in ac_items) + sum(x["base_ac"] for x in ac_items if x["shield"])
        if bsw:
            self.ac += self.mod                           # Bladesong: +INT to AC
        con = 23 if "Amulet of Greater Health" in gear else stats["CON"]
        hd = {"Wizard": (6, 4), "Bladesinger": (6, 4), "Sorcerer": (6, 4), "Cleric": (8, 5)}
        first = hd[self.start][0]
        self.hp = first + sum(hd[c][1] * n for c, n in cls.items()) - hd[self.start][1] + mod_of(con) * level
        con_save = mod_of(con) + (self.prof if self.start == "Sorcerer" else 0) + (self.mod if bsw else 0)
        adv = any(x["con_adv"] for x in g) or "War Caster" in feats
        p = clamp((21 - (10 - con_save)) / 20)
        self.conc = 1 - (1 - p) ** 2 if adv else p

    # ---------------------------------------------- per-instance flat bonus
    def flat(self, sp, cantrip=False):
        f = 0
        if self.ee and sp["school"] == "Evocation":
            f += self.mod
        if self.element and sp["type"] == self.element:
            f += self.prof                                # Kereska's Favour: +proficiency to that element
        if self.affinity and sp["type"] == "Lightning":
            f += self.affinity
        if cantrip and self.necklace and sp["type"] in ("Fire", "Cold", "Lightning", "Acid", "Thunder"):
            f += self.mod
        if cantrip and "Potent Robe" in self.gear:
            f += mod_of(self.stats["CHA"])
        return f + self.callous + self.sparks

    def cast_value(self, sp, scen, targets=1.0, maxed=False):
        e = (BOSS if scen == "boss" else ENEMY)[self.level]
        avg, mx, dav = dice(sp["expr"])
        d = mx if maxed else avg
        f = self.flat(sp, sp["level"] == 0)
        n = sp["darts"]
        if sp["kind"] == "save":
            pf = p_fail(self.dc, e["save"])
            per = pf * (d + f) + (1 - pf) * ((d + f) / 2 if sp["half"] else 0)
            val = per * targets * n
        elif sp["kind"] == "attack":
            atk = self.atk
            extra = 0
            if self.spellmight:
                atk -= 5; extra = 4.5
            ph = p_hit(atk, e["ac"])
            crit = 0.05 * (dav if not maxed else mx)
            val = n * (ph * (d + f + extra) + crit)
        else:                                             # Magic Missile darts always hit
            val = n * (d + f)
        if maxed and not DW_ALL_TARGETS and targets * n > 1:
            plain = self.cast_value(sp, scen, targets, False)
            val = plain + (val - plain) / (targets * n)
        if self.hots and sp["type"] in ("Lightning", "Thunder") and sp["level"] >= 1:
            val += self.hots * (1 if scen == "pack" else 0)  # Heart of the Storm: ~1 enemy within 6 m in a pack
        return val


# ------------------------------------------------------------------ spell lists
WIZ = ["Projectile_MagicMissile", "Projectile_ScorchingRay", "Projectile_ChromaticOrb_Lightning",
       "Projectile_ChromaticOrb_Fire", "Projectile_ChromaticOrb_Thunder", "Projectile_WitchBolt", "Zone_Thunderwave",
       "Target_Shatter", "Projectile_Fireball", "Zone_LightningBolt", "Target_IceStorm", "Target_Blight",
       "Zone_ConeOfCold", "Projectile_ChainLightning", "Projectile_Disintegrate", "Target_CircleOfDeath"]
SORC = ["Projectile_MagicMissile", "Projectile_ScorchingRay", "Projectile_ChromaticOrb_Lightning",
        "Projectile_ChromaticOrb_Thunder", "Projectile_WitchBolt", "Target_Shatter", "Projectile_Fireball",
        "Zone_LightningBolt", "Target_IceStorm", "Zone_ConeOfCold", "Projectile_ChainLightning",
        "Projectile_Disintegrate"]


def known(b):
    lst = SORC if b.cls.get("Sorcerer") and not b.wiz else WIZ
    out = [s for s in lst if int(S[s].get("Level") or 0) <= b.max_known]
    if b.cls.get("Cleric", 0) >= 1 and "Zone_Thunderwave" not in out:
        out.append("Zone_Thunderwave")                 # Tempest domain spell, always prepared
    return out


def best_for_slot(b, L, scen, maxed):
    best = (0, None)
    for s in known(b):
        if int(S[s].get("Level")) > L:
            continue
        sp = spell(s, L)
        if maxed and sp["type"] not in ("Lightning", "Thunder"):
            continue
        t = PACK_TARGETS.get(s, 1) if scen == "pack" else 1
        v = b.cast_value(sp, scen, t, maxed)
        best = max(best, (v, s))
    return best


def item_casts(b, scen, windows):
    """Free item spells: (value, maxed value, name) per use."""
    out = []
    t = lambda sid: PACK_TARGETS.get(sid, 1) if scen == "pack" else 1
    def add(sid, uses, lvl=None):
        sp = spell(sid, lvl)
        lt = sp["type"] in ("Lightning", "Thunder")
        for _ in range(uses):
            mx = b.cast_value(sp, scen, t(sid), True) if (lt and DW_ITEM_SPELLS) else None
            out.append((b.cast_value(sp, scen, t(sid)), mx, sid))
    if "Markoheshkir" in b.gear and b.element == "Lightning":
        add("Projectile_MAG_Legendary_Chromatic_ChainLightning", windows)
        add("Zone_MAG_Legendary_Chromatic_LightningBolt", windows)
    if "Markoheshkir" in b.gear and b.element == "Fire":
        add("Projectile_MAG_Legendary_Chromatic_Fireball", windows)
    if "Markoheshkir" in b.gear and b.element == "Cold":
        add("Zone_MAG_Legendary_Chromatic_ConeOfCold", windows)
        add("Target_MAG_Legendary_Chromatic_IceStorm", windows)
    if "Helldusk Gloves" in b.gear:
        add("Projectile_MAG_FireRay", windows)
    if "Ne'er Misser" in b.gear:
        sp = spell("Projectile_MAG_MagicMissile_Shot")
        sp["darts"] += 1 if b.psychic else 0
        for _ in range(windows):
            out.append((b.cast_value(sp, scen), None, "Projectile_MAG_MagicMissile_Shot"))
    if "Melf's First Staff" in b.gear:
        add("Projectile_MAG_MelfsMagicArrow", 1)
    return out


def cantrip_value(b, scen):
    e = (BOSS if scen == "boss" else ENEMY)[b.level]
    if b.cls.get("Bladesinger"):
        # Extra Attack (Bladesinger 6): 2 x Rhapsody (1d4, +3 after kills, DEX 18) + Helldusk Gloves 1d6 fire
        n = 2 if b.wiz >= 6 else 1
        atk = b.prof + 4 + 1 + 3 + (1 if "Helldusk Gloves" in b.gear else 0)
        dmg = 2.5 + 4 + 1 + 3 + (3.5 if "Helldusk Gloves" in b.gear else 0)
        return n * (p_hit(atk, e["ac"]) * dmg + 0.05 * 2.5)
    sp = spell("Projectile_FireBolt")
    sp["expr"] = cantrip_dice(b.level, 10)
    return b.cast_value(sp, scen)


def day(b, scen, fights=3, rounds=4):
    windows = min(fights, 3)                           # BG3: two short rests per long rest -> 3 windows
    slots = [i + 1 for i, n in enumerate(b.slots) for _ in range(n)] + list(b.extra)
    if b.sp:                                            # Sorcery Points -> slots (best use for sustained)
        sp_left = b.sp
        for lvl, cost in ((5, 7), (3, 5), (2, 3), (1, 2)):
            while sp_left >= cost and lvl <= len(b.slots):
                slots.append(lvl); sp_left -= cost
    casts = []
    for L in slots:
        n, ns = best_for_slot(b, min(L, len(b.slots)), scen, False)
        m, ms = best_for_slot(b, min(L, len(b.slots)), scen, True) if b.dw_per_window else (0, None)
        casts.append((n, m if ms else None, ns))
    casts += item_casts(b, scen, windows)
    dw = b.dw_per_window * windows + b.dw_extra
    # assign Destructive Wrath to the casts with the biggest gain
    gains = sorted(range(len(casts)), key=lambda i: -((casts[i][1] or 0) - casts[i][0]))
    vals = [c[0] for c in casts]
    for i in gains[:dw]:
        if casts[i][1] and casts[i][1] > casts[i][0]:
            vals[i] = casts[i][1]
    vals.sort(reverse=True)
    R = fights * rounds
    can = cantrip_value(b, scen)
    used = [v for v in vals if v > can][:R]
    total = sum(used) + can * (R - len(used))
    return total / R


def nova(b, scen, rounds=1):
    """First fight of the day: the best `rounds` actions; a Sorcerer adds one Quickened slot spell per round
    (3 Sorcery Points each). Destructive Wrath: the charges available at the start of the day."""
    slots = [i + 1 for i, n in enumerate(b.slots) for _ in range(n)] + list(b.extra)
    dw = b.dw_per_window + b.dw_extra
    spells = []
    for L in slots:
        n, _ = best_for_slot(b, L, scen, False)
        m, ms = best_for_slot(b, L, scen, True) if dw else (0, None)
        spells.append((n, m if ms else None))
    items = [(v, m) for v, m, _ in item_casts(b, scen, 1)]
    key = lambda c: -max(c[0], c[1] or 0)
    actions = sorted(spells + items, key=key)[:rounds]
    if b.quicken:
        left = [c for c in sorted(spells, key=key)]
        for c in actions:
            if c in left:
                left.remove(c)
        actions += left[:min(rounds, b.sp // 3)]
    gains = sorted(((c[1] or c[0]) - c[0] for c in actions), reverse=True)
    return sum(c[0] for c in actions) + sum(gains[:dw])


def control(b):
    e, bo = ENEMY[b.level], BOSS[b.level]
    pf_pack, pf_boss = p_fail(b.dc, e["save"] - 1), p_fail(b.dc, bo["save"] - 1)   # WIS saves ~1 lower
    hold_targets = 2 if (b.quicken and b.cls.get("Sorcerer", 0) >= 3) else 1        # Twinned Hold Monster
    return pf_pack, pf_boss, hold_targets * pf_boss


# ------------------------------------------------------------------ builds
BASE_INT = dict(STR=8, DEX=14, CON=15, INT=15, WIS=10, CHA=8)     # point buy 27: 0+7+9+9+2+0
BASE_CHA = dict(STR=8, DEX=14, CON=15, INT=8, WIS=10, CHA=15)


def stats(base, plus2, plus1, asi):
    s = dict(base); s[plus2] += 2; s[plus1] += 1
    for k, v in asi:
        s[k] = min(20, s[k] + v)
    return s


W3 = ["Markoheshkir", "Ketheric's Shield", "Hood of the Weave", "Robe of the Weave", "Cloak of the Weave",
      "Helldusk Gloves", "Helldusk Boots", "Amulet of Greater Health", "Ring of Feywild Sparks", "Ring of Free Action",
      "Hellrider Longbow", "Elixir of Battlemage's Power"]                      # LootAdvisor evoker.a3.1
T3 = ["Markoheshkir", "Ketheric's Shield", "Hood of the Weave", "Armour of Persistence", "Cloak of the Weave",
      "Helldusk Gloves", "Helldusk Boots", "Amulet of Greater Health", "Ring of Feywild Sparks", "Callous Glow Ring",
      "Hellrider Longbow", "Elixir of Battlemage's Power"]                      # verdict gear (heavy armour via Tempest)
T3D = ["Markoheshkir", "Ketheric's Shield", "Hood of the Weave", "Armour of Landfall", "Cloak of the Weave",
       "Helldusk Gloves", "Helldusk Boots", "Amulet of the Devout", "Ring of Feywild Sparks", "Callous Glow Ring",
       "Ne'er Misser", "Elixir of Battlemage's Power"]                     # variant: Devout = 4th Destructive Wrath
S3 = ["Markoheshkir", "Ketheric's Shield", "Hood of the Weave", "Helldusk Armour", "Cloak of the Weave",
      "Helldusk Gloves", "Helldusk Boots", "Amulet of the Devout", "Ring of Feywild Sparks", "Ring of Free Action",
      "Hellrider Longbow", "Elixir of Battlemage's Power"]                      # LootAdvisor stormsorc.a3.1
F3 = ["Markoheshkir", "Ketheric's Shield", "Hat of Fire Acuity", "Robe of the Weave", "Cloak of the Weave",
      "Spellmight Gloves", "Helldusk Boots", "Amulet of Greater Health", "Ring of Feywild Sparks", "Callous Glow Ring",
      "Ne'er Misser", "Elixir of Battlemage's Power"]
B3 = ["Rhapsody", "Hood of the Weave", "Armour of Landfall", "Cloak of the Weave", "Helldusk Gloves",
      "Helldusk Boots", "Amulet of Greater Health", "Ring of Feywild Sparks", "Callous Glow Ring",
      "Elixir of Battlemage's Power"]
A2 = ["Melf's First Staff", "Ketheric's Shield", "Fistbreaker Helm", "The Protecty Sparkswall", "Cloak of Protection",
      "Spellcrux Amulet", "Callous Glow Ring", "Ring of Free Action", "Ne'er Misser", "Elixir of Battlemage's Power"]
T2 = ["Melf's First Staff", "Ketheric's Shield", "Fistbreaker Helm", "Plate Armour", "Cloak of Protection",
      "Spellcrux Amulet", "Callous Glow Ring", "Ring of Free Action", "Ne'er Misser", "Elixir of Battlemage's Power"]
SS2 = ["The Spellsparkler", "Ketheric's Shield", "Fistbreaker Helm", "Plate Armour", "Cloak of Protection",
       "Spellcrux Amulet", "Callous Glow Ring", "Ring of Free Action", "Ne'er Misser", "Elixir of Battlemage's Power"]
A1 = ["Melf's First Staff", "Adamantine Shield", "The Protecty Sparkswall", "Necklace of Elemental Augmentation",
      "Ring of Protection"]
T1p = ["Melf's First Staff", "Adamantine Shield", "Plate Armour", "Necklace of Elemental Augmentation",
       "Ring of Protection"]
SS1 = ["The Spellsparkler", "Adamantine Shield", "Plate Armour", "Necklace of Elemental Augmentation",
       "Ring of Protection"]


def builds(level):
    G = {5: (A1, A1, T1p, SS1), 8: (A2, A2, T2, SS2), 10: (W3, W3, T3, S3), 12: (W3, W3, T3, S3)}[level]
    gA, _, gT, gS = G
    asi_w = [("INT", 2)] if level >= 4 else []
    asi_w2 = asi_w + ([("INT", 1), ("CON", 1)] if level >= 8 else [])
    out = []
    out.append(Build("A", "Evocation Wizard 12 (BuildAdvisor 'evoker')", level, {"Wizard": level},
                     stats(BASE_INT, "INT", "CON", asi_w + ([("CON", 0)] if level >= 8 else []) + ([("INT", 2)] if level >= 12 else [])),
                     "INT", gA, "Lightning" if level >= 10 else None, ("War Caster",) if level >= 8 else (), notes="Evocation"))
    # B: Storm Sorcerer 10 / Tempest Cleric 2, order S1 C1 C2 S2..S10 (BuildAdvisor)
    sor = 1 if level < 4 else level - 2
    out.append(Build("B", "Storm Sorcerer 10 / Tempest Cleric 2 (BuildAdvisor 'stormsorc')", level,
                     {"Sorcerer": sor, "Cleric": min(2, level - 1)},
                     stats(BASE_CHA, "CHA", "CON", ([("CHA", 2)] if sor >= 4 else [])), "CHA", gS,
                     "Lightning" if level >= 10 else None, ("War Caster",) if sor >= 8 else (), start="Sorcerer", notes="Storm"))
    # C: Evocation Wizard 10 / Tempest Cleric 2, order W1-W5, C1-C2 (levels 6-7), W6-W10
    wiz = level if level <= 5 else level - min(2, level - 5)
    cle = 0 if level <= 5 else min(2, level - 5)
    out.append(Build("C", "Evocation Wizard 10 / Tempest Cleric 2 (Cleric at 6-7)", level,
                     {"Wizard": wiz, "Cleric": cle} if cle else {"Wizard": wiz},
                     stats(BASE_INT, "INT", "CON", ([("INT", 2)] if wiz >= 4 else []) + ([("INT", 1), ("CON", 1)] if wiz >= 8 else [])),
                     "INT", gT if cle else gA, "Lightning" if level >= 10 else None, (), start="Wizard", notes="Evocation"))
    if level == 5:
        out.append(Build("C'", "C with the Cleric levels first (C1 C2 W1-W3): plate armour from level 1", level,
                         {"Cleric": 2, "Wizard": 3}, stats(BASE_INT, "INT", "CON", [("INT", 2)]), "INT", gT, None, (),
                         start="Cleric", notes="Evocation"))
    if level >= 10:
        out.append(Build("A*", "Evocation Wizard 12 with the verdict's Act 3 gear", level,
                         {"Wizard": level}, stats(BASE_INT, "INT", "CON", asi_w + ([("INT", 2)] if level >= 12 else [])),
                         "INT", [("Robe of the Weave" if n == "Armour of Persistence" else n) for n in T3], "Lightning",
                         ("War Caster",), notes="Evocation"))
        out.append(Build("C-d", "C with Amulet of the Devout + Armour of Landfall + Ne'er Misser", level,
                         {"Wizard": wiz, "Cleric": cle}, stats(BASE_INT, "INT", "CON", ([("INT", 2)] if wiz >= 4 else []) + ([("INT", 1), ("CON", 1)] if wiz >= 8 else [])),
                         "INT", T3D, "Lightning", (), start="Wizard", notes="Evocation"))
    out.append(Build("E", "Fire Evoker 12 (community: Hat of Fire Acuity + Spellmight)", level, {"Wizard": level},
                     stats(BASE_INT, "INT", "CON", asi_w + ([("INT", 2)] if level >= 12 else [])), "INT",
                     F3 if level >= 10 else gA, "Fire" if level >= 10 else None, ("War Caster",) if level >= 8 else (), notes="Evocation"))
    out.append(Build("D", "Bladesinging Wizard 12 (community)", level, {"Bladesinger": level},
                     dict(STR=8, DEX=17, CON=14, INT=17, WIS=10, CHA=8) if level < 4 else dict(STR=8, DEX=18, CON=14, INT=19 if level >= 8 else 17, WIS=10, CHA=8),
                     "INT", B3 if level >= 10 else [n for n in gA if "Shield" not in n], None, (), notes="Bladesong"))
    out.append(Build("G", "Draconic (Blue) Sorcerer 12 (game data: Elemental Affinity)", level, {"Sorcerer": level},
                     stats(BASE_CHA, "CHA", "CON", ([("CHA", 2)] if level >= 4 else []) + ([("CHA", 1), ("CON", 1)] if level >= 8 else [])),
                     "CHA", ([n for n in gS if n != "Amulet of the Devout"] + ["Amulet of Greater Health"]) if level >= 10 else
                     [("The Spellsparkler" if n == "Melf's First Staff" else n) for n in gA],
                     "Lightning" if level >= 10 else None, (), start="Sorcerer", notes="Draconic"))
    return out


def report():
    print(__doc__.split("\n")[0])
    for level in (12, 10, 8, 5):
        print(f"\n=== level {level} (pack: AC {ENEMY[level]['ac']}, saves +{ENEMY[level]['save']};"
              f" boss: AC {BOSS[level]['ac']}, saves +{BOSS[level]['save']})")
        print(f"{'build':<62} {'DC':>3} {'atk':>4} {'AC':>3} {'HP':>4} {'conc':>5} | {'pack/rd':>7} {'long':>6} {'boss/rd':>7}"
              f" | {'R1 pack':>7} {'R1 boss':>7} {'fight':>6} | {'HP fail':>7} {'Hold':>5}")
        for b in builds(level):
            pack, pack5, boss = day(b, "pack"), day(b, "pack", fights=5), day(b, "boss")
            r1p, r1b, f4 = nova(b, "pack"), nova(b, "boss"), nova(b, "pack", 4)
            hp_fail, _, hold = control(b)
            print(f"{b.key:<3} {b.name[:58]:<58} {b.dc:>3} {b.atk:>+4} {b.ac:>3} {b.hp:>4} {b.conc:>5.2f} | {pack:>7.1f} {pack5:>6.1f}"
                  f" {boss:>7.1f} | {r1p:>7.1f} {r1b:>7.1f} {f4:>6.0f} | {hp_fail:>7.2f} {hold:>5.2f}")


def sensitivity():
    global DW_ALL_TARGETS, DW_ITEM_SPELLS
    print("\n=== level 12 sensitivity: what if Destructive Wrath works less well than the data suggests")
    print(f"{'case':<52} {'A pack':>7} {'B pack':>7} {'C pack':>7} {'C boss':>7} {'B R1':>6} {'C R1':>6}")
    for all_t, item in ((True, True), (False, True), (True, False), (False, False)):
        DW_ALL_TARGETS, DW_ITEM_SPELLS = all_t, item
        bs = {b.key: b for b in builds(12)}
        label = f"maxes {'all targets' if all_t else 'first target only'}, {'item spells too' if item else 'slot spells only'}"
        print(f"{label:<52} {day(bs['A'], 'pack'):>7.1f} {day(bs['B'], 'pack'):>7.1f} {day(bs['C'], 'pack'):>7.1f}"
              f" {day(bs['C'], 'boss'):>7.1f} {nova(bs['B'], 'pack'):>6.0f} {nova(bs['C'], 'pack'):>6.0f}")
    DW_ALL_TARGETS, DW_ITEM_SPELLS = True, True


if __name__ == "__main__":
    report()
    sensitivity()
