"""render_ev_map.py -- Azimuth EV charging map. Real Dubai streets (offline OSM basemap) + charge points.

The 2D track of the Azimuth EV app. Same stack as render_heatmap.py: fully offline, no tiles, no API
key, no watermark, commercial-safe (OSM ODbL, attribution shown). Reads `v_ev_charge_points`
(build_ev_union.py) and writes public/ev_map_*.png.

Two things this map refuses to do, both because the data will not support them:

1. It never claims to show Dubai's charging network. DEWA published 2,223 charge points for Q1 2026;
   this layer holds 308. The subtitle carries the real coverage so the picture cannot be read as
   complete. See docs/DDA_PRODUCTION_CREDENTIALS_REQUEST_17SEP2026.md for why.

2. It never merges the two sources into one undifferentiated dot. The DEWA rows come from a
   government register, the OpenChargeMap rows are community-contributed, and
   GOV_DATA_METHODOLOGY.md does not let those carry the same weight. Register points are drawn as
   filled markers, community points as hollow ones, and the legend says which is which.

Marker size is connector count, colour is charging class (archetype).

    python scripts/render_ev_map.py                 # both crops
    python scripts/render_ev_map.py --square        # 1:1 only
    python scripts/render_ev_map.py --bbox dubai    # dubai | uae
"""
import argparse, os, sys

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import geopandas as gpd
from pyproj import Transformer

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ASSETS = os.path.join(ROOT, "assets", "dubai_basemap.gpkg")
PUB = os.path.join(ROOT, "public")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")

# House palette (render_heatmap.py).
INK, GROUND, TEAL, GOLD, HOT, CREAM, MUT = "#0C1413", "#0B1F1D", "#3E8A7E", "#C5A56A", "#EFD9A7", "#EDE7D6", "#8fa39f"
WATER = "#0A1A22"

FONT_DIR = os.path.join(ROOT, "assets", "fonts")
F_TITLE = F_BODY = None
try:
    from matplotlib import font_manager
    for _f in ("Fraunces-SemiBold.ttf", "IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf"):
        font_manager.fontManager.addfont(os.path.join(FONT_DIR, _f))
    F_TITLE, F_BODY = "Fraunces", "IBM Plex Sans"
    matplotlib.rcParams["font.family"] = F_BODY
except Exception as _e:
    print(f"WARNING: brand fonts not loaded ({_e}); rendering with matplotlib defaults")

ROAD_STYLE = {"motorway": ("#2A4742", 2.2), "trunk": ("#2A4742", 1.9), "primary": ("#22403B", 1.4),
              "secondary": ("#1C3833", 0.9), "tertiary": ("#183430", 0.5), "residential": ("#152E2A", 0.25)}

# Charging class -> colour and label. Ordered slowest to fastest; gold/hot reserved for the fast end
# so the eye lands on the DC rapid sites, which are the scarce, planning-relevant ones.
ARCHETYPE = [
    ("wallbox_ac",     "#2F6F66", "Wall-box 22 kW AC"),
    ("public_ac_dual", "#6FC3B0", "Public 2x22 kW AC"),
    ("fast_dc",        "#D9913F", "Fast 43-90 kW DC"),
    ("ultra_fast_dc",  HOT,       "Ultra-fast 150 kW+ DC"),
]
ACOL = {k: c for k, c, _ in ARCHETYPE}

# lon_min, lat_min, lon_max, lat_max
BBOX = {"dubai": (54.85, 24.75, 55.65, 25.40), "uae": (54.80, 24.60, 56.40, 25.60)}


def load():
    con = duckdb.connect(DB, read_only=True)
    df = con.execute("""select longitude, latitude, totalnbofconnectors, archetype, authority,
                               source, location_name
                        from v_ev_charge_points""").fetchdf()
    con.close()
    return df


