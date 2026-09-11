"""Link the Dubai Data (DDA iPaaS) pull into the truth store.

The pull lands 500+ government datasets as JSON under data/raw_downloads/dda/stg/, each
{id, title, entity, dataset, rows, columns, results:[...]} with a MANIFEST.json beside them. Useful
on disk, invisible to the graph: nothing could answer "how many licensed brokers are there" or join a
building to a municipality record without someone opening a file.

Two things are built:

  gov_dataset   one row per dataset the pull ATTEMPTED - entity, title, status, rows, file, and
                whether it is materialised. Including the failures, because 151 datasets came back
                503 and the record of what is missing is as load-bearing as the data itself. The
                DLD datasets that matter most (transactions, projects, land registry, sale index,
                area lookup) are all in that group.

  gov_<entity>__<dataset>   the actual rows, one table per landed dataset.

Registered before materialised: a dataset that is on disk but not in a table is still discoverable,
and a dataset that never arrived is still named. Re-runs are idempotent.

  python scripts/load_gov_datasets.py                 registry + materialise everything that landed
  python scripts/load_gov_datasets.py --registry-only just the registry
  python scripts/load_gov_datasets.py --entity dld    one entity
"""
import argparse, datetime as dt, glob, io, json, os, re, sys

import duckdb

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
STG = os.path.join(ROOT, "data", "raw_downloads", "dda", "stg")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
MAX_ROWS = 2_000_000          # a single dataset above this is left on disk and flagged, not loaded


def tname(entity, dataset):
    """gov_dld__brokers. The '-open-api' suffix is on every dataset name and carries nothing."""
    d = re.sub(r"-open-api$", "", str(dataset or ""))
    d = re.sub(r"^" + re.escape(str(entity or "")) + r"_", "", d)      # dld_brokers under entity dld -> brokers
    s = re.sub(r"[^a-z0-9_]+", "_", (str(entity or "x") + "__" + (d or "dataset")).lower()).strip("_")
    return ("gov_" + s)[:120]


def load_payload(path):
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:
        return None, str(e)[:70]
    if isinstance(d, list):
        return d, None
    if isinstance(d, dict):
        for k in ("results", "data", "records", "items"):
            if isinstance(d.get(k), list):
                return d[k], None
    return None, "no row array found"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry-only", action="store_true")
    ap.add_argument("--entity", help="limit materialising to one entity, e.g. dld")
    a = ap.parse_args()

    mpath = os.path.join(STG, "MANIFEST.json")
    if not os.path.exists(mpath):
        sys.exit("no manifest at " + mpath)
    man = json.load(io.open(mpath, encoding="utf-8"))
    now = dt.datetime.now().isoformat(timespec="seconds")

    con = duckdb.connect(DB)
    con.execute("""create or replace table gov_dataset (
                     key varchar primary key, dataset_id bigint, entity varchar, dataset varchar, title varchar,
                     status varchar, rows_reported bigint, columns_reported integer, file varchar, path varchar,
                     bytes bigint, pulled varchar, table_name varchar, materialised boolean, rows_loaded bigint,
                     note varchar, registered_at varchar)""")

    reg, to_load = [], []
    for key, v in sorted(man.items()):
        ent, ds = v.get("entity") or "", v.get("dataset") or ""
        f = v.get("file") or ""
        p = os.path.join(STG, f) if f else ""
        sz = os.path.getsize(p) if p and os.path.exists(p) else 0
        tn = tname(ent, ds) if v.get("status") == "ok" else None
        reg.append([key, v.get("id"), ent, ds, v.get("title"), v.get("status"), v.get("rows") or 0,
                    v.get("columns") or 0, f, p if sz else "", sz, v.get("pulled"), tn, False, 0,
                    v.get("note") or "", now])
        if v.get("status") == "ok" and sz and not a.registry_only and (not a.entity or ent == a.entity):
            to_load.append((key, ent, ds, tn, p, v.get("rows") or 0))

    con.executemany("insert into gov_dataset values (" + ",".join("?" * 17) + ")", reg)
    print("gov_dataset: %d datasets registered" % len(reg))

    ok = loaded = skipped = failed = 0
    for key, ent, ds, tn, p, nrows in to_load:
        if nrows > MAX_ROWS:
            con.execute("update gov_dataset set note=? where key=?",
                        ["left on disk: %s rows exceeds the load ceiling" % f"{nrows:,}", key])
            skipped += 1
            continue
        rows, err = load_payload(p)
        if rows is None:
            con.execute("update gov_dataset set note=? where key=?", ["could not read: " + (err or "?"), key])
            failed += 1
            continue
        if not rows:
            con.execute("update gov_dataset set materialised=false, rows_loaded=0, note=? where key=?",
                        ["landed empty", key])
            continue
        try:
            # DuckDB reads the file itself: faster than handing it 100k dicts, and it infers the types.
            # The payload is one object carrying a results array, so unnest it and expand the struct -
            # `select unnest(results)` alone yields a single anonymous struct column, not the fields.
            fp = p.replace("\\", "/")
            con.execute("create or replace table %s as with src as (select unnest(results) as r from "
                        "read_json(?, format='auto', maximum_object_size=1000000000)) select r.* from src"
                        % tn, [fp])
            n = con.execute("select count(*) from %s" % tn).fetchone()[0]
            if n == 0:      # not the {..., results:[...]} shape: try it as a plain array of rows
                con.execute("create or replace table %s as select * from read_json(?, format='auto', "
                            "maximum_object_size=1000000000, records=true)" % tn, [fp])
                n = con.execute("select count(*) from %s" % tn).fetchone()[0]
            con.execute("update gov_dataset set materialised=true, rows_loaded=? where key=?", [n, key])
            loaded += 1
            ok += n
        except Exception as e:
            con.execute("update gov_dataset set note=? where key=?", ["load failed: " + str(e)[:90], key])
            failed += 1

    print("materialised: %d tables, %s rows   (skipped %d oversize, %d failed)" % (loaded, f"{ok:,}", skipped, failed))

    # Views a person would actually ask for. Kept deliberately few - the registry is the index.
    con.execute("""create or replace view v_gov_missing as
                   select entity, dataset, title, status, note from gov_dataset
                   where status <> 'ok' order by
                     case status when 'http_503' then 0 when 'blocked' then 1 else 2 end, entity, dataset""")
    con.execute("""create or replace view v_gov_landed as
                   select entity, dataset, title, table_name, rows_loaded from gov_dataset
                   where materialised order by rows_loaded desc""")

    print()
    st = con.execute("select status, count(*), sum(rows_reported) from gov_dataset group by 1 order by 2 desc").fetchall()
    for s, c, r in st:
        print("  %-10s %3d datasets  %12s rows reported" % (s, c, f"{r or 0:,}"))
    print()
    print("  retryable (503):", con.execute("select count(*) from gov_dataset where status='http_503'").fetchone()[0])
    dld = con.execute("select dataset, status, rows_reported from gov_dataset where entity='dld' order by rows_reported desc").fetchall()
    print("\n  --- DLD ---")
    for d, s, r in dld:
        print("    %-52s %-9s %9s" % (d[:52], s, f"{r or 0:,}"))
    con.close()


if __name__ == "__main__":
    main()
