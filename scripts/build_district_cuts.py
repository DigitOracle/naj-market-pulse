"""build_district_cuts.py -- the seven per-district register cuts the building page reads, for every district on the twin's rail.

Business Bay and DAMAC Hills were cut by hand on 20 Sep 2026; the roll-out to all of Dubai needs the same seven for 38 more, so
this does every district in one pass per dataset instead of seven files at a time. Each cut is written atomically to
data/board/<cut>_<slug>.json - replaced in place at the same path, so a reader re-reads by path and never sees a half-file.

  names_<slug>             building_id -> name, by ID join only: land registry parcel -> project_name_en, units parent -> project_name_en
  projects_<slug>          DLD project register (escrow, % complete, dates) + English names from units + building_to_project
  land_registry_<slug>     plots: land_number, parcel_id, area, land type, freehold, project
  amenities_<slug>         KHDA schools (curriculum, rating) and active DHA facilities within 5 km of the district centre
  makani_<slug>            DM Makani entrance points with lon/lat and the twin duid
  permits_<slug>           DM building permits on the district's parcels
  dld_buildings_<slug>     DLD building register: property_id + parcel_id, the key bridge between the two spines
  project_team_<slug>      who designed it and who built it, by parcel (DM contractor + consultant registers)
  project_buildings_<slug> DM project -> building, with construction stage and declared cost
  usages_<slug>            DM building usages per building_id - the independent second opinion on what a building is for
  parcel_buildings_<slug>  buildings per parcel with floors, basements, units, floor area, use mix

Slugs are the twin's own rail slugs (businessbay, damachills, dubaimarina ...), taken from DLD_AREA in dld_rent_buildings.py so
rent_projects_<slug>.json and these files share one convention. A district whose DLD area has no DM community (Palm Deira, the two
Al Yelayiss) still gets the register-side cuts; the municipality-side ones are skipped and the reason is recorded in the summary.

    python scripts/build_district_cuts.py                    # all districts, all cuts
    python scripts/build_district_cuts.py --slug dubaimarina --only names,projects
"""
import argparse, collections, datetime as dt, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lake import connect  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
LAND_FILE = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_land_registry-open-api.json")
RADIUS_KM = 5.0
# DM community per DLD area, resolved 21 Sep 2026 against lk_dm_buildings.community_name; None = the area has no DM community
# (Palm Deira is reclaimed land with no DM buildings; the Al Yelayiss pair sit outside the DM building register).
COMM = {
    "Marsa Dubai": 392, "Business Bay": 346, "Burj Khalifa": 345, "Al Wasl": 343, "Al Barsha South Fourth": 681,
    "Al Barsha South Fifth": 684, "Al Hebiah First": 674, "Al Jadaf": 326, "Al Thanyah Fifth": 393, "Al Thanyah Third": 388,
    "Al Hebiah Third": 676, "Hadaeq Sheikh Mohammed Bin Rashid": 631, "Saih Shuaib 3": 532, "Al Hebiah Fourth": 682,
    "Al Hebiah Second": 675, "Wadi Al Safa 3": 645, "Al Merkadh": 347, "Nadd Hessa": 626, "Al Hebiah Fifth": 683,
    # by parcel, not by name: 414 is a name match that holds none of Al Khairan First's plots, 415 holds them
    "Al Khairan First": 415,
    "Al Satwa": 334, "Al Yufrah 1": 915, "Dubai Investment Park First": 598,
    "Dubai Investment Park Second": 597, "Jabal Ali First": 591, "Jabal Ali Industrial Second": 518, "Madinat Al Mataar": 521,
    "Madinat Hind 4": 914, "Wadi Al Safa 4": 646, "Wadi Al Safa 5": 648,
    "Palm Jumeirah": 381,                      # NAKHLAT JUMEIRA / JUMEIRA PALM
    "Nad Al Shiba First": 618,                 # NADD AL SHIBA FIRST
    "Al Barshaa South Third": 673, "Al Barshaa South Second": 672,
    "Madinat Dubai Almelaheyah": 321,          # MADINAT DUBAI AL MELAHEYAH
    "Me'Aisem First": 685,                     # ME`AISEM FIRST
    "Palm Deira": None, "Al Yelayiss 1": None, "Al Yelayiss 2": None,
    # 21 Sep 2026: the twin added Bu Kadra and Liwan 1. Both checked BY PARCEL, not by name - the land registry's plots for
    # Bukadra land in DM community 611 (178 of 226) and for Wadi Al Safa 2 in 643 (1,064 of 2,190), and the name match agrees.
    "Bukadra": 611, "Wadi Al Safa 2": 643,
}
ALIAS = {"businessbay": "business_bay", "damachills": "damac_hills"}   # the two hand-cut districts keep their original filenames too


