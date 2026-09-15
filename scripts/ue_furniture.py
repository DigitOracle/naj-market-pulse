"""ue_furniture.py -- DigitAlchemy(R) / Digital Abbot
Street furniture positions for the Unreal city, from real data where it exists and the real street geometry otherwise
(Kendall, 11 Sep: "think of everything that would be outside"):
  bus_shelters  RTA bus stops (data/registers/bus_stop_details) inside the district bbox, snapped to the nearest road edge, facing the road
  benches       along park / garden polygon edges every ~35 m, and on pavements of residential streets every ~120 m, facing the road
  bins          one beside every bench and every shelter, offset 1.5 m
  bollards      every 6 m along the kerb of pedestrian / living streets and at park entrances (first 30 m of each park edge)
  hedges        buxus rows along villa footprint edges set out 1.2 m, a plant every 1.2 m (villa = footprint under 12 m in a district that
                has villa clusters), capped per district

Output: data/ce/<slug>/furniture_ue.json  {"bus_shelters": [[x,y,yaw]], "benches": [[x,y,yaw]], "bins": [[x,y]], "bollards": [[x,y]], "hedges": [[x,y,yaw]]}
Usage:  python scripts/ue_furniture.py <slug> [<slug> ...] | all
"""
import csv, json, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); REG = os.path.join(ROOT, "data", "registers")
E0 = 328289.0; N0 = 2784598.0
_TR = None


def to_ue(lon, lat):
    global _TR
    if _TR is None:
        from pyproj import Transformer
        _TR = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    e, n = _TR.transform(lon, lat)
    return (e - E0) * 100.0, (-n + N0) * 100.0


def seg_points(pts, step_cm, offset_cm, side=1, start=0.0):
    """points every step along a polyline, offset to one side; yields (x, y, heading_deg)"""
    out = []; carry = start
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]; dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy)
        if L < 1: continue
        ux, uy = dx / L, dy / L; nx, ny = -uy, ux; head = math.degrees(math.atan2(uy, ux)); t = carry
        while t <= L:
            out.append((x1 + ux * t + nx * side * offset_cm, y1 + uy * t + ny * side * offset_cm, head)); t += step_cm
        carry = t - L
    return out


def nearest_road(pt, roads):
    best = (1e18, None, 0.0)
    for pts, w in roads:
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]; dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
            if L2 < 1: continue
            t = max(0.0, min(1.0, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / L2)); px, py = x1 + dx * t, y1 + dy * t
            d2 = (pt[0] - px) ** 2 + (pt[1] - py) ** 2
            if d2 < best[0]: best = (d2, (px, py, math.degrees(math.atan2(dy, dx)), w), 0.0)
    return best[1], math.sqrt(best[0])


