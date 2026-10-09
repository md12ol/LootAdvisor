-- (a) Real map pins: Journal marker definitions shipped in the pak
--     (Mods/LootAdvisorSpike/Story/Journal/Markers/*.lsx, same format as vanilla
--     Mods/GustavDev/Story/Journal/Markers/*.lsx) + Osi.ShowMapMarker(character, markerID, 0|1).
--     Vanilla does exactly this for items, e.g. marker "LOW_Elfsong_EmperorSword" (target type Item).
-- (a) Temporary ping on minimap + map: Osi.RequestPing(x, y, z, target, source).
-- (a fallback) In-world purple glow: Osi.PlayLoopEffectAtPosition(fx, x, y, z, scale) -> handle;
--     Osi.StopLoopEffect(handle). Loop-effect handles are invalid after a load (vanilla _GLOBAL_Effects.txt
--     re-creates them on LevelLoaded), so they are re-created here on every level start; nothing is saved.

LAS = LAS or {}
local try = LAS.try

LAS.selected = nil      -- uuid of the character selected on the client
LAS.shownMarkers = {}   -- markerID -> character uuid it was shown for
LAS.fxHandles = {}      -- item key -> loop effect handle

local function host() return try(Osi.GetHostCharacter) end

-- Which markers belong to which character comes from the real data later; the spike shows all test markers.
local function markersFor(_uuid)
  local ids = {}
  for _, t in ipairs(LAS.TEST_ITEMS) do ids[#ids + 1] = t.id end
  return ids
end

function LAS.ShowMarkers(uuid, show)
  local who = uuid or host()
  if not who then return "no character" end
  local n = 0
  for _, id in ipairs(markersFor(who)) do
    local ok, err = pcall(Osi.ShowMapMarker, who, id, show and 1 or 0)
    if ok then n = n + 1; LAS.shownMarkers[id] = show and who or nil
    else Ext.Utils.PrintWarning("LAS ShowMapMarker " .. id .. ": " .. tostring(err)) end
  end
  return string.format("markers %s: %d for %s", show and "on" or "off", n, who)
end

-- Hide everything we showed (call before switching character, and from "markers off").
function LAS.HideAllMarkers()
  for id, who in pairs(LAS.shownMarkers) do pcall(Osi.ShowMapMarker, who, id, 0) end
  LAS.shownMarkers = {}
end

function LAS.Ping(x, y, z)
  local who = LAS.selected or host()
  local ok, err = pcall(Osi.RequestPing, x, y, z, "NULL_00000000-0000-0000-0000-000000000000", who)
  return ok and string.format("ping %.1f %.1f %.1f", x, y, z) or ("ping error " .. tostring(err))
end

function LAS.StopFx()
  for k, h in pairs(LAS.fxHandles) do pcall(Osi.StopLoopEffect, h); LAS.fxHandles[k] = nil end
end

-- rows: { key, x, y, z } in the current level, not carried by the party
function LAS.StartFx(rows)
  LAS.StopFx()
  if not (LAS.Settings and LAS.Settings.WorldFx) then return 0 end
  local n = 0
  for _, r in ipairs(rows) do
    local ok, h = pcall(Osi.PlayLoopEffectAtPosition, LAS.PURPLE_FX, r.x, r.y + 0.3, r.z, 1.0)
    if ok and h then LAS.fxHandles[r.key] = h; n = n + 1 end
  end
  return n
end

-- Client tells us who is selected (Client/Selected.lua).
Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel ~= LAS.CH_SELECTED or not (LAS.Settings and LAS.Settings.Enabled) then return end
  local uuid = e.Payload
  if uuid == LAS.selected then return end
  LAS.HideAllMarkers()
  LAS.selected = uuid
  LAS.ShowMarkers(uuid, true)
  if LAS.RefreshLevelItems then LAS.RefreshLevelItems() end
end)

-- Re-create the in-world effects after every load / level change (handles do not survive a load).
Ext.Osiris.RegisterListener("LevelGameplayStarted", 2, "after", function(_level, _isEditor)
  LAS.LoadSettings()
  if LAS.Settings.Enabled and LAS.RefreshLevelItems then LAS.RefreshLevelItems() end
end)
