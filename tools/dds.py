"""DDS writer for BG3 GUI textures (no downloads: Pillow does the BC3 block compression, we write the header).

  python dds.py <in.png> <out.DDS> [bc3|bc3srgb|dxt5|rgba|rgbasrgb] [--half]
  python dds.py --info <file.DDS>            print the header like the game's (size, flags, pitch, mips, DXGI)

Formats (all 1 mip, sizes must be multiples of 4 for the BC formats):
  bc3 / bc3srgb   DX10 header, DXGI 77 BC3_UNORM / 78 BC3_UNORM_SRGB, header laid out exactly like the game's own
                  BC7 GUI textures (flags 0xA1007, linear size, depth 1, caps 0x1000, DX10 {dxgi, 2D, 0, 1, 0}).
                  The game uses BC7 (98 UNORM for map icons, 99 SRGB for rarity frames); BC7 needs an encoder we
                  do not have (texconv/LSLib), BC3 is the closest Pillow can write (alpha + colour, 16 bytes/block).
  dxt5            legacy FourCC "DXT5" header (what NMCM ships), same payload as bc3.
  rgba / rgbasrgb uncompressed DX10 R8G8B8A8 (DXGI 28 / 29), pitch = 4 * width.
Alpha is straight (not premultiplied), like the game's textures (checked on rarityFrame_*.DDS / offScreen_quest.DDS).
"""
import io
import struct
import sys

from PIL import Image

DDSD = 0x1 | 0x2 | 0x4 | 0x1000            # CAPS | HEIGHT | WIDTH | PIXELFORMAT
DDSD_PITCH, DDSD_MIPMAPCOUNT, DDSD_LINEARSIZE = 0x8, 0x20000, 0x80000
DDPF_FOURCC = 0x4
DDSCAPS_TEXTURE = 0x1000
DXGI = {"bc3": 77, "bc3srgb": 78, "rgba": 28, "rgbasrgb": 29}


def bc3_payload(im):
    """RGBA image -> raw BC3 (DXT5) blocks via Pillow's DDS encoder."""
    buf = io.BytesIO()
    im.save(buf, format="DDS", pixel_format="DXT5")
    b = buf.getvalue()
    assert b[84:88] == b"DXT5", "Pillow did not write a DXT5 file"
    n = ((im.width + 3) // 4) * ((im.height + 3) // 4) * 16
    data = b[128:128 + n]
    assert len(data) == n
    return data


def header(w, h, fmt, linear_or_pitch):
    compressed = fmt in ("bc3", "bc3srgb", "dxt5")
    flags = DDSD | DDSD_MIPMAPCOUNT | (DDSD_LINEARSIZE if compressed else DDSD_PITCH)
    fourcc = b"DXT5" if fmt == "dxt5" else b"DX10"
    hd = b"DDS " + struct.pack("<7I", 124, flags, h, w, linear_or_pitch, 1, 1)
    hd += b"\0" * 44                                              # reserved1[11]
    hd += struct.pack("<2I4s5I", 32, DDPF_FOURCC, fourcc, 0, 0, 0, 0, 0)
    hd += struct.pack("<4I", DDSCAPS_TEXTURE, 0, 0, 0) + b"\0" * 4  # caps1-4, reserved2
    if fourcc == b"DX10":
        hd += struct.pack("<5I", DXGI[fmt], 3, 0, 1, 0)             # dxgi, TEXTURE2D, misc, arraySize, misc2
    return hd


def to_dds(im, fmt="bc3"):
    im = im.convert("RGBA")
    if fmt in ("bc3", "bc3srgb", "dxt5"):
        if im.width % 4 or im.height % 4:
            raise ValueError("BC formats need sizes that are multiples of 4 (got %dx%d)" % im.size)
        data = bc3_payload(im)
        return header(im.width, im.height, fmt, len(data)) + data
    if fmt in ("rgba", "rgbasrgb"):
        return header(im.width, im.height, fmt, im.width * 4) + im.tobytes()
    raise ValueError("unknown format %s" % fmt)


def write(png_or_image, path, fmt="bc3", half=False):
    im = png_or_image if isinstance(png_or_image, Image.Image) else Image.open(png_or_image)
    im = im.convert("RGBA")
    if half:
        # like the game's AssetsLowRes copies: half size rounded UP to a multiple of 4 (68x64 -> 36x32)
        im = im.resize((-(-im.width // 8) * 4, -(-im.height // 8) * 4), Image.LANCZOS)
    blob = to_dds(im, fmt)
    with open(path, "wb") as f:
        f.write(blob)
    return im.size, len(blob)


def info(path):
    b = open(path, "rb").read()
    size, flags, h, w, pitch, depth, mips = struct.unpack_from("<7I", b, 4)
    pf = struct.unpack_from("<2I4s5I", b, 76)
    caps = struct.unpack_from("<4I", b, 108)
    dx10 = struct.unpack_from("<5I", b, 128) if pf[2] == b"DX10" else None
    return dict(bytes=len(b), w=w, h=h, flags=hex(flags), pitch=pitch, depth=depth, mips=mips,
                fourcc=pf[2].decode(), caps=hex(caps[0]), dx10=dx10)


def check(path, ref_png):
    """Decode our DDS with Pillow and return the mean absolute RGBA error vs the source image (0..255)."""
    blob = bytearray(open(path, "rb").read())
    if blob[84:88] == b"DX10" and blob[128] in (78, 29):   # Pillow cannot open the sRGB DXGI ids; same payload
        blob[128] -= 1
    a = Image.open(io.BytesIO(bytes(blob))).convert("RGBA")
    b = Image.open(ref_png).convert("RGBA") if not isinstance(ref_png, Image.Image) else ref_png.convert("RGBA")
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    pa, pb = a.tobytes(), b.tobytes()
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--info"]:
        for p in args[1:]:
            print(p, info(p))
        sys.exit(0)
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    half = "--half" in args
    args = [a for a in args if a != "--half"]
    size, n = write(args[0], args[1], args[2] if len(args) > 2 else "bc3", half)
    print("wrote %s %dx%d %d bytes, mean abs error %.2f" % (args[1], size[0], size[1], n, check(args[1], args[0])))
