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
- what the worn items add to the resources (a status an item puts on), spells allowed only out of combat never
  planned, the character's own summon's turn ended, bystanders in a lane moved away and back;
- the control pair: equal damage and equal damage taken in the model, and the search for one;
- the player cast path (the default): a click's request (FromClient, no Ignore* option, the spell's own SpellType as the
  TargetingType, its spell-book id); refusals with their reason and never asked for again, range or sight make the run
  invalid; what each cast spent checked against its costs; a toggled attack with no bonus action goes untoggled;
  Action Surge's attacks booked as the engine charges them (the surge's action, then free Extra Attacks); the
  off-hand half told by its place in the cast (a melee one comes as cause Attack); a melee attack never a Projectile;
- between runs the cooldowns reset like a long rest (a rest cooldown reads -1), and the setup check reads the plan's
  once-per-rest steps ready;
- the player path's next request waits until the last attack has landed (its damage row, a quiet spell, a toggled
  attack's off-hand half), never longer than a cap and never for a self cast or a spell that is no attack;
- real rolls (old path): the run's casters' queued Osiris casts lose IgnoreSpellRolls (nothing else, no other caster, not the
  reaction queue), on by default and recorded per run; a missed cast is done, with its outcome; riders and the turns
  of party members outside the fight; run.py counts and reports only runs of the same kind.
"""
import contextlib
import io
import itertools
import json
import math
import os
import re
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


def seq(t, n):
    """The first n values of a Lua list that may hold nils."""
    return [t[i + 1] for i in range(n)]


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
    check("arenas.json: a lanes entry's npc_park lies outside every lane (radius + margin)",
          all(math.hypot(a["npc_park"][0] - ar[x["arena"]]["center"][0], a["npc_park"][2] - ar[x["arena"]]["center"][2])
              > ar[x["arena"]]["radius"] + a.get("margin", 0) for a in lane_sets if "npc_park" in a
              for x in a["lanes"].values()) and any("npc_park" in a for a in lane_sets))
    for t in (reaction_tests, item_cost_tests, cast_tests, plan_round_tests, watchdog_tests, verdict_tests, equip_tests,
              encumbrance_tests, refusal_tests, precheck_tests, downed_tests, cleanup_tests, start_tests,
              rules_tests, setup_tests, lane_tests, respec_tests, enemy_tests, party_tests, item_resource_check_tests,
              summon_turn_tests, npc_park_tests, summon_attack_tests, item_rule_surge_tests, toggle_tests,
              carry_over_tests, crit_tests, effect_check_tests, rider_tests, hit_log_tests, speed_tests,
              plan_gap_lua_tests, real_roll_tests, outcome_tests, idle_turn_tests, popup_tests, release_tests,
              boss_reuse_tests, campaign_tests, roll_tests, offhand_melee_tests, rest_reset_tests,
              impact_wait_tests, phase_reaction_tests, step_validity_tests, policy_tests, conc_rider_tests,
              sneak_row_tests, miss_row_tests, cast_noise_tests, action_rolls_tests, arena_camera_tests,
              cast_id_tests, holder_idle_tests, end_turn_tests, engine_gate_tests, record_gap_tests,
              save_log_tests):
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
      -- the turn guard counts from the last progress: a cast requested 40 s into the turn and still held by the engine
      -- is not cut at 95 s; with no progress for ACT_MAX_MS the turn is ended
      G.reset(); G.round = 2
      G.rounds = { { r = 2, done = {}, actions = {}, casts = {} } }
      local settle = G.settle
      G.settle = function() return false end
      local F3 = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                   started = 1, state = "act", next = 0, turnStart = 0, progressT = 40000,
                   pending = { rec = { result = "pending" }, t0 = 40000 } }
      G.F = F3
      G.step(F3, 95000)
      T_guard1 = F3.state
      F3.next = 0
      G.step(F3, 40000 + G.ACT_MAX_MS + 1)
      T_guard2 = F3.state
      G.settle = settle
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
    check("watchdog: a missing turn is recovered first (once), not ended", g.T_r1 == "wait" and g.T_rec == 1,
          str(g.T_rec))
    check("watchdog: after the recoveries the run ends, invalid, with the cause",
          g.T_end == "done" and g.T_valid is False and "turn never came" in str(g.T_why), str(g.T_why))
    check("watchdog: an own turn that will not end is retried, then the run ends invalid",
          g.T_end2 == "done" and "could not be ended" in str(g.T_why2), str(g.T_why2))
    check("turn guard: a cast still held 55 s after its request is not cut; no progress for ACT_MAX_MS ends the turn",
          g.T_guard1 == "act" and g.T_guard2 == "ending", f"{g.T_guard1} {g.T_guard2}")
    check("run start: returns at once, prep not yet started", g.T_run == "started" and g.T_status == "starting",
          f"{g.T_run} {g.T_status}")
    check("run start: a bad request still ends in an invalid run record",
          g.T_after == "done" and "bad request" in str(g.T_bad) and g.T_saved >= 1, str(g.T_bad))
    check("run start: prep that never finishes -> invalid run, not a hang",
          "prep timed out" in str(g.T_prep) and g.T_prep_valid is False, str(g.T_prep))
    # Action Surge on the player path: done only once its extra action point is in (in game it came ~70 ms after the
    # status), or CAST_MAX_MS after the request (after a riposte the cast itself came 6 s late)
    L.execute(r"""
      local G = GAUNTLET
      G.reset(); G.t0 = 0
      local has, ap = 0, 1
      local hs, ar = Osi.HasActiveStatus, Osi.GetActionResourceValuePersonal
      Osi.HasActiveStatus = function(u, s) if s == "ACTION_SURGE" then return has end return 0 end
      Osi.GetActionResourceValuePersonal = function(u, kind) if kind == "ActionPoint" then return ap end return 0 end
      local function pending()
        local rec = { spell = "Shout_ActionSurge" }
        local R = { r = 6, actions = { rec }, casts = { { who = "c1", spell = "Shout_ActionSurge" } }, done = {} }
        local F = { char = "c1", enemies = {}, cooldown = {}, plan = {} }
        F.pending = { a = { spell = "Shout_ActionSurge", group = "free" }, rec = rec, spell = "Shout_ActionSurge",
                      who = "c1", target = "c1", player = true, casts0 = 0, dmg0 = 0, t0 = 0, costs = {}, res = {},
                      before = {}, snap0 = {}, ap0 = 1 }
        return F, R
      end
      local F, R = pending()
      T_s1 = G.settle(F, R, 100)
      has = 1
      T_s2 = G.settle(F, R, 150)
      T_d2 = R.done.surge == true
      ap = 2
      T_s3 = G.settle(F, R, 250)
      T_d3 = R.done.surge == true
      ap, has = 1, 0
      local F2, R2 = pending()
      T_c1 = G.settle(F2, R2, 6100)
      T_c2 = G.settle(F2, R2, 60000)
      Osi.HasActiveStatus, Osi.GetActionResourceValuePersonal = hs, ar
    """)
    g = L.globals()
    check("Action Surge: not done before its action point is in (status on is not enough), done once it is",
          g.T_s1 is False and g.T_s2 is False and g.T_d2 is False and g.T_s3 is True and g.T_d3 is True,
          str((g.T_s1, g.T_s2, g.T_d2, g.T_s3, g.T_d3)))
    check("Action Surge: a cast that comes 6 s late is still waited for, the wait capped",
          g.T_c1 is False and g.T_c2 is True, str((g.T_c1, g.T_c2)))
    # a record is written whatever the probes hold: values Stringify refuses (an Entity) kept as text
    L.execute(r"""
      local f = function() end
      local v = GAUNTLET.jsonSafe({ a = 1, s = "x", b = { c = f, d = true }, e = { 1, 2 } })
      T_js = { type(v.a), type(v.s), type(v.b.c), type(v.b.d), #v.e }
    """)
    js = list(g.T_js.values())
    check("record: jsonSafe keeps numbers, strings, booleans, tables and writes anything else as text",
          js == ["number", "string", "string", "boolean", 2], str(js))
    # the combat's first turn: the first request waits longer (in game one sent 200 ms after it started was refused)
    L.execute(r"""
      local G = GAUNTLET
      local me = { TurnBased = { IsActiveCombatTurn = true } }
      local get = Ext.Entity.Get
      Ext.Entity.Get = function(u) if u == "c3" then return me end end
      T_next = {}
      for _, r0 in ipairs({ 0, 4 }) do
        G.reset(); G.round = r0; G.t0 = 0
        local F = { char = "c3", enemies = {}, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                    started = 1, state = "wait", deadline = 1e12 }
        G.F = F
        G.step(F, 1000)
        T_next[#T_next + 1] = (F.next or 0) - 1000
      end
      Ext.Entity.Get = get
    """)
    nx = list(g.T_next.values())
    check("first turn: the combat's first request waits FIRST_ACT_DELAY_MS, later turns ACT_DELAY_MS",
          nx == [g.GAUNTLET.FIRST_ACT_DELAY_MS, g.GAUNTLET.ACT_DELAY_MS] and nx[0] >= 400, str(nx))


def cast_id_tests(L):
    """The engine's storyActionID on every event row (UsingSpell, CastedSpell, CastSpellFailed, AttackedBy, the hit and
    miss rows, with the hit's cast guid), the pending cast's own id from the character's first UsingSpell of its spell
    since the request, and the fight's turns per round."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local me, b = "c1", "b1"
      local t = 0
      local oldNow = Ext.Utils.MonotonicTime
      Ext.Utils.MonotonicTime = function() return t end
      G.t0 = 0
      local R = { r = 1, casts = {}, usings = {}, cast_fails = {} }
      G.rounds = { R }
      local rec = {}
      G.F = { char = me, enemies = { b }, pending = { who = me, spell = "Target_MainHandAttack", using0 = 0, rec = rec } }
      G.fighting, G.round = true, 1
      t = 100; G._on.using(b, "Target_MainHandAttack", "Target", "None", 49100)
      t = 200; G._on.using(me, "Target_MainHandAttack", "Target", "None", 49235)
      t = 300; G._on.using(me, "Target_MainHandAttack", "Target", "None", 49300)
      t = 400; G._on.cast(me, "Target_MainHandAttack", "Target", "None", 49235)
      t = 500; G._on.failed(me, "Target_HuntersMark", "Target", "None", 49240)
      t = 600; G._on.attacked(b, me, me, "Slashing", 7, "Attack", 49235)
      T_P, T_rec, T_R, T_dmg = G.F.pending, rec, R, G.dmg[1]
      T_hit = G.hitRow({ Hit = { StoryActionId = 49235, SpellCastGuid = "g-49235", EffectFlags = { "Hit" } } })
      T_dd = G.hitRow({ StoryActionId = 49236, Hit = { EffectFlags = { "Hit" } } })
      G.onMissEvent({ Target = { Uuid = { EntityUuid = me } }, Hit = { EffectFlags = { "Miss" }, StoryActionId = 49234,
        Inflicter = { Uuid = { EntityUuid = b } } } }, "hit_result")
      T_miss = G.hits[1]
      t = 700; G._on.turn_ended(me)
      t = 800; G._on.turn_started(b)
      G._on.turn_started("x9")
      T_turns, T_ended = R.turns, G.F.turnEndedAt
      Ext.Utils.MonotonicTime = oldNow
      G.fighting, G.F, G.rounds = false, nil, {}
    """)
    g = L.globals()
    R = g.T_R
    sids = [R.usings[i + 1].sid for i in range(3)]
    check("cast ids: UsingSpell, CastedSpell and CastSpellFailed rows keep the storyActionID",
          sids == [49100, 49235, 49300] and R.casts[1].sid == 49235 and R.cast_fails[1].sid == 49240, str(sids))
    check("cast ids: an AttackedBy row keeps its storyActionID", g.T_dmg.sid == 49235, str(g.T_dmg.sid))
    check("cast ids: a hit row keeps the hit's storyActionID and cast guid, else the damage event's id",
          g.T_hit.sid == 49235 and g.T_hit.cast_guid == "g-49235" and g.T_dd.sid == 49236,
          f"{g.T_hit.sid} {g.T_hit.cast_guid} {g.T_dd.sid}")
    check("cast ids: a miss row keeps the hit's storyActionID", g.T_miss is not None and g.T_miss.sid == 49234,
          str(g.T_miss and g.T_miss.sid))
    check("cast ids: the pending cast takes the id of the character's first UsingSpell of its spell (not the boss's)",
          g.T_P.sid == 49235 and g.T_rec.sid == 49235, f"{g.T_P.sid} {g.T_rec.sid}")
    turns = [(g.T_turns[i + 1].who, g.T_turns[i + 1].ev) for i in range(len(g.T_turns or {}))]
    check("turns: the fight's TurnStarted / TurnEnded kept per round, others left out; the character's end noted",
          turns == [("c1", "ended"), ("b1", "started")] and g.T_ended == 700, str(turns))


def engine_gate_tests(L):
    """The turn's first request waits for the engine to finish sheathing an earlier cast (a riposte), and a move ends on
    the engine's event for it, not on fixed timers."""
    L.execute(r"""
      local G = GAUNTLET
      local oldGet, oldNow = Ext.Entity.Get, Ext.Utils.MonotonicTime
      local me = {}
      Ext.Entity.Get = function(u) if u == "c1" then return me end end
      G.reset(); G.t0 = 0
      local R = { r = 4, done = {}, actions = {}, casts = {}, tm = {} }
      local F = { char = "c1" }
      me.ServerUnsheathSpellAnimationLifetime = { Spell = { Prototype = "Target_Riposte" } }
      T_sh1 = G.sheathHeld(F, R, 1000)
      T_sh2 = G.sheathHeld(F, R, 2500)
      me.ServerUnsheathSpellAnimationLifetime = nil
      T_sh3 = G.sheathHeld(F, R, 2600)
      T_sh_rec = R.tm.sheath and (R.tm.sheath.spell .. " " .. R.tm.sheath.ms) or "none"
      me.ServerUnsheathSpellAnimationLifetime = { Spell = { Prototype = "Target_Riposte" } }
      local R2 = { tm = {} }
      G.sheathHeld(F, R2, 0)
      T_sh_cap = G.sheathHeld(F, R2, G.READY_MAX_MS)
      T_sh_gave = R2.tm.sheath and R2.tm.sheath.gave_up == true
      -- the step loop: no round planned while the sheath is on
      local plan = G.planRound
      local planned = 0
      G.planRound = function() planned = planned + 1; return {} end
      G.rounds = { { r = 4, done = {}, actions = {}, casts = {}, tm = {} } }
      local Fq = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                   started = 1, state = "act", next = 0, turnStart = 0, progressT = 0 }
      G.F = Fq
      me.ServerUnsheathSpellAnimationLifetime = { Spell = { Prototype = "Target_Riposte" } }
      G.step(Fq, 100)
      T_sh_step1 = planned
      me.ServerUnsheathSpellAnimationLifetime = nil
      Fq.next = 0
      G.step(Fq, 200)
      T_sh_step2 = planned
      G.planRound, G.F = plan, nil
      me.ServerUnsheathSpellAnimationLifetime = nil
      -- the character's own last attack (a spell the harness asked for) holds nothing; recorded as such
      local Fa, Ra = { char = "c1", asked = { Target_MainHandAttack = true } }, { tm = {} }
      me.ServerUnsheathSpellAnimationLifetime = { Spell = { Prototype = "Target_MainHandAttack" } }
      T_sh_own = G.sheathHeld(Fa, Ra, 100)
      T_sh_own_rec = Ra.tm.sheath_own
      me.ServerUnsheathSpellAnimationLifetime = nil
      -- castRequest notes what the harness asked for
      local Fc = { char = "c1" }
      pcall(G.castRequest, Fc, "c1", "Target_MainHandAttack_2", "b1")
      T_sh_asked = Fc.asked and Fc.asked.Target_MainHandAttack == true
      -- a move: standing still 1.5 s is no end; the engine's event is, read MOVE_SETTLE_MS later
      local t = 0
      Ext.Utils.MonotonicTime = function() return t end
      local pos = { 3, 0, 0 }
      local gp, gr = Osi.GetPosition, Osi.GetActionResourceValuePersonal
      Osi.GetPosition = function() return pos[1], pos[2], pos[3] end
      Osi.GetActionResourceValuePersonal = function() return 9 end
      local function moving()
        return { char = "c1", moving = { spot = { x = 3, z = 0, len = 3 }, t0 = 0, p0 = { 0, 0, 0 },
          last = { 3, 0, 0 }, lastT = 0, mv0 = 9, rec = { move = {} } } }
      end
      local Fm = moving()
      T_mv_still = G.moveSettled(Fm, 1500)
      t = 1600; G._on.entity_event("c1", G.MOVE_EVENT)
      T_mv_soon = G.moveSettled(Fm, 1600 + G.MOVE_SETTLE_MS - 1)
      T_mv_done = G.moveSettled(Fm, 1600 + G.MOVE_SETTLE_MS)
      T_mv_res = Fm.moving.rec.move.result
      local Fo = moving()
      Fo.moving.t0 = 2000
      t = 2000; G._on.entity_event("c1", "SomethingElse")
      T_mv_other = G.moveSettled(Fo, 5000)
      pos = { 1, 0, 0 }
      local Fs = moving()
      Fs.moving.t0 = 6000
      t = 7000; G._on.move_cancelled("c1", G.MOVE_EVENT)
      T_mv_short = G.moveSettled(Fs, 7000 + G.MOVE_SETTLE_MS) and Fs.moving.rec.move.result
      local Ft = moving()
      Ft.moving.t0 = 8000
      T_mv_to = G.moveSettled(Ft, 8000 + G.MOVE_MAX_MS) and Ft.moving.rec.move.result
      -- a leave the engine ended short of its spot: done when out of the boss's reach and not Threatened, else failed;
      -- a hide spot needs the spot itself
      local where = { c1 = { 0, 0, 0 }, b1 = { 4, 0, 0 } }
      Osi.GetPosition = function(u) local p = where[u]; if p then return p[1], p[2], p[3] end end
      local flanked = 0
      local hs = Osi.HasActiveStatus
      Osi.HasActiveStatus = function(u, st) if st == "FLANKED" then return flanked end return 0 end
      local Fg = { char = "c1", enemies = { "b1" } }
      local function short(to)
        local R = { done = {}, actions = {} }
        local rec = { move = { result = "ended short" } }
        G.moveStep(Fg, { spell = "@move", move_to = to, done_key = "leave" }, R, rec)
        return rec.result .. "|" .. tostring(R.done.leave)
      end
      T_goal_out = short("@leave_spot")
      flanked = 1
      T_goal_flanked = short("@leave_spot")
      flanked = 0
      where.b1 = { 2, 0, 0 }
      T_goal_near = short("@leave_spot")
      -- the boss higher up: only the floor distance counts (3.2 m out: left; 2.9 m out, 1.5 m higher: still close)
      where.b1 = { 3.2, 0.55, 0 }
      T_goal_high = short("@leave_spot")
      where.b1 = { 2.9, 1.5, 0 }
      T_goal_high_close = short("@leave_spot")
      where.b1 = { 4, 0, 0 }
      T_goal_hide = short("@hide_spot")
      Osi.HasActiveStatus = hs
      Osi.GetPosition, Osi.GetActionResourceValuePersonal = gp, gr
      Ext.Entity.Get, Ext.Utils.MonotonicTime = oldGet, oldNow
    """)
    g = L.globals()
    check("move: a leave ended short is done when out of reach and not Threatened; in reach, Threatened or a hide spot fails",
          g.T_goal_out == "done|true" and g.T_goal_flanked.startswith("failed") and g.T_goal_near.startswith("failed")
          and g.T_goal_hide.startswith("failed"), f"{g.T_goal_out} {g.T_goal_flanked} {g.T_goal_near} {g.T_goal_hide}")
    check("move: a leave is judged along the floor by the game's 3 m close range, not in 3-D with slack",
          g.T_goal_high == "done|true" and g.T_goal_high_close.startswith("failed"),
          f"{g.T_goal_high} {g.T_goal_high_close}")
    check("sheath gate: the turn's first request waits while the riposte is still sheathed, then goes; the wait recorded",
          g.T_sh1 is True and g.T_sh2 is True and g.T_sh3 is False and g.T_sh_rec == "Target_Riposte 1600",
          f"{g.T_sh1} {g.T_sh2} {g.T_sh3} {g.T_sh_rec}")
    check("sheath gate: the step loop plans the round only once the sheath is gone",
          g.T_sh_step1 == 0 and g.T_sh_step2 == 1, f"{g.T_sh_step1} {g.T_sh_step2}")
    check("sheath gate: the character's own last attack holds nothing (recorded); the harness notes what it asked for",
          g.T_sh_own is False and g.T_sh_own_rec == "Target_MainHandAttack" and g.T_sh_asked is True,
          f"{g.T_sh_own} {g.T_sh_own_rec} {g.T_sh_asked}")
    check("sheath gate: a sheath that never ends is given up at READY_MAX_MS, recorded",
          g.T_sh_cap is False and g.T_sh_gave is True, f"{g.T_sh_cap} {g.T_sh_gave}")
    check("move: standing still is no end; the engine's move event is, read MOVE_SETTLE_MS later",
          g.T_mv_still is False and g.T_mv_soon is False and g.T_mv_done is True and g.T_mv_res == "there",
          f"{g.T_mv_still} {g.T_mv_soon} {g.T_mv_done} {g.T_mv_res}")
    check("move: another event name is no end; a cancelled move short of the spot ends 'ended short'; no event: timeout",
          g.T_mv_other is False and g.T_mv_short == "ended short" and g.T_mv_to == "timeout",
          f"{g.T_mv_other} {g.T_mv_short} {g.T_mv_to}")


def holder_idle_tests(L):
    """The turn watchdog ends the holder's turn (the boss's) only once the holder and the character have been idle for
    HOLDER_IDLE_MS and the holder is not casting, or at the TURN_WAIT_MS cap: a slow boss attack or a riposte is never
    cut short, which would bias the damage taken."""
    L.execute(r"""
      local G = GAUNTLET
      local t = 0
      local oldNow, oldGet = Ext.Utils.MonotonicTime, Ext.Entity.Get
      Ext.Utils.MonotonicTime = function() return t end
      local boss = { TurnBased = { IsActiveCombatTurn = true } }
      Ext.Entity.Get = function(u) if u == "e1" then return boss end end
      Osi.IsInCombat = function() return 1 end
      local function start()
        G.reset(); G.t0 = 0; G.round = 3
        G.rounds = { { r = 3, done = {}, actions = {}, casts = {} } }
        local F = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {},
                    rounds = 16, started = 1, state = "wait", deadline = G.TURN_WAIT_MS, waitAt = 0 }
        G.F, G.fighting = F, true
        return F
      end
      local function recs() return #(G.results.turn_recoveries or {}) end
      local F = start()
      t = 15000; G._on.using("e1", "Target_UnarmedAttack", "Target", "None", 1); G.step(F, t)
      t = 25000; G.step(F, t); T_active = recs()
      t = 15000 + G.HOLDER_IDLE_MS + 1; G.step(F, t); T_idle = recs()
      F = start()
      t = 10000; G._on.cast("c1", "Interrupt_Riposte", "Target", "None", 2); G.step(F, t)
      t = G.HOLDER_IDLE_MS + 1; G.step(F, t); T_riposte = recs()
      F = start()
      boss.SpellCastIsCasting = { Cast = 1 }
      t = 3 * G.HOLDER_IDLE_MS; G.step(F, t); T_casting = recs()
      t = G.TURN_WAIT_MS + 1; G.step(F, t); T_cap = recs()
      boss.SpellCastIsCasting = nil
      Ext.Utils.MonotonicTime, Ext.Entity.Get = oldNow, oldGet
      Osi.IsInCombat = nil
      G.fighting, G.F = false, nil
    """)
    g = L.globals()
    check("holder idle: a boss that acted 10 s ago keeps its turn (the old 20 s clock would have ended it)",
          g.T_active == 0, str(g.T_active))
    check("holder idle: idle for HOLDER_IDLE_MS since its last event, the holder's turn is recovered", g.T_idle == 1,
          str(g.T_idle))
    check("holder idle: the character's own cast (a riposte) counts as activity", g.T_riposte == 0, str(g.T_riposte))
    check("holder idle: a holder still casting is not recovered before the cap, at TURN_WAIT_MS it is",
          g.T_casting == 0 and g.T_cap == 1, f"{g.T_casting} {g.T_cap}")


def end_turn_tests(L):
    """Ending the own turn: the request is sent again only when the engine dropped it (RequestedEndTurn reads false and
    no TurnEnded came), never on the clock alone."""
    L.execute(r"""
      local G = GAUNTLET
      local t = 0
      local oldNow, oldGet = Ext.Utils.MonotonicTime, Ext.Entity.Get
      Ext.Utils.MonotonicTime = function() return t end
      local me
      Ext.Entity.Get = function(u) if u == "c2" then return me end end
      local asks = 0
      Osi.EndTurn = function() asks = asks + 1 end
      -- -> the requests sent: one on ending the turn, and any at the first check after engine() ran
      local function run(engine)
        me = { TurnBased = { IsActiveCombatTurn = true } }
        G.reset(); G.t0 = 0; G.round = 1
        local F = { char = "c2", enemies = {}, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                    started = 1, state = "ending", next = 0 }
        G.F, G.fighting = F, true
        asks, t = 0, 0
        G.step(F, 0)
        t = 100; engine()
        t = G.END_TURN_MS + 1; G.step(F, t)
        return asks
      end
      T_pending = run(function() end)
      T_dropped = run(function() me.TurnBased.RequestedEndTurn = false end)
      T_ended = run(function() me.TurnBased.RequestedEndTurn = false; G._on.turn_ended("c2") end)
      Ext.Utils.MonotonicTime, Ext.Entity.Get = oldNow, oldGet
      Osi.EndTurn = nil
      G.fighting, G.F = false, nil
    """)
    g = L.globals()
    check("end turn: a request the engine still holds is not sent again", g.T_pending == 1, str(g.T_pending))
    check("end turn: a dropped request (RequestedEndTurn false again) is sent again", g.T_dropped == 2,
          str(g.T_dropped))
    check("end turn: after the character's TurnEnded nothing is sent again", g.T_ended == 1, str(g.T_ended))


def speed_tests(L):
    """Fail fast and the time cuts: a start mismatch ends the run before round 1, a round that already voids the run
    ends it after that round; a combat that ended is reacted to at once (one recovery); the run ends as round 16's
    turn is released and damage taken counts per enemy turn fought (one before round 1 too); corpses cost no cleanup
    wait; the set goes on in one frame (rings one at a time) and is asked for until READY_MS while nothing is worn
    (just after a save load); buffs are put on again until they read back; the enemies are reset to 99% at each of
    our turns."""
    L.execute(r"""
      local G = GAUNTLET
      local wf, mt = Ext.Timer.WaitFor, Ext.Utils.MonotonicTime
      local function base(state)
        return { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                 started = 1, state = state, deadline = 1e12, next = 0 }
      end
      -- a round without a confirmed action ends the run as its turn ends
      G.reset(); G.round = 2
      local F = base("ending")
      G.F = F
      G.rounds = { { r = 1, done = { action = true }, actions = {}, casts = {} }, { r = 2, done = {}, actions = {}, casts = {} } }
      G.step(F, 0)
      T_idle, T_idle_why, T_idle_valid = F.state, G.results.ended, G.results.valid
      -- a refused cast ends it too; a good round goes on to end the turn
      G.reset(); G.round = 1
      F = base("ending"); G.F = F
      G.rounds = { { r = 1, done = { action = true }, cast_misses = 1, actions = {}, casts = {} } }
      G.step(F, 0)
      T_ref_why = G.results.ended
      G.reset(); G.round = 1
      F = base("ending"); G.F = F
      G.rounds = { { r = 1, done = { action = true }, actions = {}, casts = {} } }
      G.step(F, 0)
      T_good = F.state
      -- off: the round is fought to the end
      G.FAIL_FAST = false
      G.reset(); G.round = 2
      F = base("ending"); G.F = F
      G.rounds = { { r = 1, done = { action = true }, actions = {}, casts = {} }, { r = 2, done = {}, actions = {}, casts = {} } }
      G.step(F, 0)
      T_off = F.state
      G.FAIL_FAST = true
      -- the combat ended: reacted to after COMBAT_LOST_MS (not TURN_WAIT_MS), one recovery, then the run ends
      local inC, entered = 0, 0
      Osi.IsInCombat = function() return inC end
      Osi.EnterCombat = function() entered = entered + 1 end
      G.reset(); G.round = 3
      F = base("wait"); G.F = F
      F.inCombatAt = 0
      G.rounds = {}
      G.step(F, 100)
      T_lost0 = #(G.results.turn_recoveries or {})
      G.step(F, G.COMBAT_LOST_MS + 1)
      T_lost1, T_entered = #(G.results.turn_recoveries or {}), entered
      G.step(F, 2 * G.COMBAT_LOST_MS + 2)
      T_lost_state, T_lost_why, T_lost_valid = F.state, G.results.ended, G.results.valid
      -- in combat: only the turn watchdog
      inC = 1
      G.reset(); G.round = 3
      F = base("wait"); G.F = F
      F.inCombatAt = 0
      G.step(F, 10 * G.COMBAT_LOST_MS)
      T_inc = F.state .. ":" .. #(G.results.turn_recoveries or {})
      Osi.IsInCombat, Osi.EnterCombat = nil, nil
      -- round 16 released: the run ends without waiting for a 17th turn; taken per enemy turn fought
      G.reset(); G.round = 16
      F = base("ended"); G.F = F
      F.enemyFirst = true
      G.rounds = {}
      for r = 1, 16 do G.rounds[r] = { r = r, done = { action = true }, actions = {}, casts = {} } end
      G.dmg = { { r = 0, target = "c1", source = "e1", amount = 8 }, { r = 5, target = "c1", source = "e1", amount = 8 },
                { r = 16, target = "e1", source = "c1", amount = 40 } }
      G.step(F, 0)
      T_cut_state, T_cut_why = F.state, G.results.ended
      T_cut_sum = G.results.summary
      G.reset(); G.round = 16
      F = base("ended"); G.F = F
      G.rounds = {}
      for r = 1, 16 do G.rounds[r] = { r = r, done = { action = true }, actions = {}, casts = {} } end
      G.dmg = { { r = 5, target = "c1", source = "e1", amount = 9 } }
      G.step(F, 0)
      T_cut_sum2 = G.results.summary
      -- corpses: forgotten, no wait
      local waits = 0
      Ext.Timer.WaitFor = function(_, f) waits = waits + 1; f() end
      Osi.IsDead = function(u) return u == "corpse" and 1 or nil end
      G.spawned = { corpse = true, gone = true }
      G.clearLeftovers("c1", nil, function(rep) T_cl = rep end)
      T_cl_waits, T_cl_left = waits, G.spawned.corpse
      Osi.IsDead = nil
      G.spawned = nil
      -- the set in one frame: every item but the rings asked for before the first ring, the rings one after another
      local clock, calls = 0, {}
      Ext.Timer.WaitFor = function(ms, f) clock = clock + ms; calls[#calls + 1] = "wait"; f() end
      Ext.Utils.MonotonicTime = function() return clock end
      local made = 0
      Osi.CreateAt = function() made = made + 1; return "it" .. made end
      local worn = {}
      Osi.Equip = function(_, it) calls[#calls + 1] = it; worn[it] = true end
      Osi.IsEquipped = function(it) return worn[it] and 1 or 0 end
      G.results = { items = {} }
      G._equipAll("c1", { { slot = "Breast", template = "t", stats = "A" }, { slot = "Ring", template = "t", stats = "R1" },
        { slot = "Boots", template = "t", stats = "B" }, { slot = "Ring2", template = "t", stats = "R2" },
        { slot = "Helmet", template = "t", stats = "H" } }, 1, function() T_eq_done = true end)
      T_eq_calls = calls
      T_eq_items = G.results.items
      -- nothing goes on (a save just loaded): asked again until READY_MS, then given up
      local q, asks = {}, 0
      clock = 0
      Ext.Timer.WaitFor = function(ms, f) q[#q + 1] = { ms, f } end
      Osi.Equip = function() asks = asks + 1 end
      Osi.IsEquipped = function() return 0 end
      G.results = { items = {} }
      T_ready_done = false
      G._equipAll("c1", { { slot = "Boots", template = "t", stats = "B" } }, 1, function() T_ready_done = true end)
      local n = 0
      while #q > 0 and n < 2000 do n = n + 1; local x = table.remove(q, 1); clock = clock + x[1]; x[2]() end
      T_ready_clock, T_ready_asks = clock, asks
      T_ready_got = G.results.items[1] and G.results.items[1].got
      -- a buff the game ignored at first is put on again until it reads back
      local applied, has = 0, false
      Osi.ApplyStatus = function() applied = applied + 1; if applied >= 3 then has = true end end
      Osi.HasActiveStatus = function() return has and 1 or 0 end
      q = {}
      G.awaitStatuses("c1", { "BLESS" }, function(m) T_aw_missing = #m end)
      n = 0
      while #q > 0 and n < 2000 do n = n + 1; local x = table.remove(q, 1); x[2]() end
      T_aw_applied = applied
      Osi.ApplyStatus, Osi.HasActiveStatus = nil, nil
      Ext.Timer.WaitFor, Ext.Utils.MonotonicTime = wf, mt
      Osi.CreateAt, Osi.Equip, Osi.IsEquipped = nil, nil, nil
      -- the fight waits for the enemies' forced stats (one poll when they are there), not a fixed pause
      local ready = { Stats = { Abilities = { 0, 10, 10, 10, 10, 10, 10 }, ProficiencyBonus = 2 }, Resistances = { AC = 10 } }
      Ext.Entity.Get = function(u) if u == "e9" then return ready end end
      Osi.CreateAt = function() return "e9" end
      Osi.GetMaxHitpoints = function() return 5000 end
      local spawnF = base("prep"); spawnF.manual = true; spawnF.enemies = nil
      G.F = spawnF
      G.reset()
      G.enemyForced = nil
      local goF = G.goFight
      G.goFight = function() T_spawn_go = true end
      G.spawnAndFight(spawnF, { { 1, 0, 1 } }, { template = "t", ac = 10, save = 0, atk = 2, dmg = 1, dc = 10, hp = 5000 },
        {}, {})
      T_spawn_ms = G.results.spawn_ms
      ready.Stats.Abilities = { 0, 0, 0, 0, 0, 0, 0 }
      G.enemyForced = nil
      G.reset()
      G.spawnAndFight(spawnF, { { 1, 0, 1 } }, { template = "t", ac = 10, save = 0, atk = 2, dmg = 1, dc = 10, hp = 5000 },
        {}, {})
      T_spawn_ms2 = G.results.spawn_ms
      G.goFight = goF
      Ext.Entity.Get = function() return nil end
      Osi.CreateAt, Osi.GetMaxHitpoints = nil, nil
      -- max HP without temporary hit points (Health.MaxHp; else the Osiris answer less the temporary ones)
      local hpEnt = { Health = { MaxHp = 111, TemporaryHp = 8 } }
      Ext.Entity.Get = function(u) if u == "c1" then return hpEnt end end
      Osi.GetMaxHitpoints = function() return 119 end
      T_hp1 = G.maxHp("c1")
      hpEnt.Health = { TemporaryHp = 8 }
      T_hp2 = G.maxHp("c1")
      Ext.Entity.Get = function() return nil end
      Osi.GetMaxHitpoints = nil
      -- an elixir whose status lands 800 ms after the use is still recorded (and taken off in the next prep)
      local clk2 = 0
      Ext.Utils.MonotonicTime = function() return clk2 end
      Ext.Timer.WaitFor = function(ms, f) clk2 = clk2 + ms; f() end
      local usedAt
      Osi.CreateAt = function() return "elx" end
      Osi.Use = function() usedAt = clk2 end
      local stEnt = { StatusContainer = { Statuses = {} } }
      Ext.Entity.Get = function(u)
        if u == "c1" then
          stEnt.StatusContainer.Statuses = (usedAt and clk2 - usedAt >= 800) and { "ELIXIR_LATE" } or {}
          return stEnt
        end
      end
      G.results = { items = {} }
      G.usedStatuses = nil
      G._equipAll("c1", { { slot = "Elixir", template = "t", stats = "ELX", use = true } }, 1, function() end)
      T_elx = G.results.items[1].statuses
      T_elx_used = G.usedStatuses and G.usedStatuses.c1 and G.usedStatuses.c1.ELIXIR_LATE
      Ext.Entity.Get = function() return nil end
      Osi.Use = nil
      -- item creation refused at first (just after a load): asked again until the game makes the items
      local fails = 2
      Osi.CreateAt = function() if fails > 0 then fails = fails - 1; return nil end; return "made" end
      Osi.Equip = function() end
      Osi.IsEquipped = function() return 1 end
      G.results = { items = {} }
      G._equipAll("c1", { { slot = "Boots", template = "t", stats = "B" } }, 1, function() end)
      T_cr_got, T_cr_tries = G.results.items[1].got, G.results.create_tries
      Osi.CreateAt, Osi.Equip, Osi.IsEquipped = nil, nil, nil
      Ext.Timer.WaitFor, Ext.Utils.MonotonicTime = wf, mt
      -- the enemies at 99% as each of our turns starts
      local set = {}
      Osi.SetHitpointsPercentage = function(d, p) set[d] = p end
      G.reset(); G.round = 0
      F = base("wait"); G.F = F
      local notify, sent = G.notify, {}
      G.notify = function(m) sent[#sent + 1] = m end
      G._roundStart(F)
      T_hp99 = set.e1
      Osi.SetHitpointsPercentage = nil
      G.notify = notify
      -- each own turn: the camera onto the middle of the character and the boss
      T_follow = nil
      for _, m in ipairs(sent) do if m.kind == "camera_follow" then T_follow = m.char .. ">" .. tostring(m.also) end end
    """)
    g = L.globals()
    G = g.GAUNTLET
    check("camera: each own turn starts with the camera onto the character and the boss", g.T_follow == "c1>e1",
          str(g.T_follow))
    check("fail fast: a round without a confirmed action ends the run as its turn ends, invalid, with the round",
          g.T_idle == "done" and "round 2: no action confirmed" in str(g.T_idle_why) and g.T_idle_valid is False,
          f"{g.T_idle} {g.T_idle_why}")
    check("fail fast: a refused planned cast ends the run after its round", "refused" in str(g.T_ref_why),
          str(g.T_ref_why))
    check("fail fast: a round with its action confirmed goes on (the turn is ended)", g.T_good == "ended", str(g.T_good))
    check("fail fast: off -> the run goes on", g.T_off == "ended", str(g.T_off))
    check("watchdog: a combat that ended is entered again after COMBAT_LOST_MS, once, then the run ends",
          g.T_lost0 == 0 and g.T_lost1 == 1 and g.T_entered >= 1 and g.T_lost_state == "done" and
          "combat ended" in str(g.T_lost_why) and g.T_lost_valid is False,
          f"{g.T_lost0} {g.T_lost1} {g.T_lost_state} {g.T_lost_why}")
    check("watchdog: in combat the combat check does nothing", g.T_inc == "wait:0", str(g.T_inc))
    s_ = g.T_cut_sum
    check("last round: the run ends as round 16's turn is released, valid ending",
          g.T_cut_state == "done" and g.T_cut_why == "rounds done", f"{g.T_cut_state} {g.T_cut_why}")
    check("last round: damage taken per enemy turn fought (15 after our rounds + 1 before round 1)",
          s_ is not None and s_.enemy_turns == 16 and s_.taken_before_round1 == 8 and
          abs(s_.taken_per_round - 1.0) < 1e-9,
          str(s_ and (s_.enemy_turns, s_.taken_before_round1, s_.taken_per_round)))
    s2 = g.T_cut_sum2
    check("last round: no enemy turn before round 1 -> 15 enemy turns", s2.enemy_turns == 15 and
          abs(s2.taken_per_round - 9 / 15) < 1e-9, str((s2.enemy_turns, s2.taken_per_round)))
    check("cleanup: corpses and deleted creatures cost no wait and are forgotten",
          g.T_cl_waits == 0 and g.T_cl.removed == 0 and g.T_cl_left is None, f"{g.T_cl_waits} {g.T_cl_left}")
    calls = lst(g.T_eq_calls)
    eq = [c for c in calls if c != "wait"]
    one_frame = calls.index("it1") < calls.index("it5") and "wait" not in calls[calls.index("it1"):calls.index("it5")]
    rings_apart = calls.index("it2") < calls.index("it4") and "wait" in calls[calls.index("it2"):calls.index("it4")]
    check("equip: every item but the rings asked for in one frame, then the rings one after another",
          g.T_eq_done is True and sorted(eq[:3]) == ["it1", "it3", "it5"] and one_frame and rings_apart, str(calls))
    got = sorted((i.stats, i.got) for i in g.T_eq_items.values())
    check("equip: each item recorded as worn", got == [("A", "Breast"), ("B", "Boots"), ("H", "Helmet"),
                                                       ("R1", "Ring"), ("R2", "Ring2")], str(got))
    check("equip: nothing on (a save just loaded) -> asked for again until READY_MS, then given up",
          g.T_ready_done is True and g.T_ready_clock >= G.READY_MS and g.T_ready_asks >= 40 and g.T_ready_got is None,
          f"{g.T_ready_done} {g.T_ready_clock} {g.T_ready_asks}")
    check("buffs: put on again until they read back", g.T_aw_missing == 0 and g.T_aw_applied == 3,
          f"{g.T_aw_missing} {g.T_aw_applied}")
    check("boss: the enemies are reset to 99% (a hurt target) at each of our turns", g.T_hp99 == 99, str(g.T_hp99))
    check("sheet: max HP read without temporary hit points", g.T_hp1 == 111 and g.T_hp2 == 111, f"{g.T_hp1} {g.T_hp2}")
    check("elixir: a status that lands late is waited for and recorded for removal",
          g.T_elx is not None and lst(g.T_elx) == ["ELIXIR_LATE"] and g.T_elx_used is True, str(g.T_elx and lst(g.T_elx)))
    check("items: a creation the game refused is asked for again", g.T_cr_got == "Boots" and g.T_cr_tries == 3,
          f"{g.T_cr_got} {g.T_cr_tries}")
    check("spawn: the fight starts once the enemies' stats are forced, at most SPAWN_MS when they never are",
          g.T_spawn_go is True and g.T_spawn_ms == G.POLL_MS and g.T_spawn_ms2 == G.SPAWN_MS,
          f"{g.T_spawn_ms} {g.T_spawn_ms2}")


def plan_gap_lua_tests(L):
    """The plan gaps in the harness: an entry for a status (an extra action while hasted) only while that status is on
    as the turn starts; an entry needed only after a critical hit (GWM's bonus attack) is skipped without counting as
    a failed action when its status is not there; an item action replaces planned actions only when it is worth more
    (also the surge's attacks); a yielding core bonus action (the off-hand attack) gives way to a bonus item spell
    worth more, and only to one."""
    L.execute(r"""
      local G = GAUNTLET
      local has = {}
      Ext.Entity.Get = function(u) if u == "c1" then
        local l = {}
        for k in pairs(has) do l[#l + 1] = k end
        return { StatusContainer = { Statuses = l } } end end
      local yes = function() return true end
      local plan = { rounds = { { { spell = "A1", group = "action" },
        { spell = "A2", group = "action", if_status = "HASTE_X", done_key = "extra" } } }, item_actions = {} }
      local F = { char = "c1", cooldown = {}, afford = yes, plan = plan, S = {} }
      local R = { r = 1, done = {} }
      T_q0 = G.planRound(F, R)
      has.HASTE_X = true
      local R2 = { r = 1, done = {} }
      T_q1 = G.planRound(F, R2)
      -- GWM's bonus attack: not needed without its status, not a failed action
      local R3 = { r = 1, done = {}, actions = {}, casts = {} }
      Osi.HasActiveStatus = function() return 0 end
      G._doAction(F, { spell = "Target_GWM", group = "bonus", when_status = "GWM_BA", optional = true }, R3)
      T_gwm = R3.actions[1]
      G.rounds, G.dmg = { R3 }, {}
      T_gsum = G._summarize({ char = "c1", enemies = {} })
      Osi.HasActiveStatus = nil
      Ext.Entity.Get = function() return nil end
      -- the item rule's value check
      local function IR(items, list, av)
        local f = { cooldown = {}, afford = yes, plan = { item_actions = items, action_value = av } }
        local r = { done = {} }
        local out = G._itemRule(f, list, r)
        local names = {}
        for _, a in ipairs(out) do names[#names + 1] = a.spell end
        return table.concat(names, ","), r.item_rule[1].result
      end
      local caster = { { spell = "Zone_LB", group = "action", value = 46 } }
      T_v1, T_v1r = IR({ { spell = "Target_Topple", group = "action", per = "short", value = 2.5 } }, caster)
      T_v2 = IR({ { spell = "Projectile_Chain", group = "action", per = "short", value = 80 } }, caster)
      local surge = { { spell = "Atk", group = "action", value = 30 }, { spell = "Shout_ActionSurge", group = "free" },
        { spell = "Atk", group = "free", requires = "surge" } }
      T_v3 = IR({ { spell = "Shout_Haste", group = "action", per = "long", value = 390 } }, surge, 100)
      T_v4, T_v4r = IR({ { spell = "Shout_Weak", group = "action", per = "long", value = 50 } }, surge, 100)
      local bon = { { spell = "Atk", group = "action" }, { spell = "Off", group = "bonus", yield_bonus = true, value = 12 } }
      T_y1, T_y1r = IR({ { spell = "Opening", group = "bonus", per = "short", value = 2.5 } }, bon)
      T_y2 = IR({ { spell = "Strong", group = "bonus", per = "short", value = 20 } }, bon)
      local hard = { { spell = "Atk", group = "action" }, { spell = "HM", group = "bonus" } }
      T_y3 = IR({ { spell = "Strong", group = "bonus", per = "short", value = 20 } }, hard)
    """)
    g = L.globals()
    q0 = [g.T_q0[i + 1].spell for i in range(len(g.T_q0))]
    q1 = [g.T_q1[i + 1].spell for i in range(len(g.T_q1))]
    check("plan gaps: the extra action only while its status is on as the turn starts", q0 == ["A1"] and
          q1 == ["A1", "A2"], f"{q0} {q1}")
    check("plan gaps: GWM's bonus attack without its status is not needed and not a failed action",
          "not needed" in str(g.T_gwm.result) and g.T_gsum.actions_not_done == 0,
          f"{g.T_gwm.result} {g.T_gsum.actions_not_done}")
    check("item rule: an item action worth less than the planned action is not used", g.T_v1 == "Zone_LB" and
          "worth less" in str(g.T_v1r), f"{g.T_v1} {g.T_v1r}")
    check("item rule: an item action worth more replaces it", g.T_v2.startswith("Projectile_Chain"), str(g.T_v2))
    check("item rule: in a surge round the surge's attacks are what an item action is weighed against",
          "Shout_Haste" in g.T_v3 and "Shout_Weak" not in g.T_v4 and "worth less" in str(g.T_v4r),
          f"{g.T_v3} | {g.T_v4} {g.T_v4r}")
    check("item rule: a yielding bonus action gives way only to a bonus item spell worth more",
          g.T_y1 == "Atk,Off" and "worth less" in str(g.T_y1r) and g.T_y2 == "Atk,Strong", f"{g.T_y1} {g.T_y2}")
    check("item rule: a core bonus action that does not yield keeps the bonus action", g.T_y3 == "Atk,HM", str(g.T_y3))
    evade_lua_tests(L)


def phase_reaction_tests(L):
    """Reactions by whose turn it is (plan.reactions_enemy_turn): the enemies' turn's answers applied as the character
    asks to end its turn, the own turn's (plan.reactions) as its turn starts, read back; only interrupts the character
    has; nothing without such answers or in a manual run; each reaction of the character logged with the answer in
    force, and one that fired against "never" (or a phase whose answers did not stick) makes the run invalid."""
    L.execute(r"""
      local store = { Interrupt_SneakAttack = { "Enabled" }, Interrupt_SneakAttack_Critical = { "Enabled" } }
      local prefs
      prefs = setmetatable({}, {
        __index = function(_, k) local f = store[k]; return f and ("InterruptInteractionTypes(" .. table.concat(f, ",") .. ")") end,
        __newindex = function(_, k, v) store[k] = v end,
        __pairs = function() local k; return function() k = next(store, k); if k then return k, prefs[k] end end end })
      local ent = { InterruptPreferences = { Preferences = prefs }, Replicate = function() end }
      local eg = Ext.Entity.Get
      Ext.Entity.Get = function(u) if u == "c1" then return ent end end
      local G = GAUNTLET
      local plan = { reactions = { Interrupt_SneakAttack = "auto", Interrupt_SneakAttack_Critical = "auto" },
        reactions_enemy_turn = { Interrupt_SneakAttack = "never", Interrupt_SneakAttack_Critical = "auto",
                                 Interrupt_NotMine = "auto" } }
      local F = { char = "c1", plan = plan }
      T_enemy = G.reactionsPhase(F, "enemy")
      T_enemy_store = { store.Interrupt_SneakAttack and table.concat(store.Interrupt_SneakAttack, ","),
                        store.Interrupt_SneakAttack_Critical and table.concat(store.Interrupt_SneakAttack_Critical, ","),
                        store.Interrupt_NotMine == nil }
      -- a reaction in the enemies' turn is logged with the answer in force
      local gf, gfight, grounds = G.F, G.fighting, G.rounds
      G.F, G.fighting = F, true
      local R = { r = 3, reactions_seen = {} }
      G.rounds = { R }
      G._onReaction("c1", "Interrupt_SneakAttack")
      G._onReaction("b1", "Interrupt_AttackOfOpportunity")
      T_row, T_other = R.reactions_seen[1], R.reactions_seen[2]
      T_own = G.reactionsPhase(F, "own")
      T_own_store = table.concat(store.Interrupt_SneakAttack, ",")
      G._onReaction("c1", "Interrupt_SneakAttack")
      T_row2 = R.reactions_seen[3]
      T_none = G.reactionsPhase({ char = "c1", plan = { reactions = plan.reactions } }, "enemy")
      T_manual = G.reactionsPhase({ char = "c1", plan = plan, manual = true }, "enemy")
      T_j_bad = G.judge({ { r = 3, done = { action = true }, actions = {}, reactions_seen = { T_row } } }, "rounds done", {},
        { me = "c1" })
      T_j_ok = G.judge({ { r = 3, done = { action = true }, actions = {}, reactions_seen = { T_row2, T_other } } },
        "rounds done", {}, { me = "c1" })
      T_j_set = G.judge({ { r = 2, done = { action = true }, actions = {}, reaction_phases = { { phase = "enemy",
        verified = false } } } }, "rounds done", {}, { me = "c1" })
      -- answers that do not stick
      ent.InterruptPreferences.Preferences = setmetatable({}, { __newindex = function() end, __pairs = prefs and
        getmetatable(prefs).__pairs })
      T_unset = G.reactionsPhase(F, "enemy")
      G.F, G.fighting, G.rounds = gf, gfight, grounds
      Ext.Entity.Get = eg
    """)
    g = L.globals()
    check("phase reactions: the enemies' turn's answers applied and read back (Sneak Attack off, its critical one on)",
          g.T_enemy is not None and g.T_enemy.verified is True and g.T_enemy.phase == "enemy" and
          lst(g.T_enemy_store) == ["", "Enabled", True], str(g.T_enemy_store and lst(g.T_enemy_store)))
    check("phase reactions: an interrupt the character does not have is left alone",
          g.T_enemy.policy["Interrupt_NotMine"] is None)
    check("phase reactions: the own turn's answers back as its turn starts", g.T_own.phase == "own" and
          g.T_own_store == "Enabled" and g.T_own.policy["Interrupt_SneakAttack"] == "auto", str(g.T_own_store))
    check("phase reactions: none without enemy-turn answers or in a manual run", g.T_none is None and g.T_manual is None)
    check("phase reactions: the character's reaction logged with the phase and its answer; another creature's without",
          g.T_row.phase == "enemy" and g.T_row.policy == "never" and g.T_other.phase is None and
          g.T_row2.policy == "auto", f"{g.T_row.phase} {g.T_row.policy} {g.T_other.phase}")
    jb = lst(g.T_j_bad.causes)
    check("phase reactions: a reaction against the turn's answer makes the run invalid, one along it does not",
          g.T_j_bad.valid is False and any("against the plan's answer" in c for c in jb) and g.T_j_ok.valid is True,
          str(jb) + str(lst(g.T_j_ok.causes)))
    check("phase reactions: answers that did not stick are reported and make the run invalid",
          g.T_unset.verified is False and g.T_j_set.valid is False and
          any("not set" in c for c in lst(g.T_j_set.causes)), str(lst(g.T_j_set.causes)))


def step_validity_tests(L):
    """A planned step that is not carried out makes the run invalid (and ends a fail-fast run after its round): the
    evade move with no spot, a step skipped because the step it needs failed; an optional step, a fallback to the
    step's alt and a step not needed (the boss out of reach, and the move that needs that Disengage) do not."""
    L.execute(r"""
      local G = GAUNTLET
      local function R(actions) return { r = 2, done = { action = true }, actions = actions } end
      T_move = G.judge({ R({ { spell = "@move", why = "evade: move", result = "failed: no spot for @leave_spot in the arena",
        optional = false } }) }, "rounds done", {}, { me = "c1" })
      T_skip = G.judge({ R({ { spell = "@move", why = "evade: move", result = "skipped: no disengage this round" } }) },
        "rounds done", {}, { me = "c1" })
      T_fine = G.judge({ R({ { spell = "Projectile_OffhandAttack", result = "no resource BonusActionPoint", optional = true },
        { spell = "Projectile_MenacingAttack", result = "cannot afford -> alt" },
        { spell = "Shout_Disengage_CunningAction", result = "not needed: the boss is not in reach", optional = true },
        { spell = "Projectile_MainHandAttack", result = "done" } }) }, "rounds done", {}, { me = "c1" })
      T_player = G.judge({ R({ { spell = "X", result = "failed" } }) }, "rounds done", {}, { me = "c1", player = true })
      local ff = G.FAIL_FAST
      G.FAIL_FAST = true
      T_fault = G.roundFault({ S = {} }, R({ { spell = "@move", why = "evade: move", result = "failed: move stuck",
        optional = false } }))
      G.FAIL_FAST = ff
      -- a move whose Disengage was not needed is not needed either
      local P = { c1 = { 0, 0, 0 }, b1 = { 10, 0, 0 } }
      local gp, dead = Osi.GetPosition, Osi.IsDead
      Osi.GetPosition = function(u) local p = P[u]; if p then return p[1], p[2], p[3] end end
      Osi.IsDead = function() return 0 end
      local F = { char = "c1", enemies = { "b1" }, cooldown = {}, afford = function() return true end, plan = {}, S = {}, A = {} }
      local R1 = { r = 1, done = {}, actions = {}, casts = {} }
      G._doAction(F, { spell = "Shout_Disengage_CunningAction", group = "bonus", target = "@self", when_adjacent = true,
        done_key = "disengage" }, R1)
      G._doAction(F, { spell = "@move", group = "free", target = "@leave_spot", move_to = "@leave_spot",
        requires = "disengage", done_key = "left" }, R1)
      T_nn = R1.actions[2]
      R1.done.action = true
      T_j_nn = G.judge({ R1 }, "rounds done", {}, { me = "c1" })
      Osi.GetPosition, Osi.IsDead = gp, dead
    """)
    g = L.globals()
    cm = lst(g.T_move.causes)
    check("validity: the evade move with no spot makes the run invalid, with the round, the step and why",
          g.T_move.valid is False and any("round 2: planned step not done: @move (evade: move): failed: no spot" in c
                                          for c in cm), str(cm))
    check("validity: a required step skipped because its prerequisite failed makes the run invalid",
          g.T_skip.valid is False, str(lst(g.T_skip.causes)))
    check("validity: an optional step, a fallback to its alt and a step not needed leave the run valid",
          g.T_fine.valid is True, str(lst(g.T_fine.causes)))
    check("validity: a person's turn (player) is not judged by planned steps", g.T_player.valid is True,
          str(lst(g.T_player.causes)))
    check("validity: fail fast ends the run after a round with a planned step not done",
          "planned step not done" in str(g.T_fault), str(g.T_fault))
    check("validity: the move after a Disengage that was not needed is not needed either (optional, no cause)",
          g.T_nn.optional is True and "not needed" in str(g.T_nn.result) and g.T_j_nn.valid is True,
          f"{g.T_nn.result} {lst(g.T_j_nn.causes)}")


def evade_lua_tests(L):
    """The evade tactic's steps in the harness: a step for an adjacent boss is not needed (and no failed action) when
    the boss stands out of reach; a move to "@hide_spot" goes to the arena's spot nearest the character outside the
    boss's reach, through the engine's move; with no spot surveyed it fails and counts as an action not done; after
    the move it is done and opens the steps that need it."""
    L.execute(r"""
      local G = GAUNTLET
      local P = { c1 = { 0, 0, 0 }, b1 = { 10, 0, 0 } }
      local gp, dead, mtp = Osi.GetPosition, Osi.IsDead, Osi.CharacterMoveToPosition
      Osi.GetPosition = function(u) local p = P[u]; if p then return p[1], p[2], p[3] end end
      Osi.IsDead = function() return 0 end
      local moved = {}
      Osi.CharacterMoveToPosition = function(u, x, y, z) moved[#moved + 1] = { x, y, z } end
      local F = { char = "c1", enemies = { "b1" }, cooldown = {}, afford = function() return true end, plan = {}, S = {},
        A = { hide_spots = { { 20, 0, 5 }, { 1, 0, 0 }, { -6, 0, 0 } } } }
      local R = { r = 1, done = {}, actions = {}, casts = {} }
      G._doAction(F, { spell = "Shout_Disengage_CunningAction", group = "bonus", target = "@self", when_adjacent = true,
        done_key = "disengage" }, R)
      T_far = R.actions[1]
      P.b1 = { 2, 0, 0 }
      local mv = { spell = "@move", group = "free", target = "@hide_spot", move_to = "@hide_spot", requires = "disengage",
        done_key = "hide_move", optional = true }
      R.done.disengage = true
      G._doAction(F, mv, R)
      T_moved, T_moving = moved[1], F.moving ~= nil
      local M = F.moving
      F.moving = nil
      M.rec.move.result = "there"
      G._doAction(F, M.a, M.R, M.rec)
      T_rec, T_done = M.rec, R.done.hide_move
      local R2 = { r = 2, done = { disengage = true }, actions = {}, casts = {} }
      F.A = { hide_spots = {} }
      G._doAction(F, mv, R2)
      T_none = R2.actions[1]
      G.rounds, G.dmg = { R2 }, {}
      T_sum = G._summarize({ char = "c1", enemies = {} })
      local R3 = { r = 3, done = {}, actions = {}, casts = {} }
      G._doAction(F, mv, R3)
      T_skip = R3.actions[1]
      Osi.GetPosition, Osi.IsDead, Osi.CharacterMoveToPosition = gp, dead, mtp
    """)
    g = L.globals()
    check("evade: Disengage not needed while the boss is out of reach, not a failed action",
          "not needed" in str(g.T_far.result) and g.T_far.optional, str(g.T_far.result))
    check("evade: the move goes to the hide spot nearest the character outside the boss's reach",
          g.T_moved is not None and g.T_moved[1] == -6 and g.T_moving, str(g.T_moved and lst(g.T_moved)))
    check("evade: the move done opens the next step", g.T_rec.result == "done" and g.T_done, str(g.T_rec.result))
    check("evade: no hide spot surveyed: the move fails and counts as an action not done",
          str(g.T_none.result).startswith("failed: no spot") and g.T_sum.actions_not_done == 1,
          f"{g.T_none.result} {g.T_sum.actions_not_done}")
    check("evade: the move only after Disengage", "skipped" in str(g.T_skip.result), str(g.T_skip.result))
    L.execute(r"""
      local G = GAUNTLET
      local P = { c1 = { 0, 0, 0 }, b1 = { 2, 0, 0 } }
      local gp, dead, route, mv = Osi.GetPosition, Osi.IsDead, G.route, Osi.GetActionResourceValuePersonal
      Osi.GetActionResourceValuePersonal = function() return 9 end
      Osi.GetPosition = function(u) local p = P[u]; if p then return p[1], p[2], p[3] end end
      Osi.IsDead = function() return 0 end
      G.route = function(_, x, y, z) return { { x, y, z } } end
      local F = { char = "c1", enemies = { "b1" }, A = {} }
      T_leave = G.moveTarget(F, "@leave_spot")
      -- the game's path stops short of the goal (in game 1.1 to 2.3 m): its end is the spot
      G.route = function(_, x, y, z) return { { x, y, z + 1.3 } } end
      T_short = G.moveTarget(F, "@leave_spot")
      G.route = function() return nil end
      T_noroute = G.moveTarget(F, "@leave_spot")
      F.A = { leave_spots = { { 3, 0, 0 }, { 8, 0, 0 } } }
      T_surveyed = G.moveTarget(F, "@leave_spot")
      -- with the arena's centre known: the clear spot nearest the centre within the turn's movement (9 m), not the
      -- nearest one; a spot nearer the centre but out of the movement's reach is not taken
      F.A = { center = { -10, 0, 0 }, leave_spots = { { 2, 0, 4 }, { -6, 0, 0 }, { -12, 0, 0 } } }
      T_centre = G.moveTarget(F, "@leave_spot")
      -- far: history, not place: a boss back on its start spot after leaving it is not far again
      local Fs = { boss_start = { 0, 0, 0 } }
      P.b1 = { 0, 0, 0 }
      T_far1 = G.bossAtStart(Fs, "b1")
      P.b1 = { 5, 0, 0 }
      T_far2 = G.bossAtStart(Fs, "b1")
      P.b1 = { 0, 0, 0 }
      T_far3 = G.bossAtStart(Fs, "b1")
      -- a new fight with the same table: its start spot recorded again, far again
      Fs.char, Fs.enemies = "c1", { "b1" }
      G.bossStartSpot(Fs)
      T_far4 = G.bossAtStart(Fs, "b1")
      P.b1 = { 2, 0, 0 }
      Osi.GetPosition, Osi.IsDead, G.route, Osi.GetActionResourceValuePersonal = gp, dead, route, mv
    """)
    lv = g.T_leave and lst(g.T_leave)
    check("evade: with no surveyed spot the harness finds one 4.5 m from the boss by path, nearest the character",
          lv is not None and abs(((lv[0] - 2) ** 2 + lv[2] ** 2) ** 0.5 - 4.5) < 1e-6 and lv[0] < 0, str(lv))
    sh = g.T_short and lst(g.T_short)
    check("evade: a path that ends 1.3 m short of the ring still gives a spot (its end), out of the boss's reach",
          sh is not None and ((sh[0] - 2) ** 2 + sh[2] ** 2) ** 0.5 >= 3.8, str(sh))
    check("evade: no path, no spot", g.T_noroute is None, str(g.T_noroute))
    check("evade: a surveyed leave spot too close to the boss is not taken",
          g.T_surveyed is not None and g.T_surveyed[1] == 8, str(g.T_surveyed and lst(g.T_surveyed)))
    check("leave: the clear spot nearest the arena's centre within the turn's movement, not the nearest one",
          g.T_centre is not None and g.T_centre[1] == -6, str(g.T_centre and lst(g.T_centre)))
    check("far: a boss back on its start spot after leaving it is not far again",
          g.T_far1 is True and g.T_far2 is False and g.T_far3 is False and g.T_far4 is True,
          f"{g.T_far1} {g.T_far2} {g.T_far3} {g.T_far4}")
    dual_cost_tests(L)


def dual_cost_tests(L):
    """A main-hand attack whose off-hand half fired (a damage row of cause Offhand) pays that half's bonus action
    (DualWieldingUseCosts), as the game does for a player; with no such row within OFFHAND_MS nothing more is paid.
    The old path's request edit takes off IgnoreSpellRolls only. Hide is refused while the character is Threatened."""
    L.execute(r"""
      local G = GAUNTLET
      local stats = Ext.Stats.Get
      Ext.Stats.Get = function(s) if s == "Main" then return { UseCosts = "ActionPoint:1",
        DualWieldingUseCosts = "BonusActionPoint:1" } end end
      T_dc = G.dualCosts("Main")
      T_dc0 = G.dualCosts("Other")
      local P = { who = "c1", dmg0 = 0 }
      T_fired = G.offhandFired(P, { { source = "c1", cause = "Attack" }, { source = "c1", cause = "Offhand" } })
      T_notfired = G.offhandFired(P, { { source = "c1", cause = "Attack" }, { source = "e1", cause = "Offhand" } })
      -- settle: a confirmed main-hand cast waits for its off-hand row up to OFFHAND_MS, then pays (or not)
      local function pend(rows)
        local rec = { result = "pending" }
        local F = { char = "c1", cooldown = {}, plan = {}, S = {} }
        F.pending = { a = { spell = "Main", group = "action" }, rec = rec, costs = {}, before = {}, res = {}, who = "c1",
          spell = "Main", target = "b1", casts0 = 0, dmg0 = 0, t0 = 0, dual = G.dualCosts("Main"), dualBefore = {} }
        local R = { r = 1, done = {}, casts = { { who = "c1", spell = "Main" } } }
        G.dmg = rows
        return F, R, rec
      end
      local F1, R1, rec1 = pend({ { source = "c1", target = "b1", cause = "Attack", amount = 5 } })
      T_wait = G.settle(F1, R1, 100)
      G.dmg[#G.dmg + 1] = { source = "c1", target = "b1", cause = "Offhand", amount = 4 }
      T_paid = G.settle(F1, R1, 500) and rec1.offhand_half
      local F2, R2, rec2 = pend({ { source = "c1", target = "b1", cause = "Attack", amount = 5 } })
      G.settle(F2, R2, 100)
      T_none = G.settle(F2, R2, 100 + G.OFFHAND_MS + 1) and rec2.offhand_half
      G.dmg = {}
      -- the toggle per attack: on only with a bonus action free beyond the queue's later planned ones
      local ba, eget = 2, Ext.Entity.Get
      local gr = Osi.GetActionResourceValuePersonal
      Osi.GetActionResourceValuePersonal = function(_, k) if k == "BonusActionPoint" then return ba end return 1 end
      local E = { DualWielding = {}, Replicate = function() end }
      Ext.Entity.Get = function() return E end
      local atk = { spell = "Projectile_MainHandAttack", group = "action" }
      local Fq = { char = "c1", qi = 1, queue = { atk, { spell = "Target_HuntersMark", group = "bonus" },
        { spell = "Projectile_OffhandAttack", group = "bonus", optional = true } } }
      T_t2 = G.dualToggle(Fq, atk)
      T_t2e = E.DualWielding.RangedToggledOn
      ba = 1
      T_t1 = G.dualToggle(Fq, atk)
      T_t1e = E.DualWielding.RangedToggledOn
      ba = 2
      T_tno = G.dualToggle(Fq, { spell = "Target_MainHandAttack", dual = false })
      T_tnoe = E.DualWielding.MeleeToggledOn
      local stats2 = Ext.Stats.Get
      Ext.Stats.Get = function(sp) if sp == "Projectile_MainHandAttack" then
        return { UseCosts = "ActionPoint:1", DualWieldingUseCosts = "BonusActionPoint:1" } end end
      local Rd = { r = 1, done = {}, actions = {}, casts = {} }
      local Fd = { char = "c1", enemies = { "b1" }, cooldown = {}, afford = function() return true end, plan = {}, S = {},
        qi = 1, queue = { atk } }
      G._doAction(Fd, atk, Rd)
      T_dorec = Rd.actions[1].dual_toggle
      Fd.pending = nil
      Ext.Stats.Get = stats2
      Ext.Entity.Get, Osi.GetActionResourceValuePersonal = eget, gr
      Ext.Stats.Get = stats
      local req = { { Caster = { Uuid = { EntityUuid = "c1" } }, Spell = { Prototype = "S" },
                      CastOptions = { "IgnoreSpellRolls", "IgnoreCastChecks", "IgnoreTargetChecks", "Other" } },
                    { Caster = { Uuid = { EntityUuid = "c2" } }, Spell = { Prototype = "S" },
                      CastOptions = { "IgnoreSpellRolls", "IgnoreCastChecks" } } }
      G.rollRequests(req, { c1 = { edits = {}, player = true }, c2 = { edits = {} } })
      T_opts1, T_opts2 = req[1].CastOptions, req[2].CastOptions
      local has = Osi.HasActiveStatus
      Osi.HasActiveStatus = function(_, s) return s == "FLANKED" and 1 or 0 end
      local R = { r = 1, done = {}, actions = {}, casts = {} }
      G._doAction({ char = "c1", enemies = {}, cooldown = {}, afford = function() return true end, plan = {}, S = {} },
        { spell = "Shout_Hide_BonusAction", group = "bonus", target = "@self" }, R)
      T_hide = R.actions[1]
      Osi.HasActiveStatus = has
    """)
    g = L.globals()
    check("dual wield: the off-hand half's cost read from DualWieldingUseCosts",
          g.T_dc is not None and g.T_dc[1].kind == "BonusActionPoint" and g.T_dc0 is None)
    check("dual wield: paid only when the character's Offhand row came", g.T_fired and not g.T_notfired)
    check("dual wield: a confirmed main-hand cast waits for its off-hand row, then pays its bonus action",
          g.T_wait is False and g.T_paid == "paid", f"{g.T_wait} {g.T_paid}")
    check("dual wield: no off-hand row within OFFHAND_MS: nothing more paid", g.T_none == "none", str(g.T_none))
    check("dual wield: toggled on with a bonus action free beyond the turn's planned Hunter's Mark",
          g.T_t2 is True and g.T_t2e is True, f"{g.T_t2} {g.T_t2e}")
    check("dual wield: toggled off when the planned bonus action needs the last one (the attack is not refused)",
          g.T_t1 is False and g.T_t1e is False, f"{g.T_t1} {g.T_t1e}")
    check("dual wield: a main-hand attack sets the toggle before it is cast", g.T_dorec is True, str(g.T_dorec))
    check("dual wield: off when the plan says so, on the melee toggle for a melee attack",
          g.T_tno is False and g.T_tnoe is False, f"{g.T_tno} {g.T_tnoe}")
    o1, o2 = sorted(lst(g.T_opts1)), sorted(lst(g.T_opts2))
    check("old path: the request edit takes off IgnoreSpellRolls only",
          o1 == ["IgnoreCastChecks", "IgnoreTargetChecks", "Other"] and o2 == ["IgnoreCastChecks"], f"{o1} {o2}")
    check("evade: Hide refused while Threatened", "Threatened" in str(g.T_hide.result), str(g.T_hide.result))
    player_cast_tests(L)


def player_cast_tests(L):
    """The player path (the default): every scripted cast is queued as a player's click request (FromClient, no
    Ignore* option) with the TargetingType of the spell's own SpellType (never guessed: no SpellType, no cast) and the
    spell's spell-book id; the old path (player_cast = false) keeps Osi.UseSpell. The engine's CastSpellFailed that
    precedes every accepted request is not a refusal; a real one is recorded with its reason (resources, range, line of
    sight), never asked for again, and range or sight make the run invalid. After each cast the resources spent match
    its costs (the off-hand half's bonus action when it fired), else the run is invalid. A toggled attack with no bonus
    action left goes untoggled, and the toggle is put back after the attack."""
    L.execute(r"""
      local G = GAUNTLET
      local stats, eget, gpos, gres = Ext.Stats.Get, Ext.Entity.Get, Osi.GetPosition, Osi.GetActionResourceValuePersonal
      local canSee, useSpell, sys = Osi.CanSee, Osi.UseSpell, Ext.System.ServerCastRequest
      local DATA = {
        Projectile_MainHandAttack = { SpellType = "Projectile", UseCosts = "ActionPoint:1",
          DualWieldingUseCosts = "BonusActionPoint:1", TargetRadius = "18" },
        Target_MainHandAttack = { SpellType = "Target", UseCosts = "ActionPoint:1",
          DualWieldingUseCosts = "BonusActionPoint:1", TargetRadius = "1.5" },
        Shout_Dash = { SpellType = "Shout", UseCosts = "BonusActionPoint:1" },
        Zone_Thing = { SpellType = "Zone", UseCosts = "ActionPoint:1" },
        Target_NoType = { UseCosts = "ActionPoint:1" },
        Target_Odd = { SpellType = "Sideways", UseCosts = "ActionPoint:1" },
        Target_MenacingAttack = { SpellType = "Target", UseCosts = "ActionPoint:1", HitCosts = "SuperiorityDie:1",
          TargetRadius = "1.5" },
      }
      Ext.Stats.Get = function(s) return DATA[s] end
      local book = {}
      for _, s in ipairs({ "Projectile_MainHandAttack", "Target_MainHandAttack", "Shout_Dash", "Zone_Thing",
        "Target_NoType", "Target_Odd", "Target_Upcast" }) do
        book[#book + 1] = { Id = { Prototype = s, OriginatorPrototype = s, Source = "src-" .. s, SourceType = "WeaponSpell",
          ProgressionSource = "prog" } }
      end
      local E = { c1 = { SpellBook = { Spells = book }, DualWielding = { RangedToggledOn = true, MeleeToggledOn = false },
        Replicate = function() end }, b1 = { tag = "boss" } }
      Ext.Entity.Get = function(u) return E[u] end
      local POS = { c1 = { 0, 0, 0 }, b1 = { 10, 0, 0 } }
      Osi.GetPosition = function(u) local p = POS[u]; if p then return p[1], p[2], p[3] end end
      local RES = { ActionPoint = 1, BonusActionPoint = 2 }
      Osi.GetActionResourceValuePersonal = function(_, k) return RES[k] or 0 end
      Osi.CanSee = function() return 1 end
      local used = {}
      Osi.UseSpell = function(...) used[#used + 1] = { ... } end
      local queue = {}
      Ext.System.ServerCastRequest = { OsirisCastRequests = queue }

      -- the targeting type from the spell's data
      T_tt = { G.targetingType("Projectile_MainHandAttack"), G.targetingType("Target_MainHandAttack"),
        G.targetingType("Shout_Dash"), G.targetingType("Zone_Thing") }
      T_tt_none = { G.targetingType("Target_NoType") == nil, G.targetingType("Target_Odd") == nil,
        G.targetingType("Missing") == nil }
      -- the requests
      local Fp = { char = "c1", playerCast = true, realRolls = true }
      T_ok1 = G.castRequest(Fp, "c1", "Projectile_MainHandAttack", "b1")
      T_ok2 = G.castRequest(Fp, "c1", "Target_MainHandAttack", "b1")
      T_ok3 = G.castRequest(Fp, "c1", "Zone_Thing", "b1", true)
      T_req = queue
      local okn, whyn = G.castRequest(Fp, "c1", "Target_NoType", "b1")
      local okb, whyb = G.castRequest(Fp, "c1", "Target_NotInBook", "b1")
      T_refuse = { okn, whyn, okb, whyb, #queue }
      local up = G.bookSpellId("c1", "Target_Upcast_3")
      T_up = { up and up.Prototype, up and up.OriginatorPrototype, up and up.Source }
      local Fnr = { char = "c1", playerCast = true, realRolls = false }
      G.castRequest(Fnr, "c1", "Projectile_MainHandAttack", "b1")
      T_noroll = queue[#queue].CastOptions
      T_old = { G.castRequest({ char = "c1" }, "c1", "Projectile_MainHandAttack", "b1"), #used, #queue }

      -- the CastSpellFailed that comes before every accepted request
      local P = { who = "c1", spell = "Projectile_MainHandAttack", fails0 = 0, using0 = 0 }
      local Rf = { cast_fails = { { who = "c1", spell = "Projectile_MainHandAttack" } },
        usings = { { who = "c1", spell = "Projectile_MainHandAttack" } } }
      T_spur = G.playerRefused(P, Rf, 0) == nil and G.playerRefused(P, Rf, 5000) == nil
      local P2 = { who = "c1", spell = "Projectile_MainHandAttack", fails0 = 0, using0 = 0 }
      local Rg = { cast_fails = { { who = "c1", spell = "Projectile_MainHandAttack" } }, usings = {} }
      T_early = G.playerRefused(P2, Rg, 100) == nil
      T_late = G.playerRefused(P2, Rg, 100 + G.PLAYER_FAIL_MS) ~= nil

      -- the spending check
      local A1 = { { kind = "ActionPoint", n = 1 } }
      local B1 = { { kind = "BonusActionPoint", n = 1 } }
      local s = function(ap, ba, extra) local t = { ["ActionPoint:0"] = ap, ["BonusActionPoint:0"] = ba, pact = 0 }
        for k, v in pairs(extra or {}) do t[k] = v end return t end
      T_cc_ok = #G.costCheck({ A1[1], B1[1] }, nil, s(1, 2), s(0, 1))
      T_cc_extra = G.costCheck(A1, nil, s(1, 2), s(0, 1))
      T_cc_maybe = { #G.costCheck(A1, B1, s(1, 2), s(0, 1)), #G.costCheck(A1, B1, s(1, 2), s(0, 2)) }
      T_cc_short = G.costCheck(A1, nil, s(1, 2), s(1, 2))
      T_cc_surge = #G.costCheck({ { kind = "ActionSurgePoint", n = 1 } }, nil,
        s(0, 1, { ["ActionSurgePoint:0"] = 1 }), s(1, 1, { ["ActionSurgePoint:0"] = 0 }))
      local slot = { { kind = "SpellSlot", level = 1, n = 1 }, { kind = "BonusActionPoint", n = 1 } }
      local b4, a4 = s(1, 1, { ["SpellSlot:1"] = 0 }), s(1, 0, { ["SpellSlot:1"] = 0 })
      b4.pact, a4.pact = 2, 1
      T_cc_pact = #G.costCheck(slot, nil, b4, a4)

      -- settle on the player path: waits for the cast's end, checks what it spent, no harness payment
      local function pend(spell, toggled, opts)
        opts = opts or {}
        local rec = { result = "pending" }
        local F = { char = "c1", cooldown = {}, plan = {}, S = {}, playerCast = true, req = opts.req or {} }
        local costs = G._parseCosts(DATA[spell].UseCosts)
        local dual = G.dualCosts(spell)
        local hit = G.hitCosts({ spell = spell })
        local all = {}
        for _, c in ipairs(costs) do all[#all + 1] = c end
        for _, c in ipairs(dual or {}) do all[#all + 1] = c end
        for _, c in ipairs(hit) do all[#all + 1] = c end
        F.pending = { a = { spell = spell, group = "action", retried = opts.retried }, rec = rec, costs = costs,
          before = {}, res = {}, who = "c1", spell = spell, target = "b1", casts0 = 0, dmg0 = 0, t0 = 0, fails0 = 0,
          using0 = 0, dual = dual, dualBefore = {}, hit = hit, hitBefore = {}, toggled = toggled, player = true, range = opts.range,
          snap0 = G.costSnapshot("c1", all), togglePrev = opts.prev, toggleField = opts.prev ~= nil and "RangedToggledOn" or nil }
        local R = { r = 3, done = {}, casts = {}, actions = { rec } }
        return F, R, rec
      end
      -- a toggled shot: the engine spends AP 1 and BA 1, main + off-hand rows, then CastedSpell
      RES.ActionPoint, RES.BonusActionPoint = 1, 2
      E.c1.DualWielding.RangedToggledOn = true
      local F1, R1, rec1 = pend("Projectile_MainHandAttack", true, { prev = false })
      RES.ActionPoint, RES.BonusActionPoint = 0, 1
      G.dmg = { { source = "c1", target = "b1", cause = "Attack", amount = 9 } }
      T_s_wait = G.settle(F1, R1, 100)
      -- after a riposte the attack itself came 6 s after the engine spent: still waited for at 5.9 s
      T_s_late = G.settle(F1, R1, 5900)
      G.dmg[#G.dmg + 1] = { source = "c1", target = "b1", cause = "Offhand", amount = 4 }
      R1.casts[1] = { who = "c1", spell = "Projectile_MainHandAttack" }
      -- CastedSpell in, the strikes not yet marked done: still waiting; the off-hand half's LastAttack row ends it
      G.hits = { { source = "c1", target = "b1", attack_flags = "FirstAttack", hit = true } }
      T_s_strikes = G.settle(F1, R1, 6000)
      G.hits[2] = { source = "c1", target = "b1", attack_flags = "LastAttack", hit = true }
      T_s_done = G.settle(F1, R1, 6100)
      G.hits = {}
      -- a toggled melee attack after a frozen cast: main hand struck (FirstAttack only), the off-hand half never came
      -- but its bonus action was taken -> waited STRIKES_MAX_MS, then a "lost half" fault; a riposte's row is no strike
      RES.ActionPoint, RES.BonusActionPoint = 1, 2
      local Fl, Rl, recl = pend("Target_MainHandAttack", true)
      RES.ActionPoint, RES.BonusActionPoint = 0, 1
      local savedDmgL = G.dmg
      G.dmg = { { source = "c1", target = "b1", cause = "Attack", amount = 12, t = 50 } }
      G.hits = { { source = "c1", target = "b1", attack_flags = "FirstAttack", hit = true },
                 { source = "c1", target = "b1", attack_flags = "FirstAttack,LastAttack,Reaction", hit = true } }
      Rl.casts[1] = { who = "c1", spell = "Target_MainHandAttack" }
      T_l_wait = G.settle(Fl, Rl, 1000)
      T_l_done = G.settle(Fl, Rl, 1000 + G.STRIKES_MAX_MS)
      T_l_rec = { recl.offhand_half, Rl.cast_faults and Rl.cast_faults[1] and Rl.cast_faults[1].kind }
      G.hits, G.dmg = {}, savedDmgL
      T_s_rec = { rec1.result, rec1.offhand_half, R1.cast_faults == nil, RES.BonusActionPoint,
        E.c1.DualWielding.RangedToggledOn }
      -- a cast the engine ends with a CastSpellFailed of its own id after it hit (Dread Ambusher) is over at once; a
      -- failure of another id is not its end
      local savedD = G.dmg
      G.dmg = { { source = "c1", target = "b1", cause = "Attack", amount = 20, t = 900 } }
      G.hits = { { source = "c1", target = "b1", attack_flags = "FirstAttack,LastAttack", hit = true } }
      local Fd, Rd, recd = pend("Target_MainHandAttack", false)
      Fd.pending.sid = 77
      Rd.cast_fails = { { who = "c1", spell = "Target_MainHandAttack", sid = 78 } }
      T_fa_other = G.settle(Fd, Rd, 1200)
      Rd.cast_fails[2] = { who = "c1", spell = "Target_MainHandAttack", sid = 77 }
      T_fa_own = G.settle(Fd, Rd, 1300)
      T_fa_rec = recd.ended
      G.dmg, G.hits = savedD, {}
      -- no evidence yet past CONFIRM_MS: a cast the engine started (UsingSpell) is still waited for, one it did not
      -- start is a miss
      local savedDmg = G.dmg
      G.dmg = {}
      local Fu, Ru = pend("Target_MainHandAttack", false)
      Ru.usings = { { who = "c1", spell = "Target_MainHandAttack" } }
      T_s_using = G.settle(Fu, Ru, G.CONFIRM_MS + 1000)
      local Fn, Rn = pend("Target_MainHandAttack", false)
      T_s_nouse = G.settle(Fn, Rn, G.CONFIRM_MS + 1000)
      G.dmg = savedDmg
      -- a melee attack sent the wrong way: AP and BA gone, nothing hit
      RES.ActionPoint, RES.BonusActionPoint = 1, 2
      local F2, R2, rec2 = pend("Target_MainHandAttack", true)
      RES.ActionPoint, RES.BonusActionPoint = 0, 1
      G.dmg = {}
      R2.casts[1] = { who = "c1", spell = "Target_MainHandAttack" }
      G.settle(F2, R2, 1500)
      G.settle(F2, R2, 1500 + G.STRIKES_MAX_MS)
      T_bug = { rec2.result, R2.cast_faults and R2.cast_faults[1].kind, R2.cast_faults and R2.cast_faults[1].why,
        G.roundFault({ S = {} }, R2) }
      T_bug_judge = G.judge({ R2 }, "rounds done", { summary = {}, prep = {} }, {})
      -- a refused shot 21 m out of an 18 m range: recorded, never asked for again, the run invalid
      RES.ActionPoint, RES.BonusActionPoint = 1, 2
      POS.b1 = { 21, 0, 0 }
      local F3, R3, rec3 = pend("Projectile_MainHandAttack", true, { range = 18, req = { retry_any_refusal = true } })
      G.dmg = {}
      R3.cast_fails = { { who = "c1", spell = "Projectile_MainHandAttack" } }
      local w1 = G.settle(F3, R3, 100)
      local w2 = G.settle(F3, R3, 100 + G.PLAYER_FAIL_MS)
      T_range = { w1, w2, rec3.result, rec3.fail_kind, rec3.retries, R3.cast_faults and R3.cast_faults[1].kind,
        R3.cast_misses, F3.pending == nil }
      -- refused for resources (toggled with no bonus action): recorded, not a movement fault
      POS.b1 = { 10, 0, 0 }
      local F4, R4, rec4 = pend("Projectile_MainHandAttack", true, { range = 18 })
      RES.BonusActionPoint = 0
      R4.cast_fails = { { who = "c1", spell = "Projectile_MainHandAttack" } }
      G.settle(F4, R4, 100)
      G.settle(F4, R4, 100 + G.PLAYER_FAIL_MS)
      T_res = { rec4.fail_kind, R4.cast_faults == nil, rec4.result }
      -- no line of sight
      RES.BonusActionPoint = 2
      Osi.CanSee = function() return 0 end
      local F5, R5, rec5 = pend("Projectile_MainHandAttack", false, { range = 18 })
      R5.cast_fails = { { who = "c1", spell = "Projectile_MainHandAttack" } }
      G.settle(F5, R5, 100)
      G.settle(F5, R5, 100 + G.PLAYER_FAIL_MS)
      T_los = { rec5.fail_kind, R5.cast_faults and R5.cast_faults[1].kind }
      Osi.CanSee = function() return 1 end

      -- hit costs (HitCosts): a manoeuvre's superiority die is spent only when the attack hits
      local mh = G.hitCosts({ spell = "Target_MenacingAttack" })
      T_hc = { #mh, mh[1] and mh[1].kind, #G.hitCosts({ spell = "Target_MenacingAttack", hit_cost = "" }),
        #G.hitCosts({ spell = "Target_MainHandAttack" }), #G.hitCosts({ spell = "X", hit_cost = "SuperiorityDie:1" }) }
      RES.ActionPoint, RES.SuperiorityDie = 1, 0
      T_hc_afford = { G.afford({ char = "c1", cooldown = {} }, { spell = "Target_MenacingAttack", group = "action" }) }
      local function man(spent, rows)
        RES.ActionPoint, RES.BonusActionPoint, RES.SuperiorityDie = 1, 2, 4
        local Fm, Rm, recm = pend("Target_MenacingAttack", false)
        RES.ActionPoint, RES.SuperiorityDie = 0, 4 - spent
        G.hits, G.dmg = rows, {}
        Rm.casts[1] = { who = "c1", spell = "Target_MenacingAttack" }
        G.settle(Fm, Rm, 1500)
        G.settle(Fm, Rm, 1500 + G.STRIKES_MAX_MS)
        return { recm.result, recm.hit_cost, Rm.cast_faults and Rm.cast_faults[1].why or "" }
      end
      local HIT = { { source = "c1", target = "b1", spell = "Target_MenacingAttack", hit = true } }
      local CRIT = { { source = "c1", target = "b1", spell = "Target_MenacingAttack", hit = true, crit = true } }
      local MISS = { { source = "c1", target = "b1", spell = "Target_MenacingAttack", miss = true } }
      T_hc_miss, T_hc_hit, T_hc_crit = man(0, MISS), man(1, HIT), man(1, CRIT)
      T_hc_hit0, T_hc_miss1 = man(0, HIT), man(1, MISS)
      T_hc_unseen = { man(0, {}), man(1, {}) }
      -- no hit-log row: the damage row decides (a miss is a 0 damage row)
      T_hc_dmg = { G.castLanded({ who = "c1", target = "b1", spell = "Target_MenacingAttack" }, {},
          { { source = "c1", target = "b1", cause = "Attack", amount = 0 } }),
        G.castLanded({ who = "c1", target = "b1", spell = "Target_MenacingAttack" }, {},
          { { source = "c1", target = "b1", cause = "Attack", amount = 7 } }) }
      G.hits = {}
      RES.SuperiorityDie = nil

      -- doAction: no bonus action -> untoggled; a spell with no SpellType is not cast
      G.dmg = {}
      RES.ActionPoint, RES.BonusActionPoint = 1, 0
      E.c1.DualWielding.RangedToggledOn = true
      local atk = { spell = "Projectile_MainHandAttack", group = "action", target = "@boss" }
      local Fd = { char = "c1", enemies = { "b1" }, cooldown = {}, afford = function() return true end, plan = {}, S = {},
        qi = 1, queue = { atk }, playerCast = true, realRolls = true }
      local Rd = { r = 1, done = {}, actions = {}, casts = {} }
      local n0 = #queue
      G._doAction(Fd, atk, Rd)
      T_d = { Rd.actions[1].dual_toggle, E.c1.DualWielding.RangedToggledOn, #queue - n0, Fd.pending and Fd.pending.player,
        Fd.pending and Fd.pending.togglePrev }
      Fd.pending = nil
      local Rn = { r = 1, done = {}, actions = {}, casts = {} }
      G._doAction(Fd, { spell = "Target_NoType", group = "action", target = "@boss" }, Rn)
      T_dn = { Rn.actions[1].result, Rn.cast_faults and Rn.cast_faults[1].kind, Fd.pending == nil }

      -- the default and the old path's switch
      T_default = G.PLAYER_CAST

      Ext.Stats.Get, Ext.Entity.Get, Osi.GetPosition, Osi.GetActionResourceValuePersonal = stats, eget, gpos, gres
      Osi.CanSee, Osi.UseSpell, Ext.System.ServerCastRequest = canSee, useSpell, sys
      G.dmg = {}
    """)
    g = L.globals()
    check("player cast: TargetingType from the spell's SpellType (Projectile, Target, Shout, Zone)",
          lst(g.T_tt) == ["Projectile", "Target", "Shout", "Zone"], str(lst(g.T_tt)))
    check("player cast: no SpellType, or one the engine does not have, gives no TargetingType",
          all(lst(g.T_tt_none)), str(lst(g.T_tt_none)))
    q = [g.T_req[i + 1] for i in range(3)]
    opts = [sorted(lst(r.CastOptions)) for r in q]
    check("player cast: the request carries FromClient and no Ignore* option, as a click's",
          g.T_ok1 is True and all(o == sorted(["FromClient", "ShowPrepareAnimation", "AvoidDangerousAuras",
                                                "NoMovement"]) for o in opts), str(opts))
    check("player cast: ranged attack as Projectile, melee attack as Target, a zone spell as Zone",
          [r.Targets[1].TargetingType for r in q] == ["Projectile", "Target", "Zone"],
          str([r.Targets[1].TargetingType for r in q]))
    check("player cast: an attack names its target, a ground spell only the position",
          q[0].Targets[1].Target.tag == "boss" and q[1].Targets[1].Target.tag == "boss"
          and q[2].Targets[1].Target is None and q[2].Targets[1].Position[1] == 10)
    check("player cast: the spell id from the spell book (source, source type)",
          q[0].Spell.Source == "src-Projectile_MainHandAttack" and q[0].Spell.SourceType == "WeaponSpell"
          and q[0].Spell.Prototype == "Projectile_MainHandAttack", str(q[0].Spell.Source))
    rf = seq(g.T_refuse, 5)
    check("player cast: no SpellType or not in the spell book: nothing queued, the reason given",
          rf[0] is False and "SpellType" in str(rf[1]) and rf[2] is False and "spell book" in str(rf[3])
          and rf[4] == 3, str(rf))
    check("player cast: an upcast goes out under its base spell's book entry",
          seq(g.T_up, 3) == ["Target_Upcast_3", "Target_Upcast", "src-Target_Upcast"], str(seq(g.T_up, 3)))
    check("player cast: a run without real rolls asks for none", "IgnoreSpellRolls" in lst(g.T_noroll))
    check("player cast: the old path still casts with Osi.UseSpell", seq(g.T_old, 3) == [True, 1, 4], str(seq(g.T_old, 3)))
    check("player cast: the CastSpellFailed before an accepted request is not a refusal", g.T_spur is True)
    check("player cast: a refusal counts once PLAYER_FAIL_MS passed with no UsingSpell",
          g.T_early is True and g.T_late is True, f"{g.T_early} {g.T_late}")
    check("spent: a toggled shot that fired both halves owes action + bonus action", g.T_cc_ok == 0, str(g.T_cc_ok))
    ce = g.T_cc_extra
    check("spent: a bonus action spent and not owed is a mismatch",
          len(ce) == 1 and ce[1].cost == "BonusActionPoint:0" and ce[1].got == 1, str(len(ce)))
    check("spent: the off-hand half may be spent when its row did not come (toggle on)",
          lst(g.T_cc_maybe) == [0, 0], str(lst(g.T_cc_maybe)))
    check("spent: an owed action not spent is a mismatch", len(g.T_cc_short) == 1, str(len(g.T_cc_short)))
    check("spent: an action gained (Action Surge) is not a mismatch", g.T_cc_surge == 0, str(g.T_cc_surge))
    check("spent: a spell slot paid with a pact slot counts", g.T_cc_pact == 0, str(g.T_cc_pact))
    sr = seq(g.T_s_rec, 5)
    check("player cast: settle waits for the cast's end (CastedSpell), not the resource drop",
          g.T_s_wait is False and g.T_s_late is False and g.T_s_strikes is False and g.T_s_done is True,
          f"{g.T_s_wait} {g.T_s_late} {g.T_s_strikes} {g.T_s_done}")
    lr = seq(g.T_l_rec, 2)
    check("player cast: an off-hand half the engine dropped is waited for, then a 'lost half' fault",
          g.T_l_wait is False and g.T_l_done is True and lr == ["lost", "lost half"], f"{g.T_l_wait} {g.T_l_done} {lr}")
    check("player cast: a CastSpellFailed of the cast's own id after it started ends it at once; another id's does not",
          g.T_fa_other is False and g.T_fa_own is True and g.T_fa_rec == "failed after start",
          f"{g.T_fa_other} {g.T_fa_own} {g.T_fa_rec}")
    check("player cast: no evidence yet, a cast the engine started (UsingSpell) waited for, one never started a miss",
          g.T_s_using is False and g.T_s_nouse is True, f"{g.T_s_using} {g.T_s_nouse}")
    check("player cast: a toggled shot that matches its costs is done, the harness pays nothing, the toggle put back",
          sr[0] == "done" and sr[1] == "fired" and sr[2] is True and sr[3] == 1 and sr[4] is False, str(sr))
    bug = seq(g.T_bug, 4)
    check("player cast: action + bonus action spent and nothing hit (melee sent as a projectile) fails the run",
          bug[0] == "done" and bug[1] == "costs" and "BonusActionPoint" in str(bug[2])
          and "round 3" in str(bug[3]) and "spent other than its costs" in str(bug[3]), str(bug))
    jc = lst(g.T_bug_judge.causes)
    check("player cast: a cost mismatch is a cause in the run's verdict",
          g.T_bug_judge.valid is False and any("spent other than its costs" in c for c in jc), str(jc))
    rg = seq(g.T_range, 8)
    check("player cast: a refusal waits PLAYER_FAIL_MS, then fails with its reason (out of range)",
          rg[0] is False and rg[1] is True and "out of range 21.0 > 18.0" in str(rg[2]) and rg[3] == "range", str(rg))
    check("player cast: a refusal is never asked for again (even with retry_any_refusal)",
          rg[4] is None and rg[6] == 1 and rg[7] is True, str(rg))
    check("player cast: refused for range = the plan's movement was wrong, the run invalid", rg[5] == "movement", str(rg))
    rs = seq(g.T_res, 3)
    check("player cast: refused for resources is recorded as such, not a movement fault",
          rs[0] == "resources" and rs[1] is True and "BonusActionPoint" in str(rs[2]), str(rs))
    check("player cast: refused with no line of sight = a movement fault",
          seq(g.T_los, 2) == ["line of sight", "movement"], str(seq(g.T_los, 2)))
    d = seq(g.T_d, 5)
    check("dual wield: no bonus action left -> the attack goes untoggled (the request is not refused), toggle kept to put back",
          d[0] is False and d[1] is False and d[2] == 1 and d[3] is True and d[4] is True, str(d))
    dn = seq(g.T_dn, 3)
    check("player cast: a planned spell with no SpellType is not cast and fails the run",
          "player path" in str(dn[0]) and dn[1] == "request" and dn[2] is True, str(dn))
    check("player cast: the default path", g.T_default is True)
    hc = seq(g.T_hc, 5)
    check("hit costs: read from the spell's HitCosts, the plan's hit_cost first (empty = none)",
          hc == [1, "SuperiorityDie", 0, 0, 1], str(hc))
    ha = seq(g.T_hc_afford, 2)
    check("hit costs: a manoeuvre with no superiority die left is not affordable",
          ha[0] is False and "SuperiorityDie" in str(ha[1]), str(ha))
    for name, want_ok, want_tag in (("T_hc_miss", True, "none"), ("T_hc_hit", True, "owed"), ("T_hc_crit", True, "owed"),
                                    ("T_hc_hit0", False, "owed"), ("T_hc_miss1", False, "none")):
        r_ = seq(getattr(g, name), 3)
        ok_ = r_[0] == "done" and r_[1] == want_tag and ((r_[2] == "") if want_ok else "SuperiorityDie" in str(r_[2]))
        check(f"hit costs: {name[5:]}: a die spent only on a hit, else a cost mismatch "
              f"(want {'no fault' if want_ok else 'a fault'}, {want_tag})", ok_, str(r_))
    un = [seq(x, 3) for x in lst(g.T_hc_unseen)]
    check("hit costs: outcome not seen -> the die may or may not be spent",
          all(u[0] == "done" and u[1] == "unseen" and u[2] == "" for u in un), str(un))
    check("hit costs: with no hit-log row a 0 damage row is a miss, damage a hit",
          seq(g.T_hc_dmg, 2) == [False, True], str(seq(g.T_hc_dmg, 2)))
    L.execute(r"""
      local G = GAUNTLET
      T_pc = { G.playerCastFor({ mode = "scripted" }), G.playerCastFor({ mode = "scripted", player_cast = false }),
        G.playerCastFor({ mode = "manual" }), G.playerCastFor({ mode = "scripted", player_cast = true }) }
      G.PLAYER_CAST = false
      T_pc_off = G.playerCastFor({ mode = "scripted" })
      G.PLAYER_CAST = true
    """)
    check("player cast: scripted runs take it unless player_cast = false; manual runs never",
          seq(L.globals().T_pc, 4) == [True, False, False, True] and L.globals().T_pc_off is False,
          str(seq(L.globals().T_pc, 4)))


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
      -- a slow frame: the first check of the boots comes after the whole wait (the helmet went on at once)
      local per, calls, made = {}, 0, 0
      Osi.CreateAt = function() made = made + 1; return made == 1 and "helm" or "boots" end
      Osi.Equip = function(_, it) per[it] = (per[it] or 0) + 1 end
      Osi.IsEquipped = function(it) return (it == "helm" and per[it] or (per[it] or 0) >= 2) and 1 or 0 end
      Ext.Timer.WaitFor = function(ms, f) calls = calls + 1; clock = clock + (calls == 3 and 3000 or ms); f() end
      G.results = { items = {} }
      G._equipAll("c1", { { slot = "Helmet", template = "t", stats = "MAG_Helm" },
        { slot = "Boots", template = "t", stats = "MAG_Boots" } }, 1, function() end)
      for _, r in ipairs(G.results.items) do if r.stats == "MAG_Boots" then T_eqslow = r end end
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
      -- a run asked with retry_any_refusal: the same refusal is asked for again
      local F3 = { char = "c1", enemies = { "e1" }, cooldown = {}, plan = {}, afford = function() return true end,
                   req = { retry_any_refusal = true } }
      local R3 = { r = 3, actions = {}, casts = {}, done = {}, cast_fails = {}, reactions_seen = {} }
      G.rounds = { R3 }
      G._doAction(F3, { spell = "Projectile_FireBolt", group = "action", target = "@boss" }, R3)
      G._onCastFailed("c1", "Projectile_FireBolt")
      G.settle(F3, R3, 100)
      T_anyretry = F3.pending ~= nil and R3.actions[1].retries == 1 and (R3.cast_misses or 0) == 0
      T_anydefault = G.RETRY_ANY_REFUSAL
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
    check("refusal: retry_any_refusal (off by default) asks again for a refusal with no reason shown",
          g.T_anyretry is True and g.T_anydefault is False, f"{g.T_anyretry} {g.T_anydefault}")
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
    check("fail fast: a setup mismatch at the start ends the run before round 1, invalid, every cause kept",
          g.T_state == "done" and g.T_res.ended == "setup mismatch at the start" and g.T_res.summary.rounds == 0 and
          g.T_res.valid is False and any(c.startswith("setup mismatch at the start: ") for c in lst(g.T_res.invalid)),
          f"{g.T_state} {g.T_res.ended}")


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
      -- the stubbed world fails the setup check: this start is followed past it
      G.FAIL_FAST = false
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
      G.FAIL_FAST = true
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


def item_resource_check_tests(L):
    """The setup check adds what the worn items give (spec.item_resources) to the class resources and spell slots: an
    amulet's extra Channel Divinity charge is expected, not a mismatch; a resource only the items give is checked too."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.results = { prep = { bare = {}, items = {} } }
      local sheet = G.sheet
      local have = { slots = { ["1"] = 3 }, resources = { ["ChannelDivinity:0"] = 2, ["SorceryPoint:0"] = 1 } }
      G.sheet = function() return have end
      local base = { slots = { ["1"] = 2 }, resources = { { kind = "ChannelDivinity", level = 0, n = 1 } } }
      local items = { { kind = "ChannelDivinity", level = 0, n = 1 }, { kind = "SpellSlot", level = 1, n = 1 },
                      { kind = "SorceryPoint", level = 0, n = 1 } }
      T_with = G.setupCheck({ char = "c1" }, { slots = base.slots, resources = base.resources, item_resources = items },
        "start")
      T_without = G.setupCheck({ char = "c1" }, { slots = base.slots, resources = base.resources }, "start")
      have.resources["SorceryPoint:0"] = nil
      T_missing = G.setupCheck({ char = "c1" }, { slots = base.slots, resources = base.resources, item_resources = items },
        "start")
      G.sheet = sheet
    """)
    g = L.globals()

    def fields(t):
        return sorted(m.field for m in t.mismatches.values())
    check("setup: the items' extra Channel Divinity charge and spell slot are expected (no mismatch)",
          fields(g.T_with) == [], str([(m.field, m.want, m.got) for m in g.T_with.mismatches.values()]))
    check("setup: without the items' resources the extra charge and slot are mismatches",
          fields(g.T_without) == ["resource ChannelDivinity", "spell slots L1"], str(fields(g.T_without)))
    check("setup: a resource only the items give is checked",
          fields(g.T_missing) == ["resource SorceryPoint (from items)"], str(fields(g.T_missing)))


def summon_turn_tests(L):
    """The character's own summon (Spiritual Weapon) gets a turn nobody drives: it is ended as soon as it comes and
    counted, and the watchdog names the summon as the turn's holder instead of 'nobody holds the turn'."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local active = { sw = true }
      local ents, entOf = {}, {}
      for _, u in ipairs({ "c1", "sw", "other" }) do
        local e = { Uuid = { EntityUuid = u },
          IsSummon = (u == "sw") and { Owner = { Uuid = { EntityUuid = "c1" } } } or nil }
        e.TurnBased = setmetatable({}, { __index = function(_, k)
          if k == "IsActiveCombatTurn" then return active[u] == true end end })
        ents[#ents + 1] = e
        entOf[u] = e
      end
      Ext.Entity.GetAllEntitiesWithComponent = function() return ents end
      Ext.Entity.Get = function(u) return entOf[u] end
      Osi.IsSummon = function(u) return u == "sw" and 1 or 0 end
      Osi.IsDead = function() return 0 end
      Osi.IsInCombat = function() return 1 end
      local ended = {}
      Osi.EndTurn = function(u) ended[#ended + 1] = u; active[u] = false end
      local F = { char = "c1", enemies = {}, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                  started = 1, state = "wait", deadline = 1e9 }
      G.F = F
      G.round = 1
      G.step(F, 10)
      T_ended = ended
      T_count = G.results.summon_turns_ended
      T_state = F.state
      -- a summon whose turn will not end: the watchdog's recovery names it
      active.sw = true
      Osi.EndTurn = function() end
      F.summonCheck = 1e12
      F.deadline = 0
      G.step(F, 20)
      T_rec = G.results.turn_recoveries and G.results.turn_recoveries[1] and G.results.turn_recoveries[1].what
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Ext.Entity.Get = function() return nil end
      Osi.IsSummon, Osi.IsDead, Osi.IsInCombat, Osi.EndTurn = nil, nil, nil, nil
      G.F = nil
    """)
    g = L.globals()
    check("summon: the character's summon's turn is ended at once and counted, the fight keeps waiting",
          lst(g.T_ended) == ["sw"] and g.T_count == 1 and g.T_state == "wait", f"{lst(g.T_ended)} {g.T_count}")
    check("summon: the watchdog names the character's summon as the turn's holder", "sw" in str(g.T_rec),
          str(g.T_rec))


def npc_park_tests(L):
    """Lanes: living characters outside the party in a lane (radius + margin) are moved to the lanes' npc_park before
    the run, their spots kept; party members (also one made a player by script, missing from the players database),
    summons and far ones stay; everyone moved goes back after the last lane, also when the run is aborted."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local at = { ghost = { -157, 17, 939 }, monk = { -157, 17, 941 }, gale = { -156, 17, 937 },
        sw = { -150, 17, 937 }, far = { -100, 17, 937 }, edge = { -142, 17, 962 }, dead = { -150, 17, 940 } }
      local function reset()
        at.ghost, at.monk, at.edge = { -157, 17, 939 }, { -157, 17, 941 }, { -142, 17, 962 }
      end
      local ents = {}
      for u in pairs(at) do ents[#ents + 1] = { Uuid = { EntityUuid = u } } end
      Ext.Entity.GetAllEntitiesWithComponent = function() return ents end
      Osi.GetPosition = function(u) local p = at[u]; if p then return p[1], p[2], p[3] end end
      Osi.IsDead = function(u) return u == "dead" and 1 or 0 end
      Osi.IsSummon = function(u) return u == "sw" and 1 or 0 end
      Osi.IsPlayer = function(u) return u == "gale" and 1 or 0 end
      Osi.DB_Players = { Get = function() return { { "host" } } end }
      Osi.FindValidPosition = function(x, y, z) return x, y, z end
      Osi.TeleportToPosition = function(u, x, y, z) at[u] = { x, y, z } end
      local B = { center = { -142, 17.4, 937.5 }, radius = 16 }
      G.movedNpcs = nil
      T_moved = G.npcsAway({ B }, { -1328, 2, 528 }, 10)
      T_at = { ghost = at.ghost[1], monk = at.monk[1], gale = at.gale[1], sw = at.sw[1], far = at.far[1],
               edge = at.edge[1] }
      T_back = G.npcsBack()
      T_home = { ghost = at.ghost[1], monk = at.monk[3] }
      reset()
      -- the lanes' runner moves them when the lanes entry names npc_park, puts them back after the last lane
      local run, park, cat, lf, fr = G.run, G.parkOthers, G.catalog, G.laneFactions, G.laneFactionsRestore
      G.run = function() return "started" end
      G.parkOthers = function() return 0 end
      G.laneFactions = function() return {} end
      G.laneFactionsRestore = function() return 0 end
      G.catalog = function() return { arenas = { a1 = { center = { 0, 0, 0 }, radius = 16, start = { 0, 0, 0 } },
        a2 = B, LN = { lanes = { A = { arena = "a1" }, B = { arena = "a2" } }, park = { 5, 5, 5 },
        npc_park = { -1328, 2, 528 }, margin = 10 } } } end
      G.LANES = nil
      G.runLanes({ run_id = "L1", lanes = "LN", first = "A",
        entries = { { id = "A", req = { char = "host" } }, { id = "B", req = { char = "gale" } } } })
      T_lmoved = #(G.LANES.npcs_moved or {})
      T_lat = at.ghost[1]
      for _, id in ipairs({ "A", "B" }) do G.inLane(id, function() G.F = { state = "done" } end) end
      G.lanesDone()
      T_lback, T_lhome = G.LANES.npcs_restored, at.ghost[1]
      reset()
      -- a run stopped before its last lane put them back: abort does
      G.LANES = nil
      G.npcsAway({ B }, { -1328, 2, 528 }, 10)
      G.abort()
      T_ahome, T_aleft = at.ghost[1], G.movedNpcs
      G.run, G.parkOthers, G.catalog, G.laneFactions, G.laneFactionsRestore = run, park, cat, lf, fr
      G.LANES = nil
      for _, id in ipairs({ "A", "B" }) do G.inLane(id, function() G.F = nil end) end
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Osi.GetPosition, Osi.IsDead, Osi.IsSummon, Osi.IsPlayer, Osi.DB_Players = nil, nil, nil, nil, nil
      Osi.FindValidPosition, Osi.TeleportToPosition = nil, nil
    """)
    g = L.globals()
    moved = sorted(m.uuid for m in g.T_moved.values())
    check("npc park: living characters outside the party within the lane's radius + margin are moved",
          moved == ["edge", "ghost", "monk"] and g.T_at.ghost == -1328 and g.T_at.edge == -1328, str(moved))
    check("npc park: party members (one missing from the players database), summons and far ones stay",
          g.T_at.gale == -156 and g.T_at.sw == -150 and g.T_at.far == -100, str(dict(g.T_at)))
    check("npc park: everyone moved goes back to where they stood", g.T_back == 3 and g.T_home.ghost == -157 and
          g.T_home.monk == 941, f"{g.T_back} {dict(g.T_home)}")
    check("npc park: the lanes' runner moves them for the run and puts them back after the last lane",
          g.T_lmoved == 3 and g.T_lat == -1328 and g.T_lback == 3 and g.T_lhome == -157,
          f"{g.T_lmoved} {g.T_lat} {g.T_lback} {g.T_lhome}")
    check("npc park: a stopped run puts them back too", g.T_ahome == -157 and g.T_aleft is None, str(g.T_ahome))



def summon_attack_tests(L):
    """The character's summon attacks on its own turn: its basic attack on the boss, cast from where it stands, confirmed
    by a cast event like a planned cast, then its turn ends; a refused attack fails the run; its damage is the side's,
    counted apart as summon damage."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local active = { sw = true }
      local ents, entOf = {}, {}
      for _, u in ipairs({ "c1", "sw", "b1" }) do
        local e = { Uuid = { EntityUuid = u },
          IsSummon = (u == "sw") and { Owner = { Uuid = { EntityUuid = "c1" } } } or nil,
          SpellBook = (u == "sw") and { Spells = { { Id = { Prototype = "Target_Hover" } },
            { Id = { Prototype = "Target_MainHandAttack" } } } } or nil }
        e.TurnBased = setmetatable({}, { __index = function(_, k)
          if k == "IsActiveCombatTurn" then return active[u] == true end end })
        ents[#ents + 1] = e
        entOf[u] = e
      end
      local posOf = { c1 = { 6, 0, 0 }, sw = { 0, 0, 0 }, b1 = { 1, 0, 0 } }
      Ext.Entity.GetAllEntitiesWithComponent = function() return ents end
      Ext.Entity.Get = function(u) return entOf[u] end
      Osi.GetPosition = function(u) local p = posOf[u] or { 0, 0, 0 }; return p[1], p[2], p[3] end
      Osi.IsSummon = function(u) return u == "sw" and 1 or 0 end
      Osi.IsDead = function() return 0 end
      local used, ended = {}, {}
      Osi.UseSpell = function(c, sp, t1, t2, nomove) used[#used + 1] = { c, sp, t1, nomove } end
      Osi.EndTurn = function(u) ended[#ended + 1] = u; active[u] = false end
      local F = { char = "c1", enemies = { "b1" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {}, rounds = 16,
                  started = 1, state = "wait", deadline = 1e9 }
      G.F = F
      G.fighting, G.round = true, 1
      G.rounds = { { r = 1, casts = {}, cast_fails = {}, actions = {}, done = {}, reactions_seen = {} } }
      G.step(F, 10)
      T_used = used[1]
      T_pending = F.summon ~= nil
      G._onCast("sw", "Target_MainHandAttack")
      G.dmg[#G.dmg + 1] = { r = 1, source = "sw", owner = "sw", target = "b1", amount = 7 }
      G.dmg[#G.dmg + 1] = { r = 1, source = "c1", owner = "c1", target = "b1", amount = 10 }
      G.step(F, 20)
      T_turn = G.results.summon_turns[1]
      T_ended = { table.unpack and table.unpack(ended) or unpack(ended) }
      T_sum = G._summarize(F)
      -- the next round: the attack is refused
      active.sw = true
      G.round = 2
      G.rounds[2] = { r = 2, casts = {}, cast_fails = {}, actions = {}, done = { action = true }, reactions_seen = {} }
      F.summonCheck = 0
      G.step(F, 2000)
      G._onCastFailed("sw", "Target_MainHandAttack")
      G.step(F, 2100)
      T_turn2 = G.results.summon_turns[2]
      G.results.summary = G._summarize(F)
      T_j = G.judge({ { r = 1, done = { action = true } } }, "rounds done", G.results, { me = "c1" })
      G.fighting, G.F = false, nil
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Ext.Entity.Get = function() return nil end
      Osi.GetPosition, Osi.IsSummon, Osi.IsDead, Osi.UseSpell, Osi.EndTurn = nil, nil, nil, nil, nil
    """)
    g = L.globals()
    u = lst(g.T_used) or []
    check("summon: its own turn is driven with its basic attack on the boss, cast from where it stands",
          u[:3] == ["sw", "Target_MainHandAttack", "b1"] and u[3] == 1 and g.T_pending, str(u))
    check("summon: the attack is confirmed by the summon's cast and its turn ends",
          g.T_turn.result == "done" and g.T_turn.confirmed == "cast" and lst(g.T_ended) == ["sw"],
          f"{g.T_turn.result} {lst(g.T_ended)}")
    check("summon: its damage is the side's, counted apart as summon damage",
          g.T_sum.summon_damage == 7 and g.T_sum.dealt[1] == 17, f"{g.T_sum.summon_damage} {g.T_sum.dealt[1]}")
    causes = lst(g.T_j.causes)
    check("summon: an attack the engine refused fails the run",
          str(g.T_turn2.result).startswith("failed") and any("summon attack" in c for c in causes), str(causes))


def item_rule_surge_tests(L):
    """An item action in an Action Surge round takes the surge's action: the first action keeps its Extra Attack and
    the Dread Ambusher attack stays first; without a surge it replaces the core action as before."""
    L.execute(r"""
      local G = GAUNTLET
      local F = { cooldown = {}, afford = function() return true end, plan = { item_actions = {
        { spell = "Projectile_RoaringShot", item = "Bow", group = "action", per = "short" } } } }
      local list = { { spell = "Projectile_DreadAmbusher", group = "free", cost = "free" },
        { spell = "Shout_ActionSurge", group = "free", cost = "free" },
        { spell = "Projectile_MainHandAttack", group = "action" },
        { spell = "Projectile_MainHandAttack", group = "free", requires = "action", why = "Extra Attack" },
        { spell = "Projectile_MainHandAttack", group = "free", requires = "surge", why = "s1" },
        { spell = "Projectile_MainHandAttack", group = "free", requires = "surge", why = "s2" } }
      T_s = G._itemRule(F, list, { done = {} })
      T_n = G._itemRule(F, { list[3], list[4] }, { done = {} })
    """)
    g = L.globals()
    s = [(g.T_s[i + 1].spell, g.T_s[i + 1].requires) for i in range(len(g.T_s))]
    check("item rule: in a surge round the item spell takes the surge's action, the first action keeps its Extra Attack",
          s == [("Projectile_DreadAmbusher", None), ("Shout_ActionSurge", None), ("Projectile_MainHandAttack", None),
                ("Projectile_MainHandAttack", "action"), ("Projectile_RoaringShot", "surge")], str(s))
    check("item rule: the surge's own attack is the item spell's fallback",
          g.T_s[5].alt is not None and g.T_s[5].alt.why == "s1", str(s))
    n = [g.T_n[i + 1].spell for i in range(len(g.T_n))]
    check("item rule: without a surge the item spell still replaces the core action", n[0] == "Projectile_RoaringShot",
          str(n))


def offhand_melee_tests(L):
    """The off-hand half of a dual-wield attack is told by its place in the cast, not by the damage cause: a melee
    off-hand half's rows come with cause Attack like the main hand's. The cast's second strike (attack rows more than
    ROLL_MERGE_MS after the first) or a hit row that is the cast's last attack and not its first is the off-hand half;
    one strike's damage types and riders are not. The spend check then owes its bonus action. A melee weapon attack
    always goes out with its own SpellType (Target), never as a Projectile."""
    L.execute(r"""
      local G = GAUNTLET
      local P = { who = "c1", target = "b1", dmg0 = 0, hits0 = 0 }
      local function row(t, cause, amount, typ)
        return { source = "c1", owner = "c1", target = "b1", t = t, cause = cause, amount = amount, type = typ }
      end
      -- a melee main hand (two damage types) then the off-hand half 0.56 s later, all cause Attack
      T_om_two = G.offhandFired(P, { row(1000, "Attack", 8, "Piercing"), row(1000, "Attack", 4, "Necrotic"),
        row(1560, "Attack", 6, "Piercing") })
      -- the off-hand half missed: its 0 damage row is the second strike too
      T_om_miss = G.offhandFired(P, { row(1000, "Attack", 8, "Piercing"), row(1560, "Attack", 0, nil) })
      -- one strike with a rider row of its own (Sneak Attack) shortly after: no off-hand half
      T_om_one = G.offhandFired(P, { row(1000, "Attack", 8, "Piercing"), row(1066, "Attack", 11, "Piercing") })
      -- another target's row or a status tick is no second strike
      local other = row(1600, "Attack", 5, "Piercing"); other.target = "e9"
      T_om_other = G.offhandFired(P, { row(1000, "Attack", 8, "Piercing"), other, row(1700, "Status", 3, "Fire") })
      -- the hit log: the cast's last attack and not its first is the off-hand half; a single attack carries both
      T_om_hit = G.offhandFired(P, {}, { { source = "c1", attack_flags = "FirstAttack" },
        { source = "c1", attack_flags = "LastAttack" } })
      T_om_hit1 = G.offhandFired(P, {}, { { source = "c1", attack_flags = "FirstAttack,LastAttack" } })
      T_om_ranged = G.offhandFired(P, { row(1000, "Attack", 8, "Piercing"), row(1400, "Offhand", 5, "Piercing") })

      -- the spend check on the player path: a toggled melee attack, both halves cause Attack
      local stats, eget, gres = Ext.Stats.Get, Ext.Entity.Get, Osi.GetActionResourceValuePersonal
      Ext.Stats.Get = function(s) if s == "Target_MainHandAttack" then return { SpellType = "Target",
        UseCosts = "ActionPoint:1", DualWieldingUseCosts = "BonusActionPoint:1" } end end
      local RES = { ActionPoint = 1, BonusActionPoint = 2 }
      Osi.GetActionResourceValuePersonal = function(_, k) return RES[k] or 0 end
      Ext.Entity.Get = function() return { DualWielding = {}, Replicate = function() end } end
      local function pend()
        local rec = { result = "pending" }
        local costs = G._parseCosts("ActionPoint:1")
        local dual = G.dualCosts("Target_MainHandAttack")
        local F = { char = "c1", cooldown = {}, plan = {}, S = {}, playerCast = true, req = {} }
        F.pending = { a = { spell = "Target_MainHandAttack", group = "action" }, rec = rec, costs = costs, before = {},
          res = {}, who = "c1", spell = "Target_MainHandAttack", target = "b1", casts0 = 0, dmg0 = 0, hits0 = 0, t0 = 0,
          fails0 = 0, using0 = 0, dual = dual, dualBefore = {}, toggled = true, player = true,
          snap0 = G.costSnapshot("c1", { costs[1], dual[1] }) }
        local R = { r = 2, done = {}, casts = { { who = "c1", spell = "Target_MainHandAttack" } }, actions = { rec } }
        return F, R, rec
      end
      G.hits = {}
      RES.ActionPoint, RES.BonusActionPoint = 1, 2
      local F1, R1, rec1 = pend()
      RES.ActionPoint, RES.BonusActionPoint = 0, 1
      G.dmg = { row(1000, "Attack", 8, "Piercing"), row(1560, "Attack", 6, "Piercing") }
      G.settle(F1, R1, 2000)
      G.settle(F1, R1, 2000 + G.STRIKES_MAX_MS)
      T_os_ok = { rec1.result, rec1.offhand_half, R1.cast_faults == nil }
      -- both halves struck and no bonus action spent: the off-hand half's bonus action is owed
      RES.ActionPoint, RES.BonusActionPoint = 1, 2
      local F2, R2, rec2 = pend()
      RES.ActionPoint, RES.BonusActionPoint = 0, 2
      G.settle(F2, R2, 2000)
      G.settle(F2, R2, 2000 + G.STRIKES_MAX_MS)
      T_os_owed = { rec2.offhand_half, R2.cast_faults and R2.cast_faults[1].kind,
        R2.cast_faults and R2.cast_faults[1].why }
      G.dmg, G.hits = {}, {}

      -- a melee weapon attack goes out with its own SpellType, never as a Projectile, whatever the toggles or the
      -- ranged attack before it
      local DATA = { Projectile_MainHandAttack = { SpellType = "Projectile", UseCosts = "ActionPoint:1" },
        Target_MainHandAttack = { SpellType = "Target", UseCosts = "ActionPoint:1" },
        Target_OffhandAttack = { SpellType = "Target", UseCosts = "BonusActionPoint:1" },
        Target_DreadAmbusher = { SpellType = "Target", UseCosts = "" },
        Target_TripAttack = { SpellType = "Target", UseCosts = "ActionPoint:1;SuperiorityDie:1" } }
      Ext.Stats.Get = function(s) return DATA[s] end
      local book = {}
      for s in pairs(DATA) do book[#book + 1] = { Id = { Prototype = s, OriginatorPrototype = s, Source = "w" } } end
      local E = { c1 = { SpellBook = { Spells = book }, DualWielding = { RangedToggledOn = true, MeleeToggledOn = true } },
        b1 = {} }
      Ext.Entity.Get = function(u) return E[u] end
      local gpos, sys = Osi.GetPosition, Ext.System.ServerCastRequest
      Osi.GetPosition = function(u) if u == "b1" then return 1, 0, 0 end return 0, 0, 0 end
      local queue = {}
      Ext.System.ServerCastRequest = { OsirisCastRequests = queue }
      local Fp = { char = "c1", playerCast = true, realRolls = true }
      T_mt = {}
      for _, s in ipairs({ "Projectile_MainHandAttack", "Target_MainHandAttack", "Target_OffhandAttack",
        "Target_DreadAmbusher", "Target_TripAttack" }) do
        G.castRequest(Fp, "c1", s, "b1")
        T_mt[#T_mt + 1] = s .. "=" .. tostring(queue[#queue] and queue[#queue].Targets[1].TargetingType)
      end
      Ext.Stats.Get, Ext.Entity.Get, Osi.GetActionResourceValuePersonal = stats, eget, gres
      Osi.GetPosition, Ext.System.ServerCastRequest = gpos, sys
    """)
    g = L.globals()
    check("off-hand half: a melee cast's second strike (cause Attack) is the off-hand half", g.T_om_two is True)
    check("off-hand half: a missed melee off-hand half (its 0 damage row) counts too", g.T_om_miss is True)
    check("off-hand half: one strike with its rider row is no off-hand half", g.T_om_one is False)
    check("off-hand half: another target's row or a status tick is no second strike", g.T_om_other is False)
    check("off-hand half: a hit row that is the cast's last attack and not its first is the off-hand half",
          g.T_om_hit is True and g.T_om_hit1 is False, f"{g.T_om_hit} {g.T_om_hit1}")
    check("off-hand half: a ranged off-hand row (cause Offhand) still counts", g.T_om_ranged is True)
    ok = seq(g.T_os_ok, 3)
    check("spent: a toggled melee attack whose halves both came as cause Attack owes and spent the bonus action",
          ok == ["done", "fired", True], str(ok))
    ow = seq(g.T_os_owed, 3)
    check("spent: a melee off-hand half that struck with no bonus action spent is a cost mismatch",
          ow[0] == "fired" and ow[1] == "costs" and "BonusActionPoint" in str(ow[2]), str(ow))
    mt = lst(g.T_mt)
    check("player cast: a melee weapon attack never goes out as a Projectile (its own SpellType, Target)",
          mt == ["Projectile_MainHandAttack=Projectile", "Target_MainHandAttack=Target", "Target_OffhandAttack=Target",
                 "Target_DreadAmbusher=Target", "Target_TripAttack=Target"], str(mt))


def impact_wait_tests(L):
    """The next player-path request waits until the last attack landed: its damage row on its target, a quiet spell
    with no new row, the off-hand half of a toggled attack too; a cast at the character itself, one that is no attack
    and the time cap hold nothing. The step loop asks before every request."""
    L.execute(r"""
      local G = GAUNTLET
      local stats = Ext.Stats.Get
      Ext.Stats.Get = function(s)
        if s == "Projectile_DreadAmbusher" then return { SpellType = "Projectile", SpellFlags = {} } end
        if s == "Target_HuntersMark" then return { SpellType = "Target", SpellFlags = {} } end
        if s == "Target_MainHandAttack" then return { SpellType = "Target", SpellFlags = { "IsAttack" } } end
      end
      G.t0 = 0
      local function F(spell, extra)
        local P = { who = "c1", target = "b1", spell = spell, dmg0 = 0, hits0 = 0 }
        for k, v in pairs(extra or {}) do P[k] = v end
        return { lastCast = { P = P, t = 1000 } }
      end
      local function row(t, amount, target, cause)
        return { source = "c1", owner = "c1", target = target or "b1", t = t, amount = amount, cause = cause or "Attack" }
      end
      -- no damage row yet: wait; the row just in: wait; IMPACT_QUIET_MS after it: go (and forget the cast)
      local f = F("Projectile_DreadAmbusher")
      T_iw_none = G.impactPending(f, 1300, {}, {})
      T_iw_fresh = G.impactPending(f, 1400, { row(1300, 20) }, {})
      T_iw_quiet = G.impactPending(f, 1300 + G.IMPACT_QUIET_MS, { row(1300, 20) }, {})
      T_iw_forgot = f.lastCast == nil
      -- a miss's 0 row lands the cast too; another target's row does not
      T_iw_miss = G.impactPending(F("Projectile_DreadAmbusher"), 1600, { row(1300, 0) }, {})
      T_iw_other = G.impactPending(F("Projectile_DreadAmbusher"), 1600, { row(1300, 20, "e9") }, {})
      -- a rider row after the hit restarts the quiet spell
      T_iw_rider = G.impactPending(F("Target_MainHandAttack"), 1600, { row(1300, 20), row(1500, 6) }, {})
      -- a toggled attack waits for its off-hand half (or OFFHAND_MS)
      local dual = { toggled = true, dual = { { kind = "BonusActionPoint", n = 1 } } }
      T_iw_dual_wait = G.impactPending(F("Target_MainHandAttack", dual), 1600, { row(1300, 20) }, {})
      T_iw_dual_done = G.impactPending(F("Target_MainHandAttack", dual), 2000, { row(1300, 20), row(1700, 9, nil, "Offhand") }, {})
      -- nothing to wait for: a self cast, a spell that is no attack, the cap
      T_iw_self = G.impactPending(F("Projectile_DreadAmbusher", { target = "c1" }), 1100, {}, {})
      T_iw_mark = G.impactPending(F("Target_HuntersMark"), 1100, {}, {})
      T_iw_cap = G.impactPending(F("Projectile_DreadAmbusher"), 1000 + G.IMPACT_MAX_MS, {}, {})
      T_iw_nolast = G.impactPending({}, 1100, {}, {})
      Ext.Stats.Get = stats
    """)
    g = L.globals()
    check("impact wait: no damage row from the attack yet -> the next request waits", g.T_iw_none is True)
    check("impact wait: the row just came -> still waits", g.T_iw_fresh is True)
    check("impact wait: IMPACT_QUIET_MS after the row -> the next request goes, the cast forgotten",
          g.T_iw_quiet is False and g.T_iw_forgot is True, f"{g.T_iw_quiet} {g.T_iw_forgot}")
    check("impact wait: a miss's 0 row lands the attack", g.T_iw_miss is False)
    check("impact wait: another target's row is not the attack's", g.T_iw_other is True)
    check("impact wait: a rider row after the hit restarts the quiet spell", g.T_iw_rider is True)
    check("impact wait: a toggled attack waits for its off-hand half, then goes",
          g.T_iw_dual_wait is True and g.T_iw_dual_done is False, f"{g.T_iw_dual_wait} {g.T_iw_dual_done}")
    check("impact wait: a self cast, a spell that is no attack, the time cap and no last cast hold nothing",
          [g.T_iw_self, g.T_iw_mark, g.T_iw_cap, g.T_iw_nolast] == [False] * 4,
          str([g.T_iw_self, g.T_iw_mark, g.T_iw_cap, g.T_iw_nolast]))
    with open(os.path.join(G_DIR, "gauntlet.lua"), encoding="utf-8") as fh:
        src = fh.read()
    check("impact wait: the step loop asks before every request and a confirmed player cast is remembered",
          "if G.impactPending(F, t, G.dmg, G.hits) then F.next = t + G.POLL_MS; return end" in src
          and "if P.player then F.lastCast = { P = P, t = t } end" in src)


def rest_reset_tests(L):
    """Between runs the character is reset like a long rest: the game's restoration status (its ResetCooldowns), every
    cooldown written ready and the entries dropped, so Action Surge and per-rest item spells are ready for the next
    run. A rest cooldown reads -1 until the rest and is a running cooldown. The setup check reads the plan's
    once-per-rest steps ready."""
    L.execute(r"""
      local G = GAUNTLET
      local eget, apply = Ext.Entity.Get, Osi.ApplyStatus
      local function cds()
        return { { SpellId = { Prototype = "Shout_ActionSurge" }, Cooldown = -1, CooldownType = "UntilShortRest" },
          { SpellId = { Prototype = "Target_Item" }, Cooldown = -1, CooldownType = "UntilRest" },
          { SpellId = { Prototype = "Target_Turn" }, Cooldown = 2, CooldownType = "OncePerTurn" } }
      end
      local E = { SpellBookCooldowns = { Cooldowns = cds() }, ActionResources = { Resources = {} },
        Replicate = function() end }
      Ext.Entity.Get = function() return E end
      local applied = {}
      Osi.ApplyStatus = function(_, st, d) applied[#applied + 1] = st .. ":" .. tostring(d) end
      T_rr_before = { G._onCooldown("c1", "Shout_ActionSurge"), G._onCooldown("c1", "Target_Turn"),
        G._onCooldown("c1", "Missing") }
      G.refill("c1", "long")
      T_rr_long = { #E.SpellBookCooldowns.Cooldowns, G._onCooldown("c1", "Shout_ActionSurge"), applied[1] }
      -- a short rest: the short-rest and turn cooldowns ready, a long-rest one kept running
      E.SpellBookCooldowns.Cooldowns = cds()
      applied = {}
      G.refill("c1", "short")
      local c = E.SpellBookCooldowns.Cooldowns
      local function cd(i) return c[i] and c[i].Cooldown or "gone" end
      T_rr_short = { #c, cd(1), cd(2), cd(3), #applied }
      -- the setup check: the plan's Action Surge must be ready
      local plan = { rounds = { { { spell = "Shout_ActionSurge", group = "free", per = "short" },
        { spell = "Projectile_MainHandAttack", group = "action" } } }, steady = {} }
      T_rr_spells = G.restSpells(plan)
      E.SpellBookCooldowns.Cooldowns = cds()
      local bad = G.setupCheck({ char = "c1", plan = plan }, {}, "start")
      E.SpellBookCooldowns.Cooldowns = {}
      local good = G.setupCheck({ char = "c1", plan = plan }, {}, "start")
      local function ready(sc)
        for _, m in ipairs(sc.mismatches) do if m.field == "spell Shout_ActionSurge ready" then return false end end
        return true
      end
      T_rr_check = { ready(bad), ready(good) }
      Ext.Entity.Get, Osi.ApplyStatus = eget, apply
    """)
    g = L.globals()
    b = seq(g.T_rr_before, 3)
    check("rest reset: a rest cooldown (-1 until the rest) and a turn cooldown are running, no entry is ready",
          b == [True, True, False], str(b))
    lg = seq(g.T_rr_long, 3)
    check("rest reset: between runs every cooldown is reset and the entries dropped, the restoration status applied",
          lg[0] == 0 and lg[1] is False and lg[2] == "TUT_RESTORATION:0", str(lg))
    sh = seq(g.T_rr_short, 5)
    check("rest reset: a short rest readies short-rest and turn cooldowns, keeps a long-rest one, no status",
          sh == [3, 0, -1, 0, 0], str(sh))
    check("rest reset: the plan's once-per-rest steps listed", lst(g.T_rr_spells) == ["Shout_ActionSurge"],
          str(lst(g.T_rr_spells)))
    rc = seq(g.T_rr_check, 2)
    check("setup: Action Surge still on cooldown fails the setup check; ready passes", rc == [False, True], str(rc))


def toggle_tests(L):
    """Toggled passives: prep sets each one the spec names to the model's state (Osi.TogglePassive, else the field
    written), the setup check reads the state back, the run puts the character's own state back."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local pas = { { Passive = { PassiveId = "Sharpshooter_AllIn", ToggledOn = false } },
                    { Passive = { PassiveId = "GreatWeaponMaster_BonusDamage", ToggledOn = true } } }
      for _, p in ipairs(pas) do p.Replicate = function() end end
      Ext.Entity.Get = function() return { PassiveContainer = { Passives = pas } } end
      Osi.TogglePassive = function(_, id)
        for _, p in ipairs(pas) do if p.Passive.PassiveId == id then p.Passive.ToggledOn = not p.Passive.ToggledOn end end
      end
      T_set = G.setToggles("c1", { Sharpshooter_AllIn = true, GreatWeaponMaster_BonusDamage = true })
      T_on = pas[1].Passive.ToggledOn
      local sc = G.setupCheck({ char = "c1" }, { toggles = { Sharpshooter_AllIn = true } }, "start")
      T_ok = 0
      for _, m in ipairs(sc.mismatches) do if m.field:find("^toggle") then T_ok = T_ok + 1 end end
      T_rest = G.togglesRestore()
      T_back = pas[1].Passive.ToggledOn
      Osi.TogglePassive = function() error("no such call") end
      G.setToggles("c1", { Sharpshooter_AllIn = true })
      T_written = pas[1].Passive.ToggledOn
      pas[1].Passive.ToggledOn = false
      local bad = G.setupCheck({ char = "c1" }, { toggles = { Sharpshooter_AllIn = true, Missing_P = false } }, "start")
      T_bad = {}
      for _, m in ipairs(bad.mismatches) do if m.field:find("^toggle") then T_bad[#T_bad + 1] = m.field end end
      table.sort(T_bad)
      G.savedToggles = nil
      Osi.TogglePassive = nil
      Ext.Entity.Get = function() return nil end
    """)
    g = L.globals()
    check("toggles: a passive off is switched on, one already on is left alone",
          g.T_on is True and g.T_set.Sharpshooter_AllIn.method == "TogglePassive" and
          g.T_set.GreatWeaponMaster_BonusDamage.method is None, str(g.T_on))
    check("toggles: the setup check reads the state back (no mismatch when it is the model's)", g.T_ok == 0, str(g.T_ok))
    check("toggles: the character's own state is put back when the run ends", g.T_rest == 1 and g.T_back is False)
    check("toggles: without Osi.TogglePassive the field is written", g.T_written is True)
    check("toggles: a wrong or unreadable state is a mismatch",
          lst(g.T_bad) == ["toggle Missing_P", "toggle Sharpshooter_AllIn"], str(lst(g.T_bad)))


def carry_over_tests(L):
    """Carried state: prep ends the concentration, takes HUNTERS_MARK off every creature and every status outside the
    character's baseline off the character; the setup check fails a concentration or a carried status at the start."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.baseStatuses = nil
      local st = { c1 = { a = "BASE_STATUS" }, x = { a = "HUNTERS_MARK" } }
      local conc = {}
      local ents = {}
      for _, u in ipairs({ "c1", "x" }) do ents[#ents + 1] = { Uuid = { EntityUuid = u } } end
      Ext.Entity.GetAllEntitiesWithComponent = function() return ents end
      Ext.Entity.Get = function(u)
        return { StatusContainer = { Statuses = st[u] or {} },
          Concentration = conc[u] and { SpellId = { Prototype = conc[u] } } or nil }
      end
      Osi.HasActiveStatus = function(u, s)
        for _, v in pairs(st[u] or {}) do if v == s then return 1 end end
        return 0
      end
      local removed, applied = {}, {}
      Osi.RemoveStatus = function(u, s)
        removed[#removed + 1] = u .. ":" .. s
        for k, v in pairs(st[u] or {}) do if v == s then st[u][k] = nil end end
      end
      Osi.ApplyStatus = function(u, s) applied[#applied + 1] = s end
      T_first = G.removeCarryOver("c1")
      T_removed0 = #removed
      st.c1.b, st.c1.c, st.c1.d = "SCARLET_STACK", "AI_HELPER_X", "HUNTERS_MARK"
      st.x.a = "HUNTERS_MARK"
      conc.c1 = "Target_HuntersMark"
      T_rm = G.removeCarryOver("c1")
      T_applied = applied
      -- the start: concentration still held, a carried status, an item status (allowed), a technical one (ignored)
      st.c1 = { a = "BASE_STATUS", b = "MAG_CARRIED", c = "MAG_ITEM_STATUS", d = "AI_HELPER_Y" }
      local sc = G.setupCheck({ char = "c1" }, { item_statuses = { { status = "MAG_ITEM_STATUS", item = "R" } } }, "start")
      T_f = {}
      for _, m in ipairs(sc.mismatches) do T_f[#T_f + 1] = m.field end
      table.sort(T_f)
      G.baseStatuses = nil
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Ext.Entity.Get = function() return nil end
      Osi.HasActiveStatus, Osi.RemoveStatus, Osi.ApplyStatus = nil, nil, nil
    """)
    g = L.globals()
    check("carry-over: the first prep keeps the character's own statuses as its baseline",
          g.T_first.baseline == 1 and g.T_removed0 == 1, f"{g.T_first.baseline} {g.T_removed0}")
    rm = lst(g.T_rm.removed)
    check("carry-over: the concentration is ended by the game's own status",
          g.T_rm.concentration == "Target_HuntersMark" and "AI_HELPER_BREAKCONCENTRATION" in lst(g.T_applied))
    check("carry-over: HUNTERS_MARK comes off every creature, statuses outside the baseline off the character",
          "HUNTERS_MARK on x" in rm and "SCARLET_STACK on the character" in rm and
          "HUNTERS_MARK on the character" in rm and not any("AI_HELPER_X" in r for r in rm), str(rm))
    check("carry-over: the setup check fails a held concentration and a carried status (not the set's own, not technical)",
          lst(g.T_f) == ["no carried status MAG_CARRIED", "no concentration"], str(lst(g.T_f)))


def crit_tests(L):
    """Critical hits: an enemy carrying CriticalHit(...,Never) in a passive, status or boost is cleared of what can be
    taken off; the setup check reads what is left, and an enemy's statuses at the start."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local pas = { { Passive = { PassiveId = "NoCrits_P" } }, { Passive = { PassiveId = "Fine_P" } } }
      local sts = { "IMMUNE_TO_CRITS" }
      Ext.Stats.Get = function(id)
        if id == "NoCrits_P" then return { Boosts = "CriticalHit(AttackTarget,Success,Never)" } end
        if id == "IMMUNE_TO_CRITS" then return { Boosts = "CriticalHit(AttackTarget,Success,Never);AC(1)" } end
        return { Boosts = "AC(1)" }
      end
      Ext.Entity.Get = function(u)
        if u == "e1" then return { PassiveContainer = { Passives = pas }, StatusContainer = { Statuses = sts },
          BoostsContainer = { Boosts = {} } } end
      end
      local gone = {}
      Osi.RemovePassive = function(_, id) gone[#gone + 1] = id; table.remove(pas, 1) end
      Osi.RemoveStatus = function(_, id) gone[#gone + 1] = id; sts[1] = nil end
      T_nb = #G.critBlockers("e1")
      T_fix = G.makeCritable("e1")
      T_gone = gone
      local function enemyFields(sc)
        local out = {}
        for _, m in ipairs(sc.mismatches) do
          if m.field:find("critically") or m.field:find("statuses at start") then out[#out + 1] = m.field end
        end
        table.sort(out)
        return out
      end
      T_after = enemyFields(G.setupCheck({ char = "c1" }, {}, "start", { enemies = { "e1" }, E = {}, encumbered = {} }))
      sts[1] = "SOMETHING"
      pas[#pas + 1] = { Passive = { PassiveId = "NoCrits_P" } }
      T_after2 = enemyFields(G.setupCheck({ char = "c1" }, {}, "start", { enemies = { "e1" }, E = {}, encumbered = {} }))
      Ext.Stats.Get = function() return nil end
      Ext.Entity.Get = function() return nil end
      Osi.RemovePassive, Osi.RemoveStatus = nil, nil
    """)
    g = L.globals()
    check("crits: blockers found in a passive and a status", g.T_nb == 2, str(g.T_nb))
    check("crits: the blocking passive and status are taken off the enemy",
          sorted(lst(g.T_gone)) == ["IMMUNE_TO_CRITS", "NoCrits_P"], str(lst(g.T_gone)))
    check("crits: a clean enemy passes", len(g.T_after) == 0, str(lst(g.T_after)))
    check("crits: an enemy that cannot be critically hit, or carries a status, fails the setup check",
          lst(g.T_after2) == ["enemy 1 can be critically hit", "enemy 1 statuses at start"], str(lst(g.T_after2)))


def effect_check_tests(L):
    """The setup check's effect fields: worn items' equip passives and statuses, the elixir's statuses, the items'
    unconditional boosts (read from the boost container), the weapon's dice as its sheet row has them, the item spells
    in the book and off cooldown."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.baseStatuses = nil
      local have = { passives = { P_EQ = true }, statuses = { S_EQ = true, ELIXIR_S = true } }
      Osi.HasPassive = function(_, p) return have.passives[p] and 1 or 0 end
      Osi.HasActiveStatus = function(_, s) return have.statuses[s] and 1 or 0 end
      Osi.GetEquippedItem = function(_, slot) if slot == "Ranged Main Weapon" then return "bow" end end
      Osi.GetStatString = function(it) if it == "bow" then return "MAG_Bow" end end
      Ext.Stats.Get = function(id) if id == "MAG_Bow" then return { Damage = "1d8", ["Damage Type"] = "Piercing" } end end
      local boosts = { RollBonus = { { BoostInfo = { Params = { Boost = "RollBonus", Params = "Attack,2" } } } } }
      local cds = { { SpellId = { Prototype = "Projectile_Cooling" }, Cooldown = 1 } }
      Ext.Entity.Get = function(u)
        if u == "c1" then return { BoostsContainer = { Boosts = boosts }, SpellBookCooldowns = { Cooldowns = cds },
          SpellBook = { Spells = { { Id = { Prototype = "Projectile_Ready" } },
            { Id = { Prototype = "Projectile_Cooling" } } } } } end
      end
      G.results = { prep = { items = { { stats = "ELIXIR", got = "used", statuses = { "ELIXIR_S" } } } } }
      local spec = { items = { { slot = "RangedMainHand", stats = "MAG_Bow", weapon = { dice = "1d8", type = "Piercing" } } },
        item_passives = { { passive = "P_EQ", item = "R" } }, item_statuses = { { status = "S_EQ", item = "R" } },
        item_boosts = { { boost = "RollBonus(Attack, 2)", item = "G" } },
        plan = { item_actions = { { spell = "Projectile_Ready" } } } }
      local function fields(sc)
        local out = {}
        for _, m in ipairs(sc.mismatches) do if not m.field:find("^item MeleeMain") and not m.field:find("^item Ranged")
          then out[#out + 1] = m.field end end
        table.sort(out)
        return out
      end
      T_ok = fields(G.setupCheck({ char = "c1" }, spec, "start"))
      have = { passives = {}, statuses = {} }
      spec.items[1].weapon.dice = "1d10"
      spec.item_boosts[2] = { boost = "CharacterWeaponDamage(2)", item = "G" }
      spec.plan.item_actions[2] = { spell = "Projectile_Cooling" }
      spec.plan.item_actions[3] = { spell = "Projectile_Missing" }
      T_bad = fields(G.setupCheck({ char = "c1" }, spec, "start"))
      G.results = {}
      Osi.HasPassive, Osi.HasActiveStatus, Osi.GetEquippedItem, Osi.GetStatString = nil, nil, nil, nil
      Ext.Stats.Get = function() return nil end
      Ext.Entity.Get = function() return nil end
    """)
    g = L.globals()
    check("effects: a set whose effects are all there passes", lst(g.T_ok) == [], str(lst(g.T_ok)))
    check("effects: a missing equip passive / status / elixir status / boost, wrong weapon dice, an item spell missing "
          "or on cooldown are each named",
          lst(g.T_bad) == ["elixir status ELIXIR_S", "item boost CharacterWeaponDamage(2)",
                           "item passive P_EQ", "item spell Projectile_Cooling ready",
                           "item spell Projectile_Missing in the book", "item status S_EQ", "weapon dice RangedMainHand"],
          str(lst(g.T_bad)))


def rider_tests(L):
    """Riders: after the turn that casts them, HUNTERS_MARK must be on the boss (on now or put on this round) and
    DREAD_AMBUSHER on the character (there as the turn started); a missing one fails the run like a refused cast."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      Osi.IsDead = function() return 0 end
      local F = { char = "c1", enemies = { "b1" }, plan = { riders = {
        { round = 1, status = "HUNTERS_MARK", on = "@boss" }, { round = 1, status = "DREAD_AMBUSHER", on = "@self" } } } }
      G.riderCheck(F, { r = 1, turn_statuses = { "DREAD_AMBUSHER" },
        status_log = { { who = "b1", status = "HUNTERS_MARK", on = true } } })
      T_none = G.results.rider_misses
      G.riderCheck(F, { r = 1, turn_statuses = {}, status_log = {} })
      T_miss = #G.results.rider_misses
      T_j = G.judge({ { r = 1, done = { action = true } } }, "rounds done", G.results, { me = "c1" })
      -- the status log: statuses put on the run's creatures are recorded in the round
      G.F = F
      G.fighting, G.round = true, 1
      G.rounds = { { r = 1, casts = {}, actions = {}, done = {} } }
      G._on.status_on("b1", "HUNTERS_MARK", "c1")
      G._on.status_on("stranger", "BLESS", "c1")
      T_log = G.rounds[1].status_log
      G.fighting, G.F = false, nil
      Osi.IsDead = nil
    """)
    g = L.globals()
    check("riders: present riders pass", g.T_none is None)
    causes = lst(g.T_j.causes)
    check("riders: a missing rider fails the run, named",
          g.T_miss == 2 and any("HUNTERS_MARK on @boss" in c for c in causes), str(causes))
    check("riders: statuses put on the run's creatures are logged per round, others not",
          g.T_log is not None and len(g.T_log) == 1 and g.T_log[1].status == "HUNTERS_MARK" and g.T_log[1].on is True)


def hit_log_tests(L):
    """Per-hit record (Script Extender DealDamage): spell, flags (hit / miss / critical), damage per type, the target's
    statuses; only hits of the run's creatures; the first hit's description kept as a probe."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      Ext.Types = { Serialize = function() return { probe = true } end }
      Ext.Entity.Get = function(u) if u == "b1" then return { StatusContainer = { Statuses = { "HUNTERS_MARK" } } } end end
      local function ev(src, tgt, flags)
        return { Caster = { Uuid = { EntityUuid = src } }, Target = { Uuid = { EntityUuid = tgt } },
          SpellId = { Prototype = "Projectile_MainHandAttack" },
          Hit = { TotalDamageDone = 12, EffectFlags = flags, DamageList = { { DamageType = "Piercing", Amount = 12 } } } }
      end
      G.F = { char = "c1", enemies = { "b1" } }
      G.fighting, G.round = true, 3
      G._onHit(ev("c1", "b1", { "Hit", "Critical" }))
      G._onHit(ev("x", "y", { "Hit" }))
      G._onHit(ev("b1", "c1", { "Miss" }))
      T_hits = G.hits
      T_probe = G.results.hit_probe
      G.fighting, G.F = false, nil
      Ext.Types = nil
      Ext.Entity.Get = function() return nil end
    """)
    g = L.globals()
    h = g.T_hits
    check("hits: a hit's spell, total, damage per type, critical flag and the target's statuses are recorded",
          len(h) == 2 and h[1].crit is True and h[1].hit is True and h[1].total == 12 and h[1].spell ==
          "Projectile_MainHandAttack" and h[1].damage[1].amount == 12 and h[1].target_statuses[1] == "HUNTERS_MARK"
          and h[1].r == 3, str(len(h)))
    check("hits: a miss is a miss, hits of other creatures are left out",
          len(h) == 2 and h[2].miss is True and h[2].hit is False)
    check("hits: the first hit's description is kept as a probe", g.T_probe is not None and g.T_probe.probe is True)


def record_gap_tests(L):
    """The record carries what a gap rule needs: the boss's floor position at each of the character's turn starts and
    at the end of each of the boss's turns (another enemy's turn left out), the floor gap after every leave (not only
    one that ended short), and the enemies' saving throws (d20, total, DC, ability, made or not; a failed save takes the
    status its source put on right after it, a made one none; the saves among a hit's condition rolls too)."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset(); G.round = 0
      local t = 0
      local oldNow, gp, hs = Ext.Utils.MonotonicTime, Osi.GetPosition, Osi.HasActiveStatus
      Ext.Utils.MonotonicTime = function() return t end
      G.t0 = 0
      local where = { c1 = { 0, 0, 0 }, b1 = { 9, 1, 2 }, e2 = { 30, 0, 30 } }
      Osi.GetPosition = function(u) local p = where[u]; if p then return p[1], p[2], p[3] end end
      Osi.HasActiveStatus = function() return 0 end
      local F = { char = "c1", enemies = { "b1", "e2" }, cooldown = {}, plan = {}, S = { rounds = 16 }, req = {},
        rounds = 16, started = 1, state = "wait", deadline = 1e12, next = 0 }
      G.F, G.fighting = F, true
      local notify = G.notify
      G.notify = function() end
      t = 100; G._roundStart(F)
      local R = G.rounds[#G.rounds]
      where.b1 = { 4, 1, 1 }
      t = 200; G._on.turn_ended("e2")
      t = 300; G._on.turn_ended("b1")
      t = 400; G._on.turn_ended("c1")
      T_at = R.boss_at
      -- leaves: the floor gap after each one, there or ended short; a hide move none
      local function leave(result, to)
        local Rm = { done = {}, actions = {} }
        local rec = { move = { result = result } }
        G.moveStep(F, { spell = "@move", move_to = to or "@leave_spot", done_key = "leave" }, Rm, rec)
        return rec.move.gap
      end
      T_gap_there = leave("there")
      where.c1 = { 0, 0, 4 }
      T_gap_short = leave("ended short")
      T_gap_hide = leave("there", "@hide_spot")
      -- saves: a failed one, its status just after; a made one; the status before a failed save (the other order);
      -- the character's own save left out; a rider that came with the hit is no save's status
      local function save(tgt, src, ok, nat, total, dc, ab)
        G.onSave({ Target = { Uuid = { EntityUuid = tgt } }, Source = { Uuid = { EntityUuid = src } }, Success = ok,
          Total = total, Ability = ab, RollBonus = 4, Advantage = false, Disadvantage = false, SpellCastUuid = "g1",
          ConditionRoll = { Difficulty = dc, Roll = { Result = { NaturalRoll = nat, Total = total } } } })
      end
      Ext.Types = { Serialize = function() return { probe = true } end }
      t = 1000; save("b1", "c1", false, 7, 11, 16, "Wisdom")
      t = 1010; G._on.status_on("b1", "HUNTERS_MARK", "c1")
      t = 1080; G._on.status_on("b1", "FRIGHTENED", "c1")
      t = 2000; save("b1", "c1", true, 15, 19, 16, "Wisdom")
      t = 2050; G._on.status_on("b1", "PRONE", "c1")
      t = 3000; G._on.status_on("b1", "PRONE", "c1")
      t = 3020; save("b1", "c1", false, 3, 7, 16, "Strength")
      t = 3500; save("c1", "b1", false, 2, 6, 10, "Constitution")
      t = 5000; save("b1", "c1", false, 9, 13, 18, "Constitution")
      t = 5000 + G.SAVE_STATUS_MS + 1; G._on.status_on("b1", "GAPING_WOUND", "c1")
      t = 6000; save("b1", "c1", false, 4, 8, 16, "Strength")
      t = 6050; G._on.status_on("b1", "PRONE", "x9")
      T_saves, T_save_probe = R.saves, G.results.save_probe
      T_hit_saves = G.hitRow({ Hit = { EffectFlags = { "Hit" }, ConditionRolls = {
        { RollType = "AttackRoll", AttackRoll = true, Difficulty = 19, Roll = { Result = { NaturalRoll = 12, Total = 26 } } },
        { RollType = "SavingThrowRoll", SavingThrowRoll = true, Ability = "Constitution", Difficulty = 18,
          Roll = { Result = { NaturalRoll = 5, Total = 9 } } } } } }).saves
      Ext.Types = nil
      G.notify = notify
      Osi.GetPosition, Osi.HasActiveStatus, Ext.Utils.MonotonicTime = gp, hs, oldNow
      G.fighting, G.F, G.rounds = false, nil, {}
    """)
    g = L.globals()
    at = [(g.T_at[i + 1].ev, g.T_at[i + 1].x, g.T_at[i + 1].z) for i in range(len(g.T_at or {}))]
    check("record: the boss's floor position at the character's turn start and at the end of the boss's turn only",
          at == [("own_start", 9, 2), ("boss_end", 4, 1)], str(at))
    check("record: the floor gap to the boss after every leave (there or ended short), none for a hide move",
          g.T_gap_there is not None and abs(g.T_gap_there - math.hypot(4, 1)) < 1e-9 and g.T_gap_short is not None
          and abs(g.T_gap_short - math.hypot(4, 3)) < 1e-9 and g.T_gap_hide is None,
          f"{g.T_gap_there} {g.T_gap_short} {g.T_gap_hide}")
    sv = [(x.roll, x.total, x.dc, x.ability, x.success, x.status) for x in
          (g.T_saves[i + 1] for i in range(len(g.T_saves or {})))]
    check("record: the boss's saves with d20, total, DC, ability and outcome; the character's own left out",
          [r[:5] for r in sv] == [(7, 11, 16, "Wisdom", False), (15, 19, 16, "Wisdom", True),
                                  (3, 7, 16, "Strength", False), (9, 13, 18, "Constitution", False),
                                  (4, 8, 16, "Strength", False)], str(sv))
    check("record: a failed save takes the status its source put on next (a rider skipped, before or after the save, "
          "within the window); a made save, another source's status or one too late none",
          [r[5] for r in sv] == ["FRIGHTENED", None, "PRONE", None, None], str([r[5] for r in sv]))
    check("record: the first save event kept as a probe", g.T_save_probe is not None and g.T_save_probe.probe is True)
    hs_ = g.T_hit_saves
    check("record: a hit's saving throws from its condition rolls, the attack roll left out",
          hs_ is not None and len(hs_) == 1 and hs_[1].roll == 5 and hs_[1].total == 9 and hs_[1].dc == 18
          and hs_[1].ability == "Constitution", str(hs_ and len(hs_)))


def save_log_tests(L):
    """The enemies' rolls from the Osiris RollResult event (roll type, roller, source, result, criticality), filled
    from the SavingThrowRolledEvent component of the same roll whichever comes first (its roller in Target, or in
    Source when an Osiris roll claims it); a failed save takes its source's next status, a made one keeps it apart;
    the registrations' outcome is recorded."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local t = 0
      local oldNow = Ext.Utils.MonotonicTime
      Ext.Utils.MonotonicTime = function() return t end
      G.t0 = 0
      G.F = { char = "c1", enemies = { "b1", "e2" } }
      G.fighting, G.rounds = true, { {} }
      local R = G.rounds[1]
      Ext.Types = { Serialize = function() return { probe = true } end }
      local function comp(tgt, src, ok, nat, total, dc, ab)
        G._on.save({ Target = { Uuid = { EntityUuid = tgt } }, Source = { Uuid = { EntityUuid = src } }, Success = ok,
          Total = total, Ability = ab, RollBonus = 3, Advantage = false, Disadvantage = true, SpellCastUuid = "g7",
          ConditionRoll = { Difficulty = dc, Roll = { Result = { NaturalRoll = nat, Total = total } } } })
      end
      -- a failed save reported by both sources (Osiris first), then its status
      t = 1000; G._on.roll_result("GAMEPLAY_SpellSavingThrowSave", "b1", "c1", 0, 0, "NONE")
      t = 1000; comp("b1", "c1", false, 6, 10, 15, "Constitution")
      t = 1020; G._on.status_on("b1", "GAPING_WOUND", "c1")
      -- a made save: the component first, its roller in Source, claimed by the Osiris roll; a status after it
      t = 2000; comp("c1", "b1", true, 12, 16, 14, "Constitution")
      t = 2010; G._on.roll_result("GAMEPLAY_SpellSavingThrowSave", "b1", "c1", 1, 0, "SUCCESS")
      t = 2100; G._on.status_on("b1", "BLEEDING", "c1")
      -- the character's own roll left out; another enemy's concentration check from Osiris alone
      t = 3000; G._on.roll_result("Concentration", "c1", "c1", 1, 0, "NONE")
      t = 3000; G._on.roll_result("Concentration", "e2", "e2", 1, 0, "NONE")
      -- the same roller's rolls too far apart stay two rows; a component no Osiris roll claims waits apart
      t = 4000; G._on.roll_result("GAMEPLAY_SpellSavingThrowSave", "b1", "c1", 1, 0, "NONE")
      t = 4000 + G.SAVE_MERGE_MS + 1; comp("b1", "c1", true, 18, 22, 15, "Dexterity")
      t = 5000; comp("c1", "b1", false, 2, 6, 15, "Wisdom")
      t = 6000; G._on.roll_result("GAMEPLAY_SpellSavingThrowSave", "b1", "c1", 1, 0, "NONE")
      -- the two sources disagree on the outcome: the Osiris one kept, the row flagged
      t = 7000; G._on.roll_result("GAMEPLAY_SpellSavingThrowSave", "e2", "c1", 0, 0, "NONE")
      t = 7000; comp("e2", "c1", true, 15, 19, 14, "Wisdom")
      T_sl_saves, T_sl_unclaimed, T_sl_probe = R.saves, R.saves_unclaimed, G.results.save_probe
      -- an Osiris handler failure is kept in the record
      local orr = G.onRollResult
      G.onRollResult = function() error("boom") end
      G._on.roll_result("Concentration", "b1", "b1", 1, 0, "NONE")
      G.onRollResult = orr
      T_sl_error = G.results.save_error
      T_sl_listeners = G.saveListeners()
      Ext.Types = nil
      Ext.Utils.MonotonicTime = oldNow
      G.fighting, G.F, G.rounds = false, nil, {}
    """)
    g = L.globals()
    sv = lst(g.T_sl_saves) or []
    rows = [(x.who, x.source, x.roll_type, x.success, x.roll, x.total, x.dc, x.ability, x.osiris, x.component)
            for x in sv]
    check("saves: Osiris rolls of the enemies, filled from the component of the same roll whichever came first",
          rows == [("b1", "c1", "GAMEPLAY_SpellSavingThrowSave", False, 6, 10, 15, "Constitution", True, True),
                   ("b1", "c1", "GAMEPLAY_SpellSavingThrowSave", True, 12, 16, 14, "Constitution", True, True),
                   ("e2", "e2", "Concentration", True, None, None, None, None, True, None),
                   ("b1", "c1", "GAMEPLAY_SpellSavingThrowSave", True, None, None, None, None, True, None),
                   ("b1", "c1", None, True, 18, 22, 15, "Dexterity", None, True),
                   ("b1", "c1", "GAMEPLAY_SpellSavingThrowSave", True, None, None, None, None, True, None),
                   ("e2", "c1", "GAMEPLAY_SpellSavingThrowSave", False, 15, 19, 14, "Wisdom", True, True)], str(rows))
    check("saves: an outcome the two sources disagree on is flagged",
          len(sv) == 7 and sv[6].success_differs is True and sv[0].success_differs is None)
    check("saves: the Osiris result, criticality and the component's bonus and Disadvantage kept",
          len(sv) == 7 and sv[0].result == 0 and sv[1].crit == "SUCCESS" and sv[0].bonus == 3
          and sv[0].disadvantage is True and sv[1].swapped is True and sv[0].swapped is None,
          str([(x.result, x.crit, x.bonus) for x in sv]))
    check("saves: a failed save takes its source's next status, a made one keeps it as status_made",
          len(sv) == 7 and sv[0].status == "GAPING_WOUND" and sv[0].status_made is None
          and sv[1].status is None and sv[1].status_made == "BLEEDING", str([(x.status, x.status_made) for x in sv]))
    un = lst(g.T_sl_unclaimed) or []
    check("saves: a component whose enemy is only its Source waits unclaimed without an Osiris roll",
          len(un) == 1 and un[0].roll == 2 and un[0].who == "b1", str(len(un)))
    check("saves: the first component kept as a probe", g.T_sl_probe is not None and g.T_sl_probe.probe is True)
    check("saves: an Osiris handler failure is recorded", "boom" in str(g.T_sl_error), str(g.T_sl_error))
    ls = g.T_sl_listeners
    check("saves: each registration's outcome recorded (stubbed engine: RollResult yes, no component listener)",
          ls is not None and ls.roll_result is True and ls.saving_throw_event is False,
          str(ls and (ls.roll_result, ls.saving_throw_event)))
    # a reload registers RollResult with its six arguments, once per game session
    with open(os.path.join(G_DIR, "gauntlet.lua"), encoding="utf-8") as fh:
        src = fh.read()
    L.execute(r"""
      T_sl_regs = {}
      T_sl_oldreg, T_sl_oldoc = Ext.Osiris.RegisterListener, Ext.Entity.OnCreate
      Ext.Osiris.RegisterListener = function(name, n, when) T_sl_regs[#T_sl_regs + 1] = name .. "/" .. n .. "/" .. when end
      Ext.Entity.OnCreate = function(name) T_sl_regs[#T_sl_regs + 1] = name end
      GAUNTLET._listeners11, GAUNTLET._listeners12 = nil, nil
    """)
    L.eval("function(s) return load(s)() end")(src)
    L.execute(r"""
      T_sl_after = GAUNTLET.saveListeners()
      Ext.Osiris.RegisterListener, Ext.Entity.OnCreate = T_sl_oldreg, T_sl_oldoc
    """)
    regs = lst(g.T_sl_regs) or []
    check("saves: RollResult registered with its six arguments, the component listener beside it",
          regs == ["SavingThrowRolledEvent", "RollResult/6/after"], str(regs))
    la = g.T_sl_after
    check("saves: both registrations recorded as made", la.roll_result is True and la.saving_throw_event is True)
    check("saves: a fight's record starts with the registrations' outcome",
          "G.results = { prep = prepRes, save_listeners = G.saveListeners() }" in src)


def real_roll_tests(L):
    """Real rolls: the queued Osiris casts of the run's casters lose IgnoreSpellRolls and nothing else (other casters,
    the reaction queue untouched); on by default, off per request or switch; the character joins at the fight's start,
    its summons as they come, both leave at the end (one lane never drops the other's); the run record says whether
    the run rolled."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.realCasters = {}
      local OPTS = "CastOptions(IgnoreSpellRolls,AvoidDangerousAuras,IgnoreCastChecks,IgnoreTargetChecks,NoMovement,IgnoreHasSpell)"
      local function req(u, spell, opts)
        return { Caster = { Uuid = { EntityUuid = u } }, Spell = { Prototype = spell }, CastOptions = opts or OPTS }
      end
      T_names = G.castOptionNames(OPTS)
      T_names2 = G.castOptionNames({ "NoMovement", "IgnoreSpellRolls" })
      local osi = { req("c1", "Projectile_MainHandAttack"), req("b1", "Target_MainHandAttack"),
                    req("c1", "Target_X", "CastOptions(NoMovement)") }
      local reac = { req("c1", "Interrupt_SneakAttack", "CastOptions(IgnoreSpellRolls,IsInterrupt,IsReaction)") }
      Ext.System.ServerCastRequest = { OsirisCastRequests = osi, ReactionStartRequests = reac }
      local F1 = { char = "c1", realRolls = true }
      G.addRealCaster(F1, "c1")
      G._on.cast_requests()
      T_c1 = osi[1].CastOptions
      T_b1 = osi[2].CastOptions
      T_x = osi[3].CastOptions
      T_reac = reac[1].CastOptions
      T_edits = G.realCasters.c1 and G.realCasters.c1.edits
      -- the switch: on by default, off per request or for every run, a person's casts always roll
      T_on = { G.realRollsFor({ mode = "scripted" }), G.realRollsFor({ mode = "scripted", real_rolls = false }),
               G.realRollsFor({ mode = "manual", real_rolls = false }) }
      G.REAL_ROLLS = false
      T_on[4] = G.realRollsFor({ mode = "scripted" })
      G.REAL_ROLLS = true
      -- two lanes: each run drops only its own casters
      local F2 = { char = "c2", realRolls = true }
      G.addRealCaster(F2, "c2")
      G.addRealCaster({ char = "c3", realRolls = false }, "c3")
      G.addRealCaster({ char = "c4", realRolls = true, manual = true }, "c4")
      T_drop1 = G.dropRealCasters(F1)
      T_after1 = { c1 = G.realCasters.c1 ~= nil, c2 = G.realCasters.c2 ~= nil, c3 = G.realCasters.c3 ~= nil,
                   c4 = G.realCasters.c4 ~= nil }
      G.dropRealCasters(F2)
      T_empty = next(G.realCasters) == nil
      Ext.System.ServerCastRequest = nil
    """)
    g = L.globals()
    check("rolls: the cast options read from the engine's text form and from a list",
          lst(g.T_names)[0] == "IgnoreSpellRolls" and len(lst(g.T_names)) == 6 and
          sorted(lst(g.T_names2)) == ["IgnoreSpellRolls", "NoMovement"], str(lst(g.T_names)))
    c1 = lst(g.T_c1) if not isinstance(g.T_c1, str) else [g.T_c1]
    check("rolls: the character's queued Osiris cast loses IgnoreSpellRolls, keeps every other option",
          c1 == ["AvoidDangerousAuras", "IgnoreCastChecks", "IgnoreTargetChecks", "NoMovement", "IgnoreHasSpell"],
          str(c1))
    check("rolls: other casters' requests and the reaction queue are left alone",
          isinstance(g.T_b1, str) and "IgnoreSpellRolls" in g.T_b1 and isinstance(g.T_reac, str) and
          "IgnoreSpellRolls" in g.T_reac and g.T_x == "CastOptions(NoMovement)", f"{g.T_b1} {g.T_reac} {g.T_x}")
    check("rolls: each edit counted per spell", g.T_edits is not None and g.T_edits["Projectile_MainHandAttack"] == 1
          and g.T_edits["Target_X"] is None)
    check("rolls: on by default, off per request or with G.REAL_ROLLS, a person's own casts always roll",
          [g.T_on[i + 1] for i in range(4)] == [True, False, True, False], str([g.T_on[i + 1] for i in range(4)]))
    a1 = g.T_after1
    check("rolls: a run drops only its own casters (the other lane keeps rolling); no caster without rolls or for a "
          "person", a1.c1 is False and a1.c2 is True and a1.c3 is False and a1.c4 is False and g.T_empty is True and
          g.T_drop1.c1["Projectile_MainHandAttack"] == 1, str(dict(a1)))
    # the fight's start adds the character, the run's end removes it and records the run's rolls
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.realCasters = {}
      local saved
      local stringify = Ext.Json.Stringify
      Ext.Json.Stringify = function(t) if t.spec_id then saved = t end return "{}" end
      local F = { char = "c1", enemies = { "e1" }, req = { scenario = "boss", label = "x" }, plan = {}, S = {},
                  started = 1, cooldown = {}, tRun = 0, realRolls = G.realRollsFor({ mode = "scripted" }) }
      G.F = F
      G.goFight(F)
      T_start = G.realCasters.c1 ~= nil
      T_res = G.results.real_rolls
      G._finish(F, "aborted")
      T_end = G.realCasters.c1 == nil
      T_rec = saved and saved.real_rolls
      local F2 = { char = "c1", enemies = { "e1" }, req = { scenario = "boss", label = "y", real_rolls = false },
                   plan = {}, S = {}, started = 1, cooldown = {}, tRun = 0,
                   realRolls = G.realRollsFor({ real_rolls = false }) }
      G.F = F2
      G.goFight(F2)
      T_start2 = G.realCasters.c1 ~= nil
      G._finish(F2, "aborted")
      T_rec2 = saved and saved.real_rolls
      Ext.Json.Stringify = stringify
      G.F = nil
      G.fighting = false
    """)
    g = L.globals()
    check("rolls: the character rolls from the fight's start, not after its end", g.T_start is True and g.T_end is True
          and g.T_res is True, f"{g.T_start} {g.T_end}")
    check("rolls: every run record says whether the run rolled", g.T_rec is True and g.T_rec2 is False and
          g.T_start2 is False, f"{g.T_rec} {g.T_rec2}")
    # a record Stringify refuses even as a JSON-safe copy: a minimal record is written and the run still ends
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local stringify, save, mark = Ext.Json.Stringify, Ext.IO.SaveFile, G.mark
      local written, marks = nil, {}
      Ext.Json.Stringify = function(t) if t.spec_id then error("NaN") end return "min" end
      Ext.IO.SaveFile = function(path, text) if path:find("run_") then written = text end end
      G.mark = function(kind) marks[#marks + 1] = kind end
      local F = { char = "c1", enemies = { "e1" }, req = { scenario = "boss", label = "x" }, plan = {}, S = {},
                  started = 1, cooldown = {}, tRun = 0, realRolls = G.realRollsFor({ mode = "scripted" }) }
      G.F = F
      G.goFight(F)
      G._finish(F, "aborted")
      T_written, T_over = written, table.concat(marks, " "):find("over") ~= nil
      Ext.Json.Stringify, Ext.IO.SaveFile, G.mark = stringify, save, mark
      G.F = nil
      G.fighting = false
    """)
    g = L.globals()
    check("record: refused even as a JSON-safe copy -> a minimal record written, the run still marked over",
          g.T_written == "min" and g.T_over is True, f"{g.T_written} {g.T_over}")
    # a summon joining a scripted run rolls too and gets the run's reaction policy
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      G.realCasters = {}
      local F = { char = "c1", realRolls = true, plan = {} }
      G.summonJoins(F, "sw")
      T_sw = G.realCasters.sw ~= nil
      T_swr = G.results.reactions and G.results.reactions.sw ~= nil
      G.dropRealCasters(F)
    """)
    g = L.globals()
    check("rolls: a summon of the character rolls too and gets the run's reaction policy", g.T_sw is True and
          g.T_swr is True, f"{g.T_sw} {g.T_swr}")


def outcome_tests(L):
    """With real rolls a confirmed cast may miss: it is done (never refused, the round not idle) and gets its outcome
    from the hit log or a 0 damage row; a rider whose own cast missed is not missing; riders that hang on a hit are
    counted over landed hits only; the hit row carries the natural roll, total, AC or DC and advantage."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local R = { r = 1, actions = {
        { spell = "Projectile_MainHandAttack", result = "done", cast_t = 1, target_u = "b1" },
        { spell = "Projectile_MainHandAttack", result = "done", cast_t = 3, target_u = "b1" },
        { spell = "Target_HuntersMark", result = "done", cast_t = 5, target_u = "b1" },
        { spell = "Projectile_X", result = "done", cast_t = 7, target_u = "b1" },
        { spell = "Projectile_Y", result = "failed: refused", cast_t = 9, target_u = "b1" } }, done = { action = true } }
      local hits = { { r = 1, t = 1.5, source = "c1", spell = "Projectile_MainHandAttack", hit = true, crit = true },
                     { r = 1, t = 3.2, source = "c1", spell = "Projectile_MainHandAttack", hit = false, miss = true },
                     { r = 1, t = 3.3, source = "b1", spell = "Target_MainHandAttack", hit = true } }
      local dmg = { { r = 1, t = 7.1, source = "c1", target = "b1", amount = 0 },
                    { r = 1, t = 9.1, source = "c1", target = "b1", amount = 9 } }
      T_tally = G.castOutcomes(R, hits, dmg, "c1")
      T_out = {}
      for i, a in ipairs(R.actions) do T_out[i] = a.outcome or "-" end
      -- a missed attack confirmed by its 0 damage row: done, and the round is no idle round
      T_ev = G.castEvidence({ who = "c1", spell = "Projectile_X", target = "b1", casts0 = 0, dmg0 = 0 }, {},
        { { target = "b1", source = "c1", amount = 0 } })
      T_j = G.judge({ { r = 1, done = { action = true }, actions = { { result = "done", outcome = "miss" } } } },
        "rounds done", { summary = { cast_misses = 0 } }, { me = "c1" })
      -- riders: the rider's cast missed -> no rider expected; it landed -> the missing rider fails the run
      Osi.IsDead = function() return 0 end
      local F = { char = "c1", enemies = { "b1" }, plan = { riders = {
        { round = 1, status = "MARKED", on = "@boss", spell = "Projectile_Y" } } } }
      local Rm = { r = 1, turn_statuses = {}, status_log = {},
        actions = { { spell = "Projectile_Y", result = "done", outcome = "miss" } } }
      G.riderCheck(F, Rm)
      T_rm = G.results.rider_misses
      T_rs = Rm.rider_skips and #Rm.rider_skips
      G.riderCheck(F, { r = 1, turn_statuses = {}, status_log = {},
        actions = { { spell = "Projectile_Y", result = "done", outcome = "hit" } } })
      T_rm2 = G.results.rider_misses and #G.results.rider_misses
      Osi.IsDead = nil
      -- riders on hits: misses carry none
      local rounds = { { r = 1, status_log = { { who = "b1", status = "PASSIVE_HUNTERS_MARK", on = true } },
          reactions_seen = { { who = "c1", interrupt = "Interrupt_SneakAttack" } }, casts = {} },
        { r = 2, status_log = {}, reactions_seen = {}, casts = {} } }
      local hh = { { r = 1, source = "c1", hit = true, flags = "AttackAdvantage,Hit", target_statuses = { "HUNTERS_MARK" } },
        { r = 1, source = "c1", hit = false, miss = true, flags = "AttackAdvantage,Miss", target_statuses = { "HUNTERS_MARK" } },
        { r = 2, source = "c1", hit = true, flags = "AttackAdvantage,Hit", target_statuses = {} },
        { r = 2, source = "b1", hit = true, flags = "AttackAdvantage,Hit", target_statuses = { "HUNTERS_MARK" } } }
      T_hr = G.hitRiders(rounds, hh, "c1")
      -- the hit row: the first condition roll
      G.reset()
      G.F = { char = "c1", enemies = { "b1" } }
      G.fighting, G.round = true, 2
      Ext.Types = { Serialize = function() return {} end }
      G._onHit({ Caster = { Uuid = { EntityUuid = "c1" } }, Target = { Uuid = { EntityUuid = "b1" } },
        SpellId = { Prototype = "Projectile_MainHandAttack" },
        Hit = { EffectFlags = { "Hit", "AttackAdvantage" }, ConditionRolls = { { Difficulty = 16, SavingThrowRoll = false,
          Roll = { Result = { NaturalRoll = 17, Total = 25 }, Roll = { Advantage = true, RollType = "RangedWeaponAttack" } } } } } })
      T_row = G.hits[1]
      G.fighting, G.F = false, nil
      Ext.Types = nil
      -- the summary counts the outcomes
      G.rounds = { { r = 1, actions = {}, attacks = { hit = 2, crit = 1, miss = 3 } } }
      T_sum = G._summarize({ char = "c1", enemies = {} })
    """)
    g = L.globals()
    out = [g.T_out[i + 1] for i in range(5)]
    check("outcome: a critical hit, a miss flag, a cast without hits (none), a 0 damage row (miss), a failed cast "
          "(none)", out == ["crit", "miss", "-", "miss", "-"], str(out))
    t = g.T_tally
    check("outcome: the round's tally", t.crit == 1 and t.miss == 2 and t.hit == 0, f"{t.crit} {t.miss} {t.hit}")
    check("outcome: a missed attack with a 0 damage row is a confirmed cast, its round not idle",
          g.T_ev == "damage" and g.T_j.valid is True, f"{g.T_ev} {lst(g.T_j.causes)}")
    check("riders: a rider whose own cast missed is not missing (noted as skipped); one that landed is",
          g.T_rm is None and g.T_rs == 1 and g.T_rm2 == 1, f"{g.T_rm} {g.T_rs} {g.T_rm2}")
    hr = g.T_hr
    check("riders on hits: Hunter's Mark and Sneak Attack counted over the character's landed hits only",
          hr.hunters_mark.hits == 1 and hr.hunters_mark.rider == 1 and hr.sneak_attack.turns == 2 and
          hr.sneak_attack.rider == 1, f"{hr.hunters_mark.hits} {hr.hunters_mark.rider} {hr.sneak_attack.turns} "
                                      f"{hr.sneak_attack.rider}")
    r = g.T_row
    check("hits: the natural roll, the total, the AC it was rolled against, the roll type and advantage",
          r is not None and r.roll == 17 and r.roll_total == 25 and r.roll_against == 16 and
          r.roll_type == "RangedWeaponAttack" and r.advantage == "true" and r.saving_throw is False,
          str(r and (r.roll, r.roll_total, r.roll_against, r.roll_type, r.advantage)))
    a = g.T_sum.attacks
    check("summary: hits, critical hits and misses of the run", a.hit == 2 and a.crit == 1 and a.miss == 3)


def idle_turn_tests(L):
    """Turns: a party member outside the fight holding a turn is ended at the fight's start and after each of the
    character's turns; the character, its summons and every lane's fighters are left alone. Reactions: an "ask" answer
    is applied as "never" in scripted runs, and a prompt for the character's summon ends the run like the character's."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local active = { c1 = true, p2 = true, p3 = false, lb = true, sw = true }
      local ents = {}
      for u in pairs(active) do
        ents[u] = { TurnBased = setmetatable({}, { __index = function(_, k)
          if k == "IsActiveCombatTurn" then return active[u] end end }) }
      end
      Ext.Entity.Get = function(u) return ents[u] end
      Osi.DB_Players = { Get = function() return { { "c1" }, { "p2" }, { "p3" }, { "lb" }, { "sw" } } end }
      local ended = {}
      Osi.EndTurn = function(u) ended[#ended + 1] = u; active[u] = false end
      G.LANES = { on = true, members = { B = { lb = true } } }
      local F = { char = "c1", enemies = { "e1" }, req = { scenario = "boss" }, plan = {}, S = {}, cooldown = {},
                  summons = { sw = true }, realRolls = false, tRun = 0 }
      G.F = F
      G.goFight(F)
      T_start = ended
      ended = {}
      active.p2 = true
      -- after the character's turn ("ending"): its own turn and the idle member's are ended
      G.round = 1
      G.rounds = { { r = 1, actions = {}, casts = {}, done = { action = true }, cast_fails = {}, reactions_seen = {} } }
      F.state, F.next = "ending", 0
      G.step(F, 10)
      T_round = ended
      T_log = G.results.idle_turns_ended
      T_att = G.rounds[1].attacks
      G.LANES = nil
      Osi.DB_Players, Osi.EndTurn = nil, nil
      Ext.Entity.Get = function() return nil end
      G.F, G.fighting = nil, false
    """)
    g = L.globals()
    st, rd = lst(g.T_start), lst(g.T_round)
    check("turns: at the fight's start only the idle party member's turn is ended (not the character, its summon, "
          "the other lane's fighter)", st == ["p2"], str(st))
    check("turns: after the character's turn the idle member's turn is ended too, and logged",
          "p2" in rd and "c1" in rd and "lb" not in rd and "sw" not in rd and len(g.T_log) == 2, str(rd))
    check("outcome: each round's casts get their outcomes as the turn ends", g.T_att is not None)
    L.execute(r"""
      local G = GAUNTLET
      local store = { Interrupt_Charm = { "Ask", "Enabled" } }
      local prefs
      prefs = setmetatable({}, {
        __index = function(_, k) local f = store[k]; return f and ("InterruptInteractionTypes(" .. table.concat(f, ",") .. ")") end,
        __newindex = function(_, k, v) store[k] = v end,
        __pairs = function() local k; return function() k = next(store, k); if k then return k, prefs[k] end end end })
      local ent = { InterruptPreferences = { Preferences = prefs }, Replicate = function() end }
      Ext.Entity.Get = function(u) if u == "c1" then return ent end end
      Osi.GetDisplayName = function() return nil end
      G.savedReactions = nil
      local rep = G.reactionsApply({ reactions = { Interrupt_Charm = "ask" } }, { "c1" })
      T_ask = table.concat(store.Interrupt_Charm, ",")
      T_askpol = rep.c1.reactions.Interrupt_Charm
      G.reactionsRestore()
      -- a prompt for the summon
      Ext.Entity.GetAllEntitiesWithComponent = function()
        return { { InterruptActionState = { SpellCastGuid = "g", Actions = { { Observer = { Uuid = { EntityUuid = "sw" } },
          Interrupt = { InterruptData = { Interrupt = "Interrupt_X" } } } } } } }
      end
      G.results = {}
      T_sguard = G.reactionGuard({ char = "c1", summons = { sw = true } })
      Ext.Entity.GetAllEntitiesWithComponent = function() return {} end
      Ext.Entity.Get = function() return nil end
      Osi.GetDisplayName = nil
    """)
    g = L.globals()
    check("reactions: an 'ask' answer is applied as 'never' (a prompt would stop the scripted cast)",
          g.T_ask == "" and g.T_askpol == "never", f"{g.T_ask!r} {g.T_askpol}")
    check("reactions: a prompt for the character's summon ends the run too", g.T_sguard == "Interrupt_X",
          str(g.T_sguard))


def real_rolls_py_tests(R):
    """run.py: every record says whether it rolled (older ones did not); --repeats and the report count only runs of
    the same kind; --no-real-rolls and --old-cast-path go into the request."""
    check("rolls: older records ran without rolls, new ones say so",
          R.rolls_of({}) is False and R.rolls_of({"real_rolls": True}) is True and
          R.rolls_of({"req": {"real_rolls": True}}) is True and R.rolls_of({"real_rolls": False}) is False)
    A_ = type("A", (), {"arena": "x", "rounds": 16, "lanes": None})
    p = {"specs": {"a": {"act": 3}}}
    on, off = A_(), A_()
    off.no_real_rolls = True
    old = A_()
    old.old_cast_path = True
    check("player cast: requests leave the path to the harness unless --old-cast-path",
          R._req(on, 0, p, "a", "boss", False, "c")["player_cast"] is None
          and R._req(old, 0, p, "a", "boss", False, "c")["player_cast"] is False)
    check("rolls: requests roll unless --no-real-rolls", R._req(on, 0, p, "a", "boss", False, "c")["real_rolls"] is True
          and R._req(off, 0, p, "a", "boss", False, "c")["real_rolls"] is False)
    d = tempfile.mkdtemp(prefix="gauntlet_rolls_")
    try:
        pr = {"char": "c", "build": "cb", "act": 3, "specs": {x: {"set": f"c {x}", "act": 3} for x in ("a", "b")}}
        res = os.path.join(d, "res.jsonl")
        with open(res, "w", encoding="utf-8") as f:
            old = _sched_rec(pr, "a", [60.0] * 16)
            old.pop("real_rolls")
            f.write(json.dumps(dict(old, pair=0, side="a")) + "\n")
            f.write(json.dumps(dict(_sched_rec(pr, "a", [50.0] * 16), pair=0, side="a")) + "\n")
        n_on = len(R.prior_runs(res, 0, pr, ["boss"])["a"])
        n_off = len(R.prior_runs(res, 0, pr, ["boss"], False)["a"])
        check("rolls: --repeats counts only runs of the same kind", n_on == 1 and n_off == 1, f"{n_on} {n_off}")
        pairs = [_pair("x", 100, 101)]
        sp, rs = os.path.join(d, "specs.json"), os.path.join(d, "r.jsonl")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(pairs, f)
        with open(rs, "w", encoding="utf-8") as f:
            f.write(json.dumps(_rec(0, "a", [100] * 16)) + "\n")
            old = _rec(0, "b", [777] * 16)
            old.pop("real_rolls")
            f.write(json.dumps(old) + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.main(["--report", rs, "--specs", sp])
        text = buf.getvalue()
        check("rolls: the report leaves runs without rolls out, and says so",
              "777" not in text and "1 run(s) without real rolls left out" in text, text[-300:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def plan_effect_tests(P):
    """plan.py: Dread Ambusher's own free attack first in round 1 (not an action-bound attack), riders listed, spells a
    status grants not expected in the book, toggles in the model's state, action item spells only when the model's
    plan uses them, the items' equip passives / statuses / boosts and weapon dice for the setup check."""
    from types import SimpleNamespace as NS
    model = NS(slots=lambda cl: [])
    st = NS(plan={"mode": "ranged", "hunters_mark": True, "dread": True}, classes={"Ranger": 5, "Fighter": 3},
            sheet={"nAtt": 2}, subs={}, level=8)
    core = P.core_plan(model, st, {})
    r1 = core["rounds"][0]
    check("plan: Dread Ambusher's own free attack comes first in round 1, needing no action",
          r1[0]["spell"] == "Projectile_DreadAmbusher" and r1[0]["cost"] == "free" and "requires" not in r1[0],
          str([a["spell"] for a in r1]))
    check("plan: a melee build's Dread Ambusher attack is the melee one",
          P.core_plan(model, NS(plan={"mode": "melee", "dread": True}, classes={"Ranger": 3}, sheet={"nAtt": 1},
                                subs={}, level=3), {})["rounds"][0][0]["spell"] == "Target_DreadAmbusher")
    check("plan: riders listed for the round that casts them",
          sorted((r["status"], r["round"], r["on"]) for r in core["riders"]) ==
          [("DREAD_AMBUSHER", 1, "@self"), ("HUNTERS_MARK", 1, "@boss")], str(core["riders"]))
    check("plan: a spell a status grants is not expected in the book", "Projectile_DreadAmbusher" not in
          P.plan_spells(core) and "Projectile_MainHandAttack" in P.plan_spells(core))
    pred = NS(plan_events=[{"spell": "Zone_Kept", "n": 0.2, "dropped": False},
                           {"spell": "Projectile_RoaringShot", "n": 0.2, "dropped": True, "toggle": True}])
    check("plan: an action item spell the model dropped or never used is not intended",
          P.model_intends(pred, "Zone_Kept") is True and P.model_intends(pred, "Projectile_RoaringShot") is False and
          P.model_intends(pred, "Target_Topple") is False and P.model_intends(NS(), "X") is None)
    tg, src = P.model_toggles(["Sharpshooter_AllIn", "Other"], pred, ["Sharpshooter_AllIn"])
    check("plan: toggles from the test plan", tg == {"Sharpshooter_AllIn": True} and src == "test plan", str(tg))
    pred2 = NS(plan_events=[{"spell": None, "n": 2.0, "dropped": False, "toggle": False}])
    tg2, src2 = P.model_toggles(["GreatWeaponMaster_BonusDamage"], pred2)
    check("plan: toggles from the model's events when no test plan names them",
          tg2 == {"GreatWeaponMaster_BonusDamage": False} and src2 == "model events", str(tg2))
    stats = {"MAG_Bow": {"Damage": "1d8", "Damage Type": "Piercing", "PassivesOnEquip": "P1",
                         "BoostsOnEquipMainHand": "UnlockSpell(Projectile_Roar)", "Boosts": "IF(x):AC(1);Initiative(1)",
                         "StatusOnEquip": "S1"},
             "P1": {"Boosts": "RollBonus(Attack, 2);IF(Combat()):CharacterWeaponDamage(1d6)"},
             "S1": {"OnApplyFunctors": "ApplyStatus(S2,100,-1)"}, "S2": {}}
    items = [{"slot": "RangedMainHand", "stats": "MAG_Bow"}, {"slot": "Elixir", "stats": "E", "use": True}]
    ch = P.item_checks(stats, items, [{"sid": "MAG_Bow", "dmgf": ["1d8 Piercing", "DEX +4"]}])
    check("plan: item checks list equip passives, equip statuses (and what they put on), unconditional boosts",
          [x["passive"] for x in ch["item_passives"]] == ["P1"] and [x["status"] for x in ch["item_statuses"]] ==
          ["S1"] and ch["item_statuses_allowed"] == ["S1", "S2"] and
          sorted(x["boost"] for x in ch["item_boosts"]) ==
          ["Initiative(1)", "RollBonus(Attack, 2)", "UnlockSpell(Projectile_Roar)"], str(ch))
    check("plan: a weapon's dice come from its sheet row",
          items[0].get("weapon") == {"dice": "1d8", "type": "Piercing", "from": "sheet row"}, str(items[0].get("weapon")))


def plan_gap_tests(P):
    """plan.py follows the model's decisions for the boss fight (model_choices): no Trip when every attack's Advantage
    is sure (dice kept for Riposte), the off-hand attack in a free bonus action (yielding, with its value), GWM's
    bonus attack after a critical hit, the extra action while a kept buff's status is on, the action's value for the
    item rule; Hunter's Mark after a concentration buff; filler spells and a concentration zone only when kept and
    known; Destructive Wrath's gain per spell; the respec's spell names."""
    from types import SimpleNamespace as NS
    model = NS(slots=lambda cl: [4, 3, 3, 3, 2, 1], ADV_SURE=0.99, ROUNDS=16)
    stats = {"Shout_Haste": {"SpellProperties": "ApplyStatus(HASTE_X,100,5)"},
             "HASTE_X": {"Boosts": "ActionResource(ActionPoint,1,0)"}}
    st = NS(plan={"mode": "melee", "superiority": True, "hunters_mark": True}, classes={"Fighter": 12, "Ranger": 2},
            sheet={"nAtt": 3}, subs={}, level=12)
    pred = NS(st=NS(sheet={"nAtt": 3}), plan_events=[
        {"name": "attack", "n": 3.0, "dmg": 90.0, "adv": 1.0},
        {"name": "GWM bonus attack", "n": 0.3, "dmg": 9.0},
        {"name": "off-hand attack", "n": 0.9, "dmg": 9.0},
        {"name": "item buff: Bow", "kind": "buff", "spell": "Shout_Haste", "n": 0.06, "dmg": 18.0, "turns": 5,
         "gain": 300.0}])
    ch = P.model_choices(pred)
    core = P.core_plan(model, st, stats, ch)
    steady = core["steady"]
    names = [a["spell"] for a in steady]
    check("plan gaps: no Trip when every attack has Advantage (the dice go to Riposte)",
          "Target_TripAttack" not in names and steady[0]["value"] == 90.0, str(names))
    low = P.model_choices(NS(st=pred.st, plan_events=[dict(pred.plan_events[0], adv=0.5)]))
    check("plan gaps: Trip while Advantage is not sure", P.core_plan(model, st, stats, low)["steady"][0]["spell"] ==
          "Target_TripAttack")
    off = [a for a in steady if a["spell"] == "Target_OffhandAttack"]
    gwm = [a for a in steady if a["spell"] == "Target_GreatWeaponMaster_BonusAttack"]
    check("plan gaps: the off-hand attack in a free bonus action, yielding, with its value",
          off and off[0]["yield_bonus"] and off[0]["value"] == 10.0 and off[0]["granted_by"], str(off))
    check("plan gaps: GWM's bonus attack only with its status, optional",
          gwm and gwm[0]["when_status"] == "GREAT_WEAPON_MASTER_BONUS_ATTACK" and gwm[0]["optional"], str(gwm))
    ext = [a for a in steady if a.get("if_status") == "HASTE_X"]
    check("plan gaps: a kept buff's extra action (with its Extra Attacks) while its status is on",
          len(ext) == 3 and ext[0]["group"] == "action" and ext[0]["done_key"] == "extra" and
          all(a.get("requires") == "extra" for a in ext[1:]), str(ext))
    none = P.core_plan(model, st, stats, P.model_choices(NS(st=pred.st, plan_events=pred.plan_events[:1])))
    check("plan gaps: nothing of it without the model's choice",
          not any(a["spell"] in ("Target_OffhandAttack", "Target_GreatWeaponMaster_BonusAttack") or a.get("if_status")
                  for a in none["steady"]))
    rounds = [list(r) for r in core["rounds"]]
    P._mark_after(core, 6)
    hm = [i + 1 for i, r in enumerate(core["rounds"]) for a in r if a["spell"] == "Target_HuntersMark"]
    check("plan gaps: Hunter's Mark after a concentration buff's turns", hm == [6] and
          any(r["spell"] == "Target_HuntersMark" and r["round"] == 6 for r in core["riders"]) and
          any(a["spell"] == "Target_HuntersMark" for r in rounds for a in r), str(hm))
    cst = NS(plan={"mode": "caster", "cantrip": "Projectile_FireBolt", "nukes": [("Zone_LightningBolt", 5)],
                   "fillers": [("Projectile_ScorchingRay", 3, "Scorching Ray")],
                   "conc_options": [("Wall_WallOfFire", 9, "Wall of Fire")]},
             classes={"Wizard": 12}, sheet={"nAtt": 1}, subs={}, level=12)
    cstats = {"Zone_LightningBolt": {"Level": "3"}, "Zone_LightningBolt_6": {}, "Wall_WallOfFire": {"Level": "4"}}
    cch = P.model_choices(NS(st=cst, plan_events=[
        {"name": "levelled spell", "spell": "Zone_LightningBolt", "n": 0.5, "dmg": 23.0},
        {"name": "filler spell", "spell": "Projectile_ScorchingRay", "n": 0.2, "dmg": 4.0},
        {"name": "cantrip", "spell": "Projectile_FireBolt", "n": 0.1, "dmg": 2.0},
        {"name": "concentration damage", "spell": "Wall_WallOfFire", "n": 0.4, "dmg": 13.0}]))
    cp = P.core_plan(model, cst, cstats, cch, known={"scorching ray", "wall of fire"})
    chain = []
    a = cp["steady"][0]
    while a:
        chain.append(a["spell"])
        a = a.get("alt")
    check("plan gaps: a kept filler between the nuke and the cantrip",
          chain[-2:] == ["Projectile_ScorchingRay", "Projectile_FireBolt"] and chain[0] == "Zone_LightningBolt_6", str(chain))
    # a wall goes at the boss itself: a script's cast of a wall at a single position is refused
    check("plan gaps: a kept concentration zone cast at the boss in round 1",
          cp["rounds"][0][0]["spell"].startswith("Wall_WallOfFire") and not cp["rounds"][0][0].get("at_target_pos")
          and cp["rounds"][0][0]["target"] == "@boss", str(cp["rounds"][0][0]))
    cp2 = P.core_plan(model, cst, cstats, cch, known={"magic missile"})
    a, chain2 = cp2["steady"][0], []
    while a:
        chain2.append(a["spell"])
        a = a.get("alt")
    check("plan gaps: a spell the respec does not know is not planned",
          "Projectile_ScorchingRay" not in chain2 and not cp2["rounds"][0][0]["spell"].startswith("Wall_"), str(chain2))
    bare = P.model_choices(NS(st=cst, plan_events=[
        {"name": "levelled spell", "spell": "Zone_LightningBolt", "n": 0.5, "dmg": 23.0}]))
    cp3 = P.core_plan(model, cst, cstats, bare, known={"scorching ray", "wall of fire"})
    a, chain3 = cp3["steady"][0], []
    while a:
        chain3.append(a["spell"])
        a = a.get("alt")
    check("plan gaps: a filler or zone the model did not keep is not planned",
          "Projectile_ScorchingRay" not in chain3 and not cp3["rounds"][0][0]["spell"].startswith("Wall_"), str(chain3))
    kn = P.known_spell_names([{"picks": ["Spells: Misty Step, Scorching Ray"]},
                              {"picks": ["Spells: Fireball, Lightning Bolt (learn Haste from scrolls)", "Feat: X"]}])
    check("plan gaps: the respec's spell names from its picks",
          kn == {"misty step", "scorching ray", "fireball", "lightning bolt"}, str(kn))
    W = NS(stats={"Chain": {"TooltipDamageList": "DealDamage(10d8,Lightning);DealDamage(2d6,Fire)", "Level": "6"}})
    sys.path.insert(0, os.path.join(LA, "tools", "optimizer"))
    import mech
    check("plan gaps: Destructive Wrath's gain is the lightning dice at their maximum",
          abs(P._dw_gain(W, mech, "Chain", 12) - 35.0) < 1e-9, str(P._dw_gain(W, mech, "Chain", 12)))
    evade_plan_tests(P)


def evade_plan_tests(P):
    """The evade tactic in the plan (the model's choice "evade"): before the attacks, Disengage (Cunning Action) only
    while the boss is in reach, then a move out of its reach (no Hide); where the model found Hide legal, a move to the
    arena's hide spot and Hide after it. The off-hand shots are optional (a dual-wield main-hand attack may take the
    bonus action); the move is no spell for the book. Without the choice none of it. A Thief's second bonus action
    fires an off-hand shot in round 1 beside Hunter's Mark."""
    from types import SimpleNamespace as NS
    model = NS(slots=lambda cl: [], ADV_SURE=0.99, ROUNDS=16)
    st = NS(plan={"mode": "ranged", "offhand": "ranged", "hunters_mark": True}, classes={"Ranger": 5, "Rogue": 4},
            sheet={"nAtt": 2}, subs={"Rogue": "Thief"}, level=9)
    ev = [{"name": "attack", "n": 2.0, "dmg": 50.0, "adv": 1.0},
          {"name": "evade", "kind": "tactic", "n": 0.9375, "hide": True, "dmg": 0.0}]
    ch = P.model_choices(NS(st=NS(sheet={"nAtt": 2}), plan_events=ev))
    core = P.core_plan(model, st, {}, ch)
    steady = core["steady"]
    names = [a["spell"] for a in steady]
    dis = steady[0]
    mv = next((a for a in steady if a.get("move_to")), {})
    hide = next((a for a in steady if a["spell"] == "Shout_Hide_BonusAction"), {})
    shots = [a for a in steady if a["spell"] == "Projectile_OffhandAttack"]
    check("evade: the model's choice read", ch["evade"] == {"turns": 0.9375, "hide": True}, str(ch["evade"]))
    leave = P.core_plan(model, st, {}, P.model_choices(NS(st=NS(sheet={"nAtt": 2}), plan_events=[
        ev[0], dict(ev[1], hide=False)])))["steady"]
    lmv = next((a for a in leave if a.get("move_to")), {})
    check("evade: leaving = Disengage, then a move out of the boss's reach, no Hide",
          leave[0]["spell"] == "Shout_Disengage_CunningAction" and lmv.get("move_to") == "@leave_spot" and
          lmv.get("requires") == "disengage" and not any(a["spell"] == "Shout_Hide_BonusAction" for a in leave),
          str([a["spell"] for a in leave]))
    check("evade: the move is a required step (a move that cannot happen makes the run invalid)",
          not lmv.get("optional"), str(lmv))
    check("evade: Disengage first, only while the boss is in reach, a real bonus-action cast",
          dis["spell"] == "Shout_Disengage_CunningAction" and dis.get("when_adjacent") and dis["group"] == "bonus" and
          dis.get("done_key") == "disengage", str(dis))
    check("evade: then a move to the arena's hide spot, then Hide, before the attacks",
          mv.get("move_to") == "@hide_spot" and mv.get("requires") == "disengage" and
          hide.get("requires") == mv.get("done_key") and hide.get("group") == "bonus" and
          "Shout_Hide_BonusAction" in names and
          names.index("Shout_Hide_BonusAction") < names.index("Projectile_MainHandAttack"), str(names))
    check("evade: the off-hand shots optional", len(shots) == 2 and all(a.get("optional") for a in shots), str(shots))
    check("evade: in round 1 too (when the boss came first)", core["rounds"][0][0]["spell"] ==
          "Shout_Disengage_CunningAction", str([a["spell"] for a in core["rounds"][0]]))
    check("evade: the move is not a spell for the book", P.MOVE not in P.plan_spells(core) and
          "Shout_Hide_BonusAction" in P.plan_spells(core))
    check("plan: off-hand shots optional also without the tactic",
          all(a.get("optional") for a in P.core_plan(model, st, {}, P.model_choices(
              NS(st=NS(sheet={"nAtt": 2}), plan_events=ev[:1])))["steady"] if a["spell"] == "Projectile_OffhandAttack"))
    plain = P.core_plan(model, st, {}, P.model_choices(NS(st=NS(sheet={"nAtt": 2}), plan_events=ev[:1])))
    r1 = [a["spell"] for a in plain["rounds"][0]]
    check("evade: none without the model's choice", not any(a.get("when_adjacent") or a.get("move_to")
                                                           for a in plain["steady"]), str(r1))
    check("plan: a Thief's second bonus action fires an off-hand shot in round 1 beside Hunter's Mark",
          r1[-2:] == ["Target_HuntersMark", "Projectile_OffhandAttack"], str(r1))
    st1 = NS(plan=st.plan, classes=st.classes, sheet=st.sheet, subs={}, level=9)
    one_ba = [a["spell"] for a in P.core_plan(model, st1, {}, P.model_choices(
        NS(st=NS(sheet={"nAtt": 2}), plan_events=ev[:1])))["rounds"][0]]
    check("plan: one bonus action: only Hunter's Mark in round 1",
          one_ba[-1] == "Target_HuntersMark" and "Projectile_OffhandAttack" not in one_ba, str(one_ba))


def item_resource_tests(P):
    """What the worn items add to the class resources (plan.py item_resources): a boost on the item, and a status its
    equip status or a long-rest passive puts on (Amulet of the Devout: one more Channel Divinity charge, reached both
    ways, counted once); turn resources and conditional boosts are left out. Spells the game allows only out of combat
    are never planned."""
    st = {"MAG_Devout": {"PassivesOnEquip": "Devout_Cooldown", "StatusOnEquip": "DEVOUT_TECH"},
          "Devout_Cooldown": {"StatsFunctorContext": "OnLongRest",
                              "StatsFunctors": "RemoveStatus(TRACK);ApplyStatus(DEVOUT_CD, 100, -1)"},
          "DEVOUT_TECH": {"StatusType": "BOOST",
                          "OnApplyFunctors": "IF(not HasStatus('TRACK')):ApplyStatus(DEVOUT_CD, 100, -1)"},
          "DEVOUT_CD": {"StatusType": "BOOST", "Boosts": "ActionResource(ChannelDivinity, 1, 0)"},
          "TRACK": {"StatusType": "BOOST"},
          "MAG_Slot": {"Boosts": "ActionResource(SpellSlot,1,2);ActionResource(Movement,3,0)"},
          "MAG_LowHP": {"Boosts": "IF(HasHPPercentageLessThan(50)):ActionResource(SorceryPoint,1,0)"},
          "MAG_Rest": {"PassivesOnEquip": "Rest_P"},
          "Rest_P": {"StatsFunctorContext": "OnLongRest", "StatsFunctors": "ApplyStatus(SELF, REST_S, 100, -1)"},
          "REST_S": {"Boosts": "ActionResource(SorceryPoint,2,0)"},
          "Shout_ArcaneRecovery": {"Requirements": "!Combat"}, "Target_Shatter_Item": {"Requirements": "Combat"}}
    r = P.item_resources(st, ["MAG_Devout"])
    check("item resources: a status the item's equip status or long-rest passive puts on, counted once",
          [(x["kind"], x["level"], x["n"]) for x in r] == [("ChannelDivinity", 0, 1)], str(r))
    r2 = P.item_resources(st, ["MAG_Slot", "MAG_LowHP", "MAG_Rest"])
    check("item resources: spell slots and a long-rest status's resource; turn and conditional boosts left out",
          sorted((x["kind"], x["level"], x["n"]) for x in r2) == [("SorceryPoint", 0, 2), ("SpellSlot", 2, 1)], str(r2))
    check("item resources: the equip status alone gives the charge (no long-rest passive)",
          [x["n"] for x in P.item_resources(dict(st, MAG_Devout={"StatusOnEquip": "DEVOUT_TECH"}), ["MAG_Devout"])]
          == [1])
    check("item resources: the long-rest passive alone gives the charge (no equip status)",
          [x["n"] for x in P.item_resources(dict(st, MAG_Devout={"PassivesOnEquip": "Devout_Cooldown"}),
                                            ["MAG_Devout"])] == [1])
    check("out of combat: a spell whose Requirements say !Combat is never planned",
          P.unusable_reason(st, "Shout_ArcaneRecovery", None, []) == "cast only out of combat" and
          P.unusable_reason(st, "Target_Shatter_Item", None, []) is None)
    act = P.A("Shout_RadianceOfTheDawn", "action", "@self")
    fc = P.forecast({"rounds": [[act]], "steady": [act]}, {}, r,
                    {"Shout_RadianceOfTheDawn": {"UseCosts": "ActionPoint:1;ChannelDivinity:1"}}, n_rounds=2)
    check("item resources: the forecast spends the items' extra charge", fc == [["Shout_RadianceOfTheDawn"], []],
          str(fc))


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
    st_h = {"MAG_Blade": {"PassivesOffHand": " MAG_Off_P", "PassivesMainHand": " MAG_Main_P", "PassivesOnEquip": "X"},
            "MAG_Off_P": {"Boosts": "UnlockInterrupt(Interrupt_Item_Riposte)"},
            "MAG_Main_P": {"Boosts": "UnlockInterrupt(Interrupt_Item_MainOnly)"}}
    gh = [P.granted_interrupts([], [("MAG_Blade", slot)], st_h) for slot in ("MeleeOffHand", "MeleeMainHand",
                                                                            "RangedOffHand")]
    gh.append(P.granted_interrupts([], ["MAG_Blade"], st_h))
    check("reactions: a weapon's hand passives unlock interrupts only in that hand (Blade of the First Blood's riposte "
          "in the off hand)", gh == [["Interrupt_Item_Riposte"], ["Interrupt_Item_MainOnly"], ["Interrupt_Item_Riposte"],
                                     []], str(gh))
    st_c = {"Target_MenacingAttack": {"UseCosts": "ActionPoint:1", "HitCosts": "SuperiorityDie:1"},
            "Target_Smite_Divine": {"UseCosts": "ActionPoint:1", "HitCosts": "SpellSlotsGroup:1:1:1"},
            "Target_MainHandAttack": {"UseCosts": "ActionPoint:1"}}
    hplan = {"rounds": [[P.A("Target_MenacingAttack", "action", cost="ActionPoint:1;SuperiorityDie:1",
                             alt=P.A("Target_Smite_Divine", "action", cost="SpellSlotsGroup:1:1:1;ActionPoint:1",
                                     alt=P.A("Target_MainHandAttack", "action"))),
                         P.A("Target_MenacingAttack", "free")]],
             "steady": [P.A("Target_MenacingAttack", "action")]}
    P.with_hit_costs(hplan, st_c)
    m0, m1 = hplan["rounds"][0]
    got_hc = [(m0["cost"], m0.get("hit_cost")), (m0["alt"]["cost"], m0["alt"].get("hit_cost")),
              ("hit_cost" in m0["alt"]["alt"]), (m1["cost"], m1.get("hit_cost")), hplan["steady"][0].get("hit_cost")]
    check("hit costs: plan steps carry the spell's HitCosts as hit_cost, and no use cost holds them",
          got_hc == [("ActionPoint:1", "SuperiorityDie:1"), ("ActionPoint:1", "SpellSlotsGroup:1:1:1"), False,
                     ("free", "SuperiorityDie:1"), "SuperiorityDie:1"], str(got_hc))
    fplan = P.with_hit_costs({"rounds": [], "steady": [P.A("Target_MenacingAttack", "action", alt=P.A(
        "Target_MainHandAttack", "action"))]}, st_c)
    fc_h = [r[0] for r in P.forecast(fplan, {}, [{"kind": "SuperiorityDie", "level": 0, "n": 2}], st_c, n_rounds=4)]
    check("hit costs: the forecast needs the die there to cast (every manoeuvre counted as a hit)",
          fc_h == ["Target_MenacingAttack"] * 2 + ["Target_MainHandAttack"] * 2, str(fc_h))
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
              lambda: lanes_py_tests(R), engine_lane_tests, lambda: item_resource_tests(P),
              lambda: plan_effect_tests(P), lambda: scheduler_tests(R), lambda: plan_gap_tests(P),
              lambda: real_rolls_py_tests(R), testmod_tests, no_leak_tests, lambda: v2_stat_tests(R),
              lambda: v2_run_tests(R), engine_popup_tests, no_outside_buff_tests, lambda: roll_report_tests(R), lambda: count_report_tests(R),
              lambda: disadvantage_report_tests(R),
              lambda: split_report_tests(R), phase_call_tests,
              lambda: surge_plan_tests(P), arena_note_tests, lambda: strategy_spec_tests(P, R),
              lambda: strategy_round_tests(R), pointer_tests):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            check("python test block ran", False, repr(e)[:300])


def strategy_spec_tests(P, R):
    """plan.py --strategy: the family's own per-round parts replace expect.boss (the gear model's kept as boss_gear),
    so the report compares a run with the strategy it played, part by part; the riders, the forecast, the hotbar and
    the plan's spells follow the family's rounds (melee: Hunter's Mark and melee attacks, no Disengage left from the
    gear model's evade plan). A 3-round fight with hand-written thx numbers (the search's profile, no game stats)."""
    sys.path.insert(0, os.path.join(LA, "tools", "optimizer"))
    import strategy as SG
    crimson = SG.Weapon("Crimson Mischief", 14, (6, 4, 4), 8, adv_flat=7)
    prof = SG.Profile(melee_main=crimson, melee_off=SG.Weapon("Blade", 14, (4, 4, 4), 8),
                      ranged_main=SG.Weapon("Hellfire", 16, (6, 4), 8, ranged=True),
                      ranged_off=SG.Weapon("Firestoker", 14, (6, 4), 6, ranged=True), riposte=crimson, sup_dice=0,
                      taken_hit=9.0, taken_crit=4.5)
    gear = {"dpr": 104.57, "taken": 3.825, "R": 37.65, "taken_hit": 9.0, "taken_crit": 4.5, "split": True,
            "attacks": 3.188, "hit_rate": 0.8959, "own_dpr": 85.85, "react_attacks": 0.525, "react_dmg": 18.72,
            "sneak_policy": "always"}
    evade = [P.A("Shout_Disengage_CunningAction", "bonus", "@self"), P.A("Projectile_MainHandAttack", "action")]
    flourish = {"spell": "Target_OpeningAttack", "item": "Crimson Mischief", "group": "bonus", "value": 2.5}
    spec = {"plan": {"rounds": [evade], "steady": evade, "reactions": {}, "item_actions": [flourish],
                     "forecast": [["Shout_Disengage_CunningAction", "Projectile_MainHandAttack"]],
                     "riders": [{"round": 1, "status": "DREAD_AMBUSHER", "on": "@self", "why": "Dread Ambusher",
                                 "spell": "Projectile_DreadAmbusher"}]},
            "expect": {"boss": dict(gear)}, "slots": {"1": 4, "2": 2}, "resources": [], "item_resources": [],
            "passives_add": [], "spells_add": ["Shout_Disengage_CunningAction"]}
    old_rounds, old_prof = SG.ROUNDS, SG.profile_from_spec
    SG.ROUNDS = 3
    SG.profile_from_spec = lambda spec_, stats_: prof
    try:
        out = P.strategy_spec(spec, "melee", {})
        want = SG.fight_expect(SG.best_search(prof, "melee")[0])
    finally:
        SG.ROUNDS, SG.profile_from_spec = old_rounds, old_prof
    b, ex = out["expect"]["boss"], out["expect"]
    keys = [mk for _k, _l, mk, _f in R.PARTS if mk]
    check("strategy spec: expect.boss holds the family's parts, the gear model's kept as boss_gear",
          b.get("source") == "strategy melee" and ex.get("boss_gear") == gear and
          all(b.get(k) == want.get(k) for k in keys) and b.get("sneak_policy") == want["sneak_policy"] and
          ex["strategy"]["total"] == want["total"] and [r["mean"] for r in ex["strategy"]["rounds"]] ==
          [r["dmg"] for r in want["rounds"]], str({k: (b.get(k), want.get(k)) for k in keys if b.get(k) != want.get(k)}))
    check("strategy spec: damage taken from the boss's hits in the family's fight, rounds survived scaled with it",
          b.get("taken") == want["taken"] and b["taken"] != gear["taken"] and
          b.get("R") == round(gear["R"] * gear["taken"] / b["taken"], 2), str((b.get("taken"), b.get("R"))))
    game = dict({k: want[mk] for k, _l, mk, _f in R.PARTS if mk}, split=True)
    rows = {r_[0]: r_ for r_ in R.compare_parts(game, b)}
    check("strategy spec: the report compares with the family's parts (melee: 4+ rolls, its riposte rate)",
          rows["attacks"][3] == want["attacks"] > gear["attacks"] and rows["own_dpr"][3] == want["own_dpr"] and
          rows["react_attacks"][3] == want["react_attacks"] and not any(r_[5] for r_ in rows.values()),
          str({k: rows[k][3] for k in ("attacks", "own_dpr", "react_attacks")}))
    fc = [s for r in out["plan"]["forecast"] for s in r]
    spells = {a["spell"] for r in out["plan"]["rounds"] for a in r}
    check("strategy spec: the forecast is the family's rounds (melee attacks, no Disengage)",
          len(out["plan"]["forecast"]) == 16 and "Target_MainHandAttack" in fc and
          "Shout_Disengage_CunningAction" not in fc and set(fc) <= spells | {"@move"}, str(out["plan"]["forecast"][:2]))
    riders = [(r["status"], r["spell"]) for r in out["plan"]["riders"]]
    check("strategy spec: riders and the plan's spells from the family's rounds",
          ("HUNTERS_MARK", "Target_HuntersMark") in riders and all(sp in spells for _s, sp in riders) and
          "Target_MainHandAttack" in out["spells_plan"] and "Projectile_MainHandAttack" not in out["spells_plan"] and
          "Shout_Disengage_CunningAction" in out["spells_add"], str((riders, out["spells_plan"])))


    pol = out["plan"].get("policy") or {}
    dsp = {a["spell"] for d in pol.get("decisions") or [] for a in d["steps"] if not a.get("granted_by")}
    marks = [d for d in pol.get("decisions") or [] if any(a["spell"] == "Target_HuntersMark" for a in d["steps"])]
    check("strategy spec: the policy table (each decision's steps and riders, Hunter's Mark's a concentration one), "
          "plan mode melee with the search's starting distance, every decision's spell in the sheet",
          pol.get("states") and marks and all(any(r_["status"] == "HUNTERS_MARK" and r_["conc"] for r_ in d["riders"])
                                              for d in marks) and out["plan"]["mode"] == "melee" and
          out["plan"]["boss_distance"] == SG.BOSS_START_M and dsp <= set(out["spells_add"]) and
          ("HUNTERS_MARK", True) in [(r_["status"], r_["conc"]) for r_ in out["plan"]["riders"]],
          str((out["plan"].get("mode"), len(pol.get("states") or {}))))
    pd = {"rounds": [[P.A("Target_MainHandAttack", "action")]], "steady": [],
          "policy": {"decisions": [{"steps": [P.A("Target_MenacingAttack", "action", cost="ActionPoint:1;SuperiorityDie:1",
                                                  alt=P.A("Target_MainHandAttack", "action"))]}]}}
    P.with_hit_costs(pd, {"Target_MenacingAttack": {"HitCosts": "SuperiorityDie:1"}})
    m0 = pd["policy"]["decisions"][0]["steps"][0]
    check("strategy spec: a decision played only off the most likely course is in the plan's spells, with its hit costs",
          "Target_MenacingAttack" in P.plan_spells(pd) and m0.get("hit_cost") == "SuperiorityDie:1" and
          m0["cost"] == "ActionPoint:1", str((m0.get("cost"), m0.get("hit_cost"))))
    check("strategy spec: no item spell beside the family's rounds (Flourish took an off-hand half's bonus action)",
          out["plan"]["item_actions"] == [] and any(it.get("spell") == "Target_OpeningAttack"
                                                     for it in out["plan"]["item_skipped"]), str(out["plan"]["item_actions"]))


def strategy_round_tests(R):
    """The rounds against the strategy (run.py round_rows, in the turn list and the report): each round's game damage
    (own turn, reactions) against the expectation for the state the turn started in (the policy's), the round's
    expectation over every course (mean) and the most likely course's (likely) beside it, labelled; a round cut short
    after its own turn (no enemy turn) compared on its own turn only. The turn list shows each turn's state and
    decision, every attack roll of an action (the off-hand half's miss with its d20) and the enemies' rolls. A
    riposte's Sneak Attack is its weapon-type row only, not the weapon's necrotic rider."""
    rec = _roll_rec([(2, 2, 0, [30, 20]), (2, 2, 0, [25, 25]), (2, 1, 0, [40])], react={1: [(27, 0, False)]})
    rec["rounds"][2]["tm"] = {"turn": 2999990}
    pol = {"key": "rnd=1|...", "decision": "melee, Hunter's Mark", "own": 60.0, "own_sd": 10.0, "round": 80.0,
           "round_sd": 20.0}
    for R_ in rec["rounds"]:
        R_["policy"] = dict(pol, key=f"rnd={R_['r']}|conc=mark")
    rec["rounds"][2]["actions"] = [{"spell": "Target_MainHandAttack", "target": "@boss", "result": "done",
                                    "outcome": "hit", "rolls": [
                                        {"cause": "Attack", "outcome": "hit", "nat": 15, "total": 29, "adv": True},
                                        {"cause": "Attack", "outcome": "miss", "nat": 1, "total": 15, "adv": True}]}]
    rec["results"]["summary"]["enemy_rolls"] = {"per_roll": [{"r": 1, "outcome": "miss", "nat": 9, "total": 18,
                                                              "dis": True}]}
    rec["expect"] = {"strategy": {"total": 300.0, "sd": 30.0, "rounds": [
        {"round": i + 1, "mean": m, "mean_sd": 20.0, "dmg": m, "sd": 20.0, "likely": m + 5, "likely_sd": 19.0}
        for i, m in enumerate((90.0, 85.0, 95.0))]}}
    rows = R.round_rows(rec)
    r1, r3 = rows[0], rows[2]
    check("rounds: a full round against its state's round expectation, the reactions apart",
          r1["own"] == 50 and r1["react"] == 34 and r1["game"] == 84 and r1["model"] == 80.0 and
          abs(r1["z"] - 0.2) < 1e-9 and not r1["cut"], str(r1))
    check("rounds: a round cut short after its own turn compared on its own turn only",
          r3["cut"] and r3["game"] == 40 and r3["model"] == 60.0 and r3["model_sd"] == 10.0, str(r3))
    check("rounds: the expectation over every course and the most likely course both given, apart",
          r1["mean"] == 90.0 and r1["likely"] == 95.0, str((r1["mean"], r1["likely"])))
    text = "\n".join(R.round_lines(rec))
    check("rounds: the table says what was compared, the cut round and the fight's expectation",
          "every course" in text and "Most likely course" in text and "cut short" in text and "300.0" in text and
          "Full rounds (1, 2): game 134" in text, text[-400:])
    tl = "\n".join(R.turn_list(rec))
    check("turns: the state and decision, each roll (the off-hand half's miss with its d20) and the enemies' rolls",
          "state: rnd=3|conc=mark -> melee, Hunter's Mark" in tl and "off-hand miss 1 -> 15 Advantage" in tl and
          "main hit 15 -> 29 Advantage" in tl and "enemies' attack rolls: miss 9 -> 18 Disadvantage" in tl, tl[:900])
    no_pol = dict(rec, rounds=[dict(x, policy=None) for x in rec["rounds"]])
    rn = R.round_rows(no_pol)
    check("rounds: without a policy a full round is compared with the round's expectation (mean), a cut one not",
          rn[0]["model"] == 90.0 and rn[2]["model"] is None, str((rn[0]["model"], rn[2]["model"])))
    # a riposte's rows: the weapon's piercing, its necrotic rider in the same burst, Sneak Attack's piercing 57 ms later
    t = 5000000
    rr = {"rounds": [{"r": 1, "tm": {"released": t - 1000}, "rolls": {"per_roll": [{"t": 1}]},
                      "reactions_seen": [{"who": "c1", "interrupt": "Interrupt_SneakAttack", "t": t - 40}]}],
          "dmg": [{"r": 1, "t": 1, "source": "c1", "target": "b1", "amount": 10, "cause": "Attack"},
                  {"r": 1, "t": t + 2, "source": "c1", "target": "b1", "amount": 3, "cause": "Attack",
                   "type": "Necrotic"},
                  {"r": 1, "t": t, "source": "c1", "target": "b1", "amount": 21, "cause": "Attack",
                   "type": "Piercing"},
                  {"r": 1, "t": t + 57, "source": "c1", "target": "b1", "amount": 6, "cause": "Attack",
                   "type": "Piercing"},
                  {"r": 1, "t": t + 60, "source": "c1", "target": "b1", "amount": 2, "cause": "Attack",
                   "type": "Necrotic"}],
          "hits": []}
    rp = R.reaction_parts(rr)
    check("reactions: Sneak Attack is the weapon-type row after the hit, not a necrotic rider row (early or late)",
          rp["rounds"][1]["sneak"] == 6 and rp["rounds"][1]["dmg"] == 32, str(rp))
    d = tempfile.mkdtemp(prefix="gauntlet_rounds_")
    try:
        spec = {"set": "S", "act": 3, "expect": {"boss": {"dpr": 80.0, "split": True}}}
        sp, res = os.path.join(d, "specs.json"), os.path.join(d, "res.jsonl")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump([{"char": "astarion", "build": "b", "act": 3, "specs": {"a": spec}}], f)
        with open(res, "w", encoding="utf-8") as f:
            f.write(json.dumps(dict(rec, run_id="rr1")) + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.main(["--report", res, "--specs", sp])
        rep = buf.getvalue()
        check("report: each run's rounds against the strategy (its states' expectations)",
              "Run rr1, per round against the strategy" in rep and "| 3 | 40 / cut" in rep, rep[-700:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def pointer_tests():
    """Before the popup's Start the mouse pointer goes off the hotbar (no click), so no tooltip stays open in the
    recorded fight: engine.run moves it before the Start eval."""
    import engine as E
    order = []
    old = (E.pointer_off_ui, E.ev, E.write_test)
    try:
        E.pointer_off_ui = lambda *a, **k: order.append("pointer")
        E.release_stuck_buttons = lambda *a, **k: []
        E.write_test = lambda *a, **k: None

        def ev(code, timeout=10.0, side="server"):
            order.append("start" if "GAUNTLET_TEST.start" in code else "eval")
            return "busy"
        E.ev = ev
        try:
            E._run({"rounds": 1}, {}, 5, 0.01, lambda *a: None, 1)
        except E.RunInvalid:
            pass
        check("pointer: moved off the hotbar before the Start", order[:2] == ["pointer", "start"], str(order))
        check("pointer: a share of the screen away from its edges",
              all(0.1 <= v <= 0.9 for v in E.POINTER_AT), str(E.POINTER_AT))
        # a fresh copy of the module: other tests stub the button release on the shared one
        import importlib.util
        spec_ = importlib.util.spec_from_file_location("engine_fresh", E.__file__)
        Ef = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(Ef)
        state = {0x02: True}
        ups = []

        def send_up(flag):
            ups.append(flag)
            state.clear()
        still = Ef.release_stuck_buttons(lambda vk: state.get(vk, False), send_up)
        stuck = Ef.release_stuck_buttons(lambda vk: vk == 0x01, lambda flag: None)
        check("pointer: a held mouse button is released before the Start; one that stays down is reported",
              Ef.mouse_buttons_down(lambda vk: vk == 0x02) == ["right"] and still == [] and ups == [0x0010]
              and stuck == ["left"] and Ef.release_stuck_buttons(lambda vk: False, None) == [], f"{still} {ups} {stuck}")
        check("pointer: the default spot is on the minimap (nothing in the world under it)",
              E.POINTER_AT == (0.897, 0.25), str(E.POINTER_AT))
        check("pointer: LA_POINTER_AT sets the spot; a bad or out-of-range value keeps the default",
              E.pointer_at({"LA_POINTER_AT": "0.5,0.4"}) == (0.5, 0.4) and E.pointer_at({}) == E.POINTER_AT
              and E.pointer_at({"LA_POINTER_AT": "x"}) == E.POINTER_AT
              and E.pointer_at({"LA_POINTER_AT": "0.95,0.5"}) == E.POINTER_AT, str(E.pointer_at({"LA_POINTER_AT": "0.5,0.4"})))
    finally:
        E.pointer_off_ui, E.ev, E.write_test = old


def surge_plan_tests(P):
    """Action Surge in the plan books what the engine charges: Action Surge costs nothing and gives one more action, the
    surge's first attack spends that action, its Extra Attacks are free; the forecast affords all of them in round 1.
    The other steps booked as free cost nothing in the engine either (Dread Ambusher's attack, Extra Attack)."""
    from types import SimpleNamespace as NS
    model = NS(slots=lambda cl: [], ADV_SURE=0.99)
    st = NS(plan={"mode": "ranged", "dread": True}, classes={"Ranger": 5, "Fighter": 3, "Rogue": 4},
            sheet={"nAtt": 2}, subs={}, level=12)
    r1 = P.core_plan(model, st, {})["rounds"][0]
    steps = [(a["spell"], a["group"], a.get("cost"), a.get("requires"), a.get("grants")) for a in r1]
    want = [("Projectile_DreadAmbusher", "free", "free", None, None),
            ("Shout_ActionSurge", "free", "free", None, "ActionPoint:1"),
            ("Projectile_MainHandAttack", "action", None, None, None),
            ("Projectile_MainHandAttack", "free", "free", "action", None),
            ("Projectile_MainHandAttack", "action", None, "surge", None),
            ("Projectile_MainHandAttack", "free", "free", "surge", None)]
    check("surge plan: Action Surge free and gives an action; the surge's first attack spends it, its Extra Attack free",
          steps == want, str(steps))
    stats = {"Projectile_MainHandAttack": {"UseCosts": "ActionPoint:1"}, "Projectile_DreadAmbusher": {"UseCosts": ""},
             "Shout_ActionSurge": {"UseCosts": None}}
    fc = P.forecast({"rounds": [r1], "steady": []}, {}, [], stats, n_rounds=1)
    check("surge plan: the forecast affords every step of the surge round",
          fc[0] == [a["spell"] for a in r1], str(fc[0]))
    one = P.core_plan(model, NS(plan={"mode": "melee"}, classes={"Fighter": 2}, sheet={"nAtt": 1}, subs={}, level=2),
                      {})["rounds"][0]
    check("surge plan: with one attack per action the surge's single attack spends the surge's action",
          [(a["spell"], a["group"]) for a in one] == [("Shout_ActionSurge", "free"), ("Target_MainHandAttack", "action"),
                                                      ("Target_MainHandAttack", "action")], str(one))


def arena_note_tests():
    """The House of Hope arena records its sight survey: the boss sees 16 m, no hide spot, the leave tactic instead."""
    with open(os.path.join(G_DIR, "arenas.json"), encoding="utf-8") as fh:
        a = json.load(fh)["house_of_hope"]
    check("arenas.json: house_of_hope has the boss's sight, no hide spot and the leave tactic note",
          a.get("boss_sight_m") == 16.0 and a.get("hide_spots") == [] and "leave its reach" in a.get("leave_spots_note", "")
          and all(len(p) == 3 for p in a.get("out_of_sight_far", [])) and a.get("out_of_sight_far"), str(a.keys()))


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
    ba = {"levels": [("Ranger", ["Ranger"]), ("Fighter", ["Battle Master",
                                                             "Manoeuvres: Precision Attack, Menacing Attack, Trip Attack"])]}
    plain = P.plan_maneuvers({}, None, ba)
    check("grants: a plain plan (no test plan) takes the manoeuvres of the build's own Builds.lua picks",
          plain == ["PrecisionAttack", "MenacingAttack", "TripAttack"], str(plain))
    tuned = P.plan_maneuvers({"t": {"respec": {"per_level": [{"picks": ["Manoeuvres: Riposte"]}]}}}, "t", ba)
    check("grants: a test plan's own manoeuvres win over the build's", tuned == ["Riposte"], str(tuned))


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


def _sched_rec(p, side, dealt, invalid=None):
    """A run record as the game writes it (spec ids, rounds with their confirmed action, the summary)."""
    return {"mode": "scripted", "scenario": "boss", "haste": False, "real_rolls": True,
            "spec_id": {"build": p["build"], "act": p["act"], "set_name": p["specs"][side]["set"]},
            "rounds": [{"r": r + 1, "done": {"action": True}} for r in range(len(dealt))],
            "results": {"summary": {"dealt": dealt, "taken": [0] * len(dealt), "max_hp": 100}},
            "valid": not invalid, "invalid": invalid or []}


def scheduler_tests(R):
    """run.py's scheduling: rounds compared by their number (a round-1 burst does not swamp the interval), the other
    side's runs read from the results file (a pair decided there is not run again; repeats count the runs there), a
    side whose first run failed for a reason every run would meet is not repeated (recorded), and the lanes take two
    different pairs' sides with different characters at once when their spells allow (a far-reaching set runs alone)."""
    import random as _r
    rnd = _r.Random(3)
    shape = [220.0, 120.0] + [60.0] * 14
    ra = [[(r + 1, v + rnd.uniform(-3, 3)) for r, v in enumerate(shape)] for _ in range(2)]
    rb = [[(r + 1, v + rnd.uniform(-3, 3)) for r, v in enumerate(shape)] for _ in range(2)]
    st, why = R.decisive(ra[:1], rb[:1], 0.15)
    flat_a, flat_b = [v for _k, v in ra[0]], [v for _k, v in rb[0]]
    pooled = R.boot_ratio(flat_a, flat_b)
    check("stopping: rounds compared by their number decide what pooled rounds cannot",
          st is True and "within" in why and pooled[0] < 0.85, f"{why} pooled {pooled}")
    gap = [[(k, v * 0.7) for k, v in r] for r in rb]
    check("stopping: a 30% gap with the same round shape is decisive", R.decisive(ra, gap, 0.15)[0] is True and
          "excludes 1" in R.decisive(ra, gap, 0.15)[1])
    check("stopping: rounds only one side has are not compared",
          R.decisive([[(1, 50.0)] * 1], [[(2, 50.0)] * 1], 0.15)[0] is False)
    d = tempfile.mkdtemp(prefix="gauntlet_sched_")
    old = (R.engine.load, R.engine.run, R.engine.run_lanes)
    try:
        def pair(char, reach=18):
            return {"char": char, "build": char + "b", "act": 3,
                    "specs": {x: {"set": f"{char} {x}", "act": 3, "reach": {"m": reach}, "expect": {"score": 1}}
                              for x in ("a", "b")}}
        pairs = [pair("laezel"), pair("shadowheart"), pair("gale", 36), pair("astarion")]
        specs = os.path.join(d, "specs.json")
        with open(specs, "w", encoding="utf-8") as f:
            json.dump(pairs, f)
        res = os.path.join(d, "res.jsonl")
        even = [60.0] * 16
        with open(res, "w", encoding="utf-8") as f:
            # pair 0 side b measured from the other save already; pair 3 decided already (both sides there)
            f.write(json.dumps(dict(_sched_rec(pairs[0], "b", even), pair=0, side="b")) + "\n")
            f.write(json.dumps(dict(_sched_rec(pairs[0], "b", [1.0] * 16), pair=0, side="b",
                                    spec_id={"build": "x", "act": 3, "set_name": "other"})) + "\n")
            for x in ("a", "b"):
                f.write(json.dumps(dict(_sched_rec(pairs[3], x, even), pair=3, side=x)) + "\n")
        pr = R.prior_runs(res, 0, pairs[0], ["boss"])
        check("scheduling: the results file's runs of the same set count, another set's not",
              len(pr["b"]) == 1 and len(pr["a"]) == 0, str({k: len(v) for k, v in pr.items()}))
        log = {"lanes": [], "single": []}

        def fake_run(req, spec):
            i = int(req["label"].split(":")[0][4:])
            log["single"].append((i, req["char"]))
            bad = ["setup mismatch at the start: spell X (want true, got false)", "ended: setup mismatch at the start"]
            return _sched_rec(pairs[i], req["label"][-1], even, bad if i == 2 else None)

        def fake_lanes(lanes, entries, first, gap_need=None):
            log["lanes"].append(([(e[1]["label"], e[1]["char"]) for e in entries], first, gap_need))
            out = {}
            for lane, req, _sp in entries:
                i = int(req["label"].split(":")[0][4:])
                bad = ["setup mismatch at the start: feat (want 1, got 0)"] if i == 1 else None
                out[lane] = dict(_sched_rec(pairs[i], req["label"][-1], even, bad), lane=lane)
            return out
        R.engine.load, R.engine.run, R.engine.run_lanes = (lambda: "loaded"), fake_run, fake_lanes
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            R.main([specs, "--results", res, "--sides", "a", "--scenarios", "boss", "--repeats", "3",
                    "--lanes", "undercity_lanes", "--chars", "laezel=cL,shadowheart=cS,gale=cG,astarion=cA"])
        recs = [json.loads(x) for x in open(res, encoding="utf-8") if x.strip()]
        lanes = log["lanes"]
        check("lanes across pairs: two pairs' sides with different characters fight at once",
              len(lanes) >= 1 and sorted(c for _l, c in lanes[0][0]) == ["cL", "cS"] and lanes[0][2] is not None,
              str(lanes))
        check("lanes across pairs: a set reaching too far runs alone", any(i == 2 for i, _c in log["single"]) and
              not any("pair2" in lab for b in lanes for lab, _c in b[0]), str(log))
        check("scheduling: a pair decided in the results file is not run again",
              not any(i == 3 for i, _c in log["single"]) and not any("pair3" in lab for b in lanes for lab, _c in b[0]))
        p0 = [r for r in recs if r.get("pair") == 0 and r.get("side") == "a"]
        check("scheduling: the other save's side is read from the results (pair 0 decided after one run of a)",
              len(p0) == 1, f"{len(p0)} runs of pair 0 a")
        nr = [r for r in recs if r.get("not_repeated")]
        check("scheduling: a side whose first run failed for a reason every run would meet is not repeated, with why",
              sum(1 for i, _c in log["single"] if i == 2) == 1 and any(r["pair"] == 2 for r in nr) and
              any(r["pair"] == 1 for r in nr) and all("not repeated" in r["invalid"][0] for r in nr), str(nr))
        p1 = [lab for b in lanes for lab, _c in b[0] if lab.startswith("pair1")]
        check("scheduling: the not-repeated side stays out of later lanes", len(p1) == 1, str(lanes))
        rev = R.lane_batches(type("A", (), {"lanes": "undercity_lanes", "chars": "laezel=cL,shadowheart=cS",
                                            "char": None})(), pairs, [(0, "a"), (1, "a")], R.load_arenas(), 1)
        check("lanes across pairs: the lanes swap every repeat", rev[0][0] == [(1, "a"), (0, "a")], str(rev))
        one = R.lane_batches(type("A", (), {"lanes": "undercity_lanes", "chars": "laezel=cX,shadowheart=cX",
                                            "char": None})(), pairs, [(0, "a"), (1, "a")], R.load_arenas(), 0)
        check("lanes across pairs: one character cannot fight in both lanes", [len(b) for b, _n in one] == [1, 1],
              str(one))
        far = R.lane_batches(type("A", (), {"lanes": "undercity_lanes", "chars": "laezel=cL,gale=cG",
                                            "char": None})(), pairs, [(2, "a"), (0, "a")], R.load_arenas(), 0)
        check("lanes across pairs: a set reaching the other lane runs alone", [len(b) for b, _n in far] == [1, 1],
              str(far))
    finally:
        R.engine.load, R.engine.run, R.engine.run_lanes = old
        shutil.rmtree(d, ignore_errors=True)


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
    E.pointer_off_ui = lambda *a, **k: None
    E.release_stuck_buttons = lambda *a, **k: []
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
    return {"mode": "scripted", "pair": pair, "side": side, "scenario": scenario, "haste": False, "real_rolls": True,
            "valid": valid,
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
                      {"error": "the run did not finish", "pair": 1, "side": "a", "req": {"scenario": "boss", "real_rolls": True}}):
                f.write(json.dumps(r) + "\n")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g = R.main(["--report", rs, "--specs", sp, "--v1"])
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
    E.pointer_off_ui = lambda *a, **k: None
    E.release_stuck_buttons = lambda *a, **k: []
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
        starts = sum(1 for c in calls if "GAUNTLET_TEST.start(" in c)
        check("engine: a start the game never showed is sent once more (and only once)", starts == 2, str(starts))
        check("engine: a run that does not finish in time is invalid", "did not finish" in str(raised), str(raised))
    finally:
        E.ev, E.RUNS, E.write_se, E.LOCK = old
        shutil.rmtree(d, ignore_errors=True)


def _load_lua(L, path):
    with open(path, encoding="utf-8") as fh:
        return L.eval("function(s) return load(s)() end")(fh.read())


def campaign_tests(L):
    """No bonus from outside the build and set: a story / mood status with a roll or damage effect and every tadpole
    passive still on the character are listed at setup (the set's own statuses are not) and fail the setup check by
    name; the harness itself removes nothing and puts nothing back."""
    L.execute(r"""
      local G = GAUNTLET
      local removedS, removedP, added = {}, {}, {}
      local oldGet, oldStats = Ext.Entity.Get, Ext.Stats.Get
      local saved = { RemoveStatus = Osi.RemoveStatus, RemovePassive = Osi.RemovePassive, AddPassive = Osi.AddPassive,
        HasPassive = Osi.HasPassive }
      Ext.Stats.Get = function(id)
        if id == "ASTARION_HAPPY" then return { Boosts = "RollBonus(SavingThrow,1);RollBonus(Attack,1)" } end
        if id == "SET_STATUS" then return { Boosts = "RollBonus(Attack,2)" } end
        if id == "WET" then return { Boosts = "" } end
        if id == "ALCH_ELIXIR_ENLARGE" then return { Boosts = "WeaponDamage(1d4,Piercing)" } end
      end
      Ext.Entity.Get = function()
        return { StatusContainer = { Statuses = { a = "ASTARION_HAPPY", b = "SET_STATUS", c = "WET",
          d = T_drunk and "ALCH_ELIXIR_ENLARGE" or nil } },
          PassiveContainer = { Passives = { { Passive = { PassiveId = "TAD_PeaceBreaker" } },
            { Passive = { PassiveId = "Sharpshooter_AllIn" } } } } }
      end
      Osi.RemoveStatus = function(_, st) removedS[#removedS + 1] = st end
      Osi.RemovePassive = function(_, id) removedP[#removedP + 1] = id end
      Osi.AddPassive = function(_, id) added[#added + 1] = id end
      Osi.HasPassive = function() return 0 end
      T_camp = G.campaignEffects("c1", { item_statuses = { { status = "SET_STATUS", item = "x" } } })
      T_rs, T_rp = removedS, removedP
      T_back = G.restoreCampaign == nil and #added == 0
      T_drunk = true   -- the setup used the planned elixir after the campaign list was taken
      G.results = { prep = { campaign = T_camp, bare = {}, items = { { want = "Elixir", got = "used",
        stats = "ALCH_Solution_Elixir_Enlarge", statuses = { "ALCH_ELIXIR_ENLARGE" } } } } }
      local sc = G.setupCheck({ char = "c1" }, { item_statuses = { { status = "SET_STATUS" } } }, "start", nil)
      T_fields = {}
      for _, m in ipairs(sc.mismatches) do T_fields[#T_fields + 1] = m.field end
      Ext.Entity.Get, Ext.Stats.Get = oldGet, oldStats
      for k, v in pairs(saved) do Osi[k] = v end
    """)
    g = L.globals()
    c = g.T_camp
    check("campaign: a story status with an attack bonus and a tadpole passive are listed; the set's status and a "
          "status without roll effects are not",
          lst(c.statuses) == ["ASTARION_HAPPY"] and lst(c.passives) == ["TAD_PeaceBreaker"], f"{lst(c.statuses)} {lst(c.passives)}")
    check("campaign: the harness removes nothing and puts nothing back",
          not lst(g.T_rs) and not lst(g.T_rp) and g.T_back is True, f"{lst(g.T_rs)} {lst(g.T_rp)}")
    f = lst(g.T_fields)
    check("campaign: one still on fails the setup check, named",
          any("campaign passive TAD_PeaceBreaker" in x for x in f) and
          any("campaign status ASTARION_HAPPY" in x for x in f) and not any("campaign status SET_STATUS" in x for x in f), str(f))
    check("campaign: the status a planned consumable gave in the setup (the elixir) is the set's, not flagged",
          not any("campaign status ALCH_ELIXIR_ENLARGE" in x for x in f), str(f))


def popup_tests(L):
    """The test popup's state machine (gauntlet_test.lua): Manual by default, a mode check, Start without a test file
    is a setup failure that starts nothing, Start with one runs the scripted setup as a popup run in the chosen mode,
    a second Start while a run is on is refused, and the phases set Setting up -> Fighting -> Result, or Setup failed
    with the mismatches listed and the fight not started."""
    res = _load_lua(L, os.path.join(G_DIR, "gauntlet_test.lua"))
    check("popup: gauntlet_test.lua loads", "test mode ready" in str(res), str(res))
    L.execute(r"""
      local G, T = GAUNTLET, GAUNTLET_TEST
      local sent, runs = {}, {}
      local oldRun, oldParse, oldLoad, oldBc = G.run, Ext.Json.Parse, Ext.IO.LoadFile, Ext.ServerNet.BroadcastMessage
      Ext.ServerNet.BroadcastMessage = function(ch, s) sent[#sent + 1] = ch end
      G.run = function(req) runs[#runs + 1] = req; return "started" end
      G.F = nil
      T_default = T.mode
      T_bad = T.setMode("fast")
      Ext.IO.LoadFile = function() return nil end
      T_nofile = T.start()
      T_nofile_status, T_nofile_runs = T.status, #runs
      local file = { req = { char = "c1", arena = "house_of_hope", act = 3 }, spec = { set = "S" } }
      Ext.IO.LoadFile = function(name) if name == T.FILE then return "x" end end
      Ext.Json.Parse = function() return file end
      T_start = T.start()
      T_req = runs[1]
      T_status = T.status
      G.F = { state = "fight" }
      T_busy = T.start()
      T.setMode("automatic")
      G.F = nil
      T.start({ run_id = "r42" })
      T_req2 = runs[#runs]
      T.setMode("manual")
      G.onPhase({ popup = true }, "starting")
      T_ph1 = T.status
      G.onPhase({ popup = true, player = true }, "fighting")
      T_ph2, T_ph2d = T.status, T.detail
      local failed = { run_id = "r1", valid = false, invalid = { "ended: setup mismatch at the start" },
        results = { ended = "setup mismatch at the start", summary = {},
          setup = { start = { mismatches = { { field = "enemy 1 AC", want = 19, got = 10 } } } } } }
      G.onPhase({ popup = true }, "done", failed)
      T_ph3, T_ph3lines = T.status, T.last.lines
      local good = { run_id = "r2", test_mode = "automatic", valid = true, invalid = {},
        expect = { boss = { dpr = 100, hit_rate = 0.8 } },
        results = { ended = "rounds done", summary = { dpr = 90, rounds = 16, attacks = { hit = 40, crit = 5, miss = 15 },
          rolls = { n = 80, landed = 60, crit = 7 } },
          hit_riders = { hunters_mark = { hits = 30, rider = 28 },
            sneak_attack = { turns = 16, adv_turns = 3, rider = 2 } } } }
      G.onPhase({ popup = true, tFight = 1 }, "done", good)
      T_ph4, T_ph4last = T.status, T.last
      T_sent = #sent
      G.run, Ext.Json.Parse, Ext.IO.LoadFile, Ext.ServerNet.BroadcastMessage = oldRun, oldParse, oldLoad, oldBc
      G.F = nil
    """)
    g = L.globals()
    check("popup: Manual by default, an unknown mode refused", g.T_default == "manual" and "unknown" in str(g.T_bad))
    check("popup: Start without a test file starts nothing and says Setup failed",
          str(g.T_nofile).startswith("failed") and g.T_nofile_status == "Setup failed" and g.T_nofile_runs == 0)
    r = g.T_req
    check("popup: Start runs the scripted setup as a popup run in the chosen mode, with the file's spec and a run id",
          g.T_start == "started" and r.popup is True and r.mode == "scripted" and r.play == "manual" and
          r.spec.set == "S" and r.char == "c1" and str(r.run_id).startswith("gt") and g.T_status == "Setting up",
          f"{g.T_start} {g.T_status}")
    check("popup: a second Start while a run is on is refused", g.T_busy == "busy")
    check("popup: Automatic mode plays the plan; a script's run id is kept",
          g.T_req2.play == "automatic" and g.T_req2.run_id == "r42")
    check("popup: phases Setting up -> Fighting (your turns in Manual)",
          g.T_ph1 == "Setting up" and g.T_ph2 == "Fighting" and "your turns" in str(g.T_ph2d))
    lines = lst(g.T_ph3lines)
    check("popup: a setup failure says the fight was not started and lists each mismatch",
          g.T_ph3 == "Setup failed" and "NOT started" in lines[0] and any("enemy 1 AC: want 19, got 10" in x
                                                                             for x in lines), str(lines))
    last = g.T_ph4last
    ll = lst(last.lines)
    check("popup: a finished run shows Result with damage against the model's boss scenario, hit rate and riders",
          g.T_ph4 == "Result" and abs(last.hit_rate - 0.75) < 1e-9 and any("model boss 100.0" in x for x in ll) and
          any("Hunter's Mark on 28 of 30" in x for x in ll) and g.T_sent > 0, str(ll))
    check("popup: counted per attack roll, Sneak Attack per turn with the turns of net Advantage",
          last.attacks == 80 and last.crits == 7 and any("Attacks 80" in x for x in ll) and
          any("Sneak Attack in 2 of 16 turns (3 with net Advantage)" in x for x in ll), str(ll))


def release_tests(L):
    """A popup run: the enemies keep their own faction through the setup; a setup mismatch stops the run before the
    fight with no recorder marker and no hostile enemy; a clean setup writes the "fight started" marker, turns the
    enemies hostile and starts the fight; an enemy that never turns hostile stops it; the "fight over" marker follows
    the record, only after a start marker, and legacy runs write none."""
    L.execute(r"""
      local G = GAUNTLET
      local files, factions, fought, released = {}, {}, 0, 0
      local oldSave, oldFaction, oldGo, oldRel, oldCheck, oldSpawn, oldEnemy =
        Ext.IO.SaveFile, Osi.SetFaction, G.goFight, G.release, G.setupCheck, G.spawnEnemies, Osi.IsEnemy
      Ext.IO.SaveFile = function(name, s) files[name] = s end
      Osi.SetFaction = function(d, f) factions[#factions + 1] = f end
      G.goFight = function() fought = fought + 1 end
      -- setup failure: the release never comes
      G.release = function() released = released + 1 end
      G.spawnEnemies = function(_, _, faction) T_spawn_faction = faction; G.enemyForced = { e1 = true }; return { "e1" } end
      G.setupCheck = function() return { checked = 1, mismatches = { { field = "enemy 1 AC", want = 19, got = 10 } } } end
      G.reset()
      local F = { req = { run_id = "rid", label = "t" }, popup = true, char = "c1", spec = {}, plan = {}, S = {},
        cooldown = {}, started = 1, state = "prep" }
      G.F = F
      G.spawnAndFight(F, { { 0, 0, 0 } }, { ac = 19, damage_scale = 0.5 }, {}, { enemy_faction = "EVIL" })
      T_fail = { state = F.state, ended = G.results.ended, released = released, fought = fought,
        started = files[G.MARK_FILES.started], faction = T_spawn_faction }
      -- a clean setup: marker, hostile, fight
      G.release = oldRel
      G.setupCheck = function() return { checked = 1, mismatches = {} } end
      Osi.IsEnemy = function() return 1 end
      files = {}
      G.reset()
      F = { req = { run_id = "rid2", label = "t" }, popup = true, char = "c1", spec = {}, plan = {}, S = {},
        cooldown = {}, started = 1, state = "prep" }
      G.F = F
      G.spawnAndFight(F, { { 0, 0, 0 } }, { ac = 19, damage_scale = 0.5 }, {}, { enemy_faction = "EVIL" })
      T_ok = { started = files[G.MARK_FILES.started], over = files[G.MARK_FILES.over], fought = fought,
        faction = factions[#factions] }
      -- never hostile: stopped before any turn, the over marker follows
      local t = 0
      local oldNow = Ext.Utils.MonotonicTime
      Ext.Utils.MonotonicTime = function() t = t + 400; return t end
      Osi.IsEnemy = function() return 0 end
      files = {}
      G.reset()
      F = { req = { run_id = "rid3", label = "t" }, popup = true, char = "c1", spec = {}, plan = {}, S = {},
        cooldown = {}, started = 1, state = "prep", enemies = { "e1" }, enemyFaction = "EVIL" }
      G.F = F
      local before = fought
      G.release(F)
      T_never = { state = F.state, ended = G.results.ended, fought = fought - before,
        over = files[G.MARK_FILES.over] }
      Ext.Utils.MonotonicTime = oldNow
      -- markers on their own
      files = {}
      G.mark("over", { popup = true, req = { run_id = "x" } }, "rounds done")
      T_over_alone = files[G.MARK_FILES.over]
      G.mark("started", { popup = false, req = { run_id = "x" } })
      T_legacy = files[G.MARK_FILES.started]
      Ext.IO.SaveFile, Osi.SetFaction, G.goFight, G.release, G.setupCheck, G.spawnEnemies, Osi.IsEnemy =
        oldSave, oldFaction, oldGo, oldRel, oldCheck, oldSpawn, oldEnemy
      G.F, G.fighting = nil, false
    """)
    g = L.globals()
    f = g.T_fail
    check("popup setup failure: stopped before the fight, no release, no marker, enemies spawned in their own faction",
          f.state == "done" and f.ended == "setup mismatch at the start" and f.released == 0 and f.fought == 0 and
          f.started is None and f.faction is None, f"{f.state} {f.ended} {f.released} {f.started} {f.faction}")
    o = g.T_ok
    check("popup start: the start marker holds the run id, the enemies join the hostile faction, the fight starts",
          o.started == "rid2\n" and o.over == "" and o.faction == "EVIL" and o.fought >= 1,
          f"{o.started!r} {o.over!r} {o.faction} {o.fought}")
    n = g.T_never
    check("popup start: an enemy that never turns hostile stops the run before any turn; the over marker follows",
          n.state == "done" and "did not turn hostile" in str(n.ended) and n.fought == 0 and
          str(n.over).startswith("rid3 "), f"{n.state} {n.ended} {n.over!r}")
    check("markers: no over marker without a start, none for legacy runs",
          g.T_over_alone is None and g.T_legacy is None)


def boss_reuse_tests(L):
    """The save's own boss (req.boss): the gauntlet's earlier boosts come off, it moves to the enemy spot and is forced
    again (forced stats do not survive a reload); the setup check reads every forced boost back; at the end it gets
    its own faction back and is never deleted; it is no intruder in the arena."""
    L.execute(r"""
      local G = GAUNTLET
      local removed, moved, added, factions, deleted = {}, nil, {}, {}, {}
      local saved = {}
      for _, k in ipairs({ "RemoveBoosts", "TeleportToPosition", "AddBoosts", "IsDead", "GetFaction", "SetFaction",
                           "RequestDelete", "RequestDeleteTemporary", "GetMaxHitpoints" }) do saved[k] = Osi[k] end
      local oldGet = Ext.Entity.Get
      Osi.RemoveBoosts = function(d, b, _, cause) if cause == "Gauntlet" then removed[#removed + 1] = b end end
      Osi.TeleportToPosition = function(d, x, y, z) moved = { x, z } end
      Osi.AddBoosts = function(d, b) added[#added + 1] = b end
      Osi.IsDead = function() return 0 end
      Osi.GetFaction = function() return "HOUSE_OF_HOPE" end
      Osi.SetFaction = function(d, f) factions[#factions + 1] = f end
      Osi.RequestDelete = function(d) deleted[#deleted + 1] = d end
      Osi.RequestDeleteTemporary = Osi.RequestDelete
      Osi.GetMaxHitpoints = function() return 5024 end
      Ext.Entity.Get = function(u)
        return { Stats = { Abilities = { 0, 16, 11, 14, 12, 12, 14 }, ProficiencyBonus = 2 }, Resistances = { AC = 10,
          Resistances = {} }, Replicate = function() end }
      end
      G.bossFaction, G.enemyBoosts = nil, nil
      local E = { ac = 19, save = 5, atk = 9, dmg = 12, dc = 17, hp = 5000 }
      T_reuse = G.reuseBoss("boss1", { 5, 0, 7 }, E)
      T_removed1, T_moved, T_added = #removed, moved, added
      T_given = G.enemyBoosts and G.enemyBoosts.boss1
      local first = {}
      for i, x in ipairs(T_given or {}) do first[i] = x end
      -- a second Start in the same session: the first Start's boosts come off, each by its text
      G.reuseBoss("boss1", { 5, 0, 7 }, E)
      T_first, T_removed = first, removed
      G.reset()
      G._finish({ req = { label = "t" }, manual = true, boss = "boss1", enemies = { "boss1", "spawned2" },
        started = 1, state = "fight", cooldown = {}, plan = {}, S = {} }, "aborted")
      T_factions = factions
      T_deleted = deleted
      for k, v in pairs(saved) do Osi[k] = v end
      Ext.Entity.Get = oldGet
    """)
    g = L.globals()
    check("boss reuse: the save's boss is used and moved to the enemy spot (a first Start has no boosts to take off)",
          g.T_reuse is not None and g.T_removed1 == 0 and lst(g.T_moved) == [5, 7], str(lst(g.T_moved)))
    check("boss reuse: a second Start takes the first Start's boosts off by their text (an empty text removes none)",
          lst(g.T_removed) == lst(g.T_first) and len(lst(g.T_first)) > 0 and "" not in lst(g.T_removed),
          f"{lst(g.T_removed)} / {lst(g.T_first)}")
    added = lst(g.T_added) or []
    check("boss reuse: its stats are forced again on every Start (AC and attack boosts given again)",
          any(x.startswith("AC(") for x in added) and any(x.startswith("RollBonus(Attack") for x in added),
          str(added))
    check("boss reuse: the boosts given are remembered for the setup check", g.T_given is not None and
          lst(g.T_first) == added[:len(lst(g.T_first))] and len(lst(g.T_first)) * 2 == len(added), str(lst(g.T_given)))
    check("boss reuse: back in its own faction at the end, never deleted",
          lst(g.T_factions) == ["HOUSE_OF_HOPE"] and "boss1" not in (lst(g.T_deleted) or []) and
          "spawned2" in (lst(g.T_deleted) or []), f"{lst(g.T_factions)} {lst(g.T_deleted)}")
    with open(os.path.join(G_DIR, "gauntlet.lua"), encoding="utf-8") as fh:
        src = fh.read()
    check("boss reuse: the setup check reads each forced boost back and the arena check skips the boss",
          'cmp("enemy " .. i .. " boost " .. x, true, G.hasBoost(have, x))' in src and
          "G.arenaIntruders(A, req.boss and uuid(req.boss))" in src)


TESTMOD_STUBS = r"""
local noop = function() end
TM = { listeners = {}, net = {}, loadstrings = 0, prints = {}, broadcast = {}, files = {}, players = {} }
Ext = { Utils = { Print = function(s) TM.prints[#TM.prints + 1] = s end,
    LoadString = function(src) TM.loadstrings = TM.loadstrings + 1; return function() return "loaded " .. src end end },
  IO = { LoadFile = function(name, ctx) return TM.files[(ctx or "user") .. ":" .. name] end },
  Json = { Parse = function(s) return TM.parsed end },
  Osiris = { RegisterListener = function(name, n, when, fn) TM.listeners[name] = fn end },
  Events = { NetMessage = { Subscribe = function(_, fn) TM.net[#TM.net + 1] = fn end },
    GameStateChanged = { Subscribe = noop } },
  ServerNet = { BroadcastMessage = function(ch) TM.broadcast[#TM.broadcast + 1] = ch end },
  ClientNet = { PostMessageToServer = noop } }
Osi = { DB_Players = { Get = function() return TM.players end } }
"""


def testmod_tests():
    """The test mod's server bootstrap is inert in every save the test file does not name: no file -> nothing read
    but the file and nothing printed; a file whose character is not in the party, or an arena in another level ->
    the harness is never run; the test save -> the harness runs from the pak and the client is told to load F11."""
    try:
        import lupa
    except ImportError:
        print("skip test mod tests (pip install lupa)")
        return
    boot = os.path.join(G_DIR, "testmod", "LootAdvisorGauntletTest", "Mods", "LootAdvisorGauntletTest",
                        "ScriptExtender", "Lua")
    for fn in ("BootstrapServer.lua", "BootstrapClient.lua"):
        L0 = lupa.LuaRuntime(unpack_returned_tuples=True)
        with open(os.path.join(boot, fn), encoding="utf-8") as fh:
            err = L0.eval("function(s) local f, e = load(s) return e end")(fh.read())
        check(f"test mod: {fn} compiles", err is None, str(err))

    def scenario(files, parsed, players, level):
        L = lupa.LuaRuntime(unpack_returned_tuples=True)
        L.execute(TESTMOD_STUBS)
        g = L.globals()
        for k, v in files.items():
            g.TM.files[k] = v
        g.TM.parsed = L.eval("function(s) return load('return ' .. s)() end")(parsed) if parsed else None
        for i, p in enumerate(players):
            L.execute(f'TM.players[{i + 1}] = {{ "{p}" }}')
        with open(os.path.join(boot, "BootstrapServer.lua"), encoding="utf-8") as fh:
            L.eval("function(s) return load(s)() end")(fh.read())
        L.execute(f'TM.listeners.LevelGameplayStarted("{level}", 0)')
        return g
    req = '{ req = { char = "11111111-2222-3333-4444-555555555555", arena_def = { level = "CTY_Main_A" } }, spec = {} }'
    harness = {"data:Mods/LootAdvisorGauntletTest/ScriptExtender/Lua/Harness/gauntlet.lua": "G",
               "data:Mods/LootAdvisorGauntletTest/ScriptExtender/Lua/Harness/gauntlet_test.lua": "T"}
    g = scenario(harness, None, ["x_c1"], "CTY_Main_A")
    check("test mod: no test file -> inert and silent, the harness never runs",
          g.TM.loadstrings == 0 and len(g.TM.prints) == 0 and len(g.TM.broadcast) == 0 and
          g.GAUNTLET_TESTMOD.armed is False)
    g = scenario(dict(harness, **{"user:LootAdvisor_gauntlet_test.json": "x"}), req, ["Astarion_11111111-2222-3333-4444-000000000000"], "CTY_Main_A")
    check("test mod: a save whose party lacks the test character stays inert",
          g.TM.loadstrings == 0 and g.GAUNTLET_TESTMOD.armed is False and "not in this save" in str(g.GAUNTLET_TESTMOD.why))
    g = scenario(dict(harness, **{"user:LootAdvisor_gauntlet_test.json": "x"}), req, ["Astarion_11111111-2222-3333-4444-555555555555"], "WLD_Main_A")
    check("test mod: the party in another level than the arena's stays inert",
          g.TM.loadstrings == 0 and g.GAUNTLET_TESTMOD.armed is False)
    g = scenario(dict(harness, **{"user:LootAdvisor_gauntlet_test.json": "x"}),
                 req.replace("spec = {}", "spec = {}, enabled = false"), ["Astarion_11111111-2222-3333-4444-555555555555"], "CTY_Main_A")
    check("test mod: a disabled test file stays inert", g.TM.loadstrings == 0 and g.GAUNTLET_TESTMOD.armed is False)
    g = scenario(dict(harness, **{"user:LootAdvisor_gauntlet_test.json": "x"}), req, ["Astarion_11111111-2222-3333-4444-555555555555"], "CTY_Main_A")
    check("test mod: the test save -> harness and popup run from the pak, the client is told to load the window",
          g.TM.loadstrings == 2 and g.GAUNTLET_TESTMOD.armed is True and lst(g.TM.broadcast) == ["GauntletTestArm"],
          f"{g.TM.loadstrings} {lst(g.TM.prints)}")
    with open(os.path.join(G_DIR, "gauntlet_ui.lua"), encoding="utf-8") as f:
        key = re.search(r'U\.HOTKEY = U\.HOTKEY or "(\w+)"', f.read())
    # F8 quickload, F9 photo mode, F10 hides the HUD (the game's own keys); F6 / F7 Loot and Build Advisor
    check("test mod: the popup's hotkey is none the game or the two mods use",
          key and key.group(1) not in ("F6", "F7", "F8", "F9", "F10"), key and key.group(1))


def no_leak_tests():
    """The test mod never reaches the player download: it is its own mod (own folder, UUID and pak), outside the Loot
    Advisor mod source; the Loot Advisor pak's file list holds none of its files and no harness code, and the build's
    mod and release lists do not name it."""
    import testmod as TM
    names = [rel for rel, _f in TM.files()]
    check("no leak: every test mod file lies under its own mod folder",
          names and all(n.startswith("Mods/%s/" % TM.MOD) for n in names), str(names[:3]))
    src_root = os.path.join(LA, "LootAdvisor")
    check("no leak: the test mod's source is outside the Loot Advisor mod source",
          not os.path.abspath(TM.SRC).startswith(os.path.abspath(src_root) + os.sep))
    with open(os.path.join(TM.SRC, "Mods", TM.MOD, "meta.lsx"), encoding="utf-8") as fh:
        meta = fh.read()
    with open(os.path.join(src_root, "Mods", "LootAdvisor", "meta.lsx"), encoding="utf-8") as fh:
        la_meta = fh.read()
    uid = re.search(r'id="UUID" type="FixedString" value="([^"]+)"', meta).group(1)
    check("no leak: the test mod has its own UUID and folder",
          uid not in la_meta and 'value="%s"' % TM.MOD in meta)
    try:
        TM.bg3tools()
        import build_pak
    except SystemExit:
        print("skip no-leak pak checks (BG3Tools not next to this repository)")
        return
    old = dict(build_pak.REPO_DIRS)
    try:
        build_pak.REPO_DIRS["LootAdvisor"] = LA
        files = build_pak.collect("LootAdvisor")
    finally:
        build_pak.REPO_DIRS.clear()
        build_pak.REPO_DIRS.update(old)
    bad = [n for n, data in files if TM.MOD in n or "Harness/" in n or n.endswith(("gauntlet.lua", "gauntlet_ui.lua",
                                                                                 "gauntlet_test.lua"))
           or b"GAUNTLET_TEST" in data or uid.encode() in data]
    check("no leak: the Loot Advisor pak holds no test mod file and no harness code", files and not bad, str(bad[:3]))
    check("no leak: the build's mod and release lists do not name the test mod",
          TM.MOD not in build_pak.MODS and TM.MOD not in build_pak.RELEASE)


def roll_tests(L):
    """Counted per attack roll (rows of the real-roll runs): a main-hand shot with two hand crossbows is two rolls
    (Attack, then Offhand; a miss is a 0 damage row); a rider row stays with its roll (Sneak Attack taken out apart);
    a spell that rolls no attack (Hunter's Mark: 0 damage Attack and StatusEnter rows) is no miss and gets no
    outcome; a slow projectile landing after the next cast keeps its own spell; each roll takes its d20, Advantage and
    Disadvantage from the hit log; the hit row reads Disadvantage and both d20s; Sneak Attack is counted per turn with
    the turn's net Advantage."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local oldGet = Ext.Stats.Get
      Ext.Stats.Get = function(s)
        if s == "Projectile_MainHandAttack" then
          return { SpellRoll = "Attack(AttackType.RangedWeaponAttack);CastOffhand[Attack(AttackType.RangedOffHandWeaponAttack)]" }
        elseif s == "Projectile_DreadAmbusher" then return { SpellRoll = { Default = "Attack(AttackType.RangedWeaponAttack)" } }
        elseif s == "Target_HuntersMark" or s == "Shout_ActionSurge" then return { SpellRoll = "" }
        elseif s == "Target_Save" then return { SpellRoll = "not SavingThrow(Ability.Wisdom, SourceSpellDC())" } end
        return nil
      end
      T_kinds = { G.spellRollKind("Projectile_MainHandAttack"), G.spellRollKind("Projectile_DreadAmbusher"),
        G.spellRollKind("Target_HuntersMark"), G.spellRollKind("Target_Save"), G.spellRollKind("Unknown_X") or "nil" }
      local me, b = "c1", "b1"
      local R = { r = 1, actions = {
        { spell = "Projectile_DreadAmbusher", result = "done", cast_t = 100, target_u = b },
        { spell = "Shout_ActionSurge", result = "done", cast_t = 200, target_u = me },
        { spell = "Projectile_MainHandAttack", result = "done", cast_t = 1000, target_u = b },
        { spell = "Target_HuntersMark", result = "done", cast_t = 5000, target_u = b },
        { spell = "Target_Unknown", result = "done", cast_t = 7000, target_u = b } },
        reactions_seen = { { who = me, interrupt = "Interrupt_SneakAttack", t = 330 } } }
      -- the hit log: DealDamage comes about 170 ms before the damage row
      local hits = {
        { r = 1, t = 230, source = me, target = b, spell = "Projectile_DreadAmbusher", hit = true, roll = 16,
          roll_total = 27, roll_against = 19, advantage = "true", flags = "AttackAdvantage,Hit,Projectile" },
        { r = 1, t = 300, source = me, target = b, spell = "", hit = true, flags = "AttackAdvantage,Hit,Projectile" },
        { r = 1, t = 1030, source = me, target = b, spell = "Projectile_MainHandAttack", hit = true, crit = true,
          roll = 20, roll2 = 7, advantage = "true", disadvantage = "true", flags = "Hit,Projectile,Critical" },
        { r = 1, t = 1400, source = me, target = b, spell = "", hit = true, flags = "Hit" } }
      local dmg = {
        { r = 1, t = 400, source = me, owner = me, target = b, cause = "Attack", type = "Piercing", amount = 33 },
        { r = 1, t = 454, source = me, owner = me, target = b, cause = "Attack", type = "Piercing", amount = 6 },
        { r = 1, t = 1200, source = me, owner = me, target = b, cause = "Attack", type = "Piercing", amount = 30 },
        { r = 1, t = 1200, source = me, owner = me, target = b, cause = "Attack", type = "Fire", amount = 4 },
        { r = 1, t = 1567, source = me, owner = me, target = b, cause = "Offhand", type = "", amount = 0 },
        { r = 1, t = 5100, source = me, owner = me, target = b, cause = "StatusEnter", type = "", amount = 0 },
        { r = 1, t = 5130, source = me, owner = me, target = b, cause = "Attack", type = "", amount = 0 },
        { r = 1, t = 6000, source = b, owner = b, target = me, cause = "Attack", type = "", amount = 0 },
        { r = 1, t = 7100, source = me, owner = me, target = b, cause = "StatusEnter", type = "", amount = 0 } }
      T_tally = G.castOutcomes(R, hits, dmg, me)
      T_R = R
      T_out = {}
      for i, a in ipairs(R.actions) do T_out[i] = a.outcome or "-" end
      -- a landed roll with no hit row takes its critical hit from CriticalHitBy
      local R2 = { r = 2, actions = {}, crits = { { source = me, owner = me, target = b, t = 2050 } } }
      G.rollTally(R2, {}, { { r = 2, t = 2000, source = me, target = b, cause = "Offhand", type = "Piercing", amount = 40 } },
        me, {})
      T_R2 = R2
      Ext.Stats.Get = oldGet
      -- the hit row: Advantage and Disadvantage, both d20s; a single roll has no second d20
      G.reset()
      G.F = { char = me, enemies = { b } }
      G.fighting, G.round = true, 4
      Ext.Types = { Serialize = function() return {} end }
      local function ev(res)
        return { Caster = { Uuid = { EntityUuid = me } }, Target = { Uuid = { EntityUuid = b } },
          SpellId = { Prototype = "Projectile_MainHandAttack" },
          Hit = { EffectFlags = { "Hit" }, ConditionRolls = { { Difficulty = 19,
            Roll = { Result = res, Roll = { Advantage = true, Disadvantage = true, RollType = "RangedWeaponAttack" } } } } } }
      end
      G._onHit(ev({ NaturalRoll = 9, Total = 18, DiscardedDiceTotal = 17 }))
      G._onHit(ev({ NaturalRoll = 11, Total = 20, DiscardedDiceTotal = 0 }))
      T_h1, T_h2 = G.hits[1], G.hits[2]
      G.fighting, G.F = false, nil
      Ext.Types = nil
      -- Sneak Attack per turn: net Advantage from the rolls (Disadvantage cancels the AttackAdvantage-flagged hit of
      -- round 2), from the flag where a round has no rolls (round 3)
      local rounds = {
        { r = 1, rolls = { known = 2, net_adv_any = true, dis_any = false }, status_log = {}, casts = {},
          reactions_seen = { { who = me, interrupt = "Interrupt_SneakAttack" } } },
        { r = 2, rolls = { known = 1, net_adv_any = false, dis_any = true }, status_log = {}, casts = {},
          reactions_seen = {} },
        { r = 3, status_log = {}, casts = {}, reactions_seen = {} },
        { r = 4, rolls = { known = 1, net_adv_any = false, dis_any = false }, status_log = {}, reactions_seen = {},
          casts = { { who = me, spell = "Target_SneakAttack" } } } }
      local hh = { { r = 2, source = me, hit = true, flags = "AttackAdvantage,Hit" },
        { r = 3, source = me, hit = true, flags = "AttackAdvantage,Hit" } }
      T_sa = G.hitRiders(rounds, hh, me).sneak_attack
      -- a riposte's Sneak Attack (enemy phase, or a cast after the turn was released) is not the own turn's; a turn
      -- that started without the charge is not counted as one that could have used it
      local rr = {
        { r = 5, rolls = { known = 1, net_adv_any = true }, status_log = {}, tm = { released = 1000 },
          casts = { { who = me, spell = "Target_SneakAttack", t = 1500 } },
          reactions_seen = { { who = me, interrupt = "Interrupt_SneakAttack_Critical", phase = "enemy" } },
          policy = { state = { sneak = false } } },
        { r = 6, rolls = { known = 1, net_adv_any = true }, status_log = {}, casts = {},
          reactions_seen = { { who = me, interrupt = "Interrupt_SneakAttack", phase = "own" } },
          policy = { state = { sneak = true } } } }
      local sr = G.hitRiders(rr, {}, me).sneak_attack
      T_sr = { sr.per_turn[1].sneak, sr.per_turn[2].sneak, sr.adv_turns, sr.rider_adv, sr.no_charge }
      -- the summary adds the rolls up
      G.rounds = { { r = 1, actions = {}, rolls = { n = 3, landed = 2, crit = 1, miss = 1, dmg = 73, rider = 6,
        sneak_dmg = 6, known = 2, adv = 2, dis = 1, net_adv = 1 } },
        { r = 2, actions = {}, rolls = { n = 2, landed = 1, crit = 0, miss = 1, dmg = 25, rider = 0, sneak_dmg = 0,
          known = 1, adv = 1, dis = 0, net_adv = 1 } } }
      T_sum = G._summarize({ char = me, enemies = {} })
    """)
    g = L.globals()
    kinds = [g.T_kinds[i + 1] for i in range(5)]
    check("rolls: what a spell rolls from its SpellRoll (text or table): attack, save, none, unknown",
          kinds == ["attack", "attack", "none", "save", "nil"], str(kinds))
    ro = g.T_R.rolls
    pr = [None] + ([ro.per_roll[i + 1] for i in range(ro.n)] if ro else [None] * 3)
    check("rolls: a main-hand shot with two hand crossbows is two rolls (Attack, then Offhand), the miss a 0 damage row",
          ro is not None and ro.n == 3 and ro.landed == 2 and ro.miss == 1 and [p.cause for p in pr[1:]] ==
          ["Attack", "Attack", "Offhand"] and pr[2].hit is True and pr[2].dmg == 34 and pr[3].hit is False,
          str([(p.cause, p.hit, p.dmg) for p in pr[1:]]))
    check("rolls: one action is one outcome (the plan check), its two rolls counted apart",
          g.T_out[3] == "crit" and g.T_tally.crit == 1 and g.T_tally.miss == 0, str([g.T_out[i + 1] for i in range(4)]))
    check("rolls: Hunter's Mark's 0 damage Attack and StatusEnter rows are no miss and give no outcome",
          g.T_out[4] == "-" and ro.miss == 1, f"{g.T_out[4]} miss {ro.miss}")
    check("outcome: a lone 0 damage StatusEnter row (a spell of unknown stats) is no miss", g.T_out[5] == "-",
          str(g.T_out[5]))
    check("rolls: a slow projectile landing after the next cast keeps its own spell and d20",
          pr[1].spell == "Projectile_DreadAmbusher" and pr[1].nat == 16 and pr[1].against == 19 and pr[1].total == 27,
          str((pr[1].spell, pr[1].nat)))
    check("rolls: a rider row (Sneak Attack, 54 ms later) stays with its roll and is marked as Sneak Attack",
          pr[1].dmg == 39 and pr[1].rider == 6 and pr[1].sneak == 6 and ro.sneak_dmg == 6 and ro.sneak is True,
          str((pr[1].dmg, pr[1].rider, pr[1].sneak)))
    check("rolls: a second damage type of the same hit is no rider", pr[2].rider == 0)
    check("rolls: each roll's Advantage, Disadvantage and both d20s from the hit log; Disadvantage cancels Advantage",
          pr[1].adv is True and pr[1].net_adv is True and pr[2].adv is True and pr[2].dis is True and
          pr[2].net_adv is False and pr[2].nat == 20 and pr[2].nat2 == 7 and pr[2].crit is True and
          pr[3].nat is None and pr[3].adv is None, str([(p.adv, p.dis, p.net_adv, p.nat, p.nat2) for p in pr[1:]]))
    check("rolls: the tallies of Advantage are over the rolls the hit log shows",
          ro.known == 2 and ro.adv == 2 and ro.dis == 1 and ro.net_adv == 1 and ro.crit == 1 and ro.dmg == 73,
          f"{ro.known} {ro.adv} {ro.dis} {ro.net_adv} {ro.crit} {ro.dmg}")
    r2 = g.T_R2.rolls
    check("rolls: a landed roll with no hit row takes its critical hit from CriticalHitBy",
          r2.n == 1 and r2.crit == 1 and r2.per_roll[1].adv is None, f"{r2.n} {r2.crit}")
    h1, h2 = g.T_h1, g.T_h2
    check("hits: Disadvantage and the other d20 of a roll with two",
          h1.disadvantage == "true" and h1.advantage == "true" and h1.roll == 9 and h1.roll2 == 17,
          str((h1.disadvantage, h1.roll, h1.roll2)))
    check("hits: a roll with one d20 has no second one", h2.roll == 11 and h2.roll2 is None, str(h2.roll2))
    sa = g.T_sa
    pt = [(t.r, t.adv, t.dis, t.sneak) for t in (sa.per_turn[i + 1] for i in range(len(sa.per_turn)))]
    check("sneak: every turn counted, with its net Advantage (from the rolls, the flag without them) and its trigger",
          sa.turns == 4 and sa.adv_turns == 2 and sa.dis_turns == 1 and sa.rider == 2 and sa.rider_adv == 1 and
          pt == [(1, True, False, True), (2, False, True, False), (3, True, False, False), (4, False, False, True)],
          f"{sa.turns} {sa.adv_turns} {sa.rider} {sa.rider_adv} {pt}")
    srr = seq(g.T_sr, 5)
    check("Sneak Attack per turn: a riposte's is not the own turn's; a turn without the charge not counted as one that could",
          srr == [False, True, 1, 1, 1], str(srr))
    s = g.T_sum.rolls
    check("summary: the run's rolls added up", s.n == 5 and s.landed == 3 and s.crit == 1 and s.dmg == 98 and
          s.net_adv == 2 and s.sneak_dmg == 6, f"{s.n} {s.landed} {s.dmg}")


def policy_tests(L):
    """A strategy's policy (plan.policy): each turn the harness reads the state the fight is in (round, boss in reach,
    superiority dice, Action Surge and Piercing Strike ready from the engine's cooldowns, concentration and Gaping
    Wound from the boss's statuses, Dread Ambusher from the turn's statuses, Sneak Attack's charge, True Strike from a
    riposte hit in the enemies' turn just before) and plays that state's decision, recording the state, the decision
    and the strategy's expectation for it; Hunter's Mark broken in the enemies' turn -> the decision that recasts it; a
    state outside the table plays nothing, ends the round at once (fail-fast) and makes the run invalid, named."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local st = { b1 = { HUNTERS_MARK = true }, c1 = {} }
      local pos = { c1 = { 0, 0, 0 }, b1 = { 1.5, 0, 0 } }
      local res = { SuperiorityDie = 3, SneakAttack_Charge = 1 }
      local cds = { { SpellId = { Prototype = "Target_PiercingThrust" }, Cooldown = -1 } }
      local saved = { Osi.HasActiveStatus, Osi.GetPosition, Osi.GetActionResourceValuePersonal, Osi.IsDead,
        Ext.Entity.Get }
      Osi.HasActiveStatus = function(u, s) return (st[u] or {})[s] and 1 or 0 end
      Osi.GetPosition = function(u) local p = pos[u] or { 99, 0, 99 }; return p[1], p[2], p[3] end
      Osi.GetActionResourceValuePersonal = function(u, k) return res[k] end
      Osi.IsDead = function() return 0 end
      Ext.Entity.Get = function(u)
        if u == "c1" then return { SpellBookCooldowns = { Cooldowns = cds }, StatusContainer = { Statuses = {} } } end
      end
      local key = function(conc, ts) return "rnd=2|adjacent=1|dice=3|surge=1|conc=" .. conc ..
        "|gaping=0|pierce_m=0|pierce_r=1|dread=0|sneak=1|ts=" .. ts .. "|far=0" end
      local plain = { spell = "Target_MainHandAttack", group = "action", target = "@boss" }
      local mark = { spell = "Target_HuntersMark", group = "bonus", target = "@boss" }
      local policy = { fields = G.POLICY_FIELDS, has = { surge = true, pierce_m = true, pierce_r = true, dread = true,
          sneak = true, ts = true },
        decisions = { { text = "melee", steps = { plain } },
          { text = "melee, Hunter's Mark", steps = { mark, plain },
            riders = { { status = "HUNTERS_MARK", on = "@boss", spell = "Target_HuntersMark", conc = true } } } },
        states = { [key("mark", "0")] = { d = 0, own = 112.4, own_sd = 16.1, ["round"] = 131.7, round_sd = 25.3 },
          [key("mark", "1")] = { d = 0, own = 112.4, own_sd = 16.1, ["round"] = 131.7, round_sd = 25.3 },
          [key("none", "0")] = { d = 1, own = 97.3, own_sd = 16.3, ["round"] = 120.7, round_sd = 25.3 } } }
      local F = { char = "c1", enemies = { "b1" }, cooldown = {}, S = { rounds = 16 },
        afford = function() return true end,
        plan = { rounds = { { plain }, { plain } }, steady = { plain }, policy = policy } }
      G.F = F
      local prev = { r = 1, tm = { end_asked = 500 }, status_log = {} }
      local R = { r = 2, actions = {}, casts = {}, done = {} }
      G.rounds = { prev, R }
      T_q1 = G.planRound(F, R)
      T_p1 = R.policy
      -- the boss's hit broke the mark in the enemies' turn; the riposte's True Strike came before our turn ended
      st.b1.HUNTERS_MARK = nil
      prev.status_log = { { who = "b1", status = "TRUE_STRIKE", on = true, cause = "c1", t = 300 } }
      local R2 = { r = 2, actions = {}, casts = {}, done = {} }
      G.rounds = { prev, R2 }
      T_q2 = G.planRound(F, R2)
      T_p2 = R2.policy
      G.riderCheck(F, R2)
      T_rm2 = R2.rider_misses
      -- the riposte's True Strike after our turn ended: ts = 1, a state the table does not hold
      prev.status_log = { { who = "b1", status = "TRUE_STRIKE", on = true, cause = "c1", t = 900 } }
      local R3 = { r = 2, actions = {}, casts = {}, done = {} }
      G.rounds = { prev, R3 }
      T_q3 = G.planRound(F, R3)
      T_p3 = R3.policy
      T_fault = G.roundFault({ plan = F.plan, S = {} }, R3)
      T_j = G.judge({ prev, R3 }, "rounds done", G.results, { me = "c1" })
      -- following the policy, the concentration the turn started with must be on as the turn ends
      st.b1.HUNTERS_MARK = true
      local R4 = { r = 2, actions = {}, casts = {}, done = {} }
      prev.status_log = {}
      G.rounds = { prev, R4 }
      G.planRound(F, R4)
      st.b1.HUNTERS_MARK = nil
      G.results.rider_misses = nil
      G.riderCheck(F, R4)
      T_rm4 = R4.rider_misses
      -- the boss's start spot: out of reach and not moved (within G.START_SPOT_M) -> far; in reach, moved, or no
      -- start recorded -> not
      local function far(at, start)
        pos.b1, F.boss_start, F.boss_left = at, start, nil
        return G.policyState(F, { r = 2, turn_statuses = {} }).far
      end
      T_far = { far({ 9, 0, 0 }, { 9.6, 0, 0 }), far({ 9, 0, 0 }, { 10.5, 0, 0 }), far({ 1.5, 0, 0 }, { 1.5, 0, 0 }),
        far({ 9, 0, 0 }, nil) }
      pos.b1 = { 9, 0, 0 }
      G.bossStartSpot(F)
      T_far[5] = G.policyState(F, { r = 2, turn_statuses = {} }).far
      pos.b1, F.boss_start = { 1.5, 0, 0 }, nil
      Osi.HasActiveStatus, Osi.GetPosition, Osi.GetActionResourceValuePersonal, Osi.IsDead, Ext.Entity.Get =
        saved[1], saved[2], saved[3], saved[4], saved[5]
      G.F, G.rounds = nil, {}
    """)
    g = L.globals()
    q1 = [g.T_q1[i + 1].spell for i in range(len(g.T_q1))]
    p1 = g.T_p1
    check("policy: the live state read from the engine (reach, dice, cooldowns, the boss's statuses, the charge) is "
          "the table's key; its decision is played and recorded with the state's expectation",
          p1 is not None and p1.key == "rnd=2|adjacent=1|dice=3|surge=1|conc=mark|gaping=0|pierce_m=0|pierce_r=1|"
          "dread=0|sneak=1|ts=0|far=0" and p1.decision == "melee" and q1 == ["Target_MainHandAttack"] and
          p1.own == 112.4
          and p1["round"] == 131.7 and not p1.outside, str(p1 and p1.key))
    q2 = [g.T_q2[i + 1].spell for i in range(len(g.T_q2))]
    check("policy: Hunter's Mark broken in the enemies' turn -> the state's decision recasts it, its rider checked",
          g.T_p2.decision == "melee, Hunter's Mark" and q2 == ["Target_HuntersMark", "Target_MainHandAttack"] and
          g.T_rm2 is not None and g.T_rm2[1].status == "HUNTERS_MARK", str(q2))
    check("policy: True Strike counts only from a riposte after the turn ended; a state outside the table plays "
          "nothing, ends the round (fail-fast) and makes the run invalid with the state",
          g.T_p3.outside is True and "ts=1" in g.T_p3.key and len(g.T_q3) == 0 and "outside the policy" in
          str(g.T_fault) and any("outside the strategy's policy table" in c and "ts=1" in c for c in lst(g.T_j.causes)),
          f"{g.T_p3.key} {g.T_fault}")
    check("policy: the concentration the turn started with is checked as the turn ends (lost -> rider missing)",
          g.T_rm4 is not None and g.T_rm4[1].status == "HUNTERS_MARK", str(g.T_rm4))
    fa = [g.T_far[i + 1] for i in range(5)]
    check("policy: far = the boss out of reach and still at the start spot recorded as the fight starts (moved "
          "1.5 m, in reach or no start: not)", fa == [True, False, False, False, True], str(fa))


def conc_rider_tests(L):
    """A plan without a policy: its concentration rider (Hunter's Mark) is checked again after every later turn, on
    now; lost, it is noted once (rider_lost: the plan is off its course), not a failed run; a rider put on and broken
    in its own round does not count (on now only)."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local on = true
      local saved = { Osi.HasActiveStatus, Osi.IsDead }
      Osi.HasActiveStatus = function(u, s) return (u == "b1" and s == "HUNTERS_MARK" and on) and 1 or 0 end
      Osi.IsDead = function() return 0 end
      local F = { char = "c1", enemies = { "b1" }, plan = { riders = {
        { round = 1, status = "HUNTERS_MARK", on = "@boss", conc = true },
        { round = 1, status = "DREAD_AMBUSHER", on = "@self" } } } }
      G.riderCheck(F, { r = 1, turn_statuses = { "DREAD_AMBUSHER" }, status_log = {} })
      T_m1 = G.results.rider_misses
      G.riderCheck(F, { r = 2, status_log = {} })
      on = false
      local R3 = { r = 3, status_log = {} }
      G.riderCheck(F, R3)
      G.riderCheck(F, { r = 4, status_log = {} })
      T_lost, T_R3, T_m4 = G.results.rider_lost, R3.rider_lost, G.results.rider_misses
      T_j = G.judge({ { r = 1, done = { action = true } } }, "rounds done", G.results, { me = "c1" })
      -- cast and broken in its own round: logged on, not on now
      G.reset()
      G.riderCheck(F, { r = 1, turn_statuses = { "DREAD_AMBUSHER" },
        status_log = { { who = "b1", status = "HUNTERS_MARK", on = true } } })
      T_m5 = G.results.rider_misses
      Osi.HasActiveStatus, Osi.IsDead = saved[1], saved[2]
    """)
    g = L.globals()
    lost = g.T_lost
    check("riders: concentration checked again each later turn; lost, noted once as off course, the run not failed",
          g.T_m1 is None and lost is not None and len(lost) == 1 and lost[1].r == 3 and lost[1].since == 1 and
          g.T_R3 is not None and g.T_m4 is None and lst(g.T_j.causes) == [], str(lost and len(lost)))
    check("riders: a concentration rider counts only when on as the turn ends",
          g.T_m5 is not None and g.T_m5[1].status == "HUNTERS_MARK", str(g.T_m5))


def sneak_row_tests(L):
    """Sneak Attack's damage in a roll is its own row (the weapon's damage type, 55-60 ms after the hit's first rows),
    never the weapon's rider type that comes with the hit (Crimson Mischief's 1d4 necrotic), in either order; a ranged
    hit with no rider keeps its whole late row."""
    L.execute(r"""
      local G = GAUNTLET
      local me, b = "c1", "b1"
      local function run(rows)
        local R = { r = 1, actions = {}, reactions_seen = { { who = me, interrupt = "Interrupt_SneakAttack", t = 0 } } }
        local dmg = {}
        for _, x in ipairs(rows) do
          dmg[#dmg + 1] = { r = 1, t = x[1], source = me, owner = me, target = b, cause = "Attack", type = x[2],
            amount = x[3] }
        end
        return G.rollTally(R, {}, dmg, me, {})
      end
      T_a = run({ { 42, "Piercing", 21 }, { 44, "Necrotic", 3 }, { 99, "Piercing", 6 } })
      T_b = run({ { 101, "Necrotic", 2 }, { 104, "Piercing", 13 }, { 160, "Piercing", 4 } })
      T_c = run({ { 400, "Piercing", 33 }, { 454, "Piercing", 6 } })
      T_d = run({ { 42, "Piercing", 21 }, { 44, "Necrotic", 3 }, { 99, "Fire", 6 } })
    """)
    g = L.globals()
    check("sneak: only the Sneak Attack row, not the weapon's necrotic rider (9 before)",
          g.T_a.sneak_dmg == 6 and g.T_a.per_roll[1].rider == 9 and g.T_a.per_roll[1].dmg == 30,
          f"{g.T_a.sneak_dmg} {g.T_a.per_roll[1].rider}")
    check("sneak: the rider first and the weapon's row second (13 before)", g.T_b.sneak_dmg == 4, str(g.T_b.sneak_dmg))
    check("sneak: a hit with no rider keeps its late row; a late row of another type is no Sneak Attack",
          g.T_c.sneak_dmg == 6 and g.T_d.sneak_dmg == 0, f"{g.T_c.sneak_dmg} {g.T_d.sneak_dmg}")


def miss_row_tests(L):
    """Misses from the engine's attack-roll events: a miss (the character's or the boss's) is logged with its natural
    roll, total and Advantage / Disadvantage; a hit from those events is left to DealDamage; the same miss from both
    events once; a natural 1 is a miss, not a critical hit. The character's miss rows give its 0 damage roll its d20
    and Advantage (known over every roll); the enemies' rolls are counted with theirs."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local me, b = "c1", "b1"
      Ext.Types = { Serialize = function() return { probe = true } end }
      local function comp(src, tgt, flags, nat, total, adv, dis)
        return { Target = { Uuid = { EntityUuid = tgt } }, AC = 22,
          Hit = { EffectFlags = flags, SpellId = "Target_MainHandAttack", Inflicter = { Uuid = { EntityUuid = src } },
            ConditionRolls = { { Difficulty = 19, Roll = { Result = { NaturalRoll = nat, Total = total },
              Roll = { Advantage = adv, Disadvantage = dis } } } } } }
      end
      G.F = { char = me, enemies = { b } }
      G.fighting, G.round = true, 6
      G.onMissEvent(comp(me, b, { "Miss", "Critical" }, 1, 15, true, false), "target_hit")
      G.onMissEvent(comp(me, b, { "Miss", "Critical" }, 1, 15, true, false), "hit_result")
      G.onMissEvent(comp(me, b, { "Hit" }, 15, 29, true, false), "target_hit")
      G.onMissEvent(comp(b, me, { "Miss" }, 9, 18, false, true), "hit_result")
      G.onMissEvent(comp("x", "y", { "Miss" }, 9, 18, false, false), "hit_result")
      T_hits = G.hits
      T_probe = G.results.miss_probe
      local R = { r = 6, actions = {} }
      local dmg = { { r = 6, t = 50, source = me, owner = me, target = b, cause = "Attack", type = "", amount = 0 } }
      local oldStats = Ext.Stats.Get
      Ext.Stats.Get = function() return { SpellRoll = "Attack(AttackType.MeleeWeaponAttack)" } end
      T_R = G.rollTally(R, G.hits, dmg, me, { { spell = "Target_MainHandAttack", cast_t = 0 } })
      Ext.Stats.Get = oldStats
      T_foe = G.enemyRolls(G.hits, me, { [b] = 1 })
      G.fighting, G.F = false, nil
      Ext.Types = nil
    """)
    g = L.globals()
    h = g.T_hits
    check("misses: logged once from the attack-roll events with natural roll, total and Advantage, the boss's too; "
          "hits and other creatures left out",
          len(h) == 2 and h[1].miss is True and h[1].roll == 1 and h[1].roll_total == 15 and h[1].advantage == "true"
          and h[1].source == "c1" and h[2].source == "b1" and h[2].disadvantage == "true" and h[2].roll == 9 and
          g.T_probe is not None, str(len(h)))
    check("misses: a natural 1 is a critical miss, never a critical hit", h[1].crit is False and h[1].crit_miss is True)
    p = g.T_R.per_roll[1]
    check("misses: the character's 0 damage roll takes its d20 and Advantage from the miss row (known over all rolls)",
          g.T_R.miss == 1 and g.T_R.known == 1 and p.nat == 1 and p.adv is True and p.net_adv is True,
          f"{g.T_R.known} {p.nat} {p.adv}")
    f = g.T_foe
    check("misses: the enemies' attack rolls counted with their outcome, d20 and Disadvantage",
          f.n == 1 and f.miss == 1 and f.dis == 1 and f.known == 1 and f.per_roll[1].nat == 9 and
          f.per_roll[1].outcome == "miss", f"{f.n} {f.miss} {f.dis}")


def cast_noise_tests(L):
    """CastSpellFailed that is no refusal: logged after the same caster's UsingSpell of the spell with no CastedSpell
    between (the boss's Unarmed Strike on each miss; the character's Dread Ambusher on the player path) goes to
    cast_fails_noise with why; a fail with no UsingSpell, or after one a CastedSpell answered, stays a refusal; the
    character's fails on the old cast path stay as they are."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local me, b = "c1", "b1"
      G.F = { char = me, enemies = { b }, playerCast = true }
      G.fighting = true
      local t = 0
      local oldNow = Ext.Utils.MonotonicTime
      Ext.Utils.MonotonicTime = function() return t end
      G.t0 = 0
      local R = { r = 1, casts = {}, usings = {}, cast_fails = {} }
      G.rounds = { R }
      local function use(who, sp) R.usings[#R.usings + 1] = { who = who, spell = sp, t = t } end
      use(b, "Target_UnarmedAttack"); t = 700; G._onCastFailed(b, "Target_UnarmedAttack")
      t = 800; use(me, "Target_DreadAmbusher"); t = 1900; G._onCastFailed(me, "Target_DreadAmbusher")
      t = 2000; G._onCastFailed(me, "Target_HuntersMark")
      t = 2100; use(me, "Target_MainHandAttack"); t = 2200; G._onCast(me, "Target_MainHandAttack")
      t = 2300; G._onCastFailed(me, "Target_MainHandAttack")
      T_fails, T_noise = {}, R.cast_fails_noise
      for i, f in ipairs(R.cast_fails) do T_fails[i] = f end
      G.F.playerCast = false
      t = 2400; use(me, "Target_X"); t = 2500; G._onCastFailed(me, "Target_X")
      T_fails2 = #R.cast_fails
      Ext.Utils.MonotonicTime = oldNow
      G.fighting, G.F, G.rounds = false, nil, {}
    """)
    g = L.globals()
    fails = [g.T_fails[i + 1].spell for i in range(len(g.T_fails))]
    noise = [(g.T_noise[i + 1].spell, g.T_noise[i + 1].why) for i in range(len(g.T_noise or {}))]
    check("cast fails: the boss's interrupted Unarmed Strike and a started cast's late fail are noise, with why",
          [x[0] for x in noise] == ["Target_UnarmedAttack", "Target_DreadAmbusher"] and all(x[1] for x in noise),
          str(noise))
    check("cast fails: a refusal (no UsingSpell, or one a CastedSpell answered) stays a fail; the old path unchanged",
          fails == ["Target_HuntersMark", "Target_MainHandAttack"] and g.T_fails2 == 3, str(fails))


def action_rolls_tests(L):
    """Per action its attack rolls: a toggled attack's off-hand half is a roll of its own with its outcome (a miss
    too); the summary's attacks are counted per roll, as summary.rolls, the per-cast outcomes kept apart."""
    L.execute(r"""
      local G = GAUNTLET
      G.reset()
      local asked = { { spell = "Target_MainHandAttack", cast_t = 100 },
        { spell = "Target_MainHandAttack", cast_t = 2000 } }
      G.actionRolls(asked, { { t = 150, cause = "Attack", hit = true, crit = false, nat = 15, total = 29, adv = true },
        { t = 600, cause = "Attack", hit = false, crit = false, nat = 1, total = 15, adv = true },
        { t = 2100, cause = "Attack", hit = true, crit = true, nat = 20, total = 34, adv = true } })
      T_a = asked
      G.rounds = { { r = 1, actions = {}, attacks = { hit = 2, crit = 0, miss = 0 },
        rolls = { n = 3, landed = 2, crit = 1, miss = 1, dmg = 60, rider = 0, sneak_dmg = 0, known = 3, adv = 3, dis = 0,
          net_adv = 3 } } }
      T_sum = G._summarize({ char = "c1", enemies = {} })
      G.rounds = {}
    """)
    g = L.globals()
    a = g.T_a
    r1 = [(a[1].rolls[i + 1].outcome, a[1].rolls[i + 1].nat) for i in range(len(a[1].rolls))]
    check("actions: each cast lists its rolls, the off-hand half's miss included",
          r1 == [("hit", 15), ("miss", 1)] and a[2].rolls[1].outcome == "crit", str(r1))
    s = g.T_sum
    check("summary: attacks per roll (consistent with the rolls), per cast apart",
          s.attacks.hit == 1 and s.attacks.crit == 1 and s.attacks.miss == 1 and s.actions_outcome.hit == 2,
          f"{s.attacks.hit} {s.attacks.crit} {s.attacks.miss}")


def arena_camera_tests(L):
    """The arena: a plan's boss_distance sets the enemies' distance (a melee strategy whose boss starts out of reach),
    else the mode's; the popup's start moves the camera onto the character (the client answers) before the "fight
    started" marker, so the recording opens on the arena; no answer -> the start goes on, recorded."""
    L.execute(r"""
      local G = GAUNTLET
      local _, far = G.arena("boss", "melee", false, { 0, 0, 0 }, nil, 10.0)
      local _, near = G.arena("boss", "melee", false, { 0, 0, 0 }, nil)
      T_far, T_near = far[1][1], near[1][1]
      local order = {}
      local oldNotify, oldSave, oldStart = G.notify, Ext.IO.SaveFile, G.startFight
      local oldActive = Osi.MakePlayerActive
      Osi.MakePlayerActive = function(u) order[#order + 1] = "select " .. tostring(u) end
      G.notify = function(m)
        if m.kind == "camera" then
          order[#order + 1] = "camera " .. tostring(m.char)
          G.F.camera = { ok = true, dist = 0.4 }
        end
      end
      Ext.IO.SaveFile = function(name, s) if name == G.MARK_FILES.started then order[#order + 1] = "marker" end end
      G.startFight = function(F) G.mark("started", F) end
      G.reset()
      local F = { req = { run_id = "rid" }, popup = true, char = "c1", state = "prep" }
      G.F = F
      G.release(F)
      T_order, T_cam = { table.unpack(order) }, G.results.camera
      G.notify = function() end
      G.reset()
      F = { req = { run_id = "rid2" }, popup = true, char = "c1", state = "prep" }
      G.F = F
      G.release(F)
      T_cam2 = G.results.camera
      G.notify, Ext.IO.SaveFile, G.startFight, Osi.MakePlayerActive = oldNotify, oldSave, oldStart, oldActive
      G.F = nil
    """)
    g = L.globals()
    check("arena: the plan's boss distance places a melee plan's boss out of reach, else the melee ring",
          abs(g.T_far - 10.0) < 1e-9 and abs(g.T_near - 1.6) < 1e-9, f"{g.T_far} {g.T_near}")
    order = [g.T_order[i + 1] for i in range(len(g.T_order))]
    check("camera: onto the character before the fight-started marker, the client's answer recorded",
          order[:3] == ["select c1", "camera c1", "marker"] and g.T_cam.ok is True and g.T_cam.dist == 0.4,
          str(order))
    check("camera: no answer from the client -> the start goes on, recorded",
          g.T_cam2 is not None and g.T_cam2.ok is False and "no answer" in str(g.T_cam2.why), str(g.T_cam2))


def _roll_rec(rounds, i=0, side="a", run_id="r", dealt=None, sneak=None, react=None):
    """A run record with per-roll counts: rounds = [(rolls, landed, crits, landed damage list)], each roll's damage
    row from the character "c1" in its own turn (times 1000 apart, the turn released after them); react = {round:
    [(damage, sneak row or 0, critical)]}: riposte rolls in the enemy's turn after that round (a Sneak Attack row 60 ms
    after the roll's, with its reaction logged, and a 7 Passive row after each)."""
    out, dmg, hits = [], [], []
    for r, (n, landed, crits, dl) in enumerate(rounds):
        t0 = 1000000 * (r + 1)
        per = [{"hit": True, "dmg": d, "t": t0 + 1000 * j, "sneak": (sneak if (sneak and r == 0 and j == 0) else None)}
               for j, d in enumerate(dl)]
        per += [{"hit": False, "dmg": 0, "t": t0 + 1000 * (landed + j)} for j in range(n - landed)]
        for p_ in per:
            dmg.append({"r": r + 1, "t": p_["t"], "source": "c1", "target": "b1", "amount": p_["dmg"],
                        "cause": "Attack"})
        seen = []
        for k, (d, sn, cr) in enumerate((react or {}).get(r + 1, [])):
            t = t0 + 600000 + 5000 * k
            dmg.append({"r": r + 1, "t": t, "source": "c1", "target": "b1", "amount": d, "cause": "Attack"})
            hits.append({"r": r + 1, "t": t - 100, "source": "c1", "hit": d > 0, "crit": cr, "miss": d == 0})
            if sn:
                seen.append({"who": "c1", "interrupt": "Interrupt_SneakAttack", "t": t - 30})
                dmg.append({"r": r + 1, "t": t + 60, "source": "c1", "target": "b1", "amount": sn, "cause": "Attack"})
            if d:
                dmg.append({"r": r + 1, "t": t + 62, "source": "c1", "target": "b1", "amount": 7, "cause": "Passive"})
        out.append({"r": r + 1, "done": {"action": True}, "actions": [], "tm": {"turn": t0 - 10, "released": t0 + 500000},
                    "reactions_seen": seen,
                    "rolls": {"n": n, "landed": landed, "crit": crits, "miss": n - landed, "dmg": sum(dl),
                              "sneak_dmg": sneak if (sneak and r == 0) else 0, "known": landed, "net_adv": 0,
                              "dis": 0, "per_roll": per}})
    dealt = dealt or [sum(x[3]) + sum(d + sn + (7 if d else 0) for d, sn, _c in (react or {}).get(k + 1, []))
                      for k, x in enumerate(rounds)]
    return {"mode": "scripted", "pair": i, "side": side, "scenario": "boss", "real_rolls": True, "valid": True,
            "invalid": [], "test_mode": "automatic", "run_id": run_id, "spec_id": {}, "req": {"pair": i, "side": side},
            "rounds": out, "dmg": dmg, "hits": hits,
            "results": {"ended": "rounds done", "summary": {"dealt": dealt, "dpr": sum(dealt) / len(dealt),
                                                            "rounds": len(dealt)},
                        "hit_riders": {"sneak_attack": {"turns": len(dealt), "adv_turns": 1, "rider": 1,
                                                        "rider_adv": 1}}}}


def roll_report_tests(R):
    """--report per roll with 95% intervals: exact binomial for the rates, Student t for the means; a part is flagged
    when the model's value is outside the game's interval, not when the game leaves +-10% (shown beside it)."""
    lo, hi = R.binom_interval(11, 99)
    check("stats: exact binomial interval, 11 of 99 -> 5.7%-19.0%", abs(lo - 0.0568) < 5e-4 and abs(hi - 0.1901) < 5e-4,
          f"{lo} {hi}")
    lo, hi = R.binom_interval(10, 65)
    check("stats: exact binomial interval, 10 of 65 -> 7.6%-26.5%", abs(lo - 0.0763) < 5e-4 and abs(hi - 0.2648) < 5e-4,
          f"{lo} {hi}")
    check("stats: 0 of 10 and 10 of 10 reach the edge (upper 30.8%, lower 69.2%)",
          R.binom_interval(0, 10)[0] == 0.0 and abs(R.binom_interval(0, 10)[1] - 0.3085) < 5e-4 and
          R.binom_interval(10, 10)[1] == 1.0 and abs(R.binom_interval(10, 10)[0] - 0.6915) < 5e-4 and
          R.binom_interval(0, 0) is None)
    tq = {d: R.t_quantile975(d) for d in (1, 3, 30, 40, 60, 120, 100000)}
    check("stats: t quantiles (table to 30 df, the expansion beyond)",
          tq[1] == 12.706 and tq[3] == 3.182 and tq[30] == 2.042 and abs(tq[40] - 2.0211) < 1e-3 and
          abs(tq[60] - 2.0003) < 1e-3 and abs(tq[120] - 1.9799) < 1e-3 and abs(tq[100000] - 1.96) < 1e-3, str(tq))
    lo, hi = R.t_interval([1.0, 2.0, 3.0, 4.0])
    check("stats: t interval of a mean (3 df)", abs(lo - 0.446) < 1e-3 and abs(hi - 4.554) < 1e-3, f"{lo} {hi}")
    check("stats: a t interval of damage never goes below 0; one value has none",
          R.t_interval([0.0, 0.0, 0.0, 6.0])[0] == 0.0 and R.t_interval([5.0]) is None)
    # a two-shot action rolls twice: 4 rounds of 6 rolls
    rec = _roll_rec([(6, 4, 1, [25, 25, 30, 20])] * 4, sneak=6)
    gp = R.game_parts(rec)
    check("report: parts counted per roll (24 rolls, 16 landed, 4 crits) with the samples kept",
          gp["per_roll"] and gp["attacks"] == 24 and gp["landed"] == 16 and gp["crits"] == 4 and
          len(gp["landed_dmg"]) == 16 and gp["n_round"] == [6, 6, 6, 6], str({k: gp[k] for k in ("attacks", "landed")}))
    p = R.pooled([gp])
    check("report: per round and per roll values, Sneak Attack taken out of the damage per landed roll",
          p["attacks"] == 6 and p["hit_rate"] == 16 / 24 and p["dmg_per_hit"] == 100 * 4 / 16 and
          abs(p["dmg_per_hit_no_sneak"] - (400 - 6) / 16) < 1e-9 and p["sneak"] == 6 / 4, str(p))
    # +-10% would flag, the interval does not: 7 of 10 against 85% (ratio 0.82)
    small = R.pooled([R.game_parts(_roll_rec([(5, 4, 0, [20, 20, 20, 20]), (5, 3, 0, [20, 21, 19])]))])
    rows = {r_[0]: r_ for r_ in R.compare_parts(small, {"split": True, "hit_rate": 0.85, "dmg_per_hit": 20.0})}
    check("report: a hit rate 18% below the model but inside its 95% interval (7 of 10) is not flagged; the band "
          "says out", rows["hit_rate"][5] == "" and rows["hit_rate"][7] == "out" and rows["hit_rate"][6][0] < 0.85
          < rows["hit_rate"][6][1], str(rows["hit_rate"]))
    # the reverse: 900 of 1000 against 85% (ratio 1.06, inside +-10%) lies outside the interval
    big = R.pooled([R.game_parts(_roll_rec([(100, 90, 5, [20] * 90)] * 10))])
    rows = {r_[0]: r_ for r_ in R.compare_parts(big, {"split": True, "hit_rate": 0.85, "crit_rate": 0.05})}
    check("report: a hit rate 6% above the model but outside its 95% interval (900 of 1000) is flagged; the band says in",
          rows["hit_rate"][5] == "OUTSIDE" and rows["hit_rate"][7] == "in", str(rows["hit_rate"]))
    check("report: a part the model gives inside the interval unflagged; a part it lacks (Advantage) shown, not compared",
          rows["crit_rate"][5] == "" and rows["adv_rate"][3] is None and rows["adv_rate"][5] == "" and
          rows["adv_rate"][2] is not None)
    check("report: damage per landed roll with an interval from the rolls' damage (all 20: zero width, 21 outside)",
          {r_[0]: r_ for r_ in R.compare_parts(big, {"split": True, "dmg_per_hit": 21.0})}["dmg_per_hit"][5] ==
          "OUTSIDE" and
          {r_[0]: r_ for r_ in R.compare_parts(big, {"split": True, "dmg_per_hit": 20.0})}["dmg_per_hit"][5] == "")
    old = R.pooled([R.game_parts(_v2_rec(0, "a", 100.0, hit=40, crit=5, miss=15))])
    check("report: a record from before rolls were counted falls back to its per-action outcomes",
          old["attacks"] == 60 / 16 and old["hit_rate"] == 0.75 and old["_ci"].get("attacks") is None)
    d = tempfile.mkdtemp(prefix="gauntlet_rolls_")
    try:
        boss = {"split": True, "dpr": 100.0, "attacks": 6.0, "hits": 4.0, "crits": 1.0, "hit_rate": 0.66,
                "crit_rate": 0.17, "dmg_per_hit": 25.0, "sneak": 7.2, "adv_rate": 0.9}
        pairs = [{"char": "astarion", "build": "b", "act": 3, "single": True,
                  "specs": {"a": {"set": "S", "act": 3, "expect": {"boss": boss}}}}]
        sp, res = os.path.join(d, "specs.json"), os.path.join(d, "res.jsonl")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(pairs, f)
        with open(res, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = R.main(["--report", res, "--specs", sp])
        text = buf.getvalue()
        rows = {r_[0]: r_ for r_ in out["sides"][(0, "a")]["rows"]}
        check("report: the table shows the game's 95% interval and the model's +-10% band beside the flag",
              "Game 95%" in text and "Model +-10%" in text and "| own turn: attack rolls per round | 6.00 |" in text,
              text[:900])
        check("report: Sneak Attack as triggers / turns with net Advantage / turns",
              "Sneak Attack: 1 trigger(s) / 1 turn(s) with net Advantage / 4 turn(s)" in text, text[-400:])
        check("report: Sneak Attack damage per round compared (1.5 against 7.2: outside)",
              rows["sneak"][5] == "OUTSIDE", str(rows["sneak"]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def count_report_tests(R):
    """--report's per-round counts: critical hits get an exact Poisson interval on their total, and any count the
    same in every round gets one too, so a sample of zero variance (16 rounds, no riposte critical) leaves a small
    model rate inside instead of a zero-width interval flagging it."""
    lo, hi = R.poisson_interval(5, 1)
    check("stats: exact Poisson interval, 5 events -> 1.62-11.67", abs(lo - 1.6235) < 1e-3 and abs(hi - 11.668) < 1e-3,
          f"{lo} {hi}")
    check("stats: a Poisson interval of no events over 16 rounds has width (0-0.23); no rounds have none",
          R.poisson_interval(0, 16)[0] == 0.0 and abs(R.poisson_interval(0, 16)[1] - 3.6889 / 16) < 1e-3 and
          R.poisson_interval(0, 0) is None)
    rec = _roll_rec([(2, 2, 0, [20, 20])] * 16, react={r: [(20, 0, False)] for r in range(1, 8)})
    p = R.pooled([R.game_parts(rec)])
    rows = {r_[0]: r_ for r_ in R.compare_parts(p, {"split": True, "react_crits": 7 * 0.16 / 16, "crits": 0.1,
                                                     "attacks": 2.2})}
    check("report: no riposte critical in 16 rounds does not flag the model's 0.07 per round (Poisson 0-0.23)",
          rows["react_crits"][2] == 0 and rows["react_crits"][5] == "" and rows["react_crits"][6][1] > 0.2,
          str(rows["react_crits"]))
    check("report: no own critical in 16 rounds does not flag the model's 0.10 per round",
          rows["crits"][5] == "" and rows["crits"][6][1] > 0.2, str(rows["crits"]))
    check("report: 2 rolls in every round (zero variance) leave 2.2 inside, 3.0 outside",
          rows["attacks"][5] == "" and
          {r_[0]: r_ for r_ in R.compare_parts(p, {"split": True, "attacks": 3.0})}["attacks"][5] == "OUTSIDE",
          str(rows["attacks"]))


def disadvantage_report_tests(R):
    """--report's Disadvantage rows: the game logs any Disadvantage flag on a roll, so that row is compared with the
    model's any-Disadvantage rate, and Disadvantage left after cancelling (no Advantage on the roll) with its net
    rate."""
    rec = _roll_rec([(3, 3, 0, [20, 20, 20])] * 4)
    for r in rec["rounds"]:
        for j, p_ in enumerate(r["rolls"]["per_roll"]):
            p_.update(adv=j != 2, dis=True, net_adv=False)
        r["rolls"].update(known=3, dis=3, net_adv=0)
    gp = R.game_parts(rec)
    p = R.pooled([gp])
    rows = {r_[0]: r_ for r_ in R.compare_parts(p, {"split": True, "dis_any_rate": 0.95, "dis_rate": 0.3})}
    check("report: rolls with Disadvantage, cancelled or not (12 of 12), against the model's any-Disadvantage rate",
          rows["dis_rate"][2] == 1.0 and rows["dis_rate"][3] == 0.95 and rows["dis_rate"][5] == "" and
          "cancelled or not" in rows["dis_rate"][1], str(rows["dis_rate"]))
    check("report: rolls with net Disadvantage (4 of 12: no Advantage to cancel it) against the model's net rate",
          gp["net_dis"] == 4 and abs(rows["net_dis_rate"][2] - 4 / 12) < 1e-9 and rows["net_dis_rate"][3] == 0.3 and
          rows["net_dis_rate"][5] == "", str(rows["net_dis_rate"]))


def split_report_tests(R):
    """--report splits the character's own turn from its reactions in the enemies' turns, on the game's side as on
    the model's: riposte rolls (a Sneak Attack row 60 ms after the roll's is that roll's, its passive rider is damage
    but no roll) counted per round apart, their damage taken out of the own turn's; a model from before the split
    (no "split") or a record with no turn end times is not compared part by part."""
    rec = _roll_rec([(3, 3, 0, [25, 25, 25]), (3, 2, 1, [30, 20]), (3, 3, 0, [25, 25, 25]), (3, 3, 0, [20, 20, 20])],
                    react={1: [(27, 7, False)], 3: [(40, 14, True)], 4: [(0, 0, False)]})
    gp = R.game_parts(rec)
    check("split: reactions counted apart (3 rolls, 2 landed, 1 critical) with their damage and Sneak Attack",
          gp["split"] and gp["react_n"] == 3 and gp["react_landed"] == 2 and gp["react_crit"] == 1 and
          gp["react_dmg"] == 27 + 7 + 7 + 40 + 14 + 7 and gp["react_sneak"] == 21,
          str({k: gp.get(k) for k in ("react_n", "react_landed", "react_crit", "react_dmg", "react_sneak")}))
    check("split: the own turn's damage without the reactions', the total with them",
          gp["own"] == 75 + 50 + 75 + 60 and gp["total"] == gp["own"] + gp["react_dmg"] and gp["attacks"] == 12,
          str((gp["own"], gp["total"])))
    p = R.pooled([gp])
    check("split: per round values (own damage per landed roll over the own turn's damage only)",
          abs(p["react_attacks"] - 3 / 4) < 1e-9 and abs(p["react_dmg"] - 102 / 4) < 1e-9 and
          abs(p["dmg_per_hit"] - 260 / 11) < 1e-9 and abs(p["dpr"] - 362 / 4) < 1e-9 and
          abs(p["own_dpr"] - 260 / 4) < 1e-9, str({k: p[k] for k in ("react_attacks", "dmg_per_hit", "dpr")}))
    model = {"split": True, "react_attacks": 0.75, "react_dmg": 25.5, "attacks": 3.0, "own_dpr": 65.0, "dpr": 90.5}
    rows = {r_[0]: r_ for r_ in R.compare_parts(p, model)}
    check("split: own-turn and reaction parts compared with the model's split",
          rows["react_attacks"][3] == 0.75 and rows["attacks"][3] == 3.0 and rows["own_dpr"][3] == 65.0,
          str(rows["react_attacks"]))
    old = {r_[0]: r_ for r_ in R.compare_parts(p, {"attacks": 3.0, "react_dmg": 25.5, "dpr": 90.5})}
    check("split: a model from before the split is not compared part by part (damage per round still is)",
          old["attacks"][3] is None and old["react_dmg"][3] is None and old["dpr"][3] == 90.5, str(old["attacks"]))
    bare = dict(rec, rounds=[dict(r, tm={}) for r in rec["rounds"]])
    gb = R.game_parts(bare)
    nb = {r_[0]: r_ for r_ in R.compare_parts(R.pooled([gb]), model)}
    check("split: a record with no turn end times is not split and not compared part by part",
          gb["split"] is False and nb["attacks"][3] is None, str(gb.get("split")))


def v2_stat_tests(R):
    """Method v2's one statistic: the t-interval of the mean of run means on their logarithms, per side and for a
    pair's ratio."""
    gm, ci = R.mean_interval([100.0, 100.0, 100.0, 100.0])
    check("v2 stats: equal runs -> their value, a zero-width interval", abs(gm - 100) < 1e-9 and abs(ci[1] - ci[0]) < 1e-9)
    gm, ci = R.mean_interval([95.0, 105.0, 98.0, 102.0])
    check("v2 stats: four runs ~3% apart -> an interval of a few percent around 100 (t with 3 df)",
          99 < gm < 101 and 92 < ci[0] < 97 and 103 < ci[1] < 108, f"{gm} {ci}")
    check("v2 stats: one run has no interval", R.mean_interval([90.0])[1] is None)
    r, rci = R.ratio_interval([110.0, 112.0, 108.0, 111.0], [100.0, 101.0, 99.0, 100.0])
    check("v2 stats: a pair 10% apart with little spread -> its interval excludes 1", rci[0] > 1.05 and abs(r - 1.10) < 0.01,
          f"{r} {rci}")
    check("v2 stats: t quantiles by degrees of freedom", R.t975(3) == 3.182 and R.t975(11) == 2.228 and R.t975(100) == 1.96)


def _v2_rec(i, side, dpr, hit=40, crit=5, miss=15, valid=True, test_mode="automatic", run_id=None, scenario="boss"):
    dealt = [dpr] * 16
    return {"mode": "scripted", "pair": i, "side": side, "scenario": scenario, "real_rolls": True, "valid": valid,
            "invalid": [] if valid else ["ended: aborted"], "test_mode": test_mode, "run_id": run_id or f"{side}{dpr}",
            "spec_id": {"set_name": "S", "build": "b", "act": 3}, "req": {"char": "x_c1", "pair": i, "side": side},
            "rounds": [{"r": r + 1, "done": {"action": True},
                        "actions": [{"spell": "Projectile_MainHandAttack", "target": "@boss", "result": "done",
                                     "outcome": "hit"}]} for r in range(16)],
            "results": {"ended": "rounds done", "summary": {"dealt": dealt, "dpr": dpr, "rounds": 16,
                                                            "attacks": {"hit": hit, "crit": crit, "miss": miss}},
                        "hit_riders": {"hunters_mark": {"hits": 45, "rider": 44}}}}


def v2_run_tests(R):
    """Method v2 in run.py: the popup is set to Automatic right after loading, before any run; a side runs until it has
    --repeats valid runs (an invalid one is not counted, at most twice as many tries); the turn list is written per
    run; --report compares with the model's BOSS scenario part by part (not the day numbers), flags a part outside
    +-10%, lists manual runs apart without counting them, and gives one interval per side and per pair."""
    d = tempfile.mkdtemp(prefix="gauntlet_v2_")
    old = (R.engine.load, R.engine.run, R.engine.set_mode)
    try:
        boss = {"dpr": 100.0, "attacks": 3.75, "hit_rate": 0.75, "crit_rate": 0.08, "dmg_per_hit": 35.0}
        spec = {"set": "S", "act": 3, "expect": {"dpr": 60.0, "score": 70, "boss": boss}}
        pairs = [{"char": "astarion", "build": "b", "act": 3, "single": True, "specs": {"a": spec}}]
        sp, res = os.path.join(d, "specs.json"), os.path.join(d, "res.jsonl")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(pairs, f)
        log = []
        seq = iter([95.0, None, 100.0, 105.0, 98.0, 99.0])

        def fake_run(req, spec_):
            log.append(("run", req.get("pair"), req.get("side")))
            v = next(seq)
            if v is None:
                return dict(_v2_rec(0, "a", 1.0, valid=False), run_id=f"bad{len(log)}")
            return dict(_v2_rec(0, "a", v), run_id=f"ok{len(log)}")
        R.engine.load = lambda: "loaded"
        R.engine.run = fake_run
        R.engine.set_mode = lambda m: (log.append(("mode", m)), m)[1]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.main([sp, "--results", res, "--sides", "a,b"])
        runs = [x for x in log if x[0] == "run"]
        check("v2 runs: the popup is set to Automatic as the first step after loading", log[0] == ("mode", "automatic"),
              str(log[:2]))
        check("v2 runs: a side runs until 4 valid runs (the invalid one not counted); a side the entry lacks is skipped",
              len(runs) == 5 and all(x[2] == "a" for x in runs), str(runs))
        tdir = os.path.splitext(res)[0] + "_turns"
        check("v2 runs: a turn list per run next to the results", os.path.isdir(tdir) and len(os.listdir(tdir)) == 5)
        with open(os.path.join(tdir, sorted(x for x in os.listdir(tdir) if x.startswith("ok"))[0]), encoding="utf-8") as f:
            tl = f.read()
        check("v2 turns: round by round, the attack, its target and its result",
              "Round 1" in tl and "Projectile_MainHandAttack -> @boss: hit" in tl, tl[:200])
        with open(res, "a", encoding="utf-8") as f:
            f.write(json.dumps(_v2_rec(0, "a", 300.0, hit=10, crit=0, miss=50, test_mode="manual", run_id="man1")) + "\n")
            f.write(json.dumps(_v2_rec(0, "a", 50.0, scenario="pack")) + "\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = R.main(["--report", res, "--specs", sp])
        text = buf.getvalue()
        s = out["sides"][(0, "a")]
        check("v2 report: the 4 valid automatic runs only (the manual and the other scenario's runs not counted)",
              s["n"] == 4 and 98 < s["mean"] < 101, f"{s['n']} {s['mean']}")
        check("v2 report: compared with the model's boss scenario, not the day numbers",
              "model boss 100.0" in text and "60.0" not in text.split("Manual")[0], text[:600])
        rows = {r_[0]: r_ for r_ in s["rows"]}
        check("v2 report: part by part, a part within 10% unflagged (hit rate 0.75 vs 0.75)",
              rows["hit_rate"][5] == "" and abs(rows["hit_rate"][2] - 0.75) < 1e-9)
        check("v2 report: a part outside 10% flagged (crits 0.083 vs 0.08 is inside, attacks 3.75 vs 3.75 inside)",
              rows["attacks"][5] == "" and rows["crit_rate"][5] == "")
        check("v2 report: manual runs listed apart, flagged against the automatic runs",
              "Manual runs" in text and "man1" in text and "OUTSIDE" in text.split("Manual runs")[1], text[-500:])
        R.engine.load, R.engine.run, R.engine.set_mode = old
        tl2 = R.turn_list({"run_id": "p1", "test_mode": "manual", "valid": True, "req": {"char": "Astarion_11111111-2222-3333-4444-555555555555"},
                           "results": {"summary": {"dealt": [12]}},
                           "rounds": [{"r": 1, "casts": [{"who": "11111111-2222-3333-4444-555555555555", "spell": "Projectile_MainHandAttack"},
                                                         {"who": "boss", "spell": "Target_Bite"}]}],
                           "hits": [{"r": 1, "source": "11111111-2222-3333-4444-555555555555", "hit": True, "total": 12,
                                     "spell": "Projectile_MainHandAttack"}]})
        check("v2 turns: a player's turn lists its own casts and the hits they made, not the boss's",
              any("Projectile_MainHandAttack" in x for x in tl2) and not any("Target_Bite" in x for x in tl2) and
              any("hit 12" in x for x in tl2), str(tl2))
    finally:
        R.engine.load, R.engine.run, R.engine.set_mode = old
        shutil.rmtree(d, ignore_errors=True)


def engine_popup_tests():
    """engine.run goes through the popup's Start: the request (with its arena's definition) and the spec are written
    to the test file, the eval sets Automatic and calls GAUNTLET_TEST.start; a refused Start is an invalid run."""
    import engine as E
    E.pointer_off_ui = lambda *a, **k: None
    E.release_stuck_buttons = lambda *a, **k: []
    old = (E.ev, E.write_se, E.LOCK, E.RUNS)
    d = tempfile.mkdtemp(prefix="gauntlet_eng_")
    try:
        written, calls = {}, []
        E.write_se = lambda name, obj: written.__setitem__(name, obj)
        E.LOCK, E.RUNS = os.path.join(d, "lock"), d

        def ev(code, timeout=10.0, side="server"):
            calls.append(code)
            return "failed: no test file"
        E.ev = ev
        try:
            E.run({"label": "p", "arena": "house_of_hope", "char": "c1"}, {"set": "S"}, poll=0.0, log=lambda *a: None)
            raised = None
        except E.RunInvalid as e:
            raised = str(e)
        tf = written.get(E.TEST_FILE) or {}
        check("engine: a run writes the test file with its request, the arena's definition and the spec",
              tf.get("spec") == {"set": "S"} and (tf.get("req") or {}).get("arena_def", {}).get("level") == "CTY_Main_A"
              and tf["req"].get("run_id"), str(tf)[:200])
        check("engine: the start sets Automatic and presses the popup's Start in one eval",
              'setMode("automatic")' in calls[0] and "GAUNTLET_TEST.start(" in calls[0], calls[0][:120])
        check("engine: a refused Start is an invalid run with the reason", raised and "refused" in raised, str(raised))
        p = E.arm.__defaults__
        check("engine: arm takes the save's boss", p is not None and "boss" in E.arm.__code__.co_varnames)
        check("engine: every eval first points the harness globals at the test mod's copy (Script Extender keeps "
              "each mod's globals apart)", "Mods.LootAdvisorGauntletTest" in E.TESTMOD_GLOBALS["server"] and
              "GAUNTLET_TEST" in E.TESTMOD_GLOBALS["server"] and "GAUNTLET_UI" in E.TESTMOD_GLOBALS["client"])
        calls.clear()
        E.ev = lambda code, timeout=10.0, side="server": calls.append(code) or "true"
        r = E.load()
        check("engine: load keeps the test mod's packed harness in a save it armed (no second copy)",
              "test mod" in r and len(calls) == 1, f"{r} {len(calls)}")
    finally:
        E.ev, E.write_se, E.LOCK, E.RUNS = old
        shutil.rmtree(d, ignore_errors=True)


def no_outside_buff_tests():
    """No buff from outside the set: the catalogue lists none, run.py has no Haste variant, the harness applies no
    catalogue buff."""
    import catalog as C
    check("no outside buffs: the catalogue's buffs are empty for every act",
          all(v == [] for v in C.BUFFS.values()) and not hasattr(C, "HASTE"))
    with open(os.path.join(G_DIR, "gauntlet.lua"), encoding="utf-8") as fh:
        src = fh.read()
    check("no outside buffs: the harness applies none", "C.buffs" not in src and "C.haste" not in src)
    with open(os.path.join(G_DIR, "run.py"), encoding="utf-8") as fh:
        rsrc = fh.read()
    check("no outside buffs: run.py has no --haste", '"--haste"' not in rsrc)


def phase_call_tests():
    """The turn-dependent reaction answers are set where the turns change: the own turn's as the round starts, the
    enemies' after the turn's last fault check and before the character asks to end its turn, and the enemies' at the
    fight's start (they may act first)."""
    with open(os.path.join(G_DIR, "gauntlet.lua"), encoding="utf-8") as fh:
        src = fh.read()
    rs = src[src.index("local function roundStart(F)"):]
    rs = rs[:rs.index("\nend\n")]
    check("phase reactions: the own turn's answers set as each round starts", 'G.reactionsPhase(F, "own")' in rs)
    en = src[src.index('elseif F.state == "ending"'):]
    en = en[:en.index('elseif F.state == "ended"')]
    i_ph, i_end = en.find('G.reactionsPhase(F, "enemy")'), en.find("G.endTurn(F.char)")
    check("phase reactions: the enemies' answers set before the character asks to end its turn",
          0 <= i_ph < i_end, f"{i_ph} {i_end}")
    st = src[src.index("G.results.reactions = G.reactionsApply(F.plan"):]
    check("phase reactions: the enemies' answers set at the fight's start",
          st[:400].find('G.reactionsPhase(F, "enemy")') >= 0)


# ============================================================================================ mutations
GL, PL, RN, EN, PA = "gauntlet.lua", "plan.py", "run.py", "engine.py", "pairs.py"
TL = "gauntlet_test.lua"
TB = "testmod/LootAdvisorGauntletTest/Mods/LootAdvisorGauntletTest/ScriptExtender/Lua/BootstrapServer.lua"
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
     "F.enemyFaction = (F.lane and F.lane.enemy_faction) or C.enemy_faction or G.ENEMY_FACTION",
     "F.enemyFaction = C.enemy_faction or G.ENEMY_FACTION"),
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
    ("item resources: a status put on as the item goes on ignored", PL,
     '        nxt = _applied_statuses(st.get("OnApplyFunctors"), stats)', "        nxt = []"),
    ("item resources: a status put on at a long rest ignored", PL,
     '            nxt += _applied_statuses(st.get("StatsFunctors"), stats)', "            pass"),
    ("item resources: a status reached twice counted twice", PL, "        if sid in seen or depth > 4:",
     "        if depth > 4:"),
    ("item resources: turn resources counted", PL,
     '            if kind in TURN_RESOURCES or kind.startswith("Interrupt_"):', "            if False:"),
    ("item resources: conditional boosts counted", PL, ' if not b.startswith("IF(")', ""),
    ("out of combat: spells allowed only out of combat planned", PL, "    if out_of_combat_only(stats, spid):",
     "    if False:"),
    ("setup: the items' resources not expected", GL,
     '    cmp("resource " .. r.kind, r.n + (fromItems[k] or 0), (now_.resources or {})[k])',
     '    cmp("resource " .. r.kind, r.n, (now_.resources or {})[k])'),
    ("setup: the items' spell slots not expected", GL, ' + (fromItems["SpellSlot:" .. lv] or 0)', ""),
    ("setup: a resource only the items give not checked", GL,
     '    if r.kind ~= "SpellSlot" and not seen[k] then', '    if false then'),
    ("summon: its turn left alone", GL, "    if not activeTurn(F.char) then G.summonStep(F, t) end\n",
     ""),
    ("summon: not a turn holder for the watchdog", GL, "  for _, s in ipairs(summonsOnTurn(F)) do out[#out + 1] = s end\n",
     ""),
    ("npc park: nobody moved", GL, "      if near then\n", "      if false then\n"),
    ("npc park: party members moved", GL, "    if u and not party[u] and not G.movedNpcs[u]", "    if u and not G.movedNpcs[u]"),
    ("npc park: summons moved", GL, " and try(Osi.IsSummon, u) ~= 1\n", "\n"),
    ("npc park: margin ignored", GL, "<= A.radius + (margin or 0) then near = true end", "<= A.radius then near = true end"),
    ("npc park: never put back after the lanes", GL, "  L.npcs_restored = G.npcsBack()\n", ""),
    ("npc park: never put back on abort", GL, "  if G.movedNpcs and not (G.LANES and G.LANES.on) then G.npcsBack() end\n",
     ""),
    ("npc park: the lanes' runner does not move them", GL, "    L.npcs_moved = G.npcsAway(areas, LS.npc_park, LS.margin)\n",
     ""),
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
    ("cast: the engine moves before a cast", GL, "  return pcall(Osi.UseSpell, u, spell, tgt, tgt, 1)",
     "  return pcall(Osi.UseSpell, u, spell, tgt)"),
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
    ("own turn: end-turn request re-sent on the clock", GL, "if G.endTurnDropped(F) then G.endTurn(F.char) end",
     "G.endTurn(F.char)"),
    ("own turn: a dropped end-turn request never re-sent", GL, "if G.endTurnDropped(F) then G.endTurn(F.char) end",
     "if false then G.endTurn(F.char) end"),
    ("own turn: TurnEnded ignored", GL,
     "if F.turnEndedAt and F.turnEndedAt >= (F.endAskedAt or 0) then return false end", ""),
    ("watchdog: recovery on the clock, activity ignored", GL,
     "if t - math.max(F.waitAt or t, F.activeAt or 0) <= G.HOLDER_IDLE_MS then return false end",
     "if t - (F.waitAt or t) <= G.HOLDER_IDLE_MS then return false end"),
    ("watchdog: a casting holder not waited for", GL, "if casting(h) then F.activeAt = t; return false end",
     "if false then return false end"),
    ("watchdog: events not noted as activity", GL,
     'if G.member(F, (select(i, ...))) then F.activeAt = now(); return end', "if false then return end"),
    ("watchdog: no absolute cap", GL, "elseif t > F.deadline or (not F.manual and G.turnIdle(F, t, turnHolders)) then",
     "elseif not F.manual and G.turnIdle(F, t, turnHolders) then"),
    ("turns: TurnStarted / TurnEnded not recorded", GL,
     'R.turns[#R.turns + 1] = { who = uuid(who), ev = started and "started" or "ended", t = now() - G.t0 }', ""),
    ("cast ids: UsingSpell row without its id", GL,
     "R.usings[#R.usings + 1] = { who = uuid(caster), spell = spell, t = now() - G.t0, sid = sid }",
     "R.usings[#R.usings + 1] = { who = uuid(caster), spell = spell, t = now() - G.t0 }"),
    ("cast ids: CastedSpell row without its id", GL,
     "R.casts[#R.casts + 1] = { who = uuid(caster), spell = spell, t = now() - G.t0, sid = sid }",
     "R.casts[#R.casts + 1] = { who = uuid(caster), spell = spell, t = now() - G.t0 }"),
    ("cast ids: CastSpellFailed row without its id", GL,
     "local f = { who = uuid(caster), spell = spell, t = now() - G.t0, sid = sid }",
     "local f = { who = uuid(caster), spell = spell, t = now() - G.t0 }"),
    ("cast ids: AttackedBy row without its id", GL, "type = dtype, amount = amount, cause = cause, sid = sid }",
     "type = dtype, amount = amount, cause = cause }"),
    ("cast ids: hit row ignores the hit's own id", GL, 'sid = first(e, { "Hit.StoryActionId", "StoryActionId" })',
     'sid = first(e, { "StoryActionId" })'),
    ("cast ids: hit row without the cast guid", GL, 'cast_guid = first(hit, { "SpellCastGuid" })', "cast_guid = nil"),
    ("cast ids: the pending cast's id never bound", GL, "if P and P.sid == nil then G.bindSid(P, R) end", ""),
    ("cast ids: the pending cast's id from anyone's UsingSpell", GL,
     "    if x.who == P.who and baseSpell(x.spell) == baseSpell(P.spell) then\n      P.sid = x.sid",
     "    if baseSpell(x.spell) == baseSpell(P.spell) then\n      P.sid = x.sid"),
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
    ("plan: item passives not scanned", PL, 'scan(sid, ("PassivesOnEquip",) + ', "scan(sid, () + "),
    ("engine: no retry on a missed eval", EN, "if misses >= max_misses:", "if misses >= 1:"),
    ("engine: start never re-sent", EN, "elif not seen and not resent and polls >= 3:", "elif False:"),
    ("equip: no second ask", GL, "          pcall(Osi.Equip, u, e.it, 1, 0, 0)\n", ""),
    ("equip: no wait for the equip", GL, "    if #open > 0 and (waited < G.EQUIP_MS or loading or not open[1].again) then",
     "    if false then"),
    ("equip: a slow frame skips the second ask", GL,
     "    if #open > 0 and (waited < G.EQUIP_MS or loading or not open[1].again) then",
     "    if #open > 0 and (waited < G.EQUIP_MS or loading) then"),
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
    ("refusal: CastSpellFailed ignored", GL,
     "if P.player then refused = G.playerRefused(P, R, t) else refused = G.castRefused(P, R.cast_fails) end",
     "refused = nil"),
    ("refusal: any caster's failure counts", GL, "if f.who == P.who and baseSpell(f.spell) == baseSpell(P.spell) then",
     "if baseSpell(f.spell) == baseSpell(P.spell) then"),
    ("refusal: Attack of Opportunity not named", GL,
     'if tostring(x.interrupt):find("AttackOfOpportunity", 1, true) then aoo = true end', ""),
    ("start: Attacks of Opportunity banned", GL, "        G.results.ignore_leave_attack_range = false",
     "        boost(u, G.AOO_BOOST); G.results.ignore_leave_attack_range = false"),
    ("start: HP buffer given", GL, "G.HP_BUFFER = 0", "G.HP_BUFFER = 200"),
    ("refusal: no retry after an Attack of Opportunity", GL,
     '    and (tries > 0 or anyRefusal or reason.why:find("Attack of Opportunity", 1, true)) then',
     "    and false then"),
    ("refusal: any refusal retried", GL,
     '    and (tries > 0 or anyRefusal or reason.why:find("Attack of Opportunity", 1, true)) then',
     "    then"),
    ("refusal: retry_any_refusal on by default", GL, "G.CAST_RETRIES, G.RETRY_ANY_REFUSAL = 2, false",
     "G.CAST_RETRIES, G.RETRY_ANY_REFUSAL = 2, true"),
    ("refusal: retry_any_refusal ignored", GL,
     "  local anyRefusal = (F.req and F.req.retry_any_refusal) or G.RETRY_ANY_REFUSAL",
     "  local anyRefusal = false"),
    ("refusal: retries without a limit", GL, "G.CAST_RETRIES, G.RETRY_ANY_REFUSAL = 2, false",
     "G.CAST_RETRIES, G.RETRY_ANY_REFUSAL = 99, false"),
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
     "if u and not party[u] and u ~= except and standing(u) and inArena(u, A) then",
     "if u and not party[u] and u ~= except and not (G.spawned or {})[u] and standing(u) and inArena(u, A) then"),
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
    ("summon: its turn ended instead of attacking", GL, "      return G.summonBegin(F, s, t)", "      G.endTurn(s)"),
    ("summon: a refused attack does not fail the run", GL, "  if smiss > 0 then causes", "  if false then causes"),
    ("summon: its damage not the side's", GL, '(F.summons or {})[row.source or ""] == true', "false"),
    ("summon: an attack counted without evidence", GL, "  local ev = G.castEvidence(P, R.casts, G.dmg, nil)",
     '  local ev = "cast"'),
    ("summon: the engine moves it before the attack", GL, "local ok, err = G.castRequest(F, S.u, S.spell, S.tgt)",
     "local ok, err = pcall(Osi.UseSpell, S.u, S.spell, S.tgt)"),
    ("item rule: the item takes the first action in a surge round", GL,
     '    elseif it.group == "action" and G.hasSurge(out) then', "    elseif false then"),
    ("toggles: never switched", GL, "    if before ~= nil and before ~= on then rec.method = flip(u, id, on) end", ""),
    ("toggles: not compared", GL,
     '  for id, want in pairs(spec.toggles or {}) do cmp("toggle " .. id, want, G.toggleState(u, id)) end', ""),
    ("toggles: never restored", GL, "      if now_ ~= nil and now_ ~= was then flip(key, id, was); n = n + 1 end", ""),
    ("carry-over: concentration kept", GL, "  pcall(Osi.ApplyStatus, u, G.BREAK_CONCENTRATION, 0.1, 1, u)", ""),
    ("carry-over: HUNTERS_MARK on others kept", GL, "    for _, st in ipairs(c and G.CARRY_STATUSES or {}) do",
     "    for _, st in ipairs({}) do"),
    ("carry-over: statuses outside the baseline kept", GL,
     "    if not base[st] and not G.technicalStatus(st) then\n      pcall(Osi.RemoveStatus",
     "    if false then\n      pcall(Osi.RemoveStatus"),
    ("setup: concentration not compared", GL, '  cmp("no concentration", "none", G.concentration(u) or "none")', ""),
    ("setup: carried statuses not compared", GL, 'cmp("no carried status " .. st, false, true)', ""),
    ("crits: blockers left on the enemy", GL, 'if b.kind == "passive" and pcall(Osi.RemovePassive, d, b.id)',
     'if false and pcall(Osi.RemovePassive, d, b.id)'),
    ("crits: not in the setup check", GL,
     '    cmp("enemy " .. i .. " can be critically hit", "yes", #bl == 0 and "yes" or table.concat(names, ", "))', ""),
    ("enemy: statuses at the start not compared", GL,
     '    cmp("enemy " .. i .. " statuses at start", "none", #sts == 0 and "none" or table.concat(sts, ", "))', ""),
    ("effects: item passives not compared", GL,
     '    cmp("item passive " .. x.passive, true, try(Osi.HasPassive, u, x.passive) == 1)', ""),
    ("effects: item statuses not compared", GL,
     '    cmp("item status " .. x.status, true, try(Osi.HasActiveStatus, u, x.status) == 1)', ""),
    ("effects: elixir statuses not compared", GL,
     '        cmp("elixir status " .. st, true, try(Osi.HasActiveStatus, u, st) == 1)', ""),
    ("effects: item boosts not compared", GL,
     'for _, x in ipairs(spec.item_boosts or {}) do cmp("item boost " .. x.boost, true, G.hasBoost(boosts, x.boost)) end',
     ""),
    ("effects: weapon dice not compared", GL, "    if it.weapon and eq[it.slot] then", "    if false then"),
    ("effects: item spell cooldown not compared", GL,
     '    cmp("item spell " .. a.spell .. " ready", false, onCooldown(u, a.spell))', ""),
    ("effects: item spell book not compared", GL,
     '    cmp("item spell " .. a.spell .. " in the book", true, (book or {})[a.spell] == true)', ""),
    ("riders: a missing rider not recorded", GL, "      if not seen then\n        local miss",
     "      if false then\n        local miss"),
    ("riders: missing riders ignored by the verdict", GL, "  if results.rider_misses and #results.rider_misses > 0 then",
     "  if false then"),
    ("riders: the turn's starting statuses ignored", GL,
     "for _, st in ipairs(R.turn_statuses or {}) do if st == rd.status then seen = true end end", ""),
    ("status log: every creature logged", GL, "  if not G.member(F, obj) then return end", ""),
    ("hits: critical flag ignored", GL, '  row.crit = f:find("Critical", 1, true) ~= nil', "  row.crit = false"),
    ("hits: every creature's hits logged", GL, "  if not ms and not mt then return end", ""),
    ("plan: Dread Ambusher waits for the action", PL,
     'opening.insert(0, A(dread, "free", "@boss", "Dread Ambusher attack", granted_by="DREAD_AMBUSHER"))',
     'opening.append(A(spell, "free", "@boss", "Dread Ambusher attack", requires="action"))'),
    ("plan: status-granted spells expected in the book", PL,
     '                if not a.get("granted_by") and not a.get("move_to"):', '                if not a.get("move_to"):'),
    ("evade: the move expected in the book", PL,
     '                if not a.get("granted_by") and not a.get("move_to"):', '                if not a.get("granted_by"):'),
    ("plan: item spells the model dropped are intended", PL,
     'return any(e.get("spell") == spell and not e.get("dropped") and', 'return any(e.get("spell") == spell and'),
    ("plan: the test plan's toggles ignored", PL, "    if plan_toggles is not None:", "    if False:"),
    ("item checks: conditional boosts expected", PL, 'if not b.startswith("IF(")]', "]"),
    ("item checks: weapon dice not from the sheet row", PL,
     r'            m = re.match(r"(\d+d\d+)\s+(\w+)", ((row.get("dmgf") or [""])[0]) or "")', "            m = None"),
    ("riders: none listed", PL, "            if hit and (hit[0], hit[1]) not in seen:", "            if False:"),
    ("fail fast: a start mismatch fought anyway", GL,
     'if sc and #sc.mismatches > 0 and (G.FAIL_FAST or F.popup) then return stop(F, "setup mismatch at the start") end',
     ""),
    ("fail fast: a void round fought on", GL, "    if fault then return finish(F, fault) end\n", ""),
    ("fail fast: an idle round is no fault", GL,
     "if (F.S or {}).char_acts ~= false and not (R.done and (R.done.action or R.done.item)) then", "if false then"),
    ("fail fast: a refused cast is no fault", GL, "  if (R.cast_misses or 0) > 0 then\n", "  if false then\n"),
    ("watchdog: a combat that ended is waited out", GL, "    elseif not F.manual and G.combatLost(F, t) then",
     "    elseif false then"),
    ("watchdog: no reading of the combat", GL, "  return inC == 0 and t - F.inCombatAt > G.COMBAT_LOST_MS",
     "  return false"),
    ("last round: a 17th turn waited for", GL,
     "      if G.round >= F.rounds then\n        F.lastCut = true\n        return finish(F)\n      end\n", ""),
    ("summary: damage before round 1 dropped", GL,
     "if row.r == 0 and row.target == me then pre = pre + (row.amount or 0) end", ""),
    ("summary: damage taken over all rounds", GL, "local turns = #G.rounds - (F.lastCut and 1 or 0) + (F.enemyFirst and 1 or 0)",
     "local turns = #G.rounds"),
    ("cleanup: corpses waited for", GL, "  if #list == 0 then\n    if cb then cb({ removed = 0, killed = {} }) end",
     "  if false then\n    if cb then cb({ removed = 0, killed = {} }) end"),
    ("equip: one item per frame", GL, "        worn[#worn + 1] = e\n", "        rings[#rings + 1] = { e }\n"),
    ("equip: rings asked together", GL, "        rings[#rings + 1] = { e }\n", "        worn[#worn + 1] = e\n"),
    ("equip: given up while nothing is worn", GL, "local loading = S.worn == 0 and waited < G.READY_MS",
     "local loading = false"),
    ("buffs: never put on again", GL, "      for _, st in ipairs(missing) do pcall(Osi.ApplyStatus, u, st, -1, 1, u) end\n",
     ""),
    ("spawn: forced stats not waited for", GL, "    if not forced() and polls * G.POLL_MS < G.SPAWN_MS then",
     "    if polls * G.POLL_MS < G.SPAWN_MS then"),
    ("sheet: max HP with temporary hit points", GL, "  return o - ((e and try(function() return e.Health.TemporaryHp end)) or 0)", "  return o"),
    ("elixir: statuses read at once", GL, "G.POLL_MS, G.EQUIP_MS, G.USE_MS, G.READY_MS = 100, 2000, 3000, 45000",
     "G.POLL_MS, G.EQUIP_MS, G.USE_MS, G.READY_MS = 100, 2000, 500, 45000"),
    ("items: a refused creation not asked again", GL, "    return #todo == 0 or made > 0 or tries * G.REAPPLY_MS >= G.READY_MS",
     "    return true"),
    ("stopping: rounds pooled, not compared by number", RN, "    mk = {k: mean(v) for k, v in pool.items()}",
     "    mk = {k: 0.0 for k in pool}"),
    ("scheduling: the results file not read", RN,
     "    got = {i: prior_runs(a.results, i, pairs[i], scen, not a.no_real_rolls) for i in todo}",
     '    got = {i: {"a": [], "b": []} for i in todo}'),
    ("scheduling: another set's runs counted", RN, ' or not same_set(r, p, r["side"]):', ":"),
    ("scheduling: a deterministic failure repeated", RN, "                    if why and k == 0:",
     "                    if False:"),
    ("lanes across pairs: never", RN, '        if getattr(a, "lanes", None):\n            for j, (i2, side2)',
     '        if False:\n            for j, (i2, side2)'),
    ("lanes across pairs: spacing ignored", RN, "                if ok:\n                    mate = (left.pop(j), need)",
     "                if True:\n                    mate = (left.pop(j), need)"),
    ("lanes across pairs: one character in both lanes", RN,
     "if i2 == i or char_for(a, pairs[i]) == char_for(a, pairs[i2]) or not char_for(a, pairs[i]):", "if i2 == i:"),
    ("lanes across pairs: no swap", RN, "out.append((pair_ if k % 2 == 0 else pair_[::-1], mate[1]))",
     "out.append((pair_, mate[1]))"),
    ("plan gaps: the extra action every turn", GL, "    if a.if_status and not has[a.if_status] then", "    if false then"),
    ("plan gaps: GWM's bonus attack asked without its status", GL,
     "  if a.when_status and try(Osi.HasActiveStatus, F.char, a.when_status) ~= 1 then", "  if false then"),
    ("evade: Disengage with the boss out of reach", GL,
     "    if not b or not dist(F.char, b) or dist(F.char, b) > G.REACH then", "    if false then"),
    ("evade: a move with nowhere to go not counted", GL,
     '    rec.result, rec.optional = "failed: no spot for " .. tostring(a.move_to) .. " in the arena", false',
     '    rec.result = "failed: no spot for " .. tostring(a.move_to) .. " in the arena"'),
    ("evade: a leave spot inside 3 m of the boss", GL,
     "    local clear = not bx or math.sqrt((p[1] - bx) ^ 2 + (p[3] - bz) ^ 2) >= need - 0.7",
     "    local clear = true"),
    ("first turn: the combat's first request sent as early as any other", GL,
     "t + (G.round == 1 and G.FIRST_ACT_DELAY_MS or G.ACT_DELAY_MS), t", "t + G.ACT_DELAY_MS, t"),
    ("Action Surge: done before its action point is in", GL,
     "    if (resAmount(F.char, \"ActionPoint\") or 0) > (P.ap0 or 0) or t - (P.t0 or t) >= G.CAST_MAX_MS then",
     "    if true then"),
    ("Action Surge: done once its status is on (the action point comes later)", GL,
     "    if (resAmount(F.char, \"ActionPoint\") or 0) > (P.ap0 or 0) or",
     "    if try(Osi.HasActiveStatus, F.char, \"ACTION_SURGE\") == 1 or"),
    ("strategy spec: the item rule keeps its item spells", PL, '    plan["item_actions"] = []\n', ""),
    ("record: the JSON-safe copy's Stringify unprotected", GL,
     "    okj, text = pcall(Ext.Json.Stringify, G.jsonSafe(rec))\n",
     "    okj, text = true, Ext.Json.Stringify(G.jsonSafe(rec))\n"),
    ("record: a value Stringify refuses kept as it is", GL, "  if t ~= \"table\" then return tostring(v) end",
     "  if t ~= \"table\" then return v end"),
    ("impact wait: the step loop never waits for the last attack to land", GL,
     "    if G.impactPending(F, t, G.dmg, G.hits) then F.next = t + G.POLL_MS; return end\n", ""),
    ("impact wait: the attack's damage row not waited for", GL, "  if not first then return true end\n", ""),
    ("impact wait: no quiet spell after the row", GL,
     "  if rel - (last or first) < G.IMPACT_QUIET_MS then return true end\n", ""),
    ("impact wait: a toggled attack's off-hand half not waited for", GL,
     "  if P.toggled and P.dual and not G.offhandFired(P, dmg, hits) and rel - first < G.OFFHAND_MS then return true end\n",
     ""),
    ("impact wait: a confirmed player cast never remembered", GL,
     "    if P.player then F.lastCast = { P = P, t = t } end\n", ""),
    ("evade: a path that stops short of the ring gives no spot", GL,
     "G.cutAt({ x0, y0, z0 }, pts, g[1], g[2], g[3], G.LEAVE_SNAP_M, budget)",
     "G.cutAt({ x0, y0, z0 }, pts, g[1], g[2], g[3], 0.6, budget)"),
    ("dual wield: the off-hand half never paid", GL, "    if G.offhandFired(P, G.dmg, G.hits) then\n", "    if false then\n"),
    ("dual wield: any Offhand row counted", GL, "    if d.source == P.who or d.owner == P.who then\n      local cause",
     "    if true then\n      local cause"),
    ("off-hand half: a melee second strike not counted (cause only)", GL,
     "        if not first then first = d.t elseif d.t - first > G.ROLL_MERGE_MS then return true end\n", ""),
    ("off-hand half: a rider row taken for a second strike", GL,
     "elseif d.t - first > G.ROLL_MERGE_MS then return true end", "elseif d.t - first > 0 then return true end"),
    ("off-hand half: the hit log's last attack not read", GL,
     "    if h.source == P.who and f:find(\"LastAttack\", 1, true) and not f:find(\"FirstAttack\", 1, true) then",
     "    if false then"),
    ("off-hand half: the spend check ignores the damage rows", GL,
     "  local fired = P.dual and G.offhandFired(P, G.dmg, G.hits)", "  local fired = P.dual and G.offhandFired(P, {}, G.hits)"),
    ("surge: the surge's first attack booked free", PL,
     'opening + [A(spell, "action", "@boss", "Action Surge attack", requires="surge")]',
     'opening + [A(spell, "free", "@boss", "Action Surge attack", requires="surge")]'),
    ("surge: Action Surge gives no action", PL, ', per="short", grants="ActionPoint:1")', ', per="short")'),
    ("surge: the forecast ignores what a step gives", PL, "                        turn[k] = turn.get(k, 0) + n\n",
     "                        pass\n"),
    ("rest reset: a rest cooldown (-1) read as ready", GL, '  return type(v) == "number" and v ~= 0',
     '  return type(v) == "number" and v > 0'),
    ("rest reset: no restoration status between runs", GL,
     '  if kind == "long" then pcall(Osi.ApplyStatus, u, G.REST_STATUS, 0, 1, u) end\n', ""),
    ("rest reset: reset entries kept", GL,
     "    if kept == 0 and #cds > 0 then pcall(function() e.SpellBookCooldowns.Cooldowns = {} end) end\n", ""),
    ("rest reset: a long-rest cooldown reset on a short rest", GL,
     '      if kind == "long" or t:match("ShortRest") or t:match("Turn") or t:match("Combat") then\n',
     '      if true then\n'),
    ("setup: the plan's once-per-rest steps not checked ready", GL,
     '  for _, sp in ipairs(G.restSpells(F.plan or spec.plan)) do cmp("spell " .. sp .. " ready", false, '
     'onCooldown(u, sp)) end\n', ""),
    ("player cast: a melee weapon attack sent as a projectile", GL,
     "  local target = { TargetingType = tt, Position = { x, y, z } }",
     '  local target = { TargetingType = spell:find("Attack") and "Projectile" or tt, Position = { x, y, z } }'),
    ("dual wield: the turn's planned bonus actions not reserved", GL,
     "  local on = a.dual ~= false and resAmount(F.char, \"BonusActionPoint\") - G.reservedBonus(F) >= 1",
     "  local on = a.dual ~= false and resAmount(F.char, \"BonusActionPoint\") >= 1"),
    ("dual wield: optional bonus actions reserved", GL, "    if q.group == \"bonus\" and not q.optional then n = n + 1 end",
     "    if q.group == \"bonus\" then n = n + 1 end"),
    ("dual wield: the toggle never set", GL, "    toggled, togglePrev, toggleField = G.dualToggle(F, a)\n", ""),
    ("dual wield: the toggle not put back", GL, "    e.DualWielding[P.toggleField] = P.togglePrev\n", ""),
    ("player cast: not the default", GL, "G.PLAYER_CAST = true\n", "G.PLAYER_CAST = false\n"),
    ("player cast: the old path gone", GL, "  if F.playerCast then\n    local req, why", "  if true then\n    local req, why"),
    ("player cast: an Ignore* option kept", GL, '{ "FromClient", "ShowPrepareAnimation",',
     '{ "FromClient", "IgnoreCastChecks", "ShowPrepareAnimation",'),
    ("player cast: the TargetingType guessed", GL, "  return t and G.TARGETING_TYPES[t] and t or nil",
     '  return t or "Projectile"'),
    ("player cast: no rolls asked for anyway", GL, "  if F and F.realRolls == false then opts", "  if false then opts"),
    ("player cast: the CastSpellFailed before an accepted cast counted as a refusal", GL,
     "  if G.usingSeen(P, R) then return nil end\n", ""),
    ("player cast: a refusal not waited for", GL, "  if t - P.failAt < G.PLAYER_FAIL_MS then return nil end\n", ""),
    ("player cast: a refusal asked for again", GL, "  if refused and not P.player and tries < G.CAST_RETRIES",
     "  if refused and tries < G.CAST_RETRIES"),
    ("player cast: a range or sight refusal leaves the run valid", GL,
     '      G.castFault(R, P.spell, "movement", "the plan\'s movement was wrong: " .. why)\n', ""),
    ("player cast: a spell it cannot send leaves the run valid", GL,
     '      G.castFault(R, a.spell, "request", "the player path cannot send it: " .. tostring(err))\n', ""),
    ("player cast: what was spent never checked", GL,
     "    if P.player then G.checkSpent(F, R, P) else\n", "    if P.player then else\n"),
    ("hit costs: not read from the spell's data", GL,
     "  return parseCosts(st and try(function() return st.HitCosts end))", "  return {}"),
    ("hit costs: not needed to afford the step", GL,
     "  local ok, why = canPay(F.char, addCosts(costs, G.hitCosts(a)))", "  local ok, why = canPay(F.char, costs)"),
    ("hit costs: owed on a miss too", GL,
     "    elseif landed == false then owed = addCosts(owed, G.noCosts(P.hit))",
     "    elseif landed == false then owed = addCosts(owed, P.hit)"),
    ("hit costs: a die spent on a miss passes", GL,
     "    elseif landed == false then owed = addCosts(owed, G.noCosts(P.hit))", "    elseif landed == false then"),
    ("hit costs: not owed after a hit", GL, "    if landed then owed = addCosts(owed, P.hit)",
     "    if landed then maybe = addCosts(maybe, P.hit)"),
    ("hit costs: a miss read as a hit", GL, "      return not h.miss\n", "      return true\n"),
    ("hit costs: a 0 damage row read as a hit", GL, "      return (d.amount or 0) > 0\n", "      return true\n"),
    ("hit costs: left in the plan's use cost", PL, "if x.strip() and _cost_kind(x.split(\":\")[0].strip()) not in kinds)",
     "if x.strip())"),
    ("hit costs: not in the forecast", PL, "                costs += parse_costs(a.get(\"hit_cost\"))\n", ""),
    ("reactions: a weapon's hand passives ignored", PL,
     "((HAND_PASSIVES[slot],) if slot in HAND_PASSIVES else ())", "()"),
    ("reactions: the other hand's passives", PL,
     '"MeleeOffHand": "PassivesOffHand", "RangedOffHand": "PassivesOffHand"}',
     '"MeleeOffHand": "PassivesMainHand", "RangedOffHand": "PassivesMainHand"}'),
    ("player cast: checked before the cast's end", GL,
     '    if ev ~= "cast" and not failedEnd and t - (P.t0 or t) < G.CAST_MAX_MS then return false end\n', ""),
    ("player cast: a started cast with no evidence given up at CONFIRM_MS", GL,
     "  local started = casting(F.char) or (P.player and G.usingSeen(P, R))\n",
     "  local started = casting(F.char)\n"),
    ("player cast: a CastSpellFailed of any id ends the cast", GL,
     "    for _, x in ipairs(list) do if x.who == P.who and x.sid == P.sid then return true end end",
     "    for _, x in ipairs(list) do if x.who == P.who then return true end end"),
    ("player cast: a same-id CastSpellFailed waits the full cap", GL,
     '    local failedEnd = ev ~= "cast" and G.failedAfterStart(P, R)', "    local failedEnd = false"),
    ("sheath gate: the character's own last attack holds the turn", GL,
     "  if spell and (F.asked or {})[baseSpell(spell)] then", "  if false then"),
    ("sheath gate: what the harness asked for not noted", GL, "    F.asked[baseSpell(spell)] = true\n", ""),
    ("Sneak Attack per turn: a riposte's (enemy phase) counted for the own turn", GL,
     '    if x.who == me and x.phase ~= "enemy" and tostring(x.interrupt):find("SneakAttack", 1, true) then',
     '    if x.who == me and tostring(x.interrupt):find("SneakAttack", 1, true) then'),
    ("Sneak Attack per turn: a cast after the turn's release counted", GL,
     " and not (released and c.t and c.t > released) then", " then"),
    ("Sneak Attack per turn: a turn without the charge counted as one that could", GL,
     "    if adv and charged then sa.adv_turns = sa.adv_turns + 1 end", "    if adv then sa.adv_turns = sa.adv_turns + 1 end"),
    ("move: a leave ended short always fails (the spot test only)", GL,
     '    if m.result == "ended short" then met, d, why = G.moveGoalMet(F, a) end', "    if false then end"),
    ("move: a Threatened character counted out of reach", GL,
     '  if try(Osi.HasActiveStatus, F.char, "FLANKED") == 1 then return false, d, "Threatened (FLANKED)" end', ""),
    ("move: within the close range counted as left", GL,
     '  if d <= G.CLOSE_M then return false, d, "within the close range" end', ""),
    ("move: the floor distance shortened (slack or height added)", GL,
     "  local d = math.sqrt((x - bx) ^ 2 + (z - bz) ^ 2)", "  local d = math.sqrt((x - bx) ^ 2 + (z - bz) ^ 2) - 0.6"),
    ("move: a hide spot ended short counted as reached", GL,
     '  if a.move_to ~= "@leave_spot" then return false, nil, "not a leave" end', "  if false then end"),
    ("camera: not moved at each own turn", GL,
     "G.BOSS_HP_PCT) end\n  pcall(G.cameraFollow, F)\n", "G.BOSS_HP_PCT) end\n"),
    ("camera: onto the character alone (the boss not sent)", GL,
     '  G.notify({ kind = "camera_follow", char = uuid(F.char), also = b and uuid(b) or nil })',
     '  G.notify({ kind = "camera_follow", char = uuid(F.char) })'),
    ("leave: the nearest clear spot taken (the centre ignored)", GL,
     "  local c = to == \"@leave_spot\" and A.center or nil", "  local c = nil"),
    ("leave: a spot beyond the turn's movement preferred for the centre", GL,
     "    local dc = (c and d <= budget) and", "    local dc = c and"),
    ("far: back on the start spot counts as far again", GL, "  if not at then F.boss_left = true end\n", ""),
    ("record: the boss's position at the character's turn start left out", GL, '  G.noteBossAt(F, R, "own_start")\n',
     ""),
    ("record: the boss's position at the end of its turn left out", GL,
     '    if m == "enemy" and not started then G.noteBossAt(F, R, "boss_end", who) end\n', ""),
    ("record: another enemy's turn end recorded as the boss's", GL,
     "  if not b or (who and uuid(who) ~= uuid(b)) then return end", "  if not b then return end"),
    ("record: the gap after a leave only when it ended short", GL,
     '    if a.move_to == "@leave_spot" then\n      local _, gap',
     '    if a.move_to == "@leave_spot" and m.result == "ended short" then\n      local _, gap'),
    ("record: the character's own saves recorded as the boss's", GL,
     '    local v = G.addSave(R, row, "component", true)', '    local v = G.addSave(R, row, "component")'),
    ("record: a made save takes a status", GL,
     "      if v.success == false then v.status = x.status else v.status_made = x.status end",
     "      v.status = x.status"),
    ("record: a rider taken as a save's status", GL, "G.SAVE_NOT = { HUNTERS_MARK = true, TRUE_STRIKE = true }",
     "G.SAVE_NOT = {}"),
    ("record: a status just before its save never linked", GL,
     "  if not v or v.success == nil or v.status or v.status_made then return end", "  if true then return end"),
    ("saves: RollResult registered with the wrong number of arguments", GL, '"RollResult", 6,', '"RollResult", 4,'),
    ("saves: the character's Osiris rolls recorded", GL,
     '  if not G.fighting or G.member(G.F, roller) ~= "enemy" then return end', "  if not G.fighting then return end"),
    ("saves: result 1 read as a failed roll", GL,
     "  if n == 1 then success = true elseif n == 0 then success = false end",
     "  if n == 0 then success = true elseif n == 1 then success = false end"),
    ("saves: the two sources never merged", GL,
     "    if sameRoll(v, row, kind) then return G.mergeSave(v, row, kind) end\n", ""),
    ("saves: a component waiting for its Osiris roll never claimed", GL,
     '      G.mergeSave(v, table.remove(un, i), "component")\n', ""),
    ("saves: rolls far apart merged", GL,
     "math.abs((row.t or 0) - (v.t or 0)) <= G.SAVE_MERGE_MS", "true"),
    ("saves: a disagreement on the outcome not flagged", GL, "then v.success_differs = true end", "then end"),
    ("saves: a made save's status not kept", GL, " else v.status_made = x.status end", " end"),
    ("saves: an Osiris handler failure not recorded", GL,
     "G.results.save_error = tostring(err) end\nend\nif not G._listeners12",
     "end\nend\nif not G._listeners12"),
    ("saves: the component listener's outcome not read", GL,
     "    saving_throw_event = (G._listeners11 or {}).save == true }", "    saving_throw_event = true }"),
    ("saves: a fight's record without the registrations' outcome", GL,
     "      G.results = { prep = prepRes, save_listeners = G.saveListeners() }", "      G.results = { prep = prepRes }"),
    ("record: a status long after the save linked", GL, "    if dt > G.SAVE_STATUS_MS then break end\n", ""),
    ("record: another source's status linked to the save", GL,
     "    local same = v.source == nil or x.cause == nil or v.source == x.cause\n", "    local same = true\n"),
    ("record: a hit's saves not read", GL, "      saves[#saves + 1] = G.saveFields(c)\n", ""),
    ("record: a hit's attack roll taken as a save", GL,
     '    if first(c, { "SavingThrowRoll" }) == true or flagText(first(c, { "RollType" })) == "SavingThrowRoll" then',
     "    if true then"),
    ("record: the save's DC not kept", GL, '    dc = first(c, { "Difficulty" }),', "    dc = nil,"),
    ("record: the save's d20 not kept", GL, '  return { roll = first(c, { "Roll.Result.NaturalRoll" }),',
     "  return { roll = nil,"),
    ("record: no save probe", GL, "  if G.results and not G.results.save_probe then", "  if false then"),
    ("sheath gate: the step loop ignores it", GL,
     "    if not F.queue and G.sheathHeld(F, R, t) then F.next = t + G.POLL_MS; return end\n", ""),
    ("sheath gate: never gives up", GL, "  if t - F.sheathSince < G.READY_MAX_MS then return true end",
     "  if true then return true end"),
    ("sheath gate: the wait not recorded", GL,
     "    if F.sheathSince then R.tm = R.tm or {}; R.tm.sheath = { spell = F.sheathSpell, ms = t - F.sheathSince } end\n",
     ""),
    ("move: ended by standing still (the old 800 ms test)", GL,
     "  if not ended and t - M.t0 < G.MOVE_MAX_MS then return false end",
     "  if not ended and t - M.lastT < 800 and t - M.t0 < G.MOVE_MAX_MS then return false end"),
    ("move: the position read the moment the event comes", GL,
     "  if ended and t - ended < G.MOVE_SETTLE_MS then return false end\n", ""),
    ("move: any entity event ends it", GL,
     "  entity_event = function(obj, event) if event == G.MOVE_EVENT then",
     "  entity_event = function(obj, event) if true then"),
    ("move: a cancelled move never ends", GL,
     "  move_cancelled = function(obj, event) if event == G.MOVE_EVENT then G.moveEnds[uuid(obj)] = now() end end,\n",
     "  move_cancelled = function() end,\n"),
    ("turn guard: counted from the turn's start, not the last progress", GL,
     "    if t - (F.progressT or F.turnStart or t) > G.ACT_MAX_MS then", "    if t - (F.turnStart or t) > G.ACT_MAX_MS then"),
    ("player cast: costs checked at CastedSpell, before the attack's last strike", GL,
     "    if not G.strikesDone(P, G.hits) and t - P.tCast < G.STRIKES_MAX_MS then return false end\n", ""),
    ("player cast: an off-hand half the engine dropped passes as a possible half", GL,
     "  if P.toggled and P.dual and not fired and G.mainFired(P, G.dmg) and not G.strikesDone(P, G.hits)\n",
     "  if false\n"),
    ("player cast: a riposte's row taken for the cast's last strike", GL,
     ' and not f:find("Reaction", 1, true) then return true end', " then return true end"),
    ("player cast: a fixed 3 s wait for the cast's end", GL, "G.CAST_MAX_MS = 60000", "G.CAST_MAX_MS = 3000"),
    ("player cast: an attack that hit nothing may owe the off-hand half", GL,
     "elseif P.toggled and G.mainFired(P, G.dmg) then maybe = P.dual end", "elseif P.toggled then maybe = P.dual end"),
    ("spent: a bonus action not owed may be spent", GL,
     '"BonusActionPoint:0" }) do if want[k] == nil then want[k] = false end',
     '"BonusActionPoint:0" }) do if want[k] == nil then want[k] = 0 end'),
    ("spent: a gained action is a mismatch", GL, "    if w == false then bad = got > 1e-6\n",
     "    if w == false then bad = got ~= 0\n"),
    ("player cast: a cast fault not in the verdict", GL,
     '      causes[#causes + 1] = string.format("round %s, %s: %s", tostring(f.r or R.r), tostring(f.spell), '
     'tostring(f.why))\n', ""),
    ("player cast: a cast fault does not end the round", GL,
     '  if f then return string.format("round %d: %s: %s", R.r, tostring(f.spell), tostring(f.why)) end\n', ""),
    ("player cast: --old-cast-path ignored", RN, '"player_cast": False if getattr(a, "old_cast_path", False) else None',
     '"player_cast": None'),
    ("evade: Hide while Threatened", GL,
     '  if tostring(a.spell):find("^Shout_Hide") and try(Osi.HasActiveStatus, F.char, "FLANKED") == 1 then',
     "  if false then"),
    ("evade: the plan ignores the model's choice", PL, '        if ch.get("evade") and mode == "ranged":',
     "        if False:"),
    ("plan: the off-hand shots counted as failed", PL,
     'bonus_steady.append(A("Projectile_OffhandAttack", "bonus", "@boss", "off-hand shot", optional=True))',
     'bonus_steady.append(A("Projectile_OffhandAttack", "bonus", "@boss", "off-hand shot"))'),
    ("plan: round 1 leaves Fast Hands' bonus action unused", PL,
     "        bon = [bonus_open[i]] + list(bonus_steady[:n_bonus - 1]) if i < len(bonus_open) else list(bonus_steady)",
     "        bon = [bonus_open[i]] if i < len(bonus_open) else list(bonus_steady)"),
    ("plan gaps: an optional action counted as failed", GL,
     'if a.result ~= "done" and not a.optional then failed', 'if a.result ~= "done" then failed'),
    ("item rule: no value check", GL, '    elseif it.group == "action" and it.value and takes and it.value <= takes then',
     "    elseif false then"),
    ("item rule: the surge's attacks not what an item takes", GL,
     "  if G.hasSurge(list) then return F.plan.action_value end\n", ""),
    ("item rule: the off-hand attack never yields", GL,
     "      if a.yield_bonus then yields = yields or a else hasBonus = true end", "      hasBonus = true"),
    ("item rule: a yielding bonus action given to any item", GL,
     '    elseif it.group == "bonus" and yields and yields.value and (it.value or 0) <= yields.value then',
     "    elseif false then"),
    ("plan gaps: Trip with sure Advantage", PL, ' and trip and ch["adv"] < model.ADV_SURE:', " and trip:"),
    ("plan gaps: no off-hand attack", PL, '        if ch["offhand"]:\n', "        if False:\n"),
    ("plan gaps: no GWM bonus attack", PL, '        if ch["gwm"]:\n', "        if False:\n"),
    ("plan gaps: no extra action while hasted", PL, "            if st_ and _buff_actions(stats, spid):",
     "            if False:"),
    ("plan gaps: Hunter's Mark kept in round 1", PL, "                r.remove(a)\n", "                pass\n"),
    ("plan gaps: the respec's spells ignored", PL, "        return known is None or name.lower() in known",
     "        return True"),
    ("plan gaps: fillers the model did not keep", PL, '            if sid in ch["fillers"] and knows(name):',
     "            if knows(name):"),
    ("plan gaps: a zone the model did not keep", PL, '            if ch["conc"] == sid and knows(name):',
     "            if knows(name):"),
    ("plan gaps: Destructive Wrath on every damage type", PL,
     'for e, t in sp["dmg"] if t in ("Lightning", "Thunder")', 'for e, t in sp["dmg"]'),
    ("rolls: IgnoreSpellRolls kept", GL,
     "if f == G.ROLL_OPTION then had = true else keep[#keep + 1] = f end",
     "keep[#keep + 1] = f; had = true"),
    ("rolls: every caster's requests edited", GL, "    local c = cu and casters[cu]\n",
     "    local c = cu and (casters[cu] or { edits = {} })\n"),
    ("rolls: the reaction queue edited instead", GL, "Ext.System.ServerCastRequest.OsirisCastRequests end)",
     "Ext.System.ServerCastRequest.ReactionStartRequests end)"),
    ("rolls: off by default", GL, "G.REAL_ROLLS = true\n", "G.REAL_ROLLS = false\n"),
    ("rolls: the request's switch ignored", GL, "  return G.REAL_ROLLS ~= false and (req or {}).real_rolls ~= false",
     "  return G.REAL_ROLLS ~= false"),
    ("rolls: the character never rolls", GL, "  G.addRealCaster(F, F.char)\n", ""),
    ("rolls: summons never roll", GL, "  G.addRealCaster(F, s)\n", ""),
    ("rolls: casters kept after the run", GL, "    if G.realCasters[u] == c then G.realCasters[u] = nil end\n", ""),
    ("rolls: one lane drops the other's casters", GL,
     "    if G.realCasters[u] == c then G.realCasters[u] = nil end\n", "    G.realCasters = {}\n"),
    ("rolls: not in the run record", GL, "    real_rolls = F.realRolls == true, player_cast = F.playerCast == true,\n",
     "    player_cast = F.playerCast == true,\n"),
    ("outcome: a miss flag ignored", GL, "        if h.miss then missed = true elseif", "        if false then elseif"),
    ("outcome: a 0 damage row counted as a hit", GL, "        if dealt > 0 then landed = true else missed = true end",
     "        landed = true"),
    ("evidence: a missed attack's 0 damage row is no evidence", GL,
     "    if P.target and P.target ~= P.who and d.target == P.target and (d.source == P.who or d.owner == P.who)",
     "    if P.target and P.target ~= P.who and d.target == P.target and (d.source == P.who or d.owner == P.who)"
     " and (d.amount or 0) > 0"),
    ("riders: a rider whose cast missed fails the run", GL, "      if not seen and riderMissed(R, rd.spell) then",
     "      if false then"),
    ("riders on hits: misses counted", GL,
     "      if h.r == R.r and h.source == me and (h.hit or h.crit) and not h.miss then",
     "      if h.r == R.r and h.source == me then"),
    ("hits: the natural roll not read", GL, '"ConditionRolls.1.Roll.Result.NaturalRoll", ', ""),
    ("hits: numbered steps of a path read as names", GL, "do x = x[tonumber(k) or k] end", "do x = x[k] end"),
    ("reactions: an ask answer kept", GL, '      if pol[k] == "ask" then pol[k] = "never" end\n', ""),
    ("reactions: the summon's prompts unguarded", GL, "  for s in pairs(F.summons or {}) do\n    for _, p in ipairs",
     "  for s in pairs({}) do\n    for _, p in ipairs"),
    ("reactions: a summon keeps the player's settings", GL,
     "  for u, rep in pairs(G.reactionsApply(F.plan, { s })) do G.results.reactions[u] = rep end\n", ""),
    ("turns: idle party turns left open at the start", GL, "  if not F.manual then G.endIdleTurns(F) end\n", ""),
    ("outcome: never read as the turn ends", GL, "      G.castOutcomes(R, G.hits, G.dmg, uuid(F.char))\n", ""),
    ("turns: idle party turns left open after a round", GL, "    G.endIdleTurns(F)\n", ""),
    ("turns: the fighting character's turn ended", GL, "  local fighting = { [uuid(F.char)] = true }",
     "  local fighting = {}"),
    ("turns: the other lane's fighter ended", GL, "    for u in pairs(m) do fighting[u] = true end\n", ""),
    ("turns: the summon's turn ended", GL, "  for s in pairs(F.summons or {}) do fighting[s] = true end\n", ""),
    ("rolls: runs without rolls counted for repeats", RN, "        if rolls_of(r) != real_rolls:\n            continue\n",
     ""),
    ("rolls: the report mixes runs without rolls", RN,
     "        if rolls_of(r) != want_rolls:\n            other_rolls += 1\n            continue\n        i, side = rec_pair_side(r)",
     "        i, side = rec_pair_side(r)"),
    ("rolls: --no-real-rolls ignored", RN, '"real_rolls": not getattr(a, "no_real_rolls", False),', '"real_rolls": True,'),
    ("rolls: older records read as rolled", RN, '.get("real_rolls", False)) is not False',
     '.get("real_rolls", True)) is not False'),
    ("boss: full hit points at our turn", GL,
     "for _, d in ipairs(F.enemies) do pcall(Osi.SetHitpointsPercentage, d, G.BOSS_HP_PCT) end",
     "for _, d in ipairs(F.enemies) do pcall(Osi.SetHitpointsPercentage, d, 100) end"),
    ("popup: enemies hostile before the setup check", GL,
     "G.spawnEnemies(pts, E, not F.popup and F.enemyFaction or nil)", "G.spawnEnemies(pts, E, F.enemyFaction)"),
    ("popup: a setup mismatch still starts the fight", GL, "(G.FAIL_FAST or F.popup)", "(G.FAIL_FAST and not F.popup)"),
    ("markers: no start marker", GL, '    try(Ext.IO.SaveFile, G.MARK_FILES.started, id .. "\\n")\n', ""),
    ("markers: an over marker without a start", GL, '  elseif kind == "over" and F.marked then', '  elseif kind == "over" then'),
    ("popup: Automatic by default", TL, 'T.mode = T.mode or "manual"', 'T.mode = T.mode or "automatic"'),
    ("popup: a second Start while a run is on", TL,
     '  if G.F and G.F.state and G.F.state ~= "done" then return "busy" end\n  local t, err = T.read()',
     "  local t, err = T.read()"),
    ("test mod: the gate ignored", TB, "  if not pass then\n", "  if false then\n"),
    ("boss: not forced again", GL, "  wait(G.SETTLE_MS, function() forceEnemy(d, E) end)\n", ""),
    ("boss: deleted at the end", GL, "    if d == F.boss then G.restoreBoss(d) else gone[#gone + 1] = d end",
     "    gone[#gone + 1] = d"),
    ("campaign: story statuses not listed", GL,
     "    if not keep[st] and not G.technicalStatus(st) and G.campaignStatus(st) then out.statuses",
     "    if false then out.statuses"),
    ("campaign: tadpole passives not checked", GL,
     'if id:find(G.CAMPAIGN_PASSIVE) then cmp("campaign passive "', 'if false then cmp("campaign passive "'),
    ("v2: manual runs in the statistic", RN, "(manual if is_manual(r) else auto)", "auto"),
    ("v2: compared with the day numbers", RN, 'boss = (spec.get("expect") or {}).get("boss")',
     'boss = spec.get("expect")'),
    ("v2: Automatic not set before the runs", RN, '    print("popup mode:", engine.set_mode("automatic"))\n', ""),
    ("v2: invalid runs counted", RN, "                have += len(runs)\n", "                have += 1\n"),
    ("v2: no part flagged", RN, "out.append((key, label, g, m, ratio, flag, ci, band))",
     'out.append((key, label, g, m, ratio, "", ci, band))'),
    ("rolls: the off-hand shot not a roll", GL, "G.ROLL_CAUSES = { Attack = true, Offhand = true }",
     "G.ROLL_CAUSES = { Attack = true }"),
    ("rolls: a rider row counted as its own roll", GL,
     "if amt > 0 and last and last.hit and last.target == d.target and t - last.t <= G.ROLL_MERGE_MS then",
     "if false then"),
    ("rolls: a 0 damage row of a spell with no attack roll counted as a miss", GL,
     'if landed or (kind ~= "none" and kind ~= "save") then', "if true then"),
    ("rolls: a slow projectile given the next cast's spell", GL,
     'local spell = (h and h.spell ~= "" and h.spell) or (w and w.spell) or nil', "local spell = w and w.spell"),
    ("rolls: d20 taken from the nearest hit row of any outcome", GL,
     "local same = landed and ((h.hit or h.crit) and not h.miss) or (not landed and h.miss)", "local same = true"),
    ("rolls: Sneak Attack not marked on its roll", GL, "    if best then best.sneak = G.sneakPart(best) end\n", ""),
    ("outcome: Hunter's Mark's cast gets a miss", GL, '    if G.spellRollKind(a.spell) == "none" then return nil end\n',
     ""),
    ("outcome: StatusEnter 0 damage rows read as a miss", GL,
     '          and not (d.cause == "StatusEnter" and (d.amount or 0) <= 0) then', "          then"),
    ("hits: Disadvantage not read", GL, '"ConditionRolls.1.Roll.Roll.Disadvantage", ', ""),
    ("hits: the other d20 not read", GL, '"ConditionRolls.1.Roll.Result.DiscardedDiceTotal", ', ""),
    ("rolls: net Advantage ignores Disadvantage", GL, "net = adv and not dis and advFlag ~= false", "net = adv"),
    ("sneak: turns with Advantage from the damage flag only", GL,
     "if R.rolls and (R.rolls.known or 0) > 0 then adv, dis = R.rolls.net_adv_any == true, R.rolls.dis_any == true end",
     ""),
    ("sneak: only turns with Advantage counted", GL, "    sa.turns = sa.turns + 1\n",
     "    if adv then sa.turns = sa.turns + 1 end\n"),
    ("report: flagged by the 10% band", RN,
     'flag = "OUTSIDE" if not (ci[0] - 1e-12 <= m <= ci[1] + 1e-12) else ""', 'flag = "OUTSIDE" if band == "out" else ""'),
    ("report: counted per action", RN, "    rr = _round_rolls(rec)\n", "    rr = None\n"),
    ("report: Sneak Attack left in the damage per roll", RN,
     '"dmg_per_hit_no_sneak": (own - sneak) / landed if', '"dmg_per_hit_no_sneak": own / landed if'),
    ("stats: the normal quantile for small samples", RN, "    if df <= 30:\n        return T975_ALL[int(df)]\n", ""),
    ("stats: binomial upper bound at 5% one-sided", RN,
     "upper = 1.0 if k >= n else solve(lambda p: _binom_cdf(k, n, p) <= alpha / 2)",
     "upper = 1.0 if k >= n else solve(lambda p: _binom_cdf(k, n, p) <= alpha)"),
    ("stats: damage per hit with no interval", RN, '        ci["dmg_per_hit"] = _shifted(', '        ci["x"] = _shifted('),
    ("popup: per action, not per roll", TL, "  if ro and (ro.n or 0) > 0 then", "  if false then"),
    ("no outside buffs: Bless back", "catalog.py", 'BUFFS = {"1": [], "2": [], "3": []}',
     'BUFFS = {"1": ["BLESS"], "2": ["BLESS"], "3": ["BLESS"]}'),
    ("phase reactions: the enemies' turn answered like the own turn", GL,
     'pol[k] = phase == "enemy" and (POLICY_FLAGS[p] and p or "never") or G.reactionPolicy(k, F.plan)',
     "pol[k] = G.reactionPolicy(k, F.plan)"),
    ("phase reactions: interrupts the character lacks written too", GL, "    if known[k] then\n", "    if true then\n"),
    ("phase reactions: not read back", GL,
     "  for k, flags in pairs(want) do if not sameFlags(back[k] or {}, flags) then ok = false end end\n"
     "  F.reactionPhase", "  F.reactionPhase"),
    ("phase reactions: never set as the turn ends", GL,
     '    local ph = G.reactionsPhase(F, "enemy")\n    if ph and R then', "    local ph = nil\n    if ph and R then"),
    ("phase reactions: never set back as the turn starts", GL, '  local ph = G.reactionsPhase(F, "own")\n',
     "  local ph = nil\n"),
    ("phase reactions: the answer in force not logged", GL, "phase = mine and P.phase or nil, policy = mine and P.policy[interrupt] or nil",
     "phase = nil, policy = nil"),
    ("phase reactions: a reaction against the answer ignored", GL, '      if x.policy == "never" and (not me0 or x.who == me0) then',
     "      if false then"),
    ("phase reactions: answers that did not stick ignored", GL, "      if ph.verified == false then", "      if false then"),
    ("validity: a planned step not done ignored", GL,
     '        if nd then causes[#causes + 1] = string.format("round %s: planned step not done: %s", tostring(R.r), nd) end',
     ""),
    ("validity: a fallback to the alt counted as a failure", GL,
     'or tostring(a.result or ""):find("-> alt", 1, true) then return nil end', "then return nil end"),
    ("validity: fail fast ignores a step not done", GL,
     '    if nd then return string.format("round %d: planned step not done: %s", R.r, nd) end', ""),
    ("validity: a step after one not needed counted as skipped", GL, "    if (R.not_needed or {})[a.requires] then",
     "    if false then"),
    ("evade: the move optional again", PL, '             done_key="left")]', '             done_key="left", optional=True)]'),
    ("split: the reactions' damage left in the own turn's", RN, '        own -= react["react_dmg"]\n', ""),
    ("split: a Sneak Attack row counted as a roll of its own", RN,
     'if last and last["r"] == d.get("r") and t - last["t"] <= REACTION_MERGE_MS:', "if False:"),
    ("split: a model from before the split compared", RN, "        if key in SPLIT_PARTS and not split:\n            m = None\n",
     ""),
    ("strategy spec: the gear model's numbers left in expect.boss", PL,
     '    plan = with_hit_costs(out["plan"], stats)\n',
     '    out["expect"]["boss"] = spec["expect"]["boss"]\n    plan = with_hit_costs(out["plan"], stats)\n'),
    ("strategy spec: the forecast left from the gear model's plan", PL, '    plan["forecast"] = forecast(plan, out["slots"]',
     '    plan["forecast"] = plan.get("forecast") or forecast(plan, out["slots"]'),
    ("strategy spec: the riders left from the gear model's plan", PL, '    plan["riders"] = plan_riders(plan["rounds"])\n',
     ""),
    ("policy: the most likely course played, not the state's decision", GL,
     "    list = G.policyPick(F, R)\n    if not list then return {} end\n", "    G.policyPick(F, R)\n"),
    ("policy: a state outside the table not invalid", GL,
     "    if R.policy and R.policy.outside then\n      causes[#causes + 1]", "    if false then\n      causes[#causes + 1]"),
    ("policy: fail-fast ignores a state outside the table", GL,
     "  if R.policy and R.policy.outside then\n    return string.format", "  if false then\n    return string.format"),
    ("policy: concentration assumed, not read from the boss", GL,
     'conc = (on(boss, "HUNTERS_MARK") and "mark")', 'conc = ("mark")'),
    ("policy: True Strike from any riposte, not the last enemy turn's", GL,
     "  local since = (prev.tm or {}).end_asked or (prev.tm or {}).acted or math.huge", "  local since = 0"),
    ("policy: the cooldowns not read (Piercing Strike always ready)", GL,
     'pierce_m = has.pierce_m == true and not onCooldown(F.char, "Target_PiercingThrust")',
     "pierce_m = has.pierce_m == true"),
    ("riders: concentration not checked after its round", GL, "    local held = rd.conc and rd.round < R.r\n",
     "    local held = false\n"),
    ("riders: concentration counted from the round's status log", GL,
     "      for _, x in ipairs(rd.conc and {} or R.status_log or {}) do", "      for _, x in ipairs(R.status_log or {}) do"),
    ("riders: the turn's starting concentration not required under a policy", GL,
     '  if (R.policy.state or {}).conc == "mark" and not seen.HUNTERS_MARK then', "  if false then"),
    ("riders: a lost concentration never noted", GL,
     "    if held and not (F.riderLost or {})[rd.status] then", "    if false then"),
    ("sneak: the whole rider counted as Sneak Attack", GL, "    if best then best.sneak = G.sneakPart(best) end",
     "    if best then best.sneak = best.rider end"),
    ("sneak: any late row counted, whatever its type", GL,
     '    if wtype == nil or wtype == "" or k == "" or k == wtype then', "    if true then"),
    ("misses: no miss rows from the attack-roll events", GL, "  if not row.miss then return end\n  local F = G.F",
     "  if true then return end\n  local F = G.F"),
    ("misses: one miss logged twice", GL,
     "    if h.miss and h.source == row.source and h.target == row.target then return end", ""),
    ("misses: a natural 1 counted as a critical hit", GL,
     "  if row.miss and row.crit then row.crit, row.crit_miss = false, true end", ""),
    ("misses: a miss row's Advantage overruled by its flags", GL,
     'if h and flags ~= "" and not h.miss then advFlag', 'if h and flags ~= "" then advFlag'),
    ("cast fails: a started cast's late fail logged as a refusal", GL,
     "    f.why = G.failNoise(G.F, R, f)\n", "    f.why = nil\n"),
    ("cast fails: a CastedSpell between not looked at", GL,
     "  for _, c in ipairs(R.casts or {}) do if same(c) and c.t and c.t >= use.t then return nil end end\n", ""),
    ("cast fails: the character's fails on the old path made noise", GL,
     "  if mine and not F.playerCast then return nil end\n", ""),
    ("actions: the off-hand halves not listed", GL, "    if #out > 0 then a.rolls = out end", ""),
    ("summary: attacks counted per cast again", GL, "  if rolls.n > 0 then attacks =", "  if false then attacks ="),
    ("arena: the strategy's boss distance ignored", GL, "  local d = far or G.RANGE[mode] or 6.0",
     "  local d = G.RANGE[mode] or 6.0"),
    ("camera: the marker written before the camera", GL,
     "  G.cameraOn(F, function(cam)\n    G.results.camera = cam\n    G.startFight(F)\n  end)",
     "  G.startFight(F)\n  G.cameraOn(F, function(cam) G.results.camera = cam end)"),
    ("camera: the character not selected first (the camera follows the selected one)", GL,
     "  local okA = pcall(Osi.MakePlayerActive, F.char)\n", "  local okA = false\n"),
    ("camera: no answer waits for ever", GL, "    if F.camera or polls * G.POLL_MS >= G.CAMERA_WAIT_MS then",
     "    if F.camera or polls > 1e9 then"),
    ("rounds: a cut round compared as a full round", RN, "            if cut:\n                row.update(game=own,",
     "            if False:\n                row.update(game=own,"),
    ("rounds: the most likely course given as the expectation", RN,
     '               "mean": ex.get("mean"), "mean_sd"', '               "mean": ex.get("likely"), "mean_sd"'),
    ("turns: an action's rolls not listed", RN,
     '(" - rolls: " + ", ".join(_roll_text(i, y) for i, y in enumerate(rolls)) if rolls else "")', '""'),
    ("reactions: the necrotic rider counted as Sneak Attack", RN, "                if not wtype or not ty or ty == wtype:",
     "                if True:"),
    ("report: the rounds against the strategy left out", RN, "                rl = round_lines(r)\n",
     "                rl = []\n"),
    ("pointer: a held mouse button not released", EN, "            send_up(MOUSE_BUTTONS[name][2])", "            pass"),
    ("pointer: left on the hotbar at the Start", EN,
     '            raise RunInvalid("mouse button held down before the Start: " + ", ".join(stuck))\n        pointer_off_ui()\n',
     '            raise RunInvalid("mouse button held down before the Start: " + ", ".join(stuck))\n'),
    ("policy: the boss's start spot never compared", GL, "  if not (boss and s) or F.boss_left then return false end",
     "  if true then return false end"),
    ("policy: far even after the boss moved", GL, " ^ 2) <= G.START_SPOT_M\n", " ^ 2) <= 1e9\n"),
    ("policy: far with the boss in reach", GL, "    far = G.bossAtStart(F, boss) and dist(F.char, boss) > G.REACH }",
     "    far = G.bossAtStart(F, boss) }"),
    ("policy: the boss's start spot not recorded", GL,
     "  F.boss_start, F.boss_left = bx and { bx, by, bz } or nil, nil\n", "  F.boss_start, F.boss_left = nil, nil\n"),
    ("far: a new fight keeps the last fight's left flag", GL,
     "  F.boss_start, F.boss_left = bx and { bx, by, bz } or nil, nil\n", "  F.boss_start = bx and { bx, by, bz } or nil\n"),
    ("strategy spec: decisions without riders", PL,
     '        d["riders"] = [{k: v for k, v in r.items() if k != "round"} for r in plan_riders([d["steps"]])]',
     "        pass"),
    ("strategy spec: a decision's spells not in the sheet", PL,
     '        [d["steps"] for d in ((plan.get("policy") or {}).get("decisions") or [])]', "        []"),
    ("riders: Hunter's Mark not a concentration rider", PL, 'CONCENTRATION_RIDERS = {"Target_HuntersMark"}',
     "CONCENTRATION_RIDERS = set()"),
    ("report: critical hits per round given a t interval (zero width over rounds with none)", RN,
     "        ci[key] = poisson_interval(int(round(sum(rs))), len(rs)) if len(rs) >= 2 else None\n",
     "        ci[key] = t_interval(rs)\n"),
    ("report: a count the same every round given a zero-width t interval", RN, "    if min(xs) == max(xs):\n",
     "    if False:\n"),
    ("report: rolls with any Disadvantage compared with the model's net rate", RN,
     '(logged rolls)", "dis_any_rate"', '(logged rolls)", "dis_rate"'),
    ("report: net Disadvantage counted with the cancelled rolls in", RN,
     'if p.get("adv") is False and p.get("dis"))', 'if p.get("dis"))'),
    ("split: rows in the character's own turn counted as reactions", RN,
     "return r == 0 or (rel.get(r) is not None and (d.get(\"t\") or 0) > rel[r])", "return True"),
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
