"""CityEngine export — step 1+2 of the Najma "future skyline" pipeline.

Per community: pulls OSM building footprints (Overpass), clips to the community's real
boundary polygon, tags real heights where OSM knows them, and exports the community's
REGISTERED pipeline (units / %-complete / completion) as attributes — plus a starter CGA
rule and import instructions for the CE instance already scripted on this machine.

Honest limitation, stated up front: the DLD projects file carries no plot coordinates, so
pipeline massings export as an attribute CSV for manual ghost placement in CE. Automatic
placement becomes possible once the geocoding privilege is added to the Esri credential
(geocode each project name once, cache forever — same pattern as amenities).

Usage:  python scripts/ce_export.py --area "business bay"
Output: data/ce/<slug>/{buildings.geojson, pipeline.csv, najma.cga, README_CE.md}
"""
import csv, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
CE = os.path.join(HERE, "..", "data", "ce")
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]

slug = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())


def fetch_buildings(bbox):
    q = f'[out:json][timeout:90];(way["building"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}););out geom;'
    for url in OVERPASS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers={"User-Agent": "najma-ce-export/1.0 (contact@digitalabbot.io)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)["elements"]
        except Exception as e:
            print(f"  overpass {url.split('//')[1].split('/')[0]}: {e} — trying mirror")
            time.sleep(3)
    sys.exit("Overpass unreachable on all mirrors")


def est_height(tags):
    if tags.get("height"):
        try:
            return round(float(re.sub(r"[^0-9.]", "", tags["height"])), 1)
        except ValueError:
            pass
    if tags.get("building:levels"):
        try:
            return round(float(tags["building:levels"]) * 3.2, 1)
        except ValueError:
            pass
    return 12.0                                            # sensible default podium


def main():
    if "--area" not in sys.argv:
        sys.exit('usage: python scripts/ce_export.py --area "business bay"')
    want = sys.argv[sys.argv.index("--area") + 1]
    areas = json.load(open(os.path.join(PUB, "mp_areas.json"), encoding="utf-8"))
    ft = next((f for f in areas["features"] if slug(f["properties"]["n"]) == slug(want)), None)
    if not ft:
        sys.exit(f'no boundary polygon for "{want}" — run make_area_polygons.py or pick a mapped community')
    name = ft["properties"]["n"]
    from shapely.geometry import shape, Point
    poly = shape(ft["geometry"])
    b = poly.bounds
    print(f"{name}: fetching OSM buildings in bbox {tuple(round(x,3) for x in b)} …")
    els = fetch_buildings(b)
    feats = []
    for e in els:
        if e.get("type") != "way" or not e.get("geometry"):
            continue
        ring = [[p["lon"], p["lat"]] for p in e["geometry"]]
        if len(ring) < 4:
            continue
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        if not poly.contains(Point(cx, cy)):
            continue
        tags = e.get("tags", {})
        feats.append({"type": "Feature",
                      "properties": {"status": "existing", "bHeight": est_height(tags),
                                     "name": tags.get("name", ""), "levels": tags.get("building:levels", "")},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    out = os.path.join(CE, slug(name))
    os.makedirs(out, exist_ok=True)
    json.dump({"type": "FeatureCollection", "features": feats},
              open(os.path.join(out, "buildings.geojson"), "w"), separators=(",", ":"))
    print(f"  buildings.geojson: {len(feats)} footprints inside the boundary")
    # SHP for CityEngine import (ce_batch expects buildings.shp) — folded in 1 Sep 26
    if feats:
        import geopandas as gpd
        gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
        gdf["bHeight"] = gdf["bHeight"].astype(float)
        gdf.to_file(os.path.join(out, "buildings.shp"))
        print("  buildings.shp written (CE-ready)")

    pulse = json.load(open(os.path.join(PUB, "pulse.json"), encoding="utf-8"))
    projs = [p for p in pulse.get("projects", {}).get("projectLookup", [])
             if slug(p.get("area", "")) == slug(name)]
    with open(os.path.join(out, "pipeline.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["project", "developer", "units", "percentComplete", "completion", "escrow",
                    "status_for_cga", "estHeight_m"])
        for p in projs:
            pc = p.get("percentComplete")
            st = "construction" if (pc is not None and 0 < pc < 100) else "pipeline"
            est = round(max(20, min(240, (p.get("units") or 60) / 8 * 3.4)), 1)   # crude massing guess, refine in CE
            w.writerow([p.get("project"), p.get("developer"), p.get("units"), pc,
                        p.get("endDate"), "yes" if p.get("escrowRegistered") else "no", st, est])
    print(f"  pipeline.csv: {len(projs)} registered projects (manual ghost placement — see README)")

    open(os.path.join(out, "najma.cga"), "w").write('''/**
 * Najma future-skyline starter rule. Existing stock in ink-grey, under-construction rising
 * in teal, registered pipeline as translucent gold ghosts. Refine freely in CE.
 */
version "2023.0"

attr status  = "existing"     // existing | construction | pipeline
attr bHeight = 12
attr pctComplete = 100

@StartRule
Lot -->
    extrude(bHeight)
    Mass

Mass -->
    case status == "existing" :
        color("#39434F")
        Mass.
    case status == "construction" :
        color("#3E8A7E")
        set(material.opacity, 0.8)
        split(y){ bHeight * pctComplete/100 : Built | ~1 : Rising }
    else :
        color("#C5A56A")
        set(material.opacity, 0.4)
        Mass.

Built  --> color("#3E8A7E") Built.
Rising --> color("#3E8A7E") set(material.opacity, 0.25) Rising.
''')

    open(os.path.join(out, "README_CE.md"), "w", encoding="utf-8").write(f"""# CE import — {name}

1. New CE scene (WGS84 / Web Mercator per your AD masterplan setup).
2. File → Import → **buildings.geojson** — footprints arrive with `bHeight` + `status=existing`.
3. Assign **najma.cga** to the imported shapes; StartRule = `Lot`.
4. **pipeline.csv** lists this community's registered projects (units, %-complete, completion,
   est. massing height). Draw a ghost lot per project where it belongs, assign the same rule,
   set `status` = construction/pipeline, `bHeight` = estHeight_m, `pctComplete` from the CSV.
   (Automatic placement unlocks when the geocoding privilege lands — each project geocoded once.)
5. Camera preset looking NE over the community; render stills + a 10s orbit:
   "**{name} — this skyline, {{latest completion year in the CSV}}**".
6. Figures line for the post: units + completion straight from pipeline.csv — register-grounded,
   as always. Massing is illustrative and says so.

Via your CE Python bridge (port 25333) steps 2–5 are scriptable once done once by hand.
""")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
