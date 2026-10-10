"""Per-build combat model: damage per round, durability and a single score for one loadout (build, act, items).

Layers
  1. Character sheet (abilities, HP, AC, weapon attack rows, spell DC / attack) = tools/build_sets_artifact.py
     compute_sheet, the reference the Sets page is verified against. Only its unconditional numbers are used.
  2. This model adds what a sheet cannot show, all read from the game data through mech.py:
     - conditional boosts of items AND of the build's class / feat passives (Rage, Tavern Brawler, GWM,
       Sharpshooter, Brutal Critical, Improved Critical, Savage Attacker, Great Weapon Fighting, Empowered
       Evocation, Potent Spellcasting, Agonising Blast, Hexblade's Curse, Spell Sniper ...), evaluated per attack /
       spell event with the condition reader;
     - triggers (OnDamage / OnAttack / OnCast passives): extra damage, explosions, statuses on the target
       (Reverberation, Radiating Orb, Prone, Daze ...) and on the character (Arcane Acuity, Lightning Charges,
       Arcane Synergy ...) with stack averages over a 4-round fight;
     - item spells (UnlockSpell) that deal damage, as often as their cooldown allows AND the action economy
       allows: a caster's action spells share one action a round (strongest first, the cantrip gets the rest), a
       weapon build casts one only when it beats the Attack action it replaces, a bonus-action one only in a free
       bonus action; a tooltip that lists all projectiles' damage is counted once;
     - situational conditions as documented uptimes (ENEMY_TYPES, ENEMY_HP, STEALTH_DC): creature types of the
       act's enemies, the wearer's own tags (race), stealth openers (armour stealth disadvantage), killing blows
       (damage of a hit / enemy HP), "until rest" statuses (share of the day after the first application),
       concentration kept against hits (CON saves);
     - the build's own round plan (PLANS): attacks per action, bonus-action attacks (off-hand, Enraged Throw,
       Fast Hands), Action Surge, Sneak Attack, smites, Hunter's Mark / Hex, Vow of Enmity, superiority dice,
       Dread Ambusher, cantrips, nukes, concentration damage, Channel Divinity (Destructive Wrath, Radiance of
       the Dawn).
  3. Durability: incoming damage per round from an act's typical enemies (INCOMING: damage-type mix) vs AC,
     saves (bonuses, Advantage / Disadvantage, "succeed a failed save" interrupts), resistances per type, damage
     reduction, enemy attack penalties; rounds survived R = HP / incoming. Conditions (THREATS: Prone, forced
     movement, Frightened, Charmed, Held, Stunned, Poisoned, Blinded, Restrained, difficult terrain, Burning)
     cost turns unless the gear's status immunities / Grounded / saves stop them.
  score = offence x (1 - turns lost) x sqrt(sat(R) / sat(R0)) (R0 = the planned build with no items) - damage
  dealt over the time the character stays up and acts, durability at half weight. Control (save-or-lose spells,
  Prone, Daze) adds damage-equivalents.

Assumptions shared with the companion analyses (analysis/*_model.py): 4 rounds per fight, 4 fights per long rest,
3 short-rest windows per long rest, 4 enemies per fight; enemy AC / saves / attacks per act in ENEMY.
Unverified mechanics are SWITCHES (both results are reported by run.py).
"""
import math
import re

import mech
import odata

BSA = odata.BSA
ROUNDS, FIGHTS, SR_WINDOWS, ENEMIES = 4, 4, 3, 4
SR_COVER = min(1.0, SR_WINDOWS / FIGHTS)       # a once-per-short-rest feature covers 3 of 4 fights
ENEMY = {1: dict(ac=15, save=2, atk=5, dmg=9.0, dc=13, save_dmg=7.0),
         2: dict(ac=17, save=3, atk=7, dmg=13.0, dc=15, save_dmg=10.0),
         3: dict(ac=19, save=4, atk=9, dmg=17.0, dc=17, save_dmg=14.0)}
CTRL_EQ = 2.0                                   # rounds of one enemy's damage a successful control spell prevents
HIT_REMOVED = 0.6                               # uptime of a "until you are hit" status
R_SAT = 3.0 * ROUNDS                            # durability saturation (rounds), see sat()

# ----------------------------------------------------------------------------------- encounter assumptions
# Everything situational is an uptime taken from these tables (model assumptions, not game data; the game data
# only says WHEN an effect works, these say HOW OFTEN that is the case in an act's typical fights).
#
# Creature types of an act's enemies (share of the enemies met; GOBLIN is a part of HUMANOID). A condition
# Tagged('<TYPE>') on the enemy is true for that share: Goblinbane, Aberration Hunters' Amulet, Feller of
# Monsters, undead / fiend riders. Act 1: goblins, gnolls, Absolute cultists, spiders, harpies, the crypts' undead,
# intellect devourers; Act 2: shadow-cursed undead, Sharrans, Absolute army, the Moonrise mind flayers; Act 3:
# Flaming Fist / Bhaalists / Gortash's men, devils (House of Hope, Avernus), vampire spawn, Steel Watch, the brain.
ENEMY_TYPES = {
    1: dict(HUMANOID=0.55, GOBLIN=0.30, BEAST=0.08, MONSTROSITY=0.08, ABERRATION=0.07, UNDEAD=0.08, GIANT=0.03,
            PLANT=0.02, FIEND=0.03, ELEMENTAL=0.02, CONSTRUCT=0.02, DRAGON=0.01, GITHYANKI=0.03),
    2: dict(HUMANOID=0.45, GOBLIN=0.05, UNDEAD=0.25, SHADOW=0.10, ABERRATION=0.08, MONSTROSITY=0.05, FIEND=0.05,
            BEAST=0.04, CONSTRUCT=0.03, ELEMENTAL=0.02, GITHYANKI=0.01),
    3: dict(HUMANOID=0.45, GOBLIN=0.02, FIEND=0.15, UNDEAD=0.12, CONSTRUCT=0.08, ABERRATION=0.07, MONSTROSITY=0.04,
            ELEMENTAL=0.03, GIANT=0.02, BEAST=0.03, DRAGON=0.01, GITHYANKI=0.02),
}
# Average HP of an enemy: a hit kills with probability (damage of the hit / enemy HP), the expected killing blows
# of a character being its damage over the enemies' HP whoever else attacks them (IsKillingBlow, "after a kill").
ENEMY_HP = {1: 28.0, 2: 45.0, 3: 70.0}
# Stealth openers: a Gloom Stalker / Thief / Assassin starts a fight hidden when its Stealth check beats the enemy
# passive Perception below (Disadvantage from armour, Advantage / bonuses from gear); then its first attack is
# made while sneaking (HasStatus('SNEAKING_*') / SG_Invisible conditions, Advantage) and the enemies are
# Surprised in round 1. Other builds never open from stealth. Initiative: enemies +2.
STEALTH_DC = {1: 12, 2: 14, 3: 15}
STEALTH_SUBCLASSES = {("Ranger", "Gloom Stalker"), ("Rogue", "Thief"), ("Rogue", "Assassin")}
ENEMY_INIT = 2
# Incoming damage types per act: weapon attacks ("attack") and saving-throw spells / breath / traps ("save").
INCOMING = {
    1: dict(attack=dict(Slashing=0.30, Piercing=0.30, Bludgeoning=0.25, Fire=0.05, Poison=0.05, Necrotic=0.05),
            save=dict(Fire=0.30, Poison=0.15, Thunder=0.10, Cold=0.10, Lightning=0.10, Acid=0.10, Necrotic=0.10,
                      Psychic=0.05)),
    2: dict(attack=dict(Slashing=0.25, Piercing=0.25, Bludgeoning=0.20, Necrotic=0.15, Cold=0.05, Fire=0.05,
                        Radiant=0.05),
            save=dict(Necrotic=0.30, Fire=0.15, Cold=0.15, Lightning=0.10, Psychic=0.10, Radiant=0.10, Thunder=0.10)),
    3: dict(attack=dict(Slashing=0.25, Piercing=0.20, Bludgeoning=0.20, Fire=0.15, Necrotic=0.10, Lightning=0.05,
                        Force=0.05),
            save=dict(Fire=0.30, Necrotic=0.15, Lightning=0.15, Psychic=0.10, Cold=0.10, Force=0.10, Thunder=0.10)),
}
PHYSICAL = ("Slashing", "Piercing", "Bludgeoning")
# Conditions enemies try to put on the character: attempts per fight on a character at exposure 1.0 (scaled by the
# build's exposure), the save that resists it, the turns it costs when it lands and extra damage. A turn lost costs
# that share of the character's damage (score x (1 - turns lost per round)). Immunity: StatusImmunity(<id>) of any
# listed id (exact id or status group), Attribute(Grounded) for forced movement. Advantage / Disadvantage on the
# save and "succeed a failed save" interrupts (Infernal Evasion, Ring of Evasion) come from the gear's game data.
THREATS = [
    # name, immunity ids, save ability ("STR|DEX" = the better of the two: a shove contest), attempts per fight
    # per act, turns lost, extra damage (x act enemy damage), a spell (for "succeed a spell save" interrupts)
    ("knocked prone", ("SG_Prone", "PRONE"), "STR|DEX", {1: 0.25, 2: 0.3, 3: 0.35}, 0.2, 0.0, False),
    ("forced movement (shoves, pushes, Thunderwave)", ("@Grounded",), "STR", {1: 0.2, 2: 0.25, 3: 0.3}, 0.25, 0.3,
     False),
    ("frightened", ("SG_Frightened", "FRIGHTENED"), "WIS", {1: 0.05, 2: 0.15, 3: 0.15}, 0.4, 0.0, True),
    ("charmed / dominated", ("SG_Charmed", "CHARMED"), "WIS", {1: 0.03, 2: 0.08, 3: 0.15}, 1.0, 0.0, True),
    ("held / paralysed", ("SG_Paralyzed", "PARALYZED", "HOLD_PERSON"), "WIS", {1: 0.05, 2: 0.12, 3: 0.12}, 1.0, 0.0,
     True),
    ("stunned (Mind Blast)", ("SG_Stunned", "STUNNED"), "INT", {1: 0.05, 2: 0.05, 3: 0.1}, 1.0, 0.5, True),
    ("poisoned", ("SG_Poisoned", "POISONED"), "CON", {1: 0.2, 2: 0.15, 3: 0.15}, 0.2, 0.0, False),
    ("blinded", ("SG_Blinded", "BLINDED"), "CON", {1: 0.05, 2: 0.08, 3: 0.08}, 0.3, 0.0, True),
    ("restrained / webbed", ("SG_Restrained", "RESTRAINED", "WEB", "ENSNARED"), "DEX", {1: 0.15, 2: 0.1, 3: 0.1}, 0.3,
     0.0, False),
    ("difficult terrain", ("SG_DifficultTerrain", "DIFFICULT_TERRAIN"), None, {1: 0.3, 2: 0.3, 3: 0.3}, 0.1, 0.0,
     False),
    ("burning", ("BURNING",), "DEX", {1: 0.2, 2: 0.2, 3: 0.3}, 0.0, 0.3, False),
]
THREAT_DC = {1: 13, 2: 15, 3: 17}
LOST_CAP = 0.6
# Per-rest item spells: once per short rest = SR_WINDOWS casts per long rest (2 short rests -> 3 windows).
RACE_TAGS = {"High Elf": {"ELF", "HIGHELF"}, "Human": {"HUMAN"}, "Zariel Tiefling": {"TIEFLING"},
             "Githyanki": {"GITHYANKI"}, "High Half-Elf": {"HALFELF"}, "White Dragonborn": {"DRAGONBORN"}}

