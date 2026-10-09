"""Build profiles for LootAdvisor scoring (PLAN step 3).

One entry per origin character: race proficiencies, the research file, the research tag vocabulary
(codes used in data/research/<char>.md -> build ids) and the builds that get scores and sets:
  - the BuildAdvisor builds for that origin (Mods/BuildAdvisor/.../Builds.lua, BA.Origins),
  - 2-3 popular community alternatives covered by the research (user decision 2026-10-08),
  - Dark Urge: the actual build in the user's "The White Urge" campaign (seen in game 2026-10-08:
    White Dragonborn, Hexblade Warlock 12, CHA 19, Great Weapon Master) plus the top community Durge builds.

Build fields (all used by tools/score_items.py, formula in the score_items.py docstring and at the end of data/scores/SETS.md):
  classes      {class: levels}; start = first class (full proficiencies), others give multiclass proficiencies
  subclass     subclass names that add proficiencies (Tempest, Life, Hexblade, Swords ...)
  stats        assumed ability scores at level 12 (used to value "+2 X" / "X becomes 23" items)
  statw        value of +1 ability MODIFIER per ability (main stat 3, secondary 1.5, CON ~1.2)
  attacks      weapon attack modes and how much the build wants them (0-4):
               ranged (bows, crossbows), handxbow, melee2h, melee1h, finesse, light, thrown, unarmed, reach
  offhand      shield | dual | none (two-handed / empty off hand) | any
  armour       preferred body: heavy | medium | light | clothing | unarmoured
  caster       0 none, 1 half / support caster, 2 full caster (weights spell DC / spell attack rules)
  needs        weights (0-3) of the effect "needs" the scoring rules detect in item effect texts
  avoid        hard exclusions (shield, medium, heavy, armour)
  weapons      optional allow-list of weapon proficiency types for the main-hand melee weapon (Bladesong)
  needs.gwm    Great Weapon Master: value of the Heavy property on a two-handed weapon (GWM's -5/+10 needs it)
"""

# ---------------------------------------------------------------- proficiency tables (BG3 rules)
RACE_PROFS = {
    "High Elf": ["Longswords", "Shortswords", "Shortbows", "Longbows"],
    "Human": ["LightArmor", "Shields", "Spears", "Pikes", "Halberds", "Glaives"],
    "High Half-Elf": ["LightArmor", "Shields", "Spears", "Pikes", "Halberds", "Glaives"],
    "Zariel Tiefling": [],
    "Githyanki": ["LightArmor", "MediumArmor", "Shortswords", "Longswords", "Greatswords"],
    "White Dragonborn": [],
}
# Class and subclass proficiencies come from the game files (tools/class_progressions.py ->
# data/cache/class_progressions.json: Progressions.lsx level-1 Boosts for a first class / a multiclass, subclass
# progression Boosts + the Boosts of the passives they add, e.g. Hex Warrior). Session 4: the old hand tables missed
# the Cleric's Morningstar + Flail proficiency (level 1, first class) and Bladesinging's Daggers + Sickles.
import json as _json  # noqa: E402
import os as _os  # noqa: E402

CLASS_DATA_FILE = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "cache",
                                "class_progressions.json")
_CLASS_DATA = None


def class_data():
    """data/cache/class_progressions.json (run tools/class_progressions.py to create it)."""
    global _CLASS_DATA
    if _CLASS_DATA is None:
        if not _os.path.exists(CLASS_DATA_FILE):
            raise SystemExit(f"{CLASS_DATA_FILE} missing - run: python tools/class_progressions.py")
        with open(CLASS_DATA_FILE, encoding="utf-8") as f:
            _CLASS_DATA = _json.load(f)
    return _CLASS_DATA


def subclass_internal(cls, display):
    """Game subclass display name ("Evocation") of a class -> internal ClassDescription name, or None."""
    return (class_data()["by_display"].get(cls) or {}).get(display)


# character-specific extras (Wyll's "The Blade of Frontiers" keeps rapier proficiency)
CHAR_EXTRA_PROFS = {"wyll": ["Rapiers"]}


def proficiencies(char_id, race, build):
    """Race (table above) + character extras + game-data class proficiencies: the first class gives its level-1
    first-class set, every other class its multiclass set, plus anything a class or its subclass (SUBCLASSES, game
    display names) grants at a class level the build reaches."""
    cd = class_data()["classes"]
    profs = set(RACE_PROFS.get(race, []))
    profs |= set(CHAR_EXTRA_PROFS.get(char_id, []))
    subs = SUBCLASSES.get(build.get("id"), {})
    for i, (cls, lv) in enumerate(build["classes"].items()):
        c = cd[cls]
        profs |= set(c["start"] if i == 0 else c["multi"])
        for name in [cls] + ([subclass_internal(cls, subs[cls])] if subs.get(cls) else []):
            for at, ps in (cd.get(name) or {}).get("levels", {}).items():
                if int(at) <= lv:
                    profs |= set(ps)
    return profs


# ---------------------------------------------------------------- reusable build profiles
def S(STR=10, DEX=14, CON=16, INT=10, WIS=10, CHA=10):
    return {"STR": STR, "DEX": DEX, "CON": CON, "INT": INT, "WIS": WIS, "CHA": CHA}


