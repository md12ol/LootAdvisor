"""Check the tint / dye rule against the game's own item icons (3D_ALL.md, upgrade 1).

  python tools/model3d/colour_check.py      -> data/cache/model3d/colour_check.json + summary

For every item of every set: bake its materials with several rule variants, take the UV-covered texels of the LOD0
meshes, average the albedo and compare it with the item's tooltip icon (Game.pak ItemIcons, a render of the same
item by the game). Lighting differs, so both colours are scaled to the same luminance and compared as CIELAB a*b*
(chroma / hue) distance. Lower = closer to the game.
"""
import io
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import meshsrc  # noqa: E402
import shading  # noqa: E402
from pak import GAME_DATA, Pak  # noqa: E402

CACHE = shading.CACHE
VARIANTS = {"spike": ("spike", "explicit_only"), "game_explicit_only": ("game", "explicit_only"),
            "game_preset_then_explicit": ("game", "preset_then_explicit"),
            "game_explicit_then_preset": ("game", "explicit_then_preset")}


def lab(rgb_lin):
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = M @ rgb_lin / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def ab_dist(a, b):
    """CIELAB a*b* distance after scaling both linear colours to luminance 0.2."""
    ya, yb = a @ shading.LUMA, b @ shading.LUMA
    la, lb = lab(a * 0.2 / max(ya, 1e-4)), lab(b * 0.2 / max(yb, 1e-4))
    return float(np.hypot(la[1] - lb[1], la[2] - lb[2]))


def coverage(meshes, size):
    """-> {mesh name: HxW bool mask of the texels its UV triangles cover}."""
    out = {}
    for m in meshes:
        im = Image.new("L", (size, size))
        d = ImageDraw.Draw(im)
        uv = m.uv * size
        for t in m.idx.reshape(-1, 3)[:: max(1, len(m.idx) // 3 // 20000)]:
            d.polygon([tuple(uv[k]) for k in t], fill=255)
        out[m.name] = np.asarray(im) > 0
    return out


def icon(game, name):
    for p in ("Public/Game/GUI/Assets/Tooltips/ItemIcons/%s.DDS" % name,
              "Public/Game/GUI/Assets/ControllerUIIcons/items_png/%s.DDS" % name):
        e = game.by_name.get(p)
        if e:
            im = np.asarray(Image.open(io.BytesIO(game.read(e))).convert("RGBA")).astype(np.float32) / 255
            fg = im[..., 3] > 0.97          # the opaque item only, not the glow halo
            if fg.sum() < 50:
                return None
            return shading.srgb_to_lin(im[..., :3][fg]).mean(0)
    return None


def main():
    cat = json.load(open(os.path.join(CACHE, "catalog.json"), encoding="utf-8"))
    banks = json.load(open(os.path.join(CACHE, "banks.json"), encoding="utf-8"))["MaterialPresetBank"]
    P = shading.Params(banks)
    bakers = {k: shading.Baker(P, 256, rule=r, order=o) for k, (r, o) in VARIANTS.items()}
    game = Pak(os.path.join(GAME_DATA, "Game.pak"))
    items = {}
    for s in cat["sets"].values():
        for p in s["pieces"]:
            if p.get("visuals") and p.get("icon") and p["sid"] not in items:
                items[p["sid"]] = p
    res = []
    for sid, p in sorted(items.items()):
        ic = icon(game, p["icon"])
        if ic is None:
            continue
        acc = {k: [np.zeros(3), 0] for k in VARIANTS}
        tinted = False
        for vid in p["visuals"]:
            v = cat["visuals"][vid]
            if not v.get("gr2"):
                continue
            meshes, _ = meshsrc.load_meshes(os.path.splitext(os.path.basename(v["gr2"]))[0])
            wanted = {o["object"].split(".")[1]: o["material"] for o in v["objects"] if o.get("material")}
            meshes = [m for m in meshes if m.name in wanted]
            cov = coverage(meshes, 256)
            mats = {m["id"]: m for m in v["materials"]}
            for m in meshes:
                mat = mats.get(wanted[m.name])
                if not mat:
                    continue
                if any(t["param"] in ("MSKColor", "MSKcloth", "Gradients") for t in mat.get("textures", [])):
                    tinted = True
                for k, B in bakers.items():
                    r = B.material(mat, p.get("tints"))
                    if r is None or r["base"].shape[0] != 256:
                        continue
                    c = shading.srgb_to_lin(r["base"][..., :3])[cov[m.name]]
                    if len(c):
                        acc[k][0] += c.sum(0)
                        acc[k][1] += len(c)
        if not tinted or acc["spike"][1] == 0:
            continue
        row = {"sid": sid, "name": p["name"], "slot": p["slot"], "icon_lin": ic.round(4).tolist(),
               "has_presets": bool((p.get("tints") or {}).get("presets")),
               "has_vectors": bool((p.get("tints") or {}).get("vectors"))}
        for k, (s_, n) in acc.items():
            mean = s_ / max(n, 1)
            row[k] = round(ab_dist(mean, ic), 2)
        res.append(row)
        print(f"{sid:50s} " + " ".join(f"{k[:22]}={row[k]:5.1f}" for k in VARIANTS), flush=True)
    summ = {}
    for k in VARIANTS:
        d = np.array([r[k] for r in res])
        summ[k] = {"mean_dE_ab": round(float(d.mean()), 2), "median": round(float(np.median(d)), 2),
                   "within_10": int((d < 10).sum()), "n": len(d)}
    for grp in ("has_presets", "has_vectors"):
        sub = [r for r in res if r[grp]]
        summ["only_" + grp] = {k: round(float(np.mean([r[k] for r in sub])), 2) for k in VARIANTS} if sub else {}
    best = {k: sum(1 for r in res if min(VARIANTS, key=lambda x: r[x]) == k) for k in VARIANTS}
    summ["best_count"] = best
    json.dump({"summary": summ, "items": res}, open(os.path.join(CACHE, "colour_check.json"), "w"), indent=1)
    P.save()
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
