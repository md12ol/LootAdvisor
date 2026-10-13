-- Loot Advisor gauntlet test mod (server). Developer only, never part of the Loot Advisor download (its own pak, built
-- by tools/gauntlet/testmod.py). Inert in every save the test file does not name: on each load it reads the test
-- file and nothing else. Only when the gate accepts the save (the file is there and enabled, its character is in the
-- party, the party is in its arena's level) does it run the gauntlet harness and the test popup's server side, then
-- tell the client to load the F11 window.
--
-- The harness files are packed under Harness/ and run with Ext.Utils.LoadString, as tools/gauntlet/engine.py load
-- runs them, so their globals (GAUNTLET, GAUNTLET_TEST) are the ones the dev eval hook and engine.py talk to.

GAUNTLET_TESTMOD = GAUNTLET_TESTMOD or { armed = false }
local M = GAUNTLET_TESTMOD
M.DIR = "Mods/LootAdvisorGauntletTest/ScriptExtender/Lua/Harness/"
M.TEST_FILE = "LootAdvisor_gauntlet_test.json"

local function try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end
local function short(u)
  u = tostring(u or "")
  return u:match("(%x+%-%x+%-%x+%-%x+%-%x+)$") or u
end

-- Is the loaded save the test's? -> ok, why. level: the level that just started (LevelGameplayStarted).
function M.gate(level)
  local raw = try(Ext.IO.LoadFile, M.TEST_FILE)
  if type(raw) ~= "string" or raw == "" then return false, "no test file" end
  local t = try(Ext.Json.Parse, raw)
  if type(t) ~= "table" or type(t.req) ~= "table" or type(t.spec) ~= "table" then
    return false, "the test file has no req and spec"
  end
  if t.enabled == false then return false, "the test file is disabled" end
  local char = short(t.req.char)
  if char == "" then return false, "the test file names no character" end
  local inParty = false
  for _, row in ipairs(try(function() return Osi.DB_Players:Get(nil) end) or {}) do
    if short(row[1]) == char then inParty = true end
  end
  if not inParty then return false, "the test character is not in this save's party" end
  local want = t.req.arena_def and t.req.arena_def.level
  if want and tostring(level) ~= tostring(want) then
    return false, "the party is in " .. tostring(level) .. ", the test arena in " .. tostring(want)
  end
  return true, "test character and arena found"
end

-- The packed copy first; the copy engine.py load leaves in the Script Extender folder if the pak cannot be read.
function M.runHarness(name, userCopy)
  local src = try(Ext.IO.LoadFile, M.DIR .. name, "data") or try(Ext.IO.LoadFile, userCopy)
  if type(src) ~= "string" or src == "" then return false, "cannot read " .. name end
  local f, err = Ext.Utils.LoadString(src)
  if not f then return false, name .. ": " .. tostring(err) end
  local ok, res = pcall(f)
  return ok, tostring(res)
end

function M.tellClient()
  if M.armed then pcall(Ext.ServerNet.BroadcastMessage, "GauntletTestArm", "1") end
end

function M.arm(level)
  if M.armed then return M.tellClient() end
  local pass, why = M.gate(level)
  M.why = why
  if not pass then
    -- a save without a test file stays silent; one with a file says why it stays inert
    if why ~= "no test file" then Ext.Utils.Print("[gauntlet test] inert in this save: " .. tostring(why)) end
    return
  end
  local ok, res = M.runHarness("gauntlet.lua", "LootAdvisor_gauntlet.lua")
  if ok then ok, res = M.runHarness("gauntlet_test.lua", "LootAdvisor_gauntlet_test.lua") end
  if not ok then
    M.why = "harness not loaded: " .. tostring(res)
    Ext.Utils.Print("[gauntlet test] " .. M.why)
    return
  end
  M.armed = true
  Ext.Utils.Print("[gauntlet test] armed: " .. tostring(why) .. " (F11 opens the popup)")
  M.tellClient()
end

Ext.Osiris.RegisterListener("LevelGameplayStarted", 2, "after", function(level, _editor)
  local ok, err = pcall(M.arm, level)
  if not ok then Ext.Utils.Print("[gauntlet test] " .. tostring(err)) end
end)
Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel == "GauntletTestHello" then M.tellClient() end
end)
