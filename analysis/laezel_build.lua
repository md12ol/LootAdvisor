-- Lae'zel verdict build (analysis/LAEZEL_BEST_BUILD.md, model analysis/laezel_model.py). Builds.lua format.
-- NOT merged: the main session decides. Suggested origin line:
--   laezel = { builds = { "bmgiant", "oathbreaker" }, note = "Githyanki (locked). Stays Fighter: Battle Master with an advantage source; Vengeance Paladin 12 is the runner-up (respec with Withers)." },
-- (The runner-up is Vengeance Paladin 12 with Haste; Builds.lua's "oathbreaker" entry starts as Vengeance and reaches
--  it if the oath is never broken - see the doc. The current "sorcadin" entry has an illegal pick, see doc section 7.)
-- All hl labels are the game's UI names (loca of the stats DisplayName); levels follow Progressions.lsx:
-- Fighter style 1, Action Surge 2, subclass 3, feats 4/6/8/12, Extra Attack 5, Indomitable 9,
-- Improved Combat Superiority 10, Improved Extra Attack 11; manoeuvres 3 at 3, 2 at 7, 2 at 10.

local function L(cls, picks, hl) return { cls = cls, picks = picks, hl = hl or {} } end

return {
  id = "bmgiant", name = "Battle Master Fighter 12 (Giantslayer + advantage)", tier = "S+",
  role = "Melee damage: 3 attacks + Action Surge, Trip/Riposte, best burst and trash clearing",
  why = "Model (laezel_model.py): Act 3 boss fights 110 damage/round with an advantage source (Gloves of the Automaton + Hill Giant elixir), 136 with the Risky Ring, 152 when hasted; best Act 2, best burst and fastest trash clearing. Vengeance Paladin 12 is level with it only in long Act 3 boss fights. Great Weapon Master pays only with Advantage: switch 'All In' off without it.",
  classes = { "Fighter" }, start = "Fighter",
  races = { "Githyanki", "Half-Orc", "Shield Dwarf" },
  raceWhy = "Githyanki (Lae'zel, locked): Misty Step, Astral Knowledge; Githyanki Greatsword / Silver Sword psychic bonus. Half-Orc for a Tav: Savage Attacks on crits.",
  background = "Soldier (Lae'zel's fixed background: Athletics, Intimidation)",
  base = { STR = 15, DEX = 10, CON = 15, INT = 8, WIS = 14, CHA = 8 }, plus2 = "STR", plus1 = "CON",
  skills = { "Athletics", "Intimidation", "Perception", "Insight" },
  levels = {
    L("Fighter", { "Fighting Style: Great Weapon Fighting", "Skills: Perception, Insight (Athletics + Intimidation come from Soldier)" }, { "Great Weapon Fighting", "Perception", "Insight" }),
    L("Fighter", { "Action Surge" }, {}),
    L("Fighter", { "Battle Master", "Manoeuvres: Trip Attack, Riposte, Precision Attack" }, { "Battle Master", "Trip Attack", "Riposte", "Precision Attack" }),
    L("Fighter", { "Feat: Great Weapon Master (toggle 'Great Weapon Master: All In' off when you have no Advantage)" }, { "Great Weapon Master" }),
    L("Fighter", { "Extra Attack" }, {}),
    L("Fighter", { "Feat: Ability Improvement +2 STR (19)" }, { "Ability Improvement" }),
    L("Fighter", { "Manoeuvres: Menacing Attack, Goading Attack (5th superiority die)" }, { "Menacing Attack", "Goading Attack" }),
    L("Fighter", { "Feat: Savage Attacker" }, { "Savage Attacker" }),
    L("Fighter", { "Indomitable" }, {}),
    L("Fighter", { "Improved Combat Superiority (d10)", "Manoeuvres: Pushing Attack, Disarming Attack" }, { "Pushing Attack", "Disarming Attack" }),
    L("Fighter", { "Improved Extra Attack (3 attacks)" }, {}),
    L("Fighter", { "Feat: Alert" }, { "Alert" }),
  },
  gear = "Balduran's Giantslayer, Helldusk Armour, Helm of Balduran, Gloves of the Automaton + Elixir of Hill Giant Strength (or Risky Ring + Gauntlets of Hill Giant Strength), Cloak of Displacement, Amulet of Greater Health",
  note = "Lae'zel is already a Fighter: no respec needed (redo her levels with Withers if she was levelled otherwise). Open every boss fight with Action Surge; Trip Attack on the first swing each round; keep 1 die for Riposte. Give her an advantage source - it is worth more than +2 STR.",
}
