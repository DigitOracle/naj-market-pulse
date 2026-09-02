"""Unit-type card sheets for The Symphony by Imtiaz - A4 landscape PNG + PDF per type + combined PDF.

v2 (2 Sep 2026): the plan image is the DEVELOPER'S OWN PLATE excerpt (deck pages saved in data/brochure/floorplan_pages,
cut per type into data/cards/dev_<Type>.png) with the whole-floor plate as context. Our Revit schematic is NOT shown on
the card until the generator's corridor-access/door logic is fixed (see bible SS VII step 3 note).
Room schedule still comes from the Revit model (data/cards/card_rooms.json) and is labelled indicative.
"""
import collections, json, os, sys
from PIL import Image, ImageDraw, ImageFont

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CARDS_DIR = os.path.join(ROOT, "data", "cards")
ENG = r"C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Client_Engagements\Imtiaz\02_Execution\04_Golden_Building_Symphony\02_Revit\unit_cards"
OUT = os.path.join(ENG, "sheets")
os.makedirs(OUT, exist_ok=True)
TEAL, GOLD, INK, MUT, PAPER = (10, 79, 74), (197, 165, 106), (28, 32, 30), (110, 118, 114), (250, 249, 246)


def F(name, size):
    return ImageFont.truetype(r"C:\Windows\Fonts\%s.ttf" % name, size)


H1, H2, B, SM, XS = F("georgia", 74), F("georgia", 44), F("segoeui", 30), F("segoeui", 24), F("segoeui", 21)
W, H = 3508, 2480

rooms = json.load(open(os.path.join(CARDS_DIR, "card_rooms.json")))
avail = json.load(open(os.path.join(ROOT, "data", "avail", "imtiaz_2026-08-28.json")))
sheet_date = avail.get("sheet_date", "")
by_type = collections.defaultdict(list)
for p in avail["projects"]:
    for u in p["units"]:
        by_type[u[1]].append(u)

# legend as read from the developer plates (deck p15-p22 key: MASTER SUITE / 1 BEDROOM / 2-BEDROOM / larger types)
LEGEND = [("Master suite / larger units (brown)", (176, 137, 104)), ("1 bedroom (cream)", (236, 227, 205)),
          ("2 bedroom (pink)", (196, 168, 172)), ("Core, lifts, stairs (grey)", (150, 150, 150)),
          ("Balconies / terraces (light grey)", (222, 222, 222)), ("Pool (blue)", (130, 190, 210))]

CARDS = [
    ("MasterSuite_1BR", "Master Suite - 1 Bedroom", "1101", "11th floor plate (typical 11th-21st odd)", "Floors 10-22 - west wing and NW corner - 3 per floor", "1 B/R",
     "West and north faces - Park / Community per the developer compass"),
    ("1BR", "1 Bedroom", "1102", "11th floor plate (typical 11th-21st odd)", "Floors 10-33 - 6-7 per floor", "1 B/R",
     "North and east faces - Burj Khalifa & Lagoon side on the north face"),
    ("2BR", "2 Bedroom", "1104", "11th floor plate (typical 11th-21st odd)", "Floors 10-34 - 4 per floor (corners)", "2 B/R", "Corner units - two aspects"),
    ("3BR", "3 Bedroom", "2401", "24th floor plate (24, 26, 28, 30)", "Floors 24, 26, 28, 30 - 2 per floor", "3 B/R",
     "North-west wrap - Park + Burj Khalifa & Lagoon"),
    ("4BR", "4 Bedroom", "3201", "32nd floor plate", "Floor 32 - 2 units", "4 B/R", "North-west wrap - three aspects"),
    ("4BR_Duplex_lower", "4 Bedroom Duplex - lower level (33rd)", "3307L", "33rd floor plate", "Floors 33-34 - unit 3307 - private pool terrace",
     "4 B/R Duplex", "West wing + NW corner - Skyline, Lagoon & Cityscape (developer claim)"),
    ("4BR_Duplex_upper", "4 Bedroom Duplex - upper level (34th)", "3307U", "34th floor plate", "Floors 33-34 - unit 3307 - planted upper terrace",
     "4 B/R Duplex", "West wing + NW corner - Skyline, Lagoon & Cityscape (developer claim)"),
]


def fit(img, box_w, box_h):
    r = min(box_w / img.width, box_h / img.height)
    return img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)


def wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


