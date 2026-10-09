# Backing up and restoring the BG3 saves

Two scripts in this folder. Both refuse to run while Baldur's Gate 3 is open (`bg3.exe` / `bg3_dx11.exe`).
Neither ever deletes anything: files are copied, or moved aside into an archive folder.

## What gets backed up

| What | Live location | In the backup folder |
|---|---|---|
| All profiles and saves, profile `.lsf` files, `modsettings.lsx` | `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\PlayerProfiles\` | `PlayerProfiles\` |
| Installed mods (`.pak`) | `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Mods\` | `Mods\` |
| Script Extender folder (mod config, Lua, probe/scan files) | `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\` | `ScriptExtender\` |
| Script Extender settings | `D:\SteamLibrary\steamapps\common\Baldurs Gate 3\bin\ScriptExtenderSettings.json` | `ScriptExtenderSettings\` |

Files bigger than 50 MB in the Script Extender folder are skipped and listed (there are none today; the SE logs
go to `BuildAdvisor\se-logs\`, which is not part of the backup). Size today: about 3.0 GB (441 files).

## Back up (with BG3 closed)

```
bash LootAdvisor/tools/backup_saves.sh --dry-run    # shows what would be copied, copies nothing
bash LootAdvisor/tools/backup_saves.sh              # does it
```

The copy goes to `BuildAdvisor\backups\loot_pre_test_<date>\` (`_2`, `_3` ... if that name is taken - an
existing backup is never overwritten). It contains `manifest.json`: every file's path, size, SHA-256 and date,
plus where each part came from. After copying, the script reads the copy back and checks every file against the
manifest; only then is the folder given its final name (until then it is called `....incomplete`). The last line
says `VERIFIED OK` when all is well. It also prints the number of saves per profile and per campaign.

## Restore (with BG3 closed)

```
bash LootAdvisor/tools/restore_saves.sh backups/loot_pre_test_<date>            # shows the plan only
bash LootAdvisor/tools/restore_saves.sh backups/loot_pre_test_<date> --apply    # does it
```

Without `--apply` nothing is changed. With `--apply`:

1. Everything in `PlayerProfiles` and `Mods` that was not there at backup time (new test saves, extra mod paks,
   new `.bak` files ...) is **moved** to `BuildAdvisor\backups\loot_test_saves_<date>\`, keeping its folder path
   (for example `loot_test_saves_<date>\PlayerProfiles\Public\Savegames\Story\<save folder>\`).
2. Every backed-up file that is missing or different now is copied back from the backup. If a file was changed
   (for example `modsettings.lsx` or `profile8.lsf`), the changed version is moved into the same archive first,
   so it is kept too. Saves the game deleted by itself (old quick/autosaves it rotated out) come back this way.
3. The live folders are checked again: `PlayerProfiles` and `Mods` must now equal the backup exactly (every file,
   every folder, SHA-256), and every backed-up Script Extender file must match. The last line says `VERIFIED OK`.

`moved.json` in the archive lists everything that was moved and why. To look at a test save again later, move
its folder from the archive back into `...\PlayerProfiles\Public\Savegames\Story\`.

Extra files in the Script Extender folder (new scan/probe files) are left where they are and only listed.

Before changing anything, the restore checks that the backup files it needs still match the manifest; if one is
damaged it stops without touching the live folders.

## Notes

- Turn Steam Cloud off for BG3 before testing, otherwise test saves can come back from the cloud after a restore.
- Any save made after the backup counts as a test save and is moved aside on restore - including saves from
  normal play or from the helm bot (Tav) made in between.
- Options for testing on a copy: `--src-root`, `--se-settings`, `--dest-root` (backup) and `--live-root`,
  `--se-settings`, `--archive-root` (restore). `python test_backup_restore.py --work <scratch folder>` runs the
  full self-test on a fake tree.

## Kept campaigns (added 2026-10-08)
By default the restore leaves NEW save folders of the **Tav** campaign (the helm bot) where they are - the user chose
to keep them. Every other new save is still moved aside. `--keep-campaign <leader>` (repeatable) changes the list;
`--keep-campaign none` moves every new save aside. Tested on a scratch tree: a new Tav save stays, a new Ryzen save
is moved, and the check reports VERIFIED OK with the Tav save listed as a note.
