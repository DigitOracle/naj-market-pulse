"""build_ejari_daily.py -- "contracts signed through Ejari": per day, building, district, developer and bedroom band (1 Oct 2026).

Why. Ejari (pp_dld__rent_contracts, the data.dubai portal's full export) is current to within a day of its extract date, so
"how many tenancy contracts did this building / this developer / this district sign on this day" is answerable. Kendall asked
for it as a broker search in the app (Rings builds the app side). It is a LETTINGS-ACTIVITY signal, not availability.

Grain. One row per contract_start_date x district x area x project x bedroom band x New/Renew, with distinct contracts, the
properties they cover (no_of_prop), and the median/quartile annual rent where 3 or more contracts share the row. Ejari carries
no unit number, so the project is the finest place; and no registration date, so "signed" means the contract's START date -
the newest days are undercounted until filings catch up (the app shows that caveat).

Keys reuse data/dld/beds_left: key = "<district>:<app building id>" where the project is bound to an app footprint, else
"dld:<project a-z0-9>"; dld_project spelled as the register has it (whitespace collapsed). Contracts with no project (area
only, mostly older stock and villas) keep district + area with project null, so district totals stay complete.

desk_like (LOD 3's trap, 1 Oct): an Office band in a project with 20+ New contracts in the last 30 days at a median under
AED 25,000 is flexi-desk licensing, not letting - flagged so "most let" rankings use homes.

Output (files only, nothing published):
  data/dld/ejari_daily/ejari_daily_<district>.json    last 400 days through as_of, plus starts up to 31 days ahead
  data/dld/ejari_daily/ejari_recent_<district>.json   last 30 days only (fast load for the building page)
  data/dld/ejari_daily/ejari_daily_dubai.json         per area per day and per developer per day, all of Dubai
  lake table lk_ejari_daily                           the same rows, all districts (plus district null for unmapped areas)
    python scripts/build_ejari_daily.py [--no-lake]
"""
import glob, json, os, re, sys, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld", "ejari_daily")
import lake

BANDS = {"Studio": "studio", "1bed room+Hall": "1", "2 bed rooms+hall": "2", "3 bed rooms+hall": "3+", "4 bed rooms+hall": "3+",
         "5 bed rooms+hall": "3+", "6 bed rooms+hall": "3+", "Office": "office", "Shop": "retail", "Shop with a mezzanine": "retail",
         "Showroom": "retail", "Kiosk": "retail", "Restaurant": "retail", "Room in labor Camp": "staff", "Labor Camp": "staff",
         "Portacabin Rooms": "staff"}
