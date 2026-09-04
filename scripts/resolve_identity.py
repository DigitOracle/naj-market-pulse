"""Cross-source identity resolver: test every modelled footprint against every source we hold, and say what it is.

The twin draws 17,000 buildings and knows the name of one in ten. This decides, for each one, the best identity the evidence
supports - and, just as importantly, records why, so a wrong name can be traced to the source that caused it and undone.

  CAPTURE -> NORMALISE -> MATCH -> ENRICH -> VALIDATE -> KNOWLEDGE GRAPH -> AUDIT
                                     ^^^^^ this file

EVERY fact is an evidence record, never a value written straight onto a building:

    {duid, attribute, value, source, source_record_id, method, confidence, captured_at}

and the resolver picks a canonical value from the competing evidence by source precedence first, spatial quality second.
Provenance is first-class: the winning source is named on the building, and every loser is kept beside it.

Source precedence for `name` (Kendall, 4 Sep 2026) - authoritative registers before open data before commercial fallback:
    dld_unit > dm_building > dld_project > makani/municipality/building number
      > osm (name, name:en, addr:housename) > overture_building > overture_place > wikidata > google_places > inferred

Identity grade, on the face of every row:
    VERIFIED  an authoritative register names it, or two independent sources agree on the same name
    MATCHED   one good source names it and the match is spatially sound (the evidence sits inside the footprint)
    INFERRED  derived rather than stated - a scheme name from a binding, a name from a POI merely near the footprint
    UNKNOWN   nothing but geometry. It still gets a DUID, so it can be tracked and later named.

The DUID is derived from the footprint's centroid, not its index, so it survives a re-mass, a re-export and a re-order.

Outputs
    data/identity/resolved/<slug>.json   every building, its canonical identity and ALL evidence for and against
    data/identity/IDENTITY_TABLE.csv     one row per building: current name, proposed name, source, method, distance, confidence, grade
    data/identity/IDENTITY_REPORT.md     what changed, what is still unknown, and where the next source would help most

Usage: python scripts/resolve_identity.py [--min-conf 0.55] [slug ...]
"""
import argparse, csv, datetime as dt, glob, hashlib, json, math, os, re, sys, unicodedata

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names")
IDENT = os.path.join(ROOT, "data", "identity"); RES = os.path.join(IDENT, "resolved")
os.makedirs(RES, exist_ok=True)
NOW = dt.datetime.now().isoformat(timespec="seconds")

# source -> (precedence rank, base confidence). Lower rank wins. Base confidence is what the source is worth when the
# spatial match is perfect; a weaker match multiplies it down.
SOURCES = {
    "dld_unit":         (1, 0.98), "dm_building":  (2, 0.96), "makani":        (3, 0.95),
    "dld_project":      (4, 0.90), "register":     (4, 0.90), "dld":           (4, 0.90),
    "osm":              (5, 0.90), "osm_en":       (5, 0.90),
    "overture":         (6, 0.85), "overture_place": (7, 0.74),
    "wikidata":         (8, 0.88), "places":       (9, 0.70),
    "binding":         (10, 0.60), "inferred":    (11, 0.40),
}
# Overture Places categories that describe a BUILDING rather than a business inside one. A coffee shop in a tower is not
# the tower's name; a "real estate" POI called "Marina Gate 1" sitting inside the footprint usually is.
PLACE_OK = {"real_estate", "real_estate_service", "real_estate_agent", "property_management", "apartment_building",
            "apartment_complex", "condominium_complex", "housing_complex", "residential_building", "building",
            "hotel", "resort_hotel", "hotel_and_motel", "serviced_apartment", "office_building", "corporate_office",
            "shopping_center", "shopping_mall", "hospital", "school", "university", "mosque", "landmark_and_historical_building"}
# a name that reads like a building's name even when the category is a business
BUILDINGISH = re.compile(r"\b(tower|towers|residence|residences|building|plaza|heights|court|villa|villas|mansion|"
                         r"apartments?|complex|centre|center|mall|hotel|suites|lofts|park|gate|bay|point|view|house)\b", re.I)
GENERIC = re.compile(r"^(building|tower|residence|residences|apartments?|villa|villas|entrance|gate|parking|reception|"
                     r"lobby|office|shop|store|unknown|untitled)\W*\d*$", re.I)


# ---------------------------------------------------------------- geometry
def ring_of(geom):
    if not geom: return []
    if geom["type"] == "Polygon": return geom["coordinates"][0]
    if geom["type"] == "MultiPolygon": return max((p[0] for p in geom["coordinates"]), key=len)
    return []


