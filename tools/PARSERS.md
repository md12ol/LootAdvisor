# BG3 game-file parsers (read-only)

Pure Python 3.12 + `lz4` + `zstandard`. Nothing here writes into the game folder
(`D:\SteamLibrary\steamapps\common\Baldurs Gate 3\Data`, `pak.GAME_DATA`). Format reference: Norbyte's LSLib.

| tool | what it does | call |
|---|---|---|
| `pak.py` | LSPK v18 archive reader (list / extract / cat) | `python pak.py list Gustav.pak RootTemplates` |
| `lsf.py` | LSF binary resource ("LSOF", v1-v7) -> node tree / JSON | `python lsf.py Shared.pak Public/Shared/RootTemplates/_merged.lsf --json out.json` |
| `loca.py` | .loca localization ("LOCA") -> `{handle: text}` | `python loca.py --lookup h13f8876fgf255g4707g860eg0edb44661e54` / `python loca.py --json out.json` |
| `validate_parsers.py` | parses all root templates, 50 random level item files, 200 random Gustav .lsf, english.loca; cross-checks Stats and DisplayName | `python validate_parsers.py [--seed N]` |
| `build_cache.py` | writes the cache dumps below (~14 s) | `python build_cache.py [--out DIR] [--only loca,templates,levels]` |

Bare pak names (`Shared.pak`, `Localization/English.pak`) are resolved against `GAME_DATA`.

## Library use

```python
from pak import Pak, GAME_DATA
import lsf, loca, os
p = Pak(os.path.join(GAME_DATA, "Gustav.pak"))
res = lsf.load(p.read(p.by_name["Public/Gustav/RootTemplates/_merged.lsf"]))
for go in res.regions[0].children:          # region "Templates" -> GameObjects nodes
    go.get("MapKey"), go.get("Stats"), go.get("DisplayName")   # {"handle", "version"}
    go.child("Transform"), go.attrs          # attrs: {name: (type_name, value)}
texts = loca.load_english()                  # {handle: text}
lsf.to_json(res)                             # plain dict (typed); to_json(res, typed=False) drops type names
```

Attribute value mapping: ints/floats/bool -> scalars; IVec*/Vec* -> list; Mat* -> list of rows;
all string types -> str; UUID -> str in LSLib's byte-swapped form (matches the GUIDs in .txt/.lsx text files;
verified: 7720 LSF UUIDs from Shared.pak match text GUIDs with the swap, 0 without);
TranslatedString -> `{"handle", "version"}`; TranslatedFSString -> same + `"arguments"`; ScratchBuffer -> hex string.
`node.key` holds the v6+ key-attribute name if the file has a keys section.

## Cache files (`LootAdvisor/data/cache/`)

All "JSON array, one object per line" files are valid JSON *and* grep-able line by line. Empty strings,
null GUIDs and unset translated strings are omitted; floats rounded to 4 decimals.

### `loca_english.json` (~25 MB)
`{handle: text}` for all 232,878 handles of `Localization/English/english.loca`. Text keeps the game's markup
(`<br>`, `<i>`, `<LSTag ...>`, `[1]` parameters).

### `roottemplates_<pak>_<module>.json` (one per `Public/<module>/RootTemplates/_merged.lsf`)
Only GameObjects with `Type == "item"`. Each object = every attribute of the template except a skip list of
sound/physics/render/walkability fields (`SKIP_ATTRS` in build_cache.py), e.g.:
- `MapKey` (template GUID), `Name`, `Type`, `ParentTemplateId`, `Stats` (stats entry name), `Icon`, `LevelName`
- translated strings as `{"handle", "text"}`: `DisplayName`, `Description`, `TechnicalDescription`,
  `ShortDescription`, `OnUseDescription`, `UnknownDisplayName`, `UnknownDescription`, `DisplayNameAlchemy` ...
- item-ish scalars when present: `TreasureOnDestroy`, `EquipmentTypeID`, `InventoryType`, `maxStackAmount`,
  `StoryItem`, `IsKey`, `Key`, `CanBePickedUp`, `CanBePickpocketed`, `BookType`, `Archetype`, `Race`, `Faction`,
  `HardcoreOnly`, `IsBlueprintDisabledByDefault`, `Destroyed`, ...
- lists: `Tags` (tag GUIDs), `InventoryList` (treasure table names), `StatusList`, `OnlyInDifficulty`,
  `ExcludeInDifficulty`, `Labels`, `ItemList` (`[{ItemName, TemplateID, Amount, Type, UUID, LevelName, ...}]`)
- `inherited`: fields the template does NOT set itself but gets from its `ParentTemplateId` chain
  (searched across all modules): `Stats`, `DisplayName`, `Description`, `Icon`, `TechnicalDescription`,
  `ShortDescription`, each with `<field>_from` = MapKey of the ancestor that set it.
Files: Shared_Shared (5337 items), Shared_SharedDev (1441), Gustav_GustavDev (1957), Gustav_Gustav (588),
Gustav_Honour (2), GustavX_GustavX (6). The Patch8 hotfix paks contain no root templates.

