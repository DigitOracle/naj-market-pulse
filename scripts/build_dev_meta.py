"""Compose the per-district sidecar (meta_<slug>) from EVERY source we hold.

The tap-card should never be hand-written twice: this script assembles it from
 - pulse.json areaIntel        -> sales, AED/sqft, yields, momentum, by-room medians
 - pulse.json projects/supply  -> registered pipeline for the district
 - the worker's amenity cache  -> nearest metro/school/mall/hospital (English, cached)
 - DuckDB (naj.duckdb)         -> latest registered sales per featured project
 - dev_meta/curated/<slug>.json-> hand-curated featured buildings (EYWA pattern:
                                  first-party brochure facts, placement notes)
Demographics joins automatically once DSC data lands (same areaIntel merge).

Usage: python scripts/build_dev_meta.py --area "business bay"
Writes: data/dev_meta/meta_<slug>.json  (push via the ingest channel)
"""
import json, os, re, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
DM = os.path.join(HERE, "..", "data", "dev_meta")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"

slug = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
fmt = lambda n: f"{n:,.0f}" if isinstance(n, (int, float)) else str(n)


def area_intel(d, name):
    for a in (d.get("areaIntel", {}).get("areas") or []):
        if slug(a.get("area")) == slug(name):
            return a
    return None


def amenities(sl):
    try:
        key = os.environ.get("READ_KEY", "")
        req = urllib.request.Request(f"{WORKER}/amenities?area={urllib.parse.quote(sl)}&key={key}",
                                     headers={"User-Agent": "najma-market-pulse/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
            return j.get("amen") if j.get("ok") else None
    except Exception:
        return None


def latest_sales(project_names):
    """Latest registered transactions per featured project, straight from DuckDB."""
    try:
        import duckdb
    except ImportError:
        return {}
    db = os.path.join(HERE, "..", "naj.duckdb")
    if not os.path.exists(db):
        return {}
    out = {}
    con = duckdb.connect(db, read_only=True)
    for p in project_names:
        try:
            row = con.execute(
                "SELECT INSTANCE_DATE, PROCEDURE_EN, ROOMS_EN, TRY_CAST(ACTUAL_AREA AS DOUBLE), TRY_CAST(TRANS_VALUE AS DOUBLE) "
                "FROM transactions WHERE lower(PROJECT_EN) = lower(?) "
                "ORDER BY INSTANCE_DATE DESC LIMIT 1", [p]).fetchone()
            if row:
                d, proc, rooms, area, worth = row
                psm = (worth / area) if (worth and area) else None
                out[p] = f"{str(d)[:10]} · {rooms or proc} · {fmt(area)} m² · AED {fmt(worth)}" + (
                    f" ≈ {fmt(psm)}/m²" if psm else "")
        except Exception:
            pass
    con.close()
    return out


def track_record(project_names):
    """Register-entity project counts — only meaningful when the entity holds >1 project."""
    try:
        import duckdb
    except ImportError:
        return {}
    db = os.path.join(HERE, "..", "naj.duckdb")
    if not os.path.exists(db) or not project_names:
        return {}
    out = {}
    con = duckdb.connect(db, read_only=True)
    for rn in project_names:
        try:
            row = con.execute(
                "SELECT p2.DEVELOPER_EN, COUNT(*), "
                "SUM(CASE WHEN TRY_CAST(p2.PERCENT_COMPLETED AS DOUBLE) > 0 THEN 1 ELSE 0 END) "
                "FROM projects p JOIN projects p2 ON p.DEVELOPER_EN = p2.DEVELOPER_EN "
                "WHERE lower(p.PROJECT_EN) = lower(?) GROUP BY 1", [rn]).fetchone()
            if row and row[1] > 1:
                out[rn.lower()] = f"{row[0].title()[:38]} · {row[1]} registered · {row[2]} in delivery"
        except Exception:
            pass
    con.close()
    return out


def main():
    if "--area" not in sys.argv:
        sys.exit('usage: python scripts/build_dev_meta.py --area "business bay"')
    name = sys.argv[sys.argv.index("--area") + 1]
    sl = slug(name)
    d = json.load(open(os.path.join(PUB, "pulse.json"), encoding="utf-8"))
    a = area_intel(d, name)

    meta = {"district": sl, "updated": d.get("transactions", {}).get("periodTo", ""), "buildings": {}}

    # district-level card (shown when tapping the merged existing stock)
    if a:
        facts = []
        if a.get("sales"): facts.append(["Registered sales (period)", fmt(a["sales"])])
        if a.get("medianAedSqft"): facts.append(["Median AED/sqft (settled)", fmt(a["medianAedSqft"])])
        if a.get("netYieldPct") is not None: facts.append(["Net yield", f"{a['netYieldPct']}% (~estimate)"])
        if a.get("offPlanPct") is not None: facts.append(["Off-plan share", f"{a['offPlanPct']}%"])
        sup = (d.get("projects", {}).get("supplyByArea", {}) or {}).get(a.get("area"), {})
        if sup.get("units"): facts.append(["Registered supply", fmt(sup["units"]) + " units"])
        # demographics joins here automatically when DSC lands (population/households in areaIntel)
        if a.get("population"): facts.append(["Population", fmt(a["population"])])
        am = amenities(sl)
        if am:
            for x in am[:4]:
                facts.append([x["label"], x["value"]])
        meta["district_card"] = {
            "title": a.get("area", name).title(),
            "sub": f"the register, {d.get('transactions',{}).get('periodFrom','')} → {d.get('transactions',{}).get('periodTo','')}",
            "facts": facts,
            "links": [["Area deep-dive", f"/area/{a.get('area','').lower()}"],
                      ["Postcard", "/charts"], ["Map", "/map"]],
            "sources": ["Dubai Land Department (DLD) Open Data"]}

    # curated featured buildings (EYWA pattern) + live register enrichment
    cur = os.path.join(DM, "curated", f"{sl}.json")
    if os.path.exists(cur):
        c = json.load(open(cur, encoding="utf-8"))
        latest = latest_sales([b.get("register_name") for b in c.get("buildings", {}).values()
                               if b.get("register_name")])
        _track = track_record([b.get("register_name") for b in c.get("buildings", {}).values()
                               if b.get("register_name")])
        for k, b in c.get("buildings", {}).items():
            rn = b.get("register_name")
            if rn and rn in latest:
                b.setdefault("facts", []).append(["Latest registered transaction", latest[rn]])
                b.setdefault("sources", []).append("DLD Open Data transactions (live pull)")
            # developer track record: ONLY when the register entity has >1 project
            # (Dubai SPV pattern means 1-project entities say nothing about the brand)
            if rn and rn.lower() in _track:
                b.setdefault("facts", []).append(["Developer (register entity)", _track[rn.lower()]])
            if b.get("brand_note"):
                b.setdefault("facts", []).append(["Developer brand", b["brand_note"]])
            meta["buildings"][k] = b

    os.makedirs(DM, exist_ok=True)
    out = os.path.join(DM, f"meta_{sl}.json")
    json.dump(meta, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"-> {out}  ({len(meta['buildings'])} featured, district_card={'yes' if 'district_card' in meta else 'no'})")


if __name__ == "__main__":
    main()
