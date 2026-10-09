"""Read-only parser for Larian LSF binary resources ("LSOF" magic, versions 1-7; BG3 paks contain v2-v7).

  python lsf.py <pak> <path-in-pak> [--json out.json]   parse one .lsf inside a pak, print a summary or dump JSON
  python lsf.py <file.lsf> [--json out.json]            same for a loose .lsf file

<pak> may be a bare name (e.g. Shared.pak); it is then looked up in the game's Data folder (pak.GAME_DATA).

Library use:
    import lsf
    res = lsf.load(data_bytes)           # -> Resource
    for region in res.regions:           # top-level nodes (region name == node name)
        for node in region.iter():       # depth-first walk incl. the region itself
            node.name, node.attrs, node.children, node.key
            node.get("Stats")            # attribute value or None
            node.child("Transform")      # first child with that name
    lsf.to_json(res)                     # plain dict, json.dump-able

Attribute values (node.attrs[name] = (type_name, value)):
    ints/floats/bool -> Python scalars, IVec/Vec -> list, Mat* -> list of rows,
    String/FixedString/LSString/Path/WString/LSWString -> str, ScratchBuffer -> hex str,
    UUID -> str formatted like LSLib with ByteSwapGuids (matches GUIDs in .txt/.lsx files),
    TranslatedString -> {"handle", "version"} (+ "value" for pre-BG3 files),
    TranslatedFSString -> same + "arguments": [{"key", "string", "value"}].
Format reference: Norbyte's LSLib (LSLib/LS/Resources/LSF/*.cs).
"""
import json
import os
import struct
import sys
import zlib

import lz4.block
import lz4.frame
import zstandard

TYPE_NAMES = {
    0: "None", 1: "Byte", 2: "Short", 3: "UShort", 4: "Int", 5: "UInt", 6: "Float", 7: "Double",
    8: "IVec2", 9: "IVec3", 10: "IVec4", 11: "Vec2", 12: "Vec3", 13: "Vec4",
    14: "Mat2", 15: "Mat3", 16: "Mat3x4", 17: "Mat4x3", 18: "Mat4", 19: "Bool",
    20: "String", 21: "Path", 22: "FixedString", 23: "LSString", 24: "ULongLong", 25: "ScratchBuffer",
    26: "Long", 27: "Int8", 28: "TranslatedString", 29: "WString", 30: "LSWString", 31: "UUID",
    32: "Int64", 33: "TranslatedFSString",
}
# fixed-size scalar types: id -> struct format
_SCALAR = {1: "<B", 2: "<h", 3: "<H", 4: "<i", 5: "<I", 6: "<f", 7: "<d", 24: "<Q", 26: "<q",
           27: "<b", 32: "<q"}
_STRING_TYPES = {20, 21, 22, 23, 29, 30}
# vector / matrix types: id -> (rows, columns, element format)
_VECMAT = {8: (1, 2, "i"), 9: (1, 3, "i"), 10: (1, 4, "i"), 11: (1, 2, "f"), 12: (1, 3, "f"),
           13: (1, 4, "f"), 14: (2, 2, "f"), 15: (3, 3, "f"), 16: (3, 4, "f"), 17: (4, 3, "f"),
           18: (4, 4, "f")}

VER_CHUNKED = 2        # chunked (LZ4 frame) compression of sub-streams
VER_EXTENDED_NODES = 3
VER_BG3 = 4            # TranslatedString stores a version instead of a value
VER_EXT_HEADER = 5     # 64-bit engine version
VER_NODE_KEYS = 6      # keys section + V6 metadata
MAX_VERSION = 7


class LSFError(Exception):
    pass


class Node:
    __slots__ = ("name", "attrs", "children", "key", "parent")

    def __init__(self, name, parent=None):
        self.name = name
        self.attrs = {}
        self.children = []
        self.key = None
        self.parent = parent

    def get(self, attr, default=None):
        a = self.attrs.get(attr)
        return default if a is None else a[1]

    def child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def children_named(self, name):
        return [c for c in self.children if c.name == name]

    def iter(self):
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def __repr__(self):
        return f"<Node {self.name} attrs={len(self.attrs)} children={len(self.children)}>"


class Resource:
    def __init__(self, version, engine_version, regions):
        self.version = version
        self.engine_version = engine_version
        self.regions = regions          # list of top-level Nodes

    def region(self, name):
        for r in self.regions:
            if r.name == name:
                return r
        return None

    def __repr__(self):
        return f"<Resource v{self.version} regions={[r.name for r in self.regions]}>"


def format_engine_version(v, version=MAX_VERSION):
    if version < VER_EXT_HEADER:  # 32-bit: major<<28 | minor<<24 | revision<<16 | build
        return f"{(v >> 28) & 0xF}.{(v >> 24) & 0xF}.{(v >> 16) & 0xFF}.{v & 0xFFFF}"
    # 64-bit (LSLib PackedVersion): major<<55 | minor<<47 | revision<<31 | build
    return f"{v >> 55}.{(v >> 47) & 0xFF}.{(v >> 31) & 0xFFFF}.{v & 0x7FFFFFFF}"


