"""Two dates on every register row: when it happened, and when we learned it (Data Spine Phase 2, 13 Sep 2026).

The DLD register back-fills. A day's transactions keep arriving for days after it - on 25 Aug the same window had about 3%
more rows when pulled again that afternoon - and each daily fetch rewrites a 56-day window file. Until now nothing kept the
earlier readings as data: a figure quoted in a morning brief could not be rebuilt once a later pull had moved it, and a
register correction (a project name filled in, a transaction withdrawn) left no trace.

Two SERIES, because the files come in two shapes that must never be compared row for row (measured 13 Sep 2026):
  window   fetch_dld.py's daily API windows. One row per TRANSACTION_NUMBER, timestamps with a 'T'. Consecutive pulls
           agree exactly on every shared number (0-1 differing rows in ~31,000), so a difference is a real change.
  export   the portal's manual CSV and year-to-date extracts. A multi-unit deal (a portfolio mortgage, say) is several
           rows under one number, timestamps have a space. Comparing these against the API windows made nearly every row
           look changed and every portfolio look re-priced.
Within a series, a version is keyed by the transaction number plus its ordinal among rows sharing the number.

Contract: a window file with under 85% of the rows of the last window file loaded for the same register is HELD, not
loaded - the 2 Sep manual pull had 25,009 rows against ~31,800 and would have "vanished" 7,264 real transactions.

Tables (lake-native, data/lake - see lake.py):
  lk_dld_transactions  the register's columns as text, plus series, txn_key (number#ordinal), happened_at (valid time),
                       row_hash, recorded_from (the pull that first carried this version: recorded time), recorded_to (the
                       pull that replaced or dropped it; null = current), vanished, source_file
  lk_dld_rents         the same for rent contracts, keyed by row fingerprint (the register publishes no contract id): a late
                       contract appears as a new row
  lk_version_loads     one row per file: series, status (loaded | held), rows, window, new, closed, vanished
  lk_vanish_holds      the transaction keys a vanish-held pull lacked, so the next pull can be checked against them
Views: dld_transactions_now / dld_rents_now, and transactions / rents in the column shape the old naj.duckdb had (window
series where it covers the date, export series before that), so build_avail_drill.py reads current data.

"What did we know at 09:00 on 25 Aug about 24 Aug?":
  select count(*) from lk_dld_transactions where series = 'window' and happened_at::date = '2026-08-24'
    and recorded_from <= timestamp '2026-08-25 09:00' and (recorded_to is null or recorded_to > timestamp '2026-08-25 09:00')

Usage: python scripts/register_versions.py [--only transactions|rents] [--reload]
Exit 0 = loaded or nothing new; 4 = a window file newly held (printed as HELD); 1 = error.
"""
import argparse, datetime as dt, glob, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import lake  # noqa: E402

DATA = os.path.join(ROOT, "data")
FILE_RX = re.compile(r"^(transactions|rents)-(ytd-)?(\d{4}-\d{2}-\d{2})(-api)?\.csv$")
SHRINK_HOLD = 0.85
VANISH_AGREE = 0.8                     # a pull after a vanish hold loads only if at least this share of its vanishes were held too
DATE_COLS = {"transactions": ["INSTANCE_DATE"], "rents": ["REGISTRATION_DATE", "START_DATE", "END_DATE"]}


def pulled_files(kind):
    out = []
    for p in glob.glob(os.path.join(DATA, "%s-*.csv" % kind)):
        m = FILE_RX.match(os.path.basename(p))
        if m and m.group(1) == kind:
            out.append((dt.datetime.fromtimestamp(os.path.getmtime(p)).replace(microsecond=0), p, bool(m.group(2))))
    return sorted(out)


def header(con, path):
    return [d[0] for d in con.execute("select * from read_csv('%s', header=true, all_varchar=true) limit 0" % lake._p(path)).description]


def ensure_tables(con, tx_cols, rent_cols):
    con.execute("""create table if not exists lk_version_loads (
        register varchar, series varchar, status varchar, source_file varchar, recorded_at timestamp, loaded_at timestamp,
        rows bigint, window_from date, window_to date, new_versions bigint, closed_versions bigint, vanished bigint, note varchar)""")
    con.execute("create table if not exists lk_vanish_holds (source_file varchar, txn_key varchar)")
    if tx_cols:
        con.execute("create table if not exists lk_dld_transactions (%s, series varchar, txn_key varchar, happened_at timestamp, "
                    "row_hash varchar, recorded_from timestamp, recorded_to timestamp, vanished boolean, source_file varchar)"
                    % ", ".join('"%s" varchar' % c for c in tx_cols))
    if rent_cols:
        con.execute("create table if not exists lk_dld_rents (%s, happened_at timestamp, row_hash varchar, "
                    "recorded_from timestamp, recorded_to timestamp, source_file varchar)"
                    % ", ".join('"%s" varchar' % c for c in rent_cols))


