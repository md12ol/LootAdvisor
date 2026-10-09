"""Builds a mod's own GUI textures + GUI/metadata.lsf into its GUI folder (IMAGES.md Plan A).

  python LootAdvisor/tools/make_la_gui.py <mod GUI folder>                e.g. Mods/LootAdvisor/GUI  (Loot Advisor set)
  python LootAdvisor/tools/make_la_gui.py <mod GUI folder> --set build    e.g. Mods/BuildAdvisor/GUI (Build Advisor set)

Build Advisor set (Assets/BuildAdvisor/, its own copy so it works without Loot Advisor):
  ba_tile_ring.DDS  196x196 BC3 sRGB  "Prism" rainbow ring for creation / level-up tiles (race, class, subclass,
                                      background, deity): the game's selector glow profile (selector_CC: a 4 px
                                      core line + a 10 px glow), core on the outer edge so it shows around the tile
                                      picture; drawn as the tile Grid's Background (196 = the tile Grid's size)
  ba_icon_ring.DDS   88x88  BC3 sRGB  the same ring for spell / cantrip icons (80 px icon + 4 px border = 88 px),
                                      used as the icon Border's BorderBrush (only the outer 4 px show)
Loot Advisor set (default):

Writes (sizes like the game's textures; LowRes = half size rounded up to a multiple of 4, as the game does):
  Assets/LootAdvisor/frame1_back.DDS, frame1_front.DDS   80x80  BC3 sRGB   design/out/frame1_*.png ("Prism")
  Assets/LootAdvisor/map1_symbol.DDS                     68x68  BC3        design/out/map1_symbol.png (quest diamond)
  Assets/LootAdvisor/map1_arrow_empty.DDS                68x64  BC3        the game's offScreen_quest arrow recoloured
                                                                           rainbow, WITHOUT an icon inside: the game
                                                                           draws the marker icon into it itself
  test variants of frame1_front: _dxt5 (legacy DXT5), _unorm (BC3 non-sRGB), _rgba (uncompressed sRGB)
  AssetsLowRes/LootAdvisor/<same names>.DDS
  metadata.lsf   config > entries > Object{MapKey "Assets/LootAdvisor/<name>.png"} > entries{h, mipcount, w}
The XAML (StateMachines/Pages/Library) is hand-written in the mod folder, not generated here.
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(LA, "design"))
import dds  # noqa: E402
import lsf  # noqa: E402
import lsf_write  # noqa: E402

OUT = os.path.join(LA, "design", "out")


def arrow_empty():
    """offScreen_quest recoloured exactly like design/make_rainbow.py map_option(1) does, minus the inner symbol."""
    import make_rainbow as mr
    a = mr.ARROW.copy()
    px = a.load()
    rb = mr.field(a.size, "conic").load()
    w, h = a.size
    for y in range(h):
        for x in range(w):
            r, g, b, al = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            sat = (mx - mn) / mx if mx else 0
            if sat > 0.35 and mx > 60:
                rr, gg, bb = rb[x, y]
                k = mx / 255 * 1.15
                px[x, y] = (min(255, int(rr * k)), min(255, int(gg * k)), min(255, int(bb * k)), al)
    return a


def textures():
    fb = Image.open(os.path.join(OUT, "frame1_back.png"))
    ff = Image.open(os.path.join(OUT, "frame1_front.png"))
    sym = Image.open(os.path.join(OUT, "map1_symbol.png"))
    arr = arrow_empty()
    arr.save(os.path.join(OUT, "map1_arrow_empty.png"))
    return [  # (name, image, format)
        ("frame1_back", fb, "bc3srgb"),
        ("frame1_front", ff, "bc3srgb"),
        ("map1_symbol", sym, "bc3"),
        ("map1_arrow_empty", arr, "bc3"),
        ("frame1_front_dxt5", ff, "dxt5"),
        ("frame1_front_unorm", ff, "bc3"),
        ("frame1_front_rgba", ff, "rgbasrgb"),
    ]


GLOW = [113, 97, 84, 69, 53, 38, 22, 12, 4]   # the game's selector_CC.DDS glow profile, core line outwards
CORE = 4


def ring(size, radius):
    """Rainbow ring like the game's selection frame: solid 4 px core on the outer edge, then the glow inwards."""
    import make_rainbow as mr
    w = h = size
    col = mr.field((w, h), "conic").load()
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y in range(h):
        for x in range(w):
            # distance from the outer edge of a rounded square (corner radius `radius`)
            cx = min(max(x + 0.5, radius), w - radius)
            cy = min(max(y + 0.5, radius), h - radius)
            dx, dy = (x + 0.5) - cx, (y + 0.5) - cy
            inside_corner = (x + 0.5 < radius or x + 0.5 > w - radius) and (y + 0.5 < radius or y + 0.5 > h - radius)
            if inside_corner:
                d = radius - (dx * dx + dy * dy) ** 0.5
            else:
                d = min(x + 0.5, y + 0.5, w - x - 0.5, h - y - 0.5)
            if d < 0:
                continue
            r, g, b = col[x, y]
            if d < CORE:
                a = 255
                r, g, b = (int(c + (255 - c) * 0.35) for c in (r, g, b))   # bright core, like the game's pale line
            else:
                i = int(d - CORE)
                if i >= len(GLOW):
                    continue
                a = GLOW[i]
            px[x, y] = (r, g, b, a)
    return im


