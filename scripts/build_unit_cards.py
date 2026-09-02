"""Unit-type card sheets for The Symphony by Imtiaz - A4 landscape PNG + PDF per type + combined PDF.

v3 (2 Sep 2026): developer floor plate as the main image with EVERY unit numbered (deck numbering, clockwise from NW),
the card's unit type highlighted in Imtiaz crimson with the rest of the plate dimmed; vicinity block (nearest metro,
schools, 1 km / 3 km demographics from Esri); 'curated for' header; confidentiality + contact footer.
Config: data/cards/card_config.json - rooms: card_rooms.json - vicinity: vicinity.json - availability: developer sheet JSON.
Re-run whenever the availability sheet changes (the daily refresh should call this after extraction).
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
CFG = json.load(open(os.path.join(CARDS_DIR, "card_config.json"), encoding="utf-8-sig"))
TEAL, GOLD, INK, MUT, PAPER = (10, 79, 74), (197, 165, 106), (28, 32, 30), (110, 118, 114), (250, 249, 246)
HI = tuple(CFG.get("highlight_rgb", [196, 30, 58]))


def F(name, size):
    return ImageFont.truetype(r"C:\Windows\Fonts\%s.ttf" % name, size)


H1, H2, B, SM, XS, NUM = F("georgia", 70), F("georgia", 42), F("segoeui", 29), F("segoeui", 23), F("segoeui", 20), F("seguisb", 15)
W, H = 3508, 2480

rooms = json.load(open(os.path.join(CARDS_DIR, "card_rooms.json")))
avail_path = os.path.join(ROOT, "data", "avail", "imtiaz_2026-08-28.json")
avail = json.load(open(avail_path))
sheet_date = avail.get("sheet_date", "")
by_type = collections.defaultdict(list)
for p in avail["projects"]:
    if "symphony" not in p.get("p", "").lower():
        continue
    for u in p["units"]:
        by_type[u[1]].append(u)
vic = json.load(open(os.path.join(CARDS_DIR, "vicinity.json"))) if os.path.exists(os.path.join(CARDS_DIR, "vicinity.json")) else {}

LEGEND = [("Master suite / larger units (brown)", (176, 137, 104)), ("1 bedroom (cream)", (236, 227, 205)),
          ("2 bedroom (pink)", (196, 168, 172)), ("Core, lifts, stairs (grey)", (150, 150, 150)),
          ("Balconies / terraces (light grey)", (222, 222, 222)), ("Pool (blue)", (130, 190, 210))]

# key, title, rep unit, plate label, floor type for numbering, floor number for unit ids, highlight bay indices, floors text, sheet type, view
CARDS = [
    ("MasterSuite_1BR", "Master Suite - 1 Bedroom", "1101", "11th floor plate (typical 11th-21st odd)", "T13", 11, [0, 11, 12],
     "Floors 10-22 - west wing and NW corner - 3 per floor", "1 B/R", "West and north faces - Park / Community per the developer compass"),
    ("1BR", "1 Bedroom", "1102", "11th floor plate (typical 11th-21st odd)", "T13", 11, [1, 2, 4, 5, 6, 8, 9],
     "Floors 10-33 - 6-7 per floor", "1 B/R", "North and east faces - Burj Khalifa & Lagoon side on the north face"),
    ("2BR", "2 Bedroom", "1104", "11th floor plate (typical 11th-21st odd)", "T13", 11, [3, 7, 10],
     "Floors 10-34 - 4 per floor (corners)", "2 B/R", "Corner units - two aspects"),
    ("3BR", "3 Bedroom", "2401", "24th floor plate (24, 26, 28, 30)", "T10", 24, [0, 9],
     "Floors 24, 26, 28, 30 - 2 per floor", "3 B/R", "North-west wrap - Park + Burj Khalifa & Lagoon"),
    ("4BR", "4 Bedroom", "3201", "32nd floor plate", "T9", 32, [0, 9], "Floor 32 - 2 units", "4 B/R", "North-west wrap - three aspects"),
    ("4BR_Duplex_lower", "4 Bedroom Duplex - lower level (33rd)", "3307L", "33rd floor plate", "T33", 33, [0],
     "Floors 33-34 - unit 3307 - private pool terrace", "4 B/R Duplex", "West wing + NW corner - Skyline, Lagoon & Cityscape (developer claim)"),
    ("4BR_Duplex_upper", "4 Bedroom Duplex - upper level (34th)", "3307U", "34th floor plate", "T34", 34, [0],
     "Floors 33-34 - unit 3307 - planted upper terrace", "4 B/R Duplex", "West wing + NW corner - Skyline, Lagoon & Cityscape (developer claim)"),
]
PX = CFG["plate_px"]


def calibrate(img):
    """Find the plate's pixel box from the drawing itself: bbox of non-white pixels, inset for balconies (~1.5 m)."""
    g = img.convert("L").point(lambda v: 255 if v < 215 else 0)
    bb = g.getbbox() or (0, 0, img.width, img.height)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    inset_x, inset_y = int(w * 0.055), int(h * 0.055)
    return {"x0": bb[0] + inset_x, "y0": bb[1] + inset_y, "x1": bb[2] - inset_x, "y1": bb[3] - inset_y}


