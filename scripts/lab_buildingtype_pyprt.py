"""LAB (technique #5) - PyPRT proof that the building TYPE can reach the LOD 3 build with NO rule change.

najma_v4.cga already has `attr lowStyle = "villa"` (villa grammar: G+1..G+2, porch + garage shutter on the street face,
capped at 3 storeys) vs "flat" (punched rows at the real height). ce_lod3_datasmith.py never sets it, so every shape
under 20 m gets the villa grammar. The compiled data/ce/_rpk/najma_v4.rpk exposes lowStyle, so it can be pushed per
shape exactly like fclass / streetAz are today.

This builds one district twice, in memory, through the same prepare() the PyPRT lane uses (scripts/pyprt_district.py):
  today      attrs as ce_batch_v2 pushes them
  proposed   + lowStyle per shape from data/lab/buildingtype/types_<slug>.json ("villa" only for villa / townhouse)
and counts, per proposed type, the shapes that got the villa grammar (report Villa_storeys), garage doors and entry doors,
plus the built height of a few named examples. Nothing is exported, nothing is written outside data/lab/buildingtype/.

Usage: python scripts/lab_buildingtype_pyprt.py dubaiinvestmentparkfirst [--sample 12 20 22 1070]
Research use only.
"""
import json, os, sys, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from pyprt_district import prepare   # noqa: E402

LAB = os.path.join(ROOT, "data", "lab", "buildingtype")
RPK = os.path.join(ROOT, "data", "ce", "_rpk", "najma_v4.rpk")


