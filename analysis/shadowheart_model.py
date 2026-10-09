"""Shadowheart build model (Patch 8). Compares caster builds at level 5 (Act 1), 8 (Act 2) and 12 (Act 3).

Inputs read from the game data (data/cache/stats_resolved.json, Progressions.lsx in Shared.pak / GustavX):
  Radiance of the Dawn      Shout_RadianceOfTheDawn: 2d10+Level radiant, Con save half, 9 m radius, 1 Channel Divinity
  Destructive Wrath         Interrupt_DestructiveWrath: costs 1 Channel Divinity, DESTRUCTIVE_WRATH = MinimumRollResult(Damage,20)
                            on lightning/thunder spells (every die rolls its maximum)
  Channel Divinity          Cleric 2 (+1), Cleric 6 (+1); restored on short rest. Amulet of the Devout +1 (restored on long rest)
  Potent Spellcasting       Light Domain 8: Cleric cantrips + WIS modifier
  Reaper                    Death Domain 1: Toll the Dead / Chill Touch get +1 target
  Heart of the Storm        Storm Sorcery 6: every lightning/thunder spell -> ClassLevel(Sorcerer)/2 to enemies within 6 m, no save
  Spirit Guardians          SPIRIT_GUARDIANS_*: 3d8 (+1d8 per slot level), Wis save half, once per target per turn, 3 m
  Call Lightning            Target_CallLightning_k: kd10 Dex half, 2 m; recast as an action each turn, no slot (concentration)
  Chain Lightning           Projectile_ChainLightning: 10d8 Dex half on the target + 3 more targets (Projectile_ChainLightning_Explosion)
  Markoheshkir              lightning attunement -> Chain Lightning OncePerShortRest, no slot; +1 DC
  Destructive Wave          5d6 thunder + 5d6 radiant, Con half, 9 m radius, prone (Light AND Tempest domain spell, Cleric 9)
  Insect Plague             Tempest domain (Cleric 9): 4d10 (+1d10 at 6th), Con half, 6 m, concentration
  Toll the Dead             3d12 at level 10+ (D12Cantrip), Wis save, no damage on a save
  Spiritual Weapon          1d8+WIS force per hit (3d8 at 6th), summon that attacks on its own turn
  Quickened Spell           3 sorcery points
Simplifications (same for every build): 4 enemies per fight; 3 rounds per fight; 4 fights per long rest with the 2 short
rests BG3 allows; save-for-half spells; Callous Glow Ring (+2 per damage instance) from Act 2 on illuminated targets;
concentration is never broken (see the defence table); healing / buff spells are not counted as damage."""
import itertools
from functools import lru_cache

ROUNDS, FIGHTS, SHORT_RESTS = 3, 4, 2
TGT = dict(huge=4, chain=4, r6=3, r4=3, r3=2.5, line=2.5, r2=1.5, one=1)   # enemies hit per area (4 in the fight)
SG_TGT = 2                                                                  # enemies inside Spirit Guardians per round
CL_DW_ALL = True      # Destructive Wrath maximises all 4 Chain Lightning targets (status lasts until the cast resolves)
ROTD_CLASS_LEVEL = False   # Radiance of the Dawn "2d10+Level": character level (default) or Cleric level
TWIN_FREE = False     # Twinned cost = SpellPowerLevel (0 for a cantrip in the stats); wiki: 1 point. True = free twins
DEVOUT_SR = False     # Amulet of the Devout charge back on short rest (bg3.wiki bug note) instead of long rest (game data)
SLOTS = {5: [4, 3, 2, 0, 0, 0], 8: [4, 3, 3, 2, 0, 0], 12: [4, 3, 3, 3, 2, 1]}   # full-caster slot table (BG3)


def pfail(dc, sv):
    return min(.95, max(.05, (dc - sv - 1) / 20))


def p_hit(bonus, ac):
    return min(.95, max(.05, (21 - (ac - bonus)) / 20))


def avg(n, d):
    return n * (d + 1) / 2


