-- (f) Test helpers driven by a command file (same idea as Autopilot's BuildAdvisor_cmd.txt).
-- Write ONE line to LootAdvisorSpike_cmd.txt; the result appears in LootAdvisorSpike_result.txt as "<seq>|<text>".
--   spawn <templateGuid> [count]   Osi.TemplateAddTo(itemTemplate, inventoryHolder, count, showNotification)
--   tp <x> <y> <z>                 Osi.TeleportToPosition(obj, x, y, z, event, linked, followers, summons, leaveCombat, snap)
--   tpto <objectGuid>              Osi.TeleportTo(obj, target, event, linked)
--   markers on|off                 Osi.ShowMapMarker for the test markers
--   ping <x> <y> <z>               Osi.RequestPing
--   scan                           LevelItems scan + in-world effects + list to the client
--   fxoff                          stop all loop effects
-- TEST SAVES ONLY: spawning and teleporting change the save.

LAS = LAS or {}
local try = LAS.try
local seq, lastCheck = 0, 0

local function actor() return LAS.selected or try(Osi.GetHostCharacter) end

local function run(line)
  local w = {}
  for s in line:gmatch("%S+") do w[#w + 1] = s end
  local cmd, who = w[1], actor()
  if cmd == "spawn" and w[2] then
    local ok, err = pcall(Osi.TemplateAddTo, w[2], who, tonumber(w[3]) or 1, 1)
    return ok and ("spawned " .. w[2] .. " into " .. tostring(who)) or ("spawn error " .. tostring(err))
  elseif cmd == "tp" and w[4] then
    local ok, err = pcall(Osi.TeleportToPosition, who, tonumber(w[2]), tonumber(w[3]), tonumber(w[4]), "", 0, 1, 1, 0, 1)
    return ok and ("teleported " .. tostring(who)) or ("tp error " .. tostring(err))
  elseif cmd == "tpto" and w[2] then
    local ok, err = pcall(Osi.TeleportTo, who, w[2], "", 0)
    return ok and ("teleported to " .. w[2]) or ("tpto error " .. tostring(err))
  elseif cmd == "markers" then
    if w[2] == "off" then LAS.HideAllMarkers(); return "markers off" end
    return LAS.ShowMarkers(who, true)
  elseif cmd == "ping" and w[4] then
    return LAS.Ping(tonumber(w[2]), tonumber(w[3]), tonumber(w[4]))
  elseif cmd == "scan" then
    return LAS.RefreshLevelItems()
  elseif cmd == "fxoff" then
    LAS.StopFx(); return "effects stopped"
  end
  return "unknown command: " .. line
end

Ext.Events.Tick:Subscribe(function()
  local now = Ext.Utils.MonotonicTime()
  if now - lastCheck < 500 then return end
  lastCheck = now
  if not LAS.Settings then LAS.LoadSettings() end
  if not LAS.Settings.Enabled then return end
  pcall(LAS.Eval, "LootAdvisorSpike_server")
  local raw = try(Ext.IO.LoadFile, LAS.CMD_FILE)
  if type(raw) ~= "string" or raw:match("^%s*$") then return end
  try(Ext.IO.SaveFile, LAS.CMD_FILE, "")
  seq = seq + 1
  local ok, res = pcall(run, raw:gsub("[\r\n]+", " "))
  try(Ext.IO.SaveFile, LAS.RESULT_FILE, seq .. "|" .. tostring(ok and res or ("error " .. tostring(res))))
end)
