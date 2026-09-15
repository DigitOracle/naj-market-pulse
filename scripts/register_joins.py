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

Usage: python scripts/register_joins.py [all | community parcels service_charges sales_projects makani] [--dry]
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


def num(col):
    """'3656.00', ' 3656', '3656' -> 3656"""
    return "try_cast(try_cast(trim(cast(%s as varchar)) as double) as bigint)" % col


def parcel_key(col):
    """The three spellings of one parcel: '6830847', '6830847.00' and '683-847' (community-plot) -> 6830847"""
    x = "trim(cast(%s as varchar))" % col
    return ("(case when regexp_matches({x}, '^[0-9]+$') then try_cast({x} as bigint)"
            " when regexp_matches({x}, '^[0-9]+[.][0-9]+$') then try_cast(try_cast({x} as double) as bigint)"
            " when regexp_matches({x}, '^[0-9]{{1,4}}-[0-9]{{1,4}}$')"
            " then try_cast(split_part({x}, '-', 1) as bigint) * 10000 + try_cast(split_part({x}, '-', 2) as bigint) end)").format(x=x)


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
    twin = """select bp.duid, bp.district, k.parcel_key, d.building_id dm_building_id, d.height_m dm_height_m, b.height_m twin_height_m,
                     d.typical_floors dm_typical_floors, b.storeys twin_storeys, d.floor_config, d.completion_date, d.status,
                     d.building_type, d.usages, d.buildings_on_plot, bp.dist_m
              from building_parcel_dm bp
              join lk_parcel_keys k on k.source = 'building_parcel_dm' and k.raw = trim(cast(bp.parcel_id as varchar))
              join lk_dm_buildings d on d.parcel_key = k.parcel_key
              left join building b on b.duid = bp.duid"""
    plots = """select p.plot_no, p.name, p.district, p.master, k.parcel_key, d.building_id dm_building_id, d.height_m, d.typical_floors,
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


def job_sales_projects(con):
    T = read(register_files("transactions", "dld__transactions__*.csv"))
    PR = read(register_files("projects", "dld__projects__*.csv"))
    con.execute("""create or replace temp table j_portal as
        select split_part(transaction_id, '-', 2) || '-' || split_part(transaction_id, '-', 4) || '-' || split_part(transaction_id, '-', 3) k,
               transaction_id, %s project_number, try_cast(area_id as bigint) area_id, nullif(trim(building_name_en), '') building_name_en,
               nullif(trim(project_name_en), '') project_name_en, try_cast(actual_worth as double) worth, try_cast(procedure_area as double) size_sqm
        from %s where regexp_matches(transaction_id, '^[0-9]+-[0-9]+-[0-9]+-[0-9]+$')""" % (num("project_number"), T))
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
    return {"tables": [("lk_txn_register", "select * from j_bridge"), ("lk_project_number_names", "select * from j_names")],
            "views": [("v_transactions_register_project", view)],
            "keys_in": named, "keys_matched": by_row + by_name, "rows_in": keys,
            "note": "named sales rows linked by the register (row or name pair)",
            "review": report_rows,
            "report": ["current sales keys paired with the portal's row (price or size agrees): " + pct(paired, keys),
                       "paired sales whose register area carries a community number: " + pct(area_comm, with_area),
                       "named sales rows linked: by the register's row %s, by its name-number pair %s, by name match only %s, of %s"
                       % (format(by_row, ","), format(by_name, ","), format(by_match, ","), format(named, ",")),
                       "where the register's row and identity_match both give a project, they agree on " + pct(agree, both),
                       "disagreeing name/project pairs: %d (data/identity/register_vs_name.csv)" % len(report_rows)]}


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
        "sales_projects": job_sales_projects, "makani": job_makani, "resident_mix": job_resident_mix,
        "building_activity": job_building_activity}


def run(con, name, dry):
    t0 = time.time()
    r = JOBS[name](con)
    rate = float(r["keys_matched"]) / r["keys_in"] if r["keys_in"] else 0.0
    logged = con.execute("select count(*) from information_schema.tables where table_name = 'lk_join_log'").fetchone()[0]
    prev = con.execute("select rate from lk_join_log where job = ? and status = 'accepted' order by run_at desc limit 1",
                       [name]).fetchone() if logged else None
    held = prev is not None and rate < HOLD_RATIO * prev[0]
    print("== %s (%.0fs)" % (name, time.time() - t0))
    for line in r["report"]:
        print("   " + line)
    print("   contract: %s %s%s" % (r["note"], pct(r["keys_matched"], r["keys_in"]),
                                    "; last accepted %.1f%%" % (100 * prev[0]) if prev else "; first run"))
    if dry:
        print("   dry run: nothing written")
        return 0
    if "review" in r:
        os.makedirs(os.path.dirname(REVIEW), exist_ok=True)
        with open(REVIEW, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sales_project_name", "sales_area", "name_match_project_id", "register_project_id", "sales_rows"])
            w.writerows(r["review"])
    if held:
        lake.retry(lambda: con.execute("insert into lk_join_log values (localtimestamp, ?, ?, ?, ?, ?, 'held', ?)",
                                       [name, r["keys_in"], r["keys_matched"], rate, r["rows_in"], r["note"]]), "join log")
        print("HELD register join %s: %.1f%% against %.1f%% last accepted - tables left as they were" % (name, 100 * rate, 100 * prev[0]))
        return 4

    def body():
        con.execute("BEGIN TRANSACTION")
        try:
            for t, sql in r["tables"]:
                con.execute("create or replace table %s as %s" % (t, sql))
            for v, sql in r.get("views", []):
                con.execute("create or replace view %s as %s" % (v, sql))
            con.execute("insert into lk_join_log values (localtimestamp, ?, ?, ?, ?, ?, 'accepted', ?)",
                        [name, r["keys_in"], r["keys_matched"], rate, r["rows_in"], r["note"]])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    lake.retry(body, "joins " + name)
    print("   published: %s" % ", ".join([t for t, _ in r["tables"]] + [v for v, _ in r.get("views", [])]))
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
            print("FAILED register join %s: %s" % (n, str(e)[:300]))
            rc = max(rc, 1)
    sys.exit(rc)


if __name__ == "__main__":
    main()
