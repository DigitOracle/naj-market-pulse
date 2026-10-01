"""A cycle route through a district's BLOCK massing - clean aerial "cutaway", 9:16 film.

Kendall, 1 Oct 2026: run the ride through LOD 100 blocks rather than the textured twin, "so that it's a bit
cleaner", with an aerial view where "you can clearly see the line going through all of the blocks". The textured
twin page fought every plain material (its bloom pass painted them black), so this draws its own scene with
MapLibre GL from files the LOD 3 session publishes:
  - blocks: data/lab/blocks_ride/blocks_<slug>_ride.json (footprints with h, from data/ce/<slug>/blocks.json, the
    under-200 m2 "community_median" needles capped to 4 m) - fill-extrusion, light, lit by the map's own light
  - ground: data/lab/context/<slug>/ground_roles_wgs84.geojson - water, canal, asphalt, pavement, promenade, grass
    by role (road markings dropped)
  - route: data/bike/rides/<ride>.json - drawn on as the camera travels, glowing gold
Camera: opens high and wide over the district, eases down to an oblique aerial (~300-450 m) that follows the route,
pausing at named landmarks (their blocks warm to gold and the name fades in). Frames are stepped and screenshotted.

    python scripts/blocks_ride.py --ride business_bay_canal --slug businessbay --place "Business Bay" \\
        --stops "Al Habtoor Tower|CHURCHILL TOWER=Churchill Tower|Binghatti Skyrise - TOWER C=Binghatti Skyrise"
Writes data/bike/blocks_ride_<ride>_9x16.mp4.
"""
import json
import math
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIKE = os.path.join(ROOT, "data", "bike")
W, H, FPS = 1080, 1920, 25
GROUND_COL = {"water": "#1F5E73", "canal": "#1F5E73", "pool": "#2C7A8C", "asphalt": "#2B3036", "parking": "#33383E",
              "pavement": "#9C978E", "promenade": "#B7B0A3", "kerb": "#7D7870", "podium": "#8E897F",
              "plot": "#5A5E55", "construction": "#6B6250", "sand": "#8C7E62", "grass": "#4F6B45", "pitch": "#4F6B45"}

PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<link href="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel=stylesheet>
<script src="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="data.js"></script>
<style>html,body,#m{margin:0;height:100%;background:#5E5747}
#t{position:fixed;left:48px;top:44px;color:#f2f4f7;font:700 46px system-ui;text-shadow:0 2px 12px #000}
#t span{display:block;font:400 26px system-ui;color:#C5A56A;margin-top:6px}
#lab{position:fixed;left:0;right:0;top:30%;text-align:center;color:#fff;font:700 60px system-ui;opacity:0;
     text-shadow:0 3px 18px #000,0 0 4px #000}
#src{position:fixed;left:48px;bottom:30px;right:48px;color:#9aa3ad;font:400 15px system-ui;line-height:1.4}
.maplibregl-ctrl-attrib{display:none}</style></head><body><div id=m></div>
<div id=t>__TITLE__<span>__SUB__</span></div><div id=lab></div><div id=src>__SRC__</div>
<script>
const D = window.__D;
const map = new maplibregl.Map({container: "m", style: {version: 8, sources: {}, layers: [
  {id: "bg", type: "background", paint: {"background-color": "#5E5747"}}]},
  center: D.center, zoom: 13, pitch: 0, maxPitch: 85, antialias: true, fadeDuration: 0, interactive: false});
