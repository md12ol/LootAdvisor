-- Discovery dump for the first in-game session (client). Write "probe" to LootAdvisorSpike_ccmd.txt;
-- the dump goes to LootAdvisorSpike_probe.txt. Answers the open questions of FEASIBILITY.md:
--  * SE version / whether Ext.UI.Defer exists
--  * widget names under ContentRoot (Minimap, JournalMap, CharacterPanel/Inventory, Container, ...)
--  * VMItem properties on inventory cells and what EntityHandle reads back as
--  * LSWorldMapMarker DataContext properties (Type, Name, ...) and how many markers exist
--  * entities with the MapMarkerStyle component (the "SpecialItem" map markers?)
--  * the purple brush resource, the selected character description, a test template's Description handle

LAS = LAS or {}
local UI = LAS.UI
local try = LAS.try

local function props(obj)
  local out = {}
  local all = try(function() return obj:GetAllProperties() end)
  if type(all) == "table" then
    for k, v in pairs(all) do out[#out + 1] = tostring(k) .. "=" .. tostring(v):sub(1, 80) end
  end
  table.sort(out)
  return table.concat(out, "; ")
end

function LAS.Probe()
  local o = {}
  local function add(s) o[#o + 1] = s end
  add("SE version: " .. tostring(try(Ext.Utils.Version)) .. "  Defer: " .. tostring(Ext.UI.Defer ~= nil))
  local root = UI.Root()
  local content = root and try(function() return root:Find("ContentRoot") end)
  if content then
    local names = {}
    for i = 1, (try(function() return content.VisualChildrenCount end) or 0) do
      local c = try(function() return content:VisualChild(i) end)
      names[#names + 1] = tostring(c and UI.Name(c)) .. ":" .. tostring(c and UI.Type(c))
    end
    add("ContentRoot children: " .. table.concat(names, ", "))
  end
  local cells, markers = 0, 0
  UI.Walk(root, function(el)
    local nm, ty = UI.Name(el), UI.Type(el)
    if nm == "invCellBase" then
      cells = cells + 1
      if cells <= 3 then
        local vm = UI.DC(el)
        local h = vm and try(function() return vm.EntityHandle end)
        add(("cell %d: vm=%s EntityHandle type=%s value=%s"):format(cells, tostring(vm and UI.Type(vm)), type(h), tostring(h)))
        add("  vm props: " .. props(vm))
        add("  cell props: " .. props(el))
      end
      return "skip"
    elseif ty == "ls.LSWorldMapMarker" then
      markers = markers + 1
      if markers <= 5 then
        local d = UI.DC(el)
        add(("marker %d: dc=%s Type=%s Name=%s"):format(markers, tostring(d and UI.Type(d)),
          tostring(d and try(function() return d.Type end)), tostring(d and try(function() return d.Name end))))
        if markers == 1 then add("  marker dc props: " .. props(d)) end
      end
      return "skip"
    end
  end, 80000)
  add(("cells=%d markers=%d"):format(cells, markers))
  local b = root and UI.PurpleBrush(root)
  add("purple brush: " .. tostring(b and UI.Type(b)) .. " " .. (b and props(b) or ""))
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "MapMarkerStyle") or {}) do
    add("MapMarkerStyle entity: " .. tostring(try(function() return e.Uuid.EntityUuid end)) .. " style="
      .. tostring(try(function() return e.MapMarkerStyle.Style end)))
  end
  local me = LAS.SelectedEntity()
  if me then add("selected: " .. tostring(try(Ext.Json.Stringify, LAS.Describe(me)))) end
  for _, t in ipairs(LAS.TEST_ITEMS) do
    local tm = try(Ext.Template.GetRootTemplate, t.template)
    add(("template %s: Description handle=%s Icon=%s"):format(t.name,
      tostring(tm and try(function() return tm.Description.Handle.Handle end)), tostring(tm and try(function() return tm.Icon end))))
  end
  try(Ext.IO.SaveFile, LAS.PROBE_FILE, table.concat(o, "\n"))
  return #o
end
