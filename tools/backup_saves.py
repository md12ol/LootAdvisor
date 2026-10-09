"""Back up Baldur's Gate 3 saves/profiles, Mods and Script Extender config, with a verified manifest.

    python backup_saves.py               # real backup into LootAdvisor/backups/loot_pre_test_<date>[_n]/
    python backup_saves.py --dry-run     # only show what would be copied

Never overwrites an existing backup folder. Refuses while bg3.exe / bg3_dx11.exe is running.
Layout of a backup:
    <backup>/manifest.json
    <backup>/PlayerProfiles/...           (copy of ...\\Baldur's Gate 3\\PlayerProfiles)
    <backup>/Mods/...                     (copy of ...\\Baldur's Gate 3\\Mods)
    <backup>/ScriptExtender/...           (copy of ...\\Baldur's Gate 3\\Script Extender, big files skipped)
    <backup>/ScriptExtenderSettings/ScriptExtenderSettings.json   (copy of <game>\\bin\\ScriptExtenderSettings.json)
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bg3_saves_common import (COMPONENTS, DEFAULT_DEST_ROOT, DEFAULT_SE_SETTINGS, DEFAULT_SRC_ROOT, REQUIRED,
                              copy_hashed, human, lp, mtime_iso, refuse_if_running, save_counts, sha256_file,
                              today, unique_dir, walk_tree)


def component_sources(src_root, se_settings):
    out = []
    for name, kind, sub, mode in COMPONENTS:
        path = se_settings if name == "ScriptExtenderSettings" else os.path.join(src_root, sub)
        out.append((name, kind, os.path.abspath(path), mode))
    return out


def plan(src_root, se_settings, se_max_bytes):
    """What would be copied: per component (dirs, files{rel:(size,mtime)}, skipped{rel:size})."""
    comps = {}
    for name, kind, path, mode in component_sources(src_root, se_settings):
        entry = {"kind": kind, "source": path, "mode": mode, "dirs": [], "files": {}, "skipped": {},
                 "present": os.path.exists(lp(path))}
        if entry["present"]:
            if kind == "dir":
                entry["dirs"], files = walk_tree(path)
            else:
                st = os.stat(lp(path))
                files = {os.path.basename(path): (st.st_size, st.st_mtime)}
            for rel, (size, mt) in files.items():
                if name == "ScriptExtender" and size > se_max_bytes:
                    entry["skipped"][rel] = size
                else:
                    entry["files"][rel] = (size, mt)
        comps[name] = entry
    return comps


def print_summary(comps):
    total_files = sum(len(c["files"]) for c in comps.values())
    total_size = sum(s for c in comps.values() for s, _ in c["files"].values())
    print("Files: %d   Total size: %s (%d bytes)" % (total_files, human(total_size), total_size))
    for name, c in comps.items():
        if not c["present"]:
            print("  %-23s MISSING (%s)" % (name, c["source"]))
            continue
        size = sum(s for s, _ in c["files"].values())
        print("  %-23s %5d files  %10s   from %s" % (name, len(c["files"]), human(size), c["source"]))
        for rel, s in sorted(c["skipped"].items()):
            print("      skipped (too big, %s): %s" % (human(s), rel))
    counts = save_counts(comps["PlayerProfiles"]["files"].keys())
    profiles = sorted({r.split("/")[0] for r in comps["PlayerProfiles"]["dirs"] if "/" not in r})
    print("Profiles: %s" % (", ".join(profiles) or "none"))
    for prof in sorted(counts):
        camp = counts[prof]
        print("  Profile %s: %d saves" % (prof, sum(len(v) for v in camp.values())))
        for who in sorted(camp):
            print("    %-20s %3d saves" % (who, len(camp[who])))
    return total_files, total_size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src-root", default=DEFAULT_SRC_ROOT,
                    help="folder holding PlayerProfiles, Mods, Script Extender (default: %(default)s)")
    ap.add_argument("--se-settings", default=DEFAULT_SE_SETTINGS,
                    help="ScriptExtenderSettings.json path (default: %(default)s)")
    ap.add_argument("--dest-root", default=DEFAULT_DEST_ROOT, help="backups folder (default: %(default)s)")
    ap.add_argument("--name", default="loot_pre_test", help="backup folder prefix (default: %(default)s)")
    ap.add_argument("--se-max-mb", type=float, default=50.0,
                    help="skip Script Extender files bigger than this (logs) (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true", help="only show what would be copied")
    a = ap.parse_args()

    refuse_if_running()
    src_root = os.path.abspath(a.src_root)
    dest_root = os.path.abspath(a.dest_root)
    if os.path.normcase(dest_root + os.sep).startswith(os.path.normcase(src_root + os.sep)):
        sys.exit("REFUSED: the backup folder must not be inside the source folder.")

    comps = plan(src_root, a.se_settings, int(a.se_max_mb * 1024 * 1024))
    for req in REQUIRED:
        if not comps[req]["present"]:
            sys.exit("REFUSED: %s not found: %s" % (req, comps[req]["source"]))
    if not comps["PlayerProfiles"]["files"]:
        sys.exit("REFUSED: PlayerProfiles is empty: %s" % comps["PlayerProfiles"]["source"])

    target = unique_dir(dest_root, "%s_%s" % (a.name, today()))
    print("Backup %s" % ("PLAN (dry run, nothing copied)" if a.dry_run else "into " + target))
    print("Target: %s" % target)
    total_files, total_size = print_summary(comps)
    if not a.dry_run:
        os.makedirs(dest_root, exist_ok=True)
    probe = dest_root
    while not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    free = shutil.disk_usage(probe).free
    print("Free space at destination: %s" % human(free))
    if free < total_size * 1.05 + 100 * 1024 * 1024:
        sys.exit("REFUSED: not enough free space (need about %s)." % human(total_size * 1.05))
    if a.dry_run:
        return 0

    # Copy into <target>.incomplete, renamed to <target> only after verification.
    work = target + ".incomplete"
    os.makedirs(lp(work))
    manifest = {
        "format": 1,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "host": os.environ.get("COMPUTERNAME", ""),
        "sources": {n: {"path": c["source"], "kind": c["kind"], "mode": c["mode"], "present": c["present"]}
                    for n, c in comps.items()},
        "skipped": {n: c["skipped"] for n, c in comps.items() if c["skipped"]},
        "dirs": {n: c["dirs"] for n, c in comps.items()},
        "files": {},
    }
    done = 0
    for name, c in comps.items():
        entries = []
        for rel, (size, mt) in sorted(c["files"].items()):
            src = c["source"] if c["kind"] == "file" else os.path.join(c["source"], rel)
            dst = os.path.join(work, name, rel)
            digest, nbytes = copy_hashed(src, dst)
            st = os.stat(lp(dst))
            entries.append({"path": rel, "size": nbytes, "sha256": digest, "mtime": st.st_mtime,
                            "mtime_local": mtime_iso(st.st_mtime)})
            done += 1
            if done % 50 == 0:
                print("  copied %d / %d files" % (done, total_files), flush=True)
        for d in c["dirs"]:
            os.makedirs(lp(os.path.join(work, name, d)), exist_ok=True)   # keep empty folders too
        manifest["files"][name] = entries
    mpath = os.path.join(work, "manifest.json")
    with open(lp(mpath), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)

    # Verify: re-hash every copied file against the manifest, and nothing extra in the copy.
    print("Verifying the copy against manifest.json ...", flush=True)
    bad = []
    for name, entries in manifest["files"].items():
        want = {e["path"]: e for e in entries}
        dirs, files = walk_tree(os.path.join(work, name))
        for rel in sorted(set(files) | set(want)):
            if rel not in want:
                bad.append("extra in copy: %s/%s" % (name, rel))
            elif rel not in files:
                bad.append("missing in copy: %s/%s" % (name, rel))
            elif files[rel][0] != want[rel]["size"] or \
                    sha256_file(os.path.join(work, name, rel)) != want[rel]["sha256"]:
                bad.append("content differs: %s/%s" % (name, rel))
        if sorted(dirs) != sorted(manifest["dirs"][name]):
            bad.append("folder list differs in %s" % name)
    if bad:
        print("VERIFY FAILED (%d problems). The incomplete copy is left at %s" % (len(bad), work))
        for b in bad[:50]:
            print("  " + b)
        return 1
    manifest["verified"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(lp(mpath), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    if os.path.exists(lp(target)):
        print("REFUSED to rename: %s appeared meanwhile; copy left at %s" % (target, work))
        return 1
    os.rename(lp(work), lp(target))
    print("VERIFIED OK: %d files, %s, every SHA-256 matches. Backup: %s" % (total_files, human(total_size), target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
