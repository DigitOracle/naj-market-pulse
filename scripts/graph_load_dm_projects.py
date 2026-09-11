"""graph_load_dm_projects.py -- the DM PROJECT thread of the truth store: what is actually being built, by whom, to when (11 Sep 2026).

Sources (data.dubai registers already on disk, 2026-08-31 extracts):
  data/registers/project_information/*.csv            481k DM projects: parcel, status Open/Closed, permit / work-start / expected / completion dates, contractor, consultant
  data/registers/project_building_information/*.csv   209k buildings on those projects: DM building_id, construction stage, building cost
  data/raw_downloads/building_floor_level_information_*.csv   4.2M floor rows for 484k DM buildings: floor number, units per floor, usage

What lands:
  dm_project, dm_project_building, dm_building_floor (raw, typed), dm_building_floors (per DM building: floors, units, usage mix),
  dm_parcel_projects (per DM parcel: projects, open projects, latest project + stage + dates + contractor + consultant, floors, units,
  construction_status), evidence per building / plot (source dm_project), views v_parcel_projects, v_building_construction.
Links: plot.parcel_id and building_parcel_dm (same key rule as graph_load_dm_permits.py). Run after that loader; then the gate.
"""
import glob, hashlib, os, time
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb"); REG = os.path.join(ROOT, "data", "registers"); RAW = os.path.join(ROOT, "data", "raw_downloads")
NOW = time.strftime("%Y-%m-%dT%H:%M:%S"); RUN = time.strftime("%Y%m%d-%H%M%S") + "-dmprojects"; SCHEMA = "1.2"; RESOLVER = "identity-2026-09-08-rolerule"
EXTRACT = "2026-08-31"


def connect_writer(path, tries=20, wait=30):
    for k in range(tries):
        try: return duckdb.connect(path)
        except duckdb.IOException as e:
            if "being used by another process" not in str(e) or k == tries - 1: raise
            print(f"  truth store busy - waiting {wait}s ({k+1}/{tries})"); time.sleep(wait)


def eid(entity_id, attribute, value, source, rec):
    return hashlib.sha1(f"{entity_id}|{attribute}|{value}|{source}|{rec}".encode("utf-8")).hexdigest()[:24]


def g(pattern):
    fs = sorted(glob.glob(pattern)); assert fs, pattern
    return [f.replace("\\", "/") for f in fs]


