"""Bring a brochure she sent on WhatsApp down to the machine that holds the truth store, and register it.

The Worker takes the PDF off WhatsApp and parks it in 8 MB parts, because a KV value holds 25 MB and a
broker pack runs to 70. Nothing is parsed up there: the register, the name resolution and DuckDB all
live here. This is the bridge, run by the five-minute task.

  /broc_pending  what is waiting          ->  reassemble from /broc_part  ->  data/brochure_inbox/
  build_media_register.py                 ->  media table + media_index pushed back
  /broc_done     drop the parts, and tell her what was in it

Binding, in order: the filename against developers and projects the truth store already knows, then
the hand list in build_media_register. A brochure that binds to nothing is still kept and still
reported - she is told it needs a name, which is a better answer than silence.
"""
import io, json, os, re, subprocess, sys, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
INBOX = os.path.join(ROOT, "data", "brochure_inbox")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
W = "https://azimuth-2.digitalchemy.workers.dev"
UA = {"User-Agent": "najma-market-pulse/1.0 (brochures)"}


def env_token(name):
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()


def get(path, timeout=280):
    return urllib.request.urlopen(urllib.request.Request(W + path, headers=UA), timeout=timeout).read()


def known_names():
    """Developers and projects the store already knows, longest first so 'Cove Edition 4' beats 'Cove'."""
    try:
        import duckdb
        con = duckdb.connect(DB, read_only=True)
        devs = [r[0] for r in con.execute("select distinct name from developer where name is not null").fetchall()]
        devs += [r[0] for r in con.execute("select distinct developer from dev_sheet where developer is not null").fetchall()]
        projs = [r[0] for r in con.execute("select distinct name from project where name is not null").fetchall()]
        projs += [r[0] for r in con.execute("select distinct project from dev_sheet_unit where project is not null").fetchall()]
        con.close()
    except Exception as e:
        print("  (truth store unreadable, falling back to the hand list:", str(e)[:60] + ")")
        return [], []
    return sorted(set(devs), key=len, reverse=True), sorted(set(projs), key=len, reverse=True)


def guess(name, devs, projs):
    low = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    dev = next((d for d in devs if d and len(d) > 3 and d.lower() in low), None)
    proj = next((p for p in projs if p and len(p) > 4 and p.lower() in low), None)
    return dev, proj


def main():
    quiet = "--quiet" in sys.argv                       # register and clear, but send her nothing (test runs)
    key = env_token("READ_KEY")
    if not key:
        print("no READ_KEY"); return
    q = key and urllib.parse.quote(key)
    try:
        pend = json.loads(get("/broc_pending?key=" + q).decode())
    except Exception as e:
        print("broc_pending failed:", str(e)[:90]); return
    if not pend.get("n"):
        return
    os.makedirs(INBOX, exist_ok=True)
    devs, projs = known_names()
    done = []
    for it in pend["items"]:
        bid, nm, parts = it["id"], it.get("name") or "brochure.pdf", int(it.get("parts") or 1)
        safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", nm)[:80]
        buf = io.BytesIO()
        try:
            for i in range(parts):
                buf.write(get("/broc_part?key=%s&id=%s&i=%d" % (q, urllib.parse.quote(bid), i)))
        except Exception as e:
            print("  part fetch failed for", safe, str(e)[:70]); continue
        raw = buf.getvalue()
        if len(raw) != int(it.get("bytes") or len(raw)):
            print("  size mismatch on %s: got %d want %s - leaving it queued" % (safe, len(raw), it.get("bytes"))); continue
        dest = os.path.join(INBOX, safe)
        open(dest, "wb").write(raw)
        dev, proj = guess(safe, devs, projs)
        print("  pulled %-52s %5.1f MB  -> %s / %s" % (safe[:52], len(raw) / 1e6, dev or "?", proj or "?"))
        done.append({"id": bid, "name": safe, "dev": dev, "proj": proj, "bytes": len(raw)})

    if not done:
        return
    # One register run covers everything new; it is idempotent on content hash.
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_media_register.py"), "--push", "--per-project", "3"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "")[-1200:]
    print(tail)

    for d in done:
        # The register binds by its own list too; if the filename guess found nothing, take the register's word.
        # Its per-file line reads:  "  <Developer>   <Project>   57 pages -> 43 pictures   <filename>"
        if not d["dev"]:
            m0 = re.search(r"^\s+(\S+)\s+(.+?)\s+\d+ pages ->\s+\d+ pictures\s+%s" % re.escape(d["name"][:48]), r.stdout or "", re.M)
            if m0:
                d["dev"], d["proj"] = m0.group(1), m0.group(2).strip()
        n = 0
        m = re.search(r"%s\s+.*?=\s+(\d+) renders" % re.escape(d["dev"]), tail) if d["dev"] else None
        if m:
            n = int(m.group(1))
        if d["dev"] and n:
            say = "Read %s. %d renders from %s are on file now, so I can put your card in front of them." % (d["name"], n, d["dev"])
        elif d["dev"]:
            say = "Read %s. Nothing in it was a usable render, but it is on file under %s." % (d["name"], d["dev"])
        else:
            say = "Got %s and kept it. I could not tell which developer it belongs to - tell me in a line and I will file it." % d["name"]
        try:
            get("/broc_done?key=%s&id=%s&say=%s" % (q, urllib.parse.quote(d["id"]), urllib.parse.quote("" if quiet else say)), timeout=120)
            print("  done:", d["name"], "|", ("(quiet) " if quiet else "") + say[:70])
        except Exception as e:
            print("  broc_done failed for", d["name"], str(e)[:70])


if __name__ == "__main__":
    main()