# unverified mechanics (both results are reported): default = what Builds.lua / the analyses assume
SWITCHES = {
    "enraged_throw_each_ba": dict(default=True, text="Enraged Throw on every bonus action (Fast Hands: 2 per turn)"),
    "gwm_on_throws": dict(default=False, text="Great Weapon Master -5/+10 also on thrown weapons"),
    "dw_chain_all": dict(default=True, text="Destructive Wrath maximises every Chain Lightning target"),
    "hexcurse_eb": dict(default=True, text="Hexblade's Curse (+proficiency, crit 19) applies to Eldritch Blast"),
    "rotd_char_level": dict(default=True, text="Radiance of the Dawn adds the character level (not the Cleric level)"),
    "twf_offhand_xbow": dict(default=True, text="Two-Weapon Fighting adds DEX to off-hand hand crossbow shots"),
}

# ----------------------------------------------------------------------------------------------- build plans
# What the build does in a round (the companion analyses' rotations, generalised). Spell ids are the game's.
PLANS = {
    "thx": dict(mode="ranged", offhand="ranged", hunters_mark=True, dread=True),
    "gloomassassin": dict(mode="ranged", hunters_mark=True, dread=True, assassin=True),
    "giants": dict(mode="throw", rage="giant"),
    "throwzerker": dict(mode="throw", rage="frenzy"),
    "throw_zerk7_thief3": dict(mode="throw", rage="frenzy"),
    "throw_zerk5_thief4": dict(mode="throw", rage="frenzy"),
    "bmgiant": dict(mode="melee", superiority=True),
    "battlemaster": dict(mode="melee", superiority=True),
    "sorcadin": dict(mode="melee", smite=True, vow=True, control=["Target_HoldPerson"]),
    "lockadin": dict(mode="melee", smite=True, vow=True, hexblade=True, hex=True),
    "tempestevoker": dict(mode="caster", cantrip="Projectile_FireBolt",
                          nukes=[("Zone_LightningBolt", 5), ("Projectile_Fireball", 5), ("Projectile_IceStorm", 10),
                                 ("Cone_ConeOfCold", 11)], dw=True, control=["Target_HoldPerson"]),
    "evoker": dict(mode="caster", cantrip="Projectile_FireBolt",
                   nukes=[("Projectile_Fireball", 5), ("Zone_LightningBolt", 5), ("Cone_ConeOfCold", 9)]),
    "stormsorc": dict(mode="caster", cantrip="Projectile_FireBolt",
                      nukes=[("Zone_LightningBolt", 7), ("Projectile_IceStorm", 10), ("Cone_ConeOfCold", 11)],
                      dw=True, quicken_from=5, control=["Target_HoldPerson"]),
    "lightcleric": dict(mode="caster", cantrip="Target_SacredFlame", cleric_cantrip=True,
                        conc=("Shout_SpiritGuardians_Radiant", 5), nukes=[("Projectile_GuidingBolt", 1)],
                        rotd=True, spiritual=True),
    "lightquick": dict(mode="caster", cantrip="Target_SacredFlame", cleric_cantrip=True,
                       conc=("Shout_SpiritGuardians_Radiant", 5),
                       nukes=[("Projectile_GuidingBolt", 1), ("Projectile_Fireball", 5),
                              ("Shout_DestructiveWave_Radiant", 9)], rotd=True, spiritual=True, quicken_from=12),
    "sorlock": dict(mode="caster", cantrip="Projectile_EldritchBlast", hex=True,
                    nukes=[("Projectile_Fireball", 8), ("Cone_ConeOfCold", 12)], quicken_from=5,
                    control=["Target_HoldPerson"]),
    "hexsorlock": dict(mode="caster", cantrip="Projectile_EldritchBlast", hex=True, hexblade=True,
                       nukes=[("Projectile_Fireball", 8)], quicken_from=5),
}

FEAT_PASSIVES = {"Tavern Brawler": ["TavernBrawler"], "Great Weapon Master": ["GreatWeaponMaster_BonusDamage",
                                                                               "GreatWeaponMaster_BonusAttack"],
                 "Sharpshooter": ["Sharpshooter_AllIn"], "Savage Attacker": ["SavageAttacker"],
                 "Spell Sniper": ["SpellSniper_Critical"]}
STYLE_PASSIVES = {"Great Weapon Fighting": ["FightingStyle_GreatWeaponFighting"]}
# (class, subclass shown name or None, class level, passive) - the game's passive ids from Progressions.lsx
CLASS_PASSIVES = [("Barbarian", None, 9, "BrutalCritical"), ("Fighter", "Champion", 3, "ImprovedCritical"),
                  ("Rogue", "Thief", 3, "FastHands"), ("Wizard", "Evocation", 10, "EmpoweredEvocation"),
                  ("Cleric", "Light", 8, "PotentSpellcasting"), ("Warlock", None, 2, "AgonizingBlast"),
                  ("Warlock", "Hexblade", 1, "HexbladesCurse"), ("Ranger", "Gloom Stalker", 3, "DreadAmbusher"),
                  ("Rogue", "Assassin", 3, "Assassinate_Initiative")]
# origin characters' own passives (game data: Karlach's Infernal Fury, 1d4 Fire on weapon hits while raging)
ORIGIN_PASSIVES = {"karlach": ["Karlach_Infernal_Fury"]}
SAVE_PROF = {"Barbarian": ("STR", "CON"), "Fighter": ("STR", "CON"), "Ranger": ("STR", "DEX"), "Rogue": ("DEX", "INT"),
             "Wizard": ("INT", "WIS"), "Sorcerer": ("CON", "CHA"), "Cleric": ("WIS", "CHA"), "Paladin": ("WIS", "CHA"),
             "Warlock": ("WIS", "CHA"), "Monk": ("STR", "DEX"), "Bard": ("DEX", "CHA"), "Druid": ("INT", "WIS")}
FULL_CASTER = {"Wizard", "Cleric", "Sorcerer", "Druid", "Bard"}
SLOT_TABLE = {0: [], 1: [2], 2: [3], 3: [4, 2], 4: [4, 3], 5: [4, 3, 2], 6: [4, 3, 3], 7: [4, 3, 3, 1],
              8: [4, 3, 3, 2], 9: [4, 3, 3, 3, 1], 10: [4, 3, 3, 3, 2], 11: [4, 3, 3, 3, 2, 1], 12: [4, 3, 3, 3, 2, 1]}
SUB_ALIAS = {"The Hexblade": "Hexblade", "Draconic Bloodline": "Draconic"}
WEAPON_KINDS = {"Attack", "WeaponAttack"}
RANGED_KINDS = {"RangedWeaponAttack", "RangedOffHandWeaponAttack"}


def rage_damage(barb):
    return 2 if barb < 9 else 3 if barb < 16 else 4


class State:
    """One evaluation: build at an act's level with a loadout."""

    def __init__(self, W, cid, bid, act, loadout, switches, choice=None, respec=None):
        self.W, self.cid, self.bid, self.act = W, cid, bid, act
        self.level = odata.ACT_LEVEL[act]
        self.sw = dict({k: v["default"] for k, v in SWITCHES.items()}, **(switches or {}))
        self.plan = PLANS.get(bid, dict(mode="melee"))
        self.BI = W.build_input(cid, bid)
        if respec:
            # a tuned respec (respec.py): abilities, feat / ASI picks, fighting styles, cantrip; classes,
            # subclasses and the level split stay the build's
            self.BI = dict(self.BI, base=dict(respec["base"]), feats=[dict(f) for f in respec["feats"]],
                           styles=list(respec["styles"]))
            if respec.get("cantrip") and self.plan.get("cantrip"):
                self.plan = dict(self.plan, cantrip=respec["cantrip"])
        # the sheet engine expects "Hexblade" / "Draconic"; the scores data carries the game's names ("The
        # Hexblade", "Draconic Bloodline") - without this the sheet misses Hex Warrior (CHA attacks) and Draconic
        # Resilience (a known sheet-engine gap)
        self.BI = dict(self.BI, subs=[dict(s_, n=SUB_ALIAS.get(s_["n"], s_["n"])) for s_ in self.BI["subs"]])
        seq = self.BI["seq"][: self.level]
        self.classes = {}
        for c in seq:
            self.classes[c] = self.classes.get(c, 0) + 1
        self.subs = {s["cls"]: s["n"] for s in self.BI["subs"]}
        self.feats = [f["n"] for f in self.BI["feats"] if f["lv"] is None or f["lv"] <= self.level]
        self.styles = list(self.BI["styles"]) if self._styles_ok() else []
        self.loadout = {k: v for k, v in loadout.items() if v}
        self.unknown = set()
        self.notes = []
        set_items = {s: {"sid": sid} for s, sid in self.loadout.items()}
        IB = {sid: W.item_boosts(sid) for sid in self.loadout.values()}
        self.sheet = BSA.compute_sheet(W.D, self.BI, set_items, IB, self.level)
        self.mods = self.sheet["mods"]
        self.prof = self.sheet["prof"]
        boosts = BSA.collect_boosts(W.D, set_items, IB)
        self.item_boosts = []
        for x in boosts:
            r = BSA.resolve_cond(x["cond"], self.styles, self.feats) if x["cond"] else None
            if r is False:
                continue
            if r is True:
                x["cond"] = None
            self.item_boosts.append(x)
        body = W.items.get(self.loadout.get("Breast") or "") or {}
        self.armour_cat = ((body.get("armour") or {}).get("category")) if body else None
        off = W.items.get(self.loadout.get("OffHand") or "") or {}
        self.shield = bool((off.get("armour") or {}).get("shield"))
        self.offhand_used = bool(off)
        self.mechs = {s: mech.item_mech(W, sid) for s, sid in self.loadout.items()}
        self.choice = dict(choice or {})
        for slot, status in self.choice.items():
            im = self.mechs.get(slot)
            if im is None:
                continue
            for cond, name, args in mech.add_status(W, im, status):
                self.item_boosts.append({"cond": cond, "name": name, "args": args, "src": im.name, "via": status,
                                         "scope": None, "h": "", "ch": "", "_status": True})
        self.rages = "Barbarian" in self.classes and self.plan.get("rage") is not None
        self.raging = 1.0 if (self.rages and self.armour_cat != "Heavy") else 0.0
        b = W.build_entry(cid, bid)
        self.profile = b.get("profile") or {}
        melee_w = max([self.profile.get("attacks", {}).get(m, 0) for m in ("melee2h", "melee1h", "reach")] or [0])
        self.exposure = 1.5 if self.plan["mode"] in ("melee",) else 1.3 if self.plan["mode"] == "throw" else \
            1.0 if self.plan["mode"] == "ranged" else (1.1 if self.armour_cat == "Heavy" else 0.85)
        del melee_w
        self.obscured = 0.35 if self.subs.get("Ranger") == "Gloom Stalker" else 0.15
        self.self_uptime, self.target_uptime = {}, {}
        self.target_prone = 0.0
        self._toggle = {}
        self.class_passives = self._class_passives()
        self.enemy_types = ENEMY_TYPES[act]
        self.tags = {"HUMANOID", "PLAYABLE"} | RACE_TAGS.get(W.race(cid), set())
        self.persist = set()                 # self statuses applied "until rest" (duration -1)
        self.sneak_share = 0.0               # share of this build's attacks made while sneaking (set per evaluation)
        # BoostConditions gate a passive's boosts for the WEARER (Aberration Hunters' Amulet: githyanki only). The
        # sheet reader keeps either the boost's own IF or the passive's BoostConditions; here both apply: the
        # BoostConditions become the boost's weight, evaluated for the wearer.
        for x in self.item_boosts:
            bc = ((W.stats.get(x.get("via") or "") or {}).get("BoostConditions") or "").strip()
            if not bc:
                continue
            if x["cond"] == bc:
                x["cond"] = None
            x["bw"] = mech.cond_p(bc, mech.Ctx(self, {}, "self"))
        self.p_open = self._stealth_open()
        dex_init = self.sheet.get("init") or self.mods.get("DEX", 0)
        p_first = min(0.95, max(0.05, 0.5 + 0.05 * (dex_init - ENEMY_INIT)))
        # an attack lands before the target's first turn: round 1, acting first (or the enemies are Surprised)
        self.first_strike = max(p_first, self.p_open) / ROUNDS
        self.surprised = self.p_open / ROUNDS       # round-1 attacks against Surprised enemies
        self.concentrating = self._concentration()

    def _stealth_open(self):
        """Chance the fight starts with this character hidden (stealth builds only, see STEALTH_DC)."""
        if not any(s.lower() in (self.subs.get(c) or "").lower() for c, s in STEALTH_SUBCLASSES):
            return 0.0
        bonus = self.mods.get("DEX", 0) + self.prof * (2 if self.classes.get("Rogue") else 1)  # Rogue expertise
        adv = dis = 0.0
        body = self.W.items.get(self.loadout.get("Breast") or "") or {}
        if (body.get("armour") or {}).get("stealth_disadvantage"):
            dis = 1.0
        for x in self.item_boosts:
            g = x["args"]
            w = x.get("bw", 1.0) * (0.5 if x["cond"] else 1.0)
            if x["name"] == "Skill" and len(g) >= 2 and g[0] == "Stealth":
                bonus += w * mech.avg_expr(g[1], {})
            elif x["name"] == "RollBonus" and len(g) >= 3 and g[0] == "SkillCheck" and g[2] == "Stealth":
                bonus += w * mech.avg_expr(g[1], {})
            elif x["name"] == "Advantage" and len(g) >= 2 and g[0] == "Skill" and g[1] == "Stealth":
                adv = max(adv, w)
            elif x["name"] == "Disadvantage" and len(g) >= 2 and g[0] == "Skill" and g[1] == "Stealth":
                dis = max(dis, w)
        return stealth_p(bonus, STEALTH_DC[self.act], adv, dis)

    def _concentration(self):
        """Share of rounds the build is concentrating (IsConcentrating conditions): a concentration plan holds it
        from round 2 unless a hit breaks it (CON save DC 10 per hit taken, War Caster / gear Advantage); casters
        without one keep a buff or control spell up a third of the time."""
        if not (self.plan.get("conc") or self.plan.get("hex") or self.plan.get("hunters_mark")):
            return 0.3 if self.plan["mode"] == "caster" else 0.0
        E = ENEMY[self.act]
        start = self.BI["seq"][0] if self.BI["seq"] else None
        con = self.mods.get("CON", 0) + (self.prof if "CON" in SAVE_PROF.get(start, ()) else 0)
        adv = 1.0 if any(f.lower().startswith("war caster") for f in self.feats) else 0.0
        for x in self.item_boosts:
            if x["name"] == "Advantage" and x["args"] and x["args"][0] == "Concentration":
                adv = max(adv, x.get("bw", 1.0))
        broke = self.exposure * mech.p_hit(E["atk"], self.sheet["ac"]) * mech.p_fail(10, con, adv)
        return conc_uptime(min(1.0, broke))


    def _styles_ok(self):
        return True

    def has_passive(self, p):
        if p in self.class_passives:
            return True
        low = re.sub(r"[^a-z]", "", p.lower())
        if low.startswith("fightingstyle"):
            want = low[len("fightingstyle"):][:6]
            return any(re.sub(r"[^a-z]", "", s.lower()).replace("defense", "defence").startswith(want[:5])
                       for s in self.styles)
        return any(re.sub(r"[^a-z]", "", f.lower()).startswith(low[:8]) for f in self.feats)

    def _class_passives(self):
        out = []
        for cls, sub, lv, p in CLASS_PASSIVES:
            if self.classes.get(cls, 0) >= lv and (sub is None or sub.lower() in (self.subs.get(cls) or "").lower()):
                out.append(p)
        for f in self.feats:
            for k, ps in FEAT_PASSIVES.items():
                if f.lower().startswith(k.lower()):
                    out += ps
        for s in self.styles:
            for k, ps in STYLE_PASSIVES.items():
                if s.lower().startswith(k.lower()):
                    out += ps
        if self.rages:
            out.append("Rage_Rage_Boosts_2" if self.classes.get("Barbarian", 0) >= 9 else "Rage_Rage_Boosts")
        out += [p for p in ORIGIN_PASSIVES.get(self.cid, []) if p in self.W.stats]
        return out

    # toggles evaluated per event (GreatWeaponMaster(context.Source) / Sharpshooter(context.Source))
    def gwm_on(self, ev):
        if not self._toggle.get("gwm"):
            return 0.0
        if ev.get("kind") == "throw":
            return 1.0 if self.sw["gwm_on_throws"] else 0.0
        return 1.0 if ev.get("melee") and ev.get("weapon") and ev.get("heavy") else 0.0

    def ss_on(self, ev):
        if not self._toggle.get("ss"):
            return 0.0
        return 1.0 if ev.get("ranged") and ev.get("weapon") else 0.0


