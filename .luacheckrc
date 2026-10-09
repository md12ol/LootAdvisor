-- luacheck config for BG3 Script Extender mods (Lua 5.4). CI fails on syntax errors only; warnings are reported.
std = "lua54"
allow_defined_top = true          -- mods share their namespace table (LA, BA, ...) as a global across files
max_line_length = false
unused_args = false
read_globals = { "Ext", "Osi", "Mods", "_C", "_D", "_P", "Game" }
globals = { "LA", "LAS", "BA", "AP", "CAM" }
exclude_files = { "analysis/*_build.lua" }  -- Builds.lua fragments, not whole chunks
