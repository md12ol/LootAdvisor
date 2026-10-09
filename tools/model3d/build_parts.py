"""Build the 3D models of ALL sets as deduplicated per-piece GLBs + a manifest (3D_ALL.md).

  python tools/model3d/build_parts.py [--tex 512] [--sets id,id] [--rule game|spike] [--pose idle|bind]
                                      [--hands on|off] [--presets on|off] [--out artifact/3d] [--force]

Inputs: data/cache/model3d/catalog.json (catalog.py), work/ (extract_all.py), data/scores/<char>.json (build profile ->
which weapons are in hand). Output (gitignored, game-derived, private use only):
  <out>/parts/<id>.glb   one file per unique piece: per origin a base (skeleton + head / hair / body), per item visual
                         + dye one armour piece (shared by every origin: skinned by bone name, the viewer binds it to
                         the origin's skeleton like the game does), per weapon visual one weapon (own space)
  <out>/manifest.json    origins (base part, idle poses per stance), sets (parts, stance, weapons with bone + offset,
                         body regions to cut, base slots to hide), part sizes
Everything that changes the look follows the game data:
  - colours: shading.py (rules decompiled from the game's shaders, the item's dye preset and overrides)
  - pose: the race's IDLE_Still_Combat_01 animation for the stance of the weapons in hand (frame 0)
  - weapons in hand: weapon Dummy_Attachment on the skeleton's Dummy_R_Hand / Dummy_L_Hand; the other set on its
    sheath bone (weapon Dummy_Sheath on Dummy_Sheath_*)
  - hidden body / clothing parts: every equipped visual's VertexColorMaskSlots -> NakedBodySystem codes (vertex colour
    G * 255) of meshes whose shader has VertexColor_MSK ("VertCut"); hair etc. hidden by the items' equipment slots
"""
import hashlib
import io
import json
import os
import re
import struct
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import meshsrc  # noqa: E402
import shading  # noqa: E402
import spirv_dis  # noqa: E402

ROOT = shading.ROOT
CACHE = shading.CACHE
WORK = shading.WORK
VERSION = 4
BASE_SLOTS_SKIP = ("Private Parts", "ModestyLeaf")
PIERCING = ("Daggers", "Rapiers", "Shortswords", "Spears", "Tridents", "Pikes", "Javelins")
POLEARMS = ("Pikes", "Halberds", "Glaives")
STANCE_FALLBACK = {"1HP": "1HS", "1HPSH": "1HSSH", "DWP": "DWS", "XBS": "XB", "SL": "DFLT", "JAVSH": "1HSSH",
                   "JAV": "1HS", "ST": "2H", "POLE": "2H", "2HS": "2H", "DWXBS": "XBS", "BOW": "DFLT", "XB": "DFLT",
                   "1HSSH": "1HS", "DWS": "1HS", "2H": "DFLT", "1HS": "DFLT"}
SHEATH = {"melee1": "Dummy_Sheath_Hip_L", "melee2": "Dummy_Sheath_Upper_R", "off": "Dummy_Sheath_Hip_R",
          "shield": "Dummy_Sheath_Shield", "ranged2": "Dummy_Sheath_Ranged", "handxbow": "Dummy_Sheath_Lower_R",
          "handxbow_off": "Dummy_Sheath_Lower_L"}


# ---------------------------------------------------------------- GLB writer
def to_webp(arr, quality, alpha=False):
    a = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    im = Image.fromarray(a[..., :4] if alpha else a[..., :3], "RGBA" if alpha else "RGB")
    b = io.BytesIO()
    im.save(b, "WEBP", quality=quality, method=6)
    return b.getvalue()


