"""Assemble episode 08: the Golden Star -> the client's question -> [the Unreal fly-through] -> the HeyGen episode.

Order set by Kendall, 28 Sep 2026 (docs/EP08_SHOOTING_SCRIPT.md section 0). Every clip is used whole and unchanged in
content; each is only conformed to 1080x1920, 25 fps (the HeyGen episode's rate), and 48 kHz stereo, with hard cuts
between them. The fly-through has no sound, so it is given a silent track for the join.

    python scripts/assemble_ep08.py              # without the fly-through
    python scripts/assemble_ep08.py --with-fly   # with it - only once Kendall has approved the render

The fly-through is opt-in because the path can hold an unapproved render: on 28 Sep a v0 sat there with floating
black squares and colour faults while v1 was being rebuilt.
"""
import os
import subprocess
import sys

DL = os.path.expandvars(r"%USERPROFILE%\Downloads")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENER = os.path.join(ROOT, "assets", "brand", "najma_opener_9x16.mp4")          # the Golden Star (bible 9.3)
QUESTION = os.path.join(DL, "Business_Bay_Overview_Request.mp4")                 # approved 28 Sep ("Business Bay")
FLY = os.path.join(ROOT, "data", "media", "ep08", "teaser_businessbay_9x16.mp4")  # Sobha's Unreal render
EPISODE = os.path.join(DL, "BusinessBayDemo_28SEP2026_1080p.mp4")                # HeyGen, Naj over the capture
OUT_DIR = os.path.join(ROOT, "data", "media", "ep08")
W, H, FPS = 1080, 1920, 25


def has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main():
    use_fly = "--with-fly" in sys.argv
    clips = [OPENER, QUESTION] + ([FLY] if use_fly else []) + [EPISODE]
    for c in clips:
        if not os.path.exists(c):
            sys.exit("missing: %s" % c)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "EP08_BUSINESSBAY_ASSEMBLED%s_9x16.mp4" % ("" if use_fly else "_NO_FLYTHROUGH"))

    args, parts, n = ["ffmpeg", "-loglevel", "error", "-y"], [], 0
    for c in clips:
        args += ["-i", c]
    for i, c in enumerate(clips):
        parts.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,fps=%d,setsar=1,"
                     "format=yuv420p[v%d]" % (i, W, H, W, H, FPS, i))
        if has_audio(c):
            parts.append("[%d:a]aresample=48000,aformat=channel_layouts=stereo[a%d]" % (i, i))
        else:  # silent track the exact length of the clip, so the join keeps sync
            parts.append("anullsrc=r=48000:cl=stereo,atrim=duration=%.3f[a%d]" % (duration(c), i))
        n += 1
    parts.append("".join("[v%d][a%d]" % (i, i) for i in range(n)) + "concat=n=%d:v=1:a=1[v][a]" % n)
    args += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", out]
    subprocess.run(args, check=True)
    print("clips:", " -> ".join(os.path.basename(c) for c in clips))
    print("wrote %s (%.1f s)" % (out, duration(out)))


if __name__ == "__main__":
    main()
