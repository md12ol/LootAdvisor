"""Bake the game's material shaders into glTF PBR textures (3D_ALL.md, upgrade 1 "exact colours").

The rules below are read out of the game's own compiled shaders (Materials.pak *.bshd, Vulkan SPIR-V, decompiled with
spirv_dis.py) - not guessed:

  CHAR_BASE*  (MSKColor):  albedo = VT0 * sum_k param_k * w_k,  w_k = clamp((1 - |msk.rgb - key_k| / sqrt(3) - 0.75) * 4)
              keys: Cloth P/S/T/Accent (1,.5,0) (1,0,0) (1,.5,.5) (1,0,.5)
                    Leather P/S/T/Custom_1 (.5,0,1) (0,0,1) (.5,.5,1) (0,.5,1)
                    Metal P/S/T/Custom_2 (0,1,.5) (0,1,0) (.5,1,.5) (.5,1,0)
  CHAR_BASE_MSK* (MSKcloth): albedo = mix(VT0, (C1*m.r + C2*m.g + C3*m.b) * VT0, saturate(m.r+m.g+m.b))
  Base_GradientMapping_2G*:  g = mix(Grad(u=msk.g, row 2i+.5), Grad(u=msk.b, row 2i+1.5), msk.a); albedo = mix(g, VT0, msk.r)
              (implemented in gradient() but NOT used: it does not match the icons, the plain VT albedo does)
  VT layers: L0 albedo (sRGB), L1 normal (tangent x = A, normal = B, bitangent = 1 - G), L2 physical
             (R metallic, G roughness, B occlusion)
  CHAR_Skin_*: hemoglobin / melanin / vein / yellowing model on the HMVY map (see skin()); eyes, hair, lashes: same.
Parameter values: shader BaseValue < MaterialBank value < item dye preset ("02 Colour" MaterialPresets) < the item's
enabled VisualSet overrides; skin / hair / eyes: < the origin's CharacterVisual presets.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(ROOT, "data", "cache", "model3d")
WORK = os.path.join(CACHE, "work")

KEYS = [("Cloth_Primary", (1, .5, 0)), ("Cloth_Secondary", (1, 0, 0)), ("Cloth_Tertiary", (1, .5, .5)),
        ("Accent_Color", (1, 0, .5)), ("Leather_Primary", (.5, 0, 1)), ("Leather_Secondary", (0, 0, 1)),
        ("Leather_Tertiary", (.5, .5, 1)), ("Custom_1", (0, .5, 1)), ("Metal_Primary", (0, 1, .5)),
        ("Metal_Secondary", (0, 1, 0)), ("Metal_Tertiary", (.5, 1, .5)), ("Custom_2", (.5, 1, 0))]
SKIP_SHADERS = ("Helper_Invisible", "CHAR_Tearline", "Body_Genital", "CHAR_Pubes")
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def sat(x):
    return np.clip(x, 0, 1)


def mix(a, b, t):
    return a + (b - a) * t


_img_cache = {}


def load(path, size=None):
    """-> float32 HxWx4 in [0,1] (raw values, no colour-space conversion), resized to size x size if given."""
    key = (path, size)
    if key not in _img_cache:
        if not path or not os.path.exists(path):
            _img_cache[key] = None
        else:
            im = Image.open(path).convert("RGBA")
            if size and im.size != (size, size):
                im = im.resize((size, size), Image.BILINEAR if max(im.size) < size else Image.LANCZOS)
            _img_cache[key] = np.asarray(im).astype(np.float32) / 255.0
            if len(_img_cache) > 64:
                _img_cache.pop(next(iter(_img_cache)))
    return _img_cache[key]


def dds_path(t):
    return os.path.join(WORK, "dds", os.path.basename(t["file"])) if t and t.get("file") else None


class Params:
    """Shader BaseValues from Materials.pak .lsf + preset values from MaterialPresetBank."""
    def __init__(self, banks=None):
        self.banks = banks
        self.shader_cache = {}
        self.presets = {}
        path = os.path.join(CACHE, "shader_defaults.json")
        self.store = json.load(open(path)) if os.path.exists(path) else {}

    def shader_defaults(self, shader):
        name = os.path.splitext(os.path.basename(shader or ""))[0]
        if name in self.store:
            return self.store[name]
        import lsf
        from pak import GAME_DATA, Pak
        if not hasattr(self, "_mpak"):
            self._mpak = Pak(os.path.join(GAME_DATA, "Materials.pak"))
            self._mfiles = {os.path.basename(e.name): e for e in self._mpak.entries if e.name.endswith(".lsf")}
        out = {}
        e = self._mfiles.get(name + ".lsf")
        if e:
            j = lsf.to_json(lsf.load(self._mpak.read(e)).regions[0], typed=False)
            for c in j["children"]:
                a = c["attributes"]
                if c["name"] in ("ScalarParameters", "Vector3Parameters", "Vector4Parameters", "Vector2Parameters"):
                    out[a.get("ParameterName")] = a.get("BaseValue", a.get("Value"))
        self.store[name] = out
        return out

    def save(self):
        with open(os.path.join(CACHE, "shader_defaults.json"), "w") as f:
            json.dump(self.store, f)

    def preset(self, pid):
        if pid in self.presets:
            return self.presets[pid]
        vals = {}
        r = (self.banks or {}).get(pid)
        if r:
            for c in r["children"][0].get("children", []):
                a = c["attributes"]
                if c["name"] in ("ScalarParameters", "Vector3Parameters", "Vector4Parameters") and a.get("Parameter"):
                    vals[a["Parameter"]] = a.get("Value")
        self.presets[pid] = vals
        return vals

    def values(self, m, overrides=None, char_presets=None, order="preset_then_explicit"):
        v = dict(self.shader_defaults(m.get("shader")))
        v.update(m.get("vectors") or {})
        v.update(m.get("scalars") or {})
        ov = overrides or {}
        explicit = dict(ov.get("vectors") or {})
        explicit.update(ov.get("scalars") or {})
        pres = {}
        if ov.get("color_preset"):
            pres.update(self.preset(ov["color_preset"]))
        for pid in (ov.get("presets") or {}).values():
            pres.update(self.preset(pid))
        if order == "preset_then_explicit":
            v.update(pres)
            v.update(explicit)
        elif order == "explicit_then_preset":
            v.update(explicit)
            v.update(pres)
        elif order == "explicit_only":
            v.update(explicit)
        for pid in (char_presets or {}).values():
            v.update(self.preset(pid))
        return v


class Baker:
    def __init__(self, params, size=512, rule="game", order="preset_then_explicit"):
        self.P = params
        self.size = size
        self.rule = rule          # "game" = decompiled shader rules, "spike" = the earlier empirical rule
        self.order = order

    # ------------------------------------------------------------ helpers
    def vt(self, m):
        g = (m.get("virtual_textures") or [{}])[0].get("gtex")
        if not g:
            return None
        p = os.path.join(WORK, "vt", g)
        if not os.path.exists(p + "_L0.dds"):
            return None
        return [load(p + "_L%d.dds" % i, self.size) for i in range(3)]

    def tex(self, texs, *names, size=None):
        for n in names:
            t = texs.get(n)
            if t:
                im = load(dds_path(t), size or self.size)
                if im is not None:
                    if t.get("srgb"):
                        im = np.concatenate([srgb_to_lin(im[..., :3]), im[..., 3:]], -1)
                    return im
        return None

    @staticmethod
    def vt_normal(l1):
        return np.stack([l1[..., 3], 1.0 - l1[..., 1], l1[..., 2]], -1)

    @staticmethod
    def vt_orm(l2):
        return np.stack([l2[..., 2], l2[..., 1], l2[..., 0]], -1)

    @staticmethod
    def vec(v, k, d=(1, 1, 1)):
        x = v.get(k, d)
        if x is None:
            x = d
        return np.array(x if isinstance(x, (list, tuple, np.ndarray)) else [x] * 3, np.float32).reshape(-1)[:3]

    @staticmethod
    def num(v, k, d=0.0):
        x = v.get(k, d)
        return float(x[0] if isinstance(x, (list, tuple)) else x)

    # ------------------------------------------------------------ main entry
    def material(self, m, overrides=None, char_presets=None):
        """-> dict(base RGBA sRGB, normal?, orm?, emissive?, alpha, double, metal, rough) or None (not drawn)."""
        shader = os.path.basename(m.get("shader") or "")
        if not shader or m.get("missing") or any(s in shader for s in SKIP_SHADERS):
            return None
        texs = {t["param"]: t for t in m.get("textures", [])}
        v = self.P.values(m, overrides, char_presets, self.order)
        out = {"name": m.get("name"), "alpha": "OPAQUE", "metal": 1.0, "rough": 1.0,
               "double": "2S" in shader or "Hair" in shader or "Lashes" in shader or "2s" in shader}
        if "AlphaTest" in shader or "Alphatest" in shader:
            out["alpha"] = "MASK"
        layers = self.vt(m)
        if self.rule == "spike" and any(k in shader for k in ("Skin", "Hair", "Lashes", "Eye", "Scalp")):
            return self.spike_base(m, char_presets)
        if "Skin" in shader or "Karlach_Fire" in shader:
            self.skin(shader, texs, v, layers, out)
        elif "CHAR_Hair" in shader or "CHAR_Scalp" in shader:
            self.hair(texs, v, out, scalp="Scalp" in shader)
        elif "Lashes" in shader:
            t = self.tex(texs, "ID_Depth_Root_Alpha_MSKA", size=256)
            if t is None:
                return None
            c = self.vec(v, "Eyelashes_Color", (0, 0, 0)) * (t[..., 0:1] * t[..., 2:3] * self.num(v, "GradientIntensity", 1))
            out.update(base=np.concatenate([lin_to_srgb(c), t[..., 3:4] * self.num(v, "LashesAlphaIntensity", 1)], -1),
                       alpha="BLEND", metal=0.0, rough=0.7)
        elif "Eye" in shader:
            self.eye(texs, v, out)
        elif layers is not None:
            alb, nrm, phy = layers
            col = srgb_to_lin(alb[..., :3])
            if "MSKColor" in texs and self.rule == "game":
                msk = self.tex(texs, "MSKColor", size=alb.shape[0])
                if msk is not None:
                    col = col * self.tint_game(msk[..., :3], v)
            elif "MSKColor" in texs and self.rule == "spike":
                msk = self.tex(texs, "MSKColor", size=alb.shape[0])
                if msk is not None:
                    import assemble
                    tints = {k: v[k] for k, _ in KEYS if k in v}
                    col = col * assemble.Baker.tint_map(msk[..., :3], {}, tints)
            elif "MSKcloth" in texs:
                msk = self.tex(texs, "MSKcloth", size=alb.shape[0])
                if msk is not None:
                    m3 = msk[..., :3]
                    tint = (self.vec(v, "Color_01") * m3[..., 0:1] + self.vec(v, "Color_02") * m3[..., 1:2]
                            + self.vec(v, "Color_03") * m3[..., 2:3])
                    col = mix(col, tint * col, sat(m3.sum(-1, keepdims=True)))
            elif "Gradients" in texs and self.rule == "gradient":
                # the decompiled gradient lookup (gradient()) did NOT match the item icons (37 weapons: mean a*b*
                # distance 14-16 for every row orientation vs 10.6 for the plain albedo), so the plain VT albedo is
                # used; see 3D_ALL.md "gradient weapons"
                col = self.gradient(texs, v, col)
            out["base"] = np.concatenate([lin_to_srgb(col), alb[..., 3:4]], -1)
            out["normal"] = self.vt_normal(nrm)
            out["orm"] = self.vt_orm(phy)
        elif "Crystal" in shader:
            c = lin_to_srgb(self.vec(v, "BaseColor", (0.2, 0, 0)) * 2.0)
            out["base"] = np.concatenate([np.tile(c, (4, 4, 1)), np.ones((4, 4, 1))], -1).astype(np.float32)
            out["emissive_factor"] = [float(x) * 0.35 for x in self.vec(v, "InnerColor", (0.5, 0, 0))]
            out["metal"], out["rough"] = 0.0, 0.15
        else:
            bc = self.tex(texs, "basecolor", "BaseColor", "Body_color_texture")
            if bc is not None:
                c = bc[..., :3]
                for k in ("Color_01", "PrimaryColor", "NonSkinColor"):
                    if k in v and isinstance(v[k], list):
                        c = c * self.vec(v, k)
                        break
                out["base"] = np.concatenate([lin_to_srgb(c), bc[..., 3:4]], -1)
            else:
                c = lin_to_srgb(self.vec(v, "Color_01", (0.4, 0.4, 0.4)) if "Color_01" in v else np.full(3, 0.35))
                out["base"] = np.concatenate([np.tile(c, (4, 4, 1)), np.ones((4, 4, 1))], -1).astype(np.float32)
            out["metal"], out["rough"] = 0.0, 0.8
            nm = self.tex(texs, "normalmap", "NormalMap")
            if nm is not None:
                out["normal"] = self.vt_normal(nm)
            pm = self.tex(texs, "physicalmap")
            if pm is not None:
                out["orm"] = self.vt_orm(pm)
                out["metal"] = out["rough"] = 1.0
        if "base" not in out:
            return None
        # glow (GM shaders): glow map R x glow colour
        glow = self.tex(texs, "Glowmap", "glowmap", "GM", size=256)
        gcol = next((self.vec(v, k) for k in ("GlowColour", "GlowColor", "Glow_Color") if k in v), None)
        if glow is not None and gcol is not None and float(np.max(gcol)) > 0:
            out["emissive"] = lin_to_srgb(glow[..., 0:1] * gcol)
        return out

    def spike_base(self, m, char_presets):
        """The earlier approximations for skin / hair / eyes (assemble.Baker), for before/after comparisons."""
        import assemble
        b = assemble.Baker.__new__(assemble.Baker)
        b.size, b.man = self.size, None
        b.presets = {g: self.P.preset(pid) for g, pid in (char_presets or {}).items()}
        return b.material(m, {}, None)

    # ------------------------------------------------------------ rules
    @staticmethod
    def tint_game(msk, v):
        """The CHAR_BASE tint: 12 colour keys in MSKColor RGB, each weighted by its distance."""
        out = np.zeros(msk.shape[:2] + (3,), np.float32)
        for name, key in KEYS:
            w = sat((1.0 - np.linalg.norm(msk - np.array(key, np.float32), axis=-1) * 0.57735 - 0.75) * 4.0)[..., None]
            out += Baker.vec(v, name) * w
        return out

    def gradient(self, texs, v, col):
        msk = self.tex(texs, "MSK", size=col.shape[0])
        grad = self.tex(texs, "Gradients", size=None)
        if msk is None or grad is None:
            return col
        gi, ng = self.num(v, "GradientIndex", 0), max(self.num(v, "NumberOfGradients", 1), 1)
        H, W = grad.shape[:2]

        def look(u, row):
            x = (np.clip(u, 0.02, 0.98) * (W - 1)).astype(np.int32)
            y = int(min(H - 1, max(0, row / ng * H)))     # row 0 (top) is a colour legend; GradientIndex >= 1
            return grad[y][x][..., :3]
        ga = look(msk[..., 1], 2 * gi + 0.5)
        gb = look(msk[..., 2], 2 * gi + 1.5)
        g = mix(ga, gb, msk[..., 3:4])
        return mix(g, col, msk[..., 0:1])

    def skin_core(self, hmvy, v, pre="", cancel_y=0.0):
        """Hemoglobin/melanin/vein/yellowing skin colour (CHAR_Skin_Body / _Head_v3 / _DGB), wounds/tattoos off."""
        g = lambda k, d=0.0: self.num(v, pre + k, self.num(v, k, d))  # noqa: E731
        gv = lambda k, d: self.vec(v, pre + k, self.vec(v, k, d))  # noqa: E731
        mdt, mdm = g("MelaninDarkThreshold", 0.9), g("MelaninDarkMultiplier", 2.0)
        inv = 1.0 - hmvy[..., 1]
        mel_dark = mix(mix(0.0, mdt, sat(inv / max(mdt, 1e-4))), mdm, sat((inv - mdt) / max(1 - mdt, 1e-4)))
        hemo = sat(hmvy[..., 0] * g("HemoglobinAmount", 0.5))
        mel = np.maximum((mel_dark + g("MelaninAmount", 0.3)) * (1 - cancel_y * g("MelaninRemovalAmount", 0)), 0)
        a = (1 - np.exp(-hemo ** 2))[..., None]
        b = (1 - np.exp(-mel ** 2))[..., None]
        vein = sat(hmvy[..., 2] * g("VeinAmount", 0.5))[..., None]
        hc = np.maximum(gv("HemoglobinColor", (0.65, 0.008, 0.008)), 1e-4)
        mc = np.maximum(gv("MelaninColor", (0.017, 0.013, 0.014)), 1e-4)
        c = mix(hc ** a, gv("VeinColor", (0, 0.27, 0.58)), vein) * mc ** b
        yell = (hmvy[..., 3] * g("YellowingAmount", 0.2))[..., None]
        c = mix(c, c * gv("YellowingColor", (1, 0.8, 0.2)), yell) * np.array([0.95222, 0.744098, 0.595243], np.float32)
        lum = (c @ LUMA)[..., None]
        return mix(lum, c, 1 - a * b)

    def skin(self, shader, texs, v, layers, out):
        S = self.size
        if layers is not None:            # body: VT L0 = CLEA, L1 normal, L2 = HMVY
            clea, nrm, hmvy = layers
            out["normal"] = self.vt_normal(nrm)
        else:
            hmvy = self.tex(texs, "HMVY")
            clea = self.tex(texs, "CLEA")
            nm = self.tex(texs, "normalmap")
            if nm is not None:
                out["normal"] = self.vt_normal(nm)
        if hmvy is None:
            hmvy = np.zeros((S, S, 4), np.float32) + np.array([0.5, 0.5, 0, 0], np.float32)
        cancel = self.tex(texs, "CancelMSK", size=hmvy.shape[0])
        cy = cancel[..., 1] if cancel is not None else 0.0
        cx = cancel[..., 0:1] if cancel is not None else 0.0
        if "DGB" in shader:
            acc = self.tex(texs, "AccentMSK", size=hmvy.shape[0])
            sk = self.skin_core(hmvy, v, "sk_", cy)
            sc = self.skin_core(hmvy, v, "sc_", cy)
            c = mix(sk, sc, cx * self.num(v, "NonSkin_Weight", 1)) if cancel is not None else sk
            if acc is not None:
                c = mix(c, self.skin_core(hmvy, v, "acc_", cy), acc[..., 0:1])
                ag = sat(acc[..., 1:2] * self.num(v, "Accent_G_Intensity", 0) + acc[..., 2:3] * self.num(v, "Accent_B_Intensity", 0))
                c = mix(c, self.vec(v, "Accent_G", (0, 0, 0)) * acc[..., 1:2] + self.vec(v, "Accent_B", (0, 0, 0)) * acc[..., 2:3], ag)
        else:
            c = self.skin_core(hmvy, v, "", cy)
        if clea is not None:
            if clea.shape[:2] != c.shape[:2]:
                clea = np.asarray(Image.fromarray((clea * 255).astype(np.uint8)).resize(c.shape[1::-1])) / 255.0
            if layers is not None:      # body: Body hair + makeup
                c = mix(c, self.vec(v, "Body_Hair_Color", (0.1, 0.08, 0.07)) * clea[..., 0:1], clea[..., 1:2])
            else:                       # head: lips, eyebrows
                c = mix(c, self.vec(v, "Lips_Makeup_Color", (0.3, 0.1, 0.1)), clea[..., 2:3] * self.num(v, "LipsMakeupIntensity", 0))
                c = mix(c, self.vec(v, "Eyebrow_Color", (0.05, 0.04, 0.03)) * clea[..., 1:2], clea[..., 1:2])
        if cancel is not None and "DGB" not in shader:
            ns = self.tex(texs, "BaseColor_NonSkin", size=c.shape[0])
            nsc = self.vec(v, "NonSkinColor", (0.2, 0.15, 0.13)) * (ns[..., 0:1] if ns is not None else 1.0)
            c = mix(c, nsc, cx * self.num(v, "NonSkin_Weight", 1))
        out["base"] = np.concatenate([lin_to_srgb(c), np.ones(c.shape[:2] + (1,), np.float32)], -1)
        out["metal"], out["rough"] = 0.0, 0.5
        out["sss"] = True

    def hair(self, texs, v, out, scalp=False):
        t = self.tex(texs, "ID_Depth_Root_Alpha_MSKA")
        if t is None:
            return
        hc = self.vec(v, "Hair_Scalp_Color" if scalp else "Hair_Color", (0.1, 0.07, 0.05))
        gi = self.num(v, "Graying_Intensity", 0.0)
        gray = self.vec(v, "Hair_Graying_Color", hc)
        # graying is per strand (vertex-colour noise in the game); its average share is ~ gi * 0.8
        base = mix(hc, gray, min(1.0, gi * 0.8))
        hl = self.num(v, "Highlight_Intensity", 0.0)
        base = mix(base, self.vec(v, "Highlight_Color", base), hl * 0.25)
        root = t[..., 2]
        mid, soft = self.num(v, "RootTransitionMidPoint", 0.5), sat(self.num(v, "RootTransitionSoftness", 0.5))
        lo, hi = mid - soft * 0.5, mid + soft * 0.5
        r = sat((root - lo) / max(hi - lo, 1e-4))
        r = r * r * (3 - 2 * r)
        r = sat(mix(r, r ** self.num(v, "DepthColorExponent", 1.0), self.num(v, "DepthColorIntensity", 0.0)))[..., None]
        half = base * 0.5
        lum = float(half @ LUMA)
        dark = mix(np.full(3, lum, np.float32), half, 1.2)
        c = mix(dark, base, r)
        c = c * mix(1.0, 0.2 + t[..., 0:1] * 1.8, self.num(v, "IDContrast", 0.0))
        c = c * mix(1.0, 0.5 + t[..., 1:2] ** 2.2 * 1.5, self.num(v, "ColorDepthContrast", 0.0))
        out["base"] = np.concatenate([lin_to_srgb(c), t[..., 3:4]], -1)
        out["alpha"] = "MASK"
        out["metal"], out["rough"] = 0.0, 0.45

    def eye(self, texs, v, out):
        cm = self.tex(texs, "ColorsMask", size=256)
        rm = self.tex(texs, "RegionMask", size=256)
        if cm is None or rm is None:
            c = np.tile(lin_to_srgb(self.vec(v, "Eyes_IrisColour", (0.2, 0.1, 0.05))), (4, 4, 1))
            out["base"] = np.concatenate([c, np.ones((4, 4, 1))], -1).astype(np.float32)
            return
        t244 = sat(self.num(v, "SecondaryColourIntensity", 1.0) * cm[..., 3:4])
        iris = mix(self.vec(v, "Eyes_IrisColour", (0.2, 0.1, 0.05)), self.vec(v, "Eyes_IrisSecondaryColour", (0.3, 0.2, 0.1)), t244)
        iris = iris * cm[..., 1:2] * (1 - cm[..., 2:3] * self.num(v, "IrisEdgeStrength", 0.5))
        red = sat(np.maximum(cm[..., 0:1], 1e-4) ** self.num(v, "Redness", 1.0))
        sclera = mix(self.vec(v, "Eyes_BloodColour", (0.3, 0.05, 0.04)), self.vec(v, "Eyes_ScleraColour", (0.6, 0.55, 0.5)), red)
        mask = rm[..., 1:2] * rm[..., 2:3]
        c = mix(iris, sclera * mask, mask)
        out["base"] = np.concatenate([lin_to_srgb(c), np.ones(c.shape[:2] + (1,), np.float32)], -1)
        out["metal"], out["rough"] = 0.0, 0.1
