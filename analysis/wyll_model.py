"""Wyll build model (BG3 Patch 8). Same idea as analysis/astarion_dpr.py, wider: sustained and round-1 damage, AoE,
control (save DC) and defence at level 12 with Act 3 gear, plus Act 1 (level 5) and Act 2 (level 8) power curves.
Run: python analysis/wyll_model.py

Game data behind every number (Progressions.lsx of Shared / SharedDev / Gustav / GustavX, data/cache/stats_resolved.json,
data/items_all/*.jsonl, Levelmaps/LevelMapValues.lsx):
- Eldritch Blast 1d10 force per beam; beams = LevelMapValue(EldritchBlast): 1 (L1-4), 2 (L5-9), 3 (L10+).
- Agonising Blast (Warlock 2): +CHA per beam. Potent Robe: IF(IsCantrip()) DamageBonus(CHA) -> +CHA per beam again.
- Callous Glow Ring: +2 radiant per hit on an illuminated target. Spellmight Gloves (toggle): -5 spell attack, +1d8.
- Hex: +1d6 necrotic per hit, bonus action, concentration, costs a slot.
- Hexblade's Curse (Hexblade L1, GustavX): bonus action, OncePerShortRest, 10 turns; vs the target: DamageBonus(prof)
  and ReduceCriticalAttackThreshold(1), BoostContext OnAttack with no weapon-only condition -> Eldritch Blast too.
- The Dead Shot (Act 3 longbow): PassivesOnEquip ReduceCriticalAttackThreshold(1), unconditional -> worn in the ranged
  slot it lowers the crit threshold of every attack, spells included. Champion Improved Critical: same boost.
  Spell Sniper: IF(IsSpell() and IsSpellAttack()) ReduceCriticalAttackThreshold(1).
- Sorcerer: SP = Sorcerer level from Sorc 2. Metamagic at Sorc 2 = 2 of {Careful, Distant, Extended, Twinned};
  Quickened first appears in the Sorc 3 list; Quickened costs 3 SP. Create Sorcery Points uses SpellSlotsGroup, so pact
  slots convert too (slot level n -> n SP). Draconic: AC 13+DEX, +1 HP per Sorcerer level, Elemental Affinity (Sorc 6).
- Warlock: patron at Warlock 1 (Hexblade = Hex Warrior: medium armour, shields, martial weapons, bind a weapon -> CHA
  for weapon attacks); invocations at Warlock 2 (x2), 5, 7, 9, 12; Pact Boon at Warlock 3; Deepened Pact (Extra
  Attack for a pact weapon) is automatic at Warlock 5; Lifedrinker only in the Warlock 12 list; feats at 4, 8, 12.
- Paladin: Oath at Paladin 1, fighting style + Divine Smite at 2, Extra Attack 5, Aura of Protection 6, Relentless
  Avenger 7. Divine Smite (interrupt): 2d8 +1d8 per slot level above 1, max 6d8, not on killing blows.
  Vow of Enmity: bonus action, Channel Oath (1 per short rest), advantage vs the target.
  Multiclass into Paladin gives NO heavy armour proficiency (only a Paladin start does).
- GWM: -5/+10 with heavy weapons, bonus attack after a crit or kill. GWF: reroll 1-2 on weapon dice.
- Helldusk Gloves: RollBonus(Attack,1) (all attacks, spells too) and +1 DC, weapon attacks +1d6 fire.
  Duellist's Prerogative: +3 rapier, +1d4 necrotic, crit -1 and a once-per-turn bonus-action attack (empty off-hand).

Fight assumptions: 4 rounds per fight, 4 fights per long rest, 2 short rests (3 segments, so a short-rest feature such
as Hexblade's Curse or Vow of Enmity covers 3 of 4 fights). Casters keep their 4 best level-3+ slots (one Haste /
Hold Monster / Fireball / Counterspell per fight) and turn every other slot, and pact slots not used for Hex, into
Sorcery Points. Melee builds put every slot except one Hex per fight into smites (crits first, best slots first).
Target AC 19 in Act 3 (15 / 17 in Acts 1 / 2), 80% of targets illuminated, saves WIS +3 / DEX +2 in Act 3.
"""
from itertools import permutations

