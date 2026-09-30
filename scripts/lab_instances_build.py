"""LAB #4 (instancing) step 2: run the instancing rule headless (PyPRT) on one district and write, all under data/lab/instances/:

  <slug>_instance_map.json     asset table + one row per instance [asset, x, y, z, yaw_ce_deg, scale] in the district's LOCAL CE frame
  <slug>_instanceMap.txt       the same rows in Esri Tutorial 12's tab-separated layout (nr asset xpos ... zscale)
  <slug>_instances_ue.csv      Unreal: one row per instance, UE world cm (the repo's E0/N0 frame), yaw, scale, target height, UE role
  <slug>_instances_ext.glb     web: EXT_mesh_gpu_instancing (PRT INSTANCED -> gltf-transform dedup -> instance)
  <slug>_instances_baked.glb   web control: the SAME instances baked as plain geometry (PRT AS_GENERATED)
  <slug>_instancing_stats.json counts, sizes (raw and gzip -9), draw batches, stored vs drawn triangles, cross-checks

WHICH ENCODER GIVES PER-INSTANCE TRANSFORMS (measured on this rule, PyPRT 1.12):
  com.esri.pyprt.PyEncoder     reports only, through a SUMMARISING accumulator: a key reported N times per shape comes back as
                               key_n/_sum/_avg/_min/_max. Tutorial 12's repeated "xpos" etc. therefore collapse to statistics.
                               The rule's "indexed" style (one key set per instance, i<k>.x ...) survives: every _n is 1.
  com.esri.prt.codecs.GLTFEncoder meshGranularity INSTANCED: one node per instance with a full matrix, geometry stored once
                               per asset (mesh objects repeat, accessors are shared) -> gltf-transform dedup + instance turns it
                               into EXT_mesh_gpu_instancing. AS_GENERATED bakes every instance into world-space geometry.
  com.esri.prt.unreal.encoder  (Datasmith) default instancing: each asset written once as a StaticMesh, instances as
                               ActorHierarchicalInstancedStaticMesh with per-instance Transform - but one HISM actor per initial
                               shape per asset, so thousands of small HISMs for a district. See the report.
The instance map is built from the indexed reports and CROSS-CHECKED against the GLTF INSTANCED node matrices.

Research only: nothing here is pushed, uploaded or deployed. One PyPRT process at a time.

  python scripts/lab_instances_build.py alhebiahfifth [--rep LowPoly|Fan] [--limit N]
"""
import csv
import glob
import gzip
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LAB = os.path.join(ROOT, "data", "lab", "instances")
RPK = os.path.join(LAB, "lab_instances.rpk")
E0, N0 = 328289.0, 2784598.0          # the repo's Unreal world origin (ue_furniture.py, build_foliage_points.py): UE x = (E-E0)*100, y = (N0-N)*100

# asset file stem -> (category, Unreal role as in ue_bb_v0_build.KITS, UE fallback mesh or None, size axis)
NAJMA = "/Game/DA/Najma/Models/"
ASSETS = {
    "PhoenixDactylifera":   ("palm", "date_palm", NAJMA + "esri_plant_phoenixdactylifera/PhoenixDactylifera/StaticMeshes/PhoenixDactylifera", "h"),
    "WashingtoniaFilifera": ("palm", "washingtonia", NAJMA + "esri_plant_washingtoniafilifera/WashingtoniaFilifera/StaticMeshes/WashingtoniaFilifera", "h"),
    "CocosNucifera":        ("palm", "coconut_palm", None, "h"),
    "AcaciaTortilis":       ("tree", "shade_tree", NAJMA + "esri_plant_acaciatortilis/AcaciaTortilis/StaticMeshes/AcaciaTortilis", "h"),
    "Light_On_Post_-_Light_off": ("furniture", "lamp", None, "h"),
    "Park_Bench_1":         ("furniture", "bench", None, "len"),
    "Trash_Bin_1":          ("furniture", "bin", None, "h"),
}



