"""Per-building facts for the twin's panel, from the CityEngine reports our own massing already produces.
For each district: read data/ce/<slug>/report_v3.csv (one row per building: footprint, height, storeys, gross floor area, class),
join it to the anchors (name, developer, project) and, where the project is one of the eleven developers' registered schemes,
to the register facts (projfacts) so a broker can read floor area and an indicative unit count beside the price.
Indicative units = GFA x efficiency 0.78 / a typical apartment of 105 m2 - stated as indicative, never as the developer's count;
where the register or the developer's own site gives a real unit count, that wins and the source says so.
Output: data/board/bldgfacts_<slug>.json -> KV `bldgfacts_<slug>` (served at /img/bldgfacts_<slug>).
Usage: python scripts/build_buildingfacts.py [slug ...]
"""
import csv, glob, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
from build_developer_dna import norm_name  # noqa: E402

EFF, UNIT_M2 = 0.78, 105.0        # net-to-gross and a typical Dubai apartment, both stated on the card
PF = os.path.join(ROOT, "data", "board", "projfacts.json")
PROJ = json.load(open(PF, encoding="utf-8"))["projects"] if os.path.exists(PF) else {}

def run(slug):
    rep = os.path.join(ROOT, "data", "ce", slug, "report_v3.csv")
    anc = os.path.join(ROOT, "data", "names", f"anchors_{slug}.json")
    if not (os.path.exists(rep) and os.path.exists(anc)): return None
    A = json.load(open(anc, encoding="utf-8"))
    by_i = {a["i"]: a for a in A["anchors"]}
    out, tot_gfa, tot_units = {}, 0.0, 0
    for r in csv.DictReader(open(rep, encoding="utf-8")):
        sh = r.get("shape") or ""
        if not sh.startswith("b"): continue
        try: i = int(sh[1:].split("_")[0])
        except Exception: continue
        gfa = float(r.get("gfa_m2") or 0); st = int(float(r.get("storeys") or 0)); fp = float(r.get("footprint_m2") or 0)
        h = float(r.get("height_m") or 0)
        if gfa <= 0: continue
        a = by_i.get(i)
        rec = {"i": i, "footprint_m2": round(fp), "height_m": round(h, 1), "storeys": st, "gfa_m2": round(gfa),
               "gfa_sqft": round(gfa * 10.7639), "class": r.get("class"),
               "units_indicative": max(1, round(gfa * EFF / UNIT_M2)) if st > 1 else None,
               "basis": f"gross floor area from our own model; indicative homes = GFA x {EFF:.2f} / {int(UNIT_M2)} m2"}
        if a:
            rec["name"] = a.get("name"); rec["dev"] = a.get("dev"); rec["project"] = a.get("dev_project")
            # a real unit count always beats the indicative one
            if a.get("dev") and a.get("dev_project"):
                key = norm_name(a["dev_project"], [a["dev"]]).replace(" ", "")
                p = next((v for k, v in PROJ.items() if v.get("dev") == a["dev"] and norm_name(v.get("name", ""), [a["dev"]]).replace(" ", "") == key), None)
                if p and p.get("units"):
                    try: rec["units_registered"] = int(str(p["units"]).replace(",", "")); rec["units_source"] = "developer site / DLD register"
                    except Exception: pass
        tot_gfa += gfa; tot_units += rec["units_indicative"] or 0
        out[str(i)] = rec
    doc = {"district": slug, "buildings": len(out), "gfa_m2_total": round(tot_gfa), "gfa_sqft_total": round(tot_gfa * 10.7639),
           "units_indicative_total": tot_units, "efficiency": EFF, "unit_m2": UNIT_M2,
           "note": "Floor area is measured from our own massing (storey slabs), not from a developer document. Unit counts are indicative unless marked registered.",
           "buildings_by_id": out}
    f = os.path.join(ROOT, "data", "board", f"bldgfacts_{slug}.json")
    json.dump(doc, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    named = sum(1 for v in out.values() if v.get("name")); reg = sum(1 for v in out.values() if v.get("units_registered"))
    print(f"{slug:<26} buildings {len(out):>5}  named {named:>4}  GFA {round(tot_gfa/1e6,2):>6} M m2  indicative homes {tot_units:>6}  registered counts {reg}")
    return doc

if __name__ == "__main__":
    slugs = sys.argv[1:] or [os.path.basename(os.path.dirname(p)) for p in sorted(glob.glob(os.path.join(ROOT, "data", "ce", "*", "report_v3.csv")))]
    tok = env_token("INGEST_TOKEN")
    for s in slugs:
        d = run(s)
        if d: print("   ", "bldgfacts_" + s, "->", push("bldgfacts_" + s, d, tok).get("ok"))
