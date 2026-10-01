"""build_ejari_filed.py -- Ejari contracts by FILING day, from the DLD gateway rents feed (1 Oct 2026).

Why. The portal's Ejari export has contract ids and sub types but no registration date; the DLD open-data gateway feed that
fetch_dld.py pulls every morning (data/rents-<date>.csv) has REGISTRATION_DATE to the second - the filing time - but no contract
id and no project number. "Signed yesterday / this week" needs the filing time, so this is the same table as build_ejari_daily
on the "filed" basis: date = REGISTRATION_DATE's day (Dubai time, as the feed gives it), same field names, basis: "filed".

Quirks of the feed, handled here:
  one contract, many rows   the feed emits a row per PROJECT label within a master project (AYKON CITY and AYKON CITY 2; the
                            Creek Beach family under 8+ labels). Rows are deduplicated on everything but the label; a known
                            alias collapses to its canonical label; any other multi-label group is counted ONCE under its master
                            project with dld_project null, project_candidates listing the labels and project_ambiguous true.
  no bedroom count          ROOMS is null on ~95% of rows: beds is 'studio' for Studio, the ROOMS band where present, else null.
  trailing window           each daily file holds contracts STARTING in the last 28 days, so filings for starts outside the
                            pulled windows (forward-dated contracts) are absent until fetch_dld's window is extended.
All files on disk are unioned, so the history grows by a day each run.

Output (files only): data/dld/ejari_daily/ejari_filed_<district>.json, ejari_filed_recent_<district>.json (30 days),
ejari_filed_dubai.json; lake table lk_ejari_filed.
    python scripts/build_ejari_filed.py [--no-lake]
"""
import glob, json, os, re, sys, time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld", "ejari_daily")
import lake
from build_ejari_daily import district_areas, beds_left_keys, norm_key, clean_ws, FIELDS

ALIAS = {"AYKON CITY": "AYKON CITY 2"}          # the feed's second label for the same contracts (checked 1 Oct 2026: 62/62 pairs)
FIELDS_FILED = FIELDS + ["project_candidates", "project_ambiguous", "master_project"]


