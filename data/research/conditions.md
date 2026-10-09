# Campaign / origin / party / story-path conditions per item (read by tools/score_items.py)

Built 2026-10-09 from the coordinator's catalogue analysis/CAMPAIGN_CONDITIONS.md (research-derived) and checked
against the game data (data/items_all/sources.jsonl): column "Data check" says what the game data shows; "contradicts"
rows are still coded (user decision 2026-10-09: every catalogue item gets its condition) but listed as doubts in
analysis/SETS_AUDIT.md. score_items.py also derives codes on its own (Dark-Urge-only sources, items placed in one
companion's origin quest, Shar / Selune wording in an item's own research text, Last Light Inn stock) and takes the
union with this table.

Round 2 (2026-10-09): the 14 verdicts of analysis/RESEARCH_VERDICTS.md are applied (verdict numbers in the Research
column, "V#"); the act overrides and trader-loss rules below are new.

## Codes
- `durge` - only exists in a Dark Urge campaign
- `origin:<char>` - a reward of that origin companion's own quest (label: "companion quest reward")
- `party:<char>` - that companion must be in the party at the time (every origin:<char> also implies party:<char>)
- `path:<x>` - needs story path x; `!path:<x>` - lost when path x is taken
- `timing:<x>` - a moment or order to respect (not exclusive; shown as a note)
- `note:<x>` - information only (cost, alternative route)
- `unobtainable` - research says the item cannot be obtained in Patch 8: never recommended, never a fallback

## Exclusive path families
A set never holds two items whose conditions cannot both be true: `path:a` + `path:b` from one family below, or
`path:x` + `!path:x` when the item lost on path x first becomes obtainable in a LATER act than the path item (it can no
longer be bought; same or earlier act = buy it first, a timing note, not an exclusion). General rule over the tags; the
families only say which paths are alternatives.

| Family | Paths |
|---|---|
| Nightsong | shar, selune |
| Grove | goblins, tieflings |
| Bhaal | bhaal_accept, bhaal_refuse |

## Traders lost on a path
Every reliable game-data source of an item is one of these traders / places -> the item gets the codes (V5).

| Place (region contains) | Trader (holder name, empty = any) | Codes |
|---|---|---|
| Last Light Inn | | !path:isobel_kill, !path:shar |
| Moonrise Towers | Roah Moonglow | !path:shar |
| Moonrise Towers | Araj Oblodra | !path:shar |

## Act overrides
Items filed under the act they are really obtainable in (research / verdicts), not the act of their game-data placement.
First / last = the acts the item can be obtained in; the scorer uses these instead of the game-data acts.

| Stats id | Item | First act | Last act | Reason |
|---|---|---|---|---|
| END_Emperor_Staff | Staff of the Emperor | 3 | 3 | V6: disarm the Emperor in the Astral Plane (Act 2->3 transition); placement is Act 2 |
| MAG_Gortash_HeavyCrossbow | Fabricated Arbalest | 3 | 3 | carried by Gortash (Act 3 boss); placement is the Colony crown controller |
| MAG_GreaterSilver_Greatsword | Silver Sword of the Astral Plane | 3 | 3 | crafted.md:243: Lae'zel's Act 3 reward; the Act 1 copy needs disarming Kith'rak Voss and forfeits it |
| OBJ_Potion_Of_Cloud_Giant_Strength | Elixir of Cloud Giant Strength | 3 | 3 | V13: trader stock only at party level 9+ (also follows from the fixed trader level windows) |

## Paths that cost an origin companion
Items that need these paths are left out of sets and best lists unless the path already happened (the mod re-enables
them live; field `costs` in the data).

| Path | Companion lost |
|---|---|
| karlach_kill | karlach |
| astarion_kill | astarion |
| shadowheart_kill | shadowheart |
| gale_kill | gale |
| wyll_kill | wyll |
| laezel_kill | laezel |

