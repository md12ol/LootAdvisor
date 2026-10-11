"""Gauntlet harness tests that need neither the game nor game data.

    python tests/test_gauntlet.py            the tests
    python tests/test_gauntlet.py --mutate   break each guarded rule in a scratch copy of tools/gauntlet and prove the
                                             tests go red (the repo itself is never modified)

- the in-game Lua (tools/gauntlet/gauntlet.lua, gauntlet_ui.lua) compiles; with stubbed engine tables the server file
  loads and its pure helpers behave: cost parsing, the shared adaptive item rule (same input -> same choice, logs
  every candidate, only affordable item spells, the core action as fallback), the arena layout;
- casts count only when the engine shows them (cast event, damage, resource spent); a miss is a failure with fallback;
  the engine's CastSpellFailed fails a cast at once, with the reason (an Attack of Opportunity, the spell's blockers);
- the run's setup: weapons found under the Osiris slot names, unworn set items, encumbrance (earlier items deleted, the
  carry limit raised), the spell precheck, the game's rules (Attacks of Opportunity on, real hit points: a down ends
  the run as a result; a cast out of range moves first without leaving an enemy's reach when it can; a cast an Attack
  of Opportunity interrupted is asked for again once), leftover enemies and summons removed before the arena check,
  hits from outside the run;
- each round is planned from the resources the character has (upcast chains, Channel Divinity) and checked again;
- reactions: policy mapping (default never), every interrupt the character has, save / apply / restore, the guard;
- the setup check: every field of the spec read back by engine at the fight's start and end; one mismatch, an idle round
  or a refused cast fails the run (never masked);
- the turn watchdog recovers, then ends the run as invalid; a run starts without blocking the eval; run validity;
- run.py statistics, run validity, the control-pair gate (fair rounds, the dice) and re-judging older records;
  engine.py retries and invalid runs;
- plan.py helpers: upcast chains, the affordability forecast, reaction answers, hotbar rows by role, spell
  requirements, how far a spell reaches, proficiency per item;
- two lanes at once: per-lane run state (timers, events), lane factions and relations (set, put back), the isolation
  check, the start barrier, a shared combat or hits across lanes fail the run; run.py's lane spacing and schedule,
  engine.py's lane run and its lock;
- a real respec: nothing emulated in prep, classes / subclasses / feats compared; the game's proficiency answer;
- the control pair: equal damage and equal damage taken in the model, and the search for one.
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
          all(all(k in a for k in ("level", "center", "radius", "start", "park")) for a in ar.values()
              if "lanes" not in a))
    lane_sets = [a for a in ar.values() if "lanes" in a]
    check("arenas.json: a lanes entry names two arenas of the same level, each with its own enemy faction",
          lane_sets and all(len(a["lanes"]) == 2 and all(ar.get(x["arena"], {}).get("level") == a["level"] and
                                                         x.get("enemy_faction") for x in a["lanes"].values()) and
                            len({x["enemy_faction"] for x in a["lanes"].values()}) == 2 for a in lane_sets))
    check("arenas.json: lanes are mirrored (the same direction, the same radius)",
          all(len({tuple(ar[x["arena"]]["dir"]) for x in a["lanes"].values()}) == 1 and
              len({ar[x["arena"]]["radius"] for x in a["lanes"].values()}) == 1 for a in lane_sets))
    for t in (reaction_tests, item_cost_tests, cast_tests, plan_round_tests, watchdog_tests, verdict_tests, equip_tests,
              encumbrance_tests, refusal_tests, precheck_tests, downed_tests, cleanup_tests, start_tests,
              rules_tests, setup_tests, lane_tests, respec_tests, enemy_tests, party_tests):
        try:
            t(L)
        except Exception as e:  # noqa: BLE001 - a broken block is a failed test, not a crash
            check(f"{t.__name__} ran", False, repr(e)[:300])


def enemy_tests(L):
    """The model's enemy: a creature made by CreateAt has no stats in its first frames, so its abilities are set to 10
    and its gear taken off only once its stats are there; the setup check reads every ability and the worn items."""
    L.execute(r"""
      local G = GAUNTLET
      local queue, boosts, unequipped = {}, {}, {}
      local reads, ready = 0, false
      Ext.Timer.WaitFor = function(_, f) queue[#queue + 1] = f end
      Osi.AddBoosts = function(_, b) boosts[#boosts + 1] = b end
      Osi.Unequip = function(_, it) unequipped[#unequipped + 1] = it end
      Osi.CreateAt = function() return "e1" end
      Osi.GetEquippedItem = function(_, slot) if ready and slot == "Melee Main Weapon" and #unequipped == 0 then return "w" end end
      Ext.Entity.Get = function(u)
        reads = reads + 1
        if reads > 3 then ready = true end
        local a = ready and { 0, 16, 14, 12, 8, 10, 10 } or { 0, 0, 0, 0, 0, 0, 0 }
        return { Stats = { Abilities = a, ProficiencyBonus = 2 }, Resistances = { AC = 12, Resistances = {} },
                 Replicate = function() end }
      end
      G.spawnEnemies({ { 0, 0, 0 } }, { template = "t", ac = 19, save = 4, atk = 9, dmg = 9, dc = 17, hp = 5000 })
      for _ = 1, 200 do if #queue == 0 then break end; table.remove(queue, 1)() end
      T_eb, T_un = boosts, unequipped
      ready = true
      Ext.Entity.Get = function(u)
        if u == "e1" then return { Stats = { Abilities = { 0, 16, 10, 10, 10, 10, 10 } }, Resistances = { AC = 19 } } end
      end
      Osi.GetEquippedItem = function(u, slot) if u == "e1" and slot == "Melee Main Weapon" then return "w" end end
      local sc = G.setupCheck({ char = "c1" }, { items = {} }, "start",
        { enemies = { "e1" }, E = { ac = 19, damage_scale = 0.5 }, scale = 0.5, encumbered = {} })
      T_em = {}
      for _, m in ipairs(sc.mismatches) do T_em[#T_em + 1] = m.field end
      Ext.Timer.WaitFor = function(_, f) f() end
      Osi.AddBoosts, Osi.Unequip, Osi.CreateAt, Osi.GetEquippedItem = nil, nil, nil, nil
      Ext.Entity.Get = function() return nil end
    """)
    g = L.globals()
    b = lst(g.T_eb)
    check("enemy: abilities set to 10 from the stats the creature has once they are there (not +10 from a zero read)",
          "Ability(Strength,-6)" in b and "Ability(Dexterity,-4)" in b and not any(x.startswith("Ability(") and
                                                                               x.endswith(",10)") for x in b), str(b))
    check("enemy: its weapon is taken off once its gear is there", lst(g.T_un) == ["w"], str(lst(g.T_un)))
    em = lst(g.T_em)
    check("setup: an enemy ability other than 10 and a worn item fail the setup check",
          "enemy 1 Strength" in em and "enemy 1 items worn" in em and "enemy 1 Dexterity" not in em, str(em))


def party_tests(L):
    """The party: DB_Players and every player character the database misses (a companion made a player by script)."""
    L.execute(r"""
      local G = GAUNTLET
      Osi.DB_Players = { Get = function() return { { "Host_11111111-1111-1111-1111-111111111111" } } end }
      Osi.IsPlayer = function(u) return (u == "22222222-2222-2222-2222-222222222222" or
        u == "11111111-1111-1111-1111-111111111111") and 1 or 0 end
      local ents = {}
      for _, u in ipairs({ "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222",
                           "33333333-3333-3333-3333-333333333333" }) do ents[#ents + 1] = { Uuid = { EntityUuid = u } } end
      local gae = Ext.Entity.GetAllEntitiesWithComponent
      Ext.Entity.GetAllEntitiesWithComponent = function() return ents end
      T_party = G.partyMembers()
      Ext.Entity.GetAllEntitiesWithComponent = gae
      Osi.DB_Players, Osi.IsPlayer = nil, nil
    """)
    L.execute(r"""
      local G = GAUNTLET
      local rel = { ["Evil|Gale"] = 50, ["Gale|Evil"] = 50 }
      Osi.GetFaction = function(u) return u == "d" and "Template" or "Gale" end
      Osi.GetRelation = function(a, b) return rel[a .. "|" .. b] end
      Osi.SetRelation = function(a, b, v) rel[a .. "|" .. b] = v end
      Osi.IsEnemy = function() return 0 end
      local st = G.makeHostile("gale", "d", "Evil")
      T_h1 = rel["Evil|Gale"] == 0 and rel["Gale|Evil"] == 0
      T_hr = G.laneFactionsRestore(st)
      T_h2 = rel["Evil|Gale"] == 50 and rel["Gale|Evil"] == 50
      Osi.IsEnemy = function() return 1 end
      T_h3 = G.makeHostile("gale", "d", "Evil") == nil
      Osi.GetFaction, Osi.GetRelation, Osi.SetRelation, Osi.IsEnemy = nil, nil, nil, nil
    """)
    g = L.globals()
    check("hostility: a character the enemies are not hostile to gets both factions (the enemies' given one) set "
          "hostile, put back after",
          g.T_h1 is True and g.T_hr == 2 and g.T_h2 is True and g.T_h3 is True)
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local args
      Osi.UseSpell = function(...) args = { ... } end
      Osi.GetPosition = function() return 0, 0, 0 end
      local F = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, afford = function() return true end }
      local R = { r = 1, actions = {}, casts = {}, done = {}, cast_fails = {}, reactions_seen = {} }
      G.rounds = { R }
      G._doAction(F, { spell = "Projectile_FireBolt", group = "action", target = "@boss", cost = "free" }, R)
      T_nomove = args and #args == 5 and args[5] == 1
      Osi.UseSpell, Osi.GetPosition = nil, nil
      F.pending = nil
    """)
    check("cast: the character casts from where it stands (UseSpell without move; the harness moves it first)",
          L.globals().T_nomove is True)
    L.execute(r"""
      local G = GAUNTLET
      local removed = {}
      Osi.RemoveStatus = function(_, st) removed[#removed + 1] = st end
      G.usedStatuses = { ["11111111-1111-1111-1111-111111111111"] = { POTION_X = true } }
      T_used = G.removeUsedStatuses("Laezel_11111111-1111-1111-1111-111111111111")
      T_used2 = G.removeUsedStatuses("11111111-1111-1111-1111-111111111111")
      T_removed = removed
      Osi.RemoveStatus = nil
    """)
    g = L.globals()
    check("prep: the statuses an earlier run's elixir gave are taken off once",
          lst(g.T_removed) == ["POTION_X"] and lst(g.T_used) == ["POTION_X"] and len(lst(g.T_used2)) == 0,
          str(lst(g.T_removed)))
    p = lst(L.globals().T_party)
    check("party: a player character missing from DB_Players is in the party, once each, strangers are not",
          p == ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"], str(p))


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


def equip_tests(L):
    """Weapons are found under the slot names Osiris uses ("Melee Main Weapon"); a set item that did not go on makes
    the run invalid (the pilot's records never showed a weapon as worn, and a helmet whose gaze was planned was off)."""
    L.execute(r"""
      local G = GAUNTLET
      local worn = { ["Melee Main Weapon"] = "staff", Helmet = "hood" }
      Osi.GetEquippedItem = function(_, slot) return worn[slot] end
      T_eq = G.equipped("c1")
      Osi.GetEquippedItem = function() return nil end
      local prep = { items = { { want = "Helmet", stats = "MAG_Helm", got = "Helmet" },
        { want = "MeleeMainHand", stats = "MAG_Staff", got = "MeleeMainHand" },
        { want = "Ring2", stats = "MAG_Ring" }, { want = "Elixir", stats = "OBJ_Potion", got = "used" } } }
      T_unworn = G.unworn(prep)
      T_ju = G.judge({ { r = 1, done = { action = true } } }, "rounds done", { prep = prep }, { me = "c1" })
      -- an equip that has not taken is waited for and asked for once more
      local clock, equips = 0, 0
      local wf, mt = Ext.Timer.WaitFor, Ext.Utils.MonotonicTime
      Ext.Timer.WaitFor = function(ms, f) clock = clock + ms; f() end
      Ext.Utils.MonotonicTime = function() return clock end
      Osi.CreateAt = function() return "it1" end
      Osi.Equip = function() equips = equips + 1 end
      Osi.IsEquipped = function() return equips >= 2 and 1 or 0 end
      G.results = { items = {} }
      local done = false
      G._equipAll("c1", { { slot = "Boots", template = "t", stats = "MAG_Boots" } }, 1, function() done = true end)
      T_eqr = G.results.items[1]
      T_eqdone, T_equips = done, equips
      -- a slow frame: the first check comes after the whole wait
      equips = 0
      local calls = 0
      Ext.Timer.WaitFor = function(ms, f) calls = calls + 1; clock = clock + (calls == 2 and 3000 or ms); f() end
      G.results = { items = {} }
      G._equipAll("c1", { { slot = "Boots", template = "t", stats = "MAG_Boots" } }, 1, function() end)
      T_eqslow = G.results.items[1]
      Ext.Timer.WaitFor, Ext.Utils.MonotonicTime = wf, mt
      Osi.CreateAt, Osi.Equip, Osi.IsEquipped = nil, nil, nil
    """)
    g = L.globals()
    check("equip: weapons found under the Osiris slot names", g.T_eq.MeleeMainHand == "staff" and g.T_eq.Helmet == "hood",
          str(dict(g.T_eq.items())))
    check("equip: a set item that did not go on is listed", lst(g.T_unworn) == ["MAG_Ring (Ring2)"], str(lst(g.T_unworn)))
    check("equip: an equip that has not taken is asked for again and then found worn",
          g.T_eqdone is True and g.T_equips == 2 and g.T_eqr.got == "Boots" and g.T_eqr.again is True,
          f"{g.T_equips} {g.T_eqr and g.T_eqr.got}")
    check("equip: a slow frame still gets the second ask", g.T_eqslow.got == "Boots" and g.T_eqslow.again is True,
          str(g.T_eqslow and g.T_eqslow.got))
    check("verdict: set items not worn make the run invalid",
          g.T_ju.valid is False and any("MAG_Ring" in c for c in lst(g.T_ju.causes)), str(lst(g.T_ju.causes)))


def encumbrance_tests(L):
    """Prep deletes the items earlier runs spawned and raises the carry limit; a character still encumbered at the
    start of the fight makes the run invalid (Heavily Encumbered: disadvantage on attack rolls, movement x3)."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local calls = { boosts = {}, removed = {}, deleted = {} }
      local has = { ENCUMBERED_MAX = 1 }
      Osi.HasActiveStatus = function(_, s) return has[s] or 0 end
      Osi.AddBoosts = function(_, b) calls.boosts[#calls.boosts + 1] = b end
      Osi.RemoveStatus = function(_, s) calls.removed[#calls.removed + 1] = s; has[s] = nil end
      Osi.RequestDelete = function(it) calls.deleted[#calls.deleted + 1] = it end
      T_enc = G.encumbrance("c1")
      G.unencumber("c1", true)
      T_enc2 = G.encumbrance("c1")
      T_boosts, T_removed = calls.boosts, calls.removed
      G.spawnedItems = { "old1", "old2" }
      T_ndel = G.dropSpawnedItems("c1")
      T_deleted, T_left = calls.deleted, #G.spawnedItems
      T_je = G.judge({ { r = 1, done = { action = true } } }, "rounds done", { encumbered = { "ENCUMBERED_MAX" } },
                     { me = "c1" })
      Osi.HasActiveStatus, Osi.AddBoosts, Osi.RemoveStatus, Osi.RequestDelete = nil, nil, nil, nil
    """)
    g = L.globals()
    check("encumbrance: the statuses are read", lst(g.T_enc) == ["ENCUMBERED_MAX"], str(lst(g.T_enc)))
    check("encumbrance: carry limit raised by a boost, the status removed",
          "CarryCapacityMultiplier(50)" in lst(g.T_boosts) and lst(g.T_removed) == ["ENCUMBERED_MAX"] and
          len(g.T_enc2) == 0, f"{lst(g.T_boosts)} {lst(g.T_removed)}")
    check("encumbrance: items earlier runs spawned are deleted in prep",
          g.T_ndel == 2 and lst(g.T_deleted) == ["old1", "old2"] and g.T_left == 0, str(lst(g.T_deleted)))
    check("verdict: an encumbered test character makes the run invalid",
          g.T_je.valid is False and any("encumbered" in c for c in lst(g.T_je.causes)), str(lst(g.T_je.causes)))


def refusal_tests(L):
    """The engine's CastSpellFailed ends the wait at once and the reason is logged: an enemy's Attack of Opportunity
    while the cast walked the character (39 of 40 refusals in the pilot re-run), or the spell's blockers."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local F = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, afford = function() return true end }
      local R = { r = 1, actions = {}, casts = {}, done = {}, cast_fails = {}, reactions_seen = {} }
      G.rounds = { R }
      G.fighting = true
      local cl = { spell = "Projectile_MAG_ChainLightning", group = "item", target = "@boss", per = "short",
                   alt = { spell = "Zone_LightningBolt", group = "action", target = "@boss" } }
      G._doAction(F, cl, R)
      G._onCastFailed("e1", "Projectile_MAG_ChainLightning")          -- another caster: no proof
      G._onCastFailed("c1", "Projectile_FireBolt")                    -- another spell: no proof
      T_wait = G.settle(F, R, 100)
      G._onReaction("e1", "Interrupt_AttackOfOpportunity", 1)
      G._onCastFailed("c1", "Projectile_MAG_ChainLightning")
      T_fast = G.settle(F, R, 200)
      T_retried = R.actions[1].retried
      T_miss = R.actions[1].miss
      T_retry_pending = F.pending ~= nil and #R.actions == 1
      T_retry_miss = R.cast_misses
      G._onCastFailed("c1", "Projectile_MAG_ChainLightning")         -- refused again after the retry: asked once more
      T_fast15 = G.settle(F, R, 250)
      T_retry2 = F.pending ~= nil and #R.actions == 1 and R.actions[1].retries == 2
      G._onCastFailed("c1", "Projectile_MAG_ChainLightning")         -- refused a third time
      T_fast2 = G.settle(F, R, 300)
      local F2 = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, afford = function() return true end }
      local R2 = { r = 2, actions = {}, casts = {}, done = {}, cast_fails = {}, reactions_seen = {} }
      G.rounds = { R2 }
      G._doAction(F2, { spell = "Projectile_FireBolt", group = "action", target = "@boss" }, R2)
      G._onCastFailed("c1", "Projectile_FireBolt")                    -- refused with no reaction: no retry
      G.settle(F2, R2, 100)
      T_noretry = F2.pending == nil and R2.actions[1].retried == nil and R2.cast_misses == 1
      T_res = R.actions[1].result
      T_alt = R.actions[2] and R.actions[2].spell
      T_cd = F.cooldown["Projectile_MAG_ChainLightning"]
      local P = { who = "c1", spell = "X", reacts0 = 0 }
      T_why2 = G.refusalReason(P, { reactions_seen = {} }, { "no line of sight" }, 0).why
      T_why3 = G.refusalReason(P, { reactions_seen = {} }, {}, 0).why
      G.fighting = false
    """)
    g = L.globals()
    check("refusal: another caster's or another spell's failure is no refusal of this cast", g.T_wait is False)
    check("refusal: after an Attack of Opportunity the same cast is asked for again once, not counted as a miss",
          g.T_fast is True and "Attack of Opportunity" in str(g.T_retried) and g.T_retry_pending is True and
          g.T_retry_miss == 0, f"{g.T_retried} {g.T_retry_pending} {g.T_retry_miss}")
    check("refusal: refused again after the Attack of Opportunity's retry: asked once more (at most twice)",
          g.T_fast15 is True and g.T_retry2 is True)
    check("refusal: a refusal with no Attack of Opportunity before it is not retried", g.T_noretry is True)
    check("refusal: CastSpellFailed fails the cast at once (no timeout wait), the fallback runs",
          g.T_fast2 is True and str(g.T_res).startswith("failed: refused by the engine") and
          g.T_alt == "Zone_LightningBolt", str(g.T_res))
    check("refusal: an Attack of Opportunity during the cast is named as the reason, with the reaction",
          "Attack of Opportunity" in str(g.T_retried) and g.T_miss.refused is True and
          "Interrupt_AttackOfOpportunity by e1" in lst(g.T_miss.reactions), str(g.T_res))
    check("refusal: a refused per-rest item spell waits for the next rest", g.T_cd == "short")
    check("refusal: otherwise the blockers, else 'no reason shown'",
          g.T_why2 == "no line of sight" and "no reason" in str(g.T_why3), f"{g.T_why2} / {g.T_why3}")


def precheck_tests(L):
    """Before the fight every planned spell is checked: an item spell missing from the spell book (its item did not
    go on) or a weapon action without a melee weapon is unusable and passed over, with the reason logged."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local book = { { Id = { Prototype = "Projectile_FireBolt" } }, { Id = { Prototype = "Zone_MAG_Bolt" } } }
      Ext.Entity.Get = function(u) if u == "c1" then return { SpellBook = { Spells = book } } end end
      Ext.Stats.Get = function(s)
        if s == "Target_Topple" then return { RequirementConditions = "CanUseWeaponActions() and IsProficientWithEquippedWeapon()" } end
        return { SpellFlags = { "HasVerbalComponent" } }
      end
      local F = { char = "c1", cooldown = {}, plan = {
        rounds = { { { spell = "Zone_LightningBolt_6", group = "action", alt = { spell = "Projectile_FireBolt", group = "action" } } } },
        steady = {}, item_actions = {
          { spell = "Target_MAG_Gaze", item = "Helmet", group = "action", per = "short" },
          { spell = "Zone_MAG_Bolt", item = "Staff", group = "action", per = "short" },
          { spell = "Target_Topple", item = "Staff", group = "action", per = "short" } } } }
      T_pre = G.precheck(F)
      T_un = F.unusable
      F.afford = function() return true end
      T_aff = { G.afford(F, { spell = "Target_MAG_Gaze" }) }
      local R = { done = {} }
      T_q = G._itemRule(F, { { spell = "Projectile_FireBolt", group = "action" } }, R)
      T_log = R.item_rule
      Ext.Entity.Get = function() return nil end
      Ext.Stats.Get = function() return nil end
    """)
    g = L.globals()
    un = dict(g.T_un.items())
    check("precheck: an item spell missing from the spell book is unusable", "Target_MAG_Gaze" in un and
          "spell book" in un["Target_MAG_Gaze"], str(un))
    check("precheck: a weapon action without a melee weapon is unusable",
          "melee weapon" in un.get("Target_Topple", ""), str(un))
    check("precheck: the build's own spells and a usable item spell stay planned",
          "Zone_LightningBolt_6" not in un and "Zone_MAG_Bolt" not in un and "Projectile_FireBolt" not in un, str(un))
    check("precheck: logged per spell", len(g.T_pre) == 2, str(len(g.T_pre)))
    check("precheck: an unusable spell is not affordable, with the reason",
          g.T_aff[1] is False and "unusable" in str(g.T_aff[2]), str(g.T_aff[2]))
    q = [g.T_q[i + 1].spell for i in range(len(g.T_q))]
    logs = {g.T_log[i + 1].spell: g.T_log[i + 1].result for i in range(len(g.T_log))}
    check("precheck: the item rule passes over unusable item spells and uses the next one",
          q[:1] == ["Zone_MAG_Bolt"] and "unusable" in logs["Target_MAG_Gaze"], f"{q} {logs}")


def downed_tests(L):
    """A round the character starts down is recorded as downed, never as an idle round of the harness; the summary
    counts it and gives the sheet's hit points without the run's HP buffer."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local rounds = { { r = 1, done = { action = true } }, { r = 2, done = {}, downed = true },
                       { r = 3, done = { action = true } } }
      T_jd = G.judge(rounds, "rounds done", {}, { me = "c1" })
      G.rounds, G.dmg = rounds, {}
      for _, R in ipairs(rounds) do R.actions = {} end
      Osi.GetMaxHitpoints = function() return 288 end
      T_sum = G._summarize({ char = "c1", enemies = { "e1" }, hpBuffer = 200 })
      Osi.GetMaxHitpoints = nil
      local calls = {}
      Osi.RemoveBoosts = function(_, b) calls[#calls + 1] = b end
      G.dropRunBoosts("c1", 200)
      T_rb = calls
      Osi.RemoveBoosts = nil
    """)
    g = L.globals()
    check("downed: a round spent down is not an idle round (the run stays valid)", g.T_jd.valid is True,
          str(lst(g.T_jd.causes)))
    check("downed: counted in the summary; max HP without the buffer", g.T_sum.downed == 1 and g.T_sum.max_hp == 88,
          f"{g.T_sum.downed} {g.T_sum.max_hp}")
    check("run boosts: carry limit, no-AoO and the HP buffer are taken off after the run",
          sorted(lst(g.T_rb)) == sorted(["CarryCapacityMultiplier(50)", "IgnoreLeaveAttackRange()",
                                         "IncreaseMaxHP(200)"]), str(lst(g.T_rb)))


def cleanup_tests(L):
    """Leftovers: an earlier run's enemy that outlived its delete request, and a summon the character left behind,
    are removed (killed when the delete does nothing) before the arena check, which no longer skips earlier runs'
    enemies; hits from creatures outside the run make it invalid."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local dead = { old = 0, sw = 0, npc = 0, c1 = 0 }
      local at = { old = { -170, 12, 870 }, sw = { -177, 12, 871 }, npc = { 0, 0, 0 }, c1 = { -181, 12, 870 } }
      local ents = {}
      for u in pairs(at) do ents[#ents + 1] = { Uuid = { EntityUuid = u },
        IsSummon = (u == "sw") and { Owner = { Uuid = { EntityUuid = "c1" } } } or nil } end
      local entOf = {}
      for _, e in ipairs(ents) do entOf[e.Uuid.EntityUuid] = e end
      Ext.Entity.GetAllEntitiesWithComponent = function() return ents end
      Ext.Entity.Get = function(u) return entOf[u] end
      Osi.IsDead = function(u) return dead[u] end
      Osi.IsSummon = function(u) return u == "sw" and 1 or 0 end
      Osi.GetPosition = function(u) local p = at[u]; if p then return p[1], p[2], p[3] end end
      Osi.DB_Players = { Get = function() return { { "c1" } } end }
      local died = {}
      Osi.Die = function(u) died[#died + 1] = u; dead[u] = 1 end
      local A = { center = { -167, 14, 870 }, radius = 16 }
      G.spawned = { old = true }
      T_sum = G.leftoverSummons("c1", A)
      T_before = G.arenaIntruders(A)
      G.clearLeftovers("c1", A, function(rep) T_rep = rep end)
      T_died = died
      T_after = G.arenaIntruders(A)
      -- the delete and the kill both fail: the enemy is an intruder, not skipped
      dead.old = 0
      Osi.Die = function() end
      G.spawned = { old = true }
      G.clearLeftovers("c1", A, function() end)
      T_still = G.arenaIntruders(A)
      local hits = { { target = "c1", source = "e1", owner = "e1", amount = 10, cause = "Attack" },
        { target = "c1", source = "old", owner = "old", amount = 12, cause = "Attack" },
        { target = "c1", source = "c1", amount = 2, cause = "Surface" }, { target = "e1", source = "c1", amount = 30 } }
      T_oa, T_on = G.outsideAttackers(hits, "c1", { "e1" })
      T_jo = G.judge({ { r = 1, done = { action = true } } }, "rounds done", { outside_hits = T_on }, { me = "c1" })
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Ext.Entity.Get = function() return nil end
      Osi.IsDead, Osi.IsSummon, Osi.GetPosition, Osi.DB_Players, Osi.Die = nil, nil, nil, nil, nil
      G.spawned = nil
    """)
    g = L.globals()
    check("cleanup: the character's leftover summon is found", lst(g.T_sum) == ["sw"], str(lst(g.T_sum)))
    check("cleanup: an earlier run's enemy still standing counts as an intruder", len(g.T_before) == 2,
          str(lst(g.T_before)))
    check("cleanup: leftovers the delete did not remove are killed, then the arena is clear",
          sorted(lst(g.T_died)) == ["old", "sw"] and len(g.T_after) == 0 and g.T_rep.removed == 2,
          f"{lst(g.T_died)} {lst(g.T_after)}")
    check("cleanup: a leftover that cannot be removed fails the arena check (not skipped)", len(g.T_still) == 1,
          str(lst(g.T_still)))
    check("verdict: hits from a creature outside the run are counted and make it invalid",
          g.T_on == 1 and g.T_oa["old"] == 1 and g.T_jo.valid is False, str(lst(g.T_jo.causes)))


