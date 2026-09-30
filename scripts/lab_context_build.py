"""LAB (context / scenery, research only): run lab_context.rpk headless (PyPRT 1.12) on the prepared shapes and write
the web GLBs + a Datasmith export of the SAME generation, and a manifest a renderer can load without reading code.

  ground_<slug>_v5.glb        sand, water, canal, quay, plots, landuse, podium, pavement, promenade, asphalt, markings,
                              kerbs, hoardings, quay railing - one mesh per palette role (material "ctx_<role>")
  vegetation_<slug>_v5.glb    palms, trees, shrubs                         } EXT_mesh_gpu_instancing: one instanced node per
  furniture_<slug>_v5.glb     benches, bins, bollards, shelters, planters,  } (asset, klass); klass = film (what Unreal's
                              cafe tables / chairs / parasols / pots       }  Business Bay film placed) | json (the city JSONs)
  props_<slug>_v5.glb         street lights, cars, tower cranes, site kit  }
  *_meshopt.glb               the same through gltf-transform meshopt (the viewer registers MeshoptDecoder)
  manifest.json               every GLB, its layer, triangles (stored / drawn), draw calls, bytes, what it holds
  datasmith/                  com.esri.prt.unreal.encoder (Datasmith) of the same shapes and rule: useUnrealBaseMaterials,
                              instancing HISM, metadata all, globalOffset = the Unreal level frame (X = E - 328289, Y = 2784598 - N)
  build_stats.json            the same numbers + the placement cross-check
All GLBs are in the LOCAL v5 frame of data/ce/<slug>/origin_v5.json - the frame of data/ce/_glb/sky_<slug>_v5_0.glb.

Why a post-pass: PyPRT's GLTFEncoder writes baseColor / opacity / colour map only (checked: roughness 0.3, metallic
0.5, emissive set in CGA come back as defaults although CGAPrint shows the values at runtime) and one node per object.
The post-pass (1) merges the ground per material, (2) turns the per-object nodes into EXT_mesh_gpu_instancing, and
(3) re-applies the palette by MATERIAL NAME (roughness, metallic, KHR_materials_specular, emissive strength, opacity).
The names come from the rule / the palette-baked assets, so nothing is matched by guesswork. Geometry and transforms are PRT's.

  python scripts/lab_context_build.py [businessbay] [--no-datasmith] [--no-meshopt]
"""
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_context_common as C

args = [a for a in sys.argv[1:] if not a.startswith("--")]
SLUG = (args or ["businessbay"])[0]
OUT = C.lab_dir(SLUG)
RAW = os.path.join(OUT, "_raw")
RPK = os.path.join(OUT, "lab_context.rpk")
# asset -> (layer, pivot mode). pivot mirrors lab_context_rpk.SPECIES: "origin" = the asset origin sits on the point
ASSETS = {
    "PhoenixDactylifera": ("vegetation", "origin"), "WashingtoniaFilifera": ("vegetation", "origin"), "AcaciaTortilis": ("vegetation", "origin"),
    "FicusBenjamina": ("vegetation", "origin"), "ParkinsoniaAculeata": ("vegetation", "origin"), "BuxusSempervirens": ("vegetation", "origin"),
    "bench": ("furniture", "centre"), "bin": ("furniture", "centre"), "bus_shelter": ("furniture", "centre"), "bollard": ("furniture", "centre"),
    "planter_v1": ("furniture", "centre"), "cafe_table": ("furniture", "centre"), "cafe_chair": ("furniture", "centre"),
    "umbrella": ("furniture", "centre"), "pot": ("furniture", "centre"),
    "lamp_v1": ("props", "centre"), "tower_crane": ("props", "origin"),
    **{"car_%d" % k: ("props", "centre") for k in range(5)}, **{"site_%d" % k: ("props", "centre") for k in range(5)},
}
ASSET_OF = {"date_palm": "PhoenixDactylifera", "washingtonia": "WashingtoniaFilifera", "acacia": "AcaciaTortilis", "ficus": "FicusBenjamina",
            "parkinsonia": "ParkinsoniaAculeata", "buxus": "BuxusSempervirens", "lamp": "lamp_v1", "bench": "bench", "bin": "bin",
            "bus_shelter": "bus_shelter", "bollard": "bollard", "planter": "planter_v1", "cafe_table": "cafe_table", "cafe_chair": "cafe_chair",
            "umbrella": "umbrella", "pot": "pot", "crane": "tower_crane",
            **{"car_%d" % k: "car_%d" % k for k in range(5)}, **{"site_%d" % k: "site_%d" % k for k in range(5)}}
