"""buildings.geojson -> buildings.shp, so a district onboarded with reexport_footprints.py --bbox can go into CityEngine.

ce_batch.py imports data/ce/<slug>/buildings.shp. ce_export.py writes one as part of its own Overpass run, but a district
started from a bounding box (Bu Kadra and Liwan 1, 21 Sep 2026 - the two places where geometry was the blocker) only has the
geojson. This writes the shapefile from it, with the same columns the massing rules read.

  python scripts/ce_shapefile.py bukadra liwan1
"""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CE = os.path.join(ROOT, "data", "ce")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run(slug):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj):
        print("%s: no buildings.geojson" % slug)
        return False
    import geopandas as gpd
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    gdf["bHeight"] = gdf["bHeight"].astype(float)
    # a shapefile field name is ten characters; the rules read status, bHeight, name and levels, so keep those exactly
    keep = [c for c in ("status", "bHeight", "name", "levels", "geometry") if c in gdf.columns]
    gdf = gdf[keep]
    out = os.path.join(CE, slug, "buildings.shp")
    gdf.to_file(out)
    print("  %-12s %5d footprints -> %s" % (slug, len(gdf), os.path.relpath(out, ROOT)))
    return True


def main():
    for s in (sys.argv[1:] or ["bukadra"]):
        run(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
