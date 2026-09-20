"""build_parcel_buildings.py -- per-parcel building lists for a district, so register records bind to footprints by PARCEL, not by name.

Asked for by the twin session (20 Sep 2026): name binding put Enara By Omniyat's floors on The Binary By Omniyat's footprint.
A parcel key is the DM plot reference every register shares, so it survives renames, marketing names and Arabic transliteration.

    python scripts/build_parcel_buildings.py                       # Business Bay + DAMAC Hills (Al Hebiah Third)
    python scripts/build_parcel_buildings.py --community 346 --slug business_bay

Writes data/board/parcel_buildings_<slug>.json:
    {"community": {...}, "generated": "...", "parcels": {"<parcel_key>": [ {building_id, floors_above, basements, units,
     area_sqm, n_uses, uses, retail_podium, labour_accom, building_type, status, completion_date, typical_floors, height_m}, ... ]}}
Floor figures come from g_dm__building_floor_level_information with the same caps the floor stack uses: floor_no over 200 dropped
(13 buildings carry junk, one reads 47,880) and usages_area over 100,000 sqm ignored (129 rows, one at 3.3bn).
"""
import argparse, collections, datetime as dt, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lake import connect  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "board")
DISTRICTS = [(346, "business_bay", "Business Bay"), (676, "damac_hills", "DAMAC Hills (Al Hebiah Third)")]

SQL = """
with f as (
  select try_cast(building_id as bigint) bid, try_cast(floor_no as double) fno, floor_type_english ftype,
         usage_description_english usage, try_cast(no_of_units as double) units,
         case when try_cast(usages_area as double) between 0 and 100000 then try_cast(usages_area as double) end area
  from g_dm__building_floor_level_information),
roll as (
  select bid,
         max(case when fno <= 200 then fno end) floors_above,
         count(distinct case when ftype = 'Under Ground' then fno end) basements,
         sum(units) units, round(sum(area)) area_sqm, count(distinct usage) n_uses,
         max(case when usage in ('Commercial', 'Offices') and ftype in ('Ground', 'Mezzanine') then 1 else 0 end) retail_podium,
         max(case when usage in ('Labour Accomadation', 'Employees /Students Accommodation') then 1 else 0 end) labour_accom,
         string_agg(distinct usage, ' / ') uses
  from f group by 1)
select b.parcel_key, b.building_id, r.floors_above, r.basements, r.units, r.area_sqm, r.n_uses, r.uses,
       r.retail_podium, r.labour_accom, b.building_type, b.status, cast(b.completion_date as varchar), b.typical_floors, b.height_m
from lk_dm_buildings b left join roll r on r.bid = b.building_id
where b.comm_num = %d and b.parcel_key is not null
order by b.parcel_key, r.floors_above desc nulls last
"""
COLS = ("building_id", "floors_above", "basements", "units", "area_sqm", "n_uses", "uses", "retail_podium", "labour_accom",
        "building_type", "status", "completion_date", "typical_floors", "height_m")


def build(con, comm, slug, label):
    rows = con.execute(SQL % comm).fetchall()
    parcels = collections.defaultdict(list)
    for r in rows:
        parcels[r[0]].append({k: (float(v) if isinstance(v, (int, float)) and k in ("units", "area_sqm", "floors_above",
                                                                                    "typical_floors", "height_m") and v is not None else v)
                              for k, v in zip(COLS, r[1:])})
    doc = {"community": {"comm_num": comm, "name": label}, "generated": dt.datetime.now().isoformat(timespec="seconds"),
           "buildings": len(rows), "parcels_with_buildings": len(parcels),
           "source": "lk_dm_buildings (DM building register) + g_dm__building_floor_level_information, lake snapshot",
           "parcels": {k: v for k, v in sorted(parcels.items())}}
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "parcel_buildings_%s.json" % slug)
    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    multi = sum(1 for v in parcels.values() if len(v) > 1)
    print("%-34s %6d buildings on %5d parcels (%d parcels hold more than one) -> %s"
          % (label, len(rows), len(parcels), multi, os.path.relpath(p, ROOT)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--community", type=int); ap.add_argument("--slug"); ap.add_argument("--label")
    a = ap.parse_args()
    con = connect()
    todo = [(a.community, a.slug or str(a.community), a.label or str(a.community))] if a.community else DISTRICTS
    for comm, slug, label in todo:
        build(con, comm, slug, label)


if __name__ == "__main__":
    main()
