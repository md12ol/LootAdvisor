-- LootAdvisor: which items to recommend for the selected character (pure logic; runs on the server, which has the
-- story state). Rules:
--  1 closed story paths -> no marker, greyed "path closed" in the list
--  2/16 unique items: owner list `o` (game-data fit); others see "better on X" and their next pick moves up;
--       an exact tie (`ot`) between party members is the player's pick (the wearer keeps it), see L.Ties
--  3 traders -> marker on the trader; 'l' items (random loot, generic +1/+2) list only with odds, no frame/text
--  4/5 markers = best + runner-up per slot of the CURRENT act, still obtainable now; owned items keep the frame only
--  6 build: live class levels -> closest build of the character; tie -> BuildAdvisor's pick; none -> main stat;
--       characters without builds of their own (companions, Tavs, hirelings): the closest build of any origin
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
        if cs.dead then close((LA.CHAR_NAME[arg] or arg) .. " is dead")
        elseif not cs.team and (act or 1) >= 2 then close("needs " .. (LA.CHAR_NAME[arg] or arg) .. " in your team") end
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

-- A character without builds of its own (Halsin, Jaheira, Minsc, Minthara, a Tav, a hireling): the closest build of
-- any origin by live class levels, else the first build whose main ability is the character's highest.
-- -> build, the origin it belongs to, why
function L.MatchAnyBuild(ctx)
  local best, bestScore, bestChar, any = nil, -1e9, nil, false
  for _, ck in ipairs(L.ORIGINS) do
    local cd = LA.Data.chars[ck]
    local info = (LA.Mod.builds or {})[ck] or {}
    for _, b in ipairs(cd and cd.b or {}) do
      local score, overlap = classScore(b, info[b.id], ctx)
      if overlap then
        any = true
        if score > bestScore + 1e-6 then best, bestScore, bestChar = b, score, ck end
      end
    end
  end
  if any then return best, bestChar, "closest to the class levels" end
  local hi = mainAbility(ctx)
  for _, ck in ipairs(L.ORIGINS) do
    local cd = LA.Data.chars[ck]
    for _, b in ipairs(cd and cd.b or {}) do
      if hi and ((LA.Mod.builds or {})[ck] or {})[b.id] and LA.Mod.builds[ck][b.id].main == hi then
        return b, ck, "no build matches the classes - picked by main ability " .. hi
      end
    end
  end
  local cd = LA.Data.chars[L.ORIGINS[1]]
  return cd and cd.b[1], L.ORIGINS[1], "no build matches the classes - first build"
end

-- The build for one person on the roster: p = { key, ctx = {classes, abilities}, ba = Build Advisor build order }.
-- Without class levels to read (a companion not met yet, not loaded), its first Build Advisor build stands in for
-- them. Origins match among their own builds, everyone else among all builds. -> build, origin it belongs to, why
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
  if LA.Data.chars[p.key] then
    local b, why = L.MatchBuild(p.key, ctx, p.baPick, ba)
    return b, p.key, why
  end
  return L.MatchAnyBuild(ctx)
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
      out[#out + 1] = { uuid = c.npc ~= "" and (LA.Mod.npcs or {})[c.npc] or nil, key = k, name = LA.CHAR_NAME[k] or k,
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
-- opts.build: the build to use (a character without builds of its own, L.BuildFor), opts.why: why that build
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
