"""An indicative floor plate for a register-bound building: the surveyed footprint, a corridor down its spine, the homes
the registers put on that floor drawn along both sides and coloured by type, lift cores and stairs, a legend and the level.

Kendall, 20 Sep 2026, on the building page's floor card (a bare outline): "the floor plate should look something like
this" - a marketing floor plate: every unit a coloured cell, studio / one-bed / two-bed, lifts, stairs, LEVEL 5.

What is real and what is not, because the page has to say so:
  real        the outline (data/ce/<district>/buildings.geojson - the footprint the model is built on), how many homes of
              each type the floor carries (the register's units per type spread over that type's floor range), each type's
              median size (so the cells are to scale against each other), the lift count.
  indicative  WHERE each home sits, which side of the corridor, where the cores are. Nobody publishes that short of a Revit
              model or a developer stacking plan (docs/TWIN_FLOOR_LAYOUT.md, "No unit positions"). The plate says so on its face,
              and carries no unit numbers until the DLD units register supplies them (scripts/build_unit_level.py).

    python scripts/build_floor_plate.py businessbay 650 15      -> data/stack/plate_businessbay_650_15.{json,svg,html}
"""
import json, math, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COL = {"studio": "#B9A6C9", "1": "#C5A56A", "2": "#7FA8C9", "3": "#8FC7B9", "4": "#D9A441", "other": "#8A8F96"}
NAME = {"studio": "Studio", "1": "One bedroom", "2": "Two bedroom", "3": "Three bedroom", "4": "Four bedroom +", "other": "Other"}
SHORT = {"studio": "S", "1": "1", "2": "2", "3": "3", "4": "4", "other": ""}
LIFT, STAIR, PLATE, INK = "#5B6662", "#9A95D6", "#2B3532", "#0E1613"
CORRIDOR = 2.2          # metres
MAXD = 11.0             # a home is at most this deep from the facade; what is left in the middle of a deep plate stays plate
DS = 0.5                # station spacing along the spine, metres
STEP = 0.5              # slice spacing along the spine, metres


def footprint(district, name):
    g = json.load(open(os.path.join(ROOT, "data", "ce", district, "buildings.geojson"), encoding="utf-8"))
    want = name.lower()
    hits = [f for f in g["features"] if (f["properties"].get("name") or "").lower() in (want, want.split()[-1])
            or want.endswith((f["properties"].get("name") or "\0").lower())]
    if not hits:
        sys.exit("no footprint named like %r in %s" % (name, district))
    geom = hits[0]["geometry"]
    ring = geom["coordinates"][0] if geom["type"] == "Polygon" else max((p[0] for p in geom["coordinates"]), key=len)
    lon0, lat0 = ring[0]
    k = 111320 * math.cos(math.radians(lat0))
    return [((x - lon0) * k, (y - lat0) * 110540) for x, y in ring]


def spine_frame(P):
    """Rotate so the long axis lies along x (principal axis of the vertices); returns the points and the angle used."""
    n = len(P); mx = sum(p[0] for p in P) / n; my = sum(p[1] for p in P) / n
    sxx = sum((p[0] - mx) ** 2 for p in P); syy = sum((p[1] - my) ** 2 for p in P); sxy = sum((p[0] - mx) * (p[1] - my) for p in P)
    th = 0.5 * math.atan2(2 * sxy, sxx - syy)
    c, s = math.cos(-th), math.sin(-th)
    return [((p[0] - mx) * c - (p[1] - my) * s, (p[0] - mx) * s + (p[1] - my) * c) for p in P], th


def slices(Q):
    """For stations along x: the lowest and highest y inside the outline. A gently curved slab is cut near enough square-on."""
    x0, x1 = min(p[0] for p in Q), max(p[0] for p in Q)
    out = []
    x = x0 + STEP / 2
    while x < x1:
        ys = []
        for (ax, ay), (bx, by) in zip(Q, Q[1:]):
            if (ax - x) * (bx - x) < 0:
                ys.append(ay + (by - ay) * (x - ax) / (bx - ax))
        if len(ys) >= 2:
            out.append((x, min(ys), max(ys)))
        x += STEP
    return out