ROUNDS, FIGHTS, SEGMENTS = 4, 4, 3
SR_COVER = min(1.0, SEGMENTS / FIGHTS)
LIT = 0.8
KEEP_UTILITY = 4                                    # level-3+ slots a caster keeps for real spells per long rest

D = {"d4": 2.5, "d6": 3.5, "d8": 4.5, "d10": 5.5, "d12": 6.5}
GWF = {"d6": 4.1667, "d10": 6.3, "d12": 7.3333}


def prof(level):
    return 2 + (level - 1) // 4


def beams(level):
    return 1 if level < 5 else 2 if level < 10 else 3


def mod(score):
    return (score - 10) // 2


def p_crit(adv, thr=20):
    p = (21 - thr) / 20
    return 1 - (1 - p) ** 2 if adv else p


def p_hit(bonus, ac, adv, thr=20):
    need = max(2, min(20, ac - bonus))
    p = max((21 - need) / 20, (21 - thr) / 20)
    return 1 - (1 - p) ** 2 if adv else p


def attack(bonus, ac, adv, dice, flat, thr=20):
    """One attack: a hit deals dice + flat, a crit adds the dice once more."""
    return p_hit(bonus, ac, adv, thr) * (dice + flat) + p_crit(adv, thr) * dice


# ------------------------------------------------------------------ builds: class taken at each character level
W, S, P, F = "Warlock", "Sorcerer", "Paladin", "Fighter"
BUILDS = {
    "A": dict(name="BuildAdvisor 'sorlock': Fiend Warlock 2 / Draconic Sorcerer 10 (Warlock start, Spell Sniper)",
              kind="eb", seq=[W, W] + [S] * 10, patron="Fiend", feats={6: ("cha", 2), 10: ("sniper", 0)}),
    "B": dict(name="VERDICT: Hexblade Warlock 2 / Draconic Sorcerer 8 / Fighter 2 (Sorcerer start)", kind="eb",
              seq=[S, W, W, S, S, S, S, S, S, S, F, F], patron="Hexblade", feats={6: ("cha", 2), 10: ("cha", 1)}),
    "C": dict(name="Runner-up: Hexblade Warlock 2 / Draconic Sorcerer 10 (same plan, Sorcerer 9-10 at 11-12)",
              kind="eb", seq=[S, W, W] + [S] * 9, patron="Hexblade", feats={6: ("cha", 2), 10: ("cha", 1)}),
    "D": dict(name="Crit EB (community): Hexblade Warlock 2 / Draconic Sorcerer 6 / Champion Fighter 4", kind="eb",
              seq=[S, W, W, S, S, S, S, S, F, F, F, F], patron="Hexblade", champion=True,
              feats={6: ("cha", 2), 12: ("cha", 1)}),
    "E": dict(name="Pure Hexblade Warlock 12, Eldritch Blast + Quickspell Gloves", kind="eb",
              seq=[W] * 12, patron="Hexblade", feats={4: ("cha", 2), 8: ("cha", 1), 12: ("sniper", 0)}),
    "F": dict(name="BuildAdvisor 'lockadin': Vengeance Paladin 5 / Hexblade Warlock 7 (GWM)", kind="melee",
              seq=[P, W, P, P, P, P, W, W, W, W, W, W], patron="Hexblade", feats={5: ("gwm", 0), 9: ("cha", 2)}),
    "G": dict(name="Lockadin 5/7 with Duellist's Prerogative, CHA feats instead of GWM", kind="melee",
              seq=[P, W, P, P, P, P, W, W, W, W, W, W], patron="Hexblade", feats={5: ("cha", 2), 9: ("cha", 1)}),
    "H": dict(name="Vengeance Paladin 7 / Hexblade Warlock 5 (community Lockadin split)", kind="melee",
              seq=[P, W, P, P, P, P, P, P, W, W, W, W], patron="Hexblade", feats={5: ("gwm", 0), 11: ("cha", 2)}),
    "I": dict(name="CHA Sorcadin: Hexblade 1 / Vengeance Paladin 6 / Draconic Sorcerer 5", kind="melee",
              seq=[P, W, P, P, P, P, P, S, S, S, S, S], patron="Hexblade", feats={5: ("gwm", 0), 11: ("cha", 2)}),
    "J": dict(name="Pure Hexblade Warlock 12, Pact of the Blade + Lifedrinker", kind="melee",
              seq=[W] * 12, patron="Hexblade", feats={4: ("cha", 2), 8: ("gwm", 0), 12: ("cha", 1)}),
}

