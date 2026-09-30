"""LAB (ghosts, research only): which pipeline projects in a district have a location point but no footprint, and how big
an INDICATIVE ghost massing for each would be.

CityEngine technique #7 (Tutorial 16, Pointmarker_To_FootprintShape / MARKER_BASED_BUILDING): a point marker becomes a sized
footprint becomes a building. Here the marker is the project's own location point and the size comes from the registers.
Parcels are NOT available (no cadastral layer - see memory parcel-geometry-blocked), so a ghost is a square of stated size
centred on a point: an envelope, never a footprint.

UNIVERSE   lk_d_project rows for the district's DLD area whose status is ACTIVE / NOT_STARTED / PENDING / PENDING_COMING_SOON
           (plus status-less rows seen in the 2026 registrations). FINISHED is out: those are built, OSM draws them.
EXCLUDED   any project the twin already holds, by ANY of these routes (each recorded as evidence, so a wrong exclusion can
           be found and reversed; excluding too much is safe, a duplicate tower is not):
             lk_twin_binding_register  property_id, parcel_key or name  (the canonical footprint <-> register binding)
             plots.json                pid / parcel / name
             footprint names           unitmix_<slug>, bindings.json, geocoded_projects, tx_bindings, anchors_<slug>,
                                       buildings.geojson (incl. appended placeholders such as sobha_offplan)
             geometry                  the location point sits within 15 m of a modelled footprint taller than 12.1 m
LOCATION   Places / geocoder caches already paid for (no new calls): data/identity/official/dld/geocode_cache.json (Google
           Places on DLD building names), data/identity/register/geocode_cache.json (Places on developer project names),
           data/geocode_cache.json (Esri; the district-centroid fallback "Business Bay, Dubai" is rejected). A hit counts only
           if it (a) lies inside the district polygon, (b) is not a shop/station/bank type, (c) its name shares >= 60% of the
           project's distinctive tokens.
SIZING     (all INDICATIVE, basis recorded per ghost)
             1. Dubai Municipality building register on the project's parcel (lk_dm_buildings): height_m and floor_config,
                kept only if height / above-grade levels is 2.8-6.0 m (rejects e.g. 100 m for G+107) AND the register's
                units fit (<= 25 units per above-grade level). Latest record wins.
             1b. failing that, a DM HEIGHT that the units formula corroborates within +-35% (a revised permit sometimes
                keeps the old floor_config while the height is updated).
             2. developer-published storeys (projfacts.json) x 3.44 m.
             3. units: floors = max(4, ceil(units_per_building x median_sold_unit_m2 / 821)); height = floors x 3.44 m.
                821 m2 of sold area per register floor and 3.44 m per floor are Business Bay medians over 121 register-
                bound towers, calibrated in this script (calibration.json). Back-test on those towers: median error 24%,
                61/121 within 25% - against 33% and 52/121 for a flat 10 units per floor, which stays as the fallback
                when the project has no sales yet.
             plate: square, side = min(42, 30 + 0.1 x floors) m - the house rule mass_sobha_offplan.py already uses for
                    off-plan towers whose plate is unknown.
PLACEMENT  square centred on the point; if it would overlap a modelled footprint taller than 12.1 m (6 m clearance) or
           another ghost, it moves to the first free spot on 10 m rings out to 150 m, and the move is recorded.
           Footprints <= 12.1 m (placeholders / hoarded sites) are not obstacles - the ghost may stand on its own site.

Writes data/lab/ghosts/<slug>/candidates.json, ghost_markers.geojson (points, the PyPRT input), ghost_envelopes.geojson
(indicative squares, for 2D review only), calibration.json. Reads only; touches nothing outside data/lab/ghosts/.

  python scripts/lab_ghosts_candidates.py                 (businessbay)
  python scripts/lab_ghosts_candidates.py damachills
"""
import json
import math
import os
import re
import statistics as st
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import pyproj                                             # noqa: E402
from shapely.geometry import Point, box, shape            # noqa: E402
from shapely.ops import transform                         # noqa: E402
from shapely.strtree import STRtree                       # noqa: E402

