"""Write a district tile's buildings.shp from its buildings.geojson, so CityEngine imports what the geojson holds.

ce_batch_v2.py masses from the SCENE (/najma/scenes/<slug>.cej), and the scene's shapes are whatever buildings.shp held
when ce_import_tile.py imported it. A footprint added to buildings.geojson afterwards (a register placeholder from
mass_hartland2.py, a tile built from a bbox export) has no shape in the scene and is silently never massed: the batch
matches scene shapes to features by centroid and a feature with no shape just falls through. So after the geojson changes
shape count: this, then ce_import_tile.py <slug>, then the re-mass.

Same field schema split_district.py writes (status, bHeight, name, levels), EPSG:4326, and nothing else - CityEngine reads
the object attributes by these names.

Usage: python scripts/tile_shp.py <slug> [<slug> ...]
"""
import json, os, sys

import geopandas as gpd
from shapely.geometry import shape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CE = os.path.join(ROOT, "data", "ce")


def write(slug):
    d = os.path.join(CE, slug)
    feats = json.load(open(os.path.join(d, "buildings.geojson"), encoding="utf-8"))["features"]
    gdf = gpd.GeoDataFrame([{"status": str(f["properties"].get("status") or "existing"),
                             "bHeight": float(f["properties"].get("bHeight") or 12.0),
                             "name": (str(f["properties"].get("name") or ""))[:80],
                             "levels": str(f["properties"].get("levels") or "")[:10]} for f in feats],
                           geometry=[shape(f["geometry"]) for f in feats], crs="EPSG:4326")
    gdf.to_file(os.path.join(d, "buildings.shp"))
    print("%s: buildings.shp written, %d shapes (from %d features)" % (slug, len(gdf), len(feats)))


if __name__ == "__main__":
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not slugs:
        sys.exit(__doc__)
    for s in slugs:
        write(s)