def stealth_p(bonus, dc, adv=0.0, dis=0.0):
    """Skill check d20 + bonus >= dc (no natural 1 / 20 rule) with Advantage / Disadvantage probabilities."""
    p = min(1.0, max(0.0, (21 - (dc - bonus)) / 20))
    a, d = adv * (1 - dis), dis * (1 - adv)
    return a * (1 - (1 - p) ** 2) + d * p * p + (1 - a - d) * p


def conc_uptime(broke_per_round, rounds=ROUNDS):
    """Share of a fight's rounds a concentration spell cast in round 1 is up (rounds 2..N), each round lost with
    probability broke_per_round."""
    keep = 1.0 - broke_per_round
    return sum(keep ** (r - 1) for r in range(2, rounds + 1)) / rounds


def persist_uptime(rate, horizon=ROUNDS * FIGHTS):
    """Average uptime over a long-rest day of a status that lasts until rest once applied, applied at `rate` per
    round (Poisson): the share of the day after the first application = 1 - (1 - e^-x) / x, x = rate x horizon."""
    x = rate * horizon
    if x <= 0:
        return 0.0
    return 1.0 - (1.0 - math.exp(-x)) / x


# ================================================================================================ boosts
def lmv_names(st):
    n = mech.lmv_names(st.level)
    rd = rage_damage(st.classes.get("Barbarian", 0))
    n.update({"LMV_RageDamage": rd, "LMVD_RageDamage": "0", "LMVX_RageDamage": "0",
              "LMV_SuperiorityDie": 5.5 if st.classes.get("Fighter", 0) >= 10 else 4.5,
              "LMVD_SuperiorityDie": "1d10" if st.classes.get("Fighter", 0) >= 10 else "1d8"})
    for k, v in st.mods.items():
        n[BSA.ABIL_NAMES[k] + "Modifier"] = v
    n.update({"ProficiencyBonus": st.prof, "Level": st.level, "CharacterLevel": st.level,
              "SpellCastingAbilityModifier": spell_mod(st)})
    return n


def spell_mod(st):
    sp = st.sheet.get("spell")
    return st.mods.get(sp["abil"], 0) if sp else 0


def all_extra_boosts(st, dyn):
    """[(weight, cond, name, args, src, scope_slot, hand_source)] boosts this model adds on top of the sheet.
    weight = uptime / stack multiplier (1 for gear and class passives)."""
    out = []
    for x in st.item_boosts:
        counted = False if x.get("_status") else mech.sheet_counts(x)
        out.append((x.get("bw", 1.0), x["cond"], x["name"], x["args"], x["src"], x.get("scope"), "item", counted))
    S = st.W.stats
    for p in st.class_passives:
        ps = S.get(p) or {}
        bc = (ps.get("BoostConditions") or "").strip() or None
        for cond, name, args in mech.parse_boosts(ps.get("Boosts") or ""):
            c2 = " and ".join(x for x in (bc, cond) if x) or None
            out.append((1.0, c2, name, args, p, None, "class", False))
    if st.plan.get("rage") == "giant" and st.raging:
        gs = "RAGE_GIANT_2" if st.classes.get("Barbarian", 0) >= 9 and S.get("RAGE_GIANT_2") else "RAGE_GIANT"
        for cond, name, args in mech.parse_boosts((S.get(gs) or {}).get("Boosts") or ""):
            out.append((1.0, cond, name, args, "Giant's Rage", None, "class", False))
    for (w, cond, name, args, src) in dyn:
        out.append((w, cond, name, args, src, None, "dynamic", False))
    return out


def roll_kind_applies(kind, ev):
    at = ev.get("attack_type", "")
    if kind in ("Attack",):
        return bool(ev.get("attack_roll"))
    if kind == "WeaponAttack":
        return bool(ev.get("weapon"))
    if kind == "MeleeWeaponAttack":
        return at in ("MeleeWeaponAttack",)
    if kind == "MeleeOffHandWeaponAttack":
        return at == "MeleeOffHandWeaponAttack"
    if kind == "RangedWeaponAttack":
        return at == "RangedWeaponAttack"
    if kind == "RangedOffHandWeaponAttack":
        return at == "RangedOffHandWeaponAttack"
    if kind in ("SpellAttack",):
        return bool(ev.get("spell") and ev.get("attack_roll"))
    if kind == "RangedSpellAttack":
        return at == "RangedSpellAttack"
    if kind == "MeleeSpellAttack":
        return at == "MeleeSpellAttack"
    if kind == "RangedUnarmedAttack":
        return at == "RangedUnarmedAttack"
    if kind in ("UnarmedAttack", "MeleeUnarmedAttack"):
        return at in ("MeleeUnarmedAttack",)
    return False


def event_mods(st, ev, boosts, names):
    """Sum the extra boosts that apply to one event. -> dict(hit, flat, dice, crit_red, crit_dice, adv, dc, rer,
    save_bonus...)."""
    m = dict(hit=0.0, flat=0.0, dice=0.0, crit_red=0.0, crit_dice=0.0, adv=[], dc=0.0, reroll=None, savage=False,
             entity=0.0, minroll=0.0, autocrit=0.0)
    ctx = mech.Ctx(st, ev, "boost")
    weapon_like = ev.get("weapon") or ev.get("kind") == "throw"
    for (w, cond, name, args, src, scope, origin, counted) in boosts:
        if scope and scope != ev.get("slot"):
            continue
        if counted and weapon_like and name != "DamageBonus":
            continue                         # the sheet row already has it
        if counted and weapon_like and name == "DamageBonus":
            continue
        if counted and ev.get("spell") and name in ("RollBonus", "SpellSaveDC"):
            continue                         # the sheet's spell DC / attack already has it
        p = w * (mech.cond_p(cond, ctx) if cond else 1.0)
        if p <= 0:
            continue
        a0 = args[0] if args else ""
        if name == "RollBonus" and len(args) >= 2:
            if roll_kind_applies(a0, ev):
                v = mech.avg_expr(args[1], names)
                m["hit"] += p * v
        elif name == "DamageBonus" and args:
            if ev.get("kind") == "throw" and origin != "dynamic" and counted:
                continue
            m["flat"] += p * mech.avg_expr(args[0], names)
            m["dice"] += p * mech.dice_part(args[0], names)
        elif name in ("CharacterWeaponDamage", "WeaponDamage") and args and weapon_like:
            if name == "WeaponDamage" and counted:
                continue
            v = mech.avg_expr(args[0], names)
            m["flat"] += p * v
            m["dice"] += p * mech.dice_part(args[0], names)
        elif name == "CharacterUnarmedDamage" and args and ev.get("unarmed") and ev.get("melee"):
            m["flat"] += p * mech.avg_expr(args[0], names)
        elif name == "EntityThrowDamage" and args and ev.get("kind") == "throw":
            v = mech.avg_expr(args[0], names)
            m["entity"] += p * v
            m["dice"] += p * mech.dice_part(args[0], names)
        elif name == "ReduceCriticalAttackThreshold" and args and ev.get("attack_roll"):
            m["crit_red"] += p * mech.avg_expr(args[0], names)
        elif name == "CriticalHitExtraDice" and len(args) >= 2 and ev.get("attack_roll"):
            if roll_kind_applies(args[1], ev) or (args[1] == "MeleeWeaponAttack" and ev.get("melee") and
                                                  ev.get("weapon")):
                m["crit_dice"] += p * mech.avg_expr(args[0], names)
        elif name == "Advantage" and args and a0 in ("AttackRoll", "AllAttacks"):
            if ev.get("attack_roll"):
                m["adv"].append(p)
        elif name == "SpellSaveDC" and args and ev.get("spell"):
            m["dc"] += p * mech.avg_expr(args[0], names)
        elif name == "Reroll" and len(args) >= 2 and ev.get("weapon") and ev.get("melee"):
            if args[0] == "MeleeWeaponDamage":
                thr = int(mech.avg_expr(args[1], names))
                if thr >= 20:
                    m["savage"] = p >= 0.5
                else:
                    m["reroll"] = thr if p >= 0.5 else m["reroll"]
        elif name == "CriticalDamageOnHit" and ev.get("attack_roll"):
            m["autocrit"] = 1 - (1 - m["autocrit"]) * (1 - min(1.0, p))   # every hit is a critical hit
        elif name == "MinimumRollResult" and args and a0 == "Damage":
            m["minroll"] = max(m["minroll"], p)
    return m


