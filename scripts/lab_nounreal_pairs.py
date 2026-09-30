"""LAB (no-Unreal, research only): side-by-side PNGs - Unreal film frame vs headless three.js renders of the same camera.

Columns per film time:
  UNREAL   frame grabbed from data/media/businessbay/bb_v1_9x16.mp4 (Unreal 5.8 MRQ + bb_v1_encode.py grade)
  BEFORE   data/lab/no_unreal/stills/film_t<t>s.png      (v1 renderer, lab_nounreal_render_v1.py)      [--before <dir>]
  AFTER    data/lab/no_unreal/stills_v2/film_t<t>s.png   (v2 renderer, lab_nounreal_render.py)          [--after <dir>]
Both three.js columns go through the SAME ffmpeg grade bb_v1_encode.py applies to the Unreal frames (BB_V1_GRADE default),
so only the renderer differs. dE = mean |difference| per channel (0-255) against the Unreal frame at 135 x 240.
  python scripts/lab_nounreal_pairs.py [--film 6,21,34,42] [--before stills] [--after stills_v2] [--out pairs_v2]
         [--before-label "three.js v1"] [--after-label "three.js v2"]
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LAB = os.path.join(ROOT, "data", "lab", "no_unreal")
FILM = os.path.join(ROOT, "data", "media", "businessbay", "bb_v1_9x16.mp4")
GRADE = "eq=contrast=1.12:saturation=1.35:gamma=0.92,colorbalance=rs=0.04:gs=0.01:bs=-0.03:rm=0.02:bm=-0.02:bh=0.04"


def arg(k, d):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + [str(x) for x in a], check=True)


def timings(d):
    p = os.path.join(LAB, d, "timings.json")
    return {f["name"]: f for f in json.load(open(p, encoding="utf-8")).get("frames", [])} if os.path.exists(p) else {}


def de(a, b):
    s = lambda x: np.asarray(x.resize((135, 240), Image.BILINEAR)).astype(np.float32)
    return float(np.abs(s(a) - s(b)).mean())


def main():
    films = [float(x) for x in arg("--film", "6,21,34,42").split(",")]
    before, after = arg("--before", "stills"), arg("--after", "stills_v2")
    out = os.path.join(LAB, arg("--out", "pairs_v2")); os.makedirs(out, exist_ok=True)
    tb, ta = timings(before), timings(after)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30); small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 24)
    except OSError:
        font = small = ImageFont.load_default()
    tiles, rows = [], []
    for t in films:
        name = "film_t%gs" % t
        ue = os.path.join(out, "ue_t%gs.png" % t)
        ff("-ss", t, "-i", FILM, "-frames:v", 1, ue)
        cols = [("UNREAL 5.8 (MRQ, Lumen)", Image.open(ue).convert("RGB"), None)]
        for label, d, tm in (("BEFORE: " + arg("--before-label", "three.js v1"), before, tb), ("AFTER: " + arg("--after-label", "three.js v2"), after, ta)):
            src = os.path.join(LAB, d, name + ".png")
            if not os.path.exists(src):
                continue
            g = os.path.join(out, "%s_t%gs_graded.png" % (d, t))
            ff("-i", src, "-vf", GRADE + ",scale=1080:1920", g)
            cols.append((label, Image.open(g).convert("RGB"), tm.get(name, {})))
        W, H = cols[0][1].size
        pair = Image.new("RGB", (len(cols) * W + (len(cols) - 1) * 12, H + 110), (14, 17, 22))
        d_ = ImageDraw.Draw(pair); row = {"film_t": t}
        for i, (label, im, tm) in enumerate(cols):
            x = i * (W + 12); pair.paste(im, (x, 110))
            d_.text((x + 16, 12), label, fill=(232, 228, 216), font=font)
            if tm is None:
                d_.text((x + 16, 58), "bb_v1_9x16.mp4 @ %g s (graded by bb_v1_encode)" % t, fill=(160, 170, 165), font=small)
            else:
                e = de(cols[0][1], im); row[label.split(":")[0].lower()] = round(e, 1)
                d_.text((x + 16, 58), "dE %.1f vs Unreal | render %s ms | + same ffmpeg grade" % (e, tm.get("render_ms", "?")), fill=(160, 170, 165), font=small)
        p = os.path.join(out, "pair_t%gs.png" % t); pair.save(p); rows.append(row)
        tiles.append(pair.resize((pair.width // 3, pair.height // 3), Image.LANCZOS))
        print("wrote", os.path.relpath(p, ROOT), row)
    tw = max(x.width for x in tiles); th = tiles[0].height
    sheet = Image.new("RGB", (tw * 2, th * ((len(tiles) + 1) // 2)), (14, 17, 22))
    for i, tl in enumerate(tiles):
        sheet.paste(tl, ((i % 2) * tw, (i // 2) * th))
    sp = os.path.join(out, "pairs_sheet.jpg"); sheet.save(sp, quality=90)
    json.dump(rows, open(os.path.join(out, "dE.json"), "w"), indent=1)
    print("wrote", os.path.relpath(sp, ROOT))


if __name__ == "__main__":
    main()
