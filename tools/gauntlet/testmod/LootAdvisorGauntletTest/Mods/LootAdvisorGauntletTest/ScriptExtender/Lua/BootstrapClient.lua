-- Loot Advisor gauntlet test mod (client). Loads the F9 window (gauntlet_ui.lua) only once the server says this save
-- is the test's (BootstrapServer.lua's gate); in any other save it only asks the server once the game is running.

GAUNTLET_TESTMOD_UI = GAUNTLET_TESTMOD_UI or { loaded = false }
local M = GAUNTLET_TESTMOD_UI
M.FILE = "Mods/LootAdvisorGauntletTest/ScriptExtender/Lua/Harness/gauntlet_ui.lua"

local function try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end

function M.load()
  if M.loaded then return end
  local src = try(Ext.IO.LoadFile, M.FILE, "data") or try(Ext.IO.LoadFile, "LootAdvisor_gauntlet_ui.lua")
  if type(src) ~= "string" or src == "" then return Ext.Utils.Print("[gauntlet test] cannot read gauntlet_ui.lua") end
  local f, err = Ext.Utils.LoadString(src)
  if not f then return Ext.Utils.Print("[gauntlet test] gauntlet_ui.lua: " .. tostring(err)) end
  local ok, res = pcall(f)
  M.loaded = ok
  Ext.Utils.Print("[gauntlet test] " .. tostring(res))
end

Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel == "GauntletTestArm" then pcall(M.load) end
end)
Ext.Events.GameStateChanged:Subscribe(function(e)
  if tostring(e.ToState) == "Running" then pcall(Ext.ClientNet.PostMessageToServer, "GauntletTestHello", "") end
end)
