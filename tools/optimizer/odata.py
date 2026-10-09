"""Optimizer data layer: every equippable item from the game data with the act window, story conditions and
proficiency rules the set builder uses, plus the scored builds (read-only).

Sources (read-only):
  data/items_all/*.jsonl            every item (stats, boosts, passives, sources)
  data/cache/stats_resolved.json    passives / statuses / spells (game stats with inheritance resolved)
  data/scores/<char>.json           builds (class levels, feats, styles, proficiencies, profile), research sets,
                                    item_info (act window + story conditions of every recommended item)
  data/scores/owners.json           unique-item party owners
  data/research/conditions.md       story-path families, act overrides, traders lost on a path
  Builds.lua (BuildAdvisor)         BA.Origins (which builds are each origin's first two)

The item pool is the WHOLE game (not only the scorer's recommended items) so the optimizer can find items the
research never mentions. Items the scorer already knows keep the scorer's act window and conditions (research
verdicts included); other items get them from their game-data sources with the scorer's own rules
(score_items.reliable / item_conditions) - only items with a reliable game source are used.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
LA = os.path.dirname(TOOLS)
for p in (TOOLS, os.path.join(TOOLS, "sets_artifact")):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_profiles as BP  # noqa: E402
import build_sets_artifact as BSA  # noqa: E402
import la_common as LC  # noqa: E402
import score_items as SI  # noqa: E402

DATA = os.path.join(LA, "data")
SCORES = os.path.join(DATA, "scores")
CHARS = ["astarion", "gale", "karlach", "laezel", "shadowheart", "wyll", "darkurge"]
SLOTS = ["MainHand", "OffHand", "Ranged", "RangedOff", "Helmet", "Cloak", "Breast", "Gloves", "Boots", "Amulet",
         "Ring1", "Ring2", "Elixir"]
ACT_LEVEL = dict(BSA.ACT_LEVEL)          # the level the sets / sheet use per act: {1: 5, 2: 8, 3: 12}


def item_slots(rec):
    """Equipment slots an item can go into (the scorer's candidate_slots, rings in both ring slots)."""
    s = rec.get("slot")
    if s == "Melee Main Weapon":
        return ["MainHand", "OffHand"]
    if s == "Ranged Main Weapon":
        return ["Ranged", "RangedOff"]
    if s == "Melee Offhand Weapon":
        return ["OffHand"]
    if s == "Ring":
        return ["Ring1", "Ring2"]
    if s in ("Helmet", "Cloak", "Breast", "Gloves", "Boots", "Amulet"):
        return [s]
    if s == "Consumable" and (rec.get("name") or "").startswith("Elixir"):
        return ["Elixir"]
    return []


class World:
    """Everything the optimizer reads, loaded once."""

    def __init__(self, scores_dir=SCORES, quiet=False):
        self.scores_dir = scores_dir
        self.items = LC.load_items()
        self.sources = LC.load_sources()
        self.levels = LC.load_levels()
        with open(os.path.join(DATA, "cache", "stats_resolved.json"), encoding="utf-8") as f:
            self.stats = json.load(f)
        self.scores = {}
        for cid in CHARS:
            p = os.path.join(scores_dir, cid + ".json")
            with open(p, encoding="utf-8") as f:
                self.scores[cid] = json.load(f)
        try:
            with open(os.path.join(scores_dir, "owners.json"), encoding="utf-8") as f:
                self.owners = json.load(f)
        except OSError:
            self.owners = {}
        self.item_info = {}
        for cid in CHARS:
            for sid, inf in self.scores[cid]["item_info"].items():
                self.item_info.setdefault(sid, inf)
        _gear, self.ba_origins = LC.load_builds_lua(BP.BUILDS_LUA)
        BP.sync_with_builds_lua()            # Builds.lua stats / feats into the profiles (raises on unknown builds)
        # the sheet engine of the Sets page (verified against the page; same rules as the in-game sheet)
        self.D = _SheetData(self.items, self.stats)
        self.cond_table = SI.load_condition_table(self.items)
        self.universe = self._universe()
        if not quiet:
            n_game = sum(1 for u in self.universe.values() if u["basis"] == "game data only")
            print(f"optimizer data: {len(self.items)} items, {len(self.universe)} equippable with a source "
                  f"({n_game} not in the scored lists), {len(self.scores)} characters")

    # ------------------------------------------------------------------ item pool
    def _universe(self):
        uni = {}
        for sid, rec in self.items.items():
            slots = item_slots(rec)
            if not slots:
                continue
            inf = self.item_info.get(sid)
            if inf:
                disp = (inf.get("display") or {}).get("acts") or "mmm"
                u = {"act": inf.get("act") or 1, "last_act": inf.get("last_act") or 3, "cond": list(inf.get("cond") or []),
                     "display": disp, "basis": "scored"}
            else:
                if rec.get("rarity") == "Common":
                    continue                       # plain gear: never a recommendation
                srcs = self.sources.get(sid, [])
                rel = [s for s in srcs if SI.reliable(s)]
                if not rel:
                    continue                       # random / unconfirmed loot only: not a set pick
                act = min(LC.source_act(s) for s in rel)
                last = max(LC.source_act(s) for s in rel)
                if sid in SI.ACT_OVERRIDE:
                    act, last = SI.ACT_OVERRIDE[sid][0], SI.ACT_OVERRIDE[sid][1]
                flags = set()
                for s in rel:
                    flags |= set(SI.source_flags(s))
                if all("Dark Urge story" in SI.source_flags(s) for s in rel):
                    flags.add("Dark Urge campaigns only")
                cond = SI.item_conditions(sid, srcs, flags, {}, self.cond_table)
                disp = SI.display_mode(rec, srcs, SI.ACT_OVERRIDE[sid][:2] if sid in SI.ACT_OVERRIDE else None)
                u = {"act": act, "last_act": max(act, last), "cond": cond, "display": disp["acts"],
                     "basis": "game data only", "sources": sorted(rel, key=lambda s: -SI.source_rank(s, act))[:3]}
            u["slots"] = slots
            uni[sid] = u
            SI.COND[sid] = sorted(u["cond"])
            SI.ACTS[sid] = (u["act"], u["last_act"])
        return uni

    def obtainable(self, sid, act):
        """-> None (not by this act), "now" (obtainable in this act) or "owned" (earlier act only: keep it if you
        have it - the sets' only-if-owned rule)."""
        u = self.universe.get(sid)
        if not u or "unobtainable" in u["cond"]:
            return None
        if u["act"] > act:
            return None
        if u["last_act"] >= act and (len(u["display"]) < act or u["display"][act - 1] != "-"):
            return "now"
        return "owned"

    # ------------------------------------------------------------------ builds
    def origin_builds(self, cid, n=2):
        return [b for b in self.ba_origins.get(cid, []) if b in self.scores[cid]["builds"]][:n]

    def build_entry(self, cid, bid):
        return self.scores[cid]["builds"][bid]

    def race(self, cid):
        return self.scores[cid].get("race") or BP.CHARACTERS[cid]["race"]

    def build_input(self, cid, bid):
        return BSA.build_input(self.D, cid, self.race(cid), bid, self.build_entry(cid, bid))

    def scorer(self, cid, bid):
        b = self.build_entry(cid, bid)
        return SI.Scorer(self.items, cid, BP.CHARACTERS[cid], bid, set(b.get("proficiencies") or []))

    def blocked(self, sid, cid):
        """-> the party owners when this unique item (or an item made from a scarce material) belongs to OTHER
        characters (data/scores/owners.json, the party-owner rule of the set builder), else None."""
        return SI.blocked_for(sid, cid, self.owners) if self.owners else None

    def research_sets(self, cid, bid, act):
        return list(((self.build_entry(cid, bid).get("sets") or {}).get(str(act))) or [])

    def item_boosts(self, sid):
        return self.D.boosts(sid)


class _SheetData:
    """The minimal Data object BSA.compute_sheet / build_input need (items, stats, Builds.lua), plus a boost cache."""

    def __init__(self, items, stats):
        self.items = items
        self.stats = stats
        self.ba = BSA.parse_builds_lua(BSA.BUILDS_LUA)
        self._ib = {}

    def boosts(self, sid):
        if sid not in self._ib:
            self._ib[sid] = BSA.item_boosts(self, sid)
        return self._ib[sid]


def latest_scores_ready(scores_dir=SCORES):
    """True when the score pipeline marked data/scores ready (READY_FOR_MOD.txt)."""
    return os.path.exists(os.path.join(scores_dir, "READY_FOR_MOD.txt"))


def score_files(scores_dir=SCORES):
    return sorted(glob.glob(os.path.join(scores_dir, "*.json")))
