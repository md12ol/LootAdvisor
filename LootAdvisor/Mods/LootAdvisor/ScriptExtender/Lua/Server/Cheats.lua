-- LootAdvisor dev/test helpers (only with "Dev": true in LootAdvisor_settings.json). TEST SAVES ONLY.
-- One line in LootAdvisor_cmd.txt; result in LootAdvisor_result.txt as "<seq>|<text>".
--   spawn <templateGuid> [count]   Osi.TemplateAddTo into the selected character
--   tp <x> <y> <z>                 Osi.TeleportToPosition (selected character + followers)
--   tpto <objectGuid>              Osi.TeleportTo
--   refresh                        recompute + resend now
LA = LA or {}
local try = LA.try
local seq = 0

local function actor() return (LA.LastResult and LA.LastResult.uuid) or try(Osi.GetHostCharacter) end

local function run(line)
  local w = {}
  for s in line:gmatch("%S+") do w[#w + 1] = s end
  local cmd, who = w[1], actor()
  if cmd == "spawn" and w[2] then
    local ok, err = pcall(Osi.TemplateAddTo, w[2], who, tonumber(w[3]) or 1, 1)
    return ok and ("spawned " .. w[2]) or ("spawn error " .. tostring(err))
  elseif cmd == "tp" and w[4] then
    local ok, err = pcall(Osi.TeleportToPosition, who, tonumber(w[2]), tonumber(w[3]), tonumber(w[4]), "", 0, 1, 1, 0, 1)
    return ok and "teleported" or ("tp error " .. tostring(err))
  elseif cmd == "tpto" and w[2] then
    local ok, err = pcall(Osi.TeleportTo, who, w[2], "", 0)
    return ok and ("teleported to " .. w[2]) or ("tpto error " .. tostring(err))
  elseif cmd == "refresh" then
    LA.ServerRefresh(true); return "refreshed"
  end
  return "unknown command: " .. line
end

function LA.RunCommandFile()
  local raw = try(Ext.IO.LoadFile, "LootAdvisor_cmd.txt")
  if type(raw) ~= "string" or raw:match("^%s*$") then return end
  try(Ext.IO.SaveFile, "LootAdvisor_cmd.txt", "")
  seq = seq + 1
  local ok, res = pcall(run, (raw:gsub("[\r\n]+", " ")))
  try(Ext.IO.SaveFile, "LootAdvisor_result.txt", seq .. "|" .. tostring(ok and res or ("error " .. tostring(res))))
end
