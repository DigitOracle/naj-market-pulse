"""City facts for her morning feed - Dubai as a place to live, not only a market to trade.

Her five angles have all been demand: prices, volumes, off-plan share, yields. Every broker in Dubai
posts the same numbers from the same register. What the government pull adds is the city itself, and
the strongest of it is not a statistic anyone publishes - it is a JOIN. The metro register has 55
stations with coordinates; her board has 41 districts with centroids. Nobody else holds both, so
nobody else can say which of the areas she sells actually has a station near it.

Every read goes through the realness gate. The staging environment scrambles SOME ROWS of otherwise
real datasets - 9 of 235 in the bus coverage register - so this resolves each dataset to the
`g_<entity>__<dataset>` view the gate built and never touches a base table. Reading the base table
would have imported nine fabricated communities into her feed.

Writes a `cityLife` block into public/pulse.json. The feed already has a `transit` family, so an
angle can land there without any change to the Worker.
"""
import argparse, datetime as dt, io, json, os, sys

import duckdb

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
PULSE = os.path.join(ROOT, "public", "pulse.json")

# Great-circle is overkill across one emirate; a flat approximation with a cosine correction is
# accurate to a few tens of metres at this latitude and keeps the query readable.
KM = "111.0*sqrt(power(d.lat-s.lat,2)+power((d.lon-s.lon)*cos(radians(d.lat)),2))"