class Writer:
    def __init__(self):
        self.j = {"asset": {"version": "2.0", "generator": "LootAdvisor build_parts.py (game data via LSLib)"},
                  "extensionsUsed": ["KHR_mesh_quantization", "EXT_texture_webp"],
                  "extensionsRequired": ["KHR_mesh_quantization", "EXT_texture_webp"],
                  "buffers": [{}], "bufferViews": [], "accessors": [], "images": [], "textures": [],
                  "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
                  "materials": [], "meshes": [], "nodes": [], "skins": [], "scenes": [{"nodes": []}], "scene": 0}
        self.bin = bytearray()
        self.tex_bytes = 0
        self.joint_nodes = {}

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

    def accessor(self, arr, ctype, typ, normalized=False, target=None, stride=None, minmax=False, count=None):
        v = self.view(arr.tobytes(), target, stride)
        a = {"bufferView": v, "componentType": ctype, "count": int(count or arr.shape[0]), "type": typ}
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"] = [int(x) for x in arr.min(0)[:3]]
            a["max"] = [int(x) for x in arr.max(0)[:3]]
        self.j["accessors"].append(a)
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
        alpha = mb["alpha"] in ("MASK", "BLEND")
        pbr["baseColorTexture"] = {"index": self.image(to_webp(mb["base"], 82, alpha=alpha))}
        if "orm" in mb:
            pbr["metallicRoughnessTexture"] = {"index": self.image(to_webp(mb["orm"], 78))}
            m["occlusionTexture"] = {"index": pbr["metallicRoughnessTexture"]["index"]}
            pbr["metallicFactor"] = pbr["roughnessFactor"] = 1.0
        else:
            pbr["metallicFactor"], pbr["roughnessFactor"] = mb["metal"], mb["rough"]
        if "normal" in mb:
            m["normalTexture"] = {"index": self.image(to_webp(mb["normal"], 86))}
        if "emissive" in mb:
            m["emissiveTexture"] = {"index": self.image(to_webp(mb["emissive"], 80))}
            m["emissiveFactor"] = [1.0, 1.0, 1.0]
        elif "emissive_factor" in mb:
            m["emissiveFactor"] = mb["emissive_factor"]
        if mb["alpha"] == "MASK":
            m["alphaMode"], m["alphaCutoff"] = "MASK", 0.5
        elif mb["alpha"] == "BLEND":
            m["alphaMode"] = "BLEND"
        if mb["double"]:
            m["doubleSided"] = True
        if mb.get("sss"):
            m["extras"] = {"skin": True}
        self.j["materials"].append(m)
        return len(self.j["materials"]) - 1

    def joint(self, name):
        if name not in self.joint_nodes:
            self.j["nodes"].append({"name": name})
            self.joint_nodes[name] = len(self.j["nodes"]) - 1
            self.j["scenes"][0]["nodes"].append(self.joint_nodes[name])
        return self.joint_nodes[name]

    def mesh(self, name, pos, nrm, uv, groups, mat, skin=None, extras=None):
        """groups: [(index array, extras or None)] -> one primitive each (shared vertex accessors)."""
        lo, hi = pos.min(0), pos.max(0)
        center = (lo + hi) / 2
        half = float(max(np.max((hi - lo) / 2), 1e-6))     # uniform: keeps normals right under skinning
        q = np.zeros((len(pos), 4), np.int16)
        q[:, :3] = np.round((pos - center) / half * 32767).astype(np.int16)
        nn = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        qn = np.zeros((len(nrm), 4), np.int8)
        qn[:, :3] = np.round(nn * 127).astype(np.int8)
        attrs = {"POSITION": self.accessor(q, 5122, "VEC3", True, 34962, 8, minmax=True),
                 "NORMAL": self.accessor(qn, 5120, "VEC3", True, 34962, 4),
                 "TEXCOORD_0": self.accessor(uv.astype(np.float32), 5126, "VEC2", target=34962)}
        dq = np.eye(4)
        dq[:3, :3] *= half
        dq[:3, 3] = center
        node = {"name": name}
        if skin:
            jnames, ibms, joints, weights = skin
            used = sorted(set(np.unique(joints[weights > 0]).tolist()))
            remap = np.zeros(max(len(jnames), 1), np.int32)
            for k, j in enumerate(used):
                remap[j] = k
            jj = np.zeros((len(joints), 4), np.uint8)
            jj[:] = remap[joints]
            ww = np.round(weights * 255).astype(np.int32)
            ww[:, 0] += 255 - ww.sum(1)                    # sum exactly 255 (normalized ubyte weights)
            attrs["JOINTS_0"] = self.accessor(jj, 5121, "VEC4", target=34962)
            attrs["WEIGHTS_0"] = self.accessor(ww.astype(np.uint8), 5121, "VEC4", True, 34962)
            ib = np.stack([(ibms[jnames[j]] @ dq).T for j in used]).astype(np.float32)   # column-major
            sk = {"joints": [self.joint(jnames[j].split("#")[0]) for j in used],
                  "inverseBindMatrices": self.accessor(ib.reshape(len(used), 16), 5126, "MAT4", count=len(used))}
            self.j["skins"].append(sk)
            node["skin"] = len(self.j["skins"]) - 1
        else:
            node["translation"] = [float(x) for x in center]
            node["scale"] = [half] * 3
        prims = []
        for idx, ex in groups:
            if not len(idx):
                continue
            it = np.uint16 if len(pos) < 65535 else np.uint32
            p = {"attributes": attrs, "material": mat,
                 "indices": self.accessor(idx.astype(it).reshape(-1, 1), 5123 if it == np.uint16 else 5125, "SCALAR",
                                          target=34963)}
            if ex:
                p["extras"] = ex
            prims.append(p)
        if not prims:
            return
        self.j["meshes"].append({"name": name, "primitives": prims})
        node["mesh"] = len(self.j["meshes"]) - 1
        if extras:
            node["extras"] = extras
        self.j["nodes"].append(node)
        self.j["scenes"][0]["nodes"].append(len(self.j["nodes"]) - 1)

    def add_skeleton(self, bones):
        """bones: [(name, parent name|None, local 4x4)] -> real node hierarchy (base parts)."""
        idx = {}
        for name, parent, loc in bones:
            self.j["nodes"].append({"name": name, "matrix": [float(x) for x in loc.T.reshape(-1)]})
            idx[name] = len(self.j["nodes"]) - 1
            self.joint_nodes[name] = idx[name]
        for name, parent, loc in bones:
            if parent in idx:
                self.j["nodes"][idx[parent]].setdefault("children", []).append(idx[name])
            else:
                self.j["scenes"][0]["nodes"].append(idx[name])

    def save(self, path):
        for k in ("skins", "images", "textures"):
            if not self.j[k]:
                self.j.pop(k)
                if k == "textures":
                    self.j.pop("samplers", None)
        if "images" not in self.j:
            self.j["extensionsUsed"] = self.j["extensionsRequired"] = ["KHR_mesh_quantization"]
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"][0]["byteLength"] = len(self.bin)
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin))
        os.replace(path + ".part", path)
        return total


