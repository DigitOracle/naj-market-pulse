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
LISTENER_DOCS = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"   # the developer group only - other groups post promotions, not inventories
os.makedirs(INBOX, exist_ok=True)

TYPE_RX = re.compile(r"^(studio|\d\s*bed(room)?s?(\s*duplex)?|\d\s*b/?r(\s*duplex)?|office|retail|penthouse|shop)$", re.I)
NUM_RX = re.compile(r"^-?[\d,]+(\.\d+)?$")
DEV_HINTS = ["imtiaz", "fakhruddin", "emaar", "damac", "sobha", "binghatti", "danube", "azizi", "ellington", "samana", "nakheel", "meraas", "omniyat", "select", "object 1", "reportage", "arada", "beyond", "iman", "zaya", "palma"]
# a sheet often names only the project ("TREPPAN TOWER - INVENTORY"); these map a project word to the developer on the board
PROJECT_DEV = {"treppan": "fakhruddin", "maimoon": "fakhruddin", "hatimi": "fakhruddin", "symphony": "imtiaz", "westwood": "imtiaz",
               "passo": "beyond", "kanyon": "beyond", "chateau": "beyond", "talea": "beyond", "soulever": "beyond", "hado": "beyond", "arancia": "beyond", "saria": "beyond", "orise": "beyond"}
# BEYOND's export: "Created by: <name>" / "dd-MMM-yyyy hh:mm" / a wrapped header (Building | Unit Code | Bedroom Type | Total Area (Sqft) |
# Unit Sub-Type | Unit Orientation | Selling Price (AED)); one row per unit, orientation may wrap onto the next line.
BEY_CODE_RX = re.compile(r"^[A-Z]{2,6}\d?[A-Z]?/[A-Z]?\d{1,3}/[A-Z]?\d{1,4}$")
BEY_TYPE_RX = re.compile(r"^(\d(BR|BD|B)\+?|studio|penthouse|retail|office|townhouse|villa)$", re.I)
BEY_DATE_RX = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{4})\s")
INV_TITLE_RX = re.compile(r"^(?P<title>.+?)\s*-\s*INVENTORY\s*as\s*\(?\s*(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})\s*\)?", re.I)
INV_HEADER = "unitcodeviewunitnofloorunittypetotalareasalevalue"


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
    t = t.strip().lower().replace("bedrooms", "bedroom").replace("p.house", "penthouse")
    m = re.match(r"(\d)\s*(bed(room)?|b/?r|bhk)(\s*(duplex|penthouse))?", t)
    if m:
        return "%s B/R%s" % (m.group(1), (" " + m.group(5).title()) if m.group(5) else "")
    if t.startswith("duplex"):
        return "Duplex"
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
    uid = re.sub(r"^([A-Za-z]{3,})[\s-]?(\d)", lambda m: m.group(1).upper() + "-" + m.group(2), unit.upper())
    if view:
        view = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", view)                       # LagoonView -> Lagoon View
        view = re.sub(r"\s*/\s*", " / ", view)
        view = re.sub(r"\s*view\s*$", "", view, flags=re.I).strip()          # drop the trailing 'View'
        view = re.sub(r"\s+", " ", view)
    return [uid, norm_type(cells[ti]), total, price, view or None, suite, balcony]


INV_CODE_RX = re.compile(r"^[A-Z]{2,6}(-[A-Z0-9]+){1,4}$")
INV_TYPE_START = re.compile(r"^(\d|studio|duplex|retail|office|penthouse|p\.house|shop|villa|townhouse)", re.I)


def parse_inventory_row(cells):
    """code | view words | unit no | floor (token or words) | type words | area sq.ft | price  -> [uid, type, total, price, view]"""
    if len(cells) < 6 or not INV_CODE_RX.match(cells[0].strip()):
        return None
    try:
        k = next(i for i, c in enumerate(cells) if c.strip().lower().replace(" ", "") in ("sq.ft", "sqft", "sq.ft.", "sq.m", "sqm"))
    except StopIteration:
        return None
    total = num(cells[k - 1]); price = num(cells[k + 1]) if k + 1 < len(cells) else None
    if total is None or price is None or price < 50000:
        return None
    mid = [c.strip() for c in cells[1:k - 1]]
    u = next((i for i, c in enumerate(mid) if re.fullmatch(r"[A-Z]?\d{1,4}[A-Z]?", c)), None)   # unit number: first numeric-ish token
    if u is None:
        return None
    view = " ".join(mid[:u]); rest = mid[u + 1:]
    t = next((i for i, c in enumerate(rest) if INV_TYPE_START.match(c)), None)
    if t is None:
        floor, typ = " ".join(rest), ""
    else:
        floor, typ = " ".join(rest[:t]), " ".join(rest[t:])
    # a bare floor number followed by a "1 BHK" type: the first numeric of rest is the floor, not the type
    if t == 0 and len(rest) >= 3 and re.fullmatch(r"\d{1,2}", rest[0]) and re.fullmatch(r"\d", rest[1]):
        floor, typ = rest[0], " ".join(rest[1:])
    view = re.sub(r"\s*view\s*$", "", re.sub(r"\s*/\s*", " / ", view), flags=re.I).strip()
    if view.lower() in ("default", "default view", ""):
        view = None
    uid = cells[0].strip().upper()
    return [uid, norm_type(typ) if typ else "Unit", total, price, view, mid[u], floor or None]


