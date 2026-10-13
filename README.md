# Loot Advisor (BG3 mod)

> **Spoiler warning:** Loot Advisor names items, where they are and who carries them, and its notes reveal story outcomes (who can die, which side you take, endings).

Shows, for every origin character and build, the best items per slot and act: a rainbow frame and an extra tooltip
line on recommended items, map markers at their spots, an **F6** list with direction and distance, and a local
**Sets page** (full loadouts for every origin, act by act) that follows the running game.

**Made for Build Advisor's builds.** The sets are made for the builds of
[Build Advisor](https://github.com/md12ol/BuildAdvisor). Any other character (Halsin, Jaheira, Minsc, Minthara, a
custom Tav, a hireling, or an origin respecced into a class mix no build has) gets the recommendations of the closest
Build Advisor build: most alike in class levels, then subclass, main ability, caster type and weapon style. The F6
list names that build and how alike it is, and the item tooltips say the pick is for the closest build. Build
Advisor's window shows the sets of the build picked there when both mods are installed.

## Requirements
- Baldur's Gate 3 (Patch 8).
- [BG3 Script Extender](https://github.com/Norbyte/bg3se). It is a separate project and is not included;
  [BG3 Mod Manager](https://github.com/LaughingLeader/BG3ModManager) installs it in one click.

Item frames and map painting (and the tooltip lines) need
Script Extender v33 or newer; on v32 the F6 list, the map markers in the
game's own style and the Sets page work. Until v33 is a normal release, get it from the Devel channel: create a file
`ScriptExtenderUpdaterConfig.json` in the game's `bin` folder containing `{"UpdateChannel": "Devel"}`,
then start the game once. Delete that file to go back to normal releases.

## Install
Download `LootAdvisor-X.Y.Z.zip` from the [Releases](https://github.com/md12ol/LootAdvisor/releases)
page (or the mod's Nexus Mods page). It holds the built `LootAdvisor.pak`, [`INSTALL.md`](package/INSTALL.md),
`Handbook.html` (the player handbook, works offline), `Page/Sets.html` and `Media/` (banner, thumbnail, logo marks,
screenshots). Built paks are not committed to this repository.

Install with BG3 Mod Manager: install Script Extender (*Tools > Download and Extract the Script Extender*), drag
`LootAdvisor.pak` into the mod manager, move Loot Advisor to the active mods, then *Save Load Order* and *Export Load
Order to Game*. [`INSTALL.md`](package/INSTALL.md) has the steps, installing by hand and uninstalling.

**Linux and Steam Deck (Proton):** not tested yet. [`INSTALL.md`](package/INSTALL.md#linux-and-steam-deck-untested)
has a *Linux and Steam Deck (untested)* section: the Script Extender launch option, where the game's folders are
inside the Proton prefix and how to open the Sets page. Reports are welcome in
[#80](https://github.com/md12ol/LootAdvisor/issues/80).

## How to use it
- Items the advisor recommends get a rainbow frame and an extra tooltip line; their spots are marked on the map.
- **F6** opens the list of recommended items with direction and distance, including items that have no fixed spot.
- **The Sets page:** load a save once. The mod writes the live page to
  `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor\Sets.html` (the Script Extender console
  prints the path; **F6**, then **Open Sets page**, shows it too). Open it in Chrome, Edge or Firefox and bookmark it:
  it follows the running game by itself.

`Handbook.html` in the download explains every sign in the game, the F6 list and the Sets page.

## Settings
Settings live in `LootAdvisor_settings.json` in the Script Extender folder
(`%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\`). The mod re-reads the file every few seconds;
only keys you want to change need to be in it.

| Key | Default | Meaning |
|---|---|---|
| `Enabled` | `true` | Master switch. `false` hides all markers, restores frames and tooltip texts. |
| `Hotkey` | `"F6"` | Key for the item list. |
| `Frames`, `Markers`, `Tooltips` | `true` | Rainbow frames on items, map markers, the "why" text in item tooltips. |
| `Arrows` | `5` | How many off-screen markers keep a rainbow arrow. |
| `MarkerFilter` | `"all"` | Whose items get map markers: `"all"`, `"party"` or `"selected"`. The F6 list sets it. |
| `Page` | `true` | `false` stops writing the Sets page. |

The handbook, chapter "Settings and the dev toggle", lists every key.

## Known limits
- Scored builds are Build Advisor's builds for the origins; every other character gets the closest of those builds,
  named in the F6 header.
- Some items have no fixed spot (quest rewards, boss drops, forge results) and appear in the F6 list only.
- Map markers may be stored in a save made while they were shown; removing the mod from a save is not tested yet
  (see the uninstall steps in `INSTALL.md`).
- Controller mode and the low-resolution interface are not tested. Linux and Steam Deck are not tested.
- Advice texts are English. Item names and game texts on the Sets page follow your game language.
- In multiplayer only the host writes the Sets page.

## Support
Bugs and questions: [open an issue](https://github.com/md12ol/LootAdvisor/issues). Say which version of Loot Advisor
and of Script Extender you run, and what the F6 header shows for the character.

## Developing
Repository layout, rebuilding the game data, tests, the gauntlet and optimizer, building and contributing:
[`CONTRIBUTING.md`](CONTRIBUTING.md). How a version is released: [`RELEASING.md`](RELEASING.md). Licence: MIT
([`LICENSE`](LICENSE)).
