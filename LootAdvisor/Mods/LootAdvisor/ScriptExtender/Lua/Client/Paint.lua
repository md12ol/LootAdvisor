-- LootAdvisor client paint pass:
--  * item frames: every [Image back, Rectangle icon, Image front] sibling triple whose Image DataContext is an
--    ls.VMItem -> rainbow Prism frame when the item is recommended (Result.frames), else the game's own frame back;
--    covers inventory / container / camp chest / trade cells, bags, paperdoll slots and hotbar items;
--  * our journal map markers (VM Name = one of our DisplayText handles): rainbow diamond in view, the game's own
--    off-screen arrow recoloured rainbow; only the 5 best off-screen markers keep an arrow.
-- Speed (15-24 ms per pass over the whole tree): only the widgets under ContentRoot that can hold items or
-- map markers are walked (a fixed list of HUD widgets that never do is skipped), leaves are not entered, and the
-- marker subtree is handled where it is found.

LA = LA or {}
LA.Paint = LA.Paint or {}
local P = LA.Paint
local UI = LA.UI
local try = LA.try

P.painted = P.painted or {}   -- [tostring(back Image)] = true
P.hidden = P.hidden or {}     -- [tostring(marker element)] = true (arrow suppressed)
P.stats = {}

-- HUD widgets that never show items or map markers (probe 2026-10-08, ContentRoot children)
P.SKIP = { OverheadInfo = true, HudIndicator = true, TargetInfo = true, TurnModeInfo = true, CombatLog = true,
           CombatantsOverlay = true, WorldTooltips = true, PlayerPortraits = true, PassiveRoll = true,
           CursorText = true, AlwaysOnTopOverlay = true, WorldContextMenu = true, NotificationWidget = true,
           DragAndDropPreview = true, ScreenFade = true, CrossplayOverlay = true, Overlay = true }
local LEAF = { Image = true, TextBlock = true, Rectangle = true, Ellipse = true, Path = true, ["ls.LSTextBlock"] = true,
               ["ls.TextBlockFormatter"] = true }
local GAME = { Uncommon = true, Rare = true, VeryRare = true, Legendary = true, Story = true }

local function prop(el, p) return try(function() return el:GetProperty(p) end) end
local function set(el, p, v) return pcall(function() el:SetProperty(p, v) end) end
local function child(el, i) return try(function() return el:VisualChild(i) end) end
local function vp(vm, k)
  local v = try(function() return vm:GetProperty(k) end)
  if v == nil then v = try(function() return vm[k] end) end
  return v
end
P.vp = vp

function P.Assets(widget)
  local A = { game = {} }
  if not widget then return A end
  local function named(n, p)
    local e = UI.FindNamed(widget, n, 6)
    return e and prop(e, p)
  end
  A.back, A.front = named("LA_FrameBack", "Source"), named("LA_FrameFront", "Source")
  A.sym = named("LA_MapSymbol", "Source")
  A.symBrush, A.arrowBrush = named("LA_MapSymbolBrush", "Fill"), named("LA_MapArrowBrush", "Fill")
  for k in pairs(GAME) do
    A.game[k] = { back = named("LA_Game_" .. k .. "_Back", "Source"), front = named("LA_Game_" .. k .. "_Front", "Source") }
  end
  return A
end

-- uuid -> { tpl, stats } (client entity), cached per uuid
local info = {}
local function itemInfo(uuid)
  local r = info[uuid]
  if r == nil then
    local e = try(Ext.Entity.Get, uuid)
    local tpl = e and try(function() return e.GameObjectVisual.RootTemplateId end)
    local stats = e and try(function() return e.Data.StatsId end)
    if not stats and tpl then
      local t = try(Ext.Template.GetRootTemplate, tpl)
      stats = t and try(function() return t.Stats end)
    end
    r = { tpl = tpl, stats = stats }
    info[uuid] = r
  end
  return r
end
P.itemInfo = itemInfo

local function recommendedId(ii, res)
  return (ii.stats and res.frames[ii.stats] and ii.stats) or (ii.tpl and LA.FrameTemplates[ii.tpl]) or nil
end

-- bags: framed when they hold a recommended item (contents re-read at most every 2 s per bag)
local bagCache = {}
local function bagHolds(uuid, res, depth)
  local now = Ext.Utils.MonotonicTime()
  local c = bagCache[uuid]
  if c and now - c.t < 2000 and c.res == res then return c.v end
  local v = false
  local e = try(Ext.Entity.Get, uuid)
  local items = e and try(function() return e.InventoryOwner.PrimaryInventory.InventoryContainer.Items end)
  for _, slot in pairs(items or {}) do
    local it = try(function() return slot.Item end)
    local u = it and try(function() return it.Uuid.EntityUuid end)
    if u then
      if recommendedId(itemInfo(u), res) then v = true; break end
      if (depth or 0) < 2 and bagHolds(u, res, (depth or 0) + 1) then v = true; break end
    end
  end
  bagCache[uuid] = { t = now, v = v, res = res }
  return v
end

