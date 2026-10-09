"""Karlach build model (BG3 Patch 8 + HotFix 10): sustained / nova / AoE damage, control and defence at
level 5 (Act 1), 8 (Act 2) and 12 (Act 3 gear). Run:  python analysis/karlach_model.py

Every rule below was read from the game data (data/cache/stats_resolved.json, data/items_all/*.jsonl,
Public/*/Progressions/Progressions.lsx, Mods/Shared/Scripts/thoth/helpers/CommonConditions*.khn):

  Throw_Throw / Throw_FrenziedThrow  SpellRoll Attack(AttackType.RangedUnarmedAttack); damage DealDamage(ThrownWeapon)
                                 (taken here as weapon dice + enchantment + STR, like MainMeleeWeapon).
                                 Elemental Cleaver is added explicitly: DealDamage(1d6, <element>) per throw.
                                 Nyrulna: SpellProperties (hit OR miss) -> 3d4 Thunder to every character within 6 m
                                 of the target (MAG_THE_THORNS_EXPLOSION_DAMAGE_TECHNICAL, no save; allies and
                                 Karlach herself included when she is inside the 6 m).
  Throw_FrenziedThrow (Enraged Throw)  bonus action, NO cooldown (Frenzied Strike is OncePerTurn), needs SG_Rage;
                                 SpellSuccess ends with an unconditional ApplyStatus(PRONE,100,1) -> knocks Prone on hit.
  TavernBrawler                  IF(IsRangedUnarmedAttack()):RollBonus(Attack, StrengthModifier) and, on a throw hit,
                                 DealDamage(StrengthModifier). Feat gives +1 STR/DEX/CON (LightlyArmoredASI).
  Rage_Rage_Boosts(_2)           BoostConditions "not HasHeavyArmor(context.Source)": melee rage damage, EntityThrowDamage
                                 (2 / 3 from Barbarian 9) and B/P/S resistance. HasHeavyArmor = RingMail/ChainMail/
                                 Splint/Plate body armour -> Helldusk Armour (Plate) SWITCHES THESE OFF.
  RAGE_GIANT(_2)                 own EntityThrowDamage(2 / 3) on top (not armour-gated) -> "rage bonus doubled on throws".
  Shout_ElementalCleaver         no UseCosts (free); Giant 6. Throw_MightyImpel: bonus action, no cooldown, Giant 10,
                                 throws a Medium-or-smaller creature (2d4 heavy object + TB STR + EntityThrowDamage).
  Ring of Flinging / Gloves of Uninhibited Kushigo: EntityThrowDamage(1d4) each (certain on throws).
  Horns of the Berserker         +2 attack vs damaged targets; +2 Necrotic when IsUnarmedAttack() or IsWeaponAttack()
                                 (IsUnarmedAttack includes RangedUnarmedAttack -> certain on throws) while not at full HP.
  FastHands (Thief 3)            ActionResource(BonusActionPoint,1,0) -> a second Enraged Throw every turn.
  Helmet of Grit                 extra bonus action at <= 50% HP.
  Balduran's Giantslayer         TemplateStatus WeaponDamage(StrengthModifier) on the sword; Giant Form = action,
                                 once per short rest, CharacterWeaponDamage(1d6).
  GreatWeaponMaster_BonusDamage  RollBonus(MeleeWeaponAttack,-5); CharacterWeaponDamage(10) whenever the weapon is
                                 two-handed melee or versatile with nothing in the off hand (the -5 is melee-only).
  Karlach_Infernal_Fury          (her origin passive) CharacterWeaponDamage(1d4 Fire) while raging.

Two mechanics the data cannot settle (toggles, see SENSITIVITY):
  W  weapon-attached WeaponDamage statuses on a THROWN weapon (Nyrulna 1d6 Thunder, Giantslayer's +STR).
     The game adds explicit throw riders for Elemental Cleaver and Lightning Jabber, which hints they may not carry.
  C  character CharacterWeaponDamage boosts on throws (Caustic Band +2, Legacy +2, Helldusk Gloves 1d6,
     Infernal Fury 1d4; GWM +10 is a separate toggle G). Research (bg3.wiki) says the item riders do apply.
Simplifications: crits double the dice only; no advantage on throws (Reckless Attack only triggers from a melee
attack); target AC 16 / 19 / 22 for Act 1 / 2 / 3 headline; Enraged Throw adds STR once (its formula
"ThrownWeapon+StrengthModifier" may add it twice - toggle E).
"""
import itertools

