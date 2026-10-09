# Astarion - LootAdvisor web research

Researched 2026-10-08 for Patch 8 (plus current hotfixes). Main sources are bg3.wiki for item data and locations, with
build guides for community consensus (URLs are at the end). Everything is summarised in my own words.
Item names are the in-game display names. Where bg3.wiki uses a disambiguation suffix, for example
"Dark Justiciar Half-Plate (Very Rare)", the in-game name has no suffix and the suffix is only a note.

Act boundaries used below: **Act 1** covers the Wilderness, Underdark, Grymforge, Mountain Pass, Rosymorn and the
Crèche Y'llek. **Act 2** covers the Shadow-Cursed Lands, Last Light Inn, Moonrise Towers and the Gauntlet of Shar.
**Act 3** covers Rivington, Wyrm's Crossing, the Lower City, the House of Hope, the Bhaal Temple and the Steel Watch
Foundry.
The WebFetch summariser mislabelled several acts. I corrected these from the map regions: the Crèche is Act 1, the
Blighted Village cellar is Act 1, the Adamantine Forge is Act 1, Moonrise and the Gauntlet are Act 2, the House in Deep
Shadows is Act 2, and the Rosymorn trail is Act 1.

Astarion facts that matter for gear: he is a High Elf, so he has no racial armour proficiency. As a pure Rogue he has
**light armour only**. Any level in **Ranger or Fighter** adds medium armour and shields. Several items need medium
armour proficiency: Helm of Balduran, Dark Justiciar Helmet, Sarevok's Horned Helmet, Holy Lance Helm, Legacy of the
Masters and Boots of Persistence. Only his multiclass builds can use them.
His vampire **Bite heals him**, which triggers "when healed" items such as Broodmother's Revenge.

---------------------------------------------------------------------------------------------------------------------
## 1. Builds covered

- **[GSA] Gloom Stalker 5 / Assassin 4 / Battle Master 3** (BuildAdvisor main, `gloomassassin`). Archer with
  Archery style, Sharpshooter and Alert. Dread Ambusher plus Assassinate gives a huge first round, and Action Surge
  adds more attacks. Wants a ranged weapon, initiative, attack bonus to offset Sharpshooter's -5, and crit riders.
- **[GSA7] Gloom Stalker 5 / Assassin 7**. The classic "Gloom Assassin" variant: more Sneak Attack dice and Expertise,
  but no Action Surge. Uses the same gear as [GSA].
- **[THX] Gloom Stalker 5 / Thief 4(+) / Fighter 3 (or Rogue Thief + Ranger) with dual hand crossbows**. The Fast Hands
  bonus action becomes an off-hand shot. Wants one-handed crossbows, flat per-hit damage riders and initiative.
- **[TM] Thief melee: Rogue 12 or Rogue 7 / Fighter 5 (Thief + Champion or Battle Master)**. Dual-wields finesse
  weapons. Wants crit-range reduction, piercing vulnerability (Bhaalist aura) and per-hit riders. With no Fighter or
  Ranger levels it is limited to light armour.