## Scarce materials
A group of items that share one limited material: across the party only `Capacity` of them can exist (each item at
most `Copies per item` times). The best-fit (character, item) pairs get them (owner ranking in the output, like unique
items).

| Material | Capacity | Items | Note | Copies per item |
|---|---|---|---|---|
| Mithral Ore | 2 | MAG_MeleeDebuff_AttackDebuff2_OnDamage_SplintMail, MAG_MeleeDebuff_AttackDebuff1_OnDamage_ScaleMail, MAG_MeleeDebuff_AttackDebuff1_OnDamage_Shield, MAG_MeleeDebuff_AttackDebuff12versatile_OnDamage_Longsword, MAG_MeleeDebuff_AttackDebuff1_OnDamage_Mace, MAG_MeleeDebuff_AttackDebuff1_OnDamage_Scimitar | crafted.md:22: two Mithral Ore per playthrough, one per forged item; a mould can be used twice | 2 |
| Infernal Iron | 3 | MAG_Lesser_Infernal_Plate_Armor, MAG_Lesser_Infernal_Metal_Helmet, MAG_Lesser_Infernal_Metal_Gloves | crafted.md:108-157: 7 Infernal Iron, 2 go to Karlach's engine; Dammon forges Armour, then Helmet, then Gloves | 1 |

## Items