W_ON, C_ON, G_ON, E_DOUBLE = True, True, False, False   # defaults (see docstring)


def p_hit(bonus, ac):
    need = max(2, min(20, ac - bonus))
    return (21 - need) / 20


def mod(score):
    return (score - 10) // 2


# ---------------------------------------------------------------- weapons (game data)
WEAPONS = {
    "Returning Pike":         dict(dice=5.5, ench=1, w=0.0, wdice=0.0, throw_x=0.0, blast=0.0, ret=True, shield=False),
    "Lightning Jabber":       dict(dice=3.5, ench=1, w=2.5, wdice=2.5, throw_x=2.5, blast=0.0, ret=False, shield=True),
    "Nyrulna":                dict(dice=3.5, ench=3, w=3.5, wdice=3.5, throw_x=0.0, blast=7.5, ret=True, shield=True),
    "Balduran's Giantslayer": dict(dice=7.0, ench=3, w="STR", wdice=0.0, throw_x=0.0, blast=0.0, ret=False, shield=False),
}

# ---------------------------------------------------------------- gear per act (same for every build)
GEAR = {
    1: dict(STR=None, flat_entity=0, entity_dice=5.0, c_flat=2, c_dice=0.0, atk=0, horns=0,
            note="Ring of Flinging + Gloves of Uninhibited Kushigo + Caustic Band, no elixir"),
    2: dict(STR=None, flat_entity=0, entity_dice=5.0, c_flat=2, c_dice=0.0, atk=0, horns=0,
            note="same + Lightning Jabber for Giants (Cleaver returns it)"),
    3: dict(STR=27, flat_entity=0, entity_dice=5.0, c_flat=2, c_dice=0.0, atk=2, horns=2,
            note="Elixir of Cloud Giant Strength, Nyrulna, Kushigo, Flinging + Caustic, Horns of the Berserker"),
}


def throw_damage(b, lvl, ac, wpn, extra_targets=0, enraged=False):
    """Expected damage of one weapon throw (hit, crit, Nyrulna blast)."""
    g, w = GEAR[lvl], WEAPONS[wpn]
    s = mod(g["STR"] or b["STR"][lvl])
    prof = 2 + (b["lvl"][lvl] - 1) // 4
    bonus = s + prof + w["ench"] + s + g["atk"]                     # STR + prof + ench + Tavern Brawler STR + gear
    ph = p_hit(bonus, ac)
    rage = 3 if b["barb"][lvl] >= 9 else 2
    entity = rage * (2 if b["giant"] else 1) + g["entity_dice"] + g["horns"]   # EntityThrowDamage + Horns
    cleaver = 3.5 if (b["giant"] and b["barb"][lvl] >= 6) else 0.0
    wdmg = (s if w["w"] == "STR" else w["w"]) if W_ON else 0.0
    wdmg += w["throw_x"] if not W_ON else 0.0                      # Jabber's explicit throw rider always counts
    cdmg = (g["c_flat"] + g["c_dice"] + 2.5) if C_ON else 0.0      # + Infernal Fury 1d4 while raging
    gwm = 10 if (G_ON and not w["shield"]) else 0.0
    hit = w["dice"] + w["ench"] + s + s + entity + cleaver + wdmg + cdmg + gwm
    if enraged and E_DOUBLE:
        hit += s
    crit_extra = w["dice"] + cleaver + (w["wdice"] if W_ON else 0) + g["entity_dice"] + (2.5 if C_ON else 0)
    blast = w["blast"] * (1 + extra_targets)
    return ph * hit + 0.05 * crit_extra + blast, ph


def impel_damage(b, lvl, ac):
    """Mighty Impel (Giant 10): throw a Medium-or-smaller creature at an enemy (heavy object 2d4)."""
    g = GEAR[lvl]
    s = mod(g["STR"] or b["STR"][lvl])
    prof = 2 + (b["lvl"][lvl] - 1) // 4
    ph = p_hit(s + prof + s + g["atk"], ac)
    rage = 3 if b["barb"][lvl] >= 9 else 2
    return ph * (5 + s + 2 * rage + g["entity_dice"] + g["horns"])


