"""LAB (floor-use technique #2): score the rule's ESTIMATED units against the registers. Research use only.

Truths (never inputs to the rule):
  DLD  data/board/unitmix_<slug>.json   total_units, and units by class from the DLD units register TYPE rows
                                        (studio / N bedroom / penthouse ... = homes, Office, Retail; NA / Unit / GYM = unknown)
  DM   data/board/stack_<slug>.json     per-floor unit count k on "dm_floors" buildings (the Municipality floor register;
                                        the rule reads that register's USE and AREA per floor, never its k)
Estimates (data/lab/flooruse/, written by scripts/lab_flooruse_build.py):
  rule                flooruse_<slug>.csv                       register stack + register/prior plate (the full method)
  noplate             flooruse_<slug>_noplate.csv               register stack, every floor at the footprint
  noregister          flooruse_<slug>_noregister.csv            default stack everywhere (+ prior plate on flagged footprints)
  noregister_nonames  flooruse_<slug>_noregister_nonames.csv    default stack, class from height only
  incumbent           data/board/bldgfacts_<slug>.json units_indicative (footprint x storeys x 0.78 / 105, use-blind,
                      withheld on plate_suspect buildings - so it is scored on the easier half only)

  python scripts/lab_flooruse_eval.py businessbay
    -> data/lab/flooruse/flooruse_eval_<slug>.json      metrics
    -> data/lab/flooruse/flooruse_compare_<slug>.csv    one row per registered building (full method + ablations side by side)
"""
import csv
import json
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
OUT = os.path.join(ROOT, "data", "lab", "flooruse")
VARIANTS = [("rule", ""), ("noplate", "_noplate"), ("noregister", "_noregister"), ("noregister_nonames", "_noregister_nonames")]
HOME = re.compile(r"^(studio|\d+\s*(bedroom|br|b/r)|penthouse|duplex|townhouse|hotel apartment)$", re.I)


def rows(path):
    return {int(r["i"]): r for r in csv.DictReader(open(path, encoding="utf-8"))}


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def types_of(u):
    """Registered units by class from the DLD units register TYPE rows. unitmix's own asset_classes block is NOT used: it
    comes from the DLD building table's flats/offices/shops columns and reads 0 homes on towers whose type rows are all
    flats (Elite Business Bay Residence: 529 homes by type, residential 0)."""
    out = {"residential": 0, "office": 0, "retail": 0, "unknown": 0}
    for r in u.get("rows") or []:
        t = str(r.get("type") or "").strip()
        n = r.get("units") or 0
        if HOME.match(t):
            out["residential"] += n
        elif t.lower() == "office":
            out["office"] += n
        elif t.lower() in ("retail", "shop"):
            out["retail"] += n
        else:
            out["unknown"] += n
    return out


