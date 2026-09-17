"""Record the screen side of the Najma demo videos (Kendall, 17 Sep 2026).

Video 01 is a Business Bay client journey: "I want to live in Business Bay" -> "budget 2M, two
bedrooms" -> the filter drill -> Peninsula One -> its client briefing -> "how far is the nearest
school". The beats and the reasoning are in docs/DEMO_VIDEO_01_BUSINESSBAY.md; each one answers a
question the bank already marks `answered`, so if the app stops answering it the capture breaks and
we find out.

A HeyGen avatar is overlaid on the output afterwards, so nothing here draws one. It does keep the
bottom third of the frame clear of anything that matters.

  probe     dump what each page renders -> data/demo/probe_<beat>.txt, so the selectors below stay
            answerable to the app rather than to memory
  capture   record the journey -> data/demo/raw/journey.webm + marks.json, and fetch the fly-through
  cut       raw -> demo01_businessbay_screen.mp4, with the fly-through spliced in at beat 2
  all       capture + cut

ONE CONTINUOUS TAKE. Beats 1, 3, 4, 5 and 7 all happen on /map and depend on each other - the
district has to stay picked for the filter to say "37 here". They are recorded as one take with
`marks.json` recording where each beat ended, and `cut` splits on those marks to splice in beat 2.
Recording them as separate clips would reset the district every time.

THE CURSOR IS DRAWN, NOT REAL. Playwright's recorded video has no mouse pointer in it, so a click
would land with nothing on screen to explain it. `_cursor` injects a dot that follows the real mouse
and reacts to mousedown; every click is preceded by visible travel. Sliders are dragged rather than
set, so the band and its label move the way they would under a hand.

THE KEY. Read from NAJMA_CLIENT_KEY (environment, or HKCU\\Environment - see `key`); never passed on
a command line, never printed. It must be a CLIENT_KEY value: READ_KEY opens ~92 owner paths
including ones that message contacts, delete data and spend model budget, and these videos are
public. `refuse_owner_key` checks before anything records.

Playwright records the viewport only - no address bar, no tab strip, no chrome - so no URL can reach
a frame from here. That is a property of this pipeline, not of the key.

Options: --headed (watch it run), --slow <ms>.
"""
import argparse, json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "demo")
RAW = os.path.join(OUT, "raw")

APP = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
W, H = 1080, 1920
DISTRICT = "Business Bay"
HERO = "Peninsula One"
FLY = "unreal_businessbay_fly"      # /img/videos: "20 s fly-through", keyless under /video/
SPLICE_FLY = False                  # Kendall, 17 Sep: pulled. It is daylight aerial and the rest of
                                    # the video is black-and-champagne; grading got the canal to
                                    # black but the buildings stayed bright and the Burj lake still
                                    # flared cyan. Dropping it buys 7s for the client briefing to
                                    # close on, which is the beat that actually sells. Still fetched
                                    # - it is a good standalone piece and a good opener for the
                                    # DAMAC Hills cinematic.
BUDGET_HI = 14                      # #hhi: 14 reads "from AED 250k to 2.0M" - the brief, exactly
BEDS = 2


# ---------------------------------------------------------------- the key

def key():
    """NAJMA_CLIENT_KEY, from the environment or, failing that, straight out of the registry.

    `setx` writes the user environment to HKCU\\Environment at once, but processes already running
    keep the environment they started with - so a key set after this terminal's parent started is
    invisible to os.environ until something restarts. Reading the registry picks it up immediately
    and keeps the value inside this process.
    """
    k = os.environ.get("NAJMA_CLIENT_KEY", "").strip()
    if not k and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                k = str(winreg.QueryValueEx(h, "NAJMA_CLIENT_KEY")[0]).strip()
        except OSError:
            k = ""
    if not k:
        sys.exit("NAJMA_CLIENT_KEY is not set (checked the environment and HKCU\\Environment).\n"
                 "Set it with:  node scripts/set_client_key.js")
    if len(k) < 12:
        sys.exit("NAJMA_CLIENT_KEY is under 12 characters; the worker ignores those (clientKeysOf).")
    return k


