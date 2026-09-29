"""Najma globe - property sales per day (INTERNAL TEST, not for publication).

ArcGIS Pro 3.7 arcpy (headless) renders a 3D global scene with extruded columns;
Pillow composites Naj-style overlays (chips, flags, story card); ffmpeg encodes clips.

Run with Pro's python:
  "%LOCALAPPDATA%\\Programs\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts\\globe_transactions.py [stage ...]
Stages (default all): build render composite encode
All figures come from data/globe/cities.csv - edit it and re-run (build must re-run for heights).
"""
import csv, json, math, os, shutil, subprocess, sys

ROOT = r"C:\Dev\naj-market-pulse"
GDIR = os.path.join(ROOT, "data", "globe")
GDB = os.path.join(GDIR, "globe.gdb")
APRX = os.path.join(GDIR, "globe.aprx")
CSV = os.path.join(GDIR, "cities.csv")
WORK = os.path.join(GDIR, "_work")            # rendered + composited frames (disposable)
OUT = os.path.join(ROOT, "data", "media", "globe")
BLANK = os.path.join(os.environ["LOCALAPPDATA"], r"Programs\ArcGIS\Pro\Resources\ArcToolBox\Services\routingservices\data\Blank.aprx")
FFMPEG = os.path.join(os.environ["LOCALAPPDATA"], r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe")
IMAGERY = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer"

RFPS = 12.5          # rendered fps (frames doubled to 25 in composite)
FPS = 25
ASPECTS = {"9x16": (1080, 1920), "16x9": (1920, 1080)}
FOCAL = {"9x16": 2143.0, "16x9": 2143.0}   # pixels; Pro scene FOV ~48 deg on the long side (calibrated, see README)

# ----------------------------------------------------------------- data
def load_cities():
    rows = []
    with open(CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["lat"], r["lon"], r["per_day"] = float(r["lat"]), float(r["lon"]), float(r["per_day"])
            r["include_in_combined"] = r["include_in_combined"].strip().lower() == "true"
            rows.append(r)
    for r in rows:   # linear scaling (see KM_PER_UNIT) - Monaco is intentionally a stub
        r["height_m"] = KM_PER_UNIT * r["per_day"]
        r["style"] = "hero" if r["city"] == "Dubai" else ("hollow" if not r["include_in_combined"] else "std")
    return rows

def fmt_rate(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v < 10 else f"{v:,.0f}"

# ----------------------------------------------------------------- geodesy / camera
A, E2 = 6378137.0, 6.69437999014e-3
def ecef(lat, lon, h=0.0):
    la, lo = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
    return ((n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo), (n * (1 - E2) + h) * math.sin(la))
def geodetic(x, y, z):
    lon = math.atan2(y, x); p = math.hypot(x, y); lat = math.atan2(z, p * (1 - E2))
    for _ in range(6):
        n = A / math.sqrt(1 - E2 * math.sin(lat) ** 2); h = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - E2 * n / (n + h)))
    return math.degrees(lat), math.degrees(lon), h
def enu(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    e = (-math.sin(lo), math.cos(lo), 0.0)
    n = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    u = (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))
    return e, n, u
add = lambda a, b: tuple(x + y for x, y in zip(a, b)); sub = lambda a, b: tuple(x - y for x, y in zip(a, b))
mul = lambda a, s: tuple(x * s for x in a); dot = lambda a, b: sum(x * y for x, y in zip(a, b))
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def norm(a): l = math.sqrt(dot(a, a)); return mul(a, 1 / l)

def camera(key):
    """key = (lat, lon, range_m, tilt_deg_from_nadir, heading_deg) look-at -> camera dict."""
    lat, lon, rng, tilt, hd = key
    T = ecef(lat, lon); e, n, u = enu(lat, lon)
    dirh = add(mul(e, math.sin(math.radians(hd))), mul(n, math.cos(math.radians(hd))))
    C = add(T, add(mul(dirh, -rng * math.sin(math.radians(tilt))), mul(u, rng * math.cos(math.radians(tilt)))))
    clat, clon, calt = geodetic(*C)
    ce, cn, cu = enu(clat, clon)
    f = norm(sub(T, C))
    heading = math.degrees(math.atan2(dot(f, ce), dot(f, cn)))
    pitch = math.degrees(math.atan2(dot(f, cu), math.hypot(dot(f, ce), dot(f, cn))))
    upv = sub(cu, mul(f, dot(cu, f)))
    if dot(upv, upv) < 1e-6: upv = add(mul(ce, math.sin(math.radians(hd))), mul(cn, math.cos(math.radians(hd))))
    up = norm(upv); right = cross(f, up)
    return dict(X=clon, Y=clat, Z=calt, heading=heading, pitch=pitch, C=C, f=f, up=up, right=right)

def project(cam, lat, lon, h, W, H, F):
    P = ecef(lat, lon, h); v = sub(P, cam["C"]); z = dot(v, cam["f"])
    if z <= 0: return None
    _, _, nrm = enu(lat, lon)
    if dot(v, nrm) > 0 and h < 1: return None          # far side of the globe
    return (W / 2 + F * dot(v, cam["right"]) / z, H / 2 - F * dot(v, cam["up"]) / z)

# ----------------------------------------------------------------- timeline (beats)
def ease(t): t = max(0.0, min(1.0, t)); return t * t * (3 - 2 * t)
def slerp_ll(a, b, t):
    pa, pb = norm(ecef(a[0], a[1])), norm(ecef(b[0], b[1]))
    om = math.acos(max(-1, min(1, dot(pa, pb))))
    if om < 1e-9: return a[0], a[1]
    p = add(mul(pa, math.sin((1 - t) * om) / math.sin(om)), mul(pb, math.sin(t * om) / math.sin(om)))
    return math.degrees(math.asin(p[2])), math.degrees(math.atan2(p[1], p[0]))
def lerp_key(a, b, t, bump=0.0):
    t = ease(t); lat, lon = slerp_ll(a, b, t)
    rng = math.exp(math.log(a[2]) * (1 - t) + math.log(b[2]) * t) * (1 + bump * math.sin(math.pi * t))
    return (lat, lon, rng, a[3] + (b[3] - a[3]) * t, a[4] + (b[4] - a[4]) * t)
def track(keys, t, interp):
    """keys: [(time, value)]; eased interpolation between consecutive keys."""
    if t <= keys[0][0]: return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1: return interp(v0, v1, (t - t0) / (t1 - t0) if t1 > t0 else 1.0)
    return keys[-1][1]
def ease_out(t): t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3
def ease_back(t, k=1.6): t = max(0.0, min(1.0, t)); t -= 1; return 1 + (k + 1) * t ** 3 + k * t ** 2
def ease_bounce(t):
    t = max(0.0, min(1.0, t))
    if t < 0.7: return (t / 0.7) ** 2
    u = (t - 0.7) / 0.3; return 1 - 0.12 * math.sin(math.pi * u)
num = lambda a, b, u: a + (b - a) * ease_out(u)      # values count up with ease-out

# Camera look-at keys: (target lat, target lon, range m, tilt from nadir deg, heading deg). North-up, calm.
# Each view is centred on a point, then offset so that point sits in the globe area of the layout
# (9:16 -> upper ~60% of the frame; 16:9 -> left ~60%), leaving room for the comparison card.
def views(aspect):
    tall = aspect == "9x16"; W, H = ASPECTS[aspect]; F = FOCAL[aspect]
    def v(lat, lon, rng, tilt=15.0):
        if tall: lat -= (0.19 * H) * rng / F / 111e3
        else: lon += (0.19 * W) * rng / F / (111e3 * math.cos(math.radians(lat)))
        return (lat, lon, rng, tilt, 0.0)
    return {
        "EARTH":  v(32.0, 28.0, 17000e3, 5.0),
        "Dubai":  v(25.2, 55.27, 6000e3),
        "London": v(51.5, -0.13, 4500e3),
        "Paris":  v(48.86, 2.35, 4500e3),
        "Monaco": v(43.74, 7.42, 4500e3),
        "Singapore": v(1.35, 103.82, 6000e3),
        "WIDE":   v(38.0, 27.0, 11500e3 if tall else 9500e3),
    }

# Default film beats (narration plan). cam: [(t, view)], h: {city: [(t, per_day_value)]}; dur seconds.
# "h" drives the value shown (pin drop-in + bar fill); "combined" shows the L+P+M total line.
BEATS = [
    dict(name="b1_earth_to_dubai", dur=6.0, focus="Dubai",
         cam=[(0, "EARTH"), (1.0, "EARTH"), (4.0, "Dubai")], h={"Dubai": [(3.9, 0), (4.6, "v")]}),
    dict(name="b2_london", dur=4.0, focus="London",
         cam=[(0, "Dubai"), (2.2, "London")], h={"London": [(2.2, 0), (2.9, "v")]}),
    dict(name="b3_paris", dur=2.0, focus="Paris",
         cam=[(0, "London"), (1.0, "Paris")], h={"Paris": [(0.9, 0), (1.6, "v")]}),
    dict(name="b4_monaco", dur=2.0, focus="Monaco",
         cam=[(0, "Paris"), (1.0, "Monaco")], h={"Monaco": [(0.9, 0), (1.6, "v")]}),
    dict(name="b5_pullback_all", dur=5.0, focus=None, combined=True,
         cam=[(0, "Monaco"), (3.0, "WIDE")], h={}),
    dict(name="b6_dubai_spike", dur=5.0, focus="Dubai", spike=True, combined=True,
         cam=[(0, "WIDE"), (1.5, "Dubai")], h={"Dubai": [(0.8, "v"), (1.5, "peak")]}),      # reach 1,307 by ~20.5 s and hold (no count-down)
    # b7 split (28 Sep, question-bank timing): hold the busiest-day card until ~27.8 s ("two and a half years"), then snap to the compare card at 460
    dict(name="b7_wide_hold", dur=3.8, focus="Dubai", spike=True, combined=True, cam=[(0, "Dubai"), (1.8, "WIDE")], h={}),
    dict(name="b7b_compare_hold", dur=1.2, focus=None, combined=True, cam=[(0, "WIDE")], h={"Dubai": [(-0.04, "v")]}),
]
OPTIONAL_ALL = [
    dict(name="x1_singapore_optional", dur=5.0, focus="Singapore",
         cam=[(0, "WIDE"), (2.5, "Singapore")], h={"Singapore": [(2.4, 0), (3.4, "v")]}),
]
OPTIONAL = OPTIONAL_ALL if os.environ.get("GLOBE_SINGAPORE") == "1" else []   # set GLOBE_SINGAPORE=1 to render the optional clip
PEAK = {"Dubai": 1307}
KM_PER_UNIT = 1500e3 / 460.0      # LINEAR height: Dubai 460/day = 1,500 km, so heights compare honestly

def build_frames(cities, aspect):
    """-> list of clips {name, beat, frames:[state]} ; state = dict(key, vals{city:per_day shown}, t)."""
    V = views(aspect); by = {c["city"]: c for c in cities}
    vals = {c["city"]: 0.0 for c in cities}
    clips = []
    def run(beats, start_vals):
        cur = dict(start_vals)
        for b in beats:
            n = int(round(b["dur"] * FPS)); frames = []
            begin = dict(cur)
            for fi in range(n):
                t = fi / FPS
                key = track([(tt, V[v]) for tt, v in b["cam"]], t, lambda a, c, u: lerp_key(a, c, u, b.get("bump", 0.0)))
                st = dict(begin)
                for city, ks in b["h"].items():
                    kk = [(tt, by[city]["per_day"] if v == "v" else PEAK[city] if v == "peak" else float(v)) for tt, v in ks]
                    st[city] = track(kk, t, num)
                frames.append(dict(key=key, vals=st, t=t))
            cur = dict(frames[-1]["vals"])
            clips.append(dict(name=b["name"], beat=b, frames=frames))
        return cur
    end = run(BEATS, vals)
    run(OPTIONAL, end)
    return clips

def render_id(fr):
    """Frames are rendered at RFPS; identical states are reused (static holds)."""
    return json.dumps([round(x, 4) for x in fr["key"]])   # Pro renders camera only; columns drawn in composite

# ----------------------------------------------------------------- stage: build (arcpy)
def stage_build(cities):
    import arcpy
    arcpy.env.overwriteOutput = True
    if not arcpy.Exists(GDB): arcpy.management.CreateFileGDB(GDIR, "globe.gdb")
    sr = arcpy.SpatialReference(4326)
    pts = os.path.join(GDB, "cities"); arcpy.management.CreateFeatureclass(GDB, "cities", "POINT", spatial_reference=sr)
    for fld, typ in [("name", "TEXT"), ("country", "TEXT"), ("per_day", "DOUBLE"), ("peak", "DOUBLE"),
                     ("height_m", "DOUBLE"), ("style", "TEXT"), ("in_combined", "SHORT"), ("note", "TEXT")]:
        arcpy.management.AddField(pts, fld, typ, field_length=255 if typ == "TEXT" else None)
    with arcpy.da.InsertCursor(pts, ["SHAPE@XY", "name", "country", "per_day", "peak", "height_m", "style", "in_combined", "note"]) as cur:
        for c in cities:
            peak = 1307 if c["city"] == "Dubai" else None
            cur.insertRow(((c["lon"], c["lat"]), c["city"], c["country"], c["per_day"], peak, c["height_m"], c["style"], int(c["include_in_combined"]), c["note"]))
    cols = os.path.join(GDB, "columns")
    arcpy.analysis.Buffer(pts, cols, "90 Kilometers", method="GEODESIC")
    if os.path.exists(APRX): os.remove(APRX)
    shutil.copy(BLANK, APRX)
    p = arcpy.mp.ArcGISProject(APRX)
    for m in p.listMaps(): p.deleteItem(m)
    m = p.createMap("Najma Globe", "GLOBE")
    m.addDataFromPath(IMAGERY)
    lyr = m.addDataFromPath(cols); lyr.name = "Sales per day columns"
    sym = lyr.symbology; sym.updateRenderer("UniqueValueRenderer"); sym.renderer.fields = ["style"]
    colors = {"hero": [214, 170, 62, 100], "std": [246, 241, 228, 100], "hollow": [150, 200, 230, 45]}
    for grp in sym.renderer.groups:
        for it in grp.items:
            v = it.values[0][0]
            it.symbol.color = {"RGB": colors.get(v, [255, 255, 255, 100])}
            it.symbol.outlineColor = {"RGB": [20, 80, 60, 100] if v != "hollow" else [230, 245, 255, 100]}
            it.symbol.outlineWidth = 0.6 if v != "hollow" else 2.0
    lyr.symbology = sym
    d = lyr.getDefinition("V3")
    ex = arcpy.cim.CreateCIMObjectFromClassName("CIMFeatureExtrusion", "V3")
    ex.extrusionType = "Absolute"; ex.extrusionExpression = "[height_m]"; ex.extrusionUnit = "Meters"
    d.extrusion = ex
    p3 = arcpy.cim.CreateCIMObjectFromClassName("CIM3DLayerProperties", "V3")
    p3.isLayerLit = True; p3.castShadows = False
    d.layer3DProperties = p3                  # puts the layer in the 3D category (needed for extrusion)
    lyr.setDefinition(d)
    # Headless layout exports draw this layer draped (flat): extrusion only shows in the Pro GUI.
    # The film therefore draws the columns in the composite pass with the same camera maths; layer kept for GUI use.
    lyr.visible = False
    for name, (W, H) in ASPECTS.items():
        lay = p.createLayout(W, H, "POINT", f"Globe {name}")
        lay.createMapFrame(arcpy.Extent(0, 0, W, H), m, "Globe frame")
    p.save()
    print("built", GDB, APRX)

# ----------------------------------------------------------------- stage: render (arcpy)
def raw_path(aspect, fr):
    import hashlib
    return os.path.join(WORK, aspect, "raw", hashlib.md5(render_id(fr).encode()).hexdigest()[:16] + ".png")

def set_camera(mf, cam):
    """Map-frame camera via CIM (arcpy's MapFrame.camera stays in 2D 'MAP' mode headless).
    NB Pro's CIM heading is counter-clockwise, i.e. the negative of a compass bearing."""
    cim = mf.getDefinition("V3"); cim.view.viewingMode = "SceneGlobal"; c = cim.view.camera
    c.x, c.y, c.z, c.heading, c.pitch, c.roll = cam["X"], cam["Y"], cam["Z"], -cam["heading"], cam["pitch"], 0
    mf.setDefinition(cim)

def stage_render(cities, only=None):
    import arcpy, time
    p = arcpy.mp.ArcGISProject(APRX)
    cols = os.path.join(GDB, "columns")
    for aspect in ASPECTS:
        if only and aspect not in only: continue
        os.makedirs(os.path.join(WORK, aspect, "raw"), exist_ok=True)
        lay = p.listLayouts(f"Globe {aspect}")[0]; mf = lay.listElements("MAPFRAME_ELEMENT")[0]
        for clip in build_frames(cities, aspect):
            for fi in range(0, len(clip["frames"]), int(FPS / RFPS)):
                fr = clip["frames"][fi]; fn = raw_path(aspect, fr)
                if os.path.exists(fn): continue
                set_camera(mf, camera(fr["key"]))
                t = time.time(); lay.exportToPNG(fn, resolution=72)
                print(aspect, clip["name"], fi, f"{time.time()-t:.1f}s", flush=True)

# ----------------------------------------------------------------- stage: composite (Pillow)
IVORY, GOLD, GOLD_L, GREEN, INK, MUTED = (251, 248, 239), (201, 152, 58), (232, 201, 138), (20, 80, 60), (31, 42, 48), (92, 104, 110)
FONT_H = r"C:\Windows\Fonts\georgiab.ttf"     # Playfair Display not on disk -> Georgia Bold
FONT_B = r"C:\Windows\Fonts\segoeui.ttf"      # Inter not on disk -> Segoe UI
FONT_BB = r"C:\Windows\Fonts\segoeuib.ttf"

def make_flag(cc, w=54, h=36):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), "white"); d = ImageDraw.Draw(im)
    if cc == "FR":
        d.rectangle([0, 0, w/3, h], fill=(0, 35, 149)); d.rectangle([2*w/3, 0, w, h], fill=(237, 41, 57))
    elif cc == "MC":
        d.rectangle([0, 0, w, h/2], fill=(206, 17, 38))
    elif cc == "SG":
        d.rectangle([0, 0, w, h/2], fill=(239, 51, 64))
        d.ellipse([5, 3, 17, 15], fill="white"); d.ellipse([8, 3, 20, 15], fill=(239, 51, 64))
        for x, y in [(20, 5), (24, 8), (22, 12), (18, 12), (17, 8)]: d.ellipse([x-1, y-1, x+1, y+1], fill="white")
    elif cc == "AE":
        d.rectangle([0, 0, w, h/3], fill=(0, 115, 47)); d.rectangle([0, 2*h/3, w, h], fill=(0, 0, 0))
        d.rectangle([0, 0, w/4, h], fill=(255, 0, 0))
    elif cc == "GB":
        d.rectangle([0, 0, w, h], fill=(1, 33, 105))
        d.line([0, 0, w, h], fill="white", width=7); d.line([0, h, w, 0], fill="white", width=7)
        d.line([0, 0, w, h], fill=(200, 16, 46), width=2); d.line([0, h, w, 0], fill=(200, 16, 46), width=2)
        d.rectangle([w/2-5, 0, w/2+5, h], fill="white"); d.rectangle([0, h/2-5, w, h/2+5], fill="white")
        d.rectangle([w/2-3, 0, w/2+3, h], fill=(200, 16, 46)); d.rectangle([0, h/2-3, w, h/2+3], fill=(200, 16, 46))
    d.rectangle([0, 0, w-1, h-1], outline=(200, 200, 200))
    return im