- **[CRIT] Assassin/Gloom crit stack**. Any of the above, geared to lower the crit threshold and add on-crit riders
  (Dead Shot, Sarevok's helm, Shade-Slayer Cloak, Craterflesh, Killer's Sweetheart, Surgeon's Subjugation).

Two items in the BuildAdvisor `gloomassassin` gear line (Builds.lua) do not fit the build:
- **Bracers of Defence** only give AC when **no armour** is worn. That is useless for an armoured archer.
- **Ring of Absolute Force** is a Thunderwave ring with a thunder rider. It does nothing for bow attacks.

I suggest Gloves of Archery or Legacy of the Masters instead of the bracers, and Killer's Sweetheart or Strange Conduit
Ring instead of the ring.

---------------------------------------------------------------------------------------------------------------------
## 2. Best items per act and slot (details)

Format: **Name** (rarity): effect. *Why / builds.* **Get:** source. Flags: `WARNING:` (theft, killing a
neutral NPC, or a story choice) and `MISSABLE`.

### ACT 1

#### Ranged
- **Titanstring Bow** (Rare, longbow +1, 1d8+1). Adds your **Strength modifier** (minimum +1) to damage, on top of
  Dexterity. This also applies to special arrows and Sneak Attack. Weapon actions: Brace, Hamstring Shot and Pushing
  Attack. *The best Act 1 bow and arguably the best bow overall when Strength is boosted: Elixir of Hill Giant
  Strength sets Str 21 (+5), Elixir of Cloud Giant Strength Str 27 (+8), Gauntlets of Hill Giant Strength Str 23 (+6).
  [GSA][GSA7].* **Get:** Brem, Zhentarim Basement under Waukeen's Rest (X:295 Y:-250). It is special stock, unlocked by
  finishing "Find the Missing Shipment" for Zarys (deliver the chest). Fallback: Lann Tarv, Moonrise Towers, Act 2
  (X:-164 Y:-167), who only sells it if Brem's special stock was **not** unlocked.
  The Strength bonus does not appear on the tooltip or character sheet.
  `WARNING:` opening the strongbox and taking the Iron Flask turns the Zhentarim hostile and loses the special stock.
- **Harold** (Rare, heavy crossbow +1, 1d10+1). Ranged damage can **Bane** the target (Charisma save, 2 turns).
  *A strong Act 1 alternative for the Bane/debuff angle. Rangers and Fighters have martial proficiency. [GSA][GSA7].*
  **Get:** reward from Zarys, Zhentarim Basement (X:277 Y:-247), for delivering the chest in "Find the Missing
  Shipment". `MISSABLE`: lost if you make Rugan's fake-loss deal without killing Rugan and Olly before entering the
  hideout.
- **The Joltshooter** (Rare, longbow, 1d8). Each damaging hit gives 2 Lightning Charges. *A decent early longbow.
  [GSA].* **Get:** one of three reward choices from Counsellor Florrick after rescuing her from the burning Waukeen's
  Rest ("Rescue the Grand Duke"). `MISSABLE` (you pick one reward).
- **Bow of Awareness** (Uncommon, shortbow +1). +1 initiative. *A cheap initiative piece. [GSA][GSA7].* **Get:** Roah
  Moonglow, Shattered Sanctum, Goblin Camp (X:272 Y:-31), 65 gp. Buy it before you raid the camp.
- **Hunting Shortbow** (Uncommon, shortbow +1). Advantage against Monstrosities and a free Hunter's Mark once per long
  rest. *Good before Ranger 2, or for a pure Rogue. [GSA][TM backup bow].* **Get:** Dammon, The Hollow, Emerald Grove
  (X:177 Y:562).
- **Bow of the Banshee** (Rare, shortbow +1). On hit it can Frighten (DC 12 Wisdom), and you get +1d4 to attack and
  damage against Frightened targets. *[GSA][GSA7].* **Get:** Corsair Greymon on the raft to Grymforge, or his shop at
  Grymforge (X:-120 Y:-95). `MISSABLE`: if Greymon is pushed off through dialogue his loot is lost. Shove him in
  combat instead and loot his body at the southern pier of the Decrepit Village.
- **Spellthief** (Uncommon, longbow). Regains a level 1 spell slot on a crit. *Niche: Hunter's Mark slots for
  Gloom.* **Get:** Arron, The Hollow (X:205 Y:516).
- **Firestoker** (Uncommon, hand crossbow). +1d4 against Burning targets. *The only notable Act 1 hand crossbow
  [THX].* **Get:** Grymforge dormitory, opulent chest with the hellsboars (X:-574 Y:382).

#### Main hand / off hand (melee)
- **Knife of the Undermountain King** (Very rare, shortsword +2). Melee crits on 19, damage dice of 1-2 are rerolled,
  and advantage against obscured targets. *The best melee weapon of Act 1 and a consensus pick for melee Astarion.
  [TM][CRIT]; the melee slot for [GSA].* **Get:** sold by A'jak'nir Jeera, Crèche Y'llek (X:1380 Y:-798), late Act 1.
- **Sussur Dagger** (Rare, dagger +1). Melee hits can Silence (DC 12 Constitution). *Good off-hand against casters.
  [TM].* **Get:** reward for "Finish the Masterwork Weapon" at the Blighted Village forge (X:-477 Y:-378). Combine a
  plain Dagger with Sussur Tree Bark at the forge.
- **Shortsword of First Blood** (Uncommon). +1d8 piercing against targets at full HP. *Fits Assassin openers.
  [TM].* **Get:** corpse of an executed deep gnome at the Decrepit Village entrance from the Myconid side, Underdark
  (X:73 Y:-187).
- **Speedy Reply** (Uncommon, scimitar). Hits give Momentum. *Mobility for melee. [TM].* **Get:** dead caravan agent,
  Risen Road gnoll cave (X:25 Y:603).
- **Club of Hill Giant Strength** (Uncommon, club). Sets Str 19 while held. *A Titanstring enabler: guides put it in
  the **melee off-hand** while shooting the Titanstring Bow, for +4 damage per arrow. This is community-reported and
  bg3.wiki does not confirm the off-set interaction, so verify in game. [GSA].* **Get:** break the Stool of Hill Giant
  Strength in the Arcane Tower, Underdark (X:-26 Y:-272).

#### Head
- **Haste Helm** (Rare). Momentum for 3 turns at the start of combat (+1.5 m movement per remaining turn). *A
  positioning helmet. [all].* **Get:** Moss-Covered Chest, Blighted Village (X:29 Y:405).
- **Shadow of Menzoberranzan** (Rare, needs light armour proficiency). "Shrouded in Shadow" makes you Invisible once
  per short rest. *Lets you re-hide or set up advantage. [GSA][TM].* **Get:** on the ground next to Xargrim's corpse,
  Ebonlake Grotto (X:52 Y:-70), after "Defeat the Duergar Intruders" opens the secret area.
- **Holy Lance Helm** (Uncommon, **needs medium armour**). Attackers who miss you take 1d4 radiant (DC 14 Dexterity).
  *Defensive filler. [GSA][THX].* **Get:** painted chest, Rosymorn Monastery top level (X:120 Y:35).

#### Chest / armour
- **The Graceful Cloth** (Rare, clothing, AC 10+Dex). +2 Dexterity (max 20), advantage on Dexterity checks, +1
  Dexterity saves. *Takes Astarion's 17 Dex to 19, but the AC is low. Does not stack with Gloves of Dexterity.
  [GSA][THX].* **Get:** Lady Esther, Rosymorn Monastery Trail (X:-43 Y:-129), 800 gp.
- **Spidersilk Armour** (Rare, light, 12+Dex). Advantage on Constitution saves, +1 Stealth. *The best Act 1 light
  armour for a stealth Rogue. [TM][GSA7][all].* **Get:** worn by Minthara, Shattered Sanctum. `WARNING:` you must kill
  her (raid the goblin leaders, which is the "save the Grove" path) or **pickpocket** her (theft). If you side with
  the goblins, she joins as an ally instead.
- **Adamantine Scale Mail** (Very rare, medium, 16+Dex max 2). Incoming damage -1 and immunity to crits, but
  **disadvantage on Stealth**. *Only for a tanky non-stealth setup, not ideal for Gloom/Assassin.* **Get:** forge it at
  the Adamantine Forge, Grymforge (X:-558 Y:230) from a Scale Mail Mould and Mithral Ore.
- Patch 8 note: **Drow Studded Leather Armour** (Underdark, Festering Cove cache) is flagged **unobtainable** on
  bg3.wiki for Patch 8, although older guides still recommend it. Do not recommend it.

#### Cloak
- No strong generic Act 1 cloak.
- **The Deathstalker Mantle** (Rare). Once per turn, killing an enemy makes you Invisible for 2 turns. *Great for
  chaining Assassin/Gloom opening kills. [GSA][GSA7][TM].* **Get:** Sceleritas Fel gives it to the **Dark Urge** at camp
  in Act 1, and it can then be handed to Astarion. `WARNING`/`MISSABLE`: it only exists in a **Dark Urge campaign**.
  The user's "The White Urge" campaign is one.

#### Gloves
- **Gloves of Archery** (Uncommon). Bow proficiency and **+2 damage on ranged weapon attacks**. *The consensus Act 1-2
  archer gloves, and still good later. [GSA][GSA7][THX].* **Get:** Grat the Trader, Goblin Camp (X:-99 Y:424), 60 gp.
  `MISSABLE`: buy before raiding the camp.
- **Gloves of Dexterity** (Very rare). Sets Dex 18 and +1 attack rolls. *More useful for the +1 attack than the Dex;
  good with Sharpshooter. [all].* **Get:** A'jak'nir Jeera, Crèche Y'llek (X:1380 Y:-798).
- **Gloves of Power** (Uncommon). +1 Sleight of Hand. Weapon hits, ranged included, can Bane the target (-1d4 to its
  attacks and saves). Only works if the wearer has the **Brand of the Absolute**. *[GSA][THX].* **Get:** dropped by
  Za'krug in front of the Druid Grove gate (X:208 Y:427).
  `WARNING`/story: the brand comes from Priestess Gut's branding in the goblin camp.
- **Gloves of Thievery** (Uncommon). Advantage on Sleight of Hand. *Utility only (lockpicking, pickpocketing).*
  **Get:** Brem, Zhentarim Basement, after the shipment quest.

#### Boots
- **Disintegrating Night Walkers** (story item). Misty Step as a bonus action once per short rest; immune to webs,
  entangle and ensnare; no slipping on grease or ice. *BiS-tier for the whole game for archers: free repositioning to
  break line of sight and re-hide. [all].* **Get:** worn by Nere, Grymforge (X:-854 Y:780).
  `WARNING:` Nere has to die. He is not hostile when you free him, so killing him is a story choice in the True Soul
  Nere quest.
- **Boots of Speed** (Rare). "Click Heels" bonus action for extra speed. *Mobility. [TM][THX].* **Get:** Thulla's
  reward for "Cure the Poisoned Gnome", Ebonlake Grotto (X:82 Y:-97).
  `WARNING:` they can also be **stolen** from Thulla.

#### Amulet
- **Broodmother's Revenge** (Uncommon). Whenever you are healed, your weapon deals +1d6 poison for 3 turns. bg3.wiki
  says 1d6; eip.gg says 1d4. *Astarion's **Bite** heals him, which makes this a signature Astarion synergy.
  [all].* **Get:** carried by Kagha, Inner Sanctum, Emerald Grove (X:-461 Y:-22). You can knock her out non-lethally
  and later barter it from her. Alternative: Koll's table in the High Hall, Act 3 (X:235 Y:44).
  `WARNING:` taking it from Kagha means fighting or killing her (she is neutral). Koll's table is owned stock.
- **Amulet of Misty Step** (Uncommon). Misty Step once per short rest. *Mobility, and it stacks with the Night
  Walkers. [all].* **Get:** a gilded chest in Priestess Gut's chambers, Defiled Temple (X:386 Y:8), **or** from Omeluum
  after "Help Omeluum Investigate the Parasite" (X:112 Y:-88). `MISSABLE`: only one copy exists, at whichever place
  you reach first.
- **Periapt of Wound Closure** (Rare). Auto-stabilises when downed, and all healing rolls maximum. *Doubles the value
  of Bite and potions; a survivability pick. [all].* **Get:** Lady Esther, Rosymorn Monastery Trail (X:-43 Y:-129).
- **Amulet of Branding** (Rare). "Brand the Weak" bonus action once per long rest: the target becomes Vulnerable to
  piercing (or slashing/bludgeoning) for 3 turns **or until it takes damage**. *An opener: pierce-brand, then volley
  with a multi-hit action. [CRIT][GSA].* **Get:** carried by A'jak'nir Jeera, Crèche Y'llek.
  `WARNING:` you must kill Jeera, a neutral githyanki trader (and fight the Crèche).

#### Rings
- **Strange Conduit Ring** (Uncommon). While you concentrate, weapon attacks (ranged included) deal +1d4 psychic.
  *Synergy with Ranger **Hunter's Mark** concentration. [GSA][GSA7][THX].* **Get:** elegant chest, Inquisitor's Chamber,
  Crèche Y'llek (X:1360 Y:-657).
- **Caustic Band** (Uncommon). Weapon attacks deal +2 acid. *A flat rider that works best with many attacks.
  [THX][TM][GSA].* **Get:** Derryth Bonecloak, Myconid Colony / Ebonlake Grotto (X:-55 Y:-93).
- **Fetish of Callarduran Smoothhands** (Rare). Invisibility once per long rest. *Stealth reset. [all].* **Get:** a dead
  deep gnome the duergar are dumping in the lake, Grymforge (X:-610 Y:408). Kill the duergar, pass checks, or help them
  and loot it. `MISSABLE`.
- **Smuggler's Ring** (Uncommon). +2 Stealth, +2 Sleight of Hand, -1 Charisma. *Stealth-opener support. [all].*
  **Get:** skeleton in a bush, Risen Road lower river path near the broken bridge (X:58 Y:516).
- **Ring of Protection** (Rare). +1 AC and +1 saves. **Get:** Mol's reward for "Steal the Sacred Idol" (Tiefling
  Hideout, X:84 Y:73). `WARNING:` the quest is a **theft** from the druids.
