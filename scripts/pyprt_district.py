"""Build one district's massing with PyPRT - no CityEngine, no py4j bridge - and compare it to the CE build.

THE QUESTION this answers is whether the headless path produces the same buildings as the CityEngine path,
per building, before anyone trusts it for a publish. So it builds, then diffs against the GLB the CE
pipeline already produced for the same district and says where they disagree.

Inputs are the same ones ce_batch_v2 uses, reproduced here deliberately rather than approximated:
  footprints      data/ce/<slug>/buildings.geojson
  fclass / fvar   data/ce/<slug>/facade_v2.json
  bHeight         geojson, then scripts/height_overrides.json (reviewed, outranks all), then the
                  heights register as a CANDIDATE only - off the 12.0 m placeholder, or a stub under 20 m
                  at 3x or more. Same rule as ce_batch_v2.run_slug, same order.
  levels, status  geojson properties
  LOD, bandEvery  --lod (default 3), 1

Geometry goes in the CE frame: x = easting, y = up, z = -northing, in EPSG:32640 about a local origin so the
numbers stay small. Absolute position does not matter for a parity test; orientation and winding do, so
each footprint is ordered to face +Y.

Per-shape 'seed' is the feature index. CE assigns its own seed per shape at import, so wherever the rule
makes a random choice the two builds can legitimately differ; the report separates buildings that differ
only slightly (the random case) from ones that differ a lot (a real divergence).

  python scripts/pyprt_district.py arjan
  python scripts/pyprt_district.py arjan --rpk data/ce/_rpk/najma_v4.rpk --lod 3
"""
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
sys.path.insert(0, HERE)


def opt(n, d=None, cast=str):
    return cast(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d


def heights(slug, feats):
    """bHeight per feature index, by exactly the rule ce_batch_v2 uses."""
    hreg = {}
    try:
        hreg = json.load(open(os.path.join(CEDIR, slug, "heights_register.json"), encoding="utf-8")).get("heights", {})
    except Exception:
        pass
    hover = {}
    p = os.path.join(HERE, "height_overrides.json")
    if os.path.exists(p):
        hover = json.load(open(p, encoding="utf-8")).get("districts", {}).get(slug, {})
    out = {}
    for fi, f in enumerate(feats):
        pr = f["properties"]
        try:
            h = float(pr.get("bHeight") or 0)
        except (TypeError, ValueError):
            h = 0.0
        ov = hover.get(str(fi)) or {}
        rh = None if (ov.get("height_m") or ov.get("hold")) else hreg.get(str(fi))
        if ov.get("height_m"):
            h = float(ov["height_m"])
        if rh:
            try:
                rh = float(rh)
            except (TypeError, ValueError):
                rh = 0.0
            if rh > 0 and abs(h - 12.0) < 0.01:
                h = rh
            elif rh > 0 and 0 < h < 20 and rh >= 3 * h:
                h = rh
        out[fi] = round(h, 1)
    return out


def rings(geom):
    t = geom["type"]
    if t == "Polygon":
        return [geom["coordinates"][0]]
    if t == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def footprint(ring, tf, ox, oz):
    """Outer ring -> flat CE-frame vertex list facing +Y, closing vertex dropped."""
    pts = []
    for lon, lat in [(c[0], c[1]) for c in ring]:
        e, n = tf.transform(lon, lat)
        pts.append((e - ox, -(n - oz)))
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    # Signed area in the (x, z) plane. With z = -northing a polygon that is counter-clockwise on the map
    # comes out clockwise here; PyPRT wants counter-clockwise seen from +Y, which in (x, z) is NEGATIVE area.
    a = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    if a > 0:
        pts = pts[::-1]
    return [v for x, z in pts for v in (x, 0.0, z)]


def build(slug, rpk, lod):
    import pyprt
    from pyproj import Transformer
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    facade = json.load(open(os.path.join(CEDIR, slug, "facade_v2.json"), encoding="utf-8"))["buildings"]
    H = heights(slug, feats)
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)

    # local origin: first vertex of the first usable footprint
    ox = oz = None
    for f in feats:
        rs = rings(f["geometry"])
        if rs:
            ox, oz = tf.transform(rs[0][0][0], rs[0][0][1]); break

    shapes, attrs, idx, skipped = [], [], [], []
    for fi, f in enumerate(feats):
        rs = rings(f["geometry"])
        verts = footprint(rs[0], tf, ox, oz) if rs else None      # outer ring of the first part, as CE's SHP import keeps it
        if not verts:
            skipped.append(fi); continue
        pr = f["properties"]
        rec = facade.get(str(fi), {"class": "auto", "variant": fi % 3})
        a = {"shapeName": "b%d" % fi, "seed": fi,
             "fclass": str(rec["class"]), "fvar": float(int(rec.get("variant", fi % 3))),
             "status": str(pr.get("status") or "existing").lower(),
             "LOD": float(lod), "bandEvery": 1.0}
        if H[fi] > 0:
            a["bHeight"] = float(H[fi])
        lv = str(pr.get("levels") or "").strip()
        if lv:
            a["levels"] = lv
        shapes.append(pyprt.InitialShape(verts)); attrs.append(a); idx.append(fi)

    known = {i.split("$")[-1].split("/")[-1] for i in pyprt.get_rpk_attributes_info(rpk).keys()} \
        if hasattr(pyprt.get_rpk_attributes_info(rpk), "keys") else None
    t = time.time()
    mg = pyprt.ModelGenerator(shapes)
    models = mg.generate_model(attrs, rpk, "com.esri.pyprt.PyEncoder",
                               {"emitReport": True, "emitGeometry": True})
    took = time.time() - t
    per = {}
    for m in models:
        fi = idx[m.get_initial_shape_index()]
        faces = m.get_faces()
        tris = sum(max(0, int(c) - 2) for c in faces)          # a face of n vertices = n - 2 triangles
        ys = m.get_vertices()[1::3]
        per[fi] = {"tris": tris, "h": round(max(ys) - min(ys), 1) if ys else 0.0}
    return {"slug": slug, "shapes": len(shapes), "models": len(models), "skipped": skipped,
            "generate_s": round(took, 1), "per": per, "known_attrs": known}


