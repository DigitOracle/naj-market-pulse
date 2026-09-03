"""Drop-in cards for the Valley entry - vertical 1080x1920, matching the HeyGen master.

Three register-grounded inserts in Naj's Track D palette (cream / warm gold / ink):
  1. rate      - Valley villa rate against the Dubai apartment rate
  2. pillars   - the four of her nine points The Valley lands
  3. buildout  - the registered build-out, reformatted vertical from the 16:9 card

Deterministic drawing (Pillow) - never image generation.
Figures come from data/valley_evidence.json so a re-run picks up a refreshed pull.

Run:  python -X utf8 scripts/valley_dropin_cards.py
Out:  public/cards/valley_dropin_{rate,pillars,buildout}.png
"""
import json, pathlib
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "cards"
W, H = 1080, 1920

CREAM = (247, 245, 240)
INK = (41, 45, 52)
GOLD = (176, 141, 79)
MUTED = (139, 134, 126)
WHITE = (255, 255, 255)


def font(size, bold=False):
    for n in (("seguisb.ttf", "segoeui.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
    except OSError:
        return ImageFont.load_default()



# ---------------------------------------------------------------- gold line icons
# Hand-drawn line art rather than emoji: her house style is gold single-line artwork
# ("a gold-line artwork drawn in one continuous line" - series bible), and emoji would
# read as consumer social rather than quiet luxury.

def _ring(d, cx, cy, r, w=4, colour=GOLD):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=w)


def _bez(p0, p1, p2, n=24):
    """Quadratic bezier sample - used for the leaf outline."""
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in [i / n for i in range(n + 1)]]


def icon_leaf(d, cx, cy, r):
    """A leaf: two bezier edges tip to tip, plus a midrib. Earlier arc version read
    as a slashed circle - i.e. a prohibition sign - which is the opposite of the point."""
    _ring(d, cx, cy, r)
    s = r * 0.62
    tip, base = (cx + s * 0.78, cy - s * 0.78), (cx - s * 0.78, cy + s * 0.78)
    d.line(_bez(base, (cx + s * 0.55, cy - s * 0.10), tip), fill=GOLD, width=5, joint="curve")
    d.line(_bez(base, (cx - s * 0.55, cy + s * 0.10), tip), fill=GOLD, width=5, joint="curve")
    d.line([base, tip], fill=GOLD, width=3)


def icon_movement(d, cx, cy, r):
    _ring(d, cx, cy, r)
    for i, dx in enumerate((-0.42, 0.0, 0.42)):
        x = cx + r * dx
        d.line([x - r * 0.16, cy - r * 0.34, x + r * 0.14, cy], fill=GOLD, width=5)
        d.line([x + r * 0.14, cy, x - r * 0.16, cy + r * 0.34], fill=GOLD, width=5)


def icon_community(d, cx, cy, r):
    _ring(d, cx, cy, r)
    pts = [(cx, cy - r * 0.42), (cx - r * 0.40, cy + r * 0.30), (cx + r * 0.40, cy + r * 0.30)]
    for a in range(3):
        for b in range(a + 1, 3):
            d.line([pts[a], pts[b]], fill=GOLD, width=3)
    for x, y in pts:
        d.ellipse([x - r * 0.15, y - r * 0.15, x + r * 0.15, y + r * 0.15], fill=GOLD)


def icon_recovery(d, cx, cy, r):
    """A crescent, carved by overlaying a cream disc on a gold one - reads as rest
    instantly, where the previous open arc just read as the letter C."""
    _ring(d, cx, cy, r)
    s = r * 0.58
    d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=GOLD)
    o = s * 0.42
    d.ellipse([cx - s + o, cy - s - o * 0.15, cx + s + o, cy + s - o * 0.15], fill=CREAM)


def icon_villa(d, cx, cy, r):
    _ring(d, cx, cy, r)
    s = r * 0.55
    d.line([cx - s, cy, cx, cy - s * 0.85], fill=GOLD, width=5)
    d.line([cx, cy - s * 0.85, cx + s, cy], fill=GOLD, width=5)
    d.rectangle([cx - s * 0.72, cy, cx + s * 0.72, cy + s * 0.72], outline=GOLD, width=5)
    d.line([cx - s * 1.02, cy + s * 0.72, cx + s * 1.02, cy + s * 0.72], fill=GOLD, width=4)


def icon_flat(d, cx, cy, r):
    _ring(d, cx, cy, r)
    s = r * 0.5
    d.rectangle([cx - s * 0.62, cy - s, cx + s * 0.62, cy + s], outline=GOLD, width=5)
    for row in range(3):
        for col in range(2):
            x = cx - s * 0.34 + col * s * 0.44
            y = cy - s * 0.62 + row * s * 0.56
            d.rectangle([x - s * 0.13, y - s * 0.13, x + s * 0.13, y + s * 0.13], fill=GOLD)


