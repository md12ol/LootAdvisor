"""Gauntlet harness tests that need neither the game nor game data.

    python tests/test_gauntlet.py

- the in-game Lua (tools/gauntlet/gauntlet.lua, gauntlet_ui.lua) compiles; with stubbed engine tables the server file
  loads and its pure helpers behave: cost parsing, the shared adaptive item rule (same input -> same choice, logs
  every candidate), the arena layout;
- run.py statistics: the bootstrap interval contains the mean and narrows with more rounds;
- plan.py helpers: upcast variant choice, one bonus action per round, hotbar rows by role;
- reactions: policy mapping, save / apply / restore of the player's settings, the in-turn guard (scripted turns only).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
G_DIR = os.path.join(LA, "tools", "gauntlet")
sys.path.insert(0, G_DIR)

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


STUBS = r"""
local noop = function() end
local ev = setmetatable({}, { __index = function() return { Subscribe = function() return 1 end, Unsubscribe = noop } end })
Ext = { Utils = { MonotonicTime = function() return 0 end, LoadString = load }, Events = ev,
  Osiris = { RegisterListener = noop }, Timer = { WaitFor = function(_, f) f() end },
  Entity = { Get = function() return nil end }, Stats = { Get = function() return nil end },
  StaticData = { Get = function() return nil end }, IO = { SaveFile = noop, LoadFile = function() return nil end },
  Json = { Stringify = function() return "{}" end, Parse = function() return {} end },
  Level = { GetHeightsAt = function() return {} end }, ServerNet = { BroadcastMessage = noop }, System = {} }
