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
import argparse, contextlib, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

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
elif VIDEO == 3:
    # video 03 - "I've heard Emaar and Sobha are good developers": COMPARE two developers on two-beds,
    # then VERSUS - "why Dubai and not London / New York / Monaco" - then the two-bed plan she asked for.
    # Starts on a developer, not the map or the twin (Kendall, 18 Sep).
    DEV_A, DEV_B = "Emaar", "Sobha"; CITIES = ["London", "New York", "Monaco"]; BUDGET_TILE = "2m"
    PLAN_PROJECT, PLAN_TYPE = "Marina Cove", "2 BED"; PLAN_PROJECT_PARAM = "Marina%20Cove%20at%20Dubai%20Marina"; BUDGET_HI = 14
elif VIDEO == 4:
    # video 03, second concept (Kendall picked B, 18 Sep): "what's hot, and why?" - starts from the market,
    # not a client. Few figures spoken (Kendall: "too many figures"); the screens carry the numbers.
    HOT_AREA, HOT_SLUG = "Madinat Al Mataar", "madinatalmataar"; ZOOM_BUILDING = "Terra Woods"; SECOND_BUILDING = "Terra Gardens"; BUDGET_HI = 14
elif VIDEO == 5:
    # video 04 - "what's actually left, and on which floor?": the building page, filmed in the page's own phone
    # layout. Kendall's 20 Sep walkthrough was a landscape screen recording; this is the same page as a native 9:16.
    # The page is on the preview build, not production yet (production answers 401 to the client key), so the take
    # reads the preview unless AZIMUTH_URL says otherwise.
    BLD_ROUTE = "/building/businessbay/650"; VIEW_CHIP = os.environ.get("NAJMA_VIEW_CHIP", "SW"); BUDGET_HI = 14
    APP = os.environ.get("AZIMUTH_URL", "https://60715ca6-azimuth-2.digitalchemy.workers.dev")
elif VIDEO == 6:
    # video 05 - "what will I actually see from my window, and could anything block it?" (Q048, Q049, Q054): the twin's
    # building panel gives the view from each of four sides - the landmarks it sees, or the building that blocks it - and each
    # side opens the real view: live photoreal imagery from that facade at two-thirds of the tower's height. ONE River Point
    # (anchor 589) was picked from a scan of 124 named towers on 21 Sep: N Dubai Canal and Burj Khalifa, W Burj Al Arab and
    # Palm Jumeirah, E blocked by One by Binghatti.
    VIEW_ANCHOR = os.environ.get("NAJMA_VIEW_ANCHOR", "589"); VIEW_TOUR = ["N", "W", "E"]
    VIEW_GOOD, VIEW_BLOCKED, VIEW_LAST = "N", "E", "W"; VIEW_PULLBACK = int(os.environ.get("NAJMA_VIEW_PULLBACK", "5")); BUDGET_HI = 14
elif VIDEO == 7:
    # video 06 - "could someone build in front of me?" (Q049, Q048, Q054), the first episode cut to the Ask Najj template:
    # 11 shots, the turn at 55%, the payoff on the occlusion reveal. ONE River Point, blocked east by One by Binghatti.
    VIEW_ANCHOR = os.environ.get("NAJMA_VIEW_ANCHOR", "589"); BLD_ROUTE_7 = "/building/businessbay/73"; FLOOR_A, FLOOR_B = 41, 74; BUDGET_HI = 14
    APP = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
elif VIDEO == 8:
    # video 07 - "is there anything left in it?" AL HABTOOR TOWER, Business Bay, footprint 574.
    #
    # One surface, start to finish: /building/businessbay/574. Kendall, 21 Sep: "I need one link, one place to go."
    #
    # THE SUBJECT CHANGED TWICE AND BOTH REASONS ARE WORTH KEEPING.
    #
    # It was written for MARINA PINNACLE around DEWA move-ins - "when did this tower fill up", 769 meters connected,
    # 610 of them in 2025. That question is answerable and no Dubai portal answers it, but Business Bay publishes only
    # 77 DEWA buildings and Al Habtoor is not one, so the beat does not exist here.
    #
    # Then the question itself failed. "Is there anything left" looked answerable on Marina Pinnacle - the page read
    # **8 LEFT OF 772** - and that number was an artefact: `Math.max(0, units - sales)` against 2,278 sales on 772
    # homes, because homes RESELL. 304 buildings citywide read as sold out and were not. Fixed in v246.
    #
    # AL HABTOOR SURVIVES BOTH. Its sales have not exceeded its units, so **443 LEFT OF 1,739** is a true count. It is
    # hot - 1,296 sales, still trading in Aug 2026 - and, unlike every other top seller in Business Bay, its model is
    # RIGHT: 345 m of glassbronze over 93 floors. Peninsula Four is a 16 m stub for a 56-floor tower, The EDGE the
    # same, Bayz 101 is 38 m for 98 floors. Check the height before choosing a hot building; the sales rank does not.
    #
    # THE CLOSE IS THE DOSSIER, 4 pages, and it carries what the page does not - who lives in Business Bay, the shops,
    # what it sees over, and the floor plate. Kendall, 22 Sep: "we should be ending on the detailed .pdf, because
    # that's what the client gets, and we should slowly scroll through that, highlighting what information is given."
    BLD_ROUTE_8 = "/building/businessbay/574"
    DOSSIER_8 = os.path.join(ROOT, "dist_dossier", "businessbay_574.pdf")   # 4 pages
    FLOOR_8 = 86                    # the register puts ONE five-bedroom up here, and the card reads "Floor 86 - 4 homes"
    BUDGET_HI = 14
    APP = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
elif VIDEO == 9:
    # THE PHARMACY BEAT - Kendall, 24 Sep: "now film the pharmacy beat".
    #
    # Q002 "is there a pharmacy nearby?" sat at needs_data from 15 Sep to 24 Sep, on the belief that it needed a
    # source we did not have. It needed one we had all along - the DHA Sheryan facility register, already behind the
    # 1,812 clinic pins - and shipped the same day as a tenth amenity kind: 1,437 pharmacies, 727 of them flagged
    # approximate.
    #
    # THE BEAT IS MAP-ONLY, AND THAT IS A RULE, NOT A PREFERENCE. Bible 14.3: the map's amenity layer carries the
    # aligned DHA position guard and the building page's LOCATION axis still carries the old one, because the
    # district cuts reach the site only through a 32-district stack rebuild that was deliberately deferred. The two
    # can disagree on up to ten health facilities. A viewer cannot tell a deployment lag from an error, so they do
    # not go in the same frame until they agree.
    #
    # WHAT NAJ MAY AND MAY NOT SAY OVER IT. 727 of the 1,437 are positioned to about +/-555 m - the DHA register
    # rounds latitude to two decimals - and the app marks those "position approximate" on the card itself. So the
    # line is "there are nine within a kilometre", never "one is three hundred metres away". The map is honest on
    # screen; the narration has to be honest with it.
    DISTRICT_9 = os.environ.get("NAJMA_DISTRICT", "Business Bay")   # continuity with episode 07's Al Habtoor
    APP = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
    BUDGET_HI = 14
else:
    BUDGET_HI = 14                  # #hhi: 14 reads "from AED 250k to 2.0M" - the brief, exactly
BEDS = 2
TAIL_HOLD = 7.0                     # extra seconds on the LAST page of the sheet, so the sign-off lands
TWIN_TARGET = 9.0                   # seconds the twin beat should PLAY for - see the orbit note in cut()
ZOOM_TARGET = 4.0                   # a camera pull-back in the 3D, played at speed like the turns
ORBIT_TARGET = 11.0                 # video 03's opening turn of the whole city - long enough for the line that opens the film
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


# ---------------------------------------------------------------- shots
#
# Videos 01-05 were each ONE unbroken take: the cut trimmed a head and a tail and sped up the 3D turns, and scene detection
# finds zero cuts in any of them at any threshold. The Ask Najj template wants 11 shots in 45 seconds - an event every 2-3 s and
# a cut every 4-6 s. So a journey now declares its shots, and cut() ASSEMBLES them instead of trimming one take: whatever happens
# between two shots (a page load, a camera being repositioned, a panel being scrolled to the right place) never reaches the film.
#
#     with shot(mark, 3, 4.5):          # shot 3, 4.5 seconds on screen
#         orbit_by_hand(pg, ...)        # recorded slowly; played back to fit
#
# `target` is the seconds the shot should RUN FOR in the finished film. If it recorded longer than that - and on the 3D pages it
# always does, because the canvas redraws on every mouse move - the clip is sped up to fit. If it recorded shorter, it plays at
# 1x and the film is simply that much tighter; the narrative is paced to the delivered cut, never the other way round.

SHOT_PLAN = {}


@contextlib.contextmanager
def shot(mark, n, target=None, label="", mode="speed"):
    """Record one numbered shot. Everything outside a shot is discarded by cut().

    mode="speed"  a camera move: if it recorded long (the 3D always does), play it back faster to fit `target`.
    mode="hold"   a card or a held frame: never speed it up - take the LAST `target` seconds, so the film lands on
                  the settled state rather than racing through it.
    """
    SHOT_PLAN[str(n)] = {"target": target, "label": label, "mode": mode}
    mark("s%02d_in" % n)
    try:
        yield
    finally:
        mark("s%02d_out" % n)


