"""Pull EVERY open dataset on data.dubai (ex Dubai Pulse / Dubai Statistics Center) into data/raw_downloads — Kendall, 9 Sep 2026:
"you should be pulling everything, we don't know where good data lives".

Enumerates the metadata API (all pages), unions it with the 6 Sep catalogue export, downloads the latest extract of each dataset
through the same endpoint the portal's Download button uses, and keeps a manifest so the next pass only fetches what changed.

Files:   data/raw_downloads/dd/<entity>__<dataset>__<YYYY-MM-DD>.<csv|kml|xlsx|json>
Manifest data/raw_downloads/dd/MANIFEST.json  {dataset: {id, entity, title, category, file, bytes, rows, cols, fetched, status}}
Usage:   python scripts/datadubai_pull_all.py [--only name,name] [--force]
"""
import csv, glob, gzip, io, json, os, re, sys, time, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "dd"); os.makedirs(OUT, exist_ok=True)
MAN = os.path.join(OUT, "MANIFEST.json")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DigitAlchemy-Najma", "Accept": "application/json"}
CAT = glob.glob(os.path.join(ROOT, "data", "raw_downloads", "dubai_pulse_data_catalog_open_*.csv")) + glob.glob(
    r"C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Client_Engagements\RealEstateBroker\02_Execution\_from_downloads_09SEP2026\dubai_pulse_data_catalog_open_*.csv")


def get(u, raw=False, tries=3):
    for k in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=180); b = r.read()
            return b if raw else json.loads(b.decode("utf-8"))
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(4 * (k + 1))


def name_of(i):
    return str(i.get("name") or i.get("datasetName") or i.get("title") or "").strip()


def enumerate_metadata():
    """Every dataset the metadata API will list: page through without a search term, then sweep the alphabet for stragglers."""
    seen = {}
    def take(items):
        for i in items or []:
            if isinstance(i, dict) and i.get("id") and name_of(i): seen.setdefault(str(i["id"]), i)
    for page in range(1, 200):
        try:
            m = get(f"https://data.dubai/o/c/datasets?pageSize=100&page={page}")
        except Exception as e:
            print("  page", page, "failed:", str(e)[:80]); break
        items = m.get("items") if isinstance(m, dict) else m
        if not items: break
        before = len(seen); take(items)
        if len(seen) == before and page > 3: break
    for q in list("abcdefghijklmnopqrstuvwxyz") + ["dubai", "statistics", "index", "annual", "monthly", "by", "number", "total"]:
        try:
            m = get(f"https://data.dubai/o/c/datasets?search={q}&pageSize=100")
            take(m.get("items") if isinstance(m, dict) else m)
        except Exception:
            pass
    return seen


def catalogue_names():
    names = {}
    for f in CAT[:1]:
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            names.setdefault(r["dataset"], {"entity": r["entity"], "category": r.get("category", ""), "desc": r.get("dataset_description", "")[:200]})
    return names


def download(did, slug):
    """Every part of the dataset's latest extract. The payload lists one metadata entry per part (file_folder ..._0001, _0002 ...),
    each with a files list (the csv.gz plus a schema file). The first pass took one link and left multi-part registers partial."""
    d = get(f"https://data.dubai/o/dda/data-services/dataset-download?datasetId={did}&page=1&pageSize=50&sortDir=desc")
    entries = ((d.get("data") or {}).get("metadata") or []) if isinstance(d, dict) else []
    parts = []
    for e in entries:
        for f in e.get("files") or []:
            u = str(f.get("file_url") or "").replace("\\/", "/"); nm = str(f.get("file_name") or "")
            if u and not nm.lower().endswith((".json", ".txt", ".md")) and "schema" not in nm.lower(): parts.append((e.get("file_folder") or "", nm, u, int(f.get("file_size") or 0)))
    if not parts:
        s_ = json.dumps(d); links = [l.replace("\\/", "/") for l in re.findall(r"https://cdn\.data\.dubai[^\"'\\\s]+", s_)]
        parts = [("", "", l, 0) for l in links[:1]]
    if not parts: return None, "no file published", None
    # keep only the newest extract when the folders carry different timestamps
    stamps = sorted({re.sub(r"_\d{4}$", "", fo) for fo, _, _, _ in parts if fo}, reverse=True)
    if stamps: parts = [x for x in parts if not x[0] or re.sub(r"_\d{4}$", "", x[0]) == stamps[0]]
    parts.sort(key=lambda x: x[0])
    files = []; rows_total = 0; cols = None; bytes_total = 0
    for k, (fo, nm, u, sz) in enumerate(parts, 1):
        b = get(u, raw=True)
        if b[:2] == b"\x1f\x8b":
            try: b = gzip.decompress(b)
            except Exception: pass
        head = b[:64].lstrip()
        ext = "kml" if head.startswith(b"<?xml") and b"<kml" in b[:400] else "xml" if head.startswith(b"<?xml") else "json" if head[:1] in (b"{", b"[") else "xlsx" if b[:2] == b"PK" else "csv"
        suffix = f"__part{k:02d}" if len(parts) > 1 else ""
        pth = os.path.join(OUT, f"{slug}__{time.strftime('%Y-%m-%d')}{suffix}.{ext}"); open(pth, "wb").write(b); files.append(os.path.relpath(pth, ROOT)); bytes_total += len(b)
        if ext == "csv":
            try:
                txt = b.decode("utf-8-sig", errors="ignore"); rd = csv.reader(io.StringIO(txt)); c0 = next(rd, []); rows_total += sum(1 for _ in rd)
                if cols is None: cols = c0
            except Exception: pass
    return files[0], "ok", (rows_total if any(f.endswith(".csv") for f in files) else None, cols, bytes_total, files, len(parts))


