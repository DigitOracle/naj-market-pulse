"""One cycle route, drawn by a travelling dot - 9:16 video in the cycle-track map's style.

Kendall, 29 Sep 2026: "show only the first one and then we show a little dot that goes around it". The first route
on the map is the longest, Saih Al Salam (113 km on RTA's layer).

RTA's tracks are unordered segments that mostly meet mid-segment, so they do not chain end to end. They are joined
into one track graph (segments whose nearest vertices lie within JOIN_M are linked there), and the dot runs it
depth-first: every stretch is drawn in gold the first time the dot rides it, and at a dead end the dot rides back
along its own gold (faster) to the last branch. So the gold is always one continuous line ending at the dot - Kendall,
29 Sep: "it should go on like a continuous thread". The counter adds only RTA track (not the short joins, not the
ride back) and ends on the route's stated length.

    python scripts/bike_route_animation.py [--route "Saih Al Salam"] [--seconds 20]
Writes data/bike/route_<slug>_9x16.mp4 (1080x1920, 25 fps, silent).
"""
import json
import textwrap
import time
import math
import os
import re
import subprocess
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from shapely.geometry import box

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIKE = os.path.join(ROOT, "data", "bike")
BG, FG, MUTED, GOLD, FAINT = "#0e1116", "#f2f4f7", "#9aa3ad", "#C5A56A", "#3a4452"
W, H, FPS = 1080, 1920, 25
JOIN_M = 60.0          # two segments whose nearest vertices are within this are joined there
RETRACE_PACE = 0.3     # track already drawn is ridden ~3x faster, so the film spends its time on new track
INTRO_S, HOLD_S = 1.5, 3.0
MIN_HALF_M = 2600.0    # never frame tighter than ~5 km across, so a short route still shows its neighbourhoods
LABEL_SHARE = 0.03     # name a neighbourhood holding at least 3% of the route


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def build_graph(segs):
    """Nodes = every vertex (projected metres); edges = consecutive vertices, plus junction links.

    Tracks cross or touch partway along, not only at their ends (Saih Al Salam's one "separate" piece passes 22 m
    from the main loop mid-segment), so any vertex within JOIN_M of a vertex on another segment is joined to the
    nearest one there. link[] marks those joins: ridden and drawn for continuity, never counted as track."""
    nodes, seg_nodes, seg_of = [], [], []
    for si, s in enumerate(segs):
        ids = []
        for p in s:
            ids.append(len(nodes))
            nodes.append(p)
            seg_of.append(si)
        seg_nodes.append(ids)
    P = np.array(nodes)
    seg_of = np.array(seg_of)
    adj = [[] for _ in nodes]

    def link(a, b, is_join):
        d = float(np.hypot(*(P[a] - P[b])))
        adj[a].append((b, d, is_join))
        adj[b].append((a, d, is_join))

    for ids in seg_nodes:
        for a, b in zip(ids, ids[1:]):
            link(a, b, False)
    for si, ids in enumerate(seg_nodes):
        for sj in range(si + 1, len(seg_nodes)):
            A, B = P[ids], P[seg_nodes[sj]]
            d = np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1])
            ia, ib = np.unravel_index(np.argmin(d), d.shape)
            if d[ia, ib] <= JOIN_M:
                link(ids[ia], seg_nodes[sj][ib], True)
    return P, seg_nodes, adj


def plan_walk(P, seg_nodes, adj):
    """[(node_id, is_new, is_join)] - a depth-first run over the track graph from its westmost end.

    Kendall, 29 Sep: the line must be one continuous run. The first version joined segments by shortest paths that
    crossed track it had not drawn yet, so the gold appeared in fragments ahead of the dot. Now every edge is drawn
    the first time the dot rides it, and at a dead end the dot rides back along its own gold to the last branch, so
    what is drawn is always one connected line ending at the dot.

    Some routes really are separate pieces - the Dubai Canal track runs on both banks, more than JOIN_M apart. There
    the dot finishes one piece and glides, drawing nothing, straight to the nearest point of the next; returns the
    number of such crossings."""
    seen_edge, seen_node = set(), set()
    walk, crossings = [], 0
    cur = None
    while len(seen_node) < len(P):
        rest = np.array([i for i in range(len(P)) if i not in seen_node])
        if cur is None:
            start = int(rest[np.argmin(P[rest, 0])])                       # westmost point of the route
        else:
            start = int(rest[np.argmin(np.hypot(*(P[rest] - P[cur]).T))])   # nearest point of the next piece
            walk.append((start, False, False))                              # the glide: no gold
            crossings += 1
        seen_node.add(start)
        if cur is None:
            walk.append((start, True, False))
        stack = [start]
        while stack:
            u = stack[-1]
            nxt = None
            for v, d, j in sorted(adj[u], key=lambda e: e[1]):
                if (min(u, v), max(u, v)) not in seen_edge and v not in seen_node:
                    nxt = (v, j)
                    break
            if nxt:
                v, j = nxt
                seen_edge.add((min(u, v), max(u, v)))
                seen_node.add(v)
                walk.append((v, True, j))
                stack.append(v)
            else:
                stack.pop()
                if stack:
                    walk.append((stack[-1], False, False))          # back along drawn track
        cur = walk[-1][0]
    return walk, crossings