def normalised(cols, kind):
    """Column expressions for hashing: dates lose the T/space difference, everything is trimmed."""
    out = []
    for c in cols:
        e = 'trim(coalesce("%s", \'\'))' % c
        if c in DATE_COLS[kind]:
            e = "replace(%s, 'T', ' ')" % e
        out.append(e)
    return "md5(concat_ws(chr(31), %s))" % ", ".join(out)


def last_loaded_rows(con, register, series):
    r = con.execute("select rows from lk_version_loads where register = ? and series = ? and status = 'loaded' "
                    "order by recorded_at desc limit 1", [register, series]).fetchone()
    return r[0] if r else None


def hold(con, register, series, name, recorded_at, rows, prev):
    note = "%s rows against %s in the last %s file loaded" % (f"{rows:,}", f"{prev:,}", series)
    lake.retry(lambda: con.execute("insert into lk_version_loads values (?, ?, 'held', ?, ?, now(), ?, null, null, 0, 0, 0, ?)",
                                   [register, series, name, recorded_at, rows, note]), "hold " + name)
    print("HELD %s %s: %s" % (register, name, note))


def load_transactions(con, recorded_at, path, cols, ytd):
    name = os.path.basename(path)
    collist = ", ".join('"%s"' % c for c in cols)
    con.execute("""create or replace temp table stage as
        select %s, try_cast(replace("INSTANCE_DATE", 'T', ' ') as timestamp) as happened_at, %s as row_hash
        from read_csv('%s', header=true, all_varchar=true)""" % (collist, normalised(cols, "transactions"), lake._p(path)))
    rows, repeated, spaced = con.execute("""select count(*), count(*) - count(distinct "TRANSACTION_NUMBER"),
        count(*) filter (where "INSTANCE_DATE" like '% %') from stage""").fetchone()
    series = "export" if (ytd or repeated or spaced) else "window"
    if series == "window":
        prev = last_loaded_rows(con, "transactions", "window")
        if prev and rows < SHRINK_HOLD * prev:
            hold(con, "transactions", "window", name, recorded_at, rows, prev)
            return True
    con.execute("""create or replace temp table stage as select *, "TRANSACTION_NUMBER" ||
        case when rn > 1 then '#' || rn else '' end as txn_key from (
            select *, row_number() over (partition by "TRANSACTION_NUMBER" order by row_hash) rn from stage)""")
    wmin, wmax = con.execute("select min(happened_at)::date, max(happened_at)::date from stage").fetchone()
    # The first day of a window is only partly covered - the fetch's lower bound cuts through it - and a rolling window moves
    # that day forward each morning. Judged as a full day, it "vanished" 400-600 real transactions per pull (measured
    # 13 Sep 2026: nearly every vanish sat on window_from). Changes and vanishes are judged from the second day onward.
    judge_from = wmin + dt.timedelta(days=1) if series == "window" else wmin
    scope = "series = ? and recorded_to is null and happened_at::date between ? and ?"

    if series == "window":
        # Second window contract. On 9 Sep the pull silently lacked 427 transactions that were all back on 10 Sep - the row
        # count moved 2%, so the shrink rule could not see it, and the morning pulse read 3 Sep as 754 sales instead of 798.
        # Genuine withdrawals run at 0-3 a day. A pull whose vanishes exceed 0.2% of the overlap (at least 50 rows) is held.
        # The hold releases when the next pull agrees: its own vanishes fall under the limit, or at least 80% of them are
        # transactions the held pull lacked too. Until 14 Sep a file straight after a vanish hold loaded whatever it lacked -
        # that morning's pull was held for 1,496 missing sales that the gateway's unsorted paging had skipped, and the next
        # pull would have closed them all had it skipped them again.
        missing = "from lk_dld_transactions t where %s and not exists (select 1 from stage s where s.txn_key = t.txn_key)" % scope
        overlap, gone = con.execute("""select count(*), count(*) filter (where not exists (select 1 from stage s where s.txn_key = t.txn_key))
            from lk_dld_transactions t where %s""" % scope, [series, judge_from, wmax]).fetchone()
        if overlap and gone > max(50, 0.002 * overlap):
            last = con.execute("select status, note, source_file from lk_version_loads where register = 'transactions' and series = 'window' "
                               "order by recorded_at desc limit 1").fetchone()
            agree = 0.0
            if last and last[0] == "held" and (last[1] or "").startswith("vanish"):
                agree = con.execute("select count(*) %s and t.txn_key in (select txn_key from lk_vanish_holds where source_file = ?)" % missing,
                                    [series, judge_from, wmax, last[2]]).fetchone()[0] / gone
            if agree < VANISH_AGREE:
                note = "vanish: %s of %s known transactions missing from this pull (released if the next pull agrees)" % (f"{gone:,}", f"{overlap:,}")
                if agree:
                    note += "; only %.0f%% of them were missing from %s too" % (100 * agree, last[2])

                def held():
                    con.execute("BEGIN TRANSACTION")
                    try:
                        con.execute("delete from lk_vanish_holds where source_file = ?", [name])
                        con.execute("insert into lk_vanish_holds select ?, t.txn_key %s" % missing, [name, series, judge_from, wmax])
                        con.execute("insert into lk_version_loads values ('transactions', 'window', 'held', ?, ?, now(), ?, ?, ?, 0, 0, ?, ?)",
                                    [name, recorded_at, rows, wmin, wmax, gone, note])
                        con.execute("COMMIT")
                    except Exception:
                        con.execute("ROLLBACK")
                        raise
                lake.retry(held, "hold " + name)
                print("HELD transactions %s: %s" % (name, note))
                return True
            print("  %s: %s vanishes agree with the held %s (%.0f%%) - loading" % (name, f"{gone:,}", last[2], 100 * agree))

    def body():
        con.execute("BEGIN TRANSACTION")
        try:
            closed = con.execute("""select count(*) from lk_dld_transactions t where %s and not exists
                (select 1 from stage s where s.txn_key = t.txn_key and s.row_hash = t.row_hash)""" % scope,
                                 [series, judge_from, wmax]).fetchone()[0]
            vanished = con.execute("""select count(*) from lk_dld_transactions t where %s and not exists
                (select 1 from stage s where s.txn_key = t.txn_key)""" % scope, [series, judge_from, wmax]).fetchone()[0]
            con.execute("""update lk_dld_transactions set recorded_to = ?,
                    vanished = not exists (select 1 from stage s where s.txn_key = lk_dld_transactions.txn_key)
                where %s and not exists (select 1 from stage s where s.txn_key = lk_dld_transactions.txn_key
                                         and s.row_hash = lk_dld_transactions.row_hash)""" % scope,
                        [recorded_at, series, judge_from, wmax])
            new = con.execute("""select count(*) from stage s where not exists (select 1 from lk_dld_transactions t
                where t.series = ? and t.recorded_to is null and t.txn_key = s.txn_key and t.row_hash = s.row_hash)""",
                              [series]).fetchone()[0]
            con.execute("""insert into lk_dld_transactions
                select %s, ?, txn_key, happened_at, row_hash, ?, null, false, ? from stage s
                where not exists (select 1 from lk_dld_transactions t where t.series = ? and t.recorded_to is null
                                  and t.txn_key = s.txn_key and t.row_hash = s.row_hash)""" % collist,
                        [series, recorded_at, name, series])
            con.execute("insert into lk_version_loads values ('transactions', ?, 'loaded', ?, ?, now(), ?, ?, ?, ?, ?, ?, ?)",
                        [series, name, recorded_at, rows, wmin, wmax, new, closed, vanished,
                         ("%d rows share a number (multi-unit deals)" % repeated) if repeated else ""])
            con.execute("COMMIT")
            return new, closed, vanished
        except Exception:
            con.execute("ROLLBACK")
            raise
    new, closed, vanished = lake.retry(body, "versions " + name)
    print("  %-34s %-6s pulled %s  rows %6d  window %s..%s  new %6d  closed %5d  vanished %4d"
          % (name, series, recorded_at, rows, wmin, wmax, new, closed, vanished))
    return False


