"""Etihad Rail passenger service x Dubai Metro - INTERNAL RESEARCH MAP (not for publication).

Patterns reused from scripts/globe_transactions.py (arcpy headless from Blank.aprx, World Imagery by URL,
layout map-frame export, Pillow overlay at 25 fps, ffmpeg encode, Najma palette) and scripts/ue_storefronts.py
(Overpass with User-Agent + mirror fallback).

Run with Pro's python (arcpy only needed for the 'basemap' stage):
  "%LOCALAPPDATA%\\Programs\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts\\etihad_rail_map.py [stage ...]
Stages (default all): fetch basemap still video
  --test   renders only a quick half-size test still (after fetch + basemap)

2D approach: arcpy exports a ladder of Web-Mercator basemap plates (UAE-wide -> interchange); Pillow crops/zooms
between plates (log-zoom) and draws all vectors/labels per frame so line weights stay constant on screen.
"""
import heapq, json, math, os, shutil, subprocess, sys, time, urllib.parse, urllib.request

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = r"C:\Dev\naj-market-pulse"
OUT = os.path.join(ROOT, "data", "media", "etihad_rail")
WORK = os.path.join(OUT, "_work")
APRX = os.path.join(WORK, "etihad_rail.aprx")
AMEN = os.path.join(ROOT, "data", "board", "amenities.json")
BLANK = os.path.join(os.environ["LOCALAPPDATA"], r"Programs\ArcGIS\Pro\Resources\ArcToolBox\Services\routingservices\data\Blank.aprx")
FFMPEG = os.path.join(os.environ["LOCALAPPDATA"], r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe")
IMAGERY = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer"
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
W, H, FPS, DUR = 1080, 1920, 25, 10.0
OVS = 2                                   # plate oversampling
IVORY, GOLD, GOLD_L, GREEN, INK, MUTED = (251, 248, 239), (201, 152, 58), (232, 201, 138), (20, 80, 60), (31, 42, 48), (92, 104, 110)
RED_L, GREEN_L, METRO_GOLD = (226, 48, 54), (76, 175, 80), (212, 175, 55)
FONT_H = r"C:\Windows\Fonts\georgiab.ttf"; FONT_B = r"C:\Windows\Fonts\segoeui.ttf"; FONT_BB = r"C:\Windows\Fonts\segoeuib.ttf"
UAE_BB = "22.5,51.4,26.4,56.6"
JGE = (55.163351, 25.017796)             # RTA (data/board/amenities.json) + brief

# ---------------------------------------------------------------- stations: OSM name patterns; never guessed
ETIHAD = [  # key, label, status, OSM name regexes (lower-case substrings), sub-label
    ("abu_dhabi", "Abu Dhabi", "open", ["mohammed bin zayed", "mbz", "abu dhabi"], "Mohammed bin Zayed City"),
    ("al_yalayis", "Dubai · Al Yalayis", "open", ["yalayis", "jumeirah golf", "dubai"], "Jumeirah Golf Estates"),
    ("al_dhaid", "Sharjah · Al Dhaid", "open", ["dhaid", "sharjah"], "opened 30 Sep 2026"),
    ("fujairah", "Fujairah", "open", ["fujairah", "sakamkam"], ""),
    ("meydan", "Meydan", "planned", ["meydan"], "planned"),
    ("al_jaddaf", "Al Jaddaf", "planned", ["jaddaf"], "planned"),
    ("dwc", "Al Maktoum Int'l Airport", "planned", ["maktoum"], "planned"),
]

def mx(lon): return lon * 20037508.34 / 180.0
def my(lat): return math.log(math.tan((90 + lat) * math.pi / 360.0)) * 6378137.0
def hav(a, b):
    la1, la2 = math.radians(a[1]), math.radians(b[1]); dl = math.radians(b[0] - a[0])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2
    return 12742e3 * math.asin(math.sqrt(h))

# ---------------------------------------------------------------- stage: fetch (Overpass)
def overpass(q, name):
    p = os.path.join(WORK, f"osm_{name}.json")
    if os.path.exists(p): return json.load(open(p, encoding="utf-8"))
    body = urllib.parse.urlencode({"data": q}).encode()
    for i, m in enumerate(MIRRORS):
        try:
            with urllib.request.urlopen(urllib.request.Request(m, data=body, headers={"User-Agent": "DigitAlchemy-Najma/1.0"}), timeout=240) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            d["fetched"] = time.strftime("%Y-%m-%dT%H:%M:%S"); d["mirror"] = m
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False); return d
        except Exception as e:
            print(f"  overpass {m.split('/')[2]}: {str(e)[:70]} - next mirror"); time.sleep(6 + 4 * i)
    raise SystemExit("all overpass mirrors failed for " + name)

def stage_fetch():
    os.makedirs(WORK, exist_ok=True)
    overpass(f'[out:json][timeout:230];way["railway"~"^(rail|construction)$"]["operator"~"Etihad",i]({UAE_BB});out body geom;', "etihad_rail")
    # operator tagging on OSM UAE track is sparse; every railway=rail in the UAE outside metro is the Etihad network
    overpass(f'[out:json][timeout:230];way["railway"="rail"]({UAE_BB});out body geom;', "uae_rail")
    overpass(f'[out:json][timeout:230];(node["railway"~"^(station|halt)$"]({UAE_BB});node["public_transport"="station"]["train"="yes"]({UAE_BB}););out body;', "stations")
    overpass('[out:json][timeout:230];relation["route"="subway"](24.8,54.9,25.4,55.6);out geom;', "metro")

