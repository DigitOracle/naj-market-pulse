"""supercharge_pull.py -- Tesla Supercharger sites for the UAE, from supercharge.info.

This source adds almost no new LOCATIONS -- its sites sit on top of points OCM and OSM already give
us -- but it carries the fields those two do not: `stallCount`, `powerKilowatt`, `status`
(OPEN / CONSTRUCTION / PERMIT / PLAN) and `dateOpened`. That turns a Tesla dot with an unknown
connector count into a charge point with a real stall count and a real kW rating.

So it is used as an ENRICHMENT source, not a points source: build_ev_union.py matches it to existing
Tesla points by distance and fills the gaps. Sites with no match are available but are not added as
new points by default -- see --as-points.

LICENCE, AND WHY IT IS FENCED: supercharge.info is a community-maintained project with NO explicit
open licence published. That is weaker than OCM (CC-BY-SA) or OSM (ODbL). The `ext_dataset` row
records that plainly, and the payload carries `public_display_cleared: false`. Treat it as safe for
private analysis and hold the public-map question until someone has read their terms.
Only OPEN sites are loaded by default; PLAN and PERMIT sites are not built yet and would put
chargers on a map where none exist.

    python scripts/supercharge_pull.py pull      # -> data/raw_downloads/supercharge/
    python scripts/supercharge_pull.py load      # -> duckdb table + clean view
"""
import argparse, datetime as dt, io, json, os, sys, urllib.request

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "supercharge")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
URL = "https://supercharge.info/service/supercharge/allSites"
TABLE = "sci__supercharger_sites"
CLEAN = "o_sci__supercharger_sites"
COUNTRIES = {"United Arab Emirates", "UAE"}


def log(*a): print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def pull():
    os.makedirs(OUT, exist_ok=True)
    req = urllib.request.Request(URL, headers={
        "User-Agent": "DigitAlchemy-Azimuth/1.0 (contact@digitalabbot.io)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as h:
        allsites = json.loads(h.read())
    log(f"{len(allsites)} sites worldwide")

    rows = []
    for s in allsites:
        addr = s.get("address") or {}
        if (addr.get("country") or "") not in COUNTRIES: continue
        gps = s.get("gps") or {}
        lat, lon = gps.get("latitude"), gps.get("longitude")
        if lat is None or lon is None: continue
        rows.append({
            "sci_id": s.get("id"),
            "location_name": s.get("name"),
            "location_address": ", ".join(x for x in [addr.get("street"), addr.get("city"),
                                                      addr.get("state")] if x) or None,
            "city": addr.get("city"), "state": addr.get("state"),
            "latitude": float(lat), "longitude": float(lon),
            "stall_count": s.get("stallCount"),
            "power_kw": s.get("powerKilowatt"),
            "status": s.get("status"),
            "date_opened": s.get("dateOpened"),
            "source_url": "https://supercharge.info/map?site=" + str(s.get("id")),
        })

    from collections import Counter
    st = Counter(r["status"] for r in rows)
    payload = {"source": "supercharge.info /service/supercharge/allSites",
               "licence": "community project, NO explicit open licence published",
               "public_display_cleared": False,
               "provenance": "community-maintained; NOT a government register and NOT Tesla official",
               "pulled": dt.datetime.now().isoformat(timespec="seconds"),
               "rows": len(rows), "by_status": dict(st), "results": rows}
    p = os.path.join(OUT, "sci__supercharger_sites_AE.json")
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    log(f"UAE sites: {len(rows)} · {dict(st)}")
    log(f"stalls total {sum(r['stall_count'] or 0 for r in rows)}, "
        f"OPEN stalls {sum(r['stall_count'] or 0 for r in rows if r['status'] == 'OPEN')}")
    log(f"wrote {p}")


def load(include_unbuilt=False):
    import duckdb
    p = os.path.join(OUT, "sci__supercharger_sites_AE.json")
    if not os.path.exists(p):
        sys.exit(f"no payload at {p} -- run `python scripts/supercharge_pull.py pull` first")
    d = json.load(io.open(p, encoding="utf-8"))
    rows = d.get("results") or []
    if not rows: sys.exit("payload carried no rows")
    side = os.path.join(OUT, ".load.ndjson")
    with io.open(side, "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    con = duckdb.connect(DB)
    con.execute(f"create or replace table {TABLE} as select distinct * from "
                f"read_json(?, format='newline_delimited', sample_size=20000)", [side.replace(os.sep, "/")])
    n = con.execute(f"select count(*) from {TABLE}").fetchone()[0]
    # Only what is actually built. A PLAN site is a promise, not a charger.
    where = "" if include_unbuilt else "where status = 'OPEN'"
    con.execute(f"create or replace view {CLEAN} as select * from {TABLE} {where}")
    good = con.execute(f"select count(*) from {CLEAN}").fetchone()[0]
    con.execute("""create table if not exists ext_dataset (
        key varchar primary key, source varchar, dataset varchar, title varchar, licence varchar,
        provenance varchar, path varchar, pulled varchar, table_name varchar, clean_view varchar,
        rows_loaded bigint, rows_clean bigint, registered_at varchar, note varchar)""")
    con.execute("delete from ext_dataset where key = 'supercharge/sites'")
    con.execute("insert into ext_dataset values (" + ",".join("?" * 14) + ")", [
        "supercharge/sites", "supercharge.info", "allSites", "Tesla Supercharger sites (UAE)",
        "NO explicit open licence -- not cleared for public display",
        "community-maintained; NOT a government register and NOT Tesla official",
        OUT, d.get("pulled"), TABLE, CLEAN, n, good,
        dt.datetime.now().isoformat(timespec="seconds"),
        "enrichment source: stall counts and kW for Tesla points; OPEN sites only unless --include-unbuilt"])
    try: os.remove(side)
    except Exception: pass
    log(f"{TABLE}: {n} rows -> {CLEAN}: {good} OPEN")
    print(con.execute(f"select status, count(*) sites, sum(stall_count) stalls, max(power_kw) max_kw "
                      f"from {TABLE} group by 1 order by sites desc").fetchdf().to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "load"])
    ap.add_argument("--include-unbuilt", action="store_true",
                    help="also expose PLAN/PERMIT/CONSTRUCTION sites in the clean view")
    a = ap.parse_args()
    pull() if a.cmd == "pull" else load(a.include_unbuilt)


if __name__ == "__main__":
    main()
