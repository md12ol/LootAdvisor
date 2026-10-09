-- LootAdvisor spike: shared constants (client + server). Test data only.
-- Everything in this mod is dormant unless "Enabled": true is set in
-- %LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisorSpike_settings.json

LAS = LAS or {}

LAS.SETTINGS_FILE = "LootAdvisorSpike_settings.json"
LAS.CMD_FILE      = "LootAdvisorSpike_cmd.txt"     -- server commands (one line), see Server/Cheats.lua
LAS.RESULT_FILE   = "LootAdvisorSpike_result.txt"  -- "<seq>|<result>"
LAS.PROBE_FILE    = "LootAdvisorSpike_probe.txt"   -- client discovery dump, see Client/Probe.lua

-- Legacy NetMessage channels (v32 has no Ext.Net.CreateChannel / NetChannel; that is v33+)
LAS.CH_SELECTED = "LAS_Selected" -- client -> server: selected character uuid
LAS.CH_ITEMS    = "LAS_Items"    -- server -> client: recommended items in the current level with live positions

LAS.MARK = "\u{25C6}" -- the symbol ("◆"); whether BG3's fonts have the glyph must be tested (fallback "*")
LAS.PURPLE = { 0.62, 0.25, 1.0, 1.0 } -- IMGUI RGBA

-- Purple game resources that already exist (no file overrides needed):
--  * Noesis SolidColorBrush keys (Public/Game/GUI/Theme/DefaultTheme.Colours.xaml):
LAS.PURPLE_BRUSH_KEYS = { "ProgressionBarColor", "DamageType.Thunder" } -- #6600FF, #7e46ae
--  * Effect resource (Public/Shared/Content/Assets/Effects/Effects/[PAK]_LightSources/_merged.lsf):
LAS.PURPLE_FX = "e608954c-3dd0-f914-db91-f040a557678a" -- VFX_LightSources_GEN_Gem_Glowing_A_01_Purple

-- Test items (instance MapKey = level placement GUID from data/cache/level_items_index.json).
-- id = MarkerID of the journal marker in Story/Journal/Markers; markerHandle = its DisplayText handle (new, ours;
-- the text is written at runtime with Ext.Loca.UpdateTranslatedString so it can name the selected character).
LAS.TEST_ITEMS = {
  { id = "LAS_Test_EmperorSword", item = "5e46d5b5-0a24-4e01-adc9-96914091cdbe", level = "CTY_Main_A",
    template = "777cb3d5-0689-4cfd-9719-b460897cb9e6", name = "Sword of the Emperor",
    markerHandle = "h9d449e77g92a5g44f8g893eg9e8418117600",
    pos = { -733.326, 1.207, 588.646 }, why = "Test: best longsword for a Strength build" },
  { id = "LAS_Test_PhalarAluve", item = "cc16c1cb-d355-47df-820a-33a83c42234b", level = "WLD_Main_A",
    template = "6d0d3206-50b5-48ed-af92-a146ed6b98f2", name = "Phalar Aluve",
    markerHandle = "heb5c33a4g63efg4452ga7bbg0d9a8e1b2389",
    pos = { 116.2, 55.2, -190.5 }, why = "Test: Bard/Dex melee, free Shriek/Sing" },
}

function LAS.try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end

function LAS.LoadSettings()
  LAS.Settings = { Enabled = false, PurpleMap = true, Badges = true, Tooltips = true, WorldFx = true, Overlay = true }
  local raw = LAS.try(Ext.IO.LoadFile, LAS.SETTINGS_FILE)
  local data = raw and LAS.try(Ext.Json.Parse, raw)
  if type(data) == "table" then for k, v in pairs(data) do LAS.Settings[k] = v end end
  return LAS.Settings
end

-- Test-only eval: runs the Lua in <side>_eval.lua (Script Extender folder) once and writes what it returns or
-- prints to <side>_eval_out.txt. side = "LootAdvisorSpike_client" / "LootAdvisorSpike_server". Spike only.
function LAS.Eval(side)
  local src = LAS.try(Ext.IO.LoadFile, side .. "_eval.lua")
  if type(src) ~= "string" or src:match("^%s*$") then return end
  LAS.try(Ext.IO.SaveFile, side .. "_eval.lua", "")
  local out = {}
  local env = setmetatable({ print = function(...)
    local t = {}
    for i = 1, select("#", ...) do t[#t + 1] = tostring((select(i, ...))) end
    out[#out + 1] = table.concat(t, "\t")
  end }, { __index = _G })
  -- SE replaces load with Ext.Utils.LoadString(code [, globalsTable]) (SandboxStartup.lua)
  local ok, f, err = pcall(Ext.Utils.LoadString, src, env)
  if not ok then f, err = nil, f end
  if f then
    local res = table.pack(pcall(f))
    if not res[1] then out[#out + 1] = "ERROR " .. tostring(res[2])
    elseif res.n > 1 then out[#out + 1] = "=> " .. tostring(res[2]) end
  else
    out[#out + 1] = "COMPILE ERROR " .. tostring(err)
  end
  LAS.try(Ext.IO.SaveFile, side .. "_eval_out.txt", table.concat(out, "\n"))
end
