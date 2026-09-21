"""gov_thread -- the governed-API datasets on the digital thread (18 Sep 2026, production credentials live).

The DDA API pull lands ~500 datasets as g_<entity>__<dataset> (clean rows, lake). Until now none of them joined the spines the
register joins build (lk_d_area, lk_d_community, lk_d_parcel, lk_d_building, lk_d_project, lk_d_developer, lk_d_station,
lk_d_district): they sat beside the thread, not on it. This job puts every one of them on it or says why it cannot.

  keys      a column is bound to a spine by its NAME and the values are normalised with scripts/keys.py (the same num / parcel-key
            rules every thread join uses), then matched on the spine's own number - never on a name:
              area_id -> area | community_num, "345-BURJ KHALIFA" -> community | parcel_id -> parcel | property_id -> building
              project_id, master_project_id -> project | project_number -> project (any of its registered numbers)
              developer_id / _number, master_developer_* -> developer | licence numbers -> licence | location_id (RTA) -> station
              makani -> Makani entrance -> community | DM building_id / project_no -> DM building -> parcel
  licence   a new spine, lk_d_licence: one row per DED licence (licence master + trade name), because DED, DM, LAD, DET and the
            developer register all carry the same DED number. Developers holding a licence are written to lk_xref.
  places    a latitude/longitude pair lands in the district whose box holds it and on the nearest community centre within 3 km
            (method says so: a candidate, not a key).
  datasets  a code list and the register using its codes share a column (commodity codes, DED activities, DM usages); linked
            when >= 50% of the smaller side's distinct values meet (lk_gov_dataset_link)
  status    per dataset, strongest first: connected (a spine key matched >= 50% of its values) | weak (matched, below 50%) |
            via_dataset (code-linked to a connected dataset) | code_linked (code-linked, but only to unconnected datasets) |
            city_level (a small time-keyed statistics table: attached to city:dubai and its period, not to a place) |
            keys_unmatched (has key columns, none met a spine) | catalogue_only (names only: no key, code or time) |
            not_landed (the pull never delivered it). Every dataset also carries its publisher (org:<entity>).

Tables: lk_d_licence, lk_d_escrow_agent, lk_gov_key_map (dataset, column, spine, key -> canonical_id), lk_gov_link (per dataset x
column x spine: rows, keys, matched, rate), lk_gov_dataset_link, lk_gov_thread (per dataset). Views: v_gov_thread, v_gov_unconnected.
"""
import re

from keys import num_sql as num, parcel_key_sql as parcel_key, name_norm_sql as name_norm

CONNECTED = 0.5
NEAR_KM = 3.0