def render(df, W, H, out, bbox):
    tf = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    lo0, la0, lo1, la1 = BBOX[bbox]
    bx0, by0 = tf.transform(lo0, la0)
    bx1, by1 = tf.transform(lo1, la1)

    # Fit the requested aspect around the bbox centre without cropping any of it.
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    want = H / W
    have = (by1 - by0) / (bx1 - bx0)
    if have < want:                      # too short: grow vertically
        halfh = (bx1 - bx0) * want / 2
        by0, by1 = cy - halfh, cy + halfh
    else:                                 # too tall: grow horizontally
        halfw = (by1 - by0) / want / 2
        bx0, bx1 = cx - halfw, cx + halfw

    roads = gpd.read_file(ASSETS, layer="roads").to_crs(3857).cx[bx0:bx1, by0:by1]
    water = gpd.read_file(ASSETS, layer="water").to_crs(3857).cx[bx0:bx1, by0:by1]

    DPI = 200
    fig, ax = plt.subplots(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(INK)
    ax.set_xlim(bx0, bx1); ax.set_ylim(by0, by1); ax.axis("off"); ax.set_position([0, 0, 1, 1])
    ax.add_patch(Rectangle((bx0, by0), bx1 - bx0, by1 - by0, facecolor=GROUND, zorder=0))
    if len(water): water.plot(ax=ax, color=WATER, zorder=1, linewidth=0)
    for fc, (col, lw) in ROAD_STYLE.items():
        seg = roads[roads["fclass"].str.startswith(fc)]
        if len(seg): seg.plot(ax=ax, color=col, linewidth=lw, zorder=2)

    # Points. Draw slow classes first so the rapid sites sit on top and stay readable in a cluster.
    drawn = 0
    for key, col, _lab in ARCHETYPE:
        for auth, filled in (("community", False), ("register", True)):
            sel = df[(df["archetype"] == key) & (df["authority"] == auth)]
            if not len(sel): continue
            xs, ys = [], []
            for lon, lat in zip(sel["longitude"], sel["latitude"]):
                x, y = tf.transform(float(lon), float(lat))
                if bx0 < x < bx1 and by0 < y < by1:
                    xs.append(x); ys.append(y)
            if not xs: continue
            drawn += len(xs)
            size = 14 + 9 * sel["totalnbofconnectors"].fillna(1).clip(upper=6).to_numpy()[:len(xs)]
            if filled:
                ax.scatter(xs, ys, s=size, c=col, zorder=6, edgecolors=INK, linewidths=0.5, alpha=0.95)
            else:
                ax.scatter(xs, ys, s=size, facecolors="none", zorder=5, edgecolors=col,
                           linewidths=0.9, alpha=0.9)

    n_reg = int((df["authority"] == "register").sum())
    n_com = int((df["authority"] == "community").sum())
    conn = int(df["totalnbofconnectors"].fillna(0).sum())

    # Scrim behind the masthead: a point landing under the title made the subtitle unreadable at the
    # top-right on the first render. Drawn in figure space so it covers whatever the map puts there.
    fig.patches.append(Rectangle((0, 0.905), 1.0, 0.095, transform=fig.transFigure,
                                 facecolor=INK, alpha=0.82, zorder=9, linewidth=0))
    fig.text(0.055, 0.958, "Dubai — where you can charge", color=CREAM, fontsize=18,
             fontweight=600, fontfamily=F_TITLE, zorder=10)
    fig.text(0.055, 0.933, f"{len(df)} charge points · {conn} connectors · a documented subset of "
                           f"DEWA's 2,223 (Q1 2026)", color=GOLD, fontsize=10, zorder=10)

    # Legend: charging class, then the provenance distinction. Both matter; neither is decoration.
    handles = [Line2D([], [], marker="o", linestyle="none", markersize=6, markerfacecolor=c,
                      markeredgecolor=INK, label=lab) for _k, c, lab in ARCHETYPE]
    handles += [
        Line2D([], [], marker="o", linestyle="none", markersize=6, markerfacecolor=MUT,
               markeredgecolor=INK, label=f"DEWA register ({n_reg})"),
        Line2D([], [], marker="o", linestyle="none", markersize=6, markerfacecolor="none",
               markeredgecolor=MUT, label=f"OpenChargeMap, community ({n_com})"),
    ]
    leg = ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.045, 0.055),
                    frameon=True, fontsize=7.5, labelcolor=CREAM, handletextpad=0.7,
                    borderpad=0.8, labelspacing=0.55)
    leg.get_frame().set_facecolor(INK); leg.get_frame().set_edgecolor("#1C3833")
    leg.get_frame().set_alpha(0.88); leg.set_zorder(8)

    fig.text(0.945, 0.014, "AZIMUTH", color=GOLD, fontsize=11, fontweight=600, ha="right")
    fig.text(0.055, 0.014 + 54.0 / H, "Sources: DEWA EV Green Charger via Dubai Pulse (staging);",
             color=MUT, fontsize=7)
    fig.text(0.055, 0.014 + 27.0 / H, "OpenChargeMap contributors (CC-BY-SA), community-reported",
             color=MUT, fontsize=7)
    fig.text(0.055, 0.014, "© OpenStreetMap contributors", color=MUT, fontsize=7)

    fig.savefig(out, dpi=DPI, facecolor=INK, pad_inches=0)
    plt.close(fig)
    print(f"wrote {out} ({drawn} points in frame)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", default="dubai", choices=sorted(BBOX))
    ap.add_argument("--square", action="store_true", help="1:1 only")
    ap.add_argument("--story", action="store_true", help="9:16 only")
    a = ap.parse_args()
    df = load()
    print(f"{len(df)} charge points from v_ev_charge_points")
    os.makedirs(PUB, exist_ok=True)
    both = not (a.square or a.story)
    if a.square or both:
        render(df, 1440, 1440, os.path.join(PUB, "ev_map_square.png"), a.bbox)
    if a.story or both:
        render(df, 1080, 1920, os.path.join(PUB, "ev_map_story.png"), a.bbox)


if __name__ == "__main__":
    main()