# ---------------------------------------------------------------- game data helpers
def naked_body_codes():
    from pak import GAME_DATA, Pak
    p = Pak(os.path.join(GAME_DATA, "Shared.pak"))
    t = p.read(p.by_name["Mods/Shared/EquipmentSettings/VisualSlots.lsx"]).decode("utf-8", "replace")
    t = t[t.find("NakedBodySystem"):]
    return {k: int(v) for k, v in re.findall(r'id="MapKey" type="22" value="([^"]+)"/>\s*<attribute id="MapValue" type="1" value="(\d+)"', t)}


def source_worlds(gr2name, g=None):
    """Node world matrices + parents of a model's own skeleton (glTF or Collada export)."""
    out = {}
    if g is not None:
        for i, n in enumerate(g.j["nodes"]):
            if n.get("name"):
                out[n["name"]] = (g.world(i), g.j["nodes"][g.parent[i]].get("name") if i in g.parent else None)
        return out
    dae = os.path.join(WORK, "dae", gr2name + ".dae")
    if os.path.exists(dae):
        nodes = meshsrc.dae_nodes(dae)

        def world(n):
            par, loc = nodes[n]
            return world(par) @ loc if par in nodes else loc
        for n in nodes:
            out[n] = (world(n), nodes[n][0])
    return out


