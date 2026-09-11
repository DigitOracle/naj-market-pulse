"""graph_load_dm_permits.py -- the DM Building Permits slice of the truth store (Kendall, 11 Sep 2026).

Source: Dubai Municipality "Building Permits Applications" register from data.dubai (data/registers/building_permits/*.csv, the
2026-08-31 extract; 778k application rows, 114k parcels). The same dataset sits behind the governed API (dm_building_permits) - the
API pull is re-run when the service is back and this loader accepts either file.

What lands:
  dm_building_permits        raw, typed, one row per application (append-only re-landing: the table is replaced from the file, the
                             evidence it produced is never deleted)
  dm_parcel_permits          one row per DM parcel: permit counts, last permit, last NEW-BUILDING permit delivered, building type,
                             buildings/area permitted, and a construction signal (a new-building or addition permit delivered in the
                             last 30 months before the extract)
  evidence                   per building (via building_parcel_dm) and per plot (via plot.parcel_id): permit_last, new_building_permit,
                             permit_building_type, permit_building_count, permit_total_area_sqm, construction_signal - source dm_permits
  views                      v_plot_permits, v_building_permits, v_construction_signal

Parcel id forms: permits '2621465.00' -> 2621465 (community*10000 + plot); plot.parcel_id '6830847.00' same; building_parcel_dm
'392-434' -> 3920434 (DM plot form); bare '3731343' as is.

Usage:  python scripts/graph_load_dm_permits.py [csv]          then  python scripts/graph_golden_check.py
"""
import glob, hashlib, os, sys, time
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
NOW = time.strftime("%Y-%m-%dT%H:%M:%S"); RUN = time.strftime("%Y%m%d-%H%M%S") + "-dmpermits"; SCHEMA = "1.2"; RESOLVER = "identity-2026-09-08-rolerule"
ACTIVE_MONTHS = 30


def connect_writer(path, tries=20, wait=30):
    for k in range(tries):
        try: return duckdb.connect(path)
        except duckdb.IOException as e:
            if "being used by another process" not in str(e) or k == tries - 1: raise
            print(f"  truth store busy - waiting {wait}s ({k+1}/{tries})"); time.sleep(wait)


def eid(entity_id, attribute, value, source, rec):
    return hashlib.sha1(f"{entity_id}|{attribute}|{value}|{source}|{rec}".encode("utf-8")).hexdigest()[:24]


