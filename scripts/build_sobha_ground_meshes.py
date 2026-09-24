"""Water meshes for the Sobha tour's Unreal-native ground: the Gulf, the Creek, the canal, the lakes - from OpenStreetMap.

Kendall, 24 Sep 2026: "we really need to do something about the ground ... replace [the ArcGIS imagery] with
something nice from Unreal." So the ground becomes materials and meshes in the engine, not a satellite photo: a sand
plane with a procedural material, and water where water is. This script makes the water as OBJ meshes in Unreal's
world frame (X = easting - 328289 m, Y = 2784598 - northing m, in centimetres - the districts' shared offset), and
ue_sobha_ground.py imports them.

Source: data/ce/_datasmith/sobha_context_osm_water.json (Overpass, 24 Sep 2026: natural=water ways and relations,
natural=coastline ways, waterway=canal, in the Sobha box 55.07-55.38 E, 24.81-25.22 N).
  sea      the box split by the merged coastline; a piece is sea when it lies to the RIGHT of the nearest coastline
           segment (OSM draws coastlines with land on the left, water on the right)
  inland   natural=water polygons (ways closed, relations' outer rings) - Dubai Creek, the Water Canal, Hartland's
           lagoon, the Marina, lakes; waterway=canal lines buffered 25 m
Writes data/ce/_datasmith/ground/sea.obj, inland_water.obj and ground_meshes.json (counts, areas, bounds).
Usage: python scripts/build_sobha_ground_meshes.py
"""
import json, math, os

import pyproj
from shapely.geometry import LineString, Polygon, MultiPolygon, box, Point
from shapely.ops import linemerge, unary_union, split, triangulate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "ce", "_datasmith", "sobha_context_osm_water.json")
BBOX_P = os.path.join(ROOT, "data", "ce", "_datasmith", "sobha_context_bbox.json")
OUT = os.path.join(ROOT, "data", "ce", "_datasmith", "ground")
OFF_E, OFF_N = 328289.0, 2784598.0
T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)


def utm(coords):
    return [T.transform(c["lon"], c["lat"]) for c in coords]


def ue_xy(x, y):
    return (x - OFF_E) * 100.0, (OFF_N - y) * 100.0


def polygons_of(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def tri_polygon(poly):
    """Constrained-ish triangulation: Delaunay of the polygon's vertices, keep triangles whose centroid is inside."""
    tris = []
    for t in triangulate(poly):
        if poly.contains(t.representative_point()) and poly.buffer(0.5).contains(t):
            tris.append(t)
    return tris


def write_obj(path, polys, z_cm, name):
    verts, faces = [], []
    for poly in polys:
        for t in tri_polygon(poly):
            base = len(verts)
            ring = list(t.exterior.coords)[:3]
            for x, y in ring:
                ux, uy = ue_xy(x, y); verts.append((ux, uy, z_cm))
            faces.append((base + 1, base + 3, base + 2))    # wound so the normal faces +Z in Unreal's left-handed frame
    with open(path, "w", encoding="utf-8") as f:
        f.write("o %s\n" % name)
        for v in verts:
            f.write("v %.1f %.1f %.1f\n" % v)
        f.write("vn 0 0 1\n")
        for a, b, c in faces:
            f.write("f %d//1 %d//1 %d//1\n" % (a, b, c))
    return len(verts), len(faces)


def main():
    os.makedirs(OUT, exist_ok=True)
    els = json.load(open(SRC, encoding="utf-8"))["elements"]
    bb = json.load(open(BBOX_P, encoding="utf-8"))["utm"]
    B = box(bb[0], bb[1], bb[2], bb[3])
    # --- sea from the coastline
    coast = [LineString(utm(e["geometry"])) for e in els if e.get("tags", {}).get("natural") == "coastline" and len(e.get("geometry") or []) > 1]
    merged = linemerge(unary_union(coast))
    lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    pieces = polygons_of(split(B, unary_union(lines)))
    sea = []
    for p in pieces:
        pt = p.representative_point()
        best, bd = None, 1e18
        for ln in lines:
            d = ln.distance(pt)
            if d < bd:
                bd, best = d, ln
        if best is None:
            continue
        # side test against the nearest segment of the nearest coastline: right of travel = water
        cs = list(best.coords); proj = best.project(pt)
        acc, seg = 0.0, None
        for a, b in zip(cs[:-1], cs[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if acc + L >= proj:
                seg = (a, b); break
            acc += L
        if seg is None:
            seg = (cs[-2], cs[-1])
        (ax, ay), (bx, by) = seg
        cross = (bx - ax) * (pt.y - ay) - (by - ay) * (pt.x - ax)
        if cross < 0:
            sea.append(p)
    # --- inland water
    inland = []
    for e in els:
        tags = e.get("tags", {})
        if tags.get("natural") == "water":
            if e["type"] == "way" and e.get("geometry") and len(e["geometry"]) > 3:
                pts = utm(e["geometry"])
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                poly = Polygon(pts).buffer(0)
                inland.extend(polygons_of(poly))
            elif e["type"] == "relation":
                outers = [utm(m["geometry"]) for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
                rings = []
                for o in outers:
                    if len(o) > 3:
                        if o[0] != o[-1]: o.append(o[0])
                        rings.append(Polygon(o).buffer(0))
                if rings:
                    inland.extend(polygons_of(unary_union(rings)))
        elif tags.get("waterway") == "canal" and e.get("geometry") and len(e["geometry"]) > 1:
            inland.extend(polygons_of(LineString(utm(e["geometry"])).buffer(25.0)))
    inland = polygons_of(unary_union([p for p in inland if p.is_valid and p.area > 200]).intersection(B))
    # the sea pieces already cover any inland polygon inside them
    sea_u = unary_union(sea) if sea else None
    if sea_u is not None:
        inland = [p for p in inland if not sea_u.contains(p.representative_point())]
    v1, f1 = write_obj(os.path.join(OUT, "sea.obj"), sea, 10.0, "sea")
    v2, f2 = write_obj(os.path.join(OUT, "inland_water.obj"), inland, 10.0, "inland_water")
    meta = {"source": "OpenStreetMap via Overpass, 24 Sep 2026", "frame": "UE cm: X = easting - 328289 m, Y = 2784598 - northing m",
            "sea": {"pieces": len(sea), "area_km2": round(sum(p.area for p in sea) / 1e6, 1), "verts": v1, "faces": f1},
            "inland": {"polygons": len(inland), "area_km2": round(sum(p.area for p in inland) / 1e6, 2), "verts": v2, "faces": f2},
            "bbox_utm": bb}
    json.dump(meta, open(os.path.join(OUT, "ground_meshes.json"), "w"), indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
