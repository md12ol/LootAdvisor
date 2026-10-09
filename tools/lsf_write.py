"""Writer for Larian LSF binary resources ("LSOF"), the counterpart of lsf.py (which only reads).

  python lsf_write.py <in.lsx> <out.lsf>          convert an LSX (XML) resource to LSF v7 (uncompressed, like the
                                                   game's own GUI/metadata.lsf files)
  python lsf_write.py --test [N]                   round-trip test on real game files (see test() below)

Library use:
    import lsf, lsf_write
    res = lsf.load(data)                           # or lsf_write.from_lsx(text)
    blob = lsf_write.dump(res)                     # -> bytes (LSF v7, engine 4.0.9.319, no compression)
    blob = lsf_write.dump(res, extended=True)      # node/attribute "KeysAndAdjacency" layout (MetadataFormat 1)

What is written (format reference: Norbyte's LSLib, LSLib/LS/Resources/LSF/*.cs, mirrored from lsf.py):
  header   "LSOF", u32 version (7), i64 packed engine version, LSFMetadataV6 (10 x u32 sizes, u8 compression flags,
           u8, u16, u32 MetadataFormat); all sections stored uncompressed (SizeOnDisk = 0), which is what the game's
           GUI metadata files use (checked: every */GUI/metadata.lsf in Game/Gustav/GustavX/Shared/DiceSet paks).
  sections strings (512-bucket name hash table), nodes, attributes, values, keys - in that order on disk.
  nodes    MetadataFormat 0: {u32 name (bucket<<16|index), i32 firstAttr, i32 parent}
           MetadataFormat 1: {u32 name, i32 parent, i32 nextSibling, i32 firstAttr}
  attrs    MetadataFormat 0: {u32 name, u32 type|length<<6, i32 node}           (values consecutive)
           MetadataFormat 1: {u32 name, u32 type|length<<6, i32 nextAttr, u32 valueOffset}
The bucket of a name only matters for lookup tables inside LSLib; readers address names by (bucket, index), so any
deterministic bucket choice is valid. `bucket_of` lets a caller reproduce another file's layout (used by the
byte-exact test).
"""
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsf  # noqa: E402

TYPE_IDS = {v: k for k, v in lsf.TYPE_NAMES.items()}
# LSX type names that differ from lsf.TYPE_NAMES (LSLib's AttributeTypeMaps, BG3 names -> ids)
LSX_TYPES = {
    "uint8": 1, "int16": 2, "uint16": 3, "int32": 4, "uint32": 5, "float": 6, "double": 7,
    "ivec2": 8, "ivec3": 9, "ivec4": 10, "fvec2": 11, "fvec3": 12, "fvec4": 13,
    "mat2x2": 14, "mat3x3": 15, "mat3x4": 16, "mat4x3": 17, "mat4x4": 18, "bool": 19,
    "string": 20, "path": 21, "FixedString": 22, "LSString": 23, "uint64": 24, "ScratchBuffer": 25,
    "old_int64": 26, "int8": 27, "TranslatedString": 28, "WString": 29, "LSWString": 30, "guid": 31,
    "int64": 32, "TranslatedFSString": 33,
}
NAME_BUCKETS = 512
DEFAULT_ENGINE = (4, 0, 9, 319)   # what every BG3 GUI metadata.lsf carries


def pack_engine_version(major, minor, revision, build):
    return (major << 55) | (minor << 47) | (revision << 31) | build


def default_bucket(name):
    h = zlib.crc32(name.encode("utf-8"))
    return ((h & 0x1FF) ^ ((h >> 9) & 0x1FF) ^ ((h >> 18) & 0x1FF) ^ ((h >> 27) & 0x1FF)) % NAME_BUCKETS


def guid_bytes(s):
    """GUID text (LSLib ByteSwapGuids form, as lsf.guid_str prints it) -> 16 raw bytes."""
    h = s.replace("-", "")
    if len(h) != 32:
        raise ValueError("bad guid %r" % s)
    d1, d2, d3 = int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16)
    t = bytes.fromhex(h[16:32])
    t = bytes((t[1], t[0], t[3], t[2], t[5], t[4], t[7], t[6]))
    return struct.pack("<IHH", d1, d2, d3) + t


def _lstr(s):
    b = s.encode("utf-8") + b"\0"
    return struct.pack("<i", len(b)) + b


def _tfs(v, version):
    out = bytearray()
    if version >= lsf.VER_BG3:
        out += struct.pack("<H", int(v.get("version", 0)))
    else:
        out += _lstr(v.get("value", ""))
    out += _lstr(v.get("handle", ""))
    args = v.get("arguments", [])
    out += struct.pack("<i", len(args))
    for a in args:
        out += _lstr(a["key"])
        out += _tfs(a["string"], version)
        out += _lstr(a["value"])
    return bytes(out)


