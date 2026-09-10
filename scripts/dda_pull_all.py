"""dda_pull_all.py -- pull every dataset the data.dubai API profile can reach.

Reads data/raw_downloads/dda/api_catalogue.json (scripts/dda_api_catalogue.py), calls each endpoint through the governed API
(scripts/dda_api.py: bearer token, 60 requests/minute, 1,000 rows per page) and writes one JSON per dataset plus a manifest.
Resumable: a dataset already pulled today is skipped unless --force. The staging environment serves samples (5 masked rows per
table, seen 10 Sep 2026), so on STG this captures schema + sample for every endpoint = the validation evidence the production
request needs; run again with --prod once production credentials are in the env file.

    python scripts/dda_pull_all.py [--prod] [--force] [--only dld,dm,rta] [--max-pages 2000]
"""
import argparse, json, os, sys, time
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
    a = ap.parse_args()
    c = api.cfg()
    if a.prod: c["DDA_BASE_URL"] = c["DDA_BASE_URL_PROD"]
    env = "prod" if a.prod else c["DDA_ENV"].lower()
    out_dir = os.path.join(ROOT, "data", "raw_downloads", "dda", env); os.makedirs(out_dir, exist_ok=True)
    man_path = os.path.join(out_dir, "MANIFEST.json")
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    cat = json.load(open(CAT, encoding="utf-8"))["rows"]
    todo = [r for r in cat if r["endpoints"]]
    if a.only: todo = [r for r in todo if r["entity"] in set(a.only.split(","))]
    today = time.strftime("%Y-%m-%d")
    api.log(f"{len(todo)} datasets with an API endpoint ({env}); manifest has {len(man)}")
    tok = api.token(c); n_ok = n_skip = n_fail = 0
    for i, r in enumerate(todo, 1):
        key = f"{r['entity']}/{r['dataset']}"
        if not a.force and man.get(key, {}).get("pulled", "")[:10] == today and man[key].get("status") == "ok":
            n_skip += 1; continue
        base = f"{c['DDA_BASE_URL']}/secure/ddads/openapi/1.0.0/{r['entity']}/{r['dataset']}"
        rows = []; status = "ok"; note = ""; t0 = time.time()
        for page in range(1, a.max_pages + 1):
            code, raw = api.auth_get(c, f"{base}?page={page}&pageSize={a.page_size}", tok)
            if code != 200 or raw[:1] not in (b"{", b"["):
                status = "blocked" if b"Request Rejected" in raw else f"http_{code}"; note = raw[:160].decode(errors="replace"); break
            try: j = json.loads(raw)
            except Exception: status = "bad_json"; note = raw[:120].decode(errors="replace"); break
            got = j.get("results") if isinstance(j, dict) else j
            got = got or []
            if not isinstance(got, list): status = "odd_shape"; note = str(j)[:160]; break
            rows += got
            if len(got) < a.page_size: break
        cols = sorted({k for row in rows[:200] for k in (row or {}).keys()}) if rows else []
        fn = f"{r['entity']}__{r['dataset']}.json"
        if status == "ok":
            json.dump({"id": r["id"], "title": r["title"], "organization": r["organization"], "entity": r["entity"], "dataset": r["dataset"], "env": env,
                       "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": len(rows), "columns": cols, "results": rows},
                      open(os.path.join(out_dir, fn), "w", encoding="utf-8"), ensure_ascii=False)
            n_ok += 1
        else:
            n_fail += 1
        man[key] = {"id": r["id"], "title": r["title"], "entity": r["entity"], "dataset": r["dataset"], "status": status, "rows": len(rows), "columns": len(cols),
                    "file": fn if status == "ok" else "", "seconds": round(time.time() - t0, 1), "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note}
        api.log(f"[{i}/{len(todo)}] {key}: {status} rows={len(rows)} cols={len(cols)}")
        if i % 10 == 0: json.dump(man, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(man, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    api.log(f"done: ok {n_ok}, skipped {n_skip}, failed {n_fail} -> {man_path}")


if __name__ == "__main__":
    main()
