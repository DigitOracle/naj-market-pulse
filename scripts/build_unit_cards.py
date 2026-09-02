"""Unit-type card sheets for The Symphony by Imtiaz - A4 landscape PNG + PDF per type + combined PDF.
Inputs: Revit card PNGs (unit_cards/card_<Type>_plan.png, _3d.png), data/cards/card_rooms.json,
data/avail/imtiaz_2026-08-28.json (developer sheet), data/brochure/floorplan_labels.json (census).
House style: DigitAlchemy teal #0A4F4A / gold #C5A56A, Georgia headlines, Segoe UI body.
"""
import collections, json, os, sys
from PIL import Image, ImageDraw, ImageFont

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ENG = r"C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Client_Engagements\Imtiaz\02_Execution\04_Golden_Building_Symphony\02_Revit\unit_cards"
OUT = os.path.join(ENG, "sheets")
os.makedirs(OUT, exist_ok=True)
TEAL, GOLD, INK, MUT, PAPER = (10, 79, 74), (197, 165, 106), (28, 32, 30), (110, 118, 114), (250, 249, 246)


def F(name, size):
    return ImageFont.truetype(r"C:\Windows\Fonts\%s.ttf" % name, size)


H1, H2, B, SM = F("georgia", 74), F("georgia", 44), F("segoeui", 30), F("segoeui", 24)
W, H = 3508, 2480  # A4 landscape @ 300 dpi

rooms = json.load(open(os.path.join(ROOT, "data", "cards", "card_rooms.json")))
avail = json.load(open(os.path.join(ROOT, "data", "avail", "imtiaz_2026-08-28.json")))
sheet_date = avail.get("sheet_date", "")
by_type = collections.defaultdict(list)
for p in avail["projects"]:
    for u in p["units"]:
        by_type[u[1]].append(u)

PALETTE = [("Living / Kitchen / Dining", (236, 228, 212)), ("Bedrooms", (213, 223, 232)),
           ("Bathrooms / Dressing", (228, 228, 228)), ("Kitchen (duplex)", (241, 229, 198)),
           ("Terraces", (214, 232, 214)), ("Corridor / core", (246, 246, 246))]

CARDS = [
    ("MasterSuite_1BR", "Master Suite - 1 Bedroom", "1101", "Floors 10-22 - west wing, 2 per floor - corner suites", "1 B/R",
     "West face - Park / Community side per the developer compass"),
    ("1BR", "1 Bedroom", "1102", "Floors 10-33 - 6-7 per floor", "1 B/R",
     "North and east faces - Burj Khalifa & Lagoon side on the north face"),
    ("2BR", "2 Bedroom", "1104", "Floors 10-34 - 4 per floor (corners)", "2 B/R", "Corner units - two aspects"),
    ("3BR", "3 Bedroom", "2401", "Floors 24, 26, 28, 30 - 2 per floor", "3 B/R",
     "North-west wrap - Park + Burj Khalifa & Lagoon"),
    ("4BR", "4 Bedroom", "3201", "Floor 32 - 2 units", "4 B/R", "North-west wrap - three aspects"),
    ("4BR_Duplex_lower", "4 Bedroom Duplex - lower level (33rd)", "3307L", "Floors 33-34 - unit 3307 - private pool terrace",
     "4 B/R Duplex", "West wing + NW corner - Skyline, Lagoon & Cityscape (developer claim)"),
    ("4BR_Duplex_upper", "4 Bedroom Duplex - upper level (34th)", "3307U", "Floors 33-34 - unit 3307 - planted upper terrace",
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
for key, title, unit, floors, sheet_type, view in CARDS:
    plan_p = os.path.join(ENG, "card_%s_plan.png" % key)
    iso_p = os.path.join(ENG, "card_%s_3d.png" % key)
    if not os.path.exists(plan_p):
        print("missing", plan_p)
        continue
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 300], fill=TEAL)
    d.rectangle([0, 300, W, 312], fill=GOLD)
    d.text((120, 70), "THE SYMPHONY BY IMTIAZ", font=H1, fill=(255, 255, 255))
    d.text((120, 175), "Meydan Horizon - Bukadra - Dubai   |   Unit type card", font=B, fill=(220, 228, 226))
    d.text((W - 120 - d.textlength(title, font=H2), 120), title, font=H2, fill=GOLD)

    plan = fit(Image.open(plan_p).convert("RGB"), 2050, 1700)
    px, py = 120, 380
    d.rectangle([px - 12, py - 12, px + plan.width + 12, py + plan.height + 12], outline=(215, 212, 205), width=3)
    im.paste(plan, (px, py))
    d.text((px, py + plan.height + 30), "Plan 1:50 - dimensions in mm - areas per room in m2 and sq ft", font=SM, fill=MUT)

    x, y = 2290, 380
    d.text((x, y), "Key facts", font=H2, fill=TEAL)
    y += 80
    rl = rooms.get(unit, [])
    tot = sum(r[2] for r in rl)
    interior = sum(r[2] for r in rl if "Terrace" not in r[1])
    su = by_type.get(sheet_type, [])
    first = "Representative unit %s - %d rooms - %s m2 interior" % (unit.rstrip("LU"), len(rl), format(round(interior), ","))
    if tot - interior > 1:
        first += " + %s m2 terrace" % format(round(tot - interior), ",")
    if su:
        avail_line = "Developer sheet %s: %d unit(s) of this type available - from AED %s - %s-%s sq ft" % (
            sheet_date, len(su), format(int(min(q[3] for q in su)), ","), format(int(min(q[2] for q in su)), ","),
            format(int(max(q[2] for q in su)), ","))
    else:
        avail_line = "Developer sheet %s: none of this type listed as available" % sheet_date
    bullets = [first, floors, view, avail_line,
               "Classification on every room: Uniclass 2015 SL - OmniClass T11 - Brick - Haystack"]
    for btxt in bullets:
        for i, line in enumerate(wrap(d, btxt, B, 1080)):
            d.text((x + (0 if i == 0 else 34), y), ("-  " if i == 0 else "") + line, font=B, fill=INK)
            y += 42
        y += 14
    y += 20
    d.text((x, y), "Rooms", font=H2, fill=TEAL)
    y += 76
    for num, name, m2 in rl:
        d.text((x, y), num, font=SM, fill=MUT)
        d.text((x + 190, y), name, font=B, fill=INK)
        s = "%.1f m2  -  %s sq ft" % (m2, format(round(m2 * 10.7639), ","))
        d.text((x + 1080 - d.textlength(s, font=SM), y + 4), s, font=SM, fill=INK)
        y += 44
    y += 30
    d.text((x, y), "Legend", font=H2, fill=TEAL)
    y += 76
    for name, col in PALETTE:
        d.rectangle([x, y + 6, x + 44, y + 40], fill=col, outline=(120, 120, 120))
        d.text((x + 64, y), name, font=SM, fill=INK)
        y += 50
    d.rectangle([x, y + 14, x + 44, y + 22], fill=(30, 30, 30))
    d.text((x + 64, y), "Wall (cut) - door swing - window", font=SM, fill=INK)
    y += 60
    if os.path.exists(iso_p) and y < 2100:
        iso = fit(Image.open(iso_p).convert("RGB"), 1080, 2200 - y)
        im.paste(iso, (x, y))

    d.rectangle([0, H - 150, W, H], fill=(240, 238, 232))
    foot = ("Geometry: typology template scaled from the developer's floor-plan deck - dimensions are indicative, not surveyed. "
            "Availability and prices: developer sheet %s. Views: developer compass; geometry verdicts per unit in the DigitAlchemy view lane. "
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