def refuse_owner_key(k):
    """/board is owner-only. If the key opens it, it is READ_KEY and must not go near a video."""
    try:
        with urllib.request.urlopen("%s/board?key=%s" % (APP, urllib.parse.quote(k)), timeout=20) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        return
    if code == 200:
        sys.exit("refusing to run: this key opens /board, so it is READ_KEY. Use a CLIENT_KEY value.")


def url(route):
    return "%s%s%s" % (APP, route, "" if route.startswith(("/r/", "/video/", "/img/"))
                       else ("&" if "?" in route else "?") + "key=" + key())


# ------------------------------------------------------- a cursor you can see

CURSOR_JS = """() => {
  const d = document.createElement('div');
  d.id = '__cur';
  d.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;margin:-11px 0 0 -11px;'
    + 'border-radius:50%;pointer-events:none;background:rgba(197,165,106,.28);'
    + 'border:2px solid rgba(197,165,106,.95);box-shadow:0 0 14px rgba(197,165,106,.55);'
    + 'transition:transform .12s ease;left:-99px;top:-99px';
  document.body.appendChild(d);
  addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => { d.style.transform = 'scale(.55)'; }, true);
  addEventListener('mouseup',   () => { d.style.transform = 'scale(1)'; }, true);
}"""


def glide(pg, x, y, steps=26):
    """Move the pointer the way a hand would, so the drawn cursor has travel to show."""
    pg.mouse.move(x, y, steps=steps)
    pg.wait_for_timeout(140)


