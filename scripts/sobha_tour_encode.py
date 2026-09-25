"""Encode the Sobha tour: frames -> mp4 with the legend and, at every stop, four cards at the top - Metro, Schools,
Clinics & hospitals, closest beach - shown while the camera holds after its orbit.

Kendall, 24 Sep 2026: "4 cards, Metro, Schools, Clinics/Hospitals, and closest beach ... displayed at the top quickly so you
will need to pause after you rotate." ue_sobha_tour.py holds the camera HOLD_S after each orbit and writes the stop centres
and hold windows to data/media/sobha/tour_stops.json; this reads them.

  Metro     the nearest Metro station to the stop: RTA feeder-bus stops named "<station> Metro Station" (49 stations) plus
            every district's data/board/transit_<slug>.json nearest-station record (straight line)
  Schools   KHDA-listed schools within 5 km of the district centre (data/board/amenities_<slug>.json) and the nearest one
            rated Outstanding or Very good
  Clinics   DHA-licensed clinics (general / family practice, polyclinics) within 5 km, and the nearest hospital
  Beach     the nearest named public beach: OpenStreetMap natural=beach names in the cached land-use layers, plus the city's
            main public beaches (approximate points, marked "approx.")
Distances are straight-line and rounded, and the cards say so. Frames are deleted only when the mp4's decoded frame count
equals the number of frames rendered.
Usage: python scripts/sobha_tour_encode.py <frames dir> <out.mp4>
"""
import glob, json, math, os, shutil, subprocess, sys

from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, "data", "board"); CE = os.path.join(ROOT, "data", "ce")
STOPS = os.path.join(ROOT, "data", "media", "sobha", "tour_stops.json")
CARDS = os.path.join(ROOT, "data", "media", "sobha", "cards")
FF = r"C:\Users\kwils\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
FP = FF.replace("ffmpeg.exe", "ffprobe.exe")
FONT = r"C:\Windows\Fonts\segoeui.ttf"; FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"; FONT_SB = r"C:\Windows\Fonts\seguisb.ttf"
W, H = 1080, 1920          # v19: native 9:16 (HeyGen); bottom overlays sit 570 px lower than in the 4:5 cut
to_ll = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform
TITLES = {"sobhaheartland": "Sobha Hartland  ·  MBR City", "bukadra": "Sobha Hartland II", "rasalkhor": "Sobha One  ·  Ras Al Khor",
          "businessbay": "Business Bay", "motorcity": "Motor City  ·  Orbis & Solis", "althanyahfifth": "JLT  ·  Verde by Sobha",
          "jltnorth": "JLT  ·  Verde by Sobha", "jabalalifirst": "Sobha Central  ·  Sheikh Zayed Road", "dubaimarina": "Dubai Harbour  ·  SeaHaven",
          "jumeirahvillagecircle": "Jumeirah Village Circle", "madinatalmataar": "Dubai South"}
# the city's main public beaches (approximate points; OSM names in the cache are added on top)
PUBLIC_BEACHES = [("Al Mamzar Beach", 55.3453, 25.3000), ("Jumeirah Public Beach", 55.2505, 25.2335), ("La Mer", 55.2535, 25.2280),
                  ("Kite Beach", 55.1930, 25.1590), ("Sunset Beach, Umm Suqeim", 55.1885, 25.1435), ("Al Sufouh Beach", 55.1490, 25.1070),
                  ("JBR Beach", 55.1345, 25.0790)]
def is_clinic(h):
    c = (h.get("category") or "").lower(); sc = (h.get("subcategory") or "").lower()
    return c in ("general practice", "family medicine") or "polyclinic" in sc or sc.startswith("clinic") or "day surgery" in sc
GOOD = ("Outstanding", "Very good", "Very Good")


def km(a, b):
    return math.hypot((a[0] - b[0]) * 101.0, (a[1] - b[1]) * 111.0)


def metro_stations():
    """Every Metro station: RTA's bus feeder stops are named after the station they serve ("Al Fahidi Metro Station A1"),
    so the mean of those stops is the station to within a bus bay; plus the nearest-station records in transit_<slug>.json."""
    import csv, re, collections
    st = {}
    acc = collections.defaultdict(list)
    rp = os.path.join(ROOT, "data", "raw_downloads", "dd", "rta__public_transportation_routes_stops__2026-09-09.csv")
    if os.path.exists(rp):
        for r in csv.DictReader(open(rp, encoding="utf-8", errors="ignore")):
            m = re.match(r"(.+?) Metro Station", r.get("stop_name") or "")
            if m:
                try:
                    acc[m.group(1).strip()].append((float(r["stop_location_longitude"]), float(r["stop_location_latitude"])))
                except (TypeError, ValueError):
                    pass
    for nm, pts in acc.items():
        st[nm] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    for f in glob.glob(os.path.join(BOARD, "transit_*.json")):
        try:
            m = (json.load(open(f, encoding="utf-8")).get("nearest_anywhere") or {}).get("metro station")
        except Exception:
            continue
        if m and m.get("lon") is not None:
            st.setdefault(m["name"].replace(" Metro Station", ""), (m["lon"], m["lat"]))
    return st


