"""The Sobha tour's opening: an animated data sheet a narrator speaks over, then the tour - v14, 25 Sep 2026.

Kendall: "each of these kind of pop up ... 2007 pops up, and then she speaks on that card ... she's going to stand on the
right-hand side, and on the left-hand side each of these cards will pop up, and the card will stay there for five seconds
maximum ... add some icons, add a little bit of flavor."

  0.0 - 3.0 s   title: SOBHA / in Dubai, over a slow push-in on the tour's opening aerial (left side darkened for text,
                right side left light and clear for the presenter)
  then six cards, one at a time, on the LEFT ~58% of the 1080 x 1350 frame, each CARD_S long (in 0.45 s, hold, out 0.4 s):
    2007      first project registered in Dubai                    calendar icon
    49        projects on the Dubai Land Department register      register (clipboard) icon, counts up
    19·20·10  completed · under construction · off-plan           stacked bar in the tour's legend colours
    35,500+   homes registered (6,600+ delivered)                 house icon, counts up, delivered-vs-pipeline bar
    8         communities on this tour                            map pin
    450 m     SkyParks, the tallest in the pipeline               tower silhouette with a height tick, counts up
  a row of six progress dots under the card says where the narrator is.
Figures: data/identity/sobha_projects.json (DLD register, the eight Sobha group entities, Dubai only) - recomputed on every run,
so the card never drifts from the register. Timings go to data/media/sobha/intro_timings.json for the narration script.
Output: data/media/sobha/sobha_intro_4x5.mp4, and with --join <tour.mp4> <out.mp4> the intro cross-faded into the tour.
v15: --join also appends a 7 s closing card (build_outro: communities, buildings modelled, register coverage from the audit,
sources, "Prepared by DigitAlchemy") cross-faded over the tour's last aerial.
Usage: python scripts/sobha_intro.py [--join tour.mp4 out.mp4]
"""
import json, math, os, shutil, subprocess, sys, tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "data", "media", "sobha")
BG = os.path.join(MEDIA, "cards", "intro_bg.png")
FF = r"C:\Users\kwils\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
W, H, FPS = 1080, 1350, 30
TITLE_S, CARD_S, TAIL_S = 3.0, 4.5, 0.6
GOLD = (197, 165, 106); WHITE = (255, 255, 255); GREY = (176, 188, 198); NAVY = (8, 20, 28); PANEL = (14, 30, 42)
AMBER = (255, 122, 16); PALE = (216, 221, 228); OFF = (120, 132, 142)
CARD_X, CARD_W = 60, 560


def font(bold, size):
    return ImageFont.truetype(r"C:\Windows\Fonts\%s" % ("segoeuib.ttf" if bold else "segoeui.ttf"), size)


def figures():
    P = json.load(open(os.path.join(ROOT, "data", "identity", "sobha_projects.json"), encoding="utf-8"))["projects"]
    st = [p.get("status") for p in P]
    units = sum(int(p.get("units") or 0) for p in P)
    done_u = sum(int(p.get("units") or 0) for p in P if p.get("status") == "FINISHED")
    first = min(str(p.get("start"))[:4] for p in P if p.get("start"))
    n_done = st.count("FINISHED"); n_uc = st.count("ACTIVE"); n_off = len(P) - n_done - n_uc
    return {"first": first, "n": len(P), "done": n_done, "uc": n_uc, "off": n_off,
            "units": units, "units_done": done_u}


def ease(t):
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3


# ---- icons: gold line drawings in a 120 px box at (x, y) --------------------------------------------------------------
def icon_calendar(d, x, y, a):
    c = GOLD + (a,)
    d.rounded_rectangle((x + 8, y + 20, x + 112, y + 112), 12, outline=c, width=6)
    d.line((x + 8, y + 46, x + 112, y + 46), fill=c, width=6)
    for k in (36, 84):
        d.line((x + k, y + 8, x + k, y + 32), fill=c, width=7)
    for r in range(2):
        for q in range(3):
            d.rounded_rectangle((x + 26 + q * 26, y + 60 + r * 24, x + 40 + q * 26, y + 72 + r * 24), 3, fill=c)


