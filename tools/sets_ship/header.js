/* LootAdvisor - Gilded Panel header: fills the inventory-icon strip from the PLAYER'S OWN game icons (decoded by ship.js
   from the files the mod wrote, or the page's embedded icons in the claude.ai artifact). Nothing of the game ships with
   the page: DATA.hdr only names art keys of page items.
     DATA.hdr = { cols, rows, phone, la, items: [[artKey, frame, count], ...] }   best first (build_sets_ship.header_rank:
     Legendary / Very Rare items ranked by how often the sets pick them)
   The strip takes the first items whose icon exists (a missing icon -> the next item); the first `la` get Loot
   Advisor's rainbow frame, the others the game's rarity frame. Before the icons exist the cells are empty slots. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("la-data").textContent), H = DATA.hdr, UI = DATA.ui || {};
  var PITCH = 84, X0 = 10, Y0 = 8;   // design px of the 1440 x 240 panel (branding/LootAdvisor/option1_sets.png)

  function cell(c, IMG, wide, i, la) {
    var s = '<span class="gc' + (c && la ? " la" : "") + (IMG ? "" : " wait") + '"';
    if (wide) s += ' style="left:calc(' + (X0 + (i % H.cols) * PITCH) + ' * var(--u));top:calc(' + (Y0 + Math.floor(i / H.cols) * PITCH) + ' * var(--u))"';
    s += ">";
    if (!IMG || !c) return s + "</span>";
    var ic = IMG[c[0]], back = !la && IMG[UI["rf_" + c[1] + "_back"]], front = !la && IMG[UI["rf_" + c[1] + "_front"]];
    if (back) s += '<span class="rb" style="background-image:url(' + back + ')"></span>';
    s += '<img src="' + ic + '" alt="">';
    if (front) s += '<span class="rf" style="background-image:url(' + front + ')"></span>';
    if (c[2] > 1) s += "<b>" + c[2] + "</b>";
    return s + "</span>";
  }
  function paint(IMG) {
    if (!H || !H.items) return;
    var n = H.cols * H.rows, list = IMG ? H.items.filter(function (c) { return IMG[c[0]]; }) : [];
    var strip = document.getElementById("gpStrip"), row = document.getElementById("gpRow"), w = [], p = [];
    // best items where they are seen: rows 1-2 right of the fade first, then the faded first column, then the cut row 3
    var order = [], r, c2;
    for (r = 0; r < Math.min(2, H.rows); r++) for (c2 = 1; c2 < H.cols; c2++) order.push(r * H.cols + c2);
    for (r = 0; r < Math.min(2, H.rows); r++) order.push(r * H.cols);
    for (r = 2; r < H.rows; r++) for (c2 = 0; c2 < H.cols; c2++) order.push(r * H.cols + c2);
    var at = {};
    order.forEach(function (pos, rank) { at[pos] = rank; });
    for (var i = 0; i < n; i++) w.push(cell(list[at[i]], IMG, true, i, at[i] < H.la));
    for (var j = 0; j < H.phone; j++) p.push(cell(list[j], IMG, false, j, j < H.la));
    if (strip) strip.innerHTML = w.join("") + '<span class="gp-bar"></span>';
    if (row) row.innerHTML = p.join("");
  }
  if (DATA.ship) paint(null);   // shipped page: empty slots while it prepares the icons from the game files
  else { try { paint(JSON.parse(document.getElementById("la-img").textContent)); } catch (e) { paint(null); } }   // artifact: icons embedded
  window.LA_HEADER = paint;   // called with the image map once the game icons exist
})();
