"""Mass the Sobha Hartland (I) towers the base map does not hold, from the register - the Hartland II method (mass_hartland2.py)
applied to Al Merkadh.

Kendall, 24 Sep 2026: "add the Hartland towers". The Sobha twin audit (scripts/audit_sobha_twin.py) found Crest Grande, One Park
Avenue, Waves Grande, Creek Vistas and Creek Vistas Reserve with a Dubai Municipality building permit on their DLD register
parcel but no footprint in data/ce/sobhaheartland/buildings.geojson: OpenStreetMap never drew them, so the twin showed lawn.

  size      the parcel's DM permit rows (data/board/parcel_buildings_sobhaheartland.json): 'Permit Delivered' rows of
            TOWER_MIN_FLOORS floors or more, one per building id, cancelled rows ignored; capped at the register's building
            count less what the twin already holds for the project. Height = DM height (or floors x 3.2 + 3 m); the
            footprint is a square of the permitted plate (total area / floors), as for Hartland II.
  position  the cached Google Places point for the project (data/geocode_cache.json). Hartland's sister towers share
            points (Crest Grande with The Crest, Waves Grande with Waves, Creek Vistas with Reserve), and the sister is often
            already massed ON that point - so each placeholder takes the first spot, spiralling out from the point in 20 m
            rings to 180 m, where its square (plus 8 m) touches no existing footprint and no other placeholder.
            `position_source` says "google" or "google+nudged N m". A point that is the Hartland community centroid is
            refused (it says nothing about which building).
Every feature carries register_placeholder, parcel_key, project_number and dm_building_id, so build_sobha_mask.py reaches
it by the parcel route and the audit sees a placeholder. Idempotent: earlier Hartland I placeholders are replaced; the file
before the first run is kept as buildings.geojson.bak_prehartland1; the set is also written to hartland1_placeholders.geojson.
Next: python scripts/tile_shp.py sobhaheartland; python scripts/ce_import_tile.py sobhaheartland; the LOD 3 subset export.
Usage: python scripts/mass_hartland1.py [--dry]
"""
import json, math, os, shutil, sys, datetime as dt

import duckdb
from pyproj import Transformer
from shapely.geometry import shape, Point, box
from shapely.ops import transform
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mass_hartland2 import m_to_deg, square, GRAPH, BOARD, GEOCODE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CE_DIR = os.path.join(ROOT, "data", "ce", "sobhaheartland")
GEOJSON = os.path.join(CE_DIR, "buildings.geojson")
PLACEHOLDERS = os.path.join(CE_DIR, "hartland1_placeholders.geojson")
AREA = "Al Merkadh"
SOBHA_DEVS = (966, 87, 283, 89, 1314, 819, 2351, 381)
TOWER_MIN_FLOORS = 10
CENTROID = (55.3110391, 25.1766361)           # "Sobha Hartland, Award-Winning Green Community" - the community, not a building
GOOGLE_KEYS = {
    2482: "goog::Sobha Hartland - Crest Grande, SOBHA HEARTLAND, Dubai, United Arab Emirates",
    2166: "goog::Sobha Hartland One Park Avenue, SOBHA HEARTLAND, Dubai, United Arab Emirates",
    2305: "goog::Sobha Hartland Waves Grande, SOBHA HEARTLAND, Dubai, United Arab Emirates",
    2178: "goog::Sobha Creek vistas Reserve, SOBHA HEARTLAND, Dubai, United Arab Emirates",
    2066: "goog::Sobha Creek Vistas, SOBHA HEARTLAND, Dubai, United Arab Emirates",
}
PARCELS = {2482: "3470896", 2166: "3474829", 2305: "3473941", 2178: "3474775", 2066: "3474774"}
TAG = "hartland1"
CLAIM_M = 120.0
CLAIMS = os.path.join(ROOT, "data", "identity", "sobha_footprint_claims.json")
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
to_ll = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform


def towers(records, cap):
    seen, out = set(), []
    for r in sorted(records, key=lambda r: -int(r.get("floors_above") or 0)):
        fl = int(r.get("floors_above") or 0)
        if fl < TOWER_MIN_FLOORS or r.get("status") != "Permit Delivered" or r.get("building_id") in seen:
            continue
        seen.add(r.get("building_id")); out.append(r)
    return out[:max(0, cap)]


