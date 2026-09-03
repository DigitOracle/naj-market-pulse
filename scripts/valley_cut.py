"""Assemble a Valley entry: keyed presenter over Valley footage, drop-in cards, captions.

Takes a HeyGen master (Naj on white, 1080x1920) and builds the finished vertical cut:
  - background bed  : the Emaar vertical clip, looped and dimmed so she and the captions read
  - presenter       : white background keyed out, composited over the bed
  - cutaways        : register cards full-frame, plus the landscape clip WINDOWED - a sharp
                      full-width band over a blurred fill of itself, never cropped full-bleed
                      (it is only 1024x576 and a 9:16 crop would upscale 2.2x)
  - captions        : burned in, phrase-grouped on real word timings, suppressed over cards

Cutaway anchors come from the transcribed word timings, so the picture changes ON the word
that earns it. Some anchors deliberately hold on her face - the turn and the close.

Run:  python -X utf8 scripts/valley_cut.py [series1|v2|all]
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DL = pathlib.Path(r"C:\Users\kwils\Downloads")
SCRATCH = pathlib.Path(
    r"C:\Users\kwils\AppData\Local\Temp\claude\C--Users-kwils-Downloads"
    r"\5cb01229-26e5-4b1c-aeed-742b2bb167e7\scratchpad\edit")
CARDS = ROOT / "public" / "cards"

VERT = DL / "VALLEY_USE_1_vertical_fullbleed_13s.mp4"
STILL_SRC, STILL_AT = None, 17.2   # the Golden Beach frame - the one clean beat with no
                                   # burned-in marketing copy behind her (8 s and the vertical
                                   # clip both carry launch text that would read through)
LAND = DL / "VALLEY_USE_2_lifestyle_WINDOWED_ONLY_45s.mp4"

W, H = 1080, 1920
KEY_SIM = 0.20        # verified on a frame: hair edges intact, no fringing
BED_USABLE = 11.0     # the Emaar vertical clip fades to black from ~11.5 s; looping the
                      # whole 13 s left her standing on an empty frame
# The Kids Dale playground beat. Probed frame by frame: 17-18s pool, 19s skate park,
# 20s PLAYGROUND, 21s+ yoga. It is a short beat, so the insert is cut to fit the clip
# rather than the clip looped to fit the insert - a visible loop reads as a mistake.
# (An -ss seek on a looped input does NOT work: the clip keeps running forward, so by
#  the time the insert appears it has played past the beat into the end card.)
LAND_IN, LAND_OUT = 19.6, 22.6
MAXW = 26             # characters per caption line

# Whisper hears the audio, not the script. These are transcription artefacts, not delivery
# faults - without the map, "derhams" and "1 ,390" get burned into the picture.
FIX = {
    "derhams": "dirhams", "Kidsdale": "Kids Dale", "Kids'": "Kids", "MR": "Emaar",
    "center": "centre", "Everyone": "Every one", "valley": "Valley",
    "land": "Land", "department": "Department",
}

VARIANTS = {
    "series1": dict(
        master="Valley_03SEP2026_Series1.mp4", words="words.json", dur=79.28,
        inserts=[(5.40, 9.20, "rate"), (20.30, 23.10, "land"),
                 (36.90, 41.20, "pillars"), (47.20, 53.00, "buildout")]),
    "v2": dict(
        master="Valley_03SEP2026_V2.mp4", words="words_v2.json", dur=74.77,
        # Variant D never invokes the nine points, so no pillars card here
        inserts=[(26.60, 33.00, "rate"), (38.70, 41.50, "land"),
                 (46.20, 53.40, "buildout")]),
}


def fix_word(w):
    bare = w.rstrip(".,?")
    tail = w[len(bare):]
    return FIX.get(w, FIX.get(bare, bare) + tail)


def build_captions(words_file, hide, ass_path):
    words = json.loads((SCRATCH / words_file).read_text(encoding="utf-8"))
    for w in words:
        w["w"] = fix_word(w["w"])
    merged = []                                   # rejoin split thousands: "1" + ",390"
    for w in words:
        if merged and w["w"].startswith(",") and merged[-1]["w"].isdigit():
            merged[-1]["w"] += w["w"]
            merged[-1]["e"] = w["e"]
        else:
            merged.append(w)

    groups, cur = [], []
    for w in merged:
        cur.append(w)
        if len(" ".join(x["w"] for x in cur)) >= MAXW or w["w"].endswith((".", ",", "?")):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    def ts(t):
        return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"

    head = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Naj,Segoe UI Semibold,74,&H00FFFFFF,&H00FFFFFF,&H00202020,&H80000000,"
        "0,0,0,0,100,100,0,0,1,0,4,2,90,90,250,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    lines, dropped = [], 0
    for g in groups:
        txt = " ".join(x["w"] for x in g).strip()
        if not txt:
            continue
        mid = (g[0]["s"] + g[-1]["e"]) / 2
        if any(a <= mid <= b for a, b in hide):
            dropped += 1
            continue
        lines.append(f"Dialogue: 0,{ts(g[0]['s'])},{ts(g[-1]['e']+0.12)},Naj,,0,0,0,,{txt}")
    ass_path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"  captions: {len(lines)} lines ({dropped} suppressed over cards)")


def make_still():
    """One still, cover-fit and softly blurred, as the whole background.

    Looping the footage fought us twice - the vertical clip fades to black, and an -ss seek
    on a looped input runs past its beat. A still removes both failure modes, and the blur
    hides the 1024 -> 1920 upscale that made the footage look soft in the first place.
    """
    s = SCRATCH / "bg_still.png"
    if not s.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(STILL_AT), "-i", str(LAND),
                        "-frames:v", "1", "-vf",
                        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                        f"gblur=sigma=9,eq=brightness=-0.10:saturation=0.94",
                        str(s)], check=True)
        print(f"  still: Golden Beach frame at {STILL_AT}s, blurred")
    return s


def make_land():
    """Pre-cut the playground beat, so the insert always shows it."""
    lp = SCRATCH / "land_play.mp4"
    if not lp.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(LAND_IN),
                        "-t", str(round(LAND_OUT - LAND_IN, 2)), "-i", str(LAND), "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                        "-pix_fmt", "yuv420p", str(lp)], check=True)
        print(f"  land: {LAND_IN}-{LAND_OUT}s of the lifestyle clip (playground)")
    return lp


def make_bed():
    bed = SCRATCH / "bed.mp4"
    if not bed.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(VERT), "-t", str(BED_USABLE),
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                        "-pix_fmt", "yuv420p", str(bed)], check=True)
        print(f"  bed: first {BED_USABLE}s of the vertical clip (fade trimmed)")
    return bed


def cut(name):
    cfg = VARIANTS[name]
    master = DL / cfg["master"]
    out = DL / f"{master.stem}_CUT.mp4"
    ass = SCRATCH / f"captions_{name}.ass"
    dur = cfg["dur"]
    if not master.exists():
        sys.exit(f"missing master: {master}")

    cards = {k: CARDS / f"valley_dropin_{k}.png" for k in ("rate", "pillars", "buildout")}
    still = make_still()
    card_ins = [i for i in cfg["inserts"] if i[2] != "land"]
    land_ins = []   # windowed insert retired with the video bed
    build_captions(cfg["words"], [(a, b) for a, b, _ in card_ins], ass)

    # hide her only where a card actually covers the frame - building this from every
    # insert left a silent gap where the retired landscape window used to be
    hidden = "*".join(f"not(between(t,{a},{b}))" for a, b, _ in card_ins)
    ass_esc = str(ass).replace("\\", "/").replace(":", "\\:")

    fc = [
        f"[1:v]setsar=1,fps=25[bg]",
        f"[0:v]colorkey=0xFDFDFD:{KEY_SIM}:0.05,setsar=1,fps=25[her]",
        f"[bg][her]overlay=0:0:enable='{hidden}'[v0]",
    ]
    idx, last = 2, "v0"
    for a, b, _ in land_ins:
        fc.append("[5:v]split[lf][lb]")
        fc.append(f"[lf]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"boxblur=28:2,eq=brightness=-0.12,setsar=1,fps=25[landfill]")
        fc.append(f"[lb]scale={W}:-2,setsar=1,fps=25[landband]")
        fc.append(f"[{last}][landfill]overlay=0:0:enable='between(t,{a},{b})'[vf{idx}]")
        fc.append(f"[vf{idx}][landband]overlay=0:(H-h)/2:enable='between(t,{a},{b})'[v{idx}]")
        last = f"v{idx}"
        idx += 1
    for a, b, kind in card_ins:
        n = 2 + ["rate", "pillars", "buildout"].index(kind)
        fc.append(f"[{n}:v]scale={W}:{H},setsar=1,fps=25[c{idx}]")
        fc.append(f"[{last}][c{idx}]overlay=0:0:enable='between(t,{a},{b})'[v{idx}]")
        last = f"v{idx}"
        idx += 1
    fc.append(f"[{last}]subtitles='{ass_esc}'[vout]")

    cmd = ["ffmpeg", "-v", "error", "-y",
           "-i", str(master),
           "-loop", "1", "-t", str(dur), "-i", str(still),
           "-loop", "1", "-t", str(dur), "-i", str(cards["rate"]),
           "-loop", "1", "-t", str(dur), "-i", str(cards["pillars"]),
           "-loop", "1", "-t", str(dur), "-i", str(cards["buildout"]),
           "-loop", "1", "-t", str(dur), "-i", str(still),
           "-filter_complex", ";".join(fc),
           "-map", "[vout]", "-map", "0:a", "-t", str(dur),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    print(f"{name}: encoding {dur}s …")
    subprocess.run(cmd, check=True)
    print(f"  wrote {out.name}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for n in (VARIANTS if which == "all" else [which]):
        cut(n)
