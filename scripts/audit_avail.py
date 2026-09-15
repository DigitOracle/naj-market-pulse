"""Second opinion on every captured availability document: what the page says vs what the store holds.

The developer group is Najma's inventory input, and it has failed silently three times (a brochure
displacing real units, a 20 MB cap eating broker packs, a unit-type gate that rejected "BHK").
Each time nothing errored - the numbers just got smaller. This audit exists so that cannot happen
again unnoticed: it re-reads the PDFs on disk with a DELIBERATELY LOOSE detector that shares no
code path with the extractor, then compares. Agreement is evidence; a gap is a finding.

    python scripts/audit_avail.py            # table + findings, exit 1 if anything is unexplained
    python scripts/audit_avail.py --json     # machine-readable, for the daily run

Exit codes: 0 clean, 1 unexplained loss or unmapped documents, 2 could not run.
"""
import argparse, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DOCS = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"
GRAPH = os.path.join(ROOT, "data", "graph", "najma.duckdb")

# Loose, independent detector. It must NOT import the extractor's gate - a check that reuses the
# code it is checking only ever confirms itself. Anything that reads like "a unit with a price"
# counts here, and the extractor is expected to justify every row it did not take.
BED_ISH = re.compile(r"\b(studio|\d\s*(?:bed\w*|b\s*/?\s*r|bhk|bd|br)\b)", re.I)
PRICE_ISH = re.compile(r"\b\d{1,3}(?:,\d{3}){1,3}(?:\.\d{2})?\b|\b\d{6,9}(?:\.\d{2})?\b")
MIN_PRICE = 50000.0


def money(tok):
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return 0.0


def detect_rows(lines):
    """Visual rows that read like a priced unit. Returns (count, sample_of_types)."""
    n, types = 0, []
    for line in lines:
        if not BED_ISH.search(line):
            continue
        if not any(money(t) >= MIN_PRICE for t in PRICE_ISH.findall(line)):
            continue
        n += 1
        m = BED_ISH.search(line)
        if m:
            types.append(re.sub(r"\s+", " ", m.group(1)).strip())
    return n, types


def page_lines(path, tol=3.0):
    """Rebuild visual rows from word boxes: a table row is a band of y, not a line of text.
    Independently implemented from the extractor's clustering - the point is a second opinion
    on WHICH ROWS EXIST, so it must not borrow the gate that decides which rows count."""
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(path)
    except Exception:
        return None
    out = []
    for page in doc:
        try:
            words = page.get_text("words")          # x0, y0, x1, y1, word, block, line, word_no
        except Exception:
            continue
        bands = {}
        for w in words:
            key = round(w[1] / tol)
            bands.setdefault(key, []).append((w[0], w[4]))
        for key in sorted(bands):
            toks = [t for _, t in sorted(bands[key])]
            out.append(" ".join(toks))
    doc.close()
    return out