def encode_value(tid, v, version=7):
    if tid in lsf._STRING_TYPES:
        return (v or "").encode("utf-8") + b"\0"
    f = lsf._SCALAR.get(tid)
    if f is not None:
        return struct.pack(f, v)
    if tid == 19:
        return b"\1" if v else b"\0"
    if tid == 31:
        return guid_bytes(v)
    vm = lsf._VECMAT.get(tid)
    if vm is not None:
        rows, cols, ef = vm
        flat = v if rows == 1 else [x for r in v for x in r]
        return struct.pack("<%d%s" % (rows * cols, ef), *flat)
    if tid == 28:
        if version >= lsf.VER_BG3:
            return struct.pack("<H", int(v.get("version", 0))) + _lstr(v.get("handle", ""))
        return _lstr(v.get("value", "")) + _lstr(v.get("handle", ""))
    if tid == 33:
        return _tfs(v, version)
    if tid == 25:
        return bytes.fromhex(v or "")
    if tid == 0:
        return b""
    raise ValueError("unsupported attribute type %d" % tid)


class _Names:
    def __init__(self, bucket_of):
        self.buckets = [[] for _ in range(NAME_BUCKETS)]
        self.index = {}
        self.bucket_of = bucket_of or default_bucket

    def add(self, name):
        r = self.index.get(name)
        if r is None:
            b = self.bucket_of(name)
            r = (b << 16) | len(self.buckets[b])
            self.buckets[b].append(name)
            self.index[name] = r
        return r

    def blob(self):
        out = bytearray(struct.pack("<I", NAME_BUCKETS))
        for chain in self.buckets:
            out += struct.pack("<H", len(chain))
            for s in chain:
                b = s.encode("utf-8")
                out += struct.pack("<H", len(b)) + b
        return bytes(out)


def dump(res, version=7, engine=None, extended=False, bucket_of=None):
    """lsf.Resource -> LSF bytes (version 6 or 7, uncompressed)."""
    if version not in (6, 7):
        raise ValueError("only LSF v6/v7 (BG3) are written")
    if engine is None:
        engine = pack_engine_version(*DEFAULT_ENGINE)
    names = _Names(bucket_of)
    # preorder list of (node, parent_index)
    order = []

    def walk(n, parent):
        order.append((n, parent))
        me = len(order) - 1
        for c in n.children:
            walk(c, me)

    for r in res.regions:
        walk(r, -1)

    nodes = bytearray()
    attrs = bytearray()
    values = bytearray()
    keys = bytearray()
    attr_count = 0
    # next sibling index for the extended layout
    next_sib = [-1] * len(order)
    last_child = {}
    for i, (n, p) in enumerate(order):
        if p in last_child:
            next_sib[last_child[p]] = i
        last_child[p] = i
    for i, (n, p) in enumerate(order):
        nh = names.add(n.name)
        first = attr_count if n.attrs else -1
        items = list(n.attrs.items())
        for j, (aname, (tname, val)) in enumerate(items):
            tid = TYPE_IDS.get(tname)
            if tid is None:
                tid = int(tname)
            data = encode_value(tid, val, version)
            ah = names.add(aname)
            tl = tid | (len(data) << 6)
            if extended:
                nxt = attr_count + 1 if j + 1 < len(items) else -1
                attrs += struct.pack("<IIiI", ah, tl, nxt, len(values))
            else:
                attrs += struct.pack("<IIi", ah, tl, i)
            values += data
            attr_count += 1
        if extended:
            nodes += struct.pack("<Iiii", nh, p, next_sib[i], first)
        else:
            nodes += struct.pack("<Iii", nh, first, p)
        if n.key:
            keys += struct.pack("<II", i, names.add(n.key))
    strings = names.blob()
    head = b"LSOF" + struct.pack("<Iq", version, engine)
    meta = struct.pack("<10IBBHI", len(strings), 0, len(keys), 0, len(nodes), 0, len(attrs), 0,
                       len(values), 0, 0, 0, 0, 1 if extended else 0)
    return head + meta + strings + bytes(nodes) + bytes(attrs) + bytes(values) + bytes(keys)


# ------------------------------------------------------------------------------------------------ LSX input
def _lsx_value(tid, a):
    v = a.get("value")
    if tid in lsf._STRING_TYPES:
        return v or ""
    if tid in (6, 7):
        return float(v)
    if tid == 19:
        return v.strip().lower() in ("true", "1")
    if tid in lsf._SCALAR:
        return int(v)
    if tid == 31:
        return v
    vm = lsf._VECMAT.get(tid)
    if vm is not None:
        rows, cols, ef = vm
        nums = [float(x) if ef == "f" else int(x) for x in re.split(r"[\s,]+", v.strip())]
        return nums if rows == 1 else [nums[r * cols:(r + 1) * cols] for r in range(rows)]
    if tid in (28, 33):
        out = {"handle": a.get("handle", ""), "version": int(a.get("version", "0"))}
        if tid == 33:
            out["arguments"] = []
        return out
    if tid == 25:
        import base64
        return base64.b64decode(v or "").hex()
    return None


