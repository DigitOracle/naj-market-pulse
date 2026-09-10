"""ue_context_layer.py -- ground context for the Unreal property clips.

Turns what we already hold for a district into flat, triangulated ground layers in Unreal centimetres so the clip stops being
boxes on a satellite photograph: roads (asphalt) + pavements from data/ce/<slug>/streets.geojson (OSM widths the CityEngine
network already uses), and parks / grass / gardens / pitches / water / sand / parking / construction from
data/ce/<slug>/landuse_osm.json (Overpass, `out geom`). Layers are unioned per class and stacked by a small z offset so the
draw order is deterministic (water below grass below pavement below asphalt).

Output: data/ce/<slug>/context_ue.json  {"layers": [{"name","z_cm","rgb","roughness","specular","verts":[x,y,z,...],"tris":[...]}]}
Usage:  python scripts/ue_context_layer.py sobhaheartland
"""
import json, os, sys, time
import numpy as np
import mapbox_earcut as earcut
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, MultiPolygon, shape
from shapely.ops import unary_union

SLUG = sys.argv[1] if len(sys.argv) > 1 else "sobhaheartland"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); CE = os.path.join(ROOT, "data", "ce", SLUG)
geo = json.load(open(os.path.join(ROOT, "data", "ce", "_datasmith", f"{SLUG}_georef.json"))); OFF = geo["offset_ce_xyz"]
tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
t0 = time.time()


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def to_ue(e, n):                       # UTM metres -> Unreal cm (X = CE x = E + off0, Y = CE z = -N + off2)
    return ((e + OFF[0]) * 100.0, (-n + OFF[2]) * 100.0)


def ll_ring(coords):
    return [tr.transform(x, y) for x, y in coords]


# ---------------------------------------------------------------- streets
streets = json.load(open(os.path.join(CE, "streets.geojson"), encoding="utf-8"))["features"]
asphalt, walk = [], []
for f in streets:
    p = f["properties"]; g = f["geometry"]
    if g["type"] != "LineString": continue
    line = LineString(ll_ring(g["coordinates"]))
    w = float(p.get("sw") or 7.0); swl = float(p.get("swl") or 0); swr = float(p.get("swr") or 0)
    net = p.get("net") or ""; hw = p.get("hw") or ""
    if not swl and not swr and net != "freeway" and hw not in ("motorway", "motorway_link", "trunk", "trunk_link"): swl = swr = 2.0
    asphalt.append(line.buffer(w / 2.0, cap_style=2, join_style=2))
    if swl or swr: walk.append(line.buffer(w / 2.0 + max(swl, swr), cap_style=2, join_style=2))
A = unary_union(asphalt); W = unary_union(walk).difference(A) if walk else None
log(f"streets {len(streets)} -> asphalt {A.area/1e4:.1f} ha, pavement {(W.area/1e4 if W else 0):.1f} ha")

# ---------------------------------------------------------------- landuse (Overpass out geom)
lu = json.load(open(os.path.join(CE, "landuse_osm.json"), encoding="utf-8"))["elements"]
CLASS = {  # osm tag -> layer
    "natural=water": "water", "water=*": "water", "natural=wetland": "wetland", "leisure=swimming_pool": "pool",
    "landuse=grass": "grass", "leisure=garden": "grass", "leisure=park": "grass", "landuse=recreation_ground": "grass", "landuse=village_green": "grass",
    "leisure=pitch": "pitch", "leisure=golf_course": "grass", "leisure=playground": "grass", "landuse=forest": "grass", "natural=wood": "grass", "natural=scrub": "scrub",
    "natural=sand": "sand", "natural=beach": "sand", "landuse=construction": "construction", "landuse=brownfield": "construction",
    "amenity=parking": "parking", "highway=pedestrian": "pavement", "highway=footway": "pavement", "highway=service": "asphalt2",
}
def layer_of(tags):
    for k in ("natural", "water", "leisure", "landuse", "amenity", "highway"):
        if k in tags:
            key = f"{k}={tags[k]}"
            if key in CLASS: return CLASS[key]
            if k == "water": return "water"
    return None