def remap_skin(m, src, core, ref=None):
    """Joints that are not in every origin skeleton -> nearest ancestor that is (exact for the bones idle
    animations do not move; see 3D_ALL.md). Returns (jnames, ibms, joints, weights) or None (rigid)."""
    if not m.skinned:
        return None
    names = list(m.jnames)
    ibms = dict(m.ibm)
    for k, n in enumerate(names):
        if n in core:
            continue
        a = n
        while a is not None and a not in core:
            a = src.get(a, (None, None))[1]
        if a is None or a not in src:
            # the joint's own skeleton never reaches a body bone (e.g. a headwear rig): follow the body bone that is
            # nearest in the reference (human) bind pose, rigidly
            if n in src:
                p = src[n][0][:3, 3]
            else:
                p = np.linalg.inv(m.ibm[n])[:3, 3]
            a = min((b for b in core if b in ref and not b.startswith("Dummy")),
                    key=lambda b: np.linalg.norm(ref[b][:3, 3] - p))
            names[k] = a
            ibms[a + "#ref"] = np.linalg.inv(ref[a])
            names[k] = a + "#ref"
            continue
        names[k] = a
        if a not in ibms or a not in m.jnames:
            ibms[a] = np.linalg.inv(src[a][0])
    # merge duplicate joint names
    uniq = sorted(set(names))
    pos = {n: i for i, n in enumerate(uniq)}
    J = np.array([[pos[names[j]] for j in row] for row in m.joints], np.int32) if len(m.joints) else m.joints
    return uniq, {n: ibms[n] for n in uniq}, J, m.weights      # "Bone#ref" = same bone, reference-bind IBM


def region_groups(m, cut_ok):
    """Split triangles by the NakedBodySystem codes (vertex colour G) they touch."""
    idx = m.idx.reshape(-1, 3)
    if not cut_ok or m.col is None:
        return [(idx.reshape(-1), None)]
    code = np.round(m.col[:, 1] * 255).astype(np.int32)
    tc = code[idx]
    keys = {}
    for t, row in enumerate(tc):
        k = tuple(sorted(set(int(x) for x in row if x)))
        keys.setdefault(k, []).append(t)
    out = []
    for k, tris in sorted(keys.items()):
        out.append((idx[tris].reshape(-1), {"cut": list(k)} if k else None))
    return out


def stance_and_hands(set_rec, profile):
    """Which weapons are in hand (build profile: ranged vs melee attack weights) -> (stance, [(slot, bone, mode)])."""
    pieces = {p["slot"]: p for p in set_rec["pieces"] if p.get("visuals")}
    att = (profile or {}).get("attacks") or {}
    ranged_w = sum(v for k, v in att.items() if k in ("ranged", "handxbow"))
    melee_w = sum(v for k, v in att.items() if k not in ("ranged", "handxbow"))
    has_melee = "MainHand" in pieces or "OffHand" in pieces
    has_ranged = "Ranged" in pieces
    use_ranged = has_ranged and (ranged_w > melee_w or not has_melee)

    def prof(slot):
        return ((pieces.get(slot) or {}).get("weapon") or {}).get("prof") or ""

    def props(slot):
        return ((pieces.get(slot) or {}).get("weapon") or {}).get("props") or ""
    hands = []
    stance = "DFLT"
    main, off = prof("MainHand"), prof("OffHand")
    shield = "Shields" in off
    two = "Twohanded" in props("MainHand")
    # melee
    if has_melee:
        if two:
            mstance = "ST" if "Quarterstaffs" in main else "POLE" if any(x in main for x in POLEARMS) else "2H"
        elif any(x in main for x in ("Spears", "Tridents")):
            mstance = "JAVSH" if shield else "JAV"
        elif shield:
            mstance = "1HPSH" if any(x in main for x in PIERCING) else "1HSSH"
        elif "OffHand" in pieces:
            mstance = "DWP" if any(x in main for x in PIERCING) and any(x in off for x in PIERCING) else "DWS"
        elif "MainHand" in pieces:
            mstance = "1HP" if any(x in main for x in PIERCING) else "1HS"
        else:
            mstance = "DFLT"
    rprof = prof("Ranged")
    if has_ranged:
        if "HandCrossbows" in rprof:
            rstance = "DWXBS" if "RangedOff" in pieces else "XBS"
        elif "Crossbows" in rprof:
            rstance = "XB"
        else:
            rstance = "BOW"
    for slot in ("MainHand", "OffHand", "Ranged", "RangedOff"):
        if slot not in pieces:
            continue
        in_hand = (slot in ("Ranged", "RangedOff")) == use_ranged
        if in_hand:
            if slot == "MainHand":
                bone = "Dummy_R_Hand"
            elif slot == "OffHand":
                bone = "Dummy_L_Hand"
            elif slot == "Ranged":
                bone = "Dummy_L_Hand" if rstance == "BOW" else "Dummy_R_Hand"
            else:
                bone = "Dummy_L_Hand"
            hands.append((slot, bone, "attach"))
        else:
            if slot == "MainHand":
                bone = SHEATH["melee2"] if two else SHEATH["melee1"]
            elif slot == "OffHand":
                bone = SHEATH["shield"] if shield else SHEATH["off"]
            elif slot == "Ranged":
                bone = SHEATH["handxbow"] if "HandCrossbows" in rprof else SHEATH["ranged2"]
            else:
                bone = SHEATH["handxbow_off"]
            hands.append((slot, bone, "sheath"))
    if use_ranged:
        stance = rstance
    elif has_melee:
        stance = mstance
    return stance, hands