- **Crusher's Ring** (Uncommon). +3 m movement. **Get:** Crusher, Goblin Camp (X:-70 Y:439). Slip it off his toe in the
  "kiss my feet" dialogue, or kill him. `WARNING:` killing him while you are allied with the goblins is a story choice.

#### Consumables (build-defining only)
- **Elixir of Hill Giant Strength** sets Str 21 until long rest: +5 damage per arrow with the Titanstring Bow. Sold by
  Auntie Ethel (3 restock per long rest), Derryth and others, or brew it from a Hill Giant Finger.
- **Elixir of Cloud Giant Strength** sets Str 27: **+8 per arrow** with Titanstring. From level 6, Blurg and Derryth
  (Myconid Colony) sell Cloud Giant Fingers, so you can brew it in Act 1. Later, many vendors from level 9.
- **Elixir of Bloodlust**: once per turn, a kill gives 5 temp HP and an extra action. Cyrel (Risen Road Toll House),
  Derryth, Stonemason Kith, and others.

### ACT 2

#### Ranged
- **Darkfire Shortbow** (Rare, shortbow +2). Resistance to fire and cold, and casts **Haste** once per long rest.
  *Self-Haste means one more attack; the top Act 2 pick for [GSA][GSA7].* **Get:** Dammon, Last Light Inn (X:-33
  Y:164). `WARNING:` Dammon is only there if the tiefling refugees survived Act 1. If you sided with the goblins, he is
  gone.
- **Least Expected** (Rare, shortbow +2). +1d4 to ranged attack rolls while obscured, plus Blinding Shot. *Gloom
  fights from darkness; the bonus offsets Sharpshooter's -5. [GSA][GSA7].* **Get:** gilded chest beyond the locked
  puzzle door, Gauntlet of Shar (X:-730 Y:-800).
- **Hellfire Hand Crossbow** (Very rare, hand crossbow +2). Can inflict Burning when you hit while Hiding or
  Invisible. Also Scorching Ray Shot (level 3, once per short rest), Piercing Shot and Mobile Shot. *The best hand
  crossbow [THX].* **Get:** Yurgir, Gauntlet of Shar (X:-653 Y:-764). Fight him, talk him into killing himself
  (Insight 14, Persuasion 16/21/21), or kill Lyrthindor first so he renegotiates. Astarion disapproves if Yurgir is
  spared.
- **Ne'er Misser** (Rare, hand crossbow +1, force damage). Magic Missile at level 3 once per short rest. *The off-hand
  crossbow for [THX].* **Get:** Roah Moonglow, Moonrise Towers main floor (X:-174 Y:-179). `MISSABLE`: buy before
  assaulting Moonrise.
- **Titanstring Bow** carries on. Lann Tarv (Moonrise) sells it if Brem's special stock was not unlocked.

#### Main hand / off hand
- Keep **Knife of the Undermountain King**.
- **Render of Mind and Body** (Uncommon, shortsword +1): +1d8 psychic when attacking with advantage. *[TM] off-hand.*
  Lann Tarv, Moonrise.
- **The Baneful** (Rare) only works when bound (Eldritch Knight or Pact weapon), so it is **not** for Astarion.

#### Head
- **Circlet of Hunting** (Very rare). +1d4 to attack rolls against creatures **you** marked with Hunter's Mark,
  Faerie Fire, Guiding Bolt or True Strike. *An accuracy patch for Sharpshooter on a Hunter's Mark Gloom.
  [GSA][GSA7].* **Get:** Araj Oblodra, Moonrise Towers (X:-128 Y:-193). If missed, she sells it at Crimson Draughts in
  the Lower City, Act 3.
- **Dark Justiciar Helmet** (Very rare, **needs medium armour**). Crit threshold -1 while you are obscured (stacks),
  +1 saves against spells, +1 Constitution saves. *Gloom fights from darkness. [CRIT][GSA][GSA7].* **Get:** gilded chest
  behind the altar past the riddle door, Silent Library, Gauntlet of Shar (X:-822 Y:-753).
- **Marksmanship Hat** (Uncommon). +1 ranged and thrown attack rolls. *Cheap accuracy. Only applies to a **main-hand**
  hand crossbow, not the off-hand. [GSA].* **Get:** Roah Moonglow, Moonrise Towers. `MISSABLE`: buy before the
  assault.

#### Chest / armour
- **Yuan-Ti Scale Mail** (Rare, medium, **15 + full Dex**, no stealth disadvantage, +1 initiative). *The consensus
  Act 2 armour for multiclass Astarion. [GSA][GSA7][THX][TM with Fighter].* **Get:** Quartermaster Talli, Last Light
  Inn (X:-31 Y:130), 640 gp. `MISSABLE`: Talli dies if Isobel is kidnapped. Bug: the full-Dex property breaks with the
  Medium Armour Master or Magic Initiate: Cleric feats.
- **Sharpened Snare Cuirass** (Very rare, medium, 14 + full Dex, no stealth disadvantage). Enemies have disadvantage
  on saves against your Restrain effects, which works with **Ensnaring Strike**, a spell the BuildAdvisor plan takes
  at Ranger 2. *A runner-up for [GSA].* **Get:** Roah Moonglow, Moonrise Towers (X:-174 Y:-179), 830 gp.
- **Penumbral Armour** (Rare, light, 12+Dex). +3 Stealth while obscured. *Pure-Rogue stealth option [TM].*
  **Get:** locked opulent chest in the abandoned house by the river east of Last Light Inn (X:33 Y:145).
- **Dark Justiciar Half-Plate** (Very rare, medium 17+Dex max 2). Shield of Faith with damage reduction and reflect.
  `WARNING:` it is only given to Shadowheart for killing the Nightsong (she stays a Sharran). That is a big story
  choice, and it is not an Astarion-first item.

#### Cloak
- **Cloak of Protection** (Uncommon). +1 AC and +1 saves. *Filler. [all].* **Get:** Quartermaster Talli, Last Light
  Inn. Same missable condition as above.
- **Cloak of Cunning Brume** (Uncommon). Disengaging leaves a 2 m fog cloud. *Pure-Rogue hit-and-run [TM].* **Get:**
  Mattis, Last Light Inn (X:-56 Y:141).

#### Gloves
- Keep **Gloves of Archery** (ranged) or **Gloves of Dexterity**.
- **Dark Justiciar Gauntlets** (Rare). Weapon attacks deal +1d4 necrotic, plus a Beckoning Darkness curse.
  `WARNING:` only from the Shadowheart Nightsong choice described above.