def build_textures():
    return [
        ("ba_tile_ring", ring(196, 22), "bc3srgb"),
        ("ba_icon_ring", ring(88, 6), "bc3srgb"),
    ]


SETS = {"loot": ("LootAdvisor", textures), "build": ("BuildAdvisor", build_textures)}


def metadata(entries):
    root = lsf.Node("config")
    ents = lsf.Node("entries", root)
    root.children.append(ents)
    for key, w, h in entries:
        o = lsf.Node("Object", ents)
        o.attrs["MapKey"] = ("FixedString", key)
        e = lsf.Node("entries", o)
        e.attrs["h"] = ("Short", h)
        e.attrs["mipcount"] = ("Int8", 1)
        e.attrs["w"] = ("Short", w)
        o.children.append(e)
        ents.children.append(o)
    return lsf.Resource(7, lsf_write.pack_engine_version(*lsf_write.DEFAULT_ENGINE), [root])


def main(gui, which="loot"):
    folder, make = SETS[which]
    hi = os.path.join(gui, "Assets", folder)
    lo = os.path.join(gui, "AssetsLowRes", folder)
    os.makedirs(hi, exist_ok=True)
    os.makedirs(lo, exist_ok=True)
    entries = []
    for name, im, fmt in make():
        p = os.path.join(hi, name + ".DDS")
        size, n = dds.write(im, p, fmt)
        err = dds.check(p, im)
        size2, n2 = dds.write(im, os.path.join(lo, name + ".DDS"), fmt, half=True)
        entries.append(("Assets/%s/%s.png" % (folder, name), size[0], size[1]))
        print("  %-22s %-8s %dx%d %6d B (err %.2f)  lowres %dx%d" % (name, fmt, size[0], size[1], n, err, *size2))
    blob = lsf_write.dump(metadata(entries))
    back = lsf.load(blob)
    keys = [o.get("MapKey") for o in back.regions[0].children[0].children]
    assert keys == [e[0] for e in entries]
    with open(os.path.join(gui, "metadata.lsf"), "wb") as f:
        f.write(blob)
    print("wrote %s (%d entries, %d bytes)" % (os.path.join(gui, "metadata.lsf"), len(keys), len(blob)))


if __name__ == "__main__":
    args = sys.argv[1:]
    which = "loot"
    if "--set" in args:
        i = args.index("--set")
        which = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or which not in SETS:
        print(__doc__)
        sys.exit(1)
    main(args[0], which)
