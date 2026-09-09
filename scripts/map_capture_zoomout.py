"""Context shot for a community: a wide still of Dubai with the community's neighbourhoods marked, and a short fly-in clip from the
whole city to the community (Kendall, 7 Sep: "a zoomed-out version, clear, to give context"). Phone layout, page only.

Usage: python scripts/map_capture_zoomout.py <district slug> [--from "lon,lat,zoom"] [--seconds 7] [--out DIR]
"""
import os, subprocess, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import env_token, WORKER  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
W, H = 1080, 1920


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    slug = sys.argv[1]; frm = [float(x) for x in arg("--from", "55.30,25.12,9.6").split(",")]; secs = float(arg("--seconds", "7"))
    out = arg("--out", os.path.join(os.path.expanduser("~"), "Downloads", "map_capture", f"zoomout_{slug}_{time.strftime('%Y%m%d_%H%M')}")); os.makedirs(out, exist_ok=True)
    key = env_token("READ_KEY")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 693}, device_scale_factor=2.77, is_mobile=True, has_touch=True,
                            record_video_dir=out, record_video_size={"width": W, "height": H})
        pg = ctx.new_page(); pg.goto(f"{WORKER}/map?key={key}&d={slug}&r={int(time.time())}" + ("&clean=1" if "--clean" in sys.argv else ""), wait_until="load"); pg.wait_for_timeout(9000)
        # wide: the whole city, the community's bubbles visible; the card row and panel out of the way
        pg.evaluate("(function(){var p=document.getElementById('panel');if(p)p.classList.remove('on')})()")
        pg.evaluate(f"window.__najmap2.jumpTo({{center:[{frm[0]},{frm[1]}],zoom:{frm[2]}}})"); pg.wait_for_timeout(3500)
        pg.screenshot(path=os.path.join(out, "00_wide.png"))
        # the fly-in, recorded
        to = [float(x) for x in arg("--to", "").split(",")] if "--to" in sys.argv else None
        if to: pg.evaluate("window.__najmap2.easeTo({center:[%f,%f],zoom:%f,duration:%d})" % (to[0], to[1], to[2], int(secs * 1000)))
        else: pg.evaluate("(function(){var D=window.__najmap2;fetch('/img/districts_geo').then(r=>r.json()).then(function(j){var d=j.districts.filter(function(x){return x.slug==='%s'})[0];D.fitBounds([[d.bbox[0],d.bbox[1]],[d.bbox[2],d.bbox[3]]],{padding:{top:150,bottom:120,left:40,right:40},duration:%d})})})()" % (slug, int(secs * 1000)))
        pg.wait_for_timeout(int(secs * 1000) + 2500)
        pg.screenshot(path=os.path.join(out, "01_arrived.png"))
        video = pg.video.path(); ctx.close(); b.close()
    mp4 = os.path.join(out, f"{slug}_flyin.mp4")
    # keep only the fly-in: drop the load time (first ~9.5 s of the recording) and trim to the flight plus a settle
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "9.5", "-i", video, "-t", str(secs + 2.5), "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", "-an", mp4], check=False)
    print("out:", out); print("fly-in:", mp4, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip(), "s")


if __name__ == "__main__":
    main()
