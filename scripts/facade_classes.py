"""Facade material classes per building — the real-world input to rules/najma_v2.cga.

Sources, in priority order, matched onto data/ce/<slug>/buildings.geojson feature indices:
  1. OpenStreetMap tags on the footprint (building:material, building:facade:material,
     building:cladding, building:colour, roof:shape, building=*), fetched once per district
     via Overpass `out tags center` and matched by centroid (<= 15 m) the way
     scripts/osm_names_en.py does  -> data/names/osm_facade_<slug>.json
  2. Overture facade_color / facade_material / roof_shape from data/names/overture_<slug>.json
     when that file exists (another lane produces it; absent = skipped, never waited for).
  3. Defaults by height, district and name: towers > 100 m in the glass districts (Marina,
     Business Bay, Downtown) = glass, mid-rise = concrete / render, low = render, villas = render.

Classes (7): glassblue, glassclear, glassbronze, stone, render, concrete, brick.
Variant  = feature index % 3 (deterministic — a re-export gives the same look).

Output: data/ce/<slug>/facade_v2.json   {"buildings": {"<idx>": {"class","variant","source",...}}}
        data/ce/facade_classes.json      class catalogue (suggested tileable texture per class,
                                         in-family palette) + per-district class counts
Usage:  python scripts/facade_classes.py businessbay [burjkhalifa palmjumeirah ...]
        python scripts/facade_classes.py --all
"""
import colorsys, datetime, json, math, os, re, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); os.makedirs(NAMES, exist_ok=True)
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
TAGS = ["building:colour", "building:material", "building:facade:material", "building:cladding", "roof:shape", "roof:colour",
        "roof:material", "building:levels", "height", "building", "start_date", "architect"]
GLASS_DISTRICTS = {"dubaimarina", "businessbay", "burjkhalifa", "dubaimaritimecity", "meydanone", "sobhaheartland"}
CLASSES = ["glassblue", "glassclear", "glassbronze", "stone", "render", "concrete", "brick"]

# class catalogue — texture suggestions for a later atlas (tileable, one floor module high where it matters)
CATALOGUE = {
    "glassblue":   {"label": "Curtain wall, blue-tinted glass", "panel": "large panels, mullions 1.6/1.8/2.1 m, spandrel band per floor",
                    "texture": "glass_curtainwall_blue", "tile_m": [1.8, 3.4], "notes": "reflective vision glass + dark spandrel; the Dubai tower default"},
    "glassclear":  {"label": "Curtain wall, clear / grey glass", "panel": "large panels, mullions 1.6/1.8/2.1 m",
                    "texture": "glass_curtainwall_clear", "tile_m": [1.8, 3.4], "notes": "neutral low-iron or grey-tinted glazing"},
    "glassbronze": {"label": "Curtain wall, bronze glass", "panel": "large panels, mullions 1.6/1.8/2.1 m",
                    "texture": "glass_curtainwall_bronze", "tile_m": [1.8, 3.4], "notes": "warm bronze / gold reflective glazing (1980s-2000s Gulf towers)"},
    "stone":       {"label": "Stone / limestone cladding", "panel": "punched windows 1.2 x 1.6 m per 3.4 m bay",
                    "texture": "stone_limestone_ashlar", "tile_m": [3.4, 3.4], "notes": "beige / cream ashlar, sandstone, travertine"},
    "render":      {"label": "White / cream render", "panel": "punched windows 1.2 x 1.6 m per 3.4 m bay",
                    "texture": "plaster_render_white", "tile_m": [3.4, 3.4], "notes": "painted plaster; villas, low-rise, older apartment blocks"},
    "concrete":    {"label": "Concrete / precast panel", "panel": "punched windows 1.2 x 1.6 m per 3.4 m bay",
                    "texture": "concrete_precast_panel", "tile_m": [3.4, 3.4], "notes": "grey precast or fair-faced concrete; also buildings under construction"},
    "brick":       {"label": "Brick / terracotta", "panel": "punched windows 1.2 x 1.6 m per 3.4 m bay",
                    "texture": "brick_terracotta_running_bond", "tile_m": [3.4, 3.4], "notes": "rare in Dubai; kept for completeness"},
}
# in-family palette used by najma_v2.cga (status -> role -> hex); classification-safe, see rule header
PALETTE = {
    "existing":     {"base": "#39434F", "glassblue": "#485665", "glassclear": "#555C64", "glassbronze": "#494F55", "stone": "#515656", "render": "#545A61",
                     "concrete": "#4F5257", "brick": "#3B4858", "slab": "#303943", "window": "#313C49", "crown": "#363E47", "roof": "#323B46"},
    "construction": {"base": "#3E8A7E", "glassblue": "#3EA292", "glassclear": "#5F948C", "glassbronze": "#5D857E", "stone": "#688C87", "render": "#67928B",
                     "concrete": "#67837F", "brick": "#349788", "slab": "#35756B", "window": "#2F8175", "crown": "#427A71", "roof": "#37796F"},
    "pipeline":     {"base": "#C5A56A", "glassblue": "#DBB265", "glassclear": "#C5AF86", "glassbronze": "#B7A788", "stone": "#BCAC90", "render": "#C1AF8E",
                     "concrete": "#B3A792", "brick": "#D5AB5D", "slab": "#A78C5A", "window": "#B99656", "crown": "#AE966B", "roof": "#AD915D"},
}
NAMED = {"white": "#ffffff", "silver": "#c0c0c0", "grey": "#808080", "gray": "#808080", "black": "#202020", "beige": "#f5f5dc", "cream": "#fffdd0",
         "tan": "#d2b48c", "sand": "#e2ca76", "brown": "#8b5a2b", "bronze": "#cd7f32", "gold": "#d4af37", "blue": "#4a7fb5", "lightblue": "#9ec5e8",
         "green": "#4f8a5b", "red": "#b03a2e", "yellow": "#e6c84c", "orange": "#e08a3c", "pink": "#e8a0b0"}


