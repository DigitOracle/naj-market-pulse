"""Publish the unit-mix files exactly as they are on disk - no rebuild.

build_unit_mix.py rebuilds and publishes in one step. When its output has been reviewed (and, on 29 Sep 2026, patched:
five developer names the rebuild could not find were carried forward from live, marked developer_carried), re-running it
to publish would silently undo the review. This pushes data/board/unitmix_<slug>.json and, with --estate, the two
estate-wide keys (card_joins, and unitmix_projects from the slim hover index - the same payloads build_unit_mix.py sends),
then reads every key back and checks its record count.

  python scripts/push_unitmix_files.py --first alyufrah1          one district, verified, then stop
  python scripts/push_unitmix_files.py --all --estate             every district, then the estate-wide keys
  python scripts/push_unitmix_files.py arjan liwan1               just these
  python scripts/push_unitmix_files.py --kind bldgfacts motorcity   the same, for bldgfacts_<slug> (merged, not rebuilt)
"""
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402

W = "https://azimuth-2.digitalchemy.workers.dev/img/"


def served(key):
    for _ in range(4):
        r = subprocess.run(["curl", "-s", "--compressed", W + key], capture_output=True, timeout=180)
        try:
            return json.loads(r.stdout)
        except ValueError:
            time.sleep(3)
    return None


def main():
    kind = sys.argv[sys.argv.index("--kind") + 1] if "--kind" in sys.argv else "unitmix"
    assert kind in ("unitmix", "bldgfacts"), kind
    argv = list(sys.argv[1:])
    if "--kind" in argv:
        i = argv.index("--kind"); del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    if "--first" in sys.argv:
        slugs = args[:1]
    elif "--all" in sys.argv:
        slugs = sorted(os.path.basename(p)[len(kind) + 1:-5] for p in glob.glob(os.path.join(BOARD, kind + "_*.json"))
                       if not os.path.basename(p).startswith("unitmix_projects"))
    else:
        slugs = args
    tok = env_token("INGEST_TOKEN")
    bad = []
    for s in slugs:
        doc = json.load(open(os.path.join(BOARD, "%s_%s.json" % (kind, s)), encoding="utf-8"))
        n = len(doc["buildings_by_id"])
        ok = push(kind + "_" + s, doc, tok).get("ok")
        back = served(kind + "_" + s) or {}
        m = len(back.get("buildings_by_id") or {})
        good = ok and m == n and back.get("generated") == doc.get("generated")
        print("  %s_%-26s %5d records -> stored=%s served %d %s" % (kind, s, n, ok, m, "OK" if good else "MISMATCH"))
        if not good:
            bad.append(s)
    if "--estate" in sys.argv and kind == "unitmix" and not bad:
        cj = json.load(open(os.path.join(BOARD, "card_joins.json"), encoding="utf-8"))
        up = json.load(open(os.path.join(BOARD, "unitmix_projects_slim.json"), encoding="utf-8"))
        for key, doc, field in (("card_joins", cj, "joins"), ("unitmix_projects", up, "projects")):
            ok = push(key, doc, tok).get("ok")
            m = len(((served(key) or {}).get(field)) or {})
            print("  %-34s %5d entries -> stored=%s served %d %s" % (key, len(doc[field]), ok, m, "OK" if ok and m == len(doc[field]) else "MISMATCH"))
            if not (ok and m == len(doc[field])):
                bad.append(key)
    print("\n%d pushed, %d failed%s" % (len(slugs) - len([b for b in bad if b in slugs]), len(bad), (": " + " ".join(bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
