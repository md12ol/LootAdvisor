-- LootAdvisor client: the character the player has selected (ClientControl), its origin, live class levels and
-- abilities, plus BuildAdvisor's remembered build pick for it (BuildAdvisor_settings.json "Choices", key
-- "<origin>|<name>" normalised exactly like BuildAdvisor's Main.lua) and BuildAdvisor's build order for the origin.
-- Sent to the server (LA_Sel) whenever any of it changes.

LA = LA or {}
local try = LA.try
local NULL = "00000000-0000-0000-0000-000000000000"
local ORIGINS = { astarion = true, gale = true, karlach = true, laezel = true, shadowheart = true, wyll = true,
                  darkurge = true }
-- BuildAdvisor's BA.Origins build order (Mods/BuildAdvisor/ScriptExtender/Lua/Shared/Builds.lua); read live from
-- Mods.BuildAdvisor when that mod is loaded, this copy is the fallback.
local BA_ORDER = { astarion = { "thx", "gloomassassin" }, gale = { "evoker", "stormsorc" },
                   karlach = { "giants", "throwzerker" }, laezel = { "battlemaster", "sorcadin" },
                   shadowheart = { "lightcleric", "stormsorc" }, wyll = { "sorlock", "lockadin" }, darkurge = {} }
local ABIL = { "STR", "DEX", "CON", "INT", "WIS", "CHA" }

local resCache = {}
local function resource(guid, kind)
  if not guid or guid == NULL or guid == "" then return nil end
  local k = kind .. guid
  if resCache[k] == nil then
    local r = try(Ext.StaticData.Get, guid, kind)
    resCache[k] = r and { name = try(function() return r.Name end),
                          display = try(function() return r.DisplayName:Get() end),
                          parent = try(function() return r.ParentGuid end) } or false
  end
  return resCache[k] or nil
end

local function classesOf(e)
  local out = {}
  for _, c in ipairs(try(function() return e.Classes.Classes end) or {}) do
    local cl = resource(c.ClassUUID, "ClassDescription")
    local sub = resource(c.SubClassUUID, "ClassDescription")
    if cl then
      out[#out + 1] = { name = cl.name, sub = sub and (sub.display or sub.name) or nil, level = c.Level }
    end
  end
  return out
end

local function displayName(e)
  return try(function() return e.DisplayName.Name:Get() end)
      or try(function() return Ext.Loca.GetTranslatedString(e.DisplayName.NameKey.Handle.Handle) end)
end

function LA.SelectedEntity()
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ClientControl") or {}) do
    if try(function() return e.Classes ~= nil end) then return e end
  end
end

local baCache, baCacheAt = nil, -1e9
local function baChoices()
  local now = Ext.Utils.MonotonicTime()
  if now - baCacheAt > 5000 then
    baCacheAt = now
    local raw = try(Ext.IO.LoadFile, "BuildAdvisor_settings.json")
    local d = raw and try(Ext.Json.Parse, raw)
    baCache = type(d) == "table" and d.Choices or {}
  end
  return baCache or {}
end

function LA.DescribeSelected()
  local e = LA.SelectedEntity()
  if not e then return nil end
  local ctx = { uuid = try(function() return e.Uuid.EntityUuid end), name = displayName(e) }
  local o = try(function() return e.Origin.Origin end)
  local r = o and resource(o, "Origin")
  ctx.origin = r and r.name or (o and tostring(o)) or ""
  ctx.key = LA.Norm(ctx.origin)
  ctx.covered = ORIGINS[ctx.key] == true
  ctx.classes = classesOf(e)
  ctx.level = try(function() return e.EocLevel.Level end)
  local ab = try(function() return e.Stats.Abilities end)
  ctx.abilities = {}
  if ab then
    local off = ((try(function() return #ab end) or 0) >= 7) and 1 or 0
    for i, k in ipairs(ABIL) do ctx.abilities[k] = try(function() return ab[i + off] end) end
  end
  ctx.baPick = baChoices()[LA.Norm(ctx.origin) .. "|" .. LA.Norm(ctx.name)]
  local live = try(function() return Mods.BuildAdvisor.BA.Origins[ctx.key].builds end)
  ctx.baOrder = (type(live) == "table" and #live > 0) and live or BA_ORDER[ctx.key] or {}
  return ctx, e
end

local lastSig
-- returns true when the selection (or its build-relevant state) changed and was sent to the server
function LA.PollSelection()
  local ctx, e = LA.DescribeSelected()
  if not ctx or not ctx.uuid then return false end
  LA.selectedEntity = e
  local parts = { ctx.uuid, ctx.key, tostring(ctx.baPick) }
  for _, c in ipairs(ctx.classes) do parts[#parts + 1] = tostring(c.name) .. tostring(c.sub) .. tostring(c.level) end
  local sig = table.concat(parts, "|")
  if sig == lastSig then return false end
  lastSig = sig
  LA.selected = ctx
  pcall(Ext.ClientNet.PostMessageToServer, LA.CH_SEL, Ext.Json.Stringify(ctx))
  return true
end

function LA.ResendSelection() lastSig = nil; return LA.PollSelection() end
