"""Load Dubai Municipality's official geography into the truth store — Kendall, 9 Sep 2026: "load the address register and community boundaries".

Inputs (the raw shelf, data/raw_downloads/dd/):
  community__*.kml          224 official community polygons (CNAME_E / CNAME_A / COMM_NUM / DGIS_ID), extract dated 15 Aug 2026
  address__*.csv[part..]    DET business-licence address register (served under data.dubai): one row per licensed company's REGISTERED
                            address, DM plot id, community number, floor, unit; coordinates mostly empty
                            NOT PREMISES. Corrected 23 Sep 2026 - the earlier header here said "one row per licensed premises" and that
                            is the one claim this register cannot support. The address is where a company is REGISTERED, not where it
                            trades: nine "Gas Station" licences sit in Business Bay office towers of 19-39 floors, and one 29-floor
                            tower carries 2,663 active licences across 93 units (~29 per unit) whose commonest activities are tiling,
                            painting and carpentry - contractors with a registered office, not tenants with a door. Use this register
                            for tenancy DENSITY and for plot -> community. Never for "there is a pharmacy here".
                            Half of it carries no parcel at all: of 2,062,416 rows, 1,050,385 (50.9%) have a usable plot id, 688,420
                            are NULL and 323,611 are the string '0' - so dm_address_parcel rolling up 1,050,385 rows is correct and
                            current, not a stale half-load.

What it writes (evidence first, tables second, never a name onto a building):
  source / source_authority   dm_community (community 100, coordinates 95) · dm_address (parcel 95, coordinates 90, units 70)
  dm_community                one row per polygon: comm_num, name_en, name_ar, dgis_id, centroid, bbox, ring (lon lat pairs as JSON)
  building_dm_community       duid -> comm_num by point-in-polygon (also written as evidence: attribute dm_community, role LOCATION)
  district_dm_community       our 41 market districts -> the official communities they overlap, with the share of buildings in each
  dm_address                  the register as loaded (typed, plot_no normalised - see PLOT_NO_SQL), dm_address_parcel = per-plot roll-up (businesses, units, floors; position from the DLD plot when the row has none)
  evidence                    appended for what is new, and rows these two sources no longer support are closed (status SUPERSEDED, valid_to set)
  building_parcel_dm          duid -> DM plot id where the plot position sits within 60 m of the footprint point
                              (evidence: attribute plot_no + businesses_addressed, source dm_address, dist_m, ACCEPTED <= 25 m else DISCOVERED)
  views                       v_building_community, v_district_crosswalk, v_plot_businesses
Run after graph_build.py (it rebuilds the node tables) and before graph_golden_check.py / graph_export.py.
Usage: python scripts/graph_load_dm.py
"""
import glob, hashlib, io, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keys import num_sql
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
G = os.path.join(ROOT, "data", "graph"); DB = os.path.join(G, "najma.duckdb"); DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
NOW = time.strftime("%Y-%m-%dT%H:%M:%S"); RUN = time.strftime("%Y%m%d-%H%M%S") + "-dm"; SCHEMA = "1.2"; RESOLVER = "identity-2026-09-08-rolerule"

# The plot id as this register spells it (defect found 23 Sep 2026). read_csv_auto(all_varchar=true) hands us the parcelid text as written,
# and a few source rows wrote an integer parcel id through a float: '381.0', '893.00', '1503.'. Trimmed as-is those become plot keys of their
# own, so one plot's addresses, units and floors were rolled up under two keys and both counts came out short.
# Only the all-zeros-after-the-dot spellings are floats. Every other dotted value is the DM community-plot form written with a dot:
# '346.451' IS '346-451', community 346 plot 451, and there are 734 such values - a blanket cast to a number would truncate every one
# of them to its community number, the way it would flatten the 23,697 hyphenated ones.
# Fire on that one shape and hand it to num_sql (scripts/keys.py, the canonical rule); leave every other spelling exactly as written.
# The parcel key itself is not widened: '346.451' and '346-451' still meet only where parcel_key_sql is applied downstream.
# '.0' and '0.0' normalise to '0' and fall out on the plot_no <> '0' guard the dm_address_parcel roll-up already carries.
PLOT_NO_SQL = ("case when regexp_matches(trim(cast(parcelid as varchar)), '^([0-9]+[.]0*|[.]0+)$') then cast(%s as varchar)"
               " else trim(cast(parcelid as varchar)) end" % num_sql("parcelid"))


