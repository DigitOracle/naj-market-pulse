"""Register keys: joins made on the numbers the registers publish, not on names (Data Spine, 14 Sep 2026).

The held-versus-mapped audit (13 Sep 2026) found 556 of 579 downloaded portal registers never read, and the few in use joined
by name. Five joins, each on a key a register itself carries:

  community        DLD area -> Municipality community number (lkp_areas.municipality_number) -> population, bus coverage and
                   DEWA move-ins (DEWA writes the community as "345-BURJ KHALIFA")
  sales_projects   our sales row -> the portal's copy of the same row -> project_number -> projects register -> project_id.
                   The portal id reads group-procedure-year-serial, ours procedure-serial-year; a pair counts only when the
                   price or the size agrees. Sales the portal copy does not hold yet link through the register's own
                   name -> number pairs. Checked against identity_match's name matches (data/identity/register_vs_name.csv).
  parcels          one parcel key, community x 10000 + plot, from the three spellings in the store ('6830847', '6830847.00',
                   '683-847'); the Municipality building summary (height, floors, completion) loaded on it
  service_charges  owners-association budgets (DLD oa_service_charges) on project_id: AED per sq ft per year
  makani           DEWA move-ins by Makani number -> Municipality entrance point -> nearest twin building (50 m). The open
                   entrance layer stops at 256 MiB at its source (124,244 points), so building coverage is partial.

Each job replaces its lake tables (lk_*) and views in one transaction and logs lk_join_log: keys in, keys matched, rate.
A rate under 80% of the job's last accepted run is HELD - nothing replaced, exit 4 - like every other contract.
Raw rows stay on this machine. The DEWA tables keep counts only: no nationality, no identity type.
Nothing here reaches her board: docs/GOV_DATA_METHODOLOGY.md section 5 still decides that.

  rent_projects    (15 Sep 2026) Ejari rent rows -> project_id by exact registered name within the rent's own DLD area; every rent
                   row -> area_id. sales_projects also gained lk_project_numbers: register extract + 2026 registrations, with a
                   name + area bridge to project_id used only while it agrees with the register on >= 99% (digital thread Q2/Q3/Q5)

  twin_bindings    (15 Sep 2026) register and sales bindings to twin footprints, keyed by duid + property_id, with a review view (Q6);
                   parcels also carries comm_num = parcel_key // 10000, checked against the DM summary and the land registry (Q7)

  project_spine    (15 Sep 2026) one project table (lk_d_project), one developer table (lk_d_developer) and the board developers as groups
                   of DLD developer entities in the shared crosswalk lk_xref (digital thread P1.1 + P1.2)
  sheet_units      (15 Sep 2026) availability-sheet projects -> project_id and sheet units -> register property_id, as lk_xref rows (P1.4)
  place_spine      (16 Sep 2026) one table per numbered place - area, Municipality community, parcel with its split lineage, register
                   building (digital thread P2.1 + P2.2)
  sub_communities  (16 Sep 2026) each sub-community card keyed to the DLD project it names, so its id stops being a list position (P2.3)
  stations         (16 Sep 2026) RTA metro and tram stations by the RTA's own location id, and the sales register's nearest-station
                   name keyed to them (P2.5)
  districts        (16 Sep 2026) the twin's districts as a grouping over the registers' areas and communities, derived from their own
                   sub-community cards - never a join key (P2.4)

Usage: python scripts/register_joins.py [all | community parcels service_charges sales_projects rent_projects twin_bindings project_spine
       sheet_units makani resident_mix building_activity] [--dry]
"""
import csv, datetime as dt, json, glob, os, re, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lake
import nationality_regions

DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
MANIFEST = os.path.join(DD, "MANIFEST.json")
ENTRANCES = os.path.join(ROOT, "data", "dm", "entrances.csv")
REVIEW = os.path.join(ROOT, "data", "identity", "register_vs_name.csv")
HOLD_RATIO = 0.8
NEAR_M = 50
CELL = 0.0005                          # degrees, about 55 m: a 3 x 3 block of cells always covers the 50 m search

LOG_DDL = """create table if not exists lk_join_log (run_at timestamp, job varchar, keys_in bigint, keys_matched bigint,
             rate double, rows_in bigint, status varchar, note varchar)"""


def register_files(name, pattern):
    """All parts of the newest finished extract. The manifest names a download's files only once it has finished, so a pull
    in progress is never read half-written; without a manifest entry, the newest dated files on disk."""
    try:
        e = json.load(open(MANIFEST, encoding="utf-8")).get(name) or {}
    except (OSError, ValueError):
        e = {}
    listed = [os.path.join(ROOT, p) for p in (e.get("files") or ([e["file"]] if e.get("file") else []))]
    # a workbook part is read through its CSV copy (datadubai_pull_all.xlsx_to_csv); a part with no CSV fails loudly, never skipped
    listed = [os.path.splitext(p)[0] + ".csv" if p.lower().endswith(".xlsx") else p for p in listed]
    if listed and all(os.path.exists(p) for p in listed):
        return listed
    missing = [os.path.basename(p) for p in listed if not os.path.exists(p)]
    if listed and any(p.lower().endswith(".csv") and "__part" in p for p in listed) and missing:
        raise RuntimeError("%s: part(s) %s not on disk as CSV - pull the register again" % (name, ", ".join(missing)))
    found = sorted(glob.glob(os.path.join(DD, pattern)))
    if not found:
        raise RuntimeError("no file for %s (%s)" % (name, pattern))
    stamp = max(re.search(r"__(\d{4}-\d{2}-\d{2})", os.path.basename(p)).group(1) for p in found)
    return [p for p in found if "__" + stamp in os.path.basename(p)]


def read(paths):
    return "read_csv([%s], all_varchar=true, header=true, union_by_name=true, ignore_errors=true)" % ", ".join(
        "'%s'" % lake._p(p) for p in paths)


# 15 Sep 2026 (digital thread Q1): the number and parcel-key normalisers moved to scripts/keys.py so every script joins register
# numbers the same way; the names num / parcel_key are kept here for the jobs below.
from keys import num_sql as num, parcel_key_sql as parcel_key, name_norm_sql  # noqa: E402


def one(con, sql):
    return con.execute(sql).fetchone()


def pct(a, b):
    return "%s of %s (%.1f%%)" % (format(a, ","), format(b, ","), 100.0 * a / b if b else 0.0)


# --- the five jobs: each stages temp tables outside the lake transaction and returns what to publish ------------------------

def job_community(con):
    L = read(register_files("lkp_areas", "dld__lkp_areas__*.csv"))
    P = read(register_files("estimated_population_by_community", "estimated_population_by_community__*.csv"))
    B = read(register_files("bus_network_coverage", "rta__bus_network_coverage__*.csv"))
    C = read(register_files("customers_master_data", "customers_master_data__*.csv"))
    con.execute("""create or replace temp table j_area as
        select try_cast(area_id as bigint) area_id, trim(name_en) area_name_en, trim(name_ar) area_name_ar, %s comm_num from %s"""
                % (num("municipality_number"), L))
    con.execute("""create or replace temp table j_pop as
        select %s comm_num, try_cast("Year" as int) population_year, %s population, trim("Sector & Community") population_name
        from %s where %s is not null
        qualify row_number() over (partition by %s order by try_cast("Year" as int) desc) = 1"""
                % (num('"Code"'), num('"Value"'), P, num('"Code"'), num('"Code"')))
    con.execute("""create or replace temp table j_bus as
        select %s comm_num, trim(community_name) bus_name, %s bus_population, %s bus_accessible,
               try_cast(geographic_coverage as double) bus_coverage_pct, %s bus_stops, %s makani_points, report_date bus_report_date
        from %s where %s is not null"""
                % (num("community_num"), num("population"), num("accessible_population"), num("nume_of_bus_stops"),
                   num("makani_points"), B, num("community_num")))
    con.execute("""create or replace temp table j_dewa as
        select try_cast(regexp_extract(community, '^ *([0-9]+)-', 1) as bigint) comm_num, count(*) move_ins,
               count(*) filter (where date_of_move_in >= '2024-01-01' and date_of_move_in < '2025-01-01') move_ins_2024,
               count(*) filter (where date_of_move_in >= '2025-01-01' and date_of_move_in < '2026-01-01') move_ins_2025,
               max(date_of_move_in) last_move_in
        from %s group by 1""" % C)
    con.execute("""create or replace temp table j_comm as
        with keys as (select try_cast(comm_num as bigint) comm_num from dm_community union select comm_num from j_pop
                      union select comm_num from j_bus union select comm_num from j_area union select comm_num from j_dewa),
             areas as (select comm_num, count(*) dld_areas, list(area_id order by area_id) dld_area_ids,
                              string_agg(area_name_en, ' | ' order by area_id) dld_area_names
                       from j_area where comm_num is not null group by 1)
        select k.comm_num, d.name_en dm_name_en, d.name_ar dm_name_ar, d.lon, d.lat, coalesce(a.dld_areas, 0) dld_areas,
               a.dld_area_ids, a.dld_area_names, p.population_name, p.population_year, p.population,
               b.bus_name, b.bus_population, b.bus_accessible, b.bus_coverage_pct, b.bus_stops, b.makani_points, b.bus_report_date,
               w.move_ins dewa_move_ins, w.move_ins_2024 dewa_move_ins_2024, w.move_ins_2025 dewa_move_ins_2025,
               w.last_move_in dewa_last_move_in
        from keys k
        left join (select try_cast(comm_num as bigint) comm_num, name_en, name_ar, lon, lat from dm_community) d using (comm_num)
        left join areas a using (comm_num) left join j_pop p using (comm_num) left join j_bus b using (comm_num)
        left join j_dewa w using (comm_num)
        where k.comm_num is not null""")
    # The names people use. The Municipality calls Downtown "BURJ KHALIFA" and JVC "AL BARSHA SOUTH FOURTH"; the Land Department's
    # sales register names each sale's master development (Kendall, 14 Sep: "not the names a layman would know"). Sales since 2015
    # per community and master development, through the register's own area_id -> community number.
    T = read(register_files("transactions", "dld__transactions__*.csv"))
    con.execute("""create or replace temp table j_names as
        select a.comm_num, regexp_replace(trim(t.master_project_en), ' +', ' ', 'g') as master_project, count(*) as sales
        from %s t join j_area a on a.area_id = %s
        where a.comm_num is not null and nullif(trim(t.master_project_en), '') is not null and t.instance_date >= '2015-01-01'
        group by 1, 2""" % (T, num("t.area_id")))
    con.execute("""create or replace temp table j_names as
        select *, cast(round(100.0 * sales / sum(sales) over (partition by comm_num)) as int) as share_pct from j_names""")
    dm = "(select try_cast(comm_num as bigint) c from dm_community)"
    named = one(con, "select count(distinct comm_num) from j_names where share_pct >= 15")[0]
    areas, areas_keyed = one(con, "select count(*), count(*) filter (where comm_num in %s) from j_area" % dm)
    pops, pops_keyed = one(con, "select count(*), count(*) filter (where comm_num in %s) from j_pop" % dm)
    buses, buses_keyed = one(con, "select count(*), count(*) filter (where comm_num in %s) from j_bus" % dm)
    dewa, dewa_keyed = one(con, "select sum(move_ins), sum(move_ins) filter (where comm_num in %s) from j_dewa" % dm)
    shared = one(con, "select count(*) from j_comm where dld_areas > 1")[0]
    sales, sales_keyed = one(con, """select count(*), count(a.comm_num) from dld_transactions_now t
                                     left join j_area a on lower(a.area_name_en) = lower(trim(t.AREA_EN))""")
    return {"tables": [("lk_area_community", "select * from j_area"), ("lk_community", "select * from j_comm"),
                       ("lk_community_names", "select * from j_names")],
            "keys_in": areas, "keys_matched": areas_keyed, "rows_in": areas,
            "note": "population %d/%d, bus %d/%d on the community number" % (pops_keyed, pops, buses_keyed, buses),
            "report": ["DLD areas carrying a Municipality community number: " + pct(areas_keyed, areas),
                       "population communities on the number: " + pct(pops_keyed, pops),
                       "bus-coverage communities on the number: " + pct(buses_keyed, buses),
                       "DEWA move-ins whose community number is a Municipality community: " + pct(dewa_keyed or 0, dewa or 0),
                       "communities holding more than one DLD area: %d" % shared,
                       "communities with a market name (a master development holding 15%%+ of their sales since 2015): %d" % named,
                       "current sales rows whose area name reaches a community number: " + pct(sales_keyed, sales)]}


def job_parcels(con):
    B = read(register_files("building_summary_information", "dm__building_summary_information__*.csv"))
    h = "try_cast(building_height as double)"
    con.execute("""create or replace temp table j_dm as
        select try_cast(building_id as bigint) building_id, %s parcel_key, try_cast(community_no as bigint) community_no, %s project_no,
               case when %s > 0 and %s < 900 then %s end height_m, nullif(regexp_replace(trim(building_floor_height), ' +', '', 'g'), '') floor_config,
               try_cast(typical_floors_count as int) typical_floors, try_cast(no_of_lifts as int) lifts,
               try_cast(indoor_car_parking as int) indoor_parking, try_cast(outdoor_car_parking as int) outdoor_parking,
               try_cast(building_total_area as double) total_area_sqm, try_cast(plot_area as double) plot_area_sqm,
               try_cast(substr(building_completion_date, 1, 10) as date) completion_date,
               try_cast(try_cast(building_construction_year as double) as int) construction_year,
               try_cast(substr(building_permitted_date, 1, 10) as date) permitted_date,
               try_cast(substr(building_demolition_date, 1, 10) as date) demolition_date,
               nullif(trim(building_status_english), '') status, nullif(trim(building_type_english), '') building_type,
               nullif(trim(building_usages_english), '') usages, nullif(trim(community_name_english), '') community_name,
               try_cast(no_of_buildings_on_plot as int) buildings_on_plot, nullif(trim(permit_no), '') permit_no
        from %s""" % (parcel_key("parcel_id"), num("project_no"), h, h, h, B))
    sources = [("plot", "parcel_id"), ("building_parcel_dm", "parcel_id"), ("dm_address_parcel", "plot_no"), ("dm_parcel_permits", "parcel_id")]
    con.execute("create or replace temp table j_keys as " + " union all ".join(
        "select distinct '%s' as source, trim(cast(%s as varchar)) as raw, %s as parcel_key from %s where %s is not null"
        % (t, c, parcel_key(c), t, c) for t, c in sources))
    # 15 Sep 2026 (digital thread Q7): a parcel key IS community x 10000 + plot, so every parcel carries its Municipality community
    # number without a spatial join: comm_num = parcel_key // 10000. Checked below against the DM building summary's own community_no
    # and against the DLD land registry's community (munc_zip_code).
    for t in ("j_dm", "j_keys"):
        con.execute("alter table %s add column comm_num bigint" % t)
        con.execute("update %s set comm_num = parcel_key // 10000 where parcel_key is not null" % t)
    report, twin_in, twin_hit = [], 0, 0
    for t, _ in sources:
        raw, keyed, before, after = one(con, """select count(*), count(parcel_key),
                count(*) filter (where raw in (select cast(parcel_key as varchar) from j_dm)),
                count(*) filter (where parcel_key in (select parcel_key from j_dm)) from j_keys where source = '%s'""" % t)
        report.append("%-20s %s distinct values, %s keyed; reach the building summary: before %s, after %s"
                      % (t, format(raw, ","), format(keyed, ","), format(before, ","), format(after, ",")))
        if t in ("plot", "building_parcel_dm"):
            twin_in += keyed
            twin_hit += after
    dash, dash_hit, dash_same = one(con, """select count(*), count(d.parcel_key), count(*) filter (where k.parcel_key // 10000 = d.community_no)
        from (select distinct raw, parcel_key from j_keys where regexp_matches(raw, '^[0-9]+-[0-9]+$')) k
        left join (select distinct parcel_key, community_no from j_dm) d using (parcel_key)""")
    report.append("the 'community-plot' spelling: %s reach the summary, %s with the same community number"
                  % (pct(dash_hit, dash), format(dash_same, ",")))
    rows, parcels, heights = one(con, "select count(*), count(distinct parcel_key), count(height_m) from j_dm")
    report.append("Municipality buildings: %s on %s parcels, %s with a height" % (format(rows, ","), format(parcels, ","), format(heights, ",")))
    both, same = one(con, "select count(*), count(*) filter (where comm_num = community_no) from j_dm where comm_num is not null and community_no is not null")
    report.append("community from the parcel key (parcel_key // 10000) = the building summary's community_no: " + pct(same, both))
    try:
        LR = read(register_files("land_registry", "dld__land_registry__*.csv"))
        # the land registry's munc_zip_code is the community number (683 for parcel 6836248); munc_number is the plot (6248)
        lboth, lsame = one(con, """select count(*), count(*) filter (where k // 10000 = m) from (select %s k, %s m from %s)
                                   where k is not null and m is not null""" % (parcel_key("parcel_id"), num("munc_zip_code"), LR))
        report.append("community from the parcel key = the DLD land registry's community (munc_zip_code): " + pct(lsame, lboth))
    except Exception as e:
        report.append("land registry community check skipped: %s" % str(e)[:120])
    twin = """select bp.duid, bp.district, k.parcel_key, k.comm_num, d.building_id dm_building_id, d.height_m dm_height_m, b.height_m twin_height_m,
                     d.typical_floors dm_typical_floors, b.storeys twin_storeys, d.floor_config, d.completion_date, d.status,
                     d.building_type, d.usages, d.buildings_on_plot, bp.dist_m
              from building_parcel_dm bp
              join lk_parcel_keys k on k.source = 'building_parcel_dm' and k.raw = trim(cast(bp.parcel_id as varchar))
              join lk_dm_buildings d on d.parcel_key = k.parcel_key
              left join building b on b.duid = bp.duid"""
    plots = """select p.plot_no, p.name, p.district, p.master, k.parcel_key, k.comm_num, d.building_id dm_building_id, d.height_m, d.typical_floors,
                      d.floor_config, d.completion_date, d.status, d.usages
               from plot p
               join lk_parcel_keys k on k.source = 'plot' and k.raw = trim(cast(p.parcel_id as varchar))
               join lk_dm_buildings d on d.parcel_key = k.parcel_key"""
    return {"tables": [("lk_dm_buildings", "select * from j_dm"), ("lk_parcel_keys", "select * from j_keys")],
            "views": [("v_twin_building_dm", twin), ("v_plot_dm_buildings", plots)],
            "keys_in": twin_in, "keys_matched": twin_hit, "rows_in": rows,
            "note": "twin-facing parcel keys (plot, building_parcel_dm) reaching the building summary", "report": report}


