"""LAB (Blocks) - building-TYPE hints per footprint, for the LOD 100 Blocks view's heights (Rings' heights agent).

Per district, per footprint index i (the index in data/ce/<slug>/buildings.geojson = the twin's b<i>):
    {"type": villa|townhouse|lowrise_apt|tower|warehouse|mall|retail|school|mosque|other, "src": <evidence>, "conf": high|medium|low}
written to data/lab/blocks/type_hints_<slug>.json as {"slug", "generated", "types": {"<i>": {...}}, "counts": {<type>: n}, ...}.
The consumer uses villa -> ~8 m and warehouse -> ~10 m instead of the 12 m placeholder (marked typical_*), so the type only
matters where the height is unknown - a real height always wins over a type.

The METHOD is scripts/lab_buildingtype_match.py's (29-30 Sep lab, three districts), imported, not copied: OSM building tag ->
amenity/shop on the building -> Overture class -> amenity point inside -> school/mosque/hospital grounds or industrial landuse
-> real height / levels -> neighbour vote -> geometry. Added here, each in its own place in that order:
  * register storeys (anchors' DLD "levels") count as levels when OSM and the footprint have none (src "...+register");
  * a NAME rule after the Overture class (mosque / masjid, school / academy / nursery, mall / city centre, warehouse / factory,
    "Villa 12" addresses, "... Tower") - medium confidence; "Residence / Building / Hotel" names say only "an apartment
    block" (lowrise_apt, low) and never override a real height;
  * mall: shop=mall or building=mall on the building, a shop=mall POI inside it, its centroid inside a shop=mall area, or any
    retail-typed footprint of 8,000 m2+ (src "...+area");
  * lowrise_apartment is written lowrise_apt.
src names the evidence that decided (tag, tag+levels, tag+area, amenity, overture, name, poi, grounds, landuse, height,
neighbour, geometry:<rule>, construction+height, no-geometry). conf: high = the building's own OSM tag or a real height;
medium = amenity grounds, Overture, name, neighbour vote, villa fabric; low = the geometry guesses. LOW-CONFIDENCE ROWS ARE
GUESSES FROM SHAPE AND SIZE ALONE and should be read that way.

Inputs (read only): data/ce/<slug>/buildings.geojson, heights_register.json + scripts/height_overrides.json (through
pyprt_district.heights, the heights the build uses), data/names/{anchors,overture,villa_labels}_<slug>.json,
data/board/bldgfacts_<slug>.json, OSM from data/lab/buildingtype/osm[_ctx]_<slug>.json (the lab's cache, reused) or
data/lab/blocks/osm/osm[_ctx]_<slug>.json (scripts/lab_blocks_osmfetch.py, one polite Overpass query per district).
Outputs: data/lab/blocks/type_hints_<slug>.json, a line per district in data/lab/blocks/TYPE_HINTS_LOG.md.

  python scripts/lab_blocks_typehints.py damachills businessbay        classify (fetching any district not yet cached)
  python scripts/lab_blocks_typehints.py --all                         every district with data/ce/<slug>/buildings.geojson
  python scripts/lab_blocks_typehints.py --all --skip-done             ... skipping districts whose type_hints file exists
Research use only.
"""
import datetime, json, math, os, re, sys, time, traceback
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lab_buildingtype_match as L          # noqa: E402  (the method: from_tags / heuristic / osm_polys ... - read-only import)
import lab_blocks_osmfetch as F             # noqa: E402

from shapely.geometry import Point           # noqa: E402
from shapely.strtree import STRtree          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); BOARD = os.path.join(ROOT, "data", "board")
LABBT = os.path.join(ROOT, "data", "lab", "buildingtype")
OUT = os.path.join(ROOT, "data", "lab", "blocks"); os.makedirs(OUT, exist_ok=True)
LOG_MD = os.path.join(OUT, "TYPE_HINTS_LOG.md")
CITY = os.path.join(ROOT, "data", "blocks_city"); CITY_OUT = os.path.join(OUT, "city"); os.makedirs(CITY_OUT, exist_ok=True)
CITY_REV = 5          # 2: measured heights only; 3: DM community prior; 4: prior only where DM covers; 5: not-villa veto -> warehouse in industrial communities (only those were re-run; others stay 4)
TYPES = ["villa", "townhouse", "lowrise_apt", "tower", "warehouse", "mall", "retail", "school", "mosque", "other"]
MALL_M2 = 8000.0
CONF_OF = {"tag": "high", "tag+levels": "high", "amenity": "high", "tag+area": "medium"}