def beaches():
    out = {n: (lon, lat, True) for n, lon, lat in PUBLIC_BEACHES}
    for f in glob.glob(os.path.join(CE, "*", "landuse_osm.json")):
        for e in json.load(open(f, encoding="utf-8")).get("elements", []):
            t = e.get("tags") or {}
            if t.get("natural") != "beach" or t.get("access") == "private" or not e.get("geometry"):
                continue
            nm = t.get("name:en") or (t.get("name") if (t.get("name") or "").isascii() else None)
            if nm and nm not in out:
                g = e["geometry"]; out[nm] = (sum(p["lon"] for p in g) / len(g), sum(p["lat"] for p in g) / len(g), False)
    return out


def facts(stop, stations, bchs):
    lon, lat = to_ll(*stop["utm"])
    p = (lon, lat)
    ms = min(stations.items(), key=lambda kv: km(p, kv[1]))
    am_path = os.path.join(BOARD, "amenities_%s.json" % stop["district"])
    am = json.load(open(am_path, encoding="utf-8")) if os.path.exists(am_path) else {"schools": [], "health": []}
    sch = [s for s in am.get("schools", []) if (s.get("km") or 99) <= 5]
    best = sorted([s for s in sch if (s.get("rating") or "") in GOOD], key=lambda s: s["km"])
    hl = am.get("health", [])
    clinics = [h for h in hl if (h.get("km") or 99) <= 5 and is_clinic(h)]
    hosp = sorted([h for h in hl if "hospital" in (h.get("subcategory") or "").lower()], key=lambda h: h["km"])
    # the city's known public beaches first; a mapped beach only when it is clearly (1.5 km+) closer
    pub = min(((n, v) for n, v in bchs.items() if v[2]), key=lambda kv: km(p, kv[1][:2]))
    osm = [(n, v) for n, v in bchs.items() if not v[2]]
    b = pub
    if osm:
        o = min(osm, key=lambda kv: km(p, kv[1][:2]))
        if km(p, o[1][:2]) < km(p, pub[1][:2]) - 1.5:
            b = o
    return {
        "metro": ("%.1f km" % km(p, ms[1]), ms[0].replace(" Metro Station", "")),
        "schools": ("%d within 5 km" % len(sch), ("%s: %s" % (best[0]["rating"].capitalize(), tidy(best[0]["name"].split(" - ")[0]))) if best else "KHDA-listed schools"),
        "clinics": ("%d clinics within 5 km" % len(clinics), ("Hospital %.1f km: %s" % (hosp[0]["km"], tidy(hosp[0]["name"]))) if hosp else "DHA-licensed facilities"),
        "beach": ("%.0f km%s" % (km(p, b[1][:2]), " (approx.)" if b[1][2] else ""), b[0]),
        "lonlat": (round(lon, 5), round(lat, 5)),
    }


def tidy(n):
    n = n.split("(")[0].split(" L.L")[0].split(" LLC")[0].split(" FZ")[0].split(" DIP")[0].strip(" ,-")
    return (n.title() if n.isupper() else n)[:32]


def rounded(d, xy, fill, r=18):
    d.rounded_rectangle(xy, radius=r, fill=fill)


