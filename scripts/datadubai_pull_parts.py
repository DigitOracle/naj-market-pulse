"""datadubai_pull_parts.py -- fetch every part of a data.dubai portal extract, gzipped, verified (1 Oct 2026).

Why. The portal publishes its large registers as N gzipped parts under one dated folder (rent_contracts_2026-09-30_00-46-44_0001
... _0011). datadubai_pull_all.py decompresses each part to disk - 11 x 480 MB for Ejari - and the disk is 96% full. This
keeps the .csv.gz (57 MB a part), re-reads the signed link per part (links expire after 600 s) and verifies each part by
decompressing it end to end before it counts. load_portal_parts.py reads .csv.gz directly.

    python scripts/datadubai_pull_parts.py rent_contracts [customers_master_data ...]
Exit 0: every part of the newest extract is on disk and intact (already-held parts are verified, not re-downloaded).
Exit 1: a part could not be fetched after 4 tries.  Exit 3: the portal lists no files for a dataset.
"""
import gzip, json, os, re, shutil, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
UA = {"User-Agent": "Mozilla/5.0 (research; naj-market-pulse)"}
DATASETS = {                                    # short name -> (portal dataset id, file stem on disk)
    "rent_contracts": (468586, "dld__rent_contracts"),
    "customers_master_data": (1247436, "customers_master_data"),
}


def listing(did):
    url = "https://data.dubai/o/dda/data-services/dataset-download?datasetId=%d&page=1&pageSize=50&sortDir=desc" % did
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
    return ((d.get("data") or {}).get("metadata") or [])


def newest_extract(entries):
    """(stamp 'YYYY-MM-DD', [(part_no, csv.gz url, size)]) for the newest folder timestamp."""
    parts = {}
    for e in entries:
        m = re.search(r"_(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}_(\d{4})$", e.get("file_folder") or "")
        if not m:
            continue
        gz = [f for f in e.get("files") or [] if str(f.get("file_name", "")).lower().endswith(".csv.gz")]
        if gz:
            parts.setdefault(m.group(1), []).append((int(m.group(2)), gz[0]["file_url"].replace("\\/", "/"), int(gz[0].get("file_size") or 0)))
    if not parts:
        return None, []
    stamp = max(parts)
    return stamp, sorted(parts[stamp])


def verify(path):
    n = 0
    with gzip.open(path, "rb") as g:
        for _ in g:
            n += 1
    return n


def pull(short):
    did, stem = DATASETS[short]
    stamp, parts = newest_extract(listing(did))
    if not parts:
        print("%s: portal lists no csv.gz parts" % short); return 3
    os.makedirs(DD, exist_ok=True)
    total = 0
    for k, _, _ in parts:
        out = os.path.join(DD, "%s__%s__part%02d.csv.gz" % (stem, stamp, k))
        for attempt in range(4):
            try:
                if not os.path.exists(out):
                    _, url, _ = [p for p in newest_extract(listing(did))[1] if p[0] == k][0]   # a fresh signed link
                    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=900) as r, open(out + ".tmp", "wb") as w:
                        shutil.copyfileobj(r, w, 1 << 22)
                    os.replace(out + ".tmp", out)
                n = verify(out)
                total += n
                print("%s %s part%02d %s bytes %s lines ok" % (time.strftime("%H:%M:%S"), stamp, k, format(os.path.getsize(out), ","), format(n, ",")), flush=True)
                break
            except Exception as e:
                print("%s part%02d attempt %d failed: %s" % (time.strftime("%H:%M:%S"), k, attempt + 1, str(e)[:160]), flush=True)
                for p in (out, out + ".tmp"):
                    if os.path.exists(p):
                        os.remove(p)
                time.sleep(20)
        else:
            return 1
    print("%s: extract %s, %d parts, %s lines including headers" % (short, stamp, len(parts), format(total, ",")))
    return 0


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["rent_contracts"]
    rc = 0
    for n in names:
        rc = max(rc, pull(n))
    sys.exit(rc)


if __name__ == "__main__":
    main()