def draw_pin(d, x, y, fill, outline, s, drop=1.0, pulse=None):
    """Classic teardrop map pin with its tip at (x, y). drop 0->1 = drop-in with a small bounce."""
    if drop <= 0: return
    e = ease_bounce(drop); y = y - (1 - e) * 70 * s; a = int(255 * min(1.0, drop * 3))
    r = 13 * s; cy = y - 2.3 * r
    if pulse is not None:
        rr = (10 + 40 * pulse) * s
        d.ellipse([x - rr, y - rr * 0.45, x + rr, y + rr * 0.45], outline=GOLD + (int(230 * (1 - pulse)),), width=max(2, int(3 * s)))
    d.ellipse([x - 7*s, y - 2.5*s, x + 7*s, y + 2.5*s], fill=(0, 0, 0, int(a * 0.35)))
    d.polygon([(x - r * 0.86, cy + r * 0.5), (x + r * 0.86, cy + r * 0.5), (x, y)], fill=fill + (a,), outline=outline + (a,))
    d.ellipse([x - r, cy - r, x + r, cy + r], fill=fill + (a,), outline=outline + (a,), width=max(2, int(2.5 * s)))
    d.polygon([(x - r * 0.78, cy + r * 0.45), (x + r * 0.78, cy + r * 0.45), (x, y - 3 * s)], fill=fill + (a,))
    d.ellipse([x - r * 0.38, cy - r * 0.38, x + r * 0.38, cy + r * 0.38], fill=outline + (a,))

