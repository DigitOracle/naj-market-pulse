"""lab_streets_prep.py -- offline half of the LAB streets lane (technique #3). Plain CPython, no CityEngine.

Reads data/ce/<slug>/streets.geojson (OSM ways with CE-style width fields sw/swl/swr/nright/cline), and writes
data/lab/streets/<slug>/:
  prep.json          per-feature scene polylines (x = easting, y = 0, z = -northing, UTM 40N / EPSG:32640 - the same frame
                     the building scenes use) + the lane plan (street configuration) each feature gets
  source_audit.json  what is wrong with the source for a CE street graph (dangling ends, near-misses, duplicate ways,
                     bridges with no vertical profile, widths that are class defaults, corridors that overlap buildings
                     or each other)

Vertex thinning: OSM curves carry a vertex every few metres and CE makes one graph segment (and one set of lane shapes) per
vertex pair, so each run BETWEEN protected vertices (feature ends + any vertex another feature shares = a real junction) is
Douglas-Peucker simplified at --tol m (default 0.5). Protected vertices are never moved, so topology is untouched.

Usage: python scripts/lab_streets_prep.py [businessbay] [--tol 0.5] [--keep-bridges]
"""
import collections, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab_streets_ce import CEDIR, LAB, log, jdump
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.strtree import STRtree
from shapely.ops import unary_union

