-- LootAdvisor: what other mods may read, as plain tables (Mods.LootAdvisor.LA.Api). Build Advisor shows a build's
-- gear sets from it, so the item data ships in Loot Advisor only. Fields are only ever added; version counts changes
-- that remove or reshape one.

LA = LA or {}
LA.Api = { version = 1 }
local A = LA.Api

-- stats ids the party has (you, the camp chest), as far as the last result sent to this client tells; nil = unknown
local function ownedIds()
  local out = {}
  for _, r in ipairs((LA.Result or {}).rows or {}) do
    if r.s == "owned" and r.id then out[r.id] = true end
  end
  return out
end

-- The ranked gear sets of a build, act by act:
--   { char = whose sets (origin key), build = build name, sets = { [rank] = { [act] = { name, why,
--     items = { { slot, slotName, name, id, onlyOwned = true when it counts only if you already have it,
--                 owned = true when the party has it } } } } } }
-- charKey: the character's origin key (nil or unknown: the first origin that has the build). nil when Loot Advisor
-- has no sets for that build.
function A.GearSets(charKey, buildId, maxSets)
  local chars = (LA.Data or {}).chars or {}
  local function find(ck)
    for _, b in ipairs((chars[ck] or {}).b or {}) do if b.id == buildId then return b end end
  end
  local ck, b = charKey, charKey and find(charKey)
  if not b then
    for _, o in ipairs((LA.Logic or {}).ORIGINS or {}) do
      b = find(o)
      if b then ck = o; break end
    end
  end
  if not b then return nil end
  local owned = ownedIds()
  local out = { char = ck, build = b.n, sets = {} }
  for act = 1, 3 do
    local a = b.a and b.a[act]
    for rank, set in ipairs(a and a.sets or {}) do
      if rank > (maxSets or 3) then break end
      local ow = LA.AsSet(set.ow)
      local items = {}
      for _, slot in ipairs(LA.SLOTS) do
        local it = LA.Item((set.it or {})[slot])
        if it then
          items[#items + 1] = { slot = slot, slotName = LA.SLOT_NAME[slot] or slot, name = it.n, id = it.id,
                                onlyOwned = ow[slot] or nil, owned = owned[it.id] or nil }
        end
      end
      if #items > 0 then
        out.sets[rank] = out.sets[rank] or {}
        out.sets[rank][act] = { name = set.n, why = set.why, items = items }
      end
    end
  end
  if next(out.sets) == nil then return nil end
  return out
end
