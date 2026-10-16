"""Turn-by-turn strategy search for one character against the gauntlet boss (one enemy that never dies, 16 rounds).

    python tools/optimizer/strategy.py --spec specs.json [--pair 0] [--side a] [--out ranking.json]

specs.json is tools/gauntlet/plan.py's output (one set's spec per side); the character's numbers are read from it and
from the game stats (profile_from_spec). The search is exact, not sampled:

- one attack: the d20 is enumerated (Advantage = best of two, Disadvantage = worst of two, both = one straight d20; a
  natural 1 misses, a natural at or above the crit threshold is a critical hit; measured dice in place of the uniform
  d20 where the records give them, BOSS_ODDS and OWN_ODDS), a Precision Attack die is enumerated with it; damage is
  carried as its first two moments (dice means and variances, every die doubled on a critical hit);
- one turn: the attacks in order with a branch state (Sneak Attack spent, superiority dice spent, boss Frightened or
  Prone, Gaping Wound, Ensnaring Strike), so Sneak Attack lands once, on the first hit with net Advantage;
- the boss's turn: it walks up and attacks unless Frightened or restrained; still at its start spot (round 1, or held
  there since) it only Dashes into reach, which takes its action; knocked Prone by Trip Attack out of its reach it
  walks back and attacks only sometimes (PRONE_CLOSES); its miss gives the set's riposte reaction, its hit can break
  concentration;
- Sneak Attack's one charge (SneakAttack_Charge) comes back as the character's turn ends (seen in game: spent on the
  riposte in the boss's turn, it is missing in the character's next turn; spent in the character's turn, it is there
  again for the boss's), so a riposte that takes it costs the next turn's; the reaction policy (SNEAK_POLICIES) says
  when the riposte may take it;
- the fight: dynamic programming over (round, boss adjacent at the turn's start, superiority dice, Action Surge,
  concentration, the once-per-rest item attacks, Dread Ambusher, Sneak Attack's charge, True Strike from the riposte,
  the boss still at its start spot) for the largest expected total; the same recursion carries the second moment, so
  the total's standard deviation is exact for the chosen policy. The fight is the gauntlet's: it ends as the
  character's 16th turn ends.

A strategy family limits what the turn may do with the boss in reach (melee, step away, stand and shoot) and what it
may use; the search finds each family's best policy, and families are ranked by expected total.
"""
import argparse
import functools
import json
import re
import sys
from dataclasses import dataclass, replace

ROUNDS = 16
# The reaction policy for Sneak Attack in the boss's turn (on the riposte), as the gauntlet sets it
# (plan.reactions_enemy_turn for Interrupt_SneakAttack / Interrupt_SneakAttack_Critical): "always" (both fire, the
# game's default), "crit" (only on a critical riposte), "never" (kept for the character's turn). The character's own
# turn always uses it.
SNEAK_POLICIES = ("always", "crit", "never")


# ------------------------------------------------------------------------------------------------------- dice maths
def d20_naturals(mode):
    """P(natural = n) for n = 1..20; mode "adv", "dis" or "straight"."""
    if mode == "adv":
        return [(n * n - (n - 1) * (n - 1)) / 400 for n in range(1, 21)]
    if mode == "dis":
        return [((21 - n) ** 2 - (20 - n) ** 2) / 400 for n in range(1, 21)]
    return [1 / 20] * 20


def net_mode(adv, dis):
    return "straight" if adv == dis else ("adv" if adv else "dis")


def attack_odds(bonus, ac, mode, crit_from=20, bonus_die=0, naturals=None):
    """(miss, hit that is not critical, critical) of one attack roll; bonus_die: a die added to the roll (Precision);
    naturals: measured ((roll mode, P(natural = 1..20)), ...), the uniform d20 for a mode not in it."""
    miss = hit = crit = 0.0
    for nat, p in enumerate(dict(naturals or ()).get(mode) or d20_naturals(mode), 1):
        if nat == 1:
            miss += p
        elif nat >= crit_from:
            crit += p
        else:
            if bonus_die:
                frac = sum(1 for k in range(1, bonus_die + 1) if nat + bonus + k >= ac) / bonus_die
            else:
                frac = 1.0 if nat + bonus >= ac else 0.0
            hit += p * frac
            miss += p * (1 - frac)
    return miss, hit, crit


def boss_save(P, ability):
    """The boss's save bonus for one ability ("STR", "CON", "WIS", ...)."""
    return dict(P.boss_saves).get(ability, P.boss_save)


def save_fails(bonus, dc):
    """P(d20 + bonus < dc): a saving throw with no natural-roll rule."""
    return min(1.0, max(0.0, sum(1 for r in range(1, 21) if r + bonus < dc) / 20))


def dice_moments(dice, times=1):
    """(mean, variance) of the sum of the dice (die sizes), each rolled `times` times."""
    m = sum((d + 1) / 2 for d in dice) * times
    v = sum((d * d - 1) / 12 for d in dice) * times
    return m, v


def landed(dice, flat, crit):
    """(mean, E[X^2]) of one landed attack's damage."""
    m, v = dice_moments(dice, 2 if crit else 1)
    m += flat
    return m, v + m * m


# --------------------------------------------------------------------------------------------- the character's numbers
@dataclass(frozen=True)
class Weapon:
    name: str
    bonus: int                      # attack roll bonus as the sheet shows it (Sharpshooter's -5 not in it)
    dice: tuple                     # die sizes of a landed hit (weapon, riders, elixir)
    flat: int                       # flat damage of a landed hit
    adv_flat: int = 0               # flat damage only with net Advantage (Crimson Mischief's Vicious)
    ranged: bool = False
    sneak: bool = True              # finesse or ammunition: Sneak Attack can ride on it


@dataclass(frozen=True)
class Profile:
    melee_main: Weapon
    melee_off: Weapon
    ranged_main: Weapon
    ranged_off: Weapon
    sharpshooter: tuple = (5, 10)   # (to-hit penalty, damage) of Sharpshooter's All In, None without the feat
    crit_from: int = 19
    adv: bool = True                # own Advantage on every attack roll (Risky Ring)
    sneak_dice: tuple = (6, 6)
    mark_die: int = 6               # Hunter's Mark, 0 = none
    dread_die: int = 8              # Dread Ambusher, 0 = none
    bonus_actions: int = 2          # Fast Hands
    attacks: int = 2                # attacks per attack action (Extra Attack)
    surge: bool = True
    sup_dice: int = 4
    sup_die: int = 8
    maneuver_dc: int = 16
    spell_dc: int = 14
    maneuvers: tuple = ("MenacingAttack", "TripAttack", "PrecisionAttack")
    pierce_melee: bool = True       # Piercing Strike (main-hand melee weapon action, once per rest)
    pierce_ranged: bool = True      # Piercing Shot (main-hand ranged weapon action, once per rest)
    gaping: int = 2                 # Gaping Wound damage per damaging attack
    ensnare: bool = True            # Ensnaring Strike known
    ensnare_die: int = 6
    riposte: Weapon = None          # the set's reaction attack when an enemy's melee attack misses
    riposte_sneak: str = "never"    # SNEAK_POLICIES: when the riposte may take Sneak Attack's charge
    riposte_ts: bool = False        # a riposte that hits puts True Strike on the boss (TRUE_STRIKE): the first attack
                                    # action of the character's next turn rolls without Sharpshooter's -5 (seen in
                                    # game: +16 / +14 in place of +11 / +9 on both rolls of that action, the +10 kept)
    boss_ac: int = 19
    boss_save: int = 4              # the boss's save bonus for an ability boss_saves leaves out
    boss_saves: tuple = (("CON", 6), ("STR", 6))  # ((ability, bonus), ...): the gauntlet's boss template is
                                    # proficient in Strength and Constitution saves (+2 on the forced +4)
    boss_atk: int = 9
    char_ac: int = 22
    conc_save: int = 8              # Constitution save bonus (concentration)
    conc_dc: int = 10               # the boss's hits (half damage in the gauntlet) stay below 20
    boss_first: float = 0.0         # P(the boss acts before the character in round 1)
    boss_odds: tuple = None         # measured ((roll mode, P(the boss's attack lands)), ...) in place of a uniform d20
    own_odds: tuple = None          # measured ((roll mode, P(natural = 1..20)), ...) of the character's own d20
    prone_closes: float = 0.5       # P(the boss, knocked Prone out of its reach after a leave, walks back and attacks)
    taken_hit: float = None         # damage the character takes per boss hit, and a critical hit's extra (the model's
    taken_crit: float = 0.0         # boss scenario: expect.boss taken_hit / taken_crit / taken_heal); None = not known
    taken_heal: float = 0.0


