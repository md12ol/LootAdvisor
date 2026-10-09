"""Put BG3 saves/profiles, Mods and Script Extender config back exactly as they were in a backup.

    python restore_saves.py <backup dir>           # DRY RUN: only shows the plan (default)
    python restore_saves.py <backup dir> --apply   # really does it

What --apply does (it never deletes anything):
  (a) every file/folder in the live PlayerProfiles and Mods that is NOT in the backup (new test saves, extra mod
      paks, ...) is MOVED into <backups>/loot_test_saves_<date>[_n]/<component>/<same relative path>;
  (b) every backed-up file that is missing live, or whose live copy differs (SHA-256), is copied back from the
      backup; a differing live copy is first moved into the same archive (so it is kept too);
  (c) the live folders are re-hashed: PlayerProfiles and Mods must equal the backup exactly, the Script
      Extender files must match (extra Script Extender files are left in place and only listed).
New save folders of the campaigns named with --keep-campaign (default: Tav, a campaign
kept for automated tests) are left in place in (a) and in the check (c); --keep-campaign none moves every new save aside.
Refuses while bg3.exe / bg3_dx11.exe is running. The live folders default to where the backup was taken from
(recorded in manifest.json); --live-root / --se-settings override that (for testing).
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bg3_saves_common import (COMPONENTS, SAVE_RE, copy_hashed, human, key, lp, refuse_if_running,
                              save_counts, sha256_file, today, unique_dir)


def kept_save(name, rel, keep):
    """True if rel is (inside) a save folder <profile>/Savegames/Story/<leader>-... of a kept campaign."""
    if name != "PlayerProfiles" or not keep:
        return False
    parts = rel.split("/")
    if len(parts) < 4 or parts[1] != "Savegames" or parts[2] != "Story":
        return False
    m = SAVE_RE.match(parts[3])
    return bool(m) and m.group("who") in keep


def live_paths(manifest, live_root, se_settings):
    out = {}
    for name, kind, sub, mode in COMPONENTS:
        src = manifest["sources"].get(name)
        if src is None:
            continue
        path = src["path"]
        if name == "ScriptExtenderSettings" and se_settings:
            path = se_settings
        elif sub and live_root:
            path = os.path.join(live_root, sub)
        out[name] = (kind, os.path.abspath(path), src["mode"], src["present"])
    return out


def scan_extras(root, man_dirs, man_files):
    """Walk the live tree; return (extras [(rel, is_dir)], live_files {key: rel}). Extra folders are not entered."""
    extras, live_files = [], {}
    base = lp(root)
    if not os.path.isdir(base):
        return extras, live_files
    for dp, dn, fn in os.walk(base):
        rel_dp = dp[len(base):].lstrip("\\/").replace("\\", "/")
        keep = []
        for d in sorted(dn):
            rel = rel_dp + "/" + d if rel_dp else d
            if key(rel) in man_dirs:
                keep.append(d)
            else:
                extras.append((rel, True))
        dn[:] = keep
        for f in sorted(fn):
            rel = rel_dp + "/" + f if rel_dp else f
            if key(rel) in man_files:
                live_files[key(rel)] = rel
            else:
                extras.append((rel, False))
    return extras, live_files


def build_plan(manifest, backup, paths, keep=()):
    plan = {}
    for name, (kind, live, mode, present) in paths.items():
        entries = manifest["files"].get(name, [])
        man_files = {key(e["path"]): e for e in entries}
        man_dirs = {key(d) for d in manifest["dirs"].get(name, [])}
        p = {"kind": kind, "live": live, "mode": mode, "extras": [], "restore": [], "replace": [],
             "mkdirs": [], "conflicts": [], "left_extras": []}
        if kind == "file":
            live_files = {}
            if entries and os.path.isfile(lp(live)):
                live_files[key(entries[0]["path"])] = entries[0]["path"]
            elif entries and os.path.isdir(lp(live)):
                p["conflicts"].append("%s is a folder, expected a file" % live)
            extras = []
        else:
            extras, live_files = scan_extras(live, man_dirs, man_files)
            if os.path.exists(lp(live)) and not os.path.isdir(lp(live)):
                p["conflicts"].append("%s is a file, expected a folder" % live)
        if mode == "exact":
            p["extras"] = [x for x in extras if not kept_save(name, x[0], keep)]
            p["kept"] = [x for x in extras if kept_save(name, x[0], keep)]
        else:
            p["left_extras"] = extras
        extra_keys = {key(r) for r, _ in extras}
        for k, e in sorted(man_files.items()):
            livefile = live if kind == "file" else os.path.join(live, e["path"])
            if k not in live_files:
                if k in extra_keys or os.path.isdir(lp(livefile)):
                    if mode == "exact":
                        p["restore"].append(e)        # the folder in the way is moved aside first
                    else:
                        p["conflicts"].append("folder where a file should be: %s" % livefile)
                else:
                    p["restore"].append(e)
                continue
            st = os.stat(lp(livefile))
            if st.st_size != e["size"] or sha256_file(livefile) != e["sha256"]:
                p["replace"].append(e)
        for d in manifest["dirs"].get(name, []):
            if not os.path.isdir(lp(os.path.join(live, d))):
                p["mkdirs"].append(d)
        plan[name] = p
    return plan


def print_plan(plan, applied):
    verb = {False: ("WOULD MOVE ASIDE", "WOULD RESTORE (missing)", "WOULD RESTORE (changed)"),
            True: ("MOVED ASIDE", "RESTORED (was missing)", "RESTORED (was changed; changed copy archived)")}[applied]
    total = 0
    for name, p in plan.items():
        n = len(p["extras"]) + len(p["restore"]) + len(p["replace"]) + len(p["mkdirs"])
        total += n
        print("[%s] %s  (%s)" % (name, p["live"], p["mode"]))
        if not n and not p["conflicts"] and not p["left_extras"]:
            print("    nothing to do - equals the backup")
        for rel, is_dir in p["extras"]:
            print("    %s: %s%s" % (verb[0], rel, "/  (folder)" if is_dir else ""))
        for e in p["restore"]:
            print("    %s: %s" % (verb[1], e["path"]))
        for e in p["replace"]:
            print("    %s: %s" % (verb[2], e["path"]))
        for d in p["mkdirs"]:
            print("    folder re-created: %s/" % d)
        for rel, is_dir in p.get("kept", []):
            print("    kept in place (kept campaign): %s%s" % (rel, "/" if is_dir else ""))
        for rel, is_dir in p["left_extras"]:
            print("    left in place (extra, not managed): %s%s" % (rel, "/" if is_dir else ""))
        for c in p["conflicts"]:
            print("    CONFLICT: %s" % c)
    moved_saves = save_counts(["%s/%s" % (r, "x") if d else r
                               for r, d in plan.get("PlayerProfiles", {"extras": []})["extras"]])
    for prof, camp in sorted(moved_saves.items()):
        for who, folders in sorted(camp.items()):
            print("  save folders %s aside - profile %s, %s: %d" % ("moved" if applied else "to move", prof, who,
                                                                   len(folders)))
    return total


def verify(manifest, paths, keep=()):
    """Return list of problems (empty = live equals backup)."""
    bad, notes = [], []
    for name, (kind, live, mode, present) in paths.items():
        entries = manifest["files"].get(name, [])
        man_files = {key(e["path"]): e for e in entries}
        man_dirs = {key(d) for d in manifest["dirs"].get(name, [])}
        if kind == "file":
            live_files = {key(entries[0]["path"]): entries[0]["path"]} if entries and os.path.isfile(lp(live)) else {}
            extras = []
        else:
            extras, live_files = scan_extras(live, man_dirs, man_files)
        for k, e in man_files.items():
            livefile = live if kind == "file" else os.path.join(live, e["path"])
            if k not in live_files:
                bad.append("%s: missing %s" % (name, e["path"]))
            elif sha256_file(livefile) != e["sha256"]:
                bad.append("%s: differs %s" % (name, e["path"]))
        for d in manifest["dirs"].get(name, []):
            if not os.path.isdir(lp(os.path.join(live, d))):
                bad.append("%s: missing folder %s" % (name, d))
        for rel, is_dir in extras:
            if kept_save(name, rel, keep):
                notes.append("%s: kept campaign save %s%s" % (name, rel, "/" if is_dir else ""))
                continue
            (bad if mode == "exact" else notes).append("%s: extra %s%s" % (name, rel, "/" if is_dir else ""))
    return bad, notes


def move_aside(src, dst):
    os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
    if os.path.exists(lp(dst)):
        raise RuntimeError("archive target already exists, not overwriting: %s" % dst)
    shutil.move(lp(src), lp(dst))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backup", help="backup folder (contains manifest.json)")
    ap.add_argument("--apply", action="store_true", help="really do it (default: dry run, shows the plan)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan only (this is the default)")
    ap.add_argument("--live-root", help="override: folder holding the live PlayerProfiles, Mods, Script Extender")
    ap.add_argument("--se-settings", help="override: live ScriptExtenderSettings.json path")
    ap.add_argument("--archive-root", help="where loot_test_saves_<date>/ is made (default: the backup's parent)")
    ap.add_argument("--keep-campaign", action="append",
                    help="leave new save folders of this campaign (leader name) in place; repeatable; "
                         "default: Tav; 'none' = keep nothing")
    a = ap.parse_args()
    keep = set(a.keep_campaign or ["Tav"]) - {"none"}
    if a.apply and a.dry_run:
        sys.exit("Use either --apply or --dry-run, not both.")

    refuse_if_running()
    backup = os.path.abspath(a.backup)
    mpath = os.path.join(backup, "manifest.json")
    if not os.path.isfile(lp(mpath)):
        sys.exit("REFUSED: no manifest.json in %s" % backup)
    with open(lp(mpath), encoding="utf-8") as f:
        manifest = json.load(f)
    if not manifest.get("verified"):
        sys.exit("REFUSED: this backup was never verified (manifest has no 'verified' stamp).")
    paths = live_paths(manifest, a.live_root, a.se_settings)
    archive_root = os.path.abspath(a.archive_root or os.path.dirname(backup))
    for name, (kind, live, mode, present) in paths.items():
        if kind == "dir" and os.path.normcase(archive_root + os.sep).startswith(os.path.normcase(live + os.sep)):
            sys.exit("REFUSED: archive folder is inside the live %s folder." % name)

    print("Backup:  %s (made %s, verified %s)" % (backup, manifest["created"], manifest["verified"]))
    print("Mode:    %s" % ("APPLY" if a.apply else "DRY RUN - nothing is changed; add --apply to do it"))
    print("Keeping new saves of: %s" % (", ".join(sorted(keep)) or "(none)"))
    plan = build_plan(manifest, backup, paths, keep)
    conflicts = [c for p in plan.values() for c in p["conflicts"]]
    if not a.apply:
        n = print_plan(plan, applied=False)
        print("Plan: %d change(s)%s." % (n, ", %d CONFLICT(S) - apply would refuse" % len(conflicts)
                                       if conflicts else ""))
        if any(p["extras"] or p["replace"] for p in plan.values()):
            print("Archive for moved files would be: %s" % unique_dir(archive_root, "loot_test_saves_" + today()))
        return 0
    if conflicts:
        print_plan(plan, applied=False)
        print("REFUSED: %d conflict(s), fix them by hand first." % len(conflicts))
        return 1

    # Check every backup file that will be copied back BEFORE anything is moved.
    damaged = []
    for name, p in plan.items():
        for e in p["restore"] + p["replace"]:
            src = os.path.join(backup, name, e["path"])
            if not os.path.isfile(lp(src)) or sha256_file(src) != e["sha256"]:
                damaged.append("%s/%s" % (name, e["path"]))
    if damaged:
        print("REFUSED: %d backup file(s) are missing or do not match the manifest - nothing was changed:"
              % len(damaged))
        for d in damaged[:50]:
            print("  " + d)
        return 1

    refuse_if_running()   # check again right before touching anything
    archive = None
    log = []

    def archive_dir():
        nonlocal archive
        if archive is None:
            archive = unique_dir(archive_root, "loot_test_saves_" + today())
            os.makedirs(lp(archive))
            print("Archive: %s" % archive)
        return archive

    for name, p in plan.items():
        live = p["live"]
        # (a) move extras aside
        for rel, is_dir in p["extras"]:
            move_aside(os.path.join(live, rel), os.path.join(archive_dir(), name, rel))
            log.append({"component": name, "path": rel, "folder": is_dir, "reason": "not in backup"})
        # (b) restore missing / changed files
        for e, changed in [(e, False) for e in p["restore"]] + [(e, True) for e in p["replace"]]:
            livefile = live if p["kind"] == "file" else os.path.join(live, e["path"])
            if changed:
                move_aside(livefile, os.path.join(archive_dir(), name, e["path"]))
                log.append({"component": name, "path": e["path"], "folder": False,
                            "reason": "changed since backup; replaced by the backed-up version"})
            src = os.path.join(backup, name, e["path"])
            digest, _ = copy_hashed(src, livefile)
            if digest != e["sha256"]:
                print("STOPPED: backup copy of %s/%s does not match its manifest hash." % (name, e["path"]))
                return 1
        for d in p["mkdirs"]:
            os.makedirs(lp(os.path.join(live, d)), exist_ok=True)
    if archive:
        with open(lp(os.path.join(archive, "moved.json")), "w", encoding="utf-8") as f:
            json.dump({"moved": datetime.datetime.now().isoformat(timespec="seconds"), "backup": backup,
                       "live": {n: p["live"] for n, p in plan.items()}, "items": log}, f, indent=1,
                      ensure_ascii=False)
    n = print_plan(plan, applied=True)
    print("Changes: %d. Archive: %s" % (n, archive or "(none needed)"))

    # (c) verify
    print("Verifying the live folders against the manifest ...", flush=True)
    bad, notes = verify(manifest, paths, keep)
    for x in notes:
        print("  note: %s" % x)
    if bad:
        print("VERIFY FAILED (%d problems):" % len(bad))
        for b in bad[:50]:
            print("  " + b)
        return 1
    nfiles = sum(len(v) for v in manifest["files"].values())
    print("VERIFIED OK: live PlayerProfiles and Mods equal the backup exactly (apart from kept campaign saves); "
          "all %d backed-up files match." % nfiles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
