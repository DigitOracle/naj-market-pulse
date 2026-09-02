"""GeoEnrichment for every CityEngine district: who lives around this tower.

1 km ring around each district's building-stock centre -> total population,
households, avg household size, purchasing power per capita (Esri Global
demographics; Michael Bauer Research for UAE). Auth = the ArcGIS Pro sign-in
token (arcpy.GetSigninToken) against the GeoEnrichment REST service directly —
the arcgis-package wrapper has no token under GIS("pro") in 2.4.3.
Cost: ~10 credits per 1,000 attributes (38 districts x 4 vars = trivial).

Run with propy.bat. Output: data/enrich/districts_enrichment.json
"""
import json, os, sys, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import arcpy

HERE = os.path.dirname(os.path.abspath(__file__))
CE = os.path.abspath(os.path.join(HERE, "..", "data", "ce"))
OUT = os.path.abspath(os.path.join(HERE, "..", "data", "enrich"))
os.makedirs(OUT, exist_ok=True)

tok = (arcpy.GetSigninToken() or {}).get("token")
if not tok:
    sys.exit("no Pro sign-in token — sign in to ArcGIS Pro first")

slugs = sorted(d for d in os.listdir(CE)
               if os.path.exists(os.path.join(CE, d, "buildings.geojson")))
print(len(slugs), "districts")


def centre(slug):
    gj = json.load(open(os.path.join(CE, slug, "buildings.geojson")))
    xs, ys, n = 0.0, 0.0, 0
    for f in gj["features"]:
        g = f["geometry"]
        rings = g["coordinates"] if g["type"] == "Polygon" else [r for p in g["coordinates"] for r in p]
        for lon, lat in rings[0]:
            xs += lon; ys += lat; n += 1
    return round(xs / n, 5), round(ys / n, 5)


centres = {s: centre(s) for s in slugs}
study = [{"geometry": {"x": c[0], "y": c[1]},
          "areaType": "RingBuffer", "bufferUnits": "esriKilometers", "bufferRadii": [1],
          "attributes": {"slug": s}} for s, c in centres.items()]
VARS = ["KeyFacts.TOTPOP_CY", "KeyFacts.TOTHH_CY", "KeyFacts.AVGHHSZ_CY",
        "KeyFacts.PPPC_CY", "KeyFacts.PPIDX_CY", "KeyFacts.POPDENS_CY"]

body = urllib.parse.urlencode({
    "f": "json", "token": tok,
    "studyAreas": json.dumps(study),
    "analysisVariables": json.dumps(VARS),
    "returnGeometry": "false",
}).encode()
req = urllib.request.Request(
    "https://geoenrich.arcgis.com/arcgis/rest/services/World/GeoenrichmentServer/Geoenrichment/enrich",
    data=body, headers={"User-Agent": "najma-market-pulse/1.0"})
j = json.load(urllib.request.urlopen(req, timeout=120))
if "error" in j:
    sys.exit("service error: " + json.dumps(j["error"])[:300])

results = {}
fs = j["results"][0]["value"]["FeatureSet"]
for chunk in fs:
    for feat in chunk.get("features", []):
        a = feat["attributes"]
        s = a.get("slug") or slugs[int(a.get("ID", 0))]
        lon, lat = centres[s]
        results[s] = {"lon": lon, "lat": lat,
                      "TOTPOP": a.get("TOTPOP_CY"), "TOTHH": a.get("TOTHH_CY"),
                      "AVGHHSZ": a.get("AVGHHSZ_CY"), "PPPC": a.get("PPPC_CY"),
                      "PPIDX": a.get("PPIDX_CY"), "POPDENS": a.get("POPDENS_CY")}
        print(f"  {s}: pop {a.get('TOTPOP_CY')} · hh {a.get('TOTHH_CY')} · "
              f"ppc {a.get('PPPC_CY')} · ppidx {a.get('PPIDX_CY')}")

out = {"method": "Esri GeoEnrichment REST, 1 km ring around district building-stock centre",
       "variables": {"TOTPOP": "2024 total population", "TOTHH": "2024 households",
                     "AVGHHSZ": "avg household size", "PPPC": "2024 purchasing power per capita",
                     "PPIDX": "purchasing power index (100 = UAE avg)", "POPDENS": "pop/km2"},
       "source": "Esri Global Demographics (Michael Bauer Research, UAE)",
       "districts": results}
p = os.path.join(OUT, "districts_enrichment.json")
with open(p, "w") as f:
    json.dump(out, f, indent=1)
print(f"\nwritten {p} — {len(results)}/{len(slugs)} districts enriched")
