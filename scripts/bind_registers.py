"""Geocode-and-snap: place every project of the eleven developers (site registers + DLD-attributed transaction projects) on a
footprint in our 39 district models, so buildings get their developer tag and, where the map had no name, the project name.
Geocoder: Esri World Geocoder via the Worker's token endpoint (READ_KEY), cached forever in data/geocode_cache.json (never re-paid).
Snap rule (no guessed joins): geocode score >= 85 AND (point inside a footprint OR nearest footprint centroid <= 60 m, preferring the
tallest footprint within 80 m when the point lands on a plaza). Unplaced projects are listed with a reason - they become pipeline
massing candidates for CityEngine later (bind_registers_unplaced.json).
Output: data/names/dev_bindings.json  { "<slug>": { "<footprint index>": {dev, project, source, score, dist_m} } }
Usage: READ_KEY=... [GOOGLE_KEY=...] python scripts/bind_registers.py [--dry]   (GOOGLE_KEY = Places API, used only where Esri is weak)
"""
import glob, json, math, os, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); CACHE = os.path.join(ROOT, "data", "geocode_cache.json")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"
sys.path.insert(0, HERE)
from build_anchors import area_district  # noqa: E402  (same district aliases as the name matcher)
DEV_KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
           "ZAYA/Palma": "zaya_palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman"}

def token():
    key = os.environ.get("READ_KEY")
    if not key: raise SystemExit("READ_KEY not set")
    return json.load(urllib.request.urlopen(urllib.request.Request(f"{WORKER}/esri_token?key={key}", headers={"User-Agent": "najma-bind/1.0"}), timeout=30))["token"]

def geocode(tok, q):
    p = urllib.parse.urlencode({"f": "json", "token": tok, "langCode": "en", "singleLine": q, "maxLocations": "1", "outFields": "Score,Addr_type,Type", "searchExtent": "54.9,24.7,55.7,25.4", "countryCode": "ARE"})
    j = json.load(urllib.request.urlopen(urllib.request.Request("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + p, headers={"Referer": WORKER, "User-Agent": "najma-bind/1.0"}), timeout=30))
    c = (j.get("candidates") or [None])[0]
    if not c: return None
    a = c.get("attributes", {})
    return {"lon": c["location"]["x"], "lat": c["location"]["y"], "score": c.get("score", 0), "address": c.get("address", ""), "addr_type": a.get("Addr_type"), "type": a.get("Type")}

def geocode_google(key, name, area):
    """Google Places Text Search (New) - resolves developer project names far better than a street geocoder. Needs GOOGLE_KEY."""
    body = json.dumps({"textQuery": f"{name} {area} Dubai".strip(), "locationBias": {"circle": {"center": {"latitude": 25.12, "longitude": 55.25}, "radius": 45000.0}}, "maxResultCount": 1}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchText", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.displayName,places.location,places.types,places.formattedAddress"})
    j = json.load(urllib.request.urlopen(req, timeout=30)); pl = (j.get("places") or [None])[0]
    if not pl: return None
    return {"lon": pl["location"]["longitude"], "lat": pl["location"]["latitude"], "score": 90, "address": pl.get("formattedAddress", ""), "addr_type": "POI", "type": ",".join(pl.get("types", [])[:3]), "name": (pl.get("displayName") or {}).get("text"), "via": "google"}

def rings(g):
    return [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]

def inside(pt, ring):
    x, y = pt; n = len(ring); j = n - 1; c = False
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi): c = not c
        j = i
    return c

def metres(lon1, lat1, lon2, lat2):
    k = math.cos(math.radians((lat1 + lat2) / 2)); return math.hypot((lon2 - lon1) * 111320 * k, (lat2 - lat1) * 110540)

# ---- districts: footprints + bboxes
DIST = {}
for d in sorted(glob.glob(os.path.join(CE, "*", "buildings.geojson"))):
    slug = os.path.basename(os.path.dirname(d))
    if slug == "goldensymphony": continue
    feats = json.load(open(d, encoding="utf-8"))["features"]; fps = []
    for i, f in enumerate(feats):
        rs = rings(f["geometry"]); ring = max(rs, key=len)
        fps.append({"i": i, "ring": ring, "lon": sum(p[0] for p in ring) / len(ring), "lat": sum(p[1] for p in ring) / len(ring), "h": float(f["properties"].get("bHeight") or 0), "name": f["properties"].get("name") or ""})
    xs = [p[0] for fp in fps for p in fp["ring"]]; ys = [p[1] for fp in fps for p in fp["ring"]]
    DIST[slug] = {"fps": fps, "bbox": (min(xs), min(ys), max(xs), max(ys))}
print("districts:", len(DIST))

# ---- projects to place: site registers + DLD-attributed transaction/registered projects
projects = []
for f in glob.glob(os.path.join(ROOT, "data", "dev_meta", "*_portfolio.json")):
    key = os.path.basename(f)[:-len("_portfolio.json")]
    for pr in json.load(open(f, encoding="utf-8")).get("properties", []):
        projects.append({"dev": key, "name": pr["name"], "area": pr.get("area") or (pr.get("facts") or {}).get("location") or "", "source": "site"})
dna = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))["developers"]
for dev, d in dna.items():
    key = DEV_KEY.get(dev)
    for t in d.get("tx_2026", {}).get("projects", []):
        if not t.get("portfolio_unmatched"): projects.append({"dev": key, "name": t["project"], "area": t.get("area") or "", "source": "dld_tx"})
    for p in d.get("dld_projects_2026", []):
        projects.append({"dev": key, "name": p["project"], "area": p.get("area") or "", "source": "dld_reg"})