def display_names():
    """comm_num -> the name people use: the app district's name where the community is one (Dubai Marina, not Marsa
    Dubai), else the DM name in title case."""
    names = {}
    path = os.path.join(ROOT, "data", "board", "district_communities.json")
    if os.path.exists(path):
        for slug, v in json.load(open(path, encoding="utf-8"))["districts"].items():
            for n in v["comm_nums"]:
                names.setdefault(n, v["name"])
    return names


def neighbourhoods(sel, comm):
    """The DM communities the route runs through, with the share of its track in each, longest first."""
    line = sel.geometry.union_all()
    total = line.length
    disp = display_names()
    out = []
    for _, c in comm.iterrows():
        if not c.geometry.intersects(line):
            continue
        share = c.geometry.intersection(line).length / total
        if share > 0.005:
            nm = disp.get(c.comm_num) or c.name_en.title().replace("'S", "'s")
            out.append({"comm_num": int(c.comm_num), "dm_name": c.name_en, "name": nm, "share": round(share, 3)})
    return sorted(out, key=lambda h: -h["share"])


def record_neighbourhoods(route, km, hoods):
    """data/bike/route_neighbourhoods.json - for the narrative: which neighbourhoods each route passes through."""
    path = os.path.join(BIKE, "route_neighbourhoods.json")
    for _ in range(20):                                   # renders run in parallel: retry a half-written read
        try:
            doc = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
            break
        except ValueError:
            time.sleep(0.2)
    else:
        doc = {}
    doc[route] = {"km": round(km, 1), "neighbourhoods": hoods}
    tmp = path + ".%d.tmp" % os.getpid()
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    route = arg("--route", "Saih Al Salam")
    seconds = float(arg("--seconds", "20"))
    g = gpd.read_file(os.path.join(BIKE, "rta_bicycle_tracks_20251121.geojson"))
    sel = g[g.route == route].to_crs(3857)
    if sel.empty:
        sys.exit("no route %r; routes: %s" % (route, sorted(g.route.unique())))
    stated_km = sel.length_m.sum() / 1000
    segs = [list(line.coords) for geom in sel.geometry for line in getattr(geom, "geoms", [geom])]
    P, seg_nodes, adj = build_graph(segs)
    walk, jumps = plan_walk(P, seg_nodes, adj)
    last_new = max(k for k, (_, new, _) in enumerate(walk) if new)
    walk = walk[:last_new + 1]                  # the dot stops where the last new track ends - no idle retrace

    # walk -> steps with cumulative travel and cumulative NEW track
    pts, new_flags, join_flags = [], [], []
    for n, new, j in walk:
        pts.append(P[n])
        new_flags.append(new)
        join_flags.append(j)
    travel, drawn = [0.0], [0.0]
    for i in range(1, len(pts)):
        if pts[i] is None or pts[i - 1] is None:
            travel.append(travel[-1]); drawn.append(drawn[-1]); continue
        d = float(np.hypot(*(pts[i] - pts[i - 1])))
        travel.append(travel[-1] + d * (1.0 if new_flags[i] else RETRACE_PACE))   # timeline, not distance
        drawn.append(drawn[-1] + (d if new_flags[i] and not join_flags[i] else 0.0))
    total_travel, total_drawn = travel[-1], drawn[-1]
    km_scale = stated_km / (total_drawn / 1000)          # web-mercator metres -> RTA's stated km (cos-lat factor)
    print("route %s: stated %.1f km, %d segments, drawn %.1f merc-km, timeline %.1f, %d glide(s) between pieces" %
          (route, stated_km, len(segs), total_drawn / 1000, total_travel / 1000, jumps))

    # figure: land, the route faint, then gold as drawn
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.0, 0.14, 1.0, 0.70], facecolor=BG)
    comm = gpd.read_file(os.path.join(ROOT, "data", "board", "communities.geojson")).to_crs(3857)
    comm.plot(ax=ax, facecolor="#1a212b", edgecolor="#2b3441", linewidth=0.6)
    hoods = neighbourhoods(sel, comm)
    passed = comm[comm.comm_num.isin([h["comm_num"] for h in hoods])]
    passed.plot(ax=ax, facecolor="#232c38", edgecolor="#4a5566", linewidth=1.2)   # the ones the route crosses
    sel.plot(ax=ax, color=FAINT, linewidth=2.4)
    x0, y0, x1, y1 = sel.total_bounds
    cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
    aspect = 0.70 * H / W                                   # axes height / width in pixels
    half_w = max((x1 - x0) / 2, (y1 - y0) / 2 / aspect, MIN_HALF_M) * 1.12
    ax.set_xlim(cx_ - half_w, cx_ + half_w)
    ax.set_ylim(cy_ - half_w * aspect, cy_ + half_w * aspect)
    ax.set_axis_off()
    xl, yl = ax.get_xlim(), ax.get_ylim()
    for h in hoods:                                         # name each neighbourhood, inside the frame
        if h["share"] < LABEL_SHARE:
            continue
        pt = passed[passed.comm_num == h["comm_num"]].geometry.iloc[0].intersection(
            box(xl[0], yl[0], xl[1], yl[1])).representative_point()
        ax.text(pt.x, pt.y, h["name"].upper(), color="#aab4c0", fontsize=15, ha="center", va="center",
                weight="bold", alpha=0.85, zorder=3)
    trail = LineCollection([], colors=GOLD, linewidths=4.0, capstyle="round")
    ax.add_collection(trail)
    glow = ax.scatter([], [], s=900, color=GOLD, alpha=0.25, zorder=5)
    dot = ax.scatter([], [], s=170, color="#fff4d6", edgecolors=GOLD, linewidths=3, zorder=6)
    fig.text(0.06, 0.965, route, color=FG, fontsize=50, weight="bold", va="top")
    fig.text(0.06, 0.918, "Cycle track · RTA's published layer", color=MUTED, fontsize=25, va="top")
    names = [h["name"] for h in hoods if h["share"] >= LABEL_SHARE]
    fig.text(0.06, 0.885, "\n".join(textwrap.wrap("Passes through: " + " · ".join(names), 62)),
             color=FG, fontsize=20, va="top", linespacing=1.3)
    record_neighbourhoods(route, stated_km, hoods)
    counter = fig.text(0.06, 0.115, "", color=GOLD, fontsize=64, weight="bold", va="top")
    fig.text(0.06, 0.052, "Source: RTA bicycle tracks, Dubai open data portal, snapshot 21 Nov 2025. "
             "Length is RTA's own.", color=MUTED, fontsize=13)
    fig.text(0.06, 0.037, "Most tracks on this layer were last edited in 2022.", color=MUTED, fontsize=13)
    fig.text(0.06, 0.022, "Land: Dubai Municipality community boundaries.", color=MUTED, fontsize=13)

    out = os.path.join(BIKE, "route_%s_9x16.mp4" % re.sub(r"[^a-z0-9]+", "_", route.lower()).strip("_"))
    ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
                           "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18",
                           "-preset", "medium", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    n_move = int(seconds * FPS)
    frames = [0.0] * int(INTRO_S * FPS) + [(k + 1) / n_move for k in range(n_move)] + [1.0] * int(HOLD_S * FPS)
    tr = np.array(travel)
    done_segments = []
    last_i = 0
    for f in frames:
        target = f * total_travel
        i = int(np.searchsorted(tr, target, side="right")) - 1
        i = max(0, min(i, len(pts) - 1))
        for k in range(last_i + 1, i + 1):                  # add every newly drawn piece up to i
            if pts[k] is not None and pts[k - 1] is not None and new_flags[k]:
                done_segments.append([pts[k - 1], pts[k]])
        last_i = max(last_i, i)
        # the dot, interpolated between vertices (and absent mid-hop)
        here = None
        if pts[i] is not None:
            here = pts[i]
            if i + 1 < len(pts) and pts[i + 1] is not None and tr[i + 1] > tr[i]:
                t = (target - tr[i]) / (tr[i + 1] - tr[i])
                here = pts[i] + (pts[i + 1] - pts[i]) * min(max(t, 0), 1)
        trail.set_segments(done_segments)
        dot.set_offsets([here] if here is not None and f < 1.0 else np.empty((0, 2)))
        glow.set_offsets([here] if here is not None and f < 1.0 else np.empty((0, 2)))
        km = (drawn[i] / 1000) * km_scale if f < 1.0 else stated_km
        counter.set_text("%.0f km" % km)
        fig.canvas.draw()
        ff.stdin.write(np.asarray(fig.canvas.buffer_rgba()).tobytes())
    ff.stdin.close()
    ff.wait()
    print("wrote %s (%.1f s)" % (out, len(frames) / FPS))


if __name__ == "__main__":
    main()
