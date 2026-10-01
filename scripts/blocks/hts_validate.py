"""Validate stage-1 register heights against footprints that already carry a measured height (bldgfacts, anchor,
Overture/OSM height) and against named towers. Writes validation.json. Scratch only."""
import pickle, json, os, statistics, collections, sys, math
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
L = pickle.load(open(os.path.join(HERE, "links.pkl"), "rb"))["links"]
MEAS = ("bldgfacts", "anchor", "overture_height", "osm_height", "anchor_twin")


def is_meas(hs):
    return any(hs.startswith(m) for m in MEAS)


pairs = [l for l in L if l["h"] is not None and is_meas(l["cur_hs"]) and not (abs(l["cur_h"] - 12.0) < 1e-6)]
out = {"n_pairs": len(pairs)}
if pairs:
    errs = [(l["h"] - l["cur_h"]) / l["cur_h"] for l in pairs]
    ae = sorted(abs(e) for e in errs)
    out.update({"median_abs_pct_err": round(100 * statistics.median(ae), 1),
                "within_10pct": round(100 * sum(e <= 0.10 for e in ae) / len(ae), 1),
                "within_20pct": round(100 * sum(e <= 0.20 for e in ae) / len(ae), 1),
                "within_35pct": round(100 * sum(e <= 0.35 for e in ae) / len(ae), 1),
                "median_signed_pct": round(100 * statistics.median(errs), 1)})
    by_src = collections.defaultdict(list)
    for l, e in zip(pairs, errs):
        base = l["src"].split("(")[0]
        by_src[base].append(abs(e))
    out["by_src"] = {k: {"n": len(v), "median_abs_pct": round(100 * statistics.median(v), 1),
                         "within_20pct": round(100 * sum(x <= 0.2 for x in v) / len(v), 1)} for k, v in by_src.items()}
    by_via = collections.defaultdict(list)
    for l, e in zip(pairs, errs):
        by_via[l["via"].split("(")[0].split("_near")[0]].append(abs(e))
    out["by_via"] = {k: {"n": len(v), "median_abs_pct": round(100 * statistics.median(v), 1),
                         "within_20pct": round(100 * sum(x <= 0.2 for x in v) / len(v), 1)} for k, v in by_via.items()}
    worst = sorted(zip(pairs, errs), key=lambda t: -abs(t[1]))[:25]
    out["worst"] = [{"slug": l["slug"], "i": l["i"], "n": l["n"] or l["reg_name"], "register_h": l["h"], "src": l["src"],
                     "current_h": l["cur_h"], "current_hs": l["cur_hs"], "via": l["via"], "parcel": l["parcel"]} for l, e in worst]
    # towers only (current >= 40 m)
    tw = [(l, e) for l, e in zip(pairs, errs) if l["cur_h"] >= 40]
    if tw:
        a = sorted(abs(e) for _, e in tw)
        out["towers_ge40m"] = {"n": len(tw), "median_abs_pct_err": round(100 * statistics.median(a), 1),
                               "within_20pct": round(100 * sum(x <= 0.2 for x in a) / len(a), 1)}
# named checks
want = [("jumeirahvillagecircle", "Amber"), ("businessbay", "Habtoor"), ("businessbay", "Bayz"), ("dubaimarina", "Ciel"),
        ("dubaimarina", "Pinnacle"), ("dubaimarina", "Princess"), ("burjkhalifa", "Burj Khalifa"), ("burjkhalifa", "Address"),
        ("dubaimarina", "Cayan"), ("businessbay", "Peninsula")]
named = []
for slug, frag in want:
    for l in L:
        nm = (l["n"] or "") + " | " + (l["reg_name"] or "")
        if l["slug"] == slug and frag.lower() in nm.lower():
            named.append({"slug": slug, "i": l["i"], "name": nm, "register_h": l["h"], "src": l["src"], "current_h": l["cur_h"],
                          "current_hs": l["cur_hs"], "parcel": l["parcel"], "det": l["det"]})
out["named"] = named
json.dump(out, open(os.path.join(HERE, "validation.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps({k: v for k, v in out.items() if k not in ("worst", "named")}, indent=1))
for x in named:
    print(x["slug"], x["i"], x["name"][:50], x["register_h"], x["src"], "| now", x["current_h"], x["current_hs"])
print("--- worst")
for w in out.get("worst", [])[:15]:
    print(w)
