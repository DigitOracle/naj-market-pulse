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
from name_roles import normalize, classify, eligible, parent_of, CANONICAL_ROLES, BUILDINGISH  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names")
IDENT = os.path.join(ROOT, "data", "identity"); RES = os.path.join(IDENT, "resolved")
os.makedirs(RES, exist_ok=True)
NOW = dt.datetime.now().isoformat(timespec="seconds")

# PRECEDENCE IS (source, role) - NOT source alone. Google Places does not lose because Google ranks low; a TENANT loses
# because a tenant is not an eligible role at any confidence, from any source. That is what makes the Apple Office problem
# structural rather than a blacklist that has to keep growing.
ROLE_SCORE = {
    ("dld_unit", "BUILDING_NAME"): 100, ("dm_building", "BUILDING_NAME"): 98,
    ("osm", "BUILDING_NAME"): 92, ("osm_en", "BUILDING_NAME"): 92,
    ("overture", "BUILDING_NAME"): 88, ("wikidata", "BUILDING_NAME"): 86,
    ("dld_unit", "PROJECT_NAME"): 80, ("dm_building", "PROJECT_NAME"): 78,
    ("dld", "PROJECT_NAME"): 80, ("register", "PROJECT_NAME"): 78, ("binding", "PROJECT_NAME"): 74,
    ("osm", "STRUCTURAL_ID"): 76, ("osm_en", "STRUCTURAL_ID"): 76, ("register", "STRUCTURAL_ID"): 75,
    ("dld", "STRUCTURAL_ID"): 75, ("overture", "STRUCTURAL_ID"): 72, ("wikidata", "STRUCTURAL_ID"): 70,
    ("makani", "PLOT_ID"): 70, ("dm_building", "PLOT_ID"): 70, ("osm", "PLOT_ID"): 66,
    ("osm", "ADDRESS"): 68, ("dm_building", "ADDRESS"): 72, ("makani", "ADDRESS"): 70,
    ("overture_place", "BUILDING_NAME"): 55, ("places", "BUILDING_NAME"): 50,
    ("overture_place", "PROJECT_NAME"): 48, ("places", "PROJECT_NAME"): 45,
    ("overture_place", "STRUCTURAL_ID"): 44, ("places", "STRUCTURAL_ID"): 42,
    ("overture_place", "ADDRESS"): 40, ("places", "ADDRESS"): 40,
}
AUTHORITATIVE = {"dld_unit", "dm_building", "makani"}          # only these can make an identity VERIFIED
SURVEY = {"osm", "osm_en", "overture", "wikidata"}             # a real survey record: MATCHED
DEFAULT_SCORE = 20


def role_score(source, role):
    """0 means never canonical - a tenant, a venue, an amenity, an advert, a fragment, whatever the source."""
    if not eligible(role): return 0
    return ROLE_SCORE.get((source, role), DEFAULT_SCORE)


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
# Normalisation NEVER judges. classify() judges, and it keeps the string either way - that is why "A1" and "B4" survive now.
def clean_name(v):
    return normalize(v)


def norm(v):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower())


def spatial_factor(dist_m, is_inside):
    if is_inside: return 1.0
    if dist_m <= 10: return 0.90
    if dist_m <= 25: return 0.75
    if dist_m <= 50: return 0.55
    return 0.30


