"""One cycle route, drawn by a travelling dot - 9:16 video in the cycle-track map's style.

Kendall, 29 Sep 2026: "show only the first one and then we show a little dot that goes around it". The first route
on the map is the longest, Saih Al Salam (113 km on RTA's layer).

RTA's tracks are unordered segments that mostly meet mid-segment (T-junctions), so they do not chain end to end:
Saih Al Salam's 16 segments form 12 pieces by endpoints alone, and a greedy chain leaves gaps of up to 4.9 km. The dot
must never cross open ground, so every segment end is joined to the nearest point on the other segments (within
JOIN_M), and between segments the dot rides the shortest path along track already drawn. New track is drawn in gold
as the dot passes; the counter adds only new track, never the retrace, so it ends on the route's own length.

    python scripts/bike_route_animation.py [--route "Saih Al Salam"] [--seconds 20]
Writes data/bike/route_<slug>_9x16.mp4 (1080x1920, 25 fps, silent).
"""
import heapq
import json
import math
import os
import re
import subprocess
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIKE = os.path.join(ROOT, "data", "bike")
BG, FG, MUTED, GOLD, FAINT = "#0e1116", "#f2f4f7", "#9aa3ad", "#C5A56A", "#3a4452"
W, H, FPS = 1080, 1920, 25
JOIN_M = 60.0          # a segment end within this of another segment is a junction
RETRACE_PACE = 0.3     # track already drawn is ridden ~3x faster, so the film spends its time on new track
INTRO_S, HOLD_S = 1.5, 3.0


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def build_graph(segs):
    """Nodes = every vertex (projected metres); edges = consecutive vertices, plus junction links."""
    nodes, seg_nodes = [], []
    for s in segs:
        ids = []
        for p in s:
            ids.append(len(nodes))
            nodes.append(p)
        seg_nodes.append(ids)
    P = np.array(nodes)
    adj = [[] for _ in nodes]

    def link(a, b):
        d = float(np.hypot(*(P[a] - P[b])))
        adj[a].append((b, d))
        adj[b].append((a, d))

    for ids in seg_nodes:
        for a, b in zip(ids, ids[1:]):
            link(a, b)
    for si, ids in enumerate(seg_nodes):
        others = np.array([n for sj, o in enumerate(seg_nodes) if sj != si for n in o])
        for end in (ids[0], ids[-1]):
            d = np.hypot(*(P[others] - P[end]).T)
            k = int(np.argmin(d))
            if d[k] <= JOIN_M:
                link(end, int(others[k]))
    return P, seg_nodes, adj


def dijkstra(adj, src):
    dist, prev = {src: 0.0}, {}
    q = [(0.0, src)]
    while q:
        d, u = heapq.heappop(q)
        if d > dist.get(u, 1e18):
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v], prev[v] = nd, u
                heapq.heappush(q, (nd, v))
    return dist, prev


def path_to(prev, src, dst):
    out = [dst]
    while out[-1] != src:
        out.append(prev[out[-1]])
    return out[::-1]


def plan_walk(P, seg_nodes, adj):
    """[(node_id, is_new_track)] - the dot's route: every segment once, joined along drawn track."""
    left = set(range(len(seg_nodes)))
    first = min(left, key=lambda i: min(P[seg_nodes[i][0]][0], P[seg_nodes[i][-1]][0]))   # westmost end
    ids = seg_nodes[first]
    ids = ids if P[ids[0]][0] <= P[ids[-1]][0] else ids[::-1]
    walk = [(n, True) for n in ids]
    left.discard(first)
    jumps = 0
    while left:
        cur = walk[-1][0]
        dist, prev = dijkstra(adj, cur)
        best = None
        for i in left:
            for ids in (seg_nodes[i], seg_nodes[i][::-1]):
                if ids[0] in dist and (best is None or dist[ids[0]] < best[0]):
                    best = (dist[ids[0]], i, ids)
        if best is None:                  # unreachable along track: the dot hops (fades) to the nearest segment
            i = min(left, key=lambda i: min(np.hypot(*(P[seg_nodes[i][0]] - P[cur])),
                                            np.hypot(*(P[seg_nodes[i][-1]] - P[cur]))))
            ids = seg_nodes[i] if np.hypot(*(P[seg_nodes[i][0]] - P[cur])) <= \
                np.hypot(*(P[seg_nodes[i][-1]] - P[cur])) else seg_nodes[i][::-1]
            walk.append((None, False))
            jumps += 1
        else:
            _, i, ids = best
            walk += [(n, False) for n in path_to(prev, cur, ids[0])[1:]]
        walk += [(n, True) for n in ids[1:]] if walk[-1][0] == ids[0] else [(n, True) for n in ids]
        left.discard(i)
    return walk, jumps


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
    last_new = max(k for k, (_, new) in enumerate(walk) if new)
    walk = walk[:last_new + 1]                  # the dot stops where the last new track ends - no idle retrace

    # walk -> steps with cumulative travel and cumulative NEW track
    pts, new_flags = [], []
    for n, new in walk:
        if n is None:
            pts.append(None)
            new_flags.append(False)
        else:
            pts.append(P[n])
            new_flags.append(new)
    travel, drawn = [0.0], [0.0]
    for i in range(1, len(pts)):
        if pts[i] is None or pts[i - 1] is None:
            travel.append(travel[-1]); drawn.append(drawn[-1]); continue
        d = float(np.hypot(*(pts[i] - pts[i - 1])))
        travel.append(travel[-1] + d * (1.0 if new_flags[i] else RETRACE_PACE))   # timeline, not distance
        drawn.append(drawn[-1] + (d if new_flags[i] else 0.0))
    total_travel, total_drawn = travel[-1], drawn[-1]
    km_scale = stated_km / (total_drawn / 1000)          # web-mercator metres -> RTA's stated km (cos-lat factor)
    print("route %s: stated %.1f km, %d segments, drawn %.1f merc-km, timeline %.1f, %d hop(s)" %
          (route, stated_km, len(segs), total_drawn / 1000, total_travel / 1000, jumps))

    # figure: land, the route faint, then gold as drawn
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.0, 0.14, 1.0, 0.70], facecolor=BG)
    comm = gpd.read_file(os.path.join(ROOT, "data", "board", "communities.geojson")).to_crs(3857)
    comm.plot(ax=ax, facecolor="#1a212b", edgecolor="#2b3441", linewidth=0.6)
    sel.plot(ax=ax, color=FAINT, linewidth=2.4)
    x0, y0, x1, y1 = sel.total_bounds
    cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
    aspect = 0.70 * H / W                                   # axes height / width in pixels
    half_w = max((x1 - x0) / 2, (y1 - y0) / 2 / aspect) * 1.12
    ax.set_xlim(cx_ - half_w, cx_ + half_w)
    ax.set_ylim(cy_ - half_w * aspect, cy_ + half_w * aspect)
    ax.set_axis_off()
    trail = LineCollection([], colors=GOLD, linewidths=4.0, capstyle="round")
    ax.add_collection(trail)
    glow = ax.scatter([], [], s=900, color=GOLD, alpha=0.25, zorder=5)
    dot = ax.scatter([], [], s=170, color="#fff4d6", edgecolors=GOLD, linewidths=3, zorder=6)
    fig.text(0.06, 0.965, route, color=FG, fontsize=50, weight="bold", va="top")
    fig.text(0.06, 0.918, "Cycle track · RTA's published layer", color=MUTED, fontsize=25, va="top")
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
