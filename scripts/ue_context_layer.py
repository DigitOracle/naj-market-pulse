"""ue_context_layer.py -- ground context for the Unreal city: flat, triangulated layers per district in Unreal cm.

Roads + pavements: data/ce/<slug>/streets.geojson when CityEngine built one (OSM widths), otherwise OpenStreetMap highways pulled
here through Overpass with widths by class. Parks / grass / gardens / pitches / water / sand / parking / construction / pools:
OpenStreetMap polygons through Overpass, cached as data/ce/<slug>/landuse_osm.json (and highways_osm.json). Layers are unioned per
class and stacked by a small z offset so draw order is deterministic (water below grass below pavement below asphalt).
One shared Unreal origin for the whole city (the Hartland Datasmith offset), same as scripts/ue_city_build.py.

Output: data/ce/<slug>/context_ue.json  {"layers": [{"name","z_cm","rgb","roughness","specular","verts":[x,y,z,...],"tris":[...]}]}
Usage:  python scripts/ue_context_layer.py <slug> [<slug> ...] | all      (existing context_ue.json is rebuilt; Overpass is cached)
"""
import json, os, sys, time, urllib.parse, urllib.request
import numpy as np
import mapbox_earcut as earcut
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, MultiPolygon, shape
from shapely.ops import unary_union

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); CEROOT = os.path.join(ROOT, "data", "ce")
OFF = json.load(open(os.path.join(CEROOT, "_datasmith", "sobhaheartland_georef.json")))["offset_ce_xyz"]
tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True); tr_inv = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)
MIRRORS = ["https://overpass.kumi.systems/api/interpreter", "https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
# OSM highway class -> (carriageway width m, pavement each side m); 0 pavement on fast roads
HW = {"motorway": (14.0, 0.0), "motorway_link": (7.0, 0.0), "trunk": (12.0, 0.0), "trunk_link": (7.0, 0.0), "primary": (11.0, 2.5), "primary_link": (6.0, 2.0),
      "secondary": (9.0, 2.5), "secondary_link": (6.0, 2.0), "tertiary": (7.5, 2.0), "tertiary_link": (5.5, 2.0), "residential": (6.0, 2.0), "unclassified": (6.0, 1.5),
      "living_street": (5.0, 1.5), "service": (4.5, 0.0), "pedestrian": (5.0, 0.0), "footway": (2.0, 0.0), "cycleway": (2.5, 0.0), "track": (3.0, 0.0)}


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def to_ue(e, n): return ((e + OFF[0]) * 100.0, (-n + OFF[2]) * 100.0)


def ll_ring(coords): return [tr.transform(x, y) for x, y in coords]


def overpass(query, cache_path):
    if os.path.exists(cache_path):
        return json.load(open(cache_path, encoding="utf-8"))["elements"]
    data = urllib.parse.urlencode({"data": query}).encode(); els = None
    for m in MIRRORS:
        try:
            r = urllib.request.urlopen(urllib.request.Request(m, data=data, headers={"User-Agent": "najma-context/1.0"}), timeout=180); els = json.loads(r.read())["elements"]; break
        except Exception as ex:
            log(f"  overpass {m.split('/')[2]}: {str(ex)[:60]}")
    if els is None: raise RuntimeError("all Overpass mirrors failed")
    json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "elements": els}, open(cache_path, "w", encoding="utf-8"))
    time.sleep(2)
    return els


