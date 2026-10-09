"""Gauntlet specs: everything the in-game harness needs for one set, as JSON.

    python tools/gauntlet/plan.py --optimizer DIR --pairs pairs.json --out specs.json

DIR is the gear optimizer's code folder (tools/optimizer: odata / model / mech); its model supplies the build sheet
(abilities, HP, proficiency, class levels at the act's level) and its prediction for each set. pairs.json lists
[{"char", "build", "act", "a": <set>, "b": <set>}] where a set is {"name", "items": {slot: {"sid": ...}}}.

Per set the spec holds
  sheet      the build's bare sheet (no gear): abilities, HP, proficiency  -> boosts in game
  passives   class / subclass / feat / fighting-style passives of the build at that level (game Progressions,
             Feats); passives_remove = every other class passive (the test character's own class)
  spells     spells the progressions grant + the spells the round plan casts
  slots      spell slots (multiclass caster level), resources (Rage, Channel Divinity, ...)
  items      root template per slot
  plan       the scripted round plan + the item actions the shared adaptive rule may use
  expect     the model's numbers for the set (sheet AC / HP, DPR, rounds survived) to compare with
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

SLOT_GAME = {"MainHand": "MeleeMainHand", "OffHand": "MeleeOffHand", "Ranged": "RangedMainHand",
             "RangedOff": "RangedOffHand", "Helmet": "Helmet", "Cloak": "Cloak", "Breast": "Breast", "Gloves": "Gloves",
             "Boots": "Boots", "Amulet": "Amulet", "Ring1": "Ring", "Ring2": "Ring2", "Elixir": None}
EQUIP_ORDER = ["Breast", "Helmet", "Cloak", "Gloves", "Boots", "Amulet", "Ring1", "Ring2", "MainHand", "OffHand",
               "Ranged", "RangedOff", "Elixir"]
STYLE_PASSIVE = {"Archery": "FightingStyle_Archery", "Defence": "FightingStyle_Defense",
                 "Defense": "FightingStyle_Defense", "Dueling": "FightingStyle_Dueling",
                 "Great Weapon Fighting": "FightingStyle_GreatWeaponFighting",
                 "Protection": "FightingStyle_Protection", "Two-Weapon Fighting": "FightingStyle_TwoWeaponFighting"}
MANEUVERS = ["TripAttack", "PrecisionAttack", "Riposte"]   # Battle Master picks used by the round plans


# ------------------------------------------------------------------------------------------------ game lists
def game_lists():
    """Progressions, class descriptions, feats and spell lists (later modules override earlier ones by UUID)."""
    import class_progressions as cp
    from pak import GAME_DATA, Pak
    progs, descs = cp.read_game()
    feats, lists = {}, {}
    for pak, mod in cp.MODULES:
        p = Pak(os.path.join(GAME_DATA, pak))
        try:
            for kind, store, nid in (("Feats/Feats.lsx", feats, "Feat"), ("Lists/SpellLists.lsx", lists, "SpellList")):
                n = f"Public/{mod}/{kind}"
                if n in p.by_name:
                    for a in cp._nodes(p.read(p.by_name[n]), nid):
                        store[a["UUID"]] = a
        finally:
            p.close()
    return progs, descs, feats, lists


def _split(s):
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def _norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def grants(G, seq, subs, feats_taken, styles):
    """What the build's class levels give: passives, spells, resources; plus the passives of every class table (to
    remove the ones the test character has from its own class)."""
    progs, descs, feats, lists = G
    by_name = {d["Name"]: d for d in descs.values()}
    table = {d["Name"]: d.get("ProgressionTableUUID") for d in descs.values()}
    sub_of = {}
    for d in descs.values():
        par = next((x for x in descs.values() if x["UUID"] == d.get("ParentGuid")), None)
        if par:
            sub_of.setdefault(par["Name"], {})[_norm(d["Name"])] = d["Name"]
    rows = {}
    for p in progs.values():
        if p.get("ProgressionType") in ("0", "1"):
            rows.setdefault(p.get("TableUUID"), []).append(p)
    all_class_passives = set()
    for t, rs in rows.items():
        for r in rs:
            all_class_passives |= set(_split(r.get("PassivesAdded")))
    passives, removed, spells, res = [], set(), [], {}
    counts = {}
    first = seq[0] if seq else None

    def apply(r, is_first):
        passives.extend(_split(r.get("PassivesAdded")))
        removed.update(_split(r.get("PassivesRemoved")))
        for b in _split(r.get("Boosts")):
            m = re.match(r"ActionResource\((\w+),\s*(\d+),\s*(\d+)\)", b)
            if m and m.group(1) != "SpellSlot":
                k = (m.group(1), int(m.group(3)))
                res[k] = res.get(k, 0) + int(m.group(2))
            m = re.match(r"UnlockSpell\((\w+)", b)
            if m:
                spells.append(m.group(1))
        for sel in _split(r.get("Selectors")):
            m = re.match(r"AddSpells\(([0-9a-f-]{36})", sel)
            if m and m.group(1) in lists:
                spells.extend(_split(lists[m.group(1)].get("Spells")))

    for cls in seq:
        counts[cls] = counts.get(cls, 0) + 1
        lv = counts[cls]
        multi = cls != first
        cands = [r for r in rows.get(table.get(cls), []) if int(r.get("Level") or 0) == lv]
        if lv == 1:
            want = "true" if multi else None
            pick = [r for r in cands if (r.get("IsMulticlass") == "true") == bool(want)] or cands
            cands = pick[:1]
        for r in cands:
            apply(r, cls == first)
        sub = subs.get(cls)
        if sub:
            sname = sub_of.get(cls, {}).get(_norm(sub)) or next(
                (v for k, v in sub_of.get(cls, {}).items() if _norm(sub).startswith(k[:6]) or k.startswith(_norm(sub)[:6])),
                None)
            for r in rows.get(table.get(sname), []) if sname else []:
                if int(r.get("Level") or 0) == lv:
                    apply(r, False)
    by_feat = {_norm(f["Name"]): f for f in feats.values()}
    for f in feats_taken:
        if f.lower().startswith("ability improvement"):
            continue
        rec = by_feat.get(_norm(f))
        if rec:
            passives.extend(_split(rec.get("PassivesAdded")))
    for s in styles:
        if STYLE_PASSIVE.get(s):
            passives.append(STYLE_PASSIVE[s])
    if "Fighter" in counts and "Battle Master" in (subs.get("Fighter") or "") and counts["Fighter"] >= 3:
        passives.extend(MANEUVERS)
    passives = [p for p in dict.fromkeys(passives) if p not in removed]
    remove = sorted(all_class_passives - set(passives))
    resources = [{"kind": k, "level": lv, "n": n} for (k, lv), n in sorted(res.items())]
    return dict(passives=passives, passives_remove=remove, spells=list(dict.fromkeys(spells)), resources=resources,
                class_levels=counts)


# ------------------------------------------------------------------------------------------------ round plans
def A(spell, group, target="@boss", why=None, **kw):
    d = {"spell": spell, "group": group, "target": target}
    if why:
        d["why"] = why
    if group == "free":
        d["cost"] = "free"
    d.update(kw)
    return d


def best_variant(stats, spell, top):
    """Highest upcast variant (<spell>_<n>) the slots allow; the base spell otherwise."""
    for lv in range(top, 0, -1):
        if f"{spell}_{lv}" in stats:
            return f"{spell}_{lv}"
    return spell


def core_plan(model, st, stats):
    """The build's fixed round plan (the optimizer's PLANS, the same rotation its model assumes)."""
    plan, cl = st.plan, st.classes
    n_att = int(st.sheet.get("nAtt") or 1)
    mode = plan["mode"]
    opening, steady, bonus_open, bonus_steady = [], [], [], []
    top = len(model.slots(cl))
    fighter = cl.get("Fighter", 0)

    def attacks(spell, n, target="@boss"):
        return [A(spell, "action", target, "attack")] + [A(spell, "free", target, "Extra Attack", requires="action")
                                                          for _ in range(n - 1)]

    if mode in ("melee", "throw", "ranged"):
        spell = {"melee": "Target_MainHandAttack", "throw": "Throw_Throw", "ranged": "Projectile_MainHandAttack"}[mode]
        main = attacks(spell, n_att)
        if plan.get("superiority") and fighter >= 3:
            main[0] = A("Target_TripAttack", "action", "@boss", "manoeuvre (superiority die)",
                        cost="ActionPoint:1;SuperiorityDie:1", alt=A(spell, "action", "@boss", "attack"))
        if plan.get("smite") and cl.get("Paladin", 0) >= 2:
            main[0] = A("Target_Smite_Divine", "action", "@boss", "Divine Smite",
                        cost="ActionPoint:1;SpellSlotsGroup:1:1:1", alt=A(spell, "action", "@boss", "attack"))
        opening = list(main)
        steady = list(main)
        if fighter >= 2:
            opening = [A("Shout_ActionSurge", "free", "@self", "Action Surge", per="short")] + opening + \
                      [A(spell, "free", "@boss", "Action Surge attack", requires="surge") for _ in range(n_att)]
        if plan.get("rage") and cl.get("Barbarian", 0):
            bonus_open.append(A({"giant": "Shout_Rage_Giant", "frenzy": "Shout_Rage_Frenzy"}.get(plan["rage"],
                                                                                                "Shout_Rage"),
                                "bonus", "@self", "Rage"))
            if plan["rage"] == "frenzy" and cl.get("Barbarian", 0) >= 3:
                bonus_steady.append(A("Throw_FrenziedThrow", "bonus", "@boss", "Enraged Throw"))
        if plan.get("hunters_mark") and cl.get("Ranger", 0) >= 2:
            bonus_open.append(A("Target_HuntersMark", "bonus", "@boss", "Hunter's Mark"))
        if plan.get("vow") and "Vengeance" in (st.subs.get("Paladin") or ""):
            bonus_open.append(A("Target_VowOfEnmity", "bonus", "@boss", "Vow of Enmity"))
        if plan.get("hexblade") and cl.get("Warlock", 0):
            bonus_open.append(A("Target_HexbladesCurse", "bonus", "@boss", "Hexblade's Curse"))
        if plan.get("hex") and cl.get("Warlock", 0):
            bonus_open.append(A("Target_Hex", "bonus", "@boss", "Hex"))
        if plan.get("offhand") == "ranged":
            bonus_steady.append(A("Projectile_OffhandAttack", "bonus", "@boss", "off-hand shot"))
            if cl.get("Rogue", 0) >= 3 and "Thief" in (st.subs.get("Rogue") or ""):
                bonus_steady.append(A("Projectile_OffhandAttack", "bonus", "@boss", "off-hand shot (Fast Hands)"))
        if plan.get("dread") and cl.get("Ranger", 0) >= 3:
            opening.append(A(spell, "free", "@boss", "Dread Ambusher attack", requires="action"))
    else:
        cantrip = plan.get("cantrip")
        nukes = [best_variant(stats, s_, top) for s_, lv in plan.get("nukes") or [] if st.level >= lv
                 and int((stats.get(s_) or {}).get("Level") or 1) <= top]
        chain = A(cantrip, "action", "@boss", "cantrip") if cantrip else None
        for nk in nukes[:1]:
            chain = A(nk, "action", "@boss", "nuke", at_target_pos=nk.startswith("Zone_") or None, alt=chain)
        if plan.get("rotd") and cl.get("Cleric", 0) >= 2:
            chain = A("Shout_RadianceOfTheDawn", "action", "@self", "Radiance of the Dawn", alt=chain)
        steady = [chain] if chain else []
        opening = list(steady)
        if plan.get("conc") and st.level >= plan["conc"][1]:
            opening = [A(best_variant(stats, plan["conc"][0], top), "action", "@self", "concentration spell",
                         alt=chain)]
        if plan.get("spiritual"):
            bonus_open.append(A("Target_SpiritualWeapon", "bonus", "@boss", "Spiritual Weapon"))
        if plan.get("hex") and cl.get("Warlock", 0):
            bonus_open.append(A("Target_Hex", "bonus", "@boss", "Hex"))
    # one bonus action per round: the opening bonus actions go out one per round, then the steady ones
    rounds = []
    for i in range(max(2, len(bonus_open))):
        base = opening if i == 0 else steady
        bon = [bonus_open[i]] if i < len(bonus_open) else list(bonus_steady)
        rounds.append(list(base) + bon)
    return {"rounds": rounds, "steady": steady + bonus_steady, "fight_rounds": 4, "mode": mode,
            "selfaoe": bool(plan.get("conc") or plan.get("rotd")),
            "defence_opening": [a for a in bonus_open if a["target"] == "@self"]}


COMMON_ACTIONS = ["Throw_Throw", "Target_Shove", "Projectile_Jump", "Target_Dip", "Target_Help", "Shout_Dash",
                  "Shout_Disengage"]
NOT_IN_FIGHT = re.compile(r"Thaumaturgy|SpeakWith|Disguise|FindFamiliar|FindSteed|Ritual|Detect|Comprehend|"
                          r"Longstrider|Druidcraft|Prestidigitation|MinorIllusion|Friends|Light$|DancingLights|"
                          r"Message|Knock|Seeming|Speak|Animal|Tongues|Pass", re.I)


def hotbar_rows(plan, passives, spells, item_acts, stats):
    """Manual-mode hotbar rows: the round plan by role, the class / subclass actions and toggles the progressions
    grant at the build's levels (game data; out-of-combat utility left out), common combat actions, item actions."""
    seen = set()

    def take(lst, ids):
        for i in ids:
            if i and i not in seen and (i in stats):
                seen.add(i)
                lst.append(i)

    def ids(actions):
        out = []
        for a in actions:
            while a:
                out.append(a["spell"])
                a = a.get("alt")
        return out
    opener, every, bonus, react, res, items = [], [], [], [], [], []
    r1 = plan["rounds"][0] if plan["rounds"] else []
    take(opener, ids([a for a in r1 if a["group"] != "bonus"]))
    take(every, ids([a for a in plan["steady"] if a["group"] != "bonus"]))
    take(bonus, ids([a for r in plan["rounds"] for a in r if a["group"] == "bonus"]))
    toggles, unlocked = [], []
    for p in passives:
        st_ = stats.get(p) or {}
        if "IsToggled" in (st_.get("Properties") or ""):
            toggles.append(p)
        for kind, sid in re.findall(r"Unlock(Spell|Interrupt)\((\w+)", st_.get("Boosts") or ""):
            (react if kind == "Interrupt" else unlocked).append(sid)
    class_actions = [x for x in list(dict.fromkeys(unlocked + list(spells))) if not NOT_IN_FIGHT.search(x)]
    take(res, [x for x in class_actions if re.search(r"(Rage|ChannelDivinity|ChannelOath|KiPoint|SuperiorityDie|"
                                                       r"BardicInspiration|SorceryPoint|WildShape|LayOnHands)",
                                                       (stats.get(x) or {}).get("UseCosts") or "")])
    take(bonus, [x for x in class_actions if "BonusActionPoint" in ((stats.get(x) or {}).get("UseCosts") or "")])
    take(every, [x for x in class_actions if x not in seen and (stats.get(x) or {}).get("Level") in (None, "0", 0)])
    take(every, [x for x in COMMON_ACTIONS if "BonusActionPoint" not in ((stats.get(x) or {}).get("UseCosts") or "")])
    take(bonus, [x for x in COMMON_ACTIONS if "BonusActionPoint" in ((stats.get(x) or {}).get("UseCosts") or "")])
    take(items, [a["spell"] for a in item_acts])
    return [{"label": "opener", "spells": opener}, {"label": "every turn", "spells": every},
            {"label": "bonus action", "spells": bonus},
            {"label": "reactions and toggles", "spells": react, "passives": sorted(set(toggles))},
            {"label": "class resources", "spells": res}, {"label": "items", "spells": items}]