def main():
    only = None
    if "--only" in sys.argv: only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    force = "--force" in sys.argv
    man = json.load(open(MAN, encoding="utf-8")) if os.path.exists(MAN) else {}
    print("enumerating the metadata API ..."); meta = enumerate_metadata(); print("  datasets listed by the API:", len(meta))
    cat = catalogue_names(); print("  datasets in the 6 Sep catalogue:", len(cat))
    by_name = {}
    for did, i in meta.items(): by_name.setdefault(name_of(i).lower().replace(" ", "_"), (did, i))
    todo = []
    for nm, (did, i) in by_name.items(): todo.append((nm, did, i.get("publisher") or i.get("entity") or cat.get(nm, {}).get("entity") or "", i.get("category") or cat.get(nm, {}).get("category") or ""))
    for nm, c in cat.items():
        if nm.lower() not in by_name:
            try:
                m = get(f"https://data.dubai/o/c/datasets?search={urllib.parse.quote(nm)}&pageSize=40"); items = m.get("items") if isinstance(m, dict) else m
                hit = next((x for x in items or [] if name_of(x).lower().replace(" ", "_") == nm.lower()), None)
                if hit: todo.append((nm.lower(), str(hit["id"]), c["entity"], c["category"]))
                else: man.setdefault(nm.lower(), {}).update({"entity": c["entity"], "status": "not in metadata API", "checked": time.strftime("%Y-%m-%d")})
            except Exception as e:
                man.setdefault(nm.lower(), {}).update({"status": "metadata lookup failed: " + str(e)[:60]})
    print("  to fetch:", len(todo)); ok = skipped = failed = 0; t0 = time.time()
    for n, (nm, did, ent, catg) in enumerate(sorted(todo), 1):
        if only and nm not in only: continue
        rec = man.get(nm, {})
        if not force and rec.get("status") == "ok" and rec.get("fetched", "")[:10] == time.strftime("%Y-%m-%d"): skipped += 1; continue
        slug = re.sub(r"[^a-z0-9_]+", "_", f"{str(ent).lower().replace(' ', '_')[:24]}__{nm}") if ent else nm
        try:
            p, status, info = download(did, slug)
            rec.update({"id": did, "entity": ent, "category": catg, "status": status, "fetched": time.strftime("%Y-%m-%dT%H:%M:%S")})
            if p: rec.update({"file": info[3][0], "files": info[3], "parts": info[4], "rows": info[0], "cols": (info[1] or [])[:40], "bytes": info[2]}); ok += 1
            else: failed += 1
            print(f"  [{n}/{len(todo)}] {nm:55s} {status:18s} {('%s rows' % f'{info[0]:,}') if info and info[0] is not None else ''}")
        except Exception as e:
            rec.update({"id": did, "entity": ent, "status": "error: " + str(e)[:90], "fetched": time.strftime("%Y-%m-%dT%H:%M:%S")}); failed += 1
            print(f"  [{n}/{len(todo)}] {nm:55s} ERROR {str(e)[:80]}")
        man[nm] = rec
        time.sleep(float(os.environ.get('DD_PAUSE', '0')))   # the CDN answered 403 after two hours of back-to-back pulls; pace the big registers
        if n % 10 == 0: json.dump(man, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(man, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"done: {ok} fetched · {skipped} already today · {failed} without a file or failed · {round(time.time() - t0)} s · manifest {MAN}")


if __name__ == "__main__":
    main()
