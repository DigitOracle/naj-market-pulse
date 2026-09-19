"""Offline regression test for dda_pull_all: a fake API that laps like the real one (and repeats rows like real registers).

Run: python scripts/test_dda_wrap.py   (no network; writes only under data/raw_downloads/dda/test, removed afterwards)
Covers the 19 Sep 2026 bug: ded_license_master ended at 137,648 rows because one exact repeat of record 1 was read as the lap.
"""
import os, sys, json, tempfile, shutil, re
NL = chr(10)
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
tmp = tempfile.mkdtemp()
envf = os.path.join(tmp, "test.env")
open(envf, "w").write(NL.join(["DDA_ENV=TEST", "DDA_BASE_URL=http://fake", "DDA_BASE_URL_PROD=http://fake", "DDA_CLIENT_ID=x", "DDA_CLIENT_SECRET=x",
                               "DDA_SECURITY_APP_IDENTIFIER=x", "DDA_APP_ID=x"]))
os.environ["DDA_ENV_FILE"] = envf
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import dda_pull_all as P
api = P.api
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda", "test")
shutil.rmtree(OUT, ignore_errors=True)

def rec(i): return {"id": i, "name": "row %d" % i, "v": i * 1.5}
DATA = {}      # dataset -> (sequence of records as the API serves them, wraps?)
def fake_auth_get(c, url, tok=None):
    m = re.search(r"/([^/?]+)[?]page=(\d+)&pageSize=(\d+)", url)
    ds, page, ps = m.group(1), int(m.group(2)), int(m.group(3))
    seq, wraps = DATA[ds]
    n = len(seq); out = []
    for j in range((page - 1) * ps, page * ps):
        if j < n: out.append(seq[j])
        elif wraps: out.append(seq[j % n])
    return 200, json.dumps({"results": out}).encode(), "t"
api.token = lambda c, force=False: "t"
api.auth_get = fake_auth_get
api.RATE_S = 0

def run(ds, seq, wraps, page_size=10, max_pages=200, extra=None):
    DATA[ds] = (seq, wraps)
    sys.argv = ["x", "--datasets", ds, "--page-size", str(page_size), "--max-pages", str(max_pages)] + (extra or [])
    try: P.main()
    except SystemExit: pass
    man = json.load(open(os.path.join(OUT, "MANIFEST.json"), encoding="utf-8"))
    e = [v for k, v in man.items() if k.endswith("/" + ds)][0]
    return e

uniq = lambda n: [rec(i) for i in range(n)]
results = []
def check(name, e, want_rows, want_end):
    ok = e["status"] == "ok" and e["rows"] == want_rows and e["ended_by"] in (want_end if isinstance(want_end, tuple) else (want_end,))
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ": status=%s rows=%s ended_by=%s pages=%s (want rows=%s ended_by=%s)" % (e["status"], e["rows"], e["ended_by"], e["pages"], want_rows, want_end))

# page size 40 against K=10, like a real 1000-row page against K=10
s = uniq(57); s.insert(25, rec(0))
check("repeat of record 1 mid-dataset (old logic stopped near row 25)", run("dcas_activity-open-api", s, True, page_size=40), 57, "lap")
check("plain lap", run("dm_agricultural_events_and_workshops-open-api", uniq(95), True, page_size=40), 95, "lap")
# the lap starts inside the last K-1 records of a page, so the run of first records straddles two pages: the stall fallback must end it
check("lap straddles a page boundary", run("lad_advocate-open-api", uniq(155), True, page_size=40), 155, ("lap", "no_new_rows"))
check("short last page", run("courts_advocate_office-open-api", uniq(34), False, page_size=40), 34, "short_page")
s = [rec(0)] * 10 + [rec(i) for i in range(1, 41)]
check("page 1 starts with identical rows", run("lad_advocacy_firms-open-api", s, True, page_size=10), 41, "no_new_rows")
# a real duplicate run later in the data must not end it: rows 30-39 repeat rows 0-9 exactly
s = uniq(30) + uniq(10) + [rec(i) for i in range(100, 130)]
check("a full repeat of the first 10 rows mid-dataset is still only a wrap look-alike", run("dm_project_applications-open-api", s, True, page_size=40), 60, "lap")
e = run("dubai_silicon_oasis_authority_activity_master-open-api", uniq(90), True, page_size=20, max_pages=2)
ok = e["status"] == "max_pages" and e["rows"] == 40
results.append(ok); print(("PASS " if ok else "FAIL ") + "max-pages ceiling is not ok: status=%s rows=%s" % (e["status"], e["rows"]))
check("resume from the checkpoint and finish", run("dubai_silicon_oasis_authority_activity_master-open-api", uniq(90), True, page_size=20, max_pages=200), 90, "lap")
shutil.rmtree(OUT, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
print(NL + ("ALL %d PASSED" % len(results) if all(results) else "FAILURES: %d of %d" % (results.count(False), len(results))))