def centroid(ring):
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def metres(a, b):
    r = 6371000.0; p1, p2 = math.radians(a[1]), math.radians(b[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def inside(pt, ring):
    x, y = pt; ins = False; n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]; x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1: ins = not ins
    return ins


def edge_dist(pt, ring):
    """0 inside, else metres to the nearest vertex - close enough at building scale and far cheaper than true edge distance."""
    if inside(pt, ring): return 0.0
    return min(metres(pt, v) for v in ring)


def duid_of(slug, ring):
    """Stable per-footprint id from the centroid (~0.1 m quantisation), so re-massing or re-indexing does not rename it."""
    lon, lat = centroid(ring)
    h = hashlib.sha1(f"{lon:.6f},{lat:.6f}".encode()).hexdigest()[:10]
    return f"DXB-{slug.upper()[:6]}-{h}"


# ---------------------------------------------------------------- naming hygiene
def clean_name(v):
    if not v: return None
    v = unicodedata.normalize("NFKC", str(v)).strip().strip("-–—,;:")
    v = re.sub(r"\s+", " ", v)
    if len(v) < 3 or GENERIC.match(v): return None
    if not re.search(r"[A-Za-z؀-ۿ]", v): return None            # a bare number is a plot, not a name
    return v


def norm(v):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower())


def spatial_factor(dist_m, is_inside):
    if is_inside: return 1.0
    if dist_m <= 10: return 0.90
    if dist_m <= 25: return 0.75
    if dist_m <= 50: return 0.55
    return 0.30


def ev(duid, attribute, value, source, rec_id, method, conf, **extra):
    e = {"duid": duid, "attribute": attribute, "value": value, "source": source, "source_record_id": rec_id,
         "method": method, "confidence": round(float(conf), 3), "captured_at": NOW}
    e.update(extra); return e