def districts():
    src = io.open(os.path.join(HERE, "dld_rent_buildings.py"), encoding="utf-8").read()
    block = src[src.index("DLD_AREA = {"):]
    area_map = eval(block[block.index("{"):block.index("\n}") + 2])
    out = []
    for area, slugs in area_map.items():
        for sl in slugs:
            out.append({"area": area, "slug": sl, "comm": COMM.get(area)})
    return out


def write(cut, slug, doc):
    os.makedirs(BOARD, exist_ok=True)
    for name in [slug] + ([ALIAS[slug]] if slug in ALIAS else []):
        p = os.path.join(BOARD, "%s_%s.json" % (cut, name))
        tmp = p + ".tmp"
        json.dump(doc, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, p)                                   # atomic: a reader never sees a half-written file
    return len(doc.get(list(doc)[-1]) or []) if isinstance(doc.get(list(doc)[-1]), list) else 0


def idstr(v):
    """An id as a plain string. DuckDB hands these back as floats where the source column is double, and a cut that writes
    "28943491.0" will never meet a reader holding 28943491 - that cost 38 districts their whole construction section on
    21 Sep 2026, because the two hand-made districts happened to carry integers and nothing else did."""
    if v is None:
        return None
    s = str(v)
    return s[:-2] if s.endswith(".0") else s


# --------------------------------------------------------------------------------------------------- the seven cuts
FLOORS = """
with f as (
  select try_cast(building_id as bigint) bid, try_cast(floor_no as double) fno, floor_type_english ftype,
         usage_description_english usage, try_cast(no_of_units as double) units,
         case when try_cast(usages_area as double) between 0 and 100000 then try_cast(usages_area as double) end area
  from g_dm__building_floor_level_information)
select bid, max(case when fno <= 200 then fno end) floors_above,
       count(distinct case when ftype = 'Under Ground' then fno end) basements,
       sum(units) units, round(sum(area)) area_sqm, count(distinct usage) n_uses,
       max(case when usage in ('Commercial', 'Offices') and ftype in ('Ground', 'Mezzanine') then 1 else 0 end) retail_podium,
       max(case when usage in ('Labour Accomadation', 'Employees /Students Accommodation') then 1 else 0 end) labour_accom,
       string_agg(distinct usage, ' / ') uses
from f group by 1"""


def cut_parcel_buildings(con, d):
    rows = con.execute("""select b.parcel_key, b.building_id, r.floors_above, r.basements, r.units, r.area_sqm, r.n_uses, r.uses,
                                 r.retail_podium, r.labour_accom, b.building_type, b.status, cast(b.completion_date as varchar),
                                 b.typical_floors, b.height_m
                          from lk_dm_buildings b left join (%s) r on r.bid = b.building_id
                          where b.comm_num = ? and b.parcel_key is not null
                          order by b.parcel_key, r.floors_above desc nulls last""" % FLOORS, [d["comm"]]).fetchall()
    keys = ("building_id", "floors_above", "basements", "units", "area_sqm", "n_uses", "uses", "retail_podium", "labour_accom",
            "building_type", "status", "completion_date", "typical_floors", "height_m")
    parcels = collections.defaultdict(list)
    for r in rows:
        parcels[idstr(r[0])].append({k: (idstr(v) if k == "building_id" else v) for k, v in zip(keys, r[1:])})
    return {"area": d["area"], "comm_num": d["comm"], "buildings": len(rows), "parcels_with_buildings": len(parcels),
            "note": "A parcel is not one tower: podiums, service blocks and towers share plots. Pick the building by floors_above, "
                    "building_type or units. Floor figures cap floor_no at 200 and ignore areas over 100,000 sqm.",
            "parcels": {k: v for k, v in sorted(parcels.items())}}


