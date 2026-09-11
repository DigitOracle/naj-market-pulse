"""ue_greenery.py -- DigitAlchemy(R) / Digital Abbot
Tree and palm positions for the Unreal city, from the same OpenStreetMap geometry the ground layers use: palms spaced along every
street that carries them (primary through residential), broadleaf trees scattered inside parks, gardens, grass and golf polygons.
Deterministic: the same district always produces the same planting, so a re-render matches the last one.

Output: data/ce/<slug>/greenery_ue.json
  {"slug", "palms": [[x_cm, y_cm, yaw_deg, scale], ...], "trees": [...], "counts": {...}}
Unreal cm, same frame as ue_city_build.py (X = easting, Y = -northing, fixed origin offset).

Usage:  python scripts/ue_greenery.py <slug> [<slug> ...] | all
"""
import json, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
OFF = [-328289.0, 0.0, 2784598.0]                      # the Hartland Datasmith offset: the whole city shares it
LAT0 = 25.1                                             # metres per degree at Dubai
M_LAT = 111320.0; M_LON = 111320.0 * math.cos(math.radians(LAT0))
E0 = 328289.0; N0 = 2784598.0

# streets that get street trees, and how far apart (m) / how far off the centreline (m)
STREET = {"primary": (18.0, 11.0), "secondary": (16.0, 9.0), "tertiary": (15.0, 8.0), "residential": (14.0, 6.5), "living_street": (14.0, 6.0), "unclassified": (16.0, 7.0), "service": (0, 0), "trunk": (22.0, 14.0)}
# polygons that get trees, and one tree per this many m2
GREEN = {"park": 260.0, "garden": 200.0, "grass": 420.0, "golf_course": 900.0, "recreation_ground": 400.0, "dog_park": 300.0, "village_green": 300.0, "pitch": 0.0, "playground": 600.0}


def to_ue(lon, lat):
    """lon/lat -> Unreal cm, via the same UTM-like local frame the city build uses."""
    from pyproj import Transformer
    global _TR
    try: tr = _TR
    except NameError: tr = _TR = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    e, n = tr.transform(lon, lat)
    return (e - E0) * 100.0, (-n + N0) * 100.0


def poly_area_m2(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0 / 10000.0                       # cm2 -> m2


def inside(pt, poly):
    x, y = pt; c = False; n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i - 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1): c = not c
    return c


def build(slug):
    d = os.path.join(CE, slug)
    lu = json.load(open(os.path.join(d, "landuse_osm.json"), encoding="utf-8"))["elements"] if os.path.exists(os.path.join(d, "landuse_osm.json")) else []
    hw = json.load(open(os.path.join(d, "highways_osm.json"), encoding="utf-8"))["elements"] if os.path.exists(os.path.join(d, "highways_osm.json")) else []
    rnd = random.Random(hash(slug) & 0xffffffff)
    palms = []; trees = []
    for el in hw:
        g = el.get("geometry") or []
        if len(g) < 2: continue
        cls = (el.get("tags") or {}).get("highway", "")
        step, off = STREET.get(cls, (0, 0))
        if not step: continue
        pts = [to_ue(p["lon"], p["lat"]) for p in g]
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy)
            if L < 100: continue
            ux, uy = dx / L, dy / L; nx, ny = -uy, ux
            n = int(L / (step * 100.0))
            for k in range(n + 1):
                t = k * step * 100.0
                for side in (1, -1):
                    jitter = (rnd.random() - 0.5) * 120.0
                    px = x1 + ux * (t + jitter) + nx * side * off * 100.0
                    py = y1 + uy * (t + jitter) + ny * side * off * 100.0
                    palms.append([round(px), round(py), round(rnd.random() * 360, 1), round(0.85 + rnd.random() * 0.4, 2)])
    for el in lu:
        g = el.get("geometry") or []
        if len(g) < 4: continue
        tags = el.get("tags") or {}
        key = tags.get("leisure") or tags.get("landuse") or ""
        per = GREEN.get(key, 0.0)
        if not per: continue
        poly = [to_ue(p["lon"], p["lat"]) for p in g]
        area = poly_area_m2(poly)
        if area < 200: continue
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        want = int(min(area / per, 900))
        tries = 0
        while want > 0 and tries < want * 25:
            tries += 1
            px = rnd.uniform(min(xs), max(xs)); py = rnd.uniform(min(ys), max(ys))
            if inside((px, py), poly):
                trees.append([round(px), round(py), round(rnd.random() * 360, 1), round(0.8 + rnd.random() * 0.6, 2)]); want -= 1
    out = {"slug": slug, "offset_ce_xyz": OFF, "palms": palms, "trees": trees, "counts": {"palms": len(palms), "trees": len(trees)}}
    json.dump(out, open(os.path.join(d, "greenery_ue.json"), "w"), separators=(",", ":"))
    print(f"{slug:26s} palms={len(palms):6d}  trees={len(trees):6d}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    slugs = sorted(s for s in os.listdir(CE) if not s.startswith("_") and os.path.isdir(os.path.join(CE, s)) and os.path.exists(os.path.join(CE, s, "landuse_osm.json"))) if args == ["all"] else args
    for s in slugs:
        try: build(s)
        except Exception as ex: print(f"{s}: FAILED {str(ex)[:160]}", flush=True)