# 1 Oct 2026 (Kendall): the register's own sub type ("1bed room+Hall", "Hotel", "Villa", "Office"...) and usage are grouping
# columns beside the normalised band, so hotel apartments (the DAMAC Maison case) show as their own type instead of folding
# into studios; and every row carries the register's project identity - project_name_en, project_name_ar, project_number.
FIELDS = ["date", "district", "area", "dld_project", "project_name_ar", "dld_project_number", "key", "developer_number", "developer",
          "beds", "sub_type", "usage", "reg_type", "contracts", "props", "rent_median", "rent_q1", "rent_q3", "desk_like"]


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_ws(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def district_areas(con):
    """[(DLD area, app district)] - an area can serve two districts (Al Thanyah Fifth = jltnorth + althanyahfifth), so this
    is pairs, not a dict. Source of record: dld_rent_buildings.DLD_AREA (the twin's own map, corrected 9 and 21 Sep 2026 -
    Sobha Hartland = Al Merkadh, Meydan One = Nad Al Shiba First, Liwan = Wadi Al Safa 2); the sub_community crosswalk only
    fills areas that map has not named. 1 Oct 2026: the crosswalk alone left six districts with no Ejari file."""
    from dld_rent_buildings import DLD_AREA
    pairs = [(a, d) for a, ds in DLD_AREA.items() for d in ds]
    named = set(DLD_AREA)
    for d, a in con.execute("""
            select distinct sc.district, k.dld_area_names
            from sub_community sc join sub_community_dm scd on scd.sub_id = sc.sub_id
            join lk_community k on k.comm_num = try_cast(scd.comm_num as bigint)
            where k.dld_area_names is not null""").fetchall():
        if a not in named and (a, d) not in pairs:
            pairs.append((a, d))
    return pairs


def beds_left_keys():
    keys = {}
    for p in glob.glob(os.path.join(ROOT, "data", "dld", "beds_left", "beds_left_*.json")):
        d = json.load(open(p, encoding="utf-8"))
        for r in d["rows"]:
            if r.get("app_key"):
                keys[(d["district"], clean_ws(r["dld_project"]).lower())] = r["app_key"]
    return keys


def main():
    write_lake = "--no-lake" not in sys.argv
    con = lake.connect(read_only=True)          # reads only; released before the aggregation
    t0 = time.time()
    as_of = con.execute("select max(try_cast(substr(load_timestamp, 1, 10) as date)) from pp_dld__rent_contracts").fetchone()[0]
    print("extract date (as_of):", as_of)
    con.execute("create temp table d2a (area varchar, district varchar)")
    con.executemany("insert into d2a values (?, ?)", district_areas(con))
    # an area shared by two districts appears under each district; Dubai-wide rollups count it once, under its first district
    con.execute("create temp table prim as select area, min(district) district from d2a group by 1")
    band_sql = "case " + " ".join("when ejari_property_sub_type_en = '%s' then '%s'" % (k.replace("'", "''"), v) for k, v in BANDS.items()) + " else 'other' end"
    con.execute(f"""create temp table base as
        select try_cast(contract_start_date as date) d, coalesce(x.district, '') district, r.area_name_en area,
               nullif(regexp_replace(trim(r.project_name_en), '\\s+', ' ', 'g'), '') project,
               nullif(regexp_replace(trim(r.project_name_ar), '\\s+', ' ', 'g'), '') project_ar,
               try_cast(try_cast(r.project_number as double) as bigint) project_number,
               {band_sql} beds, nullif(trim(r.ejari_property_sub_type_en), '') sub_type, nullif(trim(r.property_usage_en), '') usage,
               coalesce(nullif(trim(r.contract_reg_type_en), ''), 'Unknown') reg_type,
               r.contract_id, try_cast(r.no_of_prop as double) props, try_cast(r.annual_amount as double) rent
        from pp_dld__rent_contracts r left join d2a x on x.area = r.area_name_en
        where try_cast(contract_start_date as date) between date '{as_of}' - interval 400 day and date '{as_of}' + interval 31 day""")
    n_base = con.execute("select count(*), count(distinct contract_id) from base").fetchone()
    print("contract lines in window: %s (%s contracts)" % tuple(format(x, ",") for x in n_base))
    # developer via the project register; project_number -> project_id -> developer_number -> developer name
    con.execute("""create temp table dev as
        select pn.pn project_number, any_value(p.developer_number) developer_number, any_value(dv.name_en) developer
        from (select distinct project_id, try_cast(project_number as bigint) pn from lk_project_numbers where project_id is not null) pn
        join lk_d_project p on p.project_id = pn.project_id
        left join lk_d_developer dv on dv.developer_number = p.developer_number
        where pn.pn is not null group by 1""")
    con.execute("create temp table pnames as select distinct try_cast(project_number as bigint) pn, name_ar "
                "from lk_d_project where project_number is not null")
    # every lake read is done: release the catalogue before the long aggregation - on this lake any attached connection,
    # read-only included, locks the SQLite catalogue for everyone while it lives (1 Oct 2026: seconds, not minutes)
    con.execute("USE memory"); con.execute("DETACH %s" % lake.ALIAS)
    con.execute(f"""create temp table desk as
        select project, beds from base
        where beds = 'office' and reg_type = 'New' and d between date '{as_of}' - interval 30 day and date '{as_of}'
        group by 1, 2 having count(distinct contract_id) >= 20 and median(rent) < 25000""")
    con.execute("""create temp table agg as
        select b.d, b.district, b.area, b.project, any_value(b.project_ar) project_ar, b.project_number, dv.developer_number, dv.developer,
               b.beds, b.sub_type, b.usage, b.reg_type,
               count(distinct b.contract_id) contracts, round(sum(b.props)) props,
               case when count(distinct b.contract_id) >= 3 then round(median(b.rent)) end rent_median,
               case when count(distinct b.contract_id) >= 3 then round(quantile_cont(b.rent, 0.25)) end rent_q1,
               case when count(distinct b.contract_id) >= 3 then round(quantile_cont(b.rent, 0.75)) end rent_q3,
               (b.project, b.beds) in (select project, beds from desk) desk_like
        from base b left join dev dv on dv.project_number = b.project_number
        group by b.d, b.district, b.area, b.project, b.project_number, dv.developer_number, dv.developer, b.beds, b.sub_type, b.usage, b.reg_type""")
    keys = beds_left_keys()
    rows = con.execute("select * from agg order by d, district, area, project, beds, sub_type, reg_type").fetchall()
    cols = [c[0] for c in con.execute("describe agg").fetchall()]
    by_district = defaultdict(list)
    out_rows = []
    for r in rows:
        rec = dict(zip(cols, r))
        proj = rec["project"]
        key = None
        if proj:
            key = keys.get((rec["district"], proj.lower())) or "dld:" + norm_key(proj)
        row = {"date": rec["d"].isoformat(), "district": rec["district"] or None, "area": rec["area"], "dld_project": proj,
               "project_name_ar": rec["project_ar"], "dld_project_number": rec["project_number"], "key": key,
               "developer_number": rec["developer_number"], "developer": rec["developer"], "beds": rec["beds"],
               "sub_type": rec["sub_type"], "usage": rec["usage"], "reg_type": rec["reg_type"], "contracts": rec["contracts"],
               "props": rec["props"], "rent_median": rec["rent_median"], "rent_q1": rec["rent_q1"], "rent_q3": rec["rent_q3"],
               "desk_like": bool(rec["desk_like"])}
        out_rows.append(row)
        if row["district"]:
            by_district[row["district"]].append(row)
    os.makedirs(OUT, exist_ok=True)
    source = "pp_dld__rent_contracts, data.dubai extract %s; projects/developers: lk_project_numbers, lk_d_project, lk_d_developer; keys: data/dld/beds_left" % as_of
    recent_from = (as_of.fromordinal(as_of.toordinal() - 30)).isoformat()
    caveat = ("Ejari records the contract's start date; filing can come later, so the newest days are undercounted. "
              "No unit numbers: the project (building) is the finest grain. Lettings activity, not availability.")
    for d, rs in sorted(by_district.items()):
        head = {"as_of": as_of.isoformat(), "source": source, "district": d, "caveat": caveat, "fields": FIELDS}
        json.dump(dict(head, rows=rs), open(os.path.join(OUT, "ejari_daily_%s.json" % d), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        json.dump(dict(head, window="last 30 days", rows=[r for r in rs if r["date"] >= recent_from]),
                  open(os.path.join(OUT, "ejari_recent_%s.json" % d), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # Dubai-wide project index: look a project up by number or by either name (name_ar from Ejari, else the DLD projects register)
    idx_rows = con.execute("""
        select a.project_number, any_value(a.project), coalesce(any_value(a.project_ar), any_value(p.name_ar)), any_value(a.area),
               any_value(nullif(a.district, '')), any_value(a.developer)
        from agg a left join pnames p on p.pn = a.project_number
        where a.project_number is not null and (a.district = '' or (a.area, a.district) in (select area, district from prim)) group by 1""").fetchall()
    index = {}
    for pn, name_en, name_ar, area, district, developer in idx_rows:
        k = keys.get((district or "", (name_en or "").lower())) if name_en else None
        index[str(pn)] = {"name_en": name_en, "name_ar": name_ar, "area": area, "district": district,
                          "key": k or ("dld:" + norm_key(name_en) if name_en else None), "developer": developer}
    json.dump({"as_of": as_of.isoformat(), "source": source, "projects": len(index), "index": index},
              open(os.path.join(OUT, "ejari_projects_index.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    once = "(district = '' or (area, district) in (select area, district from prim))"
    per_area = con.execute("select d, area, beds, reg_type, sum(contracts), sum(props) from agg where %s group by all order by 1, 2, 3, 4" % once).fetchall()
    per_dev = con.execute("""select d, developer_number, any_value(developer), beds, reg_type, sum(contracts), sum(props)
                             from agg where developer_number is not null and %s group by d, developer_number, beds, reg_type order by 1, 2, 4, 5""" % once).fetchall()
    json.dump({"as_of": as_of.isoformat(), "source": source, "caveat": caveat,
               "per_area": {"fields": ["date", "area", "beds", "reg_type", "contracts", "props"],
                            "rows": [[r[0].isoformat(), r[1], r[2], r[3], r[4], r[5]] for r in per_area]},
               "per_developer": {"fields": ["date", "developer_number", "developer", "beds", "reg_type", "contracts", "props"],
                                 "rows": [[r[0].isoformat(), r[1], r[2], r[3], r[4], r[5], r[6]] for r in per_dev]}},
              open(os.path.join(OUT, "ejari_daily_dubai.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("%d rows; %d districts; %d area-day rows; %d developer-day rows; %d projects in the index; %.0fs" % (
        len(out_rows), len(by_district), len(per_area), len(per_dev), len(index), time.time() - t0))
    n_key = sum(1 for r in out_rows if r["key"] and not r["key"].startswith("dld:"))
    n_proj = sum(1 for r in out_rows if r["dld_project"])
    print("rows with a project: %d, of which bound to an app building: %d; rows with a developer: %d; desk_like rows: %d" % (
        n_proj, n_key, sum(1 for r in out_rows if r["developer"]), sum(1 for r in out_rows if r["desk_like"])))
    if write_lake:
        con.execute('create temp table keyed (district varchar, project_lower varchar, "key" varchar)')
        con.executemany("insert into keyed values (?, ?, ?)", [(d, p, k) for (d, p), k in keys.items()])
        def body():
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute("""create or replace table lk_ejari_daily as
                    select a.d as date, nullif(a.district, '') district, a.area, a.project dld_project, a.project_ar project_name_ar,
                           a.project_number dld_project_number,
                           case when a.project is null then null
                                else coalesce(k."key", 'dld:' || regexp_replace(lower(a.project), '[^a-z0-9]', '', 'g')) end "key",
                           a.developer_number, a.developer, a.beds, a.sub_type, a.usage, a.reg_type, a.contracts, a.props,
                           a.rent_median, a.rent_q1, a.rent_q3, a.desk_like, date '%s' as_of
                    from agg a left join keyed k on k.district = a.district and k.project_lower = lower(a.project)""" % as_of)
                con.execute("COMMIT")
            except Exception:
                try: con.execute("ROLLBACK")
                except Exception: pass
                raise
        lake.attach(con, read_only=False); con.execute("USE %s" % lake.ALIAS)      # one short write window
        try:
            lake.retry(body, "lk_ejari_daily")
            print("published lk_ejari_daily:", con.execute("select count(*) from lk_ejari_daily").fetchone()[0], "rows")
        finally:
            con.execute("USE memory"); con.execute("DETACH %s" % lake.ALIAS)


if __name__ == "__main__":
    main()