def start_tests(L):
    """A scripted fight starts with the same setup for both sets: no Attack of Opportunity on the character, a fixed
    HP buffer, leftovers cleared, the encumbrance read and the plan prechecked."""
    L.execute(r"""
      local G = GAUNTLET
      local queue, boosts = {}, {}
      Ext.Timer.WaitFor = function(_, f) queue[#queue + 1] = f end
      Osi.AddBoosts = function(_, b) boosts[#boosts + 1] = b end
      Osi.CreateAt = function() return "e1" end
      Osi.HasActiveStatus = function() return 0 end
      Osi.GetPosition = function() return 0, 0, 0 end
      G.origin = nil
      local prep = G.prep
      G.prep = function() G.status = "prepped"; G.results = { items = {} } end
      G.F = nil
      Ext.Entity.Get = function(u)
        if u == "c1" then return { SpellBook = { Spells = { { Id = { Prototype = "Projectile_FireBolt" } } } } } end
      end
      G.run({ mode = "scripted", scenario = "boss", label = "s", enemy = { template = "t", ac = 10, save = 0, atk = 0,
             dmg = 1, dc = 10, hp = 0 }, char = "c1", spec = { plan = { item_actions = {
               { spell = "Target_MAG_Gaze", item = "Helmet", group = "action", per = "short" } } } } })
      for _ = 1, 80 do if #queue == 0 then break end; table.remove(queue, 1)() end
      T_boosts = boosts
      T_res = G.results
      T_state = G.F.state
      G.F.state = "done"
      G.fighting = false
      G.prep = prep
      Ext.Timer.WaitFor = function(_, f) f() end
      Osi.AddBoosts, Osi.CreateAt, Osi.HasActiveStatus, Osi.GetPosition = nil, nil, nil, nil
      Ext.Entity.Get = function() return nil end
    """)
    g = L.globals()
    b = lst(g.T_boosts)
    check("fight start: the game's rules, Attacks of Opportunity on and no HP buffer",
          "IgnoreLeaveAttackRange()" not in b and not any(x.startswith("IncreaseMaxHP") for x in b) and
          g.T_res.hp_buffer == 0 and g.T_res.ignore_leave_attack_range is False, f"{b} state {g.T_state}")
    check("fight start: the enemies' damage scale is applied and recorded",
          g.T_res.enemy_damage_scale == 0.5 and g.T_res.enemy_target.damage_scale == 0.5,
          str(g.T_res.enemy_damage_scale))
    check("fight start: leftovers cleared, encumbrance read, plan prechecked before the first round",
          g.T_res.leftovers is not None and g.T_res.encumbered is not None and g.T_res.precheck is not None and
          len(g.T_res.precheck) == 1 and g.T_res.precheck[1].spell == "Target_MAG_Gaze",
          f"state {g.T_state}")