def melee_gwm(b, lvl, ac, wpn):
    """Great Weapon Master melee (Reckless Attack = advantage), main attacks + Frenzied Strike."""
    g, w = GEAR[lvl], WEAPONS[wpn]
    s = mod(g["STR"] or b["STR"][lvl])
    prof = 2 + (b["lvl"][lvl] - 1) // 4
    bonus = s + prof + w["ench"] - 5 + g["atk"]
    p = p_hit(bonus, ac); ph = 1 - (1 - p) ** 2; pc = 1 - 0.95 ** 2
    rage = 3 if b["barb"][lvl] >= 9 else 2
    dice = 7.0 if wpn == "Balduran's Giantslayer" else 4.5          # Nyrulna versatile 1d8 two-handed
    rider = s if wpn == "Balduran's Giantslayer" else 3.5            # Giantslayer +STR / Nyrulna 1d6 Thunder
    form = 3.5 if wpn == "Balduran's Giantslayer" else 0.0           # Giant Form 1d6 (one action per short rest)
    hit = dice + w["ench"] + s + rider + rage + 10 + g["c_flat"] + 2.5 + form + g["horns"]
    brutal = 4.5 if b["barb"][lvl] >= 9 else 0
    per = ph * hit + pc * (dice + 3.5 + 2.5 + brutal)
    return per, ph, pc


# ---------------------------------------------------------------- builds
# lvl / barb / STR per act (1 = level 5, 2 = level 8, 3 = level 12); throws = sustained throws per turn,
# r1 = round-1 throws (the bonus action goes to Rage), surge = extra throws once per short rest.
L = {1: 5, 2: 8, 3: 12}
BUILDS = {
    "A  Path of Giants 12 (BuildAdvisor 'giants'), Nyrulna + shield": dict(
        lvl=L, barb={1: 5, 2: 8, 3: 12}, giant=True, STR={1: 18, 2: 20, 3: 20},
        throws={1: 2, 2: 2, 3: 2}, r1={1: 2, 2: 2, 3: 2}, surge={1: 0, 2: 0, 3: 0}, impel={1: 0, 2: 0, 3: 1},
        wpn={1: "Returning Pike", 2: "Lightning Jabber", 3: "Nyrulna"}, hpl=dict(barb=12, fighter=0, rogue=0), relentless=True,
        style_ac=0, prone=0.0),
    "A2 Path of Giants 12, Balduran's Giantslayer thrown (Cleaver)": dict(
        lvl=L, barb={1: 5, 2: 8, 3: 12}, giant=True, STR={1: 18, 2: 20, 3: 20},
        throws={1: 2, 2: 2, 3: 2}, r1={1: 2, 2: 2, 3: 2}, surge={1: 0, 2: 0, 3: 0}, impel={1: 0, 2: 0, 3: 1},
        wpn={1: "Returning Pike", 2: "Lightning Jabber", 3: "Balduran's Giantslayer"}, hpl=dict(barb=12, fighter=0, rogue=0),
        relentless=True, style_ac=0, prone=0.0),
    "B  Throwzerker Berserker 10 / Fighter 2 (BuildAdvisor), Nyrulna + shield": dict(
        lvl=L, barb={1: 5, 2: 6, 3: 10}, giant=False, STR={1: 18, 2: 18, 3: 20},
        throws={1: 3, 2: 3, 3: 3}, r1={1: 2, 2: 2, 3: 2}, surge={1: 0, 2: 2, 3: 2}, impel={1: 0, 2: 0, 3: 0},
        wpn={1: "Returning Pike", 2: "Returning Pike", 3: "Nyrulna"}, hpl=dict(barb=10, fighter=2, rogue=0), relentless=False,
        style_ac=1, prone=1.0),
    "C  Berserker 9 / Thief 3 (two Enraged Throws), Nyrulna + shield": dict(
        lvl=L, barb={1: 5, 2: 5, 3: 9}, giant=False, STR={1: 18, 2: 18, 3: 18},
        throws={1: 3, 2: 4, 3: 4}, r1={1: 2, 2: 3, 3: 3}, surge={1: 0, 2: 0, 3: 0}, impel={1: 0, 2: 0, 3: 0},
        wpn={1: "Returning Pike", 2: "Returning Pike", 3: "Nyrulna"}, hpl=dict(barb=9, fighter=0, rogue=3), relentless=False,
        style_ac=0, prone=2.0),
    "D  Berserker 7 / Thief 3 / Fighter 2, Nyrulna + shield": dict(
        lvl=L, barb={1: 5, 2: 5, 3: 7}, giant=False, STR={1: 18, 2: 18, 3: 18},
        throws={1: 3, 2: 4, 3: 4}, r1={1: 2, 2: 3, 3: 3}, surge={1: 0, 2: 0, 3: 2}, impel={1: 0, 2: 0, 3: 0},
        wpn={1: "Returning Pike", 2: "Returning Pike", 3: "Nyrulna"}, hpl=dict(barb=7, fighter=2, rogue=3), relentless=False,
        style_ac=1, prone=2.0),
}
MELEE = {
    "E  GWM melee Berserker 10 / Fighter 2, Balduran's Giantslayer": ("B", "Balduran's Giantslayer"),
    "E2 GWM melee Berserker 10 / Fighter 2, Nyrulna two-handed": ("B", "Nyrulna"),
}


