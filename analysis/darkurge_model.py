"""The Dark Urge - build model (Patch 8). Same idea as analysis/astarion_dpr.py, more builds and four columns.

Inputs read from the game data (data/cache/stats_resolved.json, data/items_all/*.jsonl, Progressions.lsx of
Shared/SharedDev/Gustav/GustavX), checked 2026-10-09:
- Throw_FrenziedThrow (Berserker "Enraged Throw"): BonusActionPoint:1, NO cooldown, damage ThrownWeapon+StrengthModifier,
  ApplyStatus(PRONE) on every hit (no save). Fast Hands (Thief 3) = ActionResource(BonusActionPoint,1) -> 2 per turn.
- PRONE: Advantage(AttackTarget) for attackers within 3 m. HOLD_PERSON: auto-crit within 3 m.
- TavernBrawler: thrown attacks (RangedUnarmedAttack) +STR to attack and DealDamage(StrengthModifier) on hit.
- Rage_Rage_Boosts: EntityThrowDamage(2) (Barbarian < 9), Rage_Rage_Boosts_2: EntityThrowDamage(3) (Barbarian 9+).
- MAG_Bhaalist_Aura_Of_Murder_Passive: enemies within 3 m Vulnerable to Piercing (= piercing damage x2).
- Nyrulna: 1d6+3 piercing, +1d6 thunder, thrown blast 3d4 thunder (6 m), returns. Sword of Chaos 2d6+2 +1d4 necrotic.
  Balduran's Giantslayer 2d6+3 + STR modifier again. Duellist's Prerogative 1d8+3 +1d4 necrotic, crit 19, BA attack.
- Champion ImprovedCritical, Sarevok's Horned Helmet, Dead Shot, Hexblade's Curse: ReduceCriticalAttackThreshold(1).
- END_ALLYABILITIES_BHAALBUFF (A Most Bloody Inheritance): ReduceCriticalAttackThreshold(2), finale only (High Hall).
- ThirstingBlade_Blade is granted at Warlock 5 (Patch 8): Extra Attack with a pact OR Hexblade-bound weapon.
- Slayer_Player_10: STR 25, 153 HP, AC 14, Slam 6d6+STR, Slayer_ExtraAttack_2 (3 slams per action).

Model rules (simplifications, same for every build):
- A fight = 4 rounds; 3 fights per long rest with a short rest between fights (per-short-rest resources every
  fight, per-long-rest resources spread over 12 rounds). Sustained = mean of the 4 rounds; nova = round 1.
- Crits double dice only. Bhaalist vulnerability doubles the piercing part (weapon dice + flat weapon damage);
  extra damage instances without a type (Tavern Brawler's extra STR, ring/glove throw dice, rage) are NOT doubled.
- Smites are spent on crits first (the game asks again on a crit), then on hits; budget = slots / 12 rounds.
- Every non-thrower build gets the Risky Ring (advantage) in Act 2-3 so the comparison is on equal footing; GWM /
  Sharpshooter are switched on only when they raise the expected damage.
- Target: humanoid, Medium, not undead/fiend. Act 1 = level 5, AC 15; Act 2 = level 8, AC 17; Act 3 = level 12.
"""

def p_hit(bonus, ac, adv):
    need = max(2, min(20, ac - bonus))
    p = (21 - need) / 20
    return 1 - (1 - p) ** 2 if adv else p

def p_crit(thr, adv):
    p = max(0.05, (21 - thr) / 20)
    return 1 - (1 - p) ** 2 if adv else p

def one(a, ac, adv, vuln, power=None):
    """expected damage of one attack. a: bonus, dice, flat, pdice, pflat, thr, pa (power attack -5/+10 allowed)."""
    m = 2 if vuln else 1
    best = 0
    for pw in ((False, True) if a.get("pa") else (False,)):
        if power is not None and pw != power:
            continue
        bonus = a["bonus"] - (5 if pw else 0)
        pflat = a["pflat"] + (10 if pw else 0)
        dice = a["dice"] + a["pdice"] * m
        flat = a["flat"] + pflat * m
        ph, pc = p_hit(bonus, ac, adv), p_crit(a["thr"], adv)
        e = ph * (dice + flat) + pc * dice
        best = max(best, e)
    return best

