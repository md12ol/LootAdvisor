"""Assemble one GLB of a character wearing a set (step 5 of artifact/3D_RESULTS.md).

  python tools/model3d/assemble.py [set_id] [--out PATH] [--tex 1024] [--parts]

Inputs: data/cache/model3d/<set_id>.json (resolve_visuals.py) and work/ (extract_set.py: LSLib glTF per GR2, VT
layers, DDS). Output (default artifact/models/<set_id>.glb): static meshes in the skeleton's bind pose (no skin),
LOD0 objects only, KHR_mesh_quantization (int16 positions, int8 normals), WebP textures (EXT_texture_webp),
PBR materials baked from the game data:
  base colour = VT albedo x item tint (MSKColor family R=cloth G=metal B=leather, template VisualSet overrides
                first, then the material's own values); skin/hair/eyes from the origin's material presets
  normal      = VT normal layer (DirectX -> glTF: green flipped) or the material's normal DDS
  ORM         = VT physical layer (R metal -> B, G roughness -> G)
  emissive    = Glowmap x glow colour
Weapons are attached to the skeleton's sheath bones (Dummy_Sheath_*), aligned on the weapon's Dummy_Sheath node.
--parts also writes one GLB per piece (base + each item) next to it, for size accounting / lazy loading.
"""
import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(ROOT, "data", "cache", "model3d")
WORK = os.path.join(CACHE, "work")

# where sheathed weapons hang (skeleton bone) per equipment slot
SHEATH = {"MainHand": "Dummy_Sheath_Hip_L", "OffHand": "Dummy_Sheath_Hip_R",
          "Ranged": "Dummy_Sheath_Lower_R", "RangedOff": "Dummy_Sheath_Lower_L"}
SKIP_SHADERS = ("Helper_Invisible", "CHAR_Tearline", "Body_Genital")
SKIP_OBJECTS = ("Eyeshadow", "Genital", "Body_Leaf")