# ------------------------------------------------------------------ geometry helpers (same as osm_names_en.py)
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
            r = urllib.request.urlopen(urllib.request.Request(m, data=urllib.parse.urlencode({"data": q}).encode(),
                                                              headers={"User-Agent": "najma-facade/1.0 (contact@digitalabbot.io)"}), timeout=150)
            return json.loads(r.read())
        except Exception as e:
            print(f"  overpass {m.split('/')[2]}: {str(e)[:60]} — next mirror"); last = e; time.sleep(8 + 4 * i)
    raise last


def fetch_osm_facade(slug, feats):
    """OSM facade-relevant tags for the district, matched by centroid. Cached in data/names."""
    out = os.path.join(NAMES, f"osm_facade_{slug}.json")
    if os.path.exists(out):
        return json.load(open(out, encoding="utf-8"))
    b = bbox_of(feats)
    q = f'[out:json][timeout:150];(way["building"]({b[0]},{b[1]},{b[2]},{b[3]});relation["building"]({b[0]},{b[1]},{b[2]},{b[3]}););out tags center;'
    els = overpass(q).get("elements", [])
    cents = [centroid(f) for f in feats]; res = {}
    for e in els:
        c = e.get("center"); t = e.get("tags", {})
        if not c: continue
        keep = {k: t[k] for k in TAGS if k in t}
        if not any(k in keep for k in ("building:colour", "building:material", "roof:shape", "roof:colour", "building:facade:material", "building:cladding", "start_date")):
            continue
        j, best = None, 1e9
        for i, (cx, cy) in enumerate(cents):
            dd = metres(c["lon"], c["lat"], cx, cy)
            if dd < best: best, j = dd, i
        if j is not None and best <= 15 and (str(j) not in res or best < res[str(j)]["dist_m"]):
            keep.update({"dist_m": round(best, 1), "osm_id": e.get("id"), "osm_type": e.get("type")}); res[str(j)] = keep
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"  osm facade tags: {len(els)} elements, {len(res)} matched -> {os.path.relpath(out, ROOT)}")
    time.sleep(6)
    return res