def hits_crits(a, ac, adv):
    bonus = a["bonus"] - (5 if a.get("pa") else 0)
    return p_hit(bonus, ac, adv), p_crit(a["thr"], adv)

def rnd(build, r, ac, vuln, crit_bonus=0, budget=True):
    """damage of round r (1-based) for build at act-3 style params."""
    seq = build["rounds"](r)                       # list of (attack_key, adv)
    tot, hits, crits = 0.0, 0.0, 0.0
    seq = [(e[0], e[1], e[2] if len(e) > 2 else 1.0) for e in seq]
    for key, adv, w in seq:
        a = dict(build[key]); a["thr"] -= crit_bonus
        adv = adv or build.get("adv", False)
        tot += w * one(a, ac, adv, vuln and build.get("bhaal", False))
        h, c = hits_crits(a, ac, adv)
        hits += w * h; crits += w * c
    if build.get("sa"):                            # Sneak Attack once per turn (needs advantage)
        anyadv = build.get("adv") or any(adv for _, adv, _ in seq)
        if anyadv:
            m = 2 if (vuln and build.get("bhaal")) else 1
            miss_all = 1
            for key, adv, w in seq:
                miss_all *= (1 - hits_crits(build[key], ac, adv or build.get("adv", False))[0]) ** w
            tot += (1 - miss_all) * build["sa"] * m * (1 + crits / max(hits, 1e-9))
    if build.get("smite"):                         # (avg dice per smite, smites per round / round-1 smites)
        d, per_round, nova = build["smite"]
        n = nova if (r == 1 and not budget) else per_round
        on_crit = min(n, crits)
        on_hit = max(0.0, min(n, hits) - on_crit)
        tot += d * (2 * on_crit + on_hit)
    tot += build.get("extra", lambda r: 0)(r)
    return tot

def fight(build, ac, vuln, crit_bonus=0):
    rs = [rnd(build, r, ac, vuln, crit_bonus) for r in (1, 2, 3, 4)]
    nova = rnd(build, 1, ac, vuln, crit_bonus, budget=False)
    return sum(rs) / 4, nova

# ------------------------------------------------------------------------------------------- Act 3 builds
def A(bonus, dice, flat, pdice, pflat, thr, pa=False):
    return dict(bonus=bonus, dice=dice, flat=flat, pdice=pdice, pflat=pflat, thr=thr, pa=pa)

STR27, PROF = 8, 4          # Elixir of Cloud Giant Strength (STR 27) for STR builds; proficiency at 12

BUILDS = {}

# T  VERDICT: Berserker 5 / Thief 4 / Champion 3 thrower, Nyrulna + Bhaalist Armour (Duergar).
#    throw: STR 8 + Tavern Brawler 8 + prof 4 + Nyrulna 3 = +23. Piercing: 1d6 + 3 + STR 8 (Enraged Throw +STR 8 more).
#    Other: TB 8, rage 2, Caustic Band 2, Nyrulna blast 3d4 (7.5, never crit), thunder 1d6 + Kushigo 1d4 + Flinging 1d4.
#    Helmet of Grit: a 3rd bonus action at <= 50% HP (assumed in 30% of rounds 2-4) = one more Enraged Throw.
#    Crit 19 (Champion). Round 1: Rage (BA1), Enraged Throw (BA2, Prone), 2 throws + Action Surge 2 throws at
#    advantage (Prone, within 3 m). Rounds 2-4: Enraged (no adv), Enraged (adv), 2 throws (adv).
GRIT = 0.3
_t = A(23, 3.5 + 2.5 + 2.5, 8 + 2 + 2 + 7.5, 3.5, 3 + STR27, 19)
def _t_rounds(r, grit=GRIT):
    if r == 1:
        return [("enraged", False)] + [("throw", True)] * 4
    return [("enraged", False), ("enraged", True), ("throw", True), ("throw", True), ("enraged", True, grit)]