def rules_tests(L):
    """The game's rules in a scripted fight: the character's own Attack of Opportunity is fair (not foreign); a down
    ends the run as a result (valid, with the rounds survived); a cast out of range moves first, by a route that does
    not leave an enemy's reach when one exists."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local plan = { rounds = {}, steady = { { spell = "Projectile_FireBolt" } }, item_actions = {}, reactions = {} }
      local rounds = {
        { r = 1, casts = { { who = "c1", spell = "Target_MainHandAttack" } },
          reactions_seen = { { who = "c1", interrupt = "Interrupt_AttackOfOpportunity" } } },
        { r = 2, casts = { { who = "c1", spell = "Target_MainHandAttack" } }, reactions_seen = {} } }
      T_fa = G.foreignCasts(rounds, "c1", plan)
      T_jdown = G.judge({ { r = 1, done = { action = true } } }, "downed", {}, { me = "c1" })
      -- a down before the character's turn ends the run
      local fin
      local P = {
        c1 = { 0, 0, 0 }, t = { 25, 0, 0 }, e1 = { 4, 0, 2 } }
      Osi.GetPosition = function(u) local p = P[u]; if p then return p[1], p[2], p[3] end end
      Osi.GetHitpoints = function() return 0 end
      Ext.Entity.Get = function() return { TurnBased = { IsActiveCombatTurn = true } } end
      G.round = 3
      local F = { state = "wait", rounds = 16, char = "c1", enemies = {}, deadline = 1e12, cooldown = {}, plan = plan }
      G.results = G.results or {}
      pcall(G.step, F, 0)
      T_dstate, T_dended = F.state, G.results.ended
      T_dsum = G.results.summary
      local revived = {}
      Osi.IsDead = function() return 1 end
      Osi.Resurrect = function(u) revived[#revived + 1] = u end
      G.revive("c1")
      T_revived = revived
      T_e3 = G.scaleEnemy({ dmg = 17, ac = 19 }, 0.5)
      T_e1 = G.scaleEnemy({ dmg = 9 }, G.ENEMY_DAMAGE_SCALE)
      Osi.IsDead, Osi.Resurrect = nil, nil
      Osi.GetHitpoints = nil
      -- moving to cast: the direct route leaves e1's reach, a detour south does not
      Osi.IsDead = function() return 0 end
      Osi.CanSee = function() return 1 end
      Osi.GetActionResourceValuePersonal = function() return 30 end
      Ext.Level.BeginPathfindingImmediate = function(_, goal)
        local nodes, n = {}, 40
        for i = 1, n do nodes[i] = { Position = { goal[1] * i / n, goal[2], goal[3] * i / n } } end
        return { Nodes = nodes, GoalFound = true }
      end
      Ext.Level.FindPath = function() return true end
      Ext.Level.ReleasePath = function() end
      local MF = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = plan, afford = function() return true end }
      T_spot = G.castSpot(MF, "t", 18)
      Ext.Stats.Get = function() return { TargetRadius = "18", UseCosts = "ActionPoint:1" } end
      local R = { r = 1, actions = {}, casts = {}, done = {}, cast_fails = {}, reactions_seen = {} }
      G._doAction(MF, { spell = "Projectile_FireBolt", group = "action", target = "t" }, R)
      T_moving = MF.moving ~= nil and R.actions[1].result == "moving"
      Ext.Stats.Get = function() return nil end
      Ext.Level.BeginPathfindingImmediate, Ext.Level.FindPath, Ext.Level.ReleasePath = nil, nil, nil
      Osi.GetPosition, Osi.IsDead, Osi.CanSee, Osi.GetActionResourceValuePersonal = nil, nil, nil, nil
      Ext.Entity.Get = function() return nil end
    """)
    g = L.globals()
    fa = [g.T_fa[i + 1].r for i in range(len(g.T_fa))]
    check("rules: the character's own Attack of Opportunity is no cast outside the plan; a weapon attack without one is",
          fa == [2], str(fa))
    check("rules: a down is a result, the run stays valid", g.T_jdown.valid is True, str(lst(g.T_jdown.causes)))
    check("rules: a down before the character's turn ends the run with the rounds survived",
          g.T_dstate == "done" and g.T_dended == "downed" and g.T_dsum and g.T_dsum.rounds_survived == 3,
          f"{g.T_dstate} {g.T_dended}")
    check("rules: enemy damage per hit scaled by half and rounded (17 -> 9, 9 -> 5), the rest unchanged",
          g.T_e3.dmg == 9 and g.T_e3.dmg_unscaled == 17 and g.T_e3.ac == 19 and g.T_e3.damage_scale == 0.5 and
          g.T_e1.dmg == 5, f"{g.T_e3.dmg} {g.T_e1.dmg}")
    check("rules: a dead test character is resurrected", lst(g.T_revived) == ["c1"], str(lst(g.T_revived)))
    check("rules: the route to a casting spot keeps out of leaving an enemy's reach when it can",
          g.T_spot and g.T_spot.risk is None and g.T_spot.z < 0, str(g.T_spot and (g.T_spot.risk, g.T_spot.z)))
    check("rules: a cast out of range moves first", g.T_moving is True)


def setup_tests(L):
    """The setup check: every field of the spec is read back by engine; one mismatch fails the run, field named."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      Osi.GetEquippedItem = function(_, slot) if slot == "Boots" then return "it" end end
      Osi.GetStatString = function() return "MAG_Boots" end
      Osi.HasPassive = function() return 1 end
      Osi.HasActiveStatus = function() return 1 end
      G.results = { prep = { bare = { abilities = { Strength = 10 }, hp = 50, prof = 4, slots = { ["1"] = 2 },
        resources = { ["ChannelDivinity:0"] = 1 } }, items = { { stats = "OBJ_Elixir", got = "used" } } } }
      local spec = { items = { { slot = "Boots", stats = "MAG_Boots" }, { slot = "Elixir", stats = "OBJ_Elixir", use = true } },
        passives_add = { "P1" }, statuses = { "S1" }, sheet = { abilities = { STR = 10 }, hp = 50, prof = 4 },
        slots = { ["1"] = 2 }, resources = { { kind = "ChannelDivinity", level = 0, n = 1 } } }
      local F = { char = "c1" }
      local sheet = G.sheet
      G.sheet = function() return { slots = { ["1"] = 2 }, resources = { ["ChannelDivinity:0"] = 1 } } end
      T_ok = G.setupCheck(F, spec, "start", { buffs = { "BLESS" }, encumbered = {}, reactions = true })
      G.results.prep.bare.hp = 49
      Osi.HasActiveStatus = function(_, st) return st == "BLESS" and 0 or 1 end
      T_bad = G.setupCheck(F, spec, "start", { buffs = { "BLESS" }, encumbered = {} })
      G.results.setup = { start = T_bad }
      G.results.summary = { cast_misses = 1 }
      T_j = G.judge({ { r = 1, done = { action = true } } }, "rounds done", G.results, { me = "c1" })
      G.sheet = sheet
      Osi.GetEquippedItem, Osi.GetStatString, Osi.HasPassive, Osi.HasActiveStatus = nil, nil, nil, nil
    """)
    g = L.globals()
    check("setup: a setup that matches the spec has no mismatch", len(g.T_ok.mismatches) == 0 and g.T_ok.checked >= 10,
          f"{[(m.field, m.want, m.got) for m in g.T_ok.mismatches.values()]} {g.T_ok.checked}")
    fields = sorted(m.field for m in g.T_bad.mismatches.values())
    check("setup: max HP and a missing buff are named", fields == ["buff BLESS", "max HP"], str(fields))
    causes = lst(g.T_j.causes)
    check("setup: a mismatch fails the run with the field named, and a refused cast fails it too",
          g.T_j.valid is False and any("max HP (want 50, got 49)" in c for c in causes) and
          any("refused" in c for c in causes), str(causes))


