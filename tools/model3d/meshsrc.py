"""Mesh + skin + animation readers for LSLib's exports (glTF binary, and Collada when the glTF export fails).

  load_meshes(gr2_name) -> [Mesh]   from work/glb/<name>.glb, else work/dae/<name>.dae (converted on demand)
  load_pose(dae_path)   -> {bone: 4x4 local matrix at frame 0}    (idle animations)

Mesh fields: name, pos (N,3 bind-pose model space), nrm (N,3), tan (N,4|None), uv (N,2), col (N,4|None),
joints (N,4 int into jnames|None), weights (N,4|None), idx (M,), jnames, ibm {joint: 4x4}, skinned.
"""
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, "data", "cache", "model3d", "work")
LSLIB = os.path.join(ROOT, "third_party", "lslib", "Packed", "Tools")
NS = "{http://www.collada.org/2005/11/COLLADASchema}"


class Mesh:
    def __init__(self, **kw):
        self.tan = self.col = self.joints = self.weights = None
        self.jnames, self.ibm, self.skinned = [], {}, False
        self.__dict__.update(kw)


def _gltf_meshes(path):
    import assemble
    g = assemble.Gltf(path)
    out = []
    skins = g.j.get("skins", [])
    for i, n in enumerate(g.j["nodes"]):
        if "mesh" not in n:
            continue
        mesh = g.j["meshes"][n["mesh"]]
        for p in mesh["primitives"]:
            A = p["attributes"]
            m = Mesh(name=mesh["name"], pos=g.acc(A["POSITION"]).astype(np.float64),
                     nrm=g.acc(A["NORMAL"]).astype(np.float64), uv=g.acc(A["TEXCOORD_0"]).astype(np.float32),
                     idx=g.acc(p["indices"]).reshape(-1).astype(np.int64))
            if "TANGENT" in A:
                m.tan = g.acc(A["TANGENT"]).astype(np.float32)
            if "COLOR_0" in A:
                c = g.acc(A["COLOR_0"]).astype(np.float32)
                m.col = np.concatenate([c, np.ones((len(c), 1), np.float32)], 1) if c.shape[1] == 3 else c
            if "skin" in n and "JOINTS_0" in A:
                sk = skins[n["skin"]]
                m.skinned = True
                m.jnames = [g.j["nodes"][j].get("name") for j in sk["joints"]]
                ib = g.acc(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
                m.ibm = {nm: ib[k] for k, nm in enumerate(m.jnames)}
                m.joints = g.acc(A["JOINTS_0"]).astype(np.int32)
                m.weights = g.acc(A["WEIGHTS_0"]).astype(np.float32)
            else:                          # rigid: bake the node transform
                w = g.world(i)
                m.pos = m.pos @ w[:3, :3].T + w[:3, 3]
                m.nrm = m.nrm @ w[:3, :3].T
            out.append(m)
    return out, g


def _floats(el):
    return np.array(el.text.split(), np.float64) if el is not None and el.text else np.zeros(0)


def _dae_meshes(path):
    root = ET.parse(path).getroot()
    srcs = {}
    for s in root.iter(NS + "source"):
        fa = s.find(NS + "float_array")
        na = s.find(NS + "Name_array")
        acc = s.find(f"{NS}technique_common/{NS}accessor")
        stride = int(acc.get("stride", 1)) if acc is not None else 1
        if fa is not None:
            srcs[s.get("id")] = _floats(fa).reshape(-1, stride)
        elif na is not None:
            srcs[s.get("id")] = na.text.split()
    controllers = {}
    for c in root.iter(NS + "controller"):
        skin = c.find(NS + "skin")
        controllers[skin.get("source").lstrip("#")] = skin
    # node world transforms of the joints (for rigid meshes) are not needed: LSLib bakes bind poses into the skin
    out = []
    for geo in root.iter(NS + "geometry"):
        mesh = geo.find(NS + "mesh")
        verts = mesh.find(NS + "vertices")
        vpos = srcs[verts.find(NS + "input").get("source").lstrip("#")]
        tris = mesh.find(NS + "triangles")
        inputs = [(i.get("semantic"), int(i.get("offset")), i.get("source").lstrip("#"), int(i.get("set", 0)))
                  for i in tris.findall(NS + "input")]
        nin = max(o for _, o, _, _ in inputs) + 1
        p = np.array(tris.find(NS + "p").text.split(), np.int64).reshape(-1, nin)
        uniq, inv = np.unique(p, axis=0, return_inverse=True)
        m = Mesh(name=geo.get("name"), idx=inv.reshape(-1))
        for sem, off, src, st in inputs:
            col = uniq[:, off]
            if sem == "VERTEX":
                m.pos = vpos[col][:, :3]
                pos_index = col
            elif sem == "NORMAL":
                m.nrm = srcs[src][col][:, :3]
            elif sem == "TEXCOORD" and st == 0 and not hasattr(m, "uv"):
                uv = srcs[src][col][:, :2].astype(np.float32)
                uv[:, 1] = 1.0 - uv[:, 1]           # Collada V up -> glTF V down
                m.uv = uv
            elif sem == "COLOR" and m.col is None:
                c = srcs[src][col].astype(np.float32)
                m.col = np.concatenate([c, np.ones((len(c), 4 - c.shape[1]), np.float32)], 1) if c.shape[1] < 4 else c
            elif sem == "TEXTANGENT" and m.tan is None:
                t = srcs[src][col][:, :3]
                m.tan = np.concatenate([t, np.ones((len(t), 1))], 1).astype(np.float32)
        if not hasattr(m, "uv"):
            m.uv = np.zeros((len(m.pos), 2), np.float32)
        skin = controllers.get(geo.get("id"))
        if skin is not None:
            bsm = _floats(skin.find(NS + "bind_shape_matrix")).reshape(4, 4)
            m.pos = m.pos @ bsm[:3, :3].T + bsm[:3, 3]
            m.nrm = m.nrm @ bsm[:3, :3].T
            jin = {i.get("semantic"): i.get("source").lstrip("#") for i in skin.find(NS + "joints").findall(NS + "input")}
            names = srcs[jin["JOINT"]]
            ibms = srcs[jin["INV_BIND_MATRIX"]].reshape(-1, 4, 4)
            vw = skin.find(NS + "vertex_weights")
            wi = {i.get("semantic"): (int(i.get("offset")), i.get("source").lstrip("#")) for i in vw.findall(NS + "input")}
            wsrc = srcs[wi["WEIGHT"][1]].reshape(-1)
            vcount = np.array(vw.find(NS + "vcount").text.split(), np.int64)
            v = np.array(vw.find(NS + "v").text.split(), np.int64).reshape(-1, 2)
            J = np.zeros((len(vcount), 4), np.int32)
            W = np.zeros((len(vcount), 4), np.float32)
            k = 0
            for vi, n in enumerate(vcount):
                pairs = sorted(((wsrc[w], j) for j, w in v[k:k + n]), reverse=True)[:4]
                k += n
                s = sum(w for w, _ in pairs) or 1.0
                for slot, (w, j) in enumerate(pairs):
                    J[vi, slot], W[vi, slot] = j, w / s
            m.joints, m.weights = J[pos_index], W[pos_index]
            m.jnames = list(names)
            m.ibm = {nm: ibms[i] for i, nm in enumerate(names)}
            m.skinned = True
        out.append(m)
    return out, None


def load_meshes(name):
    glb = os.path.join(WORK, "glb", name + ".glb")
    if os.path.exists(glb):
        return _gltf_meshes(glb)
    dae = os.path.join(WORK, "dae", name + ".dae")
    if not os.path.exists(dae):
        src = os.path.join(WORK, "gr2", name + ".GR2")
        if not os.path.exists(src):
            return [], None
        os.makedirs(os.path.dirname(dae), exist_ok=True)
        subprocess.run([os.path.join(LSLIB, "Divine.exe"), "-g", "bg3", "-a", "convert-model", "-s", src, "-d", dae,
                        "-i", "gr2", "-o", "dae"], capture_output=True, cwd=os.path.dirname(LSLIB))
    if not os.path.exists(dae):
        return [], None
    return _dae_meshes(dae)


def dae_nodes(path):
    """Collada scene -> {node name: (parent name, local 4x4)} (skeleton hierarchy of a model / skeleton export)."""
    root = ET.parse(path).getroot()
    out = {}

    def walk(n, parent):
        mt = n.find(NS + "matrix")
        loc = _floats(mt).reshape(4, 4) if mt is not None else np.eye(4)
        out[n.get("name")] = (parent, loc)
        for c in n.findall(NS + "node"):
            walk(c, n.get("name"))
    for vs in root.iter(NS + "visual_scene"):
        for n in vs.findall(NS + "node"):
            walk(n, None)
    return out


def load_pose(path, frame=0):
    """Idle animation (Collada from LSLib) -> {bone: local 4x4 at the given key frame}."""
    root = ET.parse(path).getroot()
    out = {}
    for a in root.iter(NS + "animation"):
        ch = a.find(NS + "channel")
        if ch is None:
            continue
        bone = re.sub(r"^Bone_", "", ch.get("target").split("/")[0])
        outs = None
        for s in a.findall(NS + "source"):
            if s.get("id", "").endswith("-outputs"):
                outs = _floats(s.find(NS + "float_array")).reshape(-1, 4, 4)
        if outs is not None and len(outs):
            out[bone] = outs[min(frame, len(outs) - 1)]
    return out
