"""Developer comparison cube for the Azimuth board (/compare, v73.3).
For every whitelisted developer: DLD 2026 transactions on ITS projects (the kept list from developer_dna.json - portfolio-verified where
we hold a developer-site register), cut by bedroom (all / studio / 1 / 2 / 3 / 4+) x price band (all / <1M / 1-2M / 2-4M / 4M+):
count, median price, P10-P90 price, median AED/m2, off-plan share, top areas; plus rents by bedroom (median annual, yield proxy),
registered projects, handover pipeline, MEED, portfolio size and what WE hold. Pushed to KV `dev_compare`.
Run after build_developer_dna.py.
"""
import datetime as dt, json, os, statistics, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
from build_avail_index import env_token, push  # noqa: E402

SEG = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_segments.json"), encoding="utf-8"))
DNA = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))
BOARD = json.load(open(os.path.join(ROOT, "data", "board", "board_devs.json"), encoding="utf-8"))
KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
       "ZAYA": "zaya", "Palma": "palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman", "Prestige One": "prestigeone", "Emaar": "emaar", "Sobha": "sobha"}
BEDS = {"all": None, "studio": ["Studio"], "1": ["1 B/R"], "2": ["2 B/R"], "3": ["3 B/R"], "4": ["4 B/R", "5 B/R", "6 B/R", "PENTHOUSE"]}
BANDS = {"all": (0, 1e12), "lt1": (0, 1e6), "1to2": (1e6, 2e6), "2to4": (2e6, 4e6), "gt4": (4e6, 1e12)}
BAND_LABEL = {"all": "any price", "lt1": "under AED 1 M", "1to2": "AED 1-2 M", "2to4": "AED 2-4 M", "gt4": "AED 4 M+"}
BED_LABEL = {"all": "all homes", "studio": "studio", "1": "1 bed", "2": "2 bed", "3": "3 bed", "4": "4 bed +"}
con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
from build_developer_dna import spine_links  # noqa: E402  (side-effect free; opens the lake read-only only when called)
SPINE = spine_links()                        # rent (project, area) -> registered project id; empty when the lake is unavailable (names only)
print(SPINE["note"])

def sql_list(names):
    return ",".join("'" + n.replace("'", "''") + "'" for n in names)

def cell(rows):
    """rows: (value, aed_per_sqm, offplan, area)"""
    if not rows: return None
    vals = sorted(r[0] for r in rows if r[0]); sqm = [r[1] for r in rows if r[1] and 500 < r[1] < 200000]
    def pct(p): return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else None
    areas = {}
    for r in rows:
        if r[3]: areas[r[3]] = areas.get(r[3], 0) + 1
    return {"n": len(rows), "median": round(statistics.median(vals)) if vals else None, "p10": round(pct(.10)) if vals else None, "p90": round(pct(.90)) if vals else None,
            "sqm": round(statistics.median(sqm)) if sqm else None, "offplan": round(sum(1 for r in rows if r[2]) / len(rows), 2),
            "areas": [a for a, _ in sorted(areas.items(), key=lambda x: -x[1])[:3]]}


# ---- tier 2: lifestyle / vicinity tags. Area-based first (AREA_EN is always present); landmark/mall fields are null on ~half the rows.
LIFE = {
    "beach":    ("beach & waterfront",   ["palm deira", "palm jumeirah", "almelaheyah", "maritime city", "la mer", "marsa dubai", "dubai marina", "dubai harbour", "bluewaters", "jumeirah second", "jumeirah first", "jumeirah third", "sufouh", "umm suqeim", "creek harbour", "jaddaf waterfront", "mina rashid", "island"]),
    "downtown": ("downtown & canal",     ["business bay", "burj khalifa", "zaabeel", "al wasl", "city walk", "water canal", "design district", "al satwa", "trade centre", "difc"]),
    "mbr":      ("MBR City & lagoons",   ["horizon", "nad al shiba", "sobha heartland", "hadaeq sheikh mohammed", "al merkadh", "meydan", "district one", "wadi al safa 3"]),
    "suburb":   ("family communities",   ["arabian ranches", "cherrywoods", "town square", "wadi al safa 7", "al yelayiss", "al yufrah", "falcon city", "city of arabia", "land residence complex", "liwan", "dubai hills", "motor city", "jumeirah village", "me'aisem", "al furjan", "production city", "sufouh gardens", "damac hills", "mudon", "tilal al ghaf", "al barsha south", "sports city"]),
    "south":    ("Dubai South & Expo",   ["madinat al mataar", "dubai south", "saih shuaib", "jabal ali", "down town jabal ali", "expo"]),
}
MALLS = {"m_dubaimall": ("near Dubai Mall", "Dubai Mall"), "m_moe": ("near Mall of the Emirates", "Mall of the Emirates"), "m_marina": ("near Marina Mall", "Marina Mall"),
         "m_ibn": ("near Ibn Battuta Mall", "Ibn-e-Battuta Mall"), "m_mirdif": ("near City Centre Mirdif", "City Centre Mirdif")}
