"""Mass Sobha Hartland II (Bukadra) from the register, because OSM has nothing there yet.

Kendall, 23 Sep 2026: "start with item 2, mass Hartland II". The bukadra tile was massed from OpenStreetMap, and OSM
does not hold the Riverside Crescent towers, Skyscape or Skyvue - the live Overpass probe (23 Sep) returns Azizi Riviera
and warehouses in that box and nothing of Sobha's, and the tile's own extent stops at 55.3233 E, west of the site. The
twin therefore shows Sobha's biggest current seller as empty ground, and build_sobha_mask.py reports every Hartland II
scheme as "nothing massed where it stands".

What this does: one placeholder mass per PERMITTED TOWER, from official records only -
  size      Dubai Municipality building record on the project's register parcel (data/board/parcel_buildings_bukadra.json,
            reached through the DLD land registry's parcel_id): permitted floors, height, total area, units. The plate is
            total area / floors and the footprint is a square of that plate, so the mass has the tower's real bulk. The DM
            register carries several rows per tower (permit revisions with the same floors and near-identical areas); the
            'Permit Delivered' row, or the newest, is the tower, and the 5-storey rows are podium and are skipped.
  status    from the DLD project register: ACTIVE -> construction, NOT_STARTED / PENDING -> pipeline.
  position  the weakest link, and said so on every feature (`position_source`):
              google    the cached Google Places point for the project name (data/geocode_cache.json goog:: keys) where
                        it is distinct and on the site - 310, 350, 360 Riverside Crescent and Skyvue.
              interpolated  320, 330, 340 sit between 310 and 360 along the crescent in numeric order; Skyscape is the
                        sister plot east of Skyvue (parcels 6110884 / 6110888). Placed so the twin shows the right bulk in
                        roughly the right place; to be replaced the day parcel polygons arrive.
            Multi-tower projects (Skyscape 3 towers, Skyvue 3 towers) are spread 70 m apart around the project point.

Every feature carries parcel_key, project_number, dm_building_id and footprint_basis, so build_sobha_mask.py reaches it by
the exact parcel route and the twin audit can see it is a register placeholder, not a survey. Nothing existing in the tile
is touched; the previous file is kept as buildings.geojson.bak_prehartland2 and the placeholders are also written on their
own to data/ce/bukadra/hartland2_placeholders.geojson so they can be removed cleanly.

After this: python scripts/remass_districts.py bukadra (CityEngine, detached), python scripts/districts_geo.py --no-push,
python scripts/build_sobha_mask.py.
Usage: python scripts/mass_hartland2.py [--dry]
"""
import json, math, os, shutil, sys, datetime as dt

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = os.path.join(ROOT, "data", "graph", "najma.duckdb")
BOARD = os.path.join(ROOT, "data", "board")
CE_DIR = os.path.join(ROOT, "data", "ce", "bukadra")
GEOJSON = os.path.join(CE_DIR, "buildings.geojson")
PLACEHOLDERS = os.path.join(CE_DIR, "hartland2_placeholders.geojson")
GEOCODE = os.path.join(ROOT, "data", "geocode_cache.json")
SOBHA = 966
AREA = "Bukadra"
TOWER_MIN_FLOORS = 10
SPREAD_M = 70.0

# Google Places points the cache holds for the project name, checked to lie on the Hartland II site (east of the OSM tile).
GOOGLE_KEYS = {
    3067: "goog::310 Riverside Crescent, Sobha Hartland 2, Dubai, United Arab Emirates",
    3083: "goog::350 Riverside Crescent, Sobha Hartland 2, Dubai, United Arab Emirates",
    3079: "goog::Signature Waterfront Community, 360 Riverside Crescent, Dubai, United Arab Emirates",
    3435: "goog::Iconic Skyline Living, SkyVue Residences, Dubai, United Arab Emirates",
}
# (project_number, from, to, fraction): between two Google-placed projects along the crescent, in numeric order
INTERPOLATE = {3088: (3067, 3079, 0.25), 2788: (3067, 3079, 0.50), 3082: (3067, 3079, 0.75)}
# (project_number, anchor project, east metres, north metres): the sister plot beside an anchored one
OFFSET = {3160: (3435, 250.0, 0.0)}


def m_to_deg(lat):
    return 1.0 / (100800.0 * math.cos(math.radians(lat)) / math.cos(math.radians(25.17))), 1.0 / 111320.0


def square(lon, lat, side_m):
    dlon, dlat = m_to_deg(lat)
    hx, hy = side_m / 2.0 * dlon, side_m / 2.0 * dlat
    ring = [[lon - hx, lat - hy], [lon + hx, lat - hy], [lon + hx, lat + hy], [lon - hx, lat + hy], [lon - hx, lat - hy]]
    return {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in ring]]}


def towers_of(records, n_buildings):
    """The permitted towers among a parcel's DM rows. Permit revisions keep the floor count and shift the units by a
    handful (310 Riverside: 908 / 896 / 921 / 908 units, all 71-72 floors, one tower), so rows are grouped by floors
    (to within one), the 'Permit Delivered' row wins over 'New' revisions, podium rows under TOWER_MIN_FLOORS are left
    out, and the DLD register's building count caps how many groups are towers."""
    best = {}
    for r in records:
        fl = int(r.get("floors_above") or 0)
        if fl < TOWER_MIN_FLOORS:
            continue
        k = fl // 2
        rank = (r.get("status") == "Permit Delivered", int(r.get("building_id") or 0))
        if k not in best or rank > best[k][0]:
            best[k] = (rank, r)
    towers = [r for _, r in sorted(best.values(), key=lambda t: -int(t[1].get("floors_above") or 0))]
    return towers[:max(1, int(n_buildings or 1))]


