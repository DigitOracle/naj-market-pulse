"""Where Dubai lives / where Dubai works - data cards recomputed from source at render time.

A port of the Sobha intro's card pattern (scripts/sobha_intro.py) for the Najma question-bank episodes, asked
for on 27 Sep 2026 after a hand-drawn card carried a false claim: it read "the most populous communities are
industrial" when only two of the top three are. Every number AND every sentence on these cards is computed from
data/board/_live_work_by_community.csv on each run, so the card cannot drift from its source and a sentence
cannot outlive the data it describes.

  Card A  "Where Dubai works"   companies per 100 residents, top 5
                                filtered to communities with at least MIN_RESIDENTS residents, because the raw
                                ratio is meaningless on a tiny population - Nakhlat Deira has 2 residents and
                                97 companies, which is 4,850 per 100 and says nothing
                                rows flagged name_differs_between_sources are excluded
  Card B  "Where Dubai lives"   residents, top 5, no filter

Both carry their caveats ON THE FACE rather than in a description no viewer reads, the way the Sobha tour's
cards say their distances are straight-line:

  registered mainland companies, not staff
  free-zone companies are missing or unplaced
  residents: DSC 2025

LAYOUT differs from the Sobha tour deliberately. There the presenter stood right and overlays went bottom-left;
here HeyGen composites Naj full-body and the burned-in captions sit in a low centred band, so the cards live in
the UPPER HALF of the 1080 x 1920 frame and nothing is drawn below CAPTION_TOP.

Names are the CSV's own, tidied for case only. The register spells them JABAL ALI INDUSTRIAL FIRST and
AL QOUZ IND.SECOND; this does not silently rewrite them to "Jebel Ali Industrial 1", because a renamed row is a
claim about identity and that is the caller's decision, not this script's. Pass --pretty to apply the small
substitution table at the top of the file, which is explicit and reviewable.

  python scripts/live_work_cards.py                    PNGs + timings JSON
  python scripts/live_work_cards.py --mp4              also an mp4 of the sequence
  python scripts/live_work_cards.py --print            figures only, render nothing

Output: data/media/live_work/card_works.png, card_lives.png, live_work_timings.json, live_work_cards.mp4
"""
import csv
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "board", "_live_work_by_community.csv")
OUT = os.path.join(ROOT, "data", "media", "live_work")

W, H = 1080, 1920
CAPTION_TOP = 1180          # nothing is drawn below this: Naj's captions own the low centred band
CARD_X, CARD_Y, CARD_W = 60, 250, W - 120
TOP_N = 5
MIN_RESIDENTS = 5000        # the ratio needs a real denominator; see the Nakhlat Deira note above
CARD_S, IN_S, OUT_S = 7.0, 0.45, 0.40
FPS = 30

BG = (16, 20, 27)
CARD_BG = (26, 32, 42)
INK = (238, 242, 248)
DIM = (150, 162, 178)
GOLD = (198, 160, 78)
TEAL = (62, 138, 126)

# Explicit and reviewable, applied only under --pretty. Never inferred.
PRETTY = {"JABAL ALI INDUSTRIAL FIRST": "Jebel Ali Industrial 1", "MUHAISANAH SECOND": "Muhaisnah 2",
          "AL QOUZ IND.SECOND": "Al Quoz Industrial 2", "WARSAN FIRST": "Warsan 1",
          "JABAL ALI FIRST": "Jebel Ali 1", "SAIH SHUAIB 3": "Saih Shuaib 3"}

# Per card, because a footnote that does not apply to the card it sits on trains the viewer to skip
# footnotes. The works card needs the residents source too - the ratio has residents in its denominator.
FOOTNOTES = {"works": ["registered mainland companies, not staff",
                       "free-zone companies are missing or unplaced",
                       "residents: DSC 2025"],
             "lives": ["residents: DSC 2025"]}