def lane_tests(L):
    """Two lanes at once: each lane keeps its own run state (timers and events land in their lane), each lane's
    enemies are hostile to its own character only (factions and relations set, then put back), both fights start
    together once every lane is ready, the first lane first; hits across lanes and a shared combat fail the run."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.status = "base"
      G.inLane("A", function() G.reset(); G.status = "a"; G.rounds = { "ra" } end)
      G.inLane("B", function() G.reset(); G.status = "b" end)
      T_iso = { base = G.status, a = G.laneField("A", "status"), b = G.laneField("B", "status"),
                ra = G.laneField("A", "rounds")[1], cur = G.curLane }
      -- a timer runs in the lane that set it
      local queue = {}
      Ext.Timer.WaitFor = function(_, f) queue[#queue + 1] = f end
      G.inLane("A", function() G._wait(10, function() T_tlane = G.curLane; G.status = "a2" end) end)
      for _, f in ipairs(queue) do f() end
      Ext.Timer.WaitFor = function(_, f) f() end
      T_timer = { lane = T_tlane, a = G.laneField("A", "status"), base = G.status }
      -- events go to the lane they name; a hit on the other lane's enemy goes to both
      G.LANES = { on = true, order = { "A", "B" }, members = { A = { cA = true, eA = true }, B = { cB = true, eB = true } } }
      for _, id in ipairs({ "A", "B" }) do
        G.inLane(id, function() G.dmg = {}; G.fighting = true; G.round = 1; G.t0 = 0 end)
      end
      G._on.attacked("eA", "cA", "cA", "Fire", 5, "x", "s")
      G._on.attacked("eB", "cA", "cA", "Fire", 7, "x", "s")
      G._on.attacked("zz", "qq", "qq", "Fire", 1, "x", "s")
      T_ev = { a = #G.laneField("A", "dmg"), b = #G.laneField("B", "dmg") }
      T_cross = G.crossLaneHits(G.laneField("A", "dmg"), "cA", G.LANES.members, "A")
      T_crossB = G.crossLaneHits(G.laneField("B", "dmg"), "cB", G.LANES.members, "B")
      for _, id in ipairs({ "A", "B" }) do G.inLane(id, function() G.fighting = false end) end
      -- factions: both characters in the party's faction -> each gets its lane's; relations set and put back
      local set, rels, facs = {}, {}, {}
      Osi.GetFaction = function(u) return facs[u] or "Hero_h" end
      Osi.SetFaction = function(u, f) facs[u] = f; set[#set + 1] = u .. "=" .. f end
      Osi.GetRelation = function() return 50 end
      Osi.SetRelation = function(a, b, v) rels[a .. ">" .. b] = v end
      local LS = { lanes = { A = { enemy_faction = "fEA", char_faction = "fCA" }, B = { enemy_faction = "fEB", char_faction = "fCB" } } }
      local LL = { order = { "B", "A" }, chars = { A = "cA", B = "cB" } }
      local st = G.laneFactions(LL, LS)
      T_rel = { aa = rels["fEA>fCA"], ab = rels["fEA>fCB"], ba = rels["fCB>fEA"], bb = rels["fEB>fCB"],
                ee = rels["fEA>fEB"], fa = facs.cA, fb = facs.cB }
      local n = G.laneFactionsRestore(st)
      T_rest = { aa = rels["fEA>fCA"], fa = facs.cA, n = n }
      Osi.GetFaction, Osi.SetFaction, Osi.GetRelation, Osi.SetRelation = nil, nil, nil, nil
      -- isolation: an enemy hostile to the other lane's character fails the lane
      local P = { cA = { 0, 0, 0 }, cB = { 80, 0, 0 } }
      Osi.GetPosition = function(u) local p = P[u]; if p then return p[1], p[2], p[3] end end
      Osi.IsEnemy = function(e, u) return (e == "eA" and u == "cA") and 1 or 0 end
      T_iso_ok = G.laneIsolation({ char = "cA", enemies = { "eA" }, lane = { others = { B = "cB" }, gap_need = 60 } })
      Osi.IsEnemy = function() return 1 end
      T_iso_bad = G.laneIsolation({ char = "cA", enemies = { "eA" }, lane = { others = { B = "cB" }, gap_need = 60 } })
      P.cB = { 30, 0, 0 }
      Osi.IsEnemy = function(e, u) return (e == "eA" and u == "cA") and 1 or 0 end
      T_iso_near = G.laneIsolation({ char = "cA", enemies = { "eA" }, lane = { others = { B = "cB" }, gap_need = 60 } })
      Osi.IsEnemy = nil
      -- a round whose combat is the other lane's is marked; the verdict fails it
      Osi.CombatGetGuidFor = function() return "combat-1" end
      G.inLane("A", function()
        G.reset(); G.round = 0
        local F = { char = "cA", enemies = {}, cooldown = {}, plan = {}, S = { }, lane = { id = "A", others = { B = "cB" } } }
        G._roundStart(F)
        T_shared = G.rounds[1].combat_shared
        T_jshared = G.judge({ { r = 1, done = { action = true }, combat_shared = true } }, "rounds done", {}, { me = "cA" })
        T_jcross = G.judge({ { r = 1, done = { action = true } } }, "rounds done", { cross_lane_hits = 2 }, { me = "cA" })
      end)
      Osi.CombatGetGuidFor, Osi.GetPosition = nil, nil
      -- the barrier: nothing spawns while a lane prepares; then every ready lane, the first lane first
      local went = {}
      local goFight, iso = G.goFight, G.laneIsolation
      local function go() went[#went + 1] = G.F.lane.id end
      G.LANES = { on = true, order = { "B", "A" }, members = {}, t0 = 0 }
      G.inLane("A", function() G.F = { state = "ready", lane = { id = "A" }, go = go } end)
      G.inLane("B", function() G.F = { state = "prep", lane = { id = "B" }, go = go } end)
      G.lanesGo()
      T_went0 = #went
      G.inLane("B", function() G.F.state = "ready" end)
      G.lanesGo()
      T_went = went
      -- the lane's isolation joins its setup check
      G.laneIsolation = function(F)
        if F.lane.id == "A" then return { { field = "lane B character beyond 60 m", want = true, got = false } } end
        return {}
      end
      G.inLane("A", function()
        G.results = { setup = { start = { checked = 0, mismatches = {} } } }
        G.laneSetup(G.F)
      end)
      T_isoA = G.laneField("A", "results").setup.start.mismatches[1]
      -- the fight loop steps every lane
      local stepped = {}
      local step = G.step
      G.step = function(F) stepped[#stepped + 1] = F.lane.id end
      G.inLane("A", function() G.F.state = "wait" end)
      G.inLane("B", function() G.F.state = "wait" end)
      Ext.Utils.MonotonicTime = function() return 1e9 end
      G._tickFn()
      Ext.Utils.MonotonicTime = function() return 0 end
      T_stepped = stepped
      G.step, G.goFight, G.laneIsolation = step, goFight, iso
      -- the last lane to finish puts the factions and the party back
      local restored = 0
      local fr, up = G.laneFactionsRestore, G.unparkOthers
      G.laneFactionsRestore = function() restored = restored + 1; return 1 end
      G.unparkOthers = function() restored = restored + 10 end
      G.inLane("A", function() G.F.state = "done" end)
      G.lanesDone()
      T_done1 = restored
      G.inLane("B", function() G.F.state = "done" end)
      G.lanesDone()
      T_done2, T_on = restored, G.LANES.on
      G.laneFactionsRestore, G.unparkOthers = fr, up
      -- the runner: the party parked except both characters, each lane its own arena, enemy faction and character
      local runs, parkedKeep = {}, nil
      local run, park, cat = G.run, G.parkOthers, G.catalog
      G.run = function(r) runs[#runs + 1] = { lane = G.curLane, id = r.lane.id, arena = r.arena, ef = r.lane.enemy_faction,
        nohigh = r.lane.no_high, char = r.char, first = r.lane.first } return "started" end
      G.parkOthers = function(_, _, keep) parkedKeep = keep; return 2 end
      G.catalog = function() return { arenas = {
        a1 = { center = { 0, 0, 0 }, start = { 0, 0, 0 }, high = { 1, 1, 1 } }, a2 = { center = { 90, 0, 0 }, start = { 90, 0, 0 } },
        LN = { lanes = { A = { arena = "a1", enemy_faction = "fEA" }, B = { arena = "a2", enemy_faction = "fEB" } }, park = { 5, 5, 5 } } } } end
      local lf = G.laneFactions
      G.laneFactions = function() return { stub = true } end
      G.LANES = nil
      T_rl = G.runLanes({ run_id = "L1", lanes = "LN", first = "B", gap_need = 60,
        entries = { { id = "A", req = { char = "cA" } }, { id = "B", req = { char = "cB" } } } })
      T_busy = G.runLanes({ run_id = "L2", lanes = "LN", first = "A", entries = {} })
      T_runs, T_keep, T_order = runs, parkedKeep, G.LANES.order
      G.run, G.parkOthers, G.catalog, G.laneFactions = run, park, cat, lf
      T_singleBusy = G.run({ mode = "scripted" })
      G.LANES = nil
      -- a lane's whole start: no parking of its own, its enemies in the lane's faction and listed as the lane's, the
      -- isolation in the setup check, then the fight
      local q2, facs2 = {}, {}
      Ext.Timer.WaitFor = function(_, f) q2[#q2 + 1] = f end
      Osi.CreateAt = function() return "eL" end
      Osi.SetFaction = function(u, f) facs2[u] = f end
      Osi.GetPosition = function() return 0, 0, 0 end
      local prep2, park2 = G.prep, G.parkOthers
      G.prep = function() G.status = "prepped"; G.results = { items = {} } end
      G.parkOthers = function() T_selfparked = true; return 0 end
      G.LANES = { on = true, order = { "A" }, members = {}, t0 = 0, parkedCount = 3 }
      G.inLane("A", function()
        G.F = nil
        G.run({ mode = "scripted", scenario = "boss", label = "l", char = "cL", enemy = { template = "t", ac = 10,
          save = 0, atk = 0, dmg = 1, dc = 10, hp = 0 }, spec = { plan = {} },
          lane = { id = "A", others = {}, enemy_faction = "fX", first = "A" } })
      end)
      for _ = 1, 80 do if #q2 == 0 then break end; table.remove(q2, 1)() end
      T_lstate = G.laneField("A", "F").state
      T_lres = G.laneField("A", "results")
      T_lfac, T_lmem = facs2.eL, G.LANES.members.A
      G.inLane("A", function() G.F.state = "done"; G.fighting = false end)
      G.prep, G.parkOthers = prep2, park2
      Ext.Timer.WaitFor = function(_, f) f() end
      Osi.CreateAt, Osi.SetFaction, Osi.GetPosition = nil, nil, nil
      G.LANES = nil
      -- parking: every party member but the lanes' characters goes, out of combat
      local moved = {}
      Osi.DB_Players = { Get = function() return { { "cA" }, { "cB" }, { "cC" } } end }
      Osi.FindValidPosition = function(x, y, z) return x, y, z end
      Osi.TeleportToPosition = function(u) moved[#moved + 1] = u end
      G.parked = nil
      T_npark = G.parkOthers(nil, { 5, 5, 5 }, { cA = true, cB = true })
      T_moved = moved
      G.unparkOthers()
      Osi.DB_Players, Osi.FindValidPosition, Osi.TeleportToPosition = nil, nil, nil
    """)
    g = L.globals()
    check("lanes: each lane keeps its own run state; the base run is untouched",
          g.T_iso.base == "base" and g.T_iso.a == "a" and g.T_iso.b == "b" and g.T_iso.ra == "ra" and
          g.T_iso.cur == "base", str(dict(g.T_iso)))
    check("lanes: a timer runs in the lane that set it", g.T_timer.lane == "A" and g.T_timer.a == "a2" and
          g.T_timer.base == "base", str(dict(g.T_timer)))
    check("lanes: an event goes to the lane it names, a hit across lanes and an unknown one to both",
          g.T_ev.a == 3 and g.T_ev.b == 2, str(dict(g.T_ev)))
    check("lanes: a hit from one lane's character on the other lane's enemy is counted against it",
          g.T_cross == 1 and g.T_crossB == 0, f"{g.T_cross} {g.T_crossB}")
    check("lanes: each lane's enemies hostile to its own character, neutral to the other lane and its enemies",
          g.T_rel.aa == 0 and g.T_rel.ab == 50 and g.T_rel.ba == 50 and g.T_rel.bb == 0 and g.T_rel.ee == 50,
          str(dict(g.T_rel)))
    check("lanes: characters of one faction each get their lane's faction", g.T_rel.fa == "fCA" and g.T_rel.fb == "fCB",
          str(dict(g.T_rel)))
    check("lanes: relations and factions put back after the run", g.T_rest.aa == 50 and g.T_rest.fa == "Hero_h",
          str(dict(g.T_rest)))
    check("lanes: isolation passes for separate lanes", len(g.T_iso_ok) == 0, str([dict(m) for m in g.T_iso_ok.values()]))
    bad = [m.field for m in g.T_iso_bad.values()]
    check("lanes: an enemy hostile to the other lane's character fails the lane", any("not hostile to lane B" in f
                                                                                       for f in bad), str(bad))
    near = [m.field for m in g.T_iso_near.values()]
    check("lanes: the other lane's character closer than the spacing fails the lane",
          any("beyond 60" in f for f in near), str(near))
    check("lanes: a round in the other lane's combat is marked and fails the run",
          g.T_shared is True and g.T_jshared.valid is False and any("shared one combat" in c
                                                                   for c in lst(g.T_jshared.causes)), str(g.T_shared))
    check("lanes: hits on the other lane fail the run", g.T_jcross.valid is False and
          any("other lane" in c for c in lst(g.T_jcross.causes)))
    check("lanes: no lane spawns its enemies while another prepares; then both, the first lane first",
          g.T_went0 == 0 and lst(g.T_went) == ["B", "A"], f"{g.T_went0} {lst(g.T_went)}")
    check("lanes: a lane's isolation failure is a setup mismatch of that lane",
          g.T_isoA is not None and g.T_isoA.field == "lane B character beyond 60 m")
    check("lanes: the fight loop steps every lane", sorted(lst(g.T_stepped)) == ["A", "B"], str(lst(g.T_stepped)))
    check("lanes: factions and party put back only after the last lane", g.T_done1 == 0 and g.T_done2 == 11 and
          g.T_on is False, f"{g.T_done1} {g.T_done2}")
    runs = [dict(r) for r in g.T_runs.values()]
    check("lanes: the runner starts each lane in its own state with its arena, enemy faction and character",
          g.T_rl == "started" and sorted((r["lane"], r["id"], r["arena"], r["ef"], r["char"]) for r in runs) ==
          [("A", "A", "a1", "fEA", "cA"), ("B", "B", "a2", "fEB", "cB")], str(runs))
    check("lanes: mirrored layout (no high ground unless every lane has one), first lane passed on",
          all(r["nohigh"] is True and r["first"] == "B" for r in runs) and lst(g.T_order) == ["B", "A"], str(runs))
    check("lanes: the rest of the party parked, both lane characters kept",
          g.T_keep is not None and g.T_keep.cA is True and g.T_keep.cB is True)
    check("lanes: a lane starts its fight with its enemies in the lane's faction, listed as the lane's",
          g.T_lstate == "wait" and g.T_lfac == "fX" and g.T_lmem is not None and g.T_lmem.eL is True and
          g.T_lmem.cL is True, f"{g.T_lstate} {g.T_lfac}")
    check("lanes: a lane does not park the party itself; its isolation is part of its setup check",
          g.T_selfparked is None and g.T_lres.parked == 3 and g.T_lres.lane_isolation is not None,
          f"{g.T_selfparked} {g.T_lres.parked}")
    check("lanes: parking moves every party member but the lanes' characters",
          g.T_npark == 1 and lst(g.T_moved) == ["cC"], f"{g.T_npark} {lst(g.T_moved)}")
    check("lanes: a second lane run or a single run while lanes fight is refused",
          g.T_busy == "busy" and g.T_singleBusy == "busy", f"{g.T_busy} {g.T_singleBusy}")