function P.Wanted(vm)
  local res = LA.Result
  if not res or LA.Settings.Frames == false then return false end
  local uuid = vp(vm, "EntityUUID")
  if type(uuid) ~= "string" then return false end
  local ii = itemInfo(uuid)
  local id = recommendedId(ii, res)
  if id then return true end
  if vp(vm, "IsContainer") then return bagHolds(uuid, res, 0) end
  return false
end

function P.PaintFrame(back, front, A)
  local vm = UI.DC(back)
  if not vm or UI.Type(vm) ~= "ls.VMItem" then return false end
  local k = tostring(back)
  if P.Wanted(vm) and A.back and A.front then
    set(back, "Source", A.back); set(back, "Visibility", "Visible")
    set(front, "Source", A.front); set(front, "Visibility", "Visible")
    P.painted[k] = true
    return true
  elseif P.painted[k] then
    local story = vp(vm, "IsStoryItem")
    local g = A.game[story and "Story" or tostring(vp(vm, "Rarity"))]
    if g and g.back and g.front then
      set(back, "Source", g.back); set(front, "Source", g.front)
      set(back, "Visibility", "Visible"); set(front, "Visibility", "Visible")
    else
      set(back, "Visibility", "Collapsed"); set(front, "Visibility", "Collapsed")
    end
    P.painted[k] = nil
  end
  return false
end

-- the parts of a marker we restyle: in-view Image "Icon" (Source, Tag), off-screen Canvas "IconHolder" (Background),
-- Ellipse "OutIcon" (minimap) / "Icon" (world map) (Fill)
local function markerParts(marker)
  local parts = {}
  UI.Walk(marker, function(c)
    local nm, ty = UI.Name(c), UI.Type(c)
    if nm == "Icon" and ty == "Image" then parts.icon = c
    elseif nm == "IconHolder" then parts.holder = c
    elseif nm == "OutIcon" or (nm == "Icon" and ty == "Ellipse") then parts.out = c end
  end, 300)
  return parts
end

P.markerPainted = P.markerPainted or {} -- [tostring(marker element)] = true
P.gameLook = P.gameLook or {}           -- [marker Type] = { src, tag, bg, fill } read from unpainted game markers

local function paintMarker(marker, parts, A)
  local p = parts
  if p.icon and A.sym then set(p.icon, "Source", A.sym); set(p.icon, "Tag", A.sym) end
  if p.holder and A.arrowBrush then set(p.holder, "Background", A.arrowBrush) end
  if p.out and A.symBrush then set(p.out, "Fill", A.symBrush) end
  P.markerPainted[tostring(marker)] = true
end

-- Noesis recycles marker elements: an element we painted can later show a game marker. There is no ClearValue in
-- SE v32 (SetProperty(nil) is refused), so the game's own values are put back, read from unpainted markers of the
-- same Type (verified: every QuestMarker shares one arrow brush and one fill brush).
-- true when any part of this element still carries one of our images (painted earlier, then recycled)
local function carriesOurs(parts, A)
  local ours = { [tostring(A.sym)] = true, [tostring(A.arrowBrush)] = true, [tostring(A.symBrush)] = true }
  return (parts.icon and ours[tostring(prop(parts.icon, "Source"))])
      or (parts.holder and ours[tostring(prop(parts.holder, "Background"))])
      or (parts.out and ours[tostring(prop(parts.out, "Fill"))]) or false
end

local function learnGameLook(ty, parts)
  local g = P.gameLook[ty] or {}
  P.gameLook[ty] = g
  if parts.icon then
    local src = prop(parts.icon, "Source")
    if src then g.src = src; g.tag = prop(parts.icon, "Tag") end
  end
  if parts.holder then g.bg = prop(parts.holder, "Background") or g.bg end
  if parts.out then g.fill = prop(parts.out, "Fill") or g.fill end
end

local function restoreMarker(marker, ty, parts)
  local g = P.gameLook[ty]
  if not g then return false end
  if parts.icon and g.src then set(parts.icon, "Source", g.src); set(parts.icon, "Tag", g.tag or g.src) end
  if parts.holder and g.bg then set(parts.holder, "Background", g.bg) end
  if parts.out and g.fill then set(parts.out, "Fill", g.fill) end
  P.markerPainted[tostring(marker)] = nil
  return true
end

local function insideViewport(marker, vm)
  local v = prop(marker, "IsInsideViewport")
  if v == nil and vm then v = vp(vm, "IsInsideViewport") end
  return v
end

-- markers of one map widget: paint ours, allow the off-screen arrow only for the best N
-- the game's own marker on the same object as ours (e.g. a trader's icon) is drawn on top of ours: hide it while
-- ours is there, so the trader shows our rainbow diamond ("marker on the trader")
P.covered = P.covered or {}  -- [tostring(element)] = true: game marker hidden by us
-- same spot = same object: GameObject reads back as a different wrapper per marker, WorldPos is equal (verified)
local function objKey(vm)
  local p = vm and vp(vm, "WorldPos")
  if type(p) ~= "table" then return nil end
  local x, z = p[1] or p.x, p[3] or p[2] or p.y  -- WorldPos is the map position {x, z} (verified)
  if not (x and z) then return nil end
  return ("%d|%d"):format(math.floor(x * 2 + 0.5), math.floor(z * 2 + 0.5))
