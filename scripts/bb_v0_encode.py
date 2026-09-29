"""Business Bay v0 - the edit and the files (plain CPython + ffmpeg). Step 6 of logs/bb_v0_run.ps1.

In:   Saved/MovieRenders/BB_v0/bb_v0.<frame>.jpeg  (one continuous 94 s render, 1080 x 1920, 25 fps)
      data/ce/_datasmith/bb_v0/bb_v0_plan.json      (EDIT and TEASER windows, bar length)
      data/ce/_datasmith/bb_v0/used_assets.json     (library folders placed) + data/board/asset_library_manifest.json (credits)
Out:  data/media/businessbay/bb_v0_9x16.mp4          the edit: 7-bar opener orbit, 2-bar shots (hard cuts on the "Five
                                                     Armies" bar grid, 2.14 s), 5-bar pull-back into the steady frame,
                                                     then a 2-bar credits end card; title card over the opener
                                                     (BB_V0_TITLE=0 drops it); music "Five Armies" (Kevin MacLeod, CC BY
                                                     4.0) trimmed, faded out over the last 3 s, loudnorm -16 LUFS
      data/media/businessbay/bb_v0_9x16_share.mp4    720 x 1280 copy under 16 MB
      data/media/ep08/teaser_businessbay_9x16.mp4    20 s teaser, 1080 x 1920, 25 fps, no text / logo / voice / music
      <each mp4>_credits.txt                         every CC-BY author, model and licence (+ the music line where used)
All text sits inside the central 1080 x 1420 safe zone. Frames are kept (delete Saved/MovieRenders/BB_v0 by hand).
Usage:  python scripts/bb_v0_encode.py
"""
import glob, json, os, re, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = r"C:\Dev\UnrealProjects\AzimuthDubai\Saved\MovieRenders\BB_v0"
PLAN = os.path.join(REPO, "data", "ce", "_datasmith", "bb_v0", "bb_v0_plan.json")
USED = os.path.join(REPO, "data", "ce", "_datasmith", "bb_v0", "used_assets.json")
MANIFEST = os.path.join(REPO, "data", "board", "asset_library_manifest.json")
OUT_DIR = os.path.join(REPO, "data", "media", "businessbay")
MAIN = os.path.join(OUT_DIR, "bb_v0_9x16.mp4")
SHARE = os.path.join(OUT_DIR, "bb_v0_9x16_share.mp4")
TEASER = os.path.join(REPO, "data", "media", "ep08", "teaser_businessbay_9x16.mp4")
MUSIC = r"C:\Dev\assets\finish\music\Five Armies.mp3"
MUSIC_LINE = '"Five Armies" Kevin MacLeod (incompetech.com). Licensed under Creative Commons: By Attribution 4.0 License http://creativecommons.org/licenses/by/4.0/'
FF = r"C:\Users\kwils\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_B = "C\\:/Windows/Fonts/segoeuib.ttf" if os.path.exists(r"C:\Windows\Fonts\segoeuib.ttf") else FONT
ASSETS = r"C:\Dev\assets"
CARD_BARS = 2
SHARE_MB = 15.5
TMP = os.path.join(OUT_DIR, "_bb_v0_tmp")


def run(args):
    print(" ".join(str(a) for a in args[:6]), "...", flush=True)
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error"] + [str(a) for a in args], check=True)


def frames():
    fs = sorted(glob.glob(os.path.join(FRAMES, "bb_v0.*.jp*g")) + glob.glob(os.path.join(FRAMES, "bb_v0.*.png")))
    if not fs:
        sys.exit("no frames in %s" % FRAMES)
    ext = os.path.splitext(fs[0])[1]
    nums = sorted(int(re.search(r"\.(\d+)\.", os.path.basename(f)).group(1)) for f in fs)
    return os.path.join(FRAMES, "bb_v0.%04d" + ext), nums[0], nums[-1]


def clean(name):
    s = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    return re.sub(r"_+", "_", s)