def cut_names(con, d, land_by_parcel):
    by_bld = dict(con.execute("""select cast(parent_property_id as varchar), any_value(project_name_en) from g_dld__units
                                 where parent_property_id is not null and project_name_en is not null group by 1""").fetchall())
    plot = dict(con.execute("""select cast(parcel_key as varchar), any_value(building_number) from lk_d_building
                               where comm_num = ? and building_number is not null group by 1""", [d["comm"]]).fetchall())
    rows = con.execute("""select building_id, cast(parcel_key as varchar), building_type, typical_floors, status
                          from lk_dm_buildings where comm_num = ?""", [d["comm"]]).fetchall()
    out, named = [], 0
    for bid, pk, btype, floors, status in rows:
        name, src = by_bld.get(str(bid)), "units_parent_property"
        if not name:
            name, src = land_by_parcel.get(pk), "land_registry_parcel"
        if name:
            named += 1
        else:
            src = None
        out.append({"building_id": idstr(bid), "parcel_key": idstr(pk), "name": name, "source": src, "building_type": btype,
                    "plot_code": plot.get(pk), "typical_floors": floors, "status": status})
    # 21 Sep 2026: the DM building register is thin in the newer freehold communities - Al Barsha South Fourth (JVC) holds 6 DM
    # buildings against 3,825 in the DLD register - so a DM-only name cut reads 0/6 there. The DLD side is added as its own array,
    # keyed by the property_id the twin's unitmix already carries, with the register's own building_number and the units register's
    # project name where a unit names it.
    dld_rows = con.execute("""select b.property_id, cast(b.parcel_key as varchar), b.building_number, b.floors, b.flats
                              from lk_d_building b where b.comm_num = ?""", [d["comm"]]).fetchall()
    dld_out = []
    for pid, pk, bnum, floors, flats in dld_rows:
        dld_out.append({"property_id": idstr(pid), "parcel_key": pk, "building_number": bnum,
                        "name": by_bld.get(str(pid)) or bnum, "source": "units_parent_property" if by_bld.get(str(pid)) else "dld_building_number",
                        "floors": floors, "flats": flats})
    return {"area": d["area"], "comm_num": d["comm"], "buildings": len(out), "named": named,
            "dld_buildings": len(dld_out), "dld_named": sum(1 for r in dld_out if r["name"]),
            "dld_buildings_list": dld_out,
            "distinct_names": len({r["name"] for r in out if r["name"]}),
            "note": "Every name is an ID join, never a name match. For villa clusters the project name is the cluster, not a unique "
                    "building name - show it as the cluster and keep plot_code for the plot.",
            "buildings_list": out}


PROJ_COLS = ("project_id", "project_number", "property_id", "project_status", "percent_completed", "project_start_date",
             "project_end_date", "completion_date", "no_of_units", "no_of_buildings", "no_of_villas", "no_of_lands",
             "escrow_agent_name", "area_name_en", "master_project_en", "project_name",
             # v238 - the developer's register number, carried through the cut so build_scheme_links can put it on
             # the building's project row and the pillars card can find the developer's record by id rather than by
             # name. Name matching reached 16% of stacked buildings; the id route reaches the 49% that have a
             # project row at all.
             "developer_number", "developer_name")


def cut_projects(con, d):
    like = d["area"].replace("'", "''")
    rows = con.execute("""select %s, p.name_en, p.master_en, p.units, p.buildings from g_dld__projects r
                          left join (select try_cast(project_id as bigint) pid, any_value(project_name_en) name_en,
                                            any_value(master_project_en) master_en, count(*) units,
                                            count(distinct parent_property_id) buildings
                                     from g_dld__units where project_id is not null group by 1) p
                            on p.pid = try_cast(r.project_id as bigint)
                          where upper(coalesce(r.area_name_en,'')) = upper('%s')
                             or upper(coalesce(r.master_project_en,'')) = upper('%s')""" % (
        ", ".join("r.%s" % c for c in PROJ_COLS), like, like)).fetchall()
    keys = list(PROJ_COLS) + ["project_name_en", "master_project_en_units", "units_registered", "buildings_registered"]
    ID_KEYS = {"project_id", "project_number", "property_id"}
    docs = [{k: (idstr(v) if k in ID_KEYS else v) for k, v in zip(keys, r)} for r in rows]
    bmap = con.execute("""select cast(parent_property_id as varchar), cast(project_id as varchar), any_value(project_name_en), count(*)
                          from g_dld__units where parent_property_id is not null and project_id is not null
                            and (upper(coalesce(area_name_en,'')) = upper('%s') or upper(coalesce(master_project_en,'')) = upper('%s'))
                          group by 1,2""" % (like, like)).fetchall()
    return {"area": d["area"], "columns": keys, "projects": docs,
            "building_to_project": [{"parent_property_id": idstr(b[0]), "project_id": idstr(b[1]), "project_name_en": b[2], "units": b[3]}
                                    for b in bmap],
            "note": "The DLD project register holds project_name and developer_name in ARABIC only; project_name_en comes from the "
                    "units register via project_id. Join by property_id, project_id, or building_to_project - never by name.",
            "named_en": sum(1 for x in docs if x.get("project_name_en"))}