AREA = {"businessbay": ("Business Bay", 346, "BUSINESS BAY"), "damachills": ("Damac Hills", None, "DAMAC HILLS")}
PIPE_STATUS = ("ACTIVE", "NOT_STARTED", "PENDING", "PENDING_COMING_SOON")
REAL_H = 12.1            # at or below this a footprint is the 12 m placeholder or a hoarded site, not a modelled building
NEAR_FOOTPRINT_M = 15.0
CLEAR_M = 6.0
UNITS_PER_FLOOR = 10.0   # overwritten by calibration when it has enough towers
M_PER_FLOOR = 3.44
NOT_BUILDING = {"store", "shopping_mall", "restaurant", "cafe", "bus_station", "transit_station", "atm", "bank",
                "school", "parking", "gas_station", "subway_station", "train_station"}
STOP = {"the", "by", "tower", "towers", "residence", "residences", "dubai", "business", "bay", "at", "of", "and",
        "apartment", "apartments", "building", "properties", "property", "llc"}

TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
TO_LL = pyproj.Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def core(s):
    """Name without a trailing ' by <developer>' - 'Bugatti Residences by Binghatti' -> 'bugatti residences'."""
    t = str(s or "").lower().strip()
    t = re.sub(r"\s+by\s+[a-z0-9 .&'-]+$", "", t)
    return t


def toks(s):
    t = re.findall(r"[a-z0-9]+", core(s))
    d = [x for x in t if x not in STOP]
    return set(d or t)


def sim(project_name, place_name):
    a, b = toks(project_name), set(re.findall(r"[a-z0-9]+", str(place_name or "").lower()))
    return len(a & b) / len(a) if a else 0.0


