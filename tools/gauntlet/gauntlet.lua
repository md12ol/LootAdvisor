-- Gauntlet: measures a gear set in the real game (server side, Script Extender). TEST SAVES ONLY: it rebuilds a
-- character's sheet, spawns items and creatures and never saves. Loaded at runtime through the mod's dev eval hook
-- (tools/gauntlet/engine.py load); driven by tools/gauntlet/run.py, which writes the spec and reads the results.
--
-- Flow for one set:  GAUNTLET.prep(spec)  -> character sheet + items + buffs   (status "prepped")
--                    GAUNTLET.fight(spec) -> one scenario, N rounds              (status "done")
--                    GAUNTLET.dump()      -> LootAdvisor_gauntlet_out.json
-- The tested character follows a SCRIPTED round plan (spec.plan); the enemies are left to the game's AI.
-- Every action is paid with its normal cost (checked against the character's resources first); an action that cannot
-- be done (no resource, out of range, engine refused) is logged with the reason and skipped.

GAUNTLET = GAUNTLET or {}
local G = GAUNTLET
G.VERSION = 5

local RES = {
  ActionPoint = "734cbcfb-8922-4b6d-8330-b2a7e4c14b6a",
  BonusActionPoint = "420c8df5-45c2-4253-93c2-7ec44e127930",
  Movement = "d6b2369d-84f0-4ca4-a3a7-62d2d192a185",
  ReactionActionPoint = "45ff0f48-b210-4024-972f-b64a44dc6985",
  SpellSlot = "d136c5d9-0ff0-43da-acce-a74a07f8d6bf",
}
local ABIL = { "Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma" }
local ABIL_SHORT = { STR = "Strength", DEX = "Dexterity", CON = "Constitution", INT = "Intelligence", WIS = "Wisdom",
  CHA = "Charisma" }
local CAUSE = "Gauntlet"

-- ------------------------------------------------------------------------------------------------ helpers
local function try(f, ...)
  local ok, r = pcall(f, ...)
  if ok then return r end
  return nil
end
local function now() return Ext.Utils.MonotonicTime() end
local function uuid(x)
  if type(x) ~= "string" then return x end
  return x:match("(%x+%-%x+%-%x+%-%x+%-%x+)$") or x
end
local function ent(u) return try(Ext.Entity.Get, uuid(u)) end
local function name(u)
  local h = try(Osi.GetDisplayName, u)
  return (h and try(Osi.ResolveTranslatedString, h)) or tostring(u)
end
local function note(fmt, ...)
  local s = string.format(fmt, ...)
  G.log[#G.log + 1] = string.format("%.1f %s", (now() - (G.t0 or now())) / 1000, s)
end
function G.fail(msg)
  note("FAIL %s", msg)
  G.status = "failed: " .. msg
end
-- ------------------------------------------------------------------------------------------------ lanes
-- Two fights at once: two characters with the same build, each with its own set and its own enemies, in two combats
-- far enough apart that nothing of one reaches the other. A run keeps its state in the fields below; each lane has its
-- own copy. G.inLane(id, fn) puts that lane's copy in place, runs fn and puts the previous one back, so timers, the
-- fight loop and the engine's events always work on the lane they belong to. A single run uses the "base" copy.
G.LANE_FIELDS = { "F", "log", "rounds", "dmg", "hits", "results", "status", "t0", "round", "fighting", "prepGen",
  "origin", "manualPrep", "spawned", "spawnedItems", "savedReactions" }
G.ctx = G.ctx or {}
G.curLane = G.curLane or "base"
local function swapTo(id)
  if G.curLane == id then return end
  local cur = G.ctx[G.curLane] or {}
  G.ctx[G.curLane] = cur
  for _, k in ipairs(G.LANE_FIELDS) do cur[k] = G[k] end
  local nxt = G.ctx[id] or {}
  G.ctx[id] = nxt
  for _, k in ipairs(G.LANE_FIELDS) do G[k] = nxt[k] end
  G.curLane = id
end
function G.inLane(id, fn, ...)
  local prev = G.curLane
  swapTo(id or prev)
  local ok, res = pcall(fn, ...)
  swapTo(prev)
  if not ok then error(res, 0) end
  return res
end
-- a field of another lane's state (the current lane's lives in G itself)
function G.laneField(id, k)
  if id == G.curLane then return G[k] end
  return (G.ctx[id] or {})[k]
end

-- a timer runs in the lane that set it
local function wait(ms, fn)
  local lane = G.curLane
  Ext.Timer.WaitFor(ms, function()
    local ok, err = pcall(G.inLane, lane, fn)
    if not ok then pcall(G.inLane, lane, G.fail, "timer: " .. tostring(err)) end
  end)
end
local function pos(u) return try(Osi.GetPosition, u) end
-- x, y, z (nil when unknown)
local function xyz(u)
  local ok, x, y, z = pcall(Osi.GetPosition, u)
  if ok and x then return x, y, z end
  return nil
end
local function dist(a, b)
  local ax, ay, az = Osi.GetPosition(a)
  local bx, by, bz = Osi.GetPosition(b)
  if not ax or not bx then return 1e9 end
  return math.sqrt((ax - bx) ^ 2 + (ay - by) ^ 2 + (az - bz) ^ 2)
end

function G.reset()
  G.log, G.rounds, G.dmg, G.hits, G.results, G.status = {}, {}, {}, {}, {}, "idle"
  G.t0 = now()
end
if not G.log then G.reset() end

function G.dump(file)
  local data = { version = G.VERSION, status = G.status, log = G.log, rounds = G.rounds, dmg = G.dmg,
    results = G.results }
  try(Ext.IO.SaveFile, file or "LootAdvisor_gauntlet_out.json", Ext.Json.Stringify(data))
  return G.status
end

-- ------------------------------------------------------------------------------------------------ resources
local function resName(k)
  local def = try(Ext.StaticData.Get, k, "ActionResource")
  return def and def.Name, def
end
local function resList(u, kind)
  local e = ent(u)
  local rs = e and try(function() return e.ActionResources.Resources end)
  if not rs then return nil end
  if RES[kind] and rs[RES[kind]] then return rs[RES[kind]] end
  for k, v in pairs(rs) do if resName(k) == kind then return v end end
  return nil
end
local function resAmount(u, kind, level)
  local v = try(Osi.GetActionResourceValuePersonal, u, kind, level or 0)
  if v then return v end
  for _, entry in ipairs(resList(u, kind) or {}) do
    if not level or level == 0 or entry.Level == level then return entry.Amount end
  end
  return 0
end
local function parseCosts(s)
  local out = {}
  for part in tostring(s or ""):gmatch("[^;]+") do
    local f = {}
    for v in part:gmatch("[^:]+") do f[#f + 1] = (v:gsub("^%s+", ""):gsub("%s+$", "")) end
    if f[1] == "SpellSlotsGroup" then
      out[#out + 1] = { kind = "SpellSlot", n = tonumber(f[2]) or 1, level = tonumber(f[4]) or 1 }
    elseif f[1] and f[1] ~= "" then
      out[#out + 1] = { kind = f[1], n = tonumber(f[2]) or 1, level = tonumber(f[3]) }
    end
  end
  return out
end
local function spellCosts(spell)
  local st = try(Ext.Stats.Get, spell)
  return parseCosts(st and try(function() return st.UseCosts end))
end
local function canPay(u, costs)
  for _, c in ipairs(costs) do
    if resAmount(u, c.kind, c.level) < c.n then return false, c.kind .. (c.level and (" L" .. c.level) or "") end
  end
  return true
end
-- Pays what the engine has not already taken: before[i] is the amount of costs[i] read just before the cast, so a
-- cost the engine deducted itself is not paid a second time.
local function pay(u, costs, before)
  local e = ent(u)
  for i, c in ipairs(costs) do
    local owed = c.n
    if before and before[i] then owed = c.n - math.max(0, before[i] - resAmount(u, c.kind, c.level)) end
    for _, entry in ipairs(owed > 0 and resList(u, c.kind) or {}) do
      if not c.level or c.level == 0 or entry.Level == c.level then
        entry.Amount = math.max(0, entry.Amount - owed)
        break
      end
    end
  end
  pcall(function() e:Replicate("ActionResources") end)
end
-- the engine's own cooldown on a spell (per-rest item spells, per-turn class actions); true while it cannot be cast
local function onCooldown(u, spell)
  local e = ent(u)
  local cds = e and try(function() return e.SpellBookCooldowns.Cooldowns end)
  for i = 1, (cds and #cds or 0) do
    local id = try(function() return cds[i].SpellId.Prototype end)
    if id == spell and (try(function() return cds[i].Cooldown end) or 0) > 0 then return true end
  end
  return false
end
-- Can the character pay for this action right now: action / bonus action / spell slot / class resource from the
-- action's costs, the harness's own per-rest record, and the engine's cooldown. Returns ok, reason.
function G.afford(F, a)
  if F.unusable and F.unusable[a.spell] then return false, "unusable: " .. F.unusable[a.spell] end
  if F.afford then return F.afford(a) end
  local costs = a.cost == "free" and {} or (a.cost and parseCosts(a.cost) or spellCosts(a.spell))
  local ok, why = canPay(F.char, costs)
  if not ok then return false, "no resource " .. tostring(why) end
  if a.per and F.cooldown[a.spell] then return false, "used this rest" end
  if onCooldown(F.char, a.spell) then return false, "on cooldown" end
  return true
end
-- Picks the first action of a priority chain (a, a.alt, a.alt.alt, ...) that the character can pay for at the call;
-- the ones passed over are logged with their reason. nil when nothing in the chain is affordable.
function G.pickAffordable(F, a, skips)
  while a do
    local ok, why = G.afford(F, a)
    if ok then return a end
    if skips then skips[#skips + 1] = { spell = a.spell, why = why } end
    a = a.alt
  end
  return nil
end

-- Refill: "long" = everything; "short" = what the game replenishes on a short rest (+ short-rest cooldowns)
function G.refill(u, kind)
  local e = ent(u)
  local rs = e and try(function() return e.ActionResources.Resources end)
  for k, list in pairs(rs or {}) do
    local _, def = resName(k)
    local rep = def and tostring(def.ReplenishType) or "?"
    if kind == "long" or rep == "ShortRest" or rep == "Turn" then
      for _, entry in ipairs(list) do entry.Amount = entry.MaxAmount end
    end
  end
  pcall(function() e:Replicate("ActionResources") end)
  local cds = e and try(function() return e.SpellBookCooldowns.Cooldowns end)
  if cds then
    for i = 1, #cds do
      local t = tostring(try(function() return cds[i].CooldownType end))
      if kind == "long" or t:match("ShortRest") or t:match("Turn") or t:match("Combat") then
        pcall(function() cds[i].Cooldown = 0 end)
      end
    end
    pcall(function() e:Replicate("SpellBookCooldowns") end)
  end
end

-- ------------------------------------------------------------------------------------------------ sheet
local function abilities(u)
  local e = ent(u)
  local a = e and try(function() return e.Stats.Abilities end)
  local out = {}
  if a then for i, n in ipairs(ABIL) do out[n] = a[i + 1] end end
  return out
end
local SLOTS = { "Helmet", "Breast", "Cloak", "MeleeMainHand", "MeleeOffHand", "RangedMainHand", "RangedOffHand",
  "Ring", "Ring2", "Amulet", "Boots", "Gloves" }
-- Osiris names the weapon slots as the item data does ("Melee Main Weapon"); asking for "MeleeMainHand" finds nothing,
-- so the pilot's run records never showed a weapon as equipped and prep never took the test character's own off.
G.SLOT_NAMES = { MeleeMainHand = { "Melee Main Weapon", "MeleeMainHand" },
  MeleeOffHand = { "Melee Offhand Weapon", "MeleeOffHand" }, RangedMainHand = { "Ranged Main Weapon", "RangedMainHand" },
  RangedOffHand = { "Ranged Offhand Weapon", "RangedOffHand" } }
function G.equipped(u)
  local out = {}
  for _, s in ipairs(SLOTS) do
    for _, n in ipairs(G.SLOT_NAMES[s] or { s }) do
      local it = try(Osi.GetEquippedItem, u, n)
      if it then out[s] = it; break end
    end
  end
  return out
end
function G.strip(u)
  for _, it in pairs(G.equipped(u)) do pcall(Osi.Unequip, u, it) end
end
function G.sheet(u)
  local e = ent(u)
  local s = { abilities = abilities(u), hp = try(Osi.GetMaxHitpoints, u),
    ac = e and try(function() return e.Resistances.AC end), prof = e and try(function() return e.Stats.ProficiencyBonus end),
    level = e and try(function() return e.EocLevel.Level end), slots = {}, passives = {}, equipped = {}, resources = {} }
  for _, entry in ipairs(resList(u, "SpellSlot") or {}) do s.slots[tostring(entry.Level)] = entry.MaxAmount end
  for k, list in pairs(e and try(function() return e.ActionResources.Resources end) or {}) do
    local n = resName(k) or tostring(k)
    for _, entry in ipairs(list) do s.resources[n .. ":" .. tostring(entry.Level)] = entry.MaxAmount end
  end
  for _, p in ipairs(e and try(function() return e.PassiveContainer.Passives end) or {}) do
    local id = try(function() return p.Passive.PassiveId end)
    if id then s.passives[#s.passives + 1] = id end
  end
  for slot, it in pairs(G.equipped(u)) do s.equipped[slot] = try(Osi.GetStatString, it) or name(it) end
  -- the active statuses, so a sheet that differs from the build (a bare max HP 8 above it, once) can be traced
  s.statuses = {}
  for id in pairs(G.statusSet(u)) do s.statuses[#s.statuses + 1] = id end
  table.sort(s.statuses)
  -- the boosts on the character and what it concentrates on, so a record shows which effects were there
  s.boosts = G.boostList(u)
  s.concentration = G.concentration(u)
  return s
end
local function boost(u, b)
  local ok, err = pcall(Osi.AddBoosts, u, b, CAUSE, u)
  note("boost %s %s", b, ok and "ok" or tostring(err))
end

-- ------------------------------------------------------------------------------------------------ probe
function G.probe()
  G.reset()
  local out = { api = {}, party = {}, difficulty = {} }
  for _, f in ipairs({ "CreateAt", "Equip", "Unequip", "GetEquippedItem", "AddBoosts", "RemoveBoosts", "AddPassive",
    "RemovePassive", "AddSpell", "UseSpell", "UseSpellAtPosition", "EndTurn", "ApplyStatus", "SetFaction",
    "EnterCombat", "SetHitpointsPercentage", "TeleportToPosition", "RequestDelete", "GetDifficulty",
    "SetRelationTemporaryHostile", "SetHostileAndEnterCombat", "IsProficientWith", "GetFaction", "SetRelation",
    "GetRelation", "IsEnemy", "CombatGetGuidFor" }) do
    out.api[f] = try(function() return Osi[f] ~= nil end)
  end
  out.api.OsirisListener = G._listeners and G._listeners.attacked
  out.api.DealDamage = Ext.Events.DealDamage ~= nil
  out.difficulty.osi = try(Osi.GetDifficulty)
  out.host = try(Osi.GetHostCharacter)
  out.pos = { pos(out.host) }
  out.region = try(Osi.GetRegion, out.host)
  for _, row in ipairs(try(function() return Osi.DB_Players:Get(nil) end) or {}) do
    local u = row[1]
    local e = ent(u)
    local cls = {}
    for _, c in ipairs(e and try(function() return e.Classes.Classes end) or {}) do
      local cd = try(Ext.StaticData.Get, c.ClassUUID, "ClassDescription")
      local sd = try(Ext.StaticData.Get, c.SubClassUUID, "ClassDescription")
      cls[#cls + 1] = { class = cd and cd.Name or tostring(c.ClassUUID), sub = sd and sd.Name or nil, level = c.Level }
    end
    out.party[#out.party + 1] = { uuid = u, name = name(u), classes = cls, sheet = G.sheet(u) }
  end
  G.results.probe = out
  G.status = "probed"
  return G.dump()
end

-- ------------------------------------------------------------------------------------------------ items
-- items: { {slot = "MeleeOffHand", template = "<uuid>", stats = "<stats id>"}, ... } equipped in order
G.POLL_MS, G.EQUIP_MS, G.USE_MS = 100, 2000, 500
local function equipAll(u, items, i, cb)
  if i > #items then return cb() end
  local spec = items[i]
  local x, y, z = Osi.GetPosition(u)
  local it = try(Osi.CreateAt, spec.template, x, y, z, 0, 0, "")
  if not it then
    G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, err = "CreateAt failed" }
    return equipAll(u, items, i + 1, cb)
  end
  G.spawnedItems = G.spawnedItems or {}
  G.spawnedItems[#G.spawnedItems + 1] = it
  pcall(Osi.ToInventory, it, u, 1, 0, 0)
  wait(G.POLL_MS, function()
    if spec.use and G.manualPrep then
      G.results.consumables = G.results.consumables or {}
      G.results.consumables[#G.results.consumables + 1] = it
      G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, got = "inventory", uuid = it }
      return equipAll(u, items, i + 1, cb)
    end
    if spec.use then
      local before = G.statusSet(u)
      pcall(Osi.Use, u, it, "")
      G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, got = "used", uuid = it }
      local rec = G.results.items[#G.results.items]
      return wait(G.USE_MS, function()
        -- the statuses the elixir gave are taken off in the next run's prep, before the bare sheet is read; the setup
        -- check finds them still on as the fight starts
        G.usedStatuses = G.usedStatuses or {}
        G.usedStatuses[uuid(u)] = G.usedStatuses[uuid(u)] or {}
        rec.statuses = {}
        for st in pairs(G.statusSet(u)) do
          if not before[st] then
            G.usedStatuses[uuid(u)][st] = true
            rec.statuses[#rec.statuses + 1] = st
          end
        end
        table.sort(rec.statuses)
        equipAll(u, items, i + 1, cb)
      end)
    end
    pcall(Osi.Equip, u, it, 1, 0, 0)
    -- worn yet? asked every POLL_MS; an equip that has not taken by half of EQUIP_MS is asked for once more (two runs
    -- of the control lost a ring or boots that a fixed 350 ms wait read as not worn)
    local t0, again = now(), false
    local function check()
      local where
      for s, e in pairs(G.equipped(u)) do if uuid(e) == uuid(it) then where = s end end
      -- the slot query can miss a slot name; the item itself knows whether it is worn
      if not where and try(Osi.IsEquipped, it) == 1 then where = spec.slot end
      local waited = now() - t0
      -- a slow frame can skip past half the time: the second ask always happens before giving up
      if not where and (waited < G.EQUIP_MS or not again) then
        if not again and waited >= G.EQUIP_MS / 2 then again = true; t0 = now() - G.EQUIP_MS / 2; pcall(Osi.Equip, u, it, 1, 0, 0) end
        return wait(G.POLL_MS, check)
      end
      G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, got = where, uuid = it,
        ms = waited, again = again or nil }
      note("item %s want %s got %s", spec.stats, spec.slot, tostring(where))
      equipAll(u, items, i + 1, cb)
    end
    wait(G.POLL_MS, check)
  end)
end

-- ------------------------------------------------------------------------------------------------ encumbrance
-- The pilot's test character carried ENCUMBERED_MAX (Heavily Encumbered) in every run: its own pack plus the items
-- each run spawned. That status gives Disadvantage on attack rolls and on Strength / Dexterity / Constitution saves and
-- limits movement to a stroll at three times the cost, so spell attacks missed more and a cast that needs a step
-- could not be made. Prep therefore deletes the items earlier runs spawned and raises the carry limit for the run
-- (a boost with the harness's cause, taken off when the run ends); a character still encumbered at the start of the
-- fight makes the run invalid.
G.ENCUMBRANCE = { "ENCUMBERED_LIGHT", "ENCUMBERED_HEAVY", "ENCUMBERED_MAX", "ENCUMBERED" }
G.CARRY_BOOST = "CarryCapacityMultiplier(50)"
function G.encumbrance(u)
  local out = {}
  for _, st in ipairs(G.ENCUMBRANCE) do
    if try(Osi.HasActiveStatus, u, st) == 1 then out[#out + 1] = st end
  end
  return out
end
-- deletes the items earlier runs spawned (worn ones are taken off first by G.strip); returns how many
function G.dropSpawnedItems(u)
  local n = 0
  for _, it in ipairs(G.spawnedItems or {}) do
    if try(Osi.IsEquipped, it) == 1 then pcall(Osi.Unequip, u, it) end
    if pcall(Osi.RequestDelete, it) then n = n + 1 end
  end
  G.spawnedItems = {}
  return n
end
function G.unencumber(u, addBoost)
  if addBoost then boost(u, G.CARRY_BOOST) end
  for _, st in ipairs(G.encumbrance(u)) do pcall(Osi.RemoveStatus, u, st, "") end
end

-- ------------------------------------------------------------------------------------------------ prep
-- spec.char, spec.sheet = {abilities = {STR = ..}, hp, prof, ac_unarmoured}, spec.passives_add / passives_remove,
-- spec.spells_add, spec.boosts, spec.slots = {["1"] = 4, ...}, spec.resources = {{kind, n, level}}, spec.items,
-- spec.statuses (fixed buffs), spec.park = {x, y, z} for the other party members (solo)
function G.prep(spec)
  G.reset()
  G.status = "prepping"
  -- a prep that was given up (timed out) must not mark a later run as prepped when its timers finally finish
  local gen = (G.prepGen or 0) + 1
  G.prepGen = gen
  local u = spec.char
  G.results.items = {}
  G.results.before = G.sheet(u)
  for _, row in ipairs(try(function() return Osi.DB_Players:Get(nil) end) or {}) do
    if uuid(row[1]) ~= uuid(u) and spec.park and not (G.LANES and G.LANES.on) then
      pcall(Osi.TeleportToPosition, row[1], spec.park[1], spec.park[2], spec.park[3], "", 0, 0, 0, 0, 1)
    end
  end
  G.revive(u)
  pcall(Osi.RemoveBoosts, u, "", 0, CAUSE, u)
  G.dropRunBoosts(u, G.OLD_HP_BUFFER)
  G.strip(u)
  -- a real respec (the character levelled to the build in a test save): the sheet is the character's own; nothing is
  -- emulated, the setup check compares it with the build instead
  local emulate = not spec.real_respec
  G.results.respec = emulate and "emulated" or "real"
  wait(G.SETTLE_MS, function()
    G.results.items_deleted = G.dropSpawnedItems(u)
    G.unencumber(u, true)
    G.results.used_statuses_removed = G.removeUsedStatuses(u)
    G.results.carry_over = G.removeCarryOver(u)
    for _, p in ipairs(emulate and spec.passives_remove or {}) do
      if try(Osi.HasPassive, u, p) == 1 then pcall(Osi.RemovePassive, u, p); note("passive -%s", p) end
    end
    for _, p in ipairs(emulate and spec.passives_add or {}) do
      if try(Osi.HasPassive, u, p) ~= 1 then pcall(Osi.AddPassive, u, p); note("passive +%s", p) end
    end
    for _, sp in ipairs(emulate and spec.spells_add or {}) do pcall(Osi.AddSpell, u, sp, 0, 1) end
    for _, b in ipairs(emulate and spec.boosts or {}) do boost(u, b) end
    wait(G.SETTLE_MS, function()
      local cur = abilities(u)
      for short, want in pairs(emulate and spec.sheet.abilities or {}) do
        local n = ABIL_SHORT[short]
        local d = want - (cur[n] or want)
        if d ~= 0 then boost(u, string.format("Ability(%s,%d)", n, d)) end
      end
      wait(G.SETTLE_MS, function()
        if not emulate then return G.prepItems(u, spec, gen) end
        local e = ent(u)
        local prof = e and try(function() return e.Stats.ProficiencyBonus end) or spec.sheet.prof
        local dp = spec.sheet.prof - prof
        if dp ~= 0 then
          boost(u, string.format("RollBonus(Attack,%d)", dp))
          boost(u, string.format("SpellSaveDC(%d)", dp))
        end
        local hp = try(Osi.GetMaxHitpoints, u) or spec.sheet.hp
        if spec.sheet.hp - hp ~= 0 then boost(u, string.format("IncreaseMaxHP(%d)", spec.sheet.hp - hp)) end
        local ac = e and try(function() return e.Resistances.AC end)
        if spec.sheet.ac_unarmoured and ac and ac ~= spec.sheet.ac_unarmoured then
          boost(u, string.format("AC(%d)", spec.sheet.ac_unarmoured - ac))
        end
        local have = {}
        for _, entry in ipairs(resList(u, "SpellSlot") or {}) do have[entry.Level] = entry.MaxAmount end
        for lv = 1, 9 do
          local d = (spec.slots and spec.slots[tostring(lv)] or 0) - (have[lv] or 0)
          if d ~= 0 then boost(u, string.format("ActionResource(SpellSlot,%d,%d)", d, lv)) end
        end
        for _, r in ipairs(spec.resources or {}) do
          local m = 0
          for _, entry in ipairs(resList(u, r.kind) or {}) do m = math.max(m, entry.MaxAmount) end
          if r.n - m ~= 0 then boost(u, string.format("ActionResource(%s,%d,%d)", r.kind, r.n - m, r.level or 0)) end
        end
        wait(G.SETTLE_MS, function() G.prepItems(u, spec, gen) end)
      end)
    end)
  end)
  return G.status
end
-- The character's active statuses as a set of ids.
function G.statusSet(u)
  local out = {}
  local e = ent(u)
  for _, v in pairs(e and try(function() return e.StatusContainer.Statuses end) or {}) do out[tostring(v)] = true end
  return out
end
-- An elixir or potion an earlier run used lasts until a long rest: its statuses (Cloud Giant Strength, STR 27) were
-- still on in the next run's bare sheet and failed the setup check. Takes off what a run's consumable gave.
function G.removeUsedStatuses(u)
  local out = {}
  for st in pairs((G.usedStatuses or {})[uuid(u)] or {}) do
    pcall(Osi.RemoveStatus, u, st, "")
    out[#out + 1] = st
  end
  if G.usedStatuses then G.usedStatuses[uuid(u)] = nil end
  table.sort(out)
  return out
end

-- ------------------------------------------------------------------------------------------------ carried state
-- A run left state behind that the next run started with: the Hunter's Mark concentration was still held (Strange
-- Conduit's concentration rider was on the next run's very first hit), kill stacks and consumable statuses last until
-- a long rest. Prep ends the concentration and takes off what earlier runs left: HUNTERS_MARK on any creature, and
-- every status on the character that its baseline does not have. The baseline is the character's statuses at its
-- first prep in this game session (gear off, before any run), so what the passives and the save give stays.
G.CARRY_STATUSES = { "HUNTERS_MARK" }
-- the game ends a concentration by this status (its story procedure PROC_GLO_BreakConcentration does the same)
G.BREAK_CONCENTRATION = "AI_HELPER_BREAKCONCENTRATION"
-- engine helpers that come and go on their own and say nothing about the sheet
G.TECHNICAL_STATUS = { "^AI_HELPER", "TECHNICAL" }
function G.technicalStatus(st)
  for _, pat in ipairs(G.TECHNICAL_STATUS) do if tostring(st):find(pat) then return true end end
  return false
end
-- the spell the character concentrates on, or nil
function G.concentration(u)
  local e = ent(u)
  local id = e and try(function() return e.Concentration.SpellId.Prototype end)
  if id == nil or id == "" then return nil end
  return id
end
function G.breakConcentration(u)
  local was = G.concentration(u)
  pcall(Osi.ApplyStatus, u, G.BREAK_CONCENTRATION, 0.1, 1, u)
  return was
end
-- -> { concentration = spell or nil, removed = { "STATUS on who" }, baseline = n }
function G.removeCarryOver(u)
  local me = uuid(u)
  local out = { concentration = G.breakConcentration(u), removed = {} }
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerCharacter") or {}) do
    local c = try(function() return e.Uuid.EntityUuid end)
    for _, st in ipairs(c and G.CARRY_STATUSES or {}) do
      if try(Osi.HasActiveStatus, c, st) == 1 then
        pcall(Osi.RemoveStatus, c, st, "")
        out.removed[#out.removed + 1] = st .. " on " .. (c == me and "the character" or c)
      end
    end
  end
  G.baseStatuses = G.baseStatuses or {}
  if not G.baseStatuses[me] then
    local base = {}
    for st in pairs(G.statusSet(u)) do if not G.technicalStatus(st) then base[st] = true end end
    G.baseStatuses[me] = base
  end
  local base = G.baseStatuses[me]
  for st in pairs(G.statusSet(u)) do
    if not base[st] and not G.technicalStatus(st) then
      pcall(Osi.RemoveStatus, u, st, "")
      out.removed[#out.removed + 1] = st .. " on the character"
    end
  end
  table.sort(out.removed)
  out.baseline = 0
  for _ in pairs(base) do out.baseline = out.baseline + 1 end
  return out
end

-- ------------------------------------------------------------------------------------------------ boosts
-- The boosts on a creature as "Type(params)" text, or nil when the container cannot be read. BoostsContainer maps a
-- boost type to the boost entities of that type; each has its BoostInfo (the boost's name and its parameters).
local function boostText(b, ty)
  local txt = try(function()
    local P = b.BoostInfo.Params
    return tostring(P.Boost) .. "(" .. tostring(P.Params) .. ")"
  end)
  return txt or tostring(try(function() return b.BoostInfo.Type end) or ty)
end
function G.boostList(u)
  local e = ent(u)
  local bc = e and try(function() return e.BoostsContainer.Boosts end)
  if not bc then return nil end
  local out = {}
  for ty, list in pairs(bc) do
    -- either { [type] = { entity, ... } } or { { Type = type, Boosts = { entity, ... } }, ... }
    local t2, l2 = ty, list
    if type(ty) == "number" and try(function() return list.Boosts end) then t2, l2 = list.Type, list.Boosts end
    for _, b in ipairs(l2 or {}) do out[#out + 1] = boostText(b, t2) end
  end
  table.sort(out)
  return out
end
local function normBoost(s) return (tostring(s or ""):lower():gsub("%s", "")) end
-- Is a boost given as "Type(params)" among the boosts read? A boost read without its parameters counts by its type.
function G.hasBoost(list, want)
  local w = normBoost(want)
  local wtype = w:match("^([%w_]+)")
  for _, b in ipairs(list or {}) do
    local n = normBoost(b)
    if n == w or (not n:find("(", 1, true) and n == wtype) then return true end
  end
  return false
end

-- ------------------------------------------------------------------------------------------------ toggled passives
-- A toggled passive (Great Weapon Master / Sharpshooter "All In": -5 to hit, +10 damage) is on or off per character.
-- The respecced test characters had them off while the model counted them on: no hit carried the +10. Prep puts each
-- one the spec names (spec.toggles = { PassiveId = true | false }, the state the model assumes) in that state and the
-- run puts the character's own state back when it ends. The state is the passive's ToggledOn field (read back in game
-- once: ToggledOn = true after AddPassive); Osi.TogglePassive flips it, and where it is missing the field is written.
local function passiveEntry(u, id)
  local e = ent(u)
  for _, p in ipairs(e and try(function() return e.PassiveContainer.Passives end) or {}) do
    if try(function() return p.Passive.PassiveId end) == id then return p end
  end
  return nil
end
-- true / false, or nil when the character lacks the passive or the field cannot be read
function G.toggleState(u, id)
  local p = passiveEntry(u, id)
  if not p then return nil end
  local v = try(function() return p.Passive.ToggledOn end)
  if v == nil then return nil end
  return v == true
end
local function flip(u, id, on)
  if pcall(Osi.TogglePassive, u, id) then return "TogglePassive" end
  local p = passiveEntry(u, id)
  if p and pcall(function() p.Passive.ToggledOn = on; p:Replicate("Passive") end) then return "ToggledOn written" end
  return "no way to toggle"
end
-- -> { [id] = { want, before, method } }; the read back is the setup check's
function G.setToggles(u, want)
  local key = uuid(u)
  G.savedToggles = G.savedToggles or {}
  G.savedToggles[key] = G.savedToggles[key] or {}
  local saved, out = G.savedToggles[key], {}
  for id, on in pairs(want or {}) do
    local before = G.toggleState(u, id)
    if saved[id] == nil and before ~= nil then saved[id] = before end
    local rec = { want = on, before = before }
    if before ~= nil and before ~= on then rec.method = flip(u, id, on) end
    out[id] = rec
  end
  return out
end
function G.togglesRestore()
  local n = 0
  for key, saved in pairs(G.savedToggles or {}) do
    for id, was in pairs(saved) do
      local now_ = G.toggleState(key, id)
      if now_ ~= nil and now_ ~= was then flip(key, id, was); n = n + 1 end
    end
  end
  G.savedToggles = nil
  return n
end

-- ------------------------------------------------------------------------------------------------ critical hits
-- No hit of the pilot was a critical one. A creature carrying CriticalHit(...,Never) (a passive, a status or a boost)
-- cannot be critically hit; spawned enemies are cleared of such passives and statuses, and the setup check reads them.
local function blocksCrit(s)
  s = tostring(s or "")
  return s:find("CriticalHit%(") ~= nil and s:find("Never", 1, true) ~= nil
end
-- -> { { kind = "passive" | "status" | "boost", id } }
function G.critBlockers(d)
  local out = {}
  local e = ent(d)
  for _, p in ipairs(e and try(function() return e.PassiveContainer.Passives end) or {}) do
    local id = try(function() return p.Passive.PassiveId end)
    local st = id and try(Ext.Stats.Get, id)
    if st and blocksCrit(try(function() return st.Boosts end)) then out[#out + 1] = { kind = "passive", id = id } end
  end
  for id in pairs(G.statusSet(d)) do
    local st = try(Ext.Stats.Get, id)
    if st and blocksCrit(try(function() return st.Boosts end)) then out[#out + 1] = { kind = "status", id = id } end
  end
  for _, b in ipairs(G.boostList(d) or {}) do
    if blocksCrit(b) then out[#out + 1] = { kind = "boost", id = b } end
  end
  return out
end
-- removes what it can (passives, statuses) -> { blockers before, removed }
function G.makeCritable(d)
  local found, removed = G.critBlockers(d), {}
  for _, b in ipairs(found) do
    if b.kind == "passive" and pcall(Osi.RemovePassive, d, b.id) then removed[#removed + 1] = b.kind .. " " .. b.id end
    if b.kind == "status" and pcall(Osi.RemoveStatus, d, b.id, "") then removed[#removed + 1] = b.kind .. " " .. b.id end
  end
  return { found = found, removed = removed }
end
-- prep, last part: the bare sheet is read, then the set goes on, the fixed statuses, full resources
function G.prepItems(u, spec, gen)
  G.results.bare = G.sheet(u)
  equipAll(u, spec.items or {}, 1, function()
    for _, st in ipairs(spec.statuses or {}) do pcall(Osi.ApplyStatus, u, st, -1, 1, u); note("status %s", st) end
    if not G.manualPrep then G.results.toggles = G.setToggles(u, spec.toggles) end
    wait(G.SETTLE_MS, function()
      if G.prepGen ~= gen then return end
      G.refill(u, "long")
      pcall(Osi.SetHitpointsPercentage, u, 100)
      G.unencumber(u, false)
      G.results.after = G.sheet(u)
      G.status = "prepped"
      G.dump()
    end)
  end)
end

-- ------------------------------------------------------------------------------------------------ reactions
-- A reaction the game asks about ("Use reaction?" for Destructive Wrath, Hellish Rebuke, Shield, smites...) stops a
-- scripted turn until someone answers. Scripted runs therefore set every party character's reactions so the game
-- never asks: each reaction either fires on its own ("auto") or not at all ("never"). The default is "never": the
-- test character's own reactions (racial ones such as Hellish Rebuke, tadpole powers, its own class and items) are
-- not part of either set. A plan names the reactions it compares in plan.reactions = { Interrupt_X = "auto" }
-- (plan.py lists the ones the build and the set grant), so both sets of a pair run with the same answers. The
-- player's own settings are saved first and put back when the run ends, aborts or fails: reactions are the player's
-- choice whenever a person has control, so manual runs never touch them.
-- Interrupt preference flags: "Enabled" = may fire, "Ask" = the game asks first.
local POLICY_FLAGS = { auto = { "Enabled" }, never = {}, ask = { "Ask", "Enabled" } }
function G.reactionFlags(policy) return POLICY_FLAGS[policy] or POLICY_FLAGS.never end
function G.reactionPolicy(name, plan)
  local p = plan and plan.reactions and plan.reactions[name]
  if p and POLICY_FLAGS[p] then return p end
  return (plan and POLICY_FLAGS[plan.reactions_default or ""] and plan.reactions_default) or "never"
end
-- "InterruptInteractionTypes(Ask,Enabled)" -> { "Ask", "Enabled" }
function G.flagsFromString(s)
  local inner = tostring(s):match("%((.*)%)") or ""
  local out = {}
  for f in inner:gmatch("[%a_]+") do out[#out + 1] = f end
  return out
end
local function prefsOf(u)
  local e = ent(u)
  return e, e and try(function() return e.InterruptPreferences.Preferences end)
end
-- { Interrupt_X = { "Ask", "Enabled" }, ... } of one character
function G.reactionsOf(u)
  local _, P = prefsOf(u)
  local out = {}
  for k, v in pairs(P or {}) do out[k] = G.flagsFromString(v) end
  return out
end
-- Lists the interrupts the character can use, read from the preference map, the interrupt container (class, racial,
-- tadpole and item interrupts) and Interrupt_ entries in the spell book. A name missing from the preference map would
-- fire with the game's default, so the policy is written for each name found.
function G.knownInterrupts(u)
  local e, P = prefsOf(u)
  local out, seen = {}, {}
  local function add(n)
    if type(n) == "string" and n ~= "" and not seen[n] then seen[n] = true; out[#out + 1] = n end
  end
  for k in pairs(P or {}) do add(k) end
  for _, x in ipairs(e and try(function() return e.InterruptContainer.Interrupts end) or {}) do
    add(try(function() return x.InterruptData.Interrupt end) or try(function() return x.Data.Interrupt end))
  end
  for _, s in ipairs(e and try(function() return e.SpellBook.Spells end) or {}) do
    local id = try(function() return s.Id.Prototype end)
    if type(id) == "string" and id:match("^Interrupt_") then add(id) end
  end
  table.sort(out)
  return out
end
local function setPrefs(u, want)
  local e, P = prefsOf(u)
  if not P then return false end
  for k, flags in pairs(want) do pcall(function() P[k] = flags end) end
  pcall(function() e:Replicate("InterruptPreferences") end)
  return true
end
local function sameFlags(a, b)
  local s = {}
  for _, f in ipairs(a) do s[f] = true end
  for _, f in ipairs(b) do if not s[f] then return false end; s[f] = nil end
  return next(s) == nil
end
-- The party: DB_Players plus every player character the database misses (a companion made a player by
-- Osi.MakePlayer, as in test saves, is not in it; left out, it failed the arena check as a stranger and was never
-- parked)
local function partyMembers()
  local out, seen = {}, {}
  for _, row in ipairs(try(function() return Osi.DB_Players:Get(nil) end) or {}) do
    local u = uuid(row[1])
    if u and not seen[u] then seen[u] = true; out[#out + 1] = u end
  end
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerCharacter") or {}) do
    local u = try(function() return e.Uuid.EntityUuid end)
    if u and not seen[u] and try(Osi.IsPlayer, u) == 1 then seen[u] = true; out[#out + 1] = u end
  end
  return out
end
G.partyMembers = partyMembers
-- Scripted runs only. Saves each character's own settings once (a second call keeps the first copy), applies the
-- plan's policy and reads it back. Returns { [uuid] = { name, reactions = { Interrupt_X = policy }, verified } }.
function G.reactionsApply(plan, chars)
  G.savedReactions = G.savedReactions or {}
  local report = {}
  for _, u in ipairs(chars or partyMembers()) do
    local own = G.reactionsOf(u)
    if G.savedReactions[u] == nil then G.savedReactions[u] = own end
    local want, pol = {}, {}
    for _, k in ipairs(G.knownInterrupts(u)) do
      pol[k] = G.reactionPolicy(k, plan)
      want[k] = G.reactionFlags(pol[k])
    end
    setPrefs(u, want)
    local back, ok, uncovered = G.reactionsOf(u), true, {}
    for k, flags in pairs(want) do
      if not sameFlags(back[k] or {}, flags) then
        ok = false
        uncovered[#uncovered + 1] = k
      end
    end
    table.sort(uncovered)
    report[u] = { name = name(u), reactions = pol, verified = ok, uncovered = uncovered }
  end
  return report
end
function G.reactionsRestore()
  local n = 0
  for u, own in pairs(G.savedReactions or {}) do
    if setPrefs(u, own) then n = n + 1 end
  end
  G.savedReactions = nil
  return n
end
-- Reaction prompts open for the character right now: { { interrupt = "Interrupt_X", cast = guid }, ... }
function G.pendingReactions(u)
  local me, out = uuid(u), {}
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "InterruptActionState") or {}) do
    local st = try(function() return e.InterruptActionState end)
    for _, a in ipairs(st and st.Actions or {}) do
      local obs = try(function() return a.Observer.Uuid.EntityUuid end)
      if obs == me then
        out[#out + 1] = { interrupt = try(function() return a.Interrupt.InterruptData.Interrupt end),
          cast = tostring(st.SpellCastGuid) }
      end
    end
  end
  return out
end
-- The in-turn guard. Scripted turns only: a prompt the policy did not cover is logged as a miss (so the reaction list
-- can be completed) and ends the run, because the engine offers no safe way to answer it (writing the server's
-- interrupt decision crashed the game). When a person has control it does nothing.
function G.reactionGuard(F)
  if not F or F.manual then return nil end
  local open = G.pendingReactions(F.char)
  if #open == 0 then return nil end
  G.results.reaction_misses = G.results.reaction_misses or {}
  for _, p in ipairs(open) do
    G.results.reaction_misses[#G.results.reaction_misses + 1] = p
    note("reaction prompt not covered by the policy: %s", tostring(p.interrupt))
  end
  return open[1].interrupt
end

-- ------------------------------------------------------------------------------------------------ the rest of the party
-- Solo runs: the other party members are moved 40 m away and kept out of the fight; put back when the run ends.
function G.parkOthers(u, spot, keep)
  G.parked = G.parked or {}
  local ox, oy, oz
  if u then ox, oy, oz = Osi.GetPosition(u) end
  if spot then ox, oy, oz = spot[1] - 40, spot[2], spot[3] end
  if not ox then return 0 end
  local n = 0
  for _, m in ipairs(partyMembers()) do
    if m ~= uuid(u) and not (keep and keep[m]) then
      local x, y, z = Osi.FindValidPosition(ox + 40, oy, oz, 20, m, 0)
      if x then pcall(Osi.TeleportToPosition, m, x, y, z, "", 0, 0, 0, 0, 1) end
      pcall(Osi.SetCanJoinCombat, m, 0)
      G.parked[m] = true
      n = n + 1
    end
  end
  return n
end
function G.unparkOthers()
  for m in pairs(G.parked or {}) do pcall(Osi.SetCanJoinCombat, m, 1) end
  G.parked = nil
end

-- Bystanders: living characters outside the party that stand in a lane (two stood at one lane's start in the test
-- saves) are moved by engine to spot (a lanes entry's npc_park, away from every lane) for the lanes' run; where each
-- stood is kept in G.movedNpcs and G.npcsBack puts them back after the last lane, also when the run is aborted. Party
-- members are parked instead (G.parkOthers); enemies and summons of earlier runs are removed by G.clearLeftovers.
-- arenas = { A, ... } (centre, radius); margin metres around each radius. -> { { uuid, name, from = {x, y, z} } }
function G.npcsAway(arenas, spot, margin)
  G.movedNpcs = G.movedNpcs or {}
  local party, out = {}, {}
  for _, m in ipairs(partyMembers()) do party[m] = true end
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerCharacter") or {}) do
    local u = try(function() return e.Uuid.EntityUuid end)
    if u and not party[u] and not G.movedNpcs[u] and not (G.spawned or {})[u] and try(Osi.IsSummon, u) ~= 1
      and try(Osi.IsDead, u) == 0 then
      local x, y, z = Osi.GetPosition(u)
      local near = false
      for _, A in ipairs(arenas) do
        if x and math.sqrt((x - A.center[1]) ^ 2 + (z - A.center[3]) ^ 2) <= A.radius + (margin or 0) then near = true end
      end
      if near then
        local px, py, pz = Osi.FindValidPosition(spot[1], spot[2], spot[3], 20, u, 0)
        if px then
          pcall(Osi.TeleportToPosition, u, px, py, pz, "", 0, 0, 0, 0, 1)
          G.movedNpcs[u] = { x, y, z }
          out[#out + 1] = { uuid = u, name = name(u), from = { x, y, z } }
        end
      end
    end
  end
  return out
end
function G.npcsBack()
  local n = 0
  for u, p in pairs(G.movedNpcs or {}) do
    pcall(Osi.TeleportToPosition, u, p[1], p[2], p[3], "", 0, 0, 0, 0, 1)
    n = n + 1
  end
  G.movedNpcs = nil
  return n
end

-- ------------------------------------------------------------------------------------------------ enemies
-- E = {template, ac, save, atk, dmg, dc, hp}. Stats are forced, then VERIFIED in G.results.enemies (a difficulty
-- setting or the template could change them).
-- A creature made by CreateAt has no stats and no equipment yet in the frame it was made: its abilities read 0, so
-- "set every ability to 10" added +10 to each (the pilot's enemy had STR 26) and its weapon stayed on (+8 to hit and
-- damage beyond the model's enemy). Abilities and gear are forced once the stats are there (G.enemyReady).
G.ENEMY_READY_TRIES = 20
function G.enemyReady(d)
  local cur = abilities(d)
  return (cur.Strength or 0) > 0 and (cur.Dexterity or 0) > 0
end
local function forceEnemy(d, E, tries)
  tries = tries or 0
  if not G.enemyReady(d) then
    if tries < G.ENEMY_READY_TRIES then wait(100, function() forceEnemy(d, E, tries + 1) end) end
    return
  end
  for _, it in pairs(G.equipped(d)) do pcall(Osi.Unequip, d, it) end
  local cur = abilities(d)
  for _, n in ipairs(ABIL) do
    local dd = 10 - (cur[n] or 10)
    if dd ~= 0 then pcall(Osi.AddBoosts, d, string.format("Ability(%s,%d)", n, dd), CAUSE, d) end
  end
  wait(300, function()
    local e = ent(d)
    local ac = e and try(function() return e.Resistances.AC end) or 10
    local prof = e and try(function() return e.Stats.ProficiencyBonus end) or 2
    local b = { string.format("AC(%d)", E.ac - ac), string.format("RollBonus(SavingThrow,%d)", E.save),
      string.format("RollBonus(Attack,%d)", E.atk - prof), string.format("DamageBonus(%d)", E.dmg - 1),
      string.format("SpellSaveDC(%d)", E.dc - (8 + prof)), string.format("IncreaseMaxHP(%d)", E.hp) }
    for _, x in ipairs(b) do
      if not x:match("%(%-?0%)$") and not x:match(",0%)$") then pcall(Osi.AddBoosts, d, x, CAUSE, d) end
    end
    pcall(function()
      local r = e.Resistances.Resistances
      for i = 1, #r do r[i] = "None" end
      e:Replicate("Resistances")
    end)
    -- a creature that cannot be critically hit takes no critical hits from either set: what blocks them is taken off
    G.enemyCrit = G.enemyCrit or {}
    G.enemyCrit[uuid(d)] = G.makeCritable(d)
    wait(300, function() pcall(Osi.SetHitpointsPercentage, d, 100) end)
  end)
end

function G.spawnEnemies(list, E, faction)
  local out = {}
  for _, p in ipairs(list) do
    local d = try(Osi.CreateAt, E.template, p[1], p[2], p[3], 0, 0, "")
    if d then
      out[#out + 1] = d
      G.spawned = G.spawned or {}
      G.spawned[uuid(d)] = true
      if faction then pcall(Osi.SetFaction, d, faction) end
      forceEnemy(d, E)
    else
      note("enemy spawn failed at %.1f %.1f", p[1], p[3])
    end
  end
  return out
end

-- ------------------------------------------------------------------------------------------------ cleanup
-- In the pilot re-run the enemies of earlier runs outlived their delete request (RequestDelete did nothing to a
-- creature made by CreateAt): they stayed in the fight, hit the next run's character (it went down, and its damage
-- taken doubled) and soaked its area spells, while the arena check skipped them as already deleted. A summon the
-- character left behind (Spiritual Weapon) failed the next run's arena check. Removal now asks for the delete of a
-- temporary creature and the plain delete, then kills whatever still stands; the arena check counts every living
-- creature outside the party again.
local NULL_GUID = "NULL_00000000-0000-0000-0000-000000000000"
G.CLEANUP_MS = 1500
function G.removeCreature(d)
  pcall(Osi.RequestDeleteTemporary, d)
  pcall(Osi.RequestDelete, d)
end
local function standing(u) return try(Osi.IsDead, u) == 0 end
function G.summonOwner(u)
  local e = ent(u)
  return e and (try(function() return e.IsSummon.Owner.Uuid.EntityUuid end)
    or try(function() return e.IsSummon.Summoner.Uuid.EntityUuid end))
end
local function inArena(u, A)
  if not A then return false end
  local x, _, z = Osi.GetPosition(u)
  return x ~= nil and math.sqrt((x - A.center[1]) ^ 2 + (z - A.center[3]) ^ 2) <= A.radius
end
-- living summons of the test character, and any living summon inside the arena
function G.leftoverSummons(me, A)
  local out = {}
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerCharacter") or {}) do
    local u = try(function() return e.Uuid.EntityUuid end)
    if u and u ~= me and try(Osi.IsSummon, u) == 1 and standing(u) and (G.summonOwner(u) == me or inArena(u, A)) then
      out[#out + 1] = u
    end
  end
  return out
end
-- Removes the enemies earlier runs spawned and the character's leftover summons; after CLEANUP_MS kills any of them
-- still standing. cb(report): { removed = n, killed = { names } }.
function G.clearLeftovers(me, A, cb)
  local list = {}
  for d in pairs(G.spawned or {}) do if try(Osi.IsDead, d) ~= nil then list[#list + 1] = d end end
  for _, d in ipairs(G.leftoverSummons(me, A)) do list[#list + 1] = d end
  for _, d in ipairs(list) do G.removeCreature(d) end
  wait(G.CLEANUP_MS, function()
    local killed = {}
    for _, d in ipairs(list) do
      if standing(d) then
        pcall(Osi.Die, d, 0, NULL_GUID, 0, 0)
        killed[#killed + 1] = name(d)
      end
    end
    for d in pairs(G.spawned or {}) do if try(Osi.IsDead, d) == nil then G.spawned[d] = nil end end
    if cb then cb({ removed = #list, killed = killed }) end
  end)
end

function G.enemyReport(list)
  local out = {}
  for _, d in ipairs(list) do
    local e = ent(d)
    local res = {}
    for i, v in ipairs(e and try(function() return e.Resistances.Resistances end) or {}) do res[i] = tostring(v) end
    -- what the template carries (stats, passives, statuses, boosts) and what could block a critical hit
    local passives, statuses = {}, {}
    for _, p in ipairs(e and try(function() return e.PassiveContainer.Passives end) or {}) do
      passives[#passives + 1] = try(function() return p.Passive.PassiveId end)
    end
    for st in pairs(G.statusSet(d)) do statuses[#statuses + 1] = st end
    table.sort(statuses)
    out[#out + 1] = { uuid = d, ac = e and try(function() return e.Resistances.AC end), hp = try(Osi.GetMaxHitpoints, d),
      abilities = abilities(d), prof = e and try(function() return e.Stats.ProficiencyBonus end), res = res,
      stats = try(Osi.GetStatString, d), passives = passives, statuses = statuses, boosts = G.boostList(d),
      crit = (G.enemyCrit or {})[uuid(d)], crit_blockers = G.critBlockers(d) }
  end
  return out
end

-- ------------------------------------------------------------------------------------------------ setup check
-- The character's setup must be the spec's, exactly: one mismatch fails the run with the field named. Checked by
-- engine at the fight's start (and the gear, passives and buffs again at its end). Abilities, max HP and proficiency
-- are read from the bare sheet prep recorded before the items went on, so an item's own boosts are not a mismatch;
-- spell slots and class resources as the fight starts. -> { checked = n, mismatches = { {field, want, got} } }
G.ABIL_FULL = { STR = "Strength", DEX = "Dexterity", CON = "Constitution", INT = "Intelligence", WIS = "Wisdom",
  CHA = "Charisma" }
-- The character's classes as the game has them: { [class] = level }, { [class] = subclass } (ClassDescription names)
function G.classesOf(u)
  local e = ent(u)
  local lv, sub = {}, {}
  for _, c in ipairs(e and try(function() return e.Classes.Classes end) or {}) do
    local cd = try(Ext.StaticData.Get, c.ClassUUID, "ClassDescription")
    local sd = try(Ext.StaticData.Get, c.SubClassUUID, "ClassDescription")
    local n = cd and cd.Name or tostring(c.ClassUUID)
    lv[n] = (lv[n] or 0) + (c.Level or 0)
    if sd and sd.Name then sub[n] = sd.Name end
  end
  return lv, sub
end
-- The feats the character took when it levelled up (names), or nil when the game does not show them.
function G.featsOf(u)
  local e = ent(u)
  local ups = e and try(function() return e.LevelUp.LevelUps end)
  if not ups then return nil end
  local out = {}
  for _, l in ipairs(ups) do
    local f = try(function() return l.Feat end)
    if f and tostring(f) ~= "00000000-0000-0000-0000-000000000000" then
      local fd = try(Ext.StaticData.Get, f, "Feat")
      out[#out + 1] = fd and fd.Name or tostring(f)
    end
  end
  return out
end
local function normName(s) return (tostring(s or ""):lower():gsub("[^%a]", "")) end
-- ability improvements are named differently by the build and the game; they show in the abilities anyway
local function isAbilityFeat(n) return n:find("^abilityimprovement") or n:find("^abilityscore") or n == "asi" end
local function featCounts(list)
  local out = {}
  for _, f in ipairs(list or {}) do
    local n = normName(f)
    if not isAbilityFeat(n) then out[n] = (out[n] or 0) + 1 end
  end
  return out
end
function G.setupCheck(F, spec, phase, extra)
  local u = F.char
  local out = { checked = 0, mismatches = {} }
  local function cmp(field, want, got)
    out.checked = out.checked + 1
    if want ~= got then out.mismatches[#out.mismatches + 1] = { field = field, want = want, got = got } end
  end
  local worn, eq = {}, G.equipped(u)
  for slot, it in pairs(eq) do worn[slot] = try(Osi.GetStatString, it) end
  for _, it in ipairs(spec.items or {}) do
    if it.use then
      if phase == "start" then
        local got
        for _, r in ipairs(((G.results.prep or {}).items) or {}) do if r.stats == it.stats then got = r.got end end
        cmp("elixir " .. tostring(it.stats), "used", got)
      end
    else
      cmp("item " .. tostring(it.slot), it.stats, worn[it.slot])
      -- proficiency as the game judges it (its "not proficient" warning and the attack bonus it shows follow it): an
      -- item the build is proficient with must not be one the game calls non-proficient
      if phase == "start" and it.proficient == true then
        local item = eq[it.slot]
        cmp("proficient with " .. tostring(it.stats), true, item ~= nil and try(Osi.IsProficientWith, u, item) == 1)
      end
    end
  end
  if phase == "start" and spec.real_respec then
    -- a real respec: the character's own classes, subclasses and feats are the build's
    local lv, sub = G.classesOf(u)
    for cls, n in pairs(spec.class_levels or {}) do cmp("class " .. cls .. " level", n, lv[cls] or 0) end
    for cls, n in pairs(lv) do
      if not (spec.class_levels or {})[cls] then cmp("class " .. cls .. " level (not in the build)", 0, n) end
    end
    for cls, want in pairs(spec.subclass_names or {}) do cmp("subclass of " .. cls, want, sub[cls]) end
    local feats = G.featsOf(u)
    if feats then
      local have, want = featCounts(feats), featCounts(spec.feats)
      for n, k in pairs(want) do cmp("feat " .. n, k, have[n] or 0) end
      for n, k in pairs(have) do if not want[n] then cmp("feat " .. n .. " (not in the build)", 0, k) end end
    else
      out.notes = { "feats not readable from the character: checked through their passives only" }
    end
  end
  for _, p in ipairs(spec.passives_add or {}) do cmp("passive " .. p, true, try(Osi.HasPassive, u, p) == 1) end
  for _, p in ipairs(spec.passives_remove or {}) do cmp("passive removed " .. p, false, try(Osi.HasPassive, u, p) == 1) end
  for _, st in ipairs(spec.statuses or {}) do cmp("status " .. st, true, try(Osi.HasActiveStatus, u, st) == 1) end
  for _, st in ipairs((extra and extra.buffs) or {}) do cmp("buff " .. st, true, try(Osi.HasActiveStatus, u, st) == 1) end
  if phase ~= "start" then return out end
  local book = {}
  local e = ent(u)
  for _, sp in ipairs(e and try(function() return e.SpellBook.Spells end) or {}) do
    local id = try(function() return sp.Id.Prototype end)
    if id then book[id] = true end
  end
  if spec.real_respec then
    -- the respec's own spell book: every spell the round plan casts (an upcast is the same spell in the book)
    for _, sp in ipairs(spec.spells_plan or {}) do cmp("spell " .. sp, true, book[sp] == true) end
  else
    for _, sp in ipairs(spec.spells_add or {}) do cmp("spell " .. sp, true, book[sp] == true) end
  end
  local bare = (G.results.prep or {}).bare or {}
  local sh = spec.sheet or {}
  for short, want in pairs(sh.abilities or {}) do
    cmp("ability " .. short, want, (bare.abilities or {})[G.ABIL_FULL[short] or short])
  end
  if sh.hp then cmp("max HP", sh.hp, bare.hp) end
  if sh.prof then cmp("proficiency bonus", sh.prof, bare.prof) end
  -- slots and class resources as the fight starts (their boosts can land after the bare sheet was read), plus what
  -- the worn items add (spec.item_resources: a boost, or a status an item puts on)
  local now_ = G.sheet(u)
  local fromItems = {}
  for _, r in ipairs(spec.item_resources or {}) do
    local k = r.kind .. ":" .. tostring(r.level or 0)
    fromItems[k] = (fromItems[k] or 0) + r.n
  end
  for lv = 1, 9 do
    local want = (spec.slots and spec.slots[tostring(lv)] or 0) + (fromItems["SpellSlot:" .. lv] or 0)
    local got = (now_.slots or {})[tostring(lv)] or 0
    if want ~= 0 or got ~= 0 then cmp("spell slots L" .. lv, want, got) end
  end
  local seen = {}
  for _, r in ipairs(spec.resources or {}) do
    local k = r.kind .. ":" .. tostring(r.level or 0)
    seen[k] = true
    cmp("resource " .. r.kind, r.n + (fromItems[k] or 0), (now_.resources or {})[k])
  end
  for _, r in ipairs(spec.item_resources or {}) do
    local k = r.kind .. ":" .. tostring(r.level or 0)
    if r.kind ~= "SpellSlot" and not seen[k] then
      seen[k] = true
      cmp("resource " .. r.kind .. " (from items)", fromItems[k], (now_.resources or {})[k])
    end
  end
  if extra then
    cmp("not encumbered", 0, #(extra.encumbered or {}))
    if extra.reactions ~= nil then cmp("reaction policy applied", true, extra.reactions) end
    for i, d in ipairs(extra.enemies or {}) do
      local E = extra.E or {}
      local de = ent(d)
      cmp("enemy " .. i .. " AC", E.ac, de and try(function() return de.Resistances.AC end))
      cmp("enemy " .. i .. " hostile to the character", 1, try(Osi.IsEnemy, F.char, d))
      -- the model's enemy: every ability 10, unarmed (its attack and damage come from the forced boosts alone)
      local ab = abilities(d)
      for _, n in ipairs(ABIL) do cmp("enemy " .. i .. " " .. n, 10, ab[n]) end
      local gear = 0
      for _ in pairs(G.equipped(d)) do gear = gear + 1 end
      cmp("enemy " .. i .. " items worn", 0, gear)
      cmp("enemy " .. i .. " damage scale", extra.scale, E.damage_scale)
    end
    for m in pairs(extra.parked or {}) do
      cmp("party member parked out of combat " .. tostring(m):sub(-12), 0, try(Osi.IsInCombat, m) or 0)
    end
  end
  G.effectChecks(F, spec, cmp, book, extra, out)
  return out
end

-- The setup check's effect fields (start of the fight): are the effects the model credits there? The toggled passives
-- in the model's state, every worn item's equip passives, equip statuses and unconditional boosts, the elixir's
-- statuses, the weapons' dice as their sheet rows have them, the item spells in the book and ready; nothing carried
-- over from an earlier run (no concentration, no status outside the baseline and what the set and the buffs put on);
-- enemies that can be critically hit and carry no status. All of it is read before round 1, so a mismatch can stop
-- the run before it is fought.
function G.effectChecks(F, spec, cmp, book, extra, out)
  local u = F.char
  local function note_(s) out.notes = out.notes or {}; out.notes[#out.notes + 1] = s end
  for id, want in pairs(spec.toggles or {}) do cmp("toggle " .. id, want, G.toggleState(u, id)) end
  for _, x in ipairs(spec.item_passives or {}) do
    cmp("item passive " .. x.passive, true, try(Osi.HasPassive, u, x.passive) == 1)
  end
  local allowed = {}
  for _, x in ipairs(spec.item_statuses or {}) do
    allowed[x.status] = true
    cmp("item status " .. x.status, true, try(Osi.HasActiveStatus, u, x.status) == 1)
  end
  for _, st in ipairs(spec.item_statuses_allowed or {}) do allowed[st] = true end
  for _, st in ipairs(spec.statuses or {}) do allowed[st] = true end
  for _, st in ipairs((extra and extra.buffs) or {}) do allowed[st] = true end
  for _, r in ipairs(((G.results.prep or {}).items) or {}) do
    if r.got == "used" and r.statuses then
      cmp("elixir " .. tostring(r.stats) .. " gave a status", true, #r.statuses > 0)
      for _, st in ipairs(r.statuses) do
        allowed[st] = true
        cmp("elixir status " .. st, true, try(Osi.HasActiveStatus, u, st) == 1)
      end
    end
  end
  local boosts = G.boostList(u)
  if boosts then
    for _, x in ipairs(spec.item_boosts or {}) do cmp("item boost " .. x.boost, true, G.hasBoost(boosts, x.boost)) end
  elseif spec.item_boosts and #spec.item_boosts > 0 then
    note_("boosts not readable from the character: item boosts not compared")
  end
  local eq = G.equipped(u)
  out.weapons = {}
  for _, it in ipairs(spec.items or {}) do
    if it.weapon and eq[it.slot] then
      local sid = try(Osi.GetStatString, eq[it.slot])
      local st = sid and try(Ext.Stats.Get, sid)
      local dmg = st and try(function() return st.Damage end)
      local vers = st and try(function() return st.VersatileDamage end)
      local typ = st and try(function() return st["Damage Type"] end)
      local itemEnt = ent(eq[it.slot])
      out.weapons[it.slot] = { damage = dmg, versatile = vers, type = typ,
        component = itemEnt and try(function() return Ext.Types.Serialize(itemEnt.Weapon) end) }
      cmp("weapon dice " .. it.slot, it.weapon.dice, (vers ~= nil and vers == it.weapon.dice) and vers or dmg)
      if it.weapon.type then cmp("weapon damage type " .. it.slot, it.weapon.type, typ) end
    end
  end
  for _, a in ipairs(((F.plan or spec.plan or {}).item_actions) or {}) do
    cmp("item spell " .. a.spell .. " in the book", true, (book or {})[a.spell] == true)
    cmp("item spell " .. a.spell .. " ready", false, onCooldown(u, a.spell))
  end
  cmp("no concentration", "none", G.concentration(u) or "none")
  local base = (G.baseStatuses or {})[uuid(u)]
  if base then
    for st in pairs(G.statusSet(u)) do
      if not base[st] and not allowed[st] and not G.technicalStatus(st) then cmp("no carried status " .. st, false, true) end
    end
  else
    note_("no status baseline for the character: carried statuses not compared")
  end
  for i, d in ipairs((extra and extra.enemies) or {}) do
    local bl = G.critBlockers(d)
    local names = {}
    for _, b in ipairs(bl) do names[#names + 1] = b.kind .. " " .. b.id end
    cmp("enemy " .. i .. " can be critically hit", "yes", #bl == 0 and "yes" or table.concat(names, ", "))
    local sts = {}
    for st in pairs(G.statusSet(d)) do if not G.technicalStatus(st) then sts[#sts + 1] = st end end
    table.sort(sts)
    cmp("enemy " .. i .. " statuses at start", "none", #sts == 0 and "none" or table.concat(sts, ", "))
  end
end

-- ------------------------------------------------------------------------------------------------ events
-- Damage log from Osiris AttackedBy (one row per damage type per hit) and the spell log from CastedSpell, registered
-- once per game session (re-loading this file keeps them).
local function onAttacked(def, ownerAtt, att, dtype, amount, cause, _sid)
  if not G.fighting then return end
  G.dmg[#G.dmg + 1] = { r = G.round, t = now() - G.t0, target = uuid(def), source = uuid(att), owner = uuid(ownerAtt),
    type = dtype, amount = amount, cause = cause }
end
local function onCast(caster, spell)
  if not G.fighting then return end
  local R = G.rounds[#G.rounds]
  if R then R.casts[#R.casts + 1] = { who = uuid(caster), spell = spell } end
end
-- The engine's refusals: CastSpellFailed names the caster and the spell (no reason), ReactionInterruptUsed the
-- creature that reacted. In the pilot re-run 39 of the character's 40 refused casts came right after an enemy's
-- Attack of Opportunity: the scripted cast walked the character to a new spot, the reaction interrupted the walk and
-- the engine dropped the cast.
local function onCastFailed(caster, spell)
  if not G.fighting then return end
  local R = G.rounds[#G.rounds]
  if R then
    R.cast_fails = R.cast_fails or {}
    R.cast_fails[#R.cast_fails + 1] = { who = uuid(caster), spell = spell, t = now() - G.t0 }
  end
end
local function onReaction(who, interrupt)
  if not G.fighting then return end
  local R = G.rounds[#G.rounds]
  if R then
    R.reactions_seen = R.reactions_seen or {}
    R.reactions_seen[#R.reactions_seen + 1] = { who = uuid(who), interrupt = interrupt, t = now() - G.t0 }
  end
end
-- Who a fight's record follows: the character, its summons and the run's enemies.
function G.member(F, u)
  u = u and uuid(u)
  if not F or not u then return false end
  if u == uuid(F.char) then return "char" end
  for _, d in ipairs(F.enemies or {}) do if uuid(d) == u then return "enemy" end end
  if (F.summons or {})[u] then return "summon" end
  return false
end
-- Statuses put on and taken off the run's creatures (Osiris StatusApplied / StatusRemoved), per round: the riders
-- (HUNTERS_MARK on the boss, DREAD_AMBUSHER on the character) and the conditions are read from them.
local function onStatus(on, obj, status, causee)
  if not G.fighting then return end
  local F = G.F
  if not G.member(F, obj) then return end
  local R = G.rounds[#G.rounds]
  if not R then return end
  R.status_log = R.status_log or {}
  R.status_log[#R.status_log + 1] = { who = uuid(obj), status = status, on = on, cause = causee and uuid(causee),
    t = now() - G.t0 }
end
-- Osiris CriticalHitBy (defender, attack owner, attacker): every critical hit in the fight, per round.
local function onCrit(def, ownerAtt, att)
  if not G.fighting then return end
  local R = G.rounds[#G.rounds]
  if R then
    R.crits = R.crits or {}
    R.crits[#R.crits + 1] = { target = uuid(def), owner = uuid(ownerAtt), source = uuid(att), t = now() - G.t0 }
  end
end
-- One row per hit the run's creatures deal or take (Script Extender DealDamage): spell, the hit's flags (hit / miss /
-- critical), the attack roll where the hit description carries it, damage per type, the target's statuses and the
-- character's concentration at the hit. The field names are read defensively; the first hit's whole description is
-- kept in results.hit_probe so the names can be checked against the game. At most HIT_LOG_MAX rows per run.
G.HIT_LOG_MAX = 3000
local function first(obj, paths)
  for _, path in ipairs(paths) do
    local v = try(function()
      local x = obj
      for k in path:gmatch("[^%.]+") do x = x[k] end
      return x
    end)
    if v ~= nil then return v, path end
  end
  return nil
end
local function flagText(v)
  if type(v) == "table" or type(v) == "userdata" then
    local parts = {}
    for k, x in pairs(v) do parts[#parts + 1] = (type(k) == "number") and tostring(x) or tostring(k) end
    table.sort(parts)
    return table.concat(parts, ",")
  end
  return v ~= nil and tostring(v) or nil
end
function G.hitRow(e)
  local hit = try(function() return e.Hit end) or {}
  local src = first(e, { "Caster.Uuid.EntityUuid", "Hit.Inflicter.Uuid.EntityUuid", "Hit.InflicterOwner.Uuid.EntityUuid" })
  local tgt = first(e, { "Target.Uuid.EntityUuid", "Hit.Target.Uuid.EntityUuid" })
  local flags = flagText(first(hit, { "EffectFlags", "HitFlags", "Flags" }))
  local attack = flagText(first(hit, { "AttackFlags" }))
  local row = { r = G.round, t = now() - G.t0, source = src and uuid(src), target = tgt and uuid(tgt),
    spell = first(e, { "SpellId.Prototype", "Hit.SpellId.Prototype", "SpellId.OriginatorPrototype" }),
    total = first(hit, { "TotalDamageDone", "TotalDamage" }), type = flagText(first(hit, { "DamageType" })),
    flags = flags, attack_flags = attack, attack_type = flagText(first(e, { "AttackType", "Hit.AttackType" })),
    roll = first(hit, { "AttackRoll.Result.NaturalRoll", "AttackRoll.NaturalRoll", "ConditionRoll.NaturalRoll",
      "Roll.NaturalRoll" }),
    roll_total = first(hit, { "AttackRoll.Result.Total", "AttackRoll.Total", "ConditionRoll.Total", "Roll.Total" }),
    advantage = flagText(first(hit, { "AttackRoll.Advantage", "AttackRoll.RollType", "Roll.Advantage" })) }
  local f = tostring(flags or "") .. "," .. tostring(attack or "")
  row.crit = f:find("Critical", 1, true) ~= nil
  row.miss = f:find("Miss", 1, true) ~= nil or f:find("Dodge", 1, true) ~= nil
  row.hit = f:find("Hit", 1, true) ~= nil and not row.miss
  local per = {}
  for _, dmg in ipairs(first(hit, { "DamageList", "Damage.DamageList" }) or {}) do
    per[#per + 1] = { type = tostring(try(function() return dmg.DamageType end)), amount = try(function() return dmg.Amount end) }
  end
  row.damage = per
  return row
end
local function onHit(e)
  if not G.fighting or #G.hits >= G.HIT_LOG_MAX then return end
  local F = G.F
  local row = G.hitRow(e)
  local ms, mt = G.member(F, row.source), G.member(F, row.target)
  if not ms and not mt then return end
  if mt == "enemy" then
    local sts = {}
    for st in pairs(G.statusSet(row.target)) do sts[#sts + 1] = st end
    table.sort(sts)
    row.target_statuses = sts
  end
  row.concentration = G.concentration(F.char)
  G.hits[#G.hits + 1] = row
  if not G.results.hit_probe then G.results.hit_probe = try(function() return Ext.Types.Serialize(e.Hit) end) or "?" end
end
G._onHit = onHit

-- Lanes: an event goes to the lane whose character or enemies it names (to each, when it names both lanes: one
-- lane's spell hitting the other's enemies is a fault both must see); an event that names neither goes to every lane.
function G.lanesFor(who)
  local L = G.LANES
  local out, seen = {}, {}
  for i = 1, who.n or #who do
    local u = who[i] and uuid(who[i])
    for _, id in ipairs(L.order) do
      if u and (L.members[id] or {})[u] and not seen[id] then seen[id] = true; out[#out + 1] = id end
    end
  end
  if #out == 0 then return L.order end
  return out
end
function G.dispatch(fn, who, ...)
  local L = G.LANES
  if not (L and L.on) then return fn(...) end
  for _, id in ipairs(G.lanesFor(who)) do G.inLane(id, fn, ...) end
end
-- Registered once per game session; they call through G._on, so a reloaded file brings its handlers along. Listeners
-- an older version registered check a field this version no longer sets, so they stay silent.
G._on = {
  attacked = function(def, ownerAtt, att, ...)
    G.dispatch(onAttacked, { n = 3, def, att, ownerAtt }, def, ownerAtt, att, ...)
  end,
  cast = function(caster, spell, ...) G.dispatch(onCast, { n = 1, caster }, caster, spell, ...) end,
  failed = function(caster, spell, ...) G.dispatch(onCastFailed, { n = 1, caster }, caster, spell, ...) end,
  reaction = function(who, interrupt, ...) G.dispatch(onReaction, { n = 1, who }, who, interrupt, ...) end,
  status_on = function(obj, status, causee) G.dispatch(onStatus, { n = 2, obj, causee }, true, obj, status, causee) end,
  status_off = function(obj, status, causee) G.dispatch(onStatus, { n = 2, obj, causee }, false, obj, status, causee) end,
  crit = function(def, ownerAtt, att, ...) G.dispatch(onCrit, { n = 3, def, att, ownerAtt }, def, ownerAtt, att, ...) end,
  hit = function(e)
    local who = { n = 2, try(function() return e.Caster.Uuid.EntityUuid end),
      try(function() return e.Target.Uuid.EntityUuid end) }
    G.dispatch(onHit, who, e)
  end,
}
if not G._listeners4 then
  local function on(k) return function(...) pcall(G._on[k], ...) end end
  G._listeners4 = {
    attacked = pcall(Ext.Osiris.RegisterListener, "AttackedBy", 7, "after", on("attacked")),
    cast = pcall(Ext.Osiris.RegisterListener, "CastedSpell", 5, "after", on("cast")),
    failed = pcall(Ext.Osiris.RegisterListener, "CastSpellFailed", 5, "after", on("failed")),
    reaction = pcall(Ext.Osiris.RegisterListener, "ReactionInterruptUsed", 3, "after", on("reaction")),
  }
end
G._listeners = G._listeners4
-- added in version 5: statuses, critical hits, the hit descriptions
if not G._listeners5 then
  local function on(k) return function(...) pcall(G._on[k], ...) end end
  G._listeners5 = {
    status_on = pcall(Ext.Osiris.RegisterListener, "StatusApplied", 4, "after", on("status_on")),
    status_off = pcall(Ext.Osiris.RegisterListener, "StatusRemoved", 4, "after", on("status_off")),
    crit = pcall(Ext.Osiris.RegisterListener, "CriticalHitBy", 4, "after", on("crit")),
    hit = pcall(function() return Ext.Events.DealDamage:Subscribe(on("hit")) end),
  }
end

-- ------------------------------------------------------------------------------------------------ fight
local function activeTurn(u)
  local e = ent(u)
  return e and try(function() return e.TurnBased.IsActiveCombatTurn end) == true
end
local function casting(u)
  local e = ent(u)
  return e and try(function() return e.SpellCastIsCasting end) ~= nil
end
function G.endTurn(u)
  local e = ent(u)
  pcall(function() e.TurnBased.RequestedEndTurn = true; e:Replicate("TurnBased") end)
  pcall(function() local q = Ext.System.ServerTurnOrder.EndTurn; q[#q + 1] = e end)
  pcall(Osi.EndTurn, u)
end

local function alive(d) return try(Osi.IsDead, d) ~= 1 end
local function resolveTarget(F, t)
  if t == "@self" then return F.char end
  if t == "@boss" or t == "@first" then
    for _, d in ipairs(F.enemies) do if alive(d) then return d end end
  end
  local k = t and tonumber(t:match("^@e(%d+)$"))
  if k then return F.enemies[k] end
  if t == "@nearest" then
    local best, bd
    for _, d in ipairs(F.enemies) do
      local dd = dist(F.char, d)
      if alive(d) and (not bd or dd < bd) then best, bd = d, dd end
    end
    return best
  end
  return t
end

local function spellRange(spell)
  local st = try(Ext.Stats.Get, spell)
  local s = st and tostring(try(function() return st.TargetRadius end) or "") or ""
  local r = tonumber(s)
  if r then return r end
  if s:match("Melee") then return 1.5 end
  if s:match("Ranged") then return 18 end
  return nil
end

-- ------------------------------------------------------------------------------------------------ requirements
-- What would stop the engine from casting a spell, read from the spell's data and the character now. The engine
-- gives no reason when it refuses, so the same list is written next to every refused cast.
local function baseSpell(s) return (tostring(s or ""):gsub("_%d+$", "")) end
local function hasFlag(flags, f)
  if type(flags) == "table" then
    for _, x in pairs(flags) do if x == f then return true end end
    return false
  end
  return tostring(flags or ""):find(f, 1, true) ~= nil
end
-- the character's spell book as a set; nil when it cannot be read (then nothing is judged from it)
function G.spellBook(u)
  local e = ent(u)
  local spells = e and try(function() return e.SpellBook.Spells end)
  if not spells then return nil end
  local out, n = {}, 0
  for _, sp in ipairs(spells) do
    local id = try(function() return sp.Id.Prototype end)
    if id then out[id] = true; n = n + 1 end
  end
  return n > 0 and out or nil
end
-- Hard blockers (the cast cannot happen) come first in the list; "encumbered" is soft (the cast is worse, and a cast
-- that needs a step may fail).
G.HARD_BLOCKERS = { ["not in the spell book"] = true, ["needs a melee weapon in the main hand"] = true,
  ["silenced (verbal component)"] = true }
function G.spellBlockers(F, spell, tgt)
  local u, out = F.char, {}
  local book = G.spellBook(u)
  if book and not book[spell] and not book[baseSpell(spell)] then out[#out + 1] = "not in the spell book" end
  local st = try(Ext.Stats.Get, spell)
  local flags = st and try(function() return st.SpellFlags end)
  local req = st and tostring(try(function() return st.RequirementConditions end) or "") or ""
  if hasFlag(flags, "HasVerbalComponent") and try(Osi.HasActiveStatus, u, "SILENCED") == 1 then
    out[#out + 1] = "silenced (verbal component)"
  end
  if req:find("CanUseWeaponActions", 1, true) and not G.equipped(u).MeleeMainHand then
    out[#out + 1] = "needs a melee weapon in the main hand"
  end
  if onCooldown(u, spell) then out[#out + 1] = "on cooldown" end
  local enc = G.encumbrance(u)
  if #enc > 0 then out[#out + 1] = "encumbered (" .. table.concat(enc, ", ") .. ")" end
  if tgt and tgt ~= u then
    if try(Osi.IsDead, tgt) == 1 then out[#out + 1] = "target dead" end
    if try(Osi.CanSee, u, tgt) == 0 then out[#out + 1] = "no line of sight" end
    local range = spellRange(spell)
    local d = dist(u, tgt)
    if range and d > range + 1.0 then out[#out + 1] = string.format("out of range %.1f > %.1f", d, range) end
  end
  return out
end
-- Before the fight: every spell the plan may cast (each chain, the item actions) is checked once. A hard blocker makes
-- it unusable for the run (logged in results.precheck; the planner passes it over as it does an unaffordable one).
-- "Not in the spell book" counts only for item actions: those come from worn items, and an item that did not go on
-- leaves its spell out of the book; the build's own spells are added in prep.
function G.precheck(F)
  local plan, seen, out = F.plan or {}, {}, {}
  F.unusable = F.unusable or {}
  local function check(spell, isItem)
    if not spell or seen[spell] then return end
    seen[spell] = true
    local hard = {}
    for _, b in ipairs(G.spellBlockers(F, spell, nil)) do
      if G.HARD_BLOCKERS[b] and (isItem or b ~= "not in the spell book") then hard[#hard + 1] = b end
    end
    if #hard > 0 then
      F.unusable[spell] = table.concat(hard, ", ")
      out[#out + 1] = { spell = spell, unusable = F.unusable[spell] }
      note("precheck: %s unusable (%s)", spell, F.unusable[spell])
    end
  end
  local function chainOf(a) while a do check(a.spell, false); a = a.alt end end
  for _, r in ipairs(plan.rounds or {}) do for _, a in ipairs(r) do chainOf(a) end end
  for _, a in ipairs(plan.steady or {}) do chainOf(a) end
  for _, it in ipairs(plan.item_actions or {}) do check(it.spell, true) end
  return out
end

-- Cast confirmation. Osi.UseSpell returning is no proof of a cast (the pilot logged Fire Bolts as done that never
-- happened: no line of sight, facing, an enemy in melee). An action counts as done only when the engine shows it:
-- a CastedSpell event of the character for that spell (an upcast variant counts for its base spell), damage from the
-- character to the action's target, or one of the action's resources going down. No evidence within the timeout =
-- a failed action, logged as such, and the fallback runs.
G.CONFIRM_MS, G.CONFIRM_MAX_MS = 6000, 15000
-- P = { who, spell, target, casts0, dmg0, res = { { kind, level, before } } }; resNow(kind, level) -> amount now
function G.castEvidence(P, casts, dmg, resNow)
  for i = (P.casts0 or 0) + 1, #(casts or {}) do
    local c = casts[i]
    if c.who == P.who and baseSpell(c.spell) == baseSpell(P.spell) then return "cast" end
  end
  for i = (P.dmg0 or 0) + 1, #(dmg or {}) do
    local d = dmg[i]
    if P.target and P.target ~= P.who and d.target == P.target and (d.source == P.who or d.owner == P.who)
      and not tostring(d.cause or ""):match("Surface") then
      return "damage"
    end
  end
  for _, r in ipairs(P.res or {}) do
    local v = resNow and resNow(r.kind, r.level)
    if v and r.before and v < r.before then return "resource" end
  end
  return nil
end
-- The engine's CastSpellFailed for the pending cast (its base spell), if one came since the cast was asked for.
function G.castRefused(P, fails)
  for i = (P.fails0 or 0) + 1, #(fails or {}) do
    local f = fails[i]
    if f.who == P.who and baseSpell(f.spell) == baseSpell(P.spell) then return f end
  end
  return nil
end
-- Why a cast did not happen, as far as the engine shows it: reactions of other creatures since the cast was asked for
-- (an Attack of Opportunity means the cast walked the character out of an enemy's reach and was interrupted), how
-- far the character moved, and the spell's blockers now. -> { why, reactions, moved, blockers }
function G.refusalReason(P, R, blockers, moved)
  local reacts, aoo = {}, false
  for i = (P.reacts0 or 0) + 1, #(R.reactions_seen or {}) do
    local x = R.reactions_seen[i]
    if x.who ~= P.who then
      reacts[#reacts + 1] = tostring(x.interrupt) .. " by " .. tostring(x.who)
      if tostring(x.interrupt):find("AttackOfOpportunity", 1, true) then aoo = true end
    end
  end
  local why
  if aoo then
    why = string.format("interrupted by an Attack of Opportunity while moving to cast (moved %.1f m)", moved or 0)
  elseif blockers and #blockers > 0 then
    why = table.concat(blockers, ", ")
  else
    why = "no reason shown by the engine"
  end
  return { why = why, reactions = reacts, moved = moved, blockers = blockers }
end

-- ------------------------------------------------------------------------------------------------ movement
-- A scripted cast that needs a step moves first, by the rules: the game's pathfinder gives the route,
-- the character runs it with CharacterMoveToPosition within its Movement, and the
-- Movement walked is charged. The spot is the first point on a route where the target is in range; a route that leaves
-- an enemy's reach is avoided when another spot in range has a clean route, else taken (the Attack of Opportunity is
-- real damage, the same for both sets). In range and in sight already: the cast goes from where the character stands.
G.REACH = 3.4          -- the game's reach plus slack for curved routes
G.MOVE_MAX_MS = 8000
function G.route(u, x, y, z)
  local e = ent(u)
  if not e then return nil end
  for _, dy in ipairs({ 0, 1.5, -1.5, 3, -3 }) do
    local okp, pts = pcall(function()
      local p = Ext.Level.BeginPathfindingImmediate(e, { x, y + dy, z })
      local found = Ext.Level.FindPath(p) and p.GoalFound
      local out = {}
      for i, nd in ipairs(p.Nodes or {}) do out[i] = { nd.Position[1], nd.Position[2], nd.Position[3] } end
      Ext.Level.ReleasePath(p)
      return found and out or nil
    end)
    if okp and pts and #pts > 0 then return pts end
  end
  return nil
end
-- The first foe (index into foes, {x, y, z}) whose reach the polyline leaves within `limit` metres, or nil; inside the
-- ring, a point farther from the foe than the start (+0.15 m) counts as leaving (curved routes).
function G.leavesReach(poly, foes, limit)
  local inside, d0, walked = {}, {}, 0
  for i, f in ipairs(foes) do
    d0[i] = math.sqrt((poly[1][1] - f[1]) ^ 2 + (poly[1][3] - f[3]) ^ 2)
    inside[i] = d0[i] < G.REACH
  end
  for k = 2, #poly do
    local ax, az, bx, bz = poly[k - 1][1], poly[k - 1][3], poly[k][1], poly[k][3]
    local seg = math.sqrt((bx - ax) ^ 2 + (bz - az) ^ 2)
    local n = math.max(1, math.ceil(seg / 0.25))
    for j = 1, n do
      local t = j / n
      if walked + seg * t > limit then return nil end
      local px, pz = ax + (bx - ax) * t, az + (bz - az) * t
      for i, f in ipairs(foes) do
        local dn = math.sqrt((px - f[1]) ^ 2 + (pz - f[3]) ^ 2)
        if (inside[i] and dn >= G.REACH) or (d0[i] < G.REACH and dn > d0[i] + 0.15) then return i end
        inside[i] = dn < G.REACH
      end
    end
    walked = walked + seg
  end
  return nil
end
-- A route cut at its first point within `need` metres of the target -> polyline from the start and its length, or nil
-- when the target is not reached within `budget` metres.
function G.cutAt(start, pts, tx, ty, tz, need, budget)
  local poly, walked = { start }, 0
  for _, p in ipairs(pts) do
    local q = poly[#poly]
    walked = walked + math.sqrt((p[1] - q[1]) ^ 2 + (p[3] - q[3]) ^ 2)
    if walked > budget then return nil end
    poly[#poly + 1] = p
    if math.sqrt((p[1] - tx) ^ 2 + (p[2] - ty) ^ 2 + (p[3] - tz) ^ 2) <= need then return poly, walked end
  end
  return nil
end
-- who: the creature that moves (default the character; the character's summon on its own turn)
-- -> nil (cast from here), or { x, y, z, len, risk = name of the foe whose reach the route leaves | nil }
function G.castSpot(F, tgt, range, who)
  local me = who or F.char
  local x0, y0, z0 = xyz(me)
  local tx, ty, tz = xyz(tgt)
  if not (x0 and tx) then return nil end
  local d = math.sqrt((x0 - tx) ^ 2 + (y0 - ty) ^ 2 + (z0 - tz) ^ 2)
  if d <= range and try(Osi.CanSee, me, tgt) ~= 0 then return nil end
  local need = math.max(1.2, range - (range > 3 and 1.0 or 0.3))
  local budget = resAmount(me, "Movement") + 0.5
  local foes, names = {}, {}
  for _, e in ipairs(F.enemies or {}) do
    local ex, ey, ez = xyz(e)
    if ex and alive(e) then foes[#foes + 1] = { ex, ey, ez }; names[#foes] = name(e) end
  end
  local start = { x0, y0, z0 }
  local best, any
  local goals = { { tx, ty, tz } }
  for k = 0, 11 do
    local a = 2 * math.pi * k / 12
    goals[#goals + 1] = { tx + need * 0.8 * math.cos(a), ty, tz + need * 0.8 * math.sin(a) }
  end
  for _, g in ipairs(goals) do
    local pts = G.route(me, g[1], g[2], g[3])
    local poly, len = nil, nil
    if pts then poly, len = G.cutAt(start, pts, tx, ty, tz, need, budget) end
    if poly then
      local bad = G.leavesReach(poly, foes, 1e9)
      local last = poly[#poly]
      local c = { x = last[1], y = last[2], z = last[3], len = len, risk = bad and names[bad] or nil }
      if not bad and (not best or len < best.len) then best = c end
      if not any or len < any.len then any = c end
    end
  end
  return best or any
end
-- Waits for the move to end (there, stalled or timed out) and charges the Movement the engine did not. -> true when done.
function G.moveSettled(F, t)
  local M = F.moving
  local x, y, z = xyz(F.char)
  if not x then return true end
  local there = math.sqrt((x - M.spot.x) ^ 2 + (z - M.spot.z) ^ 2) < 0.5
  if math.sqrt((x - M.last[1]) ^ 2 + (z - M.last[3]) ^ 2) > 0.05 then M.last, M.lastT = { x, y, z }, t end
  if not there and t - M.lastT < 800 and t - M.t0 < G.MOVE_MAX_MS then return false end
  local moved = math.sqrt((x - M.p0[1]) ^ 2 + (z - M.p0[3]) ^ 2)
  local spent = math.max(0, M.mv0 - resAmount(F.char, "Movement"))
  local owed = math.max(0, math.min(math.max(M.spot.len or 0, moved), M.mv0) - spent)
  if owed > 0 then
    for _, entry in ipairs(resList(F.char, "Movement") or {}) do entry.Amount = math.max(0, entry.Amount - owed); break end
    pcall(function() ent(F.char):Replicate("ActionResources") end)
  end
  M.rec.move.moved = moved
  M.rec.move.result = there and "there" or (t - M.t0 >= G.MOVE_MAX_MS and "timeout" or "stalled")
  return true
end

-- one scripted action: {spell, target, group ("action" | "bonus" | "free"), cost (override; "free" = granted, e.g.
-- an Extra Attack), requires ("action" / "surge": only after that succeeded this round), alt (fallback action),
-- done_key (what R.done records instead of the group), ms}. A cast that the engine accepts is left PENDING in
-- F.pending until G.settle confirms or fails it.
local function doAction(F, a, R, rec0)
  if a.requires and not R.done[a.requires] then
    R.actions[#R.actions + 1] = { spell = a.spell, why = a.why, result = "skipped: no " .. a.requires .. " this round" }
    return
  end
  local tgt = resolveTarget(F, a.target or "@boss")
  local rec = rec0
  if not rec then
    rec = { spell = a.spell, target = a.target, why = a.why, group = a.group, item = a.item }
    R.actions[#R.actions + 1] = rec
  end
  local function fallback(reason)
    rec.result = reason
    if a.alt then rec.result = reason .. " -> alt"; return doAction(F, a.alt, R) end
  end
  if not tgt then return fallback("no target") end
  local okp, why = G.afford(F, a)
  if not okp then return fallback(why) end
  local costs = a.cost == "free" and {} or (a.cost and parseCosts(a.cost) or spellCosts(a.spell))
  local range = a.range or spellRange(a.spell)
  local reachable = range and range + resAmount(F.char, "Movement") + 1.0
  if tgt ~= F.char and range and dist(F.char, tgt) > reachable then
    return fallback(string.format("out of range %.1f > %.1f", dist(F.char, tgt), reachable))
  end
  if tgt ~= F.char and range and not rec0 and not a.at_target_pos then
    local spot = G.castSpot(F, tgt, range)
    if spot then
      local x, y, z = xyz(F.char)
      rec.move = { x = spot.x, z = spot.z, len = spot.len, aoo_risk = spot.risk }
      if pcall(Osi.CharacterMoveToPosition, F.char, spot.x, spot.y, spot.z, "Run", "LA_gauntlet_move") then
        F.moving = { a = a, R = R, rec = rec, spot = spot, t0 = now(), p0 = { x, y, z }, last = { x, y, z },
          lastT = now(), mv0 = resAmount(F.char, "Movement") }
        rec.result = "moving"
        return
      end
    end
  end
  local res, before = {}, {}
  for i, c in ipairs(costs) do
    before[i] = resAmount(F.char, c.kind, c.level)
    res[#res + 1] = { kind = c.kind, level = c.level, before = before[i] }
  end
  local P = { a = a, rec = rec, costs = costs, before = before, res = res, who = uuid(F.char), spell = a.spell,
    target = uuid(tgt), casts0 = #R.casts, dmg0 = #G.dmg, t0 = now(), fails0 = #(R.cast_fails or {}),
    reacts0 = #(R.reactions_seen or {}), pos0 = { xyz(F.char) } }
  local okc, err
  if a.at_target_pos then
    local x, y, z = Osi.GetPosition(tgt)
    okc, err = pcall(Osi.UseSpellAtPosition, F.char, a.spell, x, y, z, 1)
  else
    -- cast from where the character stands (the 5-argument UseSpell, "without move"): the harness moved it first when
    -- the target was out of range or sight. Left to itself the engine stepped away from an enemy in melee before a
    -- ranged attack or a projectile spell, the enemy's Attack of Opportunity interrupted the step and the cast was
    -- refused (every Fire Bolt once the enemy stood 1 m away); the game lets a player shoot from where they stand
    okc, err = pcall(Osi.UseSpell, F.char, a.spell, tgt, tgt, 1)
  end
  if not okc then return fallback("engine refused " .. tostring(err)) end
  rec.result = "pending"
  F.pending = P
end

G.CAST_RETRIES, G.RETRY_ANY_REFUSAL = 2, false
-- Settles the pending cast at time t: true when it is finished (done, or failed and its fallback started), false
-- while still waiting. A cast still in progress may run to CONFIRM_MAX_MS.
function G.settle(F, R, t)
  local P = F.pending
  if not P then return true end
  local ev = G.castEvidence(P, R.casts, G.dmg, function(k, lv) return resAmount(F.char, k, lv) end)
  if ev then
    F.pending = nil
    pay(F.char, P.costs, P.before)
    P.rec.result, P.rec.confirmed, P.rec.ms = "done", ev, t - P.t0
    local a = P.a
    R.done[a.done_key or a.group or "free"] = true
    if a.spell == "Shout_ActionSurge" then R.done.surge = true end
    if a.per then F.cooldown[a.spell] = a.per end
    return true
  end
  local waited = t - P.t0
  -- the engine's own refusal ends the wait at once
  local refused = G.castRefused(P, R.cast_fails)
  if not refused and (waited < G.CONFIRM_MS or (waited < G.CONFIRM_MAX_MS and casting(F.char))) then return false end
  F.pending = nil
  R.cast_misses = (R.cast_misses or 0) + 1
  -- what the engine saw at the miss (range, line of sight, the caster's statuses, reactions, movement), and why
  local moved
  if P.pos0 and P.pos0[1] then
    local x, y, z = xyz(F.char)
    if x then moved = math.sqrt((x - P.pos0[1]) ^ 2 + (y - P.pos0[2]) ^ 2 + (z - P.pos0[3]) ^ 2) end
  end
  local reason = G.refusalReason(P, R, try(G.spellBlockers, F, P.spell, P.target) or {}, moved)
  P.rec.result = refused and ("failed: refused by the engine: " .. reason.why)
    or string.format("failed: no cast seen within %.1f s (%s)", waited / 1000, reason.why)
  P.rec.miss = { dist = try(dist, F.char, P.target), sees = try(Osi.CanSee, F.char, P.target), refused = refused ~= nil,
    why = reason.why, reactions = reason.reactions, moved = moved, blockers = reason.blockers,
    statuses = try(function()
      local out = {}
      for _, v in pairs(ent(F.char).StatusContainer.Statuses) do out[#out + 1] = tostring(v) end
      return out
    end) }
  -- an Attack of Opportunity interrupted the engine's step to the cast: once the step has settled the same cast is asked
  -- for again from where the character stands; it is not a miss and the round is not idle. The engine can refuse the
  -- first ask after the reaction too (no reason shown; seen when the enemy had just stepped into melee), so a cast
  -- an Attack of Opportunity interrupted gets up to G.CAST_RETRIES asks, and only such a cast. A run asked with
  -- retry_any_refusal (off by default) asks again for any refused cast
  local tries = P.a.retried or 0
  local anyRefusal = (F.req and F.req.retry_any_refusal) or G.RETRY_ANY_REFUSAL
  if refused and tries < G.CAST_RETRIES
    and (tries > 0 or anyRefusal or reason.why:find("Attack of Opportunity", 1, true)) then
    R.cast_misses = R.cast_misses - 1
    P.rec.retried = P.rec.retried or P.rec.result
    P.rec.retries = tries + 1
    local again = {}
    for k, v in pairs(P.a) do again[k] = v end
    again.retried = tries + 1
    doAction(F, again, R, P.rec)
    return true
  end
  -- a per-rest item spell the engine would not cast is not tried again before the next rest
  if P.a.per then F.cooldown[P.a.spell] = P.a.per end
  if P.a.alt then
    P.rec.result = P.rec.result .. " -> alt"
    doAction(F, P.a.alt, R)
  end
  return true
end

-- The shared adaptive rule (identical for both sets of a pair): item actions from plan.item_actions, in their
-- priority order. A per-rest action spell not used since the last rest replaces the round's core action group (in a
-- round with Action Surge, the surge's attacks instead, so the first action keeps its Extra Attacks); a
-- bonus-action item spell fills the bonus action when the core plan leaves it free; reactions stay with the engine.
-- An item spell is chosen only when the character can pay for it now (action / bonus action, resources, per-rest
-- use, engine cooldown); otherwise the next candidate is tried and the core plan keeps its action. A chosen item
-- action carries the replaced core action as its fallback. Every candidate is logged (used / skipped + reason) in
-- R.item_rule.
function G.hasSurge(list)
  for _, a in ipairs(list) do if a.requires == "surge" then return true end end
  return false
end
local function itemRule(F, list, R)
  local out = {}
  for _, a in ipairs(list) do out[#out + 1] = a end
  local hasBonus, replaced = false, false
  for _, a in ipairs(out) do if a.group == "bonus" then hasBonus = true end end
  R.item_rule = {}
  for _, it in ipairs(F.plan.item_actions or {}) do
    local log = { spell = it.spell, item = it.item, group = it.group, per = it.per }
    R.item_rule[#R.item_rule + 1] = log
    local entry = { spell = it.spell, group = it.group, target = it.target or "@boss", why = "item: " .. tostring(it.item),
      item = it.item, per = it.per ~= "none" and it.per or nil, at_target_pos = it.at_target_pos, cost = it.cost_override }
    local okp, why
    if it.group == "action" or it.group == "bonus" then okp, why = G.afford(F, entry) end
    if it.group == "reaction" then
      log.result = "skipped: reactions are left to the engine"
    elseif it.per ~= "none" and F.cooldown[it.spell] then
      log.result = "skipped: used this rest"
    elseif (it.group == "action" and replaced) then
      log.result = "skipped: one item action per round"
    elseif (it.group == "bonus" and hasBonus) then
      log.result = "skipped: the core plan uses the bonus action"
    elseif (it.group == "action" or it.group == "bonus") and not okp then
      log.result = "skipped: cannot pay (" .. tostring(why) .. ")"
    elseif it.group == "action" and G.hasSurge(out) then
      -- an Action Surge round: the item spell takes the surge's action, so the first action keeps its Extra Attacks
      -- (the pilot's Roaring Shot took round 1's attack action and its Extra Attack every run); the surge's first
      -- attack is the fallback
      local keep, first = {}, nil
      for _, a in ipairs(out) do
        if a.requires == "surge" then
          if not first then first = a; keep[#keep + 1] = entry end
        else
          keep[#keep + 1] = a
        end
      end
      entry.alt, entry.done_key, entry.requires = first, "item", "surge"
      out, replaced = keep, true
      log.result = "used: takes Action Surge's action"
    elseif it.group == "action" then
      local keep, core = {}, nil
      for _, a in ipairs(out) do
        if a.group == "action" and not core then core = a end
        if a.group ~= "action" then keep[#keep + 1] = a end
      end
      entry.alt, entry.done_key = core, "item"
      table.insert(keep, 1, entry)
      out, replaced = keep, true
      log.result = "used: replaces the core action"
    elseif it.group == "bonus" then
      out[#out + 1] = entry
      hasBonus = true
      log.result = "used: free bonus action"
    end
  end
  return out
end

-- Casts of the test character that no part of its plan asked for (its own racial / tadpole / class reactions,
-- leftovers of the test character's sheet): they would count as the set's damage. Reactions the plan sets to "auto"
-- are allowed, matched on the name after its prefix (Interrupt_HellishRebuke ~ Target_HellishRebuke). Spells only
-- items grant (MAG_ / Legendary in the name, e.g. a shield's riposte) come from the set: the test character's own
-- gear is taken off in prep.
local function core(s) return (baseSpell(s):gsub("^[^_]+_", "")) end
function G.itemSpell(s) return s:find("_MAG_", 1, true) ~= nil or s:find("_Legendary_", 1, true) ~= nil end
function G.foreignCasts(rounds, me, plan)
  local allowed = {}
  local function allow(a)
    while a do allowed[core(a.spell)] = true; a = a.alt end
  end
  for _, r in ipairs(plan.rounds or {}) do for _, a in ipairs(r) do allow(a) end end
  for _, a in ipairs(plan.steady or {}) do allow(a) end
  for _, a in ipairs(plan.defence_opening or {}) do allow(a) end
  for _, it in ipairs(plan.item_actions or {}) do allowed[core(it.spell)] = true end
  for k, p in pairs(plan.reactions or {}) do if p == "auto" then allowed[core(k)] = true end end
  local out = {}
  for _, R in ipairs(rounds or {}) do
    -- the character's own Attack of Opportunity (the engine casts it as a weapon attack): fair, the same for both sets
    local aoo = false
    for _, x in ipairs(R.reactions_seen or {}) do
      if x.who == me and tostring(x.interrupt):find("AttackOfOpportunity", 1, true) then aoo = true end
    end
    for _, c in ipairs(R.casts or {}) do
      local weapon = core(c.spell):find("HandAttack$") ~= nil
      if c.who == me and not allowed[core(c.spell)] and not G.itemSpell(c.spell) and not (aoo and weapon) then
        out[#out + 1] = { r = R.r, spell = c.spell }
      end
    end
  end
  return out
end

-- Set items that did not go on in prep (the item's spells and boosts were then never part of the run).
function G.unworn(prep)
  local out = {}
  for _, it in ipairs(prep and prep.items or {}) do
    if it.want ~= "Elixir" and not it.got then out[#out + 1] = tostring(it.stats) .. " (" .. tostring(it.want) .. ")" end
  end
  return out
end
-- Damage rows on the character from creatures that are not this run's enemies (an earlier run's enemy still in the
-- fight): { [source] = hits }, and the number of hits.
function G.outsideAttackers(dmg, me, enemies)
  local mine, out, n = {}, {}, 0
  for _, d in ipairs(enemies or {}) do mine[uuid(d)] = true end
  for _, row in ipairs(dmg or {}) do
    local src = row.owner or row.source
    if row.target == me and src and src ~= "" and src ~= me and not mine[src] and not mine[row.source or ""]
      and not tostring(row.cause or ""):match("Surface") then
      out[src] = (out[src] or 0) + 1
      n = n + 1
    end
  end
  return out, n
end

-- Is the run a measurement? { valid, causes }. Invalid: ended early (turn never came, aborted, reset, prep failed,
-- a reaction prompt), a reaction prompt the policy missed, a test character whose reactions could not be set, casts
-- outside the plan, an acting round in which no action was confirmed, set items that did not go on, a character
-- still encumbered when the fight started, or hits from creatures outside the run. A round in which the character
-- was down is no idle round: it is counted in results.downed and the summary instead.
function G.judge(rounds, why, results, opts)
  local causes = {}
  if why and why ~= "rounds done" and why ~= "downed" then causes[#causes + 1] = "ended: " .. why end
  for _, phase in ipairs({ "start", "end" }) do
    local sc = results.setup and results.setup[phase]
    if sc and #sc.mismatches > 0 then
      local parts = {}
      for _, m in ipairs(sc.mismatches) do
        parts[#parts + 1] = string.format("%s (want %s, got %s)", m.field, tostring(m.want), tostring(m.got))
      end
      causes[#causes + 1] = "setup mismatch at the " .. phase .. ": " .. table.concat(parts, "; ")
    end
  end
  local refused = (results.summary or {}).cast_misses or 0
  if refused > 0 then causes[#causes + 1] = refused .. " planned cast(s) refused or never seen" end
  local smiss = (results.summary or {}).summon_misses or 0
  if smiss > 0 then causes[#causes + 1] = smiss .. " summon attack(s) refused or never seen" end
  if results.rider_misses and #results.rider_misses > 0 then
    local parts = {}
    for _, m in ipairs(results.rider_misses) do
      parts[#parts + 1] = string.format("%s on %s after round %s", tostring(m.status), tostring(m.on), tostring(m.r))
    end
    causes[#causes + 1] = "rider(s) missing: " .. table.concat(parts, "; ")
  end
  local unworn = G.unworn(results.prep)
  if #unworn > 0 then causes[#causes + 1] = "set items not worn: " .. table.concat(unworn, ", ") end
  if results.encumbered and #results.encumbered > 0 then
    causes[#causes + 1] = "the test character was encumbered: " .. table.concat(results.encumbered, ", ")
  end
  if (results.outside_hits or 0) > 0 then
    causes[#causes + 1] = results.outside_hits .. " hit(s) on the character from creatures outside the run"
  end
  if (results.cross_lane_hits or 0) > 0 then
    causes[#causes + 1] = results.cross_lane_hits .. " hit(s) from the character on the other lane"
  end
  local shared = 0
  for _, R in ipairs(rounds or {}) do if R.combat_shared then shared = shared + 1 end end
  if shared > 0 then causes[#causes + 1] = "the two lanes shared one combat in " .. shared .. " round(s)" end
  if results.reaction_misses and #results.reaction_misses > 0 then
    causes[#causes + 1] = #results.reaction_misses .. " reaction prompt(s) not covered by the policy"
  end
  local me = opts and opts.me
  local rep = me and results.reactions and results.reactions[me]
  if rep and rep.verified == false then
    causes[#causes + 1] = "reactions not set: " .. table.concat(rep.uncovered or {}, ", ")
  end
  if results.foreign_casts and #results.foreign_casts > 0 then
    local seen, names = {}, {}
    for _, c in ipairs(results.foreign_casts) do
      if not seen[c.spell] then seen[c.spell] = true; names[#names + 1] = c.spell end
    end
    causes[#causes + 1] = "the test character cast outside the plan: " .. table.concat(names, ", ")
  end
  if not (opts and opts.char_acts == false) then
    local idle = 0
    for _, R in ipairs(rounds or {}) do
      if not R.downed and not (R.done and (R.done.action or R.done.item)) then idle = idle + 1 end
    end
    if idle > 0 then causes[#causes + 1] = idle .. " round(s) without a confirmed action" end
  end
  return { valid = #causes == 0, causes = causes }
end


-- ------------------------------------------------------------------------------------------------ arena
-- Scenario layouts relative to the arena point (the character's position when the first run starts, facing +X).
-- Distances depend on the plan's mode: melee next to the target, throw / ranged / caster at range, self-centred
-- auras ("selfaoe": Spirit Guardians, Radiance of the Dawn) with the enemies around the character.
G.SCENARIOS = {
  boss = { enemies = 1, rounds = 16 },
  pack = { enemies = 4, rounds = 16 },
  defence = { enemies = 3, rounds = 16, char_acts = false, ring = true },
  longday = { enemies = 4, rounds = 16, fight_rounds = 4, short_rest_every = 4 },
}
G.RANGE = { melee = 1.6, throw = 6.0, ranged = 10.0, caster = 10.0 }
-- A solo character takes every hit a party would share, and keeps its real hit points: the enemies' damage per hit is
-- scaled (the same for both sets; a scenario or a request may set enemy_damage_scale), rounded to whole points.
G.ENEMY_DAMAGE_SCALE = 0.5
function G.scaleEnemy(E, scale)
  local out = {}
  for k, v in pairs(E) do out[k] = v end
  out.damage_scale = scale or 1
  out.dmg_unscaled = E.dmg
  out.dmg = math.max(1, math.floor((E.dmg or 1) * out.damage_scale + 0.5))
  return out
end

local function ground(x, z, nearY)
  local best
  for _, y in ipairs(try(Ext.Level.GetHeightsAt, x, z) or {}) do
    if not best or math.abs(y - nearY) < math.abs(best - nearY) then best = y end
  end
  if best and math.abs(best - nearY) < 2.0 then return best end
  return nearY
end

-- Enemy spots: around the character (melee, self-centred auras, the defence ring) or a line at the build's range,
-- laid out along the arena's direction (default +x). A = an arena from arenas.json (start, dir, high): the character
-- starts at A.start and a pack's fourth enemy stands on A.high, the arena's high ground.
function G.arena(scn, mode, selfaoe, origin, A)
  local S = G.SCENARIOS[scn]
  if A and A.start then origin = A.start end
  local x0, y0, z0 = origin[1], origin[2], origin[3]
  local dx, dz = 1, 0
  if A and A.dir then
    local l = math.sqrt(A.dir[1] ^ 2 + A.dir[2] ^ 2)
    if l > 0 then dx, dz = A.dir[1] / l, A.dir[2] / l end
  end
  local function at(f, side) return { x0 + f * dx - side * dz, 0, z0 + f * dz + side * dx } end
  local d = G.RANGE[mode] or 6.0
  local pts = {}
  local n = S.enemies
  if S.ring or selfaoe or mode == "melee" then
    local r = selfaoe and 2.2 or 1.6
    for i = 1, n do
      local a = (i - 1) * (2 * math.pi / math.max(n, 1)) * (selfaoe and 1 or 0.35)
      pts[#pts + 1] = at(r * math.cos(a), r * math.sin(a))
    end
  else
    local offs = { { 0, 0 }, { 1.8, 0 }, { 0, 1.8 }, { 1.8, 1.8 } }
    for i = 1, n do pts[#pts + 1] = at(d + offs[i][1], offs[i][2] - (n > 1 and 0.9 or 0)) end
    if A and A.high and n >= 4 then pts[4] = { A.high[1], 0, A.high[3] } end
  end
  for i, p in ipairs(pts) do p[2] = ground(p[1], p[3], (A and A.high and i == 4 and n >= 4) and A.high[2] or y0) end
  return { x0, y0, z0 }, pts
end

-- Living characters inside the arena that are not the party: an arena must be empty before a run starts. Runs
-- G.clearLeftovers first; whatever it could not remove (an earlier run's enemy, a summon) is an intruder.
function G.arenaIntruders(A)
  local out = {}
  local party = {}
  for _, m in ipairs(partyMembers()) do party[m] = true end
  for _, e in ipairs(try(Ext.Entity.GetAllEntitiesWithComponent, "ServerCharacter") or {}) do
    local u = try(function() return e.Uuid.EntityUuid end)
    if u and not party[u] and standing(u) and inArena(u, A) then
      local x, _, z = Osi.GetPosition(u)
      out[#out + 1] = string.format("%s at %.0f,%.0f", name(u), x, z)
    end
  end
  return out
end

-- Read-only check of an arena (or of every lane of a lanes entry) before it is used: the ground under the start and
-- the enemy spots, and the living creatures outside the party inside the radius. Never during a run.
function G.survey(name)
  local C = G.catalog() or {}
  local entry = (C.arenas or {})[name]
  if not entry then return "unknown arena " .. tostring(name) end
  local names = {}
  if entry.lanes then
    for _, l in pairs(entry.lanes) do names[#names + 1] = l.arena end
  else
    names[1] = name
  end
  local out = {}
  for _, n in ipairs(names) do
    local A = C.arenas[n]
    local rec = { arena = n, intruders = A and G.arenaIntruders(A) or { "unknown arena" }, ground = {} }
    if A then
      local _, pts = G.arena("boss", "caster", false, A.start, A)
      local spots = { { "start", A.start } }
      for i, p in ipairs(pts) do spots[#spots + 1] = { "enemy " .. i, p } end
      for _, sp in ipairs(spots) do
        local hs = try(Ext.Level.GetHeightsAt, sp[2][1], sp[2][3]) or {}
        local near
        for _, y in ipairs(hs) do if not near or math.abs(y - A.start[2]) < math.abs(near - A.start[2]) then near = y end end
        rec.ground[#rec.ground + 1] = { spot = sp[1], x = sp[2][1], z = sp[2][3], ground = near,
          ok = near ~= nil and math.abs(near - A.start[2]) < 2.0 }
      end
    end
    out[#out + 1] = rec
  end
  G.results.survey = out
  return G.dump()
end

-- ------------------------------------------------------------------------------------------------ catalogue
-- LootAdvisor_gauntlet_catalog.json (written by tools/gauntlet/catalog.py): enemies + buffs per act, every build
-- (per act: sheet, passives, spells, slots, resources, round plan), every set (items), set-tuned respecs.
function G.catalog()
  if not G.CAT then
    local raw = try(Ext.IO.LoadFile, "LootAdvisor_gauntlet_catalog.json")
    G.CAT = raw and try(Ext.Json.Parse, raw) or nil
  end
  return G.CAT
end

local function compose(req)
  if req.spec then return req.spec end
  if req.spec_file then
    local raw = try(Ext.IO.LoadFile, req.spec_file)
    local sp = raw and try(Ext.Json.Parse, raw)
    if not sp then return nil, "cannot read " .. req.spec_file end
    return sp
  end
  local C = G.catalog()
  if not C then return nil, "no catalogue" end
  local act = tostring(req.act)
  local b = C.builds[req.build]
  local part = b and b.acts and b.acts[act]
  local key = tostring(req.set) .. "|" .. tostring(req.build) .. "|" .. act
  if req.tuned and C.tuned and C.tuned[key] then part = C.tuned[key] end
  if not part then return nil, "build " .. tostring(req.build) .. " has no act " .. act end
  local set = C.sets[req.set]
  if not set then return nil, "unknown set " .. tostring(req.set) end
  local spec = {}
  for k, v in pairs(part) do spec[k] = v end
  spec.items = set.items
  spec.set, spec.set_id, spec.build, spec.act = set.name, req.set, req.build, req.act
  spec.expect = set.expect and set.expect[tostring(req.build) .. "|" .. act] or nil
  spec.respec = (req.tuned and C.tuned and C.tuned[key]) and "tuned to set" or "planned"
  return spec
end

-- ------------------------------------------------------------------------------------------------ fight
local function roundStart(F)
  G.round = G.round + 1
  local R = { r = G.round, actions = {}, casts = {}, done = {}, cast_fails = {}, reactions_seen = {},
    char_hp_before = try(Osi.GetHitpoints, F.char), tm = { turn = now() - G.t0 } }
  R.char_hp_lost_enemy_turns = math.max(0, (F.hpChar or 0) - (R.char_hp_before or 0))
  -- downed in the enemies' turn: the engine gives the turn no action (healing does not bring it back). G.step ends the
  -- run before such a round; a round that still starts down is recorded as downed, never as an idle round.
  if R.char_hp_before and R.char_hp_before <= 0 then R.downed = true end
  for _, d in ipairs(F.enemies) do pcall(Osi.SetHitpointsPercentage, d, 100) end
  local S = F.S
  if S.short_rest_every and G.round > 1 and (G.round - 1) % S.short_rest_every == 0 then
    G.refill(F.char, "short")
    for k, per in pairs(F.cooldown) do if per == "short" then F.cooldown[k] = nil end end
    R.short_rest = true
  end
  F.hpChar = try(Osi.GetHitpoints, F.char)
  if F.lane then
    -- two lanes are two combats: the character's combat must not be the other lane's
    R.combat = tostring(try(Osi.CombatGetGuidFor, F.char))
    for _, u in pairs(F.lane.others or {}) do
      local c = tostring(try(Osi.CombatGetGuidFor, u))
      if c ~= "nil" and c == R.combat then R.combat_shared = true end
    end
  end
  G.rounds[#G.rounds + 1] = R
  -- the queue is planned on the first act step, once the engine has refilled the turn's resources
  F.queue, F.qi, F.pending, F.moving = (F.manual and {} or nil), 0, nil, nil
end

-- The round's queue from the character's real resources now: each entry of the round plan becomes the first
-- affordable action of its priority chain (an L6 upcast while an L6 slot is left, then L5 ..., the base spell, the
-- cantrip; Radiance of the Dawn while Channel Divinity lasts); the ones passed over go to R.plan_skips, not to the
-- failed actions. Then the shared item rule. Every action is checked again when it is cast.
function G.planRound(F, R)
  local S, plan = F.S, F.plan
  local k = R.r
  if S.fight_rounds then k = ((R.r - 1) % S.fight_rounds) + 1 end
  local list = (plan.rounds or {})[k] or plan.steady or {}
  if S.char_acts == false then list = (k == 1) and (plan.defence_opening or {}) or {} end
  R.plan_skips = R.plan_skips or {}
  -- the character's statuses as its turn starts (DREAD_AMBUSHER is there until the first attack takes it off)
  R.turn_statuses = {}
  for st in pairs(G.statusSet(F.char)) do R.turn_statuses[#R.turn_statuses + 1] = st end
  table.sort(R.turn_statuses)
  local out = {}
  for _, a in ipairs(list) do
    local pick = a.requires and a or G.pickAffordable(F, a, R.plan_skips)
    if pick then out[#out + 1] = pick end
  end
  if S.char_acts == false then return out end
  return itemRule(F, out, R)
end

-- The riders the plan relies on (plan.riders: Hunter's Mark's HUNTERS_MARK on the boss, Dread Ambusher's
-- DREAD_AMBUSHER on the character), checked as the turn that casts them ends: the status is on now, was on as the turn
-- started, or was put on during the round. A missing one fails the run like a refused cast (results.rider_misses).
function G.riderCheck(F, R)
  if F.manual or R.downed then return end
  for _, rd in ipairs((F.plan or {}).riders or {}) do
    if rd.round == R.r then
      local who = resolveTarget(F, rd.on or "@boss")
      local seen = who ~= nil and try(Osi.HasActiveStatus, who, rd.status) == 1
      if not seen and who == F.char then
        for _, st in ipairs(R.turn_statuses or {}) do if st == rd.status then seen = true end end
      end
      for _, x in ipairs(R.status_log or {}) do
        if who and x.on and x.status == rd.status and x.who == uuid(who) then seen = true end
      end
      if not seen then
        local miss = { r = R.r, status = rd.status, on = rd.on, why = rd.why }
        R.rider_misses = R.rider_misses or {}
        R.rider_misses[#R.rider_misses + 1] = miss
        G.results.rider_misses = G.results.rider_misses or {}
        G.results.rider_misses[#G.results.rider_misses + 1] = miss
        note("rider missing after round %d: %s on %s", R.r, rd.status, tostring(rd.on))
      end
    end
  end
end

-- per-run numbers (the same for scripted and manual runs)
local function summarize(F)
  local enemies = {}
  for i, d in ipairs(F.enemies or {}) do enemies[uuid(d)] = i end
  local me = uuid(F.char)
  local per = {}
  for _, R in ipairs(G.rounds) do per[R.r] = { dealt = 0, summon = 0, taken = 0, hits_taken = 0, rows = 0 } end
  -- the character's summons deal the side's damage too (counted in dealt; summon_dealt is their share)
  local mine = function(row)
    return row.source == me or row.owner == me or (F.summons or {})[row.source or ""] == true
  end
  for _, row in ipairs(G.dmg) do
    local p = per[row.r]
    if p then
      if enemies[row.target] and mine(row) then
        p.dealt = p.dealt + (row.amount or 0)
        if row.source ~= me then p.summon = p.summon + (row.amount or 0) end
        p.rows = p.rows + 1
      elseif row.target == me then
        p.taken = p.taken + (row.amount or 0)
        p.hits_taken = p.hits_taken + 1
      end
    end
  end
  local dealt, taken, summon = {}, {}, {}
  for r = 1, #G.rounds do
    dealt[r] = per[r] and per[r].dealt or 0
    summon[r] = per[r] and per[r].summon or 0
    taken[r] = per[r] and per[r].taken or 0
  end
  local function mean(t)
    local s = 0
    for _, v in ipairs(t) do s = s + v end
    return #t > 0 and s / #t or 0
  end
  -- the sheet's hit points, without the run's HP buffer
  local hp = math.max(0, (try(Osi.GetMaxHitpoints, F.char) or 0) - (F.hpBuffer or 0))
  local tk = mean(taken)
  local failed, misses, downed, smisses, riders, total = 0, 0, 0, 0, 0, 0
  for _, R in ipairs(G.rounds) do
    for _, a in ipairs(R.actions) do if a.result ~= "done" then failed = failed + 1 end end
    misses = misses + (R.cast_misses or 0)
    smisses = smisses + (R.summon_misses or 0)
    riders = riders + #(R.rider_misses or {})
    if R.downed then downed = downed + 1 end
  end
  for _, v in ipairs(summon) do total = total + v end
  return { rounds = #G.rounds, dpr = mean(dealt), dealt = dealt, taken = taken, taken_per_round = tk, max_hp = hp,
    turns_survived = tk > 0 and hp / tk or nil, actions_not_done = failed, cast_misses = misses, downed = downed,
    rounds_survived = F.downAt and (F.downAt - 1) or #G.rounds, went_down = F.downAt ~= nil,
    summon_dealt = summon, summon_damage = total, summon_misses = smisses, rider_misses = riders }
end

function G.difficulty()
  return { osi = try(Osi.GetDifficulty), note = G.difficultyNote }
end

-- The run's own boosts on the test character (carry limit, no Attack of Opportunity, HP buffer), taken off when it ends.
function G.dropRunBoosts(u, hpBuffer)
  local list = { G.CARRY_BOOST, G.AOO_BOOST }
  if hpBuffer and hpBuffer > 0 then list[#list + 1] = string.format("IncreaseMaxHP(%d)", hpBuffer) end
  for _, b in ipairs(list) do pcall(Osi.RemoveBoosts, u, b, 0, CAUSE, u) end
end

-- Back on its feet with full hit points: resurrected when dead, the downed state removed.
function G.revive(u)
  if try(Osi.IsDead, u) == 1 then pcall(Osi.Resurrect, u) end
  pcall(Osi.RemoveStatus, u, "DOWNED")
  pcall(Osi.SetHitpointsPercentage, u, 100)
end

local function finish(F, why)
  G.fighting = false
  F.state = "done"
  if not F.manual then
    G.results.reactions_restored = G.reactionsRestore()
    G.results.toggles_restored = G.togglesRestore()
    if not F.lane then
      G.unparkOthers()
      G.results.hostility_restored = G.laneFactionsRestore(F.hostility)
      F.hostility = nil
    end
  end
  -- this run's enemies and the character's summons go; whatever still stands after CLEANUP_MS is killed
  local gone = {}
  for _, d in ipairs(F.enemies or {}) do gone[#gone + 1] = d end
  if F.char then
    for _, d in ipairs(G.leftoverSummons(uuid(F.char), F.A)) do
      gone[#gone + 1] = d
      F.summons = F.summons or {}
      F.summons[d] = true
    end
  end
  for _, d in ipairs(gone) do G.removeCreature(d) end
  wait(G.CLEANUP_MS, function()
    for _, d in ipairs(gone) do if standing(d) then pcall(Osi.Die, d, 0, NULL_GUID, 0, 0) end end
  end)
  if F.manual and G.barSaved and why ~= "reset" then G.results.hotbar_restore = G.hotbarRestore() end
  if why == "downed" then F.downAt = G.round + 1 end
  if G.results.timing and F.tFight then G.results.timing.fight_ms = now() - F.tFight end
  if F.spec and not F.manual and G.results.setup then
    G.results.setup["end"] = G.setupCheck(F, F.spec, "end", { buffs = F.setupExtra and F.setupExtra.buffs })
  end
  G.results.summary = summarize(F)
  G.results.summon_damage = G.results.summary.summon_damage
  G.results.ended = why or "rounds done"
  local downed = {}
  for _, R in ipairs(G.rounds) do if R.downed then downed[#downed + 1] = R.r end end
  G.results.downed = downed
  if F.char and F.enemies then
    G.results.outside_attackers, G.results.outside_hits = G.outsideAttackers(G.dmg, uuid(F.char), F.enemies)
  end
  if F.lane and F.char then
    G.results.lane = F.lane
    G.results.cross_lane_hits = G.crossLaneHits(G.dmg, uuid(F.char), G.LANES and G.LANES.members, F.lane.id)
  end
  if F.char and not F.manual then G.dropRunBoosts(F.char, F.hpBuffer) end
  -- a character left down after its combat dies once its death saves run out: brought back at once
  if F.char and not F.manual then G.revive(F.char) end
  if not F.manual then
    G.results.foreign_casts = G.foreignCasts(G.rounds, uuid(F.char), F.plan or {})
    local j = G.judge(G.rounds, G.results.ended, G.results, { me = uuid(F.char), char_acts = F.S and F.S.char_acts })
    G.results.valid, G.results.invalid = j.valid, j.causes
  end
  G.status = "done"
  G.runSeq = (G.runSeq or 0) + 1
  local spec = F.spec or {}
  local rec = { run = G.runSeq, label = F.req.label, req = F.req, mode = F.manual and "manual" or "scripted",
    lane = F.lane and F.lane.id, lanes_run = F.lane and F.lane.run, first_lane = F.lane and F.lane.first,
    difficulty = G.difficulty(), scenario = F.req.scenario, haste = F.req.haste and true or false,
    respec = spec.respec or "planned", spec_id = { build = spec.build, set = spec.set_id, act = spec.act,
      set_name = spec.set }, expect = spec.expect, results = G.results, rounds = G.rounds, dmg = G.dmg,
    hits = G.hits, log = G.log, valid = G.results.valid, invalid = G.results.invalid }
  rec.req.spec = nil
  try(Ext.IO.SaveFile, string.format("LootAdvisor_gauntlet/run_%d_%03d%s.json", F.started, G.runSeq,
    F.lane and ("_" .. F.lane.id) or ""), Ext.Json.Stringify(rec))
  G.dump()
  G.notify({ kind = "result", run = G.runSeq, mode = rec.mode, spec = rec.spec_id, scenario = rec.scenario,
    summary = G.results.summary, expect = spec.expect })
  if F.lane then
    G.lanesGo()
    G.lanesDone()
  end
end

-- Hits the character dealt to the other lanes' characters and enemies (its spell reached the other fight).
function G.crossLaneHits(dmg, me, members, mine)
  local n = 0
  for _, row in ipairs(dmg or {}) do
    if (row.source == me or row.owner == me) and row.target ~= me then
      for id, m in pairs(members or {}) do
        if id ~= mine and m[row.target] and (row.amount or 0) > 0 then n = n + 1 end
      end
    end
  end
  return n
end

-- Boosts older runs gave the character (no Attack of Opportunity, an HP buffer): no longer given, still taken off.
G.AOO_BOOST = "IgnoreLeaveAttackRange()"
G.OLD_HP_BUFFER = 200
G.HP_BUFFER = 0

-- G.run(req): req = {mode = "scripted" | "manual", char (uuid; default the host), build, set, act, scenario
-- ("boss" | "pack" | "defence" | "longday"), haste, tuned, rounds, label, spec (a full spec from run.py)}
-- Returns at once ("started"): the spec is read and the character prepared on timers, so the eval that starts a run
-- stays small and does not time out. Anything that stops a run before or during the fight (bad request, prep failed
-- or timed out, arena not clear) still ends in a run record, marked invalid with its cause.
G.PREP_MS = 120000
-- prep pauses: boosts and statuses settle within a few frames; spawned enemies need a moment before their stats are
-- forced and read back
G.SETTLE_MS, G.SPAWN_MS = 250, 800
function G.run(req)
  if G.F and G.F.state and G.F.state ~= "done" then return "busy" end
  if G.LANES and G.LANES.on and not req.lane then return "busy" end
  local F = { req = req, manual = req.mode == "manual", cooldown = {}, started = math.floor(now() / 1000),
    state = "prep", plan = {}, S = G.SCENARIOS[req.scenario or "boss"] }
  G.F = F
  G.reset()
  G.status = "starting"
  wait(50, function() G.start(F) end)
  return "started"
end

local function stop(F, cause)
  note("FAIL %s", cause)
  finish(F, cause)
end

function G.enterCombat(F)
  pcall(Osi.EnterCombat, F.char, F.enemies[1])
  for _, d in ipairs(F.enemies) do pcall(Osi.EnterCombat, d, F.char) end
end

function G.start(F)
  local req = F.req
  local spec, err = compose(req)
  if not spec then return stop(F, "bad request: " .. tostring(err)) end
  local u = req.char or try(Osi.GetHostCharacter)
  spec.char = u
  local scn = req.scenario or "boss"
  local S = G.SCENARIOS[scn]
  if not S then return stop(F, "unknown scenario " .. tostring(scn)) end
  local C = G.catalog() or {}
  local act = tostring(req.act or spec.act)
  local E0 = req.enemy or (C.enemies and C.enemies[act])
  if not E0 then return stop(F, "no enemy stats for act " .. act) end
  local E = G.scaleEnemy(E0, req.enemy_damage_scale or S.enemy_damage_scale or G.ENEMY_DAMAGE_SCALE)
  F.enemyDamageScale = E.damage_scale
  local A
  if req.arena then
    A = (C.arenas or {})[req.arena]
    if not A then return stop(F, "unknown arena " .. tostring(req.arena)) end
  end
  F.lane = req.lane
  if F.lane and F.lane.no_high and A then
    -- mirrored lanes: the same layout in both, so no high ground unless every lane has one
    local a2 = {}
    for k, v in pairs(A) do a2[k] = v end
    a2.high = nil
    A = a2
  end
  spec.real_respec = req.respec == "real" or spec.real_respec
  G.origin = G.origin or { Osi.GetPosition(u) }
  F.char, F.spec, F.plan, F.S, F.rounds, F.A = u, spec, spec.plan or {}, S, req.rounds or S.rounds, A
  F.prepDeadline = now() + G.PREP_MS
  -- where a run's time goes (ms): prep until the fight starts, then per round R.tm (our turn, the enemies' turns)
  F.tRun = now()
  G.manualPrep = F.manual
  G.prep(spec)
  local function waitPrep()
    if G.status == "prepped" then
      local prepRes = G.results
      G.reset()
      G.results = { prep = prepRes }
      G.status = "fighting"
      local cpos, pts = G.arena(scn, F.plan.mode or "melee", F.plan.selfaoe, G.origin, A)
      pcall(Osi.TeleportToPosition, u, cpos[1], cpos[2], cpos[3], "", 0, 0, 0, 0, 1)
      if not F.manual then
        -- lanes: the lane runner parked the rest of the party; each lane sets its own character's reactions
        G.results.parked = F.lane and G.LANES and G.LANES.parkedCount or G.parkOthers(u, A and A.park)
        G.results.reactions = G.reactionsApply(F.plan, F.lane and { uuid(u) } or nil)
        -- The same setup for both sets of a pair, with the game's rules: Attacks of Opportunity stay on (a cast that
        -- needs a step moves first, G.castSpot) and the sheet's own hit points (a down ends the run, G.step).
        G.results.ignore_leave_attack_range = false
        F.hpBuffer = G.HP_BUFFER
        if F.hpBuffer > 0 then boost(u, string.format("IncreaseMaxHP(%d)", F.hpBuffer)) end
        G.results.hp_buffer = F.hpBuffer
      end
      local buffs = {}
      for _, s in ipairs((C.buffs or {})[act] or {}) do buffs[#buffs + 1] = s end
      if req.haste then buffs[#buffs + 1] = C.haste or "HASTE" end
      for _, s in ipairs(buffs) do pcall(Osi.ApplyStatus, u, s, -1, 1, u) end
      G.results.buffs = buffs
      G.clearLeftovers(uuid(u), A, function(left)
        G.results.leftovers = left
        if A then
          G.results.arena = req.arena
          local intr = G.arenaIntruders(A)
          if #intr > 0 then return stop(F, "arena " .. req.arena .. " not clear: " .. table.concat(intr, "; ")) end
        end
        -- lanes: every lane waits here until all are ready, then all spawn their enemies in the same frame, the first
        -- lane first (G.lanesGo), so no lane's enemies stand around while the other lane still prepares
        if F.lane then
          F.state, F.go = "ready", function() G.spawnAndFight(F, pts, E, buffs, C) end
          return G.lanesGo()
        end
        G.spawnAndFight(F, pts, E, buffs, C)
      end)
    elseif tostring(G.status):match("^failed") then
      stop(F, "prep " .. tostring(G.status))
    elseif now() > F.prepDeadline then
      G.prepGen = (G.prepGen or 0) + 1
      stop(F, string.format("prep timed out after %d s (status %s)", math.floor(G.PREP_MS / 1000), tostring(G.status)))
    else
      wait(G.POLL_MS, waitPrep)
    end
  end
  wait(G.POLL_MS, waitPrep)
end

-- A companion made a player by script keeps its own faction, which the enemies' faction may not be hostile to: the
-- fight never started for one (it left combat each time it was put in). The two factions are set hostile both ways
-- for the run (the game applies a relation a tick later) and put back when it ends; the setup check reads IsEnemy.
-- enemy_faction: the faction the enemies were given (read back from a creature made this frame it is still the
-- template's). -> the changes, in G.laneFactions' shape, or nil when the enemy is hostile already.
function G.makeHostile(u, d, enemy_faction)
  if try(Osi.IsEnemy, u, d) == 1 then return nil end
  local a, b = enemy_faction or try(Osi.GetFaction, d), try(Osi.GetFaction, u)
  if not a or not b then return nil end
  local out = { relations = {} }
  for _, p in ipairs({ { a, b }, { b, a } }) do
    out.relations[p[1] .. "|" .. p[2]] = { a = p[1], b = p[2], was = try(Osi.GetRelation, p[1], p[2]) }
    pcall(Osi.SetRelation, p[1], p[2], 0)
  end
  return out
end

-- The enemies, the setup check, then the fight.
function G.spawnAndFight(F, pts, E, buffs, C)
  local u, spec = F.char, F.spec
  F.enemies = G.spawnEnemies(pts, E, (F.lane and F.lane.enemy_faction) or C.enemy_faction)
  if #F.enemies == 0 then return stop(F, "no enemies") end
  if not F.lane then F.hostility = G.makeHostile(u, F.enemies[1], C.enemy_faction) end
  if F.lane and G.LANES then
    local m = G.LANES.members[F.lane.id] or {}
    m[uuid(u)] = true
    for _, d in ipairs(F.enemies) do m[uuid(d)] = true end
    G.LANES.members[F.lane.id] = m
  end
  wait(G.SPAWN_MS, function()
    G.results.enemies = G.enemyReport(F.enemies)
    G.results.enemy_target = E
    G.results.enemy_damage_scale = F.enemyDamageScale
    pcall(Osi.SetHitpointsPercentage, u, 100)
    G.results.char = G.sheet(u)
    if not F.manual then
      G.unencumber(u, false)
      G.results.encumbered = G.encumbrance(u)
      G.results.precheck = G.precheck(F)
      local me = uuid(u)
      local rep = G.results.reactions and G.results.reactions[me]
      F.setupExtra = { buffs = buffs, encumbered = G.results.encumbered, enemies = F.enemies, E = E,
        scale = F.enemyDamageScale, parked = G.parked, reactions = rep and rep.verified or nil }
      G.results.setup = { start = G.setupCheck(F, spec, "start", F.setupExtra) }
    end
    if F.lane then G.laneSetup(F) end
    G.goFight(F)
  end)
end

-- The fight starts: round 0, the combat entered, the fight loop waits for the character's turn.
function G.goFight(F)
  G.round, G.fighting = 0, true
  G.results.timing = { prep_ms = now() - F.tRun, fight_at = now() - G.t0 }
  F.tFight = now()
  F.hpChar = try(Osi.GetHitpoints, F.char)
  G.enterCombat(F)
  F.state, F.deadline = "wait", now() + G.TURN_WAIT_MS
  if F.manual then
    local rows = G.hotbarRows(F.spec, (G.results.prep or {}).consumables)
    G.hotbarFill(F.char, rows)
    G.notify({ kind = "checklist", rows = rows, hotbar = G.results.hotbar })
  end
  G.notify({ kind = "status", text = "fight on: " .. tostring(F.req.scenario or "boss") ..
    (F.manual and " - your turns" or "") })
end

-- Turn watchdog. Waiting for the character's turn: after TURN_WAIT_MS without it, a recovery is tried (back into
-- combat if the character left it, else the turn of whoever holds it is ended); after TURN_RECOVERIES tries the run
-- ends, invalid. Ending the character's own turn is retried until the engine lets go of it.
G.TURN_WAIT_MS, G.TURN_RECOVERIES, G.END_TURN_MS, G.END_TURN_TRIES, G.ACT_MAX_MS = 45000, 2, 4000, 3, 90000
-- pauses around the character's turn: after the turn starts (the engine refills the turn's resources) and after the
-- last action (the cast has ended: G.step waits for casting() first)
G.ACT_DELAY_MS, G.END_DELAY_MS = 200, 100
function G.recoverTurn(F, inCombat, holders)
  if not inCombat then
    G.enterCombat(F)
    return "the character was out of combat: entered it again"
  end
  if #holders > 0 then
    for _, h in ipairs(holders) do G.endTurn(h) end
    return "ended the turn of " .. table.concat(holders, ", ")
  end
  G.enterCombat(F)
  return "nobody holds the turn: entered combat again"
end
-- The character's own summon (Spiritual Weapon) gets a turn of its own after the character's, and nothing in a scripted
-- run drives it (the fight once waited for a turn the summon never gave back). The harness drives it: its basic
-- attack on the boss, moving first within its own Movement when out of reach and cast from where it then stands,
-- confirmed like a planned cast (a cast, or its damage to the target); an attack asked for and never seen fails the
-- run like a refused cast. A summon with no usable attack, or out of reach, has its turn ended (results.summon_turns
-- says why; summon_turns_ended counts them). Its damage is the side's: results.summon_damage, part of the damage per
-- round.
G.SUMMON_CHECK_MS = 1000
G.SUMMON_ATTACKS = { "Target_MainHandAttack", "Projectile_MainHandAttack", "Target_UnarmedAttack" }
local function summonsOnTurn(F)
  local out = {}
  for _, s in ipairs(F.char and G.leftoverSummons(uuid(F.char), nil) or {}) do
    F.summons = F.summons or {}
    if not F.summons[s] then
      F.summons[s] = true
      local m = F.lane and G.LANES and G.LANES.members[F.lane.id]
      if m then m[s] = true end
    end
    if activeTurn(s) then out[#out + 1] = s end
  end
  return out
end
-- the summon's attack: the first of SUMMON_ATTACKS in its book, else any attack in its book paid with an action point
-- -> spell, or nil and why
function G.summonAttack(s)
  local book = G.spellBook(s)
  if not book then return nil, "no spell book" end
  for _, sp in ipairs(G.SUMMON_ATTACKS) do if book[sp] and not onCooldown(s, sp) then return sp end end
  local ids = {}
  for id in pairs(book) do ids[#ids + 1] = id end
  table.sort(ids)
  for _, id in ipairs(ids) do
    local costs = tostring(try(function() return Ext.Stats.Get(id).UseCosts end) or "")
    if id:find("Attack", 1, true) and not id:find("^Interrupt_") and costs:find("ActionPoint", 1, true)
      and not costs:find("SpellSlot", 1, true) and not onCooldown(s, id) then
      return id
    end
  end
  return nil, "no usable attack"
end
local function summonDone(F, S, result, miss, t)
  S.rec.result, S.rec.ms = result, t and (t - S.t0) or nil
  if miss then
    local R = G.rounds[#G.rounds]
    if R then R.summon_misses = (R.summon_misses or 0) + 1 end
  end
  F.summon = nil
  G.endTurn(S.u)
end
local function summonCast(F, S, t)
  local R = G.rounds[#G.rounds] or { casts = {} }
  S.P = { who = uuid(S.u), spell = S.spell, target = uuid(S.tgt), casts0 = #(R.casts or {}), dmg0 = #G.dmg,
    fails0 = #(R.cast_fails or {}), t0 = t }
  local ok, err = pcall(Osi.UseSpell, S.u, S.spell, S.tgt, S.tgt, 1)
  if not ok then return summonDone(F, S, "failed: engine refused " .. tostring(err), true, t) end
  S.rec.result = "pending"
end
function G.summonBegin(F, s, t)
  local rec = { r = G.round, summon = s }
  G.results.summon_turns = G.results.summon_turns or {}
  G.results.summon_turns[#G.results.summon_turns + 1] = rec
  local spell, why = G.summonAttack(s)
  local tgt = resolveTarget(F, "@boss")
  local range = spell and (spellRange(spell) or 1.5)
  if spell and tgt and dist(s, tgt) > range + resAmount(s, "Movement") + 1.0 then why = "out of reach"; spell = nil end
  if not spell or not tgt then
    rec.result = "turn ended: " .. (tgt and why or "no target")
    G.results.summon_turns_ended = (G.results.summon_turns_ended or 0) + 1
    G.endTurn(s)
    return
  end
  rec.spell = spell
  local S = { u = s, rec = rec, spell = spell, tgt = tgt, t0 = t }
  F.summon = S
  local spot = G.castSpot(F, tgt, range, s)
  if spot then
    local x, y, z = xyz(s)
    rec.move = { x = spot.x, z = spot.z, len = spot.len, aoo_risk = spot.risk }
    if pcall(Osi.CharacterMoveToPosition, s, spot.x, spot.y, spot.z, "Run", "LA_gauntlet_summon") then
      S.moving = { spot = spot, t0 = t, last = { x, y, z }, lastT = t }
      return
    end
  end
  summonCast(F, S, t)
end
function G.summonAdvance(F, S, t)
  if S.moving then
    local M = S.moving
    local x, _, z = xyz(S.u)
    local there = x ~= nil and math.sqrt((x - M.spot.x) ^ 2 + (z - M.spot.z) ^ 2) < 0.5
    if x and math.sqrt((x - M.last[1]) ^ 2 + (z - M.last[3]) ^ 2) > 0.05 then M.last, M.lastT = { x, 0, z }, t end
    if not there and t - M.lastT < 800 and t - M.t0 < G.MOVE_MAX_MS then return end
    S.rec.move.result = there and "there" or "stalled"
    S.moving = nil
    return summonCast(F, S, t)
  end
  local P = S.P
  if not P then return end
  local R = G.rounds[#G.rounds] or {}
  local ev = G.castEvidence(P, R.casts, G.dmg, nil)
  if ev then
    S.rec.confirmed = ev
    return summonDone(F, S, "done", false, t)
  end
  local waited = t - P.t0
  local refused = G.castRefused(P, R.cast_fails)
  if not refused and (waited < G.CONFIRM_MS or (waited < G.CONFIRM_MAX_MS and casting(S.u))) then return end
  summonDone(F, S, refused and "failed: refused by the engine"
    or string.format("failed: no attack seen within %.1f s", waited / 1000), true, t)
end
-- Called while the fight waits for the character's turn: drives the summon whose turn it is (looked for once a
-- second), one attack per summon and round; a summon still holding its turn after that is asked to end it again.
function G.summonStep(F, t)
  if F.manual then return end
  if F.summon then return G.summonAdvance(F, F.summon, t) end
  if t < (F.summonCheck or 0) then return end
  F.summonCheck = t + G.SUMMON_CHECK_MS
  F.summonDone = F.summonDone or {}
  for _, s in ipairs(summonsOnTurn(F)) do
    local key = tostring(G.round) .. ":" .. s
    if F.summonDone[key] then
      G.endTurn(s)
    else
      F.summonDone[key] = true
      return G.summonBegin(F, s, t)
    end
  end
end
local function turnHolders(F)
  local out = {}
  for _, d in ipairs(F.enemies or {}) do if activeTurn(d) then out[#out + 1] = uuid(d) end end
  for _, s in ipairs(summonsOnTurn(F)) do out[#out + 1] = s end
  local other = {}
  for _, u in pairs(F.lane and F.lane.others or {}) do other[uuid(u)] = true end
  for _, m in ipairs(partyMembers()) do
    if m ~= uuid(F.char) and not other[m] and activeTurn(m) then out[#out + 1] = m end
  end
  return out
end

function G.resetFight()
  local F = G.F
  if not F then return "no fight" end
  local req = F.req
  if F.state ~= "done" then finish(F, "reset") end
  wait(1500, function() G.run(req) end)
  return "resetting"
end

local lastTick = 0
-- One step of the fight loop at time t (the Tick handler calls it every 100 ms; the tests call it directly).
function G.step(F, t)
  if F.state ~= "player" then
    local miss = G.reactionGuard(F)
    if miss then return finish(F, "reaction prompt " .. tostring(miss) .. " not covered by the policy") end
  end
  if F.state == "wait" then
    if not activeTurn(F.char) then G.summonStep(F, t) end
    if activeTurn(F.char) then
      F.recoveries = 0
      if G.round >= F.rounds then return finish(F) end
      -- real hit points: a down is a result. The run ends there; the rounds fought and their damage are the record.
      if not F.manual and G.round > 0 and (try(Osi.GetHitpoints, F.char) or 1) <= 0 then return finish(F, "downed") end
      roundStart(F)
      F.state, F.next, F.turnStart = F.manual and "player" or "act", t + G.ACT_DELAY_MS, t
    elseif t > F.deadline then
      F.recoveries = (F.recoveries or 0) + 1
      if F.recoveries > G.TURN_RECOVERIES then
        return finish(F, "the character's turn never came (round " .. G.round .. ")")
      end
      local inCombat = try(Osi.IsInCombat, F.char)
      local what = G.recoverTurn(F, inCombat ~= 0, turnHolders(F))
      G.results.turn_recoveries = G.results.turn_recoveries or {}
      G.results.turn_recoveries[#G.results.turn_recoveries + 1] = { r = G.round, what = what }
      note("turn watchdog (round %d): %s", G.round, what)
      F.deadline = t + G.TURN_WAIT_MS
    end
  elseif F.state == "player" then
    if not activeTurn(F.char) then F.state, F.deadline = "wait", t + 600000 end
  elseif F.state == "act" and t >= F.next then
    local R = G.rounds[#G.rounds]
    if t - (F.turnStart or t) > G.ACT_MAX_MS then
      note("turn took over %d s: ending it", math.floor(G.ACT_MAX_MS / 1000))
      if F.pending then F.pending.rec.result = "failed: turn time limit"; F.pending = nil end
      if F.moving then F.moving.rec.result = "failed: turn time limit (moving)"; F.moving = nil end
      F.state, F.next = "ending", t
      return
    end
    if F.moving then
      if not G.moveSettled(F, t) then F.next = t + G.POLL_MS; return end
      local M = F.moving
      F.moving = nil
      doAction(F, M.a, M.R, M.rec)
      F.next = t + G.POLL_MS
      return
    end
    if F.pending then
      if not G.settle(F, R, t) or F.pending then F.next = t + G.POLL_MS; return end
    end
    if casting(F.char) then F.next = t + 200; return end
    if not F.queue then F.queue, F.qi = G.planRound(F, R), 0 end
    if F.qi < #F.queue then
      F.qi = F.qi + 1
      doAction(F, F.queue[F.qi], R)
      F.next = t + (F.queue[F.qi].ms or 300)
    else
      R.tm.acted = t - G.t0
      F.state, F.next = "ending", t + G.END_DELAY_MS
    end
  elseif F.state == "ending" and t >= F.next then
    if casting(F.char) then F.next = t + 200; return end
    local R = G.rounds[#G.rounds]
    if R then G.riderCheck(F, R) end
    G.endTurn(F.char)
    if R and R.tm then R.tm.end_asked = t - G.t0 end
    F.state, F.endTries, F.next = "ended", 1, t + G.END_TURN_MS
  elseif F.state == "ended" then
    if not activeTurn(F.char) then
      local R = G.rounds[#G.rounds]
      if R and R.tm then R.tm.released = t - G.t0 end
      F.state, F.deadline = "wait", t + G.TURN_WAIT_MS
    elseif t >= F.next then
      if F.endTries >= G.END_TURN_TRIES then return finish(F, "the character's turn could not be ended") end
      G.endTurn(F.char)
      F.endTries, F.next = F.endTries + 1, t + G.END_TURN_MS
    end
  end
end
local function stepLane()
  local F = G.F
  if not F or not F.state or F.state == "done" or F.state == "prep" or F.state == "ready" then return end
  G.step(F, now())
end
local function tick()
  local t = now()
  if t - lastTick < 100 then return end
  lastTick = t
  local L = G.LANES
  if L and L.on then
    for _, id in ipairs(L.order) do G.inLane(id, stepLane) end
    return
  end
  stepLane()
end
if G._tick then pcall(function() Ext.Events.Tick:Unsubscribe(G._tick) end) end
G._tick = Ext.Events.Tick:Subscribe(function() pcall(tick) end)

function G.abort()
  local L = G.LANES
  if L and L.on then
    for _, id in ipairs(L.order) do
      G.inLane(id, function() if G.F and G.F.state ~= "done" then finish(G.F, "aborted") end end)
    end
    G.lanesDone()
  end
  if G.F and G.F.state ~= "done" then finish(G.F, "aborted") end
  -- bystanders a lanes' run moved and did not put back (it stopped before its last lane ended) go back now
  if G.movedNpcs and not (G.LANES and G.LANES.on) then G.npcsBack() end
  if G.barSaved then G.hotbarRestore() end
  return G.status
end

-- ------------------------------------------------------------------------------------------------ two lanes
-- G.runLanes(req): both sets of a pair at once. req = { run_id, lanes = <a "lanes" entry of arenas.json>, first = "A",
-- gap_need = metres, entries = { { id = "A", req = <a run request: char, spec_file, scenario, ...> }, { id = "B", ... } } }
-- Each lane: its own character (two party members with the same build), its own set and enemies, its own arena spot.
-- The rest of the party is parked far away; each lane's enemies get the lane's own faction, hostile to that lane's
-- character only and neutral to the other lane (factions and relations are put back when the last lane ends). Both
-- fights start in the same frame, the first lane first. Every lane writes its own run record.
function G.runLanes(req)
  if G.LANES and G.LANES.on then return "busy" end
  if G.F and G.F.state and G.F.state ~= "done" then return "busy" end
  local C = G.catalog() or {}
  local LS = (C.arenas or {})[req.lanes or ""]
  if not LS or not LS.lanes then return "unknown lanes " .. tostring(req.lanes) end
  local order = { req.first }
  for _, e in ipairs(req.entries or {}) do if e.id ~= req.first then order[#order + 1] = e.id end end
  local L = { on = true, run = req.run_id, order = order, members = {}, chars = {}, set = LS, first = req.first,
    gap_need = req.gap_need, t0 = now() }
  for _, e in ipairs(req.entries or {}) do
    L.chars[e.id] = uuid(e.req.char)
    if not L.chars[e.id] or not LS.lanes[e.id] then return "lane " .. tostring(e.id) .. ": no character or lane" end
  end
  G.LANES = L
  local keep = {}
  for _, u in pairs(L.chars) do keep[u] = true end
  L.parkedCount = G.parkOthers(nil, LS.park, keep)
  if LS.npc_park then
    local areas = {}
    for id in pairs(L.chars) do areas[#areas + 1] = (C.arenas or {})[LS.lanes[id].arena or ""] end
    L.npcs_moved = G.npcsAway(areas, LS.npc_park, LS.margin)
  end
  L.factions = G.laneFactions(L, LS)
  local allHigh = true
  for id in pairs(L.chars) do
    local A = (C.arenas or {})[LS.lanes[id].arena or ""]
    if not (A and A.high) then allHigh = false end
  end
  for _, e in ipairs(req.entries) do
    local others = {}
    for id, u in pairs(L.chars) do if id ~= e.id then others[id] = u end end
    local r = {}
    for k, v in pairs(e.req) do r[k] = v end
    r.arena = LS.lanes[e.id].arena
    r.lane = { id = e.id, run = req.run_id, first = req.first, others = others, enemy_faction = LS.lanes[e.id].enemy_faction,
      no_high = not allHigh, gap_need = req.gap_need }
    G.inLane(e.id, function() return G.run(r) end)
  end
  return "started"
end

-- Each lane's enemies get the lane's faction: hostile (0) to that lane's character, neutral (50) to the other lanes'
-- characters and enemies. Relations are between factions, so when both characters share one (the party's), each gets
-- its lane's character faction for the run. Everything changed is recorded and put back by G.laneFactionsRestore.
function G.laneFactions(L, LS)
  local out = { chars = {}, relations = {}, set = {} }
  local fac, seen = {}, {}
  local shared = false
  for _, id in ipairs(L.order) do
    local f = try(Osi.GetFaction, L.chars[id])
    if f == nil or seen[f] then shared = true end
    if f then seen[f] = true end
  end
  for _, id in ipairs(L.order) do
    local u = L.chars[id]
    local cur = try(Osi.GetFaction, u)
    local want = cur
    local lane = LS.lanes[id] or {}
    if shared and lane.char_faction then
      out.chars[#out.chars + 1] = { char = u, was = cur }
      want = lane.char_faction
      pcall(Osi.SetFaction, u, want)
    end
    fac[id] = { char = want, enemy = lane.enemy_faction }
  end
  local function rel(a, b, v)
    if not a or not b then return end
    local k = a .. "|" .. b
    if not out.relations[k] then out.relations[k] = { a = a, b = b, was = try(Osi.GetRelation, a, b) } end
    pcall(Osi.SetRelation, a, b, v)
    out.set[#out.set + 1] = { a = a, b = b, v = v }
  end
  for _, i in ipairs(L.order) do
    for _, j in ipairs(L.order) do
      local v = (i == j) and 0 or 50
      rel(fac[i].enemy, fac[j].char, v)
      rel(fac[j].char, fac[i].enemy, v)
      if i ~= j then rel(fac[i].enemy, fac[j].enemy, 50) end
    end
  end
  out.factions = fac
  return out
end
function G.laneFactionsRestore(st)
  if not st then return 0 end
  local n = 0
  for _, r in pairs(st.relations or {}) do
    if r.was ~= nil then pcall(Osi.SetRelation, r.a, r.b, r.was); n = n + 1 end
  end
  for _, c in ipairs(st.chars or {}) do
    if c.was then pcall(Osi.SetFaction, c.char, c.was); n = n + 1 end
  end
  return n
end

-- Lane isolation, read by engine as the fights start (any failure fails that lane's run, like a setup mismatch): the
-- other lanes' characters are beyond the spacing the lanes need, the lane's enemies are hostile to its character and
-- not to the other lanes' characters.
function G.laneIsolation(F)
  local out = {}
  local function cmp(field, want, got)
    if want ~= got then out[#out + 1] = { field = field, want = want, got = got } end
  end
  local me = F.char
  for id, u in pairs(F.lane.others or {}) do
    local d = dist(me, u)
    cmp("lane " .. id .. " character beyond " .. tostring(F.lane.gap_need) .. " m", true,
      F.lane.gap_need == nil or d >= F.lane.gap_need)
    for i, e in ipairs(F.enemies or {}) do
      cmp("enemy " .. i .. " not hostile to lane " .. id .. "'s character", 0, try(Osi.IsEnemy, e, u))
    end
  end
  for i, e in ipairs(F.enemies or {}) do cmp("enemy " .. i .. " hostile to the character", 1, try(Osi.IsEnemy, e, me)) end
  return out
end

-- Starts every ready lane once no lane is still preparing (a lane that failed in prep is done and is not waited for):
-- each spawns its enemies, the first lane first; their fights start after the same spawn pause.
function G.lanesGo()
  local L = G.LANES
  if not L or not L.on or L.went then return end
  for _, id in ipairs(L.order) do
    local F = G.laneField(id, "F")
    if not F or (F.state ~= "ready" and F.state ~= "done") then return end
  end
  L.went = true
  L.go_ms = now() - L.t0
  for _, id in ipairs(L.order) do
    G.inLane(id, function()
      local F = G.F
      if F.state ~= "ready" then return end
      F.state = "prep"
      F.go()
    end)
  end
end

-- As the lane's fight starts (every lane's enemies stand by then): the isolation check joins the setup check.
function G.laneSetup(F)
  local iso = G.laneIsolation(F)
  local sc = G.results.setup and G.results.setup.start
  if sc then
    for _, m in ipairs(iso) do sc.mismatches[#sc.mismatches + 1] = m end
    sc.checked = sc.checked + 1
  end
  G.results.lane_isolation = iso
  G.results.lane_factions = G.LANES and G.LANES.factions
  G.results.npcs_moved = G.LANES and G.LANES.npcs_moved
end

-- After the last lane: factions and relations back, the party back.
function G.lanesDone()
  local L = G.LANES
  if not L or not L.on then return end
  for _, id in ipairs(L.order) do
    local F = G.laneField(id, "F")
    if F and F.state ~= "done" then return end
  end
  L.restored = G.laneFactionsRestore(L.factions)
  L.npcs_restored = G.npcsBack()
  G.unparkOthers()
  L.on = false
end

function G.lanesState()
  local L = G.LANES
  if not L then return "no lanes" end
  local parts = { "lanes " .. tostring(L.run) .. (L.on and " on" or " done") }
  for _, id in ipairs(L.order) do
    local F = G.laneField(id, "F")
    parts[#parts + 1] = string.format("%s:%s r%s", id, tostring(G.laneField(id, "status")),
      tostring(G.laneField(id, "round")) .. " " .. tostring(F and F.state))
  end
  return table.concat(parts, " | ")
end

-- ------------------------------------------------------------------------------------------------ hotbar (manual)
-- Manual runs fill the character's hotbar with only what the fight needs, one row each: opener / every turn / bonus
-- action / reactions and toggles / items. The original layout is kept in memory and put back on reset or exit.
-- Spell elements copy the character's own spell book ids, so only spells it knows can be placed (others: "missing").
local function snapshotBar(e)
  local out = {}
  local cs = try(function() return e.HotbarContainer.Containers end)
  for cname, bars in pairs(cs or {}) do
    out[cname] = {}
    for bi, bar in ipairs(bars) do
      out[cname][bi] = {}
      for _, el in ipairs(bar.Elements or {}) do
        out[cname][bi][#out[cname][bi] + 1] = { slot = el.Slot, item = el.Item, passive = el.Passive,
          spell = try(function() return { OriginatorPrototype = el.SpellId.OriginatorPrototype,
            Prototype = el.SpellId.Prototype, Source = el.SpellId.Source, SourceType = el.SpellId.SourceType,
            ProgressionSource = el.SpellId.ProgressionSource } end) }
      end
    end
  end
  return out
end

local function writeBar(e, cname, bi, list)
  local bar = e.HotbarContainer.Containers[cname][bi]
  bar.Elements = {}
  for i, x in ipairs(list) do
    bar.Elements[i] = { Slot = x.slot or (i - 1), Item = x.item, SpellId = x.spell, Passive = x.passive or "",
      IsNew = false }
  end
end

function G.hotbarFill(u, rows)
  local e = ent(u)
  if not e then return false, "no entity" end
  if not G.barSaved then G.barSaved = { char = uuid(u), bars = snapshotBar(e) } end
  local book = {}
  for _, s in ipairs(try(function() return e.SpellBook.Spells end) or {}) do
    local id = try(function() return s.Id.Prototype end)
    if id and not book[id] then
      book[id] = { OriginatorPrototype = s.Id.OriginatorPrototype, Prototype = s.Id.Prototype, Source = s.Id.Source,
        SourceType = s.Id.SourceType, ProgressionSource = s.Id.ProgressionSource }
    end
  end
  local placed, missing = {}, {}
  local ok, err = pcall(function()
    local bars = e.HotbarContainer.Containers.DefaultBarContainer
    for bi = 1, #bars do writeBar(e, "DefaultBarContainer", bi, {}) end
    for ri, row in ipairs(rows) do
      local list = {}
      for _, x in ipairs(row.entries) do
        if x.item then list[#list + 1] = { item = x.item }
        elseif x.passive then list[#list + 1] = { passive = x.passive }
        elseif book[x.spell] then list[#list + 1] = { spell = book[x.spell] }
        else missing[#missing + 1] = x.spell end
      end
      if bars[ri] then writeBar(e, "DefaultBarContainer", ri, list); placed[#placed + 1] = row.label .. ": " .. #list end
    end
    e:Replicate("HotbarContainer")
  end)
  G.results.hotbar = { ok = ok, err = (not ok) and tostring(err) or nil, placed = placed, missing = missing }
  return ok, err
end

function G.hotbarRestore()
  local s = G.barSaved
  if not s then return "nothing saved" end
  local e = ent(s.char)
  local ok, err = pcall(function()
    for cname, bars in pairs(s.bars) do
      for bi, list in ipairs(bars) do writeBar(e, cname, bi, list) end
    end
    e:Replicate("HotbarContainer")
  end)
  if ok then G.barSaved = nil end
  return ok and "restored" or tostring(err)
end

-- rows for a plan, also the printed checklist when the bar cannot be written
function G.hotbarRows(spec, consumables)
  local plan = spec.plan or {}
  if plan.hotbar then
    local rows = {}
    for _, r in ipairs(plan.hotbar) do
      local entries = {}
      for _, sp in ipairs(r.spells or {}) do entries[#entries + 1] = { spell = sp } end
      for _, p in ipairs(r.passives or {}) do entries[#entries + 1] = { passive = p } end
      if r.label == "items" then
        for _, u in ipairs(consumables or {}) do entries[#entries + 1] = { item = u } end
      end
      rows[#rows + 1] = { label = r.label, entries = entries }
    end
    return rows
  end
  local seen = {}
  local function add(t, a)
    local k = a.spell or a.passive or a.item
    if k and not seen[k] then seen[k] = true; t[#t + 1] = a end
  end
  local opener, every, bonus, react, items = {}, {}, {}, {}, {}
  for _, a in ipairs((plan.rounds or {})[1] or {}) do
    if a.group == "bonus" then add(bonus, { spell = a.spell }) else add(opener, { spell = a.spell }) end
    if a.alt then add(opener, { spell = a.alt.spell }) end
  end
  for _, a in ipairs(plan.steady or {}) do
    if a.group == "bonus" then add(bonus, { spell = a.spell }) else add(every, { spell = a.spell }) end
    if a.alt then add(every, { spell = a.alt.spell }) end
  end
  for _, p in ipairs(plan.toggles or {}) do add(react, { passive = p }) end
  for _, s in ipairs(plan.reactions or {}) do add(react, { spell = s }) end
  for _, it in ipairs(plan.item_actions or {}) do add(items, { spell = it.spell }) end
  for _, u in ipairs(consumables or {}) do add(items, { item = u }) end
  return { { label = "opener", entries = opener }, { label = "every turn", entries = every },
    { label = "bonus action", entries = bonus }, { label = "reactions and toggles", entries = react },
    { label = "items", entries = items } }
end

-- ------------------------------------------------------------------------------------------------ net (window)
-- The dev-only window (gauntlet_ui.lua, client side) sends {cmd = "run" | "reset" | "abort" | "reload", ...} on the
-- "Gauntlet" channel; the server answers on "GauntletUI" with status and result messages.
function G.notify(msg)
  pcall(Ext.ServerNet.BroadcastMessage, "GauntletUI", Ext.Json.Stringify(msg))
end
local function onNet(e)
  if e.Channel ~= "Gauntlet" then return end
  local m = try(Ext.Json.Parse, e.Payload)
  if type(m) ~= "table" then return end
  local r
  if m.cmd == "run" then
    m.mode, m.cmd = "manual", nil
    r = G.run(m)
  elseif m.cmd == "reset" then r = G.resetFight()
  elseif m.cmd == "abort" then r = G.abort()
  elseif m.cmd == "reload" then G.CAT = nil; r = G.catalog() and "catalogue loaded" or "no catalogue"
  end
  G.notify({ kind = "status", text = tostring(r) })
end
if G._net then pcall(function() Ext.Events.NetMessage:Unsubscribe(G._net) end) end
G._net = Ext.Events.NetMessage:Subscribe(function(e) pcall(onNet, e) end)

-- pure helpers, exposed for the tests (tests/test_gauntlet.py)
G._itemRule, G._parseCosts, G._doAction, G._roundStart = itemRule, parseCosts, doAction, roundStart
G._equipAll = equipAll
G._onCastFailed, G._onReaction, G._finish, G._summarize = onCastFailed, onReaction, finish, summarize
G._onAttacked, G._onCast = onAttacked, onCast
G._wait, G._tickFn = wait, tick

return "gauntlet v" .. G.VERSION .. " loaded"
