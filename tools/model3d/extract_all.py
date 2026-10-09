"""Extract + convert the game files for EVERY visual in catalog.json (step 2 of the all-sets build, 3D_ALL.md).

  python tools/model3d/extract_all.py [--vt-size 512] [--only-anims]

Writes into data/cache/model3d/work/ (files already present are skipped; delete to redo):
  gr2/<name>.GR2 -> glb/<name>.glb      meshes (LSLib Divine convert-model, GR2 -> glTF binary, skinned)
  skel/<name>.glb                        each origin's skeleton (BaseVisual SkeletonResource)
  anim/<rig>_<stance>.dae + poses.json   idle animations (Divine GR2 -> Collada); frame 0 = the pose we show
  vt/<gtex>_L0|1|2.dds                   virtual texture layers, one VtBatch call per tile set (the .gts is parsed
                                         once; page files are deleted after each tile set)
  dds/<name>.DDS                         plain textures (tint masks, skin maps, gradients)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from pak import GAME_DATA, Pak  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(ROOT, "data", "cache", "model3d")
WORK = os.path.join(CACHE, "work")
LSLIB = os.path.join(ROOT, "third_party", "lslib", "Packed", "Tools")
DIVINE = os.path.join(LSLIB, "Divine.exe")
VTB = os.path.join(HERE, "lshelper", "VtBatch.dll")
# animation rig per skeleton prefix when the race has no animations of its own (half-elves and tieflings use the
# human rigs of the same body type)
RIG_FALLBACK = {"HEL": "HUM", "TIF": "HUM"}
STANCES = ["DFLT", "1HS", "1HP", "1HSSH", "1HPSH", "2H", "2HS", "DWS", "DWP", "DWXBS", "XB", "XBS", "BOW", "ST",
           "POLE", "JAV", "JAVSH", "SL"]


def divine(src, dst, out_fmt):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    r = subprocess.run([DIVINE, "-g", "bg3", "-a", "convert-model", "-s", src, "-d", dst, "-i", "gr2", "-o", out_fmt],
                       capture_output=True, text=True, cwd=os.path.dirname(LSLIB))  # granny2.dll sits in Packed/
    return r.returncode == 0 and os.path.exists(dst), (r.stdout + r.stderr).strip()[-300:]


def gr2_name(path):
    return os.path.splitext(os.path.basename(path))[0]


class Files:
    def __init__(self, names):
        self.files = {}
        for n in names:
            p = Pak(os.path.join(GAME_DATA, n))
            for e in p.entries:
                self.files.setdefault(e.name.lower(), (p, e))

    def get(self, path):
        return self.files.get(path.lower()) or self.files.get(("Generated/" + path).lower())

    def extract(self, path, dest):
        if os.path.exists(dest):
            return True
        hit = self.get(path)
        if not hit:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as f:
            f.write(hit[0].read(hit[1]))
        os.replace(dest + ".part", dest)
        return True


def anim_rig(skeleton_path):
    base = os.path.basename(skeleton_path).split("_Base")[0]      # ELF_M, HEL_F, TIF_FS
    race, body = base.split("_", 1)
    return base, RIG_FALLBACK.get(race, race) + "_" + body


def main(argv):
    t0 = time.time()
    vt_size = int(argv[argv.index("--vt-size") + 1]) if "--vt-size" in argv else 512
    cat = json.load(open(os.path.join(CACHE, "catalog.json"), encoding="utf-8"))
    F = Files(["Models.pak", "Textures.pak", "VirtualTextures.pak"])
    log = {"gr2_fail": [], "vt_fail": [], "dds_missing": [], "anim_missing": []}

    # ---- skeletons + idle animations
    models = Pak(os.path.join(GAME_DATA, "Models.pak"))
    anim_index = {}
    for e in models.entries:
        m = re.search(r"/([A-Z]{3}_[A-Z]{1,2})_Rig_([A-Z0-9]+)_IDLE_Still_(Combat|Peace)_01\.GR2$", e.name)
        if m and "/_Anims/" in e.name:
            anim_index.setdefault((m.group(1), m.group(2), m.group(3)), e.name)
    rigs = {}
    for char, c in cat["chars"].items():
        sk = c["skeleton"]
        base, rig = anim_rig(sk)
        name = gr2_name(sk)
        src = os.path.join(WORK, "skel", name + ".GR2")
        dst = os.path.join(WORK, "skel", name + ".glb")
        if F.extract(sk, src) and not os.path.exists(dst):
            ok, msg = divine(src, dst, "glb")
            print("  skeleton", name, ok, "" if ok else msg)
        rigs[rig] = 1
    for rig in rigs:
        for st in STANCES:
            for mode in ("Combat", "Peace"):
                path = anim_index.get((rig, st, mode))
                if not path:
                    continue
                src = os.path.join(WORK, "anim", os.path.basename(path))
                dst = os.path.join(WORK, "anim", f"{rig}_{st}_{mode}.dae")
                if F.extract(path, src) and not os.path.exists(dst):
                    ok, msg = divine(src, dst, "dae")
                    if not ok:
                        log["anim_missing"].append(path)
    print("animations done %.0fs" % (time.time() - t0))
    if "--only-anims" in argv:
        return

    # ---- meshes
    gtex, dds = {}, {}
    names = {}
    for vid, v in cat["visuals"].items():
        if not v.get("gr2"):
            continue
        name = gr2_name(v["gr2"])
        if names.setdefault(name, v["gr2"]) != v["gr2"]:
            print("  ! GR2 name clash:", name, v["gr2"], names[name])
        src = os.path.join(WORK, "gr2", name + ".GR2")
        dst = os.path.join(WORK, "glb", name + ".glb")
        if F.extract(v["gr2"], src) and not os.path.exists(dst):
            ok, msg = divine(src, dst, "glb")
            if not ok:
                log["gr2_fail"].append([name, msg])
                print("  convert FAIL", name, msg)
        for m in v.get("materials", []):
            for t in m.get("virtual_textures", []):
                if t.get("gtex") and t.get("vt_files"):
                    gtex[t["gtex"]] = t["vt_files"][0]
            for t in m.get("textures", []):
                if t.get("file"):
                    dds[t["file"]] = 1
    print("meshes done: %d GR2 %.0fs" % (len(names), time.time() - t0))

    # ---- plain textures
    for path in dds:
        if not F.extract(path, os.path.join(WORK, "dds", os.path.basename(path))):
            log["dds_missing"].append(path)
    print("dds done: %d %.0fs" % (len(dds), time.time() - t0))

    # ---- virtual textures, grouped by tile set
    groups = {}
    for g, page in gtex.items():
        if os.path.exists(os.path.join(WORK, "vt", g + "_L0.dds")):
            continue
        gts = os.path.basename(page).rsplit("_", 1)[0] + ".gts"
        groups.setdefault(gts, []).append((g, page))
    vtdir = os.path.join(WORK, "vtsrc")
    os.makedirs(os.path.join(WORK, "vt"), exist_ok=True)
    for i, (gts, items) in enumerate(sorted(groups.items())):
        os.makedirs(vtdir, exist_ok=True)
        F.extract("Generated/Public/VirtualTextures/" + gts, os.path.join(vtdir, gts))
        lst = os.path.join(vtdir, "list.txt")
        with open(lst, "w") as f:
            for g, page in items:
                F.extract(page, os.path.join(vtdir, os.path.basename(page)))
                f.write(f"{g} {vt_size} {os.path.join(WORK, 'vt', g)}\n")
        r = subprocess.run(["dotnet", VTB, LSLIB, os.path.join(vtdir, gts), vtdir, lst], capture_output=True, text=True)
        fails = [ln for ln in r.stdout.splitlines() if ln.startswith("fail")]
        log["vt_fail"] += fails + ([r.stderr.strip()[-300:]] if r.returncode else [])
        print(f"  vt {i + 1}/{len(groups)} {gts}: {len(items)} textures, {len(fails)} failed, rc={r.returncode} "
              f"{time.time() - t0:.0f}s", flush=True)
        shutil.rmtree(vtdir, ignore_errors=True)
    with open(os.path.join(WORK, "extract_log.json"), "w") as f:
        json.dump(log, f, indent=1)
    print("done %.0fs:" % (time.time() - t0), {k: len(v) for k, v in log.items()})


if __name__ == "__main__":
    main(sys.argv)
