"""build_project_types.py -- what each DLD project is made of: apartments, townhouses, villas, by bedroom count (1 Oct 2026).

Why. The brief needs TOWNHOUSE as a property type, and Ejari files townhouses as "Villa": the only way to tell a townhouse
lease from a villa lease is the project it sits in. This keys the answer per dld_project_number from the registers that do
carry a type: the units register (property_sub_type_en, rooms_en), the DLD projects register (classification; no_of_villas;
"townhouse" in the description), and the land register's property_sub_type for villa plots.

Output: data/dld/project_types.json  {as_of, source, type_rule, fields, rows:[{project_number, project_name, community, area,
type, bedrooms, units}], projects:{<project_number>: {name, community, single_type, types:{...}, townhouse_in_description,
classification}}} and a printed share of single-type vs mixed projects. One short lake read; nothing written to the lake.
    python scripts/build_project_types.py
"""
import json, os, sys, time, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld", "project_types.json")
import lake

TYPE_SQL = """case when lower(coalesce(property_sub_type_en, '')) like '%town%' then 'townhouse'
                   when lower(coalesce(property_sub_type_en, '')) like '%villa%' then 'villa'
                   when lower(coalesce(property_sub_type_en, '')) like '%flat%' or lower(coalesce(property_sub_type_en, '')) like '%apartment%'
                        or lower(coalesce(property_sub_type_en, '')) like '%studio%' or lower(coalesce(property_sub_type_en, '')) like '%penthouse%'
                        or lower(coalesce(property_sub_type_en, '')) like '%duplex%' then 'apartment'
                   when lower(coalesce(property_type_en, '')) like '%villa%' then 'villa'
                   when lower(coalesce(property_type_en, '')) like '%unit%' or lower(coalesce(property_type_en, '')) like '%flat%' then 'apartment'
                   else 'other' end"""


def main():
    t0 = time.time()
    con = lake.connect(read_only=True)
    subtypes = con.execute("select property_type_en, property_sub_type_en, count(*) from g_dld__units group by 1, 2 order by 3 desc").fetchall()
    rows = con.execute(f"""
        select u.project_name_en, try_cast(pn.project_number as bigint) project_number, u.area_name_en, u.master_project_en,
               {TYPE_SQL} unit_type, u.rooms_en, count(*) units
        from g_dld__units u
        left join (select distinct project_id, project_number from lk_project_numbers where project_number is not null) pn on pn.project_id = u.project_id
        where u.project_name_en is not null
        group by all""").fetchall()
    land = con.execute("""select project_name_en, property_sub_type_en, count(*) from g_dld__land_registry
                          where project_name_en is not null and lower(coalesce(property_sub_type_en,'')) like '%villa%' group by all""").fetchall()
    con.close()                                                   # lake open for seconds only
    projects = json.load(open(os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_projects-open-api.json"), encoding="utf-8"))["results"]
    preg = {}
    for p in projects:
        pn = p.get("project_number")
        try: pn = int(float(pn))
        except (TypeError, ValueError): continue
        desc = (p.get("project_description_en") or "").lower()
        preg[pn] = {"classification_ar": p.get("project_classification_ar"), "no_of_villas": p.get("no_of_villas"), "no_of_units": p.get("no_of_units"),
                    "townhouse_in_description": "town" in desc, "name_en": p.get("project_name")}
    out_rows, by_project = [], defaultdict(lambda: {"types": defaultdict(int), "name": None, "community": None, "area": None})
    for name, pn, area, master, typ, rooms, n in rows:
        beds = {"Studio": "studio", "1 B/R": "1", "2 B/R": "2", "3 B/R": "3", "4 B/R": "4", "5 B/R": "5", "6 B/R": "6+", "7 B/R": "6+"}.get(rooms, None)
        out_rows.append({"project_number": pn, "project_name": name, "community": master, "area": area, "type": typ, "bedrooms": beds, "units": n})
        key = pn if pn is not None else "name:" + re.sub(r"\s+", " ", name.strip())
        bp = by_project[key]; bp["types"][typ] += n; bp["name"] = name; bp["community"] = master; bp["area"] = area
    proj_out, single, mixed = {}, 0, 0
    for key, bp in by_project.items():
        resid = {t: n for t, n in bp["types"].items() if t != "other"}
        is_single = len(resid) == 1
        single += is_single; mixed += (not is_single and len(resid) > 1)
        reg = preg.get(key) if isinstance(key, int) else None
        proj_out[str(key)] = {"name": bp["name"], "community": bp["community"], "area": bp["area"], "single_type": (next(iter(resid)) if is_single else None),
                              "types": dict(bp["types"]), "townhouse_in_description": reg["townhouse_in_description"] if reg else None,
                              "classification_ar": reg["classification_ar"] if reg else None, "no_of_villas": reg["no_of_villas"] if reg else None}
    # villa-plot land (villas registered as land parcels, not units) adds projects the units register never sees
    land_only = 0
    for name, sub, n in land:
        key = "land:" + re.sub(r"\s+", " ", name.strip())
        if not any(v["name"] == name for v in proj_out.values()):
            land_only += 1
    json.dump({"as_of": time.strftime("%Y-%m-%d"), "source": "g_dld__units (property_sub_type_en, rooms_en), lk_project_numbers, DLD projects register (classification, description), g_dld__land_registry villa plots",
               "type_rule": "townhouse if the unit's sub type says townhouse; villa if it says villa; apartment for flat/studio/penthouse/duplex; else other. Ejari itself has no townhouse type - it files them as Villa, so the project is the key.",
               "fields": ["project_number", "project_name", "community", "area", "type", "bedrooms", "units"],
               "rows": out_rows, "projects": proj_out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    th_units = sum(r["units"] for r in out_rows if r["type"] == "townhouse")
    print("units register sub types (top 15):", subtypes[:15])
    print("%d rows, %d projects: single-type %d, mixed %d; townhouse units %d; projects with a townhouse description %d; villa-plot-only project names %d; %.0fs" % (
        len(out_rows), len(by_project), single, mixed, th_units, sum(1 for v in preg.values() if v["townhouse_in_description"]), land_only, time.time() - t0))
    print("written", OUT)


if __name__ == "__main__":
    main()