def load_json(n): return json.load(open(os.path.join(WORK, f"osm_{n}.json"), encoding="utf-8"))

def resolve():
    """Returns dict with lines, stations, flags, sources - all from files, nothing invented."""
    rail = load_json("etihad_rail"); ur = load_json("uae_rail")
    ids = {e["id"] for e in rail["elements"]}
    rail["elements"] += [e for e in ur["elements"] if e["id"] not in ids and (e.get("tags", {}).get("usage") or "").lower() != "industrial" and "metro" not in str(e.get("tags")).lower()]
    st = load_json("stations"); metro = load_json("metro")
    ways = [dict(id=e["id"], nodes=e.get("nodes", []), geom=[(g["lon"], g["lat"]) for g in e.get("geometry", [])],
                 usage=e["tags"].get("usage", ""), service=e["tags"].get("service", ""), state=e["tags"].get("railway"))
            for e in rail["elements"] if e["type"] == "way" and e.get("geometry")]
    # candidate Etihad stations (non-metro/tram)
    cands = []
    for e in st["elements"]:
        t = e.get("tags", {}); nm = " | ".join(v for k, v in t.items() if k.startswith("name")).lower()
        if t.get("station") in ("subway", "light_rail", "monorail") or t.get("subway") == "yes" or t.get("tram") == "yes" or t.get("monorail") == "yes": continue
        if "metro" in nm or "palm" in nm and "monorail" in nm: continue
        cands.append(dict(id=e["id"], lon=e["lon"], lat=e["lat"], name=t.get("name:en") or t.get("name", ""), all=nm,
                          operator=t.get("operator", ""), tags=t))
    rail_pts = [p for w in ways for p in w["geom"][::4]]
    stations, flags, sources = [], [], []
    for key, label, status, pats, sub in ETIHAD:
        hit = None
        for pat in pats:
            ms = [c for c in cands if pat in c["all"] and ("etihad" in c["operator"].lower() or "etihad" in c["all"] or "passenger station" in c["all"])]
            if ms:
                # prefer Etihad-operated, and closest to the Etihad alignment
                ms.sort(key=lambda c: (("etihad" not in c["operator"].lower()), min((hav((c["lon"], c["lat"]), p) for p in rail_pts), default=9e9)))
                hit = ms[0]; break
        if hit is None:
            flags.append(dict(station=label, status=status, issue="no OSM railway=station node found; NOT drawn (position unconfirmed)"))
            continue
        d_rail = min((hav((hit["lon"], hit["lat"]), p) for p in rail_pts), default=None)
        stations.append(dict(key=key, label=label, sub=sub, status=status, lon=hit["lon"], lat=hit["lat"]))
        src = dict(item=f"Etihad Rail station: {label}", lon=round(hit["lon"], 6), lat=round(hit["lat"], 6),
                   source=f"OpenStreetMap node {hit['id']} (name '{hit['name']}', operator '{hit['operator']}') via Overpass {st.get('fetched')}",
                   dist_to_osm_alignment_m=round(d_rail) if d_rail is not None else None)
        sources.append(src)
        if status == "planned": src["note"] = "planned per Gulf News; OSM position may be indicative"
        if d_rail is not None and d_rail > 3000 and status == "open":
            flags.append(dict(station=label, issue=f"OSM node is {d_rail/1000:.1f} km from mapped Etihad track - check"))
    # metro lines
    mlines = []
    for e in metro["elements"]:
        t = e.get("tags", {}); nm = (t.get("name:en", "") + " " + t.get("name", "") + " " + t.get("ref", "") + " " + t.get("colour", "")).lower()
        col = "red" if "red" in nm else "green" if "green" in nm else None
        if not col: continue
        segs = [[(g["lon"], g["lat"]) for g in m["geometry"]] for m in e.get("members", []) if m["type"] == "way" and m.get("geometry") and m.get("role", "") in ("", "forward", "backward")]
        mlines.append(dict(colour=col, segs=segs, rel=e["id"], name=t.get("name:en") or t.get("name")))
        sources.append(dict(item=f"Dubai Metro {col} line geometry", source=f"OpenStreetMap relation {e['id']} '{t.get('name')}' via Overpass {metro.get('fetched')}"))
    if not mlines: flags.append(dict(item="Dubai Metro lines", issue="no route=subway relations returned; lines NOT drawn"))
    # RTA metro stations
    am = json.load(open(AMEN, encoding="utf-8"))
    def walk(o):
        if isinstance(o, dict):
            if o.get("k") == "metro": yield o
            for v in o.values(): yield from walk(v)
        elif isinstance(o, list):
            for v in o: yield from walk(v)
    rta = [dict(name=m["n"].replace(" Metro Station", ""), lon=m["lon"], lat=m["lat"], line=m.get("x", "")) for m in walk(am) if "Metro" in m.get("ad", "")]
    sources.append(dict(item=f"{len(rta)} Dubai Metro stations (Red/Green)", source="RTA open data via data/board/amenities.json (k='metro')"))
    sources.append(dict(item="Jumeirah Golf Estates metro station (Red Line)", lon=JGE[0], lat=JGE[1], source="RTA via data/board/amenities.json; matches brief"))
    ys = next((s for s in stations if s["key"] == "al_yalayis"), None)
    if ys:
        dd = hav((ys["lon"], ys["lat"]), JGE)
        sources.append(dict(item="Al Yalayis <-> JGE metro separation", metres=round(dd), reference="The National: ~400 m elevated walkway"))
        if dd > 1500: flags.append(dict(station="Dubai · Al Yalayis", issue=f"OSM node is {dd:.0f} m from JGE metro vs ~400 m reported - check"))
    return dict(ways=ways, stations=stations, flags=flags, sources=sources, metro=mlines, rta=rta)

