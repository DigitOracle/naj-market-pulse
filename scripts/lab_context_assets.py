"""LAB (context / scenery, research only): the insert assets of lab_context.cga, re-materialed FROM THE PALETTE.

CGA cannot re-colour one material of a multi-material asset (set(material.*) after i() hits every part), so the
palette is baked into the assets instead: every asset here carries material names = palette roles (veg_palm_frond,
prop_lamp_body ...) with the palette's colour / roughness / metallic. CityEngine, its Datasmith export and the web GLB
therefore all read the same values, and Unreal's Datasmith import gets them as material parameters.

  plants    ESRI.lib Webstyles/Vegetation/LowPoly/<species>.glb (Crown / Trunk)   -> palette foliage roles
  lamp      Unreal's own double-arm lamp, data/ce/_datasmith/bb_v1/v1_lamp_body.obj + v1_lamp_head.obj (UE cm -> m)
  planter   Unreal's planter box, data/ce/_datasmith/bb_v1/v1_planter.obj
  bollard   octagonal steel post, 0.16 m x 1.0 m (built here; Unreal v1 has none)
  street    ESRI.lib Webstyles/StreetScene Park_Bench_1 / Trash_Bin_1 / Bus_Stop_2 - LOD1 only (32-46 triangles);
            the MSFT_lod base mesh PRT would insert is 88-393 triangles
  cars      ESRI.lib Webstyles/Transportation, 5 models, LOD1 only (~100 triangles), turned so the long axis is +x
Read-only use of ESRI.lib (C:/Dev/ce2026_lab/ESRI.lib); nothing is written there.

  python scripts/lab_context_assets.py [businessbay]  -> data/lab/context/<slug>/assets/*.glb + assets.json
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_context_common as C

SLUG = (sys.argv[1:] or ["businessbay"])[0]
OUT = os.path.join(C.lab_dir(SLUG), "assets")
LIB = "C:/Dev/ce2026_lab/ESRI.lib/assets/Webstyles"
V1 = os.path.join(C.ROOT, "data", "ce", "_datasmith", "bb_v1")

PLANTS = {  # asset stem -> {source material name: palette role}
    "PhoenixDactylifera": {"Crown": "veg_palm_frond", "Trunk": "veg_palm_trunk"},
    "WashingtoniaFilifera": {"Crown": "veg_fan_frond", "Trunk": "veg_palm_trunk"},
    "AcaciaTortilis": {"Crown": "veg_tree_crown", "Trunk": "veg_tree_trunk"},
    "FicusBenjamina": {"Crown": "veg_tree_crown", "Trunk": "veg_tree_trunk"},
    "ParkinsoniaAculeata": {"Crown": "veg_tree_crown", "Trunk": "veg_tree_trunk"},
    "BuxusSempervirens": {"Crown": "veg_shrub", "Trunk": "veg_tree_trunk"},
}
STREET = {  # asset -> (file, palette role, turn long axis z->x)
    "bench": ("StreetScene/Park_Bench_1.glb", "prop_bench", False),
    "bin": ("StreetScene/Trash_Bin_1.glb", "prop_bin", False),
    "bus_shelter": ("StreetScene/Bus_Stop_2.glb", "prop_shelter", False),
    "car_0": ("Transportation/Toyota_Prius.glb", "prop_car_0", True),
    "car_1": ("Transportation/BMW_3-Series.glb", "prop_car_1", True),
    "car_2": ("Transportation/Ford_Edge.glb", "prop_car_2", True),
    "car_3": ("Transportation/Audi_A6.glb", "prop_car_3", True),
    "car_4": ("Transportation/Ford_Expedition.glb", "prop_car_4", True),
    # construction sites of L_BB_v1 (cranes + site kit), Esri stand-ins for Unreal's Sketchfab construction models
    "tower_crane": ("Transportation/Tower_Crane.glb", "prop_site", False),
    "site_0": ("Transportation/Cargo_Box.glb", "prop_site", True),
    "site_1": ("Transportation/Dumptruck.glb", "prop_site", True),
    "site_2": ("Transportation/Backhoe.glb", "prop_site", True),
    "site_3": ("Transportation/Bobcat.glb", "prop_site", True),
    "site_4": ("StreetScene/Jersey_Barrier.glb", "prop_site", False),
}


def read_obj(path):
    V, F = [], []
    for l in open(path, encoding="utf-8"):
        if l.startswith("v "):
            V.append([float(t) for t in l.split()[1:4]])
        elif l.startswith("f "):
            F.append([int(t.split("/")[0]) - 1 for t in l.split()[1:4]])
    V = np.array(V, np.float64)
    # UE cm (X east, Y south, Z up) -> asset metres (x = X, y = Z, z = Y)
    P = np.stack([V[:, 0], V[:, 2], V[:, 1]], 1) / 100.0
    idx = np.array(F, np.uint32).reshape(-1)
    # the swap of Y/Z mirrors the handedness: flip the winding so faces keep pointing outwards
    idx = idx.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
    return P.astype(np.float32), idx


def unshare(pos, idx):
    """one vertex per corner, so flat normals stay flat (box primitives)"""
    p = pos[idx]
    return p, np.arange(len(p), dtype=np.uint32)


def write_single(name, parts, pal, extras):
    """parts: list of (pos, idx, palette role, uv or None, texture bytes or None)"""
    w = C.GLBWriter("lab_context_assets")
    prims = []
    for pos, idx, role, uv, texb in parts:
        tex = w.image(name + "_" + role, texb[0], texb[1]) if texb else None
        m = C.palette_material(w, pal, role, tex_override=tex, prt_safe=True)
        if texb is None and pal["roles"][role]["rgb"] is None:
            raise SystemExit("%s: role %s has no colour and no texture" % (name, role))
        prims.append({"pos": pos, "nrm": C.flat_normals(pos, idx), "uv": uv, "idx": idx, "material": m})
    w.node(name, w.mesh(name, prims))
    p = os.path.join(OUT, name + ".glb")
    w.write(p, extras=extras)
    P = np.concatenate([q[0] for q in parts])
    return {"file": "assets/%s.glb" % name, "tris": int(sum(len(q[1]) for q in parts) // 3), "bytes": os.path.getsize(p),
            "bbox_min": [round(float(v), 3) for v in P.min(0)], "bbox_max": [round(float(v), 3) for v in P.max(0)],
            "materials": sorted({q[2] for q in parts})}


def plant(stem, mats, pal):
    g = C.GLB(os.path.join(LIB, "Vegetation", "LowPoly", stem + ".glb"))
    parts = []
    for ni, W in g.node_world():
        for p in g.js["meshes"][g.js["nodes"][ni]["mesh"]]["primitives"]:
            q = g.primitive(p)
            src = g.js["materials"][q["material"]]["name"]
            pos = (np.c_[q["pos"], np.ones(len(q["pos"]))] @ W.T)[:, :3].astype(np.float32)
            parts.append((pos, q["idx"], mats[src], None, None))
    return write_single(stem, parts, pal, {"source": "ESRI.lib Webstyles/Vegetation/LowPoly/%s.glb" % stem, "materials_from": "context_palette.json"})


def lod1(key, rel, role, turn, pal):
    g = C.GLB(os.path.join(LIB, rel))
    nodes = g.js["nodes"]
    # MSFT_lod: the base node's list runs high -> low; the last id is the coarsest real mesh (LOD1)
    bi = next(i for i, n in enumerate(nodes) if "mesh" in n and "MSFT_lod" in (n.get("extensions") or {}))
    ids = nodes[bi]["extensions"]["MSFT_lod"]["ids"]
    ni = ids[-1] if ids else bi                     # Jersey_Barrier ships one level only
    mesh = g.js["meshes"][nodes[ni]["mesh"]]
    parts = []
    for p in mesh["primitives"]:
        q = g.primitive(p)
        pos = q["pos"].astype(np.float64)
        if turn:     # rotate +90 deg about +Y: the long (z) axis becomes +x
            pos = np.stack([pos[:, 2], pos[:, 1], -pos[:, 0]], 1)
        texb = None
        mt = g.js["materials"][q["material"]] if q["material"] is not None else {}
        bct = (mt.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        if bct is not None:
            texb = g.image_bytes(g.js["textures"][bct["index"]]["source"])
            if (mt.get("extras") or {}).get("ESRI_externalColorMixMode") == "tint" and pal["roles"][role]["rgb"] is not None:
                texb = tint_mask(texb)
        parts.append((pos.astype(np.float32), q["idx"], role, q["uv"], texb))
    name = key
    info = write_single(name, parts, pal, {"source": "ESRI.lib Webstyles/%s, node %s (LOD1 of MSFT_lod)" % (rel, nodes[ni].get("name")),
                                           "turned_long_axis_to_x": turn})
    info["source_lod"] = nodes[ni].get("name")
    return info


def tint_mask(texb):
    """Esri 'tint' textures are painted red: keep the luminance, scaled so the body (the median) reads 1.0 - the
    material's base colour (the palette paint) then multiplies it, as CityEngine's tint does."""
    import io
    from PIL import Image
    im = np.asarray(Image.open(io.BytesIO(texb[0])).convert("RGB"), dtype=np.float64) / 255.0
    lin = np.where(im <= 0.04045, im / 12.92, ((im + 0.055) / 1.055) ** 2.4)
    L = lin @ np.array([0.2126, 0.7152, 0.0722])
    L = np.clip(L / max(np.median(L), 1e-3), 0.0, 1.0)
    s = np.where(L <= 0.0031308, 12.92 * L, 1.055 * L ** (1 / 2.4) - 0.055)
    out = io.BytesIO()
    Image.fromarray((s * 255 + 0.5).astype(np.uint8), "L").convert("RGB").save(out, "JPEG", quality=88)
    return out.getvalue(), "image/jpeg"


class Prim:
    """tiny primitive builder (metres, y up) - one list of triangles per palette role"""

    def __init__(self):
        self.parts = {}

    def tri(self, role, a, b, c):
        self.parts.setdefault(role, []).extend([a, b, c])

    def quad(self, role, a, b, c, d, both=False):
        self.tri(role, a, b, c); self.tri(role, a, c, d)
        if both:
            self.tri(role, a, c, b); self.tri(role, a, d, c)

    def box(self, role, x0, y0, z0, x1, y1, z1):
        P = [(x0, z0), (x0, z1), (x1, z1), (x1, z0)]
        for k in range(4):
            (ax, az), (bx, bz) = P[k], P[(k + 1) % 4]
            self.quad(role, (ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az))
        self.quad(role, (x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0))
        self.quad(role, (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))

    def frustum(self, role, r0, r1, y0, y1, n=8, cap=True):
        ring = lambda r, y: [(r * math.cos(2 * math.pi * k / n), y, r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        a, b = ring(r0, y0), ring(r1, y1)
        for k in range(n):
            self.quad(role, a[k], b[k], b[(k + 1) % n], a[(k + 1) % n])
        if cap:
            for k in range(n):
                self.tri(role, (0, y1, 0), b[(k + 1) % n], b[k])

    def cone(self, role, r, y_rim, y_apex, n=8):
        rim = [(r * math.cos(2 * math.pi * k / n), y_rim, r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        for k in range(n):
            self.tri(role, (0, y_apex, 0), rim[(k + 1) % n], rim[k])
            self.tri(role, (0, y_apex - 0.01, 0), rim[k], rim[(k + 1) % n])     # underside

    def write(self, name, pal, src):
        parts = []
        for role, pts in self.parts.items():
            P = np.array(pts, np.float32)
            I = np.arange(len(P), dtype=np.uint32)
            # the helpers wind faces counter-clockwise seen from outside in a y-up right-handed frame
            parts.append((P, I, role, None, None))
        return write_single(name, parts, pal, {"source": src})


def cafe(pal):
    """the L_BB_v1 promenade cafe set, built as primitives (Unreal: Poly Haven gallinera table/chair + Sketchfab parasol)"""
    out = {}
    t = Prim()
    t.frustum("prop_cafe_table", 0.35, 0.35, 0.72, 0.75)                 # round top, 0.70 m
    t.frustum("prop_cafe_chair", 0.03, 0.03, 0.05, 0.72, n=6, cap=False)   # pole
    t.frustum("prop_cafe_chair", 0.22, 0.20, 0.0, 0.05)                  # foot
    out["cafe_table"] = t.write("cafe_table", pal, "primitive bistro table 0.75 m")
    c = Prim()
    c.box("prop_cafe_chair", -0.21, 0.43, -0.21, 0.21, 0.47, 0.21)        # seat; the sitter faces +x
    c.box("prop_cafe_chair", -0.23, 0.47, -0.20, -0.19, 0.90, 0.20)       # back rest on -x
    for sx in (-0.19, 0.17):
        for sz in (-0.19, 0.17):
            c.box("prop_cafe_chair", sx, 0.0, sz, sx + 0.025, 0.43, sz + 0.025)
    out["cafe_chair"] = c.write("cafe_chair", pal, "primitive bistro chair 0.9 m, front +x")
    u = Prim()
    u.frustum("prop_cafe_chair", 0.025, 0.025, 0.0, 2.6, n=6, cap=False)  # mast
    u.cone("prop_umbrella", 1.3, 2.2, 2.6)                               # canopy, 2.6 m across
    out["umbrella"] = u.write("umbrella", pal, "primitive octagonal parasol 2.6 m")
    k = Prim()
    k.frustum("prop_pot", 0.17, 0.24, 0.0, 0.45)
    out["pot"] = k.write("pot", pal, "primitive clay pot 0.45 m")
    return out


def bollard(pal):
    r, h, n = 0.08, 1.0, 8
    pos, idx = [], []
    ring = [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    for k in range(n):
        (x0, z0), (x1, z1) = ring[k], ring[(k + 1) % n]
        b = len(pos)
        pos += [(x0, 0, z0), (x1, 0, z1), (x1, h, z1), (x0, h, z0)]
        idx += [b, b + 2, b + 1, b, b + 3, b + 2]
    c = len(pos)
    pos.append((0, h + 0.03, 0))
    for k in range(n):
        (x0, z0), (x1, z1) = ring[k], ring[(k + 1) % n]
        b = len(pos); pos += [(x0, h, z0), (x1, h, z1)]
        idx += [c, b + 1, b]
    P, I = unshare(np.array(pos, np.float32), np.array(idx, np.uint32))
    return write_single("bollard", [(P, I, "prop_bollard", None, None)], pal, {"source": "lab_context_assets.py octagonal post"})


def main():
    os.makedirs(OUT, exist_ok=True)
    pal = C.load_palette(SLUG)
    info = {}
    for stem, mats in PLANTS.items():
        info[stem] = plant(stem, mats, pal)
    for key, (rel, role, turn) in STREET.items():
        info[key] = lod1(key, rel, role, turn, pal)
    body_p, body_i = read_obj(os.path.join(V1, "v1_lamp_body.obj"))
    head_p, head_i = read_obj(os.path.join(V1, "v1_lamp_head.obj"))
    bp, bi = unshare(body_p, body_i); hp, hi = unshare(head_p, head_i)
    info["lamp_v1"] = write_single("lamp_v1", [(bp, bi, "prop_lamp_body", None, None), (hp, hi, "prop_lamp_head", None, None)], pal,
                                   {"source": "Unreal L_BB_v1 lamp: bb_v1_prep.prop_meshes -> v1_lamp_body.obj + v1_lamp_head.obj (arms along +x)"})
    pp, pi = read_obj(os.path.join(V1, "v1_planter.obj"))
    pp, pi = unshare(pp, pi)
    info["planter_v1"] = write_single("planter_v1", [(pp, pi, "prop_planter", None, None)], pal, {"source": "Unreal L_BB_v1 planter: v1_planter.obj"})
    info["bollard"] = bollard(pal)
    info.update(cafe(pal))
    json.dump(info, open(os.path.join(OUT, "assets.json"), "w", encoding="utf-8"), indent=1)
    for k, v in info.items():
        print("  %-22s %5d tris %7d B  bbox %s .. %s  %s" % (k, v["tris"], v["bytes"], v["bbox_min"], v["bbox_max"], v["materials"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