class Ctx:
    def __init__(self, b, act, kit):
        self.b, self.act, self.kit = b, act, kit
        e = ENEMY[(act, kit)]
        self.lvl, self.ac, self.sv, self.n = e["level"], e["ac"], e["save"], e["n"]
        g = GEAR[(act, kit)]
        self.mod = b["mod"][act]
        self.prof = 2 + (self.lvl - 1) // 4
        self.dc = 8 + self.prof + self.mod + g["dc"]
        self.atk = self.prof + self.mod + g["atk"]
        self.cg = g["cg"] * b.get("illum", .5)       # Callous Glow per damage instance
        self.staff = g["staff"]

    def tg(self, area):
        return min(self.n, TGT[area])


# ---- spells: parts = [(n, die, type)], dw = Destructive Wrath can maximise the lightning/thunder parts
def spell(ctx, parts, area, dw=False, flat=0, inst=1, half=True, hots=True):
    tot = 0
    for n, d, t in parts:
        tot += n * d if (dw and t in ("lightning", "thunder")) else avg(n, d)
    tot += flat
    pf = pfail(ctx.dc, ctx.sv)
    per = tot * (pf + (1 - pf) / 2 if half else pf) + ctx.cg * inst
    dmg = per * ctx.tg(area)
    if hots and ctx.b.get("hots") and any(t in ("lightning", "thunder") for _, _, t in parts):
        dmg += ctx.b["hots"] * min(ctx.n, 2)
    return dmg


def chain(ctx, dw):
    if dw and not CL_DW_ALL:      # only the first target maximised
        one = spell(ctx, [(10, 8, "lightning")], "one", dw=True, hots=False)
        rest = spell(ctx, [(10, 8, "lightning")], "chain", hots=True) * (ctx.tg("chain") - 1) / ctx.tg("chain")
        return one + rest
    return spell(ctx, [(10, 8, "lightning")], "chain", dw=dw)


