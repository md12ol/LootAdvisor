-- (c) Per-selected-character "why it's best" text in the item tooltip.
-- Ext.Loca.UpdateTranslatedString(handle, text) (bg3se Lua/Libs/Localization.inl, module "Both") overwrites the
-- text of a HANDLE in the process-wide TranslatedStringRepository: runtime only (never written to the save),
-- shared by client and server in single player, and it affects EVERY template/UI that uses that handle.
-- Tooltip text for an item comes from the root template's Description (ItemTemplate.Description, a
-- TranslatedString) - the item tooltip XAML renders VMItem.Description via ls:TextBlockFormatter.SourceText
-- (Public/Game/GUI/Library/Tooltips.xaml). Markup the game's own texts use: <br>, <i>, <b>, <hl>, <LSTag ...>.
-- 2428 of 5390 item templates share a Description handle with another template (one handle is used by 744), so for
-- shared handles we point the template at a NEW handle of ours instead (template field write: UNVERIFIED).
-- Each UpdateTranslatedString allocates a new string that is never freed: update only on selection change.

LAS = LAS or {}
local try = LAS.try

local handleUse      -- handle -> number of root templates using it (built once)
local original = {}  -- handle -> original text
local redirected = {} -- template guid -> { tmpl, oldHandle, newHandle }

local function buildHandleUse()
  handleUse = {}
  for _, t in pairs(try(Ext.Template.GetAllRootTemplates) or {}) do
    local h = try(function() return t.Description.Handle.Handle end)
    if h and h ~= "" then handleUse[h] = (handleUse[h] or 0) + 1 end
  end
end

local function newHandle(templateGuid) -- deterministic, game-shaped handle: h<8>g<4>g<4>g<4>g<12> from the GUID
  local s = templateGuid:gsub("%-", "")
  return ("h%sg%sg%sg%sg%s"):format(s:sub(1, 8), s:sub(9, 12), s:sub(13, 16), s:sub(17, 20), s:sub(21, 32))
end

local function setText(handle, text)
  if original[handle] == nil then original[handle] = try(Ext.Loca.GetTranslatedString, handle) or "" end
  return try(Ext.Loca.UpdateTranslatedString, handle, text)
end

function LAS.RestoreTexts()
  for h, txt in pairs(original) do try(Ext.Loca.UpdateTranslatedString, h, txt) end
  original = {}
end

-- info = { template = guid, why = "...", name = "..." }, who = selected character display name
function LAS.SetWhyText(info, who)
  if not handleUse then buildHandleUse() end
  local tmpl = try(Ext.Template.GetRootTemplate, info.template)
  local h = tmpl and try(function() return tmpl.Description.Handle.Handle end)
  if not h then return "no template/description" end
  local base = original[h] or try(Ext.Loca.GetTranslatedString, h) or ""
  local add = ("<br><br>%s <hl>Best for %s:</hl> %s"):format(LAS.MARK, who or "?", info.why or "")
  if (handleUse[h] or 0) <= 1 or redirected[info.template] then
    setText(redirected[info.template] and redirected[info.template].newHandle or h, base .. add)
    return "updated own handle " .. h
  end
  -- shared handle: give this template its own handle (client-side template edit, not saved)
  local nh = newHandle(info.template)
  setText(nh, base .. add)
  local ok = pcall(function() tmpl.Description.Handle.Handle = nh end)
  if ok then redirected[info.template] = { tmpl = tmpl, oldHandle = h, newHandle = nh } end
  return ok and ("redirected " .. h .. " -> " .. nh) or "template Description is read-only (fallback: skip)"
end

-- Marker labels on the map: "◆ Sword of the Emperor - Karlach"
function LAS.SetMarkerTexts(who)
  for _, t in ipairs(LAS.TEST_ITEMS) do
    setText(t.markerHandle, ("%s %s - %s"):format(LAS.MARK, t.name, who or "?"))
  end
end
