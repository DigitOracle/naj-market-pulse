"""dda_api.py -- data.dubai (Digital Dubai Authority) API client for the Najma pipeline.

The portal's scriptable download endpoint (reference_datadubai_registers_api) gives whole files; this is the *governed* route:
OAuth 2.0 client credentials -> bearer token (1 h) -> health check -> paged dataset reads. Credentials live OUTSIDE the repo in
C:\\Users\\kwils\\digitalchemy-dda.env (never committed, never printed).

    python scripts/dda_api.py health
    python scripts/dda_api.py get <entity> <dataset> [--page 1] [--page-size 1000] [--filter col=value] [--columns a,b]
    python scripts/dda_api.py pull <entity> <dataset> [--max-pages 50]      # all pages -> data/raw_downloads/dda/<entity>__<dataset>.json
    python scripts/dda_api.py url <path-or-full-url>                         # raw GET on an open/secure path with the bearer token

Facts from the issuing pack (data/raw_downloads/dda_ipaas/): token 3600 s; 60 requests/minute; 30 s timeout; 1,000 records per
page; UAE-only source addresses; test credentials do not expire. Production needs a separate request quoting the Application Id.
"""
import argparse, json, os, socket, sys, time, urllib.error, urllib.parse, urllib.request
socket.setdefaulttimeout(40)            # a stalled TLS handshake hung the 10 Sep bulk pull for 30 min; urllib's timeout alone did not cover it
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ENV = os.environ.get("DDA_ENV_FILE", r"C:\Users\kwils\digitalchemy-dda.env")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda")
CACHE = os.path.join(OUT, ".token.json")
RATE_S = float(os.environ.get("DDA_RATE_S", "1.05"))   # 60 requests per minute for one process; parallel pulls share that budget, so each sets DDA_RATE_S higher
_last = [0.0]
RATE_FILE = os.path.join(OUT, ".rate.json")
RATE_MAX = int(os.environ.get("DDA_RATE_MAX", "40"))    # requests per rolling 60 s across EVERY process using this module


def cfg():
    if not os.path.exists(ENV):
        sys.exit(f"credentials file not found: {ENV}")
    d = {}
    for line in open(ENV, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); d[k.strip()] = v.strip()
    return d


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def _throttle():
    wait = RATE_S - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()


def _shared_wait():
    """Block until this process may send one request without taking the total over RATE_MAX in any rolling 60 s, counted across all
    processes on this machine (a timestamp list in .rate.json under a create-exclusive lock file). 19 Sep 2026 00:59: three streams,
    each throttling only itself, together broke the gateway's per-minute quota (HTTP 429 'exceeded per minute Quota') and the giant
    queues abandoned every dataset in seconds. The documented limit is 60/min; the default cap leaves a third of it as headroom."""
    os.makedirs(OUT, exist_ok=True)
    lock = RATE_FILE + ".lock"
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 10: os.remove(lock)      # left by a killed process
            except OSError: pass
            time.sleep(0.05); continue
        wait = 0.0
        try:
            now = time.time()
            try: ts = [t for t in json.load(open(RATE_FILE)) if now - t < 60]
            except Exception: ts = []
            if len(ts) < RATE_MAX:
                ts.append(now)
                tmp = RATE_FILE + f".{os.getpid()}.tmp"
                with open(tmp, "w") as f: json.dump(ts, f)
                os.replace(tmp, RATE_FILE)
                return
            wait = ts[0] + 60 - now
        finally:
            os.close(fd)
            try: os.remove(lock)
            except OSError: pass
        time.sleep(max(wait, 0.05) + 0.05)


def _req(url, data=None, headers=None, timeout=35):
    _throttle()
    _shared_wait()
    r = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as h:
            return h.status, h.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                            # timeouts, resets: report instead of raising mid-pull
        return 0, f"transport error: {e}".encode()


def token(c, force=False):
    if not force and os.path.exists(CACHE):
        t = json.load(open(CACHE))
        if t.get("expires_at", 0) - 60 > time.time() and t.get("base") == c["DDA_BASE_URL"]:
            return t["access_token"]
    body = json.dumps({"grant_type": "client_credentials", "client_id": c["DDA_CLIENT_ID"], "client_secret": c["DDA_CLIENT_SECRET"]}).encode()
    for attempt in range(6):                          # the hotspot link drops for a minute at a time: wait it out rather than exit
        code, raw = _req(c["DDA_BASE_URL"] + "/secure/ssis/dubaiai/gatewaytoken/1.0.0/getAccessToken", body,
                         {"Content-Type": "application/json", "x-DDA-SecurityApplicationIdentifier": c["DDA_SECURITY_APP_IDENTIFIER"]})
        if code == 200: break
        log(f"token attempt {attempt+1} HTTP {code}: {raw[:120].decode(errors='replace')}"); time.sleep(20 * (attempt + 1))
    if code != 200:
        sys.exit(f"token failed HTTP {code}: {raw[:300].decode(errors='replace')}")
    j = json.loads(raw)
    os.makedirs(OUT, exist_ok=True)
    tmp = CACHE + f".{os.getpid()}.part"               # atomic write: two processes must never see a half-written cache
    json.dump({"access_token": j["access_token"], "expires_at": time.time() + int(j.get("expires_in", 3600)), "base": c["DDA_BASE_URL"]}, open(tmp, "w"))
    os.replace(tmp, CACHE)
    log(f"token ok, valid {j.get('expires_in')} s, scope {j.get('scope')}")
    return j["access_token"]


