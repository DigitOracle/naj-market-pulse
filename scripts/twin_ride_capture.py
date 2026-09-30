"""A cycle route ridden through Najma's digital twin - chase camera, glowing gold track, 9:16 film.

Kendall, 29 Sep 2026: the 2D route clips are "really super boring" - "can we explore this in the digital twin?", then
"you can build it here" and "only one district, not all of them, as a test". So this films ONE route inside ONE
district's twin (/skyline/<slug>): the default is the Boulevard cycle track in Downtown Dubai, all 3.3 km of it
inside that district.

Nothing in the live app changes. The page's own lon/lat -> scene function (_scene, used by its map overlays) lives in
module scope, so at capture time the page HTML is intercepted and one line exposes it (with the scene and THREE) to
the ride code injected here. The route is a gold tube grown along the path (draw range), on the page's bloom layer
so it glows; a bright sphere rides its head; the camera chases from behind and above, its heading smoothed over the
path so corners do not jolt. Frames are stepped and screenshotted one at a time, so the film is smooth whatever the
machine's load.

    python scripts/twin_ride_capture.py [--ride boulevard] [--district burjkhalifa] [--seconds 18]
Reads data/bike/rides/<ride>.json (coords in drawing order, from the route animation's walk).
Writes data/bike/twin_ride_<ride>_9x16.mp4.
"""
import json
import os
import time
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NAJMA_VIDEO", "10")
import demo_capture as D                                    # noqa: E402  - url(), the CLIENT key, W and H
from playwright.sync_api import sync_playwright              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIKE = os.path.join(ROOT, "data", "bike")
FPS = 25
HOOK_AT = "window.__twinFilm={"
HOOK = "window.__ride={scene:scene,THREE:THREE,at:_scene,cam:cam,ctl:ctl};"

HIDE_CSS = ("#scope,#panel,#hint,#hstack,#rail1,#rail2,#twmk,#mini,#card,#filters,#feat,.foot,.nnav,#legend,#ppanel,"
            "#stkp,#devwrap{display:none!important}"
            ".top>*:not(h1):not(#st){display:none!important}")   # keep only the title and the district line

CAPTION_JS = """(t) => { const d = document.createElement('div'); d.id = 'ridecap';
  d.style.cssText = 'position:fixed;left:48px;bottom:120px;z-index:99;color:#f2f4f7;font:600 40px system-ui;'
    + 'text-shadow:0 2px 12px #000';
  d.innerHTML = t; document.body.appendChild(d); }"""

