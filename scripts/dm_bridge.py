"""The bridge from the Land Department register to Dubai Municipality's building records - the same parcel.

DLD parcel_id == DM parcel_id == community_no * 10000 + plot number (proven on every row of the units table). So for every DLD
building in the modelled districts:
  DLD buildings.parcel_id  ->  DM building_summary_information (one row per permit revision on the plot: New / Permit Delivered /
  Completed / Expired; floors written as "6B+ G +94 +1P +1R", lifts, indoor parking, usages, completion date, building_id, permit_no,
  project_no)  ->  DM building_floor_level_information by building_id (units on each floor, usage of each floor).
The best DM record per parcel is the delivered / completed one, else the newest with the most floors. A parcel with several DLD
buildings (a master plot) gets the DM rows split by nothing - we record `dm_buildings_on_parcel` and let the card say so.

Output data/dld/dm_buildings_<slug>.json  {"district", "source", "buildings": {"<dld property_id>": {dm_building_id, dm_status, floors_label,
       basements, floors_above, podium, roof, lifts, indoor_parking, outdoor_parking, usages, completed, permitted, height_m, total_area,
       plot_area, buildings_on_plot, dm_buildings_on_parcel, permit_no, project_no, green, floors: [{floor, type, units, usage, area}], units_by_usage: {...}}}}
Usage: python scripts/dm_bridge.py
"""
import duckdb, glob, json, os, re, sys, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from dld_rent_buildings import DLD_AREA  # noqa: E402
OUT = os.path.join(ROOT, "data", "dld")
BS = os.path.join(OUT, "dm_building_summary_2026-08-31.csv"); BLD = os.path.join(OUT, "buildings_2026-09-04.csv")
FL = sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\building_floor_level_information_2026-08-31_*.csv"))
STATUS_RANK = {"Completed": 0, "Permit Delivered": 1, "Delivered": 1, "New": 2, "Under Construction": 2, "Expired": 5, "Cancelled": 6, "Demolished": 7}


def parse_floors(label):
    """'6B+  G  +94  +1P  +1R' -> basements 6, ground True, floors_above 94, podium 1, roof 1"""
    s = (label or "").upper().replace(" ", "")
    d = {"basements": 0, "ground": "G" in s, "floors_above": 0, "podium": 0, "roof": 0, "mezzanine": 0}
    for n, k in re.findall(r"(\d+)([BPRM]?)", s):
        n = int(n)
        if k == "B": d["basements"] += n
        elif k == "P": d["podium"] += n
        elif k == "R": d["roof"] += n
        elif k == "M": d["mezzanine"] += n
        else: d["floors_above"] += n
    return d


