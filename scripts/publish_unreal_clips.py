"""Check what Unreal actually rendered, then publish only the clips that survive the check.

  python scripts/publish_unreal_clips.py businessbay            # check only, publishes nothing
  python scripts/publish_unreal_clips.py businessbay --push     # publish the ones that pass

WHY THIS IS NOT PART OF STAGE 3. A render that dies halfway still leaves a file. A camera pointed at nothing still
produces 120 valid frames of sky. Unreal is the wrong place to decide whether a file is worth putting in front of a
user, because inside the editor "the job completed" is the only fact available. Out here the file itself can be
examined, and publishing is a separate act from rendering.

WHAT IT CHECKS, and each one is a failure seen in some render pipeline before:
  * the file exists at the path stage 3 said it would
  * it is larger than MIN_KB - a 4 KB mp4 is a header and a shrug
  * it starts with a real MP4 container signature ('ftyp' at offset 4), not an HTML error page or a truncated write
  * its duration is close to what the sequence asked for - a clip that stops after 3 frames is worse than no clip,
    because it looks deliberate
  * a poster frame exists or can be made

Anything that fails is listed with the reason and NOT published. The check runs by default; --push is deliberate.

POSTER FRAMES. push_unreal_clip.py needs an mp4 and a jpg. If ffmpeg is on PATH the poster is pulled from a third of
the way in - far enough that the orbit has moved off its opening frame. Without ffmpeg the clip is reported as
needing a poster rather than published without one.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_KB = 120
DURATION_TOLERANCE = 0.30          # a clip may be 30% short before it is called broken


def ffprobe(path):
    """Duration in seconds, or None when ffprobe is unavailable or the file is unreadable."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=60)
        return float((r.stdout or "").strip())
    except Exception:
        return None


def make_poster(mp4, jpg, at):
    if os.path.exists(jpg):
        return True
    if not shutil.which("ffmpeg"):
        return False
    try:
        subprocess.run(["ffmpeg", "-y", "-ss", "%.2f" % at, "-i", mp4, "-frames:v", "1", "-q:v", "3", jpg],
                       capture_output=True, timeout=120)
        return os.path.exists(jpg) and os.path.getsize(jpg) > 2000
    except Exception:
        return False


def check(clip, expect_s):
    mp4 = clip["expect_mp4"]
    if not os.path.exists(mp4):
        return False, "no file at %s" % os.path.basename(mp4)
    kb = os.path.getsize(mp4) // 1024
    if kb < MIN_KB:
        return False, "only %d KB - a header and a shrug, not a clip" % kb
    try:
        with open(mp4, "rb") as fh:
            head = fh.read(16)
    except Exception as e:
        return False, "unreadable: %s" % e
    if head[4:8] != b"ftyp":
        return False, "not an MP4 container (no ftyp) - a truncated write or an error page"
    dur = ffprobe(mp4)
    if dur is not None and dur < expect_s * (1.0 - DURATION_TOLERANCE):
        return False, "%.1fs of an expected %.1fs - it stopped early, which looks deliberate on screen" % (dur, expect_s)
    return True, "%d KB%s" % (kb, "" if dur is None else ", %.1fs" % dur)


def main(slug, push=False):
    man = json.load(open(os.path.join(ROOT, "data", "board", "unreal_stage3_%s.json" % slug), encoding="utf-8"))
    st2 = json.load(open(os.path.join(ROOT, "data", "board", "unreal_stage2_%s.json" % slug), encoding="utf-8"))
    expect_s = float(st2.get("seconds") or 5.0)
    by_i = {m["i"]: m for m in st2["made"]}

    ok, bad = [], []
    for c in man["clips"]:
        good, why = check(c, expect_s)
        if not good:
            bad.append((c, why))
            continue
        jpg = os.path.splitext(c["expect_mp4"])[0] + ".jpg"
        if not make_poster(c["expect_mp4"], jpg, expect_s / 3.0):
            bad.append((c, "no poster frame and ffmpeg is not on PATH - push_unreal_clip.py needs one"))
            continue
        ok.append((c, jpg, why))

    print("%s: %d of %d clips pass" % (slug, len(ok), len(man["clips"])))
    for c, jpg, why in ok:
        print("   ok    b%-5d %-34s %s" % (c["i"], c["name"][:34], why))
    for c, why in bad:
        print("   FAIL  b%-5d %-34s %s" % (c["i"], c["name"][:34], why))

    if not push:
        print("\ncheck only. Add --push to publish the %d that pass." % len(ok))
        return
    if not ok:
        print("\nnothing passes; nothing published.")
        return

    script = os.path.join(ROOT, "scripts", "push_unreal_clip.py")
    for c, jpg, _ in ok:
        rec = by_i.get(c["i"]) or {}
        title = "%.0f m, %s" % (rec.get("height_m") or 0, "a slow turn")
        cmd = [sys.executable, script, slug, str(c["i"]), c["name"], c["expect_mp4"], jpg, title]
        print("\n$ " + " ".join(cmd[1:]))
        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0:
            print("   push FAILED for b%d - stopping rather than carrying on through a broken publish" % c["i"])
            return
    print("\npublished %d clips." % len(ok))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    main(args[0] if args else "businessbay", push="--push" in sys.argv)