pages = []
for key, title, unit, plate, floors, sheet_type, view in CARDS:
    dev_p = os.path.join(CARDS_DIR, "dev_%s.png" % key)
    ctx_p = os.path.join(CARDS_DIR, "devfloor_%s.png" % key)
    if not os.path.exists(dev_p):
        print("missing", dev_p)
        continue
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 300], fill=TEAL)
    d.rectangle([0, 300, W, 312], fill=GOLD)
    d.text((120, 70), "THE SYMPHONY BY IMTIAZ", font=H1, fill=(255, 255, 255))
    d.text((120, 175), "Meydan Horizon - Bukadra - Dubai   |   Unit type card", font=B, fill=(220, 228, 226))
    d.text((W - 120 - d.textlength(title, font=H2), 120), title, font=H2, fill=GOLD)

    # main image: developer plate excerpt
    plan = fit(Image.open(dev_p).convert("RGB"), 1900, 1640)
    px, py = 120, 400
    d.rectangle([px - 12, py - 12, px + plan.width + 12, py + plan.height + 12], outline=(215, 212, 205), width=3)
    im.paste(plan, (px, py))
    d.text((px, py + plan.height + 26), "Developer plate excerpt - " + plate + " - The Symphony floor-plan deck (Imtiaz). North per plate.", font=SM, fill=MUT)

    # right column
    x, y = 2140, 400
    d.text((x, y), "Key facts", font=H2, fill=TEAL)
    y += 80
    rl = rooms.get(unit, [])
    tot = sum(r[2] for r in rl)
    interior = sum(r[2] for r in rl if "Terrace" not in r[1])
    su = by_type.get(sheet_type, [])
    if su:
        avail_line = "Developer sheet %s: %d unit(s) of this type available - from AED %s - %s-%s sq ft" % (
            sheet_date, len(su), format(int(min(q[3] for q in su)), ","), format(int(min(q[2] for q in su)), ","),
            format(int(max(q[2] for q in su)), ","))
    else:
        avail_line = "Developer sheet %s: none of this type listed as available" % sheet_date
    bullets = [floors, view, avail_line,
               "Layout source: developer floor-plan deck (23 pp). Room schedule below: DigitAlchemy model, indicative (~%s m2 interior)" % format(round(interior), ","),
               "Every room classified: Uniclass 2015 SL - OmniClass T11 - Brick - Haystack"]
    for btxt in bullets:
        for i, line in enumerate(wrap(d, btxt, B, 1230)):
            d.text((x + (0 if i == 0 else 34), y), ("-  " if i == 0 else "") + line, font=B, fill=INK)
            y += 42
        y += 12
    y += 16
    d.text((x, y), "Rooms (indicative)", font=H2, fill=TEAL)
    y += 76
    for num, name, m2 in rl:
        d.text((x, y), num, font=SM, fill=MUT)
        d.text((x + 190, y), name, font=B, fill=INK)
        s = "%.0f m2  -  %s sq ft" % (m2, format(round(m2 * 10.7639), ","))
        d.text((x + 1230 - d.textlength(s, font=SM), y + 4), s, font=SM, fill=INK)
        y += 44
    y += 26
    d.text((x, y), "Legend (developer plate)", font=H2, fill=TEAL)
    y += 76
    for name, col in LEGEND:
        d.rectangle([x, y + 6, x + 44, y + 40], fill=col, outline=(120, 120, 120))
        d.text((x + 64, y), name, font=SM, fill=INK)
        y += 46
    y += 20
    if os.path.exists(ctx_p) and y < 2000:
        ctx = fit(Image.open(ctx_p).convert("RGB"), 1230, 2230 - y)
        im.paste(ctx, (x, y))
        d.text((x, y + ctx.height + 8), "Whole-floor plate for context - " + plate, font=XS, fill=MUT)

    d.rectangle([0, H - 150, W, H], fill=(240, 238, 232))
    foot = ("Plan imagery: Imtiaz developer floor-plan deck, reproduced for research/briefing at source resolution. "
            "Room areas: DigitAlchemy model scaled from the same deck - indicative, not surveyed. Availability and prices: developer sheet %s. "
            "DigitAlchemy Tech Limited - contact@digitalabbot.io - +971 56 227 6093" % sheet_date)
    yy = H - 125
    for line in wrap(d, foot, SM, W - 240):
        d.text((120, yy), line, font=SM, fill=MUT)
        yy += 34
    out_png = os.path.join(OUT, "sheet_%s.png" % key)
    im.save(out_png, optimize=True)
    im.save(out_png[:-4] + ".pdf", resolution=300)
    pages.append(im)
    print("sheet", key)

if pages:
    pages[0].save(os.path.join(OUT, "TheSymphony_UnitTypeCards.pdf"), save_all=True, append_images=pages[1:], resolution=300)
    print("combined PDF:", len(pages), "pages")
