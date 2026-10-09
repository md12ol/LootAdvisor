-- LootAdvisor spike client loop. Everything runs only with "Enabled": true in LootAdvisorSpike_settings.json.
-- Client command file LootAdvisorSpike_ccmd.txt: "probe" (dump), "restore" (undo texts/UI), "paint" (one pass now).

LAS = LAS or {}
local try = LAS.try
local lastSlow, lastFast, lastCmd, lastSettings = 0, 0, 0, 0

local function onSelectionChanged()
  local me = LAS.selectedEntity
  local who = me and try(function() return me.DisplayName.Name:Get() end) or "?"
  LAS.badgeSet = {}
  for _, t in ipairs(LAS.TEST_ITEMS) do
    LAS.badgeSet[t.item] = true; LAS.badgeSet[t.template] = true
    if LAS.Settings.Tooltips then LAS.SetWhyText(t, who) end
  end
  LAS.SetMarkerTexts(who)
end

local function paint()
  LAS.UI.Run(function()
    if LAS.Settings.Badges then LAS.PaintInventory() end
    if LAS.Settings.PurpleMap then LAS.PaintMapMarkers() end
    if LAS.Settings.Rainbow then LAS.Rainbow.Pass() end
  end)
end

local function clientCommand()
  local raw = try(Ext.IO.LoadFile, "LootAdvisorSpike_ccmd.txt")
  if type(raw) ~= "string" or raw:match("^%s*$") then return end
  try(Ext.IO.SaveFile, "LootAdvisorSpike_ccmd.txt", "")
  local cmd = raw:match("%S+")
  if cmd == "probe" then LAS.UI.Run(LAS.Probe)
  elseif cmd == "restore" then LAS.RestoreTexts()
  elseif cmd == "paint" then paint() end
end

Ext.Events.Tick:Subscribe(function()
  local now = Ext.Utils.MonotonicTime()
  if now - lastSettings > 5000 then lastSettings = now; LAS.LoadSettings() end
  if not (LAS.Settings and LAS.Settings.Enabled) then return end
  if now - lastCmd > 300 then lastCmd = now; pcall(clientCommand); pcall(LAS.Eval, "LootAdvisorSpike_client") end
  if now - lastSlow > 500 then
    lastSlow = now
    if LAS.PollSelection() then pcall(onSelectionChanged) end
    paint()
  end
  if now - lastFast > 200 then lastFast = now; pcall(LAS.UpdateOverlay) end
end)
