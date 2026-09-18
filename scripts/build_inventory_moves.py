"""What moved in a developer's own inventory, between one sheet and the next.

This is the one thing she has that no other broker in Dubai has. Everyone can quote the Land
Department: prices, volumes, off-plan share, yields. It is public, it is identical for everybody, and
it looks backwards. What the developer group gives her is different in kind - a DATED record of what
each developer claims is still available, captured from the primary source, accumulating week by week.

Two sheets from the same developer turn a snapshot into a movement, and a movement distinguishes two
things a single sheet cannot:

    a count that FELL   -> units were taken up
    a count that ROSE   -> the developer released more stock

Beyond, 24 August to 2 September: two-beds 84 to 81, three-beds 28 to 36. Three two-beds taken up
while eight three-beds were released. Nobody reading a price index can say that.

Writes `dev_unit_move` to the truth store and a compact block into public/pulse.json so the morning
feed can reach it. Movement is only computed where the SAME developer has two sheets - never inferred
from one.
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pulse", action="store_true", help="build the table, leave pulse.json alone")
    a = ap.parse_args()

    con = duckdb.connect(DB)

    # One row per developer+date+type. The hand-verified and auto-read copies of the same sheet carry
    # the same units, so count DISTINCT unit codes rather than rows - otherwise Imtiaz doubles.
    con.execute("""create or replace view v_dev_sheet_type as
        select developer, project, sheet_date, unit_type,
               count(distinct coalesce(unit_code, project || '|' || cast(price_aed as varchar))) units,
               round(min(price_aed)) from_aed, round(max(price_aed)) to_aed,
               round(avg(aed_per_sqft)) avg_psf
        from dev_sheet_unit
        group by 1, 2, 3, 4""")

    # Consecutive sheets per developer. lag() over the developer gives the previous date's count;
    # a type that appears in only one of the two sheets is a release or a sell-out, so coalesce to 0.
    con.execute("""create or replace table dev_unit_move as
        -- Per PROJECT: two sheets are comparable only for a project they both list. Arada's 11 Sep
        -- sheet was Inaura alone; compared at developer level it read every other project as sold out.
        with t as (select * from v_dev_sheet_type),
             dates as (select distinct developer, project, sheet_date from t),
             pairs as (select developer, project, sheet_date,
                              lag(sheet_date) over (partition by developer, project order by sheet_date) prev
                       from dates),
             -- Two sheets are comparable only where they describe THE SAME STOCK. W Residences at
             -- Dubai Harbour is one project and three towers, and every drop captured a different
             -- subset: 7 Sep towers 1-2, 9 Sep tower 3, 17 Sep towers 1-2 again. Compared by project
             -- that read as 22 one-beds "taken up" down to 11 in two days, and a 3-bed count RISING
             -- in the same two days - four phantom sales and a phantom release, and the morning
             -- feed was about to tell her followers half a tower sold. Nothing sold. The block field
             -- is identical across the towers, so the tower only survives in the unit code.
             --
             -- The rule is general, not a W Residences patch: real movement is the same units with
             -- some gone, so the two sheets must SHARE units. Zero overlap means a different tower,
             -- a partial document or a re-coded sheet - different stock, not a change in it.
             -- Type-level sheets carry no unit codes at all, so they keep the old comparison.
             coded as (select developer, project, sheet_date, unit_code from dev_sheet_unit
                       where unit_code is not null and trim(unit_code) <> ''),
             overlap as (select pr.developer, pr.project, pr.prev, pr.sheet_date,
                                count(distinct b.unit_code) shared,
                                (select count(*) from coded c1 where c1.developer = pr.developer
                                    and c1.project = pr.project and c1.sheet_date = pr.prev) coded_before,
                                (select count(*) from coded c2 where c2.developer = pr.developer
                                    and c2.project = pr.project and c2.sheet_date = pr.sheet_date) coded_after
                         from pairs pr
                         left join coded a on a.developer = pr.developer and a.project = pr.project
                                          and a.sheet_date = pr.prev
                         left join coded b on b.developer = pr.developer and b.project = pr.project
                                          and b.sheet_date = pr.sheet_date and b.unit_code = a.unit_code
                         where pr.prev is not null
                         group by 1, 2, 3, 4),
             p as (select pr.* from pairs pr
                   join overlap o on o.developer = pr.developer and o.project = pr.project
                                 and o.prev = pr.prev and o.sheet_date = pr.sheet_date
                   where pr.prev is not null
                     and (o.shared > 0 or o.coded_before = 0 or o.coded_after = 0)),
             types as (select distinct p.developer, p.project, p.prev, p.sheet_date, x.unit_type
                       from p join t x on x.developer = p.developer and x.project = p.project
                                      and x.sheet_date in (p.prev, p.sheet_date))
        select ty.developer, ty.project, ty.prev as from_date, ty.sheet_date as to_date, ty.unit_type,
               coalesce(a.units, 0) as units_before,
               coalesce(b.units, 0) as units_after,
               coalesce(b.units, 0) - coalesce(a.units, 0) as change,
               case when coalesce(b.units, 0) < coalesce(a.units, 0) then 'taken up'
                    when coalesce(b.units, 0) > coalesce(a.units, 0) then 'released'
                    else 'unchanged' end as movement,
               date_diff('day', ty.prev::date, ty.sheet_date::date) as days,
               b.from_aed, b.to_aed, b.avg_psf
        from types ty
        left join t a on a.developer = ty.developer and a.project = ty.project and a.sheet_date = ty.prev      and a.unit_type = ty.unit_type
        left join t b on b.developer = ty.developer and b.project = ty.project and b.sheet_date = ty.sheet_date and b.unit_type = ty.unit_type
        order by ty.developer, ty.project, ty.sheet_date, ty.unit_type""")

    n = con.execute("select count(*) from dev_unit_move").fetchone()[0]
    print("dev_unit_move: %d rows" % n)
    for r in con.execute("""select developer, project, from_date, to_date, unit_type, units_before, units_after, change, movement, days
                            from dev_unit_move where change <> 0 order by abs(change) desc limit 12""").fetchall():
        print("  %-10s %-26s %s -> %s  %-6s %3d -> %3d  %+d  %-8s %dd" % r)

    # Only developers with two sheets have movement; say so rather than implying we track everyone.
    cov = con.execute("""select count(distinct developer) from dev_sheet_unit""").fetchone()[0]
    tracked = con.execute("""select count(distinct developer) from dev_unit_move""").fetchone()[0]
    print("\n  developers on file: %d   with a second sheet, so with movement: %d" % (cov, tracked))

    if not a.no_pulse:
        if not os.path.exists(PULSE):
            print("  no pulse.json - table built, nothing pushed")
            con.close(); return
        pulse = json.load(io.open(PULSE, encoding="utf-8"))
        moves = [dict(zip(["developer", "project", "from", "to", "type", "before", "after", "change", "movement", "days"], r))
                 for r in con.execute("""select developer, project, from_date, to_date, unit_type, units_before, units_after,
                                                change, movement, days
                                         from dev_unit_move where change <> 0
                                         order by abs(change) desc limit 24""").fetchall()]
        latest = [dict(zip(["developer", "date", "units", "projects", "from_aed", "to_aed"], r))
                  for r in con.execute("""select developer, sheet_date,
                                                 count(distinct coalesce(unit_code, project || '|' || cast(price_aed as varchar))),
                                                 count(distinct project), round(min(price_aed)), round(max(price_aed))
                                          from dev_sheet_unit where status = 'current'
                                          group by 1, 2 order by 1""").fetchall()]
        pulse["developerInventory"] = {
            "source": "developer availability sheets captured from the DEVELOPER AVAILABILITY broker group",
            "basis": "what each developer CLAIMS is still available, on the date they said it",
            "caution": "a claim, not a register fact. A count that rises is a release, not a sale.",
            "asOf": dt.date.today().isoformat(),
            "developersOnFile": cov,
            "developersWithMovement": tracked,
            "current": latest,
            "moves": moves,
        }
        io.open(PULSE, "w", encoding="utf-8", newline="").write(json.dumps(pulse, ensure_ascii=False, indent=1))
        print("  pulse.json <- developerInventory (%d current, %d moves)" % (len(latest), len(moves)))
    con.close()


if __name__ == "__main__":
    main()
