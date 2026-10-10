"""Loot Advisor regression suite.

  python LootAdvisor/tests/run.py            run all checks against the real pipeline outputs + mod Lua; exit 1 on failure
  python LootAdvisor/tests/run.py --mutate   prove every check can fail: break the guarded thing in a SCRATCH COPY (or a
                                             patched in-memory Lua load), confirm the check goes red; exit 1 if any
                                             mutation is not caught. The repo itself is never modified.
  -v                                         print every failure line (default: first 8 per check)
  --ci                                       tracked files only (GitHub CI): the mod's own LootData.lua stands in for
                                             data/scores/lua/LootData.lua; LOCAL-ONLY checks (game data: data/cache,
                                             data/items_all, data/scores, the game paks) and their mutations are
                                             skipped and listed as [LOCAL]. Combines with --mutate.

Inputs: LootAdvisor/data/scores/*.json + lua/LootData.lua (pipeline outputs: run python tools/match_research.py &&
python tools/score_items.py first), LootAdvisor/Mods/LootAdvisor/ScriptExtender/Lua (read-only, through lupa),
Builds.lua (read-only), game files (tests/gamedata.py). Needs: pip install lupa.
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
MODS_LUA = os.path.join(LA, "LootAdvisor", "Mods", "LootAdvisor", "ScriptExtender", "Lua")
BUILDS_LUA = os.path.join(ROOT, "BuildAdvisor", "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender", "Lua",
                          "Shared", "Builds.lua")
sys.path.insert(0, HERE)

try:
    import lupa  # noqa: F401
except ImportError:
    print("lupa missing - installing (pip install lupa)")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "lupa"])

import checks as C  # noqa: E402

LOGIC_OWNER_OLD = "return cs ~= nil and cs.team and not cs.dead"
# the owner fix: a contested item's owner must be in the ACTIVE party (state.comp[c].party)
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
                        ignore=shutil.ignore_patterns("__pycache__", "rosters"))
        for d in ("research", "items_all", "scores"):
            shutil.copytree(os.path.join(LA, "data", d), os.path.join(self.root, "data", d))
        for fn in os.listdir(os.path.join(LA, "data", "cache")):
            if fn.endswith(".json") and (fn.startswith("roottemplates_") or fn in (
                    "class_progressions.json", "item_display_names.json", "stats_resolved.json")):
                shutil.copy2(os.path.join(LA, "data", "cache", fn), os.path.join(self.root, "data", "cache", fn))
        # score_items.py reads Builds.lua from the sibling BuildAdvisor checkout, relative to its own folder
        lua = os.path.join(self.dir, os.path.relpath(BUILDS_LUA, ROOT))
        os.makedirs(os.path.dirname(lua), exist_ok=True)
        shutil.copy2(BUILDS_LUA, lua)

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

    # 10. Gale's items handed to Shadowheart; Builds.lua's Shadowheart order swapped without a re-score
    def m10a():
        sc.reset()
        return sc.env(lua_patches={"LootData.lua": [('o={"gale"}', 'o={"shadowheart"}')]})
    out.append((names[9], "LootData: every item owned by Gale given to Shadowheart", m10a, "red"))

    def m10b():
        sc.reset()
        src = open(BUILDS_LUA, encoding="utf-8").read()
        old = 'shadowheart = { builds = { "lightquick", "lightcleric" }'
        if old not in src:
            raise RuntimeError("mutation target not found in Builds.lua: " + old)
        swapped = os.path.join(sc.dir, "Builds.lua")
        with open(swapped, "w", encoding="utf-8") as f:
            f.write(src.replace(old, 'shadowheart = { builds = { "lightcleric", "lightquick" }'))
        return C.Env(sc.root, MODS_LUA, swapped)
    out.append((names[9], "Builds.lua: Shadowheart's order swapped, LootData not re-scored", m10b, "red"))

    # 11a / 11b. the Ext.UI.Defer gate removed (old SE walks the tree from the tick); the deferred path bypassed
    def m11a():
        sc.reset()
        return sc.env(lua_patches={"UiTree.lua": [(
            "if LA.Settings and LA.Settings.UnsafeUiOnOldSE == true then", "if true then")]})
    out.append((names[10], "UiTree.lua LA.UI.Run: no Ext.UI.Defer -> runs the UI code anyway (gate removed)", m11a,
                "red"))

    def m11b():
        sc.reset()
        return sc.env(lua_patches={"UiTree.lua": [("defer(function() pcall(fn) end)", "pcall(fn)")]})
    out.append((names[10], "UiTree.lua LA.UI.Run: Ext.UI.Defer present but the code runs straight from the tick",
                m11b, "red"))

    # 12a-12d. tooltip warnings: the tooltip shows the full text again; a short form drops a name; the F6 row gets a
    # cut text; no short forms at all (nothing to check must fail too)
    def m12a():
        sc.reset()
        return sc.env(lua_patches={"Tooltip.lua": [("body, warn = r.tw, true", "body, warn = r.w, true")]})
    out.append((names[11], "Tooltip.lua shows the full warning instead of its tooltip form", m12a, "red"))

    def m12b():
        sc.reset()
        lua = os.path.join(sc.root, "data", "scores", "lua", "LootData.lua")
        src = open(lua, encoding="utf-8").read()
        m = re.search(r'tw="(Theft: owned by [^"]+)"', src)
        if not m:
            raise RuntimeError("mutation target not found in LootData.lua: a 'Theft: owned by X' tooltip warning")
        env = sc.env(lua_patches={"LootData.lua": [(m.group(0), 'tw="Theft."')]})
        env.mut_note = m.group(1)
        return env
    out.append((names[11], "LootData: one tooltip warning loses its owner's name", m12b, "red"))

    def m12c():
        sc.reset()
        return sc.env(lua_patches={"Logic.lua": [('w = it.w or ""', 'w = (it.w or ""):sub(1, 40)')]})
    out.append((names[11], "Logic.lua: the F6 rows get the warning cut at 40 characters", m12c, "red"))

    def m12d():
        sc.reset()
        return sc.env(lua_patches={"Logic.lua": [('tw = it.tw or ""', 'tw = ""')],
                                   "LootData.lua": [(",tw=", ",xtw=")]})
    out.append((names[11], "no tooltip warnings in the data or the rows (nothing to check)", m12d, "red"))

    # 13a-13g. spoiler warning: dropped from the README, from the Sets page header, from the handbook generator; the
    # F6 notice never shown, shown but its hiding not saved, hidden by a missing setting; no place listed at all
    def without_spoiler(text):
        out_ = "\n".join(line for line in text.splitlines() if "Spoiler warning" not in line)
        if out_ == text:
            raise RuntimeError("mutation target not found: no 'Spoiler warning' line")
        return out_

    def m13a():
        sc.reset()
        env = sc.env()
        env.file_overrides = {"README.md (top)": without_spoiler(open(os.path.join(LA, "README.md"),
                                                                      encoding="utf-8").read())}
        return env
    out.append((names[12], "README: the spoiler warning line removed", m13a, "red"))

    def m13b():
        sc.reset()
        page = open(os.path.join(LA, "LootAdvisor", "Mods", "LootAdvisor", "Page", "Sets.html"), encoding="utf-8").read()
        head = re.search(r'<header class="topbar">.*?</header>', page, re.S).group(0)
        env = sc.env()
        env.file_overrides = {"Page/Sets.html header": without_spoiler(head)}
        return env
    out.append((names[12], "Sets page: the header built without the spoiler line", m13b, "red"))

    def m13c():
        sc.reset()
        docs = os.path.join(ROOT, "BuildAdvisor", "docs_site")
        tmp = os.path.join(sc.dir, "docs_site")
        shutil.copytree(docs, tmp, dirs_exist_ok=True)
        gen = os.path.join(tmp, "build_player_handbook.py")
        src = open(gen, encoding="utf-8", newline="").read()
        if "</div>%(spoiler)s" not in src:
            raise RuntimeError("mutation target not found in build_player_handbook.py: </div>%(spoiler)s")
        open(gen, "w", encoding="utf-8", newline="").write(src.replace("</div>%(spoiler)s", "</div>"))
        env = sc.env()
        env.spoiler_places = [p for p in C.spoiler_doc_places(tmp) if p[0].startswith("built handbook")]
        return env
    out.append((names[12], "handbook generator: the warning left out of the handbook's opening", m13c, "red"))

    def m13d():
        sc.reset()
        return sc.env(lua_patches={"Window.lua": [("if LA.Settings.SpoilerNoticeSeen == true then return end",
                                                   "do return end")]})
    out.append((names[12], "Window.lua: the F6 spoiler notice never shown", m13d, "red"))

    def m13e():
        sc.reset()
        return sc.env(lua_patches={"Window.lua": [("    LA.SaveSettings()\n    W.Render(LA.Result)",
                                                   "    W.Render(LA.Result)")]})
    out.append((names[12], "Window.lua: hiding the notice is not saved (back in the next game)", m13e, "red"))

    def m13f():
        sc.reset()
        return sc.env(lua_patches={"Common.lua": [("SpoilerNoticeSeen = false,", "SpoilerNoticeSeen = true,")]})
    out.append((names[12], "Common.lua: the setting defaults to hidden (never shown to a new player)", m13f, "red"))

    def m13g():
        sc.reset()
        env = sc.env()
        env.spoiler_places = []
        return env
    out.append((names[12], "no place listed for the spoiler warning (nothing to check)", m13g, "red"))
    # 14a-14d. builds and roster for everyone: class levels ignored; no Build Advisor stand-in for a companion that is
    # not loaded; companions gone for good kept; companions who may still join left out
    def lua_mut(fname, old, new):
        def make():
            sc.reset()
            return sc.env(lua_patches={fname: [(old, new)]})
        return make
    out.append((names[13], "Logic.lua MatchAnyBuild: class levels ignored (main ability only)", lua_mut(
        "Logic.lua", 'if any then return best, bestChar, "closest to the class levels" end',
        'if false then return best, bestChar, "closest to the class levels" end'), "red"))
    out.append((names[13], "Logic.lua BuildFor: no Build Advisor build for a companion without class levels", lua_mut(
        "Logic.lua", "if not ctx.classes or #ctx.classes == 0 then", "if false then"), "red"))
    out.append((names[14], "Logic.lua Roster: companions gone for good stay on the roster", lua_mut(
        "Logic.lua", "return cs ~= nil and (cs.dead == true or cs.gone == true)", "return cs ~= nil and cs.dead == true"),
        "red"))
    out.append((names[14], "Logic.lua Roster: companions who may still join left out", lua_mut(
        "Logic.lua", 'if not seen[k] and k ~= "darkurge" and not lost(k) then', "if false then"), "red"))

    # 15a-15d. merged markers: the party filter keeps everyone; one name per marker; arrows for anyone's markers;
    # the client ranks everyone's markers like the selected character's
    out.append((names[15], "Logic.lua MergeMarkers: the party filter keeps camp and future companions", lua_mut(
        "Logic.lua", '(filter == "party" and p.party)', '(filter == "party")'), "red"))
    out.append((names[15], "Logic.lua MergeMarkers: a marker keeps only the first name it is for", lua_mut(
        "Logic.lua", "        add(e.who, p.name)\n", "        if #e.who == 0 then add(e.who, p.name) end\n"), "red"))
    out.append((names[15], "Common.lua MarkerLabel: long name lists are not wrapped", lua_mut(
        "Common.lua", "if #cur + #piece > LA.LABEL_WIDTH and", "if false and"), "red"))
    out.append((names[15], "Paint.lua ArrowPicks: other characters' markers get off-screen arrows", lua_mut(
        "Paint.lua", "if o.rk < LA.OTHERS * 100 and n < maxArrows then", "if n < maxArrows then"), "red"))
    out.append((names[15], "Main.lua OnResult: everyone's markers ranked like the selected character's", lua_mut(
        "Main.lua", "    if m.who and not m.sel then v = v + LA.OTHERS * 100 end\n", ""), "red"))

    # 16a-16e. ties: the wearer ignored; the saved pick ignored; camp members make a tie; the row ignores the pick;
    # no ties in the data
    out.append((names[16], "Logic.lua Ties: the one wearing it does not keep it", lua_mut(
        "Logic.lua", 'if w and has(present, w) then t.pick, t.by = w, "wear"', 'if false then t.pick, t.by = w, "wear"'),
        "red"))
    out.append((names[16], "Logic.lua Ties: the saved pick is ignored (asked again every time)", lua_mut(
        "Logic.lua", 'elseif pk and has(present, pk) then t.pick, t.by = pk, "pick" end',
        'elseif false then t.pick, t.by = pk, "pick" end'), "red"))
    out.append((names[16], "Logic.lua Ties: camp members count for a tie", lua_mut(
        "Logic.lua", "for _, c in ipairs(mem) do if ownerAvailable(c, state) then present[#present + 1] = c end end",
        "for _, c in ipairs(mem) do if state.comp[c] and state.comp[c].team then present[#present + 1] = c end end"),
        "red"))
    out.append((names[16], "Logic.lua Recommend: an owned item tied to someone else stays the viewer's pick", lua_mut(
        "Logic.lua", 'if better and picked then st.s = "better"', 'if false then st.s = "better"'), "red"))
    out.append((names[16], "Logic.lua Recommend: a settled tie still shown as a shared pick", lua_mut(
        "Logic.lua", "if t and t.pick then", "if false then"), "red"))
    out.append((names[16], "LootData: no ties in the data (nothing to check)", lua_mut(
        "LootData.lua", ",ot={", ",xot={"), "red"))

    # 17a-17b. Sets page ties.js: the page's pick beats the game's; one party member alone still makes a tie
    def ties_mut(old, new):
        def make():
            sc.reset()
            src = open(os.path.join(LA, "tools", "sets_ship", "ties.js"), encoding="utf-8").read()
            if old not in src:
                raise RuntimeError("mutation target not found in ties.js: " + old[:60])
            env = sc.env()
            env.file_overrides = {"ties.js": src.replace(old, new)}
            return env
        return make
    out.append((names[17], "ties.js: the page's pick overrides the game's", ties_mut(
        'else if (pagePick && present.indexOf(pagePick) >= 0) { pick = pagePick; by = "page"; }',
        'if (pagePick && present.indexOf(pagePick) >= 0) { pick = pagePick; by = "page"; }'), "red"))
    out.append((names[17], "ties.js: one tie member in the party is still a tie", ties_mut(
        "if (present.length < 2) {", "if (present.length < 1) {"), "red"))

    # 18a-18d. F6: the tie button sends on the wrong channel; the filter is not saved; the selection does not resend
    # on a new filter; a tie the wearer keeps offers buttons
    out.append((names[18], "Window.lua: a tie pick is sent as a selection message", lua_mut(
        "Window.lua", "PostMessageToServer, LA.CH_PICK,", "PostMessageToServer, LA.CH_SEL,"), "red"))
    out.append((names[18], "Window.lua: the marker filter is not saved", lua_mut(
        "Window.lua", "  LA.SaveSettings()\n  if LA.ResendSelection", "  if LA.ResendSelection"), "red"))
    out.append((names[18], "Selected.lua: a new filter does not send the selection again", lua_mut(
        "Selected.lua", ", tostring(ctx.filter) }", " }"), "red"))
    out.append((names[18], "Window.lua: a tie the wearer keeps offers 'Give it to' buttons", lua_mut(
        "Window.lua", '    if t.by ~= "wear" then', "    if true then"), "red"))

    def meta_mut(text):
        def make():
            sc.reset()
            env = sc.env()
            env.file_overrides = {"meta.lsx Description": text}
            return env
        return make
    desc = C.meta_description()
    out.append((names[19], "meta.lsx: a description over the Toolkit's 250 characters", meta_mut(
        desc + " " + "x" * C.META_DESCRIPTION_MAX), "red"))
    out.append((names[19], "meta.lsx: the Script Extender line dropped from the description", meta_mut(
        desc.replace("Script Extender", "")), "red"))

    # 20. an exact tie's owner gets an alternative: the scorer gives it to the other tied characters only
    def m20():
        sc.reset()
        sc.patch("tools/score_items.py", 'if not own and keeps.get(it["sid"]) != cid:', "if not own:")
        sc.run_scoring()
        return sc.env()
    out.append((names[20], "score_items.py: no alternative for the owner of a tied item", m20, "red"))
    # 21a-21b. the owner's set keeps the item after the tie went elsewhere; no alternatives in the data at all
    out.append((names[21], "Logic.lua Recommend: a set ignores its alternative when the tie went to someone else",
                lua_mut("Logic.lua", 'elseif st and st.s == "better" and set.pa and set.pa[slot] then',
                        'elseif false then'), "red"))
    out.append((names[21], "LootData: no party alternatives in any set", lua_mut("LootData.lua", ",pa={", ",xpa={"),
                "red"))
    # 22a-22c. tie wording: the old "gets more" sentence; the keeper not first; F6 says "Better on" for a tie
    def file_mut(fname, rel, old, new):
        def make():
            sc.reset()
            src = open(os.path.join(LA, *rel), encoding="utf-8").read()
            if old not in src:
                raise RuntimeError(f"mutation target not found in {fname}: {old[:60]}")
            env = sc.env()
            env.file_overrides = {fname: src.replace(old, new)}
            return env
        return make
    ties_rel = ("tools", "sets_ship", "ties.js")
    out.append((names[22], "ties.js: a tie worded 'X gets more from it'", file_mut(
        "ties.js", ties_rel, 'return "Equal for " + list + (keep ? "; " + nameOf(keep) + " keeps it"',
        'return list + (keep ? "; " + nameOf(keep) + " gets more from it"'), "red"))
    out.append((names[22], "ties.js: the game's pick does not decide who keeps it", file_mut(
        "ties.js", ties_rel, "if (lc.pick) keep = lc.pick;", "if (false) keep = lc.pick;"), "red"))
    out.append((names[22], "app.js: the item card label says 'gets more from it' for a tie", file_mut(
        "app.js", ("tools", "sets_artifact", "app.js"), "say.push(tieSay(r.e, LIVE ? liveContest(set, r.e) : null) || ",
        "say.push("), "red"))
    out.append((names[22], "Window.lua: a settled tie shown as 'Better on X'", lua_mut(
        "Window.lua", 'elseif s == "better" and r.picked then', 'elseif false then'), "red"))
    # 23a-23c. pause menu: GameMenu not recognised; the window not closed; never reopened
    out.append((names[23], "UiTree.lua: the GameMenu widget is not recognised", lua_mut(
        "UiTree.lua", "LA.UI.PAUSE_WIDGETS = { GameMenu = true,", "LA.UI.PAUSE_WIDGETS = { GameMenuX = true,"), "red"))
    out.append((names[23], "Window.lua: the window stays open under the pause menu", lua_mut(
        "Window.lua", "    W.window.Open = false\n  elseif W.reopen then", "  elseif W.reopen then"), "red"))
    out.append((names[23], "Window.lua: the window is not reopened after the pause menu", lua_mut(
        "Window.lua", "  elseif W.reopen then", "  elseif false then"), "red"))
    out.append((names[23], "UiTree.lua: the game's message box (Dialog_box) is not recognised", lua_mut(
        "UiTree.lua", "Dialog_box = true, MessageBox_c = true }", "MessageBox_c = true }"), "red"))
    out.append((names[23], "UiTree.lua: the controller message box (MessageBox_c) is not recognised", lua_mut(
        "UiTree.lua", "Dialog_box = true, MessageBox_c = true }", "Dialog_box = true }"), "red"))
    # 25a-25f. one name per character: the origin's name used where the game's name is known
    out.append((names[24], "Common.lua: LA.CharName ignores the game's names", lua_mut(
        "Common.lua", 'if type(n) == "string" and n ~= "" and n ~= "?" then return n end', ""), "red"))
    out.append((names[24], "Tooltip.lua: a settled tie names the origin", lua_mut(
        "Tooltip.lua", 'body = "Equal; " .. LA.CharName(r.better) .. " keeps it"',
        'body = "Equal; " .. (LA.CHAR_NAME[r.better] or r.better) .. " keeps it"'), "red"))
    out.append((names[24], "Window.lua: F6 names the origin", lua_mut(
        "Window.lua", "local function cname(c) return LA.CharName(c) end",
        "local function cname(c) return LA.CHAR_NAME[c] or tostring(c) end"), "red"))
    out.append((names[24], "Window.lua: F6 header names the origin for the Dark Urge", lua_mut(
        "Window.lua", "local who = LA.CharName(res.char, res.name)",
        "local who = LA.CHAR_NAME[res.char] or res.name or tostring(res.char)"), "red"))
    out.append((names[24], "app.js: the Sets page names the origin in a live game", file_mut(
        "app.js", ("tools", "sets_artifact", "app.js"), "function names(ids) { return (ids || []).map(charName)",
        "function names(ids) { return (ids || []).map(function (o) { return CHAR_NAME[o] || o; })"), "red"))
    out.append((names[24], "Server/Main.lua: the party's names are not sent with the result", file_mut(
        "Server/Main.lua", ("LootAdvisor", "Mods", "LootAdvisor", "ScriptExtender", "Lua", "Server", "Main.lua"),
        "  res.names = names\n", "\n"), "red"))
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
            env, crashed = None, False
            try:
                env = make()
                fails = by[name](env)
            except Exception as e:  # noqa: BLE001
                crashed = True
                fails = [f"mutation setup/check crashed: {e!r}"]
            red = bool(fails)
            # a crash proves nothing about the check, so it fails the mutation whatever was expected
            ok = not crashed and (red if expect == "red" else not red)
            bad += not ok
            verdict = "CRASHED (proves nothing)" if crashed else \
                ("caught (red)" if red else "NOT caught (green)") if expect == "red" else \
                ("green as expected" if not red else "STILL RED")
            note = getattr(env, "mut_note", None)
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