def credits_lines():
    """one line per library asset folder placed: its CREDIT.txt / manifest credit (CC0 sources listed after CC-BY ones)"""
    try:
        used = json.load(open(USED, encoding="utf-8"))
    except Exception:
        used = {}
    folders = sorted(set(list(used.get("placed", {}).keys()) + list(used.get("movers", {}).keys())))
    rows = []
    try:
        rows = json.load(open(MANIFEST, encoding="utf-8")).get("assets", [])
    except Exception:
        pass
    by, cc0, other = {}, set(), []
    for f in folders:
        if not f.startswith("/Game/DA/Library"):
            if f.startswith("/Game/DA/Najma"):
                other.append("Plant models from the DA_UE58 POC library (%s)" % f.split("/")[-1])
            continue
        credit = next((r.get("credit") for r in rows if r.get("asset", "").startswith(f + "/") and r.get("credit")), "")
        if not credit:                                  # fall back to the source folder's CREDIT.txt
            leaf = f.split("/")[-1]
            for c in glob.glob(os.path.join(ASSETS, "*", "*")) + glob.glob(os.path.join(ASSETS, "*", "*", "*")):
                if os.path.isdir(c) and clean(os.path.basename(c)) == leaf and os.path.exists(os.path.join(c, "CREDIT.txt")):
                    credit = open(os.path.join(c, "CREDIT.txt"), encoding="utf-8", errors="replace").read().strip()
                    break
        credit = " ".join(credit.split())
        if not credit:
            credit = "%s (%s) - licence: see C:/Dev/assets source folder" % (f.split("/")[-1], f.split("/")[-2])
        if "CC0" in credit or "Poly Haven" in credit or "ambientCG" in credit.lower():
            cc0.add(credit)
        else:
            by[credit] = 1
    return sorted(by), sorted(cc0), sorted(set(other))


def write_credits(mp4, with_music, note=""):
    by, cc0, other = credits_lines()
    L = ["Business Bay, Dubai - v0 fly-through preview (internal). DigitAlchemy(R) Tech Limited, contact@digitalabbot.io", ""]
    if note:
        L += [note, ""]
    if with_music:
        L += ["Music:", MUSIC_LINE, ""]
    else:
        L += ["Music: none in this file.", ""]
    L += ["3D models (CC BY 4.0 - attribution required):"] + ["  " + x for x in by] + [""]
    if cc0:
        L += ["CC0 assets (no attribution required, listed for good practice):"] + ["  " + x for x in cc0] + [""]
    if other:
        L += ["Other:"] + ["  " + x for x in other] + [""]
    L += ["Buildings: CityEngine LOD3 model of Business Bay (DigitAlchemy, internal research use); streets and water from OpenStreetMap",
          "(c) OpenStreetMap contributors, ODbL; Overture Maps water."]
    p = os.path.splitext(mp4)[0] + "_credits.txt"
    open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("credits ->", p, "(%d CC-BY, %d CC0)" % (len(by), len(cc0)))


def textfile(name, text):
    p = os.path.join(TMP, name)
    open(p, "w", encoding="utf-8").write(text)
    return p.replace("\\", "/").replace(":", "\\:")


