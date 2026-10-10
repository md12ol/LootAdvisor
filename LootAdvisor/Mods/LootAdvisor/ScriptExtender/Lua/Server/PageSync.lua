-- LootAdvisor server: the local Sets page. Writes into the Script Extender folder
--   %LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor\
-- 1. once per session: LootAdvisor_text.js  - the item / effect names and descriptions the page shows, read with
--                                              Ext.Loca in the player's game language (loca handles: Shared/ShipManifest.lua)
-- 2. once per game version / page version:   LootAdvisor_art_*.js + LootAdvisor_art_index.js - the game's own textures and
--                                              fonts (Ext.IO.LoadFile(path, "data") reads them from the player's paks),
--                                              base64 in .js files (a file:// page can load scripts, not fetch files)
-- 3. once per page version:                  Sets.html, copied from this mod's pak (Mods/LootAdvisor/Page/Sets.html)
-- 4. live:                                    LootAdvisor_state.js - party, classes, levels, act, region, story state,
--                                              owned items + holders, selected character, tie picks; at most every 2 s on changes,
--                                              plus a heartbeat every 10 s so the page knows the game is running.
-- Nothing of the game ships with the mod: only paths and handles. Settings: "Page": false switches all of this off.

LA = LA or {}
LA.Page = LA.Page or {}
local P = LA.Page
local try = LA.try
local DIR = "LootAdvisor/"
local MIN_GAP_MS, BEAT_MS, CHUNK = 2000, 10000, 4000000

-- ---------------------------------------------------------------- helpers
local B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local T12
local function b64(s)
  if not T12 then
    T12 = {}
    for i = 0, 4095 do
      T12[i] = B64:sub((i >> 6) + 1, (i >> 6) + 1) .. B64:sub((i & 63) + 1, (i & 63) + 1)
    end
  end
  local out, n, len, byte = {}, 0, #s, string.byte
  local full = len - len % 3
  for i = 1, full, 3 do
    local a, b, c = byte(s, i, i + 2)
    local v = (a << 16) | (b << 8) | c
    n = n + 1; out[n] = T12[v >> 12] .. T12[v & 4095]
  end
  local r = len - full
  if r == 1 then
    local v = byte(s, len) << 16
    n = n + 1; out[n] = T12[v >> 12] .. "=="
  elseif r == 2 then
    local a, b = byte(s, len - 1, len)
    local v = (a << 16) | (b << 8)
    n = n + 1; out[n] = T12[v >> 12] .. T12[v & 4095]:sub(1, 1) .. "="
  end
  return table.concat(out)
end
P.b64 = b64

-- JSON with sorted keys (stable output -> a change check by string compare)
local function jstr(s)
  return '"' .. tostring(s):gsub('[%c"\\]', function (c)
    if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" elseif c == "\n" then return "\\n" end
    return string.format("\\u%04x", c:byte())
  end) .. '"'
end
local function enc(v)
  local t = type(v)
  if t == "string" then return jstr(v)
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    if math.type(v) == "integer" then return tostring(v) end
    return string.format("%.3f", v):gsub("%.?0+$", "")
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "table" then
    if v[1] ~= nil or next(v) == nil and getmetatable(v) == P.ARRAY then
      local parts = {}
      for i = 1, #v do parts[i] = enc(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = tostring(k) end
    table.sort(keys)
    local parts = {}
    for _, k in ipairs(keys) do
      local x = v[k]
      if x == nil then x = v[tonumber(k)] end
      parts[#parts + 1] = jstr(k) .. ":" .. enc(x)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return "null"
end
P.ARRAY = {}
P.enc = enc

local function save(name, text) return try(Ext.IO.SaveFile, DIR .. name, text) end
local function load(name) return try(Ext.IO.LoadFile, DIR .. name) end
local function now() return Ext.Utils.MonotonicTime() end
local function epoch() return try(Ext.Timer.ClockEpoch) or 0 end
local function enabled() return LA.Settings.Page ~= false and LA.Ship ~= nil end

-- ---------------------------------------------------------------- 1-3: texts, art, page (once)
local inst = nil   -- install job state

local function gameVersion() return try(Ext.Utils.GameVersion) or "?" end

local function writeText()
  local h = {}
  for _, handle in ipairs(LA.Ship.text or {}) do
    h[handle] = try(Ext.Loca.GetTranslatedString, handle) or ""
  end
  local first = (LA.Ship.text or {})[1]
  local sig = gameVersion() .. "|" .. tostring(LA.Ship.version) .. "|" .. tostring(first and h[first] or "")
  save("LootAdvisor_text.js", "LA_TEXT_CB(" .. enc({ sig = sig, h = h }) .. ");\n")
  return #(LA.Ship.text or {})
end

local function artSig() return gameVersion() .. "|" .. tostring(LA.Ship.artVersion or LA.Ship.version) .. "|" .. #(LA.Ship.art or {}) end

function P.StartInstall(force)
  if not enabled() then return end
  inst = { phase = "text", force = force, t0 = now(), i = 1, chunk = {}, chunkLen = 0, files = {}, missing = {},
           raw = 0, artMs = 0 }
end

local function stepInstall()
  local j = inst
  if j.phase == "text" then
    local n = writeText()
    j.nText = n
    local have = load("art_version.txt")
    if not j.force and have == artSig() and load("LootAdvisor_art_index.js") then
      j.phase = "page"
    else
      j.phase = "art"
      j.artT0 = now()
    end
    return
  end
  if j.phase == "art" then
    local t0 = now()
    local list = LA.Ship.art or {}
    -- ~15 ms of work per tick (base64 in Lua: ~14 MB/s), so loading a save does not stall
    while j.i <= #list and now() - t0 < 15 do
      local path = list[j.i]
      j.i = j.i + 1
      local data = try(Ext.IO.LoadFile, path, "data")
      if type(data) == "string" and #data > 0 then
        j.raw = j.raw + #data
        local s = b64(data)
        j.chunk[#j.chunk + 1] = jstr(path) .. ":\"" .. s .. "\""
        j.chunkLen = j.chunkLen + #s
        if j.chunkLen >= CHUNK then
          local name = ("LootAdvisor_art_%d.js"):format(#j.files + 1)
          save(name, "LA_ART_CB({" .. table.concat(j.chunk, ",") .. "});\n")
          j.files[#j.files + 1] = { name, #j.chunk }
          j.chunk, j.chunkLen = {}, 0
        end
      else
        j.missing[#j.missing + 1] = path
      end
    end
    if j.i > #list then
      if #j.chunk > 0 then
        local name = ("LootAdvisor_art_%d.js"):format(#j.files + 1)
        save(name, "LA_ART_CB({" .. table.concat(j.chunk, ",") .. "});\n")
        j.files[#j.files + 1] = { name, #j.chunk }
        j.chunk, j.chunkLen = {}, 0
      end
      j.artMs = now() - j.artT0
      save("LootAdvisor_art_index.js", "LA_ART_INDEX(" .. enc({ sig = artSig(), files = j.files,
        missing = setmetatable(j.missing, P.ARRAY), raw = j.raw, ms = j.artMs }) .. ");\n")
      save("art_version.txt", artSig())
      Ext.Utils.Print(("[Loot Advisor] Sets page: icons and fonts ready (%d files).")
        :format(#list - #j.missing))
      j.phase = "page"
    end
    return
  end
  if j.phase == "page" then
    local ver = load("page_version.txt")
    if j.force or ver ~= LA.Ship.version or not load("Sets.html") then
      for _, f in ipairs(LA.Ship.page or {}) do
        local s = try(Ext.IO.LoadFile, "Mods/LootAdvisor/Page/" .. f, "data")
        if s then save(f, s) end
      end
      save("page_version.txt", LA.Ship.version)
      Ext.Utils.Print("[Loot Advisor] Sets page written: Script Extender\\LootAdvisor\\Sets.html (open it in your browser)")
    end
    P.lastInstall = { ms = now() - j.t0, text = j.nText, art = j.artMs, raw = j.raw, files = #j.files, missing = #j.missing }
    inst = nil
    P.Dirty()
  end
end

-- ---------------------------------------------------------------- 4: live state
local dirty, lastWrite, lastBeat, seq, lastSig, changedAt = true, -1e9, -1e9, 0, nil, 0
local lastZone, lastRegion
function P.Dirty() dirty = true end

local ORIGINS = { astarion = true, gale = true, karlach = true, laezel = true, shadowheart = true, wyll = true,
                  darkurge = true }
local NULLG = "00000000-0000-0000-0000-000000000000"
local resCache = {}
local function res(guid, kind)
  if not guid or guid == NULLG or guid == "" then return nil end
  local k = kind .. guid
  if resCache[k] == nil then
    local r = try(Ext.StaticData.Get, guid, kind)
    resCache[k] = r and { name = try(function() return r.Name end), display = try(function() return r.DisplayName:Get() end) } or false
  end
  return resCache[k] or nil
end
local function guidOf(s) return type(s) == "string" and (s:match("(%x+%-%x+%-%x+%-%x+%-%x+)$") or s) or nil end

local function charInfo(uuid, inParty)
  local e = try(Ext.Entity.Get, uuid)
  if not e then return nil end
  local name = try(function() return e.DisplayName.Name:Get() end) or ""
  local o = try(function() return e.Origin.Origin end)
  -- the server's Origin component holds the origin NAME ("DarkUrge", "Astarion", "Generic"); the client's a resource id
  local r = o and res(o, "Origin")
  local oname = r and r.name or (type(o) == "string" and not o:match("^%x+%-%x+%-") and o) or ""
  local key = LA.Norm(oname)
  local classes, lvl = {}, try(function() return e.EocLevel.Level end)
  for _, c in ipairs(try(function() return e.Classes.Classes end) or {}) do
    local cl, sub = res(c.ClassUUID, "ClassDescription"), res(c.SubClassUUID, "ClassDescription")
    if cl then classes[#classes + 1] = { name = cl.name, sub = sub and (sub.display or sub.name) or nil, level = c.Level } end
  end
  local out = { uuid = guidOf(uuid), name = name, key = ORIGINS[key] and key or nil, origin = oname ~= "" and oname or nil,
                level = lvl, classes = setmetatable(classes, P.ARRAY), inParty = inParty, dead = try(Osi.IsDead, uuid) == 1 }
  if out.key and LA.Logic and LA.Logic.MatchBuild then
    local b = try(LA.Logic.MatchBuild, out.key, { classes = classes }, nil, nil)
    if b then out.build = b.id end
  end
  return out, e
end

-- every item under an inventory owner (bags included): stats id -> holder names
local wanted
local function walkInv(ent, holder, owned, depth)
  for _, inv in ipairs(try(function() return ent.InventoryOwner.Inventories end) or {}) do
    for _, slot in pairs(try(function() return inv.InventoryContainer.Items end) or {}) do
      local it = slot.Item
      local sid = it and try(function() return it.Data.StatsId end)
      if sid and wanted[sid] then
        local h = owned[sid] or setmetatable({}, P.ARRAY)
        local dup = false
        for _, x in ipairs(h) do if x == holder then dup = true end end
        if not dup then h[#h + 1] = holder end
        owned[sid] = h
      end
      if it and depth < 3 and try(function() return it.InventoryOwner end) then walkInv(it, holder, owned, depth + 1) end
    end
  end
end

local function areaName(region, x, z, zone)
  -- a readable place: the nearest of our marker spots in the same zone (world positions with an area label such as
  -- "Lower City: Guildhall"), shown as "near Guildhall"; the zone id itself is in the state for change detection
  local best, bd
  for _, list in pairs(LA.Mod.markers or {}) do
    for _, m in ipairs(list) do
      if m.r == region and m.rg and m.x and m.z and (zone == nil or m.zn == zone) then
        local d = (m.x - x) ^ 2 + (m.z - z) ^ 2
        if not bd or d < bd then best, bd = m.rg, d end
      end
    end
  end
  if bd and bd < 150 * 150 then
    local short = best:match(":%s*(.+)$") or best:match("%-%s*(.+)$") or best
    return "near " .. short
  end
  return nil
end

function P.BuildState()
  if not wanted then
    wanted = {}
    for _, sid in ipairs(LA.Ship.items or {}) do wanted[sid] = true end
  end
  local S = LA.State
  local region = S.Region()
  local st = { v = 1, mod = LA.Ship.version, game = gameVersion(), region = region,
               regionName = region and (LA.Mod.regionName or {})[region] or region, act = S.ActOf(region) }
  if tonumber(LA.Settings.ActOverride) then st.act = tonumber(LA.Settings.ActOverride) end
  st.paths = try(S.Paths) or {}
  st.comp = try(S.Companions) or {}
  st.durge = try(S.IsDurgeCampaign) and true or false
  -- tie picks: the game's answer per tied item (the one wearing it, else the pick from the F6 list); the page asks
  -- about the open ones itself
  local okT, ties = pcall(function()
    return LA.Logic.Ties({ comp = st.comp, durge = st.durge, tiePicks = LA.TiePicks and LA.TiePicks() or {},
                           wear = S.Wear(S.People()) })
  end)
  st.picks = {}
  if okT then for id, t in pairs(ties) do if t.pick then st.picks[id] = { c = t.pick, by = t.by } end end end
  -- party (active) + camp (team members not in the party)
  local party, owned, inParty = setmetatable({}, P.ARRAY), {}, {}
  for _, u in ipairs(S.Players()) do
    local g = guidOf(u)
    if g and not inParty[g] then
      inParty[g] = true
      local ci, e = charInfo(u, true)
      if ci then party[#party + 1] = ci; walkInv(e, ci.name ~= "" and ci.name or "party", owned, 0) end
    end
  end
  for u in pairs(try(S.Team) or {}) do
    if not inParty[u] and try(Osi.IsCharacter, u) == 1 then
      local ci, e = charInfo(u, false)
      if ci and not ci.dead and #ci.classes > 0 then party[#party + 1] = ci; walkInv(e, (ci.name ~= "" and ci.name or "camp") .. " (camp)", owned, 0) end
    end
  end
  for _, c in ipairs(try(S.CampChests) or {}) do
    local e = try(Ext.Entity.Get, c)
    if e then walkInv(e, "Camp chest", owned, 0) end
  end
  st.party = party
  st.owned = owned
  local sel = LA.SelectedInfo and LA.SelectedInfo()
  if sel then
    local ci = nil
    for _, p in ipairs(party) do if p.uuid == guidOf(sel.uuid) then ci = p end end
    st.selected = { uuid = guidOf(sel.uuid), key = ORIGINS[sel.key or ""] and sel.key or nil,
                    name = ci and ci.name or sel.ctx and sel.ctx.name or nil }
    if ci and ci.key and sel.ctx and LA.Logic then
      local b = try(LA.Logic.MatchBuild, ci.key, sel.ctx, sel.ctx.baPick, sel.ctx.baOrder)
      if b then ci.build = b.id end
    end
    local ok, x, y, z = pcall(Osi.GetPosition, sel.uuid)
    if ok and type(x) == "number" then
      st.zone = region and LA.Zones and LA.Zones.At(region, x, z) or nil
      st.area = areaName(region, x, z, st.zone)
    end
  end
  return st
end

local function writeState(force)
  local t0 = now()
  local ok, st = pcall(P.BuildState)
  if not ok then Ext.Utils.PrintError("[Loot Advisor] page state: " .. tostring(st)); return end
  local sig = enc(st)
  if sig ~= lastSig then lastSig = sig; seq = seq + 1; changedAt = epoch() end
  st.seq, st.t, st.changed, st.ms = seq, epoch(), changedAt, now() - t0
  save("LootAdvisor_state.js", "LA_STATE_CB(" .. enc(st) .. ");\n")
  lastWrite, lastBeat = now(), now()
  P.lastState = st
end

-- ---------------------------------------------------------------- loop
local lastPoll = 0
local loaded = false
if P.tickHandle then pcall(function() Ext.Events.Tick:Unsubscribe(P.tickHandle) end) end   -- hot reload: one loop only
P.tickHandle = Ext.Events.Tick:Subscribe(function()
  if not enabled() or not loaded then return end
  if inst then
    local ok, err = pcall(stepInstall)
    if not ok then Ext.Utils.PrintError("[Loot Advisor] Sets page install: " .. tostring(err)); inst = nil end
    return
  end
  local t = now()
  if t - lastPoll >= 1000 then
    lastPoll = t
    -- area change: the selected character moved into another zone / region
    local sel = LA.SelectedInfo and LA.SelectedInfo()
    if sel then
      local region = LA.State.Region()
      local ok, x, y, z = pcall(Osi.GetPosition, sel.uuid)
      local zn = ok and type(x) == "number" and LA.Zones and LA.Zones.At(region, x, z) or nil
      if zn ~= lastZone or region ~= lastRegion then lastZone, lastRegion = zn, region; dirty = true end
    end
  end
  if dirty and t - lastWrite >= MIN_GAP_MS then
    dirty = false
    writeState()
  elseif t - lastBeat >= BEAT_MS then
    writeState()   -- heartbeat (same seq unless something changed that no event reported)
  end
end)

-- dev / hot reload: start as if a save had just been loaded
function P.Begin(force) loaded = true; dirty = true; P.installedThisSession = true; P.StartInstall(force) end

-- changes that matter to the page
for _, ev in ipairs({ { "AddedTo", 3 }, { "RemovedFrom", 2 }, { "FlagSet", 3 }, { "Died", 1 }, { "LeveledUp", 1 },
                      { "CharacterJoinedParty", 1 }, { "CharacterLeftParty", 1 }, { "Equipped", 2 }, { "Unequipped", 2 } }) do
  pcall(Ext.Osiris.RegisterListener, ev[1], ev[2], "after", function() dirty = true end)
end
Ext.Osiris.RegisterListener("LevelGameplayStarted", 2, "after", function()
  loaded = true
  dirty = true
  if not P.installedThisSession then
    P.installedThisSession = true
    P.StartInstall(false)
  end
end)