def _dice_flat(expr):
    """'1d6+6 Piercing + 1d4 Necrotic' -> ((6, 4), 6)."""
    dice = []
    for n, s in re.findall(r"(\d+)d(\d+)", expr or ""):
        dice += [int(s)] * int(n)
    flat = sum(int(x) for x in re.findall(r"\+(\d+)(?!\d*d)", expr or ""))
    return tuple(dice), flat


def _deal_flat(stats, passive):
    m = re.search(r"DealDamage\((\d+)\s*,", (stats.get(passive) or {}).get("StatsFunctors") or "")
    return int(m.group(1)) if m else 0


def _passives(stats, sid, hand):
    st = stats.get(sid) or {}
    out = []
    for key in ("PassivesOnEquip", "PassivesMainHand" if hand == "main" else "PassivesOffHand"):
        out += [p.strip() for p in (st.get(key) or "").split(";") if p.strip()]
    return out


def profile_from_spec(spec, stats):
    """The character's numbers from a plan.py spec (sheet rows, worn items, build passives) and the game stats."""
    rows = {r["slot"]: r for r in spec["expect"]["attacks"]}
    boosts = [b["boost"] for b in spec.get("item_boosts") or []]
    flat_all = sum(int(m) for b in boosts for m in re.findall(r"^CharacterWeaponDamage\((\d+)\)$", b))
    passives = set(spec.get("passives_add") or [])
    cl = spec.get("class_levels") or {}
    items = {it["slot"]: it["stats"] for it in spec["items"]}

    def weapon(slot, hand, ranged):
        r = rows[slot]
        dice, flat = _dice_flat(r["dmg"])
        sid = r["sid"]
        adv_flat = sum(_deal_flat(stats, p) for p in _passives(stats, sid, hand)
                       if "HasAdvantage()" in ((stats.get(p) or {}).get("Conditions") or "")
                       and "AttackedWithPassiveSourceWeapon" in ((stats.get(p) or {}).get("Conditions") or ""))
        return Weapon(r["n"], int(r["hit"]), dice, flat + flat_all, adv_flat, ranged)

    mm, mo = weapon("MainHand", "main", False), weapon("OffHand", "off", False)
    rm, ro = weapon("Ranged", "main", True), weapon("RangedOff", "off", True)
    riposte, riposte_ts = None, False
    off_sid = items.get("MeleeOffHand")
    for p in _passives(stats, off_sid, "off") if off_sid else []:
        for intr in re.findall(r"UnlockInterrupt\((\w+)\)", (stats.get(p) or {}).get("Boosts") or ""):
            props = (stats.get(intr) or {}).get("Properties") or ""
            if "IsMiss()" in ((stats.get(intr) or {}).get("Conditions") or "") and "UseSpell(" in props:
                riposte = mm
                m = re.search(r"UseSpell\(\w+,\s*(\w+)", props)
                success = ((stats.get(m.group(1)) or {}).get("SpellSuccess") or "") if m else ""
                riposte_ts = "ApplyStatus(TRUE_STRIKE," in success.replace(" ", "")
    ab = spec["sheet"]["abilities"]
    con = ab.get("CON", 10)
    for b in boosts:
        m = re.match(r"AbilityOverrideMinimum\(Constitution,\s*(\d+)", b)
        if m:
            con = max(con, int(m.group(1)))
    save_bonus = sum(int(x) for b in boosts for x in re.findall(r"^RollBonus\(SavingThrow,\s*(-?\d+)\)$", b))
    init = (ab.get("DEX", 10) - 10) // 2 + sum(int(x) for b in boosts for x in re.findall(r"^Initiative\((\d+)\)$", b))
    if "DreadAmbusher" in passives:
        init += 3
    E = spec.get("enemy") or {}
    char_ac, boss_atk = int(spec["expect"]["ac"]), int(E.get("atk", 9))
    odds = tuple(sorted(E["odds"].items())) if E.get("odds") else BOSS_ODDS.get((boss_atk, char_ac))
    own = spec.get("own_odds")
    own = tuple(sorted((m, shares(c)) for m, c in own.items())) if own else OWN_ODDS.get((boss_atk, char_ac))
    gear = spec["expect"].get("boss_gear") or spec["expect"].get("boss") or {}
    boss_init = 0
    first = sum(1 for a in range(1, 21) for b in range(1, 21) if b + boss_init > a + init) / 400 + \
        sum(1 for a in range(1, 21) for b in range(1, 21) if b + boss_init == a + init) / 800
    rogue, thief = cl.get("Rogue", 0), "Thief" in str((spec.get("subclasses") or {}).get("Rogue") or "")
    crit_red = sum(1 for b in boosts if b == "ReduceCriticalAttackThreshold(1)")
    wis = (ab.get("WIS", 10) - 10) // 2
    prof = int(spec["sheet"]["prof"])
    dex = (ab.get("DEX", 10) - 10) // 2
    sup = sum(int(r["n"]) for r in spec.get("resources") or [] if r["kind"] == "SuperiorityDie")
    maneuvers = tuple(p for p in ("MenacingAttack", "TripAttack", "PrecisionAttack") if p in passives)
    return Profile(
        melee_main=mm, melee_off=mo, ranged_main=rm, ranged_off=ro,
        sharpshooter=(5, 10) if "Sharpshooter_AllIn" in passives else None,
        crit_from=20 - crit_red, adv=any(b == "Advantage(AttackRoll)" for b in boosts),
        sneak_dice=(6,) * ((rogue + 1) // 2) if rogue else (),
        mark_die=6 if cl.get("Ranger", 0) >= 2 else 0, dread_die=8 if "DreadAmbusher" in passives else 0,
        bonus_actions=2 if (rogue >= 3 and thief) else 1, attacks=2 if "ExtraAttack" in passives else 1,
        surge=cl.get("Fighter", 0) >= 2, sup_dice=sup, sup_die=8, maneuver_dc=8 + prof + dex,
        spell_dc=8 + prof + wis, maneuvers=maneuvers,
        pierce_melee="Target_PiercingThrust" in ((stats.get(items.get("MeleeMainHand")) or {}).get("BoostsOnEquipMainHand") or ""),
        pierce_ranged="Projectile_PiercingShot" in ((stats.get(items.get("RangedMainHand")) or {}).get("BoostsOnEquipMainHand") or ""),
        ensnare=cl.get("Ranger", 0) >= 1, riposte=riposte, riposte_ts=riposte_ts,
        boss_ac=int(E.get("ac", 19)), boss_save=int(E.get("save", 4)),
        boss_saves=tuple(sorted((k, int(v)) for k, v in (E.get("saves") or {}).items())), boss_atk=boss_atk,
        char_ac=char_ac, boss_odds=odds, own_odds=own, conc_save=(con - 10) // 2 + save_bonus, boss_first=first,
        taken_hit=gear.get("taken_hit"), taken_crit=gear.get("taken_crit") or 0.0,
        taken_heal=gear.get("taken_heal") or 0.0,
        prone_closes=(float(E["prone_closes"]) if E.get("prone_closes") is not None
                      else PRONE_CLOSES[0] / PRONE_CLOSES[1]))


# ------------------------------------------------------------------------------------------------------- one turn
@dataclass(frozen=True)
class Attack:
    label: str
    weapon: Weapon
    mode: str                       # net roll: adv / dis / straight
    sharpshooter: bool = False
    extra_dice: tuple = ()          # Dread Ambusher's d8
    maneuver: str = None            # MenacingAttack / TripAttack: +superiority die on a hit, effect on a failed save
    precision: bool = False
    pierce: bool = False
    ensnare: bool = False
    if_no_ensnare: bool = False     # fired with the bonus action an Ensnaring Strike that missed left over
    true_strike: bool = False       # a roll of the turn's first attack action after a riposte hit: no Sharpshooter -5
    dis_any: bool = False           # Disadvantage on the roll, cancelled or not (a shot with the boss in reach)
    near: bool = False              # within 3 m of the boss: a Prone boss gives the roll Advantage (PRONE's boost)


@dataclass(frozen=True)
class Plan:
    mode: str                       # melee / leave / stand / free (shoot from out of reach)
    surge: bool = False
    mark: bool = False              # (re)cast Hunter's Mark first
    ensnare: bool = False
    pierce: bool = False
    maneuver: str = None
    n_maneuver: int = 0
    n_precision: int = 0
    dread: bool = False


def _choose_ss(P, w, mode, precision, extra_dice=()):
    """Sharpshooter on or off for one ranged attack: the higher expected damage of the landed hits (Sneak Attack and
    the mark leave the choice alone in practice: they add the same to both sides of nearly the same hit chance)."""
    if not (w.ranged and P.sharpshooter):
        return False
    pen, dmg = P.sharpshooter
    best = []
    for on in (False, True):
        miss, hit, crit = attack_odds(w.bonus - (pen if on else 0), P.boss_ac, mode, P.crit_from,
                                      P.sup_die if precision else 0, P.own_odds)
        flat = w.flat + (dmg if on else 0)
        best.append(hit * landed(w.dice + extra_dice, flat, False)[0] + crit * landed(w.dice + extra_dice, flat, True)[0])
    return best[1] > best[0]


def build_attacks(P, plan, state):
    """The turn's attack list in the order the plan casts them."""
    adjacent = state.adjacent
    melee = plan.mode == "melee"
    dis = (not melee) and adjacent and plan.mode == "stand"
    mode = net_mode(P.adv, dis)
    main = P.melee_main if melee else P.ranged_main
    off = P.melee_off if melee else P.ranged_off
    near = melee or (adjacent and plan.mode == "stand")
    out = []
    if plan.dread:
        out.append(Attack("Dread Ambusher", main, mode, extra_dice=(P.dread_die,), dis_any=dis, near=near))
    n_main = P.attacks * (2 if plan.surge else 1)
    kinds = []
    if plan.pierce:
        kinds.append(("pierce", None))
    if plan.ensnare:
        kinds.append(("ensnare", None))
    kinds += [("maneuver", plan.maneuver)] * plan.n_maneuver
    kinds += [("plain", None)] * (n_main - len(kinds))
    prec_left = plan.n_precision
    order = sorted(range(len(kinds)), key=lambda i: kinds[i][0] != "maneuver")
    prec = set()
    for i in order:
        if prec_left and kinds[i][0] in ("maneuver", "plain"):
            prec.add(i)
            prec_left -= 1
    for i, (kind, man) in enumerate(kinds):
        out.append(Attack(kind if kind != "maneuver" else man, main, mode, maneuver=man, precision=i in prec,
                          pierce=kind == "pierce", ensnare=kind == "ensnare", dis_any=dis, near=near))
    ba = P.bonus_actions - (1 if plan.mark else 0) - (1 if plan.mode == "leave" else 0)
    # only a plain attack fires the off-hand half: in game a toggled Menacing Attack or Piercing Strike fired none
    # (3 of 3) and left the bonus action unspent, so the halves are at most the plain attacks
    ba = min(ba, sum(1 for kind, _m in kinds if kind == "plain"))
    # the j-th half rides on the j-th plain attack; a Precision die on that attack adds to the half's roll too (in game
    # both rolls of a toggled attack carried their own d8)
    plain = [i for i, (kind, _m) in enumerate(kinds) if kind == "plain"]
    for j in range(max(0, ba)):
        out.append(Attack("off-hand", off, mode, precision=plain[j] in prec,
                          if_no_ensnare=plan.ensnare and j == ba - 1, dis_any=dis, near=near))
    if getattr(state, "ts", False):
        # True Strike on the boss: the first attack action rolls without Sharpshooter's -5, and so does its off-hand
        # half when it has one; a Piercing Shot or manoeuvre first fires no half, and in game the half on the later
        # plain attack then rolled with the -5
        first = next((i for i, a in enumerate(out) if a.label != "Dread Ambusher"), None)
        half = None
        if kinds and kinds[0][0] == "plain":
            half = next((i for i, a in enumerate(out) if a.label == "off-hand"), None)
        for i in (first, half):
            if i is not None:
                out[i] = replace(out[i], true_strike=True)
    return [replace(a, sharpshooter=bool(a.true_strike and a.weapon.ranged and P.sharpshooter) or
                    _choose_ss(P, a.weapon, a.mode, a.precision, a.extra_dice)) for a in out]


@dataclass(frozen=True)
class TurnStart:
    adjacent: bool
    conc: str                       # "" / "mark" / "ensnare" (the boss restrained)
    gaping: bool                    # Gaping Wound already on the boss (the fight search never starts a turn with it)
    sneak: bool = True              # Sneak Attack's charge is there (not spent on the riposte in the boss's turn)
    ts: bool = False                # True Strike on the boss from a riposte hit in the boss's turn


# the own turn's parts (run_turn with parts): attack rolls, landed rolls (critical ones in), critical hits, rolls with
# net Advantage, with net Disadvantage, with any Disadvantage, Sneak Attack's damage (its dice)
OWN_PARTS = ("attacks", "hits", "crits", "adv", "dis", "dis_any", "sneak")


def run_turn(P, plan, start, parts=False):
    """-> {(sneak_used, dice_hit, frightened, gaping_new, ensnare, prone): (p, E[D;branch], E[D^2;branch])}; ensnare 0
    none or missed, 1 hit and restrained, 2 hit and saved; prone: a Trip Attack knocked the boss Prone. parts: each
    value also carries E[X;branch] of OWN_PARTS."""
    q_man = save_fails(boss_save(P, "WIS"), P.maneuver_dc)
    q_trip = save_fails(boss_save(P, "STR"), P.maneuver_dc)
    q_gape = save_fails(boss_save(P, "CON"), P.maneuver_dc + 2)
    q_snare = save_fails(boss_save(P, "STR"), P.spell_dc)
    zero = (0.0,) * len(OWN_PARTS)
    states = {(not start.sneak, 0, False, False, 0, False): (1.0, 0.0, 0.0, zero)}
    marked0 = plan.mark or start.conc == "mark"
    for a in build_attacks(P, plan, start):
        nxt = {}

        def add(key, p, m1, m2, v):
            q = nxt.get(key, (0.0, 0.0, 0.0, zero))
            nxt[key] = (q[0] + p, q[1] + m1, q[2] + m2, tuple(x + y for x, y in zip(q[3], v)) if parts else zero)
        for key, (p, m1, m2, v) in states.items():
            sa, k, fr, gnew, ens, prone = key
            if a.if_no_ensnare and ens:
                add(key, p, m1, m2, v)
                continue
            w = a.weapon
            pen, ssd = P.sharpshooter if (a.sharpshooter and P.sharpshooter) else (0, 0)
            if a.true_strike:
                pen = 0
            mode = net_mode(True, a.dis_any) if (prone and a.near) else a.mode
            miss, hit, crit = attack_odds(w.bonus - pen, P.boss_ac, mode, P.crit_from,
                                          P.sup_die if a.precision else 0, P.own_odds)
            marked = marked0 and not ens
            dice = w.dice + a.extra_dice + ((P.mark_die,) if marked and P.mark_die else ()) + \
                ((P.sup_die,) if a.maneuver else ())
            gape = P.gaping if (start.gaping or gnew) else 0
            flat = w.flat + ssd + (w.adv_flat if mode == "adv" else 0) + gape
            roll = (1.0, 0.0, 0.0, float(mode == "adv"), float(mode == "dis"), float(a.dis_any or mode == "dis"), 0.0)

            def scaled(f, extra):
                # E[X;child] of the parts: the parent's share plus this roll's counts on the child's weight
                return tuple(x * f + p * f * y for x, y in zip(v, extra)) if parts else zero
            add(key, p * miss, m1 * miss, m2 * miss, scaled(miss, roll))
            sneak = P.sneak_dice and mode == "adv" and w.sneak and not sa
            for pr, is_crit in ((hit, False), (crit, True)):
                if not pr:
                    continue
                d = dice + (P.sneak_dice if sneak else ())
                # Sneak Attack's damage is a row of its own: the weapon's "on damage with Advantage" passive
                # (Crimson Mischief's Vicious: a second 7 after the Sneak Attack row, seen on every riposte) and
                # Gaping Wound's +2 (a second tick with the Sneak Attack row) land on it again
                mu, s2 = landed(d, flat + ((w.adv_flat + gape) if sneak else 0), is_crit)
                base = (p * pr, pr * (m1 + p * mu), pr * (m2 + 2 * m1 * mu + p * s2))
                sa_dice = dice_moments(P.sneak_dice, 2 if is_crit else 1)[0] if sneak else 0.0
                vb = scaled(pr, roll[:1] + (1.0, float(is_crit)) + roll[3:6] + (sa_dice,))
                k2 = k + (1 if a.maneuver else 0)
                sa2 = sa or bool(sneak)
                outs = [((sa2, k2, fr, gnew, ens, prone), 1.0)]
                if a.maneuver == "MenacingAttack":
                    outs = [((sa2, k2, True, gnew, ens, prone), q_man),
                            ((sa2, k2, fr, gnew, ens, prone), 1 - q_man)]
                elif a.maneuver == "TripAttack" and not prone:
                    outs = [((sa2, k2, fr, gnew, ens, True), q_trip), ((sa2, k2, fr, gnew, ens, False), 1 - q_trip)]
                elif a.pierce:
                    outs = [((sa2, k2, fr, True, ens, prone), q_gape), ((sa2, k2, fr, gnew, ens, prone), 1 - q_gape)]
                elif a.ensnare:
                    outs = [((sa2, k2, fr, gnew, 1, prone), q_snare), ((sa2, k2, fr, gnew, 2, prone), 1 - q_snare)]
                for kk, f in outs:
                    if f:
                        add(kk, base[0] * f, base[1] * f, base[2] * f, tuple(x * f for x in vb))
        states = nxt
    if parts:
        return states
    return {k: v[:3] for k, v in states.items()}


def boss_attack(P, mode):
    """(non-critical hit, critical hit) of one boss attack: the measured landing chance for this roll mode when the
    profile has one (critical hits kept at the uniform d20's share, the records being too few to tell), else the
    uniform d20."""
    _, h, c = attack_odds(P.boss_atk, P.char_ac, mode, 20)
    land = dict(P.boss_odds or ()).get(mode)
    return (land - c, c) if land is not None else (h, c)


def riposte_spends(P, crit):
    """Does the riposte take Sneak Attack's charge on a hit (crit: a critical hit), under the profile's policy."""
    return P.riposte_sneak == "always" or (crit and P.riposte_sneak == "crit")


# the boss turn's parts (boss_turn with parts): the riposte's attack rolls, landed rolls, critical hits, Sneak Attack's
# damage (its dice), and the boss's attack rolls, landed hits (critical ones in) and critical hits on the character
BOSS_PARTS = ("react_attacks", "react_hits", "react_crits", "react_sneak", "boss_attacks", "boss_hits", "boss_crits")


def boss_turn(P, conc, ends_adjacent, frightened, gaping, reach=True, parts=False, prone=False):
    """The boss's turn after ours -> [(p, E[R], E[R^2], conc after, adjacent at our next turn, Sneak Attack's charge at
    our next turn, True Strike on the boss at our next turn)], R = our damage in it (the riposte, the Ensnaring Strike
    tick). reach False: the boss is still at its start spot, so it only Dashes into reach, which takes its action
    (round 1, or held there since), Prone or not. prone: Trip Attack knocked it Prone; in reach it stands and attacks,
    out of its reach (after a leave) it walks back and attacks with P.prone_closes, else stays away. Sneak Attack's
    charge is always there in the boss's turn: it came back as ours ended. parts: each row also carries E[X;row] of
    BOSS_PARTS."""
    out = []
    none = (0.0,) * len(BOSS_PARTS)
    # (p, restrained, the tick's E[T], E[T^2], stays where it stood up)
    branches = [(1.0, conc == "ensnare", 0.0, 0.0, False)]
    if conc == "ensnare":
        esc = 1 - save_fails(boss_save(P, "STR"), P.spell_dc)
        tm, tv = dice_moments((P.ensnare_die,))
        branches = [(esc, False, 0.0, 0.0, False), (1 - esc, True, tm, tv + tm * tm, False)]
    if prone and reach and not ends_adjacent:
        branches = [(pb * f, held, dm, d2, stays) for pb, held, dm, d2, _ in branches
                    for f, stays in ((1 - P.prone_closes, True), (P.prone_closes, False)) if f]
    for pb, held, dm, d2, stays in branches:
        conc_b = conc if (conc != "ensnare" or held) else ""
        moves = not frightened and not held and not stays
        if not (ends_adjacent or moves):
            out.append((pb, pb * dm, pb * d2, conc_b, False, True, False) + ((none,) if parts else ()))
            continue
        if not reach:
            out.append((pb, pb * dm, pb * d2, conc_b, True, True, False) + ((none,) if parts else ()))
            continue
        h, c = boss_attack(P, "dis" if (frightened or held) else "straight")
        ph = h + c
        brk = ph * save_fails(P.conc_save, P.conc_dc)
        # (p, E[R | row], E[R^2 | row], conc, charge kept, True Strike, parts | row); the boss's hit rows carry its
        # critical share (c / ph of them)
        boss_hit = (0.0, 0.0, 0.0, 0.0, 1.0, 1.0, c / ph if ph else 0.0)
        rows = [(brk, 0.0, 0.0, "", True, False, boss_hit), (ph - brk, 0.0, 0.0, conc_b, True, False, boss_hit)]
        if P.riposte:
            w = P.riposte
            rmode = net_mode(P.adv or held, False)
            miss, hit, crit = attack_odds(w.bonus, P.boss_ac, rmode, P.crit_from, naturals=P.own_odds)
            dice = w.dice + ((P.mark_die,) if conc_b == "mark" and P.mark_die else ())
            flat = w.flat + (w.adv_flat if rmode == "adv" else 0) + (P.gaping if gaping else 0)
            can_sneak = bool(P.sneak_dice) and rmode == "adv" and w.sneak
            rows.append(((1 - ph) * miss, 0.0, 0.0, conc_b, True, False, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
            for pr, is_crit in ((hit, False), (crit, True)):
                spend = can_sneak and riposte_spends(P, is_crit)
                m_, v_ = landed(dice + (P.sneak_dice if spend else ()),
                                flat + ((w.adv_flat + (P.gaping if gaping else 0)) if spend else 0), is_crit)
                sa_dice = dice_moments(P.sneak_dice, 2 if is_crit else 1)[0] if spend else 0.0
                rows.append(((1 - ph) * pr, m_, v_, conc_b, not spend, P.riposte_ts,
                             (1.0, 1.0, float(is_crit), sa_dice, 1.0, 0.0, 0.0)))
        else:
            rows.append((1 - ph, 0.0, 0.0, conc_b, True, False, (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)))
        for pr, rm, rs, cc, keep, ts, x in rows:
            # boss damage R (riposte) and the tick (dm) are independent: E[(T+R)^2] = E[T^2] + 2E[T]E[R] + E[R^2]
            row = (pb * pr, pb * pr * (dm + rm), pb * pr * (d2 + 2 * dm * rm + rs), cc, True, keep, ts)
            out.append(row + ((tuple(pb * pr * y for y in x),) if parts else ()))
    return out


# ------------------------------------------------------------------------------------------------------ the fight
# what Search.fight_parts sums over the fight: the own turn's parts, its damage, the boss turn's parts, our damage in it
FIGHT_PARTS = OWN_PARTS + ("own_dmg",) + BOSS_PARTS + ("react_dmg",)
# the boss stands this far from the character as the fight starts (round 1: out of its reach, a walk-up to melee);
# plan.py writes it into the spec for the harness's arena layout
BOSS_START_M = 10.0
# The boss's measured landing chances, by (attack bonus, the character's AC): the gauntlet's records with a row for
# every boss attack roll pooled (20 fights). Straight rolls landed 73 of 136 and Disadvantage rolls 19 of 51 at +9
# against AC 22, where a uniform d20 gives 40% and 16% (the game's dice were high for the boss, not for the character).
# A spec's enemy "odds" ({mode: chance}) overrides it; any other bonus or AC keeps the uniform d20.
BOSS_ODDS = {(9, 22): (("straight", 73 / 136), ("dis", 19 / 51))}


def shares(counts):
    """Counts (or chances) of the faces 1..20 -> chances that sum to 1."""
    total = sum(counts)
    return tuple(c / total for c in counts)


# The character's measured d20, by the same (boss attack bonus, character AC) as BOSS_ODDS: the gauntlet's own attack
# rolls at net Advantage in every record without a roll edit (50 fights, rows of one roll counted once), 1234 rolls.
# "adv" is the higher die per face 1..20: 197 at 19-20 (16.0%, a uniform pair gives 19.0%) and 34 at 1-4 (2.8%, uniform
# 4.0%). "straight" is one die's faces, both dice of each of those rolls (2468 dice): the game resolves a roll with
# Advantage and Disadvantage on one of its two d20, kept without regard to its value (a stand run's 56 such rolls:
# every outcome followed the kept die, 42 hits and 5 critical hits against 38.5 and 4.58 under these faces).
# Disadvantage and any other bonus or AC keep the uniform d20; a spec's "own_odds" ({mode: 20 counts or chances})
# overrides it.
OWN_ODDS = {(9, 22): (
    ("adv", shares((3, 6, 8, 17, 29, 33, 37, 54, 54, 69, 80, 68, 101, 104, 73, 94, 100, 107, 96, 101))),
    ("straight", shares((103, 111, 115, 123, 114, 139, 134, 135, 129, 142, 136, 125, 151, 156, 99, 113, 117, 124,
                         100, 102))))}
# What the boss did in its turn after a Trip Attack knocked it Prone out of its reach (after a leave), as (walked back
# and attacked, all such turns) in the gauntlet's records: once each way (a 4.4 m leave: it stood up, walked in and
# attacked; a 5.1 m leave: it stood up and ended its turn). Standing up costs half its Movement and no AI_HELPER_PRONE
# was ever logged on it, so the distance left to walk decides; the model does not know it and takes the share. It
# never Dashed in from a leave spot; from its start spot it Dashes in, Prone or not (Search: far). A spec's enemy
# "prone_closes" overrides it.
PRONE_CLOSES = (1, 2)
FAMILIES = {
    # mode allowed with the boss in reach / out of reach, the options the family may use, and the harness's plan mode
    "melee": dict(adjacent=("melee",), away=("melee", "free"), ensnare=False, mode="melee",
                  why="fight in melee once the boss is in reach (Crimson Mischief + Blade of the First Blood)"),
    "melee_open": dict(adjacent=("melee",), away=("melee",), ensnare=False, mode="melee",
                       why="as melee, and walk up to the boss in round 1 too (Dread Ambusher in melee)"),
    "evade": dict(adjacent=("leave",), away=("free",), ensnare=False,
                  why="Cunning Action Disengage + step out of reach every turn the boss is in reach, then shoot; "
                      "Menacing Attack may keep the boss Frightened (it cannot move) and out of reach"),
    "evade_nohold": dict(adjacent=("leave",), away=("free",), ensnare=False, maneuvers=("TripAttack",
                                                                                         "PrecisionAttack"),
                         why="as evade, superiority dice only for Trip Attack and Precision: the boss walks back "
                             "into reach unless Trip Attack knocked it Prone"),
    "evade_ensnare": dict(adjacent=("leave",), away=("free",), ensnare=True,
                          why="as evade, with Ensnaring Strike (Ranged) to hold the boss out of reach"),
    "stand": dict(adjacent=("stand",), away=("free",), ensnare=False,
                  why="stand and shoot with the boss in reach (Advantage and Disadvantage cancel)"),
    "any": dict(adjacent=("melee", "leave", "stand"), away=("melee", "free"), ensnare=True, mode="melee",
                why="every option open each turn"),
}


@dataclass(frozen=True)
class State:
    rnd: int
    adjacent: bool
    dice: int
    surge: bool
    conc: str
    pierce_m: bool
    pierce_r: bool
    dread: bool
    boss_after: bool                # the boss's turn follows this one (false for the last turn: the gauntlet ends there)
    sneak: bool = True              # Sneak Attack's charge at the turn's start
    ts: bool = False                # True Strike on the boss at the turn's start
    far: bool = False               # the boss is still at its start spot (out of reach): it can only Dash in


def plans(P, s, fam):
    F = FAMILIES[fam]
    modes = F["adjacent"] if s.adjacent else F["away"]
    allowed = F.get("maneuvers") or P.maneuvers
    kinds = [m for m in ("MenacingAttack", "TripAttack") if m in P.maneuvers and m in allowed]
    for mode in modes:
        melee = mode == "melee"
        for surge in ((False, True) if s.surge else (False,)):
            n_main = P.attacks * (2 if surge else 1)
            for mark in ((False, True) if (P.mark_die and s.conc != "mark") else (False,)):
                ba = P.bonus_actions - mark - (mode == "leave")
                for ens in ((False, True) if (F["ensnare"] and P.ensnare and ba >= 1) else (False,)):
                    if ens and mark:
                        continue
                    can_p = s.pierce_m if melee else s.pierce_r
                    for pierce in ((False, True) if can_p else (False,)):
                        slots = n_main - pierce - ens
                        for kind in kinds or [None]:
                            for nm in range(0, min(s.dice, slots) + 1 if kind else 1):
                                if nm == 0 and kind != (kinds or [None])[0]:
                                    continue
                                prec_max = s.dice - nm if "PrecisionAttack" in P.maneuvers and                                     "PrecisionAttack" in allowed else 0
                                for npr in range(0, min(prec_max, n_main) + 1):
                                    yield Plan(mode, surge, mark, ens, pierce, kind if nm else None, nm, npr,
                                               s.dread)


# Expected totals closer than this are a tie: such gaps are float noise or modelling detail, and deciding them by the
# raw numbers lets any unrelated model change flip the published policy for no real gain.
TIE = 0.01


def spend(plan):
    """The order tied plans are chosen in: fewer superiority dice, then Action Surge now rather than later; still tied,
    the first plans() yields."""
    return plan.n_maneuver + plan.n_precision, not plan.surge


@functools.lru_cache(maxsize=None)
def _turn_cached(P, plan, start):
    return run_turn(P, plan, start)


class Search:
    """The best policy of one family: V(state) = E[this turn + boss turn + V(next)] of its best plan, the plans
    within TIE of the largest being tied and chosen by spend."""

    def __init__(self, P, fam, last_boss_turn=False):
        self.P, self.fam, self.last = P, fam, last_boss_turn
        self.memo = {}

    def value(self, s):
        """-> (E[total], E[total^2], best plan)."""
        if s is None:
            return 0.0, 0.0, None
        if s in self.memo:
            return self.memo[s]
        cands = []
        for plan in plans(self.P, s, self.fam):
            e1 = e2 = 0.0
            for p, m1, m2, nx in self._branches(s, plan):
                v1, v2, _ = self.value(nx)
                e1 += m1 + p * v1
                e2 += m2 + 2 * m1 * v1 + p * v2
            cands.append((e1, e2, plan))
        best = None
        if cands:
            top = max(c[0] for c in cands)
            best = min((c for c in cands if c[0] >= top - TIE), key=lambda c: spend(c[2]))
        self.memo[s] = best
        return best

    def _branches(self, s, plan, parts=False):
        """-> [(p, E[D;branch], E[D^2;branch], next state)], D = this turn's damage and the boss turn's after it; parts:
        each branch also carries E[X;branch] of FIGHT_PARTS."""
        start = TurnStart(s.adjacent, s.conc, False, s.sneak, s.ts)
        res = run_turn(self.P, plan, start, parts=True) if parts else _turn_cached(self.P, plan, start)
        out = []
        for (sa, k, fr, gnew, ens, prone), val in res.items():
            p, m1, m2 = val[:3]
            if p <= 0:
                continue
            own = (val[3] + (m1,)) if parts else ()
            conc = "mark" if plan.mark else s.conc
            if ens == 1:
                conc = "ensnare"
            elif ens == 2:
                conc = ""
            # Gaping Wound covers the rest of its turn and the boss's turn: in game it ends as the character's next
            # turn starts
            nx = dict(rnd=s.rnd + 1, dice=s.dice - plan.n_precision - k, surge=s.surge and not plan.surge,
                      pierce_m=s.pierce_m and not (plan.pierce and plan.mode == "melee"),
                      pierce_r=s.pierce_r and not (plan.pierce and plan.mode != "melee"), dread=False)
            last = s.rnd >= ROUNDS
            if not s.boss_after:
                out.append((p, m1, m2, None) + ((own + (0.0,) * (len(BOSS_PARTS) + 1),) if parts else ()))
                continue
            # the boss at its start spot is too far away to reach the character and attack in one turn, unless the
            # character walked up to it; it stays there only while held
            ends_adjacent = plan.mode in ("melee", "stand")
            reach = not (s.far and not ends_adjacent)
            for row in boss_turn(self.P, conc, ends_adjacent, fr, gnew, reach, parts=parts, prone=prone):
                pb, rm, rs, cc, adj, keep, ts = row[:7]
                nxt = None if last else State(adjacent=adj, conc=cc,
                                              boss_after=(s.rnd + 1 < ROUNDS) or self.last, sneak=keep, ts=ts,
                                              far=s.far and not adj, **nx)
                br = (p * pb, m1 * pb + p * rm, m2 * pb + 2 * m1 * rm + p * rs, nxt)
                if parts:
                    br += (tuple(x * pb for x in own) + tuple(p * y for y in row[7]) + (p * rm,),)
                out.append(br)
        return out

    def start_state(self):
        P = self.P
        return State(rnd=1, adjacent=False, dice=P.sup_dice, surge=P.surge, conc="",
                     pierce_m=P.pierce_melee, pierce_r=P.pierce_ranged, dread=bool(P.dread_die), boss_after=True,
                     far=True)

    def total(self):
        """-> (E[total], sd) over who acts first: we do (the boss walks up after our turn), or the boss does (it walks
        up from too far away to attack, so our first turn starts in its reach). Either way the fight ends as our 16th
        turn ends (the gauntlet does not wait for the boss's turn after it)."""
        P = self.P
        v1, v2, _ = self.value(self.start_state())
        e1, e2 = (1 - P.boss_first) * v1, (1 - P.boss_first) * v2
        if P.boss_first:
            w1, w2, _ = self.value(replace(self.start_state(), adjacent=True, far=False))
            e1 += P.boss_first * w1
            e2 += P.boss_first * w2
        return e1, max(0.0, e2 - e1 * e1) ** 0.5

    def path(self, s=None):
        """The policy along the most likely course of the fight: [(state, plan, E[turn + boss turn], sd)]."""
        s = s or self.start_state()
        out = []
        while s is not None:
            _, _, plan = self.value(s)
            br = self._branches(s, plan)
            p_all = sum(b[0] for b in br)
            m = sum(b[1] for b in br) / p_all
            m2 = sum(b[2] for b in br) / p_all
            out.append((s, plan, m, max(0.0, m2 - m * m) ** 0.5))
            groups = {}
            for p, _m1, _m2, nx in br:
                groups[nx] = groups.get(nx, 0.0) + p
            s = max(groups.items(), key=lambda kv: kv[1])[0] if groups else None
        return out

    def fight_parts(self):
        """The chosen policy's expectations over the whole fight, exact (every course weighed, not the most likely
        one), the two starts mixed as total() mixes them: {"sums": {FIGHT_PARTS name: E[sum over the fight]},
        "rounds": [(E[D_r], sd D_r)]}, D_r = round r's damage (our turn and the boss's turn after it)."""
        P = self.P
        dist = {self.start_state(): 1 - P.boss_first}
        if P.boss_first:
            s2 = replace(self.start_state(), adjacent=True, far=False)
            dist[s2] = dist.get(s2, 0.0) + P.boss_first
        sums = [0.0] * len(FIGHT_PARTS)
        rounds = []
        while dist:
            nxt, e1, e2 = {}, 0.0, 0.0
            for s, w in dist.items():
                if w <= 0:
                    continue
                _, _, plan = self.value(s)
                for p, m1, m2, nx, vec in self._branches(s, plan, parts=True):
                    e1 += w * m1
                    e2 += w * m2
                    for i, x in enumerate(vec):
                        sums[i] += w * x
                    if nx is not None:
                        nxt[nx] = nxt.get(nx, 0.0) + w * p
            rounds.append((e1, max(0.0, e2 - e1 * e1) ** 0.5))
            dist = nxt
        return {"sums": dict(zip(FIGHT_PARTS, sums)), "rounds": rounds}


def turn_numbers(P, plan, start):
    """(E[D], sd) of our own turn alone (no boss turn)."""
    res = run_turn(P, plan, start)
    p = sum(v[0] for v in res.values())
    m = sum(v[1] for v in res.values()) / p
    m2 = sum(v[2] for v in res.values()) / p
    return m, max(0.0, m2 - m * m) ** 0.5


def ss_off_band(P, w, mode, lo=-5, hi=30):
    """The sheet attack bonuses (Sharpshooter not applied) at which All In loses damage for this weapon and roll
    against the boss's AC: [] = keep it on. Not one threshold: when only critical hits land, +10 always pays."""
    if not P.sharpshooter:
        return []
    return [b for b in range(lo, hi + 1) if not _choose_ss(P, replace(w, bonus=b), mode, False)]


def describe(plan):
    bits = {"melee": "melee", "leave": "Disengage + leave, shoot", "stand": "stand and shoot", "free": "shoot"}
    out = [bits[plan.mode]]
    if plan.dread:
        out.append("Dread Ambusher")
    if plan.mark:
        out.append("Hunter's Mark")
    if plan.surge:
        out.append("Action Surge")
    if plan.pierce:
        out.append("Piercing Strike" if plan.mode == "melee" else "Piercing Shot")
    if plan.ensnare:
        out.append("Ensnaring Strike")
    if plan.n_maneuver:
        out.append("%d x %s" % (plan.n_maneuver, plan.maneuver.replace("Attack", "")))
    if plan.n_precision:
        out.append("%d x Precision" % plan.n_precision)
    return ", ".join(out)


def sneak_policies(P):
    """The reaction policies worth comparing: all of SNEAK_POLICIES when the riposte can take Sneak Attack, else the
    profile's own."""
    return SNEAK_POLICIES if (P.riposte and P.sneak_dice and P.adv) else (P.riposte_sneak,)


def best_search(P, fam, policy=None):
    """-> (Search, E[total], sd, {policy: E[total]}) of the family under the given reaction policy, or under the one of
    sneak_policies with the largest expected total (ties within TIE: the earlier one)."""
    runs, totals = [], {}
    for pol in ((policy,) if policy else sneak_policies(P)):
        S = Search(replace(P, riposte_sneak=pol), fam)
        tot, sd = S.total()
        totals[pol] = tot
        runs.append((S, tot, sd))
    top = max(r[1] for r in runs)
    return next(r for r in runs if r[1] >= top - TIE) + (totals,)


def fight_expect(S):
    """The policy's numbers per round as the gear model gives them for the gauntlet's boss fight (plan.py's expect.boss,
    model.attack_parts' names and rounding), exact over every course of the fight: per round over the 16 the own turn's
    attack rolls, landed rolls, critical hits, their rates, the shares of rolls with net Advantage / Disadvantage / any
    Disadvantage, damage per landed roll with and without Sneak Attack (its dice), Sneak Attack's damage, the own turn's
    damage; the reactions' (the riposte in the boss's turn) rolls, landed rolls, critical hits, damage and Sneak Attack;
    damage per round in all and damage taken per round (the boss's hits, None when the spec does not give its damage);
    plus the fight's total and sd and each round's mean and sd."""
    P = S.P
    fp = S.fight_parts()
    t = {k: v / ROUNDS for k, v in fp["sums"].items()}
    att, hits = t["attacks"], t["hits"]
    tot, sd = S.total()

    def r(x, n):
        return round(x, n) if x is not None else None
    taken = None
    if P.taken_hit is not None:
        raw = t["boss_hits"] * P.taken_hit + t["boss_crits"] * P.taken_crit
        taken = max(0.5 * raw, raw - P.taken_heal)
    return {"split": True, "dpr": r(t["own_dmg"] + t["react_dmg"], 2), "taken": r(taken, 3),
            "attacks": r(att, 3), "hits": r(hits, 3), "crits": r(t["crits"], 3),
            "hit_rate": r(hits / att, 4) if att else None, "crit_rate": r(t["crits"] / att, 4) if att else None,
            "adv_rate": r(t["adv"] / att, 4) if att else None, "dis_rate": r(t["dis"] / att, 4) if att else None,
            "dis_any_rate": r(t["dis_any"] / att, 4) if att else None,
            "dmg_per_hit": r(t["own_dmg"] / hits, 2) if hits else None,
            "dmg_per_hit_no_sneak": r((t["own_dmg"] - t["sneak"]) / hits, 2) if hits else None,
            "sneak": r(t["sneak"], 2), "own_dpr": r(t["own_dmg"], 2), "react_attacks": r(t["react_attacks"], 3),
            "react_hits": r(t["react_hits"], 3), "react_crits": r(t["react_crits"], 3),
            "react_dmg": r(t["react_dmg"], 2), "react_sneak": r(t["react_sneak"], 2),
            "boss_attacks": r(t["boss_attacks"], 3), "boss_hits": r(t["boss_hits"], 3),
            "sneak_policy": P.riposte_sneak, "total": r(tot, 1), "sd": r(sd, 1),
            "rounds": [{"round": i + 1, "dmg": r(m, 1), "sd": r(d, 1)} for i, (m, d) in enumerate(fp["rounds"])]}


def enemy_turn_reactions(policy):
    """The plan's Sneak Attack answers for the enemies' turns (the gauntlet's plan.reactions_enemy_turn)."""
    return {"Interrupt_SneakAttack": "auto" if policy == "always" else "never",
            "Interrupt_SneakAttack_Critical": "auto" if policy in ("always", "crit") else "never"}


def rank(P, families=None, policy=None):
    """-> [{family, why, total, sd, dpr, sneak_policy, policies, rounds: [{round, mean, sd}], path: [{round, plan, text,
    mean, sd}]}], best first. rounds: each round's expectation over every course; path: the most likely course, its mean
    being that course's round only. Each family under its best reaction policy (best_search), or under the one given."""
    out = []
    for fam in families or [f for f in FAMILIES if f != "any"]:
        S, tot, sd, totals = best_search(P, fam, policy)
        path = S.path()
        out.append({"family": fam, "why": FAMILIES[fam]["why"], "total": tot, "sd": sd, "dpr": tot / ROUNDS,
                    "sneak_policy": S.P.riposte_sneak, "policies": totals,
                    "rounds": [{"round": i + 1, "mean": m, "sd": d}
                               for i, (m, d) in enumerate(S.fight_parts()["rounds"])],
                    "path": [{"round": s.rnd, "adjacent": s.adjacent, "plan": plan, "text": describe(plan),
                              "mean": m, "sd": d} for s, plan, m, d in path]})
    out.sort(key=lambda r: -r["total"])
    return out


# --------------------------------------------------------------------------------------- harness plan (tools/gauntlet)
def plan_steps(plan, A, evade_steps, evade_every_round=False):
    """One turn's plan (Plan) as the gauntlet's step list (plan.py step dicts). A and evade_steps are plan.py's step
    builders; steps that may not be affordable carry the plain attack as their alt. evade_every_round: the Disengage
    steps also in a turn that shoots from out of reach (they skip themselves while the boss is out of reach)."""
    melee = plan.mode == "melee"
    spell = "Target_MainHandAttack" if melee else "Projectile_MainHandAttack"
    steps = []
    if plan.mode == "leave" or (plan.mode == "free" and evade_every_round):
        steps += evade_steps(False)
    if plan.mark:
        steps.append(A("Target_HuntersMark", "bonus", "@boss", "Hunter's Mark (before the attacks)"))
    if plan.dread:
        steps.append(A("Target_DreadAmbusher" if melee else "Projectile_DreadAmbusher", "free", "@boss",
                       "Dread Ambusher attack", granted_by="DREAD_AMBUSHER"))
    if plan.surge:
        steps.append(A("Shout_ActionSurge", "free", "@self", "Action Surge", per="short"))
    kinds = []
    if plan.pierce:
        kinds.append(("Target_PiercingThrust" if melee else "Projectile_PiercingShot", "piercing (once per rest)"))
    if plan.ensnare:
        kinds.append(("Projectile_EnsnaringStrike", "Ensnaring Strike"))
    prefix = "Target_" if melee else "Projectile_"
    if plan.n_maneuver:
        kinds += [(prefix + plan.maneuver, "manoeuvre (superiority die on a hit)")] * plan.n_maneuver
    n_main = 2 * (2 if plan.surge else 1)
    kinds += [(spell, None)] * (n_main - len(kinds))
    order = sorted((i for i, k in enumerate(kinds) if "piercing" not in (k[1] or "") and k[1] != "Ensnaring Strike"),
                   key=lambda i: kinds[i][0] == spell)
    prec = set(order[:plan.n_precision])
    for i, (sp, why) in enumerate(kinds):
        group, req, base_why = ("action", None, "attack") if i == 0 else \
            ("free", "action", "Extra Attack") if i == 1 else \
            ("action" if i == 2 else "free", "surge", "Action Surge attack")   # the surge's first spends its action
        if i in prec:
            steps.append(A("Shout_PrecisionAttack", "free", "@self", "Precision Attack (superiority die)",
                           cost="SuperiorityDie:1"))
        kw = {"requires": req} if req else {}
        plain = A(spell, group, "@boss", base_why, **kw)
        if sp == spell:
            steps.append(plain)
            continue
        # a manoeuvre's die is its HitCosts: spent only when the attack hits, so it is no use cost of the step
        if "manoeuvre" in why:
            kw["hit_cost"] = "SuperiorityDie:1"
        if group == "action":
            kw["cost"] = "ActionPoint:1"
        steps.append(A(sp, group, "@boss", why, alt=plain, **kw))
    return steps


def harness_rounds(path, A, evade_steps, evade_every_round=False):
    """The family's policy along its most likely course as the gauntlet's round plan (plan_steps per round)."""
    return [plan_steps(row["plan"], A, evade_steps, evade_every_round) for row in path]


# The state the harness reads as its turn starts, as the policy table's key: round, boss in reach, superiority dice,
# Action Surge ready, concentration, Piercing Strike / Shot ready, Dread Ambusher's attack,
# Sneak Attack's charge, True Strike from a riposte hit in the boss's turn just before, the boss still at its start
# spot. tools/gauntlet/gauntlet.lua (G.policyKey) builds the same text.
POLICY_FIELDS = ("rnd", "adjacent", "dice", "surge", "conc", "pierce_m", "pierce_r", "dread", "sneak", "ts", "far")


def state_key(s):
    def v(x):
        if isinstance(x, bool):
            return "1" if x else "0"
        return str(x) if x != "" else "none"
    return "|".join("%s=%s" % (f, v(getattr(s, f))) for f in POLICY_FIELDS)


def parse_state_key(key, last_boss_turn=False):
    """The State of a policy table key (state_key's text); KeyError / ValueError for a malformed one."""
    kv = dict(part.split("=", 1) for part in key.split("|"))
    b = {f: kv[f] == "1" for f in POLICY_FIELDS if f not in ("rnd", "dice", "conc")}
    rnd = int(kv["rnd"])
    return State(rnd=rnd, dice=int(kv["dice"]), conc="" if kv["conc"] == "none" else kv["conc"],
                 boss_after=rnd < ROUNDS or last_boss_turn, **b)


def state_numbers(S, s):
    """The policy in one state: its decision, and the expectation of the own turn alone and of the round (the own turn
    and the boss's turn after it; none after the last turn) as (mean, sd)."""
    _, _, plan = S.value(s)
    own = turn_numbers(S.P, plan, TurnStart(s.adjacent, s.conc, False, s.sneak, s.ts))
    br = S._branches(s, plan)
    p_all = sum(b[0] for b in br)
    m = sum(b[1] for b in br) / p_all
    m2 = sum(b[2] for b in br) / p_all
    return {"plan": plan, "own": own, "round": (m, max(0.0, m2 - m * m) ** 0.5)}


def reachable(S):
    """{state: probability} of every state the chosen policy reaches, both starts mixed as total() mixes them."""
    P = S.P
    dist = {S.start_state(): 1 - P.boss_first}
    if P.boss_first:
        s2 = replace(S.start_state(), adjacent=True, far=False)
        dist[s2] = dist.get(s2, 0.0) + P.boss_first
    out = {}
    while dist:
        nxt = {}
        for s, w in dist.items():
            if w <= 0:
                continue
            out[s] = out.get(s, 0.0) + w
            _, _, plan = S.value(s)
            for p, _m1, _m2, nx in S._branches(s, plan):
                if nx is not None:
                    nxt[nx] = nxt.get(nx, 0.0) + w * p
        dist = nxt
    return out


def policy_table(S, A, evade_steps, evade_every_round=False):
    """The policy as the harness follows it: for every state the policy reaches, its decision and the expectation in that
    state (state_numbers). -> {"fields", "rounds", "has", "decisions": [{text, steps}], "states": {state_key: {d, p,
    own, own_sd, round, round_sd}}}; d indexes decisions, p is the chance of reaching the state. has: what the character
    can hold at all; a field it cannot hold is constant in the table (no Action Surge, no Piercing Strike, ...)."""
    P = S.P
    decisions, index, states = [], {}, {}
    for s, w in sorted(reachable(S).items(), key=lambda kv: state_key(kv[0])):
        n = state_numbers(S, s)
        plan = n["plan"]
        if plan not in index:
            index[plan] = len(decisions)
            decisions.append({"text": describe(plan), "steps": plan_steps(plan, A, evade_steps, evade_every_round)})
        states[state_key(s)] = {"d": index[plan], "p": round(w, 6), "own": round(n["own"][0], 2),
                                "own_sd": round(n["own"][1], 2), "round": round(n["round"][0], 2),
                                "round_sd": round(n["round"][1], 2)}
    return {"fields": list(POLICY_FIELDS), "rounds": ROUNDS,
            "has": {"surge": P.surge, "pierce_m": P.pierce_melee, "pierce_r": P.pierce_ranged,
                    "dread": bool(P.dread_die), "sneak": bool(P.sneak_dice), "ts": bool(P.riposte and P.riposte_ts)},
            "decisions": decisions, "states": states}


def apply_to_spec(spec, P, family, A, evade_steps):
    """The spec with the family's policy and its predicted numbers: plan.policy = the decision in every state the policy
    reaches (policy_table), which the harness follows turn by turn in the state it finds; plan.rounds = the decisions
    along the most likely course (the forecast's, and the plan of a harness that has no policy table);
    expect.boss = the policy's per-round parts (fight_expect), the ones the report compares the runs with, the gear
    model's own kept as expect.boss_gear; expect.strategy = the same with per round the expectation over every course
    ("mean", and "dmg" the same) and the most likely course's ("likely", its decision "text"). plan.mode follows the
    family (melee or ranged) and plan.boss_distance is the search's starting distance (BOSS_START_M). The riposte
    reaction is set to fire when the profile counts it, and Sneak Attack's answers in the enemies' turns follow the
    family's best reaction policy (best_search)."""
    S, tot, sd, totals = best_search(P, family)
    path = [{"round": s.rnd, "adjacent": s.adjacent, "plan": plan, "text": describe(plan), "mean": m, "sd": d}
            for s, plan, m, d in S.path()]
    fe = fight_expect(S)
    out = json.loads(json.dumps(spec, default=str))
    plan = out["plan"]
    every = "leave" in FAMILIES[family]["adjacent"]
    plan["rounds"] = harness_rounds(path, A, evade_steps, every)
    plan["steady"] = list(plan["rounds"][-1])
    plan["fight_rounds"] = ROUNDS
    plan["strategy"] = family
    plan["mode"] = FAMILIES[family].get("mode", "ranged")
    plan["boss_distance"] = BOSS_START_M
    plan["policy"] = policy_table(S, A, evade_steps, every)
    if P.riposte:
        plan.setdefault("reactions", {})["Interrupt_TheClover_TrueStrike_Riposte"] = "auto"
    if len(sneak_policies(P)) > 1:
        plan["reactions_enemy_turn"] = enemy_turn_reactions(S.P.riposte_sneak)
    ex = out["expect"]
    gear = ex.get("boss_gear") or ex.get("boss") or {}
    ex["boss_gear"] = gear
    parts = {k: v for k, v in fe.items() if k not in ("rounds", "total", "sd")}
    boss = dict(parts, source="strategy " + family)
    for k in ("taken_hit", "taken_crit", "taken_heal"):
        if k in gear:
            boss[k] = gear[k]
    if boss.get("taken") and gear.get("taken") and gear.get("R"):
        # rounds survived: the same hit points over the policy's damage taken
        boss["R"] = round(gear["R"] * gear["taken"] / boss["taken"], 2)
    ex["boss"] = boss
    ex["strategy"] = dict(parts, family=family, why=FAMILIES[family]["why"], total=round(tot, 1), sd=round(sd, 1),
                          dpr=round(tot / ROUNDS, 2), policies={k: round(v, 1) for k, v in totals.items()},
                          round_basis={"mean": "expectation over every course", "likely": "the most likely course"},
                          rounds=[{"round": r["round"], "dmg": x["dmg"], "sd": x["sd"], "mean": x["dmg"],
                                   "mean_sd": x["sd"], "likely": round(r["mean"], 1), "likely_sd": round(r["sd"], 1),
                                   "text": r["text"]}
                                  for r, x in zip(path, fe["rounds"])])
    return out


# ---------------------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="plan.py output")
    ap.add_argument("--pair", type=int, default=0)
    ap.add_argument("--side", default="a")
    ap.add_argument("--stats", help="stats_resolved.json (default: data/cache)")
    ap.add_argument("--sneak-policy", choices=SNEAK_POLICIES,
                    help="Sneak Attack on the riposte in the boss's turn (default: each family's best)")
    ap.add_argument("--no-riposte", action="store_true")
    ap.add_argument("--state", help="a policy table key (state_key): print the family's decision and expectation there")
    ap.add_argument("--family", default="melee", help="the family --state is read under")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    stats_path = a.stats or os.path.join(os.path.dirname(os.path.dirname(here)), "data", "cache", "stats_resolved.json")
    with open(stats_path, encoding="utf-8") as f:
        stats = json.load(f)
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)[a.pair]["specs"][a.side]
    P = profile_from_spec(spec, stats)
    if a.no_riposte:
        P = replace(P, riposte=None)
    if a.state:
        S = best_search(P, a.family, a.sneak_policy)[0]
        n = state_numbers(S, parse_state_key(a.state))
        print("%s %s: %s; own turn %.1f (sd %.1f), round %.1f (sd %.1f)" % (
            a.family, a.state, describe(n["plan"]), n["own"][0], n["own"][1], n["round"][0], n["round"][1]))
        return 0
    res = rank(P, policy=a.sneak_policy)
    for r in res:
        print("%-14s total %7.1f  sd %5.1f  DPR %6.2f  Sneak Attack on the riposte: %s (%s)  %s" % (
            r["family"], r["total"], r["sd"], r["dpr"], r["sneak_policy"],
            ", ".join("%s %.1f" % kv for kv in r["policies"].items()), r["why"]))
        print("    round  expectation (sd) | most likely course (sd): its decision")
        for row, ex in zip(r["path"], r["rounds"]):
            print("    r%-2d %-4s %6.1f (%4.1f) | %6.1f (%4.1f): %s" % (
                row["round"], "adj" if row["adjacent"] else "away", ex["mean"], ex["sd"], row["mean"], row["sd"],
                row["text"]))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump([dict(r, path=[dict(x, plan=x["plan"].__dict__) for x in r["path"]]) for r in res], f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
