"""City-wide LOD 100 Blocks for every Dubai Municipality community not already modelled in data/ce/<slug>.

Boundaries: DM community polygons, data/raw_downloads/dda/prod/dm__dm_community-open-api.kml (snapshot 28 Sep 2026).
Footprints: Overture Maps buildings (latest release; OSM + Microsoft ML + Esri), one per representative point in the community.
Heights, in order: data/blocks_city/<slug>/heights_overlay.json when present ({"<i>": {"h", "src", "c": [lon, lat]}}, hs = its
src; written by scratchpad/hts/hts_write.py from the DM / DLD registers, type hints and the community median; an entry is used
only when its centroid "c" is within ~3 m of this footprint's, so a changed footprint list never takes a stale height) ->
Overture height (hs "overture_height") -> Overture num_floors x 3.2 m ("overture_floors") -> OSM height tag
("osm_height") / building:levels x 3.2 m ("osm_levels") matched by the OSM centre falling inside the footprint -> typical by
building class ("typical_villa" 8 m, "typical_warehouse" 10 m, "typical_small" 3.5 m) -> 12 m ("default12", unknown).
Buildings that fall inside an existing district's footprint zone (data/ce, closing of footprints: +40 m / -25 m) are left out,
so these files never double-draw what data/ce/<slug>/blocks.json already draws. A community whose buildings are >= 85 % in
existing districts is skipped (status "exists"). Streets: OSM highway ways, clipped to the boundary + 300 m.
Writes ONLY data/blocks_city/<slug>/{blocks.json,boundary.geojson,meta.json} and data/blocks_city/INDEX.json.
"""
import json, os, sys, gzip, glob, time, shutil, pickle, math, datetime
import duckdb
import numpy as np
import shapely
from shapely.geometry import shape, mapping, box, Point, LineString, MultiLineString
from shapely.ops import transform, unary_union
from shapely import wkb as swkb
import pyproj
sys.stdout.reconfigure(encoding="utf-8")

CACHE = r"C:\Users\kwils\AppData\Local\Temp\claude\C--Users-kwils-Downloads\cfd69a2f-a784-4bee-87d0-17cb12cabffb\scratchpad\city_cache"
OSM = os.path.join(CACHE, "osm")
REPO = r"C:\Dev\naj-market-pulse"
OUT = os.path.join(REPO, "data", "blocks_city")
CE = os.path.join(REPO, "data", "ce")
KML_META = os.path.join(REPO, "data", "raw_downloads", "dda", "prod", "dm__dm_community-open-api.kml.meta.json")
TODAY = datetime.date.today().isoformat()
DP = 6
FLOOR_M = 3.2
SKIP_SHARE = 0.85
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
TO_LL = pyproj.Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform

VILLA = {"house", "detached", "semidetached_house", "terrace", "villa", "bungalow", "residential_house", "farm", "static_caravan"}
WARE = {"warehouse", "industrial", "manufacture", "hangar", "factory", "storage", "shed_industrial", "transportation", "service"}
SMALL = {"garage", "garages", "shed", "carport", "roof", "hut", "cabin", "kiosk", "toilets", "guardhouse", "parking_shelter", "container"}
ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified", "living_street"]
LINKABLE = {"motorway", "trunk", "primary", "secondary", "tertiary"}
TYPICAL = [(VILLA, 8.0, "typical_villa"), (WARE, 10.0, "typical_warehouse"), (SMALL, 3.5, "typical_small")]

