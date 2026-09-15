"""look_points.py -- DigitAlchemy(R) / Digital Abbot
Camera set-ups for street-level looks in the Unreal city, chosen on the real road network rather than the district bbox: for each
district, the residential / tertiary / secondary road segments longest and closest to the densest cluster of buildings, a camera 6 m
above the carriageway at one end, looking down the road. Also one "hero" set-up: the tallest building seen from a road 160 m away.

Output: data/ce/<slug>/look_points.json  {"street": [[cam_x,cam_y,cam_z, look_x,look_y,look_z, label], ...], "hero": [...]}  (cm)
Usage:  python scripts/look_points.py <slug> [<slug> ...] | all
"""
import json, math, os, sys
from ue_props import to_ue, CE

def build(slug):
    d = os.path.join(CE, slug); hwp = os.path.join(d, "highways_osm.json"); stp = os.path.join(d, "streets.geojson"); bgp = os.path.join(d, "buildings.geojson")
    if not ((os.path.exists(hwp) or os.path.exists(stp)) and os.path.exists(bgp)): print(f"{slug:24s} missing inputs"); return
    # roads: OSM pull where we have one, else the CityEngine street network (same OSM classes under 'hw', names under 'nm')
    ways = []
    if os.path.exists(hwp):
        for el in json.load(open(hwp, encoding="utf-8"))["elements"]:
            tags = el.get("tags") or {}; g = el.get("geometry") or []
            ways.append((tags.get("highway", ""), tags.get("name", ""), [(q["lon"], q["lat"]) for q in g]))
    else:
        for f in json.load(open(stp, encoding="utf-8"))["features"]:
            pr = f.get("properties") or {}; g = f["geometry"]
            lines = [g["coordinates"]] if g["type"] == "LineString" else (g["coordinates"] if g["type"] == "MultiLineString" else [])
            for ln in lines: ways.append((pr.get("hw", ""), pr.get("nm", ""), [(q[0], q[1]) for q in ln]))
    feats = json.load(open(bgp, encoding="utf-8"))["features"]; cents = []
    for f in feats:
        g = f["geometry"]; ring = g["coordinates"][0] if g["type"] == "Polygon" else (g["coordinates"][0][0] if g["coordinates"] else [])
        if not ring: continue
        lon = sum(q[0] for q in ring) / len(ring); lat = sum(q[1] for q in ring) / len(ring); x, y = to_ue(lon, lat)
        cents.append((x, y, float((f.get("properties") or {}).get("bHeight") or 0)))
    if not cents: return
    # density grid 150 m
    grid = {}
    for x, y, h in cents: grid[(int(x // 15000), int(y // 15000))] = grid.get((int(x // 15000), int(y // 15000)), 0) + 1
    segs = []
    for cls, nm, g in ways:
        if cls not in ("residential", "tertiary", "secondary", "living_street", "unclassified") or len(g) < 2: continue
        pts = [to_ue(lon, lat) for lon, lat in g]
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]; L = math.hypot(x2 - x1, y2 - y1)
            if L < 12000: continue
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2; dens = grid.get((int(mx // 15000), int(my // 15000)), 0)
            segs.append((dens * min(L, 40000), x1, y1, x2, y2, L, nm or cls))
    segs.sort(reverse=True); street = []
    for dens, x1, y1, x2, y2, L, nm in segs[:6]:
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        cam = (x1 + ux * 1500, y1 + uy * 1500, 600.0); look = (x1 + ux * min(L, 25000), y1 + uy * min(L, 25000), 900.0)
        street.append([round(cam[0]), round(cam[1]), cam[2], round(look[0]), round(look[1]), look[2], str(nm)])
    tx, ty, th = max(cents, key=lambda c: c[2]); best = None
    for dens, x1, y1, x2, y2, L, nm in segs:
        for t in (0.25, 0.5, 0.75):
            px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t; dd = math.hypot(px - tx, py - ty)
            if 9000 <= dd <= 30000 and (best is None or abs(dd - 16000) < abs(best[0] - 16000)): best = (dd, px, py)
    hero = [[round(best[1]), round(best[2]), 700.0, round(tx), round(ty), round(th * 100 * 0.35), "tallest"]] if best else []
    json.dump({"slug": slug, "street": street, "hero": hero}, open(os.path.join(d, "look_points.json"), "w"))
    print(f"{slug:24s} street set-ups {len(street)}  hero {'yes' if hero else 'no'}  tallest {round(th)} m", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")] or ["all"]
    slugs = sorted(d for d in os.listdir(CE) if not d.startswith("_") and os.path.exists(os.path.join(CE, d, "buildings.geojson"))) if args == ["all"] else args
    for s in slugs:
        try: build(s)
        except Exception as ex: print(f"{s}: FAILED {str(ex)[:120]}")
