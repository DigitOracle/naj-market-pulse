"""Real heights for the LOD 100 Blocks (30 Sep 2026 overnight job). Scratch script; writes only into this folder.

Stage 1 (this script): join the Dubai Municipality building register (building_summary_information, 2026-09-25) and the
Dubai Land Department buildings register (dld__buildings, 2026-09-25) to footprints, by PARCEL:
  - parcel -> footprint, direct (the 51 districts only): data/identity/official/dld/reg_bindings.json (footprint i -> DLD
    record by name, with its parcel, floors, levels), data/board/plots.json (DLD plot placed on its footprint),
    najma.duckdb building_parcel_dm (DET address plot -> DUID -> footprint, dist <= 25 m, position re-checked);
  - parcel -> point -> footprint, spatial (city-wide): najma.duckdb dm_address_parcel (DET licence addresses carrying
    lat/lon and plot number, averaged per plot), point-in-polygon, else the nearest footprint within 25 m; one-to-one
    (closest claim wins on both sides).
The DM entrance layer (dm_dmgisnet_enterances KML) carries MAKANI, coordinates and community only - no plot, parcel or
building number - so it cannot bridge a register row to a footprint; it is inventoried, not used.
Outputs: links.pkl (every link with its computed height and source) and stage1_report.json.
"""
import json, os, glob, re, math, pickle, statistics, collections, sys
import duckdb
import numpy as np
import shapely
from shapely.geometry import shape, Point
import pyproj
sys.stdout.reconfigure(encoding="utf-8")

REPO = r"C:\Dev\naj-market-pulse"
D = os.path.join(REPO, "data")
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "base_ce")
CITY = os.path.join(D, "blocks_city")
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
DM_CSV = os.path.join(D, "raw_downloads", "dd", "dm__building_summary_information__2026-09-25.csv").replace("\\", "/")
DLD_CSV = os.path.join(D, "raw_downloads", "dd", "dld__buildings__2026-09-25.csv").replace("\\", "/")
PLACEHOLDER = {"unknown", "default12"}
NEAR_M = 25.0