RX_MOSQUE = re.compile(r"\b(mosque|masjid|musall?a|jami[ae]?|jumeirah mosque)\b", re.I)
RX_SCHOOL = re.compile(r"\b(school|academy|nursery|kindergarten|college|university|institute of|learning cent(re|er)|early learning)\b", re.I)
RX_MALL = re.compile(r"\b(mall|city cent(re|er)|shopping cent(re|er)|souk|hypermarket)\b", re.I)
RX_WARE = re.compile(r"\b(warehouses?|factory|logistics|workshop|industries|industrial|cold stor(e|age)|depot)\b", re.I)
RX_VILLA = re.compile(r"^\s*(villa|house)\s*(no\.?\s*)?[\dA-Z]", re.I)
RX_TOWER = re.compile(r"\btowers?\b", re.I)
RX_NOT_TOWER = re.compile(r"\b(water|clock|cooling|telecom|radio|observation|control)\s+tower\b", re.I)
RX_APT = re.compile(r"\b(residences?|residence|apartments?|bldg|building|hotel|suites|heights|court)\b", re.I)
RX_HOSP = re.compile(r"\b(hospital|clinic|police|fire station|substation|dewa)\b", re.I)


def jload(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def load_osm(slug, log=print):
    """(building elements, ctx elements, poi nodes with lat/lon, provenance)."""
    lab_b = os.path.join(LABBT, "osm_%s.json" % slug)
    if os.path.exists(lab_b):                          # the lab's cache: buildings; its POI nodes carry no lat/lon (29 Sep note)
        bel = [e for e in jload(lab_b)["elements"] if e["type"] in ("way", "relation")]
        ctx_p = os.path.join(LABBT, "osm_ctx_%s.json" % slug)
        prov = ["data/lab/buildingtype/osm_%s.json" % slug]
        if not os.path.exists(ctx_p):
            ctx_p, _ = F.fetch_district(slug, log=log, ctx_only=True)
        prov.append(os.path.relpath(ctx_p, ROOT).replace("\\", "/"))
        cel = jload(ctx_p)["elements"]
        ctx = [e for e in cel if e["type"] in ("way", "relation")]
        pois = [e for e in cel if e["type"] == "node" and "lat" in e]
        return bel, ctx, pois, prov
    p, _ = F.fetch_district(slug, log=log)
    els = jload(p)["elements"]
    bel = [e for e in els if e["type"] in ("way", "relation") and "building" in (e.get("tags") or {})]
    ctx = [e for e in els if e["type"] in ("way", "relation") and "building" not in (e.get("tags") or {})]
    ctx += [e for e in els if e["type"] in ("way", "relation") and "building" in (e.get("tags") or {})
            and ((e.get("tags") or {}).get("amenity") or (e.get("tags") or {}).get("shop") == "mall")]
    pois = [e for e in els if e["type"] == "node" and "lat" in e]
    return bel, ctx, pois, [os.path.relpath(p, ROOT).replace("\\", "/")]


def name_rule(nm, tall, h_real):
    """(type, conf) from a building name, or (None, None)."""
    if not nm:
        return None, None
    if RX_MOSQUE.search(nm): return "mosque", "medium"
    if RX_SCHOOL.search(nm) and not tall: return "school", "medium"
    if RX_MALL.search(nm): return "mall", "medium"
    if RX_HOSP.search(nm): return "other", "medium"
    if RX_WARE.search(nm) and not tall: return "warehouse", "medium"
    if RX_VILLA.search(nm) and not tall: return "villa", "medium"
    if RX_TOWER.search(nm) and not RX_NOT_TOWER.search(nm) and not (h_real and h_real < L.TALL_M): return "tower", "medium"
    if RX_APT.search(nm) and not h_real: return "lowrise_apt", "low"
    return None, None


def heuristic2(P, area, storeys, hbest, ctx):
    """The lab's heuristic (evidence 5-8), then two guarded extensions for rows it leaves as a pure geometry guess:
      * neighbour:blocks - a big box / small / irregular block among OSM-typed towers and apartment blocks (>= 3 typed within
        150 m, >= 60 % tower or lowrise apartment, footprint >= 200 m2, no industrial landuse) is an apartment block of unknown
        height (lowrise_apt), not a warehouse or 'other' (the lab's neighbour vote never fires for towers: no area band);
      * geometry:villa-fabric-weak - a 100-900 m2 footprint of <= 3 storeys the lab left as 'other' (geometry:small) where
        45-60 % of the >= 6 footprints within 150 m are villa-sized and low, no footprint within 150 m has a real height of
        20 m+ or a tower tag, and no typed neighbour majority says blocks, warehouses or shops.
    Both are low confidence."""
    t, basis, conf = _heuristic2_core(P, area, storeys, hbest, ctx)
    # city rev 3 - the DM register as a COMMUNITY prior, for rows only geometry typed (never over a tag, grounds, height or
    # neighbour vote). Old villa plots carry a villa plus majlis / annex / garage footprints, and those small pieces dilute the
    # villa-fabric test: in Al Twar Third 63 % of footprints are < 100 m2 and 89 % came out 'other'. Where >= 80 % of the
    # community's DM-permitted buildings are villas, a low 90-900 m2 footprint with no tall neighbour is a villa (medium);
    # where >= 60 % are industrial, an unmeasured 300 m2+ footprint is a warehouse (medium). City only (twin hints unchanged).
    pr = ctx.get("dm_prior")
    if pr and basis.startswith("geometry") and basis != "geometry:tiny":
        if pr["villa"] >= 0.8 and pr["coverage"] >= 0.25 and 90 <= area <= 900 and (storeys or 0) <= 3 and not ctx.get("tall_near") and not (hbest and hbest >= L.TALL_M):
            return L.row_or_villa(P, area), "dm_prior:villa", "medium"
        if pr["industrial"] >= 0.6 and pr["coverage"] >= 0.25 and area >= 300 and not hbest:
            return "warehouse", "dm_prior:industrial", "medium"
        # and the veto: where <= 15 % of permitted buildings are villas (Karama: 5 %, G+3/G+4 blocks on a 12 m placeholder look
        # like villa fabric to the geometry test), a geometry-only villa / townhouse is an apartment block, not a villa
        # (only where the register covers the community well: DM does not permit in free zones and master communities, where a
        # low villa share means "not in the register", not "not villas" - Al Thanyah 5's Springs / Meadows show 3 %)
        if pr["villa"] <= 0.15 and pr["coverage"] >= 0.8 and t in L.VILLAISH:
            if pr["industrial"] >= 0.4 and area >= 150:
                # rev 5: in an industrial community the low villa-sized box is a workshop / warehouse, not an apartment block
                return "warehouse", "dm_prior:not-villa", ("medium" if pr["industrial"] >= 0.6 else "low")
            return ("lowrise_apartment", "dm_prior:not-villa", "medium") if area >= 150 else ("other", "dm_prior:not-villa", "low")
        # a geometry-only 'warehouse' (a plain box) where <= 5 % of permitted buildings are industrial is some other block
        if pr["industrial"] <= 0.05 and pr["coverage"] >= 0.8 and t == "warehouse":
            return ("other" if pr["villa"] >= 0.8 else "lowrise_apartment"), "dm_prior:not-industrial", "low"
    return t, basis, conf


def _heuristic2_core(P, area, storeys, hbest, ctx):
    t, basis, conf = L.heuristic(P, area, storeys, hbest, ctx)
    if basis in ("geometry:area", "geometry:bigbox", "geometry:bigbox-irregular", "geometry:small"):
        v = ctx.get("votes") or Counter(); tot = sum(v.values())
        blocks = v.get("tower", 0) + v.get("lowrise_apartment", 0)
        if tot >= 3 and blocks / tot >= 0.6 and area >= 200 and not ctx.get("industrial"):
            return "lowrise_apartment", "neighbour:blocks", "low"
        fab = ctx.get("fabric", 0.0)
        if basis == "geometry:small" and 0.45 <= fab < 0.6 and 100 <= area <= 900 and (storeys or 0) <= 3 \
                and not ctx.get("tall_near") and not (tot and (blocks + v.get("warehouse", 0) + v.get("retail", 0)) / tot >= 0.5):
            return L.row_or_villa(P, area), "geometry:villa-fabric-weak", "low"
    return t, basis, conf


def load_city(slug):
    """A beyond-51 community: data/blocks_city/<slug>/blocks.json. Footprint index i = the building feature's own "i"
    (0..n-1 in file order). Heights: h when hs is a measurement (not default12 / unknown / typical_*); floors-based hs
    (e.g. overture_floors, floors x 3.2 m) also give levels."""
    p = os.path.join(CITY, slug, "blocks.json")
    blk = jload(p)
    B = [f for f in blk.get("features") or [] if (f.get("properties") or {}).get("k") == "b"]
    n = 1 + max((f["properties"]["i"] for f in B), default=-1)
    feats = [{"geometry": None, "properties": {}} for _ in range(n)]
    H = {}
    for f in B:
        pr = f["properties"]; i = pr["i"]; hs = str(pr.get("hs") or "")
        h = float(pr.get("h") or 0)
        # a per-building measurement only (whitelist): community medians, typical_* and the 12 m default are estimates - using
        # them as heights turned 7,764 Al Barsha Second footprints into "3 storeys" (city rev 1 bug, fixed 00:35)
        real = hs.startswith(("overture", "osm", "register", "dm_", "dld", "bldgfacts", "anchor", "lidar", "survey"))
        lv = round(h / 3.2) if (real and "floor" in hs and h > 0) else ""
        feats[i] = {"geometry": f.get("geometry"), "properties": {"name": pr.get("n") or "", "levels": str(lv) if lv else "",
                                                                    "status": "existing"}}
        H[i] = round(h, 1) if real else L.PLACEHOLDER
    info = {"blocks_file": "data/blocks_city/%s/blocks.json" % slug, "blocks_generated": (blk.get("meta") or {}).get("generated"),
            "blocks_mtime": datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds"), "blocks_buildings": len(B)}
    return feats, H, info


def run(slug, log=print, city=False):
    t0 = time.time()
    if city:
        feats, H, cinfo = load_city(slug)
        ours = [(L.our_polys([f])[0] if f.get("geometry") else None) for f in feats]
        els, prov = F.fetch_city(slug, [f for f in feats if f.get("geometry")], log)
        bel = [e for e in els if e["type"] in ("way", "relation") and "building" in (e.get("tags") or {})]
        ctx_el = [e for e in els if e["type"] in ("way", "relation") and ("building" not in (e.get("tags") or {})
                  or (e.get("tags") or {}).get("amenity") or (e.get("tags") or {}).get("shop") == "mall")]
        poi_el = [e for e in els if e["type"] == "node" and "lat" in e]
    else:
        feats = jload(os.path.join(CE, slug, "buildings.geojson"))["features"]
        H = L.build_heights(slug, feats)
        ours = L.our_polys(feats)
        bel, ctx_el, poi_el, prov = load_osm(slug, log)
    aux = (lambda p, d: d) if city else jload                 # the twin's per-district name / register files do not exist for the city
    vl = (aux(os.path.join(NAMES, "villa_labels_%s.json" % slug), {}) or {}).get("labels") or {}
    ov = aux(os.path.join(NAMES, "overture_%s.json" % slug), {}) or {}
    anch = aux(os.path.join(NAMES, "anchors_%s.json" % slug), {}) or {}
    a_by_i = {}
    for a in anch.get("anchors") or []:
        if a.get("i") is not None and a["i"] not in a_by_i:
            a_by_i[a["i"]] = a
    bf = (aux(os.path.join(BOARD, "bldgfacts_%s.json" % slug), {}) or {}).get("buildings_by_id") or {}
    dm_prior = None
    if city:
        cn = str((jload(os.path.join(CITY, slug, "meta.json"), {}) or {}).get("comm_num") or "")
        e = ((jload(os.path.join(OUT, "_registers_by_community.json"), {}) or {}).get("dm") or {}).get(cn)
        if e and sum((e.get("types") or {}).values()) >= 30:
            ty = e["types"]; tot = float(sum(ty.values()))
            dm_prior = {"comm_num": cn, "dm_buildings": int(tot), "coverage": round(tot / max(1, len(feats)), 2),
                        "villa": round((ty.get("Private Villa", 0) + ty.get("Investment Villa", 0)) / tot, 3),
                        "industrial": round(ty.get("Industrial Building", 0) / tot, 3)}

    O = L.osm_polys(bel)
    tree = STRtree([p for p, _ in O]) if O else None
    grounds = L.area_polys(ctx_el, lambda t: t.get("amenity") in ("school", "kindergarten", "college", "university", "place_of_worship", "hospital"))
    lu_ind = L.area_polys(ctx_el, lambda t: t.get("landuse") == "industrial")
    malls = L.area_polys(ctx_el, lambda t: t.get("shop") == "mall")
    pois = [(Point(L.TF.transform(e["lon"], e["lat"])), e.get("tags", {})) for e in poi_el]
    ptree = STRtree([p for p, _ in pois]) if pois else None

    # ---- 1. match (the lab's rule: exact IoU >= 0.9, overlap >= 0.5, contain)
    M = {}
    for i, P in enumerate(ours):
        if P is None or tree is None: continue
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
                if best is None or score > best[0]: best = (score, meth, round(iou, 3), int(k))
        if best:
            typed = None
            if (O[best[3]][1].get("tags", {}).get("building") or "yes") == "yes":
                cand = []
                for k in tree.query(P):
                    Q, e = O[int(k)]; t = e.get("tags", {})
                    if (t.get("building") or "yes") != "yes" and P.intersection(Q).area / P.area >= 0.3: cand.append((P.intersection(Q).area, int(k)))
                if cand: typed = max(cand)[1]
            M[i] = {"meth": best[1], "iou": best[2], "k": best[3], "typed_k": typed}

    # ---- 2. per-footprint facts + tag evidence
    base, typed_pts = {}, []
    for i, P in enumerate(ours):
        pr = feats[i].get("properties") or {}
        area = P.area if P is not None else 0.0
        lv_our = L.num(pr.get("levels"))
        a = a_by_i.get(i) or {}
        lv_reg = L.num(a.get("levels"))
        h = H.get(i, 0.0)
        bldgH = h if (h > 0 and not (abs(h - L.PLACEHOLDER) < 0.01 and lv_our)) else (lv_our * L.FLOOR_H if lv_our else L.PLACEHOLDER)
        placeholder = abs(h - L.PLACEHOLDER) < 0.01 and not lv_our
        h_real = None if placeholder else bldgH
        m = M.get(i); tags = {}
        if m:
            e = O[m["k"]][1]; tags = dict(e.get("tags", {}))
            if m["typed_k"] is not None:
                t2 = O[m["typed_k"]][1].get("tags", {})
                tags["building"] = t2.get("building", tags.get("building", "yes"))
                for kk in ("building:levels", "height", "amenity", "religion", "shop"):
                    if kk in t2 and kk not in tags: tags[kk] = t2[kk]
        lv_osm = L.num(tags.get("building:levels")); h_osm = L.num(tags.get("height"))
        reg_used = not (lv_osm or lv_our) and bool(lv_reg)
        storeys = lv_osm or lv_our or lv_reg or (round(h_real / L.FLOOR_H) if h_real else None)
        hbest = max(h_osm or 0, h_real or 0) or None
        tall_osm = (lv_osm or 0) >= L.TALL_STOREYS or (h_osm or 0) >= L.TALL_M
        t, basis = L.from_tags(tags, area, storeys, hbest, P, tall_osm) if tags else (None, None)
        if t: typed_pts.append((P.centroid, t))
        nm = " ".join(x for x in {(pr.get("name") or "").strip(), (a.get("name") or "").strip() if a.get("display_role") in ("BUILDING_NAME", "ADDRESS", None) else "",
                                    (tags.get("name:en") or tags.get("name") or "").strip()} if x)
        base[i] = dict(area=area, bldgH=bldgH, placeholder=placeholder, h_real=h_real, tags=tags, storeys=storeys, hbest=hbest,
                       tag_type=t, tag_basis=basis, reg_used=reg_used, name=nm, status=pr.get("status"))
    ttree = STRtree([p for p, _ in typed_pts]) if typed_pts else None
    cents = [P.centroid if P is not None else None for P in ours]
    cidx = [i for i, c in enumerate(cents) if c is not None]
    ctree = STRtree([cents[i] for i in cidx]) if cidx else None

    def context(i, P, exclude_self_type=False):
        c = P.centroid; out = {"dm_prior": dm_prior}
        for pg, t in grounds:
            if pg.contains(c):
                a_ = t.get("amenity"); out["grounds"] = "mosque" if a_ == "place_of_worship" else "hospital" if a_ == "hospital" else "school"; break
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
        out["tall_near"] = sum(1 for j in near if (base[j]["h_real"] or 0) >= L.TALL_M or base[j]["tag_type"] == "tower")
        return out

    # ---- 3. decide, in the evidence order
    rows = {}
    for i, P in enumerate(ours):
        if P is None:
            rows[i] = {"type": "other", "src": "no-geometry", "conf": "low"}; continue
        b = base[i]; t, basis = b["tag_type"], b["tag_basis"]
        conf = CONF_OF.get(basis) if t else None
        tall = (b["storeys"] or 0) >= L.TALL_STOREYS or (b["hbest"] or 0) >= L.TALL_M
        if not t and (b["tags"].get("building") == "construction" or b["status"] == "construction") and tall:
            t, basis, conf = "tower", "construction+height", "high"
        if not t:
            oc = (ov.get(str(i)) or {}).get("class")
            if oc in L.OVERTURE_MAP:
                t = L.OVERTURE_MAP[oc]
                if t == "retail" and tall: t = "tower"
                if t == "villa": t = L.row_or_villa(P, b["area"])
                basis, conf = "overture", "medium"
        if not t:
            t2, c2 = name_rule(b["name"], tall, b["h_real"])
            if t2:
                t, basis, conf = t2, "name", c2
                if t == "villa": t = L.row_or_villa(P, b["area"])
        poi_tags = []
        if ptree is not None:
            PB = P.buffer(2)
            for k in ptree.query(PB):
                p, tg = pois[int(k)]
                if PB.contains(p): poi_tags.append(tg)
        if not t and poi_tags and not tall:
            ams = {tg.get("amenity") for tg in poi_tags}; shops = [tg for tg in poi_tags if tg.get("shop")]
            if "place_of_worship" in ams: t, basis, conf = "mosque", "poi", "medium"
            elif ams & L.SCHOOL: t, basis, conf = "school", "poi", "medium"
            elif any(tg.get("shop") == "mall" for tg in poi_tags): t, basis, conf = "mall", "poi", "medium"
            elif shops or ams & L.POI_RETAIL: t, basis, conf = "retail", "poi", "low"
        if not t:
            t, basis, conf = heuristic2(P, b["area"], b["storeys"], b["hbest"], context(i, P))
        # mall: explicit tags, a mall POI or mall grounds, or a big retail box
        tg = b["tags"]
        if t in ("retail", "other", "lowrise_apartment") and (tg.get("shop") == "mall" or (tg.get("building") or "").lower() == "mall"):
            t, basis, conf = "mall", "tag", "high"
        elif t == "retail" and any(x.get("shop") == "mall" for x in poi_tags):
            t, basis = "mall", basis + "+poi"
        elif t in ("retail", "other", "warehouse") and b["area"] >= 2000 and malls and any(pg.contains(P.centroid) for pg, _ in malls):
            t, basis, conf = "mall", "grounds", "medium"
        elif t == "retail" and b["area"] >= MALL_M2:
            t, basis = "mall", basis + "+area"
        if t == "lowrise_apartment": t = "lowrise_apt"
        if b["reg_used"] and basis in ("tag", "tag+levels", "height", "geometry:levels"):
            basis += "+register"
        rows[i] = {"type": t, "src": basis, "conf": conf or "low"}

    # ---- 4. how good is the no-tag fallback here? (the lab's check: re-type the tag-typed rows with their tags hidden)
    chk, agree = 0, 0
    for i, P in enumerate(ours):
        b = base.get(i)
        if P is None or not b or b["tag_basis"] not in ("tag", "tag+levels", "tag+area") or b["tag_type"] in (None, "other"): continue
        t2, _, _ = heuristic2(P, b["area"], b["storeys"], b["hbest"], context(i, P, exclude_self_type=True))
        chk += 1
        agree += int(t2 == b["tag_type"] or (t2 in L.VILLAISH and b["tag_type"] in L.VILLAISH))

    n = len(ours)
    types = {str(i): rows[i] for i in range(n)}
    counts = Counter(r["type"] for r in rows.values())
    out = {
        "slug": slug, "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "types": types,
        "counts": {k: counts.get(k, 0) for k in TYPES},
        "footprints": n,
        "by_conf": dict(Counter(r["conf"] for r in rows.values())),
        "by_src": dict(Counter(r["src"].split(":")[0] for r in rows.values()).most_common()),
        "by_type_conf": {t: dict(Counter(r["conf"] for r in rows.values() if r["type"] == t)) for t in TYPES if counts.get(t)},
        "osm_match": dict(Counter(M[i]["meth"] if i in M else "none" for i in range(n))),
        "osm_building_tag_typed": sum(1 for i in range(n) if base[i]["tag_basis"]),
        "placeholder_12m": sum(1 for i in range(n) if base[i]["placeholder"]),
        "placeholder_12m_by_type": dict(Counter(rows[i]["type"] for i in range(n) if base[i]["placeholder"]).most_common()),
        "fallback_check": {"n": chk, "agree": agree, "agree_pct": round(100.0 * agree / chk, 1) if chk else None,
                           "what": "tag-typed OSM buildings re-typed with the type tag hidden (levels/heights kept): how often the "
                                   "no-tag rules agree with the tag. Medium/low rows rest on these rules."},
        "osm_sources": prov,
        "method": "scripts/lab_blocks_typehints.py rev 2 (lab_buildingtype_match.py order: OSM tag > amenity > construction+height > "
                  "overture > name > poi > grounds/landuse > height > neighbour > geometry; added: mall, register storeys, "
                  "neighbour:blocks, geometry:villa-fabric-weak)",
        "research_only": True,
    }
    if city:
        out.update(cinfo)
        out["city_rev"] = CITY_REV
        out["dm_prior"] = dm_prior
        out["key"] = ("i = the building feature's own \"i\" in %s (0..n-1, file order) as of blocks_mtime; if that file is rebuilt "
                      "with a different blocks_buildings count, re-run these hints" % cinfo["blocks_file"])
    dst = os.path.join(CITY_OUT if city else OUT, "type_hints_%s.json" % slug); tmp = dst + ".tmp"
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, dst)
    return out, time.time() - t0


def log_line(o, secs):
    c = o["counts"]; bc = o["by_conf"]; m = o["osm_match"]; n = o["footprints"]
    matched = n - m.get("none", 0)
    fc = o["fallback_check"]
    return ("- %s | **%s** | %d footprints | %s | conf high %d / medium %d / low %d | OSM matched %.0f%%, tag-typed %d | "
            "12 m placeholders %d | fallback agree %s | `%stype_hints_%s.json` (%.0f s)"
            % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), o["slug"], n,
               ", ".join("%s %d" % (k, v) for k, v in sorted(c.items(), key=lambda kv: -kv[1]) if v),
               bc.get("high", 0), bc.get("medium", 0), bc.get("low", 0), 100.0 * matched / max(1, n), o["osm_building_tag_typed"],
               o["placeholder_12m"], ("%s%% of %d" % (fc["agree_pct"], fc["n"])) if fc["n"] else "n/a",
               "city/" if o.get("blocks_file", "").startswith("data/blocks_city") else "", o["slug"], secs))


