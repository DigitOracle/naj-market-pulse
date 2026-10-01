"""push_ejari.py -- publish the Ejari files to the app's store (1 Oct 2026).

build_ejari_daily.py and build_ejari_filed.py write data/dld/ejari_daily/*.json to disk; the morning card (v281) and the
contracts page (v279) read KV img_ejari_<...>. This pushes each file through POST /ingest_market as imageName = the file's
stem (ejari_daily_<district>, ejari_recent_<district>, ejari_filed_<district>, ejari_filed_recent_<district>,
ejari_daily_dubai, ejari_filed_dubai, ejari_projects_index), gzipped when over 1 MB (the Worker's /img/ route sees the gzip
magic and serves it with Content-Encoding: gzip), reads each one back from /img/<name> and compares bytes, and skips a file
whose sha256 has not changed since its last successful push (data/dld/ejari_daily/.push_state.json).

    python scripts/push_ejari.py            dry run: what would be pushed, sizes, unchanged skips - touches nothing live
    python scripts/push_ejari.py --push     publish (production - in the daily chain after ejari_daily / ejari_filed, on Kendall's go)
Exit 0 all pushed/skipped and read back equal; 1 a push or readback failed; 2 a file exceeds the 5 MB cap even gzipped.
"""
import base64, glob, gzip, hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "data", "dld", "ejari_daily")
STATE = os.path.join(SRC, ".push_state.json")
WORKER = os.environ.get("AZIMUTH_URL") or "https://azimuth-2.digitalchemy.workers.dev"
GZIP_OVER = 1024 * 1024
CAP = 5 * 1024 * 1024


def env_value(name, required=True):
    v = os.environ.get(name)
    if v:
        return v
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    if required:
        raise SystemExit(name + " not set")
    return None


def token():
    return env_value("INGEST_TOKEN")


def push(name, payload, ctype, tok):
    body = json.dumps({"imageName": name, "image": base64.b64encode(payload).decode(), "contentType": ctype}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read() or b"{}")


def read_back(name):
    """v279 locks /img/ejari_* behind ?key=<READ_KEY> (Kendall's decision); keyed first, keyless as the pre-v279 fallback.
    The key is read from the listener .env and never printed."""
    key = env_value("READ_KEY", required=False)
    urls = ([WORKER + "/img/" + name + "?key=" + urllib.parse.quote(key)] if key else []) + [WORKER + "/img/" + name]
    last = None
    for u in urls:
        req = urllib.request.Request(u, headers={"User-Agent": "najma-market-pulse/1.0", "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (401, 403):
                raise
    raise last


def main():
    do_push = "--push" in sys.argv
    files = sorted(p for p in glob.glob(os.path.join(SRC, "ejari_*.json")) if not os.path.basename(p).startswith("."))
    if not files:
        sys.exit("no ejari_*.json under " + SRC)
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    tok = token() if do_push else None
    rc, pushed, skipped = 0, 0, 0
    for p in files:
        name = os.path.splitext(os.path.basename(p))[0]
        raw = open(p, "rb").read()
        sha = hashlib.sha256(raw).hexdigest()
        if state.get(name, {}).get("sha256") == sha:
            skipped += 1
            continue
        payload = gzip.compress(raw, 9) if len(raw) > GZIP_OVER else raw
        note = "%d KB%s" % (len(raw) // 1024, " -> %d KB gz" % (len(payload) // 1024) if payload is not raw else "")
        if len(payload) > CAP:
            print("CAP   %-40s %s exceeds the 5 MB ingest cap - slim it" % (name, note)); rc = max(rc, 2)
            continue
        if not do_push:
            print("WOULD %-40s %s" % (name, note))
            continue
        try:
            r = push(name, payload, "application/json", tok)
            back = read_back(name)
            ok = bool(r.get("ok")) and hashlib.sha256(back).hexdigest() == sha
            print("%s %-40s %s -> ok=%s readback=%s" % ("PUSH " if ok else "FAIL ", name, note, r.get("ok"), "equal" if ok else "DIFFERENT"))
            if ok:
                state[name] = {"sha256": sha, "pushed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "bytes": len(raw), "stored": len(payload)}
                pushed += 1
            else:
                rc = max(rc, 1)
        except Exception as e:
            print("FAIL  %-40s %s" % (name, str(e)[:160])); rc = max(rc, 1)
    if do_push:
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)
    print("%d files: %d %s, %d unchanged (skipped)%s" % (len(files), pushed if do_push else sum(1 for _ in files) - skipped,
                                                       "pushed" if do_push else "would push", skipped, "" if do_push else "  [dry run]"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
