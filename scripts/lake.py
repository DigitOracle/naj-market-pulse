"""The published Najma store: DuckLake 1.0 over Parquet, one dated version per publish (Data Spine Phase 2, 13 Sep 2026).

Why. data/graph/najma.duckdb is a single DuckDB file, and DuckDB lets one process hold it read-write while every other
process - readers included - waits or fails. graph_build holds it for minutes; on 9 Sep the 08:17 golden check failed
against that lock, and any Unreal or twin job that opens the file stops the chain. It is also overwritten in place: there
is no "what did the store say on Tuesday".

What. The file stays where the builders write (work in progress). After the golden gate passes, `publish` copies the
CHECKED data into a DuckLake store in one transaction, and that transaction is a numbered snapshot:

  data/lake/najma_catalog.sqlite   the catalogue (tables, schemas, snapshots) - SQLite, so several processes can attach
  data/lake/files/                 the data, as Parquet files

  published   every base table except gov_* (their clean rows are published as g_* tables instead - rows the realness
              gate rejected never leave the work-in-progress file), plus the v_* views recreated over the published tables
  checked     before commit: every former primary key is still unique (DuckLake has no constraints, so the contract
              checks it) and every copied table has the row count of its source; a violation rolls the publish back
  skipped     a table whose fingerprint (row count, xor and sum of row hashes) is unchanged since the last publish

Readers attach the lake read-only and are never blocked by a builder. Every publish is recoverable: `AT (VERSION => n)`
or `AT (TIMESTAMP => ...)` on any table, and `python scripts/lake.py status` lists the snapshots. Tested 13 Sep 2026 on
DuckDB 1.5.5: a second process reads while a writer is attached; two short writers interleave; a writer holding a long
open transaction makes another writer's commit fail with "database is locked", which is why writes here retry.

Usage:
  python scripts/lake.py publish [--note TEXT]     copy the checked store into a new snapshot (exit 4 = held, rolled back)
  python scripts/lake.py status                    snapshots, tables, size on disk
  python scripts/lake.py expire [--days 30]        drop snapshots older than N days and delete the files only they used
In code:  from lake import connect; con = connect()   # read-only, USE najma - unqualified table names just work
"""
import argparse, datetime as dt, hashlib, os, re, sys, time

import duckdb

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WIP = os.path.join(ROOT, "data", "graph", "najma.duckdb")
LAKE = os.path.join(ROOT, "data", "lake")
CATALOG = os.path.join(LAKE, "najma_catalog.sqlite")
FILES = os.path.join(LAKE, "files")
ALIAS = "najma"
LAKE_NATIVE = ("_publish_log",)          # tables that live only in the lake; lake-native loaders add theirs via LAKE_NATIVE_PREFIXES
LAKE_NATIVE_PREFIXES = ("lk_",)
RAW_GOV = re.compile(r"^gov_[a-z0-9_]+?__")   # gov_<entity>__<dataset>: raw staging rows, scrambled fill included


def _p(path):
    return path.replace("\\", "/")


def _load(con):
    for ext in ("ducklake", "sqlite"):
        try:
            con.execute("LOAD %s" % ext)
        except Exception:
            con.execute("INSTALL %s" % ext)
            con.execute("LOAD %s" % ext)


def attach(con, read_only=True):
    os.makedirs(FILES, exist_ok=True)
    opts = ["DATA_PATH '%s/'" % _p(FILES)] + (["READ_ONLY"] if read_only else [])
    con.execute("ATTACH 'ducklake:sqlite:%s' AS %s (%s)" % (_p(CATALOG), ALIAS, ", ".join(opts)))


def connect(read_only=True):
    """A connection with the published store as the default catalogue. Readers never wait on a builder."""
    con = duckdb.connect()
    _load(con)
    attach(con, read_only=read_only)
    con.execute("USE %s" % ALIAS)
    return con


def retry(fn, what, tries=30, wait=20):
    """Run fn(); on a catalogue write conflict wait and try again - another writer holds the SQLite lock for a moment."""
    for k in range(tries):
        try:
            return fn()
        except (duckdb.TransactionException, duckdb.IOException, duckdb.Error) as e:
            msg = str(e).lower()
            if ("locked" not in msg and "conflict" not in msg and "failed to commit" not in msg) or k == tries - 1:
                raise
            print("%s: catalogue busy (%s) - retrying in %ds" % (what, str(e)[:80], wait))
            time.sleep(wait)


