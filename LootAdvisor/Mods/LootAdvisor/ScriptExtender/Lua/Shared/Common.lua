-- LootAdvisor: shared helpers (client + server).
-- Settings file (optional): %LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Script Extender\LootAdvisor_settings.json
--   {"Enabled": true, "Hotkey": "F6", "Frames": true, "Markers": true, "Tooltips": true, "Arrows": 5, "Dev": false}
-- "SpoilerNoticeSeen": true once the spoiler warning in the F6 window was dismissed (the window writes it).
-- "MarkerFilter": whose items get map markers: "all" (party, camp, companions who may still join), "party" or
-- "selected" (the F6 window writes it).
-- "Dev": true enables the eval hook (LootAdvisor_client_eval.lua / LootAdvisor_server_eval.lua -> *_eval_out.txt,
-- for testing) and the test command file (LootAdvisor_cmd.txt, Server/Cheats.lua).

LA = LA or {}

LA.SETTINGS_FILE = "LootAdvisor_settings.json"
LA.CH_SEL = "LA_Sel"       -- client -> server: selected character (JSON ctx)
LA.CH_RESULT = "LA_Result" -- server -> client: recommendation result (JSON)
LA.CH_PICK = "LA_Pick"     -- client -> server: a tie pick { id = stats id, c = character key }
-- marker rank offset for markers that are not the selected character's: painted, but never given an off-screen arrow
LA.OTHERS = 1000
LA.FILTERS = { "all", "party", "selected" }
LA.MARK = "\u{25C6}"       -- the diamond used in texts

LA.SLOTS = { "MainHand", "OffHand", "Ranged", "RangedOff", "Helmet", "Cloak", "Breast", "Gloves", "Boots",
             "Amulet", "Ring1", "Ring2", "Elixir" }
LA.SLOT_NAME = { MainHand = "Main hand", OffHand = "Off hand", Ranged = "Ranged", RangedOff = "Ranged off hand",
                 Helmet = "Head", Cloak = "Cloak", Breast = "Armour", Gloves = "Gloves", Boots = "Boots",
                 Amulet = "Amulet", Ring1 = "Ring", Ring2 = "Ring 2", Elixir = "Elixir", Rings = "Rings" }
LA.CHAR_NAME = { astarion = "Astarion", gale = "Gale", karlach = "Karlach", laezel = "Lae'zel",
                 shadowheart = "Shadowheart", wyll = "Wyll", darkurge = "The Dark Urge", halsin = "Halsin",
                 jaheira = "Jaheira", minsc = "Minsc", minthara = "Minthara" }

-- Map marker label: the item names reachable at the marker, one per line, no other words.
-- names: list of item names, or of { n = name, who = {character names} } entries;
-- who: characters this marker is shown for; allWho: [marker] = who lists of every shown marker.
-- A character suffix " (Astarion)" is added only when markers are shown for more than one character.
function LA.MarkerLabel(names, who, allWho)
  local chars = {}
  for _, w in pairs(allWho or {}) do for _, c in ipairs(w) do chars[c] = true end end
  local multi = 0
  for _ in pairs(chars) do multi = multi + 1 end
  local lines, seen = {}, {}
  for _, e in ipairs(names or {}) do
    local n = type(e) == "table" and e.n or e
    local w = type(e) == "table" and e.who or who
    local line = tostring(n or "?")
    if multi > 1 and type(w) == "table" and #w > 0 then line = line .. " (" .. table.concat(w, ", ") .. ")" end
    if not seen[line] then seen[line] = true; lines[#lines + 1] = line end
  end
  return table.concat(lines, "\n")
end

function LA.try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end

function LA.Norm(s)
  local r = tostring(s or ""):lower():gsub("[^%w]", "")
  return r
end

LA.DEFAULTS = { Enabled = true, Hotkey = "F6", Frames = true, Markers = true, Tooltips = true, Arrows = 5, Dev = false,
                UnsafeUiOnOldSE = false, SpoilerNoticeSeen = false, MarkerFilter = "all" }
LA.Settings = {}
for k, v in pairs(LA.DEFAULTS) do LA.Settings[k] = v end
function LA.SaveSettings()
  LA.try(Ext.IO.SaveFile, LA.SETTINGS_FILE, Ext.Json.Stringify(LA.Settings))
end

-- defaults, then the file: a key removed from the file (e.g. ActOverride) goes back to its default
-- (the table itself is kept: other files hold a reference to LA.Settings)
function LA.LoadSettings()
  local raw = LA.try(Ext.IO.LoadFile, LA.SETTINGS_FILE)
  local data = raw and LA.try(Ext.Json.Parse, raw)
  if type(data) ~= "table" then return LA.Settings end
  for k in pairs(LA.Settings) do if LA.DEFAULTS[k] == nil and data[k] == nil then LA.Settings[k] = nil end end
  for k, v in pairs(LA.DEFAULTS) do if data[k] == nil then LA.Settings[k] = v end end
  for k, v in pairs(data) do LA.Settings[k] = v end
  return LA.Settings
end

-- Safe accessors for generated data that is still evolving (fields may be missing or change shape).
function LA.Item(i) return i and LA.Data and LA.Data.items and LA.Data.items[i] end
function LA.ItemAct(it, act)
  local d = it and it.d or ""
  local c = d:sub(act, act)
  return c ~= "" and c or "-"
end
-- list or set in either form {"a","b"} / {a=true} -> lookup table
function LA.AsSet(t)
  local s = {}
  if type(t) == "string" then for w in t:gmatch("[^,%s]+") do s[w] = true end return s end
  if type(t) ~= "table" then return s end
  for k, v in pairs(t) do
    if type(k) == "number" then s[v] = true else s[k] = v and true or nil end
  end
  return s
end

-- Dev eval hook: runs <prefix>_eval.lua once, writes what it prints/returns to <prefix>_eval_out.txt.
function LA.Eval(prefix)
  local src = LA.try(Ext.IO.LoadFile, prefix .. "_eval.lua")
  if type(src) ~= "string" or src:match("^%s*$") then return end
  LA.try(Ext.IO.SaveFile, prefix .. "_eval.lua", "")
  local out = {}
  local env = setmetatable({ print = function(...)
    local t = {}
    for i = 1, select("#", ...) do t[#t + 1] = tostring((select(i, ...))) end
    out[#out + 1] = table.concat(t, "\t")
  end }, { __index = _G })
  local ok, f, err = pcall(Ext.Utils.LoadString, src, env)
  if not ok then f, err = nil, f end
  if f then
    local res = table.pack(pcall(f))
    if not res[1] then out[#out + 1] = "ERROR " .. tostring(res[2])
    elseif res.n > 1 then out[#out + 1] = "=> " .. tostring(res[2]) end
  else
    out[#out + 1] = "COMPILE ERROR " .. tostring(err)
  end
  LA.try(Ext.IO.SaveFile, prefix .. "_eval_out.txt", table.concat(out, "\n"))
end
