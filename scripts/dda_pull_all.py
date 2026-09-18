"""dda_pull_all.py -- pull every dataset the data.dubai API profile can reach.

Reads data/raw_downloads/dda/api_catalogue.json (scripts/dda_api_catalogue.py), calls each endpoint through the governed API
(scripts/dda_api.py: bearer token, 60 requests/minute, 1,000 rows per page) and writes one JSON per dataset plus a manifest.
Resumable: a dataset already pulled today is skipped unless --force. The staging environment serves samples (5 masked rows per
table, seen 10 Sep 2026), so on STG this captures schema + sample for every endpoint = the validation evidence the production
request needs; run again with --prod once production credentials are in the env file.

    python scripts/dda_pull_all.py [--prod] [--force] [--only dld,dm,rta] [--max-pages 2000]
"""
import argparse, hashlib, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dda_api as api

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CAT = os.path.join(ROOT, "data", "raw_downloads", "dda", "api_catalogue.json")
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default=""); ap.add_argument("--max-pages", type=int, default=2000); ap.add_argument("--page-size", type=int, default=1000)
    # 15 Sep 2026 (Kendall: the weekly pull never refreshed anything). An "ok" dataset was skipped forever unless --force, and the
    # runner never passed --force; a full pull is ~13.6 h of API time, which no 8 h task can hold. The weekly run now rotates:
    #   --stale-days N       re-pull an ok dataset once its last pull is N days old (0 = the old behaviour: ok is never re-pulled)
    #   --budget-minutes M   stop starting new datasets after M minutes, save the manifest, exit 3 "PARTIAL" (resumes next run)
    #   --dataset-minutes D  give up on one dataset after D minutes; a refresh that fails keeps the last good pull
    # Stalest first, so every dataset comes round in turn.
    ap.add_argument("--stale-days", type=int, default=0); ap.add_argument("--budget-minutes", type=int, default=0)
    ap.add_argument("--dataset-minutes", type=int, default=0)
    # 18 Sep: run one big register (dld_transactions) in its own process beside the main pull
    ap.add_argument("--datasets", default="", help="only these dataset names, comma-separated")
    ap.add_argument("--skip-datasets", default="", help="leave these dataset names to another process")
    a = ap.parse_args()
    c = api.cfg()
    if a.prod:                                        # PROD has its own credential set (issued 18 Sep 2026)
        c["DDA_BASE_URL"] = c["DDA_BASE_URL_PROD"]; c["DDA_ENV"] = "PROD"
        for k in ("APP_ID", "SECURITY_APP_IDENTIFIER", "CLIENT_ID", "CLIENT_SECRET"):
            c["DDA_" + k] = c["DDA_PROD_" + k]
    env = "prod" if a.prod else c["DDA_ENV"].lower()
    out_dir = os.path.join(ROOT, "data", "raw_downloads", "dda", env); os.makedirs(out_dir, exist_ok=True)
    man_path = os.path.join(out_dir, "MANIFEST.json")
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    cat = json.load(open(CAT, encoding="utf-8"))["rows"]
    todo = [r for r in cat if r["endpoints"]]
    if a.only: todo = [r for r in todo if r["entity"] in set(a.only.split(","))]
    if a.datasets: todo = [r for r in todo if r["dataset"] in set(a.datasets.split(","))]
    if a.skip_datasets: todo = [r for r in todo if r["dataset"] not in set(a.skip_datasets.split(","))]
    touched = set()

    def save():
        # Two pulls may share this manifest: merge this run's entries into what is on disk instead of overwriting the other's
        disk = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
        disk.update({k: man[k] for k in touched})
        json.dump(disk, open(f"{man_path}.{os.getpid()}.part", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(f"{man_path}.{os.getpid()}.part", man_path)
    today = time.strftime("%Y-%m-%d")

    def age_days(e):
        try: return (time.time() - time.mktime(time.strptime(str(e.get("pulled", ""))[:10], "%Y-%m-%d"))) / 86400
        except Exception: return 1e9

    if a.stale_days > 0:                      # never pulled / failed first, then the oldest good pull
        todo.sort(key=lambda r: (man.get(f"{r['entity']}/{r['dataset']}", {}).get("status") == "ok",
                                 -age_days(man.get(f"{r['entity']}/{r['dataset']}", {}))))
    api.log(f"{len(todo)} datasets with an API endpoint ({env}); manifest has {len(man)}")
    tok = api.token(c); n_ok = n_skip = n_fail = 0; run_t0 = time.time(); partial = None
    for i, r in enumerate(todo, 1):
        key = f"{r['entity']}/{r['dataset']}"
        prev = man.get(key, {})
        # coverage first (12 Sep): anything already pulled in full is skipped whatever the day; refreshing is a deliberate --force run.
        # Re-pulling the 1M-row customs tables on every resume cost hours before the never-reached datasets were touched.
        # 15 Sep: with --stale-days, a good pull is skipped only while it is younger than that.
        if not a.force and prev.get("status") == "ok" and (a.stale_days <= 0 or age_days(prev) < a.stale_days):
            n_skip += 1; continue
        if a.budget_minutes and time.time() - run_t0 > a.budget_minutes * 60:
            partial = len(todo) - i + 1; break
        base = f"{c['DDA_BASE_URL']}/secure/ddads/openapi/1.0.0/{r['entity']}/{r['dataset']}"
        rows = []; status = "ok"; note = ""; t0 = time.time(); seen = set(); first_h = None
        for page in range(1, a.max_pages + 1):
            if a.dataset_minutes and time.time() - t0 > a.dataset_minutes * 60:
                status = "timeout"; note = f"stopped after {a.dataset_minutes} min at page {page}"; break
            code, raw = api.auth_get(c, f"{base}?page={page}&pageSize={a.page_size}", tok)
            # 18 Sep (PROD): a deep page often times out once (408) and serves in 2-4 s on the next ask; retry the page, not the dataset
            for attempt in range(3):
                if code not in (408, 502, 503, 504): break
                time.sleep(10 * (attempt + 1)); code, raw = api.auth_get(c, f"{base}?page={page}&pageSize={a.page_size}", tok)
            if code != 200 or raw[:1] not in (b"{", b"["):
                status = "blocked" if b"Request Rejected" in raw else f"http_{code}"; note = raw[:160].decode(errors="replace"); break
            try: j = json.loads(raw)
            except Exception: status = "bad_json"; note = raw[:120].decode(errors="replace"); break
            got = j.get("results") if isinstance(j, dict) else j
            got = got or []
            if not isinstance(got, list): status = "odd_shape"; note = str(j)[:160]; break
            # The governed API never returns a short last page: past the end it wraps round to record 1 and keeps serving
            # (dld_brokers: 8,425 records, page 9 = the last 425 + the first 575 again). Stopping on a short page pulled
            # 2,252,220 duplicate rows across 28 datasets and 42 laps of customs airway bills (13 Sep). Stop at the first
            # record already seen and keep only the unseen ones.
            # A wrap restarts at record 1, so the end is the first record of page 1 coming round again. Identical rows
            # elsewhere are dropped (they carry no information) but do not end the pull.
            new = []; wrapped = False
            for rec in got:
                h = hashlib.sha1(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                if page == 1 and not seen: first_h = h
                elif page > 1 and h == first_h: wrapped = True; break
                if h in seen: continue
                seen.add(h); new.append(rec)
            rows += new
            if wrapped or len(got) < a.page_size: break
        cols = sorted({k for row in rows[:200] for k in (row or {}).keys()}) if rows else []
        fn = f"{r['entity']}__{r['dataset']}.json"
        if status == "ok":
            json.dump({"id": r["id"], "title": r["title"], "organization": r["organization"], "entity": r["entity"], "dataset": r["dataset"], "env": env,
                       "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": len(rows), "columns": cols, "results": rows},
                      open(os.path.join(out_dir, fn), "w", encoding="utf-8"), ensure_ascii=False)
            n_ok += 1
        else:
            n_fail += 1
        entry = {"id": r["id"], "title": r["title"], "entity": r["entity"], "dataset": r["dataset"], "status": status, "rows": len(rows), "columns": len(cols),
                 "file": fn if status == "ok" else "", "seconds": round(time.time() - t0, 1), "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note}
        if status != "ok" and prev.get("status") == "ok":
            # 15 Sep: a failed REFRESH (503, block, timeout) keeps the last good pull and its file; the attempt is recorded beside it
            man[key] = dict(prev, last_refresh_attempt={k: entry[k] for k in ("status", "pulled", "seconds", "note")})
        else:
            man[key] = entry
        touched.add(key)
        api.log(f"[{i}/{len(todo)}] {key}: {status} rows={len(rows)} cols={len(cols)}")
        if i % 10 == 0: save()
    save()
    api.log(f"done: ok {n_ok}, skipped {n_skip}, failed {n_fail} -> {man_path}")
    if partial:
        print(f"PARTIAL budget of {a.budget_minutes} min reached: {partial} dataset(s) left for the next run (stalest first)")
        sys.exit(3)


if __name__ == "__main__":
    main()
