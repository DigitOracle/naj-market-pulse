"""Label anchors for the skyline viewer: one record per NAMED building per district.
Sources, in precedence order: (1) OpenStreetMap name on the footprint (what ce_export.py kept), (2) Wikidata buildings with
coordinates (point-in-footprint or nearest footprint <= 40 m), (3) confidence-gated DLD project bindings (data/ce/<slug>/bindings.json),
(4) developer-site portfolio names geocoded onto footprints (bind_portfolio.py, later). Output data/names/anchors_<slug>.json:
{ id, name, source, dev (developer key when known), lon, lat, x, z (scene metres, y-up, z = -northing like the GLB), h (roof height m) }
plus a coverage report: how many of the TALL buildings (top 30 % by height) carry a name - those are the ones that pass in front.
Usage: python scripts/build_anchors.py [slug ...]
"""
import glob, json, math, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "names"); os.makedirs(OUT, exist_ok=True)
WIKI = json.load(open(os.path.join(OUT, "wikidata_dubai_buildings.json"), encoding="utf-8"))["items"] if os.path.exists(os.path.join(OUT, "wikidata_dubai_buildings.json")) else []

def rings(geom):
    if geom["type"] == "Polygon": return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon": return [p[0] for p in geom["coordinates"]]
    return []

def centroid(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]; return sum(xs) / len(xs), sum(ys) / len(ys)

def inside(pt, ring):
    x, y = pt; n = len(ring); j = n - 1; c = False
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi): c = not c
        j = i
    return c

def metres(lon1, lat1, lon2, lat2):
    k = math.cos(math.radians((lat1 + lat2) / 2)); return math.hypot((lon2 - lon1) * 111320 * k, (lat2 - lat1) * 110540)

def build(slug):
    d = os.path.join(CE, slug); gj = os.path.join(d, "buildings.geojson")
    if not os.path.exists(gj): return None
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    ctx = json.load(open(os.path.join(d, "ctx.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "ctx.json")) else {}
    bind = {}
    bj = os.path.join(d, "bindings.json")
    if os.path.exists(bj):
        bl = json.load(open(bj, encoding="utf-8")).get("bindings", {})
        if isinstance(bl, dict):                       # bind_buildings.py: { "<feature index>": {project, tx, score, dist_m} }
            bind = {str(k): v for k, v in bl.items()}
        else:
            for b in bl:
                if b.get("osm_id") is not None: bind[str(b["osm_id"])] = b
    blds = []
    for i, f in enumerate(feats):
        p = f["properties"]; rs = rings(f["geometry"])
        if not rs: continue
        ring = max(rs, key=len); cx, cy = centroid(ring)
        blds.append({"i": i, "id": str(p.get("osm_id") or p.get("id") or i), "name": (p.get("name") or "").strip() or None, "src": "osm" if p.get("name") else None,
                     "lon": cx, "lat": cy, "ring": ring, "h": float(p.get("bHeight") or 0), "levels": p.get("levels") or None, "status": p.get("status")})
    # wikidata -> footprint (inside, else nearest <= 40 m)
    lon0 = sum(b["lon"] for b in blds) / len(blds); lat0 = sum(b["lat"] for b in blds) / len(blds)
    near_w = [w for w in WIKI if metres(lon0, lat0, w["lon"], w["lat"]) < 6000]
    for w in near_w:
        hit = next((b for b in blds if inside((w["lon"], w["lat"]), b["ring"])), None)
        if not hit:
            cand = min(blds, key=lambda b: metres(w["lon"], w["lat"], b["lon"], b["lat"]))
            if metres(w["lon"], w["lat"], cand["lon"], cand["lat"]) <= 40: hit = cand
        if hit and not hit["name"]:
            hit["name"], hit["src"] = w["name"], "wikidata"
        if hit and w.get("height_m") and w["height_m"] > hit["h"]: hit["h"] = w["height_m"]   # true height beats the 3.2 m/level estimate
    # DLD project bindings (Business Bay so far)
    for b in blds:
        bb = bind.get(b["id"]) or bind.get(str(b["i"]))
        if bb and not b["name"]: b["name"], b["src"] = bb.get("project") or bb.get("name"), "dld"
    # scene coordinates: same convention as the GLB (glb_center from ctx.json, y-up, z = -northing)
    gc = ctx.get("glb_center")
    for b in blds:
        if gc and len(gc) >= 2:
            k = math.cos(math.radians(b["lat"])); b["x"] = round((b["lon"] - gc[0]) * 111320 * k, 1); b["z"] = round(-(b["lat"] - gc[1]) * 110540, 1)
    named = [b for b in blds if b["name"]]
    hs = sorted(b["h"] for b in blds); tall_cut = hs[int(len(hs) * 0.7)] if hs else 0
    tall = [b for b in blds if b["h"] >= tall_cut and b["h"] > 12]; tall_named = [b for b in tall if b["name"]]
    anchors = [{"id": b["id"], "name": b["name"], "source": b["src"], "lon": round(b["lon"], 6), "lat": round(b["lat"], 6), "x": b.get("x"), "z": b.get("z"), "h": round(b["h"], 1), "levels": b["levels"]} for b in named]
    anchors.sort(key=lambda a: -a["h"])
    json.dump({"district": slug, "buildings": len(blds), "named": len(named), "tall": len(tall), "tall_named": len(tall_named), "tall_cut_m": round(tall_cut, 1),
               "sources": {s: sum(1 for a in anchors if a["source"] == s) for s in ("osm", "wikidata", "dld", "portfolio")}, "anchors": anchors},
              open(os.path.join(OUT, f"anchors_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return len(blds), len(named), len(tall), len(tall_named), [a["name"] for a in anchors[:4]]

if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(os.path.join(CE, "*")) if os.path.isdir(p) and not p.endswith("_glb"))
    print(f"{'district':<26} {'bldgs':>6} {'named':>6} {'tall':>5} {'tall named':>10}  tallest named")
    T = [0, 0, 0, 0]
    for s in slugs:
        r = build(s)
        if not r: continue
        T = [T[i] + r[i] for i in range(4)]
        print(f"{s:<26} {r[0]:>6} {r[1]:>6} {r[2]:>5} {r[3]:>5} {100*r[3]/max(1,r[2]):>3.0f}%  {', '.join(r[4])[:60]}")
    print(f"{'TOTAL':<26} {T[0]:>6} {T[1]:>6} {T[2]:>5} {T[3]:>5} {100*T[3]/max(1,T[2]):>3.0f}%")
