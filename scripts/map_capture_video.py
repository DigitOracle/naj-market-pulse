"""Record a scripted drive-through of the map for a community, as a portrait video (the second half of a property film).

Playwright + Chromium, 1080x1920, records the page only - no address bar, so the key never reaches a frame. The sequence:
district opens -> its sub-community cards -> a sub-community is tapped -> scope switches to 'by distance' and the radius grows ->
schools / hospitals / clinics / malls / metro cards light up one by one -> the nearest school opens as a contact card with its QR.
Every beat pauses long enough to read. Output: <out>/<slug>_map_<stamp>.webm and an H.264 .mp4 (ffmpeg), plus a frame log.

Usage: python scripts/map_capture_video.py <district slug> [--focus "Sub-community"] [--radius 5] [--out DIR]
"""
import os, subprocess, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

W, H = 1080, 1920


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    slug = [a for a in sys.argv[1:] if not a.startswith("--") and a != arg("--focus", "") and a != arg("--radius", "") and a != arg("--out", "")][0]
    focus = arg("--focus", ""); radius = arg("--radius", "5"); out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture"))
    os.makedirs(out, exist_ok=True)
    key = env_token("READ_KEY")
    url = f"{WORKER}/map?key={key}&d={slug}" + (f"&focus={focus}" if focus else "")
    stamp = time.strftime("%Y%m%d_%H%M"); log = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        # a phone's layout, rendered at 1080x1920: 390x693 CSS px at 2.77x (the recorder scales the frame to the record size)
        ctx = b.new_context(viewport={"width": 390, "height": 693}, device_scale_factor=2.77, is_mobile=True, has_touch=True,
                            record_video_dir=out, record_video_size={"width": W, "height": H})
        pg = ctx.new_page(); pg.goto(url + "&r=" + str(int(time.time())), wait_until="networkidle"); pg.wait_for_timeout(5000)
        def beat(name, ms=2200):
            pg.wait_for_timeout(ms); log.append({"t": round(time.time(), 1), "beat": name, "status": pg.evaluate("document.getElementById('st').textContent")})
        beat("district open", 2500)
        # sub-community cards scroll slowly, then one is tapped
        for x in (260, 520, 780, 1040):
            pg.evaluate(f"document.getElementById('rail').scrollTo({{left:{x},behavior:'smooth'}})"); pg.wait_for_timeout(1100)
        beat("sub-communities", 600)
        pg.evaluate("document.getElementById('rail').scrollTo({left:0,behavior:'smooth'})"); pg.wait_for_timeout(900)
        if focus:
            beat("focused place", 2000)
        else:
            pg.evaluate("var c=document.querySelectorAll('.rail .c[data-sub]')[0];c&&c.click()"); beat("sub-community tapped", 2400)
        # scope: by distance, radius grows
        pg.evaluate("document.querySelector('#scope button[data-mode=dist]').click()"); beat("by distance", 1400)
        for v in ("1", "2", "3", radius):
            pg.evaluate(f"(function(){{var r=document.getElementById('rng');r.value={v};r.dispatchEvent(new Event('input',{{bubbles:true}}))}})()"); pg.wait_for_timeout(700)
        beat(f"radius {radius} km", 1200)
        for k in ("school", "hospital", "clinic", "mall", "metro"):
            pg.evaluate(f"(function(){{var a=document.querySelector('.a[data-k=\"{k}\"]');if(a&&!a.classList.contains('on'))a.click()}})()"); beat(k, 1900)
        # the nearest school as a contact card
        pg.evaluate("(function(){var a=document.querySelector('.a[data-k=\"school\"]');a.click();a.click()})()"); pg.wait_for_timeout(900)
        pg.evaluate("var r=document.querySelector('#panel .nk');r&&r.click()"); beat("contact card", 3200)
        pg.evaluate("document.getElementById('px')&&document.getElementById('px').click()"); beat("close", 1200)
        video = pg.video.path(); ctx.close(); b.close()
    mp4 = os.path.join(out, f"{slug}_map_{stamp}.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", mp4], check=False)
    json.dump({"url_district": slug, "focus": focus, "radius": radius, "beats": log, "webm": video, "mp4": mp4}, open(os.path.join(out, f"{slug}_map_{stamp}.json"), "w"), indent=1)
    print("video:", mp4, os.path.getsize(mp4) // 1024 if os.path.exists(mp4) else "missing", "KB | beats", len(log))


if __name__ == "__main__":
    main()
