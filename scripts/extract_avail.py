"""Automated availability extraction: developer sheets (PDF) -> data/avail/<developer>_<date>.json

Sources scanned: the Azimuth listener's capture folder (C:/Dev/azimuth-listener-naj/docs/**.pdf) and a manual
inbox (data/avail/inbox/). Each PDF is processed once (sha1 registry data/avail/_processed.json).
Text-layer PDFs use PyMuPDF words; image-only sheets are rendered at 200 dpi and read with RapidOCR (installed).
Rows are rebuilt by clustering word boxes on y, then parsed into the schema the board/drill/cards already use:
  {"source_file", "sheet_date", "received", "channel", "developer",
   "projects": [{"p", "completion", "plan", "units": [[unit, type, total_sqft, price_aed, view], ...]}]}
Acceptance: --check compares a result to a hand-verified JSON (unit sets per project) and prints the diff.
"""
import argparse, datetime as dt, glob, hashlib, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AVAIL = os.path.join(ROOT, "data", "avail")
INBOX = os.path.join(AVAIL, "inbox")
REG = os.path.join(AVAIL, "_processed.json")
LISTENER_DOCS = r"C:\Dev\azimuth-listener-naj\docs"
os.makedirs(INBOX, exist_ok=True)

TYPE_RX = re.compile(r"^(studio|\d\s*bed(room)?s?(\s*duplex)?|\d\s*b/?r(\s*duplex)?|office|retail|penthouse|shop)$", re.I)
NUM_RX = re.compile(r"^-?[\d,]+(\.\d+)?$")
DEV_HINTS = ["imtiaz", "emaar", "damac", "sobha", "binghatti", "danube", "azizi", "ellington", "samana", "nakheel", "meraas", "omniyat", "select", "object 1", "reportage"]


def nkey(t):
    return re.sub(r"[^a-z0-9]", "", str(t).lower())


_canon = None


def canonical_project(name, dev):
    """Snap an OCR'd header to the DLD register's project name for this developer (fuzzy on letters-only keys)."""
    global _canon
    if _canon is None:
        _canon = []
        try:
            import duckdb
            con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
            _canon = [r[0].strip() for r in con.execute("SELECT DISTINCT PROJECT_EN FROM transactions WHERE PROJECT_EN IS NOT NULL").fetchall()]
        except Exception:
            _canon = []
    k = nkey(name)
    pool = [c for c in _canon if dev and dev in c.lower()] or _canon
    import difflib
    best, score = None, 0.0
    for c in pool:
        r = difflib.SequenceMatcher(None, k, nkey(c)).ratio()
        if r > score:
            best, score = c, r
    if best and score >= 0.74 and nkey(best)[:4] == k[:4] and (bool(re.search(r"\d", k)) == bool(re.search(r"\d", nkey(best)))):
        return " ".join(w if w.lower() in ("by", "de", "of") else w.capitalize() for w in best.split())
    # fallback: re-space a glued OCR header (…BYIMTIAZ) and title-case it
    t = re.sub(r"(?i)by(%s)" % (dev or "x"), lambda m: " by " + m.group(1).capitalize(), name.replace(" ", ""))
    t = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])", " ", t)
    return " ".join(w if w.lower() == "by" else w.capitalize() for w in t.split())


def sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_type(t):
    t = t.strip().lower().replace("bedrooms", "bedroom")
    m = re.match(r"(\d)\s*(bed(room)?|b/?r)(\s*duplex)?", t)
    if m:
        return "%s B/R%s" % (m.group(1), " Duplex" if m.group(4) else "")
    if t.startswith("studio"):
        return "Studio"
    if t.startswith("office"):
        return "Office"
    if t.startswith("retail") or t.startswith("shop"):
        return "Retail"
    if t.startswith("penthouse"):
        return "Penthouse"
    return t.title()


def num(s):
    s = s.replace(",", "").replace("AED", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ word extraction
def words_text_layer(page):
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]  # x0,y0,x1,y1,text


_ocr = None


def words_ocr(page, dpi=200):
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    pix = page.get_pixmap(dpi=dpi)
    import numpy as np
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    res, _ = _ocr(img)
    out = []
    s = 72.0 / dpi
    for box, text, conf in (res or []):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append((min(xs) * s, min(ys) * s, max(xs) * s, max(ys) * s, text))
    return out


def rows_from_words(words, ytol=4.0):
    """Cluster words into rows by vertical centre, sort by x. Returns list of [(x0, text), ...]."""
    items = sorted(((w[1] + w[3]) / 2, w[0], w[4]) for w in words)
    rows, cur, cy = [], [], None
    for y, x, t in items:
        if cy is None or abs(y - cy) <= ytol:
            cur.append((x, t)); cy = y if cy is None else (cy + y) / 2
        else:
            rows.append(sorted(cur)); cur = [(x, t)]; cy = y
    if cur:
        rows.append(sorted(cur))
    return rows