def load_rents(con, recorded_at, path, cols, ytd):
    name = os.path.basename(path)
    collist = ", ".join('"%s"' % c for c in cols)
    con.execute("""create or replace temp table stage as
        select distinct %s, try_cast(replace("REGISTRATION_DATE", 'T', ' ') as timestamp) as happened_at, %s as row_hash
        from read_csv('%s', header=true, all_varchar=true)""" % (collist, normalised(cols, "rents"), lake._p(path)))
    rows = con.execute("select count(*) from stage").fetchone()[0]
    prev = last_loaded_rows(con, "rents", "window")
    if prev and rows < SHRINK_HOLD * prev:
        hold(con, "rents", "window", name, recorded_at, rows, prev)
        return True
    wmin, wmax = con.execute("select min(happened_at)::date, max(happened_at)::date from stage").fetchone()

    def body():
        con.execute("BEGIN TRANSACTION")
        try:
            new = con.execute("select count(*) from stage s where not exists (select 1 from lk_dld_rents r where r.row_hash = s.row_hash)").fetchone()[0]
            con.execute("""insert into lk_dld_rents select %s, happened_at, row_hash, ?, null, ? from stage s
                where not exists (select 1 from lk_dld_rents r where r.row_hash = s.row_hash)""" % collist, [recorded_at, name])
            con.execute("insert into lk_version_loads values ('rents', 'window', 'loaded', ?, ?, now(), ?, ?, ?, ?, 0, 0, '')",
                        [name, recorded_at, rows, wmin, wmax, new])
            con.execute("COMMIT")
            return new
        except Exception:
            con.execute("ROLLBACK")
            raise
    new = lake.retry(body, "versions " + name)
    print("  %-34s pulled %s  rows %6d  window %s..%s  new %6d" % (name, recorded_at, rows, wmin, wmax, new))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["transactions", "rents"])
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args()
    con = lake.connect(read_only=False)
    tx = pulled_files("transactions") if a.only in (None, "transactions") else []
    rn = pulled_files("rents") if a.only in (None, "rents") else []
    if a.reload:
        for t in ("lk_dld_transactions", "lk_dld_rents", "lk_version_loads"):
            lake.retry(lambda t=t: con.execute("drop table if exists %s" % t), "reload")
        for v in ("dld_transactions_now", "transactions", "dld_rents_now", "rents"):
            lake.retry(lambda v=v: con.execute("drop view if exists %s" % v), "reload")
    tx_cols = header(con, tx[-1][1]) if tx else None
    rent_cols = header(con, rn[-1][1]) if rn else None
    lake.retry(lambda: ensure_tables(con, tx_cols, rent_cols), "tables")
    done = {r[0] for r in con.execute("select source_file from lk_version_loads").fetchall()}

    new_holds = 0
    for kind, files, cols, loader in (("transactions", tx, tx_cols, load_transactions), ("rents", rn, rent_cols, load_rents)):
        todo = [(t, p, y) for t, p, y in files if os.path.basename(p) not in done]
        print("%s: %d files, %d not yet loaded" % (kind, len(files), len(todo)))
        for t, p, y in todo:
            if header(con, p) != cols:
                print("  %s: columns differ from the register's current shape - skipped, needs a look" % os.path.basename(p))
                continue
            new_holds += 1 if loader(con, t, p, cols, y) else 0

    if tx_cols:
        cl = ", ".join('"%s"' % c for c in tx_cols)
        cover = ("(select min(window_from) from lk_version_loads where register = 'transactions' and series = 'window' "
                 "and status = 'loaded' and recorded_at = (select max(recorded_at) from lk_version_loads where register = "
                 "'transactions' and series = 'window' and status = 'loaded'))")
        now = ("select * from lk_dld_transactions where recorded_to is null and (series = 'window' or "
               "happened_at::date < coalesce(%s, date '9999-12-31'))" % cover)
        for v in ("create or replace view dld_transactions_now as %s" % now,
                  # naj.duckdb counted one row per transaction number; the legacy shape keeps that (first ordinal only)
                  "create or replace view transactions as select %s from (%s) where txn_key not like '%%#%%'" % (cl, now)):
            lake.retry(lambda v=v: con.execute(v), "views")
        cur, ver = con.execute("select (select count(*) from dld_transactions_now), count(*) from lk_dld_transactions").fetchone()
        print("transactions: %d current, %d versions kept" % (cur, ver))
    if rent_cols:
        cl = ", ".join('"%s"' % c for c in rent_cols)
        for v in ("create or replace view dld_rents_now as select * from lk_dld_rents where recorded_to is null",
                  "create or replace view rents as select %s from lk_dld_rents where recorded_to is null" % cl):
            lake.retry(lambda v=v: con.execute(v), "views")
        print("rents: %d rows known" % con.execute("select count(*) from lk_dld_rents").fetchone()[0])
    return 4 if new_holds else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("register versions error:", str(e)[:300])
        sys.exit(1)