def main():
    dry = "--dry" in sys.argv
    con = duckdb.connect(GRAPH, read_only=True)
    projects = {}
    for pn, name, status, units, pk, plot_sqm, nb in con.execute("""
        select p.project_number, any_value(t.project_name_en), any_value(p.project_status), any_value(p.no_of_units),
               cast(cast(l.parcel_id as bigint) as varchar), any_value(l.actual_area), any_value(p.no_of_buildings)
        from gov_dld__land_registry l join gov_dld__projects p using(project_id)
        left join (select project_number, any_value(project_name_en) project_name_en from gov_dld__transactions group by 1) t using(project_number)
        where p.developer_number = ? and l.area_name_en = ? and coalesce(p.no_of_buildings, 0) > 0
        group by 1, 5 order by 1""", [SOBHA, AREA]).fetchall():
        projects[int(pn)] = {"project_number": int(pn), "name": (name or "").strip(), "status": status, "units": units,
                             "parcel_key": pk, "plot_sqm": plot_sqm, "buildings": nb}
    dm = json.load(open(os.path.join(BOARD, "parcel_buildings_bukadra.json"), encoding="utf-8"))["parcels"]
    geo = json.load(open(GEOCODE, encoding="utf-8"))

    # positions
    pos = {}
    for pn, key in GOOGLE_KEYS.items():
        e = geo.get(key) or {}
        if e.get("lon") is not None:
            pos[pn] = (e["lon"], e["lat"], "google", key)
    for pn, (a, b, f) in INTERPOLATE.items():
        if a in pos and b in pos:
            pos[pn] = (pos[a][0] + (pos[b][0] - pos[a][0]) * f, pos[a][1] + (pos[b][1] - pos[a][1]) * f, "interpolated",
                       "%.0f%% of the way from %d to %d along Riverside Crescent" % (f * 100, a, b))
    for pn, (a, east, north) in OFFSET.items():
        if a in pos:
            dlon, dlat = m_to_deg(pos[a][1])
            pos[pn] = (pos[a][0] + east * dlon, pos[a][1] + north * dlat, "interpolated", "%.0f m east of %d (sister plot)" % (east, a))

    features, report = [], []
    for pn, p in sorted(projects.items()):
        if pn not in pos:
            report.append((pn, p["name"], "NO POSITION - skipped")); continue
        towers = towers_of(dm.get(p["parcel_key"]) or [], p["buildings"])
        if not towers:
            report.append((pn, p["name"], "no DM tower record on parcel %s - skipped" % p["parcel_key"])); continue
        lon0, lat0, src, basis = pos[pn]
        dlon, dlat = m_to_deg(lat0)
        n = len(towers)
        status = "construction" if p["status"] == "ACTIVE" else "pipeline"
        for k, t in enumerate(towers):
            fl = int(t["floors_above"]); h = float(t.get("height_m") or fl * 3.2 + 3)
            plate = float(t.get("area_sqm") or 0) / fl if t.get("area_sqm") else max(600.0, (p["plot_sqm"] or 3000) * 0.3)
            side = math.sqrt(plate)
            # spread a multi-tower project along an east-west line through the project point
            lon = lon0 + (k - (n - 1) / 2.0) * SPREAD_M * dlon; lat = lat0
            name = p["name"] + ("" if n == 1 else " - tower %d" % (k + 1))
            features.append({"type": "Feature", "geometry": square(lon, lat, side), "properties": {
                "status": status, "bHeight": round(h, 1), "name": name, "levels": str(fl),
                "height_source": "dm_register", "height_basis": "DM building %s: %d permitted floors, %.1f m" % (t["building_id"], fl, h),
                "footprint_basis": "square of the permitted plate (%.0f m2 total / %d floors = %.0f m2)" % (float(t.get("area_sqm") or 0), fl, plate),
                "position_source": src, "position_basis": basis, "register_placeholder": True,
                "parcel_key": p["parcel_key"], "project_number": pn, "dm_building_id": t["building_id"], "dm_units": t.get("units"),
                "developer": "sobha"}})
            report.append((pn, name, "%d fl, %.0f m, plate %.0f m2, %s @ %.5f,%.5f (%s)" % (fl, h, plate, status, lon, lat, src)))

    print("Hartland II placeholders: %d towers for %d projects" % (len(features), len({f['properties']['project_number'] for f in features})))
    for r in report:
        print("  %5d %-34s %s" % (r[0], r[1][:34], r[2]))
    if dry:
        return
    fc = json.load(open(GEOJSON, encoding="utf-8"))
    before = len(fc["features"])
    # idempotent: drop any placeholder from an earlier run before appending this one
    fc["features"] = [f for f in fc["features"] if not (f.get("properties") or {}).get("register_placeholder")]
    dropped = before - len(fc["features"])
    bak = GEOJSON + ".bak_prehartland2"
    if not os.path.exists(bak):
        shutil.copyfile(GEOJSON, bak)
    fc["features"].extend(features)
    with open(GEOJSON, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    with open(PLACEHOLDERS, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "generated": dt.datetime.now().isoformat(timespec="seconds"),
                   "note": __doc__.split("\n\n")[1], "features": features}, f, ensure_ascii=False, indent=1)
    print("-> %s: %d features (%d kept, %d earlier placeholders replaced, %d added); placeholders at %s" % (
        GEOJSON, len(fc["features"]), before - dropped, dropped, len(features), PLACEHOLDERS))


if __name__ == "__main__":
    main()