BUILDS["T  Berserker 5 / Thief 4 / Champion 3 thrower (Nyrulna, Bhaalist, Helmet of Grit)"] = dict(
    throw=_t, enraged=dict(_t, pflat=_t["pflat"] + STR27), bhaal=True, rounds=_t_rounds,
    ac="19 (Bhaalist 14+2, Defence 1, shield 2)", hp=150, dr="Rage: resist bludgeoning/piercing/slashing",
    aoe=lambda r: (5 if r == 1 else 4 + GRIT) * 0.95 * 7.5 * 2,     # blast on 2 more enemies per throw
    control="Enraged Throw: Prone, no save, 2-3 per turn",
)
_ts = dict(_t, thr=18)
BUILDS["T2 same, Sarevok's Horned Helmet instead of Grit (crit 18, Frightened immunity)"] = dict(
    throw=_ts, enraged=dict(_ts, pflat=_ts["pflat"] + STR27), bhaal=True, rounds=lambda r: _t_rounds(r, 0),
    ac="19", hp=150, dr="Rage", aoe=lambda r: (5 if r == 1 else 4) * 0.95 * 7.5 * 2, control="Prone, 2 per turn",
)

# Z  Throwzerker Berserker 10 / Fighter 2 (BuildAdvisor), same gear (Helmet of Grit too); rage throw +3; crit 20.
#    Round 1: Rage (BA) + 2 throws + Action Surge 2 throws (no Prone yet). Rounds 2-4: Enraged (Prone) + 2 throws (adv).
_z = A(23, 8.5, 8 + 3 + 2 + 7.5, 3.5, 3 + STR27, 20)
BUILDS["Z  Throwzerker Berserker 10 / Fighter 2 (BuildAdvisor), same gear"] = dict(
    throw=_z, enraged=dict(_z, pflat=_z["pflat"] + STR27), bhaal=True,
    rounds=lambda r: [("throw", False)] * 4 if r == 1
                     else [("enraged", False), ("throw", True), ("throw", True), ("enraged", True, GRIT)],
    ac="19", hp=159, dr="Rage", aoe=lambda r: (4 if r == 1 else 3 + GRIT) * 0.95 * 7.5 * 2,
    control="Enraged Throw: Prone, 1-2 per turn",
)

# X  Astarion's THX on the Durge (Gloom 5 / BM 3 / Thief 4), Hellfire + Hand Crossbow +2, Legacy, Mask, Risky Ring,
#    Bhaalist (stand within 3 m). DEX 19. Shot: 4+4+2 archery+2 ench+2 Legacy+2 Mask = +16 (SS -5/+10).
_x = A(16, 0, 0, 3.5, 2 + 4 + 2, 20, pa=True)
BUILDS["X  THX Gloom 5 / BM 3 / Thief 4, dual hand crossbows + Bhaalist (conflicts with Astarion)"] = dict(
    shot=_x, bhaal=True, adv=True, sa=7,
    rounds=lambda r: [("shot", True)] * (7 if r == 1 else 4),
    extra=lambda r: 3.5 * 0.9 if r == 1 else 0,
    ac="18 (Bhaalist 14+4)", hp=144, dr="-", aoe=lambda r: 0, control="Menacing/Trip Attack DC 16 (4 dice / SR)",
)

# G  Gloom 5 / Assassin 4 / BM 3 (BuildAdvisor): The Dead Shot (crit 19, Keen Attack +prof), Legacy, Mask, Risky,
#    Bhaalist. DEX 17. Shot: 3+4+4 keen+2 archery+2 ench+2 Legacy+2 Mask = +19.
_g = A(19, 0, 0, 4.5, 2 + 3 + 2, 19, pa=True)
BUILDS["G  Gloom Stalker 5 / Assassin 4 / BM 3 (BuildAdvisor), Dead Shot + Bhaalist"] = dict(
    shot=_g, bhaal=True, adv=True, sa=7,
    rounds=lambda r: [("shot", True)] * (5 if r == 1 else 2),
    extra=lambda r: 3.5 * 0.95 if r == 1 else 0,
    ac="17", hp=144, dr="-", aoe=lambda r: 0, control="Menacing/Trip DC 15",
)

