# Loot Advisor (BG3 mod)

Shows, for every origin character and build, the best items per slot and act: a rainbow frame and an extra tooltip
line on recommended items, map markers at their spots, an **F6** list with direction and distance, and a local
**Sets page** (full loadouts for every origin, act by act) that follows the running game.

**Players:** everything you need is in [`LootAdvisor/`](LootAdvisor/) - the built `LootAdvisor.pak` and
[`INSTALL.md`](LootAdvisor/INSTALL.md).

## Repository layout
| Path | What |
|---|---|
| `LootAdvisor/` | install folder: `LootAdvisor.pak` + `INSTALL.md` (the pak is refreshed by every build, see below) |
| `Mods/LootAdvisor/` | the mod source (Lua, GUI, the shippable Sets page) - this is what gets packed |
| `Mods/LootAdvisorSpike/` | the map-marker spike mod (test only) |
| `tools/` | game-file parsers ([`tools/PARSERS.md`](tools/PARSERS.md)), the item/set pipeline, page builders, save backup ([`tools/BACKUP_RESTORE.md`](tools/BACKUP_RESTORE.md)) |
| `tests/` | regression suite: `python tests/run.py` (and `--mutate` to prove every check can fail) |
| `data/research/` | build research notes the pipeline reads |
| `design/`, `spike/` | design generators and the marker spike sources |

## Game data is never in this repository
Extracted game files (item texts, loca, stats, level data, icons/textures, 3D models) are not committed. They are
rebuilt on your machine from your own BG3 install (read-only on the game folder; default path
`D:\SteamLibrary\steamapps\common\Baldurs Gate 3`, see `tools/pak.py` `GAME_DATA`). Needs Python 3.12 with
`lz4`, `zstandard`, `Pillow` and `lupa` (`pip install lz4 zstandard pillow lupa`).

### Rebuild (in this order, from the repo root)
```bash
python tools/build_cache.py            # data/cache/: loca, resolved stats, templates, level item index
python tools/class_progressions.py     # data/cache/class_progressions.json
python tools/global_items.py           # global item placements -> data/cache
python tools/characters.py             # NPC placements -> data/cache
python tools/region_exits.py && python tools/level_links.py && python tools/entrances.py   # zones, teleporters, exits
python tools/extract_weapons.py && python tools/extract_armour.py && python tools/extract_accessories.py
python tools/extract_sources.py        # data/items_all/ (format: data/items_all/SCHEMA.md)
python tools/match_research.py         # research names -> game ids
python tools/score_items.py            # data/scores/ (+ lua/LootData.lua)
python tools/gen_mod_data.py           # derived data into Mods/LootAdvisor
python tools/build_sets_ship.py        # Mods/LootAdvisor/Page/Sets.html + ShipManifest.lua (no game art/text inside)
python tests/run.py                    # regression suite
```
`python tools/build_sets_artifact.py` builds the private preview page `artifact/sets.html` (it embeds game icons, so
it is gitignored too).

## Build and install
The pak builder is shared by all mods and lives in the sibling repository
[BG3Tools](https://github.com/md12ol/BG3Tools), checked out next to this one (`../BG3Tools`):
```bash
python ../BG3Tools/tools/build_pak.py LootAdvisor     # -> ../BG3Tools/dist/LootAdvisor.pak AND LootAdvisor/LootAdvisor.pak
python ../BG3Tools/tools/install_mods.py              # copies the paks into the game and enables them
```
Every build copies the fresh pak into the `LootAdvisor/` install folder, so the committed pak matches the source.
Some tools read Build Advisor's build list from the sibling repository `../BuildAdvisor`.

The paks contain textures we recoloured from the game's own frame and marker textures (Larian's modding terms; the
mod is free).
