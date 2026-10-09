"""Astarion damage model (level 12, Act 3 gear). Numbers come from the game data in data/items_all and the class
passives in data/cache/stats_resolved.json (Sharpshooter -5/+10 incl. off-hand ranged, Archery +2 incl. off-hand,
Fast Hands = +1 bonus action, Two-Weapon Fighting adds the ability modifier to off-hand damage).
Simplifications: Sneak Attack once per turn when the turn has advantage; crits double dice only; Dex 20 (+5),
proficiency +4; Legacy of the Masters (+2 attack/+2 damage) on every build; Dread Ambusher extra attack +1d6."""

def p_hit(bonus, ac, adv):
    need = max(2, min(20, ac - bonus))
    p = (21 - need) / 20
    return 1 - (1 - p) ** 2 if adv else p

def p_crit(adv):
    return 1 - 0.95 ** 2 if adv else 0.05

def attack(bonus, dice, flat, ac, adv):
    ph, pc = p_hit(bonus, ac, adv), p_crit(adv)
    return ph * (dice + flat) + pc * dice     # crit adds the dice once more

BUILDS = {
  "A  Gloom 5 / Assassin 4 / BM 3, Titanstring longbow + Cloud Giant elixir (BuildAdvisor)":
     dict(atk=5 + 4 + 2 + 1 - 5 + 2, dice=4.5, flat=5 + 1 + 8 + 10 + 2, main=2, off=0, sa=7, surge=2, da=True),
  "B  Gloom 5 / Thief 4 / BM 3, dual hand crossbows (Hellfire +2 / Hand Crossbow +2), TWF style":
     dict(atk=5 + 4 + 2 + 2 - 5 + 2, dice=3.5, flat=5 + 2 + 10 + 2, main=2, off=2, sa=7, surge=2, da=True),
  "C  Arcane Archer Fighter 11 / Ranger 1, Titanstring longbow + Cloud Giant elixir":
     dict(atk=5 + 4 + 2 + 1 - 5 + 2, dice=4.5, flat=5 + 1 + 8 + 10 + 2, main=3, off=0, sa=0, surge=3, da=False),
}

def turn(b, ac, adv, first):
    n = b["main"] + b["off"] + (b["surge"] + (1 if b["da"] else 0) if first else 0)
    dmg = n * attack(b["atk"], b["dice"], b["flat"], ac, adv)
    if first and b["da"]:
        dmg += p_hit(b["atk"], ac, adv) * 3.5
    if b["sa"] and adv:
        miss_all = (1 - p_hit(b["atk"], ac, adv)) ** n
        dmg += (1 - miss_all) * b["sa"]
    return dmg

if __name__ == "__main__":
    for ac in (16, 19, 22):
        print(f"--- target AC {ac}")
        for name, b in BUILDS.items():
            s0 = turn(b, ac, False, False); s1 = turn(b, ac, True, False); r1 = turn(b, ac, True, True)
            print(f"{name[:2]} sustained {s0:5.1f} (no adv) {s1:5.1f} (adv) | round 1 with adv {r1:5.1f}")
