"""Beaches with ACCESS - public, hotel, residents, unknown - because "near a beach" means nothing to a buyer until you say whose beach.
(Kendall, 8 Sep 2026: "I want a house near a beach, but we need to be careful if it is public or private, that is a big difference.")

What exists officially: nothing machine-readable. Dubai Statistics Centre publishes no beach register. Dubai Municipality's open dataset
463074 "Dubai Parks and Beaches X and Y Coordinates" is 157 facility points (kiosks, umbrella rentals, volleyball courts) inside its parks -
useful for Jumeirah Beach Park, not a list of beaches. DM's own "Discover Dubai" page names only Jumeira Beach and Al Mamzar as its service
centres. So the register is built here, with provenance on every row:

  geometry  Overture Maps `land` theme, class=beach (= OpenStreetMap natural=beach): 206 polygons in the Dubai bbox, 151 of them >= 0.3 ha
  names     the polygon's own name (English variant where OSM has one), else the nearest Overture `beach` place within 150 m
  access    public    named on Dubai Municipality / Visit Dubai public-beach lists (Jumeirah Open, Kite, Sunset/Umm Suqeim, Mercato, La Mer,
                      JBR / Marina Beach, Jumeirah Public Beach, Al Sufouh, Al Mamzar, Pearl Jumeirah, Jebel Ali Open, Palm West Beach,
                      Deira Islands / Dubai Islands, Lagoons Beach, Al Mamzar Sea Island, Beyond the Beach (JBR))
            hotel     a hotel / resort / beach-club place within 120 m of the sand, or a hotel or club in the name
            residents inside a gated frond or island community (Palm Jumeirah fronds, Jumeirah Bay, Bluewaters residences) with no public name
            unknown   everything else (mostly Sharjah / Ajman sand inside the bbox, Palm Jebel Ali, Jebel Ali industrial coast)
Output: data/board/beaches.json {"items": [{n, acc, area_ha, lon, lat, src, why}]}, a summary printed. Usage: python scripts/beaches_register.py
"""
import glob, json, math, os, re, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from shapely.geometry import shape, Polygon, Point
from shapely.ops import transform
import pyproj
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(ROOT, "data", "names", "overture_raw"); OUT = os.path.join(ROOT, "data", "board", "beaches.json")
to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
PUBLIC = ["jumeirah open beach", "jumeira open beach", "jumeirah beach", "jumeira beach", "jumeirah 2 open beach", "jumeirah 3 open beach", "kite beach", "sunset beach", "umm suqeim",
          "mercato beach", "la mer", "jbr", "the beach", "marina beach", "jumeirah public beach", "al sufouh", "sufouh beach", "al mamzar", "mamzar", "pearl jumeirah",
          "jebel ali open", "jebel ali public", "palm west beach", "west beach", "deira islands beach", "dubai islands beach", "lagoons beach", "beyond the beach", "jumeirah beach park", "nessnass", "al mamzar sea island"]
NOT_PUBLIC = ["black palace"]   # closed to the public in 2025 - privately owned (Dubai Media Office)
HOTEL_WORDS = ["hotel", "resort", "club", "private", "nikki", "mandarin", "one&only", "one & only", "atlantis", "ritz", "sofitel", "waldorf", "fairmont", "bulgari", "bvlgari", "jumeirah al", "anantara", "marriott", "hilton", "sheraton", "westin", "kempinski", "rixos", "aloft", "cove beach", "fluid", "drift", "twiggy", "azure", "zero gravity", "barasti", "meydan beach", "summersalt", "aquaventure", "nasimi", "white beach", "wavehouse", "atlantis"]
PALM = Polygon([(55.105, 25.095), (55.160, 25.095), (55.165, 25.140), (55.100, 25.140)])                  # Palm Jumeirah incl. crescent
PALM_PUBLIC_STRIP = Polygon([(55.134, 25.098), (55.146, 25.098), (55.146, 25.118), (55.134, 25.118)])   # West Beach / Club Vista Mare / The Pointe side of the trunk
BLUEWATERS = Polygon([(55.115, 25.076), (55.128, 25.076), (55.128, 25.086), (55.115, 25.086)])
JUMEIRAH_BAY = Polygon([(55.235, 25.218), (55.252, 25.218), (55.252, 25.236), (55.235, 25.236)])


def en(names):
    n = names or {}
    for lang, val in (n.get("common") or []):
        if lang == "en" and val: return val
    return n.get("primary")


