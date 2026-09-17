"""build_ev_union.py -- one charge point layer from every source we hold.

Feeds both Azimuth EV tracks: the 2D map (render_ev_map.py), the interactive app (build_ev_app.py)
and the CityEngine prototype (ev_cityengine.py). Builds view `v_ev_charge_points`.

SOURCES, in precedence order. Each point keeps its own, and nothing is flattened:

  DEWA           g_dewa__ev_green_charger   register    the government register, via data.dubai
  OpenChargeMap  o_ocm__charge_points       community   CC-BY-SA
  OpenStreetMap  o_osm__charge_points       community   ODbL

GOV_DATA_METHODOLOGY.md requires a posted number to trace to a public body; only the DEWA rows can
carry that. So every row states its `source` and its `authority` ('register' / 'community'), and any
surface showing a total must be able to split it.

Dedup: a lower-precedence point within DEDUP_M of one already kept is dropped. Distance is the flat
cosine-corrected approximation the house uses for district binding -- accurate to tens of metres at
this latitude, well inside a 150 m threshold.

Enrichment: supercharge.info (o_sci__supercharger_sites, OPEN sites only) carries stall counts and
kW that no other source has. Any point within DEDUP_M of an OPEN Supercharger site takes its
`stall_count` and `power_kw` where the point's own are missing or smaller. `enriched` records that it
happened, because that source has NO explicit open licence and a public surface may need to exclude
it -- see scripts/supercharge_pull.py.

THE COVERAGE NUMBER: DEWA told the Emirates News Agency (WAM) on 23 June 2026 that "Dubai has 2,223
EV charging stations". That is the figure every surface compares against, and it must be quoted with
that date and that wording -- it says STATIONS, and our rows are device-level charge points, so the
comparison is indicative of the gap, not a like-for-like ratio.

    python scripts/build_ev_union.py
    python scripts/build_ev_union.py --export       # also write GeoJSON for the CityEngine track
"""
import argparse, json, os, sys

import duckdb

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
EXPORT = os.path.join(ROOT, "data", "ev")
VIEW = "v_ev_charge_points"
DEDUP_M = 150.0

# DEWA's four published classes, confirmed in the WAM statement of 23 June 2026:
#   Ultrafast 150 kW DC (Type 2) · Fast 43 kW AC / 50 kW DC (CHAdeMO + Combo CCS) ·
#   Public 2 x 22 kW AC (double Type 2) · Wall-Box 22 kW AC (single Type 2).
ARCHETYPE_SQL = """
    case
      when max_power_kw >= 100 then 'ultra_fast_dc'
      when max_power_kw >= 43  then 'fast_dc'
      when connectortype ilike '%chademo%' or connectortype ilike '%ccs%'
        or connectortype ilike '%supercharger%' then 'fast_dc'
      when totalnbofconnectors >= 2 then 'public_ac_dual'
      else 'wallbox_ac'
    end
"""

DIST_M = ("sqrt(power((%(a)s.latitude - %(b)s.latitude) * 111320.0, 2)"
          " + power((%(a)s.longitude - %(b)s.longitude) * 111320.0"
          " * cos(radians(%(a)s.latitude)), 2))")


def has(con, name):
    return con.execute("select count(*) from duckdb_views() where view_name = ? "
                       "union all select count(*) from duckdb_tables() where table_name = ?",
                       [name, name]).fetchdf().iloc[:, 0].sum() > 0


