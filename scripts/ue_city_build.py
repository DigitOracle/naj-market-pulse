"""ue_city_build.py -- all of Dubai for Unreal, straight from the truth store: extruded footprints per district, grouped by facade
class and variant, in one shared Unreal frame (the Hartland Datasmith origin, so the existing Hartland assets line up).

For every district in data/ce/<slug>/buildings.geojson: footprint rings (WGS84 -> UTM 40N -> Unreal cm), height from
data/graph/najma.duckdb building.height_m (fallback: geojson bHeight, then 12 m), facade class/variant from
data/ce/<slug>/facade_v2.json (scripts/facade_classes.py). Walls are quads with outward normals, roofs are earcut fans facing up.

Output: data/ce/_city/<slug>.json  {"slug","origin","groups":[{"cls","v","n","verts":[x,y,z,...],"tris":[...]}], "bbox_cm":[...]}
        data/ce/_city/INDEX.json   per-district counts + bboxes
Usage:  python scripts/ue_city_build.py [slug ...]        (no args = all 41)
"""
import json, math, os, sys, time
import numpy as np
import mapbox_earcut as earcut
import duckdb
from pyproj import Transformer
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.geometry.polygon import orient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(CE, "_city"); os.makedirs(OUT, exist_ok=True)
OFF = json.load(open(os.path.join(CE, "_datasmith", "sobhaheartland_georef.json")))["offset_ce_xyz"]     # shared city origin
tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def to_ue(e, n): return ((e + OFF[0]) * 100.0, (-n + OFF[2]) * 100.0)


def heights():
    con = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
    h = {(d, int(i)): float(x) for d, i, x in con.execute("select district, footprint_i, height_m from building where height_m is not null").fetchall()}
    con.close(); return h


def prism(pg, h_cm, V, T):
    """Append one extruded polygon (UE cm, z 0..h) to V/T with outward walls and an upward roof."""
    pg = orient(pg, 1.0)
    rings = [list(pg.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in pg.interiors]
    rings = [[to_ue(x, y) for x, y in r] for r in rings]
    cx = sum(p[0] for p in rings[0]) / len(rings[0]); cy = sum(p[1] for p in rings[0]) / len(rings[0])
    for ri, ring in enumerate(rings):
        hole = ri > 0
        hcx = sum(p[0] for p in ring) / len(ring); hcy = sum(p[1] for p in ring) / len(ring)
        for k in range(len(ring)):
            ax, ay = ring[k]; bx, by = ring[(k + 1) % len(ring)]
            base = len(V) // 3
            V += [ax, ay, 0.0, bx, by, 0.0, bx, by, h_cm, ax, ay, h_cm]
            # normal of (a0,b0,b1): edge (b-a) x up  -> (dy, -dx, 0); outward if it points away from the ring centroid (toward it for holes)
            nx, ny = (by - ay), -(bx - ax); mx, my = (ax + bx) / 2 - (hcx if hole else cx), (ay + by) / 2 - (hcy if hole else cy)
            out_ok = (nx * mx + ny * my) > 0
            if hole: out_ok = not out_ok
            if out_ok: T += [base, base + 1, base + 2, base, base + 2, base + 3]
            else:      T += [base, base + 2, base + 1, base, base + 3, base + 2]
    # roof
    pts = np.array([p for r in rings for p in r], dtype=np.float64); ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(pts, ends).tolist(); base = len(V) // 3
    for x, y in pts: V += [float(x), float(y), h_cm]
    for i in range(0, len(idx), 3):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        ax, ay = pts[a]; bx, by = pts[b]; cx2, cy2 = pts[c]
        up = (bx - ax) * (cy2 - ay) - (by - ay) * (cx2 - ax)          # z of the cross product; UE left-handed: flip so normal is +Z
        T += ([base + a, base + c, base + b] if up > 0 else [base + a, base + b, base + c])


def build(slug, H):
    feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    fac = json.load(open(os.path.join(CE, slug, "facade_v2.json"), encoding="utf-8"))["buildings"]
    groups = {}; n = 0; hsrc = {"store": 0, "geojson": 0, "default": 0}
    xs, ys = [], []
    for i, f in enumerate(feats):
        g = shape(f["geometry"])
        if g.is_empty: continue
        h = H.get((slug, i))
        if h is None:
            bh = f["properties"].get("bHeight")
            if bh: h = float(bh); hsrc["geojson"] += 1
            else: h = 12.0; hsrc["default"] += 1
        else: hsrc["store"] += 1
        h = max(3.0, min(h, 900.0))
        fb = fac.get(str(i), {}); key = (fb.get("class", "render"), int(fb.get("variant", i % 3)) % 3)
        G = groups.setdefault(key, {"cls": key[0], "v": key[1], "n": 0, "verts": [], "tris": []})
        polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        for pg in polys:
            if not isinstance(pg, Polygon) or pg.area < 1e-10: continue
            pg = pg.simplify(1e-6, preserve_topology=True)
            if len(pg.exterior.coords) < 4: continue
            prism(pg, h * 100.0, G["verts"], G["tris"])
        G["n"] += 1; n += 1
        b = g.bounds; xs += [b[0], b[2]]; ys += [b[1], b[3]]
    e0, n0 = tr.transform(min(xs), min(ys)); e1, n1 = tr.transform(max(xs), max(ys))
    x0, y1 = to_ue(e0, n0); x1, y0 = to_ue(e1, n1)
    out = {"slug": slug, "origin_offset_ce_xyz": OFF, "buildings": n, "heights": hsrc, "bbox_cm": [round(x0), round(y0), round(x1), round(y1)],
           "groups": sorted(groups.values(), key=lambda g: (g["cls"], g["v"]))}
    for G in out["groups"]:
        G["verts"] = [round(v, 1) for v in G["verts"]]
    p = os.path.join(OUT, f"{slug}.json"); json.dump(out, open(p, "w"))
    tris = sum(len(G["tris"]) // 3 for G in out["groups"])
    log(f"{slug:28s} {n:5d} bldgs {len(out['groups']):2d} groups {tris:7d} tris {os.path.getsize(p)//1024:6d} KB heights={hsrc}")
    return {"slug": slug, "buildings": n, "groups": len(out["groups"]), "tris": tris, "bbox_cm": out["bbox_cm"], "heights": hsrc, "file": os.path.basename(p)}


def main():
    slugs = sys.argv[1:] or sorted(d for d in os.listdir(CE) if not d.startswith("_") and os.path.exists(os.path.join(CE, d, "buildings.geojson")))
    H = heights(); log(f"heights in store: {len(H)}; districts: {len(slugs)}")
    idx_path = os.path.join(OUT, "INDEX.json"); idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    for s in slugs:
        try: idx[s] = build(s, H)
        except Exception as ex: log(f"{s}: FAILED {ex}")
        json.dump(idx, open(idx_path, "w"), indent=1)
    log(f"done: {sum(v['buildings'] for v in idx.values())} buildings, {sum(v['tris'] for v in idx.values())} triangles -> {idx_path}")


if __name__ == "__main__":
    main()
