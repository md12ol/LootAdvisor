"""The gauntlet test mod: a developer-only pak that loads the gauntlet harness and the F9 test popup in the test save,
with no eval hook. It is its own mod (LootAdvisorGauntletTest) and never part of the Loot Advisor pak or download.

    python tools/gauntlet/testmod.py build              # -> dist/LootAdvisorGauntletTest.pak
    python tools/gauntlet/testmod.py install [--dry-run] # copy the pak into the game, enable this mod only
    python tools/gauntlet/testmod.py remove [--dry-run]  # disable it again, pak moved to dist/disabled/
    python tools/gauntlet/testmod.py files              # what the pak holds (no build)

The source is tools/gauntlet/testmod/LootAdvisorGauntletTest/Mods/LootAdvisorGauntletTest (meta.lsx, Config.json,
the bootstraps); build stages it with the harness (gauntlet.lua, gauntlet_test.lua, gauntlet_ui.lua) under
ScriptExtender/Lua/Harness/ and packs it with the sibling BG3Tools checkout's build_pak.py. install and remove need
the game closed; they touch only this mod's pak and its modsettings.lsx entry, never another mod's.
The mod stays inert unless the test file (engine.py arm) names a party member of the loaded save: see the bootstraps.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(os.path.dirname(HERE))
MOD = "LootAdvisorGauntletTest"
SRC = os.path.join(HERE, "testmod", MOD)
HARNESS = ("gauntlet.lua", "gauntlet_test.lua", "gauntlet_ui.lua")
HARNESS_DIR = "Mods/%s/ScriptExtender/Lua/Harness" % MOD
DIST = os.path.join(LA, "dist")
STAGE = os.path.join(DIST, "testmod_stage")


def bg3tools():
    """The sibling BG3Tools checkout's tools folder, importable (build_pak, install_mods)."""
    tools = os.path.join(os.path.dirname(LA), "BG3Tools", "tools")
    if not os.path.isfile(os.path.join(tools, "build_pak.py")):
        # a worktree under _wt/ sits one level deeper than the checkouts
        tools = os.path.join(os.path.dirname(os.path.dirname(LA)), "BG3Tools", "tools")
    if not os.path.isfile(os.path.join(tools, "build_pak.py")):
        raise SystemExit("BG3Tools not found next to this repository (needs tools/build_pak.py)")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    return tools


def files():
    """(path in the pak, source file) of everything the test mod's pak holds, sorted by path."""
    out = []
    for dirpath, _dirs, names in os.walk(os.path.join(SRC, "Mods")):
        for n in names:
            full = os.path.join(dirpath, n)
            out.append((os.path.relpath(full, SRC).replace("\\", "/"), full))
    out += [("%s/%s" % (HARNESS_DIR, n), os.path.join(HERE, n)) for n in HARNESS]
    return sorted(out)


def stage():
    """A fresh copy of the pak's tree under dist/testmod_stage/<MOD>/; returns the staging project folder."""
    shutil.rmtree(STAGE, ignore_errors=True)
    for rel, full in files():
        dst = os.path.join(STAGE, MOD, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(full, dst)
    return STAGE


def build():
    bg3tools()
    import build_pak
    build_pak.REPO_DIRS[MOD] = stage()
    out, packed = build_pak.build(MOD)
    build_pak.verify(out, packed)
    os.makedirs(DIST, exist_ok=True)
    dst = os.path.join(DIST, MOD + ".pak")
    shutil.move(out, dst)
    shutil.rmtree(STAGE, ignore_errors=True)
    return dst, [name for name, _data in packed]


def _install_mods():
    bg3tools()
    import build_pak
    import install_mods
    build_pak.REPO_DIRS[MOD] = SRC
    return install_mods


def install(dry=False):
    im = _install_mods()
    pak = os.path.join(DIST, MOD + ".pak")
    if not os.path.isfile(pak):
        raise SystemExit("missing %s - run: python tools/gauntlet/testmod.py build" % pak)
    if im.game_running():
        raise SystemExit("BG3 is running - quit it from its menu first")
    dst = os.path.join(im.MODS_DIR, MOD + ".pak")
    print(("would copy" if dry else "copy") + " %s -> %s" % (pak, dst))
    text = open(im.MODSETTINGS, encoding="utf-8-sig").read()
    new, changes = im.patch_modsettings(text, [im.read_meta(MOD)])
    _write_settings(im, text, new, changes, dry)
    if not dry:
        os.makedirs(im.MODS_DIR, exist_ok=True)
        shutil.copyfile(pak, dst)


def remove(dry=False):
    im = _install_mods()
    if im.game_running():
        raise SystemExit("BG3 is running - quit it from its menu first")
    text = open(im.MODSETTINGS, encoding="utf-8-sig").read()
    new, changes = im.remove_from_modsettings(text, MOD)
    _write_settings(im, text, new, changes, dry)
    pak = os.path.join(im.MODS_DIR, MOD + ".pak")
    if os.path.isfile(pak):
        dst = os.path.join(DIST, "disabled", MOD + ".pak")
        print(("would move" if dry else "move") + " %s -> %s" % (pak, dst))
        if not dry:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(pak, dst)


def _write_settings(im, text, new, changes, dry):
    for c in changes:
        print(("would change: " if dry else "modsettings.lsx: ") + c)
    if not changes:
        print("modsettings.lsx unchanged")
    if dry or not changes:
        return
    raw = open(im.MODSETTINGS, "rb").read()
    shutil.copyfile(im.MODSETTINGS, im.MODSETTINGS + ".bak")
    with open(im.MODSETTINGS, "wb") as f:
        f.write((b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + new.encode("utf-8"))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    dry = "--dry-run" in argv
    if cmd == "build":
        out, names = build()
        print("Wrote %s (%d files)" % (out, len(names)))
        for n in names:
            print("  " + n)
    elif cmd == "install":
        install(dry)
    elif cmd == "remove":
        remove(dry)
    elif cmd == "files":
        for rel, _full in files():
            print(rel)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