TOPPER_OF = {"planter": "BuxusSempervirens", "pot": "BuxusSempervirens"}      # the plant the rule sets on top
LAYERS = ["vegetation", "furniture", "props"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def shapes_of(path):
    import pyprt
    d = json.load(open(path, encoding="utf-8"))
    sh = d["shapes"]
    out = []
    for s in sh:
        if s.get("holes"):
            out.append(pyprt.InitialShape(s["verts"], s["indices"], s["face_counts"], s["holes"]))
        else:
            out.append(pyprt.InitialShape(s["verts"], s["indices"], s["face_counts"]))
    return d, sh, out


def prt_gltf(shapes, attrs, base, gran):
    import pyprt
    os.makedirs(RAW, exist_ok=True)
    for f in glob.glob(os.path.join(RAW, base + "*")):
        os.remove(f)
    t = time.time()
    pyprt.ModelGenerator(shapes).generate_model(attrs, RPK, "com.esri.prt.codecs.GLTFEncoder",
                                                {"outputPath": RAW, "baseName": base, "meshGranularity": gran, "outputFormat": "GLB"})
    parts = sorted(glob.glob(os.path.join(RAW, base + "_*.glb")), key=lambda p: (len(p), p))
    err = open(os.path.join(RAW, "CGAError.txt"), encoding="utf-8", errors="replace").read() if os.path.exists(os.path.join(RAW, "CGAError.txt")) else ""
    kinds = Counter(l.split()[0] for l in err.splitlines() if l[:1].isalpha())
    msgs = Counter(re.sub(r"\d+", "#", l.split("' '")[-1])[:110] for l in err.splitlines() if l[:1].isalpha() and "CGAC version" not in l)
    return parts, round(time.time() - t, 1), {"by_kind": dict(kinds), "cgac_version_warnings": err.count("CGAC version"), "other": dict(msgs.most_common(6))}


# ------------------------------------------------------------------------------------------------------------ ground
def build_ground(pal):
    d, sh, shapes = shapes_of(os.path.join(OUT, "ground_shapes.json"))
    attrs = [dict(s["attrs"]) for s in sh]
    log("ground: %d shapes -> PRT (AS_GENERATED)" % len(shapes))
    parts, secs, errs = prt_gltf(shapes, attrs, "ground", "AS_GENERATED")
    log("  PRT %.1f s, %d part(s), CGAError.txt %s" % (secs, len(parts), errs["by_kind"]))
    acc = defaultdict(lambda: {"pos": [], "uv": [], "idx": [], "n": 0})
    for p in parts:
        g = C.GLB(p)
        for ni, W in g.node_world():
            for pr in g.js["meshes"][g.js["nodes"][ni]["mesh"]]["primitives"]:
                q = g.primitive(pr)
                name = g.js["materials"][q["material"]]["name"] if q["material"] is not None else "?"
                a = acc[name]
                pos = q["pos"].astype(np.float64)
                if not np.allclose(W, np.eye(4)):
                    pos = (np.c_[pos, np.ones(len(pos))] @ W.T)[:, :3]
                a["pos"].append(pos); a["uv"].append(q["uv"] if q["uv"] is not None else np.zeros((len(pos), 2), np.float32))
                a["idx"].append(q["idx"].astype(np.int64) + a["n"]); a["n"] += len(pos)
    w = C.GLBWriter("lab_context_build (PyPRT 1.12 + lab_context.rpk)")
    roles = sorted(acc, key=lambda m: pal["roles"].get(m, {}).get("draw_order", 99))
    per = {}
    for role in roles:
        a = acc[role]
        if role not in pal["roles"]:
            log("  WARNING: material %s is not a palette role - skipped" % role); continue
        pos = np.concatenate(a["pos"]).astype(np.float32); uv = np.concatenate(a["uv"]).astype(np.float32)
        idx = np.concatenate(a["idx"]).astype(np.uint32)
        r = pal["roles"][role]
        if r.get("y_m") is not None:          # flat layers: PRT writes 3 vertices per triangle - weld identical (pos, uv) corners
            key = np.round(np.c_[pos, uv * 64.0], 3)
            _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
            pos, uv, idx = pos[first], uv[first], inv.reshape(-1)[idx].astype(np.uint32)
        nrm = C.flat_normals(pos, idx) if r.get("y_m") is None else np.tile(np.array([[0, 1, 0]], np.float32), (len(pos), 1))
        m = C.palette_material(w, pal, role, textures_dir=OUT)
        me = w.mesh(role, [{"pos": pos, "nrm": nrm, "uv": uv if r.get("texture") else None, "idx": idx, "material": m}])
        w.node(role, me, extras={"palette_role": role, "draw_order": r["draw_order"], "y_m": r["y_m"], "layer": "ground"})
        t = idx.reshape(-1, 3)
        area = float(np.linalg.norm(np.cross(pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]]), axis=1).sum() / 2.0)
        per[role] = {"triangles": int(len(t)), "vertices": int(len(pos)), "area_m2": round(area), "y_m": [round(float(pos[:, 1].min()), 3), round(float(pos[:, 1].max()), 3)]}
    outp = os.path.join(OUT, "ground_%s_v5.glb" % SLUG)
    w.write(outp, extras={"lab": "context", "layer": "ground", "slug": SLUG, "frame": pal["frame"], "origin_ce_xyz": d["origin_ce_xyz"], "research_only": True,
                          "draw_order": {r: pal["roles"][r]["draw_order"] for r in per},
                          "note": "stack heights are centimetres apart: draw with polygonOffset by draw_order (manifest.json)"})
    return outp, {"prt_s": secs, "prt_parts": len(parts), "cga_log": errs, "per_role": per}


