"""Validate lsf.py / loca.py against the installed game (read-only).

  python validate_parsers.py [--seed N]

Parses every Public/*/RootTemplates/_merged.lsf in Shared/Gustav/GustavX/Patch8 hotfix paks, 50 random level
Items/_merged.lsf, 200 random .lsf from Gustav.pak, english.loca; then cross-checks root template Stats against
Stats/Generated/Data/*.txt entry names and DisplayName handles against english.loca. Prints counts and failures.
"""
import collections
import os
import random
import re
import struct
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loca  # noqa: E402
import lsf  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Patch8_HotFix10.pak"]
LEVEL_ITEMS = re.compile(r"^Mods/[^/]+/Levels/[^/]+/Items/_merged\.lsf$")
ROOT_TEMPLATES = re.compile(r"^Public/([^/]+)/RootTemplates/_merged\.lsf$")
STATS_TXT = re.compile(r"^Public/[^/]+/Stats/Generated/Data/[^/]+\.txt$")
PROBE = "c9ebcfae-8c9a-4acc-8a30-da7830b32121"


def header(data):
    ver = struct.unpack_from("<I", data, 4)[0]
    off = 16 if ver >= 5 else 12
    flags = data[off + (40 if ver >= 6 else 32)]
    return ver, flags & 0x0F, flags & 0xF0


def main(argv):
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 1
    rng = random.Random(seed)
    fails = []
    stats = collections.Counter()
    fmt = collections.Counter()
    paks = {n: Pak(os.path.join(GAME_DATA, n)) for n in PAKS}

    def parse(pk, e, tag):
        data = paks[pk].read(e)
        try:
            fmt[header(data)] += 1
            r = lsf.load(data)
            stats[tag + "_ok"] += 1
            stats[tag + "_nodes"] += sum(1 for reg in r.regions for _ in reg.iter())
            return r
        except Exception as ex:  # report, keep going
            stats[tag + "_fail"] += 1
            fails.append((tag, pk, e.name, repr(ex)))
            traceback.print_exc()
            return None

    t0 = time.time()
    # 1. root templates
    templates = {}
    for pk in PAKS:
        for e in paks[pk].entries:
            m = ROOT_TEMPLATES.match(e.name)
            if not m:
                continue
            r = parse(pk, e, "roottemplates")
            if r is None:
                continue
            gos = [g for reg in r.regions for g in reg.children]
            n_items = sum(1 for g in gos if g.get("Type") == "item")
            print(f"  {pk:22s} {e.name:50s} {len(gos):6d} GameObjects, {n_items:5d} items")
            for g in gos:
                templates[g.get("MapKey")] = (pk, g)
    print(f"root templates: {len(templates)} unique MapKeys  ({time.time() - t0:.1f}s)")

    # 2. 50 random level item files (all paks)
    lvl = [(pk, e) for pk in PAKS for e in paks[pk].entries if LEVEL_ITEMS.match(e.name)]
    print(f"level item files available: {len(lvl)}")
    for pk, e in rng.sample(lvl, min(50, len(lvl))):
        parse(pk, e, "levelitems")

    # 3. 200 random .lsf from Gustav.pak
    allf = [e for e in paks["Gustav.pak"].entries if e.name.endswith(".lsf")]
    print(f"Gustav.pak .lsf files: {len(allf)}")
    for e in rng.sample(allf, 200):
        parse("Gustav.pak", e, "random")

    # 4. loca
    t = time.time()
    texts = loca.load_english()
    print(f"english.loca: {len(texts)} handles ({time.time() - t:.1f}s)")

    # 5. cross checks
    stat_names = {}
    for pk in PAKS:
        for e in paks[pk].entries:
            if STATS_TXT.match(e.name):
                for m in re.finditer(rb'^new entry "([^"]+)"', paks[pk].read(e), re.M):
                    stat_names.setdefault(m.group(1).decode(), e.name)
    weapon_names = {k for k, v in stat_names.items() if v.endswith("/Weapon.txt")}
    items = [g for _, g in templates.values() if g.get("Type") == "item"]
    with_stats = [g for g in items if g.get("Stats")]
    stats_hit = [g for g in with_stats if g.get("Stats") in stat_names]
    weap_hit = [g for g in with_stats if g.get("Stats") in weapon_names]
    unknown = "ls::TranslatedStringRepository::s_HandleUnknown"
    dn_all = [g.get("DisplayName")["handle"] for g in items if g.get("DisplayName") and g.get("DisplayName")["handle"]]
    dn = [h for h in dn_all if h != unknown]
    print(f"item DisplayNames set to s_HandleUnknown (no text by design): {len(dn_all) - len(dn)}")
    dn_hit = [h for h in dn if h in texts]
    print(f"stats entries in *.txt: {len(stat_names)} (Weapon.txt: {len(weapon_names)})")
    print(f"item templates: {len(items)}; with own Stats: {len(with_stats)}; Stats found in txt: {len(stats_hit)}; "
          f"of which Weapon.txt: {len(weap_hit)}")
    missing = sorted({g.get('Stats') for g in with_stats} - set(stat_names))
    print(f"  Stats values not found in any txt ({len(missing)}): {missing[:15]}")
    print(f"item DisplayName handles: {len(dn)}; resolved in english.loca: {len(dn_hit)}")
    probe = templates.get(PROBE)
    if probe:
        g = probe[1]
        dn_h = (g.get("DisplayName") or {}).get("handle")
        print(f"probe {PROBE} [{probe[0]}]: Name={g.get('Name')} Stats={g.get('Stats')} "
              f"(in Weapon.txt: {g.get('Stats') in weapon_names}) DisplayName={dn_h} -> {texts.get(dn_h)!r}")
    else:
        print(f"probe {PROBE}: NOT FOUND among root templates")
    ls = [g for g in weap_hit if "Longsword" in g.get("Stats", "")][:3]
    for g in ls:
        h = (g.get("DisplayName") or {}).get("handle")
        print(f"  longsword sample: {g.get('MapKey')} {g.get('Name')} Stats={g.get('Stats')} -> {texts.get(h)!r}")

    print("\nLSF formats seen (version, compression method, level flags):", dict(fmt))
    print("counts:", dict(stats))
    print(f"FAILURES: {len(fails)}")
    for f in fails:
        print("  ", f)
    print(f"total {time.time() - t0:.1f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
