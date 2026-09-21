"""key_bridge -- one canonical crosswalk between every key a Dubai building is known by.

Why this exists (22 Sep 2026). The twin measured its own 1,918 buildings: 84% carry a DLD property_id, 37% a DM building_id,
5% a parcel key. Every Municipality register - contractor, consultant, permits, usages, project information - is keyed on
PARCEL, so they could reach one building in twenty. The bridge between those keys already existed, scattered: lk_d_building
holds property_id + parcel_key, g_dld__buildings holds property_id + parcel_id, lk_dm_buildings holds building_id + parcel_key,
the units register holds parent_property_id. Every consumer was re-deriving the same joins from whatever cut it happened to
hold, and each one got a different answer.

This publishes the join once:

    lk_key_bridge        one row per DLD property_id: its parcel, its DM buildings, its project ids, its land number, and
                         where each key came from (source_parcel), plus whether the units register can reach it.
    lk_key_bridge_pairs  one row per (property_id, dm_building_id) for the parcels that hold several buildings, because a
                         parcel is not a tower - a podium, a services block and a tower share one plot.

What it deliberately does NOT do: invent a parcel. A DLD parcel number that the Municipality register has never used stays
unmatched and is reported as such. Citywide that is 57% of DLD buildings, and in the newer freehold districts (JVC, Al
Yelayiss, Palm Deira) it is all of them - those districts get an honest zero rather than a fabricated link.
"""
import re

PROPERTY = """
    select cast(cast(b.property_id as bigint) as varchar)                                                   property_id,
           cast(cast(b.parent_property_id as bigint) as varchar)                                            parent_property_id,
           trim(cast(cast(try_cast(trim(cast(b.parcel_id as varchar)) as double) as bigint) as varchar))    dld_parcel_id,
           nullif(trim(cast(b.building_number as varchar)), '')                                             building_number,
           nullif(trim(cast(b.project_name_en as varchar)), '')                                             project_name_en,
           cast(cast(b.project_id as bigint) as varchar)                                                    dld_project_id,
           cast(cast(b.area_id as bigint) as varchar)                                                       area_id,
           b.area_name_en,
           nullif(trim(cast(b.land_number as varchar)), '')                                                 land_number,
           b.floors, b.flats, b.offices, b.shops, b.car_parks, b.elevators, b.built_up_area
    from g_dld__buildings b where b.property_id is not null"""


