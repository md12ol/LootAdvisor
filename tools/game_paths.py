"""Where the game and its user folder are on this machine (no third-party imports).

GAME_DIR  - the BG3 install folder: env BG3_DIR if set, else the first common Steam location that exists.
GAME_DATA - GAME_DIR/Data (the paks the parsers read, read-only).
USER_DIR  - %LOCALAPPDATA%/Larian Studios/Baldur's Gate 3 (saves, Mods, Script Extender folder).
"""
import os

_STEAM_DIRS = [r"D:\SteamLibrary\steamapps\common\Baldurs Gate 3",
               r"C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3"]

GAME_DIR = os.environ.get("BG3_DIR") or next((d for d in _STEAM_DIRS if os.path.isdir(d)), _STEAM_DIRS[0])
GAME_DATA = os.path.join(GAME_DIR, "Data")
USER_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Larian Studios", "Baldur's Gate 3")
