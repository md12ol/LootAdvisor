"""Match every item name mentioned in data/research/*.md to game stats ids.

Order: exact trimmed name -> normalised name (case, accents, apostrophes, leading "The", armor/armour,
rarity suffix such as "(Very Rare)") -> alt display names -> fuzzy (difflib, >= 0.86; >= 0.92 accepted
automatically, all fuzzy hits listed for manual review). Known non-items (research says they do not exist)
are listed separately and never matched.

Candidates: bold names that start a research bullet, every segment of best/runner-up table cells, item table
rows, synergy-set loadouts, and the BuildAdvisor gear lines in Builds.lua.

Output: data/scores/name_matches.json   (run: python tools/match_research.py)
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_profiles as BP  # noqa: E402
from la_common import (KNOWN_NON_ITEMS, RESEARCH_DIR, NameIndex, SCORES_DIR, build_display_names, deaccent,  # noqa: E402
                       load_builds_lua, load_items, load_sources, split_rarity)
from la_research import ResearchParser, segments  # noqa: E402

ITEM_WORD = re.compile(
    r"\b(Armour|Armor|Ring|Amulet|Gloves|Gauntlets?|Boots|Helm|Helmet|Hat|Circlet|Cloak|Mantle|Robe|Shield|Bow|"
    r"Longbow|Shortbow|Crossbow|Staff|Sword|Greatsword|Longsword|Shortsword|Dagger|Mace|Axe|Greataxe|Battleaxe|"
    r"Halberd|Glaive|Spear|Pike|Hammer|Warhammer|Maul|Rapier|Scimitar|Trident|Club|Flail|Elixir|Potion|Garb|Cloth|"
    r"Mail|Plate|Half-Plate|Cowl|Hood|Mask|Horns|Crown|Diadem|Pendant|Necklace|Band|Bracers|Shoes|Vest|Wraps|"
    r"Periapt|Fetish|Talisman|Lute|Javelin|Sickle|Oil|Arbalest|Knife|Blade|Whip|Splintmail|Scalemail|Cuirass|Spark"
    r"swall|Sparkler|Hands|Gift|Cap|Coat|Embrace|Fortress|Heart|Revenge|Sweetheart)\b")

CRAFTED_CFG = {"research": "crafted.md", "tags": {}, "default_tags": "*"}
AUTO_FUZZY = 0.92


def collect_candidates():
    """-> {candidate: {"kinds": set, "files": set, "lines": [...]}}"""
    cands = collections.defaultdict(lambda: {"kinds": set(), "files": set(), "lines": []})
    cfgs = [(cid, cfg) for cid, cfg in BP.CHARACTERS.items()] + [("crafted", CRAFTED_CFG)]
    for cid, cfg in cfgs:
        p = ResearchParser(cid, cfg, cfg.get("builds", []), scanner=None).parse()
        for text, kind, line in p.candidates:
            t = deaccent(text).strip().strip(".,;:")
            if not t:
                continue
            c = cands[t]
            c["kinds"].add(kind)
            c["files"].add(cfg["research"])
            if len(c["lines"]) < 5:
                c["lines"].append(f'{cfg["research"]}:{line}')
    gear, _origins = load_builds_lua(BP.BUILDS_LUA)
    for bid, g in gear.items():
        for s in segments(g):
            c = cands[deaccent(s).strip()]
            c["kinds"].add("gear")
            c["files"].add("Builds.lua")
    return cands


def looks_like_item(name, kinds):
    """General rule for what is worth reporting as an unmatched item name: a bullet / table row that states a
    rarity, or a Title-Case phrase of 2-6 words containing an item-type word (Ring, Gloves, Bow ...)."""
    words = name.split()
    if name.isupper() or name.startswith("[") or " - " in name or "/" in name or len(words) > 6:
        return False
    if {"bullet-item", "table-item"} & set(kinds):
        return True
    caps = sum(1 for w in words if w[:1].isupper() or w in ("of", "the", "and"))
    return bool(ITEM_WORD.search(name)) and len(words) >= 2 and caps == len(words)


def main():
    items = load_items()
    sources = load_sources()
    idx = NameIndex(items, sources, build_display_names(items))
    cands = collect_candidates()
    matches, fuzzy_review, unmatched, non_items, generic_overrides = {}, [], [], {}, {}
    # where do the known non-items appear in the research? (they are usually quoted in prose)
    scan = [(fn, os.path.join(RESEARCH_DIR, fn)) for fn in sorted(os.listdir(RESEARCH_DIR))]
    scan.append(("Builds.lua", BP.BUILDS_LUA))
    for fn, path in scan:
        with open(path, encoding="utf-8") as f:
            for ln, line in enumerate(deaccent(f.read()).splitlines(), 1):
                for bad, alias in KNOWN_NON_ITEMS.items():
                    if bad in line:
                        e = non_items.setdefault(bad, {"files": [], "lines": [], "note": alias})
                        if fn not in e["files"]:
                            e["files"].append(fn)
                        if len(e["lines"]) < 6:
                            e["lines"].append(f"{fn}:{ln}")
    for name, info in sorted(cands.items()):
        base, _r = split_rarity(name)
        if name in KNOWN_NON_ITEMS or base in KNOWN_NON_ITEMS:
            continue
        res = idx.match(name)
        if not res and looks_like_item(name, info["kinds"]):
            res = idx.fuzzy(name)
            if res:
                fuzzy_review.append({"research_name": name, "game_name": res["game_name"], "stats_id": res["chosen"],
                                     "ratio": res["ratio"], "accepted": res["ratio"] >= AUTO_FUZZY,
                                     "files": sorted(info["files"]), "lines": info["lines"]})
                if res["ratio"] < AUTO_FUZZY:
                    res = None
        if res and items[res["chosen"]]["rarity"] == "Common" and res["game_name"] != items[res["chosen"]]["name"]:
            # a display-name override on a generic stats entry (story / quest prop such as Moonlantern,
            # Crown of Karsus): not an equippable item of its own - list it, never score it
            generic_overrides[name] = {"stats_id": res["chosen"], "record_name": items[res["chosen"]]["name"],
                                       "files": sorted(info["files"])}
            continue
        if res:
            matches[name] = {"method": res["method"], "stats_ids": res["ids"], "chosen": res["chosen"],
                             "game_name": res["game_name"], "templates": res["templates"], "ratio": res["ratio"],
                             "rarity": items[res["chosen"]]["rarity"], "slot": items[res["chosen"]]["slot"],
                             "kinds": sorted(info["kinds"]), "files": sorted(info["files"])}
        elif looks_like_item(name, info["kinds"]):
            unmatched.append({"name": name, "kinds": sorted(info["kinds"]), "files": sorted(info["files"]),
                              "lines": info["lines"]})
    # aliases used to scan research text: research spellings + the chosen items' game names
    aliases = {}
    for name, m in matches.items():
        base, _r = split_rarity(name)
        aliases[name] = m["chosen"]
        aliases.setdefault(base, m["chosen"])
    for name, m in list(matches.items()):
        aliases.setdefault(deaccent(m["game_name"]), m["chosen"])
    # drop aliases that are too generic to scan prose safely (single common words)
    generic = {"Shield", "Dagger", "Longbow", "Shortbow", "Club", "Mace", "Greatsword", "Longsword", "Spear", "Pike",
               "Glaive", "Halberd", "Rapier", "Scimitar", "Trident", "Hand Crossbow", "Heavy Crossbow",
               "Light Crossbow", "Quarterstaff", "Warhammer", "Greataxe", "Battleaxe", "Maul", "Sickle", "Javelin",
               "Flail", "Handaxe", "Morningstar", "Shortsword", "Studded Leather Armour", "Leather Armour",
               "Half Plate Armour", "Plate Armour", "Chain Mail", "Scale Mail", "Splint Armour", "Hide Armour",
               "Padded Armour", "Breastplate", "Ring Mail", "Chain Shirt", "Boots", "Gloves", "Cloak", "Hat",
               "Helmet", "Ring", "Amulet", "Robe"}
    aliases = {a: s for a, s in aliases.items()
               if a not in generic and len(a) >= 4
               and not (items[s]["rarity"] == "Common" and len(a.split()) == 1)}
    out = {
        "about": "Research item names -> game stats ids. Generated by tools/match_research.py; see the docstring "
                 "for the matching order. 'chosen' = canonical id (has a gameplay source, highest rarity, earliest act).",
        "counts": {"candidates": len(cands), "matched": len(matches),
                   "by_method": dict(collections.Counter(m["method"] for m in matches.values())),
                   "fuzzy_review": len(fuzzy_review), "unmatched": len(unmatched), "known_non_items": len(non_items),
                   "display_name_on_generic_item": len(generic_overrides),
                   "distinct_items": len({m["chosen"] for m in matches.values()})},
        "matches": matches,
        "aliases": dict(sorted(aliases.items())),
        "fuzzy_review": fuzzy_review,
        "known_non_items": non_items,
        "display_name_on_generic_item": generic_overrides,
        "unmatched": unmatched,
    }
    os.makedirs(SCORES_DIR, exist_ok=True)
    path = os.path.join(SCORES_DIR, "name_matches.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(json.dumps(out["counts"], indent=1))
    print("\nFUZZY (review):")
    for fz in fuzzy_review:
        print(f'  {fz["ratio"]:.3f} {"OK " if fz["accepted"] else "-- "}{fz["research_name"]!r} -> {fz["game_name"]!r} ({fz["stats_id"]})')
    print("\nUNMATCHED:")
    for u in unmatched:
        print(f'  {u["name"]!r}  {",".join(u["kinds"])}  {u["lines"][:2]}')
    print("\nKNOWN NON-ITEMS:", ", ".join(sorted(non_items)))
    print("->", path)


if __name__ == "__main__":
    main()
