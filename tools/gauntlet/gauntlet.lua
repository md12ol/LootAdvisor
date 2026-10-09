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
G.VERSION = 2

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
local function wait(ms, fn)
  Ext.Timer.WaitFor(ms, function()
    local ok, err = pcall(fn)
    if not ok then G.fail("timer: " .. tostring(err)) end
  end)
end
local function pos(u) return try(Osi.GetPosition, u) end
local function dist(a, b)
  local ax, ay, az = Osi.GetPosition(a)
  local bx, by, bz = Osi.GetPosition(b)
  if not ax or not bx then return 1e9 end
  return math.sqrt((ax - bx) ^ 2 + (ay - by) ^ 2 + (az - bz) ^ 2)
end

function G.reset()
  G.log, G.rounds, G.dmg, G.results, G.status = {}, {}, {}, {}, "idle"
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
local function pay(u, costs)
  local e = ent(u)
  for _, c in ipairs(costs) do
    for _, entry in ipairs(resList(u, c.kind) or {}) do
      if not c.level or c.level == 0 or entry.Level == c.level then
        entry.Amount = math.max(0, entry.Amount - c.n)
        break
      end
    end
  end
  pcall(function() e:Replicate("ActionResources") end)
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
function G.equipped(u)
  local out = {}
  for _, s in ipairs(SLOTS) do
    local it = try(Osi.GetEquippedItem, u, s)
    if it then out[s] = it end
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
    "SetRelationTemporaryHostile", "SetHostileAndEnterCombat" }) do
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
local function equipAll(u, items, i, cb)
  if i > #items then return cb() end
  local spec = items[i]
  local x, y, z = Osi.GetPosition(u)
  local it = try(Osi.CreateAt, spec.template, x, y, z, 0, 0, "")
  if not it then
    G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, err = "CreateAt failed" }
    return equipAll(u, items, i + 1, cb)
  end
  pcall(Osi.ToInventory, it, u, 1, 0, 0)
  wait(200, function()
    if spec.use and G.manualPrep then
      G.results.consumables = G.results.consumables or {}
      G.results.consumables[#G.results.consumables + 1] = it
      G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, got = "inventory", uuid = it }
      return equipAll(u, items, i + 1, cb)
    end
    if spec.use then
      pcall(Osi.Use, u, it, "")
      G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, got = "used", uuid = it }
      return wait(800, function() equipAll(u, items, i + 1, cb) end)
    end
    pcall(Osi.Equip, u, it, 1, 0, 0)
    wait(350, function()
      local where
      for s, e in pairs(G.equipped(u)) do if uuid(e) == uuid(it) then where = s end end
      G.results.items[#G.results.items + 1] = { want = spec.slot, stats = spec.stats, got = where, uuid = it }
      note("item %s want %s got %s", spec.stats, spec.slot, tostring(where))
      equipAll(u, items, i + 1, cb)
    end)
  end)
end

-- ------------------------------------------------------------------------------------------------ prep
-- spec.char, spec.sheet = {abilities = {STR = ..}, hp, prof, ac_unarmoured}, spec.passives_add / passives_remove,
-- spec.spells_add, spec.boosts, spec.slots = {["1"] = 4, ...}, spec.resources = {{kind, n, level}}, spec.items,
-- spec.statuses (fixed buffs), spec.park = {x, y, z} for the other party members (solo)
function G.prep(spec)
  G.reset()
  G.status = "prepping"
  local u = spec.char
  G.results.items = {}
  G.results.before = G.sheet(u)
  for _, row in ipairs(try(function() return Osi.DB_Players:Get(nil) end) or {}) do
    if uuid(row[1]) ~= uuid(u) and spec.park then
      pcall(Osi.TeleportToPosition, row[1], spec.park[1], spec.park[2], spec.park[3], "", 0, 0, 0, 0, 1)
    end
  end
  pcall(Osi.RemoveBoosts, u, "", 0, CAUSE, u)
  G.strip(u)
  wait(600, function()
    for _, p in ipairs(spec.passives_remove or {}) do
      if try(Osi.HasPassive, u, p) == 1 then pcall(Osi.RemovePassive, u, p); note("passive -%s", p) end
    end
    for _, p in ipairs(spec.passives_add or {}) do
      if try(Osi.HasPassive, u, p) ~= 1 then pcall(Osi.AddPassive, u, p); note("passive +%s", p) end
    end
    for _, sp in ipairs(spec.spells_add or {}) do pcall(Osi.AddSpell, u, sp, 0, 1) end
    for _, b in ipairs(spec.boosts or {}) do boost(u, b) end
    wait(500, function()
      local cur = abilities(u)
      for short, want in pairs(spec.sheet.abilities or {}) do
        local n = ABIL_SHORT[short]
        local d = want - (cur[n] or want)
        if d ~= 0 then boost(u, string.format("Ability(%s,%d)", n, d)) end
      end
      wait(500, function()
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
        wait(400, function()
          G.results.bare = G.sheet(u)
          equipAll(u, spec.items or {}, 1, function()
            for _, st in ipairs(spec.statuses or {}) do pcall(Osi.ApplyStatus, u, st, -1, 1, u); note("status %s", st) end
            wait(600, function()
              G.refill(u, "long")
              pcall(Osi.SetHitpointsPercentage, u, 100)
              G.results.after = G.sheet(u)
              G.status = "prepped"
              G.dump()
            end)
          end)
        end)
      end)
    end)
  end)
  return G.status
