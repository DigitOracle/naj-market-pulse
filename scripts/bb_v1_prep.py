"""Business Bay v1 fly-through, step 1 (plain CPython): v0's camera + a rebuilt, VALIDATED street/waterfront layer.

v1 fixes Kendall's v0 review (28 Sep): waterfront (quay wall, promenade, railing, palms, lamps, benches, planters, plots),
boats only on water, roads with markings + kerbs, cars only on lanes/parking bays, formal tree rows, lamps from primitives,
no pack pieces (the barrier_traffic_cone_pack pieces scaled x40-x83 were the floating black squares), per-frame camera
clearance (25 m), site hoardings instead of pack fences.

Frame: UE cm, X = easting - 328289, Y = 2784598 - northing (as v0). Land level: every v1 land mesh is written relative to
the district LAND level; the build places it at gz + LIFT_CM, so the canal water (gz + 30) sits LIFT_CM below the
promenade behind a vertical quay wall.
Writes data/ce/_datasmith/bb_v1/: ctx_*.obj (v0 layers), v1_*.obj (new meshes), bb_v1_plan.json, bb_v1_validation.json.
Usage: python scripts/bb_v1_prep.py
"""
import json, math, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bb_v0_prep as P0
from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, box
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.affinity import rotate, translate

ROOT = P0.ROOT
OUT = os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v1")
P0.OUT = OUT                                     # v0 helpers write their ctx_*.obj here
P0.TOTAL_S = 121.0                               # +5 s steady hold: the 20 s teaser = finale pull-back 10 s + hold 10 s
P0.TEASER = [[101.0, 121.0]]
LIFT_CM = 120.0                                  # promenade / street level above the canal water
WATER_Z = -LIFT_CM + 30.0                        # canal surface, relative to land level
CAR_ROADS = {"primary", "secondary", "tertiary", "residential", "trunk", "primary_link", "secondary_link", "tertiary_link", "trunk_link"}
PALM_ROADS = {"primary", "secondary", "trunk", "tertiary"}
rnd = random.Random(21)
VAL = {}


def vlog(key, ok, bad):
    VAL[key] = {"kept": ok, "rejected": bad}
    print("  validate %-16s kept %5d  rejected %5d" % (key, ok, bad))


# ------------------------------------------------------------------------------------------------ geometry -> OBJ
class Obj:
    def __init__(self):
        self.V, self.T = [], []

    def tri(self, a, b, c):
        n = len(self.V) // 3
        self.V += list(a) + list(b) + list(c); self.T += [n, n + 1, n + 2]

    def quad(self, a, b, c, d):
        self.tri(a, b, c); self.tri(a, c, d)

    def poly(self, g, z):
        for pg in (g.geoms if hasattr(g, "geoms") else [g]):
            if not isinstance(pg, Polygon) or pg.is_empty or pg.area < 1.0:
                continue
            for t in constrained_delaunay_triangles(pg).geoms:
                c = list(t.exterior.coords)[:3]
                self.tri(*[(x, y, z) for x, y in c])

    def wall(self, line, z0, z1):
        cs = list(line.coords)
        for k in range(len(cs) - 1):
            (ax, ay), (bx, by) = cs[k][:2], cs[k + 1][:2]
            self.quad((ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1))

    def box(self, x0, y0, z0, x1, y1, z1):
        P = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for k in range(4):
            a, b = P[k], P[(k + 1) % 4]
            self.quad((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1))
        self.quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
        self.quad((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0))

    def save(self, name):
        if not self.T:
            return None
        return P0.write_obj(os.path.join(OUT, name + ".obj"), self.V, self.T, name)


def layer_geom(name):
    d = P0.load(os.path.join(P0.BB, "context_ue.json"))
    for L in d["layers"]:
        if L["name"] == name and L.get("tris"):
            V, T = L["verts"], L["tris"]
            tris = [Polygon([(V[3 * i], V[3 * i + 1]) for i in T[k:k + 3]]) for k in range(0, len(T), 3)]
            return unary_union([t.buffer(1.0) for t in tris if t.area > 0]).buffer(-1.0)
    return Polygon()


def lines_of(g):
    out = []
    for pg in (g.geoms if hasattr(g, "geoms") else [g]):
        if isinstance(pg, Polygon):
            out.append(pg.exterior); out += list(pg.interiors)
    return out


def dash(line, on, off):
    L, d, out = line.length, 0.0, []
    while d < L:
        a, b = d, min(L, d + on)
        if b - a > 20:
            out.append(LineString([line.interpolate(a).coords[0], line.interpolate(b).coords[0]]))
        d += on + off
    return out


