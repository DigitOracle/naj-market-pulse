"""Publish the label anchors for one or more districts to the Worker, where the twin reads them at /img/anchors_<slug>.

The anchors are what turns a grey massing into a district a broker recognises: the building's name, the developer and scheme
it is bound to, its height, its facade midpoints and the meshes it owns in the packed model. Rebuild them with
build_anchors.py (which re-reads the register bindings), then run this to put them in front of the app.

Usage: python scripts/push_anchors.py [slug ...]      (no slug = every district that has an anchors file)
"""
import glob, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402

NAMES = os.path.join(ROOT, "data", "names")

if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted(os.path.basename(p)[8:-5] for p in glob.glob(os.path.join(NAMES, "anchors_*.json")))
    tok = env_token("INGEST_TOKEN")
    ok = bad = 0
    for s in slugs:
        f = os.path.join(NAMES, f"anchors_{s}.json")
        if not os.path.exists(f):
            print(f"{s:<26} no anchors file"); bad += 1; continue
        doc = json.load(open(f, encoding="utf-8"))
        n = len(doc.get("anchors") or [])
        nd = sum(1 for a in doc.get("anchors") or [] if a.get("dev"))
        r = push("anchors_" + s, doc, tok)
        good = bool(r.get("ok")); ok += good; bad += not good
        print(f"{s:<26} {n:>5} names  {nd:>4} bound to a developer  ->  {'pushed' if good else 'FAILED'}")
    print(f"{ok} pushed, {bad} failed")
