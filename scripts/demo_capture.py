"""Record the screen side of the Najma demo videos (Kendall, 17 Sep 2026).

Video 01 is a Business Bay client journey: "I want to live in Business Bay" -> "budget 2M, two
bedrooms" -> the filter drill -> a hero building -> its client briefing -> "how far is the nearest
school". The beats and the reasoning are in docs/DEMO_VIDEO_01_BUSINESSBAY.md; each one answers a
question the bank already marks `answered`, so if the app stops answering it the capture breaks
and we find out.

A HeyGen avatar is overlaid on the output afterwards, so nothing here draws an avatar. It does
keep the bottom third of the frame clear of anything that matters.

  probe     open each beat's page and dump what is on it (roles, names, test ids) ->
            data/demo/probe_<beat>.txt, so the selectors below can be filled in from what the app
            actually renders rather than guessed
  capture   record every beat to data/demo/raw/<beat>.webm
  cut       raw beats -> demo01_businessbay_screen.mp4, held on the money shots
  all       probe + capture + cut

THE KEY. Read from NAJMA_CLIENT_KEY in the environment; never passed on the command line (it would
land in shell history) and never printed. It must be a CLIENT_KEY value, not READ_KEY: READ_KEY
opens ~92 owner paths including ones that message contacts, delete data and spend model budget, and
these videos are public. The script refuses to run if the key opens /board, which is the cheapest
test for "you have handed me the owner key by mistake".

Playwright records the viewport only - no address bar, no tab strip, no chrome - so no URL can
reach a frame from here. That is a property of this pipeline, not of the key; a manual screen
recording would not be safe in the same way.

Options: --beats 1,3,7 (only these), --headed (watch it run), --slow <ms> (slow the cursor down).
"""
import argparse, os, subprocess, sys, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "demo")
RAW = os.path.join(OUT, "raw")

APP = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
W, H = 1080, 1920                  # 9:16
SAFE_BOTTOM = 0.30                 # the avatar sits here; keep the answer above it

# Each beat: the route, what to do on it, and how long to hold the result on screen. `actions` is a
# list of (kind, argument) filled in from `probe` output - the app's own markup, not a guess.
BEATS = [
    {"n": 1, "t": 5.0, "route": "/map",     "q": "Q067", "hold": 1.5,
     "ask": "I'm thinking about Business Bay - what's it actually like?",
     "actions": [("goto_area", "Business Bay")]},
    {"n": 2, "t": 7.0, "route": "/skyline", "q": "Q039", "hold": 2.0,
     "ask": None,
     "actions": [("tilt", "3d"), ("colour_by", "status")]},
    {"n": 3, "t": 8.0, "route": "/home",    "q": "Q074", "hold": 2.0,
     "ask": "My budget's two million and I need two bedrooms.",
     "actions": [("filter_budget", 2_000_000), ("filter_beds", 2)]},
    {"n": 4, "t": 8.0, "route": "/home",    "q": "Q098", "hold": 2.5,
     "ask": None,
     "actions": [("apply_filter", None)]},
    {"n": 5, "t": 10.0, "route": "/skyline", "q": "Q048", "hold": 2.5,
     "ask": "Show me the best one.",
     "actions": [("click_building", "<HERO>"), ("open_panel", None)]},
    {"n": 6, "t": 8.0, "route": "<REPORT>", "q": None, "hold": 2.0,
     "ask": None,
     "actions": [("scroll_brief", None)]},
    {"n": 7, "t": 6.0, "route": "/map",     "q": "Q028", "hold": 2.0,
     "ask": "And how far is the nearest school?",
     "actions": [("layer_on", "schools"), ("nearest_card", None)]},
]


