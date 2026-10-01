"""pf_ondemand_poll.py -- the laptop side of the START menu's "Advertised supply" card (1 Oct 2026).

The Worker cannot crawl, so it leaves a request in KV and this poller, run every minute by Task Scheduler while the laptop is
awake, does the work: take the request, crawl the target with scripts/pf_listings.py (research only, polite, lake written once
at the end), rebuild that district's pf_supply file, publish it to KV as img_pf_supply_<district>, and write the result.

KV protocol (namespace MEETINGS, env azimuth2 - the same store every push script uses):
  pf_req_<uuid>   written by the Worker: {"district": "<our slug>", "building_slug": "<PF SEO tail or null>", "requested_at": iso}
  pf_take_<uuid>  written here when work starts: {"taken_at": iso, "host": name}
  pf_done_<uuid>  written here at the end: {"status": "ok" | "held_by_daily_chain" | "error", "as_of": iso, "district": ...,
                                            "building_slug": ..., "image": "img_pf_supply_<district>", "note": ...}
  img_pf_supply_<district>   the pf_supply JSON, published through POST /ingest_market (imageName "pf_supply_<district>")
One request per run, oldest first; a request with a pf_take_ is never taken twice. Nothing touches the lake while the daily
chain is running (daily_refresh.log has a "=== daily start" without a later "=== daily done"): the request is answered
held_by_daily_chain at once so the card can say so, and the Worker may re-request after the chain.

    python scripts/pf_ondemand_poll.py            one pass (Task Scheduler runs this every minute)
    python scripts/pf_ondemand_poll.py --dry      list pending requests, take nothing, crawl nothing, publish nothing
Task (production - create only on Kendall's go):
    schtasks /Create /TN Najma_PF_OnDemand /SC MINUTE /MO 1 /TR "C:\\...\\python.exe C:\\Dev\\naj-market-pulse\\scripts\\pf_ondemand_poll.py" /F
"""
import base64, json, os, re, socket, subprocess, sys, time, urllib.parse, urllib.request
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WORKER = os.environ.get("AZIMUTH_URL") or "https://azimuth-2.digitalchemy.workers.dev"
WRANGLER = r"C:\Dev\azimuth-worker\wrangler.toml"
CF_TOKEN_FILE = r"C:\Users\kwils\.cf_token"
LISTENER_ENV = r"C:\Dev\azimuth-listener-naj\.env"
API = "https://api.cloudflare.com/client/v4/accounts/%s/storage/kv/namespaces/%s"
DAILY_LOG = os.path.join(ROOT, "daily_refresh.log")
LOG = os.path.join(ROOT, "logs", "pf_ondemand.log")
SUPPLY = os.path.join(ROOT, "data", "listings")
PY = sys.executable


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def cf():
    w = open(WRANGLER, encoding="utf-8").read()
    acct = re.search(r'account_id\s*=\s*"([0-9a-f]+)"', w).group(1)
    ids = re.findall(r'kv_namespaces\s*=\s*\[\s*\{\s*binding\s*=\s*"MEETINGS",\s*id\s*=\s*"([0-9a-f]+)"', w)
    nid = ids[1] if len(ids) > 1 else ids[0]                # top-level block first, then [env.azimuth2]
    token = open(CF_TOKEN_FILE, encoding="utf-8").read().strip()
    return acct, nid, token


def kv_call(url, token, method="GET", body=None, ctype="application/json"):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": "Bearer " + token, "User-Agent": "najma-market-pulse/1.0", "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def kv_list(prefix):
    acct, nid, token = cf()
    keys, cursor = [], ""
    while True:
        url = API % (acct, nid) + "/keys?limit=1000&prefix=" + urllib.parse.quote(prefix) + ("&cursor=" + urllib.parse.quote(cursor) if cursor else "")
        d = json.loads(kv_call(url, token))
        keys += [k["name"] for k in d.get("result") or []]
        cursor = (d.get("result_info") or {}).get("cursor") or ""
        if not cursor:
            return keys


def kv_get(key):
    acct, nid, token = cf()
    try:
        return json.loads(kv_call(API % (acct, nid) + "/values/" + urllib.parse.quote(key), token))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def kv_put(key, value):
    acct, nid, token = cf()
    kv_call(API % (acct, nid) + "/values/" + urllib.parse.quote(key), token, method="PUT", body=json.dumps(value).encode(), ctype="text/plain")