# O  Oathbreaker Paladin 12 (BuildAdvisor): Giantslayer (STR twice), STR 27, GWF+Savage dice ~9.5, IDS 1d8,
#    Aura of Hate +3, Legacy +2, Sarevok (crit 19), Risky. Attack 8+4+3+2 = +17 (GWM). 10 slots 4/3/3.
_o = A(17, 9.5 + 4.5, 3 + 3 + 2 + STR27 + STR27, 0, 0, 19, pa=True)
BUILDS["O  Oathbreaker Paladin 12 (BuildAdvisor), Giantslayer"] = dict(
    hit=_o, adv=True, smite=(13.05, 10 / 12, 2.0),
    rounds=lambda r: [("hit", True)] * 2,
    extra=lambda r: 0.3 * 40,      # GWM bonus attack on crit/kill, ~0.3 per round x ~40
    ac="21 (Helldusk)", hp=148, dr="3 per hit (Helldusk); Aura of Protection +3 saves",
    aoe=lambda r: 0.3 * 20, control="Command / Dreadful Aspect DC 15",
)

# S  Sorcadin Vengeance 6 / Shadow 6 (BuildAdvisor): Giantslayer, STR 27, CHA 18, Dark Justiciar Helmet (crit 19,
#    Patch 8 bug: always), Legacy, Risky. 14 slots (CL 9): 2 Quickened Hold Person per long rest (DC 16,
#    ~60% fail x 60% humanoid -> held ~30% of attack rounds = auto-crit), ~8 smites avg 19.7 dice.
_s = A(17, 8.33, 3 + 2 + STR27 + STR27, 0, 0, 19, pa=True)
_s_held = dict(_s, thr=1)
HELD = {1: 0.36, 2: 0.22, 3: 0.13, 4: 0.08}   # one Quickened Hold Person per fight (2 per long rest + slot points)
BUILDS["S  Sorcadin Vengeance Paladin 6 / Shadow Sorcerer 6 (BuildAdvisor)"] = dict(
    hit=_s, held=_s_held, adv=True, smite=(19.7, 8 / 12, 2.0),
    rounds=lambda r: [("held", True, HELD[r]), ("hit", True, 1 - HELD[r])] * 2,
    extra=lambda r: 0.3 * 38,
    ac="21", hp=136, dr="3 per hit; Aura of Protection +4 saves", aoe=lambda r: 0,
    control="Quickened Hold Person / Hold Monster DC 16; Darkness",
)

# L  Lockadin Vengeance 5 / Hexblade 7: Sword of Chaos, CHA 22 (Birthright), GWF, GWM, Helldusk Gloves, Hexblade's
#    Curse (+4, crit 19, ~60% uptime), Elixir of Viciousness, Risky. Attack 6+4+2 = +12. Smites 3 L1 + 6 pact L4.
_l = A(12, 8.33 + 2.5 + 3.5, 2 + 6 + 0.6 * 4, 0, 0, 18.4, pa=True)
BUILDS["L  Lockadin Vengeance 5 / Hexblade 7 (BuildAdvisor)"] = dict(
    hit=_l, adv=True, smite=(13.5, 9 / 12, 2.0),
    rounds=lambda r: [("hit", True)] * 2, extra=lambda r: 0.3 * 35,
    ac="21", hp=130, dr="3 per hit", aoe=lambda r: 0, control="Hold Person DC 17 (Band of the Mystic Scoundrel)",
)

# B  Bardadin Paladin 2 / Swords Bard 10 with Bhaalist: Duellist's Prerogative (1d8+3 piercing, crit 19, BA attack),
#    STR 27, Duelling +2, Legacy, Sarevok (crit 18), Risky. 3 attacks. 13 smites avg ~17 dice.
_b = A(17, 2.5, 0, 4.5, 3 + STR27 + 2 + 2, 18)
BUILDS["B  Bardadin Paladin 2 / Swords Bard 10, Duellist's Prerogative + Bhaalist"] = dict(
    hit=_b, adv=True, bhaal=True, smite=(17.0, 13 / 12, 3.0),
    rounds=lambda r: [("hit", True)] * 3, extra=lambda r: 4 * 0.9,   # Withering Cut (reaction, prof necrotic)
    ac="14 (Bhaalist, DEX 10)", hp=120, dr="-", aoe=lambda r: 0,
    control="Hold Person / Hypnotic Pattern / Hold Monster DC 17",
)

