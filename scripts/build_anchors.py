"""Label anchors for the skyline viewer: one record per NAMED building per district.
Sources, in precedence order: (1) OpenStreetMap name on the footprint (what ce_export.py kept), (2) Wikidata buildings with
coordinates (point-in-footprint or nearest footprint <= 40 m), (3) confidence-gated DLD project bindings (data/ce/<slug>/bindings.json),
(4) developer-site portfolio names geocoded onto footprints (bind_portfolio.py, later). Output data/names/anchors_<slug>.json:
{ id, name, source, dev (developer key when known), lon, lat, x, z (scene metres, y-up, z = -northing like the GLB), h (roof height m) }
plus a coverage report: how many of the TALL buildings (top 30 % by height) carry a name - those are the ones that pass in front.
Usage: python scripts/build_anchors.py [slug ...]
"""
import glob, json, math, os, re, struct, sys
import pyproj
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "names"); os.makedirs(OUT, exist_ok=True)
WIKI = json.load(open(os.path.join(OUT, "wikidata_dubai_buildings.json"), encoding="utf-8"))["items"] if os.path.exists(os.path.join(OUT, "wikidata_dubai_buildings.json")) else []

def rings(geom):
    if geom["type"] == "Polygon": return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon": return [p[0] for p in geom["coordinates"]]
    return []

def centroid(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]; return sum(xs) / len(xs), sum(ys) / len(ys)

def inside(pt, ring):
    x, y = pt; n = len(ring); j = n - 1; c = False
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi): c = not c
        j = i
    return c

def metres(lon1, lat1, lon2, lat2):
    k = math.cos(math.radians((lat1 + lat2) / 2)); return math.hypot((lon2 - lon1) * 111320 * k, (lat2 - lat1) * 110540)


# ---------------- developer tagging
DEV_KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
           "ZAYA/Palma": "zaya_palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman"}
STOP = {"the", "by", "at", "residences", "residence", "tower", "towers", "dubai", "marina", "bay", "living", "collection", "building", "apartments", "hotel", "and", "of", "a"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}

def toks(n):
    t = re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split()
    return [ROMAN.get(w, w) for w in t if w not in STOP]

_DEVNAMES = None
def dev_names():
    """[(dev_key, project name, tokens)] from the site registers and the DLD-attributed transaction projects."""
    global _DEVNAMES
    if _DEVNAMES is not None: return _DEVNAMES
    out = []
    for f in glob.glob(os.path.join(ROOT, "data", "dev_meta", "*_portfolio.json")):
        key = os.path.basename(f)[:-len("_portfolio.json")]
        for pr in json.load(open(f, encoding="utf-8")).get("properties", []):
            out.append((key, pr["name"], toks(pr["name"])))
    dna = os.path.join(ROOT, "data", "dev_meta", "developer_dna.json")
    if os.path.exists(dna):
        for name, d in json.load(open(dna, encoding="utf-8")).get("developers", {}).items():
            key = DEV_KEY.get(name)
            for t in d.get("tx_2026", {}).get("projects", []):
                if key and not t.get("portfolio_unmatched"): out.append((key, t["project"], toks(t["project"])))
            for p in d.get("dld_projects_2026", []):
                if key: out.append((key, p["project"], toks(p["project"])))
    _DEVNAMES = [x for x in out if len(x[2]) >= 1]
    return _DEVNAMES

def dev_for(name):
    """Match a footprint name to a developer project: identical token sets, or one contained in the other with >= 2 shared tokens
    (or a single distinctive token of >= 6 letters). Returns (dev_key, project) or None."""
    a = toks(name)
    if not a: return None
    A = set(a); best = None
    for key, proj, b in dev_names():
        B = set(b)
        if not B: continue
        shared = A & B
        if A == B: return (key, proj)
        if (A <= B or B <= A) and (len(shared) >= 2 or (len(shared) == 1 and len(next(iter(shared))) >= 6 and not next(iter(shared)).isdigit())):
            best = best or (key, proj)
    return best

