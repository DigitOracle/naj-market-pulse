"""End-to-end audit of the Najma / Azimuth pipeline. Read-only: it touches nothing and sends nothing.

Every check names what it looked at and what it found, so a PASS is a claim you can go and verify
rather than a reassurance. WARN is "working, but degraded or unproven". FAIL is "this is broken now".

  python scripts/audit_najma.py            everything
  python scripts/audit_najma.py --quick    skip the slow Worker round-trips
"""
import argparse, datetime as dt, io, json, os, subprocess, sys, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
W = "https://azimuth-2.digitalchemy.workers.dev"
LISTENER = r"C:\Dev\azimuth-listener-naj"
CAPTURE = os.path.join(LISTENER, "docs", "developer_availability")
UA = {"User-Agent": "najma-market-pulse/1.0 (audit)"}
NOW = dt.datetime.now()

RESULTS = []


def check(area, name, state, detail):
    RESULTS.append((area, name, state, detail))
    mark = {"PASS": "  ok  ", "WARN": " warn ", "FAIL": " FAIL "}[state]
    print("%s %-34s %s" % (mark, name, detail))


def env_token(n):
    try:
        for line in io.open(os.path.join(LISTENER, ".env"), encoding="utf-8"):
            if line.startswith(n + "="):
                return line.split("=", 1)[1].strip()
    except Exception:
        return None


def get(path, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(W + path, headers=UA), timeout=timeout).read()


def age_h(ts):
    return (NOW - ts).total_seconds() / 3600


def section(t):
    print("\n" + t)
    print("-" * len(t))


def audit_listener():
    section("1. LISTENER  (her WhatsApp, read-only, on this machine)")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*azimuth-listener-naj*' } | Select-Object -First 1 -ExpandProperty ProcessId"],
                             capture_output=True, text=True, timeout=90).stdout.strip()
        check("listener", "process", "PASS" if out else "FAIL", "PID " + out if out else "not running")
    except Exception as e:
        check("listener", "process", "WARN", "could not check: " + str(e)[:50])
    try:
        g = json.load(io.open(os.path.join(LISTENER, "groups.json"), encoding="utf-8"))
        dev = [v for v in g.values() if "develop" in (v.get("name") or "").lower()]
        last = dt.datetime.fromtimestamp(dev[0]["last_activity"]) if dev and dev[0].get("last_activity") else None
        check("listener", "developer group followed", "PASS" if dev else "FAIL",
              "%s, %d groups seen, last message %.0f h ago" % (dev[0]["name"] if dev else "-", len(g), age_h(last)) if last else "no activity recorded")
    except Exception as e:
        check("listener", "developer group followed", "FAIL", str(e)[:60])
    try:
        pdfs = [f for f in os.listdir(CAPTURE) if f.lower().endswith(".pdf")]
        newest = max(os.path.getmtime(os.path.join(CAPTURE, f)) for f in pdfs)
        check("listener", "document capture", "PASS", "%d PDFs, newest %.0f h old" % (len(pdfs), age_h(dt.datetime.fromtimestamp(newest))))
    except Exception as e:
        check("listener", "document capture", "FAIL", str(e)[:60])
    for f, label in (("offers.jsonl", "caption/offer capture"), ("skipped.jsonl", "over-cap record"), ("links.jsonl", "link capture")):
        p = os.path.join(CAPTURE, f)
        n = sum(1 for _ in io.open(p, encoding="utf-8")) if os.path.exists(p) else 0
        check("listener", label, "PASS" if os.path.exists(p) else "WARN",
              "%d recorded" % n if os.path.exists(p) else "no file yet (nothing has matched since v33)")


