"""Offline test for dda_pull_ranges (adopt / work / merge) against a fake API whose deep pages are not reproducible unless sorted.

Run: python scripts/test_dda_ranges.py   (no network; writes only under data/raw_downloads/dda/test, removed afterwards)
"""
import argparse, json, os, random, re, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
tmp = tempfile.mkdtemp()
envf = os.path.join(tmp, "test.env")
open(envf, "w").write(chr(10).join(["DDA_ENV=TEST", "DDA_BASE_URL=http://fake", "DDA_BASE_URL_PROD=http://fake", "DDA_CLIENT_ID=x", "DDA_CLIENT_SECRET=x",
                                    "DDA_SECURITY_APP_IDENTIFIER=x", "DDA_APP_ID=x", "DDA_PROD_APP_ID=x", "DDA_PROD_SECURITY_APP_IDENTIFIER=x",
                                    "DDA_PROD_CLIENT_ID=x", "DDA_PROD_CLIENT_SECRET=x"]))
os.environ["DDA_ENV_FILE"] = envf
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import dda_pull_all as P
import dda_pull_ranges as R
api = P.api
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda", "test")
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
R.OUT = OUT
random.seed(11)


class Fake:
    def __init__(self, recs):
        self.recs, self.calls, self.fail_once, self.drift_after = recs, 0, set(), None

    def serve(self, page, ps, order):
        self.calls += 1
        n = len(self.recs); lo, hi = (page - 1) * ps, page * ps
        seq = random.sample(self.recs, n) if (order is None and page >= 3) else (sorted(self.recs, key=lambda r: r[order]) if order else list(self.recs))
        out = seq[lo:hi]
        if self.drift_after is not None and self.calls > self.drift_after and page >= 2: out = list(reversed(out))
        return out


DATA = {}
def fake_auth_get(c, url, tok=None):
    m = re.search(r"/([^/?]+)[?]page=(\d+)&pageSize=(\d+)(?:&order_by=(\w+)&order_dir=asc)?", url)
    ds, page, ps, order = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    f = DATA[ds]
    if page in f.fail_once:
        f.fail_once.discard(page); return 500, b"boom", tok
    return 200, json.dumps({"results": f.serve(page, ps, order)}).encode(), "t"
api.token = lambda c, force=False: "t"
api.auth_get = fake_auth_get
api.RATE_S = 0
api._shared_wait = lambda: None
P.time.sleep = lambda s: None

def recs(n): return [{"ref": "R%04d" % i, "v": i * 1.5} for i in range(n)]
results = []
def check(name, cond, detail): results.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + " :: " + detail)
def ns(**kw): return argparse.Namespace(**kw)
def work(ds, a, b, samples="", order="ref"):
    try: R.cmd_work(ns(dataset=ds, order_by=order, page_size=40, samples=samples, start=a, end=b)); return 0
    except SystemExit as e: return e.code
def merge(ds, last, samples):
    try: R.cmd_merge(ns(dataset=ds, order_by="ref", page_size=40, samples=samples, last_page=last)); return 0
    except SystemExit as e: return e.code
def man(name): return [v for k, v in json.load(open(os.path.join(OUT, "MANIFEST.json"), encoding="utf-8")).items() if k.endswith("/" + name)][0]

NAME, DS = "dcas_activity-open-api", "dcas/dcas_activity-open-api"
DATA[NAME] = Fake(recs(300))
# 1. a sequential ordered pull stopped after two pages, then adopted as range 1-2
sys.argv = ["x", "--datasets", NAME, "--page-size", "40", "--max-pages", "2"]
try: P.main()
except SystemExit: pass
R.cmd_adopt(ns(dataset=DS))
check("adopt turns the checkpoint into range 1-2", os.path.exists(os.path.join(OUT, "dcas__dcas_activity-open-api.json.range-1-2.done")), "range-1-2.done present")
# 2. workers for the rest; the middle one fails once mid-range and resumes
DATA[NAME].fail_once = {5}
rc = work(DS, 3, 5, "4"); check("a failed page exits non-zero and keeps a checkpoint", rc == 2 and os.path.exists(os.path.join(OUT, "dcas__dcas_activity-open-api.json.range-3-5.part")), "exit=%s" % rc)
rc = work(DS, 3, 5, "4"); check("re-running the range resumes and finishes", rc == 0 and os.path.exists(os.path.join(OUT, "dcas__dcas_activity-open-api.json.range-3-5.done")), "exit=%s" % rc)
work(DS, 6, 8, "7")
# 3. merge
rc = merge(DS, 8, "4,7"); e = man(NAME)
final = json.load(open(os.path.join(OUT, e["file"]), encoding="utf-8")) if e.get("file") else {}
refs = [r["ref"] for r in final.get("results", [])]
check("merge writes every record exactly once and marks ok", rc == 0 and e["status"] == "ok" and e["rows"] == 300 and len(refs) == 300 == len(set(refs)) and e["order_by"] == "ref" and e["selfcheck"] == "ok",
      "exit=%s status=%s rows=%s distinct=%s" % (rc, e["status"], e["rows"], len(set(refs))))
check("merge removes the range files", not [f for f in os.listdir(OUT) if ".range-" in f], "leftovers: %s" % [f for f in os.listdir(OUT) if ".range-" in f])

# 4. gap detection and drift
NAME2, DS2 = "dm_agricultural_events_and_workshops-open-api", "dm/dm_agricultural_events_and_workshops-open-api"
DATA[NAME2] = Fake(recs(300))
work(DS2, 1, 3, "4"); work(DS2, 6, 8, "7")
rc = merge(DS2, 8, "4,7"); check("a gap between ranges refuses to merge", isinstance(rc, str) and "gap" in rc, "exit=%s" % str(rc)[:70])
work(DS2, 4, 5)
DATA[NAME2].drift_after = DATA[NAME2].calls
rc = merge(DS2, 8, "4,7"); e = man(NAME2)
check("data that changed since the ranges were pulled is 'unstable', not ok", rc == 3 and e["status"] == "unstable" and not e["file"], "exit=%s status=%s" % (rc, e["status"]))

shutil.rmtree(OUT, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
print(chr(10) + ("ALL %d PASSED" % len(results) if all(results) else "FAILURES: %d of %d" % (results.count(False), len(results))))
sys.exit(0 if all(results) else 1)
