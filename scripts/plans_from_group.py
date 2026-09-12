"""Floor plans that arrive in the developer group -> the plans library.

The library had no door for WhatsApp material. Its sources were the Symphony unit cards, the
Symphony brochure, the Valley pages and a scrape of public developer sites. Fakhruddin publishes
no plans on its site (the 9 Sep harvest tried 11 of its project pages and got zero images, zero
PDFs, six 404s), so the only Fakhruddin plans that exist anywhere are the ones brokers post in the
group - and nothing read them. Treppan Vision's floor plates sat on disk unseen for that reason.

This renders the plan pages out of captured PDFs into data/plans/<dev>/<project>/, the drop-in
shape build_plans_index.py already consumes, so the library picks them up with no change to it.

    python scripts/plans_from_group.py --dry          # what it would take, nothing written
    python scripts/plans_from_group.py                # render + write meta.json
    python scripts/plans_from_group.py --file "<pdf>" # one document

Then: python scripts/build_plans_index.py
"""
import argparse, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
DOCS = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"
OUT = os.path.join(ROOT, "data", "plans")
DPI = 150

# A page is a floor plan when it carries the vocabulary of one. Room words are the strongest
# signal: an inventory table or a render booklet does not name a wardrobe. Scored, not matched,
# so a single stray word cannot promote a marketing page.
ROOM_WORDS = ("bedroom", "master", "living", "dining", "kitchen", "balcony", "terrace", "wardrobe",
              "ensuite", "en-suite", "bathroom", "washroom", "powder", "foyer", "lobby", "pantry",
              "maid", "study", "laundry", "store", "walk-in", "closet", "office", "retail",
              "corridor", "staircase", "elevator", "lift", "parking", "terrace")
PLAN_WORDS = ("floor plan", "floorplan", "floor plate", "typical floor", "unit plan", "key plan",
              "ground floor", "podium", "level ", "type -", "type-", "suite area", "plot area")
AREA_RX = re.compile(r"\b\d{2,4}(?:\.\d{1,2})?\s*(?:sq\.?\s?ft|sqft|sq\.?\s?m|sqm)\b", re.I)
SCALE_RX = re.compile(r"\b1\s*[:/]\s*\d{2,4}\b")
PRICEY_RX = re.compile(r"\b\d{1,3}(?:,\d{3}){1,3}(?:\.\d{2})?\b")
# What a page says when it IS a plan, as opposed to merely mentioning one.
PLAN_PHRASE_RX = re.compile(
    r"\b(floor\s*plans?|floorplan|floor\s*plate|unit\s*plan|key\s*plan|typical\s*floor"
    r"|(?:ground|first|second|third|fourth|typical|podium|roof|mezzanine|retail)\s+floor"
    r"|type\s*-\s*\w{1,3})\b", re.I)


def money(tok):
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return 0.0
# Pages that look plan-ish but are not: pure price tables and escrow/legal paperwork.
VETO_WORDS = ("selling price", "payment plan", "escrow", "reference no", "terms and conditions",
              "table of contents", "disclaimer only")


LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def deligature(s):
    """Architectural PDFs set 'floor' with an fl ligature, so a plain search for "floor plan"
    misses every page of a floor-plan set. Cost us the Treppan Vision plates on 12 Sep 2026."""
    for k, v in LIGATURES.items():
        s = s.replace(k, v)
    return s


def page_score(text, n_drawings, n_images):
    low = deligature(text or "").lower()
    rooms = sum(1 for w in ROOM_WORDS if w in low)
    words = len(low.split())

    # A ruled inventory table carries thousands of vector strokes, exactly like a drawing does, so
    # stroke density alone cannot tell them apart - it scored 42 "plans" out of one Beyond
    # availability sheet. Two hard tests decide it before any scoring happens.
    prices = [t for t in PRICEY_RX.findall(low) if money(t) >= 50000]
    if len(prices) >= 5:
        return 0, rooms, words                       # a column of prices is a table, not a plan
    if rooms < 2 and not PLAN_PHRASE_RX.search(low):
        return 0, rooms, words                       # a plan names its rooms or says what it is

    score = 0
    score += min(rooms, 6) * 2
    score += sum(3 for w in PLAN_WORDS if w in low)
    score += 3 if AREA_RX.search(low) else 0
    score += 2 if SCALE_RX.search(low) else 0
    # A plan is drawn, not written. Stroke density is the one signal that survives a page with no
    # room labels, a foreign-language title block, or nothing but a disclaimer - so weight it.
    words = len(low.split())
    if words < 400:
        if n_drawings > 2000:
            score += 8
        elif n_drawings > 500:
            score += 6
        elif n_drawings > 60:
            score += 4
    if n_images and words < 120:
        score += 2
    for w in VETO_WORDS:
        if w in low:
            score -= 4
    return score, rooms, words


