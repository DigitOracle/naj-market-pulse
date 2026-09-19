"""Offline regression test for dda_pull_all against a fake API that misbehaves like the real one.

Run: python scripts/test_dda_pull.py   (no network; writes only under data/raw_downloads/dda/test, removed afterwards)

Covers the 19 Sep 2026 findings: deep pages that are not reproducible without a sort (page 108 of ded_license_master fetched three
times gave three disjoint sets), a column that is unique on page 1 but ties later (so it cannot be the sort key), exact repeated
rows (a real register repeats them; one repeat of record 1 once ended a pull at 137,648 of ~1M rows), an environment that laps
forever (STG), checkpoints from an older pull, and data that changes between the pull and the closing self-check.
"""
import json, os, random, re, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
tmp = tempfile.mkdtemp()
envf = os.path.join(tmp, "test.env")
open(envf, "w").write(chr(10).join(["DDA_ENV=TEST", "DDA_BASE_URL=http://fake", "DDA_BASE_URL_PROD=http://fake", "DDA_CLIENT_ID=x",
                                    "DDA_CLIENT_SECRET=x", "DDA_SECURITY_APP_IDENTIFIER=x", "DDA_APP_ID=x"]))
os.environ["DDA_ENV_FILE"] = envf
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import dda_pull_all as P
api = P.api
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda", "test")
shutil.rmtree(OUT, ignore_errors=True)
random.seed(7)


class Fake:
    def __init__(self, recs, kind="stable", drift_after=None):
        self.recs, self.kind, self.drift_after, self.calls = recs, kind, drift_after, 0

    def serve(self, page, ps, order):
        self.calls += 1
        n = len(self.recs); lo, hi = (page - 1) * ps, page * ps
        if self.kind == "lapping" and order is None:
            return [self.recs[j % n] for j in range(lo, hi)]
        if order is None:
            seq = list(self.recs)
            if self.kind in ("unstable", "unstable_nokey") and page >= 3:
                seq = random.sample(self.recs, n)                   # a different arbitrary order on every request
        elif order == "a_number":                                   # ties broken arbitrarily each time
            seq = sorted(random.sample(self.recs, n), key=lambda r: r["a_number"])
        else:
            seq = sorted(self.recs, key=lambda r: r[order])
            if self.kind == "unstable_nokey" and page >= 3:
                seq = random.sample(self.recs, n)                   # no column gives a reproducible order
        out = seq[lo:hi]
        if self.drift_after is not None and self.calls > self.drift_after and page >= 2:
            out = list(reversed(out))                               # the data moved on after the pull
        return out


DATA = {}
def fake_auth_get(c, url, tok=None):
    m = re.search(r"/([^/?]+)[?]page=(\d+)&pageSize=(\d+)(?:&order_by=(\w+)&order_dir=asc)?", url)
    ds, page, ps, order = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    return 200, json.dumps({"results": DATA[ds].serve(page, ps, order)}).encode(), "t"
api.token = lambda c, force=False: "t"
api.auth_get = fake_auth_get
api.RATE_S = 0
api._shared_wait = lambda: None
P.time.sleep = lambda s: None


