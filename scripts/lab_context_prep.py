"""LAB (context / scenery, research only): the initial shapes for lab_context.cga, built from the SAME data Unreal uses.

GROUND - the geometry of the Business Bay level L_BB_v1, not a re-derivation:
  data/ce/<slug>/context_ue.json          construction, grass, pitch, parking, pavement, asphalt, pool (ue_context_layer.py;
                                          Unreal's ctx_<layer>.obj are these triangles)
  data/ce/_datasmith/bb_v1/v1_*.obj       plots, podium, promenade, kerb, mark_white, mark_yellow, canal_water, quay
                                          (bb_v1_prep.py - the paved plots, kerbs and markings of L_BB_v1)
  data/ce/_datasmith/ground/inland_water.obj   the city water mesh Unreal places as WATER_Inland
  + a sand rectangle over the district (Unreal's 40 km GROUND_Sand plane, cut to the district)
  Triangles are unioned back into polygons per role (they were polygons before ue_context_layer triangulated them),
  clipped to the district rectangle (ground_imagery.json - the web viewer's ground plane) and cut into TILE_M tiles.

DRESSING - placements are READ, never re-generated. Two sources (--source):
  film (default)  what Unreal's Business Bay film PLACED - data/ce/_datasmith/bb_v1/bb_v1_plan.json "dress" (median / kerb /
                  promenade / park palms, park trees, lamps + promenade lamps, benches, planters, promenade cafes) and its
                  construction "sites" (cranes + site kit, re-drawn with ue_bb_v1_build.sites()' own random.Random(5)
                  sequence, so every crane lands where Unreal put it) - PLUS what the plan does not give, from the JSONs:
                  bus shelters (furniture_ue: its 121 include the plan's 9), benches / bins / bollards (furniture_ue),
                  storefront planters (storefronts_ue), cars (props_ue). Every row carries klass film | json.
  json            the city-wide JSONs only (the first brief): greenery_ue palms + trees, furniture_ue, props_ue cars + lamps,
                  storefronts_ue planters.
  Species where the JSON has none: a stable hash of the UE position (zlib.crc32) picks among Unreal's species list
  (ue_sobha_foliage.SPECIES), so every engine that re-reads the JSON picks the same plant for the same spot.
  Each placement becomes a small square whose FIRST EDGE points along the object's heading and whose side length IS
  the scale jitter; the rule reads both back from the geometry (alignScopeToGeometry + scope.sx). Squares are grouped
  per (species, tile) into multi-face shapes, so Datasmith writes one HISM per species per tile, not one per object.

Writes data/lab/context/<slug>/:
  ground_shapes.json, instance_shapes.json      PyPRT initial shapes (local v5 frame, metres) + attributes
  ground_roles_wgs84.geojson                    the same ground polygons for a CityEngine scene (attr role)
  placements_quads_wgs84.geojson                the same instance groups for CityEngine (attr kind=instance, species)
  placements.json / placements_ue.csv           the normalised placement table (local m AND Unreal cm), species chosen
  prep_stats.json

  python scripts/lab_context_prep.py [businessbay] [--tile 500]
"""
import csv
import json
import math
import os
import sys
import time
import zlib
from collections import Counter, defaultdict

import mapbox_earcut as earcut
import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, box, mapping
from shapely.geometry.polygon import orient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_context_common as C

args = [a for a in sys.argv[1:] if not a.startswith("--")]
SLUG = (args or ["businessbay"])[0]
TILE_M = float(sys.argv[sys.argv.index("--tile") + 1]) if "--tile" in sys.argv else 500.0
SOURCE = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else "film"
if SOURCE in args:
    args.remove(SOURCE)
    SLUG = (args or ["businessbay"])[0]
