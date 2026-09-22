"""build_project_index.py -- every registered project name in Dubai, with the ids it resolves to, in ONE file.

Why (22 Sep 2026). The per-district cuts only exist for the 42 districts on the twin's rail, but lk_key_bridge covers 219 DLD
areas: 112,468 of 257,039 properties (44%) sit in an area with no per-district file. To a name lookup an absent DISTRICT and an
absent PROJECT look identical, which is why the question-bank session misattributed its unbound plans twice - SOBHA ONE is in
Ras Al Khor Industrial First, not on the rail, so no key_bridge_<slug>.json could ever contain it.

This indexes the whole register instead, so district membership is a property of the RESULT rather than a filter on the input.
Names come from two places, because the DLD project register itself has no English name column at all (Arabic only):
  * project_name_en on the DLD building register, via lk_key_bridge
  * project_name_en on the units register, which names a project on far more rows (Sobha One: 7 properties, 3,057 units)

    python scripts/build_project_index.py      ->  data/board/project_index.json

Each entry: the register's exact string, its project ids, how many properties and units carry it, the areas and communities it
appears in, and up to PROPERTY_CAP property ids and parcel keys to join on. A name in several areas keeps them all - a project
name is not unique in Dubai and pretending otherwise is how the wrong building ends up on screen.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lake import connect  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "board", "project_index.json")
PROPERTY_CAP = 400          # a villa community can carry hundreds; the count is exact even where the id list is capped

# 22 Sep 2026: names are matched on a NORMALISED key - trimmed, inner whitespace collapsed, upper-cased - because the registers
# disagree on spacing. The units register writes "Binghatti Haven " with a trailing space and the building register writes
# "Binghatti Haven"; joining on upper() alone left the building entry showing 0 units AND minted a phantom "units-only" entry
# for the same project, which read as evidence of selling ahead of registration for a project that is plainly registered. The
# exact register strings are kept in name_variants so nothing is lost.
NORM = "upper(regexp_replace(trim({c}), '\s+', ' ', 'g'))"

SQL = """
with bld as (
    select {n} nkey, project_name_en pname, dld_project_id, area_name_en, comm_num, property_id, parcel_key
    from lk_key_bridge where project_name_en is not null and trim(project_name_en) <> ''),
 un as (
    select {u} nkey, count(*) units
    from g_dld__units where project_name_en is not null and trim(project_name_en) <> '' group by 1)
select b.nkey,
       mode(b.pname)                                   pname,
       list(distinct b.pname)                          name_variants,
       count(*)                                        properties,
       count(distinct b.dld_project_id)                project_ids,
       list(distinct b.dld_project_id)                 project_id_list,
       list(distinct b.area_name_en)                   areas,
       list(distinct b.comm_num)                       comm_nums,
       list(b.property_id)[1:{cap}]                    property_ids,
       list(distinct b.parcel_key)[1:{cap}]            parcel_keys,
       coalesce(max(u.units), 0)                       units
from bld b left join un u on u.nkey = b.nkey
group by 1 order by properties desc"""
UNITS_ONLY = """
select mode(project_name_en) pname, count(*) units, list(distinct area_name_en) areas,
       list(distinct cast(cast(project_id as bigint) as varchar)) ids
from g_dld__units u
where project_name_en is not null and trim(project_name_en) <> ''
  and {u} not in (select distinct {n} from lk_key_bridge where project_name_en is not null and trim(project_name_en) <> '')
group by {u} order by units desc"""


def main():
    con = connect()
    sql = (SQL.replace("{cap}", str(PROPERTY_CAP))
              .replace("{n}", NORM.format(c="project_name_en")).replace("{u}", NORM.format(c="project_name_en")))
    rows = con.execute(sql).fetchall()
    cols = ("nkey", "name", "name_variants", "properties", "project_ids", "project_id_list", "areas", "comm_nums", "property_ids", "parcel_keys", "units")
    entries = []
    for r in rows:
        d = dict(zip(cols, r))
        d.pop("nkey", None)
        d["name_variants"] = sorted({x for x in (d["name_variants"] or []) if x})
        d["project_id_list"] = [x for x in (d["project_id_list"] or []) if x]
        d["areas"] = sorted(x for x in (d["areas"] or []) if x)
        d["comm_nums"] = sorted(x for x in (d["comm_nums"] or []) if x is not None)
        d["parcel_keys"] = [x for x in (d["parcel_keys"] or []) if x]
        d["property_ids_capped"] = len(d["property_ids"] or []) < d["properties"]
        entries.append(d)
    # names carried only by the units register, which the building register never issued a property for
    extra = con.execute(UNITS_ONLY.replace("{n}", NORM.format(c="project_name_en"))
                                   .replace("{u}", NORM.format(c="project_name_en"))).fetchall()
    for nm, units, areas, ids in extra:
        entries.append({"name": nm, "name_variants": [nm], "properties": 0, "project_ids": len([i for i in ids if i]),
                        "project_id_list": [i for i in ids if i], "areas": sorted(a for a in areas if a),
                        "comm_nums": [], "property_ids": [], "parcel_keys": [], "units": units,
                        "property_ids_capped": False,
                        "note": "named only by the units register: the building register has issued no property row for it"})
    doc = {"generated_from": "lk_key_bridge (DLD building register) + g_dld__units",
           "projects": len(entries),
           "from_building_register": sum(1 for e in entries if e["properties"]),
           "units_register_only": sum(1 for e in entries if not e["properties"]),
           "areas_covered": len({a for e in entries for a in e["areas"]}),
           "property_cap": PROPERTY_CAP,
           "note": "Every registered project name in Dubai, not only the districts on the twin's rail - 44 percent of properties sit "
                   "in an area with no per-district cut, and to a name lookup an absent district and an absent project look "
                   "identical. A name appearing in several areas keeps them all: project names are not unique in Dubai. "
                   "properties is exact; property_ids is capped at " + str(PROPERTY_CAP) + " per name, and property_ids_capped says when it was. "
                   "An entry with properties = 0 is named by the units register only - the building register has issued no "
                   "property for it, which is what selling ahead of registration looks like from here.",
           "index": entries}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, io.open(OUT + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(OUT + ".tmp", OUT)
    print("%s projects (%s from the building register, %s units-register-only) across %d areas -> %s"
          % (format(doc["projects"], ","), format(doc["from_building_register"], ","),
             format(doc["units_register_only"], ","), doc["areas_covered"], os.path.relpath(OUT, ROOT)))
    print("   size %.1f MB" % (os.path.getsize(OUT) / 1048576))


if __name__ == "__main__":
    main()