def main():
    land = json.load(open(os.path.join(RAW, "dubai_land.geojson"), encoding="utf-8"))["features"]
    polys = [f for f in land if f["properties"].get("class") == "beach" and f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    places = []
    for f in glob.glob(os.path.join(RAW, "*_place.geojson")):
        for ft in json.load(open(f, encoding="utf-8"))["features"]:
            c = (ft["properties"].get("categories") or {}).get("primary") or ""; n = en(ft["properties"].get("names")) or ""
            if any(k in c for k in ("hotel", "resort", "beach")) or "beach" in n.lower(): places.append((n, c, ft["geometry"]["coordinates"]))
    def dm(a, b): return math.hypot((a[0] - b[0]) * 111320 * math.cos(a[1] * math.pi / 180), (a[1] - b[1]) * 111320)
    items = []; seen = set()
    for f in polys:
        g = shape(f["geometry"]); rp = g.representative_point(); c = (rp.x, rp.y); area = transform(to_utm, g).area / 10000
        if area < 0.3: continue
        name = en(f["properties"].get("names")); why = "osm name" if name else ""
        near = sorted(((dm(c, xy), n, cat) for n, cat, xy in places if dm(c, xy) <= 250), key=lambda x: x[0])
        if not name:
            bn = [x for x in near if "beach" in x[1].lower() and x[0] <= 150 and not any(w in x[1].lower() for w in ("hotel", "resort", "residence", "residences", "tower", "apartment", "villa"))]
            if bn: name = bn[0][1]; why = f"named by the beach place {bn[0][0]:.0f} m away"
        L = (name or "").lower(); hotels = [x for x in near if x[0] <= 120 and any(k in x[2] for k in ("hotel", "resort")) and not any(w in x[1].lower() for w in ("villa", "apartment", "residence"))]
        if any(k in L for k in NOT_PUBLIC): acc, why2 = "hotel", "closed to the public 2025, privately owned"
        elif any(k in L for k in PUBLIC): acc, why2 = "public", "on the public-beach lists (Dubai Municipality / Visit Dubai)"
        elif hotels or any(k in L for k in HOTEL_WORDS): acc, why2 = "hotel", ("hotel within 120 m: " + hotels[0][1]) if hotels else "hotel / club in the name"
        elif PALM.contains(rp) and not PALM_PUBLIC_STRIP.contains(rp): acc, why2 = "residents", "Palm Jumeirah frond or crescent frontage"
        elif BLUEWATERS.contains(rp) or JUMEIRAH_BAY.contains(rp): acc, why2 = "residents", "island community frontage"
        else: acc, why2 = "unknown", "no name, no hotel, not a listed public beach"
        key = (round(c[0], 4), round(c[1], 4))
        if key in seen: continue
        seen.add(key)
        items.append({"n": name or ("beach" + (" (unnamed)")), "acc": acc, "area_ha": round(area, 2), "lon": round(c[0], 5), "lat": round(c[1], 5), "src": "overture_land/osm", "why": (why + "; " if why else "") + why2})
    for f in land:
        if f["properties"].get("class") == "beach" and f["geometry"]["type"] == "Point":
            nm = en(f["properties"].get("names")) or ""; xy = f["geometry"]["coordinates"]
            if nm and any(k in nm.lower() for k in PUBLIC):
                close = [i for i in items if dm(xy, (i["lon"], i["lat"])) <= 400]
                if close:
                    for i in close:
                        if i["acc"] == "unknown": i["n"] = nm; i["acc"] = "public"; i["why"] = f"unnamed sand named by the public-beach point {nm!r} within 400 m"
                else:
                    items.append({"n": nm, "acc": "public", "area_ha": None, "lon": round(xy[0], 5), "lat": round(xy[1], 5), "src": "overture_land/osm (point)", "why": "osm name; on the public-beach lists"})
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "source": "Overture Maps land (class beach) = OpenStreetMap natural=beach; access classified by name lists, adjacent hotels, and community polygons; no official register exists (DM 463074 is facility points; DSC publishes none)",
           "counts": {a: sum(1 for i in items if i["acc"] == a) for a in ("public", "hotel", "residents", "unknown")}, "items": items}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("beaches:", doc["counts"], "->", OUT)
    for a in ("public", "hotel", "residents"):
        print(f"\n{a.upper()}:"); [print(f"  {i['area_ha']:6.1f} ha  {i['n'][:40]:40s} @ {i['lon']},{i['lat']}   {i['why'][:70]}") for i in sorted([i for i in items if i["acc"] == a], key=lambda i: -i["area_ha"])[:25]]


if __name__ == "__main__":
    main()
