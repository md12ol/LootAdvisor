"""Loot Advisor regression suite.

  python LootAdvisor/tests/run.py            run all checks against the real pipeline outputs + mod Lua; exit 1 on failure
  python LootAdvisor/tests/run.py --mutate   prove every check can fail: break the guarded thing in a SCRATCH COPY (or a
                                             patched in-memory Lua load), confirm the check goes red; exit 1 if any
                                             mutation is not caught. Nothing in LootAdvisor/ or Mods/ is modified.
  -v                                         print every failure line (default: first 8 per check)
  --ci                                       tracked files only (GitHub CI): the mod's own LootData.lua stands in for
                                             data/scores/lua/LootData.lua; LOCAL-ONLY checks (game data: data/cache,
                                             data/items_all, data/scores, the game paks) and their mutations are
                                             skipped and listed as [LOCAL]. Combines with --mutate.

Inputs: LootAdvisor/data/scores/*.json + lua/LootData.lua (pipeline outputs: run python tools/match_research.py &&
python tools/score_items.py first), Mods/LootAdvisor/ScriptExtender/Lua (read-only, through lupa), Builds.lua
(read-only), game files (tests/gamedata.py). Needs: pip install lupa.
Expected-fail checks (XFAIL) document a known open bug; an unexpected pass (XPASS) counts as a failure so the mark
gets removed once the bug is fixed.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
ROOT = os.path.dirname(LA)
MODS_LUA = os.path.join(LA, "Mods", "LootAdvisor", "ScriptExtender", "Lua")
BUILDS_LUA = os.path.join(ROOT, "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender", "Lua", "Shared", "Builds.lua")
sys.path.insert(0, HERE)

try:
    import lupa  # noqa: F401
except ImportError:
    print("lupa missing - installing (pip install lupa)")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "lupa"])

import checks as C  # noqa: E402

LOGIC_OWNER_OLD = "return cs ~= nil and cs.team and not cs.dead"
# the decision-63 fix: a contested item's owner must be in the ACTIVE party (state.comp[c].party)
LOGIC_OWNER_FIX = "return cs ~= nil and cs.team and cs.party == true and not cs.dead"


# LOCAL-ONLY marker: checks that read game data (tests/gamedata.py, data/cache, data/items_all, data/scores) cannot run
# from tracked files, so --ci skips them; they run in the full local suite (pre-push hook). A check can also mark
# itself with a function attribute `local_only = True`. Any check not marked here runs in CI and must pass there.
LOCAL_ONLY = {"check_no_heavy_armour_raging", "check_profiles_cover_builds_lua", "check_class_proficiencies",
              "check_subclass_names", "check_sheet_subclass_features", "check_sheet_weapon_riders",
              "check_ranged_offhand_hand_crossbow"}


def local_only(fn):
    return bool(getattr(fn, "local_only", False)) or fn.__name__ in LOCAL_ONLY


class CiRoot:
    """A LootAdvisor root built from tracked files only: data/scores/lua/LootData.lua = the mod's shipped copy."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="la_ci_")
        self.root = os.path.join(self.dir, "LootAdvisor")
        self.reset()

    def reset(self):
        lua_dir = os.path.join(self.root, "data", "scores", "lua")
        os.makedirs(lua_dir, exist_ok=True)
        shutil.copy2(os.path.join(MODS_LUA, "Shared", "LootData.lua"), os.path.join(lua_dir, "LootData.lua"))

    def env(self, **kw):
        return C.Env(self.root, MODS_LUA, BUILDS_LUA, **kw)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run_check(fn, env):
    t0 = time.time()
    try:
        fails = fn(env)
    except Exception as e:  # noqa: BLE001 - a crash is a failure
        import traceback
        fails = [f"CRASH: {e!r}", traceback.format_exc(limit=3)]
    return fails, time.time() - t0


def real_env(**kw):
    return C.Env(LA, MODS_LUA, BUILDS_LUA, **kw)