die_gain = mech.die_gain


# ================================================================================================ events
def weapon_row(st, slot):
    for r in st.sheet["attacks"]:
        if r["slot"] == slot:
            return r
    return None


def weapon_dice(st, slot):
    rec = st.W.items.get(st.loadout.get(slot) or "") or {}
    w = rec.get("weapon") or {}
    two = "Twohanded" in (w.get("properties") or [])
    use_ver = w.get("versatile") and not two and slot == "MainHand" and not st.offhand_used
    d = w.get("versatile") if use_ver else w.get("damage")
    m = mech.DICE.match(d or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0), rec


def make_weapon_events(st):
    """Attack events of a weapon build for one round (counts are per round, averaged over a 4-round fight)."""
    plan = st.plan
    n_att = st.sheet["nAtt"]
    evs = []
    fighter = st.classes.get("Fighter", 0)
    surge = (n_att * SR_COVER / ROUNDS) if fighter >= 2 else 0.0
    bonus_actions = 1.0
    if st.classes.get("Rogue", 0) >= 3 and "Thief" in (st.subs.get("Rogue") or ""):
        bonus_actions += 1.0                 # Fast Hands (FastHands: ActionResource(BonusActionPoint,1,0))
    ba_used_per_round = 0.0
    if plan["mode"] == "ranged":
        main_slot = "Ranged"
    elif plan["mode"] == "throw":
        main_slot = "MainHand"
    else:
        main_slot = "MainHand"
    row = weapon_row(st, main_slot)
    if row is None:
        return evs, {}
    (nd, sides), rec = weapon_dice(st, main_slot)
    w = rec.get("weapon") or {}
    props = w.get("properties") or []
    base = dict(slot=main_slot, weapon=plan["mode"] != "throw", attack_roll=True, dtypes={row.get("dt") or "Slashing"},
                main_dtype=row.get("dt"), base_hit=row["hit"], base_dmg=row["avg"],
                base_dice=nd * (sides + 1) / 2 + sum(mech.dice_part(e) for e in (w.get("extra_damage") or [])),
                die=(nd, sides), heavy="Heavy" in props or "Twohanded" in props or (
                    "Versatile" in props and not st.offhand_used))
    for e in w.get("extra_damage") or []:
        mm = re.match(r"\d+d\d+\s+(\w+)", e)
        if mm:
            base["dtypes"] = set(base["dtypes"]) | {mm.group(1)}
        mx = re.match(r"([A-Za-z]+Modifier)\s+(\w+)$", e)
        if mx:
            # an ability-modifier rider (Balduran's Giantslayer: STR again): the sheet engine reads only dice riders
            base["base_dmg"] += max(0, mech.avg_expr(mx.group(1), lmv_names(st)))
            st.notes.append(f"{rec.get('name')}: {mx.group(1)} rider added (not on the sheet)")
    if plan["mode"] == "ranged":
        base.update(kind="weapon", ranged=True, melee=False, attack_type="RangedWeaponAttack")
    elif plan["mode"] == "throw":
        thrown = "Thrown" in props
        returning = _returns(st, rec)
        if plan.get("rage") == "giant" and st.classes.get("Barbarian", 0) >= 6:
            # Elemental Cleaver (ELEMENTAL_CLEAVER_<type>: WeaponProperty(Thrown), ItemReturnToOwner,
            # WeaponDamage(1d6,<type>)); the element is picked for the gear (Lightning here)
            thrown = returning = True
            base["rider_flat"] = base.get("rider_flat", 0.0) + 3.5
            base["rider_dice"] = base.get("rider_dice", 0.0) + 3.5
            base["dtypes"] = set(base["dtypes"]) | {"Lightning"}
        if not thrown:
            # not a throwing weapon: the throw is an improvised 1d4 object instead of the weapon dice
            base["base_dmg"] = base["base_dmg"] - nd * (sides + 1) / 2 + 2.5
            base["base_dice"] = 2.5
        base.update(kind="throw", ranged=True, melee=False, unarmed=True, weapon=False,
                    attack_type="RangedUnarmedAttack", returning=returning, thrown=thrown,
                    any_dmg=throw_status_damage(st, rec))
        if not returning:
            base["throw_penalty"] = 0.5      # it has to be picked up again: half the throws (model rule)
    else:
        base.update(kind="weapon", melee=True, ranged=False, attack_type="MeleeWeaponAttack")
    special = {}
    # round 1 costs: Rage (bonus action), Hunter's Mark / Hex / Vow / Hexblade's Curse (bonus action, once per fight)
    if st.rages:
        ba_used_per_round += 1.0 / ROUNDS
    hm = plan.get("hunters_mark") and st.classes.get("Ranger", 0) >= 2
    hex_ = plan.get("hex") and st.classes.get("Warlock", 0) >= 1
    if hm or hex_:
        ba_used_per_round += 1.0 / ROUNDS
        special["mark"] = (ROUNDS - 1) / ROUNDS * 3.5   # 1d6 per hit from round 2 on (concentration)
    if plan.get("vow") and st.classes.get("Paladin", 0) >= 3 and "Vengeance" in (st.subs.get("Paladin") or ""):
        ba_used_per_round += SR_COVER / ROUNDS
        special["vow_adv"] = SR_COVER * (ROUNDS - 1) / ROUNDS
    if plan.get("hexblade") and st.classes.get("Warlock", 0) >= 1:
        ba_used_per_round += SR_COVER / ROUNDS
        st.target_uptime["HEXBLADES_CURSE"] = SR_COVER * (ROUNDS - 1) / ROUNDS
    free_ba = max(0.0, bonus_actions - ba_used_per_round)
    main = dict(base, n=(n_att + surge) * base.get("throw_penalty", 1.0), name="attack")
    evs.append(main)
    # bonus-action attacks
    if plan.get("offhand") == "ranged" and st.loadout.get("RangedOff"):
        orow = weapon_row(st, "RangedOff")
        if orow:
            (ond, osides), orec = weapon_dice(st, "RangedOff")
            ow = orec.get("weapon") or {}
            dmg = orow["avg"]
            if not st.sw["twf_offhand_xbow"] and any(s.startswith("Two-Weapon") for s in st.styles):
                dmg -= max(0, st.mods.get("DEX", 0))
            evs.append(dict(base, slot="RangedOff", n=free_ba, name="off-hand shot", attack_type="RangedOffHandWeaponAttack",
                            base_hit=orow["hit"], base_dmg=dmg, die=(ond, osides),
                            base_dice=ond * (osides + 1) / 2 + sum(mech.dice_part(e) for e in (ow.get("extra_damage") or [])),
                            dtypes={orow.get("dt") or "Piercing"}))
            free_ba = 0.0
    if plan.get("rage") == "frenzy" and st.classes.get("Barbarian", 0) >= 3 and st.raging:
        # Enraged Throw: bonus action, no cooldown in the stats (Throw_FrenziedThrow), Prone on a hit, +STR again
        per_turn = free_ba if st.sw["enraged_throw_each_ba"] else min(1.0, free_ba)
        if per_turn > 0:
            # Throw_FrenziedThrow: DealDamage(ThrownWeapon+StrengthModifier) - the STR modifier a second time
            evs.append(dict(base, n=per_turn, name="Enraged Throw", enraged=True,
                            base_dmg=base["base_dmg"] + max(0, st.mods.get("STR", 0)), applies_prone=True))
            free_ba -= per_turn
    if "GreatWeaponMaster_BonusAttack" in st.class_passives and plan["mode"] == "melee" and free_ba > 0:
        # GWM: a bonus-action attack after a critical hit or a kill (n set per evaluation, see _evaluate)
        evs.append(dict(base, n=0.0, name="GWM bonus attack", gwm_ba=free_ba))
    if plan.get("dread") and st.classes.get("Ranger", 0) >= 3:
        evs.append(dict(base, n=1.0 / ROUNDS, name="Dread Ambusher", rider_flat=4.5))
    if plan.get("superiority") and fighter >= 3:
        dice = 5 if fighter >= 7 else 4
        die = 5.5 if fighter >= 10 else 4.5
        special["superiority"] = dice * SR_COVER / ROUNDS * die     # damage dice per round (Trip / Precision)
        special["trip_prone"] = min(1.0, dice * SR_COVER / ROUNDS)
    # item spells (UnlockSpell) that deal damage, per rest: a bonus-action one only in a free bonus action, an
    # action one in place of an Attack action - kept only when it beats that action's attacks (see _evaluate)
    for ev in item_spell_events(st):
        if ev["cost"] == "bonus":
            ev["n"] = min(ev["n"], free_ba)
            free_ba -= ev["n"]
        else:
            ev["displaces"] = n_att * base.get("throw_penalty", 1.0)
        if ev["n"] > 0:
            evs.append(ev)
    special["free_ba"] = free_ba
    return evs, special


def item_spell_events(st):
    """Damage item spells of the loadout (UnlockSpell on the item, its passives or a chosen attunement), used as
    often as their cooldown allows over a long rest: one event per spell with n = casts per round."""
    W = st.W
    out = []
    seen = set()
    for slot, im in st.mechs.items():
        for spid, hand in im.spells:
            if hand == "o" and slot not in ("OffHand", "RangedOff") or hand == "m" and slot not in ("MainHand", "Ranged"):
                continue
            if (slot, spid) in seen:
                continue
            seen.add((slot, spid))
            sp = mech.read_spell(W, spid, st.level)
            if not sp or sp["cantrip"]:
                continue
            stats = W.stats.get(spid) or {}
            cdn = stats.get("Cooldown") or ""
            per_lr = SR_WINDOWS if "ShortRest" in cdn else 1 if "Rest" in cdn else 0
            if not per_lr:
                continue
            cost = "bonus" if "BonusActionPoint" in (stats.get("UseCosts") or "") else "action"
            out.append(spell_event(st, sp, per_lr / (ROUNDS * FIGHTS), "item spell: " + (W.items[im.sid].get("name") or ""),
                                   dict(item_spell=True, dw_target=True, cost=cost, per_lr=per_lr)))
    return out


