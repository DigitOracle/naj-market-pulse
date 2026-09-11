"""ue_props.py -- DigitAlchemy(R) / Digital Abbot
Street dressing positions for the Unreal city: parked and moving cars along the road network, and lamp columns down the main roads.
Fabricated on purpose (Kendall, 11 Sep 2026: buildings exact, dressing free), but placed on the real street geometry so they sit in
lanes and bays rather than through walls.

Output: data/ce/<slug>/props_ue.json  {"cars": [[x_cm, y_cm, yaw_deg, colour_index, scale]], "lamps": [[x, y, yaw]]}

Usage:  python scripts/ue_props.py <slug> [<slug> ...] | all
"""
import json, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
E0 = 328289.0; N0 = 2784598.0
# highway class -> (car spacing m, lane offset m, lamp spacing m, lamp offset m)
ROAD = {"motorway": (55.0, 5.5, 45.0, 13.0), "trunk": (50.0, 5.5, 45.0, 12.0), "primary": (40.0, 5.0, 40.0, 10.0),
        "secondary": (38.0, 4.5, 45.0, 9.0), "tertiary": (36.0, 4.0, 50.0, 8.0), "residential": (30.0, 3.2, 0.0, 0.0),
        "living_street": (34.0, 3.0, 0.0, 0.0), "unclassified": (40.0, 3.6, 0.0, 0.0), "service": (48.0, 2.6, 0.0, 0.0)}
N_COLOURS = 8


def to_ue(lon, lat):
    from pyproj import Transformer
    global _TR
    try: tr = _TR
    except NameError: tr = _TR = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    e, n = tr.transform(lon, lat)
    return (e - E0) * 100.0, (-n + N0) * 100.0


def build(slug):
    d = os.path.join(CE, slug)
    p = os.path.join(d, "highways_osm.json")
    if not os.path.exists(p): print(f"{slug:24s} no highways file"); return
    hw = json.load(open(p, encoding="utf-8"))["elements"]
    rnd = random.Random((hash(slug) ^ 0x5EED) & 0xffffffff)
    cars = []; lamps = []
    for el in hw:
        g = el.get("geometry") or []
        if len(g) < 2: continue
        cls = (el.get("tags") or {}).get("highway", "")
        car_step, lane, lamp_step, lamp_off = ROAD.get(cls, (0, 0, 0, 0))
        if not car_step: continue
        pts = [to_ue(q["lon"], q["lat"]) for q in g]
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy)
            if L < 400: continue
            ux, uy = dx / L, dy / L; nx, ny = -uy, ux
            head = math.degrees(math.atan2(uy, ux))
            n_c = int(L / (car_step * 100.0))
            for k in range(n_c + 1):
                t = k * car_step * 100.0 + (rnd.random() - 0.5) * 400.0
                if t < 0 or t > L: continue
                side = 1 if (k % 2 == 0) else -1
                px = x1 + ux * t + nx * side * lane * 100.0
                py = y1 + uy * t + ny * side * lane * 100.0
                yaw = head if side == 1 else (head + 180.0) % 360.0
                cars.append([round(px), round(py), round(yaw, 1), rnd.randrange(N_COLOURS), round(0.95 + rnd.random() * 0.18, 2)])
            if lamp_step:
                n_l = int(L / (lamp_step * 100.0))
                for k in range(n_l + 1):
                    t = k * lamp_step * 100.0
                    for side in (1, -1):
                        lamps.append([round(x1 + ux * t + nx * side * lamp_off * 100.0), round(y1 + uy * t + ny * side * lamp_off * 100.0), round(head + (0 if side == 1 else 180), 1)])
    json.dump({"slug": slug, "cars": cars, "lamps": lamps, "counts": {"cars": len(cars), "lamps": len(lamps)}},
              open(os.path.join(d, "props_ue.json"), "w"), separators=(",", ":"))
    print(f"{slug:24s} cars={len(cars):6d}  lamps={len(lamps):6d}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    slugs = sorted(s for s in os.listdir(CE) if not s.startswith("_") and os.path.exists(os.path.join(CE, s, "highways_osm.json"))) if args == ["all"] else args
    for s in slugs:
        try: build(s)
        except Exception as ex: print(f"{s}: FAILED {str(ex)[:150]}", flush=True)