args = sys.argv[1:]
TOL = float(args[args.index("--tol") + 1]) if "--tol" in args else 0.5
KEEP_BRIDGES = "--keep-bridges" in args
SLUG = next((a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--tol")), "businessbay")
LANE_W = 3.5
tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)


def lane_plan(p):
    """Street configuration for one feature: list of (kind, width, side, travel) from the LEFT edge to the RIGHT edge of
    the segment (CE lane index order). Right-hand traffic: forward lanes on the right, reverse on the left."""
    sw, swl, swr = float(p["sw"]), float(p["swl"]), float(p["swr"])
    n = max(1, int(round(sw / LANE_W)))
    lw = round(sw / n, 3)
    if str(p.get("oneway")) == "yes":
        fwd, rev = n, 0
    else:
        fwd = int(math.ceil(n / 2.0)); rev = n - fwd
    def side(w, s):
        if w >= 2.5:
            parts = [("pave", round(w - 1.5, 2)), ("verge", 1.5)]      # verge 1.5 m: grass strip, date palms + lamps
        elif w >= 2.0:
            parts = [("pave", round(w - 0.8, 2)), ("verge", 0.8)]      # verge 0.8 m: paved, lamps only
        elif w > 0:
            parts = [("pave", w)]
        else:
            parts = []
        return [(k, wd, s, None) for k, wd in parts]                  # outside -> kerb
    left = side(swl, "L")
    right = list(reversed(side(swr, "R")))
    cars = [("car", lw, None, "Reverse")] * rev + [("car", lw, None, "Forward")] * fwd
    return left + cars + right


def plan_key(plan):
    return "lab_" + "_".join("%s%s%s%s" % (k[0], w, s or "", (t or "")[:1]) for k, w, s, t in plan)


def main():
    src = os.path.join(CEDIR, SLUG, "streets.geojson")
    out_dir = os.path.join(LAB, SLUG); os.makedirs(out_dir, exist_ok=True)
    feats = json.load(open(src, encoding="utf-8"))["features"]
    audit = {"slug": SLUG, "source": os.path.relpath(src, os.path.dirname(CEDIR)), "features": len(feats), "tol_m": TOL}
    # --- scene coordinates + vertex sharing
    rows = []
    usage = collections.Counter()
    for i, f in enumerate(feats):
        p = f["properties"]
        cs = [tuple(c[:2]) for c in f["geometry"]["coordinates"]]
        key_ll = [(round(x, 7), round(y, 7)) for x, y in cs]
        for k in set(key_ll):
            usage[k] += 1
        utm = [tr.transform(x, y) for x, y in cs]
        rows.append({"i": i, "p": p, "ll": key_ll, "utm": utm})
    ends = collections.Counter()
    for r in rows:
        ends[r["ll"][0]] += 1; ends[r["ll"][-1]] += 1
    # --- audit: topology
    dangling = [k for k, v in ends.items() if v == 1 and usage[k] == 1]
    minx = min(x for r in rows for x, _ in r["utm"]); maxx = max(x for r in rows for x, _ in r["utm"])
    miny = min(y for r in rows for _, y in r["utm"]); maxy = max(y for r in rows for _, y in r["utm"])
    bb_ll = {}
    for r in rows:
        for k, (x, y) in zip(r["ll"], r["utm"]):
            bb_ll[k] = (x, y)
    on_edge = sum(1 for k in dangling if min(bb_ll[k][0] - minx, maxx - bb_ll[k][0], bb_ll[k][1] - miny, maxy - bb_ll[k][1]) < 5.0)
    lines = [LineString(r["utm"]) for r in rows]
    tree = STRtree(lines)
    near_miss = []
    for k in dangling:
        pt = Point(bb_ll[k])
        owner = [r["i"] for r in rows if k in (r["ll"][0], r["ll"][-1])][0]
        for j in tree.query(pt.buffer(3.0)):
            j = int(j)
            if j != owner and lines[j].distance(pt) < 3.0:
                near_miss.append({"feature": owner, "osm_id": rows[owner]["p"].get("osm_id"), "to_feature": j,
                                  "gap_m": round(lines[j].distance(pt), 2)})
                break
    dup = collections.Counter(tuple(r["ll"]) for r in rows)
    rev_dup = sum(1 for r in rows if tuple(reversed(r["ll"])) in dup and tuple(reversed(r["ll"])) != tuple(r["ll"]))
    zero = [r["i"] for r in rows if LineString(r["utm"]).length < 0.5]
    bridges = [r["i"] for r in rows if int(r["p"].get("bridge") or 0) == 1]
    audit.update({
        "vertices": sum(len(r["ll"]) for r in rows),
        "distinct_endpoints": len(ends),
        "dangling_ends": len(dangling),
        "dangling_on_district_clip_edge_5m": on_edge,
        "dangling_interior": len(dangling) - on_edge,
        "near_miss_ends_lt3m": len(near_miss), "near_miss_sample": near_miss[:15],
        "duplicate_ways_same_vertices": sum(v - 1 for v in dup.values() if v > 1),
        "reversed_duplicate_ways": rev_dup,
        "zero_length_ways": len(zero),
        "bridges": len(bridges), "bridge_osm_ids": [rows[i]["p"].get("osm_id") for i in bridges][:80],
        "bridges_note": "bridge=1 carries no layer/height/profile, so a CE graph can only lay it flat at grade across the "
                        "streets it passes over; dropped from the lab build unless --keep-bridges",
        "hw_classes": dict(collections.Counter(r["p"]["hw"] for r in rows)),
        "net": dict(collections.Counter(r["p"]["net"] for r in rows)),
    })
    # --- audit: widths are class defaults, not measurements
    wc = collections.Counter((r["p"]["sw"], r["p"]["lanes"]) for r in rows)
    audit["width_is_lanes_x_3_5"] = sum(1 for r in rows if abs(float(r["p"]["sw"]) - LANE_W * int(r["p"]["lanes"])) < 1e-6)
    audit["distinct_width_keys"] = len(set(r["p"]["key"] for r in rows))
    audit["twoway_nright_mismatch"] = sum(1 for r in rows if r["p"]["oneway"] != "yes" and int(r["p"]["nright"]) * 2 != int(r["p"]["lanes"]))
    # --- corridors (carriageway + both sidewalks) vs buildings and vs each other
    corr = []
    for r, ln in zip(rows, lines):
        p = r["p"]
        if int(p.get("bridge") or 0) == 1:
            corr.append(None); continue
        half = float(p["sw"]) / 2 + max(float(p["swl"]), float(p["swr"]))
        corr.append(ln.buffer(half, cap_style=2, join_style=2))
    bpath = os.path.join(CEDIR, SLUG, "buildings.geojson")
    if os.path.exists(bpath):
        bfe = json.load(open(bpath, encoding="utf-8"))["features"]
        polys = []
        for f in bfe:
            g = shape(f["geometry"])
            gs = g.geoms if g.geom_type == "MultiPolygon" else [g]
            for pg in gs:
                from shapely.geometry import Polygon
                polys.append(Polygon([tr.transform(x, y) for x, y in pg.exterior.coords]).buffer(0))
        btree = STRtree(polys)
        hits = 0; area = 0.0; hit_feats = set()
        for i, c in enumerate(corr):
            if c is None:
                continue
            for j in btree.query(c):
                inter = c.intersection(polys[int(j)]).area
                if inter > 1.0:
                    hits += 1; area += inter; hit_feats.add(i)
        road_area = unary_union([c for c in corr if c is not None]).area
        audit["buildings"] = len(polys)
        audit["corridor_x_building"] = {"pairs_gt_1m2": hits, "features": len(hit_feats), "area_m2": round(area),
                                        "pct_of_corridor_area": round(100 * area / road_area, 2), "corridor_area_m2": round(road_area)}
    # corridor overlap between ways that do NOT share a vertex (dual carriageways drawn too close for their widths)
    ctree = STRtree([c if c is not None else Point(0, 0).buffer(0.01) for c in corr])
    ov_pairs = 0; ov_area = 0.0
    sets = [set(r["ll"]) for r in rows]
    for i, c in enumerate(corr):
        if c is None:
            continue
        for j in ctree.query(c):
            j = int(j)
            if j <= i or corr[j] is None or sets[i] & sets[j]:
                continue
            a = c.intersection(corr[j]).area
            if a > 5.0:
                ov_pairs += 1; ov_area += a
    audit["corridor_overlap_unconnected"] = {"pairs_gt_5m2": ov_pairs, "area_m2": round(ov_area)}
    # --- thinning + plan
    prot = {k for k, v in usage.items() if v > 1} | set(ends)
    out_feats = []; v_in = v_out = 0
    for r in rows:
        if int(r["p"].get("bridge") or 0) == 1 and not KEEP_BRIDGES:
            continue
        ll, utm = r["ll"], r["utm"]
        keep_idx = [0] + [k for k in range(1, len(ll) - 1) if ll[k] in prot] + [len(ll) - 1]
        pts = []
        for a, b in zip(keep_idx, keep_idx[1:]):
            run = LineString(utm[a:b + 1]).simplify(TOL, preserve_topology=False) if b - a > 1 else LineString(utm[a:b + 1])
            cs = list(run.coords)
            pts.extend(cs if not pts else cs[1:])
        # drop consecutive near-duplicates (< 0.05 m) that would become zero-length segments
        clean = [pts[0]]
        for q in pts[1:]:
            if math.dist(q, clean[-1]) >= 0.05:
                clean.append(q)
        if len(clean) < 2:
            continue
        v_in += len(utm); v_out += len(clean)
        plan = lane_plan(r["p"])
        verts = []
        for x, y in clean:
            verts += [round(x, 3), 0.0, round(-y, 3)]
        out_feats.append({"i": r["i"], "osm_id": r["p"].get("osm_id"), "hw": r["p"]["hw"], "net": r["p"]["net"],
                          "nm": r["p"].get("nm") or "", "cfg": plan_key(plan), "verts": verts})
    plans = {}
    for r in rows:
        pl = lane_plan(r["p"]); plans[plan_key(pl)] = pl
    used = {f["cfg"] for f in out_feats}
    audit["thinning"] = {"vertices_in": v_in, "vertices_out": v_out, "segments_if_unthinned": v_in - len(out_feats),
                         "segments_expected": v_out - len(out_feats), "features_built": len(out_feats)}
    audit["configs"] = len(used)
    jdump({"slug": SLUG, "crs": "EPSG:32640", "frame": "x = easting, y = up, z = -northing (m), absolute - same as the building scenes",
           "tol_m": TOL, "features": out_feats, "plans": {k: v for k, v in plans.items() if k in used}},
          os.path.join(out_dir, "prep.json"))
    jdump(audit, os.path.join(out_dir, "source_audit.json"))
    log(json.dumps({k: v for k, v in audit.items() if k not in ("near_miss_sample", "bridge_osm_ids")}, indent=1))


if __name__ == "__main__":
    main()