# W  A resisting Dark Urge: Hexblade Warlock 12, GWM, CHA 19 -> 21 with Birthright; Sword of Chaos, Lifedrinker +5,
#    Helldusk Gloves 1d6, Hex 1d6 (~70%), Hexblade's Curse (+4, crit 19, ~60%), Elixir of Viciousness, Risky.
#    Attack 5+4+2 = +11. No smites.
_w = A(11, 7 + 2.5 + 3.5 + 0.7 * 3.5, 2 + 5 + 5 + 0.6 * 4, 0, 0, 18.4, pa=True)
BUILDS["W  Resisting Durge: Hexblade Warlock 12 + GWM (durge_hexblade)"] = dict(
    hit=_w, adv=True, rounds=lambda r: [("hit", True)] * 2, extra=lambda r: 0.3 * 33,
    ac="21 (Helldusk)", hp=135, dr="3 per hit", aoe=lambda r: 0,
    control="Hold Person / Hold Monster (pact slots) DC 18",
)

SLAYER = A(4 + 7, 21, 7, 0, 0, 20)   # Slayer form at Durge level 10+: 3 slams (6d6+7) per action, gear off

def slayer(ac):
    return 3 * one(SLAYER, ac, False, False)

# ------------------------------------------------------------------------------------------- Act 1 / Act 2
# Same structure, smaller numbers. Act 1: level 5, prof 3, Hill Giant elixir (STR 21) for STR builds, AC 15.
# Act 2: level 8, prof 3, AC 17. Bhaalist / Nyrulna / Act 3 gear excluded. Mantle: kill -> Invisible -> the
# next attack has advantage (modelled as advantage on 25% of the attacks of builds without another source).
CURVE = {
  "T": {
    1: dict(throw=A(14, 5, 5 + 2 + 2, 5.5, 1 + 5, 20), enraged=A(14, 5, 9, 5.5, 11, 20),
            rounds=lambda r: [("throw", False)] * 2 if r == 1 else [("enraged", False), ("throw", True), ("throw", True)],
            note="Berserker 5 = same as Z; Returning Pike, Kushigo, Flinging, Caustic"),
    2: dict(throw=A(14, 5, 9, 5.5, 6, 19), enraged=A(14, 5, 9, 5.5, 11, 19),
            rounds=lambda r: [("enraged", False), ("throw", True), ("throw", True)] if r == 1
                             else [("enraged", False), ("enraged", True), ("throw", True), ("throw", True)],
            note="Berserker 5 / Thief 3: 4 throws; Dark Justiciar Helmet crit 19"),
  },
  "Z": {
    1: dict(throw=A(14, 5, 9, 5.5, 6, 20), enraged=A(14, 5, 9, 5.5, 11, 20),
            rounds=lambda r: [("throw", False)] * 2 if r == 1 else [("enraged", False), ("throw", True), ("throw", True)]),
    2: dict(throw=A(14, 5, 9, 5.5, 6, 19), enraged=A(14, 5, 9, 5.5, 11, 19),
            rounds=lambda r: [("throw", False)] * 4 if r == 1 else [("enraged", False), ("throw", True), ("throw", True)],
            note="Berserker 6 / Fighter 2"),
  },
  "O": {
    1: dict(hit=A(9, 6.3, 1 + 5 + 2, 0, 0, 19, pa=True), adv=False, mantle=True, smite=(10.5, 6 / 12, 2.0),
            rounds=lambda r: [("hit", False)] * 2, extra=lambda r: 0.25 * 18,
            note="Paladin 5, Unseen Menace (adv while invisible ~ 'mantle'), Caustic"),
    2: dict(hit=A(10, 6.3 + 2.5 + 2.5, 2 + 5 + 3, 0, 0, 20, pa=True), adv=True, smite=(12.5, 9 / 12, 2.0),
            rounds=lambda r: [("hit", True)] * 2, extra=lambda r: 0.3 * 25,
            note="Paladin 8, Halberd of Vigilance, Aura of Hate, Flawed Helldusk Gloves, Risky Ring"),
  },
  "S": {
    1: dict(hit=A(9, 6.3, 8, 0, 0, 19, pa=True), mantle=True, smite=(10.5, 6 / 12, 2.0),
            rounds=lambda r: [("hit", False)] * 2, extra=lambda r: 0.25 * 18, note="Paladin 5 (Vow of Enmity)"),
    2: dict(hit=A(10, 6.3 + 2.5 + 2.5, 2 + 5, 0, 0, 19, pa=True), held=A(10, 11.3, 7, 0, 0, 1, pa=True), adv=True,
            smite=(12.0, 8 / 12, 2.0), rounds=lambda r: [("held", True, HELD[r]), ("hit", True, 1 - HELD[r])] * 2,
            extra=lambda r: 0.3 * 25, note="Paladin 6 / Sorcerer 2: Quickened Hold Person, Dark Justiciar Helmet"),
  },
  "W": {
    1: dict(hit=A(7, 5.5 + 0.7 * 3.5, 1 + 3 + 0.6 * 3, 0, 0, 19.4, pa=True), mantle=True,
            rounds=lambda r: [("hit", False)] * 2, extra=lambda r: 0.25 * 15, note="Hexblade 5, Sorrow, CHA 17"),
    2: dict(hit=A(9, 5.5 + 2.5 + 2.5 + 0.7 * 3.5, 2 + 4 + 0.6 * 3, 0, 0, 19.4, pa=True), adv=True,
            rounds=lambda r: [("hit", True)] * 2, extra=lambda r: 0.3 * 22,
            note="Hexblade 8, Halberd of Vigilance, CHA 19, Risky Ring"),
  },
  "G": {
    1: dict(shot=A(10, 4.5 + 3.5 + 2.5, 1 + 3 + 2 + 2, 0, 0, 20, pa=True), mantle=True,
            rounds=lambda r: [("shot", False)] * (3 if r == 1 else 2), note="Ranger 5, Longbow +1, Archery gloves, HM, Conduit"),
    2: dict(shot=A(10, 3.5 + 3.5 + 2.5, 2 + 3 + 2 + 2, 0, 0, 19, pa=True), adv=True, sa=7,
            rounds=lambda r: [("shot", True)] * (3 if r == 1 else 2) + ([("shot", True)] * 2 if r == 1 else []),
            note="Ranger 5 / Assassin 3, Darkfire (Haste in 1 of 3 fights ~ folded into round 1), Risky"),
  },
  "X": {
    1: dict(shot=A(10, 3.5 + 2.5, 1 + 3 + 2 + 2, 0, 0, 20, pa=True), off=A(10, 3.5 + 2.5, 1 + 2 + 2, 0, 0, 20, pa=True),
            mantle=True, rounds=lambda r: [("shot", False)] * (3 if r == 1 else 2) + [("off", False)],
            note="Ranger 5 with hand crossbows (off-hand without TWF)"),
    2: dict(shot=A(11, 3.5, 2 + 3 + 2, 0, 0, 20, pa=True), adv=True,
            rounds=lambda r: [("shot", True)] * (6 if r == 1 else 3),
            note="Ranger 5 / Fighter 3 (TWF, Action Surge), Hellfire + HC +1, Risky"),
  },
  "B": {
    1: dict(hit=A(8, 4.5, 3 + 4 + 2 + 2, 0, 0, 20), mantle=True, smite=(10.0, 6 / 12, 1.0),
            rounds=lambda r: [("hit", False)], note="Paladin 2 / Bard 3 (no Extra Attack yet)"),
    2: dict(hit=A(12, 4.5, 2 + 5 + 2, 0, 0, 20), adv=True, smite=(12.5, 11 / 12, 2.0),
            rounds=lambda r: [("hit", True)] * 2, note="Paladin 2 / Bard 6, Phalar Aluve, Duellist gloves, Risky"),
  },
  "L": {
    1: dict(hit=A(8, 6.3, 3 + 4, 0, 0, 20, pa=True), mantle=True, smite=(10.5, 5 / 12, 1.0),
            rounds=lambda r: [("hit", False)], note="Paladin 4 / Warlock 1 (Extra Attack at 6)"),
    2: dict(hit=A(9, 6.3 + 2.5 + 2.5, 2 + 4 + 0.6 * 3, 0, 0, 19.4, pa=True), adv=True, smite=(11.0, 7 / 12, 2.0),
            rounds=lambda r: [("hit", True)] * 2, extra=lambda r: 0.3 * 22, note="Paladin 5 / Hexblade 3"),
  },
}
CURVE_AC = {1: 15, 2: 17}