def pkey(v):
    """parcel key = community * 10000 + plot; accepts '3460106.00', '346-106', 3460106"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("0", "0.0"):
        return None
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            return int(a) * 10000 + int(b)
        except ValueError:
            return None
    try:
        k = int(float(s))
        return k if k > 10000 else None
    except ValueError:
        return None


def floors_above(code):
    """'1B+  G  +1M  +10  +2R' -> G(1) + M(1) + 10 = 12 storeys above ground (basements and roof levels not counted)"""
    if not code:
        return None
    n = 0
    for t in code.split("+"):
        t = t.strip().upper()
        m = re.fullmatch(r"(\d*)\s*([A-Z]?)", t)
        if not t or not m:
            continue
        k = int(m.group(1)) if m.group(1) else 1
        s = m.group(2)
        if s in ("B", "R"):
            continue
        if s == "G":
            n += 1
        elif s in ("", "M", "P"):
            n += k
    return n or None


def fnum(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def formula(f, villa):
    return (f * 3.5, "floors*3.5") if villa else (f * 3.2 + 4.0, "floors*3.2+4")


def plausible(h, f):
    if h is None or not (2.5 <= h <= 900):
        return False
    if f:
        if f >= 4:
            return 2.4 <= h / f <= 7.0
        return h <= 8 * f + 12
    return True


# ---------------------------------------------------------------- registers
def load_dm():
    con = duckdb.connect()
    rows = con.sql(f"""select parcel_id, building_id, building_serial_no, building_status_english, building_type_english,
        building_usages_english, building_height, building_floor_height, typical_floors_count, community_no,
        building_completion_date, community_name_english, building_total_area
        from read_csv('{DM_CSV}', all_varchar=true)""").fetchall()
    by_parcel = collections.defaultdict(dict)
    n_all = n_act = 0
    for (pid, bid, ser, st, typ, use, hh, code, tf, cn, comp, cname, tarea) in rows:
        n_all += 1
        if st not in ("New", "Permit Delivered", "Approved") and not (st == "Expired" and comp):
            continue
        k = pkey(pid)
        if not k:
            continue
        n_act += 1
        f = floors_above(code)
        villa = "villa" in (typ or "").lower() or (use or "").strip().lower().startswith("villa")
        h = fnum(hh)
        rec = {"bid": int(float(bid)), "ser": (ser or "").strip(), "type": typ, "use": (use or "").strip(), "h": h, "f": f,
               "villa": villa, "code": (code or "").strip(), "cn": cn, "cname": cname, "status": st, "tarea": fnum(tarea)}
        # one record per building serial on the parcel: the latest building_id (revisions get new ids)
        key = rec["ser"] or ("b%d" % rec["bid"])
        old = by_parcel[k].get(key)
        if old is None or rec["bid"] > old["bid"]:
            by_parcel[k][key] = rec
    print("DM register: %d rows, %d active, %d parcels" % (n_all, n_act, len(by_parcel)), flush=True)
    return {k: list(v.values()) for k, v in by_parcel.items()}, n_all, n_act


def load_dld():
    con = duckdb.connect()
    rows = con.sql(f"""select parcel_id, floors, property_type_en, property_sub_type_en, building_number, project_name_en,
        area_name_en, property_id from read_csv('{DLD_CSV}', all_varchar=true)""").fetchall()
    by_parcel = collections.defaultdict(list)
    for (pid, fl, pt, pst, bno, proj, area, prop) in rows:
        k = pkey(pid)
        if not k:
            continue
        f = fnum(fl)
        by_parcel[k].append({"f": int(f) if f and 0 < f < 200 else None, "villa": (pst or "").lower() == "villa",
                             "bno": (bno or "").strip(), "proj": proj, "area": area, "pid": prop})
    print("DLD register: %d rows, %d parcels" % (len(rows), len(by_parcel)), flush=True)
    return by_parcel, len(rows)


# ---------------------------------------------------------------- footprints
def load_footprints():
    fps = []  # dict(set, slug, i, g (utm), hs, h, n, lonlat centroid)
    for p in sorted(glob.glob(os.path.join(BASE, "*.json"))):
        slug = os.path.basename(p)[:-5]
        fc = json.load(open(p, encoding="utf-8"))
        for f in fc["features"]:
            pr = f["properties"]
            if pr.get("k") != "b":
                continue
            g = shape(f["geometry"])
            if not g.is_valid:
                g = g.buffer(0)
            c = g.centroid
            fps.append({"set": "ce", "slug": slug, "i": pr["i"], "hs": pr["hs"], "h": pr["h"], "n": pr.get("n"),
                        "ll": (c.x, c.y), "g": shapely.transform(g, lambda a: np.column_stack(TO_UTM(a[:, 0], a[:, 1])))})
    n_ce = len(fps)
    for p in sorted(glob.glob(os.path.join(CITY, "*", "blocks.json"))):
        slug = os.path.basename(os.path.dirname(p))
        fc = json.load(open(p, encoding="utf-8"))
        for f in fc["features"]:
            pr = f["properties"]
            if pr.get("k") != "b":
                continue
            g = shape(f["geometry"])
            if not g.is_valid:
                g = g.buffer(0)
            c = g.centroid
            fps.append({"set": "city", "slug": slug, "i": pr["i"], "hs": pr["hs"], "h": pr["h"], "n": pr.get("n"),
                        "ll": (c.x, c.y), "g": shapely.transform(g, lambda a: np.column_stack(TO_UTM(a[:, 0], a[:, 1])))})
    print("footprints: %d ce, %d city" % (n_ce, len(fps) - n_ce), flush=True)
    return fps


# ---------------------------------------------------------------- height for one link
def height_for(k, dm, dld, target_f=None, target_villa=None, fp_area=None):
    """-> (h, src, detail) or (None, reason, detail)"""
    recs = dm.get(k) or []
    cands = []
    for r in recs:
        if plausible(r["h"], r["f"]):
            cands.append((r["h"], "dm_building_height", r))
        elif r["f"]:
            h, s = formula(r["f"], r["villa"])
            cands.append((h, "dm_" + s, r))
    if target_f:
        # a named DLD building on a shared parcel: take the DM building whose storeys agree (+-2), else the DLD floors
        best = None
        for h, s, r in cands:
            if r["f"] and abs(r["f"] - target_f) <= 2:
                if best is None or abs(r["f"] - target_f) < abs(best[2]["f"] - target_f) or (
                        abs(r["f"] - target_f) == abs(best[2]["f"] - target_f) and s == "dm_building_height" and best[1] != s):
                    best = (h, s, r)
        if best:
            return best[0], best[1], {"parcel": k, "bid": best[2]["bid"], "f": best[2]["f"], "n_dm": len(recs)}
        h, s = formula(target_f, bool(target_villa))
        return h, "dld_" + s, {"parcel": k, "f": target_f, "n_dm": len(recs)}
    if len(cands) == 1:
        h, s, r = cands[0]
        return h, s, {"parcel": k, "bid": r["bid"], "f": r["f"], "n_dm": len(recs)}
    if len(cands) > 1:
        hh = sorted(c[0] for c in cands)
        if hh[-1] / hh[0] <= 1.3:
            med = statistics.median(hh)
            srcs = collections.Counter(c[1] for c in cands).most_common(1)[0][0]
            return med, "%s(parcel median of %d)" % (srcs, len(cands)), {"parcel": k, "n_dm": len(recs), "min": hh[0], "max": hh[-1]}
        # several different buildings on the plot: keep the ones whose ground floor (total area / storeys) agrees with
        # this footprint's area within a factor of 2; accept if those agree on height (max/min <= 1.3)
        if fp_area:
            fit = []
            for h, s, r in cands:
                if r.get("tarea") and r["f"]:
                    ratio = (r["tarea"] / r["f"]) / fp_area
                    if 0.5 <= ratio <= 2.0:
                        fit.append((h, s, r))
            if fit:
                h2 = sorted(c[0] for c in fit)
                if h2[-1] / h2[0] <= 1.3:
                    srcs = collections.Counter(c[1] for c in fit).most_common(1)[0][0]
                    return statistics.median(h2), "%s(area-matched %d of %d on parcel)" % (srcs, len(fit), len(cands)), {
                        "parcel": k, "n_dm": len(recs), "min": h2[0], "max": h2[-1]}
        return None, "ambiguous_parcel", {"parcel": k, "n_dm": len(recs), "min": hh[0], "max": hh[-1]}
    lr = [r for r in (dld.get(k) or []) if r["f"]]
    fs = sorted({r["f"] for r in lr})
    if len(fs) == 1:
        h, s = formula(fs[0], any(r["villa"] for r in lr))
        return h, "dld_" + s, {"parcel": k, "f": fs[0], "n_dld": len(lr)}
    if len(fs) > 1:
        return None, "ambiguous_dld_floors", {"parcel": k, "fs": fs[:6]}
    return None, "no_height_on_register", {"parcel": k, "n_dm": len(recs)}


def main():
    dm, n_dm_all, n_dm_act = load_dm()
    dld, n_dld = load_dld()
    fps = load_footprints()
    # DM community of every footprint (its centroid in the DM community polygon) - a parcel key carries its community,
    # so a link whose parcel belongs to another community is wrong (a licence address geocoded elsewhere, a name clash)
    comms = json.load(open(os.path.join(HERE, "..", "city_cache", "communities.json"), encoding="utf-8"))
    cgeo = [shape(c["geom"]) for c in comms]
    ctree = shapely.STRtree(cgeo)
    cents = shapely.points([f["ll"] for f in fps])
    hit = ctree.query(cents, predicate="within")
    for a, b in zip(hit[0], hit[1]):
        fps[a]["comm"] = int(comms[b]["comm_num"])

    def comm_ok(k, j):
        c = fps[j].get("comm")
        if c is None:
            return True
        return k // 10000 == c or (k // 10000) // 10 == c
    idx_of = {(f["set"], f["slug"], f["i"]): j for j, f in enumerate(fps)}
    tree = shapely.STRtree([f["g"] for f in fps])

    links = {}  # footprint j -> link dict (first writer wins: direct bindings before spatial)
    stats = collections.Counter()

    # ---- direct bindings, the 51 districts
    rb = json.load(open(os.path.join(D, "identity", "official", "dld", "reg_bindings.json"), encoding="utf-8"))
    for slug, m in rb.items():
        if slug.startswith("_") or not isinstance(m, dict):
            continue
        for i, b in m.items():
            if not str(i).isdigit() or not isinstance(b, dict):
                continue
            j = idx_of.get(("ce", slug, int(i)))
            k = pkey(b.get("parcel"))
            stats["reg_bindings_rows"] += 1
            if j is None or not k:
                stats["reg_bindings_unusable"] += 1
                continue
            if not comm_ok(k, j):
                stats["reg_bindings_other_community"] += 1
                continue
            tf = b.get("floors") or b.get("levels")
            tf = int(tf) if tf and 0 < float(tf) < 200 else None
            links[j] = {"via": "reg_bindings(" + str(b.get("method")) + ")", "parcel": k, "target_f": tf, "name": b.get("name")}
    stats["links_reg_bindings"] = len(links)
    pj = json.load(open(os.path.join(D, "board", "plots.json"), encoding="utf-8"))
    for f in pj["features"]:
        p = f["properties"]
        j = idx_of.get(("ce", p.get("district"), p.get("i")))
        k = pkey(p.get("parcel"))
        stats["plots_json_rows"] += 1
        if j is None or not k:
            continue
        if not comm_ok(k, j):
            stats["plots_json_other_community"] += 1
            continue
        if j not in links:
            links[j] = {"via": "plots.json", "parcel": k, "target_f": None, "name": p.get("name")}
            stats["links_plots_json"] += 1
    con = duckdb.connect(os.path.join(D, "graph", "najma.duckdb"), read_only=True)
    for (pid, duid, dist, fi, lon, lat, dmd) in con.sql("""select p.parcel_id, p.duid, p.district, b.footprint_i, b.lon, b.lat, p.dist_m
            from building_parcel_dm p join building b using (duid)""").fetchall():
        stats["building_parcel_dm_rows"] += 1
        j = idx_of.get(("ce", dist, fi))
        k = pkey(pid)
        if j is None or not k or (dmd or 0) > NEAR_M:
            continue
        # the DUID's footprint_i must still be the same footprint: its point within 30 m of the footprint
        x, y = TO_UTM(lon, lat)
        if fps[j]["g"].distance(Point(x, y)) > 30:
            stats["building_parcel_dm_moved"] += 1
            continue
        if not comm_ok(k, j):
            stats["building_parcel_dm_other_community"] += 1
            continue
        if j not in links:
            links[j] = {"via": "det_address_dm(%.0fm)" % (dmd or 0), "parcel": k, "target_f": None, "name": None}
            stats["links_building_parcel_dm"] += 1
    bound_parcels = {l["parcel"] for l in links.values()}

    # ---- spatial: DET-located parcels -> footprint (PIP, else nearest <= 25 m), one-to-one
    pts = con.sql("select plot_no, lon, lat, located_rows, comm_num from dm_address_parcel where lon > 54 and lat > 24").fetchall()
    claims = []
    stats["det_parcels_located"] = len(pts)
    for (plot, lon, lat, nloc, cn) in pts:
        k = pkey(plot)
        if not k:
            continue
        x, y = TO_UTM(lon, lat)
        pt = Point(x, y)
        hit = tree.query(pt, predicate="within")
        if len(hit):
            j = int(min(hit, key=lambda q: fps[q]["g"].area))
            claims.append((0.0, k, j, lon, lat))
        else:
            near, dd = tree.query_nearest(pt, max_distance=NEAR_M, return_distance=True)
            if len(near):
                claims.append((float(dd[0]), k, int(near[0]), lon, lat))
            else:
                stats["det_no_footprint_25m"] += 1
    claims.sort()
    used_p, used_f = set(), set(links)
    for dd, k, j, lon, lat in claims:
        if not comm_ok(k, j):
            stats["det_claim_other_community"] += 1
            continue
        if k in used_p or j in used_f:
            stats["det_claim_lost_one_to_one"] += 1
            continue
        used_p.add(k); used_f.add(j)
        links[j] = {"via": "det_point_%s" % ("in" if dd == 0 else "near%.0fm" % dd), "parcel": k, "target_f": None, "name": None,
                    "pt": (lon, lat)}
        stats["links_det_spatial"] += 1
        stats["links_det_spatial_" + fps[j]["set"]] += 1

    # ---- heights
    out = []
    reasons = collections.Counter()
    for j, l in links.items():
        f = fps[j]
        h, src, det = height_for(l["parcel"], dm, dld, l.get("target_f"), None, f["g"].area)
        reasons[src if h is None else "ok"] += 1
        out.append({"set": f["set"], "slug": f["slug"], "i": f["i"], "cur_hs": f["hs"], "cur_h": f["h"], "n": f["n"],
                    "ll": f["ll"], "area": round(f["g"].area, 1), "via": l["via"], "parcel": l["parcel"],
                    "reg_name": l.get("name"), "h": None if h is None else round(h, 2), "src": src, "det": det})
    # register coverage: records (active DM buildings) whose parcel reached a footprint
    linked_parcels = {l["parcel"] for l in links.values()}
    dm_parcels = set(dm)
    rep = {"stats": dict(stats), "height_outcome": dict(reasons),
           "dm_rows": n_dm_all, "dm_active_rows": n_dm_act, "dm_parcels": len(dm_parcels),
           "dm_parcels_linked": len(dm_parcels & linked_parcels),
           "dm_buildings_on_linked_parcels": sum(len(dm[k]) for k in dm_parcels & linked_parcels),
           "dm_buildings_deduped": sum(len(v) for v in dm.values()),
           "dld_rows": n_dld, "dld_parcels": len(dld), "dld_parcels_linked": len(set(dld) & linked_parcels),
           "dld_rows_on_linked_parcels": sum(len(dld[k]) for k in set(dld) & linked_parcels),
           "footprints": {"ce": sum(1 for f in fps if f["set"] == "ce"), "city": sum(1 for f in fps if f["set"] == "city")},
           "links_by_set": dict(collections.Counter(o["set"] for o in out)),
           "links_with_height_by_set": dict(collections.Counter(o["set"] for o in out if o["h"] is not None))}
    pickle.dump({"links": out, "fps_meta": [{k: v for k, v in f.items() if k != "g"} for f in fps]},
                open(os.path.join(HERE, "links.pkl"), "wb"))
    json.dump(rep, open(os.path.join(HERE, "stage1_report.json"), "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