def guid_str(b):
    """16 raw bytes -> GUID text the way LSLib prints it (ByteSwapGuids on)."""
    d1, d2, d3 = struct.unpack_from("<IHH", b, 0)
    t = b[8:16]
    t = bytes((t[1], t[0], t[3], t[2], t[5], t[4], t[7], t[6]))
    h = t.hex()
    return f"{d1:08x}-{d2:04x}-{d3:04x}-{h[:4]}-{h[4:]}"


def _decompress(buf, off, size_on_disk, usize, flags, chunked, what):
    if size_on_disk == 0:
        if usize == 0:
            return b"", off
        return bytes(buf[off:off + usize]), off + usize
    raw = bytes(buf[off:off + size_on_disk])
    off += size_on_disk
    method = flags & 0x0F
    if method == 0:
        out = raw
    elif method == 1:
        out = zlib.decompress(raw)
    elif method == 2:
        if chunked:
            out = lz4.frame.decompress(raw)
        else:
            out = lz4.block.decompress(raw, uncompressed_size=usize)
    elif method == 3:
        out = zstandard.ZstdDecompressor().decompress(raw, max_output_size=max(usize, 1))
    else:
        raise LSFError(f"{what}: unknown compression method {method}")
    if len(out) != usize:
        raise LSFError(f"{what}: decompressed {len(out)} bytes, expected {usize}")
    return out, off


def _read_names(data):
    names = []
    (n,) = struct.unpack_from("<I", data, 0)
    pos = 4
    for _ in range(n):
        (cnt,) = struct.unpack_from("<H", data, pos)
        pos += 2
        chain = []
        for _ in range(cnt):
            (ln,) = struct.unpack_from("<H", data, pos)
            pos += 2
            chain.append(data[pos:pos + ln].decode("utf-8"))
            pos += ln
        names.append(chain)
    return names


def _cstr(b):
    # strings are NUL-terminated; strip the terminator (and any padding NULs)
    i = b.find(b"\0")
    if i >= 0:
        b = b[:i]
    return b.decode("utf-8", "replace")


class _Values:
    __slots__ = ("d",)

    def __init__(self, d):
        self.d = d

    def lstr(self, pos):
        (ln,) = struct.unpack_from("<i", self.d, pos)
        pos += 4
        return _cstr(self.d[pos:pos + ln]), pos + ln


def _read_tfs(v, pos, version):
    out = {}
    if version >= VER_BG3:
        (out["version"],) = struct.unpack_from("<H", v.d, pos)
        pos += 2
    else:
        out["value"], pos = v.lstr(pos)
    out["handle"], pos = v.lstr(pos)
    (argc,) = struct.unpack_from("<i", v.d, pos)
    pos += 4
    args = []
    for _ in range(argc):
        key, pos = v.lstr(pos)
        sub, pos = _read_tfs(v, pos, version)
        val, pos = v.lstr(pos)
        args.append({"key": key, "string": sub, "value": val})
    out["arguments"] = args
    return out, pos


def _read_value(v, tid, pos, length, version):
    d = v.d
    if tid in _STRING_TYPES:
        return _cstr(d[pos:pos + length])
    f = _SCALAR.get(tid)
    if f is not None:
        return struct.unpack_from(f, d, pos)[0]
    if tid == 19:
        return d[pos] != 0
    if tid == 31:
        return guid_str(d[pos:pos + 16])
    vm = _VECMAT.get(tid)
    if vm is not None:
        rows, cols, ef = vm
        vals = list(struct.unpack_from(f"<{rows * cols}{ef}", d, pos))
        if rows == 1:
            return vals
        return [vals[r * cols:(r + 1) * cols] for r in range(rows)]
    if tid == 28:
        out = {}
        if version >= VER_BG3:
            (out["version"],) = struct.unpack_from("<H", d, pos)
            pos += 2
        else:
            out["value"], pos = v.lstr(pos)
        out["handle"], pos = v.lstr(pos)
        return out
    if tid == 33:
        return _read_tfs(v, pos, version)[0]
    if tid == 25:
        return bytes(d[pos:pos + length]).hex()
    if tid == 0:
        return None
    raise LSFError(f"unsupported attribute type {tid}")


