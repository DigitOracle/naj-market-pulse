"""render_ev_archetypes.py -- one picture per charger class, drawn from our own 3D geometry.

WHY THIS EXISTS: there is no licence-clean photography of Dubai's chargers. OpenChargeMap carries
zero MediaItems across all 139 UAE sites, Wikimedia Commons has none, DEWA's own EV pages carry only
logos, and OSM has no image tags. So the app shows what a charger of each class actually looks like
by rendering the CityEngine geometry we already generate, rather than by finding a photograph.

That makes the picture honest in a way a stock photo would not be: it is the DEWA published
specification turned into massing (ultra-fast 150 kW DC, fast 43 kW AC / 50 kW DC, public 2x22 kW AC,
wall-box 22 kW AC -- the four classes DEWA gave WAM on 23 June 2026), not a photograph of some other
network's hardware standing in for Dubai's. The app labels it as generic massing, never as a photo of
that site.

Reads the OBJ that ev_cityengine.py writes, takes one representative station per archetype, and
renders it isometrically with flat Lambert shading on a transparent ground so it sits on either
theme. Output: public/ev_archetypes/<archetype>.png, inlined into the app payload by build_ev_app.py.

    python scripts/render_ev_archetypes.py
"""
import io, json, os, sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OBJ = os.path.join(ROOT, "data", "ev", "cityengine", "out", "ev_chargers_utm40n.obj")
IDX = os.path.join(ROOT, "data", "ev", "cityengine", "out", "ev_chargers_utm40n_index.json")
OUT = os.path.join(ROOT, "public", "ev_archetypes")

# The app's charging-class palette, so a rendered unit matches its dot on the map.
COLOUR = {"wallbox_ac": "#2F6F66", "public_ac_dual": "#6FC3B0",
          "fast_dc": "#D9913F", "ultra_fast_dc": "#EFD9A7"}
LABEL = {"wallbox_ac": "Wall-box 22 kW AC", "public_ac_dual": "Public 2x22 kW AC",
         "fast_dc": "Fast 43-90 kW DC", "ultra_fast_dc": "Ultra-fast 150 kW+ DC"}


def parse_obj(path):
    """-> {object_name: [ (v0,v1,v2[,v3]) ... ]}. OBJ face indices are global and 1-based."""
    verts, groups, cur = [], {}, None
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z = line.split()[:4]
                verts.append((float(x), float(y), float(z)))
            elif line.startswith("o "):
                cur = line[2:].strip(); groups[cur] = []
            elif line.startswith("f ") and cur is not None:
                idx = [int(p.split("/")[0]) for p in line.split()[1:]]
                groups[cur].append([verts[i - 1 if i > 0 else len(verts) + i] for i in idx])
    return groups


def pick(points):
    """One representative station per archetype: the median connector count, so the picture is
    typical rather than the biggest or smallest example of its class."""
    by = {}
    for p in points:
        by.setdefault(p.get("archetype"), []).append(p)
    out = {}
    for arch, rows in by.items():
        rows = sorted(rows, key=lambda r: (r.get("totalnbofconnectors") or 0))
        out[arch] = rows[len(rows) // 2]
    return out


def shade(hex_colour, t):
    """Flat Lambert: t in [0,1] from the face normal against a fixed key light."""
    c = hex_colour.lstrip("#")
    r, g, b = (int(c[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    lo, hi = 0.42, 1.06
    k = lo + (hi - lo) * t
    return (min(r * k, 1.0), min(g * k, 1.0), min(b * k, 1.0))


def render(faces, arch, path, px=460):
    tris = [np.array(f, dtype=float) for f in faces if len(f) >= 3]
    if not tris:
        print(f"  {arch}: no faces"); return False
    allv = np.vstack(tris)
    # OBJ is y-up (x=east, z=south); matplotlib 3d is z-up. Swap so the unit stands up.
    allv = allv[:, [0, 2, 1]]
    tris = [t[:, [0, 2, 1]] for t in tris]
    ctr = allv.mean(axis=0)
    span = max(allv.max(axis=0) - allv.min(axis=0)) or 1.0

    light = np.array([0.45, -0.75, 0.52]); light /= np.linalg.norm(light)
    polys, cols = [], []
    for t in tris:
        p = (t - ctr) / span
        n = np.cross(p[1] - p[0], p[2] - p[0])
        ln = np.linalg.norm(n)
        lam = 0.55 if ln == 0 else abs(float(np.dot(n / ln, light)))
        polys.append(p); cols.append(shade(COLOUR.get(arch, "#6FC3B0"), lam))

    fig = plt.figure(figsize=(px / 100, px / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    pc = Poly3DCollection(polys, facecolors=cols, edgecolors=(0, 0, 0, 0.16), linewidths=0.32)
    ax.add_collection3d(pc)
    lim = 0.62
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_zlim(-lim * 0.72, lim * 1.0)
    ax.set_box_aspect((1, 1, 1.05))
    ax.view_init(elev=20, azim=-58)
    ax.set_axis_off()
    fig.patch.set_alpha(0.0)          # transparent: the page supplies light or dark behind it
    ax.patch.set_alpha(0.0)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(path, dpi=100, transparent=True, pad_inches=0)
    plt.close(fig)
    return True


def main():
    for p, what in ((OBJ, "OBJ"), (IDX, "index")):
        if not os.path.exists(p):
            sys.exit(f"{what} not found: {p}\nRun: python scripts/ev_cityengine.py build --rpk "
                     f"data/ev/cityengine/EVCharger.rpk")
    os.makedirs(OUT, exist_ok=True)
    idx = json.load(io.open(IDX, encoding="utf-8"))
    groups = parse_obj(OBJ)
    print(f"{len(groups)} station groups in the OBJ")
    chosen = pick(idx["points"])
    made = 0
    for arch, row in sorted(chosen.items()):
        key = "EV_" + row["point_id"]
        faces = groups.get(key)
        if not faces:
            print(f"  {arch}: no geometry for {key}"); continue
        path = os.path.join(OUT, f"{arch}.png")
        if render(faces, arch, path):
            made += 1
            print(f"  {LABEL.get(arch, arch):24} {row['point_id']:16} "
                  f"{len(faces):4} faces -> {os.path.relpath(path, ROOT)} "
                  f"({os.path.getsize(path):,} B)")
    print(f"wrote {made} archetype renders to {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