#### Boots
- Keep **Disintegrating Night Walkers**.
- **Evasive Shoes** (Rare). +1 AC, +1 Acrobatics. *Runner-up. [all].* **Get:** Mattis, Last Light Inn (X:-56 Y:141).

#### Amulet
- Keep Act 1 picks: Broodmother's Revenge, Periapt of Wound Closure, Amulet of Misty Step.

#### Rings
- **Killer's Sweetheart** (Very rare). After a kill, your next attack roll is a **guaranteed crit**; it refreshes on
  long rest. *A cornerstone of the Assassin opener: kill one target, then auto-crit the next. [GSA][GSA7][CRIT][TM].*
  **Get:** on the ground where the shadow copy appears by the brazier in the Self-Same Trial, Gauntlet of Shar
  (X:-833 Y:-729).
- **Shadow-Cloaked Ring** (Uncommon). +1d4 weapon damage against lightly or heavily obscured creatures. *Darkness
  fights. [GSA][THX][TM].* **Get:** Shadow Mastiff Alpha, cursed camp north of the ruined pottery, Ruined Battlefield
  (X:-49 Y:36). Destroy the everburning torches to make it appear. `MISSABLE`.
- **Risky Ring** (Rare). Advantage on all attack rolls, disadvantage on saves. *Permanent advantage covers Sneak
  Attack and Sharpshooter accuracy. Risky but widely used. [all].* **Get:** Araj Oblodra, Moonrise Towers, or Crimson
  Draughts in Act 3.
- **Ring of Shadows** (Uncommon). Pass Without Trace once per long rest. *Party-wide surprise setup. [all].* **Get:**
  Oliver's reward for playing both rounds of hide and seek, House in Deep Shadows (X:76 Y:37). Knocking him out or
  pickpocketing him also works. `WARNING:` pickpocketing is theft. `MISSABLE`.
- **Callous Glow Ring** (Uncommon). +2 radiant against illuminated targets. *Strong with Gontr Mael's light, or in
  lit fights. [THX].* **Get:** opaque chest in the vault room near Balthazar, Gauntlet of Shar (X:-821 Y:-752).
- **Ring of Free Action** (Rare). Immune to paralysis and restraint, ignores difficult terrain. Araj Oblodra.

### ACT 3

#### Ranged
- **Gontr Mael** (Legendary, longbow +3). On hit it can apply Guiding Bolt (lasts only until the end of your turn).
  Also Celestial Haste (once per long rest) and Bolt of Celestial Light. Sheds light. *The consensus endgame bow:
  self-Haste plus advantage on your follow-up shots. [GSA][GSA7].* **Get:** dropped by the Steel Watcher Titan,
  Control Centre, Steel Watch Foundry (X:-1952 Y:206). `MISSABLE`: it does **not** drop if the Titan dies from the
  Atrophied condition.
- **The Dead Shot** (Very rare, longbow +2). Crit threshold -1 (stacks, and per bg3.wiki applies to all attacks) and
  **double proficiency** on its ranged attacks unless you have disadvantage. *The best accuracy and crit bow; it
  offsets Sharpshooter. [CRIT][GSA][GSA7].* **Get:** Fytz the Firecracker, Stormshore Armoury, Lower City (X:-36 Y:-83),
  770 gp.
- **Titanstring Bow** with Gauntlets of Hill Giant Strength (+6) or the Cloud Giant elixir (+8). *Often out-damages
  Gontr Mael on many-attack turns. Sources disagree on which is BiS (see section 5).*
- **Hellrider Longbow** (Uncommon, +1). **+3 initiative**, advantage on Perception, and can apply Faerie Fire once per
  turn. *The initiative and advantage pick. [GSA].* **Get:** Ferg Drogher by the Requisitioned Barn, Rivington (X:43
  Y:-101). He will not trade if Shadowheart is near, unless she killed the Nightsong.
- **Vicious Shortbow** (Rare, +2). +7 damage on crits (the Dolor Amarus passive, which applies to all weapon attacks
  and stacks). *[CRIT].* **Get:** Echo of Abazigal, Murder Tribunal. `WARNING:` see Echo below.
- Hand crossbows: no new Act 3 standouts. [THX] keeps the **Hellfire Hand Crossbow** and **Ne'er Misser**, or uses a
  generic Hand Crossbow +2.

#### Main hand / off hand (melee)
- **Crimson Mischief** (Legendary, shortsword +2). Main hand: +1d4 against targets at or below half HP and **+7
  piercing when attacking with advantage**. Off hand: adds your ability modifier to damage. *Consensus BiS main hand
  for [TM].* **Get:** Orin, Bhaal Temple (X:61 Y:1004), "Get Orin's Netherstone".
- **Bloodthirst** (Legendary, dagger +2). Main hand: crit -1. Off hand: +1 AC and **Exploit Weakness** (the target
  gains vulnerability to piercing). True Strike as a bonus action, and a True Strike riposte. *Consensus BiS off-hand
  for [TM][CRIT].* **Get:** Orin, Bhaal Temple. Her item splits into Bloodthirst and Orin's Netherstone.
- **Rhapsody** (Very rare, dagger +1). +1 attack, damage and DC per enemy killed (max +3). Can Bleed on hits while
  hidden or invisible. *[TM].* **Get:** Cazador Szarr, Cazador's Dungeon (X:-1925 Y:944). This is Astarion's personal
  quest. `MISSABLE` if you skip it.
- **Ambusher** (Rare, shortsword +1). +1 initiative, advantage on Perception, and **+1d6 necrotic against creatures
  that have not taken a turn yet**. bg3.wiki notes that this applies to ranged and off-hand attacks too. *The ideal
  melee-slot item for Gloom/Assassin openers. Verify that it triggers from the inactive set. [GSA][GSA7][TM].* **Get:**
  Exxvikyap, Rivington General (X:7 Y:-35), 190 gp.
- **Duellist's Prerogative** (Legendary, rapier +3). With an empty off hand: crit on 19, an extra reaction, and a
  bonus-action extra attack. *A single-weapon alternative [TM][CRIT].* **Get:** Lora's reward for "Save Vanra", Lora's
  House, Lower City (X:-65 Y:-89). `MISSABLE`: take the quest at the Basilisk Gate Barracks **before** freeing Vanra.
- **Dolor Amarus** (Rare, dagger +2). +7 damage on any weapon crit. **Get:** the NPC Dolor, Highberry's Home (X:20
  Y:-34), or Echo of Abazigal. `WARNING:` taking it from Dolor means killing him. If he survives he moves to the
  Facemaker's Boutique.
- **Belm** (Very rare, scimitar +2). Perfectly Balanced Strike gives a bonus-action attack every turn. *eip.gg's late
  pick for a Rogue/Fighter. [TM].* **Get:** opulent chest behind a locked bookcase (DC 18), basement of Elerrathin's
  Home (X:-210 Y:-50). `WARNING:` it may count as an owned container. Verify.
- **Club of Hill Giant Strength** stays in the melee slot only for the Titanstring trick (if not using Gauntlets of
  Hill Giant Strength).

#### Head
- **Mask of Soul Perception** (Very rare). **+2 attack rolls, +2 initiative**, +2 Perception, and Detect Thoughts.
  *The consensus BiS head for every Astarion build. [all].* **Get:** locked Gilded Chest in Helsik's upstairs bedroom,
  Devil's Fee (X:-33 Y:20). Use the Gold Key from the ritual-room desk, or Sleight of Hand DC 20.
  `WARNING:` **theft** from Helsik's private chest.
- **Sarevok's Horned Helmet** (Very rare, **needs medium armour**). Crit -1, immune to Frightened. *[CRIT][GSA][GSA7].*
  **Get:** Sarevok Anchev, Murder Tribunal (X:-1248 Y:503). Boss kill.
