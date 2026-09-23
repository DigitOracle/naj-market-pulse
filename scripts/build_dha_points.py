"""build_dha_points -- full-precision positions for DHA-licensed facilities, to repair the coarse ones.

Asked for on 23 Sep 2026 by the twin session, which holds the health amenity layer.

THE PROBLEM IT SOLVES. The DHA facility register (sheryan_facility_detail) ROUNDS latitude to two decimals while
keeping longitude in full - a single record reads lat 25.17, lon 55.150404. Two decimals, rounded, is +/-0.005 degrees,
about +/-555 m north-south, so seven in ten of the twin's health facilities are placed up to half a kilometre from their
door. (Written first as TRUNCATION, +/-1.1 km. Corrected 23 Sep 2026 after the question-bank session measured it and I
re-measured: of the coarse latitudes whose repair passes the guard, 1,026 equal the precise value ROUNDED and only 1
equals it floored-but-not-rounded - truncation would make every one equal the floor. Measured latitude error: median
276 m, p90 484 m, max 588 m.)

The professional register (dha_sheryan_professional_detail, landed 23 Sep) carries the SAME facility ids with latitude
intact: 77.6% of its positions run to twelve decimal places and only 2 of 6,002 are cut to two. So one register
lost the precision and the other kept it, and the facility id joins them.

    twin's register              this one
    25.07,     55.140743776856   ->   25.069541, 55.140744      IBN SINA SCIENTIFIC PHARMACY
    25.03,     55.279306551719   ->   25.028253, 55.279307      Widad Center For Disability
    25.19,     55.274271803812   ->   25.185405, 55.274272      A H T AESTHETIC MEDICAL CENTER

Longitude agrees to six decimals while latitude gains four - which is the signature of rounding one field, and the reason to
trust the join. Against the twin's own health filters it repairs 827 of 1,845 coarse positions (44.8%) and gives a
position to 24 of the 392 that had none.

THE GUARD, AND WHY IT IS A DISTANCE AND NOT A NAME. Of the 827 repairs, 826 move the point less than 1.1 km - well inside
what two-decimal rounding allows, and strong evidence the two ids mean the same place. Exactly one does not:

    id 3503718   facility register: Dubai Medical University Hospital
                 professional reg : Saudi German Hospital            28.4 km apart

That is an id pointing at two different hospitals, and applied blindly it would move a hospital across the city. Names
agree on only 49.6% of the repairs because the registers word branch names differently ("BR OF DM HEALTHCARE" and so
on), so a name test would throw away half the good rows to catch the one bad one. The distance test throws away one.

    CALLER MUST APPLY:  accept the precise point only when it is within ~1.15 km of the coarse one.

A SHARPER GUARD, NOT ADOPTED HERE (23 Sep 2026, measured by the question-bank session and confirmed): because only latitude
lost precision, a genuine repair keeps longitude identical to 6 dp. Across 1,551 accepted repairs, 1,537 agree on longitude
and 14 do not (58-630 m apart, longitude differing by up to 0.0023 deg - not one point recorded twice). All 6 distance
rejections also differ on longitude. "Longitude agrees AND distance <= 700 m" rejects 20 instead of 6, and 700 m clears the
588 m worst case. Adopting it changes which facilities are repaired, so it is Kendall's decision; guard_metres stays 1150.

The caller holds the coarse point, so the guard belongs there, not here - and it keeps working if a future pull
introduces another conflicting id.

NOT INCLUDED, deliberately: category, name, subcategory, contact details. The twin's amenities_official.py already
distinguishes hospital from pharmacy by licence subcategory and that logic took work. This file carries positions only.

    python scripts/build_dha_points.py   ->  data/board/_dha_precise_points.json
"""
import io, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod",
                   "dha__dha_sheryan_professional_detail-open-api.json")
OUT = os.path.join(ROOT, "data", "board", "_dha_precise_points.json")
# Dubai and a margin. The register uses (90.0, 90.0) as "position unknown" on 24,240 rows; a box rejects that
# without assuming 90/90 is the only sentinel it will ever use.
BOX = (24.5, 26.0, 54.5, 56.5)
NOTE = ("Full-precision lat/lon for DHA-licensed facilities, keyed by facility id, to repair positions the facility "
        "register rounded to two decimals of latitude (+/-0.005 deg, about +/-555 m; measured max 588 m). Longitude was never "
        "rounded, so on a genuine repair it agrees exactly - a free second test. CALLER MUST GUARD: "
        "accept a point only when it lies within ~1.15 km of the coarse one it replaces - id 3503718 carries two "
        "different hospitals across the two registers and is 28.4 km out. Positions only: no name, category or contact, "
        "because the caller's own category logic is better than anything derivable here.")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def idstr(v):
    """An id as a plain string. DuckDB hands these back as floats where the source column is double, and '7528994.0'
    joins to nothing. Third time this has cost us a join, so it is a function now."""
    if v is None:
        return None
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def points():
    rows = json.load(io.open(SRC, encoding="utf-8"))["results"]
    lo_lat, hi_lat, lo_lon, hi_lon = BOX
    out, seen_coarse = {}, 0
    for r in rows:
        # the register labels these x and y, but x holds LATITUDE and y holds LONGITUDE
        # xcoordinate holds LATITUDE and ycoordinate holds LONGITUDE - the register swaps them, and the
        # names say the opposite. Re-derived by three separate sessions on 23 Sep 2026.
        lat, lon = num(r.get("xcoordinate")), num(r.get("ycoordinate"))
        fid = idstr(r.get("facilityid"))
        if not (fid and lat and lon and lo_lat < lat < hi_lat and lo_lon < lon < hi_lon):
            continue
        if round(lat, 2) == lat:        # already coarse - carries nothing the caller does not have
            seen_coarse += 1
            continue
        out.setdefault(fid, [round(lat, 6), round(lon, 6)])
    return out, len(rows), seen_coarse


def main():
    pts, n_rows, coarse = points()
    doc = {"note": NOTE, "source": "dha/dha_sheryan_professional_detail-open-api", "facilities": len(pts),
           "guard_metres": 1150, "known_conflict": {"3503718": "Dubai Medical University Hospital vs Saudi German Hospital, 28.4 km"},
           "points": pts}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("%s professional rows -> %s facilities with a full-precision point" % (format(n_rows, ","), format(len(pts), ",")))
    print("%s rows skipped as already coarse" % format(coarse, ","))
    print("data/board/_dha_precise_points.json  (%.0f KB)" % (os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