def options(ctx):
    """(name, kind, cost{res:n}, dmg, conc, can_dw). kind: A = action; conc: None | ('sg', tick) | ('cl', level)."""
    b, L, o = ctx.b, ctx.lvl, []
    cl = b["cleric"].get(L, 0)
    maxsl = {k: v for k, v in b["spells"].items()}

    def lvl_ok(name, k):
        return maxsl.get(name, 99) <= k and SLOTS[L][k - 1] > 0

    # cantrips (always available)
    d12 = 3 if L >= 10 else 2 if L >= 5 else 1
    potent = ctx.mod if (b.get("potent") and cl >= 8) else 0
    if b.get("toll"):
        n = min(ctx.n, 2) if b.get("reaper") else 1
        toll = n * spell(ctx, [(d12, 12, "necrotic")], "one", flat=potent, half=False)
        o.append(("Toll the Dead", "A", {}, toll, None, False))
        if b.get("twin_ok") and ctx.n > 1:     # Twinned Spell (Sorcerer 2): +1 target, cost = spell level (cantrip: 1 SP)
            o.append(("Toll the Dead (twinned)", "A", {} if TWIN_FREE else {"tw": 1}, 2 * toll, None, False))
    if b.get("firebolt"):
        o.append(("Fire Bolt", "A", {}, p_hit(ctx.atk, ctx.ac) * (avg(d12, 10) + ctx.cg) + .05 * avg(d12, 10), None, False))
    # Radiance of the Dawn (Light)
    if b.get("rotd") and cl >= 2:
        o.append(("Radiance of the Dawn", "A", {"cd": 1}, spell(ctx, [(2, 10, "radiant")], "huge", flat=cl if ROTD_CLASS_LEVEL else L), None, False))
    # Markoheshkir Chain Lightning (no slot, per short rest)
    if ctx.staff:
        for dw in (False, True):
            if dw and not b.get("dw"):
                continue
            c = {"staff": 1, **({"cd": 1} if dw else {})}
            o.append(("Chain Lightning (Markoheshkir)" + (" +DW" if dw else ""), "A", c, chain(ctx, dw), None, dw))
    for k in range(3, 7):
        if SLOTS[L][k - 1] == 0:
            continue
        s = {f"s{k}": 1}
        for dw in ((False, True) if b.get("dw") else (False,)):
            c = {**s, **({"cd": 1} if dw else {})}
            tag = " +DW" if dw else ""
            if "Call Lightning" in maxsl and lvl_ok("Call Lightning", k):
                o.append((f"Call Lightning @{k}{tag}", "A", c, spell(ctx, [(k, 10, "lightning")], "r2", dw=dw), ("cl", k), dw))
            if "Destructive Wave" in maxsl and lvl_ok("Destructive Wave", k) and k <= 6:
                o.append((f"Destructive Wave @{k}{tag}", "A", c, spell(ctx, [(5, 6, "thunder"), (5, 6, "radiant")], "huge", dw=dw, inst=2), None, dw))
            if "Lightning Bolt" in maxsl and lvl_ok("Lightning Bolt", k):
                o.append((f"Lightning Bolt @{k}{tag}", "A", c, spell(ctx, [(5 + k, 6, "lightning")], "line", dw=dw), None, dw))
            if "Shatter" in maxsl and lvl_ok("Shatter", k):
                o.append((f"Shatter @{k}{tag}", "A", c, spell(ctx, [(k + 1, 8, "thunder")], "r3", dw=dw), None, dw))
            if "Chain Lightning" in maxsl and lvl_ok("Chain Lightning", k):
                o.append((f"Chain Lightning @{k}{tag}", "A", c, chain(ctx, dw), None, dw))
        if "Spirit Guardians" in maxsl and lvl_ok("Spirit Guardians", k):
            tick = spell(ctx, [(k, 8, "radiant")], "one") * min(ctx.n, SG_TGT)
            o.append((f"Spirit Guardians @{k}", "A", s, 0, ("sg", tick), False))
        if "Insect Plague" in maxsl and lvl_ok("Insect Plague", k):
            tick = spell(ctx, [(k - 1, 10, "piercing")], "r6")
            o.append((f"Insect Plague @{k}", "A", s, 0, ("sg", tick), False))
        if "Fireball" in maxsl and lvl_ok("Fireball", k):
            o.append((f"Fireball @{k}", "A", s, spell(ctx, [(5 + k, 6, "fire")], "r4"), None, False))
        if "Flame Strike" in maxsl and lvl_ok("Flame Strike", k):
            o.append((f"Flame Strike @{k}", "A", s, spell(ctx, [(k, 6, "fire"), (k, 6, "radiant")], "r3", inst=2), None, False))
        if "Cone of Cold" in maxsl and lvl_ok("Cone of Cold", k):
            o.append((f"Cone of Cold @{k}", "A", s, spell(ctx, [(k + 3, 8, "cold")], "r4"), None, False))
        if "Guardian of Faith" in maxsl and lvl_ok("Guardian of Faith", k):
            o.append(("Guardian of Faith", "A", s, min(60, 20 * ctx.n * (pfail(ctx.dc, ctx.sv) / 2 + .5) * 1.0), None, False))
    return o


def call_lightning_bolt(ctx, k, dw):
    return spell(ctx, [(k, 10, "lightning")], "r2", dw=dw)


def quickenable(name):
    """QuickenedSpellCheck() (CommonConditions.khn): needs an ActionPoint cost and SpellFlags.Spell.
    Radiance of the Dawn (Channel Divinity) has no IsSpell flag, so it cannot be quickened."""
    return not name.startswith("Radiance")


def resources(ctx):
    b, L = ctx.b, ctx.lvl
    cl = b["cleric"].get(L, 0)
    cd_sr = (1 if cl >= 2 else 0) + (1 if cl >= 6 else 0)
    devout = 1 if GEAR[(ctx.act, ctx.kit)].get("devout") else 0
    r = {"cd": (cd_sr * (SHORT_RESTS + 1) + devout * (SHORT_RESTS + 1 if DEVOUT_SR else 1)) / FIGHTS,
         "staff": (SHORT_RESTS + 1) / FIGHTS if ctx.staff else 0,
         "q": b.get("quick", {}).get(L, 0),
         "tw": 0 if TWIN_FREE else b.get("twin", {}).get(L, 0)}
    for k in range(3, 7):
        r[f"s{k}"] = SLOTS[L][k - 1] / FIGHTS
    return r


