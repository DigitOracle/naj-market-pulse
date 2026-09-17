"""osm_pull.py -- OpenStreetMap charging stations for the UAE, via Overpass.

The third source behind the Azimuth EV map, after the DEWA register and OpenChargeMap. It adds few
points but they are points nothing else has: unbranded forecourt chargers, ADNOC, ENOC, EPPCO, UAEV
and RTA sites that neither DEWA's register nor OCM lists.

Like OCM this is community-contributed, so it lands in `osm__charge_points` / `o_osm__charge_points`
and registers in `ext_dataset`, never the `gov_*` namespace. GOV_DATA_METHODOLOGY.md requires a
posted number to trace to a public body; OSM cannot carry that.

LICENCE: ODbL. Attribution is required wherever the points are shown, and share-alike attaches to a
derived DATABASE (not to the rendered map). The app footer carries the attribution.

THE NOISE PROBLEM: `amenity=charging_station` is not EV-only in the UAE extract. The tag is used for
mobile-phone charging points (two "Wifi UAE" records), and nearby records include a medical FZE, a
gas supplier and an electrical substation. Ingesting the tag raw would put phone chargers on a map of
EV chargers. So every row must pass `looks_like_ev()` below, and the rejects are printed rather than
silently dropped -- a filter you cannot see is a filter you cannot check.

    python scripts/osm_pull.py pull      # Overpass -> data/raw_downloads/osm/
    python scripts/osm_pull.py load      # -> duckdb table + clean view
"""
import argparse, datetime as dt, io, json, os, re, sys, urllib.error, urllib.parse, urllib.request

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "osm")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
TABLE = "osm__charge_points"
CLEAN = "o_osm__charge_points"

# The main instance answered 504 repeatedly while this was written; kumi answered. Try both.
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]

QUERY = """[out:json][timeout:180];
area["ISO3166-1"="AE"][admin_level=2]->.ae;
(
  node["amenity"="charging_station"](area.ae);
  way["amenity"="charging_station"](area.ae);
  node["man_made"="charge_point"](area.ae);
  way["man_made"="charge_point"](area.ae);
);
out center tags;"""

# Substrings that mark a record as NOT an EV charge point. Checked against name/operator/brand.
NOT_EV = re.compile(r"mobile\s*phone|phone\s*charg|wifi|internet|medical|pharmac|"
                    r"gas\s*suppl|substation|transformer|laptop", re.I)


def log(*a): print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def looks_like_ev(tags):
    """True when the record is an EV charge point. Returns (ok, reason_if_not)."""
    blob = " ".join(str(tags.get(k, "")) for k in ("name", "name:en", "operator", "brand",
                                                   "network", "description", "note"))
    if NOT_EV.search(blob):
        return False, "non-EV keyword"
    # An explicitly bicycle/scooter-only point is not a car charge point.
    if tags.get("motorcar") == "no" and tags.get("bicycle") == "yes":
        return False, "bicycle only"
    if tags.get("amenity") != "charging_station" and tags.get("man_made") != "charge_point":
        return False, "not a charging tag"
    return True, None


def sockets(tags):
    """socket:type2=2, socket:ccs=1 ... -> ("Type 2 , CCS", total count, max kW)."""
    names, total, kw = [], 0, None
    label = {"type2": "AC Type 2 (Mennekes)", "type2_combo": "DC ComboCCS2", "type2_cable": "AC Type 2 (cable)",
             "ccs": "DC ComboCCS2", "chademo": "DC ChaDeMo", "tesla_supercharger": "Tesla Supercharger",
             "tesla_supercharger_ccs": "DC ComboCCS2", "type1": "AC Type 1", "schuko": "AC Schuko"}
    for k, v in tags.items():
        if not k.startswith("socket:"): continue
        part = k.split(":", 1)[1]
        if part.endswith(":output"):
            try:
                n = float(re.sub(r"[^\d.]", "", str(v)) or 0)
                kw = n if kw is None else max(kw, n)
            except Exception: pass
            continue
        try: q = int(re.sub(r"[^\d]", "", str(v)) or 1)
        except Exception: q = 1
        names.append(label.get(part, part.replace("_", " ").title()))
        total += max(q, 1)
    for key in ("charging_station:output", "maxpower", "power", "socket:output"):
        if key in tags:
            try:
                n = float(re.sub(r"[^\d.]", "", str(tags[key])) or 0)
                if n: kw = n if kw is None else max(kw, n)
            except Exception: pass
    if not total:
        try: total = int(re.sub(r"[^\d]", "", str(tags.get("capacity", "") or "")) or 0)
        except Exception: total = 0
    return (" , ".join(names) if names else None), total, kw


