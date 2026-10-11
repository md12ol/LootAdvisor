"""Gauntlet specs: everything the in-game harness needs for one set, as JSON.

    python tools/gauntlet/plan.py --optimizer DIR --pairs pairs.json --out specs.json

DIR is the gear optimizer's code folder (tools/optimizer: odata / model / mech); its model supplies the build sheet
(abilities, HP, proficiency, class levels at the act's level) and its prediction for each set. pairs.json lists
[{"char", "build", "act", "a": <set>, "b": <set>}] where a set is {"name", "items": {slot: {"sid": ...}}, "respec"}; respec
names the set's test plan (pairs.py): the sheet, feats, styles and the model's numbers then follow that plan's tuned
respec, the one the test character was given, instead of the build's own picks.

Per set the spec holds
  sheet      the build's bare sheet (no gear): abilities, HP, proficiency  -> boosts in game
  passives   class / subclass / feat / fighting-style passives of the build at that level (game Progressions,
             Feats); passives_remove = every other class passive (the test character's own class)
  spells     spells the progressions grant + the spells the round plan casts
  slots      spell slots (multiclass caster level), resources (Rage, Channel Divinity, ...)
  boosts     the armour / weapon proficiencies the class levels and feats grant (Proficiency(...))
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
MANEUVERS = ["TripAttack", "PrecisionAttack", "Riposte"]   # Battle Master picks when the build names none


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


# Items whose first root template is a story copy: spawning it fires the story (MAG_Gortash_Gloves: the copy that still
# holds Gortash's Netherstone ends his quest line and the game autosaves). The plain copy is used instead.
SAFE_TEMPLATE = {"MAG_Gortash_Gloves": "6ea2650e-c12b-43d9-873e-f3d426d30d18"}


def item_template(sid, templates):
    return SAFE_TEMPLATE.get(sid) or (templates.get(sid) or [None])[0]


def _split(s):
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def _norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def maneuver_picks(per_level):
    """The Battle Master manoeuvres a respec picked ("Manoeuvres: Precision Attack, Trip Attack" in a test plan's
    per-level picks) as passive names, or None when it names none."""
    out = []
    for lv in per_level or []:
        for pick in lv.get("picks") or []:
            m = re.match(r"Man(?:oeu|eu)vres?:\s*(.+)$", pick)
            if m:
                names = re.sub(r"\([^)]*\)", "", m.group(1)).split(",")
                out += [re.sub(r"[^A-Za-z]", "", x) for x in names if x.strip()]
    return out or None


def grants(G, seq, subs, feats_taken, styles, maneuvers=None):
    """What the build's class levels give: passives, spells, resources; plus the passives of every class table (to
    remove the ones the test character has from its own class). maneuvers: the Battle Master picks as passive names
    (default MANEUVERS). A passive any race grants is never in the remove list: the character keeps its race."""
    progs, descs, feats, lists = G
    table = {d["Name"]: d.get("ProgressionTableUUID") for d in descs.values()}
    sub_of = {}
    for d in descs.values():
        par = next((x for x in descs.values() if x["UUID"] == d.get("ParentGuid")), None)
        if par:
            sub_of.setdefault(par["Name"], {})[_norm(d["Name"])] = d["Name"]
    rows, seen = {}, set()
    race_passives = set()
    for p in progs.values():
        if p.get("ProgressionType") == "2":
            race_passives |= set(_split(p.get("PassivesAdded")))
        if p.get("ProgressionType") in ("0", "1"):
            # the game data holds some rows twice under two UUIDs (Battle Master level 3: two rows of 4 superiority
            # dice; the game grants 4): a row equal to another in everything but its UUID counts once
            key = tuple(sorted((k, v) for k, v in p.items() if k != "UUID"))
            if key in seen:
                continue
            seen.add(key)
            rows.setdefault(p.get("TableUUID"), []).append(p)
    all_class_passives = set()
    for t, rs in rows.items():
        for r in rs:
            all_class_passives |= set(_split(r.get("PassivesAdded")))
    passives, removed, spells, res, profs, interrupts = [], set(), [], {}, [], []
    counts, sub_names = {}, {}
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
            m = re.match(r"UnlockInterrupt\((\w+)", b)
            if m:
                interrupts.append(m.group(1))
            if re.match(r"Proficiency\(\w+\)$", b):
                profs.append(b)
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
            if sname:
                sub_names[cls] = sname
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
            profs.extend(b for b in _split(rec.get("Boosts")) if re.match(r"Proficiency\(\w+\)$", b))
    for s in styles:
        if STYLE_PASSIVE.get(s):
            passives.append(STYLE_PASSIVE[s])
    if "Fighter" in counts and "Battle Master" in (subs.get("Fighter") or "") and counts["Fighter"] >= 3:
        passives.extend(maneuvers or MANEUVERS)
    passives = [p for p in dict.fromkeys(passives) if p not in removed]
    remove = sorted(all_class_passives - set(passives) - race_passives)
    resources = [{"kind": k, "level": lv, "n": n} for (k, lv), n in sorted(res.items())]
    return dict(passives=passives, passives_remove=remove, spells=list(dict.fromkeys(spells)), resources=resources,
                class_levels=counts, boosts=list(dict.fromkeys(profs)), interrupts=list(dict.fromkeys(interrupts)),
                subclass_names=sub_names)


# ------------------------------------------------------------------------------------------------ round plans
def A(spell, group, target="@boss", why=None, **kw):
    d = {"spell": spell, "group": group, "target": target}
    if why:
        d["why"] = why
    if group == "free":
        d["cost"] = "free"
    d.update(kw)
    return d


def plan_spells(core):
    """Every spell the round plan may cast, fallbacks included (the sheet must know them all)."""
    used = set()
    for r in core["rounds"] + [core["steady"]]:
        for a in r:
            while a:
                used.add(a["spell"])
                a = a.get("alt")
    return used


def upcast_chain(stats, spell, levels):
    """The spell's variants from the highest slot level the character has down to the base spell: the round plan
    tries them in this order, so a spent L6 slot falls back to L5 and so on instead of failing."""
    out = [f"{spell}_{lv}" for lv in sorted(set(levels), reverse=True) if f"{spell}_{lv}" in stats]
    return list(dict.fromkeys(out + [spell]))


def chain(names, group, target, why, tail=None, **kw):
    """Nested priority chain: names[0] with alt names[1] ... and finally tail."""
    a = tail
    for n in reversed(names):
        a = A(n, group, target, why, alt=a, **kw)
    return a


def parse_costs(s):
    """UseCosts -> [(kind, n, level)], read like the in-game harness does (SpellSlotsGroup:1:1:3 = one L3 slot)."""
    out = []
    for part in (s or "").split(";"):
        f = [x.strip() for x in part.split(":")]
        if f[0] == "SpellSlotsGroup":
            out.append(("SpellSlot", int(f[1]) if len(f) > 1 else 1, int(f[3]) if len(f) > 3 else 1))
        elif f[0]:
            out.append((f[0], int(f[1]) if len(f) > 1 and f[1].isdigit() else 1,
                        int(f[2]) if len(f) > 2 and f[2].isdigit() else 0))
    return out


TURN_RESOURCES = {"ActionPoint": 1, "BonusActionPoint": 1, "ReactionActionPoint": 1, "Movement": 9}


def forecast(plan, slots, resources, stats, n_rounds=16):
    """What the round plan will cast with the character's resources: per round, the first affordable action of each
    chain (the same choice the in-game harness makes each turn). No rests. -> [[spell, ...] per round]."""
    pool = {("SpellSlot", int(lv)): int(n) for lv, n in (slots or {}).items()}
    for r in resources or []:
        k = (r["kind"], int(r.get("level") or 0))
        pool[k] = pool.get(k, 0) + r["n"]
    out = []
    for i in range(n_rounds):
        turn = dict(TURN_RESOURCES)
        lst = plan["rounds"][i] if i < len(plan["rounds"]) else plan["steady"]
        picks = []
        for a in lst:
            while a:
                spec = (stats.get(a["spell"]) or {}).get("UseCosts")
                costs = [] if a.get("cost") == "free" else parse_costs(a.get("cost") or spec)
                ok = all((turn[k] if k in turn else pool.get((k, lv), 0)) >= n for k, n, lv in costs)
                if ok:
                    for k, n, lv in costs:
                        if k in turn:
                            turn[k] -= n
                        else:
                            pool[(k, lv)] -= n
                    picks.append(a["spell"])
                    break
                a = a.get("alt")
        out.append(picks)
    return out


def granted_interrupts(passives, item_stats, stats):
    """Interrupts (reactions) the build's passives and the set's items unlock: UnlockInterrupt in their Boosts, also
    through an item's PassivesOnEquip."""
    out = []

    def scan(sid, depth=0):
        st_ = stats.get(sid) or {}
        out.extend(re.findall(r"UnlockInterrupt\((\w+)", st_.get("Boosts") or ""))
        if depth == 0:
            for p in _split(st_.get("PassivesOnEquip")):
                scan(p, 1)
    for p in passives:
        scan(p, 1)
    for sid in item_stats:
        scan(sid)
    return list(dict.fromkeys(out))