end

-- ------------------------------------------------------------------------------------------------ enemies
-- E = {template, ac, save, atk, dmg, dc, hp}. Stats are forced, then VERIFIED in G.results.enemies (a difficulty
-- setting or the template could change them).
local function forceEnemy(d, E)
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
    wait(300, function() pcall(Osi.SetHitpointsPercentage, d, 100) end)
  end)
end

function G.spawnEnemies(list, E, faction)
  local out = {}
  for _, p in ipairs(list) do
    local d = try(Osi.CreateAt, E.template, p[1], p[2], p[3], 0, 0, "")
    if d then
      out[#out + 1] = d
      if faction then pcall(Osi.SetFaction, d, faction) end
      forceEnemy(d, E)
    else
      note("enemy spawn failed at %.1f %.1f", p[1], p[3])
    end
  end
  return out
end

function G.enemyReport(list)
  local out = {}
  for _, d in ipairs(list) do
    local e = ent(d)
    local res = {}
    for i, v in ipairs(e and try(function() return e.Resistances.Resistances end) or {}) do res[i] = tostring(v) end
    out[#out + 1] = { uuid = d, ac = e and try(function() return e.Resistances.AC end), hp = try(Osi.GetMaxHitpoints, d),
      abilities = abilities(d), prof = e and try(function() return e.Stats.ProficiencyBonus end), res = res }
  end
  return out
end

-- ------------------------------------------------------------------------------------------------ events
-- Damage log from Osiris AttackedBy (one row per damage type per hit) and the spell log from CastedSpell, registered
-- once per game session (re-loading this file keeps them).
local function onAttacked(def, ownerAtt, att, dtype, amount, cause, _sid)
  if not G.fightOn then return end
  G.dmg[#G.dmg + 1] = { r = G.round, t = now() - G.t0, target = uuid(def), source = uuid(att), owner = uuid(ownerAtt),
    type = dtype, amount = amount, cause = cause }
end
local function onCast(caster, spell)
  if not G.fightOn then return end
  local R = G.rounds[#G.rounds]
  if R then R.casts[#R.casts + 1] = { who = uuid(caster), spell = spell } end
end
if not G._listeners then
  G._listeners = {
    attacked = pcall(Ext.Osiris.RegisterListener, "AttackedBy", 7, "after", function(...) pcall(onAttacked, ...) end),
    cast = pcall(Ext.Osiris.RegisterListener, "CastedSpell", 5, "after", function(...) pcall(onCast, ...) end),
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

-- one scripted action: {spell, target, group ("action" | "bonus" | "free"), cost (override; "free" = granted, e.g.
-- an Extra Attack), requires ("action" / "surge": only after that succeeded this round), alt (fallback action), ms}
local function doAction(F, a, R)
  if a.requires and not R.done[a.requires] then
    R.actions[#R.actions + 1] = { spell = a.spell, why = a.why, result = "skipped: no " .. a.requires .. " this round" }
    return
  end
  local tgt = resolveTarget(F, a.target or "@boss")
  local rec = { spell = a.spell, target = a.target, why = a.why, group = a.group, item = a.item }
  R.actions[#R.actions + 1] = rec
  local function fallback(reason)
    rec.result = reason
    if a.alt then rec.result = reason .. " -> alt"; return doAction(F, a.alt, R) end
  end
  if not tgt then return fallback("no target") end
  local costs = a.cost == "free" and {} or (a.cost and parseCosts(a.cost) or spellCosts(a.spell))
  local ok, why = canPay(F.char, costs)
  if not ok then return fallback("no resource " .. tostring(why)) end
  if a.per and F.cooldown[a.spell] then return fallback("used this rest") end
  local range = a.range or spellRange(a.spell)
  if tgt ~= F.char and range and dist(F.char, tgt) > range + 1.0 then
    return fallback(string.format("out of range %.1f > %.1f", dist(F.char, tgt), range))
  end
  local okc, err
  if a.at_target_pos then
    local x, y, z = Osi.GetPosition(tgt)
    okc, err = pcall(Osi.UseSpellAtPosition, F.char, a.spell, x, y, z, 1)
  else
    okc, err = pcall(Osi.UseSpell, F.char, a.spell, tgt)
  end
  if not okc then return fallback("engine refused " .. tostring(err)) end
  pay(F.char, costs)
  rec.result = "done"
  if a.group then R.done[a.group] = true end
  if a.spell == "Shout_ActionSurge" then R.done.surge = true end
  if a.per then F.cooldown[a.spell] = a.per end
end

-- The shared adaptive rule (identical for both sets of a pair): item actions from plan.item_actions, in their
-- priority order. A per-rest action spell not used since the last rest replaces the round's core action group; a
-- bonus-action item spell fills the bonus action when the core plan leaves it free; reactions stay with the engine.
-- Every candidate is logged (used / skipped + reason) in R.item_rule.
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
      item = it.item, per = it.per ~= "none" and it.per or nil, at_target_pos = it.at_target_pos }
    if it.group == "reaction" then
      log.result = "skipped: reactions are left to the engine"
    elseif it.per ~= "none" and F.cooldown[it.spell] then
      log.result = "skipped: used this rest"
    elseif it.group == "action" then
      if replaced then
        log.result = "skipped: one item action per round"
      else
        local keep = {}
        for _, a in ipairs(out) do
          if a.group ~= "action" and a.requires ~= "action" then keep[#keep + 1] = a end
        end
        table.insert(keep, 1, entry)
        out, replaced = keep, true
        log.result = "used: replaces the core action"
      end
    elseif it.group == "bonus" then
      if hasBonus then
        log.result = "skipped: the core plan uses the bonus action"
      else
        out[#out + 1] = entry
        hasBonus = true
        log.result = "used: free bonus action"
      end
    end
  end
  return out
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

local function ground(x, z, nearY)
  local best
  for _, y in ipairs(try(Ext.Level.GetHeightsAt, x, z) or {}) do
    if not best or math.abs(y - nearY) < math.abs(best - nearY) then best = y end
  end
  if best and math.abs(best - nearY) < 2.0 then return best end
  return nearY
end

function G.arena(scn, mode, selfaoe, origin)
  local S = G.SCENARIOS[scn]
  local x0, y0, z0 = origin[1], origin[2], origin[3]
  local d = G.RANGE[mode] or 6.0
  local pts = {}
  local n = S.enemies
  if S.ring or selfaoe or mode == "melee" then
    local r = selfaoe and 2.2 or 1.6
    for i = 1, n do
      local a = (i - 1) * (2 * math.pi / math.max(n, 1)) * (selfaoe and 1 or 0.35)
      pts[#pts + 1] = { x0 + r * math.cos(a), 0, z0 + r * math.sin(a) }
    end
  else
    local offs = { { 0, 0 }, { 1.8, 0 }, { 0, 1.8 }, { 1.8, 1.8 } }
    for i = 1, n do pts[#pts + 1] = { x0 + d + offs[i][1], 0, z0 + offs[i][2] - (n > 1 and 0.9 or 0) } end
  end
  for _, p in ipairs(pts) do p[2] = ground(p[1], p[3], y0) end
  return { x0, y0, z0 }, pts
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
  local R = { r = G.round, actions = {}, casts = {}, done = {}, char_hp_before = try(Osi.GetHitpoints, F.char) }
  R.char_hp_lost_enemy_turns = math.max(0, (F.hpChar or 0) - (R.char_hp_before or 0))
  pcall(Osi.SetHitpointsPercentage, F.char, 100)
  for _, d in ipairs(F.enemies) do pcall(Osi.SetHitpointsPercentage, d, 100) end
  local S = F.S
  if S.short_rest_every and G.round > 1 and (G.round - 1) % S.short_rest_every == 0 then
    G.refill(F.char, "short")
    for k, per in pairs(F.cooldown) do if per == "short" then F.cooldown[k] = nil end end
    R.short_rest = true
  end
  F.hpChar = try(Osi.GetHitpoints, F.char)
  G.rounds[#G.rounds + 1] = R
  if F.manual then F.queue, F.qi = {}, 0; return end
  local plan = F.plan
  local k = G.round
  if S.fight_rounds then k = ((G.round - 1) % S.fight_rounds) + 1 end
  local list = (plan.rounds or {})[k] or plan.steady or {}
  if S.char_acts == false then
    list = (k == 1) and (plan.defence_opening or {}) or {}
  else
    list = itemRule(F, list, R)
  end
  F.queue, F.qi = list, 0
end

-- per-run numbers (the same for scripted and manual runs)
local function summarize(F)
  local enemies = {}
  for i, d in ipairs(F.enemies) do enemies[uuid(d)] = i end
  local me = uuid(F.char)
  local per = {}
  for _, R in ipairs(G.rounds) do per[R.r] = { dealt = 0, taken = 0, hits_taken = 0, rows = 0 } end
  for _, row in ipairs(G.dmg) do
    local p = per[row.r]
    if p then
      if enemies[row.target] and (row.source == me or row.owner == me) then
        p.dealt = p.dealt + (row.amount or 0)
        p.rows = p.rows + 1
      elseif row.target == me then
        p.taken = p.taken + (row.amount or 0)
        p.hits_taken = p.hits_taken + 1
      end
    end
  end
  local dealt, taken = {}, {}
  for r = 1, #G.rounds do
    dealt[r] = per[r] and per[r].dealt or 0
    taken[r] = per[r] and per[r].taken or 0
  end
  local function mean(t)
    local s = 0
    for _, v in ipairs(t) do s = s + v end
    return #t > 0 and s / #t or 0
  end
  local hp = try(Osi.GetMaxHitpoints, F.char) or 0
  local tk = mean(taken)
  local failed = 0
  for _, R in ipairs(G.rounds) do
    for _, a in ipairs(R.actions) do if a.result ~= "done" then failed = failed + 1 end end
  end
  return { rounds = #G.rounds, dpr = mean(dealt), dealt = dealt, taken = taken, taken_per_round = tk, max_hp = hp,
    turns_survived = tk > 0 and hp / tk or nil, actions_not_done = failed }
end

function G.difficulty()
  return { osi = try(Osi.GetDifficulty), note = G.difficultyNote }
end

local function finish(F, why)
  G.fightOn = false
  F.state = "done"
  for _, d in ipairs(F.enemies or {}) do
    if not pcall(Osi.RequestDelete, d) then pcall(Osi.Die, d, 0, "NULL_00000000-0000-0000-0000-000000000000", 0, 0) end
  end
  if F.manual and G.barSaved and why ~= "reset" then G.results.hotbar_restore = G.hotbarRestore() end
  G.results.summary = summarize(F)
  G.results.ended = why or "rounds done"
  G.status = "done"
  G.runSeq = (G.runSeq or 0) + 1
  local rec = { run = G.runSeq, label = F.req.label, req = F.req, mode = F.manual and "manual" or "scripted",
    difficulty = G.difficulty(), scenario = F.req.scenario, haste = F.req.haste and true or false,
    respec = F.spec.respec or "planned", spec_id = { build = F.spec.build, set = F.spec.set_id, act = F.spec.act,
      set_name = F.spec.set }, expect = F.spec.expect, results = G.results, rounds = G.rounds, dmg = G.dmg,
    log = G.log }
  rec.req.spec = nil
  try(Ext.IO.SaveFile, string.format("LootAdvisor_gauntlet/run_%d_%03d.json", F.started, G.runSeq),
    Ext.Json.Stringify(rec))
  G.dump()
  G.notify({ kind = "result", run = G.runSeq, mode = rec.mode, spec = rec.spec_id, scenario = rec.scenario,
    summary = G.results.summary, expect = F.spec.expect })
end

-- G.run(req): req = {mode = "scripted" | "manual", char (uuid; default the host), build, set, act, scenario
-- ("boss" | "pack" | "defence" | "longday"), haste, tuned, rounds, label, spec (a full spec from run.py)}
function G.run(req)
  if G.F and G.F.state and G.F.state ~= "done" then return "busy" end
  local spec, err = compose(req)
  if not spec then G.fail(err); return G.status end
  local u = req.char or try(Osi.GetHostCharacter)
  spec.char = u
  local scn = req.scenario or "boss"
  local S = G.SCENARIOS[scn]
  if not S then G.fail("unknown scenario " .. tostring(scn)); return G.status end
  local C = G.catalog() or {}
  local act = tostring(req.act or spec.act)
  local E = req.enemy or (C.enemies and C.enemies[act])
  if not E then G.fail("no enemy stats for act " .. act); return G.status end
  G.origin = G.origin or { Osi.GetPosition(u) }
  local F = { char = u, req = req, spec = spec, plan = spec.plan or {}, S = S, manual = req.mode == "manual",
    rounds = req.rounds or S.rounds, cooldown = {}, started = math.floor(now() / 1000), state = "prep" }
  G.manualPrep = F.manual
  G.prep(spec)
  G.F = F
  local function waitPrep()
    if G.status == "prepped" then
      local prepRes = G.results
      G.reset()
      G.results = { prep = prepRes }
      G.status = "fighting"
      local cpos, pts = G.arena(scn, F.plan.mode or "melee", F.plan.selfaoe, G.origin)
      pcall(Osi.TeleportToPosition, u, cpos[1], cpos[2], cpos[3], "", 0, 0, 0, 0, 1)
      local buffs = {}
      for _, s in ipairs((C.buffs or {})[act] or {}) do buffs[#buffs + 1] = s end
      if req.haste then buffs[#buffs + 1] = C.haste or "HASTE" end
      for _, s in ipairs(buffs) do pcall(Osi.ApplyStatus, u, s, -1, 1, u) end
      G.results.buffs = buffs
      F.enemies = G.spawnEnemies(pts, E, C.enemy_faction)
      if #F.enemies == 0 then G.fail("no enemies"); F.state = "done"; return end
      wait(1500, function()
        G.results.enemies = G.enemyReport(F.enemies)
        G.results.enemy_target = E
        G.results.char = G.sheet(u)
        G.round, G.fightOn = 0, true
        F.hpChar = try(Osi.GetHitpoints, u)
        pcall(Osi.EnterCombat, u, F.enemies[1])
        for _, d in ipairs(F.enemies) do pcall(Osi.EnterCombat, d, u) end
        F.state, F.deadline = "wait", now() + 60000
        if F.manual then
          local rows = G.hotbarRows(spec, (G.results.prep or {}).consumables)
          G.hotbarFill(u, rows)
          G.notify({ kind = "checklist", rows = rows, hotbar = G.results.hotbar })
        end
        G.notify({ kind = "status", text = "fight on: " .. scn .. (F.manual and " - your turns" or "") })
      end)
    elseif tostring(G.status):match("^failed") then
      F.state = "done"
    else
      wait(300, waitPrep)
    end
  end
  wait(300, waitPrep)
  return "started"
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
local function tick()
  local F = G.F
  if not F or not F.state or F.state == "done" or F.state == "prep" then return end
  local t = now()
  if t - lastTick < 100 then return end
  lastTick = t
  if F.state == "wait" then
    if activeTurn(F.char) then
      if G.round >= F.rounds then return finish(F) end
      roundStart(F)
      F.state, F.next = F.manual and "player" or "act", t + 400
    elseif t > F.deadline then
      finish(F, "the character's turn never came (round " .. G.round .. ")")
    end
  elseif F.state == "player" then
    if not activeTurn(F.char) then F.state, F.deadline = "wait", t + 600000 end
  elseif F.state == "act" and t >= F.next then
    if casting(F.char) then F.next = t + 200; return end
    if F.qi < #F.queue then
      F.qi = F.qi + 1
      doAction(F, F.queue[F.qi], G.rounds[#G.rounds])
      F.next = t + (F.queue[F.qi].ms or 1800)
    else
      F.state, F.next = "ending", t + 300
    end
  elseif F.state == "ending" and t >= F.next then
    if casting(F.char) then F.next = t + 200; return end
    G.endTurn(F.char)
    F.state, F.deadline = "wait", t + 90000
  end
end
if G._tick then pcall(function() Ext.Events.Tick:Unsubscribe(G._tick) end) end
G._tick = Ext.Events.Tick:Subscribe(function() pcall(tick) end)

function G.abort()
  if G.F and G.F.state ~= "done" then finish(G.F, "aborted") end
  if G.barSaved then G.hotbarRestore() end
  return G.status
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
G._itemRule, G._parseCosts = itemRule, parseCosts

return "gauntlet v" .. G.VERSION .. " loaded"
