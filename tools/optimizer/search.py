"""Loadout search: per-slot candidates (game-data legal), slot-wise beam search, then coordinate descent until
no single-slot change improves the score.

Legality (same rules as the set builder, tools/score_items.py):
  - usable: proficiency (game progression data), build avoid rules, heavy body armour never for a raging build
    (Scorer.usable);
  - slot_ok: two-handed / Duellist mains keep the off hand empty, dual wielding needs two Light weapons, an off-hand
    hand crossbow needs a hand-crossbow main, "no armour / no shield" items, story-path exclusions
    (conditions.md families via score_items.path_conflict);
  - acts: only items obtainable by this act (earlier-act-only items count as "keep it if you have it");
  - never items that cost an origin companion (costs:<char>), never Dark-Urge-only items for other characters,
    nothing tagged unobtainable; one copy of a unique item;
  - party ownership (OWNERSHIP): "party" = a unique item (or a scarce-material item) whose party owner is another
    character is not available (owners.json); "free" = the owner gives it up (every item available).
"""
import odata
import model

SI = odata.SI
ORDER = ["MainHand", "OffHand", "Ranged", "RangedOff", "Breast", "Gloves", "Helmet", "Amulet", "Ring1", "Ring2",
         "Cloak", "Boots", "Elixir"]


OWNERSHIP = ("party", "free")


def allowed(W, cid, bid, sid, scorer, ownership="party"):
    u = W.universe.get(sid)
    if not u:
        return False, "no source"
    if ownership == "party":
        own = W.blocked(sid, cid)
        if own:
            return False, "party owner: " + ", ".join(own)
    cond = set(u["cond"])
    if any(c.startswith("costs:") for c in cond) or "unobtainable" in cond:
        return False, "costs a companion / unobtainable"
    if "durge" in cond and cid != "darkurge":
        return False, "Dark Urge campaigns only"
    ok, why = scorer.usable(W.items[sid])
    return ok, why


def candidates(W, cid, bid, act, ownership="party", deny=()):
    """{slot: [sid, ...]} every legal, obtainable item per slot for this build and act, minus `deny` (unique items
    the party gave to other characters)."""
    scorer = W.scorer(cid, bid)
    plan = model.PLANS.get(bid, {})
    prof = W.build_entry(cid, bid).get("profile") or {}
    out = {s: [] for s in ORDER}
    for sid, u in W.universe.items():
        if sid in deny or not W.obtainable(sid, act):
            continue
        ok, why = allowed(W, cid, bid, sid, scorer, ownership)
        if not ok:
            continue
        rec = W.items[sid]
        for s in u["slots"]:
            if s == "RangedOff" and plan.get("offhand") != "ranged":
                continue
            if s == "OffHand" and rec.get("weapon") and prof.get("offhand") not in ("dual", "any"):
                continue
            if s == "OffHand" and rec.get("weapon") and "Light" not in ((rec.get("weapon") or {}).get("properties")
                                                                           or []):
                continue
            if s == "MainHand" and rec.get("weapon") and "not proficient" in why:
                continue                     # a main-hand weapon the build cannot attack with
            out[s].append(sid)
    return out


def ranged_off_ok(W, slot, sid):
    """The off-hand ranged slot only takes a hand crossbow (slot_ok only checks the main-hand side - found by the
    optimizer: it put a longbow there)."""
    if slot != "RangedOff":
        return True
    modes, _p, _r = SI.weapon_modes(W.items[sid])
    return "handxbow" in modes


def legal(W, slot, sid, loadout):
    if not ranged_off_ok(W, slot, sid):
        return False
    chosen = {k: {"sid": v} for k, v in loadout.items() if v and k != slot}
    if sid in chosen.values() or any(v["sid"] == sid for v in chosen.values()):
        if W.items[sid].get("unique", True):
            return False
    try:
        return SI.slot_ok(sid, slot, chosen, W.items)
    except KeyError:
        return False


def drop_illegal(W, loadout):
    """Remove items that clash with the rest (keep the earlier slot in ORDER)."""
    out = {}
    for s in ORDER:
        sid = loadout.get(s)
        if sid and legal(W, s, sid, out):
            out[s] = sid
    return out


class Searcher:
    def __init__(self, W, cid, bid, act, switches=None, beam=8, keep=14, log=None, ownership="party", deny=()):
        self.W, self.cid, self.bid, self.act = W, cid, bid, act
        self.sw = switches or {}
        self.beam, self.keep = beam, keep
        self.ownership = ownership
        self.cands = candidates(W, cid, bid, act, ownership, deny)
        self.cache = {}
        self.evals = 0
        self.log = log

    def score(self, lo):
        key = tuple(sorted((k, v) for k, v in lo.items() if v))
        r = self.cache.get(key)
        if r is None:
            r = model.score(self.W, self.cid, self.bid, self.act, dict(key), self.sw)
            self.cache[key] = r
            self.evals += 1
        return r

    def prune(self, base):
        """Top `keep` items per slot by their gain on top of `base` (the slot swapped, everything else kept)."""
        out = {}
        for s in ORDER:
            scored = []
            for sid in self.cands[s]:
                lo = dict(base)
                lo[s] = sid
                lo = drop_illegal(self.W, lo) if not legal(self.W, s, sid, base) else lo
                if lo.get(s) != sid:
                    continue
                scored.append((self.score(lo).score, sid))
            scored.sort(reverse=True)
            out[s] = [sid for _v, sid in scored[: self.keep]]
        return out

    def run(self, starts):
        """starts = loadouts to seed from (research sets, the empty loadout). -> (best loadout, Result)."""
        base = max((drop_illegal(self.W, s) for s in starts), key=lambda lo: self.score(lo).score)
        short = self.prune(base)
        # beam over slots: each state is a full loadout (unfilled slots keep the seed's item)
        beam = [base] + [drop_illegal(self.W, s) for s in starts]
        for s in ORDER:
            nxt = list(beam)
            for lo in beam:
                for sid in short[s] + [None]:
                    t = dict(lo)
                    if sid is None:
                        t.pop(s, None)
                    else:
                        if not legal(self.W, s, sid, {k: v for k, v in lo.items() if k != s}):
                            continue
                        t[s] = sid
                    nxt.append(t)
            uniq = {}
            for lo in nxt:
                uniq[tuple(sorted(lo.items()))] = lo
            beam = sorted(uniq.values(), key=lambda lo: -self.score(lo).score)[: self.beam]
        return self.descend(beam[0])

    def descend(self, best, slots=ORDER):
        """Coordinate descent with the FULL candidate lists (finds items the pruning dropped) over `slots` until no
        single-slot change improves the score. -> (loadout, Result)"""
        for _pass in range(4):
            improved = False
            for s in slots:
                cur = self.score(best).score
                pick = None
                for sid in self.cands[s] + [None]:
                    if sid == best.get(s):
                        continue
                    t = dict(best)
                    if sid is None:
                        t.pop(s, None)
                    else:
                        if not legal(self.W, s, sid, {k: v for k, v in best.items() if k != s}):
                            continue
                        t[s] = sid
                    v = self.score(t).score
                    if v > cur + 1e-6:
                        cur, pick = v, (sid, t)
                if pick:
                    best = pick[1]
                    improved = True
            if not improved:
                break
        return best, self.score(best)
