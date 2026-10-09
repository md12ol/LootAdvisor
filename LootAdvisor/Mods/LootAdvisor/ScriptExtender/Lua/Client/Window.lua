-- LootAdvisor list window (Script Extender IMGUI, styled like BuildAdvisor's). Hotkey (settings "Hotkey", default
-- F6) toggles it. Layout:
--   1. "Next" - the items you can get now, nearest first (map marker / entrance / way out), with direction;
--   2. every recommended item by slot (rings merged into one group), short status words (full sentence on hover);
--   3. a legend for the status words and the marks; no internal ids; one coordinate format (X 29, Y 405).

LA = LA or {}
LA.Win = LA.Win or {}
local W = LA.Win
local try = LA.try

local GOLD = { 1.0, 0.8, 0.3, 1.0 }
local GREY = { 0.55, 0.55, 0.55, 1.0 }
local GREEN = { 0.45, 1.0, 0.45, 1.0 }
local BLUE = { 0.6, 0.8, 1.0, 1.0 }
local VIOLET = { 0.85, 0.6, 1.0, 1.0 }
local WHITE = { 0.92, 0.9, 0.85, 1.0 }

local function colored(t, c) if c then try(function() t:SetColor("Text", c) end) end return t end
local function short(s, n) s = tostring(s or ""); if #s > n then return s:sub(1, n - 3) .. "..." end return s end
local function tip(el, text) if text and text ~= "" then try(function() el:Tooltip():AddText(text) end) end end
local function cname(c) return LA.CHAR_NAME[c] or tostring(c) end

local COMPASS = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" }
-- +Z = north, +X = east (verified against the minimap); settings NorthZ/EastX can flip them.
function W.Direction(x, z)
  local e = LA.selectedEntity
  local p = e and try(function() return e.Transform.Transform.Translate end)
  if not (p and x and z) then return nil end
  local dx = (x - p[1]) * (tonumber(LA.Settings.EastX) or 1)
  local dz = (z - p[3]) * (tonumber(LA.Settings.NorthZ) or 1)
  local dist = math.sqrt(dx * dx + dz * dz)
  local a = (math.deg(math.atan(dx, dz)) + 360) % 360
  return ("%s %.0f m"):format(COMPASS[math.floor((a + 22.5) / 45) % 8 + 1], dist), dist
end

