"""Indicative floor plates for every register-bound building in a district: the surveyed footprint, the homes the registers put
on each floor drawn round its facades and coloured by type, lifts and stairs, a legend and the level.

Kendall, 20 Sep 2026, on the building page's floor card (a bare outline): "the floor plate should look something like this" - a
marketing floor plate, every unit a coloured cell - then: "build out as many floors as you can for business bay and damac hills".
This is scripts/build_floor_plate.py (one building, one floor, slabs only) made general and run over a district.

What is real and what is not, because every surface that shows a plate has to say so:
  real        the outline (data/ce/<district>/buildings.geojson, feature index == the building id everywhere else), the floor's
              use, how many homes it carries (the Municipality's count per floor where there is one, otherwise the register's
              units per type spread over that type's floor range), each type's median size (cells are to scale against each
              other), the lift count where the building record has one.
  indicative  WHERE each home sits, and where the lifts and stairs are. Nobody publishes that short of a Revit model or a
              developer stacking plan (docs/TWIN_FLOOR_LAYOUT.md, "No unit positions"). No unit numbers are drawn until the DLD
              units register is cut per building (scripts/build_unit_level.py).

One method for slabs and towers: walk the facade; every home takes the stretch of facade whose area is its share and runs inward
at most MAXD, or to the corridor line where the plate is shallow. A deep plate keeps its middle (the core of a tower, the
courtyard of a block). Floors that carry the same homes share one drawing.

    python scripts/build_floor_plates.py businessbay damachills   -> data/board/plates_<district>.json + data/stack/plates_viewer.html
"""
import json, math, os, sys, time

from shapely.geometry import Point, Polygon, box
from shapely.geometry.polygon import orient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOARD = os.path.join(ROOT, "data", "board")
MAXD, CORRIDOR, DS = 11.0, 2.2, 1.0
HOME_USES = ("homes", "hotel")
KNOWN = ("studio", "1", "2", "3", "4", "office", "retail", "hotel")
CELL_USES = ("office", "retail")


def ring_of(feature):
    g = feature["geometry"]
    ring = g["coordinates"][0] if g["type"] == "Polygon" else max((p[0] for p in g["coordinates"]), key=len)
    lon0, lat0 = ring[0]
    k = 111320 * math.cos(math.radians(lat0))
    P = [((x - lon0) * k, (y - lat0) * 110540) for x, y in ring]
    if P[0] != P[-1]:
        P.append(P[0])
    return P


def area(P):
    return sum(P[i][0] * P[i + 1][1] - P[i + 1][0] * P[i][1] for i in range(len(P) - 1)) / 2.0


def flat_frame(P):
    """Turn the outline so its long side lies flat, counter-clockwise, centred. Returns the points and the turn in degrees."""
    n = len(P) - 1; mx = sum(p[0] for p in P[:n]) / n; my = sum(p[1] for p in P[:n]) / n
    sxx = sum((p[0] - mx) ** 2 for p in P[:n]); syy = sum((p[1] - my) ** 2 for p in P[:n]); sxy = sum((p[0] - mx) * (p[1] - my) for p in P[:n])
    th = 0.5 * math.atan2(2 * sxy, sxx - syy)
    c, s = math.cos(-th), math.sin(-th)
    Q = [((p[0] - mx) * c - (p[1] - my) * s, (p[0] - mx) * s + (p[1] - my) * c) for p in P]
    if area(Q) < 0:
        Q = Q[::-1]
    return Q, math.degrees(th)


