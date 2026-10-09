/* LootAdvisor - Gilded Panel header of the shipped Sets page: fills the inventory-icon strip from the PLAYER'S OWN game
   icons (decoded by ship.js from the files the mod wrote). Nothing of the game ships with the page: DATA.hdr only names
   art keys (icon names) + our frame / stack-count choices.
     DATA.hdr = { cols: 7, cells: [[artKey|"", frame, count], ...] (row major), phone: [cell index, ...] }
     frame: "" | "la" (Loot Advisor's rainbow frame) | uncommon / rare / veryrare / legendary / story (the game's frame art)
   Before the icons exist (first start, mod still writing them) or when one is missing, the cell stays an empty slot. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("la-data").textContent), H = DATA.hdr, UI = DATA.ui || {};
  var PITCH = 84, X0 = 10, Y0 = 8;   // design px of the 1440 x 240 panel (branding/LootAdvisor/option1_sets.png)

  function cell(c, IMG, wide, i) {
    var s = '<span class="gc' + (c[1] === "la" ? " la" : "") + (IMG ? "" : " wait") + '"';
    if (wide) {
      var col = i % H.cols, row = Math.floor(i / H.cols);
      s += ' style="left:calc(' + (X0 + col * PITCH) + ' * var(--u));top:calc(' + (Y0 + row * PITCH) + ' * var(--u))"';
    }
    s += ">";
    if (!IMG) return s + "</span>";
    var back = c[1] && c[1] !== "la" && IMG[UI["rf_" + c[1] + "_back"]], front = c[1] && c[1] !== "la" && IMG[UI["rf_" + c[1] + "_front"]];
    var ic = c[0] && IMG[c[0]];
    if (back && ic) s += '<span class="rb" style="background-image:url(' + back + ')"></span>';
    if (ic) s += '<img src="' + ic + '" alt="">';
    if (front && ic) s += '<span class="rf" style="background-image:url(' + front + ')"></span>';
    if (ic && c[2] > 1) s += "<b>" + c[2] + "</b>";
    return s + "</span>";
  }
  function paint(IMG) {
    if (!H || !H.cells) return;
    var strip = document.getElementById("gpStrip"), row = document.getElementById("gpRow");
    if (strip) strip.innerHTML = H.cells.map(function (c, i) { return cell(c, IMG, true, i); }).join("") + '<span class="gp-bar"></span>';
    if (row) row.innerHTML = (H.phone || []).map(function (i) { return cell(H.cells[i], IMG, false, i); }).join("");
  }
  paint(null);   // empty slots while the page prepares the icons
  window.LA_HEADER = paint;   // ship.js calls this with the image map once the game icons are decoded
})();