# (column-name pattern, spine, normaliser SQL template over {c}, spine lookup: SQL giving (k, canonical_id))
COMMUNITY_PREFIX = "try_cast(regexp_extract(trim(cast({c} as varchar)), '^([0-9]{3,4})\\s*-', 1) as bigint)"
LOOKUPS = {
    "area":       "select area_id k, canonical_id from lk_d_area",
    "community":  "select comm_num k, canonical_id from lk_d_community",
    "parcel":     "select parcel_key k, canonical_id from lk_d_parcel",
    "property":   "select property_id k, canonical_id from lk_d_building union all select property_id, canonical_id from lk_d_parcel",
    "project":    "select project_id k, canonical_id from lk_d_project",
    "project_no": "select distinct unnest(project_numbers) k, canonical_id from lk_d_project where project_numbers is not null "
                  "union select project_number, canonical_id from lk_d_project where project_number is not null",
    "dev_id":     "select developer_id k, canonical_id from lk_d_developer",
    "dev_no":     "select developer_number k, canonical_id from lk_d_developer",
    "licence":    "select license_number k, canonical_id from j_licence",       # this run's licence spine
    "station":    "select location_id k, canonical_id from lk_d_station",
    "station_name": "select %s k, canonical_id from lk_d_station" % name_norm("name_en"),
    "escrow":     "select escrow_agent_number k, 'esc:' || escrow_agent_number canonical_id from j_escrow",
    "makani":     "select m.makani k, c.canonical_id from lk_makani_entrances m join lk_d_community c on c.comm_num = m.comm_num",
    "dm_building": "select b.building_id k, p.canonical_id from lk_dm_buildings b join lk_d_parcel p on p.parcel_key = b.parcel_key",
    "dm_project": "select b.project_no k, any_value(p.canonical_id) canonical_id from lk_dm_buildings b join lk_d_parcel p "
                  "on p.parcel_key = b.parcel_key where b.project_no is not null group by 1",
}
RULES = [
    (r"^area_id$", "area", num("{c}")),
    (r"^(community_num|comm_num|community_number|community_no)$", "community", num("{c}")),
    (r"^community$", "community", COMMUNITY_PREFIX),
    (r"^(parcel_id|parcelid|parcel_number|parcel_no)$", "parcel", parcel_key("{c}")),
    (r"^property_id$", "property", num("{c}")),        # DLD property ids name a building or a land parcel
    # 21 Sep 2026: a UNIT's own property_id is a unit, and units are not on the building/parcel spine - g_dld__units met 0 of its
    # 2,374,092 rows and read as 'weak'. A unit's BUILDING is its parent_property_id, and that is the id that belongs on the spine.
    (r"^parent_property_id$", "property", num("{c}")),
    (r"^(project_id|master_project_id)$", "project", num("{c}")),
    (r"^project_number$", "project_no", num("{c}")),
    (r"^(developer_id|master_developer_id)$", "dev_id", num("{c}")),
    (r"^(developer_number|master_developer_number)$", "dev_no", num("{c}")),
    (r"^(license_number|licence_number|license_no|licence_no|licence|main_license_number|authority_license_number|"
     r"issue_authority_license_number|issueauthoritylicencenumber)$", "licence", num("{c}")),
    (r"^location_id$", "station", num("{c}")),
    (r"^(tram_station|marine_station|metro_station|station_name|start_station|end_station)$", "station_name", name_norm("{c}")),
    (r"^(escrow_agent_id|escrow_agent_number)$", "escrow", num("{c}")),
    (r"^(makani|makani_number|makani_no)$", "makani", num("{c}")),
    (r"^building_id$", "dm_building", num("{c}")),
    (r"^project_no$", "dm_project", num("{c}")),
]
SPINE_OF = {"station_name": "station", "project_no": "project", "dev_id": "developer", "dev_no": "developer", "makani": "community",
            "dm_building": "parcel", "dm_project": "parcel"}
# shared-code columns between datasets (code lists <-> the registers that use them)
CODE_COL = re.compile(r"(code|_id|id|number|_no|serial|symbol|isin|barcode)$|^(company|activity|person|area|usage)$", re.I)
CODE_SKIP = {"id", "sr", "load_timestamp", "phone", "phone_number", "mobile", "fax", "home_phone"}
CODE_ALIAS = {"area": "areacode", "activity_ded_code": "activity_code", "isic4code": "activity_code_isic4", "countryid": "country_id",
              "professionid": "profession_id"}
CODE_MAX_DISTINCT = 300_000
# a city-wide statistics table: small, keyed by time only (fleet sizes, crime counts, monthly index, airport throughput)
TIME_COL = re.compile(r"(^|_)(year|month|date|day|period)$|report_date|first_date_of_month", re.I)
# 21 Sep 2026: the cap was 20,000, which left genuinely city-and-period tables off the thread purely for being long - RTA public
# transport trips by month (198,528 rows), the three channel programme schedules, DSC unemployment, driver registration summaries.
# A table only reaches this test when NO column met a spine and none of its codes met another dataset, so length is not evidence of
# it being a register; a time key with nothing else is a city series however many rows it has. Raised, not removed: a million-row
# table with no key at all is more likely a broken pull than a statistic, and should be looked at rather than quietly attached.
CITY_MAX_ROWS = 250_000
# 19 Sep 2026 audit: KHDA school_search names its pair lat / long and the DHA facility register xcoordinate / ycoordinate (degrees:
# x = longitude 55.x, y = latitude 25.x) - both sat off the thread as catalogue_only. The Dubai bounding box below still rejects
# anything that is not WGS84 degrees, so a projected x/y can never be placed by mistake.
LAT = re.compile(r"(^|_)(lat|latitude|latitiude)$|latitude$|latitiude$|^ycoordinate$|^y_coordinate$", re.I)
LON = re.compile(r"(^|_)(lon|lng|long|longitude|longitiude)$|longitude$|longitiude$|^xcoordinate$|^x_coordinate$", re.I)
# a bare "code" column beside a community-name column is the DM community number (stats: 'Sector & Community' + 'Code', 226 of 226 met)
COMMUNITY_NAME_COL = re.compile(r"community", re.I)


