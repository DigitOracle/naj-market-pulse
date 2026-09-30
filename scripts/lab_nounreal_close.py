"""LAB (no-Unreal, research only): close / street-level shots - the Unreal lane's closest cameras re-rendered in three.js,
plus two new eye-level cameras (1.7 m) on the Business Bay promenade and canal.

Cameras (UE cm, absolute Z; converted by lab_nounreal_render.cam3):
  canal, boulevard   the bb_v1 camera path at render t = 58.0 s / 35.0 s (ue_bb_v1_tour STILLS: frames 1450 / 875, the
                     lowest film shots, 12-60 m); Unreal: data/media/businessbay/v1_test_canal.png, v1_test_boulevard.png
  cafe, shops, tables  ue_bb_v1_close.views() recomputed from the same data (plan dress.prom_cafes, storefronts_ue.json):
                     eye level 1.6-1.8 m; Unreal: data/media/businessbay/v4_close_<name>.png
  eye_promenade      NEW: 1.7 m on the promenade at the cafe cluster nearest the canal glide, looking along the promenade
                     (towards the next clusters) - what a pedestrian sees
  eye_canal          NEW: 1.7 m at the quay edge beside that cluster, looking across the canal at the far bank towers
Out: data/lab/no_unreal/close/<name>.png (three.js), close_sheet.jpg (Unreal | three.js, graded alike), views.json
  python scripts/lab_nounreal_close.py [--tag close] [--cafe-kits] [--no-ssr] [--mb 2] [--render-args "..."] [--sheet-only]
"""
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lab_nounreal_render as R  # noqa: E402

LAB = os.path.join(ROOT, "data", "lab", "no_unreal")
OUT = os.path.join(LAB, sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "close")
MEDIA = os.path.join(ROOT, "data", "media", "businessbay")
SF = os.path.join(ROOT, "data", "ce", "businessbay", "storefronts_ue.json")