def load_overture(slug, feats):
    """Overture building facade fields if data/names/overture_<slug>.json exists. Accepts a dict keyed by
    feature index, or a list of records carrying idx/index/feature or lon/lat (matched by centroid)."""
    p = os.path.join(NAMES, f"overture_{slug}.json")
    if not os.path.exists(p):
        return {}
    try:
        raw = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("  overture file unreadable:", e); return {}
    recs = raw.get("buildings", raw) if isinstance(raw, dict) else raw
    out = {}
    if isinstance(recs, dict):
        for k, v in recs.items():
            if str(k).isdigit() and isinstance(v, dict): out[str(k)] = v
        return out
    cents = [centroid(f) for f in feats]
    for r in recs:
        if not isinstance(r, dict): continue
        k = next((r[x] for x in ("idx", "index", "feature") if x in r), None)
        if k is None and "lon" in r and "lat" in r:
            j, best = None, 1e9
            for i, (cx, cy) in enumerate(cents):
                dd = metres(r["lon"], r["lat"], cx, cy)
                if dd < best: best, j = dd, i
            k = j if best <= 15 else None
        if k is not None: out[str(k)] = r
    return out


# ------------------------------------------------------------------ classification
def parse_colour(s):
    if not s: return None
    s = str(s).strip().lower().replace(" ", "")
    if s in NAMED: s = NAMED[s]
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if not m:
        m3 = re.fullmatch(r"#?([0-9a-f]{3})", s)
        if not m3: return None
        s = "".join(ch * 2 for ch in m3.group(1))
    else:
        s = m.group(1)
    r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    return {"hex": "#" + s, "h": h * 360, "l": l, "s": sat}

def norm_material(s):
    s = (s or "").strip().lower()
    if not s: return None
    if any(k in s for k in ("glass", "mirror", "curtain")): return "glass"
    if any(k in s for k in ("steel", "metal", "alumin", "acm", "cladding_panel", "panel")): return "metal"
    if any(k in s for k in ("sandstone", "limestone", "stone", "marble", "travertine", "granite")): return "stone"
    if any(k in s for k in ("plaster", "render", "stucco", "paint", "gypsum")): return "render"
    if any(k in s for k in ("concrete", "cement", "precast")): return "concrete"
    if any(k in s for k in ("brick", "terracotta", "tile")): return "brick"
    if s.startswith("#"): return None
    return None

def glass_tint(col):
    """Glass tint from a colour: blue-ish hue -> glassblue, warm -> glassbronze, else glassclear."""
    if not col: return "glassblue"
    if col["s"] >= 0.12 and 170 <= col["h"] <= 260: return "glassblue"
    if col["s"] >= 0.12 and 15 <= col["h"] <= 60: return "glassbronze"
    return "glassclear"

def opaque_from_colour(col):
    """Opaque class from a colour alone: light warm -> stone, light neutral -> render, mid/dark -> concrete, reds -> brick."""
    if col["s"] >= 0.25 and (col["h"] <= 25 or col["h"] >= 340) and col["l"] < 0.6: return "brick"
    if col["l"] >= 0.6 and col["s"] >= 0.10 and 20 <= col["h"] <= 60: return "stone"
    if col["l"] >= 0.72: return "render"
    return "concrete"

def default_class(slug, h, idx, name):
    n = (name or "").lower()
    if any(k in n for k in ("villa", "townhouse", "mosque", "masjid", "school", "clinic")): return "render", "default:name"
    if h > 100 and slug in GLASS_DISTRICTS:
        return ["glassblue", "glassclear", "glassblue", "glassclear", "glassbronze"][idx % 5], "default:height>100,glass district"
    if h > 100:
        return ["glassblue", "concrete", "glassclear"][idx % 3], "default:height>100"
    if h > 40:
        return (["concrete", "glassclear", "concrete", "render"] if slug in GLASS_DISTRICTS else ["concrete", "render"])[idx % (4 if slug in GLASS_DISTRICTS else 2)], "default:height>40"
    if h >= 20:
        return ["render", "concrete", "render", "stone"][idx % 4], "default:height>=20"
    return ("stone" if idx % 6 == 0 else "render"), "default:low"