def q(con, sql):
    return con.execute(sql).fetchall()


def build_licence(con):
    """lk_d_licence from the DED licence master, named from the DED trade-name register where the serial meets."""
    have = {r[0] for r in q(con, "select table_name from information_schema.tables where table_name in "
                                 "('g_ded__license_master', 'g_ded__trade_name')")}
    if "g_ded__license_master" not in have:
        con.execute("create or replace temp table j_licence (canonical_id varchar, license_number bigint, trade_name_en varchar, "
                    "trade_name_ar varchar, category varchar, status varchar, issue_date varchar, expiry_date varchar, "
                    "cancel_date varchar, chamber_of_commerce_number varchar)")
        return
    if "g_ded__trade_name" in have:
        names = "t.trade_name_en, t.trade_name_ar"
        tn = ("left join (select %s serial, any_value(trade_name_en) trade_name_en, any_value(trade_name_ar) trade_name_ar "
              "from g_ded__trade_name group by 1) t on t.serial = m.serial" % num("trade_name_serial"))
    else:
        names, tn = "null::varchar trade_name_en, null::varchar trade_name_ar", ""
    con.execute("""create or replace temp table j_licence as
        select 'lic:' || m.n canonical_id, m.n license_number, %s, m.category, m.status, m.issue_date, m.expiry_date, m.cancel_date,
               m.chamber_of_commerce_number
        from (select %s n, any_value(license_category_desc_en) category, any_value(license_status_desc_en) status,
                     cast(max(issue_date) as varchar) issue_date, cast(max(expiry_date) as varchar) expiry_date,
                     cast(max(cancel_date) as varchar) cancel_date,
                     cast(any_value(chamber_of_commerce_number) as varchar) chamber_of_commerce_number,
                     any_value(%s) serial
              from g_ded__license_master where %s is not null group by 1) m %s""" % (
        names, num("license_number"), num("trade_name_serial_number"), num("license_number"), tn))


def load_community_polygons(con):
    """The DM community boundaries (data/board/communities.geojson, from the portal KML) as a temp table of vertices.

    21 Sep 2026: before this, a dataset carrying coordinates was attached to whichever community CENTRE lay within 3 km. That is
    wrong in both directions - it misses a point at the far end of a long community (Jabal Ali, Hadaeq Sheikh Mohammed Bin Rashid)
    and it claims a point that sits just outside a small dense one. With the boundary we can say whether the point is actually IN
    the community; the centre rule stays as the fallback for points inside no polygon at all.
    Returns True when polygons are available; everything still works without the file."""
    import io, json, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "board", "communities.geojson")
    if not os.path.exists(p):
        return False
    feats = json.load(io.open(p, encoding="utf-8"))["features"]
    rows = []
    for f in feats:
        num = f["properties"].get("comm_num")
        if not num:
            continue
        for ri, ring in enumerate(f["geometry"]["coordinates"]):
            for vi, (lon, lat) in enumerate(ring):
                rows.append((int(num), ri, vi, float(lon), float(lat)))
    if not rows:
        return False
    con.execute("create or replace temp table j_comm_poly (comm_num bigint, ring int, v int, lon double, lat double)")
    con.executemany("insert into j_comm_poly values (?, ?, ?, ?, ?)", rows)
    con.execute("""create or replace temp table j_comm_box as
                   select comm_num, min(lon) w, max(lon) e, min(lat) s, max(lat) n from j_comm_poly group by 1""")
    return True


