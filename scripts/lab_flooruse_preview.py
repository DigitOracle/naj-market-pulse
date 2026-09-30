"""LAB (floor-use technique #2): a still of the floor-use GLB, for evidence only (no viewer, no upload).

Reads data/lab/flooruse/flooruse_<slug>.glb (one node per building, one primitive per use colour) and draws the buildings
within --radius metres of the tallest one (or of --at b<i>) with matplotlib, flat-shaded by their use colour, plus a legend.

  python scripts/lab_flooruse_preview.py businessbay                -> data/lab/flooruse/flooruse_<slug>_preview.png
  python scripts/lab_flooruse_preview.py businessbay --radius 350 --at b574
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "flooruse")
LEGEND = [("homes", "#D9CFB8"), ("offices", "#8FA39B"), ("shops", "#D98C6A"), ("hotel", "#C58FB0"),
          ("parking (proposed colour)", "#6E7672"), ("services", "#37423F"), ("other", "#8A8F96")]


def opt(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from matplotlib.patches import Patch
    sys.path.insert(0, HERE)
    from glb_merge_per_building import read_glb, accessor_raw

    slug = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "businessbay"
    radius = float(opt("--radius", 300))
    js, bn = read_glb(os.path.join(OUT, "flooruse_%s.glb" % slug))
    parts = []                                          # (building name, triangles (n,3,3) in the glTF frame, sRGB colour)
    for nd in js["nodes"]:
        if "mesh" not in nd:
            continue
        for pr in js["meshes"][nd["mesh"]]["primitives"]:
            raw, cnt, fmt = accessor_raw(js, bn, pr["attributes"]["POSITION"])
            v = np.frombuffer(raw, dtype="<f4").reshape(cnt, 3).astype(float)
            if "indices" in pr:
                ir, ic, ifmt = accessor_raw(js, bn, pr["indices"])
                idx = np.frombuffer(ir, dtype={5121: "<u1", 5123: "<u2", 5125: "<u4"}[ifmt[0]]).astype(int)
            else:
                idx = np.arange(cnt)
            lin = js["materials"][pr["material"]]["pbrMetallicRoughness"]["baseColorFactor"][:3] if "material" in pr else [0.3] * 3
            srgb = np.array([c ** (1 / 2.2) for c in lin])          # glTF colours are linear
            parts.append((nd.get("name", ""), v[idx].reshape(-1, 3, 3), srgb))
    # centre: the named building, else the highest point
    at = opt("--at")
    if at:
        sel = [p for p in parts if p[0].split("_")[0] == at] or parts
        c = np.concatenate([p[1].reshape(-1, 3) for p in sel]).mean(axis=0)
    else:
        top = max(parts, key=lambda p: p[1][:, :, 1].max())
        c = top[1].reshape(-1, 3).mean(axis=0)
    keep = []
    for name, tri, col in parts:
        m = tri.reshape(-1, 3).mean(axis=0)
        if (m[0] - c[0]) ** 2 + (m[2] - c[2]) ** 2 <= radius ** 2:
            keep.append((tri, col))
    fig = plt.figure(figsize=(12, 10), dpi=110)
    ax = fig.add_subplot(111, projection="3d")
    light = np.array([0.4, 0.8, -0.45]); light /= np.linalg.norm(light)
    hmax = 0.0
    polys, cols = [], []
    for tri, col in keep:
        # glTF y-up -> plot (x = east, y = north, z = up); CE frame z = -northing
        P = np.stack([tri[:, :, 0] - c[0], -(tri[:, :, 2] - c[2]), tri[:, :, 1]], axis=-1)
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        nn = np.linalg.norm(n, axis=1, keepdims=True); nn[nn == 0] = 1
        shade = 0.55 + 0.45 * np.clip(np.abs((n / nn) @ np.array([light[0], -light[2], light[1]])), 0, 1)
        polys.append(P); cols.append(np.clip(np.outer(shade, col), 0, 1))
        hmax = max(hmax, float(P[:, :, 2].max()))
    # ONE collection, so matplotlib depth-sorts face by face (per-collection sorting put slab lines over whole towers)
    ax.add_collection3d(Poly3DCollection(np.concatenate(polys), facecolors=np.concatenate(cols), edgecolors="none"))
    ax.set_xlim(-radius, radius); ax.set_ylim(-radius, radius); ax.set_zlim(0, max(hmax, 50))
    ax.set_box_aspect((1, 1, max(hmax, 50) / (2 * radius)))
    ax.view_init(elev=22, azim=-60)
    ax.set_axis_off()
    ax.set_title("%s - floor-by-floor use (lab rule flooruse.cga, PyPRT). Research use only; unit counts are estimates." % slug,
                 fontsize=10)
    ax.legend(handles=[Patch(color=c_, label=l) for l, c_ in LEGEND], loc="upper left", fontsize=8, frameon=False)
    out = os.path.join(OUT, "flooruse_%s_preview.png" % slug)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print("wrote %s  (%d use primitives within %.0f m)" % (os.path.relpath(out, ROOT), len(keep), radius))
    return 0


if __name__ == "__main__":
    sys.exit(main())