# ---------------------------------------------------------------- passenger path on the rail graph
def passenger_path(ways, stations):
    """Shortest track path Abu Dhabi -> Al Yalayis -> Al Dhaid -> Fujairah (Dijkstra on OSM node graph)."""
    coord, adj = {}, {}
    for w in ways:
        if w["state"] != "rail" or w["service"] in ("yard", "siding", "spur") or len(w["nodes"]) != len(w["geom"]): continue
        for n, p in zip(w["nodes"], w["geom"]): coord[n] = p
        for a, b in zip(w["nodes"], w["nodes"][1:]):
            d = hav(coord[a], coord[b]); adj.setdefault(a, []).append((b, d)); adj.setdefault(b, []).append((a, d))
    def nearest(s): return min(coord, key=lambda n: (coord[n][0] - s["lon"]) ** 2 + (coord[n][1] - s["lat"]) ** 2)
    order = [s for k in ("abu_dhabi", "al_yalayis", "al_dhaid", "fujairah") for s in stations if s["key"] == k]
    path = []
    for a, b in zip(order, order[1:]):
        src, dst = nearest(a), nearest(b); dist = {src: 0}; prev = {}; pq = [(0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst: break
            if d > dist.get(u, 9e18): continue
            for v, w in adj.get(u, []):
                if d + w < dist.get(v, 9e18): dist[v] = d + w; prev[v] = u; heapq.heappush(pq, (d + w, v))
        if dst not in dist: return None, f"no connected track between {a['label']} and {b['label']}"
        seg = [dst]
        while seg[-1] != src: seg.append(prev[seg[-1]])
        path += [(a["lon"], a["lat"])] + [coord[n] for n in reversed(seg)] + [(b["lon"], b["lat"])]  # tie ends to the station nodes
    km = sum(hav(p, q) for p, q in zip(path, path[1:])) / 1000
    return path, km

# ---------------------------------------------------------------- camera ladder (Web Mercator)
CEN_UAE = (54.55, 24.35)                 # UAE-wide view centre
FOCUS = ((55.1649 + JGE[0]) / 2, (25.0145 + JGE[1]) / 2)
W_UAE, W_END = 600e3, 5.2e3              # view width (m) at start / end of move
PLATES = [600e3, 200e3, 66e3, 22e3, 5.2e3]

def view_at(u):
    """u 0..1 along the move -> (cx, cy, width) in mercator metres; log zoom, centre follows zoom progress."""
    lw = math.log(W_UAE) + (math.log(W_END) - math.log(W_UAE)) * u
    w = math.exp(lw); k = (W_UAE - w) / (W_UAE - W_END)  # centre converges with linear scale -> focus stays put
    k = k ** 0.6
    fx, fy = mx(FOCUS[0]), my(FOCUS[1]); ux, uy = mx(CEN_UAE[0]), my(CEN_UAE[1])
    return ux + (fx - ux) * k, uy + (fy - uy) * k, w

def plate_views():
    out = []
    for pw in PLATES:
        u = (math.log(pw) - math.log(W_UAE)) / (math.log(W_END) - math.log(W_UAE))
        cx, cy, _ = view_at(max(0.0, min(1.0, u)))
        # make the plate large enough to hold every later (smaller) view it serves
        xs, ys = [], []
        for i in range(0, 101):
            uu = u + (1 - u) * i / 100; x, y, w = view_at(min(1, uu))
            if w < pw / 3.2: break
            xs += [x - w / 2, x + w / 2]; ys += [y - w * H / W / 2, y + w * H / W / 2]
        xs += [cx - pw / 2, cx + pw / 2]; ys += [cy - pw * H / W / 2, cy + pw * H / W / 2]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        # keep 9:16 plate aspect
        pwid = max(x1 - x0, (y1 - y0) * W / H) * 1.02; pcx, pcy = (x0 + x1) / 2, (y0 + y1) / 2
        out.append(dict(w=pwid, cx=pcx, cy=pcy, file=os.path.join(WORK, f"plate_{int(pw/1000)}km.png")))
    return out

# ---------------------------------------------------------------- stage: basemap (arcpy)
def stage_basemap():
    import arcpy
    arcpy.env.overwriteOutput = True
    os.makedirs(WORK, exist_ok=True)
    if os.path.exists(APRX): os.remove(APRX)
    shutil.copy(BLANK, APRX)
    p = arcpy.mp.ArcGISProject(APRX)
    for m in p.listMaps(): p.deleteItem(m)
    m = p.createMap("Etihad Rail", "MAP")
    m.spatialReference = arcpy.SpatialReference(3857)
    m.addDataFromPath(IMAGERY)
    lay = p.createLayout(W * OVS, H * OVS, "POINT", "Plate 9x16")
    mf = lay.createMapFrame(arcpy.Extent(0, 0, W * OVS, H * OVS), m, "Plate frame")
    p.save()
    for pl in plate_views():
        if os.path.exists(pl["file"]): continue
        hw, hh = pl["w"] / 2, pl["w"] * H / W / 2
        mf.camera.setExtent(arcpy.Extent(pl["cx"] - hw, pl["cy"] - hh, pl["cx"] + hw, pl["cy"] + hh, spatial_reference=arcpy.SpatialReference(3857)))
        t = time.time(); lay.exportToPNG(pl["file"], resolution=72)
        print("plate", os.path.basename(pl["file"]), f"{time.time()-t:.1f}s", flush=True)
    # the exporter can snap the extent; record what came out
    json.dump(plate_views(), open(os.path.join(WORK, "plates.json"), "w"), indent=1)

# ---------------------------------------------------------------- Pillow frame renderer
class Renderer:
    def __init__(self, data, scale=1.0):
        from PIL import Image, ImageFont
        self.Image = Image; self.s = scale; self.d = data
        self.plates = plate_views()
        self.img = [Image.open(p["file"]).convert("RGB") for p in self.plates]
        self.f = {k: (lambda path: (lambda px: ImageFont.truetype(path, max(8, int(px * scale)))))(v) for k, v in (("h", FONT_H), ("b", FONT_B), ("bb", FONT_BB))}
        self.W, self.H = int(W * scale), int(H * scale)
        # pre-project vectors to mercator
        P = lambda pts: [(mx(a), my(b)) for a, b in pts]
        self.wider = [P(w["geom"]) for w in data["ways"]]
        self.pax = P(data["path"]) if data.get("path") else None
        self.metro = [(m["colour"], [P(s) for s in m["segs"]]) for m in data["metro"]]
        self.gold_line = data.get("gold")
        self._cum = [0.0]; self.st_frac = {}
        if self.pax:
            for a, b in zip(self.pax, self.pax[1:]): self._cum.append(self._cum[-1] + math.dist(a, b))
            for x in data["stations"]:            # fraction along the passenger line where each station sits
                p = (mx(x["lon"]), my(x["lat"])); i = min(range(len(self.pax)), key=lambda i: (self.pax[i][0] - p[0]) ** 2 + (self.pax[i][1] - p[1]) ** 2)
                self.st_frac[x["key"]] = self._cum[i] / self._cum[-1]

    def base(self, cx, cy, w):
        # finest plate that fully contains the view
        hw, hh = w / 2, w * H / W / 2
        idx = 0
        for i, p in enumerate(self.plates):
            phw, phh = p["w"] / 2, p["w"] * H / W / 2
            if p["cx"] - phw <= cx - hw and cx + hw <= p["cx"] + phw and p["cy"] - phh <= cy - hh and cy + hh <= p["cy"] + phh: idx = i
        def crop(i):
            p, im = self.plates[i], self.img[i]
            sx = im.width / p["w"]; sy = im.height / (p["w"] * H / W)
            box = ((cx - hw - (p["cx"] - p["w"] / 2)) * sx, ((p["cy"] + p["w"] * H / W / 2) - (cy + hh)) * sy,
                   (cx + hw - (p["cx"] - p["w"] / 2)) * sx, ((p["cy"] + p["w"] * H / W / 2) - (cy - hh)) * sy)
            return im.resize((self.W, self.H), self.Image.BICUBIC, box=box)
        fr = crop(idx)
        f = w / self.plates[idx]["w"]                 # ~1 = just switched to this finer plate
        if idx > 0 and f > 0.55:                      # crossfade from the coarser plate: no hard jumps
            fr = self.Image.blend(fr, crop(idx - 1), min(1.0, (f - 0.55) / 0.45))
        return fr

    def grade(self, im):
        """light Najma film grade (warm lift) + soft vignette"""
        from PIL import Image, ImageEnhance
        im = ImageEnhance.Color(im).enhance(0.55); im = ImageEnhance.Brightness(im).enhance(0.64)
        im = Image.blend(im, Image.new("RGB", im.size, (70, 56, 30)), 0.10)
        if not hasattr(self, "_vig"):
            m = Image.new("L", (108, 192), 0); md = m.load()
            for y in range(192):
                for x in range(108):
                    r = math.hypot((x - 54) / 54, (y - 96) / 96); md[x, y] = int(255 * min(1, max(0, (r - 0.55) / 0.75)) ** 1.6 * 0.75)
            self._vig = m.resize(im.size, Image.BICUBIC)
        return Image.composite(Image.new("RGB", im.size, (12, 16, 18)), im, self._vig)

    def frame(self, u, A=None):
        """A = animation state; defaults give the settled still."""
        from PIL import Image, ImageDraw, ImageFilter
        A = dict(dict(reveal=1.0, lab_w=1.0, lab_c=1.0, walk=1.0, pulse=None, title=1.0, pop=None), **(A or {}))
        cx, cy, w = view_at(u)
        im = self.grade(self.base(cx, cy, w))
        s = self.s; S = self.W / w
        def px(p): return ((p[0] - (cx - w / 2)) * S, ((cy + w * H / W / 2) - p[1]) * S)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        zoom = math.log(W_UAE / w) / math.log(W_UAE / W_END)      # 0 wide .. 1 close
        def line(pts, col, wd, a=255, dash=None):
            q = [px(p) for p in pts]
            if dash:
                acc = 0.0
                for a0, b0 in zip(q, q[1:]):
                    L = math.dist(a0, b0); n = max(1, int(L / 2))
                    for i in range(n):
                        t0 = i / n; t1 = (i + 1) / n; m = acc + L * t0
                        if (m // dash) % 2 == 0:
                            d.line([(a0[0] + (b0[0] - a0[0]) * t0, a0[1] + (b0[1] - a0[1]) * t0), (a0[0] + (b0[0] - a0[0]) * t1, a0[1] + (b0[1] - a0[1]) * t1)], fill=col + (a,), width=int(wd))
                    acc += L
            else:
                d.line(q, fill=col + (a,), width=max(1, int(wd)), joint="curve")
        # wider network (faint)
        for g in self.wider: line(g, IVORY, 3 * s, 110)
        # metro (grows in with zoom)
        ma = int(255 * min(1, max(0, (zoom - 0.35) / 0.25)))
        if ma:
            for col, segs in self.metro:
                for sg in segs: line(sg, IVORY, 11 * s, int(ma * 0.9)); line(sg, RED_L if col == "red" else GREEN_L, 7 * s, ma)
            if self.gold_line: line([(mx(a), my(b)) for a, b in self.gold_line], METRO_GOLD, 5 * s, int(ma * 0.9), dash=18 * s)
        # passenger line
        head = None
        if self.pax:
            n = len(self.pax); cum = self._cum
            k = A["reveal"] * cum[-1]; j = max(1, min(n, next((i for i, c in enumerate(cum) if c >= k), n)))
            part = self.pax[:j]
            if A["reveal"] < 1 and j < n:
                a0, b0 = self.pax[j - 1], self.pax[j]; t = (k - cum[j - 1]) / ((cum[j] - cum[j - 1]) or 1)
                part = part + [(a0[0] + (b0[0] - a0[0]) * t, a0[1] + (b0[1] - a0[1]) * t)]; head = part[-1]
            if len(part) > 1:
                line(part, INK, 14 * s, 220); line(part, GOLD, 10 * s, 255)
        # walkway
        st = {x["key"]: x for x in self.d["stations"]}
        if "al_yalayis" in st and ma and A["walk"] > 0:
            a = px((mx(st["al_yalayis"]["lon"]), my(st["al_yalayis"]["lat"]))); b = px((mx(JGE[0]), my(JGE[1])))
            e = (a[0] + (b[0] - a[0]) * A["walk"], a[1] + (b[1] - a[1]) * A["walk"])
            d.line([a, e], fill=IVORY + (ma,), width=int(7 * s))
        img = Image.alpha_composite(im.convert("RGBA"), ov); d = ImageDraw.Draw(img)
        if head:                                       # glowing travelling head
            X, Y = px(head); g = Image.new("RGBA", img.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
            gd.ellipse([X - 34 * s, Y - 34 * s, X + 34 * s, Y + 34 * s], fill=GOLD_L + (220,))
            img.alpha_composite(g.filter(ImageFilter.GaussianBlur(14 * s)))
            d = ImageDraw.Draw(img); d.ellipse([X - 9 * s, Y - 9 * s, X + 9 * s, Y + 9 * s], fill=IVORY + (255,))
        placed = []
        def tag(x, y, text, sub="", dx=18, dy=-20, big=False, a=255, anchor_left=True, col=GOLD):
            if a <= 0: return
            fh = self.f["bb"](30 if big else 25); fs = self.f["b"](20)
            tw = max(fh.getlength(text), fs.getlength(sub) if sub else 0); th = (38 if big else 32) * s + ((26 * s) if sub else 0)
            bx = x + dx * s if anchor_left else x - dx * s - tw - 24 * s; by = y + dy * s - th / 2
            bx = max(12 * s, min(self.W - tw - 36 * s, bx)); by = max(12 * s, min(self.H - th - 12 * s, by))
            lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
            ld.line([(x, y), (bx + (0 if anchor_left else tw + 24 * s), by + th / 2)], fill=IVORY + (int(a * 0.8),), width=max(1, int(2 * s)))
            ld.rounded_rectangle([bx, by, bx + tw + 24 * s, by + th], radius=int(10 * s), fill=IVORY + (int(a * 0.94),), outline=col + (a,), width=max(1, int(2 * s)))
            ld.text((bx + 12 * s, by + 4 * s), text, font=fh, fill=INK + (a,))
            if sub: ld.text((bx + 12 * s, by + (36 if big else 31) * s), sub, font=fs, fill=MUTED + (a,))
            img.alpha_composite(lay)
        def dot(x, y, r, fill, outline, hollow=False, a=255):
            lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
            ld.ellipse([x - r, y - r, x + r, y + r], fill=(IVORY + (a,)) if hollow else fill + (a,), outline=outline + (a,), width=max(2, int(r * 0.35)))
            if hollow: ld.ellipse([x - r * 0.45, y - r * 0.45, x + r * 0.45, y + r * 0.45], fill=(0, 0, 0, 0))
            img.alpha_composite(lay)
        # metro stations (close zoom)
        if ma:
            for r in self.d["rta"]:
                x, y = px((mx(r["lon"]), my(r["lat"])))
                if -20 < x < self.W + 20 and -20 < y < self.H + 20:
                    dot(x, y, 7 * s, IVORY, RED_L if "Red" in r["line"] else GREEN_L, a=ma)
        # Etihad stations
        wide_a = int(255 * max(0, 1 - zoom / 0.45) * A["lab_w"]); close_a = int(255 * min(1, max(0, (zoom - 0.55) / 0.2)) * A["lab_c"])
        def ring(X, Y, ph, r0, col):
            rr = r0 + 46 * s * ph; lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(lay).ellipse([X - rr, Y - rr, X + rr, Y + rr], outline=col + (int(230 * (1 - ph)),), width=max(2, int(4 * s)))
            img.alpha_composite(lay)
        for k, x in st.items():
            X, Y = px((mx(x["lon"]), my(x["lat"])))
            hollow = x["status"] == "planned"
            if hollow and zoom < 0.4: continue
            sc = 1.0
            if A["pop"] is not None:                   # station pops as the line reaches it
                pk = A["pop"].get(k, 9)
                if pk <= 0: continue
                if pk < 1: sc = 1 + 0.6 * math.sin(math.pi * pk)
                if pk < 1.6: ring(X, Y, pk / 1.6, 12 * s, GOLD_L)
            dot(X, Y, (13 if not hollow else 11) * s * sc, GOLD, INK if not hollow else GOLD, hollow=hollow, a=255 if not hollow else ma)
            if A["pulse"] is not None and k == "al_yalayis": ring(X, Y, A["pulse"] % 1.0, 14 * s, GOLD)
        if A["pulse"] is not None:
            X, Y = px((mx(JGE[0]), my(JGE[1]))); ring(X, Y, (A["pulse"] + 0.5) % 1.0, 10 * s, RED_L)
        # labels: wide view
        side = {"abu_dhabi": False, "al_yalayis": False, "al_dhaid": True, "fujairah": True}
        for k in ("abu_dhabi", "al_yalayis", "al_dhaid", "fujairah"):
            if k in st:
                X, Y = px((mx(st[k]["lon"]), my(st[k]["lat"])))
                lab = {"al_yalayis": "Dubai", "al_dhaid": "Sharjah"}.get(k, st[k]["label"])
                sub = {"abu_dhabi": "Mohammed bin Zayed City", "al_yalayis": "Al Yalayis", "al_dhaid": "Al Dhaid", "fujairah": ""}[k]
                tag(X, Y, lab, sub, dy={"al_yalayis": -40, "al_dhaid": -40}.get(k, 0), anchor_left=side[k], a=wide_a)
        if wide_a and self.wider:
            # "the wider network" tag at a far-west faint point
            far = min((p for g in self.wider for p in g), key=lambda p: p[0])
            X, Y = px(far); tag(X, Y, "the wider network", "~900 km · 11 cities · 7 emirates", dx=10, dy=150, a=int(wide_a * 0.85), col=GOLD_L)
        # labels: close view
        if close_a:
            if "al_yalayis" in st:
                X, Y = px((mx(st["al_yalayis"]["lon"]), my(st["al_yalayis"]["lat"])))
                tag(X, Y, "Etihad Rail · Al Yalayis", "Dubai station · open", dy=110, anchor_left=False, big=True, a=close_a)
            X, Y = px((mx(JGE[0]), my(JGE[1])))
            tag(X, Y, "Jumeirah Golf Estates", "Metro · Red Line", dy=-120, big=True, a=close_a, col=RED_L)
            if "al_yalayis" in st:
                a0 = px((mx(st["al_yalayis"]["lon"]), my(st["al_yalayis"]["lat"])))
                mxp, myp = (a0[0] + X) / 2, (a0[1] + Y) / 2
                fb = self.f["bb"](22); t = "elevated walkway · ~400 m"
                lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
                ld.text((mxp + 40 * s, myp + 30 * s), t, font=fb, fill=IVORY + (close_a,), stroke_width=max(1, int(3 * s)), stroke_fill=INK + (close_a,))
                img.alpha_composite(lay)
        # onward arrow along Red Line (mid/close)
        mid_a = int(255 * min(1, max(0, (zoom - 0.45) / 0.2)) * A["lab_c"])
        if mid_a:
            fb = self.f["bb"](24); t = "Red Line → Dubai Marina · Business Bay · DXB"
            lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
            X, Y = px((mx(JGE[0]), my(JGE[1])))
            ang = math.atan2(-(my(25.08) - my(JGE[1])), mx(55.145) - mx(JGE[0]))  # NE towards Marina (screen coords)
            tx, ty = X + 250 * s, Y - 360 * s
            tx = min(tx, self.W - fb.getlength(t) - 20 * s) if False else 30 * s
            ld.rounded_rectangle([tx - 12 * s, ty - 8 * s, tx + fb.getlength(t) + 12 * s, ty + 36 * s], radius=int(8 * s), fill=RED_L + (int(mid_a * 0.9),))
            ld.text((tx, ty), t, font=fb, fill=IVORY + (mid_a,))
            img.alpha_composite(lay)
        # planned station labels (mid zoom)
        pa = int(255 * min(1, max(0, (zoom - 0.4) / 0.15)) * max(0, 1 - (zoom - 0.75) / 0.12)) if zoom < 0.87 else 0
        for k in ("meydan", "al_jaddaf", "dwc"):
            if k in st and pa > 0:
                X, Y = px((mx(st[k]["lon"]), my(st[k]["lat"])))
                tag(X, Y, st[k]["label"], "planned (Gulf News)", a=pa, col=GOLD_L)
        # header + footer
        lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        img.alpha_composite(lay); lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([40 * s, 70 * s, self.W - 40 * s, 262 * s], radius=int(22 * s), fill=IVORY + (240,), outline=GOLD + (255,), width=max(2, int(3 * s)))
        ld.text((70 * s, 88 * s), "ETIHAD RAIL · PASSENGER", font=self.f["bb"](30), fill=GOLD)
        ld.text((70 * s, 128 * s), "Abu Dhabi to Fujairah, via Dubai", font=self.f["h"](46), fill=INK)
        ld.text((70 * s, 196 * s), "Dubai & Sharjah stations open 30 Sep 2026 · Metro link at JGE", font=self.f["b"](25), fill=MUTED)
        if A["title"] < 1:                             # title card slides down from above
            e = 1 - (1 - A["title"]) ** 3
            lay = lay.transform(lay.size, Image.AFFINE, (1, 0, 0, 0, 1, (1 - e) * 300 * s))
            lay.putalpha(lay.getchannel("A").point(lambda v: int(v * min(1, A["title"] * 1.5))))
        img.alpha_composite(lay); lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        # legend
        ly = self.H - 250 * s
        ld.rounded_rectangle([40 * s, ly, self.W - 40 * s, self.H - 70 * s], radius=int(18 * s), fill=IVORY + (235,), outline=GOLD_L + (255,), width=2)
        items = [("line", GOLD, "Passenger service (open)"), ("line", IVORY, "Wider network"), ("dot", GOLD, "Station open"), ("dot", RED_L, "Metro station"),
                 ("line", RED_L, "Metro Red Line"), ("line", GREEN_L, "Metro Green Line")]
        for i, (kind, col, t) in enumerate(items):
            x0 = 70 * s + (i % 2) * 480 * s; y0 = ly + 26 * s + (i // 2) * 48 * s
            if kind == "line": ld.line([x0, y0 + 16 * s, x0 + 50 * s, y0 + 16 * s], fill=(col if col != IVORY else (170, 170, 160)) + (255,), width=int(8 * s))
            else:
                ld.ellipse([x0 + 13 * s, y0 + 4 * s, x0 + 37 * s, y0 + 28 * s], fill=IVORY + (255,) if kind == "hollow" else col + (255,), outline=col + (255,) if kind == "hollow" else INK + (255,), width=max(2, int(4 * s)))
            ld.text((x0 + 66 * s, y0), t, font=self.f["b"](24), fill=INK)
        ld.text((40 * s, self.H - 60 * s), "Imagery: Esri World Imagery · Rail/Metro: © OpenStreetMap", font=self.f["b"](18), fill=IVORY)
        img.alpha_composite(lay)
        return img.convert("RGB")

    def inset(self, img):
        """UAE locator inset for the still (drawn from the widest plate)."""
        from PIL import Image, ImageDraw
        p, im = self.plates[0], self.img[0]
        iw = int(300 * self.s); ih = int(iw * 1.1)
        wv = p["w"] * 0.98; hv = wv * ih / iw; cx, cy = p["cx"], p["cy"]
        sx = im.width / p["w"]; sy = im.height / (p["w"] * H / W)
        box = ((cx - wv / 2 - (p["cx"] - p["w"] / 2)) * sx, ((p["cy"] + p["w"] * H / W / 2) - (cy + hv / 2)) * sy,
               (cx + wv / 2 - (p["cx"] - p["w"] / 2)) * sx, ((p["cy"] + p["w"] * H / W / 2) - (cy - hv / 2)) * sy)
        ins = im.resize((iw, ih), Image.BICUBIC, box=box).convert("RGBA")
        ins = Image.blend(ins, Image.new("RGBA", ins.size, (20, 30, 34, 255)), 0.35)
        d = ImageDraw.Draw(ins)
        def P(lon, lat): return ((mx(lon) - (cx - wv / 2)) * iw / wv, ((cy + hv / 2) - my(lat)) * ih / hv)
        for g in self.d["ways"]: d.line([P(*q) for q in g["geom"]], fill=IVORY + (130,), width=1)
        if self.d.get("path"): d.line([P(*q) for q in self.d["path"]], fill=GOLD + (255,), width=max(2, int(4 * self.s)))
        for x in self.d["stations"]:
            if x["status"] == "open":
                X, Y = P(x["lon"], x["lat"]); r = 5 * self.s; d.ellipse([X - r, Y - r, X + r, Y + r], fill=GOLD, outline=INK)
        X, Y = P(*FOCUS); d.rectangle([X - 14 * self.s, Y - 14 * self.s, X + 14 * self.s, Y + 14 * self.s], outline=IVORY, width=max(2, int(3 * self.s)))
        d.text((10 * self.s, 8 * self.s), "UAE", font=self.f["bb"](22), fill=IVORY)
        frame = Image.new("RGBA", (iw + 8, ih + 8), GOLD + (255,)); frame.paste(ins, (4, 4))
        x0, y0 = self.W - iw - int(52 * self.s), int(290 * self.s)
        img = img.convert("RGBA"); img.alpha_composite(frame, (x0, y0)); return img.convert("RGB")

def get_data():
    r = resolve()
    path, info = passenger_path(r["ways"], r["stations"])
    if path is None:
        r["flags"].append(dict(item="passenger path", issue=info + "; passenger line NOT highlighted")); r["path"] = None
    else:
        r["path"] = path; r["path_km"] = round(info, 1)
        r["sources"].append(dict(item="Passenger service line", source="shortest path on OSM Etihad track graph through the 4 open stations", length_km=round(info, 1)))
    r["gold"] = None   # Gold Line (2032): no confirmed alignment in OSM -> not drawn
    r["flags"].append(dict(item="Dubai Metro Gold Line interchange (2032, The National)", issue="alignment/station position not confirmed; optional dashed line NOT drawn"))
    return r

def write_sources(r):
    doc = dict(status="INTERNAL RESEARCH - not for publication (ArcGIS Student licence)", generated=time.strftime("%Y-%m-%d %H:%M"),
               stations=[dict(k=s["key"], label=s["label"], status=s["status"], lon=round(s["lon"], 6), lat=round(s["lat"], 6)) for s in r["stations"]],
               sources=r["sources"], flags=r["flags"],
               context=["Intro phase Abu Dhabi-Fujairah since 30 Jun 2026; Al Yalayis (Dubai) and Al Dhaid (Sharjah) opened 30 Sep 2026 (brief)",
                        "Planned Dubai stations Meydan, Al Jaddaf, Al Maktoum Int'l Airport: Gulf News",
                        "Al Yalayis-JGE elevated walkway ~400 m: The National", "Basemap: Esri World Imagery via ArcGIS Pro 3.7 arcpy"])
    json.dump(doc, open(os.path.join(OUT, "sources.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)

STILL_U = 1.0
def stage_still(test=False):
    r = get_data(); write_sources(r)
    R = Renderer(r, 0.5 if test else 1.0)
    img = R.inset(R.frame(STILL_U))
    fn = os.path.join(WORK, "test_still.png") if test else os.path.join(OUT, "map_9x16.png")
    img.save(fn); print("still", fn)
    for f in r["flags"]: print("FLAG", f)

def stage_video():
    r = get_data(); R = Renderer(r, 1.0)
    fr_dir = os.path.join(WORK, "frames"); shutil.rmtree(fr_dir, ignore_errors=True); os.makedirs(fr_dir)
    # 14 s: title slides 0-0.8 | line draws 0.6-4.4 (wide) | wide labels 3.6-4.7 | zoom 5.0-10.4 (no labels while moving)
    # | settle: walkway 10.4-11.2, pulses, close labels 11.1-11.8 | hold final frame >= 2 s
    n = int(14.0 * FPS); cl = lambda x: max(0.0, min(1.0, x))
    for i in range(n):
        T = i / FPS
        z = cl((T - 5.0) / 5.4); u = z * z * z * (z * (6 * z - 15) + 10)
        rev = 1 - (1 - cl((T - 0.6) / 3.8)) ** 2
        pop = {k: (rev - f) * 3.8 / 0.5 if rev < 1 else 9 for k, f in R.st_frac.items()}
        A = dict(reveal=rev, pop=pop, lab_w=cl((T - 3.6) / 0.8) * (1 - cl((T - 4.7) / 0.3)),
                 lab_c=cl((T - 11.1) / 0.7), walk=cl((T - 10.4) / 0.8), pulse=((T - 10.4) / 1.4) if T >= 10.4 else None, title=cl(T / 0.8))
        R.frame(u, A).save(os.path.join(fr_dir, f"{i:04d}.jpg"), quality=92)
        if i % 25 == 0: print("frame", i, flush=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fr_dir, "%04d.jpg"),
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", os.path.join(OUT, "map_9x16.mp4")], check=True)
    shutil.rmtree(fr_dir, ignore_errors=True); print("video", os.path.join(OUT, "map_9x16.mp4"))

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--test" in args: stage_fetch(); stage_basemap(); stage_still(test=True); sys.exit()
    for st in [a for a in args if not a.startswith("--")] or ["fetch", "basemap", "still", "video"]:
        globals()["stage_" + st]()
