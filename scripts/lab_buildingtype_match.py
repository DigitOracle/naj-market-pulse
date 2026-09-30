"""LAB (technique #5, telling villas from towers) - match tagged OSM buildings to our footprints, propose a building
TYPE per footprint, and measure where today's twin disagrees.

What "our class" means today (read from the files the build uses, never guessed):
  * massing   najma_v3/v4.cga decide by HEIGHT only: >= 60 m tower grammar, 20-60 m mid-rise, < 20 m low. With no height
              the export writes the 12.0 m placeholder, so every untagged building - villa, warehouse or 30-storey block -
              becomes a 12 m box. In the v4 LOD 3 lane `lowStyle` defaults to "villa" and ce_lod3_datasmith.py never
              overrides it, so EVERY building under 20 m gets the villa grammar (porch + garage shutter on the street face).
  * label     scripts/villa_labels.py gives every unnamed low-rise (<= 3 storeys or < 12 m) the kind villa / townhouse
              (footprint < 160 m2 = townhouse) -> data/names/villa_labels_<slug>.json -> anchors / cards.
  our_class = the villa_labels kind when there is one, else the massing band (tower / midrise / lowrise).

Proposed type (taxonomy): villa | townhouse | lowrise_apartment | tower | warehouse | school | mosque | retail | other
  tower = any block of 6+ storeys or 20 m+ (the rule's own height split still chooses mid-rise vs tower grammar);
  retail = retail / commercial / office that is low-rise; other = civic, service, parking, sheds, roofs, construction.
  Evidence order, first hit wins:
    1 tag        OSM building=* on the matched way/relation (+ building:levels / height to split residential blocks)
    2 amenity    amenity / shop / religion on the building itself
    3 overture   Overture `class` already matched onto our index (data/names/overture_<slug>.json) when OSM says yes
    4 poi        amenity / shop node INSIDE the footprint (low-rise only: a cafe in a tower's podium says nothing)
    5 grounds    footprint centroid inside amenity=school|place_of_worship|hospital grounds, or landuse=industrial
    6 height     a real height (not the 12.0 placeholder) or levels -> tower if >= 20 m / 6 storeys
    7 neighbour  >= 3 typed OSM buildings within 150 m, one type >= 60 %, and this footprint's area fits that type
    8 geometry   area / shape / levels=1 / villa fabric (share of villa-sized footprints around it)
  Every row says which one decided (basis) and a confidence (high / medium / low).

Match: our footprint vs OSM polygon, both in EPSG:32640. exact (IoU >= 0.9), overlap (IoU >= 0.5), or contain
(our centroid in the OSM polygon, or the OSM centroid in ours, with >= 50 % of the smaller one covered).

Inputs (read only): data/ce/<slug>/buildings.geojson, scripts/height_overrides.json + heights_register (via
pyprt_district.heights, i.e. the heights the build really uses), data/names/villa_labels_<slug>.json,
data/names/overture_<slug>.json, data/board/bldgfacts_<slug>.json, data/lab/buildingtype/osm[_ctx]_<slug>.json.
Outputs: data/lab/buildingtype/<slug>_types.csv, types_<slug>.json, summary.json (all districts run together),
         attrs_<slug>.json (facade_match.json + lowStyle "flat" per non-villa under 20 m, for ce_lod3_datasmith.py --attr-file).
Usage:   python scripts/lab_buildingtype_match.py damachills businessbay dubaiinvestmentparkfirst
Research use only.
"""
import csv, json, math, os, sys
from collections import Counter, defaultdict

from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from pyprt_district import heights as build_heights   # noqa: E402  (read-only helper: the heights ce_batch_v2 pushes)

CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); BOARD = os.path.join(ROOT, "data", "board")
LAB = os.path.join(ROOT, "data", "lab", "buildingtype")
TF = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
TYPES = ["villa", "townhouse", "lowrise_apartment", "tower", "warehouse", "school", "mosque", "retail", "other"]
VILLAISH = {"villa", "townhouse"}
PLACEHOLDER = 12.0; TALL_M = 20.0; TALL_STOREYS = 6; FLOOR_H = 3.4

VILLA = {"house", "detached", "villa", "bungalow", "semidetached_house", "semi", "farm_house"}
ROW = {"terrace", "townhouse", "terraced_house", "row_house"}
RESI = {"apartments", "residential", "dormitory", "flats", "apartment", "hotel"}
OFFICE = {"office", "commercial"}
RETAIL = {"retail", "supermarket", "kiosk", "mall", "shop", "marketplace"}
WARE = {"warehouse", "industrial", "factory", "manufacture", "hangar", "storage", "depot"}
SCHOOL = {"school", "kindergarten", "college", "university"}
RELIG = {"mosque", "religious", "church", "temple", "chapel", "place_of_worship", "synagogue", "shrine"}
OTHER = {"hospital", "civic", "public", "government", "train_station", "transportation", "service", "garage", "garages", "parking",
         "roof", "bunker", "construction", "hut", "shed", "cabin", "stadium", "sports_hall", "sports_centre", "fire_station",
         "toilets", "carport", "gatehouse", "guardhouse", "utility", "water_tower", "greenhouse", "container", "static_caravan"}
