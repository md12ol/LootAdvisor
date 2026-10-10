-- LootAdvisor server: gets the selected character from the client, computes the recommendation (Shared/Logic.lua)
-- from the story state (Server/State.lua), shows/hides our journal map markers (Osi.ShowMapMarker, markers shipped
-- in Story/Journal/Markers, generated) for everyone on the roster (party, camp, companions who may still join; the
-- F6 filter narrows it to the party or the selected character), writes their label texts (Ext.Loca,
-- runtime only) and sends the result to the client (frames, tooltips, list window).
-- Tie picks (an item tied exactly between party members) come from the F6 list and are kept in LootAdvisor_picks.json.
-- Note: ShowMapMarker visibility is journal state and probably goes into a save made while markers are shown.

LA = LA or {}
local try = LA.try

local sel = nil            -- { uuid, key, ctx }
function LA.SelectedInfo() return sel end   -- the selected character (for the Sets page state, Server/PageSync.lua)
local shown = {}           -- markerId -> character uuid it is shown for
local labels = {}          -- handle -> text last written
local lastSig, lastRun, lastDev = nil, 0, 0
local REFRESH_MS = 1000      -- check interval; a full refresh (~40 ms) only runs when something changed
local IDLE_REFRESH_MS = 20000 -- or this long after the last one (live positions, anything not evented)
local dirty, lastFull = true, 0
local function markDirty() dirty = true end

-- ---------------------------------------------------------------- tie picks: [stats id] = character key
LA.PICKS_FILE = "LootAdvisor_picks.json"
local picks
function LA.TiePicks()
  if not picks then
    local raw = try(Ext.IO.LoadFile, LA.PICKS_FILE)
    local d = raw and try(Ext.Json.Parse, raw)
    picks = type(d) == "table" and d or {}
  end
  return picks
end
function LA.SetTiePick(id, c)
  if type(id) ~= "string" or type(c) ~= "string" then return end
  LA.TiePicks()[id] = c
  try(Ext.IO.SaveFile, LA.PICKS_FILE, Ext.Json.Stringify(picks))
end

local function hideAll()
  for id, who in pairs(shown) do pcall(Osi.ShowMapMarker, who, id, 0) end
  shown = {}
end

local function applyMarkers(res, who)
  local want = {}
  if LA.Settings.Markers ~= false and who then
    for _, m in ipairs(res.markers or {}) do want[m.m] = m end
  end
  for id, w in pairs(shown) do
    if not want[id] or w ~= who then pcall(Osi.ShowMapMarker, w, id, 0); shown[id] = nil end
  end
  local cname = res.name or LA.CHAR_NAME[res.char] or res.char
  -- label = the items reachable at this marker, one per line, each with everyone it is for; the client draws our
  -- diamond in front of it. Names are added only when markers are shown for more than one character (LA.MarkerLabel).
  local whoOf = {}
  for id, m in pairs(want) do whoOf[id] = m.who or { cname } end
  for id, m in pairs(want) do
    local it = LA.Item(m.i)
    local names = m.entries or (m.entrance and (m.items or {})) or { it and it.n or id }
    local txt = LA.MarkerLabel(names, whoOf[id], whoOf)
    if labels[m.h] ~= txt then labels[m.h] = txt; try(Ext.Loca.UpdateTranslatedString, m.h, txt) end
    -- re-asserted on every refresh: a ShowMapMarker sent while a save is still loading is silently lost
    -- (seen in game: entrance markers only appeared after a second call)
    local ok, err = pcall(Osi.ShowMapMarker, who, id, 1)
    if ok then shown[id] = who else Ext.Utils.PrintWarning("[Loot Advisor] a map marker could not be shown: " .. tostring(err)) end
  end
end

-- An item in another area of this region (an interior stored elsewhere) is marked on the
-- entrance nearest the player instead (Shared/Zones.lua); the list row says "enter <area> here".
local lastZone
function LA.PlayerSpot()
  if not sel then return nil end
  local ok, x, y, z = pcall(Osi.GetPosition, sel.uuid)
  if ok and type(x) == "number" then return x, z end
end

