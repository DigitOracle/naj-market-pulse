"""The map and the twin, filmed widescreen for a client (Kendall, 8 Sep 2026: "widescreen, pick something that has schools,
hospitals... pivot to the developer cards... costs, sold, remaining... then pivot at the end to the digital twin, click on the
card - that is the hero closer").

Same method as map_film.py (the Valley film): a directed shot list, not a screen recording. Every beat is a deliberate move,
the map settles before each one, cards animate in (film mode), a tap ripple marks each touch, holds are long enough to read.

Capture: a headed browser on the GPU (the twin is WebGL), 960x540 viewport at 2x, frames taken through the CDP screencast at
device resolution (1920x1080) - Playwright's own recorder ignores the device scale and lands a 1200x675 page in the frame.
The screencast only sends a frame when something changed, so frames carry timestamps and are re-timed to a steady 30 fps at
encode. The map and the twin are two screencast segments (the twin's load wait is never in the film) joined with a dissolve.

Usage: python scripts/map_film_wide.py [--community "business bay"] [--pick "Business Bay"] [--slug businessbay]
                                       [--place "Al Habtoor City"] [--home "Inaura"] [--home2 "Symphony Tower"] [--tower "One River Point"] [--out DIR]
Output: <out>/FILM_wide_<len>s_1920x1080.mp4 (silent, 30 fps) + SHOTLIST.md
"""
import base64, json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
W, H = 1920, 1080


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


class Screencast:
    """CDP screencast -> JPEG frames with their timestamps; segment() encodes one steady-30fps clip from a time window."""
    def __init__(self, ctx, page, out):
        self.page = page; self.out = out; self.n = 0; self.frames = []          # (timestamp, path)
        os.makedirs(out, exist_ok=True)
        self.cdp = ctx.new_cdp_session(page); self.cdp.on("Page.screencastFrame", self._frame); self.on = False
    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1}); self.on = True
    def stop(self):
        if self.on:
            try: self.cdp.send("Page.stopScreencast")
            except Exception: pass
        self.on = False
    def _frame(self, ev):
        p = os.path.join(self.out, f"f{self.n:06d}.jpg"); self.n += 1
        open(p, "wb").write(base64.b64decode(ev["data"])); self.frames.append((ev["metadata"]["timestamp"], p))
        try: self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception: pass
    def segment(self, t0, t1, mp4):
        """frames whose timestamps fall in [t0, t1] (CDP monotonic clock = time.time() on Chromium), held until the next one."""
        fr = [(t, p) for t, p in self.frames if t <= t1]
        before = [x for x in fr if x[0] <= t0]; fr = ([before[-1]] if before else []) + [x for x in fr if x[0] > t0]
        if not fr: raise SystemExit("no frames in segment")
        lst = os.path.join(self.out, os.path.basename(mp4) + ".txt")
        with open(lst, "w", encoding="utf-8") as f:
            for i, (t, p) in enumerate(fr):
                start = max(t, t0); end = fr[i + 1][0] if i + 1 < len(fr) else t1
                d = max(0.001, end - start)
                f.write(f"file '{p.replace(os.sep, '/')}'\nduration {d:.4f}\n")
            f.write(f"file '{fr[-1][1].replace(os.sep, '/')}'\n")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-an", mp4], check=True)
        return t1 - t0


