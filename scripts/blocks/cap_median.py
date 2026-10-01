"""Cap estimated heights on small footprints (no more 90 m needles on kiosks).
A community_median or typical_* height on a footprint under 200 m2 becomes 4 m (src "small_structure_cap");
measured / register / twin heights are never touched. Writes the overlay files in place (a .bak beside each), then the caller rebuilds.
  python cap_median.py            report only
  python cap_median.py --write    apply
"""
import glob, json, os, shutil, sys
from pyproj import Transformer
from shapely.geometry import shape

REPO = r"C:\Dev\naj-market-pulse\data"
U = Transformer.from_crs(4326, 32640, always_xy=True)
KIOSK, SMALL, CAP_K, CAP_S = 60.0, 400.0, 4.0, 10.0
write = "--write" in sys.argv


def area(geom):
    rings = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]] if geom["type"] == "MultiPolygon" else []
    tot = 0.0
    for r in rings:
        xs, ys = U.transform([c[0] for c in r], [c[1] for c in r])
        tot += abs(0.5 * sum(xs[k] * ys[k + 1] - xs[k + 1] * ys[k] for k in range(len(xs) - 1)))
    return tot


def estimated(src):
    return str(src or "").startswith("community_median")


def cap_for(a):
    return CAP_K if a < KIOSK else CAP_S if a < SMALL else None


total = 0
# the app's districts: overlay keyed by footprint i of buildings.geojson
for ov in sorted(glob.glob(os.path.join(REPO, "ce", "*", "blocks_heights.json"))):
    slug = os.path.basename(os.path.dirname(ov))
    feats = json.load(open(os.path.join(REPO, "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
    d = json.load(open(ov, encoding="utf-8"))
    n = 0
    for k, v in d.items():
        if not isinstance(v, dict) or not estimated(v.get("src")):
            continue
        i = int(k)
        cap = cap_for(area(feats[i]["geometry"])) if i < len(feats) else None
        if cap is not None and float(v.get("h", 0)) > cap:
            d[k] = {"h": cap, "src": "small_footprint_cap(was %s %.1f m)" % (v.get("src"), float(v["h"]))}
            n += 1
    total += n
    if n:
        print("%-28s capped %d" % (slug, n))
        if write:
            shutil.copy(ov, ov + ".bak")
            json.dump(d, open(ov, "w", encoding="utf-8"), ensure_ascii=False)
# the city set: blocks.json carries the final heights; its overlay is keyed by i with the footprint centre
for bj in sorted(glob.glob(os.path.join(REPO, "blocks_city", "*", "blocks.json"))):
    slug = os.path.basename(os.path.dirname(bj))
    ovp = os.path.join(os.path.dirname(bj), "heights_overlay.json")
    g = json.load(open(bj, encoding="utf-8"))
    ov = json.load(open(ovp, encoding="utf-8")) if os.path.exists(ovp) else {}
    rows = ov.get("rows", ov) if isinstance(ov, dict) else {}
    n = 0
    for f in g["features"]:
        p = f["properties"]
        if p.get("k") != "b" or not estimated(p.get("hs")):
            continue
        cap = cap_for(area(f["geometry"]))
        if cap is not None and float(p.get("h", 0)) > cap:
            key = str(p["i"])
            ent = dict(rows.get(key, {})) if isinstance(rows.get(key), dict) else {}
            ent.update({"h": cap, "src": "small_footprint_cap(was %s %.1f m)" % (p.get("hs"), float(p["h"]))})
            if "c" not in ent:
                c = shape(f["geometry"]).centroid
                ent["c"] = [round(c.x, 6), round(c.y, 6)]
            rows[key] = ent
            n += 1
    total += n
    if n:
        print("%-28s capped %d (city)" % (slug, n))
        if write and os.path.exists(ovp):
            shutil.copy(ovp, ovp + ".bak")
            if isinstance(ov, dict) and "rows" in ov:
                ov["rows"] = rows
            else:
                ov = rows
            json.dump(ov, open(ovp, "w", encoding="utf-8"), ensure_ascii=False)
print("total capped:", total, "(written)" if write else "(report only)")