LAND_KEEP = ("property_id", "land_number", "land_sub_number", "parcel_id", "munc_number", "munc_zip_code", "actual_area",
             "land_type_en", "property_sub_type_en", "is_free_hold", "is_registered", "project_id", "project_name_en",
             "master_project_en", "area_name_en", "zone_id", "pre_registration_number")


def cut_land(d, land_rows):
    ID_KEYS = {"property_id", "parcel_id", "project_id", "munc_number", "land_number", "land_sub_number", "zone_id"}
    sel = [{k: (idstr(r.get(k)) if k in ID_KEYS else r.get(k)) for k in LAND_KEEP} for r in land_rows]
    fh = sum(1 for r in sel if r.get("is_free_hold") in (1, 1.0, "1"))
    return {"area": d["area"], "columns": list(LAND_KEEP), "plots": sel, "freehold": fh,
            "with_parcel_id": sum(1 for r in sel if r.get("parcel_id")),
            "note": "DLD land registry (PROD). parcel_id is the DM parcel where DLD holds it. No geometry in this dataset."}


def cut_makani(con, d):
    rows = con.execute("""select makani, entrance_id, lon, lat, duid, dist_m, entrance_type
                          from lk_makani_entrances where comm_num = ?""", [d["comm"]]).fetchall()
    return {"area": d["area"], "comm_num": d["comm"],
            "points": [dict(zip(("makani", "entrance_id", "lon", "lat", "duid", "dist_m", "entrance_type"), r)) for r in rows],
            "with_duid": sum(1 for r in rows if r[4]),
            "note": "DM Makani entrance points; duid is the twin identity already bound, dist_m its distance from that anchor."}


def cut_permits(con, d):
    rows = con.execute("""select p.parcel_id, p.project_no, p.permit_no, cast(p.permit_date as varchar),
                                 cast(p.application_submission_date as varchar), cast(p.approval_date as varchar),
                                 cast(p.permit_renewal_date as varchar), p.application_type_english, p.application_status_english,
                                 p.building_count, p.building_type, p.total_area
                          from g_dm__building_permits p
                          where cast(try_cast(p.parcel_id as bigint) as varchar) in (
                                select distinct cast(parcel_key as varchar) from lk_dm_buildings where comm_num = ?)""",
                       [d["comm"]]).fetchall()
    keys = ("parcel_id", "project_no", "permit_no", "permit_date", "submitted", "approved", "renewed", "application_type",
            "status", "building_count", "building_type", "total_area")
    return {"area": d["area"], "comm_num": d["comm"], "columns": list(keys),
            "permits": [{k: (idstr(v) if k in ("parcel_id", "project_no") else v) for k, v in zip(keys, r)} for r in rows],
            "new_building": sum(1 for r in rows if (r[7] or "") == "Final-New Building"),
            "note": "DM permits carry parcel_id and project_no, never building_id. Join permit -> parcel -> parcel_buildings_<slug>.json, "
                    "then pick the building. application_type 'Final-New Building' is new construction."}


