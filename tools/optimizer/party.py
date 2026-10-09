"""Party-level assignment of contested unique items.

Each optimized set is searched for one character alone, so the same unique item (one copy in the game) can turn up
in several characters' sets of the same act. Per act and ownership variant this module decides who keeps it:

  party value  = sum over characters of the mean model score of that character's builds (the player runs one build
                 per character; every origin counts, as any of them can be in the party of four)
  value(c, K)  = character c keeps the contested items K it asked for and loses the rest; each build that used a
                 lost item is repaired: coordinate descent over the full candidate lists of the slots that lost an
                 item picks the next-best items, never one another character holds, then the sets'
                 keep-it-if-owned rule (other slots stay as optimized: a full re-search per valuation is ~30x
                 slower and the solver needs hundreds of valuations per act)
  assignment   = each contested item goes to exactly one of the characters whose sets use it, maximising the party
                 value. Characters linked by shared items form a component, solved on its own:
                 - exact enumeration of every assignment when the component needs at most EXACT_BUDGET valuations
                   (sum over its characters of 2^items asked for);
                 - otherwise greedy by marginal value (each item to the character that loses the most without it)
                   followed by local search: move one item to another claimant, or swap two items between two
                   characters, best improvement first, until no move raises the party value.
  repair rounds = two repaired sets may pick the same unique item that nobody used before; such items join the
                 contested pool and the act is solved again (at most ROUNDS times).

Ownership variants: "party" keeps the owner rulings (an owned item is never contested: the search already blocks
it for everyone else); "free" (the owner gives it up) puts owned items in the pool like any other.
"""
import itertools

EXACT_BUDGET = 48
ROUNDS = 4


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


def _local(chars, items, claims, value):
    wants = {c: frozenset(i for i in items if c in claims[i]) for c in chars}
    a = {}
    for i in items:                                  # greedy: the claimant that loses the most without it
        a[i] = max(claims[i], key=lambda c: (value(c, wants[c]) - value(c, wants[c] - {i}), c))
    cur = total(a, chars, value)
    while True:
        moves = []
        for i in items:
            moves += [{i: c} for c in claims[i] if c != a[i]]
        for i, j in itertools.combinations(items, 2):
            if a[i] != a[j] and a[j] in claims[i] and a[i] in claims[j]:
                moves.append({i: a[j], j: a[i]})
        best, best_v = None, cur
        for m in moves:
            v = total(dict(a, **m), chars, value)
            if v > best_v + 1e-9:
                best, best_v = m, v
        if best is None:
            return a
        a.update(best)
        cur = best_v


def solve(claims, value, exact_budget=EXACT_BUDGET):
    """claims {item: [characters whose sets use it]} (two or more each); value(char, frozenset kept) -> float.
    -> {"assign": {item: char}, "total": party value of the components, "methods": {"exact": n, "local": n}}"""
    assign, methods = {}, {"exact": 0, "local": 0}
    for chars, items in components(claims):
        need = sum(2 ** sum(1 for i in items if c in claims[i]) for c in chars)
        if need <= exact_budget:
            assign.update(_exact(chars, items, claims, value))
            methods["exact"] += 1
        else:
            assign.update(_local(chars, items, claims, value))
            methods["local"] += 1
    chars = sorted({c for cs in claims.values() for c in cs})
    return {"assign": assign, "total": total(assign, chars, value), "methods": methods}


# ============================================================================================ optimizer side
def is_unique(W, sid):
    return bool(W.items[sid].get("unique"))


def uniques(W, lo):
    return {s for s in lo.values() if is_unique(W, s)}


class Act:
    """Valuations of one act and ownership variant. objs = {(cid, bid): optimize() result} of that act."""

    def __init__(self, W, objs, finish):
        self.W, self.objs, self.finish = W, objs, finish
        self.chars = sorted({c for c, _b in objs})
        self.builds = {c: sorted(b for cc, b in objs if cc == c) for c in self.chars}
        self.base = {k: o["S"].score(o["loadout"]).score for k, o in objs.items()}
        self.held = {c: set().union(*(uniques(W, objs[(c, b)]["loadout"]) for b in self.builds[c]))
                     for c in self.chars}
        self.cache = {}
        self.pool = set()

    def repaired(self, cid, bid, deny):
        """(loadout, score) of the build without the denied items."""
        o = self.objs[(cid, bid)]
        deny = frozenset(deny)
        if not deny & set(o["loadout"].values()):
            return o["loadout"], self.base[(cid, bid)]
        key = (cid, bid, deny)
        if key not in self.cache:
            import search                # the solver above stays importable without the game data
            S = search.Searcher(self.W, cid, bid, o["act"], o["switches"], ownership=o["ownership"], deny=deny)
            start = {k: v for k, v in o["loadout"].items() if v not in deny}
            lo, _r = S.descend(start, [k for k in search.ORDER if k in o["loadout"] and k not in start])
            lo, _owned = self.finish(self.W, S, lo)
            self.cache[key] = (lo, S.score(lo).score)
        return self.cache[key]

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
    extra, rounds = {}, 0
    while True:
        rounds += 1
        claims = A.claims(extra)
        A.pool = set(claims)
        res = solve(claims, A.value, exact_budget)
        los = A.loadouts(res["assign"])
        by = {}
        for (c, _b), lo in los.items():
            for s in uniques(W, lo):
                by.setdefault(s, set()).add(c)
        new = {s: cs for s, cs in by.items() if len(cs) > 1}
        if not new or rounds >= ROUNDS:
            break
        for s, cs in new.items():
            extra.setdefault(s, set()).update(cs)
    builds = []
    for (c, b), lo in sorted(los.items()):
        o = objs[(c, b)]
        before = A.base[(c, b)]
        after = A.repaired(c, b, A.deny(c, {i for i, w in res["assign"].items() if w == c}))[1]
        changed = [(s, o["loadout"].get(s), lo.get(s)) for s in search.ORDER if o["loadout"].get(s) != lo.get(s)]
        builds.append({"char": c, "build": b, "score_before": round(before, 2), "score_after": round(after, 2),
                       "delta": round(after / before - 1, 4) if before else 0.0,
                       "lost": sorted(s for s in uniques(W, o["loadout"]) if s in claims and res["assign"][s] != c),
                       "changed": changed, "loadout": lo})
    return {"claims": claims, "assign": res["assign"], "total": round(res["total"], 2),
            "total_before": round(sum(sum(A.base[(c, b)] for b in A.builds[c]) / len(A.builds[c])
                                      for c in A.chars), 2),
            "methods": res["methods"], "rounds": rounds, "unresolved": sorted(new), "builds": builds,
            "valuations": len(A.cache)}
