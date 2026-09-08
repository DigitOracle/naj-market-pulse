"""District context layer — water / sea / roads / green as flat polygons for the 3D viewer.

Pulls OSM context per community, projects to UTM 40N (the CE scene frame, z = -northing),
buffers roads into polygons (so the viewer has ONE render path: polygons), solves the sea
by splitting the bbox with the OSM coastline (land side = the side containing the district
centroid), and writes a compact quantized ctx_<slug>.json aligned to the district GLB.

Trees/furniture/people are deliberately NOT here — massing scale + 5MB KV cap; they belong
to the render lane (DA_VISUAL -> CE viewport -> Chaos).

Usage:  python scripts/ce_context.py --area "business bay"
Output: data/ce/<slug>/ctx.json  (push as ctx_<slug> via the ingest channel)
"""
import json, math, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
CE = os.path.join(HERE, "..", "data", "ce")
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]

slug = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())

ROAD_W = {"motorway": 22, "trunk": 20, "primary": 15, "secondary": 11, "tertiary": 8,
          "motorway_link": 8, "trunk_link": 8, "primary_link": 7, "residential": 5.5,
          "unclassified": 5.5, "service": 3.5}


def overpass(q):
    for url in OVERPASS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers={"User-Agent": "najma-ce-context/1.0 (contact@digitalabbot.io)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)["elements"]
        except Exception as e:
            print(f"  overpass {url.split('//')[1].split('/')[0]}: {e} — trying mirror")
            time.sleep(3)
    sys.exit("Overpass unreachable on all mirrors")


def glb_center(sl):
    """Center of the district GLB in scene frame — context aligns to THIS, not its own bbox."""
    import struct
    p = os.path.join(CE, "_glb", f"sky_{sl}_0.glb")
    if not os.path.exists(p):
        return None
    b = open(p, "rb").read()
    ln = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + ln])
    xs, zs = [], []
    for m in j["meshes"]:
        for prim in m["primitives"]:
            a = j["accessors"][prim["attributes"]["POSITION"]]
            xs += [a["min"][0], a["max"][0]]; zs += [a["min"][2], a["max"][2]]
    return ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2)