def is_spike(beat, city, v):
    return bool(beat.get("spike")) and city["city"] in PEAK and v > city["per_day"] * 1.05

def chip(city, value, flags, fonts, emph, s, beat=None):
    """Ivory chip: flag + City (serif) + 'N / day' (or the busiest-day count on the spike)."""
    from PIL import Image, ImageDraw
    fh, fb = fonts["h"](int(30*s)), fonts["b"](int(22*s))
    rate = f"{value:,.0f} sales · 9 Feb 2026" if beat and is_spike(beat, city, value) else f"{fmt_rate(value)} / day"
    fl = flags[city["country"]].resize((int(42*s), int(28*s)))
    tw = max(fh.getlength(city["city"]), fb.getlength(rate))
    W, H = int(fl.width + tw + 44*s), int(84*s)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W-1, H-1], radius=int(14*s), fill=IVORY + (245,), outline=(GOLD if emph else GOLD_L) + (255,), width=max(2, int((4 if emph else 2)*s)))
    im.paste(fl, (int(14*s), int(14*s)))
    x = fl.width + int(26*s)
    d.text((x, int(8*s)), city["city"], font=fh, fill=INK)
    d.text((x, int(44*s)), rate, font=fb, fill=GREEN if emph else MUTED)
    return im

ROWS = ("Dubai", "London", "Paris", "Monaco")