def opt(n, d=None, cast=str):
    return cast(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d


def read_glb(p):
    b = open(p, "rb").read()
    L = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + L]), b


def gz(p):
    return len(gzip.compress(open(p, "rb").read(), 9))


def gltf_transform(*args):
    """gltf-transform CLI through npx (cached after the first call). Returns stdout+stderr text."""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    cmd = [npx, "--yes", "@gltf-transform/cli@4.5.1"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0:
        raise RuntimeError("gltf-transform %s failed:\n%s" % (args[0], r.stdout + r.stderr))
    return (r.stdout + r.stderr).strip()


def glb_stats(p):
    """batches (primitives the renderer draws), triangles stored in the file, triangles drawn (x instance count)."""
    js, _ = read_glb(p)
    acc = js.get("accessors", [])
    tri_prim = []
    for m in js.get("meshes", []):
        t = []
        for pr in m["primitives"]:
            t.append((acc[pr["indices"]]["count"] if "indices" in pr else acc[pr["attributes"]["POSITION"]]["count"]) // 3)
        tri_prim.append(t)
    stored = sum(sum(t) for t in tri_prim)
    drawn, batches, inst = 0, 0, 0
    for n in js.get("nodes", []):
        if "mesh" not in n:
            continue
        k = 1
        ext = (n.get("extensions") or {}).get("EXT_mesh_gpu_instancing")
        if ext:
            k = acc[ext["attributes"]["TRANSLATION"]]["count"]
        inst += k
        drawn += k * sum(tri_prim[n["mesh"]])
        batches += len(tri_prim[n["mesh"]])
    return {"bytes": os.path.getsize(p), "gzip9_bytes": gz(p), "meshes": len(js.get("meshes", [])), "mesh_nodes_or_instances": inst,
            "draw_batches": batches, "triangles_stored": stored, "triangles_drawn": drawn,
            "images": len(js.get("images", [])), "extensionsUsed": js.get("extensionsUsed", [])}


def load(slug, limit=None):
    import pyprt
    d = json.load(open(os.path.join(LAB, "%s_shapes.json" % slug), encoding="utf-8"))
    sh = d["shapes"][:limit] if limit else d["shapes"]
    return d, sh, [pyprt.InitialShape(s["verts"]) for s in sh]


def attrs(sh, rep, style):
    return [{"kind": s["kind"], "roadClass": s["roadClass"], "seed": int(s["id"]), "Representation": rep, "ReportStyle": style} for s in sh]


def instances_from_reports(models, sh):
    """indexed reports -> rows. Values come back summarised (key_sum, key_n); every _n must be 1 or two instances collided."""
    rows, collisions = [], 0
    for m in models:
        r = m.get_report(); si = m.get_initial_shape_index()
        ids = sorted({k.split(".")[0] for k in r if k.startswith("i") and "." in k}, key=lambda s: float(s[1:]))
        for iid in ids:
            v = lambda f: r.get("%s.%s_sum" % (iid, f), r.get("%s.%s" % (iid, f)))
            if (r.get("%s.x_n" % iid) or 1) != 1:
                collisions += 1
            a = os.path.splitext(os.path.basename(v("a")))[0]
            hx, hz = float(v("hx")), float(v("hz"))
            yaw = math.degrees(math.atan2(-hz, hx))            # rotation about +Y (CE frame) that takes +X to the scope's x axis
            rows.append({"shape": int(sh[si]["id"]), "idx": int(float(iid[1:])), "asset": a, "cat": v("c"),
                         "x": float(v("x")), "y": float(v("y")), "z": float(v("z")), "yaw": yaw, "ry": float(v("ry")),
                         "k": float(v("k"))})
    return rows, collisions


def prt_instance_nodes(p):
    """(translation, scale, yaw_deg) of every instance node in a PRT INSTANCED glTF (nodes carrying a matrix)."""
    js, _ = read_glb(p)
    out = []
    for n in js["nodes"]:
        M = n.get("matrix")
        if not M:
            continue
        sx = math.hypot(M[0], M[2]); yaw = math.degrees(math.atan2(-M[2], M[0]))
        out.append((M[12], M[13], M[14], sx, yaw))
    return out


def gltf_run(pyprt, shapes, at, gran, base):
    raw = os.path.join(LAB, "_raw"); os.makedirs(raw, exist_ok=True)
    for f in glob.glob(os.path.join(raw, base + "*")):
        os.remove(f)
    t = time.time()
    pyprt.ModelGenerator(shapes).generate_model(at, RPK, "com.esri.prt.codecs.GLTFEncoder",
                                                {"outputPath": raw, "baseName": base, "meshGranularity": gran, "outputFormat": "GLB"})
    return sorted(glob.glob(os.path.join(raw, base + "_*.glb")), key=lambda p: (len(p), p)), round(time.time() - t, 1)


def main():
    import pyprt
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for f in ("--rep", "--limit"):
        if f in sys.argv:
            args.remove(sys.argv[sys.argv.index(f) + 1])
    slug = (args or ["alhebiahfifth"])[0]
    rep = opt("--rep", "LowPoly"); limit = opt("--limit", None, int)
    tag = "" if rep == "LowPoly" else "_" + rep.lower()
    d, sh, shapes = load(slug, limit)
    origin = d["origin_ce_xyz"]
    print("%s: %d shapes (%s), rule %s, representation %s" % (slug, len(sh), d["counts"], os.path.relpath(RPK, ROOT), rep), flush=True)

    # 1. reports -> instance map ------------------------------------------------------------------------------------
    t = time.time()
    models = pyprt.ModelGenerator(shapes).generate_model(attrs(sh, rep, "indexed"), RPK, "com.esri.pyprt.PyEncoder",
                                                         {"emitReport": True, "emitGeometry": False})
    rows, collisions = instances_from_reports(models, sh)
    t_rep = round(time.time() - t, 1)
    # the Tutorial 12 style on the same shapes, to record what PyPRT does to repeated keys
    m12 = pyprt.ModelGenerator(shapes[:1]).generate_model(attrs(sh[:1], rep, "tutorial12"), RPK, "com.esri.pyprt.PyEncoder",
                                                          {"emitReport": True, "emitGeometry": False})
    t12_keys = sorted(k for k in m12[0].get_report() if k.startswith("xpos"))
    print("  reports: %d instances from %d models in %.1f s, %d key collisions" % (len(rows), len(models), t_rep, collisions), flush=True)

    names = sorted({r["asset"] for r in rows})
    aidx = {a: i for i, a in enumerate(names)}
    from collections import Counter
    cnt = Counter(r["asset"] for r in rows)
    imap = {"slug": slug, "representation": rep, "rule": "najma/rules/lab/instances/lab_instances.cga", "rpk": os.path.relpath(RPK, ROOT),
            "frame": "local CE frame, metres: x = easting - ox, y = up, z = -(northing - oy); CE-frame = row + origin_ce_xyz",
            "origin_ce_xyz": origin,
            "row": ["asset", "x", "y", "z", "yaw_deg (about +Y, CE right-handed; Unreal yaw = -yaw)", "scale (uniform, vs the library asset)"],
            "assets": [{"id": a, "category": ASSETS.get(a, ("?",))[0], "ue_role": ASSETS.get(a, ("?", "?"))[1], "count": cnt[a]} for a in names],
            "instances": [[aidx[r["asset"]], round(r["x"], 3), round(r["y"], 3), round(r["z"], 3), round(r["yaw"], 2), round(r["k"], 4)] for r in rows]}
    jp = os.path.join(LAB, "%s_instance_map%s.json" % (slug, tag))
    json.dump(imap, open(jp, "w", encoding="utf-8"), separators=(",", ":"))

    # Tutorial 12 layout (nr asset xpos ypos zpos xrot yrot zrot xscale yscale zscale), pivot position, world rotation
    with open(os.path.join(LAB, "%s_instanceMap%s.txt" % (slug, tag)), "w", encoding="utf-8") as fh:
        fh.write("nr\tasset\txpos\typos\tzpos\txrot\tyrot\tzrot\txscale\tyscale\tzscale\n")
        for i, r in enumerate(rows):
            fh.write("%d\t%s.glb\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\n" % (i, r["asset"], r["x"], r["y"], r["z"], 0.0, r["yaw"], 0.0, r["k"], r["k"], r["k"]))

    # 2. Unreal CSV: UE world cm in the repo's frame (E0/N0), yaw = -CE yaw, height from the native asset height x scale -------
    ox, _, oz = origin
    native = {}
    lib = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "CityEngine", "Default Workspace", "ESRI.lib", "assets", "Webstyles")
    for a in names:
        cands = glob.glob(os.path.join(lib, "Vegetation", rep, a + ".glb")) + glob.glob(os.path.join(lib, "StreetScene", a + ".glb"))
        if cands:
            js, _ = read_glb(cands[0]); mn = [1e9] * 3; mx = [-1e9] * 3
            for mm in js["meshes"][:1] if "StreetScene" in cands[0] else js["meshes"]:     # street assets carry MSFT_lod copies: LOD0 mesh only
                for pr in mm["primitives"]:
                    ac = js["accessors"][pr["attributes"]["POSITION"]]
                    mn = [min(mn[i], ac["min"][i]) for i in range(3)]; mx = [max(mx[i], ac["max"][i]) for i in range(3)]
            native[a] = {"h": mx[1] - mn[1], "len": mx[0] - mn[0]}
    cp = os.path.join(LAB, "%s_instances_ue.csv" % slug)
    with open(cp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "asset", "category", "ue_role", "ue_fallback_mesh", "x_cm", "y_cm", "z_cm", "yaw_deg", "scale", "target_m", "size_axis", "shape"])
        for i, r in enumerate(rows):
            cat, role, mesh, axis = ASSETS.get(r["asset"], ("?", "?", None, "h"))
            E = r["x"] + ox; N = -(r["z"] + oz)
            tgt = r["k"] * native.get(r["asset"], {}).get(axis, 0.0)
            w.writerow([i, r["asset"], cat, role, mesh or "", round((E - E0) * 100.0, 1), round((N0 - N) * 100.0, 1), round(r["y"] * 100.0, 1),
                        round(-r["yaw"], 2), round(r["k"], 4), round(tgt, 2), axis, r["shape"]])
    print("  wrote %s, %s, %s" % (os.path.basename(jp), "%s_instanceMap%s.txt" % (slug, tag), os.path.basename(cp)), flush=True)

    # 3. web: PRT INSTANCED -> dedup -> EXT_mesh_gpu_instancing, and the baked control ---------------------------------------
    at = attrs(sh, rep, "none")
    inst_parts, t_inst = gltf_run(pyprt, shapes, at, "INSTANCED", "%s_inst%s" % (slug, tag))
    baked_parts, t_baked = gltf_run(pyprt, shapes, at, "AS_GENERATED", "%s_baked%s" % (slug, tag))
    print("  PRT glTF: INSTANCED %d part(s) %.1f s, AS_GENERATED %d part(s) %.1f s" % (len(inst_parts), t_inst, len(baked_parts), t_baked), flush=True)

    # cross-check: PRT's own instance node matrices vs the reported pivots
    nodes = [n for p in inst_parts for n in prt_instance_nodes(p)]
    import numpy as np
    P = np.array([[n[0], n[2]] for n in nodes]); worst, yawd, scaled = 0.0, 0.0, 0.0
    if len(P):
        for r in rows:
            j = int(np.argmin((P[:, 0] - r["x"]) ** 2 + (P[:, 1] - r["z"]) ** 2))
            worst = max(worst, math.hypot(P[j, 0] - r["x"], P[j, 1] - r["z"]))
            dy = (nodes[j][4] - r["yaw"] + 180.0) % 360.0 - 180.0
            yawd = max(yawd, abs(dy)); scaled = max(scaled, abs(nodes[j][3] - r["k"]))

    ext = os.path.join(LAB, "%s_instances_ext%s.glb" % (slug, tag))
    baked = os.path.join(LAB, "%s_instances_baked%s.glb" % (slug, tag))
    logs = []
    if len(inst_parts) == 1:
        dd = inst_parts[0].replace(".glb", "_dedup.glb")
        logs.append(gltf_transform("dedup", inst_parts[0], dd))
        logs.append(gltf_transform("instance", dd, ext))
        os.remove(dd)
    else:
        sys.exit("INSTANCED came out in %d parts - merge them first (gltf-transform merge) before instancing" % len(inst_parts))
    if len(baked_parts) == 1:
        shutil.copyfile(baked_parts[0], baked)
    else:
        logs.append(gltf_transform("merge", *baked_parts, baked, "--merge-scenes"))
    # the same compression the viewer already decodes (MeshoptDecoder is registered on its GLTFLoader)
    ext_m = ext.replace(".glb", "_meshopt.glb"); baked_m = baked.replace(".glb", "_meshopt.glb")
    logs.append(gltf_transform("meshopt", ext, ext_m))
    logs.append(gltf_transform("meshopt", baked, baked_m))

    S = {k: glb_stats(p) for k, p in (("ext_mesh_gpu_instancing", ext), ("baked_plain", baked), ("ext_meshopt", ext_m), ("baked_meshopt", baked_m),
                                        ("prt_instanced_raw", inst_parts[0]))}
    stats = {"slug": slug, "representation": rep, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "shapes": len(sh), "shape_counts": d["counts"],
             "instances": len(rows), "by_asset": dict(cnt), "by_category": dict(Counter(r["cat"] for r in rows)),
             "report_key_collisions": collisions, "pyprt_reports_s": t_rep, "gltf_instanced_s": t_inst, "gltf_baked_s": t_baked,
             "tutorial12_style_under_pyprt": {"keys_for_xpos": t12_keys,
                                              "note": "PyEncoder summarises repeated keys: per-instance values are lost; use ReportStyle indexed"},
             "cross_check_vs_prt_instanced_nodes": {"prt_instance_nodes": len(nodes), "report_rows": len(rows),
                                                    "max_position_error_m": round(worst, 4), "max_yaw_error_deg": round(yawd, 3),
                                                    "max_scale_error": round(scaled, 5)},
             "glb": S,
             "ratios": {"baked_over_ext_bytes": round(S["baked_plain"]["bytes"] / S["ext_mesh_gpu_instancing"]["bytes"], 2),
                        "baked_over_ext_gzip": round(S["baked_plain"]["gzip9_bytes"] / S["ext_mesh_gpu_instancing"]["gzip9_bytes"], 2),
                        "baked_over_ext_meshopt_gzip": round(S["baked_meshopt"]["gzip9_bytes"] / S["ext_meshopt"]["gzip9_bytes"], 2),
                        "draw_batches_baked_vs_ext": [S["baked_plain"]["draw_batches"], S["ext_mesh_gpu_instancing"]["draw_batches"]]},
             "gltf_transform_log": [l.splitlines()[-1] if l else "" for l in logs]}
    sp = os.path.join(LAB, "%s_instancing_stats%s.json" % (slug, tag))
    json.dump(stats, open(sp, "w", encoding="utf-8"), indent=1)
    for k, v in S.items():
        print("  %-24s %9.2f MB  gzip %8.2f MB  batches %6d  tris stored %9d drawn %9d" % (k, v["bytes"] / 1e6, v["gzip9_bytes"] / 1e6, v["draw_batches"], v["triangles_stored"], v["triangles_drawn"]))
    print("  cross-check:", stats["cross_check_vs_prt_instanced_nodes"])
    print("  ->", os.path.relpath(sp, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
