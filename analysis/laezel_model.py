"""Lae'zel build model (BG3 Patch 8). Monte Carlo over an adventuring day: 3 boss fights of 4 rounds, a short rest
between fights (short-rest resources refill every fight, long-rest resources are shared by the 3 fights).

Inputs read from the game data (data/cache/stats_resolved.json, data/items_all/*.jsonl, Progressions.lsx):
- Great Weapon Master: toggle -5 attack / +10 damage; bonus-action attack after a crit or a kill.
- Great Weapon Fighting: Reroll(MeleeWeaponDamage,2,true) = reroll weapon dice of 1-2 once.
- Savage Attacker: Reroll(MeleeWeaponDamage,20,false) = reroll weapon dice, keep the higher (assumed per die).
- Divine Smite is an interrupt costing only a spell slot (no reaction): 2d8/3d8/4d8/5d8 for slot 1/2/3/4+.
- Improved Divine Smite (Paladin 11): +1d8 radiant on melee hits. Aura of Hate (Oathbreaker 7): +CHA mod melee damage.
- Vow of Enmity (Vengeance, Channel Oath, bonus action): Advantage on that target for 10 turns.
- Hold Person: WIS save vs spell DC, humanoids only; paralysed = melee hits within 3 m are crits, Advantage;
  save again at the end of each of its turns. Quickened Spell costs 3 sorcery points (Metamagic_Quickened).
- Haste (HASTE status): +1 action point; Extra Attack re-triggers on every action-point attack, so a hasted
  or surged action is a full Attack action (ExtraAttack passive, OnCast + HasUseCosts('ActionPoint')).
- Battle Master: 4 superiority dice at Fighter 3, +1 at Fighter 7, d8 -> d10 at Fighter 10 (ImprovedCombatSuperiority).
  Trip Attack: +die damage, STR save vs 8+prof+STR or Prone (melee Advantage until it stands).
- Champion: crit on 19 (ImprovedCritical). Giantslayer: STR modifier counted twice. Gauntlets of Hill Giant
  Strength: STR 23. Helldusk Armour: AC 21, -3 damage taken. Gloves of the Automaton: Advantage for 10 turns,
  once per short rest (bonus action). Halberd of Vigilance: +2, 1d10 + 1d4 force.
Simplifications: one boss target (no kills), crits double all dice (weapon, riders, smites, superiority die);
flat bonuses not doubled; no undead/fiend smite bonus; boss saves: STR +6, WIS +4 (Act 3), lower in Acts 1-2.
Act 3 glove/elixir kits (KITS) are compared per build and the best is reported; sensitivity runs vary fights per
long rest, rounds per fight and boss AC, plus Risky Ring (Advantage on every attack) and an ally's Haste.
Run: python analysis/laezel_model.py   (about 3-4 minutes)"""
import random

N_DAYS = 1500
FIGHTS, ROUNDS = 3, 4
SMITE_D8 = {1: 2, 2: 3, 3: 4, 4: 5, 5: 5}

# Act 3 glove / elixir variants (gloves slot): Elixir of Hill Giant Strength = STR 21 until a long rest
KITS = {
    "gauntlets": {},                                                       # Gauntlets of Hill Giant Strength, STR 23
    "automaton": dict(str_set=21, automaton=True),                         # Gloves of the Automaton + Hill Giant elixir
    "legacy":    dict(str_set=21, item=2),                                 # Legacy of the Masters + Hill Giant elixir
    "helldusk":  dict(str_set=21, extra_riders=[6]),                       # Helldusk Gloves (+1d6 fire) + elixir
}

# ------------------------------------------------------------------ builds per level (5 = end Act 1, 8 = Act 2, 12 = Act 3)
def mod(score): return (score - 10) // 2

ACT_GEAR = {   # weapon dice, enchantment, rider dice (die sizes), STR override, double STR, adv gloves
    1: dict(dice=[6, 6], ench=1, riders=[4], str_set=None, giant=False, automaton=False, ac_boss=16, wis=2, str_save=4,
            weapon="Githyanki Greatsword (+1, +1d4 psychic for githyanki)"),
    2: dict(dice=[10], ench=2, riders=[4], str_set=None, giant=False, automaton=True, ac_boss=18, wis=3, str_save=5,
            weapon="Halberd of Vigilance (+2, +1d4 force) + Gloves of the Automaton"),
    3: dict(dice=[6, 6], ench=3, riders=[], str_set=23, giant=True, automaton=False, ac_boss=19, wis=4, str_save=6,
            weapon="Balduran's Giantslayer + Gauntlets of Hill Giant Strength (STR 23)"),
}