LIFE_LABEL = {k: v[0] for k, v in LIFE.items()}; LIFE_LABEL.update({k: v[0] for k, v in MALLS.items()}); LIFE_LABEL["dxb"] = "near Dubai International Airport"

def life_tags(area, landmark, mall):
    a = (area or "").lower(); tags = set()
    for k, (_, pats) in LIFE.items():
        if any(x in a for x in pats): tags.add(k)
    for k, (_, name) in MALLS.items():
        if mall == name: tags.add(k)
    if landmark == "Dubai International Airport": tags.add("dxb")
    return tags

AMEN_KW = [("pool", "pool"), ("gym", "gym"), ("kids", "kids' zone"), ("clubhouse", "clubhouse"), ("bbq", "BBQ"), ("cinema", "cinema"), ("spa", "spa"), ("sauna", "sauna"),
           ("yoga", "yoga"), ("ev charg", "EV charging"), ("padel", "padel"), ("co-working", "co-working"), ("coworking", "co-working"), ("beach", "beach access"), ("concierge", "concierge"), ("lagoon", "lagoon")]

def amenities_from_portfolio(key):
    f = os.path.join(ROOT, "data", "dev_meta", key + "_portfolio.json")
    if not os.path.exists(f): return None
    d = json.load(open(f, encoding="utf-8")); counts = {}
    for pr in d.get("properties", []):
        seen = set()
        if pr.get("faq"):                                   # Imtiaz-style FAQ block: the amenities answer only
            t = " ".join(x["a"] for x in pr.get("faq", []) if "amenit" in x["q"].lower() or "facilit" in x["q"].lower()).lower()
            for kw, label in AMEN_KW:
                if kw in t and label not in seen: counts[label] = counts.get(label, 0) + 1; seen.add(label)
        for label in pr.get("amenities") or []:             # generic registers: keyword hits on the de-noised page text (dev_portfolio.py)
            if label not in seen: counts[label] = counts.get(label, 0) + 1; seen.add(label)
    n = len(d.get("properties", []))
    return {"source": d.get("source"), "projects": n, "items": [{"label": l, "share": round(c / n, 2)} for l, c in sorted(counts.items(), key=lambda x: -x[1])]} if n else None

out = {"updated": dt.date.today().isoformat(), "beds": BED_LABEL, "bands": BAND_LABEL, "life": LIFE_LABEL, "developers": {},
       "note": "DLD Open Data transactions Jan-Aug 2026 on each developer's own projects (the DNA's list: a sale's register row filed under one of "
               "the developer's DLD entities, or a confirmed name match). Residential sales only; AED/m2 on procedure area; rents = Ejari contracts "
               "on the same projects, by name or by registered project. Not investment advice."}