def comparison_card(st, by, flags, fonts, pw, ph, s):
    """Persistent Naj-style panel. st = animation state from Compositor.state()."""
    from PIL import Image, ImageDraw
    beat = st["beat"]; vals = st["vals"]; focus = beat.get("focus")
    im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=int(22 * s), fill=IVORY + (248,), outline=GOLD_L + (255,), width=max(2, int(3 * s)))
    pad = int(30 * s); x0 = pad; y = int(24 * s)
    d.text((x0, y), "PROPERTY SALES · PER DAY", font=fonts["bb"](int(32 * s)), fill=GOLD); y += int(52 * s)
    # header (crossfades / slides in at each beat change)
    hh = int(118 * s)
    hdr = Image.new("RGBA", (pw, hh), (0, 0, 0, 0)); hd = ImageDraw.Draw(hdr)
    if focus and vals.get(focus, 0) > 0:
        c = by[focus]; v = vals[focus]
        hdr.paste(flags[c["country"]].resize((int(48 * s), int(32 * s))), (x0, int(14 * s)))
        hd.text((x0 + int(62 * s), 0), c["city"], font=fonts["h"](int(50 * s)), fill=INK)
        numt = f"{v:,.0f}" if v >= 10 else fmt_rate(v); fn = fonts["h"](int(62 * s))
        hd.text((pw - pad - fn.getlength(numt), -int(6 * s)), numt, font=fn, fill=GOLD if focus == "Dubai" else GREEN)
        line = "Busiest day · 9 Feb 2026" if is_spike(beat, c, v) else f"{c['note'].split(';')[0]} · {c['source']}"
        fs = fonts["b"](int(21 * s))
        while fs.getlength(line) > pw - 2 * pad and len(line) > 10: line = line[:-2]
        hd.text((x0, int(70 * s)), line, font=fs, fill=MUTED)
    else:
        hd.text((x0, int(8 * s)), "Four markets compared", font=fonts["h"](int(46 * s)), fill=INK)
    hx = st["hdr"]; hdr.putalpha(hdr.getchannel("A").point(lambda a: int(a * hx)))
    im.alpha_composite(hdr, (0, y + int((1 - hx) * 18 * s)))
    y += hh
    d.line([x0, y, pw - pad, y], fill=GOLD_L + (255,), width=max(1, int(2 * s))); y += int(18 * s)
    scale = max(460.0, vals.get("Dubai", 0.0))
    lab_w = int(250 * s); num_w = int(120 * s); bar_x = x0 + lab_w; bar_w = pw - pad - num_w - bar_x
    rows = [r for r in ROWS if r in by]
    rh = int(min(62 * s, (ph - y - (110 * s if beat.get("combined") else 30 * s)) / len(rows)))
    if st["hl"] is not None:        # highlight glides between rows
        hy = y + st["hl"] * rh
        d.rounded_rectangle([x0 - int(12 * s), hy - int(4 * s), pw - pad + int(12 * s), hy + rh - int(6 * s)], radius=int(10 * s), fill=tuple(int(IVORY[k] + (hc - IVORY[k]) * st["hl_a"]) for k, hc in enumerate((246, 236, 210))) + (248,))
    for i, name in enumerate(rows):
        c = by[name]; v = vals.get(name, 0.0); hl = name == focus
        im.paste(flags[c["country"]].resize((int(33 * s), int(22 * s))), (x0, y + int(rh / 2 - 14 * s)))
        label = "Dubai · busiest day" if is_spike(beat, c, v) else name
        fnt = fonts["bb" if hl else "b"](int(25 * s if len(label) < 12 else 21 * s))
        d.text((x0 + int(44 * s), y + int(rh / 2 - 20 * s)), label, font=fnt, fill=INK if v > 0 else MUTED)
        bh = int(20 * s); by_ = y + int(rh / 2 - bh / 2 - 3 * s)
        d.rounded_rectangle([bar_x, by_, bar_x + bar_w, by_ + bh], radius=bh // 2, fill=(236, 230, 214, 255))
        if v > 0:
            L = max(bh, int(bar_w * min(1.02, v * st["bar_boost"].get(name, 1.0) / scale)))
            d.rounded_rectangle([bar_x, by_, bar_x + L, by_ + bh], radius=bh // 2, fill=(GOLD if name == "Dubai" else GREEN) + (255,))
        t = (f"{v:,.0f}" if v >= 10 else fmt_rate(v)) if v > 0 else "–"; fnn = fonts["bb"](int(25 * s))
        d.text((pw - pad - fnn.getlength(t), y + int(rh / 2 - 20 * s)), t, font=fnn, fill=INK if v > 0 else MUTED)
        y += rh
    if beat.get("combined"):
        others = [n for n in rows if n != "Dubai" and by[n]["include_in_combined"]]
        tot = sum(by[n]["per_day"] for n in others) * st["comb"]
        y += int(10 * s); d.line([x0, y, pw - pad, y], fill=GOLD_L + (255,), width=max(1, int(2 * s))); y += int(14 * s)
        d.text((x0, y), " + ".join(others), font=fonts["b"](int(28 * s)), fill=MUTED)
        bh = int(20 * s); by_ = y + int(34 * s)
        d.rounded_rectangle([bar_x, by_, bar_x + bar_w, by_ + bh], radius=bh // 2, fill=(236, 230, 214, 255))
        if tot > 0: d.rounded_rectangle([bar_x, by_, bar_x + max(bh, int(bar_w * tot / scale)), by_ + bh], radius=bh // 2, fill=(92, 140, 120, 255))
        d.text((x0, by_ - int(4 * s)), "Combined", font=fonts["bb"](int(30 * s)), fill=INK)
        t = f"{tot:,.0f} / day"; fnn = fonts["bb"](int(25 * s)); d.text((pw - pad - fnn.getlength(t), by_ - int(4 * s)), t, font=fnn, fill=INK)
    return im

def corner_marks(fonts, W, H, s, najma_xy):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    f = fonts["bb"](int(22 * s)); t = "N A J M A"; tw = f.getlength(t)
    x0, y0 = najma_xy
    d.rounded_rectangle([x0, y0, x0 + tw + 34 * s, y0 + 44 * s], radius=int(22 * s), fill=IVORY + (235,), outline=GOLD + (255,), width=2)
    d.text((x0 + 17 * s, y0 + 8 * s), t, font=f, fill=GREEN)
    # (internal tag removed on Kendall's request, 28 Sep; the use remains internal per the Bible)
    return im

def layout(aspect):
    W, H = ASPECTS[aspect]
    if aspect == "9x16":
        s = 1.0; pw, ph = W - 48, int(H * 0.33); return s, (24, H - ph - 90), (pw, ph), (28, H - 70)
    s = 0.85; pw, ph = int(W * 0.36), int(560 * 0.85); return s, (W - pw - 36, 90), (pw, ph), (W - pw - 36, H - 66)

def seg_u(keys, t):
    """Raw progress (0..1) of t within the first..last key span, or None outside it."""
    if not keys or t < keys[0][0]: return None
    if t > keys[-1][0]: return None
    return (t - keys[0][0]) / max(1e-6, keys[-1][0] - keys[0][0])

class Compositor:
    def __init__(self, cities):
        from PIL import ImageFont
        self.fonts = {"h": lambda z: ImageFont.truetype(FONT_H, z), "b": lambda z: ImageFont.truetype(FONT_B, z), "bb": lambda z: ImageFont.truetype(FONT_BB, z)}
        self.cities = cities; self.by = {c["city"]: c for c in cities}
        self.flags = {c["country"]: make_flag(c["country"], 96, 64) for c in cities}
        self.marks = {}
        allb = BEATS + OPTIONAL
        self.start = {}; self.prev_focus = {}; t = 0.0; pf = None
        for b in allb:
            self.start[b["name"]] = t; self.prev_focus[b["name"]] = pf
            if not b["name"].startswith("x"): t += b["dur"]
            pf = b.get("focus")

    def state(self, clip, fi):
        b = clip["beat"]; fr = clip["frames"][fi]; t = fr["t"]; focus = b.get("focus")
        rows = [r for r in ROWS if r in self.by]
        hdr = ease_out(t / 0.3) if b["name"] != BEATS[0]["name"] else 1.0
        pf = self.prev_focus[b["name"]]
        def idx(n): return rows.index(n) if n in rows else None
        i1, i0 = idx(focus) if focus else None, idx(pf) if pf else None
        if i1 is None: hl, hl_a = (i0, 1 - ease_out(t / 0.35)) if i0 is not None else (None, 0)
        elif i0 is None: hl, hl_a = i1, ease_out(t / 0.35)
        else: hl, hl_a = i0 + (i1 - i0) * ease_out(t / 0.35), 1.0
        boost = {}
        for city, ks in b["h"].items():
            u = seg_u(ks, t)
            if u is not None: boost[city] = 1 + 0.06 * math.sin(math.pi * min(1.0, u * 1.25))  # tiny overshoot
        comb = ease_out(t / 0.8) if (b.get("combined") and b["name"] == "b5_pullback_all") else 1.0
        card_in = ease_out(t / 0.4) if b["name"] == BEATS[0]["name"] else 1.0
        return dict(beat=b, vals=fr["vals"], hdr=hdr, hl=hl, hl_a=hl_a, bar_boost=boost, comb=comb, card_in=card_in,
                    T=self.start[b["name"]] + t)

    def frame(self, aspect, clip, fi):
        from PIL import Image, ImageDraw
        W, H = ASPECTS[aspect]; F = FOCAL[aspect]; s, cpos, csize, npos = layout(aspect)
        if aspect not in self.marks: self.marks[aspect] = corner_marks(self.fonts, W, H, s, npos)
        step = int(FPS / RFPS); fr = clip["frames"][fi]; rfr = clip["frames"][fi - fi % step]
        b = clip["beat"]; focus = b.get("focus"); t = fr["t"]; st = self.state(clip, fi); T = st["T"]
        # continuous slow drift over the whole film (zoom + pan) so the globe never freezes
        z = 1.045 + 0.03 * math.sin(2 * math.pi * T / 17.0)
        panx = 0.012 * W * math.sin(2 * math.pi * T / 23.0); pany = 0.008 * H * math.cos(2 * math.pi * T / 19.0)
        gcx, gcy = (W / 2, H * 0.32) if aspect == "9x16" else (W * 0.32, H / 2)
        def xf(p): return ((p[0] - gcx) * z + gcx + panx, (p[1] - gcy) * z + gcy + pany)
        raw = Image.open(raw_path(aspect, rfr)).convert("RGB")
        x0, y0 = xf((0, 0)); x1, y1 = xf((W, H))
        # inverse: crop the source box that maps onto the frame
        box = ((0 - x0) / z, (0 - y0) / z, (W - x0) / z, (H - y0) / z)
        base = raw.transform((W, H), Image.EXTENT, box, resample=Image.BICUBIC).convert("RGBA")
        cam = camera(rfr["key"])
        pins = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(pins); spots = []
        rise_end = max([k[-1][0] for k in b["h"].values()] or [0])
        for c in self.cities:
            v = fr["vals"][c["city"]]
            if v <= 0: continue
            p = project(cam, c["lat"], c["lon"], 0, W, H, F)
            if not p: continue
            p = xf(p)
            if not (-40 < p[0] < W + 40 and -40 < p[1] < H + 40): continue
            ks = b["h"].get(c["city"])
            if ks and not b.get("spike"):
                u = seg_u(ks, t); drop = 1.0 if u is None and t > ks[-1][0] else (0.0 if u is None else min(1.0, u * 1.4))
                pop_t = ks[0][0] + (ks[-1][0] - ks[0][0]) / 1.4
            else:
                drop, pop_t = 1.0, (0.0 if c["city"] == focus else -9)
            pulse = ((t - rise_end) * 0.9) % 1.0 if (c["city"] == focus and t >= rise_end) else None
            hero = c["city"] == "Dubai"
            draw_pin(d, p[0], p[1], (214, 170, 62) if hero else (248, 244, 232), (120, 86, 20) if hero else (31, 42, 48),
                     s * (1.35 if c["city"] == focus else 1.0), drop=drop, pulse=pulse)
            if drop >= 1.0: spots.append((c, v, p, pop_t))
        base.alpha_composite(pins)
        clean = base.convert("RGB")
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); placed = []
        for c, v, p, pop_t in sorted(spots, key=lambda x: x[0]["city"] == focus):
            emph = c["city"] == focus
            pop = 0.9 + 0.1 * ease_back((t - pop_t) / 0.3) if t >= pop_t else 1.0
            ch = chip(c, v, self.flags, self.fonts, emph, s * (0.95 if emph else 0.7) * pop, b)
            if focus and not emph: ch.putalpha(ch.getchannel("A").point(lambda a: int(a * 0.85)))
            x = int(min(W - ch.width - 10, max(10, p[0] + 18 * s))); y = int(p[1] - 40 * s - ch.height)
            for (px, py, pw_, ph_) in placed:
                if x < px + pw_ and px < x + ch.width and y < py + ph_ and py < y + ch.height: y = py - ch.height - 6
            ov.alpha_composite(ch, (x, max(70, y))); placed.append((x, y, ch.width, ch.height))
        card = comparison_card(st, self.by, self.flags, self.fonts, csize[0], csize[1], s)
        if st["card_in"] < 1:
            card.putalpha(card.getchannel("A").point(lambda a: int(a * st["card_in"])))
        ov.alpha_composite(card, (cpos[0], cpos[1] + int((1 - st["card_in"]) * 60 * s)))
        ov.alpha_composite(self.marks[aspect])
        o = base.copy(); o.alpha_composite(ov)
        return clean, o.convert("RGB")

def stage_composite(cities, only=None, names=None):
    comp = Compositor(cities)
    for aspect in ASPECTS:
        if only and aspect not in only: continue
        for clip in build_frames(cities, aspect):
            if names and clip["name"] not in names: continue
            dirs = {v: os.path.join(WORK, aspect, v, clip["name"]) for v in ("clean", "overlay")}
            for dd in dirs.values():
                if os.path.isdir(dd): shutil.rmtree(dd)
                os.makedirs(dd)
            for fi in range(len(clip["frames"])):
                cl, ov = comp.frame(aspect, clip, fi)
                cl.save(os.path.join(dirs["clean"], f"{fi:04d}.jpg"), quality=93)
                ov.save(os.path.join(dirs["overlay"], f"{fi:04d}.jpg"), quality=93)
            print("composited", aspect, clip["name"], len(clip["frames"]), flush=True)

STILL_SHEET = [("9x16", "b1_earth_to_dubai", 5.9), ("9x16", "b2_london", 3.9), ("9x16", "b4_monaco", 1.9),
               ("9x16", "b5_pullback_all", 4.9), ("9x16", "b6_dubai_spike", 3.0), ("16x9", "b6_dubai_spike", 3.0)]
def stage_stills(cities, only=None):
    """Review sheet: renders only the needed Pro frames, composites them, tiles a contact sheet."""
    import arcpy
    from PIL import Image
    p = arcpy.mp.ArcGISProject(APRX); comp = Compositor(cities); outs = []
    d = os.path.join(OUT, "review"); os.makedirs(d, exist_ok=True)
    for aspect, name, t in STILL_SHEET:
        clip = next(c for c in build_frames(cities, aspect) if c["name"] == name)
        fi = min(len(clip["frames"]) - 1, int(t * FPS)); fi -= fi % 2
        fn = raw_path(aspect, clip["frames"][fi])
        if not os.path.exists(fn):
            os.makedirs(os.path.dirname(fn), exist_ok=True)
            lay = p.listLayouts(f"Globe {aspect}")[0]; mf = lay.listElements("MAPFRAME_ELEMENT")[0]
            set_camera(mf, camera(clip["frames"][fi]["key"])); lay.exportToPNG(fn, resolution=72)
        _, ov = comp.frame(aspect, clip, fi)
        out = os.path.join(d, f"still_{aspect}_{name}.png"); ov.save(out); outs.append(ov)
    th = 960; tiles = [im.resize((int(im.width * th / im.height), th)) for im in outs]
    sheet = Image.new("RGB", (sum(t.width for t in tiles) + 20 * (len(tiles) + 1), th + 40), (251, 248, 239)); x = 20
    for tl in tiles: sheet.paste(tl, (x, 20)); x += tl.width + 20
    sheet.save(os.path.join(d, "globe_still_sheet.png")); print("sheet", os.path.join(d, "globe_still_sheet.png"))

# ----------------------------------------------------------------- stage: encode (ffmpeg) + cue sheet
def ff(*a): subprocess.run([FFMPEG, "-y", "-loglevel", "error", *a], check=True)
def tc(sec): f = int(round(sec * FPS)); return f"00:{f // (60*FPS):02d}:{(f // FPS) % 60:02d}:{f % FPS:02d}"
def stage_encode(cities):
    os.makedirs(os.path.join(OUT, "clips"), exist_ok=True)
    cue = {"status": "INTERNAL - not for publication. Verified figures from data/globe/cities.csv", "fps": FPS,
           "note": "clean = columns only, no titles/labels (for the edit); overlay = Naj-style chips/flags/cards. Timecodes HH:MM:SS:FF @25fps. x* clips are optional and not in the default film.",
           "films": {}}
    for aspect in ASPECTS:
        clips = build_frames(cities, aspect)
        for ver in ("clean", "overlay"):
            t = 0.0; rows = []
            lst = os.path.join(WORK, aspect, f"concat_{ver}.txt")
            with open(lst, "w") as L:
                for clip in clips:
                    src = os.path.join(WORK, aspect, ver, clip["name"], "%04d.jpg")
                    mp4 = os.path.join(OUT, "clips", f"globe_{aspect}_{ver}_{clip['name']}.mp4")
                    ff("-framerate", str(FPS), "-i", src, "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", mp4)
                    dur = len(clip["frames"]) / FPS; opt = clip["name"].startswith("x")
                    rows.append(dict(clip=os.path.basename(mp4), beat=clip["name"], in_default_film=not opt, duration_s=round(dur, 2),
                                     film_in=None if opt else tc(t), film_out=None if opt else tc(t + dur),
                                     film_in_s=None if opt else round(t, 2), film_out_s=None if opt else round(t + dur, 2)))
                    if not opt:
                        L.write(f"file '{mp4}'\n"); t += dur
            film = os.path.join(OUT, f"globe_transactions_{aspect}" + ("" if ver == "clean" else "_overlay") + ".mp4")
            ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", film)
            sw, sh = (540, 960) if aspect == "9x16" else (960, 540)
            ff("-i", film, "-vf", f"scale={sw}:{sh}:flags=lanczos", "-c:v", "libx264", "-crf", "22", "-pix_fmt", "yuv420p", "-an", film.replace(".mp4", "_share.mp4"))
            for lab, sec in [("start", 0.5), ("mid", t / 2), ("end", t - 0.2)]:
                ff("-ss", f"{sec:.2f}", "-i", film, "-frames:v", "1", "-update", "1", film.replace(".mp4", f"_{lab}.png"))
            cue["films"][os.path.basename(film)] = dict(aspect=aspect, version=ver, duration_s=round(t, 2), beats=rows)
    with open(os.path.join(OUT, "globe_cue_sheet.json"), "w") as f: json.dump(cue, f, indent=2)
    for r in cue["films"]["globe_transactions_9x16.mp4"]["beats"]: print(r["beat"], r["film_in"], r["film_out"], r["duration_s"])

if __name__ == "__main__":
    stages = [a for a in sys.argv[1:] if not a.startswith("--")] or ["build", "render", "composite", "encode"]
    only = [a[2:] for a in sys.argv[1:] if a.startswith("--")] or None
    cities = load_cities()
    for st in stages: globals()["stage_" + st](cities, *([only] if st in ("render", "composite", "stills") else []))
