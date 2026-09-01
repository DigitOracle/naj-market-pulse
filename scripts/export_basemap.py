"""Export a lightweight vector basemap JSON from assets/dubai_basemap.gpkg for the
interactive /map page (canvas rendering in the Worker's client JS).
Output: public/mp_basemap.json — pushed to Worker KV by push_assets.py, served at /img/mp_basemap.
Coordinates are EPSG:4326 lon/lat rounded to 4 dp (~11 m) — display cartography only.
"""
import json, os
import geopandas as gpd
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
GPKG = os.path.join(HERE, "..", "assets", "dubai_basemap.gpkg")
OUT = os.path.join(HERE, "..", "public", "mp_basemap.json")

# Frame around the 27 curated communities, with margin
LON0, LAT0, LON1, LAT1 = 54.98, 24.83, 55.55, 25.36
CLIP = box(LON0, LAT0, LON1, LAT1)

MAJOR = {"motorway", "trunk"}
MID = {"primary"}
MIN_WATER_DEG2 = 1.5e-5  # drop ponds/fountains — coastline and creeks only


def lines_of(geom):
    """Yield coordinate lists for LineString/MultiLineString."""
    if geom.geom_type == "LineString":
        yield list(geom.coords)
    elif geom.geom_type == "MultiLineString":
        for g in geom.geoms:
            yield list(g.coords)


def rings_of(geom):
    """Yield exterior rings for Polygon/MultiPolygon (interiors dropped — cartography only)."""
    if geom.geom_type == "Polygon":
        yield list(geom.exterior.coords)
    elif geom.geom_type == "MultiPolygon":
        for g in geom.geoms:
            yield list(g.exterior.coords)


def rnd(coords):
    return [[round(x, 4), round(y, 4)] for x, y in coords]


def dedupe(coords):
    out = []
    for c in coords:
        if not out or c != out[-1]:
            out.append(c)
    return out


def main():
    water = gpd.read_file(GPKG, layer="water", bbox=(LON0, LAT0, LON1, LAT1))
    roads = gpd.read_file(GPKG, layer="roads", bbox=(LON0, LAT0, LON1, LAT1))

    water_polys = []
    wg = water.clip(CLIP)
    wg = wg[wg.geometry.area >= MIN_WATER_DEG2]
    wg["geometry"] = wg.geometry.simplify(0.0015, preserve_topology=True)
    for geom in wg.geometry:
        if geom is None or geom.is_empty:
            continue
        for ring in rings_of(geom):
            r = dedupe(rnd(ring))
            if len(r) >= 4:
                water_polys.append(r)

    def road_lines(classes, tol):
        sel = roads[roads["fclass"].isin(classes)].clip(CLIP)
        sel["geometry"] = sel.geometry.simplify(tol, preserve_topology=True)
        out = []
        for geom in sel.geometry:
            if geom is None or geom.is_empty:
                continue
            for line in lines_of(geom):
                l = dedupe(rnd(line))
                if len(l) >= 2:
                    out.append(l)
        return out

    doc = {
        "bounds": [LON0, LAT0, LON1, LAT1],
        "water": water_polys,
        "roadsMajor": road_lines(MAJOR, 0.0010),
        "roadsMid": road_lines(MID, 0.0018),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    kb = os.path.getsize(OUT) // 1024
    print(f"wrote {OUT}: {kb} KB — water {len(water_polys)} rings, "
          f"major {len(doc['roadsMajor'])}, mid {len(doc['roadsMid'])} lines")
    if kb > 400:
        print("WARNING: over 400 KB — raise simplify tolerances before shipping")


if __name__ == "__main__":
    main()