# ---------------- per-building GLB mesh map
def mesh_map(slug, blds):
    f = os.path.join(CE, "_glb", f"sky_{slug}_v2_0.glb")
    if not os.path.exists(f): return {}
    b = open(f, "rb").read(); ln = struct.unpack_from("<I", b, 12)[0]; j = json.loads(b[20:20 + ln]); acc = j["accessors"]
    out = {}
    for mi, m in enumerate(j["meshes"]):
        mins = [acc[p["attributes"]["POSITION"]]["min"] for p in m["primitives"]]; maxs = [acc[p["attributes"]["POSITION"]]["max"] for p in m["primitives"]]
        cx = (min(x[0] for x in mins) + max(x[0] for x in maxs)) / 2; cz = (min(x[2] for x in mins) + max(x[2] for x in maxs)) / 2
        best = min(blds, key=lambda q: (q["x"] - cx) ** 2 + (q["z"] - cz) ** 2)
        if math.hypot(best["x"] - cx, best["z"] - cz) <= 12: out[best["i"]] = mi
    return out

def build(slug):
    d = os.path.join(CE, slug); gj = os.path.join(d, "buildings.geojson")
    if not os.path.exists(gj): return None
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    ctx = json.load(open(os.path.join(d, "ctx.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "ctx.json")) else {}
    bind = {}
    bj = os.path.join(d, "bindings.json")
    if os.path.exists(bj):
        bl = json.load(open(bj, encoding="utf-8")).get("bindings", {})
        if isinstance(bl, dict):                       # bind_buildings.py: { "<feature index>": {project, tx, score, dist_m} }
            bind = {str(k): v for k, v in bl.items()}
        else:
            for b in bl:
                if b.get("osm_id") is not None: bind[str(b["osm_id"])] = b
    blds = []
    for i, f in enumerate(feats):
        p = f["properties"]; rs = rings(f["geometry"])
        if not rs: continue
        ring = max(rs, key=len); cx, cy = centroid(ring)
        blds.append({"i": i, "id": str(p.get("osm_id") or p.get("id") or i), "name": (p.get("name") or "").strip() or None, "src": "osm" if p.get("name") else None,
                     "lon": cx, "lat": cy, "ring": ring, "h": float(p.get("bHeight") or 0), "levels": p.get("levels") or None, "status": p.get("status")})
    # OpenStreetMap English names (osm_names_en.py): name:en > addr:housename > official_name; replaces an Arabic-only `name`
    oe = os.path.join(OUT, f"osm_en_{slug}.json")
    if os.path.exists(oe):
        for k, v in json.load(open(oe, encoding="utf-8")).items():
            i = int(k)
            if i < len(blds) and blds[i]["i"] == i or True:
                b = next((x for x in blds if x["i"] == i), None)
                if not b: continue
                en = v.get("name_en") or v.get("housename") or v.get("official") or (v.get("name") if v.get("name") and not re.search(r"[؀-ۿ]", v["name"]) else None)
                if en and (not b["name"] or re.search(r"[؀-ۿ]", b["name"])):
                    b["name"], b["src"] = en, "osm_en"
    # wikidata -> footprint (inside, else nearest <= 40 m)
    lon0 = sum(b["lon"] for b in blds) / len(blds); lat0 = sum(b["lat"] for b in blds) / len(blds)
    near_w = [w for w in WIKI if metres(lon0, lat0, w["lon"], w["lat"]) < 6000]
    for w in near_w:
        hit = next((b for b in blds if inside((w["lon"], w["lat"]), b["ring"])), None)
        if not hit:
            cand = min(blds, key=lambda b: metres(w["lon"], w["lat"], b["lon"], b["lat"]))
            if metres(w["lon"], w["lat"], cand["lon"], cand["lat"]) <= 40: hit = cand
        if hit and (not hit["name"] or re.search(r"[؀-ۿ]", hit["name"])):   # fill, or replace an Arabic-only map name
            hit["name"], hit["src"] = w["name"], "wikidata"
        if hit and w.get("height_m") and w["height_m"] > hit["h"]: hit["h"] = w["height_m"]   # true height beats the 3.2 m/level estimate
    # DLD project bindings (Business Bay so far)
    for b in blds:
        bb = bind.get(b["id"]) or bind.get(str(b["i"]))
        if bb and not b["name"]: b["name"], b["src"] = bb.get("project") or bb.get("name"), "dld"
    # scene coordinates: the GLB is in EPSG:32640 metres, y-up, z = -northing, ABSOLUTE (ctx.glb_center = scene centre, same units)
    for b in blds:
        e, n = TO_UTM(b["lon"], b["lat"]); b["x"] = round(e, 1); b["z"] = round(-n, 1)
    # developer tagging: site registers (data/dev_meta/<key>_portfolio.json) + DLD-attributed project names (developer_dna.json)
    for b in blds:
        if b["name"]:
            hit = dev_for(b["name"])
            if hit: b["dev"], b["dev_project"] = hit
    # per-building GLB (sky_<slug>_v2_0.glb): map each mesh to its footprint by centre distance, so the viewer can colour/tag meshes
    mesh_of = mesh_map(slug, blds)
    for b in blds:
        if b["i"] in mesh_of: b["mesh"] = mesh_of[b["i"]]
    named = [b for b in blds if b["name"]]
    hs = sorted(b["h"] for b in blds); tall_cut = hs[int(len(hs) * 0.7)] if hs else 0
    tall = [b for b in blds if b["h"] >= tall_cut and b["h"] > 12]; tall_named = [b for b in tall if b["name"]]
    anchors = [{"id": b["id"], "i": b["i"], "mesh": b.get("mesh"), "name": b["name"], "source": b["src"], "dev": b.get("dev"), "dev_project": b.get("dev_project"), "lon": round(b["lon"], 6), "lat": round(b["lat"], 6), "x": b.get("x"), "z": b.get("z"), "h": round(b["h"], 1), "levels": b["levels"]} for b in named]
    # developer buildings are the point of the exercise: keep them even when the map had no name (the register name becomes the label)
    devmeshes = [{"i": b["i"], "mesh": b.get("mesh"), "dev": b["dev"], "name": b.get("dev_project")} for b in blds if b.get("dev") and not b["name"]]
    anchors.sort(key=lambda a: -a["h"])
    json.dump({"district": slug, "buildings": len(blds), "named": len(named), "tall": len(tall), "tall_named": len(tall_named), "tall_cut_m": round(tall_cut, 1),
               "sources": {s: sum(1 for a in anchors if a["source"] == s) for s in ("osm", "osm_en", "wikidata", "dld", "portfolio")}, "glb_center": ctx.get("glb_center"),
               "per_building_glb": os.path.exists(os.path.join(CE, "_glb", f"sky_{slug}_v2_0.glb")), "developers": sorted({a["dev"] for a in anchors if a.get("dev")}), "dev_tagged": sum(1 for a in anchors if a.get("dev")), "anchors": anchors},
              open(os.path.join(OUT, f"anchors_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return len(blds), len(named), len(tall), len(tall_named), [a["name"] for a in anchors[:4]]

if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(os.path.join(CE, "*")) if os.path.isdir(p) and not p.endswith("_glb"))
    print(f"{'district':<26} {'bldgs':>6} {'named':>6} {'tall':>5} {'tall named':>10}  tallest named")
    T = [0, 0, 0, 0]
    for s in slugs:
        r = build(s)
        if not r: continue
        T = [T[i] + r[i] for i in range(4)]
        print(f"{s:<26} {r[0]:>6} {r[1]:>6} {r[2]:>5} {r[3]:>5} {100*r[3]/max(1,r[2]):>3.0f}%  {', '.join(r[4])[:60]}")
    print(f"{'TOTAL':<26} {T[0]:>6} {T[1]:>6} {T[2]:>5} {T[3]:>5} {100*T[3]/max(1,T[2]):>3.0f}%")
