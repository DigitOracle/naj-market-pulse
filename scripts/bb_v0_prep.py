"""Business Bay v0 fly-through, step 1 (plain CPython, no Unreal): everything the Unreal scripts place or fly, as data.

Writes data/ce/_datasmith/bb_v0/:
  ctx_<layer>.obj    street layers of data/ce/businessbay/context_ue.json (asphalt, pavement, parking, grass, pitch,
                     pool, construction) as OBJ in the UE frame (cm; X = easting - 328289, Y = 2784598 - northing).
                     Sand and water layers are skipped (sand plane + the city water meshes cover them).
  bb_v0_plan.json    district extents (expected Datasmith bounds, for the import check), canal centreline, the boulevard,
                     the Burj, construction sites, every dressing point (palms at 13.5 m along the main roads, verge
                     hedges/bougainvillea, greenery_ue trees/palms, furniture_ue benches/bins/shelters/bollards, lamps,
                     parked cars, boats), the movers (cars on the boulevard, boats on the canal) and the camera keys.
Camera: ONE continuous 94 s render path (25 fps, 9:16, look-at at frame centre = inside the 1080 x 1420 safe zone);
the edit (bb_v0_encode.py) cuts it on the "Five Armies" bar grid (2.14 s), dropping the fast transits (camera study 28 Sep):
   0-16  HIGH establishing orbit of the whole district, 48 deg at 3 deg/s, sun behind camera, ease-in from rest
  16-24  descend (clearance-aware transit: climb/hold over towers, drop late)          [cut away]
  24-40  M06 boulevard glide at 12 m, 12 m/s, past palms, lamps, parked + moving cars
  40-46  hop to the canal                                                              [cut away]
  46-62  M07 canal glide at 22 m, 14 m/s, past moored and moving boats
  62-65  transit                                                                       [cut away]
  65-75  construction-site orbit, 30 deg at 3 deg/s (cranes, fences, barriers, containers)
  75-82  transit to the pull-back start                                                [cut away]
  82-90  slow M03 pull-back; the Burj Khalifa skyline stands behind the canal side at Marasi Drive (frame centre)
  90-94  steady closing frame (0.3 m/s drift)
EDIT and TEASER below are render-time windows (s). Keys every 0.2 s, Gaussian-smoothed (sigma 0.6 s); first 1 s and
last 4 s pinned.
Dressing near the low shots only (cars, furniture, lamps, boats within ~700 m of the low path) keeps VRAM modest.
Usage:  python scripts/bb_v0_prep.py
"""
import json, math, os, random, sys

from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BB = os.path.join(ROOT, "data", "ce", "businessbay")
OUT = os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v0")
OFF_E, OFF_N = 328289.0, 2784598.0
# ---- the district, as config (next district = a new entry, not a rewrite; Kendall 28 Sep) ----
DISTRICT = {"slug": "businessbay", "lod3": "businessbay_lod3.udatasmith", "backdrop": "burjkhalifa_lod3.udatasmith",
            "landmark_lonlat": (55.274225, 25.197197), "landmark_h_m": 828.0, "boulevard": "Marasi", "surround_km": 3.0,
            "sun_elev_deg": 33.0, "sky_light": 3.0, "fog_density": 0.012, "music": "Five Armies.mp3", "bar_s": 2.14, "fps": 25}
FPS, TOTAL_S = 25, 116.0
FOCAL_MM, SENSOR_W = 20.0, 24.0
BURJ_LONLAT = (55.274225, 25.197197)
BURJ_H_M = 828.0
CTX_LAYERS = ["construction", "grass", "pitch", "parking", "pavement", "asphalt", "pool"]
PALM_ROADS = {"primary", "secondary", "trunk", "tertiary"}
CAR_ROADS = {"primary", "secondary", "tertiary", "residential"}
NEAR_CM = 70000.0                    # dressing radius around the low shots
CAPS = {"road_palms": 6000, "verge": 3000, "g_palms": 5000, "g_trees": 2000, "lamps": 1500, "parked": 700, "furniture": 1500}
BAR = 2.14                          # "Five Armies", 112 BPM
# the main edit: opener 7 bars, then 2-bar shots, finale 5 bars (pull-back into the steady frame) = 28 bars = 59.9 s
EDIT = [[0.5, 8], [21.0, 2], [29.0, 2], [33.6, 2], [38.2, 2], [42.8, 2], [49.5, 2], [56.0, 2], [60.8, 2], [65.6, 2], [70.4, 2], [80.5, 2], [85.2, 2], [89.6, 2], [94.5, 2], [101.8, 6]]   # [start s, bars] = 42 bars, 89.9 s
TEASER = [[0.5, 7.5], [22.5, 26.5], [57.0, 61.0], [111.0, 116.0]]   # orbit 7 / descent 4 + canal 4 / steady high whole-district 5   # opens on the orbit start, high and wide (follows the ep08 night-gold opener)          # ep08 teaser, 20 s: orbit 7 s, canal + boats 8 s, steady 5 s
tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
rnd = random.Random(11)


