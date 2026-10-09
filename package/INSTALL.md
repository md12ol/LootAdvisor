# Installing Loot Advisor

## What is in this folder
| File | What it is |
|---|---|
| `LootAdvisor.pak` | The mod. The only file the game needs. |
| `INSTALL.md` | This file. |
| `Handbook.html` | The player handbook: install, every sign in the game, the F6 list, the Sets page, settings, FAQ. Open it in any browser; it works offline. |
| `Page/Sets.html` | A copy of the Sets page. Opened from here it tells you to load a save once and shows the path of the live page the mod writes (see below). |
| `Media/` | Banner, thumbnail, logo marks and screenshots, for sharing or a mod page. The game does not need them. |

`Media/` holds:
- `LootAdvisor_banner_1920x1080.png`, `LootAdvisor_thumbnail_1024.png`
- `LootAdvisor_mark_128.png`, `LootAdvisor_mark_64.png`, `LootAdvisor_wordmark.png`
- `Screenshot_1_world_map_marker.jpg`, `Screenshot_2_minimap_marker.jpg`, `Screenshot_3_tooltip_better_on.jpg`,
  `Screenshot_4_tooltip_best_pick.jpg`, `Screenshot_5_item_list_F6.jpg`, `Screenshot_6_frames_and_trader_marker.jpg`

## Requirements
- Baldur's Gate 3 (Patch 8).
- [BG3 Script Extender](https://github.com/Norbyte/bg3se). It is a separate project and is not included;
  [BG3 Mod Manager](https://github.com/LaughingLeader/BG3ModManager) installs it in one click.
- **Item frames and map painting need Script Extender v33 or newer** (also the tooltip lines). On v32 the rest of
  Loot Advisor works: the F6 list, the map markers in the game's own style and the Sets page.
  Until v33 is a normal release, get it from the Devel channel: create a file
  `ScriptExtenderUpdaterConfig.json` in the game's `bin` folder containing `{"UpdateChannel": "Devel"}`,
  then start the game once. Delete that file to go back to normal releases.

## Install with BG3 Mod Manager
1. Install Script Extender: in BG3 Mod Manager choose *Tools > Download and Extract the Script Extender*.
2. Drag `LootAdvisor.pak` into BG3 Mod Manager (or *File > Import Mod*).
3. Move Loot Advisor to the active mods list, then *Save Load Order* and *Export Load Order to Game*.
4. Start the game. If a *Mod Verification* dialog lists Loot Advisor, tick it and choose Start Game.

## Install by hand
1. Install Script Extender.
2. Copy `LootAdvisor.pak` to `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Mods\`.
3. Enable it in the load order (a mod manager is the safe way to edit `modsettings.lsx`).

## Where to find it in the game
- Items the advisor recommends get a rainbow frame and an extra tooltip line; their spots are marked on the map.
- **F6** opens the list of recommended items with direction and distance, including items that have no fixed spot.
- **The Sets page:** load a save once. The mod writes the live page to
  `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor\Sets.html` (the Script Extender console
  prints the path). Open it in Chrome, Edge or Firefox and bookmark it: it follows the running game by itself.
  The page builds its art and texts from your own game install; no game files ship with the mod.

## Viewing the Sets page next to the game
- Open it from the game: press **F6**, then **Open Sets page** in the item list. Or open your bookmark of the page.
- Two monitors: play in *Borderless Window* (game Video settings) and keep the browser on the second monitor.
- One monitor: use the Steam overlay browser (**Shift+Tab**, then the web browser) and open the page path there, or
  switch to the browser with Alt+Tab (smoothest in *Borderless Window*).

## Uninstall
Set `"Enabled": false` in `LootAdvisor_settings.json` (Script Extender folder) and save once, so no map markers are
stored in the save; then disable or remove Loot Advisor in the mod manager (or delete the pak from the Mods folder).
Details: `Handbook.html`, chapter *Requirements and install*.