def segment(pattern, first, t0, dur, out, fps):
    run(["-framerate", fps, "-start_number", first + int(round(t0 * fps)), "-i", pattern, "-frames:v", int(round(dur * fps)),
         "-vf", "scale=1080:1920,setsar=1,format=yuv420p", "-c:v", "libx264", "-crf", "14", "-preset", "fast", "-r", fps, out])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    plan = json.load(open(PLAN, encoding="utf-8"))
    fps, bar = int(plan["fps"]), float(plan.get("bar_s", 2.14))
    pattern, first, last = frames()
    print("frames %d..%d (%.1f s)" % (first, last, (last - first + 1) / float(fps)))
    os.makedirs(TMP, exist_ok=True); os.makedirs(os.path.dirname(TEASER), exist_ok=True)

    # ---- main edit: bar-grid shots, hard cuts ------------------------------------------------------------------
    segs = []
    for i, (t0, bars) in enumerate(plan["edit"]):
        p = os.path.join(TMP, "s%02d.mp4" % i)
        segment(pattern, first, t0, bars * bar, p, fps); segs.append(p)
    # end card: 2 bars, dark, text fades in (safe zone: y 560-1360)
    card = os.path.join(TMP, "card.mp4"); dur = CARD_BARS * bar
    t1 = textfile("c1.txt", "Business Bay, Dubai"); t2 = textfile("c2.txt", "v0 preview  ·  DigitAlchemy®")
    t3 = textfile("c3.txt", "Music: \"Five Armies\" Kevin MacLeod (incompetech.com)"); t4 = textfile("c4.txt", "Licensed under Creative Commons: By Attribution 4.0")
    t5 = textfile("c5.txt", "3D models: see the credits file (CC BY 4.0 / CC0)")
    fade = "alpha='if(lt(t,0.4),t/0.4,1)'"
    vf = ",".join([
        "drawtext=fontfile='%s':textfile='%s':fontsize=64:fontcolor=white:x=(w-tw)/2:y=760:%s" % (FONT_B, t1, fade),
        "drawtext=fontfile='%s':textfile='%s':fontsize=36:fontcolor=0xE8D2A8:x=(w-tw)/2:y=850:%s" % (FONT, t2, fade),
        "drawtext=fontfile='%s':textfile='%s':fontsize=30:fontcolor=0xD0D4DA:x=(w-tw)/2:y=1010:%s" % (FONT, t3, fade),
        "drawtext=fontfile='%s':textfile='%s':fontsize=26:fontcolor=0xB0B6BE:x=(w-tw)/2:y=1056:%s" % (FONT, t4, fade),
        "drawtext=fontfile='%s':textfile='%s':fontsize=26:fontcolor=0xB0B6BE:x=(w-tw)/2:y=1110:%s" % (FONT, t5, fade),
        "format=yuv420p"])
    run(["-f", "lavfi", "-i", "color=c=0x0E1116:s=1080x1920:r=%d:d=%.3f" % (fps, dur), "-vf", vf, "-c:v", "libx264", "-crf", "14", "-preset", "fast", card])
    segs.append(card)
    total = sum(b for _, b in plan["edit"]) * bar + dur
    lst = os.path.join(TMP, "list.txt")
    open(lst, "w", encoding="utf-8").write("".join("file '%s'\n" % s.replace("\\", "/") for s in segs))
    joined = os.path.join(TMP, "joined.mp4")
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    title = ""
    if os.environ.get("BB_V0_TITLE", "1") == "1":
        a = "alpha='if(lt(t,1.2),0,if(lt(t,2.2),t-1.2,if(lt(t,5.5),1,if(lt(t,6.5),6.5-t,0))))'"
        title = ",".join(["drawtext=fontfile='%s':textfile='%s':fontsize=78:fontcolor=white:shadowcolor=black@0.45:shadowx=2:shadowy=2:x=(w-tw)/2:y=520:%s" %
                          (FONT_B, textfile("t1.txt", "BUSINESS BAY"), a),
                          "drawtext=fontfile='%s':textfile='%s':fontsize=40:fontcolor=0xF3E3C3:shadowcolor=black@0.45:shadowx=2:shadowy=2:x=(w-tw)/2:y=620:%s" %
                          (FONT, textfile("t2.txt", "Dubai"), a)]) + ","
    af = "atrim=0:%.3f,asetpts=PTS-STARTPTS,afade=t=in:d=0.3,afade=t=out:st=%.3f:d=3,loudnorm=I=-16:TP=-1.5:LRA=11" % (total, total - 3.0)
    run(["-i", joined, "-i", MUSIC, "-filter_complex", "[0:v]%sformat=yuv420p[v];[1:a]%s[a]" % (title, af), "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-r", fps, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", "%.3f" % total, MAIN])
    write_credits(MAIN, True)
    # ---- share copy < 16 MB --------------------------------------------------------------------------------------
    kbps = int(SHARE_MB * 8192 / total) - 128
    for _ in range(4):
        run(["-i", MAIN, "-vf", "scale=720:1280", "-c:v", "libx264", "-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.3), "-bufsize", "%dk" % (kbps * 2),
             "-preset", "slow", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", SHARE])
        mb = os.path.getsize(SHARE) / 1048576.0
        if mb < 16.0:
            break
        kbps = int(kbps * 0.85)
    write_credits(SHARE, True)
    # ---- ep08 teaser: 20 s, hard cuts on calm moves, no text / music -------------------------------------------------
    tsegs = []
    for i, (a, b) in enumerate(plan["teaser"]):
        p = os.path.join(TMP, "t%02d.mp4" % i)
        segment(pattern, first, a, b - a, p, fps); tsegs.append(p)
    open(lst, "w", encoding="utf-8").write("".join("file '%s'\n" % s.replace("\\", "/") for s in tsegs))
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p", "-r", fps, "-an", "-movflags", "+faststart", TEASER])
    write_credits(TEASER, False, "ep08 teaser: 20 s cut from the v0 render (orbit 7 s, canal 8 s, steady 5 s). No music, text, logos or voice in this file.")
    for f in (MAIN, SHARE, TEASER):
        pr = subprocess.run([FP, "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "compact", f], capture_output=True, text=True).stdout
        print("%s  %.1f MB  %s" % (f, os.path.getsize(f) / 1048576.0, " | ".join(pr.split())))


if __name__ == "__main__":
    main()