function LA.UseEntrances(res, region)
  local px, pz = LA.PlayerSpot()
  local zp = px and LA.Zones.At(region, px, pz)
  lastZone = zp
  res.playerZone = zp
  if not zp then return end
  local out, byEnt = {}, {}
  local rowOf = {}
  for _, r in ipairs(res.rows) do rowOf[r.i .. "|" .. r.slot] = r end
  for _, m in ipairs(res.markers) do
    local e, _, direct
    if m.zn and m.zn ~= zp then e, _, direct = LA.Zones.Route(region, zp, px, pz, m.zn, m.x, m.z) end
    if e then
      local em = byEnt[e.m]
      if not em then
        em = { m = e.m, h = e.h, entrance = true, rank = m.rank, slot = m.slot, i = m.i, x = e.x, z = e.z,
               rg = m.rg, items = {} }
        byEnt[e.m] = em
        out[#out + 1] = em
      end
      if m.rank < em.rank then em.rank, em.slot, em.i = m.rank, m.slot, m.i end
      local it = LA.Item(m.i)
      local nm = it and it.n or "?"
      local area = (m.rg and m.rg ~= "") and m.rg or "the area"
      local dup = false
      for _, x in ipairs(em.items) do if x == nm then dup = true end end
      if not dup then
        em.items[#em.items + 1] = nm
        em.itemAreas = em.itemAreas or {}
        em.itemAreas[#em.items] = area
      end
      em.areas = em.areas or {}
      local seenA = false
      for _, a in ipairs(em.areas) do if a == area then seenA = true end end
      if not seenA then em.areas[#em.areas + 1] = area end
      em.direct = (em.direct ~= false) and direct and true or false
      local row = rowOf[m.i .. "|" .. m.slot]
      if row then row.enter = area; row.direct = direct and true or false; row.x, row.z = e.x, e.z end
    else
      out[#out + 1] = m
    end
  end
  res.markers = out
  -- items in ANOTHER region -> marker on the way out of this one (exit / waypoint), reached through this
  -- region's entrances when it lies in another area
  for _, r in ipairs(res.rows) do
    if r.away and (r.rank == 1 or r.rank == 2) and r.away.r ~= region then
      local spot, isWaypoint = LA.Zones.WayOut(region, px, pz, r.away.r)
      if spot then
        local tgt = spot
        if spot.zn and spot.zn ~= zp then
          local e = LA.Zones.Route(region, zp, px, pz, spot.zn, spot.x, spot.z)
          if e then tgt = e end
        end
        local em = byEnt[tgt.m]
        if not em then
          em = { m = tgt.m, h = tgt.h, entrance = true, rank = r.rank, slot = r.slot, i = r.i, x = tgt.x, z = tgt.z,
                 items = {}, itemAreas = {}, areas = {}, direct = false }
          byEnt[tgt.m] = em
          res.markers[#res.markers + 1] = em
        end
        if r.rank < em.rank then em.rank, em.slot, em.i = r.rank, r.slot, r.i end
        local regName = (LA.Mod.regionName or {})[r.away.r] or r.away.rg or "another region"
        em.itemAreas = em.itemAreas or {}
        em.items[#em.items + 1] = r.n
        em.itemAreas[#em.items] = regName
        em.direct = false
        em.fast = isWaypoint or nil
        r.enter = regName
        r.direct = false
        r.viaWaypoint = isWaypoint
        r.x, r.z = tgt.x, tgt.z
      end
    end
  end
end

function LA.PlayerZoneChanged(region)
  local px, pz = LA.PlayerSpot()
  local z = px and LA.Zones.At(region, px, pz)
  if z ~= lastZone then lastZone = z; return true end
  return false
end

local function guidOf(s) return type(s) == "string" and (s:match("(%x+%-%x+%-%x+%-%x+%-%x+)$") or s) or nil end

-- the map markers of everyone on the roster, merged with the selected character's (res); the F6 filter picks who
local function everyone(res, state, people)
  local filter = sel.ctx.filter or LA.Settings.MarkerFilter or "all"
  local list = { { key = res.char, name = res.name or LA.CHAR_NAME[res.char] or "?", party = true, selected = true,
                   res = res } }
  local roster = {}
  if filter ~= "selected" then
    for _, p in ipairs(LA.Logic.Roster(people, state)) do
      if guidOf(p.uuid) ~= guidOf(sel.uuid) and (filter == "all" or p.party) then
        if not p.ctx and p.uuid then
          -- a companion who may still join: its live class levels when it is loaded, else its Build Advisor build
          local d = LA.State.Describe(p.uuid)
          p.ctx = d and d.ctx or nil
        end
        local b, _, why = LA.Logic.BuildFor(p)
        if b then
          local key = p.key or ("p_" .. tostring(guidOf(p.uuid) or #list))
          local r = LA.Logic.Recommend(key, p.ctx or {}, state, nil, p.ba, { build = b, why = why })
          LA.UseEntrances(r, state.region)
          list[#list + 1] = { key = key, name = p.name, party = p.party, res = r }
          roster[#roster + 1] = { n = p.name, party = p.party, camp = p.camp, future = p.future, b = b.n }
        end
      end
    end
  end
  res.markers = LA.Logic.MergeMarkers(list, filter)
  res.filter, res.roster = filter, roster
end

-- open and settled ties among the party, for the F6 list (items obtainable in this act or owned)
local function tieRows(state)
  local out, byId = {}, {}
  for _, x in ipairs(LA.Data.items or {}) do byId[x.id] = x end
  for id, t in pairs(state.ties or {}) do
    local it = byId[id]
    if it and (LA.ItemAct(it, state.act) ~= "-" or (state.owned[id] or 0) > 0) then
      out[#out + 1] = { id = id, n = it.n, cands = t.cands, pick = t.pick, by = t.by }
    end
  end
  table.sort(out, function(a, b) return tostring(a.n) < tostring(b.n) end)
  return out
end

function LA.ServerRefresh(force)
  if not sel then return end
  local t0 = Ext.Utils.MonotonicTime()
  local state = LA.State.Snapshot()
  if tonumber(LA.Settings.ActOverride) then state.act = tonumber(LA.Settings.ActOverride) end
  local people = LA.State.People()
  state.tiePicks = LA.TiePicks()
  state.wear = LA.State.Wear(people)
  state.ties = LA.Logic.Ties(state)
  local res
  if (LA.Data.chars or {})[sel.key] then
    res = LA.Logic.Recommend(sel.key, sel.ctx, state, sel.ctx.baPick, sel.ctx.baOrder)
  else
    -- a companion without builds of its own, a Tav or a hireling: the closest build of any origin
    local key = (LA.Mod.companions or {})[sel.key or ""] and sel.key or ("p_" .. tostring(guidOf(sel.uuid)))
    local b, _, why = LA.Logic.BuildFor({ key = key, ctx = sel.ctx, ba = (LA.Mod.baOrigins or {})[sel.key or ""] })
    res = LA.Logic.Recommend(key, sel.ctx, state, nil, nil, { build = b, why = why })
  end
  res.uuid = sel.uuid
  res.paths, res.comp, res.durge = state.paths, state.comp, state.durge
  LA.UseEntrances(res, state.region)
  everyone(res, state, people)
  res.ties = tieRows(state)
  res.ms = Ext.Utils.MonotonicTime() - t0
  LA.LastResult, LA.LastState = res, state
  applyMarkers(res, sel.uuid)
  local payload = Ext.Json.Stringify(res)
  local sig = payload:gsub('"ms":[%d%.]+', "")
  if force or sig ~= lastSig then
    lastSig = sig
    Ext.ServerNet.BroadcastMessage(LA.CH_RESULT, payload)
  end
end

Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel ~= LA.CH_SEL then return end
  local ctx = try(Ext.Json.Parse, e.Payload)
  if type(ctx) ~= "table" then return end
  if sel and sel.uuid ~= ctx.uuid then hideAll() end
  sel = { uuid = ctx.uuid, key = ctx.key, ctx = ctx }
  if LA.Page and LA.Page.Dirty then LA.Page.Dirty() end
  local ok, err = pcall(LA.ServerRefresh, true)
  if not ok then Ext.Utils.PrintError("[Loot Advisor] refresh: " .. tostring(err)) end
end)

-- a tie pick from the F6 list: { id = stats id, c = character key }
Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel ~= LA.CH_PICK then return end
  local p = try(Ext.Json.Parse, e.Payload)
  if type(p) ~= "table" then return end
  LA.SetTiePick(p.id, p.c)
  if LA.Page and LA.Page.Dirty then LA.Page.Dirty() end
  local ok, err = pcall(LA.ServerRefresh, true)
  if not ok then Ext.Utils.PrintError("[Loot Advisor] refresh: " .. tostring(err)) end
end)

Ext.Events.Tick:Subscribe(function()
  local now = Ext.Utils.MonotonicTime()
  if LA.Settings.Dev and now - lastDev > 300 then
    lastDev = now
    pcall(LA.Eval, "LootAdvisor_server")
    if LA.RunCommandFile then pcall(LA.RunCommandFile) end
  end
  if now - lastRun < REFRESH_MS then return end
  lastRun = now
  LA.LoadSettings()
  if not LA.Settings.Enabled then hideAll(); dirty = true; return end
  if not dirty and sel and LA.LastState and LA.PlayerZoneChanged(LA.LastState.region) then dirty = true end
  if not dirty and now - lastFull < IDLE_REFRESH_MS then return end
  dirty, lastFull = false, now
  local ok, err = pcall(LA.ServerRefresh, false)
  if not ok then Ext.Utils.PrintError("[Loot Advisor] refresh: " .. tostring(err)) end
end)

-- inventory / story changes -> recompute on the next check (owned items, closed paths)
pcall(Ext.Osiris.RegisterListener, "AddedTo", 3, "after", markDirty)
pcall(Ext.Osiris.RegisterListener, "RemovedFrom", 2, "after", markDirty)
pcall(Ext.Osiris.RegisterListener, "FlagSet", 3, "after", markDirty)
pcall(Ext.Osiris.RegisterListener, "Died", 1, "after", markDirty)

Ext.Osiris.RegisterListener("LevelGameplayStarted", 2, "after", function()
  shown = {}
  labels = {}
  lastSig = nil
  if sel then pcall(LA.ServerRefresh, true) end
end)