def card_png(stop, f, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    fb = ImageFont.truetype(FONT_B, 34); fl = ImageFont.truetype(FONT_SB if os.path.exists(FONT_SB) else FONT_B, 19)
    fv = ImageFont.truetype(FONT_B, 34); fs = ImageFont.truetype(FONT, 20)
    title = TITLES.get(stop["district"], stop["name"].title())
    rounded(d, (40, 36, W - 40, 96), (8, 20, 28, 205), 16)
    d.rectangle((40, 36, 48, 96), fill=(197, 165, 106, 255))
    d.text((66, 44), title, font=fb, fill=(255, 255, 255, 255))
    cells = [("METRO", "metro"), ("SCHOOLS", "schools"), ("CLINICS & HOSPITALS", "clinics"), ("CLOSEST BEACH", "beach")]
    cw, ch = (W - 80 - 16) // 2, 132
    for k, (lab, key) in enumerate(cells):
        x0 = 40 + (k % 2) * (cw + 16); y0 = 108 + (k // 2) * (ch + 14)
        rounded(d, (x0, y0, x0 + cw, y0 + ch), (8, 20, 28, 190), 16)
        d.text((x0 + 22, y0 + 14), lab, font=fl, fill=(197, 165, 106, 255))
        v, sub = f[key]
        d.text((x0 + 22, y0 + 40), v, font=fv, fill=(255, 255, 255, 255))
        if d.textlength(sub, font=fs) > cw - 44:
            while d.textlength(sub + "…", font=fs) > cw - 44 and len(sub) > 8:
                sub = sub[:-1]
            sub = sub.rstrip(" ,(-") + "…"
        d.text((x0 + 22, y0 + 90), sub, font=fs, fill=(200, 210, 218, 255))
    d.text((44, 108 + 2 * (ch + 14) + 2), "Straight-line distances, rounded", font=ImageFont.truetype(FONT, 16), fill=(230, 235, 240, 200))
    img.save(path)


# v20: the HeyGen presenter stands bottom-right of the 9:16 frame, so the legend is a compact block bottom-LEFT
_F = r"fontfile='C\:/Windows/Fonts/segoeui.ttf'"
LEGEND = ("drawbox=x=40:y=1706:w=600:h=176:color=0x08141C@0.74:t=fill,"
          "drawbox=x=66:y=1728:w=28:h=28:color=0xD8DDE4@1:t=fill,"
          "drawtext=" + _F + ":text='Sobha - completed':x=108:y=1728:fontsize=25:fontcolor=white,"
          "drawbox=x=66:y=1778:w=28:h=28:color=0xD8DDE4@1:t=fill,drawbox=x=66:y=1778:w=28:h=28:color=0xFF7A10@1:t=4,"
          "drawtext=" + _F + ":text='Sobha - under construction (amber edge)':x=108:y=1778:fontsize=25:fontcolor=0xFFB060,"
          "drawbox=x=66:y=1828:w=28:h=28:color=0xDCE3EC@0.45:t=fill,"
          "drawtext=" + _F + ":text='Other developers':x=108:y=1828:fontsize=25:fontcolor=0xC8D0DA")


def main():
    frames, out = sys.argv[1], sys.argv[2]
    meta = json.load(open(STOPS, encoding="utf-8"))
    os.makedirs(CARDS, exist_ok=True)
    stations, bchs = metro_stations(), beaches()
    inputs, chains, last = [], [], "[base]"
    fc = ["[0:v]%s[base]" % LEGEND]
    summary = []
    for k, s in enumerate(meta["stops"]):
        if not s.get("hold"):
            continue
        f = facts(s, stations, bchs)
        png = os.path.join(CARDS, "stop%02d_%s.png" % (s["n"], s["district"])); card_png(s, f, png)
        summary.append({"n": s["n"], "district": s["district"], **{k2: v for k2, v in f.items()}})
        a, b = s["hold"][0] - 0.4, s["hold"][1] + 1.2
        idx = len(inputs) // 8 + 1; inputs += ["-loop", "1", "-framerate", str(meta.get("fps", 30)), "-t", "%.2f" % (meta["total_s"] + 1), "-i", png]
        fc.append("[%d:v]format=rgba,fade=t=in:st=%.2f:d=0.35:alpha=1,fade=t=out:st=%.2f:d=0.45:alpha=1[c%d]" % (idx, a, b - 0.45, idx))
        fc.append("%s[c%d]overlay=0:0:enable='between(t,%.2f,%.2f)'[v%d]" % (last, idx, a, b, idx)); last = "[v%d]" % idx
    json.dump(summary, open(os.path.join(CARDS, "cards.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in summary:
        print("stop %d %-15s metro %s | schools %s | clinics %s | beach %s" % (r["n"], r["district"], r["metro"], r["schools"][0], r["clinics"][0], r["beach"]))
    nj = len(glob.glob(os.path.join(frames, "*.jpeg")))
    cmd = [FF, "-y", "-loglevel", "error", "-framerate", str(meta.get("fps", 30)), "-start_number", "0", "-i", os.path.join(frames, "sobha_tour.%04d.jpeg")] + inputs + [
        "-filter_complex", ";".join(fc), "-map", last, "-frames:v", str(nj), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", "-shortest", out]
    subprocess.run(cmd, check=True)
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", out, "-vf", "scale=720:1280", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "27", "-movflags", "+faststart", out.replace(".mp4", "_phone.mp4")], check=True)
    nm = int(subprocess.run([FP, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip() or 0)
    print("mp4 frames %d of %d" % (nm, nj))
    if nj and nm == nj:
        shutil.rmtree(frames, ignore_errors=True); print("frames cleared")
    else:
        print("frames KEPT")


if __name__ == "__main__":
    main()