def job_service_charges(con):
    O = read(register_files("oa_service_charges", "dld__oa_service_charges__*.csv"))
    PR = read(register_files("projects", "dld__projects__*.csv"))
    con.execute("""create or replace temp table j_sc as
        select try_cast(budget_year as int) budget_year, nullif(%s, -1) project_id, nullif(trim(project_name), '') project_name,
               nullif(%s, -1) master_community_id, nullif(trim(master_community_name_en), '') master_community,
               nullif(trim(management_company_name_en), '') management_company, %s property_group_id,
               nullif(trim(property_group_name_en), '') property_group, nullif(trim(usage_name_en), '') usage,
               nullif(trim(service_category_name_en), '') service_category, try_cast(service_cost as double) aed_per_sqft
        from %s""" % (num("project_id"), num("master_community_id"), num("property_group_id"), O))
    rows, projects, keyed = one(con, """select (select count(*) from j_sc), count(*), count(*) filter (where project_id in
        (select %s from %s)) from (select distinct project_id from j_sc where project_id is not null)""" % (num("project_id"), PR))
    years = con.execute("""select budget_year, count(distinct project_id) from j_sc where project_id is not null group by 1 order by 1""").fetchall()
    med = one(con, """select quantile_cont(r, 0.5), count(*) from (select project_id, budget_year, property_group_id, sum(aed_per_sqft) r
        from j_sc where project_id is not null and usage = 'Residential' group by 1, 2, 3) where r > 0""")
    rate = """select project_id, any_value(project_name) project_name, budget_year, usage, property_group_id, any_value(property_group) property_group,
                     round(sum(aed_per_sqft), 2) aed_per_sqft_year, count(*) categories, any_value(management_company) management_company
              from lk_service_charges where project_id is not null group by project_id, budget_year, usage, property_group_id"""
    latest = """select * from v_service_charge_rate
                qualify row_number() over (partition by project_id, usage, property_group_id order by budget_year desc) = 1"""
    return {"tables": [("lk_service_charges", "select * from j_sc")],
            "views": [("v_service_charge_rate", rate), ("v_service_charge_latest", latest)],
            "keys_in": projects, "keys_matched": keyed, "rows_in": rows, "note": "projects found in the projects register",
            "report": ["budget lines: %s" % format(rows, ","),
                       "projects on project_id in the projects register: " + pct(keyed, projects),
                       "projects per budget year: " + ", ".join("%s %d" % y for y in years),
                       "residential charge, median of %s project-year-group totals: %.2f AED per sq ft a year" % (format(med[1], ","), med[0] or 0)]}


def project_numbers(con):
    """Digital thread Q2 + Q3 (15 Sep 2026): one table of every DLD project number we hold, with its project_id where one can be
    established, and its developer number.

      numbers      the projects register extract (dld__projects, 3,039 rows, extract 6 Jul 2026 - the newest the portal holds)
                   + the DLD projects CSV of 2026 registrations (data/projects-YYYY-MM-DD.csv, numbers up to 4557) the extract lacks
      project_id   the register's own id; else a bridge: the number's English project name + area_id (from the portal sales rows
                   that carry the number, and from the 2026 CSV) matched exactly to ONE project_id in the buildings, land and units
                   registers. The bridge is used only when it agrees with the register on >= 99% of the numbers both hold.
      developer    the register's developer_number, else the 2026 CSV's

    Leaves temp table j_projects (project_number, project_id, developer_number, project_id_method, number_source) and returns report
    lines. Needs temp table j_portal."""
    PR = read(register_files("projects", "dld__projects__*.csv"))
    con.execute("""create or replace temp table j_reg_projects as
        select %s project_number, %s project_id, %s developer_number from %s where %s is not null""" % (
        num("project_number"), num("project_id"), num("developer_number"), PR, num("project_number")))
    lines = []
    y26 = sorted(glob.glob(os.path.join(ROOT, "data", "projects-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv")))
    if y26:
        con.execute("""create or replace temp table j_2026 as
            select %s project_number, %s developer_number, %s name_norm, upper(trim(AREA_EN)) area_up
            from read_csv('%s', all_varchar=true, header=true) where %s is not null""" % (
            num("PROJECT_NUMBER"), num("DEVELOPER_NUMBER"), name_norm_sql("PROJECT_EN"), lake._p(y26[-1]), num("PROJECT_NUMBER")))
    else:
        con.execute("create or replace temp table j_2026 (project_number bigint, developer_number bigint, name_norm varchar, area_up varchar)")
    parts = [p for name, pattern in (("buildings", "dld__buildings__*.csv"), ("land_registry", "dld__land_registry__*.csv"),
                                     ("units", "dld__units__*.csv")) for p in register_files(name, pattern)]
    con.execute("""create or replace temp table j_right as
        select name_norm, area_id, count(distinct project_id) ids, any_value(project_id) project_id from (
            select %s name_norm, %s area_id, %s project_id from %s)
        where name_norm is not null and area_id is not null and project_id is not null group by 1, 2""" % (
        name_norm_sql("project_name_en"), num("area_id"), num("project_id"), read(parts)))
    L = read(register_files("lkp_areas", "dld__lkp_areas__*.csv"))
    con.execute("""create or replace temp table j_num_names as
        select project_number, name_norm, area_id from (
            select project_number, %s name_norm, area_id from j_portal where project_number is not null
            union all
            select t.project_number, t.name_norm, l.area_id from j_2026 t
            left join (select %s area_id, upper(trim(name_en)) area_up from %s) l on l.area_up = t.area_up)
        where name_norm is not null and area_id is not null group by 1, 2, 3""" % (name_norm_sql("project_name_en"), num("area_id"), L))
    con.execute("""create or replace temp table j_num_bridge as
        select n.project_number, count(distinct r.project_id) ids, any_value(r.project_id) project_id
        from j_num_names n join j_right r on r.name_norm = n.name_norm and r.area_id = n.area_id and r.ids = 1 group by 1""")
    checks, agree = one(con, """select count(*), count(*) filter (where b.project_id = g.project_id)
        from j_num_bridge b join (select project_number, any_value(project_id) project_id from j_reg_projects
                                  where project_id is not null group by 1) g using (project_number) where b.ids = 1""")
    use_bridge = checks >= 100 and agree >= 0.99 * checks
    con.execute("""create or replace temp table j_projects as
        with reg as (select project_number, any_value(project_id) project_id, any_value(developer_number) developer_number
                     from j_reg_projects group by 1),
             br as (select project_number, project_id from j_num_bridge where ids = 1 and %s),
             y as (select project_number, any_value(developer_number) developer_number from j_2026 group by 1),
             allnum as (select project_number from reg union select project_number from y)
        select a.project_number, coalesce(reg.project_id, br.project_id) project_id,
               coalesce(reg.developer_number, y.developer_number) developer_number,
               case when reg.project_id is not null then 'projects register' when br.project_id is not null then 'register name + area' end project_id_method,
               case when reg.project_number is not null then 'dld__projects extract' else 'DLD projects CSV (2026 registrations)' end number_source
        from allnum a left join reg on reg.project_number = a.project_number left join br on br.project_number = a.project_number
        left join y on y.project_number = a.project_number""" % ("true" if use_bridge else "false"))
    tot, by_reg, by_bridge, y_only, devs = one(con, """select count(*), count(*) filter (where project_id_method = 'projects register'),
        count(*) filter (where project_id_method = 'register name + area'), count(*) filter (where number_source <> 'dld__projects extract'),
        count(developer_number) from j_projects""")
    lines.append("project numbers held: %s (register extract %s, 2026 registrations only %s) - project_id by register %s, by name + area bridge %s; developer number on %s"
                 % tuple(format(x, ",") for x in (tot, tot - y_only, y_only, by_reg, by_bridge, devs)))
    lines.append("name + area bridge vs the register where both hold the number: agrees on %s%s"
                 % (pct(agree, checks), "" if use_bridge else " - BELOW 99%, bridge not used"))
    ambiguous = one(con, "select count(*) from j_num_bridge where ids > 1")[0]
    if ambiguous:
        lines.append("numbers whose name + area reach more than one project_id (left unlinked): %d" % ambiguous)
    return lines


def job_sales_projects(con):
    T = read(register_files("transactions", "dld__transactions__*.csv"))
    PR = read(register_files("projects", "dld__projects__*.csv"))
    con.execute("""create or replace temp table j_portal as
        select split_part(transaction_id, '-', 2) || '-' || split_part(transaction_id, '-', 4) || '-' || split_part(transaction_id, '-', 3) k,
               transaction_id, %s project_number, try_cast(area_id as bigint) area_id, nullif(trim(building_name_en), '') building_name_en,
               nullif(trim(project_name_en), '') project_name_en, try_cast(actual_worth as double) worth, try_cast(procedure_area as double) size_sqm
        from %s where regexp_matches(transaction_id, '^[0-9]+-[0-9]+-[0-9]+-[0-9]+$')""" % (num("project_number"), T))
    # 15 Sep 2026 (digital thread Q2/Q3): project numbers -> project_id through the register AND a checked name + area bridge, with the
    # 2026 registrations the extract lacks. If that build fails for any reason the job falls back to the register alone, as before.
    try:
        number_lines = project_numbers(con)
        extra_tables = [("lk_project_numbers", "select * from j_projects")]
    except Exception as e:
        number_lines = ["project number bridge skipped (%s) - register extract only" % str(e)[:160]]
        extra_tables = []
        con.execute("""create or replace temp table j_projects as
            select %s project_number, %s project_id from %s where %s is not null""" % (num("project_number"), num("project_id"), PR, num("project_number")))
    con.execute("""create or replace temp table j_now as
        select split_part(txn_key, '#', 1) txn_key, max(try_cast(TRANS_VALUE as double)) worth, max(try_cast(PROCEDURE_AREA as double)) size_sqm,
               max(PROJECT_EN) project_en, max(AREA_EN) area_en, count(*) row_count
        from dld_transactions_now group by 1""")
    con.execute("""create or replace temp table j_bridge as
        select n.txn_key, p.transaction_id portal_transaction_id, p.project_number, j.project_id, p.area_id, p.building_name_en,
               p.project_name_en portal_project_en, abs(n.worth - p.worth) <= 1 value_agrees, abs(n.size_sqm - p.size_sqm) <= 0.5 size_agrees
        from j_now n join j_portal p on p.k = n.txn_key left join j_projects j on j.project_number = p.project_number
        where abs(n.worth - p.worth) <= 1 or abs(n.size_sqm - p.size_sqm) <= 0.5
        qualify row_number() over (partition by n.txn_key order by abs(n.worth - p.worth), abs(n.size_sqm - p.size_sqm)) = 1""")
    con.execute("""create or replace temp table j_names as
        select project_en, project_number, project_id, portal_rows, count(*) over (partition by project_en) numbers_for_name
        from (select p.project_name_en project_en, p.project_number, any_value(j.project_id) project_id, count(*) portal_rows
              from j_portal p left join j_projects j using (project_number)
              where p.project_number is not null and p.project_name_en is not null group by 1, 2)""")
    keys, paired = one(con, "select (select count(*) from j_now), count(*) from j_bridge")
    L = read(register_files("lkp_areas", "dld__lkp_areas__*.csv"))
    with_area, area_comm = one(con, """select count(b.area_id), count(a.comm_num) from j_bridge b
        left join (select try_cast(area_id as bigint) area_id, %s comm_num from %s) a on a.area_id = b.area_id""" % (num("municipality_number"), L))
    named, by_row, by_name, by_match = one(con, """
        select count(*), count(b.project_id), count(*) filter (where b.project_id is null and nm.project_id is not null),
               count(*) filter (where b.project_id is null and nm.project_id is null and x.project_id is not null)
        from j_now n left join j_bridge b using (txn_key)
        left join (select project_en, project_id from j_names where numbers_for_name = 1) nm on nm.project_en = n.project_en
        left join (select left_name, left_area, try_cast(project_id as bigint) project_id from lk_identity_xref
                   where job = 'tx_project' and decision = 'accepted') x on x.left_name = n.project_en and x.left_area = n.area_en
        where n.project_en is not null""")
    both, agree = one(con, """
        select count(*), count(*) filter (where r.project_id = x.project_id)
        from j_now n
        join (select b.txn_key, b.project_id from j_bridge b where b.project_id is not null) r using (txn_key)
        join (select left_name, left_area, try_cast(project_id as bigint) project_id from lk_identity_xref
              where job = 'tx_project' and decision = 'accepted') x on x.left_name = n.project_en and x.left_area = n.area_en""")
    report_rows = con.execute("""
        select n.project_en, n.area_en, x.project_id name_match_project, r.project_id register_project, count(*) sales_rows
        from j_now n
        join (select txn_key, project_id from j_bridge where project_id is not null) r using (txn_key)
        join (select left_name, left_area, try_cast(project_id as bigint) project_id from lk_identity_xref
              where job = 'tx_project' and decision = 'accepted') x on x.left_name = n.project_en and x.left_area = n.area_en
        where r.project_id <> x.project_id group by 1, 2, 3, 4 order by 5 desc""").fetchall()
    view = """with n as (select t.*, split_part(t.txn_key, '#', 1) base_key from dld_transactions_now t),
                   nm as (select project_en, project_id, project_number from lk_project_number_names where numbers_for_name = 1)
              select n.*, coalesce(r.project_id, nm.project_id, x.project_id) project_id,
                     coalesce(r.project_number, nm.project_number) project_number, r.building_name_en register_building_en,
                     case when r.project_id is not null then 'register row' when nm.project_id is not null then 'register name'
                          when x.project_id is not null then 'name match' end project_link,
                     r.area_id register_area_id, ac.comm_num
              from n left join lk_txn_register r on r.txn_key = n.base_key
              left join lk_area_community ac on ac.area_id = r.area_id
              left join nm on nm.project_en = n.PROJECT_EN
              left join (select left_name, left_area, try_cast(project_id as bigint) project_id from lk_identity_xref
                         where job = 'tx_project' and decision = 'accepted') x on x.left_name = n.PROJECT_EN and x.left_area = n.AREA_EN"""
    return {"tables": [("lk_txn_register", "select * from j_bridge"), ("lk_project_number_names", "select * from j_names")] + extra_tables,
            "views": [("v_transactions_register_project", view)],
            "keys_in": named, "keys_matched": by_row + by_name, "rows_in": keys,
            "note": "named sales rows linked by the register (row or name pair)",
            "review": report_rows,
            "report": number_lines + ["current sales keys paired with the portal's row (price or size agrees): " + pct(paired, keys),
                       "paired sales whose register area carries a community number: " + pct(area_comm, with_area),
                       "named sales rows linked: by the register's row %s, by its name-number pair %s, by name match only %s, of %s"
                       % (format(by_row, ","), format(by_name, ","), format(by_match, ","), format(named, ",")),
                       "where the register's row and identity_match both give a project, they agree on " + pct(agree, both),
                       "disagreeing name/project pairs: %d (data/identity/register_vs_name.csv)" % len(report_rows)]}


