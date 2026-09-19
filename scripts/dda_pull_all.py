"""dda_pull_all.py -- pull every dataset the data.dubai API profile can reach.

Reads data/raw_downloads/dda/api_catalogue.json (scripts/dda_api_catalogue.py), calls each endpoint through the governed API
(scripts/dda_api.py: bearer token, shared 60 requests/minute budget, 1,000 rows per page) and writes one JSON per dataset plus a manifest.
Resumable: a dataset already pulled is skipped unless --force; a dataset that did not finish resumes from its .part checkpoint.

    python scripts/dda_pull_all.py [--prod] [--force] [--only dld,dm,rta] [--datasets a,b] [--skip-datasets a,b] [--max-pages 2000]

How a dataset is pulled (19 Sep 2026, after two silent-truncation bugs):
  1. Page 1 comes back in a stable order. A page shorter than the page size is the whole dataset.
  2. Otherwise the TRUE last page is found (the API serves an empty page once a page lies wholly past the end: double the page
     number until one is empty, then bisect).
  3. Deep pages of many datasets are NOT reproducible when no sort is given: the same request returns different rows each time
     (page 108 of ded_license_master fetched three times gave three disjoint sets; dld_transactions, dm_project_applications and
     dsc_buildings behave the same), so a sequential pull silently skips and repeats records. Two pages are fetched twice; if they
     differ, a column that is unique on page 1 is tried as order_by (order_dir=asc) until one makes the pages reproducible.
  4. Every page is then fetched with that order_by, rows are de-duplicated by content hash (exact repeats carry no information),
     and each page is checkpointed to <file>.part / .part.state.
  5. Before a dataset is called ok, two sample pages are fetched again and must match what was stored. A dataset whose pages
     cannot be made reproducible is 'unstable', never ok.
The end is an empty or short page (or, on an environment that laps forever such as STG, five pages with nothing new); it is never
"a record I have seen before", which a real register with repeated rows trips over.
"""
import argparse, hashlib, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dda_api as api

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CAT = os.path.join(ROOT, "data", "raw_downloads", "dda", "api_catalogue.json")
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

STALL_PAGES = 5          # only for an environment whose pages never run out: this many consecutive pages with nothing new ends it
MAX_PROBE_PAGE = 9000    # deepest page the end-finder will look at
ORDER_V = 3              # checkpoint format: older checkpoints hold pages fetched without a reproducible order and are discarded
TRANSIENT = (0, 408, 429, 502, 503, 504)