def parse_beyond_row(cells):
    """building words | CODE | type | area | sub-type tokens | orientation words | price  -> [uid, type, total, price, view, building]"""
    ci = next((i for i, c in enumerate(cells) if BEY_CODE_RX.match(c.strip())), None)
    if ci is None or ci + 3 >= len(cells):
        return None
    price = num(cells[-1]); total = num(cells[ci + 2])
    if price is None or price < 50000 or total is None or not BEY_TYPE_RX.match(cells[ci + 1].strip()):
        return None
    building = " ".join(cells[:ci]).replace("'", "").strip()
    building = re.sub(r"\s+by\s+beyond", "", building, flags=re.I).strip()
    tail = [c.strip() for c in cells[ci + 3:-1]]
    # sub-type is the leading run of code-like tokens (T7_1BR, 2B-4, B-5, PODIUM, "1 BED A"); the orientation is what follows
    k = 0
    while k < len(tail) and (re.search(r"[_\d]", tail[k]) or tail[k].isupper() and len(tail[k]) <= 6 or tail[k].lower() in ("bed", "podium", "maid", "study", "duplex", "simplex")):
        k += 1
    view = " ".join(tail[k:]).strip(" /")
    view = re.sub(r"\s*/\s*", " / ", view)
    return [cells[ci].strip().upper(), norm_type(cells[ci + 1].strip().replace("BD", "BR").replace("+", "")), total, price, view or None, building or None]