def hp(b):
    """d12 Barbarian start (12), then the fixed per-level values 7 / 6 / 5, CON 23 (+6) from Amulet of Greater Health."""
    h = b["hpl"]
    return 12 + 7 * (h["barb"] - 1) + 6 * h["fighter"] + 5 * h["rogue"] + 12 * 6


def defence(b, armour="Armour of Agility", shield=True):
    """Expected damage taken per enemy round in Act 3: 4 weapon attacks at +12 for 17 physical, one DC 18
    DEX-save spell for 30 (half on a save). Rage resistance halves physical unless the body armour is heavy."""
    if armour == "Armour of Agility":
        ac, dr, heavy, saves = 17 + 2, 0, False, 2
    elif armour == "Helldusk Armour":
        ac, dr, heavy, saves = 21, 3, True, 0
    else:  # Bonespike Garb, unarmoured: 10 + DEX 2 + CON 6
        ac, dr, heavy, saves = 18, 2, False, 0
    # Fighting Style Defence is AC(1) only while WearingArmor; Unarmoured Defence needs no body armour
    ac += (3 if shield else 0) + (b["style_ac"] if armour != "Bonespike Garb" else 0)
    p_atk = p_hit(12, ac)
    phys = max(0, 17 - dr) * (1 if heavy else 0.5)
    dmg = 4 * p_atk * phys
    p_save = 1 - (1 - p_hit(2 + saves, 18)) ** 2                    # Danger Sense: advantage on DEX saves
    dmg += max(0, 30 * (1 - p_save) + 15 * p_save - dr)
    life = hp(b) + (15 if b["relentless"] else 0) + (0 if armour != "Bonespike Garb" else 15)
    return ac, dmg, life / dmg


def table(ac_by_act=None, extra_targets=1):
    ac_by_act = ac_by_act or {1: 16, 2: 18, 3: 19}
    rows = {}
    for name, b in BUILDS.items():
        r = {}
        for act in (1, 2, 3):
            ac = ac_by_act[act]
            t, ph = throw_damage(b, act, ac, b["wpn"][act])
            te, _ = throw_damage(b, act, ac, b["wpn"][act], enraged=True)
            ta, _ = throw_damage(b, act, ac, b["wpn"][act], extra_targets=extra_targets)
            n = b["throws"][act]
            imp = 0.5 * impel_damage(b, act, ac) if b["impel"][act] else 0.0
            sus = t * min(n, 2) + te * max(0, n - 2) + imp
            r1 = t * min(b["r1"][act], 2) + te * max(0, b["r1"][act] - 2) + t * b["surge"][act]
            three = r1 + 2 * sus
            aoe = (ta - t) * n
            r[act] = dict(sus=sus, r1=r1, three=three, aoe=aoe, prone=b["prone"] * ph,
                          ph=ph)
        rows[name] = r
    for name, (bk, wpn) in MELEE.items():
        b = BUILDS[[k for k in BUILDS if k.startswith(bk)][0]]
        per, ph, pc = melee_gwm(b, 3, ac_by_act[3], wpn)
        sus = 3 * per                         # 2 attacks + Frenzied Strike (bonus action)
        r1 = 2 * per + 2 * per                # 2 attacks + Action Surge 2, bonus action = Rage
        rows[name] = {3: dict(sus=sus, r1=r1, three=r1 + 2 * sus, aoe=0.0, prone=0.0, ph=ph)}
    return rows


