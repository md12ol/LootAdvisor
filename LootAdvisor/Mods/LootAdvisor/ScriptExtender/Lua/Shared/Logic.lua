-- LootAdvisor: which items to recommend for the selected character (pure logic; runs on the server, which has the
-- story state). Rules:
--  1 closed story paths -> no marker, greyed "path closed" in the list
--  2/16 unique items: owner list `o` (game-data fit); others see "better on X" and their next pick moves up;
--       an exact tie (`ot`) between party members is the player's pick (the wearer keeps it), see L.Ties
--  3 traders -> marker on the trader; 'l' items (random loot, generic +1/+2) list only with odds, no frame/text
--  4/5 markers = best + runner-up per slot of the CURRENT act, still obtainable now; owned items keep the frame only
--  6 build: live class levels -> closest build of the character; tie -> BuildAdvisor's pick; none -> main stat;
--       characters without builds of their own (companions, Tavs, hirelings) and origins respecced away from all of
--       theirs: the most similar Build Advisor build (L.ClosestBuild), shown as the closest build
--  markers for everyone in the party, camp and who may still join (L.MergeMarkers); arrows stay the selected's
--  8 items that cost an origin companion are left out unless that already happened
--  12 off-screen arrows only for the 5 best (client paints; rows carry the rank)
--  15 earlier-act items ("ow" slots, la < act) count only when owned and never get a marker
--  17 act = the act the item is really obtainable in (data field d / la)

LA = LA or {}
LA.Logic = {}
local L = LA.Logic

L.COST_PATHS = { karlach_kill = "karlach", shadowheart_kill = "shadowheart", astarion_kill = "astarion",
                 gale_kill = "gale", wyll_kill = "wyll", laezel_kill = "laezel" }
L.PATH_LABEL = {
  shar = "Shadowheart's Shar path", selune = "Shadowheart's Selune path", goblins = "the goblins raiding the Grove",
  tieflings = "saving the tieflings (Grove)", isobel_kill = "Isobel's death (Last Light falls)",
  isobel_dead = "Isobel's death", isobel_alive = "Isobel alive", bhaal_accept = "accepting Bhaal",
  bhaal_refuse = "refusing Bhaal", mizora_freed = "freeing Mizora", ravengard_rescued = "rescuing Duke Ravengard",
  astarion_ascends = "Astarion's ascension", kagha_kill = "killing Kagha", nere_kill = "Nere's death",
  nere_dead = "Nere's death", tribunal = "the Murder Tribunal (Unholy Assassin)",
  prisoners_rescued = "rescuing the Moonrise prisoners", durge_alfira = "Alfira's murder",
  karlach_kill = "Karlach's death", shadowheart_kill = "Shadowheart's death", astarion_kill = "Astarion's death",
  gale_kill = "Gale's death", wyll_kill = "Wyll's death", laezel_kill = "Lae'zel's death",
  ethel_spared = "sparing Auntie Ethel", absolute_brand = "accepting the Absolute's brand",
  anders_or_karlach_kill = "killing Anders' group (or Karlach)",
}
local function label(x) return L.PATH_LABEL[x] or x:gsub("_", " ") end

