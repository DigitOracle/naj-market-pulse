"""Nearest metro + schools via the World Geocoding service category search (fallback when Places returns 403).
Merges into data/cards/vicinity.json. Run with propy.bat.
"""
import json, math, os, sys, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import arcpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "cards", "vicinity.json")
LON, LAT = 55.308, 25.168
tok = arcpy.GetSigninToken()["token"]
WORKER = "https://azimuth-2.digitalchemy.workers.dev"


def dist_km(lon, lat):
    dx = (lon - LON) * 111.32 * math.cos(math.radians(LAT)); dy = (lat - LAT) * 110.57
    return math.hypot(dx, dy)


def cat(category, radius_m):
    p = urllib.parse.urlencode({"f": "json", "token": tok, "category": category, "location": "%s,%s" % (LON, LAT),
                                "searchExtent": "%s,%s,%s,%s" % (LON - 0.15, LAT - 0.15, LON + 0.15, LAT + 0.15),
                                "maxLocations": 20, "outFields": "PlaceName,Type,Place_addr,X,Y", "langCode": "en"})
    req = urllib.request.Request("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + p,
                                 headers={"Referer": WORKER, "User-Agent": "najma-market-pulse/1.0"})
    j = json.load(urllib.request.urlopen(req, timeout=60))
    rows = []
    for c in j.get("candidates", []):
        a = c.get("attributes", {}); lon, lat = c["location"]["x"], c["location"]["y"]
        rows.append({"name": a.get("PlaceName") or c.get("address"), "category": a.get("Type"), "km": round(dist_km(lon, lat), 2), "lon": lon, "lat": lat})
    rows = [r for r in rows if r["km"] * 1000 <= radius_m]
    rows.sort(key=lambda r: r["km"])
    return rows


v = json.load(open(OUT)) if os.path.exists(OUT) else {}
try:
    metro = cat("Metro Station", 12000)
    v["metro"] = metro[:5]; print("metro:", [(r["name"], r["km"]) for r in metro[:5]])
except Exception as e:
    print("metro ERR", str(e)[:120])
try:
    schools = []
    for c in ("School", "Primary School", "Secondary School", "Nursery"):
        schools += cat(c, 5000)
    seen = set(); uniq = []
    for r in schools:
        k = (r["name"] or "").lower()
        if k and k not in seen:
            seen.add(k); uniq.append(r)
    uniq.sort(key=lambda r: r["km"])
    v["schools"] = uniq[:6]; print("schools:", [(r["name"], r["km"]) for r in uniq[:6]])
except Exception as e:
    print("schools ERR", str(e)[:120])
v["poi_source"] = "Esri World Geocoding category search (Metro Station / School), straight-line km from the site anchor"
json.dump(v, open(OUT, "w"), indent=1)
print("written")
