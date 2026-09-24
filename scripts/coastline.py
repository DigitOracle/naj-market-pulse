"""The waterline of Dubai - every body of water a resident would name, as short segments the map can measure against.

Why: "Chelsea by Damac is literally on the coast so it's weird that it says there is not beach" (Najjuko, 8 Sep 2026). A public beach is
a register fact; being on the water is a geometry fact. This gives the app the second one, with the water body NAMED.

Source: Overture Maps `water` theme for the Dubai bbox (data/names/overture_raw/dubai_water.geojson, overturemaps CLI). Overture's water
is OpenStreetMap (every feature here carries sources=OpenStreetMap). 3,550 features, of which 2,286 are swimming pools and 181 carry a name.

What is kept (v2, 8 Sep 2026):
  - sea    ocean / sea / bay polygons (the Gulf; Overture also draws the Creek, the Canal and the Marina as ocean - see corridors)
  - creek  Dubai Creek (Overture class canal, primary name خور دبي, en 'Dubai Creek') + ocean water inside the Creek corridor
  - canal  Dubai Water Canal (قناة دبي, en 'Dubai Canal') + Business Bay's canal loop + any other canal polygon
  - marina Dubai Marina (Overture class water, en 'Dubai Marina') + ocean water inside the Marina basin
  - lake   lakes / lagoons / plain water / reservoirs / ponds >= 2 ha that are not pools, wastewater, drains or storm basins
Each segment points at a BODY: {id, name (English where Overture has one, else the Arabic primary, else '<class> in <district>'), cls,
overture_class, area_ha, centroid, district}. Output data/board/coast.json {"bodies": [...], "segments": [[lon1,lat1,lon2,lat2,cls,bodyIdx], ...]}
and data/board/water_register.json (the bodies alone, for the audit and the knowledge graph). Pushed to KV `coast`.
Usage: python scripts/coastline.py [--no-push]
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, push  # noqa: E402
from shapely.geometry import shape, box, Polygon, Point  # noqa: E402
from shapely.ops import transform, unary_union  # noqa: E402
import pyproj  # noqa: E402
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(ROOT, "data", "names", "overture_raw", "dubai_water.geojson"); BOARD = os.path.join(ROOT, "data", "board")
OUT = os.path.join(BOARD, "coast.json"); REG = os.path.join(BOARD, "water_register.json")
BBOX = box(54.85, 24.75, 55.70, 25.42)
to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
to_ll = pyproj.Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform
DROP = {"swimming_pool", "reflecting_pool", "wastewater", "drain", "ditch", "basin"}
# corridors: where Overture's ocean polygon is, to a resident, the Creek, the Canal or the Marina
CORR = {"creek": Polygon([(55.280, 25.278), (55.300, 25.286), (55.345, 25.240), (55.365, 25.210), (55.350, 25.160), (55.318, 25.165), (55.318, 25.215), (55.300, 25.245), (55.282, 25.262)]),
        "canal": Polygon([(55.236, 25.200), (55.248, 25.214), (55.302, 25.202), (55.322, 25.186), (55.314, 25.164), (55.270, 25.174), (55.244, 25.188)]),
        "marina": Polygon([(55.126, 25.094), (55.150, 25.096), (55.156, 25.072), (55.132, 25.066)])}
CORR_NAME = {"creek": "Dubai Creek", "canal": "Dubai Canal", "marina": "Dubai Marina"}
# Overture names the Burj Khalifa lake a drain and the District One lagoon a pond - keep these by name whatever the class
KEEP_BY_NAME = {"Burj Khalifa Lake", "Crystal Lagoon", "Cristal Lagoon (future location)", "Jumeirah Fishing Harbour", "Mall of the Emirates Basin"}


def en_name(p):
    n = p.get("names") or {}
    for lang, val in (n.get("common") or []):
        if lang == "en" and val: return val
    return n.get("primary")


def main():
    D = json.load(open(os.path.join(BOARD, "districts_geo.json"), encoding="utf-8"))["districts"]
    def district_of(x, y):
        for d in D:
            b = d["bbox"]
            if b[0] - 0.005 <= x <= b[2] + 0.005 and b[1] - 0.005 <= y <= b[3] + 0.005: return d["name"]
        return None
    g = json.load(open(RAW, encoding="utf-8")); polys = []                         # (cls, name, overture_class, geom_ll, area_ha)
    for f in g["features"]:
        if f["geometry"]["type"] not in ("Polygon", "MultiPolygon"): continue
        p = f["properties"]; st, cl = p.get("subtype"), p.get("class"); nm = en_name(p)
        try: geom = shape(f["geometry"]).intersection(BBOX)
        except Exception: continue
        if geom.is_empty: continue
        area = transform(to_utm, geom).area / 10000.0
        if cl in DROP and nm not in KEEP_BY_NAME: continue
        if st == "ocean" or (cl in ("ocean", "sea", "bay", "strait") and area > 100000): cls = "sea"
        elif nm in ("Burj Khalifa Lake", "Crystal Lagoon", "Cristal Lagoon (future location)", "Mall of the Emirates Basin"): cls = "lake"
        elif nm == "Jumeirah Fishing Harbour" or (cl == "bay" and area <= 100000): cls = "harbour"
        elif nm == "Dubai Creek": cls = "creek"
        elif nm == "Dubai Canal" or st == "canal" or cl == "canal": cls = "canal"
        elif nm == "Dubai Marina": cls = "marina"
        elif area >= 2 or nm in KEEP_BY_NAME: cls = "lake"
        else: continue
        polys.append((cls, nm, f"{st}/{cl}", geom, area))
    bodies = []; segs = []
    def add_body(cls, name, ocls, geom_ll, area):
        rp = geom_ll.representative_point(); dist = district_of(rp.x, rp.y)
        bid = len(bodies)
        label = name or ((cls if cls != "lake" else "lake") + (f" in {dist}" if dist else (" in Sharjah" if rp.x > 55.35 and rp.y > 25.30 else "")))
        bodies.append({"id": bid, "name": label, "named": bool(name), "cls": cls, "overture_class": ocls, "area_ha": round(area, 1), "centroid": [round(rp.x, 5), round(rp.y, 5)], "district": dist})
        u = transform(to_utm, geom_ll).simplify(12.0); lines = u.boundary
        for ln in (lines.geoms if hasattr(lines, "geoms") else [lines]):
            cs = [to_ll(x, y) for x, y in ln.coords]
            for a, b in zip(cs, cs[1:]):
                c2 = cls
                if cls == "sea":
                    mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    for k, poly in CORR.items():
                        if poly.contains(mid): c2 = k; break
                segs.append([round(a[0], 6), round(a[1], 6), round(b[0], 6), round(b[1], 6), c2, bid])
    sea = [pg for pg in polys if pg[0] == "sea"]
    if sea: add_body("sea", "Arabian Gulf", "ocean/ocean", unary_union([s[3] for s in sea]), sum(s[4] for s in sea))
    for cls in ("creek", "canal", "marina"):
        group = [pg for pg in polys if pg[0] == cls]
        if not group: continue
        named = [pg for pg in group if pg[1] == CORR_NAME[cls]]; rest = [pg for pg in group if pg[1] != CORR_NAME[cls]]
        if named: add_body(cls, CORR_NAME[cls], named[0][2], unary_union([pg[3] for pg in named]), sum(pg[4] for pg in named))
        for pg in rest: add_body(cls, pg[1], pg[2], pg[3], pg[4])
    for pg in polys:
        if pg[0] == "lake": add_body("lake", pg[1], pg[2], pg[3], pg[4])
    # a sea segment inside a corridor belongs to that corridor's named body
    by_cls = {b["cls"]: b["id"] for b in bodies if b["named"] and b["name"] in CORR_NAME.values()}
    for s in segs:
        if s[4] in by_cls and bodies[s[5]]["cls"] == "sea": s[5] = by_cls[s[4]]
    stats = {}
    for s in segs: stats[s[4]] = stats.get(s[4], 0) + 1
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "source": "Overture Maps water theme (= OpenStreetMap), Dubai bbox 54.85-55.70 E 24.75-25.42 N, boundaries simplified 12 m",
           "classes": stats, "bodies": bodies, "segments": segs}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    json.dump({"generated": doc["generated"], "source": doc["source"], "count": len(bodies), "named": sum(1 for b in bodies if b["named"]), "bodies": bodies},
              open(REG, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"bodies {len(bodies)} (named {sum(1 for b in bodies if b['named'])}) · segments {stats} · {os.path.getsize(OUT) // 1024} KB")
    if "--push" in sys.argv and "--no-push" not in sys.argv: print("coast ->", push("coast", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