def _attach_wip(con, wait_seconds=1200):
    deadline = time.time() + wait_seconds
    while True:
        try:
            con.execute("ATTACH '%s' AS src (READ_ONLY)" % _p(WIP))
            return
        except duckdb.IOException as e:
            if "lock" not in str(e).lower() or time.time() > deadline:
                raise
            print("work-in-progress store is locked by a builder - waiting")
            time.sleep(20)


def _fingerprint(con, qualified):
    n, x, s = con.execute('select count(*), coalesce(bit_xor(hash(t)), 0), coalesce(sum(hash(t)), 0)::varchar from %s t' % qualified).fetchone()
    return int(n), hashlib.md5(("%s|%s|%s" % (n, x, s)).encode()).hexdigest()


def publish(note=""):
    run_id = dt.datetime.now().isoformat(timespec="seconds")
    con = duckdb.connect()
    _load(con)
    _attach_wip(con)
    attach(con, read_only=False)

    tables = [r[0] for r in con.execute(
        "select table_name from duckdb_tables() where database_name='src' and schema_name='main' order by table_name").fetchall()]
    views = con.execute("select view_name, sql from duckdb_views() where database_name='src' and schema_name='main' "
                        "and not internal order by view_name").fetchall()
    g_views = [v for v, _ in views if v.startswith("g_")]
    plain_views = [(v, sql) for v, sql in views if not v.startswith("g_")]
    # gov_<entity>__<dataset> base tables stay in work in progress (their clean rows are published as g_*); the register
    # tables gov_dataset and gov_contract ARE published, because v_gov_usable and friends read them
    objects = [t for t in tables if not RAW_GOV.match(t)] + g_views

    con.execute("create table if not exists %s.main._publish_log (run_id varchar, published_at timestamp, object varchar, "
                "rows bigint, fingerprint varchar, copied boolean)" % ALIAS)
    prev = dict(con.execute("""select object, fingerprint from (
            select object, fingerprint, row_number() over (partition by object order by published_at desc) rn
            from %s.main._publish_log) where rn = 1""" % ALIAS).fetchall())
    lake_tables = {r[0] for r in con.execute(
        "select table_name from duckdb_tables() where database_name='%s' and schema_name='main'" % ALIAS).fetchall()}

    plan = []
    for o in objects:
        n, fp = _fingerprint(con, 'src.main."%s"' % o)
        plan.append((o, n, fp, fp != prev.get(o) or o not in lake_tables))
    gone = [t for t in lake_tables if t in prev and t not in objects and t not in LAKE_NATIVE and not t.startswith(LAKE_NATIVE_PREFIXES)]
    pk = con.execute("select table_name, constraint_column_names from duckdb_constraints() "
                     "where database_name='src' and constraint_type='PRIMARY KEY'").fetchall()
    changed = [p for p in plan if p[3]]
    view_fp = hashlib.md5("\n".join("%s:%s" % (v, s) for v, s in plain_views).encode()).hexdigest()
    views_changed = view_fp != prev.get("view-definitions")
    print("publish plan: %d objects, %d changed, %d unchanged, %d removed%s"
          % (len(plan), len(changed), len(plan) - len(changed), len(gone), ", view definitions changed" if views_changed else ""))
    if not changed and not gone and not views_changed:
        snap = con.execute("select max(snapshot_id) from ducklake_snapshots('%s')" % ALIAS).fetchone()[0]
        print("nothing changed since snapshot %s - no new snapshot" % snap)
        return 0
    plan.append(("view-definitions", len(plain_views), view_fp, views_changed))    # logged, never copied as a table

    def body():
        con.execute("BEGIN TRANSACTION")
        try:
            for o, n, fp, copy in plan:
                if copy and o != "view-definitions":
                    con.execute('create or replace table %s.main."%s" as select * from src.main."%s"' % (ALIAS, o, o))
            for t in gone:
                con.execute('drop table if exists %s.main."%s"' % (ALIAS, t))
            con.execute("USE %s" % ALIAS)
            pending, failures = list(plain_views), {}
            for _ in range(6):                                   # views may depend on each other: create in passes
                nxt = []
                for v, sql in pending:
                    stmt = sql.strip().rstrip(";")
                    head = stmt.upper().find(" AS ")
                    try:
                        con.execute('create or replace view "%s" as %s' % (v, stmt[head + 4:]))
                    except Exception as e:
                        failures[v] = str(e)[:160]
                        nxt.append((v, sql))
                if not nxt or len(nxt) == len(pending):
                    pending = nxt
                    break
                pending = nxt
            con.execute("USE memory")
            problems = ["view %s not published: %s" % (v, failures.get(v, "")) for v, _ in pending]
            for t, cols in pk:                                   # the contract DuckLake cannot enforce: keys stay unique
                if RAW_GOV.match(t):
                    continue
                collist = ", ".join('"%s"' % c for c in cols)
                dup = con.execute('select count(*) - count(distinct (%s)) from %s.main."%s"' % (collist, ALIAS, t)).fetchone()[0]
                if dup:
                    problems.append("%s: %d rows repeat the key (%s)" % (t, dup, ", ".join(cols)))
            for o, n, fp, copy in plan:
                if copy and o != "view-definitions":
                    got = con.execute('select count(*) from %s.main."%s"' % (ALIAS, o)).fetchone()[0]
                    if got != n:
                        problems.append("%s: published %d rows of %d" % (o, got, n))
            if problems:
                con.execute("ROLLBACK")
                return problems
            con.executemany("insert into %s.main._publish_log values (?, ?, ?, ?, ?, ?)" % ALIAS,
                            [(run_id, dt.datetime.now(), o, n, fp, copy) for o, n, fp, copy in plan])
            try:
                con.execute("CALL ducklake_set_commit_message('%s', 'refresh_runner', ?)" % ALIAS,
                            ["publish %s: %d changed of %d. %s" % (run_id, len(changed), len(plan), note)])
            except Exception:
                pass
            con.execute("COMMIT")
            return []
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise

    problems = retry(body, "publish")
    if problems:
        for p in problems:
            print("HELD lake publish: %s" % p)
        return 4
    snap = con.execute("select max(snapshot_id) from ducklake_snapshots('%s')" % ALIAS).fetchone()[0]
    print("published snapshot %s: %d objects (%d copied), %d views" % (snap, len(plan), len(changed), len(plain_views)))
    return 0