def ue(e, n, z_m=0.0):
    return [(e - OFF_E) * 100.0, (OFF_N - n) * 100.0, z_m * 100.0]


def load(p):
    return json.load(open(p, encoding="utf-8"))


def write_obj(path, V, T, name):
    with open(path, "w", encoding="utf-8") as f:
        f.write("o %s\n" % name)
        for k in range(0, len(V), 3):
            f.write("v %.1f %.1f %.1f\n" % (V[k], V[k + 1], V[k + 2]))
        for k in range(0, len(T), 3):
            f.write("f %d %d %d\n" % (T[k] + 1, T[k + 1] + 1, T[k + 2] + 1))
    xs, ys = V[0::3], V[1::3]
    return {"verts": len(V) // 3, "tris": len(T) // 3, "bounds_cm": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]}


def context_layers():
    d = load(os.path.join(BB, "context_ue.json"))
    meta, sites = {}, []
    for L in d["layers"]:
        if L["name"] not in CTX_LAYERS or not L.get("tris"):
            continue
        m = write_obj(os.path.join(OUT, "ctx_%s.obj" % L["name"]), L["verts"], L["tris"], "ctx_" + L["name"])
        m.update(rgb=L.get("rgb"), roughness=L.get("roughness"), specular=L.get("specular"), z_cm=L.get("z_cm"))
        meta[L["name"]] = m
        print("  ctx_%-12s %6d tris" % (L["name"], m["tris"]))
        if L["name"] == "construction":
            sites = construction_clusters(L["verts"], L["tris"])
    return meta, sites


def construction_clusters(V, T):
    """connected triangle groups of the OSM construction layer -> site rectangles (UE cm)"""
    n = len(T) // 3
    parent = list(range(len(V) // 3))
    def f(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for k in range(n):
        a, b, c = T[3 * k:3 * k + 3]
        for q in (b, c):
            ra, rq = f(a), f(q)
            if ra != rq:
                parent[rq] = ra
    groups = {}
    for k in range(n):
        a, b, c = T[3 * k:3 * k + 3]
        P = [(V[3 * i], V[3 * i + 1]) for i in (a, b, c)]
        area = abs((P[1][0] - P[0][0]) * (P[2][1] - P[0][1]) - (P[2][0] - P[0][0]) * (P[1][1] - P[0][1])) / 2.0
        g = groups.setdefault(f(a), {"pts": [], "area": 0.0})
        g["pts"] += P; g["area"] += area
    out = []
    for g in groups.values():
        if g["area"] < 1500.0 * 1e4:                    # < 1,500 m2: not a tower site
            continue
        xs = [p[0] for p in g["pts"]]; ys = [p[1] for p in g["pts"]]
        out.append({"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys), "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2,
                    "area_m2": round(g["area"] / 1e4), "src": "osm_construction"})
    return out


def buildings():
    feats = load(os.path.join(BB, "buildings.geojson"))["features"]
    out = []
    for i, f in enumerate(feats):
        g = f.get("geometry") or {}
        rings = g.get("coordinates") or []
        rings = [r for poly in rings for r in poly[:1]] if g.get("type") == "MultiPolygon" else rings[:1]
        pts = [tr.transform(x, y) for r in rings for x, y in (p[:2] for p in r)]
        if not pts:
            continue
        uu = [ue(e, n) for e, n in pts]
        xs, ys = [p[0] for p in uu], [p[1] for p in uu]
        out.append({"i": i, "x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys), "cx": sum(xs) / len(xs), "cy": sum(ys) / len(ys),
                    "ring": uu, "h": float(f["properties"].get("bHeight") or 12.0) * 100.0, "status": f["properties"].get("status") or "existing"})
    return out


def pca(pts):
    n = len(pts); mx = sum(p[0] for p in pts) / n; my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts); syy = sum((p[1] - my) ** 2 for p in pts); sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return (mx, my), (math.cos(ang), math.sin(ang))


def poly_area(r):
    return abs(sum(r[k][0] * r[k + 1][1] - r[k + 1][0] * r[k][1] for k in range(len(r) - 1))) / 2.0


def canal_centreline(bx):
    w = load(os.path.join(BB, "water.json"))
    best = None
    for poly in w["polys"]:
        r = [ue(p[0], -p[1])[:2] for p in poly]            # water.json: (easting, -northing)
        if len(r) < 4:
            continue
        cx = sum(p[0] for p in r) / len(r); cy = sum(p[1] for p in r) / len(r)
        if not (bx[0] - 20000 <= cx <= bx[2] + 20000 and bx[1] - 20000 <= cy <= bx[3] + 20000):
            continue
        a = poly_area(r)
        if best is None or a > best[0]:
            best = (a, r)
    if best is None:
        return [], []
    r = best[1]
    (mx, my), ax = pca(r)
    nx, ny = -ax[1], ax[0]
    proj = [((p[0] - mx) * ax[0] + (p[1] - my) * ax[1], (p[0] - mx) * nx + (p[1] - my) * ny) for p in r]
    s0, s1 = min(q[0] for q in proj), max(q[0] for q in proj)
    step, line, widths, k = 5000.0, [], [], 0
    while s0 + (k + 1) * step <= s1:
        lo, hi = s0 + k * step, s0 + (k + 1) * step
        ts = [q[1] for q in proj if lo <= q[0] < hi]
        if len(ts) >= 2:
            s, t = (lo + hi) / 2.0, (min(ts) + max(ts)) / 2.0
            line.append([mx + s * ax[0] + t * nx, my + s * ax[1] + t * ny]); widths.append(max(ts) - min(ts))
        k += 1
    sm = []
    for j in range(len(line)):
        a = line[max(0, j - 2):j + 3]
        sm.append([sum(p[0] for p in a) / len(a), sum(p[1] for p in a) / len(a)])
    return sm, widths


def streets():
    s = load(os.path.join(BB, "streets.geojson"))["features"]
    out = []
    for f in s:
        p = f["properties"]
        pl = [ue(*tr.transform(x, y))[:2] for x, y in f["geometry"]["coordinates"]]
        if len(pl) >= 2:
            out.append({"pl": pl, "hw": p.get("hw"), "nm": p.get("nm") or "", "sw": float(p.get("sw") or 7.0), "bridge": bool(p.get("bridge")),
                        "oneway": p.get("oneway") == "yes", "len": polyline_len(pl)})
    return out


def polyline_len(pl):
    return sum(math.hypot(pl[k + 1][0] - pl[k][0], pl[k + 1][1] - pl[k][1]) for k in range(len(pl) - 1))


def along(pl, d):
    for k in range(len(pl) - 1):
        seg = math.hypot(pl[k + 1][0] - pl[k][0], pl[k + 1][1] - pl[k][1])
        if d <= seg or k == len(pl) - 2:
            u = max(0.0, min(1.0, d / seg)) if seg > 0 else 0.0
            dx, dy = (pl[k + 1][0] - pl[k][0]) / (seg or 1), (pl[k + 1][1] - pl[k][1]) / (seg or 1)
            return [pl[k][0] + u * (pl[k + 1][0] - pl[k][0]), pl[k][1] + u * (pl[k + 1][1] - pl[k][1])], (dx, dy)
        d -= seg
    return list(pl[-1]), (1.0, 0.0)


def samples(pl, step, start=0.0):
    L = polyline_len(pl); d = start
    while d <= L:
        p, dr = along(pl, d)
        yield p, dr
        d += step


def yaw(dr):
    return math.degrees(math.atan2(dr[1], dr[0]))


def ease(u):
    u = max(0.0, min(1.0, u)); return u * u * (3 - 2 * u)


def lerp(a, b, u):
    return [a[i] + (b[i] - a[i]) * u for i in range(len(a))]


def chain_road(sts, name):
    """one ordered polyline for a named road: the longest chain of its segments (end-to-end joins within 15 m)"""
    segs = [s["pl"] for s in sts if name.lower() in s["nm"].lower() and not s["bridge"]]
    if not segs:
        return []
    best = []
    for start in segs:
        pl = list(start); used = {id(start)}
        grow = True
        while grow:
            grow = False
            for s in segs:
                if id(s) in used:
                    continue
                if math.dist(pl[-1], s[0]) < 1500:
                    pl += s[1:]; used.add(id(s)); grow = True
                elif math.dist(pl[-1], s[-1]) < 1500:
                    pl += s[::-1][1:]; used.add(id(s)); grow = True
        if polyline_len(pl) > polyline_len(best):
            best = pl
    return best


def dist_to_pl(p, pl):
    best = 1e18
    for k in range(len(pl) - 1):
        ax, ay = pl[k]; bx, by = pl[k + 1]
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy or 1.0
        u = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
        best = min(best, math.hypot(p[0] - ax - u * dx, p[1] - ay - u * dy))
    return best


def plan():
    blds = buildings()
    x0 = min(b["x0"] for b in blds); y0 = min(b["y0"] for b in blds); x1 = max(b["x1"] for b in blds); y1 = max(b["y1"] for b in blds)
    tall = [b for b in blds if b["h"] >= 6000.0] or blds
    wsum = sum(b["h"] for b in tall)
    C = [sum(b["cx"] * b["h"] for b in tall) / wsum, sum(b["cy"] * b["h"] for b in tall) / wsum]
    reach = sorted(math.hypot(b["cx"] - C[0], b["cy"] - C[1]) for b in tall)[int(0.9 * (len(tall) - 1))]
    Htop = max(b["h"] for b in blds)
    burj = ue(*tr.transform(*BURJ_LONLAT))
    canal, cwidth = canal_centreline((x0, y0, x1, y1))
    sts = streets()
    blvd = chain_road(sts, "Marasi")
    if polyline_len(blvd) < 60000:                     # fallback: the longest named primary/secondary road
        named = sorted({s["nm"] for s in sts if s["nm"] and s["hw"] in ("primary", "secondary")}, key=lambda n: -polyline_len(chain_road(sts, n)))
        blvd = chain_road(sts, named[0]) if named else []
    print("  district %.1f x %.1f km, %d buildings, tallest %.0f m, reach(p90) %.0f m; canal %.0f m; boulevard %.0f m" %
          ((x1 - x0) / 1e5, (y1 - y0) / 1e5, len(blds), Htop / 100, reach / 100, polyline_len(canal) / 100 if canal else 0, polyline_len(blvd) / 100))

    def clearance(a, b):
        """highest building within 120 m of the straight line a->b, plus 30 m"""
        seg = [a[:2], b[:2]]
        hs = [q["h"] for q in blds if dist_to_pl([q["cx"], q["cy"]], seg) < 12000.0 + max(q["x1"] - q["x0"], q["y1"] - q["y0"]) / 2]
        return (max(hs) if hs else 0.0) + 3000.0

    def transit(a, b, u, zc):
        xy = lerp(a[:2], b[:2], ease(u))
        if zc > max(a[2], b[2]):
            if u < 0.3:
                z = a[2] + (zc - a[2]) * ease(u / 0.3)
            elif u > 0.7:
                z = zc + (b[2] - zc) * ease((u - 0.7) / 0.3)
            else:
                z = zc
        else:
            z = a[2] + (b[2] - a[2]) * ease(u)
        return xy + [z]

    half = math.atan(SENSOR_W / 2.0 / FOCAL_MM)
    PITCH = math.radians(38.0)
    D = max(reach / (math.tan(half) * 0.95), 90000.0) * 0.9
    R_orb, Z_orb = D * math.cos(PITCH), D * math.sin(PITCH) + 5000.0
    look_C = [C[0], C[1], 6000.0]
    th0, th1 = math.radians(140.0), math.radians(188.0)   # 48 deg in 16 s: 3 deg/s (grammar 2-4 deg/s)
    orb = lambda th, z: [C[0] + math.cos(th) * R_orb, C[1] + math.sin(th) * R_orb, z]
    W = []

    def seg(t0, t1, fpos, flook):
        n = max(2, int((t1 - t0) * 5))
        for k in range(1 if W else 0, n + 1):
            u = k / float(n)
            W.append((t0 + (t1 - t0) * u, fpos(u), flook(u)))

    # A. 0-16 s high establishing orbit; ease-in from rest (u^2 for the first third), a 12 % descent over the arc
    def ua(u):
        return 1.5 * u * u if u < 1 / 3.0 else (u - 1 / 6.0) * 1.0 / (5 / 6.0) if u < 1 else 1.0
    seg(0.0, 20.0, lambda u: orb(th0 + (th1 - th0) * min(1.0, ua(u)), Z_orb * (1.0 - 0.12 * u)), lambda u: look_C)
    # B/C. boulevard: a 360 m stretch of the boulevard from ~30 % of its length, direction chosen towards the canal
    Lb = polyline_len(blvd)
    b_len = min(26400.0, Lb * 0.5)            # 22 s at 12 m/s
    from shapely.geometry import Polygon as _P0, Point as _Pt0
    fps_ = []
    for q in blds:
        try:
            fps_.append(_P0([(v[0], v[1]) for v in q["ring"]]).buffer(800.0))
        except Exception:
            pass
    def blocked(s0):
        n = 0
        for d in range(0, int(b_len) + 1, 2000):
            p, _ = along(blvd, s0 + d); pt = _Pt0(p[0], p[1])
            n += any(g.contains(pt) for g in fps_ if g.bounds[0] <= p[0] <= g.bounds[2] and g.bounds[1] <= p[1] <= g.bounds[3])
        return n
    cands = [(blocked(s0), abs(s0 - Lb * 0.3), s0) for s0 in range(0, int(max(1.0, Lb - b_len)), 5000)]
    b_s0 = float(min(cands)[2]) if cands else 0.0                         # the clearest stretch (no footprint over the road)
    print("  boulevard stretch from %.0f m, %d blocked samples" % (b_s0 / 100, min(cands)[0] if cands else -1))
    ALT_B = 1200.0
    b0, bd0 = along(blvd, b_s0)
    bstart = [b0[0], b0[1], ALT_B]
    pA = W[-1][1]
    zc = clearance(pA, bstart)
    b_look0, _ = along(blvd, b_s0 + 8000.0)
    seg(20.0, 27.0, lambda u: transit(pA, bstart, u, zc), lambda u: lerp(look_C, [b_look0[0], b_look0[1], 600.0], ease(u)))
    def bpos(u):
        p, _ = along(blvd, b_s0 + b_len * u); return [p[0], p[1], ALT_B]
    def blook(u):
        p, _ = along(blvd, b_s0 + b_len * u + 8000.0); return [p[0], p[1], 600.0]
    seg(27.0, 49.0, bpos, blook)
    # D/E. canal: a 490 m stretch starting at the canal point nearest the boulevard's end
    ALT_C = 2200.0
    bend = W[-1][1]
    Lc = polyline_len(canal)
    dists = []
    s = 0.0
    while s < Lc:
        p, _ = along(canal, s); dists.append((math.dist(p, bend[:2]), s)); s += 2000.0
    c_s = min(dists)[1] if dists else 0.0
    c_len = min(30800.0, Lc * 0.6)            # 22 s at 14 m/s
    fwd = 1
    if c_s + c_len > Lc:
        fwd = -1                                          # glide the other way along the canal
    c_s0 = c_s
    def cpt(d):
        return along(canal, max(0.0, min(Lc, c_s0 + fwd * d)))
    cstart = cpt(0.0)[0] + [ALT_C]
    zc = clearance(bend, cstart)
    cl0 = cpt(15000.0)[0]
    seg(49.0, 55.0, lambda u: transit(bend, cstart, u, zc), lambda u: lerp(W[-1][2] if False else blook(1.0), [cl0[0], cl0[1], 300.0], ease(u)))
    seg(55.0, 77.0, lambda u: cpt(c_len * u)[0] + [ALT_C], lambda u: cpt(c_len * u + 15000.0)[0] + [300.0])
    cend = W[-1][1]
    canal_stretch = [cpt(d)[0] for d in range(0, int(c_len) + 1, 2000)]
    # F. construction site nearest the canal end: 61-64 transit, 64-73 a 90 deg orbit
    sites = PLAN_SITES[:]
    for b in blds:
        if b["status"] != "existing":
            sites.append({"x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"], "cx": b["cx"], "cy": b["cy"], "h": b["h"], "src": "register_construction"})
    for q in sites:
        q.setdefault("h", 0.0)
    site = min(sites, key=lambda q: math.hypot(q["cx"] - cend[0], q["cy"] - cend[1])) if sites else {"cx": C[0], "cy": C[1], "x0": C[0] - 3000, "x1": C[0] + 3000, "y0": C[1] - 3000, "y1": C[1] + 3000, "h": 0}
    hd = math.hypot(site["x1"] - site["x0"], site["y1"] - site["y0"]) / 2.0
    R_s = max(15000.0, 2.2 * hd)
    near_h = [q["h"] for q in blds if math.hypot(q["cx"] - site["cx"], q["cy"] - site["cy"]) < R_s + 30000.0]
    Z_s = max(7000.0, (max(near_h) if near_h else 0.0) + 2500.0)       # orbit above every tower within the circle
    look_s = [site["cx"], site["cy"], 2000.0]
    ths = math.atan2(cend[1] - site["cy"], cend[0] - site["cx"])
    s0p = [site["cx"] + math.cos(ths) * R_s, site["cy"] + math.sin(ths) * R_s, Z_s]
    zc = clearance(cend, s0p)
    seg(77.0, 80.0, lambda u: transit(cend, s0p, u, zc), lambda u: lerp(cpt(c_len + 15000.0)[0] + [300.0], look_s, ease(u)))
    seg(80.0, 94.0, lambda u: [site["cx"] + math.cos(ths + math.radians(42) * u) * R_s, site["cy"] + math.sin(ths + math.radians(42) * u) * R_s, Z_s], lambda u: look_s)
    # G. rise + pull-back to the Burj skyline 73-85 s; H. steady closing frame 85-90 s
    # Closing frame (also the teaser's, ep08 map beat): centred on the canal side at Marasi Drive, the camera on the far
    # side of it from the Burj, so the Burj Khalifa skyline stands behind the district in the upper frame.
    last = W[-1][1]
    mid, _ = along(blvd, Lb * 0.5)
    Q = min((along(canal, s)[0] for s in range(0, int(Lc), 2000)), key=lambda p: math.dist(p, mid)) if canal else mid
    away = [Q[0] - burj[0], Q[1] - burj[1]]; na = math.hypot(*away) or 1.0; away = [away[0] / na, away[1] / na]
    close_look = [Q[0], Q[1], 3000.0]
    pb_end = [Q[0] + away[0] * 220000.0, Q[1] + away[1] * 220000.0, 135000.0]
    pb_start = [Q[0] + away[0] * 190000.0, Q[1] + away[1] * 190000.0, 115000.0]     # teaser/ep08: the close must read as the WHOLE district
    zc = max(clearance(last, pb_start), 30000.0)
    # G. 75-82 transit (cut away in the edit); H. 82-90 slow pull-back (~26 m/s, 200 m back + 80 m up); 90-94 steady
    seg(94.0, 101.0, lambda u: transit(last, pb_start, u, zc), lambda u: lerp(look_s, close_look, ease(u)))
    seg(101.0, 111.0, lambda u: lerp(pb_start, pb_end, ease(u)), lambda u: close_look)
    hold_end = [pb_end[0] + away[0] * 120.0, pb_end[1] + away[1] * 120.0, pb_end[2] + 40.0]   # 0.3 m/s drift
    seg(111.0, TOTAL_S, lambda u: lerp(pb_end, hold_end, u), lambda u: close_look)

    W.sort(key=lambda w: w[0])
    def at(t):
        for k in range(len(W) - 1):
            if W[k][0] <= t <= W[k + 1][0]:
                u = (t - W[k][0]) / ((W[k + 1][0] - W[k][0]) or 1)
                return lerp(W[k][1], W[k + 1][1], u), lerp(W[k][2], W[k + 1][2], u)
        return W[-1][1], W[-1][2]
    DT = 0.2
    ts = [round(k * DT, 3) for k in range(int(TOTAL_S / DT) + 1)]
    raw = [at(t) for t in ts]
    sig = 3.0
    keys = []
    for j, t in enumerate(ts):
        if t <= 1.0 or t >= 111.0:
            keys.append([t, raw[j][0], raw[j][1]]); continue
        acc_p = [0.0] * 3; acc_l = [0.0] * 3; ws = 0.0
        for k in range(max(0, j - 9), min(len(ts), j + 10)):
            w = math.exp(-0.5 * ((k - j) / sig) ** 2); ws += w
            for q in range(3):
                acc_p[q] += w * raw[k][0][q]; acc_l[q] += w * raw[k][1][q]
        keys.append([t, [v / ws for v in acc_p], [v / ws for v in acc_l]])
    # clearance: no key inside a tower's bounds (+15 m); lifts are feathered over +-1.6 s so the camera rises over it smoothly
    from shapely.geometry import Polygon as _P, Point as _Pt
    polys = []
    for q in blds:
        try:
            polys.append((_P([(v[0], v[1]) for v in q["ring"]]).buffer(400.0), q["h"]))    # true footprint + 4 m
        except Exception:
            pass
    req = []
    for t, p, l in keys:
        z = 0.0; pt = _Pt(p[0], p[1])
        for pg, h in polys:
            if h + 2500.0 > p[2] and pg.contains(pt):
                z = max(z, h + 2500.0)
        req.append(z)
    lifted = 0
    for j in range(len(keys)):
        need = max(req[k] * (0.5 + 0.5 * math.cos(math.pi * (k - j) / 9.0)) for k in range(max(0, j - 8), min(len(keys), j + 9)))
        if need > keys[j][1][2]:
            keys[j][1][2] = need; lifted += 1
    print("  clearance: %d keys lifted over towers" % lifted)
    vmax = max(math.dist(keys[k + 1][1], keys[k][1]) / DT for k in range(len(keys) - 1)) / 100.0
    print("  camera: %d keys, orbit D %.0f m (radius %.0f, alt %.0f m), peak %.0f m/s, site %s (%s)" %
          (len(keys), D / 100, R_orb / 100, Z_orb / 100, vmax, site.get("src"), "%.0f m2" % site.get("area_m2", 0)))

    # ---- dressing -------------------------------------------------------------------------------------------------
    low_path = [k[1][:2] for k in keys if 20.0 <= k[0] <= 94.0 and k[1][2] < 12000.0]
    def near(p, r=NEAR_CM):
        return any(abs(p[0] - q[0]) < r and abs(p[1] - q[1]) < r and math.hypot(p[0] - q[0], p[1] - q[1]) < r for q in low_path[::3])
    fp = [(b["x0"] - 300, b["y0"] - 300, b["x1"] + 300, b["y1"] + 300) for b in blds]
    def in_bld(p):
        return any(a <= p[0] <= c and b <= p[1] <= d for a, b, c, d in fp)
    def in_water(p):
        return canal and dist_to_pl(p, canal) < 3000.0 + (max(cwidth) / 2 if cwidth else 0)
    D_ = {"road_palms": [], "verge_hedge": [], "verge_bougainvillea": [], "lamps": [], "parked_cars": [], "boats": [],
          "g_palms": [], "g_trees": [], "benches": [], "bins": [], "bus_shelters": [], "bollards": []}
    for s in sts:
        if s["bridge"] or s["hw"] not in PALM_ROADS | CAR_ROADS:
            continue
        off = s["sw"] * 50.0 + 250.0                       # kerb + 2.5 m verge
        for side in (-1, 1):
            if s["hw"] in PALM_ROADS:
                for k, (p, dr) in enumerate(samples(s["pl"], 1350.0, 600.0)):
                    q = [p[0] - dr[1] * off * side, p[1] + dr[0] * off * side]
                    if in_bld(q) or in_water(q):
                        continue
                    D_["road_palms"].append([round(q[0]), round(q[1]), round(rnd.uniform(0, 360), 1), round(rnd.uniform(0.9, 1.12), 3), k % 3])   # k%3: 0,1 date, 2 washingtonia
                    m, _ = along(s["pl"], 600.0 + 1350.0 * k + 675.0)
                    hq = [m[0] - dr[1] * off * side, m[1] + dr[0] * off * side]
                    if not in_bld(hq) and near(hq, NEAR_CM * 1.4):
                        D_["verge_bougainvillea" if k % 4 == 1 else "verge_hedge"].append([round(hq[0]), round(hq[1]), round(yaw(dr), 1), round(rnd.uniform(0.85, 1.15), 3)])
                for k, (p, dr) in enumerate(samples(s["pl"], 3200.0, 1200.0)):
                    q = [p[0] - dr[1] * (off - 150.0) * side, p[1] + dr[0] * (off - 150.0) * side]
                    if near(q) and not in_bld(q):
                        D_["lamps"].append([round(q[0]), round(q[1]), round(yaw(dr) + (90 if side > 0 else -90), 1), 1.0])
            if s["hw"] in CAR_ROADS:
                po = s["sw"] * 50.0 - 120.0
                for p, dr in samples(s["pl"], 650.0, 300.0):
                    if rnd.random() > 0.3:
                        continue
                    q = [p[0] - dr[1] * po * side, p[1] + dr[0] * po * side]
                    if near(q) and not in_bld(q):
                        D_["parked_cars"].append([round(q[0]), round(q[1]), round(yaw(dr) + (0 if side > 0 else 180), 1), 1.0, rnd.randrange(8)])
    g = load(os.path.join(BB, "greenery_ue.json"))
    for key, src in (("g_palms", "palms"), ("g_trees", "trees")):
        for r in g.get(src, []):
            D_[key].append([r[0], r[1], r[2], r[3], rnd.randrange(3)])
    fu = load(os.path.join(BB, "furniture_ue.json"))
    for key in ("benches", "bins", "bus_shelters", "bollards"):
        for r in fu.get(key, []):
            if near(r[:2]):
                D_[key].append([r[0], r[1], r[2] if len(r) > 2 else 0.0, 1.0])
    # boats: moored along both banks of the canal stretch, every ~45 m
    for k, p in enumerate(canal_stretch):
        j = min(len(canal) - 1, k)
        _, dr = along(canal, c_s0 + fwd * 2000.0 * k)
        wh = (cwidth[min(len(cwidth) - 1, int((c_s0 + fwd * 2000.0 * k) / 5000.0))] / 2.0 if cwidth else 3000.0)
        side = 1 if k % 2 else -1
        q = [p[0] - dr[1] * (wh - 900.0) * side, p[1] + dr[0] * (wh - 900.0) * side]
        D_["boats"].append([round(q[0]), round(q[1]), round(yaw(dr) + rnd.choice((0, 180)), 1), 1.0, rnd.randrange(3)])
    for key, cap in (("road_palms", CAPS["road_palms"]), ("g_palms", CAPS["g_palms"]), ("g_trees", CAPS["g_trees"]), ("lamps", CAPS["lamps"]),
                     ("parked_cars", CAPS["parked"]), ("verge_hedge", CAPS["verge"]), ("verge_bougainvillea", CAPS["verge"] // 3)):
        if len(D_[key]) > cap:
            # keep everything near the low shots, thin the rest
            nr = [r for r in D_[key] if near(r[:2])]; far = [r for r in D_[key] if not near(r[:2])]
            rnd.shuffle(far)
            D_[key] = (nr + far)[:cap]
    for key in ("benches", "bins", "bollards"):
        D_[key] = D_[key][:CAPS["furniture"]]
    print("  dressing: " + ", ".join("%s %d" % (k, len(v)) for k, v in D_.items()))

    # ---- movers: cars on the boulevard (both directions), boats on the canal stretch --------------------------------
    movers = []
    b_path = [along(blvd, max(0.0, b_s0 - 20000.0) + d)[0] for d in range(0, int(b_len + 60000.0), 1000)]
    for k in range(8):
        lane = (1 if k % 2 else -1) * (350.0 + 350.0 * (k % 4 // 2))
        pl = b_path if k % 2 else b_path[::-1]
        movers.append({"kind": "car", "variant": k % 8, "path": [[round(p[0]), round(p[1])] for p in pl], "lane_cm": lane,
                       "start_cm": 4000.0 + 7000.0 * k, "speed_cms": rnd.uniform(1300.0, 1800.0)})
    c_path = [cpt(d - 10000.0)[0] for d in range(0, int(c_len + 40000.0), 1000)]
    for k in range(3):
        movers.append({"kind": "boat", "variant": k % 3, "path": [[round(p[0]), round(p[1])] for p in c_path], "lane_cm": (-1500.0, 1200.0, 0.0)[k],
                       "start_cm": 9000.0 + 14000.0 * k, "speed_cms": 700.0 + 150.0 * k})
    return {
        "fps": FPS, "total_s": TOTAL_S, "focal_mm": FOCAL_MM, "teaser": TEASER, "edit": EDIT, "bar_s": BAR, "district_cfg": DISTRICT, "frame": "UE cm, X = easting - 328289, Y = 2784598 - northing",
        "district": {"bbox_cm": [x0, y0, x1, y1], "centre_cm": C, "reach_cm": reach, "tallest_cm": Htop, "buildings": len(blds)},
        "burj_cm": burj, "canal_cm": canal, "boulevard_cm": blvd, "site": site, "sites": sites, "dress": D_, "movers": movers,
        "keys": [[t, [round(v, 1) for v in p], [round(v, 1) for v in l]] for t, p, l in keys],
    }


PLAN_SITES = []
SURROUND_KM = 3.0
SKIP_SURROUND = {"businessbay", "burjkhalifa"}          # both come in as Datasmith towers


def surroundings(bbox):
    """the neighbouring districts within SURROUND_KM (Ellington v17 lesson: no island in the desert): their buildings as
    one massing OBJ (register/geojson heights) and their street layers merged per layer. Returns context meta rows."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ue_city_build as CB
    from shapely.geometry import shape, Polygon, MultiPolygon
    from shapely.ops import transform as shp_transform
    idx = load(os.path.join(ROOT, "data", "ce", "_city", "INDEX.json"))
    m = SURROUND_KM * 1e5
    X0, Y0, X1, Y1 = bbox[0] - m, bbox[1] - m, bbox[2] + m, bbox[3] + m
    slugs = [s for s, v in idx.items() if s not in SKIP_SURROUND and v.get("bbox_cm") and not
             (v["bbox_cm"][2] < X0 or v["bbox_cm"][0] > X1 or v["bbox_cm"][3] < Y0 or v["bbox_cm"][1] > Y1)]
    V, T, n = [], [], 0
    acc = {}
    for s in slugs:
        p = os.path.join(ROOT, "data", "ce", s, "buildings.geojson")
        if os.path.exists(p):
            for f in load(p)["features"]:
                try:
                    g = shp_transform(lambda x, y, z=None: tr.transform(x, y), shape(f["geometry"])).buffer(0)
                except Exception:
                    continue
                c = g.centroid; ux, uy = (c.x - OFF_E) * 100, (OFF_N - c.y) * 100
                if not (X0 <= ux <= X1 and Y0 <= uy <= Y1):
                    continue
                h = max(3.0, min(float(f["properties"].get("bHeight") or 12.0), 900.0))
                for pg in (list(g.geoms) if isinstance(g, MultiPolygon) else [g]):
                    if isinstance(pg, Polygon) and pg.area > 4.0:
                        pg = pg.simplify(0.3, preserve_topology=True)
                        if len(pg.exterior.coords) >= 4:
                            CB.prism(pg, h * 100.0, V, T); n += 1
        cp = os.path.join(ROOT, "data", "ce", s, "context_ue.json")
        if os.path.exists(cp):
            for L in load(cp).get("layers", []):
                if L["name"] not in ("asphalt", "pavement", "parking", "grass") or not L.get("tris"):
                    continue
                A = acc.setdefault(L["name"], {"V": [], "T": [], "L": L})
                base = len(A["V"]) // 3
                A["V"] += L["verts"]; A["T"] += [t + base for t in L["tris"]]
    meta = {}
    if T:
        meta["s_buildings"] = dict(write_obj(os.path.join(OUT, "ctx_s_buildings.obj"), V, T, "ctx_s_buildings"), role="massing", buildings=n)
    for name, A in acc.items():
        L = A["L"]
        meta["s_" + name] = dict(write_obj(os.path.join(OUT, "ctx_s_%s.obj" % name), A["V"], A["T"], "ctx_s_" + name),
                                 rgb=L.get("rgb"), roughness=L.get("roughness"), specular=L.get("specular"), z_cm=L.get("z_cm"))
    print("  surroundings (%.0f km): %d districts %s, %d buildings, layers %s" % (SURROUND_KM, len(slugs), slugs, n, sorted(acc)))
    return meta


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    print("bb_v0_prep: context layers")
    ctx, sites = context_layers()
    PLAN_SITES.extend(sites)
    print("  construction sites (OSM, >= 1,500 m2): %d" % len(sites))
    print("bb_v0_prep: plan")
    p = plan()
    ctx.update(surroundings(p["district"]["bbox_cm"]))
    p["context"] = ctx
    json.dump(p, open(os.path.join(OUT, "bb_v0_plan.json"), "w", encoding="utf-8"), separators=(",", ":"))
    print("bb_v0_prep: -> %s" % OUT)


if __name__ == "__main__":
    main()