def build(key, level):
    """Return the level-`level` profile of build `key`. Feats/levels follow Progressions.lsx."""
    b = dict(key=key, attacks=2, surge=False, sup=0, sup_die=8, crit=20, savage=False, gwf=True,
             slots={}, sp=0, vow=False, hp_quick=False, hp_action=False, haste=False, quick_haste=False,
             hate=0, ids=False, cha=16, str=17, prof=2 if level < 5 else (3 if level < 9 else 4), defence=0,
             aura=False, hp_die=10, save_prof=("WIS", "CHA"))
    f = lambda n: level >= n
    if key in ("BM", "CH"):                    # Fighter 12, start Fighter
        b.update(save_prof=("STR", "CON"), surge=f(2), cha=8)
        b["str"] = 17 + (2 if f(6) else 0)       # GWM 4, STR+2 6, Alert 8, Savage 12
        b["savage"] = f(12)
        b["attacks"] = 3 if f(11) else (2 if f(5) else 1)
        if key == "BM":
            b["sup"] = (4 if f(3) else 0) + (1 if f(7) else 0)
            b["sup_die"] = 10 if f(10) else 8
        else:
            b["crit"] = 19 if f(3) else 20
            b["defence"] = 1 if f(10) else 0     # Champion 10: second fighting style = Defence
    elif key == "SORC":                         # Vengeance Paladin 6 / Shadow Sorcerer 6 (BuildAdvisor order)
        pal, sor = min(level, 6), max(0, level - 6)
        b.update(vow=pal >= 3, hp_action=pal >= 5, aura=pal >= 6)
        b["attacks"] = 2 if pal >= 5 else 1
        b["cha"] = 16 + (2 if sor >= 4 else 0)   # GWM at Paladin 4, CHA+2 at Sorcerer 4
        b["sp"] = [0, 0, 2, 3, 4, 5, 6][sor]
        b["hp_quick"] = sor >= 3                 # Quickened is only in the Sorcerer-3 metamagic list
        b["haste"] = sor >= 5
        b["quick_haste"] = sor >= 5
        caster = pal // 2 + sor
        b["slots"] = MC_SLOTS[caster] if sor else PAL_SLOTS[pal]
    elif key in ("OATH", "VENG"):               # Paladin 12
        b.update(vow=(key == "VENG" and f(3)), hp_action=(key == "VENG" and f(5)), aura=f(6))
        b["attacks"] = 2 if f(5) else 1
        b["cha"] = 16 + (2 if f(8) else 0)       # GWM 4, CHA+2 8, Savage 12
        b["savage"] = f(12)
        b["ids"] = f(11)
        b["hate"] = mod(b["cha"]) if (key == "OATH" and f(7)) else 0
        b["haste"] = key == "VENG" and f(9)
        b["slots"] = PAL_SLOTS[level]
    elif key == "PBM":                          # Vengeance Paladin 6 / Battle Master 6 (Paladin first)
        pal, fig = min(level, 6), max(0, level - 6)
        b.update(vow=pal >= 3, hp_action=pal >= 5, aura=pal >= 6, surge=fig >= 2)
        b["attacks"] = 2 if pal >= 5 else 1
        b["sup"] = 4 if fig >= 3 else 0
        b["defence"] = 1 if fig >= 1 else 0      # Fighter 1 style: Defence (+1, Helldusk +1 more)
        b["cha"] = 16 + (2 if fig >= 4 else 0)   # GWM P4, CHA+2 F4, Savage F6
        b["savage"] = fig >= 6
        b["slots"] = PAL_SLOTS[pal]
    return b

PAL_SLOTS = {1: {}, 2: {1: 2}, 3: {1: 3}, 4: {1: 3}, 5: {1: 4, 2: 2}, 6: {1: 4, 2: 2}, 7: {1: 4, 2: 3}, 8: {1: 4, 2: 3},
             9: {1: 4, 2: 3, 3: 2}, 10: {1: 4, 2: 3, 3: 2}, 11: {1: 4, 2: 3, 3: 3}, 12: {1: 4, 2: 3, 3: 3}}
