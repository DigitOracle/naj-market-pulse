"""LAB (no-Unreal, research only): cut the three.js full-path render the way bb_v1_encode.py cuts Unreal's MRQ frames,
and put it next to the Unreal film.

In:  data/lab/no_unreal/film_v2/three_film_v2_graded.mp4   (lab_nounreal_render.py film --grade: 0-121 s camera path,
                                                              same frame numbering as MRQ's Saved/MovieRenders/BB_v1)
     data/ce/_datasmith/bb_v1/bb_v1_plan.json              (edit list [render t0, bars] and bar_s - bb_v1_encode's EDIT)
     data/media/businessbay/bb_v1_9x16.mp4                 (the Unreal film: the same edit + end card + music)
Out: data/lab/no_unreal/film_v2/three_bb_v1_edit_9x16.mp4  (1080 x 1920, the film's shots, no card / music / title)
     data/lab/no_unreal/film_v2/sidebyside_bb_v1_edit.mp4  (Unreal | three.js, 540 x 960 each, labelled)
  python scripts/lab_nounreal_edit.py
"""
import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
D = os.path.join(ROOT, "data", "lab", "no_unreal", "film_v2")
PLAN = os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v1", "bb_v1_plan.json")
FILM = os.path.join(ROOT, "data", "media", "businessbay", "bb_v1_9x16.mp4")
FONT = "C\\:/Windows/Fonts/segoeui.ttf"


def main():
    plan = json.load(open(PLAN, encoding="utf-8"))
    fps, bar = int(plan["fps"]), float(plan.get("bar_s", 2.14))
    src = os.path.join(D, "three_film_v2_graded.mp4")
    parts, filt, t = [], [], 0.0
    for i, (t0, bars) in enumerate(plan["edit"]):
        a = int(round(t0 * fps)); n = int(round(bars * bar * fps))
        filt.append("[0:v]trim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS[s%d]" % (a, a + n, i)); parts.append("[s%d]" % i)
        t += n / float(fps)
    filt.append("%sconcat=n=%d:v=1:a=0[v]" % ("".join(parts), len(parts)))
    edit = os.path.join(D, "three_bb_v1_edit_9x16.mp4")
    t0 = time.time()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", ";".join(filt), "-map", "[v]", "-c:v", "h264_nvenc", "-preset", "p5",
                    "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart", edit], check=True)
    print("edit %.2f s -> %s (%.1f s)" % (t, os.path.relpath(edit, ROOT), time.time() - t0))
    lab = lambda s: "drawtext=fontfile='%s':text='%s':x=16:y=16:fontsize=26:fontcolor=white:box=1:boxcolor=0x0E1116@0.7:boxborderw=8" % (FONT, s)
    sbs = os.path.join(D, "sidebyside_bb_v1_edit.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", "%.3f" % t, "-i", FILM, "-i", edit, "-filter_complex",
                    "[0:v]scale=540:960,setsar=1,fps=%d,%s[a];[1:v]scale=540:960,setsar=1,%s[b];[a][b]hstack=2,format=yuv420p[v]"
                    % (fps, lab("Unreal 5.8 (MRQ)"), lab("three.js v2 headless")),
                    "-map", "[v]", "-an", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0", "-movflags", "+faststart", sbs], check=True)
    print("side by side -> %s" % os.path.relpath(sbs, ROOT))


if __name__ == "__main__":
    main()
