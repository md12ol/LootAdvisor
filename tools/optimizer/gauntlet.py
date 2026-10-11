"""Test plans for an in-game measurement ("gauntlet"): one machine-readable plan per set (optimizer and research
sets), written by run.py to tools/optimizer/.cache/test_plans.json. Format "loot-advisor-test-plan/1":

  {"format", "generated", "assumptions": {rounds_per_fight, fights_per_long_rest, short_rest_windows,
                                          enemy: {act: {ac, save, atk, dmg, dc, hp}}},
   "plans": [plan, ...],
   "contested": [{"ownership", "act", "item", "name", "owner", "pick", "gain_owner", "gain_pick", "margin",
                  "close": both gain from it, "sets": {char: [set id, ...]}}, ...]}
  contested = unique items the party step's 10% rule kept with their owner although the solver preferred "pick"
  (margin = pick's gain / owner's gain - 1, null when the owner gains nothing); the in-game test confirms them

  plan = {
    "id": set id ("<char>.<build>.a<act>.opt" / research set id), "source": "optimizer" | "research",
    "char", "build", "act", "level", "ownership": "party" | "free" (optimizer sets),
    "classes": [[class, levels at this level, subclass or null], ...], "level_sequence": [class per level],
    "respec": {"tuned": bool, "per_level": [{"level", "class", "class_level", "picks": [str]}],
               "abilities": {ability: score at this level before gear}, "feats": [..], "fighting_styles": [..],
               "cantrip": spell id or null, "score_untuned", "score_tuned"},
      level 0 of per_level = point buy and racial bonus; picks are "Feat: ...", "Fighting Style: ...",
      "Cantrip: <spell id>" and the build's own Builds.lua picks (spells, manoeuvres, invocations, metamagic)
    "gear": {slot: {"id": stats id, "name"}}, "choices": {slot: status id} (Markoheshkir attunement),
    "buffs": [{"id", "kind": "elixir" | "class" | "spell", "when": "before combat" | "round 1 bonus action" ...}],
    "toggles": [passive id]: the toggled passives the model's attacks assume switched on (Great Weapon Master /
               Sharpshooter "All In": -5 to hit, +10 damage); a test switches them on before the fight,
    "rounds": [{"round": n, "actions": [{"resource": "Action" | "BonusAction" | "Reaction" | "Free",
                                         "id": spell / action id, "slot": weapon slot or null, "repeat": n}]}],
    "expected": {"dpr": model damage per round (long-rest average), "score",
                 "per_use": [{"name", "id", "per_round", "damage_per_use", "damage_per_round"}],
                 "scenarios": {"boss": {"dpr", "taken", "R"}}: the same set scored for the gauntlet's boss fight
                 (model.SCENARIOS: one enemy that never dies, one 16-round fight, no short rest, no stealth opener),
                 the number a boss run's damage per round compares with},
    "enemy": {ac, save, atk, dmg, dc, hp} of the act,
    "kept_by_threshold": optimizer plans only: [{"item", "name", "keeps": this character keeps it, "owner",
                         "other", "margin", "close"}] of the contested list above that this plan's gear holds
  }

The round plan is the FIRST fight after a long rest (every per-rest resource available); "expected.per_use" is
the model's damage of one use of each action so a measured fight can be compared action by action; "dpr" is the
model's long-rest average (4 fights, 3 short-rest windows).
"""
import model
import odata

FORMAT = "loot-advisor-test-plan/1"
TOGGLES = ("GreatWeaponMaster_BonusDamage", "Sharpshooter_AllIn")
ATTACK_ID = {"melee": ("Target_MainHandAttack", "MainHand"), "ranged": ("Projectile_MainHandAttack", "Ranged"),
             "throw": ("Throw_Throw", "MainHand")}


def envelope(plans, generated):
    return {"format": FORMAT, "generated": generated,
            "assumptions": {"rounds_per_fight": model.ROUNDS, "fights_per_long_rest": model.FIGHTS,
                            "short_rest_windows": model.SR_WINDOWS,
                            "enemy": {a: dict(model.ENEMY[a], hp=model.ENEMY_HP[a]) for a in (1, 2, 3)}},
            "plans": plans}


def _upcast(W, sid, slot_level):
    if slot_level and isinstance(W.stats.get(f"{sid}_{slot_level}"), dict):
        return f"{sid}_{slot_level}"
    return sid


