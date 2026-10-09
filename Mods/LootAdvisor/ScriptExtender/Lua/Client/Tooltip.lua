-- Loot Advisor client: advice inside the game's own tooltips.
--  * Item tooltips: while the hovered item is recommended for the selected character, the tooltip's description
--    strip (Control "LoreDescriptionSection") is given our template (Pages/LootAdvisorRes.xaml,
--    LA.ItemAdviceTemplate): the game's description strip, then ONE row like the tooltip's other rows - our rainbow
--    diamond in the description icon's column, a short title in our colour ("Best Gloves for Astarion") and one
--    short line (why / warning / status). Nothing is written into game texts; only this tooltip's UI is touched,
--    and the game's own template is put back as soon as the tooltip shows an item that is not recommended (or the
--    mod / tooltips are switched off).
--  * Map marker labels (our markers only): the label's content template gets our diamond in front of the text
--    (item names, one per line, written by the server); the game's template is put back for other markers.
-- Open tooltips are found by a cheap per-frame check (T.Watch): the children of the root's PopupLayer.
-- SE v32 element handles die at the end of the tick that made them ("DEAD REFERENCE"), so nothing UI is kept
-- across ticks: our templates are recognised by address (tostring), and the game's own templates are parked in the
-- Tag of two hidden elements of our widget (LA_KeepItemTpl / LA_KeepMarkerTpl) when we first replace them.

LA = LA or {}
LA.Tip = LA.Tip or {}
local T = LA.Tip
local UI = LA.UI
local try = LA.try

T.advice = {}   -- stats id -> { title, body, warn }
T.tplId = {}    -- root template -> stats id
T.stats = { scans = 0, item = 0, marker = 0, restored = 0, ms = 0, maxMs = 0 }

local function prop(el, p) return try(function() return el:GetProperty(p) end) end
local function set(el, p, v) return pcall(function() el:SetProperty(p, v) end) end
local function parent(el) return try(function() return el.VisualParent end) end

------------------------------------------------------------------------------------------------------------------
-- texts
------------------------------------------------------------------------------------------------------------------
local TITLE_SLOT = { MainHand = "Weapon", OffHand = "Off-hand", Ranged = "Ranged weapon", RangedOff = "Off-hand ranged",
                     Helmet = "Helmet", Cloak = "Cloak", Breast = "Armour", Gloves = "Gloves", Boots = "Boots",
                     Amulet = "Amulet", Ring1 = "Ring", Ring2 = "Ring", Elixir = "Elixir" }
local STATUS = { owned = "You have it", marker = "On your map", elsewhere = "In another area",
                 nospot = "No fixed spot (see F6)", list = "In the F6 list", setonly = "Set item",
                 onlyowned = "Only if you already have it" }
local MAXLINE = 52 -- characters that fit one tooltip line next to the icon (the TextBlock also trims with "...")

local function clean(s)
  s = tostring(s or ""):gsub("[<>]", ""):gsub("%s*%b()", ""):gsub("%s+", " ")
  return (s:gsub("^[%s|]+", ""):gsub("[%s%.;,|]+$", ""))
end

-- first sentence, then whole comma / semicolon parts while they fit
local function fit(s, budget)
  s = clean((tostring(s or "")):match("^(.-%.)%s") or s)
  if #s <= budget then return s end
  local out = ""
  for part in (s:gsub(" %- ", ";") .. ","):gmatch("%s*([^,;]+)[,;]") do
    local nxt = out == "" and part or (out .. ", " .. part)
    if #nxt > budget then break end
    out = nxt
  end
  if out ~= "" then return out end
  local cut = s:sub(1, budget - 3):gsub("%s+%S*$", "")
  return cut .. "..."
end

local function shortWhy(why, budget)
  local first = clean((tostring(why or "")):match("^(.-%.)%s") or why)
  if first == "" then return "" end
  if first:match("^Community") or first:match("^Used in") then return "Community pick" end
  return fit(first, budget)
end

