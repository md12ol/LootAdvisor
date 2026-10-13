-- Gauntlet window (client side, Script Extender IMGUI). Dev/test only: it is not part of the Loot Advisor pak; the
-- test mod (tools/gauntlet/testmod) or tools/gauntlet/engine.py load loads it into a running game. Hotkey F9 toggles
-- it. On top, the test popup (gauntlet_test.lua on the server): mode Manual / Automatic, Start, Stop, the status and
-- the last result. Below, folded, the free runs: pick build, set, act and scenario from the catalogue and Start sets
-- up the arena on the host character and hands its turns to you.

GAUNTLET_UI = GAUNTLET_UI or {}
local U = GAUNTLET_UI
U.HOTKEY = U.HOTKEY or "F9"

local function try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end

local SCENARIOS = { "boss", "pack", "defence", "longday" }
local SCN_TEXT = { boss = "Boss (1 target)", pack = "Pack (4 targets)", defence = "Defence (attackers)",
  longday = "Long day (4 fights, short rests)" }
local MODE_IDS = { "manual", "automatic" }
local MODE_TEXT = { manual = "Manual (you play the turns)", automatic = "Automatic (the plan plays the turns)" }

-- The game's own panel look: dark brown panels, gold text and frames.
U.COLORS = {
  WindowBg = { 0.075, 0.06, 0.05, 0.96 }, ChildBg = { 0.10, 0.08, 0.06, 0.9 }, Border = { 0.55, 0.43, 0.24, 0.9 },
  TitleBg = { 0.16, 0.12, 0.08, 1 }, TitleBgActive = { 0.24, 0.18, 0.10, 1 }, Text = { 0.92, 0.86, 0.72, 1 },
  FrameBg = { 0.17, 0.13, 0.09, 1 }, FrameBgHovered = { 0.26, 0.20, 0.12, 1 }, Button = { 0.30, 0.21, 0.11, 1 },
  ButtonHovered = { 0.45, 0.32, 0.15, 1 }, ButtonActive = { 0.58, 0.42, 0.18, 1 }, Header = { 0.24, 0.18, 0.10, 1 },
  HeaderHovered = { 0.36, 0.27, 0.14, 1 }, Separator = { 0.55, 0.43, 0.24, 0.6 },
}
U.GOLD, U.RED, U.GREEN, U.GREY = { 0.86, 0.69, 0.36, 1 }, { 0.90, 0.40, 0.32, 1 }, { 0.55, 0.80, 0.45, 1 },
  { 0.65, 0.60, 0.52, 1 }
U.STATUS_COLOR = { Ready = U.GREY, ["Setting up"] = U.GOLD, Fighting = U.GREEN, Result = U.GOLD,
  ["Setup failed"] = U.RED }

local function style(w)
  for k, c in pairs(U.COLORS) do pcall(function() w:SetColor(k, c) end) end
  pcall(function() w:SetStyle("WindowRounding", 4) end)
  pcall(function() w:SetStyle("FrameRounding", 3) end)
  pcall(function() w:SetStyle("WindowBorderSize", 1) end)
end
local function colored(t, c) if t and c then pcall(function() t:SetColor("Text", c) end) end return t end

local function catalog()
  local raw = try(Ext.IO.LoadFile, "LootAdvisor_gauntlet_catalog.json")
  return raw and try(Ext.Json.Parse, raw) or nil
end

local function sortedBuilds(C)
  local list = {}
  for id, b in pairs(C.builds or {}) do list[#list + 1] = { id = id, name = b.name, group = b.group or "" } end
  table.sort(list, function(a, b)
    if a.group ~= b.group then return a.group > b.group end   -- "Tier S+" before "Tier S" before "Tier A"
    return a.name < b.name
  end)
  return list
end

local function setsFor(C, build, all)
  local list = {}
  for id, s in pairs(C.sets or {}) do
    if all or s.build == build then
      list[#list + 1] = { id = id, label = string.format("%s - %s (%s, act %s)", tostring(s.name), tostring(s.char),
        tostring(s.build), tostring(s.act)), act = s.act }
    end
  end
  table.sort(list, function(a, b) return a.label < b.label end)
  return list
end

local function reset(name)
  if U[name] then try(function() U[name]:Destroy() end) end
  U[name] = (U.free or U.window):AddGroup(name)
  return U[name]
end

