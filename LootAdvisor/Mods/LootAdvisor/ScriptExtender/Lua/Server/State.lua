-- LootAdvisor server: story / party state the recommendation needs.
--   act + region (Osi.GetRegion), story paths (Osi.GetFlag on the flags in Shared/ModData.lua + Osi.IsDead on
--   global NPCs), companions (team flag GLO_Origin_PartOfTheTeam_<X>, dead flags / IsDead), Dark Urge campaign,
--   items the party owns (party inventories incl. bags + the camp chest), live positions of our marker targets.
-- Read-only: nothing here changes the game or the save.

LA = LA or {}
LA.State = {}
local S = LA.State
local try = LA.try
local NULL = "NULL_00000000-0000-0000-0000-000000000000"

local function flag(name)
  local f = LA.Mod.flags and LA.Mod.flags[name]
  if not f then return false end
  local v = try(Osi.GetFlag, f, NULL)
  if v == nil then
    -- not a global flag: an object flag on a player character (e.g. ORI_DarkUrge_State_KilledIsobel)
    for _, u in ipairs(S.Players()) do if try(Osi.GetFlag, f, u) == 1 then return true end end
    return false
  end
  return v == 1
end
local function dead(npcName)
  local u = LA.Mod.npcs and LA.Mod.npcs[npcName]
  if not u then return false end
  return try(Osi.IsDead, u) == 1
end

function S.Host() return try(Osi.GetHostCharacter) end

function S.Region()
  local h = S.Host()
  return h and try(Osi.GetRegion, h) or nil
end

function S.ActOf(region)
  if not region then return 1 end
  local a = LA.Mod.regionAct and LA.Mod.regionAct[region]
  if a then return a end
  local p = region:sub(1, 3):upper()
  if p == "WLD" or p == "CRE" or p == "TUT" then return 1 elseif p == "SCL" or p == "INT" then return 2 end
  return 3
end

function S.Paths()
  local out = {}
  for name, p in pairs(LA.Mod.paths or {}) do
    local yes, no = false, false
    for _, f in ipairs(p.yes or {}) do if flag(f) then yes = true end end
    for _, n in ipairs(p.dead or {}) do if dead(n) then yes = true end end
    for _, f in ipairs(p.no or {}) do if flag(f) then no = true end end
    for _, n in ipairs(p.deadno or {}) do if dead(n) then no = true end end
    if yes then out[name] = "yes" elseif no then out[name] = "no" end
  end
  return out
end

local function guidOf(s) return type(s) == "string" and (s:match("(%x+%-%x+%-%x+%-%x+%-%x+)$") or s) or nil end

-- uuid set of everyone in the player's team (party + camp): Osiris DB_PartOfTheTeam (verified in game: a
-- Lae'zel who left the party is not in it although she is alive - she left; DB_InCamp lists camp members)
function S.Team()
  local out = {}
  for _, r in ipairs(try(function() return Osi.DB_PartOfTheTeam:Get(nil) end) or {}) do
    local u = guidOf(r[1])
    if u then out[u] = true end
  end
  return out
end

-- party = in the ACTIVE party (S.Players(), the same list PageSync uses), not just in the team (camp counts as team)
function S.Companions()
  local out = {}
  local team = S.Team()
  local inParty = {}
  -- keyed by guid AND by the name part ("S_Player_Astarion_<guid>" -> "S_Player_Astarion"), as LA.Mod.companions
  -- names its npcs by name
  for _, u in ipairs(S.Players()) do
    if type(u) == "string" then
      inParty[u] = true
      local g = guidOf(u); if g then inParty[g] = true end
      local nm = u:match("^(.-)_%x+%-%x+%-%x+%-%x+%-%x+$"); if nm then inParty[nm] = true end
    end
  end
  for name, c in pairs(LA.Mod.companions or {}) do
    local d = false
    for _, f in ipairs(c.dead or {}) do if flag(f) then d = true end end
    if c.npc and c.npc ~= "" and try(Osi.IsDead, c.npc) == 1 then d = true end
    local inTeam = (c.npc ~= "" and team[c.npc]) or (c.team ~= "" and flag(c.team)) or false
    -- gone for good: a "left / killed" story flag while not in the team (never joins again, gets no markers)
    local gone = false
    if not inTeam then for _, f in ipairs(c.gone or {}) do if flag(f) then gone = true end end end
    out[name] = { team = inTeam and true or false, party = (c.npc ~= "" and inParty[c.npc]) or false, dead = d,
                  gone = gone }
  end
  return out
