"""HOMES first (Kendall, 8 Sep 2026: "another video that starts with the homes and moves through, 1:30 maximum").

Widescreen, same capture method as map_film_wide.py (CDP screencast in a headed GPU browser, two segments joined). The arc:
budget and bedrooms in, developer stock only, the list, one developer card in Dubai Marina, one in Business Bay, then what
sits around that one (schools within 3 km, a school card, hospitals within 1 km), then the twin closer on a tower. Nothing is
typed; the sliders do the talking. Budget: 90 s including title and end cards.

Usage: python scripts/map_film_homes.py [--home1 "W Residences"] [--home2 "Inaura"] [--slug businessbay] [--tower "One River Point"] [--out DIR]
"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from map_film_wide import Screencast, W, H, arg  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    home1 = arg("--home1", "W Residences"); home2 = arg("--home2", "Inaura"); slug = arg("--slug", "businessbay"); tower = arg("--tower", "One River Point")
    out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture", f"filmhomes_{time.strftime('%Y%m%d_%H%M')}")); os.makedirs(out, exist_ok=True)
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
        SET = "(function(){var s=function(id,v){var e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('input'))};%s})()"

        # ---- I · homes first: the sliders do the talking --------------------------------------------------------------
        beat("all Dubai, breath", 1.6); hold(1.6)
        beat("open HOMES", 1.6); F("window.__film.tap('#hh')"); hold(1.6)
        beat("budget walks up", 3.0)
        for lo, hi in ((10, 30), (11, 33), (12, 36), (12, 38)): F(SET % f"s('hlo',{lo});s('hhi',{hi})"); hold(0.6)
        hold(0.6)
        beat("bedrooms one to three", 1.6); F(SET % "s('hblo',1);s('hbhi',3)"); hold(1.6)
        beat("developer stock only", 2.4); F("window.__film.tap('#hlivet')"); hold(2.4)
        beat("the list", 3.0); F("window.__film.tap('#hlist')"); hold(0.6); F("window.__film.tap('#hh')"); hold(2.4)
        # ---- II · two developer cards, two districts ----------------------------------------------------------------------
        beat("open " + home1, 7.5); F(f"window.__film.tapText('#panel .nk', {json.dumps(home1)})"); hold(1.8); F("window.__film.settle(6000)"); hold(5.7)
        beat("back to the list", 1.6); F("window.__film.tap('#panel #px')"); hold(0.5); F("window.__film.tap('#hh')"); hold(0.4); F("window.__film.tap('#hlist')"); hold(0.4); F("window.__film.tap('#hh')"); hold(0.3)
        beat("open " + home2, 7.0); F(f"window.__film.tapText('#panel .nk', {json.dumps(home2)})"); hold(1.8); F("window.__film.settle(6000)"); hold(5.2)
        # ---- III · what sits around it -------------------------------------------------------------------------------------
        beat("close the card", 0.8); F("window.__film.tap('#panel #px')"); hold(0.8)
        beat("schools within 3 km", 3.0); F("window.__film.tap('.a[data-k=school]')"); hold(3.0)
        beat("school contact card", 4.6); F("window.__film.tapText('#panel .nk', 'Dubai British School')||window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(4000)"); hold(3.2)
        beat("back", 1.0); F("window.__film.tap('#back')"); hold(1.0)
        beat("tighten to 1 km", 1.6); F("window.__film.tapText('.scw button', '1 km')"); hold(1.6)
        beat("hospitals within 1 km", 3.0); F("window.__film.tap('.a[data-k=school]')"); hold(0.4); F("window.__film.tap('.a[data-k=hospital]')"); hold(2.6)
        beat("end of the map", 1.0); hold(1.0)
        T_MAP_END = time.time(); sc.stop()
        # ---- IV · the twin closer --------------------------------------------------------------------------------------------
        pg.goto(f"{WORKER}/skyline/{slug}?key={key}&film=1&wide=1&r={int(time.time())}", wait_until="load")
        for i in range(150):
            hold(1.0)
            if F("!!(window.__twinFilm&&window.__twinFilm.loaded()&&!document.getElementById('msg'))"): break
        hold(2.0); F("window.__twinFilm.orbit(true,0.6)")
        sc2 = Screencast(ctx, pg, os.path.join(out, "frames2")); sc2.start(); hold(0.6)
        T_TWIN_START = time.time(); beat("TWIN begins", 0)
        beat("the skyline turns", 4.0); hold(4.0)
        beat("open " + tower, 6.0); ok = F(f"window.__twinFilm.open({json.dumps(tower)})"); log.append((round(time.time() - T0, 1), "tower opened: " + str(ok), 0)); hold(6.0)
        SCR = "(function(){var p=document.getElementById('ppanel');if(!p)return false;var t=p.querySelector(SEL);var y=t?Math.max(0,t.offsetTop-14):p.scrollHeight;p.scrollTo({top:y,behavior:'smooth'});return y})()"
        beat("scroll: the unit mix", 5.0); F(SCR.replace("SEL", "'table,.mix,.um'")); hold(5.0)
        beat("end hold", 2.0); hold(2.0)
        T_END = time.time(); sc2.stop(); hold(0.3)
        m1 = os.path.join(out, "seg_map.mp4"); m2 = os.path.join(out, "seg_twin.mp4")
        d1 = sc.segment(T0, T_MAP_END, m1); d2 = sc2.segment(T_TWIN_START, T_END, m2)
        print(f"frames: map {sc.n} twin {sc2.n}")
        ctx.close(); b.close()
    X = 0.8; mp4 = os.path.join(out, f"FILM_homes_{int(d1 + d2 - X)}s_1920x1080.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", m1, "-i", m2, "-filter_complex", f"[0:v][1:v]xfade=transition=fade:duration={X}:offset={d1 - X:.2f},format=yuv420p[v]",
                    "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", "-an", mp4], check=True)
    with open(os.path.join(out, "SHOTLIST.md"), "w", encoding="utf-8") as f:
        f.write("# Shot list (homes first, widescreen)\n\n| at | beat | planned hold |\n|---|---|---|\n" + "".join(f"| {t}s | {n} | {h}s |\n" for t, n, h in log))
        f.write(f"\nmap part {d1:.1f}s, twin part {d2:.1f}s, dissolve {X}s\n")
    print("film:", mp4, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip(), "s")


if __name__ == "__main__":
    main()