def classify(slug, idx, props, osm, ovt):
    h = float(props.get("bHeight") or 0); name = props.get("name") or props.get("bname") or ""
    detail = {}
    # 1. OSM material / colour
    mat = norm_material(osm.get("building:facade:material")) or norm_material(osm.get("building:cladding")) or norm_material(osm.get("building:material"))
    col = parse_colour(osm.get("building:colour")) or (parse_colour(osm.get("building:facade:material")) if str(osm.get("building:facade:material", "")).startswith("#") else None)
    if mat or col:
        detail["osm"] = {k: osm[k] for k in osm if k not in ("dist_m", "osm_id", "osm_type")}
    # 2. Overture
    if not (mat or col) and ovt:
        mat = norm_material(ovt.get("facade_material")); col = parse_colour(ovt.get("facade_color"))
        if mat or col: detail["overture"] = {k: ovt[k] for k in ("facade_material", "facade_color", "roof_shape") if k in ovt}
    src = None; cls = None
    if mat in ("glass", "metal"):
        cls, src = glass_tint(col), ("osm" if "osm" in detail else "overture") + ":material"
    elif mat in ("stone", "render", "concrete", "brick"):
        cls, src = mat, ("osm" if "osm" in detail else "overture") + ":material"
        if mat == "stone" and col and col["l"] >= 0.85 and col["s"] < 0.08: cls = "render"
    elif col:
        cls, src = opaque_from_colour(col), ("osm" if "osm" in detail else "overture") + ":colour"
        if h > 100 and cls in ("render", "concrete") and col["l"] < 0.5: cls, src = "glassclear", src + ",dark tower->glass"
    if cls is None and ovt.get("class"):      # Overture building class as a use hint (no colour / material given)
        oc = str(ovt["class"]).lower()
        if oc in ("office", "hotel", "commercial") and h > 40:
            cls, src = ["glassblue", "glassclear", "glassblue"][idx % 3], "overture:class=" + oc
        elif oc in ("kiosk", "service", "industrial", "warehouse", "garage", "parking"):
            cls, src = "concrete", "overture:class=" + oc
        elif oc in ("house", "detached", "semidetached_house", "terrace", "villa", "bungalow"):
            cls, src = "render", "overture:class=" + oc
        if cls: detail["overture"] = {k: ovt[k] for k in ("class", "num_floors", "height", "roof_shape") if ovt.get(k) is not None}
    if cls is None:
        cls, src = default_class(slug, h, idx, name)
    rec = {"class": cls, "variant": idx % 3, "source": src, "h": h}
    if name: rec["name"] = name
    if osm.get("building") in ("construction",): rec["osm_building"] = "construction"
    if osm.get("roof:shape"): rec["roof_shape"] = osm["roof:shape"]
    if osm.get("start_date"): rec["start_date"] = osm["start_date"]
    rec.update(detail)
    return rec


def run(slug):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj):
        print(slug, "no buildings.geojson"); return None
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    print(f"== {slug}: {len(feats)} footprints")
    osm = fetch_osm_facade(slug, feats)
    ovt = load_overture(slug, feats)
    if ovt: print(f"  overture records matched: {len(ovt)}")
    bld = {}
    for i, f in enumerate(feats):
        bld[str(i)] = classify(slug, i, f["properties"], osm.get(str(i), {}), ovt.get(str(i), {}))
    counts = {c: sum(1 for v in bld.values() if v["class"] == c) for c in CLASSES}
    srcs = {}
    for v in bld.values():
        k = v["source"].split(":")[0]; srcs[k] = srcs.get(k, 0) + 1
    out = {"district": slug, "generated": datetime.datetime.now().isoformat(timespec="seconds"), "n": len(feats), "counts": counts,
           "sources": srcs, "osm_construction": sum(1 for v in bld.values() if v.get("osm_building") == "construction"), "buildings": bld}
    json.dump(out, open(os.path.join(CE, slug, "facade_v2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"  classes: {counts}\n  sources: {srcs}  (OSM building=construction on {out['osm_construction']})")
    update_catalogue(slug, counts, srcs, len(feats))
    return out


def update_catalogue(slug, counts, srcs, n):
    p = os.path.join(CE, "facade_classes.json")
    cat = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    cat["classes"] = CATALOGUE
    cat["palette"] = PALETTE
    cat["rule"] = "rules/najma_v2.cga"
    cat["variants"] = {"rule": "feature index % 3", "spandrel_ratio": [0.30, 0.36, 0.42], "mullion_spacing_m": [1.6, 1.8, 2.1]}
    cat["shape_name"] = "b<feature index>_<class>"
    cat.setdefault("districts", {})[slug] = {"n": n, "counts": counts, "sources": srcs, "generated": datetime.datetime.now().isoformat(timespec="seconds")}
    cat["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    json.dump(cat, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        args = [d for d in sorted(os.listdir(CE)) if os.path.exists(os.path.join(CE, d, "buildings.geojson"))]
    for s in args or ["businessbay"]:
        run(s)