| Stats id | Item | Codes | Research | Data check |
|---|---|---|---|---|
| UNI_DarkUrge_Bhaal_Cloak | The Deathstalker Mantle | durge | darkurge.md:48, crafted.md:118 | agrees: reward of story goal Act1_ORI_DarkUrge; Sceleritas Fel (Durge butler) |
| MAG_PHB_OfEvasion_Ring | Ring of Evasion | origin:gale | - (game data only) | game data: only source is Gale's origin quest (Tara, GLO_Origin_Gale_PostEA) |
| MAG_OfSharpCaster_Hat | Hat of the Sharp Caster | party:gale | wyll.md:376 | contradicts: lies in the world at the Lower City Tressym Trade |
| MAG_OfTheDevout_Amulet | Amulet of the Devout | note:curse_free_if_jaheira_loots_it_wearing_khalids_gift | gale.md:464, laezel.md:197 | partly: container owned by Vicar Humbletoes; the party condition only removes the curse |
| CRE_MAG_Psychic_Githborn_Circlet | Circlet of Psionic Revenge | origin:laezel | laezel.md:57, crafted.md:96 | partly: worn by the Inquisitor (kill / pickpocket works in any party) |
| MAG_GreaterSilver_Greatsword | Silver Sword of the Astral Plane | origin:laezel | crafted.md:243, laezel.md:153 | partly: Act 1 copy worn by Kith'rak Voss (disarm), Act 3 copy via Lae'zel's quest |
| UNI_Cazador_RitualDagger | Rhapsody | note:cazador_boss_drop | V9 (astarion.md:313 wrong) | plain Cazador loot, any party |
| SHA_SharSpear | Spear of Night | origin:shadowheart | crafted.md:170, darkurge.md:203 | agrees: Gauntlet of Shar rewards (Nightsong prison) |
| MAG_TheBulwark_Shield | Viconia's Walking Fortress | origin:shadowheart | crafted.md:297, shadowheart.md:345 | agrees: worn by Viconia DeVir (House of Grief) |
| MAG_Viconia_Robe | Viconia's Priestess Robe | origin:shadowheart | shadowheart.md:387 | agrees: worn by Viconia DeVir |
| MAG_SHA_SharBlessing_Spear | Shar's Spear of Evening | origin:shadowheart, path:shar | shadowheart.md:203, crafted.md:176 | agrees: Origin story (companion quest): Shadowheart |
| UNI_DarkJusticiarArmor_HalfPlate | Dark Justiciar Half-Plate (Very rare) | origin:shadowheart, path:shar | shadowheart.md:246, crafted.md:176 | agrees |
| SHA_JusticiarArmor_Gloves | Dark Justiciar Gauntlets (Rare) | origin:shadowheart, path:shar | shadowheart.md:276, darkurge.md:236 | agrees |
| UNI_SHA_DarkJusticiar_Boots | Dark Justiciar Boots | origin:shadowheart, path:shar | shadowheart.md:282, crafted.md:176 | agrees |
| MAG_Moonlight_Glaive | Moonlight Glaive | origin:shadowheart, path:selune | crafted.md:178, laezel.md:100 | agrees: quest step SCL_NightsongPrison_Weapon |
| MAG_SHA_SeluneBlessing_Spear | Selune's Spear of Night | origin:shadowheart, path:selune | shadowheart.md:327, crafted.md:178 | agrees: camp reward (Act2_CAMP) |
| MAG_WYR_Hellrider_Longbow | Hellrider Longbow | timing:ferg_selune_shadowheart | shadowheart.md:355, astarion.md:298 | Ferg will not trade with a Selune Shadowheart nearby |
| MAG_PHB_DwarvenThrower_Warhammer | Dwarven Thrower | timing:ferg_selune_shadowheart | karlach.md:153 | same trader rule |
| ORI_Wyll_Infernal_Rapier | Infernal Rapier | origin:wyll, path:mizora_freed | wyll.md:191, wyll.md:603 | agrees: quest 'The Blade of Frontiers' MizorasRescueReward |
| ORI_Wyll_Infernal_Robe | Infernal Robe | origin:wyll, path:karlach_kill | wyll.md:110, gale.md:644 | agrees: quest 'The Blade of Frontiers' MizorasJudgementReward |
| MAG_WYRM_Commander_Longsword | Duke Ravengard's Longsword | origin:wyll, path:ravengard_rescued | wyll.md:339 | partly: worn by the Duke (Command: Drop / theft) |
| DEN_RaidingParty_GoblinCaptain_Gloves | Gloves of Power | path:absolute_brand | astarion.md:138 | only the bonus needs the brand |
| MAG_LC_CazadorVampiric_Quarterstaff | Woe | !path:astarion_ascends | gale.md:365 | worn by Cazador Szarr |
| END_Emperor_Staff | Staff of the Emperor | timing:astral_plane | V6 (wyll.md:324 right) | worn by the Emperor; disarm him in the Astral Plane |
| MAG_OfFeywildSparks_Ring | Ring of Feywild Sparks | path:ethel_spared | gale.md:474, darkurge.md:313, crafted.md:105 | contradicts: Act 3 reward at the Blushing Mermaid |
| MAG_Infernal_Metal_Boots | Helldusk Boots | timing:gortash_deal | crafted.md:223, darkurge.md:301 | locked chest at Wyrm's Rock (Gortash's key) |
| MAG_Harpers_RingOfProjection | Ring of Flinging | !path:goblins | darkurge.md:180 | agrees: sold by Arron (Emerald Grove) |
| UNI_Bow_SpellslotRecharge | Spellthief | !path:goblins | darkurge.md:180 | partly: also sold by Auntie Ethel |
| MAG_Safeguard_Shield | Safeguard Shield | !path:goblins | shadowheart.md:81 | partly: Dammon also sells it in Acts 2-3 |
| WPN_HandCrossbow_1 | Hand Crossbow +1 | !path:goblins | astarion.md:80 | contradicts: 25 copies in the game |
| MAG_Selunite_Isobel_Robe | Moon Devotion Robe | path:isobel_dead | V4 | worn by Isobel; only from her corpse (any cause of death) |
| MAG_Harpers_JhannylGloves | Jhannyl's Gloves | path:isobel_dead | V4 | worn by Isobel; only from her corpse |
| MAG_CharismaCaster_Robe | Potent Robe | path:tieflings, !path:durge_alfira, path:prisoners_rescued, !path:isobel_kill, !path:shar | V3 | reward of quest 'Rescue the Tieflings' (Alfira's big reward) |
| MAG_CKM_SerpenScale_Armor | Yuan-ti Scale Mail | !path:isobel_kill, !path:shar | darkurge.md:97, darkurge.md:191 | agrees: Talli (Last Light Inn) |
| MAG_PHB_CloakOfProtection_Cloak | Cloak of Protection | !path:isobel_kill, !path:shar | darkurge.md:97 | agrees: Talli |
| MAG_BarbMonk_Offensive_Cloth | The Mighty Cloth | !path:isobel_kill, !path:shar | darkurge.md:97 | agrees: Talli |
| MAG_Harpers_HarpersAmulet | Amulet of the Harpers | !path:isobel_kill, !path:shar | darkurge.md:97 | agrees: Talli |
| MAG_Heat_Fire_Robe | Obsidian Laced Robe | !path:isobel_kill, !path:shar | darkurge.md:97 | agrees: Talli |
| MAG_Evasive_Shoes | Evasive Shoes | !path:isobel_kill, !path:shar | darkurge.md:97 | partly: Mattis also sells it in Act 3 |
| MAG_Shadow_FogOfCloudDisengage_Cloak | Cloak of Cunning Brume | !path:isobel_kill, !path:shar | astarion.md:235 | partly: Mattis Act 3 |
| MAG_Shadow_CriticalBoostWhileObscured_Helmet | Covert Cowl | !path:isobel_kill, !path:shar | darkurge.md:227 | agrees: Meenlock, LLI cellar |
| MAG_Radiant_RadiatingOrb_Ring | Coruscation Ring | !path:isobel_kill, !path:shar | darkurge.md:97 | agrees: LLI buried chest |
| MAG_BG_Darkfire_Shortbow | Darkfire Shortbow | path:tieflings, !path:isobel_kill | astarion.md:199, darkurge.md:195 | agrees: Dammon after Act2_HAV_Tiefling... |
| MAG_BG_Harmonium_Halberd | Harmonium Halberd | path:tieflings, !path:isobel_kill | darkurge.md:195 | agrees: Dammon |
| MAG_PHB_OfLifestealing_Shortsword | Sword of Life Stealing | path:tieflings, !path:isobel_kill | darkurge.md:195 | agrees: Dammon |
| MAG_Bonded_Shocking_Warhammer | Charge-Bound Warhammer | path:tieflings, !path:isobel_kill | darkurge.md:195 | agrees: Dammon |
| MAG_Fire_HeatOnWeaponDamage_Battleaxe | Thermodynamo Axe | path:tieflings, !path:isobel_kill | karlach.md:100 | partly: second copy in the Upper City |
| MAG_Lesser_Infernal_Plate_Armor | Flawed Helldusk Armour | path:tieflings, !path:isobel_kill | crafted.md:149 | agrees: Dammon forges it |
| MAG_Lesser_Infernal_Metal_Helmet | Flawed Helldusk Helmet | path:tieflings, !path:isobel_kill | crafted.md:149 | agrees |
| MAG_Lesser_Infernal_Metal_Gloves | Flawed Helldusk Gloves | path:tieflings, !path:isobel_kill | crafted.md:149 | agrees |
| MAG_EndGame_Plate_Armor | Armour of Persistence | path:tieflings, !path:isobel_kill | darkurge.md:98, darkurge.md:279 | agrees: Dammon, Act 3 |
| MAG_BG_OfTheMasters_Legacy_Gauntlet | Legacy of the Masters | path:tieflings, !path:isobel_kill | darkurge.md:297 | agrees: Dammon, Act 3 |
| MAG_EndGame_Metal_Boots | Boots of Persistence | path:tieflings, !path:isobel_kill | darkurge.md:98 | agrees: Dammon, Act 3 |
| MAG_DevilsBlackmith_ScaleMail | Unwanted Masterwork Scalemail | path:tieflings, !path:isobel_kill | astarion.md:358 | agrees: Dammon, Act 3 |
| MAG_Healer_HealSelf_Helmet | Wapira's Crown | path:tieflings | shadowheart.md:97 | contradicts: container in the Emerald Grove |
| DEN_HellridersPride | Hellrider's Pride | path:tieflings | shadowheart.md:136, darkurge.md:159 | agrees: reward Act1_DEN_TieflingRefugees / Zevlor |
| GOB_DrowCommander_Leather_Armor | Spidersilk Armour | path:tieflings | astarion.md:115, darkurge.md:140 | agrees: worn by Minthara (goblin path: pickpocket only) |
| MAG_Paladin_MomentumOnConcentration_Boots | Boots of Striding | path:tieflings | shadowheart.md:147 | agrees: worn by Minthara |
| MAG_Violence_ViolenceOnDash_Boots | Linebreaker Boots | path:tieflings | karlach.md:76 | agrees: worn by Beastmaster Zurk |
| MAG_Throwable_Pike | Returning Pike | timing:goblin_camp_raid | darkurge.md:118 | Grat the Trader (goblin camp) |
| UNI_ARM_OfArchery_Gloves | Gloves of Archery | timing:goblin_camp_raid | darkurge.md:118 | Grat |
| UNI_DoomHammer | Doom Hammer | timing:goblin_camp_raid | darkurge.md:118 | Grat |
| MAG_LowHP_IncreaseDamage_Greataxe | Blooded Greataxe | timing:goblin_camp_raid | darkurge.md:123 | Roah (also Moonrise, Act 2) |
| MAG_OfAwareness_Bow | Bow of Awareness | timing:goblin_camp_raid | darkurge.md:123 | Roah (also Moonrise, Act 2) |
| MAG_Healer_HealSelfPoisonWeapon_Amulet | Broodmother's Revenge | path:kagha_kill | darkurge.md:169, astarion.md:156 | agrees: worn by Kagha (second copy only at the endgame High Hall) |
| PLA_WPN_SwordOfJustice | Sword of Justice | path:anders_or_karlach_kill | darkurge.md:120, laezel.md:38 | Anders (siding with Karlach also gives it) |
| FOR_NightWalkers | Disintegrating Night Walkers | note:kill_or_pickpocket_nere | V12 | in Nere's inventory, CanBePickpocketed; also on his body if he suffocates |
| UND_Nere_Sword | Sword of Screams | path:nere_dead | darkurge.md:127, crafted.md:63 | worn by Nere (killed or suffocated) |
| LOW_OrphicHammer | Orphic Hammer | path:orpheus | crafted.md:214 | House of Hope rewards |
| MAG_Bhaalist_Armor | Bhaalist Armour | path:tribunal | V1, V10 (any party; Valeria only) | agrees: Echo of Abazigal / Ghost of Murders Past only |
| MAG_Bhaalist_Gloves | Bhaalist Gloves | path:tribunal | darkurge.md:65 | agrees |
| MAG_Bhaalist_Hat | Assassin of Bhaal Cowl | path:tribunal | darkurge.md:66 | agrees |
| MAG_Critical_Force_Gloves | Craterflesh Gloves | path:tribunal | V11 | agrees |
| MAG_LC_Fleshrend_Shortsword | Fleshrender | path:tribunal | darkurge.md:68 | agrees |
| MAG_Vicious_Battleaxe | Vicious Battleaxe | path:tribunal | darkurge.md:70 | agrees |
| MAG_Vicious_Shortbow | Vicious Shortbow | path:tribunal | darkurge.md:70 | agrees |
| MAG_Zhentarim_SleeperDagger | Dread Iron Dagger | path:tribunal | darkurge.md:70 | agrees |
| ARM_StuddedLeather_Body_Drow | Drow Studded Leather Armour | unobtainable | astarion.md:122, astarion.md:574 | data: Underdark Drow Resupply chest + Lower City placement; bg3.wiki flags it unobtainable in Patch 8 |
| MAG_Hat_Butler | Gibus of the Worshipful Servant | note:free_for_the_durge_else_35gp_or_theft | V8 | Helsik sells it to anyone; free for the Durge (note only) |