def main():
    from shapely.geometry import shape, Point, Polygon, LineString, box, mapping
    from shapely.ops import unary_union, polygonize, transform as shp_transform
    import pyproj

    if "--area" not in sys.argv:
        sys.exit('usage: python scripts/ce_context.py --area "business bay"')
    want = sys.argv[sys.argv.index("--area") + 1]
    areas = json.load(open(os.path.join(PUB, "mp_areas.json"), encoding="utf-8"))
    ft = next((f for f in areas["features"] if slug(f["properties"]["n"]) == slug(want)), None)
    tile_gj = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ce", slug(want), "buildings.geojson")
    if not ft and os.path.exists(tile_gj):
        # v86: a model TILE (jltnorth / jltsouth) has no community polygon of its own - frame it on its footprints' hull
        from shapely.ops import unary_union as _uu
        _fc = json.load(open(tile_gj, encoding="utf-8"))
        poly = _uu([shape(f["geometry"]) for f in _fc["features"]]).convex_hull
        name = slug(want); sl = name
    elif not ft:
        sys.exit(f'no boundary polygon for "{want}"')
    else:
        name = ft["properties"]["n"]; sl = slug(name)
        poly = shape(ft["geometry"])
    b = poly.buffer(0.004).bounds                                  # ~400m frame beyond the district
    bbox = f"{b[1]},{b[0]},{b[3]},{b[2]}"
    print(f"{name}: context bbox {tuple(round(x,3) for x in b)}")

    q = f"""[out:json][timeout:120];(
      way["natural"="water"]({bbox}); relation["natural"="water"]({bbox});
      way["waterway"~"riverbank|dock|canal"]({bbox});
      way["natural"="coastline"]({bbox});
      way["highway"~"^({'|'.join(ROAD_W)})$"]({bbox});
      way["leisure"~"park|garden"]({bbox}); way["landuse"~"grass|recreation_ground|village_green|forest"]({bbox});
    );out geom;"""
    els = overpass(q)
    print(f"  {len(els)} elements")

    to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
    scene = lambda g: shp_transform(lambda x, y: (to_utm(x, y)[0], -to_utm(x, y)[1]), g)  # z = -northing

    def ring_geoms(e):
        if e.get("type") == "way" and e.get("geometry"):
            pts = [(p["lon"], p["lat"]) for p in e["geometry"]]
            if len(pts) >= 4 and pts[0] == pts[-1]:
                try: return [Polygon(pts).buffer(0)]
                except Exception: return []
        if e.get("type") == "relation":
            outs = []
            for mm in e.get("members", []):
                if mm.get("role") == "outer" and mm.get("geometry"):
                    pts = [(p["lon"], p["lat"]) for p in mm["geometry"]]
                    if len(pts) >= 4:
                        try: outs.append(Polygon(pts).buffer(0))
                        except Exception: pass
            return outs
        return []

    water, green, coast, roads = [], [], [], []
    for e in els:
        t = e.get("tags", {})
        if t.get("natural") == "coastline" and e.get("geometry"):
            coast.append(LineString([(p["lon"], p["lat"]) for p in e["geometry"]]))
        elif t.get("natural") == "water" or re.match("riverbank|dock|canal", t.get("waterway", "") or ""):
            water += ring_geoms(e)
        elif t.get("leisure") or t.get("landuse"):
            green += ring_geoms(e)
        elif t.get("highway") in ROAD_W and e.get("geometry"):
            roads.append((ROAD_W[t["highway"]], LineString([(p["lon"], p["lat"]) for p in e["geometry"]])))

    frame = box(*b)
    # sea: split the frame by the merged coastline; keep pieces NOT holding the district centroid
    sea = []
    if coast:
        try:
            merged = unary_union(coast)
            pieces = list(polygonize(unary_union([frame.boundary, merged])))
            landmark = poly.representative_point()
            sea = [p for p in pieces if not p.contains(landmark) and p.area > 1e-7]
            print(f"  sea: {len(sea)} piece(s) from coastline")
        except Exception as ex:
            print("  sea solve failed:", str(ex)[:80])

    road_polys = []
    if roads:
        # buffer in metres (UTM), grouped by width for fewer unions
        from collections import defaultdict
        byw = defaultdict(list)
        for w, ls in roads: byw[w].append(scene(ls))
        for w, lss in byw.items():
            try: road_polys.append(unary_union([l.buffer(w / 2, resolution=4) for l in lss]).simplify(0.8))
            except Exception: pass

    def emit(geoms, already_scene=False, clip=True):
        out = []
        for g in geoms:
            try:
                gg = g if already_scene else scene(g.intersection(frame) if clip else g)
                if gg.is_empty: continue
                polys = getattr(gg, "geoms", [gg])
                for p in polys:
                    if not isinstance(p, Polygon) or p.area < (20 if already_scene else 0): continue
                    rings = [[[round(x, 1), round(z, 1)] for x, z in p.exterior.coords]]
                    rings += [[[round(x, 1), round(z, 1)] for x, z in i.coords] for i in p.interiors]
                    out.append(rings)
            except Exception:
                pass
        return out

    ctx = {"district": sl,
           "water": emit([unary_union([w.buffer(0) for w in water]).simplify(1e-6)] if water else []),
           "sea": emit(sea),
           "green": emit([unary_union([g.buffer(0) for g in green]).simplify(1e-6)] if green else []),
           "roads": emit(road_polys, already_scene=True, clip=False)}
    c = glb_center(sl)
    if c: ctx["glb_center"] = [round(c[0], 1), round(c[1], 1)]
    out = os.path.join(CE, sl); os.makedirs(out, exist_ok=True)
    p = os.path.join(out, "ctx.json")
    json.dump(ctx, open(p, "w"), separators=(",", ":"))
    kb = os.path.getsize(p) // 1024
    print(f"  water {len(ctx['water'])} · sea {len(ctx['sea'])} · green {len(ctx['green'])} · road-groups {len(ctx['roads'])} -> {kb} KB")
    if kb > 4500: print("  ⚠️ near the 5MB KV cap — raise simplify tolerances")
    print(f"-> {p}")


if __name__ == "__main__":
    main()