def throw_status_damage(st, rec):
    """Damage a throw deals hit or miss because of a status the thrown weapon carries (the throw spells'
    SpellProperties: TARGET:IF(HasStatus('<X>', ThrownObject)):ApplyStatus(<Y>) -> Y / its chain OnApplyFunctors
    DealDamage; Nyrulna's 3d4 Thunder explosion). Counted on the main target only."""
    S = st.W.stats
    carried = set(mech.split_top(((rec.get("boosts_raw") or {}).get("TemplateStatusList") or "")))
    if not carried:
        return 0.0
    names = lmv_names(st)
    props = (S.get("Throw_Throw") or {}).get("SpellProperties") or ""
    tot = 0.0
    for m in re.finditer(r"IF\(HasStatus\('(\w+)',\s*context\.HitDescription\.ThrownObject\)\):(\w+)\(([^;]*)\)", props):
        if m.group(1) not in carried:
            continue
        if m.group(2) == "DealDamage":
            tot += mech.avg_expr(m.group(3).split(",")[0], names)
        elif m.group(2) == "ApplyStatus":
            todo, seen = [m.group(3).split(",")[0].strip()], set()
            while todo:
                sid = todo.pop()
                if sid in seen:
                    continue
                seen.add(sid)
                for _c, name, args in mech.functor_list((S.get(sid) or {}).get("OnApplyFunctors") or ""):
                    if name == "DealDamage" and args:
                        tot += mech.avg_expr(args[0], names)
                    elif name == "ApplyStatus" and args:
                        todo.append(args[1] if args[0].upper() in ("SELF", "TARGET") and len(args) > 1 else args[0])
    return tot


def _returns(st, rec):
    txt = " ".join((e.get("text") or "").lower() for e in rec.get("effects") or [])
    return "return" in txt


def caster_level(classes):
    """Spell-slot level: full casters + half of Paladin / Ranger (multiclass rule); a single-class half caster
    uses its own table (level / 2 rounded up)."""
    full = sum(v for c, v in classes.items() if c in FULL_CASTER)
    half = classes.get("Paladin", 0) + classes.get("Ranger", 0)
    if not full and half and sum(1 for c in ("Paladin", "Ranger") if classes.get(c)) == 1 and half >= 2:
        return (half + 1) // 2
    return full + half // 2