def bbox_of(slug):
    feats = json.load(open(os.path.join(CEROOT, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    xs, ys = [], []
    for f in feats:
        b = shape(f["geometry"]).bounds; xs += [b[0], b[2]]; ys += [b[1], b[3]]
    e0, n0 = tr.transform(min(xs), min(ys)); e1, n1 = tr.transform(max(xs), max(ys))
    w, s = tr_inv.transform(e0 - 150, n0 - 150); e, n = tr_inv.transform(e1 + 150, n1 + 150)
    return f"{s:.5f},{w:.5f},{n:.5f},{e:.5f}"


def streets_from_ce(path):
    asphalt, walk = [], []
    for f in json.load(open(path, encoding="utf-8"))["features"]:
        p = f["properties"]; g = f["geometry"]
        if g["type"] != "LineString": continue
        line = LineString(ll_ring(g["coordinates"])); w = float(p.get("sw") or 7.0); swl = float(p.get("swl") or 0); swr = float(p.get("swr") or 0)
        net = p.get("net") or ""; hw = p.get("hw") or ""
        if not swl and not swr and net != "freeway" and hw not in ("motorway", "motorway_link", "trunk", "trunk_link"): swl = swr = 2.0
        asphalt.append(line.buffer(w / 2.0, cap_style=2, join_style=2))
        if swl or swr: walk.append(line.buffer(w / 2.0 + max(swl, swr), cap_style=2, join_style=2))
    return asphalt, walk


def streets_from_osm(slug, bbox):
    q = f'[out:json][timeout:120];(way["highway"~"^({"|".join(HW)})$"]({bbox}););out geom;'
    els = overpass(q, os.path.join(CEROOT, slug, "highways_osm.json")); asphalt, walk = [], []
    for el in els:
        if el.get("type") != "way" or "geometry" not in el or len(el["geometry"]) < 2: continue
        t = el.get("tags", {}); hw = t.get("highway"); cw, pw = HW.get(hw, (5.0, 0.0))
        try:
            if t.get("width"): cw = max(2.0, min(40.0, float(str(t["width"]).split()[0])))
            elif t.get("lanes"): cw = max(cw, 3.5 * float(t["lanes"]))
        except Exception: pass
        line = LineString(ll_ring([(g["lon"], g["lat"]) for g in el["geometry"]]))
        if hw in ("footway", "cycleway", "pedestrian", "track"):
            walk.append(line.buffer(cw / 2.0, cap_style=2, join_style=2)); continue
        asphalt.append(line.buffer(cw / 2.0, cap_style=2, join_style=2))
        if pw: walk.append(line.buffer(cw / 2.0 + pw, cap_style=2, join_style=2))
    return asphalt, walk


CLASS = {"natural=water": "water", "natural=wetland": "wetland", "leisure=swimming_pool": "pool", "landuse=grass": "grass", "leisure=garden": "grass", "leisure=park": "grass",
         "landuse=recreation_ground": "grass", "landuse=village_green": "grass", "leisure=pitch": "pitch", "leisure=golf_course": "grass", "leisure=playground": "grass",
         "landuse=forest": "grass", "natural=wood": "grass", "natural=scrub": "scrub", "natural=sand": "sand", "natural=beach": "sand", "landuse=construction": "construction",
         "landuse=brownfield": "construction", "amenity=parking": "parking", "highway=pedestrian": "pavement", "highway=footway": "pavement", "highway=service": "asphalt2"}
LANDUSE_Q = '''[out:json][timeout:120];(
  way["landuse"~"grass|park|recreation_ground|village_green|forest|construction|brownfield"]({b});
  way["leisure"~"park|garden|pitch|golf_course|playground|swimming_pool"]({b});
  way["natural"~"water|sand|scrub|wetland|wood|beach"]({b}); way["water"]({b}); way["amenity"="parking"]({b});
  way["highway"~"pedestrian|footway|service"]["area"="yes"]({b});
  relation["natural"~"water|wetland"]({b}); relation["leisure"~"park|golf_course"]({b}); relation["landuse"~"grass|park|recreation_ground|forest"]({b});
);out geom;'''


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
        return [Polygon(ll_ring(pts))] if len(pts) >= 4 and pts[0] == pts[-1] else []
    if el["type"] == "relation":
        outers, inners = [], []
        for m in el.get("members", []):
            if m.get("type") != "way" or "geometry" not in m: continue
            pts = [(g["lon"], g["lat"]) for g in m["geometry"]]
            if len(pts) < 4 or pts[0] != pts[-1]: continue
            (outers if m.get("role") != "inner" else inners).append(Polygon(ll_ring(pts)))
        if not outers: return []
        u = unary_union(outers)
        return [u.difference(unary_union(inners)) if inners else u]
    return []


ORDER = [("water", 1.0, (0.02, 0.07, 0.09), 0.03, 1.0), ("wetland", 1.5, (0.20, 0.24, 0.16), 0.9, 0.3), ("sand", 2.0, (0.70, 0.62, 0.46), 0.95, 0.2),
         ("construction", 2.0, (0.60, 0.54, 0.44), 0.95, 0.2), ("scrub", 2.5, (0.36, 0.38, 0.24), 0.9, 0.2), ("grass", 3.0, (0.17, 0.30, 0.10), 0.9, 0.2),
         ("pitch", 3.5, (0.14, 0.34, 0.12), 0.85, 0.2), ("parking", 4.0, (0.16, 0.16, 0.16), 0.85, 0.3), ("pavement", 5.0, (0.60, 0.58, 0.54), 0.95, 0.2),
         ("asphalt2", 6.0, (0.12, 0.12, 0.12), 0.88, 0.3), ("asphalt", 7.0, (0.085, 0.085, 0.09), 0.86, 0.35), ("pool", 8.0, (0.05, 0.35, 0.45), 0.02, 1.0)]


def tri_polygon(pg, z):
    if pg.is_empty: return [], []
    rings = [list(pg.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in pg.interiors]
    pts = np.array([to_ue(x, y) for ring in rings for (x, y) in ring], dtype=np.float64); ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(pts, ends); verts = []
    for x, y in pts: verts += [round(x, 1), round(y, 1), z]
    return verts, idx.tolist()


def build(slug):
    CE = os.path.join(CEROOT, slug); t0 = time.time(); bbox = bbox_of(slug)
    sp = os.path.join(CE, "streets.geojson")
    asphalt, walk = streets_from_ce(sp) if os.path.exists(sp) else streets_from_osm(slug, bbox)
    src = "cityengine" if os.path.exists(sp) else "osm"
    A = unary_union(asphalt) if asphalt else Polygon(); W = unary_union(walk).difference(A) if walk else None
    els = overpass(LANDUSE_Q.replace("{b}", bbox), os.path.join(CE, "landuse_osm.json"))
    buckets = {}
    for el in els:
        lay = layer_of(el.get("tags", {}))
        if not lay: continue
        for pg in polys_from(el):
            if pg.is_valid and pg.area > 4: buckets.setdefault(lay, []).append(pg)
    layers = {k: unary_union(v) for k, v in buckets.items()}
    if not A.is_empty: layers["asphalt"] = A
    if W is not None and not W.is_empty: layers["pavement"] = unary_union([layers["pavement"], W]) if "pavement" in layers else W
    out = []
    for name, z, rgb, rough, spec in ORDER:
        if name not in layers: continue
        g = layers[name]; polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]; V, T = [], []
        for pg in polys:
            if pg.area < 2: continue
            pg = pg.simplify(0.15, preserve_topology=True); v, t = tri_polygon(pg, z); base = len(V) // 3; V += v; T += [i + base for i in t]
        out.append({"name": name, "z_cm": z, "rgb": rgb, "roughness": rough, "specular": spec, "verts": V, "tris": T})
    p = os.path.join(CE, "context_ue.json")
    json.dump({"slug": slug, "streets": src, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "layers": out}, open(p, "w"))
    log(f"{slug:28s} streets={src:10s} asphalt {A.area/1e4:6.1f} ha  layers " + " ".join(f"{L['name']}:{len(L['tris'])//3}" for L in out) + f"  ({os.path.getsize(p)//1024} KB, {time.time()-t0:.0f}s)")


def main():
    args = sys.argv[1:] or ["sobhaheartland"]
    slugs = sorted(d for d in os.listdir(CEROOT) if not d.startswith("_") and os.path.exists(os.path.join(CEROOT, d, "buildings.geojson"))) if args == ["all"] else args
    for s in slugs:
        try: build(s)
        except Exception as ex: log(f"{s}: FAILED {ex}")


if __name__ == "__main__":
    main()
