-- Dark Urge verdict build (model analysis/darkurge_model.py), in Builds.lua format; reference copy for
-- Mods/BuildAdvisor/ScriptExtender/Lua/Shared/Builds.lua (needs the local L() helper from there).
-- Suggested origin entry after the merge:
--   darkurge = { builds = { "throwthief", "throwzerker" }, note = "Race/class free. Berserker 5 / Thief 4 / Champion 3 thrower; Bhaalist Armour (Murder Tribunal) doubles Nyrulna's piercing damage." },
-- Level timings verified in Progressions.lsx (Shared/SharedDev/GustavX): Barbarian subclass 3, feat 4, Extra Attack 5;
-- Rogue (multiclass) 1 skill + 2 Expertise, Cunning Action 2, subclass 3 (Thief: Fast Hands), feat 4;
-- Fighter (multiclass) Fighting Style 1, Action Surge 2, subclass 3 (Champion: Improved Critical).

local function L(cls, picks, hl) return { cls = cls, picks = picks, hl = hl or {} } end

return {
  id = "throwthief", name = "Throw-Thief (Berserker Barbarian 5 / Thief Rogue 4 / Champion Fighter 3)", tier = "S+",
  role = "Thrower: 4 Tavern Brawler throws a turn, two of them Enraged Throws that knock the target Prone",
  why = "Enraged Throw is a bonus action with no once-per-turn limit, so Thief's Fast Hands gives a second one every turn; each Enraged Throw adds STR again and knocks Prone (no save), so the other throws get Advantage within 3 m. Tavern Brawler adds STR to every throw's attack and damage. With Bhaalist Armour (Murder Tribunal) Nyrulna's piercing damage is doubled: about 37% more sustained damage than the Throwzerker 10/2 and 2.4x the Oathbreaker in the model.",
  classes = { "Barbarian", "Rogue", "Fighter" }, start = "Barbarian",
  races = { "Duergar", "Half-Orc", "Githyanki" },
  raceWhy = "Duergar: Enlarge (+1d4 weapon damage for one fight a day) and Advantage against Hold Person / charm. Half-Orc: Relentless Endurance and 9 m speed. Githyanki: Misty Step. Savage Attacks does not work on throws.",
  background = "Haunted One (fixed for the Dark Urge: Intimidation, Medicine)",
  base = { STR = 15, DEX = 14, CON = 15, INT = 8, WIS = 10, CHA = 8 }, plus2 = "STR", plus1 = "CON",
  skills = { "Athletics", "Perception", "Sleight of Hand", "Intimidation" },
  levels = {
    L("Barbarian", { "Skills: Athletics, Perception (Haunted One already gives Intimidation, Medicine)", "Weapon: Returning Pike / any thrown weapon" }, { "Athletics", "Perception" }),
    L("Barbarian", { "Reckless Attack, Danger Sense" }, {}),
    L("Barbarian", { "Subclass: Berserker (Frenzy -> Enraged Throw, a bonus-action throw that knocks Prone)" }, { "Berserker" }),
    L("Barbarian", { "Feat: Tavern Brawler (+1 Strength)" }, { "Tavern Brawler" }),
    L("Barbarian", { "Extra Attack (works with the Throw action)" }, {}),
    L("Rogue", { "Skill: Sleight of Hand", "Expertise: Sleight of Hand, Athletics (Nyrulna's chest is Sleight of Hand DC 20)" }, { "Sleight of Hand", "Athletics" }),
    L("Rogue", { "Cunning Action" }, {}),
    L("Rogue", { "Subclass: Thief (Fast Hands = a second bonus action = a second Enraged Throw)" }, { "Thief" }),
    L("Fighter", { "Fighting Style: Defence" }, { "Defence" }),
    L("Fighter", { "Action Surge" }, {}),
    L("Fighter", { "Subclass: Champion (Improved Critical: crit on 19)" }, { "Champion" }),
    L("Rogue", { "Feat: Ability Improvement +2 Strength (20); with an Elixir of Cloud Giant Strength running all the time, +2 Dexterity instead" }, { "Ability Improvement" }),
  },
  gear = "Returning Pike -> Nyrulna, Gloves of Uninhibited Kushigo, Ring of Flinging, Caustic Band, Bhaalist Armour, Helmet of Grit / Sarevok's Horned Helmet, Elixir of Cloud Giant Strength",
  note = "Rage first (bonus action), then Enraged Throw with the Fast Hands bonus action so the target is Prone before the normal throws. Stand within 3 m of the target: Prone advantage and the Bhaalist aura both stop at 3 m. Only 3 rages per long rest (Barbarian 5).",
}