def fight(ctx):
    """Best 3-round fight; fractional per-fight resources are enumerated as integer scenarios with weights."""
    opts = options(ctx)
    res = resources(ctx)
    keys = [k for k, v in res.items() if v > 0]
    lo = {k: int(res[k]) for k in keys}
    fr = {k: res[k] - int(res[k]) for k in keys}
    total, plan_w = 0, {}
    for bits in itertools.product((0, 1), repeat=len(keys)):
        w = 1
        have = {}
        for k, bt in zip(keys, bits):
            w *= fr[k] if bt else 1 - fr[k]
            have[k] = lo[k] + bt
        if w == 0:
            continue

        @lru_cache(None)
        def best(rnd, conc, state):
            if rnd == ROUNDS:
                return 0, ()
            have_ = dict(state)
            choices = []
            # running concentration effects tick this round
            tick = conc[1] if conc and conc[0] == "sg" else 0
            cands = [(n, c, d, cn) for n, kd, c, d, cn, dw in opts]
            if conc and conc[0] == "cl":
                k = conc[1]
                cands.append((f"Call Lightning bolt @{k}", {}, call_lightning_bolt(ctx, k, False), None))
                if ctx.b.get("dw"):
                    cands.append((f"Call Lightning bolt @{k} +DW", {"cd": 1}, call_lightning_bolt(ctx, k, True), None))
            n_actions = 1
            for n, c, d, cn in cands:
                if any(have_.get(r, 0) < v for r, v in c.items()):
                    continue
                st = dict(have_)
                for r, v in c.items():
                    st[r] -= v
                nconc = cn if cn else conc
                ntick = nconc[1] if nconc and nconc[0] == "sg" else 0
                v, p = best(rnd + 1, nconc, tuple(sorted(st.items())))
                # quickened second spell this round (sorcerer)
                choices.append((d + ntick + v, (n,) + p))
                if have_.get("q", 0) >= 1:
                    for n2, c2, d2, cn2 in cands:
                        if cn2 or not c2 or not quickenable(n2):
                            continue
                        st2 = dict(st)
                        st2["q"] -= 1
                        if any(st2.get(r, 0) < v2 for r, v2 in c2.items()):
                            continue
                        for r, v2 in c2.items():
                            st2[r] -= v2
                        v2b, p2 = best(rnd + 1, nconc, tuple(sorted(st2.items())))
                        choices.append((d + d2 + ntick + v2b, (n + " + quickened " + n2,) + p2))
            return max(choices)

        v, p = best(0, None, tuple(sorted(have.items())))
        total += w * v
        plan_w[p] = plan_w.get(p, 0) + w
    sw = 0
    if ctx.b["cleric"].get(ctx.lvl, 0) >= 3:      # Spiritual Weapon (2nd slot, bonus action) attacks 3 times
        sw = 3 * (p_hit(ctx.atk, ctx.ac) * (avg(1, 8) + ctx.mod + ctx.cg))
        sw *= min(1, SLOTS[ctx.lvl][1] / FIGHTS)
    top = max(plan_w.items(), key=lambda kv: kv[1])[0]
    return total + sw, top, sw


def nova(ctx):
    """Round 1 with everything available: best action (+ quickened bonus-action spell)."""
    opts = [o for o in options(ctx)]
    best_a = max(o[3] + (o[4][1] if o[4] and o[4][0] == "sg" else 0) for o in opts)
    if ctx.b.get("quick", {}).get(ctx.lvl, 0) > 0:      # one quickened leveled spell next to the action
        a = sorted([(o[3], "staff" in o[2]) for o in opts if o[2] and not o[4] and quickenable(o[0])], reverse=True)
        first = a[0]
        second = next(x for x in a[1:] if not (x[1] and first[1]))
        best_a = max(best_a, first[0] + second[0])
    return best_a


def sustained(ctx):
    """A round with no new resources: running concentration (cast earlier) + the best free action."""
    o = options(ctx)
    free = max([d for n, kd, c, d, cn, dw in o if not c and not cn] + [0])
    best = free
    for n, kd, c, d, cn, dw in o:
        if cn and cn[0] == "sg":
            best = max(best, cn[1] + free)
        if cn and cn[0] == "cl":
            best = max(best, call_lightning_bolt(ctx, cn[1], False))
    return best