def from_lsx(text):
    """LSX XML text -> lsf.Resource (regions -> nodes -> attributes)."""
    root = ET.fromstring(text)
    regions = []

    def conv(xn, parent):
        n = lsf.Node(xn.get("id"), parent)
        if xn.get("key"):
            n.key = xn.get("key")
        for a in xn.findall("attribute"):
            t = a.get("type")
            tid = LSX_TYPES.get(t, TYPE_IDS.get(t))
            if tid is None:
                tid = int(t)
            n.attrs[a.get("id")] = (lsf.TYPE_NAMES[tid], _lsx_value(tid, a))
        ch = xn.find("children")
        if ch is not None:
            for c in ch.findall("node"):
                n.children.append(conv(c, n))
        return n

    for reg in root.findall("region"):
        top = reg.findall("node")
        if len(top) != 1:
            raise ValueError("region %s: expected one top node" % reg.get("id"))
        regions.append(conv(top[0], None))
    return lsf.Resource(7, pack_engine_version(*DEFAULT_ENGINE), regions)


# ------------------------------------------------------------------------------------------------ tests
def _names_layout(blob):
    """name -> bucket, read from an LSF file's (uncompressed) strings section."""
    (s_u, s_d) = struct.unpack_from("<II", blob, 16)
    if s_d:
        return None
    s = blob[64:64 + s_u]
    out = {}
    (n,) = struct.unpack_from("<I", s, 0)
    pos = 4
    for b in range(n):
        (c,) = struct.unpack_from("<H", s, pos)
        pos += 2
        for _ in range(c):
            (ln,) = struct.unpack_from("<H", s, pos)
            out[s[pos + 2:pos + 2 + ln].decode("utf-8")] = b
            pos += 2 + ln
    return out


def test(sample=150, seed=1):
    import json
    import random
    from pak import Pak, GAME_DATA
    canon = lambda r: json.dumps(lsf.to_json(r)["regions"], ensure_ascii=False)  # tree only (v<6 files become v7)
    files = []
    for pk in ("Game.pak", "Gustav.pak", "GustavX.pak", "Shared.pak", "DiceSet01.pak"):
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            if e.name.lower().endswith(".lsf"):
                files.append((pk, p, e))
    rnd = random.Random(seed)
    meta = [f for f in files if f[2].name.endswith("GUI/metadata.lsf")]
    pick = meta + rnd.sample([f for f in files if f not in meta], min(sample, len(files)))
    ok = exact = tested = 0
    fails = []
    for pk, p, e in pick:
        data = p.read(e)
        try:
            r1 = lsf.load(data)
        except Exception as ex:  # file the reader cannot parse - not a writer problem
            fails.append((e.name, "reader: %s" % ex))
            continue
        tested += 1
        try:
            fmt = struct.unpack_from("<I", data, 60)[0] if r1.version >= 6 else 0
            layout = _names_layout(data) if r1.version >= 6 else None
            bo = (lambda n, L=layout: L[n]) if layout else None
            b1 = dump(r1, version=7 if r1.version < 6 else r1.version, engine=r1.engine_version
                      if r1.version >= 5 else None, extended=(fmt == 1), bucket_of=bo)
            r2 = lsf.load(b1)
            assert canon(r1) == canon(r2), "tree differs after round trip"
            b2 = dump(r2, version=r2.version, engine=r2.engine_version, extended=(fmt == 1), bucket_of=bo)
            assert b1 == b2, "second write not byte-identical"
            for ext in (False, True):     # the other node layout must read back the same too
                assert canon(lsf.load(dump(r1, version=r2.version, engine=r2.engine_version, extended=ext)))                     == canon(r2), "layout %s" % ext
            ok += 1
            if b1 == bytes(data):
                exact += 1
            elif e.name.endswith("GUI/metadata.lsf"):
                raise AssertionError("metadata file not byte-identical")
        except AssertionError as ex:
            fails.append((pk + ":" + e.name, str(ex)))
    print("round trip: %d/%d files OK, %d byte-identical to the game file (%d GUI metadata files incl.)"
          % (ok, tested, exact, len(meta)))
    for f in fails[:20]:
        print("  FAIL", f)
    return not [f for f in fails if not f[1].startswith("reader")]


def main(argv):
    if len(argv) >= 2 and argv[1] == "--test":
        return 0 if test(int(argv[2]) if len(argv) > 2 else 150) else 1
    if len(argv) != 3:
        print(__doc__)
        return 1
    res = from_lsx(open(argv[1], encoding="utf-8-sig").read())
    blob = dump(res)
    back = lsf.load(blob)
    with open(argv[2], "wb") as f:
        f.write(blob)
    print("wrote %s (%d bytes, %d nodes)" % (argv[2], len(blob), sum(1 for r in back.regions for _ in r.iter())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
