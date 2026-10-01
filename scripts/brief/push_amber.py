"""Publish the Binghatti Amber fix (JVC footprint 1503) from the files ON DISK - no regeneration, so nothing else is rebuilt.

  python push_amber.py            DRY RUN (default): fetch each live key read-only, diff it against the local payload, push nothing
  python push_amber.py --push     publish every key below to azimuth-2 (POST /ingest_market via build_avail_index.push)

Each key is what the pipeline's own publisher sends for that file (same key, same envelope).
"""
import json, os, sys, urllib.request
REPO = r"C:\Dev\naj-market-pulse"
sys.path.insert(0, os.path.join(REPO, "scripts"))
from build_avail_index import WORKER  # noqa: E402

S = "jumeirahvillagecircle"
def load(rel): return json.load(open(os.path.join(REPO, rel), encoding="utf-8"))


def plate():
    d = load(r"data\board\plates_%s.json" % S)
    return {"district": S, "id": "1503", "generated": d.get("generated"), "note": d.get("note"), "building": d["buildings"]["1503"]}


def slim():
    d = load(r"data\board\unitmix_projects_slim.json")
    return {"generated": d.get("generated"), "projects": d["projects"]}


# (KV key the worker serves at /img/<key>, payload, the pipeline publisher it matches)
KEYS = [
    ("anchors_" + S, lambda: load(r"data\names\anchors_%s.json" % S), "push_anchors.py / apply_identity.py"),
    ("identity_" + S, lambda: load(r"data\identity\identity_%s.json" % S), "apply_identity.py"),
    ("bldgfacts_" + S, lambda: load(r"data\board\bldgfacts_%s.json" % S), "build_buildingfacts.py"),
    ("unitmix_" + S, lambda: load(r"data\board\unitmix_%s.json" % S), "build_unit_mix.py"),
    ("unitmix_projects", slim, "build_unit_mix.py (estate-wide, slim hover index)"),
    ("stack_" + S, lambda: load(r"data\board\stack_%s.json" % S), "build_view_openness.py / build_scheme_links.py --push"),
    # plate key left out: JVC plates are not published (live 404)
    ("plots", lambda: load(r"data\board\plots.json"), "plot_points.py --push"),
    ("map_prices", lambda: load(r"data\board\map_prices.json"), "map_prices.py --push"),
    ("search_index", lambda: load(r"data\board\search_index.json"), "build_search_index.py"),
    ("rent_index", lambda: load(r"data\board\rent_index.json"), "build_rent_index.py --push (served as img_rent_index)"),
]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jdiff_lib import diff  # noqa: E402

push = "--push" in sys.argv
if push:
    from build_avail_index import env_token, push as kv_push
    tok = env_token("INGEST_TOKEN")
print(("PUSHING to " if push else "DRY RUN against ") + WORKER)
for key, fn, who in KEYS:
    body = fn()
    size = len(json.dumps(body, ensure_ascii=False).encode())
    if push:
        print("%-38s %8d B  -> %s" % (key, size, kv_push(key, body, tok))); continue
    try:
        live = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/img/" + key, headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=300))
    except Exception as e:
        print("%-38s %8d B  live read failed: %s" % (key, size, str(e)[:80])); continue
    out = diff(live, body)
    print("%-38s %8d B  (%s)  differences vs live: %d" % (key, size, who, len(out)))
    for p, a, b in out[:8]:
        print("      %s | %s -> %s" % (p[:90], json.dumps(a, ensure_ascii=False)[:70], json.dumps(b, ensure_ascii=False)[:70]))
    if len(out) > 8: print("      ... %d more" % (len(out) - 8))
print("nothing pushed" if not push else "done")