def append_log(line):
    new = not os.path.exists(LOG_MD)
    with open(LOG_MD, "a", encoding="utf-8") as fh:
        if new:
            fh.write("# Type hints log (lab_blocks_typehints.py)\n\nOne line per district as its `type_hints_<slug>.json` lands in "
                     "data/lab/blocks/. Research use only. Types: villa | townhouse | lowrise_apt | tower | warehouse | mall | retail | "
                     "school | mosque | other. conf low = shape/size guess only.\n\n")
        fh.write(line + "\n")


def all_slugs():
    return sorted(s for s in os.listdir(CE) if os.path.exists(os.path.join(CE, s, "buildings.geojson")))


def city_slugs():
    """Every data/blocks_city community with a blocks.json, most OSM-sourced footprints first (where the hints are strongest)."""
    r = []
    for s in sorted(os.listdir(CITY)) if os.path.isdir(CITY) else []:
        if not os.path.exists(os.path.join(CITY, s, "blocks.json")): continue
        m = jload(os.path.join(CITY, s, "meta.json"), {}) or {}
        if m.get("buildings") == 0: continue
        r.append((-(m.get("footprint_sources") or {}).get("OpenStreetMap", 0), -(m.get("buildings") or 0), s))
    return [s for _, _, s in sorted(r)]


