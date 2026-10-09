"""Read-only reader for BG3 .pak archives (LSPK version 18).

  python pak.py list    <pak> [substring]          list files (name, size)
  python pak.py extract <pak> <out_dir> [substr...] extract files whose path contains any substring
  python pak.py cat     <pak> <exact path>          print one file to stdout

Library use:  p = Pak(path); for e in p.entries: ...; data = p.read(e)
"""
import os
import struct
import sys
import zlib

import lz4.block
import lz4.frame
import zstandard

GAME_DATA = r"D:\SteamLibrary\steamapps\common\Baldurs Gate 3\Data"


class Entry:
    __slots__ = ("name", "offset", "part", "flags", "size_on_disk", "size")

    def __init__(self, name, offset, part, flags, size_on_disk, size):
        self.name, self.offset, self.part = name, offset, part
        self.flags, self.size_on_disk, self.size = flags, size_on_disk, size


class Pak:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"LSPK":
                raise ValueError(f"{path}: not an LSPK archive")
            version, list_off, list_size, flags, prio = struct.unpack("<IQIBB", f.read(18))
            if version != 18:
                raise ValueError(f"{path}: unsupported pak version {version}")
            f.seek(list_off)
            num_files, comp_size = struct.unpack("<II", f.read(8))
            raw = lz4.block.decompress(f.read(comp_size), uncompressed_size=num_files * 272)
        self.entries = []
        for i in range(num_files):
            name, off1, off2, part, eflags, sod, usize = struct.unpack_from("<256sIHBBII", raw, i * 272)
            name = name.split(b"\0", 1)[0].decode("utf-8", "replace")
            self.entries.append(Entry(name, off1 | (off2 << 32), part, eflags, sod, usize))
        self.by_name = {e.name: e for e in self.entries}
        self._files = {}

    def _part_path(self, part):
        if part == 0:
            return self.path
        base, ext = os.path.splitext(self.path)
        return f"{base}_{part}{ext}"

    def read(self, e):
        f = self._files.get(e.part)
        if f is None:
            f = self._files[e.part] = open(self._part_path(e.part), "rb")
        f.seek(e.offset)
        data = f.read(e.size_on_disk)
        method = e.flags & 0x0F
        if method == 0 or e.size_on_disk == 0:  # stored raw (size field is 0) or empty file
            return data
        if method == 1:
            return zlib.decompress(data)
        if method == 2:
            try:
                return lz4.block.decompress(data, uncompressed_size=e.size)
            except Exception:
                return lz4.frame.decompress(data)
        if method == 3:
            return zstandard.ZstdDecompressor().decompress(data, max_output_size=max(e.size, 1))
        raise ValueError(f"{e.name}: unknown compression {method}")

    def close(self):
        for f in self._files.values():
            f.close()
        self._files.clear()


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    if not os.path.exists(path):
        path = os.path.join(GAME_DATA, path)
    p = Pak(path)
    if cmd == "list":
        sub = argv[3] if len(argv) > 3 else ""
        for e in p.entries:
            if sub in e.name:
                print(f"{e.size or e.size_on_disk:>10}  {e.name}")
    elif cmd == "extract":
        out, subs = argv[3], argv[4:]
        n = 0
        for e in p.entries:
            if subs and not any(s in e.name for s in subs):
                continue
            dst = os.path.join(out, e.name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as g:
                g.write(p.read(e))
            n += 1
        print(f"extracted {n} files to {out}")
    elif cmd == "cat":
        sys.stdout.buffer.write(p.read(p.by_name[argv[3]]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