seen = set(); uniq = []
for p in projects:
    k = (p["dev"], p["name"].strip().lower())
    if k in seen: continue
    seen.add(k); uniq.append(p)
projects = uniq; print("projects to place:", len(projects))

# DLD area per (dev, alias) from the project fact sheets - the truth about where a project's sales register
DLD_AREA = {}
_pf = os.path.join(ROOT, "data", "board", "projfacts.json")
if os.path.exists(_pf):
    for rec in json.load(open(_pf, encoding="utf-8")).get("projects", {}).values():
        da = (rec.get("dld") or {}).get("dld_area")
        if da:
            for al in set(rec.get("aliases", [])) | {rec.get("name", "")}: DLD_AREA[(rec["dev"], al.strip().lower())] = da
cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
dry = "--dry" in sys.argv
tok = None if dry else token()
bind = {}; unplaced = []; placed = 0; stats = {"inside": 0, "near": 0, "tall80": 0}
for p in projects:
    q = f"{p['name']}, {p['area']}, Dubai, United Arab Emirates" if p["area"] else f"{p['name']}, Dubai, United Arab Emirates"
    ck = "reg::" + q
    if ck not in cache:
        if dry: unplaced.append({**p, "why": "not geocoded (dry run)"}); continue
        try: cache[ck] = geocode(tok, q)
        except Exception as e: cache[ck] = None; print("  geocode err", p["name"][:30], str(e)[:40])
        time.sleep(0.3)
    g = cache[ck]
    gk = os.environ.get("GOOGLE_KEY")
    if gk and (not g or g["score"] < 85 or (g.get("addr_type") or "") not in ("POI", "PointAddress", "StreetAddress", "Subaddress", "Building")):
        ckg = "goog::" + q                                  # second opinion from Google Places when Esri is weak (cached too)
        if ckg not in cache:
            try: cache[ckg] = geocode_google(gk, p["name"], p["area"])
            except Exception as e: cache[ckg] = None; print("  google err", p["name"][:30], str(e)[:40])
            time.sleep(0.15)
        gg = cache[ckg]
        # a Google hit must actually be THIS project: its display name shares a distinctive word with the project name
        if gg:
            import re as _re
            stop = {"the", "by", "at", "residences", "residence", "tower", "towers", "dubai", "building", "apartments", "and", "of"}
            tk = lambda t: {w for w in _re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split() if w not in stop and len(w) > 2}
            if not (tk(p["name"]) & tk(gg.get("name"))): gg = None
        if gg: g = gg
    if not g: unplaced.append({**p, "why": "no candidate"}); continue
    slug0 = next((s0 for s0, D in DIST.items() if D["bbox"][0] <= g["lon"] <= D["bbox"][2] and D["bbox"][1] <= g["lat"] <= D["bbox"][3]), None)
    exp = area_district(p["area"]) or area_district(DLD_AREA.get((p["dev"], p["name"].strip().lower())))   # register area, else the DLD area of its sales
    agree = bool(exp and slug0 and exp == slug0)
    if exp and slug0 and exp != slug0: unplaced.append({**p, "why": f"area disagrees ({exp} vs {slug0})", "geo": g}); continue
    # score gate: 85 on its own, or 75 when the geocoder hit is a POI/address AND the stated area agrees with where it landed
    poi = (g.get("addr_type") or "") in ("POI", "PointAddress", "StreetAddress", "Subaddress", "Building")
    if g["score"] < 85 and not (agree and poi and g["score"] >= 75): unplaced.append({**p, "why": f"low score {g['score']:.0f}", "geo": g}); continue
    # POI-quality hits only: a locality/postal-level hit is not a building
    if (g.get("addr_type") or "") in ("Locality", "Postal", "PostalExt", "Region", "Subregion", "Sector", "Block", "Zone", "Neighborhood", "District", "City"):
        unplaced.append({**p, "why": f"coarse hit ({g.get('addr_type')})", "geo": g}); continue
    slug = slug0
    if not slug: unplaced.append({**p, "why": "outside the 38 districts", "geo": g}); continue
    fps = DIST[slug]["fps"]; pt = (g["lon"], g["lat"])
    hit = next((fp for fp in fps if inside(pt, fp["ring"])), None); how = "inside"
    if not hit:
        near = sorted(((metres(pt[0], pt[1], fp["lon"], fp["lat"]), fp) for fp in fps), key=lambda x: x[0])[:12]
        tall = [x for x in near if x[0] <= 80 and x[1]["h"] >= 20]
        if tall: hit, how = max(tall, key=lambda x: x[1]["h"])[1], "tall80"
        elif near and near[0][0] <= 60: hit, how = near[0][1], "near"
    if not hit: unplaced.append({**p, "why": "no footprint within 60 m", "geo": g, "slug": slug}); continue
    d = metres(pt[0], pt[1], hit["lon"], hit["lat"]); stats[how] += 1
    b = bind.setdefault(slug, {}); k = str(hit["i"])
    if k in b and b[k]["source"] == "site" and p["source"] != "site": continue          # site register beats a DLD name on the same footprint
    b[k] = {"dev": p["dev"], "project": p["name"], "source": p["source"], "score": round(g["score"], 1), "dist_m": round(d, 1), "how": how, "map_name": hit["name"]}
    placed += 1
json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"updated": time.strftime("%Y-%m-%d %H:%M"), "placed": placed, "unplaced": len(unplaced), "how": stats, "bindings": bind}, open(os.path.join(NAMES, "dev_bindings.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(unplaced, open(os.path.join(NAMES, "bind_registers_unplaced.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
import collections
why = collections.Counter(u["why"].split(" (")[0].split(" score")[0] for u in unplaced)
print(f"placed {placed} on footprints ({stats}) | unplaced {len(unplaced)}: {dict(why)}")
for slug, b in sorted(bind.items(), key=lambda x: -len(x[1]))[:12]: print(f"  {slug:<26} {len(b):>3}  e.g. " + "; ".join(f"{v['project'][:22]}->{v['map_name'][:18] or '(unnamed)'}" for v in list(b.values())[:3]))
