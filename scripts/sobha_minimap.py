"""A "where are we in Dubai" mini-map for the Sobha tour - v17, 25 Sep 2026.

Kendall asked from the start for "the context of where this is in Dubai". The aerials give it only while the camera is high;
once it drops onto an orbit the viewer loses the city. This draws a small map in the bottom-right corner - the coast and the
Creek / canal / lagoons (the same OpenStreetMap meshes the tour's ground uses: data/ce/_datasmith/ground/sea.obj and
inland_water.obj, Unreal cm on the shared CE offset), every tour stop as a numbered dot, the current stop gold - and shows it
for the whole of each stop (arrival, orbit, hold, pull-out). Stops and timings from data/media/sobha/tour_stops.json.

  panel     300 x 300 px at (740, 870), above the legend band; dark, rounded, 88% opaque
  frame     the stops' extent + 5 km, square, north up
Usage: python scripts/sobha_minimap.py <tour.mp4> <out.mp4>      (the encoder can also call overlay_args())
"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "data", "media", "sobha")
GROUND = os.path.join(ROOT, "data", "ce", "_datasmith", "ground")
OUT_DIR = os.path.join(MEDIA, "cards")
FF = r"C:\Users\kwils\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
W, H = 1080, 1920
PX, PY, PS = 740, 1440, 300
OFF_E, OFF_N = 328289.0, 2784598.0
GOLD = (197, 165, 106); SAND = (38, 46, 50); SEA = (28, 92, 128); WATER = (40, 112, 150)


def obj_tris(path):
    V, T = [], []
    for line in open(path, encoding="utf-8"):
        if line.startswith("v "):
            _, x, y, z = line.split()[:4]; V.append((float(x), float(y)))
        elif line.startswith("f "):
            T.append([int(p.split("/")[0]) - 1 for p in line.split()[1:4]])
    return V, T


def build(stops):
    xs = [(s["utm"][0] - OFF_E) * 100 for s in stops]; ys = [(OFF_N - s["utm"][1]) * 100 for s in stops]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 500000.0          # + 5 km
    inner = PS - 24
    def px(x, y):
        return (12 + (x - (cx - half)) / (2 * half) * inner, 12 + (y - (cy - half)) / (2 * half) * inner)
    S = 3                                                                       # supersample for smooth edges
    base = Image.new("RGBA", (PS * S, PS * S), (0, 0, 0, 0)); d = ImageDraw.Draw(base)
    d.rounded_rectangle((0, 0, PS * S - 1, PS * S - 1), 18 * S, fill=(8, 20, 28, 226))
    d.rounded_rectangle((12 * S, 12 * S, (PS - 12) * S, (PS - 12) * S), 10 * S, fill=SAND + (255,))
    clip = Image.new("L", base.size, 0); ImageDraw.Draw(clip).rounded_rectangle((12 * S, 12 * S, (PS - 12) * S, (PS - 12) * S), 10 * S, fill=255)
    water = Image.new("RGBA", base.size, (0, 0, 0, 0)); wd = ImageDraw.Draw(water)
    for name, col in (("sea", SEA), ("inland_water", WATER)):
        V, T = obj_tris(os.path.join(GROUND, name + ".obj"))
        for a, b, c in T:
            pts = [px(*V[k]) for k in (a, b, c)]
            if all(p[0] < -50 or p[0] > PS + 50 for p in pts) or all(p[1] < -50 or p[1] > PS + 50 for p in pts):
                continue
            wd.polygon([(p[0] * S, p[1] * S) for p in pts], fill=col + (255,))
    base.paste(water, (0, 0), Image.composite(water, Image.new("RGBA", base.size, (0, 0, 0, 0)), clip).split()[3])
    f = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 13 * S)
    fn = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 14 * S)
    d = ImageDraw.Draw(base)
    d.text((PS * S - 34 * S, 16 * S), "N", font=fn, fill=(230, 230, 230, 220))
    d.polygon([(PS * S - 28 * S, 36 * S), (PS * S - 33 * S, 46 * S), (PS * S - 23 * S, 46 * S)], fill=(230, 230, 230, 220))
    pos = [px(x, y) for x, y in zip(xs, ys)]
    out = []
    for k, s in enumerate(stops):
        im = base.copy(); dd = ImageDraw.Draw(im)
        for j, (x, y) in enumerate(pos):
            r = 9 if j == k else 7
            fill = GOLD + (255,) if j == k else (225, 232, 238, 235)
            if j == k:
                dd.ellipse(((x - 15) * S, (y - 15) * S, (x + 15) * S, (y + 15) * S), outline=GOLD + (200,), width=2 * S)
            dd.ellipse(((x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S), fill=fill)
            t = str(j + 1); tw = dd.textlength(t, font=f)
            dd.text((x * S - tw / 2, (y - 9.5) * S), t, font=f, fill=(8, 20, 28, 255))
        im = im.resize((PS, PS), Image.LANCZOS)
        # caption strip under the map: which stop this is
        from sobha_tour_encode import TITLES
        cap = Image.new("RGBA", (PS, 40), (0, 0, 0, 0)); cd = ImageDraw.Draw(cap)
        cd.rounded_rectangle((0, 0, PS - 1, 39), 12, fill=(8, 20, 28, 226))
        txt = "%d  ·  %s" % (k + 1, TITLES.get(s["district"], s["name"].title()).split("  ·  ")[0])
        fc = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 18)
        cd.text((14, 8), txt, font=fc, fill=GOLD + (255,))
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0)); frame.alpha_composite(im, (PX, PY - 46)); frame.alpha_composite(cap, (PX, PY - 46 + PS + 6))
        p = os.path.join(OUT_DIR, "minimap_%02d.png" % (k + 1)); frame.save(p); out.append(p)
    return out


def windows(meta):
    """(start, end) of every stop: arrival is the hold start less the approach + orbit (8.5 s)."""
    st = meta["stops"]; T = meta["total_s"]
    starts = [s["hold"][0] - 8.5 for s in st]
    return [(max(0.0, a), (starts[k + 1] if k + 1 < len(starts) else T)) for k, a in enumerate(starts)]


def overlay_args(meta, first_input_index, last_label):
    """ffmpeg inputs + filter chain pieces to lay the map over [last_label]; returns (inputs, filters, new_label)."""
    pngs = build(meta["stops"]); inputs, fc, last = [], [], last_label
    for k, (png, (a, b)) in enumerate(zip(pngs, windows(meta))):
        idx = first_input_index + k
        inputs += ["-loop", "1", "-framerate", str(meta.get("fps", 30)), "-t", "%.2f" % (meta["total_s"] + 1), "-i", png]
        fc.append("[%d:v]format=rgba,fade=t=in:st=%.2f:d=0.5:alpha=1[m%d]" % (idx, a, idx))
        fc.append("%s[m%d]overlay=0:0:enable='between(t,%.2f,%.2f)'[w%d]" % (last, idx, a, b, idx)); last = "[w%d]" % idx
    return inputs, fc, last


def main():
    src, out = sys.argv[1], sys.argv[2]
    meta = json.load(open(os.path.join(MEDIA, "tour_stops.json"), encoding="utf-8"))
    inputs, fc, last = overlay_args(meta, 1, "[0:v]")
    n = int(subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-count_frames", "-select_streams", "v:0",
                            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip())
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", src] + inputs + ["-filter_complex", ";".join(fc), "-map", last,
                    "-frames:v", str(n), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", out], check=True)
    print("minimap over %d stops -> %s" % (len(meta["stops"]), out))


if __name__ == "__main__":
    main()
