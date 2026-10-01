"""THE BRIEF video: a client's WhatsApp ask -> the brief -> the shortlist -> the Compare 10 PDF -> the ten in blocks.

Narrative approved by Kendall, 1 Oct 2026 (docs/BRIEF_VIDEO_SHOOTING_SCRIPT.md), with his three additions: scroll down
the results list, scroll through the PDF, show the buildings in blocks. Filmed on v283 (Rings: element ids below) on
the CLIENT key - never the read key.

Three parts, joined:
  A  the app, recorded live in its phone layout (540x960 at device scale 2 -> a sharp 1080x1920): START, the six-step
     brief, the results (slow scroll to the register note), What to send -> Compare 10, until the PDF is ready
  P  the downloaded PDF itself, page by page as one slow vertical scroll (rendered with PyMuPDF), not a viewer
  B  the app again: See them in blocks - Business Bay, the ten in gold, a slow orbit, held for the sign-off

    python scripts/brief_capture.py
Writes data/media/brief/brief_9x16.mp4 and data/media/brief/compare10.pdf.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NAJMA_VIDEO", "10")
import demo_capture as D                                   # noqa: E402  url() on the CLIENT key, CURSOR_JS, glide
from playwright.sync_api import sync_playwright            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "media", "brief")
W, H, FPS = 1080, 1920, 25
PAPER = "0x0C1413"


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)


def glide_click(pg, loc, pause=700):
    loc.scroll_into_view_if_needed(timeout=10_000)
    b = loc.bounding_box()
    if b:
        pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=22)
        pg.wait_for_timeout(180)
    loc.click(timeout=15_000)
    pg.wait_for_timeout(pause)


def type_slow(pg, loc, text, pause=500):
    glide_click(pg, loc, 250)
    loc.fill("")
    loc.type(text, delay=110)
    pg.wait_for_timeout(pause)


def part_a(pg, marks, t0):
    mark = lambda k: marks.__setitem__(k, round(time.monotonic() - t0, 2))
    pg.goto(D.url("/start"), wait_until="networkidle", timeout=90_000)
    pg.evaluate(D.CURSOR_JS)
    pg.wait_for_timeout(1200)
    mark("open")
    pg.wait_for_timeout(2200)                                           # START, held
    glide_click(pg, pg.locator("a.btn.rent"), 0)
    pg.wait_for_load_state("networkidle")
    pg.evaluate(D.CURSOR_JS)
    pg.wait_for_timeout(1200)
    glide_click(pg, pg.locator("#ftype").get_by_text("Apartment", exact=True), 500)
    glide_click(pg, pg.locator('#fbeds [data-v="studio"]'), 700)
    glide_click(pg, pg.locator("#fnextbd:visible, #fnextb:visible").first, 900)
    type_slow(pg, pg.locator("#fmin"), "50k", 300)
    type_slow(pg, pg.locator("#fmax"), "70k", 700)
    glide_click(pg, pg.locator("#s-budget button:visible", has_text="NEXT").first, 900)
    glide_click(pg, pg.locator("#s-furn").get_by_text("Either", exact=True).first, 500)
    nb = pg.locator("#s-furn button:visible", has_text="NEXT")
    if nb.count():
        glide_click(pg, nb.first, 900)
    type_slow(pg, pg.locator("#fdq"), "bus", 900)
    glide_click(pg, pg.locator("#s-where").get_by_text("Business Bay", exact=True).first, 700)
    glide_click(pg, pg.locator("#fnextw"), 900)
    glide_click(pg, pg.locator('.wr[data-k="metro"] button[data-l="must"]'), 900)
    glide_click(pg, pg.locator("#fgo"), 0)
    pg.wait_for_selector("#bres .bcard, #bres > *:nth-child(3)", timeout=60_000)
    pg.wait_for_timeout(2500)
    mark("results")
    # the slow scroll down the list, to the register note at its foot
    pg.mouse.move(W // 4, H // 4)
    for _ in range(60):
        pg.mouse.wheel(0, 38)
        pg.wait_for_timeout(110)
    pg.wait_for_timeout(1500)
    mark("results_end")
    glide_click(pg, pg.locator("#o-c10"), 0)
    ready = pg.locator("#jobs a", has_text=re.compile("Open the PDF", re.I))
    ready.first.wait_for(timeout=120_000)
    pg.wait_for_timeout(1500)
    mark("pdf_ready")
    href = ready.first.get_attribute("href")
    blocks = pg.locator("#o-blocks")
    bhref = blocks.get_attribute("href") if blocks.count() else None
    return href, bhref


def part_b(pg, marks, t0, bhref):
    mark = lambda k: marks.__setitem__(k, round(time.monotonic() - t0, 2))
    mark("blocks_start")
    if bhref:
        pg.goto(bhref if bhref.startswith("http") else D.APP.rstrip("/") + bhref, wait_until="load", timeout=90_000)
    else:
        glide_click(pg, pg.locator("#o-blocks"), 0)
    pg.wait_for_function("() => window.__blocksReady === true", timeout=90_000)
    pg.evaluate(D.CURSOR_JS)
    pg.wait_for_timeout(2500)
    mark("blocks_in")
    pg.evaluate("""() => { const m = window.__blocksMap; m.easeTo({bearing: m.getBearing() + 70, pitch: Math.min(65, m.getPitch() + 10),
                                                          duration: 9000, easing: t => t * (2 - t)}); }""")
    pg.wait_for_timeout(9500)
    mark("end")


def pdf_scroll(pdf, secs_per_page=6.5):
    """The PDF, page by page, read across: each landscape A4 page shown tall enough to read (~1,400 px) and panned
    left to right, so the phone frame travels over the comparison table and then the map."""
    import fitz
    doc = fitz.open(pdf)
    clips = []
    for i, page in enumerate(doc):
        png = os.path.join(OUT, "_pdf_p%d.png" % (i + 1))
        zoom = 1400 / page.rect.height
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(png)
        import PIL.Image
        pw, ph = PIL.Image.open(png).size
        span = max(0, pw - W)
        hold = 1.0
        x = "if(lt(t,{h}),0,if(gt(t,{e}),{s},{s}*(1-cos(PI*(t-{h})/({e}-{h})))/2))".format(h=hold, e=secs_per_page - hold, s=span)
        clip = os.path.join(OUT, "_pdf_%d.mp4" % (i + 1))
        ff("-loop", "1", "-framerate", str(FPS), "-i", png, "-t", str(secs_per_page),
           "-vf", "pad=iw:%d:0:(oh-ih)/2:%s,crop=%d:%d:'%s':0,format=yuv420p" % (H, PAPER, W, H, x),
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", "-r", str(FPS), clip)
        clips.append(clip)
    print("pdf: %d pages, %.1f s each, panned across" % (len(clips), secs_per_page))
    return clips


def main():
    os.makedirs(OUT, exist_ok=True)
    marks = {}
    raw = os.path.join(OUT, "take.webm")
    if "--cut-only" in sys.argv:                               # rebuild from the kept take, PDF and marks
        marks = json.load(open(os.path.join(OUT, "marks.json")))
        return assemble(raw, marks)
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--force-device-scale-factor=2", "--window-size=%d,%d" % (W // 2, H // 2),
                                     "--use-angle=d3d11", "--ignore-gpu-blocklist"])
        ctx = br.new_context(no_viewport=True, record_video_dir=OUT, record_video_size={"width": W, "height": H},
                             accept_downloads=True)
        pg = ctx.new_page()
        t0 = time.monotonic()
        try:
            href, bhref = part_a(pg, marks, t0)
            pdf = os.path.join(OUT, "compare10.pdf")
            if href.startswith("blob:") or href.startswith("data:"):
                # the PDF is built in the page and offered as a blob: read its bytes from inside the page
                import base64
                b64 = pg.evaluate("""async (u) => { const b = await (await fetch(u)).arrayBuffer(); let s = "";
                    const a = new Uint8Array(b); for (let i = 0; i < a.length; i += 32768) s += String.fromCharCode(...a.subarray(i, i + 32768));
                    return btoa(s); }""", href)
                body = base64.b64decode(b64)
            else:
                body = ctx.request.get(href if href.startswith("http") else D.APP.rstrip("/") + href, timeout=120_000).body()
            open(pdf, "wb").write(body)
            print("pdf saved: %d KB" % (len(body) // 1024))
            part_b(pg, marks, t0, bhref)
        finally:
            ctx.close()
            raw = os.path.join(OUT, "take.webm")
            if os.path.exists(raw):
                os.remove(raw)
            os.replace(pg.video.path(), raw)
            json.dump(marks, open(os.path.join(OUT, "marks.json"), "w"), indent=1)
            print("marks:", marks)
        br.close()
    assemble(raw, marks)


def assemble(raw, marks):
    enc = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", "-r", str(FPS),
           "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)]
    a = os.path.join(OUT, "_a.mp4")
    ff("-i", raw, "-ss", str(max(0, marks["open"] - 0.3)), "-t", str(marks["pdf_ready"] - marks["open"] + 0.3), *enc, a)
    pdfclips = pdf_scroll(os.path.join(OUT, "compare10.pdf"))
    b = os.path.join(OUT, "_b.mp4")
    ff("-i", raw, "-ss", str(marks["blocks_in"] - 0.5), "-t", str(marks["end"] - marks["blocks_in"] + 0.5), *enc, b)
    last = os.path.join(OUT, "_last.png")
    ff("-sseof", "-0.2", "-i", b, "-frames:v", "1", "-update", "1", last)
    tail = os.path.join(OUT, "_tail.mp4")
    ff("-loop", "1", "-framerate", str(FPS), "-i", last, "-t", "6", "-vf", "format=yuv420p",
       "-c:v", "libx264", "-crf", "18", "-an", "-r", str(FPS), tail)
    listing = os.path.join(OUT, "_concat.txt")
    open(listing, "w").write("".join("file '%s'\n" % x.replace("\\", "/") for x in [a] + pdfclips + [b, tail]))
    out = os.path.join(OUT, "brief_9x16.mp4")
    ff("-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", out)
    secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                                capture_output=True, text=True).stdout.strip())
    print("wrote %s (%.1f s)" % (out, secs))


if __name__ == "__main__":
    main()
