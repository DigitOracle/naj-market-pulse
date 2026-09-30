"""LAB (no-Unreal, research only): colour statistics of three.js stills vs the Unreal film frames, for tuning the look.

For each film time: the Unreal frame (bb_v1_9x16.mp4) and the three.js still (graded with bb_v1_encode's ffmpeg grade, so
both sides went through the same encode-stage grade) are compared on:
  sky     mean sRGB of the top 6 % (skipped at 21 s: that shot looks down at the canal)
  ground  mean sRGB of the bottom 25 %
  shadow  mean sRGB of the darkest 12 % of the bottom half (luma) - shadow colour: warm (Lumen bounce) or blue
  lit     mean sRGB of the brightest 30 % of the bottom half
  all     whole-frame mean; dE = mean |difference| per channel (0-255) over the whole frame at 135 x 240
  python scripts/lab_nounreal_tune.py <stills dir under data/lab/no_unreal> [--film 6,21,34,42]
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LAB = os.path.join(ROOT, "data", "lab", "no_unreal")
FILM = os.path.join(ROOT, "data", "media", "businessbay", "bb_v1_9x16.mp4")
GRADE = "eq=contrast=1.12:saturation=1.35:gamma=0.92,colorbalance=rs=0.04:gs=0.01:bs=-0.03:rm=0.02:bm=-0.02:bh=0.04"


def load(p, graded):
    tmp = p + (".g.png" if graded else ".s.png")
    vf = (GRADE + "," if graded else "") + "scale=540:960"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p, "-vf", vf, tmp], check=True)
    a = np.asarray(Image.open(tmp).convert("RGB")).astype(np.float32); os.remove(tmp); return a


def stats(a, sky=True):
    h = a.shape[0]; out = {}
    if sky:
        out["sky"] = a[: int(h * 0.06)].reshape(-1, 3).mean(0)
    out["ground"] = a[int(h * 0.75):].reshape(-1, 3).mean(0)
    bot = a[h // 2:].reshape(-1, 3); y = bot @ np.array([0.2126, 0.7152, 0.0722])
    out["shadow"] = bot[y <= np.percentile(y, 12)].mean(0); out["lit"] = bot[y >= np.percentile(y, 70)].mean(0)
    out["all"] = a.reshape(-1, 3).mean(0)
    return out


def main():
    d = os.path.join(LAB, sys.argv[1])
    films = [float(x) for x in (sys.argv[sys.argv.index("--film") + 1] if "--film" in sys.argv else "6,21,34,42").split(",")]
    fmt = lambda v: "#%02x%02x%02x" % tuple(int(round(min(255, max(0, x)))) for x in v)
    tot = []
    for t in films:
        ue = os.path.join(LAB, "film_frames", "ue_bb_v1_t%gs.png" % t)
        if not os.path.exists(ue):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", FILM, "-frames:v", "1", ue], check=True)
        A = load(ue, False); B = load(os.path.join(d, "film_t%gs.png" % t), True)
        sa, sb = stats(A, t != 21), stats(B, t != 21)
        small = lambda x: np.asarray(Image.fromarray(x.astype(np.uint8)).resize((135, 240), Image.BILINEAR)).astype(np.float32)
        de = float(np.abs(small(A) - small(B)).mean()); tot.append(de)
        print("t=%-3g dE %.1f   " % (t, de) + "  ".join("%s UE %s 3js %s (%+.0f,%+.0f,%+.0f)" % (k, fmt(sa[k]), fmt(sb[k]), *(sb[k] - sa[k])) for k in sa))
    print("mean dE %.1f" % (sum(tot) / len(tot)))


if __name__ == "__main__":
    main()