# ------------------------------------------------------------------------------------------------ local meshes (props)
def prop_meshes():
    m = {}
    # Dubai double-arm street lamp: 10 m tapered pole, two 2.2 m arms, two LED heads (heads = own mesh, emissive)
    body, head = Obj(), Obj()
    body.box(-14, -14, 0, 14, 14, 1000)
    body.box(-24, -24, 0, 24, 24, 90)                           # base plinth
    for s in (-1, 1):
        body.box(min(0, s * 220), -6, 950, max(0, s * 220), 6, 962)
        head.box(s * 220 - 45, -16, 935, s * 220 + 45, 16, 952)
    m["lamp_body"] = body.save("v1_lamp_body"); m["lamp_head"] = head.save("v1_lamp_head")
    # abra: 10 m timber hull, 2.8 m beam, flat canopy on posts
    hull, roof = Obj(), Obj()
    for k in range(10):
        x0, x1 = -500 + 100 * k, -400 + 100 * k
        taper = 1.0 - (max(0, abs((x0 + x1) / 2) - 300) / 250.0)
        hw = 140 * max(0.35, taper)
        hull.box(x0, -hw, 0, x1, hw, 90)
    for x in (-300, 300):
        for y in (-110, 110):
            roof.box(x - 5, y - 5, 90, x + 5, y + 5, 260)
    roof.box(-380, -135, 260, 380, 135, 272)
    m["abra_hull"] = hull.save("v1_abra_hull"); m["abra_roof"] = roof.save("v1_abra_roof")
    # wake: a V of foam behind a 1 m boat (scaled by boat length), heading +X, at the water surface
    wk = Obj()
    for s in (-1, 1):
        wk.tri((-0.5, s * 0.1, 0), (-4.5, s * 1.6, 0), (-4.5, s * 1.1, 0))
    wk.quad((-0.5, -0.25, 0), (-2.2, -0.35, 0), (-2.2, 0.35, 0), (-0.5, 0.25, 0))
    wk.V = [v * 100.0 if i % 3 != 2 else v for i, v in enumerate(wk.V)]
    m["wake"] = wk.save("v1_wake")
    pl = Obj(); pl.box(-60, -60, 0, 60, 60, 55)                  # planter 1.2 m square
    m["planter"] = pl.save("v1_planter")
    return m


# ------------------------------------------------------------------------------------------------ main build
def canal_low(keys, water):
    """canal glide lowered to 12 m and moved towards one bank (the quay face + promenade fill the frame); 15 m from the
    quay at least; blended in over 53-56 s and out over 77-79 s"""
    from shapely.prepared import prep as _prep
    inner = _prep(water.buffer(-1500))
    def w(t):
        if t < 53 or t > 79: return 0.0
        if t < 56: return (t - 53) / 3.0
        if t > 77: return (79 - t) / 2.0
        return 1.0
    glide = [k for k in keys if 56 <= k[0] <= 77]
    best = None
    for side in (1, -1):
        for off in (3500.0, 3000.0, 2500.0, 2000.0, 1500.0):
            ok = True
            for j in range(len(glide) - 1):
                p0, p1 = glide[j][1], glide[j + 1][1]
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]; n = math.hypot(dx, dy) or 1.0
                q = (p0[0] - dy / n * off * side, p0[1] + dx / n * off * side)
                if not inner.contains(Point(q)):
                    ok = False; break
            if ok:
                if best is None or off > best[0]: best = (off, side)
                break
    off, side = best or (0.0, 1)
    orig = [list(k[1]) for k in keys]           # directions from the UNSHIFTED path (29 Sep: reading already-shifted
    for j, k in enumerate(keys):                # neighbours flipped the normal every key -> 50 m zig-zag at film 35 s)
        a = w(k[0])
        if a <= 0: continue
        nb = orig[min(len(keys) - 1, j + 1)]; pb = orig[max(0, j - 1)]
        dx, dy = nb[0] - pb[0], nb[1] - pb[1]; n = math.hypot(dx, dy) or 1.0
        k[1][0] += a * (-dy / n * off * side); k[1][1] += a * (dx / n * off * side)
        k[1][2] = k[1][2] * (1 - a) + 1200.0 * a
    print("  canal glide: 12 m, %.0f m towards the bank (side %d)" % (off / 100, side))
    VAL["canal_offset_m"] = off / 100
    return keys


def keys_only():
    """BB_V1_KEYS_ONLY=1: recompute the camera keys (v0 plan + clearance) into the existing bb_v1_plan.json"""
    P0.OUT = OUT
    ctx, sites = P0.context_layers(); P0.PLAN_SITES.extend(sites)
    base = P0.plan()
    pth = os.path.join(OUT, "bb_v1_plan.json"); plan = json.load(open(pth, encoding="utf-8"))
    plan["keys"] = clearance(canal_low(base["keys"], layer_geom("water")), fps, plan["fps"])
    json.dump(plan, open(pth, "w", encoding="utf-8"), separators=(",", ":"))
    v = json.load(open(os.path.join(OUT, "bb_v1_validation.json"), encoding="utf-8")); v["camera_frames_clipping"] = VAL.get("camera_frames_clipping")
    json.dump(v, open(os.path.join(OUT, "bb_v1_validation.json"), "w", encoding="utf-8"), indent=1)


