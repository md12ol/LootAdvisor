-- (a) Make OUR journal markers purple on the minimap (widget "Minimap", LSWorldMap "WorldMap") and the full map
-- (JournalMap widget, LSWorldMap "WorldMap"). Markers are ls:LSWorldMapMarker visuals whose DataContext has
-- Type ("QuestMarker", ...) and Name (= the marker's DisplayText) - see Public/Game/GUI/Theme/DefaultTheme.Styles.xaml
-- "Map.MarkerDataTemplate" and DefaultShared.Styles.xaml "MapMarkerIconStyle" (icon chosen by Type, never purple).
-- We cannot load images (no Ext.UI.LoadXaml in v32, no string->ImageSource conversion), but we CAN fetch the game's
-- own purple SolidColorBrush ("ProgressionBarColor" #6600FF) via element:Resource(key) and assign it as a local
-- value: a purple disc behind our marker icon. Our markers are recognised by their DisplayText, which starts with
-- LAS.MARK (the text is ours: marker DisplayText handles are filled at runtime by Ext.Loca.UpdateTranslatedString).
-- UNVERIFIED in game: marker visuals being reachable via VisualChild, Border.Background taking effect, recycling.

LAS = LAS or {}
local UI = LAS.UI
local try = LAS.try

local MARKER_TYPE = "ls.LSWorldMapMarker"

local function isOurs(markerEl)
  local d = UI.DC(markerEl)
  local name = d and try(function() return d.Name end)
  return type(name) == "string" and name:sub(1, #LAS.MARK) == LAS.MARK
end

local function decorate(markerEl, brush)
  local icon = UI.FindNamed(markerEl, "Icon", 8)
  local holder = icon and try(function() return icon.VisualParent end)
  -- climb to the first Border/Grid above the icon (template: Border > Button > Image, or Grid > Image)
  for _ = 1, 4 do
    local ty = holder and UI.Type(holder)
    if ty == "Border" or ty == "Grid" then break end
    holder = holder and try(function() return holder.VisualParent end)
  end
  if not holder then return false end
  UI.Set(holder, "Background", brush)
  if UI.Type(holder) == "Border" then
    UI.Set(holder, "CornerRadius", { 40, 40, 40, 40 })
    UI.Set(holder, "BorderBrush", brush)
    UI.Set(holder, "BorderThickness", { 4, 4, 4, 4 })
  end
  return true
end

-- Returns the number of markers recoloured (also counts markers seen, for the probe)
function LAS.PaintMapMarkers()
  local root = UI.Root()
  if not root then return 0, 0 end
  local brush = UI.PurpleBrush(root)
  if not brush then return 0, 0 end
  local seen, painted = 0, 0
  UI.Walk(root, function(el)
    if UI.Type(el) == MARKER_TYPE then
      seen = seen + 1
      if isOurs(el) and decorate(el, brush) then painted = painted + 1 end
      return "skip"
    end
  end, 60000)
  return painted, seen
end