PLAN = os.path.join(C.CE, "_datasmith", "bb_v1", "bb_v1_plan.json")      # (data/media/businessbay has none; this is the file L_BB_v1 was built from)
OUT = C.lab_dir(SLUG)
DCE = os.path.join(C.CE, SLUG)
V1 = os.path.join(C.CE, "_datasmith", "bb_v1")
GROUND_OBJ = os.path.join(C.CE, "_datasmith", "ground")
CTX_LAYERS = ["construction", "grass", "pitch", "parking", "pavement", "asphalt", "pool"]     # = bb_v0_prep CTX_LAYERS
V1_FLAT = {"plot": "v1_plots.obj", "podium": "v1_podium.obj", "promenade": "v1_promenade.obj", "kerb": "v1_kerb.obj",
           "marking_white": "v1_mark_white.obj", "marking_yellow": "v1_mark_yellow.obj", "canal": "v1_canal_water.obj"}
V1_MESH = {"quay": "v1_quay.obj", "hoarding": "v1_hoarding.obj", "rail_steel": "v1_rail_steel.obj", "rail_glass": "v1_rail_glass.obj"}
FILM_TREES = ["acacia", "parkinsonia", "ficus"]         # L_BB_v1 shade_tree variants 0/1/2 = acacia_tree / frangipani / jacaranda (used_assets.json counts 692/656/652)
SHADE_TREE_M = 7.5                                      # KITS["shade_tree"] target height
STREET_SEAT_M = 2.4                                     # K["street_seat"] length (bench variant 1)
SITE_KIT = ["site_0", "site_1", "site_2", "site_3", "site_4"]
PALMS = ["date_palm", "washingtonia"]                  # ue_sobha_foliage SPECIES["palm"]
TREES = ["acacia", "ficus", "parkinsonia"]             # ue_sobha_foliage SPECIES["tree"]
LAMP_YAW_OFFSET = 90.0      # props_ue lamp yaw = road heading; the v1 double-arm lamp wants arms ACROSS the road (bb_v1_prep: yaw(dr) + 90)
SQUARE = 1.0                # placement square side at scale 1.0 (m)
TO_LL = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def read_obj(path):
    V, F = [], []
    with open(path, encoding="utf-8") as fh:
        for l in fh:
            if l.startswith("v "):
                V.append(l.split()[1:4])
            elif l.startswith("f "):
                F.append([t.split("/")[0] for t in l.split()[1:4]])
    return np.array(V, np.float64), np.array(F, np.int64) - 1


def district_rect(fr):
    gi = json.load(open(os.path.join(DCE, "ground_imagery.json"), encoding="utf-8"))
    x0, z1 = fr.utm_to_local(gi["xmin"], gi["ymin"])
    x1, z0 = fr.utm_to_local(gi["xmax"], gi["ymax"])
    return box(x0, z0, x1, z1)


def tris_to_polys(P2, T, rect):
    """P2 (n,2) local x,z; T (m,3) -> unioned polygons inside rect"""
    tri = P2[T]                                              # (m, 3, 2)
    lo, hi = tri.min(1), tri.max(1)
    b = rect.bounds
    keep = (hi[:, 0] >= b[0]) & (lo[:, 0] <= b[2]) & (hi[:, 1] >= b[1]) & (lo[:, 1] <= b[3])
    tri = tri[keep]
    if not len(tri):
        return None, 0
    ring = np.concatenate([tri, tri[:, :1]], 1)
    polys = shapely.polygons(ring)
    area = shapely.area(polys)
    polys = polys[area > 1e-6]
    u = shapely.union_all(polys, grid_size=0.001)
    return shapely.intersection(u, rect, grid_size=0.001), int(keep.sum())


def as_polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def tiles(rect):
    x0, z0, x1, z1 = rect.bounds
    nx, nz = int(math.ceil((x1 - x0) / TILE_M)), int(math.ceil((z1 - z0) / TILE_M))
    return [((i, j), box(x0 + i * TILE_M, z0 + j * TILE_M, min(x1, x0 + (i + 1) * TILE_M), min(z1, z0 + (j + 1) * TILE_M)))
            for i in range(nx) for j in range(nz)], (x0, z0)


