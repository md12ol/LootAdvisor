-- LootAdvisor custom images (IMAGES.md Plan A): our own textures, created by Noesis from our own XAML page
-- (GUI/Pages/LootAdvisorAssets.xaml, widget "LootAdvisorAssets", added by GUI/StateMachines/Keyboard.xaml), are
-- read back here as objects and assigned with SetProperty:
--   * inventory / container / camp-chest / equipment cells and BAGS: the two rarity-frame Images of the cell
--     (Image back, Rectangle icon, Image front - DataTemplates.xaml Template.Item/ItemContainer/ItemEquipment)
--     get our rainbow "Prism" frame; cells that no longer hold a recommended item get the game's own frame back;
--   * item frames anywhere (inventory, containers, bags, paperdoll + weapon slots, hotbar items): see PaintFrame;
--   * our journal map markers (marker VM Name = one of our DisplayText handles): in-view Image "Icon" -> our quest diamond;
--     off-screen: Canvas "IconHolder".Background -> the game's offScreen_quest arrow recoloured rainbow (no icon
--     inside) and Ellipse "OutIcon" (minimap) / "Icon" (full map) .Fill -> our diamond. Size, position, rotation
--     and the inside/outside switch stay the game's own (template triggers); only the textures change.
-- Settings: "Rainbow": true in LootAdvisorSpike_settings.json. UI only, nothing is saved.
-- Verified in game 2026-10-09 (IMAGES_RESULTS.md). Resource(key) only sees the element's OWN resources: app-level
-- keys (and the A2 Lib keys) return one shared dummy object, never nil -> R.Assets rejects that dummy.

LAS = LAS or {}
LAS.Rainbow = LAS.Rainbow or {}
local R = LAS.Rainbow
local UI = LAS.UI
local try = LAS.try

R.set = R.set or {}          -- [item uuid or template guid] = true -> rainbow frame
R.painted = R.painted or {}  -- [tostring(back Image)] = true
R.stats = {}

local GAME = { Uncommon = true, Rare = true, VeryRare = true, Legendary = true, Story = true }

local function prop(el, p) return try(function() return el:GetProperty(p) end) end
local function set(el, p, v) return pcall(function() el:SetProperty(p, v) end) end
local function child(el, i) return try(function() return el:VisualChild(i) end) end

-- Objects from the asset widget: named elements' Source/Fill (local values set by the XAML parser, readable),
-- else widget:Resource(key). A missing key returns a shared dummy object (not nil): compare and reject it.
function R.Assets(widget, root)
  local A = {}
  local function named(n, p)
    local e = widget and UI.FindNamed(widget, n, 12)
    return e and prop(e, p)
  end
  local dummy = root and tostring(try(function() return root:Resource("LA.__no_such_key__") end))
  local function res(k)
    local v = widget and try(function() return widget:Resource(k) end)
    if v and tostring(v) == dummy then v = nil end
    return v
  end
  A.back = named("LA_FrameBack", "Source") or res("LA.FrameBack")
  A.front = named("LA_FrameFront", "Source") or res("LA.FrameFront")
  A.sym = named("LA_MapSymbol", "Source") or res("LA.MapSymbol")
  A.symBrush = named("LA_MapSymbolBrush", "Fill") or res("LA.MapSymbolBrush")
  A.arrowBrush = named("LA_MapArrowBrush", "Fill") or res("LA.MapArrowBrush")
  A.game = {}
  for k in pairs(GAME) do
    A.game[k] = { back = named("LA_Game_" .. k .. "_Back", "Source"), front = named("LA_Game_" .. k .. "_Front", "Source") }
  end
  return A
end

-- The cell's frame Images: [Image back, Rectangle (icon), Image front] siblings.
function R.FrameImages(cell)
  local back, front
  UI.Walk(cell, function(el)
    if back then return "skip" end
    local n = try(function() return el.VisualChildrenCount end) or 0
    for i = 2, n - 1 do
      local c = child(el, i)
      if c and UI.Type(c) == "Rectangle" then
        local a, b = child(el, i - 1), child(el, i + 1)
        if a and b and UI.Type(a) == "Image" and UI.Type(b) == "Image" then back, front = a, b; return "skip" end
      end
    end
  end, 400)
  return back, front
end

-- View-model properties are read with GetProperty (ls.VMItem / marker VMs are Noesis objects, not tables).
local function vp(vm, k)
  local v = try(function() return vm:GetProperty(k) end)
  if v == nil then v = try(function() return vm[k] end) end
  return v
end
R.vp = vp

-- uuid -> root template (client entity), cached
local tplOf = {}
local function templateOf(uuid)
  if tplOf[uuid] == nil then
    local e = try(Ext.Entity.Get, uuid)
    tplOf[uuid] = e and try(function() return e.GameObjectVisual.RootTemplateId end) or false
  end
  return tplOf[uuid] or nil
end

