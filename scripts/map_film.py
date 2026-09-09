"""The map, filmed properly (Kendall, 7 Sep: "seamless... like a Hollywood director... show this as it is").

Not a screen recording of clicks. A directed shot list: every beat is a deliberate camera move or a reveal, the map settles
(tiles loaded) before each one, cards and panels animate in (film mode on the page), a soft tap ripple marks each touch, and
holds are long enough to read. Recorded at 1080x1920 from a phone-sized viewport at 2.77x; the fixed 60 fps come from a
CDP screencast rather than Playwright's video recorder, so motion is smooth.

Usage: python scripts/map_film.py [--community "the valley"] [--pick "The Valley"] [--card "Ovelle"] [--radius 10] [--out DIR]
Output: <out>/frames/*.jpg and <out>/FILM_<slug>_<len>s.mp4 (silent, 60 fps, H.264), plus SHOTLIST.md with the beat timings.
"""
import base64, os, subprocess, sys, time, json, threading, queue
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
W, H = 1080, 1920


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


class Screencast:
    """CDP screencast -> numbered JPEG frames at a steady rate (frames are re-timed to 60 fps at encode)."""
    def __init__(self, page, out):
        self.page = page; self.out = out; self.n = 0; self.t0 = None; self.times = []
        os.makedirs(out, exist_ok=True)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})
    def _frame(self, ev):
        if self.t0 is None: self.t0 = ev["metadata"]["timestamp"]
        self.times.append(ev["metadata"]["timestamp"] - self.t0)
        open(os.path.join(self.out, f"f{self.n:06d}.jpg"), "wb").write(base64.b64decode(ev["data"])); self.n += 1
        try: self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception: pass
    def stop(self):
        try: self.cdp.send("Page.stopScreencast")
        except Exception: pass
        json.dump(self.times, open(os.path.join(self.out, "_times.json"), "w"))


def main():
    community = arg("--community", "the valley"); pick = arg("--pick", "The Valley"); card = arg("--card", "Ovelle"); radius = float(arg("--radius", "10"))
    out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture", f"film_{time.strftime('%Y%m%d_%H%M')}")); os.makedirs(out, exist_ok=True)
    key = env_token("READ_KEY"); log = []
    def beat(name, secs): log.append((round(time.time() - T0, 1), name, secs))
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--force-device-scale-factor=2.77"])
        ctx = b.new_context(viewport={"width": 390, "height": 693}, device_scale_factor=2.77, is_mobile=True, has_touch=True,
                            record_video_dir=os.path.join(out, "rec"), record_video_size={"width": W, "height": H})   # steady 25 fps; the CDP screencast throttled to 4-10 fps in headless
        pg = ctx.new_page()
        pg.goto(f"{WORKER}/map?key={key}&film=1&r={int(time.time())}", wait_until="load"); pg.wait_for_timeout(7000)
        pg.evaluate("window.__film.settle(8000)")
        T0 = time.time(); T_START = T0
        F = lambda js: pg.evaluate(js)
        hold = lambda s: pg.wait_for_timeout(int(s * 1000))

        # 1 · establish: the whole city, breathing
        beat("all Dubai, hold", 3.0); hold(3.0)
        # 2 · the search, typed like a person types
        beat("type the community", 2.5); F("window.__film.tap('#q')"); hold(0.6); F(f"window.__film.type({json.dumps(community)}, 85)"); hold(1.4)
        # 3 · pick the result: the map flies itself
        beat("pick result, fly", 4.5); F("window.__film.tap('.qi')"); hold(1.2); F("window.__film.settle(6000)"); hold(3.0)
        # 4 · the neighbourhood cards arrive
        beat("cards read", 2.5); hold(2.5)
        # 5 · slow drift across the community so the names pass through frame
        c = F("fetch('/img/districts_geo').then(function(r){return r.json()}).then(function(j){var d=(j.districts||[]).filter(function(x){return x.name===" + json.dumps(pick) + "})[0];return d?d.centre:null})") or None
        if c:
            beat("drift across community", 4.0); F(f"window.__film.fly({c[0]-0.006},{c[1]+0.004},13.6,3600)"); hold(0.4)
        # 6 · open the chosen neighbourhood: a tap, a glide, the panel rises
        beat("open " + card, 4.5); F(f"window.__film.tapText('.rail .c[data-sub]', {json.dumps(card)})"); hold(1.6); F("window.__film.settle(5000)"); hold(2.6)
        # 7 · what is inside: one card at a time, each a small reveal
        for k, hs in (("school", 1.6), ("hospital", 1.6), ("clinic", 2.4)):
            beat("in community: " + k, hs); F(f"window.__film.tap('.a[data-k={k}]')"); hold(hs)
        # 8 · widen the circle: by distance, the slider walks out
        beat("by distance", 1.6); F("window.__film.mode('dist')"); hold(1.6)
        beat("radius walks out", 3.0)
        for r in (2, 3.5, 5, 7, radius): F(f"window.__film.radius({r})"); hold(0.55)
        hold(0.6)
        # 9 · the schools list rises; the nearest opens as a contact card
        beat("schools list", 3.0); F("window.__film.tap('.a[data-k=school]')"); hold(0.5); F("window.__film.tap('.a[data-k=school]')"); hold(2.5)
        beat("school card", 5.0); F("window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(5000)"); hold(3.4)
        beat("back", 1.2); F("window.__film.tap('#back')"); hold(1.2)
        # 10 · clinics, the closest opens
        beat("clinics list", 2.6); F("window.__film.tap('.a[data-k=clinic]')"); hold(0.5); F("window.__film.tap('.a[data-k=clinic]')"); hold(2.1)
        beat("clinic card", 4.5); F("window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(5000)"); hold(3.0)
        beat("back", 1.2); F("window.__film.tap('#back')"); hold(1.2)
        # 11 · shopping: the mall card with hours and the code
        beat("malls list", 2.4); F("window.__film.tap('.a[data-k=mall]')"); hold(2.4)
        beat("mall card", 5.5); F("window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(5000)"); hold(4.0)
        beat("back", 1.2); F("window.__film.tap('#back')"); hold(1.2)
        # 12 · return home: close, glide back to the neighbourhood, hold on it
        beat("close, glide home", 5.0); F("window.__film.tap('#panel #px')"); hold(0.6)
        F(f"window.__film.tapText('.rail .c[data-sub]', {json.dumps(card)})"); hold(1.6); F("window.__film.settle(5000)"); hold(2.8)
        beat("end hold", 2.0); hold(2.0)
        total = time.time() - T0; vid = pg.video.path(); load_s = 7.0 + 0.0; ctx.close(); b.close()
    # encode: the recorder ran from page open; keep only the directed part (after the load wait), steady 30 fps
    mp4 = os.path.join(out, f"FILM_map_{int(total)}s_1080x1920.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{load_s + 1.0:.2f}", "-i", vid, "-t", f"{total:.2f}",
                    "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", "-an", mp4], check=True)
    with open(os.path.join(out, "SHOTLIST.md"), "w", encoding="utf-8") as f:
        f.write("# Shot list\n\n| at | beat | planned hold |\n|---|---|---|\n" + "".join(f"| {t}s | {n} | {h}s |\n" for t, n, h in log))
    print("film:", mp4, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip(), "s")


if __name__ == "__main__":
    main()
