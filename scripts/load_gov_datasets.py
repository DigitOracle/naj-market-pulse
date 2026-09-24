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
PROD = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod")     # production credentials live 18 Sep 2026
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
# a single dataset above this is left on disk and flagged, not loaded. 18 Sep: 2M -> 6M for PROD, whose DLD transaction register
# alone runs past 900k rows at page 900 (STG served it as 5 rows); anything over BIG_BYTES streams through the NDJSON sidecar.
MAX_ROWS = 6_000_000


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



BIG_BYTES = 150 * 1024 * 1024


def ndjson_sidecar(path, keep_repeats=False):
    """Stream a {..., results:[...]} payload to one-record-per-line JSON, dropping identical records on the way - unless the
    pull marked the file repeats_kept (24 Sep 2026: identical rows there are separate records).

    DuckDB's read_json has to hold a single JSON object in memory to parse it, so the two 700 MB payloads (DM building permits,
    DED licence master) ran it out of memory on 13 Sep however much it was allowed to spill. Line-delimited JSON streams.
    The sidecar is rebuilt only when the payload is newer than it."""
    import hashlib, ijson
    side = path[:-5] + ".ndjson" if path.endswith(".json") else path + ".ndjson"
    if keep_repeats: side = side[:-7] + ".keep.ndjson"          # never reuse a de-duplicated cache for a keep file
    if os.path.exists(side) and os.path.getmtime(side) >= os.path.getmtime(path):
        return side
    seen = set(); tmp = side + ".part"
    with open(path, "rb") as f, open(tmp, "w", encoding="utf-8") as out:
        for rec in ijson.items(f, "results.item", use_float=True):
            line = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
            h = hashlib.sha1(line.encode("utf-8")).digest()
            if h in seen and not keep_repeats: continue
            seen.add(h); out.write(line + "\n")
    os.replace(tmp, side)
    return side

def read_manifest(d):
    p = os.path.join(d, "MANIFEST.json")
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else {}


