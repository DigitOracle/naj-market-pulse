"""Publish an already-built units_<district>.json (the flats the register puts on each floor) without rescanning the 3.1 GB
units export. build_unit_level.py --push does both; the roll-out builds once for every district and publishes per district.

  python scripts/push_units.py businessbay damachills --push
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BOARD = os.path.join(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")), "data", "board")


def main():
    ds = [a for a in sys.argv[1:] if not a.startswith("--")] or ["businessbay", "damachills"]
    tok = None
    if "--push" in sys.argv:
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    for d in ds:
        p = os.path.join(BOARD, "units_%s.json" % d)
        if not os.path.exists(p):
            print("%s: no units file" % d)
            continue
        doc = json.load(open(p, encoding="utf-8"))
        n = len(doc.get("buildings_by_id") or {})
        if not tok:
            print("%s: %d buildings at unit level (not pushed)" % (d, n))
            continue
        from build_avail_index import push
        print("%s: %d buildings -> push units_%s %s" % (d, n, d, push("units_" + d, doc, tok).get("ok")))


if __name__ == "__main__":
    main()