# reactions every set has and the model counts (both sides of a pair alike)
COMMON_REACTIONS = ["Interrupt_AttackOfOpportunity"]


def reaction_policy(build_interrupts, set_interrupts):
    """The plan's reaction answers: the build's and the set's reactions fire on their own ("auto"); everything else
    the test character has (racial, tadpole, its own class and items) stays off ("never", the harness default)."""
    return {k: "auto" for k in list(build_interrupts) + list(set_interrupts) + COMMON_REACTIONS}


def core_plan(model, st, stats):
    """The build's fixed round plan (the optimizer's PLANS, the same rotation its model assumes)."""
    plan, cl = st.plan, st.classes
    n_att = int(st.sheet.get("nAtt") or 1)
    mode = plan["mode"]
    opening, steady, bonus_open, bonus_steady = [], [], [], []
    top = len(model.slots(cl))
    slot_levels = [i + 1 for i, n in enumerate(model.slots(cl)) if n]
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
        nukes = [s_ for s_, lv in plan.get("nukes") or [] if st.level >= lv
                 and int((stats.get(s_) or {}).get("Level") or 1) <= top]
        # each spell as a chain: highest slot first, down to the base spell, then the cantrip
        act = A(cantrip, "action", "@boss", "cantrip") if cantrip else None
        for nk in nukes[:1]:
            act = chain(upcast_chain(stats, nk, slot_levels), "action", "@boss", "nuke", tail=act,
                        at_target_pos=nk.startswith("Zone_") or None)
        if plan.get("rotd") and cl.get("Cleric", 0) >= 2:
            act = A("Shout_RadianceOfTheDawn", "action", "@self", "Radiance of the Dawn", alt=act)
        steady = [act] if act else []
        opening = list(steady)
        if plan.get("conc") and st.level >= plan["conc"][1]:
            opening = [chain(upcast_chain(stats, plan["conc"][0], slot_levels), "action", "@self",
                             "concentration spell", tail=act)]
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


