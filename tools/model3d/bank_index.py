"""Index the game's resource banks (read-only on the game folder).

  python tools/model3d/bank_index.py            -> data/cache/model3d/banks.json

Scans every Public/*/Content/**/_merged.lsf in the data paks (later paks override earlier ones, like the game)
and keeps the banks a 3D export needs, keyed by resource ID:
  CharacterVisualBank  character visuals (BaseVisual, BodySetVisual, Slots -> VisualResource, material overrides)
  VisualBank           mesh resources (SourceFile = .GR2 in Models.pak, Objects -> MaterialID per mesh object)
  MaterialBank         materials (shader SourceFile, Texture2D / VirtualTexture / scalar / vector parameters)
  TextureBank          DDS textures (SourceFile in Textures*.pak)
  VirtualTextureBank   virtual textures (GTexFileName -> VirtualTextures*.pak tiles)
  MaterialPresetBank   material presets (skin / hair / eye colours of origin characters)
  SkeletonBank         skeletons (SourceFile = .GR2 with all bones incl. Dummy_* attachment bones)
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import lsf  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

PAKS = ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Patch8_HotFix10.pak"]
BANKS = {"CharacterVisualBank", "VisualBank", "MaterialBank", "TextureBank", "VirtualTextureBank",
         "MaterialPresetBank", "SkeletonBank"}
CONTENT = re.compile(r"^Public/[^/]+/Content/.*_merged\.lsf$")
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "cache", "model3d", "banks.json")


def main():
    t = time.time()
    banks = {b: {} for b in BANKS}
    nfiles = 0
    for pk in PAKS:
        p = Pak(os.path.join(GAME_DATA, pk))
        for e in p.entries:
            if not CONTENT.match(e.name):
                continue
            try:
                res = lsf.load(p.read(e))
            except Exception as ex:  # noqa: BLE001
                print("skip", pk, e.name, ex)
                continue
            nfiles += 1
            for reg in res.regions:
                if reg.name not in BANKS:
                    continue
                for r in reg.children:
                    rid = r.get("ID")
                    if rid:
                        j = lsf.to_json(r, typed=False)
                        j["_pak"] = pk
                        j["_file"] = e.name
                        banks[reg.name][rid] = j
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(banks, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{nfiles} bank files, " + ", ".join(f"{k}={len(v)}" for k, v in banks.items()),
          f"-> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB, {time.time() - t:.0f}s)")


if __name__ == "__main__":
    main()
