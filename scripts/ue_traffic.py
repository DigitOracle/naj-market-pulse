"""ue_traffic.py -- DigitAlchemy(R) / Digital Abbot
Moving traffic for a district film (Kendall, 13 Sep: "we have the ability to add people, cars... why can't those be in the fly
through"). The 5,696 parked cars in Damac Hills are invisible from a drone; cars that move are what make an aerial read as a living
place.

Lanes come from the real road network (data/ce/<slug>/highways_osm.json, Overpass 'out geom'): UAE traffic drives on the right, so
each carriageway gets lanes offset to the right of its direction of travel, both directions unless the way is one-way. Cars are
seeded along lanes at a density by road class and drive at 85-100% of a class speed for the length of the film.

Only cars the camera can plausibly see are kept: a car is chosen when its route passes within reach of the film's camera track
(data from the film's camera_track.json), with reach growing with camera height, capped so the sequence stays light.

Keys are written at the lane's vertices (time = arc length / speed), so the Unreal side keys a handful of points per car with linear
interpolation instead of one key per frame.

Output: data/ce/<slug>/traffic_ue.json
  {"fps": 24, "frames": 1080, "cars": [{"model": "esri_car_audia6", "keys": [[frame, x, y, z, yaw_deg], ...]}, ...]}
Usage:  python scripts/ue_traffic.py <slug> [max_cars=240] [seconds=45]
"""
import json, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
FILMS = "C:/Users/kwils/OneDrive/Desktop/DigitAlchemy_31MAY2026/Ecosystem/30_kits/unreal/results"
E0 = 328289.0; N0 = 2784598.0
# class -> (speed km/h, cars per km per lane, lanes each way, lane width cm)
ROADS = {"motorway": (100, 10, 3, 360), "trunk": (90, 10, 3, 360), "primary": (80, 9, 2, 350), "secondary": (60, 7, 2, 340),
         "tertiary": (50, 5, 1, 330), "residential": (30, 2.5, 1, 300), "unclassified": (40, 2.5, 1, 300), "living_street": (20, 1.5, 1, 280),
         "motorway_link": (60, 5, 1, 360), "trunk_link": (60, 5, 1, 360), "primary_link": (50, 5, 1, 350), "secondary_link": (40, 4, 1, 340)}
MODELS = [("esri_car_toyotaprius", 16), ("esri_car_audia6", 10), ("esri_car_fordedge", 12), ("esri_car_mercedessclass", 8),
          ("esri_car_bmw3series", 8), ("esri_car_fordexpedition", 8), ("esri_car_pickuptrucktoyotahilux", 9), ("esri_car_teslap7", 6),
          ("esri_car_taxi", 7), ("esri_car_vantaxi", 3), ("esri_car_volkswagenjettawagon", 5), ("esri_car_fordtransitcommercialvan", 4),
          ("esri_car_deliverytruck", 2), ("esri_car_bus", 1)]
_TR = None


def to_ue(lon, lat):
    global _TR
    if _TR is None:
        from pyproj import Transformer
        _TR = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    e, n = _TR.transform(lon, lat)
    return (e - E0) * 100.0, (-n + N0) * 100.0


