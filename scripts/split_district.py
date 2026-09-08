"""Split one district into two model tiles, from a BUILDING-level OpenStreetMap export.

Why. JLT re-exported at building level (ways + relations) is 7,153 footprints - the towers the old plot-fragment export
missed are all there (111 over 60 m, was 84), but one tile that size cannot ship under the 5 MB model cap. Two tiles can.
The cut is a straight east-west line at the median latitude of the building centroids, so the halves are balanced by count;
a building is never split - it goes with its centroid.

For each tile this writes what the CityEngine lane expects of a district folder:
    data/ce/<tile>/buildings.geojson      same schema as every district (status, bHeight, name, levels) + osm id, height_source
    data/ce/<tile>/buildings.shp (+dbf/shx/prj/cpg)  the file ce_import_tile.py hands to CityEngine
    data/ce/<tile>/najma.cga, README_CE.md, pipeline.csv   copied from the parent
    data/ce/<tile>/bindings.json          empty - the tile inherits developer bindings through build_anchors / bind_registers
    data/ce/<tile>/tile.json              parent, cut latitude, which half, counts - so the split is auditable and repeatable

The parent district is left exactly as it is. Nothing is pushed.

Usage: python scripts/split_district.py althanyahfifth jltnorth jltsouth [--dry]
"""
import json, os, shutil, sys
import geopandas as gpd
from shapely.geometry import shape, mapping

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import reexport_footprints as RX  # noqa: E402
CE = os.path.join(ROOT, "data", "ce")


def building_level(parent):
    """The building-level feature list for the parent, built exactly as reexport_footprints.py builds it (cached raw)."""
    gj = os.path.join(CE, parent, "buildings.geojson")
    old = json.load(open(gj, encoding="utf-8"))
    xs = [p[0] for f in old["features"] for p in shape(f["geometry"]).exterior.coords]
    ys = [p[1] for f in old["features"] for p in shape(f["geometry"]).exterior.coords]
    J = RX.fetch(parent, (min(xs), min(ys), max(xs), max(ys)))
    els = J.get("elements", [])
    member = {m.get("ref") for e in els if e.get("type") == "relation" for m in e.get("members", []) if m.get("type") == "way"}
    feats = []
    for e in els:
        tags = e.get("tags") or {}
        if tags.get("building") in RX.NOT_BUILDINGS: continue
        if e.get("type") == "way":
            if e.get("id") in member: continue
            pg = RX.poly_from_way(e.get("geometry") or [])
        else:
            pg = RX.poly_from_relation(e)
        if pg is None or pg.is_empty: continue
        a = RX.area_m2(pg)
        if a < 15: continue
        h, basis, lv = RX.height_of(tags)
        props = {"status": "existing", "bHeight": h if h else 12.0, "name": (tags.get("name:en") or tags.get("name") or "").strip(),
                 "levels": str(int(lv)) if lv else "", "osm": f"{e.get('type')}/{e.get('id')}", "footprint_m2": round(a)}
        if h: props["height_source"] = "osm_export"; props["height_basis"] = basis
        feats.append({"type": "Feature", "properties": props, "geometry": mapping(pg)})
    return feats


def write_tile(tile, feats, parent, meta, dry):
    d = os.path.join(CE, tile)
    if dry:
        print(f"  {tile:<10} {len(feats):>5} footprints | named {sum(1 for f in feats if f['properties']['name']):>4} | "
              f"real height {sum(1 for f in feats if f['properties']['bHeight'] > 12.01):>4} | towers>60 {sum(1 for f in feats if f['properties']['bHeight'] > 60):>3}")
        return
    os.makedirs(d, exist_ok=True)
    json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(d, "buildings.geojson"), "w", encoding="utf-8"), ensure_ascii=False)
    gdf = gpd.GeoDataFrame([{"status": f["properties"]["status"], "bHeight": float(f["properties"]["bHeight"]),
                             "name": f["properties"]["name"][:80], "levels": f["properties"]["levels"][:10]} for f in feats],
                           geometry=[shape(f["geometry"]) for f in feats], crs="EPSG:4326")
    gdf.to_file(os.path.join(d, "buildings.shp"))
    for fn in ("najma.cga", "README_CE.md", "pipeline.csv"):
        src = os.path.join(CE, parent, fn)
        if os.path.exists(src): shutil.copy2(src, os.path.join(d, fn))
    json.dump({"bindings": {}}, open(os.path.join(d, "bindings.json"), "w"))
    json.dump(meta, open(os.path.join(d, "tile.json"), "w"), indent=1)
    print(f"  {tile:<10} {len(feats):>5} footprints written -> {d}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; dry = "--dry" in sys.argv
    if len(args) != 3: sys.exit("usage: split_district.py <parent> <north-tile> <south-tile> [--dry]")
    parent, north, south = args
    feats = building_level(parent)
    lats = sorted(shape(f["geometry"]).centroid.y for f in feats)
    cut = lats[len(lats) // 2]
    N = [f for f in feats if shape(f["geometry"]).centroid.y >= cut]; S = [f for f in feats if shape(f["geometry"]).centroid.y < cut]
    print(f"{parent}: {len(feats)} building-level footprints, cut at lat {cut:.5f}" + ("  (DRY RUN)" if dry else ""))
    base = {"parent": parent, "cut_lat": round(cut, 6), "source": "OpenStreetMap ways + relations (reexport_footprints.py)", "total": len(feats)}
    write_tile(north, N, parent, dict(base, half="north", count=len(N)), dry)
    write_tile(south, S, parent, dict(base, half="south", count=len(S)), dry)
    if not dry:
        print("\nnext: python scripts/ce_import_tile.py", north, south, "  ->  python scripts/ce_batch_v2.py --v3", north, south)
