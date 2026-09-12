"""City facts for her morning feed - Dubai as a place to live, not only a market to trade.

Her five angles have all been demand: prices, volumes, off-plan share, yields. Every broker in Dubai
posts the same numbers from the same register. What the government pull adds is the city itself, and
the strongest of it is not a statistic anyone publishes - it is a JOIN. The metro register has 55
stations with coordinates; her board has 41 districts with centroids. Nobody else holds both, so
nobody else can say which of the areas she sells actually has a station near it.

Only datasets that passed the realness gate are read, and only through v_gov_usable. The staging
environment serves some datasets with the values scrambled, and one of those reaching her feed would
have her posting a number that was never true.

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


def usable(con, dataset):
    """True only if the dataset landed AND passed the realness gate."""
    r = con.execute("select count(*) from v_gov_usable where dataset like ?", [dataset + "%"]).fetchone()
    return bool(r and r[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pulse", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(DB, read_only=True)
    block = {"asOf": dt.date.today().isoformat(),
             "source": "Dubai Data (DDA) open datasets, joined to the Najma district board",
             "caution": "structural facts. Station locations and hourly airport patterns do not move "
                        "week to week, so these are safe to state without a fresh pull.",
             "basedOn": []}

    # 1. METRO ACCESS BY DISTRICT - the join nobody else can make.
    if usable(con, "rta_metro_stations"):
        near = con.execute(f"""
            with s as (select location_name_english nm, line_name ln,
                              cast(station_location_longitude as double) lon,
                              cast(station_location_latitude as double) lat
                       from gov_rta__metro_stations
                       where try_cast(station_location_longitude as double) is not null),
                 d as (select name, slug, lon, lat from district where lon is not null),
                 j as (select d.name, d.slug, s.nm, s.ln, {KM} km from d cross join s),
                 r as (select *, row_number() over (partition by slug order by km) rn from j)
            select name, nm, ln, round(km, 1) from r where rn = 1 order by km""").fetchall()
        served = [x for x in near if x[3] <= 2.0]
        far = [x for x in near if x[3] > 5.0]
        block["metro"] = {
            "stations": con.execute("select count(*) from gov_rta__metro_stations").fetchone()[0],
            "byLine": dict(con.execute("select line_name, count(*) from gov_rta__metro_stations "
                                       "group by 1 order by 2 desc").fetchall()),
            "districtsMeasured": len(near),
            "withinWalk2km": len(served),
            "beyond5km": len(far),
            "closest": [{"district": x[0], "station": x[1], "line": x[2], "km": x[3]} for x in near[:8]],
            "furthest": [{"district": x[0], "station": x[1], "km": x[3]} for x in near[-8:]],
            "oldestStationOpened": str(con.execute("select min(try_cast(station_opening_date as date)) "
                                                   "from gov_rta__metro_stations").fetchone()[0]),
        }
        block["basedOn"].append("rta_metro_stations")

    # 2. THE AIRPORT'S OWN RHYTHM - relatable to anyone who lives here, and in no property feed.
    if usable(con, "dans_e_dxb_hourly_departure_throughput"):
        rows = con.execute("""select period, round(avg(cast(number as double)), 1) avg_per_hour
                              from gov_dans__e_dxb_hourly_departure_throughput
                              where try_cast(number as double) is not null
                              group by 1 order by avg_per_hour desc""").fetchall()
        if rows:
            block["airport"] = {
                "airport": "DXB",
                "measure": "average departures per hour band",
                "busiest": [{"hour": r[0], "perHour": r[1]} for r in rows[:3]],
                "quietest": [{"hour": r[0], "perHour": r[1]} for r in rows[-3:]],
                "observations": con.execute("select count(*) from gov_dans__e_dxb_hourly_departure_throughput").fetchone()[0],
            }
            block["basedOn"].append("dans_e_dxb_hourly_departure_throughput")

    # 3. HOW FAST THE CITY ACTUALLY MOVES.
    if usable(con, "rta_average_speed_per_line_buses"):
        cols = [d[0] for d in con.execute("select * from gov_rta__average_speed_per_line_buses limit 1").description]
        spd = next((x for x in cols if "speed" in x.lower()), None)
        line = next((x for x in cols if "line" in x.lower() or "route" in x.lower()), None)
        if spd and line:
            rows = con.execute(f'''select "{line}" ln, round(avg(try_cast("{spd}" as double)), 1) kph
                                   from gov_rta__average_speed_per_line_buses
                                   where try_cast("{spd}" as double) between 1 and 120
                                   group by 1 having count(*) >= 5 order by kph''').fetchall()
            if rows:
                # Lead with the median. The raw column runs 0 to 201 km/h, so any single line's mean is
                # fragile; a median across 53,319 observations is not, and "Dubai buses move at 18 km/h"
                # is the more honest statement as well as the better one.
                mid = con.execute('select round(median(try_cast("%s" as double)), 1), '
                                  'round(avg(try_cast("%s" as double)), 1), count(*) '
                                  'from gov_rta__average_speed_per_line_buses '
                                  'where try_cast("%s" as double) between 1 and 120' % (spd, spd, spd)).fetchone()
                block["buses"] = {"measure": "average speed in km/h",
                                  "medianKph": mid[0], "meanKph": mid[1], "observations": mid[2],
                                  "slowest": [{"line": r[0], "kph": r[1]} for r in rows[:4]],
                                  "fastest": [{"line": r[0], "kph": r[1]} for r in rows[-4:]],
                                  "linesMeasured": len(rows),
                                  "note": "readings outside 1-120 km/h are excluded; the raw column "
                                          "contains values up to 201"}
                block["basedOn"].append("rta_average_speed_per_line_buses")

    # 4. WHO THE CITY LICENSES - a list, not a count of people, so say so.
    if usable(con, "gdrfa_profession"):
        block["professions"] = {
            "recognised": con.execute("select count(distinct professiondescen) from gov_gdrfa__profession").fetchone()[0],
            "note": "recognised occupation titles in the residency register, not a count of residents",
        }
        block["basedOn"].append("gdrfa_profession")

    # 5. OLD DUBAI. Visitor counts are historical, so the year is carried with the figure.
    if usable(con, "dm_heritage_places"):
        rows = con.execute("""select heritage_location, max(year_visited) yr,
                                     sum(try_cast(number_of_visitors as double)) v
                              from gov_dm__heritage_places group by 1
                              having v > 0 order by v desc limit 5""").fetchall()
        if rows:
            block["heritage"] = {"sites": con.execute("select count(distinct heritage_location) "
                                                      "from gov_dm__heritage_places").fetchone()[0],
                                 "mostVisited": [{"site": r[0], "throughYear": r[1], "visitors": int(r[2])} for r in rows]}
            block["basedOn"].append("dm_heritage_places")

    print("cityLife block: %d sections from %d dataset(s)" % (len([k for k in block if k not in
          ("asOf", "source", "caution", "basedOn")]), len(block["basedOn"])))
    m = block.get("metro")
    if m:
        print("  metro     %d stations; %d of %d districts within 2 km, %d beyond 5 km"
              % (m["stations"], m["withinWalk2km"], m["districtsMeasured"], m["beyond5km"]))
    if block.get("airport"):
        b = block["airport"]["busiest"][0]; q = block["airport"]["quietest"][-1]
        print("  airport   busiest %s at %.0f/hr, quietest %s at %.0f/hr" % (b["hour"], b["perHour"], q["hour"], q["perHour"]))
    if block.get("buses"):
        bb = block["buses"]
        print("  buses     median %.1f km/h over %s readings, %d lines; slowest %s at %.1f"
              % (bb["medianKph"], f'{bb["observations"]:,}', bb["linesMeasured"],
                 bb["slowest"][0]["line"], bb["slowest"][0]["kph"]))
    if block.get("professions"):
        print("  professions %d recognised titles" % block["professions"]["recognised"])
    if block.get("heritage"):
        print("  heritage  %d sites" % block["heritage"]["sites"])
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