def polys_from(el):
    if el["type"] == "way" and "geometry" in el:
        pts = [(g["lon"], g["lat"]) for g in el["geometry"]]
        if len(pts) >= 4 and pts[0] == pts[-1]: return [Polygon(ll_ring(pts))]
        return []
    if el["type"] == "relation":
        outers, inners = [], []
        for m in el.get("members", []):
            if m.get("type") != "way" or "geometry" not in m: continue
            pts = [(g["lon"], g["lat"]) for g in m["geometry"]]
            if len(pts) < 4 or pts[0] != pts[-1]: continue     # unclosed member rings are skipped (good enough for ground colour)
            (outers if m.get("role") != "inner" else inners).append(Polygon(ll_ring(pts)))
        if not outers: return []
        u = unary_union(outers)
        if inners: u = u.difference(unary_union(inners))
        return [u]
    return []
buckets = {}
for el in lu:
    lay = layer_of(el.get("tags", {}))
    if not lay: continue
    for pg in polys_from(el):
        if pg.is_valid and pg.area > 4: buckets.setdefault(lay, []).append(pg)
layers = {k: unary_union(v) for k, v in buckets.items()}
for k, v in layers.items(): log(f"landuse {k}: {v.area/1e4:.1f} ha")

# ---------------------------------------------------------------- stacking + triangulation
# z order (cm above the imagery plane at -5): lower layers first
ORDER = [("water", 1.0, (0.02, 0.07, 0.09), 0.03, 1.0), ("wetland", 1.5, (0.20, 0.24, 0.16), 0.9, 0.3), ("sand", 2.0, (0.70, 0.62, 0.46), 0.95, 0.2),
         ("construction", 2.0, (0.60, 0.54, 0.44), 0.95, 0.2), ("scrub", 2.5, (0.36, 0.38, 0.24), 0.9, 0.2), ("grass", 3.0, (0.17, 0.30, 0.10), 0.9, 0.2),
         ("pitch", 3.5, (0.14, 0.34, 0.12), 0.85, 0.2), ("parking", 4.0, (0.16, 0.16, 0.16), 0.85, 0.3), ("pavement", 5.0, (0.60, 0.58, 0.54), 0.95, 0.2),
         ("asphalt2", 6.0, (0.12, 0.12, 0.12), 0.88, 0.3), ("asphalt", 7.0, (0.085, 0.085, 0.09), 0.86, 0.35), ("pool", 8.0, (0.05, 0.35, 0.45), 0.02, 1.0)]
layers["asphalt"] = A
if W is not None: layers["pavement"] = unary_union([layers["pavement"], W]) if "pavement" in layers else W
out = []
def tri_polygon(pg, z):
    if pg.is_empty: return [], []
    rings = [list(pg.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in pg.interiors]
    pts = np.array([to_ue(x, y) for ring in rings for (x, y) in ring], dtype=np.float64)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(pts, ends)
    verts = []
    for x, y in pts: verts += [round(x, 1), round(y, 1), z]
    return verts, idx.tolist()
for name, z, rgb, rough, spec in ORDER:
    if name not in layers: continue
    g = layers[name]
    polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
    V, T = [], []
    for pg in polys:
        if pg.area < 2: continue
        pg = pg.simplify(0.15, preserve_topology=True)
        v, t = tri_polygon(pg, z)
        base = len(V) // 3; V += v; T += [i + base for i in t]
    out.append({"name": name, "z_cm": z, "rgb": rgb, "roughness": rough, "specular": spec, "verts": V, "tris": T})
    log(f"layer {name}: {len(polys)} polygons, {len(T)//3} triangles")
json.dump({"slug": SLUG, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "layers": out}, open(os.path.join(CE, "context_ue.json"), "w"))
log(f"wrote context_ue.json ({os.path.getsize(os.path.join(CE, 'context_ue.json'))//1024} KB) in {time.time()-t0:.1f}s")