Osi = setmetatable({}, { __index = function() return function() return nil end end })
"""


def lua_tests():
    try:
        import lupa
    except ImportError:
        print("skip Lua tests (pip install lupa)")
        return
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    for f in ("gauntlet.lua", "gauntlet_ui.lua"):
        with open(os.path.join(G_DIR, f), encoding="utf-8") as fh:
            err = L.eval("function(s) local f, e = load(s) return e end")(fh.read())
        check(f"{f} compiles", err is None, str(err))
    L.execute(STUBS)
    with open(os.path.join(G_DIR, "gauntlet.lua"), encoding="utf-8") as fh:
        res = L.eval("function(s) return load(s)() end")(fh.read())
    check("gauntlet.lua loads with stubbed engine", "loaded" in str(res), str(res))
    G = L.globals().GAUNTLET
    c = G._parseCosts("ActionPoint:1;SpellSlotsGroup:1:1:3")
    check("costs: action + level-3 slot", c[1].kind == "ActionPoint" and c[2].kind == "SpellSlot" and c[2].level == 3)
    L.execute(r"""
      local G = GAUNTLET
      local function F() return { cooldown = {}, plan = { item_actions = {
        { spell = "Zone_X", item = "Staff", group = "action", per = "short" },
        { spell = "Target_B", item = "Ring", group = "bonus", per = "none" },
        { spell = "Interrupt_R", item = "Cloak", group = "reaction", per = "none" } } } } end
      local core = { { spell = "Target_MainHandAttack", group = "action" },
                     { spell = "Target_MainHandAttack", group = "free", requires = "action" } }
      local R1, R2 = { done = {} }, { done = {} }
      T_out1 = G._itemRule(F(), core, R1)
      T_out2 = G._itemRule(F(), core, R2)
      T_log = R1.item_rule
      local f3 = F(); f3.cooldown["Zone_X"] = "short"
      T_out3 = G._itemRule(f3, { { spell = "A", group = "action" }, { spell = "B", group = "bonus" } }, { done = {} })
    """)
    g = L.globals()
    o1 = [g.T_out1[i + 1].spell for i in range(len(g.T_out1))]
    o2 = [g.T_out2[i + 1].spell for i in range(len(g.T_out2))]
    check("item rule: per-rest action replaces the core action group", o1[:1] == ["Zone_X"] and
          "Target_MainHandAttack" not in o1, str(o1))
    check("item rule: bonus item fills the free bonus action", "Target_B" in o1, str(o1))
    check("item rule: same input, same choice (both sets of a pair)", o1 == o2)
    check("item rule: every candidate logged", len(g.T_log) == 3 and all(g.T_log[i + 1].result for i in range(3)))
    o3 = [g.T_out3[i + 1].spell for i in range(len(g.T_out3))]
    check("item rule: used-this-rest and busy bonus action skipped", o3 == ["A", "B"], str(o3))
    L.execute('T_c, T_p = GAUNTLET.arena("pack", "throw", false, {0, 0, 0})')
    pts = g.T_p
    check("arena: pack = 4 enemies at throwing range", len(pts) == 4 and all(5.0 <= pts[i + 1][1] <= 8.5
                                                                              for i in range(4)))
    L.execute('T_c, T_p = GAUNTLET.arena("pack", "caster", true, {0, 0, 0})')
    import math
    d = [math.hypot(g.T_p[i + 1][1], g.T_p[i + 1][3]) for i in range(4)]
    check("arena: self-centred aura -> enemies around the character", all(1.5 < x < 3.0 for x in d), str(d))
    L.execute('T_c, T_p = GAUNTLET.arena("pack", "caster", false, {0, 0, 0}, '
              '{ start = {10, 5, 20}, dir = {0, 1}, high = {13, 9, 30} })')
    p = [(g.T_p[i + 1][1], g.T_p[i + 1][3]) for i in range(4)]
    check("arena: the character starts on the arena's start spot", g.T_c[1] == 10 and g.T_c[3] == 20)
    check("arena: enemies laid out along the arena's direction", all(abs(z - 30.0) <= 2.0 for _, z in p[:3]), str(p))
    check("arena: a pack's fourth enemy on the high ground", p[3] == (13, 30), str(p))
    with open(os.path.join(G_DIR, "arenas.json"), encoding="utf-8") as fh:
        import json
        ar = json.load(fh)
    check("arenas.json: every arena has level, centre, radius, start, park",
          all(all(k in a for k in ("level", "center", "radius", "start", "park")) for a in ar.values()))
    reaction_tests(L)


def reaction_tests(L):
    """Reaction policy: flag mapping, save / apply / read back / restore with a stub character, and the in-turn guard
    that only acts on scripted turns."""
    L.execute(r"""
      local P1 = { Interrupt_DestructiveWrath = "InterruptInteractionTypes(Ask,Enabled)",
                   Interrupt_AttackOfOpportunity = "InterruptInteractionTypes(Enabled)",
                   Interrupt_Shield = "InterruptInteractionTypes()" }
      T_orig = {}
      for k, v in pairs(P1) do T_orig[k] = v end
      -- stub: assignments store flag lists, reads give the game's string form back
      local store = {}
      for k, v in pairs(P1) do store[k] = GAUNTLET.flagsFromString(v) end
      local prefs
      prefs = setmetatable({}, {
        __index = function(_, k) local f = store[k]; return f and ("InterruptInteractionTypes(" .. table.concat(f, ",") .. ")") end,
        __newindex = function(_, k, v) store[k] = v end,
        __pairs = function() local k; return function() k = next(store, k); if k then return k, prefs[k] end end end })
      T_store = store
      local ent = { InterruptPreferences = { Preferences = prefs }, Replicate = function() end }
      Ext.Entity.Get = function(u) if u == "c1" then return ent end end
      Osi.DB_Players = { Get = function() return { { "c1" } } end }
      Osi.GetDisplayName = function() return nil end
      local G = GAUNTLET
      T_map = { G.reactionFlags("auto"), G.reactionFlags("never"), G.reactionFlags("ask"), G.reactionFlags("bogus") }
      T_pol = { G.reactionPolicy("Interrupt_Shield", { reactions = { Interrupt_Shield = "never" } }),
                G.reactionPolicy("Interrupt_Shield", {}), G.reactionPolicy("Interrupt_X", { reactions_default = "never" }) }
      T_rep = G.reactionsApply({ reactions = { Interrupt_Shield = "never" } })
      T_after = {}
      for k, v in pairs(store) do T_after[k] = table.concat(v, ",") end
      T_n = G.reactionsRestore()
      T_back = {}
      for k, v in pairs(store) do T_back[k] = table.concat(v, ",") end
      -- guard: an open prompt for c1
      Ext.Entity.GetAllEntitiesWithComponent = function()
        return { { InterruptActionState = { SpellCastGuid = "g", Actions = { { Observer = { Uuid = { EntityUuid = "c1" } },
          Interrupt = { InterruptData = { Interrupt = "Interrupt_DestructiveWrath" } } } } } } }
      end
      G.results = {}
      T_guard_manual = G.reactionGuard({ char = "c1", manual = true })
      T_guard_script = G.reactionGuard({ char = "c1", manual = false })
      T_misses = G.results.reaction_misses and #G.results.reaction_misses or 0
    """)
    g = L.globals()

    def lst(t):
        return [t[i + 1] for i in range(len(t))]
    m = [lst(g.T_map[i + 1]) for i in range(4)]
    check("reactions: auto = fires without asking, never = off, ask = game asks, unknown = auto",
          m == [["Enabled"], [], ["Ask", "Enabled"], ["Enabled"]], str(m))
    p = [g.T_pol[i + 1] for i in range(3)]
    check("reactions: the plan names a reaction / default auto / plan default", p == ["never", "auto", "never"], str(p))
    after = dict(g.T_after.items())
    check("reactions: applied (no Ask left, the named one off)", after == {
        "Interrupt_DestructiveWrath": "Enabled", "Interrupt_AttackOfOpportunity": "Enabled", "Interrupt_Shield": ""},
        str(after))
    check("reactions: read back and verified", g.T_rep["c1"].verified is True)
    back = dict(g.T_back.items())
    check("reactions: the player's own settings restored after the run", g.T_n == 1 and back == {
        "Interrupt_DestructiveWrath": "Ask,Enabled", "Interrupt_AttackOfOpportunity": "Enabled",
        "Interrupt_Shield": ""}, str(back))
    check("reactions guard: does nothing while a person has control", g.T_guard_manual is None)
    check("reactions guard: a prompt in a scripted turn is logged as a miss",
          g.T_guard_script == "Interrupt_DestructiveWrath" and g.T_misses == 1)


def py_tests():
    import plan as P
    import run as R
    xs = [10, 20, 30, 40, 50, 60, 70, 80]
    lo, hi = R.boot_ci(xs)
    check("bootstrap CI contains the mean", lo <= R.mean(xs) <= hi, f"{lo} {hi}")
    lo2, hi2 = R.boot_ci(xs * 8)
    check("bootstrap CI narrows with more rounds", (hi2 - lo2) < (hi - lo))
    stats = {"Zone_LightningBolt": {}, "Zone_LightningBolt_4": {}, "Zone_LightningBolt_5": {}}
    check("upcast: highest variant the slots allow", P.best_variant(stats, "Zone_LightningBolt", 4) == "Zone_LightningBolt_4")
    check("upcast: base spell without variants", P.best_variant({}, "Projectile_FireBolt", 6) == "Projectile_FireBolt")
    plan = {"rounds": [[P.A("Throw_Throw", "action"), P.A("Shout_Rage", "bonus", "@self")],
                       [P.A("Throw_Throw", "action"), P.A("Throw_FrenziedThrow", "bonus")]],
            "steady": [P.A("Throw_Throw", "action"), P.A("Throw_FrenziedThrow", "bonus")]}
    st = {"Throw_Throw": {"UseCosts": "ActionPoint:1"}, "Shout_Rage": {"UseCosts": "BonusActionPoint:1;Rage:1"},
          "Throw_FrenziedThrow": {"UseCosts": "BonusActionPoint:1"}, "RageUnlock": {"Boosts": "UnlockSpell(Shout_Rage)"},
          "Shout_Thaumaturgy": {"UseCosts": "ActionPoint:1"}, "Target_Shove": {"UseCosts": "BonusActionPoint:1"},
          "GWM": {"Properties": "IsToggled"}}
    rows = {r["label"]: r for r in P.hotbar_rows(plan, ["RageUnlock", "GWM"], ["Shout_Thaumaturgy"], [], st)}
    check("hotbar: plan actions by role", rows["opener"]["spells"] == ["Throw_Throw"] and
          rows["bonus action"]["spells"][:2] == ["Shout_Rage", "Throw_FrenziedThrow"], str(rows))
    check("hotbar: toggles from the granted passives", rows["reactions and toggles"]["passives"] == ["GWM"])
    check("hotbar: out-of-combat utility left out", all("Thaumaturgy" not in s for r in rows.values()
                                                         for s in r["spells"]))
    check("hotbar: common combat actions added", "Target_Shove" in rows["bonus action"]["spells"])
    check("items: the story copy of Gortash's gloves is never spawned",
          P.item_template("MAG_Gortash_Gloves", {"MAG_Gortash_Gloves": ["story-copy"]}) == P.SAFE_TEMPLATE["MAG_Gortash_Gloves"])
    check("items: other items keep their first template", P.item_template("X", {"X": ["t1", "t2"]}) == "t1")


if __name__ == "__main__":
    lua_tests()
    py_tests()
    print(f"{len(FAILS)} failed" if FAILS else "all passed")
    sys.exit(1 if FAILS else 0)
