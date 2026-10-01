"""ejari_watch_damac.py -- how long does a signed tenancy take to reach the public Ejari export? (1 Oct 2026)

Kendall signed a tenancy in a DAMAC Maison building on 30 Sep 2026. Every daily extract the portal publishes is checked for
New contracts in the DAMAC Maison projects (Business Bay / Downtown) starting 29 Sep - 31 Oct 2026; the first extract that
shows a matching contract gives the signing-to-register lag the app's "contracts signed" panel must state. Counts and dates
only - no names, no amounts, nothing stored beyond counts.

Reads the parts on disk (data/raw_downloads/dd/dld__rent_contracts__<stamp>__partNN.csv.gz) - no lake needed.
    python scripts/ejari_watch_damac.py [--stamp 2026-09-30]      default: the newest extract on disk
Writes data/dld/ejari_watch/damac_maison_<stamp>.json and prints the table.
"""
import glob, json, os, re, sys, time
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
OUT = os.path.join(ROOT, "data", "dld", "ejari_watch")
# DAMAC Maison hotel-apartment buildings as the Ejari register names them (checked 1 Oct 2026: Canal Views = THE VOGUE;
# Cour Jardin and Dubai Mall Street have no Ejari project name at all). Pattern terms catch any later spelling.
PROJECTS = ["THE VOGUE", "PRIVE BY DAMAC", "MAJESTINE", "UPPER CREST", "THE DISTINCTION", "AYKON CITY", "AYKON CITY 2"]
PATTERN = r"(damac maison|cour jardin|mall street|bays? ?edge|canal view|vogue|maison)"
FROM, TO = "2026-09-29", "2026-10-31"


def stamps():
    return sorted({m.group(1) for p in glob.glob(os.path.join(DD, "dld__rent_contracts__*__part*"))
                   for m in [re.search(r"__(\d{4}-\d{2}-\d{2})__part", os.path.basename(p))] if m})


def parts(stamp):
    ps = sorted(glob.glob(os.path.join(DD, "dld__rent_contracts__%s__part*" % stamp)))
    gz = [p for p in ps if p.endswith(".csv.gz")]
    return gz if gz else [p for p in ps if p.endswith(".csv")]


def main():
    stamp = sys.argv[sys.argv.index("--stamp") + 1] if "--stamp" in sys.argv else (stamps() or [None])[-1]
    if not stamp:
        sys.exit("no rent_contracts parts on disk")
    ps = parts(stamp)
    con = duckdb.connect()
    con.execute("create view E as select * from read_csv(%r, all_varchar=true, header=true, union_by_name=true)" % ps)
    names = ", ".join("'%s'" % n for n in PROJECTS)
    t0 = time.time()
    rows = con.execute(f"""
        with c as (select distinct contract_id, upper(trim(project_name_en)) project, area_name_en area, contract_start_date start_date,
                          ejari_property_sub_type_en band, contract_reg_type_en reg
                   from E where (upper(trim(project_name_en)) in ({names}) or regexp_matches(lower(coalesce(project_name_en, '')), '{PATTERN}'))
                     and contract_start_date between '{FROM}' and '{TO}')
        select project, area, start_date, band, reg, count(*) contracts from c group by all order by project, start_date, band""").fetchall()
    scope = con.execute(f"""select upper(trim(project_name_en)), count(distinct contract_id) from E
        where upper(trim(project_name_en)) in ({names}) or regexp_matches(lower(coalesce(project_name_en, '')), '{PATTERN}')
        group by 1 order by 2 desc""").fetchall()
    max_start = con.execute(f"select max(contract_start_date) from E where contract_start_date <= '{TO}'").fetchone()[0]
    out = {"extract": stamp, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "window": [FROM, TO],
           "projects_in_scope": [{"project": p, "contracts_all_time": n} for p, n in scope],
           "newest_start_date_in_extract": max_start,
           "fields": ["project", "area", "start_date", "band", "reg_type", "contracts"],
           "rows": [list(r) for r in rows],
           "new_contracts_in_window": sum(r[5] for r in rows if r[4] == "New")}
    # the DLD gateway feed (fetch_dld.py, daily) carries REGISTRATION_DATE - the filing time - which the portal export lacks;
    # the newest rents-<date>.csv shows filings in scope since 29 Sep, so the two channels can be compared
    gw = sorted(glob.glob(os.path.join(ROOT, "data", "rents-20??-??-??*.csv")))
    if gw:
        g = gw[-1]
        try:
            filed = con.execute(f"""select PROJECT_EN, substr(REGISTRATION_DATE, 1, 16) filed_at, substr(START_DATE, 1, 10) start_on, VERSION_EN,
                                           PROP_SUB_TYPE_EN
                                    from read_csv('{g.replace(os.sep, "/")}', all_varchar=true, header=true)
                                    where (upper(trim(PROJECT_EN)) in ({names}) or regexp_matches(lower(coalesce(PROJECT_EN, '')), '{PATTERN}'))
                                      and REGISTRATION_DATE >= '{FROM}' order by REGISTRATION_DATE""").fetchall()
            out["gateway_feed"] = {"file": os.path.basename(g), "newest_registration": con.execute(
                f"select max(REGISTRATION_DATE) from read_csv('{g.replace(os.sep, '/')}', all_varchar=true, header=true)").fetchone()[0],
                "fields": ["project", "filed_at", "start_on", "version", "sub_type"], "rows": [list(r) for r in filed],
                "note": "AYKON CITY and AYKON CITY 2 list the same contracts under both labels - count once"}
            print("gateway feed %s: %d filings in scope since %s (newest registration %s)" % (
                os.path.basename(g), len(filed), FROM, out["gateway_feed"]["newest_registration"]))
        except Exception as e:
            out["gateway_feed"] = {"file": os.path.basename(g), "error": str(e)[:160]}
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "damac_maison_%s.json" % stamp), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("extract %s (%d parts, %.0fs); newest start date anywhere: %s" % (stamp, len(ps), time.time() - t0, max_start))
    print("in scope:", ", ".join("%s %d" % (p, n) for p, n in scope))
    print("New contracts starting %s..%s in scope: %d" % (FROM, TO, out["new_contracts_in_window"]))
    for r in rows:
        print("  %-18s %-14s %s %-20s %-6s %d" % (r[0][:18], (r[1] or "")[:14], r[2], (r[3] or "")[:20], r[4], r[5]))


if __name__ == "__main__":
    main()
