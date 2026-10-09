# Lae'zel - LootAdvisor research (BG3 Patch 8 + hotfixes)

Race: Githyanki (locked). Default class Fighter. Starting kit: Githyanki Half Plate (common medium armour, AC 15 + DEX max 2),
Longsword, Shortbow, Githyanki Boots. Githyanki-only bonuses exist on: Silver Sword of the Astral Plane, Soulbreaker Greatsword,
Githyanki Greatsword (Psionic), Circlet of Psionic Revenge, Boots of Psionic Movement.

Primary data source: bg3.wiki item pages (coordinates are bg3.wiki X/Y). Locations/acts were cross-checked; where a summary
tool reported an obviously wrong act (e.g. "Crèche Y'llek = Act 3"), the correct act is used here: Crèche Y'llek, Grymforge,
Underdark, Rosymorn = Act 1; Moonrise Towers, Last Light Inn, Gauntlet of Shar, Shadowfell, House of Healing, Mind Flayer Colony = Act 2;
Lower City, Wyrm's Crossing, House of Hope, Murder Tribunal, Forge of the Nine, Steel Watch Foundry = Act 3.

---------------------------------------------------------------------------------------------------------------------

## 1. Builds covered

- **BM** - Battle Master Fighter 12 (BuildAdvisor main): GWF + GWM, greatsword/polearm, Trip/Precision/Riposte, STR/CON.
- **SORC** - Sorcadin (Vengeance Paladin 6 / Shadow Sorcerer 6) (BuildAdvisor): STR 2H + GWM, Quickened Hold Person -> paralysed = auto-crit smites, Booming Blade, Darkness + Devil's Sight from Shadow Magic.
- **EK** - Eldritch Knight Fighter 12: weapon + Booming Blade/Shield; wants Arcane Synergy / Arcane Acuity / Strange Conduit gear.
- **FP** - Fighter/Paladin GWM hybrids (e.g. Paladin 6-7 / Fighter 5-6 or Vengeance 5 / BM 7): smites + Action Surge; uses BM and SORC gear.
- **CH** - Champion Fighter crit build: stack crit-range reduction (Improved Critical 19 + items) and auto-crit items.
- **TANK** - sword-and-board Fighter (Protection / Defence style): Adamantine Shield / Viconia's Walking Fortress + crit-immune armour.

