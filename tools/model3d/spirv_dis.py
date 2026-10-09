"""Minimal SPIR-V reader for the game's compiled material shaders (Materials.pak *.bshd, Vulkan variants).

  python tools/model3d/spirv_dis.py <shader name, e.g. CHAR_BASE_VT_ST_DEF_Vulkan> [--material CHAR_BASE_VT] [--raw]

Prints the fragment shader as single-assignment pseudo code with the material parameter names put back in (the
uniform offsets come from the material's .lsf in Materials.pak). Used to derive the exact tint rule (3D_ALL.md);
no third-party tools needed. Only the opcodes the game's shaders use are named; others print as op<N>.
"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

OPS = {
    12: "ExtInst", 41: "true", 42: "false", 43: "Constant", 44: "ConstantComposite", 46: "Null", 57: "Call",
    59: "Variable", 61: "Load", 62: "Store", 65: "AccessChain", 66: "AccessChain", 77: "ExtractDyn",
    79: "Shuffle", 80: "Construct", 81: "Extract", 82: "Insert", 83: "Copy", 86: "SampledImage",
    87: "Sample", 88: "SampleLod", 89: "SampleDref", 90: "SampleDrefLod", 95: "Fetch", 96: "Gather", 100: "Image",
    103: "QuerySizeLod", 104: "QuerySize", 109: "FtoU", 110: "FtoS", 111: "StoF", 112: "UtoF", 124: "Bitcast",
    126: "SNeg", 127: "FNeg", 128: "IAdd", 129: "FAdd", 130: "ISub", 131: "FSub", 132: "IMul", 133: "FMul",
    134: "UDiv", 135: "SDiv", 136: "FDiv", 137: "UMod", 141: "FMod", 142: "VxS", 143: "MxS", 144: "VxM", 145: "MxV",
    146: "MxM", 148: "Dot", 154: "Any", 155: "All", 164: "LEq", 165: "LNe", 166: "LOr", 167: "LAnd", 168: "LNot",
    169: "Select", 170: "IEq", 171: "INe", 172: "UGt", 173: "SGt", 174: "UGe", 175: "SGe", 176: "ULt", 177: "SLt",
    178: "ULe", 179: "SLe", 180: "FEq", 182: "FNe", 183: "FUNe", 184: "FLt", 185: "FULt", 186: "FGt", 187: "FUGt",
    188: "FLe", 189: "FULe", 190: "FGe", 191: "FUGe", 194: "Shr", 195: "Sar", 196: "Shl", 197: "Or", 198: "Xor",
    199: "And", 200: "Not", 202: "BfSExt", 203: "BfUExt", 207: "ddx", 208: "ddy", 209: "fwidth", 245: "Phi",
    246: "LoopMerge", 247: "SelectionMerge", 248: "Label", 249: "Branch", 250: "BranchCond", 251: "Switch",
    252: "Kill", 253: "Return", 254: "ReturnValue", 255: "Unreachable", 5380: "Demote",
}
GLSL = {1: "round", 2: "roundEven", 3: "trunc", 4: "abs", 5: "sabs", 6: "sign", 8: "floor", 9: "ceil", 10: "fract",
        13: "sin", 14: "cos", 15: "tan", 16: "asin", 17: "acos", 18: "atan", 25: "atan2", 26: "pow", 27: "exp",
        28: "log", 29: "exp2", 30: "log2", 31: "sqrt", 32: "rsqrt", 37: "min", 38: "umin", 39: "smin", 40: "max",
        41: "umax", 42: "smax", 43: "clamp", 44: "uclamp", 45: "sclamp", 46: "mix", 48: "step", 49: "smoothstep",
        50: "fma", 66: "length", 67: "distance", 68: "cross", 69: "normalize", 71: "reflect", 79: "nmin", 80: "nmax",
        81: "nclamp"}
TYPED_NO_RESULT = {62, 246, 247, 249, 250, 251, 252, 253, 254, 255, 5380}
INFIX = {"FAdd": "+", "FSub": "-", "FMul": "*", "FDiv": "/", "VxS": "*", "IAdd": "+", "ISub": "-", "IMul": "*",
         "FLt": "<", "FGt": ">", "FLe": "<=", "FGe": ">=", "FULt": "<", "FUGt": ">", "FULe": "<=", "FUGe": ">=",
         "FEq": "==", "FNe": "!=", "FUNe": "!=", "And": "&", "Or": "|", "LAnd": "&&", "LOr": "||", "Shr": ">>",
         "Shl": "<<", "IEq": "==", "INe": "!=", "ULt": "<", "UGt": ">", "SLt": "<", "SGt": ">", "UGe": ">=",
         "SGe": ">=", "ULe": "<=", "SLe": "<=", "Dot": "dot", "MxV": "*", "VxM": "*"}


def modules(blob):
    """-> list of SPIR-V word arrays found in a .bshd blob (vertex, pixel)."""
    out = []
    for m in re.finditer(re.escape(bytes.fromhex("03022307")), blob):
        i = m.start()
        bound = struct.unpack_from("<I", blob, i + 12)[0]
        words = []
        j = i + 20
        words = list(struct.unpack_from("<5I", blob, i))
        while j + 4 <= len(blob):
            w = struct.unpack_from("<I", blob, j)[0]
            n, op = w >> 16, w & 0xFFFF
            if n == 0 or j + 4 * n > len(blob) or op > 6000:
                break
            words += struct.unpack_from("<%dI" % n, blob, j)
            j += 4 * n
            if op == 56 and j + 4 <= len(blob) and struct.unpack_from("<I", blob, j)[0] & 0xFFFF != 54:
                break   # OpFunctionEnd not followed by another OpFunction: module ends
        out.append((bound, words))
    return out


class Module:
    def __init__(self, words, params=None):
        self.ins = []
        i = 5
        while i < len(words):
            n, op = words[i] >> 16, words[i] & 0xFFFF
            self.ins.append((op, words[i + 1:i + n]))
            i += n
        self.types, self.consts, self.defs, self.dec, self.mdec, self.names = {}, {}, {}, {}, {}, {}
        self.params = params or {}          # (set, binding) -> name ; ("cb", offset) -> name
        for op, a in self.ins:
            if 19 <= op <= 39:
                self.types[a[0]] = (op, a[1:])
            elif op in (43,):
                t = self.types.get(a[0])
                v = a[2]
                if t and t[0] == 22:
                    v = struct.unpack("<f", struct.pack("<I", v))[0]
                self.consts[a[1]] = v
            elif op == 44:
                self.consts[a[1]] = ("vec", a[2:])
            elif op == 71:
                self.dec.setdefault(a[0], {})[a[1]] = a[2:]
            elif op == 72:
                self.mdec.setdefault((a[0], a[1]), {})[a[2]] = a[3:]
            if op not in TYPED_NO_RESULT and op in OPS and op not in (248,) and len(a) >= 2:
                self.defs[a[1]] = (op, a)

    def cname(self, i):
        c = self.consts[i]
        if isinstance(c, tuple):
            return "(" + ", ".join(self.cname(x) for x in c[1]) + ")"
        if isinstance(c, float):
            return ("%.6g" % c)
        return str(c)

    def var_name(self, vid):
        d = self.dec.get(vid, {})
        s, b = d.get(34, [None])[0], d.get(33, [None])[0]
        if (s, b) in self.params:
            return self.params[(s, b)]
        if 30 in d:
            return "loc%d" % d[30][0]
        if 11 in d:
            return "builtin%d" % d[11][0]
        return "v%d_s%s_b%s" % (vid, s, b)

    def expr(self, i, depth=0, cache=None):
        if i in self.consts:
            return self.cname(i)
        if i not in self.defs or depth > 14:
            return "%" + str(i)
        op, a = self.defs[i]
        name = OPS.get(op, "op%d" % op)
        e = lambda x: self.expr(x, depth + 1)  # noqa: E731
        if op == 59:
            return self.var_name(i)
        if op in (65, 66):
            base = a[2]
            idx = a[3:]
            bname = self.var_name(base) if base in self.defs and self.defs[base][0] == 59 else e(base)
            # CB member: struct offset -> param name
            ptr_t = self.types.get(self.defs[base][1][0]) if base in self.defs else None
            if ptr_t and idx:
                st = ptr_t[1][1]
                if idx[0] in self.consts:
                    off = self.mdec.get((st, self.consts[idx[0]]), {}).get(35)
                    if off is not None:
                        d = self.dec.get(base, {})
                        key = ("cb", d.get(34, [None])[0], d.get(33, [None])[0], off[0])
                        if key in self.params:
                            return self.params[key] + "".join("[%s]" % e(x) for x in idx[1:])
            return bname + "".join("[%s]" % e(x) for x in idx)
        if op == 61:
            return e(a[2])
        if op == 81:
            return e(a[2]) + "." + "".join("xyzw"[x] if x < 4 else "[%d]" % x for x in a[3:])
        if op == 79:
            v1, v2 = a[2], a[3]
            n1 = self.types.get(self.defs[v1][1][0], (0, [0, 4]))[1][1] if v1 in self.defs else 4
            comps = []
            for c in a[4:]:
                comps.append(("xyzw"[c] if c < n1 else "_") if c != 0xFFFFFFFF else "_")
            if all(c < n1 for c in a[4:]):
                return e(v1) + "." + "".join(comps)
            return "shuffle(%s, %s, %s)" % (e(v1), e(v2), list(a[4:]))
        if op == 12:
            return GLSL.get(a[3], "ext%d" % a[3]) + "(" + ", ".join(e(x) for x in a[4:]) + ")"
        if name in INFIX and len(a) == 4:
            return "(%s %s %s)" % (e(a[2]), INFIX[name], e(a[3]))
        if op == 169:
            return "(%s ? %s : %s)" % (e(a[2]), e(a[3]), e(a[4]))
        if op in (87, 88):
            return "%s(%s, uv=%s%s)" % (name, e(a[2]), e(a[3]), (", " + ", ".join(e(x) for x in a[5:])) if len(a) > 5 else "")
        if op == 86:
            return e(a[2])
        args = [e(x) if (x in self.defs or x in self.consts) else str(x) for x in a[2:]]
        return name + "(" + ", ".join(args) + ")"

    def dump(self, raw=False):
        """Statements: every store to an output / variable, plus every sample, as expressions over named inputs."""
        lines = []
        for op, a in self.ins:
            if raw:
                if op in self.defs.get(a[1] if len(a) > 1 else -1, (None,))[:1]:
                    lines.append("%%%d = %s %s" % (a[1], OPS.get(op, "op%d" % op), a[2:]))
                else:
                    lines.append("%s %s" % (OPS.get(op, "op%d" % op), a))
                continue
            if op == 62:
                lines.append("STORE %s <- %s" % (self.expr(a[0]), self.expr(a[1])))
            elif op in (250,):
                lines.append("IF %s" % self.expr(a[0]))
            elif op == 252 or op == 5380:
                lines.append("DISCARD")
        return lines


def material_params(material):
    """Material .lsf (Materials.pak) -> {("cb", set, binding, offset): name, (set, binding): texture name}."""
    import lsf
    from pak import GAME_DATA, Pak
    p = Pak(os.path.join(GAME_DATA, "Materials.pak"))
    e = next(x for x in p.entries if x.name.endswith("/" + material + ".lsf"))
    j = lsf.to_json(lsf.load(p.read(e)).regions[0], typed=False)
    out = {}
    for c in j["children"]:
        a = c["attributes"]
        nm = a.get("ParameterName") or a.get("UniformName")
        if c["name"] in ("ScalarParameters", "Vector2Parameters", "Vector3Parameters", "Vector4Parameters"):
            if a.get("StaticDeferred") is not None:
                out[("cb", 1, 1, a["StaticDeferred"])] = nm
        for ch in c.get("children", []):
            if ch["name"] == "StaticDeferred":
                if ch["attributes"].get("VkBindingIndex") is not None:
                    out[(ch["attributes"]["VkDescriptorSet"], ch["attributes"]["VkBindingIndex"])] = nm
                for g in ch.get("children", []):
                    out[(g["attributes"]["VkDescriptorSet"], g["attributes"]["VkBindingIndex"])] = nm + "." + g["name"]
    return out


def load_shader(name):
    from pak import GAME_DATA, Pak
    p = Pak(os.path.join(GAME_DATA, "Materials.pak"))
    e = next(x for x in p.entries if x.name.endswith("/" + name + ".bshd"))
    return p.read(e)


def main(argv):
    name = argv[1]
    mat = argv[argv.index("--material") + 1] if "--material" in argv else re.sub(r"_STI?_[A-Z]+_(Vulkan|DX1[12])$", "", name)
    params = material_params(mat)
    mods = modules(load_shader(name))
    m = Module(mods[-1][1], params)
    for ln in m.dump(raw="--raw" in argv):
        print(ln)


if __name__ == "__main__":
    main(sys.argv)