def status():
    con = connect()
    snaps = con.execute("select snapshot_id, cast(snapshot_time as varchar), commit_message from ducklake_snapshots('%s') "
                        "order by snapshot_id desc limit 12" % ALIAS).fetchall()
    for s in snaps:
        print("snapshot %-5s %s  %s" % (s[0], s[1][:19], (s[2] or "")[:90]))
    n_t = con.execute("select count(*) from duckdb_tables() where database_name='%s'" % ALIAS).fetchone()[0]
    n_v = con.execute("select count(*) from duckdb_views() where database_name='%s' and not internal" % ALIAS).fetchone()[0]
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(LAKE) for f in fs)
    print("%d tables, %d views, %.0f MB on disk (%s)" % (n_t, n_v, size / 1e6, _p(LAKE)))
    return 0


def expire(days):
    con = duckdb.connect()
    _load(con)
    attach(con, read_only=False)
    def body():
        con.execute("CALL ducklake_expire_snapshots('%s', older_than => now() - INTERVAL '%d days')" % (ALIAS, days))
        con.execute("CALL ducklake_cleanup_old_files('%s', cleanup_all => true)" % ALIAS)
    retry(body, "expire")
    print("expired snapshots older than %d days and removed their files" % days)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["publish", "status", "expire"])
    ap.add_argument("--note", default="")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    if a.action == "publish":
        return publish(a.note)
    if a.action == "status":
        return status()
    return expire(a.days)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("lake %s error: %s" % (sys.argv[1] if len(sys.argv) > 1 else "", str(e)[:300]))
        sys.exit(1)