# ------------------------------------------------------------------------------------------------------------ dressing
def base_name(n, known):
    """PRT de-duplicates names by appending _<k> (PhoenixDactylifera_1 = its second part, prop_car_2 = the third car
    texture); 'car_1' itself is a real asset name - strip only when the stripped name is known and the full one is not"""
    if n in known:
        return n
    b = re.sub(r"_\d+$", "", n)
    return b if b in known else n


def generate_dressing(pal):
    d, sh, shapes = shapes_of(os.path.join(OUT, "instance_shapes.json"))
    attrs = [dict(s["attrs"]) for s in sh]
    log("dressing: %d shapes, %d objects -> PRT (INSTANCED)" % (len(shapes), sum(s["count"] for s in sh)))
    parts, secs, errs = prt_gltf(shapes, attrs, "dressing", "INSTANCED")
    log("  PRT %.1f s, %d part(s), CGAError.txt %s" % (secs, len(parts), errs["by_kind"]))
    groups = {}
    for p in parts:
        g = C.GLB(p)
        for ni, W in g.node_world():
            mesh = g.js["meshes"][g.js["nodes"][ni]["mesh"]]
            key = (os.path.basename(p),) + tuple((pr["attributes"]["POSITION"], pr.get("indices"), pr.get("material")) for pr in mesh["primitives"])
            if key not in groups:
                prims = []
                for pr in mesh["primitives"]:
                    q = g.primitive(pr)
                    mt = g.js["materials"][q["material"]] if q["material"] is not None else {"name": "?"}
                    tex = None
                    bct = (mt.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
                    if bct is not None:
                        tex = g.image_bytes(g.js["textures"][bct["index"]]["source"])
                    q["mname"] = base_name(mt.get("name", "?"), pal["roles"]); q["tex"] = tex
                    prims.append(q)
                groups[key] = {"name": base_name(mesh.get("name", "?"), ASSETS), "prims": prims, "M": []}
            groups[key]["M"].append(W)
    order = sorted(groups.values(), key=lambda G: (G["name"], -len(G["M"])))
    merged = []                                   # parts of one asset (crown + trunk) share the instance list: one mesh, one node
    for G in order:
        prev = merged[-1] if merged else None
        if prev and prev["name"] == G["name"] and len(prev["M"]) == len(G["M"]) and np.allclose(np.array(prev["M"]), np.array(G["M"]), atol=1e-4):
            prev["prims"] = prev["prims"] + G["prims"]
        else:
            merged.append({"name": G["name"], "prims": list(G["prims"]), "M": np.array(G["M"])})
    return merged, {"prt_s": secs, "prt_parts": len(parts), "cga_log": errs}


def reference_points(G, assets):
    """where the rule put each object: the asset origin (plants, crane mast) or its bbox centre (Unreal's scatter)"""
    a = assets.get(G["name"])
    pivot = ASSETS.get(G["name"], ("?", "centre"))[1]
    ref = np.array([0.0, 0.0, 0.0, 1.0]) if (pivot == "origin" or a is None) else \
        np.array([(a["bbox_min"][0] + a["bbox_max"][0]) / 2, 0.0, (a["bbox_min"][2] + a["bbox_max"][2]) / 2, 1.0])
    M = G["M"]
    P = M @ ref
    S = np.linalg.norm(M[:, :3, :3], axis=1)
    R3 = M[:, :3, :3] / S[:, None, :]
    head = np.degrees(np.arctan2(R3[:, 2, 0], R3[:, 0, 0]))            # the asset +x in (x, z): the UE heading
    return np.stack([P[:, 0], P[:, 2], head, S[:, 1]], 1), R3, S


def match(G, I, rows_by_asset):
    """each PRT instance -> its placement row (nearest within 5 cm; heading breaks ties between source duplicates)"""
    rs = rows_by_asset.get(G["name"], [])
    klass = np.array(["?"] * len(I), dtype=object)
    if not rs:
        return klass, 0
    P = np.array([[r[2], r[3]] for r in rs]); H = np.array([r[4] for r in rs])
    cell = defaultdict(list)
    for k, (x, z) in enumerate(P):
        cell[(int(math.floor(x)), int(math.floor(z)))].append(k)
    miss = 0
    for n, (x, z, h, _s) in enumerate(I):
        cx, cz = int(math.floor(x)), int(math.floor(z))
        cand = [k for dx in (-1, 0, 1) for dz in (-1, 0, 1) for k in cell.get((cx + dx, cz + dz), [])]
        cand = [k for k in cand if (P[k, 0] - x) ** 2 + (P[k, 1] - z) ** 2 < 0.05 ** 2]
        if not cand:
            miss += 1; continue
        k = min(cand, key=lambda k: abs((H[k] - h + 180.0) % 360.0 - 180.0))
        klass[n] = rs[k][11] if len(rs[k]) > 11 else "json"
    return klass, miss


def write_layers(pal, merged, assets):
    pl = json.load(open(os.path.join(OUT, "placements.json"), encoding="utf-8"))
    rows_by_asset = defaultdict(list)
    for r in pl["rows"]:
        rows_by_asset[ASSET_OF[r[1]]].append(r)
        if r[1] in TOPPER_OF:
            rows_by_asset[TOPPER_OF[r[1]]].append(r)
    writers = {L: C.GLBWriter("lab_context_build (PyPRT 1.12 + lab_context.rpk, INSTANCED -> EXT_mesh_gpu_instancing)") for L in LAYERS}
    nodes = {L: defaultdict(list) for L in LAYERS}
    per = {L: {} for L in LAYERS}
    inst_rows = {}
    unmatched = {}
    for G in merged:
        layer = ASSETS.get(G["name"], ("props", "centre"))[0]
        w = writers[layer]
        I, R3, S = reference_points(G, assets)
        if G["name"] not in inst_rows:
            inst_rows[G["name"]] = I
        klass, miss = match(G, I, rows_by_asset)
        if miss:
            unmatched[G["name"]] = unmatched.get(G["name"], 0) + miss
        th = np.arctan2(-R3[:, 2, 0], R3[:, 0, 0])                   # rotation about +Y (the rule only turns about up)
        Q = np.stack([np.zeros_like(th), np.sin(th / 2), np.zeros_like(th), np.cos(th / 2)], 1)
        T = G["M"][:, :3, 3]
        prims = []
        for q in G["prims"]:
            role = q["mname"]
            if role not in pal["roles"]:
                log("  WARNING: %s material %s not in the palette" % (G["name"], role))
            tex = w.image("%s_%s" % (G["name"], role), q["tex"][0], q["tex"][1]) if q["tex"] else None
            mat = C.palette_material(w, pal, role, tex_override=tex) if role in pal["roles"] else w.material(role)
            nrm = q["nrm"] if q["nrm"] is not None else C.flat_normals(q["pos"], q["idx"])
            prims.append({"pos": q["pos"], "nrm": nrm, "uv": q["uv"] if tex is not None else None, "idx": q["idx"], "material": mat})
        me = w.mesh(G["name"], prims)
        tris = int(sum(len(q["idx"]) for q in G["prims"]) // 3)
        e = per[layer].setdefault(G["name"], {"instances": 0, "film": 0, "json": 0, "triangles_per_object": tris, "draw_calls": 0})
        for kl in ("film", "json", "?"):
            sel = np.nonzero(klass == kl)[0]
            if not len(sel):
                continue
            name = "%s__%s" % (G["name"], "unmatched" if kl == "?" else kl)
            ni = w.instanced_node(name, me, T[sel], Q[sel], S[sel], root=False,
                                  extras={"asset": G["name"], "layer": layer, "klass": kl, "instances": int(len(sel))})
            nodes[layer][kl].append(ni)
            e["instances"] += int(len(sel)); e["draw_calls"] += len(prims)
            if kl in ("film", "json"):
                e[kl] += int(len(sel))
    outs = {}
    for L in LAYERS:
        w = writers[L]
        kids = [w.node("%s_%s" % (L, kl), children=ns, root=False, extras={"layer": L, "klass": kl}) for kl, ns in sorted(nodes[L].items())]
        w.node("lab_context_%s" % L, children=kids, extras={"lab": "context", "layer": L})
        p = os.path.join(OUT, "%s_%s_v5.glb" % (L, SLUG))
        w.write(p, extras={"lab": "context", "layer": L, "slug": SLUG, "frame": pal["frame"], "origin_ce_xyz": pl["origin_ce_xyz"], "research_only": True,
                           "placements": "placements.json (source %s)" % pl.get("source"), "klass": "film = placed by Unreal's Business Bay film (bb_v1_plan.json), json = city JSONs"})
        outs[L] = p
    return outs, per, inst_rows, unmatched


def cross_check(inst_rows):
    """every placement row vs the PRT instance the rule made for it: position, heading"""
    pl = json.load(open(os.path.join(OUT, "placements.json"), encoding="utf-8"))
    rows = defaultdict(list)
    for r in pl["rows"]:
        rows[ASSET_OF[r[1]]].append(r)
    out = {}
    for asset, rs in rows.items():
        I = inst_rows.get(asset)
        if I is None or not len(I):
            out[asset] = {"placements": len(rs), "instances": 0}; continue
        cell = defaultdict(list)
        for k, (x, z) in enumerate(I[:, :2]):
            cell[(int(math.floor(x)), int(math.floor(z)))].append(k)
        worst = 0.0; yaw_err = 0.0; matched = 0; dup = 0
        for r in rs:
            cx, cz = int(math.floor(r[2])), int(math.floor(r[3]))
            cand = [k for dx in (-1, 0, 1) for dz in (-1, 0, 1) for k in cell.get((cx + dx, cz + dz), [])]
            d2 = {k: (I[k, 0] - r[2]) ** 2 + (I[k, 1] - r[3]) ** 2 for k in cand}
            near = [k for k, v in d2.items() if v < 0.05 ** 2]
            if len(near) > 1:
                dup += 1
            dy = lambda j: abs((I[j, 2] - r[4] + 180.0) % 360.0 - 180.0)
            if near:
                j = min(near, key=dy); matched += 1
                worst = max(worst, math.sqrt(d2[j])); yaw_err = max(yaw_err, dy(j))
            else:
                worst = max(worst, math.sqrt(min(d2.values())) if d2 else 99.0)
        out[asset] = {"placements": len(rs), "instances": int(len(I)), "matched_within_5cm": int(matched), "max_position_error_m": round(worst, 4),
                      "max_heading_error_deg": round(float(yaw_err), 3), "source_rows_sharing_a_spot": dup}
    return out


def meshopt(src):
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        return None
    dst = src.replace(".glb", "_meshopt.glb")
    r = subprocess.run([npx, "--yes", "@gltf-transform/cli@4.5.1", "meshopt", src, dst], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    if r.returncode != 0:
        log("  meshopt failed: %s" % (r.stdout + r.stderr)[-400:]); return None
    return dst


def datasmith(pal):
    """the SAME shapes and rule through PRT's Datasmith encoder - what CityEngine 2026's UnrealExportModelSettings
    (UseUnrealBaseMaterials, Instancing, Metadata) writes, headless"""
    import pyprt
    ddir = os.path.join(OUT, "datasmith")
    if os.path.isdir(ddir):
        shutil.rmtree(ddir)
    os.makedirs(ddir)
    fr = C.Frame(SLUG)
    off = [fr.origin_ce_xyz[0] - C.UE_E0, 0.0, fr.origin_ce_xyz[2] + C.UE_N0]      # local -> CE frame -> Unreal level frame
    res = {"global_offset_m": off}
    for part in ("ground", "instance"):
        d, sh, shapes = shapes_of(os.path.join(OUT, "%s_shapes.json" % part))
        attrs = [dict(s["attrs"]) for s in sh]
        t = time.time()
        pyprt.ModelGenerator(shapes).generate_model(attrs, RPK, "com.esri.prt.unreal.encoder",
                                                    {"outputPath": ddir, "baseName": "lab_context_%s_%s" % (SLUG, part), "meshMerging": "perInitialShape",
                                                     "instancing": "instancingHISM", "useUnrealBaseMaterials": True, "metadata": "all",
                                                     "globalOffset": off})
        p = os.path.join(ddir, "lab_context_%s_%s.udatasmith" % (SLUG, part))
        x = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        tags = Counter(re.findall(r"<([A-Za-z]+)[ >]", x))
        res[part] = {"udatasmith": os.path.relpath(p, C.ROOT).replace("\\", "/") if x else None, "seconds": round(time.time() - t, 1),
                     "bytes": os.path.getsize(p) if x else 0, "static_meshes": tags.get("StaticMesh", 0), "mesh_actors": tags.get("ActorMesh", 0),
                     "hism_actors": tags.get("ActorHierarchicalInstancedStaticMesh", 0),
                     "hism_instances": sum(int(c) for c in re.findall(r'<Instances count="(\d+)"', x)),
                     "material_instances": tags.get("MaterialInstance", 0), "textures": tags.get("Texture", 0), "metadata_blocks": tags.get("MetaData", 0)}
    res["files"] = sum(len(fs) for _r, _d, fs in os.walk(ddir))
    res["bytes"] = sum(os.path.getsize(os.path.join(r, f_)) for r, _d, fs in os.walk(ddir) for f_ in fs)
    return res


def manifest(pal, stats):
    fr = C.Frame(SLUG)
    layers = []
    g = stats["ground"]
    layers.append({"layer": "ground", "file": os.path.basename(g["meshopt"]["glb"]) if g.get("meshopt") else os.path.basename(g["glb"]),
                   "file_uncompressed": os.path.basename(g["glb"]), "needs": ["MeshoptDecoder"] if g.get("meshopt") else [],
                   "bytes": g["meshopt"]["bytes"] if g.get("meshopt") else g["bytes"], "gzip_bytes": g["meshopt"]["gzip9_bytes"] if g.get("meshopt") else g["gzip9_bytes"],
                   "triangles": g["triangles_stored"], "draw_calls": g["draw_batches"], "materials": sorted(g["per_role"]),
                   "draw_order": {r: pal["roles"][r]["draw_order"] for r in g["per_role"]},
                   "render_hint": "flat layers cm apart: material.polygonOffset = true, polygonOffsetFactor = -1, polygonOffsetUnits = -6 x draw_order (node extras.draw_order); ctx_rail_glass is alpha-blended"})
    for L in LAYERS:
        s = stats[L]
        by = s["per_asset"]
        layers.append({"layer": L, "file": os.path.basename(s["glb"]), "needs": [], "extensions": s["extensionsUsed"],
                       "bytes": s["bytes"], "gzip_bytes": s["gzip9_bytes"], "instances": sum(v["instances"] for v in by.values()),
                       "instances_film": sum(v["film"] for v in by.values()), "instances_json": sum(v["json"] for v in by.values()),
                       "triangles_stored": s["triangles_stored"], "triangles_drawn": s["triangles_drawn"], "draw_calls": s["draw_batches"],
                       "by_asset": by,
                       "render_hint": "GLTFLoader turns EXT_mesh_gpu_instancing into THREE.InstancedMesh; set frustumCulled = false (instances span the district); "
                                      "node extras.klass: film = placed by Unreal's film, json = the city JSONs - hide 'json' nodes for strict film parity"})
    tot = {"triangles_stored": sum(l.get("triangles", 0) + l.get("triangles_stored", 0) for l in layers),
           "triangles_drawn": sum(l.get("triangles", 0) + l.get("triangles_drawn", 0) for l in layers),
           "draw_calls": sum(l["draw_calls"] for l in layers), "bytes": sum(l["bytes"] for l in layers), "gzip_bytes": sum(l["gzip_bytes"] for l in layers)}
    m = {"schema": "najma.context_manifest/1", "slug": SLUG, "built": stats["built"], "research_only": True,
         "frame": {"space": "local v5", "origin_v5": "data/ce/%s/origin_v5.json" % SLUG, "origin_ce_xyz": fr.origin_ce_xyz,
                   "contract": "CE-frame metres (x = easting, y = up, z = -northing) = vertex + origin_ce_xyz; place every file's scene in ONE group at origin_ce_xyz (float64)",
                   "same_frame_as": "data/ce/_glb/sky_%s_v5_0.glb" % SLUG, "land_level_y": 0.0,
                   "note": "Unreal L_BB_v1 heights: land (buildings, streets, dressing) at y = 0, canal water -0.90, city water -1.10, sand plane -1.20"},
         "layers": layers, "totals": tot, "palette": "context_palette.json", "placements": "placements.json",
         "placements_source": json.load(open(os.path.join(OUT, "placements.json"), encoding="utf-8")).get("source"),
         "rule": "lab_context.rpk (rules/lab_context.cga)", "datasmith": {k: v for k, v in (stats.get("datasmith") or {}).items() if k in ("ground", "instance")},
         "renders": sorted(os.path.basename(p) for p in glob.glob(os.path.join(OUT, "render_*.png")))}
    json.dump(m, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), indent=1)
    return m


def main():
    t0 = time.time()
    pal = C.load_palette(SLUG)
    assets = json.load(open(os.path.join(OUT, "assets", "assets.json"), encoding="utf-8"))
    for old in glob.glob(os.path.join(OUT, "dressing_%s_v5*.glb" % SLUG)):     # superseded by the per-layer files
        os.remove(old)
    gp, gs = build_ground(pal)
    merged, dstat = generate_dressing(pal)
    outs, per, inst_rows, unmatched = write_layers(pal, merged, assets)
    xc = cross_check(inst_rows)
    stats = {"slug": SLUG, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "rpk": os.path.relpath(RPK, C.ROOT).replace("\\", "/"),
             "ground": {"glb": os.path.relpath(gp, C.ROOT).replace("\\", "/"), **C.glb_stats(gp), **gs},
             "dressing_prt": dstat, "instances_without_a_placement": unmatched, "cross_check_placements_vs_prt": xc}
    for L, p in outs.items():
        stats[L] = {"glb": os.path.relpath(p, C.ROOT).replace("\\", "/"), **C.glb_stats(p), "per_asset": per[L]}
    if "--no-meshopt" not in sys.argv:
        m = meshopt(gp)
        if m:
            stats["ground"]["meshopt"] = {"glb": os.path.relpath(m, C.ROOT).replace("\\", "/"), **C.glb_stats(m)}
    if "--no-datasmith" not in sys.argv:
        log("datasmith: PRT unreal encoder on the same shapes")
        stats["datasmith"] = datasmith(pal)
    stats["seconds"] = round(time.time() - t0, 1)
    json.dump(stats, open(os.path.join(OUT, "build_stats.json"), "w", encoding="utf-8"), indent=1)
    man = manifest(pal, stats)
    for l in man["layers"]:
        log("%-10s %-32s %6.2f MB  gz %5.2f MB  draws %3d  tris %s" % (l["layer"], l["file"], l["bytes"] / 1e6, l["gzip_bytes"] / 1e6, l["draw_calls"],
                                                                     l.get("triangles") or "%d stored / %d drawn, %d objects (%d film, %d json)" % (
                                                                         l["triangles_stored"], l["triangles_drawn"], l["instances"], l["instances_film"], l["instances_json"])))
    log("totals", man["totals"])
    bad = {k: v for k, v in xc.items() if v.get("matched_within_5cm") != v.get("placements")}
    log("cross-check: %d assets, all matched: %s %s; worst position %.4f m, worst heading %.3f deg; unmatched instances %s" % (
        len(xc), not bad, bad or "", max(v.get("max_position_error_m", 0) for v in xc.values()), max(v.get("max_heading_error_deg", 0) for v in xc.values()), unmatched))
    if stats.get("datasmith"):
        log("datasmith:", json.dumps({k: stats["datasmith"][k] for k in ("ground", "instance")}))
    log("done in %.1f s" % stats["seconds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
