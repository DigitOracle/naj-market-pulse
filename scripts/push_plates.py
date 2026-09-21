"""Publish the indicative floor plates, one key per building (the video session's handover, 21 Sep 2026).

plates_<district>.json is 1.8 MB because it holds every building in the district; a building page needs one of them. So each
building is pushed on its own key, plate_<district>_<id>, which the page fetches for the building it is showing - median 10 KB,
largest 86 KB (Al Habtoor Tower, 91 floors).

  python scripts/push_plates.py businessbay damachills          count and size them, push nothing
  python scripts/push_plates.py businessbay damachills --push    publish
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")


def main():
    districts = [a for a in sys.argv[1:] if not a.startswith("--")] or ["businessbay", "damachills"]
    tok = None
    if "--push" in sys.argv:
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    for d in districts:
        p = os.path.join(BOARD, "plates_%s.json" % d)
        if not os.path.exists(p):
            print("%s: no plates file - run scripts/build_floor_plates.py first" % d)
            continue
        doc = json.load(open(p, encoding="utf-8"))
        note, gen = doc.get("note"), doc.get("generated")
        bl = doc.get("buildings") or {}
        sizes, pushed, t0 = [], 0, time.time()
        for i, b in bl.items():
            one = {"district": d, "id": i, "generated": gen, "note": note, "building": b}
            body = json.dumps(one, ensure_ascii=False, separators=(",", ":"))
            sizes.append(len(body))
            if tok:
                from build_avail_index import push
                if push("plate_%s_%s" % (d, i), one, tok).get("ok"):
                    pushed += 1
        sizes.sort()
        print("%s: %d buildings, median %d KB, largest %d KB%s"
              % (d, len(bl), sizes[len(sizes) // 2] // 1024 if sizes else 0, (sizes[-1] // 1024) if sizes else 0,
                 (", pushed %d in %.0fs" % (pushed, time.time() - t0)) if tok else ""))


if __name__ == "__main__":
    main()