def audit_tasks():
    section("2. SCHEDULED TASKS  (this machine)")
    try:
        raw = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-ScheduledTask | Where-Object {$_.TaskName -like 'Najma*' -or $_.TaskName -like 'DA_Azimuth*'} | ForEach-Object { $i=$_|Get-ScheduledTaskInfo; '{0}|{1}|{2}|{3}|{4}' -f $_.TaskName,$_.State,$i.LastRunTime,$i.LastTaskResult,$i.NextRunTime }"],
                             capture_output=True, text=True, timeout=120).stdout.strip().splitlines()
    except Exception as e:
        check("tasks", "scheduler", "FAIL", str(e)[:60]); return
    for line in raw:
        p = line.split("|")
        if len(p) < 4:
            continue
        nm, state, lastrun, res = p[0], p[1], p[2], p[3]
        try:
            lr = dt.datetime.strptime(lastrun.strip(), "%m/%d/%Y %I:%M:%S %p")
            ago = "%.1f h ago" % age_h(lr)
        except Exception:
            ago = lastrun.strip()
        # A repeating task with a bounded window reports 267014 when the window closes, and 0x40010004
        # when the machine sleeps under it. Neither is a failure, and treating them as one made this
        # audit cry wolf about two tasks that were scheduled and fine. What matters is whether the task
        # will run again: a future NextRunTime is the real health signal, not the last exit code.
        BENIGN = ("0", "267009", "267011", "267014", "1073807364")
        res_s = res.strip()
        nxt = p[4].strip() if len(p) > 4 else ""
        ok = res_s in BENIGN and bool(nxt)
        note = "%s, last %s, next %s, result %s" % (state, ago, nxt or "NONE SCHEDULED", res_s)
        if res_s in ("267014", "1073807364") and nxt:
            note += "  (window closed or machine slept; next run scheduled)"
        check("tasks", nm, "PASS" if ok else "FAIL", note)


def audit_store():
    section("3. TRUTH STORE  (data/graph/najma.duckdb)")
    try:
        import duckdb
        con = duckdb.connect(DB, read_only=True)
    except Exception as e:
        check("store", "open", "FAIL", str(e)[:70]); return
    for t, floor in (("project", 5000), ("building", 60000), ("evidence", 250000), ("dev_sheet_unit", 500), ("media", 100)):
        try:
            n = con.execute("select count(*) from %s" % t).fetchone()[0]
            check("store", t, "PASS" if n >= floor else "WARN", "%s rows" % f"{n:,}")
        except Exception as e:
            check("store", t, "FAIL", str(e)[:50])
    try:
        n = con.execute("select count(*) from dev_doc where state <> 'held'").fetchone()[0]
        check("store", "documents never downloaded", "WARN" if n else "PASS", "%d known gaps" % n)
    except Exception as e:
        check("store", "documents never downloaded", "FAIL", str(e)[:50])
    try:
        rows = con.execute("select developer, count(*) from media where kind='render' group by 1 order by 2 desc").fetchall()
        check("store", "renders bound to a developer", "PASS" if rows else "WARN",
              ", ".join("%s %d" % r for r in rows) or "none")
    except Exception as e:
        check("store", "renders bound to a developer", "FAIL", str(e)[:50])
    try:
        v = con.execute("select verdict from dev_link where verdict is not null").fetchall()
        check("store", "links carrying a checked verdict", "PASS" if v else "WARN", "%d checked" % len(v))
    except Exception:
        pass
    con.close()


def audit_data_freshness():
    section("4. MARKET DATA  (what the morning feed is built on)")
    import glob
    for pat, label, warn_h in (("data/transactions-*.csv", "DLD transactions", 30), ("data/rents-*.csv", "DLD rents", 30)):
        fs = [f for f in glob.glob(os.path.join(ROOT, pat)) if "ytd" not in f and "api" not in f]
        if not fs:
            check("data", label, "FAIL", "no files"); continue
        newest = max(fs, key=os.path.getmtime)
        h = age_h(dt.datetime.fromtimestamp(os.path.getmtime(newest)))
        check("data", label, "PASS" if h < warn_h else "WARN", "%s, %.0f h old" % (os.path.basename(newest), h))
    p = os.path.join(ROOT, "public", "pulse.json")
    if os.path.exists(p):
        h = age_h(dt.datetime.fromtimestamp(os.path.getmtime(p)))
        check("data", "pulse.json (feeds the angles)", "PASS" if h < 30 else "FAIL", "%.0f h old" % h)
    else:
        check("data", "pulse.json (feeds the angles)", "FAIL", "missing")


