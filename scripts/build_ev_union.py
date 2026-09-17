"""build_ev_union.py -- one charge point layer from the DEWA register and OpenChargeMap.

Feeds both Azimuth EV tracks: the 2D map (render_ev_map.py) and the CityEngine prototype
(ev_cityengine.py). Builds view `v_ev_charge_points`.

Provenance is kept on every row and never flattened away. GOV_DATA_METHODOLOGY.md requires a posted
number to trace to a public body; OCM is community-contributed and cannot carry that weight. So each
row states its `source` ('DEWA' / 'OpenChargeMap') and `authority` ('register' / 'community'), and any
surface that shows a total must be able to split it.

Dedup: OCM points within DEDUP_M of a DEWA point are dropped, DEWA winning -- it is the register and
the OCM DEWA rows are a thin echo of it (8 rows against 186). Distance is the flat cosine-corrected
approximation the house uses for district binding, accurate to tens of metres at this latitude, which
is well inside a 150 m threshold.

Archetype: charger class is derived for the 3D track. DEWA deploys a small standard set, so ~4
archetypes instanced 300+ times beats modelling each site. Power drives it where known (OCM has
max_power_kw, the DEWA register has no power field at all), connector text otherwise.

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

# DEWA's published classes. ultra-fast 150 kW DC, fast 43 kW AC / 50 kW DC, public 2x22 kW AC,
# wall-box 22 kW AC. One CityEngine asset per archetype.
ARCHETYPE_SQL = """
    case
      when max_power_kw >= 100 then 'ultra_fast_dc'
      when max_power_kw >= 43  then 'fast_dc'
      when connectortype ilike '%chademo%' or connectortype ilike '%ccs%' then 'fast_dc'
      when totalnbofconnectors >= 2 then 'public_ac_dual'
      else 'wallbox_ac'
    end
"""


def build(con):
    con.execute(f"""create or replace view {VIEW} as
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
        where not exists (
            select 1 from dewa d
            where sqrt(power((o.latitude - d.latitude) * 111320.0, 2)
                     + power((o.longitude - d.longitude) * 111320.0
                             * cos(radians(o.latitude)), 2)) < {DEDUP_M}
        )
    ),
    merged as (
        select point_id, source, authority, operator, location_name, location_address,
               latitude, longitude, totalnbofconnectors, connectortype, max_power_kw, source_url
        from dewa
        union all
        select point_id, source, authority, operator, location_name, location_address,
               latitude, longitude, totalnbofconnectors, connectortype, max_power_kw, source_url
        from ocm_kept
    )
    select *, {ARCHETYPE_SQL} as archetype from merged
    """)


def report(con):
    print(con.execute(f"""select source, authority, count(*) points,
                                 sum(totalnbofconnectors) connectors
                          from {VIEW} group by 1,2 order by points desc""").fetchdf().to_string(index=False))
    print()
    print(con.execute(f"""select archetype, count(*) points, sum(totalnbofconnectors) connectors,
                                 round(max(max_power_kw)) max_kw
                          from {VIEW} group by 1 order by points desc""").fetchdf().to_string(index=False))
    tot = con.execute(f"select count(*), sum(totalnbofconnectors) from {VIEW}").fetchone()
    print(f"\ntotal: {tot[0]} charge points, {tot[1]} connectors")
    print("DEWA published 2,223 charge points for Dubai (Q1 2026) -- this layer is a documented subset.")


def export(con):
    os.makedirs(EXPORT, exist_ok=True)
    rows = con.execute(f"select * from {VIEW}").fetchdf().to_dict("records")
    fc = {"type": "FeatureCollection",
          "name": "azimuth_ev_charge_points",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": []}
    for r in rows:
        props = {k: (None if v != v else v) for k, v in r.items()          # NaN -> None
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
    build(con)
    report(con)
    if a.export:
        export(con)


if __name__ == "__main__":
    main()