def main():
    dry = "--dry" in sys.argv
    projects = {}
    try:
        con = duckdb.connect(GRAPH, read_only=True)
        for pn, name, status, pk, nb in con.execute("""
            select p.project_number, any_value(t.project_name_en), any_value(p.project_status),
                   cast(cast(l.parcel_id as bigint) as varchar), any_value(p.no_of_buildings)
            from gov_dld__land_registry l join gov_dld__projects p using(project_id)
            left join (select project_number, any_value(project_name_en) project_name_en from gov_dld__transactions group by 1) t using(project_number)
            where p.developer_number in %s and l.area_name_en = ? and coalesce(p.no_of_buildings, 0) > 0
            group by 1, 4 order by 1""" % (SOBHA_DEVS,), [AREA]).fetchall():
            projects.setdefault(int(pn), {"name": (name or "").strip(), "status": status, "buildings": nb, "parcels": []})["parcels"].append(pk)
    except duckdb.IOException:
        # the graph store is held by a writer (another session's ingest): the register parcels of these five, as read from
        # gov_dld__land_registry on 24 Sep 2026, and the rest from data/identity/sobha_projects.json
        reg = {p["project_number"]: p for p in json.load(open(os.path.join(ROOT, "data", "identity", "sobha_projects.json"), encoding="utf-8"))["projects"]}
        for pn, pk in PARCELS.items():
            r = reg[pn]
            projects[pn] = {"name": r["name_en"], "status": r["status"], "buildings": r.get("buildings"), "parcels": [pk]}
    dm = json.load(open(os.path.join(BOARD, "parcel_buildings_sobhaheartland.json"), encoding="utf-8"))["parcels"]
    geo = json.load(open(GEOCODE, encoding="utf-8"))
    mask = json.load(open(os.path.join(BOARD, "sobha_mask.json"), encoding="utf-8"))
    have = {p["project_number"]: p["footprints"] for p in mask["projects"]}

    fc = json.load(open(GEOJSON, encoding="utf-8"))
    keep = [f for f in fc["features"] if (f.get("properties") or {}).get("placeholder_set") != TAG]
    obstacles = [transform(to_utm, shape(f["geometry"])).buffer(0) for f in keep if f.get("geometry")]
    tree = STRtree(obstacles)
    placed = []

    def free(sq):
        g = sq.buffer(8.0)
        if any(obstacles[int(j)].intersects(g) for j in tree.query(g)):
            return False
        return not any(p.intersects(g) for p in placed)

    features, report = [], []
    claimed_mask = set((mask["districts"].get("sobhaheartland") or {}).get("by_i") or {})
    stack = json.load(open(os.path.join(BOARD, "stack_sobhaheartland.json"), encoding="utf-8")).get("buildings_by_id") or {}
    from build_sobha_mask import is_sobha_name
    claimed = {}
    for pn, key in GOOGLE_KEYS.items():
        p = projects.get(pn)
        if not p:
            report.append((pn, "?", "not a Sobha Al Merkadh register project - skipped")); continue
        e = geo.get(key) or {}
        if e.get("lon") is None:
            report.append((pn, p["name"], "no Google point - skipped")); continue
        if abs(e["lon"] - CENTROID[0]) < 1e-5 and abs(e["lat"] - CENTROID[1]) < 1e-5:
            report.append((pn, p["name"], "Google point is the community centroid - refused")); continue
        recs = [r for pk in p["parcels"] for r in (dm.get(pk) or [])]
        cap = int(p["buildings"] or 1) - int(have.get(pn) or 0)
        tw = towers(recs, cap)
        if not tw:
            report.append((pn, p["name"], "nothing to add (register %s, twin %s, DM towers %d)" % (p["buildings"], have.get(pn), len(towers(recs, 99))))); continue
        ex, ny = to_utm(e["lon"], e["lat"])
        status = "construction" if p["status"] == "ACTIVE" else "existing"
        # the tower may already be massed - unnamed, from OSM, standing on the Google point (One Park Avenue: 110 m on the
        # point, permit 103 m). An unclaimed footprint within CLAIM_M whose height is within 35% of the permit is that tower:
        # claim it (build_sobha_mask.py "claim" route) instead of drawing a second one beside it.
        gp = Point(ex, ny); rest = []
        for t in tw:
            h0 = float(t.get("height_m") or int(t["floors_above"]) * 3.2 + 3)
            cands = []
            for i, f in enumerate(keep):
                if str(i) in claimed_mask or i in claimed:
                    continue
                hb = float((f.get("properties") or {}).get("bHeight") or 0)
                if not (0.65 * h0 <= hb <= 1.35 * h0) or not f.get("geometry"):
                    continue
                # the DM binding already names it for somebody else's building (502 = Maybach Six Tower A, 1340 = Vision
                # Iconic): not ours, whatever Google says - build_sobha_mask.py's geocode guard learned this the same way
                sn = ((stack.get(str(i)) or {}).get("name") or "").strip()
                if sn and not is_sobha_name(sn):
                    continue
                d = transform(to_utm, shape(f["geometry"])).distance(gp)
                if d <= CLAIM_M:
                    cands.append((d, i, hb))
            if cands:
                d, i, hb = min(cands)
                claimed[i] = {"project_number": pn, "name": p["name"], "dm_building_id": t["building_id"],
                              "basis": "unclaimed %.0f m footprint %.0f m from the Google point (%s); DM permit %d floors, %.0f m" % (hb, d, key[6:60], int(t["floors_above"]), h0)}
                report.append((pn, p["name"], "CLAIMED existing footprint %d (%.0f m tall, %.0f m from the point)" % (i, hb, d)))
            else:
                rest.append(t)
        tw = rest
        for k, t in enumerate(tw):
            fl = int(t["floors_above"]); h = float(t.get("height_m") or fl * 3.2 + 3)
            plate = float(t.get("area_sqm") or 0) / fl if t.get("area_sqm") else 900.0
            side = max(18.0, min(60.0, math.sqrt(plate)))
            spot = None
            for r in [0.0] + [20.0 * i for i in range(1, 10)]:
                for a in ([0] if r == 0 else range(0, 360, 20)):
                    cx, cy = ex + r * math.cos(math.radians(a)), ny + r * math.sin(math.radians(a))
                    sq = box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
                    if free(sq):
                        spot = (cx, cy, r, sq); break
                if spot:
                    break
            if not spot:
                report.append((pn, p["name"], "no free spot within 180 m of the Google point - skipped")); continue
            cx, cy, r, sq = spot
            placed.append(sq)
            lon, lat = to_ll(cx, cy)
            name = p["name"] + ("" if len(tw) == 1 else " - tower %d" % (k + 1))
            src = "google" if r == 0 else "google+nudged %d m" % r
            features.append({"type": "Feature", "geometry": square(lon, lat, side), "properties": {
                "status": status, "bHeight": round(h, 1), "name": name, "levels": str(fl),
                "height_source": "dm_register", "height_basis": "DM building %s: %d permitted floors, %.1f m" % (t["building_id"], fl, h),
                "footprint_basis": "square of the permitted plate (%.0f m2 / %d floors = %.0f m2)" % (float(t.get("area_sqm") or 0), fl, plate),
                "position_source": src, "position_basis": key, "register_placeholder": True, "placeholder_set": TAG,
                "parcel_key": p["parcels"][0], "project_number": pn, "dm_building_id": t["building_id"], "dm_units": t.get("units"),
                "developer": "sobha"}})
            report.append((pn, name, "%d fl, %.0f m, side %.0f m, %s, %s" % (fl, h, side, status, src)))
    print("Hartland I: %d existing footprints claimed, %d placeholder towers" % (len(claimed), len(features)))
    for r in report:
        print("  %5s %-36s %s" % (r[0], r[1][:36], r[2]))
    if dry:
        return
    cl = json.load(open(CLAIMS, encoding="utf-8")) if os.path.exists(CLAIMS) else {"note": "footprints claimed for a Sobha project by evidence other than parcel/DM keys; read by build_sobha_mask.py (claim route)", "districts": {}}
    cl["districts"]["sobhaheartland"] = {str(i): v for i, v in sorted(claimed.items())}
    json.dump(cl, open(CLAIMS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-> %s: %d claims for sobhaheartland" % (CLAIMS, len(claimed)))
    if not features:
        return
    bak = GEOJSON + ".bak_prehartland1"
    if not os.path.exists(bak):
        shutil.copyfile(GEOJSON, bak)
    fc["features"] = keep + features
    json.dump(fc, open(GEOJSON, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"type": "FeatureCollection", "generated": dt.datetime.now().isoformat(timespec="seconds"), "features": features},
              open(PLACEHOLDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-> %s: %d features (%d placeholders appended at indices %d..%d)" % (GEOJSON, len(fc["features"]), len(features), len(keep), len(fc["features"]) - 1))


if __name__ == "__main__":
    main()