PRIORITY = [
    # Deira
    "alrigga", "almuraqqabat", "naif", "almurar", "albaraha", "cornichedeira", "almuteena", "horalanz", "abuhail", "portsaeed",
    "alras", "alsabkha", "albuteen", "aldaghaya", "ayalnasir", "riggatalbuteen", "alkhabaisi", "alcorniche", "alwuheida",
    "horalanzeast", "almamzar", "alhamriyaport", "algarhoud", "ummramool",
    # Bur Dubai, Karama
    "alsouqalkabeer", "alhamriya", "mankhool", "alraffa", "ummhurairfirst", "ummhurairsecond", "oudmetha", "alshindagha",
    "alhudaiba", "aljafiliya", "alkifaf", "alkarama",
    # Al Barsha, Mirdif, Al Qusais, Al Nahda, Muhaisnah, Rashidiya
    "albarshafirst", "albarshasecond", "albarshathird", "albarshasouthfirst", "mirdif", "mushraif", "alqusais", "alnahdafirst",
    "alnahdasecond", "muhaisanahsecond", "muhaisnahfirst", "muhaisanahthird", "muhaisanahfourth", "muhaisanahfifth",
    "alrashidiya", "naddshamma", "altwarfirst", "altwarsecond", "altwarthird", "altwarfourth", "altwarfifth",
    "almizharfirst", "almizharsecond", "almizharthird", "almizharfourth", "oudalmuteena",
    # Nad Al Sheba, MBR City
    "naddalshibasecond", "naddalshibathird", "naddalshibafourth", "naddalshibafirst", "almerkadh",
    # Jumeirah, Umm Suqeim, Al Safa, Al Wasl area
    "jumeirafirst", "jumeirasecond", "jumeirathird", "albada", "ummsuqeimfirst", "ummsuqeimsecond", "ummsuqeimthird",
    "alsafafirst", "alsafasecond", "almanara", "ummalsheif", "alsafouhfirst", "alsafouhsecond", "tradecenterfirst",
    "tradecentersecond", "zaabeelfirst", "zaabeelsecond",
    # International City, Warqa, Warsan
    "warsanfirst", "warsansecond", "warsanfourth", "alwarqaafirst", "alwarqaasecond", "alwarqaathird", "alwarqaafourth",
    "alwarqaafifth", "naddalhamar",
    # Springs / Meadows / Lakes / Emirates Hills / JLT side
    "althanyahfourth", "althanyahthird", "althanyahsecond", "althanyahfirst",
    # Discovery Gardens / Al Furjan, Arabian Ranches, Mudon, Remraam, Damac Lagoons, Tilal Al Ghaf, Dubai South, Creek
    "jabalalifirst", "jabalalisecond", "wadialsafa6", "wadialsafa7", "alhebiahsixth", "alhebiahthird", "alhebiahfifth",
    "alyalayis1", "alyalayis2", "madinatalmataar", "alkheeranfirst", "alkheeran", "aljadaf", "wadialsafa2", "wadialsafa3",
    "hadaeqsheikhmohammedbinrashid", "meaisemsecond", "madinathind1", "madinathind2", "madinathind3", "alyufrah2",
]


def free_gb():
    return shutil.disk_usage("C:\\").free / 1e9


def r6(v):
    return round(float(v), DP)


def ring_ll(coords):
    out = []
    for c in coords:
        p = [r6(c[0]), r6(c[1])]
        if not out or p != out[-1]:
            out.append(p)
    if len(out) >= 2 and out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def geom_out(g):
    polys = [g] if g.geom_type == "Polygon" else list(g.geoms) if g.geom_type == "MultiPolygon" else []
    rr = []
    for p in polys:
        ext = ring_ll(p.exterior.coords)
        if not ext:
            continue
        rings = [ext] + [x for x in (ring_ll(i.coords) for i in p.interiors) if x]
        rr.append(rings)
    if not rr:
        return None
    return {"type": "Polygon", "coordinates": rr[0]} if len(rr) == 1 else {"type": "MultiPolygon", "coordinates": rr}


def load_tiles(kind, bb):
    """elements of every cached tile (recursing into split tiles) touching bb=(x0,y0,x1,y1); None if a tile is missing."""
    S = 0.1
    els, missing = [], []

    def load(path):
        if not os.path.exists(path):
            missing.append(path); return
        d = json.load(gzip.open(path, "rt", encoding="utf-8"))
        if d.get("split"):
            base = path[:-len(".json.gz")]
            for q in range(4):
                load(base + "q%d.json.gz" % q)
        else:
            els.extend(d.get("elements") or [])
    for ix in range(int(math.floor(bb[0] / S)), int(math.floor(bb[2] / S)) + 1):
        for iy in range(int(math.floor(bb[1] / S)), int(math.floor(bb[3] / S)) + 1):
            load(os.path.join(OSM, "%s_%d_%d.json.gz" % (kind, ix, iy)))
    return (None, missing) if missing else (els, [])


