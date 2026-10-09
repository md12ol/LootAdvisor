/* LootAdvisor - DDS decoder for the local Sets page (no game art ships with the page: the mod copies the player's own
   game textures as base64 and this decodes them in the browser). Formats: DXT1/BC1, DXT3/BC2, DXT5/BC3, BC4, BC5,
   BC7 (DXGI 98/99), uncompressed 32-bit (DXGI 28/29/87/88, legacy masks). decode(bytes) -> {w, h, data: RGBA}.
   BC7 partition / anchor tables: the BC7 specification (D3D11 / KHR_texture_compression_bptc), packed as hex. */
(function (root) {
  "use strict";
  var P2S = "cccc8888eeeeecc8c880feecfec8ec80c800ffecfe80e800ffe8ff00fff0f000f710008e710008ce008c731031008cce088c31106666366c17e80ff0718e399caaaaf0f05a5a33cc3c3c55aa9696a55a73ce13c8324c3bdc6996c33c99660660027204e44e402720c936936c39c6639c93369cc6817ee718ccf00fcc7744ee22", P3S = "aa6850506a5a50405a5a42005450a0a8a5a50000a0a050505555a0a05a5a5050aa550000aa555500aaaa55009090909094949494a4a4a4a4a9a594502a0a4250a59450400a425054a5a5a50055a0a0a0a8a854546a6a4040a4a450001a1a05000050a4a4aaa590901469691469691400a08585a0aa82141450a4a4506a5a0200a9a580005090a0a8a8a090502424242400aa5500249249242449922450a50a50500aa550aaaa444466660000a5a0a5a050a050a06928692844aaaa4466666600aa44444454a854a89580958096969600a85454a880959580aa14141496960000aaaa1414a05050a0a0a5a5a09600000040804080a9a8a9a8aaaaaa442a4a5254";
  var A2 = [15,15,15,15,15,15,15,15,15,15,15,15,15,15,15,15,15,2,8,2,2,8,8,15,2,8,2,2,8,8,2,2,15,15,6,8,2,8,15,15,2,8,2,2,2,15,15,6,6,2,6,8,15,15,2,2,15,15,15,15,15,2,2,15], A3A = [3,3,15,15,8,3,15,15,8,8,6,6,6,5,3,3,3,3,8,15,3,3,6,10,5,8,8,6,8,5,15,15,8,15,3,5,6,10,8,15,15,3,15,5,15,15,15,15,3,15,5,5,5,8,5,10,5,10,8,13,15,12,3,3], A3B = [15,8,8,3,15,15,3,8,15,15,15,15,15,15,15,8,15,8,15,3,15,8,15,8,3,15,6,10,15,15,10,8,15,3,15,10,10,8,9,10,6,15,8,15,3,6,6,8,15,3,15,15,15,15,15,15,15,15,15,15,3,15,15,8];
  var P2 = [], P3 = [];
  (function () {
    for (var p = 0; p < 64; p++) {
      var m2 = parseInt(P2S.substr(p * 4, 4), 16), m3 = parseInt(P3S.substr(p * 8, 8), 16), r2 = [], r3 = [];
      for (var i = 0; i < 16; i++) { r2.push((m2 >>> i) & 1); r3.push((m3 >>> (2 * i)) & 3); }
      P2.push(r2); P3.push(r3);
    }
  })();
  var W2 = [0, 21, 43, 64], W3 = [0, 9, 18, 27, 37, 46, 55, 64], W4 = [0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64];
  // mode: subsets, partition bits, rotation bits, index-selection bit, colour bits, alpha bits, endpoint P-bit,
  //       shared P-bit, index bits, secondary index bits
  var MODES = [[3, 4, 0, 0, 4, 0, 1, 0, 3, 0], [2, 6, 0, 0, 6, 0, 0, 1, 3, 0], [3, 6, 0, 0, 5, 0, 0, 0, 2, 0], [2, 6, 0, 0, 7, 0, 1, 0, 2, 0],
    [1, 0, 2, 1, 5, 6, 0, 0, 2, 3], [1, 0, 2, 0, 7, 8, 0, 0, 2, 2], [1, 0, 0, 0, 7, 7, 1, 0, 4, 0], [2, 6, 0, 0, 5, 5, 1, 0, 2, 0]];

  function interp(e0, e1, w) { return ((64 - w) * e0 + w * e1 + 32) >> 6; }
  function expand(v, n) { v = v << (8 - n); return v | (v >> n); }

  function bc7Block(src, o, out, ow, x0, y0, W, H) {
    var bitPos = 0;
    function bits(n) {
      var v = 0;
      for (var i = 0; i < n; i++) { var p = bitPos + i; v |= ((src[o + (p >> 3)] >> (p & 7)) & 1) << i; }
      bitPos += n; return v;
    }
    var mode = 0, px, py, k, i, s, e, c;
    while (mode < 8 && !bits(1)) mode++;
    if (mode >= 8) { // reserved mode: transparent black
      for (i = 0; i < 16; i++) { px = i & 3; py = i >> 2; if (x0 + px >= W || y0 + py >= H) continue; k = ((y0 + py) * ow + x0 + px) * 4; out[k] = out[k + 1] = out[k + 2] = out[k + 3] = 0; }
      return;
    }
    var M = MODES[mode], NS = M[0], part = bits(M[1]), rot = bits(M[2]), isb = bits(M[3]), CB = M[4], AB = M[5];
    var ep = [];  // ep[subset][endpoint] = [r, g, b, a]
    for (s = 0; s < NS; s++) ep.push([[0, 0, 0, 255], [0, 0, 0, 255]]);
    for (c = 0; c < 3; c++) for (s = 0; s < NS; s++) for (e = 0; e < 2; e++) ep[s][e][c] = bits(CB);
    if (AB) for (s = 0; s < NS; s++) for (e = 0; e < 2; e++) ep[s][e][3] = bits(AB);
    var cb = CB, ab = AB;
    if (M[6]) {
      for (s = 0; s < NS; s++) for (e = 0; e < 2; e++) {
        var pb = bits(1);
        for (c = 0; c < 3; c++) ep[s][e][c] = (ep[s][e][c] << 1) | pb;
        if (AB) ep[s][e][3] = (ep[s][e][3] << 1) | pb;
      }
      cb++; if (AB) ab++;
    } else if (M[7]) {
      for (s = 0; s < NS; s++) {
        var sp = bits(1);
        for (e = 0; e < 2; e++) for (c = 0; c < 3; c++) ep[s][e][c] = (ep[s][e][c] << 1) | sp;
      }
      cb++;
    }
    for (s = 0; s < NS; s++) for (e = 0; e < 2; e++) {
      for (c = 0; c < 3; c++) ep[s][e][c] = expand(ep[s][e][c], cb);
      ep[s][e][3] = AB ? expand(ep[s][e][3], ab) : 255;
    }
    var subsetOf = NS === 1 ? null : NS === 2 ? P2[part] : P3[part];
    var anchors = NS === 1 ? [0] : NS === 2 ? [0, A2[part]] : [0, A3A[part], A3B[part]];
    var IB = M[8], IB2 = M[9], idx = [], idx2 = [];
    for (i = 0; i < 16; i++) idx.push(bits(i === anchors[subsetOf ? subsetOf[i] : 0] ? IB - 1 : IB));
    if (IB2) for (i = 0; i < 16; i++) idx2.push(bits(i === 0 ? IB2 - 1 : IB2));
    var Wc = IB === 2 ? W2 : IB === 3 ? W3 : W4, Wa = Wc, ci = idx, ai = idx;
    if (IB2) {
      var Wsec = IB2 === 2 ? W2 : W3;
      if (isb) { ci = idx2; Wc = Wsec; ai = idx; Wa = W2; } else { ci = idx; ai = idx2; Wa = Wsec; }
    }
    for (i = 0; i < 16; i++) {
      px = i & 3; py = i >> 2;
      if (x0 + px >= W || y0 + py >= H) continue;
      var s2 = subsetOf ? subsetOf[i] : 0, a0 = ep[s2][0], a1 = ep[s2][1], wc = Wc[ci[i]], wa = Wa[ai[i]];
      var r = interp(a0[0], a1[0], wc), g = interp(a0[1], a1[1], wc), b = interp(a0[2], a1[2], wc), a = interp(a0[3], a1[3], wa), t;
      if (rot === 1) { t = a; a = r; r = t; } else if (rot === 2) { t = a; a = g; g = t; } else if (rot === 3) { t = a; a = b; b = t; }
      k = ((y0 + py) * ow + x0 + px) * 4;
      out[k] = r; out[k + 1] = g; out[k + 2] = b; out[k + 3] = a;
    }
  }

  function rgb565(v) { var r = (v >> 11) & 31, g = (v >> 5) & 63, b = v & 31; return [(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)]; }
  function colorBlock(src, o, out, ow, x0, y0, W, H, dxt1, alphaFn) {
    var c0 = src[o] | (src[o + 1] << 8), c1 = src[o + 2] | (src[o + 3] << 8), p0 = rgb565(c0), p1 = rgb565(c1);
    var pal = [p0.concat(255), p1.concat(255)], j;
    if (!dxt1 || c0 > c1) {
      pal.push([0, 1, 2].map(function (j) { return ((2 * p0[j] + p1[j]) / 3) | 0; }).concat(255));
      pal.push([0, 1, 2].map(function (j) { return ((p0[j] + 2 * p1[j]) / 3) | 0; }).concat(255));
    } else {
      pal.push([0, 1, 2].map(function (j) { return ((p0[j] + p1[j]) / 2) | 0; }).concat(255));
      pal.push([0, 0, 0, 0]);
    }
    var bitsv = (src[o + 4] | (src[o + 5] << 8) | (src[o + 6] << 16) | (src[o + 7] << 24)) >>> 0;
    for (var i = 0; i < 16; i++) {
      var px = i & 3, py = i >> 2;
      if (x0 + px >= W || y0 + py >= H) continue;
      var c = pal[(bitsv >>> (2 * i)) & 3], k = ((y0 + py) * ow + x0 + px) * 4;
      out[k] = c[0]; out[k + 1] = c[1]; out[k + 2] = c[2];
      out[k + 3] = alphaFn ? alphaFn(i) : c[3];
    }
  }
  function alphaPal(src, o) {
    var a0 = src[o], a1 = src[o + 1], pal = [a0, a1], j;
    if (a0 > a1) for (j = 1; j < 7; j++) pal.push((((7 - j) * a0 + j * a1) / 7) | 0);
    else { for (j = 1; j < 5; j++) pal.push((((5 - j) * a0 + j * a1) / 5) | 0); pal.push(0, 255); }
    var lo = (src[o + 2] | (src[o + 3] << 8) | (src[o + 4] << 16)) >>> 0, hi = (src[o + 5] | (src[o + 6] << 8) | (src[o + 7] << 16)) >>> 0;
    return function (i) { return pal[i < 8 ? (lo >>> (3 * i)) & 7 : (hi >>> (3 * (i - 8))) & 7]; };
  }

  function decode(buf) {
    var u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    var dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    if (u8.length < 128 || dv.getUint32(0, true) !== 0x20534444) throw new Error("not a DDS file");
    var H = dv.getUint32(12, true), W = dv.getUint32(16, true), pfFlags = dv.getUint32(80, true);
    var four = String.fromCharCode(u8[84], u8[85], u8[86], u8[87]), off = 128, fmt = four;
    if (four === "DX10") { fmt = "DXGI" + dv.getUint32(128, true); off = 148; }
    var out = new Uint8ClampedArray(W * H * 4), bw = Math.ceil(W / 4), bh = Math.ceil(H / 4), bx, by, o = off, i;
    if (fmt === "DXGI98" || fmt === "DXGI99" || fmt === "DXGI97") {
      for (by = 0; by < bh; by++) for (bx = 0; bx < bw; bx++, o += 16) bc7Block(u8, o, out, W, bx * 4, by * 4, W, H);
    } else if (fmt === "DXT1" || fmt === "DXGI71" || fmt === "DXGI72") {
      for (by = 0; by < bh; by++) for (bx = 0; bx < bw; bx++, o += 8) colorBlock(u8, o, out, W, bx * 4, by * 4, W, H, true, null);
    } else if (fmt === "DXT5" || fmt === "DXT4" || fmt === "DXGI77" || fmt === "DXGI78") {
      for (by = 0; by < bh; by++) for (bx = 0; bx < bw; bx++, o += 16) colorBlock(u8, o + 8, out, W, bx * 4, by * 4, W, H, false, alphaPal(u8, o));
    } else if (fmt === "DXT3" || fmt === "DXT2" || fmt === "DXGI74" || fmt === "DXGI75") {
      for (by = 0; by < bh; by++) for (bx = 0; bx < bw; bx++, o += 16) {
        colorBlock(u8, o + 8, out, W, bx * 4, by * 4, W, H, false, (function (ao) {
          return function (i) { return ((u8[ao + (i >> 1)] >> ((i & 1) * 4)) & 15) * 17; };
        })(o));
      }
    } else if (fmt === "ATI1" || fmt === "BC4U" || fmt === "DXGI80" || fmt === "ATI2" || fmt === "BC5U" || fmt === "DXGI83") {
      var two = fmt === "ATI2" || fmt === "BC5U" || fmt === "DXGI83";
      for (by = 0; by < bh; by++) for (bx = 0; bx < bw; bx++) {
        var fr = alphaPal(u8, o), fg = two ? alphaPal(u8, o + 8) : null; o += two ? 16 : 8;
        for (i = 0; i < 16; i++) {
          var px = i & 3, py = i >> 2; if (bx * 4 + px >= W || by * 4 + py >= H) continue;
          var k = ((by * 4 + py) * W + bx * 4 + px) * 4, r = fr(i);
          out[k] = r; out[k + 1] = fg ? fg(i) : r; out[k + 2] = fg ? 0 : r; out[k + 3] = 255;
        }
      }
    } else {
      var bpp = dv.getUint32(88, true), rm = dv.getUint32(92, true), gm = dv.getUint32(96, true), bm = dv.getUint32(100, true), am = dv.getUint32(104, true);
      if (fmt === "DXGI28" || fmt === "DXGI29") { rm = 0xff; gm = 0xff00; bm = 0xff0000; am = 0xff000000; bpp = 32; }
      else if (fmt === "DXGI87" || fmt === "DXGI91") { rm = 0xff0000; gm = 0xff00; bm = 0xff; am = 0xff000000; bpp = 32; }
      else if (fmt === "DXGI88" || fmt === "DXGI93") { rm = 0xff0000; gm = 0xff00; bm = 0xff; am = 0; bpp = 32; }
      else if (!(pfFlags & 0x40)) throw new Error("unsupported DDS format " + fmt);
      var B = bpp >> 3;
      var ch = function (v, m) { if (!m) return 255; var sh = 0; while (!((m >>> sh) & 1)) sh++; return Math.round(((v & m) >>> sh) * 255 / (m >>> sh)); };
      for (var p = 0; p < W * H; p++) {
        var v = 0; for (var b = 0; b < B; b++) v |= u8[o + p * B + b] << (8 * b);
        v >>>= 0;
        out[p * 4] = ch(v, rm); out[p * 4 + 1] = ch(v, gm); out[p * 4 + 2] = ch(v, bm); out[p * 4 + 3] = am ? ch(v, am) : 255;
      }
    }
    return { w: W, h: H, data: out, fmt: fmt };
  }
  root.LADDS = { decode: decode };
  if (typeof module !== "undefined" && module.exports) module.exports = root.LADDS;
})(typeof window !== "undefined" ? window : globalThis);
