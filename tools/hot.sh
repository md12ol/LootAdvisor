#!/bin/sh
# hot.sh client|server <mod-relative lua file>...: hot-reload LootAdvisor Lua files in the running game (dev eval hook).
# e.g. hot.sh server Server/State.lua Shared/ModData.lua
D="$LOCALAPPDATA/Larian Studios/Baldur's Gate 3/Script Extender"
M="$(cd "$(dirname "$0")/.." && pwd)/Mods/LootAdvisor/ScriptExtender/Lua"
side=$1; shift
mkdir -p "$D/LootAdvisor_dev"
code=""
for f in "$@"; do
  n=$(echo "$f" | tr '/' '_'); cp "$M/$f" "$D/LootAdvisor_dev/$n"
  code="$code local f,e = Ext.Utils.LoadString(Ext.IO.LoadFile('LootAdvisor_dev/$n'), (Mods and Mods.LootAdvisor) or _G); if f then f() print('reloaded $f') else print('ERR $f', e) end"
done
echo "$code" | "$(dirname "$0")/ev.sh" "$side" -
