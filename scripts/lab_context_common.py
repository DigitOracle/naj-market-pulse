"""LAB (context / scenery, research only): shared helpers for scripts/lab_context_*.py - frames, the palette, and a
small glTF 2.0 binary (GLB) reader / writer (numpy only, no gltf library needed).

Frames
  UE     cm, X = easting - 328289, Y = 2784598 - northing, Z up           (ue_greenery / ue_props / ue_furniture / bb_v1_prep)
  local  m,  x = easting - ox,     y = up,  z = -(northing - oy)           (data/ce/<slug>/origin_v5.json: CE-frame = local + origin_ce_xyz)
"""
import gzip
import json
import math
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
UE_E0, UE_N0 = 328289.0, 2784598.0


def lab_dir(slug):
    return os.path.join(ROOT, "data", "lab", "context", slug)


class Frame:
    """UE cm <-> local v5 metres for one district"""

    def __init__(self, slug):
        o = json.load(open(os.path.join(CE, slug, "origin_v5.json"), encoding="utf-8"))
        self.origin_ce_xyz = o["origin_ce_xyz"]
        self.ox, self.oy = float(o["origin_utm_en"][0]), float(o["origin_utm_en"][1])
        self.dx = UE_E0 - self.ox          # local x = ue_x / 100 + dx
        self.dz = self.oy - UE_N0          # local z = ue_y / 100 + dz

    def ue_to_local(self, x_cm, y_cm):
        return x_cm / 100.0 + self.dx, y_cm / 100.0 + self.dz

    def local_to_ue(self, x, z):
        return (x - self.dx) * 100.0, (z - self.dz) * 100.0

    def local_to_utm(self, x, z):
        return x + self.ox, self.oy - z

    def utm_to_local(self, e, n):
        return e - self.ox, self.oy - n


def load_palette(slug):
    return json.load(open(os.path.join(lab_dir(slug), "context_palette.json"), encoding="utf-8"))


def srgb(v):
    v = min(1.0, max(0.0, float(v)))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def gz_size(path):
    return len(gzip.compress(open(path, "rb").read(), 9))


