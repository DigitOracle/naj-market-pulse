"""Dubai's cycle tracks on one map - the RTA open-data layer, 9:16, in the live-work maps' house style.

Kendall asked for "a map of all the bike trails across Dubai", 29 Sep 2026. The DDA session pulled the layer from the
data.dubai public portal: data/raw_downloads/dda/prod/rta__rta_bicycle_tracks-open-api.kml, 291 track placemarks,
snapshot dated 21 Nov 2025 (the portal's newest). Two caveats the map carries:
  - 280 of the 291 tracks were last edited in 2022, so the layer is older than its date, and tracks built since
    may be missing. It is RTA's published layer, not a claim about the whole network on the ground.
  - Lengths are RTA's own LENGTH_IN_M; the geometry agrees (290.7 km measured vs 290.5 km stated).

    python scripts/bike_tracks_map.py
Writes data/bike/rta_bicycle_tracks_20251121.geojson and data/bike/dubai_cycle_tracks_9x16.png.
"""
import collections
import json
import math
import os
import re

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import MultiLineString

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KML = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "rta__rta_bicycle_tracks-open-api.kml")
OUT = os.path.join(ROOT, "data", "bike")
BG, FG, MUTED = "#0e1116", "#f2f4f7", "#9aa3ad"
GOLD, OTHER = "#C5A56A", "#8fb8a8"


def route_name(n):
    n = re.sub(r"\s+", " ", (n or "").strip())
    n = re.sub(r"(?i)^cycle track\s*-\s*", "", n)
    n = re.sub(r"(?i)^al qudra( cycle)? track$", "Al Qudra", n)
    n = n.title().replace("Jlt", "JLT").replace("Dic ", "DIC ").replace("2Nd ", "2nd ")
    return n or "Unnamed"


def load():
    t = open(KML, encoding="utf-8").read()
    rows = []
    for q in re.findall(r"<Placemark.*?</Placemark>", t, re.S):
        p = dict(re.findall(r'<SimpleData name="([^"]+)">([^<]*)</SimpleData>', q))
        lines = [[tuple(map(float, s.split(",")[:2])) for s in c.split()]
                 for c in re.findall(r"<coordinates>(.*?)</coordinates>", q, re.S)]
        rows.append({"route": route_name(p.get("NAME")), "length_m": float(p.get("LENGTH_IN_M") or 0),
                     "paving": p.get("PAVING_MATERIAL"), "width_m": p.get("WIDTH_IN_M"),
                     "last_edited": p.get("LAST_EDITED_DATE"), "objectid": p.get("OBJECTID"),
                     "geometry": MultiLineString(lines)})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def main():
    os.makedirs(OUT, exist_ok=True)
    g = load()
    g.to_file(os.path.join(OUT, "rta_bicycle_tracks_20251121.geojson"), driver="GeoJSON")
    total_km = g.length_m.sum() / 1000
    routes = g.groupby("route").length_m.sum().sort_values(ascending=False) / 1000
    old = sum(1 for d in g.last_edited if str(d).endswith("2022"))
    top = list(routes.index[:6])

    gm = g.to_crs(3857)
    fig = plt.figure(figsize=(10.8, 19.2), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.0, 0.25, 1.0, 0.62], facecolor=BG)
    # the land, drawn from Dubai Municipality's own community polygons - no tile service (CARTO now wants a key)
    comm = gpd.read_file(os.path.join(ROOT, "data", "board", "communities.geojson")).to_crs(3857)
    comm.plot(ax=ax, facecolor="#1a212b", edgecolor="#2b3441", linewidth=0.6)
    gm[~gm.route.isin(top)].plot(ax=ax, color=OTHER, linewidth=2.2, alpha=0.9)
    gm[gm.route.isin(top)].plot(ax=ax, color=GOLD, linewidth=3.2)
    x0, y0, x1, y1 = gm.total_bounds
    pad = (x1 - x0) * 0.06
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    for r in top:
        c = gm[gm.route == r].union_all().centroid
        right = c.x > (x0 + x1) / 2          # eastern routes are labelled to their left, so nothing runs off
        ax.annotate("%s  %.0f km" % (r, routes[r]), (c.x, c.y), xytext=(-12 if right else 12, 6),
                    textcoords="offset points", ha="right" if right else "left",
                    color=FG, fontsize=17, weight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc=BG, ec="none", alpha=0.7))
    ax.set_axis_off()

    fig.text(0.06, 0.965, "Dubai's cycle tracks", color=FG, fontsize=50, weight="bold", va="top")
    named = len([r for r in routes.index if r != "Unnamed"])
    fig.text(0.06, 0.918, "%d km on RTA's published layer, %d named routes" % (round(total_km), named),
             color=MUTED, fontsize=25, va="top")
    fig.text(0.06, 0.890, "Gold: the six longest.  Green: the other %d." % (named - len(top)),
             color=MUTED, fontsize=19, va="top")
    y = 0.225
    for r in top:
        fig.text(0.06, y, r, color=FG, fontsize=19)
        fig.text(0.60, y, "%5.0f km" % routes[r], color=GOLD, fontsize=19, weight="bold")
        y -= 0.022
    fig.text(0.06, 0.052, "Source: RTA bicycle tracks, Dubai open data portal, snapshot 21 Nov 2025 (newest published).",
             color=MUTED, fontsize=13)
    fig.text(0.06, 0.037, "%d of %d tracks were last edited in 2022, so tracks built since may be missing." % (old, len(g)),
             color=MUTED, fontsize=13)
    fig.text(0.06, 0.022, "Lengths are RTA's own. Land: Dubai Municipality community boundaries.", color=MUTED, fontsize=13)
    fig.text(0.06, 0.006, "DRAFT - internal research", color="#e0a040", fontsize=13, weight="bold")
    out = os.path.join(OUT, "dubai_cycle_tracks_9x16.png")
    fig.savefig(out, facecolor=BG)
    print("%d tracks, %.1f km, %d routes -> %s" % (len(g), total_km, len(routes), out))
    for r, km in routes.items():
        print("  %6.1f km  %s" % (km, r))


if __name__ == "__main__":
    main()