def stored():
    """{sheet_file: units}, {sheet_file: (developer, [source_files])}, and the dev_doc state map."""
    import duckdb
    c = duckdb.connect(GRAPH, read_only=True)
    units = dict(c.execute("select sheet_file, count(*) from dev_sheet_unit group by 1").fetchall())
    sheets = {}
    for sf, dev, src in c.execute("select sheet_file, developer, source_files from dev_sheet").fetchall():
        try:
            files = json.loads(src) if src else []
        except Exception:
            files = []
        sheets[sf] = (dev, files)
    docs = {}
    for fn, into, u, parsed in c.execute("select file_name, parsed_into, units, parsed from dev_doc").fetchall():
        docs[fn] = {"parsed_into": into, "units": u, "parsed": bool(parsed)}
    c.close()
    return units, sheets, docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--docs", default=DOCS)
    a = ap.parse_args()

    if not os.path.isdir(a.docs):
        print("capture folder not found: %s" % a.docs, file=sys.stderr)
        return 2
    try:
        units, sheets, docs = stored()
    except Exception as e:
        print("cannot read the store: %s" % e, file=sys.stderr)
        return 2

    file_to_sheet = {}
    for sf, (dev, files) in sheets.items():
        for f in files:
            file_to_sheet[f] = sf

    # Documents whose priced rows are a TYPE-LEVEL summary (extract_type_avail.py), not unit rows. Their
    # "Studio 378 sq ft 799,000" lines are accounted for by the type card, so zero unit rows is correct,
    # not a loss. Without this the audit flagged Treppan Vision's broker pack forever.
    type_level_docs = set()
    for jp in glob.glob(os.path.join(ROOT, "data", "avail", "*_20*.json")):
        try:
            jd = json.load(open(jp, encoding="utf-8"))
        except Exception:
            continue
        for pr in jd.get("projects") or []:
            if pr.get("level") == "type":
                m = re.search(r"\(([^,()]+\.pdf)", pr.get("source_note") or "", re.I)
                if m:
                    type_level_docs.add(m.group(1).strip())

    # The listener re-saves the same document under a new timestamp on every re-delivery, so the
    # folder holds many byte-identical copies. Audit each distinct DOCUMENT once, judged by the
    # copy the store actually used - otherwise duplicates bury the real findings.
    import hashlib
    by_hash = {}
    for path in sorted(glob.glob(os.path.join(a.docs, "*.pdf"))):
        try:
            with open(path, "rb") as fh:
                h = hashlib.sha1(fh.read()).hexdigest()
        except OSError:
            continue
        by_hash.setdefault(h, []).append(path)

    chosen = []
    for h, paths in by_hash.items():
        pick = next((p for p in paths if os.path.basename(p) in file_to_sheet), paths[0])
        chosen.append((pick, len(paths)))

    rows, findings = [], []
    for path, copies in sorted(chosen):
        base = os.path.basename(path)
        lines = page_lines(path)
        if lines is None:
            findings.append({"file": base, "kind": "unreadable", "detail": "no text layer could be read"})
            continue
        found, types = detect_rows(lines)
        sheet = file_to_sheet.get(base)
        d = docs.get(base) or {}
        rec = {"file": base, "detected": found, "sheet": sheet, "copies": copies,
               "developer": (sheets.get(sheet) or (None, None))[0],
               "doc_units": d.get("units"), "parsed": d.get("parsed"),
               "types": sorted(set(types))[:8]}
        rows.append(rec)

        if found and sheet is None:
            findings.append({"file": base, "kind": "orphan",
                             "detail": "%d priced unit rows on the page, document belongs to no sheet" % found})
        elif found and base in type_level_docs:
            pass                                   # summary rows, captured as a type-level card
        elif found and (d.get("units") or 0) == 0 and d.get("parsed"):
            findings.append({"file": base, "kind": "parsed_to_nothing",
                             "detail": "%d priced unit rows on the page, 0 units stored" % found})
        elif found and (d.get("units") or 0) and found > (d.get("units") or 0):
            findings.append({"file": base, "kind": "short",
                             "detail": "page shows %d priced unit rows, store holds %d" % (found, d["units"])})
        if not d:
            findings.append({"file": base, "kind": "unregistered",
                             "detail": "on disk but absent from dev_doc"})

    for sf, (dev, files) in sorted(sheets.items()):
        if (dev or "").lower() in ("unknown", "none", ""):
            findings.append({"file": sf, "kind": "unmapped_developer",
                             "detail": "sheet filed under %r, %d source documents" % (dev, len(files))})

    if a.json:
        print(json.dumps({"documents": rows, "findings": findings}, indent=1))
    else:
        print("%-62s %9s %7s  %s" % ("document", "on page", "stored", "sheet"))
        print("-" * 108)
        for r in rows:
            flag = " " if (r["detected"] or 0) <= (r["doc_units"] or 0) else "!"
            print("%s%-61s %9s %7s  %s" % (flag, r["file"][:61], r["detected"],
                                           "-" if r["doc_units"] is None else r["doc_units"],
                                           r["sheet"] or "(none)"))
        print()
        if findings:
            print("FINDINGS (%d)" % len(findings))
            for f in findings:
                print("  [%s] %s" % (f["kind"], f["file"]))
                print("         %s" % f["detail"])
        else:
            print("No findings: every priced row on every page is accounted for in the store.")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