def item_actions(st, stats, mech):
    """Item spells the shared adaptive rule may use (same rule and priority for both sets): per-rest spells first
    (strongest first), then unlimited bonus-action spells. Non-damaging spells are listed as skipped."""
    out, skipped = [], []
    for slot, im in st.mechs.items():
        for spid, hand in im.spells:
            if hand == "o" and slot not in ("OffHand", "RangedOff") or hand == "m" and slot not in ("MainHand", "Ranged"):
                continue
            s = stats.get(spid) or {}
            costs = s.get("UseCosts") or ""
            cd = s.get("Cooldown") or ""
            sp = mech.read_spell(st.W, spid, st.level)
            group = "bonus" if "BonusActionPoint" in costs else "reaction" if "Reaction" in costs else "action"
            per = "short" if "ShortRest" in cd else "long" if "Rest" in cd else "none"
            rec = {"spell": spid, "item": im.name, "slot": slot, "group": group, "per": per, "cost": costs}
            if not sp or not sp.get("dmg"):
                skipped.append(dict(rec, reason="no damage in the spell data"))
                continue
            if "SpellSlot" in costs:
                skipped.append(dict(rec, reason="costs a spell slot"))
                continue
            if group == "action" and per == "none":
                skipped.append(dict(rec, reason="unlimited action spell: the core plan keeps the action"))
                continue
            dmg = sum(model_avg(e) for e, _t in sp["dmg"]) * (sp.get("targets") or 1)
            rec.update(value=round(dmg, 1), target="@self" if (s.get("SpellType") == "Shout") else "@boss",
                       at_target_pos=spid.startswith("Zone_") or None)
            out.append(rec)
    out.sort(key=lambda r: (r["per"] == "none", -r["value"]))
    return out, skipped