def spell_requirements(stats, spid):
    """What a spell needs besides its cost, read from its RequirementConditions: a melee weapon (weapon actions such as
    Topple), proficiency with the wielded weapon, not being encumbered."""
    req = (stats.get(spid) or {}).get("RequirementConditions") or ""
    out = []
    if "CanUseWeaponActions" in req:
        out.append("melee weapon")
    if "IsProficientWithEquippedWeapon" in req:
        out.append("proficient weapon")
    if "ENCUMBERED" in req:
        out.append("not encumbered")
    return out


def unusable_reason(stats, spid, main_hand, proficiencies):
    """Why the character could never cast this spell with the set (None when it can): a weapon action without a melee
    weapon in the main hand, or with a weapon the build is not proficient with. The game refuses such a cast."""
    reqs = spell_requirements(stats, spid)
    if "melee weapon" in reqs and not main_hand:
        return "needs a melee weapon in the main hand"
    if "proficient weapon" in reqs and main_hand:
        groups = [g for g in re.split(r"[;,]\s*", (stats.get(main_hand) or {}).get("Proficiency Group") or "") if g]
        if groups and not set(groups) & set(proficiencies):
            return f"not proficient with {main_hand}"
    return None


def model_avg(expr):
    tot = 0.0
    for n, d in re.findall(r"(\d+)d(\d+)", expr):
        tot += int(n) * (int(d) + 1) / 2
    return tot


