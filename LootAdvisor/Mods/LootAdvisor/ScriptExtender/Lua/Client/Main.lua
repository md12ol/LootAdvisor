-- LootAdvisor client loop: selection polling (0.5 s), paint pass (0.5 s), list window directions (1 s),
-- results from the server (LA_Result) -> frames / tooltips / marker ranks / list window.

LA = LA or {}
local try = LA.try
LA.FrameTemplates = {}
LA.MarkerRank = {}

local SLOTI = {}
for i, s in ipairs(LA.SLOTS) do SLOTI[s] = i end

function LA.OnResult(res)
  LA.Result = res
  res.frames = res.frames or {}
  local ft = {}
  for _, r in ipairs(res.rows or {}) do
    if res.frames[r.id] then for _, t in ipairs(r.t or {}) do ft[t] = r.id end end
  end
  LA.FrameTemplates = ft
  -- rank per marker label handle: the selected character's markers by pick and slot (the off-screen arrows go to
  -- the best of them), everyone else's after LA.OTHERS (painted, never an arrow)
  local mr = {}
  for _, m in ipairs(res.markers or {}) do
    local v = (m.rank or 2) * 100 + (SLOTI[m.slot] or 50)
    if m.who and not m.sel then v = v + LA.OTHERS * 100 end
    if not mr[m.h] or v < mr[m.h] then mr[m.h] = v end
  end
  LA.MarkerRank = mr
  pcall(LA.Tip.Apply, res)
  if LA.Win.window then pcall(LA.Win.Render, res) end
end

Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel ~= LA.CH_RESULT then return end
  local res = try(Ext.Json.Parse, e.Payload)
  if type(res) == "table" then
    local ok, err = pcall(LA.OnResult, res)
    if not ok then Ext.Utils.PrintError("[Loot Advisor] result: " .. tostring(err)) end
  end
end)

local lastSlow, lastDir, lastDev, lastSettings, lastMenu = 0, 0, 0, 0, 0
local wasEnabled = true
local function onTick()
  local now = Ext.Utils.MonotonicTime()
  if now - lastSettings > 3000 then lastSettings = now; LA.LoadSettings() end
  if LA.Settings.Dev and now - lastDev > 300 then lastDev = now; pcall(LA.Eval, "LootAdvisor_client") end
  -- the F6 window steps aside while the game's pause menu is open (read in the deferred UI update)
  if now - lastMenu >= 100 then lastMenu = now; LA.UI.Run(LA.UI.CheckMenu) end
  pcall(LA.Win.SetMenuHidden, LA.UI.menuOpen == true)
  if not LA.Settings.Enabled then
    if wasEnabled then wasEnabled = false; LA.Result = nil; pcall(LA.Tip.RestoreAll); LA.UI.Run(LA.Paint.Pass) end
    LA.UI.Run(LA.Tip.Watch) -- puts the game's templates back on tooltips that still carry ours
    return
  end
  wasEnabled = true
  LA.UI.Run(LA.Tip.Watch) -- open tooltips: cheap check every frame
  if now - lastSlow >= 500 then
    lastSlow = now
    pcall(LA.PollSelection)
    LA.UI.Run(LA.Paint.Pass)
  end
  if now - lastDir >= 1000 then lastDir = now; pcall(LA.Win.Tick) end
end

local function onKey(e)
  if e.Event == "KeyDown" and not e.Repeat and tostring(e.Key) == tostring(LA.Settings.Hotkey) then LA.Win.Toggle() end
end

local initialized = false
local function init()
  if initialized then return end
  initialized = true
  LA.LoadSettings()
  pcall(LA.Win.Init)
  Ext.Events.Tick:Subscribe(onTick)
  Ext.Events.KeyInput:Subscribe(onKey)
  Ext.Utils.Print("[Loot Advisor] loaded - " .. tostring(LA.Settings.Hotkey) .. " toggles the item list.")
end
-- dev toggle (shipped default Dev = false): console "!la_dev" flips it and saves LootAdvisor_settings.json
Ext.RegisterConsoleCommand("la_dev", function()
  LA.LoadSettings()
  LA.Settings.Dev = not LA.Settings.Dev
  LA.SaveSettings()
  Ext.Utils.Print("[Loot Advisor] Dev = " .. tostring(LA.Settings.Dev))
end)
-- console "!la_menu": the widgets below ContentRoot with their Visibility, and whether the pause menu counts as open
Ext.RegisterConsoleCommand("la_menu", function()
  LA.UI.Run(function()
    local root = LA.UI.Root()
    local content = root and (try(function() return root:Find("ContentRoot") end) or root)
    LA.UI.Walk(content, function(el, d)
      if tostring(LA.UI.Type(el)):find("UIWidget", 1, true) then
        Ext.Utils.Print(("[Loot Advisor] widget %s (%s)"):format(tostring(LA.UI.Name(el)),
          tostring(try(function() return el:GetProperty("Visibility") end))))
        return "skip"
      end
      if d >= 4 then return "skip" end
    end, 400)
    LA.UI.CheckMenu()
    Ext.Utils.Print("[Loot Advisor] pause menu open: " .. tostring(LA.UI.menuOpen))
  end)
end)
Ext.Events.SessionLoaded:Subscribe(init)
Ext.Events.ResetCompleted:Subscribe(init)