end

local function handleMarkers(list, A, st)
  local off = {}
  local recycled = {}
  local ourObjs = {}
  for _, m in ipairs(list) do
    local vm = UI.DC(m)
    local h = vm and vp(vm, "Name")
    if type(h) == "string" and LA.MarkerRank and LA.MarkerRank[h] then
      local o = objKey(vm)
      if o then ourObjs[o] = true end
    end
  end
  for _, m in ipairs(list) do
    local vm = UI.DC(m)
    local h = vm and vp(vm, "Name")
    local rk = type(h) == "string" and LA.MarkerRank and LA.MarkerRank[h]
    local k = tostring(m)
    if rk then
      st.ours = st.ours + 1
      P.ourMarkersNext[#P.ourMarkersNext + 1] = m
      paintMarker(m, markerParts(m), A)
      local inside = insideViewport(m, vm)
      if inside == false then off[#off + 1] = { m = m, rk = rk } else
        if P.hidden[k] then set(m, "Opacity", 1.0); P.hidden[k] = nil end
      end
    else
      local ty = tostring(vm and vp(vm, "Type"))
      local parts = markerParts(m)
      if P.markerPainted[k] or carriesOurs(parts, A) then
        recycled[#recycled + 1] = { m = m, ty = ty }
      else
        learnGameLook(ty, parts)
      end
      local o = objKey(vm)
      if o and ourObjs[o] then
        if not P.covered[k] then set(m, "Opacity", 0.0); P.covered[k] = true end
        st.covered = (st.covered or 0) + 1
      elseif P.covered[k] then
        set(m, "Opacity", 1.0); P.covered[k] = nil
      elseif P.hidden[k] then set(m, "Opacity", 1.0); P.hidden[k] = nil end
    end
  end
  for _, r in ipairs(recycled) do
    if restoreMarker(r.m, r.ty, markerParts(r.m)) then st.restored = (st.restored or 0) + 1 end
  end
  table.sort(off, function(a, b) return a.rk < b.rk end)
  local maxArrows = tonumber(LA.Settings.Arrows) or 5
  for i, o in ipairs(off) do
    local k = tostring(o.m)
    if i <= maxArrows then
      if P.hidden[k] then set(o.m, "Opacity", 1.0); P.hidden[k] = nil end
      st.arrows = st.arrows + 1
    else
      if not P.hidden[k] then set(o.m, "Opacity", 0.0); P.hidden[k] = true end
      st.suppressed = st.suppressed + 1
    end
  end
end

function P.Pass()
  local t0 = Ext.Utils.MonotonicTime()
  local root = UI.Root()
  if not root then return end
  local content = try(function() return root:Find("ContentRoot") end) or root
  local widgets = {}
  local res
  for i = 1, (try(function() return content.VisualChildrenCount end) or 0) do
    local w = child(content, i)
    local nm = w and UI.Name(w)
    if nm == "LootAdvisorRes" then res = w
    elseif w and not P.SKIP[nm] then widgets[#widgets + 1] = w end
  end
  if not res then res = UI.FindNamed(root, "LootAdvisorRes", 8) end
  local A = P.Assets(res)
  local st = { widgets = #widgets, visited = 0, frames = 0, painted = 0, markers = 0, ours = 0, arrows = 0,
               suppressed = 0, assets = A.back ~= nil and A.arrowBrush ~= nil }
  local frames = {}
  P.ourMarkersNext = {}
  for _, w in ipairs(widgets) do
    local markers = {}
    local budget = 60000
    local function go(el, d)
      if budget <= 0 or d > 90 then return end
      budget = budget - 1
      local ty = UI.Type(el)
      if ty == "ls.LSWorldMapMarker" then markers[#markers + 1] = el; return end
      if LEAF[ty] then return end
      local n = try(function() return el.VisualChildrenCount end) or 0
      if n == 0 then return end
      local kids, types = {}, {}
      for i = 1, n do kids[i] = child(el, i); types[i] = kids[i] and UI.Type(kids[i]) end
      for i = 2, n - 1 do
        if types[i] == "Rectangle" and types[i - 1] == "Image" and types[i + 1] == "Image" then
          frames[#frames + 1] = { kids[i - 1], kids[i + 1] }
        end
      end
      for i = 1, n do if kids[i] and not LEAF[types[i]] then go(kids[i], d + 1) end end
    end
    go(w, 0)
    st.visited = st.visited + (60000 - budget)
    st.markers = st.markers + #markers
    if #markers > 0 then handleMarkers(markers, A, st) end
  end
  P.ourMarkers = P.ourMarkersNext
  st.frames = #frames
  for _, f in ipairs(frames) do
    if P.PaintFrame(f[1], f[2], A) then st.painted = st.painted + 1 end
  end
  st.ms = Ext.Utils.MonotonicTime() - t0
  P.stats = st
  return st
end
