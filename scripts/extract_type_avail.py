"""Type-level availability from a developer brochure ("Prices & Availability" tables).

Every project on the board arrives as a unit-by-unit sheet: one row per unit, with its own code,
area, price and view. Some projects never get one. Treppan Vision has been live in the group since
1 Sep 2026 and the only numbers anyone posted are a summary table in its broker pack - 463 units
across five types, with a starting area and a starting price each.

That is real, sourced availability and it was invisible to the app, because the pipeline only
understands unit rows. This reads the summary and writes it as a TYPE-LEVEL project, kept
deliberately distinct from unit-level inventory:

    {"p": "<project>", "level": "type", "units": [],
     "types": [{"t","n","from_sqft","from_aed","promo_aed"}], "source_note": "..."}

`units` stays empty ON PURPOSE. Synthesising 463 unit rows from a summary would put invented
inventory into the store where nothing could tell it from the real thing. The app shows the type
card and says where the numbers came from.

    python scripts/extract_type_avail.py --file "<pdf>" [--dry]
"""
import argparse, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
AVAIL = os.path.join(ROOT, "data", "avail")

HDR_RX = re.compile(r"UNIT\s*TYPE.*STARTING\s*(AREA|PRICE)", re.I)
# "Smart Studio 378 sq.ft 799,000"  /  "Offices · Levels 1 2 454 sq.ft 925,000"
ROW_RX = re.compile(r"^(?P<t>.+?)\s+(?P<area>[\d,]+(?:\.\d+)?)\s*sq\.?\s*ft\s+(?P<price>[\d,]{5,})\s*$", re.I)
# the continuation band under it: "252 735,080"  or  "48 N/A"
CONT_RX = re.compile(r"^(?P<n>\d{1,4})\s+(?P<promo>[\d,]{5,}|N/?A)\s*$", re.I)
TOTAL_RX = re.compile(r"\b(?P<n>\d{2,5})\s+units\b", re.I)


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def bands(page, tol=3.0):
    out, by = [], {}
    for w in page.get_text("words"):
        by.setdefault(round(w[1] / tol), []).append((w[0], w[4]))
    for k in sorted(by):
        line = " ".join(t for _, t in sorted(by[k])).strip()
        if line:
            out.append(line)
    return out


def parse_pdf(path):
    """-> {"project", "total_units", "location", "types":[...], "page"} or None."""
    import fitz
    doc = fitz.open(path)
    try:
        for pno, page in enumerate(doc):
            text = page.get_text()
            if not HDR_RX.search(re.sub(r"\s+", " ", text)):
                continue
            lines = bands(page)
            hi = next((i for i, l in enumerate(lines) if HDR_RX.search(l)), None)
            if hi is None:
                continue
            types, i = [], hi + 1
            while i < len(lines):
                m = ROW_RX.match(lines[i])
                if m:
                    row = {"t": re.sub(r"\s*[·|]\s*", " · ", m.group("t")).strip(),
                           "from_sqft": num(m.group("area")), "from_aed": num(m.group("price")),
                           "n": None, "promo_aed": None}
                    if i + 1 < len(lines):
                        c = CONT_RX.match(lines[i + 1])
                        if c:
                            row["n"] = int(c.group("n"))
                            row["promo_aed"] = num(c.group("promo"))
                            i += 1
                    types.append(row)
                elif types and not ROW_RX.match(lines[i]) and re.search(r"(?i)starting prices|pre-?launch offer", lines[i]):
                    break
                i += 1
            if not types:
                continue
            total = next((int(m.group("n")) for l in lines[:hi] for m in [TOTAL_RX.search(l)] if m), None)
            loc = None
            for j, l in enumerate(lines[:hi]):
                if l.strip().upper() == "LOCATION" and j + 1 < len(lines):
                    loc = lines[j + 1].strip()
                    break
            return {"total_units": total, "location": loc, "types": types, "page": pno + 1}
    finally:
        doc.close()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--project", help="project name (default: inferred from the filename)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    from extract_avail import dev_from_text

    res = parse_pdf(a.file)
    if not res:
        print("no 'Prices & Availability' table found in %s" % os.path.basename(a.file))
        return 1
    base = os.path.basename(a.file)
    dev = dev_from_text(base)
    if not dev:
        print("no developer resolves from %s - add its project to PROJECT_DEV first" % base)
        return 1
    proj = a.project or re.sub(r"\b(brok?re?|broker)\s*pack.*$", "", re.sub(r"^\d+_", "", os.path.splitext(base)[0]), flags=re.I)
    proj = re.sub(r"[-_]+", " ", proj).strip(" -_.").title()

    named = sum(t["n"] or 0 for t in res["types"])
    print("%s / %s - page %d" % (dev, proj, res["page"]))
    print("  location: %s" % (res["location"] or "-"))
    print("  %-30s %6s %12s %14s %14s" % ("type", "units", "from sq ft", "from AED", "promo AED"))
    for t in res["types"]:
        print("  %-30s %6s %12s %14s %14s" % (t["t"][:30], t["n"], t["from_sqft"],
                                              t["from_aed"], t["promo_aed"] or "-"))
    print("  units named in the table: %s   headline total: %s   %s"
          % (named, res["total_units"],
             "AGREE" if res["total_units"] and named == res["total_units"] else "DISAGREE - check"))
    if a.dry:
        return 0
    if res["total_units"] and named != res["total_units"]:
        print("  refusing to write: the table does not add up to its own headline")
        return 1

    out = {"p": proj, "level": "type", "units": [], "types": res["types"],
           "completion": None, "plan": None,
           "source_note": "type-level summary from the developer's broker pack (%s, p%d); "
                          "starting prices, not unit-by-unit availability" % (base, res["page"]),
           "location": res["location"], "total_units": res["total_units"]}
    # attach to the sheet that already owns this document, else a new one for its date
    target = None
    for p in sorted(glob.glob(os.path.join(AVAIL, "%s_*.json" % dev))):
        d = json.load(open(p, encoding="utf-8"))
        src = d.get("source_file") or []
        if base in (src if isinstance(src, list) else [src]):
            target = p
            break
    if not target:
        print("  no existing sheet lists %s - run extract_avail.py on it first" % base)
        return 1
    d = json.load(open(target, encoding="utf-8"))
    d["projects"] = [p for p in d.get("projects") or [] if p.get("p") != proj] + [out]
    json.dump(d, open(target, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  -> %s" % os.path.basename(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
