"""A Ras Al Khor tile for the twin: OSM warehouses as they stand, plus Sobha One and The Element from the register.

Sobha One (3,057 units, the most-sold Sobha scheme on the DLD register) and The Element at Sobha One sit in Ras Al Khor
Industrial First, which the twin had never massed: no district slug, no tile, no boundary polygon in public/mp_areas.json
(the community-polygon set covers 39 areas and this is not one). So the twin's Sobha view had a hole where Sobha's biggest
scheme is. This builds the tile the way the others were, minus the boundary clip:

  footprints  OpenStreetMap ways and relations tagged building inside a fixed box around the site
              (25.174-25.196 N, 55.328-55.356 E; data/names/osm_footprints_raw/rasalkhor_geom.json, Overpass `out geom`,
              23 Sep 2026). What OSM holds there is the industrial estate - warehouses, showrooms - which is the truth of the
              ground today and the right backdrop. Heights from OSM height= / building:levels where stated, else the 12 m
              placeholder every tile starts with.
  Sobha One / The Element  register placeholders exactly as mass_hartland2.py makes them: one mass per permitted tower from
              the Dubai Municipality building record on the project's DLD parcel (floors, height, plate), status from the DLD
              project register, position from the cached Google Places point that lies on the site ("Golf Ridges, Sobha One"
              for Sobha One - the plain "Sobha One" query returns the Hartland centroid; "The Element at Sobha One" for the
              Element), towers spread 70 m apart. Weakest link is position and every feature says so.

Writes data/ce/rasalkhor/buildings.geojson (+ buildings.shp via tile_shp.py, + rasalkhor_placeholders.geojson). Then:
python scripts/ce_import_tile.py rasalkhor, python scripts/remass_districts.py rasalkhor, districts_geo, the Sobha mask.
Usage: python scripts/make_rasalkhor_tile.py [--dry]
"""
import json, math, os, re, sys, datetime as dt

import duckdb
from shapely.geometry import Polygon, mapping

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mass_hartland2 import m_to_deg, square, towers_of  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = os.path.join(ROOT, "data", "graph", "najma.duckdb")
RAW = os.path.join(ROOT, "data", "names", "osm_footprints_raw", "rasalkhor_geom.json")
OUT_DIR = os.path.join(ROOT, "data", "ce", "rasalkhor")
GEOCODE = os.path.join(ROOT, "data", "geocode_cache.json")
SLUG = "rasalkhor"
SPREAD_M = 70.0
STOREY_M, GROUND_M = 3.2, 3.0
NOT_BUILDINGS = {"roof", "shelter", "wall", "fence", "carport", "canopy", "no", "construction_site", "ruins", "tent"}
# project_number -> (google cache key that lies on the site, DLD parcel_id)
SITES = {
    2948: ("goog::Golf Ridges, Sobha One, Dubai, United Arab Emirates", 6120442),
    3540: ("goog::The Element at Sobha One, Ras Al Khor Industrial First, Dubai, United Arab Emirates", 6120119),
}


def num(v):
    m = re.match(r"^\s*(-?[\d.]+)", str(v or "").replace(",", ""))
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def osm_height(tags):
    lv = num(tags.get("building:levels")); h = num(tags.get("height"))
    if h is not None and h > 0:
        return round(h, 1), "osm height", lv
    if lv and lv >= 1:
        return round(lv * STOREY_M + GROUND_M, 1), "osm levels", lv
    return 12.0, None, lv


def osm_footprints():
    d = json.load(open(RAW, encoding="utf-8"))
    in_relation = set()
    for e in d["elements"]:
        if e["type"] == "relation":
            for m in e.get("members") or []:
                if m.get("type") == "way":
                    in_relation.add(m.get("ref"))
    feats = []
    for e in d["elements"]:
        tags = e.get("tags") or {}
        if (tags.get("building") or "yes") in NOT_BUILDINGS:
            continue
        rings = []
        if e["type"] == "way" and e.get("geometry") and e["id"] not in in_relation:
            rings = [[(p["lon"], p["lat"]) for p in e["geometry"]]]
        elif e["type"] == "relation":
            rings = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in (e.get("members") or [])
                     if m.get("role") == "outer" and m.get("geometry")]
        for ring in rings:
            if len(ring) < 4:
                continue
            poly = Polygon(ring)
            if not poly.is_valid or poly.area * 111320 * 100800 < 15:
                continue
            h, src, lv = osm_height(tags)
            props = {"status": "existing", "bHeight": h, "name": (tags.get("name") or "").strip() or None,
                     "levels": str(int(lv)) if lv else None, "osm": "%s/%s" % (e["type"], e["id"])}
            if src:
                props["height_source"] = "osm_export"; props["height_basis"] = src
            feats.append({"type": "Feature", "geometry": mapping(poly), "properties": props})
    return feats