def points_in_communities(con, pts_sql):
    """Ray casting in SQL: a point is inside a ring when an odd number of its edges cross the ray east of the point.
    The bounding box narrows the candidates first, so this stays cheap even with 223 polygons."""
    return """
        with pt as (select distinct lat, lon from %s),
             cand as (select pt.lat, pt.lon, b.comm_num from pt join j_comm_box b
                      on pt.lon between b.w and b.e and pt.lat between b.s and b.n),
             edge as (select p.comm_num, p.ring, p.lon x1, p.lat y1,
                             lead(p.lon) over (partition by p.comm_num, p.ring order by p.v) x2,
                             lead(p.lat) over (partition by p.comm_num, p.ring order by p.v) y2
                      from j_comm_poly p),
             cross_count as (
                 select c.lat, c.lon, c.comm_num,
                        sum(case when ((e.y1 > c.lat) <> (e.y2 > c.lat))
                                  and (c.lon < (e.x2 - e.x1) * (c.lat - e.y1) / nullif(e.y2 - e.y1, 0) + e.x1)
                                 then 1 else 0 end) crossings
                 from cand c join edge e on e.comm_num = c.comm_num and e.x2 is not null
                 group by 1, 2, 3)
        select lat, lon, comm_num from cross_count where crossings %% 2 = 1""" % pts_sql