def respec_tests(L):
    """A real respec: prep emulates nothing (no passives, spells or sheet boosts); the setup check compares the
    character's own classes, subclasses and feats with the build. Proficiency: the game's own answer for each item the
    build is proficient with."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local calls = {}
      for _, f in ipairs({ "AddPassive", "RemovePassive", "AddSpell", "AddBoosts" }) do
        Osi[f] = function(_, x) calls[#calls + 1] = f .. " " .. tostring(x) end
      end
      Osi.HasPassive = function() return 0 end
      local eq = G.equipped
      G.equipped = function() return {} end
      G.prep({ char = "c1", real_respec = true, passives_add = { "P1" }, passives_remove = { "P2" }, spells_add = { "S1" },
        boosts = { "Proficiency(HeavyArmor)" }, sheet = { abilities = { STR = 20 }, hp = 99, prof = 5 }, slots = { ["3"] = 3 },
        resources = { { kind = "Rage", n = 3 } }, items = {} })
      T_calls = calls
      T_respec = G.results.respec
      for _, f in ipairs({ "AddPassive", "RemovePassive", "AddSpell", "AddBoosts", "HasPassive" }) do Osi[f] = nil end
      -- the character's classes, subclasses, feats
      local SD = { cR = { Name = "Ranger" }, sG = { Name = "GloomStalker" }, cF = { Name = "Fighter" },
        sB = { Name = "BattleMaster" }, fS = { Name = "Sharpshooter" }, fA = { Name = "Alert" }, fI = { Name = "AbilityScoreIncrease" } }
      Ext.StaticData.Get = function(id) return SD[id] end
      local ups = { { Feat = "fS" }, { Feat = "fI" }, { Feat = "00000000-0000-0000-0000-000000000000" } }
      Ext.Entity.Get = function() return { Classes = { Classes = {
        { ClassUUID = "cR", SubClassUUID = "sG", Level = 9 }, { ClassUUID = "cF", SubClassUUID = "sB", Level = 3 } } },
        LevelUp = { LevelUps = ups }, SpellBook = { Spells = { { Id = { Prototype = "Projectile_FireBolt" } } } } } end
      local sheet = G.sheet
      G.sheet = function() return { slots = {}, resources = {} } end
      Osi.HasPassive = function() return 0 end
      G.results = { prep = { bare = {}, items = {} } }
      local spec = { real_respec = true, class_levels = { Ranger = 9, Fighter = 3 },
        subclass_names = { Ranger = "GloomStalker", Fighter = "BattleMaster" }, feats = { "Sharpshooter", "Ability Improvement +2 DEX" },
        spells_plan = { "Projectile_FireBolt" }, spells_add = { "Zone_NotKnown" } }
      T_ok = G.setupCheck({ char = "c1" }, spec, "start")
      spec.class_levels = { Ranger = 8, Fighter = 3, Rogue = 1 }
      spec.feats = { "Sharpshooter", "Alert" }
      spec.subclass_names.Fighter = "Champion"
      T_bad = G.setupCheck({ char = "c1" }, spec, "start")
      ups[#ups + 1] = { Feat = "fA" }
      ups[#ups + 1] = { Feat = "fA" }
      spec.class_levels = { Ranger = 9 }
      T_extra = G.setupCheck({ char = "c1" }, spec, "start")
      -- proficiency: an item the build is proficient with that the game calls non-proficient fails the run
      G.equipped = function() return { Breast = "it1", MeleeMainHand = "it2" } end
      Osi.GetStatString = function(it) return it == "it1" and "ARM_X" or "WPN_Y" end
      Osi.IsProficientWith = function(_, it) return it == "it1" and 0 or 1 end
      T_prof = G.setupCheck({ char = "c1" }, { items = { { slot = "Breast", stats = "ARM_X", proficient = true },
        { slot = "MeleeMainHand", stats = "WPN_Y", proficient = true }, { slot = "Amulet", stats = "A", proficient = nil } } },
        "start")
      G.equipped, G.sheet = eq, sheet
      Osi.GetStatString, Osi.IsProficientWith, Osi.HasPassive = nil, nil, nil
      Ext.Entity.Get = function() return nil end
      Ext.StaticData.Get = function() return nil end
    """)
    g = L.globals()
    calls = lst(g.T_calls)
    check("real respec: prep adds no passive, spell or sheet boost (only the carry limit)",
          g.T_respec == "real" and calls == ["AddBoosts CarryCapacityMultiplier(50)"], str(calls))
    ok = [(m.field, m.want, m.got) for m in g.T_ok.mismatches.values()]
    check("real respec: the character's classes, subclasses, feats and plan spells match the build", ok == [], str(ok))
    bad = sorted(m.field for m in g.T_bad.mismatches.values())
    check("real respec: a wrong class level, a missing class, a wrong subclass and a missing feat are named",
          {"class Ranger level", "class Rogue level", "subclass of Fighter", "feat alert"} <= set(bad), str(bad))
    extra = sorted((m.field, m.want, m.got) for m in g.T_extra.mismatches.values() if m.field.startswith("feat"))
    check("real respec: a feat taken twice that the build takes once is named", ("feat alert", 1, 2) in extra, str(extra))
    cls = sorted(m.field for m in g.T_extra.mismatches.values() if m.field.startswith("class"))
    check("real respec: a class the build does not have is named", cls == ["class Fighter level (not in the build)"],
          str(cls))
    pf = [m.field for m in g.T_prof.mismatches.values() if m.field.startswith("proficient")]
    check("proficiency: the game's non-proficient answer for a planned item fails the run; items without a "
          "proficiency are not asked", pf == ["proficient with ARM_X"], str(pf))


def py_tests():
    import plan as P
    import run as R
    xs = [10, 20, 30, 40, 50, 60, 70, 80]
    lo, hi = R.boot_ci(xs)
    check("bootstrap CI contains the mean", lo <= R.mean(xs) <= hi, f"{lo} {hi}")
    flat = [50.0, 52.0, 48.0, 51.0, 49.0, 50.0, 50.0, 51.0] * 3
    check("sequential stopping: two sides alike within the tolerance are decisive",
          R.decisive(flat, list(reversed(flat)), 0.15)[0] is True, R.decisive(flat, list(reversed(flat)), 0.15)[1])
    check("sequential stopping: a clear gap is decisive", R.decisive(flat, [x * 0.5 for x in flat], 0.15)[0] is True)
    noisy_a, noisy_b = [10, 90, 20, 80, 15, 85, 30, 70], [60, 40, 70, 30, 55, 45, 65, 35]
    check("sequential stopping: wide intervals and too few rounds are not decisive",
          R.decisive(noisy_a, noisy_b, 0.15)[0] is False and R.decisive(flat[:4], flat[:4], 0.15)[0] is False)
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
    import pairs as PA
    for t in (lambda: gate_tests(R), engine_tests, lambda: requirement_tests(P), lambda: rescore_tests(R),
              lambda: control_tests(PA), lambda: tuned_respec_tests(PA), lambda: grants_tests(P), lambda: reach_tests(P),
              lambda: lanes_py_tests(R), engine_lane_tests):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            check("python test block ran", False, repr(e)[:300])


def grants_tests(P):
    """What a real respec gives, as the setup check expects it: a game row held twice under two UUIDs counts once, the
    Battle Master manoeuvres are the respec's picks, and a passive the race grants is never on the remove list."""
    descs = {"f": {"UUID": "f", "Name": "Fighter", "ProgressionTableUUID": "tf"},
             "bm": {"UUID": "bm", "Name": "BattleMaster", "ParentGuid": "f", "ProgressionTableUUID": "tbm"},
             "gs": {"UUID": "gs", "Name": "GloomStalker", "ProgressionTableUUID": "tgs"}}
    row = {"TableUUID": "tbm", "Level": "3", "ProgressionType": "1", "Boosts": "ActionResource(SuperiorityDie,4,0)"}
    progs = {"1": dict(row, UUID="1"), "2": dict(row, UUID="2"),
             "3": {"UUID": "3", "TableUUID": "tf", "Level": "1", "ProgressionType": "0", "PassivesAdded": "SecondWind"},
             "4": {"UUID": "4", "TableUUID": "tgs", "Level": "3", "ProgressionType": "1",
                   "PassivesAdded": "Darkvision;UmbralSight"},
             "5": {"UUID": "5", "TableUUID": "tr", "Level": "1", "ProgressionType": "2", "PassivesAdded": "Darkvision"}}
    g = P.grants((progs, descs, {}, {}), ["Fighter"] * 3, {"Fighter": "Battle Master"}, [], [],
                 maneuvers=["MenacingAttack"])
    check("grants: a game row held twice under two UUIDs counts once (4 superiority dice, not 8)",
          g["resources"] == [{"kind": "SuperiorityDie", "level": 0, "n": 4}], str(g["resources"]))
    check("grants: the Battle Master manoeuvres are the respec's picks",
          "MenacingAttack" in g["passives"] and "Riposte" not in g["passives"], str(g["passives"]))
    check("grants: a passive the race grants is never removed", "Darkvision" not in g["passives_remove"] and
          "UmbralSight" in g["passives_remove"], str(g["passives_remove"]))
    mv = P.maneuver_picks([{"picks": ["Manoeuvres: Trip Attack, Riposte"]}, {"picks": ["Feat: Alert"]},
                           {"picks": ["Manoeuvres: Goading Attack (5th superiority die)"]}])
    check("grants: manoeuvre picks read from a test plan, notes in brackets dropped",
          mv == ["TripAttack", "Riposte", "GoadingAttack"], str(mv))


