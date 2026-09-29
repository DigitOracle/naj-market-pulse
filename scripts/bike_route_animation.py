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
SPLIT_M = 1000.0       # tracks of one RTA route more than this apart are different places: separate clips
MIN_PIECE_M = 100.0    # drop a piece shorter than this
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


KEEP_CAPS = {"DAMAC", "JVC", "JLT", "JBR", "DIFC", "DIP", "DIC", "II", "III"}


def _tidy(label):
    """'Al KHAWANEEJ DISTRICT' -> 'Al Khawaneej District'; keeps DAMAC, JLT and the like."""
    return " ".join(w if w in KEEP_CAPS or not w.isupper() or len(w) <= 1 else w.title() for w in label.split())


def display_names():
    """comm_num -> the name people know, as the Najma maps show it (Kendall, 29 Sep: "the names need to be
    recognizable, of the districts, similar to maps in najma").

    First the Najma map's own district names (data/board/district_communities.json: Marsa Dubai -> "Dubai Marina",
    DM 598 -> "Dubai Investments Park"); then a short hand list (COMMON); then the DM name as people write it
    (common_name: Jumeira First -> "Jumeirah 1")."""
    names = {}
    path = os.path.join(ROOT, "data", "board", "district_communities.json")
    if os.path.exists(path):
        for slug, v in json.load(open(path, encoding="utf-8"))["districts"].items():
            for n in v["comm_nums"]:
                names.setdefault(n, v["name"])
    # The residents page's labels were tried and dropped: many are a project's name, not the area's ("Dubai Hills -
    # Lambourghini" for Al Bada', "Site A" for Al Safouh Second). A short hand list instead, then tidied DM names.
    for n, v in COMMON.items():
        names.setdefault(n, v)
    return names


COMMON = {382: "Dubai Internet City", 381: "Palm Jumeirah", 347: "Sobha Hartland", 383: "Barsha Heights",
          394: "Emirates Living", 343: "Al Wasl"}


def common_name(dm_name):
    """How people write a DM community name: JUMEIRA FIRST -> Jumeirah 1, AL QOUZ THIRD -> Al Quoz 3."""
    n = re.sub(r"'([A-Z])", lambda m: "'" + m.group(1).lower(), dm_name.title())
    for a, b in (("First", "1"), ("Second", "2"), ("Third", "3"), ("Fourth", "4"), ("Fifth", "5"),
                 ("Jumeira ", "Jumeirah "), ("Qouz", "Quoz"), ("Mushraif", "Mushrif"), ("Khwaneej", "Khawaneej"),
                 ("Warqa'a", "Warqa"), ("Safouh", "Sufouh"), ("Yalayis", "Yelayiss"), ("Bada'", "Bada'a"), ("Ind.", "Industrial")):
        n = re.sub(r"\b%s\b" % re.escape(a) if a[-1].isalnum() else re.escape(a), b, n)
    return n


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
            nm = disp.get(c.comm_num) or common_name(c.name_en)
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
    for _ in range(50):                                   # Windows refuses the swap while another render reads it
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            time.sleep(0.2)


def clips(g, disp=None):
    """clip name -> (RTA route name, row index list). A route whose tracks lie more than SPLIT_M apart is split.

    Kendall, 29 Sep, on the Jumeirah clip: "Why did you mix these two? These are different areas." RTA files an
    inland loop in Al Merkadh under "Cycle Track - Jumeirah", and the Expo Route and Al Qudra likewise have pieces
    kilometres apart, so grouping by RTA's name had the dot glide across the city. The largest piece keeps RTA's
    name; every other piece is its own clip, named after the neighbourhood holding most of it."""
    m = g.to_crs(32640)
    disp = disp or display_names()
    comm = gpd.read_file(os.path.join(ROOT, "data", "board", "communities.geojson")).to_crs(32640)
    out = {}
    for route, sub in m.groupby("route"):
        if route == "Unnamed":
            continue
        idx = list(sub.index)
        pts = [np.vstack([np.array(l.coords) for l in getattr(geom, "geoms", [geom])]) for geom in sub.geometry]
        parent = list(range(len(idx)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(idx)):
            for j in range(i + 1, len(idx)):
                A, B = pts[i], pts[j]
                if np.sqrt(((A[:, None, :] - B[None, :, :]) ** 2).sum(-1)).min() <= SPLIT_M:
                    parent[find(i)] = find(j)
        groups = {}
        for i in range(len(idx)):
            groups.setdefault(find(i), []).append(idx[i])
        pieces = sorted(groups.values(), key=lambda ix: -m.loc[ix].length_m.sum())
        for k, ix in enumerate(pieces):
            if m.loc[ix].length_m.sum() < MIN_PIECE_M:
                continue                                       # a stray of a few metres is not a route
            if k == 0:
                name = route
            else:
                line = m.loc[ix].geometry.union_all()
                best = max(comm.itertuples(), key=lambda c: c.geometry.intersection(line).length)
                name = disp.get(best.comm_num) or common_name(best.name_en)
                if name in out or name == route:
                    name = "%s (%s)" % (name, route)
            out[name] = (route, ix)
    return out


def main():
    if "--list" in sys.argv:
        g = gpd.read_file(os.path.join(BIKE, "rta_bicycle_tracks_20251121.geojson"))
        for name, (rta, ix) in sorted(clips(g).items(), key=lambda kv: -g.loc[kv[1][1]].length_m.sum()):
            print("%s\t%s\t%.1f" % (name, rta, g.loc[ix].length_m.sum() / 1000))
        return
    route = arg("--route", "Saih Al Salam")
    seconds = float(arg("--seconds", "20"))
    g = gpd.read_file(os.path.join(BIKE, "rta_bicycle_tracks_20251121.geojson"))
    table = clips(g)
    if route not in table:
        sys.exit("no clip %r; clips: %s" % (route, sorted(table)))
    rta_route, ix = table[route]
    sel = g.loc[ix].to_crs(3857)
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
    fig.text(0.06, 0.918, "Cycle track \u00b7 RTA's published layer" + ("" if rta_route == route else
             " \u00b7 filed by RTA under \"%s\"" % rta_route), color=MUTED, fontsize=25 if rta_route == route else 21,
             va="top")
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
