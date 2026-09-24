"""Reconcile buildings that appear in more than one district's geojson and are massed at different heights.

District cuts overlap. 2,357 footprints sit in more than one data/ce/<slug>/buildings.geojson and 575 carry a
different bHeight in the two files, because a newer cut inherited a real height its older neighbour never had:

    althanyahfifth b590  340.0 m   +  jltnorth b1428   12.0 m
    dubaimarina    b9    147.0 m   +  jltnorth b2       9.4 m   Horizon Tower
    liwan1 (cut 21 Sep) holds the higher value 496 times; wadialsafa5 and siliconoasis (both 1 Sep) hold
    the stub 482 times between them.

In the web twin nothing is drawn twice - one district tile is served at a time - so this is a CORRECTNESS
problem there: a viewer in wadialsafa5 sees a 12 m stub where liwan1 shows a tower. In Unreal, where several
districts import into one level, both copies exist and z-fight.

THE RULE IS NARROW ON PURPOSE. It raises a building only where the losing value is <= 12 m - a placeholder,
not a measurement. It does NOT take the max generally: the Sobha session found a pair where the unsourced
250/220 would have beaten the sourced 211/179, so "newer cut wins" and "tallest wins" are both wrong as
general rules. Where the loser carries a height_source, or sits above 12 m, the disagreement is left for a
person and reported.

SKIPPED ENTIRELY: features with register_placeholder=true (Sobha's Hartland II entries in bukadra, i 658-670).
Their heights are Dubai Municipality permitted heights, not OSM stubs, and are not ours to reconcile.

Feature ORDER and COUNT are never changed - every b<i> shape name, shape_map, facade_v2 entry and published
bld3_<slug>_b<i> KV key depends on the index. Only the bHeight property value moves.

  python scripts/reconcile_shared_heights.py --dry-run
  python scripts/reconcile_shared_heights.py --apply
"""
import json
import os
import shutil
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
PLACEHOLDER = 12.0


def centroid(geom):
    c = geom["coordinates"]
    ring = c[0] if geom["type"] == "Polygon" else c[0][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (round(sum(xs) / len(xs), 6), round(sum(ys) / len(ys), 6))


def height(props):
    try:
        return float(props.get("bHeight") or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    apply = "--apply" in sys.argv
    if not apply and "--dry-run" not in sys.argv:
        print(__doc__)
        return 2

    files = sorted(p for p in
                   (os.path.join(CEDIR, d, "buildings.geojson") for d in os.listdir(CEDIR))
                   if os.path.exists(p))
    docs = {}
    groups = defaultdict(list)
    for p in files:
        slug = os.path.basename(os.path.dirname(p))
        docs[slug] = json.load(open(p, encoding="utf-8"))
        for i, f in enumerate(docs[slug]["features"]):
            pr = f["properties"]
            if pr.get("register_placeholder"):
                continue                      # permitted heights, not ours to reconcile
            try:
                groups[centroid(f["geometry"])].append((slug, i))
            except Exception:
                continue

    raised = defaultdict(list)
    left = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        hs = [(height(docs[s]["features"][i]["properties"]), s, i) for s, i in members]
        if len({round(h, 1) for h, _, _ in hs}) == 1:
            continue
        hs.sort()
        best_h, best_s, best_i = hs[-1]
        # The WINNER has to be a real height, not merely the larger of two stubs. Without this the rule
        # "raises" 6.2 m to 9.4 m across 429 buildings - churn that reads as a fix and changes nothing
        # anyone can see. Only 21 of the 575 are a placeholder losing to an actual height.
        if best_h <= PLACEHOLDER + 0.01:
            continue
        for h, s, i in hs[:-1]:
            if h > PLACEHOLDER + 0.01:
                # Not a placeholder: two real-looking values disagree. Leave it and say so.
                left.append((s, i, h, best_s, best_i, best_h,
                             docs[s]["features"][i]["properties"].get("height_source")))
                continue
            raised[s].append((i, h, best_h, best_s))

    n_raised = sum(len(v) for v in raised.values())
    print("shared footprints with a height disagreement : %d" % (n_raised + len(left)))
    print("  raised (loser was <= %.0f m placeholder)    : %d across %d districts"
          % (PLACEHOLDER, n_raised, len(raised)))
    print("  left for a person (both values look real)  : %d" % len(left))
    print()
    for s in sorted(raised, key=lambda k: -len(raised[k])):
        gains = raised[s]
        print("  %-26s %4d raised, tallest %.1f m (from %s)"
              % (s, len(gains), max(g[2] for g in gains), gains[0][3]))

    if not apply:
        print("\ndry run - nothing written")
        return 0

    for s, gains in raised.items():
        p = os.path.join(CEDIR, s, "buildings.geojson")
        bak = p + ".bak_preshared"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        doc = docs[s]
        before = len(doc["features"])
        for i, was, now, src in gains:
            pr = doc["features"][i]["properties"]
            pr["bHeight"] = now
            pr["height_source"] = "shared_footprint:%s" % src
            pr["height_basis"] = "raised from %.1f m placeholder to the value the same footprint carries in %s" % (was, src)
        assert len(doc["features"]) == before, "feature count changed - refusing to write"
        tmp = p + ".tmp"
        json.dump(doc, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, p)
        print("  wrote %-26s %d raised (backup %s)" % (s, len(gains), os.path.basename(bak)))

    json.dump({"raised": {s: [{"bid": "b%d" % i, "was": w, "now": n, "from": f} for i, w, n, f in v]
                          for s, v in raised.items()},
               "left_for_review": [{"district": s, "bid": "b%d" % i, "height": h,
                                    "other": "%s b%d" % (bs, bi), "other_height": bh, "height_source": src}
                                   for s, i, h, bs, bi, bh, src in left]},
              open(os.path.join(CEDIR, "_shared_height_reconcile.json"), "w", encoding="utf-8"), indent=1)
    print("\nreport: data/ce/_shared_height_reconcile.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
