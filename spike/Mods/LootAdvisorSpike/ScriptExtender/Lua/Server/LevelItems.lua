-- (e) Items of the loaded level with live positions (server).
--     Ext.Entity.GetAllEntitiesWithComponent("ServerItem") -> entity.Uuid.EntityUuid,
--     entity.GameObjectVisual.RootTemplateId (template), entity.Data.StatsId (stats entry),
--     Osi.GetPosition(uuid) / entity.Transform.Transform.Translate, Osi.IsInInventory / Osi.GetInventoryOwner.
--     Same pattern as Mods/Autopilot/ScriptExtender/Lua/Server/Scan.lua (dumpAll), which works in this setup.
--     Only the CURRENT level's items exist as entities; other levels come from the static data
--     (LootAdvisor/data/cache/level_items_index.json) and from the journal markers, which the game handles per level.

LAS = LAS or {}
local try = LAS.try

local function guidOf(s) -- "Name_<guid>" (Osi.GetTemplate) or "<guid>" -> "<guid>"
  if type(s) ~= "string" then return nil end
  return s:match("(%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x)$")
end

local function pos(uuid)
  local ok, x, y, z = pcall(Osi.GetPosition, uuid) -- try() would drop y and z
  if ok and type(x) == "number" then return x, y, z end
end

local function isParty(uuid) return try(Osi.IsPartyMember, uuid, 1) == 1 end

-- wanted: { [instanceGuid or templateGuid] = info }; returns rows for every match in the loaded level
function LAS.ScanLevel(wanted)
  local rows = {}
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerItem") or {}) do
    local uuid = try(function() return e.Uuid.EntityUuid end)
    local tpl = try(function() return e.GameObjectVisual.RootTemplateId end) or guidOf(try(Osi.GetTemplate, uuid))
    local info = uuid and (wanted[uuid] or (tpl and wanted[tpl]))
    if info then
      local row = { key = info.id, uuid = uuid, template = tpl, name = info.name, why = info.why,
                    stats = try(function() return e.Data.StatsId end) }
      local holder = try(Osi.IsInInventory, uuid) == 1 and try(Osi.GetInventoryOwner, uuid) or nil
      row.carriedByParty = holder ~= nil and isParty(holder)
      row.holder = holder
      row.x, row.y, row.z = pos(holder or uuid) -- inside a chest / on an NPC: point at the holder
      if row.x then rows[#rows + 1] = row end
    end
  end
  return rows
end

function LAS.RefreshLevelItems()
  local wanted = {}
  for _, t in ipairs(LAS.TEST_ITEMS) do wanted[t.item] = t; wanted[t.template] = t end
  local rows = LAS.ScanLevel(wanted)
  local free = {}
  for _, r in ipairs(rows) do if not r.carriedByParty then free[#free + 1] = r end end
  local nfx = LAS.StartFx(free)
  Ext.ServerNet.BroadcastMessage(LAS.CH_ITEMS, Ext.Json.Stringify(rows))
  return string.format("scan: %d matches, %d not carried, %d effects", #rows, #free, nfx)
end