def glide_click(pg, locator, pause=420):
    box = locator.bounding_box()
    if not box:
        raise RuntimeError("nothing to click - the element has no box")
    glide(pg, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down(); pg.wait_for_timeout(90); pg.mouse.up()
    pg.wait_for_timeout(pause)


def drag_range(pg, sel, target, hold=260):
    """Drag a range input's thumb to `target`, so the band and its label move under the hand."""
    box = pg.locator(sel).bounding_box()
    lo = float(pg.eval_on_selector(sel, "e => e.min || 0"))
    hi = float(pg.eval_on_selector(sel, "e => e.max || 100"))
    cur = float(pg.eval_on_selector(sel, "e => e.value"))
    y = box["y"] + box["height"] / 2
    at = lambda v: box["x"] + 8 + (box["width"] - 16) * (v - lo) / (hi - lo)
    glide(pg, at(cur), y, steps=14)
    pg.mouse.down()
    for i in range(1, 13):
        pg.mouse.move(at(cur + (target - cur) * i / 12.0), y)
        pg.wait_for_timeout(22)
    pg.mouse.up()
    pg.wait_for_timeout(hold)


def search_pick(pg, text, pause=2200):
    """Type into the district/building searchbox and take the first offer."""
    sb = pg.get_by_role("searchbox").first
    glide_click(pg, sb, pause=160)
    pg.keyboard.press("ControlOrMeta+a")
    pg.keyboard.type(text, delay=85)
    pg.wait_for_timeout(1200)
    pg.get_by_text(text, exact=False).first.click()
    pg.wait_for_timeout(pause)


# ---------------------------------------------------------------- the take

def journey(pg, mark):
    """Beats 1, 3, 4, 5 and 7 - one continuous take on /map."""
    pg.goto(url("/map"), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS)
    pg.wait_for_timeout(900)
    mark("open")

    # BEAT 1 - "I'm thinking about Business Bay"                            Q067
    search_pick(pg, DISTRICT)
    pg.wait_for_timeout(1500)
    mark("beat1")            # the fly-through is spliced in here

    # BEAT 2 - "what are the schools like?"                                 Q028/Q029
    # Asked here, with the district up, rather than after the building: clicking an amenity chip
    # clears the building selection, which would take the panel's "on the twin" link with it.
    try:
        glide_click(pg, pg.get_by_text("SCHOOLS", exact=False).first, pause=900)
    except Exception as e:
        print("   beat 2: could not reach the schools chip (%s)" % str(e).split("\n")[0][:70])
    pg.wait_for_timeout(2400)
    mark("beat2")

    # BEAT 3 - "my budget's two million and I need two bedrooms"            Q074
    # "two million" is a CEILING, so the low handle goes to the floor too - drag only the high one
    # and the filter silently becomes a 1.5M-2.0M band, which quietly drops every match under 1.5M
    # (25 instead of 37) and puts a number on screen that answers a question nobody asked.
    glide_click(pg, pg.locator("#hh"), pause=600)
    drag_range(pg, "#hhi", BUDGET_HI)
    drag_range(pg, "#hlo", 0)
    drag_range(pg, "#hblo", BEDS)
    drag_range(pg, "#hbhi", BEDS)
    pg.wait_for_timeout(1400)
    mark("beat3")

    # BEAT 4 - the count lands                                              Q098
    pg.wait_for_timeout(3000)
    mark("beat4")

    # BEAT 5 - "show me the best one"                                       Q048/Q051
    # collapse the filter first: left open, the building panel slides in over it and the two
    # overlap down the right-hand side
    glide_click(pg, pg.locator("#hh"), pause=600)
    search_pick(pg, HERO, pause=3000)
    pg.wait_for_timeout(2600)
    mark("beat5")

    # BEAT 6 - the twin (Kendall, 17 Sep: "the digital twin is pretty important")     Q038/Q039
    # Go through the building panel's own "on the twin" link (-> /skyline/businessbay), not the TWIN
    # tab in the nav: the nav goes to /skyline?all=1, the whole-of-Dubai view, and the district would
    # have to be picked again. The panel link carries the building across, and clicking it is what a
    # client would actually do. The twin's own searchbox is no use here - the 3D canvas swallows
    # keystrokes, so typing into it times out.
    glide_click(pg, pg.get_by_text("on the twin", exact=False).first, pause=1500)
    pg.wait_for_load_state("networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS)                       # a new document - the drawn cursor went with the old one
    pg.wait_for_timeout(7000)                    # the CityEngine scene streams in
    mark("beat6")


def fetch_flythrough():
    dst = os.path.join(RAW, "flythrough.mp4")
    if os.path.exists(dst) and os.path.getsize(dst) > 100_000:
        return dst
    # the worker turns away a request with no browser User-Agent (403), so send one
    req = urllib.request.Request(url("/video/" + FLY), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Referer": APP + "/map"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        f.write(r.read())
    print("fly-through -> %s (%d bytes)" % (os.path.basename(dst), os.path.getsize(dst)))
    return dst


def capture(headed, slow):
    from playwright.sync_api import sync_playwright
    os.makedirs(RAW, exist_ok=True)
    marks = {}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=not headed, slow_mo=slow)
        ctx = br.new_context(viewport={"width": W, "height": H},
                             record_video_dir=RAW, record_video_size={"width": W, "height": H})
        pg = ctx.new_page()
        t0 = time.monotonic()

        def mark(name):
            marks[name] = round(time.monotonic() - t0, 2)
            print("   %-7s %6.2fs" % (name, marks[name]))

        print("recording the journey:")
        try:
            journey(pg, mark)
        finally:
            ctx.close()                       # the video is only written on close
            src = pg.video.path()
            dst = os.path.join(RAW, "journey.webm")
            if os.path.exists(dst):
                os.remove(dst)
            os.replace(src, dst)
            json.dump(marks, open(os.path.join(RAW, "marks.json"), "w"), indent=1)
            print("journey -> %s" % os.path.basename(dst))
        br.close()
    fetch_flythrough()


# ---------------------------------------------------------------- the cut

def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


SHEET_PDF = os.path.join(ROOT, "data", "sheets", "peninsula_one.pdf")
PAPER = "0x0E1310"          # the app's near-black, so the document sits on the film rather than in a window


def close_clip(seconds_per_page=4.0):
    """The three-pager, page by page - the close. Kendall, 17 Sep: "that's like the gold".

    Built by scripts/build_client_sheet.py, which is the same PDF Naj forwards to a client, so the
    video ends on the actual artefact rather than a picture of one.

    Each page is fitted into the TOP of the frame, not the middle: the avatar takes the bottom third,
    and page 1's bottom is the provenance block - where every figure came from - which is the whole
    argument for the document and must not end up behind her head.
    """
    if not os.path.exists(SHEET_PDF):
        print("NOTE: no client sheet at %s - build it with:" % SHEET_PDF)
        print("      python scripts/build_client_sheet.py --building \"%s\"" % HERO)
        return None
    import fitz
    doc = fitz.open(SHEET_PDF)
    clips = []
    for i, page in enumerate(doc):
        png = os.path.join(RAW, "sheet_p%d.png" % (i + 1))
        page.get_pixmap(dpi=200).save(png)
        clip = os.path.join(RAW, "_close%d.mp4" % (i + 1))
        ff("-loop", "1", "-framerate", "30", "-i", png, "-t", str(seconds_per_page),
           "-vf", "scale=950:1344:flags=lanczos,pad=%d:%d:65:60:%s,format=yuv420p" % (W, H, PAPER),
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", clip)
        clips.append(clip)
    print("close: %d pages x %.1fs" % (len(clips), seconds_per_page))
    return clips


def cut():
    j = os.path.join(RAW, "journey.webm")
    fly = os.path.join(RAW, "flythrough.mp4")
    mk = os.path.join(RAW, "marks.json")
    if not os.path.exists(j):
        sys.exit("no journey recorded yet - run `capture` first")
    marks = json.load(open(mk))
    parts = []
    enc = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an",
           "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)]

    if SPLICE_FLY and os.path.exists(fly):
        split = marks.get("beat1")
        if not split:
            sys.exit("marks.json has no beat1 - the take did not get past the district pick")
        a = os.path.join(RAW, "_a.mp4")
        ff("-i", j, "-t", str(split), *enc, a); parts.append(a)
        b = os.path.join(RAW, "_b.mp4")
        grade = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
                 "eq=brightness=-0.10:contrast=1.16:saturation=0.78,"
                 "colorbalance=rs=0.06:gs=0.01:bs=-0.11:rm=0.05:bm=-0.09" % (W, H, W, H))
        ff("-i", fly, "-t", "7", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-an", "-vf", grade, b); parts.append(b)
        c = os.path.join(RAW, "_c.mp4")
        ff("-i", j, "-ss", str(split), *enc, c); parts.append(c)
    else:
        # Trim to the marks. Playwright starts recording when the context opens and stops when it
        # closes, so the raw take carries a blank head while the app loads and a tail after the last
        # beat - about 17s of nothing between them.
        head = max(0.0, marks.get("open", 0) - 0.6)
        last = max(marks.values()) if marks else None
        # -ss AFTER -i: before it, ffmpeg seeks to the nearest keyframe, and a Playwright webm has
        # them far enough apart to leave ~10s of the blank head still in the cut. After it, the seek
        # is frame-accurate. Slower, and this is re-encoding anyway.
        a = os.path.join(RAW, "_a.mp4")
        span = ["-ss", str(head)] + (["-t", str(last + 1.5 - head)] if last else [])
        ff("-i", j, *span, *enc, a); parts.append(a)

    # THE CLOSE. Kendall, 17 Sep: the three-pager is "the gold" - so it ends the video rather than
    # sitting mid-roll. The app answers the questions; the PDF is what the client walks away with.
    closing = close_clip()
    if closing:
        parts.extend(closing)

    listing = os.path.join(RAW, "concat.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % p.replace("\\", "/"))
    out = os.path.join(OUT, "demo01_businessbay_screen.mp4")
    ff("-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", out)
    secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip() or 0)
    print("wrote %s  (%.1fs)" % (out, secs))


# ---------------------------------------------------------------- probe

def probe():
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": W, "height": H}).new_page()
        for route in ["/map", "/skyline?d=businessbay", "/home"]:
            pg.goto(url(route), wait_until="networkidle", timeout=60_000)
            name = route.strip("/").split("?")[0] or "root"
            with open(os.path.join(OUT, "probe_%s.txt" % name), "w", encoding="utf-8") as f:
                f.write(pg.locator("body").aria_snapshot())
            print("%s -> probe_%s.txt" % (route, name))
        br.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["probe", "capture", "cut", "all"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--slow", type=int, default=0)
    a = ap.parse_args()
    if a.command != "cut":
        refuse_owner_key(key())
    if a.command == "probe":
        probe()
    if a.command in ("capture", "all"):
        capture(a.headed, a.slow)
    if a.command in ("cut", "all"):
        cut()


if __name__ == "__main__":
    main()
