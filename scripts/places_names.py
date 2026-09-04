"""Name the buildings that matter and still have no name: Google Places Nearby Search on each unnamed footprint above a height floor.

The open survey record (OpenStreetMap, Overture, Wikidata) is exhausted for the modelled districts - every name it holds is already
on the twin. What remains unnamed above 12 m is a few hundred real buildings; a place lookup on the footprint centroid resolves most
of them. Villas and bare 12 m default footprints are NOT sent here: a villa's "name" is a plot number, and that comes from the
municipality's registers, not from a place search.

Gate on the answer: the place must sit inside the footprint or within NEAR_M of its edge, and its types must say building-like
(premise, establishment, point_of_interest, lodging, apartment/real-estate style) - never a shop, ATM or bus stop that happens to be
at the base of a tower. Every accepted name records the place id, distance and types, so it can be audited and undone.

Output data/names/places_<slug>.json { "<feature index>": {"name", "place_id", "types", "dist_m", "inside", "source": "places"} }.
build_anchors.py merges these after Overture (name fills a footprint that is still unnamed; source "places").
Cost: Nearby Search (New) is billed per call - this script prints the count before it spends, and caches every answer in
data/names/places_cache.json so a re-run is free. Needs GOOGLE_KEY (listener .env or environment).
Usage: python scripts/places_names.py [--min-h 12.1] [--dry] [--radius 35] [slug ...]
"""
import argparse, glob, json, math, os, sys, time, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "names")
CACHE = os.path.join(OUT, "places_cache.json")
GOOD = {"premise", "subpremise", "establishment", "point_of_interest", "lodging", "hotel", "apartment_building", "apartment_complex",
        "condominium_complex", "housing_complex", "real_estate_agency", "office_building", "corporate_office", "shopping_mall", "hospital",
        "school", "university", "mosque", "place_of_worship", "government_office", "embassy", "bank", "tourist_attraction"}
BAD = {"bus_stop", "transit_station", "atm", "parking", "gas_station", "car_wash", "route", "street_address", "plus_code",
       "neighborhood", "sublocality", "locality", "political", "natural_feature", "park"}
NEAR_M = 30.0


def metres(lon1, lat1, lon2, lat2):
    r = 6371000.0; p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def inside(pt, ring):
    x, y = pt; ins = False; n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]; x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1: ins = not ins
    return ins


def ring_of(geom):
    if geom["type"] == "Polygon": return geom["coordinates"][0]
    if geom["type"] == "MultiPolygon": return max((p[0] for p in geom["coordinates"]), key=len)
    return []


def nearby(key, lon, lat, radius):
    body = json.dumps({"locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(radius)}},
                       "maxResultCount": 5, "rankPreference": "DISTANCE", "languageCode": "en"}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchNearby", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                                          "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.types,places.primaryType"})
    j = json.load(urllib.request.urlopen(req, timeout=30))
    return j.get("places") or []


def run(slug, key, min_h, radius, dry, cache):
    gj = os.path.join(CE, slug, "buildings.geojson"); anc = os.path.join(OUT, f"anchors_{slug}.json")
    if not (os.path.exists(gj) and os.path.exists(anc)): return None
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    named = {a["i"] for a in json.load(open(anc, encoding="utf-8"))["anchors"] if a.get("name")}
    # heights come from the model's own report (bldgfacts), not the raw footprint file - that is where the survey heights landed
    bfp = os.path.join(ROOT, "data", "board", f"bldgfacts_{slug}.json")
    H = {int(k): (v.get("height_m") or 0) for k, v in json.load(open(bfp, encoding="utf-8"))["buildings_by_id"].items()} if os.path.exists(bfp) else {}
    todo = [(i, f) for i, f in enumerate(feats) if i not in named and float(H.get(i, f["properties"].get("bHeight") or 0)) >= min_h]
    outp = os.path.join(OUT, f"places_{slug}.json")
    res = json.load(open(outp, encoding="utf-8")) if os.path.exists(outp) else {}
    print(f"{slug:<26} unnamed >= {min_h} m: {len(todo):>4}" + ("  (dry run - no calls)" if dry else ""))
    if dry: return len(todo), 0
    hits = 0
    for i, f in todo:
        if str(i) in res: hits += bool(res[str(i)].get("name")); continue
        ring = ring_of(f["geometry"])
        if not ring: continue
        lon = sum(p[0] for p in ring) / len(ring); lat = sum(p[1] for p in ring) / len(ring)
        ck = f"{lon:.6f},{lat:.6f},{radius}"
        if ck not in cache:
            try: cache[ck] = nearby(key, lon, lat, radius)
            except Exception as e: print("   places err", slug, i, str(e)[:80]); cache[ck] = []
            time.sleep(0.12)
        best = None
        for pl in cache[ck]:
            types = set(pl.get("types") or []); pt = (pl["location"]["longitude"], pl["location"]["latitude"])
            if types & BAD and not (types & {"premise", "lodging", "apartment_building", "apartment_complex", "condominium_complex", "office_building"}): continue
            if not (types & GOOD): continue
            d = 0.0 if inside(pt, ring) else min(metres(pt[0], pt[1], q[0], q[1]) for q in ring)
            if d > NEAR_M: continue
            nm = ((pl.get("displayName") or {}).get("text") or "").strip()
            if not nm or len(nm) < 3: continue
            cand = {"name": nm, "place_id": pl.get("id"), "types": sorted(types)[:6], "dist_m": round(d, 1), "inside": d == 0.0,
                    "primary": pl.get("primaryType"), "source": "places"}
            if best is None or d < best["dist_m"]: best = cand
        res[str(i)] = best or {"name": None, "checked": True}
        hits += bool(best)
    json.dump(res, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return len(todo), hits


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--min-h", type=float, default=12.1); ap.add_argument("--radius", type=float, default=35.0)
    ap.add_argument("--dry", action="store_true"); ap.add_argument("slugs", nargs="*"); a = ap.parse_args()
    key = os.environ.get("GOOGLE_KEY") or env_token("GOOGLE_KEY")
    if not key and not a.dry: sys.exit("GOOGLE_KEY not set")
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    slugs = a.slugs or [os.path.basename(p)[10:-5] for p in sorted(glob.glob(os.path.join(ROOT, "data", "board", "bldgfacts_*.json")))]
    T = H = 0
    for s in slugs:
        r = run(s, key, a.min_h, a.radius, a.dry, cache)
        if r: T += r[0]; H += r[1]
    json.dump(cache, open(CACHE, "w", encoding="utf-8"))
    print(f"TOTAL unnamed >= {a.min_h} m: {T} | named by Places: {H}")
