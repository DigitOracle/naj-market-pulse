"""Analytical backend: load every register CSV in data/ into DuckDB (naj.duckdb).

Why: baked pulse.json serves the edge; DuckDB serves DEPTH locally — YoY, long trends,
per-project histories, ad-hoc questions — over the full 1M+ row history without pandas
gymnastics. Pattern validated by thomasproject/dubai-transactions-atlas (MIT).

Idempotent: tables are rebuilt from the newest file per source each run; the ytd
transactions file is unioned with the rolling window and deduplicated on TRANSACTION_NUMBER.

Usage:  python scripts/build_duck.py           # (re)build naj.duckdb
        python scripts/build_duck.py --sql "SELECT ..."   # quick query
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
DB = os.path.join(HERE, "..", "naj.duckdb")


def newest(pattern):
    c = sorted(glob.glob(os.path.join(DATA, pattern)))
    return c[-1] if c else None


def main():
    try:
        import duckdb
    except ImportError:
        sys.exit("pip install duckdb   (one-off)")
    con = duckdb.connect(DB)
    tx = newest("transactions-????-??-??.csv")
    ty = newest("transactions-ytd-*.csv")
    if tx or ty:
        parts = [f"SELECT * FROM read_csv_auto('{p}', header=true, all_varchar=true)" for p in (tx, ty) if p]
        con.execute("CREATE OR REPLACE TABLE transactions AS "
                    "SELECT * FROM (" + " UNION ALL BY NAME ".join(parts) + ") "
                    "QUALIFY row_number() OVER (PARTITION BY TRANSACTION_NUMBER ORDER BY INSTANCE_DATE DESC) = 1")
    for src, pat in [("rents", "rents-????-??-??.csv"), ("projects", "projects-????-??-??.csv"),
                     ("valuations", "valuations-????-??-??.csv"), ("brokers", "brokers-*.csv"),
                     ("lands", "lands-*.csv")]:
        f = newest(pat)
        if f:
            con.execute(f"CREATE OR REPLACE TABLE {src} AS SELECT * FROM read_csv_auto('{f}', header=true, all_varchar=true)")
    if "--sql" in sys.argv:
        q = sys.argv[sys.argv.index("--sql") + 1]
        print(con.execute(q).df().to_string())
    else:
        for (t,) in con.execute("SHOW TABLES").fetchall():
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"  {t:14s} {n:>10,} rows")
        print(f"-> {DB}")
    con.close()


if __name__ == "__main__":
    main()
