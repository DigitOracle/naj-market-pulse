"""Vicinity facts for a building card: nearest metro, nearest schools (Esri Places), 1 km demographics (GeoEnrichment).
Auth = ArcGIS Pro sign-in token. Run with propy.bat. Output: data/cards/vicinity.json
"""
import json, math, os, sys, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import arcpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "cards", "vicinity.json")
LON, LAT = 55.308, 25.168          # The Symphony site anchor
tok = (arcpy.GetSigninToken() or {}).get("token")
if not tok:
    sys.exit("no Pro sign-in token")
UA = {"User-Agent": "najma-market-pulse/1.0"}


def get(url, params):
    params = dict(params, f="json", token=tok)
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))


def post(url, params):
    params = dict(params, f="json", token=tok)
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=120))


def dist_km(lon, lat):
    dx = (lon - LON) * 111.32 * math.cos(math.radians(LAT)); dy = (lat - LAT) * 110.57
    return math.hypot(dx, dy)


PLACES = "https://places-api.arcgis.com/arcgis/rest/services/places-service/v1/places/near-point"
# Esri Places category ids (Foursquare taxonomy): metro/subway station, tram, schools
CATS = {
    "metro": ["4bf58dd8d48988d1fd931735", "4bf58dd8d48988d129951735", "52f2ab2ebcbc57f1066b8b51"],  # Metro Station, Train Station, Tram Station
    "school": ["4bf58dd8d48988d13b941735", "4f4533804b9074f6e4fb0105", "4bf58dd8d48988d13d941735", "52e81612bcbc57f1066b7a45", "4f4533814b9074f6e4fb0106"],  # School, Elementary, High School, Nursery, Middle
}
result = {"anchor": {"lon": LON, "lat": LAT}, "source": "Esri Places (Foursquare taxonomy) + Esri GeoEnrichment KeyFacts UAE 2024, via ArcGIS Pro sign-in", "metro": [], "schools": []}
for key, cats in CATS.items():
    try:
        j = get(PLACES, {"x": LON, "y": LAT, "radius": 10000 if key == "metro" else 4000, "categoryIds": ",".join(cats), "pageSize": 20})
        rows = []
        for p in j.get("results", []):
            loc = p.get("location", {}); lon, lat = loc.get("x"), loc.get("y")
            rows.append({"name": p.get("name"), "category": (p.get("categories") or [{}])[0].get("label"), "km": round(dist_km(lon, lat), 2), "lon": lon, "lat": lat})
        rows.sort(key=lambda r: r["km"])
        result["metro" if key == "metro" else "schools"] = rows[:6]
        print(key, len(rows), "->", [(r["name"], r["km"]) for r in rows[:4]])
    except Exception as e:
        result[key + "_error"] = str(e)[:200]; print(key, "ERROR", str(e)[:120])

# demographics: 1 km ring + 3 km ring
study = [{"geometry": {"x": LON, "y": LAT}, "areaType": "RingBuffer", "bufferUnits": "esriKilometers", "bufferRadii": [1, 3], "attributes": {"slug": "symphony"}}]
VARS = ["KeyFacts.TOTPOP_CY", "KeyFacts.TOTHH_CY", "KeyFacts.AVGHHSZ_CY", "KeyFacts.PPPC_CY", "KeyFacts.PPIDX_CY", "KeyFacts.POPDENS_CY"]
try:
    j = post("https://geoenrich.arcgis.com/arcgis/rest/services/World/GeoenrichmentServer/Geoenrichment/enrich",
             {"studyAreas": json.dumps(study), "analysisVariables": json.dumps(VARS), "returnGeometry": "false"})
    rings = []
    for chunk in j["results"][0]["value"]["FeatureSet"]:
        for feat in chunk.get("features", []):
            a = feat["attributes"]
            rings.append({"radius_km": a.get("bufferRadii"), "pop": a.get("TOTPOP_CY"), "households": a.get("TOTHH_CY"), "avg_hh": a.get("AVGHHSZ_CY"),
                          "pp_per_capita": a.get("PPPC_CY"), "pp_index": a.get("PPIDX_CY"), "density": a.get("POPDENS_CY")})
    result["demographics"] = rings
    print("demographics:", rings)
except Exception as e:
    result["demographics_error"] = str(e)[:200]; print("enrich ERROR", str(e)[:120])

json.dump(result, open(OUT, "w"), indent=1)
print("written", OUT)