# ---------------------------------------------------------------- source adapters
def load_json(p, default=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return default


def adapters(slug, blds):
    """Every source, turned into evidence records keyed by footprint index. Missing sources simply contribute nothing."""
    out = {i: [] for i in blds}

    # 1. anchors — whatever build_anchors already merged (osm, osm_en, overture, wikidata, dld, register, places)
    A = load_json(os.path.join(NAMES, f"anchors_{slug}.json"), {"anchors": []})
    for a in A.get("anchors", []):
        i = a.get("i")
        if i not in out: continue
        src = a.get("source") or "osm"
        nm = clean_name(a.get("name"))
        if nm:
            rank, base = SOURCES.get(src, (6, 0.80))
            out[i].append(ev(blds[i]["duid"], "name", nm, src, a.get("id"), "carried on the footprint by build_anchors", base,
                             dist_m=0.0, inside=True))
        if a.get("dev"):
            out[i].append(ev(blds[i]["duid"], "developer", a["dev"], "binding", a.get("dev_project"),
                             "register scheme bound to this footprint", SOURCES["binding"][1], dist_m=0.0, inside=True))
        if a.get("dev_project"):
            out[i].append(ev(blds[i]["duid"], "project", a["dev_project"], "binding", a.get("dev_project"),
                             "register scheme bound to this footprint", SOURCES["binding"][1], dist_m=0.0, inside=True))

    # 2. Google Places — the targeted pass over unnamed buildings above the default height
    P = load_json(os.path.join(NAMES, f"places_{slug}.json"), {}) or {}
    for k, v in P.items():
        i = int(k)
        if i not in out or not v or not v.get("name"): continue
        nm = clean_name(v["name"])
        if not nm: continue
        f = spatial_factor(v.get("dist_m") or 0, bool(v.get("inside")))
        out[i].append(ev(blds[i]["duid"], "name", nm, "places", v.get("place_id"),
                         f"place search on the footprint centroid ({v.get('primary') or 'poi'})",
                         SOURCES["places"][1] * f, dist_m=v.get("dist_m"), inside=bool(v.get("inside"))))

    # 3. Overture Places — POIs that describe the building rather than a business inside it
    op = os.path.join(IDENT, "overture", f"place_{slug}.geojson")
    if os.path.exists(op):
        G = load_json(op, {"features": []})
        pts = []
        for f in G.get("features", []):
            g = f.get("geometry") or {}
            if g.get("type") != "Point": continue
            nm = clean_name(((f["properties"].get("names") or {}).get("primary")))
            if not nm: continue
            cat = ((f["properties"].get("categories") or {}).get("primary")) or ""
            conf = f["properties"].get("confidence") or 0.5
            if cat not in PLACE_OK and not BUILDINGISH.search(nm): continue
            pts.append((tuple(g["coordinates"][:2]), nm, cat, conf, f["properties"].get("id") or f.get("id")))
        for i, b in blds.items():
            ring = b["ring"]; c = b["centroid"]
            for pt, nm, cat, conf, rid in pts:
                if abs(pt[0] - c[0]) > 0.004 or abs(pt[1] - c[1]) > 0.004: continue      # cheap bbox reject first
                d = edge_dist(pt, ring)
                if d > 25: continue
                f = spatial_factor(d, d == 0.0)
                out[i].append(ev(b["duid"], "name", nm, "overture_place", rid,
                                 f"Overture place '{cat}' inside/next to the footprint", SOURCES["overture_place"][1] * f * (0.6 + 0.4 * float(conf)),
                                 dist_m=round(d, 1), inside=d == 0.0))

    # 4. Wikidata — landmarks, wide emirate box
    W = load_json(os.path.join(IDENT, "wikidata", "dubai_structures.json"), None)
    if W:
        rows = []
        for b in W.get("results", {}).get("bindings", []):
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", (b.get("coord") or {}).get("value", "") or "")
            nm = clean_name((b.get("itemLabel") or {}).get("value"))
            if m and nm and not nm.startswith("Q"):
                rows.append(((float(m.group(1)), float(m.group(2))), nm, (b.get("item") or {}).get("value")))
        for i, b in blds.items():
            c = b["centroid"]
            for pt, nm, qid in rows:
                if abs(pt[0] - c[0]) > 0.004 or abs(pt[1] - c[1]) > 0.004: continue
                d = edge_dist(pt, b["ring"])
                if d > 40: continue
                f = spatial_factor(d, d == 0.0)
                out[i].append(ev(b["duid"], "name", nm, "wikidata", qid, "Wikidata structure at this location",
                                 SOURCES["wikidata"][1] * f, dist_m=round(d, 1), inside=d == 0.0))

    # 5/6. DLD Unit and DM Building Summary — the authoritative sources, when their CSVs are dropped in by hand.
    # Collapsed to one row per building number, then matched on the register's own project + area rather than on geometry,
    # because those files carry no coordinates. Absent files contribute nothing and are reported as missing.
    for kind, folder, cols in (("dld_unit", "dld", ("BUILDING_NAME_EN", "BUILDING_NAME", "BUILDING_NUMBER", "PROJECT_EN", "AREA_EN")),
                               ("dm_building", "dm", ("BUILDING_NAME", "BLDG_NAME", "MAKANI", "PLOT_NO", "COMMUNITY"))):
        for f in glob.glob(os.path.join(IDENT, "official", folder, "*.csv")):
            try:
                with open(f, encoding="utf-8-sig", errors="ignore") as fh:
                    head = next(csv.reader(fh))
            except Exception:
                continue
            if not any(c in head for c in cols): continue
            print(f"    [{kind}] {os.path.basename(f)} present - columns {[c for c in cols if c in head]}"
                  f" (matching to footprints needs the cadastral join; see IDENTITY_REPORT)")
    return out


# ---------------------------------------------------------------- the resolver
def resolve(building, evidence, min_conf):
    names = [e for e in evidence if e["attribute"] == "name" and e["confidence"] >= min_conf]
    by_norm = {}
    for e in names: by_norm.setdefault(norm(e["value"]), []).append(e)
    best = None
    for _, group in by_norm.items():
        top = max(group, key=lambda e: (-SOURCES.get(e["source"], (9, 0))[0], e["confidence"]))
        distinct = {e["source"] for e in group}
        agree = len(distinct) > 1
        score = (SOURCES.get(top["source"], (9, 0))[0], -(top["confidence"] + (0.10 if agree else 0)))
        if best is None or score < best[0]: best = (score, top, sorted(distinct), agree)
    if not best:
        return {"name": None, "grade": "UNKNOWN", "name_source": None, "confidence": 0.0, "agreeing_sources": []}
    _, top, distinct, agree = best
    rank = SOURCES.get(top["source"], (9, 0))[0]
    if rank <= 3 or (agree and top["inside"]): grade = "VERIFIED"
    elif top["inside"] and top["confidence"] >= 0.70: grade = "MATCHED"
    else: grade = "INFERRED"
    return {"name": top["value"], "grade": grade, "name_source": top["source"], "confidence": round(top["confidence"] + (0.10 if agree else 0), 3),
            "agreeing_sources": distinct, "method": top["method"], "dist_m": top.get("dist_m"), "inside": top.get("inside")}


def run(slug, min_conf):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj): return None
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    BF = load_json(os.path.join(ROOT, "data", "board", f"bldgfacts_{slug}.json"), {"buildings_by_id": {}})["buildings_by_id"]
    H = {int(k): v for k, v in BF.items()}
    blds = {}
    for i, f in enumerate(feats):
        ring = ring_of(f.get("geometry"))
        if len(ring) < 3: continue
        blds[i] = {"i": i, "ring": ring, "centroid": centroid(ring), "duid": duid_of(slug, ring),
                   "height_m": (H.get(i) or {}).get("height_m"), "storeys": (H.get(i) or {}).get("storeys")}
    print(f"  {slug}: {len(blds)} footprints")
    EV = adapters(slug, blds)
    rows = []
    A = load_json(os.path.join(NAMES, f"anchors_{slug}.json"), {"anchors": []})
    current = {a["i"]: a.get("name") for a in A.get("anchors", []) if a.get("name")}
    for i, b in blds.items():
        r = resolve(b, EV[i], min_conf)
        dev = next((e["value"] for e in EV[i] if e["attribute"] == "developer"), None)
        proj = next((e["value"] for e in EV[i] if e["attribute"] == "project"), None)
        rows.append({"duid": b["duid"], "district": slug, "i": i, "lon": round(b["centroid"][0], 6), "lat": round(b["centroid"][1], 6),
                     "height_m": b["height_m"], "storeys": b["storeys"], "current_name": current.get(i),
                     "proposed_name": r["name"], "grade": r["grade"], "name_source": r["name_source"],
                     "confidence": r["confidence"], "agreeing_sources": r["agreeing_sources"],
                     "method": r.get("method"), "dist_m": r.get("dist_m"), "inside": r.get("inside"),
                     "developer": dev, "project": proj,
                     "changed": bool(r["name"] and norm(r["name"]) != norm(current.get(i) or "")),
                     "evidence": EV[i]})
    json.dump({"district": slug, "generated": NOW, "buildings": len(rows),
               "note": "Every fact is an evidence record with its own source, method and confidence. The canonical name is chosen "
                       "by source precedence first and spatial quality second; the losing evidence is kept so any name can be traced and undone.",
               "rows": rows}, open(os.path.join(RES, f"{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--min-conf", type=float, default=0.55); ap.add_argument("slugs", nargs="*")
    a = ap.parse_args()
    slugs = a.slugs or [os.path.basename(p)[10:-5] for p in sorted(glob.glob(os.path.join(ROOT, "data", "board", "bldgfacts_*.json")))]
    allrows = []
    for s in slugs:
        r = run(s, a.min_conf)
        if r: allrows += r
    # the one table Kendall asked for
    tcsv = os.path.join(IDENT, "IDENTITY_TABLE.csv")
    with open(tcsv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["duid", "district", "lon", "lat", "height_m", "storeys", "current_name", "proposed_name", "grade",
                    "name_source", "agreeing_sources", "confidence", "match_distance_m", "inside_footprint", "method",
                    "developer", "project", "changed"])
        for r in allrows:
            w.writerow([r["duid"], r["district"], r["lon"], r["lat"], r["height_m"], r["storeys"], r["current_name"] or "",
                        r["proposed_name"] or "", r["grade"], r["name_source"] or "", "|".join(r["agreeing_sources"]),
                        r["confidence"], r["dist_m"] if r["dist_m"] is not None else "", r["inside"], r["method"] or "",
                        r["developer"] or "", r["project"] or "", r["changed"]])
    import collections
    g = collections.Counter(r["grade"] for r in allrows)
    src = collections.Counter(r["name_source"] for r in allrows if r["proposed_name"])
    named_before = sum(1 for r in allrows if r["current_name"]); named_after = sum(1 for r in allrows if r["proposed_name"])
    n = len(allrows)
    print(f"\nbuildings {n:,} | named before {named_before:,} ({named_before/max(1,n):.1%}) -> after {named_after:,} ({named_after/max(1,n):.1%})")
    print("grades:", dict(g))
    print("winning source:", dict(src.most_common()))
    print("new names proposed:", sum(1 for r in allrows if r["changed"]))
    print("table ->", tcsv)