def pull():
    os.makedirs(OUT, exist_ok=True)
    data = None
    for ep in ENDPOINTS:
        try:
            log(f"querying {ep.split('/')[2]} ...")
            req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": QUERY}).encode(),
                                         headers={"User-Agent": "DigitAlchemy-Azimuth/1.0 (contact@digitalabbot.io)"})
            with urllib.request.urlopen(req, timeout=200) as h:
                data = json.loads(h.read()); break
        except Exception as e:
            log(f"  {type(e).__name__}: {e}")
    if data is None:
        sys.exit("every Overpass endpoint failed; try again later")

    rows, rejected = [], []
    for e in data.get("elements", []):
        tags = e.get("tags") or {}
        lat = e.get("lat") if e.get("lat") is not None else (e.get("center") or {}).get("lat")
        lon = e.get("lon") if e.get("lon") is not None else (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            rejected.append((e.get("id"), tags.get("name"), "no coordinates")); continue
        ok, why = looks_like_ev(tags)
        if not ok:
            rejected.append((e.get("id"), tags.get("name"), why)); continue
        ct, n, kw = sockets(tags)
        rows.append({
            "osm_id": f"{e.get('type','node')}/{e.get('id')}",
            "location_name": tags.get("name") or tags.get("name:en") or tags.get("operator") or "Unnamed charging station",
            "location_address": ", ".join(x for x in [tags.get("addr:street"), tags.get("addr:city")] if x) or None,
            "operator": tags.get("operator") or tags.get("brand") or tags.get("network"),
            "latitude": float(lat), "longitude": float(lon),
            "totalnbofconnectors": n or 0,
            "connectortype": ct,
            "max_power_kw": kw,
            "access": tags.get("access"),
            "source_url": f"https://www.openstreetmap.org/{e.get('type','node')}/{e.get('id')}",
        })

    payload = {"source": "OpenStreetMap via Overpass", "licence": "ODbL -- attribution required",
               "provenance": "community-contributed; NOT a government register",
               "pulled": dt.datetime.now().isoformat(timespec="seconds"),
               "rows": len(rows), "rejected": len(rejected), "results": rows}
    p = os.path.join(OUT, "osm__charge_points_AE.json")
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    log(f"kept {len(rows)}, rejected {len(rejected)}")
    for rid, nm, why in rejected:
        log(f"  rejected {rid} ({nm or 'unnamed'}): {why}")
    log(f"wrote {p}")


def load():
    import duckdb
    p = os.path.join(OUT, "osm__charge_points_AE.json")
    if not os.path.exists(p):
        sys.exit(f"no payload at {p} -- run `python scripts/osm_pull.py pull` first")
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
    con.execute(f"""create or replace view {CLEAN} as select * from {TABLE}
                    where latitude between 22.5 and 26.6 and longitude between 51.0 and 56.6""")
    good = con.execute(f"select count(*) from {CLEAN}").fetchone()[0]
    con.execute("""create table if not exists ext_dataset (
        key varchar primary key, source varchar, dataset varchar, title varchar, licence varchar,
        provenance varchar, path varchar, pulled varchar, table_name varchar, clean_view varchar,
        rows_loaded bigint, rows_clean bigint, registered_at varchar, note varchar)""")
    con.execute("delete from ext_dataset where key = 'osm/charge_points'")
    con.execute("insert into ext_dataset values (" + ",".join("?" * 14) + ")", [
        "osm/charge_points", "OpenStreetMap", "overpass", "EV charging stations (UAE)",
        "ODbL -- attribution required, share-alike on derived databases",
        "community-contributed; NOT a government register", OUT, d.get("pulled"), TABLE, CLEAN,
        n, good, dt.datetime.now().isoformat(timespec="seconds"),
        f"{d.get('rejected', 0)} records rejected as non-EV before load"])
    try: os.remove(side)
    except Exception: pass
    log(f"{TABLE}: {n} rows -> {CLEAN}: {good} in the UAE fence")
    print(con.execute(f"select coalesce(operator,'(unbranded)') op, count(*) n from {CLEAN} "
                      f"group by 1 order by n desc limit 12").fetchdf().to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "load"])
    a = ap.parse_args()
    pull() if a.cmd == "pull" else load()


if __name__ == "__main__":
    main()