def _canal_tris():
    V, T = [], []
    for line in open(os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v1", "v1_canal_water.obj"), encoding="utf-8"):
        if line.startswith("v "):
            a = line.split(); V.append((float(a[1]), float(a[2])))
        elif line.startswith("f "):
            a = line.split(); T.append(tuple(int(x.split("/")[0]) - 1 for x in a[1:4]))
    return V, T


def in_water(pt, VT=[]):
    if not VT:
        VT.append(_canal_tris())
    V, T = VT[0]
    for i, j, k in T:
        (x1, y1), (x2, y2), (x3, y3) = V[i], V[j], V[k]
        d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if d == 0:
            continue
        a = ((y2 - y3) * (pt[0] - x3) + (x3 - x2) * (pt[1] - y3)) / d; b = ((y3 - y1) * (pt[0] - x3) + (x1 - x3) * (pt[1] - y3)) / d
        if a >= 0 and b >= 0 and a + b <= 1:
            return True
    return False


def water_side(c):
    """unit vector (UE cm frame) from a promenade point, perpendicular to its cafe yaw, towards the canal water"""
    a = math.radians(c[2])
    for s_ in (1, -1):
        n = (-math.sin(a) * s_, math.cos(a) * s_)
        if any(in_water((c[0] + n[0] * d, c[1] + n[1] * d)) for d in (800, 1500, 2500)):
            return n
    raise SystemExit("no canal water beside the cafe cluster")


def views():
    plan = json.load(open(R.PLAN, encoding="utf-8"))
    land = R.GZ_M * 100.0 + float(plan["lift_cm"])                 # UE: gz + LIFT_CM (ue_bb_v1_close: land)
    V = []
    for nm, rt in (("canal", 58.0), ("boulevard", 35.0)):
        loc, tgt = R.cam_at(plan, rt)
        V.append({"name": nm, "render_t": rt, "pos_ue": loc, "tgt_ue": tgt, "ue": "v1_test_%s.png" % nm})
    # ue_bb_v1_close.views(), verbatim logic
    glide = [k[1] for k in plan["keys"] if 56 <= k[0] <= 77]
    S = json.load(open(SF, encoding="utf-8"))
    cafes = plan["dress"].get("prom_cafes", [])
    c = min(cafes, key=lambda r: min(math.hypot(r[0] - g[0], r[1] - g[1]) for g in glide))
    a = math.radians(c[2]); d = (math.cos(a), math.sin(a))
    V.append({"name": "cafe", "pos_ue": [c[0] - d[0] * 1100.0, c[1] - d[1] * 1100.0, land + 170.0], "tgt_ue": [c[0], c[1], land + 90.0], "ue": "v4_close_cafe.png"})
    aw = S.get("awnings", [])
    x, y, yaw, w = aw[len(aw) // 3][:4]
    r = math.radians(yaw); n = (-math.sin(r), math.cos(r)); u = (math.cos(r), math.sin(r))
    V.append({"name": "shops", "pos_ue": [x + n[0] * 1300.0 + u[0] * 500.0, y + n[1] * 1300.0 + u[1] * 500.0, land + 180.0],
              "tgt_ue": [x, y, land + 300.0], "ue": "v4_close_shops.png"})
    tb, bays = S.get("tables", []), S.get("bays", [])
    t = tb[len(tb) // 2]
    b = min(bays, key=lambda q: math.hypot(q[0] - t[0], q[1] - t[1]))
    v = (t[0] - b[0], t[1] - b[1]); L = math.hypot(*v) or 1.0; v = (v[0] / L, v[1] / L)
    V.append({"name": "tables", "pos_ue": [t[0] + v[0] * 700.0 - v[1] * 250.0, t[1] + v[1] * 700.0 + v[0] * 250.0, land + 160.0],
              "tgt_ue": [b[0], b[1], land + 150.0], "ue": "v4_close_tables.png"})
    # NEW eye-level shots (1.7 m): along the promenade, and across the canal from the quay edge
    V.append({"name": "eye_promenade", "pos_ue": [c[0] - d[0] * 300.0, c[1] - d[1] * 300.0, land + 170.0],
              "tgt_ue": [c[0] + d[0] * 6000.0, c[1] + d[1] * 6000.0, land + 400.0], "ue": None})
    to = water_side(c)                                                   # perpendicular to the promenade, the side the canal water is on
    edge = [c[0] + to[0] * 400.0, c[1] + to[1] * 400.0]                  # 4 m from the cafe cluster towards the quay edge
    V.append({"name": "eye_canal", "pos_ue": [edge[0], edge[1], land + 170.0],
              "tgt_ue": [edge[0] + to[0] * 12000.0 + to[1] * 3000.0, edge[1] + to[1] * 12000.0 - to[0] * 3000.0, land + 3500.0], "ue": None})
    return V


def main():
    os.makedirs(OUT, exist_ok=True)
    V = views()
    vj = os.path.join(OUT, "views.json"); json.dump(V, open(vj, "w"), indent=1)
    extra = sys.argv[sys.argv.index("--render-args") + 1].split() if "--render-args" in sys.argv else []
    for flag in ("--no-ssr", "--cafe-kits"):
        if flag in sys.argv:
            extra.append(flag)
    if "--mb" in sys.argv:
        extra += ["--mb", sys.argv[sys.argv.index("--mb") + 1]]
    if "--sheet-only" not in sys.argv:
        subprocess.run([sys.executable, os.path.join(HERE, "lab_nounreal_render.py"), "stills", "--views", vj, "--out", os.path.basename(OUT)] + extra, check=True)
    import numpy as np
    small = lambda im: np.asarray(im.convert("RGB").resize((135, 240), Image.BILINEAR)).astype(np.float32)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    tiles = []
    for v in V:
        three = os.path.join(OUT, v["name"] + ".png")
        g = os.path.join(OUT, v["name"] + "_graded.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", three, "-vf", R.GRADE, g], check=True)
        cols = []
        if v["ue"] and os.path.exists(os.path.join(MEDIA, v["ue"])):
            cols.append(("Unreal: " + v["ue"], Image.open(os.path.join(MEDIA, v["ue"])).convert("RGB")))
        cols.append(("three.js: " + v["name"], Image.open(g).convert("RGB")))
        if len(cols) == 2:                                   # dE vs the Unreal still (same 135 x 240 metric as the aerial pairs)
            v["dE"] = round(float(np.abs(small(cols[0][1]) - small(cols[1][1])).mean()), 1)
            cols[1] = ("three.js: %s  dE %.1f" % (v["name"], v["dE"]), cols[1][1])
        W, H = 540, 960
        tile = Image.new("RGB", (len(cols) * (W + 8), H + 44), (14, 17, 22)); d = ImageDraw.Draw(tile)
        for i, (lab, im) in enumerate(cols):
            tile.paste(im.resize((W, H), Image.LANCZOS), (i * (W + 8), 44)); d.text((i * (W + 8) + 10, 8), lab, fill=(232, 228, 216), font=font)
        tiles.append(tile)
    # two rows: pairs first, then the new eye-level shots
    rows, row, wmax = [], [], 0
    for t in tiles:
        row.append(t)
        if sum(x.width for x in row) > 3000:
            rows.append(row); row = []
    if row:
        rows.append(row)
    W = max(sum(x.width for x in r) for r in rows); H = sum(max(x.height for x in r) for r in rows)
    sheet = Image.new("RGB", (W, H), (14, 17, 22)); y = 0
    for r_ in rows:
        x = 0
        for t in r_:
            sheet.paste(t, (x, y)); x += t.width
        y += max(t.height for t in r_)
    sheet.save(os.path.join(OUT, "close_sheet.jpg"), quality=88)
    de = {v["name"]: v["dE"] for v in V if "dE" in v}
    if de:
        de["mean"] = round(sum(de.values()) / len(de), 1); json.dump(de, open(os.path.join(OUT, "close_dE.json"), "w"), indent=1); print("close dE", de)
    print("wrote", os.path.relpath(os.path.join(OUT, "close_sheet.jpg"), ROOT))


if __name__ == "__main__":
    main()
