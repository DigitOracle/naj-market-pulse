"""Per-project fact sheet for the skyline viewer's information panel (developer -> project drill, v74.5).
One record per (developer, project): developer-site facts (area, handover, storeys, units, mix, payment plans), the availability
sheet where we hold one, and DLD Open Data 2026: registered sales, median price, P10-P90, median AED/m2, off-plan share, bedroom mix,
nearest metro / mall / landmark (the mode across that project's transactions), last registration. Keyed by developer + normalised
name, with every alias (register name, DLD PROJECT_EN, map name) listed so the viewer can join from an anchor's dev_project.
Output: data/board/projfacts.json -> KV `projfacts` (served at /img/projfacts).
"""
import collections, json, os, statistics, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
from build_avail_index import env_token, push  # noqa: E402
from build_developer_dna import norm_name  # noqa: E402

SEG = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_segments.json"), encoding="utf-8"))
BOARD = json.load(open(os.path.join(ROOT, "data", "board", "board_devs.json"), encoding="utf-8"))
DNA = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))["developers"]
KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
       "ZAYA": "zaya", "Palma": "palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman", "Emaar": "emaar", "Sobha": "sobha"}
con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
JUNK_AREA = ("luxury", "prestige", "real estate", "apartments", "for sale", "developer", "properties")

def sk(dev, name):
    return dev + "|" + norm_name(name, SEG["aliases"].get(next((n for n, k in KEY.items() if k == dev), ""), [dev])).replace(" ", "")

def dld_facts(names):
    rows = con.execute("select try_cast(TRANS_VALUE as double), try_cast(TRANS_VALUE as double)/nullif(try_cast(PROCEDURE_AREA as double),0), IS_OFFPLAN_EN, ROOMS_EN, "
                       "NEAREST_METRO_EN, NEAREST_MALL_EN, NEAREST_LANDMARK_EN, AREA_EN, INSTANCE_DATE from transactions where lower(trim(PROJECT_EN)) in (%s) and try_cast(TRANS_VALUE as double) > 100000"
                       % ",".join("'" + n.lower().strip().replace("'", "''") + "'" for n in names)).fetchall()
    if not rows: return None
    vals = sorted(r[0] for r in rows if r[0]); sqm = [r[1] for r in rows if r[1] and 500 < r[1] < 200000]
    mode = lambda i: (collections.Counter(r[i] for r in rows if r[i]).most_common(1) or [(None, 0)])[0][0]
    rooms = collections.Counter(r[3] for r in rows if r[3] and r[3] not in ("NA",))
    return {"sales_2026": len(rows), "median_aed": round(statistics.median(vals)) if vals else None, "p10_aed": round(vals[int(len(vals) * .1)]) if vals else None,
            "p90_aed": round(vals[min(len(vals) - 1, int(len(vals) * .9))]) if vals else None, "median_aed_per_sqm": round(statistics.median(sqm)) if sqm else None,
            "offplan_share": round(sum(1 for r in rows if r[2] == "Off-Plan") / len(rows), 2), "rooms": dict(rooms.most_common(6)),
            "nearest_metro": mode(4), "nearest_mall": mode(5), "nearest_landmark": mode(6), "dld_area": mode(7), "last_registration": max(str(r[8])[:10] for r in rows)}

out = {}; n_dld = 0
for dv in BOARD["developers"]:
    dev = dv["key"]; dname = dv["name"]; d = DNA.get(dname, {})
    tx_by_norm = {}
    for t in d.get("tx_2026", {}).get("projects", []): tx_by_norm.setdefault(sk(dev, t["project"]), []).append(t["project"])
    for p in dv["properties"]:
        k = sk(dev, p["name"]); rec = out.get(k) or {"dev": dev, "developer": dname, "name": p["name"], "aliases": set(), "kind": p["kind"]}
        rec["aliases"].add(p["name"])
        area = p.get("area") or ""
        if area and not any(j in area.lower() for j in JUNK_AREA): rec.setdefault("area", area)
        for f in ("handover", "structure", "storeys", "units", "plans", "mix", "location", "url", "slug", "status"):
            if p.get(f) not in (None, "", []): rec.setdefault(f, p[f])
        if p.get("sheet"): rec["sheet"] = p["sheet"]
        if p.get("cards"): rec["cards"] = p["cards"]; rec["meta"] = p.get("meta")
        if p.get("tx") and "tx_hint" not in rec: rec["tx_hint"] = p["tx"]
        out[k] = rec
    for k, names in tx_by_norm.items():
        rec = out.get(k) or {"dev": dev, "developer": dname, "name": names[0].title(), "aliases": set(), "kind": "trading"}
        rec["aliases"].update(names); out[k] = rec
for k, rec in out.items():
    names = set(rec["aliases"]) | {rec["name"]}
    f = dld_facts(names)
    if f: rec["dld"] = f; n_dld += 1
    if not rec.get("area") and f and f.get("dld_area"): rec["area"] = f["dld_area"].title()
    rec["aliases"] = sorted(names)
json.dump({"updated": BOARD.get("updated"), "count": len(out), "projects": out,
           "note": "developer-site facts + availability sheet + DLD Open Data 2026 per project; nearest metro/mall/landmark are the most common values on that project's registered sales"},
          open(os.path.join(ROOT, "data", "board", "projfacts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("projects:", len(out), "| with DLD facts:", n_dld)
r = push("projfacts", json.load(open(os.path.join(ROOT, "data", "board", "projfacts.json"), encoding="utf-8")), env_token("INGEST_TOKEN")); print("projfacts ->", r.get("ok"))