# ------------------------------------------------------------------ row parsing
def split_cells(row):
    """OCR often glues a cell's words; re-split tokens that hold several numbers."""
    cells = []
    for x, t in row:
        parts = re.split(r"\s{2,}|\s(?=\d[\d,]*\.\d{2}\b)", t.strip())
        cells.extend(p for p in parts if p)
    return cells


def parse_row(cells):
    """unit | type | suite | balcony | total | price | view  (S.N column optional; view may be several words)."""
    if len(cells) < 5:
        return None
    # find the type token
    ti = next((i for i, c in enumerate(cells) if TYPE_RX.match(c.strip())), None)
    if ti is None or ti == 0:
        return None
    unit = cells[ti - 1].strip()
    unit = unit.replace("*", "").strip()
    if not re.match(r"^((office|retail|shop|villa|ph|p\d)-?)?[A-Z]?\d{1,4}[A-Z]?(-\d{1,3})?$", unit, re.I):
        return None
    nums = []
    j = ti + 1
    while j < len(cells) and NUM_RX.match(cells[j].replace(" ", "")):
        nums.append(num(cells[j])); j += 1
    view = " ".join(c for c in cells[j:]).strip()
    if len(nums) < 2:
        return None
    if len(nums) >= 4:
        suite, balcony, total, price = nums[0], nums[1], nums[2], nums[3]
    elif len(nums) == 3:
        suite, balcony, total, price = nums[0], None, nums[1], nums[2]
    else:
        suite, balcony, total, price = None, None, nums[0], nums[1]
    if price is not None and price < 50000:      # sanity: AED price, not sqft
        return None
    uid = re.sub(r"^([A-Za-z]{3,})-?(\d)", lambda m: m.group(1).upper() + "-" + m.group(2), unit.upper())
    return [uid, norm_type(cells[ti]), total, price, view or None, suite, balcony]


def parse_pdf(path):
    import fitz
    doc = fitz.open(path)
    projects, cur = [], None
    header_project, completion, plan = None, None, None
    dev = next((d for d in DEV_HINTS if d in os.path.basename(path).lower()), None)
    for page in doc:
        words = words_text_layer(page)
        mode = "text"
        if len(words) < 8:
            words = words_ocr(page); mode = "ocr"
        rows = rows_from_words(words)
        for row in rows:
            line = " ".join(t for _, t in row)
            low = line.lower()
            if dev is None:
                dev = next((d for d in DEV_HINTS if d in low), None)
            m = re.search(r"completion(?:date)?[:\-]?\s*(q\d|[a-z]+?)[,\s]*(\d{4})", re.sub(r"\s+", "", low))
            if m:
                completion = m.group(1).upper() + " " + m.group(2) if m.group(1).startswith("q") else m.group(1).title() + " " + m.group(2)
            m = re.search(r"\b(\d{2}/\d{2})\b", line)
            if m and ("plan" in low or "selling" in low or re.search(r"\b\d{2}/\d{2}\b", low)):
                plan = m.group(1)
            # project header: a line naming the developer + 'tower|residence|by <dev>' with no numbers
            flat = nkey(line)
            is_header = (not re.search(r"\d{3,}", line) and len(line) < 70 and not TYPE_RX.match(line)
                         and not flat.startswith("unitview") and "completiondate" not in flat and "sellingprice" not in flat
                         and re.search(r"(tower|residence|by" + (dev or "x") + r"|edition|boulevard|grand|horizon|bay|cove|house|walk|district)", flat)
                         and (dev is None or dev in flat or re.search(r"(tower|residences?)$", flat)))
            if is_header:
                cand = canonical_project(re.sub(r"\s+", " ", line).strip(" :-"), dev)
                if nkey(cand) != nkey(header_project or ""):
                    header_project = cand
                    cur = None
                continue
            rec = parse_row(split_cells(row))
            if rec:
                if cur is None or cur["p"] != (header_project or "Unknown project"):
                    cur = {"p": header_project or "Unknown project", "completion": completion, "plan": plan, "units": [], "_mode": mode}
                    projects.append(cur)
                cur["completion"] = cur["completion"] or completion
                cur["plan"] = cur["plan"] or plan
                cur["units"].append(rec[:5])
    # de-duplicate units within a project (OCR sometimes yields a row twice)
    for p in projects:
        seen, uniq = set(), []
        for u in p["units"]:
            if u[0] not in seen:
                seen.add(u[0]); uniq.append(u)
        p["units"] = uniq
    return dev, [p for p in projects if p["units"]]