def font(size, bold=False):
    return ImageFont.truetype(r"C:\Windows\Fonts\%s" % ("segoeuib.ttf" if bold else "segoeui.ttf"), size)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def title_case(s):
    return re.sub(r"\b([A-Z])([A-Z']+)\b", lambda m: m.group(1) + m.group(2).lower(), s.strip())


def display(name, pretty):
    return PRETTY.get(name.strip().upper(), title_case(name)) if pretty else title_case(name)


def is_industrial(name):
    """A whole word, not a substring - "IND" inside another word is not an industrial community."""
    return bool(re.search(r"\b(IND|INDUSTRIAL)\b", name.upper().replace(".", ". ")))


def read_rows():
    with open(CSV, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        res, ratio = num(r.get("residents")), num(r.get("companies_per_100_residents"))
        if not r.get("name_en", "").strip() or res is None:
            continue
        out.append({"name": r["name_en"].strip(), "residents": res, "ratio": ratio,
                    "companies": num(r.get("mainland_companies_registered")),
                    "flagged": bool((r.get("name_differs_between_sources") or "").strip())})
    return out


def figures(pretty=False):
    rows = read_rows()
    works = sorted([r for r in rows if r["ratio"] is not None
                    and r["residents"] >= MIN_RESIDENTS and not r["flagged"]],
                   key=lambda r: -r["ratio"])[:TOP_N]
    lives = sorted(rows, key=lambda r: -r["residents"])[:TOP_N]

    # The sentence that went wrong by hand. Counted, phrased from the count, never typed.
    top3 = lives[:3]
    n_ind = sum(1 for r in top3 if is_industrial(r["name"]))
    words = {0: "none", 1: "one", 2: "two", 3: "all three"}
    if n_ind == 0:
        line = "none of the top three are industrial areas"
    elif n_ind == 3:
        line = "all three of the largest are industrial areas"
    else:
        line = "%s of the top three are industrial areas" % words[n_ind]

    excluded = sum(1 for r in rows if r["flagged"])
    below = sum(1 for r in rows if r["ratio"] is not None and r["residents"] < MIN_RESIDENTS)
    return {
        "source": os.path.relpath(CSV, ROOT), "communities": len(rows),
        "min_residents": MIN_RESIDENTS, "excluded_name_mismatch": excluded, "excluded_small": below,
        "works": [{"name": display(r["name"], pretty), "raw_name": r["name"],
                   "value": int(round(r["ratio"])), "residents": int(r["residents"])} for r in works],
        "lives": [{"name": display(r["name"], pretty), "raw_name": r["name"],
                   "value": int(r["residents"]), "industrial": is_industrial(r["name"])} for r in lives],
        "lives_note": line, "industrial_in_top3": n_ind,
        "works_note": "of communities with %s+ residents" % f"{MIN_RESIDENTS:,}",
    }


def rounded(dr, box, r, fill):
    dr.rounded_rectangle(box, radius=r, fill=fill)


def draw_card(fig, which, pretty=False):
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    rows = fig["works"] if which == "works" else fig["lives"]
    head = "Where Dubai works" if which == "works" else "Where Dubai lives"
    sub = ("companies per 100 residents" if which == "works" else "residents")
    accent = TEAL if which == "works" else GOLD

    dr.text((CARD_X, 120), head.upper(), font=font(64, True), fill=INK)
    dr.text((CARD_X, 196), sub, font=font(34), fill=DIM)

    top = CARD_Y + 60
    row_h = 104
    card_h = row_h * len(rows) + 210
    rounded(dr, (CARD_X, top, CARD_X + CARD_W, top + card_h), 26, CARD_BG)

    y = top + 34
    biggest = max(r["value"] for r in rows) or 1
    for i, r in enumerate(rows):
        bar_w = int((CARD_W - 150) * r["value"] / biggest)
        dr.rounded_rectangle((CARD_X + 34, y + 62, CARD_X + 34 + max(bar_w, 4), y + 74), radius=6, fill=accent)
        dr.text((CARD_X + 34, y + 6), "%d." % (i + 1), font=font(30, True), fill=DIM)
        dr.text((CARD_X + 86, y), r["name"], font=font(40, True), fill=INK)
        val = f"{r['value']:,}"
        vw = dr.textlength(val, font=font(44, True))
        dr.text((CARD_X + CARD_W - 34 - vw, y + 2), val, font=font(44, True), fill=accent)
        y += row_h

    note = fig["lives_note"] if which == "lives" else fig["works_note"]
    dr.text((CARD_X + 34, y + 10), note, font=font(32), fill=INK)

    fy = y + 62
    for fn in FOOTNOTES[which]:
        dr.text((CARD_X + 34, fy), "\u00b7 " + fn, font=font(25), fill=DIM)
        fy += 32

    assert fy < CAPTION_TOP, ("card runs to y=%d and the caption band starts at %d - "
                              "it would sit under Naj's captions" % (fy, CAPTION_TOP))
    return img


def main():
    pretty = "--pretty" in sys.argv
    fig = figures(pretty)

    print("%s  %d communities" % (os.path.relpath(CSV, ROOT), fig["communities"]))
    print("  excluded: %d name-mismatch flagged, %d under %s residents"
          % (fig["excluded_name_mismatch"], fig["excluded_small"], f"{MIN_RESIDENTS:,}"))
    print("Where Dubai works - companies per 100 residents")
    for r in fig["works"]:
        print("   %-30s %6d   (residents %s)" % (r["name"], r["value"], f"{r['residents']:,}"))
    print("Where Dubai lives - residents")
    for r in fig["lives"]:
        print("   %-30s %9s%s" % (r["name"], f"{r['value']:,}", "  industrial" if r["industrial"] else ""))
    print("computed sentence: %s" % fig["lives_note"])
    if "--print" in sys.argv:
        return 0

    os.makedirs(OUT, exist_ok=True)
    imgs = {}
    for which, name in (("works", "card_works.png"), ("lives", "card_lives.png")):
        img = draw_card(fig, which, pretty)
        p = os.path.join(OUT, name)
        img.save(p)
        imgs[which] = (img, p)
        print("wrote %s" % os.path.relpath(p, ROOT))

    tim = {"generated_from": fig["source"], "fps": FPS, "frame": [W, H], "caption_top": CAPTION_TOP,
           "card_s": CARD_S, "in_s": IN_S, "out_s": OUT_S,
           "cards": [{"key": "works", "on": 0.0, "off": CARD_S, "head": "Where Dubai works",
                      "rows": fig["works"], "note": fig["works_note"], "footnotes": FOOTNOTES["works"]},
                     {"key": "lives", "on": CARD_S, "off": 2 * CARD_S, "head": "Where Dubai lives",
                      "rows": fig["lives"], "note": fig["lives_note"], "footnotes": FOOTNOTES["lives"]}],
           "footnotes": FOOTNOTES, "total_s": 2 * CARD_S, "figures": fig}
    tp = os.path.join(OUT, "live_work_timings.json")
    json.dump(tim, open(tp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote %s  (%.1f s total)" % (os.path.relpath(tp, ROOT), tim["total_s"]))

    if "--mp4" in sys.argv:
        tmp = tempfile.mkdtemp(prefix="lwcards_")
        n = 0
        for which in ("works", "lives"):
            img, _ = imgs[which]
            for f in range(int(CARD_S * FPS)):
                t = f / float(FPS)
                a = min(1.0, t / IN_S) if t < IN_S else (min(1.0, (CARD_S - t) / OUT_S) if t > CARD_S - OUT_S else 1.0)
                frame = Image.blend(Image.new("RGB", (W, H), BG), img, a)
                frame.save(os.path.join(tmp, "%05d.png" % n))
                n += 1
        mp4 = os.path.join(OUT, "live_work_cards.mp4")
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", os.path.join(tmp, "%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", mp4],
                       check=True, capture_output=True)
        print("wrote %s  (%d frames)" % (os.path.relpath(mp4, ROOT), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