def main():
    t = time.time(); con = duckdb.connect()
    areas = ",".join("'" + a.replace("'", "''") + "'" for a in DLD_AREA)
    con.execute(f"create table b as select property_id, parcel_id, project_name_en, area_name_en, flats, offices, shops, floors from read_csv_auto('{BLD.replace(chr(92), '/')}', sample_size=50000, all_varchar=true) where area_name_en in ({areas}) and parcel_id is not null")
    con.execute(f"create table bs as select * from read_csv_auto('{BS.replace(chr(92), '/')}', sample_size=50000, all_varchar=true) where try_cast(parcel_id as bigint) in (select distinct try_cast(parcel_id as bigint) from b)")
    nbs = con.execute("select count(*) from bs").fetchone()[0]; print(f"DM building rows on our parcels: {nbs:,} ({time.time()-t:.0f}s)")
    files = ",".join("'" + f.replace("\\", "/") + "'" for f in FL)
    con.execute(f"create table fl as select * from read_csv_auto([{files}], sample_size=50000, all_varchar=true, union_by_name=true) where try_cast(building_id as bigint) in (select distinct try_cast(building_id as bigint) from bs)")
    nfl = con.execute("select count(*) from fl").fetchone()[0]; print(f"floor-level rows for those buildings: {nfl:,} ({time.time()-t:.0f}s)")
    # DM rows per parcel
    dm_by_parcel = collections.defaultdict(list)
    cols = [d[0] for d in con.execute("select * from bs limit 0").description]
    for row in con.execute("select * from bs").fetchall():
        r = dict(zip(cols, row)); dm_by_parcel[int(float(r["parcel_id"]))].append(r)
    # floors per DM building
    floors = collections.defaultdict(list)
    for bid, fno, ftype, units, usage, area in con.execute("select building_id, floor_no, floor_type_english, no_of_units, usage_description_english, usages_area from fl").fetchall():
        floors[int(float(bid))].append({"floor": int(float(fno)) if fno not in (None, "") else None, "type": (ftype or "").strip(), "units": int(float(units or 0)), "usage": (usage or "").strip(), "area": float(area) if area not in (None, "") else None})
    def best(rows):
        def key(r):
            fl_ = parse_floors(r.get("building_floor_height"))["floors_above"]
            return (STATUS_RANK.get((r.get("building_status_english") or "").strip(), 3), -fl_, -(float(r.get("typical_floors_count") or 0)), (r.get("building_completion_date") or ""))
        return sorted(rows, key=key)[0]
    per = {s: {} for v in DLD_AREA.values() for s in v}; hit = tot = 0
    for pid, parcel, name, area, flats, offices, shops, dfl in con.execute("select * from b").fetchall():
        tot += 1; rows = dm_by_parcel.get(int(float(parcel)))
        if not rows: continue
        r = best(rows); hit += 1; pf = parse_floors(r.get("building_floor_height")); bid = int(float(r["building_id"]))
        fls = sorted(floors.get(bid, []), key=lambda x: (x["floor"] if x["floor"] is not None else -99))
        ubu = collections.Counter(); lvl = collections.defaultdict(set)
        for f in fls:
            if f["units"]: ubu[f["usage"] or "unspecified"] += f["units"]
            if f["floor"] is not None and f["units"]: lvl[f["usage"] or "unspecified"].add(f["floor"])
        rec = {"dm_building_id": bid, "dm_status": (r.get("building_status_english") or "").strip() or None, "floors_label": (r.get("building_floor_height") or "").strip() or None,
               "basements": pf["basements"], "floors_above": pf["floors_above"] or (int(float(r.get("typical_floors_count") or 0)) or None), "podium": pf["podium"], "roof": pf["roof"],
               "lifts": int(float(r.get("no_of_lifts") or 0)) or None, "indoor_parking": int(float(r.get("indoor_car_parking") or 0)) or None, "outdoor_parking": int(float(r.get("outdoor_car_parking") or 0)) or None,
               "usages": [u.strip() for u in (r.get("building_usages_english") or "").split("+") if u.strip()], "building_type": (r.get("building_type_english") or "").strip() or None,
               "completed": r.get("building_completion_date"), "permitted": r.get("building_permitted_date"), "construction_year": int(float(r["building_construction_year"])) if r.get("building_construction_year") else None,
               "height_m": float(r["building_height"]) if r.get("building_height") and float(r["building_height"]) > 0 else None, "total_area_sqm": float(r["building_total_area"]) if r.get("building_total_area") else None,
               "plot_area_sqm": float(r["plot_area"]) if r.get("plot_area") else None, "buildings_on_plot": int(float(r.get("no_of_buildings_on_plot") or 0)) or None, "dm_buildings_on_parcel": len(rows),
               "permit_no": r.get("permit_no"), "project_no": int(float(r["project_no"])) if r.get("project_no") else None, "green": r.get("is_green_building"), "community_no": int(float(r["community_no"])) if r.get("community_no") else None,
               "floors": fls[:140], "units_by_usage": dict(ubu), "levels_by_usage": {k: [min(v), max(v), len(v)] for k, v in lvl.items()},
               "dld": {"name": name, "flats": int(float(flats or 0)), "offices": int(float(offices or 0)), "shops": int(float(shops or 0)), "floors": int(float(dfl or 0))}}
        for _s in DLD_AREA[area]: per[_s][pid] = rec
    for slug, d in per.items():
        json.dump({"district": slug, "generated": time.strftime("%Y-%m-%d"), "source": "DM building_summary_information + building_floor_level_information (31 Aug 2026) via DLD parcel_id == DM parcel_id", "buildings": d},
                  open(os.path.join(OUT, f"dm_buildings_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        wf = sum(1 for r in d.values() if r["floors"]); print(f"  {slug:<24} DLD buildings bridged {len(d):>5} | with floor-level detail {wf:>5}")
    print(f"TOTAL bridged {hit:,} of {tot:,} DLD buildings ({time.time()-t:.0f}s)")


if __name__ == "__main__":
    main()