def address_files():
    """The address register's CSV parts, preferring the multi-part pull over the single-file fallback."""
    parts = sorted(glob.glob(os.path.join(DD, "address__*part*.csv"))) or sorted(glob.glob(os.path.join(DD, "address__*.csv")))
    return [p.replace("\\", "/") for p in parts]


def check_address_complete(con, files):
    """Refuse to write anything off a partial address pull (Azimuth Rings, 24 Sep 2026).

    The glob above falls back to the single file when the multi-part pull has not landed. On 9 Sep that happened twice: both
    runs printed "the multi-part pull had not finished" and then wrote 567 businesses_addressed rows off an incomplete
    register anyway. Nothing retracts them - the evidence id hashes the VALUE, so the corrected count lands beside the wrong
    one instead of superseding it, and 392 buildings still carry contradictory numbers because of it. An instrument that
    reports the smaller thing it did and then does it is the failure worth closing, not the 567 rows themselves.
    MANIFEST.json carries the row count the pull declared, so completeness is checkable rather than guessable.
    Pass --allow-partial to load anyway; the roll-up and the ledger are only as complete as what it read.
    """
    try:
        man = json.load(io.open(os.path.join(DD, "MANIFEST.json"), encoding="utf-8")).get("address") or {}
        want = int(man.get("rows"))
    except Exception as e:
        print(f"  ! MANIFEST.json gives no row count for the address register ({str(e)[:60]}) - completeness unchecked"); return
    got = con.execute("select count(*) from read_csv_auto(?, union_by_name=true, header=true, all_varchar=true)", [files]).fetchone()[0]
    if got == want:
        print(f"  address register complete: {got:,} rows, as MANIFEST.json declares"); return
    msg = (f"address register INCOMPLETE: {len(files)} file(s) give {got:,} rows, MANIFEST.json declares {want:,} "
           f"({want - got:+,}). Refusing to write dm_address off a partial pull - finish the multi-part download and rerun. "
           f"Pass --allow-partial to override.")
    if "--allow-partial" not in sys.argv:
        raise SystemExit("  ! " + msg)
    print("  ! " + msg.replace("Refusing to write", "Would refuse to write") + "  [--allow-partial given, loading anyway]")


def connect_writer(path, tries=20, wait=30):
    for k in range(tries):
        try: return duckdb.connect(path)
        except duckdb.IOException as e:
            if "being used by another process" not in str(e) or k == tries - 1: raise
            print(f"  truth store busy - waiting {wait}s ({k+1}/{tries})"); time.sleep(wait)


def eid(entity_id, attribute, value, source, rec):
    return hashlib.sha1(f"{entity_id}|{attribute}|{value}|{source}|{rec}".encode("utf-8")).hexdigest()[:24]


def parse_kml(path):
    t = open(path, encoding="utf-8", errors="ignore").read(); out = []
    for pm in re.findall(r"<Placemark.*?</Placemark>", t, re.S):
        def attr(k):
            m = re.search(r"<th>%s</th>\s*<td>(.*?)</td>" % k, pm, re.S); return m.group(1).strip() if m else None
        m = re.search(r"<coordinates>(.*?)</coordinates>", pm, re.S)
        if not m: continue
        ring = []
        for tok in m.group(1).split():
            p = tok.split(",")
            if len(p) >= 2:
                try: ring.append((float(p[0]), float(p[1])))
                except ValueError: pass
        if len(ring) < 4: continue
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        out.append({"comm_num": attr("COMM_NUM"), "name_en": (attr("CNAME_E") or "").strip(), "name_ar": (attr("CNAME_A") or "").strip(), "dgis_id": attr("DGIS_ID"),
                    "lon": sum(xs) / len(xs), "lat": sum(ys) / len(ys), "w": min(xs), "s": min(ys), "e": max(xs), "n": max(ys), "ring": ring})
    return out