-- one coordinate format for the how-to texts: "X 29, Y 405" (the map's X/Y; texts mixed X:/x/z forms)
local function coords(s)
  s = tostring(s or "")
  s = s:gsub("%(?[Xx]%s*:?%s*(%-?%d+%.?%d*)%s*[,;]?%s*[YyZz]%s*:?%s*(%-?%d+%.?%d*)%)?", function(x, y)
    return ("(X %d, Y %d)"):format(math.floor(tonumber(x) + 0.5), math.floor(tonumber(y) + 0.5))
  end)
  s = s:gsub("[;,]?%s*key id [%w_%-]+", "")
  return s
end

-- short status word + colour + the full sentence for the hover
local function status(r)
  local s, full, col = r.s, nil, nil
  local area = r.enter or r.where
  if r.enter and r.viaWaypoint then
    return "Fast travel", ("In %s: fast travel there (a waypoint near you is marked)."):format(area), BLUE
  elseif r.enter and r.away then
    return "Way out marked", ("In %s: the way out of this region is marked on your map."):format(area), BLUE
  elseif r.enter and r.direct then
    return "Enter area", ("Inside %s: its entrance is marked on your map - enter there."):format(area), GOLD
  elseif r.enter then
    return "Way marked", ("Inside %s: the next entrance on the way is marked on your map."):format(area), GOLD
  end
  if s == "owned" then return "Owned", "You or the camp chest have it.", GREEN
  elseif s == "marker" then return "On your map", "Marked on your map (rainbow diamond).", GOLD
  elseif s == "elsewhere" then return "Other area", ("In %s (no marker from here)."):format(area or "another area"), BLUE
  elseif s == "list" then
    full = "Not marked: random loot or a common item."
    if r.odds and r.odds > 0 and r.odds < 1 then full = full .. (" Chance about %d%%."):format(math.floor(r.odds * 100 + 0.5)) end
    return "List only", full, nil
  elseif s == "nospot" then return "No fixed spot", "No fixed place to mark (reward, random or a wandering NPC).", nil
  elseif s == "setonly" then return "Set item", "Part of a set below; not marked on the map.", VIOLET
  elseif s == "closed" then return "Path closed", tostring(r.reason or "Your story choices closed this path."), GREY
  elseif s == "better" then return "Better on " .. cname(r.better), ("Fits %s better (best use in your party)."):format(cname(r.better)), GREY
  elseif s == "onlyowned" then return "If you have it", "From an earlier act: counts only if you already have it.", GREY
  end
  return tostring(s), nil, nil
end

local PICK = { [1] = "best", [2] = "runner-up", [0] = "-", [3] = "set" }
local SLOT_GROUP = { Ring1 = "Rings", Ring2 = "Rings" }

function W.Init()
  if W.window then return end
  local w = Ext.IMGUI.NewWindow("Loot Advisor")
  w.Closeable = true
  w.Open = false
  W.window = w
  W.header = w:AddGroup("hdr")
  W.content = w:AddGroup("content")
end

local function place(w)
  local vp = try(Ext.IMGUI.GetViewportSize)
  if not (vp and vp[1]) then return end
  try(function() w:SetPos({ vp[1] * 0.15, vp[2] * 0.07 }, "Always") end)
  try(function() w:SetSize({ vp[1] * 0.66, vp[2] * 0.70 }, "Always") end)
end

function W.Toggle()
  W.Init()
  if not W.placed then place(W.window); W.placed = true end
  W.window.Open = not W.window.Open
  if W.window.Open then W.Render(LA.Result) end
end

function W.Show(open)
  W.Init()
  if not W.placed then place(W.window); W.placed = true end
  W.window.Open = open ~= false
  if W.window.Open then W.Render(LA.Result) end
end

local function reset(name)
  if W[name] then try(function() W[name]:Destroy() end) end
  W[name] = W.window:AddGroup(name)
  return W[name]
end

local SLOTI = {}
for i, s in ipairs(LA.SLOTS) do SLOTI[s] = i end
local RORD = { [1] = 1, [2] = 2, [3] = 3, [0] = 4 }

-- rows -> display rows: rings merged into one group, one line per item per group (best pick kept, sets merged)
local function displayRows(res)
  local out, byKey = {}, {}
  for _, r in ipairs(res.rows) do
    local grp = SLOT_GROUP[r.slot] or r.slot
    local key = grp .. "|" .. r.id
    local d = byKey[key]
    if not d then
      d = setmetatable({ group = grp, sets = {} }, { __index = r })
      byKey[key] = d
      out[#out + 1] = d
    elseif (RORD[r.rank] or 9) < (RORD[d.rank] or 9) then
      local sets = d.sets
      d = setmetatable({ group = grp, sets = sets }, { __index = r })
      byKey[key] = d
      for i, x in ipairs(out) do if x.group == grp and x.id == r.id then out[i] = d end end
    end
    for _, s in ipairs(r.sets or {}) do
      local dup = false
      for _, x in ipairs(d.sets) do if x == s then dup = true end end
      if not dup then d.sets[#d.sets + 1] = s end
    end
  end
  return out
end

local function nameCell(row, r, grey)
  local _, _, scol = status(r)
  local mark = (r.s == "marker" or r.enter) and "* " or ""
  local warn = ((r.w and r.w ~= "") or (r.sev and r.sev ~= "Tip")) and r.s ~= "closed" and " (!)" or ""
  local t = colored(row:AddCell():AddText(mark .. short(r.n, 32) .. warn), grey or scol or WHITE)
  local h = {}
  if r.why and r.why ~= "" then h[#h + 1] = "Why: " .. r.why end
  if r.shared then
    local nm = {}
    for _, c in ipairs(r.shared) do nm[#nm + 1] = cname(c) end
    h[#h + 1] = "Shared pick: " .. table.concat(nm, ", ") .. " fit it equally well."
  end
  if r.alt then h[#h + 1] = "Set slot: " .. r.alt end
  if r.w and r.w ~= "" then h[#h + 1] = (r.sev and r.sev .. ": " or "Warning: ") .. r.w
  elseif r.sev then h[#h + 1] = "Note: " .. r.sev end
  tip(t, table.concat(h, "\n"))
end

-- "Open Sets page". Script Extender v32 has no way to open a URL or file or to set the clipboard
-- (checked in game: Ext.IO / Utils / IMGUI / UI / Input / Debug / Mod / Types, no os / io / package), so the button
-- shows the page's path in a read-only field: click it (selects all), Ctrl+C, then Win+R, Ctrl+V, Enter.
W.PAGE_PATH = [[%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor\Sets.html]]
local function pageRow(h)
  local b = h:AddButton(W.showPath and "Hide Sets page path" or "Open Sets page")
  try(function() b.OnClick = function() W.showPath = not W.showPath; W.Render(LA.Result) end end)
  if not W.showPath then return end
  local f = h:AddInputText("##la_page_path", W.PAGE_PATH)
  try(function() f.ReadOnly = true; f.AutoSelectAll = true end)
  try(function() f.ItemWidth = 760 end)
  colored(h:AddText("Your browser cannot be opened from the game: click the path, press Ctrl+C, then Win+R, Ctrl+V, Enter."), GREY)
end

W.dirCells = {}
function W.Render(res)
  if not W.window then return end
  local h = reset("header")
  local c = reset("content")
  W.dirCells = {}
  if not res then
    colored(h:AddText("Waiting for the selected character..."), GREY)
    return
  end
  pageRow(h)
  if res.notCovered then
    colored(h:AddText(("%s: not covered - Loot Advisor covers the origin characters only (Astarion, Gale, Karlach, " ..
      "Lae'zel, Shadowheart, Wyll, the Dark Urge)."):format(tostring(res.name or "?"))), GREY)
    return
  end
  local regName = (LA.Mod.regionName or {})[res.region] or "this region"
  colored(h:AddText(("%s  -  Act %s  -  %s"):format(cname(res.char), tostring(res.act), tostring(res.build and res.build.n))), GOLD)
  local sub = colored(h:AddText(("%s  -  %d items, %d marked on your map  -  %s shows / hides this list"):format(
    regName, #res.rows, #(res.markers or {}), tostring(LA.Settings.Hotkey))), GREY)
  tip(sub, "Build picked: " .. tostring(res.build and res.build.why))

  local leg = c:AddCollapsingHeader("Legend")
  for _, l in ipairs({
    "* = marked on your map (rainbow diamond; the 5 best also get an arrow at the map edge).",
    "(!) = has a warning (theft, a kill, a story choice or a missable step) - hover the item name.",
    "On your map / Enter area / Way marked / Way out marked / Fast travel: where the marker leads you.",
    "Owned: you or the camp chest have it.  Set item: part of a set, not marked.",
    "List only: random loot or a common item.  No fixed spot: reward or wandering NPC.  Other area: no marker from here.",
    "Greyed: Path closed (your story choices), Better on <companion>, If you have it (earlier act).",
    "Coordinates are the map's X / Y (bottom of the minimap).",
  }) do colored(leg:AddText(l), GREY) end

  local rows = displayRows(res)

  -- 1) Next: obtainable now, nearest first
  local nextRows = {}
  for _, r in ipairs(rows) do
    if r.x and (r.s == "marker" or r.enter) and (r.rank == 1 or r.rank == 2) then
      local _, d = W.Direction(r.x, r.z)
      nextRows[#nextRows + 1] = { r = r, d = d or 1e9 }
    end
  end
  table.sort(nextRows, function(a, b) return a.d < b.d end)
  c:AddSeparatorText("Next - nearest items you can get now")
  if #nextRows == 0 then
    colored(c:AddText("Nothing marked from here - see the list below."), GREY)
  else
    local nt = c:AddTable("la_next", 4)
    try(function() nt.Borders = true; nt.RowBg = true end)
    try(function()
      nt:AddColumn("Item", "WidthFixed", 300); nt:AddColumn("Slot", "WidthFixed", 100)
      nt:AddColumn("Direction", "WidthFixed", 110); nt:AddColumn("Where", "WidthStretch")
    end)
    for k, x in ipairs(nextRows) do
      if k > 6 then break end
      local r = x.r
      local row = nt:AddRow()
      nameCell(row, r, nil)
      colored(row:AddCell():AddText(LA.SLOT_NAME[r.group] or r.group), nil)
      local d = row:AddCell():AddText(W.Direction(r.x, r.z) or "-")
      W.dirCells[#W.dirCells + 1] = { t = d, x = r.x, z = r.z }
      local word, full = status(r)
      local area = tostring(r.enter or r.where or ""):match(":%s*(.+)$") or tostring(r.enter or r.where or "")
      local wh
      if r.enter and r.viaWaypoint then wh = "Fast travel to " .. area
      elseif r.enter and r.away then wh = "Way out to " .. area
      elseif r.enter and r.direct then wh = "Enter " .. area
      elseif r.enter then wh = "On the way to " .. area
      else wh = word .. (area ~= "" and (": " .. area) or "") end
      local wt = row:AddCell():AddText(short(wh, 70))
      tip(wt, coords((full or "") .. "\n" .. (r.g or "")))
    end
  end

  -- 2) every recommended item, by slot
  c:AddSeparatorText("All recommended items")
  table.sort(rows, function(a, b)
    local sa, sb = SLOTI[a.slot] or 99, SLOTI[b.slot] or 99
    if a.group == "Rings" then sa = SLOTI.Ring1 end
    if b.group == "Rings" then sb = SLOTI.Ring1 end
    if sa ~= sb then return sa < sb end
    if RORD[a.rank] ~= RORD[b.rank] then return (RORD[a.rank] or 9) < (RORD[b.rank] or 9) end
    return tostring(a.n) < tostring(b.n)
  end)
  local tbl = c:AddTable("la_items", 7)
  try(function() tbl.Borders = true; tbl.RowBg = true end)
  try(function()
    tbl:AddColumn("Slot", "WidthFixed", 80)
    tbl:AddColumn("Item", "WidthFixed", 280)
    tbl:AddColumn("Pick", "WidthFixed", 125)
    tbl:AddColumn("Status", "WidthFixed", 170)
    tbl:AddColumn("Direction", "WidthFixed", 95)
    tbl:AddColumn("Set", "WidthFixed", 150)
    tbl:AddColumn("How to get it", "WidthStretch")
  end)
  local hdr = tbl:AddRow()
  for _, t in ipairs({ "Slot", "Item", "Pick", "Status", "Direction", "Set", "How to get it" }) do
    colored(hdr:AddCell():AddText(t), GOLD)
  end
  for _, r in ipairs(rows) do
    local row = tbl:AddRow()
    local word, full, scol = status(r)
    local grey = (r.s == "closed" or r.s == "better" or r.s == "onlyowned") and GREY or nil
    colored(row:AddCell():AddText(LA.SLOT_NAME[r.group] or r.group), grey)
    nameCell(row, r, grey)
    colored(row:AddCell():AddText((PICK[r.rank] or "-") .. (r.shared and " (shared)" or "")), grey)
    local st = colored(row:AddCell():AddText(word), grey or scol)
    tip(st, full)
    local d = row:AddCell():AddText(r.x and (W.Direction(r.x, r.z) or "-") or "-")
    colored(d, grey)
    if r.x then W.dirCells[#W.dirCells + 1] = { t = d, x = r.x, z = r.z } end
    local sets = table.concat(r.sets or {}, ", ")
    local stc = colored(row:AddCell():AddText(short(sets, 22)), grey)
    if #sets > 22 then tip(stc, sets) end
    local how = coords(r.g or "")
    local ht = colored(row:AddCell():AddText(short(how, 100)), grey)
    if #how > 100 then tip(ht, how) end
  end

  if LA.Settings.Dev and res.durge ~= nil then
    local paths = {}
    for k, v in pairs(res.paths or {}) do paths[#paths + 1] = k .. "=" .. v end
    table.sort(paths)
    colored(c:AddText("[dev] story state: " .. (res.durge and "Dark Urge campaign; " or "") .. table.concat(paths, ", ") -- leak-ok: Dev only
      .. "; region " .. tostring(res.region) .. ", zone " .. tostring(res.playerZone)), GREY)
  end
end

-- refresh the direction cells (called every second while the window is open)
function W.Tick()
  if not (W.window and W.window.Open) then return end
  for _, d in ipairs(W.dirCells) do
    local s = W.Direction(d.x, d.z)
    if s then try(function() d.t.Label = s end) end
  end
end
