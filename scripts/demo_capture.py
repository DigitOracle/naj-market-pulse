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
HERO_LONLAT = (55.266267, 25.184666)   # from /img/map_prices - used to click the tower on the map
FLY = "unreal_businessbay_fly"      # /img/videos: "20 s fly-through", keyless under /video/
SPLICE_FLY = False                  # Kendall, 17 Sep: pulled. It is daylight aerial and the rest of
                                    # the video is black-and-champagne; grading got the canal to
                                    # black but the buildings stayed bright and the Burj lake still
                                    # flared cyan. Dropping it buys 7s for the client briefing to
                                    # close on, which is the beat that actually sells. Still fetched
                                    # - it is a good standalone piece and a good opener for the
                                    # DAMAC Hills cinematic.
VIDEO = int(os.environ.get("NAJMA_VIDEO", "1"))   # 1 = Business Bay (video 01), 2 = DAMAC Hills, a British family (video 02)
if VIDEO == 2:
    DISTRICT = "DAMAC Hills"; HERO = "LORETO 3 - A"; HERO_LONLAT = None      # no twin here; the block is picked from the list. Loreto replaced Carson 18 Sep: DAMAC still publishes a gallery for it
    BUDGET_HI = 12                  # #hhi: 12 reads "from AED 250k to 1.8M" -> 13 here (1.8M / 13 was the recommendation)
    NATIONALITY = "United Kingdom"; SHARE = "10%+"; REGION = "Europe"
else:
    BUDGET_HI = 14                  # #hhi: 14 reads "from AED 250k to 2.0M" - the brief, exactly
BEDS = 2
TAIL_HOLD = 7.0                     # extra seconds on the LAST page of the sheet, so the sign-off lands
TWIN_TARGET = 9.0                   # seconds the twin beat should PLAY for - see the orbit note in cut()
FPS = 30                            # Playwright records ~25fps and the close clips were built at 30;
                                    # `concat -c copy` across that mismatch writes a container whose
                                    # duration runs well past the last frame (79s for 66s of video).
                                    # Everything is re-encoded to one framerate before concat.


# ---------------------------------------------------------------- the key

def key():
    """NAJMA_CLIENT_KEY, from the environment or, failing that, straight out of the registry.

    `setx` writes the user environment to HKCU\\Environment at once, but processes already running
    keep the environment they started with - so a key set after this terminal's parent started is
    invisible to os.environ until something restarts. Reading the registry picks it up immediately
    and keeps the value inside this process.
    """
    k = os.environ.get("NAJMA_CLIENT_KEY", "").strip()
    if (not k or k.startswith("<") or len(k) < 12) and sys.platform == "win32":   # a stale inherited value must not shadow the registry
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


def rkey():
    """NAJMA_RESIDENTS_KEY - the private residents page. Same registry fallback as key(); same rule:
    never printed, never on a command line. Recovered 18 Sep from the browser history of this machine."""
    k = os.environ.get("NAJMA_RESIDENTS_KEY", "").strip()
    if (not k or k.startswith("<") or len(k) < 24) and sys.platform == "win32":   # inherited placeholder from yesterday's paste
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                k = str(winreg.QueryValueEx(h, "NAJMA_RESIDENTS_KEY")[0]).strip()
        except OSError:
            k = ""
    if not k or k.startswith("<") or len(k) < 24:
        sys.exit("NAJMA_RESIDENTS_KEY is missing or still the placeholder. node scripts/set_residents_key.js")
    return k


def rurl():
    return "%s/residents?rk=%s" % (APP, urllib.parse.quote(rkey()))


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
    # click through Playwright, which re-resolves the position at click time. A raw mouse click at
    # the measured box put "list them" onto the APARTMENT button twice: the panel grew a line between
    # the measurement and the click.
    locator.click(timeout=15_000)
    pg.wait_for_timeout(pause)