map.on("load", () => {
  map.setLight({anchor: "map", position: [1.4, 210, 35], color: "#ffffff", intensity: 0.55});
  map.addSource("g", {type: "geojson", data: D.ground});
  map.addLayer({id: "g", type: "fill", source: "g", paint: {"fill-color": ["get", "c"], "fill-antialias": false}});
  map.addSource("b", {type: "geojson", data: D.blocks, promoteId: "i"});
  map.addLayer({id: "b", type: "fill-extrusion", source: "b", paint: {
    "fill-extrusion-color": ["case", ["boolean", ["feature-state", "hl"], false], "#E8C77E", "#E7E2D8"],
    "fill-extrusion-height": ["get", "h"], "fill-extrusion-base": 0, "fill-extrusion-opacity": 0.96,
    "fill-extrusion-vertical-gradient": true}});
  map.addSource("r", {type: "geojson", data: {type: "Feature", geometry: {type: "LineString", coordinates: D.route.slice(0, 2)}}});
  map.addLayer({id: "rglow", type: "line", source: "r", layout: {"line-cap": "round", "line-join": "round"},
    paint: {"line-color": "#F2B84B", "line-width": 34, "line-blur": 18, "line-opacity": 0.6}});
  map.addLayer({id: "r", type: "line", source: "r", layout: {"line-cap": "round", "line-join": "round"},
    paint: {"line-color": "#FFD27A", "line-width": 11}});
  map.addSource("dot", {type: "geojson", data: {type: "Point", coordinates: D.route[0]}});
  map.addLayer({id: "dot", type: "circle", source: "dot", paint: {"circle-radius": 11, "circle-color": "#FFF4D6",
    "circle-stroke-color": "#F2B84B", "circle-stroke-width": 4}});
  window.__ready = true;
});
let lit = [];
window.__frame = (fr) => {
  const pts = D.route, k = Math.max(2, Math.min(pts.length, fr.n));
  map.getSource("r").setData({type: "Feature", geometry: {type: "LineString", coordinates: pts.slice(0, k)}});
  map.getSource("dot").setData({type: "Point", coordinates: fr.dot});
  for (const i of lit) map.setFeatureState({source: "b", id: i}, {hl: false});
  lit = fr.hl || []; for (const i of lit) map.setFeatureState({source: "b", id: i}, {hl: true});
  const lab = document.getElementById("lab"); lab.textContent = fr.label || ""; lab.style.opacity = fr.lw || 0;
  map.jumpTo({center: fr.center, zoom: fr.zoom, pitch: fr.pitch, bearing: fr.bearing});
  return new Promise(r => map.once("idle", () => requestAnimationFrame(() => r(true))));
};
</script></body></html>"""


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def metres(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return 6371008.8 * math.hypot(math.radians(b[0] - a[0]) * math.cos(lat), math.radians(b[1] - a[1]))


def bearing(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.degrees(math.atan2(math.radians(b[0] - a[0]) * math.cos(lat), math.radians(b[1] - a[1])))


def ease(u):
    return u * u * (3 - 2 * u)


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_angle(a, b, t):
    d = (b - a + 540) % 360 - 180
    return a + d * t


def main():
    ride, slug = arg("--ride", "business_bay_canal"), arg("--slug", "businessbay")
    place, seconds = arg("--place", "Business Bay"), float(arg("--seconds", "40"))
    route = json.load(open(os.path.join(BIKE, "rides", ride + ".json"), encoding="utf-8"))
    pts = route["coords"]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + metres(pts[i - 1], pts[i]))
    L = cum[-1]

    def at(s):
        s = max(0.0, min(L, s))
        lo, hi = 0, len(cum) - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            lo, hi = (m, hi) if cum[m] <= s else (lo, m)
        t = (s - cum[lo]) / max(1e-9, cum[hi] - cum[lo])
        return [lerp(pts[lo][0], pts[hi][0], t), lerp(pts[lo][1], pts[hi][1], t)], hi

    blocks = json.load(open(os.path.join(ROOT, "data", "lab", "blocks_ride", "blocks_%s_ride.json" % slug), encoding="utf-8"))
    bfeat = [f for f in blocks["features"] if f["properties"].get("k") == "b"]
    for f in bfeat:
        f["properties"]["h"] = float(f["properties"].get("h") or 4)
    ground = json.load(open(os.path.join(ROOT, "data", "lab", "context", slug, "ground_roles_wgs84.geojson"), encoding="utf-8"))
    gfeat = []
    for f in ground["features"]:
        c = GROUND_COL.get(f["properties"].get("role"))
        if c:
            gfeat.append({"type": "Feature", "geometry": f["geometry"], "properties": {"c": c}})
    def area(f):
        g = f["geometry"]; rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
        return sum(abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) for r in rings)
    gfeat.sort(key=area, reverse=True)                    # big backdrops first, canal/roads/walks drawn over them

    # landmark stops: the block whose name matches, the route point nearest its centroid
    stops = []
    for spec in [x for x in arg("--stops", "").split("|") if x]:
        key, label = (spec.split("=", 1) + [spec])[:2] if "=" in spec else (spec, spec)
        hits = [f for f in bfeat if (f["properties"].get("n") or "").lower() == key.lower()]
        if not hits:
            print("  stop %-24s MISSING" % label)
            continue
        ring = hits[0]["geometry"]["coordinates"][0] if hits[0]["geometry"]["type"] == "Polygon" \
            else hits[0]["geometry"]["coordinates"][0][0]
        c = [sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)]
        k = min(range(len(pts)), key=lambda i: metres(pts[i], c))
        stops.append({"label": label, "s": cum[k], "c": c, "ids": [f["properties"]["i"] for f in hits],
                      "h": max(f["properties"]["h"] for f in hits)})
        print("  stop %-24s %4.0f m from track, %3.0f m tall" % (label, metres(pts[k], c), stops[-1]["h"]))
    stops.sort(key=lambda s: s["s"])

    # the timeline: intro (high, top-down-ish -> oblique on the route start), travel with stops, hold
    xs = [p[0] for f in bfeat for p in (f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon"
                                        else f["geometry"]["coordinates"][0][0])]
    ys = [p[1] for f in bfeat for p in (f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon"
                                        else f["geometry"]["coordinates"][0][0])]
    centre = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    RIDE_Z, RIDE_P, LOOK = 16.3, 62, 220.0
    frames = []

    def ride_view(s):
        p, idx = at(s)
        ahead, _ = at(s + 260)
        behind, _ = at(s - 260)
        b = bearing(behind, ahead)
        look, _ = at(s + LOOK)
        return {"center": look, "zoom": RIDE_Z, "pitch": RIDE_P, "bearing": b, "dot": p, "n": idx + 1}

    v0 = ride_view(0)
    hi = {"center": centre, "zoom": 13.9, "pitch": 30, "bearing": v0["bearing"] - 40}
    for k in range(int(1.2 * FPS)):
        frames.append(dict(hi, dot=pts[0], n=2, label=place, lw=1))
    nI = int(6 * FPS)
    for k in range(nI):
        e = ease(k / (nI - 1))
        frames.append({"center": [lerp(hi["center"][0], v0["center"][0], e), lerp(hi["center"][1], v0["center"][1], e)],
                       "zoom": lerp(hi["zoom"], v0["zoom"], e), "pitch": lerp(hi["pitch"], v0["pitch"], e),
                       "bearing": lerp_angle(hi["bearing"], v0["bearing"], e), "dot": pts[0], "n": 2,
                       "label": place, "lw": max(0.0, 1 - k / (0.4 * nI))})
    knots = [0.0] + [s["s"] for s in stops] + [L * 0.995]
    nR = int(seconds * FPS)
    for i in range(len(knots) - 1):
        a, b = knots[i], knots[i + 1]
        nf = max(2, int(nR * (b - a) / max(1.0, knots[-1])))
        for k in range(nf):
            frames.append(ride_view(a + (b - a) * ease(k / (nf - 1))))
        if i < len(stops):
            st = stops[i]
            base = ride_view(b)
            orbit = {"center": st["c"], "zoom": max(15.6, 17.4 - st["h"] / 260), "pitch": 58,
                     "bearing": bearing(base["dot"], st["c"]) - 25}
            nS, nT = int(4.5 * FPS), int(1.2 * FPS)
            for k in range(nS):
                w = ease(min(1.0, k / nT, (nS - 1 - k) / nT))
                frames.append({"center": [lerp(base["center"][0], orbit["center"][0], w), lerp(base["center"][1], orbit["center"][1], w)],
                               "zoom": lerp(base["zoom"], orbit["zoom"], w), "pitch": lerp(base["pitch"], orbit["pitch"], w),
                               "bearing": lerp_angle(base["bearing"], orbit["bearing"] + 18 * (k / nS), w),
                               "dot": base["dot"], "n": base["n"], "hl": st["ids"] if w > 0.05 else [],
                               "label": st["label"], "lw": max(0.0, (w - 0.4) * 1.7)})
    end = ride_view(L * 0.995)
    wide = {"center": centre, "zoom": 14.6, "pitch": 50, "bearing": end["bearing"]}
    nE = int(3.5 * FPS)
    for k in range(nE):                                   # pull back to the whole district with the full route drawn
        e = ease(k / (nE - 1))
        frames.append({"center": [lerp(end["center"][0], wide["center"][0], e), lerp(end["center"][1], wide["center"][1], e)],
                       "zoom": lerp(end["zoom"], wide["zoom"], e), "pitch": lerp(end["pitch"], wide["pitch"], e),
                       "bearing": end["bearing"], "dot": end["dot"], "n": len(pts)})
    frames += [frames[-1]] * int(2 * FPS)

    html = (PAGE.replace("__TITLE__", "%s cycle track" % route["route"])
                .replace("__SUB__", "%s &middot; %.1f km on RTA&#39;s layer" % (place, route["km"]))
                .replace("__SRC__", "Route: RTA bicycle tracks (open data, Nov 2025). Blocks: Najma massing, LOD 100; "
                                    "some heights are estimates. Ground: Najma context layer. Research only."))
    fdir = os.path.join(BIKE, "_blocks_frames_%s_%d" % (ride, int(time.time())))
    os.makedirs(fdir, exist_ok=True)
    data = {"center": centre, "route": pts, "blocks": {"type": "FeatureCollection", "features": bfeat},
            "ground": {"type": "FeatureCollection", "features": gfeat}}
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-angle=d3d11", "--ignore-gpu-blocklist", "--enable-webgl"])
        pg = br.new_context(viewport={"width": W, "height": H}).new_page()
        pg.on("console", lambda m: m.type in ("error", "warning") and print("  [page]", m.text[:160]))
        pg.on("pageerror", lambda e: print("  [page error]", str(e)[:160]))
        # the page and its data as files: an init script carrying ~12 MB of JSON never reached set_content's page
        open(os.path.join(fdir, "data.js"), "w", encoding="utf-8").write("window.__D=" + json.dumps(data, separators=(",", ":")) + ";")
        open(os.path.join(fdir, "index.html"), "w", encoding="utf-8").write(html)
        pg.goto("file:///" + os.path.join(fdir, "index.html").replace("\\", "/"), wait_until="load", timeout=120_000)
        pg.wait_for_function("() => window.__ready === true", timeout=120_000)
        limit = int(arg("--frames", "0")) or len(frames)
        pick = [int(x) for x in arg("--pick", "").split(",") if x]       # preview: just these frame numbers
        todo = [(i, frames[i]) for i in pick if i < len(frames)] if pick else list(enumerate(frames[:limit]))
        print("timeline %d frames (%.1f s)" % (len(frames), len(frames) / FPS))
        for i, fr in todo:
            pg.evaluate("(fr) => window.__frame(fr)", fr)
            pg.screenshot(path=os.path.join(fdir, "f%05d.png" % i))
        br.close()
    if arg("--pick", ""):
        print("preview frames in", fdir)
        return
    out = os.path.join(BIKE, "blocks_ride_%s_9x16.mp4" % ride)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%05d.png"),
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out], check=True)
    print("frames %d (%.1f s) -> %s" % (min(limit, len(frames)), min(limit, len(frames)) / FPS, out))
    print("frames dir:", fdir)


if __name__ == "__main__":
    main()
