"""Respec tuning: for one set (gear) of a build at an act's level, re-pick what a respec can change and keep what it
cannot (classes, subclasses, the level split): point-buy abilities and the racial +2 / +1, the ASI / feat pick at
every ability-improvement level, fighting styles and the damage cantrip, scored with the same model score as the
gear search (model.score, the planned build's no-gear durability as reference).

Rules (BG3): point buy 27 points, each ability 8-15 before the racial +2 / +1 (two different abilities), an ASI
gives +2 to one ability or +1 to two, no ability above 20 from ASIs; a feat once (except ASIs); half-feats give +1
to one of their abilities; Spell Sniper / War Caster need a spellcasting class; fighting styles only from the
classes that grant them, each once; cantrips from the casting classes' lists (CANTRIPS, checked against the game's
spell stats: a cantrip = Level 0). Gear that sets an ability (Gloves of Dexterity, giant-strength elixirs,
Headband of Intellect: AbilityOverrideMinimum) or gives a feat's effect is part of the score, so the points and
picks it makes redundant move elsewhere by themselves.

Kept from the plan (the model gives them no different value, so tuning them would be noise): spells known other
than the damage cantrip, manoeuvres, invocations, metamagic, skills; they stay as the Builds.lua level picks.

The search is a hill climb from the planned build over single changes (one point-buy point, the racial bonus, one
level's pick, one style, the cantrip) until no change improves the score. The planned build is always a
candidate: the tuned score is never below the untuned one.
"""
import itertools
import re

import model

ABILS = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINTS = 27
ASI_LEVELS = {"Fighter": (4, 6, 8, 12), "Rogue": (4, 8, 10, 12)}
# feats the model values (model.FEAT_PASSIVES, the sheet's Alert, War Caster's concentration Advantage); half-feats
# with the abilities their +1 can go to
FEATS = {"Great Weapon Master": (), "Sharpshooter": (), "Savage Attacker": (), "Alert": (),
         "Tavern Brawler": ("STR", "CON"), "Spell Sniper": (), "War Caster": ()}
HALF = {"Tavern Brawler": ("STR", "CON"), "Resilient": ABILS, "Athlete": ("STR", "DEX"),
        "Lightly Armoured": ("STR", "DEX"), "Moderately Armoured": ("STR", "DEX"), "Heavily Armoured": ("STR",),
        "Heavy Armour Master": ("STR",), "Actor": ("CHA",), "Durable": ("CON",), "Observant": ("INT", "WIS"),
        "Weapon Master": ("STR", "DEX")}
CASTERS = {"Wizard", "Sorcerer", "Cleric", "Warlock", "Druid", "Bard", "Paladin", "Ranger"}
STYLE_CLASSES = {"Fighter": 1, "Paladin": 2, "Ranger": 2}
STYLES = {"Fighter": ("Archery", "Defence", "Duelling", "Great Weapon Fighting", "Protection", "Two-Weapon Fighting"),
          "Paladin": ("Defence", "Duelling", "Great Weapon Fighting", "Protection"),
          "Ranger": ("Archery", "Defence", "Duelling", "Two-Weapon Fighting")}
CANTRIPS = {"Wizard": ("Projectile_FireBolt", "Projectile_RayOfFrost", "Target_ShockingGrasp"),
            "Sorcerer": ("Projectile_FireBolt", "Projectile_RayOfFrost", "Target_ShockingGrasp"),
            "Cleric": ("Target_SacredFlame", "Target_TollTheDead"),
            "Warlock": ("Projectile_EldritchBlast",)}
MAX_EVALS = 900


def half_feat(name):
    """-> abilities a half-feat's +1 can go to, or ()."""
    for k, v in HALF.items():
        if name.lower().startswith(k.lower()):
            m = re.search(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)", name)
            if m and k == "Resilient":
                return (m.group(1)[:3].upper(),)
            return v
    return ()


def asi_levels(seq):
    out, cnt = [], {}
    for i, c in enumerate(seq):
        cnt[c] = cnt.get(c, 0) + 1
        if cnt[c] in ASI_LEVELS.get(c, (4, 8, 12)):
            out.append(i + 1)
    return out


