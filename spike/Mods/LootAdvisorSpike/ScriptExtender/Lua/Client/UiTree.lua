-- Noesis helpers (client). Verified API in the installed SE v32 DLL (strings): Ext.UI.GetRoot, element:Find,
-- :VisualChild(i) (1-based), .VisualChildrenCount, .VisualParent, .DataContext, :Resource(key), :GetProperty,
-- :SetProperty, :GetAllProperties, .Type, .Name, :Subscribe. NOT in v32: Ext.UI.Defer, :PointToScreen,
-- :AttachXamlChild / :SetXamlProperty (all on bg3se main = v33+). Ext.UI.Defer is used when it exists.

LAS = LAS or {}
LAS.UI = {}
local try = LAS.try

-- Run Noesis code on the UI thread when the SE build supports it (v33+), else directly (v32, like Highlighter.lua).
function LAS.UI.Run(fn)
  if Ext.UI.Defer then Ext.UI.Defer(function() pcall(fn) end) else pcall(fn) end
end

function LAS.UI.Root() return try(Ext.UI.GetRoot) end

local function typeOf(e) return e.Type end
local function nameOf(e) return e.Name end
local function count(e) return e.VisualChildrenCount end
local function child(e, i) return e:VisualChild(i) end
local function dc(e) return e.DataContext end

LAS.UI.Type = function(e) return try(typeOf, e) end
LAS.UI.Name = function(e) return try(nameOf, e) end
LAS.UI.DC = function(e) return try(dc, e) end

-- Depth-first walk; fn(el, depth) returns "skip" to not descend. budget caps visited nodes.
function LAS.UI.Walk(root, fn, budget)
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
function LAS.UI.FindNamed(root, name, maxDepth)
  local found
  LAS.UI.Walk(root, function(el, d)
    if found then return "skip" end
    if LAS.UI.Name(el) == name then found = el; return "skip" end
    if maxDepth and d >= maxDepth then return "skip" end
  end, 20000)
  return found
end

-- A theme resource (SolidColorBrush etc.) looked up from any element; cached.
local resCache = {}
function LAS.UI.Resource(anyElement, key)
  if resCache[key] then return resCache[key] end
  local r = try(function() return anyElement:Resource(key) end)
  if r then resCache[key] = r end
  return r
end

function LAS.UI.PurpleBrush(anyElement)
  for _, k in ipairs(LAS.PURPLE_BRUSH_KEYS) do
    local b = LAS.UI.Resource(anyElement, k)
    if b then return b end
  end
end

-- Remember original values so everything can be restored (only UI objects are touched; nothing is saved).
-- Keyed by tostring(element) (the native address), like Highlighter.lua does: Lua proxies are not unique.
-- There is no ClearValue binding in SE, so "restore" re-sets the value read before our change.
LAS.UI.touched = {}
function LAS.UI.Key(el) return tostring(el) end
function LAS.UI.Set(el, prop, value)
  local k = LAS.UI.Key(el)
  local t = LAS.UI.touched[k]
  if not t then t = {}; LAS.UI.touched[k] = t end
  if t[prop] == nil then t[prop] = { v = try(function() return el:GetProperty(prop) end) } end
  return pcall(function() el:SetProperty(prop, value) end)
end
function LAS.UI.Restore(el, prop)
  local t = LAS.UI.touched[LAS.UI.Key(el)]
  if not (t and t[prop]) then return false end
  pcall(function() el:SetProperty(prop, t[prop].v) end)
  t[prop] = nil
  return true
end