# ------------------------------------------------------------------------------------------------ reach
# How far from the caster a spell's effect can land, for the spacing of two lanes fighting at once. A weapon attack's
# range names the weapon's range; a spell that spawns more projectiles (Chain Lightning) reaches as far again from
# the target it hit.
WEAPON_RANGE = {"MeleeMainWeaponRange": 3.0, "MeleeOffHandWeaponRange": 3.0, "RangedMainWeaponRange": 18.0,
                "RangedOffHandWeaponRange": 18.0, "ThrownObjectRange": 18.0}
AREA_KEYS = ("AreaRadius", "ExplodeRadius", "HitRadius", "SurfaceRadius")


def _num(v, default=0.0):
    if v in WEAPON_RANGE:
        return WEAPON_RANGE[v]
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def spell_reach(stats, spid, seen=()):
    """Metres from the caster to the farthest point the spell's effect can land: the zone's length, or the target
    range plus the largest area radius, plus the reach of the projectiles it spawns from the target (a spell that
    spawns itself again counts once)."""
    st = stats.get(spid) or {}
    if not st or spid in seen or len(seen) > 3:
        return 0.0
    if st.get("SpellType") == "Zone":
        own = _num(st.get("Range"))
    else:
        own = _num(st.get("TargetRadius")) + max([_num(st.get(k)) for k in AREA_KEYS] + [0.0])
    props = ";".join(st.get(k) or "" for k in ("SpellSuccess", "SpellFail", "SpellProperties"))
    spawned = [spell_reach(stats, x, tuple(seen) + (spid,)) for x in re.findall(r"SpawnExtraProjectiles\((\w+)", props)]
    return own + max(spawned + [0.0])


def set_reach(stats, spells):
    """-> {"m": the largest reach over the spells, "spell": the spell that reaches that far}."""
    best = (0.0, None)
    for sp in spells:
        r = spell_reach(stats, sp)
        if r > best[0]:
            best = (r, sp)
    return {"m": round(best[0], 1), "spell": best[1]}


def item_proficiency(stats, sid, profs):
    """Is the character proficient with this item (None: the item needs no proficiency)? profs = the build's
    proficiency groups plus the ones the set's items grant."""
    grp = (stats.get(sid) or {}).get("Proficiency Group") or ""
    groups = [g for g in re.split(r"[;,]\s*", grp) if g and g != "None"]
    if not groups:
        return None
    return bool(set(groups) & set(profs))


def granted_proficiencies(stats, sids):
    """Proficiency groups the items grant (Proficiency(X) in their Boosts or an equip passive's)."""
    out = []
    for sid in sids:
        st = stats.get(sid) or {}
        txt = st.get("Boosts") or ""
        for p in _split(st.get("PassivesOnEquip")):
            txt += ";" + ((stats.get(p) or {}).get("Boosts") or "")
        out += re.findall(r"Proficiency\((\w+)\)", txt)
    return out