def icon_register(d, x, y, a):
    c = GOLD + (a,)
    d.rounded_rectangle((x + 18, y + 14, x + 102, y + 114), 10, outline=c, width=6)
    d.rounded_rectangle((x + 40, y + 4, x + 80, y + 24), 6, fill=c)
    for k in range(4):
        d.line((x + 36, y + 46 + k * 18, x + 84, y + 46 + k * 18), fill=c, width=5)


def icon_house(d, x, y, a):
    c = GOLD + (a,)
    d.line((x + 6, y + 58, x + 60, y + 10, x + 114, y + 58), fill=c, width=7, joint="curve")
    d.rectangle((x + 22, y + 52, x + 98, y + 112), outline=c, width=6)
    d.rectangle((x + 50, y + 76, x + 70, y + 112), fill=c)


def icon_pin(d, x, y, a):
    c = GOLD + (a,)
    d.ellipse((x + 22, y + 4, x + 98, y + 80), outline=c, width=7)
    d.polygon([(x + 30, y + 62), (x + 60, y + 116), (x + 90, y + 62)], fill=c)
    d.ellipse((x + 44, y + 26, x + 76, y + 58), fill=c)


def icon_tower(d, x, y, a):
    c = GOLD + (a,)
    d.polygon([(x + 44, y + 116), (x + 50, y + 16), (x + 62, y + 2), (x + 74, y + 16), (x + 80, y + 116)], outline=c, width=6)
    for k in range(5):
        d.line((x + 54, y + 34 + k * 16, x + 70, y + 34 + k * 16), fill=c, width=3)
    d.line((x + 96, y + 4, x + 96, y + 116), fill=c, width=3)
    for yy in (4, 116):
        d.line((x + 88, y + yy, x + 104, y + yy), fill=c, width=3)


def icon_status(d, x, y, a):
    c = GOLD + (a,)
    d.ellipse((x + 10, y + 10, x + 110, y + 110), outline=c, width=7)
    d.line((x + 36, y + 62, x + 54, y + 80, x + 86, y + 42), fill=c, width=8, joint="curve")


def countup(value, t, fmt="{:,}"):
    return fmt.format(int(round(value * ease(t / 0.9))))


def draw_card(layer, k, cards, t, F):
    """card k at time t since its start (seconds); alpha / slide from the easing."""
    a_in = ease(t / 0.45); a_out = 1 - ease((t - (CARD_S - 0.4)) / 0.4) if t > CARD_S - 0.4 else 1.0
    a = max(0.0, min(a_in, a_out))
    if a <= 0:
        return
    dx = int((1 - a_in) * -60)
    card = Image.new("RGBA", (CARD_W, 520), (0, 0, 0, 0)); d = ImageDraw.Draw(card)
    A = int(255 * a)
    d.rounded_rectangle((0, 0, CARD_W - 1, 519), 26, fill=PANEL + (int(232 * a),))
    d.rounded_rectangle((0, 0, 10, 519), 4, fill=GOLD + (A,))
    c = cards[k]
    c["icon"](d, 40, 40, A)
    big = c["value"](t) if callable(c["value"]) else c["value"]
    fs = 124 if len(big) <= 5 else (100 if len(big) <= 8 else 84)
    d.text((40, 190), big, font=F(True, fs), fill=WHITE + (A,))
    y = 190 + fs + 34
    for line in c["label"]:
        d.text((42, y), line, font=F(False, 36), fill=GREY + (A,)); y += 48
    if c.get("bar"):
        c["bar"](d, 42, 460, CARD_W - 84, A, t)
    layer.alpha_composite(card, (CARD_X + dx, 470))


OUTRO_S = 7.0


