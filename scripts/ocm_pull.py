"""ocm_pull.py -- OpenChargeMap ingestion for the Azimuth EV charging map.

Why this exists: DEWA's register reaches us only through the data.dubai STAGING tier, which serves 177
charge points against DEWA's published 2,223 for Q1 2026, with row timestamps frozen at Oct 2025.
Production credentials are requested (docs/DDA_PRODUCTION_CREDENTIALS_REQUEST_17SEP2026.md) but even
production is DEWA-only. OpenChargeMap carries every operator -- DEWA, UAEV, ADNOC E2GO, Tesla,
private -- across the whole UAE.

NAMESPACE, AND WHY IT IS NOT gov_: OpenChargeMap is community-contributed, not a government register.
GOV_DATA_METHODOLOGY.md requires a posted number to trace to a public body, a date and an openable
row; OCM satisfies the date and the row but NOT the public body. So it lands as `ocm__charge_points`,
never `gov_*`, and registers in `ext_dataset` rather than `gov_dataset` -- which load_gov_datasets.py
rebuilds with `create or replace` from the DDA manifest and would silently wipe an OCM row anyway.
Downstream must treat an OCM figure as community-reported and say so.

Credentials live OUTSIDE the repo in C:\\Users\\kwils\\digitalchemy-ocm.env (never committed, never
printed). A free key is issued instantly at https://openchargemap.org/site/develop/api.

    OCM_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Usage:
    python scripts/ocm_pull.py health                  # key valid? how many UAE points?
    python scripts/ocm_pull.py pull                    # all UAE points -> data/raw_downloads/ocm/
    python scripts/ocm_pull.py pull --country AE,SA    # several countries
    python scripts/ocm_pull.py load                    # raw JSON -> duckdb table + clean view
    python scripts/ocm_pull.py compare                 # OCM vs the DEWA register, side by side

API facts: v3/poi returns a flat array; `compact=true` strips reference data, so operator and
connection-type names come from v3/referencedata and are joined here. No documented hard rate limit,
so we self-throttle at 1 req/s as we do for DDA.
"""
import argparse, datetime as dt, io, json, os, socket, sys, time, urllib.error, urllib.parse, urllib.request

socket.setdefaulttimeout(60)
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ENV = os.environ.get("OCM_ENV_FILE", r"C:\Users\kwils\digitalchemy-ocm.env")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "ocm")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
API = "https://api.openchargemap.io/v3"
TABLE = "ocm__charge_points"
CLEAN = "o_ocm__charge_points"
RATE_S = 1.05
PAGE = 500                      # OCM caps a single response well below the UAE total; we page by offset
UAE_BBOX = (22.5, 51.0, 26.6, 56.6)     # lat_min, lon_min, lat_max, lon_max -- sanity fence, not a filter
_last = [0.0]


