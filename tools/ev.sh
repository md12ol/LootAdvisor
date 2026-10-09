#!/bin/sh
# ev.sh client|server <lua file or ->: run Lua in the game through the LootAdvisor mod's dev eval hook
# ("Dev": true in LootAdvisor_settings.json), print the output. EV_PREFIX=LootAdvisorSpike targets the old spike mod.
D="$LOCALAPPDATA/Larian Studios/Baldur's Gate 3/Script Extender"
S="${EV_PREFIX:-LootAdvisor}_$1"
rm -f "$D/${S}_eval_out.txt"
if [ "$2" = "-" ] || [ -z "$2" ]; then cat > "$D/${S}_eval.lua"; else cp "$2" "$D/${S}_eval.lua"; fi
for i in $(seq 1 40); do [ -f "$D/${S}_eval_out.txt" ] && { cat "$D/${S}_eval_out.txt"; echo; exit 0; }; sleep 0.25; done
echo "(no output after 10 s)"; exit 1
