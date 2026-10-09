"""Rainbow design options for LootAdvisor, built from the game's own frame / map-icon textures (shapes and alpha
are the game's; only the colours change). Writes design/out/*.png and two comparison sheets.

  python design/make_rainbow.py
"""
import colorsys
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)


def load(*p):
    return Image.open(os.path.join(HERE, *p)).convert("RGBA")


def hue_rgb(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def field(size, kind, s=1.0, v=1.0, phase=0.0):
    """RGB image whose hue follows `kind`: conic (around centre), diag, horiz, vert."""
    w, h = size
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(h):
        for x in range(w):
            if kind == "conic":
                t = (math.atan2(y - h / 2 + 0.5, x - w / 2 + 0.5) / (2 * math.pi)) + 0.5
            elif kind == "diag":
                t = (x + y) / (w + h - 2) * 0.85
            elif kind == "horiz":
                t = x / (w - 1) * 0.85
            else:
                t = y / (h - 1) * 0.85
            px[x, y] = hue_rgb(t + phase, s, v)
    return im


def recolor_alpha(src, colours):
    """Keep src's alpha, take colours' RGB."""
    out = colours.convert("RGBA")
    out.putalpha(src.getchannel("A"))
    return out


def recolor_lum(src, colours, gain=1.35):
    """Keep src's alpha and its brightness pattern, tint with colours (for detailed icons)."""
    lum = src.convert("L")
    c = colours.convert("RGB")
    r, g, b = [ImageChops.multiply(ch, lum) for ch in c.split()]
    out = Image.merge("RGB", [x.point(lambda v: min(255, int(v * gain))) for x in (r, g, b)]).convert("RGBA")
    out.putalpha(src.getchannel("A"))
    return out


# ---------------------------------------------------------------- item frames (80x80, back + front + overlay)
FB = load("frames_game", "rarityFrame_veryrare_back.png")
FF = load("frames_game", "rarityFrame_veryrare_front.png")
S80 = FF.size


def frame_option(n):
    over = None
    if n == 1:   # Prism: border hue runs around the frame; back glows rainbow left to right
        back = recolor_alpha(FB, field(S80, "horiz", 0.9, 0.75))
        front = recolor_alpha(FF, field(S80, "conic"))
    elif n == 2:  # Sheen: diagonal rainbow border + a light diagonal rainbow wash over the icon
        back = recolor_alpha(FB, field(S80, "diag", 0.8, 0.6))
        front = recolor_alpha(FF, field(S80, "diag"))
        over = field(S80, "diag", 0.9, 1.0).convert("RGBA")
        a = Image.new("L", S80, 0)
        d = ImageDraw.Draw(a)
        for i in range(80):   # stronger at the edges, clear in the middle so the icon stays readable
            d.rectangle([i // 2, i // 2, 79 - i // 2, 79 - i // 2], outline=int(70 * (1 - i / 80) ** 1.6))
        over.putalpha(a)
    else:         # Aurora: rainbow light rising from the bottom, white-hot border with a rainbow glow
        back = recolor_alpha(FB, field(S80, "horiz", 1.0, 1.0))
        ba = FB.getchannel("A").point(lambda v: min(255, int(v * 1.6)))
        back.putalpha(ba)
        glow = recolor_alpha(FF, field(S80, "horiz")).filter(ImageFilter.GaussianBlur(2.2))
        core = FF.copy()
        core = Image.merge("RGBA", (Image.new("L", S80, 255),) * 3 + (FF.getchannel("A").point(lambda v: int(v * 0.85)),))
        front = Image.alpha_composite(glow, core)
        front = Image.alpha_composite(front, recolor_alpha(FF, field(S80, "horiz")).copy())
        over = field(S80, "horiz").convert("RGBA")
        a = Image.new("L", S80, 0)
        d = ImageDraw.Draw(a)
        for y in range(80):
            d.line([(0, y), (79, y)], fill=int(60 * max(0, (y - 48) / 32) ** 1.5))
        over.putalpha(a)
    return back, front, over


def cell(icon, back, front, over, size=80):
    """Composite like the game cell: dark slot, back layer, icon, overlay, front border."""
    c = Image.new("RGBA", (size, size), (24, 21, 19, 255))
    if back:
        c.alpha_composite(back)
    ic = icon.resize((64, 64), Image.LANCZOS)
    c.alpha_composite(ic, (8, 8))
    if over:
        c.alpha_composite(over)
    if front:
        c.alpha_composite(front)
    return c


ICONS = [load("icons", n + ".png") for n in ("Item_WPN_HUM_Longsword_A_1", "Item_ARM_Helmet_Metal_A",
                                             "Item_LOOT_GEN_Amulet_Necklace_B_Silver_A", "Item_WPN_HUM_Longbow_A_1")]


def frames_sheet():
    rows = []
    labels = []
    for n in (1, 2, 3):
        b, f, o = frame_option(n)
        b.save(os.path.join(OUT, f"frame{n}_back.png"))
        f.save(os.path.join(OUT, f"frame{n}_front.png"))
        if o:
            o.save(os.path.join(OUT, f"frame{n}_overlay.png"))
        rows.append([cell(i, b, f, o) for i in ICONS])
        labels.append({1: "Option 1  Prism", 2: "Option 2  Rainbow sheen", 3: "Option 3  Aurora"}[n])
    ref = []
    for r in ("uncommon", "rare", "veryrare", "legendary"):
        ref.append(cell(ICONS[0], load("frames_game", f"rarityFrame_{r}_back.png"),
                        load("frames_game", f"rarityFrame_{r}_front.png"), None))
    rows.append(ref)
    labels.append("Game: uncommon / rare / very rare / legendary")
    scale, pad, lab = 3, 16, 300
    W = lab + len(rows[0]) * (80 * scale + pad) + pad
    H = len(rows) * (80 * scale + pad) + pad
    sheet = Image.new("RGBA", (W, H), (14, 12, 11, 255))
    d = ImageDraw.Draw(sheet)
    for ri, row in enumerate(rows):
        y = pad + ri * (80 * scale + pad)
        d.text((pad, y + 110), labels[ri], fill=(230, 220, 200, 255))
        for ci, c in enumerate(row):
            sheet.alpha_composite(c.resize((80 * scale, 80 * scale), Image.NEAREST), (lab + pad + ci * (80 * scale + pad), y))
    sheet.save(os.path.join(OUT, "SHEET_item_frames.png"))


# ---------------------------------------------------------------- map symbols (+ matching off-screen arrows)
Q = load("mapicons", "mapSelector_quest.png")
SEC = load("mapicons", "ico_secret.png")
ARROW = load("mapicons", "offScreen_quest.png")
GLOW = load("mapicons", "marker_glow.png")


def gem(size=68):
    """Option 3: a faceted rainbow diamond with a gold rim (drawn, game has no gem marker)."""
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    mask = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(mask)
    m = 8
    d.polygon([(s / 2, m), (s - m, s / 2), (s / 2, s - m), (m, s / 2)], fill=255)
    col = field((s, s), "conic").convert("RGBA")
    col.putalpha(mask)
    # facets: lighter top-left, darker bottom-right
    shade = Image.new("L", (s, s), 0)
    sd = ImageDraw.Draw(shade)
    sd.polygon([(s / 2, m), (s / 2, s / 2), (m, s / 2)], fill=70)
    sd.polygon([(s / 2, s - m), (s / 2, s / 2), (s - m, s / 2)], fill=0)
    white = Image.new("RGBA", (s, s), (255, 255, 255, 0))
    white.putalpha(ImageChops.multiply(shade, mask))
    im.alpha_composite(col)
    im.alpha_composite(white)
    rim = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.polygon([(s / 2, m - 3), (s - m + 3, s / 2), (s / 2, s - m + 3), (m - 3, s / 2)], outline=(229, 190, 110, 255), width=3)
    return Image.alpha_composite(rim, im)


def map_option(n):
    if n == 1:   # the game's quest marker, rainbow around
        sym = recolor_lum(Q, field(Q.size, "conic"), 1.6)
        arr = recolor_lum(ARROW, field(ARROW.size, "conic"), 1.6)
    elif n == 2:  # the game's secret marker, diagonal rainbow, with a soft rainbow halo
        halo = recolor_alpha(GLOW.resize(SEC.size), field(SEC.size, "conic", 1.0, 1.0))
        halo.putalpha(halo.getchannel("A").point(lambda v: int(v * 0.6)))
        sym = Image.alpha_composite(halo, recolor_lum(SEC, field(SEC.size, "diag"), 1.7))
        arr = recolor_lum(ARROW, field(ARROW.size, "diag"), 1.6)
    else:         # drawn rainbow gem, gold rim; arrow = the game arrow in rainbow with the gem inside
        sym = gem()
        arr = recolor_lum(ARROW, field(ARROW.size, "horiz"), 1.6)
    # The game's own off-screen arrow texture (dark disc, gold rim, gold tip = up); the game draws the marker icon
    # inside it. Keep the texture exactly (size, shape, dark disc, glow) and only turn its gold into rainbow, then put
    # our symbol inside at the game's proportion (icon ~ 0.7 of the disc).
    a = ARROW.copy()
    px = a.load()
    rb = field(a.size, "conic").load()
    w, h = a.size
    for y in range(h):
        for x in range(w):
            r, g, b, al = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn) / mx if mx else 0
            if sat > 0.35 and mx > 60:          # the gold parts (rim, tip, glow)
                rr, gg, bb = rb[x, y]
                k = mx / 255 * 1.15
                px[x, y] = (min(255, int(rr * k)), min(255, int(gg * k)), min(255, int(bb * k)), al)
    # dark inner disc of offScreen_quest.DDS: centre (34, 41), diameter ~36 px (measured from the texture)
    isz, cxx, cyy = 30, 34, 41
    inner = sym.resize((isz, isz), Image.LANCZOS)
    a.alpha_composite(inner, (cxx - isz // 2, cyy - isz // 2))
    return sym, a


def map_sheet():
    mm = Image.open(os.path.join(HERE, "..", "shots", "04_markers_off_crop.png")).convert("RGBA")
    tiles = []
    for n in (1, 2, 3):
        sym, arr = map_option(n)
        sym.save(os.path.join(OUT, f"map{n}_symbol.png"))
        arr.save(os.path.join(OUT, f"map{n}_arrow.png"))
        t = mm.copy()
        s = sym.resize((44, 44), Image.LANCZOS)
        t.alpha_composite(s, (205, 150))          # on the map, near the party
        a = arr.resize((40, 38), Image.LANCZOS).rotate(-35, expand=True, resample=Image.BICUBIC)
        t.alpha_composite(a, (88, 360))          # at the minimap edge, pointing outwards (bottom-left)
        big = Image.new("RGBA", (300, 150), (14, 12, 11, 255))
        big.alpha_composite(sym.resize((136, 136), Image.LANCZOS), (6, 7))
        big.alpha_composite(arr.resize((128, 120), Image.LANCZOS), (160, 15))
        col = Image.new("RGBA", (t.width, t.height + 160), (14, 12, 11, 255))
        col.alpha_composite(t, (0, 0))
        col.alpha_composite(big, (10, t.height + 5))
        d = ImageDraw.Draw(col)
        d.text((330, t.height + 20), {1: "Option 1\nQuest diamond,\nrainbow around", 2: "Option 2\nQuest pin,\ndiagonal rainbow\n+ halo", 3: "Option 3\nRainbow gem,\ngold rim"}[n], fill=(230, 220, 200, 255))
        tiles.append(col)
    W = sum(t.width for t in tiles) + 20 * 4
    sheet = Image.new("RGBA", (W, tiles[0].height + 40), (14, 12, 11, 255))
    x = 20
    for t in tiles:
        sheet.alpha_composite(t, (x, 20))
        x += t.width + 20
    sheet.save(os.path.join(OUT, "SHEET_map_symbols.png"))


if __name__ == "__main__":
    frames_sheet()
    map_sheet()
    print("wrote", OUT)
