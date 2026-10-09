# Installing Loot Advisor

This folder holds only what you need to play: `LootAdvisor.pak` and this file.

## Requirements
- Baldur's Gate 3 (Patch 8).
- [BG3 Script Extender](https://github.com/Norbyte/bg3se) v20 or newer. BG3 Mod Manager can install it for you.

## Install with BG3 Mod Manager
1. Install Script Extender (BG3 Mod Manager: *Tools > Download and Extract the Script Extender*).
2. Drag `LootAdvisor.pak` into BG3 Mod Manager (or *File > Import Mod*).
3. Move Loot Advisor to the active mods list, then *Save Load Order* and *Export Load Order to Game*.

## Install by hand
1. Install Script Extender.
2. Copy `LootAdvisor.pak` to `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Mods\`.
3. Enable it in the load order (a mod manager is the safe way to edit `modsettings.lsx`).

## Where to find it in the game
- Items the advisor recommends get a rainbow frame and an extra tooltip line; their spots are marked on the map.
- **F6** opens the list of recommended items with direction and distance, including items that have no fixed spot.
- **The Sets page:** load a save once. The mod writes the page to
  `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor\Sets.html` (the Script Extender console
  prints the path). Open it in Chrome, Edge or Firefox and bookmark it: it follows the running game by itself.
  The page builds its art and texts from your own game install; no game files ship with the mod.

## Uninstall
Disable or remove Loot Advisor in the mod manager (or delete the pak from the Mods folder).