def metrics(pairs):
    """(estimate, truth) pairs, truth > 0."""
    p = [(e, t) for e, t in pairs if e is not None and t]
    if not p:
        return {"n": 0}
    ape = [abs(e - t) / t for e, t in p]
    lr = [math.log(max(e, 0.5) / t) for e, t in p]
    return {"n": len(p),
            "median_abs_pct_err": round(100 * st.median(ape), 1),
            "within_25pct": round(100.0 * sum(a <= 0.25 for a in ape) / len(p), 1),
            "within_50pct": round(100.0 * sum(a <= 0.5 for a in ape) / len(p), 1),
            "median_ratio_est_over_reg": round(math.exp(st.median(lr)), 2),
            "est_zero": sum(e < 1 for e, _ in p),
            "sum_est": round(sum(e for e, _ in p)), "sum_reg": round(sum(t for _, t in p)),
            "aggregate_ratio": round(sum(e for e, _ in p) / sum(t for _, t in p), 2)}


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "businessbay"
    var = {k: rows(os.path.join(OUT, "flooruse_%s%s.csv" % (slug, t))) for k, t in VARIANTS
           if os.path.exists(os.path.join(OUT, "flooruse_%s%s.csv" % (slug, t)))}
    um = json.load(open(os.path.join(BOARD, "unitmix_%s.json" % slug), encoding="utf-8"))["buildings_by_id"]
    stack = json.load(open(os.path.join(BOARD, "stack_%s.json" % slug), encoding="utf-8"))["buildings_by_id"]
    facts = json.load(open(os.path.join(BOARD, "bldgfacts_%s.json" % slug), encoding="utf-8"))["buildings_by_id"]
    rule = var["rule"]

    est = lambda row, c: f(row["est_%s" % c]) or 0.0
    tot = lambda row: sum(est(row, c) for c in ("homes", "hotel", "office", "retail"))
    cmp_rows = []
    for k, u in um.items():
        i = int(k)
        reg_total = f(u.get("total_units"))          # two rows carry it as a string ("381")
        if not reg_total or i not in rule:
            continue
        ac = types_of(u)
        r, fc, s = rule[i], facts.get(k, {}), stack.get(k) or {}
        dm = {}
        if s.get("basis") == "dm_floors":
            for fl in s["floors"]:
                dm[fl["u"]] = dm.get(fl["u"], 0) + (fl.get("k") or 0)
        dom = max(("residential", "office", "retail"), key=lambda c: ac[c]) if any(ac[c] for c in ("residential", "office", "retail")) else None
        row = {"i": i, "name": r["name"] or u.get("name"), "stack_source": r["stack_source"], "stack_used": r["stack_used"],
               "plate_source": r.get("plate_source"), "plate_suspect": bool(fc.get("plate_suspect")),
               "stack_fits_massing": s.get("fits"), "height_m": f(r["height_m"]), "footprint_m2": f(r["footprint_m2"]),
               "typ_plate_in_m2": f(r.get("typ_plate_in_m2")), "floors_rule": int(r["floors"]),
               "reg_total": reg_total, "reg_homes": ac["residential"], "reg_office": ac["office"], "reg_retail": ac["retail"],
               "reg_unknown_type": ac["unknown"], "reg_dominant": dom,
               "dm_homes_k": dm.get("homes") if dm else None, "dm_office_k": dm.get("office") if dm else None,
               "dm_hotel_k": dm.get("hotel") if dm else None}
        for vk, vr in var.items():
            v = vr[i]
            row.update({"%s_homes" % vk: est(v, "homes"), "%s_office" % vk: est(v, "office"), "%s_hotel" % vk: est(v, "hotel"),
                        "%s_total" % vk: round(tot(v), 1), "%s_stack" % vk: v["stack_used"]})
        row["incumbent_units_indicative"] = fc.get("units_indicative")
        row["label"] = "estimates vs register - research use only"
        cmp_rows.append(row)

    def seg(pred, key_est, key_reg):
        return metrics([(c[key_est], c[key_reg]) for c in cmp_rows if pred(c) and key_est in c])

    ALL = lambda c: True
    DMF = lambda c: c["stack_source"] == "dm_floors"
    NOREG = lambda c: c["stack_source"] != "dm_floors"
    OK = lambda c: not c["plate_suspect"]
    SUS = lambda c: c["plate_suspect"]
    INC = lambda c: c["incumbent_units_indicative"] is not None
    out = {"slug": slug, "use": "research only - every unit figure here is an ESTIMATE scored against a register",
           "buildings_with_registered_units": len(cmp_rows),
           "truth": "DLD units register type rows (homes = studio / N bedroom / penthouse / duplex / townhouse)",
           "homes_vs_DLD": {}, "total_vs_DLD": {}, "office_vs_DLD": {}}
    segs = [("all", ALL), ("dm_floors_stack", DMF), ("default_stack", NOREG), ("plate_ok", OK), ("plate_suspect", SUS),
            ("same_set_as_incumbent", INC)]
    for vk in var:
        out["homes_vs_DLD"][vk] = {sn: seg(sp, "%s_homes" % vk, "reg_homes") for sn, sp in segs}
        out["total_vs_DLD"][vk] = {sn: seg(sp, "%s_total" % vk, "reg_total") for sn, sp in segs}
        out["office_vs_DLD"][vk] = {sn: seg(sp, "%s_office" % vk, "reg_office") for sn, sp in (("all", ALL), ("dm_floors_stack", DMF))}
    out["homes_vs_DLD"]["incumbent"] = {"same_set_as_incumbent": seg(INC, "incumbent_units_indicative", "reg_homes")}
    out["total_vs_DLD"]["incumbent"] = {"same_set_as_incumbent": seg(INC, "incumbent_units_indicative", "reg_total")}
    out["homes_vs_DM_k"] = {vk: seg(DMF, "%s_homes" % vk, "dm_homes_k") for vk in ("rule", "noplate") if vk in var}
    out["hotel_keys_vs_DM_k"] = {vk: seg(DMF, "%s_hotel" % vk, "dm_hotel_k") for vk in ("rule", "noplate") if vk in var}
    out["register_noise_DM_k_vs_DLD_homes"] = seg(lambda c: DMF(c) and c["dm_homes_k"], "dm_homes_k", "reg_homes")
    z = [c for c in cmp_rows if not c["reg_homes"] and not c["reg_unknown_type"]]
    out["homes_where_DLD_has_none"] = {"buildings": len(z)}
    for vk in var:
        out["homes_where_DLD_has_none"]["%s_est_homes_gt_10" % vk] = sum(c["%s_homes" % vk] > 10 for c in z)
    for vk in ("noregister", "noregister_nonames"):
        if vk in var:
            conf = {}
            for c in cmp_rows:
                key = "%s -> %s" % (c["%s_stack" % vk], c["reg_dominant"])
                conf[key] = conf.get(key, 0) + 1
            out["default_class_vs_DLD_dominant_%s" % vk] = dict(sorted(conf.items(), key=lambda kv: -kv[1]))
    json.dump(out, open(os.path.join(OUT, "flooruse_eval_%s.json" % slug), "w", encoding="utf-8"), indent=1)
    with open(os.path.join(OUT, "flooruse_compare_%s.csv" % slug), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cmp_rows[0].keys()))
        w.writeheader(); w.writerows(cmp_rows)

    def line(name, m):
        if not m.get("n"):
            return
        print("  %-38s n=%-4d MdAPE=%5.1f%%  w25=%4.1f%%  w50=%4.1f%%  med est/reg=%4.2f  sum est/reg=%4.2f  zero=%d"
              % (name, m["n"], m["median_abs_pct_err"], m["within_25pct"], m["within_50pct"],
                 m["median_ratio_est_over_reg"], m["aggregate_ratio"], m["est_zero"]))
    for block in ("homes_vs_DLD", "total_vs_DLD", "office_vs_DLD"):
        print(block)
        for vk, d in out[block].items():
            for sn, m in d.items():
                line("%s / %s" % (vk, sn), m)
    print("homes_vs_DM_k"); [line(k, m) for k, m in out["homes_vs_DM_k"].items()]
    print("hotel_keys_vs_DM_k"); [line(k, m) for k, m in out["hotel_keys_vs_DM_k"].items()]
    line("register noise DM k vs DLD", out["register_noise_DM_k_vs_DLD_homes"])
    for k in out:
        if k.startswith(("homes_where", "default_class")):
            print(k, out[k])
    return 0


if __name__ == "__main__":
    sys.exit(main())
