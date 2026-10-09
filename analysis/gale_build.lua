-- Gale verdict build (analysis/GALE_BEST_BUILD.md, model analysis/gale_model.py), in BA.Builds format.
-- For the main session to merge into Mods/BuildAdvisor/ScriptExtender/Lua/Shared/Builds.lua (not merged here).
-- Suggested origin line: gale = { builds = { "tempestevoker", "stormsorc" }, note = "Human (locked). Wizard 1-5, Tempest Cleric at 6-7 (Withers), then Wizard to 10." }
-- Levels follow the game's Progressions.lsx: Evocation at Wizard 2, feats at Wizard 4 / 8, Potent Cantrip at
-- Wizard 6, Empowered Evocation at Wizard 10; Tempest Domain is chosen at Cleric 1 (heavy armour, martial weapons,
-- Thunderwave + Fog Cloud always prepared), Destructive Wrath at Cleric 2.

local function L(cls, picks, hl) return { cls = cls, picks = picks, hl = hl or {} } end

return {
  id = "tempestevoker", name = "Evocation Wizard 10 / Tempest Cleric 2", tier = "S",
  role = "AoE lightning nuker in heavy armour; Sculpt Spells keeps allies safe",
  why = "Destructive Wrath maximises a whole Lightning cast (Markoheshkir's free Chain Lightning every short rest: about 89 per target) and Empowered Evocation adds INT to every target, dart and beam. Tempest also gives heavy armour. Model: +17% sustained AoE and +24% single target over Evocation Wizard 12 at level 12, AC 22 instead of 16.",
  classes = { "Wizard", "Cleric" }, start = "Wizard",
  races = { "Human", "Githyanki", "High Elf" },
  raceWhy = "Gale is a locked Human (light armour + shields). For a Tav: Githyanki for Misty Step, High Elf for an extra wizard cantrip; Tempest gives the heavy armour anyway.",
  background = "Sage (Gale's own)",
  base = { STR = 8, DEX = 14, CON = 15, INT = 15, WIS = 10, CHA = 8 }, plus2 = "INT", plus1 = "CON",
  skills = { "Arcana", "History", "Investigation", "Perception" },
  levels = {
    L("Wizard", { "Cantrips: Fire Bolt, Shocking Grasp, Minor Illusion", "Spells: Magic Missile, Shield, Chromatic Orb, Mage Armour, Find Familiar, Sleep" }, { "Fire Bolt", "Shocking Grasp", "Minor Illusion", "Magic Missile", "Shield", "Chromatic Orb", "Mage Armour", "Find Familiar", "Sleep" }),
    L("Wizard", { "Evocation School (Sculpt Spells)", "Spells: Thunderwave, Feather Fall" }, { "Evocation", "Thunderwave", "Feather Fall" }),
    L("Wizard", { "Spells: Misty Step, Scorching Ray" }, { "Misty Step", "Scorching Ray" }),
    L("Wizard", { "Feat: Ability Improvement +2 INT", "Cantrip: Mage Hand", "Spells: Shatter, Hold Person" }, { "Ability Improvement", "Mage Hand", "Shatter", "Hold Person" }),
    L("Wizard", { "Spells: Fireball, Lightning Bolt (learn Haste / Counterspell from scrolls)" }, { "Fireball", "Lightning Bolt" }),
    L("Cleric", { "Tempest Domain: heavy armour + martial weapons, Wrath of the Storm, Thunderwave + Fog Cloud always prepared", "Cantrips: Guidance, Resistance, Light", "Prepare: Bless", "Put on heavy armour (Plate Armour) now" }, { "Tempest Domain", "Guidance", "Resistance", "Light", "Bless" }),
    L("Cleric", { "Channel Divinity: Destructive Wrath (save it for Lightning Bolt / Chain Lightning on a group)", "Prepare: Healing Word" }, { "Healing Word" }),
    L("Wizard", { "Potent Cantrip", "Spells: Haste, Counterspell" }, { "Haste", "Counterspell" }),
    L("Wizard", { "Spells: Greater Invisibility, Wall of Fire" }, { "Greater Invisibility", "Wall of Fire" }),
    L("Wizard", { "Feat: Ability Improvement +1 INT +1 CON (INT 20)", "Spells: Ice Storm, Banishment" }, { "Ability Improvement", "Ice Storm", "Banishment" }),
    L("Wizard", { "Spells: Cone of Cold, Hold Monster" }, { "Cone of Cold", "Hold Monster" }),
    L("Wizard", { "Empowered Evocation", "Cantrip: Ray of Frost", "Spells: Telekinesis, Conjure Elemental" }, { "Ray of Frost", "Telekinesis", "Conjure Elemental" }),
  },
  gear = "Markoheshkir (Kereska's Favour: Lightning), Ketheric's Shield, Hood of the Weave, Armour of Persistence, Cloak of the Weave, Helldusk Gloves, Helldusk Boots, Amulet of Greater Health, Ring of Feywild Sparks, Callous Glow Ring, Elixir of Battlemage's Power",
  note = "Respec Gale once with Withers for these stats and spells; at level 6 take Cleric in the normal level-up (Fireball first at 5). Use Destructive Wrath on Markoheshkir's free Chain Lightning each short rest. Switch Kereska's Favour to Fire for single-boss fights. Amulet of the Devout gives a 4th Destructive Wrath if Shadowheart does not take it.",
}