def num(v):
    try:
        s = str(v).lower().replace("m", "").replace(",", ".").strip().split(";")[0].split()[0]
        x = float(s)
        return x if x > 0 else None
    except Exception:
        return None


def load_index():
    p = os.path.join(OUT, "INDEX.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return None


def save_index(idx):
    idx["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    comms = idx["communities"]
    idx["totals"] = {
        "communities": len(comms),
        "built": sum(1 for c in comms.values() if c["status"] == "built"),
        "exists": sum(1 for c in comms.values() if c["status"] == "exists"),
        "empty": sum(1 for c in comms.values() if c["status"] == "empty"),
        "pending": sum(1 for c in comms.values() if c["status"].startswith("pending")),
        "failed": sum(1 for c in comms.values() if c["status"] == "failed"),
        "buildings": sum(c.get("buildings", 0) for c in comms.values() if c["status"] == "built"),
        "streets": sum(c.get("streets", 0) for c in comms.values() if c["status"] == "built"),
    }
    tmp = os.path.join(OUT, "INDEX.json.tmp")
    json.dump(idx, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(OUT, "INDEX.json"))


def main():
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    comms = json.load(open(os.path.join(CACHE, "communities.json"), encoding="utf-8"))
    ce_slugs = {s for s in os.listdir(CE) if not s.startswith("_") and os.path.isdir(os.path.join(CE, s))}
    kml_meta = json.load(open(KML_META, encoding="utf-8"))
    dmreg = json.load(open(os.path.join(CACHE, "dm_register_stats.json"), encoding="utf-8"))
    idx = load_index() or {
        "note": "City-wide LOD 100 Blocks for every Dubai Municipality community outside the data/ce districts. "
                "status: built | exists (>=85% of its buildings already in data/ce districts) | empty (no buildings) | pending_* | failed. "
                "A slug ending _rest is a DM community whose DM slug equals an existing data/ce slug: it holds only the buildings "
                "OUTSIDE the existing district, so the two never double-draw.",
        "boundary_source": "Dubai Municipality community polygons (data.dubai open data, dm_community-open-api, snapshot %s): "
                           "data/raw_downloads/dda/prod/dm__dm_community-open-api.kml" % kml_meta.get("snapshot"),
        "footprint_source": "Overture Maps Foundation buildings (overturemaps CLI, latest release, downloaded %s): OpenStreetMap (ODbL), "
                            "Microsoft ML Buildings (ODbL), Esri Community Maps (CDLA-Permissive 2.0)" % TODAY,
        "communities": {}}
    idx["street_source"] = ("OpenStreetMap contributors (ODbL) highway ways via the Overture Maps transportation theme (segments, "
                            "downloaded %s); classes motorway..tertiary (+_link), residential, unclassified, living_street; "
                            "clipped to boundary + 300 m. Overpass was tried first and was returning 504s, so it was stopped." % TODAY)
    idx["height_rule"] = ("heights_overlay.json (register_* = DM/DLD register height or storeys joined by parcel; typical_<type> "
                          "= type hints; community_median = DM register median for the community, never measured) -> Overture height ->Overture num_floors x 3.2 m (OSM building:levels) -> typical by building class "
                          "(typical_villa 8 m, typical_warehouse 10 m, typical_small 3.5 m) -> default12 (unknown, 12 m placeholder)")

    order = {s: i for i, s in enumerate(PRIORITY)}
    cen = (55.30, 25.20)
    comms.sort(key=lambda c: (order.get(c["slug"], 999), (c["bbox"][0] - cen[0]) ** 2 + (c["bbox"][1] - cen[1]) ** 2))
    if only:
        comms = [c for c in comms if c["slug"] in only]

    zones = pickle.load(open(os.path.join(CACHE, "existing_zones.pkl"), "rb"))["zones"]
    zone_names = list(zones.keys())
    zone_tree = shapely.STRtree([zones[s] for s in zone_names])

    print("loading Overture ...", flush=True)
    con = duckdb.connect()
    con.sql("install spatial; load spatial;")
    q = ("select id, names.primary as nm, height, num_floors, class, subtype, is_underground, "
         "ST_AsWKB(geometry) as g, sources[1].dataset as ds from read_parquet(['%s','%s'])" %
         (os.path.join(CACHE, "overture_buildings_mainland.parquet").replace("\\", "/"),
          os.path.join(CACHE, "overture_buildings_hatta.parquet").replace("\\", "/")))
    rows = con.sql(q).fetchall()
    print("  %d Overture buildings" % len(rows), flush=True)
    geoms = shapely.from_wkb([bytes(r[7]) for r in rows])
    reps = shapely.point_on_surface(geoms)
    rep_tree = shapely.STRtree(reps)
    reps_utm = shapely.transform(reps, lambda a: np.column_stack(TO_UTM(a[:, 0], a[:, 1])))
    # existing-zone membership per building (UTM points)
    in_zone = np.full(len(rows), "", dtype=object)
    hits = zone_tree.query(reps_utm, predicate="within")
    for bi, zi in zip(hits[0], hits[1]):
        in_zone[bi] = zone_names[zi]
    print("  %d buildings inside existing district zones" % int((in_zone != "").sum()), flush=True)
    sq = ("select class, subclass, coalesce(names.common['en'], names.primary) as nm, ST_AsWKB(geometry) "
          "from read_parquet(['%s','%s']) where subtype='road' and class in (%s)" %
          (os.path.join(CACHE, "overture_segments_mainland.parquet").replace("\\", "/"),
           os.path.join(CACHE, "overture_segments_hatta.parquet").replace("\\", "/"),
           ",".join("'%s'" % x for x in ROAD_CLASSES)))
    srows = con.sql(sq).fetchall()
    seg_geoms = shapely.from_wkb([bytes(r[3]) for r in srows])
    seg_attr = [((r[0] + "_link") if r[1] == "link" and r[0] in LINKABLE else r[0], (r[2] or "").strip() or None) for r in srows]
    seg_tree = shapely.STRtree(seg_geoms)
    print("  %d Overture road segments" % len(srows), flush=True)

    for c in comms:
        slug = c["slug"]
        prev = idx["communities"].get(slug) or idx["communities"].get(slug + "_rest")
        if prev and prev["status"] in ("built", "exists", "empty") and not force:
            continue
        if free_gb() < 5:
            print("DISK under 5 GB - stopping", flush=True)
            break
        t0 = time.time()
        poly = shape(c["geom"])
        entry = {"comm_num": c["comm_num"], "name": c["name"], "name_ar": c["name_ar"], "dm_slug": slug,
                 "area_km2": c["area_km2"], "bbox": [round(v, 5) for v in c["bbox"]]}
        try:
            cand = rep_tree.query(poly, predicate="contains")
            cand = np.sort(cand)
            total = len(cand)
            ex = [i for i in cand if in_zone[i]]
            ex_by = {}
            for i in ex:
                ex_by[in_zone[i]] = ex_by.get(in_zone[i], 0) + 1
            keep = [i for i in cand if not in_zone[i]]
            entry.update({"overture_in_boundary": int(total), "in_existing_districts": len(ex), "existing_by_slug": ex_by})
            share = len(ex) / total if total else 0.0
            entry["existing_share"] = round(share, 3)
            out_slug = slug + "_rest" if (slug in ce_slugs and ex) or (slug in ce_slugs) else slug
            entry["slug"] = out_slug
            if total and share >= SKIP_SHARE:
                entry["status"] = "exists"
                entry["note"] = "%.0f%% of its buildings already modelled in data/ce (%s)" % (share * 100, ", ".join(sorted(ex_by)))
                idx["communities"][slug] = entry; save_index(idx)
                print("%-32s exists (%.0f%% in %s)" % (slug, share * 100, ",".join(sorted(ex_by))), flush=True)
                continue
            buf = transform(TO_LL, transform(TO_UTM, poly).buffer(300))
            lv_tree = None  # OSM building:levels / height reach us as Overture num_floors / height (Overture carries the OSM tags)

            feats, hs_count, fp_src = [], {}, {}
            n_named = 0
            ov_path = os.path.join(OUT, out_slug, "heights_overlay.json")
            overlay = json.load(open(ov_path, encoding="utf-8")) if os.path.exists(ov_path) else {}
            n_ov = n_ov_stale = 0
            lo = [999, 999, -999, -999]
            for i in keep:
                r = rows[i]
                if r[6]:  # underground
                    continue
                g = geoms[i]
                if not g.is_valid:
                    g = g.buffer(0)
                geo = geom_out(g)
                if not geo:
                    continue
                h, hs = None, None
                ov = overlay.get(str(len(feats)))
                if ov and ov.get("h"):
                    cc = ov.get("c")
                    gc = g.centroid
                    if not cc or (abs(gc.x - cc[0]) < 3e-5 and abs(gc.y - cc[1]) < 3e-5):
                        h, hs = float(ov["h"]), str(ov.get("src") or "overlay")
                        n_ov += 1
                    else:
                        n_ov_stale += 1
                if h is not None:
                    pass
                elif r[2] and 2 <= r[2] <= 900:
                    h, hs = r[2], "overture_height"
                elif r[3] and 0 < r[3] <= 200:
                    h, hs = r[3] * FLOOR_M, "overture_floors"
                elif lv_tree is not None:
                    m = lv_tree.query(g, predicate="contains")
                    if len(m):
                        h, hs = lv_vals[int(m[0])]
                if h is None:
                    cls = (r[4] or "").lower()
                    for S_, hv, tag in TYPICAL:
                        if cls in S_:
                            h, hs = hv, tag; break
                if h is None:
                    h, hs = 12.0, "default12"
                props = {"k": "b", "i": len(feats), "h": round(float(h), 1), "hs": hs}
                nm = (r[1] or "").strip()
                if nm:
                    props["n"] = nm; n_named += 1
                hs_count[hs] = hs_count.get(hs, 0) + 1
                fp_src[r[8] or "?"] = fp_src.get(r[8] or "?", 0) + 1
                feats.append({"type": "Feature", "properties": props, "geometry": geo})
                x0, y0, x1, y1 = g.bounds
                lo = [min(lo[0], x0), min(lo[1], y0), max(lo[2], x1), max(lo[3], y1)]
            nb = len(feats)
            # streets clipped to boundary + 300 m
            shapely.prepare(buf)
            st_feats = []
            for si in np.sort(seg_tree.query(buf, predicate="intersects")):
                ln = seg_geoms[si]
                hwc, nm = seg_attr[si]
                t = {"highway": hwc}
                if nm:
                    t["name"] = nm
                cl = ln if buf.contains(ln) else ln.intersection(buf)
                parts = [cl] if cl.geom_type == "LineString" else [p for p in getattr(cl, "geoms", []) if p.geom_type == "LineString"]
                for p in parts:
                    line = []
                    for x, y in p.coords:
                        qq = [r6(x), r6(y)]
                        if not line or qq != line[-1]:
                            line.append(qq)
                    if len(line) < 2:
                        continue
                    props = {"k": "s", "hw": t.get("highway")}
                    nm = t.get("name:en") or t.get("name")
                    if nm:
                        props["nm"] = nm
                    st_feats.append({"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": line}})
            n_st = len(st_feats)
            if nb == 0:
                entry["status"] = "empty"
            else:
                entry["status"] = "built"
            n_def = hs_count.get("default12", 0)
            n_typ = sum(v for k, v in hs_count.items() if k.startswith("typical_"))
            meta = {"slug": out_slug, "dm_slug": slug, "comm_num": c["comm_num"], "name": c["name"], "name_ar": c["name_ar"],
                    "v": 1, "generated": TODAY, "lod": 100,
                    "bbox": [r6(v) for v in (lo if nb else poly.bounds)], "buildings": nb, "named": n_named, "streets": n_st,
                    "height_sources": hs_count, "default_height_share": round(n_def / nb, 3) if nb else None,
                    "typical_height_share": round(n_typ / nb, 3) if nb else None,
                    "footprint_sources": fp_src,
                    "heights_overlay": {"applied": n_ov, "stale_skipped": n_ov_stale, "entries": len(overlay)},
                    "community_median_share": round(hs_count.get("community_median", 0) / nb, 3) if nb else None,
                    "dm_register_check": dict(dmreg.get(str(int(c["comm_num"])), {}), note="DM building_summary_information 2026-08-31 (New/Permit Delivered/Approved) for this community; no geometry, sanity check only"),
                    "excluded_in_existing_districts": len(ex), "existing_by_slug": ex_by,
                    "sources": "boundary: Dubai Municipality community %s (dm_community-open-api, snapshot %s); footprints and "
                               "heights/floors: Overture Maps buildings (OSM ODbL, Microsoft ML Buildings ODbL, Esri CDLA-P-2.0); "
                               "OSM height / building:levels carried by Overture; streets: OpenStreetMap contributors (ODbL) highway "
                               "ways as served by the Overture transportation theme (segments, class -> hw, link subclass -> <class>_link), clipped "
                               "to boundary + 300 m; heights: h in metres, floors x %.1f m, hs=default12 means unknown (12 m placeholder)"
                               % (c["comm_num"], kml_meta.get("snapshot"), FLOOR_M)}
            d = os.path.join(OUT, out_slug)
            os.makedirs(d, exist_ok=True)
            fc = {"type": "FeatureCollection", "meta": {k: meta[k] for k in ("slug", "v", "generated", "bbox", "buildings", "named", "streets", "sources")},
                  "features": feats + st_feats}
            txt = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
            open(os.path.join(d, "blocks.json"), "w", encoding="utf-8").write(txt)
            gz = len(gzip.compress(txt.encode("utf-8"), 6))
            bnd = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
                "comm_num": c["comm_num"], "name": c["name"], "name_ar": c["name_ar"], "dgis_id": c["dgis_id"], "slug": out_slug,
                "area_km2": c["area_km2"]}, "geometry": c["geom"]}]}
            json.dump(bnd, open(os.path.join(d, "boundary.geojson"), "w", encoding="utf-8"), ensure_ascii=False)
            meta["bytes"] = len(txt.encode("utf-8")); meta["gzip_bytes"] = gz
            json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            entry.update({"buildings": nb, "streets": n_st, "named": n_named, "default_share": meta["default_height_share"],
                          "typical_share": meta["typical_height_share"], "height_sources": hs_count,
                          "dm_register_buildings": meta["dm_register_check"].get("dm_buildings"),
                          "dm_register_median_h": meta["dm_register_check"].get("median_h"),
                          "bytes": meta["bytes"], "gzip_bytes": gz, "dir": "data/blocks_city/%s" % out_slug})
            entry.pop("missing_tiles", None)
            idx["communities"][slug] = entry; save_index(idx)
            print("%-32s %-8s b=%6d def=%5.1f%% st=%5d %.1fMB %.0fs" % (out_slug, entry["status"], nb,
                  100 * (meta["default_height_share"] or 0), n_st, meta["bytes"] / 1e6, time.time() - t0), flush=True)
        except Exception as e:
            import traceback; traceback.print_exc()
            entry["status"] = "failed"; entry["error"] = repr(e)[:300]
            idx["communities"][slug] = entry; save_index(idx)
    save_index(idx)
    print("TOTALS", json.dumps(idx["totals"]), flush=True)


main()
