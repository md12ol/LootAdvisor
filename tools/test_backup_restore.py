"""Self-test for backup_saves.py / restore_saves.py on a synthetic scratch tree (never the real game folders).

    python test_backup_restore.py --work <empty scratch folder> [--real-save <one real save folder to copy>]

Builds <work>/live (fake "Baldur's Gate 3" folder) + <work>/bin/ScriptExtenderSettings.json, backs it up into
<work>/backups, simulates test-play changes, restores, and checks the tree equals the original byte for byte.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
from bg3_saves_common import DEFAULT_SRC_ROOT, lp, today  # noqa: E402

FAILS = []
SHORT = {}   # long path -> short label, only to keep the transcript readable


def check(cond, what):
    print("  [%s] %s" % ("PASS" if cond else "FAIL", what))
    if not cond:
        FAILS.append(what)


def write(path, data, mtime=None):
    os.makedirs(lp(os.path.dirname(path)), exist_ok=True)
    with open(lp(path), "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    if mtime:
        os.utime(lp(path), (mtime, mtime))


def snapshot(root):
    """{rel: (size, sha256, mtime)} for files and {rel/} for folders below root."""
    snap, base = {}, lp(root)
    for dp, dn, fn in os.walk(base):
        rd = dp[len(base):].lstrip("\\/").replace("\\", "/")
        for d in dn:
            snap[(rd + "/" + d if rd else d) + "/"] = "dir"
        for f in fn:
            p = os.path.join(dp, f)
            st = os.stat(p)
            with open(p, "rb") as fh:
                snap[rd + "/" + f if rd else f] = (st.st_size, hashlib.sha256(fh.read()).hexdigest(), st.st_mtime)
    return snap


def run(args, env_extra=None, wrapper=False):
    env = dict(os.environ)
    env.pop("BG3_FAKE_RUNNING_PROCS", None)
    env["BG3_FAKE_RUNNING_PROCS"] = ""          # tests never depend on whether the real game is open ...
    env.update(env_extra or {})
    if wrapper:
        cmd = ["bash", os.path.join(TOOLS, args[0] + ".sh")] + args[1:]
    else:
        cmd = [sys.executable, os.path.join(TOOLS, args[0] + ".py")] + args[1:]
    env["PYTHONIOENCODING"] = "utf-8"

    def short(t):
        for k, v in SHORT.items():
            t = t.replace(k, v)
        return t
    print("\n$ %s%s" % (short(" ".join('"%s"' % c if " " in c else c for c in cmd[1:])),
                        "   [BG3_FAKE_RUNNING_PROCS=%s]" % env["BG3_FAKE_RUNNING_PROCS"]
                        if env["BG3_FAKE_RUNNING_PROCS"] else ""))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    for line in (r.stdout + r.stderr).rstrip().splitlines():
        print("  | " + short(line))
    print("  exit code %d" % r.returncode)
    return r


def build_tree(live, binf, real_save):
    t0 = 1_700_000_000
    pp = os.path.join(live, "PlayerProfiles")
    write(os.path.join(pp, "playerprofiles8.lsf"), b"LSOF\x00profiles-list", t0)
    pub = os.path.join(pp, "Public")
    write(os.path.join(pub, "profile8.lsf"), b"LSOF\x00profile-public-v1", t0 + 1)
    write(os.path.join(pub, "config.lsf"), b"LSOF\x00config", t0 + 2)
    write(os.path.join(pub, "modsettings.lsx"), "<save><!-- original mod order --></save>\n", t0 + 3)
    story = os.path.join(pub, "Savegames", "Story")
    for i, folder in enumerate(["Tav-3151261930__QuickSave_1", "The White Urge-37271261780__Undercity Ruins - 71h 09m",
                                "Ryzen-25512515358__Selûnite Outpost - 20h 51m", "Ryzen-1612519314__AutoSave_85"]):
        nm = folder.split("__", 1)[1]
        write(os.path.join(story, folder, nm + ".lsv"), os.urandom(200_000 + i), t0 + 10 + i)
        write(os.path.join(story, folder, nm + ".WebP"), os.urandom(5_000 + i), t0 + 10 + i)
    # a deep folder so full paths go well past 260 characters; its name ends in a space (kept by the scripts)
    deep = os.path.join(story, "Micah-0201262063__" + "Very long save name " * 6, "x" * 60, "y" * 60)
    write(os.path.join(deep, "deep_file_" + "z" * 40 + ".lsv"), os.urandom(1000), t0 + 20)
    write(os.path.join(story, "Tav-12345__Ends with a dot.", "x.lsv"), b"dot", t0 + 21)
    os.makedirs(lp(os.path.join(pub, "Savegames", "EmptyFolder")))
    write(os.path.join(pp, "Alt", "profile8.lsf"), b"LSOF\x00profile-alt", t0 + 30)
    write(os.path.join(pp, "Alt", "Savegames", "Story", "Micah-122112618657__QuickSave_28", "QuickSave_28.lsv"),
          os.urandom(50_000), t0 + 31)
    if real_save:
        dst = os.path.join(story, os.path.basename(real_save.rstrip("\\/")))
        shutil.copytree(lp(real_save), lp(dst))      # read-only copy of one real save, mtimes kept
    write(os.path.join(live, "Mods", "BuildAdvisor.pak"), os.urandom(80_000), t0 + 40)
    write(os.path.join(live, "Mods", "Autopilot.pak"), os.urandom(80_000), t0 + 41)
    se = os.path.join(live, "Script Extender")
    write(os.path.join(se, "BuildAdvisor_settings.json"), '{"a": 1}\n', t0 + 50)
    write(os.path.join(se, "BA_adv.lua"), "-- lua\n", t0 + 51)
    write(os.path.join(se, "huge_log.txt"), b"L" * (2 * 1024 * 1024), t0 + 52)   # skipped with --se-max-mb 1
    write(binf, '{"CreateConsole": false, "EnableLogging": true}\n', t0 + 60)


def simulate_test_play(live, binf):
    pp = os.path.join(live, "PlayerProfiles")
    story = os.path.join(pp, "Public", "Savegames", "Story")
    write(os.path.join(story, "The White Urge-99999999__LOOT TEST 1", "LOOT TEST 1.lsv"), os.urandom(70_000))
    write(os.path.join(story, "The White Urge-99999999__LOOT TEST 1", "LOOT TEST 1.WebP"), os.urandom(3_000))
    write(os.path.join(story, "Ryzen-88888888__QuickSave_198", "QuickSave_198.lsv"), os.urandom(70_000))
    write(os.path.join(pp, "Alt", "Savegames", "Story", "Micah-7777__AutoSave_29", "AutoSave_29.lsv"),
          os.urandom(9_000))
    write(os.path.join(pp, "Public", "profile8.lsf"), b"LSOF\x00profile-public-MODDED")        # modified
    write(os.path.join(pp, "Public", "modsettings.lsx"), "<save><!-- LootAdvisor added --></save>\n")
    write(os.path.join(pp, "Public", "modsettings.lsx.bak"), "backup the game made\n")          # extra file
    os.remove(lp(os.path.join(story, "Tav-3151261930__QuickSave_1", "QuickSave_1.WebP")))     # deleted file
    shutil.rmtree(lp(os.path.join(story, "Ryzen-1612519314__AutoSave_85")))                   # rotated away
    os.rmdir(lp(os.path.join(pp, "Public", "Savegames", "EmptyFolder")))                      # empty dir gone
    write(os.path.join(live, "Mods", "LootAdvisor.pak"), os.urandom(60_000))                    # extra mod
    write(os.path.join(live, "Mods", "BuildAdvisor.pak"), os.urandom(81_000))                  # rebuilt mod
    write(os.path.join(live, "Script Extender", "BuildAdvisor_settings.json"), '{"a": 2}\n')   # changed SE
    write(os.path.join(live, "Script Extender", "LootAdvisor_scan.txt"), "scan\n")             # extra SE
    write(binf, '{"CreateConsole": true}\n')                                                     # changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--real-save", help="one real save folder to copy (read-only) into the fake tree")
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    real = os.path.normcase(os.path.abspath(DEFAULT_SRC_ROOT))
    assert not os.path.normcase(work).startswith(real), "work folder must not be inside the real BG3 folder"
    SHORT[TOOLS + os.sep] = ""
    SHORT[work] = "<W>"
    if os.path.exists(lp(work)):
        shutil.rmtree(lp(work))
    live, binf = os.path.join(work, "live"), os.path.join(work, "bin", "ScriptExtenderSettings.json")
    backups, archive_root = os.path.join(work, "backups"), os.path.join(work, "backups")
    print("== build synthetic tree in %s" % work)
    build_tree(live, binf, a.real_save)
    s0, s0_bin = snapshot(live), snapshot(os.path.dirname(binf))
    print("  %d files, %d folders" % (sum(1 for v in s0.values() if v != "dir"),
                                       sum(1 for v in s0.values() if v == "dir")))
    longest = max(len(os.path.join(live, k)) for k in s0)
    print("  longest full path: %d characters" % longest)
    src = ["--src-root", live, "--se-settings", binf, "--dest-root", backups, "--se-max-mb", "1"]

    print("\n== 1. refusal while BG3 runs (faked process list)")
    r = run(["backup_saves"] + src, {"BG3_FAKE_RUNNING_PROCS": "explorer.exe,bg3_dx11.exe"})
    check(r.returncode == 2 and "REFUSED" in r.stdout, "backup refuses when bg3_dx11.exe runs")
    check(not os.path.exists(backups), "no backup folder was created")
    r = run(["backup_saves"] + src, {"BG3_FAKE_RUNNING_PROCS": "bg3.exe"}, wrapper=True)
    check(r.returncode == 2 and "REFUSED" in r.stdout, "backup_saves.sh refuses when bg3.exe runs")
    r = run(["backup_saves"] + src, {"BG3_FAKE_RUNNING_PROCS": "explorer.exe,steam.exe"})
    check(r.returncode == 0, "backup runs when other processes (not BG3) run")
    first = os.path.join(backups, "loot_pre_test_" + today())

    print("\n== 2. dry run creates nothing; a second backup never overwrites the first")
    shutil.rmtree(lp(backups))
    r = run(["backup_saves", "--dry-run"] + src)
    check(r.returncode == 0 and not os.path.exists(backups), "backup --dry-run copies nothing")
    r = run(["backup_saves"] + src, wrapper=True)
    check(r.returncode == 0 and os.path.isfile(os.path.join(first, "manifest.json")), "backup via .sh wrapper OK")
    check("huge_log.txt" in r.stdout and "skipped" in r.stdout, "big Script Extender file reported as skipped")
    b_snap = snapshot(first)
    r = run(["backup_saves"] + src)
    check(r.returncode == 0 and os.path.isdir(first + "_2"), "second backup went to a new _2 folder")
    check(snapshot(first) == b_snap, "first backup untouched by the second")
    check(snapshot(live) == s0, "backup did not change the live tree")

    print("\n== 3. refusal of restore while BG3 runs")
    r = run(["restore_saves", first, "--apply"], {"BG3_FAKE_RUNNING_PROCS": "bg3.exe"})
    check(r.returncode == 2 and "REFUSED" in r.stdout, "restore --apply refuses when bg3.exe runs")

    print("\n== 4. simulate test play")
    simulate_test_play(live, binf)
    s1, s1_bin = snapshot(live), snapshot(os.path.dirname(binf))
    check(s1 != s0, "tree changed")

    print("\n== 5. restore dry run (default)")
    r = run(["restore_saves", first], wrapper=True)
    check(r.returncode == 0 and "DRY RUN" in r.stdout, "dry run OK")
    check(snapshot(live) == s1 and snapshot(os.path.dirname(binf)) == s1_bin, "dry run changed nothing")
    check(not any(n.startswith("loot_test_saves") for n in os.listdir(backups)), "dry run made no archive")

    print("\n== 6. restore --apply")
    r = run(["restore_saves", first, "--apply"])
    check(r.returncode == 0 and "VERIFIED OK" in r.stdout, "restore --apply verified OK")
    s2 = snapshot(live)
    pp_mods = lambda s: {k: v for k, v in s.items() if k.startswith(("PlayerProfiles", "Mods"))}
    check(pp_mods(s2) == pp_mods(s0), "PlayerProfiles + Mods equal the original byte for byte (and mtimes)")
    se2 = {k: v for k, v in s2.items() if k.startswith("Script Extender")}
    se0 = {k: v for k, v in s0.items() if k.startswith("Script Extender")}
    check(all(se2.get(k) == v for k, v in se0.items()), "every original Script Extender file is back")
    check(set(se2) - set(se0) == {"Script Extender/LootAdvisor_scan.txt"},
          "only the extra SE file is left in place (by design)")
    check(snapshot(os.path.dirname(binf)) == s0_bin, "ScriptExtenderSettings.json restored")
    arch = os.path.join(archive_root, "loot_test_saves_" + today())
    check(os.path.isfile(os.path.join(arch, "moved.json")), "archive with moved.json exists")
    a_snap = snapshot(arch)
    expect = {
        "PlayerProfiles/Public/Savegames/Story/The White Urge-99999999__LOOT TEST 1/LOOT TEST 1.lsv",
        "PlayerProfiles/Public/Savegames/Story/The White Urge-99999999__LOOT TEST 1/LOOT TEST 1.WebP",
        "PlayerProfiles/Public/Savegames/Story/Ryzen-88888888__QuickSave_198/QuickSave_198.lsv",
        "PlayerProfiles/Alt/Savegames/Story/Micah-7777__AutoSave_29/AutoSave_29.lsv",
        "PlayerProfiles/Public/profile8.lsf", "PlayerProfiles/Public/modsettings.lsx",
        "PlayerProfiles/Public/modsettings.lsx.bak", "Mods/LootAdvisor.pak", "Mods/BuildAdvisor.pak",
        "ScriptExtender/BuildAdvisor_settings.json", "ScriptExtenderSettings/ScriptExtenderSettings.json",
    }
    live_name = {"ScriptExtender/": "Script Extender/"}
    for rel in sorted(expect):
        lrel = rel
        for k, v in live_name.items():
            lrel = lrel.replace(k, v, 1) if lrel.startswith(k) else lrel
        want = s1_bin.get("ScriptExtenderSettings.json") if rel.startswith("ScriptExtenderSettings/") else s1.get(lrel)
        got = a_snap.get(rel)
        check(got is not None and want is not None and got[:2] == want[:2], "archived with test content: " + rel)
    check({k for k, v in a_snap.items() if v != "dir"} == expect | {"moved.json"}, "archive holds nothing else")

    print("\n== 7. restore again: nothing left to do")
    r = run(["restore_saves", first])
    check(r.returncode == 0 and "Plan: 0 change(s)" in r.stdout, "second dry run plans 0 changes")

    print("\n== 8. a tampered backup is caught")
    import json
    m2 = os.path.join(first + "_2", "manifest.json")
    with open(m2, encoding="utf-8") as f:
        man = json.load(f)
    man.pop("verified")
    with open(m2, "w", encoding="utf-8") as f:
        json.dump(man, f)
    r = run(["restore_saves", first + "_2"])
    check(r.returncode != 0 and "never verified" in r.stdout + r.stderr, "unverified backup refused")
    man["verified"] = "test"
    with open(m2, "w", encoding="utf-8") as f:
        json.dump(man, f)
    write(os.path.join(first + "_2", "PlayerProfiles", "Public", "profile8.lsf"), b"bit rot")   # damage backup
    write(os.path.join(live, "PlayerProfiles", "Public", "profile8.lsf"), b"changed again")     # needs restore
    write(os.path.join(live, "Mods", "Another.pak"), b"pak")                                    # extra
    s3 = snapshot(live)
    r = run(["restore_saves", first + "_2", "--apply"])
    check(r.returncode != 0 and "nothing was changed" in r.stdout, "damaged backup file refused before any change")
    check(snapshot(live) == s3, "live tree untouched after the refusal")

    print("\n== RESULT: %s" % ("ALL PASS" if not FAILS else "%d FAIL(S): %s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