def report(name, fails, env, secs, xfail, verbose):
    counts = ", ".join(f"{k} {v}" for k, v in env.counts.items())
    if fails and xfail:
        tag = "XFAIL"
    elif fails:
        tag = "FAIL"
    elif xfail:
        tag = "XPASS"
    else:
        tag = "PASS"
    print(f"[{tag:5}] {name}  ({counts}; {secs:.1f}s)")
    for f in fails[: None if verbose else 8]:
        print("         - " + f)
    if len(fails) > 8 and not verbose:
        print(f"         ... {len(fails) - 8} more (-v)")
    if tag == "XPASS":
        print("         expected to fail (known bug) but passed: the bug looks fixed - remove the xfail mark")
    return tag


def main_checks(verbose, ci=False):
    bad = 0
    tags = {}
    ci_root = CiRoot() if ci else None
    for name, fn, xfail in C.CHECKS:
        if ci and local_only(fn):
            print(f"[LOCAL] {name}  (local-only: needs game data, skipped in --ci)")
            tags[name] = "LOCAL"
            continue
        env = ci_root.env() if ci else real_env()
        fails, secs = run_check(fn, env)
        tag = report(name, fails, env, secs, xfail, verbose)
        tags[name] = tag
        bad += tag in ("FAIL", "XPASS")
    print(f"\n{sum(t == 'PASS' for t in tags.values())} passed, {sum(t == 'FAIL' for t in tags.values())} failed, "
          f"{sum(t == 'XFAIL' for t in tags.values())} expected-fail, {sum(t == 'XPASS' for t in tags.values())} "
          "unexpected pass" + (f", {sum(t == 'LOCAL' for t in tags.values())} local-only skipped" if ci else ""))
    if ci_root:
        ci_root.close()
    if all(t == "LOCAL" for t in tags.values()):
        print("no check ran")
        return 1
    return 1 if bad else 0