# ---- builds ------------------------------------------------------------------------------------------------
CLERIC_SPELLS = {"Spirit Guardians": 3, "Guardian of Faith": 4}
BUILDS = {
    "A  Light Cleric 12 (BuildAdvisor)": dict(
        cleric={5: 5, 8: 8, 12: 12}, mod={1: 5, 2: 5, 3: 5}, rotd=True, potent=True, toll=True, illum=1.0,
        spells={**CLERIC_SPELLS, "Fireball": 3, "Flame Strike": 5, "Destructive Wave": 5}),
    "B  Storm Sorcerer 10 / Tempest Cleric 2 (BuildAdvisor)": dict(
        cleric={5: 2, 8: 2, 12: 2}, mod={1: 4, 2: 5, 3: 5}, dw=True, firebolt=True,
        hots_by={5: 0, 8: 3, 12: 5}, quick={5: 0, 8: .5, 12: 1},
        spells_by={5: {"Shatter": 2},
                   8: {"Shatter": 2, "Lightning Bolt": 3, "Call Lightning": 3, "Fireball": 3},
                   12: {"Shatter": 2, "Lightning Bolt": 3, "Call Lightning": 3, "Fireball": 3, "Cone of Cold": 5,
                        "Chain Lightning": 6}}),
    "C  Tempest Cleric 12": dict(
        cleric={5: 5, 8: 8, 12: 12}, mod={1: 5, 2: 5, 3: 5}, dw=True, toll=True,
        spells={**CLERIC_SPELLS, "Shatter": 2, "Call Lightning": 3, "Destructive Wave": 5, "Insect Plague": 5}),
    "D  Tempest Cleric 6 / Storm Sorcerer 6 (WIS)": dict(
        cleric={5: 5, 8: 6, 12: 6}, mod={1: 5, 2: 5, 3: 5}, dw=True, toll=True,
        hots_by={5: 0, 8: 0, 12: 3}, quick={5: 0, 8: 0, 12: .75},   # Quickened needs Sorcerer 3
        spells={"Spirit Guardians": 3, "Shatter": 2, "Call Lightning": 3}),
    # Sorcery points per long rest = Sorcerer level + 3 level-1 slots turned into points (Font of Magic).
    # Metamagic offered (PassiveLists.lsx): Sorcerer 2 picks 2 of Careful/Distant/Extended/Twinned (list 49704931);
    # Quickened/Heightened/Subtle only from Sorcerer 3 (list c3506532). Careful/Distant/Extended add no damage here.
    "G  Light Cleric 10 / Sorcerer 2 (Twinned)": dict(
        cleric={5: 5, 8: 8, 12: 10}, mod={1: 5, 2: 5, 3: 5}, rotd=True, potent=True, toll=True, illum=1.0,
        sp_lr={12: 5}, twin_ok=True,
        spells={**CLERIC_SPELLS, "Fireball": 3, "Flame Strike": 5, "Destructive Wave": 5}),
    "I  Light Cleric 9 / Sorcerer 3 (Quickened)": dict(
        cleric={5: 5, 8: 8, 12: 9}, mod={1: 5, 2: 5, 3: 5}, rotd=True, potent=True, toll=True, illum=1.0,
        sp_lr={12: 6}, twin_ok=True, quick_ok=True,
        spells={**CLERIC_SPELLS, "Fireball": 3, "Flame Strike": 5, "Destructive Wave": 5}),
    "H  Tempest Cleric 9 / Sorcerer 3 (Quickened)": dict(
        cleric={5: 5, 8: 8, 12: 9}, mod={1: 5, 2: 5, 3: 5}, dw=True, toll=True,
        sp_lr={12: 6}, twin_ok=True, quick_ok=True,
        spells={**CLERIC_SPELLS, "Shatter": 2, "Call Lightning": 3, "Destructive Wave": 5, "Insect Plague": 5}),
    "E  Death Cleric 12 (Patch 8)": dict(
        cleric={5: 5, 8: 8, 12: 12}, mod={1: 5, 2: 5, 3: 5}, toll=True, reaper=True,
        spells={**CLERIC_SPELLS}),
    "F  Trickery Cleric 12 (her default)": dict(
        cleric={5: 5, 8: 8, 12: 12}, mod={1: 5, 2: 5, 3: 5}, toll=True,
        spells={**CLERIC_SPELLS}),
}

