"""v8 context for the Sobha tour: every OTHER building within a block or two of a Sobha building, as ghost massing, and the
streets under all of it - so the Sobha towers stand in a city, not in empty desert.

Kendall, 24 Sep 2026: "add the rest of the buildings ... within the radius of the Sobha buildings ... transparent, just very
very light ... those buildings won't need labels ... put in a street instead of just having empty desert."

  ctx_buildings.obj    non-Sobha footprints whose centroid lies within RADIUS_M of any Sobha footprint (all districts, not
                       only the Sobha ones - Meydan One sits against Hartland). Extruded prisms (scripts/ue_city_build.prism),
                       heights from the store (building.height_m), then geojson bHeight, then 12 m. A footprint that overlaps a
                       Sobha footprint is dropped (the Sobha LOD 3 tower is already there); the district files overlap at
                       their edges, so footprints are de-duplicated by centroid (1 m).
  ctx_<layer>.obj      the street layers of data/ce/<slug>/context_ue.json (scripts/ue_context_layer.py: roads + pavements
                       from CityEngine streets.geojson or OSM with widths by class; parks, pitches, parking) for every Sobha
                       district, merged per layer. Water and sand are left out - the tour has its own sea and sand.
  context_meshes.json  per mesh: counts, material hints (rgb, roughness, specular) and the expected XY bounds in Unreal cm,
                       which the Unreal side checks after import (an OBJ importer that mirrors Y shows up as swapped bounds).
All geometry is in Unreal cm on the shared city origin (sobhaheartland_georef offset), Z up - the same frame as the Sobha
Datasmith imports and the sand/water ground. Output: data/ce/_datasmith/context/
Usage: python scripts/build_sobha_context_meshes.py [--radius 300]
"""
import json, os, sys, time

from pyproj import Transformer
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_city_build as CB

ROOT = CB.ROOT; CE = CB.CE
OUT = os.path.join(CE, "_datasmith", "context"); os.makedirs(OUT, exist_ok=True)
MASK = os.path.join(ROOT, "data", "board", "sobha_mask.json")
RADIUS_M = float(sys.argv[sys.argv.index("--radius") + 1]) if "--radius" in sys.argv else 300.0
LAYERS = ["asphalt", "pavement", "parking", "grass", "pitch", "pool"]
tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def to_utm(g):
    from shapely.ops import transform
    return transform(lambda x, y, z=None: tr.transform(x, y), g)