def main():
    community = arg("--community", "business bay"); pick = arg("--pick", "Business Bay"); slug = arg("--slug", "businessbay")
    place = arg("--place", "Al Habtoor City"); home = arg("--home", "Inaura"); home2 = arg("--home2", "Symphony Tower"); tower = arg("--tower", "One River Point")
    out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture", f"filmwide_{time.strftime('%Y%m%d_%H%M')}")); os.makedirs(out, exist_ok=True)
    key = env_token("READ_KEY"); log = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, args=["--window-position=40,40", "--window-size=1180,800", "--ignore-gpu-blocklist", "--enable-gpu-rasterization"])
        ctx = b.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2)
        pg = ctx.new_page()
        pg.goto(f"{WORKER}/map?key={key}&film=1&wide=1&r={int(time.time())}", wait_until="load"); pg.wait_for_timeout(6000)
        pg.evaluate("window.__film.settle(8000)")
        sc = Screencast(ctx, pg, os.path.join(out, "frames")); sc.start(); pg.wait_for_timeout(600)
        T0 = time.time()
        F = lambda js: pg.evaluate(js)
        hold = lambda s: pg.wait_for_timeout(int(s * 1000))
        def beat(name, secs): log.append((round(time.time() - T0, 1), name, secs))

        # ---- I · the city, then the district ------------------------------------------------------------------------
        beat("all Dubai, hold", 3.0); hold(3.0)
        beat("type the community", 2.6); F("window.__film.tap('#q')"); hold(0.5); F(f"window.__film.type({json.dumps(community)}, 80)"); hold(1.3)
        beat("pick result, fly", 4.5); F("window.__film.tap('.qi')"); hold(1.2); F("window.__film.settle(6000)"); hold(3.0)
        beat("sub-community cards read", 2.0); hold(2.0)
        c = F("fetch('/img/districts_geo').then(function(r){return r.json()}).then(function(j){var d=(j.districts||[]).filter(function(x){return x.name===" + json.dumps(pick) + "})[0];return d?d.centre:null})") or None
        if c:
            beat("drift across the district", 3.6); F(f"window.__film.fly({c[0]+0.004},{c[1]-0.002},14.2,3200)"); hold(0.4)
        # ---- II · one place, and what sits around it ------------------------------------------------------------------
        beat("open " + place, 4.0); F(f"window.__film.tapText('.rail .c[data-sub]', {json.dumps(place)})"); hold(1.4); F("window.__film.settle(5000)"); hold(2.4)
        beat("hospital in the community", 2.6); F("window.__film.tap('.a[data-k=hospital]')"); hold(2.6)
        beat("hospital contact card", 4.6); F("window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(4000)"); hold(3.0)
        beat("back", 1.0); F("window.__film.tap('#back')"); hold(1.0)
        beat("metro", 2.6); F("window.__film.tap('.a[data-k=hospital]')"); hold(0.4); F("window.__film.tap('.a[data-k=metro]')"); hold(2.2)
        beat("close", 0.8); F("window.__film.tap('#panel #px')"); hold(0.4); F("window.__film.tap('.a[data-k=metro]')"); hold(0.4)
        # ---- III · widen the circle: the schools appear by distance ----------------------------------------------------
        beat("by distance", 1.4); F("window.__film.mode('dist')"); hold(1.4)
        beat("radius walks out", 3.2)
        for r in (1.5, 2, 2.5, 3, 3.5, 4): F(f"window.__film.radius({r})"); hold(0.5)
        hold(0.2)
        beat("schools list", 3.0); F("window.__film.tap('.a[data-k=school]')"); hold(3.0)
        beat("school contact card", 5.0); F("window.__film.tapText('#panel .nk', 'Dubai British School')||window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(4000)"); hold(3.4)
        beat("back, close", 1.4); F("window.__film.tap('#back')"); hold(0.7); F("window.__film.tap('#panel #px')"); hold(0.4); F("window.__film.tap('.a[data-k=school]')"); hold(0.3)
        beat("scope back to the community", 0.8); F("window.__film.mode('in')"); hold(0.8)
        # ---- IV · the developer cards: budget sliders, live sheets only, costs, sold, remaining ----------------------------
        beat("open HOMES", 1.6); F("window.__film.tap('#hh')"); hold(1.6)
        beat("sliders: budget and bedrooms", 3.6)
        for lo, hi in ((10, 30), (11, 33), (12, 36)):
            F(f"(function(){{var s=function(id,v){{var e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('input'))}};s('hlo',{lo});s('hhi',{hi})}})()"); hold(0.5)
        F("(function(){var s=function(id,v){var e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('input'))};s('hblo',1);s('hbhi',3)})()"); hold(2.1)
        beat("live availability only", 2.2); F("window.__film.tap('#hp .seg button[data-x=live]')"); hold(2.2)
        beat("the list", 2.6); F("window.__film.tap('#hlist')"); hold(0.6); F("window.__film.tap('#hh')"); hold(2.0)
        beat("open " + home, 7.0); F(f"window.__film.tapText('#panel .nk', {json.dumps(home)})"); hold(1.6); F("window.__film.settle(5000)"); hold(5.4)
        beat("back to the list", 1.6); F("window.__film.tap('#panel #px')"); hold(0.5); F("window.__film.tap('#hh')"); hold(0.4); F("window.__film.tap('#hlist')"); hold(0.4); F("window.__film.tap('#hh')"); hold(0.3)
        beat("open " + home2, 6.0); F(f"window.__film.tapText('#panel .nk', {json.dumps(home2)})"); hold(1.6); F("window.__film.settle(5000)"); hold(4.4)
        beat("end of the map", 1.0); hold(1.0)
        T_MAP_END = time.time(); sc.stop()
        # ---- V · the twin: the hero closer ------------------------------------------------------------------------------
        pg.goto(f"{WORKER}/skyline/{slug}?key={key}&film=1&wide=1&r={int(time.time())}", wait_until="load")
        for i in range(150):
            hold(1.0)
            if F("!!(window.__twinFilm&&window.__twinFilm.loaded()&&!document.getElementById('msg'))"): break
        hold(2.0); F("window.__twinFilm.orbit(true,0.6)")
        sc2 = Screencast(ctx, pg, os.path.join(out, "frames2")); sc2.start(); hold(0.6)
        T_TWIN_START = time.time(); beat("TWIN begins", 0)
        beat("the skyline turns", 5.0); hold(5.0)
        beat("open " + tower, 6.0); ok = F(f"window.__twinFilm.open({json.dumps(tower)})"); log.append((round(time.time() - T0, 1), "tower opened: " + str(ok), 0)); hold(6.0)
        SCR = "(function(){var p=document.getElementById('ppanel');if(!p)return false;var t=p.querySelector(SEL);var y=t?Math.max(0,t.offsetTop-14):p.scrollHeight;p.scrollTo({top:y,behavior:'smooth'});return y})()"
        beat("scroll: the unit mix", 6.0); F(SCR.replace("SEL", "'table,.mix,.um'")); hold(6.0)
        beat("scroll: plot, property, floors, the views", 5.0); F(SCR.replace("SEL", "'.vw'")); hold(5.0)
        beat("stand on a facade", 0.0); side = F("(function(){var c=[].slice.call(document.querySelectorAll('#ppanel .vc:not(.blk)'));if(!c.length)return null;var el=c[0];return {side:el.querySelector('b').textContent,href:el.getAttribute('href')}})()")
        T_TWIN_END = time.time(); sc2.stop(); hold(0.2)
        segs = [(sc, T0, T_MAP_END), (sc2, T_TWIN_START, T_TWIN_END)]
        if side and side.get("href") and "--view" in sys.argv:      # Kendall, 8 Sep: the real views are no good - opt-in only
            F("window.__film.tapText('#ppanel .vc', %s)" % json.dumps(side["side"])); hold(0.5)
            pg.wait_for_load_state("load"); hold(1.5)
            for i in range(40):
                hold(1.0)
                if F("(function(){var im=[].slice.call(document.images);return im.length>0&&im.every(function(i){return i.complete})})()"): break
            sc3 = Screencast(ctx, pg, os.path.join(out, "frames3")); sc3.start(); hold(0.6)
            T_VIEW = time.time(); beat("the real view from the " + side["side"] + " facade", 6.0); hold(6.0)
            T_END = time.time(); sc3.stop(); hold(0.2); segs.append((sc3, T_VIEW, T_END))
        parts, durs = [], []
        for i, (scx, ta, tb) in enumerate(segs):
            m = os.path.join(out, f"seg_{i}.mp4"); durs.append(scx.segment(ta, tb, m)); parts.append(m)
        print("frames:", [scx.n for scx, _, _ in segs])
        ctx.close(); b.close()
    X = 0.8; total = sum(durs) - X * (len(parts) - 1); mp4 = os.path.join(out, f"FILM_wide_{int(total)}s_1920x1080.mp4")
    if len(parts) == 1: fc = "[0:v]format=yuv420p[v]"
    else:
        fc = ""; prev = "[0:v]"; off = 0.0
        for i in range(1, len(parts)):
            off += durs[i - 1] - X; lab = "[v]" if i == len(parts) - 1 else f"[x{i}]"
            fc += f"{prev}[{i}:v]xfade=transition=fade:duration={X}:offset={off:.2f}{lab};"; prev = lab
        fc = fc.rstrip(";")
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for m in parts: cmd += ["-i", m]
    subprocess.run(cmd + ["-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", "-an", mp4], check=True)
    with open(os.path.join(out, "SHOTLIST.md"), "w", encoding="utf-8") as f:
        f.write("# Shot list (widescreen)\n\n| at | beat | planned hold |\n|---|---|---|\n" + "".join(f"| {t}s | {n} | {h}s |\n" for t, n, h in log))
        f.write(f"\nsegments {[round(d, 1) for d in durs]} s \u00b7 dissolve {X}s\n")
    print("film:", mp4, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip(), "s")


if __name__ == "__main__":
    main()
