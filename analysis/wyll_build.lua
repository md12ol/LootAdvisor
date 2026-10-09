-- Wyll verdict build, in BuildAdvisor's Builds.lua format (analysis/WYLL_BEST_BUILD.md, analysis/wyll_model.py).
-- Not merged: the main session copies the table into BA.Builds and adds "hexsorlock" to BA.Origins.wyll.builds.
-- hl strings are the game's English UI labels (loca of the Progressions / stats DisplayName). Metamagic passives are
-- labelled "Metamagic: Quickened Spell" etc. in loca; the hl key "Quickened Spell" matches that label (and a bare
-- "Quickened Spell") through the highlighter's substring rule. Note the British spelling "Agonising Blast".

local function L(cls, picks, hl) return { cls = cls, picks = picks, hl = hl or {} } end

local build = {
  id = "hexsorlock", name = "Hexblade Sorlock (Hexblade Warlock 2 / Draconic Sorcerer 8 / Fighter 2)", tier = "S",
  role = "Ranged Eldritch Blast damage: up to 9 beams in an Action Surge turn, Hold Person / Haste / Fireball support",
  why = "Two Eldritch Blasts a turn (Quickened from Sorcerer 3), Charisma added twice per beam (Agonising Blast + Potent Robe), Hexblade's Curse uses the bonus actions Sorcery Points cannot fill, Action Surge at 12. About 20% more sustained damage than the Fiend Sorlock and 50-65% more in the opening round.",
  classes = { "Sorcerer", "Warlock", "Fighter" }, start = "Sorcerer",
  races = { "Human" },
  raceWhy = "Wyll's race is locked. Human Civil Militia gives shield proficiency, so the caster can carry a shield.",
  background = "Wyll's own origin background (locked; Athletics, Persuasion)",
  base = { STR = 8, DEX = 14, CON = 15, INT = 8, WIS = 10, CHA = 15 }, plus2 = "CHA", plus1 = "CON",
  skills = { "Deception", "Intimidation", "Perception" },
  levels = {
    L("Sorcerer", { "Draconic Bloodline, Draconic Ancestry: Red (Fire)", "Cantrips: Fire Bolt, Shocking Grasp, Mage Hand, Minor Illusion", "Spells: Shield, Magic Missile", "Skills: Deception, Intimidation (Human Versatility: Perception)" },
      { "Draconic Bloodline", "Draconic Ancestry: Red (Fire)", "Fire Bolt", "Shield", "Magic Missile", "Deception", "Intimidation" }),
    L("Warlock", { "Patron: The Hexblade (Hex Warrior, Hexblade's Curse)", "Cantrips: Eldritch Blast, Toll the Dead", "Spells: Hex, Armour of Agathys" },
      { "The Hexblade", "Eldritch Blast", "Hex", "Armour of Agathys" }),
    L("Warlock", { "Invocations: Agonising Blast, Repelling Blast", "Spell: Hellish Rebuke" },
      { "Agonising Blast", "Repelling Blast" }),
    L("Sorcerer", { "Metamagic: Twinned Spell, Distant Spell (Quickened is not offered at Sorcerer 2)", "Spell: Sleep" },
      { "Twinned Spell", "Distant Spell" }),
    L("Sorcerer", { "Metamagic: Quickened Spell (Quickened Eldritch Blast as the bonus action)", "Spell: Hold Person (twin it)", "Eldritch Blast now fires 2 beams" },
      { "Quickened Spell", "Hold Person" }),
    L("Sorcerer", { "Feat: Ability Improvement +2 CHA", "Cantrip: Light", "Spell: Misty Step" },
      { "Ability Improvement", "Misty Step" }),
    L("Sorcerer", { "Spell: Haste" }, { "Haste" }),
    L("Sorcerer", { "Elemental Affinity (fire spells add CHA)", "Spell: Fireball" }, { "Fireball" }),
    L("Sorcerer", { "Spell: Greater Invisibility (advantage when the Risky Ring is on someone else)" }, { "Greater Invisibility" }),
    L("Sorcerer", { "Feat: Ability Improvement +1 CHA +1 CON (CHA 22 with Birthright; Spell Sniper instead if Auntie Ethel's Hair or the Mirror of Loss already gave +CHA)", "Spell: Dimension Door", "Eldritch Blast now fires 3 beams" },
      { "Ability Improvement", "Dimension Door" }),
    L("Fighter", { "Fighting Style: Protection (works with the shield)", "Second Wind", "Alternative: Sorcerer 9, Hold Monster" }, { "Protection" }),
    L("Fighter", { "Action Surge (a third Eldritch Blast once per short rest)", "Alternative: Sorcerer 10, Metamagic: Heightened Spell" }, {}),
  },
  gear = "Potent Robe, Birthright, Markoheshkir, Ketheric's Shield, Helldusk Gloves (or Spellmight Gloves), Cloak of the Weave, Callous Glow Ring, Risky Ring, The Dead Shot in the ranged slot",
  note = "Respec Wyll with Withers and start as Sorcerer (CON saves for Hex). Levels 1-10 are a plain Hexblade Sorlock; at 11-12 take Fighter 1-2 for Action Surge, or Sorcerer 9-10 for Hold Monster and Heightened Spell (5% less damage, better control). In the story his patron stays Mizora whatever subclass you pick.",
}

return build
