"""Party-level assignment of contested unique items.

Each optimized set is searched for one character alone, so the same unique item (one copy in the game) can turn up
in several characters' sets of the same act. Per act and ownership variant this module decides who keeps it:

  party value  = sum over characters of the mean model score of that character's builds (the player runs one build
                 per character; every origin counts, as any of them can be in the party of four)
  value(c, K)  = character c keeps the contested items K it asked for and loses the rest; each build that used a
                 lost item is repaired: coordinate descent over the slots that lost an item picks the next-best
                 items, never one another character holds, then the sets' keep-it-if-owned rule (other slots stay
                 as optimized: a full re-search per valuation is ~30x slower and the solver needs hundreds of
                 valuations per act). A repair tries each lost slot's best REPAIR_KEEP items the character may
                 still use, ranked once per build by the optimized loadout's score with that slot swapped: the full
                 lists made the Act 3 "free" solve (23 contested items) the long pole of the whole run
  assignment   = each contested item goes to exactly one of the characters whose sets use it, maximising the party
                 value. Characters linked by shared items form a component, solved on its own:
                 - exact enumeration of every assignment when the component needs at most EXACT_BUDGET valuations
                   (sum over its characters of 2^items asked for);
                 - otherwise greedy by marginal value (each item to the character that loses the most without it)
                   followed by local search: move one item to another claimant, or (when no move helps) swap two
                   items between two characters, taking the first that raises the party value, until none does.
  owner rule   = the character the set builder's owner rule names (data/scores/owners.json when its owner is a
                 claimant, else the same rule over the claimants' optimized sets: the build the character plays
                 first, then the game-data fit of the item in its slot, then the finer numeric tie model)
  10% rule     = the solver may move an item away from that owner only when it is clearly better elsewhere:
                   gain(c)  = value(c, kept + item) - value(c, kept - item), every other item as assigned
                   margin   = (gain(solver's pick) - gain(owner)) / gain(owner)
                 margin < THRESHOLD puts the item back with the owner (kept_by_threshold), fixes it there and solves
                 the rest again, so the other characters get their next-best arrangement. An owner that gains
                 nothing from the item loses it to any pick that gains something
  repair rounds = two repaired sets may pick the same unique item that nobody used before; such items join the
                 contested pool and the act is solved again from the last assignment (at most ROUNDS times; items
                 still shared after that are settled by a last pass, listed as settled_last).

Ownership variants: "party" keeps the owner rulings (an owned item is never contested: the search already blocks
it for everyone else); "free" (the owner gives it up) puts owned items in the pool like any other.
"""
import itertools
import math

EXACT_BUDGET = 48
ROUNDS = 4
REPAIR_KEEP = 8            # vs the full lists: same party totals in Act 3 party and Act 2 free, -0.6% in Act 3 free
THRESHOLD = 0.10           # the 10% rule: smallest margin that moves an item away from its owner


