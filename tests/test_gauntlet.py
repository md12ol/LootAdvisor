"""Gauntlet harness tests that need neither the game nor game data.

    python tests/test_gauntlet.py            the tests
    python tests/test_gauntlet.py --mutate   break each guarded rule in a scratch copy of tools/gauntlet and prove the
                                             tests go red (the repo itself is never modified)

- the in-game Lua (tools/gauntlet/gauntlet.lua, gauntlet_ui.lua) compiles; with stubbed engine tables the server file
  loads and its pure helpers behave: cost parsing, the shared adaptive item rule (same input -> same choice, logs
  every candidate, only affordable item spells, the core action as fallback), the arena layout;
- casts count only when the engine shows them (cast event, damage, resource spent); a miss is a failure with fallback;
- each round is planned from the resources the character has (upcast chains, Channel Divinity) and checked again;
- reactions: policy mapping (default never), every interrupt the character has, save / apply / restore, the guard;
- the turn watchdog recovers, then ends the run as invalid; a run starts without blocking the eval; run validity;
- run.py statistics, run validity and the control-pair gate; engine.py retries and invalid runs;
- plan.py helpers: upcast chains, the affordability forecast, reaction answers, hotbar rows by role.
"""
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
G_DIR = os.path.join(LA, "tools", "gauntlet")
if "--gdir" in sys.argv:
    G_DIR = sys.argv[sys.argv.index("--gdir") + 1]
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


