"""Before/after placeholder shares from the rebuilt files. Scratch."""
import json, glob, os, sys, collections
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
D = r"C:\Dev\naj-market-pulse\data"
PH = {"unknown", "default12"}


def cls(hs):
    if hs in PH:
        return "placeholder"
    if hs == "community_median":
        return "median"
    if hs.startswith("register_"):
        return "register"
    if hs.startswith("typical_"):
        return "typical"
    return "measured_other"


out = {}
# city
base = json.load(open(os.path.join(HERE, "base_city.json"), encoding="utf-8"))
rows = []
T = collections.Counter()
for p in sorted(glob.glob(os.path.join(D, "blocks_city", "*", "meta.json"))):
    m = json.load(open(p, encoding="utf-8"))
    s = m["slug"]
    n = m["buildings"]
    if not n:
        continue
    c = collections.Counter()
    for hs, k in m["height_sources"].items():
        c[cls(hs)] += k
    b = base.get(s, {})
    ph0 = sum(v for hs, v in (b.get("height_sources") or {}).items() if hs in PH)
    ph_excl_median = c["placeholder"] + c["median"]
    rows.append({"slug": s, "name": m["name"], "n": n, "before": round(ph0 / n, 3), "after_register": round(ph_excl_median / n, 3),
                 "after_median": round(c["placeholder"] / n, 3), "register": c["register"], "typical_hint_or_class": c["typical"],
                 "median": c["median"], "median_h": (m.get("dm_register_check") or {}).get("median_h"), "overlay": m.get("heights_overlay")})
    T["n"] += n; T["before"] += ph0; T["after_register"] += ph_excl_median; T["after_median"] += c["placeholder"]; T["register"] += c["register"]
    T["median"] += c["median"]; T["typical"] += c["typical"]; T["stale"] += (m.get("heights_overlay") or {}).get("stale_skipped", 0)
out["city"] = {"totals": dict(T), "share_before": round(T["before"] / T["n"], 4), "share_after_register": round(T["after_register"] / T["n"], 4),
               "share_after_median": round(T["after_median"] / T["n"], 4), "rows": rows}
# ce
ce_rows = []
TC = collections.Counter()
for p in sorted(glob.glob(os.path.join(HERE, "base_ce", "*.json"))):
    s = os.path.basename(p)[:-5]
    bm = json.load(open(p, encoding="utf-8"))["meta"]
    ap = os.path.join(D, "ce", s, "blocks.json")
    am = json.load(open(ap, encoding="utf-8"))["meta"]
    n = am["buildings"]
    ph0 = sum(v for hs, v in (bm.get("height_sources") or {}).items() if hs in PH)
    c = collections.Counter()
    for hs, k in (am.get("height_sources") or {}).items():
        c[cls(hs)] += k
    ce_rows.append({"slug": s, "n": n, "before": round(ph0 / n, 3) if n else None, "after_register": round((c["placeholder"] + c["median"]) / n, 3),
                    "after_median": round(c["placeholder"] / n, 3), "register": c["register"], "typical": c["typical"], "median": c["median"]})
    TC["n"] += n; TC["before"] += ph0; TC["after_register"] += c["placeholder"] + c["median"]; TC["after_median"] += c["placeholder"]
    TC["register"] += c["register"]; TC["median"] += c["median"]; TC["typical"] += c["typical"]
out["ce"] = {"totals": dict(TC), "share_before": round(TC["before"] / TC["n"], 4), "share_after_register": round(TC["after_register"] / TC["n"], 4),
             "share_after_median": round(TC["after_median"] / TC["n"], 4), "rows": ce_rows}
json.dump(out, open(os.path.join(HERE, "summary.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
for k in ("city", "ce"):
    o = out[k]
    print(k, o["totals"], "before", o["share_before"], "after register", o["share_after_register"], "after median", o["share_after_median"])
    rs = [r for r in o["rows"] if r["n"] >= 20]
    print("  top 10 (lowest placeholder after register, excl. median):")
    for r in sorted(rs, key=lambda r: (r["after_register"], -r["n"]))[:10]:
        print("   ", r["slug"], r["n"], r["before"], "->", r["after_register"], "->", r["after_median"], "reg", r["register"])
    print("  bottom 10:")
    for r in sorted(rs, key=lambda r: (-r["after_register"], -r["n"]))[:10]:
        print("   ", r["slug"], r["n"], r["before"], "->", r["after_register"], "->", r["after_median"], "reg", r["register"])
