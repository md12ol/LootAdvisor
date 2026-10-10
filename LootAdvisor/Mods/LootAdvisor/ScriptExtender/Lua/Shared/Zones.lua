-- LootAdvisor: areas ("zones") and their entrances (data: LA.Mod.zones / LA.Mod.entrances, generated from the
-- game's level data - teleporting doors/ladders/hatches/portals and the story scripts' portal tables).
-- An item inside an interior that is stored elsewhere in the level (vaults, House of Hope, Guildhall, ...) gets its
-- map marker on the entrance on the shortest way from the player (Dijkstra over the entrance links, straight-line
-- distances inside an area).

LA = LA or {}
LA.Zones = LA.Zones or {}
local Z = LA.Zones
local cells = {}  -- region -> { [cx * 100000 + cz] = zone }

local function cellmap(region)
  local m = cells[region]
  if m then return m end
  m = {}
  for zone, runs in pairs((LA.Mod.zones or {})[region] or {}) do
    for rs, as, bs in runs:gmatch("(-?%d+),(-?%d+),(-?%d+)") do
      local row, a, b = tonumber(rs), tonumber(as), tonumber(bs)
      for x = a, b do m[x * 100000 + row] = zone end
    end
  end
  cells[region] = m
  return m
end

function Z.At(region, x, z)
  if not (region and x and z) then return nil end
  local m = cellmap(region)
  local c = LA.Mod.zoneCell or 16
  local cx, cz = math.floor(x / c), math.floor(z / c)
  local hit = m[cx * 100000 + cz]
  if hit then return hit end
  for r = 1, 3 do
    local best, bd
    for dx = -r, r do
      for dz = -r, r do
        local v = m[(cx + dx) * 100000 + (cz + dz)]
        if v and (not bd or dx * dx + dz * dz < bd) then best, bd = v, dx * dx + dz * dz end
      end
    end
    if best then return best end
  end
  return nil
end

local function dist(ax, az, bx, bz) return math.sqrt((ax - bx) ^ 2 + (az - bz) ^ 2) end

-- Shortest distances from the player to every entrance (Dijkstra over the entrance links, straight lines inside an
-- area), with the first entrance taken on each way. Computed once per player spot and shared by every item: with the
-- whole roster marked, a refresh routes hundreds of items and a search per item cost most of a second (seen in game).
local tree = { key = nil }
local function routes(region, ents, zp, px, pz)
  local key = ("%s|%s|%.1f|%.1f"):format(region, zp, px, pz)
  if tree.key == key then return tree end
  local byZone = {}
  for j, f in ipairs(ents) do
    local l = byZone[f.zf]
    if not l then l = {}; byZone[f.zf] = l end
    l[#l + 1] = j
  end
  local d, first, done, open = {}, {}, {}, {}
  for _, i in ipairs(byZone[zp] or {}) do
    local e = ents[i]
    d[i], first[i] = dist(px, pz, e.x, e.z), i
    open[#open + 1] = i
  end
  while #open > 0 do
    local bi = 1
    for k = 2, #open do if d[open[k]] < d[open[bi]] then bi = k end end
    local i = table.remove(open, bi)
    if not done[i] then
      done[i] = true
      local e = ents[i]
      for _, j in ipairs(byZone[e.zt] or {}) do
        if not done[j] then
          local f = ents[j]
          local nd = d[i] + dist(e.tx, e.tz, f.x, f.z)
          if not d[j] or nd < d[j] then
            if not d[j] then open[#open + 1] = j end
            d[j], first[j] = nd, first[i]
          end
        end
      end
    end
  end
  tree = { key = key, d = d, first = first }
  return tree
end

-- player at (px, pz) in zone zp, item at (ix, iz) in zone zi -> first entrance on the shortest way (or nil)
function Z.Route(region, zp, px, pz, zi, ix, iz)
  local ents = (LA.Mod.entrances or {})[region]
  if not ents or not zp or not zi or zp == zi then return nil end
  local t = routes(region, ents, zp, px, pz)
  local best, bd
  for i, e in ipairs(ents) do
    if e.zt == zi and t.d[i] then
      local tot = t.d[i] + dist(e.tx, e.tz, ix, iz)
      if not bd or tot < bd then best, bd = i, tot end
    end
  end
  if best then
    local f = ents[t.first[best]]
    return f, bd, f.zt == zi
  end
  -- no way from here (the player's area is not linked): the last entrance into the item's area nearest the player
  local last, ld
  for _, e in ipairs(ents) do
    if e.zt == zi then
      local dd = dist(px, pz, e.x, e.z)
      if not ld or dd < ld then last, ld = e, dd end
    end
  end
  return last, ld, true
end

-- Round 3: the way out of `region` toward region `to` (items in another region). Region graph = the region-swap
-- teleporters (LA.Mod.exits, from the story's DB_GLO_LevelSwap tables); the first exit of the shortest region path
-- that is nearest the player; no path -> the nearest waypoint (fast travel). Returns the spot (exit or waypoint),
-- whether it is a waypoint, and the next region.
function Z.WayOut(region, px, pz, to)
  local exits = LA.Mod.exits or {}
  -- BFS over regions
  local prev, queue, seen = {}, { region }, { [region] = true }
  while #queue > 0 and not seen[to] do
    local r = table.remove(queue, 1)
    for _, e in ipairs(exits[r] or {}) do
      if e.to ~= "" and not seen[e.to] then seen[e.to] = true; prev[e.to] = r; queue[#queue + 1] = e.to end
    end
  end
  if seen[to] then
    local nxt = to
    while prev[nxt] and prev[nxt] ~= region do nxt = prev[nxt] end
    local best, bd
    for _, e in ipairs(exits[region] or {}) do
      if e.to == nxt then
        local d = dist(px, pz, e.x, e.z)
        if not bd or d < bd then best, bd = e, d end
      end
    end
    if best then return best, false, nxt end
  end
  local best, bd
  for _, w in ipairs((LA.Mod.waypoints or {})[region] or {}) do
    local d = dist(px, pz, w.x, w.z)
    if not bd or d < bd then best, bd = w, d end
  end
  return best, true, to
end