class Space:
    """The respec of one build: decomposes the planned abilities into point buy + racial + picks."""

    def __init__(self, W, cid, bid):
        self.W, self.cid, self.bid = W, cid, bid
        BI = W.build_input(cid, bid)
        self.BI = BI
        self.seq = list(BI["seq"])
        self.plan = model.PLANS.get(bid, {})
        self.levels = asi_levels(self.seq)
        classes = set(self.seq)
        self.casting = bool(classes & CASTERS)
        # planned picks per ASI level; a half-feat's hidden +1 goes to its first ability the plan can carry
        by_lv = {f["lv"]: f for f in BI["feats"] if f.get("lv")}
        self.picks0 = {}
        for lv in self.levels:
            f = by_lv.get(lv)
            if not f:
                self.picks0[lv] = None
            elif f.get("asi"):
                self.picks0[lv] = ("asi", tuple(sorted(f["asi"].items())))
            else:
                self.picks0[lv] = ("feat", f["n"], None)
        self.extra_feats = [f for f in BI["feats"] if not f.get("lv") or f["lv"] not in self.levels]
        pre = dict(BI["base"])
        for p in self.picks0.values():
            if p and p[0] == "asi":
                for k, v in p[1]:
                    pre[k] -= v
        self.decomposed = self._decompose(pre)
        self.styles0 = list(BI["styles"])
        self.style_classes = [c for c in STYLE_CLASSES if c in classes]
        self.cantrip0 = self.plan.get("cantrip")
        cls_cant = set()
        for c in classes:
            cls_cant |= {x for x in CANTRIPS.get(c, ()) if int((W.stats.get(x) or {}).get("Level") or 1) == 0}
        self.cantrips = sorted(cls_cant | ({self.cantrip0} if self.cantrip0 else set()))

    def _decompose(self, pre):
        """pre-ASI abilities -> (point buy, racial +2 ability, racial +1 ability, half-feat bumps) or None."""
        halves = [(lv, p[1]) for lv, p in self.picks0.items() if p and p[0] == "feat" and half_feat(p[1])]
        bump_opts = [[(lv, a) for a in half_feat(n)] for lv, n in halves]
        for bumps in itertools.product(*bump_opts) if bump_opts else [()]:
            b = dict(pre)
            for _lv, a in bumps:
                b[a] -= 1
            for r2, r1 in itertools.permutations(ABILS, 2):
                pb = dict(b)
                pb[r2] -= 2
                pb[r1] -= 1
                if all(8 <= pb[k] <= 15 for k in ABILS) and sum(COST[pb[k]] for k in ABILS) <= POINTS:
                    for lv, a in bumps:
                        self.picks0[lv] = ("feat", self.picks0[lv][1], a)
                    return pb, r2, r1
        return None

    # ------------------------------------------------------------------ state <-> respec
    def initial(self):
        if not self.decomposed:
            return None
        pb, r2, r1 = self.decomposed
        return dict(pb=dict(pb), r2=r2, r1=r1, picks=dict(self.picks0), styles=list(self.styles0),
                    cantrip=self.cantrip0)

    def respec(self, s):
        base = {k: s["pb"][k] + (2 if k == s["r2"] else 0) + (1 if k == s["r1"] else 0) for k in ABILS}
        feats = []
        for lv in self.levels:
            p = s["picks"].get(lv)
            if not p:
                continue
            if p[0] == "asi":
                asi = dict(p[1])
                for k, v in asi.items():
                    base[k] += v
                name = "Ability Improvement " + " ".join(f"+{v} {k}" for k, v in sorted(asi.items(), key=lambda t: -t[1]))
                feats.append({"n": name, "lv": lv, "asi": asi})
            else:
                asi = {p[2]: 1} if p[2] else {}
                for k, v in asi.items():
                    base[k] += v
                feats.append({"n": p[1], "lv": lv, "asi": asi})
        feats += [dict(f) for f in self.extra_feats]
        key = repr((sorted(base.items()), [(f["n"], f["lv"]) for f in feats], s["styles"], s["cantrip"]))
        return {"base": base, "feats": feats, "styles": list(s["styles"]), "cantrip": s["cantrip"], "key": key}

    def valid(self, s):
        pb = s["pb"]
        if not all(8 <= pb[k] <= 15 for k in ABILS) or sum(COST[pb[k]] for k in ABILS) > POINTS:
            return False
        if s["r2"] == s["r1"]:
            return False
        r = self.respec(s)
        if any(v > 20 for v in r["base"].values()):
            return False
        names = [f["n"] for f in r["feats"] if not f["n"].startswith("Ability Improvement")]
        if len(names) != len(set(names)):
            return False
        if len(s["styles"]) != len(set(s["styles"])):
            return False
        return True

    # ------------------------------------------------------------------ moves
    def neighbours(self, s, level):
        out = []
        for a, b in itertools.permutations(ABILS, 2):
            t = _copy(s)
            t["pb"][a] -= 1
            t["pb"][b] += 1
            out.append(t)
        for r2, r1 in itertools.permutations(ABILS, 2):
            if (r2, r1) != (s["r2"], s["r1"]):
                t = _copy(s)
                t["r2"], t["r1"] = r2, r1
                out.append(t)
        for lv in self.levels:
            if lv > level:
                continue                     # a pick after this act's level cannot matter here
            for opt in self.pick_options():
                if opt != s["picks"].get(lv):
                    t = _copy(s)
                    t["picks"][lv] = opt
                    out.append(t)
        for i, st_ in enumerate(s["styles"]):
            for c in self.style_classes:
                for alt in STYLES[c]:
                    if alt != st_:
                        t = _copy(s)
                        t["styles"][i] = alt
                        out.append(t)
        for c in self.cantrips:
            if c != s["cantrip"]:
                t = _copy(s)
                t["cantrip"] = c
                out.append(t)
        return [t for t in out if self.valid(t)]

    def pick_options(self):
        opts = [("asi", ((a, 2),)) for a in ABILS]
        opts += [("asi", tuple(sorted(((a, 1), (b, 1))))) for a, b in itertools.combinations(ABILS, 2)]
        mode = self.plan.get("mode", "melee")
        for f, half in FEATS.items():
            if f in ("Spell Sniper", "War Caster") and not self.casting:
                continue
            if f == "Great Weapon Master" and mode != "melee":
                continue
            if f == "Sharpshooter" and mode != "ranged":
                continue
            if f == "Tavern Brawler" and mode not in ("throw", "melee"):
                continue
            for a in (half or (None,)):
                opts.append(("feat", f, a))
        for p in self.picks0.values():            # the plan's own feats stay possible
            if p and p not in opts:
                opts.append(p)
        return opts