# ------------------------------------------------------------------------------------------------ specs
def spec_for(W, model, mech, G, cid, bid, act, setrec, stats, templates, respec=None, maneuvers=None):
    """respec: the test plan's tuned respec (pairs.tuned_respec) the test character was given, or None for the
    build's own picks; the sheet, feats, styles, plan and the model's numbers follow it. maneuvers: the plan's Battle
    Master picks (maneuver_picks)."""
    lo = {k: v["sid"] for k, v in (setrec.get("items") or {}).items() if v and v.get("sid") and v["sid"] in W.items}
    bare = model.State(W, cid, bid, act, {}, {}, respec=respec)
    st = model.State(W, cid, bid, act, lo, {}, respec=respec)
    g = grants(G, bare.BI["seq"][: bare.level], bare.subs, bare.feats, bare.styles, maneuvers=maneuvers)
    pred = model.score(W, cid, bid, act, lo, None, detail=True, respec=respec)
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
    # requirements checked before the run: an item spell the character could never cast with this set is not planned
    profs = re.findall(r"Proficiency\((\w+)\)", ";".join(g["boosts"]))
    keep = []
    for rec in acts:
        why = unusable_reason(stats, rec["spell"], lo.get("MainHand"), profs)
        if why:
            skipped.append(dict(rec, reason="unusable: " + why))
        else:
            keep.append(rec)
    acts = keep
    used = plan_spells(core)
    items = []
    for slot in EQUIP_ORDER:
        sid = lo.get(slot)
        if not sid:
            continue
        tpl = item_template(sid, templates)
        items.append({"slot": SLOT_GAME[slot] or "Elixir", "stats": sid, "template": tpl, "use": slot == "Elixir" or None,
                      "name": W.items[sid].get("name")})
    # proficiency per worn item: the build's (class, race, feats) and what the set's items grant; the setup check reads
    # the game's own answer (the "not proficient" warning) for every item marked true
    build_profs = (W.build_entry(cid, bid).get("proficiencies") or []) if hasattr(W, "build_entry") else []
    profs_all = set(build_profs) | set(re.findall(r"Proficiency\((\w+)\)", ";".join(g["boosts"])))
    profs_all |= set(granted_proficiencies(stats, [it["stats"] for it in items]))
    for it in items:
        if not it.get("use"):
            it["proficient"] = item_proficiency(stats, it["stats"], profs_all)
    item_unlocks = re.findall(r"UnlockSpell\((\w+)", ";".join((stats.get(it["stats"]) or {}).get("Boosts") or ""
                                                                 for it in items))
    slots = {str(i + 1): n for i, n in enumerate(model.slots(bare.classes))}
    set_interrupts = granted_interrupts([], [it["stats"] for it in items], stats)
    build_interrupts = list(dict.fromkeys(g["interrupts"] + granted_interrupts(g["passives"], [], stats)))
    return {
        "char": cid, "build": bid, "act": act, "set": setrec.get("name"), "set_id": setrec.get("id"),
        "respec_from": setrec.get("respec"),
        "sheet": {"abilities": dict(bare.sheet["ab"]), "hp": bare.sheet["hp"], "prof": bare.sheet["prof"],
                  "level": bare.level},
        "class_levels": g["class_levels"], "subclasses": bare.subs, "subclass_names": g["subclass_names"],
        "feats": bare.feats, "styles": bare.styles,
        "spells_plan": sorted({re.sub(r"_\d+$", "", x) for x in used}),
        "reach": set_reach(stats, sorted(used | {a["spell"] for a in acts} | set(item_unlocks))),
        "passives_add": g["passives"], "passives_remove": g["passives_remove"],
        "spells_add": sorted(set(g["spells"]) | used),
        "slots": slots,
        "resources": g["resources"], "boosts": g["boosts"], "items": items, "statuses": sorted(set(choice.values())),
        "plan": dict(core, item_actions=acts, item_skipped=skipped,
                     hotbar=hotbar_rows(core, g["passives"], g["spells"], acts, stats),
                     reactions=reaction_policy(build_interrupts, set_interrupts), reactions_default="never",
                     forecast=forecast(core, slots, g["resources"], stats)),
        "expect": {"ac": st.sheet["ac"], "hp": st.sheet["hp"], "attacks": st.sheet.get("attacks"),
                   "spell": st.sheet.get("spell"), "dpr": round(pred.dpr, 1), "offence": round(pred.offence, 1),
                   "R": round(pred.R, 2), "score": round(pred.score, 2), "events": pred.events},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimizer", required=True, help="the gear optimizer's code folder")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--test-plans", help="the optimizer's test plans (default: pairs.py TEST_PLANS)")
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.abspath(a.optimizer))
    import mech
    import model
    import odata
    import pairs as PA
    import respec as RS
    plans = PA.load_test_plans(a.test_plans or PA.TEST_PLANS)
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
            pid = p[side].get("respec")
            r = PA.tuned_respec(W, model, RS.tune, plans, pid) if pid else None
            mv = maneuver_picks(((plans.get(pid) or {}).get("respec") or {}).get("per_level")) if pid else None
            row["specs"][side] = spec_for(W, model, mech, G, p["char"], p["build"], p["act"], p[side], stats, templates,
                                          respec=r, maneuvers=mv)
        row.pop("a"), row.pop("b")
        out.append(row)
        print(p["char"], p["build"], p["act"], "->", row["specs"]["a"]["set"], "/", row["specs"]["b"]["set"])
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
