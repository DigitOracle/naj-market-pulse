"""Search-led capture of the map for a community, as stills AND a recording (Kendall, 7 Sep): open the page, type the community's
name, pick it, tap a sub-community card, then tap hospitals / schools / clinics / malls / metro one by one - a 1080x1920 still
at every beat so the film can be pieced together, plus the continuous recording.

Phone layout (390x693 CSS px at 2.77x), page only - the key never enters a frame.
Usage: python scripts/map_capture_stills.py "the valley" [--pick "The Valley"] [--card "Rivana"] [--radius 5] [--out DIR]
"""
import os, subprocess, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
W, H = 1080, 1920


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    query = sys.argv[1]; pick = arg("--pick", query); card = arg("--card", ""); radius = arg("--radius", "5")
    stamp = time.strftime("%Y%m%d_%H%M"); out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture", f"stills_{stamp}"))
    os.makedirs(out, exist_ok=True); key = env_token("READ_KEY"); shots = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 693}, device_scale_factor=2.77, is_mobile=True, has_touch=True,
                            record_video_dir=out, record_video_size={"width": W, "height": H})
        pg = ctx.new_page(); pg.goto(f"{WORKER}/map?key={key}&r={int(time.time())}", wait_until="networkidle"); pg.wait_for_timeout(5000)
        n = [0]
        def shot(name, hold=1600):
            pg.wait_for_timeout(hold); n[0] += 1; f = os.path.join(out, f"{n[0]:02d}_{name}.png"); pg.screenshot(path=f); shots.append({"n": n[0], "beat": name, "file": os.path.basename(f), "status": pg.evaluate("document.getElementById('st').textContent")})
        shot("home")
        # type the name, letter by letter, so the dropdown is seen forming
        pg.click("#q");
        for ch in query:
            pg.type("#q", ch, delay=90)
        shot("search_typed", 1200)
        picked = pg.evaluate("""(p)=>{var it=[...document.querySelectorAll('.qi')];var hit=it.find(x=>x.innerText.toLowerCase().indexOf(p.toLowerCase())>=0&&x.innerText.toLowerCase().indexOf('district')>=0)||it.find(x=>x.innerText.toLowerCase().indexOf(p.toLowerCase())>=0);if(hit){hit.click();return hit.innerText.replace(/\\n/g,' | ')}return null}""", pick)
        shot("district_picked", 2200)
        pg.evaluate("document.getElementById('rail').scrollTo({left:260,behavior:'smooth'})"); shot("sub_community_cards", 1400)
        pg.evaluate("document.getElementById('rail').scrollTo({left:0,behavior:'smooth'})"); pg.wait_for_timeout(600)
        tapped = pg.evaluate("""(c)=>{var cs=[...document.querySelectorAll('.rail .c[data-sub]')];var hit=c?cs.find(x=>x.innerText.toLowerCase().indexOf(c.toLowerCase())>=0):cs[0];if(hit){hit.click();return hit.innerText.replace(/\\n/g,' | ')}return null}""", card)
        shot("sub_community_open", 2200)
        for k in ("hospital", "school", "clinic", "mall", "metro"):
            pg.evaluate(f"(function(){{var a=document.querySelector('.a[data-k=\"{k}\"]');if(a&&!a.classList.contains('on'))a.click()}})()"); shot(f"{k}_in_community", 1500)
        pg.evaluate("document.querySelector('#scope button[data-mode=dist]').click()"); pg.wait_for_timeout(500)
        pg.evaluate(f"(function(){{var r=document.getElementById('rng');r.value={radius};r.dispatchEvent(new Event('input',{{bubbles:true}}))}})()")
        shot(f"by_distance_{radius}km", 1800)
        # every filter with results: open the list, then click through to the first place's card (the show-off beat), then back
        for k in ("school", "hospital", "clinic", "mall", "metro"):
            pg.evaluate(f"(function(){{var a=document.querySelector('.a[data-k=\"{k}\"]');if(a.classList.contains('on')){{a.click()}}a.click()}})()"); shot(f"{k}_list_{radius}km", 1500)
            has = pg.evaluate("!!document.querySelector('#panel .nk')")
            if has:
                pg.evaluate("document.querySelector('#panel .nk').click()"); shot(f"{k}_card", 2600)
                pg.evaluate("var b=document.getElementById('back');b&&b.click()"); pg.wait_for_timeout(600)
        video = pg.video.path(); ctx.close(); b.close()
    mp4 = os.path.join(out, f"sequence_{stamp}.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", mp4], check=False)
    json.dump({"query": query, "pick": pick, "picked": picked, "card": card, "tapped": tapped, "radius": radius, "shots": shots, "mp4": mp4}, open(os.path.join(out, "SEQUENCE.json"), "w"), indent=1)
    print("out:", out); print("picked:", picked, "| tapped:", tapped)
    for s in shots: print(f"  {s['n']:02d} {s['beat']:<24} {s['status'][:60]}")


if __name__ == "__main__":
    main()
