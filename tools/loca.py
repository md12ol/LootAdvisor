"""Read-only parser for Larian .loca localization files ("LOCA" magic).

  python loca.py [<pak> [<path-in-pak>]] [--json out.json] [--lookup HANDLE ...]
      defaults: Localization/English.pak, Localization/English/english.loca
      --json   write {handle: text} as JSON
      --lookup print the text of one or more handles
  python loca.py <file.loca> [--json out.json]           loose file

Library use:
    import loca
    texts = loca.load(data_bytes)              # {handle: text}
    texts, versions = loca.load(data, with_versions=True)
    texts = loca.load_english()                # reads english.loca straight from the game's English.pak

Layout (LSLib LocaReader): "LOCA", uint32 count, uint32 texts_offset; count x {char key[64] (NUL padded),
uint16 version, uint32 length}; then the texts back to back, each `length` bytes incl. its NUL terminator.
If a handle occurs more than once the entry with the highest version wins.
Texts contain the game's markup (e.g. <LSTag ...>, <br>, [1] placeholders) unchanged.
"""
import json
import os
import struct
import sys

ENGLISH_PAK = "Localization/English.pak"
ENGLISH_LOCA = "Localization/English/english.loca"


class LocaError(Exception):
    pass


def load(data, with_versions=False):
    if data[:4] != b"LOCA":
        raise LocaError("not a LOCA file (magic %r)" % bytes(data[:4]))
    count, texts_off = struct.unpack_from("<II", data, 4)
    if count and texts_off != 12 + count * 70:
        raise LocaError(f"unexpected texts offset {texts_off} for {count} entries")
    texts, versions = {}, {}
    pos = texts_off
    for i, (key, ver, ln) in enumerate(struct.iter_unpack("<64sHI", data[12:12 + count * 70])):
        handle = key.split(b"\0", 1)[0].decode("utf-8")
        raw = data[pos:pos + ln]
        pos += ln
        if raw.endswith(b"\0"):
            raw = raw[:-1]
        if handle in versions and versions[handle] > ver:
            continue
        texts[handle] = raw.decode("utf-8", "replace")
        versions[handle] = ver
    if pos > len(data):
        raise LocaError("truncated LOCA file")
    return (texts, versions) if with_versions else texts


def load_english(game_data=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pak import Pak, GAME_DATA
    p = Pak(os.path.join(game_data or GAME_DATA, ENGLISH_PAK))
    try:
        return load(p.read(p.by_name[ENGLISH_LOCA]))
    finally:
        p.close()


def main(argv):
    args = argv[1:]
    out, lookups = None, []
    if "--json" in args:
        i = args.index("--json")
        out = args[i + 1]
        del args[i:i + 2]
    if "--lookup" in args:
        i = args.index("--lookup")
        lookups = args[i + 1:]
        del args[i:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(args) == 1 and os.path.isfile(args[0]) and args[0].lower().endswith(".loca"):
        with open(args[0], "rb") as f:
            data = f.read()
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pak import Pak, GAME_DATA
        pak_path = args[0] if args else ENGLISH_PAK
        if not os.path.exists(pak_path):
            pak_path = os.path.join(GAME_DATA, pak_path)
        inner = args[1] if len(args) > 1 else ENGLISH_LOCA
        p = Pak(pak_path)
        data = p.read(p.by_name[inner])
    texts = load(data)
    for h in lookups:
        print(f"{h}: {texts.get(h, '<missing>')}")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(texts, f, ensure_ascii=False, indent=0)
        print(f"wrote {len(texts)} entries to {out}")
    elif not lookups:
        print(f"{len(texts)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