def tuned_respec_tests(PA):
    """Each side's respec is its test plan's: the tuner runs on the plan's gear only for a tuned plan, and a respec
    whose ability scores differ from the plan's stops the spec (the setup check would test the wrong character)."""
    calls = []

    class _St:
        def __init__(self, W, cid, bid, act, lo, sw, respec=None):
            self.sheet = {"abBase": dict((respec or {}).get("ab") or {"DEX": 17})}

    class _M:
        State = _St

    def tune(W, cid, bid, act, lo):
        calls.append(lo)
        return {"respec": {"ab": {"DEX": 18}}}
    plans = {"x.b.a3.1": {"char": "x", "build": "b", "act": 3, "gear": {"Ring1": {"id": "R1"}},
                          "respec": {"tuned": True, "abilities": {"DEX": 18}}},
             "x.b.a3.opt": {"char": "x", "build": "b", "act": 3, "gear": {}, "respec": {"tuned": False,
                                                                                         "abilities": {"DEX": 17}}},
             "x.b.a3.2": {"char": "x", "build": "b", "act": 3, "gear": {}, "respec": {"tuned": True,
                                                                                       "abilities": {"DEX": 16}}}}
    try:
        r = PA.tuned_respec(None, _M, tune, plans, "x.b.a3.1")
    except SystemExit as e:
        r = str(e)
    check("respec: a tuned test plan's respec comes from the tuner on the plan's gear",
          r == {"ab": {"DEX": 18}} and calls == [{"Ring1": "R1"}], f"{r} {calls}")
    check("respec: an untuned test plan keeps the build's picks", PA.tuned_respec(None, _M, tune, plans, "x.b.a3.opt")
          is None)
    try:
        PA.tuned_respec(None, _M, tune, plans, "x.b.a3.2")
        stopped = False
    except SystemExit:
        stopped = True
    check("respec: ability scores other than the plan's stop the spec", stopped)


class _Res:
    """A model result for the control tests: damage, durability numbers, turns lost, unknown effects."""

    def __init__(self, dpr, ac=20, hp=100, taken=10.0, saves=None, dr=0.0, mult=None, unknown=()):
        self.dpr, self.lost, self.unknown = dpr, 0.05, set(unknown)
        self.dur = {"incoming": taken, "R": hp / taken, "ac": ac, "hp": hp, "saves": saves or {"DEX": 5.0},
                    "dr": dr, "mult": mult or {}}


def control_tests(PA):
    """The control pair: the model rates the two sets alike in damage AND in damage taken (AC, HP, saves,
    resistances, damage reduction, damage taken, rounds survived); the search swaps items the model values alike."""
    n = PA.numbers
    ok, why = PA.control_check(n(_Res(70.0)), n(_Res(71.0)))
    check("control: equal damage and equal defence is a control", ok is True, str(why))
    ok, why = PA.control_check(n(_Res(70.0)), n(_Res(80.0)))
    check("control: damage 14% apart is no control", ok is False and any("damage per round" in w for w in why))
    ok, why = PA.control_check(n(_Res(70.0)), n(_Res(70.0, ac=21)))
    check("control: a different AC is no control (equal damage only is not enough)", ok is False and
          any(w.startswith("ac") for w in why), str(why))
    ok, why = PA.control_check(n(_Res(70.0)), n(_Res(70.0, taken=11.0)))
    check("control: 10% more damage taken is no control", ok is False and any("damage taken" in w for w in why),
          str(why))
    for kw, word in ((dict(saves={"DEX": 6.0}), "saving"), (dict(mult={"Fire": 0.5}), "resist"), (dict(dr=2.0), "dr")):
        ok, why = PA.control_check(n(_Res(70.0)), n(_Res(70.0, **kw)))
        check(f"control: a different {word} is no control", ok is False and any(word in w for w in why), str(why))
    # the search: ring R2 (adds 5, like R1) is a control swap; R3 adds AC; R4 grants an action; W2 sits in an idle slot
    value = {"R1": 5.0, "R2": 5.0, "R3": 5.0, "R4": 5.0, "W1": 3.0, "W2": 3.0, "H1": 2.0, "H2": 2.1, "B1": 2.0, "B2H": 2.0}

    def score(lo):
        ac = 21 if "R3" in lo.values() else 20
        return _Res(50.0 + sum(value.get(x, 0.0) for x in lo.values()), ac=ac)
    alts = {"Ring1": ["R2", "R3", "R4"], "MainHand": ["W2"], "Helmet": ["H2"], "Ranged": ["B2H"]}
    cands = PA.find_controls(score, [("base", {"Ring1": "R1", "MainHand": "W1", "Helmet": "H1", "Ranged": "B1"})],
                             lambda s: alts.get(s, []), lambda sid: sid == "R4", idle_slots=("MainHand",),
                             legal=lambda lo: lo.get("Ranged") != "B2H")
    swaps = [c["swaps"] for c in cands]
    check("control search: an equal-value swap is found, two swaps preferred", swaps and swaps[0] ==
          {"Ring1": "R2", "Helmet": "H2"} and {"Ring1": "R2"} in swaps, str(swaps))
    check("control search: a swap that changes the defence is left out", all("R3" not in s.values() for s in swaps))
    check("control search: an item with an action of its own is left out", all("R4" not in s.values() for s in swaps))
    check("control search: idle slots and sets the game would not let be worn are left out",
          all("MainHand" not in s and "Ranged" not in s for s in swaps), str(swaps))
    check("control: the chosen pair names a build, a base set and its swaps",
          all(PA.CONTROL.get(k) for k in ("char", "build", "act", "base", "swaps")))
    st = {"Ring_U": {"Boosts": "UnlockSpell(Target_X)"}, "Ring_P": {"PassivesOnEquip": "P1"},
          "P1": {"Boosts": "UnlockSpell(Shout_Y)"}, "Ring_N": {"Boosts": "RollBonus(Attack,1)"},
          "Bow": {"Weapon Properties": "Twohanded;Ammunition"}, "HX": {"Weapon Properties": "Light"}}
    check("control: actions granted by an item or its equip passive are found",
          PA.grants_action(st, "Ring_U") and PA.grants_action(st, "Ring_P") and not PA.grants_action(st, "Ring_N"))
    check("control: a two-handed weapon beside an off-hand cannot be worn",
          not PA.wearable(st, {"Ranged": "Bow", "RangedOff": "HX"}) and PA.wearable(st, {"Ranged": "HX", "RangedOff": "HX"}))


def reach_tests(P):
    """Lane spacing and proficiency data from the spell and item data."""
    st = {"Zone_Bolt": {"SpellType": "Zone", "Range": "30"},
          "Projectile_Ball": {"SpellType": "Projectile", "TargetRadius": "18", "ExplodeRadius": "4"},
          "Projectile_Chain": {"SpellType": "Projectile", "TargetRadius": "18",
                               "SpellSuccess": "DealDamage(1d8,Lightning);SpawnExtraProjectiles(Projectile_Chain_Jump)"},
          "Projectile_Chain_Jump": {"TargetRadius": "18"},
          "Projectile_Self": {"TargetRadius": "RangedMainWeaponRange",
                              "SpellFail": "SpawnExtraProjectiles(Projectile_Self)"},
          "Target_Melee": {"TargetRadius": "MeleeMainWeaponRange"}}
    check("reach: a zone reaches its length, a ball its range plus radius",
          P.spell_reach(st, "Zone_Bolt") == 30 and P.spell_reach(st, "Projectile_Ball") == 22)
    check("reach: spawned projectiles reach on from the target", P.spell_reach(st, "Projectile_Chain") == 36)
    check("reach: a spell that spawns itself counts once; weapon ranges by name",
          P.spell_reach(st, "Projectile_Self") == 18 and P.spell_reach(st, "Target_Melee") == 3)
    check("reach: the set's reach is its farthest spell", P.set_reach(st, ["Target_Melee", "Projectile_Chain"]) ==
          {"m": 36.0, "spell": "Projectile_Chain"})
    items = {"ARM_H": {"Proficiency Group": "HeavyArmor"}, "WPN_S": {"Proficiency Group": "Shortswords;MartialWeapons"},
             "RING": {"Proficiency Group": ""}, "HELM": {"PassivesOnEquip": "HP"}, "HP": {"Boosts": "Proficiency(HeavyArmor)"}}
    check("proficiency: by the item's groups; none needed for items without one",
          P.item_proficiency(items, "WPN_S", {"MartialWeapons"}) is True and
          P.item_proficiency(items, "ARM_H", {"LightArmor"}) is False and P.item_proficiency(items, "RING", set()) is None)
    check("proficiency: proficiencies an item grants (also through its equip passive)",
          P.granted_proficiencies(items, ["HELM", "RING"]) == ["HeavyArmor"])


def lanes_py_tests(R):
    """run.py's lane scheduling: the spacing rule, the sides swapping lanes and the first lane alternating per repeat,
    one character -> one after the other."""
    ar = {"a1": {"center": [0, 0, 0], "radius": 16}, "a2": {"center": [0, 0, 72], "radius": 16},
          "LN": {"lanes": {"A": {"arena": "a1"}, "B": {"arena": "a2"}}, "margin": 10}}
    ok, need, have = R.lane_gap(ar, "LN", [18, 12])
    check("lanes: two spots 72 m apart hold sets reaching 18 m (16 + 18 + 16 + 10)", ok and need == 60 and have == 72,
          f"{ok} {need} {have}")
    ok2, need2, _ = R.lane_gap(ar, "LN", [36, None])
    check("lanes: a set reaching 36 m is too far for them", ok2 is False and need2 == 78)
    sch = [R.lane_schedule(k) for k in range(4)]
    check("lanes: the sides swap lanes every repeat", [s["sides"]["A"] for s in sch] == ["a", "b", "a", "b"] and
          [s["sides"]["B"] for s in sch] == ["b", "a", "b", "a"], str(sch))
    check("lanes: the first lane alternates every repeat", [s["first"] for s in sch] == ["A", "B", "A", "B"])
    check("lanes: one lane only -> one after the other, the first side alternating",
          R.sequential_order(0) == ["a", "b"] and R.sequential_order(1) == ["b", "a"])

    class A_:
        lanes, char, char_b = "LN", "cA", None
    p = {"specs": {"a": {"reach": {"m": 18}}, "b": {"reach": {"m": 18}}}}
    ok3, why3 = R.lanes_possible(A_, p, ar)
    check("lanes: one character -> no two lanes, with the reason", ok3 is False and "one character" in why3, why3)
    A_.char_b = "cB"
    ok4, gap4 = R.lanes_possible(A_, p, ar)
    check("lanes: two characters and room -> two lanes, with the spacing they need", ok4 is True and gap4 == 60)
    p["specs"]["b"]["reach"]["m"] = 36
    ok5, why5 = R.lanes_possible(A_, p, ar)
    check("lanes: a pair whose spells reach the other lane runs one after the other", ok5 is False and "need" in why5,
          str(why5))


def engine_lane_tests():
    """engine.py: a run holds the lock (nothing else may use the eval hook meanwhile; the CLI refuses), released when
    it ends; a lane run returns each lane's record; a lane that never writes one is an invalid run."""
    import engine as E
    d = tempfile.mkdtemp(prefix="gauntlet_lanes_")
    old = (E.ev, E.RUNS, E.write_se, E.LOCK)
    try:
        E.RUNS, E.write_se, E.LOCK = d, (lambda name, obj: None), os.path.join(d, "active.lock")
        seen = {}

        def ev(code, timeout=10.0, side="server"):
            if "runLanes" in code:
                body = json.loads(code.split("[==[", 1)[1].split("]==]", 1)[0])
                seen["body"] = body
                seen["locked"] = E.active() is not None
                for e in body["entries"]:
                    if e["id"] in seen.get("write", ("A", "B")):
                        with open(os.path.join(d, f"run_1_00{e['id'] == 'A' and 1 or 2}_{e['id']}.json"), "w",
                                  encoding="utf-8") as f:
                            json.dump({"lanes_run": body["run_id"], "lane": e["id"], "valid": True}, f)
                    elif e["id"] == "B":
                        # a record of another lane run must not count for this one
                        with open(os.path.join(d, "run_0_000_B.json"), "w", encoding="utf-8") as f:
                            json.dump({"lanes_run": "lanes0", "lane": "B", "valid": True}, f)
                return "started"
            return "lanes " + seen["body"]["run_id"] + " on"
        E.ev = ev
        recs = E.run_lanes("LN", [("A", {"rounds": 2}, {}), ("B", {"rounds": 2}, {})], "B", gap_need=60, poll=0.01,
                           log=lambda *a: None)
        check("engine lanes: one start for both lanes, the first lane named", seen["body"]["first"] == "B" and
              [e["id"] for e in seen["body"]["entries"]] == ["A", "B"])
        check("engine lanes: each lane's record returned", sorted(recs) == ["A", "B"] and
              recs["A"]["lane"] == "A", str(recs))
        check("engine: the run holds the lock while it runs and drops it after", seen["locked"] is True and
              E.active() is None)
        for fn in os.listdir(d):
            os.remove(os.path.join(d, fn))
        seen["write"] = ("A",)
        try:
            E.run_lanes("LN", [("A", {}, {}), ("B", {}, {})], "A", timeout=0.2, poll=0.01, log=lambda *a: None)
            raised = None
        except E.RunInvalid as e:
            raised = str(e)
        check("engine lanes: a lane without a record is an invalid run, not a hang", raised is not None and
              "did not finish" in raised, str(raised))
        check("engine: the lock is dropped after a failed run too", E.active() is None)
        E.ev = lambda *a, **k: (_ for _ in ()).throw(AssertionError("eval while a run is active"))
        with E._Held("test", 60):
            rc = E.main(["engine.py", "eval", "return 1"])
        check("engine: the CLI does not talk to the game while a run holds the lock", rc == 2)
    finally:
        E.ev, E.RUNS, E.write_se, E.LOCK = old
        shutil.rmtree(d, ignore_errors=True)


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
    pt = _pair("x", 100, 101)
    pt["model"].update(a_taken=10.0, b_taken=13.0, a_R=10.0, b_R=7.7)
    check("control: equal damage but more damage taken is no control", not R.is_control(pt))
    pt["model"].update(b_taken=10.2, b_R=9.8)
    check("control: equal damage and equal damage taken is a control", R.is_control(pt))
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


