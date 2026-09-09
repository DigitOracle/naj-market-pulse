"""HOMES tab first (Kendall, 8 Sep 2026: "start from the homes tab, with the developer cards").

Widescreen. Four pages, one film: the developers grid (/home) -> a developer's page with its KPIs and property cards (/dev)
-> that property on the twin (/skyline/<slug>?b=) with its panel -> the same property on the map with what sits around it.
Each page is its own screencast segment (a navigation ends a screencast), the load waits are cut, segments are joined with
dissolves. A soft ripple is injected before every click so the taps read on screen.

Usage: python scripts/map_film_hometab.py [--dev Arada] [--prop "W Residences at Dubai Harbour"] [--out DIR]
"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from map_film_wide import Screencast, W, H, arg  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

RIP = ("(function(){if(window.__rip)return;var st=document.createElement('style');st.textContent='.tapfx2{position:fixed;z-index:9999;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;"
       "background:rgba(197,165,106,.55);box-shadow:0 0 0 2px rgba(197,165,106,.9);pointer-events:none;animation:tapfx2 .7s ease-out forwards}@keyframes tapfx2{to{transform:scale(3.2);opacity:0}}';"
       "document.head.appendChild(st);window.__rip=function(x,y){var d=document.createElement('div');d.className='tapfx2';d.style.left=x+'px';d.style.top=y+'px';document.body.appendChild(d);setTimeout(function(){d.remove()},800)}})()")


def main():
    dev = arg("--dev", "Arada"); prop = arg("--prop", "W Residences at Dubai Harbour")
    out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture", f"filmhometab_{time.strftime('%Y%m%d_%H%M')}")); os.makedirs(out, exist_ok=True)
    key = env_token("READ_KEY"); log = []; segs = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, args=["--window-position=40,40", "--window-size=1180,800", "--ignore-gpu-blocklist", "--enable-gpu-rasterization"])
        ctx = b.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2)
        pg = ctx.new_page()
        T0 = [None]
        F = lambda js: pg.evaluate(js)
        hold = lambda s: pg.wait_for_timeout(int(s * 1000))
        def beat(name, secs): log.append((round(time.time() - T0[0], 1), name, secs))
        def tap(sel, text=None):
            el = pg.locator(sel).filter(has_text=text).first if text else pg.locator(sel).first
            try: el.evaluate("e=>e.scrollIntoView({block:'center'})"); hold(0.4)
            except Exception: pass
            bb = el.bounding_box()
            if bb: F(RIP); F(f"window.__rip({bb['x'] + bb['width'] / 2},{bb['y'] + bb['height'] / 2})"); hold(0.35)
            el.click(force=True, timeout=8000)
        def scroll_to(y, ms=1800):
            F(f"window.scrollTo({{top:{int(y)},behavior:'smooth'}})"); hold(ms / 1000 + 0.2)
        def start(name):
            sc = Screencast(ctx, pg, os.path.join(out, "frames_" + name)); sc.start(); hold(0.5); t = time.time()
            if T0[0] is None: T0[0] = t
            return sc, t
        def stop(sc, t): sc.stop(); segs.append((sc, t, time.time())); hold(0.2)

        # ---- I · the developers grid ------------------------------------------------------------------------------------
        pg.goto(f"{WORKER}/home?key={key}&r={int(time.time())}", wait_until="load"); hold(3.0)
        sc, t = start("home")
        beat("developers grid", 2.4); hold(2.4)
        beat("scroll to " + dev, 2.6); y = F(f"(function(){{var t=[].slice.call(document.querySelectorAll('.tile')).filter(function(e){{return e.innerText.indexOf({json.dumps(dev)})>=0}})[0];return t?t.getBoundingClientRect().top+window.scrollY-120:0}})()"); scroll_to(y, 2000)
        beat("tap " + dev, 1.2); tap(".tile", dev); hold(0.9)
        stop(sc, t)
        # ---- II · the developer's page: KPIs, then the property card ------------------------------------------------------
        pg.wait_for_load_state("load"); hold(3.5)
        sc, t = start("dev")
        beat("KPIs read", 3.6); hold(3.6)
        y = F(f"(function(){{var p=[].slice.call(document.querySelectorAll('.prop')).filter(function(e){{return e.innerText.indexOf({json.dumps(prop)})>=0}})[0];return p?p.getBoundingClientRect().top+window.scrollY-70:600}})()")
        beat("scroll to " + prop, 3.0); scroll_to(y, 2600)
        beat("the property card", 3.4); hold(3.4)
        href = F(f"(function(){{var p=[].slice.call(document.querySelectorAll('.prop')).filter(function(e){{return e.innerText.indexOf({json.dumps(prop)})>=0}})[0];var a=p&&[].slice.call(p.querySelectorAll('a')).filter(function(x){{return /on the twin/.test(x.innerText)}})[0];return a?a.getAttribute('href'):null}})()")
        beat("on the twin", 1.2)
        card = pg.locator(".prop", has_text=prop).first; bb = card.bounding_box()
        if bb: F(RIP); F(f"window.__rip({bb['x'] + 60},{bb['y'] + bb['height'] - 40})"); hold(0.9)
        stop(sc, t)
        pg.goto((WORKER + href) if href and href.startswith("/") else (href or f"{WORKER}/skyline/dubaimarina?key={key}"), wait_until="load")
        # ---- III · the twin: the tower and its panel -----------------------------------------------------------------------
        for i in range(150):
            hold(1.0)
            if F("!!(window.__twinFilm&&window.__twinFilm.loaded()&&!document.getElementById('msg'))"): break
        hold(2.5)
        opened = F("!!(document.getElementById('ppanel')&&document.getElementById('ppanel').classList.contains('on'))")
        if not opened: F(f"window.__twinFilm.open({json.dumps(prop)})"); hold(1.0)
        sc, t = start("twin")
        beat("the tower, panel open (auto-open=" + str(opened) + ")", 7.0); hold(7.0)
        SCR = "(function(){var p=document.getElementById('ppanel');if(!p)return false;var t=p.querySelector(SEL);var y=t?Math.max(0,t.offsetTop-14):p.scrollHeight;p.scrollTo({top:y,behavior:'smooth'});return y})()"
        beat("scroll: the unit mix", 5.0); F(SCR.replace("SEL", "'table,.mix,.um'")); hold(5.0)
        beat("scroll: plot, floors, car parks", 3.0); F(SCR.replace("SEL", "'.vw'")); hold(3.0)
        stop(sc, t)
        # ---- IV · the map: the same place and what sits around it ---------------------------------------------------------
        slug = pg.url.split("/skyline/")[1].split("?")[0] if "/skyline/" in pg.url else "dubaimarina"
        pg.goto(f"{WORKER}/map?key={key}&film=1&wide=1&d={slug}&focus={prop}&r={int(time.time())}", wait_until="load"); hold(6.0); F("window.__film.settle(8000)"); hold(1.5)
        sc, t = start("map")
        beat("the place on the map: nearest of each kind", 5.0); hold(5.0)
        beat("schools within 3 km", 3.0); F("window.__film.tap('.a[data-k=school]')"); hold(3.0)
        beat("school contact card", 4.6); F("window.__film.tap('#panel .nk')"); hold(1.4); F("window.__film.settle(4000)"); hold(3.2)
        beat("back, beach", 3.4); F("window.__film.tap('#back')"); hold(0.8); F("window.__film.tap('.a[data-k=school]')"); hold(0.3); F("window.__film.tap('.a[data-k=beach]')"); hold(2.3)
        beat("end hold", 1.6); hold(1.6)
        stop(sc, t)
        parts, durs = [], []
        for i, (scx, ta, tb) in enumerate(segs):
            m = os.path.join(out, f"seg_{i}.mp4"); durs.append(scx.segment(ta, tb, m)); parts.append(m)
        print("frames:", [scx.n for scx, _, _ in segs])
        ctx.close(); b.close()
    X = 0.8; total = sum(durs) - X * (len(parts) - 1); mp4 = os.path.join(out, f"FILM_hometab_{int(total)}s_1920x1080.mp4")
    fc = ""; prev = "[0:v]"; off = 0.0
    for i in range(1, len(parts)):
        off += durs[i - 1] - X; lab = "[v]" if i == len(parts) - 1 else f"[x{i}]"
        fc += f"{prev}[{i}:v]xfade=transition=fade:duration={X}:offset={off:.2f}{lab};"; prev = lab
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for m in parts: cmd += ["-i", m]
    subprocess.run(cmd + ["-filter_complex", fc.rstrip(";"), "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", "-an", mp4], check=True)
    with open(os.path.join(out, "SHOTLIST.md"), "w", encoding="utf-8") as f:
        f.write("# Shot list (HOMES tab first, widescreen)\n\n| at | beat | planned hold |\n|---|---|---|\n" + "".join(f"| {t}s | {n} | {h}s |\n" for t, n, h in log))
        f.write(f"\nsegments {[round(d, 1) for d in durs]} s, dissolve {X}s\n")
    print("film:", mp4, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip(), "s")


if __name__ == "__main__":
    main()