# ============================================================================================ solver (pure)
def components(claims):
    """claims {item: [chars]} -> [(sorted chars, sorted items)] linked by shared characters."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for item, chars in claims.items():
        for c in chars:
            parent[find(("c", c))] = find(("i", item))
    groups = {}
    for item, chars in claims.items():
        g = groups.setdefault(find(("i", item)), (set(), set()))
        g[1].add(item)
        g[0].update(chars)
    return [(sorted(cs), sorted(its)) for cs, its in groups.values()]


def _kept(assign, chars):
    out = {c: set() for c in chars}
    for item, c in assign.items():
        out[c].add(item)
    return {c: frozenset(v) for c, v in out.items()}


def total(assign, chars, value):
    return sum(value(c, k) for c, k in _kept(assign, chars).items())


def _exact(chars, items, claims, value):
    best, best_v = None, None
    for pick in itertools.product(*(claims[i] for i in items)):
        a = dict(zip(items, pick))
        v = total(a, chars, value)
        if best_v is None or v > best_v + 1e-9:
            best, best_v = a, v
    return best


def _local(chars, items, claims, value, start=None):
    wants = {c: frozenset(i for i in items if c in claims[i]) for c in chars}
    a = {}
    for i in items:
        if start and start.get(i) in claims[i]:
            a[i] = start[i]                          # the previous round's choice (repair rounds)
        else:                                        # greedy: the claimant that loses the most without it
            a[i] = max(claims[i], key=lambda c: (value(c, wants[c]) - value(c, wants[c] - {i}), c))
    cur = total(a, chars, value)
    while True:
        # single moves first; swaps only once no single move helps (each swap values two new kept sets, and
        # checking every swap after every step made the 23-item Act 3 solve value thousands of kept sets)
        best = None
        for kind in ("move", "swap"):
            moves = []
            if kind == "move":
                for i in items:
                    moves += [{i: c} for c in claims[i] if c != a[i]]
            else:
                for i, j in itertools.combinations(items, 2):
                    if a[i] != a[j] and a[j] in claims[i] and a[i] in claims[j]:
                        moves.append({i: a[j], j: a[i]})
            best_v = cur
            for m in moves:
                v = total(dict(a, **m), chars, value)
                if v > best_v + 1e-9:
                    best, best_v = m, v
                    break
            if best is not None:
                break
        if best is None:
            return a
        a.update(best)
        cur = best_v


def solve(claims, value, exact_budget=EXACT_BUDGET, start=None):
    """claims {item: [characters whose sets use it]} (two or more each); value(char, frozenset kept) -> float;
    start = an earlier assignment the local search begins from (items it does not cover start greedy).
    -> {"assign": {item: char}, "total": party value of the components, "methods": {"exact": n, "local": n}}"""
    assign, methods = {}, {"exact": 0, "local": 0}
    for chars, items in components(claims):
        need = sum(2 ** sum(1 for i in items if c in claims[i]) for c in chars)
        if need <= exact_budget:
            assign.update(_exact(chars, items, claims, value))
            methods["exact"] += 1
        else:
            assign.update(_local(chars, items, claims, value, start))
            methods["local"] += 1
    chars = sorted({c for cs in claims.values() for c in cs})
    return {"assign": assign, "total": total(assign, chars, value), "methods": methods}


def margin(assign, chars, value, item, owner):
    """-> (gain of the solver's pick, gain of the owner, margin) of one item under the 10% rule; the margin is
    math.inf when the owner gains nothing and the pick gains something."""
    kept = _kept(assign, chars)
    pick = assign[item]
    g_pick = value(pick, kept[pick] | {item}) - value(pick, kept[pick] - {item})
    g_own = value(owner, kept[owner] | {item}) - value(owner, kept[owner] - {item})
    if g_own > 1e-9:
        return g_pick, g_own, (g_pick - g_own) / g_own
    return g_pick, g_own, (math.inf if g_pick > 1e-9 else 0.0)


def solve_rule(claims, value, owner, threshold=None, exact_budget=EXACT_BUDGET, start=None, fixed=None):
    """solve() under the 10% rule. owner = {item: character the owner rule names} (items without one are not
    checked); fixed = {item: record} kept by the rule in an earlier repair round.
    -> solve()'s dict + "kept_by_threshold" and "moved": {item: {"owner", "pick", "gain_owner", "gain_pick",
    "margin"}} (moved = the solver's pick differs from the owner and the margin reaches the threshold)."""
    threshold = THRESHOLD if threshold is None else threshold
    fixed = dict(fixed or {})
    chars = sorted({c for cs in claims.values() for c in cs})
    while True:
        res = solve({i: ([fixed[i]["owner"]] if i in fixed else cs) for i, cs in claims.items()}, value,
                    exact_budget, start)
        a = res["assign"]
        moved, new = {}, {}
        for i in sorted(a):
            o = owner.get(i)
            if i in fixed or o is None or o not in claims[i] or a[i] == o:
                continue
            g_pick, g_own, m = margin(a, chars, value, i, o)
            rec = {"owner": o, "pick": a[i], "gain_owner": g_own, "gain_pick": g_pick, "margin": m}
            (moved if m >= threshold else new)[i] = rec
        if not new:
            res.update(total=total(a, chars, value), kept_by_threshold=fixed, moved=moved)
            return res
        fixed.update(new)
        start = a


# ============================================================================================ optimizer side
def is_unique(W, sid):
    return bool(W.items[sid].get("unique"))


def uniques(W, lo):
    return {s for s in lo.values() if is_unique(W, s)}


def search_order():
    import search                        # the solver above stays importable without the game data
    return search.ORDER


class Act:
    """Valuations of one act and ownership variant. objs = {(cid, bid): {"loadout", "act", "switches",
    "ownership"}} of that act (an optimize() result or the same fields read back from a job file)."""

    def __init__(self, W, objs, finish):
        self.W, self.objs, self.finish = W, objs, finish
        self.chars = sorted({c for c, _b in objs})
        self.builds = {c: sorted(b for cc, b in objs if cc == c) for c in self.chars}
        self.searchers = {}
        self.base = {k: self.searcher(*k).score(o["loadout"]).score for k, o in objs.items()}
        self.held = {c: set().union(*(uniques(W, objs[(c, b)]["loadout"]) for b in self.builds[c]))
                     for c in self.chars}
        self.cache = {}
        self.reads = {}
        self.rank = {}
        self.pool = set()
        self.owners = {}

    def owner_rule(self, sid, places):
        """places = {char: {(build, slot)}} where the claimants' sets hold the item. -> (owner or None, basis), worked
        out once per item: the set builder's owner (owners.json) when it is a claimant, else its rule over these
        sets (the build the character plays first, then the game-data fit in that slot rounded as owners.json
        rounds it, read from the build's scored list or computed for items the list leaves out, then the numeric
        tie model, then the set builder's character order)."""
        if sid in self.owners:
            return self.owners[sid]
        import odata
        SI, BP = odata.SI, odata.BP
        for g in self.W.owners.values():
            if g.get("kind") == "unique" and sid in g["items"] and g["owners"] and g["owners"][0] in places:
                self.owners[sid] = (g["owners"][0], "owners.json")
                return self.owners[sid]
        rec = self.W.items[sid]
        best = {}
        for c, where in sorted(places.items()):
            first = SI.primary_build(c, BP.CHARACTERS[c], self.W.ba_origins)
            for b, slot in sorted(where):
                key_slot = "Ring1" if slot == "Ring2" else slot
                stored = (self.W.build_entry(c, b)["items"].get(sid) or {}).get("slots", {}).get(key_slot)
                fit, comps = ((stored["fit"], stored["components"]) if stored
                              else self.W.scorer(c, b).score(rec, key_slot))
                k = (b == first, round(fit, 2))
                if c not in best or k > best[c][0]:
                    best[c] = (k, b, key_slot, comps)
        top_k = max(v[0] for v in best.values())
        top = {c: v for c, v in best.items() if v[0] == top_k}
        if len(top) == 1:
            self.owners[sid] = (next(iter(top)), "fit")
            return self.owners[sid]
        order = list(BP.CHARACTERS)
        nv = sorted(((-SI.numeric_value(b, rec, sl, comps), order.index(c), c) for c, (_k, b, sl, comps) in top.items()))
        # an exact tie goes to the first character in the set builder's character order, as owners.json does
        tie = nv[1][0] - nv[0][0] < 1e-6
        self.owners[sid] = (nv[0][2], "exact tie, character order" if tie else "fit tie, numeric")
        return self.owners[sid]

    def searcher(self, cid, bid):
        """One searcher per build: every repair shares its score cache (repairs revisit the same loadouts)."""
        if (cid, bid) not in self.searchers:
            import search
            o = self.objs[(cid, bid)]
            self.searchers[(cid, bid)] = search.Searcher(self.W, cid, bid, o["act"], o["switches"],
                                                         ownership=o["ownership"])
        return self.searchers[(cid, bid)]

    def repaired(self, cid, bid, deny):
        """(loadout, score) of the build without the denied items. The repair only reads the candidate lists of
        the slots that lost an item and of the slots holding a keep-it-if-owned item (the finish rule), so only
        denied items in those lists can change it: the cache key keeps just those, and valuations that differ
        elsewhere (another build's items, items new to the pool in a later round) share one repair."""
        o = self.objs[(cid, bid)]
        lo0 = o["loadout"]
        lost = [k for k in search_order() if k in lo0 and lo0[k] in deny]
        if not lost:
            return lo0, self.base[(cid, bid)]
        S0 = self.searcher(cid, bid)
        read = frozenset(lost) | frozenset(k for k, v in lo0.items() if self.W.obtainable(v, o["act"]) == "owned")
        if (cid, bid, read) not in self.reads:
            self.reads[(cid, bid, read)] = frozenset().union(*(S0.cands[k] for k in read), lo0.values())
        deny = frozenset(deny) & self.reads[(cid, bid, read)]
        key = (cid, bid, deny)
        if key not in self.cache:
            S = S0.without(deny)
            S.cands.update({k: [c for c in self.ranked(cid, bid, k) if c not in deny][:REPAIR_KEEP] for k in lost})
            start = {k: v for k, v in lo0.items() if k not in lost}
            lo, _r = S.descend(start, lost)
            # the keep-it-if-owned rule compares with the best current items: the top REPAIR_KEEP of those
            act = o["act"]
            F = S0.without(deny)
            F.cands.update({k: [c for c in self.ranked(cid, bid, k) if c not in deny and
                                self.W.obtainable(c, act) == "now"][:REPAIR_KEEP] for k in read})
            lo, _owned = self.finish(self.W, F, lo)
            self.cache[key] = (lo, S.score(lo).score)
        return self.cache[key]

    def ranked(self, cid, bid, slot):
        """The slot's candidates, best first by the score of the optimized loadout with that slot swapped (items
        that clash with it dropped, as the search's pruning does)."""
        if (cid, bid, slot) not in self.rank:
            import search
            S0, lo0 = self.searcher(cid, bid), self.objs[(cid, bid)]["loadout"]
            scored = []
            for i, sid in enumerate(S0.cands[slot]):
                t = dict(lo0)
                t[slot] = sid
                if not search.legal(self.W, slot, sid, lo0):
                    t = search.drop_illegal(self.W, t)
                if t.get(slot) == sid:
                    scored.append((-S0.score(t).score, i, sid))
            self.rank[(cid, bid, slot)] = [sid for _v, _i, sid in sorted(scored)]
        return self.rank[(cid, bid, slot)]

    def deny(self, cid, kept):
        """Items this character may not use: contested items it did not get + unique items others hold."""
        others = set().union(*(self.held[c] for c in self.chars if c != cid))
        return frozenset((self.pool | others) - set(kept))

    def value(self, cid, kept):
        d = self.deny(cid, kept)
        return sum(self.repaired(cid, b, d)[1] for b in self.builds[cid]) / len(self.builds[cid])

    def loadouts(self, assign):
        kept = {c: {i for i, w in assign.items() if w == c} for c in self.chars}
        return {(c, b): self.repaired(c, b, self.deny(c, kept[c]))[0] for c in self.chars for b in self.builds[c]}

    def claims(self, extra=None):
        by = {}
        for (c, _b), o in self.objs.items():
            for s in uniques(self.W, o["loadout"]):
                by.setdefault(s, set()).add(c)
        for s, cs in (extra or {}).items():
            by.setdefault(s, set()).update(cs)
        return {s: sorted(cs) for s, cs in by.items() if len(cs) > 1}


def resolve(W, objs, finish, exact_budget=EXACT_BUDGET):
    """Assign every contested unique item of one act. -> dict with the assignment, rounds, methods, and per build
    the score before / after and the slots that changed."""
    import search
    A = Act(W, objs, finish)
    places = {}

    def note(los):
        for (c, b), lo in los.items():
            for slot, s in lo.items():
                if is_unique(W, s):
                    places.setdefault(s, {}).setdefault(c, set()).add((b, slot))

    note({k: o["loadout"] for k, o in objs.items()})
    extra, rounds, res, fixed = {}, 0, {"assign": None}, {}
    while True:
        rounds += 1
        claims = A.claims(extra)
        A.pool = set(claims)
        owner = {s: A.owner_rule(s, {c: places[s][c] for c in claims[s]})[0] for s in claims}
        res = solve_rule(claims, A.value, owner, exact_budget=exact_budget, start=res["assign"], fixed=fixed)
        fixed = res["kept_by_threshold"]
        los = A.loadouts(res["assign"])
        note(los)
        by = {}
        for (c, _b), lo in los.items():
            for s in uniques(W, lo):
                by.setdefault(s, set()).add(c)
        new = {s: cs for s, cs in by.items() if len(cs) > 1}
        if not new or rounds >= ROUNDS:
            break
        for s, cs in new.items():
            extra.setdefault(s, set()).update(cs)
    kept = {c: {i for i, w in res["assign"].items() if w == c} for c in A.chars}
    final = {}
    for c in A.chars:
        d = A.deny(c, kept[c])
        if new:
            # rounds used up and two repaired sets still share an item: each character in turn also gives up every
            # unique item another character's current set holds, so no item ends up twice
            cur = {k: (final[k][0] if k in final else lo) for k, lo in los.items()}
            d |= set().union(*(uniques(W, lo) for (cc, _b), lo in cur.items() if cc != c)) - kept[c]
        for b in A.builds[c]:
            final[(c, b)] = A.repaired(c, b, d)
    builds = []
    for (c, b), (lo, after) in sorted(final.items()):
        o = objs[(c, b)]
        before = A.base[(c, b)]
        changed = [(s, o["loadout"].get(s), lo.get(s)) for s in search.ORDER if o["loadout"].get(s) != lo.get(s)]
        builds.append({"char": c, "build": b, "score_before": round(before, 2), "score_after": round(after, 2),
                       "delta": round(after / before - 1, 4) if before else 0.0,
                       "lost": sorted(s for s in uniques(W, o["loadout"]) if (s in claims and res["assign"][s] != c)
                                      or (s in new and s not in lo.values())),
                       "changed": changed, "loadout": lo})
    tot = sum(sum(final[(c, b)][1] for b in A.builds[c]) / len(A.builds[c]) for c in A.chars)
    def rule_rec(r):
        both = r["gain_owner"] > 1e-9 and r["gain_pick"] > 1e-9
        return {"owner": r["owner"], "pick": r["pick"], "gain_owner": round(r["gain_owner"], 3),
                "gain_pick": round(r["gain_pick"], 3), "close": both,
                "margin": None if math.isinf(r["margin"]) else round(r["margin"], 4)}

    return {"claims": claims, "assign": res["assign"], "total": round(tot, 2),
            "owner_rule": {s: list(A.owners[s]) for s in sorted(claims)}, "threshold": THRESHOLD,
            "kept_by_threshold": {s: rule_rec(r) for s, r in sorted(res["kept_by_threshold"].items())},
            "moved": {s: rule_rec(r) for s, r in sorted(res["moved"].items())},
            "total_before": round(sum(sum(A.base[(c, b)] for b in A.builds[c]) / len(A.builds[c])
                                      for c in A.chars), 2),
            "methods": res["methods"], "rounds": rounds, "settled_last": sorted(new), "builds": builds,
            "valuations": len(A.cache), "evals": sum(len(S.cache) for S in A.searchers.values())}