### `level_items_index.json` (~31 MB, 58,899 placements)
Every GameObject in `Mods/<module>/Levels/<level>/Items/*` LSF files of all five paks (388 `_merged.lsf` +
one stray extensionless LSF in `WLD_VillageSubs_C`). Per placement:
- `pak`, `module`, `level` (folder name), `file` (only for the non-merged file)
- the placement's own attributes (same skip list): `MapKey` (instance GUID), `TemplateName` (root template
  MapKey), `Name`, `Type`, `LevelName`, `Stats` (only if overridden), `DisplayName`/`Description` (if overridden),
  `Key`, `IsKey`, `StoryItem`, `owner`, `LockDifficultyClassID`, `TreasureOnDestroy`, `TreasureLevel`, ...
- lists: `InventoryList` (treasure tables of containers), `ItemList` (explicit contents), `Tags`, `StatusList`
- `position` `[x, y, z]`, `rotation` quaternion `[x, y, z, w]` (from the `Transform` child)
- `template`: summary of the root template (`Name`, `module`, and `Stats`, `DisplayName` text, `Icon` resolved
  through the parent chain), or `null` if the TemplateName is not a known root template (0 cases today).

## Known limits
- Containers' contents mostly come from treasure tables (`InventoryList` -> `Stats/Generated/TreasureTable.txt`),
  which are not expanded here. Character placements (`Levels/*/Characters`), trader inventories, ItemCombos and
  stats `.txt` files are not parsed by these tools (the .txt files are plain text).
- LSX (XML) and LSJ (JSON) resources are not handled by lsf.py (they are text; use an XML/JSON parser).
- Matrix element order follows LSLib (rows of `columns` floats); not cross-checked against game usage.
- Full-coverage test: all 80,466 .lsf files in Shared, GustavX, Gustav, Game and Engine paks (2.7 GB of LSF data,
  ~225 s) parse without error. Formats seen: LSF v2-v7; metadata format 0, 1 (KeysAndAdjacency -> extended
  nodes) and 2; sections stored raw (most files) or LZ4-frame compressed (flags 0x22, 595 files).
  zlib and zstd section compression and LZ4 *block* mode (only used for v1) are implemented per LSLib but no game
  file uses them, so they are untested. Attribute types never seen in game data (implemented, untested):
  None, Path, WString, Long, IVec4, Mat2, Mat3x4.
- TranslatedFSString argument order (key, nested string, value) follows LSLib; rare in item data.
- Hotfix paks (Patch8_HotFix9/10) only contain story goals, GUI .xaml and story.div.osi files - no LSF.
- `pak.py` notes: uncompressed entries store size 0 (fixed in `list` output); empty compressed entries now
  read as `b""` instead of failing.
- Cross-check results (validate_parsers.py): 4561 item templates set their own `Stats`; 4554 of them name an entry
  in `Public/*/Stats/Generated/Data/*.txt` (552 in Weapon.txt). 7 do not (`ARM_Belt`, `ARM_Gloves_Cloth_A_2`,
  `COL_IllithidManuscript`, `OBJ_Philter_Of_Love`, `OBJ_TransmuterStone`, `THR_TreeStump`, `UND_Bibberbang`) -
  game-data leftovers, not parser errors. All 7433 real item DisplayName handles resolve in english.loca; 122 more
  are the placeholder `ls::TranslatedStringRepository::s_HandleUnknown` (dropped in the cache).

## Item sources (where every item comes from)

| tool | what it does | call |
|---|---|---|
| `treasure.py` | TreasureTable.txt parser + recursive expansion with approximate drop chances (CanMerge, `-N` / `amount,weight` subtables, StartLevel/EndLevel) | `python treasure.py DEN_Weaponsmith_Trade` |
| `characters.py` | every NPC placement (Levels + Globals) resolved through the character root-template chain -> `data/cache/level_characters_index.json` | `python characters.py` |
| `global_items.py` | item placements in `Mods/*/Globals/*/Items` (not in level_items_index.json!) -> `data/cache/global_items_index.json` | `python global_items.py` |
| `extract_sources.py` | builds `data/items_all/sources.jsonl`, `recipes.jsonl`, `levels.json` (~30 s) | `python extract_sources.py [--out DIR]` |

Findings used by extract_sources.py:
- Container contents: placement `InventoryList`/`ItemList`, else inherited from the item root template chain
  (e.g. Mithral Vein -> Mithral Ore). ItemList `Type` 0 = stats name (`ItemName`), 1 = template (`TemplateID`),
  2 = existing placed instance (`UUID`, the instance is inside that container / NPC).
- Positions are world coordinates of the main level; bg3.wiki "X, Y" = game x, z.
- Quest rewards: `Mods/GustavDev/Story/Journal/quest_prototypes.lsx` QuestStep children `QuestRewardTables`,
  `QuestRewardOptionalTables` (choose one), `RewardTemplateDescription` (template GUIDs); tables named after a
  quest objective are rewards too (e.g. DEN_IdolTheft_ReturnForReward -> Ring of Protection).
- Trade tables switched by story: `PROC_SetCustomTradeTreasure(char, "table")` in Osiris goals.
- Item ownership areas: `DB_ItemOwnerShipTriggers(level, trigger, owner)` + trigger shapes in Levels/Globals Triggers.
- Adamantine Forge recipes: `DB_UND_AdamantineForge_Result(combo, result template, mould template, spawn)`.
- Gaps: ~115 Uncommon+ weapon/armour stats have no source in these files (cut content, or given by dialog/compiled
  story only, e.g. Dammon's infernal-iron weapons, Oathbreaker set); dialog item gifts are not parsed.
