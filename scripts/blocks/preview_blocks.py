"""QA preview: render a district's blocks.json as the oblique LOD 100 view (same look as make_map.py), small PNG.
python preview_blocks.py <path to blocks.json> <out.png> [title]"""
import json, math, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPoly
from matplotlib.collections import LineCollection
from pyproj import Transformer

src, out = sys.argv[1], sys.argv[2]
title = sys.argv[3] if len(sys.argv) > 3 else src
g = json.load(open(src, encoding="utf-8"))
to_utm = Transformer.from_crs(4326, 32640, always_xy=True)
KY, KH = math.sin(math.radians(50)), math.cos(math.radians(50))
BG = "#F6F4EE"


def rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


blds, sts = [], []
for f in g["features"]:
    p = f["properties"]
    if p.get("k") == "b":
        for r in rings(f["geometry"]):
            xs, ys = to_utm.transform([c[0] for c in r], [c[1] for c in r])
            blds.append((list(zip(xs, ys)), float(p.get("h") or 12), p.get("hs", "")))
    elif p.get("k") == "s" and f["geometry"]["type"] == "LineString":
        xs, ys = to_utm.transform([c[0] for c in f["geometry"]["coordinates"]], [c[1] for c in f["geometry"]["coordinates"]])
        sts.append(list(zip(xs, ys)))
if not blds:
    print("NO BUILDINGS", src); sys.exit(1)
allx = [q[0] for b in blds for q in b[0]]; ally = [q[1] for b in blds for q in b[0]]
X0, X1, Y0, Y1 = min(allx) - 100, max(allx) + 100, min(ally) - 100, max(ally) + 100
OX, OY = (X0 + X1) / 2, Y0
P = lambda x, y, h=0.0: (x - OX, (y - OY) * KY + h * KH)
fig = plt.figure(figsize=(9, 6.5), dpi=110); fig.patch.set_facecolor(BG)
ax = fig.add_axes([0.01, 0.01, 0.98, 0.9]); ax.set_facecolor(BG); ax.set_aspect("equal"); ax.axis("off")
if sts:
    L = [[P(x, y) for x, y in s] for s in sts]
    ax.add_collection(LineCollection(L, colors="#D9D5CA", linewidths=1.2, zorder=1))
    ax.add_collection(LineCollection(L, colors="white", linewidths=0.6, zorder=2))
n12 = 0
for r, h, hs in sorted(blds, key=lambda b: -min(q[1] for q in b[0])):
    area = 0.5 * sum(r[k][0] * r[k + 1][1] - r[k + 1][0] * r[k][1] for k in range(len(r) - 1))
    if area < 0: r = r[::-1]
    default = hs in ("unknown", "default12") or (abs(h - 12) < 0.01 and hs == "")
    n12 += default
    roof, wall = ("#EAD9B0", "#D2BC88") if default else ("#E9E9E4", "#D3D4CE")
    for k in range(len(r) - 1):
        (x0, y0), (x1, y1) = r[k], r[k + 1]
        if (x1 - x0) > 0:
            ax.add_patch(MPoly([P(x0, y0), P(x1, y1), P(x1, y1, h), P(x0, y0, h)], fc=wall, ec="#BFC1BA", lw=0.15, zorder=4))
    ax.add_patch(MPoly([P(x, y, h) for x, y in r], fc=roof, ec="#BFC1BA", lw=0.15, zorder=4))
ax.set_xlim(X0 - OX, X1 - OX); ax.set_ylim(-20, (Y1 - OY) * KY + max(b[1] for b in blds) * KH + 40)
fig.text(0.02, 0.95, "%s  -  %d buildings, %d streets, %d%% at default 12 m (tinted)" % (title, len(blds), len(sts),
         round(100.0 * n12 / len(blds))), fontsize=10, color="#0A4F4A", fontweight="bold")
fig.savefig(out, dpi=110, facecolor=BG); print("ok", out)
