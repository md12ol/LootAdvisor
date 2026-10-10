-- Noesis helpers (client). Verified API in the installed SE v32 DLL (strings): Ext.UI.GetRoot, element:Find,
-- :VisualChild(i) (1-based), .VisualChildrenCount, .VisualParent, .DataContext, :Resource(key), :GetProperty,
-- :SetProperty, :GetAllProperties, .Type, .Name, :Subscribe. NOT in v32: Ext.UI.Defer, :PointToScreen,
-- :AttachXamlChild / :SetXamlProperty (all on bg3se main = v33+). Ext.UI.Defer is used when it exists.

LA = LA or {}
LA.UI = {}
local try = LA.try

-- Every read or write of the Noesis tree goes through LA.UI.Run. Noesis renders in parallel with Lua, so a walk
-- from the game tick can reach an element the UI has just freed and crash the game inside VisualChild (seen in
-- combat, where the HUD is rebuilt all the time). Ext.UI.Defer (SE v33+) runs the code at the start of the next
-- UI update, where that cannot happen. Older SE has no safe moment, so the code is skipped there unless the
-- player opts in with the setting UnsafeUiOnOldSE. Returns true when fn was run or queued.
local warnedOldSE = false
function LA.UI.Run(fn)
  local defer = try(function() return Ext.UI.Defer end)
  if defer then
    defer(function() pcall(fn) end)
    return true
  end
  if LA.Settings and LA.Settings.UnsafeUiOnOldSE == true then
    pcall(fn)
    return true
  end
  if not warnedOldSE then
    warnedOldSE = true
    Ext.Utils.Print("[Loot Advisor] item frames, tooltip advice and the rainbow map marker style need Script Extender"
      .. " v33 or newer; this Script Extender is older, so they are off. The F6 list, map markers and the Sets page"
      .. " still work.")
  end
  return false
end

function LA.UI.Root() return try(Ext.UI.GetRoot) end

local function typeOf(e) return e.Type end
local function nameOf(e) return e.Name end
local function count(e) return e.VisualChildrenCount end
local function child(e, i) return e:VisualChild(i) end
local function dc(e) return e.DataContext end

LA.UI.Type = function(e) return try(typeOf, e) end
LA.UI.Name = function(e) return try(nameOf, e) end
LA.UI.DC = function(e) return try(dc, e) end

-- Depth-first walk; fn(el, depth) returns "skip" to not descend. budget caps visited nodes.
function LA.UI.Walk(root, fn, budget)
  budget = budget or 40000
  local function go(el, d)
    if budget <= 0 or d > 90 then return end
    budget = budget - 1
    if fn(el, d) == "skip" then return end
    for i = 1, (try(count, el) or 0) do
      local c = try(child, el, i)
      if c then go(c, d + 1) end
    end
  end
  if root then go(root, 0) end
end

-- First descendant (or self) with the given x:Name
function LA.UI.FindNamed(root, name, maxDepth)
  local found
  LA.UI.Walk(root, function(el, d)
    if found then return "skip" end
    if LA.UI.Name(el) == name then found = el; return "skip" end
    if maxDepth and d >= maxDepth then return "skip" end
  end, 20000)
  return found
end

-- The game's pause menu (Esc) and the pages it opens (options, save, load) are widgets on the UI's Pause layer,
-- named by the x:Name of their XAML page (GameMenu.xaml: "GameMenu"). The game's message boxes (a confirmation such
-- as the respec warning, the new game's tutorial question) are the widget of MessageBox.xaml, "Dialog_box", and
-- MessageBox_c.xaml on a controller. Script Extender windows draw over every game widget, so the F6 window hides
-- while one of them is shown. Run through LA.UI.Run only: sets LA.UI.menuOpen.
-- The widgets sit a few levels below ContentRoot; their insides are not walked.
LA.UI.PAUSE_WIDGETS = { GameMenu = true, GameOptions = true, InterfaceOptions = true, AccessibilityOptions = true,
                        ConnectivityMenu = true, LoadGame = true, SaveGame = true,
                        Dialog_box = true, MessageBox_c = true }
local function getVis(e) return e:GetProperty("Visibility") end
function LA.UI.CheckMenu()
  local root = LA.UI.Root()
  if not root then return end
  local content = try(function() return root:Find("ContentRoot") end) or root
  local open = false
  LA.UI.Walk(content, function(el, d)
    if open then return "skip" end
    if tostring(LA.UI.Type(el)):find("UIWidget", 1, true) then
      -- an unreadable Visibility counts as shown: the widget only exists while its state is on the stack
      local v = try(getVis, el)
      if LA.UI.PAUSE_WIDGETS[LA.UI.Name(el) or ""] and (v == nil or tostring(v) == "Visible") then open = true end
      return "skip"
    end
    if d >= 4 then return "skip" end
  end, 400)
  LA.UI.menuOpen = open
end

-- A theme resource (SolidColorBrush etc.) looked up from any element; cached.
local resCache = {}
function LA.UI.Resource(anyElement, key)
  if resCache[key] then return resCache[key] end
  local r = try(function() return anyElement:Resource(key) end)
  if r then resCache[key] = r end
  return r
end

function LA.UI.PurpleBrush(anyElement)
  for _, k in ipairs({}) do
    local b = LA.UI.Resource(anyElement, k)
    if b then return b end
  end
end

-- Remember original values so everything can be restored (only UI objects are touched; nothing is saved).
-- Keyed by tostring(element) (the native address), like Highlighter.lua does: Lua proxies are not unique.
-- There is no ClearValue binding in SE, so "restore" re-sets the value read before our change.
LA.UI.touched = {}
function LA.UI.Key(el) return tostring(el) end
function LA.UI.Set(el, prop, value)
  local k = LA.UI.Key(el)
  local t = LA.UI.touched[k]
  if not t then t = {}; LA.UI.touched[k] = t end
  if t[prop] == nil then t[prop] = { v = try(function() return el:GetProperty(prop) end) } end
  return pcall(function() el:SetProperty(prop, value) end)
end
function LA.UI.Restore(el, prop)
  local t = LA.UI.touched[LA.UI.Key(el)]
  if not (t and t[prop]) then return false end
  pcall(function() el:SetProperty(prop, t[prop].v) end)
  t[prop] = nil
  return true
end