def job_gov_thread(con):
    build_licence(con)
    have_poly = load_community_polygons(con)
    has_esc = q(con, "select count(*) from information_schema.tables where table_name = 'g_dld__accredited_escrow_agents'")[0][0]
    con.execute("create or replace temp table j_escrow as select %s escrow_agent_number, %s name_en from %s" % (
        (num("escrow_agent_number"), "any_value(escrow_agent_name_en)", "g_dld__accredited_escrow_agents group by 1")
        if has_esc else ("null::bigint", "null::varchar", "(select 1) where false")))
    tables = sorted(r[0] for r in q(con, "select table_name from information_schema.tables where table_type = 'BASE TABLE'")
                    if r[0].startswith("g_") and "__" in r[0])
    reg = {}
    try:
        for key, ent, ds, tn, env in q(con, "select key, entity, dataset, table_name, coalesce(env, 'stg') from gov_dataset"):
            if tn: reg["g_" + tn[4:]] = (key, ent, ds, env)
    except Exception:
        try:
            for key, ent, ds, tn in q(con, "select key, entity, dataset, table_name from gov_dataset"):
                if tn: reg["g_" + tn[4:]] = (key, ent, ds, "stg")
        except Exception:
            pass
    for sp, sql in LOOKUPS.items():
        con.execute("create or replace temp table jl_%s as select distinct cast(k as varchar) k, canonical_id from (%s) where k is not null" % (sp, sql))
    con.execute("create or replace temp table j_keymap (table_name varchar, column_name varchar, spine varchar, key_value varchar, canonical_id varchar, method varchar)")
    con.execute("create or replace temp table j_link (table_name varchar, dataset_key varchar, column_name varchar, spine varchar, "
                "rows_in bigint, keys_in bigint, keys_matched bigint, rate double, method varchar)")
    per = {}
    for t in tables:
        cols = [r[0] for r in q(con, "describe %s" % t)]
        n = q(con, "select count(*) from %s" % t)[0][0]
        dkey = reg.get(t, (t[2:].replace("__", "/", 1), t[2:].split("__")[0], "", ""))[0]
        per[t] = {"rows": n, "links": []}
        comm_code = any(COMMUNITY_NAME_COL.search(x) for x in cols)
        for c in cols:
            for rx, lk, norm in RULES + ([(r"^code$", "community", num("{c}"))] if comm_code else []):
                if not re.search(rx, c, re.I):
                    continue
                expr = "cast(%s as varchar)" % norm.replace("{c}", '"%s"' % c)   # replace, not format: parcel_key_sql carries regex braces
                spine = SPINE_OF.get(lk, lk)
                con.execute("""insert into j_keymap select '%s', '%s', '%s', v.k, l.canonical_id, 'key:%s'
                               from (select distinct %s k from %s) v join jl_%s l on l.k = v.k where v.k is not null""" % (
                    t, c, spine, lk, expr, t, lk))
                k_in, k_m = q(con, """select count(*), count(*) filter (where k in (select key_value from j_keymap
                                      where table_name = '%s' and column_name = '%s' and method = 'key:%s'))
                                      from (select distinct %s k from %s) where k is not null""" % (t, c, lk, expr, t))[0]
                rate = k_m / k_in if k_in else 0.0
                con.execute("insert into j_link values (?, ?, ?, ?, ?, ?, ?, ?, ?)", [t, dkey, c, spine, n, k_in, k_m, rate, "key:" + lk])
                per[t]["links"].append((spine, rate, k_m))
                break
        lat = next((c for c in cols if LAT.search(c)), None)
        lon = next((c for c in cols if LON.search(c)), None)
        if lat and lon:
            # a swapped pair (DHA: xcoordinate holds the latitude) is put back the right way round: Dubai's latitude (24.6-25.5)
            # and longitude (54.8-56.0) ranges do not overlap, so the swap can only be read one way
            pts = """(select * from (select distinct case when a between 54.8 and 56.0 and b between 24.6 and 25.5 then b else a end lat,
                                                   case when a between 54.8 and 56.0 and b between 24.6 and 25.5 then a else b end lon
                                     from (select try_cast("%s" as double) a, try_cast("%s" as double) b from %s))
                     where lat between 24.6 and 25.5 and lon between 54.8 and 56.0) p""" % (lat, lon, t)
            k_in = q(con, "select count(*) from %s" % pts)[0][0]
            con.execute("""insert into j_keymap select '%s', '%s,%s', 'district', null, d.canonical_id, 'point in district box'
                           from %s join lk_d_district d on p.lon between d.bbox_w and d.bbox_e and p.lat between d.bbox_s and d.bbox_n""" % (
                t, lat, lon, pts))
            if have_poly:
                con.execute("""insert into j_keymap select '%s', '%s,%s', 'community', null, c.canonical_id, 'point in community polygon'
                               from (%s) ip join lk_d_community c on c.comm_num = ip.comm_num""" % (
                    t, lat, lon, points_in_communities(con, pts)))
            # whatever no boundary claims still gets the old rule, so coverage never goes backwards
            con.execute("""insert into j_keymap select '%s', '%s,%s', 'community', null, canonical_id, 'nearest community centre <= %g km'
                           from (select p.lat, p.lon, c.canonical_id, row_number() over (partition by p.lat, p.lon order by
                                 (p.lat - c.lat)^2 + ((p.lon - c.lon) * 0.906)^2) r,
                                 111.2 * sqrt((p.lat - c.lat)^2 + ((p.lon - c.lon) * 0.906)^2) km
                                 from %s, lk_d_community c where c.lat is not null) where r = 1 and km <= %g
                           and not exists (select 1 from j_keymap k where k.table_name = '%s'
                                           and k.method = 'point in community polygon')""" % (
                t, lat, lon, NEAR_KM, pts, NEAR_KM, t))
            k_m = q(con, "select count(*) from j_keymap where table_name = '%s' and spine = 'community'" % t)[0][0]
            rate = k_m / k_in if k_in else 0.0
            con.execute("insert into j_link values (?, ?, ?, ?, ?, ?, ?, ?, ?)", [t, dkey, lat + "," + lon, "community", n, k_in, k_m, rate, "point"])
            per[t]["links"].append(("community", rate, k_m))
    # Dataset to dataset: a code list and the registers that use its codes (DED activities, commodity codes, DM usages, country
    # and profession lists) share a column. Linked when >= 50% of the smaller side's distinct values meet on the other side.
    con.execute("create or replace temp table j_codes (table_name varchar, column_name varchar, code varchar, v varchar)")
    for t in tables:
        used = {c for c, in q(con, "select distinct split_part(column_name, ',', 1) from j_link where table_name = '%s'" % t)}
        for c, typ in [(r[0], r[1]) for r in q(con, "describe %s" % t)]:
            if c in used or c.lower() in CODE_SKIP or not CODE_COL.search(c) or typ.upper() in ("DOUBLE", "FLOAT", "DECIMAL"):
                continue
            d = q(con, 'select count(distinct "%s") from %s' % (c, t))[0][0]
            if 3 <= d <= CODE_MAX_DISTINCT:
                con.execute("""insert into j_codes select distinct '%s', '%s', '%s', upper(trim(regexp_replace(cast("%s" as varchar), '[.]0+$', '')))
                               from %s where "%s" is not null""" % (t, c, CODE_ALIAS.get(c.lower(), c.lower()), c, t, c))
    con.execute("""create or replace temp table j_dslink as
        with n as (select table_name, column_name, code, count(*) n from j_codes group by all),
             m as (select a.table_name ta, a.column_name ca, b.table_name tb, b.column_name cb, a.code, count(*) common
                   from j_codes a join j_codes b on a.code = b.code and a.v = b.v and a.table_name < b.table_name group by all)
        select m.ta from_table, m.ca from_column, m.tb to_table, m.cb to_column, m.code code_list, m.common,
               round(m.common / least(na.n, nb.n), 4) rate
        from m join n na on na.table_name = m.ta and na.column_name = m.ca join n nb on nb.table_name = m.tb and nb.column_name = m.cb
        where m.common >= 3 and m.common >= %g * least(na.n, nb.n)""" % CONNECTED)
    dslinks = {}
    for a, b in q(con, "select from_table, to_table from j_dslink"):
        dslinks.setdefault(a, set()).add(b); dslinks.setdefault(b, set()).add(a)
    status_of = {}
    for t in tables:
        links = per[t]["links"]
        best = max((r for _, r, _ in links), default=0.0)
        status_of[t] = "connected" if best >= CONNECTED else "weak" if any(m for _, _, m in links) else None
    rows = []
    for t in tables:
        key, ent, ds, env = reg.get(t, (t[2:].replace("__", "/", 1), t[2:].split("__")[0], "", ""))
        links = per[t]["links"]
        best = max((r for _, r, _ in links), default=0.0)
        spines = sorted({s for s, r, m in links if m})
        cols = [r[0] for r in q(con, "describe %s" % t)]
        status = status_of[t]
        if not status and t in dslinks:
            # a code list reaches the thread through the register that uses it
            status = "via_dataset" if any(status_of.get(o) == "connected" for o in dslinks[t]) else "code_linked"
            spines.append(("dataset:" + "|".join(sorted(x[2:] for x in dslinks[t])))[:200])
        if not status and per[t]["rows"] <= CITY_MAX_ROWS and any(TIME_COL.search(c) for c in cols):
            status = "city_level"; spines.append("city:dubai")
        if not status:
            status = "keys_unmatched" if links else "catalogue_only"
        rows.append((key, t, ent, env, "org:" + ent, per[t]["rows"], ",".join(spines), round(best, 4), status))
    con.execute("""create or replace temp table j_thread (dataset_key varchar, table_name varchar, entity varchar, env varchar,
                   organisation_id varchar, rows_in bigint, spines varchar, best_rate double, status varchar)""")
    if rows:
        con.executemany("insert into j_thread values (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    # every gov dataset the pull attempted but that never landed as a clean table is on the thread as 'not landed'
    try:
        con.execute("""insert into j_thread select key, null, entity, coalesce(env, 'stg'), 'org:' || entity, 0, '', 0, 'not_landed'
                       from gov_dataset where key not in (select dataset_key from j_thread)""")
    except Exception:
        pass
    # developers that hold a DED licence: the one entity-level crosswalk this job adds
    con.execute("""create or replace temp table j_xref_gov as
        select 'gov_thread' as job, 'developer' as from_type, d.canonical_id as from_id, 'licence' as to_type, l.canonical_id as to_id,
               'holds licence' as relation, 'licence number' as "method", 1.0 as score, 'accepted' as decision, 'rule' as decided_by,
               'developer register licence ' || d.license_number || ' = DED licence master' as evidence,
               'lk_d_developer; g_ded__license_master' as source_snapshot, localtimestamp as valid_from, null::timestamp as valid_to,
               'gov_thread@' || strftime(localtimestamp, '%Y-%m-%dT%H:%M:%S') as run_id
        from lk_d_developer d join j_licence l on l.license_number = """ + num("d.license_number") + """
        where d.license_source is null or upper(d.license_source) like '%DED%'""")
    st = dict(q(con, "select status, count(*) from j_thread group by 1"))
    k_in, k_m = q(con, "select coalesce(sum(keys_in), 0), coalesce(sum(keys_matched), 0) from j_link")[0]
    ATTACHED = ("connected", "weak", "via_dataset", "code_linked", "city_level")
    landed = sum(n for s, n in st.items() if s != "not_landed")
    attached = sum(n for s, n in st.items() if s in ATTACHED)
    dev_lic = q(con, "select count(*) from j_xref_gov")[0][0]
    top = q(con, """select table_name, column_name, spine, keys_matched, keys_in, rate from j_link
                    order by keys_matched desc limit 12""")
    weak = q(con, "select table_name, column_name, spine, keys_matched, keys_in from j_link where rate < %g order by keys_in desc limit 8" % CONNECTED)
    thread = """select t.*, l.links from lk_gov_thread t left join (select table_name, string_agg(column_name || ' -> ' || spine || ' ' ||
                round(100 * rate, 1) || '%', '; ' order by rate desc) links from lk_gov_link group by 1) l using (table_name)"""
    unconnected = "select * from lk_gov_thread where status <> 'connected' order by status, rows_in desc"
    return {"tables": [("lk_d_licence", "select * from j_licence"),
                       ("lk_d_escrow_agent", "select 'esc:' || escrow_agent_number canonical_id, * from j_escrow"),
                       ("lk_gov_dataset_link", "select * from j_dslink"), ("lk_gov_key_map", "select * from j_keymap"),
                       ("lk_gov_link", "select * from j_link"), ("lk_gov_thread", "select * from j_thread")],
            "xref": [("gov_thread", "j_xref_gov")],
            "views": [("v_gov_thread", thread), ("v_gov_unconnected", unconnected)],
            # 21 Sep 2026: the contract used to be "distinct key VALUES on a spine", which the full PROD sweep diluted from 78.8% to
            # 61.3% - matched keys ROSE 6.45M -> 6.55M, but ~300 newly landed company, licence and food registers added 2.7M key
            # values that can never meet a place, and the job held itself. The goal is one thread through every dataset, so the
            # contract now measures exactly that: the share of LANDED datasets attached to the thread by any route - a spine key
            # (connected / weak), a code link to another dataset (code_linked / via_dataset), or a city-and-period anchor
            # (city_level). Only catalogue_only (names, no key at all) and keys_unmatched count against it. Key-value coverage
            # stays in the report below, where dilution is visible without gating the job.
            "keys_in": landed, "keys_matched": attached, "rows_in": len(tables),
            "note": "landed datasets attached to the thread (spine key, code link or city anchor)",
            "report": ["gov tables: %d; status %s" % (len(tables), ", ".join("%s %d" % kv for kv in sorted(st.items()))),
                       "attached: %d of %d landed datasets (%.1f%%); key values on a spine: %s of %s (%.1f%%)"
                       % (attached, landed, 100.0 * attached / max(landed, 1), format(k_m, ","), format(k_in, ","),
                          100.0 * k_m / max(k_in, 1)),
                       "licence spine: %s DED licences; developers holding one: %d" % (format(q(con, "select count(*) from j_licence")[0][0], ","), dev_lic)]
                      + ["  %-48s %-26s -> %-10s %s of %s (%.1f%%)" % (t[:48], c[:26], s, format(m, ","), format(k, ","), 100 * r)
                         for t, c, s, m, k, r in top]
                      + ["weak: %s %s -> %s %s of %s" % (t, c, s, format(m, ","), format(k, ",")) for t, c, s, m, k in weak]}
