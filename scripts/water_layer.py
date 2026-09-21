"""Water for the twin: the real coastline, clipped to each district and simplified, so the sea is a shape rather than a blue disc.

Source: Overture Maps `water` (data/names/overture_raw/<slug>_water.geojson). The Gulf arrives as one enormous polygon covering
half the map, so every feature is clipped to the district's own bbox, then simplified in metres. Swimming pools are dropped -
at this scale they are noise, and a pool rendered with the sea shader looks absurd.

Output data/ce/<slug>/water.json   {"scene": {x0,z0,x1,z1}, "polys": [[[x,z], ...], ...], "classes": {...}}   scene metres,
                                   x = UTM easting, z = -northing, the same frame the massing and imagery use.
Pushed to KV as water_<slug>; the twin draws it with a Fresnel + depth-fade shader just above the terrain sheet.
Usage: python scripts/water_layer.py [slug ...] [--no-push]
"""
import json, os, sys, glob, time
from shapely.geometry import shape, box, mapping
from shapely.ops import transform, unary_union
import pyproj
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
RAW = os.path.join(ROOT, "data", "names", "overture_raw"); CE = os.path.join(ROOT, "data", "ce")
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
DROP = {"swimming_pool", "fountain", "drain"}          # not sea; at district scale they are noise
PAD_M = 900.0                                          # how far past the footprints the water may reach
SIMPLIFY_M = 6.0                                       # coastline detail we keep; below this is invisible at twin zoom


def district_box(slug):
    """the district's own extent in scene metres, padded, from its footprints"""
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj): return None
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for f in json.load(open(gj, encoding="utf-8"))["features"]: walk(f["geometry"]["coordinates"])
    if not xs: return None
    a = TO_UTM(min(xs), min(ys)); b = TO_UTM(max(xs), max(ys))
    return box(min(a[0], b[0]) - PAD_M, min(a[1], b[1]) - PAD_M, max(a[0], b[0]) + PAD_M, max(a[1], b[1]) + PAD_M)


_CITY = {"feats": None}


def city_water():
    """Every district can have real water. Only three had their own Overture cut, so the rest drew no water plane at all and
    what showed through was the aerial sheet - where the creek and the canals are almost black, with the towers' shadows baked
    into them (Kendall, 21 Sep 2026: "why is the water black?"). The Gulf, the creek, the canals and the lakes are all in the
    one Dubai-wide file, so a district without its own cut is clipped out of that. Loaded once per run, not once per district."""
    if _CITY["feats"] is None:
        p, out = os.path.join(RAW, "dubai_water.geojson"), []
        if os.path.exists(p):
            for f in json.load(open(p, encoding="utf-8"))["features"]:
                pr = f.get("properties") or {}
                cls = pr.get("class") or pr.get("subtype") or "water"
                if cls in DROP: continue
                g = f.get("geometry") or {}
                if g.get("type") not in ("Polygon", "MultiPolygon"): continue
                try:
                    geom = transform(TO_UTM, shape(g))
                    if not geom.is_valid: geom = geom.buffer(0)
                except Exception:
                    continue
                if not geom.is_empty: out.append((geom, cls))
            print(f"  city water: {len(out)} polygons from dubai_water.geojson")
        _CITY["feats"] = out
    return _CITY["feats"]


def features(slug):
    """The district's own Overture cut where it exists, the city-wide file clipped to it otherwise."""
    src = os.path.join(RAW, f"{slug}_water.geojson")
    if not os.path.exists(src) or os.path.getsize(src) < 200:
        return city_water(), "city"
    out = []
    for f in json.load(open(src, encoding="utf-8"))["features"]:
        p = f.get("properties") or {}
        cls = p.get("class") or p.get("subtype") or "water"
        if cls in DROP: continue
        g = f.get("geometry") or {}
        if g.get("type") not in ("Polygon", "MultiPolygon"): continue
        try:
            geom = transform(TO_UTM, shape(g))
            if not geom.is_valid: geom = geom.buffer(0)
        except Exception:
            continue
        if not geom.is_empty: out.append((geom, cls))
    return out, "district"


def run(slug, do_push, tok):
    bb = district_box(slug)
    if bb is None: return None
    feats, whence = features(slug)
    if not feats: return None
    keep, classes = [], {}
    for geom, cls in feats:
        try:
            if not geom.intersects(bb): continue
            clipped = geom.intersection(bb)
        except Exception:
            continue
        if clipped.is_empty or clipped.area < 400: continue
        keep.append(clipped); classes[cls] = classes.get(cls, 0) + 1
    if not keep: return None
    merged = unary_union(keep).simplify(SIMPLIFY_M, preserve_topology=True)
    polys = []
    for g in (merged.geoms if merged.geom_type == "MultiPolygon" else [merged]):
        if g.area < 400: continue
        ring = [[round(x, 1), round(-y, 1)] for x, y in g.exterior.coords]      # scene z = -northing
        if len(ring) >= 4: polys.append(ring)
    if not polys: return None
    doc = {"district": slug, "generated": time.strftime("%Y-%m-%d"),
           "source": "Overture Maps water (sea, bay, lake, canal), %s cut; swimming pools removed; clipped to the district and simplified to 6 m" % whence,
           "scene": {"x0": round(bb.bounds[0], 1), "z0": round(-bb.bounds[3], 1), "x1": round(bb.bounds[2], 1), "z1": round(-bb.bounds[1], 1)},
           "classes": classes, "polys": polys}
    out = os.path.join(CE, slug, "water.json")
    json.dump(doc, open(out, "w", encoding="utf-8"))
    ok = push(f"water_{slug}", doc, tok).get("ok") if do_push else "dry"
    pts = sum(len(r) for r in polys)
    print(f"  {slug:<24} polygons {len(polys):>3} | points {pts:>6} | {os.path.getsize(out)//1024:>4} KB | {classes} -> {ok}")
    return doc


def main():
    do_push = "--no-push" not in sys.argv
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    # every district the twin can draw, not only the three with their own Overture cut
    slugs = want or sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(CE, "*", "buildings.geojson")))
    tok = env_token("INGEST_TOKEN") if do_push else None
    n = 0
    for s in slugs:
        if run(s, do_push, tok): n += 1
    print(f"water layers written: {n} of {len(slugs)}")


if __name__ == "__main__":
    main()
