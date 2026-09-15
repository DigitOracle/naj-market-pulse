"""Label anchors for the skyline viewer: one record per NAMED building per district.
Sources, in precedence order: (1) OpenStreetMap name on the footprint (what ce_export.py kept), (2) Wikidata buildings with
coordinates (point-in-footprint or nearest footprint <= 40 m), (3) confidence-gated DLD project bindings (data/ce/<slug>/bindings.json), (4) Overture Maps building names (overture_names.py ->
data/names/overture_<slug>.json; Overture heights also replace the 3.2 m/level estimate when larger),
(5) developer-site portfolio names geocoded onto footprints (bind_portfolio.py, later). Output data/names/anchors_<slug>.json:
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
           "ZAYA": "zaya", "Palma": "palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman", "Prestige One": "prestigeone", "Emaar": "emaar", "Sobha": "sobha"}
STOP = {"the", "by", "at", "residences", "residence", "tower", "towers", "dubai", "marina", "bay", "living", "collection", "building", "apartments", "hotel", "and", "of", "a"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}

def toks(n):
    t = re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split()
    return [ROMAN.get(w, w) for w in t if w not in STOP]


# district <- area aliases (lower-case substrings of the DLD AREA_EN or the developers' own location text)
DISTRICT_ALIASES = {
    "dubaimarina": ["marsa dubai", "dubai marina", "marina", "jbr", "jumeirah beach residence", "bluewaters", "dubai harbour"],
    "businessbay": ["business bay", "marasi"], "burjkhalifa": ["burj khalifa", "downtown", "opera district"],
    "palmjumeirah": ["palm jumeirah", "the palm"], "alkhairanfirst": ["creek harbour", "al khairan", "creek beach"],
    "dubaimaritimecity": ["maritime", "almelaheyah", "mina rashid"], "meydanone": ["meydan", "nad al shiba", "nadd al shiba", "district one", "meydan horizon"],
    "sobhaheartland": ["sobha hartland", "hartland", "al merkadh", "bukadra", "bu kadra", "mbr city", "mohammed bin rashid city"], "alwasl": ["al wasl", "city walk", "al safa", "jumeirah 1", "la mer", "port de la mer"],
    "althanyahfifth": ["jlt", "jumeirah lakes", "al thanyah fifth", "uptown"], "jltnorth": ["jlt", "jumeirah lakes", "al thanyah fifth", "uptown"], "jltsouth": ["jlt", "jumeirah lakes", "al thanyah fifth", "uptown"], "jumeirahvillagecircle": ["jvc", "jumeirah village circle"],
    "jumeirahvillagetriangle": ["jvt", "jumeirah village triangle"], "arjan": ["arjan", "al barsha south"], "motorcity": ["motor city"],
    "dubaisportscity": ["sports city", "al hebiah fourth"], "dubaihills": ["dubai hills", "hadaeq"], "palmdeira": ["palm deira", "dubai islands", "deira islands"],
    "madinatalmataar": ["dubai south", "madinat al mataar", "expo"], "samaaljadaf": ["jaddaf", "al jadaf", "culture village", "dubai healthcare city"],
    "siliconoasis": ["silicon oasis", "dso"], "dubaistudiocity": ["studio city"], "dubaiproductioncity": ["production city", "impz"],
    "dubaisciencepark": ["science park"], "majan": ["majan", "wadi al safa 3"], "wadialsafa5": ["wadi al safa 5", "town square", "al yelayiss"],
    "wadialsafa4": ["wadi al safa 4", "img"], "damachills": ["damac hills"], "alhebiahfifth": ["al hebiah fifth", "damac hills 2", "akoya"],
    "alsatwa": ["al satwa", "satwa", "al bada"], "alyufrah1": ["al yufrah", "arabian ranches 3"], "alyelayiss1": ["mira", "reem"], "alyelayiss2": ["al yelayiss 2", "town square"],
    "jabalalifirst": ["jabal ali first", "discovery gardens", "ibn battuta", "the gardens"], "jabalaliindustrialsecond": ["jabal ali industrial", "downtown jebel ali", "raw district"],
    "dubaiinvestmentparkfirst": ["dip", "investment park"], "dubaiinvestmentparksecond": ["investment park second", "green community"],
    "dubaiindustrialcity": ["industrial city", "saih shuaib"], "madinathind4": ["madinat hind", "dubai lifestyle"], "alkhairan": ["creek harbour"],
}

def area_district(area):
    """slug whose alias appears in the free-text area, or None when unknown."""
    a = (area or "").lower()
    if not a: return None
    best = None
    for slug, al in DISTRICT_ALIASES.items():
        if any(x in a for x in al):
            best = slug if best is None else best
    return best

_DEVNAMES = None
def dev_names():
    """[(dev_key, project name, tokens)] from the site registers and the DLD-attributed transaction projects."""
    global _DEVNAMES
    if _DEVNAMES is not None: return _DEVNAMES
    out = []
    for f in glob.glob(os.path.join(ROOT, "data", "dev_meta", "*_portfolio.json")):
        key = os.path.basename(f)[:-len("_portfolio.json")]
        for pr in json.load(open(f, encoding="utf-8")).get("properties", []):
            out.append((key, pr["name"], toks(pr["name"]), pr.get("area") or (pr.get("facts") or {}).get("location")))
    dna = os.path.join(ROOT, "data", "dev_meta", "developer_dna.json")
    if os.path.exists(dna):
        for name, d in json.load(open(dna, encoding="utf-8")).get("developers", {}).items():
            key = DEV_KEY.get(name)
            for t in d.get("tx_2026", {}).get("projects", []):
                if key and not t.get("portfolio_unmatched"): out.append((key, t["project"], toks(t["project"]), t.get("area")))
            for p in d.get("dld_projects_2026", []):
                if key: out.append((key, p["project"], toks(p["project"]), p.get("area")))
    _DEVNAMES = [x for x in out if len(x[2]) >= 1]
    return _DEVNAMES


_PD = None
def project_districts():
    """(dev_key, normalised project) -> set of district slugs named by ANY register/DLD row of that project (plus projfacts DLD area)."""
    global _PD
    if _PD is not None: return _PD
    _PD = {}
    for key, proj, b, area in dev_names():
        d = area_district(area)
        if d: _PD.setdefault((key, " ".join(b)), set()).add(d)
    pf = os.path.join(ROOT, "data", "board", "projfacts.json")
    if os.path.exists(pf):
        for rec in json.load(open(pf, encoding="utf-8")).get("projects", {}).values():
            d = area_district((rec.get("dld") or {}).get("dld_area") or rec.get("area"))
            if not d: continue
            for al in set(rec.get("aliases", [])) | {rec.get("name", "")}:
                _PD.setdefault((rec["dev"], " ".join(toks(al))), set()).add(d)
    return _PD

def dev_for(name, slug=None):
    """Match a footprint name to a developer project: identical token sets, or one contained in the other with >= 2 shared tokens.
    A project whose stated area belongs to a DIFFERENT district is never matched here. Returns (dev_key, project) or None."""
    a = toks(name)
    if not a: return None
    A = set(a); best = None
    for key, proj, b, area in dev_names():
        B = set(b)
        if not B: continue
        known = project_districts().get((key, " ".join(b)), set())   # every district any row of this project points at
        if slug and known and slug not in known: continue
        shared = A & B
        if A == B: return (key, proj)
        if (A <= B or B <= A) and len(shared) >= 2:          # one shared word is not evidence ("Symphony Business Bay" is not Imtiaz's Symphony)
            best = best or (key, proj)
    return best

# ---------------- per-building GLB mesh map
def mesh_map(slug, blds):
    # v3 (textured) exports name every node "b<i>_<class>_s<status>", so the footprint index is exact —
    # no centre matching, and it survives the quantised/meshopt pack the viewer actually loads.
    f3 = os.path.join(CE, "_glb", f"sky_{slug}_v3_0.glb")
    if os.path.exists(f3):
        b = open(f3, "rb").read(); ln = struct.unpack_from("<I", b, 12)[0]; j = json.loads(b[20:20 + ln])
        out = {}
        for n in j.get("nodes", []):
            m = re.match(r"^b(\d+)_", n.get("name") or "")
            if m and n.get("mesh") is not None: out[int(m.group(1))] = n["mesh"]
        if out: return out
    f = next((x for x in (os.path.join(CE, "_glb", f"sky_{slug}_v3_0.glb"), os.path.join(CE, "_glb", f"sky_{slug}_v2_0.glb")) if os.path.exists(x)), "")   # the shipped export is v3 where it exists; mesh order differs between them
    if not os.path.exists(f): return {}
    b = open(f, "rb").read(); ln = struct.unpack_from("<I", b, 12)[0]; j = json.loads(b[20:20 + ln]); acc = j["accessors"]
    out = {}
    for mi, m in enumerate(j["meshes"]):
        mins = [acc[p["attributes"]["POSITION"]]["min"] for p in m["primitives"]]; maxs = [acc[p["attributes"]["POSITION"]]["max"] for p in m["primitives"]]
        cx = (min(x[0] for x in mins) + max(x[0] for x in maxs)) / 2; cz = (min(x[2] for x in mins) + max(x[2] for x in maxs)) / 2
        best = min(blds, key=lambda q: (q["x"] - cx) ** 2 + (q["z"] - cz) ** 2)
        if math.hypot(best["x"] - cx, best["z"] - cz) <= 12: out[best["i"]] = mi
    return out


def facade_points(ring):
    """Oriented bbox of the footprint ring (EPSG:32640 metres): returns (bearing_deg, [N,E,S,W] midpoints 1.5 m outside, as [x, z])."""
    pts = [TO_UTM(px, py) for px, py in ring]
    # longest edge bearing
    best = (0.0, 0.0)
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]; L = math.hypot(x2 - x1, y2 - y1)
        if L > best[0]: best = (L, math.degrees(math.atan2(x2 - x1, y2 - y1)) % 180.0)
    th = math.radians(best[1]); ux, uy = math.sin(th), math.cos(th); vx, vy = -uy, ux        # u along the long edge, v across
    cx = sum(x for x, _ in pts) / len(pts); cy = sum(y for _, y in pts) / len(pts)
    du = [(x - cx) * ux + (y - cy) * uy for x, y in pts]; dv = [(x - cx) * vx + (y - cy) * vy for x, y in pts]
    hu, hv = max(du), max(dv); lu, lv = min(du), min(dv)
    mids = {"+u": (cx + (hu + 1.5) * ux, cy + (hu + 1.5) * uy), "-u": (cx + (lu - 1.5) * ux, cy + (lu - 1.5) * uy),
            "+v": (cx + (hv + 1.5) * vx, cy + (hv + 1.5) * vy), "-v": (cx + (lv - 1.5) * vx, cy + (lv - 1.5) * vy)}
    # label each midpoint by the compass quadrant of its outward normal
    out = {}
    for k, (mx, my) in mids.items():
        nx, ny = mx - cx, my - cy; b = math.degrees(math.atan2(nx, ny)) % 360
        q = "N" if b < 45 or b >= 315 else "E" if b < 135 else "S" if b < 225 else "W"
        if q not in out or math.hypot(nx, ny) < 0: out[q] = [round(mx, 1), round(-my, 1)]
    return round(best[1], 1), [out.get(q) for q in ("N", "E", "S", "W")]

LANDMARKS = [("Burj Khalifa", 55.27419, 25.19720, 828), ("Dubai Mall", 55.27960, 25.19770, 40), ("Downtown Dubai", 55.2760, 25.1930, 120),
             ("Dubai Canal", 55.2640, 25.1880, 0), ("Dubai Canal (Safa)", 55.2470, 25.1850, 0), ("Dubai Creek", 55.3300, 25.2200, 0),
             ("Arabian Gulf (Jumeirah)", 55.2380, 25.2070, 0), ("Arabian Gulf (Marina)", 55.1330, 25.0850, 0), ("Burj Al Arab", 55.1853, 25.1412, 321),
             ("Palm Jumeirah", 55.1380, 25.1120, 30), ("DIFC", 55.2820, 25.2120, 200), ("Museum of the Future", 55.2810, 25.2190, 77),
             ("Ras Al Khor Sanctuary", 55.3250, 25.1900, 0), ("Meydan Racecourse", 55.3040, 25.1560, 30), ("Dubai Hills", 55.2440, 25.1150, 20)]

def write_landmarks():
    f = os.path.join(OUT, "landmarks.json")
    if os.path.exists(f): return
    rows = []
    for name, lon, lat, h in LANDMARKS:
        e, n = TO_UTM(lon, lat); rows.append({"name": name, "lon": lon, "lat": lat, "x": round(e, 1), "z": round(-n, 1), "h": h})
    json.dump({"crs": "EPSG:32640 (x = easting, z = -northing)", "items": rows}, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

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
        # a sourced height only wins if it is credible: Wikidata carries feet mislabelled as metres (Paramount 886 "m" is 886 ft),
        # so reject anything more than 1.6x the footprint's own height when that height already came from a survey source,
        # and reject anything a floor count cannot support (3.6 m per floor is generous for a tower)
        if hit and w.get("height_m"):
            cand = float(w["height_m"]); cur = float(hit["h"] or 0); fl = w.get("floors") or 0
            plaus = (not fl or cand <= fl * 3.6 + 12) and (cur < 20 or cand <= cur * 1.6)
            if plaus and cand > cur: hit["h"] = cand
            elif fl and fl * 3.4 > cur: hit["h"] = round(fl * 3.4, 1)                       # fall back to floors x 3.4
    # DLD project bindings (Business Bay so far)
    for b in blds:
        bb = bind.get(b["id"]) or bind.get(str(b["i"]))
        if bb and not b["name"]: b["name"], b["src"] = bb.get("project") or bb.get("name"), "dld"
    # Overture Maps buildings (overture_names.py -> overture_<slug>.json, keyed by feature index): name fills a footprint that is still
    # unnamed; measured height replaces the 3.2 m/level estimate when larger; num_floors fills a missing level count
    ovf = os.path.join(OUT, f"overture_{slug}.json"); ov_h = 0
    if os.path.exists(ovf):
        ov = json.load(open(ovf, encoding="utf-8"))
        for b in blds:
            o = ov.get(str(b["i"]))
            if not o: continue
            if o.get("name") and not b["name"]: b["name"], b["src"] = o["name"].strip(), "overture"
            if o.get("height") and float(o["height"]) > b["h"]: b["h"] = float(o["height"]); ov_h += 1
            if o.get("num_floors") and not b["levels"]: b["levels"] = str(o["num_floors"])
    # scene coordinates: the GLB is in EPSG:32640 metres, y-up, z = -northing, ABSOLUTE (ctx.glb_center = scene centre, same units)
    for b in blds:
        e, n = TO_UTM(b["lon"], b["lat"]); b["x"] = round(e, 1); b["z"] = round(-n, 1)
    # developer tagging: (1) geocode-and-snap bindings (bind_registers.py -> data/names/dev_bindings.json), which also NAME an unnamed
    # footprint after the project; (2) name matching against the site registers + DLD-attributed project names (developer_dna.json)
    dbf = os.path.join(OUT, "dev_bindings.json")
    if os.path.exists(dbf):
        _db = json.load(open(dbf, encoding="utf-8"))
        # 15 Sep 2026 (digital thread Q9): a binding a person rejected (rejected_by_hand) never tags or names a footprint, even while an
        # older bind_registers run still carries it in "bindings"
        _rej = {(r.get("district"), str(r.get("i")), str(r.get("project") or "").strip().upper()) for r in (_db.get("rejected_by_hand") or [])}
        for k, v in (_db.get("bindings", {}).get(slug, {})).items():
            if (slug, str(k), str(v.get("project") or "").strip().upper()) in _rej: continue
            b = next((x for x in blds if x["i"] == int(k)), None)
            if not b: continue
            nm = dev_for(b["name"], slug) if b["name"] else None
            if nm and nm[0] != v["dev"] and set(toks(b["name"])) == set(toks(nm[1])): continue   # the map name IS another developer's project (Residence 110 = Select, not ANWA)
            b["dev"], b["dev_project"] = v["dev"], v["project"]
            if not b["name"] or re.search(r"[؀-ۿ]", b["name"]): b["name"], b["src"] = v["project"], "register"
    for b in blds:
        if b["name"] and not b.get("dev"):
            hit = dev_for(b["name"], slug)
            if hit: b["dev"], b["dev_project"] = hit
    # per-building GLB (sky_<slug>_v2_0.glb): map each mesh to its footprint by centre distance, so the viewer can colour/tag meshes
    mesh_of = mesh_map(slug, blds)
    for b in blds:
        if b["i"] in mesh_of: b["mesh"] = mesh_of[b["i"]]
    named = [b for b in blds if b["name"]]
    hs = sorted(b["h"] for b in blds); tall_cut = hs[int(len(hs) * 0.7)] if hs else 0
    tall = [b for b in blds if b["h"] >= tall_cut and b["h"] > 12]; tall_named = [b for b in tall if b["name"]]
    TO_LL = pyproj.Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform
    for b in named:
        try:
            b["bear"], b["fm"] = facade_points(b["ring"])
            # lon/lat of each facade midpoint so the photoreal view can stand exactly there
            b["fm_ll"] = [[round(v, 6) for v in TO_LL(p[0], -p[1])] if p else None for p in (b["fm"] or [None] * 4)]
        except Exception: b["bear"], b["fm"], b["fm_ll"] = None, None, None
    write_landmarks()
    anchors = [{"id": b["id"], "i": b["i"], "mesh": b.get("mesh"), "name": b["name"], "source": b["src"], "dev": b.get("dev"), "dev_project": b.get("dev_project"), "lon": round(b["lon"], 6), "lat": round(b["lat"], 6), "x": b.get("x"), "z": b.get("z"), "h": round(b["h"], 1), "levels": b["levels"], "bear": b.get("bear"), "fm": b.get("fm"), "fm_ll": b.get("fm_ll")} for b in named]
    # developer buildings are the point of the exercise: keep them even when the map had no name (the register name becomes the label)
    devmeshes = [{"i": b["i"], "mesh": b.get("mesh"), "dev": b["dev"], "name": b.get("dev_project")} for b in blds if b.get("dev") and not b["name"]]
    anchors.sort(key=lambda a: -a["h"])
    json.dump({"district": slug, "buildings": len(blds), "named": len(named), "tall": len(tall), "tall_named": len(tall_named), "tall_cut_m": round(tall_cut, 1),
               "sources": {s: sum(1 for a in anchors if a["source"] == s) for s in ("osm", "osm_en", "wikidata", "dld", "overture", "portfolio")}, "overture_heights": ov_h, "glb_center": ctx.get("glb_center"),
               "per_building_glb": any(os.path.exists(os.path.join(CE, "_glb", f"sky_{slug}_{v}_0.glb")) for v in ("v3", "v2")),
               "fps": [[b["i"], b.get("x"), b.get("z"), round(b["h"], 1)] for b in blds],   "developers": sorted({a["dev"] for a in anchors if a.get("dev")}), "dev_tagged": sum(1 for a in anchors if a.get("dev")), "anchors": anchors},
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
