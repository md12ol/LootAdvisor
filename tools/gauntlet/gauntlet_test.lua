-- Gauntlet test mode (server side): the F11 popup's mode and Start for the one character, set and arena the test
-- file names. Dev/test only, never in the player download: the test mod (tools/gauntlet/testmod) or
-- tools/gauntlet/engine.py load runs it after gauntlet.lua.
--
-- The test file LootAdvisor_gauntlet_test.json (Script Extender folder, written by engine.py arm) holds
-- { req = run request (char, arena, arena_def, act, rounds, ...), spec = one set's spec from plan.py }.
-- Start = the scripted run's setup and setup check (gauntlet.lua G.run with popup = true); a mismatch stops it before
-- the enemies turn hostile, else the fight starts. Manual: the player plays the character's turns; Automatic: the
-- plan does. Both write the same run record (plus test_mode) and the recorder's marker files.

GAUNTLET_TEST = GAUNTLET_TEST or {}
local T = GAUNTLET_TEST
local G = GAUNTLET
T.FILE = "LootAdvisor_gauntlet_test.json"
T.MODES = { manual = "Manual", automatic = "Automatic" }
-- The mode lives in this Lua state only: every save load and every game start begins in Manual, so a script that
-- wants Automatic sets it as its first step after the load.
T.mode = T.mode or "manual"
T.status = T.status or "Ready"

local function try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end

function T.read()
  local raw = try(Ext.IO.LoadFile, T.FILE)
  if not raw or raw == "" then return nil, "no test file (" .. T.FILE .. ")" end
  local t = try(Ext.Json.Parse, raw)
  if type(t) ~= "table" or type(t.req) ~= "table" or type(t.spec) ~= "table" then
    return nil, "the test file has no req and spec"
  end
  return t
end

function T.state()
  return { kind = "test", mode = T.mode, modes = T.MODES, status = T.status, detail = T.detail, last = T.last,
    run_id = T.runId, busy = G.F ~= nil and G.F.state ~= nil and G.F.state ~= "done" }
end
function T.push()
  pcall(Ext.ServerNet.BroadcastMessage, "GauntletUI", Ext.Json.Stringify(T.state()))
end
function T.set(status, detail)
  T.status, T.detail = status, detail
  T.push()
end

function T.setMode(m)
  if not T.MODES[m] then return "unknown mode " .. tostring(m) end
  T.mode = m
  T.push()
  return m
end

-- Run ids name the run record's run_id field and the recorder's video, so they carry the date when the game's Lua
-- has os.date and a counter in any case.
function T.newId()
  T.seq = (T.seq or 0) + 1
  local stamp = try(function() return os.date("%Y%m%d-%H%M%S") end) or
    tostring(math.floor(Ext.Utils.MonotonicTime() / 1000))
  return string.format("gt%s_%d", stamp, T.seq)
end

-- Start (the popup's button; engine.py runs set Automatic first and call it with their own run id). -> "started",
-- "busy" or "failed: why".
function T.start(opts)
  opts = opts or {}
  if G.F and G.F.state and G.F.state ~= "done" then return "busy" end
  local t, err = T.read()
  if not t then
    T.set("Setup failed", err)
    return "failed: " .. err
  end
  local req = {}
  for k, v in pairs(t.req) do req[k] = v end
  req.mode, req.popup, req.play, req.spec = "scripted", true, T.mode, t.spec
  req.run_id = opts.run_id or T.newId()
  req.label = req.label or "test"
  T.runId = req.run_id
  T.set("Setting up", string.format("run %s, %s: HP, resources, leftovers, the set and the boss", req.run_id,
    T.MODES[T.mode]))
  local r = G.run(req)
  if r ~= "started" then T.set("Ready", "not started: " .. tostring(r)) end
  return r
end

function T.stop()
  if not (G.F and G.F.state and G.F.state ~= "done") then return "nothing to stop" end
  return G.abort()
end

local function pct(x) return x and string.format("%.0f%%", 100 * x) or "-" end

-- The popup's last-result lines from a run record.
function T.summary(rec)
  local res = rec.results or {}
  local s = res.summary or {}
  local a = s.attacks or {}
  local n = (a.hit or 0) + (a.crit or 0) + (a.miss or 0)
  local landed = (a.hit or 0) + (a.crit or 0)
  -- counted per attack roll where the run has them (a two-weapon shot rolls twice), else per action
  local ro = s.rolls
  if ro and (ro.n or 0) > 0 then n, landed, a = ro.n, ro.landed or 0, { crit = ro.crit } end
  local boss = rec.expect and rec.expect.boss or {}
  local hr = res.hit_riders or {}
  local out = {
    run_id = rec.run_id, test_mode = rec.test_mode, valid = rec.valid, invalid = rec.invalid, ended = res.ended,
    dpr = s.dpr, rounds = s.rounds, attacks = n, hit_rate = n > 0 and landed / n or nil,
    crits = a.crit, model_dpr = boss.dpr, model_hit_rate = boss.hit_rate,
    hunters_mark = hr.hunters_mark, sneak_attack = hr.sneak_attack,
  }
  local lines = {
    string.format("Run %s (%s): %s", tostring(rec.run_id), T.MODES[rec.test_mode] or tostring(rec.test_mode),
      rec.valid and "valid" or "INVALID"),
    string.format("Damage per round %.1f over %d rounds%s", s.dpr or 0, s.rounds or 0,
      boss.dpr and string.format(" (model boss %.1f, x%.2f)", boss.dpr, (s.dpr or 0) / boss.dpr) or ""),
    string.format("Attacks %d: hit rate %s%s, crits %d", n, pct(out.hit_rate),
      boss.hit_rate and (" (model " .. pct(boss.hit_rate) .. ")") or "", a.crit or 0),
  }
  if hr.hunters_mark and (hr.hunters_mark.hits or 0) > 0 then
    lines[#lines + 1] = string.format("Hunter's Mark on %d of %d hits", hr.hunters_mark.rider, hr.hunters_mark.hits)
  end
  local sa = hr.sneak_attack
  if sa and sa.adv_turns then
    lines[#lines + 1] = string.format("Sneak Attack in %d of %d turns (%d with net Advantage)", sa.rider or 0,
      sa.turns or 0, sa.adv_turns)
  elseif sa and (sa.turns or 0) > 0 then
    lines[#lines + 1] = string.format("Sneak Attack in %d of %d turns with Advantage", sa.rider, sa.turns)
  end
  for i, c in ipairs(rec.invalid or {}) do
    if i > 6 then lines[#lines + 1] = "..."; break end
    lines[#lines + 1] = "- " .. tostring(c)
  end
  out.lines = lines
  return out
end

-- Setup mismatches as lines: what the check wanted and what the game had.
function T.mismatchLines(rec)
  local out = {}
  local sc = ((rec.results or {}).setup or {}).start
  for _, m in ipairs(sc and sc.mismatches or {}) do
    out[#out + 1] = string.format("%s: want %s, got %s", tostring(m.field), tostring(m.want), tostring(m.got))
  end
  return out
end

G.onPhase = function(F, name, rec)
  if name == "starting" then
    T.set("Setting up", "setup check passed: the boss turns hostile in a moment")
  elseif name == "fighting" then
    T.set("Fighting", F.player and "your turns: play the character" or "the plan plays the character's turns")
  elseif name == "done" then
    T.last = T.summary(rec)
    if not F.tFight then
      -- stopped before the fight: nothing was started, the cause is what the popup shows
      local lines = T.mismatchLines(rec)
      if #lines == 0 then lines = rec.invalid or { tostring((rec.results or {}).ended) } end
      T.last.lines = { "The fight was NOT started. Fix the setup and press Start again:" }
      for _, l in ipairs(lines) do T.last.lines[#T.last.lines + 1] = "- " .. tostring(l) end
      T.set("Setup failed", tostring((rec.results or {}).ended))
    else
      T.set("Result", rec.valid and "valid run" or "invalid run")
    end
  end
end

-- The popup's commands (gauntlet_ui.lua, channel "GauntletTest"): state, mode, start, stop.
function T.onCmd(m)
  if m.cmd == "mode" then T.setMode(m.mode)
  elseif m.cmd == "start" then T.start()
  elseif m.cmd == "stop" then T.stop()
  end
  T.push()
end
if T._net then pcall(function() Ext.Events.NetMessage:Unsubscribe(T._net) end) end
T._net = Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel ~= "GauntletTest" then return end
  local m = try(Ext.Json.Parse, e.Payload)
  if type(m) == "table" then pcall(T.onCmd, m) end
end)

return "gauntlet test mode ready (" .. T.MODES[T.mode] .. ")"