POI_RETAIL = {"restaurant", "cafe", "fast_food", "bank", "pharmacy", "marketplace", "bureau_de_change", "ice_cream", "food_court"}
FIELDS = ["i", "osm_id", "building", "levels", "our_class", "proposed_type", "basis", "confidence", "disagreement", "match", "iou",
          "osm_height", "roof_shape", "amenity", "osm_name", "poi", "our_name", "our_levels", "our_height_m", "height_placeholder",
          "villa_label", "facade_class", "units_indicative", "footprint_m2", "lon", "lat"]
AREA_FIT = {"villa": (80, 900), "townhouse": (50, 450), "lowrise_apartment": (200, 6000), "warehouse": (300, 1e9), "retail": (100, 1e9)}


# ------------------------------------------------------------------ parsing helpers
def num(s):
    if s is None: return None
    t = str(s).strip().lower().replace(",", ".")
    if not t: return None
    feet = "'" in t or "ft" in t
    buf = ""
    for ch in t:
        if ch.isdigit() or ch == ".": buf += ch
        elif buf: break
    try:
        v = float(buf)
    except ValueError:
        return None
    return v * 0.3048 if feet else v


def ring_xy(coords):
    return [TF.transform(c[0], c[1]) for c in coords]


def our_polys(feats):
    out = []
    for f in feats:
        g = f["geometry"]; polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        parts = []
        for p in polys:
            try:
                pg = Polygon(ring_xy(p[0]), [ring_xy(r) for r in p[1:]])
                if not pg.is_valid: pg = pg.buffer(0)
                if not pg.is_empty: parts.append(pg)
            except Exception:
                pass
        out.append(unary_union(parts) if parts else None)
    return out


def osm_polys(elements):
    """(polygon, element) for every building way / relation."""
    out = []
    for e in elements:
        if e["type"] == "way" and e.get("geometry"):
            pts = [TF.transform(p["lon"], p["lat"]) for p in e["geometry"] if p]
            if len(pts) >= 4 and pts[0] == pts[-1]:
                pg = Polygon(pts)
                if not pg.is_valid: pg = pg.buffer(0)
                if not pg.is_empty and pg.area > 1: out.append((pg, e))
        elif e["type"] == "relation":
            outer, inner = [], []
            for m in e.get("members", []):
                if m.get("type") != "way" or not m.get("geometry"): continue
                pts = [TF.transform(p["lon"], p["lat"]) for p in m["geometry"] if p]
                if len(pts) >= 2: (inner if m.get("role") == "inner" else outer).append(LineString(pts))
            polys = list(polygonize(unary_union(outer))) if outer else []
            if not polys: continue
            pg = unary_union(polys)
            holes = list(polygonize(unary_union(inner))) if inner else []
            if holes: pg = pg.difference(unary_union(holes))
            if not pg.is_valid: pg = pg.buffer(0)
            if not pg.is_empty and pg.area > 1: out.append((pg, e))
    return out


def area_polys(elements, pred):
    out = []
    for pg, e in osm_polys(elements):
        if pred(e.get("tags", {})): out.append((pg, e.get("tags", {})))
    return out


def aspect(pg):
    try:
        r = pg.minimum_rotated_rectangle; xs = list(r.exterior.coords)
        a = math.dist(xs[0], xs[1]); b = math.dist(xs[1], xs[2])
        lo, hi = min(a, b), max(a, b)
        return (hi / lo if lo > 0.1 else 99.0), hi
    except Exception:
        return 1.0, 0.0