def cut_usages(con, d):
    """The Municipality's own use list per building - the second source the floor register has never had.
    One row per building x usage, so a mixed building has several; the floor register says which FLOOR, this says whether the
    Municipality agrees the use is there at all."""
    rows = con.execute("""select cast(cast(u.building_id as bigint) as varchar), cast(cast(u.usage_id as bigint) as varchar),
                                 l.usage_description_english
                          from g_dm__building_usages u
                          left join g_dm__building_usages_lookup l on cast(l.usage_id as bigint) = cast(u.usage_id as bigint)
                          where cast(cast(u.building_id as bigint) as varchar) in (
                                select cast(building_id as varchar) from lk_dm_buildings where comm_num = ?)""", [d["comm"]]).fetchall()
    by_b = collections.defaultdict(list)
    for bid, uid, desc in rows:
        by_b[bid].append({"usage_id": uid, "usage": desc})
    return {"area": d["area"], "comm_num": d["comm"], "buildings": len(by_b), "rows": len(rows),
            "note": "DM building usages: the Municipality's use list per building_id, independent of the floor register. A building "
                    "with several rows is mixed use. It says WHETHER a use is recorded, never which floor - compare it against the "
                    "floor register's per-floor use, and treat a disagreement as a question, not an error.",
            "by_building": dict(by_b)}


DLDB_COLS = ("property_id", "parcel_id", "parent_property_id", "building_number", "floors", "bld_levels", "flats", "offices",
             "shops", "car_parks", "elevators", "swimming_pools", "built_up_area", "actual_area", "common_area", "land_number",
             "land_sub_number", "land_type_en", "project_id", "project_name_en", "master_project_en", "property_sub_type_en",
             "is_free_hold", "is_registered", "area_id", "area_name_en")


def cut_dld_buildings(con, d):
    """The DLD building register for one district: the KEY BRIDGE between the two spines.

    22 Sep 2026, measured by the twin on its own stacks: of 1,918 buildings, 84% carry a DLD property_id, 37% a DM building id
    and only 5% a parcel key - so every parcel-keyed register (contractor, consultant, permits, usages, project information)
    could reach a twentieth of them. This file carries property_id AND parcel_id on the same row, which turns the key the twin
    has into the key those registers need. It is also an id-only path from a footprint to its units:
    parcel -> property_id -> units.parent_property_id, with no name matching anywhere in the chain.
    Citywide 110,720 of 257,039 rows (43%) carry a parcel_id the DM building register also knows; the rest carry a DLD parcel
    number with no DM counterpart, so the bridge is real but partial, and each district's file reports its own share."""
    like = d["area"].replace("'", "''")
    rows = con.execute("select %s from g_dld__buildings where upper(coalesce(area_name_en,'')) = upper('%s')"
                       % (", ".join(DLDB_COLS), like)).fetchall()
    ID = {"property_id", "parcel_id", "parent_property_id", "project_id", "area_id", "land_number", "land_sub_number"}
    docs = [{k: (idstr(v) if k in ID else v) for k, v in zip(DLDB_COLS, r)} for r in rows]
    dm = set()
    if d["comm"]:
        dm = {str(x[0]) for x in con.execute(
            "select distinct cast(parcel_key as varchar) from lk_dm_buildings where comm_num = ?", [d["comm"]]).fetchall()}
    on_dm = sum(1 for x in docs if x.get("parcel_id") and x["parcel_id"] in dm)
    return {"area": d["area"], "columns": list(DLDB_COLS), "buildings": len(docs),
            "with_parcel_id": sum(1 for x in docs if x.get("parcel_id")),
            "parcel_id_on_dm_spine": on_dm,
            "note": "THE KEY BRIDGE: property_id (the key the twin holds on ~84% of its buildings) and parcel_id (what the "
                    "Municipality registers are keyed on) on the same row. Use it to reach contractor, consultant, permits, "
                    "usages and project information from a property_id, and as an id-only path footprint -> parcel -> "
                    "property_id -> units.parent_property_id. parcel_id_on_dm_spine counts this district's rows whose parcel "
                    "the DM building register also knows; the remainder carry a DLD parcel number with no DM counterpart.",
            "buildings_list": docs}


# 22 Sep 2026: the registers carry the same firm under several spellings - 7,072 raw contractor names collapse to 6,985 once
# trimmed and case-folded, 1,265 consultants to 1,250. The display string stays exactly as the register wrote it; *_key is the
# normalised form, and anything that GROUPS or counts firms must use the key or it will report one firm as two.
TEAM_COLS = ("project_no", "parcel_id", "contractor_english", "contractor_key", "contractor_license_no", "consultant_english",
             "consultant_key",
             "consultant_license_no", "project_type", "building_type", "building_count", "first_building_permit_date",
             "last_app_submission_date", "project_status", "project_closing_date", "community_name")