def rounds_plan(W, r):
    """First fight after a long rest, from the model's events of this loadout."""
    st = r.st
    plan = st.plan
    ev = [e for e in (r.plan_events or []) if not e.get("dropped")]
    R = model.ROUNDS
    rounds = [{"round": i + 1, "actions": []} for i in range(R)]

    def add(i, resource, id_, slot=None, repeat=1):
        if 0 <= i < R and id_:
            rounds[i]["actions"].append({"resource": resource, "id": id_, "slot": slot, "repeat": repeat})
    ba_used = [False] * R
    if plan["mode"] != "caster":
        atk_id, slot = ATTACK_ID[plan["mode"]]
        n_att = st.sheet["nAtt"]
        setup = []
        if st.rages:
            setup.append("Shout_Rage_Giant" if plan.get("rage") == "giant" else
                         "Shout_Rage_Frenzy" if plan.get("rage") == "frenzy" else "Shout_Rage")
        if plan.get("vow") and st.classes.get("Paladin", 0) >= 3:
            setup.append("Target_VowOfEnmity")
        if plan.get("hexblade") and st.classes.get("Warlock", 0) >= 1:
            setup.append("Target_HexbladesCurse")
        if plan.get("hunters_mark") and st.classes.get("Ranger", 0) >= 2:
            setup.append("Target_HuntersMark")
        if plan.get("hex") and st.classes.get("Warlock", 0) >= 1:
            setup.append("Target_Hex")
        for i, s in enumerate(setup[:R]):
            add(i, "BonusAction", s)
            ba_used[i] = True
        item_actions = [e for e in ev if e.get("kind") == "spell" and e.get("cost") == "action"]
        item_bonus = [e for e in ev if e.get("kind") == "spell" and e.get("cost") == "bonus"]
        for i in range(R):
            if i > 0 and item_actions:
                e = item_actions.pop(0)
                add(i, "Action", e["spell"])
            else:
                add(i, "Action", atk_id, slot, n_att)
        if st.classes.get("Fighter", 0) >= 2:
            add(0, "Free", "Shout_ActionSurge")
            add(0, "Action", atk_id, slot, n_att)
        offhand = next((e for e in ev if e["name"] == "off-hand shot"), None)
        enraged = next((e for e in ev if e["name"] == "Enraged Throw"), None)
        fast_hands = st.classes.get("Rogue", 0) >= 3 and "Thief" in (st.subs.get("Rogue") or "")
        for i in range(R):
            n_ba = (0 if ba_used[i] else 1) + (1 if fast_hands else 0)
            if item_bonus and n_ba:
                add(i, "BonusAction", item_bonus.pop(0)["spell"])
                n_ba -= 1
            if offhand and n_ba:
                add(i, "BonusAction", "Projectile_OffhandAttack", "RangedOff", n_ba)
            elif enraged and n_ba:
                add(i, "BonusAction", "Throw_FrenziedThrow", "MainHand", n_ba)
        if plan.get("smite"):
            add(0, "Reaction", "Interrupt_Smite_Divine")
    else:
        conc = next((e for e in ev if e["name"] == "Spirit Guardians"), None)
        order = []
        if conc:
            order.append(conc["spell"])
        if plan.get("control"):
            order.append(plan["control"][0])
        bud = sorted([e for e in ev if e.get("kind") == "spell" and e["name"] not in
                      ("Spirit Guardians", "Spiritual Weapon", "cantrip", "Destructive Wrath") and e.get("n")],
                     key=lambda e: -e["dmg"] / e["n"] if e["n"] else 0)
        for e in bud:
            order.append(e["spell"])
        cantrip = plan.get("cantrip")
        for i in range(R):
            add(i, "Action", order[i] if i < len(order) else cantrip)
        if plan.get("spiritual") and st.level >= 3:
            add(0, "BonusAction", "Target_SpiritualWeapon")
        elif plan.get("hex") and st.classes.get("Warlock", 0) >= 1:
            add(0, "BonusAction", "Target_Hex")
        if plan.get("dw") and st.classes.get("Cleric", 0) >= 2:
            add(0, "Reaction", "Interrupt_DestructiveWrath")
    return rounds


def test_plan(W, r, set_id, loadout, source, ownership=None, tuning=None):
    """r = model.score(..., detail=True) of the set's loadout (with its tuned respec when there is one)."""
    import respec as RS
    st = r.st
    cid, bid, act = st.cid, st.bid, st.act
    lvl = odata.ACT_LEVEL[act]
    subs = st.subs
    classes, seen = [], []
    for c in st.BI["seq"][:lvl]:
        if c not in seen:
            seen.append(c)
    for c in seen:
        classes.append([c, st.classes[c], subs.get(c)])
    buffs = []
    if loadout.get("Elixir"):
        buffs.append({"id": loadout["Elixir"], "kind": "elixir", "when": "before combat"})
    on = any(e.get("toggle") and e.get("n") for e in r.plan_events or [] if not e.get("dropped"))
    toggles = [p for p in TOGGLES if on and p in st.class_passives]
    per_use = []
    for e in r.plan_events or []:
        if e.get("dropped"):
            continue
        n = e.get("n") or 0.0
        per_use.append({"name": e["name"], "id": e.get("spell") or ATTACK_ID.get(st.plan["mode"], (None,))[0],
                        "per_round": round(n, 4), "damage_per_use": round(e["dmg"] / n, 2) if n else None,
                        "damage_per_round": e["dmg"]})
    tuning = tuning or {}
    sp = tuning.get("space") or RS.Space(W, cid, bid)
    out_respec = {"tuned": bool(tuning.get("respec")),
                  "per_level": RS.pick_list(sp, tuning.get("state"), lvl),
                  "abilities": dict(st.sheet["abBase"]), "feats": [f["n"] for f in st.BI["feats"]
                                                                   if f["lv"] is None or f["lv"] <= lvl],
                  "fighting_styles": list(st.styles), "cantrip": st.plan.get("cantrip"),
                  "score_untuned": round(tuning.get("untuned", r.score), 2),
                  "score_tuned": round(tuning.get("tuned", r.score), 2)}
    return {"id": set_id, "source": source, "char": cid, "build": bid, "act": act, "level": lvl,
            "ownership": ownership, "classes": classes, "level_sequence": st.BI["seq"][:lvl], "respec": out_respec,
            "gear": {s: {"id": sid, "name": W.items[sid]["name"]} for s, sid in loadout.items()},
            "choices": dict(r.choice), "buffs": buffs, "toggles": toggles, "rounds": rounds_plan(W, r),
            "expected": {"dpr": round(r.dpr, 2), "score": round(r.score, 2), "per_use": per_use,
                         "scenarios": {"boss": model.scenario_numbers(W, cid, bid, act, loadout, "boss",
                                                                      tuning.get("respec"), dict(r.choice))}},
            "enemy": dict(model.ENEMY[act], hp=model.ENEMY_HP[act])}