# copied verbatim from scripts/ce_lod3_datasmith.py (importing that module would run its CE-lock / argv setup) so the
# PyPRT build gets the same per-shape streetAz the CityEngine LOD 3 lane pushes - that is what puts the porch + garage on a face
def street_bearings(slug, feats):
    """Per feature: bearing (deg, CE frame atan2(x, z)) of the outward normal of the footprint edge nearest a drivable OSM
    road (data/ce/<slug>/highways_osm.json, Overpass 'out geom'); longest edge if no road within 80 m. None if no file."""
    p = os.path.join(ROOT, "data", "ce", slug, "highways_osm.json")
    if not os.path.exists(p): return None
    import math, pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
    skip = {"footway", "path", "steps", "cycleway", "pedestrian", "track", "bridleway", "corridor", "construction", "proposed"}
    segs = []
    for e in json.load(open(p, encoding="utf-8")).get("elements", []):
        if e.get("type") != "way" or not e.get("geometry") or (e.get("tags") or {}).get("highway") in skip: continue
        pts = [tr(g["lon"], g["lat"]) for g in e["geometry"]]; segs += list(zip(pts, pts[1:]))
    cell = 60.0; grid = {}
    for a, b in segs:
        for cx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
            for cy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                grid.setdefault((cx, cy), []).append((a, b))
    def dseg(px, py, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L2)) if L2 else 0.0
        return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))
    def near(px, py, r=2):
        cx, cy = int(px // cell), int(py // cell); best = 1e9
        for i in range(cx - r, cx + r + 1):
            for j in range(cy - r, cy + r + 1):
                for a, b in grid.get((i, j), ()): best = min(best, dseg(px, py, a, b))
        return best
    out = []; stats = {"road": 0, "longest_edge": 0, "none": 0, "segments": len(segs)}
    for f in feats:
        g = f["geometry"]; ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        pts = [tr(x, y) for x, y in ring[:-1]]; n = len(pts)
        area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2  # > 0 = CCW
        edges = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]; dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy)
            if L < 2: continue
            ox, oy = (dy, -dx) if area > 0 else (-dy, dx)                 # outward normal (UTM east, north)
            az = math.degrees(math.atan2(ox, -oy))                         # CE frame: x = east, z = -north
            edges.append((near((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), -L, az))
        if not edges: out.append(None); stats["none"] += 1; continue
        # terraced rows (long thin footprints) front the street along a LONG edge: drop the short ends from the candidates
        Lmax = max(-e[1] for e in edges); Lmin = min(-e[1] for e in edges)
        if Lmax >= 24 and Lmax / max(0.1, Lmin) >= 2.2:
            edges = [e for e in edges if -e[1] >= 0.6 * Lmax] or edges
        edges.sort()
        if edges[0][0] <= 80: out.append(edges[0][2]); stats["road"] += 1
        else: out.append(min(edges, key=lambda e: e[1])[2]); stats["longest_edge"] += 1
    return out, stats


def gen(shapes, attrs, geometry):
    import pyprt
    return pyprt.ModelGenerator(shapes).generate_model(attrs, RPK, "com.esri.pyprt.PyEncoder",
                                                       {"emitReport": True, "emitGeometry": geometry})


def tally(models, idx, types):
    out = defaultdict(Counter)
    for m in models:
        fi = idx[m.get_initial_shape_index()]; t = types.get(str(fi), {}).get("type", "?"); r = m.get_report()
        out[t]["shapes"] += 1
        if "Villa_storeys_sum" in r: out[t]["villa_grammar"] += 1
        out[t]["garage_door_faces"] += int(r.get("Faces.garage_door_sum", 0) or 0)
        out[t]["entry_door_faces"] += int(r.get("Faces.entry_door_sum", 0) or 0)
        out[t]["faces"] += int(r.get("Faces_sum", 0) or 0)
    return {k: dict(v) for k, v in sorted(out.items())}


def main():
    slug = sys.argv[1]
    sample = [int(a) for a in sys.argv[sys.argv.index("--sample") + 1:]] if "--sample" in sys.argv else []
    tj = json.load(open(os.path.join(LAB, "types_%s.json" % slug), encoding="utf-8"))
    types, low = tj["types"], tj["lowStyle"]
    shapes, attrs, idx, skipped, _ = prepare(slug, 3)
    feats = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
    sb = street_bearings(slug, feats)
    if sb:
        az, st = sb
        for a, fi in zip(attrs, idx):
            if az[fi] is not None: a["streetAz"] = float(round(az[fi]))
        res_sb = st
    else:
        res_sb = None
    prop = [dict(a, lowStyle=low.get(str(fi), "villa")) for a, fi in zip(attrs, idx)]
    res = {"slug": slug, "rpk": os.path.basename(RPK), "lod": 3, "shapes": len(shapes), "street_bearings": res_sb}
    t = time.time(); res["today"] = tally(gen(shapes, attrs, False), idx, types); res["today_s"] = round(time.time() - t, 1)
    t = time.time(); res["proposed"] = tally(gen(shapes, prop, False), idx, types); res["proposed_s"] = round(time.time() - t, 1)
    if sample:
        pos = [idx.index(i) for i in sample if i in idx]
        sub_s = [shapes[p] for p in pos]; ex = {}
        for tag, A in (("today", [attrs[p] for p in pos]), ("proposed", [prop[p] for p in pos])):
            for m in gen(sub_s, A, True):
                fi = idx[pos[m.get_initial_shape_index()]]; ys = m.get_vertices()[1::3]; r = m.get_report()
                ex.setdefault(str(fi), {"type": types.get(str(fi), {}).get("type"), "bHeight": A[m.get_initial_shape_index()].get("bHeight"),
                                        "levels": A[m.get_initial_shape_index()].get("levels")})
                ex[str(fi)][tag] = {"built_h": round(max(ys) - min(ys), 1) if ys else 0.0, "villa_grammar": "Villa_storeys_sum" in r,
                                    "garage_door_faces": int(r.get("Faces.garage_door_sum", 0) or 0), "faces": int(r.get("Faces_sum", 0) or 0)}
        res["examples"] = ex
    json.dump(res, open(os.path.join(LAB, "pyprt_lowstyle_%s.json" % slug), "w", encoding="utf-8"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