MC_SLOTS = {3: {1: 4, 2: 2}, 4: {1: 4, 2: 3}, 5: {1: 4, 2: 3, 3: 2}, 6: {1: 4, 2: 3, 3: 3}, 7: {1: 4, 2: 3, 3: 3, 4: 1},
            8: {1: 4, 2: 3, 3: 3, 4: 2}, 9: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1}}

NAMES = {
    "BM":   "A  Battle Master Fighter 12 (BuildAdvisor 'battlemaster')",
    "SORC": "B  Sorcadin: Vengeance Paladin 6 / Shadow Sorcerer 6 (BuildAdvisor 'sorcadin')",
    "VENG": "C  Vengeance Paladin 12 (Haste + Vow + Improved Divine Smite)",
    "OATH": "D  Oathbreaker Paladin 12 (Aura of Hate + Improved Divine Smite)",
    "PBM":  "E  Vengeance Paladin 6 / Battle Master 6",
    "CH":   "F  Champion Fighter 12 (crit 19)",
}

# ------------------------------------------------------------------ dice
R = random.Random(12345)
def d(n): return R.randint(1, n)
def wdie(n, gwf, savage):
    def one():
        x = d(n)
        return d(n) if gwf and x <= 2 else x
    return max(one(), one()) if savage else one()