local function send(msg)
  pcall(Ext.ClientNet.PostMessageToServer, "Gauntlet", Ext.Json.Stringify(msg))
end
local function sendTest(msg)
  pcall(Ext.ClientNet.PostMessageToServer, "GauntletTest", Ext.Json.Stringify(msg))
end

-- ------------------------------------------------------------------------------------------------ test popup
function U.BuildTest()
  local g = U.window:AddGroup("test")
  U.test = g
  colored(g:AddText("Gauntlet test"), U.GOLD)
  local mode = g:AddCombo("Mode")
  local opts = {}
  for _, id in ipairs(MODE_IDS) do opts[#opts + 1] = MODE_TEXT[id] end
  mode.Options = opts
  mode.SelectedIndex = 0
  mode.OnChange = function() sendTest({ cmd = "mode", mode = MODE_IDS[(mode.SelectedIndex or 0) + 1] }) end
  U.modeCombo = mode
  local start = g:AddButton("Start")
  start.OnClick = function() sendTest({ cmd = "start" }) end
  local stop = g:AddButton("Stop")
  stop.SameLine = true
  stop.OnClick = function() sendTest({ cmd = "stop" }) end
  U.statusLine = g:AddText("Status: waiting for the server")
  U.detailLine = colored(g:AddText(""), U.GREY)
  g:AddSeparator()
  colored(g:AddText("Last result"), U.GOLD)
  U.lastGroup = g:AddGroup("last")
  U.lastGroup:AddText("no run yet")
  sendTest({ cmd = "state" })
end

-- The server's test state (gauntlet_test.lua T.state): mode, status, detail, last result.
function U.TestState(m)
  if not U.test then return end
  for i, id in ipairs(MODE_IDS) do
    if id == m.mode and U.modeCombo then pcall(function() U.modeCombo.SelectedIndex = i - 1 end) end
  end
  U.statusLine.Label = "Status: " .. tostring(m.status) .. (m.run_id and ("   run " .. tostring(m.run_id)) or "")
  colored(U.statusLine, U.STATUS_COLOR[m.status] or U.GOLD)
  U.detailLine.Label = tostring(m.detail or "")
  if m.last and m.last.lines then
    try(function() U.lastGroup:Destroy() end)
    U.lastGroup = U.test:AddGroup("last")
    for i, l in ipairs(m.last.lines) do
      local c = (i == 1 and (m.last.valid and U.GREEN or U.RED)) or (tostring(l):sub(1, 1) == "-" and U.RED) or nil
      colored(U.lastGroup:AddText(tostring(l)), c)
    end
  end
end

-- ------------------------------------------------------------------------------------------------ free runs
function U.Build()
  U.C = catalog()
  local top = reset("top")
  if not U.C then
    top:AddText("No catalogue: run tools/gauntlet/catalog.py first, then Reload.")
    top:AddButton("Reload").OnClick = function() U.Build() end
    return
  end
  U.builds = sortedBuilds(U.C)
  local bopts = {}
  for _, b in ipairs(U.builds) do bopts[#bopts + 1] = b.group .. " | " .. b.name end
  local cb = top:AddCombo("Build")
  cb.Options = bopts
  cb.SelectedIndex = U.bi or 0
  local allBox = top:AddCheckbox("Show all sets", U.all or false)
  local sc = top:AddCombo("Set")
  local function fillSets()
    local b = U.builds[(cb.SelectedIndex or 0) + 1]
    U.sets = setsFor(U.C, b and b.id, allBox.Checked)
    local o = {}
    for _, s in ipairs(U.sets) do o[#o + 1] = s.label end
    if #o == 0 then o = { "(no set for this build - tick Show all sets)" } end
    sc.Options = o
    sc.SelectedIndex = 0
  end
  fillSets()
  cb.OnChange = function() U.bi = cb.SelectedIndex; fillSets() end
  allBox.OnChange = function() U.all = allBox.Checked; fillSets() end
  local ac = top:AddCombo("Act")
  ac.Options = { "Act 1 (level 5)", "Act 2 (level 8)", "Act 3 (level 12)" }
  ac.SelectedIndex = 2
  local scn = top:AddCombo("Scenario")
  local so = {}
  for _, s in ipairs(SCENARIOS) do so[#so + 1] = SCN_TEXT[s] end
  scn.Options = so
  scn.SelectedIndex = 0
  local tuned = top:AddCheckbox("Respec tuned to the set (else as planned)", false)
  top:AddSeparator()
  local start = top:AddButton("Start fight")
  start.OnClick = function()
    local b = U.builds[(cb.SelectedIndex or 0) + 1]
    local s = U.sets and U.sets[(sc.SelectedIndex or 0) + 1]
    if not (b and s) then U.Status("pick a build and a set") return end
    send({ cmd = "run", build = b.id, set = s.id, act = (ac.SelectedIndex or 0) + 1,
      scenario = SCENARIOS[(scn.SelectedIndex or 0) + 1], tuned = tuned.Checked, label = "manual" })
    U.Status("setting up ...")
  end
  local rs = top:AddButton("Reset fight")
  rs.SameLine = true
  rs.OnClick = function() send({ cmd = "reset" }) end
  local ab = top:AddButton("End / exit")
  ab.SameLine = true
  ab.OnClick = function() send({ cmd = "abort" }) end
  local rl = top:AddButton("Reload catalogue")
  rl.SameLine = true
  rl.OnClick = function() send({ cmd = "reload" }); U.Build() end
  U.statusText = reset("status"):AddText("ready")
  reset("checklist")
  reset("results")
end

function U.Status(t)
  if U.statusText then U.statusText.Label = tostring(t) end
end

local function showChecklist(m)
  local g = reset("checklist")
  local hb = m.hotbar or {}
  g:AddText(hb.ok and "Hotbar filled (rows below)." or ("Hotbar not written (" .. tostring(hb.err) ..
    ") - use this checklist:"))
  for _, r in ipairs(m.rows or {}) do
    local names = {}
    for _, e in ipairs(r.entries or {}) do names[#names + 1] = e.spell or e.passive or "item" end
    g:AddText(r.label .. ": " .. table.concat(names, ", "))
  end
  if hb.missing and #hb.missing > 0 then g:AddText("Not known to the character: " .. table.concat(hb.missing, ", ")) end
end

local function showResult(m)
  local g = reset("results")
  local s = m.summary or {}
  g:AddText(string.format("Run %s (%s) - %s, set %s, %s", tostring(m.run), tostring(m.mode),
    tostring(m.spec and m.spec.build), tostring(m.spec and m.spec.set_name), tostring(m.scenario)))
  g:AddText(string.format("Damage per round %.1f over %d rounds", s.dpr or 0, s.rounds or 0))
  g:AddText(string.format("Damage taken per round %.1f, max HP %d, turns survived %s", s.taken_per_round or 0,
    s.max_hp or 0, s.turns_survived and string.format("%.1f", s.turns_survived) or "-"))
  if m.expect then
    g:AddText(string.format("Model: DPR %s, rounds survived %s", tostring(m.expect.dpr), tostring(m.expect.R)))
  end
end

local function onNet(e)
  if e.Channel ~= "GauntletUI" then return end
  local m = try(Ext.Json.Parse, e.Payload)
  if type(m) ~= "table" or not U.window then return end
  if m.kind == "test" then U.TestState(m)
  elseif m.kind == "status" then U.Status(m.text)
  elseif m.kind == "checklist" then showChecklist(m)
  elseif m.kind == "result" then U.Status("done"); showResult(m)
  end
end

function U.Toggle()
  if not U.window then
    U.window = Ext.IMGUI.NewWindow("Gauntlet (test)")
    U.window.Closeable = true
    U.window.Open = false
    style(U.window)
    U.BuildTest()
    U.window:AddSeparator()
    U.free = U.window:AddCollapsingHeader("Free runs (catalogue)")
    U.Build()
  end
  U.window.Open = not U.window.Open
  if U.window.Open then sendTest({ cmd = "state" }) end
end

if U._net then pcall(function() Ext.Events.NetMessage:Unsubscribe(U._net) end) end
U._net = Ext.Events.NetMessage:Subscribe(function(e) pcall(onNet, e) end)
if U._key then pcall(function() Ext.Events.KeyInput:Unsubscribe(U._key) end) end
U._key = Ext.Events.KeyInput:Subscribe(function(e)
  if e.Event == "KeyDown" and not e.Repeat and tostring(e.Key) == U.HOTKEY then pcall(U.Toggle) end
end)

return "gauntlet window ready (" .. U.HOTKEY .. ")"