def main_city():
    """The beyond-51 queue: one pass over every community, then re-passes for any that are new, failed, or whose blocks.json
    changed its building count since its hints were written; stops when a pass has nothing to do."""
    if "## city" not in (open(LOG_MD, encoding="utf-8").read() if os.path.exists(LOG_MD) else ""):
        append_log("\n## city\n\nBeyond-51 DM communities (data/blocks_city/<slug>/blocks.json). Files: `data/lab/blocks/city/type_hints_<slug>.json`, "
                   "keyed by that blocks.json's own building index i. OSM reused from overlapping cached fetches where a footprint lies "
                   "inside one; the rest in one polite query per community.\n")
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    for rnd in range(3):
        todo = []
        for s in (only or city_slugs()):
            dst = os.path.join(CITY_OUT, "type_hints_%s.json" % s)
            o = jload(dst)
            if o and o.get("city_rev") == CITY_REV:
                meta = jload(os.path.join(CITY, s, "meta.json"), {}) or {}
                if meta.get("buildings") in (None, o.get("blocks_buildings")): continue
            todo.append(s)
        if not todo: break
        print("city round %d: %d communities" % (rnd + 1, len(todo)), flush=True)
        for k, s in enumerate(todo):
            # batch the small ones: one query for up to 8 pending small communities (<= 1,000 footprints each, <= 4,000 in all)
            def small(x):
                return ((jload(os.path.join(CITY, x, "meta.json"), {}) or {}).get("buildings") or 0) <= 1000 \
                    and not os.path.exists(os.path.join(F.CITY_OUT, "osm_%s.json" % x))
            if small(s) and F.uncovered([f for f in load_city(s)[0] if f.get("geometry")]):   # (a previous batch may cover it)
                grp, nfp = [], 0
                for x in todo[k:]:
                    if len(grp) >= 8: break
                    if not small(x): continue
                    fx = [f for f in load_city(x)[0] if f.get("geometry")]
                    if grp and nfp + len(fx) > 4000: break
                    grp.append((x, fx)); nfp += len(fx)
                if len(grp) > 1:
                    try:
                        F.fetch_batch(s, [f for _, fx in grp for f in fx], log=lambda x: print(x, flush=True))
                        print("  batch %s covers %s" % (s, ", ".join(x for x, _ in grp)), flush=True)
                    except Exception as e:
                        print("  batch %s failed (%s) - per-community queries instead" % (s, str(e)[:120]), flush=True)
            try:
                o, secs = run(s, log=lambda x: print(x, flush=True), city=True)
                line = log_line(o, secs); append_log(line); print(line, flush=True)
            except Exception as e:
                traceback.print_exc()
                append_log("- %s | **%s** | FAILED: %s (retried in the next round)" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), s, str(e)[:200]))
    if not only:
        open(os.path.join(OUT, "_city_hints_done"), "w").write(datetime.datetime.now().isoformat(timespec="seconds"))
        append_log("- %s | city queue finished" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))


def main():
    if "--city" in sys.argv:
        return main_city()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    slugs = args or (all_slugs() if "--all" in sys.argv else [])
    if "--all" in sys.argv and args:
        slugs = args + [s for s in all_slugs() if s not in args]           # named ones first, then the rest
    for s in slugs:
        if "--skip-done" in sys.argv and os.path.exists(os.path.join(OUT, "type_hints_%s.json" % s)):
            print("  %s: done already" % s, flush=True); continue
        try:
            o, secs = run(s, log=lambda x: print(x, flush=True))
            line = log_line(o, secs)
            append_log(line)
            print(line, flush=True)
        except Exception as e:
            traceback.print_exc()
            append_log("- %s | **%s** | FAILED: %s (will retry on the next pass)" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), s, str(e)[:200]))


if __name__ == "__main__":
    main()
