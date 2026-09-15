"""One line to Kendall on WhatsApp when a Najma chain fails or a contract holds a feed. Never to Naj.

Data Spine Phase 1 (13 Sep 2026). Posts to /owner_note on meeting-capture, Kendall's own Azimuth instance. The route refuses
on any instance without OWNER_TEMPLATE, so azimuth-2 cannot carry an alert to her, and it uses the Worker's ownerNotify, which
falls back to the approved azimuth_daily template outside WhatsApp's 24-hour window. The ingest token comes from Kendall's
listener .env (C:\\Dev\\azimuth-listener\\.env, INGEST_URL = meeting-capture) and is never printed.

An alert is late, never lost: until /owner_note is deployed, or whenever a send fails, the line waits in
data/runs/alerts_pending.jsonl and goes out with the next successful send. Several waiting lines leave as ONE message.

Usage: python scripts/notify_owner.py "text"      send (after flushing anything waiting)
       python scripts/notify_owner.py --flush     retry what is waiting
       python scripts/notify_owner.py --pending   show what is waiting, send nothing
"""
import datetime as dt, json, os, sys, urllib.error, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PENDING = os.path.join(ROOT, "data", "runs", "alerts_pending.jsonl")
OWNER_ENV = r"C:\Dev\azimuth-listener\.env"          # Kendall's listener: INGEST_URL points at meeting-capture
OWNER_URL = "https://meeting-capture.digitalchemy.workers.dev/owner_note"
MAX_PENDING = 30


def _token():
    try:
        for line in open(OWNER_ENV, encoding="utf-8"):
            if line.startswith("INGEST_TOKEN="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def _post(text):
    tok = _token()
    if not tok:
        return False, "no INGEST_TOKEN in Kendall's listener .env"
    body = json.dumps({"text": text[:1500]}).encode()
    req = urllib.request.Request(OWNER_URL, data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json",
                                          "User-Agent": "najma-market-pulse/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            reply = r.read(200).decode("utf-8", "replace")
            return (r.status == 200 and reply.startswith("sent")), reply[:80]
    except urllib.error.HTTPError as e:
        return False, "http %s" % e.code
    except Exception as e:                                     # offline, DNS, timeout
        return False, str(e)[:80]


def _read_pending():
    if not os.path.exists(PENDING):
        return []
    with open(PENDING, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def _write_pending(items):
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    items = items[-MAX_PENDING:]
    with open(PENDING, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def flush():
    """Send everything waiting as one message. Returns (sent, still_waiting)."""
    items = _read_pending()
    if not items:
        return 0, 0
    if len(items) == 1:
        text = items[0]["text"]
    else:
        text = "Najma alerts held while the route was down (%d):\n" % len(items) + "\n".join(
            "- %s %s" % (it["at"][5:16].replace("T", " "), it["text"]) for it in items)
    ok, detail = _post(text)
    if ok:
        _write_pending([])
        return len(items), 0
    for it in items:
        it["last_try"] = dt.datetime.now().isoformat(timespec="seconds")
        it["detail"] = detail
    _write_pending(items)
    return 0, len(items)


def send(text):
    """Flush the queue, then send. True when this line reached Kendall's WhatsApp."""
    text = " ".join(str(text).split())
    if not text:
        return False
    items = _read_pending()
    if not any(it["text"] == text for it in items):            # the same alert twice is noise, not news
        items.append({"at": dt.datetime.now().isoformat(timespec="seconds"), "text": text})
        _write_pending(items)
    sent, waiting = flush()
    return waiting == 0 and sent > 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--pending":
        for it in _read_pending():
            print(it["at"], "|", it["text"], "|", it.get("detail", ""))
    elif args[0] == "--flush":
        s, w = flush()
        print("sent %d, still waiting %d" % (s, w))
    else:
        ok = send(" ".join(args))
        print("sent" if ok else "queued (route not live or send failed) - see data/runs/alerts_pending.jsonl")
