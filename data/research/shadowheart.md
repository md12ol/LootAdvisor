# Shadowheart - LootAdvisor web research

Patch 8 (current hotfixes). Character: Shadowheart, High Half-Elf (locked race), default Trickery Domain Cleric, Acolyte.
Item data (names, rarity, UIDs, locations, X/Y) comes from bg3.wiki raw page data unless noted; build picks come from the
guides listed at the end. All text is summarised. `uid` is the bg3.wiki stats/template id (useful for game-file matching).

## 0. Proficiency facts that drive item choice (check before recommending)

- Racial: High Half-Elf gets **Civil Militia** = spears, pikes, halberds, glaives, light armour, shields. So spears
  (Shar's Spear of Evening / Selûne's Spear of Night) and glaives (Moonlight Glaive) are proficient on every build.
- Cleric base: simple weapons, light + medium armour, shields.
- **Light Domain gives NO heavy armour and NO martial weapons.** Pure Light Cleric 12 is not proficient with
  morningstars (The Sacred Star), flails (Defender Flail), longswords (Phalar Aluve), longbows, hand/heavy crossbows
  (Fabricated Arbalest). Several guides still list these - flag as "needs Weapon Master / martial multiclass".
  Exception: **Helldusk Armour can be worn without proficiency.**
- **Tempest Domain grants heavy armour + martial weapons** (also when taken as a 2-level dip), so Storm Sorc 10 / Tempest 2
  can use Adamantine Splint, Flawed Helldusk, Armour of Persistence, The Sacred Star, Hellrider Longbow, Fabricated Arbalest.
- Holy Lance Helm, Dark Justiciar Helmet, Helm of Balduran, Boots of Striding, Boots of Persistence, The Reviving Hands,
  Speedy Lightfeet are "medium armour" headwear/footwear/handwear: need medium proficiency (all cleric builds have it).

## 1. Builds covered

