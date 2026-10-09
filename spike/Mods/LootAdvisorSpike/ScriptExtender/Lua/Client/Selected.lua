-- (e) The selected character and its build, client side. Patterns verified in
-- Mods/BuildAdvisor/ScriptExtender/Lua/Client/Detect.lua (ClientControl, Classes, EocLevel, StaticData).
-- Field names from bg3se ExtIdeHelpers.lua: ProgressionLevelUpComponent.LevelUps[].Feat (entity.LevelUp),
-- PassiveContainer.Passives -> entity.Passive.PassiveId, SpellBook.Spells[].Id.Prototype,
-- InventoryOwner.PrimaryInventory -> InventoryContainer.Items[slot].Item -> InventoryMember.EquipmentSlot /
-- Equipable.Slot, Data.StatsId, GameObjectVisual.RootTemplateId. Client replication of LevelUp is UNVERIFIED.

LAS = LAS or {}
local try = LAS.try
local NULL = "00000000-0000-0000-0000-000000000000"

function LAS.SelectedEntity()
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ClientControl") or {}) do
    if try(function() return e.Classes ~= nil end) then return e end
  end
end

local function resName(guid, kind)
  if not guid or guid == NULL then return nil end
  local r = try(Ext.StaticData.Get, guid, kind)
  return r and (try(function() return r.Name end) or guid) or guid
end

function LAS.Describe(e)
  local d = { uuid = try(function() return e.Uuid.EntityUuid end) }
  d.name = try(function() return e.DisplayName.Name:Get() end)
  d.level = try(function() return e.EocLevel.Level end)
  d.abilities = try(function() return e.Stats.Abilities end) -- 7 entries, [1] = None
  d.classes, d.feats, d.passives, d.spells, d.equipped = {}, {}, {}, {}, {}
  for _, c in ipairs(try(function() return e.Classes.Classes end) or {}) do
    d.classes[#d.classes + 1] = { class = resName(c.ClassUUID, "ClassDescription"),
                                  sub = resName(c.SubClassUUID, "ClassDescription"), level = c.Level }
  end
  for _, lu in ipairs(try(function() return e.LevelUp.LevelUps end) or {}) do
    local f = try(function() return lu.Feat end)
    if f and f ~= NULL then d.feats[#d.feats + 1] = resName(f, "Feat") end
  end
  for _, p in ipairs(try(function() return e.PassiveContainer.Passives end) or {}) do
    local id = try(function() return p.Passive.PassiveId end)
    if id then d.passives[#d.passives + 1] = id end
  end
  for _, s in ipairs(try(function() return e.SpellBook.Spells end) or {}) do
    local id = try(function() return s.Id.Prototype end)
    if id then d.spells[#d.spells + 1] = id end
  end
  local inv = try(function() return e.InventoryOwner.PrimaryInventory end)
  for _, slot in pairs(try(function() return inv.InventoryContainer.Items end) or {}) do
    local it = slot.Item
    local eq = try(function() return it.InventoryMember.EquipmentSlot end)
    if eq and eq >= 0 then
      d.equipped[#d.equipped + 1] = { slot = try(function() return it.Equipable.Slot end) or eq,
        stats = try(function() return it.Data.StatsId end),
        template = try(function() return it.GameObjectVisual.RootTemplateId end),
        uuid = try(function() return it.Uuid.EntityUuid end) }
    end
  end
  return d
end

-- Tell the server when the selection changes (legacy NetMessage; v32 has no NetChannel).
local lastSent
function LAS.PollSelection()
  local e = LAS.SelectedEntity()
  local uuid = e and try(function() return e.Uuid.EntityUuid end)
  if uuid and uuid ~= lastSent then
    lastSent = uuid
    LAS.selectedEntity = e
    pcall(Ext.ClientNet.PostMessageToServer, LAS.CH_SELECTED, uuid)
    return true
  end
  return false
end