_OCR = None


def respace(s):
    """OCR on these title blocks drops word gaps ("SmartFlex1BRTYPE1"). Put them back."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", s)
    s = re.sub(r"(?i)\b(BR|BHK)\s*(TYPE)\b", r"\1 \2", s)
    s = re.sub(r"(?i)\b(st|nd|rd|th)\s*(to)\b", r"\1 \2", s)   # split "rdto" BEFORE rejoining "3 rd"
    s = re.sub(r"(?i)(\d)\s+(st|nd|rd|th)\b", r"\1\2", s)
    return re.sub(r"\s+", " ", s).strip()


def ocr_label(path, page_no):
    """Read a raster plan page's own title block. These pages carry no text layer at all - the
    broker pack's 7 unit plans were unlabelled ("Page 50") until this read them."""
    global _OCR
    try:
        import fitz, numpy as np
        if _OCR is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        d = fitz.open(path)
        pix = d[page_no].get_pixmap(dpi=130)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        res, _ = _OCR(img)
        d.close()
    except Exception:
        return None, None, None
    lines = [respace(r[1]) for r in (res or [])]
    typ = next((l for l in lines if re.search(r"(?i)\b(smart\s*flex|studio|\d\s*(?:br|bhk|bedroom))\b", l)
                and "view" not in l.lower() and len(l) < 60), None)
    lvl = next((l for l in lines if re.search(r"(?i)\bfloors?\b.*\d", l) and len(l) < 70), None)
    if not typ and lvl:
        typ, lvl = lvl, None          # a whole-floor plate is named by its floors, not a unit type
    area = next((l for l in lines if re.search(r"(?i)total\s*area", l)), None)
    if area:
        m = re.search(r"([\d,]+\.?\d*)\s*SQ", area, re.I)
        area = (m.group(1) + " sq ft") if m else None
    return typ, lvl, area