NORM_NAME = "upper(regexp_replace(trim({c}), '\s+', ' ', 'g'))"

TEAM_SQL = """
    with p as (select distinct cast(parcel_key as varchar) k from lk_dm_buildings where comm_num = ?),
    c as (select cast(cast(try_cast(trim(cast(parcel_id as varchar)) as double) as bigint) as varchar) pk, project_no,
                 contractor_english, contractor_license_no, consultant_english, null consultant_license_no, project_type,
                 building_type, building_count, first_building_permit_date, last_app_submission_date, project_status,
                 project_closing_date, community_name
          from g_dm__contractor_projects
          union all
          select cast(cast(try_cast(trim(cast(parcel_id as varchar)) as double) as bigint) as varchar), project_no,
                 contractor_english, null, consultant_english, consultant_license_no, project_type, building_type,
                 building_count, first_building_permit_date, last_app_submission_date, project_status,
                 project_closing_date, community_name
          from g_dm__consultant_projects)
    select c.project_no, c.pk, c.contractor_english, upper(regexp_replace(trim(c.contractor_english), '\s+', ' ', 'g')),
           c.contractor_license_no, c.consultant_english, upper(regexp_replace(trim(c.consultant_english), '\s+', ' ', 'g')),
           c.consultant_license_no,
           c.project_type, c.building_type, c.building_count, cast(c.first_building_permit_date as varchar),
           cast(c.last_app_submission_date as varchar), c.project_status, cast(c.project_closing_date as varchar),
           c.community_name
    from c join p on p.k = c.pk"""


def cut_project_team(con, d):
    """Who designed it and who built it, by parcel: the DM contractor and consultant registers, merged.
    Each register names the other party, so a row from either side carries both where the Municipality recorded both."""
    rows = con.execute(TEAM_SQL, [d["comm"]]).fetchall()
    seen, out = set(), []
    for r in rows:
        key = (r[0], r[1], r[3], r[6])      # dedupe on the NORMALISED names, not the register's spellings
        if key in seen:
            continue
        seen.add(key)
        out.append({k: (idstr(v) if k in ("project_no", "parcel_id") else v) for k, v in zip(TEAM_COLS, r)})
    return {"area": d["area"], "comm_num": d["comm"], "columns": list(TEAM_COLS), "rows": len(out),
            "with_contractor": sum(1 for x in out if x.get("contractor_english")),
            "with_consultant": sum(1 for x in out if x.get("consultant_english")),
            "distinct_contractors": len({x["contractor_key"] for x in out if x.get("contractor_key")}),
            "distinct_consultants": len({x["consultant_key"] for x in out if x.get("consultant_key")}),
            "note": "DM contractor and consultant project registers, joined to this district by parcel (95.1% of their rows "
                    "carry a parcel the spine knows). 'Designed by X, built by Y' per parcel: join parcel -> "
                    "parcel_buildings_<slug>.json to choose the building, or arrive from a property_id through "
                    "dld_buildings_<slug>.json. A parcel with several projects has several rows, oldest permit first. "
                    "GROUP FIRMS BY contractor_key / consultant_key, never by the display name: the register spells the same "
                    "firm several ways (7,072 raw contractor names are 6,985 once normalised), so grouping on the raw string "
                    "reports one firm as two.",
            "projects": out}


def cut_project_buildings(con, d):
    """The Municipality's own project -> building mapping, with construction stage and declared building cost.
    A second route from a project to its buildings that never touches the DLD project_id."""
    rows = con.execute("""select cast(cast(i.project_no as bigint) as varchar), cast(cast(i.building_id as bigint) as varchar),
                                 i.building_construction_stage_e, i.building_cost, cast(b.parcel_key as varchar)
                          from g_dm__project_building_information i
                          join lk_dm_buildings b on b.building_id = i.building_id
                          where b.comm_num = ?""", [d["comm"]]).fetchall()
    keys = ("project_no", "building_id", "construction_stage", "building_cost", "parcel_key")
    out = [dict(zip(keys, r)) for r in rows]
    return {"area": d["area"], "comm_num": d["comm"], "columns": list(keys), "rows": len(out),
            "with_cost": sum(1 for x in out if x.get("building_cost")),
            "with_stage": sum(1 for x in out if x.get("construction_stage")),
            "note": "DM project -> building mapping; every one of its 208,946 citywide rows meets the DM building spine. Carries "
                    "the Municipality's own construction stage (Site organizing, Internal finishes, Final finishes, Work "
                    "completed) and the declared building cost. This is the project-to-building route that does NOT depend on "
                    "the DLD project_id.",
            "buildings": out}


