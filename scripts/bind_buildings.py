"""Geocode-bind pass: register projects -> OSM footprints, confidence-gated.

For a district: every distinct PROJECT_EN with transactions is geocoded ONCE
(cache: data/geocode_cache.json — never re-paid), then matched to the OSM
footprint it lands on. Ghaf Woods rule enforced in code: a binding requires
geocoder score >= 85 AND (point inside footprint OR centroid <= 60 m).
Everything else stays unbound — no guessed joins, ever.

Usage: READ_KEY=... python scripts/bind_buildings.py --area "business bay"
Out:   data/ce/<slug>/bindings.json + bind-rate report
"""
import json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CE = os.path.join(HERE, "..", "data", "ce")
CACHE = os.path.join(HERE, "..", "data", "geocode_cache.json")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"
slug = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())


def token():
    key = os.environ["READ_KEY"]
    req = urllib.request.Request(f"{WORKER}/esri_token?key={key}", headers={"User-Agent": "najma-bind/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))["token"]


def geocode(tok, q):
    p = urllib.parse.urlencode({"f": "json", "token": tok, "langCode": "en", "singleLine": q,
                                "maxLocations": "1", "outFields": "Score"})
    req = urllib.request.Request(
        "https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + p,
        headers={"Referer": WORKER, "User-Agent": "najma-bind/1.0"})
    j = json.load(urllib.request.urlopen(req, timeout=30))
    c = (j.get("candidates") or [None])[0]
    if not c: return None
    return {"lon": c["location"]["x"], "lat": c["location"]["y"], "score": c.get("score", 0),
            "address": c.get("address", "")}


def main():
    from shapely.geometry import shape, Point
    import duckdb, pyproj
    area = sys.argv[sys.argv.index("--area") + 1]
    sl = sys.argv[sys.argv.index("--slug") + 1] if "--slug" in sys.argv else slug(area)   # folder slug when it differs from the DLD area name (Marsa Dubai -> dubaimarina)
    gj = json.load(open(os.path.join(CE, sl, "buildings.geojson")))
    feats = gj["features"]
    polys = [shape(f["geometry"]) for f in feats]
    to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
    cents = [p.centroid for p in polys]

    con = duckdb.connect(os.path.join(HERE, "..", "naj.duckdb"), read_only=True)
    projects = con.execute(
        "SELECT PROJECT_EN, COUNT(*) c FROM transactions WHERE upper(AREA_EN)=upper(?) "
        "AND PROJECT_EN IS NOT NULL AND PROJECT_EN<>'' GROUP BY 1 ORDER BY c DESC", [area]).fetchall()
    print(f"{area}: {len(projects)} distinct register projects, {len(feats)} footprints")

    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    tok = token()
    bound, low, far, none = {}, [], [], []
    for name, txc in projects:
        ck = sl + "::" + name
        if ck not in cache:
            try:
                cache[ck] = geocode(tok, f"{name}, {area}, Dubai, United Arab Emirates")
            except Exception as e:
                print("  geocode err", name[:30], str(e)[:40]); cache[ck] = None
            time.sleep(0.35)
        g = cache[ck]
        if not g: none.append(name); continue
        if g["score"] < 85: low.append((name, g["score"])); continue
        pt = Point(g["lon"], g["lat"])
        # inside a footprint?
        idx = next((i for i, p in enumerate(polys) if p.contains(pt)), None)
        dist = 0.0
        if idx is None:
            ux, uy = to_utm(pt.x, pt.y)
            best, bd = None, 1e9
            for i, c in enumerate(cents):
                cx, cy = to_utm(c.x, c.y)
                d = ((ux - cx) ** 2 + (uy - cy) ** 2) ** 0.5
                if d < bd: bd, best = d, i
            if bd <= 60: idx, dist = best, round(bd, 1)
            else: far.append((name, round(bd, 1))); continue
        # one project per footprint: keep the higher-tx binding
        if idx in bound and bound[idx]["tx"] >= txc: continue
        bound[idx] = {"project": name, "tx": txc, "score": g["score"], "dist_m": dist}
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    out = {"district": sl, "bindings": {str(k): v for k, v in bound.items()}}
    json.dump(out, open(os.path.join(CE, sl, "bindings.json"), "w"), ensure_ascii=False, indent=1)
    print(f"BOUND: {len(bound)} footprints <- projects")
    print(f"unbound: low-score {len(low)} · too-far {len(far)} · no-candidate {len(none)}")
    for n, s in low[:5]: print(f"  low  {n[:40]} ({s:.0f})")
    for n, d in far[:5]: print(f"  far  {n[:40]} ({d}m)")
    tx_bound = sum(v["tx"] for v in bound.values()); tx_all = sum(c for _, c in projects)
    print(f"transaction coverage: {tx_bound}/{tx_all} = {100*tx_bound//max(1,tx_all)}%")


if __name__ == "__main__":
    main()
