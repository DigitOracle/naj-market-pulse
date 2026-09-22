"""dewa_moveins_<slug>.json -- meters connected per building, keyed by the twin's duid, under a disclosure floor.

A DEWA move-in is a meter connected in someone's name: the closest any Dubai register gets to occupancy, where sales say what
changed hands and Ejari says what was let. Already bound to the twin's duid at 14 m median, so it needs no identity work.

DISCLOSURE FLOOR, set by the twin session on 22 Sep 2026 and consistent with Kendall's rule of 17 Sep for the resident mix:
  * a building with fewer than MIN_MOVE_INS connections is not published at all - below that it is a household, not a pattern
    (11,998 of 17,080 bound buildings have exactly ONE connection: those are villas, and one date is one family's move-in day)
  * dates are coarsened to the MONTH, never the day
  * the residential/commercial split is DEWA's own and is labelled as such
The floor keeps 2,156 buildings of 17,080 (12.6%) but 199,840 connections of 219,089 (91.2%): it removes single-home buildings,
which is the intent, and keeps almost all of the signal.
"""
import sys

sys.path.insert(0, r"C:\Dev\naj-market-pulse\scripts")
from lake import connect  # noqa: E402
import build_district_cuts as bdc  # noqa: E402

MIN_MOVE_INS = 5
SQL = """
    select duid,
           any_value(entrance_comm_num)                    comm_num,
           count(*)                                        makani_points,
           sum(move_ins)                                   move_ins,
           sum(move_ins_2024)                              move_ins_2024,
           sum(move_ins_2025)                              move_ins_2025,
           sum(move_ins_2026)                              move_ins_2026,
           sum(residential)                                residential,
           sum(commercial)                                 commercial,
           strftime(min(try_cast(first_move_in as date)), '%Y-%m')  first_move_in_month,
           strftime(max(try_cast(last_move_in as date)),  '%Y-%m')  last_move_in_month,
           round(min(dist_m))                              nearest_entrance_m
    from lk_dewa_moveins_makani
    where duid is not null and entrance_comm_num = ?
    group by 1
    having sum(move_ins) >= {floor}
    order by move_ins desc""".replace("{floor}", str(MIN_MOVE_INS))
COLS = ("duid", "comm_num", "makani_points", "move_ins", "move_ins_2024", "move_ins_2025", "move_ins_2026",
        "residential", "commercial", "first_move_in_month", "last_move_in_month", "nearest_entrance_m")
NOTE = ("DEWA meters connected per building, keyed by duid (median 14 m from the building's anchor). "
        "A CONNECTION IS NOT A HOUSEHOLD: one home relet three times is three connections, so this cannot be divided by the "
        "unit count to make an occupancy rate. A building with no rows is NOT RECORDED, never 'empty'. "
        "Buildings with fewer than 5 connections are withheld entirely and dates are coarsened to the month, because below "
        "that a move-in date identifies a household rather than a pattern. The residential/commercial split is DEWA's own.")

con = connect()
kept = dropped = 0
for d in bdc.districts():
    if not d["comm"]:
        continue
    rows = con.execute(SQL, [d["comm"]]).fetchall()
    all_n = con.execute("""select count(*) from (select duid, sum(move_ins) mi from lk_dewa_moveins_makani
                           where duid is not null and entrance_comm_num = ? group by 1)""", [d["comm"]]).fetchone()[0]
    docs = [dict(zip(COLS, r)) for r in rows]
    doc = {"area": d["area"], "comm_num": d["comm"], "columns": list(COLS),
           "buildings_published": len(docs), "buildings_withheld_below_floor": all_n - len(docs),
           "disclosure_floor": MIN_MOVE_INS, "dates": "month", "note": NOTE, "buildings": docs}
    bdc.write("dewa_moveins", d["slug"], doc)
    kept += len(docs)
    dropped += all_n - len(docs)
    if docs:
        print("%-26s %5d buildings published, %5d withheld, %8s connections"
              % (d["slug"], len(docs), all_n - len(docs), format(sum(x["move_ins"] for x in docs), ",")))
print("\npublished %s buildings, withheld %s below the floor of %d" % (format(kept, ","), format(dropped, ","), MIN_MOVE_INS))