def placeholders(con, geo):
    out, report = [], []
    for pn, (key, parcel) in SITES.items():
        name, status, nb = con.execute(
            "select coalesce((select any_value(project_name_en) from gov_dld__transactions where project_number = p.project_number), p.project_name), "
            "p.project_status, p.no_of_buildings from gov_dld__projects p where p.project_number = ?", [pn]).fetchone()
        name = (name or "").strip()
        rows = [dict(zip(("building_id", "floors_above", "height_m", "area_sqm", "units", "status"), r)) for r in con.execute(
            "select building_id, typical_floors_count, building_height, building_total_area, null, building_status_english "
            "from gov_dm__building_summary_information where cast(parcel_id as bigint) = ? and building_status_english <> 'Expired'", [parcel]).fetchall()]
        towers = towers_of(rows, nb)
        e = geo.get(key) or {}
        if not towers or e.get("lon") is None:
            report.append((pn, name, "skipped: %d DM towers, google point %s" % (len(towers), "yes" if e.get("lon") is not None else "none"))); continue
        lon0, lat0 = e["lon"], e["lat"]; dlon, _ = m_to_deg(lat0); n = len(towers)
        st = "construction" if status == "ACTIVE" else "pipeline"
        for k, t in enumerate(towers):
            fl = int(t["floors_above"]); h = float(t.get("height_m") or fl * STOREY_M + GROUND_M)
            plate = float(t.get("area_sqm") or 0) / fl if t.get("area_sqm") else 1200.0
            lon = lon0 + (k - (n - 1) / 2.0) * SPREAD_M * dlon
            nm = name + ("" if n == 1 else " - tower %d" % (k + 1))
            out.append({"type": "Feature", "geometry": square(lon, lat0, math.sqrt(plate)), "properties": {
                "status": st, "bHeight": round(h, 1), "name": nm, "levels": str(fl),
                "height_source": "dm_register", "height_basis": "DM building %s: %d permitted floors, %.1f m" % (t["building_id"], fl, h),
                "footprint_basis": "square of the permitted plate (%.0f m2 total / %d floors = %.0f m2)" % (float(t.get("area_sqm") or 0), fl, plate),
                "position_source": "google", "position_basis": key, "register_placeholder": True,
                "parcel_key": str(parcel), "project_number": pn, "dm_building_id": t["building_id"], "developer": "sobha"}})
            report.append((pn, nm, "%d fl, %.0f m, plate %.0f m2, %s @ %.5f,%.5f" % (fl, h, plate, st, lon, lat0)))
    return out, report


def main():
    dry = "--dry" in sys.argv
    base = osm_footprints()
    con = duckdb.connect(GRAPH, read_only=True)
    geo = json.load(open(GEOCODE, encoding="utf-8"))
    ph, report = placeholders(con, geo)
    print("rasalkhor tile: %d OSM footprints + %d register placeholders" % (len(base), len(ph)))
    for r in report:
        print("  %5d %-34s %s" % (r[0], r[1][:34], r[2]))
    if dry:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": base + ph}
    with open(os.path.join(OUT_DIR, "buildings.geojson"), "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "rasalkhor_placeholders.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "generated": dt.datetime.now().isoformat(timespec="seconds"), "features": ph}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "tile.json"), "w", encoding="utf-8") as f:
        json.dump({"slug": SLUG, "made": dt.datetime.now().isoformat(timespec="seconds"), "source": "OSM bbox export + DLD/DM register placeholders",
                   "bbox": [55.328, 25.174, 55.356, 25.196], "osm_footprints": len(base), "placeholders": len(ph),
                   "note": "no community boundary polygon for Ras Al Khor Industrial First in public/mp_areas.json; box is the Sobha One site and its industrial surroundings"}, f, indent=1)
    import tile_shp
    tile_shp.write(SLUG)
    print("-> %s" % OUT_DIR)


if __name__ == "__main__":
    main()
