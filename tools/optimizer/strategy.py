"""Turn-by-turn strategy search for one character against the gauntlet boss (one enemy that never dies, 16 rounds).

    python tools/optimizer/strategy.py --spec specs.json [--pair 0] [--side a] [--out ranking.json]

specs.json is tools/gauntlet/plan.py's output (one set's spec per side); the character's numbers are read from it and
from the game stats (profile_from_spec). The search is exact, not sampled:

- one attack: the d20 is enumerated (Advantage = best of two, Disadvantage = worst of two, both = one straight d20; a
  natural 1 misses, a natural at or above the crit threshold is a critical hit), a Precision Attack die is enumerated
  with it; damage is carried as its first two moments (dice means and variances, every die doubled on a critical hit);
- one turn: the attacks in order with a branch state (Sneak Attack spent, superiority dice spent, boss Frightened, Gaping
  Wound, Ensnaring Strike), so Sneak Attack lands once, on the first hit with net Advantage;
- the boss's turn: it walks up and attacks unless Frightened or restrained; its miss gives the set's riposte reaction,
  its hit can break concentration;
- the fight: dynamic programming over (round, boss adjacent at the turn's start, superiority dice, Action Surge,
  concentration, Gaping Wound, the once-per-rest item attacks, Dread Ambusher) for the largest expected total; the same
  recursion carries the second moment, so the total's standard deviation is exact for the chosen policy.

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


def attack_odds(bonus, ac, mode, crit_from=20, bonus_die=0):
    """(miss, hit that is not critical, critical) of one attack roll; bonus_die: a die added to the roll (Precision)."""
    miss = hit = crit = 0.0
    for nat, p in enumerate(d20_naturals(mode), 1):
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
    riposte_sneak: bool = False     # Sneak Attack on the reaction attack (once per turn, the boss's turn)
    boss_ac: int = 19
    boss_save: int = 4
    boss_atk: int = 9
    char_ac: int = 22
    conc_save: int = 8              # Constitution save bonus (concentration)
    conc_dc: int = 10               # the boss's hits (half damage in the gauntlet) stay below 20
    boss_first: float = 0.0         # P(the boss acts before the character in round 1)


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
    riposte = None
    off_sid = items.get("MeleeOffHand")
    for p in _passives(stats, off_sid, "off") if off_sid else []:
        for intr in re.findall(r"UnlockInterrupt\((\w+)\)", (stats.get(p) or {}).get("Boosts") or ""):
            props = (stats.get(intr) or {}).get("Properties") or ""
            if "IsMiss()" in ((stats.get(intr) or {}).get("Conditions") or "") and "UseSpell(" in props:
                riposte = mm
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
        ensnare=cl.get("Ranger", 0) >= 1, riposte=riposte,
        boss_ac=int(E.get("ac", 19)), boss_save=int(E.get("save", 4)), boss_atk=int(E.get("atk", 9)),
        char_ac=int(spec["expect"]["ac"]), conc_save=(con - 10) // 2 + save_bonus, boss_first=first)


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
                                      P.sup_die if precision else 0)
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
    out = []
    if plan.dread:
        out.append(Attack("Dread Ambusher", main, mode, extra_dice=(P.dread_die,)))
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
                          pierce=kind == "pierce", ensnare=kind == "ensnare"))
    ba = P.bonus_actions - (1 if plan.mark else 0) - (1 if plan.mode == "leave" else 0)
    for j in range(max(0, ba)):
        out.append(Attack("off-hand", off, mode, if_no_ensnare=plan.ensnare and j == ba - 1))
    return [replace(a, sharpshooter=_choose_ss(P, a.weapon, a.mode, a.precision, a.extra_dice)) for a in out]


@dataclass(frozen=True)
class TurnStart:
    adjacent: bool
    conc: str                       # "" / "mark" / "ensnare" (the boss restrained)
    gaping: bool                    # Gaping Wound from the turn before is still on the boss


def run_turn(P, plan, start):
    """-> {(sneak_used, dice_hit, frightened, gaping_new, ensnare): (p, E[D;branch], E[D^2;branch])}; ensnare 0 none
    or missed, 1 hit and restrained, 2 hit and saved."""
    q_fright = save_fails(P.boss_save, P.maneuver_dc)
    q_gape = save_fails(P.boss_save, P.maneuver_dc + 2)
    q_snare = save_fails(P.boss_save, P.spell_dc)
    states = {(False, 0, False, False, 0): (1.0, 0.0, 0.0)}
    marked0 = plan.mark or start.conc == "mark"
    for a in build_attacks(P, plan, start):
        nxt = {}

        def add(key, p, m1, m2):
            q = nxt.get(key, (0.0, 0.0, 0.0))
            nxt[key] = (q[0] + p, q[1] + m1, q[2] + m2)
        for key, (p, m1, m2) in states.items():
            sa, k, fr, gnew, ens = key
            if a.if_no_ensnare and ens:
                add(key, p, m1, m2)
                continue
            w = a.weapon
            pen, ssd = P.sharpshooter if (a.sharpshooter and P.sharpshooter) else (0, 0)
            miss, hit, crit = attack_odds(w.bonus - pen, P.boss_ac, a.mode, P.crit_from,
                                          P.sup_die if a.precision else 0)
            marked = marked0 and not ens
            dice = w.dice + a.extra_dice + ((P.mark_die,) if marked and P.mark_die else ()) + \
                ((P.sup_die,) if a.maneuver else ())
            flat = w.flat + ssd + (w.adv_flat if a.mode == "adv" else 0) + \
                (P.gaping if (start.gaping or gnew) else 0)
            add(key, p * miss, m1 * miss, m2 * miss)
            sneak = P.sneak_dice and a.mode == "adv" and w.sneak and not sa
            for pr, is_crit in ((hit, False), (crit, True)):
                if not pr:
                    continue
                d = dice + (P.sneak_dice if sneak else ())
                mu, s2 = landed(d, flat, is_crit)
                base = (p * pr, pr * (m1 + p * mu), pr * (m2 + 2 * m1 * mu + p * s2))
                k2 = k + (1 if a.maneuver else 0)
                outs = [((sa or bool(sneak), k2, fr, gnew, ens), 1.0)]
                if a.maneuver == "MenacingAttack":
                    outs = [((sa or bool(sneak), k2, True, gnew, ens), q_fright),
                            ((sa or bool(sneak), k2, fr, gnew, ens), 1 - q_fright)]
                elif a.pierce:
                    outs = [((sa or bool(sneak), k2, fr, True, ens), q_gape),
                            ((sa or bool(sneak), k2, fr, gnew, ens), 1 - q_gape)]
                elif a.ensnare:
                    outs = [((sa or bool(sneak), k2, fr, gnew, 1), q_snare),
                            ((sa or bool(sneak), k2, fr, gnew, 2), 1 - q_snare)]
                for kk, f in outs:
                    if f:
                        add(kk, base[0] * f, base[1] * f, base[2] * f)
        states = nxt
    return states


def boss_turn(P, conc, ends_adjacent, frightened, gaping):
    """The boss's turn after ours -> [(p, E[R], E[R^2], conc after, adjacent at our next turn)], R = our damage in it
    (the riposte, the Ensnaring Strike tick)."""
    out = []
    branches = [(1.0, conc == "ensnare", 0.0, 0.0)]
    if conc == "ensnare":
        esc = 1 - save_fails(P.boss_save, P.spell_dc)
        tm, tv = dice_moments((P.ensnare_die,))
        branches = [(esc, False, 0.0, 0.0), (1 - esc, True, tm, tv + tm * tm)]
    for pb, held, dm, d2 in branches:
        conc_b = conc if (conc != "ensnare" or held) else ""
        moves = not frightened and not held
        attacks = ends_adjacent or moves
        if not attacks:
            out.append((pb, pb * dm, pb * d2, conc_b, False))
            continue
        _, h, c = attack_odds(P.boss_atk, P.char_ac, "dis" if (frightened or held) else "straight", 20)
        ph = h + c
        brk = ph * save_fails(P.conc_save, P.conc_dc)
        rows = [(brk, 0.0, 0.0, ""), (ph - brk, 0.0, 0.0, conc_b)]
        if P.riposte:
            w = P.riposte
            rmode = net_mode(P.adv or held, False)
            miss, hit, crit = attack_odds(w.bonus, P.boss_ac, rmode, P.crit_from)
            dice = w.dice + ((P.mark_die,) if conc_b == "mark" and P.mark_die else ()) + \
                (P.sneak_dice if (P.riposte_sneak and rmode == "adv") else ())
            flat = w.flat + (w.adv_flat if rmode == "adv" else 0) + (P.gaping if gaping else 0)
            mh, sh = landed(dice, flat, False)
            mc, sc = landed(dice, flat, True)
            rm = hit * mh + crit * mc
            rs = hit * sh + crit * sc
            rows.append((1 - ph, rm, rs, conc_b))
        else:
            rows.append((1 - ph, 0.0, 0.0, conc_b))
        for pr, rm, rs, cc in rows:
            # boss damage R (riposte) and the tick (dm) are independent: E[(T+R)^2] = E[T^2] + 2E[T]E[R] + E[R^2]
            out.append((pb * pr, pb * pr * (dm + rm), pb * pr * (d2 + 2 * dm * rm + rs), cc, True))
    return out


# ------------------------------------------------------------------------------------------------------ the fight
FAMILIES = {
    # mode allowed with the boss in reach / out of reach, and the options the family may use
    "melee": dict(adjacent=("melee",), away=("melee", "free"), ensnare=False,
                  why="fight in melee once the boss is in reach (Crimson Mischief + Blade of the First Blood)"),
    "melee_open": dict(adjacent=("melee",), away=("melee",), ensnare=False,
                       why="as melee, and walk up to the boss in round 1 too (Dread Ambusher in melee)"),
    "evade": dict(adjacent=("leave",), away=("free",), ensnare=False,
                  why="Cunning Action Disengage + step out of reach every turn the boss is in reach, then shoot; "
                      "Menacing Attack may keep the boss Frightened (it cannot move) and out of reach"),
    "evade_nohold": dict(adjacent=("leave",), away=("free",), ensnare=False, maneuvers=("TripAttack",
                                                                                         "PrecisionAttack"),
                         why="as evade, superiority dice only for damage (Trip Attack, Precision): the boss always "
                             "walks back into reach (the model's plan today)"),
    "evade_ensnare": dict(adjacent=("leave",), away=("free",), ensnare=True,
                          why="as evade, with Ensnaring Strike (Ranged) to hold the boss out of reach"),
    "stand": dict(adjacent=("stand",), away=("free",), ensnare=False,
                  why="stand and shoot with the boss in reach (Advantage and Disadvantage cancel)"),
    "any": dict(adjacent=("melee", "leave", "stand"), away=("melee", "free"), ensnare=True,
                why="every option open each turn"),
}


@dataclass(frozen=True)
class State:
    rnd: int
    adjacent: bool
    dice: int
    surge: bool
    conc: str
    gaping: bool
    pierce_m: bool
    pierce_r: bool
    dread: bool
    boss_after: bool                # the boss's turn follows this one (false only for the last turn when it acts first)


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


@functools.lru_cache(maxsize=None)
def _turn_cached(P, plan, start):
    return run_turn(P, plan, start)


class Search:
    """The best policy of one family: V(state) = max over plans of E[this turn + boss turn + V(next)]."""

    def __init__(self, P, fam, last_boss_turn=True):
        self.P, self.fam, self.last = P, fam, last_boss_turn
        self.memo = {}

    def value(self, s):
        """-> (E[total], E[total^2], best plan)."""
        if s is None:
            return 0.0, 0.0, None
        if s in self.memo:
            return self.memo[s]
        best = None
        for plan in plans(self.P, s, self.fam):
            e1 = e2 = 0.0
            for p, m1, m2, nx in self._branches(s, plan):
                v1, v2, _ = self.value(nx)
                e1 += m1 + p * v1
                e2 += m2 + 2 * m1 * v1 + p * v2
            if best is None or e1 > best[0] + 1e-9:
                best = (e1, e2, plan)
        self.memo[s] = best
        return best

    def _branches(self, s, plan):
        start = TurnStart(s.adjacent, s.conc, s.gaping)
        res = _turn_cached(self.P, plan, start)
        out = []
        for (sa, k, fr, gnew, ens), (p, m1, m2) in res.items():
            if p <= 0:
                continue
            conc = "mark" if plan.mark else s.conc
            if ens == 1:
                conc = "ensnare"
            elif ens == 2:
                conc = ""
            nx = dict(rnd=s.rnd + 1, dice=s.dice - plan.n_precision - k, surge=s.surge and not plan.surge,
                      gaping=gnew, pierce_m=s.pierce_m and not (plan.pierce and plan.mode == "melee"),
                      pierce_r=s.pierce_r and not (plan.pierce and plan.mode != "melee"), dread=False)
            last = s.rnd >= ROUNDS
            if not s.boss_after:
                out.append((p, m1, m2, None))
                continue
            for pb, rm, rs, cc, adj in boss_turn(self.P, conc, plan.mode in ("melee", "stand"), fr, gnew):
                nxt = None if last else State(adjacent=adj, conc=cc,
                                              boss_after=(s.rnd + 1 < ROUNDS) or self.last, **nx)
                out.append((p * pb, m1 * pb + p * rm, m2 * pb + 2 * m1 * rm + p * rs, nxt))
        return out

    def start_state(self):
        P = self.P
        return State(rnd=1, adjacent=False, dice=P.sup_dice, surge=P.surge, conc="", gaping=False,
                     pierce_m=P.pierce_melee, pierce_r=P.pierce_ranged, dread=bool(P.dread_die), boss_after=True)

    def total(self):
        """-> (E[total], sd) over who acts first: we do (the boss walks up after our turn), or the boss walks up and
        attacks first (then our first turn starts in its reach and no boss turn follows our 16th)."""
        P = self.P
        v1, v2, _ = self.value(self.start_state())
        e1, e2 = (1 - P.boss_first) * v1, (1 - P.boss_first) * v2
        if P.boss_first:
            other = Search(P, self.fam, last_boss_turn=False)
            s0 = replace(self.start_state(), adjacent=True)
            for pb, rm, rs, cc, _adj in boss_turn(P, "", True, False, False):
                w1, w2, _ = other.value(replace(s0, conc=cc))
                e1 += P.boss_first * (pb * w1 + rm)
                e2 += P.boss_first * (pb * w2 + 2 * rm * w1 + rs)
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


def rank(P, families=None):
    """-> [{family, why, total, sd, dpr, path: [{round, plan, text, mean, sd}]}], best first."""
    out = []
    for fam in families or [f for f in FAMILIES if f != "any"]:
        S = Search(P, fam)
        tot, sd = S.total()
        path = S.path()
        out.append({"family": fam, "why": FAMILIES[fam]["why"], "total": tot, "sd": sd, "dpr": tot / ROUNDS,
                    "path": [{"round": s.rnd, "adjacent": s.adjacent, "plan": plan, "text": describe(plan),
                              "mean": m, "sd": d} for s, plan, m, d in path]})
    out.sort(key=lambda r: -r["total"])
    return out


# --------------------------------------------------------------------------------------- harness plan (tools/gauntlet)
def harness_rounds(path, A, evade_steps, evade_every_round=False):
    """The family's policy along its most likely course as the gauntlet's round plan (plan.py step dicts). A and
    evade_steps are plan.py's step builders; steps that may not be affordable carry the plain attack as their alt.
    evade_every_round: the Disengage steps in every round (they skip themselves while the boss is out of reach), so
    a boss that was not held off as the most likely course assumed is still left behind."""
    rounds = []
    for row in path:
        plan = row["plan"]
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
            group, req, base_why = ("action", None, "attack") if i == 0 else                 ("free", "action", "Extra Attack") if i == 1 else ("free", "surge", "Action Surge attack")
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
        rounds.append(steps)
    return rounds


def apply_to_spec(spec, P, family, A, evade_steps):
    """The spec with the family's round plan and its predicted numbers (expect.strategy); the riposte reaction is set
    to fire when the profile counts it."""
    S = Search(P, family)
    tot, sd = S.total()
    path = [{"round": s.rnd, "adjacent": s.adjacent, "plan": plan, "text": describe(plan), "mean": m, "sd": d}
            for s, plan, m, d in S.path()]
    out = json.loads(json.dumps(spec, default=str))
    plan = out["plan"]
    plan["rounds"] = harness_rounds(path, A, evade_steps, "leave" in FAMILIES[family]["adjacent"])
    plan["steady"] = list(plan["rounds"][-1])
    plan["fight_rounds"] = ROUNDS
    plan["strategy"] = family
    if P.riposte:
        plan.setdefault("reactions", {})["Interrupt_TheClover_TrueStrike_Riposte"] = "auto"
    out["expect"]["strategy"] = {"family": family, "why": FAMILIES[family]["why"], "total": round(tot, 1),
                                 "sd": round(sd, 1), "dpr": round(tot / ROUNDS, 2),
                                 "rounds": [{"round": r["round"], "text": r["text"], "dmg": round(r["mean"], 1),
                                             "sd": round(r["sd"], 1)} for r in path]}
    return out


# ---------------------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="plan.py output")
    ap.add_argument("--pair", type=int, default=0)
    ap.add_argument("--side", default="a")
    ap.add_argument("--stats", help="stats_resolved.json (default: data/cache)")
    ap.add_argument("--riposte-sneak", action="store_true", help="count Sneak Attack on the boss-turn riposte")
    ap.add_argument("--no-riposte", action="store_true")
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
    if a.riposte_sneak:
        P = replace(P, riposte_sneak=True)
    if a.no_riposte:
        P = replace(P, riposte=None)
    res = rank(P)
    for r in res:
        print("%-14s total %7.1f  sd %5.1f  DPR %6.2f  %s" % (r["family"], r["total"], r["sd"], r["dpr"], r["why"]))
        for row in r["path"]:
            print("    r%-2d %-4s %6.1f (sd %4.1f)  %s" % (row["round"], "adj" if row["adjacent"] else "away",
                                                       row["mean"], row["sd"], row["text"]))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump([dict(r, path=[dict(x, plan=x["plan"].__dict__) for x in r["path"]]) for r in res], f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