def floor_units(b, floor):
    """How many homes of each type the register puts on this floor: a type's units spread evenly over its floor range."""
    out = []
    for t in b["types"]:
        if t["lo"] is None or not (t["lo"] <= floor <= t["hi"]) or t["c"] == "other":
            continue
        n = int(round(t["units"] / float(t["hi"] - t["lo"] + 1)))
        if n:
            out.append({"c": t["c"], "n": n, "sqm": t["sqm"]})
    return out


def interleave(kinds):
    """One run of homes with the types mixed the way a plate mixes them: larger homes to the ends and beside the cores fall out
    of an even spread, rather than all the studios in a row."""
    total = sum(k["n"] for k in kinds); seq = []; acc = {k["c"]: 0.0 for k in kinds}
    for _ in range(total):
        for k in kinds:
            acc[k["c"]] += k["n"] / float(total)
        best = max(kinds, key=lambda k: acc[k["c"]]); acc[best["c"]] -= 1.0
        seq.append(best)
    big = sorted([u for u in seq if u["c"] in ("2", "3", "4")], key=lambda u: -u["sqm"])
    rest = [u for u in seq if u["c"] not in ("2", "3", "4")]
    ends = big[:4]; mid = big[4:]
    gap = max(1, len(rest) // (len(mid) + 1))
    body = []
    for i, u in enumerate(rest):
        body.append(u)
        if mid and (i + 1) % gap == 0:
            body.append(mid.pop())
    body += mid
    return ends[:2] + body + ends[2:]


def stations(Q):
    """The spine (centres of square-on slices, smoothed), walked by arc length; at each station the normal and how far the
    outline is on either side of it. Homes are then cut square to the spine, so a curved slab gets fan-shaped homes, not slivers."""
    raw = [(x, (a + b) / 2.0) for x, a, b in slices(Q)]
    W = 40                                                     # +-20 m moving average
    sm = []
    for i in range(len(raw)):
        seg = raw[max(0, i - W):i + W + 1]
        sm.append((raw[i][0], sum(p[1] for p in seg) / len(seg)))
    out, acc = [], 0.0
    edges = list(zip(Q, Q[1:]))

    def reach(c, n):
        best = None
        for (ax, ay), (bx, by) in edges:
            ex, ey = bx - ax, by - ay
            den = n[0] * ey - n[1] * ex
            if abs(den) < 1e-9:
                continue
            t = ((ax - c[0]) * ey - (ay - c[1]) * ex) / den
            u = ((ax - c[0]) * n[1] - (ay - c[1]) * n[0]) / den
            if t > 0 and 0 <= u <= 1 and (best is None or t < best):
                best = t
        return best or 0.0

    for i in range(1, len(sm) - 1):
        tx, ty = sm[i + 1][0] - sm[i - 1][0], sm[i + 1][1] - sm[i - 1][1]
        L = math.hypot(tx, ty) or 1.0
        n = (-ty / L, tx / L)
        acc += math.hypot(sm[i][0] - sm[i - 1][0], sm[i][1] - sm[i - 1][1])
        out.append({"s": acc, "c": sm[i], "n": n, "up": reach(sm[i], n), "dn": reach(sm[i], (-n[0], -n[1]))})
    return out


def _edge(st, side, which):
    t = st["up"] if side > 0 else st["dn"]
    inner = max(CORRIDOR / 2.0, t - MAXD)
    d = t if which == "outer" else inner
    return (st["c"][0] + side * st["n"][0] * d, st["c"][1] + side * st["n"][1] * d)


def _depth(st, side):
    t = st["up"] if side > 0 else st["dn"]
    return max(0.0, t - max(CORRIDOR / 2.0, t - MAXD))


def lay(ST, side, run, blocks):
    """Walk the spine handing each home the stretch of facade whose area is its share. `blocks` are (s0, s1, kind) kept clear."""
    free = [st for st in ST if not any(a <= st["s"] <= b for a, b, _ in blocks)]
    avail = sum(_depth(st, side) * DS for st in free)
    want = sum(u["sqm"] for u in run) or 1.0
    cells, i, cur, acc = [], 0, [], 0.0
    for st in ST:
        blocked = any(a <= st["s"] <= b for a, b, _ in blocks)
        if blocked:
            if len(cur) > 3 and i < len(run):
                cells.append((run[i], cur)); i += 1
            cur, acc = [], 0.0
            continue
        if i >= len(run):
            continue
        cur.append(st); acc += _depth(st, side) * DS
        if acc >= run[i]["sqm"] / want * avail and i < len(run) - 1:
            cells.append((run[i], cur)); i += 1; cur, acc = [cur[-1]], 0.0
    if len(cur) > 3 and i < len(run):
        cells.append((run[i], cur))
    polys = []
    for u, ss in cells:
        ss2 = ss[::4] + ([ss[-1]] if (len(ss) - 1) % 4 else [])
        polys.append({"c": u["c"], "pts": [_edge(s, side, "inner") for s in ss2] + [_edge(s, side, "outer") for s in ss2][::-1]})
    return polys, avail / want


def block_polys(ST, blocks, side):
    out = []
    for a, b, kind in blocks:
        ss = [st for st in ST if a <= st["s"] <= b]
        if len(ss) < 2:
            continue
        out.append({"k": kind, "pts": [_edge(s, side, "inner") for s in ss] + [_edge(s, side, "outer") for s in ss][::-1]})
    return out


def build(district, fid, floor):
    b = json.load(open(os.path.join(ROOT, "data", "board", "stack_%s.json" % district), encoding="utf-8"))["buildings_by_id"][str(fid)]
    Q, th = spine_frame(footprint(district, b["name"]))
    if Q[0] != Q[-1]:
        Q.append(Q[0])
    ST = stations(Q)
    kinds = floor_units(b, floor)
    run = interleave(kinds)
    top, bottom = run[0::2], run[1::2]
    s0, s1 = ST[0]["s"], ST[-1]["s"]; L = s1 - s0
    lifts = 26 if str(fid) == "650" else 8           # the building card's lift count; TODO read it from the DM rollup when the page hands it over
    cores = max(2, int(round(lifts / 6.0)))
    ends = [(s0, s0 + 4.5, "stair"), (s1 - 4.5, s1, "stair")]
    blocks = list(ends)
    for i in range(cores):
        cs = s0 + L * (i + 0.5) / cores
        blocks += [(cs - 5, cs + 5, "lift"), (cs + 5, cs + 8.5, "stair")]
    top_cells, k1 = lay(ST, +1, top, ends)
    bot_cells, k2 = lay(ST, -1, bottom, blocks)
    outline = Q
    return {"building": b["name"], "district": district, "id": str(fid), "floor": floor, "levels": len(b["floors"]),
            "north_deg": round(math.degrees(th), 1),      # the plate is turned so its long side lies flat; north is this far off "up"
            "outline": outline, "cells": top_cells + bot_cells,
            "blocks": block_polys(ST, ends, +1) + block_polys(ST, blocks, -1),
            "counts": [{"c": k["c"], "n": k["n"], "sqm": k["sqm"]} for k in kinds], "lifts": lifts,
            "scale_note": round((k1 + k2) / 2.0, 2)}


def svg(p, width=1000):
    xs = [q[0] for q in p["outline"]]; ys = [q[1] for q in p["outline"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); pad = 6.0
    k = width / (x1 - x0 + 2 * pad); h = (y1 - y0 + 2 * pad) * k
    T = lambda pts: " ".join("%.1f,%.1f" % ((x - x0 + pad) * k, (y1 - y + pad) * k) for x, y in pts)
    o = ['<svg class="fplate" viewBox="0 0 %d %.0f" xmlns="http://www.w3.org/2000/svg" font-family="IBM Plex Mono, monospace">' % (width, h)]
    o.append('<polygon points="%s" fill="%s" stroke="#C5A56A" stroke-opacity=".55" stroke-width="1.6"/>' % (T(p["outline"]), PLATE))
    for c in p["cells"]:
        o.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="1.4" stroke-linejoin="round"/>' % (T(c["pts"]), COL[c["c"]], INK))
        cx = sum(q[0] for q in c["pts"]) / len(c["pts"]); cy = sum(q[1] for q in c["pts"]) / len(c["pts"])
        wpx = (max(q[0] for q in c["pts"]) - min(q[0] for q in c["pts"])) * k
        if wpx > 13:
            o.append('<text x="%.1f" y="%.1f" font-size="10" font-weight="600" text-anchor="middle" fill="%s" fill-opacity=".8">%s</text>'
                     % ((cx - x0 + pad) * k, (y1 - cy + pad) * k + 3.5, INK, SHORT[c["c"]]))
    for bl in p["blocks"]:
        o.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="1.2"/>' % (T(bl["pts"]), LIFT if bl["k"] == "lift" else STAIR, INK))
    a = math.radians(p["north_deg"]); nx, ny = width - 46, 40
    o.append('<g transform="translate(%d,%d) rotate(%.1f)"><circle r="17" fill="none" stroke="#C5A56A" stroke-opacity=".6"/>'
             '<path d="M0,-12 L5,7 L0,3 L-5,7 Z" fill="#C5A56A"/></g><text x="%d" y="%d" font-size="11" fill="#C5A56A" text-anchor="middle">N</text>'
             % (nx, ny, -p["north_deg"], nx + 26 * math.sin(-a), ny - 26 * math.cos(-a) + 4))
    o.append("</svg>")
    return "\n".join(o)


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__B__ - level __F__</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>body{margin:0;background:#0B1412;color:#E8E4D8;font-family:"IBM Plex Mono",monospace;display:flex;justify-content:center;padding:18px}
.card{width:100%;max-width:520px;background:#121C19;border:1px solid rgba(197,165,106,.32);border-radius:14px;padding:16px 17px;box-sizing:border-box}
.t{color:#C5A56A;font-size:.56rem;letter-spacing:.12em;text-transform:uppercase}h2{margin:2px 0 0;font:600 1.25rem/1.2 Fraunces,Georgia,serif}
h3{margin:15px 0 9px;font:600 .55rem/1 "IBM Plex Mono",monospace;letter-spacing:.14em;text-transform:uppercase;color:#C5A56A;border-top:1px solid rgba(197,165,106,.22);padding-top:12px}
.fplate{display:block;width:100%;height:auto}.lvl{text-align:center;font-size:.68rem;letter-spacing:.2em;color:#C5A56A;margin:8px 0 2px;font-weight:600}
.leg{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;margin-top:10px;font-size:.62rem}.leg div{display:flex;align-items:center;gap:7px}
.leg i{width:11px;height:11px;border-radius:2px;flex:none}.leg span{margin-left:auto;color:#8FA39B}
.src{font-size:.52rem;color:rgba(143,163,155,.9);line-height:1.55;margin-top:11px}.pill{display:inline-block;margin-top:9px;padding:3px 9px;border-radius:99px;font-size:.55rem;letter-spacing:.08em;text-transform:uppercase;background:#C5A56A;color:#0E1613;font-weight:600}
</style><div class=card><div class=t>__B__</div><h2>Floor __F__</h2><span class=pill>homes</span>
<h3>The floor plate</h3>__SVG__<div class=lvl>LEVEL __F__</div><div class=leg>__LEG__</div>
<div class=src><b style="color:#C5A56A">Indicative layout.</b> The outline is this building's surveyed footprint; how many homes of each type the floor carries, and their
sizes against each other, are the Land Department register's. Where each home sits, and where the lifts and stairs are, is not published for this building -
that comes from a Revit model or the developer's stacking plan, as on The Symphony. No unit numbers are shown until the units register supplies them.</div></div>"""


if __name__ == "__main__":
    district, fid, floor = sys.argv[1], sys.argv[2], int(sys.argv[3])
    p = build(district, fid, floor)
    out = os.path.join(ROOT, "data", "stack"); os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, "plate_%s_%s_%d" % (district, fid, floor))
    json.dump(p, open(stem + ".json", "w", encoding="utf-8"))
    s = svg(p); open(stem + ".svg", "w", encoding="utf-8").write(s)
    leg = "".join('<div><i style="background:%s"></i>%s<span>%d</span></div>' % (COL[c["c"]], NAME[c["c"]], c["n"]) for c in p["counts"])
    leg += '<div><i style="background:%s"></i>Lifts<span>%d</span></div><div><i style="background:%s"></i>Stairs</div>' % (LIFT, p["lifts"], STAIR)
    html = PAGE.replace("__SVG__", s).replace("__LEG__", leg).replace("__B__", p["building"]).replace("__F__", str(floor))
    open(stem + ".html", "w", encoding="utf-8").write(html)
    print("%s level %d: %s homes drawn (%s), %d blocks; cells are %.2fx their registered size to fill the plate -> %s.html"
          % (p["building"], floor, len(p["cells"]), ", ".join("%d %s" % (c["n"], NAME[c["c"]]) for c in p["counts"]), len(p["blocks"]), p["scale_note"], stem))
