"""Golden Building footprint: Imtiaz Symphony Tower, Meydan Horizon / Bukadra.

No OSM footprint exists (construction started Nov 2025), so the massing anchor
is authored: a rounded-corner plate sized from the sheet's floor areas
(~1,100 m2 plate inside the 4,234 m2 plot), rotated to face the Ras Al Khor
lagoon, at the site-level coordinate. Replace with the surveyed footprint the
day Dubai Pulse / Makani yields it — everything downstream re-generates.

Output: data/ce/goldensymphony/buildings.shp + .geojson
"""
import json, math, os

import geopandas as gpd
import pyproj
from shapely.affinity import rotate
from shapely.geometry import box
from shapely.ops import transform

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "ce", "goldensymphony")
os.makedirs(OUT, exist_ok=True)

LON, LAT = 55.308, 25.168          # site-level anchor (Meydan Horizon)
W, D, R = 40.0, 40.0, 3.0          # plate 40x40 m per the developer floor-plan deck (square plate, central core)
BEARING = 40.0                     # long axis swung toward the lagoon (NE)

to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
to_wgs = pyproj.Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)
cx, cy = to_utm.transform(LON, LAT)

plate = box(cx - (W - 2 * R) / 2, cy - (D - 2 * R) / 2,
            cx + (W - 2 * R) / 2, cy + (D - 2 * R) / 2).buffer(R, quad_segs=8)
plate = rotate(plate, -BEARING, origin=(cx, cy))
plate_wgs = transform(lambda x, y: to_wgs.transform(x, y), plate)

feat = {"type": "Feature",
        "properties": {"status": "construction", "bHeight": 130.0,
                       "name": "Imtiaz Symphony Tower", "levels": "34"},
        "geometry": plate_wgs.__geo_interface__}
json.dump({"type": "FeatureCollection", "features": [feat]},
          open(os.path.join(OUT, "buildings.geojson"), "w"), separators=(",", ":"))
gdf = gpd.GeoDataFrame.from_features([feat], crs="EPSG:4326")
gdf["bHeight"] = gdf["bHeight"].astype(float)
gdf.to_file(os.path.join(OUT, "buildings.shp"))
print(f"footprint written: {plate.area:.0f} m2 plate @ {LAT},{LON} bearing {BEARING}")