BUILDS = {
    # ---------------- archers / rogues
    "gloomassassin": dict(
        name="Gloom Stalker 5 / Assassin 4 / Battle Master 3", origin="BuildAdvisor",
        classes={"Ranger": 5, "Rogue": 4, "Fighter": 3}, subclass=[],
        stats=S(STR=8, DEX=20, CON=14, WIS=16), statw={"DEX": 3, "WIS": 1.0, "CON": 1.0},
        attacks={"ranged": 4, "finesse": 1, "light": 1}, offhand="any", armour="medium", caster=0,
        needs={"weapon_dmg": 2.5, "weapon_atk": 2.5, "crit": 2, "adv": 2, "initiative": 2, "stealth": 1.5,
               "obscured": 1.5, "hunters_mark": 2.5, "sneak_attack": 2, "concentration": 1, "mobility": 1,
               "dmg_piercing": 1, "kill_trigger": 1.5},
        why="Archer opener: Dread Ambusher + Assassinate + Action Surge."),
    "thx": dict(
        name="Gloom Stalker 5 / Battle Master 3 / Thief 4 (dual hand crossbows)", origin="BuildAdvisor",
        classes={"Ranger": 5, "Rogue": 4, "Fighter": 3}, subclass=[],
        # Builds.lua: base DEX 15 CON 15 WIS 14, +2 DEX +1 CON, ASI +2 DEX (synced at run time anyway)
        stats=S(STR=8, DEX=19, CON=16, WIS=14, CHA=8), statw={"DEX": 3, "WIS": 0.8, "CON": 1.0},
        attacks={"handxbow": 4, "ranged": 1, "finesse": 1, "light": 1}, offhand="any", armour="medium", caster=0,
        dual_ranged=True,
        needs={"weapon_dmg": 3, "weapon_atk": 2, "crit": 1.5, "adv": 2.5, "initiative": 2, "stealth": 1.5,
               "obscured": 1, "hunters_mark": 1.5, "sneak_attack": 2, "mobility": 1, "dmg_piercing": 1},
        why="Fast Hands makes the off-hand crossbow a bonus-action shot: many hits per turn."),
    "thiefmelee": dict(
        name="Thief Rogue 12 - dual-wield melee", origin="community",
        classes={"Rogue": 12}, subclass=[],
        stats=S(STR=8, DEX=20, CON=14, WIS=12), statw={"DEX": 3, "CON": 1.2},
        attacks={"finesse": 3, "light": 3, "melee1h": 2}, offhand="dual", armour="light", caster=0,
        needs={"weapon_dmg": 3, "weapon_atk": 2, "crit": 2, "adv": 3, "initiative": 1, "stealth": 1.5,
               "sneak_attack": 2.5, "piercing_vuln": 3, "dmg_piercing": 1.5, "mobility": 1, "healed": 1.5,
               "kill_trigger": 1.5},
        why="Two finesse blades, Sneak Attack every turn with advantage, piercing vulnerability."),
    "critarcher": dict(
        name="Assassin / Gloom Stalker crit-stack archer", origin="community",
        classes={"Ranger": 5, "Rogue": 7}, subclass=[],
        stats=S(STR=8, DEX=20, CON=14, WIS=16), statw={"DEX": 3, "WIS": 1.0, "CON": 1.0},
        attacks={"ranged": 4, "finesse": 1, "light": 1}, offhand="any", armour="medium", caster=0,
        needs={"weapon_dmg": 2, "weapon_atk": 2, "crit": 4, "adv": 2, "initiative": 1.5, "stealth": 2.5,
               "obscured": 2, "sneak_attack": 1.5, "hunters_mark": 1, "dmg_piercing": 1, "kill_trigger": 1.5},
        why="Lower the crit threshold while hidden, then stack on-crit damage riders."),
    # ---------------- wizards / sorcerers / warlocks
    "evoker": dict(
        name="Evocation Wizard 12", origin="BuildAdvisor",
        classes={"Wizard": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, INT=20), statw={"INT": 3, "CON": 1.5, "DEX": 0.5},
        attacks={}, offhand="shield", armour="clothing", caster=2,
        needs={"spell_dc": 3, "spell_atk": 2, "spell_slot": 2, "concentration": 2, "cantrip": 1,
               "magic_missile": 1, "arcane_acuity": 1.5, "dmg_fire": 1, "dmg_cold": 1, "dmg_lightning": 1,
               "mobility": 1, "lightning_charge": 0.5},
        why="Biggest spell list; Sculpt Spells AoE and Empowered Evocation."),
    "stormsorc": dict(
        name="Storm Sorcerer 10 / Tempest Cleric 2", origin="BuildAdvisor",
        classes={"Sorcerer": 10, "Cleric": 2}, subclass=["Tempest"],
        stats=S(STR=8, DEX=14, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="heavy", caster=2,
        needs={"spell_dc": 3, "spell_atk": 1.5, "spell_slot": 1.5, "concentration": 1.5, "cantrip": 1,
               "magic_missile": 1, "lightning_charge": 2, "reverberation": 2.5, "daze": 2, "channel": 2,
               "arcane_acuity": 1, "dmg_lightning": 3, "dmg_thunder": 3, "illuminated": 1, "dmg_radiant": 1,
               "mobility": 0.5},
        why="Destructive Wrath maximises lightning/thunder; Tempest adds heavy armour."),
    "firewiz": dict(
        name="Fire Evoker (Arcane Acuity Scorching Ray / Fireball)", origin="community",
        classes={"Wizard": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, INT=20), statw={"INT": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="clothing", caster=2,
        needs={"spell_dc": 3, "spell_atk": 2.5, "spell_slot": 1.5, "concentration": 1, "cantrip": 1,
               "arcane_acuity": 3, "heat": 1.5, "dmg_fire": 3, "mobility": 1},
        why="Fire spells stack Arcane Acuity, then the big save spell lands."),
    "coldwiz": dict(
        name="Cold control / Abjuration Wizard", origin="community",
        classes={"Wizard": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, INT=20), statw={"INT": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="clothing", caster=2,
        needs={"spell_dc": 3, "spell_atk": 1.5, "spell_slot": 1, "concentration": 1.5, "cantrip": 1.5,
               "frost": 3, "dmg_cold": 3, "ac": 1, "mobility": 1},
        why="Cold spells chill and encrust targets; ice surfaces control the field."),
    "bladesinger": dict(
        name="Bladesinging Wizard 12", origin="community",
        classes={"Wizard": 12}, subclass=["Bladesinging"],
        stats=S(STR=8, DEX=18, CON=16, INT=20), statw={"INT": 3, "DEX": 1.5, "CON": 1.2},
        attacks={"finesse": 3, "light": 2, "melee1h": 2}, offhand="none", armour="light", caster=2,
        avoid=["shield", "medium", "heavy"],
        weapons=["Daggers", "Longswords", "Rapiers", "Scimitars", "Shortswords", "Sickles"],
        needs={"weapon_spell": 3, "arcane_acuity": 2, "arcane_synergy": 2, "dmg_thunder": 1.5, "spell_dc": 2,
               "concentration": 1.5, "weapon_dmg": 1.5, "weapon_atk": 1, "ac": 1, "mobility": 1},
        why="Booming Blade and other weapon cantrips feed Acuity / Synergy loops; Bladesong forbids shields."),
    "sorlock": dict(
        name="Sorlock (Fiend Warlock 2 / Draconic Sorcerer 10)", origin="BuildAdvisor",
        classes={"Warlock": 2, "Sorcerer": 10}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="clothing", caster=2,
        needs={"cantrip": 4, "spell_atk": 3, "adv": 2, "spell_dc": 1.5, "spell_slot": 1, "dmg_fire": 1.5,
               "dmg_force": 1, "illuminated": 1, "dmg_radiant": 1, "reverberation": 1, "concentration": 1,
               "arcane_acuity": 1, "mobility": 1},
        why="Quickened Eldritch Blast: two blasts a turn, CHA on every beam."),
    "ebwarlock": dict(
        name="Pure Warlock 12 - Eldritch Blast", origin="community",
        classes={"Warlock": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="light", caster=2,
        needs={"cantrip": 4, "spell_atk": 3, "adv": 2, "spell_dc": 1, "dmg_force": 1, "illuminated": 1,
               "dmg_radiant": 1, "reverberation": 1, "daze": 1, "concentration": 1, "mobility": 1},
        why="Three-beam Eldritch Blast with Agonizing Blast; quick-cast cantrip gear matters most."),
    "lockadin": dict(
        name="Lockadin (Vengeance Paladin 5 / Hexblade Warlock 7)", origin="BuildAdvisor",
        classes={"Paladin": 5, "Warlock": 7}, subclass=["Hexblade"],
        stats=S(STR=8, DEX=14, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.2},
        attacks={"melee2h": 3, "melee1h": 2.5}, offhand="any", armour="heavy", caster=1,
        needs={"weapon_dmg": 2.5, "weapon_atk": 2, "crit": 2.5, "adv": 2, "smite": 3, "spell_dc": 1,
               "arcane_synergy": 1, "bonus_enchant": 2, "concentration": 1, "spell_slot": 1, "dmg_necrotic": 0.5},
        why="Hex Warrior: CHA for weapon attacks; short-rest slots fuel smites."),
    "hexblade": dict(
        name="Hexblade Warlock 12 - Pact of the Blade melee", origin="community",
        classes={"Warlock": 12}, subclass=["Hexblade"],
        stats=S(STR=8, DEX=14, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.2},
        attacks={"melee1h": 3, "melee2h": 3}, offhand="any", armour="medium", caster=1,
        needs={"weapon_dmg": 2.5, "weapon_atk": 2, "crit": 2.5, "adv": 2, "arcane_synergy": 1.5,
               "spell_dc": 1, "bonus_enchant": 1.5, "concentration": 1, "ac": 1, "dmg_necrotic": 0.5},
        why="Hexblade's Curse crits on 19; Thirsting Blade gives Extra Attack with CHA weapon hits."),
    "bladelock": dict(
        name="Bladelock gish (Pact of the Blade + Booming Blade)", origin="community",
        classes={"Warlock": 12}, subclass=["Hexblade"],
        stats=S(STR=8, DEX=16, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.2},
        attacks={"melee1h": 3, "finesse": 2}, offhand="any", armour="medium", caster=1,
        needs={"weapon_spell": 3, "arcane_synergy": 2.5, "arcane_acuity": 2, "dmg_thunder": 1.5,
               "weapon_dmg": 1.5, "weapon_atk": 1.5, "crit": 1.5, "concentration": 1},
        why="Booming Blade -> Arcane Synergy adds CHA to weapon damage a second time."),
    # ---------------- barbarians / fighters / paladins
    "giants": dict(
        name="Path of Giants Barbarian 12", origin="BuildAdvisor",
        classes={"Barbarian": 12}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 4, "CON": 1.5},
        attacks={"thrown": 3, "melee2h": 2.5, "melee1h": 1.5}, offhand="any", armour="medium", caster=0,
        needs={"throw": 4, "weapon_dmg": 2.5, "weapon_atk": 1.5, "rage": 2, "adv": 1, "crit": 1,
               "dmg_lightning": 0.5, "mobility": 1},
        why="Tavern Brawler throws in Giant's Rage; Elemental Cleaver makes any weapon a returning throw."),
    "throwzerker": dict(
        name="Throwzerker (Berserker Barbarian 10 / Fighter 2)", origin="BuildAdvisor",
        classes={"Barbarian": 10, "Fighter": 2}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 4, "CON": 1.5},
        attacks={"thrown": 4, "melee2h": 1, "melee1h": 1}, offhand="any", armour="medium", caster=0,
        needs={"throw": 4, "returning": 3, "weapon_dmg": 2.5, "weapon_atk": 1.5, "rage": 1.5, "adv": 1.5,
               "crit": 1, "mobility": 1, "kill_trigger": 1},
        why="Throw + Enraged Throw every turn; returning weapons keep the volley going."),
    "gwmbarb": dict(
        name="Berserker Barbarian / Fighter - Great Weapon Master melee", origin="community",
        classes={"Barbarian": 10, "Fighter": 2}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 3, "CON": 1.5},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="medium", caster=0,
        needs={"gwm": 2, "weapon_dmg": 2.5, "weapon_atk": 2, "adv": 1.5, "crit": 1.5, "rage": 2, "mobility": 1,
               "kill_trigger": 1},
        why="Reckless Attack advantage covers the GWM -5; Frenzy adds bonus attacks."),
    "bearbarb": dict(
        name="Wildheart (Bear) Barbarian - unarmoured tank", origin="community",
        classes={"Barbarian": 12}, subclass=[],
        stats=S(STR=18, DEX=14, CON=18), statw={"STR": 2.5, "CON": 2.5, "DEX": 1},
        attacks={"melee2h": 3, "melee1h": 2}, offhand="any", armour="unarmoured", caster=0,
        needs={"ac": 2.5, "saves": 1.5, "dmg_reduction": 2, "crit_immune": 1.5, "temp_hp": 1.5, "rage": 2.5, "retaliation": 1.5,
               "weapon_dmg": 1.5, "weapon_atk": 1},
        why="Resists almost everything while raging; Unarmoured Defence scales with CON."),
    "battlemaster": dict(
        name="Battle Master Fighter 12", origin="BuildAdvisor",
        classes={"Fighter": 12}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 3, "CON": 1.5},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="heavy", caster=0,
        needs={"gwm": 2, "weapon_dmg": 2.5, "weapon_atk": 2.5, "adv": 2, "crit": 1.5, "manoeuvre": 2, "reaction_atk": 1.5,
               "initiative": 1, "mobility": 1, "kill_trigger": 1},
        why="Three attacks + Action Surge + manoeuvres; GWM with a great weapon."),
    "sorcadin": dict(
        name="Sorcadin (Vengeance Paladin 6 / Shadow Sorcerer 6)", origin="BuildAdvisor",
        classes={"Paladin": 6, "Sorcerer": 6}, subclass=[],
        stats=S(STR=18, DEX=10, CON=16, CHA=18), statw={"STR": 2.5, "CHA": 2, "CON": 1.2},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="heavy", caster=1,
        needs={"gwm": 2, "weapon_dmg": 2, "weapon_atk": 2, "crit": 2.5, "adv": 2, "smite": 3, "spell_dc": 1.5,
               "concentration": 1.5, "arcane_acuity": 1.5, "arcane_synergy": 1, "bonus_enchant": 2,
               "spell_slot": 1.5, "obscured": 1},
        why="Quickened Hold Person: paralysed targets take auto-crit smites."),
    "oathbreaker": dict(
        name="Pure Paladin 12 (Oathbreaker)", origin="BuildAdvisor",
        classes={"Paladin": 12}, subclass=[],
        stats=S(STR=20, DEX=10, CON=16, CHA=16), statw={"STR": 3, "CHA": 1.5, "CON": 1.2},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="heavy", caster=1,
        needs={"gwm": 2, "weapon_dmg": 2, "weapon_atk": 2, "crit": 2.5, "adv": 2, "smite": 3, "channel": 2,
               "spell_dc": 1, "spell_slot": 1.5, "bonus_enchant": 1.5, "concentration": 1, "kill_trigger": 1},
        why="Aura of Hate + Improved Divine Smite; heavy armour two-hander."),
    "eldritchknight": dict(
        name="Eldritch Knight Fighter 12", origin="community",
        classes={"Fighter": 12}, subclass=[],
        stats=S(STR=20, DEX=12, CON=16, INT=14), statw={"STR": 3, "CON": 1.5, "INT": 0.8},
        attacks={"melee2h": 3, "melee1h": 2.5}, offhand="any", armour="heavy", caster=1,
        needs={"weapon_dmg": 2, "weapon_atk": 2, "weapon_spell": 2.5, "arcane_synergy": 2, "arcane_acuity": 2,
               "concentration": 1, "ac": 1, "crit": 1},
        why="Weapon + Booming Blade / Shield; Arcane Synergy and Acuity loops."),
    "champion": dict(
        name="Champion Fighter 12 - crit build", origin="community",
        classes={"Fighter": 12}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 3, "CON": 1.5},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="heavy", caster=0,
        needs={"gwm": 2, "crit": 4, "adv": 2.5, "weapon_dmg": 2, "weapon_atk": 2, "kill_trigger": 1.5},
        why="Improved/Superior Critical plus item crit reductions and on-crit riders."),
    "tankfighter": dict(
        name="Sword-and-board Fighter (tank)", origin="community",
        classes={"Fighter": 12}, subclass=[],
        stats=S(STR=20, DEX=12, CON=18), statw={"STR": 2.5, "CON": 2},
        attacks={"melee1h": 4}, offhand="shield", armour="heavy", caster=0,
        needs={"ac": 3, "crit_immune": 2, "saves": 2, "dmg_reduction": 2.5, "temp_hp": 1.5, "retaliation": 1.5, "weapon_dmg": 1.5,
               "weapon_atk": 1.5},
        why="Shield + crit-immune heavy armour; reflect and Reeling effects punish attackers."),
    # ---------------- clerics
    "lightcleric": dict(
        name="Light Domain Cleric 12", origin="BuildAdvisor",
        classes={"Cleric": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, WIS=20), statw={"WIS": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="medium", caster=2,
        needs={"spell_dc": 3, "spell_atk": 1, "radiating_orb": 3, "illuminated": 2.5, "dmg_radiant": 3,
               "dmg_fire": 1, "reverberation": 1.5, "concentration": 2, "channel": 2, "healer": 1, "ac": 1,
               "spell_slot": 1},
        why="Radiant blaster: Spirit Guardians + Radiating Orb debuff stacking."),
    "tempestcleric": dict(
        name="Tempest Domain Cleric 12", origin="community",
        classes={"Cleric": 12}, subclass=["Tempest"],
        stats=S(STR=10, DEX=12, CON=16, WIS=20), statw={"WIS": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="heavy", caster=2,
        needs={"spell_dc": 3, "dmg_lightning": 3, "dmg_thunder": 3, "reverberation": 2.5, "daze": 1.5,
               "channel": 2.5, "concentration": 2, "lightning_charge": 1, "ac": 1, "spell_slot": 1},
        why="Destructive Wrath maximised lightning/thunder from a heavy-armour front-liner."),
    "lifecleric": dict(
        name="Life Domain Cleric 12 - healer", origin="community",
        classes={"Cleric": 12}, subclass=["Life"],
        stats=S(STR=10, DEX=10, CON=16, WIS=20), statw={"WIS": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="heavy", caster=2,
        needs={"healer": 4, "spell_dc": 1.5, "ac": 1.5, "concentration": 1.5, "channel": 1.5, "spell_slot": 1.5,
               "saves": 1},
        why="Every heal also buffs, protects or shields the target."),
    "trickcleric": dict(
        name="Trickery Domain Cleric 12 (Shar / darkness)", origin="community",
        classes={"Cleric": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, WIS=20), statw={"WIS": 3, "CON": 1.5},
        attacks={"melee1h": 1, "reach": 0.5}, offhand="shield", armour="medium", caster=2,
        needs={"obscured": 3, "stealth": 2, "spell_dc": 2.5, "dmg_necrotic": 1.5, "concentration": 1.5,
               "ac": 1, "saves": 1},
        why="Fights inside Shar's darkness: obscured bonuses on saves, AC and damage."),
    # ---------------- monk
    "tbmonk": dict(
        name="Tavern Brawler Open Hand Monk 12", origin="BuildAdvisor",
        classes={"Monk": 12}, subclass=[],
        stats=S(STR=20, DEX=16, CON=14, WIS=14), statw={"STR": 4, "DEX": 1.5, "WIS": 1.5},
        attacks={"unarmed": 4}, offhand="none", armour="unarmoured", caster=0, avoid=["shield"],
        needs={"unarmed": 4, "ki": 2, "weapon_atk": 1.5, "adv": 2, "mobility": 1.5, "ac": 1.5, "kill_trigger": 1},
        why="Tavern Brawler adds STR twice to 4-5 unarmed hits a turn."),
    # ---------------- Builds.lua builds added in session 4 (decision 65; analysis/*_BEST_BUILD.md, *_build.lua).
    # stats / feats / styles / level plan are synced from Builds.lua at run time; needs / attacks from the analyses.
    "tempestevoker": dict(
        name="Evocation Wizard 10 / Tempest Cleric 2", origin="BuildAdvisor",
        classes={"Wizard": 10, "Cleric": 2}, subclass=["Tempest"],
        stats=S(STR=8, DEX=14, CON=16, INT=20), statw={"INT": 3, "CON": 1.5, "DEX": 0.3},
        attacks={}, offhand="shield", armour="heavy", caster=2,
        needs={"spell_dc": 3, "spell_atk": 2, "spell_slot": 1.5, "concentration": 2, "cantrip": 1,
               "magic_missile": 1, "arcane_acuity": 1.5, "lightning_charge": 1.5, "dmg_lightning": 3,
               "dmg_thunder": 2, "dmg_fire": 1.5, "dmg_cold": 1, "reverberation": 1.5, "channel": 2, "mobility": 1},
        why="Destructive Wrath maximises a whole Lightning cast and Empowered Evocation adds INT to every target; "
            "Tempest adds heavy armour and martial weapons."),
    "lightquick": dict(
        name="Light Domain Cleric 9 / Sorcerer 3 (Quickened)", origin="BuildAdvisor",
        classes={"Cleric": 9, "Sorcerer": 3}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, WIS=20), statw={"WIS": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="medium", caster=2,
        needs={"spell_dc": 3, "spell_atk": 1, "radiating_orb": 3, "illuminated": 2.5, "dmg_radiant": 3,
               "dmg_fire": 1.5, "reverberation": 1.5, "concentration": 2, "channel": 2, "healer": 1, "ac": 1,
               "spell_slot": 2},
        why="Light Cleric up to 9, then Quickened Spell: a second levelled radiant / fire spell every turn."),
    "hexsorlock": dict(
        name="Hexblade Sorlock (Hexblade Warlock 2 / Draconic Sorcerer 8 / Fighter 2)", origin="BuildAdvisor",
        classes={"Sorcerer": 8, "Warlock": 2, "Fighter": 2}, subclass=["Hexblade"],
        stats=S(STR=8, DEX=14, CON=16, CHA=20), statw={"CHA": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="medium", caster=2,
        needs={"cantrip": 4, "spell_atk": 3, "adv": 2, "spell_dc": 1.5, "spell_slot": 1, "dmg_fire": 1.5,
               "dmg_force": 1, "illuminated": 1, "dmg_radiant": 1, "reverberation": 1, "concentration": 1,
               "arcane_acuity": 1, "mobility": 1, "ac": 1},
        why="Two Eldritch Blasts a turn with CHA added twice per beam; Hexblade's Curse fills the bonus actions."),
    "bmgiant": dict(
        name="Battle Master Fighter 12 (Giantslayer + advantage)", origin="BuildAdvisor",
        classes={"Fighter": 12}, subclass=[],
        stats=S(STR=20, DEX=10, CON=16, WIS=14), statw={"STR": 3, "CON": 1.5, "WIS": 0.3},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="heavy", caster=0,
        needs={"gwm": 2, "weapon_dmg": 2.5, "weapon_atk": 2.5, "adv": 3, "crit": 1.5, "manoeuvre": 2,
               "reaction_atk": 1.5, "initiative": 1.5, "mobility": 1, "kill_trigger": 1},
        why="Three attacks + Action Surge; Great Weapon Master pays with an advantage source (Automaton gloves, "
            "Risky Ring)."),
    "throw_zerk7_thief3": dict(
        name="Throwzerker Thief (Berserker 7 / Thief 3 / Fighter 2)", origin="BuildAdvisor",
        classes={"Barbarian": 7, "Rogue": 3, "Fighter": 2}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 4, "CON": 1.5},
        attacks={"thrown": 4, "melee2h": 1, "melee1h": 1}, offhand="any", armour="medium", caster=0,
        needs={"throw": 4, "returning": 3, "weapon_dmg": 2.5, "weapon_atk": 1.5, "rage": 1.5, "adv": 1.5,
               "crit": 1, "mobility": 1, "kill_trigger": 1, "ac": 1},
        why="Fast Hands gives a second bonus-action Enraged Throw: four Tavern Brawler throws a turn."),
    "throw_zerk5_thief4": dict(
        name="Throw-Thief (Berserker Barbarian 5 / Thief Rogue 4 / Champion Fighter 3)", origin="BuildAdvisor",
        classes={"Barbarian": 5, "Rogue": 4, "Fighter": 3}, subclass=[],
        stats=S(STR=20, DEX=14, CON=16), statw={"STR": 4, "CON": 1.5},
        attacks={"thrown": 4, "melee2h": 1, "melee1h": 1}, offhand="any", armour="medium", caster=0,
        needs={"throw": 4, "returning": 3, "weapon_dmg": 2.5, "weapon_atk": 1.5, "rage": 1.5, "adv": 1.5,
               "crit": 1.5, "dmg_piercing": 1.5, "mobility": 1, "kill_trigger": 1, "ac": 1},
        why="Two Enraged Throws a turn knock targets Prone; Champion crits on 19; Bhaalist Armour doubles piercing."),
    "bardadin": dict(
        name="Bardadin (Paladin 2 / College of Swords Bard 10)", origin="BuildAdvisor",
        classes={"Paladin": 2, "Bard": 10}, subclass=["Swords"],
        stats=S(STR=16, DEX=10, CON=14, CHA=20), statw={"CHA": 2.5, "STR": 2, "CON": 1.2},
        attacks={"melee1h": 3, "melee2h": 2}, offhand="any", armour="heavy", caster=1,
        needs={"weapon_dmg": 2, "weapon_atk": 2, "smite": 2, "spell_dc": 2, "concentration": 1.5, "bardic": 1,
               "ac": 1, "crit": 1},
        why="Paladin dip for heavy armour + smites; Swords Bard Extra Attack, Flourishes and Magical Secrets."),
    "moondruid": dict(
        name="Circle of the Moon Druid 12", origin="BuildAdvisor",
        classes={"Druid": 12}, subclass=[],
        stats=S(STR=10, DEX=14, CON=16, WIS=20), statw={"WIS": 2.5, "CON": 1.5},
        attacks={}, offhand="shield", armour="medium", caster=2,
        needs={"wildshape": 2.5, "healer": 1, "spell_dc": 2, "concentration": 1.5, "ac": 1, "saves": 1,
               "temp_hp": 1, "dmg_reduction": 1},
        why="Combat Wild Shape: a second HP bar; gear stays on in Wild Shape (on-hit and resistance items)."),
    "starsdruid": dict(
        name="Circle of Stars Druid 12", origin="BuildAdvisor",
        classes={"Druid": 12}, subclass=[],
        stats=S(STR=8, DEX=14, CON=16, WIS=20), statw={"WIS": 3, "CON": 1.5},
        attacks={}, offhand="shield", armour="medium", caster=2,
        needs={"spell_dc": 2.5, "healer": 2, "concentration": 2, "dmg_radiant": 1.5, "spell_slot": 1, "ac": 1},
        why="Starry Form keeps concentration safe (Dragon) and adds damage / heals every turn."),
    # ---------------- Dark Urge actual build (The White Urge campaign)
    "durge_hexblade": dict(
        name="Hexblade Warlock 12 with Great Weapon Master (Dark Urge)", origin="campaign",
        classes={"Warlock": 12}, subclass=["Hexblade"],
        stats=S(STR=10, DEX=14, CON=16, CHA=19), statw={"CHA": 3, "CON": 1.2},
        attacks={"melee2h": 4, "reach": 1}, offhand="none", armour="medium", caster=1,
        needs={"gwm": 2, "weapon_dmg": 2.5, "weapon_atk": 2.5, "adv": 2, "crit": 2.5, "arcane_synergy": 1,
               "bonus_enchant": 1.5, "concentration": 1, "spell_dc": 1, "dmg_necrotic": 0.5, "kill_trigger": 1.5,
               "mobility": 1},
        why="Pact two-hander with Hex Warrior (CHA attacks) + GWM; Hexblade's Curse crits on 19.",
        note="Taken from a real Dark Urge playthrough: White Dragonborn, Hexblade Warlock 12, CHA 19, Great Weapon Master. "
             "Assumes Pact of the Blade so Hex Warrior covers the two-handed pact weapon."),
}

for _bid, _b in BUILDS.items():
    _b["id"] = _bid

# ---------------------------------------------------------------- characters
CHARACTERS = {
    "astarion": dict(
        name="Astarion", race="High Elf", research="astarion.md",
        builds=["gloomassassin", "thiefmelee", "thx", "critarcher"],
        tags={"GSA": ["gloomassassin"], "GSA7": ["gloomassassin"], "THX": ["thx"], "TM": ["thiefmelee"],
              "CRIT": ["critarcher"], "all": "*"},
        default_tags=["gloomassassin"]),
    "gale": dict(
        name="Gale", race="Human", research="gale.md",
        builds=["tempestevoker", "evoker", "stormsorc", "firewiz", "bladesinger", "coldwiz"],
        tags={"EVO": ["evoker"], "STORM": ["stormsorc"], "FIRE": ["firewiz"], "COLD": ["coldwiz"],
              "ABJ": ["coldwiz"], "BLADE": ["bladesinger"], "CTRL": ["evoker"], "ALL": "*"},
        default_tags="*"),
    "karlach": dict(
        name="Karlach", race="Zariel Tiefling", research="karlach.md",
        builds=["giants", "throwzerker", "throw_zerk7_thief3", "gwmbarb", "bearbarb"],
        tags={"GIANT": ["giants"], "THROWZ": ["throwzerker"], "GWM": ["gwmbarb"], "WILD-B": ["bearbarb"],
              "WILD-T": ["gwmbarb"], "TB-GEN": ["giants", "throwzerker"]},
        soft_tags={"throwers": ["giants", "throwzerker"], "throw": ["giants", "throwzerker"],
                   "melee": ["gwmbarb"], "unarmoured": ["bearbarb"], "tank": ["bearbarb"]},
        default_tags="*"),
    "laezel": dict(
        name="Lae'zel", race="Githyanki", research="laezel.md",
        builds=["bmgiant", "sorcadin", "eldritchknight", "champion", "tankfighter"],
        # bmgiant replaced battlemaster as her BuildAdvisor build (decision 53): the Battle Master research is hers
        tags={"BM": ["bmgiant"], "SORC": ["sorcadin"], "EK": ["eldritchknight"],
              "FP": ["bmgiant", "sorcadin"], "CH": ["champion"], "TANK": ["tankfighter"]},
        default_tags="*"),
    "shadowheart": dict(
        name="Shadowheart", race="High Half-Elf", research="shadowheart.md",
        builds=["lightcleric", "lightquick", "stormsorc", "tempestcleric", "lifecleric", "trickcleric"],
        tags={"LIGHT": ["lightcleric"], "STORM": ["stormsorc"], "TRICK": ["trickcleric"],
              "TEMPEST": ["tempestcleric"], "LIFE": ["lifecleric"], "SG": ["lightcleric", "tempestcleric"],
              "CLESOR": ["stormsorc"]},
        default_tags="*"),
    "wyll": dict(
        name="Wyll", race="Human", research="wyll.md",
        builds=["sorlock", "lockadin", "hexsorlock", "ebwarlock", "hexblade", "bladelock"],
        tags={"SL": ["sorlock"], "LP": ["lockadin"], "EB": ["ebwarlock"], "HB": ["hexblade"], "BL": ["bladelock"]},
        default_tags="*"),
    "darkurge": dict(
        name="The Dark Urge", race="White Dragonborn", research="darkurge.md",
        builds=["throw_zerk5_thief4", "durge_hexblade", "oathbreaker", "sorcadin", "gloomassassin", "throwzerker"],
        # darkurge.md names builds in words; Lockadin research is the closest match to the actual Hexblade build
        word_tags={"Oathbreaker": ["oathbreaker"], "Sorcadin": ["sorcadin"], "Gloom Stalker": ["gloomassassin"],
                   "Gloomstalker": ["gloomassassin"], "Throwzerker": ["throwzerker"], "Giants": ["throwzerker"],
                   "Berserker": ["throwzerker"], "Lockadin": ["durge_hexblade"], "Hexblade": ["durge_hexblade"],
                   "Bardadin": [], "Storm Sorcerer": [], "Tempest": [], "Monk": []},
        tags={},
        default_tags="*"),
}

# Research of the same build in another character's file counts at half weight (general rule), plus these
# explicit cross-references for builds that have no own research section.
XREFS = {
    "durge_hexblade": [("wyll", "hexblade", 0.5), ("wyll", "lockadin", 0.4)],
    # session 4 builds without own research sections: the closest researched build (own file counts too)
    "tempestevoker": [("gale", "evoker", 0.7), ("gale", "stormsorc", 0.4), ("shadowheart", "stormsorc", 0.3)],
    "lightquick": [("shadowheart", "lightcleric", 0.8)],
    "hexsorlock": [("wyll", "sorlock", 0.8)],
    "throw_zerk7_thief3": [("karlach", "throwzerker", 0.8)],
    "throw_zerk5_thief4": [("darkurge", "throwzerker", 0.8), ("karlach", "throwzerker", 0.5)],
}

# BuildAdvisor gear lines and BA.Origins are read from Builds.lua at run time (la_common.load_builds_lua).
BUILDS_LUA = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                          "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender", "Lua", "Shared", "Builds.lua")


# ---------------------------------------------------------------- Builds.lua sync (round 3, 2026-10-09)
ABIL = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


def builds_lua_stats(path=BUILDS_LUA):
    """Level-12 ability scores of every Builds.lua build: base + plus2 / plus1 + the first choice of every
    "Feat: ..." pick ("Ability Improvement +2 DEX", "+1 WIS +1 CON", "Tavern Brawler (+1 STR)"; text after "(or"
    is an alternative and ignored), capped at 20. -> {build id: {"stats": {...}, "feats": [...], "styles": [...]}}"""
    import re
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return {}
    out = {}
    starts = [m.start() for m in re.finditer(r'\bid\s*=\s*"', src)]
    for i, s in enumerate(starts):
        block = src[s: starts[i + 1] if i + 1 < len(starts) else len(src)]
        bid = re.match(r'id\s*=\s*"([^"]+)"', block).group(1)
        bm = re.search(r"base\s*=\s*\{([^}]*)\}", block)
        if not bm:
            continue
        st = {k: int(v) for k, v in re.findall(r"(STR|DEX|CON|INT|WIS|CHA)\s*=\s*(\d+)", bm.group(1))}
        for key, n in (("plus2", 2), ("plus1", 1)):
            pm = re.search(key + r'\s*=\s*"([A-Z]{3})"', block)
            if pm:
                st[pm.group(1)] = st.get(pm.group(1), 10) + n
        feats, styles, levels, hls = [], [], [], []
        for lm in re.finditer(r'L\("([A-Za-z]+)",\s*\{([^}]*)\}(?:\s*,\s*\{([^}]*)\})?', block):
            levels.append((lm.group(1), re.findall(r'"([^"]*)"', lm.group(2))))
            hls.append((lm.group(1), re.findall(r'"([^"]*)"', lm.group(3) or "")))
            for pick in re.findall(r'"([^"]*)"', lm.group(2)):
                if pick.startswith("Feat:"):
                    first = pick[5:].split("(or")[0]
                    feats.append(first.split("(")[0].strip())
                    for n, ab in re.findall(r"\+(\d)\s*(STR|DEX|CON|INT|WIS|CHA)", first):
                        st[ab] = min(20, st.get(ab, 10) + int(n))
                elif pick.startswith("Fighting Style:"):
                    styles.append(pick[15:].split("(")[0].strip())
        out[bid] = {"stats": {a: st.get(a, 10) for a in ABIL}, "feats": feats, "styles": styles, "levels": levels,
                    "hl": hls}
    return out


class ProfileSyncError(Exception):
    pass


def builds_lua_subclasses(ba):
    """{class: subclass display name} from a Builds.lua build's star labels (hl): the label that is one of that
    class's subclass names in the game (class_progressions.json)."""
    out = {}
    by_disp = class_data()["by_display"]
    for cls, hl in ba["hl"]:
        for lab in hl:
            if lab in (by_disp.get(cls) or {}):
                out[cls] = lab
    return out


def sync_with_builds_lua(path=BUILDS_LUA):
    """Every build that exists in Builds.lua is a BuildAdvisor build: its profile takes the Builds.lua level-12
    stats, feats and fighting styles, and its subclasses (game names) from the build's star labels.
    A Builds.lua build without a profile here is an error (decision 65): raise ProfileSyncError listing them.
    -> list of (build id, old stats, new stats) where the profile had drifted."""
    drift = []
    ba_all = builds_lua_stats(path)
    if not ba_all:
        raise ProfileSyncError(f"no builds read from {path}")
    missing = sorted(bid for bid in ba_all if bid not in BUILDS)
    if missing:
        raise ProfileSyncError("Builds.lua builds without a LootAdvisor profile (add them to "
                               "tools/build_profiles.py BUILDS): " + ", ".join(missing))
    for bid, ba in ba_all.items():
        b = BUILDS[bid]
        # star labels name the subclass picked in the menu; the table below names the FINAL one where they differ
        # (Oathbreaker: pick Vengeance, break the oath later) - the table wins, the labels fill missing classes
        for cls, sub in builds_lua_subclasses(ba).items():
            SUBCLASSES.setdefault(bid, {}).setdefault(cls, sub)
        if b.get("stats") != ba["stats"]:
            drift.append((bid, dict(b.get("stats") or {}), ba["stats"]))
        b["stats"] = ba["stats"]
        b["feats"] = ba["feats"]
        b["styles"] = ba["styles"]
        cnt = {}
        lv = []
        for i, (c, picks) in enumerate(ba["levels"], 1):
            cnt[c] = cnt.get(c, 0) + 1
            lv.append({"level": i, "class": c, "class_level": cnt[c], "picks": picks, "source": "BuildAdvisor"})
        b["plan"] = {"source": "BuildAdvisor (Builds.lua)", "inferred": False, "levels": lv,
                     "feats": ba["feats"], "styles": ba["styles"], "from_research": []}
        if b.get("origin") != "campaign":
            b["origin"] = "BuildAdvisor"
    return drift


# ---------------------------------------------------------------- subclasses per build (LootData `sc`, mod build matching)
# class -> subclass as the game shows it (ClassDescriptions DisplayName: "Evocation", "Giant"); a class missing here
# has no fixed subclass in the build (any). Builds.lua builds are overwritten from their star labels at sync time;
# check_subclass_names() rejects any name the game does not use.
SUBCLASSES = {
    "gloomassassin": {"Ranger": "Gloom Stalker", "Rogue": "Assassin", "Fighter": "Battle Master"},
    "thx": {"Ranger": "Gloom Stalker", "Rogue": "Thief", "Fighter": "Battle Master"},
    "thiefmelee": {"Rogue": "Thief"},
    "critarcher": {"Ranger": "Gloom Stalker", "Rogue": "Assassin"},
    "evoker": {"Wizard": "Evocation"},
    "stormsorc": {"Sorcerer": "Storm Sorcery", "Cleric": "Tempest Domain"},
    "firewiz": {"Wizard": "Evocation"},
    "coldwiz": {"Wizard": "Abjuration"},
    "bladesinger": {"Wizard": "Bladesinging"},
    "sorlock": {"Warlock": "The Fiend", "Sorcerer": "Draconic Bloodline"},
    "ebwarlock": {},
    "lockadin": {"Paladin": "Oath of Vengeance", "Warlock": "The Hexblade"},
    "hexblade": {"Warlock": "The Hexblade"},
    "bladelock": {"Warlock": "The Hexblade"},
    "giants": {"Barbarian": "Giant"},
    "throwzerker": {"Barbarian": "Berserker"},
    "gwmbarb": {"Barbarian": "Berserker"},
    "bearbarb": {"Barbarian": "Wildheart"},
    "battlemaster": {"Fighter": "Battle Master"},
    "sorcadin": {"Paladin": "Oath of Vengeance", "Sorcerer": "Shadow Magic"},
    "oathbreaker": {"Paladin": "Oathbreaker"},
    "eldritchknight": {"Fighter": "Eldritch Knight"},
    "champion": {"Fighter": "Champion"},
    "tankfighter": {},
    "lightcleric": {"Cleric": "Light Domain"},
    "tempestcleric": {"Cleric": "Tempest Domain"},
    "lifecleric": {"Cleric": "Life Domain"},
    "trickcleric": {"Cleric": "Trickery Domain"},
    "tbmonk": {"Monk": "Way of the Open Hand"},
    "durge_hexblade": {"Warlock": "The Hexblade"},
    # session 4 (Builds.lua builds; the sync re-reads them from the star labels)
    "tempestevoker": {"Wizard": "Evocation", "Cleric": "Tempest Domain"},
    "lightquick": {"Cleric": "Light Domain", "Sorcerer": "Shadow Magic"},
    "hexsorlock": {"Sorcerer": "Draconic Bloodline", "Warlock": "The Hexblade"},
    "bmgiant": {"Fighter": "Battle Master"},
    "throw_zerk7_thief3": {"Barbarian": "Berserker", "Rogue": "Thief"},
    "throw_zerk5_thief4": {"Barbarian": "Berserker", "Rogue": "Thief", "Fighter": "Champion"},
    "bardadin": {"Paladin": "Oath of Vengeance", "Bard": "College of Swords"},
    "moondruid": {"Druid": "Circle of the Moon"},
    "starsdruid": {"Druid": "Circle of the Stars"},
}


def check_subclass_names():
    """Every SUBCLASSES entry must be a subclass name the game shows for that class; raise listing the bad ones."""
    bad = [f"{bid}: {cls} = {name!r}" for bid, subs in SUBCLASSES.items() for cls, name in subs.items()
           if subclass_internal(cls, name) is None]
    if bad:
        raise ProfileSyncError("subclass names the game does not use (see data/cache/class_progressions.json "
                               "by_display): " + "; ".join(bad))


# ---------------------------------------------------------------- level-by-level plans (round 5)
import re  # noqa: E402

SUBCLASS_LEVEL = {"Cleric": 1, "Sorcerer": 1, "Warlock": 1, "Paladin": 1, "Wizard": 2, "Druid": 2}
STYLE_LEVEL = {"Fighter": 1, "Paladin": 2, "Ranger": 2}
ASI_AT = {"Fighter": (4, 6, 8, 12), "Rogue": (4, 8, 10, 12)}
FEAT_NAMES = ["Great Weapon Master", "Sharpshooter", "Alert", "Tavern Brawler", "War Caster", "Polearm Master",
              "Dual Wielder", "Savage Attacker", "Elemental Adept", "Spell Sniper", "Lucky", "Tough", "Mobile",
              "Sentinel", "Resilient", "Heavy Armour Master", "Lightly Armoured", "Moderately Armoured",
              "Defensive Duellist", "Shield Master", "Athlete", "Magic Initiate"]
STYLE_NAMES = ["Archery", "Defence", "Duelling", "Great Weapon Fighting", "Two-Weapon Fighting", "Protection"]


def default_style(b):
    att = b["attacks"]
    if att.get("handxbow", 0) >= 2 and b.get("dual_ranged"):
        return "Two-Weapon Fighting" if any(c in b["classes"] for c in ("Fighter",)) else "Archery"
    if max(att.get("ranged", 0), att.get("handxbow", 0)) >= 2:
        return "Archery"
    if b["offhand"] == "dual":
        return "Two-Weapon Fighting"
    if att.get("melee2h", 0) >= 2 and b["offhand"] == "none":
        return "Great Weapon Fighting"
    if b["offhand"] == "shield" or b["armour"] == "heavy":
        return "Defence"
    return "Duelling" if att.get("melee1h", 0) >= 2 else "Defence"


def level_plan(bid, research_text=""):
    """Level 1-12 plan for a build: class per level (classes in profile order, the first class first), subclass at
    its level, fighting styles, feats / ability improvements. Builds.lua builds come from Builds.lua elsewhere; this is
    for community builds. Feats and styles named in the build's own research text come first (source research),
    the rest is filled by rule (inferred): ability improvement +2 on the main stat until 20, then Alert / Tough."""
    b = BUILDS[bid]
    subs = SUBCLASSES.get(bid, {})
    text = (research_text or "") + " " + b.get("why", "") + " " + b.get("name", "")
    feats_r = [f for f in FEAT_NAMES if re.search(r"\b" + re.escape(f) + r"\b", text, re.I)]
    if b["needs"].get("gwm") and "Great Weapon Master" not in feats_r:
        feats_r.insert(0, "Great Weapon Master")
    styles_r = [s for s in STYLE_NAMES if re.search(r"\b" + re.escape(s.replace("Defence", "Defen")) , text, re.I)]
    main = max(b["statw"], key=b["statw"].get)
    # level-1 main stat of a standard point buy (16 + racial +1 / +2 -> 17), raised by the improvements below
    cur = 17 if b["stats"].get(main, 10) >= 19 else b["stats"].get(main, 10)
    role = []
    if max(b["attacks"].get("ranged", 0), b["attacks"].get("handxbow", 0)) >= 2:
        role.append("Sharpshooter")
    if b["caster"] == 2 and b["needs"].get("concentration", 0) >= 1.5:
        role.append("War Caster")
    role_feats = [f for f in role if f not in feats_r]
    seq = [c for c, n in b["classes"].items() for _ in range(n)]
    levels, cnt, feats, styles = [], {}, [], []
    fr, sr = list(feats_r), list(styles_r)
    # rough level-1 score: assumed level-12 score minus the improvements we will add below
    for i, c in enumerate(seq, 1):
        cnt[c] = cnt.get(c, 0) + 1
        cl = cnt[c]
        picks, src = [], []
        if cl == SUBCLASS_LEVEL.get(c, 3) and subs.get(c):
            picks.append(f"Subclass: {subs[c]}")
        if cl == STYLE_LEVEL.get(c):
            st = sr.pop(0) if sr else default_style(b)
            picks.append(f"Fighting Style: {st}")
            styles.append(st)
            src.append("research" if st in styles_r else "inferred")
        if cl in ASI_AT.get(c, (4, 8, 12)):
            if fr:
                f = fr.pop(0)
                src.append("research")
            elif cur <= 18 and (cur < 19 and not any(x.startswith("Ability Improvement") for x in feats)
                                or not role_feats):
                f = f"Ability Improvement +2 {main}"
                cur += 2
                src.append("inferred")
            elif role_feats:
                f = role_feats.pop(0)
                src.append("inferred")
            elif cur <= 18:
                f = f"Ability Improvement +2 {main}"
                cur += 2
                src.append("inferred")
            elif cur == 19:
                f = f"Ability Improvement +1 {main} +1 CON"
                cur += 1
                src.append("inferred")
            elif role_feats:
                f = role_feats.pop(0)
                src.append("inferred")
            else:
                f = next((x for x in ("Alert", "Tough") if x not in feats), "Ability Improvement +2 CON")
                src.append("inferred")
            feats.append(f)
            picks.append(f"Feat: {f}")
        levels.append({"level": i, "class": c, "class_level": cl, "picks": picks,
                       "source": "inferred" if "inferred" in src else ("research" if src else "")})
    return {"source": "community (research + rules)", "inferred": any(lv["source"] == "inferred" for lv in levels),
            "levels": levels, "feats": feats, "styles": styles, "from_research": feats_r + styles_r}