def main():
    t0 = time.time()
    csv = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(ROOT, "data", "registers", "building_permits", "*.csv")))[-1]
    extract = os.path.basename(csv).split("_")[2] if "_" in os.path.basename(csv) else NOW[:10]     # building_permits_2026-08-31_...
    con = connect_writer(DB); csvp = csv.replace("\\", "/")
    print(f"permits file: {os.path.basename(csv)} (extract {extract})")
    # ---- source + authority --------------------------------------------------------------------------------------------------------
    con.execute("delete from source where source_id = 'dm_permits'")
    con.execute("insert into source values ('dm_permits','Dubai Municipality','building permits applications (data.dubai)','authority','AE-DU')")
    con.execute("delete from source_authority where source_id = 'dm_permits'")
    con.execute("insert into source_authority values ('dm_permits','permit',95), ('dm_permits','construction_status',90), ('dm_permits','building_type',85), ('dm_permits','building_count',85), ('dm_permits','floor_area',80)")
    # ---- raw landing -----------------------------------------------------------------------------------------------------------------
    con.execute(f"""create or replace table dm_building_permits as
        select try_cast(application_id as bigint) as application_id, application_status_english as status_en, application_status_arabic as status_ar,
               try_cast(application_submission_date as date) as submitted, application_type_english as type_en, application_type_arabic as type_ar,
               try_cast(approval_date as date) as approval_date, try_cast(building_count as integer) as building_count, nullif(building_type, '') as building_type,
               parcel_id as parcel_id_raw, try_cast(round(try_cast(parcel_id as double)) as bigint) as parcel_id,
               case when try_cast(permit_date as date) between date '1970-01-01' and date '2027-12-31' then try_cast(permit_date as date) end as permit_date,
               nullif(permit_no, '') as permit_no, try_cast(permit_renewal_date as date) as renewal_date, nullif(project_no, '') as project_no,
               try_cast(total_area as double) as total_area_sqm, load_timestamp, '{extract}' as extract_date
        from read_csv('{csvp}', header=true, all_varchar=true)""")
    n = con.execute("select count(*), count(distinct parcel_id), count(permit_date) from dm_building_permits").fetchone()
    print(f"  landed {n[0]:,} applications · {n[1]:,} parcels · {n[2]:,} with a permit date")
    # ---- per-parcel roll-up ------------------------------------------------------------------------------------------------------------
    con.execute(f"""create or replace table dm_parcel_permits as
        with p as (select * from dm_building_permits where parcel_id is not null and parcel_id > 0),
             delivered as (select * from p where status_en = 'Permit Delivered' and permit_date is not null),
             newb as (select * from delivered where type_en = 'Final-New Building'),
             last_any as (select parcel_id, arg_max(type_en, permit_date) as last_permit_type, max(permit_date) as last_permit_date, arg_max(permit_no, permit_date) as last_permit_no from delivered group by parcel_id),
             last_new as (select parcel_id, max(permit_date) as new_building_permit_date, arg_max(permit_no, permit_date) as new_building_permit_no, arg_max(building_type, permit_date) as new_building_type,
                                 sum(building_count) as buildings_permitted, sum(total_area_sqm) as area_permitted_sqm, arg_max(project_no, permit_date) as project_no, count(*) as new_building_permits from newb group by parcel_id),
             act as (select parcel_id, count(*) as recent_works from delivered where type_en in ('Final-New Building','Final-Adjustment/Addition') and permit_date >= date '{extract}' - interval {ACTIVE_MONTHS} month group by parcel_id),
             cnt as (select parcel_id, count(*) as applications, count(*) filter (where status_en = 'Permit Delivered') as permits_delivered, mode(building_type) as building_type from p group by parcel_id)
        select c.parcel_id, c.applications, c.permits_delivered, c.building_type, a.last_permit_type, a.last_permit_date, a.last_permit_no,
               ln.new_building_permit_date, ln.new_building_permit_no, ln.new_building_type, ln.buildings_permitted, ln.area_permitted_sqm, ln.project_no, ln.new_building_permits,
               coalesce(act.recent_works, 0) as recent_works, coalesce(act.recent_works, 0) > 0 as construction_signal
        from cnt c left join last_any a using (parcel_id) left join last_new ln using (parcel_id) left join act using (parcel_id)""")
    m = con.execute("select count(*), count(*) filter (where construction_signal), count(new_building_permit_date) from dm_parcel_permits").fetchone()
    print(f"  parcels rolled up: {m[0]:,} · with a new-building permit: {m[2]:,} · construction signal (works permitted in the last {ACTIVE_MONTHS} months): {m[1]:,}")
    # ---- links to our entities ------------------------------------------------------------------------------------------------------------
    con.execute("""create or replace temp view plot_key as
        select distinct plot_no, district, try_cast(round(try_cast(parcel_id as double)) as bigint) as parcel_key from plot where parcel_id is not null""")
    con.execute("""create or replace temp view bld_key as
        select duid, district, parcel_id as parcel_form,
               case when parcel_id like '%-%' then try_cast(split_part(parcel_id, '-', 1) as bigint) * 10000 + try_cast(split_part(parcel_id, '-', 2) as bigint)
                    else try_cast(parcel_id as bigint) end as parcel_key
        from building_parcel_dm""")
    lp = con.execute("select count(distinct k.plot_no) from plot_key k join dm_parcel_permits d on d.parcel_id = k.parcel_key").fetchone()[0]
    lb = con.execute("select count(distinct k.duid) from bld_key k join dm_parcel_permits d on d.parcel_id = k.parcel_key").fetchone()[0]
    print(f"  matched: {lp:,} of {con.execute('select count(distinct plot_no) from plot_key').fetchone()[0]:,} DLD plots · {lb:,} of {con.execute('select count(*) from bld_key').fetchone()[0]:,} buildings with a DM parcel")
    # ---- evidence -----------------------------------------------------------------------------------------------------------------------
    ev = []
    def add(etype, eidv, attr, value, role, rec, method, conf, valid_from, status="ACCEPTED"):
        ev.append((eid(eidv, attr, str(value), "dm_permits", rec), RUN, etype, eidv, attr, str(value), role, "dm_permits", str(rec), method, conf, None, 0.0, True, NOW, status, SCHEMA, RESOLVER, valid_from, None))
    rows = con.execute("""select 'building' as et, k.duid as id, d.* from bld_key k join dm_parcel_permits d on d.parcel_id = k.parcel_key
                          union all select 'plot', k.plot_no, d.* from plot_key k join dm_parcel_permits d on d.parcel_id = k.parcel_key""").fetchall()
    cols = [c[0] for c in con.description]
    for r in rows:
        x = dict(zip(cols, r)); et, idv = x["et"], x["id"]; rec = x["last_permit_no"] or x["parcel_id"]
        if x["last_permit_date"]:
            add(et, idv, "permit_last", f"{x['last_permit_type']} · {x['last_permit_date']}", "EVENT", rec, "latest permit delivered on the DM parcel (building permits register)", 0.9, str(x["last_permit_date"]))
        if x["new_building_permit_date"]:
            add(et, idv, "new_building_permit", str(x["new_building_permit_date"]), "EVENT", x["new_building_permit_no"] or rec, "latest Final-New Building permit delivered on the parcel", 0.9, str(x["new_building_permit_date"]))
            if x["new_building_type"]: add(et, idv, "permit_building_type", x["new_building_type"], "CLASS", x["new_building_permit_no"] or rec, "building type on the new-building permit", 0.85, str(x["new_building_permit_date"]))
            if x["buildings_permitted"]: add(et, idv, "permit_building_count", int(x["buildings_permitted"]), "MEASURE", x["new_building_permit_no"] or rec, "buildings on new-building permits for the parcel", 0.85, str(x["new_building_permit_date"]))
            if x["area_permitted_sqm"]: add(et, idv, "permit_total_area_sqm", round(float(x["area_permitted_sqm"]), 1), "MEASURE", x["new_building_permit_no"] or rec, "total area on new-building permits for the parcel", 0.8, str(x["new_building_permit_date"]))
        add(et, idv, "construction_signal", "active" if x["construction_signal"] else "none", "STATUS", x["parcel_id"], f"new-building or addition permit delivered within {ACTIVE_MONTHS} months of the {extract} extract", 0.75, extract, "ACCEPTED" if x["construction_signal"] else "DISCOVERED")
    con.execute("create or replace temp table ev_new as select * from evidence limit 0")
    con.executemany("insert into ev_new values (" + ",".join("?" * 20) + ")", ev)
    added = con.execute("insert into evidence select n.* from ev_new n where not exists (select 1 from evidence e where e.evidence_id = n.evidence_id)").fetchone()[0]
    print(f"  evidence rows: {len(ev):,} prepared · {added:,} new in the ledger")
    # ---- views -------------------------------------------------------------------------------------------------------------------------
    con.execute("""create or replace view v_plot_permits as
        select p.plot_no, p.name, p.district, p.master, d.* exclude (parcel_id), d.parcel_id as dm_parcel_id from plot p
        join dm_parcel_permits d on d.parcel_id = try_cast(round(try_cast(p.parcel_id as double)) as bigint)""")
    con.execute("""create or replace view v_building_permits as
        select b.duid, b.district, b.display_name, b.height_m, b.storeys, k.parcel_id as dm_plot, d.applications, d.permits_delivered, d.building_type, d.last_permit_type, d.last_permit_date,
               d.new_building_permit_date, d.new_building_type, d.buildings_permitted, d.area_permitted_sqm, d.project_no, d.recent_works, d.construction_signal
        from building b join building_parcel_dm k on k.duid = b.duid
        join dm_parcel_permits d on d.parcel_id = case when k.parcel_id like '%-%' then try_cast(split_part(k.parcel_id, '-', 1) as bigint) * 10000 + try_cast(split_part(k.parcel_id, '-', 2) as bigint) else try_cast(k.parcel_id as bigint) end""")
    con.execute("create or replace view v_construction_signal as select district, count(*) as buildings_with_permits, count(*) filter (where construction_signal) as active_works, max(last_permit_date) as latest_permit from v_building_permits group by district order by active_works desc")
    # ---- run row (whatever columns the run table has) --------------------------------------------------------------------------------------
    try:
        rc = [c[0] for c in con.execute("describe run").fetchall()]
        vals = {"run_id": RUN, "started": NOW, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "script": "graph_load_dm_permits.py", "label": "dm building permits slice", "notes": f"{n[0]} applications, {added} evidence rows", "schema_version": SCHEMA, "resolver_version": RESOLVER}
        use = [c for c in rc if c in vals]
        con.execute(f"insert into run ({', '.join(use)}) values ({', '.join('?' * len(use))})", [vals[c] for c in use])
    except Exception as ex:
        print("  run row skipped:", str(ex)[:100])
    for row in con.execute("select * from v_construction_signal limit 12").fetchall(): print("   ", row)
    con.close(); print(f"done in {round(time.time() - t0)} s - run {RUN}; now: python scripts/graph_golden_check.py")


if __name__ == "__main__":
    main()