# ======================================================================== mutations
class Scratch:
    """A scratch copy of the LootAdvisor pieces the pipeline needs (tools, research, items, scores, small caches)."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="la_mutate_")
        self.root = os.path.join(self.dir, "LootAdvisor")
        self.reset()

    def reset(self):
        if os.path.exists(self.root):
            shutil.rmtree(self.root)
        os.makedirs(os.path.join(self.root, "data", "cache"))
        shutil.copytree(os.path.join(LA, "tools"), os.path.join(self.root, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__", "model3d", "rosters"))
        for d in ("research", "items_all", "scores"):
            shutil.copytree(os.path.join(LA, "data", d), os.path.join(self.root, "data", d))
        for fn in os.listdir(os.path.join(LA, "data", "cache")):
            if fn.endswith(".json") and (fn.startswith("roottemplates_") or fn in (
                    "class_progressions.json", "item_display_names.json", "stats_resolved.json")):
                shutil.copy2(os.path.join(LA, "data", "cache", fn), os.path.join(self.root, "data", "cache", fn))

    def patch(self, rel, old, new, count=1):
        p = os.path.join(self.root, rel)
        s = open(p, encoding="utf-8").read()
        if old not in s:
            raise RuntimeError(f"mutation target not found in {rel}: {old[:70]!r}")
        with open(p, "w", encoding="utf-8") as f:
            f.write(s.replace(old, new, count))

    def run_scoring(self):
        r = subprocess.run([sys.executable, os.path.join(self.root, "tools", "score_items.py")], cwd=self.root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError("scratch score_items.py failed:\n" + (r.stdout + r.stderr)[-1500:])

    def env(self, **kw):
        return C.Env(self.root, MODS_LUA, BUILDS_LUA, **kw)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def mutations(sc):
    """-> [(check name, mutation description, env factory, expect)] ; expect 'red' or 'green'."""
    by = {n: fn for n, fn, _x in C.CHECKS}
    names = [n for n, _f, _x in C.CHECKS]
    out = []

    # 1. re-allow heavy armour for raging builds (scorer rule removed), re-run scoring in the scratch copy
    def m1():
        sc.reset()
        sc.patch("tools/score_items.py", 'if rec["slot"] == "Breast" and arm.get("category") == "Heavy" and self.rages:',
                 "if False:")
        sc.run_scoring()
        return sc.env()
    out.append((names[0], "scorer: heavy-armour Rage rule removed, scoring re-run", m1, "red"))

    # 2a. drop one profile (the last build Builds.lua lists) from the profiles module
    def m2a():
        sc.reset()
        env = sc.env()
        bp = env.build_profiles()
        ids = [b[0] for b in C.gamedata.builds_lua(BUILDS_LUA)[0]]
        del bp.BUILDS[ids[-1]]
        env.mut_note = ids[-1]
        return env
    out.append((names[1], "profile of the last Builds.lua build deleted", m2a, "red"))

    # 2b. the old silent skip in sync_with_builds_lua
    def m2b():
        sc.reset()
        sc.patch("tools/build_profiles.py", "    if missing:\n        raise", "    if False:\n        raise")
        sc.patch("tools/build_profiles.py", "        b = BUILDS[bid]\n",
                 "        b = BUILDS.get(bid)\n        if not b:\n            continue\n")
        return sc.env()
    out.append((names[1], "sync_with_builds_lua: unknown build silently skipped (old code)", m2b, "red"))

    # 3. Cleric loses Morningstar + Flail at level 1 (class data the scorer reads), scoring re-run
    def m3():
        sc.reset()
        p = os.path.join(sc.root, "data", "cache", "class_progressions.json")
        d = json.load(open(p, encoding="utf-8"))
        d["classes"]["Cleric"]["start"] = [x for x in d["classes"]["Cleric"]["start"]
                                           if x not in ("Morningstars", "Flails")]
        json.dump(d, open(p, "w", encoding="utf-8"))
        sc.run_scoring()
        return sc.env()
    out.append((names[2], "Cleric level-1 Morningstar/Flail proficiency removed, scoring re-run", m3, "red"))

    # 4. rename a subclass in the outputs (first one found) the way the old table did ("... School")
    def m4():
        sc.reset()
        lua = os.path.join(sc.root, "data", "scores", "lua", "LootData.lua")
        s = open(lua, encoding="utf-8").read()
        m = re.search(r'sc=\{(\w+)="([^"]+)"', s)
        cls, name = m.group(1), m.group(2)
        new = name + " School"
        s = s.replace(f'{cls}="{name}"', f'{cls}="{new}"')
        open(lua, "w", encoding="utf-8").write(s)
        for p in os.listdir(os.path.join(sc.root, "data", "scores")):
            if p.endswith(".json"):
                fp = os.path.join(sc.root, "data", "scores", p)
                t = open(fp, encoding="utf-8").read()
                t2 = t.replace(f'"{cls}": "{name}"', f'"{cls}": "{new}"')
                if t2 != t:
                    open(fp, "w", encoding="utf-8").write(t2)
        return sc.env()
    out.append((names[3], "first subclass renamed to '<name> School' in LootData + json", m4, "red"))

    # 5a / 5b. a list-only row gets a frame / tooltip text (patched Lua load, files untouched)
    def m5a():
        sc.reset()
        return sc.env(lua_patches={"Logic.lua": [(
            'if row.s == "owned" or (framed[row.s] and row.mode ~= "l") then',
            'if row.s == "owned" or framed[row.s] or row.mode == "l" then')]})
    out.append((names[4], "Logic.lua: mode 'l' rows framed", m5a, "red"))

    def m5b():
        sc.reset()
        return sc.env(lua_patches={"Tooltip.lua": [('if r.mode ~= "l" or r.s == "owned" then', "if true then")]})
    out.append((names[4], "Tooltip.lua T.Apply: list-only rows get text", m5b, "red"))

    # 6. owners: Logic.lua carries the active-party fix -> the unpatched mod must pass; the pre-fix line (team only)
    #    and a variant that lets a camp companion count must both fail
    def m6fix():
        sc.reset()
        return sc.env()
    out.append((names[5], "Logic.lua as shipped (ownerAvailable = active party only) - must pass", m6fix, "green"))

    def m6old():
        sc.reset()
        return sc.env(lua_patches={"Logic.lua": [(LOGIC_OWNER_FIX, LOGIC_OWNER_OLD)]})
    out.append((names[5], "ownerAvailable back to the pre-fix line (whole team counts)", m6old, "red"))

    def m6():
        sc.reset()
        # a camp companion (in the team, not in the party) counts as owner
        return sc.env(lua_patches={"Logic.lua": [(LOGIC_OWNER_FIX, LOGIC_OWNER_FIX.replace(
            "cs.party == true", "(cs.party == true or cs.team == true)"))]})
    out.append((names[5], "ownerAvailable broken again: camp companion counts as owner", m6, "red"))

    # 7. the sheet matches subclasses by the shown name again (the old "Hexblade" / "Draconic" comparisons)
    def m7():
        sc.reset()
        sc.patch("tools/build_sets_artifact.py", 'sub_cls = {s["cls"]: s.get("k") for s in BI["subs"]}',
                 'sub_cls = {s["cls"]: s["n"] for s in BI["subs"]}')
        return sc.env()
    out.append((names[6], "sheet: subclass features matched on the shown name, not the game's internal name", m7,
                "red"))

    # 8a / 8b. stat riders dropped again; the weapon's own WeaponDamage boost counted on top of its rider again
    def m8a():
        sc.reset()
        sc.patch("tools/build_sets_artifact.py", "n = val(m.group(1))", "n = 0")
        return sc.env()
    out.append((names[7], "sheet: number / stat weapon riders (Giantslayer STR) ignored", m8a, "red"))

    def m8b():
        sc.reset()
        sc.patch("tools/build_sets_artifact.py", 'if x["name"] == "WeaponDamage" and (d0, t) in riders:', "if False:")
        return sc.env()
    out.append((names[7], "sheet: the weapon's own WeaponDamage boost counted again next to its rider", m8b, "red"))

    # 9. the validator lets any ranged weapon into the ranged off hand again
    def m9():
        sc.reset()
        sc.patch("tools/score_items.py", 'if slot == "RangedOff" and not me["handxbow"]:', "if False:")
        return sc.env()
    out.append((names[8], "validator: off-hand ranged hand-crossbow rule removed", m9, "red"))
    return out, by


def main_mutate(verbose, ci=False):
    sc = CiRoot() if ci else Scratch()
    print(f"scratch copy: {sc.root}\n")
    bad = 0
    results = []
    try:
        muts, by = mutations(sc)
        if ci:
            skipped = [m for m in muts if local_only(by[m[0]])]
            muts = [m for m in muts if not local_only(by[m[0]])]
            for name, desc, _make, _expect in skipped:
                print(f"[LOCAL] {name}\n      mutation: {desc} (local-only, skipped in --ci)")
            if not muts:
                print("no mutation ran")
                return 1
        for name, desc, make, expect in muts:
            t0 = time.time()
            try:
                env = make()
                fails = by[name](env)
            except Exception as e:  # noqa: BLE001
                fails = [f"mutation setup/check crashed: {e!r}"]
            red = bool(fails)
            ok = red if expect == "red" else not red
            bad += not ok
            verdict = ("caught (red)" if red else "NOT caught (green)") if expect == "red" else \
                ("green as expected" if not red else "STILL RED")
            note = getattr(env, "mut_note", None) if "env" in dir() else None
            results.append((name, desc, expect, verdict, ok))
            print(f"[{'OK' if ok else 'BAD'}] {name}\n      mutation: {desc}{' (' + note + ')' if note else ''}\n"
                  f"      -> {verdict}; {len(fails)} failure line(s); {time.time() - t0:.1f}s")
            for f in fails[: (None if verbose else 2)]:
                print("         - " + f[:220])
    finally:
        sc.close()
    print(f"\n{sum(r[4] for r in results)}/{len(results)} mutations behaved as expected")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--ci", action="store_true", help="tracked files only; skip LOCAL-ONLY checks")
    a = ap.parse_args()
    sys.exit(main_mutate(a.v, a.ci) if a.mutate else main_checks(a.v, a.ci))


if __name__ == "__main__":
    main()