def inside(pt, ring):
    x, y = pt; c = False; n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]; x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
            if x < xin: c = not c
    return c


def locate(polys, lon, lat):
    for p in polys:
        if p["w"] <= lon <= p["e"] and p["s"] <= lat <= p["n"] and inside((lon, lat), p["ring"]): return p
    return None


def main():
    t0 = time.time(); con = connect_writer(DB)
    files = address_files(); check_address_complete(con, files)   # fail closed before anything is written
    kml = sorted(glob.glob(os.path.join(DD, "community__*.kml")))[-1]; polys = parse_kml(kml)
    print(f"communities: {len(polys)} polygons from {os.path.basename(kml)}")
    # ---- sources -------------------------------------------------------------------------------------------------------------------
    con.execute("delete from source where source_id in ('dm_community','dm_address')")
    con.execute("insert into source values ('dm_community','Dubai Municipality','community boundaries (GIS, data.dubai)','authority','AE-DU'), ('dm_address','Dubai Municipality','address register (data.dubai)','authority','AE-DU')")
    con.execute("delete from source_authority where source_id in ('dm_community','dm_address')")
    con.execute("insert into source_authority values ('dm_community','community',100), ('dm_community','coordinates',95), ('dm_address','parcel',95), ('dm_address','coordinates',90), ('dm_address','units',70), ('dm_address','address',95)")
    # ---- dm_community ----------------------------------------------------------------------------------------------------------------
    con.execute("create or replace table dm_community (comm_num varchar, name_en varchar, name_ar varchar, dgis_id varchar, lon double, lat double, bbox_w double, bbox_s double, bbox_e double, bbox_n double, ring_json varchar, extract_date varchar)")
    con.executemany("insert into dm_community values (?,?,?,?,?,?,?,?,?,?,?,?)", [(p["comm_num"], p["name_en"], p["name_ar"], p["dgis_id"], p["lon"], p["lat"], p["w"], p["s"], p["e"], p["n"], json.dumps(p["ring"]), "2026-08-15") for p in polys])
    # ---- buildings, sub-communities, districts -> community (point in polygon) --------------------------------------------------------
    rows = con.execute("select duid, lon, lat from building where lon is not null").fetchall()
    bc = []; ev = []; miss = 0
    for duid, lon, lat in rows:
        p = locate(polys, lon, lat)
        if not p: miss += 1; continue
        bc.append((duid, p["comm_num"], p["name_en"]))
        ev.append((eid(duid, "dm_community", p["comm_num"], "dm_community", p["dgis_id"]), RUN, "building", duid, "dm_community", p["comm_num"], "LOCATION", "dm_community", p["dgis_id"], "footprint point inside the official community polygon", 0.98, None, 0.0, True, NOW, "ACCEPTED", SCHEMA, RESOLVER, "2026-08-15", None))
    con.execute("create or replace table building_dm_community (duid varchar, comm_num varchar, name_en varchar)")
    if bc: con.executemany("insert into building_dm_community values (?,?,?)", bc)
    print(f"  buildings located: {len(bc):,} · outside every polygon: {miss:,}")
    subs = con.execute("select sub_id, lon, lat from sub_community where lon is not null").fetchall(); sc = []
    for sid, lon, lat in subs:
        p = locate(polys, lon, lat)
        if p:
            sc.append((sid, p["comm_num"], p["name_en"]))
            ev.append((eid(sid, "dm_community", p["comm_num"], "dm_community", p["dgis_id"]), RUN, "sub_community", sid, "dm_community", p["comm_num"], "LOCATION", "dm_community", p["dgis_id"], "cluster centroid inside the official community polygon", 0.95, None, 0.0, True, NOW, "ACCEPTED", SCHEMA, RESOLVER, "2026-08-15", None))
    con.execute("create or replace table sub_community_dm (sub_id varchar, comm_num varchar, name_en varchar)")
    if sc: con.executemany("insert into sub_community_dm values (?,?,?)", sc)
    con.execute("""create or replace table district_dm_community as
        select b.district as slug, c.comm_num, c.name_en, count(*) as buildings,
               round(count(*) * 1.0 / sum(count(*)) over (partition by b.district), 3) as share
        from building_dm_community c join building b on b.duid = c.duid group by 1, 2, 3 order by 1, 4 desc""")
    print(f"  sub-communities located: {len(sc):,} of {len(subs):,} · district crosswalk rows: {con.execute('select count(*) from district_dm_community').fetchone()[0]}")
    # ---- dm_address ------------------------------------------------------------------------------------------------------------------
    # What this register really is (checked 9 Sep 2026): the DET business-licence ADDRESS register served under data.dubai (cdn path det/open/address):
    # one row per licensed company's REGISTERED address, Arabic address line, unit number, floor, area = DM community number, parcel id in
    # DM plot form "346-451". Coordinates are mostly 0 / null. It is NOT a residential unit register, and (corrected 23 Sep 2026) it is not
    # a premises register either - see the module header. Useful as: businesses per plot (tenancy density), plot -> community. Not for
    # "there is a pharmacy here": the licence sits at the registered office, which is usually a business centre in a tower.
    print(f"  address files: {len(files)}")
    con.execute("create or replace table dm_address as select try_cast(id as bigint) as id, addressline1, addressline2, addresstype, area as comm_num, street, try_cast(floor as varchar) as floor, unitnumber, unittype, "
                f"{PLOT_NO_SQL} as plot_no, case when try_cast(latitude as double) between 24.5 and 25.6 then try_cast(latitude as double) end as lat, "
                "case when try_cast(longitude as double) between 54.5 and 56.5 then try_cast(longitude as double) end as lon, freezone, emirate "
                "from read_csv_auto(?, union_by_name=true, header=true, all_varchar=true)", [files])
    n_addr = con.execute("select count(*) from dm_address").fetchone()[0]
    con.execute("""create or replace table dm_address_parcel as
        select a.plot_no, count(*) as addresses, count(distinct a.unitnumber) filter (where a.unitnumber is not null and a.unitnumber <> '') as units,
               count(distinct a.floor) filter (where a.floor is not null and a.floor <> '' and a.floor <> '0') as floors, any_value(a.comm_num) as comm_num,
               coalesce(avg(a.lon), any_value(p.lon)) as lon, coalesce(avg(a.lat), any_value(p.lat)) as lat, mode(a.unittype) as unit_type,
               count(a.lon) as located_rows, any_value(p.district) as district
        from dm_address a left join (select plot_no, any_value(lon) lon, any_value(lat) lat, any_value(district) district from plot group by plot_no) p on p.plot_no = a.plot_no
        where a.plot_no is not null and a.plot_no <> '' and a.plot_no <> '0' group by a.plot_no""")
    n_parc = con.execute("select count(*) from dm_address_parcel").fetchone()[0]
    n_pos = con.execute("select count(*) from dm_address_parcel where lon is not null").fetchone()[0]
    n_plot = con.execute("select count(*) from dm_address_parcel a where exists (select 1 from plot p where p.plot_no = a.plot_no)").fetchone()[0]
    print(f"  address rows: {n_addr:,} · plots with addresses: {n_parc:,} · with a position: {n_pos:,} · matching our DLD plot register: {n_plot:,}")
    # plot position -> nearest building within 60 m (bucketed self-join, planar metres at 25 N)
    con.execute("""create or replace table building_parcel_dm as
        with a as (select plot_no, addresses, units, floors, lon, lat, floor(lat*500) as gy, floor(lon*500) as gx from dm_address_parcel where lon is not null),
             b as (select duid, district, lon, lat, floor(lat*500) as gy, floor(lon*500) as gx from building where lon is not null),
             j as (select a.plot_no, a.addresses, a.units, a.floors, b.duid, b.district,
                          sqrt(power((b.lat-a.lat)*111320, 2) + power((b.lon-a.lon)*100800, 2)) as dist_m
                   from a join b on b.gy between a.gy-1 and a.gy+1 and b.gx between a.gx-1 and a.gx+1),
             r as (select *, row_number() over (partition by plot_no order by dist_m) rn from j where dist_m <= 60)
        select plot_no as parcel_id, duid, district, addresses, units, floors, round(dist_m, 1) as dist_m from r where rn = 1""")
    links = con.execute("select parcel_id, duid, addresses, units, floors, dist_m from building_parcel_dm").fetchall()
    for parcel_id, duid, addresses, units, floors, dist in links:
        st = "ACCEPTED" if dist <= 25 else "DISCOVERED"
        ev.append((eid(duid, "plot_no", parcel_id, "dm_address", parcel_id), RUN, "building", duid, "plot_no", parcel_id, "IDENTIFIER", "dm_address", parcel_id, "DET licence addresses on the plot; plot position nearest the footprint point", 0.85 if dist <= 25 else 0.55, None, float(dist), dist <= 25, NOW, st, SCHEMA, RESOLVER, "2026-08-04", None))
        ev.append((eid(duid, "businesses_addressed", str(addresses), "dm_address", parcel_id), RUN, "building", duid, "businesses_addressed", str(addresses), "MEASURE", "dm_address", parcel_id, "licences REGISTERED to an address on the plot in the DET address register - a registered office, not a shopfront", 0.8, None, float(dist), dist <= 25, NOW, "DISCOVERED", SCHEMA, RESOLVER, "2026-08-04", None))
    # ---- evidence: append what the ledger has not seen, and close what this run no longer stands behind -------------------------------------
    # The append is keyed on a hash that includes the VALUE, so a corrected number lands BESIDE the old one instead of replacing it. Left at
    # that, every rerun widens the disagreement: on 24 Sep 2026, 392 buildings held two or more businesses_addressed values at once, one of
    # them 4, 32 and 6, and nothing in the row said which was current. A reader taking the newest run was right by luck, not by construction.
    # ev_new is this run's complete recomputation of everything these two sources assert, so any open row of theirs NOT in it is a claim the
    # current data no longer supports - a partial pull's count, or a parcel link that has since moved. Close those rather than delete them:
    # the ledger keeps its history, status stops readers believing them, and valid_to says when they stopped being true. Idempotent, because
    # each run re-affirms its own set and closing an already-closed row is a no-op.
    con.execute("create or replace temp table ev_new as select * from evidence limit 0")
    con.executemany("insert into ev_new values (" + ",".join("?" * 20) + ")", ev)
    added = con.execute("insert into evidence select n.* from ev_new n where not exists (select 1 from evidence e where e.evidence_id = n.evidence_id)").fetchone()[0]
    closed = con.execute("""update evidence set status = 'SUPERSEDED', valid_to = ?
        where source in ('dm_address', 'dm_community') and valid_to is null and status <> 'SUPERSEDED'
          and evidence_id not in (select evidence_id from ev_new)""", [NOW]).fetchone()[0]
    con.execute("""create or replace view v_building_community as
        select b.duid, b.district, b.display_name, c.comm_num, c.name_en as community, c.name_ar as community_ar from building b left join building_dm_community bc on bc.duid=b.duid left join dm_community c on c.comm_num=bc.comm_num""")
    con.execute("create or replace view v_district_crosswalk as select d.slug, d.name as market_name, x.comm_num, x.name_en as official_community, x.buildings, x.share from district d join district_dm_community x on x.slug=d.slug order by d.slug, x.share desc")
    con.execute("create or replace view v_plot_businesses as select p.duid, p.parcel_id as plot_no, p.addresses as businesses, p.units, p.floors, p.dist_m from building_parcel_dm p")
    con.execute("insert into run values (?,?,?,?,?)", [RUN, NOW, SCHEMA, RESOLVER, f"dm loader: {len(bc)} community links, {len(links)} parcel links, {added} evidence rows appended, {closed} superseded, {len(files)} address file(s)"])
    con.close()
    print(f"  parcel -> building links: {len(links):,} (within 25 m: {sum(1 for l in links if l[5] <= 25):,}) · evidence rows appended: {added:,} · superseded: {closed:,}")
    top = duckdb.connect(DB, read_only=True).execute("select slug, official_community, share from v_district_crosswalk where share >= 0.2 order by slug, share desc limit 12").fetchall()
    print("  crosswalk sample:", top)
    print(f"done in {round(time.time()-t0)} s")


if __name__ == "__main__":
    main()