def main():
    if os.environ.get("BB_V1_KEYS_ONLY") == "1":
        return keys_only()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    print("bb_v1_prep: v0 context layers + camera plan")
    ctx, sites = P0.context_layers()
    P0.PLAN_SITES.extend(sites)
    plan = P0.plan()
    ctx.update(P0.surroundings(plan["district"]["bbox_cm"]))
    bx = plan["district"]["bbox_cm"]

    print("bb_v1_prep: geometry")
    water = layer_geom("water")
    asphalt = layer_geom("asphalt"); pavement = layer_geom("pavement"); parking = layer_geom("parking")
    grass = layer_geom("grass"); constr = layer_geom("construction")
    blds = P0.buildings()
    fps = []
    for b in blds:
        try:
            g = Polygon([(v[0], v[1]) for v in b["ring"]]).buffer(0)
            if g.area > 0:
                fps.append((g, b["h"]))
        except Exception:
            pass
    bld = unary_union([g for g, _ in fps])
    region = unary_union([asphalt, pavement, grass, parking, constr, bld]).buffer(6000).buffer(-5000)
    region = region.intersection(box(bx[0] - 20000, bx[1] - 20000, bx[2] + 20000, bx[3] + 20000))
    water = water.intersection(region.buffer(3000))
    land = region.difference(water)
    print("  water %.2f km2, asphalt %.2f km2, land region %.2f km2" % (water.area / 1e10, asphalt.area / 1e10, land.area / 1e10))
    P_asph, P_bld, P_water, P_park = prep(asphalt.buffer(30)), prep(bld.buffer(200)), prep(water.buffer(300)), prep(parking.buffer(-30))
    water_in5 = prep(water.buffer(-500))
    carriage = prep(asphalt.buffer(-20))

    meshes = {}
    # A. waterfront -----------------------------------------------------------------------------------------------
    o = Obj(); o.poly(water, WATER_Z); meshes["canal"] = o.save("v1_canal_water")
    quay = Obj(); rail = Obj(); cap = Obj()
    edge = [l for l in lines_of(water)]
    road_mask = prep(asphalt.buffer(100))
    for l in edge:
        ls = LineString(l.coords)
        quay.wall(ls, WATER_Z - 60, 8)                                  # stone quay wall, water -> coping
        inner = LineString(l.coords).parallel_offset(40, "left") if False else None
        for piece in dash(ls.segmentize(300), 300, 0.001):
            mid = piece.interpolate(0.5, normalized=True)
            if road_mask.contains(mid) or not land.buffer(200).contains(mid):
                continue                                                # bridges / road crossings: no railing
            rail.wall(piece, 8, 110)                                    # glass balustrade 1.1 m
            cap.wall(piece, 104, 114)                                   # steel handrail band
    coping = water.buffer(60).difference(water).intersection(land.buffer(100))
    quay.poly(coping, 8)
    meshes["quay"] = quay.save("v1_quay"); meshes["rail_glass"] = rail.save("v1_rail_glass"); meshes["rail_steel"] = cap.save("v1_rail_steel")
    prom = water.buffer(1000).difference(water.buffer(60)).intersection(land).difference(bld.buffer(100))
    o = Obj(); o.poly(prom.simplify(20), 6); meshes["promenade"] = o.save("v1_promenade")
    plots = land.difference(asphalt).difference(water.buffer(60))
    o = Obj(); o.poly(plots.simplify(50), 1); meshes["plots"] = o.save("v1_plots")
    podium = bld.buffer(400).difference(bld).intersection(land).difference(asphalt)
    o = Obj(); o.poly(podium.simplify(20), 4); meshes["podium"] = o.save("v1_podium")
    # C. kerbs + markings -------------------------------------------------------------------------------------------
    kerb = asphalt.simplify(15).buffer(25).difference(asphalt.simplify(15)).intersection(land)
    o = Obj(); o.poly(kerb, 14); meshes["kerb"] = o.save("v1_kerb")
    sts = P0.streets()
    raw = P0.load(os.path.join(P0.BB, "streets.geojson"))["features"]
    white, yellow = Obj(), Obj()
    nmark = [0, 0]
    for s, f in zip(sts, raw):
        p = f["properties"]
        if s["hw"] not in CAR_ROADS or len(s["pl"]) < 2:
            continue
        s["lanes"] = max(1, int(p.get("lanes") or 1)); s["oneway"] = p.get("oneway") == "yes"
        w = s["sw"] * 100.0; n = s["lanes"]; lw = w / n
        cl = LineString(s["pl"])
        specs = []
        if s["oneway"]:
            specs += [(-w / 2 + 30, "y", False), (w / 2 - 30, "w", False)] + [(-w / 2 + lw * k, "w", True) for k in range(1, n)]
        else:
            specs += [(-w / 2 + 30, "w", False), (w / 2 - 30, "w", False), (0.0, "w", n <= 2)]
            nd = max(1, n // 2); lwd = (w / 2) / nd
            specs += [(sg * lwd * k, "w", True) for k in range(1, nd) for sg in (-1, 1)]
        for off, col, dashed in specs:
            try:
                ln = cl.offset_curve(off) if abs(off) > 1 else cl
            except Exception:
                continue
            if ln.is_empty or ln.geom_type != "LineString":
                continue
            pieces = dash(ln, 300, 600) if dashed else dash(ln.segmentize(1000), 1000, 0.001)
            for pc in pieces:
                if not carriage.contains(pc.interpolate(0.5, normalized=True)):
                    continue
                (white if col == "w" else yellow).poly(pc.buffer(7.5, cap_style="flat"), 10)
                nmark[col == "y"] += 1
    meshes["mark_white"] = white.save("v1_mark_white"); meshes["mark_yellow"] = yellow.save("v1_mark_yellow")
    print("  markings: %d white, %d yellow pieces" % tuple(nmark))
    # G. site hoardings (replace the pack fences) ---------------------------------------------------------------------
    hd = Obj()
    for q in plan["sites"]:
        r = box(q["x0"], q["y0"], q["x1"], q["y1"])
        hd.wall(LineString(r.exterior.coords), 0, 240)
    meshes["hoarding"] = hd.save("v1_hoarding")
    meshes.update(prop_meshes())

    # ------------------------------------------------------------------------------------------------ dressing
    keys = plan["keys"]
    low_path = [k[1][:2] for k in keys if 20.0 <= k[0] <= 94.0 and k[1][2] < 12000.0]
    near_g = prep(unary_union([Point(p).buffer(P0.NEAR_CM) for p in low_path[::6]]))
    def near(p, f=1.0):
        return near_g.contains(Point(p)) if f == 1.0 else any(math.hypot(p[0] - q[0], p[1] - q[1]) < P0.NEAR_CM * f for q in low_path[::6])
    def ok_land(p, clear_road=True):
        pt = Point(p)
        return not ((clear_road and P_asph.contains(pt)) or P_bld.contains(pt) or P_water.contains(pt))
    D = {k: [] for k in ("prom_cafes", "median_palms", "kerb_palms", "prom_palms", "park_trees", "park_palms", "lamps", "prom_lamps", "benches",
                         "planters", "hedges", "bus_shelters", "parked_cars", "yachts", "speedboats", "abras")}
    grid = set()
    def claim(p, cell=600.0):
        k = (int(p[0] // cell), int(p[1] // cell))
        if k in grid:
            return False
        grid.add(k); return True
    bad = {"trees": 0, "lamps": 0}
    lines = [(s, LineString(s["pl"])) for s in sts if s["hw"] in CAR_ROADS and not s["bridge"]]
    oneways = [l for s, l in lines if s.get("oneway")]
    from shapely.strtree import STRtree
    tree = STRtree(oneways)
    # E. medians: midpoint between a oneway carriageway and its opposite partner, 13.5 m spacing, date palms + lamps
    for s, cl in lines:
        if not s.get("oneway") or s["hw"] not in PALM_ROADS:
            continue
        for k, (p, dr) in enumerate(P0.samples(s["pl"], 1350.0, 600.0)):
            best = None
            for j in tree.query(Point(p).buffer(4500)):
                other = oneways[j]
                if other is cl:
                    continue
                q = other.interpolate(other.project(Point(p))).coords[0]
                d = math.hypot(q[0] - p[0], q[1] - p[1])
                if 700 < d < 4500 and (best is None or d < best[0]):
                    best = (d, q)
            if not best:
                continue
            m = [(p[0] + best[1][0]) / 2, (p[1] + best[1][1]) / 2]
            if not ok_land(m):
                bad["trees"] += 1; continue
            if not claim(m, 500):
                continue
            D["median_palms"].append([round(m[0]), round(m[1]), round(rnd.uniform(0, 360), 1), round(rnd.uniform(0.95, 1.08), 3), k % 2])
            if k % 3 == 1 and near(m, 1.3):
                D["lamps"].append([round(m[0]), round(m[1]), round(P0.yaw(dr) + 90, 1), 1.0])
    # kerb rows: 2 m behind the kerb, 13.5 m, both sides of two-way roads, the outer (right) side of oneways
    for s, cl in lines:
        if s["hw"] not in PALM_ROADS | {"residential"}:
            continue
        off = s["sw"] * 50.0 + 200.0
        for side in ((1,) if s.get("oneway") else (-1, 1)):
            for k, (p, dr) in enumerate(P0.samples(s["pl"], 1350.0, 300.0)):
                q = [p[0] - dr[1] * off * side, p[1] + dr[0] * off * side]
                if not ok_land(q):
                    bad["trees"] += 1; continue
                if not claim(q):
                    continue
                D["kerb_palms"].append([round(q[0]), round(q[1]), round(rnd.uniform(0, 360), 1), round(rnd.uniform(0.95, 1.08), 3), k % 2])
            if s["hw"] in PALM_ROADS:
                for k, (p, dr) in enumerate(P0.samples(s["pl"], 3000.0, 1000.0)):
                    q = [p[0] - dr[1] * (off - 120) * side, p[1] + dr[0] * (off - 120) * side]
                    if near(q, 1.3) and ok_land(q):
                        D["lamps"].append([round(q[0]), round(q[1]), round(P0.yaw(dr) + 90, 1), 1.0])
                    elif near(q, 1.3):
                        bad["lamps"] += 1
    # promenade: palm row 8 m back from the quay (12 m), lamps (25 m), benches + planters (30 m)
    pv = prep(prom.buffer(-150))
    for l in edge:
        for off, step, key in ((650.0, 1200.0, "prom_palms"), (320.0, 2500.0, "prom_lamps"), (450.0, 3000.0, "benches"), (750.0, 3000.0, "planters"),
                               (830.0, 1400.0, "prom_cafes")):          # 29 Sep (Kendall): cafe sets + umbrellas on the promenade
            for side in (-1, 1):
                try:
                    ln = LineString(l.coords).offset_curve(side * off)
                except Exception:
                    continue
                if ln.is_empty or ln.geom_type != "LineString" or ln.length < step:
                    continue
                d = step * (0.25 if key == "benches" else 0.5 if key == "planters" else 0.0)
                while d < ln.length:
                    a = ln.interpolate(d); b = ln.interpolate(min(ln.length, d + 50))
                    p = (a.x, a.y); d += step
                    if not pv.contains(a) or not ok_land(p) or water.distance(a) < off - 150:
                        continue
                    yw = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
                    if key in ("benches", "planters", "prom_lamps", "prom_cafes") and not near(p, 1.5):
                        continue
                    D[key].append([round(p[0]), round(p[1]), round(yw, 1), 1.0, len(D[key]) % 2])
    # parks: clusters only in ctx_grass (>1,500 m2), 9 m hex grid, jittered
    for pg in (grass.geoms if hasattr(grass, "geoms") else [grass]):
        if pg.area < 1500e4:
            continue
        inner = prep(pg.buffer(-250)); x0, y0, x1, y1 = pg.bounds
        y, row = y0, 0
        while y < y1:
            x = x0 + (450 if row % 2 else 0)
            while x < x1:
                q = [x + rnd.uniform(-150, 150), y + rnd.uniform(-150, 150)]
                if inner.contains(Point(q)) and ok_land(q) and rnd.random() < 0.55:
                    D["park_palms" if rnd.random() < 0.3 else "park_trees"].append([round(q[0]), round(q[1]), round(rnd.uniform(0, 360), 1), round(rnd.uniform(0.85, 1.15), 3), rnd.randrange(3)])
                x += 900
            y += 780; row += 1
    fu = P0.load(os.path.join(P0.BB, "furniture_ue.json"))
    nb = 0
    for r in fu.get("bus_shelters", []):
        if near(r[:2]) and ok_land(r[:2]):
            D["bus_shelters"].append([r[0], r[1], r[2] if len(r) > 2 else 0.0, 1.0])
        else:
            nb += 1
    # D. parked cars: bays inside ctx_parking only (2.6 x 5.5 m, rows along the lot's long axis, 6 m aisles)
    npk_bad = 0
    for pg in (parking.geoms if hasattr(parking, "geoms") else [parking]):
        if pg.area < 200e4:
            continue
        mrr = pg.minimum_rotated_rectangle; c = list(mrr.exterior.coords)
        e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1]); e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
        ax_ = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
        ang = math.degrees(math.atan2(ax_[1], ax_[0]))
        cx, cy = mrr.centroid.x, mrr.centroid.y
        L = max(math.hypot(*e1), math.hypot(*e2)); Wd = min(math.hypot(*e1), math.hypot(*e2))
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        v = -Wd / 2 + 275
        rowi = 0
        while v < Wd / 2:
            u = -L / 2 + 130
            while u < L / 2:
                x, y = cx + u * ca - v * sa, cy + u * sa + v * ca
                car = rotate(box(-95, -235, 95, 235), ang, origin=(0, 0))
                car = translate(car, x, y)
                if P_park.contains(car) and not P_bld.contains(Point(x, y)):
                    if rnd.random() < 0.72:
                        D["parked_cars"].append([round(x), round(y), round(ang + 90 + (180 if rowi % 2 else 0), 1), 1.0, rnd.randrange(8)])
                else:
                    npk_bad += 1
                u += 260
            v += 550 if rowi % 2 == 0 else 1150
            rowi += 1
    vlog("parked_cars", len(D["parked_cars"]), npk_bad)
    vlog("trees+palms", sum(len(D[k]) for k in ("median_palms", "kerb_palms", "prom_palms", "park_trees", "park_palms")), bad["trees"])
    vlog("lamps", len(D["lamps"]) + len(D["prom_lamps"]), bad["lamps"])
    # caps for 8 GB VRAM: keep what is near the low shots first
    for key, cap in (("kerb_palms", 5000), ("median_palms", 2500), ("park_trees", 2000), ("park_palms", 800), ("lamps", 1500), ("parked_cars", 900)):
        if len(D[key]) > cap:
            nr = [r for r in D[key] if near(r[:2])]; far = [r for r in D[key] if not near(r[:2])]
            rnd.shuffle(far); D[key] = (nr + far)[:cap]

    # B. boats ---------------------------------------------------------------------------------------------------------
    BOAT = {"yachts": (2800.0, 0.27), "speedboats": (850.0, 0.31), "abras": (1000.0, 0.28)}
    def hull_ok(x, y, yaw, L, beam_f):
        h = translate(rotate(box(-L / 2, -L * beam_f / 2, L / 2, L * beam_f / 2), yaw, origin=(0, 0)), x, y)
        return water_in5.contains(h)
    canal_line = plan["canal_cm"]
    moored_bad = 0
    # moored: along the quay, near the canal glide first; abra station = 3 abras side by side
    cand = []
    for l in edge:
        ls = LineString(l.coords)
        d = 0.0
        while d < ls.length:
            a = ls.interpolate(d); b = ls.interpolate(min(ls.length, d + 100))
            cand.append((a.x, a.y, math.degrees(math.atan2(b.y - a.y, b.x - a.x)), l))
            d += 700.0
    cand.sort(key=lambda c: min(math.hypot(c[0] - p[0], c[1] - p[1]) for p in low_path[::10]))
    plan_mix = ["abras"] * 3 + ["yachts", "speedboats", "yachts", "yachts", "speedboats", "yachts", "abras", "speedboats", "yachts", "yachts", "speedboats", "yachts", "abras"]
    taken = []
    for kind in plan_mix:
        L0, bf = BOAT[kind]
        js = rnd.uniform(0.75, 1.25) if kind == "yachts" else rnd.uniform(0.95, 1.05)
        L = L0 * js
        placed = False
        for (x, y, yw, l) in cand:
            if any(math.hypot(x - t[0], y - t[1]) < (L + t[2]) / 2 + 300 for t in taken):
                continue
            for s in (1, -1):
                nx, ny = -math.sin(math.radians(yw)) * s, math.cos(math.radians(yw)) * s
                push = 500 + L * bf / 2 + 80
                bx_, by_ = x + nx * push, y + ny * push
                if hull_ok(bx_, by_, yw, L, bf):
                    D[kind].append([round(bx_), round(by_), round(yw + rnd.choice((0, 180)), 1), round(js, 3), rnd.randrange(3)])
                    taken.append((bx_, by_, L)); placed = True; break
                moored_bad += 1
            if placed:
                break
    nm = sum(len(D[k]) for k in BOAT)
    # moving: 10 boats along the canal centreline lanes; every sample inside water, >= 5 m from the quay
    movers = []
    mv_bad = 0
    cl = LineString(canal_line)
    kinds = ["abras", "speedboats", "yachts", "abras", "speedboats", "abras", "yachts", "speedboats", "abras", "speedboats", "abras", "yachts"]
    for i, kind in enumerate(kinds):
        L0, bf = BOAT[kind]; L = L0
        for lane in ((1800.0, 2600.0, 1400.0, 2200.0)[i % 4], 1600.0):
            # the canal's inner offset ring at `lane` cm from the quay: a closed lane along each bank (PCA centreline
            # left the water at every bend: 28,691 rejected samples in the first pass)
            rings = [g for g in (lambda w: w.geoms if hasattr(w, "geoms") else [w])(water.buffer(-lane)) if isinstance(g, Polygon)]
            if not rings:
                continue
            path = LineString(max(rings, key=lambda g: g.area).exterior.coords)
            if path.is_empty or path.geom_type != "LineString":
                continue
            pts = [path.interpolate(d).coords[0] for d in range(0, int(path.length), 500)]
            okm = [hull_ok(pts[k][0], pts[k][1], math.degrees(math.atan2(pts[min(len(pts) - 1, k + 1)][1] - pts[k][1], pts[min(len(pts) - 1, k + 1)][0] - pts[k][0])), L, bf) for k in range(len(pts) - 1)]
            runs, cur = [], []
            for k, g in enumerate(okm):
                if g:
                    cur.append(pts[k])
                else:
                    if len(cur) > 1: runs.append(cur)
                    cur = []
            if len(cur) > 1: runs.append(cur)
            mv_bad += okm.count(False)
            runs = [r for r in runs if len(r) * 5.0 >= 350]
            if not runs:
                continue
            run = max(runs, key=len)
            if i % 2:
                run = run[::-1]
            spd = {"abras": 450.0, "speedboats": 1100.0, "yachts": 600.0}[kind] * rnd.uniform(0.9, 1.1)
            Lr = (len(run) - 1) * 500.0
            # centred so the boat is mid-run at t = 66 s (canal glide), staggered along the run
            gk = min(plan["keys"], key=lambda k: abs(k[0] - 66.0))[1]
            j0 = min(range(len(run)), key=lambda j: math.hypot(run[j][0] - gk[0], run[j][1] - gk[1]))
            start = j0 * 500.0 + (i - 5) * 5000.0 - spd * 66.0          # in the canal-glide view at t = 66 s, staggered 50 m
            movers.append({"kind": kind, "variant": i % 3, "path": [[round(p[0]), round(p[1])] for p in run], "lane_cm": 0.0, "start_cm": start,
                           "speed_cms": spd, "len_cm": L, "hide_outside": True, "wake": True})
            break
        if len([m for m in movers if m["kind"] in BOAT]) >= 11:
            break
    vlog("boats_moored", nm, moored_bad)
    vlog("boats_moving", len(movers), mv_bad)
    # D. moving cars: lane centrelines (right-hand traffic), chained segments, validated against the carriageway
    car_bad, car_ok = 0, 0
    segs = [(s, LineString(s["pl"])) for s, _ in lines if s["hw"] in CAR_ROADS and near(s["pl"][len(s["pl"]) // 2], 1.2)]
    def chain(s0):
        pl = list(s0["pl"]); used = {id(s0)}
        for _ in range(30):
            nxt = None
            for s, _ in segs:
                if id(s) in used or not s.get("oneway") == s0.get("oneway"):
                    continue
                if math.dist(pl[-1], s["pl"][0]) < 500:
                    h0 = math.atan2(pl[-1][1] - pl[-2][1], pl[-1][0] - pl[-2][0]); h1 = math.atan2(s["pl"][1][1] - s["pl"][0][1], s["pl"][1][0] - s["pl"][0][0])
                    dh = abs((h1 - h0 + math.pi) % (2 * math.pi) - math.pi)
                    if dh < 0.5 and (nxt is None or dh < nxt[0]):
                        nxt = (dh, s)
            if not nxt:
                break
            used.add(id(nxt[1])); pl += nxt[1]["pl"][1:]
            if P0.polyline_len(pl) > 180000:
                break
        return pl
    segs.sort(key=lambda t: -t[1].length)
    ncar = 0
    for s, _ in segs:
        if ncar >= 36:
            break
        pl = chain(s)
        if P0.polyline_len(pl) < 25000:
            continue
        w = s["sw"] * 100.0; n = s.get("lanes", 1); lw = w / n
        dirs = [(pl, [(-w / 2 + lw * (k + 0.5)) for k in range(n)])] if s.get("oneway") else \
               [(pl, [lw * (k + 0.5) for k in range(max(1, n // 2))]), (pl[::-1], [lw * (k + 0.5) for k in range(max(1, n // 2))])]
        for base, offs in dirs:
            for li, off in enumerate(offs):
                try:
                    ln = LineString(base).offset_curve(off)
                except Exception:
                    continue
                if ln.is_empty or ln.geom_type != "LineString":
                    continue
                # offset_curve keeps the direction for positive offsets in shapely 2; check it
                if Point(ln.coords[0]).distance(Point(base[0])) > Point(ln.coords[-1]).distance(Point(base[0])):
                    ln = LineString(ln.coords[::-1])
                pts = [ln.interpolate(d).coords[0] for d in range(0, int(ln.length), 400)]
                good = [P_asph.contains(Point(p)) for p in pts]
                run, cur = [], []
                for p, g in zip(pts, good):
                    if g:
                        cur.append(p)
                    else:
                        if len(cur) > len(run): run = cur
                        cur = []
                if len(cur) > len(run): run = cur
                car_bad += good.count(False)
                if len(run) * 4.0 < 150:
                    continue
                spd = rnd.uniform(1100.0, 1500.0) if li == len(offs) - 1 else rnd.uniform(1400.0, 1800.0)
                for c in range(2):                                     # two cars per lane, >= 35 m apart
                    movers.append({"kind": "car", "variant": rnd.randrange(8), "path": [[round(p[0]), round(p[1])] for p in run], "lane_cm": 0.0,
                                   "start_cm": (len(run) * 400.0) * (0.15 + 0.4 * c) - spd * 36.0, "speed_cms": spd, "hide_outside": True})
                    ncar += 1; car_ok += 1
    vlog("cars_moving", car_ok, car_bad)
    # camera: per-rendered-frame clearance, 25 m around every footprint + 25 m over its roof -----------------------
    keys = clearance(canal_low(plan["keys"], water), fps, plan["fps"])
    print("  dressing: " + ", ".join("%s %d" % (k, len(v)) for k, v in D.items()))
    # 29 Sep (Kendall "too much time on the street"): one street shot, aerials get the time; v0's list kept for reference
    plan["edit_street_heavy"] = plan.get("edit")
    plan["edit"] = [[0.5, 9], [80.5, 6], [94.5, 2], [101.5, 9]]   # 29 Sep (Kendall): aerials only - no canal glide, no street
    plan.update(keys=keys, dress=D, movers=movers, context=ctx, v1_meshes={k: v for k, v in meshes.items() if v}, lift_cm=LIFT_CM, water_z_cm=WATER_Z,
                sites=plan["sites"])
    json.dump(plan, open(os.path.join(OUT, "bb_v1_plan.json"), "w", encoding="utf-8"), separators=(",", ":"))
    json.dump(VAL, open(os.path.join(OUT, "bb_v1_validation.json"), "w", encoding="utf-8"), indent=1)
    print("bb_v1_prep: -> %s" % OUT)


def clearance(keys, fps, rate):
    """camera keys every 0.2 s; sample every rendered frame (linear between keys), lift keys where any frame is within
    25 m of a footprint below roof + 25 m, feathered over +-1.6 s; repeat until clean"""
    from shapely.strtree import STRtree
    polys = [g.buffer(2500) for g, _ in fps]; hs = [h for _, h in fps]
    tree = STRtree(polys)
    core = [g for g, _ in fps]
    GLIDES = ((29.0, 49.0), (56.5, 77.0))                  # street/canal glides: 5 m footprint rule, never lifted
    locked = lambda t: any(a <= t <= b for a, b in GLIDES)
    def need_at(p, t=None):
        # 25 m around every footprint for aerials/transits; a street-level glide (< 60 m up) flies down the road
        # canyon, where 25 m sideways is impossible, so there only the true footprint + 5 m counts (v1 test 1: the
        # boulevard glide was lifted over the towers into a top-down view)
        z = 0.0
        low = p[2] < 6000.0 or (t is not None and locked(t))
        for j in tree.query(Point(p[0], p[1])):
            g = core[j].buffer(500) if low else polys[j]
            if hs[j] + 2500.0 > p[2] and g.contains(Point(p[0], p[1])):
                z = max(z, hs[j] + 2500.0)
        return z
    # street-level keys inside a footprint + 6 m are nudged sideways out of it (not lifted: a lift would turn the
    # boulevard glide into a top-down view)
    nudged = 0
    for k in keys:
        p = k[1]
        if p[2] >= 6000.0:
            continue
        for _ in range(4):
            hit = [j for j in tree.query(Point(p[0], p[1])) if hs[j] + 2500.0 > p[2] and core[j].buffer(600).contains(Point(p[0], p[1]))]
            if not hit:
                break
            g = core[hit[0]].buffer(700)
            q = g.exterior.interpolate(g.exterior.project(Point(p[0], p[1])))
            p[0], p[1] = q.x, q.y; nudged += 1
    print("  clearance: %d low keys nudged sideways out of footprints" % nudged)
    for it in range(12):
        req = [0.0] * len(keys); bad = 0
        for k in range(len(keys) - 1):
            t0, p0, _ = keys[k]; t1, p1, _ = keys[k + 1]
            nf = max(1, int(round((t1 - t0) * rate)))
            for f in range(nf + 1):
                u = f / nf
                p = [p0[i] + (p1[i] - p0[i]) * u for i in range(3)]
                z = need_at(p, t0 + (t1 - t0) * u)
                if z > 0:
                    bad += 1; req[k] = max(req[k], z); req[k + 1] = max(req[k + 1], z)
        print("  clearance pass %d: %d frames inside a 25 m envelope" % (it, bad))
        if bad == 0:
            VAL["camera_frames_clipping"] = 0
            break
        for j in range(len(keys)):
            # flat top over +-0.6 s, cosine feather to +-2 s: frames between keys never sag back into the envelope
            need = max(req[k] * (1.0 if abs(k - j) <= 3 else 0.5 + 0.5 * math.cos(math.pi * (abs(k - j) - 3) / 7.0)) for k in range(max(0, j - 10), min(len(keys), j + 11)))
            if need > keys[j][1][2] and not locked(keys[j][0]):
                keys[j][1][2] = need + 100.0
        VAL["camera_frames_clipping"] = bad
    return keys


fps = []
if __name__ == "__main__":
    _m = main
    def main_wrap():
        global fps
        blds = P0.buildings()
        for b in blds:
            try:
                g = Polygon([(v[0], v[1]) for v in b["ring"]]).buffer(0)
                if g.area > 0:
                    fps.append((g, b["h"]))
            except Exception:
                pass
        _m()
    main_wrap()
