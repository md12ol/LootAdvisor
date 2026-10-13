# Contributing to Loot Advisor

Setup, building and testing in the game for both mods: see
[CONTRIBUTING in BG3Tools](https://github.com/md12ol/BG3Tools/blob/main/CONTRIBUTING.md) (`sh setup.sh` there clones
the repositories side by side and installs the pre-push hook).

## Repository layout
| Path | What |
|---|---|
| `LootAdvisor/` | the mod source as in other BG3 mod repositories: `LootAdvisor/Mods/LootAdvisor/` (meta.lsx, Lua, GUI, journal markers, the shippable Sets page); `Public/` and `Localization/` next to it when the mod needs them. This folder is what gets packed |
| `package/` | the hand-made part of the player package: `INSTALL.md` and `Media/` (banner, thumbnail, marks, screenshots) |
| `dist/` | local builds (gitignored): `LootAdvisor.pak` and the assembled player package `dist/LootAdvisor/` |
| `.luarc.json` | Lua language server settings (Script Extender API, see [Lua tooling](#lua-tooling)) |
| `nexus_description.bb` | the Nexus Mods page text (BBCode) |
| `LICENSE` | MIT |
| `tools/` | game-file parsers ([`tools/PARSERS.md`](tools/PARSERS.md)), the item/set pipeline, page builders, save backup ([`tools/BACKUP_RESTORE.md`](tools/BACKUP_RESTORE.md)), the [optimizer and gauntlet](#gauntlet-and-optimizer) |
| `tests/` | regression suite and optimizer / gauntlet tests (see [Tests](#tests)) |
| `data/research/` | build research notes the pipeline reads |
| `design/` | design generators |

## Game data is never in this repository
Extracted game files (item texts, loca, stats, level data, icons/textures) are not committed. They are
rebuilt on your machine from your own BG3 install (read-only on the game folder). The game folder is taken from
the environment variable `BG3_DIR` if set, otherwise the first of `D:\SteamLibrary\steamapps\common\Baldurs Gate 3`
and `C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3` that exists (`tools/game_paths.py`). Needs
Python 3.12 with `lz4`, `zstandard`, `Pillow` and `lupa` (`pip install lz4 zstandard pillow lupa`).

### Rebuild (in this order, from the repo root)
Checked end to end from empty `data/cache`, `data/items_all` and `data/scores` (about 3 minutes).
```bash
python tools/build_cache.py            # data/cache/: loca, root templates, level item index
python tools/stats.py --dump data/cache/stats_resolved.json   # resolved stats (all later steps read it)
python tools/class_progressions.py     # data/cache/class_progressions.json
python tools/global_items.py           # global item placements -> data/cache
python tools/characters.py             # NPC placements -> data/cache
python tools/extract_weapons.py && python tools/extract_armour.py && python tools/extract_accessories.py
python tools/extract_sources.py        # data/items_all/ (sources, levels, recipes; format: data/items_all/SCHEMA.md)
python tools/level_links.py && python tools/entrances.py   # teleporters, zones + entrances (needs items_all/levels.json)
python tools/match_research.py         # research names -> game ids
python tools/score_items.py            # data/scores/ (+ lua/LootData.lua)
python tools/gen_mod_data.py           # derived data into LootAdvisor/Mods/LootAdvisor
python tools/build_sets_ship.py        # LootAdvisor/Mods/LootAdvisor/Page/Sets.html + ShipManifest.lua (no game art/text inside)
python tests/run.py                    # regression suite
```
`python tools/build_sets_artifact.py` builds the private preview page `artifact/sets.html` (it embeds game icons, so
it is gitignored too).

Two of the files the Rebuild writes are tracked and carry the build time (`Page/Sets.html` and `ShipManifest.lua`'s
`version`), so a Rebuild always shows them as changed; commit them only with a change that needs them.

## Tests
```bash
python tests/run.py [--mutate] [--ci]     # regression suite; --mutate proves every check can fail, --ci = no game data
python tests/test_optimizer.py [--ci] [--mutate]   # optimizer maths (CI) + checks of its output (run the optimizer first)
python tests/test_gauntlet.py [--mutate]  # gauntlet harness without the game; --mutate proves each test can fail
python tools/leak_scan.py                 # no game text in shipped files
```
CI runs the `--ci` parts; the pre-push hook from BG3Tools runs the full suite. How to add a check: CONTRIBUTING in
BG3Tools, "Extending the mods".

## Gauntlet and optimizer
The **optimizer** (`tools/optimizer/`) searches an "Optimized" set per origin, build and act under the same scoring
model as the research sets. It needs the Rebuild outputs and writes only to `tools/optimizer/.cache/` (gitignored):
```bash
python tools/optimizer/run.py --jobs 8      # all origins, builds, acts (--only gale[:build[:act]] for one)
python tests/test_optimizer.py              # checks its output against the game data
```
The **gauntlet** (`tools/gauntlet/`) measures gear sets in the running game: it takes a character levelled to the
build (a test save per build; `--respec emulated` rebuilds the sheet with boosts instead), spawns the items and
enemies, fights scripted rounds and records damage and survival. It changes the loaded save, so use a test save and
never save afterwards. It talks to the game through Loot Advisor's dev eval hook
(`"Dev": true` in `LootAdvisor_settings.json`; setup in BG3Tools `tools/testing/README.md`, whose `cheat.py` gives the
same engine shortcuts for other tests).
```bash
python tools/gauntlet/engine.py load        # gauntlet.lua + gauntlet_test.lua (server), the F9 window gauntlet_ui.lua
python tools/gauntlet/engine.py probe       # API check, party, position, difficulty
# manual runs: build the catalogue, then press F9 in the game and pick build, set, act and scenario
python tools/gauntlet/catalog.py --optimizer tools/optimizer --optimized tools/optimizer/.cache/optimized.json
# scripted runs: pick pairs (optimizer set vs research set), write specs, run, report
python tools/gauntlet/pairs.py --optimizer tools/optimizer --optimized tools/optimizer/.cache/optimized.json     --control --select shadowheart:lightcleric:3 --out pairs.json
python tools/gauntlet/plan.py --optimizer tools/optimizer --pairs pairs.json --out specs.json
python tools/gauntlet/run.py specs.json --results results.jsonl --char UUID
python tools/gauntlet/run.py --report results.jsonl --specs specs.json --md report.md
# one set on the build's own Build Advisor plan (no tuned respec), side a only
python tools/gauntlet/pairs.py --optimizer tools/optimizer --optimized tools/optimizer/.cache/optimized.json     --single astarion:thx:3:1 --plain --out one.json
```

### The test popup and the test mod
F9 opens the test popup on top of the window: mode **Manual** (you play the character's turns) or **Automatic** (the
plan plays them), **Start**, Stop, the status (Ready, Setting up, Fighting, Result, Setup failed) and the last
result. Start runs the same setup as a scripted run: hit points, resources, cooldowns, concentration and carried
statuses reset, the set and the build checked field by field (also: no story or mood status with a roll or damage
effect and no tadpole power may be on, since the build, the set, the planned actions and the consumables give no such
bonus; remove them from the test save once, the check lists any it finds and the run record keeps the list), the consumables prepared, the enemy at its arena spot with its forced stats.
The enemy turns hostile only once that check has passed: a mismatch is shown in the popup and the fight does not
start. Both modes write the same run record (with `test_mode` manual or automatic) and per-hit log. The mode starts
as Manual after every load. A test save may keep its own boss standing in the arena (`--boss UUID`): its forced stats
do not survive a reload, so every Start forces them again and the setup check reads them back.

What Start runs is the test file `LootAdvisor_gauntlet_test.json` in the Script Extender folder (one side of a spec):
```bash
python tools/gauntlet/engine.py arm specs.json --pair 0 --side a --arena house_of_hope --char UUID [--boss UUID]
python tools/gauntlet/engine.py disarm                     # remove it
python tools/gauntlet/engine.py mode automatic             # what a script does first after loading
python tools/gauntlet/engine.py start                      # the popup's Start
```
`run.py` goes through the same Start: it sets Automatic right after loading, writes each run's request and spec to
the test file and presses Start. A side runs until it has `--repeats` valid runs (default 4), and every run's turn
list (round by round: the attack or spell, its target, its result) is written to `<results>_turns/` for a person to
replay the run by hand. `--report` compares each set with the model's boss scenario part by part (attacks per round,
hit rate, critical hits, damage per landed hit, the riders, then damage per round), flags a part outside +-10%, and
gives one 95% interval of the mean of the run means per side and per pair; runs played by hand are listed apart. The
earlier method (early stopping, the control gate, two lanes, the day-score report) stays behind `--v1`.

The **test mod** loads the harness with the save, with no eval hook: a developer-only pak of its own
(`LootAdvisorGauntletTest`, source in `tools/gauntlet/testmod/`), never part of the Loot Advisor pak or download (the
tests check both). It does nothing in a save the test file does not name (its character in the party, the party in
its arena's level); in the test save it loads the harness and offers F9.
```bash
python tools/gauntlet/testmod.py build      # dist/LootAdvisorGauntletTest.pak (the harness files packed in)
python tools/gauntlet/testmod.py install    # game closed: copies the pak and enables this mod only
python tools/gauntlet/testmod.py remove     # disables it again
```

### The earlier method (`--v1`)
Two lanes, `--repeats` with early stopping and the control gate below belong to the earlier method, kept for its
records (`--v1`; `--lanes` implies it). What follows on rolls, validity and the setup check applies to both.
```bash
# both sides of a pair at once: two party members levelled to the same build, two lanes (arenas.json)
python tools/gauntlet/engine.py survey undercity_lanes
python tools/gauntlet/run.py specs.json --results results.jsonl --lanes undercity_lanes --char UUID_A --char-b UUID_B
# one save per side (one character per build): the same side of two pairs at once, then the other save
python tools/gauntlet/run.py specs.json --results results.jsonl --sides a --repeats 2 --lanes undercity_lanes --chars laezel=UUID,shadowheart=UUID
```
While a run is active nothing else may use the eval hook (the run's own status reads would lose answers): the run
holds a lock file and `engine.py` refuses other commands until it ends.

**Two lanes** run both sets of a pair at the same time in two separate combats: each lane has its own character, set,
enemies and arena spot. Each lane's enemies get their own faction, hostile to that lane's character and neutral to the
other lane; the lanes lie farther apart than the farthest spell of either set reaches (from anywhere inside one lane
to anywhere inside the other, plus a margin), the sides swap lanes and the first lane alternates every repeat. A hit
from one lane on the other, a shared combat, or an enemy hostile to the other lane's character fails the run. With one
character, or lanes too close for the pair's spells, the sides run one after the other. When each save holds one
character per build, the lanes take the same side of two different pairs at once instead (`--chars`), under the same
spacing rule.
`--repeats` counts the usable runs already in `--results` for the same pair and set, so the side run from the second
save sees the first save's runs and a pair is not run again once it is decided. A pair is decided when the 95%
interval of the ratio of its two sides' damage per round excludes 1 or lies within the control tolerance; rounds are
compared by their number, since a round's damage depends on its number (Action Surge, item spells, slots running out)
far more than on the dice. A side whose first run failed for a reason every run would meet (a setup mismatch at the
start, a combat that ended) is not repeated; the results file says why.
The gauntlet Lua is not part of the pak: `engine.py load` copies it into the Script Extender folder and runs it
through the hook. Loading a save resets the game's Lua state, so run `engine.py load` again after every load.
Scripted runs park the rest of the party 40 m away and set every party character's reactions so the game never asks
("Use reaction?" would stop a scripted turn): the reactions the build and the set grant (`plan.reactions`, written by
`plan.py`) fire on their own; every other reaction the character has (racial, tadpole, its own class and items) is
off. The player's own reaction settings are put back when the run ends; manual runs never change them. A prompt that
still opens in a scripted turn ends the run and is listed under `reaction_misses` in the record. Reactions are set this
way before every fight (an "ask" answer becomes "never"), also for the character's summon, and a party member left
holding a turn outside the fight has it ended at the start and after every round (an open party turn stops the next
round and the refill of the character's resources).

Scripted casts roll like a player's: an attack can miss or score a critical hit, a save spell gets its saving throw,
and what hangs on the roll applies (Sharpshooter's and Great Weapon Master's +10, Hunter's Mark, Sneak Attack). The
game queues a script's casts with an option that skips every roll; the harness takes that one option off the queued
casts of the character and its summons just before the game reads them, and leaves every other option (the cast
still does not move the character or check its resources: the harness moves it and pays the costs itself). A missed
attack is a confirmed cast like a hit: the round is not idle and nothing is retried; each cast's outcome (hit, critical
hit, miss) is in the record, and every hit row carries its natural roll, total and the AC or DC it was rolled against.
`run.py --no-real-rolls` runs the older way (every attack hits, no saves) for comparison. Every run record says which
in `real_rolls`; results from runs without rolls (records without the field) are not comparable with rolled ones, so
`--repeats` and `--report` count only runs of the kind asked for.

Each turn is planned from the resources the character has at that moment (an upcast falls back to a lower slot, then
the base spell, then the cantrip; an item spell is used only when it can be paid), and a scripted action counts as done
only when the game shows it (a cast event, damage to its target, or its cost spent); otherwise it is logged as failed
and its fallback runs. A run is recorded as invalid, with the causes, when it ends early (the character's turn never
came after the recovery attempt, the combat ended, the prep timed out, ...), a round passes without a confirmed action,
or the character casts something outside its plan. Such a run ends as soon as it is known to be invalid: a setup
mismatch before round 1, a round without a confirmed action or with a refused cast after that round. The run ends as
the last round's turn is released; damage taken is counted per enemy turn fought (one before round 1 included). The
enemies are reset to 99% of their hit points at each of the character's turns, so effects that need a hurt target
work while "below half" and kill effects do not. Before the fight every field of the setup is read back from the game
and compared with the plan (items, proficiency as the game judges it for each item, the character's own classes,
subclasses and feats, abilities, hit points, spells, slots, resources, buffs, reactions, enemies), and so are the
effects the model credits: toggled passives such as Great Weapon Master's "All In" in the state the model assumes (prep
sets them), every worn item's equip passives, statuses and unconditional boosts, the elixir's statuses, the weapons'
dice, the item spells in the book and ready, no concentration or status left over from an earlier run (prep ends and
removes them), and enemies that can be critically hit and carry no status; one mismatch fails the run. A rider the
plan relies on (Hunter's Mark on the boss, Dread Ambusher's status) missing after its turn fails it too, unless the
rider's own cast missed; riders that hang on a hit (Hunter's Mark's die, Sneak Attack) are counted over landed hits
only (`hit_riders` in the record). The
character's summon attacks the boss on its own turn and its damage counts for the set. Every hit is recorded with its
spell, flags (hit, miss, critical) and the target's statuses. `run.py --report` leaves invalid runs out, and marks the whole report INVALID when a control pair differs in
the game by more than `--control-tol` (default 15%). A control pair is two sets the model rates alike in damage and in
damage taken (AC, hit points, saving throws, resistances, damage reduction; damage per round and damage taken within
5%): `pairs.py --find-control char:build:act` searches for them, `--control` adds the chosen one.
Each side of a pair names its test plan (`--select char:build:act:N` compares with research set N): the optimizer tunes
ability scores, feats and fighting styles to each set, the test character is respecced to that plan, and `plan.py`
builds the expected sheet and the model's numbers from the same respec.
The round plan follows the model's decisions for the boss fight: a buff item spell (an extra action, weapon dice) is
cast when the model finds it worth the action it takes, with the extra action's attacks while its status is on; a
Battle Master whose every attack has Advantage keeps the superiority dice for Riposte instead of Trip; the off-hand
weapon attacks in a free bonus action, Great Weapon Master's bonus attack follows a critical hit, a caster spends its
lower slots on spells worth more than its cantrip and holds a damage zone when its ticks beat a nuke. An item action
replaces planned actions only when it is worth more than they are, and Destructive Wrath goes to the item spell it
adds most to.

## Build and install
The pak builder is shared by all mods and lives in the sibling repository
[BG3Tools](https://github.com/md12ol/BG3Tools), checked out next to this one (`../BG3Tools`):
```bash
python ../BG3Tools/tools/build_pak.py LootAdvisor     # -> dist/LootAdvisor.pak + the player package dist/LootAdvisor/
python ../BG3Tools/tools/install_mods.py              # copies the paks into the game and enables them
python ../BG3Tools/tools/ci_release.py check LootAdvisor   # what CI runs: build, zip the package, check it against INSTALL.md
```
Every build assembles the player package `dist/LootAdvisor/` from scratch: the pak, `INSTALL.md` and `Media/` from
`package/`, `Page/` from `LootAdvisor/Mods/LootAdvisor/Page`, and `Handbook.html` generated by
`../BuildAdvisor/docs_site/build_player_handbook.py`. See `../BG3Tools/tools/release_files.py`. Local builds are
also archived in `../BG3Tools/builds/` (`python ../BG3Tools/tools/builds.py list`).
Some tools read Build Advisor's build list from the sibling repository `../BuildAdvisor`.

### Lua tooling
`.luarc.json` configures [Lua Language Server](https://luals.github.io/) (the VS Code "Lua" extension) for Script
Extender's Lua 5.4 and its globals. For completion of `Ext.*`, `Osi.*` and the entity types, fetch Script Extender's
IDE helpers ([`ExtIdeHelpers.lua`](https://github.com/Norbyte/bg3se/blob/main/BG3Extender/IdeHelpers/ExtIdeHelpers.lua)
from the bg3se repository) into `.ide/`, which `.luarc.json` already lists as a library:
```bash
curl -L --create-dirs -o .ide/ExtIdeHelpers.lua https://raw.githubusercontent.com/Norbyte/bg3se/main/BG3Extender/IdeHelpers/ExtIdeHelpers.lua
```
`.ide/` is gitignored: the helpers are Script Extender's own file under its own license, so they are not copied here.

The paks contain textures we recoloured from the game's own frame and marker textures (Larian's modding terms; the
mod is free).

## Branches, commits and pull requests
- **One branch per task**, named after its topic (`ci-setup`, `sets-page-header`, ...), cut from `main`. Nobody
  commits to `main` directly: it is protected and only takes pull requests.
- **Commits and PR titles use [Conventional Commits](https://www.conventionalcommits.org/)**: `feat:`, `fix:`,
  `docs:`, `chore:`, `refactor:`, `test:`, `ci:` (`feat!:` for a breaking change). A commit message is a subject line
  plus at most one body line. No co-author, "generated with" or other attribution lines.
- Open a pull request to `main` (`gh pr create`); the CI checks (`lint`, `tests`, `pr-title`) must be green. CI checks out the sibling
  repositories side by side and uses their branch of the same name when it exists, else `main`.
- Merge with **"Create a merge commit"** (`gh pr merge --merge`, i.e. `--no-ff`); squash and rebase merges are off so
  the branch history stays readable. The PR title becomes the merge commit subject.
- Tests that need the game's data run locally only, in the pre-push hook (see CONTRIBUTING in
  [BG3Tools](https://github.com/md12ol/BG3Tools)); it runs the full suite before every push.