ENEMY = {
    (1, "std"): dict(level=5, ac=15, save=3, n=4),
    (2, "std"): dict(level=8, ac=16, save=4, n=4),
    (3, "solo"): dict(level=12, ac=18, save=5, n=4),
    (3, "party"): dict(level=12, ac=18, save=5, n=4),
    (3, "boss"): dict(level=12, ac=21, save=8, n=1),
}
# DC from gear on top of 8 + proficiency + modifier
GEAR = {
    (1, "std"): dict(dc=1, atk=1, cg=0, staff=False),                       # Melf's First Staff / Shadespell Circlet
    (2, "std"): dict(dc=2, atk=1, cg=2, staff=False),                       # Fistbreaker / Ketheric's Shield; Callous Glow
    (3, "solo"): dict(dc=8, atk=5, cg=2, staff=True, devout=True),          # Hood 2, Devout 2, Cloak 1, Markoheshkir 1, Helldusk Gloves 1, Feywild Sparks 1
    (3, "party"): dict(dc=3, atk=1, cg=2, staff=False, devout=True),        # Gale keeps the Weave kit + Markoheshkir: Devout 2 + Staff of Spell Power 1
    (3, "boss"): dict(dc=8, atk=5, cg=2, staff=True, devout=True),
}


SHAR_MIRROR = False   # Shar path: Mirror of Loss gives Shadowheart +2 to her casting ability in Act 3 (WIS/CHA 22)

# Defence at level 12 (Act 3). HP = BG3 averages (Cleric 8 + 5/level, Sorcerer 6 + 4/level, MC levels at average) + CON 16-17
# (+3). AC: everyone ends in Helldusk Armour (no proficiency needed) + Viconia's Walking Fortress = 24; in Act 2 the
# Dark Justiciar Half-Plate (medium, 16/17 + DEX 2) + shield beats every heavy armour available (Flawed Helldusk 18).
# Concentration = chance to pass a DC 10 Con save (damage <= 20).
DEFENCE = {
    "A": dict(hp=99, conc="War Caster: 91%", react="Warding Flare (any attack vs you/ally, every round)", heal="6th: Heal, Heroes' Feast"),
    "B": dict(hp=88, conc="Sorc start (proficient) + War Caster: 99%", react="Shield (+5 AC)", heal="1st only (Tempest 2)"),
    "C": dict(hp=99, conc="War Caster: 91%", react="Wrath of the Storm (2d8 vs melee hitter)", heal="6th: Heal, Heroes' Feast"),
    "D": dict(hp=93, conc="War Caster: 91%", react="Wrath of the Storm", heal="3rd: Mass Healing Word, Revivify"),
    "G": dict(hp=97, conc="Resilient (Con): 90%, 99% with Dark Justiciar / Greater Health advantage", react="Warding Flare + Shield (+5 AC)", heal="5th: Mass Cure Wounds, Greater Restoration"),
    "I": dict(hp=96, conc="Resilient (Con): 90%, 99% with Dark Justiciar / Greater Health advantage", react="Warding Flare + Shield (+5 AC)", heal="5th: Mass Cure Wounds (no Divine Intervention)"),
    "H": dict(hp=96, conc="Resilient (Con): 90%", react="Wrath of the Storm + Shield", heal="5th: Mass Cure Wounds (no Divine Intervention)"),
    "E": dict(hp=99, conc="War Caster: 91%", react="-", heal="6th"),
    "F": dict(hp=99, conc="War Caster: 91%", react="-", heal="6th"),
}