def centre(con, comm):
    r = con.execute("select avg(lat), avg(lon), count(*) from lk_makani_entrances where comm_num = ?", [comm]).fetchone()
    if r and r[2]:
        return r[0], r[1], "makani entrance points"
    r = con.execute("select lat, lon from lk_d_community where comm_num = ? and lat is not null", [comm]).fetchone()
    return (r[0], r[1], "community centre") if r else (None, None, None)


def cut_amenities(con, d):
    lat, lon, how = centre(con, d["comm"])
    if lat is None:
        return None
    km = "111.2 * sqrt(pow(%f - lat, 2) + pow((%f - lon) * 0.906, 2))" % (lat, lon)
    sch = con.execute("""select name_eng, curriculumen, overallperformanceen, areaen, cast(studentcount as varchar), round(%s, 2) km
                         from (select *, try_cast(lat as double) lat, try_cast(long as double) lon from g_khda__school_search)
                         where lat is not null and %s <= %g order by km""" % (km, km, RADIUS_KM)).fetchall()
    # The health positions come from the PRECISE register where we have them.
    #
    # sheryan_facility_detail truncates LATITUDE to two decimals - about 1.1 km - and this count is what the
    # building page's LOCATION axis reads. amenities_official.py already repairs those positions, but it
    # writes amenities.json and THIS reads the raw lake table, so the repair never reached the district
    # count: rebuilding amenities moved 888 positions and changed this number by exactly zero, which is how
    # the gap was found. The same 1,150 m guard applies, because a "correction" further than truncation
    # could explain is a different facility, not a better position.
    # The DHA facility register SWAPS its coordinate columns: xcoordinate holds LATITUDE (truncated to
    # two decimals, ~1.1 km) and ycoordinate holds LONGITUDE at full precision. Reversed from what the
    # names say. Three sessions re-derived this on 23 Sep 2026 alone - the caveat existed, in one file's
    # docstring, which is not where anyone reads it. It belongs at every point of use.
    dha = con.execute("""select facilitynameenglish, facilitycategorynameenglish, facilitysubcategorynameenglish, areaenglish,
                                round(%s, 2) km
                         from (select f.*,
                                      case when p.lat is not null and 111.2 * sqrt(pow(p.lat - f.rawlat, 2)
                                             + pow((p.lon - f.rawlon) * 0.906, 2)) <= 1.15 then p.lat else f.rawlat end lat,
                                      case when p.lat is not null and 111.2 * sqrt(pow(p.lat - f.rawlat, 2)
                                             + pow((p.lon - f.rawlon) * 0.906, 2)) <= 1.15 then p.lon else f.rawlon end lon
                               from (select *, case when try_cast(xcoordinate as double) between 54.8 and 56.0
                                                    then try_cast(ycoordinate as double) else try_cast(xcoordinate as double) end rawlat,
                                                case when try_cast(xcoordinate as double) between 54.8 and 56.0
                                                    then try_cast(xcoordinate as double) else try_cast(ycoordinate as double) end rawlon,
                                                status from g_dha__sheryan_facility_detail) f
                               left join dha_precise p on cast(f.id as varchar) = p.id)
                         where lat between 24.6 and 25.5 and lon between 54.8 and 56.0 and status = 'FAC_ACT' and %s <= %g
                         order by km""" % (km, km, RADIUS_KM)).fetchall()
    return {"centre": {"lat": lat, "lon": lon, "label": d["area"], "from": how}, "radius_km": RADIUS_KM,
            "schools": [dict(zip(("name", "curriculum", "rating", "area", "students", "km"), r)) for r in sch],
            "health": [dict(zip(("name", "category", "subcategory", "area", "km"), r)) for r in dha],
            "note": "Distances are straight-line from the district centre, not from a building's door."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=""); ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    con = connect()
    # id -> full-precision DHA position (the DDA session, 23 Sep 2026), so the health count below is not
    # computed from latitudes the register truncated to 1.1 km.
    con.execute("create or replace temp table dha_precise(id varchar, lat double, lon double)")
    try:
        with io.open(os.path.join(BOARD, "_dha_precise_points.json"), encoding="utf-8") as fh:
            _pts = (json.load(fh).get("points") or {})
        con.executemany("insert into dha_precise values (?,?,?)",
                        [(str(k), float(v[0]), float(v[1])) for k, v in _pts.items()])
        print("dha precise points loaded: %d" % len(_pts))
    except Exception as e:
        print("dha precise points unavailable, health falls back to the truncated register: %s" % e)
    todo = [d for d in districts() if not a.slug or d["slug"] == a.slug]
    land_all = json.load(io.open(LAND_FILE, encoding="utf-8"))["results"]
    land_by_area = collections.defaultdict(list)
    for r in land_all:
        land_by_area[(r.get("area_name_en") or "").upper()].append(r)
    summary = []
    for d in todo:
        rows = land_by_area.get(d["area"].upper(), [])
        land_by_parcel = {}
        for r in rows:
            nm, pid = (r.get("project_name_en") or "").strip(), r.get("parcel_id")
            if nm and pid:
                try: land_by_parcel[str(int(float(pid)))] = nm
                except Exception: pass
        made = {}
        want = lambda c: (only is None or c in only)
        if want("dld_buildings"):
            doc = cut_dld_buildings(con, d); write("dld_buildings", d["slug"], doc)
            made["dld_buildings"] = "%d (%d on DM parcels)" % (doc["buildings"], doc["parcel_id_on_dm_spine"])
        if want("land_registry"):
            write("land_registry", d["slug"], cut_land(d, rows)); made["land_registry"] = len(rows)
        if d["comm"]:
            if want("parcel_buildings"):
                doc = cut_parcel_buildings(con, d); write("parcel_buildings", d["slug"], doc); made["parcel_buildings"] = doc["buildings"]
            if want("names"):
                doc = cut_names(con, d, land_by_parcel); write("names", d["slug"], doc); made["names"] = "%d/%d" % (doc["named"], doc["buildings"])
            if want("makani"):
                doc = cut_makani(con, d); write("makani", d["slug"], doc); made["makani"] = len(doc["points"])
            if want("usages"):
                doc = cut_usages(con, d); write("usages", d["slug"], doc); made["usages"] = doc["buildings"]
            if want("project_team"):
                doc = cut_project_team(con, d); write("project_team", d["slug"], doc)
                made["project_team"] = "%d (%d contractor, %d consultant)" % (doc["rows"], doc["with_contractor"], doc["with_consultant"])
            if want("project_buildings"):
                doc = cut_project_buildings(con, d); write("project_buildings", d["slug"], doc)
                made["project_buildings"] = "%d (%d cost, %d stage)" % (doc["rows"], doc["with_cost"], doc["with_stage"])
            if want("permits"):
                doc = cut_permits(con, d); write("permits", d["slug"], doc); made["permits"] = len(doc["permits"])
            if want("amenities"):
                doc = cut_amenities(con, d)
                if doc: write("amenities", d["slug"], doc); made["amenities"] = "%d schools, %d health" % (len(doc["schools"]), len(doc["health"]))
        if want("projects"):
            doc = cut_projects(con, d); write("projects", d["slug"], doc); made["projects"] = "%d (%d en)" % (len(doc["projects"]), doc["named_en"])
        summary.append((d["slug"], d["area"], d["comm"], made))
        print("%-26s %-34s comm %-6s %s" % (d["slug"], d["area"], d["comm"] if d["comm"] else "-", made))
    idx = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "districts":
           [{"slug": s, "area": ar, "comm_num": c, "cuts": m} for s, ar, c, m in summary]}
    json.dump(idx, io.open(os.path.join(BOARD, "_district_cuts_index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\n%d districts; index -> data/board/_district_cuts_index.json" % len(summary))


if __name__ == "__main__":
    main()
