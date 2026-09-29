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
  const pts = route.coords.map(c => R.at(c[0], c[1])).filter(Boolean).map(p => p.add(new T.Vector3(0, 4, 0)));
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
  const tube = new T.Mesh(new T.TubeGeometry(curve, segs, 6, radial, false),
                          new T.MeshBasicMaterial({ color: 0xC5A56A, toneMapped: false }));
  tube.layers.enable(1);                                 // the page's bloom layer
  tube.geometry.setDrawRange(0, 0);
  R.scene.add(tube);
  const dot = new T.Mesh(new T.SphereGeometry(18, 24, 16), new T.MeshBasicMaterial({ color: 0xFFF4D6, toneMapped: false }));
  dot.layers.enable(1);
  R.scene.add(dot);
  S.ctl.autoRotate = false; S.ctl.enabled = false;
  const up = new T.Vector3(0, 1, 0);
  window.__rideSet = (f, o) => {                          // f in [0,1]
    const s = f * L;
    tube.geometry.setDrawRange(0, Math.round(f * segs) * radial * 6);
    const p = at(s); dot.position.copy(p);
    const a = at(s - o.smooth), b = at(s + o.smooth);
    const dir = b.clone().sub(a).setY(0); if (dir.lengthSq() < 1e-6) dir.set(0, 0, -1); dir.normalize();
    const pos = p.clone().sub(dir.clone().multiplyScalar(o.back)).add(up.clone().multiplyScalar(o.height));
    const tgt = at(s + o.look);
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
    frames_dir = os.path.join(BIKE, "_twin_frames_%s_%d" % (ride, int(time.time())))   # fresh folder each run
    os.makedirs(frames_dir, exist_ok=True)
    # Downtown's towers reach 828 m, so a street-level chase flies through them: this is a drone chase, high and
    # behind, looking down at the dot (scene units are metres - 1 km east measures 1,008 m).
    opts = {"back": float(arg("--back", "520")), "height": float(arg("--height", "420")),
            "look": float(arg("--look", "60")), "smooth": 260.0, "ease": 1.0}

    def patch(r):
        resp = r.fetch()
        body = resp.text()
        if HOOK_AT in body:
            body = body.replace(HOOK_AT, HOOK + HOOK_AT, 1)
        r.fulfill(response=resp, body=body)

    n = int(seconds * FPS)
    total = n + int(2.5 * FPS)                             # plus a 2.5 s hold on the finished route
    CHUNK = int(arg("--chunk", "24"))
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
                f = min(1.0, i / max(1, n - 1))
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
    nxt, stalls = 0, 0
    with sync_playwright() as p:
        while nxt < total and stalls < 6:
            got = session(p, nxt)
            stalls = stalls + 1 if got == nxt else 0
            nxt = got
            print("  %d / %d frames" % (nxt, total))
    if nxt < total:
        sys.exit("stopped at frame %d of %d" % (nxt, total))

    out = os.path.join(BIKE, "twin_ride_%s_9x16.mp4" % ride)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i",
                    os.path.join(frames_dir, "f%05d.png"), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    out], check=True)
    print("wrote %s (%.1f s)" % (out, total / FPS))


if __name__ == "__main__":
    main()