function R.Wanted(vm)
  if R.all then return true end
  local uuid = vp(vm, "EntityUUID")
  if type(uuid) ~= "string" then return false end
  if R.set[uuid] then return true end
  local tpl = templateOf(uuid)
  return tpl ~= nil and R.set[tpl] == true
end

-- One item frame = [Image back, Rectangle icon, Image front] (all item DataTemplates). Its VMItem is read from the
-- back Image (invCellBase.DataContext itself is a binding and reads back nil). Covers inventory / container /
-- camp-chest cells, bags, the paperdoll equipment + weapon slots and hotbar item slots (all ls.VMItem);
-- empty equipment slots (ls.VMEquipmentSlot) are left alone.
function R.PaintFrame(back, front, A)
  local vm = UI.DC(back)
  if not vm or UI.Type(vm) ~= "ls.VMItem" then return false end
  local k = tostring(back)
  if R.Wanted(vm) and A.back and A.front then
    set(back, "Source", A.back); set(back, "Visibility", "Visible")
    set(front, "Source", A.front); set(front, "Visibility", "Visible")
    R.painted[k] = true
    return true
  elseif R.painted[k] then
    -- local values beat the style triggers forever (no ClearValue in v32): put the game's look back ourselves
    local story = vp(vm, "IsStoryItem")
    local key = story and "Story" or tostring(vp(vm, "Rarity"))
    local g = A.game[key]
    if g and g.back and g.front then
      set(back, "Source", g.back); set(front, "Source", g.front)
      set(back, "Visibility", "Visible"); set(front, "Visibility", "Visible")
    else
      set(back, "Visibility", "Collapsed"); set(front, "Visibility", "Collapsed")
    end
    R.painted[k] = nil
  end
  return false
end

-- Our journal markers: the marker VM's Name is the DisplayText HANDLE (not the text) -> match our handles;
-- fall back to the text prefix (LAS.MARK) for markers whose text we wrote at runtime.
R.markerHandles = R.markerHandles or {}
for _, t in ipairs(LAS.TEST_ITEMS or {}) do if t.markerHandle then R.markerHandles[t.markerHandle] = true end end
local function isOurs(marker)
  local d = UI.DC(marker)
  local name = d and vp(d, "Name")
  if type(name) ~= "string" then return false end
  if R.markerHandles[name] then return true end
  local txt = name:sub(1, #LAS.MARK) == LAS.MARK and name or try(Ext.Loca.GetTranslatedString, name)
  return type(txt) == "string" and txt:sub(1, #LAS.MARK) == LAS.MARK
end

function R.PaintMarker(marker, A)
  local n = 0
  UI.Walk(marker, function(c)
    local nm, ty = UI.Name(c), UI.Type(c)
    if nm == "Icon" and ty == "Image" and A.sym then
      set(c, "Source", A.sym); set(c, "Tag", A.sym); n = n + 1
    elseif nm == "IconHolder" and A.arrowBrush then
      set(c, "Background", A.arrowBrush); n = n + 1
    elseif (nm == "OutIcon" or (nm == "Icon" and ty == "Ellipse")) and A.symBrush then
      set(c, "Fill", A.symBrush); n = n + 1
    end
  end, 300)
  return n
end

function R.Pass()
  local root = UI.Root()
  if not root then return end
  local widget
  local frames, markers = {}, {}
  local budget = 150000
  local function go(el, d)
    if budget <= 0 or d > 90 then return end
    budget = budget - 1
    local nm = UI.Name(el)
    if nm == "LootAdvisorAssets" then widget = el; return end
    if UI.Type(el) == "ls.LSWorldMapMarker" then markers[#markers + 1] = el; return end
    local n = try(function() return el.VisualChildrenCount end) or 0
    if n == 0 then return end
    local kids, types = {}, {}
    for i = 1, n do kids[i] = child(el, i); types[i] = kids[i] and UI.Type(kids[i]) end
    for i = 2, n - 1 do
      if types[i] == "Rectangle" and types[i - 1] == "Image" and types[i + 1] == "Image" then
        frames[#frames + 1] = { kids[i - 1], kids[i + 1] }
      end
    end
    for i = 1, n do if kids[i] then go(kids[i], d + 1) end end
  end
  go(root, 0)
  local A = R.Assets(widget, root)
  local st = { widget = widget ~= nil, frames = #frames, painted = 0, markers = #markers, ours = 0, parts = 0,
               visited = 150000 - budget,
               objects = (A.back and 1 or 0) + (A.front and 1 or 0) + (A.sym and 1 or 0) + (A.symBrush and 1 or 0)
                 + (A.arrowBrush and 1 or 0) }
  for _, f in ipairs(frames) do
    if R.PaintFrame(f[1], f[2], A) then st.painted = st.painted + 1 end
  end
  for _, m in ipairs(markers) do
    if isOurs(m) then st.ours = st.ours + 1; st.parts = st.parts + R.PaintMarker(m, A) end
  end
  R.stats = st
  return st
end