def audit_worker(quick):
    section("5. WORKER  (azimuth-2, what her phone talks to)")
    key = env_token("READ_KEY")
    if not key:
        check("worker", "read key", "FAIL", "not in the listener .env"); return
    q = urllib.parse.quote(key)
    routes = [("/inbox?n=3&key=" + q, "inbound record", True), ("/broc_pending?key=" + q, "brochure queue", True),
              ("/pic_resume?min_age=99999&key=" + q, "picture job resume", True),
              ("/img/media_index?key=" + q, "developer render index", True),
              ("/img/avail_index?key=" + q, "availability strip", True),
              ("/style_status?key=" + q, "her style card", True)]
    for path, label, _ in routes:
        if quick and label in ("picture job resume",):
            continue
        try:
            raw = get(path, timeout=120)
            j = json.loads(raw.decode())
            if label == "inbound record":
                d = "%d messages on record" % j.get("n", 0)
            elif label == "brochure queue":
                d = "%d waiting" % j.get("n", 0)
            elif label == "picture job resume":
                d = "%d jobs outstanding" % j.get("checked", 0)
            elif label == "developer render index":
                d = ", ".join("%s %d" % (v["name"], sum(len(p["renders"]) for p in v["projects"].values())) for v in j.get("developers", {}).values())
            elif label == "availability strip":
                d = "%d sheets, updated %s" % (len(j.get("sheets", [])), j.get("updated"))
            else:
                d = "step=%s, %d style refs" % ((j.get("flow") or {}).get("step"), len(j.get("refs") or []))
            check("worker", label, "PASS", d)
        except Exception as e:
            check("worker", label, "FAIL", str(e)[:70])
    try:
        code = urllib.request.urlopen(urllib.request.Request(W + "/inbox", headers=UA), timeout=30).getcode()
        check("worker", "keyed routes reject no key", "FAIL", "HTTP %d without a key" % code)
    except urllib.error.HTTPError as e:
        check("worker", "keyed routes reject no key", "PASS" if e.code == 401 else "FAIL", "HTTP %d" % e.code)
    except Exception as e:
        check("worker", "keyed routes reject no key", "WARN", str(e)[:50])


def audit_feed(quick):
    section("6. THE MORNING FEED  (07:00 GST)")
    key = env_token("READ_KEY")
    try:
        out = subprocess.run(["npx", "wrangler", "kv", "key", "get", "mkt_feed_qa",
                              "--namespace-id", "2cdf36a27f834b5f9c726294d36770fb", "--text"],
                             cwd=r"C:\Dev\azimuth-worker", capture_output=True, text=True, timeout=240, shell=True).stdout
        i = out.find("{")
        qa = json.loads(out[i:]) if i >= 0 else {}
        at = qa.get("at", "")
        # "repaired" is the REDUNDANCY pass. The voice pass is voice_repaired, written after it (v126).
        rep = qa.get("voice_repaired")
        check("feed", "last run", "PASS" if at else "WARN", at or "no record")
        if rep is None:
            check("feed", "voice pass", "WARN", "record predates v126 - cannot tell whether it ran")
        else:
            check("feed", "voice pass", "PASS" if len(rep) >= 5 else "WARN",
                  "%d angles rewritten into her voice at %s" % (len(rep), qa.get("voice_at", "?")))
        rem = qa.get("remaining") or []
        check("feed", "repeat check", "PASS" if not rem else "WARN",
              "%d angles still overlap recent subjects" % len(rem))
    except Exception as e:
        check("feed", "last run", "WARN", "could not read: " + str(e)[:60])


def summary():
    section("SUMMARY")
    n = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for _, _, st, _ in RESULTS:
        n[st] += 1
    print("  %d pass   %d warn   %d fail" % (n["PASS"], n["WARN"], n["FAIL"]))
    for area, name, st, detail in RESULTS:
        if st != "PASS":
            print("  %-5s %-34s %s" % (st, name, detail))
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true"); a = ap.parse_args()
    print("NAJMA PIPELINE AUDIT   %s" % NOW.strftime("%Y-%m-%d %H:%M"))
    audit_listener(); audit_tasks(); audit_store(); audit_data_freshness(); audit_worker(a.quick); audit_feed(a.quick)
    sys.exit(summary())