def model_avg(expr):
    tot = 0.0
    for n, d in re.findall(r"(\d+)d(\d+)", expr):
        tot += int(n) * (int(d) + 1) / 2
    return tot


# ------------------------------------------------------------------------------------------------ specs
def spec_for(W, model, mech, G, cid, bid, act, setrec, stats, templates):
    lo = {k: v["sid"] for k, v in (setrec.get("items") or {}).items() if v and v.get("sid") and v["sid"] in W.items}
    bare = model.State(W, cid, bid, act, {}, {})
    st = model.State(W, cid, bid, act, lo, {})
    g = grants(G, bare.BI["seq"][: bare.level], bare.subs, bare.feats, bare.styles)
    pred = model.score(W, cid, bid, act, lo, None, detail=True)
    core = core_plan(model, bare, stats)
    acts, skipped = item_actions(st, stats, mech)
    # choice items (Markoheshkir attunements, elemental weapons): the model's pick is applied as a status in the
    # setup; the spells it unlocks join the item actions
    choice = dict(pred.choice or {})
    for slot, status in choice.items():
        for spid in re.findall(r"UnlockSpell\((\w+)", (stats.get(status) or {}).get("Boosts") or ""):
            sp = mech.read_spell(W, spid, st.level)
            s_ = stats.get(spid) or {}
            if sp and sp.get("dmg"):
                cd = s_.get("Cooldown") or ""
                acts.append({"spell": spid, "item": (W.items[lo[slot]].get("name") if slot in lo else slot),
                             "slot": slot, "group": "bonus" if "BonusActionPoint" in (s_.get("UseCosts") or "")
                             else "action", "per": "short" if "ShortRest" in cd else "long" if "Rest" in cd else "none",
                             "cost": s_.get("UseCosts"), "value": round(sum(model_avg(e) for e, _t in sp["dmg"]) *
                                                                        (sp.get("targets") or 1), 1),
                             "target": "@boss", "at_target_pos": spid.startswith("Zone_") or None})
    acts.sort(key=lambda r: (r["per"] == "none", -r["value"]))
    used = {a["spell"] for r in core["rounds"] + [core["steady"]] for a in r}
    items = []
    for slot in EQUIP_ORDER:
        sid = lo.get(slot)
        if not sid:
            continue
        tpl = (templates.get(sid) or [None])[0]
        items.append({"slot": SLOT_GAME[slot] or "Elixir", "stats": sid, "template": tpl, "use": slot == "Elixir" or None,
                      "name": W.items[sid].get("name")})
    return {
        "char": cid, "build": bid, "act": act, "set": setrec.get("name"), "set_id": setrec.get("id"),
        "sheet": {"abilities": dict(bare.sheet["ab"]), "hp": bare.sheet["hp"], "prof": bare.sheet["prof"],
                  "level": bare.level},
        "class_levels": g["class_levels"], "subclasses": bare.subs, "feats": bare.feats, "styles": bare.styles,
        "passives_add": g["passives"], "passives_remove": g["passives_remove"],
        "spells_add": sorted(set(g["spells"]) | used),
        "slots": {str(i + 1): n for i, n in enumerate(model.slots(bare.classes))},
        "resources": g["resources"], "items": items, "statuses": sorted(set(choice.values())),
        "plan": dict(core, item_actions=acts, item_skipped=skipped,
                     hotbar=hotbar_rows(core, g["passives"], g["spells"], acts, stats)),
        "expect": {"ac": st.sheet["ac"], "hp": st.sheet["hp"], "attacks": st.sheet.get("attacks"),
                   "spell": st.sheet.get("spell"), "dpr": round(pred.dpr, 1), "offence": round(pred.offence, 1),
                   "R": round(pred.R, 2), "score": round(pred.score, 2), "events": pred.events},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimizer", required=True, help="the gear optimizer's code folder")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.abspath(a.optimizer))
    import mech
    import model
    import odata
    W = odata.World()
    stats = W.stats
    templates = {sid: (rec.get("templates") or []) for sid, rec in W.items.items()}
    G = game_lists()
    with open(a.pairs, encoding="utf-8") as f:
        pairs = json.load(f)
    out = []
    for p in pairs:
        row = dict(p, specs={})
        for side in ("a", "b"):
            row["specs"][side] = spec_for(W, model, mech, G, p["char"], p["build"], p["act"], p[side], stats, templates)
        row.pop("a"), row.pop("b")
        out.append(row)
        print(p["char"], p["build"], p["act"], "->", row["specs"]["a"]["set"], "/", row["specs"]["b"]["set"])
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