def auth_get(c, url, tok=None):
    """Returns (code, raw, tok): the caller MUST keep using the returned tok for its next call. A caller that discards it and
    keeps passing its original tok will 401 on every single request once that token turns over (18 Sep 2026: dda_pull_all.py
    did exactly this - the per-dataset page loop held one `tok` captured before the loop and never picked up a refreshed one,
    so once the token expired every remaining page cost two round trips - one 401, one forced refresh - forever)."""
    tok = tok or token(c)
    code, raw = _req(url, None, {"Authorization": "Bearer " + tok})
    for attempt in range(4):                          # transport drops: retry the same page with backoff
        if code != 0: break
        time.sleep(15 * (attempt + 1)); code, raw = _req(url, None, {"Authorization": "Bearer " + tok})
    if code == 401:                                   # expired mid-run, or another process already rotated it - re-read the
        cached = None                                 # cache first (cheap) before paying for a brand-new server token
        if os.path.exists(CACHE):
            try:
                t = json.load(open(CACHE))
                if t.get("expires_at", 0) - 60 > time.time() and t.get("base") == c["DDA_BASE_URL"] and t.get("access_token") != tok:
                    cached = t["access_token"]
            except Exception:
                pass
        tok = cached or token(c, force=True)
        code, raw = _req(url, None, {"Authorization": "Bearer " + tok})
    return code, raw, tok


def data_url(c, entity, dataset, **q):
    q = {k: v for k, v in q.items() if v not in (None, "")}
    base = f"{c['DDA_BASE_URL']}/secure/ddads/openapi/1.0.0/{entity}/{dataset}"
    return base + ("?" + urllib.parse.urlencode(q) if q else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["health", "get", "pull", "url", "token"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--page", type=int, default=1); ap.add_argument("--page-size", type=int, default=1000)
    ap.add_argument("--filter", default=""); ap.add_argument("--columns", default="")
    ap.add_argument("--order-by", default=""); ap.add_argument("--order-dir", default="")
    ap.add_argument("--max-pages", type=int, default=50); ap.add_argument("--prod", action="store_true")
    a = ap.parse_args()
    c = cfg()
    if a.prod:                                        # PROD has its own credential set (issued 18 Sep 2026)
        c["DDA_BASE_URL"] = c["DDA_BASE_URL_PROD"]; c["DDA_ENV"] = "PROD"
        for k in ("APP_ID", "SECURITY_APP_IDENTIFIER", "CLIENT_ID", "CLIENT_SECRET"):
            c["DDA_" + k] = c["DDA_PROD_" + k]
    if a.cmd == "token":
        token(c, force=True); return
    if a.cmd == "health":
        code, raw, _ = auth_get(c, c["DDA_BASE_URL"] + "/secure/ddads/healthcheck/1.0.0/health")
        log(f"health HTTP {code}: {raw[:400].decode(errors='replace')}"); return
    if a.cmd == "url":
        u = a.args[0]; u = u if u.startswith("http") else c["DDA_BASE_URL"] + u
        code, raw, _ = auth_get(c, u); log(f"HTTP {code} {len(raw)} bytes"); print(raw[:2000].decode(errors="replace")); return
    entity, dataset = a.args[0], a.args[1]
    if a.cmd == "get":
        u = data_url(c, entity, dataset, page=a.page, pageSize=a.page_size, filter=a.filter, column=a.columns, order_by=a.order_by, order_dir=a.order_dir)
        code, raw, _ = auth_get(c, u); log(f"HTTP {code} {len(raw)} bytes"); print(raw[:3000].decode(errors="replace")); return
    # pull: every page into one file
    os.makedirs(OUT, exist_ok=True); rows = []; tok = token(c)
    for page in range(1, a.max_pages + 1):
        u = data_url(c, entity, dataset, page=page, pageSize=a.page_size, filter=a.filter, column=a.columns)
        code, raw, tok = auth_get(c, u, tok)          # pick up any refreshed token for the next page
        if code != 200:
            log(f"page {page} HTTP {code}: {raw[:200].decode(errors='replace')}"); break
        j = json.loads(raw); got = j.get("results") or j.get("data") or []
        rows += got; log(f"page {page}: {len(got)} rows (total {len(rows)})")
        if len(got) < a.page_size: break
    path = os.path.join(OUT, f"{entity}__{dataset}.json")
    json.dump({"entity": entity, "dataset": dataset, "env": c["DDA_ENV"], "pulled": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": len(rows), "results": rows},
              open(path, "w", encoding="utf-8"), ensure_ascii=False)
    log(f"wrote {path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
