"""Title and end cards for a map film, in the app's own type, cross-faded onto the film.

Cards are rendered from HTML with the same fonts and palette as the app (Fraunces, IBM Plex Mono, #0C1413 ground, #C5A56A gold),
so they look like the app rather than a template. Usage:
  python scripts/film_cards.py <film.mp4> --title "The Valley" --sub "nineteen neighbourhoods, and what sits around them" --out <final.mp4>
"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright  # noqa: E402
W, H = (1920, 1080) if "--wide" in sys.argv else (1080, 1920)


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


HEAD = ('<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;500&display=swap">'
        '<style>html,body{margin:0;width:'+str(W)+'px;height:'+str(H)+'px;background:#0C1413;color:#E8E4D8;font-family:Fraunces,Georgia,serif;overflow:hidden}'
        '.wrap{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 110px;box-sizing:border-box}'
        '.eye{font-family:"IBM Plex Mono",monospace;font-size:26px;letter-spacing:.18em;text-transform:uppercase;color:#8FA39B;margin-bottom:34px}'
        '.brand{font-size:74px;font-weight:600;line-height:1.05;margin-bottom:22px}.brand i{font-style:normal;color:#C5A56A}'
        '.title{font-size:150px;font-weight:600;line-height:.98;letter-spacing:-.01em;margin:26px 0 30px;text-wrap:balance}'
        '.sub{font-family:"IBM Plex Mono",monospace;font-size:30px;line-height:1.5;letter-spacing:.04em;color:#8FA39B;max-width:820px}'
        '.rule{width:120px;height:3px;background:#C5A56A;margin:44px 0 40px;border-radius:2px}'
        '.foot{position:absolute;left:110px;right:110px;bottom:120px;font-family:"IBM Plex Mono",monospace;font-size:24px;letter-spacing:.14em;text-transform:uppercase;color:#5F736C;display:flex;justify-content:space-between}'
        '.glow{position:absolute;right:-260px;top:-260px;width:900px;height:900px;border-radius:50%;background:radial-gradient(closest-side,rgba(197,165,106,.16),rgba(197,165,106,0))}'
        '</style>'+('<style>.wrap{padding:0 160px;max-width:1240px}.title{font-size:132px}.brand{font-size:66px}.sub{font-size:28px;max-width:900px}.foot{left:160px;right:160px;bottom:70px}.eye{margin-bottom:26px}.rule{margin:34px 0 30px}</style>' if W>H else ''))


def title_html(title, sub):
    return (f'<!doctype html><meta charset=utf-8>{HEAD}<div class=glow></div><div class=wrap><div class=eye>Najma &middot; the map</div>'
            f'<div class=title>{title}</div><div class=rule></div><div class=sub>{sub}</div></div>'
            f'<div class=foot><span>every place from a public register</span><span>Dubai</span></div>')


def end_html():
    return (f'<!doctype html><meta charset=utf-8>{HEAD}<div class=glow></div><div class=wrap><div class=brand>Najma <i>&#1606;&#1580;&#1605;&#1577;</i></div>'
            f'<div class=sub>Schools, clinics, hospitals, metro and malls from the registers that license them.<br>Distances measured, never guessed.</div>'
            f'<div class=rule></div><div class=sub style="color:#C5A56A">Message Naj for the plot list.</div></div>'
            f'<div class=foot><span>register-true</span><span>2026</span></div>')


def render(html, png):
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.set_content(html, wait_until="networkidle"); pg.wait_for_timeout(1500)     # fonts
        pg.screenshot(path=png); b.close()


def main():
    film = sys.argv[1]; title = arg("--title", "The Valley"); sub = arg("--sub", "nineteen neighbourhoods, and what sits around them")
    out = arg("--out", os.path.splitext(film)[0] + "_titled.mp4"); tmp = tempfile.mkdtemp()
    t_png, e_png = os.path.join(tmp, "title.png"), os.path.join(tmp, "end.png")
    render(title_html(title, sub), t_png); render(end_html(), e_png)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", film], capture_output=True, text=True).stdout.strip())
    T, E, X = 3.2, 4.5, 0.9                                     # title hold, end hold, cross-fade
    fc = (f"[0:v]loop=loop=-1:size=1:start=0,trim=0:{T},fps=30,format=yuv420p,setsar=1,fade=t=in:st=0:d=0.8[t];"
          f"[1:v]fps=30,format=yuv420p,setsar=1[f];"
          f"[2:v]loop=loop=-1:size=1:start=0,trim=0:{E},fps=30,format=yuv420p,setsar=1,fade=t=out:st={E-1.0:.2f}:d=1.0[e];"
          f"[t][f]xfade=transition=fade:duration={X}:offset={T-X:.2f}[tf];"
          f"[tf][e]xfade=transition=fade:duration={X}:offset={T-X+dur-X:.2f}[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", str(T + 1), "-i", t_png, "-i", film, "-loop", "1", "-t", str(E + 1), "-i", e_png,
                    "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out], check=True)
    print("out:", out, subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip(), "s")
    print("cards:", t_png, e_png)


if __name__ == "__main__":
    main()