def requirement_tests(P):
    """Spell requirements read from the data before the run: weapon actions need a melee weapon the build is
    proficient with; such a spell is not planned when the set cannot meet it."""
    st = {"Target_Topple": {"RequirementConditions": "CanUseWeaponActions() and IsProficientWithEquippedWeapon()"},
          "Shout_SteadyRanged": {"RequirementConditions": "not HasStatus('ENCUMBERED_MAX') and CanUseWeaponActions()"},
          "Projectile_FireBolt": {}, "MAG_Staff": {"Proficiency Group": "Quarterstaffs;SimpleWeapons"},
          "MAG_Sword": {"Proficiency Group": "Greatswords;MartialWeapons"}}
    check("requirements: weapon action, proficiency, encumbrance read from the data",
          P.spell_requirements(st, "Target_Topple") == ["melee weapon", "proficient weapon"] and
          "not encumbered" in P.spell_requirements(st, "Shout_SteadyRanged") and
          P.spell_requirements(st, "Projectile_FireBolt") == [])
    check("requirements: a weapon action without a melee weapon is unusable",
          P.unusable_reason(st, "Target_Topple", None, ["Quarterstaffs"]) == "needs a melee weapon in the main hand")
    check("requirements: a weapon the build is not proficient with makes it unusable",
          (P.unusable_reason(st, "Target_Topple", "MAG_Sword", ["Quarterstaffs", "Daggers"]) or "").startswith(
              "not proficient") and P.unusable_reason(st, "Target_Topple", "MAG_Staff", ["Quarterstaffs"]) is None)
    check("requirements: a spell without requirements is usable",
          P.unusable_reason(st, "Projectile_FireBolt", None, []) is None)


# The control of the pilot re-run (two sets the model rates 129.9 vs 132.6 DPR), first records: damage per round, and
# the rounds in which the character was down or no cast went through on the b side (harness faults).
R7_A = [69, 51, 43, 43, 41, 47, 43, 34, 31, 41, 19, 33, 23, 28, 17, 23]
R7_B = [58, 53, 0, 70, 55, 60, 38, 48, 40, 53, 48, 37, 0, 21, 14, 0]
R7_B_FAIR = [i not in (2, 12, 14, 15) for i in range(16)]


def _r7_rec(side, dealt, fair, causes=()):
    rounds = [{"r": i + 1, "done": {"action": True} if f else [], "char_hp_before": 50 if f else 0}
              for i, f in enumerate(fair)]
    return {"mode": "scripted", "pair": 0, "side": side, "scenario": "boss", "haste": False, "valid": not causes,
            "invalid": list(causes), "rounds": rounds,
            "results": {"summary": {"dealt": dealt, "taken": [0] * len(dealt), "max_hp": 88}}}


def rescore_tests(R):
    """Older run records re-judged under the current rules, and the control gate on the pilot re-run's control."""
    fair = R.fair_rounds(_r7_rec("b", R7_B, R7_B_FAIR))
    check("rescore: rounds down or without a confirmed action are not fair", fair == R7_B_FAIR, str(fair))
    down = R.fair_rounds({"rounds": [{"r": 1, "downed": True, "done": {"action": True}},
                                     {"r": 2, "char_hp_before": 0, "done": {"action": True}},
                                     {"r": 3, "char_hp_before": 40, "done": {"item": True}}]})
    check("rescore: a round the character started down is not fair, whatever else the record shows",
          down == [False, False, True], str(down))
    ok, causes, _ = R.rescore(_r7_rec("b", R7_B, R7_B_FAIR, ["the test character cast outside the plan: "
                                                             "Target_Legendary_ShieldBlow_Riposte",
                                                             "4 round(s) without a confirmed action"]))
    check("rescore: an item spell's cast is not foreign; idle rounds are never masked (the run fails)",
          not ok and causes == ["4 round(s) without a confirmed action"], str(causes))
    ok2, causes2, _ = R.rescore(_r7_rec("a", R7_A[:2], [True, True], ["ended: the character's turn could not be ended"]))
    check("rescore: a run that ended early stays void", not ok2 and "ended" in causes2[0], str(causes2))
    ok3, causes3, _ = R.rescore(_r7_rec("a", R7_A[:5], [True] * 5))
    check("rescore: too few fair rounds is no measurement", not ok3 and "fair rounds" in causes3[0], str(causes3))
    rec4 = _r7_rec("b", R7_B[:3], [True] * 3)
    rec4["results"]["ended"] = "downed"
    ok4, causes4, _ = R.rescore(rec4)
    check("rescore: a run the character's down ended is short by its result and stays usable", ok4, str(causes4))
    pairs = [_pair("gale", 129.9, 132.6)]
    by = {(0, "a", "boss", False): {"dealt": R7_A, "clean": [True] * 16},
          (0, "b", "boss", False): {"dealt": R7_B, "clean": R7_B_FAIR}}
    g = R.control_gate(pairs, by, 0.15)
    c = g["controls"][0] if g["controls"] else {}
    check("control gate: the pilot re-run's control passes on the rounds fair on both sides (17%, within the dice)",
          g["valid"] is True and c.get("rounds") == 12 and abs(c.get("a", 0) - 40.0) < 0.05, str(g))
    by_all = {k: {"dealt": v["dealt"]} for k, v in by.items()}
    g2 = R.control_gate(pairs, by_all, 0.15)
    check("control gate: without the fair-round masks the faulty rounds count", g2["controls"][0]["rounds"] == 16,
          str(g2))
    far = {(0, "a", "boss", False): {"dealt": [40] * 16}, (0, "b", "boss", False): {"dealt": [55] * 16}}
    check("control gate: a steady gap beyond the dice fails even under twice the tolerance",
          R.control_gate(pairs, far, 0.15)["valid"] is False)
    few = {(0, "a", "boss", False): {"dealt": R7_A, "clean": [True] * 6 + [False] * 10},
           (0, "b", "boss", False): {"dealt": R7_B, "clean": R7_B_FAIR}}
    check("control gate: fewer than 8 rounds fair on both sides is not a pass",
          R.control_gate(pairs, few, 0.15)["valid"] is False)


def engine_tests():
    """engine.run: a busy game that misses evals is asked again; a game that stops answering, or a run that never
    finishes, is an invalid run with its cause, never a hang."""
    import engine as E
    d = tempfile.mkdtemp(prefix="gauntlet_runs_")
    old = (E.ev, E.RUNS, E.write_se, E.LOCK)
    try:
        E.RUNS, E.write_se, E.LOCK = d, (lambda name, obj: None), os.path.join(tempfile.gettempdir(), "gauntlet_t.lock")
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
        E.ev, E.RUNS, E.write_se, E.LOCK = old
        shutil.rmtree(d, ignore_errors=True)