# ---------------------------------------------------------------- glTF reading
class Gltf:
    CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
    NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def __init__(self, path):
        d = open(path, "rb").read()
        jl = struct.unpack_from("<I", d, 12)[0]
        self.j = json.loads(d[20:20 + jl])
        o = 20 + jl
        bl = struct.unpack_from("<I", d, o)[0]
        self.bin = d[o + 8:o + 8 + bl]
        self.parent = {}
        for i, n in enumerate(self.j["nodes"]):
            for c in n.get("children", []):
                self.parent[c] = i
        self.byname = {n.get("name"): i for i, n in enumerate(self.j["nodes"])}

    def acc(self, i):
        a = self.j["accessors"][i]
        bv = self.j["bufferViews"][a["bufferView"]]
        dt = np.dtype(self.CT[a["componentType"]])
        nc = self.NC[a["type"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0) or dt.itemsize * nc
        raw = np.frombuffer(self.bin, dtype=np.uint8, count=stride * (a["count"] - 1) + dt.itemsize * nc, offset=off)
        out = np.lib.stride_tricks.as_strided(raw, shape=(a["count"], dt.itemsize * nc), strides=(stride, 1)).copy()
        arr = out.view(dt).reshape(a["count"], nc)
        if a.get("normalized"):
            arr = arr.astype(np.float32) / float(np.iinfo(dt).max)
        return arr

    @staticmethod
    def local(n):
        if "matrix" in n:
            return np.array(n["matrix"], dtype=np.float64).reshape(4, 4).T
        t = n.get("translation", [0, 0, 0])
        x, y, z, w = n.get("rotation", [0, 0, 0, 1])
        s = n.get("scale", [1, 1, 1])
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = r * np.array(s)
        m[:3, 3] = t
        return m

    def world(self, i):
        m = self.local(self.j["nodes"][i])
        while i in self.parent:
            i = self.parent[i]
            m = self.local(self.j["nodes"][i]) @ m
        return m


# ---------------------------------------------------------------- textures
def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def load_img(path, size=None):
    im = Image.open(path).convert("RGBA")
    if size and max(im.size) > size:
        im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


def to_webp(arr, quality=82, alpha=False, lossless=False):
    a = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    im = Image.fromarray(a, "RGBA" if alpha else "RGB") if a.shape[2] in (3, 4) else Image.fromarray(a[..., 0], "L")
    if not alpha and a.shape[2] == 4:
        im = Image.fromarray(a[..., :3], "RGB")
    b = io.BytesIO()
    im.save(b, "WEBP", quality=quality, method=6, lossless=lossless)
    return b.getvalue()


def tex_path(t):
    return os.path.join(WORK, "dds", os.path.basename(t["file"])) if t.get("file") else None


class Baker:
    def __init__(self, man, size):
        self.size = size
        self.man = man
        self.presets = {}
        banks = json.load(open(os.path.join(CACHE, "banks.json"), encoding="utf-8"))["MaterialPresetBank"]
        for group, pid in man["char_visual"].get("material_presets", {}).items():
            r = banks.get(pid)
            if not r:
                continue
            vals = {}
            for c in r["children"][0].get("children", []):
                a = c["attributes"]
                if c["name"] in ("ScalarParameters", "Vector3Parameters"):
                    vals[a.get("Parameter")] = a.get("Value")
            self.presets[group] = vals

    def preset(self, key, default):
        for v in self.presets.values():
            if key in v:
                return v[key]
        return default

    def material(self, m, tints, slot):
        """-> dict(base=RGBA array, alpha_mode, normal, orm, emissive, rough, metal) or None (skip)."""
        shader = os.path.basename(m.get("shader") or "")
        texs = {t["param"]: t for t in m.get("textures", [])}
        vt = (m.get("virtual_textures") or [{}])[0].get("gtex")
        vec = dict(m.get("vectors") or {})
        sc = m.get("scalars") or {}
        S = self.size
        out = {"name": m.get("name"), "alpha": "OPAQUE", "metal": 1.0, "rough": 1.0, "double": False}
        if not shader or m.get("missing") or any(s in shader for s in SKIP_SHADERS):
            return None   # no material: cloth-simulation proxies (*_Cloth_Mesh) and helpers are never drawn
        if "2S" in shader or "Hair" in shader or "Lashes" in shader:
            out["double"] = True
        if vt and os.path.exists(os.path.join(WORK, "vt", vt + "_L0.dds")):
            alb = load_img(os.path.join(WORK, "vt", vt + "_L0.dds"), S)
            nrm = load_img(os.path.join(WORK, "vt", vt + "_L1.dds"), S)
            phy = load_img(os.path.join(WORK, "vt", vt + "_L2.dds"), S)
            col = srgb_to_lin(alb[..., :3])
            mskt = next((t for k, t in texs.items() if k.upper().startswith("MSK") and k != "MSKA"
                         and tex_path(t) and os.path.exists(tex_path(t))), None)
            if mskt:
                msk = load_img(tex_path(mskt), alb.shape[0])[..., :3]
                if msk.shape[:2] != col.shape[:2]:
                    msk = np.asarray(Image.fromarray((msk * 255).astype(np.uint8)).resize(col.shape[1::-1])) / 255.0
                col = col * self.tint_map(msk, vec, tints)
            if "Gradients" in texs:  # gradient-mapped weapon: placeholder colours -> neutral wood / steel
                hsv = np.asarray(Image.fromarray((alb[..., :3] * 255).astype(np.uint8)).convert("HSV")) / 255.0
                lum = col.mean(-1, keepdims=True)
                yellow = ((hsv[..., 0] > 0.08) & (hsv[..., 0] < 0.2) & (hsv[..., 1] > 0.3))[..., None]
                blue = ((hsv[..., 0] > 0.5) & (hsv[..., 0] < 0.72) & (hsv[..., 1] > 0.3))[..., None]
                col = np.where(yellow, lum * srgb_to_lin([0.55, 0.36, 0.24]) * 1.4, col)
                col = np.where(blue, lum * srgb_to_lin([0.62, 0.62, 0.66]) * 1.4, col)
            base = np.concatenate([lin_to_srgb(col), alb[..., 3:4]], -1)
            if "AlphaTest" in shader:
                out["alpha"] = "MASK"
            out["base"] = base
            n = nrm[..., :3].copy()
            n[..., 1] = 1.0 - n[..., 1]
            out["normal"] = n
            orm = np.stack([np.ones_like(phy[..., 0]), phy[..., 1], phy[..., 0]], -1)
            out["orm"] = orm
        elif "Skin" in shader:
            out["base"] = self.skin(texs)
            out["metal"], out["rough"] = 0.0, 0.55
            if "normalmap" in texs and os.path.exists(tex_path(texs["normalmap"])):
                n = load_img(tex_path(texs["normalmap"]), S)[..., :3].copy()
                n[..., 1] = 1.0 - n[..., 1]
                out["normal"] = n
        elif "Hair" in shader:
            t = load_img(tex_path(texs["ID_Depth_Root_Alpha_MSKA"]), S)
            hair = np.array(self.preset("Hair_Color", [0.3, 0.2, 0.1]), np.float32)
            gray = np.array(self.preset("Hair_Graying_Color", hair), np.float32)
            gi = float(self.preset("Graying_Intensity", 0.0)) * 0.35
            c = hair * (1 - gi) + gray * gi
            shade = 0.55 + 0.45 * t[..., 1:2]          # depth channel: darker inside the strands
            col = lin_to_srgb(c[None, None, :] * shade)
            out["base"] = np.concatenate([col, t[..., 3:4]], -1)
            out["alpha"] = "MASK"
            out["metal"], out["rough"] = 0.0, 0.45
        elif "Lashes" in shader:
            t = load_img(tex_path(texs["ID_Depth_Root_Alpha_MSKA"]), 256)
            out["base"] = np.concatenate([np.full(t.shape[:2] + (3,), 0.03, np.float32), t[..., 3:4]], -1)
            out["alpha"] = "MASK"
            out["metal"], out["rough"] = 0.0, 0.8
        elif "Eye" in shader:
            reg = load_img(tex_path(texs["RegionMask"]), 512) if "RegionMask" in texs else None
            sclera = lin_to_srgb(np.array(self.preset("Eyes_ScleraColour", [0.6, 0.55, 0.5])) * 1.8)
            iris = lin_to_srgb(np.array(self.preset("Eyes_IrisSecondaryColour", [0.3, 0.2, 0.1])))
            pupil = np.array([0.02, 0.01, 0.01])
            if reg is not None:
                r, g = reg[..., 0:1], reg[..., 1:2]
                col = sclera * (1 - r) + iris * r
                col = col * (1 - g) + pupil * g
            else:
                col = np.tile(sclera, (64, 64, 1))
            out["base"] = np.concatenate([col, np.ones(col.shape[:2] + (1,))], -1).astype(np.float32)
            out["metal"], out["rough"] = 0.0, 0.15
        elif "Crystal" in shader:
            c = lin_to_srgb(np.array(vec.get("BaseColor", [0.2, 0, 0])) * 2.0)
            out["base"] = np.concatenate([np.tile(c, (4, 4, 1)), np.ones((4, 4, 1))], -1).astype(np.float32)
            out["emissive_factor"] = [float(x) * 0.35 for x in vec.get("InnerColor", [0.5, 0, 0])]
            out["metal"], out["rough"] = 0.0, 0.15
        else:
            out["base"] = np.full((4, 4, 4), 0.6, np.float32)
        # glow
        glow = texs.get("Glowmap") or texs.get("glowmap")
        gcol = vec.get("GlowColour") or vec.get("Glow_Color") or vec.get("GlowColor")
        if glow and gcol and tex_path(glow) and os.path.exists(tex_path(glow)):
            g = load_img(tex_path(glow), 512)[..., 0:1]
            out["emissive"] = lin_to_srgb(g * np.array(gcol, np.float32))
        return out

    @staticmethod
    def tint_map(msk, vec, tints):
        """MSKColor -> per-pixel linear tint (empirical, from mask classes vs. the physical map on 7 items):
        dominant channel = family (R cloth, G metal, B leather); the level channel picks Primary / Secondary /
        Tertiary: cloth -> G (0 / ~0.34 / ~0.5), metal -> R (0 / ~0.34 / ~0.5), leather -> R (<=0.34 / ~0.5 / more)."""
        fam = np.argmax(msk, -1)
        weight = msk.max(-1)                       # how strongly masked at all
        lvl = np.where(fam == 0, msk[..., 1], msk[..., 0])
        sub = np.where(lvl < 0.2, 0, np.where(lvl < 0.42, 1, 2))
        sub = np.where(fam == 2, np.where(lvl < 0.42, 0, np.where(lvl < 0.6, 1, 2)), sub)
        names = [["Cloth_Primary", "Cloth_Secondary", "Cloth_Tertiary"],
                 ["Metal_Primary", "Metal_Secondary", "Metal_Tertiary"],
                 ["Leather_Primary", "Leather_Secondary", "Leather_Tertiary"]]
        out = np.ones(msk.shape, np.float32)
        for f in range(3):
            for s in range(3):
                key = names[f][s]
                v = tints.get(key) or vec.get(key)
                if v is None:
                    continue
                sel = (fam == f) & (sub == s)
                out[sel] = np.array(v, np.float32)
        w = np.clip(weight * 1.6, 0, 1)[..., None]
        return out * w + (1 - w)

    def skin(self, texs):
        hmvy = load_img(tex_path(texs["HMVY"]), 1024) if "HMVY" in texs and os.path.exists(tex_path(texs["HMVY"])) \
            else np.zeros((8, 8, 4), np.float32)
        hemo = float(self.preset("HemoglobinAmount", 0.5))
        mel = float(self.preset("MelaninAmount", 0.3))
        base = srgb_to_lin([0.86, 0.79, 0.76])[None, None, :] * np.ones(hmvy.shape[:2] + (3,), np.float32)
        hc = np.array(self.preset("HemoglobinColor", [0.65, 0.01, 0.01]), np.float32)
        h = (hmvy[..., 0:1] * hemo * 0.45)
        base = base * (1 - h) + base * (0.35 + hc) * h
        base = base * (1 - hmvy[..., 1:2] * mel * 0.6)
        return np.concatenate([lin_to_srgb(base), np.ones(base.shape[:2] + (1,), np.float32)], -1)


# ---------------------------------------------------------------- GLB writing
class GlbWriter:
    def __init__(self):
        self.j = {"asset": {"version": "2.0", "generator": "LootAdvisor assemble.py (game data via LSLib)"},
                  "extensionsUsed": ["KHR_mesh_quantization", "EXT_texture_webp"],
                  "extensionsRequired": ["KHR_mesh_quantization", "EXT_texture_webp"],
                  "buffers": [{}], "bufferViews": [], "accessors": [], "images": [], "textures": [],
                  "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
                  "materials": [], "meshes": [], "nodes": [], "scenes": [{"nodes": []}], "scene": 0}
        self.bin = bytearray()
        self.tex_bytes = 0
        self.mesh_bytes = 0

    def view(self, data, target=None, stride=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        bv = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            bv["target"] = target
        if stride:
            bv["byteStride"] = stride
        self.bin += data
        self.j["bufferViews"].append(bv)
        return len(self.j["bufferViews"]) - 1

    def accessor(self, arr, ctype, typ, normalized=False, target=None, stride=None, minmax=False):
        v = self.view(arr.tobytes(), target, stride)
        a = {"bufferView": v, "componentType": ctype, "count": int(arr.shape[0]), "type": typ}
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"] = [int(x) if ctype != 5126 else float(x) for x in arr.min(0)[:3]]
            a["max"] = [int(x) if ctype != 5126 else float(x) for x in arr.max(0)[:3]]
        self.j["accessors"].append(a)
        self.mesh_bytes += len(arr.tobytes())
        return len(self.j["accessors"]) - 1

    def image(self, data):
        v = self.view(data)
        self.tex_bytes += len(data)
        self.j["images"].append({"bufferView": v, "mimeType": "image/webp"})
        self.j["textures"].append({"sampler": 0, "extensions": {"EXT_texture_webp": {"source": len(self.j["images"]) - 1}}})
        return len(self.j["textures"]) - 1

    def material(self, mb):
        m = {"name": mb["name"] or "mat", "pbrMetallicRoughness": {}}
        pbr = m["pbrMetallicRoughness"]
        alpha = mb["alpha"] == "MASK"
        pbr["baseColorTexture"] = {"index": self.image(to_webp(mb["base"], 82, alpha=alpha))}
        if "orm" in mb:
            pbr["metallicRoughnessTexture"] = {"index": self.image(to_webp(mb["orm"], 80))}
            pbr["metallicFactor"] = 1.0
            pbr["roughnessFactor"] = 1.0
        else:
            pbr["metallicFactor"] = mb["metal"]
            pbr["roughnessFactor"] = mb["rough"]
        if "normal" in mb:
            m["normalTexture"] = {"index": self.image(to_webp(mb["normal"], 88))}
        if "emissive" in mb:
            m["emissiveTexture"] = {"index": self.image(to_webp(mb["emissive"], 80))}
            m["emissiveFactor"] = [1.0, 1.0, 1.0]
        elif "emissive_factor" in mb:
            m["emissiveFactor"] = mb["emissive_factor"]
        if alpha:
            m["alphaMode"] = "MASK"
            m["alphaCutoff"] = 0.5
        if mb["double"]:
            m["doubleSided"] = True
        self.j["materials"].append(m)
        return len(self.j["materials"]) - 1

    def mesh(self, name, pos, nrm, uv, idx, mat):
        lo, hi = pos.min(0), pos.max(0)
        center = (lo + hi) / 2
        half = np.maximum((hi - lo) / 2, 1e-6)
        q = np.zeros((len(pos), 4), np.int16)
        q[:, :3] = np.round((pos - center) / half * 32767).astype(np.int16)
        nn = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        qn = np.zeros((len(nrm), 4), np.int8)
        qn[:, :3] = np.round(nn * 127).astype(np.int8)
        attrs = {"POSITION": self.accessor(q, 5122, "VEC3", True, 34962, 8, minmax=True),
                 "NORMAL": self.accessor(qn, 5120, "VEC3", True, 34962, 4),
                 "TEXCOORD_0": self.accessor(uv.astype(np.float32), 5126, "VEC2", target=34962)}
        # VEC3 accessors over padded VEC4 data: fix min/max to 3 comps (done in accessor) and count stays per vertex
        it = np.uint16 if idx.max() < 65535 else np.uint32
        ia = self.accessor(idx.astype(it).reshape(-1, 1), 5123 if it == np.uint16 else 5125, "SCALAR", target=34963)
        self.j["meshes"].append({"name": name, "primitives": [{"attributes": attrs, "indices": ia, "material": mat}]})
        self.j["nodes"].append({"name": name, "mesh": len(self.j["meshes"]) - 1,
                                "translation": [float(x) for x in center], "scale": [float(x) for x in half]})
        self.j["scenes"][0]["nodes"].append(len(self.j["nodes"]) - 1)

    def save(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"][0]["byteLength"] = len(self.bin)
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin))
        return total


# ---------------------------------------------------------------- assembly
def visual_meshes(v, transform=None):
    """LOD0 mesh objects of one visual -> list of (object name, material id, pos, nrm, uv, idx)."""
    g = Gltf(os.path.join(WORK, "glb", os.path.splitext(os.path.basename(v["gr2"]))[0] + ".glb"))
    wanted = {}
    for o in v["objects"]:
        if o.get("lod", 0) == 0 and o.get("material"):
            wanted[o["object"].split(".")[1]] = o["material"]
    out = []
    for i, n in enumerate(g.j["nodes"]):
        if "mesh" not in n:
            continue
        mesh = g.j["meshes"][n["mesh"]]
        if mesh["name"] not in wanted or any(s in mesh["name"] for s in SKIP_OBJECTS):
            continue
        for p in mesh["primitives"]:
            pos = g.acc(p["attributes"]["POSITION"]).astype(np.float64)
            nrm = g.acc(p["attributes"]["NORMAL"]).astype(np.float64)
            uv = g.acc(p["attributes"]["TEXCOORD_0"]).astype(np.float32)
            idx = g.acc(p["indices"]).reshape(-1)
            if "skin" not in n:            # rigid mesh: apply its node transform
                m = g.world(i)
                pos = pos @ m[:3, :3].T + m[:3, 3]
                nrm = nrm @ m[:3, :3].T
            if transform is not None:
                pos = pos @ transform[:3, :3].T + transform[:3, 3]
                nrm = nrm @ transform[:3, :3].T
            out.append((mesh["name"], wanted[mesh["name"]], pos.astype(np.float32), nrm.astype(np.float32), uv, idx))
    return out, g


def main(argv):
    set_id = next((a for a in argv[1:] if not a.startswith("--") and not a[0].isdigit()
                   and not a.endswith(".glb")), "astarion.thx.a3.1")
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "artifact", "models", set_id + ".glb")
    size = int(argv[argv.index("--tex") + 1]) if "--tex" in argv else 1024
    man = json.load(open(os.path.join(CACHE, f"{set_id}.json"), encoding="utf-8"))
    baker = Baker(man, size)
    skel = Gltf(os.path.join(WORK, "skel", "ELF_M_Base.glb"))  # TODO generator: per-body skeleton from BaseVisual

    c = man["char_visual"]
    occupied = {s for p in man["pieces"] for s in (p.get("equip_slots") or [])}   # e.g. a helmet takes "Hair"
    groups = [("base", None, v, {}) for v in c["slots"] if v.get("slot") not in occupied]  # head, hair; body: notes
    for p in man["pieces"]:
        for v in p.get("visuals", []):
            groups.append((p["slot"], p, v, p.get("tints") or {}))
    W = GlbWriter()
    parts = {}
    mat_cache = {}
    for slot, piece, v, tints in groups:
        if not v.get("gr2"):
            continue
        transform = None
        if slot in SHEATH:
            wg = Gltf(os.path.join(WORK, "glb", os.path.splitext(os.path.basename(v["gr2"]))[0] + ".glb"))
            sheath = next((i for i, n in enumerate(wg.j["nodes"]) if n.get("name") == "Dummy_Sheath"), None)
            bone = skel.byname.get(SHEATH[slot])
            if sheath is not None and bone is not None:
                transform = skel.world(bone) @ np.linalg.inv(wg.world(sheath))
        meshes, _ = visual_meshes(v, transform)
        mats = {m["id"]: m for m in v["materials"]}
        PW = GlbWriter() if "--parts" in argv else None
        for name, mid, pos, nrm, uv, idx in meshes:
            key = (mid, json.dumps(tints, sort_keys=True))
            if key not in mat_cache:
                mat_cache[key] = baker.material(mats.get(mid, {}), tints, slot)
            mb = mat_cache[key]
            if mb is None:
                continue
            W.mesh(name, pos, nrm, uv, idx, W.material(mb) if ("w", key) not in mat_cache else mat_cache[("w", key)])
            mat_cache[("w", key)] = W.j["meshes"][-1]["primitives"][0]["material"]
            if PW is not None:
                PW.mesh(name, pos, nrm, uv, idx, PW.material(mb))
        if PW is not None and PW.j["meshes"]:
            pname = (piece["sid"] if piece else "base_" + c["name"].split("_")[1].lower()) + "__" + v["name"]
            n = PW.save(os.path.join(os.path.dirname(out), "parts", pname + ".glb"))
            parts[pname] = {"bytes": n, "mesh": PW.mesh_bytes, "tex": PW.tex_bytes, "slot": slot}
    total = W.save(out)
    print(f"{out}: {total/1e6:.2f} MB (mesh {W.mesh_bytes/1e6:.2f} MB, textures {W.tex_bytes/1e6:.2f} MB), "
          f"{len(W.j['meshes'])} meshes, {len(W.j['materials'])} materials")
    if parts:
        for k, p in parts.items():
            print(f"  part {k:70s} {p['bytes']/1e6:6.2f} MB (mesh {p['mesh']/1e6:.2f}, tex {p['tex']/1e6:.2f})")
        json.dump(parts, open(os.path.join(os.path.dirname(out), "parts", "sizes.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv)