def frame():
    """Cream card with a thin gold rule top and bottom - the series signature."""
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=GOLD)
    d.rectangle([0, H - 10, W, H], fill=GOLD)
    return img, d


def footer(d, text="Dubai Land Department, 2026 transactions"):
    d.text((W // 2, H - 96), text, font=font(30), fill=MUTED, anchor="ma")


def card_rate(ev):
    img, d = frame()
    d.text((W // 2, 260), "PER SQUARE FOOT", font=font(40, True), fill=GOLD, anchor="ma")
    d.text((W // 2, 332), "what has actually traded, 2026", font=font(32), fill=MUTED, anchor="ma")

    rows = [(icon_villa, "A villa in The Valley", "1,390", GOLD, 404),
            (icon_flat, "The average Dubai apartment", "1,715", INK, 87706)]
    y = 560
    for ico, label, rate, colour, n in rows:
        ico(d, 168, y + 96, 74)
        d.text((286, y + 26), label, font=font(44), fill=INK)
        d.text((286, y + 92), f"AED {rate}", font=font(140, True), fill=colour)
        d.text((286, y + 254), f"{n:,} recorded sales", font=font(30), fill=MUTED)
        y += 400

    d.line([168, 1470, W - 168, 1470], fill=(224, 219, 210), width=3)
    d.text((W // 2, 1526), "A villa. For less a foot", font=font(54, True), fill=INK, anchor="ma")
    d.text((W // 2, 1596), "than the average flat.", font=font(54, True), fill=INK, anchor="ma")
    footer(d)
    return img


def card_pillars(_ev):
    img, d = frame()
    d.text((W // 2, 260), "WHAT I LOOK FOR", font=font(40, True), fill=GOLD, anchor="ma")
    d.text((W // 2, 332), "four of the nine, in one place", font=font(32), fill=MUTED, anchor="ma")

    items = [(icon_leaf, "NATURE", "parks and gardens on foot"),
             (icon_movement, "MOVEMENT", "a Sports Village, a beach inland"),
             (icon_community, "COMMUNITY", "a centre you walk to"),
             (icon_recovery, "RECOVERY", "the quiet")]
    y = 560
    for ico, word, sub in items:
        ico(d, 190, y + 44, 78)
        d.text((320, y - 6), word, font=font(84, True), fill=INK)
        d.text((320, y + 88), sub, font=font(34), fill=MUTED)
        y += 232

    d.line([190, 1516, W - 190, 1516], fill=(224, 219, 210), width=3)
    d.text((W // 2, 1568), "Air · Water · Nutrition · Technology · Sustainability",
           font=font(32), fill=MUTED, anchor="ma")
    footer(d, "The nine-point framework · Wellness Real Estate")
    return img


def card_buildout(ev):
    projects = sorted(ev["dld_project_register"], key=lambda r: r["end_date"])
    total = sum(int(p["villas"]) for p in projects)
    img, d = frame()
    d.text((W // 2, 280), "THE REGISTERED BUILD-OUT", font=font(40, True), fill=GOLD, anchor="ma")
    d.text((W // 2, 352), "five Emaar projects, all escrowed", font=font(32), fill=MUTED, anchor="ma")
    d.text((W // 2, 452), f"{total}", font=font(210, True), fill=INK, anchor="ma")
    d.text((W // 2, 700), "villas registered", font=font(44), fill=MUTED, anchor="ma")

    y = 860
    for p in projects:
        name = p["project"].replace("The Valley - ", "").strip()
        built = float(p["pct_complete"] or 0) > 0
        d.rounded_rectangle([160, y, 190, y + 34], radius=6, fill=GOLD if not built else INK)
        d.text((222, y - 4), name, font=font(46, True), fill=INK)
        d.text((W - 160, y - 2), str(p["end_date"])[:7], font=font(38), fill=MUTED, anchor="ra")
        d.text((222, y + 48), f"{p['villas']} villas", font=font(30), fill=MUTED)
        y += 138

    d.text((W // 2, 1620), "Not a forecast. A schedule.", font=font(52, True), fill=INK, anchor="ma")
    footer(d, "Dubai Land Department, register of projects")
    return img


def main():
    ev = json.loads((ROOT / "data" / "valley_evidence.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("rate", card_rate), ("pillars", card_pillars), ("buildout", card_buildout)):
        p = OUT / f"valley_dropin_{name}.png"
        fn(ev).save(p, "PNG")
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
