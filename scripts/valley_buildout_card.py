"""The Valley — registered build-out card.

Renders the segment-3 insert for the Emaar District Ambassador entry: the five REGISTERED
projects in Al Yufrah 1 on their registered construction schedule, coloured by register
status. Deterministic drawing (Pillow) - never image generation.

Honest by construction: this is a SCHEDULE, not a map. No parcel geometry exists in the
open register (DLD lands carries areas, not coordinates; the community polygon set is
community-level), so project positions are NOT claimable. Rather than invent plot locations
inside a real geographic frame - which would read as fact - the build-out is drawn against
time. Each bar spans the project's registered START_DATE to END_DATE, so bar length is
duration and nothing else; villa count is stated in words, never encoded as width.

Palette follows najma.cga: ink-grey existing, teal under construction, gold registered.

Run:  python -X utf8 scripts/valley_buildout_card.py
Out:  public/cards/valley_buildout.png  (1920x1080, video-ready)
"""
import json, os, pathlib, datetime
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "cards" / "valley_buildout.png"
W, H = 1920, 1080

INK = (57, 67, 79)          # #39434F existing stock
TEAL = (62, 138, 126)       # #3E8A7E under construction
GOLD = (197, 165, 106)      # #C5A56A registered pipeline
CREAM = (247, 245, 240)
MUTED = (140, 148, 158)
WHITE = (255, 255, 255)


def font(size, bold=False):
    for name in (("seguisb.ttf", "segoeui.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    for name in ("arialbd.ttf" if bold else "arial.ttf",):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def load_projects():
    """Registered projects for Al Yufrah 1, straight from the built pulse."""
    pulse = json.loads((ROOT / "public" / "pulse.json").read_text(encoding="utf-8"))
    rows = [p for p in pulse["projects"]["projectLookup"] if p.get("area") == "Al Yufrah 1"]
    for r in rows:
        r["project"] = r["project"].replace("The Valley - ", "").strip()
        r["year"] = int((r.get("endDate") or "2030")[:4])
    return sorted(rows, key=lambda r: (r["endDate"] or "", r["project"]))


def main():
    projects = load_projects()
    if not projects:
        raise SystemExit("no registered Al Yufrah 1 projects in pulse.json - run build_pulse.py")
    total = sum(p["units"] for p in projects)

    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    # ---- header -------------------------------------------------------------
    d.rectangle([0, 0, W, 168], fill=INK)
    d.text((88, 46), "THE VALLEY", font=font(58, True), fill=WHITE)
    d.text((88, 116), "The registered build-out  ·  Al Yufrah 1", font=font(27), fill=(178, 186, 196))
    d.text((W - 88, 52), f"{total:,}", font=font(60, True), fill=GOLD, anchor="ra")
    d.text((W - 88, 124), "villas registered", font=font(24), fill=(178, 186, 196), anchor="ra")

    # ---- timeline axis ------------------------------------------------------
    LABEL_R = 286            # right edge of the project-name gutter
    DATE_W = 168             # reserved strip for the completion date, never overrun
    x0, x1 = LABEL_R + 34, W - 88 - DATE_W
    ytop, row_h = 276, 118
    years = list(range(2026, 2032))
    span = years[-1] - years[0]

    def dx(iso):
        """x for an ISO date, linear across the year axis."""
        y, m = int(iso[:4]), int(iso[5:7])
        return x0 + (x1 - x0) * ((y - years[0] + (m - 1) / 12) / span)

    bottom = ytop + row_h * len(projects) - 26
    for yr in years:
        x = dx(f"{yr}-01-01")
        d.line([x, ytop - 48, x, bottom], fill=(222, 218, 210), width=2)
        d.text((x, ytop - 82), str(yr), font=font(25, True), fill=MUTED, anchor="ma")

    # ---- one bar per registered project: START_DATE -> END_DATE -------------
    for i, p in enumerate(projects):
        y = ytop + i * row_h
        pct = p.get("percentComplete") or 0
        building = pct > 0
        colour = TEAL if building else GOLD
        bx, ex = dx(p["startDate"]), dx(p["endDate"])

        d.text((LABEL_R, y + 22), p["project"], font=font(33, True), fill=INK, anchor="ra")
        d.text((LABEL_R, y + 64), f"{p['units']} villas", font=font(23), fill=MUTED, anchor="ra")

        d.rounded_rectangle([bx, y + 14, ex, y + 74], radius=8, fill=colour)
        if building:
            d.rounded_rectangle([bx, y + 14, bx + max(10, (ex - bx) * pct / 100), y + 74],
                                radius=8, fill=INK)
            d.text((bx + 20, y + 30), f"{pct}% built", font=font(23, True), fill=WHITE)
        d.ellipse([ex - 9, y + 35, ex + 9, y + 53], fill=INK)
        d.text((ex + 24, y + 30), p["endDate"], font=font(24, True), fill=INK)

    # ---- legend + footer ----------------------------------------------------
    ly = bottom + 52
    for label, colour, lx in (("Under construction", TEAL, x0),
                              ("Registered, not started", GOLD, x0 + 340),
                              ("Built to date", INK, x0 + 700)):
        d.rounded_rectangle([lx, ly, lx + 30, ly + 26], radius=5, fill=colour)
        d.text((lx + 44, ly + 1), label, font=font(24), fill=INK)

    d.line([88, H - 132, W - 88, H - 132], fill=(222, 218, 210), width=2)
    d.text((88, H - 110),
           "Every date, villa count and percentage is from the Dubai Land Department "
           "register of projects. Escrow registered on all five.",
           font=font(24), fill=INK)
    d.text((88, H - 72),
           "A construction schedule, not a site plan - the open register carries no plot "
           "coordinates, so nothing here is geographic.",
           font=font(22), fill=MUTED)
    d.text((W - 88, H - 72), datetime.date.today().isoformat(), font=font(22), fill=MUTED, anchor="ra")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"wrote {OUT}  ({W}x{H})")
    print(f"  {len(projects)} registered projects, {total:,} villas, "
          f"{sum(1 for p in projects if (p.get('percentComplete') or 0) > 0)} under construction")


if __name__ == "__main__":
    main()