def build_ctx(name, act, kit):
    b = dict(BUILDS[name])
    if SHAR_MIRROR and act == 3:
        b["mod"] = {**b["mod"], 3: b["mod"][3] + 1}
    lvl = ENEMY[(act, kit)]["level"]
    if "spells_by" in b:
        b["spells"] = b["spells_by"][lvl]
    b.setdefault("spells", {})
    b["hots"] = b.get("hots_by", {}).get(lvl, 0)
    # Tempest 6 / Storm 6 is pure Tempest until level 6
    if name.startswith("D") and lvl == 5:
        b["spells"] = {"Spirit Guardians": 3, "Shatter": 2, "Call Lightning": 3}
    return Ctx(b, act, kit)


def table(cases):
    for (act, kit), label in cases:
        print()
        print(f"=== {label}")
        rows = []
        for name in BUILDS:
            c = build_ctx(name, act, kit)
            sp = c.b.get("sp_lr", {}).get(c.lvl, 0)
            best_row = None
            for x in range(0, sp // 3 + 1 if c.b.get("quick_ok") else 1):   # x quickened casts per long rest
                if sp:      # builds without sp_lr keep their own "quick" table
                    c.b["quick"] = {c.lvl: x / FIGHTS}
                    c.b["twin"] = {c.lvl: (sp - 3 * x) / FIGHTS if c.b.get("twin_ok") else 0}
                f, plan, sw = fight(c)
                if best_row is None or f > best_row[4]:
                    tag = (f"[{x} quickened + {sp - 3 * x if c.b.get('twin_ok') else 0} twinned per LR] ",) if sp else ()
                    best_row = (name, c.dc, nova(c), sustained(c), f, f * FIGHTS, tag + plan)
            rows.append(best_row)
        base = rows[0][4]
        for name, dc, nv, su, f, lr, plan in rows:
            print(f"{name[:46]:<46} DC {dc:2d} | nova {nv:6.1f} | sustained {su:5.1f} | fight {f:6.1f} "
                  f"({100 * (f / base - 1):+4.0f}% vs A) | long rest {lr:6.0f}")
            print(f"      most common plan: {' / '.join(plan)}")


if __name__ == "__main__":
    table([((1, "std"), "ACT 1 (level 5)"), ((2, "std"), "ACT 2 (level 8)"),
           ((3, "solo"), "ACT 3 (level 12) - Shadowheart gets the caster kit incl. Markoheshkir"),
           ((3, "party"), "ACT 3 (level 12) - Gale keeps Markoheshkir + Weave kit (owners.json)"),
           ((3, "boss"), "ACT 3 - single boss (AC 21, saves +8), full kit")])
    print()
    print("##### SENSITIVITY: Destructive Wrath maximises only the FIRST Chain Lightning target")
    CL_DW_ALL = False
    table([((3, "solo"), "ACT 3 solo kit")])
    CL_DW_ALL = True
    print()
    print("##### SENSITIVITY: Amulet of the Devout charge returns on short rest (bug note)")
    DEVOUT_SR = True
    table([((3, "solo"), "ACT 3 solo kit"), ((3, "party"), "ACT 3 party kit")])
    DEVOUT_SR = False
    print()
    print("##### SENSITIVITY: twinned cantrips cost 0 sorcery points (SpellPowerLevel 0)")
    TWIN_FREE = True
    table([((3, "solo"), "ACT 3 solo kit"), ((3, "party"), "ACT 3 party kit")])
    TWIN_FREE = False
    print()
    print("##### SENSITIVITY: Radiance of the Dawn adds the Cleric level, not the character level")
    ROTD_CLASS_LEVEL = True
    table([((3, "party"), "ACT 3 party kit"), ((3, "solo"), "ACT 3 solo kit")])
    ROTD_CLASS_LEVEL = False
    print()
    print("##### SHAR PATH: Mirror of Loss +2 WIS/CHA (Act 3)")
    SHAR_MIRROR = True
    table([((3, "party"), "ACT 3 party kit, Shar path")])
    SHAR_MIRROR = False
    print()
    print("##### DEFENCE (level 12)")
    for name in BUILDS:
        d = DEFENCE[name[0]]
        print(f"{name[:46]:<46} HP {d['hp']:3d} | AC 24 | conc {d['conc']} | reaction {d['react']} | healing {d['heal']}")