def project_of(base):
    """Project name from the captured filename, minus the listener's timestamp and noise."""
    stem = re.sub(r"^\d+_", "", base)
    stem = os.path.splitext(stem)[0]
    stem = re.sub(r"\b(floor\s*plate|floor\s*plans?|brok?re?\s*pack|broker\s*pack|inventory|availability|compressed)\b", " ", stem, flags=re.I)
    stem = re.sub(r"[-_]+", " ", stem)
    stem = re.sub(r"\b\d{1,2}[-.]?\s*(sep|sept|aug|oct|jan|feb|mar|apr|may|jun|jul|nov|dec)\b.*$", " ", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip(" -_.")
    return stem.title() or "Unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--docs", default=DOCS)
    ap.add_argument("--min-score", type=int, default=8)
    ap.add_argument("--dev", help="write only this developer key (the rest are still reported)")
    a = ap.parse_args()

    try:
        import fitz
    except ImportError:
        print("PyMuPDF (fitz) is required", file=sys.stderr)
        return 2
    from extract_avail import dev_from_text          # the ONE developer resolver

    # Attribution the store already made. The extractor recovers the developer from page CONTENT,
    # which beats any filename guess, so reuse it rather than growing a second alias table here -
    # that duplication is what put the unit-type gate and its label out of step in the first place.
    attributed = {}
    try:
        import duckdb
        c = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
        for dev, src in c.execute("select developer, source_files from dev_sheet").fetchall():
            if not dev or dev.lower() in ("unknown", "none"):
                continue
            try:
                for f in json.loads(src or "[]"):
                    attributed[f] = dev.lower()
            except Exception:
                pass
        c.close()
    except Exception as e:
        print("note: store attribution unavailable (%s); falling back to filenames" % e)

    paths = [a.file] if a.file else sorted(glob.glob(os.path.join(a.docs, "*.pdf")))
    # The listener re-saves a document under a fresh timestamp on every re-delivery, so the same
    # broker pack can sit on disk many times. Process each distinct document once, or its pages
    # land in the pack twice over.
    import hashlib
    uniq, seen_hash = [], set()
    for p in paths:
        try:
            with open(p, "rb") as fh:
                h = hashlib.sha1(fh.read()).hexdigest()
        except OSError:
            continue
        if h in seen_hash:
            continue
        seen_hash.add(h)
        uniq.append(p)
    paths = uniq
    packs, skipped = {}, []
    for path in paths:
        base = os.path.basename(path)
        dev = attributed.get(base) or dev_from_text(base)
        try:
            doc = fitz.open(path)
        except Exception as e:
            skipped.append((base, "unreadable: %s" % e))
            continue
        pages = []
        for i, page in enumerate(doc):
            try:
                pages.append((i, page.get_text(), len(page.get_drawings()), len(page.get_images(full=True))))
            except Exception:
                continue
        hits = []
        for (i, text, nd, ni) in pages:
            sc, rooms, words = page_score(text, nd, ni)
            if sc >= a.min_score:
                hits.append((i, sc, rooms, words, text))

        # Section rule. A brochure's plan pages are often flat raster with no text and no strokes -
        # nothing in the page itself says "plan". What identifies them is the header that announces
        # them. Treppan Vision's broker pack hides 7 plans this way behind "DLRC EXCLUSIVE FLOOR
        # PLANS" on page 49. A wholly textless image page following such a header is a plan page;
        # the first page carrying any text at all ends the run.
        seen = {h[0] for h in hits}
        for idx, (i, text, nd, ni) in enumerate(pages):
            flat = re.sub(r"\s+", " ", deligature(text or "")).strip().lower()
            if not (len(flat.split()) <= 10 and "floor plan" in flat):
                continue
            for (j, t2, nd2, ni2) in pages[idx + 1:]:
                if (t2 or "").strip() or ni2 < 1:
                    break
                if j not in seen:
                    seen.add(j)
                    # empty text on purpose: these pages carry none, which is what marks them
                    # for OCR labelling further down. A placeholder here suppressed it once.
                    hits.append((j, a.min_score, 0, 0, ""))
        hits.sort()
        if not hits:
            doc.close()
            continue
        if not dev:
            skipped.append((base, "%d plan pages found but no developer resolves from the name" % len(hits)))
            doc.close()
            continue
        proj = project_of(base)
        key = (dev, proj)
        packs.setdefault(key, {"pages": [], "sources": set()})
        packs[key]["sources"].add(base)
        folder = os.path.join(OUT, dev, re.sub(r"[^a-z0-9]+", "_", proj.lower()).strip("_"))
        for (i, sc, rooms, words, text) in hits:
            label = None
            m = re.search(r"(smart flex[^\n|]{0,40}|type\s*-?\s*\w{1,3}\b|[a-z]+ floor offices?|ground floor[^\n|]{0,24}|typical floor[^\n|]{0,24})", text, re.I)
            if m:
                label = re.sub(r"\s+", " ", m.group(1)).strip(" -.|")
            # page number alone collides when two documents of the same project both have a plan
            # on the same page - fingerprint the source so each keeps its own file
            fn = "p%03d_%s.jpg" % (i + 1, hashlib.sha1(base.encode()).hexdigest()[:6])
            packs[key]["pages"].append({"src": path, "page": i, "file": fn, "folder": folder,
                                        "score": sc, "label": label or "Page %d" % (i + 1),
                                        # OCR whenever the text layer yielded no usable title -
                                        # a page can carry text (a disclaimer) and still be unlabelled
                                        "ocr": label is None})
        doc.close()

    if not packs:
        print("no plan pages found in %d document(s)" % len(paths))
        for b, why in skipped:
            print("  skipped: %s - %s" % (b, why))
        return 0

    for (dev, proj), pack in sorted(packs.items()):
        folder = pack["pages"][0]["folder"]
        print("%s / %s: %d plan pages -> %s" % (dev, proj, len(pack["pages"]), os.path.relpath(folder, ROOT)))
        for p in pack["pages"]:
            print("    p%-4d score %-3d %s" % (p["page"] + 1, p["score"], p["label"]))
        if a.dry:
            continue
        if a.dev and dev != a.dev:
            print("    (reported only: --dev %s)" % a.dev)
            continue
        os.makedirs(os.path.join(folder, "jpg"), exist_ok=True)
        items = []
        for p in pack["pages"]:
            d = fitz.open(p["src"])
            pg = d[p["page"]]
            pix = pg.get_pixmap(dpi=DPI)
            pix.save(os.path.join(folder, "jpg", p["file"]))
            d.close()
            typ, lvl, area = (None, None, None)
            if p.get("ocr"):                      # raster page: its title block is the only label
                typ, lvl, area = ocr_label(p["src"], p["page"])
            items.append({"file": p["file"], "type": typ or p["label"], "unit": area or "",
                          "levels": lvl or "", "page": p["page"] + 1})
        meta = {"developer": dev, "developer_name": dev.title(), "project": proj, "area": "",
                "source": "developer group capture: " + "; ".join(sorted(pack["sources"])),
                "note": "Pages rendered at %d dpi from the broker's own PDF. Nothing redrawn or cropped." % DPI,
                "items": items}
        json.dump(meta, open(os.path.join(folder, "meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    if skipped:
        print()
        print("SKIPPED (%d)" % len(skipped))
        for b, why in skipped:
            print("  %s" % b)
            print("      %s" % why)
    print()
    print("next: python scripts/build_plans_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