def curve_fight(p, ac):
    b = dict(p)
    if b.get("mantle") and not b.get("adv"):           # Deathstalker Mantle: ~25% of attacks with advantage
        base = dict(b); adv = dict(b, adv=True)
        s0, n0 = fight(base, ac, False); s1, n1 = fight(adv, ac, False)
        return 0.75 * s0 + 0.25 * s1, 0.75 * n0 + 0.25 * n1
    return fight(b, ac, False)

if __name__ == "__main__":
    print("Act 3, level 12 - sustained (mean of a 4-round fight) / nova (round 1), single target")
    print(f"{'build':<88} {'AC16':>6} {'AC19':>6} {'AC22':>6} | {'nova19':>6} | {'noBhaalist19':>12} | {'finale19 (crit-2)':>17} | {'AoE+':>5}")
    ref = None
    rows = []
    for name, b in BUILDS.items():
        s16, _ = fight(b, 16, True); s19, n19 = fight(b, 19, True); s22, _ = fight(b, 22, True)
        nb, _ = fight(b, 19, False)
        fin, _ = fight(b, 19, True, crit_bonus=2)
        aoe = sum(b["aoe"](r) for r in (1, 2, 3, 4)) / 4
        rows.append((name, s16, s19, s22, n19, nb, fin, aoe))
        print(f"{name:<88} {s16:6.1f} {s19:6.1f} {s22:6.1f} | {n19:6.1f} | {nb:12.1f} | {fin:17.1f} | {aoe:5.1f}")
    print(f"Slayer form (Durge level 10+, gear off): {slayer(16):.1f} / {slayer(19):.1f} / {slayer(22):.1f} at AC 16/19/22")
    t = rows[0][2]; w = [r for r in rows if r[0].startswith("W")][0][2]
    print(f"\nVerdict T vs resisting-Durge Hexblade at AC 19: {t:.1f} vs {w:.1f} = +{(t / w - 1) * 100:.0f}%")
    for r in rows[1:]:
        print(f"  T vs {r[0][:2].strip()}: +{(t / r[2] - 1) * 100:.0f}% sustained AC19, finale +{(rows[0][6] / r[6] - 1) * 100:.0f}%")
    tk = list(BUILDS)[0]
    once = dict(BUILDS[tk], rounds=lambda r: [("enraged", False)] + [("throw", True)] * 4 if r == 1
                else [("enraged", False), ("throw", True), ("throw", True)])
    print(f"\nSensitivity (AC 19): T if Enraged Throw were once per turn (Fast Hands wasted): "
          f"{fight(once, 19, True)[0]:.1f} (Bhaalist) / {fight(once, 19, False)[0]:.1f} (none) -> then Z is the pick")
    lean = dict(BUILDS[tk], throw=dict(_t, flat=2 + 7.5, dice=3.5),
                enraged=dict(_t, flat=2 + 7.5, dice=3.5, pflat=_t["pflat"] + STR27))
    print(f"Sensitivity (AC 19): T if Tavern Brawler's extra hit, Kushigo, Flinging and Caustic did NOT apply to "
          f"throws: {fight(lean, 19, True)[0]:.1f} (Bhaalist) / {fight(lean, 19, False)[0]:.1f} (none)")
    nostr = dict(BUILDS[tk], throw=dict(_t, bonus=_t["bonus"] - 6, flat=_t["flat"] - 3, pflat=_t["pflat"] - 3),
                 enraged=dict(_t, bonus=_t["bonus"] - 6, flat=_t["flat"] - 3, pflat=_t["pflat"] - 6 + STR27))
    print(f"Sensitivity (AC 19): T with STR 20 (no elixir): {fight(nostr, 19, True)[0]:.1f} (Bhaalist) / "
          f"{fight(nostr, 19, False)[0]:.1f} (none)")
    print("\nPower curve (sustained / nova) - Act 1 level 5 vs AC 15, Act 2 level 8 vs AC 17")
    for k, acts in CURVE.items():
        out = []
        for act in (1, 2):
            s, n = curve_fight(acts[act], CURVE_AC[act])
            out.append(f"Act {act}: {s:5.1f} / {n:5.1f}")
        print(f"  {k}: " + " | ".join(out))