# ---------------------------------------------------------------- builder
class Builder:
    def __init__(self, argv):
        self.argv = argv
        self.tex = int(argv[argv.index("--tex") + 1]) if "--tex" in argv else 512
        self.rule = argv[argv.index("--rule") + 1] if "--rule" in argv else "game"
        self.pose_mode = argv[argv.index("--pose") + 1] if "--pose" in argv else "idle"
        self.hands_mode = argv[argv.index("--hands") + 1] if "--hands" in argv else "on"
        self.presets_mode = argv[argv.index("--presets") + 1] if "--presets" in argv else "on"
        out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join("artifact", "3d")
        self.out = out if os.path.isabs(out) else os.path.join(ROOT, out)
        self.force = "--force" in argv
        self.cat = json.load(open(os.path.join(CACHE, "catalog.json"), encoding="utf-8"))
        banks = json.load(open(os.path.join(CACHE, "banks.json"), encoding="utf-8"))
        self.vbank = banks["VisualBank"]
        self.P = shading.Params(banks["MaterialPresetBank"])
        order = "preset_then_explicit" if self.rule == "game" else "explicit_only"
        self.B = shading.Baker(self.P, self.tex, rule=self.rule, order=order)
        self.base_rule = argv[argv.index("--base-rule") + 1] if "--base-rule" in argv else self.rule
        self.Bbase = shading.Baker(self.P, self.tex, rule=self.base_rule)
        self.codes = naked_body_codes()
        self.cut_shaders = {}
        self.parts = {}
        self.part_meta = {}
        self.profiles = {}
        for char in self.cat["chars"]:
            sc = json.load(open(os.path.join(ROOT, "data", "scores", f"{char}.json"), encoding="utf-8"))
            self.profiles[char] = {b: bd.get("profile") for b, bd in sc["builds"].items()}
        self.skel = {}
        for char, c in self.cat["chars"].items():
            name = os.path.splitext(os.path.basename(c["skeleton"]))[0]
            g = meshsrc._gltf_meshes(os.path.join(WORK, "skel", name + ".glb"))[1]
            bones = []
            for i, n in enumerate(g.j["nodes"]):
                if n.get("name") and "mesh" not in n:
                    par = g.j["nodes"][g.parent[i]].get("name") if i in g.parent else None
                    bones.append((n["name"], par, g.local(n)))
            self.skel[char] = {"name": name, "bones": bones, "world": {b: g.world(i) for i, n in enumerate(g.j["nodes"])
                                                                       for b in [n.get("name")] if b}}
        self.core = set.intersection(*[{b for b, _, _ in s["bones"]} for s in self.skel.values()])
        self.ref = next(s["world"] for s in self.skel.values() if s["name"] == "HUM_M_Base")

    def cut_ok(self, shader):
        name = os.path.splitext(os.path.basename(shader or ""))[0]
        if name not in self.cut_shaders:
            try:
                self.cut_shaders[name] = "VertexColor_MSK" in spirv_dis.material_params(name).values()
            except StopIteration:
                self.cut_shaders[name] = False
        return self.cut_shaders[name]

    def key(self, *parts):
        h = hashlib.sha1(json.dumps([VERSION, self.tex, self.rule, self.presets_mode, parts], sort_keys=True).encode())
        return h.hexdigest()[:12]

    def build_visual(self, pid, vids, overrides=None, char_presets=None, rigid=False, extras_by_vid=None, baker=None):
        """Write parts/<pid>.glb from visuals; returns meta (bytes, mesh/tex bytes, nodes for weapons)."""
        path = os.path.join(self.out, "parts", pid + ".glb")
        meta_path = path + ".json"
        if os.path.exists(path) and os.path.exists(meta_path) and not self.force:
            return json.load(open(meta_path))
        W = Writer()
        mats = {}
        meta = {}
        skeleton = (extras_by_vid or {}).get("_skeleton")
        if skeleton:
            W.add_skeleton(skeleton)
        for vid in vids:
            v = self.cat["visuals"].get(vid)
            if not v or not v.get("gr2"):
                continue
            name = os.path.splitext(os.path.basename(v["gr2"]))[0]
            meshes, g = meshsrc.load_meshes(name)
            src = source_worlds(name, g)
            wanted = {o["object"].split(".")[1]: o["material"] for o in v["objects"] if o.get("material")}
            mrec = {m["id"]: m for m in v["materials"]}
            if rigid:
                for d in ("Dummy_Attachment", "Dummy_Sheath"):
                    if d in src:
                        meta[d] = np.linalg.inv(src[d][0]).T.reshape(-1).round(6).tolist()
            for m in meshes:
                mid = wanted.get(m.name)
                if not mid or any(s in m.name for s in ("Eyeshadow", "Genital")):
                    continue
                mat = mrec.get(mid, {})
                key = (mid, json.dumps(overrides, sort_keys=True))
                if key not in mats:
                    mb = (baker or self.B).material(mat, overrides, char_presets)
                    mats[key] = W.material(mb) if mb else None
                if mats[key] is None:
                    continue
                skin = None if rigid else remap_skin(m, src, self.core, self.ref)
                groups = region_groups(m, self.cut_ok(mat.get("shader")) and not rigid)
                ex = (extras_by_vid or {}).get(vid)
                W.mesh(m.name, m.pos, m.nrm, m.uv, groups, mats[key], skin, ex)
        n = W.save(path)
        meta.update(bytes=n, tex=W.tex_bytes)
        json.dump(meta, open(meta_path, "w"))
        return meta

    def base_part(self, char):
        c = self.cat["chars"][char]
        vids, extras = [], {}
        for s in [{"slot": "NakedBody", "visual": c["body"]}] + c["slots"]:
            if s["slot"] in BASE_SLOTS_SKIP or not s.get("visual"):
                continue
            vids.append(s["visual"])
            extras[s["visual"]] = {"slot": s["slot"]}
        sk = self.skel[char]["bones"] if self.pose_mode != "none" else None
        presets = c["material_presets"] if self.presets_mode == "on" else {}
        # ONLY skin / hair / eye groups of the origin presets apply to its own body (the "02 Colour" group is for the
        # CharacterVisual's default clothes)
        presets = {k: v for k, v in presets.items() if "Colour" not in k}
        pid = "base_" + char + "_" + self.key("base", char, vids, presets, self.base_rule)
        extras["_skeleton"] = sk
        return pid, self.build_visual(pid, vids, None, presets, extras_by_vid=extras, baker=self.Bbase)

    def hidden(self, vids):
        codes, tags = set(), set()
        for vid in vids:
            r = self.vbank.get(vid) or {}
            for ch in r.get("children", []):
                if ch["name"] == "VertexColorMaskSlots":
                    nm = ch["attributes"].get("Object")
                    if nm in self.codes:
                        codes.add(self.codes[nm])
                if ch["name"] == "Base":
                    for t in ch.get("children", []):
                        tags.add(t["attributes"].get("Object"))
        return codes, tags

    def pose(self, char, stance):
        c = self.cat["chars"][char]
        base = os.path.basename(c["skeleton"]).split("_Base")[0]
        race, body = base.split("_", 1)
        rig = {"HEL": "HUM", "TIF": "HUM"}.get(race, race) + "_" + body
        st = stance
        while st:
            p = os.path.join(WORK, "anim", f"{rig}_{st}_Combat.dae")
            if os.path.exists(p):
                loc = meshsrc.load_pose(p)
                bones = {b for b, _, _ in self.skel[char]["bones"]}
                return st, {b: [round(float(x), 5) for x in m.T.reshape(-1)] for b, m in loc.items() if b in bones}
            st = STANCE_FALLBACK.get(st)
        return "bind", {}

    def run(self):
        t0 = time.time()
        only = None
        if "--sets" in self.argv:
            only = set(self.argv[self.argv.index("--sets") + 1].split(","))
        man = {"version": VERSION, "generated": time.strftime("%Y-%m-%d %H:%M"), "tex": self.tex, "rule": self.rule,
               "pose": self.pose_mode, "chars": {}, "sets": {}, "parts": {}, "skipped": {}}
        poses_needed = {}
        for set_id, s in sorted(self.cat["sets"].items()):
            if only and set_id not in only:
                continue
            char = s["char"]
            if char not in man["chars"]:
                pid, meta = self.base_part(char)
                man["parts"][pid] = meta["bytes"]
                man["chars"][char] = {"base": pid, "poses": {}}
            stance, hands = stance_and_hands(s, self.profiles[char].get(s["build"]))
            if self.hands_mode == "off":
                stance = "DFLT"
                hands = [(sl, b if m == "sheath" else {"MainHand": "Dummy_Sheath_Hip_L", "OffHand": "Dummy_Sheath_Hip_R",
                                                       "Ranged": "Dummy_Sheath_Ranged", "RangedOff": "Dummy_Sheath_Lower_L"}[sl], "sheath")
                         for sl, b, m in hands]
            hand_of = {sl: (b, mode) for sl, b, mode in hands}
            parts, weapons, all_vids, hide_slots = [], [], [], set()
            for p in s["pieces"]:
                if not p.get("visuals"):
                    man["skipped"].setdefault(p["sid"], "no visual")
                    continue
                all_vids += p["visuals"]
                hide_slots |= set(p.get("equip_slots") or [])
                ov = p.get("tints") if self.presets_mode == "on" else {"vectors": (p.get("tints") or {}).get("vectors", {})}
                if p["slot"] in hand_of:
                    pid = "wpn_" + self.key("wpn", p["visuals"], ov)
                    meta = self.build_visual(pid, p["visuals"], ov, rigid=True)
                    bone, mode = hand_of[p["slot"]]
                    off = meta.get("Dummy_Attachment" if mode == "attach" else "Dummy_Sheath") or \
                        meta.get("Dummy_Sheath") or np.eye(4).reshape(-1).tolist()
                    weapons.append({"part": pid, "slot": p["slot"], "bone": bone, "mode": mode, "offset": off})
                else:
                    pid = "itm_" + self.key("itm", p["visuals"], ov)
                    meta = self.build_visual(pid, p["visuals"], ov)
                    parts.append(pid)
                man["parts"][pid] = meta["bytes"]
            codes, tags = self.hidden(all_vids)
            if "Hide Beard" in tags:
                hide_slots.add("Beard")
            pose_key = stance if self.pose_mode == "idle" else "bind"
            if pose_key not in man["chars"][char]["poses"]:
                used, pose = self.pose(char, stance) if self.pose_mode == "idle" else ("bind", {})
                man["chars"][char]["poses"][pose_key] = {"anim": used, "bones": pose}
            man["sets"][set_id] = {"char": char, "name": s["name"], "stance": pose_key, "parts": parts,
                                   "weapons": weapons, "cut": sorted(codes), "hideSlots": sorted(hide_slots)}
            print(f"{set_id:34s} {pose_key:6s} parts {len(parts)} weapons {len(weapons)}  {time.time() - t0:5.0f}s",
                  flush=True)
        os.makedirs(self.out, exist_ok=True)
        with open(os.path.join(self.out, "manifest.json"), "w") as f:
            json.dump(man, f, separators=(",", ":"))
        self.P.save()
        tot = sum(man["parts"].values())
        print(f"{len(man['sets'])} sets, {len(man['parts'])} parts, {tot / 1e6:.1f} MB, {time.time() - t0:.0f}s -> {self.out}")
        return man


if __name__ == "__main__":
    Builder(sys.argv).run()