def glide_click_scrolled(pg, locator, pause=420):
    """glide_click for things that may sit below a panel's fold: scroll into view first, then travel.
    Playwright's own click auto-scrolls, but bounding_box() does not - it times out on a row that
    is attached and visible but scrolled out of its list. That cost 30s of the first video-02 take."""
    locator.scroll_into_view_if_needed(timeout=15_000)
    pg.wait_for_timeout(400)
    glide_click(pg, locator, pause=pause)


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
    # a drag can land a notch short (1.5M for a target of 1.8M, twice). Read where it landed and
    # finish with the arrow keys - exact, and it still reads as a hand adjusting.
    got = float(pg.eval_on_selector(sel, "e => e.value"))
    for _ in range(8):
        if got == target: break
        pg.locator(sel).press("ArrowRight" if got < target else "ArrowLeft"); pg.wait_for_timeout(120)
        got = float(pg.eval_on_selector(sel, "e => e.value"))
    print("   slider %s -> %s (wanted %s)%s" % (sel, got, target, "" if got == target else "  NOT EXACT"))
    pg.wait_for_timeout(hold)


def orbit(pg, seconds=7.0, dx=360, at=(300, 1200)):
    """Rotate the twin by dragging it, the way a hand would.

    The twin draws into its own canvas with the camera in a closure - there is no maplibregl, Cesium
    or THREE on window, and no object with easeTo/getBearing - so the camera cannot be driven from
    JavaScript. Dragging is the only way in, and it is also what a client does. Left drag rotates
    (checked against right drag; both move, left is the orbit).

    Slow and eased: a constant-speed drag reads as a machine, and the whole point of the beat is
    that a person is turning the building around to look at it.
    """
    x, y = at
    SEGMENTS = 6
    pg.mouse.move(x, y)
    pg.wait_for_timeout(300)
    pg.mouse.down()
    # One mouse.move per segment, letting Playwright interpolate inside it. Moving a pixel at a time
    # from Python is one round trip each, and against this canvas a single move costs well over a
    # second - an 84-step orbit took 149s. Six batched moves take about as long as the 3D needs to
    # redraw anyway.
    for i in range(1, SEGMENTS + 1):
        t = i / SEGMENTS
        eased = t * t * (3 - 2 * t)                  # smoothstep: ease in, ease out
        pg.mouse.move(x + dx * eased, y, steps=10)
    pg.mouse.up()
    pg.wait_for_timeout(1200)