def rec_hash(rec):
    return hashlib.sha1(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def fetch_page(c, base, page, page_size, order, tok, label=""):
    """One page, with the retry policy that keeps a multi-hour pull alive. Returns (code, raw, tok).
    A deep page often times out once (408) and serves in a few seconds on the next ask. code 0 is a transport error (link down): 18 Sep
    19:42 one drop threw away an hour of pages, so a dead link gets up to 8 rounds of 20-120 s waits. 429 is the gateway's per-minute quota
    and must never end a dataset (19 Sep 00:59 it ended eleven in seconds): wait out the minute and ask again."""
    url = f"{base}?page={page}&pageSize={page_size}" + (f"&order_by={order}&order_dir=asc" if order else "")
    code, raw, tok = api.auth_get(c, url, tok)
    n = 0
    while code in TRANSIENT and n < {0: 8, 429: 12}.get(code, 3):
        n += 1
        if code in (0, 429): api.log(f"{label} page {page}: {'link down' if code == 0 else 'rate limited (429)'}, waiting (round {n})")
        time.sleep(65 if code == 429 else (20 if code == 0 else 10) * min(n, 6))
        code, raw, tok = api.auth_get(c, url, tok)
    return code, raw, tok


def parse_page(code, raw):
    """(records, status, note): records is a list when the page is usable, else None with the failure status."""
    if code != 200 or raw[:1] not in (b"{", b"["):
        return None, ("blocked" if b"Request Rejected" in raw else f"http_{code}"), raw[:160].decode(errors="replace")
    try: j = json.loads(raw)
    except Exception: return None, "bad_json", raw[:120].decode(errors="replace")
    got = j.get("results") if isinstance(j, dict) else j
    got = got or []
    if not isinstance(got, list): return None, "odd_shape", str(j)[:160]
    return got, None, ""


def find_last_page(c, base, page_size, tok, label):
    """(last non-empty page, tok, status, note). Emptiness past the end is deterministic even where row order is not."""
    lo, hi, p = 1, None, 2
    while hi is None:
        code, raw, tok = fetch_page(c, base, p, page_size, None, tok, label)
        got, st, nt = parse_page(code, raw)
        if got is None: return None, tok, st, nt
        if got: lo = p
        else: hi = p
        if hi is None:
            if p >= MAX_PROBE_PAGE: return None, tok, "too_deep", f"still serving at page {p}"
            p = min(p * 2, MAX_PROBE_PAGE)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        code, raw, tok = fetch_page(c, base, mid, page_size, None, tok, label)
        got, st, nt = parse_page(code, raw)
        if got is None: return None, tok, st, nt
        if got: lo = mid
        else: hi = mid
    return lo, tok, None, ""


def stable_at(c, base, page_size, order, pages, tok, label):
    """(True/False, tok, (status, note)): does every page in `pages` return the same records in the same order on two requests?"""
    for p in pages:
        out = []
        for _ in range(2):
            code, raw, tok = fetch_page(c, base, p, page_size, order, tok, label)
            got, st, nt = parse_page(code, raw)
            if got is None: return None, tok, (st, nt)
            out.append([rec_hash(r) for r in got])
        if out[0] != out[1]: return False, tok, None
    return True, tok, None


def key_candidates(page1):
    """Columns that are filled and unique across page 1, best guesses for a record key first (id, *_id, then *number/no/serial/key/code)."""
    cols = list(page1[0].keys())
    uniq = [k for k in cols if all(r.get(k) is not None for r in page1)
            and len({json.dumps(r.get(k), sort_keys=True, ensure_ascii=False) for r in page1}) == len(page1)]
    def rank(k):
        kl = k.lower()
        return (0 if kl == "id" else 1 if kl.endswith("_id") else 2 if re.search(r"(id|number|no|serial|key|code)$", kl) else 3, cols.index(k))
    return sorted(uniq, key=rank)


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
        # Several pulls may share this manifest: merge this run's entries into what is on disk instead of overwriting the others'
        disk = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
        disk.update({k: man[k] for k in touched})
        json.dump(disk, open(f"{man_path}.{os.getpid()}.part", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(f"{man_path}.{os.getpid()}.part", man_path)

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
        # 15 Sep: with --stale-days, a good pull is skipped only while it is younger than that.
        if not a.force and prev.get("status") == "ok" and (a.stale_days <= 0 or age_days(prev) < a.stale_days):
            n_skip += 1; continue
        if a.budget_minutes and time.time() - run_t0 > a.budget_minutes * 60:
            partial = len(todo) - i + 1; break
        base = f"{c['DDA_BASE_URL']}/secure/ddads/openapi/1.0.0/{r['entity']}/{r['dataset']}"
        label = r["dataset"]
        fn = f"{r['entity']}__{r['dataset']}.json"
        part = os.path.join(out_dir, fn + ".part"); pstate = part + ".state"; psamp = part + ".samples"
        rows = []; status = "ok"; note = ""; t0 = time.time(); seen = set()
        order = None; last_est = None; raw_rows = 0; dry = 0; ended_by = ""; last_page = 0; start_page = 1
        sample_pages = []; samples = {}; got1 = None; selfcheck = ""
        resumed = False
        if not a.force and os.path.exists(part) and os.path.exists(pstate):
            try:
                st = json.load(open(pstate, encoding="utf-8"))
                if st.get("order_v") != ORDER_V:               # pages fetched without a reproducible order cannot be trusted or completed
                    raise ValueError("checkpoint from an older pull")
                if st.get("page_size") != a.page_size:         # page N means different records at a different page size
                    raise ValueError(f"page size changed ({st.get('page_size')} -> {a.page_size})")
                with open(part, encoding="utf-8") as pf:
                    for line in pf:
                        try: rows.append(json.loads(line))
                        except Exception: break                # a torn last line from a power cut: keep what parsed
                order = st.get("order_by"); last_est = st.get("last_page_est"); raw_rows = int(st.get("raw_rows", 0))
                start_page = int(st["page"]) + 1; last_page = int(st["page"]); sample_pages = st.get("sample_pages") or []
                samples = json.load(open(psamp, encoding="utf-8")) if os.path.exists(psamp) else {}
                for rec in rows: seen.add(rec_hash(rec))
                resumed = True
                api.log(f"{key}: resuming at page {start_page} with {len(rows):,} rows checkpointed (order_by={order})")
            except Exception as e:
                rows = []; seen = set(); order = None; last_est = None; raw_rows = 0; start_page = 1; last_page = 0; sample_pages = []; samples = {}
                api.log(f"{key}: checkpoint discarded ({str(e)[:70]}), starting over")
        if not resumed:
            for p_ in (part, pstate, psamp):                   # fresh start (or --force): no stale checkpoint may survive
                if os.path.exists(p_): os.remove(p_)
            code, raw, tok = fetch_page(c, base, 1, a.page_size, None, tok, label)
            got1, st_, nt_ = parse_page(code, raw)
            if got1 is None:
                status, note = st_, nt_
            elif len(got1) >= a.page_size:                     # more than one page: where does it end, and are its pages reproducible?
                last_est, tok, st_, nt_ = find_last_page(c, base, a.page_size, tok, label)
                if last_est is None and st_ == "too_deep":
                    api.log(f"{key}: pages never run out (a lapping environment); ending on {STALL_PAGES} pages with nothing new")
                elif last_est is None:
                    status, note = st_, nt_
                elif last_est >= 3:
                    sample_pages = sorted({max(2, last_est // 2), max(2, last_est - 1)})
                    ok_, tok, err = stable_at(c, base, a.page_size, None, sample_pages, tok, label)
                    if ok_ is None: status, note = err
                    elif not ok_:
                        order = None
                        # 19 Sep: no single column is a key for some registers (DM floor levels: building x floor x usage); the gateway
                        # takes a comma list, and ordering by EVERY column leaves ties only between identical rows, which are
                        # interchangeable - so the full-row order is the last candidate (4,212 pages reproducible, 4,211,807 rows).
                        full_row = ",".join(got1[0].keys())
                        for cand in key_candidates(got1)[:6] + [full_row]:
                            ok2, tok, err = stable_at(c, base, a.page_size, cand, sample_pages, tok, label)
                            if ok2 is None: status, note = err; break
                            if ok2: order = cand; break
                        if status == "ok" and order is None:
                            status = "unstable"; note = "deep pages are not reproducible and no column tried as order_by makes them so"
                        elif status == "ok":
                            api.log(f"{key}: unordered deep pages are not reproducible; sorting by {order}")
                if status == "ok" and last_est is None and st_ == "too_deep": sample_pages = []
        if status == "ok":
            for page in range(start_page, a.max_pages + 1):
                if a.dataset_minutes and time.time() - t0 > a.dataset_minutes * 60:
                    status = "timeout"; note = f"stopped after {a.dataset_minutes} min at page {page}"; break
                if page == 1 and order is None and got1 is not None:
                    got = got1                                     # already fetched unordered, and page 1 is stable
                else:
                    code, raw, tok = fetch_page(c, base, page, a.page_size, order, tok, f"{label}({len(rows):,} rows held)")
                    got, st_, nt_ = parse_page(code, raw)
                    if got is None: status, note = st_, nt_; break
                hs = [rec_hash(x) for x in got]
                raw_rows += len(got)
                new = []
                for rec, h in zip(got, hs):
                    if h in seen: continue                         # identical rows carry no information: dropped, they never end the pull
                    seen.add(h); new.append(rec)
                rows += new; last_page = page
                dry = 0 if new else dry + 1
                if page in sample_pages:
                    samples[str(page)] = hs
                    with open(psamp + ".tmp", "w", encoding="utf-8") as sf: json.dump(samples, sf)
                    os.replace(psamp + ".tmp", psamp)
                if new:                                            # checkpoint: rows first, then the state that says they are complete
                    with open(part, "a", encoding="utf-8") as pf:
                        for rec in new: pf.write(json.dumps(rec, ensure_ascii=False) + chr(10))
                with open(pstate + ".tmp", "w", encoding="utf-8") as sf:
                    json.dump({"order_v": ORDER_V, "page": page, "page_size": a.page_size, "order_by": order, "last_page_est": last_est,
                               "raw_rows": raw_rows, "sample_pages": sample_pages}, sf)
                os.replace(pstate + ".tmp", pstate)
                if len(got) < a.page_size: ended_by = "short_page"; break
                if last_est is not None and page >= last_est: ended_by = "last_page"; break
                if last_est is None and dry >= STALL_PAGES: ended_by = "no_new_rows"; break
            if status == "ok" and not ended_by:                    # the loop ran out of pages without reaching the end of the dataset
                status = "max_pages"; note = f"stopped at the --max-pages ceiling ({a.max_pages}) with {len(rows):,} rows; the checkpoint keeps them"
        if status == "ok" and samples:                             # self-check: the pages fetched must come back the same
            bad = []
            for p_, want in sorted(samples.items(), key=lambda kv: int(kv[0])):
                code, raw, tok = fetch_page(c, base, int(p_), a.page_size, order, tok, label)
                got, st_, nt_ = parse_page(code, raw)
                if got is None: bad.append(f"page {p_}: {st_}"); continue
                if [rec_hash(x) for x in got] != want: bad.append(f"page {p_} changed")
            selfcheck = "mismatch" if bad else "ok"
            if bad: status = "unstable"; note = "self-check failed: " + "; ".join(bad)
        cols = sorted({k for row in rows[:200] for k in (row or {}).keys()}) if rows else []
        if status == "ok":
            with open(os.path.join(out_dir, fn + ".tmp"), "w", encoding="utf-8") as of:
                json.dump({"id": r["id"], "title": r["title"], "organization": r["organization"], "entity": r["entity"], "dataset": r["dataset"], "env": env,
                           "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": len(rows), "columns": cols, "order_by": order, "results": rows}, of, ensure_ascii=False)
            os.replace(os.path.join(out_dir, fn + ".tmp"), os.path.join(out_dir, fn))   # never a half-written final file
            for p_ in (part, pstate, psamp):
                if os.path.exists(p_): os.remove(p_)
            n_ok += 1
        else:
            n_fail += 1
        entry = {"id": r["id"], "title": r["title"], "entity": r["entity"], "dataset": r["dataset"], "status": status, "rows": len(rows), "columns": len(cols),
                 "file": fn if status == "ok" else "", "seconds": round(time.time() - t0, 1), "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note,
                 "pages": last_page, "last_page": last_est, "raw_rows": raw_rows, "order_by": order, "selfcheck": selfcheck,
                 "ended_by": ended_by if status == "ok" else status}
        if status != "ok" and prev.get("status") == "ok":
            # 15 Sep: a failed REFRESH (503, block, timeout) keeps the last good pull and its file; the attempt is recorded beside it
            man[key] = dict(prev, last_refresh_attempt={k: entry[k] for k in ("status", "pulled", "seconds", "note")})
        else:
            man[key] = entry
        touched.add(key)
        api.log(f"[{i}/{len(todo)}] {key}: {status} rows={len(rows)} cols={len(cols)}" + (f" order_by={order}" if order else "") + (f" ({note[:80]})" if note and status != "ok" else ""))
        save()                                                     # every dataset: the loader reads the manifest, and a giant can take hours
    save()
    api.log(f"done: ok {n_ok}, skipped {n_skip}, failed {n_fail} -> {man_path}")
    if partial:
        print(f"PARTIAL budget of {a.budget_minutes} min reached: {partial} dataset(s) left for the next run (stalest first)")
        sys.exit(3)


if __name__ == "__main__":
    main()
