"""The gauntlet catalogue for the in-game window (manual runs): every Build Advisor build per act, every set, the
standard enemies and buffs per act. Written to the Script Extender folder as LootAdvisor_gauntlet_catalog.json.

    python tools/gauntlet/catalog.py --optimizer DIR [--optimized optimized.json] [--out FILE]

Builds come from Build Advisor's Builds.lua (grouped by tier like Build Advisor's own list). A build that an origin
character plays in the scored data takes that character's sheet (abilities, HP) at the act's level; a build nobody
plays gets an approximate point-buy sheet (marked "approximate"). Sets: every research / generated set and the
optimizer's sets, each with its items' root templates and item spells.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine  # noqa: E402
import plan as P  # noqa: E402

TEMPLATE = "b7f6f34b-07e6-4bcc-a4bc-023b25fb6e84"   # a plain humanoid (Absolute Cultist); stats are forced anyway
ENEMY_HP = 5000
BUFFS = {"1": ["BLESS"], "2": ["BLESS"], "3": ["BLESS"]}
HASTE = "HASTE"
PRIME = {"Barbarian": "STR", "Fighter": "STR", "Paladin": "STR", "Monk": "DEX", "Rogue": "DEX", "Ranger": "DEX",
         "Bard": "CHA", "Sorcerer": "CHA", "Warlock": "CHA", "Cleric": "WIS", "Druid": "WIS", "Wizard": "INT"}
HIT_DIE = {"Barbarian": 12, "Fighter": 10, "Paladin": 10, "Ranger": 10, "Monk": 8, "Rogue": 8, "Bard": 8, "Cleric": 8,
           "Druid": 8, "Warlock": 8, "Sorcerer": 6, "Wizard": 6}


def tiers(builds_lua):
    with open(builds_lua, encoding="utf-8") as f:
        src = f.read()
    return dict(re.findall(r'id = "(\w+)", name = "[^"]*", tier = "([^"]+)"', src))


def approx_part(model, stats, G, bid, b, act):
    """A build no origin plays: point-buy sheet from its class order (prime 17 -> ASIs, CON 16, DEX 14)."""
    level = {1: 5, 2: 8, 3: 12}[act]
    seq = b["order"][:level]
    first = seq[0]
    ab = {"STR": 10, "DEX": 14, "CON": 16, "INT": 10, "WIS": 10, "CHA": 8}
    ab[PRIME.get(first, "STR")] = min(20, 17 + (1 if level >= 4 else 0) + (2 if level >= 8 else 0))
    prof = 2 + (level - 1) // 4
    con = (ab["CON"] - 10) // 2
    hp = HIT_DIE.get(first, 8) + con + sum((HIT_DIE.get(c, 8) // 2 + 1) + con for c in seq[1:])
    subs = {}
    for lv in b.get("levels") or []:
        for p in lv[1]:
            m = re.match(r"(?:Subclass:\s*)?(Oath of [\w ]+|College of [\w ]+|Circle of [\w ]+|Way of [\w ]+|"
                         r"Path of [\w ]+|Battle Master|Champion|Thief|Assassin|Gloom Stalker)", p)
            if m:
                subs[lv[0]] = m.group(1).strip()
    g = P.grants(G, seq, subs, [], [])
    counts = g["class_levels"]
    mode = "melee"
    plan = {"rounds": [[P.A("Target_MainHandAttack", "action", "@boss", "attack")]],
            "steady": [P.A("Target_MainHandAttack", "action", "@boss", "attack")], "fight_rounds": 4, "mode": mode,
            "selfaoe": False, "defence_opening": []}
    plan["hotbar"] = P.hotbar_rows(plan, g["passives"], g["spells"], [], stats)
    return {"approximate": True, "sheet": {"abilities": ab, "hp": hp, "prof": prof, "level": level},
            "class_levels": counts, "passives_add": g["passives"], "passives_remove": g["passives_remove"],
            "spells_add": g["spells"], "slots": {str(i + 1): n for i, n in enumerate(model.slots(counts))},
            "resources": g["resources"], "plan": plan}


def owned_part(W, model, stats, G, cid, bid, act):
    bare = model.State(W, cid, bid, act, {}, {})
    g = P.grants(G, bare.BI["seq"][: bare.level], bare.subs, bare.feats, bare.styles)
    core = P.core_plan(model, bare, stats)
    core["hotbar"] = P.hotbar_rows(core, g["passives"], g["spells"], [], stats)
    used = {a["spell"] for r in core["rounds"] + [core["steady"]] for a in r}
    return {"approximate": False, "sheet_from": cid,
            "sheet": {"abilities": dict(bare.sheet["ab"]), "hp": bare.sheet["hp"], "prof": bare.sheet["prof"],
                      "level": bare.level},
            "class_levels": g["class_levels"], "subclasses": bare.subs, "feats": bare.feats, "styles": bare.styles,
            "passives_add": g["passives"], "passives_remove": g["passives_remove"],
            "spells_add": sorted(set(g["spells"]) | used),
            "slots": {str(i + 1): n for i, n in enumerate(model.slots(bare.classes))},
            "resources": g["resources"], "plan": core}


def set_entry(W, mech, stats, cid, s, templates):
    items, spells = [], []
    lo = {k: v["sid"] for k, v in (s.get("items") or {}).items() if v and v.get("sid") and v["sid"] in W.items}
    for slot in P.EQUIP_ORDER:
        sid = lo.get(slot)
        if not sid:
            continue
        items.append({"slot": P.SLOT_GAME[slot] or "Elixir", "stats": sid, "template": (templates.get(sid) or [None])[0],
                      "use": slot == "Elixir" or None, "name": W.items[sid].get("name")})
        im = mech.ItemMech(W, sid)
        for spid, hand in im.spells:
            if hand == "o" and slot not in ("OffHand", "RangedOff") or hand == "m" and slot not in ("MainHand", "Ranged"):
                continue
            if not P.NOT_IN_FIGHT.search(spid) and spid in stats:
                spells.append(spid)
    return {"name": s.get("name"), "char": cid, "build": s.get("build"), "act": s.get("act"),
            "origin": s.get("origin"), "items": items, "item_spells": list(dict.fromkeys(spells)), "expect": {}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimizer", required=True)
    ap.add_argument("--optimized", help="the optimizer's export (adds its sets and, when present, set-tuned respecs)")
    ap.add_argument("--out", default=os.path.join(engine.SE_DIR, "LootAdvisor_gauntlet_catalog.json"))
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.abspath(a.optimizer))
    import mech
    import model
    import odata
    W = odata.World()
    stats = W.stats
    G = P.game_lists()
    templates = {sid: (rec.get("templates") or []) for sid, rec in W.items.items()}
    ba = W.D.ba
    tier = tiers(odata.BSA.BUILDS_LUA)
    origins = ba.get("_origins") or {}
    builds = {}
    for bid, b in ba.items():
        if bid.startswith("_"):
            continue
        owners = [c for c in odata.CHARS if bid in W.scores[c]["builds"]]
        pref = [c for c, x in origins.items() if x == bid and c in owners]
        cid = (pref or owners or [None])[0]
        acts = {}
        for act in (1, 2, 3):
            try:
                acts[str(act)] = owned_part(W, model, stats, G, cid, bid, act) if cid else \
                    approx_part(model, stats, G, bid, b, act)
            except Exception as e:  # keep the catalogue usable; the window shows the reason
                acts[str(act)] = {"error": f"{type(e).__name__}: {e}"}
        builds[bid] = {"name": b["name"], "group": "Tier " + tier.get(bid, "?"), "acts": acts}
    sets = {}
    for cid in odata.CHARS:
        for bid, be in W.scores[cid]["builds"].items():
            for act, lst in (be.get("sets") or {}).items():
                for s in lst:
                    sid = s.get("id") or f"{cid}.{bid}.a{act}.{s.get('name')}"
                    e = set_entry(W, mech, stats, cid, dict(s, build=bid, act=int(act)), templates)
                    sets[sid] = e
    if a.optimized:
        with open(a.optimized, encoding="utf-8") as f:
            opt = json.load(f)
        for s in opt.get("sets") or []:
            e = set_entry(W, mech, stats, s["char"], s, templates)
            m = s.get("model") or {}
            e["expect"][f"{s['build']}|{s['act']}"] = {k: m.get(k) for k in ("score", "dpr", "R", "ac", "hp")}
            sets[s["id"]] = e
        for c in opt.get("compare") or []:
            pass
    out = {"version": 1, "enemies": {str(k): dict(v, template=TEMPLATE, hp=ENEMY_HP) for k, v in model.ENEMY.items()},
           "buffs": BUFFS, "haste": HASTE, "enemy_faction": None, "builds": builds, "sets": sets, "tuned": {}}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, default=str)
    print(f"{len(builds)} builds, {len(sets)} sets -> {a.out}")


if __name__ == "__main__":
    main()