def gated(con, dataset):
    """The gate's clean view for a dataset, or None if it has nothing usable."""
    r = con.execute("select clean_view, rows_clean, rows_fabricated from gov_dataset "
                    "where dataset like ? and clean_view is not null and rows_clean > 0",
                    [dataset + "%"]).fetchone()
    return (r[0], r[1], r[2]) if r else (None, 0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pulse", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(DB, read_only=True)
    block = {"asOf": dt.date.today().isoformat(),
             "source": "Dubai Data (DDA) open datasets, read through the realness gate and joined to "
                       "the Najma district board",
             "caution": "structural facts. Station locations, community coverage and hourly airport "
                        "patterns do not move week to week, so these are safe to state without a fresh pull.",
             "basedOn": [], "excludedFillRows": 0}

    def note(dataset, view, clean, fill):
        block["basedOn"].append({"dataset": dataset, "rowsUsed": clean, "fillRowsExcluded": fill})
        block["excludedFillRows"] += fill

    # 1. METRO ACCESS BY DISTRICT - the join nobody else can make.
    v, cl, fl = gated(con, "rta_metro_stations")
    if v:
        near = con.execute(f"""
            with s as (select location_name_english nm, line_name ln,
                              cast(station_location_longitude as double) lon,
                              cast(station_location_latitude as double) lat
                       from {v} where try_cast(station_location_longitude as double) is not null),
                 d as (select name, slug, lon, lat from district where lon is not null),
                 j as (select d.name, d.slug, s.nm, s.ln, {KM} km from d cross join s),
                 r as (select *, row_number() over (partition by slug order by km) rn from j)
            select name, nm, ln, round(km, 1) from r where rn = 1 order by km""").fetchall()
        block["metro"] = {
            "stations": cl,
            "byLine": dict(con.execute("select line_name, count(*) from %s group by 1 order by 2 desc" % v).fetchall()),
            "districtsMeasured": len(near),
            "withinWalk2km": len([x for x in near if x[3] <= 2.0]),
            "beyond5km": len([x for x in near if x[3] > 5.0]),
            "closest": [{"district": x[0], "station": x[1], "line": x[2], "km": x[3]} for x in near[:8]],
            "furthest": [{"district": x[0], "station": x[1], "km": x[3]} for x in near[-8:]],
            "oldestStationOpened": str(con.execute("select min(try_cast(station_opening_date as date)) from %s" % v).fetchone()[0]),
        }
        note("rta_metro_stations", v, cl, fl)

    # 2. BUS COVERAGE BY COMMUNITY - the Roads Authority's own measure of who the network reaches.
    #    This is the day-in-the-life layer: official population, stop count, and the share of that
    #    population within reach of a stop. Reported by community name, NOT mapped onto her board:
    #    only a handful of the 226 names match her district labels exactly and a fuzzy match here
    #    would invent a geography.
    v, cl, fl = gated(con, "rta_bus_network_coverage")
    if v:
        city = con.execute(f"""select count(*) communities, sum(population) pop,
                                      sum(nume_of_bus_stops) stops, sum(accessible_population) reach,
                                      round(100.0*sum(accessible_population)/nullif(sum(population),0), 1) pct,
                                      max(report_date) as_of
                               from {v} where population is not null""").fetchone()
        worst = con.execute(f"""select community_name, population, nume_of_bus_stops, geographic_coverage
                                from {v} where population > 2000
                                order by geographic_coverage, population desc limit 6""").fetchall()
        best = con.execute(f"""select community_name, population, nume_of_bus_stops, geographic_coverage
                               from {v} where population > 10000
                               order by geographic_coverage desc, population desc limit 6""").fetchall()
        nostop = con.execute(f"""select count(*), sum(population) from {v}
                                 where population > 1000 and coalesce(nume_of_bus_stops,0) = 0""").fetchone()
        # The Valley is hers to sell right now, and it registers under its legacy community name.
        valley = con.execute(f"""select community_name, population, nume_of_bus_stops,
                                        accessible_population, geographic_coverage
                                 from {v} where community_name in ('AL YUFRAH 1','AL YUFRAH 2','AL YUFRAH 3','AL YUFRAH 4')
                                 order by community_name""").fetchall()
        block["busCoverage"] = {
            "measure": "Roads and Transport Authority bus network coverage by community",
            "reportDate": str(city[5]),
            "communities": city[0],
            "populationCovered": int(city[1] or 0),
            "stops": int(city[2] or 0),
            "withinReach": int(city[3] or 0),
            "cityCoveragePct": city[4],
            "communitiesOver1000WithNoStop": {"count": nostop[0], "residents": int(nostop[1] or 0)},
            "worstServed": [{"community": x[0], "residents": x[1], "stops": x[2], "coveragePct": x[3]} for x in worst],
            "bestServed": [{"community": x[0], "residents": x[1], "stops": x[2], "coveragePct": x[3]} for x in best],
            "theValley": [{"community": x[0], "residents": x[1], "stops": x[2],
                           "withinReach": x[3], "coveragePct": x[4]} for x in valley],
            "note": "reported by the community names the Authority uses, not mapped onto the district "
                    "board; only a few names match exactly and a fuzzy match would invent a geography",
        }
        note("rta_bus_network_coverage", v, cl, fl)

    # 3. BUS STOPS NEAR HER DISTRICTS - the count she can actually quote for an area.
    v, cl, fl = gated(con, "rta_bus_stop_details")
    if v:
        rows = con.execute(f"""
            with s as (select cast(stop_location_longitude as double) lon,
                              cast(stop_location_latitude as double) lat
                       from {v} where try_cast(stop_location_longitude as double) is not null),
                 d as (select name, lon, lat from district where lon is not null)
            select d.name, count(*) stops from d join s on {KM} <= 3 group by 1 order by 2 desc""").fetchall()
        block["busStops"] = {"total": cl, "radiusKm": 3,
                             "mostServed": [{"district": x[0], "stops": x[1]} for x in rows[:6]],
                             "leastServed": [{"district": x[0], "stops": x[1]} for x in rows[-6:]],
                             "districtsWithNone": con.execute("select count(*) from district where lon is not null").fetchone()[0] - len(rows)}
        note("rta_bus_stop_details", v, cl, fl)

    # 4. THE AIRPORT'S OWN RHYTHM - relatable to anyone who lives here, and in no property feed.
    v, cl, fl = gated(con, "dans_e_dxb_hourly_departure_throughput")
    if v:
        rows = con.execute(f"""select period, round(avg(cast(number as double)), 1) avg_per_hour
                               from {v} where try_cast(number as double) is not null
                               group by 1 order by avg_per_hour desc""").fetchall()
        if rows:
            block["airport"] = {"airport": "DXB", "measure": "average departures per hour band",
                                "busiest": [{"hour": r[0], "perHour": r[1]} for r in rows[:3]],
                                "quietest": [{"hour": r[0], "perHour": r[1]} for r in rows[-3:]],
                                "observations": cl}
            note("dans_e_dxb_hourly_departure_throughput", v, cl, fl)

    # 5. HOW FAST THE CITY ACTUALLY MOVES. Median, because the raw column runs to 201 km/h.
    v, cl, fl = gated(con, "rta_average_speed_per_line_buses")
    if v:
        cols = [d[0] for d in con.execute("select * from %s limit 1" % v).description]
        spd = next((x for x in cols if "speed" in x.lower()), None)
        line = next((x for x in cols if "route" in x.lower() or "line" in x.lower()), None)
        if spd and line:
            rows = con.execute('select "%s" ln, round(avg(try_cast("%s" as double)), 1) kph from %s '
                               'where try_cast("%s" as double) between 1 and 120 group by 1 '
                               'having count(*) >= 5 order by kph' % (line, spd, v, spd)).fetchall()
            mid = con.execute('select round(median(try_cast("%s" as double)), 1), '
                              'round(avg(try_cast("%s" as double)), 1), count(*) from %s '
                              'where try_cast("%s" as double) between 1 and 120' % (spd, spd, v, spd)).fetchone()
            if rows:
                block["buses"] = {"measure": "average speed in km/h", "medianKph": mid[0], "meanKph": mid[1],
                                  "observations": mid[2], "linesMeasured": len(rows),
                                  "slowest": [{"line": r[0], "kph": r[1]} for r in rows[:4]],
                                  "fastest": [{"line": r[0], "kph": r[1]} for r in rows[-4:]],
                                  "note": "readings outside 1-120 km/h are excluded; the raw column "
                                          "contains values up to 201"}
                note("rta_average_speed_per_line_buses", v, cl, fl)

    # 6. WHO THE CITY LICENSES - titles, not people. Say so.
    v, cl, fl = gated(con, "gdrfa_profession")
    if v:
        block["professions"] = {"recognised": con.execute("select count(distinct professiondescen) from %s" % v).fetchone()[0],
                                "note": "recognised occupation titles in the residency register, not a count of residents"}
        note("gdrfa_profession", v, cl, fl)

    # 7. OLD DUBAI.
    v, cl, fl = gated(con, "dm_heritage_places")
    if v:
        rows = con.execute(f"""select heritage_location, max(year_visited) yr,
                                      sum(try_cast(number_of_visitors as double)) vis
                               from {v} group by 1 having vis > 0 order by vis desc limit 5""").fetchall()
        if rows:
            block["heritage"] = {"sites": con.execute("select count(distinct heritage_location) from %s" % v).fetchone()[0],
                                 "mostVisited": [{"site": r[0], "throughYear": r[1], "visitors": int(r[2])} for r in rows]}
            note("dm_heritage_places", v, cl, fl)

    sections = [k for k in block if k not in ("asOf", "source", "caution", "basedOn", "excludedFillRows")]
    print("cityLife: %d sections, %d datasets, %d fill rows kept out"
          % (len(sections), len(block["basedOn"]), block["excludedFillRows"]))
    m = block.get("metro")
    if m:
        print("  metro       %d stations; %d of %d districts within 2 km, %d beyond 5 km"
              % (m["stations"], m["withinWalk2km"], m["districtsMeasured"], m["beyond5km"]))
    b = block.get("busCoverage")
    if b:
        print("  coverage    %d communities, %s residents, %s stops, %s%% of the population within reach"
              % (b["communities"], f'{b["populationCovered"]:,}', f'{b["stops"]:,}', b["cityCoveragePct"]))
        print("              %d communities over 1,000 residents have NO stop (%s people)"
              % (b["communitiesOver1000WithNoStop"]["count"], f'{b["communitiesOver1000WithNoStop"]["residents"]:,}'))
        for vv in b["theValley"]:
            print("              %s: %s residents, %s stop(s), %s%% covered"
                  % (vv["community"], f'{vv["residents"]:,}', vv["stops"], vv["coveragePct"]))
    if block.get("busStops"):
        print("  stops       %s mapped; %d district(s) with none inside 3 km"
              % (f'{block["busStops"]["total"]:,}', block["busStops"]["districtsWithNone"]))
    if block.get("airport"):
        x, q = block["airport"]["busiest"][0], block["airport"]["quietest"][-1]
        print("  airport     busiest %s at %.0f/hr, quietest %s at %.0f/hr" % (x["hour"], x["perHour"], q["hour"], q["perHour"]))
    if block.get("buses"):
        print("  bus speed   median %.1f km/h over %s readings" % (block["buses"]["medianKph"], f'{block["buses"]["observations"]:,}'))
    if block.get("professions"):
        print("  professions %d recognised titles" % block["professions"]["recognised"])
    if block.get("heritage"):
        print("  heritage    %d site(s)" % block["heritage"]["sites"])
    con.close()

    if not a.no_pulse:
        if not os.path.exists(PULSE):
            print("  no pulse.json"); return
        p = json.load(io.open(PULSE, encoding="utf-8"))
        p["cityLife"] = block
        io.open(PULSE, "w", encoding="utf-8", newline="").write(json.dumps(p, ensure_ascii=False, indent=1))
        print("  pulse.json <- cityLife")


if __name__ == "__main__":
    main()
