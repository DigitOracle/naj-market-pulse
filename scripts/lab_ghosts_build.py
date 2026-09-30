"""LAB (ghosts, research only): generate the ghost massings headlessly with PyPRT and export an opt-in GLB layer.

Input   data/lab/ghosts/<slug>/ghost_markers.geojson   (scripts/lab_ghosts_candidates.py - points + indicative sizes)
Rule    data/lab/ghosts/najma_ghost.rpk                 (scripts/lab_ghosts_rpk.py, from rules/lab/ghosts/najma_ghost.cga)
Output  data/lab/ghosts/<slug>/ghosts_<slug>.glb        one mesh per ghost, named b<k>_ghost_s<status> so the viewer's
                                                        existing STATUS_RE path would tint it even if merged by mistake
        data/lab/ghosts/<slug>/ghosts_<slug>.json       the layer's sidecar: origin (same contract as origin_v5.json),
                                                        b<k> -> project, size basis, and the INDICATIVE label per ghost
        data/lab/ghosts/<slug>/verify.json              what PRT actually built vs what was asked (height, plate area)

Each marker becomes a 2 x 2 m quad at the location point - the CE point-marker idiom, since a PRT initial shape needs a
face - and the rule scales it to the ghost's footprint (Tutorial 16 marker technique). Geometry is in the district's
LOCAL CE frame: x = easting, y = up, z = -northing (EPSG:32640) minus the SAME origin the district's v5 tile uses
(data/ce/<slug>/origin_v5.json), so ghost vertex + origin_ce_xyz lands exactly where the tile's vertex + origin does.

  python scripts/lab_ghosts_build.py              (businessbay)
"""
import glob
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
RPK = os.path.abspath(os.path.join(ROOT, "data", "lab", "ghosts", "najma_ghost.rpk"))   # absolute: PRT resolves relative paths against the drive root
MARKER = 2.0