def main():
    t0 = time.time(); con = connect_writer(DB)
    con.execute("delete from source_authority where source_id = 'dm_project'")
    con.execute("insert into source_authority values ('dm_project','construction_status',95), ('dm_project','construction_stage',95), ('dm_project','expected_completion',90), ('dm_project','contractor',95), ('dm_project','consultant',95), ('dm_project','floors',90), ('dm_project','units',85)")
    # ---- raw landing ---------------------------------------------------------------------------------------------------------------
    con.execute("""create or replace table dm_project as
        select try_cast(round(try_cast(project_no as double)) as bigint) as project_no, try_cast(round(try_cast(parcel_id as double)) as bigint) as parcel_id,
               project_status_english as status, applicanttype as applicant_type, consultant_english as consultant, consultant_license_no, contractor_english as contractor, contractor_license_no,
               try_cast(permit_date as date) as permit_date, try_cast(work_start_date as date) as work_start,
               case when try_cast(expected_completion_date as date) > date '1951-01-01' then try_cast(expected_completion_date as date) end as expected_completion,
               case when try_cast(project_completion_date as date) > date '1951-01-01' then try_cast(project_completion_date as date) end as completed,
               try_cast(project_creation_date as date) as created, related_entity_name_en as related_entity
        from read_csv(?, header=true, all_varchar=true, union_by_name=true)""", [g(os.path.join(REG, "project_information", "*.csv"))])
    con.execute("""create or replace table dm_project_building as
        select try_cast(round(try_cast(building_id as double)) as bigint) as building_id, try_cast(round(try_cast(project_no as double)) as bigint) as project_no,
               nullif(trim(building_construction_stage_e), '') as stage, try_cast(building_cost as double) as building_cost
        from read_csv(?, header=true, all_varchar=true, union_by_name=true)""", [g(os.path.join(REG, "project_building_information", "*.csv"))])
    con.execute("""create or replace table dm_building_floor as
        select try_cast(round(try_cast(building_id as double)) as bigint) as building_id, try_cast(round(try_cast(floor_no as double)) as integer) as floor_no, floor_type_english as floor_type,
               try_cast(round(try_cast(no_of_units as double)) as integer) as units, usage_description_english as usage, try_cast(usages_area as double) as usage_area_sqm
        from read_csv(?, header=true, all_varchar=true, union_by_name=true)""", [g(os.path.join(RAW, "building_floor_level_information_*.csv"))])
    con.execute("""create or replace table dm_building_floors as
        select building_id, max(floor_no) filter (where floor_type = 'Floor') as floors, count(distinct floor_no) as levels, sum(units) as units,
               mode(usage) as main_usage, sum(usage_area_sqm) as usage_area_sqm from dm_building_floor where building_id is not null group by building_id""")
    n = [con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("dm_project", "dm_project_building", "dm_building_floor", "dm_building_floors")]
    print(f"  landed: projects {n[0]:,} · project buildings {n[1]:,} · floor rows {n[2]:,} · DM buildings with floors {n[3]:,}")
    # ---- per-parcel roll-up ----------------------------------------------------------------------------------------------------------
    con.execute("""create or replace table dm_parcel_projects as
        with pj as (select p.*, (select count(*) from dm_project_building b where b.project_no = p.project_no) as bld_n,
                           (select arg_max(stage, building_cost) from dm_project_building b where b.project_no = p.project_no and stage is not null) as stage,
                           (select max(f.floors) from dm_project_building b join dm_building_floors f using (building_id) where b.project_no = p.project_no) as floors,
                           (select sum(f.units) from dm_project_building b join dm_building_floors f using (building_id) where b.project_no = p.project_no) as units,
                           (select mode(f.main_usage) from dm_project_building b join dm_building_floors f using (building_id) where b.project_no = p.project_no) as main_usage
                    from dm_project p where p.parcel_id is not null and p.parcel_id > 0),
             latest as (select parcel_id, arg_max(project_no, coalesce(permit_date, created)) as project_no from pj group by parcel_id),
             latest_open as (select parcel_id, arg_max(project_no, coalesce(permit_date, created)) as project_no from pj where status = 'Open' group by parcel_id)
        select c.parcel_id, c.projects, c.open_projects, l.project_no as latest_project, lp.status as latest_status, lp.permit_date, lp.work_start, lp.expected_completion, lp.completed,
               lp.contractor, lp.consultant, lp.stage, lp.bld_n as buildings_on_project, lp.floors, lp.units, lp.main_usage,
               lo.project_no as open_project, coalesce(np.new_building_permit_date, date '1900-01-01') as new_building_permit_date,
               -- an "Open" DM project alone is not construction: towers keep adjustment projects open for years. Works are called only on
               -- stage evidence, or on a new-building permit delivered within 3 years of the extract with the project still open.
               case when lo.project_no is not null and (coalesce(lp.stage, '') like 'Work completed%' or coalesce(lp.stage, '') like 'Existing building%') then 'completed'
                    when lo.project_no is not null and lp.stage is not null then 'under construction - ' || trim(lp.stage)
                    when lo.project_no is not null and np.new_building_permit_date >= date '2023-09-01' then 'under construction - new building permit ' || cast(np.new_building_permit_date as varchar)
                    when lo.project_no is not null then 'open project - works not evidenced'
                    else 'completed' end as construction_status
        from (select parcel_id, count(*) as projects, count(*) filter (where status = 'Open') as open_projects from pj group by parcel_id) c
        join latest l using (parcel_id) join pj lp on lp.project_no = l.project_no and lp.parcel_id = c.parcel_id
        left join latest_open lo using (parcel_id)
        left join (select parcel_id, new_building_permit_date from dm_parcel_permits) np using (parcel_id)""")
    m = con.execute("select count(*), count(*) filter (where open_project is not null), count(*) filter (where construction_status like 'under construction%') from dm_parcel_projects").fetchone()
    print(f"  parcels: {m[0]:,} · with an open project: {m[1]:,} · under construction by stage: {m[2]:,}")
    # ---- links ---------------------------------------------------------------------------------------------------------------------------
    con.execute("create or replace temp view plot_key as select distinct plot_no, district, try_cast(round(try_cast(parcel_id as double)) as bigint) as parcel_key from plot where parcel_id is not null")
    con.execute("""create or replace temp view bld_key as select duid, district, case when parcel_id like '%-%' then try_cast(split_part(parcel_id, '-', 1) as bigint) * 10000 + try_cast(split_part(parcel_id, '-', 2) as bigint) else try_cast(parcel_id as bigint) end as parcel_key from building_parcel_dm""")
    rows = con.execute("""select 'building' as et, k.duid as id, d.* from bld_key k join dm_parcel_projects d on d.parcel_id = k.parcel_key
                          union all select 'plot', k.plot_no, d.* from plot_key k join dm_parcel_projects d on d.parcel_id = k.parcel_key""").fetchall()
    cols = [c[0] for c in con.description]; ev = []
    def add(et, idv, attr, value, role, rec, method, conf, valid_from, status="ACCEPTED"):
        ev.append((eid(idv, attr, str(value), "dm_project", rec), RUN, et, idv, attr, str(value), role, "dm_project", str(rec), method, conf, None, 0.0, True, NOW, status, SCHEMA, RESOLVER, valid_from, None))
    for r in rows:
        x = dict(zip(cols, r)); et, idv, rec = x["et"], x["id"], x["latest_project"]; vf = str(x["permit_date"] or EXTRACT)
        cs = x["construction_status"]; evidenced = cs == "completed" or cs.startswith("under construction - ")
        add(et, idv, "construction_status", cs, "STATUS", rec, "latest DM project on the parcel: stage evidence, or a new-building permit within 3 years while the project is open; an open project alone is not works", 0.9 if evidenced else 0.5, vf, "ACCEPTED" if evidenced else "DISCOVERED")
        if x["stage"]: add(et, idv, "construction_stage", x["stage"].strip(), "CLASS", rec, "construction stage of the costliest building on the latest project", 0.9, vf)
        if x["expected_completion"]: add(et, idv, "expected_completion", str(x["expected_completion"]), "EVENT", rec, "expected completion date on the latest DM project", 0.85, vf)
        if x["completed"]: add(et, idv, "project_completed", str(x["completed"]), "EVENT", rec, "completion date on the latest DM project", 0.9, vf)
        if x["contractor"]: add(et, idv, "contractor", x["contractor"].strip(), "PARTY", rec, "contractor on the latest DM project", 0.95, vf)
        if x["consultant"]: add(et, idv, "consultant", x["consultant"].strip(), "PARTY", rec, "consultant on the latest DM project", 0.95, vf)
        if x["floors"]: add(et, idv, "dm_floors", int(x["floors"]), "MEASURE", rec, "highest numbered floor across the project's buildings (DM floor-level register)", 0.9, vf)
        if x["units"]: add(et, idv, "dm_units", int(x["units"]), "MEASURE", rec, "units summed over the project's buildings (DM floor-level register)", 0.85, vf)
        if x["main_usage"]: add(et, idv, "dm_main_usage", x["main_usage"], "CLASS", rec, "most common floor usage across the project's buildings", 0.8, vf)
    con.execute("create or replace temp table ev_new as select * from evidence limit 0")
    con.executemany("insert into ev_new values (" + ",".join("?" * 20) + ")", ev)
    added = con.execute("insert into evidence select n.* from ev_new n where not exists (select 1 from evidence e where e.evidence_id = n.evidence_id)").fetchone()[0]
    lb = len({r[1] for r in rows if r[0] == "building"}); lp = len({r[1] for r in rows if r[0] == "plot"})
    print(f"  linked: {lb:,} buildings · {lp:,} plots · evidence rows {len(ev):,} prepared · {added:,} new in the ledger")
    # ---- views ---------------------------------------------------------------------------------------------------------------------------
    con.execute("""create or replace view v_parcel_projects as select p.plot_no, p.name, p.district, p.master, d.* from plot p
        join dm_parcel_projects d on d.parcel_id = try_cast(round(try_cast(p.parcel_id as double)) as bigint)""")
    con.execute("""create or replace view v_building_construction as
        select b.duid, b.district, b.display_name, b.height_m, b.storeys as storeys_model, d.floors as floors_dm, d.units as units_dm, d.construction_status, d.stage, d.expected_completion, d.completed, d.contractor, d.consultant, d.latest_project, d.open_projects
        from building b join building_parcel_dm k on k.duid = b.duid
        join dm_parcel_projects d on d.parcel_id = case when k.parcel_id like '%-%' then try_cast(split_part(k.parcel_id, '-', 1) as bigint) * 10000 + try_cast(split_part(k.parcel_id, '-', 2) as bigint) else try_cast(k.parcel_id as bigint) end""")
    try:
        rc = [c[0] for c in con.execute("describe run").fetchall()]
        vals = {"run_id": RUN, "started": NOW, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "script": "graph_load_dm_projects.py", "label": "dm project thread", "notes": f"{n[0]} projects, {added} evidence rows", "schema_version": SCHEMA, "resolver_version": RESOLVER}
        use = [c for c in rc if c in vals]; con.execute(f"insert into run ({', '.join(use)}) values ({', '.join('?' * len(use))})", [vals[c] for c in use])
    except Exception as ex:
        print("  run row skipped:", str(ex)[:100])
    print("  status mix on our buildings:", con.execute("select construction_status, count(*) from v_building_construction group by 1 order by 2 desc").fetchall())
    print("  storeys check (model vs DM floors, where both):", con.execute("select count(*), count(*) filter (where abs(storeys_model - floors_dm) <= 2) from v_building_construction where storeys_model is not null and floors_dm is not null").fetchone())
    con.close(); print(f"done in {round(time.time() - t0)} s - run {RUN}; now: python scripts/graph_golden_check.py")


if __name__ == "__main__":
    main()