-- conditions string -> "ok" | "closed" | "excluded", reason text, notes
function L.EvalCond(c, state, charKey, act)
  if type(c) ~= "string" or c == "" then return "ok" end
  local verdict, reason, notes = "ok", nil, {}
  local function close(why) if verdict == "ok" then verdict, reason = "closed", why end end
  for code in c:gmatch("[^,%s]+") do
    local neg = code:sub(1, 1) == "!"
    local body = neg and code:sub(2) or code
    local kind, arg = body:match("^(%w+):(.+)$")
    if not kind then kind, arg = "path", body end
    if body == "durge" and not neg then
      if not state.durge then close("Dark Urge campaign only") end
    elseif kind == "origin" or kind == "party" then
      local cs = state.comp and state.comp[arg]
      if arg ~= charKey and cs then
        if cs.dead then close(LA.CharName(arg) .. " is dead")
        elseif not cs.team and (act or 1) >= 2 then close("needs " .. LA.CharName(arg) .. " in your team") end
      end
    elseif kind == "path" then
      local st = state.paths and state.paths[arg]
      if neg then
        if st == "yes" then close("lost: " .. label(arg) .. " happened") end
      elseif L.COST_PATHS[arg] then
        if st ~= "yes" then verdict, reason = "excluded", "costs " .. label(arg) end
      elseif st == "no" then
        close("path closed: needs " .. label(arg))
      end
    elseif kind == "timing" or kind == "note" then
      notes[#notes + 1] = arg:gsub("_", " ")
    end
  end
  return verdict, reason, notes
end

-- how close a build is to the live class levels: levels in common (+2 per matching subclass), minus half the levels
-- of classes the build does not have. -> score, any class in common
local function classScore(b, info, ctx)
  -- class levels + subclasses from LootData (b.cl / b.sc, game names), else the generated table
  local cl = (type(b.cl) == "table" and next(b.cl)) and b.cl or (info or {}).cl or {}
  local sc = type(b.sc) == "table" and b.sc or nil
  local score, overlap = 0, false
  for _, c in ipairs(ctx.classes or {}) do
    local want = cl[c.name]
    if want then
      score = score + math.min(c.level or 0, want)
      overlap = true
      local live = LA.Norm(c.sub)
      if live ~= "" then
        local wantSub = sc and sc[c.name] and LA.Norm(sc[c.name]) or nil
        if wantSub and wantSub ~= "" then
          if live:find(wantSub, 1, true) or wantSub:find(live, 1, true) then score = score + 2 end
        elseif tostring(b.n):lower():find(tostring(c.sub):lower(), 1, true) then
          score = score + 2
        end
      end
    else
      score = score - 0.5 * (c.level or 0)
    end
  end
  return score, overlap
end

-- the highest ability of the live character, else the main ability its Build Advisor build names (ctx.main)
local function mainAbility(ctx)
  local hi, hiv = nil, -1
  for _, k in ipairs({ "STR", "DEX", "CON", "INT", "WIS", "CHA" }) do
    local v = (ctx.abilities or {})[k]
    if type(v) == "number" and v > hiv then hi, hiv = k, v end
  end
  return hi or ctx.main
end

-- Build matching (rule 6). ctx.classes = { {name="Rogue", sub="Thief", level=12}, ... }
function L.MatchBuild(charKey, ctx, baPick, baOrder)
  local cd = LA.Data.chars[charKey]
  if not cd then return nil end
  local info = (LA.Mod.builds or {})[charKey] or {}
  local best, bestScore, tied = nil, -1e9, {}
  local anyOverlap = false
  for _, b in ipairs(cd.b) do
    local score, overlap = classScore(b, info[b.id], ctx)
    anyOverlap = anyOverlap or overlap
    if score > bestScore + 1e-6 then best, bestScore, tied = b, score, { b }
    elseif math.abs(score - bestScore) <= 1e-6 then tied[#tied + 1] = b end
  end
  if not anyOverlap then
    -- no class in common: generic pick by main ability
    local hi = mainAbility(ctx)
    for _, b in ipairs(cd.b) do
      if (info[b.id] or {}).main == hi then return b, "no build matches your classes - picked by main ability " .. tostring(hi) end
    end
    return cd.b[1], "no build matches your classes - first build"
  end
  if #tied > 1 then
    for _, b in ipairs(tied) do if b.id == baPick then return b, "closest to your classes; Build Advisor's pick" end end
    for _, id in ipairs(baOrder or {}) do
      for _, b in ipairs(tied) do if b.id == id then return b, "closest to your classes; Build Advisor's order" end end
    end
  end
  return best, "closest to your class levels"
end

-- the origin characters whose builds Loot Advisor scores, in a fixed order (ties between builds go to the first)
L.ORIGINS = { "astarion", "gale", "karlach", "laezel", "shadowheart", "wyll", "darkurge" }

-- ---------------------------------------------------------------- closest build
-- How alike a character and a build are, 0-1: the weighted share of what can be read from the character. A part the
-- character gives no data for (no subclass yet, no abilities, no weapon) is left out of the weights for every build
-- alike, so the ranking stays comparable.
L.SIM_WEIGHTS = { class = 55, sub = 20, main = 15, caster = 5, weapon = 5 }
L.FULL_CASTERS = { Wizard = true, Sorcerer = true, Cleric = true, Druid = true, Bard = true, Warlock = true }
L.HALF_CASTERS = { Paladin = true, Ranger = true }
local ATK_FAMILY = { melee1h = "melee", finesse = "melee", melee2h = "melee", thrown = "melee", ranged = "ranged",
                     handxbow = "ranged" }
local ABIL = { "STR", "DEX", "CON", "INT", "WIS", "CHA" }

-- 2 = mostly a full caster, 1 = some casting (a full caster dip, Paladin / Ranger half, Eldritch Knight, Arcane
-- Trickster), 0 = none: the scale of the generated builds table's caster field. nil without class levels.
function L.CasterType(classes)
  local total, full, half, third = 0, 0, 0, false
  for _, c in ipairs(classes or {}) do
    local n = tonumber(c.level) or 0
    total = total + n
    if L.FULL_CASTERS[c.name] then full = full + n elseif L.HALF_CASTERS[c.name] then half = half + n end
    local s = LA.Norm(c.sub)
    if s:find("eldritchknight", 1, true) or s:find("arcanetrickster", 1, true) then third = true end
  end
  if total == 0 then return nil end
  if full / total >= 0.6 then return 2 end
  if full > 0 or half / total >= 0.5 or third then return 1 end
  return 0
end

-- the character's highest abilities (all of them when tied), else the main ability of its stand-in build (ctx.main)
local function mainAbilities(ctx)
  local hi, set = -1, {}
  for _, k in ipairs(ABIL) do
    local v = (ctx.abilities or {})[k]
    if type(v) == "number" then
      if v > hi then hi, set = v, { [k] = true } elseif v == hi then set[k] = true end
    end
  end
  if next(set) == nil and ctx.main then set[ctx.main] = true end
  return set
end

-- ctx.atk: the styles of the equipped weapons (Server/State.lua S.WeaponStyles), a list or one string
local function liveStyles(ctx)
  local out = {}
  if type(ctx.atk) == "string" and ctx.atk ~= "" then out[ctx.atk] = true end
  if type(ctx.atk) == "table" then for _, a in ipairs(ctx.atk) do out[a] = true end end
  return out
end

local function subMatches(live, want)
  return live:find(want, 1, true) ~= nil or want:find(live, 1, true) ~= nil
end

-- -> similarity 0-1, parts { class, sub, main, caster, weapon = 0-1, nil when the character gives no data for it;
-- prec = share of the build's levels in classes the character has, nclass = classes in the build }
function L.Similarity(b, info, ctx)
  info = info or {}
  local cl = (type(b.cl) == "table" and next(b.cl)) and b.cl or info.cl or {}
  local sc = type(b.sc) == "table" and b.sc or {}
  local total, shared, subLv, subHit, inLive = 0, 0, 0, 0, {}
  for _, c in ipairs(ctx.classes or {}) do
    local n = tonumber(c.level) or 0
    local want = cl[c.name]
    total = total + n
    inLive[c.name] = true
    if want then shared = shared + math.min(n, want) end
    local live = LA.Norm(c.sub)
    if live ~= "" and n > 0 then
      subLv = subLv + n
      local ws = want and LA.Norm(sc[c.name]) or nil
      if ws == "" then subHit = subHit + 0.5 * n -- the build takes any subclass of that class
      elseif ws and subMatches(live, ws) then subHit = subHit + n end
    end
  end
  local blv, bin, nclass = 0, 0, 0
  for c, n in pairs(cl) do
    blv, nclass = blv + n, nclass + 1
    if inLive[c] then bin = bin + n end
  end
  local p = { prec = blv > 0 and bin / blv or 0, nclass = nclass }
  if total > 0 then p.class = shared / total end
  if subLv > 0 then p.sub = subHit / subLv end
  local mains = mainAbilities(ctx)
  if next(mains) ~= nil then p.main = (info.main and mains[info.main]) and 1 or 0 end
  local live = L.CasterType(ctx.classes)
  if live then
    local want = tonumber(info.caster)
    p.caster = want and (1 - math.abs(live - want) / 2) or 0
  end
  -- a caster's staff or dagger says nothing about its build
  local styles = liveStyles(ctx)
  if next(styles) ~= nil and live ~= 2 then
    local want = info.atk or ""
    p.weapon = 0
    if styles[want] then p.weapon = 1
    elseif want ~= "" then
      for a in pairs(styles) do if ATK_FAMILY[a] == ATK_FAMILY[want] then p.weapon = 0.5 end end
    end
  end
  local sum, wsum = 0, 0
  for k, w in pairs(L.SIM_WEIGHTS) do
    if p[k] then sum, wsum = sum + w * p[k], wsum + w end
  end
  return wsum > 0 and sum / wsum or 0, p
end

-- The builds a character is compared with: its own (an origin's, every one Loot Advisor scores), then every Build
-- Advisor build of the origins in L.ORIGINS order; a build id already in the list is not added again.
function L.Candidates(ownKey)
  local out, seen = {}, {}
  local function add(ck, b, own)
    if seen[b.id] then return end
    seen[b.id] = true
    out[#out + 1] = { b = b, ck = ck, own = own, info = ((LA.Mod.builds or {})[ck] or {})[b.id], order = #out + 1 }
  end
  local cd = ownKey and LA.Data.chars[ownKey]
  for _, b in ipairs(cd and cd.b or {}) do add(ownKey, b, true) end
  for _, ck in ipairs(L.ORIGINS) do
    local d = LA.Data.chars[ck]
    for _, b in ipairs(d and d.b or {}) do
      if b.o == "BuildAdvisor" then add(ck, b, false) end
    end
  end
  return out
end

-- The most similar candidate. Equal similarity: the character's own build, Build Advisor's pick, Build Advisor's
-- order, more of the build's levels in the character's classes, fewer classes, then the candidate order.
-- -> { b, ck, sim, parts, info } or nil
function L.ClosestBuild(ownKey, ctx, baPick, baOrder)
  local rank = {}
  for i, id in ipairs(baOrder or {}) do rank[id] = rank[id] or i end
  local function better(x, y)
    if math.abs(x.sim - y.sim) > 1e-6 then return x.sim > y.sim end
    if x.own ~= y.own then return x.own end
    local xp, yp = x.b.id == baPick, y.b.id == baPick
    if xp ~= yp then return xp end
    local xr, yr = rank[x.b.id] or 1e9, rank[y.b.id] or 1e9
    if xr ~= yr then return xr < yr end
    if math.abs(x.parts.prec - y.parts.prec) > 1e-6 then return x.parts.prec > y.parts.prec end
    if x.parts.nclass ~= y.parts.nclass then return x.parts.nclass < y.parts.nclass end
    return x.order < y.order
  end
  local best
  for _, c in ipairs(L.Candidates(ownKey)) do
    c.sim, c.parts = L.Similarity(c.b, c.info, ctx)
    if not best or better(c, best) then best = c end
  end
  return best
end

-- "closest build, 78% alike: same classes, other subclass, main ability DEX"
function L.ClosestWhy(c)
  local p, out = c.parts or {}, {}
  if p.class == nil then out[#out + 1] = "no class levels yet"
  elseif p.class >= 0.999 then out[#out + 1] = "same classes"
  elseif p.class <= 0 then out[#out + 1] = "no class in common"
  else out[#out + 1] = ("%d%% of the class levels"):format(math.floor(p.class * 100 + 0.5)) end
  if p.sub ~= nil then
    out[#out + 1] = p.sub >= 0.999 and "same subclass" or p.sub > 0 and "subclass partly" or "other subclass"
  end
  local main = c.info and c.info.main
  if p.main ~= nil and main then out[#out + 1] = (p.main > 0 and "main ability " or "main ability not ") .. main end
  return ("closest build, %d%% alike: %s"):format(L.Percent(c.sim), table.concat(out, ", "))
end

function L.Percent(sim) return math.floor((sim or 0) * 100 + 0.5) end

-- An origin keeps its own builds while at least half its class levels are in classes one of them has.
function L.OwnBuildFits(key, ctx)
  local cd = key and LA.Data.chars[key]
  if not cd then return false end
  if not ctx.classes or #ctx.classes == 0 then return true end
  local info = (LA.Mod.builds or {})[key] or {}
  for _, b in ipairs(cd.b) do
    local _, p = L.Similarity(b, info[b.id], { classes = ctx.classes })
    if (p.class or 0) >= 0.5 then return true end
  end
  return false
end

-- A character without builds of its own (Halsin, Jaheira, Minsc, Minthara, a Tav, a hireling): the closest Build
-- Advisor build. -> build, the origin whose sets it is, why, the closest-build record (similarity, parts)
function L.MatchAnyBuild(ctx, baPick, baOrder)
  local c = L.ClosestBuild(nil, ctx, baPick, baOrder)
  if not c then return nil end
  return c.b, c.ck, L.ClosestWhy(c), c
end

-- The build for one person: p = { key, ctx = {classes, abilities, atk}, ba = Build Advisor build order, baPick }.
-- Without class levels to read (a companion not met yet, not loaded), its first Build Advisor build stands in for
-- them. An origin matches among its own builds while one fits its classes (L.OwnBuildFits); everyone else, and an
-- origin respecced away from all of them, gets the closest build. -> build, origin it belongs to, why, closest-build
-- record (nil for an origin's own build)
function L.BuildFor(p)
  local ctx = p.ctx or {}
  local ba = p.ba or (LA.Mod.baOrigins or {})[p.key]
  if not ctx.classes or #ctx.classes == 0 then
    for _, id in ipairs(ba or {}) do
      local bb = (LA.Mod.baBuilds or {})[id]
      if bb then
        local cls = {}
        for c, n in pairs(bb.cl or {}) do cls[#cls + 1] = { name = c, level = n } end
        table.sort(cls, function(a, b) return a.name < b.name end)
        ctx = { classes = cls, main = bb.main, name = ctx.name }
        break
      end
    end
  end
  if L.OwnBuildFits(p.key, ctx) then
    local b, why = L.MatchBuild(p.key, ctx, p.baPick, ba)
    return b, p.key, why, nil
  end
  local c = L.ClosestBuild(LA.Data.chars[p.key or ""] and p.key or nil, ctx, p.baPick, ba)
  if not c then return nil end
  return c.b, c.ck, L.ClosestWhy(c), c
end

local function ownerAvailable(c, state)
  if c == "darkurge" then return state.durge end
  local cs = state.comp and state.comp[c]
  -- contested owners only among the ACTIVE party (a camp companion never takes an item away)
  return cs ~= nil and cs.team and cs.party == true and not cs.dead
end

-- everyone tied for an item: its owners plus the characters tied exactly with them (nil when nobody is tied)
local function tieMembers(it)
  if type(it.ot) ~= "table" or #it.ot == 0 then return nil end
  local out, seen = {}, {}
  for _, list in ipairs({ it.o or {}, it.ot }) do
    for _, c in ipairs(list) do if not seen[c] then seen[c] = true; out[#out + 1] = c end end
  end
  return out
end
local function has(list, x) for _, v in ipairs(list or {}) do if v == x then return true end end return false end

-- Genuine ties: two or more of an item's tie members are in the active party (other players' characters count).
-- Who gets it: the one wearing it (state.wear[stats id]), else the saved pick (state.tiePicks[stats id]) when that
-- character is among them, else nobody yet (the player is asked; a pick is kept across party swaps).
-- -> { [stats id] = { cands = {characters in the party}, pick = character or nil, by = "wear" | "pick" | nil } }
function L.Ties(state)
  local out = {}
  for _, it in ipairs(LA.Data and LA.Data.items or {}) do
    local mem = tieMembers(it)
    if mem then
      local present = {}
      for _, c in ipairs(mem) do if ownerAvailable(c, state) then present[#present + 1] = c end end
      if #present >= 2 then
        local t = { cands = present }
        local w = state.wear and state.wear[it.id]
        local pk = state.tiePicks and state.tiePicks[it.id]
        if w and has(present, w) then t.pick, t.by = w, "wear"
        elseif pk and has(present, pk) then t.pick, t.by = pk, "pick" end
        out[it.id] = t
      end
    end
  end
  return out
end

-- Who gets map markers: everyone in the active party (other players' characters too), the camp, and every companion
-- who may still join - not dead, not gone for good (state.comp[c].dead / .gone).
-- people = { {uuid, key = origin / companion key or nil, name, inParty, ctx}, ... } read from the game.
-- -> { {uuid, key, name, party, camp, future, ctx, ba = Build Advisor build order}, ... }
function L.Roster(people, state)
  local out, seen = {}, {}
  local function lost(key)
    local cs = key and state.comp and state.comp[key]
    return cs ~= nil and (cs.dead == true or cs.gone == true)
  end
  for _, p in ipairs(people or {}) do
    if p.inParty == true or not lost(p.key) then
      out[#out + 1] = { uuid = p.uuid, key = p.key, name = p.name, party = p.inParty == true,
                        camp = p.inParty ~= true, ctx = p.ctx, ba = (LA.Mod.baOrigins or {})[p.key or ""] }
    end
    if p.key then seen[p.key] = true end
  end
  local keys = {}
  for k in pairs(LA.Mod.companions or {}) do keys[#keys + 1] = k end
  table.sort(keys)
  for _, k in ipairs(keys) do
    local c = LA.Mod.companions[k]
    local cs = state.comp and state.comp[k] or {}
    if not seen[k] and k ~= "darkurge" and not lost(k) then
      out[#out + 1] = { uuid = c.npc ~= "" and (LA.Mod.npcs or {})[c.npc] or nil, key = k, name = LA.CharName(k),
                        party = false, camp = cs.team == true, future = cs.team ~= true,
                        ba = (LA.Mod.baOrigins or {})[k] }
    end
  end
  return out
end

-- Markers for everyone: one marker per marker id, labelled with everyone it is for.
-- people: one entry per character with key, name, party (bool), selected (bool) and res (its Recommend result);
-- filter "party" keeps the active party (and the selected character), "selected" only the selected character.
-- Each merged marker: who = names, entries = { {n = item name, who = {names}} } for the label, sel = true with the
-- selected character's rank / slot when it is one of theirs (the off-screen arrows follow only those).
function L.MergeMarkers(people, filter)
  local out, byId = {}, {}
  local function add(list, x) if not has(list, x) then list[#list + 1] = x end end
  for _, p in ipairs(people or {}) do
    local keep = p.selected or filter == nil or filter == "all" or (filter == "party" and p.party)
    if keep and p.res then
      for _, m in ipairs(p.res.markers or {}) do
        local e = byId[m.m]
        if not e then
          e = {}
          for k, v in pairs(m) do e[k] = v end
          e.who, e.entries, e.sel, e.items = {}, {}, nil, nil
          byId[m.m] = e
          out[#out + 1] = e
        end
        add(e.who, p.name)
        local names = m.entrance and (m.items or {}) or { (LA.Item(m.i) or {}).n or m.m }
        for _, n in ipairs(names) do
          local en
          for _, x in ipairs(e.entries) do if x.n == n then en = x end end
          if not en then en = { n = n, who = {} }; e.entries[#e.entries + 1] = en end
          add(en.who, p.name)
        end
        if p.selected and (not e.sel or (m.rank or 9) < (e.rank or 9)) then
          e.sel, e.rank, e.slot, e.i = true, m.rank, m.slot, m.i
        end
      end
    end
  end
  return out
end

-- state = { act, region, durge, paths={x="yes"/"no"}, comp={c={team,party,dead}}, owned={[stats id]=n},
--           markerPos={[markerId]={x,y,z,live}}, tiePicks={[stats id]=char}, wear={[stats id]=char} }
-- opts.build: the build to use (L.BuildFor), opts.why: why that build, opts.closest: L.ClosestBuild's record when it
-- is the closest build rather than one of the character's own (res.build.sim = similarity in %, .from = whose sets)
function L.Recommend(charKey, ctx, state, baPick, baOrder, opts)
  local res = { char = charKey, name = ctx.name, act = state.act, region = state.region, rows = {}, markers = {},
                frames = {}, texts = {} }
  local cd = LA.Data and LA.Data.chars and LA.Data.chars[charKey]
  if not cd and not (opts and opts.build) then res.notCovered = true; return res end
  local b, why
  if opts and opts.build then b, why = opts.build, opts.why or "closest build"
  else b, why = L.MatchBuild(charKey, ctx, baPick, baOrder) end
  if not b then res.notCovered = true; return res end
  local ties = state.ties or L.Ties(state)
  res.build = { id = b.id, n = b.n, why = why }
  local cl = opts and opts.closest
  if cl then res.build.closest, res.build.sim, res.build.from = true, L.Percent(cl.sim), cl.ck end
  local act = state.act or 1
  local a = b.a and b.a[act]
  if not a then return res end

  local rowsByItem = {}
  local function status(idx)
    if not idx or idx == 0 then return nil end
    local it = LA.Item(idx)
    if not it then return nil end
    local mode = LA.ItemAct(it, act)
    local owned = (state.owned[it.id] or 0) > 0
    local cond, reason, notes = L.EvalCond(it.c, state, charKey, act)
    if cond == "excluded" and not owned then return nil end
    local st = { mode = mode, owned = owned, reason = reason, notes = notes }
    -- (shared is filled in below, after the owner check)
    local better, shared, picked
    local o = it.o
    local mem = tieMembers(it)
    if mem then
      local t = ties[it.id]
      if t and t.pick then
        -- a settled tie: the wearer or the player's pick has it, everyone else moves on to their next best
        if t.pick ~= charKey then better, picked = t.pick, t.by end
      elseif t then
        -- an open tie: the party members tied for it share the pick until the player decides
        if has(t.cands, charKey) then
          local others = {}
          for _, c in ipairs(t.cands) do if c ~= charKey then others[#others + 1] = c end end
          shared = others
        else
          better = t.cands[1]
        end
      else
        -- fewer than two of them in the party: the one who is there gets it
        for _, c in ipairs(mem) do
          if ownerAvailable(c, state) then
            if c ~= charKey then better = c end
            break
          end
        end
      end
    elseif type(o) == "table" and #o > 0 and not has(o, charKey) then
      for _, c in ipairs(o) do if ownerAvailable(c, state) then better = c; break end end
    end
    -- a settled tie goes to the wearer / pick even when the party owns the item (seen in game: boots the Dark Urge
    -- wears and keeps stayed "owned" and best in Astarion's list)
    if better and picked then st.s = "better"; st.better = better; st.picked = picked
    elseif owned then st.s = "owned"
    elseif cond == "closed" then st.s = "closed"
    elseif mode == "-" or (tonumber(it.la) and tonumber(it.la) < act) then st.s = "onlyowned"
    elseif better then st.s = "better"; st.better = better; st.picked = picked
    elseif mode == "l" then st.s = "list"
    else
      st.s = "marker" -- 'm' / 't'; downgraded to "elsewhere" below when no marker exists in this region
    end
    st.shared = shared
    return st
  end

  local function addRow(idx, slot, rank, setName)
    if not idx or idx == 0 then return nil end -- fb = 0: leave the slot empty
    local key = idx .. "|" .. slot
    local row = rowsByItem[key]
    if not row then
      local st = status(idx)
      if not st then return nil end
      local it = LA.Item(idx)
      row = { i = idx, id = it.id, n = it.n, r = it.r, slot = slot, rank = rank, s = st.s, mode = st.mode,
              reason = st.reason, better = st.better, picked = st.picked, shared = st.shared, notes = st.notes,
              sets = {},
              why = b.why and b.why[idx] or "", w = it.w or "", tw = it.tw or "", g = it.g or "",
              odds = it.od and it.od[act] or nil, t = it.t or {} }
      rowsByItem[key] = row
      res.rows[#res.rows + 1] = row
    elseif rank > 0 and (row.rank == 0 or rank < row.rank) then
      row.rank = rank
    end
    if setName then row.sets[#row.sets + 1] = setName end
    return row
  end

  local usable = { owned = true, marker = true, list = true }
  for _, slot in ipairs(LA.SLOTS) do
    local pair = a.best and a.best[slot]
    if type(pair) == "table" then
      local cands = { pair[1], pair[2] }
      local pb = a.pb and a.pb[slot]
      if pb then cands[#cands + 1] = pb end
      local rank = 1
      for ci, idx in ipairs(cands) do
        local st = status(idx)
        if st then
          if usable[st.s] and rank <= 2 then
            addRow(idx, slot, rank, nil)
            rank = rank + 1
          elseif ci <= 2 then
            addRow(idx, slot, 0, nil) -- shown greyed: closed / better on X / only if owned
          end
        end
      end
    end
  end

  -- same rules as the Sets page: ca = Dark-Urge-only item that beats the pick in a Dark Urge campaign,
  -- oa = earlier-act item that is better if the party owns it, sv = the note's severity (list window)
  local SEV = { ["story lock"] = "Story lock", ["theft-kill"] = "Theft / kill", missable = "Missable",
                ["party conflict"] = "Party conflict", tip = "Tip" }
  for _, set in ipairs(a.sets or {}) do
    local ow = LA.AsSet(set.ow)
    for slot, idx in pairs(set.it or {}) do
      local use, note = idx, nil
      local st = status(idx)
      local ca = type(set.ca) == "table" and set.ca[slot] or nil
      local oa = type(set.oa) == "table" and set.oa[slot] or nil
      local cst = ca and state.durge and status(ca) or nil
      local ost = oa and status(oa) or nil
      if cst and cst.s ~= "closed" then
        use, note = ca, "Dark Urge campaign: beats the set's pick here"
      elseif ost and ost.owned then
        use, note = oa, "you have it: better than the set's pick here"
      elseif ow[slot] then
        if not (st and st.owned) then use = set.fb and set.fb[slot] or nil end
      elseif st and st.s == "better" and set.pa and set.pa[slot] then
        use = set.pa[slot]
      elseif (not st or st.s == "closed" or st.s == "onlyowned") and set.fb and set.fb[slot] then
        use = set.fb[slot]
      end
      if use then
        local row = addRow(use, slot, 3, set.n)
        if row then
          if note then row.alt = note end
          local sv = use == idx and type(set.sv) == "table" and set.sv[slot] or nil
          if sv and SEV[sv] then row.sev = SEV[sv] end
        end
      end
    end
  end

  -- markers, frames, tooltip texts
  local region = state.region
  for _, row in ipairs(res.rows) do
    local it = LA.Item(row.i)
    local ms = (LA.Mod.markers or {})[row.id] or {}
    if row.s == "marker" then
      local here = {}
      for _, m in ipairs(ms) do if m.r == region and m.a == act then here[#here + 1] = m end end
      if #here == 0 then
        -- a marker exists in another region of this act -> "other area"; none at all (reward, random, NPC
        -- without a placed holder) -> "no fixed spot" (the how-to text explains)
        row.s = "nospot"
        for _, m in ipairs(ms) do
          if m.a == act then
            row.s = "elsewhere"; row.where = m.rg
            row.away = { r = m.r, rg = m.rg, x = m.x, z = m.z } -- way out of this region toward it
            break
          end
        end
      elseif row.rank == 1 or row.rank == 2 then
        for _, m in ipairs(here) do
          local p = state.markerPos and state.markerPos[m.m]
          res.markers[#res.markers + 1] = { m = m.m, h = m.h, i = row.i, slot = row.slot, rank = row.rank,
            x = p and p.x or m.x, y = p and p.y or m.y, z = p and p.z or m.z, k = m.k, w = m.w, rg = m.rg,
            zn = m.zn }
        end
        row.where = here[1].rg
        row.x, row.z = here[1].x, here[1].z
        local p = state.markerPos and state.markerPos[here[1].m]
        if p then row.x, row.z = p.x, p.z end
      else
        row.s = "setonly" -- set member only: frame + list with its place; markers only for best/runner-up
        row.where = here[1].rg
        row.x, row.z = here[1].x, here[1].z
      end
    end
    local framed = { owned = true, marker = true, elsewhere = true, setonly = true, nospot = true }
    if row.s == "owned" or (framed[row.s] and row.mode ~= "l") then res.frames[it.id] = true end
  end
  return res
end
