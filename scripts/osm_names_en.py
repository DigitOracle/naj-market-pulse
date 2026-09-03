"""English building names from OpenStreetMap for every district: ways with name:en / name / addr:housename / official_name / brand
inside the district bbox, returned with their centre point and matched onto our footprints by centroid distance (<= 15 m).
ce_export.py only kept `name` (often Arabic); this pass adds name:en without touching the footprints or the GLBs.
Output: data/names/osm_en_<slug>.json  { "<feature index>": {"name_en", "name", "housename", "official", "dist_m"} }
Overpass is rate-limited: one query per district, mirrors rotated, 8 s pause. Usage: python scripts/osm_names_en.py [slug ...]
"""
import glob, json, math, os, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "names"); os.makedirs(OUT, exist_ok=True)
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]

def bbox_of(feats):
    xs, ys = [], []
    for f in feats:
        g = f["geometry"]; polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for x, y in poly[0]: xs.append(x); ys.append(y)
    return min(ys), min(xs), max(ys), max(xs)

def centroid(f):
    g = f["geometry"]; ring = (g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0])
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)

def metres(lon1, lat1, lon2, lat2):
    k = math.cos(math.radians((lat1 + lat2) / 2)); return math.hypot((lon2 - lon1) * 111320 * k, (lat2 - lat1) * 110540)

def overpass(q):
    last = None
    for i, m in enumerate(MIRRORS * 2):
        try:
            r = urllib.request.urlopen(urllib.request.Request(m, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": "najma-names/1.0 (contact@digitalabbot.io)"}), timeout=120)
            return json.loads(r.read())
        except Exception as e:
            last = e; time.sleep(10 + 5 * i)
    raise last

def run(slug):
    gj = os.path.join(CE, slug, "buildings.geojson"); out = os.path.join(OUT, f"osm_en_{slug}.json")
    if not os.path.exists(gj): return None
    if os.path.exists(out): return json.load(open(out, encoding="utf-8"))
    feats = json.load(open(gj, encoding="utf-8"))["features"]; b = bbox_of(feats)
    q = f'[out:json][timeout:120];(way["building"]["name:en"]({b[0]},{b[1]},{b[2]},{b[3]});way["building"]["addr:housename"]({b[0]},{b[1]},{b[2]},{b[3]});way["building"]["official_name"]({b[0]},{b[1]},{b[2]},{b[3]});way["building"]["name"]({b[0]},{b[1]},{b[2]},{b[3]}););out tags center;'
    els = overpass(q).get("elements", [])
    cents = [centroid(f) for f in feats]
    res = {}
    for e in els:
        c = e.get("center"); t = e.get("tags", {})
        if not c: continue
        j, best = None, 1e9
        for i, (cx, cy) in enumerate(cents):
            d = metres(c["lon"], c["lat"], cx, cy)
            if d < best: best, j = d, i
        if j is not None and best <= 15:
            res[str(j)] = {"name_en": t.get("name:en"), "name": t.get("name"), "housename": t.get("addr:housename"), "official": t.get("official_name"), "brand": t.get("brand"), "dist_m": round(best, 1), "osm_id": e.get("id")}
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    return res

if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(os.path.join(CE, "*")) if os.path.isdir(p) and not p.endswith("_glb"))
    for s in slugs:
        try:
            r = run(s); en = sum(1 for v in (r or {}).values() if v.get("name_en")); hn = sum(1 for v in (r or {}).values() if v.get("housename"))
            print(f"{s:<26} matched {len(r or {}):>4}  name:en {en:>4}  housename {hn:>3}"); time.sleep(8)
        except Exception as e:
            print(s, "FAILED", str(e)[:80]); time.sleep(20)
    print("OSM_EN_DONE")
