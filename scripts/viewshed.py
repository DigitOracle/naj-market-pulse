"""Viewshed v1 — per-floor view verdicts from OUR footprints+heights. No external services.

Method: 2D sight-line from observer (tower centroid, floor height) to target; every
footprint crossing the line is a potential blocker. A blocker of height Hb at distance d
occludes the target plane (distance D) above observer height up to:
    min_visible_target_h = h_obs + (Hb - h_obs) * D / d
The verdict reports how much of the target remains visible. Curvature correction applied
for D > 5km. Heights honest: OSM-real where known, 12m default elsewhere (stated).

Usage: python scripts/viewshed.py --district businessbay --tower "CHURCHILL TOWER" \
       --floors 2,10,20 [--target burjkhalifa|sea|canal]
"""
import argparse, json, math, os, re, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
CE = os.path.join(HERE, "..", "data", "ce")
R_EARTH = 6371000.0
LANDMARKS = {"burjkhalifa": {"name": "Burj Khalifa", "lon": 55.27414, "lat": 25.19717, "h": 828.0}}
FLOOR_H = 3.5


def utm(lon, lat):
    import pyproj
    t = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    return t.transform(lon, lat)


def load_footprints(districts):
    from shapely.geometry import shape
    fps = []
    for sl in districts:
        p = os.path.join(CE, sl, "buildings.geojson")
        if not os.path.exists(p):
            print(f"  (no footprints for {sl} — occlusion there unmodelled)")
            continue
        gj = json.load(open(p))
        for i, f in enumerate(gj["features"]):
            fps.append({"i": f"{sl}#{i}", "g": shape(f["geometry"]),
                        "h": float(f["properties"].get("bHeight", 12)),
                        "real": bool(f["properties"].get("levels") or (f["properties"].get("bHeight", 12) != 12)),
                        "name": f["properties"].get("name", "")})
    return fps


def main():
    from shapely.geometry import LineString, Point
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", required=True)
    ap.add_argument("--tower", required=True, help="bound project name OR fp#<index>")
    ap.add_argument("--floors", default="2,10,20")
    ap.add_argument("--target", default="burjkhalifa")
    ap.add_argument("--extra-districts", default="", help="comma slugs along the sight path")
    a = ap.parse_args()

    # observer footprint from the bindings
    bp = os.path.join(CE, a.district, "bindings.json")
    binds = json.load(open(bp))["bindings"] if os.path.exists(bp) else {}
    gj = json.load(open(os.path.join(CE, a.district, "buildings.geojson")))
    from shapely.geometry import shape
    obs_i = None
    for k, v in binds.items():
        if v["project"].lower() == a.tower.lower():
            obs_i = int(k); break
    if obs_i is None and a.tower.lower().startswith("fp#"):
        obs_i = int(a.tower[3:])
    if obs_i is None:
        sys.exit(f'tower "{a.tower}" not bound in {a.district} — run bind_buildings.py or pass fp#<i>')
    obs_f = gj["features"][obs_i]
    og = shape(obs_f["geometry"]).centroid
    ox, oy = utm(og.x, og.y)
    obs_name = binds.get(str(obs_i), {}).get("project", a.tower)

    lm = LANDMARKS[a.target]
    tx, ty = utm(lm["lon"], lm["lat"])
    D = math.hypot(tx - ox, ty - oy)
    sag = (D ** 2) / (2 * R_EARTH) if D > 5000 else 0.0     # curvature drop at target
    print(f"{obs_name} ({a.district}) → {lm['name']}: distance {D/1000:.2f} km"
          + (f" · curvature drop {sag:.0f} m" if sag else ""))

    districts = [a.district] + [s for s in a.extra_districts.split(",") if s]
    fps = load_footprints(districts)
    ray = LineString([(ox, oy), (tx, ty)])

    for fl in [int(x) for x in a.floors.split(",")]:
        h_obs = fl * FLOOR_H + 1.5
        min_vis = 0.0
        blockers = []
        for f in fps:
            if f["i"] == f"{a.district}#{obs_i}":
                continue
            if not f["g"].intersects(LineString([(og.x, og.y), (lm['lon'], lm['lat'])])):
                continue
            # distance to crossing (WGS ray used for intersect test; distance via centroid utm)
            cx, cy = utm(f["g"].centroid.x, f["g"].centroid.y)
            d = math.hypot(cx - ox, cy - oy)
            if d <= 1 or d >= D:
                continue
            need = h_obs + (f["h"] - h_obs) * D / d
            if need > min_vis:
                min_vis = need
                blockers.append((f["h"], d, f["name"] or f["i"], f["real"]))
        vis_from = max(0.0, min_vis - 0 + sag)  # curvature raises the bar at the target
        if vis_from <= 0.05 * lm["h"]:
            verdict = "CLEAR — full view plausible"
        elif vis_from < lm["h"]:
            pct = 100 * (lm["h"] - vis_from) / lm["h"]
            verdict = f"PARTIAL — top {pct:.0f}% visible (above {vis_from:.0f} m)"
        else:
            verdict = "BLOCKED — no line of sight"
        est = "" if all(b[3] for b in blockers[-2:]) else " · some blocker heights are OSM-default estimates"
        top = f" · tallest blocker {blockers[-1][2][:24]} {blockers[-1][0]:.0f}m @ {blockers[-1][1]/1000:.1f}km" if blockers else ""
        print(f"  floor {fl:>2} (h={h_obs:.0f}m): {verdict}{top}{est}")


if __name__ == "__main__":
    main()
