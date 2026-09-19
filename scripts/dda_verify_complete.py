"""dda_verify_complete.py -- did a finished PROD pull stop before the end of its dataset?

19 Sep 2026: ded_license_master was written as "ok" with 137,648 rows although pages 138, 139 and 250 still held new records (one
exact repeat of record 1 was mistaken for the API lapping back to the start; see split_page in dda_pull_all.py). Every dataset
that finished under the old test may be short the same way, so this checks them.

For each ok dataset with at least one full page of rows it hashes every record in the file, then finds the dataset's TRUE last page
(the API serves an EMPTY page once a page lies wholly past the end - so page availability is monotonic: double the page number until
a page comes back empty, then bisect) and reads that last page and the one before it. If the pull reached the real end, those records
are in the file (a boundary page may also lap back over records already held); any record NOT in the file proves it stopped early.
The first version probed only at 2x/4x/8x the pulled page count and read empty pages as "complete", which cannot see a dataset cut
off at more than half of its true size. About 12-15 API requests per dataset (shared rate budget).

    python scripts/dda_verify_complete.py [--only name,name] [--mark]     --mark sets truncated datasets to status 'truncated' in
                                                                          MANIFEST.json so the next pull re-pulls them
Report: data/raw_downloads/dda/prod/VERIFY.json
"""
import argparse, json, math, os, sys, time

import ijson

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dda_api as api
from dda_pull_all import rec_hash

ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROD = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod")
PAGE = 1000
MAX_PAGE = 9000
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def file_hashes(path):
    hs = set()
    with open(path, "rb") as f:
        for rec in ijson.items(f, "results.item", use_float=True):
            hs.add(rec_hash(rec))
    return hs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=""); ap.add_argument("--mark", action="store_true")
    a = ap.parse_args()
    c = api.cfg()
    c["DDA_BASE_URL"] = c["DDA_BASE_URL_PROD"]; c["DDA_ENV"] = "PROD"
    for k in ("APP_ID", "SECURITY_APP_IDENTIFIER", "CLIENT_ID", "CLIENT_SECRET"): c["DDA_" + k] = c["DDA_PROD_" + k]
    man = json.load(open(os.path.join(PROD, "MANIFEST.json"), encoding="utf-8"))
    only = set(x for x in a.only.split(",") if x)
    todo = sorted(((v["rows"], k) for k, v in man.items()
                   if v.get("status") in ("ok", "truncated") and v.get("rows", 0) >= PAGE and v.get("file") and os.path.exists(os.path.join(PROD, v["file"]))
                   and (not only or k.split("/")[1] in only)))
    api.log(f"ijson backend: {ijson.backend}; {len(todo)} datasets to verify (smallest first)")
    tok = api.token(c); report = {}
    for n, (rows, key) in enumerate(todo, 1):
        entity, dataset = key.split("/")
        t0 = time.time()
        hs = file_hashes(os.path.join(PROD, man[key]["file"]))
        base = f"{c['DDA_BASE_URL']}/secure/ddads/openapi/1.0.0/{entity}/{dataset}"
        cache = {}

        def fetch(pg):
            """records on page pg (None if the API would not answer)"""
            nonlocal tok
            if pg in cache: return cache[pg]
            code, raw, tok = api.auth_get(c, f"{base}?page={pg}&pageSize={PAGE}", tok)
            for _ in range(6):                                      # a deep page can time out (408) or hit the quota (429): wait and ask again
                if code not in (0, 408, 429, 502, 503, 504): break
                time.sleep(65 if code == 429 else 15); code, raw, tok = api.auth_get(c, f"{base}?page={pg}&pageSize={PAGE}", tok)
            cache[pg] = (json.loads(raw).get("results") or []) if code == 200 else None
            return cache[pg]

        expect = max(1, math.ceil(rows / PAGE)); lo, hi, unknown = 1, None, False
        g = fetch(expect)
        if g is None: unknown = True
        elif g: lo = expect
        step = max(expect, 1)
        while not unknown and hi is None:                           # double until a page comes back empty
            nxt = min(lo * 2, MAX_PAGE) if lo >= 1 else 1
            g = fetch(nxt)
            if g is None: unknown = True
            elif g: lo = nxt
            else: hi = nxt
            if not unknown and hi is None and lo >= MAX_PAGE: unknown = True   # still serving at the ceiling: cannot bound the end
        while not unknown and hi - lo > 1:                          # bisect between the last non-empty and the first empty page
            mid = (lo + hi) // 2; g = fetch(mid)
            if g is None: unknown = True
            elif g: lo = mid
            else: hi = mid
        probes = []
        if not unknown:
            for pg in sorted({lo, max(1, lo - 1)}):
                recs = fetch(pg)
                if recs is None: unknown = True; continue
                probes.append({"page": pg, "records": len(recs), "not_in_file": sum(1 for r in recs if rec_hash(r) not in hs)})
        checked = [p for p in probes if "not_in_file" in p]
        new = sum(p["not_in_file"] for p in checked)
        verdict = "TRUNCATED" if new else ("complete" if checked and not unknown else "unverified")
        report[key] = {"rows": rows, "file_hashes": len(hs), "true_last_page": None if unknown else lo, "probes": probes, "verdict": verdict}
        api.log(f"[{n}/{len(todo)}] {verdict:10s} {key} rows={rows:,} pulled>={expect} pages, true last page={'?' if unknown else lo}, "
                f"records not in file on it={new if checked else '?'} ({time.time()-t0:.0f}s, {len(cache)} requests)")
        del hs
        json.dump(report, open(os.path.join(PROD, "VERIFY.json"), "w", encoding="utf-8"), indent=1)
    bad = [k for k, v in report.items() if v["verdict"] == "TRUNCATED"]
    api.log(f"done: {len(bad)} truncated, {sum(1 for v in report.values() if v['verdict']=='complete')} complete, "
            f"{sum(1 for v in report.values() if v['verdict']=='unverified')} unverified")
    if a.mark and bad:
        mp = os.path.join(PROD, "MANIFEST.json")
        man = json.load(open(mp, encoding="utf-8"))                 # fresh read: the pull streams save this file too
        for k in bad:
            if man.get(k, {}).get("status") == "ok":
                man[k]["status"] = "truncated"; man[k]["note"] = "verify 19 Sep: the pull stopped early (the API still served records not in the file); re-pull"
        tmp = mp + f".{os.getpid()}.tmp"
        json.dump(man, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, mp)
        api.log("marked as 'truncated' in the manifest: " + ", ".join(bad))


if __name__ == "__main__":
    main()
