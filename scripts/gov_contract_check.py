"""Contract on the Dubai Data governed-API feed: every landed dataset reconciles, or it is held.

Data Spine Phase 1 (13 Sep 2026). The governed API never serves a short last page: past the final record it wraps round to
record 1 and keeps serving full pages. 2,252,220 of 6,923,807 landed rows were repeats across 28 datasets, and the realness
gate rated them clean, because it looks for scrambled text, not for the same row twice. The pager and the loader were fixed
on 13 Sep. This check makes the class impossible to miss again, by reconciling numbers every run:

  rows_reported   what the pull landed (repeats included)             gov_dataset.rows_reported
  rows_loaded     what the loader kept after select distinct          gov_dataset.rows_loaded
  rows_in_table   what the table holds now                            count(*)
  rows_distinct   distinct rows in the table (full mode, weekly)      count of select distinct *

A dataset is HELD when
  - it landed rows but nothing was loaded,
  - the table no longer holds the count the register recorded,
  - duplicate rows reached the table (full mode), or
  - it loaded under 80% of its last accepted count (a shrinking register is a pull that stopped early until proven otherwise).
It is STALE (reported, not held) when the pull is older than 10 days, and OK-DEDUPLICATED when the source repeated rows and
the loader removed them. Held datasets drop out of v_gov_usable (gate_gov_realness.py reads v_gov_contract_holds), so nothing
downstream posts them. Every run is appended to gov_contract; nothing is overwritten.

Usage: python scripts/gov_contract_check.py [--full]
Exit 0 = no new hold; 4 = a dataset newly held (printed as HELD lines); 1 = error.
"""
import argparse, datetime as dt, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from contracts import FRESH_DAYS, GOV_CONTRACT_DDL, HOLDS_VIEW, SHRINK_HOLD, connect_store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="also scan every table for duplicate rows (weekly)")
    a = ap.parse_args()
    mode = "full" if a.full else "quick"
    run_id = dt.datetime.now().isoformat(timespec="seconds")

    con = connect_store()
    con.execute(GOV_CONTRACT_DDL)
    tables = {r[0] for r in con.execute("select table_name from information_schema.tables where table_schema='main'").fetchall()}
    rows = con.execute("""select key, table_name, materialised, pulled, rows_reported, rows_loaded
                          from gov_dataset where status = 'ok' order by key""").fetchall()
    last_accepted = dict(con.execute("""
        select key, rows_loaded from (
            select key, rows_loaded, row_number() over (partition by key order by run_id desc) rn
            from gov_contract where not held and rows_loaded is not null) where rn = 1""").fetchall())
    held_before = {r[0] for r in con.execute(
        "select key from gov_contract where held and run_id = (select max(run_id) from gov_contract)").fetchall()}

    out, counts = [], {"ok": 0, "ok-deduplicated": 0, "stale": 0, "held": 0}
    today = dt.date.today()
    for key, tn, mat, pulled, reported, loaded in rows:
        reported, loaded = int(reported or 0), (None if loaded is None else int(loaded))
        in_table = distinct = None
        if tn and tn in tables:
            in_table = con.execute('select count(*) from "%s"' % tn).fetchone()[0]
            if a.full and in_table:
                distinct = con.execute('select count(*) from (select distinct * from "%s")' % tn).fetchone()[0]
        repeats = (reported - loaded) if loaded is not None else None
        status, reason = "ok", ""

        if reported > 0 and (not mat or in_table in (None, 0) or not loaded):
            status, reason = "held", "landed %s rows but nothing was loaded" % f"{reported:,}"
        elif in_table is not None and loaded is not None and in_table != loaded:
            status, reason = "held", "table holds %s rows, the register recorded %s" % (f"{in_table:,}", f"{loaded:,}")
        elif distinct is not None and distinct < in_table:
            status, reason = "held", "%s duplicate rows reached the table" % f"{in_table - distinct:,}"
        elif key in last_accepted and loaded is not None and last_accepted[key] and loaded < SHRINK_HOLD * last_accepted[key]:
            status, reason = "held", "loaded %s rows, down from %s at the last accepted pull" % (f"{loaded:,}", f"{last_accepted[key]:,}")
        else:
            try:
                age = (today - dt.date.fromisoformat(str(pulled)[:10])).days
            except Exception:
                age = None
            if age is not None and age > FRESH_DAYS:
                status, reason = "stale", "pulled %d days ago" % age
            elif repeats:
                status, reason = "ok-deduplicated", "the source repeated %s rows; the loader removed them" % f"{repeats:,}"
        counts[status] += 1
        out.append((run_id, mode, key, tn, pulled, reported, loaded, in_table, distinct, repeats, status, reason, status == "held"))

    con.executemany("insert into gov_contract values (?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    con.execute(HOLDS_VIEW)
    con.close()

    new_holds = [r for r in out if r[12] and r[2] not in held_before]
    for r in out:
        if r[12]:
            print("%s %s: %s" % ("HELD" if r[2] not in held_before else "still held", r[2], r[11]))
    print("gov contract (%s): %d datasets - %d ok, %d ok after removing repeats, %d stale, %d held"
          % (mode, len(out), counts["ok"], counts["ok-deduplicated"], counts["stale"], counts["held"]))
    return 4 if new_holds else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("gov contract error:", e)
        sys.exit(1)
