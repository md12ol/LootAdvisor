-- Shadowheart verdict build (model analysis/shadowheart_model.py).
-- CORRECTED 2026-10-09: Quickened Spell is only offered from Sorcerer 3 (PassiveLists.lsx c3506532; Sorcerer 2 list
-- 49704931 = Careful/Distant/Extended/Twinned). The split is therefore Cleric 9 / Sorcerer 3. This matches the
-- `lightquick` entry in Builds.lua; kept here only as the analysis copy.
{
  id = "lightquick", name = "Light Domain Cleric 9 / Sorcerer 3 (Quickened)", tier = "S",
  role = "Radiant AoE caster + support: Radiance of the Dawn, Spirit Guardians and a quickened second spell",
  why = "Same as Light Cleric 12 up to level 9 (best cleric in Acts 1-2). Sorcerer 3 adds Quickened Spell (a second leveled spell each turn) and Shield: about 10% more Act 3 damage than Light Cleric 12, with or without the Weave kit. Costs Divine Intervention, Heal / Heroes' Feast and the level-12 feat.",
  classes = { "Cleric", "Sorcerer" }, start = "Cleric",
  races = { "High Half-Elf", "Wood Half-Elf", "Githyanki" },
  raceWhy = "Shadowheart is locked High Half-Elf (spears, glaives, shields; take Mage Hand as the race cantrip). For a Tav: Wood Half-Elf speed or Githyanki Misty Step.",
  background = "Acolyte (Shadowheart's own; Insight, Religion)",
  base = { STR = 8, DEX = 14, CON = 15, INT = 8, WIS = 15, CHA = 10 }, plus2 = "WIS", plus1 = "CON",
  skills = { "Insight", "Religion", "Medicine", "Persuasion" },
  levels = {
    L("Cleric", { "Light Domain (Warding Flare; Light, Burning Hands, Faerie Fire always prepared)", "Cantrips: Guidance, Sacred Flame, Toll the Dead", "Skills: Medicine, Persuasion", "Prepare: Bless, Healing Word, Guiding Bolt, Shield of Faith" }, { "Light Domain", "Guidance", "Sacred Flame", "Toll the Dead", "Medicine", "Persuasion", "Bless", "Healing Word", "Guiding Bolt", "Shield of Faith" }),
    L("Cleric", { "Channel Divinity: Radiance of the Dawn (1 charge per short rest)" }, {}),
    L("Cleric", { "Prepare: Spiritual Weapon, Aid, Silence (domain: Flaming Sphere, Scorching Ray)" }, { "Spiritual Weapon", "Aid" }),
    L("Cleric", { "Feat: Ability Improvement +2 WIS", "Cantrip: Bursting Sinew (Light is already granted at level 1)" }, { "Ability Improvement", "Bursting Sinew" }),
    L("Cleric", { "Prepare: Spirit Guardians, Revivify, Mass Healing Word (domain: Fireball, Daylight)" }, { "Spirit Guardians", "Revivify", "Mass Healing Word" }),
    L("Cleric", { "Improved Warding Flare; 2nd Channel Divinity charge" }, {}),
    L("Cleric", { "Prepare: Banishment, Death Ward, Freedom of Movement (domain: Guardian of Faith, Wall of Fire)" }, { "Banishment", "Death Ward" }),
    L("Cleric", { "Potent Spellcasting (cantrips + WIS)", "Feat: Resilient - Constitution (no Auntie Ethel's Hair: Ability Improvement +1 WIS +1 CON instead)" }, { "Resilient", "Constitution" }),
    L("Cleric", { "Prepare: Greater Restoration, Mass Cure Wounds (domain: Flame Strike, Destructive Wave)" }, { "Greater Restoration", "Mass Cure Wounds" }),
    L("Sorcerer", { "Sorcerous Origin: Shadow Magic (Strength of the Grave)", "Cantrips: Minor Illusion, Blade Ward, Friends, Dancing Lights", "Spells: Shield, Magic Missile" }, { "Shadow Magic", "Minor Illusion", "Blade Ward", "Shield", "Magic Missile" }),
    L("Sorcerer", { "Metamagic (Sorcerer 2 offers Careful / Distant / Extended / Twinned): Twinned Spell, Careful Spell", "Spell: Feather Fall" }, { "Twinned Spell", "Careful Spell", "Feather Fall" }),
    L("Sorcerer", { "Metamagic: Quickened Spell", "Spell: Misty Step", "Turn spare level-1 slots into sorcery points (Quickened = 3 points)" }, { "Quickened Spell", "Misty Step" }),
  },
  gear = "Markoheshkir or Staff of Spell Power, Viconia's Walking Fortress, Amulet of the Devout, Hood of the Weave / Helm of Balduran, Coruscation Ring + Callous Glow Ring, Luminous Gloves / Helldusk Gloves, Helldusk Armour / Dark Justiciar Half-Plate",
  note = "Respec with Withers (race stays High Half-Elf). Play it as Light Cleric 12 until level 9. Radiance of the Dawn cannot be quickened (no Spell flag); quicken Fireball, Destructive Wave or Spirit Guardians. Keep a light on Shadowheart for Coruscation Ring. Same build on the Shar and Selune paths.",
},