# ------------------------------------------------------------------ one adventuring day
def day(b, act, humanoid, gwm, risky=False, resources=True, rounds=None, hp_open=False, dc_bonus=0,
        hold=True, ally_haste=False, hp_spare=False, kit=None):
    """One day; returns damage per round. hold=False: a Sorcadin opens with Quickened Haste even vs humanoids.
    kit: Act 3 glove/elixir variant (KITS)."""
    g = dict(ACT_GEAR[act]); g.update(KITS.get(kit, {}))
    rounds = rounds or ROUNDS
    b = dict(b)
    if not hold: b["hp_quick"] = False
    st = g["str_set"] if (g["str_set"] and g["str_set"] > b["str"]) else b["str"]
    sm = mod(st)
    atk = b["prof"] + sm + g["ench"] + g.get("item", 0) - (5 if gwm else 0)
    flat = g["ench"] + g.get("item", 0) + sm * (2 if g["giant"] else 1) + (10 if gwm else 0) + b["hate"]
    riders = list(g["riders"]) + ([8] if b["ids"] else []) + g.get("extra_riders", [])
    dc_spell = 8 + b["prof"] + mod(b["cha"]) + dc_bonus
    dc_man = 8 + b["prof"] + sm
    AC, WIS, STRS = g["ac_boss"], g["wis"], g["str_save"]
    slots = dict(b["slots"]) if resources else {}
    sp = b["sp"] if resources else 0
    per_round = [0.0] * (FIGHTS * rounds)
    sup_die = b["sup_die"]

    reserve = {}
    def take_slot(minlvl=1, smite=False):
        for lvl in sorted(slots, reverse=True):
            if lvl >= minlvl and slots[lvl] - (reserve.get(lvl, 0) if smite else 0) > 0:
                slots[lvl] -= 1
                return lvl
        return 0

    for fight in range(FIGHTS):
        sup = b["sup"] if resources else 0
        surge = b["surge"] and resources
        oath = 1 if resources else 0
        left = FIGHTS - fight - 1                     # slots kept for Haste / Hold Person in later fights
        reserve.clear()
        if b["haste"] and not (humanoid and b["hp_quick"]): reserve[3] = left
        if humanoid and (b["hp_quick"] or hp_open): reserve[2] = left
        if humanoid and b["hp_quick"]: reserve[3] = max(0, left - (sp // 3 - 1))
        smite_budget = (sum(slots.values()) - sum(reserve.values())) / (FIGHTS - fight) if resources else 0
        smites_used = 0
        vow = adv_gloves = held = hasted = False
        hold_tries = 0
        for rnd in range(rounds):
            dmg = 0.0
            ba_free = True
            actions = 1 + (1 if (hasted or (ally_haste and rnd >= 1)) else 0)
            # ---- bonus-action / opening decisions
            if rnd == 0 and g["automaton"] and resources:
                adv_gloves, ba_free = True, False
            quick_hold_r1 = b["hp_quick"] and humanoid and rnd == 0 and resources
            quick_haste_r1 = b["quick_haste"] and rnd == 0 and resources and not ally_haste and not (humanoid and b["hp_quick"])
            if b["vow"] and oath and not vow and ba_free and not quick_hold_r1 and not quick_haste_r1:
                vow, oath, ba_free = True, 0, False
            if surge and rnd == 0:
                actions += 1; surge = False
            haste_now = False
            if b["haste"] and resources and not ally_haste and rnd == 0 and slots.get(3, 0) + slots.get(4, 0) + slots.get(5, 0) > 0 and not (humanoid and b["hp_quick"]):
                if b["quick_haste"] and ba_free and (sp >= 3 or slots.get(3, 0) > 1):
                    if sp < 3: slots[3] -= 1; sp += 3
                    sp -= 3; take_slot(3); ba_free = False; haste_now = True   # haste from next round
                elif not b["quick_haste"]:
                    take_slot(3); actions -= 1; haste_now = True               # cast with the action
            # open with Hold Person as the action (no Quickened Spell yet)
            if humanoid and hp_open and b["hp_action"] and resources and rnd == 0 and actions >= 1 and slots.get(2, 0) > 0 and not b["hp_quick"]:
                slots[2] -= 1; actions -= 1; hold_tries += 1
                if d(20) + WIS < dc_spell: held = True
            # Vengeance-style: hold person with a spare action when hasted / surged
            if hp_spare and humanoid and b["hp_action"] and not b["hp_quick"] and resources and not held and actions >= 2 and hold_tries < 1 and slots.get(2, 0) > 0:
                slots[2] -= 1; actions -= 1; hold_tries += 1
                if d(20) + WIS < dc_spell: held = True
            crit_this_turn = False

            def swing(trip=False, bonus_die=0):
                nonlocal dmg, crit_this_turn, smites_used, sup
                adv = risky or vow or adv_gloves or held or prone[0]
                r = max(d(20), d(20)) if adv else d(20)
                crit = r >= b["crit"]
                hit = crit or (r != 1 and r + atk >= AC)
                if not hit:
                    return False
                if held: crit = True
                k = 2 if crit else 1
                x = flat + sum(wdie(s, b["gwf"], b["savage"]) for s in g["dice"] * k)
                x += sum(d(s) for s in riders * k)
                if bonus_die: x += sum(d(bonus_die) for _ in range(k))
                # smite: crits always (if a slot is left), plain hits while under the fight budget
                if slots and (crit or smites_used < smite_budget):
                    lvl = take_slot(smite=True)
                    if lvl:
                        smites_used += 1
                        x += sum(d(8) for _ in range(SMITE_D8[lvl] * k))
                dmg += x
                if crit: crit_this_turn = True
                if trip and not prone[0] and d(20) + STRS < dc_man:
                    prone[0] = True
                return True

            prone = [False]
            for a in range(actions):
                for i in range(b["attacks"]):
                    use = sup > (1 if b["key"] == "BM" else 0) and a == 0 and i == 0
                    if use: sup -= 1
                    swing(trip=use, bonus_die=sup_die if use else 0)
            # Sorcadin: quickened Hold Person after the attacks (Arcane Acuity not counted here)
            if humanoid and b["hp_quick"] and resources and not held and ba_free and hold_tries < 2:
                if sp < 3 and slots.get(3, 0) > 0: slots[3] -= 1; sp += 3
                if sp >= 3 and slots.get(2, 0) > 0:
                    sp -= 3; slots[2] -= 1; ba_free = False; hold_tries += 1
                    if d(20) + WIS < dc_spell: held = True
            if (crit_this_turn) and ba_free:          # GWM bonus attack (crit trigger; no kills on a boss)
                ba_free = False
                swing()
            if b["key"] == "BM" and sup > 0 and not held and d(2) == 1:   # Riposte: boss misses ~half its rounds
                sup -= 1; swing(bonus_die=sup_die)
            per_round[fight * rounds + rnd] = dmg
            if haste_now: hasted = True
            if held and d(20) + WIS >= dc_spell: held = False      # save at the end of its turn
    return per_round

def run(key, level, act, humanoid, risky=False, resources=True, gwm=None, dc_bonus=0, ally_haste=False, kit=None):
    """Best policy (GWM on/off, Hold Person opener or not, Sorcadin hold vs haste) for this build and scenario.
    Returns fight = mean damage per round over the day, burst = first two rounds of the first fight."""
    b = build(key, level)
    best = None
    opens = [(False, False), (True, False), (False, True)] if (humanoid and b["hp_action"] and resources) else [(False, False)]
    holds = [True, False] if (humanoid and b["hp_quick"]) else [True]
    for g_on in ([True, False] if gwm is None else [gwm]):
        for hp_open, hp_spare in opens:
            for hold in holds:
                tot = [0.0] * (FIGHTS * ROUNDS)
                for _ in range(N_DAYS):
                    for i, v in enumerate(day(b, act, humanoid, g_on, risky, resources, hp_open=hp_open,
                                              dc_bonus=dc_bonus, hold=hold, ally_haste=ally_haste, hp_spare=hp_spare, kit=kit)):
                        tot[i] += v
                avg = [t / N_DAYS for t in tot]
                res = dict(fight=sum(avg) / len(avg), burst=avg[0] + avg[1], gwm=g_on, hp_open=hp_open, hp_spare=hp_spare, hold=hold)
                if best is None or res["fight"] > best["fight"]:
                    best = res
    return best

# ------------------------------------------------------------------ trash fight (AoE value): 4 enemies, 45 HP, AC 16
def trash(key, level=12, act=3, n=4, hp=45, ac=16, trials=3000):
    b = build(key, level); g = ACT_GEAR[act]
    st = max(b["str"], g["str_set"] or 0); sm = mod(st)
    rounds_total = 0
    for _ in range(trials):
        hps = [hp] * n; rnd = 0; surge = b["surge"]; sup = b["sup"]
        while any(h > 0 for h in hps) and rnd < 10:
            rnd += 1
            actions = 1 + (1 if surge and rnd == 1 else 0)
            ba = True; extra = 0
            for a in range(actions):
                for i in range(b["attacks"]):
                    tgt = next((j for j, h in enumerate(hps) if h > 0), None)
                    if tgt is None: break
                    gwm = hps[tgt] > 15                 # finish low targets without the -5
                    atk = b["prof"] + sm + g["ench"] - (5 if gwm else 0)
                    r = d(20); crit = r >= b["crit"]
                    if crit or (r != 1 and r + atk >= ac):
                        k = 2 if crit else 1
                        x = g["ench"] + sm * (2 if g["giant"] else 1) + (10 if gwm else 0) + b["hate"]
                        x += sum(wdie(s, b["gwf"], b["savage"]) for s in g["dice"] * k) + sum(d(s) for s in (g["riders"] + ([8] if b["ids"] else [])) * k)
                        hps[tgt] -= x
                        if (hps[tgt] <= 0 or crit) and ba: extra = 1
            if extra and ba:
                tgt = next((j for j, h in enumerate(hps) if h > 0), None)
                if tgt is not None:
                    r = d(20)
                    if r >= b["crit"] or r + b["prof"] + sm + g["ench"] - 5 >= ac:
                        hps[tgt] -= g["ench"] + sm * 2 + 10 + 7 + b["hate"]
            surge = surge and rnd == 0
        rounds_total += rnd
    return rounds_total / trials

# ------------------------------------------------------------------ defence (Act 3 kit)
def defence(key):
    b = build(key, 12)
    ac = 21 + 1 + b["defence"] * 2          # Helldusk 21, Helm of Balduran +1, Defence style +1 (+1 Helldusk passive)
    con = 23                                # Amulet of Greater Health
    if key == "SORC": hp = 10 + 5 * 6 + 6 * 4 + 12 * mod(con)
    else: hp = 10 + 11 * 6 + 12 * mod(con)
    p_hit = max(0.05, min(0.95, (21 - (ac - 11)) / 20))           # boss +11 to hit, 2 attacks of 2d8+6
    p_hit_dis = p_hit ** 2                                       # Cloak of Displacement: first attack at disadvantage
    taken = (p_hit_dis + p_hit) * (15 - 3)                       # Helldusk -3 per hit
    wis_save = 1 + (b["prof"] if "WIS" in b["save_prof"] else 0) + (mod(b["cha"]) if b["aura"] else 0) + mod(10 if key in ("BM", "CH") else 8)
    p_fail_wis = max(0.05, min(0.95, (18 - 1 - wis_save) / 20))
    return dict(ac=ac, hp=hp, taken=taken, rounds_to_drop=hp / taken, wis_bonus=wis_save, p_fail_wis18=p_fail_wis)

def mix(key, level=12, act=3, **kw):
    """50% humanoid / 50% other bosses."""
    h, o = run(key, level, act, True, **kw), run(key, level, act, False, **kw)
    return (h["fight"] + o["fight"]) / 2, max(h["burst"], o["burst"]), h, o

def best_kit(key):
    scores = {kit: mix(key, kit=kit)[0] for kit in KITS}
    return max(scores, key=scores.get), scores

if __name__ == "__main__":
    global_fr = (FIGHTS, ROUNDS)
    keys = list(NAMES)
    print(f"Act 3 (level 12), boss AC 19, {FIGHTS} fights x {ROUNDS} rounds per long rest, 50% humanoid bosses.")
    print("Damage per round (fight average). Glove kits: " + ", ".join(KITS))
    print(f"{'build':<84} {'gauntlets':>9} {'best kit':>18} {'burst R1+2':>10} {'sustain':>8} {'Risky':>6} {'ally Haste':>10}")
    kits, table = {}, {}
    for k in keys:
        kit, sc = best_kit(k)
        kits[k], table[k] = kit, sc[kit]
        _, burst, h, o = mix(k, kit=kit)
        sus = run(k, 12, 3, False, resources=False, kit=kit)["fight"]
        rk = mix(k, kit="legacy", risky=True)[0]
        ah = mix(k, kit=kit if kit != "automaton" else "legacy", ally_haste=True)[0]
        print(f"{NAMES[k]:<84} {sc['gauntlets']:9.1f} {sc[kit]:7.1f} ({kit:>9}) {burst:10.1f} {sus:8.1f} {rk:6.1f} {ah:10.1f}")
        print(f"{'':<84} humanoid {h['fight']:.1f} (GWM {'on' if h['gwm'] else 'off'}, Sorcadin hold={h['hold']}) / other {o['fight']:.1f}")
    print("\nSensitivity (best kit): fights per long rest x rounds per fight, boss AC")
    for fr in [(4, 4), (3, 3), (2, 5), (5, 3)]:
        FIGHTS, ROUNDS = fr
        print(f"  {fr[0]} fights x {fr[1]} rounds: " + "  ".join(f"{k} {mix(k, kit=kits[k])[0]:.1f}" for k in keys))
    FIGHTS, ROUNDS = global_fr
    for ac in (16, 22):
        old = ACT_GEAR[3]["ac_boss"]; ACT_GEAR[3]["ac_boss"] = ac
        print(f"  AC {ac}: " + "  ".join(f"{k} {mix(k, kit=kits[k])[0]:.1f}" for k in keys))
        ACT_GEAR[3]["ac_boss"] = old
    print("\nPower curve (fight average): Act 1 = level 5 vs AC 16, Act 2 = level 8 vs AC 18 (Automaton gloves), Act 3 best kit")
    for k in keys:
        print(f"{NAMES[k]:<84} Act1 {mix(k, 5, 1)[0]:5.1f}  Act2 {mix(k, 8, 2)[0]:5.1f}  Act3 {table[k]:5.1f}")
    print("\nTrash fight (4 enemies, 45 HP, AC 16, no long-rest resources): rounds to clear")
    for k in keys:
        print(f"{NAMES[k]:<84} {trash(k):4.2f}")
    print("\nControl at level 12")
    for k in keys:
        b = build(k, 12)
        spell = 8 + 4 + mod(b["cha"]) if k in ("SORC", "VENG", "OATH", "PBM") else None
        man = 8 + 4 + mod(23) if k in ("BM", "PBM") else None
        p_hold = None if not spell else max(0.05, min(0.95, (spell - 1 - 4) / 20))
        print(f"{NAMES[k]:<84} spell DC {spell}  manoeuvre DC {man}  Hold Person lands vs WIS+4: {p_hold}")
    print("\nDefence (Act 3 kit: Helldusk Armour, Helm of Balduran, Cloak of Displacement, Amulet of Greater Health)")
    for k in keys:
        x = defence(k)
        print(f"{NAMES[k]:<84} AC {x['ac']} HP {x['hp']} taken/round {x['taken']:4.1f} rounds-to-drop {x['rounds_to_drop']:4.1f}"
              f" WIS save {x['wis_bonus']:+d} fail DC18 {x['p_fail_wis18']:.0%}")
