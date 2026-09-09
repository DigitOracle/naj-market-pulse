"""Parks with ACCESS - public park, community park (inside a residential estate), garden/playground - from Overture land use.
(Kendall, 8 Sep 2026: "we should also be auditing against the parks as well".)

What exists officially: Dubai Municipality's open dataset 463074 covers three parks' facilities (Creek, Al Safa, Jumeirah Beach Park);
there is no machine-readable list of the Municipality's ~200 parks. Wikipedia's "List of parks in Dubai" names the major ones. So, as
with beaches, the register is built from OpenStreetMap (via Overture Maps `land_use`) with provenance on every row:

  geometry  Overture land_use class in (park, garden, playground, dog_park, nature_reserve, recreation_ground): 4,317 polygons in the
            Dubai bbox, 271 named. Kept: park >= 0.5 ha (named or not), garden/playground/dog_park >= 0.5 ha only when named,
            nature_reserve any size.
  access    public     a named park not inside a residential estate polygon, or on the Municipality/Wikipedia major-park list
            community  a park whose representative point lies inside an Overture `residential` land-use polygon (an estate's own park:
                       Arabian Ranches, Springs, JVC pocket parks) - real, but for residents
            unknown    unnamed and not inside a residential polygon
Output: data/board/parks.json {"items": [{n, acc, kind, area_ha, lon, lat, src, why}]}. Usage: python scripts/parks_register.py
"""
import json, math, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from shapely.geometry import shape
from shapely.ops import transform
from shapely.strtree import STRtree
import pyproj
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(ROOT, "data", "names", "overture_raw", "dubai_land_use.geojson"); OUT = os.path.join(ROOT, "data", "board", "parks.json")
to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
MAJOR = ["zabeel park", "safa park", "al safa park", "creek park", "mushrif", "al mamzar", "jumeirah beach park", "al barsha pond park", "al barsha park", "quranic park", "al khazzan park",
         "burj park", "al qudra", "love lake", "dubai miracle garden", "al ittihad park", "al warqa", "mirdif", "uptown mirdif", "al nahda pond park", "al twar park", "al khawaneej",
         "hatta", "al mizhar", "satwa park", "gate avenue", "dubai water canal", "jlt park", "the greens", "kite beach", "umm suqeim park", "zabeel", "al barari", "dubai hills park",
         "expo city", "al jaddaf", "mohammed bin rashid", "dubai frame", "al garhoud", "al rashidiya park", "al quoz pond park", "nad al sheba", "al wasl", "dubai safari", "children's city"]


def en(names):
    n = names or {}
    for lang, val in (n.get("common") or []):
        if lang == "en" and val: return val
    return n.get("primary")


def main():
    D = json.load(open(os.path.join(ROOT, "data", "board", "districts_geo.json"), encoding="utf-8"))["districts"]
    def district_of(x, y):
        for d in D:
            b = d["bbox"]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]: return d["slug"]
        return None
    feats = json.load(open(RAW, encoding="utf-8"))["features"]
    res = [shape(f["geometry"]) for f in feats if f["properties"].get("class") == "residential" and f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    tree = STRtree(res)
    items = []; seen = set()
    for f in feats:
        cl = f["properties"].get("class")
        if cl not in ("park", "garden", "playground", "dog_park", "nature_reserve", "recreation_ground") or f["geometry"]["type"] not in ("Polygon", "MultiPolygon"): continue
        g = shape(f["geometry"]); nm = en(f["properties"].get("names")); area = transform(to_utm, g).area / 10000
        if cl == "park" and area < 0.5: continue
        if cl in ("garden", "playground", "dog_park", "recreation_ground") and (area < 0.5 or not nm): continue
        rp = g.representative_point(); key = (round(rp.x, 4), round(rp.y, 4))
        if key in seen: continue
        seen.add(key)
        inside = [i for i in tree.query(rp) if res[i].contains(rp)] if hasattr(tree, "query") else []
        L = (nm or "").lower()
        if any(w in L for w in ("library", "dewa", "staff", "school", "mosque", "hospital", "clinic", "office", "police", "metro", "station", "cemetery", "graveyard")): continue   # OSM polygons tagged park that are not parks
        if cl == "nature_reserve" or "reserve" in L or "sanctuary" in L or "protected area" in L or "conservation" in L: acc, why = "reserve", "nature reserve / sanctuary - not a neighbourhood park"
        elif "private" in L or "ladies" in L or "women" in L or "للسيدات" in L: acc, why = "community", "restricted by name (private / ladies-only)"
        elif nm and any(k in L for k in MAJOR): acc, why = "public", "major park (Municipality / Wikipedia list)"
        elif inside: acc, why = "community", "inside a residential estate polygon (residents' park)"
        elif nm: acc, why = "public", "named park outside any estate"
        else: acc, why = "unknown", "unnamed park outside any estate"
        items.append({"n": nm or ("park (unnamed)" if cl == "park" else cl), "acc": acc, "kind": cl, "area_ha": round(area, 2), "lon": round(rp.x, 5), "lat": round(rp.y, 5),
                      "d": district_of(rp.x, rp.y), "src": "overture_land_use/osm", "why": why})
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "source": "Overture Maps land_use (= OpenStreetMap leisure=park/garden/playground); access by name list and residential-estate containment; DM publishes facilities for 3 parks only",
           "counts": {a: sum(1 for i in items if i["acc"] == a) for a in ("public", "community", "reserve", "unknown")}, "named": sum(1 for i in items if not i["n"].startswith("park (") and i["n"] not in ("garden", "playground")), "items": items}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("parks:", doc["counts"], "named", doc["named"], "->", OUT)
    print("largest public:"); [print(f"  {i['area_ha']:7.1f} ha  {i['n'][:44]:44s} {i['d'] or ''}") for i in sorted([i for i in items if i["acc"] == "public"], key=lambda i: -i["area_ha"])[:20]]
    print("largest community:"); [print(f"  {i['area_ha']:7.1f} ha  {i['n'][:44]:44s} {i['d'] or ''}") for i in sorted([i for i in items if i["acc"] == "community"], key=lambda i: -i["area_ha"])[:10]]


if __name__ == "__main__":
    main()