def lst(t):
    return [t[i + 1] for i in range(len(t))] if t is not None else None


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
      local yes = function() return true end
      local function F() return { cooldown = {}, afford = yes, plan = { item_actions = {
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
    groups1 = [g.T_out1[i + 1].group for i in range(len(g.T_out1))]
    check("item rule: per-rest action replaces the core action group", o1[:1] == ["Zone_X"] and
          groups1.count("action") == 1, str(o1))
    check("item rule: the replaced core action is the item action's fallback",
          g.T_out1[1].alt is not None and g.T_out1[1].alt.spell == "Target_MainHandAttack", str(o1))
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
    d = [math.hypot(g.T_p[i + 1][1], g.T_p[i + 1][3]) for i in range(4)]
    check("arena: self-centred aura -> enemies around the character", all(1.5 < x < 3.0 for x in d), str(d))
    L.execute('T_c, T_p = GAUNTLET.arena("pack", "caster", false, {0, 0, 0}, '
              '{ start = {10, 5, 20}, dir = {0, 1}, high = {13, 9, 30} })')
    p = [(g.T_p[i + 1][1], g.T_p[i + 1][3]) for i in range(4)]
    check("arena: the character starts on the arena's start spot", g.T_c[1] == 10 and g.T_c[3] == 20)
    check("arena: enemies laid out along the arena's direction", all(abs(z - 30.0) <= 2.0 for _, z in p[:3]), str(p))
    check("arena: a pack's fourth enemy on the high ground", p[3] == (13, 30), str(p))
    with open(os.path.join(G_DIR, "arenas.json"), encoding="utf-8") as fh:
        ar = json.load(fh)
    check("arenas.json: every arena has level, centre, radius, start, park",
          all(all(k in a for k in ("level", "center", "radius", "start", "park")) for a in ar.values()))
    for t in (reaction_tests, item_cost_tests, cast_tests, plan_round_tests, watchdog_tests, verdict_tests):
        try:
            t(L)
        except Exception as e:  # noqa: BLE001 - a broken block is a failed test, not a crash
            check(f"{t.__name__} ran", False, repr(e)[:300])


def reaction_tests(L):
    """Reaction policy: flag mapping, save / apply / read back / restore with a stub character, every interrupt the
    character has (also ones missing from the preference map), and the in-turn guard (scripted turns only)."""
    L.execute(r"""
      local P1 = { Interrupt_DestructiveWrath = "InterruptInteractionTypes(Ask,Enabled)",
                   Interrupt_AttackOfOpportunity = "InterruptInteractionTypes(Enabled)",
                   Interrupt_Shield = "InterruptInteractionTypes()" }
      -- stub: assignments store flag lists, reads give the game's string form back
      local store = {}
      for k, v in pairs(P1) do store[k] = GAUNTLET.flagsFromString(v) end
      local prefs
      prefs = setmetatable({}, {
        __index = function(_, k) local f = store[k]; return f and ("InterruptInteractionTypes(" .. table.concat(f, ",") .. ")") end,
        __newindex = function(_, k, v) store[k] = v end,
        __pairs = function() local k; return function() k = next(store, k); if k then return k, prefs[k] end end end })
      -- a racial reaction and a tadpole power the preference map does not list
      local ent = { InterruptPreferences = { Preferences = prefs }, Replicate = function() end,
        InterruptContainer = { Interrupts = { { InterruptData = { Interrupt = "Interrupt_HellishRebuke" } } } },
        SpellBook = { Spells = { { Id = { Prototype = "Interrupt_Charm" } }, { Id = { Prototype = "Target_Fly" } } } } }
      Ext.Entity.Get = function(u) if u == "c1" then return ent end end
      Osi.DB_Players = { Get = function() return { { "c1" } } end }
      Osi.GetDisplayName = function() return nil end
      local G = GAUNTLET
      T_map = { G.reactionFlags("auto"), G.reactionFlags("never"), G.reactionFlags("ask"), G.reactionFlags("bogus") }
      T_pol = { G.reactionPolicy("Interrupt_Shield", { reactions = { Interrupt_Shield = "auto" } }),
                G.reactionPolicy("Interrupt_Shield", {}), G.reactionPolicy("Interrupt_X", { reactions_default = "auto" }) }
      T_known = G.knownInterrupts("c1")
      T_rep = G.reactionsApply({ reactions = { Interrupt_DestructiveWrath = "auto" }, reactions_default = "never" })
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
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Ext.Entity.Get = function() return nil end
      Osi.DB_Players = nil
    """)
    g = L.globals()
    m = [lst(g.T_map[i + 1]) for i in range(4)]
    check("reactions: auto = fires without asking, never = off, ask = game asks, unknown = never",
          m == [["Enabled"], [], ["Ask", "Enabled"], []], str(m))
    p = [g.T_pol[i + 1] for i in range(3)]
    check("reactions: the plan names a reaction / default never / plan default", p == ["auto", "never", "auto"], str(p))
    known = lst(g.T_known)
    check("reactions: every interrupt the character has (preferences, racial, tadpole), nothing else",
          known == ["Interrupt_AttackOfOpportunity", "Interrupt_Charm", "Interrupt_DestructiveWrath",
                    "Interrupt_HellishRebuke", "Interrupt_Shield"], str(known))
    after = dict(g.T_after.items())
    check("reactions: applied (only the plan's reaction fires; the test character's own ones are off)", after == {
        "Interrupt_DestructiveWrath": "Enabled", "Interrupt_AttackOfOpportunity": "", "Interrupt_Shield": "",
        "Interrupt_HellishRebuke": "", "Interrupt_Charm": ""}, str(after))
    check("reactions: read back and verified", g.T_rep["c1"].verified is True and len(g.T_rep["c1"].uncovered) == 0)
    back = dict(g.T_back.items())
    check("reactions: the player's own settings restored after the run", g.T_n == 1 and all(back[k] == v for k, v in {
        "Interrupt_DestructiveWrath": "Ask,Enabled", "Interrupt_AttackOfOpportunity": "Enabled",
        "Interrupt_Shield": ""}.items()), str(back))
    check("reactions guard: does nothing while a person has control", g.T_guard_manual is None)
    check("reactions guard: a prompt in a scripted turn is logged as a miss",
          g.T_guard_script == "Interrupt_DestructiveWrath" and g.T_misses == 1)


def item_cost_tests(L):
    """The item rule checks the cost before it chooses (the pilot spent the action on an item gaze it could not pay,
    every round): an unaffordable item spell is skipped with the reason and the next candidate / the core plan acts."""
    L.execute(r"""
      local G = GAUNTLET
      local pay = { Target_Gaze = false, Zone_Staff = true, Target_Ring = false }
      local function F() return { cooldown = {}, afford = function(a)
          if pay[a.spell] == false then return false, "no resource ActionPoint" end
          return true end,
        plan = { item_actions = {
          { spell = "Target_Gaze", item = "Helmet", group = "action", per = "short" },
          { spell = "Zone_Staff", item = "Staff", group = "action", per = "long" },
          { spell = "Target_Ring", item = "Ring", group = "bonus", per = "none" } } } } end
      local core = { { spell = "Projectile_FireBolt", group = "action" } }
      local R = { done = {} }
      T_ic = G._itemRule(F(), core, R)
      T_icl = R.item_rule
      pay.Zone_Staff = false
      local R2 = { done = {} }
      T_ic2 = G._itemRule(F(), core, R2)
    """)
    g = L.globals()
    out = [g.T_ic[i + 1].spell for i in range(len(g.T_ic))]
    logs = {g.T_icl[i + 1].spell: g.T_icl[i + 1].result for i in range(len(g.T_icl))}
    check("item rule: an item spell it cannot pay is skipped with the reason",
          logs["Target_Gaze"].startswith("skipped: cannot pay") and "ActionPoint" in logs["Target_Gaze"], str(logs))
    check("item rule: falls back to the next affordable item spell", out[:1] == ["Zone_Staff"], str(out))
    check("item rule: an unaffordable bonus item spell is not queued", "Target_Ring" not in out, str(out))
    out2 = [g.T_ic2[i + 1].spell for i in range(len(g.T_ic2))]
    check("item rule: nothing affordable -> the core action stays", out2 == ["Projectile_FireBolt"], str(out2))


def cast_tests(L):
    """A scripted action counts as done only when the engine shows it; a miss is a failure and runs the fallback."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local F = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, afford = function() return true end }
      local R = { r = 1, actions = {}, casts = {}, done = {} }
      local fb = { spell = "Projectile_FireBolt", group = "action", target = "@boss",
                   alt = { spell = "Projectile_RayOfFrost", group = "action", target = "@boss" } }
      G._doAction(F, fb, R)
      T_pend = R.actions[1].result
      T_ok1 = G.settle(F, R, 1000)                -- still waiting
      R.casts[#R.casts + 1] = { who = "e1", spell = "Projectile_FireBolt" }   -- someone else's cast
      T_ok2 = G.settle(F, R, 1500)
      T_ok3 = G.settle(F, R, G.CONFIRM_MS + 1)    -- timed out
      T_res1 = R.actions[1].result
      T_done1 = R.done.action
      T_alt = R.actions[2] and R.actions[2].spell
      R.casts[#R.casts + 1] = { who = "c1", spell = "Projectile_RayOfFrost" }
      T_ok4 = G.settle(F, R, G.CONFIRM_MS + 100)
      T_res2 = R.actions[2] and R.actions[2].result
      T_conf2 = R.actions[2] and R.actions[2].confirmed
      T_done2 = R.done.action
      T_miss = R.cast_misses
      -- evidence kinds
      local P = { who = "c1", spell = "Zone_LightningBolt_6", target = "e1", casts0 = 1, dmg0 = 1,
                  res = { { kind = "SpellSlot", level = 6, before = 1 } } }
      local old = { { who = "c1", spell = "Zone_LightningBolt" } }
      T_ev = {
        G.castEvidence(P, { old[1], { who = "c1", spell = "Zone_LightningBolt" } }, {}, nil),
        G.castEvidence(P, old, { { target = "e1", source = "x" }, { target = "e1", source = "c1", cause = "Attack" } }, nil),
        G.castEvidence(P, old, { {}, { target = "e1", source = "c1", cause = "Surface" } }, nil) or "none",
        G.castEvidence(P, old, {}, function() return 0 end),
        G.castEvidence(P, old, {}, function() return 1 end) or "none",
      }
    """)
    g = L.globals()
    check("cast: the engine accepting UseSpell is only 'pending'", g.T_pend == "pending" and g.T_ok1 is False)
    check("cast: another character's cast of the same spell is no proof", g.T_ok2 is False)
    check("cast: no cast within the timeout = failed, never done",
          g.T_ok3 is True and str(g.T_res1).startswith("failed") and g.T_done1 is None, str(g.T_res1))
    check("cast: a miss runs the fallback", g.T_alt == "Projectile_RayOfFrost")
    check("cast: confirmed by the cast event -> done", g.T_res2 == "done" and g.T_conf2 == "cast" and g.T_done2 is True,
          str(g.T_res2))
    check("cast: misses counted for the run", g.T_miss == 1)
    ev = [g.T_ev[i + 1] for i in range(5)]
    check("cast evidence: an upcast variant's cast counts for its base, earlier casts do not; damage to the target "
          "(not from a surface); a spent resource",
          ev == ["cast", "damage", "none", "resource", "none"], str(ev))


def plan_round_tests(L):
    """Each round is planned from what the character can pay now: the first affordable action of each priority chain;
    what was passed over is logged as a plan skip, not as a failed action."""
    L.execute(r"""
      local G = GAUNTLET
      local have = { Zone_LightningBolt_6 = false, Zone_LightningBolt_5 = true, Shout_RadianceOfTheDawn = false }
      local cantrip = { spell = "Projectile_FireBolt", group = "action", target = "@boss" }
      local lb = { spell = "Zone_LightningBolt_6", group = "action", target = "@boss",
        alt = { spell = "Zone_LightningBolt_5", group = "action", target = "@boss",
          alt = { spell = "Zone_LightningBolt", group = "action", target = "@boss", alt = cantrip } } }
      local rotd = { spell = "Shout_RadianceOfTheDawn", group = "action", target = "@self", alt = lb }
      local F = { char = "c1", cooldown = {}, S = { rounds = 16 }, afford = function(a)
          if have[a.spell] == false then return false, "no resource" end
          return true end,
        plan = { rounds = { { rotd, { spell = "Target_X", group = "free", requires = "action" } } }, steady = { rotd } } }
      local R = { r = 1, actions = {}, casts = {}, done = {} }
      T_q = G.planRound(F, R)
      T_sk = R.plan_skips
      have.Zone_LightningBolt_5, have.Zone_LightningBolt, have.Projectile_FireBolt = false, false, false
      local R2 = { r = 2, actions = {}, casts = {}, done = {} }
      T_q2 = G.planRound(F, R2)
      T_a2 = #R2.actions
    """)
    g = L.globals()
    q = [g.T_q[i + 1].spell for i in range(len(g.T_q))]
    sk = [g.T_sk[i + 1].spell for i in range(len(g.T_sk))]
    check("plan round: first affordable of the chain (no Channel Divinity, no L6 slot -> L5 upcast)",
          q[:1] == ["Zone_LightningBolt_5"], str(q))
    check("plan round: Extra-Attack style entries kept for the turn", "Target_X" in q, str(q))
    check("plan round: passed-over options logged as plan skips", sk == ["Shout_RadianceOfTheDawn",
                                                                         "Zone_LightningBolt_6"], str(sk))
    q2 = [g.T_q2[i + 1].spell for i in range(len(g.T_q2))]
    check("plan round: nothing affordable -> no action queued (and no failed action logged)",
          "Zone_LightningBolt_6" not in q2 and "Shout_RadianceOfTheDawn" not in q2 and g.T_a2 == 0, str(q2))


def watchdog_tests(L):
    """Turn watchdog (the pilot hung on 'turn never came'), ending the own turn, and a run start that never blocks."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.round = 3
      T_saved = 0
      Ext.IO.SaveFile = function() T_saved = T_saved + 1 end
      local F = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {},
                  rounds = 16, started = 1, state = "wait", deadline = 0 }
      G.F = F
      G.step(F, 1)
      T_r1 = F.state
      G.step(F, 1 + G.TURN_WAIT_MS + 1)
      T_rec = #(G.results.turn_recoveries or {})
      G.step(F, 2 * (G.TURN_WAIT_MS + 2))
      T_end = F.state
      T_valid = G.results.valid
      T_why = G.results.ended
      -- the character's own turn that will not end
      local me = { TurnBased = { IsActiveCombatTurn = true } }
      Ext.Entity.Get = function(u) if u == "c2" then return me end end
      G.reset(); G.round = 1
      local F2 = { char = "c2", enemies = {}, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                   started = 1, state = "ending", next = 0 }
      G.F = F2
      G.step(F2, 0)
      local t = 0
      for _ = 1, G.END_TURN_TRIES + 1 do t = t + G.END_TURN_MS + 1; G.step(F2, t) end
      T_end2, T_why2 = F2.state, G.results.ended
      Ext.Entity.Get = function() return nil end
      -- a run start returns at once; the work runs on timers
      local queue = {}
      Ext.Timer.WaitFor = function(_, f) queue[#queue + 1] = f end
      G.F = nil
      T_run = G.run({ mode = "scripted", scenario = "boss", label = "x" })
      T_status = G.status
      T_saved = 0
      for _ = 1, 50 do if #queue == 0 then break end; table.remove(queue, 1)() end
      T_after = G.status
      T_bad = G.results.invalid and G.results.invalid[1]
      -- prep that never finishes ends as an invalid run
      local prep = G.prep
      G.prep = function() G.status = "prepping" end
      G.PREP_MS = -1
      T_run2 = G.run({ mode = "scripted", scenario = "boss", label = "y", enemy = { template = "t" },
                       spec = { plan = {} }, char = "c1" })
      for _ = 1, 50 do if #queue == 0 then break end; table.remove(queue, 1)() end
      T_prep = G.results.ended
      T_prep_valid = G.results.valid
      G.prep, G.PREP_MS = prep, 120000
      Ext.Timer.WaitFor = function(_, f) f() end
      Ext.IO.SaveFile = function() end
    """)
    g = L.globals()
    check("watchdog: a missing turn is recovered first, not ended", g.T_r1 == "wait" and g.T_rec == 2, str(g.T_rec))
    check("watchdog: after the recoveries the run ends, invalid, with the cause",
          g.T_end == "done" and g.T_valid is False and "turn never came" in str(g.T_why), str(g.T_why))
    check("watchdog: an own turn that will not end is retried, then the run ends invalid",
          g.T_end2 == "done" and "could not be ended" in str(g.T_why2), str(g.T_why2))
    check("run start: returns at once, prep not yet started", g.T_run == "started" and g.T_status == "starting",
          f"{g.T_run} {g.T_status}")
    check("run start: a bad request still ends in an invalid run record",
          g.T_after == "done" and "bad request" in str(g.T_bad) and g.T_saved >= 1, str(g.T_bad))
    check("run start: prep that never finishes -> invalid run, not a hang",
          "prep timed out" in str(g.T_prep) and g.T_prep_valid is False, str(g.T_prep))


def verdict_tests(L):
    """Run validity and casts outside the plan (the test character's own reactions leaking into the numbers)."""
    L.execute(r"""
      local G = GAUNTLET
      local plan = { rounds = { { { spell = "Zone_LightningBolt_6", group = "action",
                                   alt = { spell = "Projectile_FireBolt", group = "action" } } } },
                     steady = {}, item_actions = { { spell = "Target_MAG_Gaze" } },
                     reactions = { Interrupt_DestructiveWrath = "auto", Interrupt_Charm = "never" } }
      local rounds = { { r = 1, done = { action = true }, casts = {
          { who = "c1", spell = "Zone_LightningBolt" }, { who = "c1", spell = "Projectile_FireBolt" },
          { who = "c1", spell = "Target_MAG_Gaze" }, { who = "c1", spell = "Target_DestructiveWrath" },
          { who = "c1", spell = "Target_HellishRebuke_5" }, { who = "c1", spell = "Target_Charm" },
          { who = "c1", spell = "Target_Legendary_ShieldBlow_Riposte" },
          { who = "e1", spell = "Target_Bite" } } },
        { r = 2, done = { item = true }, casts = {} }, { r = 3, done = {}, casts = {} } }
      T_fc = G.foreignCasts(rounds, "c1", plan)
      T_j1 = G.judge({ rounds[1], rounds[2] }, "rounds done", {}, { me = "c1" })
      T_j2 = G.judge(rounds, "rounds done", { foreign_casts = T_fc }, { me = "c1" })
      T_j3 = G.judge(rounds, "rounds done", {}, { me = "c1", char_acts = false })
      T_j4 = G.judge({}, "aborted", { reactions = { c1 = { verified = false, uncovered = { "Interrupt_X" } } } },
                     { me = "c1" })
    """)
    g = L.globals()
    fc = sorted(g.T_fc[i + 1].spell for i in range(len(g.T_fc)))
    check("verdict: the test character's own reactions are casts outside the plan; the plan's and the items' are not",
          fc == ["Target_Charm", "Target_HellishRebuke_5"], str(fc))
    check("verdict: a clean run is valid", g.T_j1.valid is True)
    j2 = lst(g.T_j2.causes)
    check("verdict: a round without a confirmed action and foreign casts make it invalid",
          g.T_j2.valid is False and any("without a confirmed action" in c for c in j2) and
          any("outside the plan" in c for c in j2), str(j2))
    check("verdict: defence rounds (the character only opens) need no action", g.T_j3.valid is True)
    j4 = lst(g.T_j4.causes)
    check("verdict: ended early / reactions not set -> invalid with causes",
          g.T_j4.valid is False and any("aborted" in c for c in j4) and any("Interrupt_X" in c for c in j4), str(j4))


def py_tests():
    import plan as P
    import run as R
    xs = [10, 20, 30, 40, 50, 60, 70, 80]
    lo, hi = R.boot_ci(xs)
    check("bootstrap CI contains the mean", lo <= R.mean(xs) <= hi, f"{lo} {hi}")
    lo2, hi2 = R.boot_ci(xs * 8)
    check("bootstrap CI narrows with more rounds", (hi2 - lo2) < (hi - lo))
    stats = {"Zone_LightningBolt": {"UseCosts": "ActionPoint:1;SpellSlotsGroup:1:1:3"},
             "Zone_LightningBolt_4": {"UseCosts": "ActionPoint:1;SpellSlotsGroup:1:1:4"},
             "Zone_LightningBolt_5": {"UseCosts": "ActionPoint:1;SpellSlotsGroup:1:1:5"},
             "Zone_LightningBolt_6": {"UseCosts": "ActionPoint:1;SpellSlotsGroup:1:1:6"},
             "Projectile_FireBolt": {"UseCosts": "ActionPoint:1"},
             "Shout_RadianceOfTheDawn": {"UseCosts": "ActionPoint:1;ChannelDivinity:1"}}
    ch = P.upcast_chain(stats, "Zone_LightningBolt", [1, 2, 3, 4, 6])
    check("upcast chain: highest slot first, down to the base, only levels the character has",
          ch == ["Zone_LightningBolt_6", "Zone_LightningBolt_4", "Zone_LightningBolt"], str(ch))
    check("upcast chain: base spell without variants", P.upcast_chain({}, "Projectile_FireBolt", [6]) ==
          ["Projectile_FireBolt"])
    act = P.chain(P.upcast_chain(stats, "Zone_LightningBolt", [3, 4, 5, 6]), "action", "@boss", "nuke",
                  tail=P.A("Projectile_FireBolt", "action"))
    rotd = P.A("Shout_RadianceOfTheDawn", "action", "@self", alt=act)
    plan = {"rounds": [[rotd]], "steady": [rotd]}
    fc = P.forecast(plan, {"3": 3, "4": 3, "5": 2, "6": 1}, [{"kind": "ChannelDivinity", "level": 0, "n": 2}], stats,
                    n_rounds=12)
    first = [r[0] if r else None for r in fc]
    check("forecast: Channel Divinity twice, the L6 slot once, then lower slots, then the cantrip - never a cast it "
          "cannot pay",
          first == ["Shout_RadianceOfTheDawn"] * 2 + ["Zone_LightningBolt_6"] + ["Zone_LightningBolt_5"] * 2 +
          ["Zone_LightningBolt_4"] * 3 + ["Zone_LightningBolt"] * 3 + ["Projectile_FireBolt"], str(first))
    check("plan spells: fallbacks are learned too", P.plan_spells(plan) >= {"Zone_LightningBolt_5",
                                                                          "Projectile_FireBolt"})
    st_i = {"MAG_Helm": {"Boosts": "UnlockInterrupt(Interrupt_Item_Shield)", "PassivesOnEquip": "MAG_P"},
            "MAG_P": {"Boosts": "UnlockInterrupt(Interrupt_Item_Riposte)"},
            "Cls_P": {"Boosts": "UnlockInterrupt(Interrupt_DestructiveWrath)"}}
    gi = P.granted_interrupts(["Cls_P"], ["MAG_Helm"], st_i)
    check("reactions: the build's and the set's interrupts (also through an item's passive)",
          gi == ["Interrupt_DestructiveWrath", "Interrupt_Item_Shield", "Interrupt_Item_Riposte"], str(gi))
    pol = P.reaction_policy(["Interrupt_DestructiveWrath"], ["Interrupt_Item_Shield"])
    check("reactions: plan answers = the build's and the set's reactions fire, nothing else listed",
          pol == {"Interrupt_DestructiveWrath": "auto", "Interrupt_Item_Shield": "auto",
                  "Interrupt_AttackOfOpportunity": "auto"} and "Interrupt_HellishRebuke" not in pol, str(pol))
    hplan = {"rounds": [[P.A("Throw_Throw", "action"), P.A("Shout_Rage", "bonus", "@self")],
                        [P.A("Throw_Throw", "action"), P.A("Throw_FrenziedThrow", "bonus")]],
             "steady": [P.A("Throw_Throw", "action"), P.A("Throw_FrenziedThrow", "bonus")]}
    st = {"Throw_Throw": {"UseCosts": "ActionPoint:1"}, "Shout_Rage": {"UseCosts": "BonusActionPoint:1;Rage:1"},
          "Throw_FrenziedThrow": {"UseCosts": "BonusActionPoint:1"}, "RageUnlock": {"Boosts": "UnlockSpell(Shout_Rage)"},
          "Shout_Thaumaturgy": {"UseCosts": "ActionPoint:1"}, "Target_Shove": {"UseCosts": "BonusActionPoint:1"},
          "GWM": {"Properties": "IsToggled"}}
    rows = {r["label"]: r for r in P.hotbar_rows(hplan, ["RageUnlock", "GWM"], ["Shout_Thaumaturgy"], [], st)}
    check("hotbar: plan actions by role", rows["opener"]["spells"] == ["Throw_Throw"] and
          rows["bonus action"]["spells"][:2] == ["Shout_Rage", "Throw_FrenziedThrow"], str(rows))
    check("hotbar: toggles from the granted passives", rows["reactions and toggles"]["passives"] == ["GWM"])
    check("hotbar: out-of-combat utility left out", all("Thaumaturgy" not in s for r in rows.values()
                                                         for s in r["spells"]))
    check("hotbar: common combat actions added", "Target_Shove" in rows["bonus action"]["spells"])
    check("items: the story copy of Gortash's gloves is never spawned",
          P.item_template("MAG_Gortash_Gloves", {"MAG_Gortash_Gloves": ["story-copy"]}) == P.SAFE_TEMPLATE["MAG_Gortash_Gloves"])
    check("items: other items keep their first template", P.item_template("X", {"X": ["t1", "t2"]}) == "t1")
    for t in (lambda: gate_tests(R), engine_tests):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            check("python test block ran", False, repr(e)[:300])


def _rec(pair, side, dealt, valid=True, invalid=None, scenario="boss"):
    return {"mode": "scripted", "pair": pair, "side": side, "scenario": scenario, "haste": False, "valid": valid,
            "invalid": invalid or [], "results": {"summary": {"dealt": dealt, "taken": [0] * len(dealt), "max_hp": 100}}}


def _pair(char, da, db, control=None):
    p = {"char": char, "build": "b", "act": 3, "model": {"a_dpr": da, "b_dpr": db},
         "specs": {s: {"set": s, "sheet": {"hp": 100}, "expect": {"score": 1.0, "dpr": d, "R": 1}}
                   for s, d in (("a", da), ("b", db))}}
    if control is not None:
        p["control"] = control
    return p


def gate_tests(R):
    """Run validity and the control-pair gate. Numbers from the first in-game pilot: the control (two sets the model
    rates 129.9 vs 132.6 DPR) measured 11.8 vs 23.2 per round, a harness gap."""
    check("validity: the game's verdict is kept", R.run_validity(_rec(0, "a", [1], False, ["2 round(s) without a "
                                                                                        "confirmed action"]))[0] is False)
    check("validity: an error record is invalid with its cause",
          R.run_validity({"error": "the game did not answer", "req": {}}) == (False, ["the game did not answer"]))
    check("validity: a complete record is valid", R.run_validity(_rec(0, "a", [5, 6])) == (True, []))
    pairs = [_pair("shadowheart", 89.8, 59.8), _pair("gale", 129.9, 132.6)]
    check("control: equal model DPR (within 5%) marks a control pair; a clear model gap does not",
          R.is_control(pairs[1]) and not R.is_control(pairs[0]))
    check("control: an explicit flag wins", R.is_control(_pair("x", 10, 50, control=True)))
    pilot_a = [82, 0, 38, 0, 22, 0, 0, 26, 0, 0, 20, 0, 0, 0, 0, 0]
    pilot_b = [57, 49, 93, 56, 23, 0, 28, 0, 0, 23, 0, 0, 0, 29, 0, 14]
    by = {(1, "a", "boss", False): {"dealt": pilot_a}, (1, "b", "boss", False): {"dealt": pilot_b},
          (0, "a", "boss", False): {"dealt": [100] * 16}, (0, "b", "boss", False): {"dealt": [60] * 16}}
    gate = R.control_gate(pairs, by, 0.15)
    check("control gate: the pilot's control (11.8 vs 23.2) makes the result invalid",
          gate["valid"] is False and "control pair 1" in gate["causes"][0], str(gate))
    by[(1, "b", "boss", False)] = {"dealt": [x * 1.05 for x in pilot_a]}
    check("control gate: a control within tolerance passes (the disagreement pair is not a control)",
          R.control_gate(pairs, by, 0.15)["valid"] is True)
    by.pop((1, "b", "boss", False))
    check("control gate: a control measured on one side only is not a pass",
          R.control_gate(pairs, by, 0.15)["valid"] is False)
    check("control gate: no control pair -> unchecked", R.control_gate(pairs[:1], by, 0.15)["valid"] is None)
    d = tempfile.mkdtemp(prefix="gauntlet_test_")
    try:
        sp, rs = os.path.join(d, "specs.json"), os.path.join(d, "results.jsonl")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(pairs, f)
        with open(rs, "w", encoding="utf-8") as f:
            for r in (_rec(0, "a", [100] * 16), _rec(0, "b", [60] * 16), _rec(1, "a", pilot_a), _rec(1, "b", pilot_b),
                      _rec(1, "b", [999] * 16, False, ["ended: aborted"]),
                      {"error": "the run did not finish", "pair": 1, "side": "a", "req": {"scenario": "boss"}}):
                f.write(json.dumps(r) + "\n")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g = R.main(["--report", rs, "--specs", sp])
        text = buf.getvalue()
        check("report: PILOT INVALID at the top when the control fails", g["valid"] is False and
              text.startswith("**PILOT INVALID**"), text[:200])
        check("report: invalid runs are listed and left out of the numbers", "Invalid runs (left out)" in text and
              "ended: aborted" in text and "999" not in text and "the run did not finish" in text, text[-400:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def engine_tests():
    """engine.run: a busy game that misses evals is asked again; a game that stops answering, or a run that never
    finishes, is an invalid run with its cause, never a hang."""
    import engine as E
    d = tempfile.mkdtemp(prefix="gauntlet_runs_")
    old = (E.ev, E.RUNS, E.write_se)
    try:
        E.RUNS, E.write_se = d, (lambda name, obj: None)
        calls = []

        def fake(script):
            it = itertools.chain(script, itertools.repeat(script[-1] if isinstance(script[-1], str) else "timeout"))

            def ev(code, timeout=10.0, side="server"):
                calls.append(code)
                step = next(it, "timeout")
                if callable(step):
                    step = step()
                if step == "timeout":
                    raise TimeoutError("no answer")
                return step
            return ev

        def write_record():
            with open(os.path.join(d, "run_1_001.json"), "w", encoding="utf-8") as f:
                json.dump({"results": {"summary": {"dealt": [1]}}, "valid": True}, f)
            return "fighting r1 x"
        E.ev = fake(["timeout", "timeout", "timeout", write_record])
        try:
            rec = E.run({"label": "x", "run_id": "x"}, {"plan": {}}, poll=0.0, log=lambda *a: None)
        except E.RunInvalid as e:
            rec = {"error": str(e)}
        check("engine: missed evals are retried and the run record is returned", rec.get("valid") is True, str(rec))
        for fn in os.listdir(d):
            os.remove(os.path.join(d, fn))
        E.ev = fake(["started", "timeout"])
        try:
            E.run({"label": "y", "run_id": "y"}, None, poll=0.0, log=lambda *a: None, max_misses=3)
            raised = None
        except E.RunInvalid as e:
            raised = str(e)
        check("engine: a game that stops answering -> RunInvalid with the cause, not a hang",
              raised is not None and "did not answer" in raised, str(raised))
        calls.clear()
        E.ev = fake(["no answer yet", "idle r0 nil", "idle r0 nil", "idle r0 nil", "started",
                     "fighting r1 z", "fighting r1 z"])
        try:
            E.run({"label": "z", "run_id": "z"}, None, poll=0.0, timeout=0.05, log=lambda *a: None)
        except E.RunInvalid as e:
            raised = str(e)
        starts = sum(1 for c in calls if "GAUNTLET.run(" in c)
        check("engine: a start the game never showed is sent once more (and only once)", starts == 2, str(starts))
        check("engine: a run that does not finish in time is invalid", "did not finish" in str(raised), str(raised))
    finally:
        E.ev, E.RUNS, E.write_se = old
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================================ mutations
GL, PL, RN, EN = "gauntlet.lua", "plan.py", "run.py", "engine.py"
MUTATIONS = [
    ("casts: UseSpell returning counts as done", GL, 'rec.result = "pending"\n  F.pending = P',
     'rec.result = "done"; R.done[a.group or "free"] = true'),
    ("casts: any caster's cast confirms", GL, "if c.who == P.who and baseSpell(c.spell)", "if baseSpell(c.spell)"),
    ("casts: a miss without its fallback", GL, '    P.rec.result = P.rec.result .. " -> alt"\n    doAction(F, P.a.alt, R)',
     '    P.rec.result = P.rec.result .. " -> alt"'),
    ("round plan: no affordability check", GL, "local pick = a.requires and a or G.pickAffordable(F, a, R.plan_skips)",
     "local pick = a"),
    ("item rule: no cost check", GL, 'elseif (it.group == "action" or it.group == "bonus") and not okp then',
     "elseif false then"),
    ("item rule: no core action fallback", GL, 'entry.alt, entry.done_key = core, "item"', 'entry.done_key = "item"'),
    ("reactions: default auto", GL, 'plan.reactions_default) or "never"', 'plan.reactions_default) or "auto"'),
    ("reactions: preference map only", GL,
     "for _, x in ipairs(e and try(function() return e.InterruptContainer.Interrupts end) or {}) do",
     "for _, x in ipairs({}) do"),
    ("watchdog: never gives up", GL, "if F.recoveries > G.TURN_RECOVERIES then", "if false then"),
    ("watchdog: no recovery", GL, "local what = G.recoverTurn(F, inCombat ~= 0, turnHolders(F))",
     'local what = "none"; F.recoveries = G.TURN_RECOVERIES'),
    ("own turn: no end-turn retry limit", GL, 'if F.endTries >= G.END_TURN_TRIES then return finish',
     'if false then return finish'),
    ("run start: prep inside the eval", GL, "wait(50, function() G.start(F) end)", "G.start(F)"),
    ("prep: no deadline", GL, "elseif now() > F.prepDeadline then", "elseif false then"),
    ("verdict: idle rounds ignored", GL, "if idle > 0 then", "if false then"),
    ("verdict: foreign casts not detected", GL,
     "if c.who == me and not allowed[core(c.spell)] and not G.itemSpell(c.spell) then", "if false then"),
    ("verdict: item spells count as foreign", GL, "if c.who == me and not allowed[core(c.spell)] and not G.itemSpell(c.spell) then",
     "if c.who == me and not allowed[core(c.spell)] then"),
    ("plan: only the top upcast", PL, "return list(dict.fromkeys(out + [spell]))",
     "return list(dict.fromkeys(out[:1] or [spell]))"),
    ("forecast: no affordability", PL, "ok = all((turn[k] if k in turn else pool.get((k, lv), 0)) >= n for k, n, lv in "
     "costs)", "ok = True"),
    ("plan: set reactions dropped", PL, "list(build_interrupts) + list(set_interrupts) + COMMON_REACTIONS",
     "list(build_interrupts) + COMMON_REACTIONS"),
    ("plan: item passives not scanned", PL, "            for p in _split(st_.get(\"PassivesOnEquip\")):\n"
     "                scan(p, 1)", "            pass"),
    ("engine: no retry on a missed eval", EN, "if misses >= max_misses:", "if misses >= 1:"),
    ("engine: start never re-sent", EN, "elif not seen and not resent and polls >= 3:", "elif False:"),
    ("gate: tolerance ignored", RN, "if diff > tol:", "if diff > 1e9:"),
    ("gate: one-sided control passes", RN, 'causes.append(f"control pair {i} ({p[\'char\']} {p[\'build\']}) not measured '
     'on both sides")', "pass"),
    ("validity: game verdict ignored", RN,
     'valid = rec.get("valid", res.get("valid", True)) is not False and not causes', "valid = True"),
]


def run_mutations():
    ok = 0
    for desc, fn, old, new in MUTATIONS:
        tmp = tempfile.mkdtemp(prefix="gauntlet_mut_")
        try:
            gd = os.path.join(tmp, "gauntlet")
            shutil.copytree(G_DIR, gd, ignore=shutil.ignore_patterns("__pycache__"))
            p = os.path.join(gd, fn)
            with open(p, encoding="utf-8") as f:
                src = f.read()
            if old not in src:
                print(f"[BAD] {desc}: mutation target not found in {fn}")
                continue
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(src.replace(old, new, 1))
            try:
                r = subprocess.run([sys.executable, os.path.abspath(__file__), "--gdir", gd], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=120)
            except subprocess.TimeoutExpired:
                print(f"[BAD] {desc} -> the tests hung")
                continue
            fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL ")]
            red = r.returncode != 0 and bool(fails)
            ok += red
            print(f"[{'OK ' if red else 'BAD'}] {desc} -> {'caught: ' + fails[0][5:90] if red else 'NOT caught'}"
                  + ("" if red or fails else f" (exit {r.returncode}) {(r.stdout + r.stderr)[-300:]}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok}/{len(MUTATIONS)} mutations caught")
    return 0 if ok == len(MUTATIONS) else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(run_mutations())
    lua_tests()
    py_tests()
    print(f"{len(FAILS)} failed" if FAILS else "all passed")
    sys.exit(1 if FAILS else 0)