def key():
    """NAJMA_CLIENT_KEY, from the environment or, failing that, straight out of the registry.

    `setx` writes the user environment to HKCU\\Environment at once, but processes already running
    keep the environment they started with - so a key set after this terminal's parent started is
    invisible to os.environ until something restarts. Reading the registry directly picks it up
    immediately, and keeps the value inside this process: it is never printed, never passed on a
    command line, and never has to be pasted into a chat to reach the capture.
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
                 "Set it to a CLIENT_KEY value - not READ_KEY - with:\n"
                 '  setx NAJMA_CLIENT_KEY "<value>"')
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
        return          # can't reach it; the capture will fail on its own and say so
    if code == 200:
        sys.exit("refusing to run: this key opens /board, so it is READ_KEY. Use a CLIENT_KEY value.")


def url(route):
    return "%s%s%s" % (APP, route, "" if route.startswith("/r/") else "?key=" + key())


def probe(beats):
    """Dump what each beat's page actually renders, so the selectors above stop being guesses."""
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": W, "height": H}).new_page()
        for b in beats:
            if b["route"].startswith("<"):
                print("beat %d: route not decided yet (%s) - skipped" % (b["n"], b["route"]))
                continue
            pg.goto(url(b["route"]), wait_until="networkidle", timeout=60_000)
            path = os.path.join(OUT, "probe_%d.txt" % b["n"])
            with open(path, "w", encoding="utf-8") as f:
                f.write("beat %d  %s  %s\n\n" % (b["n"], b["route"], b["q"] or ""))
                f.write(pg.locator("body").aria_snapshot())
            pg.screenshot(path=os.path.join(OUT, "probe_%d.png" % b["n"]), full_page=False)
            print("beat %d -> %s" % (b["n"], os.path.basename(path)))
        br.close()


def capture(beats, headed, slow):
    from playwright.sync_api import sync_playwright
    os.makedirs(RAW, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(headless=not headed, slow_mo=slow)
        for b in beats:
            if b["route"].startswith("<"):
                print("beat %d: route not decided yet (%s) - skipped" % (b["n"], b["route"]))
                continue
            ctx = br.new_context(viewport={"width": W, "height": H},
                                 record_video_dir=RAW,
                                 record_video_size={"width": W, "height": H})
            pg = ctx.new_page()
            pg.goto(url(b["route"]), wait_until="networkidle", timeout=60_000)
            for kind, arg in b["actions"]:
                run_action(pg, kind, arg)
            pg.wait_for_timeout(int(b["hold"] * 1000))
            ctx.close()          # the video is only written on close
            src = pg.video.path()
            dst = os.path.join(RAW, "beat%02d.webm" % b["n"])
            os.replace(src, dst)
            print("beat %d -> %s" % (b["n"], os.path.basename(dst)))
        br.close()


def run_action(pg, kind, arg):
    """One storyboard action. Filled in from probe output - see docs/DEMO_VIDEO_01_BUSINESSBAY.md.

    Cursor moves are deliberate, not teleported: a click that jumps straight to its target reads as
    automation on camera, which is the one thing these videos must not look like.
    """
    raise NotImplementedError(
        "action %r is not wired up yet - run `probe` first and fill it in from the app's markup" % kind)


def cut(beats):
    """Raw beats -> one 9:16 file, in order, with the splash grade."""
    listing = os.path.join(OUT, "concat.txt")
    have = [b for b in beats if os.path.exists(os.path.join(RAW, "beat%02d.webm" % b["n"]))]
    if not have:
        sys.exit("nothing captured yet - run `capture` first")
    with open(listing, "w", encoding="utf-8") as f:
        for b in have:
            f.write("file '%s'\n" % os.path.join(RAW, "beat%02d.webm" % b["n"]).replace("\\", "/"))
    out = os.path.join(OUT, "demo01_businessbay_screen.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing,
                    "-vf", "scale=%d:%d,eq=contrast=1.06:saturation=1.04" % (W, H),
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out], check=True)
    print("wrote %s" % out)
    missing = [b["n"] for b in beats if b not in have]
    if missing:
        print("NOTE: beats %s are missing from this cut" % ", ".join(str(m) for m in missing))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["probe", "capture", "cut", "all"])
    ap.add_argument("--beats", help="only these, e.g. 1,3,7")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--slow", type=int, default=0, help="ms between actions")
    a = ap.parse_args()

    beats = BEATS
    if a.beats:
        want = {int(x) for x in a.beats.split(",")}
        beats = [b for b in BEATS if b["n"] in want]

    if a.command in ("probe", "capture", "all"):
        refuse_owner_key(key())
    if a.command in ("probe", "all"):
        probe(beats)
    if a.command in ("capture", "all"):
        capture(beats, a.headed, a.slow)
    if a.command in ("cut", "all"):
        cut(beats)


if __name__ == "__main__":
    main()