- **LIGHT** - Light Domain Cleric 12 (BuildAdvisor main): radiant/fire blaster, Spirit Guardians (Radiant), Radiating Orb debuff stacking, Warding Flare.
- **STORM** - Storm Sorcerer 10 / Tempest Cleric 2 (BuildAdvisor alt): heavy-armoured lightning/thunder blaster, Destructive Wrath (max dmg), Chain Lightning, Reverberation.
- **TRICK** - Trickery Cleric (default): Shar/darkness/obscurement support, stealth, Shar's Spear; "Sharran darkness" gear.
- **TEMPEST** - pure Tempest Cleric: thunder/lightning caster + Spirit Guardians front-liner, Destructive Wrath, heavy armour.
- **LIFE** - Life Cleric healer: on-heal buff gear (Bless/Blade Ward/temp HP on heal).
- **SG** - Spirit Guardians melee-cleric (any domain): concentration protection, Con saves, mobility, on-hit while concentrating.
- **CLE/SOR** - Cleric x / Sorcerer y hybrids (e.g. Cleric 10 / Sorc 2 for Quickened, or Gamestegy's "Blaster Tempest" Cleric 9 / Storm Sorc 3): wants spell save DC stacking.

## 2. Best items per act, per slot

Legend: Builds = which builds the item suits. WARNING = theft / killing a neutral or friendly NPC / story choice.
MISSABLE = can be permanently lost.

General missable rules:
- **Rosymorn Monastery / Mountain Pass / Crèche Y'llek** (Act 1) items are lost if you leave Act 1 via the Underdark ->
  Grymforge route without visiting the Mountain Pass first.
- **Last Light Inn vendors (Talli, Mattis, Dammon)** in Act 2 die if the inn falls (Isobel killed/abducted). Buy early.
- **Moonrise Towers vendors (Lann Tarv, Roah Moonglow, Araj Oblodra)** turn hostile/leave during the Moonrise assault.
  Araj reappears in Act 3 (Crimson Draughts, Lower City) with her unbought stock; Lann Tarv/Roah do not.

---

### ACT 1

#### Main hand
- **The Blood of Lathander** - legendary +3 Mace (1d6+3), uid `S_CRE_BloodOfLathander`. Sheds holy light 6 m
  (blinds fiends/undead on failed DC 14 Con save), once-per-LR save from death + heal, Sunbeam (lvl 6, 1/LR, no recast).
  WHY: best caster mace in Act 1 and the build's **portable light source** - illuminates you and nearby enemies, which is
  exactly what Coruscation Ring (wearer illuminated) and Callous Glow Ring (target illuminated) need in Act 2+.
  Builds: LIGHT (core), TRICK, LIFE, SG, TEMPEST. HOW: quest "Find the Blood of Lathander" - in Rosymorn Monastery put the
  four Ceremonial weapons (any longsword/mace/warhammer/battleaxe works) on their altars to open the hidden chamber with
  **Dawnmaster's Crest**; use the Crest to disable the artefact's defences; the mace sits on a locked altar in the
  Secret Chamber, Crèche Y'llek (X 1068, Y -779). MISSABLE (Mountain Pass route only).
- **The Spellsparkler** - rare Quarterstaff, uid `MAG_ChargedLightning_Quarterstaff`. Gain 2 Lightning Charges whenever you
  deal damage with a spell/cantrip (charges: +1 attack, +1 lightning dmg, 5 charges = +1d8 burst).
  Builds: STORM (Act 1-2 BiS), TEMPEST. HOW: one-of-three reward from Florrick for saving her during "Rescue the Grand Duke",
  Waukeen's Rest (X -63, Y 600). MISSABLE: Florrick must survive the burning inn; you only get ONE of Spellsparkler /
  The Joltshooter / The Sparky Points.
- **Melf's First Staff** - uncommon +1 Quarterstaff, uid `MAG_BasicEnchanted_Quarterstaff`. +1 spell save DC and spell attack
  (Arcane Enchantment +1), Melf's Acid Arrow 1/LR. Builds: STORM, any caster wanting DC. HOW: sold by Blurg, Ebonlake Grotto
  (Myconid Colony, Underdark) X 111, Y -89.
- **Staff of Arcane Blessing** - uncommon Quarterstaff, uid `UNI_UND_Tower_StaffBlessMystra`. Bless 1/LR; your Bless also adds
  +1d4 to spell attacks. Builds: LIFE/support. HOW: Arcane Tower basement, leaning on a table (X 164, Y 432); needs the
  Guiding Light ring from Bernard (persuade or defeat) to reach the basement.
- **Shattered Flail** (actually a Mace) - rare +2, uid `UNI_PLA_ConflictedFlind_Flail_Broken`. Heals wielder on hit, risk of
  Madness when you stop attacking. Builds: SG melee cleric (niche). HOW: carried by Flind (gnoll leader attacking the
  Zhentarim caravan), The Risen Road (X 33, Y 597).
- Not proficient for LIGHT/TRICK/LIFE (martial): Phalar Aluve (rare +1 longsword, sword-in-stone Underdark X 116 Y -192;
  Sing/Shriek aura), Defender Flail (rare +1 flail, AC/physical-dmg reduction, sold by A'jak'nir Jeera, Crèche Y'llek).
  Gamestegy lists both for Light/Tempest; only TEMPEST/STORM (via Tempest dip) are proficient.
- Off-hand light source: **Shining Staver-of-Skulls** - uncommon +1 Light Hammer, uid `MAG_Radiant_Radiating_Hammer`,
  25 ft light aura + 1d4 radiant. Simple weapon, so all clerics can carry it as an off-hand light source when not using a
  shield. HOW: carried by Greymon on the Gekh Coal raft to Grymforge, later sold by Corsair Greymon in Grymforge.

#### Off hand / shield
- **Adamantine Shield** - rare, uid `WPN_HUM_Shield_Adamantine_A`. No crits against you; melee misses make attacker
  Reeling; Shield Bash. Builds: all cleric builds, STORM (Tempest gives shields). HOW: Adamantine Forge, Grymforge
  (X -558, Y 230): Shield Mould + Mithral Ore, then run the forge.
- **Safeguard Shield** - uncommon, uid `MAG_Safeguard_Shield`, +1 all saving throws. HOW: sold by Dammon, Emerald Grove
  (The Hollow X 177, Y 562). Builds: LIGHT/SG (concentration saves).
- **The Real Sparky Sparkswall** - uncommon shield, uid `MAG_ChargedLightning_StaticDischarge_Shield`, Lightning Aura action.
  Builds: STORM theme pick only. HOW: locked + trapped chest, Grymforge (X -695, Y 420).
- Glowing Shield (temp HP when badly hurt, Goblin Camp locked chest X -53 Y 461) - filler.

#### Ranged
- **Bow of Awareness** - uncommon +1 Shortbow (simple, proficient), uid `MAG_Generic_01_Shortbow_1`, +1 Initiative.
  Builds: all (initiative stick). HOW: sold by Roah Moonglow in the Shattered Sanctum (goblin temple) X 272, Y -31.
- Spellthief (uncommon longbow, regain lvl-1 slot on crit; martial - Tempest/Storm only), sold by Arron, The Hollow.

#### Head
- **Holy Lance Helm** - uncommon (medium-armour helm), uid `MAG_Radiant_Radiating_Helmet`. +1 Con saves; attackers who miss you
  must pass DC 14 Dex save or take 1d4 radiant (Smite the Graceless). WHY: radiant procs feed Luminous Armour/Gloves,
  Gloves of Belligerent Skies; +1 Con helps concentration. Builds: LIGHT (BiS Act 1), SG, TEMPEST, CLE/SOR.
  HOW: painted chest reached from the top level, Rosymorn Monastery (X 120, Y 35). MISSABLE (Mountain Pass).
- **Wapira's Crown** - uncommon, uid `MAG_Healer_HealSelf_Helmet`, heals you whenever you heal others. Builds: LIFE.
  HOW: Zevlor's reward in "Save the Refugees" if you accept the money (Secluded Chamber, Emerald Grove).
- **The Shadespell Circlet** - uncommon, uid `MAG_Shadow_SpellDCBonusWhileObscured_Circlet`, + spell save DC while obscured.
  Builds: TRICK (Shar darkness), STORM (Gamestegy Act 1 pick). HOW: Omeluum, Ebonlake Grotto, after "Help Omeluum Investigate
  the Parasite".
- **The Lifebringer** - uncommon circlet, uid `MAG_ChargedLightning_TempHP_Circlet`, temp HP when you gain Lightning Charges.
  Builds: STORM with Spellsparkler. HOW: sold by Blurg, Ebonlake Grotto.
- Haste Helm (rare, momentum at combat start; Moss-Covered Chest, Blighted Village X 29 Y 405) - generic runner-up.

#### Chest / armour
- **Luminous Armour** - uncommon +1 Medium Armour (AC 15 + Dex max 2), uid `MAG_Radiant_RadiatingOrb_Armor`. Whenever you deal
  radiant damage, emits a Radiant Shockwave that spreads Radiating Orb to nearby enemies. WHY: the engine of the Light/radiant
  build; many guides (Gamestegy, Hack the Minotaur) keep it to the END of the game. Builds: LIGHT (BiS), SG, TEMPEST, CLE/SOR.
  HOW: locked + trapped opulent chest, Selûnite Outpost (Underdark) X 176, Y -247 - behind a hidden door (Perception) or jump
  over from the waypoint room. Honour Mode note (community): low-level smites don't trigger the shockwave; spells do.
- **Adamantine Splint Armour** - very rare Heavy (AC 18), uid `MAG_MeleeDebuff_AttackDebuff2_OnDamage_SplintMail`. -2 all damage,
  attackers Reeling, no crits. Builds: STORM (Tempest dip), TEMPEST, LIFE. Not LIGHT (no heavy prof).
  HOW: Adamantine Forge, Grymforge: Splint Mould + Mithral Ore.
- **Adamantine Scale Mail** - very rare Medium (AC 16), uid `ARM_Scalemail_Adamantine_A`. -1 damage, no crits.
  Builds: LIGHT/SG tank alternative to Luminous. HOW: Adamantine Forge (Scale Mail Mould + Mithral Ore).
- **The Protecty Sparkswall** - rare Clothing, uid `MAG_ChargedLightning_BonusAC_Robe`, +1 spell save DC and AC/saves while you
  have Lightning Charges. Builds: STORM (Gamestegy Act 1-2 pick). HOW: gilded chest at end of the trapped bridge, Grymforge
  (X -645, Y 360).
- **Spidersilk Armour** - rare Light Armour, uid `GOB_DrowCommander_Armor_Leather`, Advantage on Con saves. Builds: SG, TRICK.
  HOW: worn by Minthara, Shattered Sanctum. WARNING: Minthara must die (goblin-raid path) - or she is recruitable on the evil
  path, so killing her locks out that companion.

#### Cloak
- **No meaningful magical cloak exists in Act 1** (bg3.wiki cloak list: the only Act 1 magic cloak is The Deathstalker Mantle,
  Dark Urge origin only). First good cloaks are Act 2 (Cloak of Protection, Thunderskin Cloak).

#### Gloves
- **Gloves of Belligerent Skies** - uncommon, uid `MAG_Thunder_Reverberation_Gloves`. Thunder, lightning OR radiant damage
  inflicts 2 turns of Reverberation (stacks to 5 = 1d4 thunder + Con save vs Prone; -1 Str/Dex/Con saves per stack).
  WHY: works for BOTH main builds (radiant for LIGHT, lightning/thunder for STORM); widely called best caster gloves of Act 1-2.
  Builds: LIGHT, STORM, TEMPEST, CLE/SOR. HOW: elegant chest on the south wall (west side), Inquisitor's Chamber, Crèche Y'llek
  (X 1348, Y -677). MISSABLE (Mountain Pass). WARNING: the Inquisitor's Chamber is a restricted githyanki area - get access by
  dialogue (claim business with the Inquisitor) and loot unseen, or loot after the githyanki turn hostile; looting in view of
  neutral gith risks a theft/hostility response.
- **Hellrider's Pride** - uncommon, uid `DEN_HellridersPride`. Creatures you heal gain resistance to weapon physical damage
  (works like Blade Ward). Builds: LIFE, support LIGHT. HOW: reward from Zevlor for "Kill Kagha" / "Investigate Kagha"
  (Secluded Chamber, Emerald Grove). WARNING: can also be looted or stolen from Zevlor - use the quest reward instead.
- Bracers of Defence (rare, +2 AC only when unarmoured and no shield) - STORM in robes only; gilded chest, Apothecary's Cellar
  (Blighted Village).

#### Boots
- **Boots of Stormy Clamour** - uncommon, uid `MAG_Thunder_ReverberationOnStatusApply_Boots`. Inflicting any condition on an enemy
  also applies 2 turns of Reverberation (only first target per action). Builds: STORM, LIGHT (Blood of Lathander blind, Sacred
  Flame-less conditions, Command, Hold Person), TEMPEST. HOW: sold by Omeluum after "Help Omeluum Investigate the Parasite",
  Ebonlake Grotto (X 144, Y 29).
- **Boots of Striding** - uncommon (medium-armour boots), uid `MAG_Paladin_MomentumOnConcentration_Boots`, +1 Athletics; gain
  Momentum (speed) when you start concentrating; prevents being shoved/knocked prone while concentrating (per guides).
  Builds: SG (BiS for Spirit Guardians walking), LIGHT, TEMPEST. HOW: worn by Minthara, Shattered Sanctum (X 335, Y 43).
  WARNING: same Minthara kill caveat as above (guides say a copy is also obtainable later from her in Act 2 Moonrise).
- **The Watersparkers** - rare, uid `MAG_ChargedLightning_ElectricSurface_Boots`, electrify water you stand in and gain Lightning
  Charges. Builds: STORM/TEMPEST with Create Water (Tempest) + **The Sparkswall** (lightning resistance ring, Arcane Tower
  basement). HOW: gilded chest in Minthara's area, Shattered Sanctum (X 339, Y 41).
- **Boots of Aid and Comfort** - uncommon, uid `MAG_Healer_TempHPOnHeal_Boots`, healed creatures gain temp HP. Builds: LIFE.
  HOW: sold by Grat the Trader, Goblin Camp (X -99, Y 424).
- **Disintegrating Night Walkers** - story boots, uid `S_UND_DuergarGaleItem`, immune to web/ice/grease-type surfaces, Misty Step
  1/SR. Builds: all (mobility). HOW: worn by Nere, Grymforge (kill him or let the gnomes/True Souls deal with him; he's hostile
  in his quest).
- Boots of Speed (rare, Click Heels dash; Thulla's thank-you gift for curing her, Ebonlake Grotto) - SG mobility alternative.

#### Amulet
- **Amulet of Restoration** - rare, uid `MAG_Healer_HPRestoration_Amulet`, Healing Word + Mass Healing Word 1/LR each.
  Builds: LIGHT/LIFE/SG ("best early cleric amulet" - Gamestegy). HOW: sold by Derryth Bonecloak, Ebonlake Grotto (X -55, Y -93).
- **Amulet of Misty Step** - uncommon, uid `UNI_GOB_DrowCommander_Amulet`, Misty Step 1/SR. Builds: all. HOW: gilded chest next to
  the bed in Gut's private chambers (Defiled Temple X 386, Y 8) OR sold by Omeluum - only ONE copy, whichever you reach first.
  WARNING: the Gut's-room chest is owned; opening it while goblins are friendly and watching counts as theft.
- **The Blast Pendant** - uncommon, uid `MAG_ChargedLightning_LightningBlast_Amulet`, discharge Lightning Charges into your next
  lightning spell. Builds: STORM (called Act 1 BiS for Storm/Tempest by Pro Game Guides). HOW: worn by Dhourn, a petrified drow
  west of the Selûnite Outpost, Underdark (X 121, Y -245).
- **Periapt of Wound Closure** - rare, uid `MAG_PHB_PeriaptofWoundClosure_Amulet`, auto-stabilise; healing on you is maximised.
  Builds: SG front-liner. HOW: sold by Lady Esther, Rosymorn Monastery Trail (X -43, Y -129). MISSABLE (Mountain Pass).
- Psychic Spark (uncommon, upgraded Magic Missile; Blurg) - STORM Magic-Missile-proc variant. Pearl of Power Amulet (restore a
  slot <= 3 1/LR; Omeluum) - any caster.

#### Ring 1 / Ring 2
- **Ring of Protection** - rare, uid `MAG_PHB_Ring_Of_Protection`, +1 AC and +1 saves. Builds: all. HOW: Mol's reward for
  "Steal the Sacred Idol" (Tiefling Hideout, Emerald Grove). Note: the quest itself is a theft from the druids (story choice;
  angers druids if caught).
- **Strange Conduit Ring** - uncommon, uid `MAG_Gish_PsychicDamageBonusWhileConcentrating_Ring`, +1d4 psychic on weapon attacks
  while concentrating. Builds: SG (BiS), LIGHT/TEMPEST melee turns. HOW: elegant chest, Inquisitor's Chamber, Crèche Y'llek
  (X 1360, Y -657). MISSABLE + same githyanki WARNING as the gloves.
- **The Whispering Promise** - uncommon, uid `UNI_MassHealRing`, creatures you heal get +1d4 attack rolls and saves for 2 turns
  (Bless without concentration; Mass Healing Word blesses everyone). Builds: LIFE (BiS), LIGHT/SG support. HOW: sold by Grat,
  Goblin Camp; also sold by Volo (Sacred Pool, and at camp in every act).
- **Ring of Absolute Force** - uncommon, uid `UNI_UND_KC_RingOfAbsolute`, Thunderwave 1/SR (+1 thunder only with Absolute's Brand).
  Builds: STORM/TEMPEST (thunder proc for Reverberation). HOW: carried by Elenna Thrinn, Grymforge. WARNING: Elenna is a
  non-hostile NPC - requires pickpocketing (theft) or killing her.
- **Crusher's Ring** - uncommon, uid `Quest_GOB_DrunkGoblin_Ring`, +movement speed. Builds: SG (mobility). HOW: worn by Crusher,
  Goblin Camp - slip it off his toe when he demands you kiss his feet, or loot after the goblin fight.
- **Ring of Salving** - uncommon, heals you more when you heal others. Builds: LIFE. HOW: Omeluum.
- The Sparkswall (lightning resistance; STORM Watersparkers combo; Arcane Tower basement gilded chest X 163 Y -432).

#### Consumables / permanent boosts (build-defining)
- **Auntie Ethel's Hair** - permanent +1 to a chosen ability (choose Wisdom for clerics, Charisma for STORM). HOW: reduce Ethel
  below ~20% HP in her Ancient Abode and accept her bargain. STORY CHOICE: you let Ethel go; a DC 20 Deception/Intimidation lets
  you also free Mayrina, otherwise Mayrina is lost.

---

### ACT 2

#### Main hand
- **Shar's Spear of Evening** - legendary +3 Spear (proficient via Civil Militia), uid `MAG_SHA_SharBlessing_Spear`. Shar's
  Darkness castable, blind immunity, Shar's Blessing (Advantage on saves while obscured, +1d6 dmg vs obscured creatures), Edge of
  Darkness weapon action. Builds: TRICK (BiS), SG, Shar-path LIGHT melee turns. HOW: STORY CHOICE - Shadowheart kills the Nightsong
  (Aylin) in the Shadowfell at the end of the Gauntlet of Shar (X -604, Y -1431). WARNING: locks the Selûne path (see §6).
- **Moonlight Glaive** - rare +2 Glaive (proficient via Civil Militia, two-handed), uid `MAG_Moonlight_Glaive`. +1d4 radiant per hit,
  permanent light aura, Moonlight Butterflies. WHY: radiant on every hit + self light = feeds Luminous gear, Coruscation and
  Callous Glow. Builds: LIGHT melee variant, SG (no shield). HOW: STORY CHOICE - reward from Aylin for freeing her ("Find the
  Nightsong"), Shadowfell. Only on the "spare the Nightsong" outcome.
- The Blood of Lathander stays the default caster main hand for LIGHT/LIFE (guides: "no better caster mace in Act 2").
- STORM: keep The Spellsparkler (Gamestegy keeps it through Act 2).

#### Off hand / shield
- **Ketheric's Shield** - rare, uid `MAG_Ketheric_Shield`. +1 spell save DC & spell attack (Arcane Enchantment +1), Advantage on Dex
  saves, Shield Bash. Builds: LIGHT, STORM, TEMPEST, CLE/SOR (DC stacking). HOW: carried by Ketheric Thorm - looted after the final
  fight in the Mind Flayer Colony (end of Act 2, X 861 Y -23). bg3.wiki notes an early pickpocket trick during the Moonrise rooftop
  fight (WARNING: theft).
- **Shield of Devotion** - very rare, uid `MAG_BG_OfDevotion_Shield`. +1 level-1 spell slot, Shield Bash, self-only Aid at level 3
  1/LR. Builds: LIGHT/LIFE/SG (extra HP + slot). HOW: sold by Talli near the Last Light Inn waypoint (X -31, Y 130). MISSABLE
  (Last Light vendors).
- **Sentinel Shield** - rare, uid `MAG_PHB_Sentinel_Shield`, +3 Initiative, Advantage on Perception. Builds: all (go-first).
  HOW: sold by Lann Tarv, Moonrise Towers main floor. MISSABLE (buy before the Moonrise assault).

#### Ranged
- **Darkfire Shortbow** - rare +2 Shortbow (simple), uid `MAG_BG_Darkfire_Shortbow`. Fire + cold resistance, Haste 1/LR.
  Builds: all clerics (pre-buff Haste). HOW: sold by Dammon, Last Light Inn (Act 2). MISSABLE (Last Light).
- **Ne'er Misser** - rare +1 Hand Crossbow (martial), uid `MAG_MagicMissile_HandCrossbow`, Magic Missile at lvl 3 1/SR.
  Builds: STORM (Tempest gives martial). HOW: sold by Roah Moonglow, Moonrise Towers. MISSABLE (Moonrise).

#### Head
- **Hat of Fire Acuity** - uncommon, uid `MAG_Fire_ArcaneAcuityOnFireDamage_Hat`. Dealing fire damage grants Arcane Acuity
  (stacking + spell DC/attack). Builds: LIGHT (Burning Hands, Scorching Ray, Fireball, Wall of Fire, Flame Strike - Gamestegy pick).
  HOW: carried by the Strange Ox at Dammon's smithy, Last Light Inn (Act 2) or near Rivington's requisitioned barn (Act 3).
  WARNING: the ox is a neutral creature (a disguised devil) - the hat comes from killing or pickpocketing it.
- **Fistbreaker Helm** - rare, uid `MAG_BarbMonk_Cloth_Hat_A_1_Late`, +1 spell save DC, +1 Initiative. Builds: LIGHT, STORM, CLE/SOR.
  HOW: sold by Lann Tarv, Moonrise Towers. MISSABLE.
- **Hat of Storm Scion's Power** - uncommon, uid `MAG_Thunder_ArcaneAcuityOnThunderDamage_Hat`, Arcane Acuity on thunder damage.
  Builds: STORM, TEMPEST (Thunderwave/Shatter/Destructive Wrath thunder). HOW: Araj Oblodra, Moonrise Towers (or Crimson Draughts,
  Act 3).
- **Dark Justiciar Helmet** - very rare (medium), uid `UNI_DarkJusticiar_Helmet`. +1 Con saves, +1 saves vs spells (Magical
  Durability), crits more likely while obscured. Builds: TRICK (BiS), SG. HOW: gilded chest behind the altar beyond the riddle door,
  Silent Library, Gauntlet of Shar (X -822, Y -753). Available on both Shar and Selûne paths.

#### Chest / armour
- **Dark Justiciar Half-Plate (Very Rare)** - Medium AC 17, uid `UNI_SHA_Shadowheart_JusticiarArmor_HalfPlate`. Advantage on Con
  saves, Advantage on Stealth when obscured, Shield of Faith 1/LR (Shar's Aegis) and damage reduction while Shield of Faith is on.
  Builds: LIGHT tank, SG (concentration), TRICK (BiS). HOW: STORY CHOICE - awarded to Shadowheart for killing the Nightsong.
- **Dark Justiciar Half-Plate (Rare)** - Medium AC 16, uid `MAG_DarkJusticiar_HalfPlate`, Advantage on Con saves, Shield of Faith
  1/LR. Builds: same, any path. HOW: on the ground by the Spear of Night altar beyond the riddle door, Gauntlet of Shar (X -818, Y -755).
- **Luminous Armour** stays BiS for radiant LIGHT (Gamestegy, Hack the Minotaur).
- **Flawed Helldusk Armour** - rare Heavy AC 18, uid `QUEST_HAV_InfernalReward_001`, -1 piercing, 1d4 fire retaliation.
  Builds: STORM, TEMPEST, LIFE. HOW: Dammon crafts it at Last Light when you give him Infernal Iron (first piece).
- **Robe of Exquisite Focus** - rare clothing, uid `MAG_OfArcanicAssault_Robe`, +1 spell save DC. Builds: STORM in robes.
  HOW: Araj Oblodra, Moonrise Towers (or Crimson Draughts, Act 3).
- **Yuan-Ti Scale Mail** - rare medium AC 15, uncapped Dex, +1 Initiative. Builds: Dex-leaning clerics. HOW: Talli, Last Light. MISSABLE.
- **Moon Devotion Robe** - very rare clothing, uid `MAG_Selunite_Isobel_Robe`. Advantage on Con saves, Produce Flame (Wis), Lunar
  Bulwark. Builds: SG. HOW: worn by Isobel. WARNING: Isobel is a friendly NPC - only by pickpocketing (theft) or killing her
  (or looting after she dies). Not recommended for a clean playthrough.

#### Cloak
- **Thunderskin Cloak** - uncommon, uid `MAG_Thunder_InflictDazeOnReverberatedCreature_Cloak`. Reverberating creatures that hurt you
  must pass DC 13 Con or be Dazed. Builds: STORM, TEMPEST, LIGHT with Belligerent Skies. HOW: Araj Oblodra, Moonrise Towers main
  floor (X -128, Y -193); Crimson Draughts in Act 3 if not bought.
- **Cloak of Protection** - uncommon, uid `MAG_PHB_CloakOfProtection_Cloak`, +1 AC, +1 saves. Builds: all. HOW: Talli, Last Light Inn.
  MISSABLE.
- **Vivacious Cloak** - uncommon, 8 temp HP when you cast a spell in melee range. Builds: SG. HOW: locked traveller's chest in the
  south-east corner, Grand Mausoleum (Reithwin).
- Shade-Slayer Cloak (very rare, lower crit threshold while hiding; Sticky Dondo, Guildhall Act 3) - TRICK only.

#### Gloves
- **Luminous Gloves** - uncommon, uid `MAG_Radiant_RadiatingOrb_Gloves`, your radiant damage applies Radiating Orb; +1 Str saves.
  Builds: LIGHT (Act 2 BiS swap from Belligerent Skies for the orb build), SG radiant, TEMPEST. HOW: potter's chest, Ruined
  Battlefield (X -52, Y 11).
- Gloves of Belligerent Skies remain BiS for STORM.
- **Dark Justiciar Gauntlets (Rare)** - uid `UNI_SHA_JusticiarArmor_Gloves`, +1d4 necrotic on weapon attacks, Beckoning Darkness,
  +1 Str saves. Builds: TRICK/SG melee. HOW: STORY CHOICE - Shar path reward (kill Nightsong). Uncommon version (no Beckoning
  Darkness) on boxes near Yurgir, Gauntlet of Shar (X -660, Y -760).

#### Boots
- **Evasive Shoes** - rare, uid `MAG_Evasive_Shoes`, +1 AC, +1 Acrobatics. Builds: all. HOW: sold by Mattis, Last Light Inn. MISSABLE.
- **Dark Justiciar Boots** - rare (medium), uid `UNI_SHA_DarkJusticiar_Boots`, +1 Dex saves, Shadow Teleportation 1/SR.
  Builds: TRICK, SG. HOW: STORY CHOICE - Shar path reward (kill Nightsong).
- Boots of Stormy Clamour remain BiS for STORM / LIGHT-Reverberation.

#### Amulet
- **Spineshudder Amulet** - uncommon, uid `MAG_Thunder_ReverberationOnRangeSpellDamage_Amulet`, ranged spell attacks that deal damage
  apply 2 turns of Reverberation. Builds: STORM, LIGHT (Guiding Bolt), TEMPEST. HOW: inside the Mimic in Isobel Thorm's bedroom,
  upper floor, Moonrise Towers (X -171, Y -195).
- **Spellcrux Amulet** - very rare, uid `MAG_Restoration_SpellSlotRestoration_Amulet`, restore ANY one spent spell slot 1/LR (e.g. a
  6th-level slot). Builds: all casters. HOW: worn by The Warden, Moonrise Towers Prison (Act 2, prison-break fight).
- **Amulet of the Harpers** - rare, uid `MAG_Harpers_HarpersAmulet`, Shield 1/LR, Advantage on Wis saves. Builds: LIGHT/STORM
  defence. HOW: Talli, Last Light Inn. MISSABLE.
- Surgeon's Subjugation Amulet (rare, paralyse a humanoid on crit 1/LR; worn by Malus Thorm, House of Healing) - Hack the Minotaur pick.

#### Ring 1 / Ring 2
- **Coruscation Ring** - uncommon, uid `MAG_Radiant_RadiatingOrb_Ring`. While YOU are illuminated, spell damage inflicts 2 turns of
  Radiating Orb (-1 attack per turn remaining, cap 10). Works with ANY damage type of spell. Builds: LIGHT (BiS), SG, TEMPEST,
  CLE/SOR. HOW: trapped heavy chest in the Last Light Inn cellar (X 44, Y -734).
- **Callous Glow Ring** - uncommon, uid `MAG_Radiant_DamageBonusOnIlluminatedTarget_Ring`. +2 radiant damage to illuminated targets,
  applied per damage instance (Magic Missile, Scorching Ray, Spirit Guardians ticks each get it). WHY: turns every hit into
  radiant -> triggers Luminous Armour/Gloves, Gloves of Belligerent Skies (Reverberation from ANY spell). Builds: LIGHT (BiS),
  STORM (BiS combo with Belligerent Skies), TEMPEST, SG. HOW: opulent chest in the vault room near Balthazar, Gauntlet of Shar
  (X -821, Y -752).
- **Ring of Spiteful Thunder** - uncommon, uid `MAG_Thunder_InflictDazeOnThunderDamage_Ring`, thunder damage can Daze Reverberating
  creatures. Builds: STORM, TEMPEST. HOW: sold by Roah Moonglow, Moonrise Towers (X -174, Y -179). MISSABLE.
- **Ring of Mental Inhibition** - uncommon, uid `MAG_Psychic_MentalOverload_Ring`, enemies failing a save vs your spells get Mental
  Fatigue (penalty to further saves). Builds: STORM, LIGHT, CLE/SOR (save-spell casters). HOW: locked chest just east of the Shadowed
  Battlefield waypoint (House in Deep Shadows, X 76 Y 40).
- **Ring of Twilight** - rare, + AC while obscured. Builds: TRICK. HOW: traveller's chest behind pots in a ruined tower, Ruined
  Battlefield (X -34, Y -12).
- Ring of Free Action (rare, immune Paralysed/Restrained, ignore difficult terrain; Araj Oblodra) - utility.

#### Other
- **Moonlantern** (story club, big light radius when equipped) - a light source option for the Coruscation/Callous setup.
  HOW: carried by Kar'niss (Ruined Battlefield / top of Moonrise). Freeing the pixie inside gives Pixie's Blessing.

---

### ACT 3

#### Main hand
- **Devotee's Mace** - legendary +3 Mace (main hand only), uid `MAG_Cleric_Devotees_Mace`. +1d8 radiant per hit, Healing Incense
  Aura. Builds: LIGHT (Cleric 10+), LIFE/TEMPEST/TRICK only if Cleric 10+. HOW: cast Divine Intervention -> "Arm Thy Servant"
  (Cleric level 10). STORY/BUILD CHOICE: Divine Intervention is ONE use per character for the whole game (even after respec) -
  you give up the other options (e.g. Sunder the Heretical, Exodus, Golden Hour). STORM (Tempest 2) cannot get it.
- **Selûne's Spear of Night** - legendary +3 Spear (proficient), uid `MAG_SHA_SeluneBlessing_Spear`. Moonbeam (lvl 3, 1/LR),
  Moonmote (light wisps: difficult terrain for enemies, ally dmg buff), Darkvision, Advantage on Wis saves and Perception.
  Builds: LIGHT (radiant Moonbeam + Moonmote light for Coruscation/Callous), SG, Selûne-path TRICK. HOW: STORY CHOICE - Shadowheart
  spares the Nightsong; Aylin hands it over at camp after Ketheric Thorm is defeated (end of Act 2 / start of Act 3).
  Shadowheart must have been taken into the Shadowfell.
- **Markoheshkir** - legendary +2 Quarterstaff, uid `MAG_TheChromatic_Staff`. +1 spell DC/attack, Arcane Battery (one free-slot
  spell 1/LR), tune to an element (Kereska's Favour) - lightning tuning grants Chain Lightning per guides. Builds: STORM (BiS),
  TEMPEST, CLE/SOR. HOW: inside a Globe of Invulnerability in Ramazith's Tower (Lorroakan's tower, reached via Sorcerous Sundries'
  portal, X 4970 Y 705): See Invisibility reveals the lever, then one DC 20 Arcana attempt per character (fail = trap).
- **Staff of Spell Power** - very rare +2 Quarterstaff, uid `MAG_OfSpellPower_Quarterstaff`, +1 spell DC/attack, Arcane Battery.
  Builds: STORM runner-up, any caster. HOW: Raphael's Vault, House of Hope (X -6486, Y 2939).
- **The Sacred Star** - very rare +2 Morningstar (MARTIAL), uid `MAG_RadiantLight_Morningstar`. +1d4 radiant, Radiating Orb on hit,
  may Turn undead, Dawnburst Strike. Builds: TEMPEST, STORM melee, LIGHT only with Weapon Master/martial dip (Hack the Minotaur calls
  it Light BiS - disagrees with proficiency reality). HOW: sold by Vicar Humbletoes, Stormshore Tabernacle (X 107, Y -22).
- The Blood of Lathander remains a strong LIGHT pick (light source + Sunbeam) if no Devotee's Mace.
- Hammer of the Just (rare +2 warhammer, +1d4 radiant, martial) - TEMPEST; "Offerings to Tyr" chest, Stormshore Tabernacle basement.

#### Off hand / shield
- **Viconia's Walking Fortress** - legendary shield, uid `MAG_TheBulwark_Shield`. Advantage on saves vs spells, spell attacks against
  you have Disadvantage, Force retaliation when hit (Rebuke of the Mighty). Builds: all shield users (LIGHT, STORM, TEMPEST, LIFE,
  SG). Widely called the best shield in the game. HOW: carried by Viconia DeVir, Cloister of Sombre Embrace (House of Grief) during
  "Daughter of Darkness" - defeat her in combat (she is hostile; talking her down with DC 20 checks means no shield).
- **Ketheric's Shield** - stays the runner-up (+1 DC).
- **Shield of the Undevout** - very rare, extra level-1 slot, enemies get Disadvantage on Frightened saves. HOW: That Which Guards
  (death knight), Murder Tribunal (Temple of Bhaal).
- Shield of Shielding (rare, Shield spell + Shield Bash; "Offerings to Helm" chest, Stormshore Tabernacle basement).

#### Ranged
- **Hellrider Longbow** - uncommon +1 Longbow (martial), uid `MAG_WYR_Hellrider_Longbow`. Large Initiative bonus, Advantage on
  Perception, Faerie Fire on hit chance. Builds: STORM/TEMPEST (proficient). HOW: sold by Ferg Drogher near the Requisitioned Barn,
  Rivington. STORY NOTE: Ferg refuses to sell anything while Shadowheart is nearby UNLESS she killed Aylin - on the Selûne path,
  leave her out of the party to shop.
- LIGHT (simple weapons only): keep Darkfire Shortbow.
- Fabricated Arbalest (very rare +2 heavy crossbow, Radiating Orb on Dazzling Ray/Illuminating Shot; martial; carried by Enver
  Gortash, Wyrm's Rock) - TEMPEST/STORM radiant-orb niche.

#### Head
- **Hood of the Weave** - very rare, uid `MAG_EndGameCaster_Hood_A`, +2 spell save DC and spell attack. Builds: LIGHT, STORM, TEMPEST,
  CLE/SOR (DC BiS). HOW: sold by Mystic Carrion, Philgrave's Mansion (Lower City). MISSABLE: buy before the Mystic Carrion fight
  (Gamestegy notes it is "in high demand" across party casters).
- **Helm of Balduran** - legendary (medium), uid `MAG_WYRM_OfBalduran_Helmet`. Regain HP every turn, stun immunity, no crits on you.
  Builds: SG, LIGHT tank, TEMPEST. HOW: stone altar next to Ansur, The Dragon's Sanctum (Wyrmway trials, X 636 Y -964), after the
  Ansur encounter (normally a boss fight).
- **Birthright** - very rare, uid `MAG_GleamingSorcery_Hat`, +2 Charisma (max 22). Builds: STORM (CHA caster). HOW: sold by
  Lorroakan's Projection / Rolan, Sorcerous Sundries ground floor.
- **Helldusk Helmet** - very rare, +2 saves vs spells, no crits, see in magical darkness (great with Shar's Darkness). Builds: TRICK, SG.
  HOW: Raphael's Vault, House of Hope (needs DC 10 Wis + DC 20 Arcana gem checks).

#### Chest / armour
- **Helldusk Armour** - legendary Heavy AC 21, **no proficiency needed**, uid `MAG_Infernal_Plate_Armor`. Fire resistance, -3 damage
  from all sources, Fly, fire retaliation. Builds: LIGHT (works despite no heavy prof), STORM, TEMPEST, LIFE, SG. HOW: carried by
  Raphael - defeat him in the House of Hope (hostile boss fight).
- **Luminous Armour** - several guides (Gamestegy, Hack the Minotaur) keep it as LIGHT BiS for the Radiating Orb engine;
  Deltia's/EIP lean to Helldusk/Dark Justiciar for defence. See §5.
- **Armour of Agility** - very rare medium AC 17, uncapped Dex, +2 all saves, uid `MAG_EndGame_HalfPlate`. Builds: LIGHT/SG with
  Dex. HOW: sold by Gloomy Fentonson, Stormshore Armoury (Lower City).
- **Armour of Persistence** - very rare heavy AC 20, -2 damage, permanent Resistance + Blade Ward, uid `MAG_EndGame_Plate_Armor`.
  Builds: STORM/TEMPEST/LIFE. HOW: Dammon, Forge of the Nine (Act 3).
- **Robe of the Weave** - very rare clothing, uid `MAG_EndGameCaster_Robe`, +1 DC/attack, +2 AC, heals on successful save vs spell.
  Builds: STORM in robes. HOW: Globe of Invulnerability, Ramazith's Tower (same puzzle as Markoheshkir).
- **Viconia's Priestess Robe** - rare clothing, Advantage on Stealth while obscured, Shield of Faith also gives +2 saves. Builds:
  TRICK. HOW: worn by Viconia (defeat her).

#### Cloak
- **Cloak of the Weave** - very rare, uid `MAG_EndGameCaster_Cape_A`, +1 DC/attack, Absorb Elements. Builds: STORM, LIGHT, CLE/SOR.
  HOW: Helsik's curated stock, Devil's Fee - unlocked by spotting several diabolic curios (DC 5 Perception) and one DC 15 Arcana,
  then remarking that a diabolist runs the shop.
- **Cloak of Displacement** - rare, uid `MAG_PHB_CloakOfDisplacement_Cloak`, attacks against you at Disadvantage until you take
  damage (resets each turn). Builds: SG, LIGHT tank, TEMPEST. HOW: Entharl Danthelon, Danthelon's Dancing Axe (Wyrm's Crossing).
- **Mantle of the Holy Warrior** - very rare, uid `MAG_Radiant_CrusaderMantle_Cloak`, Crusader's Mantle (lvl 3, 1/SR) - party weapon
  hits add 1d4 radiant. Builds: LIGHT/SG party support. HOW: Vicar Humbletoes, Stormshore Tabernacle.
- Thunderskin Cloak stays a STORM option.

#### Gloves
- **Helldusk Gloves** - very rare, uid `MAG_Infernal_Metal_Gloves`. +1 spell attack and spell save DC (Infernal Acuity), +1d6 fire on
  weapon attacks, +1 Str saves. Builds: LIGHT, STORM, TEMPEST. HOW: worn by Haarlep in the Boudoir, House of Hope (X -6478, Y 2993) -
  loot after defeating Haarlep (pickpocketing = theft).
- Luminous Gloves (LIGHT orb) / Gloves of Belligerent Skies (STORM) stay competitive - most guides keep them over Helldusk Gloves.
- **The Reviving Hands** - very rare, uid `MAG_OfRevivify_Gloves`, Revivify; healed allies get Blade Ward, revived get Death Ward.
  Builds: LIFE (BiS). HOW: Vicar Humbletoes, Stormshore Tabernacle.

#### Boots
- **Helldusk Boots** - very rare, uid `MAG_Infernal_Metal_Boots`. Ignore difficult terrain, reaction to auto-succeed a save, Hellcrawler
  teleport, can't be moved against your will (per guides). Builds: all, SG/LIGHT especially. HOW: locked gilded chest, top floor of
  Wyrm's Rock Fortress. WARNING: taking them AFTER Gortash's coronation makes Gortash and the Steel Watchers on that floor hostile.
- **Boots of Persistence** - very rare (medium), permanent Freedom of Movement + Longstrider, +1 Dex saves. HOW: Dammon, Forge of the Nine.

#### Amulet
- **Amulet of the Devout** - very rare, uid `MAG_OfTheDevout_Amulet`. +2 spell save DC and +1 Channel Divinity charge (Godswill).
  Builds: LIGHT (BiS - extra Radiance of the Dawn), STORM (BiS - extra Destructive Wrath via Tempest dip), TEMPEST, TRICK, LIFE.
  HOW: main Offering Chest in the basement of the Stormshore Tabernacle (secret hatch in the corner; X 796, Y 1159).
  bg3.wiki bug note: the extra charge actually recovers on short rest.
- **Amulet of Greater Health** - very rare, Constitution set to 23. Builds: SG, LIGHT/TEMPEST concentration. HOW: left-most pedestal
  in the Archive, House of Hope (X -6548, Y 2940).
- Spellcrux Amulet (Act 2) stays a strong runner-up for any caster.

#### Ring 1 / Ring 2
- **Coruscation Ring + Callous Glow Ring** remain LIGHT/radiant BiS (no Act 3 replacement).
- **Ring of Feywild Sparks** - very rare, +1 spell save DC (Wild Magic part irrelevant). Builds: STORM, LIGHT, CLE/SOR. HOW: carried
  by Auntie Ethel at The Blushing Mermaid (Lower City) - fight her.
- Ring of Spiteful Thunder (STORM), Strange Conduit Ring (SG), The Whispering Promise (LIFE) carry over.

#### Consumables / permanent boosts
- **Mirror of Loss** - Cloister of Sombre Embrace (X -474, Y -1650): +2 to one ability. STORY: a Shar-loyal Shadowheart gets the +2
  automatically (pick Wisdom); a Selûne-path Shadowheart is refused entirely.

---

## 3. Best + runner-up per slot per act

### LIGHT - Light Domain Cleric 12

| Slot | Act 1 best / runner-up | Act 2 best / runner-up | Act 3 best / runner-up |
|---|---|---|---|
| Main hand | The Blood of Lathander / Staff of Arcane Blessing | The Blood of Lathander / Moonlight Glaive (2H, spare-Nightsong) or Shar's Spear of Evening (Shar) | Devotee's Mace / Selûne's Spear of Night (Selûne) or The Blood of Lathander |
| Off hand | Adamantine Shield / Safeguard Shield | Ketheric's Shield / Shield of Devotion | Viconia's Walking Fortress / Ketheric's Shield |
| Ranged | Bow of Awareness / - | Darkfire Shortbow / Bow of Awareness | Darkfire Shortbow / Bow of Awareness |
| Head | Holy Lance Helm / Haste Helm | Hat of Fire Acuity / Fistbreaker Helm | Hood of the Weave / Helm of Balduran |
| Chest | Luminous Armour / Adamantine Scale Mail | Luminous Armour / Dark Justiciar Half-Plate | Luminous Armour (orb) or Helldusk Armour (defence) - sources split |
| Cloak | (none) | Cloak of Protection / Thunderskin Cloak | Cloak of the Weave / Cloak of Displacement |
| Gloves | Gloves of Belligerent Skies / Hellrider's Pride | Luminous Gloves / Gloves of Belligerent Skies | Luminous Gloves / Helldusk Gloves |
| Boots | Boots of Stormy Clamour / Boots of Striding | Boots of Stormy Clamour / Evasive Shoes | Helldusk Boots / Boots of Stormy Clamour |
| Amulet | Amulet of Restoration / Amulet of Misty Step | Spineshudder Amulet / Spellcrux Amulet | Amulet of the Devout / Amulet of Greater Health |
| Ring 1 | Ring of Protection / The Whispering Promise | Coruscation Ring / Ring of Protection | Coruscation Ring / Ring of Feywild Sparks |
| Ring 2 | Strange Conduit Ring / Crusher's Ring | Callous Glow Ring / Ring of Mental Inhibition | Callous Glow Ring / Ring of Protection |

### STORM - Storm Sorcerer 10 / Tempest Cleric 2

| Slot | Act 1 best / runner-up | Act 2 best / runner-up | Act 3 best / runner-up |
|---|---|---|---|
| Main hand | The Spellsparkler / Melf's First Staff | The Spellsparkler / Melf's First Staff | Markoheshkir / Staff of Spell Power |
| Off hand | Adamantine Shield / The Real Sparky Sparkswall | Ketheric's Shield / Sentinel Shield | Viconia's Walking Fortress / Ketheric's Shield |
| Ranged | Bow of Awareness / Spellthief | Ne'er Misser / Darkfire Shortbow | Hellrider Longbow / Darkfire Shortbow |
| Head | The Shadespell Circlet / The Lifebringer | Hat of Storm Scion's Power / Fistbreaker Helm | Hood of the Weave / Birthright |
| Chest | Adamantine Splint Armour / The Protecty Sparkswall | Flawed Helldusk Armour / Robe of Exquisite Focus | Helldusk Armour / Robe of the Weave |
| Cloak | (none) | Thunderskin Cloak / Cloak of Protection | Cloak of the Weave / Cloak of Displacement |
| Gloves | Gloves of Belligerent Skies / Bracers of Defence (robe only) | Gloves of Belligerent Skies / - | Gloves of Belligerent Skies / Helldusk Gloves |
| Boots | Boots of Stormy Clamour / The Watersparkers | Boots of Stormy Clamour / Evasive Shoes | Boots of Stormy Clamour / Helldusk Boots |
| Amulet | The Blast Pendant / Psychic Spark | Spineshudder Amulet / Spellcrux Amulet | Amulet of the Devout / Spellcrux Amulet |
| Ring 1 | Ring of Protection / Ring of Absolute Force | Callous Glow Ring / Ring of Spiteful Thunder | Callous Glow Ring / Ring of Spiteful Thunder |
| Ring 2 | The Sparkswall (with Watersparkers) / Ring of Absolute Force | Ring of Mental Inhibition / Coruscation Ring | Ring of Feywild Sparks / Ring of Mental Inhibition |

### Other builds - key differences only

| Build | Act 1 | Act 2 | Act 3 |
|---|---|---|---|
| TRICK (Shar) | Shadespell Circlet, Spidersilk Armour, Blood of Lathander | Shar's Spear of Evening, Dark Justiciar Half-Plate (VR) + Helmet + Gauntlets (Rare) + Boots, Ring of Twilight | Viconia's Priestess Robe, Helldusk Helmet (see in magic darkness), Shade-Slayer Cloak |
| LIFE | Wapira's Crown, Hellrider's Pride, Boots of Aid and Comfort, Amulet of Restoration, The Whispering Promise, Ring of Salving | Shield of Devotion, Cloak of Protection, Spellcrux Amulet | The Reviving Hands, Helldusk Armour, Amulet of the Devout |
| SG | Boots of Striding, Strange Conduit Ring, Holy Lance Helm, Luminous Armour | Vivacious Cloak, Dark Justiciar Half-Plate (Adv Con saves), Callous Glow Ring | Amulet of Greater Health, Helm of Balduran, Cloak of Displacement, Helldusk Boots |
| TEMPEST | as STORM but Blood of Lathander or Spellsparkler main hand, Luminous Armour/Adamantine Splint | as STORM + Luminous Gloves alt | The Sacred Star (martial OK) or Markoheshkir, Helldusk Armour, Amulet of the Devout |
| CLE/SOR | DC stack: Melf's First Staff, Protecty Sparkswall | Ketheric's Shield, Fistbreaker Helm, Robe of Exquisite Focus | Hood of the Weave, Cloak of the Weave, Helldusk Gloves, Amulet of the Devout, Ring of Feywild Sparks |

## 4. Synergy sets

### Act 1
1. **"Dawn Engine" (LIGHT)** - Main: The Blood of Lathander; Shield: Adamantine Shield; Head: Holy Lance Helm; Chest: Luminous
   Armour; Gloves: Gloves of Belligerent Skies; Boots: Boots of Stormy Clamour; Amulet: Amulet of Restoration; Rings: Ring of
   Protection + Strange Conduit Ring. WHY: every radiant tick (Sacred Flame, Guiding Bolt, Spirit Guardians Radiant at lvl 5,
   Holy Lance retaliation) sends a Luminous shockwave and stacks Reverberation; Lathander's blind aura + Stormy Clamour add more
   Reverberation; Prone on 5 stacks.
2. **"Sparkstruck Storm" (STORM)** - Main: The Spellsparkler; Shield: Adamantine Shield; Head: The Lifebringer; Chest: Adamantine Splint
   Armour (or The Protecty Sparkswall); Gloves: Gloves of Belligerent Skies; Boots: The Watersparkers; Amulet: The Blast Pendant;
   Rings: The Sparkswall + Ring of Absolute Force. WHY: every damaging spell gives 2 Lightning Charges, Watersparkers + Tempest
   Create Water electrify the field (Sparkswall makes you immune to your own water), Lifebringer turns charges into temp HP,
   Blast Pendant dumps them into the next lightning spell.
3. **"Bless-on-Heal" (LIFE)** - Head: Wapira's Crown; Gloves: Hellrider's Pride; Boots: Boots of Aid and Comfort; Amulet: Amulet of
   Restoration; Rings: The Whispering Promise + Ring of Salving; Main: Staff of Arcane Blessing or Blood of Lathander. WHY: one
   Mass Healing Word gives the party Bless-like +1d4, weapon-damage resistance and temp HP; works to the end of the game.
4. **"Guardian Walker" (SG)** - Boots: Boots of Striding; Ring: Strange Conduit Ring + Crusher's Ring; Chest: Luminous Armour or
   Spidersilk Armour (Adv Con); Head: Holy Lance Helm; Amulet: Periapt of Wound Closure; Shield: Safeguard Shield. WHY: start
   concentrating -> momentum; walk Spirit Guardians through packs; weapon swings add psychic while concentrating.

### Act 2
1. **"Radiating Orb Lockdown" (LIGHT - community BiS)** - Main: The Blood of Lathander (light source) or Moonlight Glaive; Shield:
   Ketheric's Shield; Head: Hat of Fire Acuity; Chest: Luminous Armour; Cloak: Cloak of Protection; Gloves: Luminous Gloves; Boots:
   Boots of Stormy Clamour; Amulet: Spineshudder Amulet; Rings: Coruscation Ring + Callous Glow Ring. WHY: Callous Glow makes every
   damage instance radiant (illuminated target), Coruscation adds 2 Orb turns per spell while you stand in light, Luminous Gloves +
   Armour spread more -> enemies at up to -10 to hit (reports of 20+ stacks from one Spirit Guardians/Flame Strike sweep).
2. **"Thunderhead" (STORM)** - Main: The Spellsparkler; Shield: Ketheric's Shield; Head: Hat of Storm Scion's Power; Chest: Flawed
   Helldusk Armour; Cloak: Thunderskin Cloak; Gloves: Gloves of Belligerent Skies; Boots: Boots of Stormy Clamour; Amulet:
   Spineshudder Amulet; Rings: Callous Glow Ring + Ring of Spiteful Thunder. WHY: Callous Glow's 2 radiant per instance procs
   Belligerent Skies on ANY spell (Magic Missile/Scorching Ray = many procs), Reverberation drops Con saves, Spiteful Thunder and
   Thunderskin Daze reverberating enemies; Storm Scion stacks Arcane Acuity on thunder.
3. **"Dark Justiciar" (TRICK / Shar path)** - Main: Shar's Spear of Evening; Head: Dark Justiciar Helmet; Chest: Dark Justiciar
   Half-Plate (Very Rare); Gloves: Dark Justiciar Gauntlets (Rare); Boots: Dark Justiciar Boots; Ring: Ring of Twilight +
   Callous Glow Ring (only if lit). WHY: fight inside Shar's Darkness - Advantage on saves, +1d6 vs obscured, higher crit chance,
   AC while obscured; Shadow Teleportation for repositioning.
4. **"DC Stack" (CLE/SOR, STORM robe variant)** - Melf's First Staff + Ketheric's Shield (+2), Fistbreaker Helm (+1), Robe of
   Exquisite Focus (+1), Ring of Mental Inhibition, Spellcrux Amulet. WHY: +4 spell save DC over base before Act 3 for Hold
   Person / Lightning Bolt / Command builds.

### Act 3
1. **"Lathander's Wrath" (LIGHT)** - Main: Devotee's Mace (or Blood of Lathander for its light); Shield: Viconia's Walking Fortress;
   Head: Hood of the Weave; Chest: Luminous Armour (orb) or Helldusk Armour (tank); Cloak: Cloak of the Weave or Mantle of the Holy
   Warrior; Gloves: Luminous Gloves; Boots: Helldusk Boots; Amulet: Amulet of the Devout; Rings: Coruscation + Callous Glow.
   WHY: +5 DC from gear (Hood 2, Cloak 1, Devout 2), extra Radiance of the Dawn charge, orb stacking intact, Devotee's Mace adds
   1d8 radiant per swing. Keep a light source (Light cantrip on self or the Blood) for Coruscation.
2. **"Kereska's Storm" (STORM)** - Main: Markoheshkir (lightning); Shield: Viconia's Walking Fortress; Head: Hood of the Weave (or
   Birthright); Chest: Helldusk Armour; Cloak: Cloak of the Weave; Gloves: Gloves of Belligerent Skies; Boots: Boots of Stormy
   Clamour; Amulet: Amulet of the Devout (+1 Destructive Wrath); Rings: Callous Glow Ring + Ring of Feywild Sparks. WHY: max-damage
   Chain Lightning/Lightning Bolt via Destructive Wrath on wet targets, Arcane Battery for a free big spell, DC stack for saves.
3. **"Unhittable Guardian" (SG / tank)** - Chest: Helldusk Armour; Head: Helm of Balduran; Cloak: Cloak of Displacement; Amulet:
   Amulet of Greater Health; Boots: Helldusk Boots; Shield: Viconia's Walking Fortress; Rings: Strange Conduit + Callous Glow;
   Gloves: Luminous Gloves. WHY: Con 23 + Adv-from-nothing concentration safety, regen, no crits, Disadvantage on attacks, -3 dmg.
4. **"Moon and Shadow" (path-flavoured)** - Selûne: Selûne's Spear of Night (Moonbeam + Moonmote light) + Moonlight Glaive swap,
   Coruscation/Callous (Moonmote counts as light per its description). Shar: Shar's Spear of Evening + Viconia's Priestess Robe +
   Helldusk Helmet (see through your own magical darkness) + Shade-Slayer Cloak.
5. **"Healbot Deluxe" (LIFE)** - The Reviving Hands, The Whispering Promise, Ring of Salving, Wapira's Crown (or Hood of the Weave),
   Boots of Aid and Comfort, Amulet of the Devout (extra Preserve Life), Helldusk Armour, Viconia's Walking Fortress.

## 5. Community consensus notes

- **Near-universal BiS for radiant Shadowheart:** The Blood of Lathander (Act 1), Luminous Armour + Luminous Gloves + Coruscation
  Ring + Callous Glow Ring (Act 2 core), Amulet of the Devout and Viconia's Walking Fortress (Act 3). Gloves of Belligerent Skies
  is called the best caster gloves for thunder/lightning/radiant in Acts 1-2.
- **Disagreement - chest piece in Act 3:** Gamestegy and Hack the Minotaur keep Luminous Armour to the end ("core engine");
  Deltia's Gaming, EIP and most generic lists put Helldusk Armour as cleric BiS (AC 21, -3 dmg, no proficiency needed). Recommend
  scoring both: Luminous for orb-focused LIGHT, Helldusk for defence/STORM.
- **Disagreement - martial items for Light Cleric:** Hack the Minotaur calls The Sacred Star / Fabricated Arbalest Light BiS and
  Gamestegy lists Defender Flail / Phalar Aluve, but a pure Light Cleric lacks martial proficiency. Only Tempest/War dips (or
  Weapon Master) fix that. LootAdvisor should down-rank them for LIGHT 12.
- **Act 2 shield:** Ketheric's Shield (+1 DC) is the consensus caster shield; Sentinel Shield is the "go first" alternative;
  Shield of Devotion is under-mentioned in guides but strong for slot-hungry clerics.
- **Head slot Act 2 for Light:** split between Hat of Fire Acuity (Gamestegy), Fistbreaker Helm (Hack the Minotaur, Gamestegy for
  Storm/Tempest) and Dark Justiciar Helmet (EIP). Hood of the Weave is the uncontested Act 3 caster helm.
- **Storm Sorc / Tempest:** consensus combo is Callous Glow Ring + Gloves of Belligerent Skies + Boots of Stormy Clamour + Spineshudder
  Amulet + Thunderskin Cloak/Ring of Spiteful Thunder ("Reverberation set"), then Markoheshkir in Act 3 for Chain Lightning. The
  Sparkstruck (Lightning Charges) set is called fun but niche; Blast Pendant is the Act 1 standout of it. Some guides run Storm
  10/Tempest 2 for heavy armour + Destructive Wrath, others Storm 6/Tempest 6 for Thunderbolt Strike and Create Water.
- **Life healer:** the Act 1 on-heal set (Whispering Promise, Hellrider's Pride, Boots of Aid and Comfort, Amulet of Restoration,
  Wapira's Crown) is reported to carry through Honour Mode; The Reviving Hands is the Act 3 upgrade.
- **Shar vs Selûne (gear impact):**
  - Shar (kill Nightsong): Shar's Spear of Evening, Dark Justiciar Half-Plate (Very Rare), Dark Justiciar Gauntlets (Rare), Dark
    Justiciar Boots; Mirror of Loss +2 automatic in Act 3; Ferg Drogher (Hellrider Longbow) will trade with her.
  - Selûne (spare Nightsong): Moonlight Glaive (Aylin's reward) and Selûne's Spear of Night (from Aylin at camp after Ketheric);
    Isobel survives (her Moon Devotion Robe only via theft/kill); Mirror of Loss refuses her; Ferg won't sell with her nearby.
  - Both paths: Dark Justiciar Half-Plate (Rare), Dark Justiciar Helmet, uncommon Gauntlets and Callous Glow Ring from the Gauntlet
    of Shar; Viconia's items require defeating Viconia in either path.
- Items I could NOT verify / do not exist under that name (do not match against game files): "Spellguard Shield" (Spellguard is the
  passive on Viconia's Walking Fortress), "Healing Pendant" (guides mean Amulet of Restoration), "Radiating Orb Gloves" (passive
  name on Luminous Gloves, not an item).

## Sources

- bg3.wiki item pages (raw data via the wiki API), e.g. https://bg3.wiki/wiki/The_Blood_of_Lathander ,
  https://bg3.wiki/wiki/Luminous_Armour , https://bg3.wiki/wiki/Gloves_of_Belligerent_Skies , https://bg3.wiki/wiki/Coruscation_Ring ,
  https://bg3.wiki/wiki/Callous_Glow_Ring , https://bg3.wiki/wiki/Amulet_of_the_Devout , https://bg3.wiki/wiki/Helldusk_Armour ,
  https://bg3.wiki/wiki/Viconia%27s_Walking_Fortress , https://bg3.wiki/wiki/Markoheshkir , https://bg3.wiki/wiki/Ketheric%27s_Shield ,
  https://bg3.wiki/wiki/Sel%C3%BBne%27s_Spear_of_Night , https://bg3.wiki/wiki/Shar%27s_Spear_of_Evening ,
  https://bg3.wiki/wiki/Dark_Justiciar_Half-Plate_(Very_Rare) , https://bg3.wiki/wiki/Hellrider_Longbow
- bg3.wiki set/mechanic pages: https://bg3.wiki/wiki/Luminous_set , https://bg3.wiki/wiki/Radiant_set , https://bg3.wiki/wiki/Thunder_set ,
  https://bg3.wiki/wiki/Sparkstruck_set , https://bg3.wiki/wiki/Radiating_Orb_(Condition) , https://bg3.wiki/wiki/Reverberation ,
  https://bg3.wiki/wiki/Lightning_Charges , https://bg3.wiki/wiki/Civil_Militia , https://bg3.wiki/wiki/Tempest_Domain ,
  https://bg3.wiki/wiki/Divine_Intervention , https://bg3.wiki/wiki/Mirror_of_Loss , https://bg3.wiki/wiki/Helsik ,
  https://bg3.wiki/wiki/Daughter_of_Darkness , https://bg3.wiki/wiki/Shadowheart , https://bg3.wiki/wiki/Category:Cloaks
- Gamestegy Light Domain Cleric: https://gamestegy.com/post/bg3/872/light-domain-cleric-build
- Gamestegy Blaster Tempest Cleric: https://gamestegy.com/post/bg3/1100/blaster-tempest-cleric-build
- Gamestegy Storm Sorcerer: https://gamestegy.com/post/bg3/882/best-storm-sorcerer-build
- EIP Light Domain Cleric: https://eip.gg/bg3/builds/light-domain-cleric/
- EIP Shadowheart (Cleric/Sorc): https://eip.gg/bg3/builds/shadowheart-5/
- Hack the Minotaur Light Cleric: https://hacktheminotaur.com/baldurs-gate-3/ultimate-bg3-light-cleric-build/
- AlcastHQ Shadowheart / radiant / lightning sets (page bodies truncated on fetch; titles + search snippets only):
  https://alcasthq.com/bg3-shadowheart-build-guide , https://alcasthq.com/bg3-radiant-item-sets-radiating-orb/ ,
  https://alcasthq.com/bg3-lightning-item-sets-lightning-charges/
- Pro Game Guides lightning charges items: https://progameguides.com/baldurs-gate/all-lighting-charges-items-in-bg3/
- Ludo.guide Storm Sorcerer (10 Storm / 2 Tempest): https://www.ludo.guide/guide/baldurs-gate-3/classes/sorcerer/best-storm-sorcerer-build-for-baldurs-gate-3-best-ra-499by0
- Deltia's Gaming (Gloves of Belligerent Skies access, Act 3 best items): https://deltiasgaming.com/how-to-get-gloves-of-belligerent-skies-in-baldurs-gate-3 , https://deltiasgaming.com/baldurs-gate-3-the-10-best-items-in-act-3
- GameSkinny Luminous armour set: https://www.gameskinny.com/tips/best-luminous-armor-bg3-build/
- Reddit r/BG3Builds threads (via search snippets; direct fetch blocked): https://www.reddit.com/r/BG3Builds/comments/1dgkj4j/ ,
  https://www.reddit.com/r/BG3Builds/comments/1c9y7rp/ , https://www.reddit.com/r/BG3Builds/comments/1aucvpd/
- Steam community discussions on radiating orb stacking: https://steamcommunity.com/app/1086940/discussions/0/4632611078380018089
- Gamers Decide top Shadowheart builds: https://gamersdecide.com/articles/baldurs-gate-3-best-shadowheart-builds