def merged_manifest(env):
    """key -> (entry, directory, env). 18 Sep 2026: production credentials arrived. PROD serves the real registers, STG serves
    samples and scrambled fill, so 'best' takes a dataset from PROD whenever PROD landed it and falls back to STG otherwise;
    a dataset neither landed is registered with the PROD failure when there is one. Table names do not change with the source."""
    stg, prod = read_manifest(STG), read_manifest(PROD)
    if env == "stg": return {k: (v, STG, "stg") for k, v in stg.items()}
    if env == "prod": return {k: (v, PROD, "prod") for k, v in prod.items()}
    out = {}
    for k in set(stg) | set(prod):
        p, s = prod.get(k), stg.get(k)
        # 19 Sep 2026: marking PROD dld_transactions 'truncated' (1.26M of ~1.78M rows, awaiting re-pull) made this fall back to the
        # 5-row STG sample and overwrite the table the developer brief reads. A PROD file that is on disk and larger than STG's is kept
        # (as 'prod_partial') until the re-pull replaces it: an incomplete real register beats a sample.
        p_file = p and p.get("file") and os.path.exists(os.path.join(PROD, p["file"]))
        if p and p.get("status") == "ok": out[k] = (p, PROD, "prod")
        elif p_file and (p.get("rows") or 0) > ((s or {}).get("rows") or 0):
            out[k] = (dict(p, status="ok", note=f"PROD partial ({p.get('status')}), re-pull pending: " + (p.get("note") or "")), PROD, "prod_partial")
        elif s and s.get("status") == "ok": out[k] = (s, STG, "stg")
        else: out[k] = (p, PROD, "prod") if p else (s, STG, "stg")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry-only", action="store_true")
    ap.add_argument("--entity", help="limit materialising to one entity, e.g. dld")
    ap.add_argument("--env", choices=["best", "prod", "stg"], default="best", help="best = PROD where it landed, else STG")
    a = ap.parse_args()

    man = merged_manifest(a.env)
    if not man:
        sys.exit("no manifest under " + os.path.dirname(STG))
    now = dt.datetime.now().isoformat(timespec="seconds")

    con = duckdb.connect(DB)
    # The two biggest payloads (DM permits 658 MB, DED licence master) ran DuckDB out of memory on 13 Sep while the Unreal
    # editor held most of the RAM, and landed as empty tables. Let large reads spill to disk instead of failing.
    tmp = os.path.join(os.path.dirname(DB), '.duck_tmp'); os.makedirs(tmp, exist_ok=True)
    con.execute("set preserve_insertion_order=false"); con.execute("set temp_directory='%s'" % tmp.replace(os.sep, "/"))
    con.execute("""create or replace table gov_dataset (
                     key varchar primary key, dataset_id bigint, entity varchar, dataset varchar, title varchar,
                     status varchar, rows_reported bigint, columns_reported integer, file varchar, path varchar,
                     bytes bigint, pulled varchar, table_name varchar, materialised boolean, rows_loaded bigint,
                     note varchar, registered_at varchar, env varchar)""")

    reg, to_load = [], []
    for key, (v, src, env) in sorted(man.items()):
        ent, ds = v.get("entity") or "", v.get("dataset") or ""
        f = v.get("file") or ""
        p = os.path.join(src, f) if f else ""
        sz = os.path.getsize(p) if p and os.path.exists(p) else 0
        tn = tname(ent, ds) if v.get("status") == "ok" else None
        reg.append([key, v.get("id"), ent, ds, v.get("title"), v.get("status"), v.get("rows") or 0,
                    v.get("columns") or 0, f, p if sz else "", sz, v.get("pulled"), tn, False, 0,
                    v.get("note") or "", now, env])
        if v.get("status") == "ok" and sz and not a.registry_only and (not a.entity or ent == a.entity):
            to_load.append((key, ent, ds, tn, p, v.get("rows") or 0, bool(v.get("repeats_kept"))))

    con.executemany("insert into gov_dataset values (" + ",".join("?" * 18) + ")", reg)
    print("gov_dataset: %d datasets registered" % len(reg))

    ok = loaded = skipped = failed = 0
    for key, ent, ds, tn, p, nrows, keep in to_load:
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
            if os.path.getsize(p) > BIG_BYTES:
                side = ndjson_sidecar(p, keep).replace(os.sep, "/")
                con.execute("create or replace table %s as select * from read_json(?, format='newline_delimited', "
                            "maximum_object_size=16777216, sample_size=20000)" % tn, [side])
                n = con.execute("select count(*) from %s" % tn).fetchone()[0]
                fp = None
                # 24 Sep 2026: sidecars were kept forever and reached 22 GB, which with everything else filled the disk and
                # killed a pull mid-write. ndjson_sidecar() rebuilds one whenever it is missing, so it is a cache: drop it now.
                try: os.remove(side)
                except OSError: pass
            # DISTINCT: until 13 Sep the pager read past the end of every dataset, because the API wraps round to record 1
            # instead of returning a short page. 2,252,220 of 6,923,807 landed rows were repeats (ded license master 3x,
            # customs airway bills 42x). Identical rows carry no information, so they are collapsed here; the raw JSON on
            # disk keeps what the API actually served. Falls back to a plain select if a column type cannot be compared.
            # 24 Sep 2026: NOT for a file the pull marks repeats_kept (read sorted to a known last page, which cannot wrap):
            # there an identical row is another record of a register with no key, and DISTINCT would delete it.
            def build(sql_distinct, sql_plain):
                if keep: con.execute(sql_plain, [fp]); return
                try: con.execute(sql_distinct, [fp])
                except Exception: con.execute(sql_plain, [fp])
            if fp is not None: build("create or replace table %s as with src as (select unnest(results) as r from "
                  "read_json(?, format='auto', maximum_object_size=1000000000)) select distinct r.* from src" % tn,
                  "create or replace table %s as with src as (select unnest(results) as r from "
                  "read_json(?, format='auto', maximum_object_size=1000000000)) select r.* from src" % tn)
            if fp is not None: n = con.execute("select count(*) from %s" % tn).fetchone()[0]
            if fp is not None and n == 0:      # not the {..., results:[...]} shape: try it as a plain array of rows
                build("create or replace table %s as select distinct * from read_json(?, format='auto', "
                      "maximum_object_size=1000000000, records=true)" % tn,
                      "create or replace table %s as select * from read_json(?, format='auto', "
                      "maximum_object_size=1000000000, records=true)" % tn)
                n = con.execute("select count(*) from %s" % tn).fetchone()[0]
            # Some registers carry each record twice, identical but for load_timestamp (the publisher loaded it twice two
            # seconds apart: dm_building_permits 1,103,352 rows, 568,037 records). Keep one row per record, earliest load.
            cols = [r[0] for r in con.execute("describe %s" % tn).fetchall()]
            if "load_timestamp" in cols and len(cols) > 1:
                try:
                    if keep:    # drop only the LATER loads of a record; repeats within the earliest load are separate records
                        part_by = ", ".join('"%s"' % c for c in cols if c != "load_timestamp")
                        con.execute("create or replace table %s as select * exclude (_m) from (select *, min(load_timestamp) over "
                                    "(partition by %s) as _m from %s) where load_timestamp is not distinct from _m" % (tn, part_by, tn))
                    else:
                        con.execute("create or replace table %s as select * exclude (load_timestamp), min(load_timestamp) as "
                                    "load_timestamp from %s group by all" % (tn, tn))
                    n = con.execute("select count(*) from %s" % tn).fetchone()[0]
                except Exception:
                    pass
            con.execute("update gov_dataset set materialised=true, rows_loaded=? where key=?", [n, key])
            loaded += 1
            ok += n
        except Exception as e:
            con.execute("update gov_dataset set note=? where key=?", ["load failed: " + str(e)[:90], key])
            failed += 1

    print("materialised: %d tables, %s rows   (skipped %d oversize, %d failed)" % (loaded, f"{ok:,}", skipped, failed))

    # The registry is rebuilt on every run, so a one-entity run used to mark every other landed table as not materialised.
    # Re-credit any table that already exists from an earlier run (13 Sep).
    existing = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    for key, tn in con.execute("select key, table_name from gov_dataset where not materialised and table_name is not null").fetchall():
        if tn in existing:
            n = con.execute("select count(*) from %s" % tn).fetchone()[0]
            if n: con.execute("update gov_dataset set materialised=true, rows_loaded=? where key=?", [n, key])

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