def parse_pdf(path):
    import fitz
    doc = fitz.open(path)
    projects, cur = [], None
    header_project, completion, plan = None, None, None
    dev = next((d for d in DEV_HINTS if d in os.path.basename(path).lower()), None)
    inv_title, inv_date, inv_block, prev_line, inv_mode = None, None, None, "", False
    bey_date, bey_building, pending_view = None, None, None
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
                dev = next((d for d in DEV_HINTS if d in low), None) or next((v for k, v in PROJECT_DEV.items() if k in low), None)
            # --- inventory format (Fakhruddin et al.): "<PROJECT> - INVENTORY as (m/d/yyyy)", sections, a fixed column header
            mt = INV_TITLE_RX.match(line.strip())
            if mt:
                inv_title = re.sub(r"\s+by\s+\w+$", "", mt.group("title").strip(), flags=re.I)
                try: inv_date = dt.date(int(mt.group("y")), int(mt.group("m")), int(mt.group("d"))).isoformat()
                except ValueError: inv_date = None
                inv_mode = True; prev_line = ""; continue
            if inv_mode and nkey(line) == INV_HEADER:
                inv_block = prev_line.strip() if prev_line and not re.search(r"\d{3,}", prev_line) else inv_block
                prev_line = ""; continue
            if inv_mode:
                rec = parse_inventory_row(split_cells(row))
                if rec:
                    pname = canonical_project((inv_title or "Unknown project").title(), dev)   # title-case first: an all-caps title survives the fallback re-spacing
                    if cur is None or cur["p"] != pname or cur.get("block") != inv_block:
                        cur = {"p": pname, "block": inv_block, "completion": completion, "plan": plan, "units": [], "_mode": mode}
                        projects.append(cur)
                    cur["units"].append(rec[:5]); prev_line = line; continue
                # a one-word continuation row ("P.HOUSE") belongs to the type of the unit above it
                if cur and cur["units"] and re.fullmatch(r"[A-Za-z.]+", line.strip()) and INV_TYPE_START.match(line.strip()):
                    cur["units"][-1][1] = norm_type((cur["units"][-1][1].replace(" B/R", " BHK")) + " " + line.strip()); continue
                prev_line = line; continue
            # --- BEYOND export
            md = BEY_DATE_RX.match(line.strip())
            if md and not bey_date:
                try: bey_date = dt.datetime.strptime(md.group(0).strip(), "%d-%b-%Y").date().isoformat()
                except ValueError: bey_date = None
                dev = dev or "beyond"; continue
            if bey_date:
                cells = [t for _, t in row]
                rec = parse_beyond_row(cells)
                if os.environ.get('AVAIL_DEBUG'): print('DBG', repr(line[:50]), '| rec', bool(rec), '| bld', bey_building)
                if rec:
                    if not rec[5] and bey_building: rec[5] = bey_building
                    if pending_view and not rec[4]: rec[4] = pending_view
                    pending_view = None
                    pname = canonical_project(rec[5] or "Unknown project", dev)
                    if cur is None or cur["p"] != pname:
                        cur = {"p": pname, "completion": completion, "plan": plan, "units": [], "_mode": mode, "_sheet_date": bey_date}
                        projects.append(cur)
                    cur["units"].append(rec[:5]); continue
                sl = line.strip()
                if re.fullmatch(r"Building [A-Z0-9]{1,2}", sl):                       # "Building B": a sub-label, not a name
                    continue
                if re.search(r"by\s+beyond", sl, re.I) or (re.fullmatch(r"[A-Za-z][A-Za-z0-9 ']{2,40}", sl) and sl.split()[0][0].isupper() and len(sl.split()) <= 5 and not re.search(r"\d", sl) and sl.lower().split()[0] not in ("beach","ocean","sea","garden","zen","skyline","forest","botanical","evermore","marjan","dubai","cove","park","green","sunset","villa","golf","marina","community","the","bedroom","selling","total","unit","created","building","type","price","area")):
                    bey_building = re.sub(r"\s+by\s+beyond", "", sl, flags=re.I).replace("'", "").strip(); continue   # a name-only row names the building for the rows that follow
                # a wrapped orientation ("Beach / Ocean / Zen", "Garden", "Botanical Garden /"): to the unit above if it has none, else held for the next
                if cur and cur["units"] and not re.search(r"\d", sl) and len(sl) < 40 and not sl.lower().startswith(("created", "total", "bedroom", "type", "(sqft")):
                    u = cur["units"][-1]
                    if not u[4]: u[4] = re.sub(r"\s*/\s*", " / ", sl.strip(" /")) or None
                    else: pending_view = re.sub(r"\s*/\s*", " / ", sl.strip(" /")) or None
                continue
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
    out = [p for p in projects if p["units"]]
    if inv_date:
        for p in out: p.setdefault("_sheet_date", inv_date)
    return dev, out


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
    stated = next((p.get("_sheet_date") for p in projects if p.get("_sheet_date")), None)
    sheet_date = stated or sheet_date_from(re.sub(r"^\d{13}_", "", os.path.basename(path)), received)   # strip the capture timestamp
    out = {"source_file": os.path.basename(path), "sheet_date": sheet_date, "received": dt.date.today().isoformat(),
           "channel": "DEVELOPER AVAILABILITY group (listener capture)" if path.lower().startswith(LISTENER_DOCS.lower()) else "manual inbox",
           "developer": (dev or "unknown").title(), "extraction": "auto: " + ("ocr" if any(p.get("_mode") == "ocr" for p in projects) else "text"),
           "projects": [{k: v for k, v in p.items() if not k.startswith("_")} for p in projects]}
    fname = "%s_%s.json" % ((dev or "unknown"), sheet_date)
    dest = os.path.join(AVAIL, fname)
    if os.path.exists(dest) and not json.load(open(dest, encoding="utf-8")).get("extraction", "").startswith("auto"):
        # NEVER overwrite a hand-verified file (even with --force): write alongside as _auto
        dest = os.path.join(AVAIL, "%s_%s_auto.json" % ((dev or "unknown"), sheet_date))
    # Fakhruddin posts one PDF per project: the developer's sheet for the day is the union of them, never the last one to land
    if os.path.exists(dest):
        try:
            prev = json.load(open(dest, encoding="utf-8"))
            if prev.get("extraction", "").startswith("auto") and prev.get("developer") == out["developer"]:
                keep = [p for p in prev.get("projects", []) if (p.get("p"), p.get("block")) not in {(q.get("p"), q.get("block")) for q in out["projects"]}]
                out["projects"] = keep + out["projects"]
                srcs = prev.get("source_file"); srcs = srcs if isinstance(srcs, list) else [srcs]
                out["source_file"] = sorted(set(srcs + [out["source_file"]]))
        except Exception:
            pass
    json.dump(out, open(dest, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    reg[h] = {"file": os.path.basename(path), "out": os.path.basename(dest), "when": dt.datetime.now().isoformat(timespec="seconds"),
              "units": sum(len(p["units"]) for p in projects)}
    json.dump(reg, open(REG, "w"), indent=1)
    return dest, reg[h]


def check(auto_path, truth_path):
    a = json.load(open(auto_path, encoding="utf-8")); t = json.load(open(truth_path, encoding="utf-8"))
    cu = lambda u: re.sub(r"^([A-Z]{3,})[\s-]?(\d)", r"-", str(u).upper().replace("*", "").strip())
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