def pact_slots(classes):
    """Warlock pact slots: (number, slot level) - Warlock 1: 1 x 1st, 2: 2 x 1st, 3-4: 2nd, 5-6: 3rd, 7-8: 4th,
    9+: 5th, 11+: 3 slots."""
    w = classes.get("Warlock", 0)
    if not w:
        return 0, 0
    n = 1 if w == 1 else 3 if w >= 11 else 2
    return n, min(5, (w + 1) // 2)


def slots(classes):
    return list(SLOT_TABLE.get(min(12, caster_level(classes)), []))


def spell_event(st, sp, n, name, extra=None):
    ev = dict(kind="spell", spell=True, cantrip=sp["cantrip"], spell_id=sp["id"], school=sp["school"],
              spell_level=sp["slot"], attack_roll=sp["roll"] == "attack", save=sp["roll"] == "save",
              attack_type="RangedSpellAttack" if sp["roll"] == "attack" else "", ranged=True, melee=False,
              weapon=False, dtypes={t for _e, t in sp["dmg"]}, main_dtype=sp["dmg"][0][1], n=n, name=name, sp=sp,
              save_abil=sp.get("save_abil"),
              cleric_cantrip=bool(st.plan.get("cleric_cantrip") and sp["cantrip"]))
    if extra:
        ev.update(extra)
    return ev


def make_caster_events(st):
    W, plan = st.W, st.plan
    evs = []
    lvl = st.level
    sl = slots(st.classes)
    # damage slots: two thirds of the level-3+ slots (the rest: Haste, Counterspell, Hold Person ...)
    big = sum(sl[2:]) * 2 / 3 if len(sl) >= 3 else 0.0
    small = sum(sl[:2]) * 0.5
    rounds_lr = ROUNDS * FIGHTS
    used = 0.0
    conc = plan.get("conc")
    if conc and lvl >= conc[1] and big > 0:
        sp = mech.read_spell(W, conc[0], lvl, slot_level=min(len(sl), 3))
        if sp:
            casts = min(FIGHTS, big)
            big -= casts
            per_round = casts / FIGHTS * (ROUNDS - 1) / ROUNDS   # ticks from round 2 on
            evs.append(spell_event(st, sp, per_round, "Spirit Guardians", dict(targets=2.0, conc_tick=True)))
            used += casts / FIGHTS / ROUNDS
    # nukes: best available, highest slots first
    cands = []
    for sid, lv_min in plan.get("nukes") or []:
        if lvl >= lv_min:
            base = W.stats.get(sid) or {}
            need = int(base.get("Level") or 1)
            if need <= len(sl):
                top = len(sl)
                sp = mech.read_spell(W, sid, lvl, slot_level=top if top > need else None)
                if sp:
                    cands.append((sp, need))
    nuke_rounds = 0.0
    sorc_points = st.classes.get("Sorcerer", 0) + sum(sl[:2])     # Sorcery Points + low slots turned into points
    if cands:
        cands.sort(key=lambda t: -_raw_spell_value(st, t[0]))
        sp, need = cands[0]
        pool = big if need >= 3 else big + small
        casts = min(rounds_lr * 0.6, pool)                       # the slots limit the casts per long rest
        nuke_rounds = casts / rounds_lr
        # Quickened Spell (3 Sorcery Points) moves a cast to the bonus action; it does not add casts
        quick = min(casts, sorc_points / 3) if plan.get("quicken_from") and lvl >= plan["quicken_from"] else 0.0
        sorc_points -= 3 * quick
        q = quick / casts if casts else 0.0
        evs.append(spell_event(st, sp, nuke_rounds, "levelled spell", dict(a_cost=1.0 - q, b_cost=q, budget=True)))
    # Channel Divinity
    cd = 0
    if st.classes.get("Cleric", 0) >= 2:
        cd = 1 + (1 if st.classes.get("Cleric", 0) >= 6 else 0)
    cd_per_round = cd * SR_COVER / ROUNDS
    if plan.get("rotd") and cd:
        sp = mech.read_spell(W, "Shout_RadianceOfTheDawn", lvl)
        if sp:
            lv_for = lvl if st.sw["rotd_char_level"] else st.classes.get("Cleric", 0)
            sp = dict(sp, dmg=[(e.replace("Level", str(lv_for)), t) for e, t in sp["dmg"]], targets=3.0)
            evs.append(spell_event(st, sp, cd_per_round, "Radiance of the Dawn", dict(a_cost=1.0, b_cost=0.0,
                                                                                      budget=True)))
    if plan.get("spiritual") and lvl >= 3:
        # Spiritual Weapon: bonus action summon, 1d8 + WIS force per round from round 2 (one 2nd-level slot a fight)
        sp = {"id": "Target_SpiritualWeapon", "dmg": [("1d8+SpellCastingAbilityModifier", "Force")], "roll": "attack",
              "save_abil": None, "half": False, "targets": 1, "chain": 0, "beams": 1, "school": "Evocation",
              "level": 2, "slot": 2, "conc": False, "cantrip": False, "is_spell": True}
        evs.append(spell_event(st, sp, (ROUNDS - 1) / ROUNDS, "Spiritual Weapon", dict(attack_type="MeleeSpellAttack",
                                                                                       melee=True, ranged=False)))
    # action economy per round: one action and one bonus action. Reserved first: a control spell a fight (plan
    # "control") and the concentration cast; then the levelled spells, Channel Divinity and the per-rest item
    # spells share what is left, the strongest cast first (each up to its own per-rest budget); the cantrip gets
    # the rest. A bonus-action item spell needs a free bonus action; a quickened levelled spell uses one.
    action_left = 1.0 - (1.0 / ROUNDS if plan.get("control") else 0.0) - used
    ba_left = 1.0 - (1.0 / ROUNDS if plan.get("spiritual") and lvl >= 3 else 0.0) \
        - (1.0 / ROUNDS if plan.get("hex") or plan.get("hunters_mark") else 0.0)
    items = item_spell_events(st)
    for ev in items:
        ev.update(a_cost=0.0 if ev["cost"] == "bonus" else 1.0, b_cost=1.0 if ev["cost"] == "bonus" else 0.0,
                  budget=True)
    budgeted = [ev for ev in evs if ev.get("budget")] + items
    budgeted.sort(key=lambda ev: -_raw_spell_value(st, ev["sp"]))
    for ev in budgeted:
        cap = ev["n"]
        if ev["a_cost"]:
            cap = min(cap, max(0.0, action_left) / ev["a_cost"])
        if ev["b_cost"]:
            cap = min(cap, max(0.0, ba_left) / ev["b_cost"])
        ev["n"] = max(0.0, cap)
        action_left -= ev["n"] * ev["a_cost"]
        ba_left -= ev["n"] * ev["b_cost"]
    evs += [ev for ev in items if ev["n"] > 0]
    # cantrip in the remaining rounds
    can = plan.get("cantrip")
    if can:
        sp = mech.read_spell(W, can, lvl)
        if sp:
            left = max(0.0, action_left)
            n = left
            if plan.get("quicken_from") and lvl >= plan["quicken_from"] and sp["id"] == "Projectile_EldritchBlast":
                # Quickened Eldritch Blast: the Sorcery Points the levelled spells left / 3 per long rest
                n += min(max(0.0, ba_left), max(0.0, sorc_points) / 3 / rounds_lr)
            beams = sp["beams"]
            for _b in range(1):
                evs.append(spell_event(st, sp, n * beams, "cantrip"))
    # Hex (Warlock): 1d6 necrotic per hit from round 2, a bonus action and concentration
    if plan.get("hex") and st.classes.get("Warlock", 0) >= 1:
        for ev in evs:
            if ev.get("spell_id") == "Projectile_EldritchBlast":
                ev["rider_dice"] = ev.get("rider_dice", 0.0) + 3.5 * (ROUNDS - 1) / ROUNDS
    # Destructive Wrath: max lightning / thunder of one cast per charge (Interrupt_DestructiveWrath)
    if plan.get("dw") and cd:
        best = None
        for ev in evs:
            if {"Lightning", "Thunder"} & set(ev["dtypes"]) and not ev["sp"]["cantrip"]:
                v = _dw_gain(st, ev)
                if best is None or v > best[0]:
                    best = (v, ev)
        if best:
            evs.append(dict(best[1], n=0.0, name="Destructive Wrath", dw_bonus=best[0] * cd_per_round))
    return evs


def _raw_spell_value(st, sp):
    names = lmv_names(st)
    d = sum(mech.avg_expr(e, names) for e, _t in sp["dmg"])
    return d * (sp["targets"] + sp["chain"]) * sp["beams"]


def _dw_gain(st, ev):
    names = lmv_names(st)
    sp = ev["sp"]
    g = 0.0
    for e, t in sp["dmg"]:
        if t in ("Lightning", "Thunder"):
            g += mech.max_part(e, names) - mech.dice_part(e, names)
    tg = sp["targets"] + (sp["chain"] if st.sw["dw_chain_all"] else 0.0)
    return g * tg


# ================================================================================================ evaluation
def eval_event(st, ev, boosts, names, E, target_save_pen, adv_extra=0.0):
    """Expected damage per round of one event + hit/crit rates for the triggers."""
    m = event_mods(st, ev, boosts, names)
    adv_list = list(m["adv"])
    if adv_extra:
        adv_list.append(adv_extra)
    adv = 1.0 - math.prod(1 - min(1.0, a) for a in adv_list) if adv_list else 0.0
    n = ev.get("n", 0.0)
    out = dict(dmg=0.0, ph=0.0, pc=0.0, casts=n, hits=0.0, crits=0.0, dmg_instances=0.0, fail=0.0)
    if ev["kind"] == "spell":
        sp = ev["sp"]
        spell = st.sheet.get("spell") or {"dc": 8 + st.prof, "atk": st.prof}
        tg = ev.get("targets", sp["targets"]) + sp.get("chain", 0)
        instances = 0.0
        if sp["roll"] == "attack":
            bonus = (spell.get("atkM") if ev.get("attack_type") == "MeleeSpellAttack" else spell["atk"]) + m["hit"]
            thr = 20 - m["crit_red"]
            ph = mech.p_hit(bonus, E["ac"], adv)
            pc = mech.p_crit(thr, adv)
            pc = pc + max(0.0, ph - pc) * m["autocrit"]
            per = 0.0
            dice = 0.0
            for e, _t in sp["dmg"]:
                per += mech.avg_expr(e, names)
                dice += mech.dice_part(e, names)
            per += m["flat"] + ev.get("rider_dice", 0.0)
            dice += m["dice"] + ev.get("rider_dice", 0.0)
            dmg = (ph * per + pc * dice) * tg
            out.update(ph=ph, pc=pc)
            instances = ph * tg * len(sp["dmg"])
            out["hits"] = n * ph * tg
            out["crits"] = n * pc * tg
        else:
            dc = spell["dc"] + m["dc"]
            pf = mech.p_fail(dc, E["save"] - target_save_pen)
            if sp["roll"] == "auto":
                pf = 1.0
            per = 0.0
            for e, _t in sp["dmg"]:
                per += mech.avg_expr(e, names)
            per_inst_bonus = m["flat"]
            full = per + per_inst_bonus * len(sp["dmg"]) + ev.get("rider_dice", 0.0)
            half = full / 2 if sp["half"] else 0.0
            dmg = (pf * full + (1 - pf) * half) * tg
            instances = (pf + (1 - pf) * (1 if sp["half"] else 0)) * tg * len(sp["dmg"])
            out["hits"] = n * instances / max(1, len(sp["dmg"]))
            out["fail"] = pf
        out["dmg"] = n * dmg + ev.get("dw_bonus", 0.0)
        out["dmg_instances"] = n * instances
        out["dc_eff"] = (spell["dc"] + m["dc"]) if sp["roll"] != "attack" else None
        return out
    # weapon / throw
    bonus = ev["base_hit"] + m["hit"]
    flat = ev["base_dmg"] + m["flat"] + m["entity"] + ev.get("rider_flat", 0.0)
    dice = ev["base_dice"] + m["dice"] + ev.get("rider_dice", 0.0)
    thr = 20 - m["crit_red"]
    nd, sides = ev.get("die", (0, 0))
    if ev.get("melee") and nd and (m["reroll"] or m["savage"]):
        g = nd * die_gain(sides, m["reroll"], m["savage"])
        flat += g
    best = None
    toggles = [False]
    if any(p_ in st.class_passives for p_ in ("GreatWeaponMaster_BonusDamage", "Sharpshooter_AllIn")):
        toggles = [False, True]
    for tog in toggles:
        st._toggle = {"gwm": tog, "ss": tog}
        mt = event_mods(st, ev, boosts, names) if tog else m
        b2 = ev["base_hit"] + mt["hit"]
        f2 = ev["base_dmg"] + mt["flat"] + mt["entity"] + ev.get("rider_flat", 0.0) + (flat - (ev["base_dmg"] + m["flat"] + m["entity"] + ev.get("rider_flat", 0.0)))
        ph = mech.p_hit(b2, E["ac"], adv)
        pc = mech.p_crit(thr, adv)
        pc = pc + max(0.0, ph - pc) * mt["autocrit"]
        crit_extra = dice + mt["crit_dice"] * ((sides + 1) / 2 if sides else 0)
        val = ph * f2 + pc * crit_extra
        if best is None or val > best[0]:
            best = (val, ph, pc, tog)
    st._toggle = {}
    val, ph, pc, tog = best
    val += ev.get("any_dmg", 0.0)            # hit or miss (a thrown weapon's explosion)
    out.update(dmg=n * val, ph=ph, pc=pc, hits=n * ph, crits=n * pc, dmg_instances=n * ph, toggle=tog)
    return out


def triggers_of(st):
    """[(trigger dict, slot, origin)] from items (by hand) and the class passives."""
    out = []
    for slot, im in st.mechs.items():
        for t in im.triggers:
            if t["hand"] == "m" and slot not in ("MainHand", "Ranged"):
                continue
            if t["hand"] == "o" and slot not in ("OffHand", "RangedOff"):
                continue
            out.append((t, slot, "item"))
    S = st.W.stats
    for p in st.class_passives:
        ps = S.get(p) or {}
        if ps.get("StatsFunctors") and ps.get("StatsFunctorContext"):
            out.append(({"ctx": ps["StatsFunctorContext"], "cond": (ps.get("Conditions") or "").strip(),
                         "functors": ps["StatsFunctors"], "props": ps.get("Properties") or "", "hand": "a", "via": p},
                        None, "class"))
    return out


def status_info(W, sid):
    s = W.stats.get(sid) or {}
    return s, ("MultiplyEffectsByDuration" in (s.get("StatusPropertyFlags") or "")), s.get("StackType") or ""


def run_triggers(st, evs, results, names, E):
    """-> (extra damage per round, self status generation {status: turns per round}, target status generation,
    healing per round, notes)"""
    extra = 0.0
    self_gen, tgt_gen = {}, {}
    heal = 0.0
    for t, slot, origin in triggers_of(st):
        ctxs = set(x.strip() for x in t["ctx"].split(";"))
        once_turn = "OncePerTurn" in t["props"]
        total_rate = 0.0
        per_ev = []
        if "OnStatusApplied" in ctxs and "SNEAKING" in t["cond"] and st.p_open > 0:
            # entering stealth (Shade-Slayer Cloak): once per fight for a stealth opener
            ev2 = dict(evs[0] if evs else {}, _item_slot=slot, status_match=lambda n, a: 1.0)
            per_ev.append((ev2, st.p_open / ROUNDS))
            total_rate += st.p_open / ROUNDS
        for ev, res in zip(evs, results):
            if ev.get("n", 0) <= 0 and not ev.get("dw_bonus"):
                continue
            per_hit = res["dmg"] / res["hits"] if res.get("hits") else 0.0
            ev2 = dict(ev, _item_slot=slot, crit_given_hit=(res["pc"] / res["ph"]) if res.get("ph") else 0.05,
                       hit_flag=1.0 if "OnDamage" in ctxs else (res.get("ph") or 1.0),
                       kill_p=min(0.95, per_hit / ENEMY_HP[st.act]))
            c = mech.Ctx(st, ev2, "trigger")
            p = mech.cond_p(t["cond"], c) if t["cond"] else 1.0
            if p <= 0:
                continue
            if "OnDamage" in ctxs:
                rate = res.get("dmg_instances", 0.0) if ev["kind"] == "spell" else res.get("hits", 0.0)
                if "OncePerAttack" in t["props"] and ev["kind"] == "spell":
                    rate = res.get("hits", 0.0)
            elif "OnAttack" in ctxs:
                rate = ev.get("n", 0.0) * (ev.get("targets", 1) if ev["kind"] == "spell" else 1)
            elif "OnCast" in ctxs:
                rate = ev.get("n", 0.0) if ev["kind"] == "spell" else 0.0
            elif "OnStatusApply" in ctxs or "OnStatusApplied" in ctxs:
                rate = 0.0                      # handled with the statuses below (conditions on status ids)
            else:
                rate = 0.0
            if rate <= 0:
                continue
            per_ev.append((ev2, rate * p))
            total_rate += rate * p
        if total_rate <= 0:
            continue
        scale = min(1.0, 1.0 / total_rate) if once_turn else 1.0
        for ev2, r in per_ev:
            r *= scale
            c = mech.Ctx(st, ev2, "trigger")
            for cond, name, args in mech.functor_list(t["functors"]):
                fp = mech.cond_p(cond, c) if cond else 1.0
                if fp <= 0:
                    continue
                rr = r * fp
                if name == "DealDamage" and args:
                    who = args[0]
                    if who.upper() in ("SELF",):
                        continue
                    expr = args[1] if who.upper() in ("TARGET",) and len(args) > 1 else args[0]
                    extra += rr * mech.avg_expr(expr, names)
                elif name == "ApplyStatus" and args:
                    if args[0].upper() in ("SELF", "SOURCE"):
                        sid, ch, du = (args[1:4] + ["100", "1"])[:3]
                        tgt = self_gen
                    elif args[0].upper() in ("TARGET",):
                        sid, ch, du = (args[1:4] + ["100", "1"])[:3]
                        tgt = tgt_gen
                    else:
                        sid, ch, du = (args[0:3] + ["100", "1"])[:3]
                        tgt = tgt_gen
                    try:
                        chance = float(ch) / 100
                        dur = float(du)
                    except ValueError:
                        chance, dur = 1.0, 1.0
                    if dur < 0:
                        dur = ROUNDS             # lasts until rest: day-long uptime in status_effects
                        if tgt is self_gen:
                            st.persist.add(sid)
                    tgt[sid] = tgt.get(sid, 0.0) + rr * chance * max(1.0, dur)
                elif name == "CreateExplosion" and args:
                    sp = mech.read_spell(st.W, args[0], st.level)
                    if sp:
                        d = sum(mech.avg_expr(e, names) for e, _t in sp["dmg"])
                        extra += rr * d * 1.5 * (0.75 if sp["roll"] == "save" else 1.0)
                elif name == "RegainHitPoints" and args:
                    heal += rr * mech.avg_expr(args[-1] if len(args) > 1 else args[0], names)
    return extra, self_gen, tgt_gen, heal


def status_effects(st, self_gen, tgt_gen, names, E, evs, results):
    """Turn status generation into (dynamic boosts for the next pass, target effects)."""
    W = st.W
    dyn = []
    tgt = dict(save_pen=0.0, atk_pen=0.0, prone=0.0, dot=0.0, control=0.0, adv=0.0)
    floors = {}
    # statuses kept up by items (StatusOnEquip, elixirs): their Passives + duration floors (Battlemage's Power)
    for slot, im in st.mechs.items():
        for s in im.self_status:
            sd = W.stats.get(s) or {}
            for f in ("OnApplyFunctors", "TickFunctors"):
                for cond, name, args in mech.functor_list(sd.get(f) or ""):
                    if name == "SetStatusDuration" and len(args) >= 2:
                        try:
                            floors[args[0]] = max(floors.get(args[0], 0.0), float(args[1]))
                        except ValueError:
                            pass
                    if name == "ApplyStatus" and len(args) >= 3 and args[0] not in ("SELF",):
                        try:
                            floors[args[0]] = max(floors.get(args[0], 0.0), float(args[2]))
                        except ValueError:
                            pass
            for p in mech.split_top(sd.get("Passives") or ""):
                ps = W.stats.get(p) or {}
                for cond, name, args in mech.parse_boosts(ps.get("Boosts") or ""):
                    dyn.append((1.0, cond, name, args, p))
    for sid in set(self_gen) | set(floors):
        sd, mult, stack = status_info(W, sid)
        if not sd:
            continue
        gen = self_gen.get(sid, 0.0)
        if mult and stack == "Additive":
            v = mech.stack_average(gen, decay=1.0, cap=10.0, rounds=ROUNDS, floor=floors.get(sid, 0.0))
            up = 1.0 if v > 0 else 0.0
        elif sid in st.persist and not floors.get(sid):
            up = v = persist_uptime(gen / ROUNDS)     # until rest: share of the day after the first application
        else:
            up = min(1.0, gen) if gen else (1.0 if floors.get(sid) else 0.0)
            v = up
        if "SNEAKING" in (sd.get("RemoveConditions") or "") and gen:
            up = v = min(up, st.sneak_share)          # ends when the character stops sneaking: the opener only
        if re.search(r"OnAttacked|OnDamaged", sd.get("RemoveEvents") or ""):
            v *= HIT_REMOVED                  # lost on the first hit taken each round (Cloak of Displacement ...)
            up *= HIT_REMOVED
        st.self_uptime[sid] = up
        if v <= 0:
            continue
        for cond, name, args in mech.parse_boosts(sd.get("Boosts") or ""):
            dyn.append((v, cond, name, args, sid))
        for p in mech.split_top(sd.get("Passives") or ""):
            ps = W.stats.get(p) or {}
            for cond, name, args in mech.parse_boosts(ps.get("Boosts") or ""):
                dyn.append((up, cond, name, args, p))
    # target statuses
    enemies = ENEMIES
    for sid, gen in tgt_gen.items():
        sd, mult, stack = status_info(W, sid)
        if not sd:
            continue
        per_enemy = gen / enemies if not sid.startswith("PRONE") else gen
        if mult and stack == "Additive":
            v = mech.stack_average(per_enemy, decay=1.0, cap=10.0, rounds=ROUNDS)
            up = 1.0 if v > 0 else 0.0
        else:
            up = min(1.0, per_enemy)
            v = up
        st.target_uptime[sid] = max(st.target_uptime.get(sid, 0.0), up)
        groups = sd.get("StatusGroups") or ""
        for cond, name, args in mech.parse_boosts(sd.get("Boosts") or ""):
            a0 = args[0] if args else ""
            if name == "RollBonus" and a0 == "SavingThrow" and len(args) >= 2:
                tgt["save_pen"] += -v * mech.avg_expr(args[1], names) / (3.0 if len(args) > 2 else 1.0)
            elif name == "RollBonus" and a0 in ("Attack", "WeaponAttack", "MeleeWeaponAttack") and len(args) >= 2:
                tgt["atk_pen"] += -v * mech.avg_expr(args[1], names)
            elif name == "Advantage" and a0 == "AttackTarget":
                tgt["adv"] = 1 - (1 - tgt["adv"]) * (1 - up)
            elif name == "Disadvantage" and a0 == "SavingThrow":
                tgt["save_pen"] += up * 3.0 / 6.0
        if "SG_Prone" in groups:
            tgt["prone"] = 1 - (1 - tgt["prone"]) * (1 - up)
        if re.search(r"SG_Incapacitated|SG_Stunned|SG_Paralyzed", groups):
            tgt["control"] += up
        if sid in ("DAZED",) or "SG_Dazed" in groups:
            tgt["control"] += 0.3 * up
        for cond, name, args in mech.functor_list(sd.get("TickFunctors") or ""):
            if name == "DealDamage" and args:
                tgt["dot"] += up * mech.avg_expr(args[0], names) * min(enemies, gen)
    tgt["save_pen"] = max(0.0, tgt["save_pen"])
    tgt["atk_pen"] = max(0.0, tgt["atk_pen"])
    return dyn, tgt


def evaluate(W, cid, bid, act, loadout, switches=None, detail=False, respec=None):
    """Best over the items' choice options (attunements); -> Result with .choice set."""
    opts = []
    for slot, sid in loadout.items():
        if sid:
            o = _options(W, sid)
            if o:
                opts.append((slot, o))
    if not opts:
        return _evaluate(W, cid, bid, act, loadout, switches, detail, None, respec)
    # the best option of each choice item is found once per build / act / switches and then reused (speed)
    mkey = (cid, bid, act, tuple(sorted((switches or {}).items())), tuple(sorted((s_, loadout[s_]) for s_, _o in opts)),
            (respec or {}).get("key"))
    if mkey in _CHOICE:
        return _evaluate(W, cid, bid, act, loadout, switches, detail, _CHOICE[mkey], respec)
    best = None
    import itertools
    for combo in itertools.product(*[[(slot, st_) for _v, st_ in o] for slot, o in opts]):
        r = _evaluate(W, cid, bid, act, loadout, switches, detail, dict(combo), respec)
        if best is None or r.raw_value() > best.raw_value():
            best = r
    _CHOICE[mkey] = best.choice
    return best


_OPT = {}
_CHOICE = {}


def reset_caches():
    """Forget the choice items' best options. _CHOICE keeps the option found for the FIRST loadout evaluated with
    an item, so a result depends on evaluation order; each optimizer job starts from an empty cache, which keeps a
    job's result the same in any worker process and order."""
    _CHOICE.clear()


def _options(W, sid):
    if sid not in _OPT:
        _OPT[sid] = mech.ItemMech(W, sid).options
    return _OPT[sid]


def _evaluate(W, cid, bid, act, loadout, switches, detail, choice, respec=None):
    st = State(W, cid, bid, act, loadout, switches, choice, respec)
    E = ENEMY[act]
    names = lmv_names(st)
    if st.plan["mode"] == "caster":
        evs = make_caster_events(st)
        special = {}
    else:
        evs, special = make_weapon_events(st)
    # the stealth opener is one attack of the fight: its share of this build's attack rolls
    n_rolls = sum(ev.get("n", 0.0) for ev in evs if ev.get("attack_roll") and ev["kind"] != "spell") or         sum(ev.get("n", 0.0) for ev in evs if ev.get("attack_roll")) or 1.0
    st.sneak_share = min(1.0, st.p_open / (ROUNDS * max(1.0, n_rolls)))
    dyn = []
    tgt = dict(save_pen=0.0, atk_pen=0.0, prone=0.0, dot=0.0, control=0.0, adv=0.0)
    results = []
    extra = heal = 0.0
    displaced = 0.0
    for _it in range(3):
        boosts = all_extra_boosts(st, dyn)
        # Prone: attackers within 3 m get Advantage (PRONE: IF(not DistanceToTargetGreaterThan(3)):Advantage(AttackTarget))
        prone = max(tgt["prone"], st.target_prone)
        results = []
        for ev in evs:
            adv_x = 0.0
            if ev["kind"] in ("weapon", "throw") and (ev.get("melee") or ev["kind"] == "throw"):
                adv_x = prone if not ev.get("enraged") else 0.0
            if special.get("vow_adv") and ev["kind"] == "weapon":
                adv_x = 1 - (1 - adv_x) * (1 - special["vow_adv"])
            if tgt["adv"] and ev["kind"] in ("weapon", "throw"):
                adv_x = 1 - (1 - adv_x) * (1 - tgt["adv"])
            if st.sneak_share and ev.get("attack_roll"):
                adv_x = 1 - (1 - adv_x) * (1 - st.sneak_share)      # attacking while hidden: Advantage
            results.append(eval_event(st, ev, boosts, names, E, tgt["save_pen"], adv_x))
        # an action item spell replaces an Attack action: keep it only when it beats those attacks
        displaced = 0.0
        main = next(((ev, r) for ev, r in zip(evs, results) if ev.get("name") == "attack" and ev.get("n")), None)
        per_attack = main[1]["dmg"] / main[0]["n"] if main else 0.0
        for ev, r in zip(evs, results):
            if ev.get("displaces") and ev.get("n"):
                lost = ev["n"] * ev["displaces"] * per_attack
                if r["dmg"] <= lost:
                    r["dmg"] = 0.0
                    r["hits"] = r["crits"] = r["dmg_instances"] = 0.0
                    ev["dropped"] = True
                else:
                    displaced += lost
        # GWM bonus attack: P(a critical hit or a kill among the round's melee attacks), up to the free bonus action
        main_r = [(ev, r) for ev, r in zip(evs, results) if ev.get("name") == "attack" and ev.get("melee")]
        for ev in evs:
            if ev.get("gwm_ba") and main_r:
                mev, mr = main_r[0]
                kill = min(0.95, (mr["dmg"] / mr["hits"] if mr["hits"] else 0.0) / ENEMY_HP[st.act])
                p_one = min(1.0, mr["pc"] + mr["ph"] * kill)
                ev["n"] = min(ev["gwm_ba"], 1 - (1 - p_one) ** max(0.0, mev["n"]))
        # Enraged Throw knocks Prone on a hit (Throw_FrenziedThrow: ApplyStatus(PRONE,100,1)), before the action throws
        p_prone = 0.0
        for ev, r in zip(evs, results):
            if ev.get("applies_prone"):
                p_prone = 1 - (1 - p_prone) * (1 - r["ph"]) ** max(0.0, ev["n"])
        if special.get("trip_prone"):
            p_prone = 1 - (1 - p_prone) * (1 - special["trip_prone"] * 0.6)
        st.target_prone = p_prone
        extra, self_gen, tgt_gen, heal = run_triggers(st, evs, results, names, E)
        dyn, tgt = status_effects(st, self_gen, tgt_gen, names, E, evs, results)
    # per-round damage
    dmg = sum(r["dmg"] for r in results) + extra + tgt["dot"] - displaced
    hits = sum(r["hits"] for ev, r in zip(evs, results) if ev["kind"] != "spell")
    # Sneak Attack (Rogue): once per turn on a finesse / ranged weapon hit with Advantage or an ally next to the target
    rogue = st.classes.get("Rogue", 0)
    sa = 0.0
    if rogue and st.plan["mode"] != "caster":
        sad = math.ceil(rogue / 2) * 3.5
        elig = [(ev, r) for ev, r in zip(evs, results) if ev["kind"] in ("weapon",) and
                (ev.get("ranged") or "Finesse" in ((W.items.get(st.loadout.get(ev["slot"]) or "") or {}).get("weapon")
                                                   or {}).get("properties", []))]
        if elig:
            p_any = 1 - math.prod((1 - r["ph"]) ** ev["n"] for ev, r in elig)
            pc_any = 1 - math.prod((1 - r["pc"]) ** ev["n"] for ev, r in elig)
            sa = 0.8 * (p_any * sad + pc_any * sad * 0.5)
            dmg += sa
    # marks / smites / superiority
    if special.get("mark"):
        dmg += special["mark"] * hits
    if special.get("superiority"):
        dmg += special["superiority"] * min(1.0, hits)
    if st.plan.get("smite") and st.classes.get("Paladin", 0) >= 2:
        sl = slots(st.classes)
        pn, pl = pact_slots(st.classes)
        pact = pn * SR_WINDOWS
        budget = (sum(sl) + pact) / (ROUNDS * FIGHTS)
        # dice per smite: 1 + slot level (max 5d8), averaged over the slots spent (pact slots first: highest)
        tot = sum(sl) + pact
        lvl_avg = ((pact * pl + sum(n * (i + 1) for i, n in enumerate(sl))) / tot) if tot else 1
        smite = min(5.0, 1 + lvl_avg) * 4.5
        main = [r for ev, r in zip(evs, results) if ev["kind"] == "weapon" and ev.get("melee")]
        if main:
            hits_m = sum(r["hits"] for r in main)
            crits_m = sum(r["crits"] for r in main)
            used_c = min(budget, crits_m)
            used_h = min(budget - used_c, hits_m - crits_m)
            dmg += used_c * smite * 2 + max(0.0, used_h) * smite
    # control value (save-or-lose spells once per fight, Prone / Daze from gear)
    ctrl = 0.0
    for sid in st.plan.get("control") or []:
        sp_dc = (st.sheet.get("spell") or {}).get("dc")
        if sp_dc:
            extra_dc = sum(b[0] * mech.avg_expr(b[3][0], names) for b in dyn if b[2] == "SpellSaveDC" and b[3])
            pf = mech.p_fail(sp_dc + extra_dc, E["save"] - tgt["save_pen"])
            ctrl += pf * CTRL_EQ * E["dmg"] / ROUNDS
    ctrl += tgt["control"] * E["dmg"] * 0.5
    offence = dmg + ctrl
    # ---------------------------------------------------------------- durability
    dur = durability(st, E, all_extra_boosts(st, dyn), names, tgt, heal)
    return Result(st, offence, dmg, ctrl, dur, evs, results, extra, sa, tgt, detail)


def durability(st, E, boosts, names, tgt, heal):
    """Incoming damage per round and turns lost to conditions, from the act's encounter assumptions (INCOMING,
    THREATS) and the gear's defensive game data: AC, saving-throw bonuses / Advantage / Disadvantage, "succeed a
    failed save" interrupts, resistances per damage type, damage reduction, critical-hit immunity, status
    immunities (Prone, Frightened, Paralysed ...), Attribute(Grounded) against forced movement, healing."""
    sh = st.sheet
    act = st.act
    ctx = mech.Ctx(st, {"defence": True}, "boost")
    ac = sh["ac"]
    if st.plan["mode"] == "ranged" and st.shield:
        # an archer shoots with the ranged weapon set: the melee set's shield is not in hand
        ac -= (st.W.items[st.loadout["OffHand"]].get("armour") or {}).get("ac") or 2
    save_b = {k: st.mods[k] for k in st.mods}
    start = st.BI["seq"][0] if st.BI["seq"] else None
    for k in SAVE_PROF.get(start, ()):
        save_b[k] += st.prof
    if st.classes.get("Paladin", 0) >= 6:
        for k in save_b:
            save_b[k] += max(1, st.mods.get("CHA", 0))
    save_adv = {k: 0.0 for k in save_b}
    save_dis = {k: 0.0 for k in save_b}
    dr = {}
    dis = 0.0
    crit_immune = 0.0
    res_p = {}                      # damage type -> probability of resistance from conditional boosts
    immune = {}                     # status id / group -> probability of immunity
    grounded = 0.0
    auto_saves = []                 # (ability or None, spells only, uses per long rest)
    temp = 0.0
    hp_bonus = 0.0
    for (w, cond, name, args, src, scope, origin, counted) in boosts:
        a0 = args[0] if args else ""
        if counted and name in ("AC", "RollBonus") and not cond:
            if name == "RollBonus" and a0 == "SavingThrow":
                pass
            else:
                continue
        p = w * (mech.cond_p(cond, ctx) if cond else 1.0)
        if p <= 0:
            continue
        if name == "AC" and cond:
            ac += p * mech.avg_expr(a0, names)
        elif name == "RollBonus" and a0 == "SavingThrow" and len(args) >= 2:
            v = p * mech.avg_expr(args[1], names)
            if len(args) > 2 and args[2] in mech.ABIL:
                save_b[mech.ABIL[args[2]]] += v
            else:
                for k in save_b:
                    save_b[k] += v
        elif name == "DamageReduction" and len(args) >= 3:
            dr[a0] = dr.get(a0, 0.0) + p * mech.avg_expr(args[2], names)
        elif name in ("Advantage", "Disadvantage") and a0 in ("SavingThrow", "AllSavingThrows"):
            into = save_adv if name == "Advantage" else save_dis
            keys = [mech.ABIL[args[1]]] if a0 == "SavingThrow" and len(args) > 1 and args[1] in mech.ABIL else \
                list(save_b)
            for k in keys:
                into[k] = 1 - (1 - into[k]) * (1 - min(1.0, p))
        elif name == "Disadvantage" and a0 in ("AttackTarget",):
            dis = 1 - (1 - dis) * (1 - p)
        elif name == "CriticalHit" and len(args) >= 3 and a0 == "AttackTarget" and args[1] == "Success" and \
                args[2] == "Never":
            crit_immune = max(crit_immune, p)
        elif name == "Resistance" and len(args) >= 2 and cond and args[1] in ("Resistant", "Immune"):
            res_p[a0] = max(res_p.get(a0, 0.0), p)
        elif name == "StatusImmunity" and args:
            immune[a0] = max(immune.get(a0, 0.0), min(1.0, p))
        elif name == "Attribute" and a0 == "Grounded":
            grounded = max(grounded, min(1.0, p))
        elif name == "UnlockInterrupt" and args:
            a_ = auto_save(st.W, a0)
            if a_:
                auto_saves.append(a_)
        elif name == "TemporaryHP" and args:
            temp += p * mech.avg_expr(a0, names)
        elif name == "IncreaseMaxHP" and cond and args:
            hp_bonus += p * mech.avg_expr(a0, names)
    # damage multiplier per type: sheet resistances (unconditional), conditional ones, Rage (B/P/S)
    level = {r["t"]: r["l"] for r in sh["res"]}
    mult = {}
    for t in mech.DMG_TYPES:
        lv = level.get(t) or level.get("All") or (level.get("Physical") if t in PHYSICAL else None)
        m = 0.0 if lv == "Immune" else 0.5 if lv == "Resistant" else 2.0 if lv == "Vulnerable" else 1.0
        if m == 1.0 and res_p.get(t):
            m = 1.0 - 0.5 * res_p[t]
        if st.raging and t in PHYSICAL:
            m = min(m, 0.5)                    # Rage: B/P/S resistance (Rage_Rage_Boosts)
        mult[t] = m

    def typed(mix):
        return sum(sh_ * mult.get(t, 1.0) for t, sh_ in mix.items())

    def dr_for(mix):
        phys = sum(sh_ for t, sh_ in mix.items() if t in PHYSICAL)
        return sum(v * (1.0 if t == "All" else phys if t == "Physical" else mix.get(t, 0.0)) for t, v in dr.items())

    def fail(dc, abil):
        """Chance a save fails ("STR|DEX": the better ability); Advantage and Disadvantage cancel."""
        best = None
        for k in abil.split("|"):
            a, d = save_adv[k] * (1 - save_dis[k]), save_dis[k] * (1 - save_adv[k])
            p = mech.p_fail(dc, save_b[k])
            v = a * p * p + d * (1 - (1 - p) ** 2) + (1 - a - d) * p
            best = v if best is None else min(best, v)
        return best

    hp = sh["hp"] + hp_bonus
    mix = INCOMING[act]
    n_att = 1.0 * st.exposure
    atk = E["atk"] - tgt["atk_pen"]
    adv_enemy = 0.0
    if st.rages and st.plan["mode"] == "melee":
        adv_enemy = 0.5                         # Reckless Attack
    # ---- conditions: chance per round each lands
    rows = []
    failed_day = 0.0
    for name, ids, abil, per_fight, lost, xdmg, spell in THREATS:
        att = per_fight[act] / ROUNDS * st.exposure
        imm = 0.0
        for i in ids:
            imm = max(imm, grounded if i == "@Grounded" else immune.get(i, 0.0))
        pf = fail(THREAT_DC[act], abil) if abil else 1.0
        rows.append([name, att, imm, pf, lost, xdmg, spell, abil])
        if abil:
            failed_day += att * ROUNDS * FIGHTS * (1 - imm) * pf
    sv = (save_b["DEX"] + save_b["CON"] + save_b["WIS"]) / 3
    p_save_dmg = (fail(E["dc"], "DEX") + fail(E["dc"], "CON") + fail(E["dc"], "WIS")) / 3
    failed_day += 0.35 * ROUNDS * FIGHTS * p_save_dmg
    # "succeed a failed save" interrupts: each use covers one failed save of the day
    cover = min(1.0, sum(u for _a, _s, u in auto_saves) / failed_day) if failed_day > 0 else 0.0
    lost_turns = threat_dmg = self_prone = 0.0
    out_rows = {}
    for name, att, imm, pf, lost, xdmg, spell, abil in rows:
        if abil:
            pf *= (1 - cover)
        land = att * (1 - imm) * pf
        out_rows[name] = round(land, 4)
        lost_turns += land * lost
        threat_dmg += land * xdmg * E["dmg"]
        if name == "knocked prone":
            self_prone = min(1.0, land)
    lost_turns = min(LOST_CAP, lost_turns)
    if st.plan["mode"] in ("melee", "throw"):
        adv_enemy = 1 - (1 - adv_enemy) * (1 - self_prone)   # melee attackers have Advantage on a Prone target
    ph = mech.p_hit(atk, ac, adv_enemy, dis)
    pc = mech.p_crit(20, adv_enemy) * (1 - crit_immune)
    per_hit = max(1.0, E["dmg"] * typed(mix["attack"]) - dr_for(mix["attack"]))
    incoming_atk = n_att * (ph * per_hit + pc * E["dmg"] * 0.5 * typed(mix["attack"]))
    p_save_dmg *= (1 - cover)
    incoming_save = 0.35 * E["save_dmg"] * typed(mix["save"]) * (p_save_dmg + 0.5 * (1 - p_save_dmg))
    raw = incoming_atk + incoming_save + threat_dmg
    incoming = max(0.5 * raw, raw - heal)      # healing can at most halve the damage taken (model rule)
    R = (hp + temp) / incoming
    return dict(ac=ac, hp=hp, temp=temp, R=R, incoming=incoming, saves=save_b, dr=sum(dr.values()), dis=dis,
                lost=lost_turns, sv=sv, cover=cover, mult={t: v for t, v in mult.items() if v != 1.0},
                threats=out_rows)


def auto_save(W, iid):
    """An interrupt that turns a failed saving throw into a success (AdjustRoll(>= 10) / SetRoll(20) on a saving
    throw): -> (ability or None, spells only, uses per long rest) or None."""
    sd = W.stats.get(iid) or {}
    cond = sd.get("Conditions") or ""
    props = sd.get("Properties") or ""
    if not ("IsSavingThrow" in cond or "HasSavingThrowWithAbility" in cond):
        return None
    m = re.search(r"AdjustRoll\((?:[A-Z_]+,)?\s*(-?\d+)\)|SetRoll\((\d+)\)", props)
    if not m or (m.group(1) and int(m.group(1)) < 10):
        return None
    ab = re.search(r"Ability\.(\w+)", cond)
    cdn = sd.get("Cooldown") or ""
    uses = SR_WINDOWS if "ShortRest" in cdn else 1
    return (mech.ABIL.get(ab.group(1)) if ab else None, "IsSpell" in cond, uses)


class Result:
    def __init__(self, st, offence, dmg, ctrl, dur, evs, results, extra, sa, tgt, detail):
        self.st = st
        self.offence = offence
        self.dpr = dmg
        self.control = ctrl
        self.dur = dur
        self.R = dur["R"]
        self.lost = dur.get("lost", 0.0)
        self.extra = extra
        self.sneak = sa
        self.tgt = tgt
        self.unknown = set(st.unknown)
        self.choice = dict(st.choice)
        self.score = None
        self.events = [(ev.get("name"), ev.get("n"), round(r["dmg"], 2)) for ev, r in zip(evs, results)] if detail \
            else None
        self.plan_events = [dict(name=ev.get("name"), n=ev.get("n"), slot=ev.get("slot"), spell=ev.get("spell_id"),
                                 kind=ev.get("kind"), cost=ev.get("cost"), dropped=bool(ev.get("dropped")),
                                 dmg=round(r["dmg"], 2)) for ev, r in zip(evs, results)] if detail else None

    def raw_value(self):
        return self.offence * (1.0 - self.lost) * math.sqrt(sat(self.R))

    def finish(self, R0):
        """score = damage (+ control) x (1 - turns lost to conditions) x sqrt(durability vs the no-gear build)."""
        self.score = self.offence * (1.0 - self.lost) * math.sqrt(max(0.05, sat(self.R) / sat(R0)))
        return self


def sat(R):
    """Rounds survived with diminishing returns: past a few fights' worth of focus fire more durability matters
    less (half value at R_SAT rounds)."""
    return R / (1.0 + R / R_SAT)


_R0 = {}


def score(W, cid, bid, act, loadout, switches=None, detail=False, respec=None):
    """Full evaluation with the score normalised by the build's no-gear durability (the planned build's, also for
    a tuned respec, so tuned and planned scores compare)."""
    key = (cid, bid, act, tuple(sorted((switches or {}).items())))
    if key not in _R0:
        _R0[key] = evaluate(W, cid, bid, act, {}, switches).R
    return evaluate(W, cid, bid, act, loadout, switches, detail, respec).finish(_R0[key])