def cfg():
    if not os.path.exists(ENV):
        sys.exit(
            f"credentials file not found: {ENV}\n"
            "Get a free key at https://openchargemap.org/site/develop/api (instant, no cost), then create\n"
            f"{ENV} containing one line:\n    OCM_API_KEY=<your-key>"
        )
    d = {}
    for line in io.open(ENV, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    if not d.get("OCM_API_KEY"):
        sys.exit(f"OCM_API_KEY missing from {ENV}")
    return d


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def _throttle():
    wait = RATE_S - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()


def _get(path, params, key, timeout=55):
    """GET with the key in the header (the query-string form is deprecated and 403s on some edges)."""
    _throttle()
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    r = urllib.request.Request(url, headers={
        "X-API-Key": key,
        "User-Agent": "DigitAlchemy-Azimuth/1.0 (contact@digitalabbot.io)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(r, timeout=timeout) as h:
            return h.status, json.loads(h.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode(errors="replace")
    except Exception as e:
        return 0, f"transport error: {e}"


def refdata(key):
    """Operator and connection-type names. compact=true omits them from the POI rows."""
    code, d = _get("referencedata", {}, key)
    if code != 200 or not isinstance(d, dict):
        log(f"referencedata HTTP {code} -- names will fall back to ids")
        return {}, {}, {}
    ops = {o["ID"]: o.get("Title") for o in d.get("Operators", []) if o.get("ID") is not None}
    conns = {c["ID"]: c.get("Title") for c in d.get("ConnectionTypes", []) if c.get("ID") is not None}
    stats = {s["ID"]: s.get("Title") for s in d.get("StatusTypes", []) if s.get("ID") is not None}
    return ops, conns, stats


def pull(countries, key):
    """Page by offset until a short page. OCM wraps nothing, so a short page really is the end."""
    os.makedirs(OUT, exist_ok=True)
    ops, conns, stats = refdata(key)
    rows, offset = [], 0
    while True:
        code, d = _get("poi", {
            "output": "json", "countrycode": countries, "maxresults": PAGE, "offset": offset,
            "compact": "true", "verbose": "false", "includecomments": "false",
        }, key)
        if code != 200:
            if offset == 0: sys.exit(f"HTTP {code}: {d}")
            log(f"HTTP {code} at offset {offset}; stopping with what we have"); break
        if not isinstance(d, list):
            log(f"unexpected payload at offset {offset}; stopping"); break
        rows.extend(d)
        log(f"offset {offset}: {len(d)} rows (total {len(rows)})")
        if len(d) < PAGE: break
        offset += PAGE
        if offset > 100_000:
            log("offset ceiling reached; stopping"); break

    flat = [flatten(p, ops, conns, stats) for p in rows]
    flat = [f for f in flat if f]
    payload = {
        "source": "OpenChargeMap v3/poi",
        "licence": "OpenChargeMap data is licensed CC-BY-SA 4.0 -- attribution required on any surface",
        "provenance": "community-contributed; NOT a government register",
        "countries": countries,
        "pulled": dt.datetime.now().isoformat(timespec="seconds"),
        "rows": len(flat),
        "results": flat,
    }
    path = os.path.join(OUT, f"ocm__charge_points_{countries.replace(',', '_')}.json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    log(f"wrote {path} ({len(flat)} rows)")
    return path


def flatten(p, ops, conns, stats):
    """One row per charge point. Connections collapse to a count, a kW max and a joined type list --
    the same shape DEWA uses (totalnbofconnectors + a comma-joined connectortype)."""
    ai = p.get("AddressInfo") or {}
    lat, lon = ai.get("Latitude"), ai.get("Longitude")
    if lat is None or lon is None:
        return None
    cs = [c for c in (p.get("Connections") or []) if isinstance(c, dict)]
    kws = [c.get("PowerKW") for c in cs if isinstance(c.get("PowerKW"), (int, float))]
    names = [conns.get(c.get("ConnectionTypeID")) or f"type_{c.get('ConnectionTypeID')}" for c in cs]
    qty = sum(c.get("Quantity") or 1 for c in cs) if cs else (p.get("NumberOfPoints") or 0)
    return {
        "ocm_id": p.get("ID"),
        "uuid": p.get("UUID"),
        "location_name": ai.get("Title"),
        "location_address": ", ".join(x for x in [ai.get("AddressLine1"), ai.get("Town"),
                                                  ai.get("StateOrProvince")] if x),
        "town": ai.get("Town"),
        "state": ai.get("StateOrProvince"),
        "country_id": (ai.get("CountryID") if "CountryID" in ai else None),
        "latitude": lat,
        "longitude": lon,
        "operator": ops.get(p.get("OperatorID")) or (f"operator_{p.get('OperatorID')}"
                                                     if p.get("OperatorID") else None),
        "operator_id": p.get("OperatorID"),
        "status": stats.get(p.get("StatusTypeID")),
        "usage_type_id": p.get("UsageTypeID"),
        "totalnbofconnectors": qty,
        "connectortype": " , ".join(names) if names else None,
        "max_power_kw": max(kws) if kws else None,
        "date_last_verified": p.get("DateLastVerified"),
        "date_last_status_update": p.get("DateLastStatusUpdate"),
        "source_url": f"https://openchargemap.org/site/poi/details/{p.get('ID')}",
    }


def load():
    """Materialise the raw JSON, then build the clean view. Mirrors the gov pipeline's two-step shape:
    a base table nothing downstream may read, and a gated view that it may."""
    import duckdb
    files = [os.path.join(OUT, f) for f in os.listdir(OUT) if f.endswith(".json")] if os.path.isdir(OUT) else []
    if not files:
        sys.exit(f"no OCM payload in {OUT} -- run `python scripts/ocm_pull.py pull` first")
    con = duckdb.connect(DB)
    rows, pulled = [], None
    for p in files:
        d = json.load(io.open(p, encoding="utf-8"))
        rows.extend(d.get("results") or [])
        pulled = d.get("pulled") or pulled
    if not rows:
        sys.exit("payload carried no rows")

    # read_json wants a path; write a scratch NDJSON so DuckDB infers the types itself.
    side = os.path.join(OUT, ".load.ndjson")
    with io.open(side, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    con.execute(f"create or replace table {TABLE} as select distinct * from "
                f"read_json(?, format='newline_delimited', sample_size=20000)", [side.replace(os.sep, "/")])
    n = con.execute(f"select count(*) from {TABLE}").fetchone()[0]

    # The gate: a usable row needs real coordinates inside the UAE fence and at least one connector.
    la0, lo0, la1, lo1 = UAE_BBOX
    con.execute(f"""create or replace view {CLEAN} as
        select * from {TABLE}
        where latitude between {la0} and {la1}
          and longitude between {lo0} and {lo1}
          and coalesce(totalnbofconnectors, 0) > 0""")
    good = con.execute(f"select count(*) from {CLEAN}").fetchone()[0]

    con.execute("""create table if not exists ext_dataset (
        key varchar primary key, source varchar, dataset varchar, title varchar, licence varchar,
        provenance varchar, path varchar, pulled varchar, table_name varchar, clean_view varchar,
        rows_loaded bigint, rows_clean bigint, registered_at varchar, note varchar)""")
    con.execute("delete from ext_dataset where key = 'ocm/charge_points'")
    con.execute("insert into ext_dataset values (" + ",".join("?" * 14) + ")", [
        "ocm/charge_points", "OpenChargeMap", "poi", "EV charge points (all operators)",
        "CC-BY-SA 4.0 -- attribution required", "community-contributed; NOT a government register",
        OUT, pulled, TABLE, CLEAN, n, good, dt.datetime.now().isoformat(timespec="seconds"),
        f"{n - good} rows failed the coordinate/connector gate",
    ])
    try: os.remove(side)
    except Exception: pass
    log(f"{TABLE}: {n} rows -> {CLEAN}: {good} usable ({n - good} gated out)")
    print(con.execute(f"select operator, count(*) n, sum(totalnbofconnectors) connectors "
                      f"from {CLEAN} group by 1 order by n desc limit 15").fetchdf().to_string())


def compare():
    """OCM against the DEWA staging register -- the honest measure of what the gap actually is."""
    import duckdb
    con = duckdb.connect(DB, read_only=True)
    have = {r[0] for r in con.execute("show tables").fetchall()}
    if CLEAN not in have and TABLE not in have:
        sys.exit("no OCM table yet -- run `pull` then `load`")
    dewa = con.execute("select count(*), sum(try_cast(totalnbofconnectors as int)) "
                       "from g_dewa__ev_green_charger").fetchone()
    ocm_all = con.execute(f"select count(*), sum(totalnbofconnectors) from {CLEAN}").fetchone()
    ocm_dxb = con.execute(f"select count(*), sum(totalnbofconnectors) from {CLEAN} "
                          f"where lower(coalesce(town,'') || ' ' || coalesce(state,'')) like '%dubai%'").fetchone()
    print(f"{'source':<38} {'points':>8} {'connectors':>11}")
    print(f"{'-'*38} {'-'*8} {'-'*11}")
    print(f"{'DEWA register (data.dubai staging)':<38} {dewa[0]:>8} {dewa[1] or 0:>11}")
    print(f"{'OpenChargeMap, Dubai':<38} {ocm_dxb[0]:>8} {ocm_dxb[1] or 0:>11}")
    print(f"{'OpenChargeMap, all pulled countries':<38} {ocm_all[0]:>8} {ocm_all[1] or 0:>11}")
    print("\nDEWA published 2,223 charge points for Dubai, Q1 2026.")
    print("OCM is community-contributed: treat it as reported, not registered.")


def health(key):
    code, d = _get("poi", {"output": "json", "countrycode": "AE", "maxresults": 1,
                           "compact": "true", "verbose": "false"}, key)
    if code != 200:
        sys.exit(f"HTTP {code}: {d}")
    log(f"key OK -- UAE reachable, sample row id {d[0].get('ID') if d else 'none'}")
    code, d = _get("poi", {"output": "json", "countrycode": "AE", "maxresults": 10000,
                           "compact": "true", "verbose": "false"}, key)
    if code == 200 and isinstance(d, list):
        log(f"UAE charge points available: {len(d)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["health", "pull", "load", "compare"])
    ap.add_argument("--country", default="AE", help="comma-separated ISO codes (default AE)")
    a = ap.parse_args()
    if a.cmd == "load": return load()
    if a.cmd == "compare": return compare()
    key = cfg()["OCM_API_KEY"]
    if a.cmd == "health": return health(key)
    if a.cmd == "pull": return pull(a.country, key)


if __name__ == "__main__":
    main()
