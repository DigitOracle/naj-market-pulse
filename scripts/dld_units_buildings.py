"""The digital thread through the Dubai Land Department exports, building by building.

units (2.38 M registered units)  --parent_property_id-->  buildings (property_id: name = project_name_en, area, parcel, land, flats/offices/shops,
floors, car parks, lifts)  --project_name_en / building_name_en-->  transactions (sold by type, prices)  --project_name_en-->  Ejari rent contracts.
So for every registered building in the modelled districts this writes the true unit mix: units by rooms type, median size, the floors each
type sits on (min-max and count of levels), parking allocation, freehold flag - the "N units across M asset classes" card, from the register.

Output data/dld/units_buildings_<slug>.json  {"district","area","source","buildings":[{property_id, name, project, master, parcel, land, bno,
       units, floors_min, floors_max, levels, flats, offices, shops, floors, car_parks, elevators, pools, freehold,
       by_rooms:{type:{n, median_sqm, floors_min, floors_max, levels}}, parking:{allocated, none}}]}
Usage: python scripts/dld_units_buildings.py
"""
import duckdb, glob, json, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld"); os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
from dld_rent_buildings import DLD_AREA  # noqa: E402
UNITS = sorted(f for f in glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\units_2026-09-04_*.csv") if "(1)" not in f)
BLD = os.path.join(OUT, "buildings_2026-09-04.csv")
TYPE = {"Studio": "Studio", "1 B/R": "1 B/R", "2 B/R": "2 B/R", "3 B/R": "3 B/R", "4 B/R": "4 B/R", "5 B/R": "5 B/R", "6 B/R": "6 B/R", "PENTHOUSE": "PENTHOUSE", "Office": "Office", "Shop": "Shop", "Single Room": "Room"}


def main():
    t = time.time(); con = duckdb.connect()
    areas = ",".join("'" + a.replace("'", "''") + "'" for a in DLD_AREA)
    files = ",".join("'" + f.replace("\\", "/") + "'" for f in UNITS)
    con.execute(f"create table u as select * from read_csv_auto([{files}], sample_size=50000, all_varchar=true, union_by_name=true) where area_name_en in ({areas})")
    con.execute(f"create table b as select * from read_csv_auto('{BLD.replace(chr(92), '/')}', sample_size=50000, all_varchar=true) where area_name_en in ({areas})")
    LAND = r"C:\Dev\naj-market-pulse\data\raw_downloads\land_registry_2026-09-04_17-30-03_0001.csv"
    con.execute(f"create table l as select * from read_csv_auto('{LAND.replace(chr(92), '/')}', sample_size=50000, all_varchar=true) where area_name_en in ({areas})")
    n = con.execute("select count(*) from u").fetchone()[0]; print(f"units in modelled districts: {n:,} ({time.time()-t:.0f}s) from {len(UNITS)} files")
    # the plot: buildings.parent_property_id = land.property_id (and units.grandparent_property_id = the same plot). Master project, community
    # (munc_zip_code) and plot number (munc_number) live on the plot; parcel_id = community * 10000 + plot number, proven on every row.
    plots = {r[0]: {"plot_property_id": r[0], "plot_parcel": r[1], "plot_land_number": r[2], "community": r[3], "plot_no": r[4], "master": r[5], "plot_area_sqm": float(r[6]) if r[6] else None,
                    "plot_type": r[7], "plot_sub_type": r[8], "plot_freehold": r[9], "master_project_id": r[10], "buildings_on_plot": r[11]}
             for r in con.execute("""select l.property_id, l.parcel_id, l.land_number, l.munc_zip_code, l.munc_number, l.master_project_en, l.actual_area, l.land_type_en, l.property_sub_type_en,
                                            l.is_free_hold, l.master_project_id, (select count(*) from b where b.parent_property_id = l.property_id) from l""").fetchall()}
    bplot = dict(con.execute("select property_id, parent_property_id from b").fetchall())
    uplot = dict(con.execute("select parent_property_id, any_value(grandparent_property_id) from u group by 1").fetchall())
    hdr = con.execute("""
      select u.parent_property_id, any_value(u.area_name_en), coalesce(any_value(b.project_name_en), any_value(u.project_name_en)), any_value(u.master_project_en),
             any_value(coalesce(b.parcel_id, u.parcel_id)), any_value(coalesce(b.land_number, u.land_number)), any_value(coalesce(b.building_number, u.building_number)),
             count(*), min(try_cast(u.floor as double)), max(try_cast(u.floor as double)), count(distinct u.floor),
             any_value(b.flats), any_value(b.offices), any_value(b.shops), any_value(b.floors), any_value(b.car_parks), any_value(b.elevators), any_value(b.swimming_pools), any_value(coalesce(b.is_free_hold, u.is_free_hold)),
             sum(case when u.unit_parking_number is not null and u.unit_parking_number <> '' then 1 else 0 end), any_value(b.property_id) is not null
      from u left join b on u.parent_property_id = b.property_id group by 1""").fetchall()
    bt = con.execute("""select parent_property_id, rooms_en, count(*), round(median(try_cast(actual_area as double)),1), min(try_cast(floor as double)), max(try_cast(floor as double)), count(distinct floor)
                        from u group by 1,2""").fetchall()
    BR = {}
    for pid, ty, c, sqm, f0, f1, lv in bt: BR.setdefault(pid, {})[TYPE.get(ty or "", ty or "Unit")] = {"n": c, "median_sqm": sqm, "floors_min": f0, "floors_max": f1, "levels": lv}
    per = {s: [] for v in DLD_AREA.values() for s in v}
    for pid, area, proj, master, parcel, land, bno, c, f0, f1, lv, fl, of, sh, floors, cp, el, sp, fh, park, inb in hdr:
        rec = {"property_id": pid, "name": (proj or "").strip() or None, "project": (proj or "").strip() or None, "master": master, "parcel": parcel, "land": land, "bno": bno, "units": c,
               "floors_min": f0, "floors_max": f1, "levels": lv, "flats": int(float(fl or 0)), "offices": int(float(of or 0)), "shops": int(float(sh or 0)), "floors": int(float(floors or 0)),
               "car_parks": int(float(cp or 0)), "elevators": int(float(el or 0)), "pools": int(float(sp or 0)), "freehold": fh, "in_buildings_table": bool(inb),
               "by_rooms": BR.get(pid, {}), "parking": {"allocated": park, "none": c - park}}
        pl = plots.get(bplot.get(pid) or uplot.get(pid))
        if pl: rec.update(pl)
        elif parcel:
            try: rec["community"], rec["plot_no"] = str(int(float(parcel)) // 10000), str(int(float(parcel)) % 10000)
            except Exception: pass
        for _s in DLD_AREA[area]: per[_s].append(rec)
    for slug, rows in per.items():
        rows.sort(key=lambda r: -r["units"]); area = next(a for a, v in DLD_AREA.items() if slug in v)
        json.dump({"district": slug, "area": area, "generated": time.strftime("%Y-%m-%d"), "source": "DLD units + buildings exports 2026-09-04 (units.parent_property_id = buildings.property_id)", "buildings": rows},
                  open(os.path.join(OUT, f"units_buildings_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        named = sum(1 for r in rows if r["name"]); big = sum(1 for r in rows if r["units"] >= 50)
        print(f"  {slug:<24} buildings {len(rows):>5} | named {named:>5} | >=50 units {big:>4} | units {sum(r['units'] for r in rows):>7,} | top: {rows[0]['name']} {rows[0]['units']}")
    print(f"done {time.time()-t:.0f}s")


if __name__ == "__main__":
    main()