- **Assassin of Bhaal Cowl** (Very rare). +2 initiative, See Invisibility. *[GSA][TM].* **Get:** Echo of Abazigal.
  `WARNING:` see Echo below.
- **Helm of Balduran** (Legendary, **needs medium armour**). +1 AC and saves, regenerates 2 HP per turn, immune to
  crits and stun. *Defensive BiS. [GSA][GSA7][THX].* **Get:** stone altar beside Ansur, Dragon's Sanctum (X:636
  Y:-964), Wyrm's Rock.

#### Chest / armour
- **Elegant Studded Leather** (Very rare, light 14+Dex). Advantage on Stealth, **+2 initiative**, and Shield as a
  reaction once per short rest (bug: effectively once per long rest unless re-equipped). *Often called the best
  general rogue armour. [all, including a pure-Rogue TM].* **Get:** High Security Vault No.9, Counting House (X:-686
  Y:874). The key comes from "Return Rakath's Gold". `WARNING:` getting in without the quest key is a vault theft.
- **Bhaalist Armour** (Very rare, light 14+Dex). **Aura of Murder: enemies within 3 m become Vulnerable to piercing**,
  and +2 initiative. *Huge for melee piercing builds; the aura needs enemies within 3 m, so archers get less from it.
  [TM][CRIT]; [GSA] for the initiative.* **Get:** Echo of Abazigal. `WARNING:` see Echo below.
- **Armour of Agility** (Very rare, medium, **17 + full Dex**, no stealth disadvantage, +2 all saves). *The highest
  AC for multiclass Astarion. [GSA][GSA7][THX].* **Get:** Gloomy Fentonson, Stormshore Armoury, Lower City (X:-41
  Y:-71), 2900 gp.
- **Elven Chain** (Rare, medium, 14+Dex max 2). Counts as proficient for anyone, +2 initiative, advantage on Dexterity
  saves. *Gives medium-armour-like AC to a **pure Rogue**. [TM].* **Get:** Exxvikyap, Rivington General.
- **Unwanted Masterwork Scalemail** (Rare, medium 16 + full Dex, fire resistance). *Runner-up.* **Get:** Dammon, Forge
  of the Nine (X:5 Y:-7). Requires Dammon alive, as above.
- **Studded Leather Armour +2** (Rare, light 14+Dex, +1 initiative). Levelled magic armour vendors, or Orin's body.

#### Cloak
- **Shade-Slayer Cloak** (Very rare). While **Hiding**, crit threshold -1 (stacks). *[CRIT][GSA][GSA7][TM].* **Get:**
  Sticky Dondo, Guildhall, Lower City (X:-17 Y:755).
- **Cloak of Displacement** (Rare). Attackers have disadvantage until you take damage. *Defensive alternative.
  [all].* **Get:** Entharl Danthelon, Danthelon's Dancing Axe, Wyrm's Crossing (X:-10 Y:143).
- **The Deathstalker Mantle** stays strong in a Dark Urge campaign.

#### Gloves
- **Legacy of the Masters** (Very rare, **needs medium armour**). **+2 attack and +2 damage with weapons**. *BiS for
  bows and generic weapons on multiclass Astarion. [GSA][GSA7][THX].* **Get:** Dammon, Forge of the Nine (X:5 Y:-7),
  570 gp. Requires Dammon alive.
- **Gauntlets of Hill Giant Strength** (Very rare). Sets Str 23, which means **+6 per arrow with Titanstring**. *[GSA
  Titanstring].* **Get:** a pedestal in the Archive, House of Hope (X:-6549 Y:2940). Disarm with Sleight of Hand DC 20 or
  do a weight swap. `WARNING:` **theft** from Raphael's vault; it trips the trap and alerts the house if mishandled.
- **Helldusk Gloves** (Very rare). Weapon attacks deal +1d6 fire, +1 spell attack and DC. A bug makes the +1 apply to
  all attack rolls. *[TM][THX][GSA].* **Get:** worn by Haarlep, Boudoir, House of Hope (X:-6478 Y:2993).
  `WARNING:` you must kill Haarlep, who is not hostile by default.
- **Stalker Gloves** (Rare). +1 initiative and **Sneak Attack +1d4 force**. *[TM][GSA7].* **Get:** Exxvikyap, Rivington
  General (X:7 Y:-35).
- **Craterflesh Gloves** (Rare). +1d6 force on crits (bug: effectively 2d6). *[CRIT].* **Get:** Echo of Abazigal.
  `WARNING:` see Echo below.
- **Bhaalist Gloves** (Very rare). +1 attack rolls and Garrotte. **Get:** Echo of Abazigal. `WARNING:` see Echo below.
- **Gloves of Archery** stay a strong budget pick (+2 per arrow).

#### Boots
- **Helldusk Boots** (Very rare). Infernal Evasion: a reaction turns a failed save into a success. Also immune to
  forced movement, ignores difficult terrain, and Hellcrawler teleport. *[all].* **Get:** locked Gilded Chest, top
  floor of Wyrm's Rock Fortress (X:-32 Y:219). `WARNING:` taking them **after** Gortash's coronation turns Gortash and the
  Steel Watch on that floor hostile. Take them before the coronation, or after a deal with Gortash once Orin is dead.
- **Boots of Persistence** (Very rare, **needs medium armour**). Permanent Freedom of Movement and Longstrider, +1
  Dexterity saves. **Get:** Dammon, Forge of the Nine.
- **Disintegrating Night Walkers** stay competitive; many keep them all game.

#### Amulet
- **Surgeon's Subjugation Amulet** (Rare). Once per long rest, a crit on a humanoid Paralyses it for 2 turns. Melee
  attacks against a paralysed target auto-crit. *[CRIT][TM][GSA].* **Get:** worn by Malus Thorm, House of Healing
  (X:-201 Y:49). Fought during that quest.
- **Amulet of Greater Health** (Very rare). Con 23 and advantage on Constitution saves. *The survivability BiS (big HP
  jump). [all].* **Get:** leftmost pedestal, Archive, House of Hope (X:-6548 Y:2940). `WARNING:` **theft** from
  Raphael's vault (same trap rules).
- **Broodmother's Revenge** with Bite, or **Periapt of Wound Closure**: carry-overs.

#### Rings
- **Killer's Sweetheart**, **Risky Ring** and **Strange Conduit Ring** carry over.
- **Ring of Regeneration** (Very rare). Heals 1d4 at the start of each turn. **Get:** Rolan or Lorroakan's Projection,
  Sorcerous Sundries. It depends on who is alive, and it is unavailable if both Rolan and Lorroakan are dead.

#### Echo of Abazigal (Murder Tribunal, X:-1263 Y:511): one gate for many items
Sells Bhaalist Armour, Bhaalist Gloves, Assassin of Bhaal Cowl, Craterflesh Gloves, Vicious Shortbow, Dolor Amarus,
Dread Iron Dagger and Fleshrender.
`WARNING:` you can only buy here after "Impress the Murder Tribunal", which makes you an Unholy Assassin.
That requires **killing Investigator Valeria**, the hollyphant: a neutral or good NPC and a major story choice. It also
breaks a Paladin's oath. A "White Urge" (resisting) Dark Urge run would normally refuse this.
A known exploit exists: pickpocket the ghost summoned through Sarevok's "I'm ready to be judged" dialogue. Failing it
turns the Tribunal hostile.

#### Consumables (build-defining only)
- Elixir of Cloud Giant Strength or Elixir of Hill Giant Strength, for Titanstring.
- Elixir of Bloodlust: Popper, Entharl Danthelon, Bonecloaks.
- Oil of Accuracy: +2 attack rolls with the oiled weapon for 10 turns. eip.gg pairs it with Sharpshooter. Brew it from
  Ashes of Daggerroot plus a Salt.

---------------------------------------------------------------------------------------------------------------------
## 3. Best and runner-up per slot per act (main build [GSA], notes for others)