def amenity(pg, k, label):
    """Turn on one amenity layer by its data-k, and check it actually came on.

    Matching these by their visible text does not work. The chip row scrolls horizontally and only
    six of the nine fit, so EV charging - the ninth - sits off the right edge at x=912 in a 1080-wide
    frame. A text match finds it in the DOM and clicks something else; the run reports success and
    the layer never comes on. That is what put a school detail card in the EV beat of the 18 Sep cut.

    So: address the chip by attribute, scroll the row until it is really on screen, click, and then
    assert the chip carries "on" - the click landing is not the same as the layer being lit.
    """
    chip = pg.locator('#am .a[data-k="%s"]' % k)
    try:
        chip.scroll_into_view_if_needed(timeout=10_000)
        pg.wait_for_timeout(700)                 # the row eases; clicking mid-scroll misses
        glide_click(pg, chip, pause=1000)
        on = pg.eval_on_selector('#am .a[data-k="%s"]' % k, "e => e.className.includes('on')")
        print("   %s: %s layer -> %s" % (label, k, "on" if on else "NOT ON - re-run, do not ship"))
    except Exception as e:
        print("   %s: could not reach the %s chip (%s)" % (label, k, str(e)[:60]))


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
    amenity(pg, "school", "beat 2")
    pg.wait_for_timeout(2400)
    mark("beat2")

    # BEAT 2b - "and can I charge a car?"                                   Q015
    # The ninth amenity chip, live since v171-172 (17 Sep). 297 points: 186 from DEWA's Green
    # Charger register, 80 OpenChargeMap, 31 OpenStreetMap - and the contributed rows say so on the
    # row, which is the part worth having on camera. Business Bay reads 22 nearby, 5 in community.
    # The bank had Q015 as `held` until this; it is `answered` now.
    amenity(pg, "ev", "beat 2b")
    pg.wait_for_timeout(3400)                    # the charger list is long - give it a beat to read
    mark("beat2b")

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

    # BEAT 5 - "so which one's the best?"                                   Q096/Q098
    # Reached from the LIST, not the searchbox. Kendall, 17 Sep: the filter should drive a list and
    # the building should be picked out of it - searching by name implies you already knew the
    # answer. "list them ->" (#hlist) sits in the filter footer; it opens the matches, sorted by
    # price, and since 2.0M is the ceiling Peninsula One is at the far end of the list. Scrolling
    # to the top of the budget and finding it there is the whole point of the beat.
    #
    # This needs v171 (commit 19cc3ab, live 17 Sep). Before it, #hlist listed all 1010 city-wide
    # while the header said "37 here", and the two disagreed inside one frame.
    glide_click(pg, pg.locator("#hlist"), pause=1800)
    rows = pg.locator("text=Peninsula One")
    box = pg.locator("#hp").bounding_box()
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] + 420)
    for _ in range(7):                       # scroll the list visibly, even where it nearly fits
        pg.mouse.wheel(0, 320)
        pg.wait_for_timeout(260)
    pg.wait_for_timeout(900)
    try:
        glide_click(pg, rows.last, pause=3200)
    except Exception as e:
        print("   beat 5: could not click the list row (%s)" % str(e).split("\n")[0][:70])
        search_pick(pg, HERO, pause=3000)    # fall back to the searchbox rather than lose the beat
    # The filter panel used to stay open on top of the building card it had just opened, and this
    # collapsed it by hand. Fixed in 5a378ba (17 Sep): clicking a row closes the filter behind it.
    pg.wait_for_timeout(1800)

    # Then click the tower itself on the map. This looks like a flourish and is not: the twin link
    # is the SAME url from either route (/skyline/businessbay, no building parameter), and which
    # building the twin opens on is carried in page state rather than the URL. A list row alone does
    # not set it, so the twin arrives on the district with nothing selected - which is what the last
    # cut did, and it quietly drops the one thing this beat exists to show. Clicking the tower sets
    # it. Checked end to end: the twin comes up with the Peninsula One panel.
    xy = pg.evaluate("([lon,lat]) => { const p = window.__najmap2.project([lon,lat]); return [p.x,p.y]; }",
                     list(HERO_LONLAT))
    glide(pg, xy[0], xy[1])
    pg.mouse.down(); pg.wait_for_timeout(90); pg.mouse.up()
    pg.wait_for_timeout(3000)
    mark("beat5")

    # BEAT 6 - the twin (Kendall, 17 Sep: "the digital twin is pretty important")     Q038/Q039
    # Go through the building panel's own "on the twin" link (-> /skyline/businessbay), not the TWIN
    # tab in the nav: the nav goes to /skyline?all=1, the whole-of-Dubai view, and the district would
    # have to be picked again. The panel link carries the building across, and clicking it is what a
    # client would actually do. The twin's own searchbox is no use here - the 3D canvas swallows
    # keystrokes, so typing into it times out.
    # Go through the panel's own "on the twin" link, which carries the building across. A building
    # reached from the homes list briefly did not carry it while one reached from the searchbox did;
    # fixed in 5a378ba (17 Sep). The fallback below navigates to the same route by hand, but it
    # arrives with nothing selected - Business Bay in general rather than this tower - which is not
    # the beat. If it ever fires, the take is worth re-running rather than shipping.
    try:
        glide_click(pg, pg.get_by_text("on the twin", exact=False).first, pause=1500)
    except Exception:
        print("   beat 6: NO 'on the twin' LINK - falling back, and the twin will not show the "
              "building. Re-run rather than ship this take.")
        pg.goto(url("/skyline/businessbay"), wait_until="domcontentloaded", timeout=90_000)
    pg.wait_for_load_state("networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS)                       # a new document - the drawn cursor went with the old one
    # Wait for the scene rather than for a number: networkidle does not mean the GLB has streamed in,
    # and mesh matching cannot start until it has.
    try:
        pg.wait_for_function("() => document.querySelectorAll('#rail .c').length > 1", timeout=60_000)
    except Exception:
        pass
    pg.wait_for_timeout(6000)

    # Open the building's card on the twin by clicking its own rail card. This is what gives the beat
    # its point: Peninsula One with 525 units, the DLD unit mix by type with levels and rents, 36
    # floors, 558 car parks - and the tower ringed in gold in the 3D. Arriving without it shows
    # Business Bay in general, which is not what this beat is for.
    #
    # It writes #panel, the chrome's bottom sheet, NOT #ppanel - those are different panels built by
    # different functions, and checking the wrong one is how this was nearly cut as broken.
    try:
        idx = pg.evaluate("""() => Array.from(document.querySelectorAll('#rail .c'))
            .findIndex(c => /%s/i.test(c.textContent || ''))""" % HERO)
        if idx >= 0:
            pg.locator("#rail .c").nth(idx).click()
            pg.wait_for_timeout(2500)            # easeTo runs 700ms
            got = pg.evaluate("""() => { const e=document.getElementById('panel');
                return !!e && e.className.includes('on') && e.childElementCount > 0; }""")
            print("   beat 6: building card on the twin -> %s" % ("open" if got else "NOT OPEN"))
        else:
            print("   beat 6: %s is not in the twin's rail" % HERO)
    except Exception as e:
        print("   beat 6: could not open the building card (%s)" % str(e).split("\n")[0][:70])

    orbit(pg)                                    # turn it, or it could be a photograph
    mark("beat6")


def journey2(pg, mark):
    """Video 02 - DAMAC Hills, a British family: "stores, schools and people that remind me of home".

    Beat order is deliberate. Schools and shops answer the client first; the budget shortlists;
    Carson is picked from the list; and only then does the residents page answer "and who lives
    here?" for the community already on the table. The residents page says on its own face that it
    is "not for recommending homes", and section 11 keeps nationality off the list of things a
    client filters by to choose where to live - so the video shows it as context about a community,
    never as the thing that chose it. Kendall's 17 Sep decision is what lets it appear on camera at
    all; this order is what keeps the screen and the storyline from contradicting each other.
    """
    pg.goto(url("/map"), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(900); mark("open")

    # BEAT 1 - "I'm thinking about DAMAC Hills"                                Q067
    search_pick(pg, DISTRICT); pg.wait_for_timeout(1500); mark("b1_district")

    # BEAT 2 - "are there British schools?" -> the list, curriculum and KHDA rating on every row   Q028/Q029
    amenity(pg, "school", "beat 2"); pg.wait_for_timeout(2600); mark("b2_schools")

    # BEAT 3 - tap Ranches Primary -> phone, email, website, directions, WhatsApp, QR. Everything clickable.
    try:
        glide_click(pg, pg.get_by_text("Ranches Primary", exact=False).first, pause=1200)
        for label in ("PHONE", "EMAIL", "WEBSITE", "SCAN"):          # the cursor visits each line
            try: glide(pg, *_centre(pg.get_by_text(label, exact=False).first)); pg.wait_for_timeout(500)
            except Exception: pass
        print("   beat 3: school card -> %s" % ("open" if pg.get_by_text("SCAN TO EMAIL", exact=False).count() else "NOT OPEN - re-run"))
    except Exception as e:
        print("   beat 3: could not open the school card (%s)" % str(e)[:60])
    pg.wait_for_timeout(1800); mark("b3_card")

    # BEAT 4 - "is there a Spinneys?" -> 804 m, 924 m                          Q001
    amenity(pg, "supermarket", "beat 4"); pg.wait_for_timeout(2600); mark("b4_shops")

    # BEAT 5 - "two bedrooms, up to one point eight million" -> 13 here         Q074/Q098
    glide_click(pg, pg.locator("#hh"), pause=600)
    # floor first, then the ceiling. The two thumbs share one track and #hhi sits on top: once #hhi
    # is at 12 the #hlo thumb at 10 is seven pixels away, and the second drag grabs #hhi instead and
    # pulls it to 0 (takes 3-6 all read "from AED 250k to ..." with the ceiling gone). With #hhi still
    # at 30 the floor drag has the track to itself.
    drag_range(pg, "#hlo", 0); drag_range(pg, "#hhi", BUDGET_HI); drag_range(pg, "#hblo", BEDS); drag_range(pg, "#hbhi", BEDS)
    pg.wait_for_timeout(1400); mark("b5_filter"); pg.wait_for_timeout(2600); mark("b5_count")

    # BEAT 6 - "which one?" -> list them, scroll, Carson                        Q096/Q051
    glide_click(pg, pg.locator("#hlist"), pause=1800)
    box = pg.locator("#hp").bounding_box(); pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] + 420)
    for _ in range(5): pg.mouse.wheel(0, 320); pg.wait_for_timeout(260)
    pg.wait_for_timeout(800)
    # the list row, not the rail chip: "Damac Hills - Carson" also sits in the sub-community strip at
    # the top and text= matches it. The row is the match inside the right-hand panel, below the filter.
    row = None
    for i in range(pg.locator("text=%s" % HERO).count()):
        b = pg.locator("text=%s" % HERO).nth(i).bounding_box()
        if b and b["x"] > 680 and b["y"] > 360: row = pg.locator("text=%s" % HERO).nth(i); break
    try:
        if row is None: raise RuntimeError("no list row for %s in the panel" % HERO)
        glide_click(pg, row, pause=3200)
    except Exception as e: print("   beat 6: could not click the list row (%s)" % str(e)[:60]); search_pick(pg, HERO, pause=3000)
    pg.wait_for_timeout(2400)
    card = pg.evaluate("""() => [...document.querySelectorAll('*')].some(e => e.children.length && e.getBoundingClientRect().x > 600 && /%s/i.test(e.innerText||'') && /units/i.test(e.innerText||'') && /floors|car park|register/i.test(e.innerText||''))""" % HERO)
    print("   beat 6: %s card -> %s" % (HERO, "open" if card else "NOT OPEN - re-run, do not ship"))
    mark("b6_carson")

    # BEAT 7 - "and who lives here?" -> the residents page: United Kingdom, 10%+, DAMAC Hills, Europe > UK   Q040
    pg.goto(rurl(), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(2500)
    if pg.get_by_role("button", name="India", exact=True).get_attribute("aria-pressed") == "true":
        glide_click(pg, pg.get_by_role("button", name="India", exact=True), pause=700)     # the default chip; off, so only the UK is lit
    glide_click(pg, pg.get_by_role("button", name=NATIONALITY, exact=True), pause=1400)
    glide_click(pg, pg.get_by_role("button", name=SHARE, exact=True), pause=2200)
    pg.wait_for_timeout(1200); mark("b7_map")
    # the list row reads "DAMAC HILLS" in capitals; exact match keeps it off "DAMAC HILLS 2" and the map labels
    glide_click_scrolled(pg, pg.get_by_text(DISTRICT.upper(), exact=True).first, pause=2200)
    try:
        # the region rows are div.bar.reg whose text node reads "▸Europe" - caret glued on, so an
        # exact text match never finds it; match the row by contained text instead
        region = pg.locator("div.bar.reg", has_text=REGION).first
        glide_click_scrolled(pg, region, pause=1800)
        ok = pg.get_by_text(NATIONALITY, exact=True).count() > 1     # the chip AND the country row
        print("   beat 7: DAMAC Hills card, %s expanded -> %s" % (REGION, "countries shown" if ok else "NOT EXPANDED - re-run"))
    except Exception as e:
        print("   beat 7: could not expand %s (%s)" % (REGION, str(e)[:60]))
    pg.wait_for_timeout(3500); mark("b7_people")


def _centre(loc):
    b = loc.bounding_box(); return (b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)


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
            (journey2 if VIDEO == 2 else journey)(pg, mark)
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


SHEET_PDF = os.path.join(ROOT, "data", "sheets", "damac_hills_loreto.pdf" if VIDEO == 2 else "peninsula_one.pdf")
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
    last = doc.page_count - 1
    for i, page in enumerate(doc):
        png = os.path.join(RAW, "sheet_p%d.png" % (i + 1))
        page.get_pixmap(dpi=200).save(png)
        # The final page holds for TAIL_HOLD longer so the sign-off - "Welcome to Azimuth. Complexity
        # into clarity." - has somewhere to land. Without it the line runs past the end of the footage
        # and HeyGen either pads or slows the whole video to fit, and slowing it makes the app look
        # sluggish. Holding page three is also the right image to end on: it is what she is welcoming
        # them to.
        secs = seconds_per_page + (TAIL_HOLD if i == last else 0)
        clip = os.path.join(RAW, "_close%d.mp4" % (i + 1))
        ff("-loop", "1", "-framerate", str(FPS), "-i", png, "-t", str(secs),
           "-vf", "scale=950:1344:flags=lanczos,pad=%d:%d:65:60:%s,format=yuv420p" % (W, H, PAPER),
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", "-r", str(FPS), clip)
        clips.append(clip)
    print("close: %d pages x %.1fs, last held +%.1fs for the sign-off"
          % (len(clips), seconds_per_page, TAIL_HOLD))
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
           "-r", str(FPS),        # every part at one framerate - see FPS
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
        b5, b6 = marks.get("beat5"), marks.get("beat6")
        if b5 and b6 and (b6 - b5) > TWIN_TARGET * 2:
            # THE ORBIT RUNS IN SLOW MOTION AND HAS TO BE SPED UP. Dragging the twin's canvas costs
            # over a second per mouse move however the moves are batched - the 3D redraws and
            # Playwright waits for it - so a 7-second orbit records as about 105. The frames are all
            # there and the recording is a real 30fps throughout; only the clock is wrong. So the
            # twin beat is cut out and played back at speed, which is what the orbit was meant to
            # look like. Everything before it stays at 1x.
            a1 = os.path.join(RAW, "_a1.mp4")
            ff("-i", j, "-ss", str(head), "-t", str(b5 - head), *enc, a1); parts.append(a1)
            factor = (b6 - b5) / TWIN_TARGET
            a2 = os.path.join(RAW, "_a2.mp4")
            # -ss and -t go BEFORE -i here - the opposite of the trim above, and the opposite is
            # load-bearing. An input seek rebases timestamps to zero, which is what setpts needs;
            # with an output seek they still start at ~41s, dividing them puts the segment past the
            # window -t keeps, and ffmpeg writes a 261-byte file with no frames. Frame-accuracy does
            # not matter for this beat the way it does for the head trim, so the keyframe-aligned
            # input seek costs nothing. -fps_mode cfr keeps the timebase sane through the concat.
            ff("-ss", str(b5), "-t", str(b6 + 1.0 - b5), "-i", j,
               "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an",
               "-fps_mode", "cfr", "-r", str(FPS),
               "-vf", "setpts=PTS/%.3f,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d"
                      % (factor, W, H, W, H), a2)
            parts.append(a2)
            print("twin beat: %.1fs recorded -> %.1fs at %.1fx" % (b6 - b5, TWIN_TARGET, factor))
        else:
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
    out = os.path.join(OUT, "demo02_damachills_screen.mp4" if VIDEO == 2 else "demo01_businessbay_screen.mp4")
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