def job_twin_bindings(con):
    """Digital thread Q6 (15 Sep 2026): the only register -> twin link lived in two JSON files keyed by district and footprint LIST
    POSITION (data/identity/official/dld/reg_bindings.json from bind_register_buildings.py, tx_bindings.json from bind_dld_buildings.py)
    and never reached the lake. This job loads both keyed by the twin's duid (resolved from data/identity/resolved/<district>.json)
    and the register's property_id / parcel key, and publishes a review view for what a one-to-one link must not do: one register
    building on several footprints, and a register name that disagrees with the twin's own name. Nothing is decided here - it makes
    the links queryable and their conflicts countable."""
    from keys import norm_number, parcel_key as pkey, name_norm
    ident = os.path.join(ROOT, "data", "identity")
    duid = {}
    for f in glob.glob(os.path.join(ident, "resolved", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        slug = d.get("district") or os.path.splitext(os.path.basename(f))[0]
        for r in d.get("rows") or []:
            if r.get("i") is not None and r.get("duid"):
                duid[(slug, int(r["i"]))] = (r["duid"], r.get("display_name") or r.get("official_building_name") or r.get("current_name"))
    reg_rows, tx_rows = [], []
    regf, txf = os.path.join(ident, "official", "dld", "reg_bindings.json"), os.path.join(ident, "official", "dld", "tx_bindings.json")
    for slug, B in (json.load(open(regf, encoding="utf-8")) if os.path.exists(regf) else {}).items():
        if not isinstance(B, dict):
            continue
        for i, b in B.items():
            if not str(i).isdigit() or not isinstance(b, dict):
                continue                                   # summary blocks keyed by district, not footprint bindings
            fp = duid.get((slug, int(i)), (None, None))
            for rank, x in [("primary", b)] + [("also", a) for a in (b.get("also") or [])]:
                reg_rows.append((slug, int(i), fp[0], fp[1], rank, norm_number(x.get("property_id")), pkey(x.get("parcel")), x.get("name"),
                                 x.get("project"), x.get("master"), x.get("units"), x.get("floors"), b.get("method"), b.get("dist_m")))
    for slug, B in (json.load(open(txf, encoding="utf-8")) if os.path.exists(txf) else {}).items():
        if not isinstance(B, dict):
            continue
        for i, b in B.items():
            if not str(i).isdigit() or not isinstance(b, dict):
                continue
            fp = duid.get((slug, int(i)), (None, None))
            tx_rows.append((slug, int(i), fp[0], fp[1], b.get("area"), b.get("project"), b.get("building"), b.get("master"), b.get("sales"),
                            b.get("first"), b.get("last"), b.get("median_aed_sqm")))
    con.execute("""create or replace temp table j_bind_reg (district varchar, footprint_i integer, duid varchar, twin_name varchar, rank varchar,
                   property_id varchar, parcel_key bigint, register_name varchar, project varchar, master varchar, units integer, floors integer,
                   method varchar, dist_m double)""")
    if reg_rows:
        con.executemany("insert into j_bind_reg values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", reg_rows)
    con.execute("""create or replace temp table j_bind_tx (district varchar, footprint_i integer, duid varchar, twin_name varchar, area varchar,
                   project varchar, building varchar, master varchar, sales integer, first_sale varchar, last_sale varchar, median_aed_sqm double)""")
    if tx_rows:
        con.executemany("insert into j_bind_tx values (?,?,?,?,?,?,?,?,?,?,?,?)", tx_rows)
    con.execute("alter table j_bind_reg add column names_differ boolean")
    con.execute("update j_bind_reg set names_differ = twin_name is not null and register_name is not null")
    for row in con.execute("select rowid, twin_name, register_name from j_bind_reg where names_differ").fetchall():
        a, b = name_norm(row[1]), name_norm(row[2])
        if a and b and (a in b or b in a):
            con.execute("update j_bind_reg set names_differ = false where rowid = ?", [row[0]])
    fps, fps_duid, props, multi, differ = one(con, """select count(*) filter (where rank = 'primary'), count(duid) filter (where rank = 'primary'),
        count(distinct property_id), (select count(*) from (select property_id from j_bind_reg where property_id is not null
                                       group by 1 having count(distinct duid) > 1)),
        count(*) filter (where rank = 'primary' and names_differ) from j_bind_reg""")
    units = one(con, "select coalesce(sum(units), 0) from j_bind_reg where rank = 'primary'")[0]
    txn, txn_duid = one(con, "select count(*), count(duid) from j_bind_tx")
    review = """select 'register building on several footprints' issue, property_id, list(distinct duid) duids, any_value(register_name) register_name,
                       null::varchar twin_name, count(distinct duid) n
                from lk_twin_binding_register where property_id is not null group by property_id having count(distinct duid) > 1
                union all
                select 'register name differs from the twin name', property_id, [duid], register_name, twin_name, 1
                from lk_twin_binding_register where rank = 'primary' and names_differ"""
    return {"tables": [("lk_twin_binding_register", "select * from j_bind_reg"), ("lk_twin_binding_sales", "select * from j_bind_tx")],
            "views": [("v_twin_binding_review", review)],
            "keys_in": fps, "keys_matched": fps_duid, "rows_in": len(reg_rows) + len(tx_rows),
            "note": "register-bound footprints resolved to a duid",
            "report": ["register bindings: %s footprints (%s register buildings incl. 'also', %s units on the primaries); footprints with a duid: %s"
                       % (format(fps, ","), format(props, ","), format(units, ","), pct(fps_duid, fps)),
                       "sales bindings: %s footprints, with a duid: %s" % (format(txn, ","), pct(txn_duid, txn)),
                       "for review: %s register buildings on more than one footprint; %s primary bindings whose register name differs from the twin's"
                       % (format(multi, ","), format(differ, ","))]}


def job_rent_projects(con):
    """Digital thread Q5 (15 Sep 2026): registered rent contracts -> project_id and area_id. Rents carried no project link at all.
    Ejari names its project in free text and its area by the DLD area name, so: the normalised project name matched exactly to the
    English names the buildings, land and units registers give each project_id (plus the sales-register aliases identity_match has
    accepted), and accepted only when exactly one of those projects is registered in the rent's own area. A name several projects
    share in that area, or a name whose only project sits in another area, goes to review - never guessed. Every rent row also gets
    its area_id from the DLD area lookup. Publishes lk_rent_project, lk_dld_area_names and the view v_rents_project (live over rents)."""
    parts = [p for name, pattern in (("buildings", "dld__buildings__*.csv"), ("land_registry", "dld__land_registry__*.csv"),
                                     ("units", "dld__units__*.csv")) for p in register_files(name, pattern)]
    L = read(register_files("lkp_areas", "dld__lkp_areas__*.csv"))
    con.execute("""create or replace temp table j_rreg as
        select distinct %s name_norm, %s area_id, %s project_id from %s""" % (name_norm_sql("project_name_en"), num("area_id"), num("project_id"), read(parts)))
    con.execute("delete from j_rreg where name_norm is null or project_id is null")
    con.execute("create or replace temp table j_pid_area as select distinct project_id, area_id from j_rreg where area_id is not null")
    con.execute("""create or replace temp table j_rcand as
        select name_norm, project_id from j_rreg
        union
        select %s, %s from lk_project_alias where lang = 'en'""" % (name_norm_sql("alias"), num("project_id")))
    # two DLD area names belong to two area ids each (OUD AL MUTEENA 381/474, MUSHRIF 404/420): such a name gives no area_id rather
    # than two, so the view never duplicates a rent row
    con.execute("""create or replace temp table j_area_names as
        select area_id, name_en, name_up from (select %s area_id, trim(name_en) name_en, upper(trim(name_en)) name_up from %s where %s is not null)
        qualify count(*) over (partition by name_up) = 1""" % (num("area_id"), L, num("area_id")))
    con.execute("""create or replace temp table j_rnames as
        select PROJECT_EN project_en, AREA_EN area_en, %s name_norm, count(*) n_rows from rents
        where nullif(trim(PROJECT_EN), '') is not null group by 1, 2, 3""" % name_norm_sql("PROJECT_EN"))
    con.execute("""create or replace temp table j_rent_project as
        with c as (select n.project_en, n.area_en, n.n_rows, an.area_id, c.project_id, pa.project_id is not null area_ok
                   from j_rnames n left join j_area_names an on an.name_up = upper(trim(n.area_en))
                   left join j_rcand c on c.name_norm = n.name_norm
                   left join j_pid_area pa on pa.project_id = c.project_id and pa.area_id = an.area_id),
             g as (select project_en, area_en, any_value(n_rows) n_rows, any_value(area_id) area_id,
                          count(distinct project_id) ids_any, count(distinct project_id) filter (where area_ok) ids_area,
                          any_value(project_id) filter (where area_ok) pid_area
                   from c group by 1, 2)
        select project_en, area_en, n_rows, area_id, case when ids_area = 1 then pid_area end project_id,
               case when ids_area = 1 then 'exact name + area' when ids_area > 1 then 'exact name, several projects in the area'
                    when ids_any >= 1 then 'exact name, registered in another area' else 'no registered name' end link_method,
               case when ids_area = 1 then 'accepted' when ids_any >= 1 then 'review' else 'unmatched' end decision
        from g""")
    total, named, accepted, review, with_area = one(con, """select (select count(*) from rents), sum(n_rows),
        sum(n_rows) filter (where decision = 'accepted'), sum(n_rows) filter (where decision = 'review'),
        (select count(*) from rents r join j_area_names a on a.name_up = upper(trim(r.AREA_EN))) from j_rent_project""")
    names_acc = one(con, "select count(*) from j_rent_project where decision = 'accepted'")[0]
    view = """select r.*, a.area_id, x.project_id, x.link_method project_link
              from rents r left join lk_dld_area_names a on a.name_up = upper(trim(r.AREA_EN))
              left join lk_rent_project x on x.project_en = r.PROJECT_EN and x.area_en = r.AREA_EN and x.decision = 'accepted'"""
    return {"tables": [("lk_rent_project", "select * from j_rent_project"), ("lk_dld_area_names", "select * from j_area_names")],
            "views": [("v_rents_project", view)],
            "keys_in": named or 0, "keys_matched": accepted or 0, "rows_in": total,
            "note": "named rent rows linked to one registered project in their own area",
            "report": ["rent rows: %s; named %s" % (format(total, ","), pct(named or 0, total)),
                       "named rent rows linked to a project_id (exact name + area): %s across %s names" % (pct(accepted or 0, named or 0), format(names_acc, ",")),
                       "named rent rows left for review (several projects, or registered elsewhere): " + format(review or 0, ","),
                       "rent rows given an area_id: " + pct(with_area, total)]}


# --- digital thread P1: one project table, one developer table, one crosswalk -----------------------------------------------------

XREF_DDL = """create table if not exists lk_xref (job varchar, from_type varchar, from_id varchar, to_type varchar, to_id varchar,
              relation varchar, method varchar, score double, decision varchar, decided_by varchar, evidence varchar,
              source_snapshot varchar, valid_from timestamp, valid_to timestamp, run_id varchar)"""
XREF_COLS = "job, from_type, from_id, to_type, to_id, relation, method, score, decision, decided_by, evidence, source_snapshot, valid_from, valid_to, run_id"
GROUP_DECISIONS = os.path.join(ROOT, "data", "identity", "developer_group_decisions.json")
GROUP_REVIEW = os.path.join(ROOT, "data", "identity", "developer_group_review.csv")
CHURN_MAX = 0.01                       # gate C6: more than 1% of the ids a spine table published last time vanishing holds the job


def lake_has(con, table):
    return con.execute("select count(*) from information_schema.tables where table_name = ?", [table]).fetchone()[0] > 0


def job_project_spine(con):
    """Digital thread P1.1 + P1.2 (15 Sep 2026): one project table, one developer table, and each board developer as a group of DLD
    developer entities in the crosswalk. Names are alias columns here, never the key.

      lk_d_project    one row per project: prj:<project_id>, or prjn:<project_number> for a 2026 registration no register gives an id yet
                      (superseded once one does). Union of the projects register, the 2026 registrations CSV (bridged to project_id by
                      lk_project_numbers), and every project_id the buildings, land, units and service-charge registers carry. The projects
                      register names projects in Arabic only, so the English name comes from the buildings/land/units registers, then the
                      2026 CSV, then the sales register's name for the number.
      lk_d_developer  one row per DLD developer: dev:<developer_id> (id and number are one-to-one in the developers register), or
                      devn:<number> for a number only the projects files carry; licence, legal status, projects as developer and as master.
      lk_xref         job developer_group: grp:<board key> -> dev:<id>, relation member. Evidence: (a) the entity's English name carries one
                      of the group's aliases, whole words; (b) the entity is the registered developer of the group's own portfolio projects
                      (portfolio file, project seeds and - P1.4 - the projects on its own availability sheets, lk_avail_units; by exact English
                      name that reaches one project only, or a name titled with the brand).
                      Accepted: an alias that leads the name or has two or more words; a brand inside another name with (b); (b) alone when
                      two or more portfolio projects, or one titled with the brand, make at least half the entity's registered projects.
                      Other evidence is review (data/identity/developer_group_review.csv); an entity accepted for two groups goes to review
                      for both; hand decisions in data/identity/developer_group_decisions.json win. A master developer role is never
                      membership.
      v_thread_developer   accepted group -> developer -> project, role developer or master developer.
    Held, nothing replaced, when more than 1% of the canonical ids published last time vanish without being superseded (gate C6)."""
    import collections
    import build_developer_dna as dna                      # side-effect free at import: PORT_KEY, wmatch, load_portfolio
    from keys import name_norm, norm_number
    PRF, DVF = register_files("projects", "dld__projects__*.csv"), register_files("developers", "dld__developers__*.csv")
    PR, DV = read(PRF), read(DVF)
    L = read(register_files("lkp_areas", "dld__lkp_areas__*.csv"))
    SC = read(register_files("oa_service_charges", "dld__oa_service_charges__*.csv"))
    B, LR, U = (read(register_files(n, p)) for n, p in (("buildings", "dld__buildings__*.csv"), ("land_registry", "dld__land_registry__*.csv"),
                                                          ("units", "dld__units__*.csv")))
    txt = lambda c: "nullif(trim(%s), '')" % c
    day = lambda c: "try_cast(left(trim(%s), 10) as date)" % c
    cnt = lambda c: "try_cast(try_cast(%s as double) as bigint)" % c
    not_ar = lambda c: "case when not regexp_matches(coalesce(%s, ''), '[\\x{0600}-\\x{06FF}]') then %s end" % (c, c)

    con.execute("""create or replace temp table j_sp_pr as
        select %s project_id, %s project_number, %s name_ar, %s area_id, %s area_name_en, %s master_project_en, %s developer_id,
               %s developer_number, %s developer_name, %s master_developer_number, %s master_developer_name, %s status,
               try_cast(percent_completed as double) percent_completed, %s start_date, %s end_date, %s completion_date, %s cancellation_date,
               %s planned_units, %s planned_buildings, %s planned_villas, %s planned_lands, %s escrow_agent_id, %s zoning_authority,
               %s register_property_id
        from %s where %s is not null
        qualify row_number() over (partition by %s order by project_number) = 1""" % (
        num("project_id"), num("project_number"), txt("project_name"), num("area_id"), txt("area_name_en"), txt("master_project_en"),
        num("developer_id"), num("developer_number"), not_ar(txt("developer_name")), num("master_developer_number"),
        not_ar(txt("master_developer_name")), txt("project_status"), day("project_start_date"), day("project_end_date"),
        day("completion_date"), day("cancellation_date"), cnt("no_of_units"), cnt("no_of_buildings"), cnt("no_of_villas"),
        cnt("no_of_lands"), num("escrow_agent_id"), txt("zoning_authority_en"), num("property_id"), PR, num("project_id"), num("project_id")))
    con.execute("""create or replace temp table j_sp_y26 (project_number bigint, name_en varchar, developer_number bigint, developer_name varchar,
                   start_date date, end_date date, registered_date date, status varchar, percent_completed double, completion_date date,
                   area_name_en varchar, zoning_authority varchar, master_project_en varchar, planned_units bigint, planned_buildings bigint,
                   planned_villas bigint, planned_lands bigint)""")
    y26 = sorted(glob.glob(os.path.join(ROOT, "data", "projects-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv")))
    if y26:
        con.execute("""insert into j_sp_y26 select %s, %s, %s, %s, %s, %s, %s, %s, try_cast(PERCENT_COMPLETED as double), %s, %s, %s, %s,
                       %s, %s, %s, %s
            from read_csv('%s', all_varchar=true, header=true) where %s is not null
            qualify row_number() over (partition by %s order by ADOPTION_DATE desc nulls last) = 1""" % (
            num("PROJECT_NUMBER"), txt("PROJECT_EN"), num("DEVELOPER_NUMBER"), txt("DEVELOPER_EN"), day("START_DATE"), day("END_DATE"),
            day("ADOPTION_DATE"), txt("PROJECT_STATUS"), day("COMPLETION_DATE"), txt("AREA_EN"), txt("ZONE_EN"), txt("MASTER_PROJECT_EN"),
            cnt("CNT_UNIT"), cnt("CNT_BUILDING"), cnt("CNT_VILLA"), cnt("CNT_LAND"), lake._p(y26[-1]), num("PROJECT_NUMBER"),
            num("PROJECT_NUMBER")))
    one_reg = "select '%s' src, %s project_id, %s name_en, %s area_id, %s master_project_id, %s master_project_en, %s property_id from %s"
    con.execute("""create or replace temp table j_sp_reg as
        select project_id, mode(name_en) name_en, list(distinct name_en) filter (where name_en is not null) names_en, mode(area_id) area_id,
               mode(master_project_id) master_project_id, mode(master_project_en) master_project_en,
               count(distinct property_id) filter (where src = 'buildings') registered_buildings,
               count(distinct property_id) filter (where src = 'land') registered_land,
               count(distinct property_id) filter (where src = 'units') registered_units
        from (%s) where project_id is not null group by 1""" % " union all ".join(
        one_reg % (s, num("project_id"), txt("project_name_en"), num("area_id"), num("master_project_id"), txt("master_project_en"),
                   num("property_id"), R) for s, R in (("buildings", B), ("land", LR), ("units", U))))
    con.execute("""create or replace temp table j_sp_sc as select %s project_id, max(try_cast(budget_year as integer)) service_charge_year
        from %s where %s is not null group by 1""" % (num("project_id"), SC, num("project_id")))
    # project numbers -> project_id: the register's own pairs first, then lk_project_numbers (2026 registrations by the checked bridge)
    con.execute("""create or replace temp table j_sp_num as
        select project_number, project_id, developer_number, project_id_method from (
            select project_number, project_id, developer_number, 'projects register' project_id_method, 1 prio from j_sp_pr
            %s)
        qualify row_number() over (partition by project_number order by prio) = 1""" % (
        "union all select project_number, project_id, developer_number, project_id_method, 2 from lk_project_numbers"
        if lake_has(con, "lk_project_numbers") else ""))
    con.execute("create or replace temp table j_sp_pnn (project_number bigint, project_en varchar, portal_rows bigint)")
    if lake_has(con, "lk_project_number_names"):
        con.execute("""insert into j_sp_pnn select project_number, project_en, portal_rows from lk_project_number_names
                       where project_number is not null and project_en is not null""")
    con.execute("""create or replace temp table j_sp_area as
        select %s area_id, any_value(%s) name_en from %s where %s is not null group by 1""" % (num("area_id"), txt("name_en"), L, num("area_id")))
    con.execute("""create or replace temp table j_sp_area_up as
        select upper(name_en) name_up, any_value(area_id) area_id from j_sp_area where name_en is not null group by 1 having count(*) = 1""")
    con.execute("""create or replace temp table j_sp_proj as
        with ids as (select project_id from j_sp_pr union select project_id from j_sp_reg union select project_id from j_sp_sc
                     union select project_id from j_sp_num where project_id is not null),
             nid as (select project_id, list_sort(list(distinct project_number)) numbers, min(project_id_method) id_method
                     from j_sp_num where project_id is not null group by 1),
             yid as (select n.project_id id_, y.* from j_sp_num n join j_sp_y26 y on y.project_number = n.project_number
                     where n.project_id is not null
                     qualify row_number() over (partition by n.project_id order by y.registered_date desc nulls last, y.project_number desc) = 1),
             pnid as (select n.project_id, arg_max(p.project_en, p.portal_rows) project_en from j_sp_num n
                      join j_sp_pnn p on p.project_number = n.project_number where n.project_id is not null group by 1),
             ndev as (select project_id, any_value(developer_number) developer_number from j_sp_num
                      where project_id is not null and developer_number is not null group by 1)
        select 'prj:' || cast(i.project_id as varchar) canonical_id, i.project_id, coalesce(p.project_number, nid.numbers[1]) project_number,
               nid.numbers project_numbers, coalesce(r.name_en, y.name_en, pn.project_en) name_en,
               case when r.name_en is not null then 'buildings/land/units registers' when y.name_en is not null then '2026 registrations'
                    when pn.project_en is not null then 'sales register' end name_source,
               p.name_ar, r.names_en, coalesce(p.area_id, r.area_id, ya.area_id) area_id, p.area_name_en area_name_register,
               r.master_project_id, coalesce(r.master_project_en, p.master_project_en, y.master_project_en) master_project_en,
               coalesce(p.developer_number, y.developer_number, nd.developer_number) developer_number, p.developer_id,
               p.master_developer_number, coalesce(p.status, y.status) status, coalesce(p.percent_completed, y.percent_completed) percent_completed,
               coalesce(p.start_date, y.start_date) start_date, coalesce(p.end_date, y.end_date) end_date,
               coalesce(p.completion_date, y.completion_date) completion_date, p.cancellation_date, y.registered_date,
               coalesce(p.planned_units, y.planned_units) planned_units, coalesce(p.planned_buildings, y.planned_buildings) planned_buildings,
               coalesce(p.planned_villas, y.planned_villas) planned_villas, coalesce(p.planned_lands, y.planned_lands) planned_lands,
               coalesce(r.registered_buildings, 0) registered_buildings, coalesce(r.registered_land, 0) registered_land,
               coalesce(r.registered_units, 0) registered_units, sc.service_charge_year, p.escrow_agent_id,
               coalesce(p.zoning_authority, y.zoning_authority) zoning_authority, p.register_property_id,
               p.project_id is not null in_projects_register, y.id_ is not null in_2026_registrations,
               coalesce(case when p.project_id is not null then 'projects register' end, nid.id_method, 'register id, no project number') project_id_method
        from ids i left join j_sp_pr p on p.project_id = i.project_id left join j_sp_reg r on r.project_id = i.project_id
        left join j_sp_sc sc on sc.project_id = i.project_id left join nid on nid.project_id = i.project_id
        left join yid y on y.id_ = i.project_id left join pnid pn on pn.project_id = i.project_id
        left join ndev nd on nd.project_id = i.project_id left join j_sp_area_up ya on ya.name_up = upper(y.area_name_en)
        union all by name
        select 'prjn:' || cast(y.project_number as varchar) canonical_id, y.project_number, [y.project_number] project_numbers, y.name_en,
               '2026 registrations' name_source, ya.area_id, y.master_project_en, y.developer_number, y.status, y.percent_completed,
               y.start_date, y.end_date, y.completion_date, y.registered_date, y.planned_units, y.planned_buildings, y.planned_villas,
               y.planned_lands, 0 registered_buildings, 0 registered_land, 0 registered_units, y.zoning_authority,
               false in_projects_register, true in_2026_registrations, 'none yet' project_id_method
        from j_sp_y26 y left join j_sp_area_up ya on ya.name_up = upper(y.area_name_en)
        where not exists (select 1 from j_sp_num n where n.project_number = y.project_number and n.project_id is not null)""")
    con.execute("""create or replace temp table j_sp_dv as
        select %s developer_id, %s developer_number, %s name_en, %s name_ar, %s legal_status, %s license_number, %s license_source,
               %s license_type, %s license_issue_date, %s license_expiry_date, %s chamber_of_commerce_no, %s registration_date
        from %s where %s is not null
        qualify row_number() over (partition by %s order by registration_date desc nulls last) = 1""" % (
        num("developer_id"), num("developer_number"), txt("developer_name_en"), txt("developer_name_ar"), txt("legal_status_en"),
        txt("license_number"), txt("license_source_en"), txt("license_type_en"), day("license_issue_date"), day("license_expiry_date"),
        txt("chamber_of_commerce_no"), day("registration_date"), DV, num("developer_number"), num("developer_number")))
    con.execute("""create or replace temp table j_d_project as
        select d.canonical_id, d.project_id, d.project_number, d.project_numbers, d.name_en, d.name_source, d.name_ar, d.names_en,
               d.area_id, coalesce(d.area_name_register, a.name_en) area_name_en, d.master_project_id, d.master_project_en,
               d.developer_number, coalesce(d.developer_id, v.developer_id) developer_id, d.master_developer_number, d.status,
               d.percent_completed, d.start_date, d.end_date, d.completion_date, d.cancellation_date, d.registered_date, d.planned_units,
               d.planned_buildings, d.planned_villas, d.planned_lands, d.registered_buildings, d.registered_land, d.registered_units,
               d.service_charge_year, d.escrow_agent_id, d.zoning_authority, d.register_property_id, d.in_projects_register,
               d.in_2026_registrations, d.project_id_method,
               concat_ws(', ', case when d.in_projects_register then 'projects register' end,
                         case when d.in_2026_registrations then '2026 registrations' end, case when d.registered_buildings > 0 then 'buildings' end,
                         case when d.registered_land > 0 then 'land' end, case when d.registered_units > 0 then 'units' end,
                         case when d.service_charge_year is not null then 'service charges' end) sources
        from j_sp_proj d left join j_sp_area a on a.area_id = d.area_id left join j_sp_dv v on v.developer_number = d.developer_number""")
    con.execute("""create or replace temp table j_d_developer as
        with nums as (select developer_number from j_sp_dv union select developer_number from j_d_project where developer_number is not null
                      union select master_developer_number from j_d_project where master_developer_number is not null),
             names as (select developer_number, arg_min(developer_name, prio) name_en from (
                          select developer_number, developer_name, 1 prio from j_sp_y26 union all
                          select developer_number, developer_name, 2 from j_sp_pr union all
                          select master_developer_number, master_developer_name, 3 from j_sp_pr)
                       where developer_name is not null group by 1),
             dp as (select developer_number, count(*) projects_as_developer, cast(sum(planned_units) as bigint) planned_units_as_developer,
                           count(*) filter (where status = 'ACTIVE') active_projects, min(start_date) first_project_start,
                           max(start_date) last_project_start
                    from j_d_project where developer_number is not null group by 1),
             mp as (select master_developer_number developer_number, count(*) projects_as_master from j_d_project
                    where master_developer_number is not null group by 1)
        select case when d.developer_id is not null then 'dev:' || cast(d.developer_id as varchar)
                    else 'devn:' || cast(n.developer_number as varchar) end canonical_id,
               d.developer_id, n.developer_number, coalesce(d.name_en, nm.name_en) name_en,
               case when d.name_en is not null then 'developers register' when nm.name_en is not null then 'projects files' end name_source,
               d.name_ar, d.legal_status, d.license_number, d.license_source, d.license_type, d.license_issue_date, d.license_expiry_date,
               d.chamber_of_commerce_no, d.registration_date, coalesce(dp.projects_as_developer, 0) projects_as_developer,
               coalesce(mp.projects_as_master, 0) projects_as_master, dp.planned_units_as_developer, coalesce(dp.active_projects, 0) active_projects,
               dp.first_project_start, dp.last_project_start, d.developer_id is not null in_developers_register
        from nums n left join j_sp_dv d on d.developer_number = n.developer_number left join names nm on nm.developer_number = n.developer_number
        left join dp on dp.developer_number = n.developer_number left join mp on mp.developer_number = n.developer_number""")

    # gate C6: ids published last time that vanished without being superseded (prjn -> prj once the id appears, devn -> dev)
    hold, churn = None, []
    for table, tmp, superseded in (
            ("lk_d_project", "j_d_project",
             "select distinct 'prjn:' || cast(unnest(project_numbers) as varchar) cid from j_d_project where project_id is not null"),
            ("lk_d_developer", "j_d_developer",
             "select 'devn:' || cast(developer_number as varchar) cid from j_d_developer where developer_id is not null")):
        if not lake_has(con, table):
            churn.append("%s: first publish" % table)
            continue
        old, gone, sup = one(con, """select count(*), count(*) filter (where n.canonical_id is null and s.cid is null),
            count(*) filter (where n.canonical_id is null and s.cid is not null)
            from %s o left join %s n on n.canonical_id = o.canonical_id left join (%s) s on s.cid = o.canonical_id""" % (table, tmp, superseded))
        churn.append("%s: %s of %s ids published last time vanished, %s superseded" % (table, format(gone, ","), format(old, ","), format(sup, ",")))
        if old and gone > CHURN_MAX * old:
            hold = "id churn on %s: %s of %s ids vanished (limit %.0f%%)" % (table, format(gone, ","), format(old, ","), 100 * CHURN_MAX)

    # P1.2: board developers -> DLD developer entities
    seg = json.load(open(dna.SEG_FILE, encoding="utf-8"))
    groups = [(dev, dna.PORT_KEY.get(dev) or re.sub(r"[^a-z0-9]+", "", dev.lower())) for s in seg["segments"] for dev in s["developers"]]
    ents = con.execute("select canonical_id, developer_number, name_en, projects_as_developer from j_d_developer where name_en is not null").fetchall()
    proj_dev, name_to = {}, collections.defaultdict(set)
    for cid, dn, nm, names in con.execute("select canonical_id, developer_number, name_en, names_en from j_d_project").fetchall():
        proj_dev[cid] = dn
        for n in [nm] + list(names or []):
            if name_norm(n):
                name_to[name_norm(n)].add(cid)
    more = """select p.project_en, d.canonical_id from j_sp_pnn p
              join (select canonical_id, unnest(project_numbers) project_number from j_d_project) d on d.project_number = p.project_number"""
    if lake_has(con, "lk_project_alias"):
        more += " union select alias, 'prj:' || cast(%s as varchar) from lk_project_alias where lang = 'en'" % num("project_id")
    for n, cid in con.execute(more).fetchall():
        if name_norm(n) and cid in proj_dev:
            name_to[name_norm(n)].add(cid)
    hand = {}
    try:
        for h in json.load(open(GROUP_DECISIONS, encoding="utf-8")).get("decisions") or []:
            n = norm_number(h.get("developer_number"))
            if h.get("group") and n and h.get("decision") in ("accepted", "rejected"):
                hand[(str(h["group"]).strip().lower(), int(n))] = h
    except (OSError, ValueError):
        pass
    snapshot = "; ".join(os.path.basename(p) for p in DVF + PRF + y26[-1:])
    sheet_names = collections.defaultdict(list)
    if lake_has(con, "lk_avail_units"):
        for dk, proj in con.execute("select distinct developer, project from lk_avail_units").fetchall():
            sheet_names[dk].append(proj)
    now = dt.datetime.now().replace(microsecond=0)
    run_id = "project_spine@" + now.isoformat()
    links = []
    for dev, key in groups:
        al = [a.strip().lower() for a in seg["aliases"].get(dev, [dev.lower()]) if a and a.strip()]
        seeds = [p.get("name") for p in (dna.load_portfolio(dev) or {}).get("properties") or [] if p.get("name")]
        seeds += [x for x in (seg.get("project_aliases") or {}).get(dev) or [] if isinstance(x, str)]
        seeds += sheet_names.get(key, [])                  # P1.4: the projects on the developer's own availability sheets, same rules
        ev = collections.defaultdict(lambda: {"names": set(), "ids": set(), "branded": set()})
        for s in seeds:
            cids, branded = name_to.get(name_norm(s)) or set(), any(dna.wmatch(s, a) for a in al)
            if len(cids) == 1 or (cids and branded):
                for cid in cids:
                    if proj_dev.get(cid) is not None:
                        e = ev[proj_dev[cid]]
                        e["names"].add(s); e["ids"].add(cid)
                        if branded:
                            e["branded"].add(cid)
        seen = set()
        for cid, dn, nm, nproj in ents:
            hits = [a for a in al if dna.wmatch(nm, a)]
            h = hand.get((dev.lower(), dn)) or hand.get((key, dn))
            if not hits and dn not in ev and not h:
                continue
            seen.add(dn)
            e = ev.get(dn) or {"names": set(), "ids": set(), "branded": set()}
            b, bb = len(e["ids"]), len(e["branded"])
            share = float(b) / nproj if nproj else 0.0
            lead = [a for a in hits if len(a.split()) > 1 or re.match(r"[^a-z0-9]*" + re.escape(a) + r"(?![a-z0-9])", nm.lower())]
            if lead and b:
                method, decision, score = "register name + portfolio projects", "accepted", 1.0
            elif lead:
                method, decision, score = "register name", "accepted", 0.95
            elif hits and b:
                method, decision, score = "brand inside the name + portfolio projects", "accepted", 0.9
            elif b >= 2 and share >= 0.5:
                method, decision, score = "portfolio projects", "accepted", round(share, 3)
            elif bb and share >= 0.5:
                method, decision, score = "portfolio project titled with the brand", "accepted", round(share, 3)
            elif hits:
                method, decision, score = "brand inside another name", "review", 0.5
            elif b:
                method, decision, score = "portfolio projects, too few", "review", round(share, 3)
            else:
                method, decision, score = "hand only", "review", 0.0
            evidence = "; ".join(x for x in (
                "name carries " + ", ".join("'%s'" % a for a in hits) if hits else "",
                "developer of %d of its %d registered projects in the portfolio (%s)" % (b, nproj, ", ".join(sorted(e["names"]))[:180])
                if b else "%d registered projects as developer" % nproj) if x)
            by = "rule"
            if h:
                decision, method, score, by = h["decision"], "hand", 1.0, h.get("by") or "hand"
                evidence = "; ".join(x for x in (h.get("note"), evidence) if x)
            links.append(["developer_group", "developer_group", "grp:" + key, "developer", cid, "member", method, score, decision, by,
                          evidence[:400], snapshot, now, None, run_id, dev, dn, nm])
    claimed = collections.defaultdict(set)
    for l in links:
        if l[8] == "accepted" and l[9] == "rule":
            claimed[l[4]].add(l[2])
    for l in links:
        if l[8] == "accepted" and l[9] == "rule" and len(claimed[l[4]]) > 1:
            l[8], l[6] = "review", l[6] + ", claimed by %d groups" % len(claimed[l[4]])
    con.execute(XREF_DDL.replace("create table if not exists lk_xref", "create or replace temp table j_xref_dev"))
    if links:
        con.executemany("insert into j_xref_dev values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [l[:15] for l in links])
    per = collections.OrderedDict((dev, collections.Counter()) for dev, _ in groups)
    for l in links:
        per[l[15]][l[8] if l[8] != "accepted" else "accepted: " + l[6]] += 1
    keyed = sum(1 for c in per.values() if any(k.startswith("accepted") for k in c))
    review_rows = [[l[15], l[16], l[17], l[6], l[7], l[10]] for l in links if l[8] == "review"]

    tot, n_id, in_pr, in_y, reg_only, sc_only, named, with_area, with_dev, multi = one(con, """select count(*), count(project_id),
        count(*) filter (where in_projects_register), count(*) filter (where in_2026_registrations),
        count(*) filter (where not in_projects_register and not in_2026_registrations and sources <> 'service charges'),
        count(*) filter (where sources = 'service charges'), count(name_en), count(area_id), count(developer_number),
        count(*) filter (where len(project_numbers) > 1) from j_d_project""")
    dtot, d_reg, d_dev, d_mas = one(con, """select count(*), count(*) filter (where in_developers_register),
        count(*) filter (where projects_as_developer > 0), count(*) filter (where projects_as_master > 0) from j_d_developer""")
    no_dev = one(con, """select count(*) from j_d_project p where developer_number is not null
        and not exists (select 1 from j_d_developer d where d.developer_number = p.developer_number and d.in_developers_register)""")[0]
    view = """select x.from_id group_id, substr(x.from_id, 5) group_key, x.method link_method, x.score link_score, d.canonical_id developer_canonical_id,
                     d.developer_number, d.name_en developer_name_en, p.canonical_id project_canonical_id, p.project_id, p.project_number,
                     p.name_en project_name_en, p.area_id, p.area_name_en, p.status, p.planned_units,
                     case when p.developer_number = d.developer_number then 'developer' else 'master developer' end project_role
              from lk_xref x join lk_d_developer d on d.canonical_id = x.to_id
              join lk_d_project p on p.developer_number = d.developer_number or p.master_developer_number = d.developer_number
              where x.job = 'developer_group' and x.decision = 'accepted'"""
    return {"tables": [("lk_d_project", "select * from j_d_project"), ("lk_d_developer", "select * from j_d_developer")],
            "xref": [("developer_group", "j_xref_dev")],
            "views": [("v_thread_developer", view)],
            "keys_in": len(groups), "keys_matched": keyed, "rows_in": tot, "hold": hold,
            "note": "board developers keyed to at least one DLD developer entity",
            "review_csv": (GROUP_REVIEW, ["group", "developer_number", "developer_name_en", "method", "score", "evidence"], review_rows),
            "report": ["projects: %s (project_id %s, 2026 registrations with no id yet %s) - in the projects register %s, in the 2026 registrations %s, "
                       "only in the buildings/land/units registers %s, only in service charges %s"
                       % tuple(format(x, ",") for x in (tot, n_id, tot - n_id, in_pr, in_y, reg_only, sc_only)),
                       "projects with an English name %s; with an area %s; with a developer number %s; project ids holding several numbers %s"
                       % (pct(named, tot), pct(with_area, tot), pct(with_dev, tot), format(multi, ",")),
                       "developers: %s (in the developers register %s); developer of at least one project %s; master developer %s; "
                       "projects whose developer number the developers register lacks %s"
                       % tuple(format(x, ",") for x in (dtot, d_reg, d_dev, d_mas, no_dev))] + churn +
                      ["board developers keyed: %d of %d" % (keyed, len(groups))] +
                      ["  %-13s %s" % (dev, ", ".join("%s %d" % kv for kv in sorted(c.items())) or "no evidence") for dev, c in per.items()] +
                      ["group links for review: %d (%s)" % (len(review_rows), os.path.relpath(GROUP_REVIEW, ROOT))]}


def job_place_spine(con):
    """Digital thread P2.1 + P2.2 (16 Sep 2026): one table per place the registers number, with the parcel's own lineage.

      lk_d_area       area:<area_id> - the DLD's areas, each with the Municipality community it sits in (lkp_areas), and what the registers
                      hold there: parcels, buildings, units, projects.
      lk_d_community  comm:<comm_num> - the Municipality's communities, from the areas that name one and from every parcel key on record
                      (comm_num = parcel_key / 10000, exact on all 231,108 parcels). Carries what the community job already measured (name,
                      point, population, bus coverage, DEWA move-ins) where it has it, so nothing is counted twice.
      lk_d_parcel     pcl:<parcel_key> - every registered land parcel: its area, community, project, land and property type, size, and
                      LINEAGE - separated_from is the property id of the parcel it was split from, and every one of the 110,951 splits
                      resolves, so each parcel carries its parent's key, the key it descends from and how many splits deep it is.
      lk_d_building   bld:<property_id> - every registered building: parcel, project, area, community, floors, flats, offices, shops,
                      parking and size, with the Municipality's own buildings on the same parcel counted beside it (lk_dm_buildings).
      v_thread_parcel  parcel -> community, area, project, its buildings and its parent parcel.
    Held (nothing replaced) when more than 1% of the canonical ids published last time vanish (gate C6)."""
    L = read(register_files("land_registry", "dld__land_registry__*.csv"))
    B = read(register_files("buildings", "dld__buildings__*.csv"))
    U = read(register_files("units", "dld__units__*.csv"))
    LK = read(register_files("lkp_areas", "dld__lkp_areas__*.csv"))
    txt = lambda c: "nullif(trim(%s), '')" % c
    dbl = lambda c: "try_cast(%s as double)" % c
    cnt = lambda c: "try_cast(try_cast(%s as double) as bigint)" % c
    yes = lambda c: "case when trim(cast(%s as varchar)) in ('1', 'true', 'True') then true when trim(cast(%s as varchar)) in ('0', 'false', 'False') then false end" % (c, c)
    con.execute("""create or replace temp table j_pl_parcel as
        select %s parcel_key, %s property_id, %s area_id, %s project_id, %s land_number, %s land_sub_number, %s land_type,
               %s property_type, %s property_sub_type, %s actual_area, %s is_free_hold, %s is_registered, %s master_project_id,
               %s master_project_en, %s zone_id, %s munc_zip_code, %s separated_from
        from %s where %s is not null
        qualify row_number() over (partition by %s order by property_id) = 1""" % (
        parcel_key("parcel_id"), num("property_id"), num("area_id"), num("project_id"), txt("land_number"), txt("land_sub_number"),
        txt("land_type_en"), txt("property_type_en"), txt("property_sub_type_en"), dbl("actual_area"), yes("is_free_hold"),
        yes("is_registered"), num("master_project_id"), txt("master_project_en"), num("zone_id"), num("munc_zip_code"),
        num("separated_from"), L, parcel_key("parcel_id"), parcel_key("parcel_id")))
    con.execute("""create or replace temp table j_pl_bld as
        select %s property_id, %s parcel_key, %s project_id, %s area_id, %s building_number, %s parent_property_id, %s floors,
               %s bld_levels, %s flats, %s offices, %s shops, %s car_parks, %s elevators, %s built_up_area, %s actual_area,
               %s property_sub_type, %s is_registered, %s master_project_en, try_cast(left(trim(creation_date), 10) as date) creation_date
        from %s where %s is not null
        qualify row_number() over (partition by %s order by creation_date desc nulls last) = 1""" % (
        num("property_id"), parcel_key("parcel_id"), num("project_id"), num("area_id"), txt("building_number"), num("parent_property_id"),
        cnt("floors"), cnt("bld_levels"), cnt("flats"), cnt("offices"), cnt("shops"), cnt("car_parks"), cnt("elevators"),
        dbl("built_up_area"), dbl("actual_area"), txt("property_sub_type_en"), yes("is_registered"), txt("master_project_en"),
        B, num("property_id"), num("property_id")))
    con.execute("""create or replace temp table j_pl_units as
        select %s area_id, %s parcel_key, count(*) units from %s group by 1, 2""" % (num("area_id"), parcel_key("parcel_id"), U))
    con.execute("""create or replace temp table j_pl_areas as
        select %s area_id, %s name_en, %s name_ar, %s comm_num from %s where %s is not null
        qualify row_number() over (partition by %s order by name_en) = 1""" % (
        num("area_id"), txt("name_en"), txt("name_ar"), num("municipality_number"), LK, num("area_id"), num("area_id")))
    # lineage: separated_from is the parent's property id, so a parcel gets its parent's key, the key it descends from, and its depth
    con.execute("""create or replace temp table j_pl_lineage as
        with recursive parent as (select c.parcel_key, m.parcel_key parent_parcel_key
                        from j_pl_parcel c join j_pl_parcel m on m.property_id = c.separated_from where m.parcel_key <> c.parcel_key),
             walk as (select parcel_key, parent_parcel_key, parent_parcel_key root_parcel_key, 1 generation from parent
                      union all
                      select w.parcel_key, w.parent_parcel_key, p.parent_parcel_key, w.generation + 1
                      from walk w join parent p on p.parcel_key = w.root_parcel_key where w.generation < 8)
        select parcel_key, any_value(parent_parcel_key) parent_parcel_key,
               case when max(generation) >= 8 then null else max(generation) end split_generation,
               case when max(generation) >= 8 then null else arg_max(root_parcel_key, generation) end root_parcel_key,
               max(generation) >= 8 lineage_loop            -- 159 parcels name each other as the parcel they were split from
        from walk group by 1""")
    con.execute("""create or replace temp table j_d_parcel as
        select 'pcl:' || cast(p.parcel_key as varchar) canonical_id, p.parcel_key, p.property_id, p.area_id, a.name_en area_name_en,
               p.parcel_key // 10000 comm_num, p.project_id, p.land_number, p.land_sub_number, p.land_type, p.property_type,
               p.property_sub_type, p.actual_area, p.is_free_hold, p.is_registered, p.master_project_id, p.master_project_en, p.zone_id,
               p.munc_zip_code, p.separated_from parent_property_id, l.parent_parcel_key,
               case when l.lineage_loop then null else coalesce(l.split_generation, 0) end split_generation,
               case when l.lineage_loop then null else coalesce(l.root_parcel_key, p.parcel_key) end root_parcel_key,
               coalesce(l.lineage_loop, false) lineage_loop, coalesce(b.buildings, 0) register_buildings,
               coalesce(d.dm_buildings, 0) dm_buildings, coalesce(u.units, 0) register_units
        from j_pl_parcel p left join j_pl_areas a on a.area_id = p.area_id left join j_pl_lineage l on l.parcel_key = p.parcel_key
        left join (select parcel_key, count(*) buildings from j_pl_bld where parcel_key is not null group by 1) b on b.parcel_key = p.parcel_key
        left join (select parcel_key, count(*) dm_buildings from lk_dm_buildings where parcel_key is not null group by 1) d on d.parcel_key = p.parcel_key
        left join (select parcel_key, sum(units) units from j_pl_units where parcel_key is not null group by 1) u on u.parcel_key = p.parcel_key""")
    con.execute("""create or replace temp table j_d_building as
        select 'bld:' || cast(b.property_id as varchar) canonical_id, b.property_id, b.parcel_key, b.parcel_key // 10000 comm_num,
               b.area_id, a.name_en area_name_en, b.project_id, b.building_number, b.parent_property_id, b.floors, b.bld_levels, b.flats,
               b.offices, b.shops, b.car_parks, b.elevators, b.built_up_area, b.actual_area, b.property_sub_type, b.is_registered,
               b.master_project_en, b.creation_date, coalesce(d.dm_buildings, 0) dm_buildings_on_parcel
        from j_pl_bld b left join j_pl_areas a on a.area_id = b.area_id
        left join (select parcel_key, count(*) dm_buildings from lk_dm_buildings where parcel_key is not null group by 1) d
          on d.parcel_key = b.parcel_key""")
    con.execute("""create or replace temp table j_d_area as
        select 'area:' || cast(a.area_id as varchar) canonical_id, a.area_id, a.name_en, a.name_ar, a.comm_num,
               coalesce(p.parcels, 0) parcels, coalesce(p.free_hold, 0) free_hold_parcels, coalesce(b.buildings, 0) register_buildings,
               coalesce(u.units, 0) register_units, coalesce(j.projects, 0) projects, coalesce(j.planned_units, 0) planned_units
        from j_pl_areas a
        left join (select area_id, count(*) parcels, count(*) filter (where is_free_hold) free_hold from j_pl_parcel group by 1) p on p.area_id = a.area_id
        left join (select area_id, count(*) buildings from j_pl_bld where area_id is not null group by 1) b on b.area_id = a.area_id
        left join (select area_id, sum(units) units from j_pl_units where area_id is not null group by 1) u on u.area_id = a.area_id
        left join (select area_id, count(*) projects, sum(planned_units) planned_units from lk_d_project where area_id is not null group by 1) j
          on j.area_id = a.area_id""")
    has_comm = lake_has(con, "lk_community")
    con.execute("""create or replace temp table j_d_community as
        with nums as (select comm_num from j_pl_areas where comm_num is not null
                      union select comm_num from j_d_parcel where comm_num is not null %s)
        select 'comm:' || cast(n.comm_num as varchar) canonical_id, n.comm_num, %s,
               (select list_sort(list(distinct a.area_id)) from j_pl_areas a where a.comm_num = n.comm_num) area_ids,
               (select count(*) from j_pl_areas a where a.comm_num = n.comm_num) areas,
               coalesce(p.parcels, 0) parcels, coalesce(p.register_buildings, 0) register_buildings,
               coalesce(p.register_units, 0) register_units, coalesce(d.dm_buildings, 0) dm_buildings
        from nums n %s
        left join (select comm_num, count(*) parcels, sum(register_buildings) register_buildings, sum(register_units) register_units
                   from j_d_parcel where comm_num is not null group by 1) p on p.comm_num = n.comm_num
        left join (select %s comm_num, count(*) dm_buildings from lk_dm_buildings where community_no is not null group by 1) d
          on d.comm_num = n.comm_num""" % (
        "union select comm_num from lk_community where comm_num is not null" if has_comm else "",
        ("c.dm_name_en name_en, c.dm_name_ar name_ar, c.lon, c.lat, c.population, c.bus_coverage_pct, c.dewa_move_ins"
         if has_comm else "null::varchar name_en, null::varchar name_ar, null::double lon, null::double lat, null::bigint population, "
                          "null::double bus_coverage_pct, null::bigint dewa_move_ins"),
        "left join lk_community c on c.comm_num = n.comm_num" if has_comm else "", num("community_no")))

    hold, churn = None, []
    for table, tmp in (("lk_d_parcel", "j_d_parcel"), ("lk_d_building", "j_d_building"), ("lk_d_area", "j_d_area"),
                       ("lk_d_community", "j_d_community")):
        if not lake_has(con, table):
            churn.append("%s: first publish" % table)
            continue
        old, gone = one(con, """select count(*), count(*) filter (where n.canonical_id is null)
            from %s o left join %s n on n.canonical_id = o.canonical_id""" % (table, tmp))
        churn.append("%s: %s of %s ids published last time vanished" % (table, format(gone, ","), format(old, ",")))
        if old and gone > CHURN_MAX * old:
            hold = "id churn on %s: %s of %s ids vanished (limit %.0f%%)" % (table, format(gone, ","), format(old, ","), 100 * CHURN_MAX)
    parcels, with_comm, with_area, with_project, split, deepest, loops = one(con, """select count(*), count(comm_num), count(area_id),
        count(project_id), count(parent_parcel_key), max(split_generation), count(*) filter (where lineage_loop) from j_d_parcel""")
    blds, b_parcel, b_project = one(con, "select count(*), count(parcel_key), count(project_id) from j_d_building")
    areas, a_comm = one(con, "select count(*), count(comm_num) from j_d_area")
    comms, c_named = one(con, "select count(*), count(name_en) from j_d_community")
    view = """select p.canonical_id, p.parcel_key, p.comm_num, c.name_en community_name_en, p.area_id, p.area_name_en, p.project_id,
                     j.name_en project_name_en, j.developer_number, p.land_type, p.property_sub_type, p.actual_area, p.is_free_hold,
                     p.register_buildings, p.dm_buildings, p.register_units, p.parent_parcel_key, p.split_generation, p.root_parcel_key,
                     p.lineage_loop
              from lk_d_parcel p left join lk_d_community c on c.comm_num = p.comm_num
              left join lk_d_project j on j.project_id = p.project_id"""
    return {"tables": [("lk_d_parcel", "select * from j_d_parcel"), ("lk_d_building", "select * from j_d_building"),
                       ("lk_d_area", "select * from j_d_area"), ("lk_d_community", "select * from j_d_community")],
            "views": [("v_thread_parcel", view)],
            "keys_in": parcels, "keys_matched": with_comm, "rows_in": parcels + blds, "hold": hold,
            "note": "registered parcels carrying a Municipality community number",
            "report": ["parcels: %s - with a community %s, with an area %s, with a project %s; split from another parcel %s (deepest chain %s)"
                       % (format(parcels, ","), pct(with_comm, parcels), pct(with_area, parcels), pct(with_project, parcels),
                          format(split, ","), deepest),
                       "parcels whose split chain loops back on itself (lineage left empty): " + format(loops, ","),
                       "register buildings: %s - on a parcel %s, with a project %s" % (format(blds, ","), pct(b_parcel, blds), pct(b_project, blds)),
                       "areas: %s, with a community number %s; communities: %s, named by the Municipality %s"
                       % (format(areas, ","), pct(a_comm, areas), format(comms, ","), pct(c_named, comms))] + churn}


def job_districts(con):
    """Digital thread P2.4 (16 Sep 2026): the twin's districts as a GROUPING over the registers' own places, never a join key.

    A district is Najma's own slice of the city (data/board/districts_geo.json, the twin's view areas) - the DLD has areas and the
    Municipality has communities, and several scripts each keep their own hand list of what a district contains. This publishes the
    grouping the registers themselves imply: each district's sub-community cards carry a DLD area (register_joins sub_communities), and
    each area carries a Municipality community (lkp_areas), so district -> area -> community falls out, with the share of cards, plots and
    units behind every link, and lk_d_district carries what the registers hold inside that district.

    Publishes lk_d_district, lk_xref job district_area (the share is on the row) and v_thread_district."""
    geo = os.path.join(ROOT, "data", "board", "districts_geo.json")
    if not os.path.exists(geo) or not lake_has(con, "lk_sub_community") or not lake_has(con, "lk_d_area"):
        raise RuntimeError("needs data/board/districts_geo.json, lk_sub_community (sub_communities) and lk_d_area (place_spine)")
    D = json.load(open(geo, encoding="utf-8")).get("districts") or []
    con.execute("""create or replace temp table j_dist (slug varchar, name varchar, corridor varchar, lon double, lat double,
                   bbox_w double, bbox_s double, bbox_e double, bbox_n double, twin_buildings bigint, twin_named bigint)""")
    con.executemany("insert into j_dist values (?,?,?,?,?,?,?,?,?,?,?)", [
        [d.get("slug"), d.get("name"), d.get("corridor"), (d.get("centre") or [None, None])[0], (d.get("centre") or [None, None])[1],
         *(d.get("bbox") or [None, None, None, None]), d.get("buildings"), d.get("named")] for d in D if d.get("slug")])
    con.execute("""create or replace temp table j_dist_area as
        select s.district, s.area_id, a.name_en area_name_en, a.comm_num, count(*) cards, sum(coalesce(s.plots, 0)) plots,
               sum(coalesce(s.units, 0)) units, count(*) filter (where s.decision = 'accepted') keyed_cards
        from lk_sub_community s join lk_d_area a on a.area_id = s.area_id where s.area_id is not null group by 1, 2, 3, 4""")
    con.execute("""create or replace temp table j_d_district as
        select 'dist:' || d.slug canonical_id, d.slug, d.name, d.corridor, d.lon, d.lat, d.bbox_w, d.bbox_s, d.bbox_e, d.bbox_n,
               d.twin_buildings, d.twin_named, coalesce(x.areas, 0) areas, coalesce(x.communities, 0) communities,
               coalesce(x.cards, 0) sub_community_cards, coalesce(x.plots, 0) card_plots, coalesce(x.units, 0) card_units,
               x.area_ids, x.comm_nums, coalesce(p.parcels, 0) register_parcels, coalesce(p.register_buildings, 0) register_buildings,
               coalesce(p.register_units, 0) register_units
        from j_dist d
        left join (select district, count(distinct area_id) areas, count(distinct comm_num) communities, sum(cards) cards,
                          sum(plots) plots, sum(units) units, list_sort(list(distinct area_id)) area_ids,
                          list_sort(list(distinct comm_num)) comm_nums
                   from j_dist_area group by 1) x on x.district = d.slug
        left join (select da.district, count(*) parcels, sum(pa.register_buildings) register_buildings, sum(pa.register_units) register_units
                   from lk_d_parcel pa join (select distinct district, area_id from j_dist_area) da on da.area_id = pa.area_id
                   group by 1) p on p.district = d.slug""")
    now = dt.datetime.now().replace(microsecond=0)
    run_id = "districts@" + now.isoformat()
    snapshot = "districts_geo.json (%d districts); lk_sub_community; lk_d_area" % len(D)
    xref = [["district_area", "district", "dist:" + slug, "area", "area:" + str(aid), "covers", "sub-community cards in the area",
             round(share, 3), "accepted", "rule",
             "%d of the district's %d cards, %s plots, %s units - %s (community %s)"
             % (cards, total, format(plots or 0, ","), format(units or 0, ","), aname, comm if comm is not None else "none"),
             snapshot, now, None, run_id]
            for slug, aid, aname, comm, cards, plots, units, total, share in con.execute("""
                select district, area_id, area_name_en, comm_num, cards, plots, units,
                       sum(cards) over (partition by district), cards / sum(cards) over (partition by district)
                from j_dist_area""").fetchall()]
    con.execute(XREF_DDL.replace("create table if not exists lk_xref", "create or replace temp table j_xref_dist"))
    if xref:
        con.executemany("insert into j_xref_dist values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", xref)
    dists, with_area, multi = one(con, "select count(*), count(*) filter (where areas > 0), count(*) filter (where areas > 1) from j_d_district")
    areas_covered, comms_covered = one(con, "select count(distinct area_id), count(distinct comm_num) from j_dist_area")
    shared = one(con, """select count(*) from (select area_id from (select distinct district, area_id from j_dist_area)
                         group by 1 having count(*) > 1)""")[0]
    view = """select d.canonical_id, d.slug, d.name, d.corridor, d.areas, d.communities, d.sub_community_cards, d.register_parcels,
                     d.register_buildings, d.register_units, x.to_id area_canonical_id, a.area_id, a.name_en area_name_en, a.comm_num,
                     c.name_en community_name_en, x.score card_share
              from lk_d_district d left join lk_xref x on x.job = 'district_area' and x.from_id = d.canonical_id
              left join lk_d_area a on 'area:' || cast(a.area_id as varchar) = x.to_id
              left join lk_d_community c on c.comm_num = a.comm_num"""
    return {"tables": [("lk_d_district", "select * from j_d_district")],
            "xref": [("district_area", "j_xref_dist")],
            "views": [("v_thread_district", view)],
            "keys_in": dists, "keys_matched": with_area, "rows_in": dists,
            "note": "twin districts their own cards place in at least one DLD area",
            "report": ["districts: %s - placed in a DLD area by their own cards %s, spanning more than one area %s"
                       % (format(dists, ","), pct(with_area, dists), format(multi, ",")),
                       "areas covered: %s; communities reached: %s; areas two districts share: %s"
                       % (format(areas_covered, ","), format(comms_covered, ","), format(shared, ",")),
                       "district -> area links: %s (each carries the share of the district's cards behind it)" % format(len(xref), ",")]}


STATION_REVIEW = os.path.join(ROOT, "data", "identity", "station_review.csv")


def job_stations(con):
    """Digital thread P2.5 (16 Sep 2026): the RTA's own station ids, and the sales register's nearest-metro name keyed to them.

    Every amenity the pipeline carries was minted from its content; the RTA publishes a station id (location_id) for each metro and tram
    station, so a station is poi:rta:<location_id> - the source's key, not ours (data/registers/{metro,tram}_stations). The sales register
    names a nearest station in free text on 47.8% of its rows, in its own spellings ("Buj Khalifa Dubai Mall", "Trade Centre", plural
    "Stations"), so each name is matched to a station: the same name, the name inside the station's name (or the station's inside it) when
    only one station fits, or one letter apart. A name that fits several stations, or none, goes to review and is never guessed - the
    register still names stations the RTA has since renamed (Sharaf DG, Palm Deira), which only a person should decide.

    Publishes lk_d_station, lk_xref job sale_station, and review rows to data/identity/station_review.csv."""
    import collections
    from keys import name_norm
    strip = re.compile(r"\b(metro|tram)?\s*stations?\b", re.I)
    sn = lambda s: name_norm(strip.sub(" ", s or ""))
    rows = []
    for folder, mode in (("metro_stations", "metro"), ("tram_stations", "tram")):
        for f in sorted(glob.glob(os.path.join(ROOT, "data", "registers", folder, "*.csv"))):
            with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
                for r in csv.DictReader(fh):
                    lid = (r.get("location_id") or "").strip()
                    nm = (r.get("location_name_english") or "").strip()
                    if not (lid and nm) or (r.get("station_closing_date") or "").strip():
                        continue
                    line = (r.get("line_name") or ("Tram" if mode == "tram" else "")).replace(" Metro line", " line").strip()
                    rows.append(["poi:rta:" + lid, int(lid), " ".join(nm.split()), (r.get("location_name_arabic") or "").strip() or None, mode,
                                 line or None, (r.get("zone_id") or "").strip() or None, float(r["station_location_longitude"]),
                                 float(r["station_location_latitude"]), (r.get("station_opening_date") or "").strip()[:10] or None])
    if not rows:
        raise RuntimeError("no RTA station register on disk (data/registers/metro_stations)")
    rows = {r[1]: r for r in rows}                          # one row per location id, whatever the extract repeats
    rows = [rows[k] for k in sorted(rows)]
    same = collections.defaultdict(list)
    for r in rows:
        same[sn(r[2])].append(r[1])                          # an interchange is one name on two lines (BurJuman, Union)
    for r in rows:
        r.append(sorted(x for x in same[sn(r[2])] if x != r[1]))
    con.execute("""create or replace temp table j_d_station (canonical_id varchar, location_id bigint, name_en varchar, name_ar varchar,
                   mode varchar, line varchar, zone_id varchar, lon double, lat double, opened varchar, interchange_ids bigint[])""")
    con.executemany("insert into j_d_station values (?,?,?,?,?,?,?,?,?,?,?)", rows)

    def dist1(a, b):                                        # one insertion, deletion or substitution apart
        if abs(len(a) - len(b)) > 1:
            return False
        if len(a) == len(b):
            return sum(x != y for x, y in zip(a, b)) == 1
        lo, hi = (a, b) if len(a) < len(b) else (b, a)
        for i in range(len(hi)):
            if hi[:i] + hi[i + 1:] == lo:
                return True
        return False

    by_name = collections.defaultdict(list)
    for r in rows:
        by_name[sn(r[2])].append(r)
    now = dt.datetime.now().replace(microsecond=0)
    run_id = "stations@" + now.isoformat()
    snapshot = "RTA metro + tram station registers; %s" % ("dld_transactions_now" if lake_has(con, "dld_transactions_now") else "no sales")
    names = con.execute("""select nullif(trim(NEAREST_METRO_EN), ''), count(*) from dld_transactions_now
                           where nullif(trim(NEAREST_METRO_EN), '') is not null group by 1""").fetchall() if lake_has(con, "dld_transactions_now") else []
    total = one(con, "select count(*) from dld_transactions_now")[0] if lake_has(con, "dld_transactions_now") else 0
    xref, review, reached = [], [], 0
    for nm, n in sorted(names, key=lambda x: -x[1]):
        k = sn(nm)
        hits = by_name.get(k) or []
        method = "the station's own name"
        if not hits:
            inside = [r for r in rows if k and (k in sn(r[2]) or sn(r[2]) in k)]
            hits, method = (inside, "the name inside the station's name") if len(inside) == 1 else (hits, method)
        if not hits:
            near = [r for r in rows if dist1(k, sn(r[2]))]
            hits, method = (near, "one letter from the station's name") if len(near) == 1 else (hits, method)
        decision = "accepted" if hits else "review"
        if hits:
            reached += n
        else:
            cand = [r for r in rows if k and (k.split(" ")[0] == sn(r[2]).split(" ")[0] or k[:6] in sn(r[2]))][:4]
            review.append([nm, n, ", ".join(r[2] for r in cand)[:120], "no station fits the name"])
        for r in hits:
            xref.append(["sale_station", "sales_name", "salemetro:" + nm, "poi", r[0], "nearest station", method, 1.0, decision, "rule",
                         "%s sales rows name '%s' = %s (%s%s)" % (format(n, ","), nm, r[2], r[5] or r[4],
                                                                  ", zone " + r[6] if r[6] else ""), snapshot, now, None, run_id])
    con.execute(XREF_DDL.replace("create table if not exists lk_xref", "create or replace temp table j_xref_station"))
    if xref:
        con.executemany("insert into j_xref_station values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", xref)
    named = sum(n for _, n in names)
    metro, tram = sum(1 for r in rows if r[4] == "metro"), sum(1 for r in rows if r[4] == "tram")
    return {"tables": [("lk_d_station", "select * from j_d_station")],
            "xref": [("sale_station", "j_xref_station")],
            "keys_in": named, "keys_matched": reached, "rows_in": total,
            "note": "sales rows whose nearest-station name reaches an RTA station id",
            "review_csv": (STATION_REVIEW, ["register_name", "sales_rows", "nearest_stations", "why"], review),
            "report": ["RTA stations: %s (metro %d, tram %d), keyed by the RTA's own location id" % (format(len(rows), ","), metro, tram),
                       "sales rows naming a station: %s of %s; reaching a station id: %s"
                       % (format(named, ","), format(total, ","), pct(reached, total)),
                       "names left for review (the register's own spellings, or stations since renamed): %d - %s"
                       % (len(review), "; ".join("%s (%s rows)" % (r[0], format(r[1], ",")) for r in review[:6]))]}


SUB_REVIEW = os.path.join(ROOT, "data", "identity", "sub_community_review.csv")


def job_sub_communities(con):
    """Digital thread P2.3 (16 Sep 2026): the sub-community cards keyed to the DLD project they are.

    The cards (data/names/clusters_<district>.json, cluster_names.py) are the sub-community each PLOT belongs to in the land and units
    registers - Maple 2, Sidra, Golf Promenade - geocoded once each and drawn on the map as a point with a radius. Their ids were list
    positions (SUB-<district>-<k> in graph_build), so inserting one card renumbered every card after it. Each card's name is a registered
    project name in its own DLD area, so the card IS that project: matched on the normalised English name inside the file's own area, it
    takes that project's canonical id and never moves again. A name several projects in the area carry goes to review and keeps a content
    id - the hash of the name - which is stable too.

    Publishes lk_sub_community (one row per card, with the point, radius, plots, units, footprints and Google place id it carries) and
    lk_xref job sub_community; review rows to data/identity/sub_community_review.csv."""
    import collections
    import hashlib
    from keys import name_norm
    if not lake_has(con, "lk_d_project") or not lake_has(con, "lk_d_area"):
        raise RuntimeError("needs the project and place spines (project_spine, place_spine)")
    areas = {name_norm(n): (a, n) for a, n in con.execute("select area_id, name_en from lk_d_area").fetchall()}
    by_name, pname = collections.defaultdict(set), {}
    for aid, cid, nm, names in con.execute("""select area_id, canonical_id, name_en, names_en from lk_d_project
                                              where area_id is not null and project_id is not null""").fetchall():
        pname[cid] = nm
        for n in [nm] + list(names or []):
            if name_norm(n):
                by_name[(aid, name_norm(n))].add(cid)
    now = dt.datetime.now().replace(microsecond=0)
    run_id = "sub_communities@" + now.isoformat()
    files = sorted(glob.glob(os.path.join(ROOT, "data", "names", "clusters_*.json")))
    snapshot = "%d cluster files; lk_d_project; lk_d_area" % len(files)
    rows, xref, review, cards, dupes = [], [], [], set(), []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slug = d.get("district") or os.path.basename(f)[9:-5]
        aid, area_name = areas.get(name_norm(d.get("area") or ""), (None, d.get("area")))
        for c in d.get("clusters") or []:
            name = (c.get("name") or "").strip()
            if not name:
                continue
            spot = (slug, name_norm(name), "%.5f" % (c.get("lon") or 0), "%.5f" % (c.get("lat") or 0))
            if spot in cards:                              # the same card twice in one file (MAPLE 2 in Dubai Hills): one place, one id
                dupes.append(spot)
                continue
            cards.add(spot)
            cands = sorted(by_name.get((aid, name_norm(name)), set())) if aid is not None else []
            fid = "subc:%s:%s" % (slug, name)
            if len(cands) == 1:
                cid, decision, method = cands[0], "accepted", "registered project name in the card's own area"
            else:
                cid, decision = None, "review" if cands else "unmatched"
                method = ("several projects in the area carry the name" if cands else
                          "no project of that name in the area" if aid is not None else "the card's area is not in the register")
            rows.append([None, slug, name, aid, area_name, cid, decision, method, c.get("lon"), c.get("lat"), c.get("radius_m"),
                         c.get("plots"), c.get("units"), c.get("footprints"), c.get("place_id"), c.get("place_name")])
            for hit in cands:
                xref.append(["sub_community", "sub_community", fid, "project", hit, "same place", method,
                             1.0 if decision == "accepted" else 0.5, decision, "rule",
                             "card '%s' in %s = registered '%s'" % (name, area_name or slug, pname.get(hit) or hit), snapshot, now, None, run_id])
            if decision != "accepted":
                review.append([slug, area_name, name, ", ".join(pname.get(x) or x for x in cands)[:160], method, c.get("plots"), c.get("units")])
    # the id: the project's own, so the card never moves; a project several cards divide keeps them apart by district, and by the name's
    # hash where even that is shared. A card with no single project takes the hash of its name - stable too, just not a register key.
    shared = collections.Counter(r[5] for r in rows if r[5])
    seen = collections.Counter()
    for r in rows:
        h = hashlib.sha1(("%s|%s|%.5f|%.5f" % (r[1], name_norm(r[2]), r[8] or 0, r[9] or 0)).encode("utf-8")).hexdigest()[:8]
        if not r[5]:
            r[0] = "subc:%s:%s" % (r[1], h)
        elif shared[r[5]] == 1:
            r[0] = r[5]
        else:
            seen[(r[5], r[1])] += 1
            r[0] = "%s:%s" % (r[5], r[1]) if seen[(r[5], r[1])] == 1 else "%s:%s:%s" % (r[5], r[1], h)
    con.execute("""create or replace temp table j_sub_community (canonical_id varchar, district varchar, name varchar, area_id bigint,
                   area_name varchar, project_canonical_id varchar, decision varchar, link_method varchar, lon double, lat double,
                   radius_m double, plots bigint, units bigint, footprints bigint, place_id varchar, place_name varchar)""")
    if rows:
        con.executemany("insert into j_sub_community values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute(XREF_DDL.replace("create table if not exists lk_xref", "create or replace temp table j_xref_subc"))
    if xref:
        con.executemany("insert into j_xref_subc values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", xref)
    tot, acc, rev, unm, dup = one(con, """select count(*), count(*) filter (where decision = 'accepted'),
        count(*) filter (where decision = 'review'), count(*) filter (where decision = 'unmatched'),
        (select count(*) from (select project_canonical_id from j_sub_community where project_canonical_id is not null
                               group by 1 having count(*) > 1)) from j_sub_community""")
    plots, units = one(con, "select sum(plots), sum(units) from j_sub_community where decision = 'accepted'")
    uniq = one(con, "select count(distinct canonical_id) from j_sub_community")[0]
    return {"tables": [("lk_sub_community", "select * from j_sub_community")],
            "xref": [("sub_community", "j_xref_subc")],
            "keys_in": tot, "keys_matched": acc, "rows_in": tot,
            "note": "sub-community cards keyed to the DLD project they name",
            "review_csv": (SUB_REVIEW, ["district", "area", "card", "projects", "method", "plots", "units"], review),
            "report": ["sub-community cards: %s - keyed to a registered project %s, for review %s, no registered name %s"
                       % (format(tot, ","), pct(acc, tot), format(rev, ","), format(unm, ",")),
                       "keyed cards carry %s plots and %s units; projects divided across several cards (each card keeps its own id): %s"
                       % (format(plots or 0, ","), format(units or 0, ","), format(dup, ",")),
                       "ids unique: %s of %s%s" % (format(uniq, ","), format(tot, ","),
                                                   "; the same card twice in one file, kept once: %d" % len(dupes) if dupes else "")]}


SHEET_REVIEW = os.path.join(ROOT, "data", "identity", "sheet_register_review.csv")
SQFT_SQM = 0.09290304
SIZE_TOL = 0.03


def units_files():
    """The fullest units register on disk: the newest manual download (data/raw_downloads/units_<date>_<time>_000N.csv, every part - the
    portal extract holds one part of three), else the portal extract."""
    found = sorted(glob.glob(os.path.join(ROOT, "data", "raw_downloads", "units_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_*.csv")))
    if found:
        stamp = max(re.search(r"units_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", os.path.basename(p)).group(1) for p in found)
        return [p for p in found if stamp in os.path.basename(p)], "manual download " + stamp
    return register_files("units", "dld__units__*.csv"), "portal extract"


def job_sheet_units(con):
    """Digital thread P1.4 (15 Sep 2026): the developers' availability sheets -> the DLD register, as crosswalk rows.

      sheet project -> project_id   each (developer, project) of lk_avail_units against the registered projects of that developer's own DLD
                                    entities (accepted lk_xref developer_group links -> lk_d_project): a registered English name equal to the
                                    sheet's after build_developer_dna.norm_name, tower / building / block suffixes removed ("Hado Tower A" =
                                    "Hado By Beyond"). One project -> accepted. Several, a name inside a registered name or the reverse, or a
                                    name only a project of another entity carries -> review. Nothing -> no row (Aljada is in Sharjah, not in
                                    the Dubai register).
      sheet unit -> property_id     inside an accepted project: the sheet unit number (the last digit group of its id) among the digits of the
                                    register unit number, and the sheet size within 3% of the register's actual area, with or without the
                                    balcony. Several candidates are narrowed by the building: first the register unit number whose whole digit
                                    sequence ends the sheet's ("WRDH1-0101" = "1-0101"), then the letter or digit that tells the sheet's
                                    buildings apart (HADA / HADB / HADC, AYA2B / AYA2C, TSA / TSB) against the letter the register writes first
                                    ("C104", "BG01") or, where it writes none, the building ordinal. One candidate -> accepted; several, or the
                                    number with a different size -> review.
    Keys: sht:<developer>:<project> and shu:<developer>:<project>:<unit id> - the sheet's own names, stable across readings of a project (the
    id a unit carries in lk_avail_units). Writes lk_xref jobs sheet_project and sheet_unit, lk_sheet_register (one row per sheet unit) and
    v_thread_unit; review rows to data/identity/sheet_register_review.csv."""
    import collections
    import build_developer_dna as dna                      # side-effect free at import
    from keys import name_norm as name_norm_py
    if not all(lake_has(con, t) for t in ("lk_avail_units", "lk_xref", "lk_d_project", "lk_d_developer")):
        raise RuntimeError("needs lk_avail_units (avail_intervals) and the project spine (project_spine)")
    seg = json.load(open(dna.SEG_FILE, encoding="utf-8"))
    key_dev = {v: k for k, v in dna.PORT_KEY.items()}
    tower = re.compile(r"\b(tower|towers|building|block|phase|cluster)\s+[a-z0-9]{1,2}\b", re.I)
    sheet_units = con.execute("select developer, project, unit_id, unit_type, sqft, last_seen from lk_avail_units").fetchall()
    projects = sorted({(u[0], u[1]) for u in sheet_units})
    group_projects = collections.defaultdict(list)
    for gk, cid, pid, nm, names, area, dn in con.execute("""select substr(x.from_id, 5), p.canonical_id, p.project_id, p.name_en, p.names_en,
            p.area_name_en, p.developer_number from lk_xref x join lk_d_developer d on d.canonical_id = x.to_id
            join lk_d_project p on p.developer_number = d.developer_number
            where x.job = 'developer_group' and x.decision = 'accepted'""").fetchall():
        group_projects[gk].append((cid, pid, [n for n in [nm] + list(names or []) if n], area))
    everything = [(cid, pid, [n for n in [nm] + list(names or []) if n], area, dn) for cid, pid, nm, names, area, dn in con.execute(
        "select canonical_id, project_id, name_en, names_en, area_name_en, developer_number from lk_d_project").fetchall()]
    now = dt.datetime.now().replace(microsecond=0)
    run_id = "sheet_units@" + now.isoformat()
    ufiles, usource = units_files()
    snapshot = "lk_avail_units; lk_d_project; units " + usource

    def xrow(job, ftype, fid, ttype, tid, rel, method, score, decision, evidence):
        return [job, ftype, fid, ttype, tid, rel, method, score, decision, "rule", evidence[:400], snapshot, now, None, run_id]

    # --- sheet project -> project_id
    xp, proj_link, review = [], {}, []
    memo = {}
    for dev_key, proj in projects:
        al = seg["aliases"].get(key_dev.get(dev_key), [dev_key])

        def pn(n, al=al, dev_key=dev_key):
            k = (dev_key, n)
            if k not in memo:
                memo[k] = dna.norm_name(tower.sub(" ", n or ""), al).replace(" ", "")
            return memo[k]
        target = pn(proj)
        mine = group_projects.get(dev_key) or []
        exact = {c[0]: c for c in mine if target and any(pn(n) == target for n in c[2])}
        near = {} if exact else {c[0]: c for c in mine if target and any(len(pn(n)) >= 4 and (pn(n) in target or target in pn(n)) for n in c[2])}
        # outside the developer's own projects: the sheet's name exactly as registered ("IMTIAZ SYMPHONY TOWER"), else the stripped name
        # ("symphony" - Nshama's Town Square project, never Imtiaz's)
        plain = {} if (exact or near) else {c[0]: c for c in everything if name_norm_py(proj) and any(name_norm_py(n) == name_norm_py(proj) for n in c[2])}
        other = {} if (exact or near or plain) else {c[0]: c for c in everything if target and len(target) >= 4 and any(pn(n) == target for n in c[2])}
        lone = list(plain.values())[0] if len(plain) == 1 else None
        fid = "sht:%s:%s" % (dev_key, proj)
        if len(exact) == 1 or (lone and lone[4] is None and lone[1] is not None):
            # one of the developer's own projects; or the one project in the register carrying the sheet's exact name, with no developer on
            # record yet (a project only the buildings / land / units registers hold: Arancia Yards 2, Imtiaz Symphony Tower, Inaura)
            c = list(exact.values())[0] if len(exact) == 1 else lone
            method = "registered name (developer's own projects)" if len(exact) == 1 else "exact registered name, unique; no developer on record"
            proj_link[(dev_key, proj)] = (c[0], c[1], "accepted")
            xp.append(xrow("sheet_project", "sheet_project", fid, "project", c[0], "same project", method, 1.0 if len(exact) == 1 else 0.9,
                           "accepted", "sheet '%s' = registered '%s' (%s)" % (proj, c[2][0], c[3] or "")))
        else:
            outside = {cid: (c, "registered name, a project of DLD developer %s - not linked to this developer" % c[4] if c[4] is not None
                             else "registered name, carried by several projects") for cid, c in list(plain.items()) + list(other.items())}
            for c, label in outside.values():
                proj_link.setdefault((dev_key, proj), (None, None, "review"))
                xp.append(xrow("sheet_project", "sheet_project", fid, "project", c[0], "same project", label, 0.4, "review",
                               "sheet '%s' ~ registered '%s' (%s)" % (proj, c[2][0], c[3] or "")))
                review.append(["project", dev_key, proj, "", c[0], c[2][0], label, ""])
            for label, found, score in (("registered name (several of the developer's projects)", exact, 0.6),
                                        ("name inside a registered name (developer's own projects)", near, 0.5)):
                for c in found.values():
                    proj_link.setdefault((dev_key, proj), (None, None, "review"))
                    xp.append(xrow("sheet_project", "sheet_project", fid, "project", c[0], "same project", label, score, "review",
                                   "sheet '%s' ~ registered '%s' (%s)" % (proj, c[2][0], c[3] or "")))
                    review.append(["project", dev_key, proj, "", c[0], c[2][0], label, ""])

    # --- sheet unit -> property_id, inside accepted projects
    pids = sorted({v[1] for v in proj_link.values() if v[2] == "accepted" and v[1] is not None})
    reg = collections.defaultdict(list)
    if pids:
        for pid, prop, unum, bnum, area, balcony in con.execute("""select %s, %s, trim(unit_number), %s, try_cast(actual_area as double),
                coalesce(try_cast(unit_balcony_area as double), 0) from %s where %s in (%s) and %s is not null""" % (
                num("project_id"), num("property_id"), num("building_number"), read(ufiles), num("project_id"), ", ".join(str(p) for p in pids),
                num("property_id"))).fetchall():
            reg[pid].append((prop, unum or "", bnum, area, balcony))
    prefixes = collections.defaultdict(set)                 # register project -> the sheets' first unit-id segments
    for dev_key, proj, uid, *_ in sheet_units:
        link = proj_link.get((dev_key, proj))
        seg0 = re.split(r"[-/ ]", uid or "")[0]
        if link and link[2] == "accepted" and re.match(r"^[A-Za-z]+[A-Za-z0-9]*$", seg0) and seg0 != uid:
            prefixes[link[1]].add(seg0.upper())

    def block_token(pid, uid):
        ps = prefixes.get(pid) or set()
        seg0 = re.split(r"[-/ ]", uid or "")[0].upper()
        if len(ps) < 2 or seg0 not in ps:
            return None
        stem = os.path.commonprefix(sorted(ps))
        tok = seg0[len(stem):]
        return tok if len(tok) == 1 else None

    def ordinal(tok):
        return int(tok) if tok.isdigit() else ord(tok) - 64

    xu, flat, counts = [], [], collections.Counter()
    for dev_key, proj, uid, utype, sqft, last_seen in sheet_units:
        cid, pid, pdec = proj_link.get((dev_key, proj), (None, None, None))
        row = [dev_key, proj, uid, utype, sqft, last_seen, cid, pdec, None, None, None, None, None, 0]
        if pdec == "accepted" and pid is not None:
            digits = re.findall(r"\d+", uid or "")
            un = int(digits[-1]) if digits else None
            cands = [r for r in reg.get(pid, []) if un is not None and un in {int(x) for x in re.findall(r"\d+", r[1])}]
            fit = lambda a: bool(sqft) and bool(a) and abs(a - sqft * SQFT_SQM) <= SIZE_TOL * a
            sized = [r for r in cands if fit(r[3]) or fit((r[3] or 0) + r[4])]
            tok = block_token(pid, uid)
            narrowed, how = [], ""
            if len(sized) > 1:
                # the whole digit sequence of the register unit number ends the sheet's ("WRDH1-0101" [1, 101] = "1-0101", not "2-0101")
                seq = [int(x) for x in digits]
                tail = [r for r in sized if re.findall(r"\d+", r[1]) and [int(x) for x in re.findall(r"\d+", r[1])] == seq[-len(re.findall(r"\d+", r[1])):]]
                narrowed, how = (tail, "building number in the unit number") if len(tail) == 1 else ([], "")
                if not narrowed and tok:
                    pool = tail or sized
                    # the building letter the register writes first ("C104", "BG01"); where it writes none, the building ordinal
                    letter = lambda r: (re.match(r"^([A-Za-z])(?=[A-Za-z]?\d)", r[1]) or [None, None])[1]
                    lettered = [r for r in pool if letter(r)]
                    pick = [r for r in pool if (letter(r) or "").upper() == tok] if lettered else [r for r in pool if r[2] == ordinal(tok)]
                    narrowed, how = (pick, "building %s" % tok) if len(pick) == 1 else ([], "")
            fid = "shu:%s:%s:%s" % (dev_key, proj, uid)
            if len(sized) == 1 or len(narrowed) == 1:
                r = sized[0] if len(sized) == 1 else narrowed[0]
                method = "unit number + size" if len(sized) == 1 else "unit number + size + " + how
                counts["accepted"] += 1
                row[8:14] = [r[0], "accepted", method, r[1], r[3], len(sized)]
                xu.append(xrow("sheet_unit", "sheet_unit", fid, "unit", "unit:%s" % r[0], "same unit", method, 1.0, "accepted",
                               "sheet %s, %s sq ft = register unit %s, %.1f sq m%s" % (uid, sqft, r[1], r[3] or 0, " (building %s)" % r[2] if r[2] else "")))
            elif sized or cands:
                pool = sized or cands
                label = "unit number + size, several units" if sized else "unit number only, size differs"
                counts["review"] += 1
                row[8:14] = [None, "review", label, ", ".join(sorted({r[1] for r in pool}))[:120], None, len(pool)]
                for r in pool[:6]:
                    xu.append(xrow("sheet_unit", "sheet_unit", fid, "unit", "unit:%s" % r[0], "same unit", label, 0.5, "review",
                                   "sheet %s, %s sq ft ~ register unit %s, %.1f sq m (building %s)" % (uid, sqft, r[1], r[3] or 0, r[2])))
                review.append(["unit", dev_key, proj, uid, cid, "; ".join("%s %.1f sq m b%s" % (r[1], r[3] or 0, r[2]) for r in pool[:6]), label, sqft])
            else:
                counts["no register unit"] += 1
        flat.append(row)
    con.execute(XREF_DDL.replace("create table if not exists lk_xref", "create or replace temp table j_xref_sp"))
    con.execute(XREF_DDL.replace("create table if not exists lk_xref", "create or replace temp table j_xref_su"))
    if xp:
        con.executemany("insert into j_xref_sp values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", xp)
    if xu:
        con.executemany("insert into j_xref_su values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", xu)
    con.execute("""create or replace temp table j_sheet_register (developer varchar, project varchar, unit_id varchar, unit_type varchar,
                   sqft double, last_seen date, project_canonical_id varchar, project_decision varchar, property_id bigint, unit_decision varchar,
                   unit_method varchar, register_unit_number varchar, register_area_sqm double, candidates integer)""")
    if flat:
        con.executemany("insert into j_sheet_register values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", flat)
    n_proj = len(projects)
    p_acc = sum(1 for v in proj_link.values() if v[2] == "accepted")
    p_rev = sum(1 for v in proj_link.values() if v[2] == "review")
    in_acc = sum(1 for r in flat if r[7] == "accepted")
    names_acc = sorted({"%s: %s" % (k[0], k[1]) for k, v in proj_link.items() if v[2] == "accepted"})
    unlinked = sorted("%s: %s" % k for k in projects if k not in proj_link)
    view = """select s.developer, s.project, s.unit_id, s.unit_type, s.sqft, s.last_seen, s.unit_decision, s.unit_method, s.property_id,
                     s.register_unit_number, s.register_area_sqm, p.canonical_id project_canonical_id, p.project_id, p.name_en project_name_en,
                     p.area_name_en, p.developer_number, d.name_en developer_name_en
              from lk_sheet_register s left join lk_d_project p on p.canonical_id = s.project_canonical_id and s.project_decision = 'accepted'
              left join lk_d_developer d on d.developer_number = p.developer_number"""
    return {"tables": [("lk_sheet_register", "select * from j_sheet_register")],
            "xref": [("sheet_project", "j_xref_sp"), ("sheet_unit", "j_xref_su")],
            "views": [("v_thread_unit", view)],
            "keys_in": in_acc, "keys_matched": counts["accepted"], "rows_in": len(flat),
            "note": "sheet units in register-linked projects matched to one register unit",
            "review_csv": (SHEET_REVIEW, ["level", "developer", "sheet_project", "unit_id", "project", "register_candidates", "method", "sqft"], review),
            "report": ["sheet projects: %d - linked to one registered project %d, for review %d, no registered match %d (Aljada is in Sharjah)"
                       % (n_proj, p_acc, p_rev, n_proj - p_acc - p_rev),
                       "  linked: " + "; ".join(names_acc)[:900],
                       "  not linked: " + "; ".join(unlinked)[:900],
                       "sheet units: %s; in linked projects %s - one register unit %s, for review %s, no register unit %s (units: %s)"
                       % (format(len(flat), ","), format(in_acc, ","), format(counts["accepted"], ","), format(counts["review"], ","),
                          format(counts["no register unit"], ","), usource),
                       "review rows: %d (%s)" % (len(review), os.path.relpath(SHEET_REVIEW, ROOT))]}


def job_makani(con):
    C = read(register_files("customers_master_data", "customers_master_data__*.csv"))
    mk = "replace(trim(makani_number), ' ', '')"
    con.execute("""create or replace temp table j_dewa_mk as
        select %s makani, count(*) move_ins,
               count(*) filter (where date_of_move_in >= '2024-01-01' and date_of_move_in < '2025-01-01') move_ins_2024,
               count(*) filter (where date_of_move_in >= '2025-01-01' and date_of_move_in < '2026-01-01') move_ins_2025,
               count(*) filter (where date_of_move_in >= '2026-01-01') move_ins_2026,
               min(date_of_move_in) first_move_in, max(date_of_move_in) last_move_in,
               count(*) filter (where customer_category ilike '%%resi%%') residential,
               count(*) filter (where customer_category ilike 'commercial%%') commercial,
               try_cast(any_value(regexp_extract(community, '^ *([0-9]+)-', 1)) as bigint) dewa_comm_num
        from %s where regexp_matches(%s, '^[0-9]{10}$') group by 1""" % (mk, C, mk))
    em = "replace(trim(\"MAKANI\"), ' ', '')"
    con.execute("""create or replace temp table j_ent as
        select %s makani, try_cast("ENTERANCEID" as bigint) entrance_id, try_cast(lon as double) lon, try_cast(lat as double) lat,
               try_cast("COMM_NUM" as bigint) comm_num, nullif(nullif(trim("TYPE_DESC_E"), '&lt;Null&gt;'), '') entrance_type
        from read_csv('%s', all_varchar=true, header=true) where regexp_matches(%s, '^[0-9]{10}$')
        qualify row_number() over (partition by %s order by try_cast("ENTERANCEID" as bigint)) = 1""" % (em, lake._p(ENTRANCES), em, em))
    con.execute("""create or replace temp table j_near as
        with e as (select makani, lon, lat, cast(floor(lon / {c}) as bigint) gx, cast(floor(lat / {c}) as bigint) gy
                   from j_ent where lon is not null and lat is not null),
             e9 as (select e.makani, e.lon, e.lat, e.gx + dx.d cx, e.gy + dy.d cy
                    from e, (select unnest([-1, 0, 1]) d) dx, (select unnest([-1, 0, 1]) d) dy),
             b as (select duid, lon, lat, cast(floor(lon / {c}) as bigint) cx, cast(floor(lat / {c}) as bigint) cy
                   from building where lon is not null and lat is not null)
        select makani, duid, dist_m from (
            select e9.makani, b.duid, sqrt(power((b.lon - e9.lon) * 111320 * cos(radians(e9.lat)), 2) + power((b.lat - e9.lat) * 110574, 2)) dist_m
            from e9 join b on b.cx = e9.cx and b.cy = e9.cy)
        where dist_m <= {m}
        qualify row_number() over (partition by makani order by dist_m) = 1""".format(c=CELL, m=NEAR_M))
    con.execute("""create or replace temp table j_mk_ent as
        select e.*, n.duid, round(n.dist_m, 1) dist_m from j_ent e left join j_near n using (makani)""")
    con.execute("""create or replace temp table j_mk as
        select d.*, e.entrance_id, e.comm_num entrance_comm_num, e.duid, e.dist_m from j_dewa_mk d left join j_mk_ent e using (makani)""")
    makanis, with_ent, with_bld, moves, moves_ent, moves_bld = one(con, """select count(*), count(entrance_id), count(duid),
        sum(move_ins), sum(move_ins) filter (where entrance_id is not null), sum(move_ins) filter (where duid is not null) from j_mk""")
    ents, ents_bld, comms = one(con, "select count(*), count(duid), count(distinct comm_num) from j_mk_ent")
    gaps = con.execute("""select d.dewa_comm_num, max(c.name_en) community, sum(d.move_ins_2025) moves_2025
        from j_mk d left join dm_community c on try_cast(c.comm_num as bigint) = d.dewa_comm_num
        group by 1 having count(d.entrance_id) = 0 order by 3 desc limit 5""").fetchall()
    view = """select m.duid, any_value(b.district) district, any_value(b.display_name) display_name, count(*) makani_numbers,
                     sum(m.move_ins) move_ins, sum(m.move_ins_2024) move_ins_2024, sum(m.move_ins_2025) move_ins_2025,
                     sum(m.move_ins_2026) move_ins_2026, max(m.last_move_in) last_move_in
              from lk_dewa_moveins_makani m left join building b on b.duid = m.duid
              where m.duid is not null group by m.duid"""
    return {"tables": [("lk_makani_entrances", "select * from j_mk_ent"), ("lk_dewa_moveins_makani", "select * from j_mk")],
            "views": [("v_building_moveins", view)],
            "keys_in": makanis, "keys_matched": with_ent, "rows_in": moves,
            "note": "DEWA Makani numbers found in the entrance layer (cut at 256 MiB at source)",
            "report": ["DEWA Makani numbers on an entrance point: " + pct(with_ent, makanis),
                       "... and on a twin building within %d m: %s" % (NEAR_M, pct(with_bld, makanis)),
                       "move-ins covered: entrance %s, building %s" % (pct(moves_ent or 0, moves or 0), pct(moves_bld or 0, moves or 0)),
                       "entrance points: %s, on a twin building %s, in %d communities" % (format(ents, ","), pct(ents_bld, ents), comms),
                       "largest 2025 move-in communities with no entrance point at all: "
                       + "; ".join("%s %s (%s)" % (g[0], g[1] or "?", format(g[2] or 0, ",")) for g in gaps)]}


MIX_MIN_ACCOUNTS = 500                 # a community shows its resident mix only above this many residential accounts
MIX_MIN_SHARE = 0.05                   # groups under this share are folded into "Other nationalities"
MIX_NAME_MIN_ACCOUNTS = 20             # regions view: no country, region or remainder under this many accounts is shown (section 11)
REGION_COUNTRY_MIN_PCT = 1             # regions view: a country is named inside its region from this whole percent
TOWER_MIN_ACCOUNTS = 20                # buildings with fewer DEWA accounts get no colour: a small building's move-in is a household's


def job_resident_mix(con):
    """Kendall, 14 Sep 2026: resident nationality by community, for him and Naj only, never shown to clients, and a filter by
    group. Residential DEWA accounts, current at the extract. Kept: rounded shares of groups at 5% or more, and (15 Sep) the
    regions view - each region's share with its countries at 1%+, never a figure under 20 accounts. No counts per
    nationality are stored, nothing below community level, and nothing here is linked to homes or listings."""
    C = read(register_files("customers_master_data", "customers_master_data__*.csv"))
    con.execute("""create or replace temp table j_rm as
        select try_cast(regexp_extract(community, '^ *([0-9]+)-', 1) as bigint) comm_num, nullif(trim(nationality), '') nationality,
               count(*) n, min(trim(regexp_replace(community, '^ *[0-9]+-', ''))) dewa_name
        from %s where customer_category ilike '%%resi%%' group by 1, 2""" % C)
    con.execute("""create or replace temp table j_rm_tot as
        select comm_num, sum(n) filter (where nationality is not null) with_nat, sum(n) all_res, min(dewa_name) dewa_name
        from j_rm where comm_num is not null group by 1""")
    con.execute("""create or replace temp table j_rm_share as
        select r.comm_num, r.nationality, r.n::double / t.with_nat as share from j_rm r join j_rm_tot t using (comm_num)
        where r.nationality is not null and t.with_nat >= %d""" % MIX_MIN_ACCOUNTS)
    con.execute("""create or replace temp table j_rm_mix as
        with shown as (select comm_num, nationality, cast(round(100 * share) as int) share_pct,
                              row_number() over (partition by comm_num order by share desc, nationality) as rank
                       from j_rm_share where share >= {s}),
             other as (select comm_num, 'Other nationalities' as nationality, cast(round(100 * sum(share)) as int) as share_pct, 99 as rank
                       from j_rm_share where share < {s} group by 1)
        select t.comm_num, coalesce(d.name_en, upper(t.dewa_name)) community, cast(round(t.with_nat / 100.0) * 100 as bigint) accounts_rounded,
               cast(round(100.0 * (t.all_res - t.with_nat) / t.all_res) as int) no_nationality_pct, m.nationality, m.share_pct, m.rank
        from j_rm_tot t
        join (select * from shown union all select * from other) m using (comm_num)
        left join (select try_cast(comm_num as bigint) comm_num, name_en from dm_community) d using (comm_num)
        where t.with_nat >= {n}""".format(s=MIX_MIN_SHARE, n=MIX_MIN_ACCOUNTS))
    con.execute("""create or replace temp table j_rm_bands as
        with groups as (select distinct nationality from j_rm_share where share >= {s}),
             comms as (select distinct comm_num from j_rm_share),
             grid as (select c.comm_num, g.nationality, coalesce(s.share, 0) as share from comms c cross join groups g
                      left join j_rm_share s on s.comm_num = c.comm_num and s.nationality = g.nationality)
        select comm_num, nationality,
               case when share >= 0.40 then '40%+' when share >= 0.20 then '20-40%' when share >= 0.10 then '10-20%'
                    when share >= {s} then '5-10%' else 'under 5%' end band,
               case when share >= 0.40 then 40 when share >= 0.20 then 20 when share >= 0.10 then 10 when share >= {s} then 5 else 0 end band_min
        from grid""".format(s=MIX_MIN_SHARE))
    # Kendall, 15 Sep 2026: "instead of individual countries, continents, then a further breakdown" - regions with their
    # countries, from every group's count before rounding. Floors in nationality_regions.regions_for; only percents are stored.
    by_comm = {}
    for c, nat, n, tot in con.execute("""select r.comm_num, r.nationality, r.n, t.with_nat from j_rm r join j_rm_tot t using (comm_num)
                                         where r.nationality is not null and t.with_nat >= %d""" % MIX_MIN_ACCOUNTS).fetchall():
        by_comm.setdefault(c, ([], tot))[0].append((nat, n))
    reg_rows, unmapped, named_per = [], set(), []
    for c, (counts, tot) in by_comm.items():
        regs, miss = nationality_regions.regions_for(counts, tot, MIX_NAME_MIN_ACCOUNTS, REGION_COUNTRY_MIN_PCT)
        unmapped.update(miss)
        named_per.append(sum(len(g["countries"]) for g in regs))
        for i, g in enumerate(regs, 1):
            for j, (nat, p) in enumerate(g["countries"] or [(None, None)], 1):
                reg_rows.append((c, g["name"], i, g["pct"], g["others"], nat, j if nat else None, p))
    con.execute("""create or replace temp table j_rm_regions (comm_num bigint, region varchar, region_rank int, region_pct int,
                   others_pct int, country varchar, country_rank int, country_pct int)""")
    con.executemany("insert into j_rm_regions values (?, ?, ?, ?, ?, ?, ?, ?)", reg_rows)
    named_per.sort()
    comms, eligible, covered, total = one(con, """select count(*) filter (where with_nat > 0), count(*) filter (where with_nat >= %d),
        sum(with_nat) filter (where with_nat >= %d), sum(with_nat) from j_rm_tot""" % (MIX_MIN_ACCOUNTS, MIX_MIN_ACCOUNTS))
    groups, med_shown = one(con, """select (select count(distinct nationality) from j_rm_bands),
        median(k) from (select comm_num, count(*) k from j_rm_mix where rank < 99 group by 1)""")
    return {"tables": [("lk_community_resident_mix", "select * from j_rm_mix"), ("lk_community_resident_bands", "select * from j_rm_bands"),
                       ("lk_community_resident_regions", "select * from j_rm_regions")],
            "keys_in": comms, "keys_matched": eligible, "rows_in": total,
            "note": "communities with at least %d residential accounts carrying a nationality" % MIX_MIN_ACCOUNTS,
            "report": ["communities shown: " + pct(eligible, comms),
                       "residential accounts inside the communities shown: " + pct(covered or 0, total or 0),
                       "nationalities reaching 5%% in at least one community: %d; groups shown per community, median %s" % (groups, med_shown),
                       "stored: rounded shares of groups at 5% or more, 'Other nationalities', bands for the filter - no counts per nationality",
                       "regions: %d communities; countries named at %d%%+ with %d+ accounts, median %s per community"
                       % (len(by_comm), REGION_COUNTRY_MIN_PCT, MIX_NAME_MIN_ACCOUNTS, named_per[len(named_per) // 2] if named_per else 0),
                       "nationality spellings with no region (counted in Rest of the world): " + (", ".join(sorted(unmapped)) or "none")]}


def job_building_activity(con):
    """Kendall, 14 Sep 2026: twin building colours with no nationality - how fast newly handed-over towers fill, residents against
    businesses, and move-ins in the last six months against the six before. DEWA keeps current accounts only, so older move-ins
    fall away as people leave: the earlier six months run a little low, and a building's first month with three residential
    move-ins stands in for its handover. Buildings with fewer than 20 accounts get no colour."""
    C = read(register_files("customers_master_data", "customers_master_data__*.csv"))
    last = one(con, "select max(date_of_move_in) from %s" % C)[0]
    end = dt.date.fromisoformat(last[:10])
    end = (end.replace(day=1) - dt.timedelta(days=1)) if end.day < 28 else end      # the last whole month in the extract
    months = [(end.year * 12 + end.month - 1 - k) for k in range(12)]
    ym = lambda v: "%04d-%02d" % (v // 12, v % 12 + 1)
    l6a, p6a, p6b, endm = ym(months[5]), ym(months[11]), ym(months[6]), ym(months[0])
    # Both halves carry the same current-accounts tilt citywide, so a building is judged against Dubai's own ratio, not against 1:
    # measured on the first run, 517 buildings read "more" and 74 "fewer" against a flat threshold.
    city_last, city_prev = one(con, """select count(*) filter (where substr(date_of_move_in, 1, 7) between '{l6a}' and '{end}'),
        count(*) filter (where substr(date_of_move_in, 1, 7) between '{p6a}' and '{p6b}')
        from {c} where customer_category ilike '%resi%'""".format(l6a=l6a, end=endm, p6a=p6a, p6b=p6b, c=C))
    city = float(city_last) / city_prev if city_prev else 1.0
    con.execute("""create or replace temp table j_ba_months as
        select e.duid, substr(c.date_of_move_in, 1, 7) as month, count(*) as accounts,
               count(*) filter (where c.customer_category ilike '%resi%') residential,
               count(*) filter (where c.customer_category ilike 'commercial%' or c.customer_category ilike 'industrial%') business
        from {c} c join lk_makani_entrances e on e.makani = replace(trim(c.makani_number), ' ', '')
        where e.duid is not null and c.date_of_move_in is not null and substr(c.date_of_move_in, 1, 7) <= '{end}'
        group by 1, 2""".format(c=C, end=endm))
    con.execute("""create or replace temp table j_ba as
        with tot as (select duid, sum(accounts) accounts, sum(residential) residential, sum(business) business,
                            min(month) filter (where residential >= 3) first_month,
                            coalesce(sum(residential) filter (where month between '{l6a}' and '{end}'), 0) last6,
                            coalesce(sum(residential) filter (where month between '{p6a}' and '{p6b}'), 0) prev6
                     from j_ba_months group by 1),
             opened as (select *, date_diff('month', cast(first_month || '-01' as date), cast('{end}-01' as date)) + 1 months_open from tot),
             fill as (select o.duid, sum(m.residential) first6 from opened o join j_ba_months m using (duid)
                      where m.month >= o.first_month and date_diff('month', cast(o.first_month || '-01' as date), cast(m.month || '-01' as date)) < 6
                      group by 1)
        select o.duid, b.district, b.display_name, o.accounts, o.residential, o.business,
               cast(round(100.0 * o.residential / o.accounts) as int) residential_pct,
               case when o.residential >= 0.75 * o.accounts then 'mostly residents' when o.residential >= 0.25 * o.accounts then 'mixed'
                    else 'mostly businesses' end residents_band,
               o.first_month, o.first_month >= '2024-01' newly_handed_over, o.months_open,
               case when o.first_month >= '2024-01' then round(f.first6 / least(6, o.months_open), 1) end fill_per_month,
               case when o.first_month < '2024-01' or o.first_month is null then null
                    when f.first6 / least(6, o.months_open) >= 40 then '40+ a month' when f.first6 / least(6, o.months_open) >= 15 then '15-40 a month'
                    when f.first6 / least(6, o.months_open) >= 5 then '5-15 a month' else 'under 5 a month' end fill_band,
               o.last6, o.prev6,
               case when o.last6 + o.prev6 < 20 then null when o.prev6 = 0 or o.last6 >= 1.25 * {r} * o.prev6 then 'ahead of Dubai'
                    when o.last6 <= 0.8 * {r} * o.prev6 then 'behind Dubai' else 'in line with Dubai' end activity_band,
               {r} city_ratio
        from opened o left join fill f using (duid) left join building b on b.duid = o.duid
        where o.accounts >= {n}""".format(l6a=l6a, end=endm, p6a=p6a, p6b=p6b, n=TOWER_MIN_ACCOUNTS, r=round(city, 4)))
    linked, eligible = one(con, "select count(distinct duid), (select count(*) from j_ba) from j_ba_months")
    new, act = one(con, "select count(*) filter (where newly_handed_over), count(activity_band) from j_ba")
    bands = con.execute("select residents_band, count(*) from j_ba group by 1 order by 2 desc").fetchall()
    return {"tables": [("lk_building_dewa_activity", "select *, '%s' last6_from, '%s' last6_to, '%s' prev6_from, '%s' prev6_to from j_ba"
                        % (l6a, endm, p6a, p6b))],
            "keys_in": linked, "keys_matched": eligible, "rows_in": eligible,
            "note": "twin buildings on a DEWA address with at least %d accounts" % TOWER_MIN_ACCOUNTS,
            "report": ["DEWA move-ins to %s (last whole month %s): last six months %s..%s against %s..%s; Dubai's residential ratio %.2f"
                       % (last[:10], endm, l6a, endm, p6a, p6b, city),
                       "twin buildings on a DEWA address: %d; coloured (at least %d accounts): %d" % (linked, TOWER_MIN_ACCOUNTS, eligible),
                       "handed over since Jan 2024 (first month with three residential move-ins): %d; with a six-month comparison: %d" % (new, act),
                       "residents against businesses: " + ", ".join("%s %d" % b for b in bands)]}


JOBS = {"community": job_community, "parcels": job_parcels, "service_charges": job_service_charges,
        "sales_projects": job_sales_projects, "rent_projects": job_rent_projects, "twin_bindings": job_twin_bindings,
        "project_spine": job_project_spine, "sheet_units": job_sheet_units, "place_spine": job_place_spine, "sub_communities": job_sub_communities, "stations": job_stations, "districts": job_districts, "makani": job_makani, "resident_mix": job_resident_mix,
        "building_activity": job_building_activity}
# 15 Sep 2026: a job added for the digital thread must not fail the gov-weekly register_joins step - that step's failure skips
# dewa_views and both DEWA pushes. Such a job's error is reported and the run carries on with the exit code it would have had.
NON_BLOCKING = {"rent_projects", "twin_bindings", "project_spine", "sheet_units", "place_spine", "sub_communities", "stations", "districts"}


def run(con, name, dry):
    t0 = time.time()
    r = JOBS[name](con)
    rate = float(r["keys_matched"]) / r["keys_in"] if r["keys_in"] else 0.0
    logged = con.execute("select count(*) from information_schema.tables where table_name = 'lk_join_log'").fetchone()[0]
    prev = con.execute("select rate from lk_join_log where job = ? and status = 'accepted' order by run_at desc limit 1",
                       [name]).fetchone() if logged else None
    held = (prev is not None and rate < HOLD_RATIO * prev[0]) or bool(r.get("hold"))
    print("== %s (%.0fs)" % (name, time.time() - t0))
    for line in r["report"]:
        print("   " + line)
    print("   contract: %s %s%s" % (r["note"], pct(r["keys_matched"], r["keys_in"]),
                                    "; last accepted %.1f%%" % (100 * prev[0]) if prev else "; first run"))
    if r.get("hold"):
        print("   gate: " + r["hold"])
    if dry:
        print("   dry run: nothing written")
        return 0
    if "review" in r:
        os.makedirs(os.path.dirname(REVIEW), exist_ok=True)
        with open(REVIEW, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sales_project_name", "sales_area", "name_match_project_id", "register_project_id", "sales_rows"])
            w.writerows(r["review"])
    if r.get("review_csv"):
        path, header, rows = r["review_csv"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    if held:
        lake.retry(lambda: con.execute("insert into lk_join_log values (localtimestamp, ?, ?, ?, ?, ?, 'held', ?)",
                                       [name, r["keys_in"], r["keys_matched"], rate, r["rows_in"], r.get("hold") or r["note"]]), "join log")
        print("HELD register join %s: %s - tables left as they were" % (
            name, r.get("hold") or "%.1f%% against %.1f%% last accepted" % (100 * rate, 100 * prev[0])))
        return 4

    def body():
        con.execute("BEGIN TRANSACTION")
        try:
            for t, sql in r["tables"]:
                con.execute("create or replace table %s as %s" % (t, sql))
            for job, tmp in r.get("xref", []):             # one crosswalk for every job: a job replaces only its own rows
                con.execute(XREF_DDL)
                con.execute("delete from lk_xref where job = ?", [job])
                con.execute("insert into lk_xref (%s) select %s from %s" % (XREF_COLS, XREF_COLS, tmp))
            for v, sql in r.get("views", []):
                con.execute("create or replace view %s as %s" % (v, sql))
            con.execute("insert into lk_join_log values (localtimestamp, ?, ?, ?, ?, ?, 'accepted', ?)",
                        [name, r["keys_in"], r["keys_matched"], rate, r["rows_in"], r["note"]])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    lake.retry(body, "joins " + name)
    print("   published: %s" % ", ".join([t for t, _ in r["tables"]] + ["lk_xref (%s)" % j for j, _ in r.get("xref", [])] +
                                         [v for v, _ in r.get("views", [])]))
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    names = list(JOBS) if not args or args == ["all"] else args
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        raise SystemExit("unknown job(s): %s - choose from %s" % (", ".join(unknown), ", ".join(JOBS)))
    con = lake.connect(read_only=dry)
    if not dry:
        lake.retry(lambda: con.execute(LOG_DDL), "join log")
    rc = 0
    for n in names:
        try:
            rc = max(rc, run(con, n, dry))
        except Exception as e:
            if n in NON_BLOCKING:
                print("FAILED register join %s (reported, does not fail the step): %s" % (n, str(e)[:300]))
                continue
            print("FAILED register join %s: %s" % (n, str(e)[:300]))
            rc = max(rc, 1)
    sys.exit(rc)


if __name__ == "__main__":
    main()
