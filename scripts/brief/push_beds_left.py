"""Publish the beds-left register (DDA session, 30 Sep 2026) as KV img_beds_left_<district> - Kendall's go, 1 Oct 2026.
  python push_beds_left.py            list what would be sent (nothing pushed)
  python push_beds_left.py --push     publish through POST /ingest_market (build_avail_index.push, the pipeline's own publisher)
"""
import glob, json, os, sys
REPO = r"C:\Dev\naj-market-pulse"
sys.path.insert(0, os.path.join(REPO, "scripts"))
from build_avail_index import WORKER  # noqa: E402

files = sorted(glob.glob(os.path.join(REPO, r"data\dld\beds_left\beds_left_*.json")))
push = "--push" in sys.argv
if push:
    from build_avail_index import env_token, push as kv_push
    tok = env_token("INGEST_TOKEN")
print(("PUSHING to " if push else "DRY RUN for ") + WORKER, len(files), "files")
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    district = os.path.basename(f)[len("beds_left_"):-len(".json")]
    key = "beds_left_" + district
    assert d.get("rows") is not None and d.get("as_of"), f
    size = len(json.dumps(d, ensure_ascii=False).encode())
    if push:
        print("%-44s %8d B  -> %s" % (key, size, kv_push(key, d, tok)))
    else:
        print("%-44s %8d B  %d rows  as_of %s" % (key, size, len(d["rows"]), d["as_of"]))
print("done" if push else "nothing pushed")
