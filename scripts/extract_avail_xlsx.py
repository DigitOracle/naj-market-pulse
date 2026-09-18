"""Developer availability posted as SPREADSHEETS, which extract_avail.py never read.

extract_avail.py and load_dev_group.py both glob *.pdf, so on 8 Sep 2026 Binghatti's whole portfolio
- three workbooks, one sheet per project - landed in the developer group and never reached the app.
Nothing failed; the files were simply invisible. This reader writes the SAME shape extract_avail.py
writes (data/avail/<dev>_<date>.json, projects[].units = [code, type, sqft, price, note]) and
registers each file's sha1 in _processed.json, so everything downstream treats it as one more sheet.

Every Binghatti tab has its own header layout - "Selling Price", "Asking Price", "Actual Price",
"Full Payment", "20 DP / 50 DP"; "Total Area", "TotalArea", "Total Area Sq.ft"; one header even omits
the Floor column its data carries. So columns are found by NAME, never by position, and a row is kept
only when it has a real unit code and a price that makes sense for its size. Placeholder rows ("0")
and empty tabs produce nothing rather than something wrong.

Unit types go through extract_avail.norm_type, the pipeline's one vocabulary, so the two readers
cannot drift apart.

Usage: python scripts/extract_avail_xlsx.py [--force] [--dry]
"""
import argparse, datetime as dt, glob, hashlib, io, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from extract_avail import norm_type  # noqa: E402  - one vocabulary for unit types

AVAIL = os.path.join(ROOT, "data", "avail")
REG = os.path.join(AVAIL, "_processed.json")
DOCS = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"

# Which developer a workbook belongs to, read from its unit codes and tab names rather than guessed.
DEVELOPERS = [("Binghatti", re.compile(r"binghatti|^B[A-Z]{2,4}\d?-|MYB6-|MBUL-|PMYB-|MBVI-|ONEB-", re.I))]

WORD_NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6"}
# The LIST price, which is what every other developer's sheet in this pipeline carries. Binghatti
# also prints "Full Payment" / "Full Cash" - a cash DISCOUNT (Ghost: 4.2M asking, 2.7M full payment) -
# so it is the last resort, after the 20%-down payment-plan price that stands in for a list price on
# tabs that print no asking price at all.
PRICE_HEADS = ["selling price", "asking price", "actual price", "20 dp", "20% dp",
               "full payment", "full cash", "100% full cash", "price"]
SIZE_HEADS = ["total area", "totalarea", "total area sq.ft"]
TYPE_WORDS = re.compile(r"bed|studio|retail|office|shop|penthouse|suite|duplex|villa|townhouse", re.I)
FLOOR_RX = re.compile(r"^(g|p\d?|b\d?|m|\d{1,3})$", re.I)


def unit_type(v):
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    t = re.sub(r"^(%s)\b" % "|".join(WORD_NUM), lambda m: WORD_NUM[m.group(1).lower()], t, flags=re.I)
    return norm_type(t) if TYPE_WORDS.search(t) else None


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def find(heads, names):
    for n in names:
        for i, h in enumerate(heads):
            if h == n or h.startswith(n):
                return i
    return None