def recs(n):
    return [{"ref": "R%04d" % i, "a_number": i if i < 40 else 40 + (i - 40) // 3, "v": i * 1.5} for i in range(n)]

def run(name, fake, page_size=40, max_pages=200):
    DATA[name] = fake
    sys.argv = ["x", "--datasets", name, "--page-size", str(page_size), "--max-pages", str(max_pages)]
    try: P.main()
    except SystemExit: pass
    man = json.load(open(os.path.join(OUT, "MANIFEST.json"), encoding="utf-8"))
    return [v for k, v in man.items() if k.endswith("/" + name)][0]

results = []
def check(name, cond, detail):
    results.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + " :: " + detail)

def final_rows(name):
    fp = os.path.join(OUT, [f for f in os.listdir(OUT) if f.endswith("__" + name + ".json")][0])
    return json.load(open(fp, encoding="utf-8"))["results"]


e = run("dcas_activity-open-api", Fake(recs(95)))
check("stable multi-page dataset ends on its short page, unsorted", e["status"] == "ok" and e["rows"] == 95 and e["order_by"] is None and e["ended_by"] == "short_page" and e["selfcheck"] == "ok", str({k: e[k] for k in ("status", "rows", "order_by", "ended_by", "selfcheck", "last_page")}))

base = recs(95); dups = []
for i, r in enumerate(base):
    dups.append(r)
    if i % 3 == 0: dups.append(dict(r))                              # exact repeat, including one of record 1
e = run("dm_agricultural_events_and_workshops-open-api", Fake(dups))
check("exact repeated rows (record 1 included) never end the pull early", e["status"] == "ok" and e["rows"] == 95 and e["raw_rows"] > 95, "rows=%s raw_rows=%s ended_by=%s" % (e["rows"], e["raw_rows"], e["ended_by"]))

e = run("lad_advocate-open-api", Fake(recs(300), "unstable"))
got = final_rows("lad_advocate-open-api")
check("unreproducible deep pages: rejects the tie-prone key, sorts by the reproducible one, gets every record",
      e["status"] == "ok" and e["order_by"] == "ref" and e["rows"] == 300 and len({r["ref"] for r in got}) == 300 and e["selfcheck"] == "ok",
      "status=%s order_by=%s rows=%s distinct=%s" % (e["status"], e["order_by"], e["rows"], len({r["ref"] for r in got})))

e = run("courts_advocate_office-open-api", Fake(recs(300), "unstable_nokey"))
check("no column makes the pages reproducible: 'unstable', never ok, no final file", e["status"] == "unstable" and not e["file"], "status=%s note=%s" % (e["status"], e["note"][:70]))

e = run("lad_advocacy_firms-open-api", Fake(recs(57), "lapping"))
check("an environment whose pages never run out (STG) still ends, with every record", e["status"] == "ok" and e["rows"] == 57 and e["ended_by"] == "no_new_rows", "status=%s rows=%s ended_by=%s" % (e["status"], e["rows"], e["ended_by"]))

fk = Fake(recs(300), "unstable")
e1 = run("dubai_silicon_oasis_authority_activity_master-open-api", fk, max_pages=3)
check("page ceiling is not ok and keeps a checkpoint", e1["status"] == "max_pages" and e1["rows"] == 120, "status=%s rows=%s" % (e1["status"], e1["rows"]))
e2 = run("dubai_silicon_oasis_authority_activity_master-open-api", fk)
check("resumes the sorted pull from its checkpoint and finishes with every record", e2["status"] == "ok" and e2["rows"] == 300 and e2["order_by"] == "ref", "status=%s rows=%s order_by=%s" % (e2["status"], e2["rows"], e2["order_by"]))

part = os.path.join(OUT, "courts__courts_advocates-open-api.json.part")
os.makedirs(OUT, exist_ok=True)
open(part, "w").write(chr(10).join(json.dumps({"ref": "FAKE%d" % i, "a_number": 0, "v": 0}) for i in range(5)) + chr(10))
json.dump({"page": 5, "first_h": "x", "page_size": 40}, open(part + ".state", "w"))
e = run("courts_advocates-open-api", Fake(recs(95)))
got = final_rows("courts_advocates-open-api")
check("a checkpoint from the older, unordered pull is discarded, not built on", e["status"] == "ok" and e["rows"] == 95 and not any(r["ref"].startswith("FAKE") for r in got), "status=%s rows=%s" % (e["status"], e["rows"]))

e = run("dm_project_applications-open-api", Fake(recs(300), "stable", drift_after=19))
check("data that changes between the pull and the self-check is 'unstable', not ok", e["status"] == "unstable" and "self-check" in e["note"], "status=%s note=%s" % (e["status"], e["note"][:60]))

shutil.rmtree(OUT, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
print(chr(10) + ("ALL %d PASSED" % len(results) if all(results) else "FAILURES: %d of %d" % (results.count(False), len(results))))
sys.exit(0 if all(results) else 1)
