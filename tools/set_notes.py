"""Short "why it works" texts for the research seed sets (key = "<char>:<act>:<set number>"), written in our
own words from the mechanics of the items. Used by score_items.py; sets without an entry get a generated text."""

WHY = {
    # ---------------- Astarion
    "astarion:1:1": "Titanstring adds Strength to every arrow, so a Strength elixir (or the Club in the off hand) turns "
                    "each shot into a big flat hit; archery gloves, acid ring and the psychic ring under Hunter's Mark "
                    "pile more flat damage onto every arrow.",
    "astarion:1:2": "Two separate Bane sources (Harold's bolts and the branded gloves) weaken enemy attacks and saves, "
                    "and Brand the Weak doubles the opener's damage.",
    "astarion:1:3": "Three invisibility or teleport resets per rest keep Astarion hidden, so every opener is a surprise "
                    "crit and Sneak Attack has advantage.",
    "astarion:1:4": "Bite heals Astarion, which coats his blades in poison for three turns; a kill with the Mantle makes "
                    "him invisible for the next advantaged Sneak Attack.",
    "astarion:2:1": "Hunter's Mark is used three times: the Circlet's accuracy covers the Sharpshooter penalty, the "
                    "Conduit ring adds psychic damage, and the bow's self-Haste buys another attack.",
    "astarion:2:2": "Act 2 darkness keeps targets obscured: the bow hits more often, the helmet crits on 19 and the ring "
                    "adds damage against obscured foes.",
    "astarion:2:3": "Two hand crossbows mean many shots a turn, so flat riders (acid ring, archery gloves) multiply; "
                    "the Risky Ring gives advantage and with it Sneak Attack every turn.",
    "astarion:2:4": "The cuirass makes Ensnaring Strike stick; restrained targets give advantage, which keeps Sneak "
                    "Attack and Sharpshooter landing.",
    "astarion:3:1": "Mask, gloves and the +3 bow add about +7 to hit, cancelling Sharpshooter; Gontr Mael's Haste and "
                    "Guiding Bolt add attacks and advantage, Ambusher adds damage before enemies act.",
    "astarion:3:2": "Strength 23-27 makes Titanstring add +6 to +8 to every arrow and Sneak Attack; the Risky Ring "
                    "keeps advantage up to offset Sharpshooter.",
    "astarion:3:3": "Bow, helmet and cloak each lower the crit number while hidden (crit on 17), then the gloves and "
                    "Dolor passive add damage to every crit and the amulet paralyses humanoids for auto-crits.",
    "astarion:3:4": "Bhaalist aura and Bloodthirst's off-hand both make targets vulnerable to piercing; the Risky "
                    "Ring's advantage triggers Crimson Mischief's +7 and Sneak Attack on every hit.",
    "astarion:3:5": "Bow, Mask, armour, Ambusher and gloves stack initiative so Astarion acts first and the whole "
                    "first round hits enemies that have not moved yet.",
    # ---------------- Gale
    "gale:1:1": "Every Magic Missile dart charges the staff with Lightning Charges; the charges power the robe's AC "
                "and saves, the helmet's temp HP and the shield's aura.",
    "gale:1:2": "Lightning and thunder hits and every condition stack Reverberation, lowering CON saves and knocking "
                "targets prone - the base for Act 2 daze rings.",
    "gale:1:3": "Staff, circlet and robe raise the save DC; the Pearl restores a slot, the shield makes him crit-proof "
                "and the boots give a free escape.",
    "gale:1:4": "Cold spells chill and encrust targets with frost and leave ice; the boots stop Gale slipping on his "
                "own ice.",
    "gale:1:5": "The necklace adds Intelligence to Fire Bolt and the gloves remove point-blank disadvantage - strong "
                "cantrip damage without spending slots.",
    "gale:2:1": "Scorching Ray beams build Arcane Acuity, so the next Fireball lands at a much higher DC; Spellcrux "
                "refunds the big slot.",
    "gale:2:2": "Spells light targets with Radiating Orb; Callous Glow adds radiant to every hit, which also spreads "
                "Reverberation and dazes attackers through the cloak.",
    "gale:2:3": "A flat-DC Charisma caster kit: helmet, shield and robe raise DC and cantrip damage, the rings turn "
                "thunder hits into Daze.",
    "gale:2:4": "Every cold hit leaves ice and frost and any condition adds more frost, locking groups down.",
    "gale:2:5": "Booming Blade is a weapon spell (Battlemage gloves) and deals thunder (Storm Scion hat): two Arcane "
                "Acuity sources at once; no shield so Bladesong stays up.",
    "gale:3:1": "Seven flat bonuses to DC and spell attack from staff, shield, hood, robe, cloak, gloves and ring; the "
                "Amulet of Greater Health protects concentration.",
    "gale:3:2": "Same DC stack, but Armour of Landfall gives Constitution-save advantage so the Amulet of the Devout "
                "can add +2 DC instead.",
    "gale:3:3": "Spellmight adds a d8 to each Scorching Ray beam and the staff's fire mode adds more fire damage; "
                "the Weave hood, cloak and robe raise spell attack to cover the gloves' penalty.",
    "gale:3:4": "Devout gives a second Destructive Wrath for a maximised Chain Lightning on wet targets; thunder gear "
                "turns the hits into Daze.",
    "gale:3:5": "Weapon hits feed Acuity and Rhapsody; the Band lets Gale cast enchantments as a bonus action after a "
                "hit, and Landfall keeps concentration safe.",
    # ---------------- Karlach
    "karlach:1:1": "Every throw adds Tavern Brawler Strength plus two d4 throw riders and acid; Misty Step and "
                   "Momentum find throwing angles, the elixir raises Strength twice over.",
    "karlach:1:2": "Three separate triggers keep Wrath up for extra damage, and the gloves' advantage covers the "
                   "Great Weapon Master penalty.",
    "karlach:1:3": "Shield and armour both stop crits and make melee attackers reel; with Bear rage resistances she "
                   "is very hard to kill, and the mace can revive her once.",
    "karlach:1:4": "Club and elixir give high Strength before the Pike is bought, so thrown objects and enemies hit "
                   "hard with Tavern Brawler.",
    "karlach:2:1": "Each throw carries lightning, the Elemental Cleaver die, doubled rage bonus and both throw "
                   "riders; Act 2 darkness triggers the shadow ring often.",
    "karlach:2:2": "Risky Ring advantage means more hits and crits; a crit on a humanoid paralyses it and Bloodlust "
                   "gives an extra action after a kill.",
    "karlach:2:3": "Reach plus advantage on reaction attacks, flat fire riders and guaranteed crits after kills feed "
                   "Great Weapon Master spikes.",
    "karlach:2:4": "Unarmoured Defence scales with Constitution; the bracers only add AC without armour.",
    "karlach:3:1": "Every Nyrulna throw adds a thunder blast on top of Tavern Brawler Strength, throw riders and acid; "
                   "the Helldusk pieces make her nearly immune to control.",
    "karlach:3:2": "Giantslayer doubles the Strength bonus, so Strength items count twice; crit immunity, "
                   "regeneration and damage reduction make her a wall.",
    "karlach:3:3": "Every rage gives temp HP and a psychic aura; high Constitution powers Unarmoured AC and the "
                   "garb's retaliation.",
    "karlach:3:4": "Piercing vulnerability doubles piercing hits; wider crit range, advantage and a guaranteed crit "
                   "after kills stack big crit turns.",
    "karlach:3:5": "Fire riders on the axe and gloves, the boots' teleport and Karlach's own fire resistance fit her "
                    "fire theme.",
    # ---------------- Lae'zel
    "laezel:1:1": "Invisibility from the pike gives advantage and crits on 19 to cover the Great Weapon Master "
                  "penalty; the armour makes her crit-immune in the front line.",
    "laezel:1:2": "Githyanki weapons add psychic damage only for a githyanki wielder; extra initiative and Brand the "
                  "Weak help her open on bosses.",
    "laezel:1:3": "Concentrating on Hold Person or Hunter's Mark adds psychic damage per hit, and conditions from "
                  "smites or trips trigger Arcane Synergy.",
    "laezel:1:4": "Two crit immunities, Reeling on hit and on miss, and a self-revive make her a front-line wall.",
    "laezel:2:1": "Reach plus advantage on Riposte and opportunity attacks; the Risky Ring keeps GWM swings landing "
                  "and Killer's Sweetheart chains a guaranteed crit.",
    "laezel:2:2": "Inside Shadow-Magic darkness the helmet crits on 19, the spear adds damage against obscured foes "
                  "and Hold Person concentration feeds the Conduit ring.",
    "laezel:2:3": "The glaive lights targets so Callous Glow adds radiant to every hit; radiant smites spread "
                  "Reverberation.",
    "laezel:2:4": "The Flawed Helldusk pieces from Dammon add fire to each of her many attacks; easy to assemble.",
    "laezel:3:1": "Strength 23 doubled by Giantslayer gives a huge flat bonus on every attack; helm and armour add "
                  "crit immunity, regeneration and damage reduction.",
    "laezel:3:2": "A little less raw damage than Giantslayer, but psychic and fire on every hit, charm immunity and "
                  "advantage on mental saves.",
    "laezel:3:3": "Weapon hits raise the Hold Person DC; the Band casts it as a bonus action after a hit, and "
                  "paralysed targets take auto-crit smites.",
    "laezel:3:4": "Champion's Improved Critical plus helmet and elixir lower the crit number again; Killer's "
                  "Sweetheart and advantage make crits very frequent.",
    "laezel:3:5": "Shield, resistant armour, regeneration and immunities make her almost impossible to bring down.",
    # ---------------- Shadowheart
    "shadowheart:1:1": "Every radiant tick (Sacred Flame, Guiding Bolt, Spirit Guardians, helm retaliation) sends a "
                       "radiant shockwave and stacks Reverberation; the mace's light blinds undead.",
    "shadowheart:1:2": "Every damaging spell gives Lightning Charges; water from the boots electrifies the field, the "
                       "ring protects her from it, the helm turns charges into temp HP.",
    "shadowheart:1:3": "One Mass Healing Word also blesses, protects and shields the whole party.",
    "shadowheart:1:4": "Concentrating gives Momentum to walk Spirit Guardians through packs; weapon swings add psychic "
                       "damage while concentrating.",
    "shadowheart:2:1": "Callous Glow makes every hit on a lit target deal radiant, Coruscation adds Radiating Orb per "
                       "spell, and the Luminous pieces spread it further - enemies miss constantly.",
    "shadowheart:2:2": "Callous Glow's radiant damage procs the thunder gloves on every spell instance; Reverberation "
                       "lowers saves and the ring and cloak daze.",
    "shadowheart:2:3": "Fight inside Shar's darkness: obscured gives advantage on saves, extra damage, a better crit "
                       "chance and AC.",
    "shadowheart:2:4": "Staff, shield, helm, robe and ring raise the save DC for Hold Person and Command before Act 3.",
    "shadowheart:3:1": "Hood, cloak and amulet add +5 DC, the amulet gives another Radiance of the Dawn, and the "
                       "radiant orb engine keeps working.",
    "shadowheart:3:2": "Destructive Wrath maximises Chain Lightning on wet targets; the staff gives a free spell and "
                       "the DC stack makes saves fail.",
    "shadowheart:3:3": "Constitution 23 and advantage protect concentration; regeneration, crit immunity, "
                       "displacement and damage reduction keep her up.",
    "shadowheart:3:4": "Path-flavoured weapons: the Selune spear gives Moonbeam and light; the Shar spear thrives in "
                       "darkness.",
    "shadowheart:3:5": "The healing gloves, rings and boots turn every heal into a buff; the amulet adds another "
                       "Preserve Life.",
    # ---------------- Wyll
    "wyll:1:1": "Every Eldritch Blast beam adds Lightning Charges for AC and lightning procs; lightning and Hex start "
                "Reverberation that later Daze rings exploit.",
    "wyll:1:2": "+2 to hit for Eldritch Blast early; the gloves remove point-blank disadvantage and darkness keeps the "
                "circlet's DC bonus on.",
    "wyll:1:3": "Both Mithral Ores make an uncrittable tank; concentration on Hex or Bless powers the psychic ring "
                "and acid adds to every swing.",
    "wyll:1:4": "Booming Blade and Hex trigger Arcane Synergy, adding Charisma to weapon damage a second time.",
    "wyll:2:1": "The amulet starts Reverberation, each later beam forces a CON save or Daze, and the cloak punishes "
                "attackers; weak against high-CON bosses.",
    "wyll:2:2": "Coruscation lights the target, Callous Glow adds radiant to every beam and the radiant damage keeps "
                "the Orb stacking.",
    "wyll:2:3": "Fire Bolt with the necklace and Elemental Affinity stacks Arcane Acuity, then Quickened Eldritch "
                "Blast and Hold Person land more often.",
    "wyll:2:4": "Advantage doubles crit chances, Killer's Sweetheart guarantees one, and a crit on a humanoid "
                "paralyses it for auto-crit smites.",
    "wyll:3:1": "Charisma is added twice per beam (Agonizing + Potent Robe); Risky Ring's advantage pays for "
                "Spellmight's -5 to get +1d8 per beam.",
    "wyll:3:2": "Crowd control version of the blaster: Reverberation and Daze on trash packs, weaker on bosses.",
    "wyll:3:3": "Fire spells stack Arcane Acuity, then Hold Monster and Fireball land; Mental Inhibition chains "
                "failed saves.",
    "wyll:3:4": "Hit, bonus-action Hold Person through the Band, then every hit on the paralysed target crits with "
                "smites; Helldusk adds fire and damage reduction.",
    "wyll:3:5": "Booming Blade triggers Arcane Synergy; the rapier's crit on 19 plus Hexblade's Curse makes crits "
                "common.",
    # ---------------- Dark Urge
    "darkurge:1:A1-1": "Open invisible, Assassinate crits the opener, and every kill re-cloaks the Durge through the "
                       "Mantle so each shot keeps advantage and Sneak Attack.",
    "darkurge:1:A1-2": "Advantage and crits on 19 from the pike make smites crit often; the diadem and conditions add "
                       "damage, the splint makes the Durge crit-immune, the Mantle chains invisibility.",
    "darkurge:1:A1-3": "Spells build Lightning Charges that power the armour, helm and shield; lightning and thunder "
                       "start Reverberation.",
    "darkurge:1:A1-4": "Each throw stacks two d4 riders and acid on Tavern Brawler; Frenzy kills re-cloak through the "
                       "Mantle for advantage without Reckless Attack.",
    "darkurge:1:A1-5": "Many unarmed hits a turn build Lightning Charges; speed items let the monk reach anything and "
                       "kills trigger invisibility.",
    "darkurge:2:A2-1": "Act 2 darkness keeps everyone obscured: the cowl crits on 19 and the ring adds damage; an "
                       "Assassinate crit paralyses humanoids and Killer's Sweetheart guarantees the next crit.",
    "darkurge:2:A2-2": "Darkness and the Act 2 gloom keep the Durge obscured, so the helmet crits on 19 and smite "
                       "dice double; Spellcrux refunds a top slot.",
    "darkurge:2:A2-3": "Lightning and thunder start Reverberation, the ring turns the next hit into Daze, and the "
                       "DC items make the saves fail.",
    "darkurge:2:A2-4": "The halberd's Strength frees ASIs for Charisma; the armour returns a Channel Oath and the "
                       "rings add crit smites.",
    "darkurge:2:A2-5": "Duelling style, the gloves and the Risky Ring make flourishes land; hits stack Acuity for "
                       "Hold Person, then smite the held target.",
    "darkurge:3:A3-1": "Double Strength damage plus crits on 19 (17 with Bhaal's blessing in the finale) double the "
                       "smite dice; the Band makes Hold Person a bonus action after a hit.",
    "darkurge:3:A3-2": "A hidden opener crits on 18-20 and Assassinate crits surprised foes anyway; Bhaalist Armour "
                       "doubles piercing damage near the Durge.",
    "darkurge:3:A3-3": "Nyrulna's piercing throws are doubled by the Bhaalist aura and each throw also blasts "
                       "thunder; the helmet gives an extra throw below half HP.",
    "darkurge:3:A3-4": "The rapier crits on 19 with a bonus-action attack; the Band turns a hit into a bonus-action "
                       "Hold Person for auto-crit smites.",
    "darkurge:3:A3-5": "Five DC from items for Chain Lightning, a free spell from the staff, and a second "
                       "Destructive Wrath from the amulet.",
}