-- the most telling part of a warning: missable > a kill / loss > theft > the first sentence
local WARN_RANK = { { "Missable" }, { "kill", "die", "Lost", "lost" }, { "steal", "stolen", "theft", "Theft", "pickpocket" } }
local function shortWarn(w)
  local s = tostring(w or "")
  local who = s:match("Taking it from (.-) means killing or pickpocketing")
  if who then return fit("Kill or pickpocket " .. who, MAXLINE) end
  local best, bestRank
  for sen in (s .. " "):gmatch("%s*(.-[%.;])%s") do
    local rank = 9
    for i, keys in ipairs(WARN_RANK) do
      for _, key in ipairs(keys) do if rank == 9 and sen:find(key, 1, true) then rank = i end end
    end
    if not best or rank < bestRank then best, bestRank = sen, rank end
  end
  local out = fit(best or s, MAXLINE)
  return (out:gsub("^%l", string.upper))
end

-- one row per recommended item: the most important of its rows (best > runner-up > set > greyed)
local function primary(rows)
  local best
  for _, r in ipairs(rows) do
    local k = (r.rank and r.rank > 0) and r.rank or 9
    if not best or k < best.k then best = { k = k, r = r } end
  end
  return best and best.r
end

function T.Text(rows, who)
  local r = primary(rows)
  if not r then return nil end
  local slot = TITLE_SLOT[r.slot] or LA.SLOT_NAME[r.slot] or r.slot
  local title
  if r.rank == 1 then title = ("Best %s for %s"):format(slot, who)
  elseif r.rank == 2 then title = ("Runner-up %s for %s"):format(slot, who)
  elseif r.rank == 3 then title = ("Set %s for %s"):format(slot, who)
  else title = ("%s for %s"):format(slot, who) end

  local body, warn
  if r.s == "better" and r.better then
    body = "Better on " .. (LA.CHAR_NAME[r.better] or r.better)
  elseif r.s == "closed" then
    body = fit("Path closed: " .. clean(r.reason or ""), MAXLINE)
  elseif r.shared and #r.shared > 0 then
    local nm = {}
    for _, c in ipairs(r.shared) do nm[#nm + 1] = LA.CHAR_NAME[c] or c end
    body = fit("Shared pick with " .. table.concat(nm, ", "), MAXLINE)
  elseif r.w and r.w ~= "" and r.s ~= "owned" then
    body, warn = shortWarn(r.w), true
  else
    local st = STATUS[r.s] or ""
    if r.enter then st = "Way marked on your map" end
    local why = shortWhy(r.why, MAXLINE - #st - 3)
    body = (st ~= "" and why ~= "") and (st .. " · " .. why) or (st ~= "" and st or why)
  end
  return { title = title, body = body or "", warn = warn or false }
end

-- result -> advice per stats id / template (no game text is changed)
function T.Apply(res)
  local advice, tplId = {}, {}
  if res and res.rows and not res.notCovered then
    -- decision 76: the Dark Urge is the player's own character -> the name the player gave it ("Best Ring for <name>")
    local own = type(res.name) == "string" and res.name ~= "" and res.name or nil
    local who = (res.char == "darkurge" and own) or LA.CHAR_NAME[res.char] or own or "?"
    local per = {}
    for _, r in ipairs(res.rows) do
      -- list-only items (generic +1/+2, random loot) get no tooltip text and no frame
      if r.mode ~= "l" or r.s == "owned" then
        per[r.id] = per[r.id] or {}
        table.insert(per[r.id], r)
      end
    end
    for id, rows in pairs(per) do
      advice[id] = T.Text(rows, who)
      for _, r in ipairs(rows) do for _, t in ipairs(r.t or {}) do tplId[t] = id end end
    end
  end
  T.advice, T.tplId = advice, tplId
  T.gen = (T.gen or 0) + 1 -- open tooltips are refreshed on the next check
end

------------------------------------------------------------------------------------------------------------------
-- our templates / images (from the hidden widget LootAdvisorRes) - looked up again in every tick that needs them
------------------------------------------------------------------------------------------------------------------
local function realRes(w, key)
  local r = try(function() return w:Resource(key) end)
  local ty = r and UI.Type(r)
  -- a missing key returns one shared dummy BaseComponent
  if ty and ty ~= "Noesis::BaseComponent" and ty ~= "BaseComponent" then return r end
end
local function Assets()
  local root = UI.Root()
  local w = root and UI.FindNamed(root, "LootAdvisorRes", 8)
  if not w then return nil end
  local A = {
    itemTpl = realRes(w, "LA.ItemAdviceTemplate"),
    markerTpl = realRes(w, "LA.MarkerTipTemplate"),
    keepItem = UI.FindNamed(w, "LA_KeepItemTpl", 6),
    keepMarker = UI.FindNamed(w, "LA_KeepMarkerTpl", 6),
  }
  A.ok = A.itemTpl ~= nil and A.keepItem ~= nil
  return A.ok and A or nil
end
T.Assets = Assets

------------------------------------------------------------------------------------------------------------------
-- item tooltips
------------------------------------------------------------------------------------------------------------------
local function enabled() return LA.Settings.Enabled ~= false and LA.Settings.Tooltips ~= false end

-- the VMItem of the tooltip that holds this element (the tooltip content presenter's DataContext)
local function itemOf(el)
  local e = el
  for _ = 1, 12 do
    e = parent(e)
    if not e then return nil end
    local dc = UI.DC(e)
    if dc and UI.Type(dc) == "ls.VMItem" then return dc end
  end
end

local function adviceForVM(vm)
  local uuid = vm and LA.Paint.vp(vm, "EntityUUID")
  if type(uuid) ~= "string" then return nil end
  local ii = LA.Paint.itemInfo(uuid)
  local id = (ii.stats and T.advice[ii.stats] and ii.stats) or (ii.tpl and T.tplId[ii.tpl])
  return id and T.advice[id]
end

local function setText(el, v)
  if el and prop(el, "Text") ~= v then set(el, "Text", v) end
end
local function setVis(el, on)
  local v = on and "Visible" or "Collapsed"
  if el and tostring(prop(el, "Visibility")) ~= v then set(el, "Visibility", v) end
end

local function fill(el, adv)
  local title = UI.FindNamed(el, "LA_TipTitle", 12)
  if not title then return false end
  local body, warn = UI.FindNamed(el, "LA_TipBody", 12), UI.FindNamed(el, "LA_TipWarn", 12)
  setText(title, adv.title)
  local has = adv.body ~= ""
  setText(body, adv.warn and "" or adv.body)
  setVis(body, has and not adv.warn)
  setText(warn, adv.warn and adv.body or "")
  setVis(warn, has and adv.warn)
  return true
end

-- the game's template, parked in a hidden element's Tag the first time we replace it
local function keep(holder, orig)
  if holder and orig and not prop(holder, "Tag") then set(holder, "Tag", orig) end
end

-- returns true when this element needs another look next tick (our template not applied yet)
local function itemTip(lore, A)
  local cur = prop(lore, "Template")
  local mine = cur ~= nil and tostring(cur) == tostring(A.itemTpl)
  local adv = enabled() and adviceForVM(itemOf(lore)) or nil
  if not adv then
    if mine then
      local orig = prop(A.keepItem, "Tag")
      if orig and set(lore, "Template", orig) then T.stats.restored = T.stats.restored + 1 end
    end
    return false
  end
  if not mine then
    if not cur then return false end
    keep(A.keepItem, cur)
    if not set(lore, "Template", A.itemTpl) then return false end
    return true -- texts next tick, once the template is applied
  end
  T.stats.item = T.stats.item + 1
  return not fill(lore, adv)
end

------------------------------------------------------------------------------------------------------------------
-- map marker labels
------------------------------------------------------------------------------------------------------------------
-- holder: the label's ContentPresenter "tooltipContent" (DataContext ls.MapMarker); pres: its child "root",
-- whose ContentTemplate is the label template (one template for every marker type, verified)
local function markerTip(holder, pres, A)
  local cur = prop(pres, "ContentTemplate")
  local mine = cur ~= nil and A.markerTpl ~= nil and tostring(cur) == tostring(A.markerTpl)
  local vm = UI.DC(holder)
  local h = vm and LA.Paint.vp(vm, "Name")
  local ours = enabled() and A.markerTpl and type(h) == "string" and LA.MarkerRank and LA.MarkerRank[h]
  if not ours then
    if mine then
      local orig = prop(A.keepMarker, "Tag")
      if orig and set(pres, "ContentTemplate", orig) then T.stats.restored = T.stats.restored + 1 end
    end
    return false
  end
  if not mine then
    if not cur then return false end
    keep(A.keepMarker, cur)
    if not set(pres, "ContentTemplate", A.markerTpl) then return false end
    return true
  end
  T.stats.marker = T.stats.marker + 1
  local text = UI.FindNamed(pres, "LA_MarkText", 6)
  if not text then return true end
  local s = try(Ext.Loca.GetTranslatedString, h)
  if type(s) == "string" and s ~= "" then setText(text, s) end
  return false
end

------------------------------------------------------------------------------------------------------------------
-- finding open tooltips
------------------------------------------------------------------------------------------------------------------
-- one open popup subtree -> its item description strips / marker label presenters
local function scanTip(tip, found)
  UI.Walk(tip, function(el)
    local nm = UI.Name(el)
    if nm == "LoreDescriptionSection" then found[#found + 1] = { "item", el }; return "skip" end
    if nm == "tooltipContent" then
      local dc = UI.DC(el)
      if dc and UI.Type(dc) == "ls.MapMarker" then
        local pres = UI.FindNamed(el, "root", 2)
        if pres then found[#found + 1] = { "marker", pres, el } end
        return "skip"
      end
    end
  end, 4000)
end

-- The open tooltips: every child of the root visual's PopupLayer (tooltips are popups; usually 0-2 of them).
function T.FindTips()
  local r = UI.Root()
  local rv = r and parent(r)
  rv = rv and parent(rv)
  if not rv then return {} end
  local tips = {}
  for i = 1, (try(function() return rv.VisualChildrenCount end) or 0) do
    local c = try(function() return rv:VisualChild(i) end)
    if c and UI.Type(c) == "PopupLayer" then
      for j = 1, (try(function() return c.VisualChildrenCount end) or 0) do
        local p = try(function() return c:VisualChild(j) end)
        if p then tips[#tips + 1] = p end
      end
      break
    end
  end
  return tips
end

local lastSig, lastScan, pending = nil, 0, 0
local RESCAN_MS = 150 -- an open tooltip can change its item without a new popup: look again this often
function T.Watch()
  local t0 = Ext.Utils.MonotonicTime()
  local tips = T.FindTips()
  if #tips == 0 and pending == 0 then lastSig = nil; return end
  local parts = { tostring(T.gen), tostring(enabled()) }
  for _, t in ipairs(tips) do parts[#parts + 1] = tostring(t) end
  local sig = table.concat(parts, "|")
  if sig == lastSig and pending == 0 and t0 - lastScan < RESCAN_MS then return end
  lastSig, lastScan = sig, t0
  local A = Assets()
  if not A then return end
  T.stats.scans = T.stats.scans + 1
  local again = false
  for _, tip in ipairs(tips) do
    local found = {}
    scanTip(tip, found)
    for _, f in ipairs(found) do
      local a
      if f[1] == "item" then a = itemTip(f[2], A) else a = markerTip(f[3], f[2], A) end
      again = again or a
    end
  end
  pending = again and math.min(pending + 1, 30) or 0
  if pending >= 30 then pending = 0 end -- give up on an element that never takes our template
  T.stats.ms = Ext.Utils.MonotonicTime() - t0
  if T.stats.ms > T.stats.maxMs then T.stats.maxMs = T.stats.ms end
end

-- mod / tooltips switched off: forget the advice; open tooltips get the game's template back in Watch, closed
-- ones the next time they open (Watch keeps running while the mod is off)
function T.RestoreAll()
  T.advice, T.tplId = {}, {}
  T.gen = (T.gen or 0) + 1
end
