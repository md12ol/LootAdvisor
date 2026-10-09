"""Extract + convert the game files of one resolved set (steps 3-4 of artifact/3D_RESULTS.md).

  python tools/model3d/extract_set.py [set_id] [--vt-level N]

Reads data/cache/model3d/<set_id>.json (resolve_visuals.py) and writes into data/cache/model3d/work/:
  gr2/<name>.GR2 -> glb/<name>.glb      LSLib Divine convert-model (GR2 -> glTF binary)
  vt/<gtex>_L0|1|2.dds                  virtual texture layers (albedo / normal / physical) via lshelper/VtExtract
  dds/<name>.DDS                        plain textures (masks, skin maps)
Files already present are skipped (delete work/ to redo).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from pak import GAME_DATA, Pak  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(ROOT, "data", "cache", "model3d")
WORK = os.path.join(CACHE, "work")
LSLIB = os.path.join(ROOT, "third_party", "lslib", "Packed", "Tools")
DIVINE = os.path.join(LSLIB, "Divine.exe")
VTX = os.path.join(HERE, "lshelper", "VtExtract.dll")


def all_visuals(man):
    c = man["char_visual"]
    for v in [c["body"]] + c["slots"]:
        yield v
    for p in man["pieces"]:
        for v in p.get("visuals", []):
            yield v


def main(argv):
    set_id = next((a for a in argv[1:] if not a.startswith("--")), "astarion.thx.a3.1")
    vt_level = int(argv[argv.index("--vt-level") + 1]) if "--vt-level" in argv else 1
    man = json.load(open(os.path.join(CACHE, f"{set_id}.json"), encoding="utf-8"))
    paks = {n: Pak(os.path.join(GAME_DATA, n)) for n in ("Models.pak", "Textures.pak", "VirtualTextures.pak")}
    files = {}
    for p in paks.values():
        for e in p.entries:
            files[e.name.lower()] = (p, e)

    def extract(path, dest):
        if os.path.exists(dest):
            return True
        hit = files.get(path.lower()) or files.get(("Generated/" + path).lower())
        if not hit:
            print("  missing in paks:", path)
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(hit[0].read(hit[1]))
        return True

    gtex, dds = {}, {}
    for v in all_visuals(man):
        if v.get("gr2"):
            name = os.path.splitext(os.path.basename(v["gr2"]))[0]
            src = os.path.join(WORK, "gr2", name + ".GR2")
            dst = os.path.join(WORK, "glb", name + ".glb")
            if extract(v["gr2"], src) and not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                r = subprocess.run([DIVINE, "-g", "bg3", "-a", "convert-model", "-s", src, "-d", dst,
                                    "-i", "gr2", "-o", "glb"], capture_output=True, text=True,
                                   cwd=os.path.dirname(LSLIB))  # granny2.dll (BitKnit GR2) sits in Packed/
                print(f"  convert {name}: rc={r.returncode} {os.path.getsize(dst) if os.path.exists(dst) else 0} B",
                      (r.stdout + r.stderr).strip()[-300:] if r.returncode else "")
        for m in v.get("materials", []):
            for t in m.get("virtual_textures", []):
                if t.get("gtex") and t.get("vt_files"):
                    gtex[t["gtex"]] = t["vt_files"][0]
            for t in m.get("textures", []):
                if t.get("file"):
                    dds[t["file"]] = 1

    for g, page in gtex.items():
        out = os.path.join(WORK, "vt", g)
        if os.path.exists(out + "_L0.dds"):
            continue
        base = os.path.basename(page)                       # Albedo_Normal_Physical_5_<hash>.gtp
        gts_name = base.rsplit("_", 1)[0] + ".gts"
        vtdir = os.path.join(WORK, "vtsrc")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        extract("Generated/Public/VirtualTextures/" + gts_name, os.path.join(vtdir, gts_name))
        extract(page, os.path.join(vtdir, base))
        for lvl in range(vt_level, -1, -1):  # small textures have no lower mip level in the page file
            r = subprocess.run(["dotnet", VTX, LSLIB, os.path.join(vtdir, gts_name), vtdir, g, str(lvl), out],
                               capture_output=True, text=True)
            if r.returncode == 0:
                break
        print(f"  vt {g}: rc={r.returncode}", (r.stdout + r.stderr).strip().replace("\n", " | ")[-400:])

    if "--keep-vt" not in argv:   # the .gts/.gtp sources are ~80 MB per tile set; the layers are extracted now
        import shutil
        shutil.rmtree(os.path.join(WORK, "vtsrc"), ignore_errors=True)
    for path in dds:
        extract(path, os.path.join(WORK, "dds", os.path.basename(path)))
    print("done:", WORK)


if __name__ == "__main__":
    main(sys.argv)