# ------------------------------------------------------------------ the classification rule
def from_tags(tags, area, storeys, h_m, pg=None, tall_osm=None):
    """Evidence 1-2. Returns (type, basis) or (None, None).
    storeys / h_m = best available (OSM levels, else ours; the taller of OSM height and our real height) - a block tagged
    office with height=15 on its podium outline but a 135 m register height is a tower. A HOUSE is only made a tower by OSM's
    own levels / height (tall_osm): our height on a house-tagged footprint is exactly the conflict this lab is looking for."""
    b = (tags.get("building") or "").strip().lower()
    if b == "construction":                    # a site, not a type: use construction=* if mapped, else fall through to levels / height
        b = (tags.get("construction") or "").strip().lower()
        if b in ("yes", "building", "construction"): b = ""
    tall = (storeys or 0) >= TALL_STOREYS or (h_m or 0) >= TALL_M
    am = (tags.get("amenity") or "").lower(); rel = (tags.get("religion") or "").lower()
    if b in VILLA: return ("tower" if (tall if tall_osm is None else tall_osm) else "villa"), "tag"
    if b in ROW: return "townhouse", "tag"
    if b in RESI:
        if tall: return "tower", "tag+levels"
        if storeys: return ("lowrise_apartment" if storeys > 3 or b != "residential" or area >= 450 else row_or_villa(pg, area)), "tag+levels"
        if b == "residential" and area < 450: return row_or_villa(pg, area), "tag+area"
        return "lowrise_apartment", "tag+area"             # a block of unknown height: the height lane, not this rule, makes it a tower
    if b in OFFICE: return ("tower" if tall else "retail"), "tag"
    if b in RETAIL: return "retail", "tag"
    if b in WARE: return ("warehouse" if area >= 60 else "other"), "tag"
    if b in SCHOOL: return "school", "tag"
    if b in RELIG: return ("mosque" if rel in ("", "muslim", "islam") else "other"), "tag"
    if b in OTHER: return "other", "tag"
    # building=yes (or an unknown value): the building's own amenity / shop / religion
    if am == "place_of_worship": return ("mosque" if rel in ("", "muslim", "islam") else "other"), "amenity"
    if am in SCHOOL: return "school", "amenity"
    if am in ("hospital", "clinic", "fire_station", "police", "townhall", "community_centre"): return "other", "amenity"
    if (tags.get("shop") or am in ("marketplace",)) and not tall: return "retail", "amenity"
    return None, None


def row_or_villa(pg, area):
    asp, long = aspect(pg) if pg is not None else (1.0, 0.0)
    if asp >= 2.2 and long >= 24: return "townhouse"          # the rule's own isRow test (rowMinAspect / rowMinLen)
    return "townhouse" if area < 160 else "villa"              # villa_labels.py's own 160 m2 split


OVERTURE_MAP = {"house": "villa", "detached": "villa", "semidetached_house": "villa", "terrace": "townhouse", "warehouse": "warehouse",
                "industrial": "warehouse", "factory": "warehouse", "school": "school", "kindergarten": "school", "college": "school",
                "university": "school", "mosque": "mosque", "religious": "mosque", "retail": "retail", "supermarket": "retail",
                "commercial": "retail", "office": "retail", "kiosk": "retail", "hospital": "other", "service": "other",
                "train_station": "other", "transportation": "other", "civic": "other", "entertainment": "other"}


def rectangularity(pg):
    try:
        g = pg if pg.geom_type == "Polygon" else max(pg.geoms, key=lambda x: x.area)
        return g.area / g.minimum_rotated_rectangle.area, len(g.exterior.coords) - 1
    except Exception:
        return 0.0, 99


def heuristic(pg, area, storeys, h_real, ctx):
    """Evidence 5-8 (no tag). ctx: grounds, industrial, votes, fabric, touching."""
    if ctx.get("grounds") == "school" and area >= 50 and not (h_real and h_real >= TALL_M): return "school", "grounds", "medium"
    if ctx.get("grounds") == "mosque" and area >= 50: return "mosque", "grounds", "medium"
    if ctx.get("grounds") == "hospital": return "other", "grounds", "medium"
    if (storeys or 0) >= TALL_STOREYS or (h_real or 0) >= TALL_M: return "tower", "height", "high" if h_real else "medium"
    if area < 40: return "other", "geometry:tiny", "medium"
    if ctx.get("industrial") and area >= 300: return "warehouse", "landuse", "medium"
    v = ctx.get("votes")
    if v:
        top, n = v.most_common(1)[0]; tot = sum(v.values())
        lo, hi = AREA_FIT.get(top, (0, -1))
        if tot >= 3 and n / tot >= 0.6 and lo <= area <= hi and not (top in VILLAISH and (storeys or 0) > 3):
            if top in VILLAISH: top = row_or_villa(pg, area)
            return top, "neighbour", "medium"
    rect, nv = rectangularity(pg)
    if storeys == 1 and area >= 400: return "warehouse", "geometry:levels1", "medium"
    if area >= 2500 and (storeys or 0) <= 2:
        return ("warehouse", "geometry:bigbox", "low") if rect >= 0.92 else ("other", "geometry:bigbox-irregular", "low")
    fab = ctx.get("fabric", 0.0)
    if fab >= 0.6 and 80 <= area <= 1000 and (storeys or 0) <= 3:
        return row_or_villa(pg, area), "geometry:villa-fabric", "medium" if fab >= 0.75 else "low"
    if storeys and 2 <= storeys <= 5: return ("lowrise_apartment" if area >= 250 else row_or_villa(pg, area)), "geometry:levels", "low"
    # >= 600 m2 with no height: a plain box (warehouses: median area / min-rectangle 0.98, <= 6 corners) vs a notched block
    # (OSM-typed towers 0.87, low-rise apartments 0.80, measured on the three lab districts)
    if area >= 600: return ("warehouse" if (rect >= 0.95 and nv <= 6) or (ctx.get("bigblock") and rect >= 0.9) else "lowrise_apartment"), "geometry:area", "low"
    return "other", "geometry:small", "low"