def load(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def levels(cfg):
    """'8B+G+1M+91+3R' -> (above-grade levels, basements). G, M, P, R and bare numbers count above grade."""
    above = below = 0
    for part in str(cfg or "").upper().replace(" ", "").split("+"):
        m = re.match(r"^(\d*)([A-Z]*)$", part)
        if not m or not (m.group(1) or m.group(2)):
            continue
        n = int(m.group(1)) if m.group(1) else 1
        if m.group(2).startswith("B"):
            below += n
        else:
            above += n
    return above, below


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    slug = args[0] if args else "businessbay"
    if slug not in AREA:
        sys.exit("no area mapping for %s - add it to AREA" % slug)
    area_en, comm, poly_name = AREA[slug]
    out_dir = os.path.join(ROOT, "data", "lab", "ghosts", slug)
    os.makedirs(out_dir, exist_ok=True)

    from lake import connect
    con = connect()

    # ---- district polygon (the same one ce_export clipped the footprints with) and the modelled footprints
    areas = load(os.path.join(ROOT, "public", "mp_areas.json"))
    ft = next(f for f in areas["features"] if norm(f["properties"]["n"]) == norm(poly_name))
    district = shape(ft["geometry"])
    feats = load(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"))["features"]
    fp_m, fp_h = [], []
    for f in feats:
        try:
            fp_m.append(transform(TO_UTM, shape(f["geometry"])))
        except Exception:
            fp_m.append(Point(0, 0))
        fp_h.append(float(f["properties"].get("bHeight") or 0))
    real_idx = [i for i, h in enumerate(fp_h) if h > REAL_H]
    real_tree = STRtree([fp_m[i] for i in real_idx])

    # ---- calibration: units/floor, m/floor over register-bound towers in THIS district
    cal_rows = con.execute("""select footprint_i, units, floors from lk_twin_binding_register
                              where district=? and rank='primary' and units>0 and floors>=5""", [slug]).fetchall()
    seen, upf, mpf, plate = set(), [], [], []
    for fi, u, fl in cal_rows:
        if fi in seen or fi >= len(feats) or fp_h[fi] <= REAL_H:
            continue
        seen.add(fi)
        upf.append(u / fl); mpf.append(fp_h[fi] / fl); plate.append(fp_m[fi].area)
    q = lambda xs: {"n": len(xs), "median": round(st.median(xs), 2), "q1": round(st.quantiles(xs, n=4)[0], 2),
                    "q3": round(st.quantiles(xs, n=4)[2], 2)} if len(xs) >= 8 else {"n": len(xs)}
    cal = {"units_per_floor": q(upf), "m_per_floor": q(mpf), "footprint_m2": q(plate),
           "source": "lk_twin_binding_register primary bindings, register units and floors, footprint bHeight > 12.1 m",
           "note": "floors are the DLD register's floors (podium included), so units/floor and m/floor are per register floor"}
    upf_k = cal["units_per_floor"].get("median", UNITS_PER_FLOOR) if len(upf) >= 30 else UNITS_PER_FLOOR
    mpf_k = cal["m_per_floor"].get("median", M_PER_FLOOR) if len(mpf) >= 30 else M_PER_FLOOR
    # unit-size-aware variant: a floor holds ~A m2 of SOLD area, so floors = units x median sold unit size / A.
    # Median sold unit size per footprint from the DLD transactions binding (tx_bindings median_sqm).
    txb = (load(os.path.join(ROOT, "data", "identity", "official", "dld", "tx_bindings.json"), {}) or {}).get(slug, {})
    sold = []
    for fi, u, fl in cal_rows:
        t = txb.get(str(fi)) or {}
        if fi < len(feats) and fp_h[fi] > REAL_H and t.get("median_sqm"):
            sold.append((u, fl, fp_h[fi], float(t["median_sqm"])))
    A = st.median([u / fl * s for u, fl, h, s in sold]) if len(sold) >= 30 else None
    cal["sold_m2_per_register_floor"] = {"n": len(sold), "A": round(A, 1) if A else None,
                                         "source": "units/floors (register) x median_sqm (tx_bindings, DLD transactions)"}
    # back-test both formulas on the same towers: how wrong is each where we know the answer?
    e1, e2 = [], []
    for u, fl, h, s in sold:
        e1.append(abs(max(4, math.ceil(u / upf_k)) * mpf_k - h) / h)
        if A:
            e2.append(abs(max(4, math.ceil(u * s / A)) * mpf_k - h) / h)
    bt = lambda es: {"towers": len(es), "median_abs_pct_error": round(100 * st.median(es), 1) if es else None,
                     "within_25pct": sum(1 for e in es if e <= 0.25)}
    cal["backtest_constant_units_per_floor"] = bt(e1)
    cal["backtest_unit_size_aware"] = bt(e2)
    cal["used"] = {"units_per_floor": upf_k, "m_per_floor": mpf_k, "sold_m2_per_floor": round(A, 1) if A else None}

    # ---- footprint-name sources (for exclusion)
    names = {}
    def add(src, nm):
        if nm and len(norm(nm)) >= 3:
            names.setdefault(norm(nm), set()).add(src)
            names.setdefault(norm(core(nm)), set()).add(src)
    for f in feats:
        add("buildings.geojson", f["properties"].get("name"))
    for v in (load(os.path.join(ROOT, "data", "board", "unitmix_%s.json" % slug), {}) or {}).get("buildings_by_id", {}).values():
        add("unitmix", v.get("name"))
    for v in (load(os.path.join(ROOT, "data", "ce", slug, "bindings.json"), {}) or {}).get("bindings", {}).values():
        add("bindings.json", v.get("project"))
    for v in (load(os.path.join(ROOT, "data", "identity", "register", "geocoded_projects.json"), {}) or {}).get(slug, {}).values():
        add("geocoded_projects", v.get("name"))
    for v in (load(os.path.join(ROOT, "data", "identity", "official", "dld", "tx_bindings.json"), {}) or {}).get(slug, {}).values():
        add("tx_bindings", v.get("project")); add("tx_bindings", v.get("building"))
    for a in (load(os.path.join(ROOT, "data", "names", "anchors_%s.json" % slug), {}) or {}).get("anchors", []):
        add("anchors", a.get("name"))
    plots = [f for f in load(os.path.join(ROOT, "data", "board", "plots.json"))["features"] if f["properties"].get("district") == slug]
    placeholder_pnos = {str(f["properties"].get("project_number")) for f in feats if f["properties"].get("register_placeholder")}

    # ---- location caches
    dld_cache = load(os.path.join(ROOT, "data", "identity", "official", "dld", "geocode_cache.json"), {}) or {}
    reg_cache = load(os.path.join(ROOT, "data", "identity", "register", "geocode_cache.json"), {}) or {}
    esri = load(os.path.join(ROOT, "data", "geocode_cache.json"), {}) or {}
    tx_b = (load(os.path.join(ROOT, "data", "dld", "tx_buildings_%s.json" % slug), {}) or {}).get("buildings", [])
    projfacts = load(os.path.join(ROOT, "data", "board", "projfacts.json"), {}).get("projects", {})
    pf_by = {}
    for v in projfacts.values():
        for nm in [v.get("name")] + list(v.get("aliases") or []):
            pf_by.setdefault(norm(nm), v)
    suffix = ", %s, dubai" % area_en.lower()
    dld_idx = {}
    for k, v in dld_cache.items():
        if k.lower().endswith(suffix):
            dld_idx.setdefault(norm(k[:-len(suffix)]), []).extend(v or [])

    def points_for(name_list, dev):
        hits = []
        def consider(src, key, r):
            loc = r.get("location") or {}
            lon, lat = loc.get("longitude"), loc.get("latitude")
            if lon is None:
                return
            types = set(r.get("types") or [])
            disp = (r.get("displayName") or {}).get("text", "")
            hits.append({"source": src, "key": key, "lon": round(lon, 7), "lat": round(lat, 7), "place": disp,
                         "types": sorted(types)[:6], "in_district": district.contains(Point(lon, lat)),
                         "shop_type": bool(types & NOT_BUILDING),
                         "name_sim": round(max(sim(n, disp) for n in name_list), 2)})
        tx_names = [b["building"] for b in tx_b if norm(b.get("project")) in {norm(n) for n in name_list}]
        for n in list(name_list) + tx_names:
            for r in dld_idx.get(norm(n), []):
                consider("google_places:dld_building", n, r)
        for k, v in reg_cache.items():
            if any(norm(k).startswith(norm(n)) and len(norm(n)) >= 4 for n in name_list):
                for r in v or []:
                    consider("google_places:register", k, r)
        for k, v in esri.items():
            kk = k.split("::", 1)[-1].split(",")[0]
            if any(norm(kk) == norm(n) for n in name_list):
                if (v.get("address") or "").strip().lower() in ("business bay, dubai", "dubai") or v.get("addr_type") == "Locality":
                    hits.append({"source": "esri", "key": k, "lon": v["lon"], "lat": v["lat"], "place": v.get("address"),
                                 "rejected": "district-centroid fallback"})
                    continue
                consider("esri", k, {"location": {"longitude": v["lon"], "latitude": v["lat"]},
                                     "displayName": {"text": v.get("name") or v.get("address")},
                                     "types": (v.get("type") or "").split(",")})
        ok = [h for h in hits if not h.get("rejected") and h["in_district"] and not h["shop_type"] and h["name_sim"] >= 0.6]
        order = {"google_places:dld_building": 0, "google_places:register": 1, "esri": 2}
        ok.sort(key=lambda h: (-h["name_sim"], order.get(h["source"], 9)))
        return ok, hits

    # ---- universe
    rows = con.execute("""select d.project_number, d.project_id, d.name_en, d.names_en, d.status, d.percent_completed,
                                 d.planned_units, d.planned_buildings, d.planned_villas, d.end_date, d.completion_date,
                                 d.register_property_id, d.developer_number, d.in_projects_register, d.in_2026_registrations,
                                 v.name_en as developer
                          from lk_d_project d left join lk_d_developer v on v.developer_number=d.developer_number
                          where d.area_name_en=?""", [area_en]).fetchall()
    cols = ["project_number", "project_id", "name_en", "names_en", "status", "pct", "units", "buildings", "villas", "end_date",
            "completion_date", "property_id", "developer_number", "in_projects_register", "in_2026_registrations", "developer"]
    P = [dict(zip(cols, r)) for r in rows]
    universe = [p for p in P if p["status"] in PIPE_STATUS or (p["status"] is None and p["in_2026_registrations"] and not p["completion_date"])]

    cands, ghosts = [], []
    placed_m = []
    for p in sorted(universe, key=lambda p: int(p["project_number"] or 0)):
        nm = p["name_en"] or ""
        name_list = [n for n in ([nm] + list(p["names_en"] or [])) if n]
        rec = {"project_number": p["project_number"], "project_id": p["project_id"], "name": nm or None,
               "developer": p["developer"], "status": p["status"], "percent_completed": float(p["pct"]) if p["pct"] is not None else None,
               "units": p["units"], "buildings": p["buildings"], "villas": p["villas"],
               "end_date": str(p["end_date"]) if p["end_date"] else None, "property_id": p["property_id"]}
        parcels = []
        if p["property_id"] or p["project_id"]:
            parcels = sorted({r[0] for r in con.execute(
                "select parcel_key from lk_d_parcel where property_id=? or project_id=?",
                [int(p["property_id"] or -1), int(p["project_id"] or -1)]).fetchall() if r[0]})
        rec["parcel_keys"] = parcels

        # exclusion evidence
        ev = []
        tb = con.execute("""select distinct footprint_i, twin_name, register_name, method, names_differ from lk_twin_binding_register
                            where district=? and (property_id=? or parcel_key in (select unnest(?)) or upper(trim(register_name))=upper(trim(?))
                                                  or upper(trim(project))=upper(trim(?)))""",
                         [slug, str(p["property_id"] or ""), parcels or [0], nm, nm]).fetchall()
        for fi, tn, rn, meth, nd in tb:
            ev.append({"route": "lk_twin_binding_register", "footprint_i": fi, "twin_name": tn, "register_name": rn,
                       "method": meth, "names_differ": bool(nd)})
        for f in plots:
            pr = f["properties"]
            if (p["property_id"] and str(pr.get("pid")) == str(p["property_id"])) or norm(pr.get("name")) in {norm(n) for n in name_list} \
               or any(str(pr.get("parcel", "")).split(".")[0] == str(k) for k in parcels):
                ev.append({"route": "plots.json", "plot": pr.get("plot"), "name": pr.get("name"), "footprint_i": pr.get("i")})
        for n in name_list:
            for key in {norm(n), norm(core(n))}:
                if len(key) >= 4 and key in names:
                    ev.append({"route": "footprint names", "name": n, "sources": sorted(names[key])})
        if str(p["project_number"]) in placeholder_pnos:
            ev.append({"route": "buildings.geojson placeholder", "project_number": p["project_number"]})
        rec["footprint_evidence"] = ev

        # location
        ok, hits = points_for(name_list, p["developer"]) if name_list else ([], [])
        rec["location_hits"] = hits[:8]
        pt = ok[0] if ok else None
        if pt and len({(round(h["lon"], 3), round(h["lat"], 3)) for h in ok}) > 1:
            far = max(Point(TO_UTM(h["lon"], h["lat"])).distance(Point(TO_UTM(pt["lon"], pt["lat"]))) for h in ok)
            rec["location_spread_m"] = round(far, 1)
        rec["location"] = {k: pt[k] for k in ("source", "key", "lon", "lat", "place", "types", "name_sim")} if pt else None
        if pt:
            bt = set(pt["types"]) & {"apartment_building", "apartment_complex", "condominium_complex", "housing_complex", "premise", "lodging", "hotel"}
            rec["location"]["confidence"] = "building-type place" if bt else \
                "office/organisation-type place - may be a sales office, not the site"

        # geometric: is a modelled building already standing on that point?
        if pt:
            pm = Point(TO_UTM(pt["lon"], pt["lat"]))
            near = [real_idx[j] for j in real_tree.query(pm.buffer(NEAR_FOOTPRINT_M))]
            near = [i for i in near if fp_m[i].distance(pm) <= NEAR_FOOTPRINT_M]
            if near:
                i = min(near, key=lambda i: fp_m[i].distance(pm))
                ev.append({"route": "geometry", "footprint_i": i, "name": feats[i]["properties"].get("name"),
                           "bHeight": fp_h[i], "dist_m": round(fp_m[i].distance(pm), 1)})

        if ev:
            rec["decision"] = "excluded: already on the twin"
            rec["exclusion_routes"] = sorted({e["route"] for e in ev})
            cands.append(rec); continue
        if not pt:
            rec["decision"] = "not ghosted: no location point"
            cands.append(rec); continue

        # ---- sizing (indicative)
        size = None
        u = int(p["units"] or 0); nb = max(1, int(p["buildings"] or 1))
        # median sold unit size: this project's DLD transaction buildings (off-plan sales count), else the developer-site DLD facts
        pf = next((pf_by[norm(n)] for n in name_list if norm(n) in pf_by), None)
        txs = [b for b in tx_b if norm(b.get("project")) in {norm(n) for n in name_list} or norm(b.get("building")) in {norm(n) for n in name_list}]
        s_sqm, s_src = None, None
        if txs and any(b.get("median_sqm") for b in txs):
            best = max((b for b in txs if b.get("median_sqm")), key=lambda b: b.get("sales") or 0)
            s_sqm, s_src = float(best["median_sqm"]), "DLD transactions, %s (%s sales)" % (best["building"], best.get("sales"))
        elif pf and (pf.get("dld") or {}).get("median_aed") and (pf.get("dld") or {}).get("median_aed_per_sqm"):
            s_sqm = pf["dld"]["median_aed"] / pf["dld"]["median_aed_per_sqm"]; s_src = "developer-site DLD facts, median AED / median AED per m2"
        fl_u = None
        if u:
            if A and s_sqm:
                fl_u = max(4, math.ceil(u / nb * s_sqm / A))
                u_detail = "max(4, ceil(%d units / %d bldg x %.0f m2 median sold unit / %.0f m2 per floor)) = %d floors x %.2f m" % (
                    u, nb, s_sqm, A, fl_u, mpf_k)
            else:
                fl_u = max(4, math.ceil(u / nb / upf_k))
                u_detail = "max(4, ceil(%d units / %d bldg / %.2f units per floor)) = %d floors x %.2f m" % (u, nb, upf_k, fl_u, mpf_k)
            rec["units_formula"] = {"floors": fl_u, "height_m": round(fl_u * mpf_k, 1), "unit_sqm": round(s_sqm, 1) if s_sqm else None,
                                    "unit_sqm_source": s_src, "detail": u_detail}
        dm = con.execute("""select building_id, height_m, floor_config, typical_floors, total_area_sqm, plot_area_sqm, status, permitted_date
                            from lk_dm_buildings where parcel_key in (select unnest(?)) and coalesce(status,'')<>'Building Cancelled'
                            and demolition_date is null and height_m >= 12 order by permitted_date desc nulls last, building_id desc""",
                         [parcels or [0]]).fetchall()
        dm_seen = []
        for bid, h, cfg, tf_, gfa, plot_a, stt, pdate in dm:
            above, below = levels(cfg)
            mpl = h / above if above else None
            dens = (u / nb / above) if (u and above) else None
            ok_dm = bool(mpl and 2.8 <= mpl <= 6.0) and (dens is None or dens <= 25)
            dm_seen.append({"building_id": bid, "height_m": h, "floor_config": cfg, "above_grade": above, "m_per_level": round(mpl, 2) if mpl else None,
                            "units_per_level": round(dens, 1) if dens else None, "status": stt,
                            "permitted_date": str(pdate) if pdate else None, "plausible": ok_dm})
            if ok_dm and not size:
                size = {"basis": "dm_register", "height_m": round(float(h), 1), "floors": above, "plot_area_m2": plot_a,
                        "detail": "DM building %s on parcel: %s, %.1f m (%s)" % (bid, cfg, h, stt)}
        if not size and fl_u:
            # no DM record passes both checks; take a DM HEIGHT the register's own unit count corroborates (+-35%) -
            # the floor_config on a revised permit is sometimes left at the old scheme while the height is updated
            want = fl_u * mpf_k
            corr = [d for d in dm_seen if abs(d["height_m"] - want) <= 0.35 * want]
            if corr:
                d = min(corr, key=lambda d: abs(d["height_m"] - want))
                size = {"basis": "dm_register_height", "height_m": round(float(d["height_m"]), 1),
                        "floors": int(round(d["height_m"] / mpf_k)),
                        "detail": "DM building %s height %.1f m (its floor_config %s is inconsistent), corroborated by the units formula %.0f m" % (
                            d["building_id"], d["height_m"], d["floor_config"], want)}
        rec["dm_records"] = dm_seen[:6]
        if not size and pf and str(pf.get("storeys") or "").isdigit():
            fl = int(pf["storeys"])
            size = {"basis": "developer_storeys", "floors": fl, "height_m": round(fl * mpf_k, 1),
                    "detail": "%s storeys (%s) x %.2f m" % (fl, pf.get("url") or "projfacts", mpf_k)}
        if not size and fl_u:
            size = {"basis": "units_formula", "floors": fl_u, "height_m": round(fl_u * mpf_k, 1), "detail": rec["units_formula"]["detail"]}
        if not size:
            size = {"basis": "none", "floors": 0, "height_m": 6.0,
                    "detail": "register holds no units and no DM record: drawn as a 6 m site marker, size unknown"}
        side = min(42.0, 30.0 + 0.1 * size["floors"]) if size["floors"] else 24.0
        size["side_m"] = round(side, 1)
        size["plate_rule"] = "square, side = min(42, 30 + 0.1 x floors) m (house rule, mass_sobha_offplan.py)"
        rec["size"] = size

        # ---- placement: n towers (DLD no_of_buildings) around the point, clear of real footprints and earlier ghosts
        e0, n0 = TO_UTM(pt["lon"], pt["lat"])
        towers = []
        for t in range(nb if size["basis"] != "none" else 1):
            spot = None
            for r in [0] + list(range(10, 151, 10)):
                angs = [0] if r == 0 else [k * 2 * math.pi / max(8, int(r / 5)) for k in range(max(8, int(r / 5)))]
                for a in angs:
                    cx, cy = e0 + r * math.cos(a), n0 + r * math.sin(a)
                    sq = box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
                    grow = sq.buffer(CLEAR_M)
                    hit_real = [real_idx[j] for j in real_tree.query(grow) if fp_m[real_idx[j]].intersects(grow)]
                    hit_ghost = [g for g in placed_m if g.intersects(grow)]
                    if not hit_real and not hit_ghost:
                        spot = (cx, cy, r, sq); break
                if spot:
                    break
            if not spot:
                sq = box(e0 - side / 2, n0 - side / 2, e0 + side / 2, n0 + side / 2)
                spot = (e0, n0, None, sq)
            cx, cy, moved, sq = spot
            placed_m.append(sq)
            stubs = [i for i, g in enumerate(fp_m) if fp_h[i] <= REAL_H and g.intersects(sq)]
            lon, lat = TO_LL(cx, cy)
            towers.append({"lon": round(lon, 7), "lat": round(lat, 7), "moved_m": moved,
                           "stands_on_placeholder_footprints": stubs[:5], "square_utm": [round(c, 2) for c in sq.bounds]})
        rec["towers"] = towers
        rec["decision"] = "ghosted"
        cands.append(rec)
        for k, t in enumerate(towers):
            ghosts.append((rec, k, t))

    # ---- outputs
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    label = "INDICATIVE ghost - placeholder envelope for a registered pipeline project with no footprint; NOT a surveyed footprint"
    markers, envs = [], []
    for rec, k, t in ghosts:
        s = rec["size"]
        props = {"ghost_id": "g%s_%d" % (rec["project_number"], k), "project_number": rec["project_number"],
                 "name": rec["name"], "developer": rec["developer"], "register_status": rec["status"],
                 "status": "construction" if (rec["percent_completed"] or 0) > 0 else "pipeline",
                 "pctComplete": rec["percent_completed"] or 0.0, "units": rec["units"], "end_date": rec["end_date"],
                 "ghostH": s["height_m"], "ghostW": s["side_m"], "ghostD": s["side_m"], "floors": s["floors"],
                 "size_basis": s["basis"], "size_detail": s["detail"], "position_source": rec["location"]["source"],
                 "position_place": rec["location"]["place"], "position_confidence": rec["location"]["confidence"],
                 "moved_m": t["moved_m"],
                 "indicative": True, "is_footprint": False, "label": label}
        markers.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]}, "properties": props})
        x0, y0, x1, y1 = t["square_utm"]
        ring = [list(TO_LL(x, y)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
        envs.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[round(a, 7), round(b, 7)] for a, b in ring]]},
                     "properties": props})
    meta = {"generated": now, "district": slug, "research_only": True, "label": label}
    json.dump(dict(meta, type="FeatureCollection", features=markers),
              open(os.path.join(out_dir, "ghost_markers.geojson"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(dict(meta, type="FeatureCollection", features=envs),
              open(os.path.join(out_dir, "ghost_envelopes.geojson"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(dict(meta, **cal), open(os.path.join(out_dir, "calibration.json"), "w", encoding="utf-8"), indent=1)
    from collections import Counter
    dec = Counter(c["decision"] for c in cands)
    names_differ = [c for c in cands if c["decision"].startswith("excluded") and c["footprint_evidence"]
                    and all(e.get("names_differ") for e in c["footprint_evidence"] if e["route"] == "lk_twin_binding_register")
                    and any(e["route"] == "lk_twin_binding_register" for e in c["footprint_evidence"])
                    and not any(e["route"] in ("footprint names", "plots.json") for e in c["footprint_evidence"])]
    # excluded by a NAME route only, although a valid location point has no modelled building within 15 m: the binding
    # may be a neighbour carrying this project's name. Kept excluded (a duplicate is worse than a gap) but listed for review.
    name_only = [c for c in cands if c["decision"].startswith("excluded") and c.get("location")
                 and not any(e["route"] == "geometry" for e in c["footprint_evidence"])]
    summary = {"pipeline_projects": len(cands), "decisions": dict(dec), "ghost_towers": len(ghosts),
               "excluded_by_name_but_nothing_modelled_at_its_point": [
                   {"project_number": c["project_number"], "name": c["name"], "routes": c["exclusion_routes"]} for c in name_only],
               "excluded_by_route": dict(Counter(r for c in cands for r in c.get("exclusion_routes", []))),
               "excluded_only_by_a_names_differ_binding": [{"project_number": c["project_number"], "name": c["name"],
                   "bound_to": [e["twin_name"] for e in c["footprint_evidence"] if e["route"] == "lk_twin_binding_register"]} for c in names_differ],
               "size_basis": dict(Counter(c["size"]["basis"] for c in cands if c.get("size")))}
    json.dump(dict(meta, summary=summary, calibration=cal, projects=cands),
              open(os.path.join(out_dir, "candidates.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    print("calibration:", json.dumps(cal["used"]), "backtest constant", json.dumps(cal["backtest_constant_units_per_floor"]),
          "size-aware", json.dumps(cal["backtest_unit_size_aware"]))
    for rec, k, t in ghosts:
        s = rec["size"]
        print("  GHOST %-6s %-34s %-12s %5.1f m  %2d fl  side %4.1f  %-16s moved %s" % (
            rec["project_number"], (rec["name"] or "")[:34], rec["status"], s["height_m"], s["floors"], s["side_m"], s["basis"], t["moved_m"]))
    for c in cands:
        if c["decision"].startswith("not ghosted"):
            print("  NO POINT %-6s %s (%s, %s units)" % (c["project_number"], c["name"], c["status"], c["units"]))
    preview(out_dir, slug, fp_m, fp_h, ghosts, cands)
    print("-> %s" % os.path.relpath(out_dir, ROOT))


def preview(out_dir, slug, fp_m, fp_h, ghosts, cands):
    """Plan view for review: modelled footprints grey, ghost envelopes gold (hatched = indicative), every excluded
    project's point as a small grey cross. Evidence only - never a publish asset."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MPoly
    except Exception as e:
        print("  preview skipped: %s" % e); return
    fig, ax = plt.subplots(figsize=(11, 8), dpi=130)
    for g, h in zip(fp_m, fp_h):
        if g.geom_type != "Polygon":
            continue
        ax.add_patch(MPoly(list(g.exterior.coords), closed=True, fc="#6f7a84" if h > REAL_H else "#c9ccd0", ec="none", alpha=0.9))
    for c in cands:
        loc = c.get("location")
        if loc and c["decision"].startswith("excluded"):
            x, y = TO_UTM(loc["lon"], loc["lat"])
            ax.plot(x, y, "x", color="#444", ms=4, mew=0.8)
    for rec, k, t in ghosts:
        x0, y0, x1, y1 = t["square_utm"]
        ax.add_patch(MPoly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True, fc="#C5A56A", ec="#8a6d2f", alpha=0.55, hatch="//", lw=1.2))
        ax.annotate("%s\n%.0f m (%s)" % ((rec["name"] or "?")[:26], rec["size"]["height_m"], rec["size"]["basis"].replace("_", " ")),
                    ((x0 + x1) / 2, y1 + 12), ha="center", va="bottom", fontsize=7, color="#5a4413")
    xs = [p for g in fp_m for p in (g.bounds[0], g.bounds[2]) if g.bounds[0] > 1e5]
    ys = [p for g in fp_m for p in (g.bounds[1], g.bounds[3]) if g.bounds[1] > 1e6]
    ax.set_xlim(min(xs) - 50, max(xs) + 50); ax.set_ylim(min(ys) - 50, max(ys) + 50)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("%s - pipeline ghosts (gold, hatched) are INDICATIVE envelopes, not footprints. Research only.\n"
                 "grey = modelled footprints (light = 12 m placeholder), x = excluded project already on the twin" % slug, fontsize=9)
    fig.tight_layout(); fig.savefig(os.path.join(out_dir, "ghosts_preview.png")); plt.close(fig)


if __name__ == "__main__":
    main()