Note on BuildAdvisor data: Builds.lua lists "Gloves of Power" for the Sorcadin. bg3.wiki says Gloves of Power (Uncommon, Act 1, worn by
Za'krug at the Emerald Grove gate, X 208 Y 427) only gives +1 Sleight of Hand and a Bane-on-hit effect that **needs Brand of the Absolute**
and is off while disguised. It is weak for Lae'zel. Better Sorcadin gloves: Gauntlets of Hill Giant Strength / Legacy of the Masters / Helldusk Gloves (Act 3).

---------------------------------------------------------------------------------------------------------------------

## 2. Best items per Act per slot

Format: **Exact name** (rarity) - effect | why/builds | HOW TO GET | flags

### ACT 1 (Nautiloid, Wilderness, Underdark, Grymforge, Rosymorn / Crèche Y'llek, Mountain Pass)

#### Main hand (two-handed unless noted)
- **Everburn Blade** (Uncommon, greatsword, 2d6 + 1d4 fire) - earliest magic weapon, ignores non-magic slashing resistance. | BM, SORC, FP early. | Nautiloid (X -53 Y -391), carried by Commander Zhalk; normally needs Command: Drop (he usually resists) or killing him (very hard) before the escape. | MISSABLE (Prologue only).
- **Githyanki Greatsword (Psionic)** (Uncommon, +1 greatsword) - githyanki wielder gets +1d4 psychic per hit. | Lae'zel-specific; BM, SORC early. | Mountain Pass (Act 1), carried by Sarth Baretha (Kith'rak Voss's githyanki patrol); W'wargaz in the Crèche also drops a "Githyanki Greatsword" (variant not confirmed). | WARNING: the Voss patrol is neutral; getting it from Baretha means a fight (they turn hostile if provoked or if you fail Voss's interrogation).
- **Sword of Justice** (Uncommon, +1 greatsword) - grants Tyr's Protection (bonus action, short-rest recharge; a Shield of Faith style AC buff). | BM, SORC, FP; BuildAdvisor's Sorcadin gear line. | Risen Road Toll House (X 110 Y 560), carried by Anders. | WARNING: STORY CHOICE - loot it by siding with Karlach and killing Anders' group, or get it as the "Hunt the Devil" reward for killing Karlach (loses a companion).
- **Sussur Greatsword** (Rare, +1 greatsword) - on melee hit, target makes a DC 12 CON save or is Silenced for 2 turns (blocks casters). | BM, FP; anti-caster. | Quest "Finish the Masterwork Weapon", Blighted Village forge (X -477 Y -378): put Sussur Tree Bark and a plain Greatsword in the forge. | Only one masterwork weapon per playthrough - choose the greatsword.
- **Sorrow** (Rare, +1 glaive, reach) - Sorrowful Lash as a bonus-action attack each turn. | BM, SORC (when bonus action is free), FP; GWM/PAM-style reach. | Hidden Vault under the Emerald Grove (X 183 Y -82), on the wolf altar; solve the Enclave Library puzzle first. | -
- **Soulbreaker Greatsword** (Rare, +1 greatsword) - Soulbreaker action (psychic = proficiency bonus, may stun), +2 initiative, githyanki +1d4 psychic per hit. | Lae'zel-specific; BM best Act 1 greatsword on paper. | Crèche Y'llek Captain's Quarters (X 1408 Y -763), carried by Kith'rak Therezzyn. | WARNING: you have to kill the (neutral) Crèche commander, which turns the Crèche hostile. **Buy from A'jak'nir Jeera first.**
- **Unseen Menace** (Rare, +1 pike, reach, piercing) - wielder is invisible -> Advantage on attacks; crit on 19 while invisible; missing removes this for 2 rounds. | BM/GWM (Advantage cancels the -5), CH (crit range), SORC. Most-cited Act 1 polearm. | Bought from A'jak'nir Jeera, Crèche Y'llek trade post (X 1380 Y -798), about 190 gp. | Buy before anything turns the Crèche hostile.
- **Phalar Aluve** (Rare, +1 longsword, versatile 1d8/1d10, finesse) - Shriek/Sing auras. | SORC (Paladin gets an easy DC 10 route), TANK one-handed. | Underdark, stuck in a stone (X 116 Y -192): DC 15 STR, DC 15 Religion, Paladin DC 10 options, or spill blood on the stone. | -
- **The Blood of Lathander** (Legendary, +3 mace, one-handed) - light that blinds fiends/undead, Sunbeam (long rest), revives the wielder once per long rest. | TANK / one-handed SORC; not for GWM. | Rosymorn Monastery, Secret Chamber altar (bg3.wiki X 1068 Y -779), quest "Find the Blood of Lathander" (sun-puzzle). | MISSABLE quest item.
- **Silver Sword of the Astral Plane - early route** (Legendary, +3) - see Act 3. Act 1 option: disarm Kith'rak Voss at the Mountain Pass (Command: Drop, Heat Metal, fear) before he leaves. | WARNING: high difficulty; doing this **removes the Act 3 reward** (one copy per game).

#### Off hand (only for one-handed/TANK builds)
- **Adamantine Shield** (Rare, +2 AC) - attackers can't crit you; enemies that miss you in melee are Reeling; Shield Bash reaction can knock Prone. | TANK. | Forge at the Adamantine Forge, Grymforge (X -558 Y 230), from a Shield Mould + Mithral Ore. Only 2 Mithral Ore in the game (X -645 Y 255; X -558 Y 278), so 2 forged items total. The first lava-valve use spawns Grym (boss). | Competes with Adamantine Splint Armour for the ore.
- **Knife of the Undermountain King** (Very rare, +2 shortsword) - crit range -1, rerolls damage dice of 1-2, Advantage vs obscured targets. | CH dual-wield, EK; not for 2H builds. | A'jak'nir Jeera, Crèche Y'llek (X 1380 Y -798).

#### Ranged
- **Bow of Awareness** (Uncommon, +1 shortbow) - +1 initiative. | All (backup ranged). | Roah Moonglow, Shattered Sanctum entrance (X 272 Y -31), 65 gp.
- **Titanstring Bow** (Rare, +1 longbow) - adds STR modifier to damage. | BM/SORC/FP ranged backup (STR build). | Brem, Zhentarim Basement (X 295 Y -250), after "Find the Missing Shipment"; otherwise Lann Tarv, Moonrise Towers (Act 2).

#### Head
- **Haste Helm** (Rare) - Momentum at combat start (+1.5 m speed per remaining turn, 3 turns). | BM, SORC (reach the target turn 1). | Blighted Village (X 29 Y 405), Moss-Covered Chest. | -
- **Circlet of Psionic Revenge** (Rare) - when you pass a save, the source takes 1d4 psychic; githyanki get +1 INT/WIS/CHA saves. | Lae'zel-specific, all builds. | Crèche, carried by Inquisitor Ch'r'ai W'wargaz (X 1392 Y -752). The Inquisitor fight comes in Lae'zel's Crèche quest whether you obey Vlaakith or refuse.
- **Diadem of Arcane Synergy** (Rare) - applying a condition gives Arcane Synergy (2 turns: bonus spell damage). | EK, SORC (Trip/Hold Person/Booming Blade) - "best Acts 1-2 damage helm" per Gamestegy's Sorcadin guide. | Crèche, carried by Ardent Jhe'rezath, Inquisitor's Chamber (X 1365 Y -663).
- **Cap of Wrath** (Rare) - Wrath when you start a turn at 50% HP or less. | Niche BM. | Grymforge (X -617 Y 320), on Thudd.

#### Chest / armour
- **Adamantine Splint Armour** (Very rare, AC 18 heavy) - all damage -2, immune to crits, melee attackers become Reeling. | BM, SORC, FP, TANK. The Act 1 armour everyone agrees on. | Adamantine Forge, Grymforge (X -558 Y 230): Splint Mould (Grymforge ledge near the Ancient Forge waypoint, X -593 Y 311) + Mithral Ore, then kill Grym. | Uses 1 of the 2 Mithral Ore.
- **Githyanki Half Plate** (Common, medium) - starting armour; placeholder only.

#### Cloak
- No strong Act 1 cloak for melee (guides call Act 1 cloaks mostly cosmetic). Cloak of Protection becomes available in Act 2.

#### Gloves
- **Gloves of the Growling Underdog** (Uncommon) - Advantage on melee attacks while 2+ enemies are within 3 m; +1 STR saves. | BM/GWM, SORC, FP (Advantage cancels the GWM penalty). | Shattered Sanctum, Dror Ragzlin's treasure crates behind the locked gate (X 298 Y 66); or Rosymorn Monastery Trail crate after a Survival check (X -118 Y -134).
- **Gloves of Belligerent Skies** (Uncommon) - dealing thunder/lightning/radiant damage applies Reverberation (2 turns). | SORC/FP (Divine Smite = radiant; Booming Blade = thunder). | Crèche Inquisitor's Chamber, elegant chest by the south wall (X 1348 Y -677).

#### Boots
- **Disintegrating Night Walkers** (story item; Rare tier) - Misty Step once per short rest; immune to web/entangle/ensnare; no slipping on grease/ice. | All melee. | Grymforge (X -854 Y 780), worn by Nere. | WARNING: STORY CHOICE - you have to kill Nere (True Soul) during the Grymforge rescue; the duergar may turn on you.
- **Boots of Speed** (Rare) - Click Heels: bonus action doubles movement. | BM, SORC (gap-closer). | Ebonlake Grotto (X 82 Y -97), reward from Thulla for "Cure the Poisoned Gnome". | Stealing them instead is THEFT (optional).
- **Varsh Ko'kuu's Boots** (Uncommon) - acid resistance, ignore acid surfaces. | Niche. | Crèche hatchery, from Varsh Ko'kuu (egg quest).

#### Amulet
- **Amulet of Misty Step** (Uncommon) - Misty Step once per short rest. | All. | Gilded chest in Priestess Gut's room, Defiled Temple (X 386 Y 8), OR Omeluum (Ebonlake Grotto, X 112 Y -88) after his parasite quest. It only spawns at whichever place you reach first. | Taking it from Gut's chest while the goblins are friendly is THEFT.
- **Broodmother's Revenge** (Uncommon) - when healed, weapon deals +1d6 poison for 3 turns. | SORC (Gamestegy's Sorcadin pick in every act), FP with self-heals. | Kagha (Emerald Grove Inner Sanctum, X -461 Y -22), or Koll's goods table, High Hall (X 235 Y 44). | WARNING: Kagha route = kill or knock her out ("Investigate Kagha"); the Koll table = buy it or THEFT.
- **Periapt of Wound Closure** (Rare) - auto-stabilise when downed; heals on you roll max. | TANK, all (Honour mode). | Lady Esther, Rosymorn Monastery Trail (X -43 Y -129).
- **Amulet of Branding** (Rare) - Brand the Weak (vulnerability) once per long rest. | BM, SORC (boss nova). | A'jak'nir Jeera, Crèche (X 1380 Y -798).
- **Pearl of Power Amulet** (Uncommon) - restore spell slots up to level 3 once per long rest. | SORC/FP (more smites). | Omeluum, Ebonlake Grotto (X 144 Y 29), after "Help Omeluum Investigate the Parasite".

#### Rings
- **Ring of Protection** (Rare) - +1 AC, +1 all saves. | All. | Mol, Tiefling Hideout (X 84 Y 73), reward for "Steal the Sacred Idol". | WARNING: THEFT quest - stealing the Idol of Silvanus can turn the druids hostile if you are caught.
- **Caustic Band** (Uncommon) - +2 acid on every weapon attack. | BM (many attacks), CH. | Derryth Bonecloak, Myconid Colony / Ebonlake Grotto (X -55 Y -93).
- **Strange Conduit Ring** (Uncommon) - while concentrating, weapon attacks +1d4 psychic. | SORC (Hold Person / Hunter's Mark / Haste), EK, FP. | Crèche Inquisitor's Chamber, elegant chest (X 1360 Y -657).
- **Ring of Arcane Synergy** (Rare) - cantrip damage gives Arcane Synergy (2 turns). | EK, SORC (Booming Blade). | Crèche, worn by Gish Far'aag (X 1359 Y -831). | Combat drop.
- **Crusher's Ring** (Uncommon) - +3 m movement. | BM/SORC mobility. | Goblin Camp (X -70 Y 439), Crusher: take it from his toe in the foot-kiss dialogue, or kill him. | Can't be stolen normally.

#### Consumables (build-defining)
- **Elixir of Hill Giant Strength** (Uncommon) - STR 21 until a long rest. | SORC (STR 17 base), FP; BM until you hit 20 STR. | Auntie Ethel (restocks 3 per long rest), Derryth Bonecloak, Act 2 Talli/Mattis/Araj; one fixed copy at South Span Checkpoint.
- **Elixir of Bloodlust** (Uncommon) - each kill (once per turn) gives 5 temp HP and an extra Action. | BM (GWM cleanup). | Cyrel (Risen Road Toll House), Derryth, Stonemason Kith (Grymforge). Honour mode: the extra Action gives only one attack.

### ACT 2 (Shadow-Cursed Lands, Last Light Inn, Moonrise Towers, Gauntlet of Shar, Shadowfell, Mind Flayer Colony)

#### Main hand
- **Drakethroat Glaive** (Rare, +2 glaive, reach) - Draconic Elemental Weapon once per long rest (effectively +3 with elemental damage). | BM, SORC, FP. | Roah Moonglow, Moonrise Towers main floor (X -174 Y -179), 960 gp.
- **Halberd of Vigilance** (Very rare, +2 halberd, reach, +1d4 force) - +1 initiative, Advantage on reaction attacks (Riposte, opportunity attacks, Polearm Master). | BM (Riposte), FP/PAM. | Lann Tarv, Moonrise Towers main floor (X -164 Y -167).
- **Moonlight Glaive** (Rare, +2 glaive, +1d4 radiant) - Moonlight Butterflies (Advantage on that target); light radius. | BM, SORC (radiant with Gloves of Belligerent Skies). | Shadowfell (X -604 Y -1431), reward from Dame Aylin when you FREE the Nightsong. | WARNING: STORY CHOICE - mutually exclusive with Shar's Spear of Evening.
- **Shar's Spear of Evening** (Legendary, +3 spear, piercing) - +1d6 vs obscured targets, Advantage on saves while obscured, see through magical darkness, Shar's Darkness. | SORC Shadow (Darkness synergy); pairs with Bhaalist Armour (piercing). | Shadowfell (X -604 Y -1431); Shadowheart receives it from Shar if she KILLS the Nightsong while carrying the Spear of Night. | WARNING: STORY CHOICE - you need Shadowheart in the party and the Shar path (Aylin dies); this loses the Moonlight Glaive.
- **Harmonium Halberd** (Rare, +1 halberd) - STR +2 (max 23), INT/WIS -1. | BM/FP without elixirs. | Dammon, Last Light Inn (X -33 Y 164).
- **Soulbreaker / Githyanki greatswords / Sword of Justice** stay usable for greatsword roleplay.

#### Off hand
- **Adamantine Shield** (carried over); **Shield of Devotion** (Quartermaster Talli, Last Light Inn) for one-handed SORC per eip.gg. TANK only.

#### Ranged
- **Darkfire Shortbow** (Rare, +2 shortbow) - fire/cold resistance, Haste once per long rest. | All (free Haste on Lae'zel). | Dammon, Last Light Inn (X -33 Y 164), 480 gp.
- **Titanstring Bow** (Lann Tarv, Moonrise Towers, if Brem's stock wasn't unlocked in Act 1).

#### Head
- **Dark Justiciar Helmet** (Very rare, medium) - +1 saves vs spells; crit range -1 while obscured (stacks). | SORC Shadow (stand in your own Darkness), CH. | Gauntlet of Shar, Silent Library: gilded chest behind the altar past the riddle door (X -822 Y -753).
- **Flawed Helldusk Helmet** (Rare, medium) - +1 CON saves, +2 saves vs spells. | BM/TANK (keeps concentration and CON for SORC/EK). | Dammon crafts it from your 2nd Infernal Iron (Last Light Inn).
- **Haste Helm** (carried over).

#### Chest / armour
- **Dwarven Splintmail** (Rare, AC 19 heavy) - CON +2, -1 piercing damage, +1 STR saves/checks. | BM, SORC, FP. | Lann Tarv, Moonrise Towers (X -164 Y -167); restocks after long rests.
- **Adamantine Splint Armour** (carried over) - many players keep it until Helldusk because of crit immunity.
- **Flawed Helldusk Armour** (Rare, AC 18) - -1 piercing damage, fire aura on attackers. | Fallback. | Dammon, 1st Infernal Iron.
- **Reaper's Embrace** (Very rare, AC 19) - all damage -2, immune to forced movement, Howl of the Dead. | BM/TANK into Act 3. | Worn by Ketheric Thorm, Mind Flayer Colony finale (X 861 Y -23), end of Act 2.

#### Cloak
- **Cloak of Protection** (Uncommon) - +1 AC, +1 saves. | All. | Quartermaster Talli, Last Light Inn (X -31 Y 130), 200 gp.
- **Vivacious Cloak** (Uncommon) - 8 temp HP after casting a spell in melee. | SORC, EK. | Grand Mausoleum (X -257 Y -886), locked traveller's chest.
- **Fleshmelter Cloak** (Uncommon) - melee attackers take 1d4 acid. | TANK. | House of Healing morgue (X 29 Y -930), gilded chest.
- **Cloak of Elemental Absorption** (Uncommon) - halves the next elemental hit and adds that element to your next attack. | Utility. | Ketheric's chambers, Moonrise Towers (X -170 Y -171), opulent chest. Taking it may count as THEFT while Moonrise is friendly.

#### Gloves
- **Gloves of the Automaton** (Rare) - Circuitry Interface: Advantage on weapon attacks for 10 turns (once per short rest); healing spells can't target you while it's on. | BM/GWM, SORC. | Barcus Wroot, Last Light Inn (X -56 Y 133).
- **Flawed Helldusk Gloves** (Rare) - weapon attacks +1d4 fire; +1 STR saves. | BM (many attacks), FP. | Dammon, 3rd Infernal Iron.
- **Dark Justiciar Gauntlets (Rare)** - weapon attacks +1d4 necrotic; Beckoning Darkness curse. | SORC Shadow/Darkness. | Shadowfell; Shadowheart's reward for KILLING the Nightsong. | WARNING: STORY CHOICE (Shar path).

#### Boots
- **Evasive Shoes** (Rare) - +1 AC, +1 Acrobatics. | All. | Mattis, Last Light Inn (X -56 Y 141).
- **Disintegrating Night Walkers / Boots of Speed** (carried over) - still preferred by most builds.

#### Amulet
- **Spellcrux Amulet** (Very rare) - recover one spell slot of any level (bonus action, once per long rest). | SORC/FP (one more big smite). | Moonrise Towers Prison (X 569 Y -650), worn by the Warden (killed during the prison break).
- **Amulet of Misty Step / Periapt of Wound Closure / Broodmother's Revenge** (carried over).

#### Rings
- **Killer's Sweetheart** (Very rare) - after a kill, your next attack roll is a crit (once per long rest). | BM, CH, SORC (crit smite). | Gauntlet of Shar, Self-Same Trial: on the ground where the shadow copy by the brazier dies (X -833 Y -729). | MISSABLE (trial loot).
- **Risky Ring** (Rare) - Advantage on all attack rolls, Disadvantage on saves. | BM/GWM, SORC, CH - called "mandatory" by Gamestegy's Sorcadin guide. | Araj Oblodra, Moonrise Towers (X -128 Y -193); also sold by her in Act 3 at the Crimson Draughts, Lower City (X -92 Y -78).
- **Callous Glow Ring** (Uncommon) - +2 radiant vs illuminated targets. | SORC/FP smites, Moonlight Glaive light. | Gauntlet of Shar vault, opulent chest near Balthazar (X -821 Y -752).
- **Coruscation Ring** (Uncommon) - spell damage while illuminated applies Radiating Orb (which lights the target for Callous Glow). | SORC combo. | Last Light Inn cellar, trapped heavy chest in a secret area (X 44 Y -734).
- **Ring of Free Action** (Rare) - immune to paralysis/restrained, ignore difficult terrain. | TANK, Honour mode. | Araj Oblodra, Moonrise (Act 2) / Crimson Draughts (Act 3).
- **Strange Conduit Ring / Caustic Band** (carried over).

### ACT 3 (Rivington, Wyrm's Crossing, Lower City, House of Hope, Murder Tribunal, Wyrmway)

#### Main hand
- **Silver Sword of the Astral Plane** (Legendary, +3 greatsword) - 2d6+3 slashing; Soulbreaker action; **githyanki only**: +1d6 psychic, Advantage on INT/WIS/CHA saves, psychic resistance, can't be charmed. | Lae'zel BiS for roleplay and defence; BM, SORC, FP. | Show or give the **Orphic Hammer** to Kith'rak Voss at the Lower City Sewers meeting (after agreeing to meet him in the Undercity); alternative: DC 30 Deception if you turned down Raphael's contract; Act 1 disarm route (see Act 1). | WARNING: you need the Orphic Hammer, which comes from the House of Hope heist (stealing from Raphael). One per game.
- **Balduran's Giantslayer** (Legendary, +3 greatsword) - STR modifier counts twice for damage; Advantage vs Large+; Giant Form; Topple the Big Folk. | BM highest raw damage; SORC/FP. Most guides rank it #1. | Dragon's Sanctum, Wyrmway (X 633 Y -989), on Ansur's corpse; you can loot it without a fight if already in combat with something else nearby. | Boss kill (optional Wyrmway).
- **Sword of Chaos** (Very rare, +2 greatsword, +1d4 necrotic) - heal 1d6 on every damage instance. | BM sustain. | Murder Tribunal (X -1248 Y 503), carried by Sarevok Anchev. | Boss kill.
- **Halberd of Vigilance / Drakethroat Glaive** (carried over, for reach/Riposte builds).

#### Off hand
- **Viconia's Walking Fortress** (Legendary shield, +3 AC) - reflects projectiles, Warding Bond, melee hits on you deal force damage and knock Prone, spell defence. | TANK, one-handed SORC. | Cloister of Sombre Embrace (X -400 Y -1651), carried by Viconia DeVir ("Daughter of Darkness"). | Requires killing Viconia (Shadowheart quest).

#### Ranged
- **Gontr Mael** (Legendary, +3 longbow) - Celestial Haste, Guiding Bolt on hit, radiant frighten shot. | All (free Haste). | Steel Watch Foundry control centre (X -1952 Y 206), Steel Watcher Titan drop; it won't drop if the Titan dies of Atrophied.
- **Titanstring Bow** (STR damage; carried over).

#### Head
- **Helm of Balduran** (Legendary, medium) - +1 AC and saves; heal 2 HP per turn; can't be crit; stun immunity. | BM/TANK/FP BiS defence. | Dragon's Sanctum altar next to Ansur (X 636 Y -964).
- **Sarevok's Horned Helmet** (Very rare, medium) - crit range -1 (always), fear immunity, short darkvision. | CH BiS; SORC/BM crit fishing. | Carried by Sarevok, Murder Tribunal (X -1248 Y 503); also an Unholy Assassin reward (see WARNING under Bhaalist Armour). | Boss kill.
- **Helmet of Arcane Acuity** (Uncommon, light) - weapon damage gives Arcane Acuity (stacking bonus to spell DC and spell attack). | SORC BiS (pumps Hold Person DC), EK. | Mason's Guild secret basement (X 107 Y -758): trapdoor, then a locked + trapped gilded chest (DC 14 to unlock, DC 21 to disarm) or the Tower-Shaped Key on the Keyholed Herald.
- **Horns of the Berserker** (Very rare) - +2 attack vs damaged creatures; +2 necrotic while you're hurt; 1d4 self-damage if you dealt none this turn. | BM/GWM offence. | Entharl Danthelon, Danthelon's Dancing Axe, Wyrm's Crossing (X -10 Y 143).
- **Dark Justiciar Helmet** (carried over) - SORC Darkness / CH.

#### Chest / armour
- **Helldusk Armour** (Legendary, AC 21, no proficiency needed) - all damage -3, fire resistance, Fly once per long rest, burns casters whose saves you pass. | BM, SORC, FP, TANK BiS. | House of Hope (X -6477 Y 2884), worn by Raphael. | Boss kill (fight Raphael; that means not accepting his deal).
- **Armour of Persistence** (Very rare, AC 20) - permanent Blade Ward (B/P/S resistance) + Resistance, all damage -2. | TANK, BM - best you can buy. | Dammon, Forge of the Nine, Lower City (X 5 Y -7), 6400 gp.
- **Reaper's Embrace** (carried over), **Plate Armour +2** (Rare, AC 20; levelled magic-armour vendors at level 11+), **Blackguard's Plate** (Very rare, AC 19, Advantage on WIS saves; worn by "That Which Guards", Murder Tribunal X -1293 Y 503).
- **Bhaalist Armour** (Very rare, LIGHT armour 14 + DEX) - Aura of Murder: enemies within 3 m are vulnerable to piercing; +2 initiative. | Only for piercing weapons (Shar's Spear of Evening, Unseen Menace): Gamestegy's 2H Sorcadin BiS. Wrong for slashing greatswords. | Echo of Abazigal, Murder Tribunal (X -1263 Y 511). | WARNING: STORY CHOICE - becoming an Unholy Assassin (Impress the Murder Tribunal) means killing Minsc or Jaheira plus Valeria; an exploit exists.

#### Cloak
- **Cloak of Displacement** (Rare) - enemies have Disadvantage on attacks against you until you take damage (re-arms each turn). | All melee. | Entharl Danthelon, Wyrm's Crossing (X -10 Y 143).
- **Mantle of the Holy Warrior** (Very rare) - Crusader's Mantle (level 3) once per short rest: party +1d4 radiant per hit. | SORC/FP/BM party buff (radiant procs Callous Glow / Belligerent Skies). | Vicar Humbletoes, Stormshore Tabernacle (X 107 Y -22).
- **Shade-Slayer Cloak** (Very rare) - crit range -1 while hiding. | CH (niche for a heavy-armour Lae'zel). | Sticky Dondo, Guildhall (X -17 Y 755).
- **Cloak of Protection** (carried over).

#### Gloves
- **Gauntlets of Hill Giant Strength** (Very rare) - STR 23; +1 STR saves. | BM, SORC (frees the elixir slot), FP. | House of Hope Archive pedestal (X -6549 Y 2940): disarm the trap (DC 20 Sleight of Hand), swap in an equal-weight item, or pickpocket them from Helsik after her quest. | WARNING: THEFT (Raphael's house).
- **Legacy of the Masters** (Very rare, medium) - +2 weapon attack and damage, +1 STR saves. | BM/GWM (directly offsets the -5), any build already at 20+ STR. | Dammon, Forge of the Nine (X 5 Y -7).
- **Helldusk Gloves** (Very rare) - weapon attacks +1d6 fire; +1 spell attack/DC (bug: +1 to all attacks); Rays of Fire. | BM (6+ attacks per turn), SORC/EK. | House of Hope Boudoir (X -6478 Y 2993), worn by Haarlep. | Kill Haarlep (incubus; fight or trick).
- **Craterflesh Gloves** (Rare) - +1d6 force on crits (bugged to 2d6). | SORC/CH crit smite. | Echo of Abazigal. | WARNING: Unholy Assassin requirement (see Bhaalist Armour).

#### Boots
- **Helldusk Boots** (Very rare) - reaction: turn a failed save into a success; immune to forced movement; ignore difficult terrain; Hellcrawler teleport. | All (Honour mode BiS). | Wyrm's Rock Fortress top floor, locked Gilded Chest (X -32 Y 219). | WARNING: THEFT - taking them after Gortash's coronation makes Gortash and the Steel Watchers on that floor hostile; take them before.
- **Boots of Psionic Movement** (Very rare, medium) - githborn Fly once per long rest; next melee hit after Fly +1d4 psychic; +1 DEX saves. | Lae'zel-themed mobility. | Knights of the Shield Hideout (X -731 Y 553), worn by Ch'r'ai Har'rak. | Combat drop.
- **Boots of Persistence** (Very rare, medium) - permanent Freedom of Movement + Longstrider. | All. | Dammon, Forge of the Nine (X 5 Y -7), 1300 gp.

#### Amulet
- **Amulet of Greater Health** (Very rare) - CON 23, Advantage on CON saves. | All (HP; SORC/EK keep concentration). | House of Hope Archive, left-most pedestal (X -6548 Y 2940); same heist methods as the gauntlets. | WARNING: THEFT.
- **Amulet of the Devout** (Very rare) - +2 spell save DC, +1 Channel Divinity charge. | SORC (Hold Person DC, extra Vow of Enmity), FP. | Stormshore Tabernacle basement offering chest (X 796 Y 1159). | WARNING: looting the offering chests curses the looter (Castigated By Divinity) unless Jaheira takes it wearing Khalid's Gift.
- **Spellcrux Amulet** (carried over) - SORC slot battery.

#### Rings
- **Ring of Regeneration** (Very rare) - heal 1d4 at the start of each combat turn. | All. | Sorcerous Sundries: sold by Rolan (if Rolan and Lorroakan both live) or by Lorroakan's Projection (if Rolan is dead); carried by Rolan if Lorroakan dies. | Lost if both are dead or missing.
- **Band of the Mystic Scoundrel** (Rare) - after a weapon hit you can cast an illusion/enchantment spell as a bonus action. | SORC (bonus-action Hold Person without Quickened Spell = sorcery points saved), EK. | Jungle (X -1566 Y -1522), backpack.
- **Killer's Sweetheart / Risky Ring / Ring of Protection / Strange Conduit Ring** (carried over). The usual BM/CH endgame pair is Risky Ring + Killer's Sweetheart.

#### Consumables
- **Elixir of Viciousness** (Rare) - crit range -1 until a long rest (stacks). | CH, SORC crit smite, BM. | Level-6+ elixir/potion vendor tables; craft from Vitriol of Shadowroot Sac + Ashes.
- **Elixir of Bloodlust** - Act 3 vendors: Popper (Circus), Entharl Danthelon, Bonecloak's Apothecary.
- **Elixir of Cloud Giant Strength** (STR 27; Act 3, limited) - mentioned by eip.gg for BM/SORC burst; location not verified here.

---------------------------------------------------------------------------------------------------------------------

## 3. Best + runner-up per slot per act

### Act 1
| Slot | Best | Runner-up | Notes |
|---|---|---|---|
| Main hand (2H) | Unseen Menace (BM/CH/SORC) | Soulbreaker Greatsword (gith, WARNING kill Therezzyn) / Sorrow / Githyanki Greatsword (Psionic) | Sword of Justice for SORC (BuildAdvisor); Everburn Blade is missable |
| Off hand | Adamantine Shield (TANK) | Knife of the Undermountain King (CH/EK dual wield) | n/a for 2H |
| Ranged | Titanstring Bow | Bow of Awareness | |
| Head | Haste Helm (BM) / Diadem of Arcane Synergy (SORC/EK) | Circlet of Psionic Revenge (gith saves) | |
| Armour | Adamantine Splint Armour | Githyanki Half Plate | |
| Cloak | (none notable) | - | |
| Gloves | Gloves of the Growling Underdog | Gloves of Belligerent Skies (SORC) | |
| Boots | Disintegrating Night Walkers | Boots of Speed | |
| Amulet | Amulet of Misty Step | Broodmother's Revenge (SORC) / Periapt of Wound Closure | |
| Ring 1 | Ring of Protection (WARNING theft quest) | Caustic Band (BM) | |
| Ring 2 | Strange Conduit Ring (SORC/EK) / Caustic Band (BM) | Crusher's Ring / Ring of Arcane Synergy | |

### Act 2
| Slot | Best | Runner-up | Notes |
|---|---|---|---|
| Main hand | Halberd of Vigilance (BM Riposte) / Drakethroat Glaive | Moonlight Glaive or Shar's Spear of Evening (exclusive) | Soulbreaker for greatsword fans |
| Off hand | Adamantine Shield | Shield of Devotion | TANK only |
| Ranged | Darkfire Shortbow | Titanstring Bow | |
| Head | Dark Justiciar Helmet (SORC/CH) | Flawed Helldusk Helmet / Haste Helm | |
| Armour | Adamantine Splint (crit immunity) | Dwarven Splintmail (CON +2) | Reaper's Embrace at end of act |
| Cloak | Cloak of Protection | Vivacious Cloak (SORC) | |
| Gloves | Gloves of the Automaton | Flawed Helldusk Gloves | |
| Boots | Disintegrating Night Walkers | Evasive Shoes / Boots of Speed | |
| Amulet | Spellcrux Amulet (SORC) / Amulet of Misty Step (BM) | Periapt of Wound Closure | |
| Ring 1 | Risky Ring | Killer's Sweetheart | |
| Ring 2 | Killer's Sweetheart | Strange Conduit (SORC) / Ring of Protection | |

### Act 3
| Slot | Best | Runner-up | Notes |
|---|---|---|---|
| Main hand | Balduran's Giantslayer (raw damage) | Silver Sword of the Astral Plane (Lae'zel defence + psychic) | Sources disagree: see section 5 |
| Off hand | Viconia's Walking Fortress | Adamantine Shield | TANK |
| Ranged | Gontr Mael | Titanstring Bow | |
| Head | Helm of Balduran (BM/TANK) | Helmet of Arcane Acuity (SORC) / Sarevok's Horned Helmet (CH) | |
| Armour | Helldusk Armour | Armour of Persistence | |
| Cloak | Cloak of Displacement | Mantle of the Holy Warrior / Cloak of Protection | |
| Gloves | Gauntlets of Hill Giant Strength (if STR < 23) | Legacy of the Masters / Helldusk Gloves | |
| Boots | Helldusk Boots | Boots of Persistence / Boots of Speed | |
| Amulet | Amulet of Greater Health | Amulet of the Devout (SORC) | |
| Ring 1 | Risky Ring | Ring of Regeneration | |
| Ring 2 | Killer's Sweetheart | Band of the Mystic Scoundrel (SORC) / Ring of Protection | |

---------------------------------------------------------------------------------------------------------------------

## 4. Synergy sets

### Act 1
1. **"Invisible Pike" (BM / CH)** - Unseen Menace, Adamantine Splint Armour, Haste Helm, Gloves of the Growling Underdog, Disintegrating Night Walkers, Amulet of Misty Step, Ring of Protection + Caustic Band. Advantage from invisibility (and Underdog) cancels the GWM -5; crit on 19 while invisible; Caustic Band adds flat damage to every swing; the armour makes her crit-immune in the front line.
2. **"Gith Psionic Blade" (BM, Lae'zel flavour)** - Soulbreaker Greatsword (or Githyanki Greatsword (Psionic)), Circlet of Psionic Revenge, Adamantine Splint Armour, Gloves of the Growling Underdog, Boots of Speed, Amulet of Branding, Caustic Band + Ring of Protection. Githyanki psychic riders on every hit, +2 initiative, Brand the Weak for boss turns, extra mental saves. WARNING: the Soulbreaker means killing Therezzyn.
3. **"Concentration Smiter" (SORC / FP / EK)** - Sword of Justice or Sorrow, Diadem of Arcane Synergy, Adamantine Splint Armour, Gloves of Belligerent Skies, Disintegrating Night Walkers, Broodmother's Revenge (or Pearl of Power Amulet), Strange Conduit Ring + Ring of Arcane Synergy. Concentrating on Hold Person / Hunter's Mark gives +1d4 psychic per hit; Trip or Hold Person triggers Arcane Synergy; radiant smites apply Reverberation; Elixir of Hill Giant Strength covers STR.
4. **"Crit-Immune Wall" (TANK)** - Phalar Aluve or The Blood of Lathander, Adamantine Shield, Adamantine Splint Armour (uses both Mithral Ores), Periapt of Wound Closure, Ring of Protection, Disintegrating Night Walkers. Two separate crit immunities, attackers Reeling on hit and on miss, Lathander's self-revive.

### Act 2
1. **"Riposte Machine" (BM)** - Halberd of Vigilance, Dwarven Splintmail (or Adamantine Splint), Haste Helm, Cloak of Protection, Gloves of the Automaton, Disintegrating Night Walkers, Amulet of Misty Step, Risky Ring + Killer's Sweetheart. Reach + Advantage on reaction attacks (Riposte, opportunity attacks); Risky Ring and Automaton keep GWM accurate; Killer's Sweetheart chains a guaranteed crit after a kill.
2. **"Shadow Sorcadin" (SORC)** - Shar's Spear of Evening (WARNING Shar path) or Drakethroat Glaive, Dark Justiciar Helmet, Dark Justiciar Gauntlets (Rare) or Gloves of the Automaton, Adamantine Splint, Vivacious Cloak, Spellcrux Amulet, Risky Ring + Strange Conduit Ring. Inside Shadow Magic Darkness (Devil's Sight): crit 19 from the helmet, +1d6 vs obscured from the spear, Advantage from the Risky Ring, Hold Person concentration feeds Strange Conduit; Spellcrux returns one high smite slot.
3. **"Radiant Butterfly" (SORC / FP)** - Moonlight Glaive (WARNING free-Nightsong path), Gloves of Belligerent Skies, Callous Glow Ring + Coruscation Ring, Cloak of Protection, Evasive Shoes, Pearl of Power Amulet. The glaive lights targets so Callous Glow (+2 radiant) works; smite and glaive radiant apply Reverberation; Butterflies gives Advantage.
4. **"Flawed Helldusk" (BM)** - Flawed Helldusk Armour/Helmet/Gloves (3 Infernal Iron to Dammon), Darkfire Shortbow (Haste), Harmonium Halberd (STR without elixir), Killer's Sweetheart + Risky Ring. Easy to assemble; +1d4 fire per hit matters with 3 attacks.

### Act 3
1. **"Giantslayer Endgame" (BM, consensus BiS)** - Balduran's Giantslayer, Helm of Balduran, Helldusk Armour, Cloak of Displacement, Gauntlets of Hill Giant Strength (or Legacy of the Masters once STR is 20+ naturally plus Mirror of Loss / Everlasting Vigour), Helldusk Boots, Amulet of Greater Health, Risky Ring + Killer's Sweetheart. Doubled STR modifier with STR 23 means +12 per hit at up to 3-4 attacks per action; Helm + Helldusk give crit immunity, regen and flat reduction.
2. **"Silver Sword Mind-Guard" (BM / FP, Lae'zel)** - Silver Sword of the Astral Plane, Helm of Balduran, Helldusk Armour, Cloak of Displacement, Helldusk Gloves (+1d6 fire per hit), Boots of Psionic Movement or Helldusk Boots, Amulet of Greater Health, Ring of Regeneration + Risky Ring. Lower raw damage than Giantslayer but +1d6 psychic + 1d6 fire per hit, immune to charm, Advantage on mental saves (mind flayers, Orin, Gortash's dominate effects).
3. **"Hold-Person Crit Smiter" (SORC, BuildAdvisor plan)** - Balduran's Giantslayer or Silver Sword, Helmet of Arcane Acuity, Helldusk Armour, Mantle of the Holy Warrior, Gauntlets of Hill Giant Strength, Helldusk Boots, Amulet of the Devout (WARNING curse) or Amulet of Greater Health, Band of the Mystic Scoundrel + Strange Conduit Ring (or Risky Ring). Weapon hits stack Arcane Acuity, so Hold Person (bonus action via the Band, or Quickened) lands more often; paralysed = every melee hit crits, which doubles smite dice; Devout adds +2 DC and an extra Vow of Enmity.
4. **"Crit Fisher" (CH)** - Unseen Menace or Giantslayer, Sarevok's Horned Helmet, Helldusk Armour, Cloak of Displacement, Craterflesh Gloves (WARNING Unholy Assassin) or Legacy of the Masters, Helldusk Boots, Amulet of Greater Health, Killer's Sweetheart + Risky Ring, Elixir of Viciousness. Improved Critical (19) + helmet (18) + elixir (17) + Unseen Menace while invisible (16): roughly a 25-30% crit chance per swing, with Advantage.
5. **"Unbreakable" (TANK)** - Sword of Chaos (self-heal) or one-handed weapon + Viconia's Walking Fortress, Armour of Persistence (resists B/P/S) or Helldusk Armour, Helm of Balduran, Cloak of Displacement, Boots of Persistence, Amulet of Greater Health, Ring of Regeneration + Ring of Free Action.

---------------------------------------------------------------------------------------------------------------------

## 5. Community consensus notes

- **Widely called BiS (Act 3, any STR martial):** Balduran's Giantslayer, Helldusk Armour, Helm of Balduran, Gauntlets of Hill Giant Strength, Amulet of Greater Health, Helldusk Boots, Cloak of Displacement, Risky Ring, Killer's Sweetheart. eip.gg, Gamestegy and most Lae'zel guides list these, and BuildAdvisor's own gear line matches.
- **Giantslayer vs Silver Sword (sources disagree):** pure-damage lists (eip.gg, exputer, Gamestegy) put Giantslayer first (doubled STR modifier ~ +6, more with STR 23+). Lae'zel-specific guides (Prima, switchblade, gameranx) prefer the Silver Sword for her because the githyanki bonuses add +1d6 psychic plus strong mental-save defences. Simple LootAdvisor rule: Giantslayer for max DPS; Silver Sword when defence or roleplay matters, or if you don't do the Wyrmway. Both are +3 greatswords, so the gap is small.
- **Act 1 consensus:** Adamantine Splint Armour is universally recommended. For weapons, guides split between Unseen Menace (Advantage + crit 19, most optimizers), Sorrow (bonus-action attack) and the Everburn Blade (early but missable). Sword of Justice is usually listed for Paladin hybrids. One Lae'zel guide (switchblade) wrongly puts the Soulbreaker Greatsword on the Inquisitor; bg3.wiki says Kith'rak Therezzyn carries it.
- **Act 2 consensus:** Risky Ring is the most-cited GWM accessory; Gloves of the Automaton and Cloak of Protection are standard. Polearms (Drakethroat, Halberd of Vigilance, Moonlight Glaive) are preferred over greatswords in Act 2, because Act 2 has no standout greatsword except carrying the Act 1 githyanki ones.
- **Sorcadin specifics:** Gamestegy's Sorcadin uses DEX/Shadow Blade or 2H with Bhaalist Armour + Shar's Spear (piercing only). BuildAdvisor's version is STR 2H Hold Person crit-smite, so Helmet of Arcane Acuity, Band of the Mystic Scoundrel, Amulet of the Devout, Strange Conduit Ring and Spellcrux/Pearl of Power fit better than Bhaalist gear (Bhaalist Armour is light armour and only helps piercing).
- **Niche / situational:** Bhaalist Armour and Craterflesh Gloves (evil path), Shade-Slayer Cloak (needs hiding), Cap of Wrath and Horns of the Berserker (low-HP play), Fleshmelter/Cindermoth cloaks (tank thorns), Knife of the Undermountain King (dual wield only).
- **Patch 8 caveat:** none of the sources found document Patch 8 changes to these items. bg3.wiki pages are maintained for the current patch, so their stats were used. Patch 8 added the Arcane Archer Fighter subclass (not covered here).
- **Data-quality caveat:** many search results were SEO copies with errors (wrong acts, invented items). Only bg3.wiki was trusted for names and locations. The bg3.wiki fetch tool sometimes mislabelled the act (e.g. Crèche items as "Act 3", Moonrise vendors as "Act 3"); this file uses the corrected acts.

### Sources
- https://bg3.wiki/wiki/Lae'zel
- https://bg3.wiki/wiki/Crèche_Y'llek
- https://bg3.wiki/wiki/Silver_Sword_of_the_Astral_Plane
- https://bg3.wiki/wiki/Balduran's_Giantslayer
- https://bg3.wiki/wiki/Sword_of_Justice
- https://bg3.wiki/wiki/Everburn_Blade
- https://bg3.wiki/wiki/Sorrow
- https://bg3.wiki/wiki/Sussur_Greatsword
- https://bg3.wiki/wiki/Unseen_Menace
- https://bg3.wiki/wiki/Soulbreaker_Greatsword
- https://bg3.wiki/wiki/Githyanki_Greatsword_(Psionic)
- https://bg3.wiki/wiki/Sarth_Baretha
- https://bg3.wiki/wiki/Ch'r'ai_W'wargaz
- https://bg3.wiki/wiki/Phalar_Aluve
- https://bg3.wiki/wiki/The_Blood_of_Lathander
- https://bg3.wiki/wiki/Adamantine_Splint_Armour
- https://bg3.wiki/wiki/Adamantine_Shield
- https://bg3.wiki/wiki/Adamantine_Forge
- https://bg3.wiki/wiki/Splint_Mould
- https://bg3.wiki/wiki/Gloves_of_the_Growling_Underdog
- https://bg3.wiki/wiki/Gloves_of_Belligerent_Skies
- https://bg3.wiki/wiki/Gloves_of_Power
- https://bg3.wiki/wiki/Amulet_of_Misty_Step
- https://bg3.wiki/wiki/Amulet_of_Branding
- https://bg3.wiki/wiki/Broodmother's_Revenge
- https://bg3.wiki/wiki/Periapt_of_Wound_Closure
- https://bg3.wiki/wiki/Pearl_of_Power_Amulet
- https://bg3.wiki/wiki/Boots_of_Speed
- https://bg3.wiki/wiki/Disintegrating_Night_Walkers
- https://bg3.wiki/wiki/Varsh_Ko'kuu's_Boots
- https://bg3.wiki/wiki/Haste_Helm
- https://bg3.wiki/wiki/Circlet_of_Psionic_Revenge
- https://bg3.wiki/wiki/Diadem_of_Arcane_Synergy
- https://bg3.wiki/wiki/Cap_of_Wrath
- https://bg3.wiki/wiki/Ring_of_Protection
- https://bg3.wiki/wiki/Caustic_Band
- https://bg3.wiki/wiki/Crusher's_Ring
- https://bg3.wiki/wiki/Strange_Conduit_Ring
- https://bg3.wiki/wiki/Ring_of_Arcane_Synergy
- https://bg3.wiki/wiki/Knife_of_the_Undermountain_King
- https://bg3.wiki/wiki/Bow_of_Awareness
- https://bg3.wiki/wiki/Titanstring_Bow
- https://bg3.wiki/wiki/Githyanki_Half_Plate
- https://bg3.wiki/wiki/Drakethroat_Glaive
- https://bg3.wiki/wiki/Moonlight_Glaive
- https://bg3.wiki/wiki/Halberd_of_Vigilance
- https://bg3.wiki/wiki/Harmonium_Halberd
- https://bg3.wiki/wiki/Shar's_Spear_of_Evening
- https://bg3.wiki/wiki/Darkfire_Shortbow
- https://bg3.wiki/wiki/Flawed_Helldusk_Armour
- https://bg3.wiki/wiki/Flawed_Helldusk_Helmet
- https://bg3.wiki/wiki/Flawed_Helldusk_Gloves
- https://bg3.wiki/wiki/Infernal_Iron
- https://bg3.wiki/wiki/Dwarven_Splintmail
- https://bg3.wiki/wiki/Reaper's_Embrace
- https://bg3.wiki/wiki/Dark_Justiciar_Helmet
- https://bg3.wiki/wiki/Dark_Justiciar_Gauntlets_(Rare)
- https://bg3.wiki/wiki/Cloak_of_Protection
- https://bg3.wiki/wiki/Vivacious_Cloak
- https://bg3.wiki/wiki/Fleshmelter_Cloak
- https://bg3.wiki/wiki/Cloak_of_Elemental_Absorption
- https://bg3.wiki/wiki/Gloves_of_the_Automaton
- https://bg3.wiki/wiki/Evasive_Shoes
- https://bg3.wiki/wiki/Spellcrux_Amulet
- https://bg3.wiki/wiki/Killer's_Sweetheart
- https://bg3.wiki/wiki/Risky_Ring
- https://bg3.wiki/wiki/Callous_Glow_Ring
- https://bg3.wiki/wiki/Coruscation_Ring
- https://bg3.wiki/wiki/Ring_of_Free_Action
- https://bg3.wiki/wiki/Sword_of_Chaos
- https://bg3.wiki/wiki/Viconia's_Walking_Fortress
- https://bg3.wiki/wiki/Gontr_Mael
- https://bg3.wiki/wiki/Helm_of_Balduran
- https://bg3.wiki/wiki/Sarevok's_Horned_Helmet
- https://bg3.wiki/wiki/Helmet_of_Arcane_Acuity
- https://bg3.wiki/wiki/Horns_of_the_Berserker
- https://bg3.wiki/wiki/Bonespike_Helmet
- https://bg3.wiki/wiki/Helldusk_Armour
- https://bg3.wiki/wiki/Armour_of_Persistence
- https://bg3.wiki/wiki/Plate_Armour_+2
- https://bg3.wiki/wiki/Splint_Armour_+1
- https://bg3.wiki/wiki/Blackguard's_Plate
- https://bg3.wiki/wiki/Bhaalist_Armour
- https://bg3.wiki/wiki/Impress_the_Murder_Tribunal
- https://bg3.wiki/wiki/Cloak_of_Displacement
- https://bg3.wiki/wiki/Mantle_of_the_Holy_Warrior
- https://bg3.wiki/wiki/Shade-Slayer_Cloak
- https://bg3.wiki/wiki/Gauntlets_of_Hill_Giant_Strength
- https://bg3.wiki/wiki/Legacy_of_the_Masters
- https://bg3.wiki/wiki/Helldusk_Gloves
- https://bg3.wiki/wiki/Craterflesh_Gloves
- https://bg3.wiki/wiki/Helldusk_Boots
- https://bg3.wiki/wiki/Boots_of_Psionic_Movement
- https://bg3.wiki/wiki/Boots_of_Persistence
- https://bg3.wiki/wiki/Amulet_of_Greater_Health
- https://bg3.wiki/wiki/Amulet_of_the_Devout
- https://bg3.wiki/wiki/Ring_of_Regeneration
- https://bg3.wiki/wiki/Band_of_the_Mystic_Scoundrel
- https://bg3.wiki/wiki/Elixir_of_Hill_Giant_Strength
- https://bg3.wiki/wiki/Elixir_of_Viciousness
- https://bg3.wiki/wiki/Elixir_of_Bloodlust
- https://bg3.wiki/wiki/Critical_hit
- https://bg3.wiki/wiki/Greatswords , /Glaives , /Halberds , /Helmets , /Cloaks , /Boots , /Gloves , /Rings , /Amulets , /Heavy_armour
- https://eip.gg/bg3/builds/companion-laezel-2/
- https://eip.gg/bg3/builds/battle-master-fighter/
- https://eip.gg/bg3/builds/shadow-blade-vengeance-sorcadin-bard-party-code-v1/
- https://gamestegy.com/post/bg3/881/sorcadin-sorcerer-paladin-build
- https://www.switchbladegaming.com/baldurs-gate-3/githyanki-creche-guide/ (used with caution; contains errors)
- https://www.switchbladegaming.com/baldurs-gate-3/battle-master-fighter-build/
- https://primagames.com/gaming/best-laezel-build-in-baldurs-gate-3
- https://smartupworld.com/best-baldurs-gate-3-laezel-companion-build-guide/
- https://exputer.com/guides/bg3-best-greatswords/
- https://progameguides.com/baldurs-gate/best-items-in-act-1-baldurs-gate-3/
- https://www.gamerguides.com/baldurs-gate-3/guide/equipment/overview/best-armour-and-weapons-in-act-2-of-baldurs-gate-3