for seg in SEG["segments"]:
    for name in seg["developers"]:
        k = KEY[name]; d = DNA["developers"].get(name, {}); bd = next((x for x in BOARD["developers"] if x["key"] == k), {})
        projects = [t["project"] for t in d.get("tx_2026", {}).get("projects", [])]
        rec = {"name": name, "key": k, "tier": seg["rank"], "segment_label": seg["label"], "icon": bd.get("icon"), "logo": bd.get("logo"),
               "projects_trading": len(projects), "registered_2026": len(d.get("dld_projects_2026", [])),
               "portfolio": (d.get("portfolio") or {}).get("count"), "meed_active": len((d.get("meed") or {}).get("active", [])), "meed_projects": (d.get("meed") or {}).get("projects", 0),
               "ours_cards": len(bd.get("ours", [])), "sheet_units": sum((p.get("sheet") or {}).get("units", 0) for p in bd.get("properties", [])),
               "handovers": sorted({p.get("handover") for p in bd.get("properties", []) if p.get("handover")})[:6], "cells": {}, "rents": {}}
        if projects:
            rows = con.execute("select try_cast(TRANS_VALUE as double), try_cast(TRANS_VALUE as double)/nullif(try_cast(PROCEDURE_AREA as double),0), "
                               "IS_OFFPLAN_EN='Off-Plan', AREA_EN, ROOMS_EN, NEAREST_LANDMARK_EN, NEAREST_MALL_EN from transactions where PROJECT_EN in (%s) and (USAGE_EN is null or USAGE_EN not like '%%Commercial%%') "
                               "and ROOMS_EN not in ('Office','Shop','NA') and try_cast(TRANS_VALUE as double) > 100000" % sql_list(projects)).fetchall()
            rows = [r + (life_tags(r[3], r[5], r[6]),) for r in rows]          # r[7] = lifestyle tag set
            rec["life"] = {}
            for bk, bl in BEDS.items():
                for gk, (lo, hi) in BANDS.items():
                    sub = [r for r in rows if (bl is None or r[4] in bl) and r[0] and lo <= r[0] < hi]
                    c = cell(sub)
                    if c: rec["cells"][bk + "|" + gk] = c
                    for lk in LIFE_LABEL:                                       # tier 2: same cut, one lifestyle / vicinity tag
                        cl = cell([r for r in sub if lk in r[7]])
                        if cl: rec["life"][bk + "|" + gk + "|" + lk] = cl
            rec["amenities"] = amenities_from_portfolio(k)
            # rents: Ejari names differ in case/spacing from the sales register ("Pearl House II By Imtiaz " vs "PEARL HOUSE II BY IMTIAZ") and ROOMS is mostly null.
            # 15 Sep 2026 (digital thread P1.3): plus the rents whose registered project (lk_rent_project, exact name in the rent's own area)
            # is one of the developer's counted projects (their project_ids in the DNA) - the same rent population the DNA counts
            ids = {c for t in d.get("tx_2026", {}).get("projects", []) for c in t.get("project_ids", [])}
            pairs = ["%s|%s" % pa for pa, cid in SPINE["rent_ids"].items() if cid in ids and pa[0] and pa[1]]
            rn = con.execute("select ROOMS, median(try_cast(ANNUAL_AMOUNT as double)), count(*) from rents where (lower(trim(PROJECT_EN)) in (%s) or PROJECT_EN || '|' || AREA_EN in (%s)) "
                             "and try_cast(ANNUAL_AMOUNT as double) > 10000 group by 1" % (sql_list([x.lower().strip() for x in projects]), sql_list(pairs) or "''")).fetchall()
            rmap = {"Studio": "studio", "0": "studio", "1": "1", "2": "2", "3": "3", "4": "4", "5": "4", "6": "4"}
            allr = []
            for r in rn:
                bk = rmap.get(r[0] or "")
                if bk: rec["rents"][bk] = {"median": round(r[1]), "n": r[2]}
                allr += [r[1]] * r[2]                      # rows with no bedroom count still feed the all-homes median
            if allr: rec["rents"]["all"] = {"median": round(statistics.median(allr)), "n": len(allr)}
        out["developers"][k] = rec
        a = rec["cells"].get("all|all") or {}
        print(f"{name:<13} tx {a.get('n', 0):>5}  median AED {a.get('median') or 0:>10,}  AED/m2 {a.get('sqm') or 0:>7,}  offplan {a.get('offplan')}  rents {rec['rents'].get('all', {}).get('n', 0)}")
json.dump(out, open(os.path.join(ROOT, "data", "board", "dev_compare.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
r = push("dev_compare", out, env_token("INGEST_TOKEN")); print("dev_compare ->", r.get("ok"))