def show(title, rows, acts=(1, 2, 3)):
    print(f"\n=== {title}")
    hdr = "build".ljust(66) + "".join(f"| A{a} sus  r1   3rd  " for a in acts)
    print(hdr)
    for name, r in rows.items():
        line = name[:65].ljust(66)
        for a in acts:
            if a in r:
                x = r[a]
                line += f"| {x['sus']:6.1f} {x['r1']:5.1f} {x['three']:6.1f} "
            else:
                line += "|      -     -      - "
        print(line)


if __name__ == "__main__":
    rows = table()
    show("Damage per turn: sustained (sus), round 1 (r1), 3-round total (3rd); AC 16 / 18 / 19", rows)
    print("\n=== Act 3 extras (AC 19): AoE = Nyrulna blast on ONE more enemy per throw; prone = Enraged Throw hits/turn")
    for name, r in rows.items():
        x = r[3]
        print(f"{name[:65].ljust(66)} AoE +{x['aoe']:5.1f}/turn  prone {x['prone']:.2f}/turn  hit {x['ph']:.2f}")
    for ac in (16, 22):
        show(f"Act 3 at AC {ac}", {k: v for k, v in table({1: ac, 2: ac, 3: ac}).items()}, acts=(3,))
    print("\n=== Defence, Act 3 (expected damage taken per enemy round; 'rounds' = HP / that damage)")
    for name, b in BUILDS.items():
        for arm, sh in (("Armour of Agility", WEAPONS[b["wpn"][3]]["shield"]), ("Helldusk Armour", WEAPONS[b["wpn"][3]]["shield"]),
                        ("Bonespike Garb", WEAPONS[b["wpn"][3]]["shield"])):
            ac, dmg, rounds = defence(b, arm, sh)
            print(f"{name[:40].ljust(41)} {arm:<18} AC {ac:2d} HP {hp(b):3d}  takes {dmg:5.1f}/round  lasts {rounds:4.1f} rounds")
    print("\n=== Helldusk Armour damage cost (rage EntityThrowDamage off; Giants keeps RAGE_GIANT's own +3)")
    for name, b in BUILDS.items():
        base, _ = throw_damage(b, 3, 19, b["wpn"][3])
        lost = 3 * b["throws"][3]
        print(f"{name[:65].ljust(66)} -{lost} per turn of {base * b['throws'][3]:.0f}")
    print("\n=== SENSITIVITY (Act 3 sustained, AC 19)")
    for label, w, c, gw, e in (("W off (weapon statuses do not carry to throws)", False, True, False, False),
                               ("C off (CharacterWeaponDamage does not carry to throws)", True, False, False, False),
                               ("W and C off", False, False, False, False),
                               ("GWM +10 applies to throws (no shield)", True, True, True, False),
                               ("Enraged Throw adds STR twice", True, True, False, True)):
        W_ON, C_ON, G_ON, E_DOUBLE = w, c, gw, e
        r = table()
        print(" " + label + ": " + "  ".join(f"{k[:2].strip()} {v[3]['sus']:.0f}" for k, v in r.items()))
    W_ON, C_ON, G_ON, E_DOUBLE = True, True, False, False
    r = table()
    a, b_, d_ = (r[[k for k in r if k.startswith(x)][0]] for x in ("A ", "B ", "D "))
    print("\n=== Verdict D vs BuildAdvisor A (giants) / B (throwzerker), AC 16 / 18 / 19")
    for act in (1, 2, 3):
        print(f" Act {act}: sustained {100 * (d_[act]['sus'] / a[act]['sus'] - 1):+.0f}% / {100 * (d_[act]['sus'] / b_[act]['sus'] - 1):+.0f}%"
              f"   3-round {100 * (d_[act]['three'] / a[act]['three'] - 1):+.0f}% / {100 * (d_[act]['three'] / b_[act]['three'] - 1):+.0f}%")