# ============================================================================================ mutations
GL, PL, RN, EN, PA = "gauntlet.lua", "plan.py", "run.py", "engine.py", "pairs.py"
MUTATIONS = [
    ("lanes: one state for all lanes", GL, "  for _, k in ipairs(G.LANE_FIELDS) do G[k] = nxt[k] end\n",
     "  for _, k in ipairs({}) do G[k] = nxt[k] end\n"),
    ("lanes: a timer loses its lane", GL, "    local ok, err = pcall(G.inLane, lane, fn)",
     "    local ok, err = pcall(fn)"),
    ("lanes: every event to every lane", GL, "  if #out == 0 then return L.order end\n  return out",
     "  return L.order"),
    ("lanes: hits across lanes not counted", GL, "if id ~= mine and m[row.target] and (row.amount or 0) > 0 then n = n + 1 end",
     ""),
    ("lanes: hits across lanes ignored by the verdict", GL, "  if (results.cross_lane_hits or 0) > 0 then", "  if false then"),
    ("lanes: a shared combat ignored", GL, "if c ~= \"nil\" and c == R.combat then R.combat_shared = true end", ""),
    ("lanes: enemies hostile to both lanes", GL, "      local v = (i == j) and 0 or 50", "      local v = 0"),
    ("lanes: shared character faction kept", GL, "    if shared and lane.char_faction then", "    if false then"),
    ("lanes: relations never put back", GL, "    if r.was ~= nil then pcall(Osi.SetRelation, r.a, r.b, r.was); n = n + 1 end",
     ""),
    ("lanes: isolation not checked", GL, "      cmp(\"enemy \" .. i .. \" not hostile to lane \" .. id .. \"'s character\", 0, "
     "try(Osi.IsEnemy, e, u))", ""),
    ("lanes: spacing not checked", GL, "F.lane.gap_need == nil or d >= F.lane.gap_need)", "true)"),
    ("lanes: enemies in the shared enemy faction", GL,
     "G.spawnEnemies(pts, E, (F.lane and F.lane.enemy_faction) or C.enemy_faction)", "G.spawnEnemies(pts, E, C.enemy_faction)"),
    ("lanes: each lane parks the party itself", GL,
     "G.results.parked = F.lane and G.LANES and G.LANES.parkedCount or G.parkOthers(u, A and A.park)",
     "G.results.parked = G.parkOthers(u, A and A.park)"),
    ("lanes: enemies not listed as the lane's", GL, "    for _, d in ipairs(F.enemies) do m[uuid(d)] = true end", ""),
    ("lanes: no barrier", GL, "    if not F or (F.state ~= \"ready\" and F.state ~= \"done\") then return end", ""),
    ("lanes: isolation not added to the setup check", GL,
     "    for _, m in ipairs(iso) do sc.mismatches[#sc.mismatches + 1] = m end", ""),
    ("lanes: party back while a lane fights", GL, "    if F and F.state ~= \"done\" then return end\n  end\n  L.restored",
     "  end\n  L.restored"),
    ("lanes: only the first lane stepped", GL, "    for _, id in ipairs(L.order) do G.inLane(id, stepLane) end",
     "    G.inLane(L.order[1], stepLane)"),
    ("lanes: the other lane's character parked", GL, "    if m ~= uuid(u) and not (keep and keep[m]) then",
     "    if m ~= uuid(u) then"),
    ("lanes: high ground in one lane only", GL, "    if not (A and A.high) then allHigh = false end", ""),
    ("lanes: single runs allowed during lanes", GL,
     "  if G.LANES and G.LANES.on and not req.lane then return \"busy\" end", ""),
    ("respec: emulation on a real respec", GL, "  local emulate = not spec.real_respec", "  local emulate = true"),
    ("respec: classes not compared", GL,
     "    for cls, n in pairs(spec.class_levels or {}) do cmp(\"class \" .. cls .. \" level\", n, lv[cls] or 0) end", ""),
    ("respec: extra classes allowed", GL,
     "      if not (spec.class_levels or {})[cls] then cmp(\"class \" .. cls .. \" level (not in the build)\", 0, n) end",
     ""),
    ("respec: subclasses not compared", GL,
     "    for cls, want in pairs(spec.subclass_names or {}) do cmp(\"subclass of \" .. cls, want, sub[cls]) end", ""),
    ("respec: feats not compared", GL, "      for n, k in pairs(want) do cmp(\"feat \" .. n, k, have[n] or 0) end", ""),
    ("respec: feats taken twice pass", GL, "if not isAbilityFeat(n) then out[n] = (out[n] or 0) + 1 end",
     "if not isAbilityFeat(n) then out[n] = 1 end"),
    ("proficiency: not asked", GL, "      if phase == \"start\" and it.proficient == true then",
     "      if false then"),
    ("control: damage taken not required alike", RN,
     "        if m.get(ka) and m.get(kb) and abs(m[ka] / m[kb] - 1) > CONTROL_MODEL_EQ:\n            return False",
     "        pass"),
    ("schedule: sides never swap lanes", RN,
     "    sides = {lane_ids[0]: \"a\", lane_ids[1]: \"b\"} if k % 2 == 0 else {lane_ids[0]: \"b\", lane_ids[1]: \"a\"}",
     "    sides = {lane_ids[0]: \"a\", lane_ids[1]: \"b\"}"),
    ("schedule: the first lane never alternates", RN, "    first = lane_ids[k % 2]", "    first = lane_ids[0]"),
    ("schedule: one lane, same order every repeat", RN,
     "    return list(sides) if k % 2 == 0 else list(reversed(sides))", "    return list(sides)"),
    ("spacing: spell reach ignored", RN, "        need = max(need, x[\"radius\"] + reach + y[\"radius\"] + float(LS.get(\"margin\") or 0))",
     "        need = max(need, x[\"radius\"] + y[\"radius\"])"),
    ("lanes: one character accepted", RN, "    if not a.char or not a.char_b:", "    if not a.char:"),
    ("lanes: too-close lanes accepted", RN, "    if not ok:\n        return False, f\"lanes", "    if False:\n        return False, f\"lanes"),
    ("engine: no lock during a lane run", EN,
     "    with _Held(\"lanes \" + \",\".join(i for i, _r, _s in entries), timeout + 60):\n        return _run_lanes(",
     "    if True:\n        return _run_lanes("),
    ("engine: the CLI ignores the lock", EN, "    held = active()", "    held = None"),
    ("engine: lane records of another run accepted", EN,
     "if rec.get(\"lanes_run\") == run_id and rec.get(\"lane\") in want:", "if rec.get(\"lane\") in want:"),
    ("reach: spawned projectiles ignored", PL, "    return own + max(spawned + [0.0])", "    return own"),
    ("reach: area radius ignored", PL,
     "        own = _num(st.get(\"TargetRadius\")) + max([_num(st.get(k)) for k in AREA_KEYS] + [0.0])",
     "        own = _num(st.get(\"TargetRadius\"))"),
    ("proficiency: item-granted proficiencies ignored", PL, "            txt += \";\" + ((stats.get(p) or {}).get(\"Boosts\") or \"\")\n"
     "        out += re.findall", "            pass\n        out += re.findall"),
    ("control: AC not compared", PA, "    for k in (\"ac\", \"hp\", \"dr\"):", "    for k in (\"hp\", \"dr\"):"),
    ("control: damage taken not compared", PA, "    if _rel(na[\"taken\"], nb[\"taken\"]) > tol:", "    if False:"),
    ("control: saves not compared", PA, "    if na[\"saves\"] != nb[\"saves\"]:", "    if False:"),
    ("control: resistances not compared", PA, "    if na[\"resist\"] != nb[\"resist\"]:", "    if False:"),
    ("enemy: abilities forced before the stats are there", GL, "  if not G.enemyReady(d) then", "  if false then"),
    ("enemy: abilities not in the setup check", GL,
     "      for _, n in ipairs(ABIL) do cmp(\"enemy \" .. i .. \" \" .. n, 10, ab[n]) end", ""),
    ("enemy: worn items not in the setup check", GL, "      cmp(\"enemy \" .. i .. \" items worn\", 0, gear)", ""),
    ("party: player characters outside DB_Players left out", GL,
     "if u and not seen[u] and try(Osi.IsPlayer, u) == 1 then", "if false then"),
    ("hostility: only one way", GL, "  for _, p in ipairs({ { a, b }, { b, a } }) do", "  for _, p in ipairs({ { a, b } }) do"),
    ("cast: the engine moves before a cast", GL, "pcall(Osi.UseSpell, F.char, a.spell, tgt, tgt, 1)",
     "pcall(Osi.UseSpell, F.char, a.spell, tgt)"),
    ("grants: duplicate game rows counted twice", PL, "            if key in seen:\n                continue", "            pass"),
    ("grants: race passives removed", PL, "    remove = sorted(all_class_passives - set(passives) - race_passives)",
     "    remove = sorted(all_class_passives - set(passives))"),
    ("grants: fixed manoeuvres", PL, "        passives.extend(maneuvers or MANEUVERS)", "        passives.extend(MANEUVERS)"),
    ("respec: the plan's ability scores not compared", PA, "    if want and got != want:", "    if False:"),
    ("respec: tuned plans keep the build's picks", PA, "    if rs.get(\"tuned\"):", "    if False:"),
    ("control: damage not compared", PA, "    if _rel(na[\"dpr\"], nb[\"dpr\"]) > tol:", "    if False:"),
    ("control search: items with actions swapped", PA, "if alt == cur or alt in lo.values() or has_action(alt):",
     "if alt == cur or alt in lo.values():"),
    ("control search: idle slots swapped", PA, "            if slot in idle_slots or has_action(cur):",
     "            if has_action(cur):"),
    ("control search: unwearable sets", PA, "            if not legal(lo2):\n                continue\n", ""),
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
     "if c.who == me and not allowed[core(c.spell)] and not G.itemSpell(c.spell) and not (aoo and weapon) then",
     "if false then"),
    ("verdict: item spells count as foreign", GL,
     "and not G.itemSpell(c.spell) and not (aoo and weapon) then", "and not (aoo and weapon) then"),
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
    ("equip: no second ask", GL, "if not again and waited >= G.EQUIP_MS / 2 then again = true; t0 = now() - G.EQUIP_MS / 2; pcall(Osi.Equip, u, it, 1, 0, 0) end", ""),
    ("equip: no wait for the equip", GL, "if not where and (waited < G.EQUIP_MS or not again) then", "if false then"),
    ("equip: a slow frame skips the second ask", GL, "if not where and (waited < G.EQUIP_MS or not again) then",
     "if not where and waited < G.EQUIP_MS then"),
    ("rescore: a down-ended run voided as too short", RN, "if not left and not downed and sum(clean)", "if not left and sum(clean)"),
    ("enemies: damage not scaled", GL, "  local E = G.scaleEnemy(E0, req.enemy_damage_scale or S.enemy_damage_scale or G.ENEMY_DAMAGE_SCALE)",
     "  local E = E0"),
    ("enemies: default scale 1", GL, "G.ENEMY_DAMAGE_SCALE = 0.5", "G.ENEMY_DAMAGE_SCALE = 1"),
    ("setup: mismatches ignored", GL, "    if sc and #sc.mismatches > 0 then", "    if false then"),
    ("setup: refused casts ignored", GL, "  if refused > 0 then causes", "  if false then causes"),
    ("setup: sheet numbers not compared", GL, '  if sh.hp then cmp("max HP", sh.hp, bare.hp) end', ""),
    ("setup: buffs not compared", GL,
     '  for _, st in ipairs((extra and extra.buffs) or {}) do cmp("buff " .. st, true, try(Osi.HasActiveStatus, u, st) == 1) end', ""),
    ("revive: the dead stay dead", GL, "  if try(Osi.IsDead, u) == 1 then pcall(Osi.Resurrect, u) end", ""),
    ("stopping: never decisive on equality", RN, "    if ci[0] >= 1 - tol and ci[1] <= 1 + tol:", "    if False:"),
    ("stopping: decisive on any interval", RN, '    return False, f"ratio 95% interval', '    return True, f"ratio 95% interval'),
    ("gate: tolerance ignored", RN, "if diff > 2 * tol or (diff > tol and beyond_dice):", "if False:"),
    ("gate: one-sided control passes", RN, 'causes.append(f"control pair {i} ({p[\'char\']} {p[\'build\']}) not measured '
     'on both sides")', "pass"),
    ("validity: game verdict ignored", RN,
     'valid = rec.get("valid", res.get("valid", True)) is not False and not causes', "valid = True"),
    ("slots: weapon slot names not tried", GL, "for _, n in ipairs(G.SLOT_NAMES[s] or { s }) do",
     "for _, n in ipairs({ s }) do"),
    ("verdict: unworn set items ignored", GL, "if #unworn > 0 then causes", "if false then causes"),
    ("encumbrance: no carry boost", GL, "if addBoost then boost(u, G.CARRY_BOOST) end", "if false then end"),
    ("encumbrance: verdict ignores it", GL, "if results.encumbered and #results.encumbered > 0 then", "if false then"),
    ("items: earlier runs' items kept", GL, "if pcall(Osi.RequestDelete, it) then n = n + 1 end", "n = n + 1"),
    ("refusal: CastSpellFailed ignored", GL, "local refused = G.castRefused(P, R.cast_fails)", "local refused = nil"),
    ("refusal: any caster's failure counts", GL, "if f.who == P.who and baseSpell(f.spell) == baseSpell(P.spell) then",
     "if baseSpell(f.spell) == baseSpell(P.spell) then"),
    ("refusal: Attack of Opportunity not named", GL,
     'if tostring(x.interrupt):find("AttackOfOpportunity", 1, true) then aoo = true end', ""),
    ("start: Attacks of Opportunity banned", GL, "        G.results.ignore_leave_attack_range = false",
     "        boost(u, G.AOO_BOOST); G.results.ignore_leave_attack_range = false"),
    ("start: HP buffer given", GL, "G.HP_BUFFER = 0", "G.HP_BUFFER = 200"),
    ("refusal: no retry after an Attack of Opportunity", GL,
     'if refused and tries < G.CAST_RETRIES and (tries > 0 or reason.why:find("Attack of Opportunity", 1, true)) then',
     "if false then"),
    ("refusal: any refusal retried", GL,
     'if refused and tries < G.CAST_RETRIES and (tries > 0 or reason.why:find("Attack of Opportunity", 1, true)) then',
     "if refused and tries < G.CAST_RETRIES then"),
    ("refusal: retries without a limit", GL, "G.CAST_RETRIES = 2", "G.CAST_RETRIES = 99"),
    ("foreign: own Attack of Opportunity voids the run", GL, "and not (aoo and weapon) then", "then"),
    ("down: a down does not end the run", GL,
     'if not F.manual and G.round > 0 and (try(Osi.GetHitpoints, F.char) or 1) <= 0 then return finish(F, "downed") end',
     ""),
    ("down: a down voids the run", GL, 'and why ~= "rounds done" and why ~= "downed" then', 'and why ~= "rounds done" then'),
    ("movement: casts never move first", GL, "    local spot = G.castSpot(F, tgt, range)", "    local spot = nil"),
    ("movement: a route leaving reach is preferred", GL, "if not bad and (not best or len < best.len) then best = c end",
     "best = best or c"),
    ("start: no precheck", GL, "G.results.precheck = G.precheck(F)", "G.results.precheck = {}"),
    ("precheck: nothing marked unusable", GL, "    if #hard > 0 then\n      F.unusable[spell]",
     "    if false then\n      F.unusable[spell]"),
    ("precheck: the spell book also judges the build's spells", GL, "(isItem or b ~= \"not in the spell book\")",
     "true"),
    ("afford: unusable spells still planned", GL, "if F.unusable and F.unusable[a.spell] then return false",
     "if false then return false"),
    ("verdict: downed rounds counted as idle", GL, "if not R.downed and not (R.done", "if not (R.done"),
    ("summary: HP buffer counted as the sheet's", GL, "- (F.hpBuffer or 0))", "- 0)"),
    ("run boosts: HP buffer left on", GL, 'list[#list + 1] = string.format("IncreaseMaxHP(%d)", hpBuffer)', ""),
    ("cleanup: earlier runs' enemies skipped by the arena check", GL,
     "if u and not party[u] and standing(u) and inArena(u, A) then",
     "if u and not party[u] and not (G.spawned or {})[u] and standing(u) and inArena(u, A) then"),
    ("cleanup: leftovers never killed", GL, "      if standing(d) then\n        pcall(Osi.Die",
     "      if false then\n        pcall(Osi.Die"),
    ("cleanup: summons left behind", GL, "if u and u ~= me and try(Osi.IsSummon, u) == 1", "if false and u"),
    ("verdict: hits from outside the run ignored", GL, "if (results.outside_hits or 0) > 0 then", "if false then"),
    ("requirements: weapon actions without a weapon planned", PL, 'if "melee weapon" in reqs and not main_hand:',
     "if False:"),
    ("requirements: proficiency not checked", PL, "if groups and not set(groups) & set(proficiencies):",
     "if False:"),
    ("gate: fair-round masks ignored", RN, "if ca is not None and cb is not None and", "if False and"),
    ("gate: dice not considered", RN, "if diff > 2 * tol or (diff > tol and beyond_dice):", "if diff > tol:"),
    ("gate: gross gap passes within the dice", RN, "if diff > 2 * tol or (diff > tol and beyond_dice):",
     "if diff > tol and beyond_dice:"),
    ("gate: too few fair rounds pass", RN, "if min(len(xa), len(xb)) < CONTROL_MIN_ROUNDS:", "if False:"),
    ("rescore: idle rounds masked", RN, "    for c in causes:\n        if c.startswith(",
     "    for c in causes:\n        if 'without a confirmed action' in c:\n            continue\n"
     "        if c.startswith("),
    ("rescore: down rounds fair", RN, "down = bool(R.get(\"downed\")) or (hp is not None and hp <= 0)",
     "down = False"),
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