def shots_from(marks):
    """[(n, t_in, t_out)] for every complete sNN_in/sNN_out pair, in shot order."""
    out = []
    for k in marks:
        m = re.match(r"^s(\d+)_in$", k)
        if m:
            end = marks.get("s%s_out" % m.group(1))
            if end is not None and end > marks[k]:
                out.append((int(m.group(1)), marks[k], end))
    return sorted(out)


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


def scroll_through(pg, ticks, step=380, pause=650):
    """Read down a long page the way a hand would - a few wheel ticks with a beat between them."""
    pg.mouse.move(540, 1000)
    for _ in range(ticks):
        pg.mouse.wheel(0, step); pg.wait_for_timeout(pause)


def to_top(pg):
    pg.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})"); pg.wait_for_timeout(900)


def journey3(pg, mark):
    """Video 03 - the developers, then the world. Starts on COMPARE, not the map.

    "I've heard Emaar and Sobha are the good developers - put them side by side, two bedrooms" ->
    COMPARE re-cuts every row. "I'm also looking at London - why Dubai?" -> VERSUS, then New York,
    then Monaco, back and forth. "Fine - Emaar. Show me the two-bed." -> PLANS, Marina Cove, 2 BED.
    Every beat asserts on what is visible, not on what was clicked.
    """
    # BEAT 0 - the whole city, turning. "Dubai is a big place - when you move here it feels
    # overwhelming - let me walk you through how Azimuth guides you." (Kendall, 18 Sep.) The all-Dubai
    # twin: 64,238 buildings, 41 districts, coloured by district; the drag orbit from video 01, which
    # records in slow motion and is played back at speed by cut() (marks orbit_start / orbit_end).
    pg.goto(url("/skyline?all=1"), wait_until="networkidle", timeout=120_000)
    pg.wait_for_timeout(6500)                    # the city builds in; a turn before it is drawn is a turn of nothing
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(600); mark("open")
    n_bld = pg.evaluate("() => (document.body.innerText.match(/([0-9,]+) BUILDINGS/) || [])[1] || ''")
    print("   beat 0: all-Dubai twin -> %s" % (("%s buildings on screen" % n_bld) if n_bld else "NOT DRAWN - re-run, do not ship"))
    mark("orbit_start"); orbit(pg, dx=360, at=(300, 1100)); mark("orbit_end"); pg.wait_for_timeout(600)

    # BEAT 1 - COMPARE: Emaar vs Sobha, two-beds                                 Q063/Q103
    pg.goto(url("/compare"), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(900)
    glide_click(pg, pg.get_by_text(DEV_A, exact=True).first, pause=1300)
    glide_click(pg, pg.get_by_text(DEV_B, exact=True).first, pause=2600)
    glide_click(pg, pg.get_by_text("2 bed", exact=True).first, pause=2200)
    ok = ("a=%s" % DEV_A.lower()) in pg.url and ("b=%s" % DEV_B.lower()) in pg.url and "bed=2" in pg.url
    print("   beat 1: compare %s vs %s, two-beds -> %s" % (DEV_A, DEV_B, "on" if ok else "NOT ON - re-run, do not ship"))
    scroll_through(pg, 5); pg.wait_for_timeout(1400); to_top(pg); pg.wait_for_timeout(1200); mark("b1_compare")

    # BEATS 2-4 - VERSUS: London at the budget, then New York, then Monaco
    pg.goto(url("/versus"), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(700)
    for n, city in enumerate(CITIES):
        to_top(pg)
        glide_click(pg, pg.get_by_text(city, exact=True).first, pause=1800)
        if n == 0:
            glide_click(pg, pg.get_by_text(BUDGET_TILE, exact=True).first, pause=1600)
        body = pg.evaluate("() => document.body.innerText")
        print("   beat %d: versus %s -> %s" % (n + 2, city, "on" if ("%s costs" % city) in body else "NOT ON - re-run, do not ship"))
        if n == 0:
            # Every row is a button: tapping one opens a drawer at the foot of the frame with the working
            # and the source ("stamp duty up to 12% ... plus 2% for a non-resident: up to 19%, GOV.UK 2026").
            # Kendall, 18 Sep: show that a couple of these open, without clicking a lot.
            scroll_through(pg, 1, pause=900)
            for label in ("TAX AND FEES", "TOP RATE OF INCOME TAX"):
                glide_click(pg, pg.locator("button.row", has_text=label).first, pause=2600)
                opened = pg.evaluate("() => !!document.querySelector('.drawer.open')")
                print("   beat 2: row '%s' -> %s" % (label, "drawer open" if opened else "NO DRAWER"))
                # the open drawer scrims the page - a second row tap times out behind it - so close it the
                # way a hand would, on its x, before the next line is tapped
                if opened:
                    glide_click(pg, pg.locator(".drawer.open").get_by_text("×").first, pause=900)
                    if pg.evaluate("() => !!document.querySelector('.drawer.open')"):
                        pg.keyboard.press("Escape"); pg.wait_for_timeout(600)
            scroll_through(pg, 2, pause=800)
        else:
            scroll_through(pg, 3, pause=600)
        # Never scroll far enough to bring "Say it" into frame - the script under the tables is for Naj,
        # not the client (Kendall, 18 Sep). Three ticks of 380 px show down to ~3,060 px; "Say it" sits at
        # ~3,240 on a 4,090 px page. Asserted, not assumed.
        say_y = pg.evaluate("() => { const el = [...document.querySelectorAll('*')].find(e => e.children.length < 3 && (e.innerText||'').trim().startsWith('Say it')); return el ? el.getBoundingClientRect().top : 99999 }")
        if say_y < H: print("   beat %d: 'Say it' IS IN FRAME (y=%d) - re-run, do not ship" % (n + 2, say_y))
        pg.wait_for_timeout(1500); mark("b%d_%s" % (n + 2, city.lower().replace(" ", "")))

    # BEAT 5 - "So, Emaar." -> Emaar's own project list, the close. Kendall, 18 Sep: the floor plan did not
    # tie into the story (developers -> cities -> Dubai); end on the list of what the developer is building.
    # /dev?d=emaar threw Cloudflare 1101 on 18 Sep (reported to the Azimuth session) - asserted, so a broken
    # page can never be filmed as the ending.
    pg.goto(url("/dev?d=%s" % DEV_A.lower()), wait_until="networkidle", timeout=90_000)
    body = pg.evaluate("() => document.body.innerText")
    if "Worker threw exception" in body or "Error 1101" in body or len(body) < 400:
        raise RuntimeError("beat 5: /dev?d=%s is not rendering (1101) - the Emaar list cannot be filmed yet" % DEV_A.lower())
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(1800)
    print("   beat 5: %s project list -> on (%d chars)" % (DEV_A, len(body)))
    pg.wait_for_timeout(1500)                   # the header first: sales, value, AED/m2, projects
    scroll_through(pg, 6, step=420, pause=850); pg.wait_for_timeout(1400); mark("b5_list")


def jump_click(pg, locator, pause=420):
    """Click on a heavy 3D page: one mouse move to the target (the drawn cursor follows), then the click."""
    box = locator.bounding_box()
    if not box:
        raise RuntimeError("nothing to click - the element has no box")
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    locator.click(timeout=15_000)
    pg.wait_for_timeout(pause)


def journey4(pg, mark):
    """Video 03, concept B, third cut. Kendall, 18 Sep: the hotspot, then straight into it - no PULSE page
    ("too much stuff"), no comparison; the 3D must show THAT area's buildings and projects, not an empty
    district ("I just see a big blank space ... I can't tell what's what").

    The register's projects in Madinat Al Mataar are 5-11 km apart, so no single frame holds them all; the film
    goes to the Expo City cluster, where two of them (Terra Woods, Terra Gardens) sit either side of the Red Line.
    Heat map -> hard cut to the area page, its register list -> view in 3D -> Terra Woods, the camera pulled back
    to the cluster -> AROUND IT, the metro -> Terra Gardens -> a slow turn round the cluster, held.
    """
    # HOOK - the heat map, framed before the take is marked so the film opens on it
    pg.goto(url("/charts"), wait_until="networkidle", timeout=90_000)
    # The heat map is the LAST tile on the page, so the page cannot scroll far enough to lift it out of the
    # bottom of the frame - take 1 opened with the glow at y=1847, behind the avatar and the nav bar. Empty
    # space under the page (nothing added to what is shown) lets the tile sit in the upper part of the frame.
    pg.evaluate("() => { document.body.style.paddingBottom = '1400px'; }")
    tile = pg.get_by_text("Dubai — where it", exact=False).first
    tile.scroll_into_view_if_needed(timeout=15_000); pg.wait_for_timeout(400)
    tb = tile.bounding_box()
    pg.evaluate("dy => window.scrollBy(0, dy)", tb["y"] - 330)
    pg.wait_for_timeout(2500)
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(500); mark("open")
    # the push-in: the tile eases up to nearly full width, the way a hand pinches to zoom - the app's own
    # tile enlarged in place (vector text stays sharp), not an upscale in the edit
    tile.evaluate("""el => { let c = el; while (c && c.getBoundingClientRect().height < 400) c = c.parentElement;
        c.style.transformOrigin = 'top center'; c.style.transition = 'transform 1.6s cubic-bezier(.25,.1,.25,1)';
        requestAnimationFrame(() => { c.style.transform = 'scale(1.9)'; }); }""")
    pg.wait_for_timeout(2000)
    hot = pg.get_by_text("Madinat Al Mat", exact=False).last
    box = hot.bounding_box()
    print("   hook: heat map -> %s" % ("framed, %s glowing at y=%d" % (HOT_AREA, box["y"]) if box and 0 < box["y"] < H else "NOT IN FRAME - re-run, do not ship"))
    if box: glide(pg, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.wait_for_timeout(3800); mark("b0_heat")

    # BEAT 1 - hard cut to the area's own page (the heat tile is not a link - the film cuts, it does not fake a tap)
    pg.goto(url("/area/%s" % HOT_AREA.replace(" ", "%20")), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS); pg.wait_for_timeout(2600); mark("b1_area")
    reg = pg.get_by_text("PROJECTS ON THE REGISTER HERE", exact=False).first
    reg.scroll_into_view_if_needed(timeout=15_000); pg.evaluate("() => window.scrollBy(0, -300)"); pg.wait_for_timeout(900)
    tw = pg.get_by_text(ZOOM_BUILDING, exact=False).first; twb = tw.bounding_box()
    if twb: glide(pg, twb["x"] + twb["width"] / 2, twb["y"] + twb["height"] / 2)
    print("   beat 1: register list -> %s" % ("%s on it" % ZOOM_BUILDING if twb else "NOT FOUND - re-run, do not ship"))
    pg.wait_for_timeout(3000); mark("b1_register")

    # BEAT 2 - view in 3D, straight to Terra Woods. The district loading and the fly-in cross the empty district -
    # Kendall: "I just see a big blank space" - so that stretch is a skip span: the film hard-cuts from the tap on
    # "view in 3D" to Terra Woods up close, then pulls back to reveal the cluster, the viaduct and the station.
    to_top(pg)
    glide_click(pg, pg.locator("a", has_text="view in 3D").first, pause=300)
    mark("orbitskip_start")
    pg.wait_for_load_state("networkidle", timeout=120_000); pg.wait_for_timeout(6500)
    print("   beat 2: district twin -> %s" % ("drawn" if "/skyline/%s" % HOT_SLUG in pg.url else "NOT OPEN - re-run, do not ship"))
    pg.evaluate(CURSOR_JS)
    jump_click(pg, pg.get_by_text(ZOOM_BUILDING, exact=False).first, pause=4500)
    card = pg.evaluate("() => /%s/.test(document.body.innerText) && /AROUND IT/i.test(document.body.innerText)" % ZOOM_BUILDING)
    print("   beat 2: %s card -> %s" % (ZOOM_BUILDING, "open" if card else "NOT OPEN - re-run, do not ship"))
    pg.mouse.move(420, 1150); pg.wait_for_timeout(300)
    mark("orbitskip_end"); pg.wait_for_timeout(1400)
    # the pull-back: seven slower ticks settle on the cluster and stay (nine fast ones overshot into the district)
    mark("orbitzoom_start")
    for _ in range(7): pg.mouse.wheel(0, 400); pg.wait_for_timeout(260)
    pg.wait_for_timeout(2200); mark("orbitzoom_end")
    pg.wait_for_timeout(700); mark("b2_cluster")            # was 2.8 s: with the 0.9 s below, a 4 s still at 0:22

    # BEAT 3 - AROUND IT is already open on the card (it opens on that tab); no tap - a tap on the heavy 3D page
    # takes seconds to go through and left 0:29-0:39 still (Kendall). Assert the metro row, hold a beat, move on.
    body = pg.evaluate("() => document.body.innerText")
    line = next((l.strip() for l in body.splitlines() if "EXPO Metro Station" in l), "")
    print("   beat 3: around it -> %s" % (("metro listed: " + line[:60]) if line else "NO METRO ROW - re-run, do not ship"))
    pg.wait_for_timeout(300); mark("b3_around")

    # BEAT 4 - a slow turn round the cluster at that height, held for the sign-off
    pg.mouse.move(420, 1150); pg.wait_for_timeout(300)
    mark("orbit2_start"); orbit(pg, dx=-240, at=(420, 1150)); mark("orbit2_end")

    # BEATS 5a-5b - show the app off: tap the station, then the park (Kendall, 18 Sep: "click on the Expo Metro
    # station and she can speak on it ... and the park ... it's going to zoom into that"). Each tap takes ~8 s to go
    # through on the 3D page, so the wait is a skip span - the film cuts from the tap to the camera arriving - and each
    # flight lands very close, so a short pull-back follows. The card for each place holds while Naj speaks.
    def visit(name, tag, n):
        mark("orbitskip%s_start" % tag)
        jump_click(pg, pg.get_by_text(name, exact=False).first, pause=600)
        ok = name in pg.evaluate("() => document.body.innerText") and "DIRECTIONS" in pg.evaluate("() => document.body.innerText")
        print("   beat 5: %s card -> %s" % (name, "open" if ok else "NOT OPEN - re-run, do not ship"))
        pg.mouse.move(420, 1150)          # slow on the 3D page - kept inside the cut-out span (was 2-3 s of stillness)
        mark("orbitskip%s_end" % tag); pg.wait_for_timeout(150)
        mark("orbitzoom%s_start" % tag)
        for _ in range(n): pg.mouse.wheel(0, 400); pg.wait_for_timeout(260)
        pg.wait_for_timeout(1800); mark("orbitzoom%s_end" % tag)
        pg.wait_for_timeout(2600); mark("b5_%s" % tag)      # the card holds ~3.5 s with the settle - Naj's line
    def back(tag):
        mark("orbitskip%s_start" % tag)
        jump_click(pg, pg.get_by_text("BACK", exact=False).first, pause=400)
        mark("orbitskip%s_end" % tag)
    visit("EXPO Metro Station", "metro", 5)
    back("back1")
    visit("Expo Park", "park", 5)
    back("back2")
    ok = "824 UNITS" in pg.evaluate("() => document.body.innerText")
    print("   beat 5: back to %s -> %s" % (ZOOM_BUILDING, "card open" if ok else "NOT BACK - re-run, do not ship"))

    # BEAT 6 - pull back for context (Kendall: "zooming out a bit so we get a bit of context at the very end"),
    # then label the places on the held frame. The 3D names only the station itself; the app's own place rings
    # (.tm.sel = the selected project, .tm.near = the nearest of each kind, coloured by kind as in AROUND IT) get
    # a name beside them, positioned from each ring's live position once the camera has stopped. Labels added for
    # the film, not app features - the storyboard says so. The pink ring (clinic or school - ambiguous) is left bare.
    pg.mouse.move(420, 1150); pg.wait_for_timeout(300)
    mark("orbitzoom3_start")
    for _ in range(6): pg.mouse.wheel(0, 400); pg.wait_for_timeout(260)
    pg.wait_for_timeout(2600); mark("orbitzoom3_end")
    n = pg.evaluate("""() => {
      const names = {'143,211,160': ['Expo Park', '#8FD3A0'], '201,179,126': ['Spinneys', '#C9B37E']};
      const cur = document.getElementById('__cur'); if (cur) cur.style.display = 'none';   // the drawn cursor is a gold ring too
      const placed = [];   // the app's own station label counts as taken - never cover it
      document.querySelectorAll('*').forEach(e => { if (e.children.length < 2 && /Red Line station/.test(e.innerText || '')) {
        const q = e.getBoundingClientRect(); if (q.width) placed.push({x: q.x, y: q.y, w: q.width, h: q.height}); } });
      const put = (el, name, col, side) => { const r = el.getBoundingClientRect(); const d = document.createElement('div');
        d.textContent = name; d.style.cssText = 'position:fixed;z-index:50;pointer-events:none;font:600 22px/1.1 "IBM Plex Sans",system-ui,sans-serif;'
          + 'color:#F3EEE3;text-shadow:0 1px 3px #000,0 0 8px #000;padding:2px 6px;border-left:3px solid ' + col + ';background:rgba(10,14,12,.55);opacity:0;transition:opacity .6s';
        document.body.appendChild(d); const w = d.offsetWidth, h = d.offsetHeight;
        let x = r.x + r.width + 10, y = r.y + r.height / 2 - h / 2;
        if (side === 'above') { x = r.x + r.width / 2 - w / 2; y = r.y - h - 10; }
        if (side === 'below') { x = r.x + r.width / 2 - w / 2; y = r.y + r.height + 8; }
        if (x + w > 690) x = r.x - w - 10;
        for (let k = 0; k < 6; k++) {   // nudge clear of any label already placed
          const hit = placed.some(q => x < q.x + q.w + 6 && x + w + 6 > q.x && y < q.y + q.h + 6 && y + h + 6 > q.y);
          if (!hit) break; y -= h + 8; }
        placed.push({x, y, w, h});
        d.style.left = Math.round(x) + 'px'; d.style.top = Math.round(y) + 'px'; requestAnimationFrame(() => d.style.opacity = 1); return 1; };
      let n = 0;
      const sel = document.querySelector('.tm.sel'); if (sel) n += put(sel, 'Terra Woods', '#C5A56A', 'below');
      const side = {'Expo Park': 'above', 'Spinneys': 'right'};
      document.querySelectorAll('.tm.near').forEach(e => { const c = getComputedStyle(e).borderColor.replace(/[^0-9,]/g, '');
        if (names[c]) n += put(e, names[c][0], names[c][1], side[names[c][0]]); });
      return n; }""")
    print("   beat 5: labels placed -> %d of 3%s" % (n, "" if n == 3 else "  CHECK FRAME"))
    pg.wait_for_timeout(3000); mark("b5_hold")


# ---------------------------------------------------------------- video 04: the building page

# The building page's own phone layout (its max-width:820px rules), applied at 1080 wide and drawn at twice the
# size, so the take is a native 9:16 at full sharpness. One change for the film: a card opens over the filter panel
# at the bottom rather than over the model at the top, so the floor that was tapped stays in view; and the scene
# is drawn BLD_SHIFT higher, because the page centres the building exactly where the phone layout's panel begins.
BLD_CSS = """
#title{position:fixed!important;left:0!important;right:0!important;top:52px!important;transform:none!important;max-width:none!important;padding:0!important}
#panel{left:10px!important;right:10px!important;width:auto!important;top:auto!important;bottom:10px!important;max-height:23vh!important;background:#121C19!important}
#card{left:10px!important;right:10px!important;width:auto!important;top:auto!important;bottom:10px!important;max-height:23vh!important;z-index:6!important;background:#121C19!important}
#foot,#gcredit{display:none!important}
#warn{left:10px!important;right:10px!important;max-width:none!important;bottom:auto!important;top:112px!important}
#about{top:18px!important;left:auto!important;right:14px!important}
#panel,#card,#about,.bk,#title,#warn{zoom:2}
body{background:#0B1412!important}canvas{transform:translateY(-%dpx)}
""" % 330
BLD_SHIFT = 330    # the scene is drawn that much higher, so the building - the orbit's pivot, mid-screen - sits in the clear top half


def smooth_scroll(pg, sel, target_js, ms=1500):
    """Scroll a panel the way a thumb does - eased, to a named place - rather than in wheel notches."""
    pg.evaluate("""([sel, tjs, ms]) => new Promise(done => {
      const e = document.querySelector(sel), a = e.scrollTop, top = Math.max(0, Math.min(e.scrollHeight - e.clientHeight, (new Function('e', 'return ' + tjs))(e))), t0 = performance.now();
      const step = t => { const p = Math.min(1, (t - t0) / ms), k = p * p * (3 - 2 * p); e.scrollTop = a + (top - a) * k; p < 1 ? requestAnimationFrame(step) : done(); };
      requestAnimationFrame(step); })""", [sel, target_js, ms])
    pg.wait_for_timeout(250)


def _drag(pg, x0, y0, x1, y1, button="left", steps=12, settle=900):
    pg.mouse.move(x0, y0); pg.mouse.down(button=button); pg.mouse.move(x1, y1, steps=steps); pg.mouse.up(button=button)
    pg.wait_for_timeout(settle)


def _txt(pg, sel):
    return re.sub(r"\s+", " ", pg.evaluate("s => (document.querySelector(s) || {}).innerText || ''", sel)).strip()


def journey5(pg, mark):
    pg.goto(url(BLD_ROUTE), wait_until="domcontentloaded", timeout=90_000)
    pg.add_style_tag(content=BLD_CSS)
    pg.wait_for_selector("canvas", timeout=60_000); pg.wait_for_timeout(1500)
    pg.mouse.move(540, 300); pg.mouse.down(); pg.mouse.up()          # any press stops the page's idle rotation
    pg.wait_for_timeout(8000)                                        # the district model and the ground imagery arrive
    _drag(pg, 540, 500, 540, 700)                                    # look down on it
    pg.mouse.move(540, 620); pg.mouse.wheel(0, -240); pg.wait_for_timeout(1200)   # and a little closer
    pg.evaluate(CURSOR_JS)
    pg.mouse.move(860, 960, steps=4); pg.wait_for_timeout(1200)
    mark("open")
    pg.wait_for_timeout(2200)

    # beat 1 - move in on the building. Kendall, 20 Sep, on take 4: "why doesn't the video ever zoom in or cue into
    # the building itself? ... I don't feel like the building is highlighted." From the wide view the tapped floor lit
    # as a hairline; at this distance the floors read one by one and the tapped one is a gold band across the face.
    mark("orbit1_start")
    pg.mouse.move(540, 620, steps=6); pg.wait_for_timeout(300)
    for i in range(18):
        pg.mouse.wheel(0, -100); pg.wait_for_timeout(150 - 60 * (1 - abs(i - 9) / 9.0))     # eased: slow in, slow out
    pg.wait_for_timeout(500)
    x, y, N = 760, 860, 40                       # then down beside it, and a small turn, in one hand movement
    pg.mouse.move(x, y, steps=6); pg.wait_for_timeout(200); pg.mouse.down()
    for i in range(1, N + 1):
        t = i / N; k = t * t * (3 - 2 * t); pg.mouse.move(x - 110 * k, y - 110 * k); pg.wait_for_timeout(80)
    pg.mouse.up(); pg.wait_for_timeout(900)
    mark("orbit1_end")

    # beat 2 - tap a floor: its card, with the floor plate
    mark("beat2")
    # The canvas is drawn BLD_SHIFT higher than the page thinks, so a real click would cast its ray from the wrong
    # height. The hand travels to the floor on screen; the press itself is handed to the canvas at the height the
    # page's own arithmetic expects.
    tap = """([x, y]) => { const c = document.querySelector('canvas'), cur = document.getElementById('__cur');
      const ev = t => c.dispatchEvent(new PointerEvent(t, {clientX: x, clientY: y, bubbles: true, pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0}));
      if (cur) { cur.style.transform = 'scale(.55)'; setTimeout(() => cur.style.transform = 'scale(1)', 160); }
      try { ev('pointerdown'); } catch (e) {} try { ev('pointerup'); } catch (e) {} }"""
    hit = None
    for n, (px, py) in enumerate(((560, 650), (560, 610), (560, 690), (440, 650), (680, 650), (560, 570), (560, 730))):
        pg.mouse.move(px, py, steps=1 if n else 6); pg.wait_for_timeout(350)
        pg.evaluate(tap, [px, py + BLD_SHIFT]); pg.wait_for_timeout(900)
        if pg.locator("#card").is_visible():
            hit = (n, px, py); break
    if not hit:
        raise RuntimeError("no floor answered the tap - the building is not where the framing expects it")
    print("   tap %d hit at %s,%s" % hit)
    print("   floor card:", _txt(pg, "#card")[:420])
    pg.wait_for_timeout(2600)
    smooth_scroll(pg, "#card", "e.querySelector('.plate') ? e.querySelector('.plate').previousElementSibling.offsetTop - 6 : 0", 1300)
    pg.wait_for_timeout(3000)
    glide_click(pg, pg.locator("#card .x"), pause=900)

    # beat 3 - the filters: every type off, then the two-beds, then a side that sees over the roofs
    mark("beat3")
    glide_click(pg, pg.locator("#hide"), pause=1100)
    glide_click(pg, pg.locator("[data-t]", has_text="2 BHK"), pause=1500)
    print("   count, 2 BHK only:", _txt(pg, "#count"))
    pg.wait_for_timeout(1400)
    if VIEW_CHIP:
        glide_click(pg, pg.locator("[data-d]", has_text=re.compile(r"^\s*%s\s*$" % VIEW_CHIP)).first, pause=1500)
        print("   count, + open to %s:" % VIEW_CHIP, _txt(pg, "#count"))
        pg.wait_for_timeout(1600)

    # beat 4 - sold so far, by type
    mark("beat4")
    glide(pg, 560, 1500)
    smooth_scroll(pg, "#panel", "[...e.querySelectorAll('.grp')].find(g => /sold so far/i.test(g.textContent)).offsetTop - 10", 1700)
    pg.wait_for_timeout(5200)

    # beat 5 - about the building: the facts, what it sees over, who lives here, and the plans
    mark("beat5")
    pg.mouse.move(540, 620, steps=6)
    for i in range(9):
        pg.mouse.wheel(0, 100); pg.wait_for_timeout(120)
    pg.wait_for_timeout(500)
    glide_click(pg, pg.locator("#about"), pause=1200)
    print("   about h3s:", pg.evaluate("[...document.querySelectorAll('#card h3')].map(h => h.textContent)"))
    print("   sees over:", _txt(pg, "#card")[_txt(pg, "#card").find("What it sees over"):][:330])
    glide(pg, 560, 1500); pg.wait_for_timeout(2600)
    h3 = lambda rx: "[...e.querySelectorAll('h3')].find(h => /%s/i.test(h.textContent)).offsetTop - 6" % rx
    smooth_scroll(pg, "#card", h3("sold, from"), 1500); pg.wait_for_timeout(3000)
    mark("beat5b")
    smooth_scroll(pg, "#card", h3("who lives"), 1700); pg.wait_for_timeout(3400)
    mark("beat6")
    smooth_scroll(pg, "#card", h3("the plans"), 1900); pg.wait_for_timeout(3600)
    smooth_scroll(pg, "#card", h3("the plans") + " + 330", 2200); pg.wait_for_timeout(1500)
    pg.evaluate("document.getElementById('__cur').style.display = 'none'")
    mark("hold")
    pg.wait_for_timeout(3000)


# ---------------------------------------------------------------- video 05: the view from the window

def _real_view(pg, mark, side, n, hold):
    """Tap one side's card on the building panel -> the real view from that facade, at that height. The photoreal tiles take
    up to 12 s to sharpen, and the page only starts its own slow pan once they have: that wait is a skip span, so the film
    goes from the tap to the sharp view."""
    cell = pg.locator("#ppanel .vw .vc", has=pg.locator("b", has_text=re.compile(r"^%s$" % side))).first
    cell.scroll_into_view_if_needed(timeout=15_000); pg.wait_for_timeout(500)
    print("   %s: %s" % (side, _txt_of(cell)))
    jump_click(pg, cell, pause=200)
    mark("orbitskip%d_start" % n)
    pg.wait_for_url(re.compile(r"/view\?"), timeout=30_000)
    try:
        pg.wait_for_function("() => !document.getElementById('st')", timeout=25_000)     # the 'sharpening...' note goes when the tiles are in
    except Exception:
        print("   %s: the view never reported sharp - check the frames" % side)
    pg.wait_for_timeout(1500)
    mark("orbitskip%d_end" % n)
    pg.wait_for_timeout(int(hold * 1000))


def _deeper(pg, click):
    """The phone panel opens on the floor layout (or the snapshot). Its mode switch is the little target at the top right: tap it,
    the three modes unfold, tap Deeper dive - and the four views are at the top of that block."""
    if not pg.locator("#ppanel .mb[data-m=deep]").is_visible():
        click(pg, pg.locator("#ppanel #mob"), pause=600)
    click(pg, pg.locator("#ppanel .mb[data-m=deep]"), pause=900)
    pg.evaluate("(() => { const p = document.getElementById('ppanel'), v = p.querySelector('.vw'); if (v) p.scrollTo({top: Math.max(0, v.offsetTop - 46), behavior: 'smooth'}); })()")
    pg.wait_for_timeout(900)


def _txt_of(loc):
    return re.sub(r"\s+", " ", loc.inner_text()).strip()


def _back_to_panel(pg, mark, n):
    """Back to the twin. The 3D reloads and the panel reopens on the building from the deep link; all of it is a skip span."""
    mark("orbitskip%d_start" % n)
    pg.goto(url("/skyline/businessbay?clean=1&b=%s" % VIEW_ANCHOR), wait_until="domcontentloaded", timeout=90_000)
    pg.wait_for_selector("#ppanel .vw .vc", timeout=60_000, state="attached")
    pg.evaluate(CURSOR_JS)
    pg.wait_for_timeout(2500)
    _deeper(pg, jump_click)
    pg.wait_for_timeout(900)
    mark("orbitskip%d_end" % n)
    pg.wait_for_timeout(1400)


def journey6(pg, mark):
    pg.goto(url("/skyline/businessbay?clean=1&b=%s" % VIEW_ANCHOR), wait_until="domcontentloaded", timeout=90_000)
    pg.wait_for_selector("#ppanel .vw .vc", timeout=60_000, state="attached")
    pg.wait_for_timeout(7000)                                        # the district model streams in and the camera settles on the tower
    pg.evaluate(CURSOR_JS)
    # ?clean=1 is the twin's own film mode: the search bar, the district rail and the nav step aside, so on a phone the tower has
    # the top half of the screen and the building panel the bottom. The deep link lands the camera hard against the tower; pull
    # back until the whole of it, and what stands round it, is in view.
    pg.mouse.move(270, 250)
    for _ in range(VIEW_PULLBACK):
        pg.mouse.wheel(0, 240); pg.wait_for_timeout(260)
    pg.wait_for_timeout(1200)
    pg.mouse.move(410, 330, steps=4); pg.wait_for_timeout(800)
    print("   window:", pg.evaluate("[innerWidth, innerHeight, devicePixelRatio]"), "| panel:", _txt(pg, "#ppanel")[:200])
    mark("open")
    pg.wait_for_timeout(2000)

    # beat 1 - turn the tower, by hand
    mark("orbit1_start")
    box = pg.locator("#ppanel").bounding_box()
    y = max(150, min(420, (box["y"] if box else 520) - 110))
    x, dx, N = 410, -170, 44
    pg.mouse.move(x, y, steps=8); pg.wait_for_timeout(200); pg.mouse.down()
    for i in range(1, N + 1):
        t = i / N; pg.mouse.move(x + dx * t * t * (3 - 2 * t), y); pg.wait_for_timeout(95)
    pg.mouse.up(); pg.wait_for_timeout(900)
    mark("orbit1_end")

    # beat 2 - the deeper dive: the view from each side
    mark("beat2")
    _deeper(pg, glide_click)
    pg.wait_for_timeout(1200)
    cells = pg.evaluate("[...document.querySelectorAll('#ppanel .vw .vc')].map(c => c.querySelector('b').textContent + ': ' + c.querySelector('i').textContent)")
    print("   views:", cells)
    for side in VIEW_TOUR:                                           # the hand passes over each side as Naj names it
        c = pg.locator("#ppanel .vw .vc", has=pg.locator("b", has_text=re.compile(r"^%s$" % side))).first
        b2 = c.bounding_box()
        if b2:
            glide(pg, b2["x"] + b2["width"] / 2, b2["y"] + b2["height"] / 2, steps=14); pg.wait_for_timeout(1500)

    # beat 3 - stand on the good side
    mark("beat3")
    _real_view(pg, mark, VIEW_GOOD, 1, 9.0)
    _back_to_panel(pg, mark, 2)

    # beat 4 - stand on the blocked side
    mark("beat4")
    _real_view(pg, mark, VIEW_BLOCKED, 3, 8.0)
    _back_to_panel(pg, mark, 4)

    # beat 5 - and the sunset side, held for the sign-off
    mark("beat5")
    _real_view(pg, mark, VIEW_LAST, 5, 9.0)
    mark("hold")
    pg.wait_for_timeout(3000)


# ---------------------------------------------------------------- video 06: could someone build in front of me?

# The first episode cut to the Ask Najj template: 11 shots in ~45 s, an event every 2-3 s, a cut every 4-6 s, the turn at 55%,
# and the payoff on the occlusion reveal - the camera arcs until the thing that blocks the view comes out from behind the tower.
#
# ONE River Point (anchor 589, Business Bay), verified 21 Sep: N sees the Dubai Canal and Burj Khalifa, W the Burj Al Arab and
# Palm Jumeirah, S Dubai Hills - and E is blocked by One by Binghatti, which stands 344 m away and 87 m taller (227 m against
# 140 m). The blocker really is the neighbouring mass, so the format's signature shot and the episode's answer are one move.
#
# Filmed in the twin's own phone layout at a real device scale of 2 (see capture()), with ?clean=1 - the twin's film mode, which
# stands the search bar, the district rail and the nav aside.


def _turn(pg, x, y, dx, n=26, ms=85):
    """A hand-dragged orbit. One mouse.move per step so the canvas redraws; eased so it does not read as a machine."""
    pg.mouse.move(x, y, steps=6); pg.wait_for_timeout(180); pg.mouse.down()
    for i in range(1, n + 1):
        t = i / n
        pg.mouse.move(x + dx * t * t * (3 - 2 * t), y); pg.wait_for_timeout(ms)
    pg.mouse.up(); pg.wait_for_timeout(500)


def _wheel(pg, x, y, ticks, step=180, ms=120):
    pg.mouse.move(x, y)
    for _ in range(abs(ticks)):
        pg.mouse.wheel(0, step if ticks > 0 else -step); pg.wait_for_timeout(ms)
    pg.wait_for_timeout(400)


def _side(pg, letter):
    return pg.locator("#ppanel .vw .vc", has=pg.locator("b", has_text=re.compile(r"^%s$" % letter))).first


def _show(pg, letter):
    """Bring one side's card to the top of the panel and read it back, so the take proves what was on screen."""
    c = _side(pg, letter)
    c.scroll_into_view_if_needed(timeout=15_000)
    pg.evaluate("""(l) => { const p = document.getElementById('ppanel');
        const c = [...p.querySelectorAll('.vw .vc')].find(x => x.querySelector('b').textContent.trim() === l);
        if (c) p.scrollTo({top: Math.max(0, c.offsetTop - 40), behavior: 'smooth'}); }""", letter)
    pg.wait_for_timeout(700)
    return re.sub(r"\s+", " ", c.inner_text()).strip()


TWIN_CSS = """
#ppanel{bottom:10px!important;max-height:33vh!important;background:#121C19!important}
#foot,#gcredit,.maplibregl-ctrl-bottom-right{display:none!important}
"""


def journey7(pg, mark):
    """The building page in its WIDE layout, 11 shots, closing on the dossier. Aykon City-tower B, 89 floors.

    Three things learned the hard way, written down so nobody repeats them.

    FILM THE BUILDING PAGE, NOT THE TWIN. On the twin a selected building is repainted by home type and loses its facade
    entirely - Kendall, on that cut: "you picked the building with no facade, this is horrible... I wouldn't put this in front
    of any client." The building page keeps the CityEngine texture, so the tower looks like a tower.

    DO NOT FORCE THE PHONE LAYOUT. Video 04 injected the page's own max-width:820px rules to film a phone. At 1080 wide the
    page's NATIVE wide layout puts About the building down the left, the filters and the rings down the right, and the tower
    between them - which is the composition Kendall asked for: "we have stuff to scroll through on the right hand side, stuff
    to scroll through on the left hand side."

    NO OCCLUSION REVEAL. Four takes and nine stepped camera positions on the twin never brought the blocking tower into frame
    labelled; the camera answers a drag too little to swing a reliable arc. The view answer is carried by "What it sees over"
    and by the dossier, in writing, instead.
    """
    pg.goto(url(BLD_ROUTE_7), wait_until="domcontentloaded", timeout=90_000)
    pg.wait_for_selector("canvas", timeout=60_000)
    pg.wait_for_timeout(16000)                                   # the model, its facade and the ground imagery
    pg.evaluate(CURSOR_JS)
    mark("open")

    # 1 - the tower as it really looks: facade, neighbours, a slow turn
    with shot(mark, 1, 6.0, "the tower, facade"):
        _turn(pg, 620, 900, -150, n=20, ms=95)

    # 2 - closer
    with shot(mark, 2, 5.0, "closer"):
        _wheel(pg, 620, 800, -3, step=170, ms=180)
        _turn(pg, 620, 900, -100, n=14, ms=95)

    # 3 - About the building: what the register says it is
    with shot(mark, 3, 5.0, "about the building", mode="hold"):
        glide_click(pg, pg.locator("#about"), pause=1200)
        pg.wait_for_timeout(3000)

    # 4 - down the left: the stack, and what has sold
    with shot(mark, 4, 6.0, "the stack, and what sold", mode="hold"):
        smooth_scroll(pg, "#card", "[...e.querySelectorAll('h3')].find(h => /sold, from/i.test(h.textContent)).offsetTop - 8", 1800)
        pg.wait_for_timeout(3600)

    # 5 - what it sees over, side by side
    with shot(mark, 5, 5.5, "what it sees over", mode="hold"):
        smooth_scroll(pg, "#card", "[...e.querySelectorAll('h3')].find(h => /sees over/i.test(h.textContent)).offsetTop - 8", 1600)
        pg.wait_for_timeout(3400)
        print("   sees over:", _txt(pg, "#card")[_txt(pg, "#card").find("What it sees over"):][:190])

    # 6 - the right-hand side: filter the tower by home type
    with shot(mark, 6, 4.5, "filter by home type"):
        glide_click(pg, pg.locator("#hide"), pause=1000)
        glide_click(pg, pg.locator("[data-t]", has_text="2 BHK").first, pause=1600)
        print("   2 BHK:", _txt(pg, "#count"))

    # 7 - WHAT IS LEFT: a ring per bedroom type (Kendall's design, live 21 Sep)
    with shot(mark, 7, 6.0, "what is left, ring per type", mode="hold"):
        glide_click(pg, pg.locator("#hide"), pause=900)
        smooth_scroll(pg, "#panel", "[...e.querySelectorAll('.grp')].find(g => /sold so far/i.test(g.textContent)).offsetTop - 10", 1700)
        pg.wait_for_timeout(3800)
        seen = _txt(pg, "#panel"); i = seen.upper().find("SOLD SO FAR")
        print("   left:", seen[i:i + 180] if i >= 0 else "RINGS NOT IN VIEW")

    # 8 - choose a floor, and the plate for it appears on the left
    with shot(mark, 8, 6.0, "choose a floor - the plate", mode="hold"):
        pg.select_option("#fpick", index=FLOOR_A)
        pg.wait_for_timeout(4200)
        print("   floor A:", _txt(pg, "#card")[:130])

    # 9 - a different floor, a different plate
    with shot(mark, 9, 5.5, "another floor, another plate", mode="hold"):
        pg.select_option("#fpick", index=FLOOR_B)
        pg.wait_for_timeout(3800)
        print("   floor B:", _txt(pg, "#card")[:130])

    # 10 - a last turn, wide
    with shot(mark, 10, 5.0, "a last turn"):
        _wheel(pg, 620, 800, 2, step=150, ms=170)
        _turn(pg, 620, 900, 130, n=18, ms=95)

    # 11 - held, before the document
    with shot(mark, 11, 4.0, "held", mode="hold"):
        pg.evaluate("document.getElementById('__cur').style.display='none'")
        pg.wait_for_timeout(3000)
    mark("hold")


def journey8(pg, mark):
    """Video 07 - AL HABTOOR TOWER, Business Bay 574. 45 seconds, 11 shots, one surface.

    "I keep walking past Al Habtoor Tower. Is there anything left in it? And what's Business Bay actually like to
    live in?" Two questions: the page answers the first, the dossier answers the second.

    Kendall, 22 Sep, on the opening: "I'd like to start with a shot like this and then zoom into the building, or
    let it rotate with all of the buildings and then zoom in." So shots 1-3 are one continuous approach - the
    district turning, the camera closing, the tower arriving - cut into three rather than filmed as three.

    THE NUMBERS THIS FILM RESTS ON, all verified on the live build before a frame was shot:
        443 LEFT OF 1,739   a TRUE count here - sales have not exceeded units, unlike 304 buildings citywide
        93 floors, 345 m    the model is correct, which most Business Bay top-sellers' are not
        Floor 86 - 4 homes  ninety-three floors, seventeen hundred homes, and four of them up there
    """
    # SHOTS 1-3 ARE THE DISTRICT, NOT THE BUILDING PAGE, and that is the fix that mattered most.
    #
    # The first take opened on /building/businessbay/574. Deep-linking a building SELECTS it, and a selected building
    # is repainted by home type - so the hero shot was a mustard-and-blue block and the 345 m glassbronze facade was
    # never seen. Kendall, 21 Sep, on the previous time this happened: "this looks absolutely horrible. I wouldn't
    # put this in front of any client."
    #
    # So the film arrives the way a person would: the district first, with every facade intact and its towers
    # labelled - Al Habtoor Tower among them - and the repaint happens at shot 4, when she taps in. The cut makes the
    # two pages read as one continuous approach.
    pg.goto(url("/skyline/businessbay?clean=1"), wait_until="domcontentloaded", timeout=90_000)
    pg.wait_for_selector("canvas", timeout=60_000)
    pg.wait_for_timeout(18000)                       # the district, the ground imagery and the facades all stream in
    pg.mouse.move(700, 400); pg.mouse.down(); pg.mouse.up()      # any press stops the page's own idle rotation
    pg.evaluate(CURSOR_JS)
    pg.wait_for_timeout(1200)
    mark("open")

    # 1 - Business Bay from above. Two notches, not nine: at nine the district leaves the frame entirely and the shot
    #     is an empty green field. Verified by frame check before this was written.
    with shot(mark, 1, 4.0, "the district, real facades"):
        _wheel(pg, 540, 900, 2, step=170, ms=160)
        _turn(pg, 620, 900, -70, n=12, ms=95)

    # 2 - the turn continuing, Al Habtoor's label arriving on the left. Cut on motion, so 1 and 2 read as one camera.
    with shot(mark, 2, 4.0, "Al Habtoor Tower, named"):
        _turn(pg, 620, 900, -70, n=12, ms=95)

    # 3 - in on the tower, still in the district, facade intact
    with shot(mark, 3, 3.5, "closing on the tower"):
        _wheel(pg, 540, 900, -3, step=170, ms=180)
        _turn(pg, 620, 900, -40, n=9, ms=95)

    # 4 - now the building page, and ABOUT THE BUILDING. Dead until 22 Sep: the handler threw on `K is not defined`
    #     and took the whole card with it, including the occupancy block nobody had ever seen. Fixed in v245.1.
    with shot(mark, 4, 3.0, "the card opens", mode="hold"):
        pg.goto(url(BLD_ROUTE_8), wait_until="domcontentloaded", timeout=90_000)
        pg.wait_for_selector("canvas", timeout=60_000)
        pg.wait_for_timeout(11000)
        pg.evaluate(CURSOR_JS)
        jump_click(pg, pg.locator("#about"))
        pg.wait_for_timeout(2200)

    # 5 - the register: 1,739 homes, 93 floors, and the answer to her first question
    with shot(mark, 5, 4.5, "443 LEFT OF 1,739", mode="hold"):
        smooth_scroll(pg, "#card", "0")
        pg.wait_for_timeout(3000)
        print("   sold line:", pg.evaluate(
            """(() => { const t = document.getElementById('card').innerText;
                 return (t.match(/[^\\n]*LEFT OF[^\\n]*/) || ['(no sold line)'])[0]; })()"""))

    # 6 - what each home type costs, and which floors it sits on
    with shot(mark, 6, 3.5, "types and their floors", mode="hold"):
        smooth_scroll(pg, "#card", "e.scrollHeight * 0.34")
        pg.wait_for_timeout(2600)

    # 7 - FLOOR 86. Ninety-three floors, and the register puts four homes up here - one of them the tower's only
    #     five-bedroom. This is the detail no portal holds.
    with shot(mark, 7, 4.5, "floor 86 - four homes", mode="hold"):
        _pick_floor(pg, FLOOR_8)
        pg.wait_for_timeout(3000)

    # 8 - THE TURN, at 60%: the question turns from what is left to what it is like to live there
    with shot(mark, 8, 2.0, "TURN - but what is it like?", mode="hold"):
        pg.wait_for_timeout(1800)

    # 9 - the floor plate: the homes on that floor, drawn, with lifts and stairs
    with shot(mark, 9, 5.0, "the floor plate", mode="hold"):
        smooth_scroll(pg, "#card", """(() => { const t = [...document.querySelectorAll('#card *')]
            .find(e => /floor plate/i.test(e.textContent || '') && e.children.length < 30);
            return t ? Math.max(0, t.offsetTop - 30) : 0; })()""")
        pg.wait_for_timeout(3600)

    # 10 - back out to the tower among its neighbours, easing to a full stop. The payoff move, per template 4 v1.1:
    #      motion into stillness is the full stop, and this is the only shot allowed to come to rest.
    with shot(mark, 10, 4.5, "held among its neighbours"):
        pg.evaluate("(() => { const c = document.getElementById('card'); if (c) c.style.display = 'none'; })()")
        _wheel(pg, 540, 500, 2, step=150, ms=180)
        _turn(pg, 620, 420, -45, n=10, ms=100)
        pg.wait_for_timeout(1400)

    # 11 - held, clean, on the tower. The last thing before the document.
    with shot(mark, 11, 3.5, "held on the tower", mode="hold"):
        pg.evaluate("(() => { const c = document.getElementById('__cur'); if (c) c.style.display = 'none'; })()")
        pg.wait_for_timeout(2800)

    # 12-17 - THE DOSSIER, SCROLLED. Kendall, 22 Sep: "she should be scrolling through that four page dossier slowly
    # and kind of explaining everything there as well. She doesn't want to like fly through it."
    #
    # So the close is NOT close_clip(), which cuts page to page and reads as a slideshow. It is the dossier's own HTML,
    # opened in the browser and SCROLLED - continuous motion, real type, and a pause on each section long enough for
    # Naj to name what it is. Six stops, about 3.5 s each: the stack, what it sells for, who built it, what is around
    # it, who lives here, and the floor plate.
    _dossier_scroll(pg, mark)
    mark("hold")


# The dossier is authored for paper - dark type on white. Dropped into a champagne-graded film it flares, and at the
# zoom that fits a page on screen the type is unreadable on a phone. So it is dressed for the film: the app's own
# near-black, cream type, gold headings, and 2.4x so a section reads at phone size. Nothing is re-worded or hidden -
# only the paper is changed, and it is our document.
DOSSIER_CSS = """
html,body{background:#0B1412!important;color:#E8E2D4!important}
*{border-color:#2A3A34!important}
h1,h2,h3,h4{color:#C9A227!important}
table,td,th,tr{background:transparent!important;color:#E8E2D4!important}
img,svg{filter:invert(.92) hue-rotate(180deg) saturate(.85)}
html{scroll-behavior:auto}
body{zoom:2.4}
"""

DOSSIER_STOPS = [
    (12, "the building and the stack",   "the stack"),
    (13, "what it sells for",            "what it sells for"),
    (14, "who designed and built it",    "designed and built by"),
    (15, "around it, and the shops",     "shops and groceries"),
    (16, "who lives in Business Bay",    "who lives in"),
    (17, "the floor plate",              "the floor plate"),
]


def _dossier_scroll(pg, mark):
    """Open the dossier's own HTML and scroll it, pausing on each section.

    The HTML rather than the PDF because a PDF can only be flipped: rendering page images and holding each one reads
    as a slideshow, and this is the document the client keeps - it should feel like being walked through it, not
    shown it. `smooth_scroll` eases to each heading the way a thumb does.
    """
    html = os.path.splitext(DOSSIER_8)[0] + ".html"
    if not os.path.exists(html):
        print("NOTE: no dossier HTML at %s - the close will fall back to the PDF" % html)
        return
    pg.goto("file:///" + html.replace("\\", "/"), wait_until="domcontentloaded", timeout=60_000)
    pg.add_style_tag(content=DOSSIER_CSS)
    pg.wait_for_timeout(2500)
    for n, label, needle in DOSSIER_STOPS:
        with shot(mark, n, 3.5, label, mode="hold"):
            found = pg.evaluate(
                """(needle) => { const h = [...document.querySelectorAll('h1,h2,h3,h4')]
                     .find(e => (e.textContent || '').toLowerCase().includes(needle));
                   if (!h) return null;
                   window.scrollTo({top: Math.max(0, h.getBoundingClientRect().top + window.scrollY - 40),
                                    behavior: 'smooth'});
                   return (h.textContent || '').trim().slice(0, 60); }""", needle)
            print("   %-28s %s" % (label, found or "NOT FOUND - check the section list"))
            pg.wait_for_timeout(3000)


def _pick_floor(pg, n):
    """Choose a floor VISIBLY, so the viewer sees it being chosen.

    Kendall, 22 Sep: "when we are selecting a floor, we should either use a dropdown or click on that floor level to
    show that it is interactive." The bible has the same rule from 18 Sep - "show that the rows are clickable" -
    because implying an interaction is worth nothing on film.

    Tapping the floor on the tower was tried first and does not work: a raycast at eight different heights up the
    building opened the card every time and selected Ground floor every time, so the tower is not answering the tap
    per floor. The picker is what works, so the picker is what we show.

    A native <select> never renders its menu in a recording, so the press alone would be invisible. What IS visible is
    the drawn cursor travelling to the control and pressing it, and then the tower's own floor band jumping to the
    chosen level. That is the interaction, proved twice on screen.
    """
    sel = pg.locator("#fpick, #fsel").first
    try:
        glide_click(pg, sel, pause=700)          # the hand goes there and presses, in frame
    except Exception:
        pass
    try:
        sel.select_option(str(n), timeout=8000)
    except Exception:
        opts = pg.evaluate("""(n) => { const s = document.querySelector('#fpick, #fsel'); if (!s) return null;
            const o = [...s.options].find(o => new RegExp('\\\\bFloor\\\\s+' + n + '\\\\b').test(o.textContent || ''));
            if (!o) return null; s.value = o.value;
            s.dispatchEvent(new Event('change', {bubbles: true})); return o.textContent.trim(); }""", n)
        if not opts:
            print("   !! floor %d not in the picker - the shot will show whatever was already selected" % n)
    pg.wait_for_timeout(1800)
    print("   floor %d ->" % n, re.sub(r"\s+", " ", (pg.locator("#card").inner_text() or ""))[:110])


def journey9(pg, mark):
    """THE PHARMACY BEAT - one question, answered on one surface, in four shots.

    "Is there a pharmacy nearby?" is the question a buyer actually asks, and until 24 Sep 2026 the honest answer
    was a hedge. Q002 had been needs_data since the bank was written, against a belief that it needed a source we
    did not hold. It needed the DHA Sheryan facility register - already behind the 1,812 clinic pins - and shipped
    the same day as a tenth amenity kind.

    THE NUMBERS ON SCREEN, read off the live map before a frame was shot:
        pharmacies 1437     the chip's own count, verified in probe_map.txt
        727 approximate     the DHA register rounds latitude to 2 dp, so those sit within about 555 m
        46 excluded         hospital in-patient pharmacies, which dispense to wards and are not shops

    MAP ONLY. The building page's LOCATION axis reads district_amenities, which still carries the pre-aligned
    guard, and the two surfaces can disagree on up to ten facilities. Bible 14.3: they do not share a frame until
    they agree, because a viewer cannot tell a deployment lag from an error.
    """
    pg.goto(url("/map"), wait_until="networkidle", timeout=90_000)
    pg.evaluate(CURSOR_JS)
    pg.wait_for_timeout(900)
    mark("open")

    # 1 - the district, nothing lit. She asks the question before the app answers it, so the answer lands as an
    #     answer rather than as a layer that was already on.
    search_pick(pg, DISTRICT_9)
    with shot(mark, 1, 4.0, "the district, no layer on"):
        pg.wait_for_timeout(2600)

    # 2 - THE PRESS. amenity() addresses the chip by data-k and then asserts it carries "on", because a click
    #     landing is not the same as a layer lighting: on 18 Sep a text match found the EV chip in the DOM, clicked
    #     something else, reported success, and put a school card in the EV beat.
    with shot(mark, 2, 5.0, "pharmacies, pressed in frame"):
        amenity(pg, "pharmacy", "pharmacy beat")
        pg.wait_for_timeout(2600)

    # 3 - the pins, held still. This is the shot the beat exists for and it is the one that must not move.
    with shot(mark, 3, 4.5, "1,437 pins, held", mode="hold"):
        pg.wait_for_timeout(3200)

    # 4 - one card, so the claim is a named shop and not a coloured dot. The card carries "position approximate"
    #     on the 727 coarse ones, which is the app telling on itself and is the reason the narration can be honest.
    with shot(mark, 4, 4.5, "one pharmacy, named", mode="hold"):
        try:
            pin = pg.locator('#am .a[data-k="pharmacy"]')
            pin.wait_for(timeout=5000)
            pg.mouse.move(540, 760); pg.wait_for_timeout(900)
        except Exception as e:
            print("   pharmacy card: %s" % str(e)[:70])
        pg.wait_for_timeout(2600)
    mark("end")


def capture(headed, slow):
    from playwright.sync_api import sync_playwright
    os.makedirs(RAW, exist_ok=True)
    marks = {}
    with sync_playwright() as p:
        # the building page is a three.js scene over ground imagery: without the GPU a single screenshot took 28 s
        gpu = ["--use-angle=d3d11", "--ignore-gpu-blocklist", "--enable-gpu"] if VIDEO in (5, 6, 7, 8) else []
        # VIDEO 6 films the app's own PHONE layout: a 540x960 window at a real device scale of 2 records as a sharp 1080x1920.
        # Playwright's emulated device_scale_factor does not do this - its recorder captures CSS pixels, so the page comes out
        # at 540 wide in a corner of the frame. A real window scale is captured in device pixels. Mouse coordinates are CSS px.
        phone = VIDEO == 6          # video 7 films the building page's NATIVE wide layout at 1080x1920
        br = p.chromium.launch(headless=not headed, slow_mo=slow,
                               args=gpu + (["--force-device-scale-factor=2", "--window-size=%d,%d" % (W // 2, H // 2)] if phone else []))
        ctx = (br.new_context(no_viewport=True, record_video_dir=RAW, record_video_size={"width": W, "height": H}) if phone else
               br.new_context(viewport={"width": W, "height": H}, record_video_dir=RAW, record_video_size={"width": W, "height": H}))
        pg = ctx.new_page()
        t0 = time.monotonic()

        def mark(name):
            marks[name] = round(time.monotonic() - t0, 2)
            print("   %-7s %6.2fs" % (name, marks[name]))

        print("recording the journey:")
        try:
            {2: journey2, 3: journey3, 4: journey4, 5: journey5, 6: journey6, 7: journey7, 8: journey8, 9: journey9}.get(VIDEO, journey)(pg, mark)
        finally:
            ctx.close()                       # the video is only written on close
            src = pg.video.path()
            dst = os.path.join(RAW, "journey.webm")
            if os.path.exists(dst):
                os.remove(dst)
            os.replace(src, dst)
            json.dump(marks, open(os.path.join(RAW, "marks.json"), "w"), indent=1)
            json.dump(SHOT_PLAN, open(os.path.join(RAW, "shots.json"), "w"), indent=1)
            if SHOT_PLAN:
                print("   %d shots planned, %d recorded" % (len(SHOT_PLAN), len(shots_from(marks))))
            print("journey -> %s" % os.path.basename(dst))
        br.close()
    fetch_flythrough()


# ---------------------------------------------------------------- the cut

def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


# VIDEO 8 has no SHEET_PDF on purpose: its dossier is SCROLLED inside the journey (shots 12-17) rather than
# appended page by page, because a flip reads as a slideshow and this document is the thing the client keeps.
SHEET_PDF = (os.path.join(ROOT, "dist_dossier", "businessbay_73.pdf") if VIDEO == 7 else
             None) if VIDEO in (3, 4, 5, 6, 7, 8, 9) else os.path.join(ROOT, "data", "sheets", "damac_hills_loreto.pdf" if VIDEO == 2 else "peninsula_one.pdf")
PAPER = "0x0E1310"          # the app's near-black, so the document sits on the film rather than in a window


def close_clip(seconds_per_page=4.0):
    """The three-pager, page by page - the close. Kendall, 17 Sep: "that's like the gold".

    Built by scripts/build_client_sheet.py, which is the same PDF Naj forwards to a client, so the
    video ends on the actual artefact rather than a picture of one.

    Each page is fitted into the TOP of the frame, not the middle: the avatar takes the bottom third,
    and page 1's bottom is the provenance block - where every figure came from - which is the whole
    argument for the document and must not end up behind her head.
    """
    if not SHEET_PDF or not os.path.exists(SHEET_PDF):
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


def freeze_close(last_part):
    """Video 03 ends on the two-bed plan, not a PDF: hold its last frame for TAIL_HOLD so the sign-off lands."""
    png = os.path.join(RAW, "_last.png")
    ff("-sseof", "-0.2", "-i", last_part, "-frames:v", "1", "-update", "1", png)
    clip = os.path.join(RAW, "_close_hold.mp4")
    hold = 3.0 if VIDEO == 7 else 5.0 if VIDEO in (4, 5, 6) else TAIL_HOLD + 2.0   # video 04 already holds 3 s on the labelled frame in the take
    ff("-loop", "1", "-framerate", str(FPS), "-i", png, "-t", str(hold), "-vf", "format=yuv420p",
       "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", "-r", str(FPS), clip)
    print("close: the last frame held %.1fs for the sign-off" % hold)
    return [clip]


OUTNAME = {2: "demo02_damachills_screen.mp4", 3: "demo03_compare_versus_screen.mp4", 4: "demo03_whatshot_screen.mp4",
           5: "demo04_building_screen.mp4", 6: "demo05_view_screen.mp4", 7: "demo06_theview_screen.mp4",
           8: "demo07_habtoor_screen.mp4"}.get(VIDEO, "demo01_businessbay_screen.mp4")


def cut():
    j = os.path.join(RAW, "journey.webm")
    fly = os.path.join(RAW, "flythrough.mp4")
    mk = os.path.join(RAW, "marks.json")
    if not os.path.exists(j):
        sys.exit("no journey recorded yet - run `capture` first")
    marks = json.load(open(mk))
    parts = []
    plan_p = os.path.join(RAW, "shots.json")
    plan = json.load(open(plan_p)) if os.path.exists(plan_p) else {}
    shots = shots_from(marks)
    if shots:
        # ASSEMBLE. Each shot is cut out on its own and the joins are hard cuts; everything between shots is dropped.
        enc2 = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", "-fps_mode", "cfr",
                "-r", str(FPS)]
        vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)
        total = 0.0
        for n, a, b in shots:
            spec = plan.get(str(n)) or {}
            target, dur = spec.get("target"), b - a
            hold = spec.get("mode") == "hold"
            factor = 1.0 if hold else ((dur / target) if (target and dur > target * 1.05) else 1.0)
            start, take = max(0.0, a - 0.05), dur + 0.1
            if hold and target and dur > target:
                start, take = b - target, target                 # the settled tail, not the scramble into it
            p = os.path.join(RAW, "_s%02d.mp4" % n)
            ff("-ss", str(start), "-t", str(take), "-i", j, *enc2, "-vf", ("setpts=PTS/%.4f," % factor) + vf, p)
            out_s = take if hold else (target if factor > 1.0 else dur)
            parts.append(p); total += out_s
            print("   shot %02d %-24s %5.1fs -> %4.1fs  %s" % (n, (spec.get("label") or "")[:24], dur, out_s,
                  "hold" if hold else ("" if factor == 1.0 else "%.1fx" % factor)))
        closing = close_clip() if SHEET_PDF else freeze_close(parts[-1])
        if closing:
            parts.extend(closing)
        listing = os.path.join(RAW, "concat.txt")
        with open(listing, "w", encoding="utf-8") as f:
            for p in parts:
                f.write("file '%s'\n" % p.replace("\\", "/"))
        out = os.path.join(OUT, OUTNAME)
        ff("-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", out)
        secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip() or 0)
        print("assembled %d shots -> %s  (%.1fs, average shot %.1fs)" % (len(shots), out, secs, total / max(1, len(shots))))
        return
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
        o1, o2 = marks.get("orbit_start"), marks.get("orbit_end")
        spans = [(marks[k], marks[k.replace("_start", "_end")]) for k in sorted(marks)
                 if k.startswith("orbit") and k.endswith("_start") and k.replace("_start", "_end") in marks]
        zoom_spans = {(marks[k], marks[k.replace("_start", "_end")]) for k in marks
                      if k.startswith("orbit") and "zoom" in k and k.endswith("_start") and k.replace("_start", "_end") in marks}
        skip_spans = {(marks[k], marks[k.replace("_start", "_end")]) for k in marks
                      if k.startswith("orbit") and "skip" in k and k.endswith("_start") and k.replace("_start", "_end") in marks}
        tgt = lambda sp: 0.0 if sp in skip_spans else (ZOOM_TARGET if sp in zoom_spans else ORBIT_TARGET)
        spans = sorted(sp for sp in spans if sp in skip_spans or (sp[1] - sp[0]) > tgt(sp) * 2)
        if spans:
            # Every 3D turn records in slow motion (the canvas redraws on each drag move) and is played back at
            # speed; everything between the turns stays at 1x. Video 03 opened on one turn; video 04 has two -
            # the district, then the building. Same seek rules as the twin branch below.
            cursor = head
            for n, (s1, s2) in enumerate(spans):
                if s1 - 0.3 - cursor > 0.5:
                    ap = os.path.join(RAW, "_p%d.mp4" % n)
                    ff("-i", j, "-ss", str(cursor), "-t", str(s1 - 0.3 - cursor), *enc, ap); parts.append(ap)
                target = tgt((s1, s2))
                if target == 0.0:             # a skip span: dropped - the film hard-cuts across it
                    print("skip %d: %.1fs of loading cut out" % (n + 1, s2 - s1)); cursor = s2; continue
                factor = (s2 - s1) / target
                a0 = os.path.join(RAW, "_o%d.mp4" % n)
                ff("-ss", str(max(0.0, s1 - 0.3)), "-t", str(s2 + 0.4 - s1), "-i", j,
                   "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an",
                   "-fps_mode", "cfr", "-r", str(FPS),
                   "-vf", "setpts=PTS/%.3f,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (factor, W, H, W, H), a0)
                parts.append(a0)
                print("orbit %d: %.1fs recorded -> %.1fs at %.1fx" % (n + 1, s2 - s1, target, factor))
                cursor = s2 + 0.4
            if last + 1.5 - cursor > 0.5:
                a1 = os.path.join(RAW, "_tail.mp4")
                ff("-i", j, "-ss", str(cursor), "-t", str(last + 1.5 - cursor), *enc, a1); parts.append(a1)
        elif b5 and b6 and (b6 - b5) > TWIN_TARGET * 2:
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
    closing = close_clip() if SHEET_PDF else freeze_close(parts[-1])
    if closing:
        parts.extend(closing)

    listing = os.path.join(RAW, "concat.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % p.replace("\\", "/"))
    out = os.path.join(OUT, OUTNAME)
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