# ------------------------------------------------------------------ gear per act (data/items_all values)
CASTER_GEAR = {
    1: dict(desc="Melf's First Staff (+1/+1), Daredevil Gloves (+1 spell attack), The Protecty Sparkswall (+1 DC)",
            atk=2, dc=2, potent=False, callous=False, cha=0, crit=0, ac=2, gloves=["none"]),
    2: dict(desc="Incandescent Staff (+1 ranged spell attack), Daredevil Gloves (+1), Potent Robe, Callous Glow Ring, "
                 "Fistbreaker Helm (+1 DC)", atk=2, dc=1, potent=True, callous=True, cha=0, crit=0, ac=3,
            gloves=["none"]),
    3: dict(desc="Markoheshkir + Ketheric's Shield + Cloak of the Weave (+1/+1 each), Birthright (+2 CHA, max 22), "
                 "Potent Robe, Callous Glow Ring, The Dead Shot in the ranged slot (crit -1)",
            atk=3, dc=3, potent=True, callous=True, cha=2, crit=1, ac=3,
            gloves=["Spellmight Gloves", "Helldusk Gloves"]),
}
# weapon: (label, die, n dice, enchantment, extra weapon dice, heavy, duellist)
MELEE_GEAR = {
    1: dict(desc="Blood of Lathander (+3 mace), Caustic Band (+2 acid), Strange Conduit Ring (+1d4 psychic with Hex)",
            weapons=[("Blood of Lathander", "d6", 1, 3, 0.0, False, False)],
            atk=0, flat=2, extra=0.0, extra_conc=2.5, cha=0, crit=0, ac=20, dr=2),
    2: dict(desc="Halberd of Vigilance (+2, +1d4 force) or Blood of Lathander, Hellgloom Gloves (+1d4 fire), "
                 "Caustic Band, Strange Conduit Ring",
            weapons=[("Halberd of Vigilance", "d10", 1, 2, 2.5, True, False),
                     ("Blood of Lathander", "d6", 1, 3, 0.0, False, False)],
            atk=0, flat=2, extra=2.5, extra_conc=2.5, cha=0, crit=0, ac=18, dr=2),
    3: dict(desc="Balduran's Giantslayer (+3) or Duellist's Prerogative (+3, +1d4), Helldusk Gloves (+1 attack, +1d6 "
                 "fire), Birthright, Caustic Band, The Dead Shot in the ranged slot",
            weapons=[("Balduran's Giantslayer", "d6", 2, 3, 0.0, True, False),
                     ("Duellist's Prerogative", "d8", 1, 3, 2.5, False, True)],
            atk=1, flat=2, extra=3.5, extra_conc=0.0, cha=2, crit=1, ac=21, dr=3),
}
ACT_LEVEL = {1: 5, 2: 8, 3: 12}
ACT_AC = {1: 15, 2: 17, 3: 19}
ACT_SAVE = {1: 1, 2: 2, 3: 3}


# ------------------------------------------------------------------ character state at a level
def mc_slots(cl):
    t = {1: {1: 2}, 2: {1: 3}, 3: {1: 4, 2: 2}, 4: {1: 4, 2: 3}, 5: {1: 4, 2: 3, 3: 2}, 6: {1: 4, 2: 3, 3: 3},
         7: {1: 4, 2: 3, 3: 3, 4: 1}, 8: {1: 4, 2: 3, 3: 3, 4: 2}, 9: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
         10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2}, 11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1}}
    return dict(t.get(min(cl, 11), {}))


def paladin_slots(p):
    return {k: v for k, v in {1: 0 if p < 2 else 2 if p == 2 else 3 if p < 5 else 4,
                              2: 0 if p < 5 else 2 if p < 7 else 3, 3: 0 if p < 9 else 2}.items() if v}


