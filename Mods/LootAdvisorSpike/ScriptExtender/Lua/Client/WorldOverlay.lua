-- (a fallback) Purple symbol drawn OVER the item on screen + a list window with direction and distance.
-- Pure client UI (Ext.IMGUI), nothing in the save. World -> screen projection is the one already used and
-- working in Mods/Autopilot/ScriptExtender/Lua/Client/Probe.lua (active Camera entity, Controller.Camera.ViewMatrix /
-- ProjectionMatrix, column-major). IMGUI fields used are present in the installed v32 DLL: NewWindow, Open,
-- NoTitleBar, NoBackground, NoInputs, SetPos, AddText, SetColor, Label, Visible, AddImage (with Tint).
-- Compass orientation (which world axis is map north) is UNVERIFIED: check once against the minimap's X/Y readout.

LAS = LAS or {}
local try = LAS.try

LAS.items = {} -- rows from the server (LAS_Items): { key, name, why, x, y, z, carriedByParty }
local MAX_PINS = 12

Ext.Events.NetMessage:Subscribe(function(e)
  if e.Channel == LAS.CH_ITEMS then LAS.items = try(Ext.Json.Parse, e.Payload) or {} end
end)

local function activeCamera()
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "Camera") or {}) do
    local c = try(function() return e.Camera end)
    if c and try(function() return c.Active end) then return c end
  end
end

local function flat(m)
  if type(m) ~= "table" then return nil end
  if #m == 16 then return m end
  local out = {}
  for i = 1, 4 do local r = m[i]; if type(r) ~= "table" then return nil end; for j = 1, 4 do out[#out + 1] = r[j] end end
  return #out == 16 and out or nil
end

local function mulCM(m, v)
  local r = {}
  for i = 1, 4 do r[i] = m[i] * v[1] + m[4 + i] * v[2] + m[8 + i] * v[3] + m[12 + i] * v[4] end
  return r
end

local function projector()
  local cam = activeCamera()
  local V = cam and flat(try(function() return cam.Controller.Camera.ViewMatrix end))
  local P = cam and flat(try(function() return cam.Controller.Camera.ProjectionMatrix end))
  local vp = try(Ext.IMGUI.GetViewportSize) or { 2560, 1440 }
  if not (V and P) then return nil end
  return function(x, y, z)
    local c = mulCM(P, mulCM(V, { x, y, z, 1 }))
    if not c[4] or c[4] <= 0.0001 then return nil end
    local nx, ny = c[1] / c[4], c[2] / c[4]
    if math.abs(nx) > 1 or math.abs(ny) > 1 then return nil end
    return (nx + 1) / 2 * vp[1], (1 - ny) / 2 * vp[2]
  end, V
end

local COMPASS = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" }
local function compass(dx, dz) -- assumes +Z = north, +X = east (to verify)
  local a = (math.deg(math.atan(dx, dz)) + 360) % 360
  return COMPASS[math.floor((a + 22.5) / 45) % 8 + 1], a
end

local function relative(V, dx, dz) -- camera-relative: V row 3 = camera back axis (see Probe.lua pitch)
  if not V then return "" end
  local fx, fz = -V[3], -V[11] -- forward projected on the ground (column-major: row 3 = m[3], m[7], m[11])
  local ang = math.deg(math.atan(dx, dz) - math.atan(fx, fz))
  ang = (ang + 540) % 360 - 180
  if math.abs(ang) < 30 then return "ahead" elseif math.abs(ang) > 150 then return "behind" end
  return ang > 0 and "to the right" or "to the left" -- sign to verify in game
end

local list, listRows, pins = nil, {}, {}

local function ensureList()
  if list then return end
  list = Ext.IMGUI.NewWindow("LootAdvisor (spike)")
  list.Closeable = true
  list.AlwaysAutoResize = true
end

local function pin(i)
  if pins[i] then return pins[i] end
  local w = Ext.IMGUI.NewWindow("##LASpin" .. i)
  w.NoTitleBar, w.NoBackground, w.NoInputs, w.NoSavedSettings = true, true, true, true
  w.NoFocusOnAppearing, w.NoBringToFrontOnFocus, w.AlwaysAutoResize = true, true, true
  local t = w:AddText(LAS.MARK)
  pcall(function() t:SetColor("Text", LAS.PURPLE) end)
  pins[i] = { w = w, t = t }
  return pins[i]
end

function LAS.UpdateOverlay()
  if not (LAS.Settings and LAS.Settings.Overlay) then return end
  ensureList()
  local me = LAS.selectedEntity
  local p = me and try(function() return me.Transform.Transform.Translate end)
  local proj, V = projector()
  for _, r in ipairs(listRows) do pcall(function() r:Destroy() end) end
  listRows = {}
  local used = 0
  for _, it in ipairs(LAS.items or {}) do
    if p and not it.carriedByParty then
      local dx, dz = it.x - p[1], it.z - p[3]
      local dist = math.sqrt(dx * dx + dz * dz)
      local dir = compass(dx, dz)
      local row = list:AddText(("%s %s  %.0f m %s, %s  (%s)"):format(LAS.MARK, it.name or it.key, dist, dir,
        relative(V, dx, dz), it.why or ""))
      pcall(function() row:SetColor("Text", LAS.PURPLE) end)
      listRows[#listRows + 1] = row
      local sx, sy = proj and proj(it.x, it.y + 1.2, it.z)
      if sx and used < MAX_PINS then
        used = used + 1
        local pn = pin(used)
        pn.w.Open = true
        pcall(function() pn.w:SetPos({ sx - 8, sy - 16 }) end)
      end
    end
  end
  for i = used + 1, #pins do pins[i].w.Open = false end
end