def build_outro():
    """Closing card (v15): what the tour showed and where every number came from, over the tour's last aerial.
    Counts from data/board/sobha_audit.json, so the card says what the model actually holds."""
    au = json.load(open(os.path.join(ROOT, "data", "board", "sobha_audit.json"), encoding="utf-8"))["totals"]
    stops = json.load(open(os.path.join(MEDIA, "tour_stops.json"), encoding="utf-8"))["stops"]
    bg = Image.open(os.path.join(MEDIA, "cards", "outro_bg.png")).convert("RGBA").crop((0, 0, W, int(H * 0.88))).resize((W, H))
    shade = Image.new("RGBA", (W, H), NAVY + (205,))
    base = Image.alpha_composite(bg, shade)
    rows = [("%d" % len(stops), "communities toured"), ("%d" % au["footprints"], "Sobha buildings modelled"),
            ("%d of %d" % (au["in_twin"], au["projects"]), "register projects in the model")]
    src = ["Dubai Land Department project register  ·  Dubai Municipality building permits",
           "RTA  ·  KHDA  ·  DHA  ·  OpenStreetMap  ·  Sobha Realty"]
    tmp = tempfile.mkdtemp(prefix="sobha_outro_")
    n = int(OUTRO_S * FPS)
    for f in range(n):
        t = f / FPS
        fr = base.copy(); d = ImageDraw.Draw(fr)
        a = ease(t / 0.6); A = int(255 * a)
        d.rectangle((CARD_X, 250, CARD_X + 8, 370), fill=GOLD + (A,))
        d.text((CARD_X + 30, 236), "SOBHA", font=font(True, 88), fill=WHITE + (A,))
        d.text((CARD_X + 34, 340), "in Dubai  ·  the tour", font=font(False, 36), fill=GREY + (A,))
        for k, (v, l) in enumerate(rows):
            ak = int(255 * ease((t - 0.5 - 0.45 * k) / 0.5))
            y = 470 + k * 170
            d.text((CARD_X + 30, y), v, font=font(True, 96), fill=WHITE + (ak,))
            d.text((CARD_X + 34, y + 112), l, font=font(False, 34), fill=GREY + (ak,))
        a2 = int(255 * ease((t - 2.2) / 0.6))
        d.text((CARD_X + 34, 1000), "Sources", font=font(True, 26), fill=GOLD + (a2,))
        for k, line in enumerate(src):
            d.text((CARD_X + 34, 1040 + k * 36), line, font=font(False, 24), fill=GREY + (a2,))
        d.text((CARD_X + 34, 1200), "Prepared by DigitAlchemy®  ·  contact@digitalabbot.io", font=font(False, 24), fill=(150, 162, 172, a2))
        fr.convert("RGB").save(os.path.join(tmp, "o%04d.jpg" % f), quality=93)
    out = os.path.join(MEDIA, "sobha_outro_4x5.mp4")
    subprocess.run([FF, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(tmp, "o%04d.jpg"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    fig = figures()
    F = lambda b, s: font(b, s)

    def status_bar(d, x, y, w, A, t):
        tot = fig["done"] + fig["uc"] + fig["off"]; g = ease(t / 1.0); cx = x
        for n, col in ((fig["done"], PALE), (fig["uc"], AMBER), (fig["off"], OFF)):
            seg = int(w * n / tot * g); d.rectangle((cx, y, cx + seg, y + 22), fill=col + (A,)); cx += seg

    def homes_bar(d, x, y, w, A, t):
        g = ease(t / 1.0)
        d.rectangle((x, y, x + int(w * g), y + 22), fill=OFF + (A,))
        d.rectangle((x, y, x + int(w * fig["units_done"] / fig["units"] * g), y + 22), fill=PALE + (A,))

    cards = [
        {"key": "first", "value": fig["first"], "label": ["first project registered", "in Dubai"], "icon": icon_calendar},
        {"key": "projects", "value": lambda t: countup(fig["n"], t), "label": ["projects on the Dubai Land", "Department register"], "icon": icon_register},
        {"key": "status", "value": "%d · %d · %d" % (fig["done"], fig["uc"], fig["off"]), "label": ["completed · under construction", "· off-plan"], "icon": icon_status, "bar": status_bar},
        {"key": "homes", "value": lambda t: countup(int(fig["units"] // 500 * 500), t) + "+", "label": ["homes registered", "(%s+ delivered)" % "{:,}".format(fig["units_done"] // 100 * 100)], "icon": icon_house, "bar": homes_bar},
        {"key": "tour", "value": "8", "label": ["communities on this tour"], "icon": icon_pin},
        {"key": "tallest", "value": lambda t: countup(450, t) + " m", "label": ["Sobha SkyParks, the tallest", "in the pipeline"], "icon": icon_tower},
    ]
    total = TITLE_S + CARD_S * len(cards) + TAIL_S
    nfr = int(round(total * FPS))
    bg0 = Image.open(BG).convert("RGB")
    # the tour frame carries the legend band at the bottom: work from the top 88% only
    bg0 = bg0.crop((0, 0, W, int(H * 0.88)))
    shade = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line((x, 0, x, H), fill=int(215 * max(0.0, 1 - x / (W * 0.72)) ** 0.8 + 25))
    tmp = tempfile.mkdtemp(prefix="sobha_intro_")
    for f in range(nfr):
        t = f / FPS
        z = 1.18 + 0.10 * (t / total)
        bw, bh = int(W * z), int(H * z)
        bg = bg0.resize((bw, bh), Image.BILINEAR) if f % 2 == 0 or f == 0 else bg
        ox = int((bw - W) * 0.62); oy = int((bh - H) * 0.40)
        frame = bg.crop((ox, oy, ox + W, oy + H)).convert("RGBA")
        frame = Image.composite(Image.new("RGBA", (W, H), NAVY + (255,)), frame, shade)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        # title: big in the first 3 s, then held small top-left
        tt = ease(t / 0.8)
        if t < TITLE_S:
            A = int(255 * tt); s = 150
            d.rectangle((CARD_X, 520, CARD_X + 10, 780), fill=GOLD + (A,))
            d.text((CARD_X + 36, 500), "SOBHA", font=F(True, s), fill=WHITE + (A,))
            d.text((CARD_X + 40, 690), "in Dubai", font=F(False, 60), fill=GREY + (A,))
        else:
            d.rectangle((CARD_X, 250, CARD_X + 8, 370), fill=GOLD)
            d.text((CARD_X + 30, 236), "SOBHA", font=F(True, 88), fill=WHITE)
            d.text((CARD_X + 34, 340), "in Dubai  ·  at a glance", font=F(False, 36), fill=GREY)
            k = int((t - TITLE_S) // CARD_S)
            if k < len(cards):
                draw_card(layer, k, cards, t - TITLE_S - k * CARD_S, F)
            for j in range(len(cards)):
                cx = CARD_X + 14 + j * 30
                d.ellipse((cx, 1030, cx + 14, 1044), fill=(GOLD + (255,)) if j == min(k, len(cards) - 1) else (GREY + (110,)))
        frame.alpha_composite(layer)
        frame.convert("RGB").save(os.path.join(tmp, "i%04d.jpg" % f), quality=93)
    out = os.path.join(MEDIA, "sobha_intro_4x5.mp4")
    subprocess.run([FF, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(tmp, "i%04d.jpg"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    tim = {"total_s": total, "title": [0.0, TITLE_S], "cards": [{"key": c["key"], "on": round(TITLE_S + k * CARD_S, 2), "off": round(TITLE_S + (k + 1) * CARD_S, 2),
           "value": c["value"](CARD_S) if callable(c["value"]) else c["value"], "label": " ".join(c["label"])} for k, c in enumerate(cards)], "figures": fig}
    json.dump(tim, open(os.path.join(MEDIA, "intro_timings.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("intro %.1f s, %d frames -> %s" % (total, nfr, out))
    for c in tim["cards"]:
        print("  %5.1f-%5.1f s  %-10s %s" % (c["on"], c["off"], c["value"], c["label"]))
    if "--join" in sys.argv:
        tour, joined = sys.argv[sys.argv.index("--join") + 1], sys.argv[sys.argv.index("--join") + 2]
        off = total - 0.8
        tour_s = float(subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", tour],
                                      capture_output=True, text=True).stdout.strip())
        outro = build_outro()
        off2 = off + tour_s - 1.0
        subprocess.run([FF, "-y", "-loglevel", "error", "-i", out, "-i", tour, "-i", outro, "-filter_complex",
                        "[0:v][1:v]xfade=transition=fade:duration=0.8:offset=%.2f[a];[a][2:v]xfade=transition=fade:duration=1.0:offset=%.2f,format=yuv420p[v]" % (off, off2),
                        "-map", "[v]", "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", joined], check=True)
        print("joined -> %s" % joined)


if __name__ == "__main__":
    main()