# ------------------------------------------------------------------ one district
def run(slug):
    feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    H = build_heights(slug, feats)
    ours = our_polys(feats)
    osm = json.load(open(os.path.join(LAB, "osm_%s.json" % slug), encoding="utf-8"))["elements"]
    ctx_p = os.path.join(LAB, "osm_ctx_%s.json" % slug)
    ctx_el = json.load(open(ctx_p, encoding="utf-8"))["elements"] if os.path.exists(ctx_p) else []
    vl = (json.load(open(os.path.join(NAMES, "villa_labels_%s.json" % slug), encoding="utf-8")).get("labels") or {}) \
        if os.path.exists(os.path.join(NAMES, "villa_labels_%s.json" % slug)) else {}
    ov = json.load(open(os.path.join(NAMES, "overture_%s.json" % slug), encoding="utf-8")) \
        if os.path.exists(os.path.join(NAMES, "overture_%s.json" % slug)) else {}
    bf = {}
    try:
        bf = json.load(open(os.path.join(BOARD, "bldgfacts_%s.json" % slug), encoding="utf-8")).get("buildings_by_id", {})
    except Exception:
        pass
    fac = {}
    try:
        fac = json.load(open(os.path.join(CE, slug, "facade_v2.json"), encoding="utf-8")).get("buildings", {})
    except Exception:
        pass

    O = osm_polys(osm)
    tree = STRtree([p for p, _ in O])
    grounds = area_polys(ctx_el, lambda t: t.get("amenity") in ("school", "kindergarten", "college", "university", "place_of_worship", "hospital"))
    lu_ind = area_polys(ctx_el, lambda t: t.get("landuse") == "industrial")
    pois = [(Point(TF.transform(e["lon"], e["lat"])), e.get("tags", {})) for e in ctx_el if e["type"] == "node" and "lat" in e]
    ptree = STRtree([p for p, _ in pois]) if pois else None

    # ---- 1. match
    M = {}
    for i, P in enumerate(ours):
        if P is None: continue
        best = None
        for k in tree.query(P):
            Q, e = O[int(k)]
            inter = P.intersection(Q).area
            if inter <= 0: continue
            iou = inter / P.union(Q).area
            cov_small = inter / min(P.area, Q.area)
            meth = "exact" if iou >= 0.9 else "overlap" if iou >= 0.5 else None
            if not meth and cov_small >= 0.5 and (Q.contains(P.representative_point()) or P.contains(Q.representative_point())):
                meth = "contain"
            if meth:
                score = iou + (0.001 * inter / P.area)
                if best is None or score > best[0]: best = (score, meth, round(iou, 3), int(k), inter / P.area)
        if best:
            # a typed OSM piece inside a footprint whose best match is building=yes lends its type (area-weighted)
            typed = None
            if (O[best[3]][1].get("tags", {}).get("building") or "yes") == "yes":
                cand = []
                for k in tree.query(P):
                    Q, e = O[int(k)]; t = e.get("tags", {})
                    if (t.get("building") or "yes") != "yes" and P.intersection(Q).area / P.area >= 0.3: cand.append((P.intersection(Q).area, int(k)))
                if cand: typed = max(cand)[1]
            M[i] = {"meth": best[1], "iou": best[2], "k": best[3], "typed_k": typed}

    # ---- 2. per-footprint facts
    rows = []
    typed_pts = []   # (point, type) for neighbour votes: OSM tag-typed buildings only
    base = {}
    for i, P in enumerate(ours):
        pr = feats[i]["properties"]
        area = P.area if P is not None else 0.0
        lv_our = num(pr.get("levels"))
        h = H.get(i, 0.0)
        bldgH = h if (h > 0 and not (abs(h - PLACEHOLDER) < 0.01 and lv_our)) else (lv_our * FLOOR_H if lv_our else PLACEHOLDER)
        placeholder = abs(h - PLACEHOLDER) < 0.01 and not lv_our
        h_real = None if placeholder else bldgH
        mass = "tower" if bldgH >= 60 else "midrise" if bldgH >= 20 else "lowrise"
        kind = (vl.get(str(i)) or {}).get("kind")
        m = M.get(i); tags = {}; oid = ""
        if m:
            e = O[m["k"]][1]; tags = dict(e.get("tags", {})); oid = "%s/%s" % (e["type"], e["id"])
            if m["typed_k"] is not None:
                e2 = O[m["typed_k"]][1]; t2 = e2.get("tags", {})
                tags["building"] = t2.get("building", tags.get("building", "yes"))            # the typed piece's type wins over "yes"
                for kk in ("building:levels", "height", "amenity", "religion", "shop"):
                    if kk in t2 and kk not in tags: tags[kk] = t2[kk]
                oid += "+%s/%s" % (e2["type"], e2["id"])
        lv_osm = num(tags.get("building:levels")); h_osm = num(tags.get("height"))
        storeys = lv_osm or lv_our or (round(h_real / FLOOR_H) if h_real else None)
        hbest = max(h_osm or 0, h_real or 0) or None
        tall_osm = (lv_osm or 0) >= TALL_STOREYS or (h_osm or 0) >= TALL_M
        t, basis = from_tags(tags, area, storeys, hbest, P, tall_osm) if tags else (None, None)
        if t: typed_pts.append((P.centroid, t))
        base[i] = dict(area=area, lv_our=lv_our, lv_osm=lv_osm, h=h, bldgH=bldgH, placeholder=placeholder, h_real=h_real, mass=mass,
                       kind=kind, m=m, tags=tags, oid=oid, storeys=storeys, hbest=hbest, tag_type=t, tag_basis=basis)
    ttree = STRtree([p for p, _ in typed_pts]) if typed_pts else None
    cents = [P.centroid if P is not None else None for P in ours]
    ctree = STRtree([c for c in cents if c is not None]); cidx = [i for i, c in enumerate(cents) if c is not None]

    def context(i, P, exclude_self_type=False):
        c = P.centroid; out = {}
        for pg, t in grounds:
            if pg.contains(c):
                a = t.get("amenity"); out["grounds"] = "mosque" if a == "place_of_worship" else "hospital" if a == "hospital" else "school"; break
        out["industrial"] = any(pg.contains(c) for pg, _ in lu_ind)
        if ttree is not None:
            v = Counter()
            for k in ttree.query(c.buffer(150)):
                p, t = typed_pts[int(k)]
                if exclude_self_type and p.distance(c) < 0.5: continue
                if p.distance(c) <= 150: v[t] += 1
            out["votes"] = v
        near = [cidx[int(k)] for k in ctree.query(c.buffer(150))]
        near = [j for j in near if j != i and cents[j].distance(c) <= 150]
        if len(near) >= 6:
            out["fabric"] = sum(1 for j in near if 90 <= base[j]["area"] <= 1000 and base[j]["bldgH"] < 20) / len(near)
            ar = sorted(base[j]["area"] for j in near); out["bigblock"] = ar[len(ar) // 2] >= 1000
        return out

    for i, P in enumerate(ours):
        if P is None: continue
        b = base[i]; t, basis = b["tag_type"], b["tag_basis"]
        conf = None if not t else "medium" if basis == "tag+area" else "high"
        if not t and (b["tags"].get("building") == "construction" or feats[i]["properties"].get("status") == "construction") and                 ((b["storeys"] or 0) >= TALL_STOREYS or (b["hbest"] or 0) >= TALL_M):
            t, basis, conf = "tower", "construction+height", "high"
        if not t:
            oc = (ov.get(str(i)) or {}).get("class")
            if oc in OVERTURE_MAP:
                t = OVERTURE_MAP[oc]
                if t in ("retail",) and ((b["storeys"] or 0) >= TALL_STOREYS or (b["hbest"] or 0) >= TALL_M): t = "tower"
                if t == "villa": t = row_or_villa(P, b["area"])
                basis, conf = "overture", "medium"
        tall = (b["storeys"] or 0) >= TALL_STOREYS or (b["hbest"] or 0) >= TALL_M
        poi_names = []
        if ptree is not None:
            for k in ptree.query(P.buffer(2)):
                p, tg = pois[int(k)]
                if P.buffer(2).contains(p): poi_names.append(tg)
        if not t and poi_names and not tall:
            ams = {tg.get("amenity") for tg in poi_names}; shops = [tg for tg in poi_names if tg.get("shop")]
            if "place_of_worship" in ams: t, basis, conf = "mosque", "poi", "medium"
            elif ams & SCHOOL: t, basis, conf = "school", "poi", "medium"
            elif shops or ams & POI_RETAIL: t, basis, conf = "retail", "poi", "low"
        if not t:
            t, basis, conf = heuristic(P, b["area"], b["storeys"], b["hbest"], context(i, P))
        b.update(type=t, basis=basis, conf=conf, poi=";".join(sorted({(tg.get("amenity") or ("shop=" + tg["shop"] if tg.get("shop") else tg.get("office") or "")) for tg in poi_names})[:4]))

    # ---- 3. how good is the fallback? re-classify the tag-typed buildings with their tags hidden
    conf_m, conf_b = Counter(), Counter()
    for i, P in enumerate(ours):
        b = base.get(i)
        if P is None or not b or b["basis"] not in ("tag", "tag+levels", "tag+area") or b["type"] == "other": continue
        cx = context(i, P, exclude_self_type=True)
        t2, _, _ = heuristic(P, b["area"], b["storeys"], b["hbest"], cx)            # (a) type tag hidden, levels / heights kept
        conf_m[(b["type"], t2)] += 1
        t3, _, _ = heuristic(P, b["area"], None, None, cx)                          # (b) no tags, no levels, no height: geometry only
        conf_b[(b["type"], t3)] += 1

    # ---- 4. rows + disagreement
    for i, P in enumerate(ours):
        b = base[i]
        if P is None:
            rows.append({"i": i, "osm_id": "", "building": "", "levels": "", "our_class": "", "proposed_type": "", "basis": "no-geometry"}); continue
        our_class = b["kind"] or b["mass"]
        t = b["type"]; dis = ""
        # A-D are real type conflicts; V is the v4 LOD 3 grammar (lowStyle "villa" on EVERY building < 20 m, capped at 3 storeys);
        # e is villa vs townhouse only (the rule's row test vs villa_labels' 160 m2 split)
        if t in VILLAISH and b["bldgH"] >= TALL_M: dis = "A villa massed tall"
        elif t == "tower" and b["bldgH"] < TALL_M: dis = "B block massed low" + (" + labelled %s" % b["kind"] if b["kind"] else "")
        elif t not in VILLAISH and t != "tower" and b["kind"] in VILLAISH: dis = "C labelled %s, is %s" % (b["kind"], t)
        elif t in ("warehouse", "school", "mosque", "retail") and b["bldgH"] >= TALL_M: dis = "D %s massed tall" % t
        elif t not in VILLAISH and b["bldgH"] < TALL_M: dis = "V %s built with villa grammar (LOD 3)" % t
        elif t in VILLAISH and b["kind"] in VILLAISH and t != b["kind"]: dis = "e %s labelled %s" % (t, b["kind"])
        m = b["m"] or {}
        c = P.centroid; lon, lat = TF.transform(c.x, c.y, direction="INVERSE")
        rows.append({"i": i, "osm_id": b["oid"], "building": b["tags"].get("building", ""), "levels": b["tags"].get("building:levels", ""),
                     "our_class": our_class, "proposed_type": t,
                     "basis": b["basis"], "confidence": b["conf"], "disagreement": dis,
                     "match": m.get("meth", ""), "iou": m.get("iou", ""), "osm_height": b["tags"].get("height", ""),
                     "roof_shape": b["tags"].get("roof:shape", ""), "amenity": b["tags"].get("amenity", ""), "osm_name": b["tags"].get("name:en") or b["tags"].get("name", ""),
                     "poi": b.get("poi", ""), "our_name": feats[i]["properties"].get("name", "") or "", "our_levels": feats[i]["properties"].get("levels", "") or "",
                     "our_height_m": round(b["bldgH"], 1), "height_placeholder": int(b["placeholder"]), "villa_label": b["kind"] or "",
                     "facade_class": (fac.get(str(i)) or {}).get("class", ""), "units_indicative": (bf.get(str(i)) or {}).get("units_indicative", ""),
                     "footprint_m2": round(b["area"]), "lon": round(lon, 6), "lat": round(lat, 6)})

    # ---- 5. OSM-typed buildings inside our district that none of our footprints picked up (gaps, not our problem to type)
    hull = unary_union([P for P in ours if P is not None]).convex_hull
    used = {M[i]["k"] for i in M} | {M[i]["typed_k"] for i in M if M[i]["typed_k"] is not None}
    gaps = Counter()
    for k, (Q, e) in enumerate(O):
        if k in used or not hull.contains(Q.representative_point()): continue
        gaps[(e.get("tags", {}).get("building") or "yes")] += 1

    with open(os.path.join(LAB, "%s_types.csv" % slug), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    lowstyle = {str(r["i"]): ("villa" if r["proposed_type"] in VILLAISH else "flat") for r in rows if r.get("proposed_type")}
    json.dump({"district": slug, "rule": "lab_buildingtype_match.py (tags > amenity > overture > poi > grounds > height > neighbour > geometry)",
               "types": {str(r["i"]): {"type": r["proposed_type"], "basis": r["basis"], "confidence": r["confidence"]} for r in rows if r.get("proposed_type")},
               "lowStyle": lowstyle},
              open(os.path.join(LAB, "types_%s.json" % slug), "w", encoding="utf-8"), ensure_ascii=False)

    # integration step 1, no code or rule change: a per-building attr file in the shape ce_lod3_datasmith.py --attr-file and
    # pyprt_district already read ({fi: {"cga": {...}}}). The district's own facade_match.json (hero / photo knobs) is carried
    # over unchanged; lowStyle "flat" is added only where it changes the build (a non-villa under 20 m, i.e. today a villa).
    fm_p = os.path.join(CE, slug, "facade_match.json")
    attrs = json.load(open(fm_p, encoding="utf-8")) if os.path.exists(fm_p) else {}
    n_flat = Counter()
    for r in rows:
        if r.get("proposed_type") and r["proposed_type"] not in VILLAISH and r["our_height_m"] < TALL_M:
            ent = attrs.setdefault(str(r["i"]), {"name": r.get("our_name") or r.get("osm_name") or "", "cga": {}})
            ent.setdefault("cga", {})["lowStyle"] = "flat"
            ent["btype"] = {"type": r["proposed_type"], "basis": r["basis"], "confidence": r["confidence"], "source": "lab_buildingtype_match.py"}
            n_flat[r["confidence"]] += 1
    json.dump(attrs, open(os.path.join(LAB, "attrs_%s.json" % slug), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n = len(ours); nm = sum(1 for r in rows if r.get("match"))
    useful = sum(1 for i in range(n) if base[i]["tag_basis"] and base[i]["tags"].get("building", "yes") not in ("yes", "construction"))
    useful_any = sum(1 for i in range(n) if base[i]["tag_basis"])
    lv_osm = sum(1 for i in range(n) if base[i]["lv_osm"]); lv_our = sum(1 for i in range(n) if base[i]["lv_our"])
    lv_any = sum(1 for i in range(n) if base[i]["lv_osm"] or base[i]["lv_our"])
    h_osm = sum(1 for i in range(n) if num(base[i]["tags"].get("height")))
    rs = sum(1 for i in range(n) if base[i]["tags"].get("roof:shape"))
    s = {"district": slug, "footprints": n, "matched": nm, "matched_pct": round(100 * nm / n, 1),
         "match_methods": dict(Counter(r.get("match") or "none" for r in rows)),
         "type_tag": useful, "type_tag_pct": round(100 * useful / n, 1),
         "type_from_osm_tags_incl_amenity": useful_any, "type_from_osm_tags_incl_amenity_pct": round(100 * useful_any / n, 1),
         "osm_levels": lv_osm, "osm_levels_pct": round(100 * lv_osm / n, 1), "our_levels": lv_our, "any_levels_pct": round(100 * lv_any / n, 1),
         "osm_height": h_osm, "roof_shape": rs, "height_placeholder": sum(1 for i in range(n) if base[i]["placeholder"]),
         "our_class": dict(Counter(r["our_class"] for r in rows)),
         "proposed": dict(Counter(r["proposed_type"] for r in rows)),
         "basis": dict(Counter((r["basis"] or "").split(":")[0] for r in rows)),
         "confidence": dict(Counter(r.get("confidence") for r in rows)),
         "disagree": dict(Counter(r["disagreement"].split(" ")[0] for r in rows if r.get("disagreement"))),
         "disagree_detail": dict(Counter(r["disagreement"] for r in rows if r.get("disagreement")).most_common(12)),
         "disagree_on_tag_rows": dict(Counter(r["disagreement"].split(" ")[0] for r in rows if r.get("disagreement") and r.get("confidence") == "high")),
         "tag_rows": sum(1 for r in rows if r.get("confidence") == "high"),
         "fallback_check": {"%s->%s" % k: v for k, v in sorted(conf_m.items())},
         "fallback_check_agree": sum(v for (a, b2), v in conf_m.items() if a == b2 or (a in VILLAISH and b2 in VILLAISH)),
         "fallback_check_n": sum(conf_m.values()),
         "fallback_geometry_only": {"%s->%s" % k: v for k, v in sorted(conf_b.items())},
         "fallback_geometry_only_agree": sum(v for (a, b2), v in conf_b.items() if a == b2 or (a in VILLAISH and b2 in VILLAISH)),
         "disagree_by_conf": {c: dict(Counter(r["disagreement"].split(" ")[0] for r in rows if r.get("disagreement") and r.get("confidence") == c))
                              for c in ("high", "medium", "low")},
         "units_indicative_on_proposed_villas": sum(int(r["units_indicative"] or 0) for r in rows if r.get("proposed_type") in VILLAISH),
         "proposed_villas": sum(1 for r in rows if r.get("proposed_type") in VILLAISH),
         "units_indicative_total": sum(int(r["units_indicative"] or 0) for r in rows if r.get("proposed_type")),
         "osm_typed_not_in_ours": dict(gaps.most_common(12)),
         "villa_grammar_under_20m_today": sum(1 for i in range(n) if base[i]["bldgH"] < TALL_M),
         "attrs_lowStyle_flat": dict(n_flat), "attrs_carried_from_facade_match": os.path.exists(fm_p),
         "villa_grammar_on_nonvilla_today": sum(1 for r in rows if r.get("proposed_type") and r["proposed_type"] not in VILLAISH and r["our_height_m"] < TALL_M),
         "villa_grammar_on_nonvilla_today_tagged": sum(1 for r in rows if r.get("proposed_type") and r["proposed_type"] not in VILLAISH and r["our_height_m"] < TALL_M and r.get("confidence") == "high"),
         "villa_grammar_under_20m_proposed": sum(1 for r in rows if r.get("proposed_type") in VILLAISH)}
    return s, rows


def main():
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = {"generated_by": "scripts/lab_buildingtype_match.py", "research_only": True, "districts": {}}
    allrows = []
    for slug in slugs:
        s, rows = run(slug); out["districts"][slug] = s
        for r in rows: r["district"] = slug
        allrows += rows
        print("\n== %s: %d footprints | matched %.1f%% | type tag %.1f%% (incl. amenity %.1f%%) | OSM levels %.1f%% | any levels %.1f%% | placeholder 12 m %d"
              % (slug, s["footprints"], s["matched_pct"], s["type_tag_pct"], s["type_from_osm_tags_incl_amenity_pct"], s["osm_levels_pct"], s["any_levels_pct"], s["height_placeholder"]))
        print("   our   ", s["our_class"]); print("   prop  ", s["proposed"]); print("   basis ", s["basis"], s["confidence"])
        print("   disagree", s["disagree"], "| on tag rows", s["disagree_on_tag_rows"], "of", s["tag_rows"])
        print("   detail  ", s["disagree_detail"])
        print("   by confidence", s["disagree_by_conf"])
        print("   fallback check (type hidden) %d/%d" % (s["fallback_check_agree"], s["fallback_check_n"]), s["fallback_check"])
        print("   fallback check (geometry only) %d/%d" % (s["fallback_geometry_only_agree"], s["fallback_check_n"]), s["fallback_geometry_only"])
        print("   indicative homes on proposed villas/townhouses: %d on %d buildings (district total %d)"
              % (s["units_indicative_on_proposed_villas"], s["proposed_villas"], s["units_indicative_total"]))
        print("   OSM buildings in our hull that no footprint matched:", s["osm_typed_not_in_ours"])
    # worst examples
    def worst(cat, key, n=8):
        return [r for r in sorted((r for r in allrows if r.get("disagreement", "").startswith(cat)), key=key)][:n]
    out["worst"] = {
        "A_villa_massed_tall": worst("A", lambda r: -r["our_height_m"]),
        "B_block_massed_low": worst("B", lambda r: (r["confidence"] != "high", -(float(r["levels"] or 0)), -r["footprint_m2"])),
        "C_labelled_villa": worst("C", lambda r: (r["confidence"] != "high", -r["footprint_m2"])),
        "D_nonresidential_tall": worst("D", lambda r: -r["our_height_m"]),
    }
    keep = ("district", "i", "osm_id", "building", "levels", "our_class", "proposed_type", "basis", "confidence", "disagreement", "osm_name", "our_name",
            "our_height_m", "height_placeholder", "villa_label", "units_indicative", "footprint_m2", "lon", "lat")
    out["worst"] = {k: [{kk: r.get(kk) for kk in keep} for r in v] for k, v in out["worst"].items()}
    json.dump(out, open(os.path.join(LAB, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in out["worst"].items():
        print("\n--", k)
        for r in v: print("  ", r["district"], r["i"], r["osm_id"], r["building"], "lv", r["levels"], "|", r["our_class"], "->", r["proposed_type"],
                          "(%s/%s)" % (r["basis"], r["confidence"]), "|", r["osm_name"] or r["our_name"], "| h", r["our_height_m"], "| %d m2" % r["footprint_m2"],
                          "| units", r["units_indicative"], "|", r["lat"], r["lon"])


if __name__ == "__main__":
    main()