def build(slug, stops):
    d = os.path.join(CE, slug); hwp = os.path.join(d, "highways_osm.json"); lup = os.path.join(d, "landuse_osm.json"); bgp = os.path.join(d, "buildings.geojson")
    idx = json.load(open(os.path.join(CE, "_city", slug + ".json"), encoding="utf-8")); x0, y0, x1, y1 = idx["bbox_cm"][:4]
    rnd = random.Random((hash(slug) ^ 0xF00D) & 0xffffffff)
    roads = []; resi = []; ped = []
    if os.path.exists(hwp):
        for el in json.load(open(hwp, encoding="utf-8"))["elements"]:
            g = el.get("geometry") or []; tags = el.get("tags") or {}; cls = tags.get("highway", "")
            if len(g) < 2 or cls in ("footway", "path", "cycleway", "steps", "service", "track"): continue
            pts = [to_ue(q["lon"], q["lat"]) for q in g]
            w = {"motorway": 16, "trunk": 14, "primary": 12, "secondary": 10, "tertiary": 8, "residential": 6, "living_street": 5, "pedestrian": 6, "unclassified": 6}.get(cls, 6)
            roads.append((pts, w))
            if cls in ("residential", "living_street", "unclassified", "tertiary"): resi.append((pts, w))
            if cls in ("pedestrian", "living_street"): ped.append((pts, w))
    # bus shelters
    shelters = []
    for lon, lat in stops:
        x, y = to_ue(lon, lat)
        if not (x0 - 5000 <= x <= x1 + 5000 and y0 - 5000 <= y <= y1 + 5000): continue
        r, dist = nearest_road((x, y), roads)
        if r and dist < 6000:
            px, py, head, w = r; nx, ny = -math.sin(math.radians(head)), math.cos(math.radians(head))
            sd = 1 if ((x - px) * nx + (y - py) * ny) >= 0 else -1; off = (w / 2 + 2.2) * 100
            shelters.append([round(px + nx * sd * off), round(py + ny * sd * off), round((head + (180 if sd > 0 else 0)) % 360, 1)])
        else:
            shelters.append([round(x), round(y), round(rnd.random() * 360, 1)])
    # parks: benches along edges, bollards at entrances
    benches = []; bollards = []; hedges = []
    if os.path.exists(lup):
        for el in json.load(open(lup, encoding="utf-8"))["elements"]:
            tags = el.get("tags") or {}; kind = tags.get("leisure") or tags.get("landuse") or ""
            if kind not in ("park", "garden", "recreation_ground", "grass", "village_green"): continue
            g = el.get("geometry") or []
            if len(g) < 4: continue
            pts = [to_ue(q["lon"], q["lat"]) for q in g]
            for x, y, h in seg_points(pts, 3500, -250, start=rnd.random() * 3500): benches.append([round(x), round(y), round((h + 90) % 360, 1)])
            for x, y, h in seg_points(pts[:2], 600, -120): bollards.append([round(x), round(y)])
    # pavement benches on residential streets
    for pts, w in resi:
        for side in (1, -1):
            for x, y, h in seg_points(pts, 12000, (w / 2 + 2.5) * 100, side, start=rnd.random() * 12000): benches.append([round(x), round(y), round((h + (0 if side > 0 else 180)) % 360, 1)])
    for pts, w in ped:
        for side in (1, -1):
            for x, y, h in seg_points(pts, 600, (w / 2 + 0.4) * 100, side): bollards.append([round(x), round(y)])
    bins = [[b[0] + round(150 * math.cos(math.radians(b[2] + 90))), b[1] + round(150 * math.sin(math.radians(b[2] + 90)))] for b in benches] + \
           [[s[0] + round(220 * math.cos(math.radians(s[2] + 90))), s[1] + round(220 * math.sin(math.radians(s[2] + 90)))] for s in shelters]
    # hedges along villa footprints
    if os.path.exists(bgp):
        feats = json.load(open(bgp, encoding="utf-8"))["features"]
        low = [f for f in feats if float((f.get("properties") or {}).get("bHeight") or 0) <= 12 and f["geometry"]["type"] == "Polygon"]
        # 12 m is the export placeholder as well as a real villa height: treat a district as villa country only when most footprints are low
        villas = low if len(low) >= 0.5 * max(len(feats), 1) else [f for f in low if float((f.get("properties") or {}).get("bHeight") or 0) < 12]
        if len(villas) >= 40:
            for f in villas[:2500]:
                ring = f["geometry"]["coordinates"][0]; pts = [to_ue(q[0], q[1]) for q in ring]
                # signed area -> outward normal side
                area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
                side = 1 if area < 0 else -1
                for x, y, h in seg_points(pts, 120, 120, side): hedges.append([round(x), round(y), round(h, 1)])
    out = {"slug": slug, "bus_shelters": shelters, "benches": benches, "bins": bins, "bollards": bollards, "hedges": hedges,
           "counts": {k: len(v) for k, v in (("bus_shelters", shelters), ("benches", benches), ("bins", bins), ("bollards", bollards), ("hedges", hedges))}}
    json.dump(out, open(os.path.join(d, "furniture_ue.json"), "w"))
    print(f"{slug:26s} " + "  ".join(f"{k} {v:6d}" for k, v in out["counts"].items()), flush=True)


if __name__ == "__main__":
    stops = []
    for p in sorted(os.listdir(os.path.join(REG, "bus_stop_details"))):
        if p.endswith(".csv"):
            with open(os.path.join(REG, "bus_stop_details", p), encoding="utf-8-sig", errors="replace") as h:
                for r in csv.DictReader(h):
                    try: stops.append((round(float(r["stop_location_longitude"]), 5), round(float(r["stop_location_latitude"]), 5)))
                    except (TypeError, ValueError, KeyError): pass
    stops = sorted(set(stops))                      # the register has one row per route per stop: 6,968 "shelters" in Silicon Oasis before this
    print(f"{len(stops)} distinct RTA bus stop positions")
    args = [a for a in sys.argv[1:] if not a.startswith("--")] or ["all"]
    slugs = sorted(d for d in os.listdir(CE) if not d.startswith("_") and os.path.exists(os.path.join(CE, "_city", d + ".json"))) if args == ["all"] else args
    for s in slugs:
        try: build(s, stops)
        except Exception as ex: print(f"{s}: FAILED {str(ex)[:120]}", flush=True)