| Act | Slot | Best | Runner-up | Notes |
|---|---|---|---|---|
| 1 | Ranged | Titanstring Bow (+ Str elixir) | Harold | Bow of Awareness / Hunting Shortbow early; [THX]: Firestoker |
| 1 | Melee MH | Knife of the Undermountain King | Shortsword of First Blood | [TM] main hand |
| 1 | Melee OH | Club of Hill Giant Strength (Titanstring trick) | Sussur Dagger | [TM]: Sussur Dagger off hand |
| 1 | Head | Haste Helm | Shadow of Menzoberranzan | |
| 1 | Armour | Spidersilk Armour | The Graceful Cloth | Adamantine Scale Mail only if stealth is not needed |
| 1 | Cloak | The Deathstalker Mantle (Dark Urge campaigns only) | none notable | |
| 1 | Gloves | Gloves of Archery | Gloves of Dexterity | [TM]: Gloves of Dexterity |
| 1 | Boots | Disintegrating Night Walkers | Boots of Speed | |
| 1 | Amulet | Broodmother's Revenge | Amulet of Misty Step / Periapt of Wound Closure | |
| 1 | Ring 1 | Strange Conduit Ring | Caustic Band | |
| 1 | Ring 2 | Fetish of Callarduran Smoothhands | Smuggler's Ring / Ring of Protection | |
| 2 | Ranged | Darkfire Shortbow | Least Expected (or Titanstring + elixir) | [THX]: Hellfire Hand Crossbow + Ne'er Misser |
| 2 | Melee | Knife of the Undermountain King | Render of Mind and Body | |
| 2 | Head | Circlet of Hunting | Dark Justiciar Helmet / Marksmanship Hat | |
| 2 | Armour | Yuan-Ti Scale Mail | Sharpened Snare Cuirass | [TM] pure Rogue: Penumbral Armour |
| 2 | Cloak | Cloak of Protection | Cloak of Cunning Brume | |
| 2 | Gloves | Gloves of Archery | Gloves of Dexterity | |
| 2 | Boots | Disintegrating Night Walkers | Evasive Shoes | |
| 2 | Amulet | Broodmother's Revenge | Periapt of Wound Closure | |
| 2 | Ring 1 | Killer's Sweetheart | Risky Ring | |
| 2 | Ring 2 | Strange Conduit Ring | Shadow-Cloaked Ring | |
| 3 | Ranged | Gontr Mael | The Dead Shot / Titanstring + Gauntlets of Hill Giant Strength | sources disagree |
| 3 | Melee MH | Ambusher (opener rider) | Crimson Mischief | [TM]: Crimson Mischief |
| 3 | Melee OH | Bloodthirst | Club of Hill Giant Strength (Titanstring) | [TM]: Bloodthirst |
| 3 | Head | Mask of Soul Perception | Sarevok's Horned Helmet / Helm of Balduran | |
| 3 | Armour | Armour of Agility | Elegant Studded Leather / Bhaalist Armour | [TM] pure Rogue: Elegant Studded Leather / Bhaalist |
| 3 | Cloak | Shade-Slayer Cloak | Cloak of Displacement | |
| 3 | Gloves | Legacy of the Masters | Gloves of Archery / Gauntlets of Hill Giant Strength (Titanstring) | [TM]: Helldusk Gloves or Stalker Gloves |
| 3 | Boots | Helldusk Boots | Disintegrating Night Walkers | |
| 3 | Amulet | Amulet of Greater Health | Surgeon's Subjugation Amulet | |
| 3 | Ring 1 | Killer's Sweetheart | Risky Ring | |
| 3 | Ring 2 | Strange Conduit Ring | Ring of Regeneration / Shadow-Cloaked Ring | |

---------------------------------------------------------------------------------------------------------------------
## 4. Synergy sets

### Act 1
1. **"Giant's Draw" (Titanstring Strength archer)** for [GSA][GSA7]
   - Ranged: Titanstring Bow. Melee: Knife of the Undermountain King + Club of Hill Giant Strength.
   - Head: Haste Helm. Armour: Spidersilk Armour. Gloves: Gloves of Archery. Boots: Disintegrating Night Walkers.
   - Amulet: Broodmother's Revenge. Rings: Strange Conduit Ring + Caustic Band.
   - Consumable: Elixir of Cloud Giant Strength (or Hill Giant).
   - *Why:* every arrow adds Dex + Str (up to +8) + 2 (Gloves of Archery) + 2 acid + 1d4 psychic while Hunter's Mark is
     up. Sneak Attack also gets the Strength bonus. With many arrows per turn, flat riders multiply.
2. **"Bane Bolt" (debuffer)** for [GSA]
   - Ranged: Harold. Gloves: Gloves of Power (needs the Absolute brand).
   - Amulet: Amulet of Branding (`WARNING:` kill Jeera). The rest as in set 1.
   - *Why:* two separate Bane sources lower enemy attacks and saves, which helps casters and Battle Master
     manoeuvre DCs. Brand the Weak makes the opener's first hit deal double damage.
3. **"Shadow Step" (stealth reset)** for [GSA7][TM]
   - Ranged: Bow of Awareness. Melee: Knife of the Undermountain King + Sussur Dagger.
   - Head: Shadow of Menzoberranzan. Armour: Spidersilk Armour. Gloves: Gloves of Dexterity.
   - Boots: Disintegrating Night Walkers. Amulet: Amulet of Misty Step.
   - Rings: Fetish of Callarduran Smoothhands + Smuggler's Ring.
   - *Why:* three invisibility or teleport resets per rest. The opener stays a surprise-and-crit, and you get advantage
     for Sneak Attack every turn.
4. **"Blood Bite" (Astarion signature)** for [TM]
   - Melee: Knife of the Undermountain King + Shortsword of First Blood. Amulet: Broodmother's Revenge.
   - Ring: Caustic Band. Cloak: The Deathstalker Mantle (Dark Urge campaigns).
   - *Why:* Bite heals him, which gives +1d6 poison on every weapon hit for 3 turns. Each kill makes him Invisible, so
     he gets advantage and Sneak Attack again.

### Act 2
1. **"Hasted Hunter"** for [GSA][GSA7]
   - Ranged: Darkfire Shortbow (self-Haste). Head: Circlet of Hunting. Armour: Yuan-Ti Scale Mail.
   - Gloves: Gloves of Archery. Rings: Strange Conduit Ring + Killer's Sweetheart.
   - Boots: Disintegrating Night Walkers. Amulet: Broodmother's Revenge. Cloak: Cloak of Protection.
   - *Why:* Hunter's Mark feeds three things at once: Circlet +1d4 to hit (which offsets Sharpshooter's -5), Conduit
     +1d4 psychic, and Hunter's Mark's own +1d6. Haste adds an attack. Killer's Sweetheart turns the first kill into a
     guaranteed crit.
2. **"Gloom of Shar" (darkness crit)** for [GSA][CRIT]
   - Ranged: Least Expected. Head: Dark Justiciar Helmet. Ring: Shadow-Cloaked Ring + Killer's Sweetheart.
   - Armour: Yuan-Ti Scale Mail. Gloves: Gloves of Archery.
   - *Why:* fight from darkness. Obscured gives +1d4 to hit (Least Expected), crit on 19 (Dark Justiciar Helmet), and
     +1d4 damage against obscured enemies, all in the Shadow-Cursed Lands' own darkness.
3. **"Twin Hellfire"** for [THX]
   - Ranged: Hellfire Hand Crossbow (main hand) + Ne'er Misser (off hand). Head: Marksmanship Hat (main hand only).
   - Armour: Yuan-Ti Scale Mail. Ring: Caustic Band + Risky Ring. Gloves: Gloves of Archery.
   - *Why:* many one-handed shots per turn multiply the flat +2 acid and +2 ranged damage. Risky Ring gives permanent
     advantage, which means Sneak Attack every turn. Hellfire burns targets while you are hidden.