def main():
    import pyprt
    from pyproj import Transformer
    global RPK
    if "--rpk" in sys.argv:            # mechanics dry-run against another package (sizes are then ignored by that rule)
        RPK = os.path.abspath(sys.argv[sys.argv.index("--rpk") + 1])
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] != "--rpk"]
    slug = args[0] if args else "businessbay"
    d = os.path.join(ROOT, "data", "lab", "ghosts", slug)
    mk = json.load(open(os.path.join(d, "ghost_markers.geojson"), encoding="utf-8"))
    feats = mk["features"]
    if not feats:
        sys.exit("no ghosts to build for %s" % slug)
    if not os.path.exists(RPK):
        sys.exit("no rule package at %s - run scripts/lab_ghosts_rpk.py first" % RPK)
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    op = os.path.join(ROOT, "data", "ce", slug, "origin_v5.json")
    if os.path.exists(op):
        o = json.load(open(op, encoding="utf-8")); oe, on = o["origin_utm_en"]; origin_from = os.path.relpath(op, ROOT)
    else:
        es, ns = zip(*[tf.transform(*f["geometry"]["coordinates"]) for f in feats])
        oe, on = float(round((min(es) + max(es)) / 2)), float(round((min(ns) + max(ns)) / 2)); origin_from = "ghost bbox centre"

    shapes, attrs, index = [], [], []
    for k, f in enumerate(feats):
        pr = f["properties"]
        e, n = tf.transform(*f["geometry"]["coordinates"])
        x, z = e - oe, -(n - on)
        h = MARKER / 2
        # counter-clockwise seen from +Y = negative signed area in (x, z) - same convention as pyprt_district.footprint
        pts = [(x - h, z - h), (x - h, z + h), (x + h, z + h), (x + h, z - h)]
        a = sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
        if a > 0:
            pts = pts[::-1]
        shapes.append(pyprt.InitialShape([v for px, pz in pts for v in (px, 0.0, pz)]))
        name = "b%d_ghost_s%s" % (k, pr["status"])
        attrs.append({"shapeName": name, "seed": k, "ghostW": float(pr["ghostW"]), "ghostD": float(pr["ghostD"]),
                      "ghostH": float(pr["ghostH"]), "status": str(pr["status"]), "pctComplete": float(pr["pctComplete"] or 0),
                      "floorH": 3.44, "bandEvery": 10.0})
        index.append({"b": "b%d" % k, "mesh_name": name, "ghost_id": pr["ghost_id"], "project_number": pr["project_number"],
                      "name": pr["name"], "developer": pr["developer"], "register_status": pr["register_status"],
                      "pctComplete": pr["pctComplete"], "units": pr["units"], "end_date": pr["end_date"],
                      "height_m": pr["ghostH"], "side_m": pr["ghostW"], "floors": pr["floors"],
                      "size_basis": pr["size_basis"], "size_detail": pr["size_detail"],
                      "position_source": pr["position_source"], "position_place": pr["position_place"],
                      "position_confidence": pr.get("position_confidence"), "moved_m": pr["moved_m"],
                      "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
                      "indicative": True, "is_footprint": False})

    # 1. verify: what does the rule actually build for these attributes?
    t = time.time()
    models = pyprt.ModelGenerator(shapes).generate_model(attrs, RPK, "com.esri.pyprt.PyEncoder",
                                                         {"emitReport": True, "emitGeometry": True})
    ver = []
    for m in models:
        k = m.get_initial_shape_index(); rep = m.get_report(); ys = m.get_vertices()[1::3]
        xs = m.get_vertices()[0::3]; zs = m.get_vertices()[2::3]
        built_h = round(max(ys) - min(ys), 2) if ys else 0.0
        want = attrs[k]
        ver.append({"b": "b%d" % k, "name": index[k]["name"], "asked_h": want["ghostH"], "built_h": built_h,
                    "asked_plate_m2": round(want["ghostW"] * want["ghostD"], 1),
                    "report_plate_m2": round(rep.get("ghost.footprint_m2_sum", rep.get("ghost.footprint_m2", 0)), 1),
                    "bbox_w": round(max(xs) - min(xs), 2) if xs else 0, "bbox_d": round(max(zs) - min(zs), 2) if zs else 0,
                    "faces": len(m.get_faces()), "ok": abs(built_h - want["ghostH"]) <= 0.5})
    gen_s = round(time.time() - t, 2)
    if len(models) != len(shapes):
        print("WARNING: %d shapes in, %d models out" % (len(shapes), len(models)))

    # 2. export: glTF binary, then one mesh per ghost (the same merge the district tiles use).
    # The marker technique's primitiveCube() replaces the shape's geometry with the builtin:cube asset, and the glTF
    # encoder then names every leaf "builtin:cube_N" - the shape name is lost. So each ghost is generated on its own and
    # its nodes/meshes are renamed b<k>_ghost_s<status>_<n> before the per-building merge groups them.
    from glb_merge_per_building import merge, read_glb, write_glb
    from glb_merge_parts import concat
    raw = "ghosts_%s_raw" % slug
    for f in glob.glob(os.path.join(d, raw + "*")):
        os.remove(f)
    merged, tris = [], 0
    for k in range(len(shapes)):
        base = "%s%d" % (raw, k)
        pyprt.ModelGenerator([shapes[k]]).generate_model(
            [attrs[k]], RPK, "com.esri.prt.codecs.GLTFEncoder",
            {"outputPath": d, "baseName": base, "meshGranularity": "AS_GENERATED", "outputFormat": "GLB"})
        parts = sorted(glob.glob(os.path.join(d, base + "_*.glb")) or glob.glob(os.path.join(d, base + "*.glb")))
        if not parts:
            sys.exit("the glTF encoder wrote nothing for ghost %d" % k)
        for p in parts:
            js, bn = read_glb(p)
            for i, nd in enumerate(js.get("nodes", [])):
                nd["name"] = "%s_%d" % (attrs[k]["shapeName"], i)
            for i, me in enumerate(js.get("meshes", [])):
                me["name"] = "%s_%d" % (attrs[k]["shapeName"], i)
            write_glb(p, js, bn)
            mp = p.replace(".glb", ".m.glb"); tris += merge(p, mp)["triangles"]; merged.append(mp)
            os.remove(p)
    out = os.path.join(d, "ghosts_%s.glb" % slug)
    r = concat(merged, out) if len(merged) > 1 else merge(merged[0], out)
    r["triangles"] = tris
    for mp in merged:
        os.remove(mp)

    side = {"layer": "ghosts", "slug": slug, "research_only": True, "opt_in": True,
            "label": "Indicative placeholders for registered pipeline projects with no footprint yet. Positions come from "
                     "place searches, sizes from the DM register, developer storeys or a units formula. Not surveyed footprints.",
            "crs": "EPSG:32640", "origin_ce_xyz": [oe, 0.0, -on], "origin_utm_en": [oe, on], "origin_from": origin_from,
            "contract": "CE-frame metres (x = easting, y = up, z = -northing) = vertex + origin_ce_xyz",
            "apply": "set as the object's position in float64; never add into the vertex buffer",
            "rule": "najma_ghost.rpk (rules/lab/ghosts/najma_ghost.cga)", "glb": os.path.basename(out),
            "glb_bytes": os.path.getsize(out), "buildings": r.get("buildings"), "triangles": r.get("triangles"),
            "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "builder": "pyprt", "ghosts": index}
    json.dump(side, open(os.path.join(d, "ghosts_%s.json" % slug), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"slug": slug, "generate_s": gen_s, "shapes": len(shapes), "models": len(models),
               "all_heights_ok": all(v["ok"] for v in ver), "per_ghost": ver},
              open(os.path.join(d, "verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for v in ver:
        print("  %-4s %-28s asked %6.1f m  built %6.1f m  plate %7.1f m2 (report %7.1f)  bbox %5.1f x %5.1f  %s" % (
            v["b"], (v["name"] or "")[:28], v["asked_h"], v["built_h"], v["asked_plate_m2"], v["report_plate_m2"],
            v["bbox_w"], v["bbox_d"], "ok" if v["ok"] else "MISMATCH"))
    print("-> %s  %d ghosts, %s triangles, %.1f KB" % (os.path.relpath(out, ROOT), r.get("buildings", 0), r.get("triangles"),
                                                       os.path.getsize(out) / 1024))
    render_check(slug, d, out, (oe, on))
    return 0


def render_check(slug, d, glb, origin):
    """Review render (evidence only): the GLB's own triangles, gold/teal translucent, among the district's modelled
    footprints extruded to bHeight in grey, within 700 m of the ghosts. Reads the GLB back, so it shows what was built."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import struct
        from pyproj import Transformer
        from glb_merge_per_building import read_glb, accessor_raw
    except Exception as e:
        print("  render skipped: %s" % e); return
    oe, on = origin
    js, bn = read_glb(glb)
    fig = plt.figure(figsize=(12, 8), dpi=120); ax = fig.add_subplot(111, projection="3d")
    cx, cy = [], []
    for nd in js["nodes"]:
        me = js["meshes"][nd["mesh"]]; colr = "#3E8A7E" if "_sconstruction" in nd["name"] else "#C5A56A"
        for pr in me["primitives"]:
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            raw = accessor_raw(js, bn, pr["attributes"]["POSITION"])[0]
            v = struct.unpack("<%df" % (acc["count"] * 3), raw[:acc["count"] * 12])
            pts = [(v[i] + oe, -v[i + 2] + on, v[i + 1]) for i in range(0, len(v), 3)]
            if "indices" in pr:
                ia = js["accessors"][pr["indices"]]; ib = accessor_raw(js, bn, pr["indices"])[0]
                fmt = {5121: "B", 5123: "H", 5125: "I"}[ia["componentType"]]
                ix = struct.unpack("<%d%s" % (ia["count"], fmt), ib)
                tris = [[pts[ix[i]], pts[ix[i + 1]], pts[ix[i + 2]]] for i in range(0, len(ix) - 2, 3)]
            else:
                tris = [pts[i:i + 3] for i in range(0, len(pts) - 2, 3)]
            ax.add_collection3d(Poly3DCollection(tris, facecolor=colr, alpha=0.28, edgecolor=colr, linewidths=0.2))
            cx += [p[0] for p in pts]; cy += [p[1] for p in pts]
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    feats = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
    x0, x1, y0, y1 = min(cx) - 700, max(cx) + 700, min(cy) - 700, max(cy) + 700
    for f in feats:
        if f["geometry"]["type"] != "Polygon":
            continue
        ring = [tf.transform(c[0], c[1]) for c in f["geometry"]["coordinates"][0]]
        if not any(x0 < x < x1 and y0 < y < y1 for x, y in ring):
            continue
        h = float(f["properties"].get("bHeight") or 12)
        walls = [[(a[0], a[1], 0), (b[0], b[1], 0), (b[0], b[1], h), (a[0], a[1], h)] for a, b in zip(ring, ring[1:])]
        ax.add_collection3d(Poly3DCollection(walls + [[(x, y, h) for x, y in ring]], facecolor="#8b949c", alpha=0.85,
                                             edgecolor="#5d656c", linewidths=0.1))
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_zlim(0, 450)
    ax.set_box_aspect((x1 - x0, y1 - y0, 450), zoom=1.9); ax.view_init(elev=22, azim=-62); ax.set_axis_off()
    ax.set_title("%s - pipeline ghosts (gold = pipeline, teal = registered as started), INDICATIVE envelopes among modelled buildings.\n"
                 "Research only. Positions from place searches, sizes from DM register / units; not surveyed footprints." % slug, fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(d, "ghosts_3d.png")); plt.close(fig)
    print("  review render -> %s" % os.path.relpath(os.path.join(d, "ghosts_3d.png"), ROOT))


if __name__ == "__main__":
    sys.exit(main())
