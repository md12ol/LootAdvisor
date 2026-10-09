-- (b) + (d) Purple mark on inventory / camp-chest / container cells, items AND bags.
-- Every inventory cell is  ListBoxItem > LSButton > ls:LSEntityObject x:Name="invCellBase"
--   DataContext="{Binding Object}" (an ls:VMItem) EntityRef="{Binding EntityHandle}" Background="{TemplateBinding ...}"
-- (Public/Game/GUI/Library/CharacterSheetTemplates_k.xaml, style SingleClickBaseInvContainerItemStyle), and the
-- item visual inside is DataTemplate Template.Item / Template.ItemContainer (bags) / Template.ItemEquipment
-- (Public/Game/GUI/Library/DataTemplates.xaml) whose root Grid has a 2-6 % margin around the icon.
-- Approach: give invCellBase a LOCAL Background = the game's purple brush -> a purple frame around the icon.
-- Local values beat template bindings/style triggers in WPF/Noesis precedence. Cells are recycled when the list
-- scrolls/sorts, so every pass re-checks every visible cell and restores the ones that are no longer ours.
-- Nothing here touches game state; UI-only, never saved.
-- UNVERIFIED in game: what VMItem.EntityHandle reads back as in Lua (number vs entity), whether the frame is visible.

LAS = LAS or {}
local UI = LAS.UI
local try = LAS.try

LAS.badgeSet = LAS.badgeSet or {} -- [instance uuid or template guid] = true

local function entityOf(vm)
  local h = try(function() return vm.EntityHandle end)
  if type(h) == "number" then
    local eh = try(Ext.Utils.IntegerToHandle, h)
    return eh and try(Ext.Entity.Get, eh)
  end
  return h -- userdata entity (or nil)
end

local function wanted(vm)
  local e = entityOf(vm)
  if e then
    local uuid = try(function() return e.Uuid.EntityUuid end)
    local tpl = try(function() return e.GameObjectVisual.RootTemplateId end)
    if (uuid and LAS.badgeSet[uuid]) or (tpl and LAS.badgeSet[tpl]) then return true end
  end
  return false
end

function LAS.PaintInventory()
  local root = UI.Root()
  if not root then return 0, 0 end
  local brush = UI.PurpleBrush(root)
  local cells, painted = 0, 0
  UI.Walk(root, function(el)
    if UI.Name(el) == "invCellBase" then
      cells = cells + 1
      local vm = UI.DC(el)
      if vm and brush and wanted(vm) then
        if UI.Set(el, "Background", brush) then painted = painted + 1 end
      else
        UI.Restore(el, "Background") -- recycled cell that showed one of our items before
      end
      return "skip"
    end
  end, 60000)
  return painted, cells
end
