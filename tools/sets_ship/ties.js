/* LootAdvisor - tie picks on the local Sets page: an item that fits two or more party members exactly as well
   (the data's owners `o` plus the characters tied with them `ot`). Who gets it:
     1. the game's answer, written by the mod into the live state (state.picks[stats id] = {c, by}): the one wearing it
        (by "wear") or the pick made in the game's F6 list (by "pick");
     2. else the pick made on this page (kept in the browser);
     3. else nobody yet: the page asks.
   Only party members count (other players' characters too); fewer than two of them in the party is no tie.
   Pure functions, also run by the offline tests (node). */
(function (root) {
  "use strict";
  // the item's tie members, or [] when nobody is tied with its owner
  function members(it) {
    if (!it || !it.ot || !it.ot.length) return [];
    var out = [];
    (it.o || []).concat(it.ot).forEach(function (c) { if (out.indexOf(c) < 0) out.push(c); });
    return out;
  }
  // me: the set's character; inParty(c) -> bool; gamePick: {c, by} or null; pagePick: a character or null.
  // -> { k: "free" (me / nobody else in the party), "give" (someone else gets it: use the set's alternative),
  //      "shared" (an open tie: ask), who: [characters], pick, by: "wear" | "game" | "page" | null, cands: [party members] }
  function contest(me, it, inParty, gamePick, pagePick) {
    var mem = members(it), present = mem.filter(function (c) { return inParty(c); });
    if (present.length < 2) {
      if (!present.length || present[0] === me) return { k: "free", who: [], pick: null, by: null, cands: present };
      return { k: "give", who: [present[0]], pick: null, by: null, cands: present };
    }
    var pick = null, by = null;
    if (gamePick && present.indexOf(gamePick.c) >= 0) { pick = gamePick.c; by = gamePick.by === "wear" ? "wear" : "game"; }
    else if (pagePick && present.indexOf(pagePick) >= 0) { pick = pagePick; by = "page"; }
    if (pick) return { k: pick === me ? "free" : "give", who: pick === me ? [] : [pick], pick: pick, by: by, cands: present };
    if (present.indexOf(me) < 0) return { k: "give", who: [present[0]], pick: null, by: null, cands: present };
    return { k: "shared", who: present.filter(function (c) { return c !== me; }), pick: null, by: null, cands: present };
  }
  var T = { members: members, contest: contest };
  if (typeof module !== "undefined" && module.exports) module.exports = T;
  else root.LA_TIES = T;
})(this);