def ce_reference(slug):
    """Per-building triangles and height from the GLB the CityEngine pipeline built."""
    from glb_merge_per_building import read_glb
    import struct
    p = os.path.join(CEDIR, "_glb", "sky_%s_v4_0.glb" % slug)
    js, bn = read_glb(p)
    out = {}
    for nd in js["nodes"]:
        if "mesh" not in nd:
            continue
        name = nd.get("name", "")
        bid = name.split("_")[0]
        if not bid.startswith("b") or not bid[1:].isdigit():
            continue
        fi = int(bid[1:])
        tris, ymin, ymax = 0, 1e18, -1e18
        for pr in js["meshes"][nd["mesh"]]["primitives"]:
            if "indices" in pr:
                tris += js["accessors"][pr["indices"]]["count"] // 3
            else:
                tris += js["accessors"][pr["attributes"]["POSITION"]]["count"] // 3
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            if "min" in acc and "max" in acc:
                ymin = min(ymin, acc["min"][1]); ymax = max(ymax, acc["max"][1])
        out[fi] = {"tris": tris, "h": round(ymax - ymin, 1) if ymax > ymin else 0.0}
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    slug = args[0]
    # ABSOLUTE, always: PRT resolves a relative rule-package path against the drive root, so
    # data/ce/_rpk/najma_v4.rpk becomes /data/ce/_rpk/najma_v4.rpk and fails as "invalid header".
    rpk = os.path.abspath(opt("--rpk", os.path.join(CEDIR, "_rpk", "najma_v4.rpk")))
    lod = opt("--lod", 3, int)
    if not os.path.exists(rpk):
        sys.exit("no rule package at %s - run scripts/export_najma_rpk.py first" % rpk)

    print("PyPRT build of %s at LOD %d from %s" % (slug, lod, os.path.relpath(rpk, ROOT)), flush=True)
    got = build(slug, rpk, lod)
    print("  %d shapes in, %d models out, %d skipped, generate %.1f s"
          % (got["shapes"], got["models"], len(got["skipped"]), got["generate_s"]), flush=True)

    ref = ce_reference(slug)
    a, b = got["per"], ref
    both = sorted(set(a) & set(b))
    only_py, only_ce = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    tri_py = sum(a[i]["tris"] for i in both); tri_ce = sum(b[i]["tris"] for i in both)
    exact = [i for i in both if a[i]["tris"] == b[i]["tris"]]
    near = [i for i in both if a[i]["tris"] != b[i]["tris"] and abs(a[i]["tris"] - b[i]["tris"]) <= 0.10 * max(1, b[i]["tris"])]
    far = [i for i in both if abs(a[i]["tris"] - b[i]["tris"]) > 0.10 * max(1, b[i]["tris"])]
    hdiff = [i for i in both if abs(a[i]["h"] - b[i]["h"]) > 0.5]

    res = {"slug": slug, "lod": lod, "pyprt_generate_s": got["generate_s"],
           "buildings": {"pyprt": len(a), "cityengine": len(b), "both": len(both),
                         "only_pyprt": only_py[:20], "only_cityengine": only_ce[:20]},
           "triangles": {"pyprt": tri_py, "cityengine": tri_ce,
                         "ratio": round(tri_py / tri_ce, 4) if tri_ce else None},
           "per_building": {"exact": len(exact), "within_10pct": len(near), "beyond_10pct": len(far),
                            "height_diff_over_0.5m": len(hdiff)},
           "worst": [{"b": i, "pyprt": a[i], "cityengine": b[i]}
                     for i in sorted(far, key=lambda i: -abs(a[i]["tris"] - b[i]["tris"]))[:10]],
           "height_worst": [{"b": i, "pyprt_h": a[i]["h"], "ce_h": b[i]["h"]}
                            for i in sorted(hdiff, key=lambda i: -abs(a[i]["h"] - b[i]["h"]))[:10]]}
    outp = os.path.join(CEDIR, slug, "pyprt_parity.json")
    json.dump(res, open(outp, "w", encoding="utf-8"), indent=1)

    print()
    print("  buildings   PyPRT %d   CityEngine %d   in both %d" % (len(a), len(b), len(both)))
    print("  triangles   PyPRT %d   CityEngine %d   ratio %s" % (tri_py, tri_ce, res["triangles"]["ratio"]))
    print("  per building: %d exact, %d within 10%%, %d beyond 10%%; %d differ in height by > 0.5 m"
          % (len(exact), len(near), len(far), len(hdiff)))
    for w in res["worst"][:5]:
        print("    b%-5d PyPRT %7d tris %6.1f m   CE %7d tris %6.1f m"
              % (w["b"], w["pyprt"]["tris"], w["pyprt"]["h"], w["cityengine"]["tris"], w["cityengine"]["h"]))
    print("  -> %s" % os.path.relpath(outp, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