def prt_shape(polys):
    """polygons (x,z) -> flat PRT shape, faces CCW seen from +Y (PyPRT's convention). Hole-free polygons go in as
    polygons; a polygon WITH holes is triangulated here (earcut) - PRT dropped 35 holes it judged 'outside its boundary'
    (holes touching the outline after the union), which grew the markings layer by 7-15 %. CityEngine gets the same
    polygons with their holes through ground_roles_wgs84.geojson."""
    verts, idx, counts = [], [], []
    for pg in polys:
        pg = orient(pg, sign=-1.0)                            # exterior clockwise in (x, z) == counter-clockwise seen from +y
        if not pg.interiors:
            r = list(pg.exterior.coords)[:-1]
            if len(r) < 3:
                continue
            base = len(verts) // 3
            for x, z in r:
                verts += [round(x, 3), 0.0, round(z, 3)]
            idx += list(range(base, base + len(r))); counts.append(len(r))
            continue
        rings = [list(pg.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in pg.interiors]
        pts = np.array([p for r in rings for p in r], np.float64)
        ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        tri = earcut.triangulate_float64(pts, ends).reshape(-1, 3)
        base = len(verts) // 3
        for x, z in pts:
            verts += [round(float(x), 3), 0.0, round(float(z), 3)]
        for a, b, c in tri:
            # keep counter-clockwise seen from +y (clockwise in x, z): signed area in (x, z) must be negative
            ax, az = pts[a]; bx, bz = pts[b]; cx, cz = pts[c]
            if (bx - ax) * (cz - az) - (cx - ax) * (bz - az) > 0:
                b, c = c, b
            idx += [base + int(a), base + int(b), base + int(c)]; counts.append(3)
    return {"verts": verts, "indices": idx, "face_counts": counts, "holes": []}


def to_ll_ring(fr, ring):
    out = []
    for x, z in ring:
        e, n = fr.local_to_utm(x, z)
        lon, lat = TO_LL.transform(e, n)
        out.append([round(lon, 9), round(lat, 9)])
    return out


def ground(fr, rect):
    layers = {}
    ctx = json.load(open(os.path.join(DCE, "context_ue.json"), encoding="utf-8"))
    for L in ctx["layers"]:
        if L["name"] not in CTX_LAYERS or not L["tris"]:
            continue
        V = np.array(L["verts"], np.float64).reshape(-1, 3)
        x, z = fr.ue_to_local(V[:, 0], V[:, 1])
        g, n = tris_to_polys(np.stack([x, z], 1), np.array(L["tris"], np.int64).reshape(-1, 3), rect)
        layers[L["name"]] = (g, "context_ue.json layer %s (%d of %d triangles in the district)" % (L["name"], n, len(L["tris"]) // 3))
    for role, f in V1_FLAT.items():
        V, F = read_obj(os.path.join(V1, f))
        x, z = fr.ue_to_local(V[:, 0], V[:, 1])
        g, n = tris_to_polys(np.stack([x, z], 1), F, rect)
        layers[role] = (g, "bb_v1/%s (%d of %d triangles)" % (f, n, len(F)))
    # Unreal places BOTH city water meshes at gz + 10 cm (WATER_Sea, WATER_Inland). The OSM coastline runs up Dubai Creek
    # and the Water Canal, so the Business Bay canal itself is in sea.obj - without it the canal centre is sand.
    wg, wsrc = [], []
    for f in ("sea.obj", "inland_water.obj"):
        V, F = read_obj(os.path.join(GROUND_OBJ, f))
        x, z = fr.ue_to_local(V[:, 0], V[:, 1])
        g, n = tris_to_polys(np.stack([x, z], 1), F, rect)
        if g is not None and not g.is_empty:
            wg.append(g)
        wsrc.append("%s (%d of %d triangles)" % (f, n, len(F)))
    layers["water"] = (shapely.union_all(wg, grid_size=0.001), "_datasmith/ground/" + " + ".join(wsrc))
    layers["sand"] = (rect, "district rectangle (ground_imagery.json extent) - Unreal's GROUND_Sand plane cut to the district")
    return layers


def mesh3d(fr, rect, f):
    V, F = read_obj(os.path.join(V1, f))
    x, z = fr.ue_to_local(V[:, 0], V[:, 1])
    P = np.stack([x, V[:, 2] / 100.0, z], 1)
    c = P[F].mean(1)
    b = rect.bounds
    keep = (c[:, 0] >= b[0]) & (c[:, 0] <= b[2]) & (c[:, 2] >= b[1]) & (c[:, 2] <= b[3])
    return P, F[keep], F[:, [0, 2, 1]][keep]


def species_pick(x, y, pool):
    return pool[zlib.crc32(("%d,%d" % (round(x), round(y))).encode()) % len(pool)]


def placements(fr, rect):
    rows = []                  # (cat, species, x_local, z_local, heading_deg_ue, scale, src, src_index, ue_x, ue_y, ue_yaw)
    g = json.load(open(os.path.join(DCE, "greenery_ue.json"), encoding="utf-8"))
    fu = json.load(open(os.path.join(DCE, "furniture_ue.json"), encoding="utf-8"))
    pr = json.load(open(os.path.join(DCE, "props_ue.json"), encoding="utf-8"))
    sp = os.path.join(DCE, "storefronts_ue.json")
    sf = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    src_counts = {}

    def add(cat, sp_, r, i, src, yaw, scale, off=0.0, klass="json"):
        rows.append((cat, sp_, r[0], r[1], (yaw + off) % 360.0, scale, src, i, yaw, klass))

    if SOURCE == "film":
        return film_placements(fr, rect, add, rows, fu, pr, sf)
    for i, r in enumerate(g.get("palms", [])):
        add("palm", species_pick(r[0], r[1], PALMS), r, i, "greenery_ue.palms", r[2], r[3])
    for i, r in enumerate(g.get("trees", [])):
        add("tree", species_pick(r[0], r[1], TREES), r, i, "greenery_ue.trees", r[2], r[3])
    for i, r in enumerate(fu.get("bus_shelters", [])):
        add("furniture", "bus_shelter", r, i, "furniture_ue.bus_shelters", r[2], 1.0)
    for i, r in enumerate(fu.get("benches", [])):
        add("furniture", "bench", r, i, "furniture_ue.benches", r[2], 1.0)
    for i, r in enumerate(fu.get("bins", [])):
        add("furniture", "bin", r, i, "furniture_ue.bins", 0.0, 1.0)
    for i, r in enumerate(fu.get("bollards", [])):
        add("furniture", "bollard", r, i, "furniture_ue.bollards", 0.0, 1.0)
    for i, r in enumerate(fu.get("hedges", [])):
        add("shrub", "buxus", r, i, "furniture_ue.hedges", r[2], 1.0)
    for i, r in enumerate(pr.get("cars", [])):
        add("car", "car_%d" % (int(r[3]) % 5), r, i, "props_ue.cars", r[2], r[4] if len(r) > 4 else 1.0)
    for i, r in enumerate(pr.get("lamps", [])):
        add("lamp", "lamp", r, i, "props_ue.lamps", r[2], 1.0, LAMP_YAW_OFFSET)
    for i, r in enumerate(sf.get("planters", [])):
        add("planter", "planter", r, i, "storefronts_ue.planters", 0.0, 1.0)
    return clip_rows(fr, rect, rows)


def clip_rows(fr, rect, rows):
    src_counts = dict(Counter(r[6] for r in rows))
    b = rect.bounds
    out = []
    for cat, sp_, ux, uy, head, scale, src, i, yaw_src, klass in rows:
        x, z = fr.ue_to_local(ux, uy)
        if b[0] <= x <= b[2] and b[1] <= z <= b[3]:
            out.append({"cat": cat, "species": sp_, "x": round(x, 3), "z": round(z, 3), "heading_ue_deg": round(head, 2),
                        "yaw_ue_src": yaw_src, "scale": float(scale), "src": src, "i": i, "ue_x": ux, "ue_y": uy, "klass": klass})
    return out, src_counts


def film_placements(fr, rect, add, rows, fu, pr, sf):
    """Unreal's Business Bay film: bb_v1_plan dress + sites exactly as ue_bb_v1_build.dress() / sites() place them"""
    import random
    pal = C.load_palette(SLUG)
    tgt = lambda s: pal["species"][s]["target_h_m"]
    plan = json.load(open(PLAN, encoding="utf-8"))
    D = plan["dress"]
    for key in ("median_palms", "kerb_palms", "prom_palms", "park_palms"):
        # L_BB_v1: every palm is a date palm (the washingtonia kit failed its material check; used_assets.json: 4,075 + 4,656
        # date palms = 8,731 = these four lists)
        for i, r in enumerate(D.get(key, [])):
            add("palm", "date_palm", r, i, "bb_v1_plan." + key, r[2], r[3], klass="film")
    for i, r in enumerate(D.get("park_trees", [])):
        sp_ = FILM_TREES[int(r[4]) % 3]
        add("tree", sp_, r, i, "bb_v1_plan.park_trees", r[2], r[3] * SHADE_TREE_M / tgt(sp_), klass="film")
    for key in ("lamps", "prom_lamps"):
        for i, r in enumerate(D.get(key, [])):
            add("lamp", "lamp", r, i, "bb_v1_plan." + key, r[2], 1.0, klass="film")       # plan yaw already = road heading + 90
    for i, r in enumerate(D.get("benches", [])):
        add("furniture", "bench", r, i, "bb_v1_plan.benches", r[2], (STREET_SEAT_M / 1.9) if (len(r) > 4 and r[4] == 1) else 1.0, klass="film")
    for i, r in enumerate(D.get("planters", [])):
        add("furniture", "planter", r, i, "bb_v1_plan.planters", r[2], 1.0, klass="film")
    for k, r in enumerate(D.get("prom_cafes", [])):   # ue_bb_v1_build.dress(): table, 4 chairs at 80 cm, parasol, a pot 180 cm each side
        add("furniture", "cafe_table", r, k, "bb_v1_plan.prom_cafes", r[2], 1.0, klass="film")
        for q in range(4):
            a = math.radians(r[2] + 45.0 + 90.0 * q)
            add("furniture", "cafe_chair", [r[0] + 80.0 * math.cos(a), r[1] + 80.0 * math.sin(a)], k, "bb_v1_plan.prom_cafes",
                r[2] + 45.0 + 90.0 * q + 180.0, 1.0, klass="film")
        add("furniture", "umbrella", r, k, "bb_v1_plan.prom_cafes", r[2], 1.0, klass="film")
        a = math.radians(r[2])
        for sgn in (-1, 1):
            add("furniture", "pot", [r[0] + sgn * 180.0 * math.cos(a), r[1] + sgn * 180.0 * math.sin(a)], k, "bb_v1_plan.prom_cafes", k * 40.0, 1.0, klass="film")
    # construction sites: ue_bb_v1_build.sites() verbatim - same order, same random.Random(5) draws
    rnd = random.Random(5)
    cranes, kitrows = [], []
    for q in sorted(plan.get("sites") or [], key=lambda q: -q.get("area_m2", 0)):
        x0, y0, x1, y1 = q["x0"], q["y0"], q["x1"], q["y1"]; w, h = x1 - x0, y1 - y0
        cranes.append([x0 + 0.3 * w, y0 + 0.35 * h, rnd.uniform(0, 360), rnd.uniform(0.9, 1.25), 0])
        if w * h > 6000.0 * 6000.0:
            cranes.append([x0 + 0.72 * w, y0 + 0.7 * h, rnd.uniform(0, 360), rnd.uniform(0.8, 1.1), 1])
        for k in range(max(6, min(18, int(w * h / (1500.0 * 1500.0))))):
            kitrows.append([x0 + w * rnd.uniform(0.1, 0.9), y0 + h * rnd.uniform(0.1, 0.9), rnd.choice((0, 90, 180, 270)) + rnd.uniform(-8, 8), 1.0, rnd.randrange(64)])
    for i, r in enumerate(cranes):
        add("site", "crane", r, i, "bb_v1_plan.sites.cranes", r[2], r[3], klass="film")
    for i, r in enumerate(kitrows):
        add("site", SITE_KIT[r[4] % len(SITE_KIT)], r, i, "bb_v1_plan.sites.kit", r[2], 1.0, klass="film")
    # what the plan does not give: the JSONs
    film_shelters = {(round(r[0]), round(r[1])) for r in D.get("bus_shelters", [])}
    for i, r in enumerate(fu.get("bus_shelters", [])):
        add("furniture", "bus_shelter", r, i, "furniture_ue.bus_shelters", r[2], 1.0,
            klass="film" if (round(r[0]), round(r[1])) in film_shelters else "json")
    for i, r in enumerate(fu.get("benches", [])):
        add("furniture", "bench", r, i, "furniture_ue.benches", r[2], 1.0)
    for i, r in enumerate(fu.get("bins", [])):
        add("furniture", "bin", r, i, "furniture_ue.bins", 0.0, 1.0)
    for i, r in enumerate(fu.get("bollards", [])):
        add("furniture", "bollard", r, i, "furniture_ue.bollards", 0.0, 1.0)
    for i, r in enumerate(sf.get("planters", [])):
        add("furniture", "planter", r, i, "storefronts_ue.planters", 0.0, 1.0)
    for i, r in enumerate(pr.get("cars", [])):
        add("car", "car_%d" % (int(r[3]) % 5), r, i, "props_ue.cars", r[2], r[4] if len(r) > 4 else 1.0)
    return clip_rows(fr, rect, rows)


def square(x, z, head_deg, s):
    """oriented square centred on (x, z): edge 0 along the heading, face normal +Y (PyPRT CCW)."""
    a = math.radians(head_deg)
    d = (math.cos(a), math.sin(a))                  # UE yaw turns +X (east) toward +Y (south) = local +z
    n = (d[1], -d[0])                               # d x n = +Y
    h = s / 2.0
    p0 = (x - d[0] * h - n[0] * h, z - d[1] * h - n[1] * h)
    p1 = (p0[0] + d[0] * s, p0[1] + d[1] * s)
    p2 = (p1[0] + n[0] * s, p1[1] + n[1] * s)
    p3 = (p0[0] + n[0] * s, p0[1] + n[1] * s)
    return [p0, p1, p2, p3]


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    pal = C.load_palette(SLUG)
    fr = C.Frame(SLUG)
    rect = district_rect(fr)
    tl, (tx0, tz0) = tiles(rect)
    log("%s: district %.0f x %.0f m (local %s), %d tiles of %.0f m" % (SLUG, rect.bounds[2] - rect.bounds[0], rect.bounds[3] - rect.bounds[1],
                                                                   [round(v, 1) for v in rect.bounds], len(tl), TILE_M))
    # ---------------------------------------------------------------------------------------------------- ground
    layers = ground(fr, rect)
    shapes, feats, gstats = [], [], {}
    for role, (g, src) in layers.items():
        pr = pal["roles"]["ctx_" + role]
        n_poly = 0; area = 0.0
        for (i, j), tb in tl:
            part = shapely.intersection(g, tb, grid_size=0.001)
            polys = [p.simplify(0.01, preserve_topology=True) for p in as_polys(part)]
            polys = [p for p in polys if p.is_valid and p.area > 0.05]
            if not polys:
                continue
            s = prt_shape(polys)
            s.update(kind="ground", role=role, tile=[i, j], attrs={"kind": "ground", "role": role})
            shapes.append(s)
            n_poly += len(polys); area += sum(p.area for p in polys)
            for p in polys:
                p = orient(p, sign=-1.0)                  # clockwise in (x, z) == counter-clockwise in lon/lat
                feats.append({"type": "Feature", "properties": {"kind": "ground", "role": role, "tile": "%d_%d" % (i, j), "y_m": pr["y_m"]},
                              "geometry": {"type": "Polygon", "coordinates": [to_ll_ring(fr, list(p.exterior.coords))] +
                                           [to_ll_ring(fr, list(r.coords)) for r in p.interiors]}})
        gstats[role] = {"polygons": n_poly, "area_m2": round(area), "source": src}
        log("  ground %-15s %6d polygons %10.0f m2  <- %s" % (role, n_poly, area, src))
    for role, f in V1_MESH.items():                    # walls: quay, site hoardings, quay railing - 3D, they keep their own heights
        P, F_ok, _ = mesh3d(fr, rect, f)
        c = P[F_ok].mean(1)
        for (i, j), tb in tl:
            b = tb.bounds
            sel = F_ok[(c[:, 0] >= b[0]) & (c[:, 0] < b[2]) & (c[:, 2] >= b[1]) & (c[:, 2] < b[3])]
            if not len(sel):
                continue
            used, inv = np.unique(sel.reshape(-1), return_inverse=True)
            # PRT expects CCW seen from outside: the UE OBJ winding is mirrored by the Y/Z swap, so reverse it
            tri = inv.reshape(-1, 3)[:, [0, 2, 1]]
            shapes.append({"kind": "ground", "role": role, "tile": [i, j], "attrs": {"kind": "ground", "role": role},
                           "verts": [round(float(v), 3) for v in P[used].reshape(-1)], "indices": tri.reshape(-1).tolist(),
                           "face_counts": [3] * len(tri), "holes": []})
        gstats[role] = {"triangles": int(len(F_ok)), "source": "bb_v1/%s (3D, keeps its own heights)" % f}
        log("  ground %-15s %6d triangles (3D)  <- bb_v1/%s" % (role, len(F_ok), f))
    json.dump({"slug": SLUG, "frame": pal["frame"], "origin_ce_xyz": fr.origin_ce_xyz, "tile_m": TILE_M, "district_local_bounds": list(rect.bounds),
               "shapes": shapes}, open(os.path.join(OUT, "ground_shapes.json"), "w", encoding="utf-8"), separators=(",", ":"))
    json.dump({"type": "FeatureCollection", "name": "lab_context_ground_%s" % SLUG,
               "note": "WGS84 lon/lat (GeoJSON). CityEngine: import into the EPSG:32640 scene, assign lab_context.rpk, start rule Scenery (kind = ground, role = the attribute).",
               "features": feats}, open(os.path.join(OUT, "ground_roles_wgs84.geojson"), "w", encoding="utf-8"), separators=(",", ":"))
    log("  ground: %d PRT shapes, %d GeoJSON polygons" % (len(shapes), len(feats)))
    # ---------------------------------------------------------------------------------------------------- dressing
    rows, src_counts = placements(fr, rect)
    groups = defaultdict(list)
    for r in rows:
        i = int((r["x"] - tx0) // TILE_M); j = int((r["z"] - tz0) // TILE_M)
        groups[(r["species"], r["klass"], i, j)].append(r)
    ishapes, qfeats = [], []
    for (sp_, klass, i, j), rs in sorted(groups.items()):
        verts, idx, counts = [], [], []
        mp = []
        for r in rs:
            q = square(r["x"], r["z"], r["heading_ue_deg"], SQUARE * r["scale"])
            base = len(verts) // 3
            for x, z in q:
                verts += [round(x, 4), 0.0, round(z, 4)]
            idx += list(range(base, base + 4)); counts.append(4)
            mp.append([to_ll_ring(fr, q + [q[0]])])       # clockwise in (x, z) with z = south == counter-clockwise in lon/lat (RFC 7946)
        ishapes.append({"kind": "instance", "species": sp_, "cat": rs[0]["cat"], "klass": klass, "tile": [i, j], "count": len(rs),
                        "attrs": {"kind": "instance", "species": sp_}, "verts": verts, "indices": idx, "face_counts": counts, "holes": []})
        qfeats.append({"type": "Feature", "properties": {"kind": "instance", "species": sp_, "klass": klass, "tile": "%d_%d" % (i, j), "count": len(rs)},
                       "geometry": {"type": "MultiPolygon", "coordinates": mp}})
    json.dump({"slug": SLUG, "frame": pal["frame"], "origin_ce_xyz": fr.origin_ce_xyz, "tile_m": TILE_M, "square_m": SQUARE,
               "encoding": "one face per object: edge 0 = heading (UE yaw, +X toward +Y_ue = local +z), side = SQUARE x scale",
               "shapes": ishapes}, open(os.path.join(OUT, "instance_shapes.json"), "w", encoding="utf-8"), separators=(",", ":"))
    json.dump({"type": "FeatureCollection", "name": "lab_context_placements_%s" % SLUG,
               "note": "WGS84. One MultiPolygon per (species, tile); each part is one object's square (first edge = heading, side = scale). "
                       "CityEngine: import as shapes, rule lab_context.rpk, start rule Scenery, kind = instance.",
               "features": qfeats}, open(os.path.join(OUT, "placements_quads_wgs84.geojson"), "w", encoding="utf-8"), separators=(",", ":"))
    sp_meta = pal["species"]
    json.dump({"slug": SLUG, "schema": "najma.context_placements/1", "frame": pal["frame"], "unreal_frame": pal["unreal_frame"],
               "origin_ce_xyz": fr.origin_ce_xyz, "species": sp_meta, "source": SOURCE,
               "lamp_yaw_offset_deg": {"props_ue.lamps": LAMP_YAW_OFFSET, "bb_v1_plan.lamps": 0.0},
               "species_rule": ("film: palms = date_palm (as L_BB_v1 drew them); park_trees variant 0/1/2 -> acacia / parkinsonia / ficus at 7.5 m x jitter; "
                                "bench variant 1 (street seat) = bench x 2.4/1.9; sites via random.Random(5) as ue_bb_v1_build.sites(); site kit variant %% 5 -> site_0..4. "
                                "json: palms crc32('%d,%d' % (round(ue_x), round(ue_y))) % 2 -> date_palm | washingtonia; trees % 3 -> acacia | ficus | parkinsonia. cars: colour index % 5"),
               "row": ["cat", "species", "x", "z", "heading_ue_deg", "scale", "src", "i", "ue_x", "ue_y", "yaw_ue_src", "klass"],
               "rows": [[r["cat"], r["species"], r["x"], r["z"], r["heading_ue_deg"], r["scale"], r["src"], r["i"], r["ue_x"], r["ue_y"], r["yaw_ue_src"], r["klass"]] for r in rows]},
              open(os.path.join(OUT, "placements.json"), "w", encoding="utf-8"), separators=(",", ":"))
    with open(os.path.join(OUT, "placements_ue.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cat", "species", "ue_x_cm", "ue_y_cm", "ue_yaw_deg", "scale", "target_m", "size_axis", "asset", "src", "src_index", "klass"])
        for r in rows:
            key = "car" if r["species"].startswith("car_") else ("site_kit" if r["species"].startswith("site_") else r["species"])
            m = sp_meta[key]
            tgt = m.get("target_h_m") or m.get("target_len_m")
            w.writerow([r["cat"], r["species"], r["ue_x"], r["ue_y"], r["heading_ue_deg"], r["scale"], round(tgt * r["scale"], 3) if tgt else "",
                        "h" if "target_h_m" in m else ("len" if "target_len_m" in m else "native"), m["asset"], r["src"], r["i"], r["klass"]])
    cnt = Counter(r["species"] for r in rows)
    stats = {"slug": SLUG, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "tile_m": TILE_M, "district_local_bounds": [round(v, 2) for v in rect.bounds],
             "ground": gstats, "ground_prt_shapes": len(shapes), "ground_geojson_polygons": len(feats),
             "placements_in_source": src_counts, "placements_in_district": len(rows), "by_species": dict(cnt),
             "by_cat": dict(Counter(r["cat"] for r in rows)), "instance_prt_shapes": len(ishapes), "seconds": round(time.time() - t0, 1)}
    json.dump(stats, open(os.path.join(OUT, "prep_stats.json"), "w", encoding="utf-8"), indent=1)
    log("  placements: %d of %d in the district, %d instance shapes; %s" % (len(rows), sum(src_counts.values()), len(ishapes), dict(cnt)))
    log("done in %.1f s" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
