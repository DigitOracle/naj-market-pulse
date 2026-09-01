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
INK, GROUND, TEAL, GOLD, HOT, CREAM, MUT = "#0C1413", "#0B1F1D", "#3E8A7E", "#C5A56A", "#EFD9A7", "#EDE7D6", "#8fa39f"

# Brand fonts (assets/fonts). Falls back to matplotlib defaults if the TTFs are missing.
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
F_TITLE = F_BODY = None
try:
    from matplotlib import font_manager
    for _f in ("Fraunces-SemiBold.ttf", "IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf"):
        font_manager.fontManager.addfont(os.path.join(FONT_DIR, _f))
    F_TITLE, F_BODY = "Fraunces", "IBM Plex Sans"
    matplotlib.rcParams["font.family"] = F_BODY
except Exception as _e:
    print(f"WARNING: brand fonts not loaded ({_e}); rendering with matplotlib defaults")

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
    # --- dots first (all of them), then greedy label placement against dots + placed labels ---
    upx = (bx1 - bx0) / W                       # data units per output pixel
    lab_fs = 8.5
    ch_w = lab_fs * DPI / 72 * 0.52 * upx       # est. glyph advance, data units
    ch_h = lab_fs * DPI / 72 * 1.10 * upx       # est. line height, data units
    dot_r = 7 * upx                             # clearance radius around a marker
    dots = []
    for p in pts:
        x, y = tf.transform(p[0], p[1])
        if not (bx0 < x < bx1 and by0 < y < by1): continue
        ax.scatter([x], [y], s=15, c=HOT, zorder=6, edgecolors=INK, linewidths=0.6)
        dots.append((x, y, p[2], p[3]))
    def rect(lx, ly, w, h, ha, va):
        x0 = lx - w if ha == "right" else lx - w / 2 if ha == "center" else lx
        y0 = ly - h if va == "top" else ly - h / 2 if va == "center" else ly
        return (x0, y0, x0 + w, y0 + h)
    placed = []                                 # bboxes of labels already placed
    def clashes(r):
        pad = 3 * upx
        if any(r[0] - pad < px1 and r[2] + pad > px0 and r[1] - pad < py1 and r[3] + pad > py0
               for px0, py0, px1, py1 in placed): return True
        return any(r[0] - dot_r < dx < r[2] + dot_r and r[1] - dot_r < dy < r[3] + dot_r
                   for dx, dy, _, _ in dots)
    for x, y, _, name in sorted(dots, key=lambda d: -d[2]):
        if len(placed) >= 6: break
        txt = name.title(); tw, th = len(txt) * ch_w, ch_h; off = 14 * upx
        for i, (lx, ly, ha, va) in enumerate([(x, y + off, "center", "bottom"), (x, y - off, "center", "top"),
                                              (x + off, y, "left", "center"), (x - off, y, "right", "center")]):
            r = rect(lx, ly, tw, th, ha, va)
            if not (bx0 < r[0] and r[2] < bx1 and by0 < r[1] and r[3] < by1) or clashes(r): continue
            ax.text(lx, ly, txt, color=CREAM, fontsize=lab_fs, ha=ha, va=va, zorder=7, fontweight=600)
            if i > 0:  # displaced from the default slot — subtle 1px leader from dot to label
                exy = {1: ((x, y - dot_r), (x, ly + 2 * upx)), 2: ((x + dot_r, y), (lx - 2 * upx, y)),
                       3: ((x - dot_r, y), (lx + 2 * upx, y))}[i]
                ax.plot([exy[0][0], exy[1][0]], [exy[0][1], exy[1][1]], color=MUT, linewidth=72 / DPI, alpha=0.8, zorder=6, solid_capstyle="round")
            placed.append(r)
            break
    fig.text(0.055, 0.958, "Dubai — where it's trading", color=CREAM, fontsize=18, fontweight=600, fontfamily=F_TITLE)
    fig.text(0.055, 0.933, "Registered sales density by community", color=GOLD, fontsize=11.5)
    # Wordmark latin-only: IBM Plex Sans carries no Arabic glyphs (نجمة would render as tofu).
    fig.text(0.945, 0.014, "NAJMA", color=GOLD, fontsize=11, fontweight=600, ha="right")
    # Source credit stacked in two short lines so it can never run under the wordmark.
    fig.text(0.055, 0.014 + 27.0 / H, "Source: Dubai Land Department (DLD) Open Data", color=MUT, fontsize=7)
    fig.text(0.055, 0.014, "© OpenStreetMap contributors", color=MUT, fontsize=7)
    fig.savefig(out, dpi=DPI, facecolor=INK, pad_inches=0); plt.close(fig)
    print("wrote", out)

if __name__ == "__main__":
    pts = load()
    render(pts, 1080, 1920, os.path.join(PUB, "heatmap_story.png"), 300)
    render(pts, 1080, 1080, os.path.join(PUB, "heatmap_square.png"), 320)