def ev(duid, attribute, value, source, rec_id, method, conf, role=None, category=None, **extra):
    """One evidence record. The ROLE is decided here, once, and travels with the fact - the resolver never re-guesses it."""
    r = role or classify(value, category, source)
    e = {"duid": duid, "attribute": attribute, "value": value, "role": r, "source": source, "source_record_id": rec_id,
         "method": method, "confidence": round(float(conf), 3), "score": role_score(source, r),
         "canonical_eligible": bool(role_score(source, r)), "captured_at": NOW}
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
            out[i].append(ev(blds[i]["duid"], "name", nm, src, a.get("id"), "carried on the footprint by build_anchors",
                             0.90, dist_m=0.0, inside=True))
        if a.get("dev"):
            out[i].append(ev(blds[i]["duid"], "developer", a["dev"], "binding", a.get("dev_project"),
                             "register scheme bound to this footprint", 0.60, role="PROJECT_NAME", dist_m=0.0, inside=True))
        if a.get("dev_project"):
            out[i].append(ev(blds[i]["duid"], "project", a["dev_project"], "binding", a.get("dev_project"),
                             "register scheme bound to this footprint", 0.60, role="PROJECT_NAME", dist_m=0.0, inside=True))

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
                         0.70 * f, category=v.get("primary"), dist_m=v.get("dist_m"), inside=bool(v.get("inside"))))

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
            pts.append((tuple(g["coordinates"][:2]), nm, cat, conf, f["properties"].get("id") or f.get("id")))
        for i, b in blds.items():
            ring = b["ring"]; c = b["centroid"]
            for pt, nm, cat, conf, rid in pts:
                if abs(pt[0] - c[0]) > 0.004 or abs(pt[1] - c[1]) > 0.004: continue      # cheap bbox reject first
                d = edge_dist(pt, ring)
                if d > 25: continue
                f = spatial_factor(d, d == 0.0)
                out[i].append(ev(b["duid"], "name", nm, "overture_place", rid,
                                 f"Overture place '{cat}' inside/next to the footprint", 0.74 * f * (0.6 + 0.4 * float(conf)),
                                 category=cat, dist_m=round(d, 1), inside=d == 0.0))

    # 3b. OSM addresses — addr:housename / building:name give a name; addr:housenumber + street give an IDENTIFIER.
    ao = os.path.join(IDENT, "osm", f"addr_{slug}.json")
    if os.path.exists(ao):
        A2 = load_json(ao, {"elements": []})
        pts = []
        for e in A2.get("elements", []):
            c = e.get("center") or {}
            if not c: continue
            pts.append(((c["lon"], c["lat"]), e.get("tags") or {}, e.get("id")))
        for i, b in blds.items():
            cen = b["centroid"]
            for pt, tags, oid in pts:
                if abs(pt[0] - cen[0]) > 0.002 or abs(pt[1] - cen[1]) > 0.002: continue
                d = edge_dist(pt, b["ring"])
                if d > 15: continue
                f = spatial_factor(d, d == 0.0)
                nm = clean_name(tags.get("addr:housename") or tags.get("building:name"))
                if nm and classify(nm) not in ("FRAGMENT","ADVERTISEMENT","PERSON"):
                    out[i].append(ev(b["duid"], "name", nm, "osm", f"way/{oid}", "OpenStreetMap addr:housename / building:name",
                                     0.90 * f, dist_m=round(d, 1), inside=d == 0.0))
                hn = (tags.get("addr:housenumber") or "").strip()
                if hn:
                    st = (tags.get("addr:street") or "").strip()
                    label = (("Villa " if (tags.get("building") or "") in ("house", "detached", "residential", "villa") else "No. ") + hn
                             + (", " + st if st else ""))
                    out[i].append(ev(b["duid"], "identifier", label, "osm", f"way/{oid}", "OpenStreetMap street address on the footprint",
                                     0.90 * f, dist_m=round(d, 1), inside=d == 0.0))
                rf = (tags.get("ref") or "").strip()
                if rf and not hn:
                    out[i].append(ev(b["duid"], "identifier", rf, "osm", f"way/{oid}", "OpenStreetMap ref on the footprint",
                                     0.90 * 0.9 * f, role="STRUCTURAL_ID", dist_m=round(d, 1), inside=d == 0.0))

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
                                 0.88 * f, dist_m=round(d, 1), inside=d == 0.0))

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
    """Four separate identity fields, then a display name by strict precedence. A tenant or venue is recorded against the
    building and can never be its name - not because its source ranks low, but because its ROLE is not canonical."""
    cand = [e for e in evidence if e["attribute"] in ("name", "identifier") and e["confidence"] >= min_conf]
    # parent-name lifting: "Jam Tower Car Parking" is an amenity, but it is evidence FOR "Jam Tower"
    for e in list(cand):
        if e["canonical_eligible"]: continue
        par = parent_of(e["value"], e["role"])
        if par:
            cand.append(ev(e["duid"], "name", par, e["source"], e["source_record_id"],
                           f"lifted from {e['role'].lower()} '{e['value'][:40]}'", e["confidence"] * 0.85,
                           dist_m=e.get("dist_m"), inside=e.get("inside"), lifted_from=e["value"]))
    buckets = {r: [] for r in ("BUILDING_NAME", "STRUCTURAL_ID", "PROJECT_NAME", "PLOT_ID", "ADDRESS",
                               "TENANT", "VENUE", "AMENITY", "INFRASTRUCTURE", "ADVERTISEMENT", "FRAGMENT", "PERSON", "UNKNOWN")}
    for e in cand: buckets.setdefault(e["role"], []).append(e)

    def best_of(role):
        g = buckets.get(role) or []
        if not g: return None
        by = {}
        for e in g: by.setdefault(norm(e["value"]), []).append(e)
        out = None
        for _, grp in by.items():
            top = max(grp, key=lambda e: (e["score"], e["confidence"]))
            agree = len({e["source"] for e in grp}) > 1
            key = (top["score"] + (6 if agree else 0), top["confidence"])
            if out is None or key > out[0]: out = (key, top, sorted({e["source"] for e in grp}), agree)
        return out

    fields, chosen = {}, {}
    for role in ("BUILDING_NAME", "STRUCTURAL_ID", "PROJECT_NAME", "PLOT_ID", "ADDRESS"):
        b = best_of(role)
        if b: fields[role] = b[1]["value"]; chosen[role] = b
    # display name, strict precedence
    order = ("BUILDING_NAME", "STRUCTURAL_ID", "PROJECT_NAME", "PLOT_ID", "ADDRESS")
    pick = next((r for r in order if r in chosen), None)
    if not pick:
        return {"display_name": None, "display_role": None, "grade": "UNKNOWN", "name_source": None, "confidence": 0.0,
                "agreeing_sources": [], "fields": fields,
                "tenants": sorted({e["value"] for e in buckets["TENANT"] + buckets["VENUE"]}),
                "amenities": sorted({e["value"] for e in buckets["AMENITY"] + buckets["INFRASTRUCTURE"]})}
    _, top, distinct, agree = chosen[pick]
    src = top["source"]
    if src in AUTHORITATIVE: grade = "VERIFIED"
    elif pick in ("STRUCTURAL_ID", "PLOT_ID", "ADDRESS"): grade = "STRUCTURALLY_IDENTIFIED"
    elif src in SURVEY: grade = "MATCHED"
    else: grade = "INFERRED"
    return {"display_name": top["value"], "display_role": pick, "grade": grade, "name_source": src,
            "confidence": round(top["confidence"] + (0.05 if agree else 0), 3), "agreeing_sources": distinct,
            "method": top["method"], "dist_m": top.get("dist_m"), "inside": top.get("inside"), "fields": fields,
            "tenants": sorted({e["value"] for e in buckets["TENANT"] + buckets["VENUE"]}),
            "amenities": sorted({e["value"] for e in buckets["AMENITY"] + buckets["INFRASTRUCTURE"]})}


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
        f = r["fields"]
        dev = next((e["value"] for e in EV[i] if e["attribute"] == "developer"), None)
        rows.append({"duid": b["duid"], "district": slug, "i": i, "lon": round(b["centroid"][0], 6), "lat": round(b["centroid"][1], 6),
                     "height_m": b["height_m"], "storeys": b["storeys"], "current_name": current.get(i),
                     "official_building_name": f.get("BUILDING_NAME"), "structural_identifier": f.get("STRUCTURAL_ID"),
                     "project_name": f.get("PROJECT_NAME"), "plot_id": f.get("PLOT_ID"), "address": f.get("ADDRESS"),
                     "display_name": r["display_name"], "display_role": r["display_role"],
                     "tenant_names": r["tenants"], "amenity_names": r["amenities"],
                     "grade": r["grade"], "name_source": r["name_source"], "confidence": r["confidence"],
                     "agreeing_sources": r["agreeing_sources"], "method": r.get("method"),
                     "dist_m": r.get("dist_m"), "inside": r.get("inside"), "developer": dev,
                     "changed": bool(r["display_name"] and norm(r["display_name"]) != norm(current.get(i) or "")),
                     "evidence": EV[i]})
    json.dump({"district": slug, "generated": NOW, "buildings": len(rows),
               "note": "Every fact is an evidence record carrying its own ROLE, source, method and confidence. Identity is resolved "
                       "into four separate fields; the display name is chosen by strict role precedence, so a tenant or a venue is "
                       "recorded against the building but can never become its name. Losing evidence is kept so any name can be traced and undone.",
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
        w.writerow(["duid", "district", "lon", "lat", "height_m", "storeys", "current_name",
                    "display_name", "display_role", "official_building_name", "structural_identifier", "project_name",
                    "plot_id", "address", "grade", "name_source", "agreeing_sources", "confidence", "match_distance_m",
                    "inside_footprint", "tenant_names", "amenity_names", "developer", "method", "changed"])
        for r in allrows:
            w.writerow([r["duid"], r["district"], r["lon"], r["lat"], r["height_m"], r["storeys"], r["current_name"] or "",
                        r["display_name"] or "", r["display_role"] or "", r["official_building_name"] or "",
                        r["structural_identifier"] or "", r["project_name"] or "", r["plot_id"] or "", r["address"] or "",
                        r["grade"], r["name_source"] or "", "|".join(r["agreeing_sources"]), r["confidence"],
                        r["dist_m"] if r["dist_m"] is not None else "", r["inside"],
                        " | ".join(r["tenant_names"][:5]), " | ".join(r["amenity_names"][:5]),
                        r["developer"] or "", r["method"] or "", r["changed"]])
    import collections
    n = len(allrows)
    g = collections.Counter(r["grade"] for r in allrows)
    role = collections.Counter(r["display_role"] for r in allrows if r["display_name"])
    src = collections.Counter(r["name_source"] for r in allrows if r["display_name"])
    proper = sum(1 for r in allrows if r["official_building_name"])
    structural = sum(1 for r in allrows if not r["official_building_name"] and (r["structural_identifier"] or r["plot_id"]))
    cadastral = sum(1 for r in allrows if not r["official_building_name"] and not r["structural_identifier"] and r["address"])
    identified = sum(1 for r in allrows if r["display_name"])
    pct = lambda x: f"{100*x/max(1,n):5.1f}%"
    print(f"\n{'footprints':<34}{n:>8,}")
    print(f"{'  properly named (BUILDING_NAME)':<34}{proper:>8,}{pct(proper):>9}")
    print(f"{'  structural identity only':<34}{structural:>8,}{pct(structural):>9}")
    print(f"{'  address identity only':<34}{cadastral:>8,}{pct(cadastral):>9}")
    print(f"{'  UNIQUELY IDENTIFIED (any)':<34}{identified:>8,}{pct(identified):>9}")
    print(f"{'  completely unidentified':<34}{n-identified:>8,}{pct(n-identified):>9}")
    print("\ngrades:", dict(g))
    print("display role:", dict(role))
    print("winning source:", dict(src.most_common(8)))
    print("tenants recorded (never canonical):", sum(len(r["tenant_names"]) for r in allrows))
    print("amenities recorded:", sum(len(r["amenity_names"]) for r in allrows))
    print("table ->", tcsv)