def sheet_date_from(name, fallback):
    m = re.search(r"(\d{1,2})[.\-_/](\d{1,2})(?:[.\-_/](\d{2,4}))?", name)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(y) if y else fallback.year
        if y < 100:
            y += 2000
        try:
            return dt.date(y, mo, d).isoformat()
        except ValueError:
            pass
    return fallback.isoformat()


def process(path, received=None, force=False):
    reg = json.load(open(REG)) if os.path.exists(REG) else {}
    h = sha1(path)
    if h in reg and not force:
        return None, reg[h]
    dev, projects = parse_pdf(path)
    received = received or dt.date.fromtimestamp(os.path.getmtime(path))
    sheet_date = sheet_date_from(os.path.basename(path), received)
    out = {"source_file": os.path.basename(path), "sheet_date": sheet_date, "received": dt.date.today().isoformat(),
           "channel": "DEVELOPER AVAILABILITY group (listener capture)" if path.lower().startswith(LISTENER_DOCS.lower()) else "manual inbox",
           "developer": (dev or "unknown").title(), "extraction": "auto: " + ("ocr" if any(p.get("_mode") == "ocr" for p in projects) else "text"),
           "projects": [{k: v for k, v in p.items() if not k.startswith("_")} for p in projects]}
    fname = "%s_%s.json" % ((dev or "unknown"), sheet_date)
    dest = os.path.join(AVAIL, fname)
    if os.path.exists(dest) and not json.load(open(dest, encoding="utf-8")).get("extraction", "").startswith("auto"):
        # NEVER overwrite a hand-verified file (even with --force): write alongside as _auto
        dest = os.path.join(AVAIL, "%s_%s_auto.json" % ((dev or "unknown"), sheet_date))
    json.dump(out, open(dest, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    reg[h] = {"file": os.path.basename(path), "out": os.path.basename(dest), "when": dt.datetime.now().isoformat(timespec="seconds"),
              "units": sum(len(p["units"]) for p in projects)}
    json.dump(reg, open(REG, "w"), indent=1)
    return dest, reg[h]


def check(auto_path, truth_path):
    a = json.load(open(auto_path, encoding="utf-8")); t = json.load(open(truth_path, encoding="utf-8"))
    cu = lambda u: re.sub(r"^([A-Z]{3,})-?(\d)", r"-", str(u).upper().replace("*", "").strip())
    ta = {p["p"].lower(): {cu(u[0]): u for u in p["units"]} for p in t["projects"]}
    aa = {p["p"].lower(): {cu(u[0]): u for u in p["units"]} for p in a["projects"]}
    tot_t = sum(len(v) for v in ta.values()); hit = 0; field_ok = 0; field_n = 0
    for pname, units in ta.items():
        # match project by best token overlap
        import difflib
        best = max(aa, key=lambda k: difflib.SequenceMatcher(None, nkey(k), nkey(pname)).ratio(), default=None)
        au = aa.get(best, {})
        for unum, u in units.items():
            if unum in au:
                hit += 1
                for i in (1, 2, 3):
                    field_n += 1
                    x, y = au[unum][i], u[i]
                    if isinstance(y, (int, float)) and isinstance(x, (int, float)):
                        field_ok += abs(x - y) <= max(1, 0.005 * abs(y))
                    else:
                        field_ok += str(x).strip().lower() == str(y).strip().lower()
        print("  %-38s truth %2d  auto %2d  matched %2d  (auto project: %s)" % (pname[:38], len(units), len(au), sum(1 for k in units if k in au), best))
    print("UNITS matched %d/%d (%.0f%%) | type/sqft/price fields correct %d/%d (%.0f%%)" % (hit, tot_t, 100 * hit / max(1, tot_t), field_ok, field_n, 100 * field_ok / max(1, field_n)))
    extra = sum(len(v) for v in aa.values()) - hit
    print("extra (unmatched auto) units:", extra)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="process one PDF")
    ap.add_argument("--scan", action="store_true", help="process every new PDF in listener docs + inbox")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", nargs=2, metavar=("AUTO_JSON", "TRUTH_JSON"))
    a = ap.parse_args()
    if a.check:
        check(*a.check)
    elif a.file:
        dest, info = process(a.file, force=a.force)
        print("->", dest or "(already processed)", info)
    elif a.scan:
        pdfs = glob.glob(os.path.join(LISTENER_DOCS, "**", "*.pdf"), recursive=True) + glob.glob(os.path.join(INBOX, "*.pdf"))
        new = 0
        for p in sorted(pdfs, key=os.path.getmtime):
            dest, info = process(p, force=a.force)
            if dest:
                new += 1; print("extracted:", os.path.basename(p), "->", os.path.basename(dest), info["units"], "units")
        print("scan done: %d pdf(s) seen, %d new" % (len(pdfs), new))
    else:
        ap.print_help()