def biggest(g):
    if g.is_empty:
        return None
    if g.geom_type == "Polygon":
        return g
    polys = [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon" and not p.is_empty]
    return max(polys, key=lambda p: p.area) if polys else None


def inset(poly, t):
    return biggest(poly.buffer(-t, join_style=2))


def deepest(poly):
    """How far in from the facade the middle of the plate is (its inradius), by bisection on the inward offset."""
    lo, hi = 0.0, 80.0
    for _ in range(18):
        mid = (lo + hi) / 2.0
        if inset(poly, mid) is None:
            hi = mid
        else:
            lo = mid
    return lo


def tower_of(poly, gross):
    """A footprint far larger than the floor the register describes is a podium: the tower plate is drawn inside it, at the size
    the register implies, by offsetting the footprint inward. Returns (plate, True) then, else (footprint, False)."""
    if not gross or poly.area <= gross * 1.6:
        return poly, False
    lo, hi = 0.0, deepest(poly)
    for _ in range(18):
        mid = (lo + hi) / 2.0
        g = inset(poly, mid)
        if g is None or g.area < gross * 1.15:
            hi = mid
        else:
            lo = mid
    g = inset(poly, lo)
    return (g, True) if g is not None and g.area > 80 else (poly, False)


def ray(c, n, edges):
    best = 0.0
    for (ax, ay), (bx, by) in edges:
        ex, ey = bx - ax, by - ay
        den = n[0] * ey - n[1] * ex
        if abs(den) < 1e-9:
            continue
        t = ((ax - c[0]) * ey - (ay - c[1]) * ex) / den
        u = ((ax - c[0]) * n[1] - (ay - c[1]) * n[0]) / den
        if t > 0.3 and -1e-6 <= u <= 1 + 1e-6 and (best == 0.0 or t < best):
            best = t
    return best


def walk(plate):
    """Points every DS round the facade, counter-clockwise from the leftmost corner, each with the way in and how deep a home may
    run there: MAXD, or to the corridor line where the plate is shallower than two homes and a corridor."""
    ring = list(orient(plate, 1.0).exterior.coords)
    k = min(range(len(ring) - 1), key=lambda i: (ring[i][0], ring[i][1]))
    ring = ring[k:-1] + ring[:k] + [ring[k]]
    edges = list(zip(ring, ring[1:]))
    st = []
    for (ax, ay), (bx, by) in edges:
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-6:
            continue
        n = (-(by - ay) / L, (bx - ax) / L)
        m = max(1, int(round(L / DS)))
        for j in range(m):
            t = (j + 0.5) / m
            st.append({"p": (ax + (bx - ax) * t, ay + (by - ay) * t), "n": n, "w": L / m})
    N = len(st)
    for i, s in enumerate(st):                                 # soften the turn at a corner, so homes fan round it
        nx = sum(st[(i + k) % N]["n"][0] for k in range(-3, 4)); ny = sum(st[(i + k) % N]["n"][1] for k in range(-3, 4))
        L = math.hypot(nx, ny) or 1.0
        s["ns"] = (nx / L, ny / L)
    for s in st:
        across = ray(s["p"], s["ns"], edges)
        s["d0"] = min(MAXD, max(1.5, across / 2.0 - CORRIDOR / 2.0)) if across else 1.5
    for i, s in enumerate(st):
        s["d"] = sum(st[(i + k) % N]["d0"] for k in range(-3, 4)) / 7.0
        s["in"] = (s["p"][0] + s["ns"][0] * s["d"], s["p"][1] + s["ns"][1] * s["d"])
        s["a"] = s["w"] * s["d"]
    return st


def layout(plate, run, lifts, want):
    """Cells for one floor: every home takes the stretch of facade whose share of the band is its share of the floor. The cells
    are clipped to the plate and to each other, so a tight corner gives an odd-shaped home, never two homes on one spot."""
    st = walk(plate)
    N = len(st)
    if N < 8:
        return [], [], None
    dmax = deepest(plate)
    blocks, polys = [], []
    central = dmax > MAXD + 3.5 and plate.area / (plate.length ** 2) > 0.035      # deep AND compact: a tower, not a long block with one fat end
    if central:                                                   # a tower: the lifts sit in the middle
        mid = inset(plate, max(0.0, dmax - 1.0)) or plate
        c = mid.centroid if mid.contains(mid.centroid) else mid.representative_point()
        room = max(3.0, (dmax - MAXD) * 1.2)
        w = min(room * 1.4, 5.0 + math.sqrt(lifts or 6) * 2.6); h = min(room, w * 0.62)
        polys.append(["lift", box(c.x - w / 2, c.y - h / 2, c.x + w / 2 - 2.8, c.y + h / 2)])
        polys.append(["stair", box(c.x + w / 2 - 2.8, c.y - h / 2, c.x + w / 2, c.y + h / 2)])
    else:                                                         # a slab or a block round a court: along the far facade
        per = sum(s["w"] for s in st)
        k = max(1, min(int(per // 70) or 1, int(round((lifts or 6) / 6.0))))
        for i in range(k):
            a = min(int(N * (0.5 + (i + 0.5) / k)) % N, max(0, N - 13))
            blocks += [(a, a + 8, "lift"), (a + 8, a + 12, "stair")]
    used = [None]

    def union_safe(a, b):
        """GEOS refuses a few of these wedges outright - "side location conflict", which killed every plate in Jumeirah
        Village Circle on 21 Sep. A zero-width buffer repairs the geometry; if the union still cannot be taken, the area
        already claimed is kept as it was, so one bad cell costs its own overlap and not the whole district."""
        for x, y in ((a, b), (a.buffer(0), b.buffer(0))):
            try:
                return x.union(y)
            except Exception:
                pass
        return a

    def wedge(ss):
        pts = [s["p"] for s in ss] + [s["in"] for s in ss[::-1]]
        if len(pts) < 4:
            return None
        try:
            g = Polygon(pts).buffer(0).intersection(plate)
            if used[0] is not None:
                g = g.difference(used[0])
            g = biggest(g)
        except Exception:
            return None
        if g is None or g.area < 1.0:
            return None
        used[0] = g if used[0] is None else union_safe(used[0], g)
        return g

    taken = [None] * N
    for a, b, kind in blocks:
        for i in range(a, min(b, N)):
            taken[i] = kind
        g = wedge(st[a:min(b + 1, N)])
        if g is not None:
            polys.append([kind, g])
    avail = sum(s["a"] for i, s in enumerate(st) if not taken[i])
    cells, i, cur, acc = [], 0, [], 0.0

    def close(u, ss):
        g = wedge(ss)
        if g is not None:
            cells.append([u["c"], g, i])

    for j, s in enumerate(st):
        if taken[j]:
            if len(cur) > 1 and i < len(run):
                close(run[i], cur); i += 1
            cur, acc = [], 0.0
            continue
        if i >= len(run):
            break
        cur.append(s); acc += s["a"]
        if acc >= run[i]["sqm"] / want * avail and i < len(run) - 1:
            close(run[i], cur); i += 1; cur, acc = [s], 0.0
    if len(cur) > 1 and i < len(run):
        close(run[i], cur)
    flat = lambda g: [round(v, 1) for p in list(g.simplify(0.15).exterior.coords)[:-1] for v in p]
    return [[c, flat(g), n] for c, g, n in cells], [[k, flat(g)] for k, g in polys], avail / want


def interleave(kinds):
    """The floor's homes as one run with the types mixed evenly, the largest at the ends of the run and spread through it."""
    total = sum(k["n"] for k in kinds); seq = []; acc = {k["c"]: 0.0 for k in kinds}
    for _ in range(total):
        for k in kinds:
            acc[k["c"]] += k["n"] / float(total)
        best = max(kinds, key=lambda k: acc[k["c"]]); acc[best["c"]] -= 1.0
        seq.append(best)
    return seq


def floor_kinds(b, f):
    """The homes on one floor, by type: the Municipality's count for the floor where it has one, shared between the types whose
    floor range covers it in the register's proportions; otherwise the register's units spread over each type's range."""
    n = f["n"]
    rates = []
    for t in b.get("types") or []:
        if n is None or t.get("lo") is None or t.get("hi") is None or t["c"] in ("other", "office", "retail") or not (t["lo"] <= n <= t["hi"]):
            continue
        rates.append((t, t["units"] / float(t["hi"] - t["lo"] + 1)))
    if not rates:
        return [], "none"
    k = f.get("k") or 0
    if k:
        tot = sum(r for _, r in rates); shares = [(t, k * r / tot) for t, r in rates]
        counts = [(t, int(math.floor(x))) for t, x in shares]
        left = k - sum(c for _, c in counts)
        order = sorted(range(len(shares)), key=lambda i: -(shares[i][1] - math.floor(shares[i][1])))
        counts = [(t, c + (1 if i in order[:left] else 0)) for i, (t, c) in enumerate(counts)]
        basis = "municipality"
    else:
        counts = [(t, int(round(r))) for t, r in rates]; basis = "register"
    return [{"c": t["c"], "n": c, "sqm": t.get("sqm") or 60.0} for t, c in counts if c > 0], basis


def building(b, feature, lifts, units=None):
    Q, north = flat_frame(ring_of(feature))
    poly = biggest(Polygon(Q[:-1]).buffer(0))
    flat = lambda g: [round(v, 1) for p in list(g.exterior.coords)[:-1] for v in p]
    rec = {"name": b["name"], "levels": len(b["floors"]), "lifts": lifts, "north": round(north, 1), "area": round(poly.area) if poly else 0,
           "outline": flat(poly) if poly else [], "conflict": bool(b.get("conflict")), "fits": b.get("fits", True), "plates": [], "floors": {}}
    if poly is None or poly.area < 120:
        return rec, 0
    seen = {}
    for f in b["floors"]:
        use = f["u"]
        if use in HOME_USES:
            kinds, basis = floor_kinds(b, f)
        elif use in CELL_USES and (f.get("k") or 0) > 0:
            kinds, basis = [{"c": use, "n": f["k"], "sqm": 100.0}], "municipality"
        else:
            kinds, basis = [], "none"
        real = (units or {}).get(str(f["n"])) if f.get("n") is not None else None
        labels = None; dm_use = None
        if real and use not in HOME_USES + CELL_USES:
            dm_use, use = use, "homes"          # the two registers disagree about this floor; the one that lists the homes is drawn, and the plate says so
        if real and use in HOME_USES + CELL_USES:
            # the DLD units register, one row per unit: real unit numbers, types and sizes for this floor. Laid round the facade in
            # unit-number order - the order is the register's, the position on the plate is still indicative.
            real = sorted(real, key=lambda x: (len(x["u"]), x["u"]))
            med = {t["c"]: t.get("sqm") or 60.0 for t in b.get("types") or []}
            run_real = [{"c": x["c"] if x["c"] in KNOWN else "other", "sqm": max(15.0, round((x["sqft"] or 0) / 10.764, 0)) if x.get("sqft") else med.get(x["c"], 60.0)} for x in real]
            labels = [x["u"] for x in real]
            kinds, basis = [], "units"
            tally = {}
            for u in run_real:
                tally.setdefault(u["c"], []).append(u["sqm"])
            kinds = [{"c": c, "n": len(v), "sqm": sorted(v)[len(v) // 2]} for c, v in tally.items()]
        else:
            run_real = None
        sig = (use, basis, tuple((k["c"], k["n"]) for k in kinds)) if run_real is None else (use, basis, dm_use, tuple((u["c"], u["sqm"]) for u in run_real))
        if sig not in seen:
            p = {"use": use, "basis": basis, "counts": [[k["c"], k["n"], round(k["sqm"], 1)] for k in kinds], "scale": None,
                 "cells": [], "blocks": [], "tower": None, "skip": None, "dm_use": dm_use}
            if kinds:
                run = run_real if run_real is not None else interleave(kinds)
                want = float(sum(u["sqm"] for u in run))
                gross = want / 0.72 if use in HOME_USES else None
                if gross and poly.area < gross * 0.45:
                    p["skip"] = "small"                       # more homes than this footprint can hold: several buildings on one record
                elif len(run) > 400:
                    p["skip"] = "many"
                else:
                    plate, podium = tower_of(poly, gross)
                    cells, blocks, scale = layout(plate, run, lifts, want if use in HOME_USES else float(len(run)) * 100.0)
                    p["cells"], p["blocks"], p["scale"] = cells, blocks, round(scale, 2) if scale else None
                    if podium:
                        p["tower"] = flat(plate)
            seen[sig] = len(rec["plates"]); rec["plates"].append(p)
        rec["floors"][f["l"]] = seen[sig]
        if labels:
            rec.setdefault("labels", {})[f["l"]] = labels
    return rec, len(b["floors"])


def lifts_of(district):
    p = os.path.join(BOARD, "unitmix_%s.json" % district)
    if not os.path.exists(p):
        return {}
    return {i: r.get("elevators") for i, r in json.load(open(p, encoding="utf-8"))["buildings_by_id"].items()}


def run(district):
    stack = json.load(open(os.path.join(BOARD, "stack_%s.json" % district), encoding="utf-8"))
    feats = json.load(open(os.path.join(ROOT, "data", "ce", district, "buildings.geojson"), encoding="utf-8"))["features"]
    lifts = lifts_of(district)
    up = os.path.join(BOARD, "units_%s.json" % district)
    units = json.load(open(up, encoding="utf-8"))["buildings_by_id"] if os.path.exists(up) else {}
    out = {"district": {"businessbay": "Business Bay", "damachills": "DAMAC Hills"}.get(district, stack.get("district") or district), "slug": district, "generated": time.strftime("%Y-%m-%d"),
           "note": "Indicative floor plates. Real: the surveyed outline, each floor's use, how many homes it carries and their sizes against each "
                   "other, the lift count. Indicative: where each home sits, and where the lifts and stairs are - not published short of a Revit "
                   "model or a developer stacking plan. No unit numbers until the DLD units register is cut per building.",
           "buildings": {}}
    floors = plates = cells = 0
    for i, b in stack["buildings_by_id"].items():
        if int(i) >= len(feats):
            continue
        rec, n = building(b, feats[int(i)], lifts.get(i), (units.get(i) or {}).get("floors"))
        rec["name"] = rec["name"] or "Footprint %s (no name on the register record)" % i
        out["buildings"][i] = rec
        floors += n; plates += len(rec["plates"]); cells += sum(len(p["cells"]) for p in rec["plates"])
    p = os.path.join(BOARD, "plates_%s.json" % district)
    json.dump(out, open(p, "w", encoding="utf-8"), separators=(",", ":"))
    print("%-12s %3d buildings, %5d floors -> %4d distinct plates, %6d homes drawn  (%s, %.1f MB)"
          % (district, len(out["buildings"]), floors, plates, cells, os.path.relpath(p, ROOT), os.path.getsize(p) / 1e6))
    return out


if __name__ == "__main__":
    districts = [a for a in sys.argv[1:] if not a.startswith("-")] or ["businessbay", "damachills"]
    data = [run(d) for d in districts]
    tpl = os.path.join(ROOT, "scripts", "plates_viewer_template.html")
    if os.path.exists(tpl):
        html = open(tpl, encoding="utf-8").read().replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
        dst = os.path.join(ROOT, "data", "stack", "plates_viewer.html"); os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "w", encoding="utf-8").write(html)
        print("viewer -> %s (%.1f MB)" % (os.path.relpath(dst, ROOT), os.path.getsize(dst) / 1e6))