def offset_line(pts, off):
    """polyline offset to the RIGHT of travel by off cm (Unreal frame: +Y is right of +X, so right-hand normal = (-uy, ux))."""
    out = []
    for i, (x, y) in enumerate(pts):
        a = pts[max(i - 1, 0)]; b = pts[min(i + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy) or 1.0
        out.append((x - dy / L * off, y + dx / L * off))
    return out


def main():
    args = [a for a in sys.argv[1:] if a]; kw = dict(a.split("=") for a in args if "=" in a); pos = [a for a in args if "=" not in a]
    slug = pos[0]; MAX = int(kw.get("max_cars", 240)); SECONDS = float(kw.get("seconds", 45)); FPS = 24
    rnd = random.Random(slug + "traffic")
    osm = json.load(open(os.path.join(CE, slug, "highways_osm.json"), encoding="utf-8"))
    cam = json.load(open(os.path.join(FILMS, kw.get("film", f"film_{slug}"), "camera_track.json")))      # film=film_<slug>_c3 for a cluster ending
    cams = [(r[1], r[2], r[3]) for r in cam["track"][::6]]
    lanes = []
    for el in osm.get("elements", []):
        t = el.get("tags") or {}; cls = t.get("highway")
        if el.get("type") != "way" or cls not in ROADS or not el.get("geometry"): continue
        speed, dens, nl, lw = ROADS[cls]
        try: nl = max(1, int(t.get("lanes", 0)) // (1 if t.get("oneway") == "yes" else 2)) if t.get("lanes") else nl
        except ValueError: pass
        pts = [to_ue(g["lon"], g["lat"]) for g in el["geometry"]]
        oneway = t.get("oneway") in ("yes", "1", "true") or cls in ("motorway", "motorway_link")
        dirs = [pts] if oneway else [pts, pts[::-1]]
        for d in dirs:
            for li in range(nl):
                off = (li + 0.5) * lw if not oneway else (li + 0.5 - nl / 2) * lw
                lp = offset_line(d, off)
                seg = [math.hypot(lp[i + 1][0] - lp[i][0], lp[i + 1][1] - lp[i][1]) for i in range(len(lp) - 1)]
                L = sum(seg)
                if L < 300: continue
                lanes.append({"pts": lp, "seg": seg, "len": L, "speed": speed * 100000 / 3600.0, "dens": dens, "cls": cls})

    def reach(px, py):
        best = 0.0
        for cx, cy, cz in cams:
            d = math.hypot(px - cx, py - cy); r = max(25000.0, min(160000.0, cz * 3.0 + 20000.0))
            if d < r: best = max(best, 1.0 - d / r)
        return best

    def point_at(lane, s):
        acc = 0.0
        for i, L in enumerate(lane["seg"]):
            if acc + L >= s:
                t = (s - acc) / (L or 1.0); a, b = lane["pts"][i], lane["pts"][i + 1]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), i
            acc += L
        return lane["pts"][-1], len(lane["seg"]) - 1

    cands = []
    for lane in lanes:
        if lane["len"] < 8000: continue          # seed only on real carriageways; short connectors still carry cars through junctions
        n = max(0, int(round(lane["len"] / 100000.0 * lane["dens"] + rnd.random() - 0.3)))
        for _ in range(n):
            s0 = rnd.uniform(0, lane["len"]); v = lane["speed"] * rnd.uniform(0.85, 1.0)
            s1 = min(lane["len"], s0 + v * SECONDS)
            (mx, my), _ = point_at(lane, (s0 + s1) / 2)
            w = reach(mx, my)
            if w > 0: cands.append((w + rnd.random() * 0.15, lane, s0, v))
    cands.sort(key=lambda c: -c[0]); chosen = cands[:MAX]
    # junction graph: a lane ends where another begins (within 18 m); a car carries on along the straightest continuation instead
    # of vanishing where an OSM way is split at a junction.
    # every vertex is a possible join: OSM side streets meet a main road part-way along its way, not at its first node
    grid = {}
    for li, lane in enumerate(lanes):
        for vi in range(len(lane["pts"]) - 1):
            sx, sy = lane["pts"][vi]; grid.setdefault((int(sx // 3000), int(sy // 3000)), []).append((li, vi))
    def lane_heading(lane, at_end):
        a, b = (lane["pts"][-2], lane["pts"][-1]) if at_end else (lane["pts"][0], lane["pts"][1])
        return math.atan2(b[1] - a[1], b[0] - a[0])
    def next_lane(li):
        lane = lanes[li]; ex, ey = lane["pts"][-1]; h = lane_heading(lane, True); best = None
        for gx in range(int(ex // 3000) - 1, int(ex // 3000) + 2):
            for gy in range(int(ey // 3000) - 1, int(ey // 3000) + 2):
                for lj, vj in grid.get((gx, gy), ()):
                    if lj == li: continue
                    o = lanes[lj]; sx, sy = o["pts"][vj]
                    if math.hypot(sx - ex, sy - ey) > 1800: continue
                    a, b = o["pts"][vj], o["pts"][vj + 1]
                    turn = abs((math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]) - h) + 180) % 360 - 180)
                    if turn > 100 and turn < 170: continue
                    key = turn + rnd.random() * 25 + (400 if turn >= 170 else 0)      # a U-turn only at a dead end
                    if best is None or key < best[0]: best = (key, (lj, vj))
        return None if best is None else best[1]

    total_w = sum(w for _, w in MODELS); cars = []
    index_of = {id(l): i for i, l in enumerate(lanes)}
    end_frame = SECONDS * FPS
    for k, (_, lane, s0, v) in enumerate(chosen):
        r = rnd.uniform(0, total_w); acc = 0
        for model, w in MODELS:
            acc += w
            if r <= acc: break
        li = index_of[id(lane)]
        (px, py), seg_i = point_at(lane, s0)
        def hd(ln, i):
            a, b = ln["pts"][i], ln["pts"][i + 1]; return round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), 2)
        keys = [[0, round(px, 1), round(py, 1), 0.0, hd(lane, seg_i)]]; frame = 0.0; hops = 0; done = False
        while not done:
            ln = lanes[li]
            while seg_i < len(ln["seg"]):
                bx, by = ln["pts"][seg_i + 1]; d = math.hypot(bx - px, by - py); f = frame + d / v * FPS
                if f >= end_frame:
                    t = (end_frame - frame) / max(f - frame, 1e-6)
                    keys.append([int(end_frame), round(px + (bx - px) * t, 1), round(py + (by - py) * t, 1), 0.0, hd(ln, seg_i)]); done = True; break
                keys.append([round(f, 2), round(bx, 1), round(by, 1), 0.0, hd(ln, seg_i)]); frame, px, py = f, bx, by; seg_i += 1
                if seg_i < len(ln["seg"]): keys.append([round(frame + 0.5, 2), round(px, 1), round(py, 1), 0.0, hd(ln, seg_i)])
            if done: break
            nxt = next_lane(li) if hops < 40 else None
            if nxt is None:
                keys.append([round(frame + 1, 2), round(px, 1), round(py, 1), -100000.0, keys[-1][4]]); break
            li, seg_i = nxt; hops += 1
            sx, sy = lanes[li]["pts"][seg_i]; d = math.hypot(sx - px, sy - py); frame += d / v * FPS; px, py = sx, sy
            keys.append([round(frame, 2), round(px, 1), round(py, 1), 0.0, hd(lanes[li], seg_i)])
        cars.append({"model": model, "cls": lane["cls"], "hops": hops, "vanishes": keys[-1][3] < 0, "keys": keys})
    out = {"slug": slug, "fps": FPS, "frames": int(SECONDS * FPS), "lanes": len(lanes), "candidates": len(cands), "cars": cars}
    json.dump(out, open(os.path.join(CE, slug, kw.get("out", "traffic_ue.json")), "w", encoding="utf-8"))
    by = {}
    for c in cars: by[c["cls"]] = by.get(c["cls"], 0) + 1
    print(f"{slug}: {len(lanes)} lanes, {len(cands)} candidate cars in camera reach, {len(cars)} kept; by road {by}; "
          f"keys {sum(len(c['keys']) for c in cars)}; still vanish before the end {sum(1 for c in cars if c['vanishes'])}")


if __name__ == "__main__":
    main()