def state(bid, level):
    b = BUILDS[bid]
    seq = b["seq"][:level]
    lv = {c: seq.count(c) for c in (W, S, P, F)}
    cha, sniper, gwm = 17, False, False                  # point buy 15 + racial +2
    for at, (feat, n) in b["feats"].items():
        if at <= level:
            cha += n if feat == "cha" else 0
            sniper |= feat == "sniper"
            gwm |= feat == "gwm"
    w = lv[W]
    pact = (0, 0) if w == 0 else ((1 if w == 1 else 2 if w < 11 else 3), min(5, (w + 1) // 2))
    if lv[S] and lv[P]:
        slots = mc_slots(lv[S] + lv[P] // 2)
    elif lv[S]:
        slots = mc_slots(lv[S])
    elif lv[P]:
        slots = paladin_slots(lv[P])
    else:
        slots = {}
    return dict(level=level, lv=lv, cha=cha, sniper=sniper, gwm=gwm, prof=prof(level), pact=pact, slots=slots,
                hexblade=b["patron"] == "Hexblade", champion=b.get("champion") and lv[F] >= 3,
                sp=lv[S] if lv[S] >= 2 else 0)


def cha_mod(st, g):
    """CHA modifier with gear: Birthright adds +2 up to 22; an uncapped +2 (Duke Ravengard's Longsword) goes on top."""
    cha = min(22, st["cha"] + g["cha"]) if g["cha"] else st["cha"]
    return mod(cha + g.get("cha_extra", 0))


# ------------------------------------------------------------------ Eldritch Blast builds
def quick_per_fight(st):
    """Quickened Eldritch Blasts per fight from the Sorcery Point budget (see the module docstring)."""
    if st["lv"][S] < 3:
        return 0.0
    pn, pl = st["pact"]
    spare_pact = max(0, pn * SEGMENTS - FIGHTS) * pl     # one Hex per fight from pact slots
    big = sorted([l for l, c in st["slots"].items() if l >= 3 for _ in range(c)], reverse=True)
    conv = sum(l * c for l, c in st["slots"].items() if l <= 2) + sum(big[KEEP_UTILITY:])
    return (st["sp"] + conv + spare_pact) / 3 / FIGHTS


def eb_fight(st, g, ac, adv, gloves, curse_ok, spellmight_on):
    cha = cha_mod(st, g)
    pb, n = st["prof"], beams(st["level"])
    atk = g["atk"] + (1 if gloves == "Helldusk Gloves" else 0) - (5 if spellmight_on else 0)
    bonus = pb + cha + atk
    agon = cha if st["lv"][W] >= 2 else 0
    quick = quick_per_fight(st) + (SEGMENTS / FIGHTS if g.get("quickspell") else 0)
    surge = SEGMENTS / FIGHTS if st["lv"][F] >= 2 else 0
    thr0 = 20 - st["sniper"] - g["crit"] - (1 if st["champion"] else 0)
    best = 0.0
    for buffs in [(), ("hex",), ("curse",), ("curse", "hex"), ("hex", "curse")]:
        if "curse" in buffs and not curse_ok:
            continue
        total, q_left, active = 0.0, quick, set()
        for r in range(ROUNDS):
            if r < len(buffs):
                active.add(buffs[r])
                casts = 1.0
            else:
                use = min(1.0, q_left)
                q_left -= use
                casts = 1.0 + use
            if r == 0:
                casts += surge
            dice = D["d10"] + (D["d6"] if "hex" in active else 0) + (D["d8"] if spellmight_on else 0)
            flat = agon + (cha if g["potent"] else 0) + (2 * LIT if g["callous"] else 0) + \
                (pb if "curse" in active else 0)
            total += casts * n * attack(bonus, ac, adv, dice, flat, thr0 - ("curse" in active))
        best = max(best, total)
    return best


def eb_round1(st, g, ac, gloves, spellmight_on):
    """Round 1 with advantage, no buffs: Eldritch Blast + Quickened EB (+ Action Surge / Quickspell)."""
    cha = cha_mod(st, g)
    bonus = st["prof"] + cha + g["atk"] + (1 if gloves == "Helldusk Gloves" else 0) - (5 if spellmight_on else 0)
    casts = 1 + (st["lv"][S] >= 3) + (st["lv"][F] >= 2) + bool(g.get("quickspell"))
    flat = (cha if st["lv"][W] >= 2 else 0) + (cha if g["potent"] else 0) + (2 * LIT if g["callous"] else 0)
    dice = D["d10"] + (D["d8"] if spellmight_on else 0)
    thr = 20 - st["sniper"] - g["crit"] - (1 if st["champion"] else 0)
    return casts * beams(st["level"]) * attack(bonus, ac, True, dice, flat, thr)


# ------------------------------------------------------------------ melee builds
def smite_pool(st):
    """Slots per fight that go into Divine Smite (one level-1/lowest slot per fight is Hex)."""
    if st["lv"][P] < 2:
        return {}
    pool = dict(st["slots"])
    pn, pl = st["pact"]
    if pn:
        pool[pl] = pool.get(pl, 0) + pn * SEGMENTS
    hex_left = FIGHTS
    for l in sorted(pool):
        take = min(pool[l], hex_left)
        pool[l] -= take
        hex_left -= take
    if st["lv"][S] >= 3:
        pool[2] = max(0, pool.get(2, 0) - 1)             # keep one level-2 slot for a Quickened Hold Person
    return {l: c / FIGHTS for l, c in pool.items() if c > 0}


def smite_dice(level):
    return D["d8"] * min(6, level + 1)


def melee_fight(st, g, ac, adv_item, weapon, gwm_on, curse_ok, vow_ok):
    label, die, ndice, ench, wextra, heavy, duel = weapon
    cha, pb = cha_mod(st, g), st["prof"]
    n_att = 2 if (st["lv"][P] >= 5 or st["lv"][W] >= 5) else 1
    gwm = gwm_on and st["gwm"] and heavy
    wdice = (GWF[die] if heavy and st["lv"][P] >= 2 else D[die]) * ndice
    duelling = 2 if (duel and st["lv"][P] >= 2) else 0  # Paladin takes Duelling with the rapier
    bonus = pb + cha + ench + g["atk"] - (5 if gwm else 0)
    flat0 = cha + ench + (10 if gwm else 0) + g["flat"] + duelling + (cha if st["lv"][W] >= 12 else 0)
    thr0 = 20 - g["crit"] - (1 if duel else 0)
    pool = smite_pool(st)
    best = 0.0
    for buffs in [(), ("hex",), ("curse",), ("curse", "hex"), ("vow",), ("vow", "curse"), ("vow", "hex"),
                  ("vow", "curse", "hex")]:
        if ("curse" in buffs and not curse_ok) or ("vow" in buffs and not vow_ok):
            continue
        for order in set(permutations(buffs)):
            total, active, crits, hits = 0.0, set(), 0.0, 0.0
            for r in range(ROUNDS):
                free_bonus = r >= len(order)
                if not free_bonus:
                    active.add(order[r])
                adv = adv_item or "vow" in active
                thr = thr0 - ("curse" in active)
                dice = wdice + wextra + g["extra"] + (D["d6"] + g["extra_conc"] if "hex" in active else 0)
                flat = flat0 + (pb if "curse" in active else 0)
                ph, pc = p_hit(bonus, ac, adv, thr), p_crit(adv, thr)
                att = n_att
                if free_bonus and duel:
                    att += 1
                elif free_bonus and gwm:
                    att += min(1.0, 1 - (1 - pc) ** n_att + 0.15)     # crit or kill triggers the bonus attack
                total += att * (ph * (dice + flat) + pc * dice)
                crits += att * pc
                hits += att * (ph - pc)
            sm, c_left, h_left = 0.0, crits, hits
            for l in sorted(pool, reverse=True):
                cnt = pool[l]
                on_c = min(cnt, c_left); c_left -= on_c; cnt -= on_c
                on_h = min(cnt, h_left); h_left -= on_h
                sm += smite_dice(l) * (2 * on_c + on_h)
            best = max(best, total + sm)
    return best


def melee_round1(st, g, ac, weapon, gwm_on):
    """Round 1 with advantage: Hexblade's Curse as the bonus action, every hit smites with the best slots left."""
    label, die, ndice, ench, wextra, heavy, duel = weapon
    cha, pb = cha_mod(st, g), st["prof"]
    n_att = 2 if (st["lv"][P] >= 5 or st["lv"][W] >= 5) else 1
    gwm = gwm_on and st["gwm"] and heavy
    wdice = (GWF[die] if heavy and st["lv"][P] >= 2 else D[die]) * ndice
    curse = st["hexblade"]
    thr = 20 - g["crit"] - (1 if duel else 0) - curse
    bonus = pb + cha + ench + g["atk"] - (5 if gwm else 0)
    flat = cha + ench + (10 if gwm else 0) + g["flat"] + (2 if duel and st["lv"][P] >= 2 else 0) + \
        (cha if st["lv"][W] >= 12 else 0) + (pb if curse else 0)
    dice = wdice + wextra + g["extra"]
    att = n_att + (0 if curse else (1 if duel else 0))
    ph, pc = p_hit(bonus, ac, True, thr), p_crit(True, thr)
    dmg = att * (ph * (dice + flat) + pc * dice)
    if st["lv"][P] >= 2:
        avail = dict(st["slots"])
        pn, pl = st["pact"]
        if pn:
            avail[pl] = avail.get(pl, 0) + pn
        best = sorted([l for l, c in avail.items() for _ in range(c)], reverse=True)[:att]
        dmg += sum(smite_dice(l) * (ph + pc) for l in best)
    return dmg


# ------------------------------------------------------------------ AoE, control, defence
def save_fail(dc, save_bonus, disadv=False):
    p_save = max(0.05, min(0.95, (21 - (dc - save_bonus)) / 20))
    return 1 - (p_save ** 2 if disadv else p_save)


def gear_of(bid, act):
    return CASTER_GEAR[act] if BUILDS[bid]["kind"] == "eb" else MELEE_GEAR[act]


def dc_of(bid, level, act):
    st = state(bid, level)
    g = gear_of(bid, act)
    gear_dc = g["dc"] if BUILDS[bid]["kind"] == "eb" else (1 if act == 3 else 0)    # melee: Helldusk Gloves
    return 8 + st["prof"] + cha_mod(st, g) + gear_dc


def aoe(bid, level, act):
    """Best single AoE cast vs 3 targets (DEX / CON save +2 in Act 3): expected total damage."""
    st = state(bid, level)
    dc, sv = dc_of(bid, level, act), ACT_SAVE[act] - 1
    cha = cha_mod(st, gear_of(bid, act))
    opts = [(0.0, "none")]
    if st["lv"][S] >= 5:
        ea = cha if st["lv"][S] >= 6 else 0             # Elemental Affinity (Red Draconic) adds CHA to fire spells
        top = max(l for l in st["slots"])
        dmg = (8 + top - 3) * D["d6"] + ea
        pf = save_fail(dc, sv)
        opts.append((3 * (pf * dmg + (1 - pf) * dmg / 2), f"Fireball (level {top})"))
    if st["lv"][W] >= 11:
        pf = save_fail(dc, sv + 1)
        opts.append((3 * pf * 8 * D["d6"], "Circle of Death (Mystic Arcanum)"))
    if st["lv"][W] >= 5:
        pf = save_fail(dc, sv)
        opts.append((3 * (2 * D["d6"] + pf * 2 * D["d6"] + (1 - pf) * D["d6"]), "Hunger of Hadar (1st round)"))
    return max(opts)


def defence(bid, level, act):
    st = state(bid, level)
    seq = BUILDS[bid]["seq"][:level]
    con = 23 if act == 3 else 16                         # Act 3: Amulet of Greater Health
    cm = mod(con)
    hd = {W: 8, S: 6, P: 10, F: 10}
    hp = hd[seq[0]] + cm + sum(hd[c] // 2 + 1 + cm for c in seq[1:]) + (st["lv"][S] if "Draconic" in
                                                                        BUILDS[bid]["name"] else 0)
    g = gear_of(bid, act)
    if BUILDS[bid]["kind"] == "eb":
        ac = (13 if st["lv"][S] else 10) + 2 + g["ac"]  # Draconic 13 + DEX 2 (or robe 10 + DEX); shield, robe +1
        dr = 0
    else:
        ac, dr = g["ac"], g["dr"]
    return dict(hp=hp, ac=ac, dr=dr, aura=st["lv"][P] >= 6)


# ------------------------------------------------------------------ evaluation
def evaluate(bid, act, ac=None, adv=False):
    level, ac = ACT_LEVEL[act], (ACT_AC[act] if ac is None else ac)
    st, g = state(bid, level), gear_of(bid, act)
    if BUILDS[bid]["kind"] == "eb":
        g = dict(g)
        gloves_opts = g["gloves"]
        if bid == "E" and act == 3:
            g["quickspell"] = True                        # the pure Warlock spends the glove slot on Quickspell
            gloves_opts = ["Quickspell Gloves"]
        best = (0.0, 0.0, "")
        for gl in gloves_opts:
            for sm in ([False, True] if gl == "Spellmight Gloves" else [False]):
                f = SR_COVER * eb_fight(st, g, ac, adv, gl, st["hexblade"], sm) + \
                    (1 - SR_COVER) * eb_fight(st, g, ac, adv, gl, False, sm)
                if f / ROUNDS > best[0]:
                    best = (f / ROUNDS, eb_round1(st, g, ac, gl, sm), gl + (" (-5/+1d8 on)" if sm else ""))
        return best
    best = (0.0, 0.0, "")
    for wpn in g["weapons"]:
        for gw in (False, True):
            if gw and not (st["gwm"] and wpn[5]):
                continue
            f = SR_COVER * melee_fight(st, g, ac, adv, wpn, gw, st["hexblade"], st["lv"][P] >= 1) + \
                (1 - SR_COVER) * melee_fight(st, g, ac, adv, wpn, gw, False, False)
            if f / ROUNDS > best[0]:
                best = (f / ROUNDS, melee_round1(st, g, ac, wpn, gw), wpn[0] + (" + GWM" if gw else ""))
    return best


def evaluate_patron(bid, patron):
    BUILDS["_p"] = dict(BUILDS[bid], patron=patron)
    r = evaluate("_p", 3, 19)[0]
    BUILDS.pop("_p")
    return r


def main():
    global KEEP_UTILITY
    print("=== Level 12, Act 3 gear. Sustained = average per round of a 4-round fight; R1 = round 1 with advantage")
    print(f"{'':<3} {'AC16':>6} {'AC19':>6} {'AC22':>6} | {'AC19adv':>7} | {'R1':>6} | {'AoE x3':>6} {'DC':>3} "
          f"{'WIS fail':>8} | {'AC':>3} {'HP':>4} {'DR':>2}  best gear choice")
    rows = {}
    for bid in BUILDS:
        s16 = evaluate(bid, 3, 16)[0]
        s19, r1, choice = evaluate(bid, 3, 19)
        s22 = evaluate(bid, 3, 22)[0]
        a19 = evaluate(bid, 3, 19, adv=True)[0]
        ao, aon = aoe(bid, 12, 3)
        dc = dc_of(bid, 12, 3)
        hei = state(bid, 12)["lv"][S] >= 10
        df = defence(bid, 12, 3)
        rows[bid] = (s19, a19, r1)
        print(f"{bid:<3} {s16:6.1f} {s19:6.1f} {s22:6.1f} | {a19:7.1f} | {r1:6.1f} | {ao:6.1f} {dc:3d} "
              f"{save_fail(dc, 3, hei):8.0%} | {df['ac']:3d} {df['hp']:4d} {df['dr']:2d}  {choice}; {aon}"
              f"{'; Heightened' if hei else ''}{'; Aura of Protection' if df['aura'] else ''}")
    print()
    for bid, b in BUILDS.items():
        print(f"  {bid:<3} {b['name']}")
    print("\n=== Gain at AC 19 (no advantage / advantage / round 1)")
    for ref in ("A", "F"):
        for bid in rows:
            if bid == ref:
                continue
            print(f"  {bid:<3} vs {ref}: " + " / ".join(f"{100 * (rows[bid][i] / rows[ref][i] - 1):+4.0f}%"
                                                     for i in range(3)))
        print()
    print("=== Power curve: sustained per round, no advantage / advantage (AC 15 at L5, 17 at L8, 19 at L12)")
    for bid in BUILDS:
        cells = []
        for act in (1, 2, 3):
            cells.append(f"{evaluate(bid, act)[0]:5.1f} / {evaluate(bid, act, adv=True)[0]:5.1f}")
        print(f"  {bid:<3} Act 1 {cells[0]}   Act 2 {cells[1]}   Act 3 {cells[2]}")
    print("\n=== Where B's gain over A comes from (AC 19: no advantage / advantage / round 1)")
    steps = [("A as in BuildAdvisor", dict(BUILDS["A"])),
             ("+ 2nd feat +1 CHA (CHA 22 with Birthright) instead of Spell Sniper",
              dict(BUILDS["A"], feats={6: ("cha", 2), 10: ("cha", 1)})),
             ("+ Hexblade instead of Fiend (Hexblade's Curse)",
              dict(BUILDS["A"], feats={6: ("cha", 2), 10: ("cha", 1)}, patron="Hexblade")),
             ("+ Fighter 1-2 at levels 11-12 (Action Surge) = B", dict(BUILDS["B"]))]
    for label, b in steps:
        BUILDS["X"] = b
        r, a = evaluate("X", 3, 19), evaluate("X", 3, 19, adv=True)
        print(f"  {label:<70} {r[0]:6.1f} / {a[0]:6.1f} / {r[1]:6.1f}")
    BUILDS.pop("X", None)
    print("\n=== Checks for B (AC 19, no advantage / advantage)")
    st = state("B", 12)
    for gl in ("Spellmight Gloves", "Helldusk Gloves"):
        out = []
        for adv in (False, True):
            out.append(max(SR_COVER * eb_fight(st, CASTER_GEAR[3], 19, adv, gl, True, sm) / ROUNDS +
                           (1 - SR_COVER) * eb_fight(st, CASTER_GEAR[3], 19, adv, gl, False, sm) / ROUNDS
                           for sm in ([False, True] if gl == "Spellmight Gloves" else [False])))
        print(f"  gloves {gl:<18} {out[0]:6.1f} / {out[1]:6.1f}")
    no_ds = dict(CASTER_GEAR[3], crit=0)
    v = [SR_COVER * eb_fight(st, no_ds, 19, a, "Helldusk Gloves", True, False) / ROUNDS +
         (1 - SR_COVER) * eb_fight(st, no_ds, 19, a, "Helldusk Gloves", False, False) / ROUNDS for a in (False, True)]
    print(f"  without The Dead Shot (Hellrider Longbow) {v[0]:6.1f} / {v[1]:6.1f}")
    duke = dict(CASTER_GEAR[3], atk=2, dc=2, cha_extra=2)
    v = [SR_COVER * eb_fight(st, duke, 19, a, "Helldusk Gloves", True, False) / ROUNDS +
         (1 - SR_COVER) * eb_fight(st, duke, 19, a, "Helldusk Gloves", False, False) / ROUNDS for a in (False, True)]
    print(f"  Duke Ravengard's Longsword (+2 CHA uncapped) instead of Markoheshkir {v[0]:6.1f} / {v[1]:6.1f}")
    print(f"  if Hexblade's Curse does not work on Eldritch Blast: B {evaluate_patron('B', 'Fiend'):6.1f}, "
          f"C {evaluate_patron('C', 'Fiend'):6.1f}")
    for label, feats in (("2nd feat +1 CHA +1 CON", {6: ("cha", 2), 10: ("cha", 1)}),
                         ("2nd feat Spell Sniper", {6: ("cha", 2), 10: ("sniper", 0)}),
                         ("Spell Sniper + Mirror of Loss (CHA 22)", {6: ("cha", 4), 10: ("sniper", 0)})):
        BUILDS["X"] = dict(BUILDS["B"], feats=feats)
        print(f"  {label:<40} {evaluate('X', 3, 19)[0]:6.1f} / {evaluate('X', 3, 19, adv=True)[0]:6.1f}")
    for keep in (8, 4, 0):
        old, KEEP_UTILITY = KEEP_UTILITY, keep
        print(f"  keep {keep} level-3+ slots: quickened/fight {quick_per_fight(st):.2f}, "
              f"B {evaluate('B', 3, 19)[0]:6.1f}; C {evaluate('C', 3, 19)[0]:6.1f}; A {evaluate('A', 3, 19)[0]:6.1f}; "
              f"D {evaluate('D', 3, 19)[0]:6.1f}")
        KEEP_UTILITY = old
    BUILDS.pop("X", None)


if __name__ == "__main__":
    main()