def write_obj(path, V, T, name):
    with open(path, "w", encoding="utf-8") as f:
        f.write("o %s\n" % name)
        for k in range(0, len(V), 3):
            f.write("v %.1f %.1f %.1f\n" % (V[k], V[k + 1], V[k + 2]))
        for k in range(0, len(T), 3):
            f.write("f %d %d %d\n" % (T[k] + 1, T[k + 1] + 1, T[k + 2] + 1))
    xs = V[0::3]; ys = V[1::3]
    return {"verts": len(V) // 3, "tris": len(T) // 3, "bounds_cm": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))] if xs else None,
            "kb": os.path.getsize(path) // 1024}


def main():
    mask = json.load(open(MASK, encoding="utf-8"))
    sobha_slugs = sorted(s for s, d in mask["districts"].items() if d.get("i"))
    # 1. Sobha footprints in UTM, every district
    sobha = []
    for s in sobha_slugs:
        feats = json.load(open(os.path.join(CE, s, "buildings.geojson"), encoding="utf-8"))["features"]
        for i in mask["districts"][s]["i"]:
            i = int(i)
            if i < len(feats):
                g = shape(feats[i]["geometry"])
                if not g.is_empty:
                    sobha.append(to_utm(g).buffer(0))
    zone = unary_union(sobha).buffer(RADIUS_M)
    tree = STRtree(sobha)
    zx0, zy0, zx1, zy1 = zone.bounds
    log("Sobha footprints %d in %d districts; context zone %.0f m -> %.1f km2" % (len(sobha), len(sobha_slugs), RADIUS_M, zone.area / 1e6))
    # 2. candidate districts: any whose buildings bbox meets the zone
    idx = json.load(open(os.path.join(CE, "_city", "INDEX.json"), encoding="utf-8"))
    ux0, uy0 = (zx0 + CB.OFF[0]) * 100, (-zy1 + CB.OFF[2]) * 100; ux1, uy1 = (zx1 + CB.OFF[0]) * 100, (-zy0 + CB.OFF[2]) * 100
    slugs = sorted(set(sobha_slugs) | {s for s, v in idx.items() if v.get("bbox_cm") and not (v["bbox_cm"][2] < ux0 or v["bbox_cm"][0] > ux1 or v["bbox_cm"][3] < uy0 or v["bbox_cm"][1] > uy1)})
    try:
        H = CB.heights()
    except Exception as e:
        log("height store unavailable (%s) - geojson heights only" % e); H = {}
    V, T, seen, kept, by = [], [], set(), 0, {}
    for s in slugs:
        p = os.path.join(CE, s, "buildings.geojson")
        if not os.path.exists(p):
            continue
        feats = json.load(open(p, encoding="utf-8"))["features"]
        own = {int(i) for i in (mask["districts"].get(s, {}).get("i") or [])}
        n = 0
        for i, f in enumerate(feats):
            if i in own:
                continue
            g = shape(f["geometry"])
            if g.is_empty:
                continue
            gu = to_utm(g).buffer(0)
            c = gu.centroid
            if not zone.contains(c):
                continue
            key = (round(c.x), round(c.y))
            if key in seen:
                continue
            hit = False
            for j in tree.query(gu):
                sp = sobha[int(j)]
                if sp.intersects(gu) and sp.intersection(gu).area > 0.3 * min(sp.area, gu.area):
                    hit = True; break
            if hit:
                continue
            seen.add(key)
            h = H.get((s, i)) or f["properties"].get("bHeight") or 12.0
            h = max(3.0, min(float(h), 900.0))
            for pg in (list(g.geoms) if isinstance(g, MultiPolygon) else [g]):
                if isinstance(pg, Polygon) and pg.area > 1e-10:
                    pg = pg.simplify(1e-6, preserve_topology=True)
                    if len(pg.exterior.coords) >= 4:
                        CB.prism(pg, h * 100.0, V, T)
            n += 1
        if n:
            by[s] = n; kept += n
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"), "radius_m": RADIUS_M, "sobha_districts": sobha_slugs, "meshes": {}}
    meta["meshes"]["ctx_buildings"] = dict(write_obj(os.path.join(OUT, "ctx_buildings.obj"), V, T, "ctx_buildings"), buildings=kept, by_district=by,
                                           rgb=[0.92, 0.94, 0.97], role="ghost")
    log("ghost buildings: %d from %d districts %s" % (kept, len(by), by))
    # 3. street layers from the Sobha districts' context_ue.json
    acc = {}
    for s in sobha_slugs:
        p = os.path.join(CE, s, "context_ue.json")
        if not os.path.exists(p):
            log("  %s: no context_ue.json - no streets there" % s); continue
        for L in json.load(open(p, encoding="utf-8")).get("layers", []):
            if L["name"] not in LAYERS:
                continue
            A = acc.setdefault(L["name"], {"V": [], "T": [], "rgb": L.get("rgb"), "roughness": L.get("roughness"), "specular": L.get("specular"), "z_cm": L.get("z_cm"), "from": []})
            base = len(A["V"]) // 3
            A["V"] += L["verts"]; A["T"] += [t + base for t in L["tris"]]; A["from"].append(s)
    for name, A in acc.items():
        meta["meshes"]["ctx_%s" % name] = dict(write_obj(os.path.join(OUT, "ctx_%s.obj" % name), A["V"], A["T"], "ctx_%s" % name),
                                               rgb=A["rgb"], roughness=A["roughness"], specular=A["specular"], z_cm=A["z_cm"], districts=A["from"], role="ground")
        log("  ctx_%-10s %7d tris from %s" % (name, len(A["T"]) // 3, ",".join(A["from"])))
    json.dump(meta, open(os.path.join(OUT, "context_meshes.json"), "w", encoding="utf-8"), indent=1)
    log("context meshes -> %s" % OUT)


if __name__ == "__main__":
    main()
