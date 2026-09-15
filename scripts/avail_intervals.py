"""Developer availability as intervals: when each unit was first and last on a sheet, at what prices, and when it left.

Data Spine Phase 2 (13 Sep 2026), the availability half of "two dates on every register row". The board shows each
project's newest reading; the history of what was available on which day lived only in the sheet files, and "Beyond
released eight three-beds in nine days" had to be recomputed by hand. This rebuilds, from every sheet in data/avail:

  lk_avail_units   one row per unit a developer has listed (developer, project, unit_id)
                     unit_type, sqft, view         from the latest sheet that lists it
                     first_seen / last_seen       sheet dates  - valid time: when the developer said it was available
                     first_price / last_price, price_changes
                     sheets_seen                  how many readings of the project listed it
                     left_after                   date of the first later sheet of the SAME project that no longer lists
                                                  it (sold, withdrawn or re-released - a sheet cannot say which)
                     id_break_after               set instead when that later sheet shares NO unit ids with the one
                                                  before: the developer rewrote its ids; the unit's fate is unknown
                     recorded_first / recorded_last   when those sheets reached us (file time) - recorded time
  lk_avail_types   the same for broker packs that give counts per unit type instead of unit rows

Readings the volume check holds (data/avail/_held.json) are left out, so a brochure cannot end a real unit's interval.
The tables are rebuilt whole each run, and every rebuild is a DuckLake snapshot, so an earlier state stays queryable.
Usage: python scripts/avail_intervals.py        Exit 0 = rebuilt; 1 = error.
"""
import datetime as dt, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lake  # noqa: E402
from build_avail_index import held_readings  # noqa: E402

AVAIL = os.path.join(ROOT, "data", "avail")
SHEET_RX = re.compile(r"([a-z0-9]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$")


def readings():
    """[(developer, project, sheet_date, verified, sheet_file, recorded_at, units{id: row}, types{type: n})] oldest first."""
    held = held_readings()
    merged = {}
    for p in glob.glob(os.path.join(AVAIL, "*.json")):
        b = os.path.basename(p)
        m = SHEET_RX.match(b)
        if b.startswith("_") or not m:
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        rec = dt.datetime.fromtimestamp(os.path.getmtime(p)).replace(microsecond=0)
        for pr in d.get("projects") or []:
            proj = pr.get("p")
            if not proj or (b, proj) in held or not (pr.get("units") or pr.get("types")):
                continue
            slot = merged.setdefault((m.group(1), proj, b), {"date": m.group(2), "verified": not m.group(3), "rec": rec,
                                                            "units": {}, "types": {}})
            for u in pr.get("units") or []:
                if isinstance(u, (list, tuple)) and u:
                    slot["units"][str(u[0])] = u
            for t in pr.get("types") or []:
                slot["types"][str(t.get("t"))] = int(t.get("n") or 0)
    out = [(dev, proj, s["date"], s["verified"], sheet, s["rec"], s["units"], s["types"]) for (dev, proj, sheet), s in merged.items()]
    return sorted(out, key=lambda r: (r[0], r[1], r[2], r[3]))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build():
    units, types = {}, {}
    by_project = {}
    for dev, proj, date, verified, sheet, rec, us, ts in readings():
        by_project.setdefault((dev, proj), []).append((date, sheet, rec, us, ts))
    for (dev, proj), rs in by_project.items():
        for i, (date, sheet, rec, us, ts) in enumerate(rs):
            for uid, u in us.items():
                price = num(u[3]) if len(u) > 3 else None
                k = (dev, proj, uid)
                row = units.get(k)
                if row is None:
                    row = units[k] = {"first_seen": date, "first_price": price, "recorded_first": rec, "price_changes": 0,
                                      "sheets_seen": 0, "last_price": price}
                if price is not None and row["last_price"] is not None and price != row["last_price"]:
                    row["price_changes"] += 1
                row.update(last_seen=date, last_price=price if price is not None else row["last_price"], recorded_last=rec,
                           unit_type=u[1] if len(u) > 1 else None, sqft=num(u[2]) if len(u) > 2 else None,
                           view=u[4] if len(u) > 4 else None, left_after=None, id_break_after=None)
                row["sheets_seen"] += 1
                row["_last_index"] = i
            for t, n in ts.items():
                k = (dev, proj, t)
                row = types.setdefault(k, {"first_seen": date, "first_n": n, "recorded_first": rec, "readings": 0})
                row.update(last_seen=date, last_n=n, recorded_last=rec)
                row["readings"] += 1
        # A unit absent from a LATER reading of its project left it - unless that reading shares no unit ids at all with the
        # one before, which is the developer changing how ids are written, not every unit selling at once (W Residences,
        # 7 -> 9 Sep 2026: 52 ids on one sheet, 29 different ids on the next, zero in common).
        id_break = {i + 1 for i in range(len(rs) - 1) if rs[i][3] and rs[i + 1][3] and not (set(rs[i][3]) & set(rs[i + 1][3]))}
        for (d2, p2, uid), row in units.items():
            if (d2, p2) == (dev, proj) and row["_last_index"] < len(rs) - 1:
                nxt = row["_last_index"] + 1
                row["left_after"] = None if nxt in id_break else rs[nxt][0]
                row["id_break_after"] = rs[nxt][0] if nxt in id_break else None
    return units, types


def main():
    units, types = build()
    con = lake.connect(read_only=False)
    urows = [(d, p, u, r.get("unit_type"), r.get("sqft"), r.get("view"), r["first_seen"], r["last_seen"], r["first_price"],
              r["last_price"], r["price_changes"], r["sheets_seen"], r["left_after"], r.get("id_break_after"), r["recorded_first"], r["recorded_last"])
             for (d, p, u), r in units.items()]
    trows = [(d, p, t, r["first_seen"], r["last_seen"], r["first_n"], r["last_n"], r["readings"], r["recorded_first"], r["recorded_last"])
             for (d, p, t), r in types.items()]

    def body():
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("""create or replace table lk_avail_units (developer varchar, project varchar, unit_id varchar,
                unit_type varchar, sqft double, view varchar, first_seen date, last_seen date, first_price double, last_price double,
                price_changes integer, sheets_seen integer, left_after date, id_break_after date, recorded_first timestamp, recorded_last timestamp)""")
            if urows:
                con.executemany("insert into lk_avail_units values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", urows)
            con.execute("""create or replace table lk_avail_types (developer varchar, project varchar, unit_type varchar,
                first_seen date, last_seen date, first_n integer, last_n integer, readings integer,
                recorded_first timestamp, recorded_last timestamp)""")
            if trows:
                con.executemany("insert into lk_avail_types values (?,?,?,?,?,?,?,?,?,?)", trows)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    lake.retry(body, "avail intervals")
    left = sum(1 for r in units.values() if r["left_after"] is not None)
    broke = sum(1 for r in units.values() if r.get("id_break_after"))
    listed = len(units) - left - broke
    moved = sum(1 for r in units.values() if r["price_changes"])
    print("availability intervals: %d units (%d still listed, %d left a later sheet, %d behind an id-format change, %d re-priced), %d type rows"
          % (len(units), listed, left, broke, moved, len(types)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("avail intervals error:", str(e)[:300])
        sys.exit(1)
