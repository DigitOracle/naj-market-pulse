"""Buildings as the Dubai Land Department's own transactions describe them - from the full transactions export.

Input: the two export files Kendall downloaded (Downloads/transactions_2026-09-04_17-34-00_000N.csv, ~1.8 M rows together).
Per (area, project, building name) this aggregates every SALE: how many, by rooms type, median size per type, first and last
registration, usage split, the register's nearest metro / mall / landmark. Two uses:
  1. UNIT MIX  - "sold by type" per building (an initial off-plan sale is one unit; for finished stock it is a lower bound).
  2. NAMES     - building_name_en per area/project is an authoritative name list to geocode onto footprints.

Output: data/dld/tx_buildings.json      {"generated","rows":N,"buildings":[{area, project, master, building, sales, by_rooms:{type:{n,median_sqm}},
                                          first, last, usage:{...}, metro, mall, landmark, median_sqm, median_aed_sqm}]}
        data/dld/tx_buildings_<slug>.json  the same, filtered to each modelled district (by DLD area name).
Usage: python scripts/dld_tx_buildings.py [--files a.csv b.csv]
"""
import duckdb, glob, json, os, sys, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld"); os.makedirs(OUT, exist_ok=True)
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from dld_rent_buildings import DLD_AREA   # 6 Sep 2026: one shared map, all 40 modelled districts


def main():
    files = sys.argv[sys.argv.index("--files") + 1:] if "--files" in sys.argv else sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\transactions_*.csv"))
    files = [f for f in files if "(1)" not in f]
    print("files:", [os.path.basename(f) for f in files])
    con = duckdb.connect(); t = time.time()
    src = " UNION ALL ".join(f"select * from read_csv_auto('{f.replace(chr(92), '/')}', sample_size=50000, all_varchar=true)" for f in files)
    con.execute(f"create table tx as select * from ({src})")
    n = con.execute("select count(*) from tx").fetchone()[0]; print(f"rows {n:,} loaded in {time.time()-t:.0f}s")
    q = """
    with s as (
      select area_name_en as area, coalesce(nullif(project_name_en,''),'') as project, coalesce(nullif(master_project_en,''),'') as master,
             coalesce(nullif(building_name_en,''),'') as building, coalesce(nullif(rooms_en,''),'n/a') as rooms,
             try_cast(procedure_area as double) as sqm, try_cast(meter_sale_price as double) as aed_sqm, try_cast(instance_date as date) as d,
             coalesce(nullif(property_usage_en,''),'?') as usage, nearest_metro_en as metro, nearest_mall_en as mall, nearest_landmark_en as landmark
      from tx where trans_group_en = 'Sales' and property_type_en = 'Unit' and area_name_en is not null
    )
    select area, project, master, building, count(*) as sales, min(d) as first_d, max(d) as last_d,
           median(sqm) as median_sqm, median(aed_sqm) as median_aed_sqm,
           any_value(metro) as metro, any_value(mall) as mall, any_value(landmark) as landmark,
           map_from_entries(list(distinct struct_pack(k:=rooms, v:=1))) as _dummy
    from s group by all
    """
    # per building header
    hdr = con.execute("""
      with s as (select area_name_en as area, coalesce(nullif(project_name_en,''),'') as project, coalesce(nullif(master_project_en,''),'') as master,
             coalesce(nullif(building_name_en,''),'') as building, try_cast(procedure_area as double) as sqm, try_cast(meter_sale_price as double) as aed_sqm,
             try_cast(instance_date as date) as d, nearest_metro_en as metro, nearest_mall_en as mall, nearest_landmark_en as landmark
             from tx where trans_group_en='Sales' and property_type_en='Unit' and area_name_en is not null)
      select area, project, master, building, count(*) sales, cast(min(d) as varchar) first_d, cast(max(d) as varchar) last_d,
             round(median(sqm),1) median_sqm, round(median(aed_sqm)) median_aed_sqm, any_value(metro) metro, any_value(mall) mall, any_value(landmark) landmark
      from s group by all having count(*) >= 3 order by area, project, building""").fetchall()
    rooms = con.execute("""
      select area_name_en, coalesce(nullif(project_name_en,''),''), coalesce(nullif(building_name_en,''),''), coalesce(nullif(rooms_en,''),'n/a'),
             count(*), round(median(try_cast(procedure_area as double)),1), round(median(try_cast(actual_worth as double))), round(median(try_cast(meter_sale_price as double))),
             sum(case when reg_type_en='Off-Plan Properties' then 1 else 0 end), cast(max(try_cast(instance_date as date)) as varchar)
      from tx where trans_group_en='Sales' and property_type_en='Unit' and area_name_en is not null group by all""").fetchall()
    usage = con.execute("""
      select area_name_en, coalesce(nullif(project_name_en,''),''), coalesce(nullif(building_name_en,''),''), coalesce(nullif(property_usage_en,''),'?'), count(*)
      from tx where trans_group_en='Sales' and property_type_en='Unit' and area_name_en is not null group by all""").fetchall()
    R = collections.defaultdict(dict); U = collections.defaultdict(dict)
    for a, p, b, r, c, m, aed, aedsqm, offp, last in rooms: R[(a, p, b)][r] = {"n": c, "median_sqm": m, "median_aed": aed, "median_aed_sqm": aedsqm, "offplan": offp, "last": last}
    for a, p, b, u, c in usage: U[(a, p, b)][u] = c
    out = []
    for a, p, m, b, sales, f, l, msq, maed, metro, mall, lm in hdr:
        out.append({"area": a, "project": p, "master": m, "building": b, "sales": sales, "first": f, "last": l, "median_sqm": msq, "median_aed_sqm": maed, "metro": metro, "mall": mall, "landmark": lm,
                    "by_rooms": R.get((a, p, b), {}), "usage": U.get((a, p, b), {})})
    json.dump({"generated": time.strftime("%Y-%m-%d"), "source": "DLD transactions export 2026-09-04 (sales of units, >=3 sales per building)", "rows": n, "buildings": out}, open(os.path.join(OUT, "tx_buildings.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"buildings with >=3 unit sales: {len(out):,}  (named buildings: {sum(1 for x in out if x['building']):,})")
    per = collections.Counter()
    for area, slugs in DLD_AREA.items():
      for slug in slugs:
        sub = [x for x in out if x["area"] == area]
        prev = json.load(open(os.path.join(OUT, f"tx_buildings_{slug}.json"), encoding="utf-8"))["buildings"] if slug == "jltsouth" and os.path.exists(os.path.join(OUT, f"tx_buildings_{slug}.json")) else []
        json.dump({"district": slug, "area": area, "buildings": sub + prev}, open(os.path.join(OUT, f"tx_buildings_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        per[slug] = len(sub)
        print(f"  {slug:<24} {area:<26} buildings {len(sub):>5}  named {sum(1 for x in sub if x['building']):>5}  sales {sum(x['sales'] for x in sub):>7,}")


if __name__ == "__main__":
    main()