def worker_call(path, body=None):
    """The Worker's keyed on-demand routes (v279): GET /pf_queue, POST /pf_status. Same token as /ingest_market. The
    account KV API is kept only as a fallback: from this laptop every api.cloudflare.com call takes ~127 s (1 Oct 2026)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(WORKER + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"X-Azimuth-Ingest": ingest_token(), "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def queue_pending():
    """[(req_key, request)] oldest first, from the Worker; falls back to the KV API if the route is not there yet (pre-v279)."""
    try:
        d = worker_call("/pf_queue")
        items = sorted(d.get("pending") or [], key=lambda x: x.get("requested_at") or "")
        return [("pf_req_" + x["id"], x) for x in items if x.get("id")], "worker"
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    reqs = sorted(kv_list("pf_req_"))
    taken = set(k[len("pf_take_"):] for k in kv_list("pf_take_"))
    return [(k, kv_get(k) or {}) for k in reqs if k[len("pf_req_"):] not in taken], "kv-api"


def mark(uid, stage, result, via):
    if via == "worker":
        worker_call("/pf_status", {"id": uid, "stage": stage, "result": result})
    elif via == "stub":
        log("STUB %s %s %s" % (stage, uid, json.dumps(result)[:200]))
    else:
        kv_put(("pf_take_" if stage == "take" else "pf_done_") + uid, result)


def ingest_token():
    for line in open(LISTENER_ENV, encoding="utf-8"):
        if line.startswith("INGEST_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("INGEST_TOKEN not found in " + LISTENER_ENV)


def publish_json(name, path):
    body = json.dumps({"imageName": name, "image": base64.b64encode(open(path, "rb").read()).decode(), "contentType": "application/json"}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": ingest_token(), "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def daily_chain_running():
    """True between the latest '=== daily start' and a later '=== daily done' in daily_refresh.log (never the clock)."""
    if not os.path.exists(DAILY_LOG):
        return False
    last_start = last_done = None
    with open(DAILY_LOG, "rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace")
            if "=== daily start" in line:
                last_start = line[:20]
            elif "=== daily done" in line:
                last_done = line[:20]
    return bool(last_start) and (last_done is None or last_done < last_start)


def run(cmd, timeout):
    p = subprocess.run([PY, "-u"] + cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def handle(req_key, req, dry, via="worker"):
    uid = req_key[len("pf_req_"):]
    district = (req.get("district") or "").strip()
    building = (req.get("building_slug") or "").strip() or None
    now = dt.datetime.now().isoformat(timespec="seconds")
    if not re.fullmatch(r"[a-z0-9]+", district or ""):
        result = {"status": "error", "as_of": now, "district": district, "note": "bad district slug"}
    elif daily_chain_running():
        result = {"status": "held_by_daily_chain", "as_of": now, "district": district, "building_slug": building,
                  "note": "the morning refresh holds the lake; ask again after it finishes"}
    else:
        result = None
    if dry:
        log("DRY %s -> would %s" % (req_key, (result or {}).get("status") or ("crawl %s" % (building or "district " + district))))
        return
    mark(uid, "take", {"taken_at": now, "host": socket.gethostname()}, via)
    if result is None:
        t0 = time.time()
        if building:
            if not re.fullmatch(r"[a-z0-9-]+", building):
                result = {"status": "error", "as_of": now, "district": district, "note": "bad building slug"}
            else:
                code, out = run([os.path.join("scripts", "pf_listings.py"), "crawl", "--buildings", building, "--max-requests", "60"], 900)
        else:
            code, out = run([os.path.join("scripts", "pf_listings.py"), "crawl", "--bound-only", "--district", district, "--max-requests", "400"], 3000)
        if result is None:
            if code in (0, 3):                                  # 3 = cap reached, whole buildings written
                code2, out2 = run([os.path.join("scripts", "pf_listings.py"), "report", "--district", district], 600)
                path = os.path.join(SUPPLY, "pf_supply_%s.json" % district)
                if code2 == 0 and os.path.exists(path):
                    pub = {"ok": True, "skipped": "--no-publish"} if "--no-publish" in sys.argv else publish_json("pf_supply_" + district, path)
                    result = {"status": "ok" if pub.get("ok") else "error", "as_of": dt.datetime.now().isoformat(timespec="seconds"),
                              "district": district, "building_slug": building, "image": "img_pf_supply_" + district,
                              "seconds": round(time.time() - t0), "note": None if pub.get("ok") else "publish failed: %s" % str(pub)[:120]}
                else:
                    result = {"status": "error", "as_of": now, "district": district, "building_slug": building, "note": "report failed: " + out2[-300:]}
            elif code == 4:
                result = {"status": "held_by_daily_chain", "as_of": now, "district": district, "building_slug": building,
                          "note": "lake held; pages fetched and kept, ask again later"}
            else:
                result = {"status": "error", "as_of": now, "district": district, "building_slug": building, "note": out[-300:]}
    mark(uid, "done", result, via)
    log("%s -> %s (%s)" % (req_key, result["status"], result.get("note") or ("%ss" % result.get("seconds", "?"))))


LOCK = os.path.join(ROOT, "logs", "pf_ondemand.lock")


def take_lock():
    """A district crawl can run 35 minutes while Task Scheduler fires every minute: only one poller works at a time. A lock
    older than 2 h belongs to a dead run and is taken over."""
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    if os.path.exists(LOCK):
        try:
            pid = int(open(LOCK, encoding="utf-8").read().strip() or 0)
        except ValueError:
            pid = 0
        if time.time() - os.path.getmtime(LOCK) < 7200 and pid and subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True, text=True).stdout.find(str(pid)) >= 0:
            return False
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def main():
    dry = "--dry" in sys.argv
    if not dry and not take_lock():
        return 0                                                 # another poller is working; this minute's trigger just leaves
    if "--stub" in sys.argv:                                     # local test before v279: requests from a JSON file, results printed
        stub = json.load(open(sys.argv[sys.argv.index("--stub") + 1], encoding="utf-8"))
        pending, via = [("pf_req_" + x["id"], x) for x in stub.get("pending", [])], "stub"
    else:
        pending, via = queue_pending()
    log("%d pending request(s) via %s%s" % (len(pending), via, " (dry)" if dry else ""))
    if not pending:
        return 0
    try:
        for k, req in (pending if dry else pending[:1]):         # one request per run; a dry run just lists them all
            handle(k, req, dry, via)
    finally:
        if not dry:
            try: os.remove(LOCK)
            except OSError: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
