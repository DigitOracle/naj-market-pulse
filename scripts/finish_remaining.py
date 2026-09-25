"""finish_remaining.py -- finish every unfinished PROD dataset, waiting out gateway outages instead of burning through queues.

Why (25 Sep 2026). At 04:06 the gateway went down ("Downtime exception: Read timed out" on page 1 of anything). Four finish_all
lanes and two re-pull lanes each spent their retries in minutes and moved down their queues, marking datasets failed that
only needed the outage to end. This replaces them with one queue and four workers, and a health probe before EVERY attempt:
while the gateway is down, workers wait (10-minute probes, up to 24 h) instead of failing.

The work list is built from the state on disk at launch, so it is correct whatever ran before:
  resume     a dataset with a live checkpoint (<file>.part.state, not a *_backup)        -> resume it
  repull     status ok but raw_rows > rows and not repeats_kept (rows were dropped)     -> --force --order-by full
  pull       anything else not ok (consignments and licence partners restart fresh here)
  refused    404 / 400 last time                                                         -> tried once more, last
Smallest first, so landings keep arriving. One writer per dataset is enforced by dda_pull_all's PID lock.

    python scripts/finish_remaining.py [--dry] [--workers 4]
"""
import glob, json, os, queue, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROD = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod")
MAN = os.path.join(PROD, "MANIFEST.json")
# portal-complete, no page total, served unordered forever: last, and only after everything else
LAST = {"rta_bus_ridership-open-api", "rta_metro_ridership-open-api"}
TRANSIENT = {"timeout", "http_0", "http_408", "http_502", "http_503", "http_504", "disk_low", "unstable", "truncated",
             "bad_json", "odd_shape", "max_pages"}
REFUSED = {"http_404", "http_400", "blocked"}
lock = threading.Lock()
LOG = None


def log(msg):
    line = "%s %s" % (time.strftime("%m-%d %H:%M"), msg)
    with lock:
        print(line, flush=True)
        if LOG: LOG.write(line + "\n"); LOG.flush()


def manifest():
    return json.load(open(MAN, encoding="utf-8"))


def healthy():
    import dda_api as api
    c = api.cfg(); c["DDA_BASE_URL"] = c["DDA_BASE_URL_PROD"]; c["DDA_ENV"] = "PROD"
    for k in ("APP_ID", "SECURITY_APP_IDENTIFIER", "CLIENT_ID", "CLIENT_SECRET"):
        c["DDA_" + k] = c["DDA_PROD_" + k]
    try:
        code, raw, tok = api.auth_get(c, api.data_url(c, "dld", "dld_projects-open-api", page=1, pageSize=3), None)
        return code == 200
    except Exception:
        return False


_health = {"ok_until": 0.0}


def wait_healthy(who):
    """Probe at most once a minute across all workers; while down, every worker waits here."""
    waited = 0
    while True:
        with lock:
            fresh = time.time() < _health["ok_until"]
        if fresh:
            return True
        if healthy():
            with lock: _health["ok_until"] = time.time() + 60
            if waited: log("[%s] gateway back after %d min" % (who, waited // 60))
            return True
        if waited == 0: log("[%s] gateway down - waiting (probe every 10 min)" % who)
        if waited >= 24 * 3600:
            log("[%s] gateway down for 24 h - giving up" % who); return False
        time.sleep(600); waited += 600


def build():
    m = manifest()
    parts = {}
    for p in glob.glob(os.path.join(PROD, "*.json.part.state")):
        b = os.path.basename(p)
        if "_backup" in b: continue
        ent, rest = b.split("__", 1)
        ds = rest[: -len(".json.part.state")]
        try: st = json.load(open(p, encoding="utf-8"))
        except Exception: st = {}
        parts[ds] = st
    work = []
    for k, v in m.items():
        ds = k.split("/")[1]; st = v.get("status"); raw, rows = v.get("raw_rows") or 0, v.get("rows") or 0
        if ds in parts:
            est = max(1, (parts[ds].get("last_page_est") or 0) - parts[ds].get("page", 0)) if parts[ds].get("last_page_est") else 3000
            work.append(("resume", ds, est, []))
        elif st == "ok" and raw > rows and not v.get("repeats_kept"):
            work.append(("repull", ds, raw // 1000 + 1, ["--force", "--order-by", "full"]))
        elif st != "ok" and st in REFUSED:
            work.append(("refused", ds, 1, []))
        elif st != "ok":
            work.append(("pull", ds, max(1, raw // 1000) if raw else 500, []))
    rank = {"resume": 0, "repull": 0, "pull": 0, "refused": 1}
    work.sort(key=lambda w: (w[1] in LAST, rank[w[0]], w[2]))
    return work


def status_of(ds):
    v = next((v for k, v in manifest().items() if k.split("/")[1] == ds), {})
    att = v.get("last_refresh_attempt") or {}
    if att and att.get("pulled", "") > v.get("pulled", ""):          # a failed refresh keeps the old ok entry; the attempt is what ran
        return att.get("status"), v
    return v.get("status"), v


def worker(name, q, dry):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", DDA_RATE_S="4.0", DDA_RATE_MAX="40")
    while True:
        try: kind, ds, est, extra = q.get_nowait()
        except queue.Empty: return
        tries = 2 if kind == "refused" else 6
        for n in range(1, tries + 1):
            if not wait_healthy(name): return
            args = [sys.executable, "-u", os.path.join(HERE, "dda_pull_all.py"), "--prod", "--datasets", ds,
                    "--dataset-minutes", "900", "--max-pages", "60000"] + (extra if n == 1 or kind != "repull" else [])
            # a re-pull's --force applies to its FIRST attempt only: later attempts resume the checkpoint it started
            if kind == "repull" and n > 1: args += ["--order-by", "full"]
            log("[%s] %s %s (~%d pages) attempt %d" % (name, kind, ds, est, n))
            if dry: break
            with open(os.path.join(PROD, "finish_remaining_%s.log" % name), "a", encoding="utf-8") as lf:
                subprocess.run(args, cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT)
            st, v = status_of(ds)
            kept = "kept" if v.get("repeats_kept") else "NOT kept"
            log("[%s] %s -> %s %s of %s %s" % (name, ds, st, v.get("rows"), v.get("raw_rows"), kept))
            if st == "ok": break
            if st in REFUSED and n >= 2: break
            time.sleep(60)
    return


def main():
    global LOG
    dry = "--dry" in sys.argv
    nw = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
    work = build()
    LOG = open(os.path.join(ROOT, "logs", "finish_remaining_%s.log" % time.strftime("%Y%m%d_%H%M")), "a", encoding="utf-8")
    log("%d datasets: %s" % (len(work), ", ".join("%s %d" % (k, sum(1 for w in work if w[0] == k)) for k in ("resume", "repull", "pull", "refused"))))
    q = queue.Queue()
    for w in work: q.put(w)
    ts = [threading.Thread(target=worker, args=("w%d" % i, q, dry)) for i in range(1, nw + 1)]
    for t in ts: t.start(); time.sleep(5)
    for t in ts: t.join()
    log("FINISH REMAINING EXIT")


if __name__ == "__main__":
    main()