4. **"Snare Stalker"** for [GSA]
   - Armour: Sharpened Snare Cuirass with Ensnaring Strike, plus Darkfire Shortbow, Circlet of Hunting and Risky Ring.
   - *Why:* Ensnaring Strike lands more often, restrained targets give advantage, and advantage makes Sneak Attack
     reliable.

### Act 3
1. **"Celestial Volley" (consensus BiS archer)** for [GSA][GSA7]
   - Ranged: Gontr Mael. Melee: Ambusher + Club of Hill Giant Strength (or a shield or dagger).
   - Head: Mask of Soul Perception. Armour: Armour of Agility. Cloak: Shade-Slayer Cloak.
   - Gloves: Legacy of the Masters. Boots: Helldusk Boots. Amulet: Amulet of Greater Health.
   - Rings: Killer's Sweetheart + Strange Conduit Ring.
   - *Why:* +2 (Mask) and +2 (Legacy) to hit, +3 from Gontr Mael, and Guiding Bolt advantage together cancel
     Sharpshooter's penalty. Celestial Haste gives more attacks. Ambusher adds +1d6 to every opener shot on enemies that
     have not acted yet.
2. **"Titan's Fury" (Strength archer)** for [GSA]
   - Ranged: Titanstring Bow. Gloves: Gauntlets of Hill Giant Strength (`WARNING:` theft), or Elixir of Cloud Giant
     Strength with Legacy of the Masters.
   - Head: Mask of Soul Perception. Armour: Armour of Agility. Rings: Strange Conduit Ring + Risky Ring.
   - *Why:* +6 to +8 flat damage per arrow, and on Sneak Attack. Risky Ring keeps advantage up, which offsets
     Sharpshooter. eip.gg and others say this is the highest sustained bow damage.
3. **"Executioner" (crit stack)** for [CRIT][GSA7]
   - Ranged: The Dead Shot. Head: Sarevok's Horned Helmet. Cloak: Shade-Slayer Cloak.
   - Gloves: Craterflesh Gloves. Melee: Dolor Amarus + Bloodthirst (the main-hand Bloodthirst crit only works in melee).
   - Amulet: Surgeon's Subjugation Amulet. Rings: Killer's Sweetheart + Risky Ring.
   - *Why:* shooting from Hiding, the stacked reductions (Dead Shot, Sarevok and Shade-Slayer, -3) give a crit on 17.
     Each crit adds +1d6 force (Craterflesh) and +7 (Dolor passive), and Surgeon's paralyse sets up follow-up crits.
     Assassinate already auto-crits surprised targets.
   - `WARNING:` Craterflesh and Dolor Amarus come from Echo, which means killing Valeria.
4. **"Murder Aura" (melee Thief)** for [TM]
   - Melee: Crimson Mischief (main hand) + Bloodthirst (off hand). Armour: Bhaalist Armour. Head: Mask of Soul
     Perception or Assassin of Bhaal Cowl. Gloves: Bhaalist Gloves, Helldusk Gloves or Stalker Gloves.
   - Cloak: Shade-Slayer Cloak. Amulet: Amulet of Greater Health. Rings: Killer's Sweetheart + Risky Ring.
   - *Why:* Bhaalist's aura and Bloodthirst's Exploit Weakness both make targets vulnerable to piercing, so piercing
     damage is doubled. Risky Ring advantage triggers Crimson Mischief's +7 and Sneak Attack on every hit.
     Fextralife and the GameRant-style guides list this as the melee BiS. `WARNING:` it needs Echo (killing Valeria).
     The no-Echo version swaps in Elegant Studded Leather and Mask of Soul Perception.
5. **"First Strike" (initiative stack)** for [GSA][GSA7]
   - Ranged: Hellrider Longbow (+3). Head: Mask of Soul Perception (+2). Armour: Elegant Studded Leather (+2).
   - Melee: Ambusher (+1). Gloves: Stalker Gloves (+1).
   - *Why:* with Alert (+5) and Dread Ambusher (+Wisdom), Astarion acts first in nearly every fight. Assassinate's
     advantage against enemies that have not acted, plus Ambusher's +1d6, applies to the whole first round.
     Hellrider's Faerie Fire gives advantage to the rest of the party.

---------------------------------------------------------------------------------------------------------------------
## 5. Community consensus notes

- **Widely called BiS:** Mask of Soul Perception (every build); Gontr Mael (archer endgame); Crimson Mischief and
  Bloodthirst (melee Astarion); Bhaalist Armour (melee) and Elegant Studded Leather (all-round rogue armour);
  Killer's Sweetheart; Disintegrating Night Walkers; Gloves of Archery (early to mid archer); Titanstring Bow (Act 1
  and as a Strength-boosted endgame option); Knife of the Undermountain King (Act 1-2 melee); Yuan-Ti Scale Mail (Act 2
  multiclass).
- **Bow disagreement:** Prima, cyberpost and most tier lists rank Gontr Mael first. Titanstring advocates (eip.gg,
  Steam threads) argue that with Gauntlets of Hill Giant Strength or a Cloud Giant elixir it does more damage over
  many attacks. Steam users say Titanstring is better at 2-3 attacks per turn, while dual hand crossbows pull ahead at
  5-6 attacks. The Dead Shot is preferred for crit builds.
- **Armour disagreement:** pure-Rogue guides (Fextralife, TheGamer) use light armour (Bhaalist or Elegant). Multiclass
  guides (eip.gg Astarion guide, TheGamer search summary) use full-Dex medium armour: Yuan-Ti, then Armour of Agility
  or Unwanted Masterwork Scalemail.
- **Niche or situational:** Ring of Shadows, Penumbral Armour, Smuggler's Ring (stealth utility); Sharpened Snare
  Cuirass (Ensnaring builds); Spellthief; The Joltshooter; Callous Glow Ring; Bow of the Banshee.
- **Errors in guides, to avoid:**
  - eip.gg's level-20 page lists "Legacy of the Masters" and "Craterflesh" as rings; both are gloves.
  - eip.gg says Broodmother's Revenge gives 1d4; bg3.wiki says 1d6.
  - Deltia's says the Cloak of Displacement is in Act 1 and gives spell attack. Per bg3.wiki it is a displacement cloak
    sold at Wyrm's Crossing in Act 3.
  - GameRant and gfinity-style guides recommend Drow Studded Leather Armour, which bg3.wiki flags as unobtainable in
    Patch 8.
  - The eip.gg party guide lists The Deathstalker Mantle as an Act 1 cloak without saying it is Dark Urge only.
  - Builds.lua lists Bracers of Defence and Ring of Absolute Force. Both are a poor fit (see section 1).
- **Patch 8:** no major changes found to the items above. Patch 8 mostly added subclasses, such as Swarmkeeper for
  Ranger.
- **Reddit:** reddit.com could not be fetched from this environment, so the consensus here comes from guide sites,
  Steam discussions and tier lists that summarise community picks. Spot-check r/BG3Builds if needed.