def build(con):
    osm_on = has(con, "o_osm__charge_points")
    sci_on = has(con, "o_sci__supercharger_sites")

    osm_cte = """,
    osm as (
        select
            'OSM-' || replace(osm_id, '/', '-')        as point_id,
            'OpenStreetMap'                            as source,
            'community'                                as authority,
            operator, location_name, location_address,
            latitude, longitude,
            cast(totalnbofconnectors as int)           as totalnbofconnectors,
            connectortype,
            cast(max_power_kw as double)               as max_power_kw,
            source_url
        from o_osm__charge_points
    ),
    osm_kept as (
        select o.* from osm o
        where not exists (select 1 from dewa d where %s < {m})
          and not exists (select 1 from ocm_kept c where %s < {m})
    )""" % (DIST_M % {"a": "o", "b": "d"}, DIST_M % {"a": "o", "b": "c"})

    sql = f"""create or replace view {VIEW} as
    with dewa as (
        select
            'DEWA-' || devicedb_id                     as point_id,
            'DEWA'                                     as source,
            'register'                                 as authority,
            'DEWA'                                     as operator,
            location_name, location_address,
            try_cast(latitude  as double)              as latitude,
            try_cast(longitude as double)              as longitude,
            try_cast(totalnbofconnectors as int)       as totalnbofconnectors,
            connectortype,
            cast(null as double)                       as max_power_kw,
            cast(null as varchar)                      as source_url
        from g_dewa__ev_green_charger
        where try_cast(latitude as double) is not null
          and try_cast(longitude as double) is not null
    ),
    ocm as (
        select
            'OCM-' || cast(ocm_id as varchar)          as point_id,
            'OpenChargeMap'                            as source,
            'community'                                as authority,
            operator, location_name, location_address,
            latitude, longitude,
            cast(totalnbofconnectors as int)           as totalnbofconnectors,
            connectortype,
            cast(max_power_kw as double)               as max_power_kw,
            source_url
        from o_ocm__charge_points
    ),
    ocm_kept as (
        select o.* from ocm o
        where not exists (select 1 from dewa d where {DIST_M % {"a": "o", "b": "d"}} < {DEDUP_M})
    ){osm_cte.format(m=DEDUP_M) if osm_on else ""},
    merged as (
        select * from dewa
        union all select * from ocm_kept
        {"union all select * from osm_kept" if osm_on else ""}
    ),
    enriched as (
        select m.*,
               {"(select max(s.power_kw)    from o_sci__supercharger_sites s where " + (DIST_M % {"a": "m", "b": "s"}) + f" < {DEDUP_M})" if sci_on else "cast(null as double)"} as sci_kw,
               {"(select max(s.stall_count) from o_sci__supercharger_sites s where " + (DIST_M % {"a": "m", "b": "s"}) + f" < {DEDUP_M})" if sci_on else "cast(null as int)"}    as sci_stalls
        from merged m
    ),
    final as (
        select
            point_id, source, authority, operator, location_name, location_address,
            latitude, longitude,
            -- 0 from OSM means "not tagged", not "no connectors" (21 rows). Keep it null so totals
            -- stay honest and a surface can say "not recorded" instead of drawing a zero.
            nullif(greatest(coalesce(totalnbofconnectors, 0), coalesce(sci_stalls, 0)), 0)
                as totalnbofconnectors,
            connectortype,
            greatest(coalesce(max_power_kw, 0), coalesce(sci_kw, 0))
                = 0 ? null : greatest(coalesce(max_power_kw, 0), coalesce(sci_kw, 0)) as max_power_kw,
            source_url,
            (sci_kw is not null or sci_stalls is not null) as enriched
        from enriched
    )
    select *, {ARCHETYPE_SQL} as archetype from final
    """
    # DuckDB has no `?:` ternary; rewrite that one expression with a case.
    sql = sql.replace(
        "greatest(coalesce(max_power_kw, 0), coalesce(sci_kw, 0))\n                = 0 ? null : "
        "greatest(coalesce(max_power_kw, 0), coalesce(sci_kw, 0)) as max_power_kw",
        "case when greatest(coalesce(max_power_kw, 0), coalesce(sci_kw, 0)) = 0 then null "
        "else greatest(coalesce(max_power_kw, 0), coalesce(sci_kw, 0)) end as max_power_kw")
    con.execute(sql)
    return osm_on, sci_on


def report(con, osm_on, sci_on):
    print(con.execute(f"""select source, authority, count(*) points,
                                 sum(totalnbofconnectors) connectors
                          from {VIEW} group by 1,2 order by points desc""").fetchdf().to_string(index=False))
    print()
    print(con.execute(f"""select archetype, count(*) points, sum(totalnbofconnectors) connectors,
                                 round(max(max_power_kw)) max_kw
                          from {VIEW} group by 1 order by points desc""").fetchdf().to_string(index=False))
    tot = con.execute(f"select count(*), sum(totalnbofconnectors) from {VIEW}").fetchone()
    enr = con.execute(f"select count(*) from {VIEW} where enriched").fetchone()[0]
    print(f"\ntotal: {tot[0]} charge points, {tot[1]} connectors"
          f"{'' if not sci_on else f' ({enr} enriched from supercharge.info)'}")
    if not osm_on: print("NOTE: o_osm__charge_points missing -- run scripts/osm_pull.py")
    if not sci_on: print("NOTE: o_sci__supercharger_sites missing -- run scripts/supercharge_pull.py")
    print('DEWA told WAM on 23 June 2026 that "Dubai has 2,223 EV charging stations" -- this layer is'
          "\na documented subset, and their figure counts stations where ours counts charge points.")


def export(con):
    os.makedirs(EXPORT, exist_ok=True)
    rows = con.execute(f"select * from {VIEW}").fetchdf().to_dict("records")
    fc = {"type": "FeatureCollection", "name": "azimuth_ev_charge_points",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": []}
    for r in rows:
        props = {k: (None if v != v else v) for k, v in r.items()
                 if k not in ("latitude", "longitude")}
        fc["features"].append({"type": "Feature",
                               "geometry": {"type": "Point",
                                            "coordinates": [float(r["longitude"]), float(r["latitude"])]},
                               "properties": props})
    p = os.path.join(EXPORT, "ev_charge_points.geojson")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"wrote {p} ({len(fc['features'])} features)")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true", help="also write GeoJSON for the CityEngine track")
    a = ap.parse_args()
    con = duckdb.connect(DB)
    osm_on, sci_on = build(con)
    report(con, osm_on, sci_on)
    if a.export:
        export(con)


if __name__ == "__main__":
    main()
