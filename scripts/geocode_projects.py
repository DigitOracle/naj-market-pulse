"""Put the register's project names on the twin: geocode every developer project we hold and bind it to a footprint.

Why. The eleven developers' projects (data/board/projfacts.json, 340 of them: name, developer, area, aliases, DLD hint) are the
buildings Najjuko actually sells, and most of them are still "unknown" on the twin because no survey tagged the tower. A Places
text search on "<project> <developer> Dubai" returns the building's point; if that point lands inside or within NEAR_M of a
modelled footprint taller than MIN_H in the project's own district, the project name becomes evidence for that footprint
(source "register", role PROJECT_NAME - the resolver decides whether it is also the building's name).

Gate, so a sales office or a showroom never names a tower: the place must be a building-like type, must sit in the district the
register says, and must be within NEAR_M of a footprint above MIN_H. Every binding records place id, distance and types; nothing
is deleted, nothing pinned is overridden.

Output: data/identity/register/geocoded_projects.json  { "<slug>": { "<feature index>": {name, developer, project_id, place_id,
        dist_m, inside, types, source: "register", role: "PROJECT_NAME"} } }   (+ misses listed for audit)
Usage:  python scripts/geocode_projects.py [--dry] [--limit N] [slug ...]
"""
import json, os, sys, time, urllib.request, math
from shapely.geometry import shape, Point
from shapely.strtree import STRtree
import pyproj

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "identity", "register"); os.makedirs(OUT, exist_ok=True)
CACHE = os.path.join(OUT, "geocode_cache.json")
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
NEAR_M = 45.0; MIN_H = 12.1
BUILDINGISH = {"premise", "establishment", "point_of_interest", "lodging", "apartment_building", "apartment_complex", "condominium_complex", "housing_complex", "real_estate_agency", "hotel", "resort_hotel", "building"}
NOT_BUILDING = {"store", "shopping_mall", "restaurant", "cafe", "bus_station", "transit_station", "atm", "bank", "school", "parking", "gas_station"}
AREA_TO_SLUG = {"dubai marina": "dubaimarina", "marsa dubai": "dubaimarina", "business bay": "businessbay", "burj khalifa": "burjkhalifa", "downtown dubai": "burjkhalifa", "downtown": "burjkhalifa",
    "palm jumeirah": "palmjumeirah", "al wasl": "alwasl", "jumeirah": "alwasl", "jumeirah village circle": "jumeirahvillagecircle", "jvc": "jumeirahvillagecircle", "jumeirah village triangle": "jumeirahvillagetriangle", "jvt": "jumeirahvillagetriangle",
    "motor city": "motorcity", "palm deira": "palmdeira", "dubai islands": "palmdeira", "al jaddaf": "samaaljadaf", "jaddaf": "samaaljadaf", "al jadaf": "samaaljadaf", "sobha hartland": "sobhaheartland", "mohammed bin rashid city": "sobhaheartland", "mbr city": "sobhaheartland", "nad al shiba first": "sobhaheartland",
    "la mer": "alwasl", "city walk": "alwasl", "umm suqeim": "alwasl", "jumeirah lake towers": "jltnorth", "jlt": "jltnorth", "al thanyah fifth": "jltnorth", "jumeirah islands": "jltsouth", "jumeirah park": "jltsouth"}


def area_slug(area):
    a = (area or "").strip().lower()
    for k in sorted(AREA_TO_SLUG, key=len, reverse=True):      # longest alias first: "jumeirah village circle" before "jumeirah"
        if k in a: return AREA_TO_SLUG[k]
    return None


def places_text(q, key):
    body = json.dumps({"textQuery": q, "regionCode": "AE", "languageCode": "en", "maxResultCount": 3}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchText", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.types,places.formattedAddress"})
    return json.load(urllib.request.urlopen(req, timeout=30)).get("places", [])


def main():
    dry = "--dry" in sys.argv; lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    want = [a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
    key = env_token("GOOGLE_KEY")
    P = json.load(open(os.path.join(ROOT, "data", "board", "projfacts.json"), encoding="utf-8")); P = P.get("projects") or P; P = list(P.values()) if isinstance(P, dict) else P
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    prev = json.load(open(os.path.join(OUT, "geocoded_projects.json"), encoding="utf-8")) if os.path.exists(os.path.join(OUT, "geocoded_projects.json")) else {}
    out = {k: v for k, v in prev.items() if not k.startswith("_")}; misses = []
    # footprints per district, in metres
    fp = {}
    def load(slug):
        if slug in fp: return fp[slug]
        p = os.path.join(CE, slug, "buildings.geojson")
        if not os.path.exists(p): fp[slug] = None; return None
        F = json.load(open(p, encoding="utf-8"))["features"]; polys, idx = [], []
        for i, f in enumerate(F):
            if float(f["properties"].get("bHeight") or 0) < MIN_H: continue
            g = shape(f["geometry"]); polys.append(g); idx.append(i)
        from shapely.ops import transform
        polys_m = [transform(TO_UTM, g) for g in polys]
        fp[slug] = (F, polys_m, idx, STRtree(polys_m) if polys_m else None); return fp[slug]
    n = 0
    for pr in P:
        name = (pr.get("name") or "").strip(); dev = (pr.get("developer") or pr.get("dev") or "").strip(); slug = area_slug(pr.get("area"))
        if not name or not slug or (want and slug not in want): continue
        n += 1
        if n > lim: break
        q = f"{name} {dev} Dubai".strip()
        if q in cache: res = cache[q]
        else:
            if dry: print("  would search:", q); continue
            try: res = places_text(q, key)
            except Exception as e: print("  search failed:", q, str(e)[:60]); continue
            cache[q] = res; time.sleep(0.15)
        data = load(slug)
        if not data or not data[3]: misses.append({"project": name, "developer": dev, "why": "no footprints in " + slug}); continue
        F, polys_m, idx, tree = data; hit = None
        for pl in res:
            types = set(pl.get("types") or [])
            if types & NOT_BUILDING and not (types & BUILDINGISH): continue
            loc = pl.get("location") or {}; pt = Point(TO_UTM(loc.get("longitude", 0), loc.get("latitude", 0)))
            j = tree.nearest(pt); d = polys_m[j].distance(pt)
            if d <= NEAR_M: hit = {"i": idx[j], "d": round(d, 1), "inside": d == 0.0, "place": pl}; break
        if not hit: misses.append({"project": name, "developer": dev, "slug": slug, "why": "no footprint above 12 m within 45 m of the place" if res else "no place found"}); continue
        pl = hit["place"]
        out.setdefault(slug, {})[str(hit["i"])] = {"name": name, "developer": dev, "project_id": pr.get("slug") or pr.get("dld"), "place_id": pl.get("id"), "place_name": (pl.get("displayName") or {}).get("text"),
                                                  "dist_m": hit["d"], "inside": hit["inside"], "types": (pl.get("types") or [])[:6], "source": "register", "role": "PROJECT_NAME", "method": "Places text search on the register's project name, bound to the nearest footprint above 12 m"}
        print(f"  {slug:<22} #{hit['i']:<5} {name[:34]:<34} {dev[:14]:<14} {hit['d']:>5.1f} m {'inside' if hit['inside'] else ''}")
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    if not dry:
        out["_misses"] = misses; out["_updated"] = time.strftime("%Y-%m-%d %H:%M")
        json.dump(out, open(os.path.join(OUT, "geocoded_projects.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    bound = sum(len(v) for k, v in out.items() if not k.startswith("_"))
    print(f"\nprojects considered {n} | bound to a footprint {bound} | misses {len(misses)} -> {OUT}")


if __name__ == "__main__":
    main()
