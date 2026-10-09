# items_all - shared schema (every extraction script follows this)

Inputs (already built, read-only game access):
- `tools/pak.py` (pak reader), `tools/lsf.py`, `tools/loca.py`, `tools/stats.py` (stats with `using` inheritance,
  load order Shared, SharedDev, Gustav, GustavDev, GustavX; Honour/HonourX = Honour mode only, ignored except a flag).
- `data/cache/stats_resolved.json` - every stats entry resolved ({name: fields}, `_type`, `_chain`).
- `data/cache/roottemplates_*.json` - item root templates (MapKey, Name, Stats, DisplayName{handle,text},
  Description, Icon, inherited{...}).
- `data/cache/level_items_index.json` - every level item placement (level, MapKey, TemplateName, position, ...).
- `data/cache/loca_english.json` - handle -> English text. Stats DisplayName/Description values look like
  "h<handle>;<version>" - strip ";N" and look up.
- `tools/PARSERS.md` - parser docs and cache schemas.

## Item records - `data/items_all/<group>.jsonl` (one JSON object per line), group = weapons | armour | accessories
Key = stats entry name. Include every stats entry of the group that a real item uses (has a RootTemplate or is
referenced by an item root template), skip pure abstract bases (names starting "_") but keep their fields inherited.
```
{
 "stats_id": "Quest_SCL_Moonblade",            // stats entry name
 "group": "weapons",
 "stats_type": "Weapon",                          // Weapon | Armor | Object
 "name": "...", "description": "...",             // English, from the root template DisplayName/Description
                                                  //  (fall back to the stats entry's own DisplayName/Description)
 "templates": ["<MapKey>", ...],                  // all item root templates using this stats id
 "icon": "<icon name>",                           // root template Icon (or inherited)
 "rarity": "Common|Uncommon|Rare|VeryRare|Legendary|Story", "unique": true,
 "slot": "Melee Main Weapon|Melee Offhand Weapon|Ranged Main Weapon|Helmet|Breast|Cloak|Gloves|Boots|Amulet|Ring|Underwear|VanityBody|VanityBoots|...",
 "weight": 1.35, "value": ...,                    // value if derivable (ValueLevel/ValueScale) else null
 "weapon": {"damage": "1d8", "versatile": "1d10", "damage_type": "Slashing", "range": 1.5,
            "properties": [...], "proficiency": [...], "group": "MartialMeleeWeapon"} | null,
 "armour": {"ac": 14, "armor_type": "HalfPlate", "dex_cap": 2, "shield": false, "stealth_disadvantage": true,
            "proficiency": [...]} | null,
 "boosts_raw": {"Boosts": "...", "DefaultBoosts": "...", "BoostsOnEquipMainHand": "...", "BoostsOnEquipOffHand": "...",
                "PassivesOnEquip": "...", "PassivesMainHand": "...", "PassivesOffHand": "...", "StatusOnEquip": "..."},
 "effects": [  // every boost/passive/spell/status, parsed and resolved to readable text
   {"kind": "passive|spell|status|boost", "id": "...", "name": "...", "text": "...short readable effect...",
    "raw": "..."}  ],
 "grants_spells": ["Target_..."], "requirements": {"str": 0, "...": 0, "proficiency": [...]},
 "tags": [...],
 "honour_override": true|false,                   // a Honour-mode version exists
 "notes": "anything odd"
}
```

## Source records - `data/items_all/sources.jsonl` (recipes + locations)
One line per (item, source):
```
{"stats_id": "...", "template": "<MapKey>", "kind": "world|container|npc_equipped|npc_inventory|trader|treasure|reward|combo|forge|other",
 "level": "WLD_Main_A", "act": 1, "region": "...", "position": [x,y,z],
 "holder": {"name": "...", "MapKey": "...", "template": "...", "faction": "...", "neutral": true} | null,
 "container": {"name": "...", "MapKey": "...", "locked": true, "owner": "..."} | null,
 "treasure_table": "...", "chance": 1.0,
 "steal": true|false,                              // owned by an NPC / OwnerID set
 "requires": "short text: key, quest, story flag, kill, ...", "notes": "..."}
```
Plus `data/items_all/recipes.jsonl` (ItemCombos and multi-step assembly: inputs, result, station, where each input is).
Plus `data/items_all/levels.json`: level name -> {act, region (human name), notes}.