# ---------------------------------------------------------------------------------------------------------------- GLB read
CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GLB:
    def __init__(self, path):
        b = open(path, "rb").read()
        assert b[:4] == b"glTF", path
        jl = struct.unpack("<I", b[12:16])[0]
        self.js = json.loads(b[20:20 + jl])
        off = 20 + jl
        self.bin = b""
        if off < len(b):
            bl = struct.unpack("<I", b[off:off + 4])[0]
            self.bin = b[off + 8:off + 8 + bl]
        self.path = path

    def accessor(self, i):
        a = self.js["accessors"][i]
        dt = np.dtype(CT[a["componentType"]]); n = NC[a["type"]]; cnt = a["count"]
        if "bufferView" not in a:
            return np.zeros((cnt, n), dt) if n > 1 else np.zeros(cnt, dt)
        bv = self.js["bufferViews"][a["bufferView"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0) or dt.itemsize * n
        if stride == dt.itemsize * n:
            arr = np.frombuffer(self.bin, dt, cnt * n, start).reshape(cnt, n) if n > 1 else np.frombuffer(self.bin, dt, cnt, start)
        else:
            raw = np.frombuffer(self.bin, np.uint8, stride * (cnt - 1) + dt.itemsize * n, start)
            arr = np.lib.stride_tricks.as_strided(raw, (cnt, dt.itemsize * n), (stride, 1)).copy().view(dt).reshape(cnt, n)
            if n == 1:
                arr = arr[:, 0]
        if a.get("normalized") and dt != np.float32:
            arr = arr.astype(np.float32) / float(np.iinfo(dt).max)
        return np.array(arr)

    def image_bytes(self, i):
        im = self.js["images"][i]
        bv = self.js["bufferViews"][im["bufferView"]]
        o = bv.get("byteOffset", 0)
        return self.bin[o:o + bv["byteLength"]], im.get("mimeType", "image/png")

    def primitive(self, p):
        """-> dict(pos, nrm, uv, idx, material) as numpy arrays (None when absent)"""
        at = p["attributes"]
        pos = self.accessor(at["POSITION"]).astype(np.float32)
        nrm = self.accessor(at["NORMAL"]).astype(np.float32) if "NORMAL" in at else None
        uv = self.accessor(at["TEXCOORD_0"]).astype(np.float32) if "TEXCOORD_0" in at else None
        idx = self.accessor(p["indices"]).astype(np.uint32) if "indices" in p else np.arange(len(pos), dtype=np.uint32)
        return {"pos": pos, "nrm": nrm, "uv": uv, "idx": idx, "material": p.get("material")}

    def node_world(self):
        """-> list of (node index, world 4x4) for nodes with a mesh (column-major glTF matrices resolved)"""
        nodes = self.js.get("nodes", [])
        out = []

        def local(n):
            if "matrix" in n:
                return np.array(n["matrix"], dtype=np.float64).reshape(4, 4).T
            M = np.eye(4)
            t = n.get("translation", [0, 0, 0]); r = n.get("rotation", [0, 0, 0, 1]); s = n.get("scale", [1, 1, 1])
            x, y, z, w = r
            R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            M[:3, :3] = R * np.array(s)[None, :]; M[:3, 3] = t
            return M

        def walk(i, P):
            n = nodes[i]; W = P @ local(n)
            if "mesh" in n:
                out.append((i, W))
            for c in n.get("children", []):
                walk(c, W)
        scenes = self.js.get("scenes") or [{"nodes": list(range(len(nodes)))}]
        for r in scenes[self.js.get("scene", 0)].get("nodes", []):
            walk(r, np.eye(4))
        return out


# ---------------------------------------------------------------------------------------------------------------- GLB write
class GLBWriter:
    """minimal glTF 2.0 binary writer: meshes of indexed triangle primitives, PBR materials, embedded images, nodes
    (optionally EXT_mesh_gpu_instancing)."""

    def __init__(self, generator="lab_context"):
        self.js = {"asset": {"version": "2.0", "generator": generator}, "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                   "materials": [], "accessors": [], "bufferViews": [], "buffers": [{"byteLength": 0}]}
        self.blob = bytearray()
        self.ext = set()
        self._mat = {}
        self._img = {}

    def _view(self, data, target=None):
        while len(self.blob) % 4:
            self.blob += b"\0"
        bv = {"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.blob += data
        self.js["bufferViews"].append(bv)
        return len(self.js["bufferViews"]) - 1

    def _acc(self, arr, typ, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        ct = {np.dtype(np.float32): 5126, np.dtype(np.uint32): 5125, np.dtype(np.uint16): 5123}[arr.dtype]
        a = {"bufferView": self._view(arr.tobytes(), target), "componentType": ct, "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = [float(v) for v in arr.min(0)] if arr.ndim > 1 else [float(arr.min())]
            a["max"] = [float(v) for v in arr.max(0)] if arr.ndim > 1 else [float(arr.max())]
        self.js["accessors"].append(a)
        return len(self.js["accessors"]) - 1

    def image(self, key, data, mime):
        if key in self._img:
            return self._img[key]
        self.js.setdefault("images", []).append({"bufferView": self._view(data), "mimeType": mime, "name": key})
        self.js.setdefault("samplers", [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}])
        self.js.setdefault("textures", []).append({"source": len(self.js["images"]) - 1, "sampler": 0})
        self._img[key] = len(self.js["textures"]) - 1
        return self._img[key]

    def material(self, name, rgb=(0.8, 0.8, 0.8), rough=0.8, metal=0.0, spec=None, tex=None, emissive=None, emissive_strength=None,
                 double=True, alpha=1.0, extras=None):
        if name in self._mat:
            return self._mat[name]
        pbr = {"baseColorFactor": [float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha)], "roughnessFactor": float(rough), "metallicFactor": float(metal)}
        if tex is not None:
            pbr["baseColorTexture"] = {"index": tex}
        m = {"name": name, "pbrMetallicRoughness": pbr, "doubleSided": bool(double)}
        if alpha < 1.0:
            m["alphaMode"] = "BLEND"
        ext = {}
        if spec:
            ext["KHR_materials_specular"] = spec
            self.ext.add("KHR_materials_specular")
        if emissive:
            m["emissiveFactor"] = [float(v) for v in emissive]
            if emissive_strength and emissive_strength != 1.0:
                ext["KHR_materials_emissive_strength"] = {"emissiveStrength": float(emissive_strength)}
                self.ext.add("KHR_materials_emissive_strength")
        if ext:
            m["extensions"] = ext
        if extras:
            m["extras"] = extras
        self.js["materials"].append(m)
        self._mat[name] = len(self.js["materials"]) - 1
        return self._mat[name]

    def mesh(self, name, prims):
        """prims: list of dict(pos (n,3) f32, nrm (n,3)|None, uv (n,2)|None, idx (m,) u32, material int)"""
        P = []
        for p in prims:
            at = {"POSITION": self._acc(p["pos"].astype(np.float32), "VEC3", 34962, True)}
            if p.get("nrm") is not None:
                at["NORMAL"] = self._acc(p["nrm"].astype(np.float32), "VEC3", 34962)
            if p.get("uv") is not None:
                at["TEXCOORD_0"] = self._acc(p["uv"].astype(np.float32), "VEC2", 34962)
            idx = p["idx"].astype(np.uint32)
            if len(p["pos"]) < 65535:
                idx = idx.astype(np.uint16)
            P.append({"attributes": at, "indices": self._acc(idx, "SCALAR", 34963), "material": p["material"], "mode": 4})
        self.js["meshes"].append({"name": name, "primitives": P})
        return len(self.js["meshes"]) - 1

    def node(self, name, mesh=None, T=None, R=None, S=None, children=None, extras=None, root=True):
        n = {"name": name}
        if mesh is not None:
            n["mesh"] = mesh
        if T is not None and any(abs(v) > 0 for v in T):
            n["translation"] = [float(v) for v in T]
        if R is not None:
            n["rotation"] = [float(v) for v in R]
        if S is not None:
            n["scale"] = [float(v) for v in S]
        if children:
            n["children"] = children
        if extras:
            n["extras"] = extras
        self.js["nodes"].append(n)
        i = len(self.js["nodes"]) - 1
        if root:
            self.js["scenes"][0]["nodes"].append(i)
        return i

    def instanced_node(self, name, mesh, T, R, S, extras=None, root=True):
        """EXT_mesh_gpu_instancing: T (n,3), R (n,4) xyzw, S (n,3)"""
        self.ext.add("EXT_mesh_gpu_instancing")
        n = {"name": name, "mesh": mesh, "extensions": {"EXT_mesh_gpu_instancing": {"attributes": {
            "TRANSLATION": self._acc(np.asarray(T, np.float32), "VEC3", minmax=True),
            "ROTATION": self._acc(np.asarray(R, np.float32), "VEC4"),
            "SCALE": self._acc(np.asarray(S, np.float32), "VEC3")}}}}
        if extras:
            n["extras"] = extras
        self.js["nodes"].append(n)
        i = len(self.js["nodes"]) - 1
        if root:
            self.js["scenes"][0]["nodes"].append(i)
        return i

    def write(self, path, extras=None):
        if extras:
            self.js["asset"]["extras"] = extras
        if self.ext:
            self.js["extensionsUsed"] = sorted(self.ext)
        for k in ("images", "textures", "samplers", "materials", "meshes"):
            if k in self.js and not self.js[k]:
                del self.js[k]
        while len(self.blob) % 4:
            self.blob += b"\0"
        self.js["buffers"][0]["byteLength"] = len(self.blob)
        j = json.dumps(self.js, separators=(",", ":")).encode("utf-8")
        j += b" " * ((4 - len(j) % 4) % 4)
        total = 12 + 8 + len(j) + 8 + len(self.blob)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(j), 0x4E4F534A)); f.write(j)
            f.write(struct.pack("<II", len(self.blob), 0x004E4942)); f.write(bytes(self.blob))
        return total


def palette_material(w, pal, role, textures_dir=None, tex_override=None, prt_safe=False):
    """add palette role `role` as a glTF material on writer w (base colour texture when the role has one).
    prt_safe: core glTF only - PRT's glTF decoder (PyPRT 1.12) rejects KHR_materials_specular / emissive_strength."""
    r = pal["roles"][role]
    tex = tex_override
    if tex is None and r.get("texture") and textures_dir:
        p = os.path.join(textures_dir, r["texture"])
        tex = w.image(os.path.basename(p), open(p, "rb").read(), "image/jpeg")
    # a ground tile carries the whole colour (factor white); an asset texture with a palette colour is a tint mask (factor = colour)
    rgb = r["rgb"] if r["rgb"] is not None and (tex is None or tex_override is not None) else [1.0, 1.0, 1.0]
    g = r.get("gltf") or {}
    return w.material(role if not role.startswith("ctx_") else r["material"], rgb, r["roughness"], r["metallic"],
                      spec=None if prt_safe else g.get("KHR_materials_specular"), tex=tex,
                      emissive=g.get("emissiveFactor"), emissive_strength=None if prt_safe else (g.get("KHR_materials_emissive_strength") or {}).get("emissiveStrength"),
                      extras={"palette_role": role, "source": r.get("source", "")[:160]})


def flat_normals(pos, idx):
    """per-vertex normals by area-weighted face normals"""
    n = np.zeros_like(pos, dtype=np.float64)
    t = idx.reshape(-1, 3)
    a, b, c = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(n, t[:, k], fn)
    l = np.linalg.norm(n, axis=1)
    l[l == 0] = 1.0
    return (n / l[:, None]).astype(np.float32)


def glb_stats(path):
    """draw batches (primitives the renderer draws, instancing counted once), stored and drawn triangles"""
    g = GLB(path)
    js = g.js; acc = js.get("accessors", [])
    tri = [[(acc[p["indices"]]["count"] if "indices" in p else acc[p["attributes"]["POSITION"]]["count"]) // 3 for p in m["primitives"]] for m in js.get("meshes", [])]
    drawn = batches = inst = 0
    for n in js.get("nodes", []):
        if "mesh" not in n:
            continue
        k = 1
        e = (n.get("extensions") or {}).get("EXT_mesh_gpu_instancing")
        if e:
            k = acc[e["attributes"]["TRANSLATION"]]["count"]
        inst += k; drawn += k * sum(tri[n["mesh"]]); batches += len(tri[n["mesh"]])
    return {"bytes": os.path.getsize(path), "gzip9_bytes": gz_size(path), "meshes": len(js.get("meshes", [])), "objects": inst,
            "draw_batches": batches, "triangles_stored": sum(sum(t) for t in tri), "triangles_drawn": drawn,
            "materials": len(js.get("materials", [])), "images": len(js.get("images", [])), "extensionsUsed": js.get("extensionsUsed", [])}


def quat_y(theta_rad):
    """quaternion (x, y, z, w) for a rotation about +Y"""
    return (0.0, math.sin(theta_rad / 2.0), 0.0, math.cos(theta_rad / 2.0))