def load(data):
    """Parse LSF bytes -> Resource."""
    mv = memoryview(data)
    if bytes(mv[:4]) != b"LSOF":
        raise LSFError("not an LSF file (magic %r)" % bytes(mv[:4]))
    (version,) = struct.unpack_from("<I", mv, 4)
    if not 1 <= version <= MAX_VERSION:
        raise LSFError(f"unsupported LSF version {version}")
    off = 8
    if version >= VER_EXT_HEADER:
        (engine,) = struct.unpack_from("<q", mv, off)
        off += 8
    else:
        (engine,) = struct.unpack_from("<i", mv, off)
        off += 4
    if version < VER_NODE_KEYS:
        (s_u, s_d, n_u, n_d, a_u, a_d, v_u, v_d, cflags, _u2, _u3, mformat) = \
            struct.unpack_from("<8IBBHI", mv, off)
        off += 40
        k_u = k_d = 0
    else:
        (s_u, s_d, k_u, k_d, n_u, n_d, a_u, a_d, v_u, v_d, cflags, _u2, _u3, mformat) = \
            struct.unpack_from("<10IBBHI", mv, off)
        off += 48
    ch = version >= VER_CHUNKED
    strings, off = _decompress(mv, off, s_d, s_u, cflags, False, "strings")
    nodes_b, off = _decompress(mv, off, n_d, n_u, cflags, ch, "nodes")
    attrs_b, off = _decompress(mv, off, a_d, a_u, cflags, ch, "attributes")
    values_b, off = _decompress(mv, off, v_d, v_u, cflags, ch, "values")
    keys_b = b""
    if version >= VER_NODE_KEYS:
        keys_b, off = _decompress(mv, off, k_d, k_u, cflags, ch, "keys")

    names = _read_names(strings)
    extended = version >= VER_EXTENDED_NODES and mformat == 1  # KeysAndAdjacency

    # nodes: (name_idx, name_off, parent, first_attr)
    if extended:
        node_defs = [(h >> 16, h & 0xFFFF, parent, first)
                     for h, parent, _sib, first in struct.iter_unpack("<Iiii", nodes_b)]
    else:
        node_defs = [(h >> 16, h & 0xFFFF, parent, first)
                     for h, first, parent in struct.iter_unpack("<Iii", nodes_b)]

    # attributes: (name, type, length, data_offset, next)
    attr_defs = []
    if extended:
        for h, tl, nxt, doff in struct.iter_unpack("<IIiI", attrs_b):
            attr_defs.append((names[h >> 16][h & 0xFFFF], tl & 0x3F, tl >> 6, doff, nxt))
    else:
        doff = 0
        last_for_node = {}
        for i, (h, tl, node_idx) in enumerate(struct.iter_unpack("<IIi", attrs_b)):
            ln = tl >> 6
            attr_defs.append([names[h >> 16][h & 0xFFFF], tl & 0x3F, ln, doff, -1])
            doff += ln
            prev = last_for_node.get(node_idx)
            if prev is not None:
                attr_defs[prev][4] = i
            last_for_node[node_idx] = i

    vals = _Values(values_b)
    instances = []
    regions = []
    for name_idx, name_off, parent, first in node_defs:
        if parent == -1:
            node = Node(names[name_idx][name_off])
            regions.append(node)
        else:
            p = instances[parent]
            node = Node(names[name_idx][name_off], p)
            p.children.append(node)
        instances.append(node)
        a = first
        attrs = node.attrs
        while a != -1:
            aname, tid, ln, doff, nxt = attr_defs[a]
            attrs[aname] = (TYPE_NAMES.get(tid, str(tid)), _read_value(vals, tid, doff, ln, version))
            a = nxt

    for node_idx, kn in struct.iter_unpack("<II", keys_b):
        instances[node_idx].key = names[kn >> 16][kn & 0xFFFF]

    return Resource(version, engine, regions)


def node_to_json(node, typed=True):
    out = {"name": node.name}
    if node.key:
        out["key"] = node.key
    if typed:
        out["attributes"] = {k: {"type": t, "value": v} for k, (t, v) in node.attrs.items()}
    else:
        out["attributes"] = {k: v for k, (t, v) in node.attrs.items()}
    if node.children:
        out["children"] = [node_to_json(c, typed) for c in node.children]
    return out


def to_json(res, typed=True):
    """Resource (or Node) -> plain dict. typed=False drops the type names."""
    if isinstance(res, Node):
        return node_to_json(res, typed)
    return {
        "version": res.version,
        "engine_version": format_engine_version(res.engine_version, res.version),
        "regions": [node_to_json(r, typed) for r in res.regions],
    }


def _resolve_pak(path):
    if os.path.exists(path):
        return path
    from pak import GAME_DATA
    return os.path.join(GAME_DATA, path)


def main(argv):
    args = argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json")
        out = args[i + 1]
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 1
    if len(args) == 1:
        with open(args[0], "rb") as f:
            data = f.read()
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pak import Pak
        p = Pak(_resolve_pak(args[0]))
        data = p.read(p.by_name[args[1].replace("\\", "/")])
    res = load(data)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(to_json(res), f, ensure_ascii=False, indent=1)
        print(f"wrote {out}")
    else:
        total = sum(1 for r in res.regions for _ in r.iter())
        print(f"LSF v{res.version}, engine {to_json(res)['engine_version']}, {total} nodes")
        for r in res.regions:
            print(f"  region {r.name}: {len(r.children)} children")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