def read_tab(ws):
    """-> (project, [units], note). A tab with no real rows returns no units, never a guess."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    title = next((str(c).strip() for r in rows[:2] for c in r if c), ws.title.strip())
    hi = next((i for i, r in enumerate(rows[:6])
               if any(str(c or "").strip().lower() in ("unit code", "code") for c in r)), None)
    if hi is None:
        return title, [], "no header row"
    heads = [re.sub(r"\s+", " ", str(c or "")).strip().lower() for c in rows[hi]]
    ci = find(heads, ["unit code", "code"])
    ti = find(heads, ["unit type", "typedescriptionen"])
    pi = find(heads, PRICE_HEADS)
    si = find(heads, SIZE_HEADS)
    proj_i = find(heads, ["project"])
    units, skipped = [], 0
    for r in rows[hi + 1:]:
        if not r or ci is None or ci >= len(r):
            continue
        code = str(r[ci] or "").strip()
        if not code or code == "0" or not re.search(r"[A-Za-z]", code) or not re.search(r"\d", code):
            continue
        # The type column, or the next cell if the header left one out (Ivory omits "Floor").
        t = unit_type(r[ti]) if ti is not None and ti < len(r) else None
        shift = 0
        if t is None:
            for k in range(ci + 1, min(len(r), ci + 5)):
                t = unit_type(r[k])
                if t:
                    shift = k - (ti if ti is not None else k)
                    break
        price = num(r[pi + shift]) if pi is not None and pi + shift < len(r) else None
        if not price or price < 50000:
            price = next((x for x in (num(c) for c in r[ci + 1:]) if x and x >= 50000), None)
        size = num(r[si + shift]) if si is not None and si + shift < len(r) else None
        if not (t and price):
            skipped += 1
            continue
        if size and not (150 <= size <= 60000 and 200 <= price / size <= 25000):
            size = None          # a size that makes nonsense of the price is worse than no size
        name = str(r[proj_i]).strip() if proj_i is not None and proj_i < len(r) and r[proj_i] else title
        units.append([code, t, round(size, 2) if size else None, round(price), name])
    project = re.sub(r"\s+AVA\w*.*$|\s+AVAILABILITY.*$", "", title, flags=re.I).strip()
    project = re.sub(r"^BINGHATT(?=\s)", "BINGHATTI", project, flags=re.I)   # the sheet's own typo
    return project, units, ("%d row(s) without a type or price" % skipped if skipped else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    reg = json.load(io.open(REG, encoding="utf-8")) if os.path.exists(REG) else {}

    by_dev = {}
    for f in sorted(glob.glob(os.path.join(DOCS, "*.xlsx"))):
        h = hashlib.sha1(open(f, "rb").read()).hexdigest()
        if h in reg and not a.force:
            print("  already read:", os.path.basename(f)[:70])
            continue
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        m = re.match(r"^(\d{13})_", os.path.basename(f))
        posted = dt.datetime.fromtimestamp(int(m.group(1)) / 1000, dt.timezone.utc) if m else None
        md = re.search(r"as of (\d{1,2})\w* (\w+) (\d{4})", os.path.basename(f), re.I)
        asof = (dt.datetime.strptime("%s %s %s" % md.groups(), "%d %B %Y").date().isoformat()
                if md else (posted.date().isoformat() if posted else None))
        dev = None
        projects = []
        for ws in wb.worksheets:
            proj, units, note = read_tab(ws)
            if units and not dev:
                probe = " ".join([ws.title] + [u[0] for u in units[:3]])
                dev = next((d for d, rx in DEVELOPERS if rx.search(probe)), None)
            if units:
                projects.append({"p": proj.title() if proj.isupper() else proj, "block": proj,
                                 "master": None, "completion": None, "plan": None, "units": units})
            print("   %-38s %4d units %s" % (ws.title.strip()[:38], len(units), note))
        wb.close()
        if not dev:
            print("  ! could not tell whose workbook this is - skipped:", os.path.basename(f)[:70])
            continue
        n = sum(len(p["units"]) for p in projects)
        print("  %s  %-10s %4d units in %d projects  <- %s" % (asof, dev, n, len(projects), os.path.basename(f)[14:70]))
        slot = by_dev.setdefault((dev, asof), {"files": [], "projects": [], "hashes": [],
                                               "received": posted.date().isoformat() if posted else asof})
        slot["files"].append(os.path.basename(f))
        slot["projects"].extend(projects)
        slot["hashes"].append((h, os.path.basename(f), n))

    for (dev, asof), s in by_dev.items():
        # One entry per project. Ghost sits in two of the three workbooks and Aquarise in both the
        # residential and the commercial one; separate same-named entries would read downstream as
        # two sheets of one project and invite exactly the phantom comparison W Residences made.
        merged = {}
        for pr in s["projects"]:
            k = pr["p"].strip().lower()
            if k in merged:
                have = {u[0] for u in merged[k]["units"]}
                merged[k]["units"].extend(u for u in pr["units"] if u[0] not in have)
            else:
                merged[k] = pr
        s["projects"] = list(merged.values())
        out = {"source_file": s["files"], "sheet_date": asof, "received": s["received"],
               "channel": "DEVELOPER AVAILABILITY group (listener capture)", "developer": dev,
               "extraction": "auto: xlsx", "projects": s["projects"]}
        dest = os.path.join(AVAIL, "%s_%s.json" % (re.sub(r"[^a-z0-9]", "", dev.lower()), asof))
        total = sum(len(p["units"]) for p in s["projects"])
        print("\n-> %s  %d units, %d projects" % (os.path.basename(dest), total, len(s["projects"])))
        if a.dry:
            continue
        json.dump(out, io.open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for h, fn, n in s["hashes"]:
            reg[h] = {"file": fn, "dest": os.path.basename(dest), "units": n,
                      "at": dt.datetime.now().isoformat(timespec="seconds"), "reader": "xlsx"}
    if not a.dry:
        json.dump(reg, io.open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