def main():
    write_lake = "--no-lake" not in sys.argv
    con = lake.connect(read_only=True)          # reads only; released before anything slow
    t0 = time.time()
    # the only lake reads: the area->district pairs and the project names. Then the catalogue is released - on this lake any
    # attached connection, read-only included, locks the SQLite catalogue for everyone (1 Oct 2026: seconds, not minutes)
    con.execute("create temp table d2a (area varchar, district varchar)")
    con.executemany("insert into d2a values (?, ?)", district_areas(con))
    con.execute("create temp table prim as select area, min(district) district from d2a group by 1")
    con.execute("create temp table pnames as select try_cast(p.project_number as bigint) pn, p.name_en, p.name_ar, d.name_en developer "
                "from lk_d_project p left join lk_d_developer d on d.developer_number = p.developer_number where p.project_number is not null")
    con.execute("USE memory"); con.execute("DETACH %s" % lake.ALIAS)
    files = sorted(glob.glob(os.path.join(ROOT, "data", "rents-20??-??-??*.csv")))
    if not files:
        sys.exit("no data/rents-*.csv on disk")
    as_of = max(re.search(r"rents-(\d{4}-\d{2}-\d{2})", os.path.basename(f)).group(1) for f in files)
    con.execute("create temp table raw as select * from read_csv(%r, all_varchar=true, header=true, union_by_name=true)" % [f.replace("\\", "/") for f in files])
    n_raw = con.execute("select count(*) from raw").fetchone()[0]
    alias_sql = "case " + " ".join("when upper(trim(PROJECT_EN)) = '%s' then '%s'" % (k, v) for k, v in ALIAS.items()) + " else nullif(regexp_replace(trim(PROJECT_EN), '\\s+', ' ', 'g'), '') end"
    con.execute(f"""create temp table rows as
        select distinct REGISTRATION_DATE reg, START_DATE st, END_DATE en, CONTRACT_AMOUNT amt, ANNUAL_AMOUNT rent_s, ACTUAL_AREA sqm,
               nullif(trim(PROP_SUB_TYPE_EN), '') sub_type, nullif(trim(USAGE_EN), '') usage, VERSION_EN ver, ROOMS rooms,
               AREA_EN area, nullif(trim(MASTER_PROJECT_EN), '') master, {alias_sql} project
        from raw where REGISTRATION_DATE is not null""")
    # one contract = everything but the label; collect the labels it was emitted under
    con.execute("""create temp table contracts as
        select reg, st, en, amt, rent_s, sqm, sub_type, usage, ver, rooms, area, any_value(master) master,
               list_sort(list(distinct project)) labels, count(distinct project) n_labels
        from rows group by reg, st, en, amt, rent_s, sqm, sub_type, usage, ver, rooms, area""")
    n_contracts, n_multi = con.execute("select count(*), count(*) filter (where n_labels > 1) from contracts").fetchone()
    con.execute(f"""create temp table base as
        select try_cast(substr(c.reg, 1, 10) as date) d, coalesce(x.district, '') district, c.area,
               case when c.n_labels = 1 then c.labels[1] end project, c.labels, c.n_labels > 1 ambiguous, c.master,
               case when lower(c.sub_type) like 'studio%' then 'studio'
                    when c.rooms in ('1') then '1' when c.rooms in ('2') then '2' when c.rooms in ('3','4','5','6','7') then '3+'
                    when c.sub_type = 'Office' then 'office' when c.sub_type in ('Shop','Showroom') then 'retail'
                    when c.sub_type in ('Labor Camps') then 'staff' end beds,
               c.sub_type, c.usage, case c.ver when 'Renewed' then 'Renew' else coalesce(c.ver, 'Unknown') end reg_type,
               try_cast(c.rent_s as double) rent, try_cast(c.amt as double) amt
        from contracts c left join d2a x on x.area = c.area
        where try_cast(substr(c.reg, 1, 10) as date) >= date '{as_of}' - interval 400 day""")
    # project number / Arabic name / developer by name, from the portal-based index when it exists, else the lake
    idx_path = os.path.join(OUT, "ejari_projects_index.json")
    name_to = {}
    if os.path.exists(idx_path):
        for pn, v in json.load(open(idx_path, encoding="utf-8"))["index"].items():
            if v.get("name_en"):
                name_to[clean_ws(v["name_en"]).lower()] = (int(pn), v.get("name_ar"), v.get("developer"))
    if not name_to:
        for pn, name, ar, dev in con.execute("select pn, name_en, name_ar, developer from pnames").fetchall():
            if name:
                name_to.setdefault(clean_ws(name).lower(), (pn, ar, dev))
    desk = set(r[0] for r in con.execute(f"""select project from base where sub_type = 'Office' and reg_type = 'New' and project is not null
        and d between date '{as_of}' - interval 30 day and date '{as_of}' group by 1 having count(*) >= 20 and median(rent) < 25000""").fetchall())
    agg = con.execute("""select d, district, area, project, labels, ambiguous, master, beds, sub_type, usage, reg_type, count(*) contracts,
               case when count(*) >= 3 then round(median(rent)) end, case when count(*) >= 3 then round(quantile_cont(rent, 0.25)) end,
               case when count(*) >= 3 then round(quantile_cont(rent, 0.75)) end
        from base group by d, district, area, project, labels, ambiguous, master, beds, sub_type, usage, reg_type
        order by d, district, area, project, beds, sub_type, reg_type""").fetchall()
    keys = beds_left_keys()
    out_rows, by_district = [], defaultdict(list)
    for d, district, area, project, labels, ambiguous, master, beds, sub_type, usage, reg_type, n, med, q1, q3 in agg:
        meta = name_to.get(clean_ws(project).lower()) if project else None
        key = None
        if project:
            key = keys.get((district, clean_ws(project).lower())) or "dld:" + norm_key(project)
        elif master:
            key = "master:" + norm_key(master)
        row = {"date": d.isoformat(), "district": district or None, "area": area, "dld_project": project,
               "project_name_ar": meta[1] if meta else None, "dld_project_number": meta[0] if meta else None, "key": key,
               "developer_number": None, "developer": meta[2] if meta else None, "beds": beds, "sub_type": sub_type, "usage": usage,
               "reg_type": reg_type, "contracts": n, "props": None, "rent_median": med, "rent_q1": q1, "rent_q3": q3,
               "desk_like": project in desk if project else False,
               "project_candidates": list(labels) if ambiguous else None, "project_ambiguous": bool(ambiguous), "master_project": master}
        out_rows.append(row)
        if row["district"]:
            by_district[row["district"]].append(row)
    os.makedirs(OUT, exist_ok=True)
    source = "DLD open-data gateway rents feed (scripts/fetch_dld.py), %d daily files to %s, deduplicated across project labels; project numbers/Arabic names/developers by name from ejari_projects_index.json" % (len(files), as_of)
    caveat = ("basis filed: date is the REGISTRATION_DATE (filing) day. The feed holds contracts STARTING in each day's trailing 28-day window, "
              "so filings for forward-dated starts are missing until the pull window is extended. Bedroom band is unknown on most rows "
              "(ROOMS null); sub_type is the feed's own coarse type. A contract emitted under several project labels is counted once "
              "under its master project (project_ambiguous). Lettings activity, not availability.")
    recent_from = (time.strptime(as_of, "%Y-%m-%d"))
    import datetime as dt
    recent_from = (dt.date(*recent_from[:3]) - dt.timedelta(days=30)).isoformat()
    for dname, rs in sorted(by_district.items()):
        head = {"as_of": as_of, "basis": "filed", "source": source, "district": dname, "caveat": caveat, "fields": FIELDS_FILED}
        json.dump(dict(head, rows=rs), open(os.path.join(OUT, "ejari_filed_%s.json" % dname), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        json.dump(dict(head, window="last 30 days", rows=[r for r in rs if r["date"] >= recent_from]),
                  open(os.path.join(OUT, "ejari_filed_recent_%s.json" % dname), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    per_area = con.execute("""select d, area, sub_type, reg_type, count(*) from base
                              where district = '' or (area, district) in (select area, district from prim) group by all order by 1, 2, 3, 4""").fetchall()
    json.dump({"as_of": as_of, "basis": "filed", "source": source, "caveat": caveat,
               "per_area": {"fields": ["date", "area", "sub_type", "reg_type", "contracts"], "rows": [[r[0].isoformat(), r[1], r[2], r[3], r[4]] for r in per_area]}},
              open(os.path.join(OUT, "ejari_filed_dubai.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("files %d (to %s); raw rows %s -> %s contracts after de-labelling (%s emitted under 2+ labels, %.1f%%); %d output rows in %d districts; %.0fs" % (
        len(files), as_of, format(n_raw, ","), format(n_contracts, ","), format(n_multi, ","), 100.0 * n_multi / n_contracts, len(out_rows), len(by_district), time.time() - t0))
    print("rows with a unique project: %d; label-ambiguous (counted under master): %d; with a project number: %d; beds known: %d" % (
        sum(1 for r in out_rows if r["dld_project"]), sum(1 for r in out_rows if r["project_ambiguous"]),
        sum(1 for r in out_rows if r["dld_project_number"]), sum(1 for r in out_rows if r["beds"])))
    if write_lake:
        con.execute('''create temp table outrows ("date" date, district varchar, area varchar, dld_project varchar, project_name_ar varchar,
                       dld_project_number bigint, "key" varchar, developer varchar, beds varchar, sub_type varchar, usage varchar, reg_type varchar,
                       contracts bigint, rent_median double, rent_q1 double, rent_q3 double, desk_like boolean, master_project varchar)''')
        con.executemany("insert into outrows values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(r["date"], r["district"], r["area"], r["dld_project"], r["project_name_ar"], r["dld_project_number"], r["key"], r["developer"],
                          r["beds"], r["sub_type"], r["usage"], r["reg_type"], r["contracts"], r["rent_median"], r["rent_q1"], r["rent_q3"],
                          r["desk_like"], r["master_project"]) for r in out_rows])
        def body():
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute("create or replace table lk_ejari_filed as select *, date '%s' as_of, 'filed' basis from outrows" % as_of)
                con.execute("COMMIT")
            except Exception:
                try: con.execute("ROLLBACK")
                except Exception: pass
                raise
        lake.attach(con, read_only=False); con.execute("USE %s" % lake.ALIAS)      # one short write window
        try:
            lake.retry(body, "lk_ejari_filed")
            print("published lk_ejari_filed:", con.execute("select count(*) from lk_ejari_filed").fetchone()[0], "rows")
        finally:
            con.execute("USE memory"); con.execute("DETACH %s" % lake.ALIAS)


if __name__ == "__main__":
    main()