### Sources
- bg3.wiki item pages: https://bg3.wiki/wiki/Titanstring_Bow, https://bg3.wiki/wiki/Gontr_Mael,
  https://bg3.wiki/wiki/The_Dead_Shot, https://bg3.wiki/wiki/Darkfire_Shortbow, https://bg3.wiki/wiki/Least_Expected,
  https://bg3.wiki/wiki/Harold, https://bg3.wiki/wiki/Hellfire_Hand_Crossbow, https://bg3.wiki/wiki/Ne%27er_Misser,
  https://bg3.wiki/wiki/Hellrider_Longbow, https://bg3.wiki/wiki/Bow_of_Awareness, https://bg3.wiki/wiki/Hunting_Shortbow,
  https://bg3.wiki/wiki/Bow_of_the_Banshee, https://bg3.wiki/wiki/Spellthief, https://bg3.wiki/wiki/The_Joltshooter,
  https://bg3.wiki/wiki/Vicious_Shortbow, https://bg3.wiki/wiki/Firestoker,
  https://bg3.wiki/wiki/Knife_of_the_Undermountain_King, https://bg3.wiki/wiki/Crimson_Mischief,
  https://bg3.wiki/wiki/Bloodthirst, https://bg3.wiki/wiki/Rhapsody, https://bg3.wiki/wiki/Ambusher,
  https://bg3.wiki/wiki/Duellist%27s_Prerogative, https://bg3.wiki/wiki/Dolor_Amarus, https://bg3.wiki/wiki/Sussur_Dagger,
  https://bg3.wiki/wiki/Belm, https://bg3.wiki/wiki/Render_of_Mind_and_Body, https://bg3.wiki/wiki/Shortsword_of_First_Blood,
  https://bg3.wiki/wiki/Speedy_Reply, https://bg3.wiki/wiki/The_Baneful, https://bg3.wiki/wiki/Club_of_Hill_Giant_Strength,
  https://bg3.wiki/wiki/Mask_of_Soul_Perception, https://bg3.wiki/wiki/Haste_Helm, https://bg3.wiki/wiki/Helm_of_Balduran,
  https://bg3.wiki/wiki/Marksmanship_Hat, https://bg3.wiki/wiki/Dark_Justiciar_Helmet,
  https://bg3.wiki/wiki/Sarevok%27s_Horned_Helmet, https://bg3.wiki/wiki/Circlet_of_Hunting,
  https://bg3.wiki/wiki/Assassin_of_Bhaal_Cowl, https://bg3.wiki/wiki/Shadow_of_Menzoberranzan,
  https://bg3.wiki/wiki/Holy_Lance_Helm, https://bg3.wiki/wiki/Spidersilk_Armour, https://bg3.wiki/wiki/Bhaalist_Armour,
  https://bg3.wiki/wiki/Elegant_Studded_Leather, https://bg3.wiki/wiki/Yuan-Ti_Scale_Mail,
  https://bg3.wiki/wiki/Armour_of_Agility, https://bg3.wiki/wiki/Unwanted_Masterwork_Scalemail,
  https://bg3.wiki/wiki/Sharpened_Snare_Cuirass, https://bg3.wiki/wiki/Penumbral_Armour, https://bg3.wiki/wiki/Elven_Chain,
  https://bg3.wiki/wiki/Studded_Leather_Armour_%2B2, https://bg3.wiki/wiki/Drow_Studded_Leather_Armour,
  https://bg3.wiki/wiki/Adamantine_Scale_Mail, https://bg3.wiki/wiki/The_Graceful_Cloth,
  https://bg3.wiki/wiki/Dark_Justiciar_Half-Plate_(Very_Rare), https://bg3.wiki/wiki/The_Deathstalker_Mantle,
  https://bg3.wiki/wiki/Shade-Slayer_Cloak, https://bg3.wiki/wiki/Cloak_of_Displacement,
  https://bg3.wiki/wiki/Cloak_of_Protection, https://bg3.wiki/wiki/Cloak_of_Cunning_Brume,
  https://bg3.wiki/wiki/Gloves_of_Archery, https://bg3.wiki/wiki/Gloves_of_Dexterity,
  https://bg3.wiki/wiki/Legacy_of_the_Masters, https://bg3.wiki/wiki/Stalker_Gloves,
  https://bg3.wiki/wiki/Gauntlets_of_Hill_Giant_Strength, https://bg3.wiki/wiki/Helldusk_Gloves,
  https://bg3.wiki/wiki/Craterflesh_Gloves, https://bg3.wiki/wiki/Bhaalist_Gloves, https://bg3.wiki/wiki/Gloves_of_Power,
  https://bg3.wiki/wiki/Gloves_of_Thievery, https://bg3.wiki/wiki/Bracers_of_Defence,
  https://bg3.wiki/wiki/Dark_Justiciar_Gauntlets_(Rare), https://bg3.wiki/wiki/Disintegrating_Night_Walkers,
  https://bg3.wiki/wiki/Boots_of_Speed, https://bg3.wiki/wiki/Helldusk_Boots, https://bg3.wiki/wiki/Evasive_Shoes,
  https://bg3.wiki/wiki/Boots_of_Persistence, https://bg3.wiki/wiki/Broodmother%27s_Revenge,
  https://bg3.wiki/wiki/Amulet_of_Misty_Step, https://bg3.wiki/wiki/Periapt_of_Wound_Closure,
  https://bg3.wiki/wiki/Amulet_of_Branding, https://bg3.wiki/wiki/Brand_the_Weak,
  https://bg3.wiki/wiki/Surgeon%27s_Subjugation_Amulet, https://bg3.wiki/wiki/Amulet_of_Greater_Health,
  https://bg3.wiki/wiki/Strange_Conduit_Ring, https://bg3.wiki/wiki/Killer%27s_Sweetheart, https://bg3.wiki/wiki/Caustic_Band,
  https://bg3.wiki/wiki/Shadow-Cloaked_Ring, https://bg3.wiki/wiki/Risky_Ring,
  https://bg3.wiki/wiki/Fetish_of_Callarduran_Smoothhands, https://bg3.wiki/wiki/Ring_of_Shadows,
  https://bg3.wiki/wiki/Callous_Glow_Ring, https://bg3.wiki/wiki/Smuggler%27s_Ring, https://bg3.wiki/wiki/Ring_of_Protection,
  https://bg3.wiki/wiki/Crusher%27s_Ring, https://bg3.wiki/wiki/Ring_of_Absolute_Force,
  https://bg3.wiki/wiki/Ring_of_Free_Action, https://bg3.wiki/wiki/Ring_of_Regeneration,
  https://bg3.wiki/wiki/Elixir_of_Hill_Giant_Strength, https://bg3.wiki/wiki/Elixir_of_Cloud_Giant_Strength,
  https://bg3.wiki/wiki/Elixir_of_Bloodlust, https://bg3.wiki/wiki/Oil_of_Accuracy, https://bg3.wiki/wiki/Sentinel_Shield
- bg3.wiki context pages: https://bg3.wiki/wiki/Echo_of_Abazigal, https://bg3.wiki/wiki/Impress_the_Murder_Tribunal,
  https://bg3.wiki/wiki/Devil%27s_Fee, https://bg3.wiki/wiki/Zhentarim_Hideout, https://bg3.wiki/wiki/Yurgir,
  https://bg3.wiki/wiki/Dammon, https://bg3.wiki/wiki/Quartermaster_Talli, https://bg3.wiki/wiki/Sticky_Dondo,
  https://bg3.wiki/wiki/Patch_8, plus the list pages Longbows, Shortbows, Hand_Crossbows, Heavy_Crossbows, Daggers,
  Rapiers, Shortswords, Scimitars, Light_Armour, Medium_Armour, Headwear, Cloaks, Boots, Amulets, Rings
- Build guides: https://eip.gg/bg3/builds/astarion-gloomstalker-assassin-party-code-v1/ ,
  https://eip.gg/bg3/builds/gloom-stalker-assassin-fighter-lvl-20/ , https://eip.gg/bg3/guides/astarion-build/ ,
  https://www.thegamer.com/baldurs-gate-3-astarion-best-build-equipment-subclass/ ,
  https://baldursgate3.wiki.fextralife.com/Astarion , https://www.gfinityesports.com/guides/baldurs-gate-3-best-astarion-build ,
  https://hacktheminotaur.com/baldurs-gate-3/ultimate-bg3-astarion-build/
- Tier lists and bows: https://primagames.com/lists/best-bows-in-bg3-ranked , https://cyberpost.co/what-is-the-best-bow-in-bg3/ ,
  https://hacktheminotaur.com/baldurs-gate-3/best-titanstring-bow-build-for-baldurs-gate-3/
- Community threads: https://steamcommunity.com/app/1086940/discussions/0/4032474464292247935 (the dual hand crossbow vs
  Titanstring debate, taken from the search snippet; the page body did not load)
- Not used due to errors: https://deltiasgaming.com (cloak claims). mobalytics.gg returned 403; alcasthq returned no body.