def job_key_bridge(con):
    q = lambda s: con.execute(s).fetchall()
    con.execute("create or replace temp table k_prop as " + PROPERTY)

    # the Municipality side, keyed by parcel: which DM buildings sit on each parcel, and how tall
    con.execute("""create or replace temp table k_dm as
        select cast(cast(b.building_id as bigint) as varchar) dm_building_id,
               cast(b.parcel_key as varchar) parcel_key, b.comm_num, b.community_name,
               cast(cast(b.project_no as bigint) as varchar) dm_project_no, b.building_type, b.typical_floors, b.height_m
        from lk_dm_buildings b where b.parcel_key is not null""")

    # the canonical id and parcel the thread already minted, where it has one
    con.execute("""create or replace temp table k_canon as
        select cast(cast(property_id as bigint) as varchar) property_id, canonical_id,
               cast(parcel_key as varchar) parcel_key, comm_num
        from lk_d_building where property_id is not null""")

    # the land registry as a third route to a parcel: its plots carry both a land number and a DM parcel_id
    con.execute("""create or replace temp table k_land as
        select cast(cast(property_id as bigint) as varchar) property_id,
               trim(cast(cast(try_cast(trim(cast(parcel_id as varchar)) as double) as bigint) as varchar)) parcel_key
        from g_dld__land_registry where property_id is not null and parcel_id is not null""")

    # which property ids the units register can actually reach (its parent_property_id), and how many units hang off each
    con.execute("""create or replace temp table k_units as
        select cast(cast(parent_property_id as bigint) as varchar) property_id, count(*) unit_rows,
               count(distinct floor) floors_with_units
        from g_dld__units where parent_property_id is not null group by 1""")

    con.execute("""create or replace temp table k_bridge as
        with parcel_choice as (
            select p.property_id,
                   -- a parcel is only claimed when the Municipality register knows it; each route is named, never blended
                   case when dmp.parcel_key is not null then p.dld_parcel_id
                        when c.parcel_key is not null then c.parcel_key
                        when l.parcel_key is not null and lp.parcel_key is not null then l.parcel_key end parcel_key,
                   case when dmp.parcel_key is not null then 'dld_parcel_id on the DM register'
                        when c.parcel_key is not null then 'thread building spine'
                        when l.parcel_key is not null and lp.parcel_key is not null then 'land registry plot' end source_parcel
            from k_prop p
            left join (select distinct parcel_key from k_dm) dmp on dmp.parcel_key = p.dld_parcel_id
            left join k_canon c on c.property_id = p.property_id
            left join k_land  l on l.property_id = p.property_id
            left join (select distinct parcel_key from k_dm) lp on lp.parcel_key = l.parcel_key)
        select p.property_id, p.parent_property_id, p.dld_parcel_id, pc.parcel_key, pc.source_parcel,
               d.n_dm_buildings, d.dm_building_id, d.dm_project_no, d.comm_num, d.community_name,
               p.area_id, p.area_name_en, p.dld_project_id, p.project_name_en, p.land_number, p.building_number,
               p.floors, p.flats, p.offices, p.shops, p.car_parks, p.elevators, p.built_up_area,
               coalesce(u.unit_rows, 0) unit_rows, coalesce(u.floors_with_units, 0) floors_with_units,
               c.canonical_id
        from k_prop p
        left join parcel_choice pc on pc.property_id = p.property_id
        left join (select parcel_key, count(*) n_dm_buildings,
                          -- the tallest building on the plot, which for a mixed plot is the tower rather than its podium
                          arg_max(dm_building_id, coalesce(typical_floors, -1)) dm_building_id,
                          any_value(dm_project_no) dm_project_no, any_value(comm_num) comm_num,
                          any_value(community_name) community_name
                   from k_dm group by 1) d on d.parcel_key = pc.parcel_key
        left join k_units u on u.property_id = p.property_id
        left join k_canon c on c.property_id = p.property_id""")

    con.execute("""create or replace temp table k_pairs as
        select b.property_id, m.dm_building_id, m.parcel_key, m.building_type, m.typical_floors, m.height_m
        from k_bridge b join k_dm m on m.parcel_key = b.parcel_key where b.parcel_key is not null""")

    n = q("select count(*) from k_bridge")[0][0]
    with_parcel = q("select count(*) from k_bridge where parcel_key is not null")[0][0]
    with_dm = q("select count(*) from k_bridge where dm_building_id is not null")[0][0]
    with_units = q("select count(*) from k_bridge where unit_rows > 0")[0][0]
    reachable = q("""select count(*) from k_bridge
                     where parcel_key is not null or dm_building_id is not null or unit_rows > 0""")[0][0]
    by_src = q("select coalesce(source_parcel, 'no parcel'), count(*) from k_bridge group by 1 order by 2 desc")
    multi = q("select count(*) from k_bridge where n_dm_buildings > 1")[0][0]
    worst = q("""select area_name_en, count(*) n, count(parcel_key) p from k_bridge
                 where area_name_en is not null group by 1 having n >= 500 order by 1.0 * p / n limit 5""")
    best = q("""select area_name_en, count(*) n, count(parcel_key) p from k_bridge
                where area_name_en is not null group by 1 having n >= 500 order by 1.0 * p / n desc limit 5""")

    return {"tables": [("lk_key_bridge", "select * from k_bridge"), ("lk_key_bridge_pairs", "select * from k_pairs")],
            "views": [("v_key_bridge_reachable",
                       "select * from lk_key_bridge where parcel_key is not null or dm_building_id is not null or unit_rows > 0")],
            "keys_in": n, "keys_matched": reachable, "rows_in": n,
            "note": "DLD buildings reachable by at least one other key (parcel, DM building or units)",
            "report": ["%s DLD buildings; parcel %s, DM building %s, units %s" % (
                           format(n, ","), format(with_parcel, ","), format(with_dm, ","), format(with_units, ",")),
                       "parcels holding more than one DM building: %s (a parcel is not a tower)" % format(multi, ","),
                       "how the parcel was reached:"]
                      + ["   %-36s %s" % (s, format(c, ",")) for s, c in by_src]
                      + ["best areas (>=500 buildings): " + ", ".join("%s %.0f%%" % (a, 100.0 * p / n2) for a, n2, p in best),
                         "worst: " + ", ".join("%s %.0f%%" % (a, 100.0 * p / n2) for a, n2, p in worst)]}