RIDE_JS = r"""
(route) => {
  const R = window.__ride, T = R.THREE, S = window.__sky;
  const pts = route.coords.map(c => R.at(c[0], c[1])).filter(Boolean).map(p => p.add(new T.Vector3(0, route.lift, 0)));
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + pts[i].distanceTo(pts[i - 1]));
  const L = cum[cum.length - 1];
  const at = (s) => {                                   // position at distance s along the path
    s = Math.max(0, Math.min(L, s));
    let lo = 0, hi = cum.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] <= s) lo = m; else hi = m; }
    const k = (s - cum[lo]) / Math.max(1e-6, cum[hi] - cum[lo]);
    return pts[lo].clone().lerp(pts[hi], k);
  };
  const curve = new T.CatmullRomCurve3(pts.filter((p, i) => i === 0 || p.distanceTo(pts[i - 1]) > 1.5), false, "centripetal");
  const segs = Math.min(6000, Math.max(400, Math.round(L / 2)));
  const radial = 6;
  const tube = new T.Mesh(new T.TubeGeometry(curve, segs, route.tube, radial, false),
                          new T.MeshBasicMaterial({ color: 0xC5A56A, toneMapped: false }));
  tube.layers.enable(1);                                 // the page's bloom layer
  tube.geometry.setDrawRange(0, route.ahead ? Infinity : 0);   // first person: the whole route shows ahead
  R.scene.add(tube);
  const dot = new T.Mesh(new T.SphereGeometry(route.dot, 24, 16), new T.MeshBasicMaterial({ color: 0xFFF4D6, toneMapped: false }));
  dot.layers.enable(1);
  dot.visible = !route.ahead;                            // first person: the camera is the rider
  R.scene.add(dot);
  if (route.lane) {                                      // a painted cycle lane, as Dubai lays them (Kendall's photos,
    tube.visible = false;                                // 30 Sep): red, white centre line, yellow edges, symbols
    const cv = document.createElement("canvas"); cv.width = 256; cv.height = 2560;   // 3.0 m wide x 30 m long
    const g = cv.getContext("2d"), M = 256 / 3.0;         // px per metre
    g.fillStyle = "#B4463E"; g.fillRect(0, 0, 256, 2560);
    g.fillStyle = "#E8B923"; g.fillRect(0, 0, 0.16 * M, 2560); g.fillRect(256 - 0.16 * M, 0, 0.16 * M, 2560);
    g.fillStyle = "#F4F1EA"; g.fillRect(128 - 0.06 * M, 0, 0.12 * M, 2560);
    g.strokeStyle = "#F4F1EA"; g.fillStyle = "#F4F1EA"; g.lineWidth = 0.07 * M; g.lineCap = "round";
    const bike = (cx, cy, s) => {                       // a plain bicycle pictogram, s = wheel radius in px
      g.beginPath(); g.arc(cx - 1.25 * s, cy, s, 0, 7); g.stroke();
      g.beginPath(); g.arc(cx + 1.25 * s, cy, s, 0, 7); g.stroke();
      g.beginPath(); g.moveTo(cx - 1.25 * s, cy); g.lineTo(cx - 0.2 * s, cy - 1.1 * s); g.lineTo(cx + 0.9 * s, cy - 1.1 * s);
      g.lineTo(cx + 1.25 * s, cy); g.moveTo(cx - 0.2 * s, cy - 1.1 * s); g.lineTo(cx, cy); g.lineTo(cx + 0.9 * s, cy - 1.1 * s);
      g.moveTo(cx - 0.35 * s, cy - 1.45 * s); g.lineTo(cx - 0.05 * s, cy - 1.45 * s);
      g.moveTo(cx + 0.9 * s, cy - 1.1 * s); g.lineTo(cx + 0.8 * s, cy - 1.6 * s); g.stroke();
    };
    const scooter = (cx, cy, s) => {
      g.beginPath(); g.arc(cx - 1.2 * s, cy, 0.6 * s, 0, 7); g.stroke();
      g.beginPath(); g.arc(cx + 1.2 * s, cy, 0.6 * s, 0, 7); g.stroke();
      g.beginPath(); g.moveTo(cx - 1.2 * s, cy - 0.1 * s); g.lineTo(cx + 1.0 * s, cy - 0.1 * s); g.lineTo(cx + 1.2 * s, cy - 2.2 * s);
      g.lineTo(cx + 0.8 * s, cy - 2.2 * s); g.stroke();
    };
    const arrow = (cx, cy, up) => {                     // up: pointing along the direction of travel
      const d = up ? -1 : 1; g.beginPath();
      g.moveTo(cx, cy + d * 1.1 * M); g.lineTo(cx - 0.35 * M, cy + d * 0.4 * M); g.lineTo(cx - 0.12 * M, cy + d * 0.4 * M);
      g.lineTo(cx - 0.12 * M, cy - d * 1.0 * M); g.lineTo(cx + 0.12 * M, cy - d * 1.0 * M); g.lineTo(cx + 0.12 * M, cy + d * 0.4 * M);
      g.lineTo(cx + 0.35 * M, cy + d * 0.4 * M); g.closePath(); g.fill();
    };
    const R_ = 192, L_ = 64;                             // right and left lane centres (px)
    g.save(); g.translate(R_, 5 * M); g.rotate(-Math.PI / 2); bike(0, 0, 0.3 * M); g.restore();
    g.save(); g.translate(R_, 8.5 * M); g.rotate(-Math.PI / 2); scooter(0, 0, 0.25 * M); g.restore();
    arrow(R_, 12 * M, true);
    arrow(L_, 5 * M, false);
    g.save(); g.translate(L_, 8.5 * M); g.rotate(Math.PI / 2); bike(0, 0, 0.3 * M); g.restore();
    g.beginPath(); g.arc(L_, 12.5 * M, 0.4 * M, 0, 7); g.fill();
    g.fillStyle = "#B4463E"; g.font = "bold " + Math.round(0.42 * M) + "px system-ui"; g.textAlign = "center";
    g.textBaseline = "middle"; g.save(); g.translate(L_, 12.5 * M); g.rotate(Math.PI); g.fillText("20", 0, 0); g.restore();
    const tex = new T.CanvasTexture(cv); tex.wrapS = T.ClampToEdgeWrapping; tex.wrapT = T.RepeatWrapping;
    tex.colorSpace = T.SRGBColorSpace; tex.anisotropy = 16;
    // ribbon along the smoothed path, 3 m wide, just above the ground
    const n = Math.max(2, Math.round(L / 1.2)), sp = curve.getSpacedPoints(n);
    const pos = [], uv = [], idx = []; let dist = 0;
    for (let i = 0; i <= n; i++) {
      const a = sp[Math.max(0, i - 1)], b = sp[Math.min(n, i + 1)];
      const t = b.clone().sub(a).setY(0).normalize(), side = new T.Vector3(-t.z, 0, t.x).multiplyScalar(1.5);
      if (i > 0) dist += sp[i].distanceTo(sp[i - 1]);
      const c = sp[i].clone(); c.y -= route.lift - 0.25;
      pos.push(...c.clone().add(side).toArray(), ...c.clone().sub(side).toArray());
      uv.push(1, dist / 30, 0, dist / 30);
      if (i < n) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2)); geo.setIndex(idx); geo.computeVertexNormals();
    const lane = new T.Mesh(geo, new T.MeshStandardMaterial({ map: tex, roughness: 0.9, metalness: 0,
      side: T.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 }));
    lane.receiveShadow = true; R.scene.add(lane);
    S.cam.near = 1.0; S.cam.updateProjectionMatrix();    // the page's 6 m near plane would clip the lane at rider height
  }
  S.ctl.autoRotate = false; S.ctl.enabled = false;
  const up = new T.Vector3(0, 1, 0);
  window.__rideSet = (f, o) => {                          // f in [0,1]
    const s = f * L;
    if (!route.ahead) tube.geometry.setDrawRange(0, Math.round(f * segs) * radial * 6);
    const p = at(s); dot.position.copy(p);
    const a = at(s - o.smooth), b = at(s + o.smooth);
    const dir = b.clone().sub(a).setY(0); if (dir.lengthSq() < 1e-6) dir.set(0, 0, -1); dir.normalize();
    const pos = p.clone().sub(dir.clone().multiplyScalar(o.back)).add(up.clone().multiplyScalar(o.height));
    // look along the direction of travel, a little above the track - at(s + look) clamps at the route's end and
    // pitched the last frames straight down at the ground
    const tgt = p.clone().add(dir.clone().multiplyScalar(o.look)).add(up.clone().multiplyScalar(o.height * 0.35));
    S.cam.position.lerp(pos, o.ease); S.ctl.target.lerp(tgt, o.ease);
    S.cam.lookAt(S.ctl.target);
  };
  window.__rideSnap = (o) => { window.__rideSet(0, Object.assign({}, o, { ease: 1 })); };
  return { points: pts.length, metres: Math.round(L) };
}
"""


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    ride = arg("--ride", "boulevard")
    district = arg("--district", "burjkhalifa")
    seconds = float(arg("--seconds", "18"))
    route = json.load(open(os.path.join(BIKE, "rides", ride + ".json"), encoding="utf-8"))
    frames_dir = arg("--resume", "") or os.path.join(BIKE, "_twin_frames_%s_%d" % (ride, int(time.time())))
    # --resume <folder>: carry on in a folder a failed run left, from its next missing frame
    os.makedirs(frames_dir, exist_ok=True)
    # Downtown's towers reach 828 m, so a street-level chase flies through them: this is a drone chase, high and
    # behind, looking down at the dot (scene units are metres - 1 km east measures 1,008 m).
    opts = {"back": float(arg("--back", "520")), "height": float(arg("--height", "420")),
            "look": float(arg("--look", "60")), "smooth": float(arg("--smooth", "260")), "ease": 1.0}
    # --view first: Kendall, 29 Sep - "make the camera angle lower, so it's almost like a first person view".
    # The Boulevard track runs along streets, so a camera ~14 m up and 25 m behind stays clear of the towers;
    # at that range the tube and dot must shrink and sit low, or they fill the frame.
    if arg("--view", "drone") == "first":
        opts.update({"back": float(arg("--back", "25")), "height": float(arg("--height", "14")),
                     "look": float(arg("--look", "90")), "smooth": float(arg("--smooth", "60"))})
    first = arg("--view", "drone") == "first"
    route["lift"] = 1.5 if first else 4.0
    route["tube"] = 0.75 if first else 6.0
    route["dot"] = 1.6 if first else 18.0
    route["ahead"] = first     # first person: behind the camera a growing trail is invisible, so show the road ahead
    route["lane"] = arg("--view", "drone") == "rider"
    if route["lane"]:
        # --view rider: Kendall, 30 Sep, with photos of the real lane - "make it slower and make it look like a bike
        # track". A painted red lane on the ground, the camera at a rider's eye, slow.
        route.update({"ahead": True, "lift": 1.5, "dot": 0.1})
        opts.update({"back": float(arg("--back", "6")), "height": float(arg("--height", "3.5")),
                     "look": float(arg("--look", "40")), "smooth": float(arg("--smooth", "25"))})

    def patch(r):
        resp = r.fetch()
        body = resp.text()
        if HOOK_AT in body:
            body = body.replace(HOOK_AT, HOOK + HOOK_AT, 1)
        r.fulfill(response=resp, body=body)

    n = int(seconds * FPS)
    total = n + (0 if "--no-hold" in sys.argv else int(2.5 * FPS))   # plus a 2.5 s hold on the finished route
    CHUNK = int(arg("--chunk", "24"))
    END_AT = 0.985 if route.get("lane") else 1.0      # a rider stops before the lane ends, not past it
    caption = ("%s cycle track<br><span style='font-weight:400;font-size:28px;color:#C5A56A'>%s &middot; %.1f km on "
               "RTA&#39;s layer</span>" % (route["route"], arg("--place", "Downtown Dubai"), route["km"]))

    def session(p, start):
        """One browser: load the twin, build the ride, film frames from `start` for up to CHUNK frames."""
        br = p.chromium.launch(args=["--use-angle=d3d11", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"])
        try:
            pg = br.new_context(viewport={"width": D.W, "height": D.H}).new_page()
            pg.route("**/skyline/%s*" % district, patch)
            pg.goto(D.url("/skyline/%s" % district), wait_until="domcontentloaded", timeout=120_000)
            pg.wait_for_function("() => window.__twinFilm && window.__twinFilm.loaded() && window.__ride",
                                 timeout=180_000)
            pg.wait_for_timeout(6000)                      # let tiles and textures settle
            pg.add_style_tag(content=HIDE_CSS)             # film clean: the page's panels off, header and labels kept
            pg.evaluate(CAPTION_JS, caption)
            info = pg.evaluate(RIDE_JS, route)
            if start == 0:
                print("ride %s in %s: %d points, %d m in scene" % (ride, district, info["points"], info["metres"]))
            done = start
            for i in range(start, min(total, start + CHUNK)):
                f = min(1.0, i / max(1, n - 1)) * END_AT
                pg.evaluate("([f,o]) => window.__rideSet(f,o)", [f, opts])
                pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                pg.screenshot(path=os.path.join(frames_dir, "f%05d.png" % i))
                done = i + 1
            return done
        except Exception as e:
            print("  browser stopped after frame %d: %s" % (start, str(e).splitlines()[0][:80]))
            return max(start, len([f for f in os.listdir(frames_dir) if f.endswith(".png")]))
        finally:
            try:
                br.close()
            except Exception:
                pass

    # The machine runs Unreal alongside, and one browser dies after ~30 WebGL frames on 0.4 GB free. So film in
    # chunks, a fresh browser each, resuming at the next frame. The camera is a pure function of the route position
    # (ease 1), so a chunk boundary is invisible.
    nxt, stalls = len([f for f in os.listdir(frames_dir) if f.endswith(".png")]), 0
    with sync_playwright() as p:
        while nxt < total and stalls < 6:
            got = session(p, nxt)
            stalls = stalls + 1 if got == nxt else 0
            nxt = got
            print("  %d / %d frames" % (nxt, total))
    if nxt < total:
        sys.exit("stopped at frame %d of %d" % (nxt, total))

    out = os.path.join(BIKE, "twin_ride_%s%s_9x16.mp4" % (ride, "_rider" if route.get("lane") else
                                                           ("_first" if first else "")))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i",
                    os.path.join(frames_dir, "f%05d.png"), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    out], check=True)
    print("wrote %s (%.1f s)" % (out, total / FPS))


if __name__ == "__main__":
    main()