def to_px(xm, ym):
    """plate metres (origin centre, north up) -> pixel on the plate crop (PX calibrated per image)."""
    sx = (PX["x1"] - PX["x0"]) / 40000.0; sy = (PX["y1"] - PX["y0"]) / 40000.0
    return PX["x0"] + (xm + 20000) * sx, PX["y1"] - (ym + 20000) * sy


def unit_number(ftype, floor, idx):
    # deck numbering: clockwise from NW = 01..; T33/T34 keep 3307 for the duplex (bay 0) and skip 07 for the others
    if ftype in ("T33", "T34"):
        if idx == 0:
            return "%d07" % floor
        n = idx + 1 if idx < 6 else idx + 2
        return "%d%02d" % (floor, n)
    return "%d%02d" % (floor, idx + 1)


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


def plate_image(key, ftype, floor, hi_idx):
    src = Image.open(os.path.join(CARDS_DIR, "devfloor_%s.png" % key)).convert("RGB")
    global PX
    PX = calibrate(src)
    bays = CFG["bays_by_type"][ftype]
    # dim everything, then paste the highlighted bays back at full strength
    dim = Image.blend(src, Image.new("RGB", src.size, (255, 255, 255)), 0.55)
    for i in hi_idx:
        x0, y0, x1, y1 = bays[i][:4]
        px0, py1 = to_px(x0, y0); px1, py0 = to_px(x1, y1)
        box = (int(px0), int(py0), int(px1), int(py1))
        dim.paste(src.crop(box), box)
    d = ImageDraw.Draw(dim)
    for i in hi_idx:
        x0, y0, x1, y1 = bays[i][:4]
        px0, py1 = to_px(x0, y0); px1, py0 = to_px(x1, y1)
        d.rectangle([px0, py0, px1, py1], outline=HI, width=7)
    # unit numbers on every bay
    for i, b in enumerate(bays):
        cx, cy = to_px((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        lab = unit_number(ftype, floor, i)
        tw = d.textlength(lab, font=NUM)
        bg = HI if i in hi_idx else (40, 40, 40)
        d.rounded_rectangle([cx - tw / 2 - 6, cy - 12, cx + tw / 2 + 6, cy + 12], radius=6, fill=bg)
        d.text((cx - tw / 2, cy - 10), lab, font=NUM, fill=(255, 255, 255))
    return dim


pages = []
for key, title, unit, plate, ftype, floor, hi_idx, floors, sheet_type, view in CARDS:
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    # header
    d.rectangle([0, 0, W, 300], fill=TEAL)
    d.rectangle([0, 300, W, 312], fill=GOLD)
    d.text((120, 62), CFG["building"], font=H1, fill=(255, 255, 255))
    d.text((120, 170), CFG["location"] + "   |   Unit type card   |   " + title, font=B, fill=(220, 228, 226))
    cur = "Curated by " + CFG["curated_by"] + " for " + CFG["curated_for"]
    d.text((W - 120 - d.textlength(cur, font=B), 78), cur, font=B, fill=GOLD)
    av = "Availability as of " + sheet_date
    d.text((W - 120 - d.textlength(av, font=SM), 130), av, font=SM, fill=(220, 228, 226))
    ttl = title
    d.text((W - 120 - d.textlength(ttl, font=H2), 190), ttl, font=H2, fill=GOLD)

    # main image: numbered, highlighted developer plate
    plan = fit(plate_image(key, ftype, floor, hi_idx), 1900, 1560)
    px, py = 120, 380
    d.rectangle([px - 12, py - 12, px + plan.width + 12, py + plan.height + 12], outline=(215, 212, 205), width=3)
    im.paste(plan, (px, py))
    d.text((px, py + plan.height + 22), "Developer plate - " + plate + " - The Symphony floor-plan deck (Imtiaz). Crimson = this unit type; every unit carries its number. North per plate.", font=XS, fill=MUT)

    # vicinity block under the plate
    vy = py + plan.height + 70
    d.text((px, vy), "Vicinity", font=H2, fill=TEAL); vy += 66
    metro = (vic.get("metro") or [])[:2]
    schools = [s for s in (vic.get("schools") or []) if "tennis" not in (s.get("name") or "").lower()][:3]
    demo = {r.get("radius_km"): r for r in (vic.get("demographics") or [])}
    lines = []
    if metro:
        lines.append("Nearest metro: " + " - ".join("%s (%.1f km)" % (m["name"].replace(" Metro Station", ""), m["km"]) for m in metro) + " - straight-line")
    if schools:
        lines.append("Schools: " + " - ".join("%s (%.1f km)" % (s["name"], s["km"]) for s in schools))
    if 1 in demo:
        r1 = demo[1]; r3 = demo.get(3, {})
        lines.append("Within 1 km: %s residents, %s households, purchasing-power index %s (UAE = 100)" % (format(int(r1["pop"]), ","), format(int(r1["households"]), ","), r1["pp_index"]))
        if r3:
            lines.append("Within 3 km: %s residents, %s households, index %s - Esri demographics 2024" % (format(int(r3["pop"]), ","), format(int(r3["households"]), ","), r3["pp_index"]))
    for ln in lines:
        for i, seg in enumerate(wrap(d, ln, SM, 1900)):
            d.text((px + (0 if i == 0 else 30), vy), ("-  " if i == 0 else "") + seg, font=SM, fill=INK); vy += 34
        vy += 4

    # right column
    x, y = 2140, 380
    d.text((x, y), "Key facts", font=H2, fill=TEAL); y += 76
    rl = rooms.get(unit, [])
    interior = sum(r[2] for r in rl if "Terrace" not in r[1])
    su = by_type.get(sheet_type, [])
    if su:
        avail_line = "Developer sheet %s: %d unit(s) of this type available - from AED %s - %s-%s sq ft - units %s" % (
            sheet_date, len(su), format(int(min(q[3] for q in su)), ","), format(int(min(q[2] for q in su)), ","),
            format(int(max(q[2] for q in su)), ","), ", ".join(str(q[0]) for q in su[:8]) + (" ..." if len(su) > 8 else ""))
    else:
        avail_line = "Developer sheet %s: none of this type listed as available" % sheet_date
    bullets = [floors, view, avail_line,
               "Layout source: developer floor-plan deck (23 pp). Room schedule below: DigitAlchemy model, indicative (~%s m2 interior)" % format(round(interior), ","),
               "Every room classified: Uniclass 2015 SL - OmniClass T11 - Brick - Haystack"]
    for btxt in bullets:
        for i, line in enumerate(wrap(d, btxt, B, 1230)):
            d.text((x + (0 if i == 0 else 34), y), ("-  " if i == 0 else "") + line, font=B, fill=INK); y += 40
        y += 10
    y += 14
    d.text((x, y), "Rooms (indicative) - unit " + unit.rstrip("LU"), font=H2, fill=TEAL); y += 72
    for num, name, m2 in rl:
        d.text((x, y), num, font=SM, fill=MUT); d.text((x + 190, y), name, font=B, fill=INK)
        s = "%.0f m2  -  %s sq ft" % (m2, format(round(m2 * 10.7639), ","))
        d.text((x + 1230 - d.textlength(s, font=SM), y + 4), s, font=SM, fill=INK); y += 42
    y += 22
    d.text((x, y), "Legend (developer plate)", font=H2, fill=TEAL); y += 72
    for name, col in LEGEND:
        d.rectangle([x, y + 6, x + 44, y + 40], fill=col, outline=(120, 120, 120)); d.text((x + 64, y), name, font=SM, fill=INK); y += 44
    d.rectangle([x, y + 6, x + 44, y + 40], outline=HI, width=5); d.text((x + 64, y), "This card's unit type - numbers = unit identifiers (floor + position)", font=SM, fill=INK); y += 44

    # footer: confidentiality + contact
    d.rectangle([0, H - 210, W, H], fill=(240, 238, 232)); d.rectangle([0, H - 210, W, H - 204], fill=GOLD)
    yy = H - 190
    for line in wrap(d, CFG["confidentiality"], XS, W - 240):
        d.text((120, yy), line, font=XS, fill=MUT); yy += 30
    d.text((120, H - 62), CFG["contact"], font=SM, fill=TEAL)
    src_line = "Sources: Imtiaz floor-plan deck - developer availability sheet " + sheet_date + " - Esri World Geocoding & GeoEnrichment (2024) - DigitAlchemy Revit model"
    d.text((W - 120 - d.textlength(src_line, font=XS), H - 56), src_line, font=XS, fill=MUT)

    out_png = os.path.join(OUT, "sheet_%s.png" % key)
    im.save(out_png, optimize=True); im.save(out_png[:-4] + ".pdf", resolution=300); pages.append(im)
    print("sheet", key)

if pages:
    pages[0].save(os.path.join(OUT, "TheSymphony_UnitTypeCards.pdf"), save_all=True, append_images=pages[1:], resolution=300)
    print("combined PDF:", len(pages), "pages")
