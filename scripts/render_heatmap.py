"""Najma heat map — real Dubai streets (offline OSM basemap) + sales-density heat.
Fully offline: no tiles, no API key, no watermark. Commercial-safe (OSM ODbL, attribution shown).
Reads public/pulse.json areaIntel; writes public/heatmap_story.png (9:16) + heatmap_square.png (1:1)."""
import json, os, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from scipy.stats import gaussian_kde
import geopandas as gpd
from pyproj import Transformer

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "dubai_basemap.gpkg")
PUB = os.path.join(os.path.dirname(__file__), "..", "public")
INK, GROUND, TEAL, GOLD, HOT, CREAM, MUT = "#0C1413", "#0B1F1D", "#0F5A54", "#C9A24B", "#F5D27A", "#EDE7D6", "#8fa39f"

COORDS = {'business bay':[55.264,25.186],'jumeirah village circle':[55.207,25.058],'downtown dubai':[55.276,25.194],'dubai marina':[55.138,25.080],'palm jumeirah':[55.138,25.112],'jumeirah lakes towers':[55.141,25.069],'dubai hills estate':[55.246,25.104],'arjan':[55.243,25.055],'al furjan':[55.145,25.026],'dubai south':[55.161,24.896],'madinat al mataar':[55.16,24.90],'city of arabia':[55.30,25.13],'jumeirah village triangle':[55.19,25.05],'damac hills':[55.25,25.03],'dubai creek harbour':[55.34,25.20],'meydan':[55.30,25.16],'town square':[55.28,25.02],'sobha hartland':[55.30,25.18],'majan':[55.26,25.07],'dubai land residence complex':[55.28,25.06],'al barsha':[55.20,25.11],'deira':[55.32,25.27],'jabal ali first':[55.13,25.00],'wadi al safa 5':[55.30,25.07]}
ROAD_STYLE = {'motorway':( "#2A4742",2.2),'trunk':("#2A4742",1.9),'primary':("#22403B",1.4),'secondary':("#1C3833",0.9),'tertiary':("#183430",0.5),'residential':("#152E2A",0.25)}

def load():
    d = json.load(open(os.path.join(PUB, "pulse.json"), encoding="utf-8"))
    sales = {a["area"].lower(): a["sales"] for a in d["areaIntel"]["areas"]}
    return [(COORDS[k][0], COORDS[k][1], sales.get(k, 0), k) for k in COORDS if sales.get(k, 0) > 0]

def render(pts, W, H, out, grid):
    tf = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    xs = np.array([tf.transform(p[0], p[1])[0] for p in pts]); ys = np.array([tf.transform(p[0], p[1])[1] for p in pts]); ws = np.array([p[2] for p in pts], float)
    cx0, cy = tf.transform(55.235, 25.09)   # centre on the built-up corridor
    span = 34000 if H >= W else 30000
    ar = H / W
    bx0, bx1 = cx0 - span, cx0 + span
    by0, by1 = cy - span * ar, cy + span * ar
    roads = gpd.read_file(ASSETS, layer="roads").to_crs(3857).cx[bx0:bx1, by0:by1]
    water = gpd.read_file(ASSETS, layer="water").to_crs(3857).cx[bx0:bx1, by0:by1]
    DPI = 200
    fig, ax = plt.subplots(figsize=(W/DPI, H/DPI), dpi=DPI); fig.patch.set_facecolor(INK)
    ax.set_xlim(bx0, bx1); ax.set_ylim(by0, by1); ax.axis("off"); ax.set_position([0, 0, 1, 1])
    ax.add_patch(Rectangle((bx0, by0), bx1-bx0, by1-by0, facecolor=GROUND, zorder=0))
    if len(water): water.plot(ax=ax, color="#0A1A22", zorder=1, linewidth=0)
    for fc, (col, lw) in ROAD_STYLE.items():
        seg = roads[roads["fclass"].str.startswith(fc)]
        if len(seg): seg.plot(ax=ax, color=col, linewidth=lw, zorder=2)
    gx, gy = np.mgrid[bx0:bx1:complex(0, grid), by0:by1:complex(0, int(grid*ar))]
    kde = gaussian_kde(np.vstack([xs, ys]), weights=ws); kde.set_bandwidth(kde.factor * 0.5)
    z = kde(np.vstack([gx.ravel(), gy.ravel()])).reshape(gx.shape).T; z = z / z.max()
    z = np.where(z < 0.07, np.nan, z)
    heat = LinearSegmentedColormap.from_list("h", [(0.0,(0.06,0.35,0.33,0.0)),(0.22,(0.06,0.35,0.33,0.5)),(0.55,(0.243,0.541,0.494,0.82)),(0.78,GOLD),(1.0,HOT)])
    ax.imshow(z, extent=(bx0, bx1, by0, by1), origin="lower", cmap=heat, zorder=5, interpolation="bilinear")
    placed = []
    for p in sorted(pts, key=lambda q:-q[2]):
        x, y = tf.transform(p[0], p[1])
        if not (bx0 < x < bx1 and by0 < y < by1): continue
        ax.scatter([x], [y], s=15, c=HOT, zorder=6, edgecolors=INK, linewidths=0.6)
        if len(placed) >= 6: continue
        if any(abs(x-px) < span*0.28 and abs(y-py) < span*0.06 for px, py in placed): continue
        ax.text(x, y + span*0.022, p[3].title(), color=CREAM, fontsize=8.5, ha="center", va="bottom", zorder=7, fontweight="bold")
        placed.append((x, y))
    fig.text(0.055, 0.958, "Dubai — where it's trading", color=CREAM, fontsize=18, fontweight="bold")
    fig.text(0.055, 0.933, "Registered sales density by community", color=GOLD, fontsize=11.5)
    fig.text(0.945, 0.014, "NAJMA نجمة", color=GOLD, fontsize=11, fontweight="bold", ha="right")
    fig.text(0.055, 0.014, "Source: Dubai Land Department (DLD) Open Data  ·  © OpenStreetMap contributors", color=MUT, fontsize=7)
    fig.savefig(out, dpi=DPI, facecolor=INK, pad_inches=0); plt.close(fig)
    print("wrote", out)

if __name__ == "__main__":
    pts = load()
    render(pts, 1080, 1920, os.path.join(PUB, "heatmap_story.png"), 300)
    render(pts, 1080, 1080, os.path.join(PUB, "heatmap_square.png"), 320)