end

-- Every player character (party + camp): DB_Players, falling back to the party list.
function S.Players()
  local out, seen = {}, {}
  local rows = try(function() return Osi.DB_Players:Get(nil) end) or {}
  for _, r in ipairs(rows) do
    local u = r[1]
    if u and not seen[u] then seen[u] = true; out[#out + 1] = u end
  end
  return out
end

function S.IsDurgeCampaign()
  if flag("GLO_Origin_PartOfTheTeam_DarkUrge") then return true end
  for _, u in ipairs(S.Players()) do
    local e = try(Ext.Entity.Get, u)
    local o = e and try(function() return e.Origin.Origin end)
    if o then
      local res = try(Ext.StaticData.Get, o, "Origin")
      local nm = res and try(function() return res.Name end) or tostring(o)
      if LA.Norm(nm) == "darkurge" then return true end
    end
  end
  return false
end

-- Camp chests: DB_Camp_UserCampChest lists one chest per user, but the party's items can sit in other camp chest
-- instances (verified in game: one save's Traveller's Chest is CONT_PlayerCampChest_B, while the DB names _A).
-- So every placed instance of the camp chest templates counts (CONT_PlayerCampChest_A..D, all children of one parent
-- template); found once per level by an entity scan, plus whatever the DB names.
local CHEST_TEMPLATES = { ["96eab9d1-74b1-42f7-b1ad-061a9fcea8c4"] = true, ["f68b5862-887c-4adf-b9f8-bb29e4d73b0f"] = true,
                          ["b5de2260-8e6b-4c2f-91eb-6f3133682a2f"] = true, ["9b293d36-29f0-460c-bc81-2bdd4610a478"] = true }
local chestCache, chestRegion
function S.CampChests()
  local region = S.Region()
  if chestCache and chestRegion == region then return chestCache end
  local out, seen = {}, {}
  local function add(u) if u and not seen[u] then seen[u] = true; out[#out + 1] = u end end
  for _, r in ipairs(try(function() return Osi.DB_Camp_UserCampChest:Get(nil, nil) end) or {}) do
    for _, v in ipairs(r) do
      if type(v) == "string" then add(v:match("(%x+%-%x+%-%x+%-%x+%-%x+)$")) end
    end
  end
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerItem") or {}) do
    local tpl = try(function() return e.GameObjectVisual.RootTemplateId end)
    if tpl and CHEST_TEMPLATES[tpl] then add(try(function() return e.Uuid.EntityUuid end)) end
  end
  chestCache, chestRegion = out, region
  return out
end

-- stats id -> number of copies the party owns (party inventories incl. bags, camp chest). Lazy: only the items the
-- recommendation asks about are checked (a few dozen per refresh instead of all items).
local byId
function S.Owned()
  if not byId then
    byId = {}
    for _, it in ipairs(LA.Data.items or {}) do byId[it.id] = it end
  end
  local host = S.Host()
  local chests, camp
  return setmetatable({}, { __index = function(t, id)
    local it = byId[id]
    local n = 0
    if it and host then
      if not chests then
        chests = S.CampChests()
        -- companions in camp (in the team, not in the active party): their inventories count too
        camp = {}
        local inParty = {}
        for _, u in ipairs(S.Players()) do inParty[guidOf(u)] = true end
        for u in pairs(S.Team()) do
          if not inParty[u] and try(Osi.IsCharacter, u) == 1 then camp[#camp + 1] = u end
        end
      end
      for _, tp in ipairs(it.t or {}) do
        n = n + (try(Osi.TemplateIsInPartyInventory, tp, host, 0) or 0)
        if n > 0 then break end
        for _, c in ipairs(chests) do n = n + (try(Osi.TemplateIsInInventory, tp, c) or 0) end
        for _, c in ipairs(camp) do n = n + (try(Osi.TemplateIsInInventory, tp, c) or 0) end
        if n > 0 then break end
      end
    end
    rawset(t, id, n)
    return n
  end })
end

local function pos(u)
  local ok, x, y, z = pcall(Osi.GetPosition, u)
  if ok and type(x) == "number" then return { x = x, y = y, z = z } end
end

-- live positions of our marker targets in this region (objects of other levels are not loaded -> static data)
function S.MarkerPositions(region)
  local out = {}
  for _, list in pairs(LA.Mod.markers or {}) do
    for _, m in ipairs(list) do
      if m.r == region then
        local p = pos(m.t)
        if p then out[m.m] = p end
      end
    end
  end
  return out
end

-- ---------------------------------------------------------------- everyone (markers for the whole roster)
local NULLG = "00000000-0000-0000-0000-000000000000"
local resCache = {}
local function resource(guid, kind)
  if not guid or guid == NULLG or guid == "" then return nil end
  local k = kind .. guid
  if resCache[k] == nil then
    local r = try(Ext.StaticData.Get, guid, kind)
    resCache[k] = r and { name = try(function() return r.Name end),
                          display = try(function() return r.DisplayName:Get() end) } or false
  end
  return resCache[k] or nil
end
local ABIL = { "STR", "DEX", "CON", "INT", "WIS", "CHA" }

-- key (origin / companion: "astarion", "halsin"; nil for a Tav or hireling), name, class levels and abilities of a
-- loaded character; nil when the entity is not loaded (a companion in another level)
function S.Describe(uuid)
  local e = try(Ext.Entity.Get, uuid)
  if not e then return nil end
  local classes = {}
  for _, c in ipairs(try(function() return e.Classes.Classes end) or {}) do
    local cl, sub = resource(c.ClassUUID, "ClassDescription"), resource(c.SubClassUUID, "ClassDescription")
    if cl then classes[#classes + 1] = { name = cl.name, sub = sub and (sub.display or sub.name) or nil, level = c.Level } end
  end
  local abilities = {}
  local ab = try(function() return e.Stats.Abilities end)
  if ab then
    local off = ((try(function() return #ab end) or 0) >= 7) and 1 or 0
    for i, k in ipairs(ABIL) do abilities[k] = try(function() return ab[i + off] end) end
  end
  -- the server's Origin component holds the origin name ("Astarion", "DarkUrge", "Generic")
  local o = try(function() return e.Origin.Origin end)
  local r = o and resource(o, "Origin")
  local oname = r and r.name or (type(o) == "string" and not o:match("^%x+%-%x+%-") and o) or ""
  local key = LA.Norm(oname)
  if not ((LA.Data.chars or {})[key] or (LA.Mod.companions or {})[key]) then key = nil end
  local name = try(function() return e.DisplayName.Name:Get() end)
  return { key = key, name = (name and name ~= "") and name or (key and LA.CHAR_NAME[key]) or "?",
           ctx = { classes = classes, abilities = abilities, name = name } }
end

-- party (every player's characters) + camp, as L.Roster wants them
function S.People()
  local out, seen = {}, {}
  for _, u in ipairs(S.Players()) do
    local g = guidOf(u)
    if g and not seen[g] then
      seen[g] = true
      local d = S.Describe(u) or { name = "?", ctx = {} }
      out[#out + 1] = { uuid = g, key = d.key, name = d.name, inParty = true, ctx = d.ctx }
    end
  end
  for u in pairs(S.Team()) do
    if not seen[u] and try(Osi.IsCharacter, u) == 1 then
      seen[u] = true
      local d = S.Describe(u)
      if d then out[#out + 1] = { uuid = u, key = d.key, name = d.name, inParty = false, ctx = d.ctx } end
    end
  end
  return out
end

-- tied items someone in the party is wearing: [stats id] = that character's key (the wearer keeps a tied item)
local EQUIP_SLOTS = { "Helmet", "Breast", "Cloak", "MeleeMainHand", "MeleeOffHand", "RangedMainHand", "RangedOffHand",
                      "Ring", "Ring2", "Boots", "Gloves", "Amulet" }
local tiedIds
function S.Wear(people)
  if not tiedIds then
    tiedIds = {}
    for _, it in ipairs(LA.Data.items or {}) do if type(it.ot) == "table" and #it.ot > 0 then tiedIds[it.id] = true end end
  end
  local out = {}
  for _, p in ipairs(people or {}) do
    if p.inParty and p.key then
      for _, slot in ipairs(EQUIP_SLOTS) do
        local item = try(Osi.GetEquippedItem, p.uuid, slot)
        local sid = item and try(Osi.GetStatString, item)
        if sid and tiedIds[sid] then out[sid] = p.key end
      end
    end
  end
  return out
end

function S.Snapshot()
  local region = S.Region()
  return { region = region, act = S.ActOf(region), paths = S.Paths(), comp = S.Companions(),
           durge = S.IsDurgeCampaign(), owned = S.Owned(), markerPos = S.MarkerPositions(region) }
end