def _copy(s):
    return dict(pb=dict(s["pb"]), r2=s["r2"], r1=s["r1"], picks=dict(s["picks"]), styles=list(s["styles"]),
                cantrip=s["cantrip"])


def tune(W, cid, bid, act, loadout, switches=None, max_evals=MAX_EVALS):
    """-> dict(untuned score, tuned score, respec (None = the plan is best), changes, evals)."""
    level = model.odata.ACT_LEVEL[act]
    sp = Space(W, cid, bid)
    base_score = model.score(W, cid, bid, act, loadout, switches).score
    out = dict(untuned=base_score, tuned=base_score, respec=None, state=None, evals=1, space=sp, note="")
    s = sp.initial()
    if s is None:
        out["note"] = "planned abilities do not decompose into a 27-point buy + racial bonus: kept as planned"
        return out
    cache = {}

    def val(st):
        r = sp.respec(st)
        if r["key"] not in cache:
            cache[r["key"]] = model.score(W, cid, bid, act, loadout, switches, respec=r).score
        return cache[r["key"]]
    cur = val(s)
    best_s, best_v = s, cur
    improved = True
    while improved and len(cache) < max_evals:
        improved = False
        for t in sp.neighbours(best_s, level):
            v = val(t)
            if v > best_v + 1e-6:
                best_s, best_v = t, v
                improved = True
            if len(cache) >= max_evals:
                break
    out["evals"] = len(cache)
    if best_v > base_score + 1e-6:
        out.update(tuned=best_v, respec=sp.respec(best_s), state=best_s)
    return out


def pick_list(sp, state, level):
    """Exact per-level pick list for a respec: level 0 = point buy + racial bonus, then every character level's
    class and picks (all 12 levels; the set is tested at `level`) - the Builds.lua picks with the tuned feat / ASI,
    fighting-style and cantrip picks in their place."""
    BI = sp.BI
    ba = sp.W.D.ba.get(sp.bid) or {}
    planned = [list(p) for _c, p in ba.get("levels") or []]
    s = state or sp.initial()
    out = []
    if s:
        out.append({"level": 0, "class": None, "picks": [f"Point buy {s['pb'][k]} {k}" for k in ABILS] +
                    [f"Racial +2 {s['r2']}", f"Racial +1 {s['r1']}"]})
    style_i = 0
    cnt = {}
    for i, c in enumerate(sp.seq):
        lv = i + 1
        cnt[c] = cnt.get(c, 0) + 1
        picks = [p for p in (planned[i] if i < len(planned) else [])
                 if not p.startswith("Feat:") and not p.startswith("Fighting Style") and not p.startswith("Cantrip")]
        if STYLE_CLASSES.get(c) == cnt[c] and s and style_i < len(s["styles"]):
            picks.append("Fighting Style: " + s["styles"][style_i])
            style_i += 1
        if s and lv in s["picks"] and s["picks"][lv]:
            p = s["picks"][lv]
            if p[0] == "asi":
                picks.append("Feat: Ability Improvement " + " ".join(f"+{v} {k}" for k, v in p[1]))
            else:
                picks.append(f"Feat: {p[1]}" + (f" (+1 {p[2]})" if p[2] else ""))
        if s and s.get("cantrip") and cnt[c] == 1 and any(s["cantrip"] in CANTRIPS.get(c, ()) for _ in [0]):
            picks.append("Cantrip: " + s["cantrip"])
        out.append({"level": lv, "class": c, "class_level": cnt[c], "picks": picks})
    del BI
    return out
