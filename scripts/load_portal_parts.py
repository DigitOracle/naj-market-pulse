"""load_portal_parts -- the complete data.dubai portal extracts that nothing was loading (24 Sep 2026).

Why. The portal serves a large dataset two ways: a single "whole" export capped at Excel's row limit (~1.05M rows) and a
set of __partNN files that together hold everything. The portal MANIFEST points at the capped whole file, and no loader read
the parts. So the lake held 1,048,443 rows of DED licence partners against 7,220,702 on disk, 68,000 airway bills against
4,189,495, and no trip-level bus, metro or tram ridership at all - while the DDA gateway was being fought for days to fetch
the same datasets less completely.

What. For each dataset below, every __part file (CSV, line-delimited JSON or a JSON array - the portal mixes them within one
dataset) is read, unioned BY NAME as text, and published to the lake as pp_<entity>__<dataset> ("portal parts"). The capped
whole file is never read, so nothing is counted twice. The g_* tables are left alone: the realness gate rebuilds those from
the API pulls, and would overwrite anything written there.

No de-duplication, on purpose: two identical ridership taps are two people at the same gate in the same second. The contract
is exact: the published row count must equal the rows counted independently, part by part, in Python - or nothing is
published.

    python scripts/load_portal_parts.py            all datasets
    python scripts/load_portal_parts.py --dry      count and check only, publish nothing
    python scripts/load_portal_parts.py bus_ridership metro_ridership
"""
import csv, glob, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lake  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
STAMP = "2026-09-09"
DATASETS = {                               # short name -> portal file stem
    "license_partners": "ded__license_partners",
    "airway_bill_detail": "customs__airway_bill_detail",
    "bus_ridership": "rta__bus_ridership",
    "metro_ridership": "rta__metro_ridership",
    "tram_ridership": "rta__tram_ridership",
    # 24 Sep 2026, from the capped-file scan. Parts checked first (logs/_csv_overlap.txt, _id_overlap.txt): rent contract
    # CSV parts are disjoint and each JSON part repeats the CSV before it; consignment parts overlap ~8% pairwise (paging,
    # as bus - source_part records it); customer parts share ~6%.
    "rent_contracts": "dld__rent_contracts",
    "container_consignments": "container_of_the_consignments",
    "customers_master_data": "customers_master_data",
    # 18 CSV parts, ids 1..18,819,595 contiguous and unique across parts (logs/_employment_check.txt) - clean paging.
    "employment": "employment",
    "food_health_certificate": "food_health_certificate",
}
# Parts that are the SAME export written twice as CSV (no format difference for drop_format_copies to key on). Food health
# part03 = part01 except one row whose backslash is escaped differently ('JEDDAH\\' vs 'JEDDAH\'); part01 = the whole
# file, 1,032,055 rows, under the Excel cap. Checked 24 Sep 2026.
ONLY = {"food_health_certificate": ("01",)}
STAMPS = {"customers_master_data": "2026-09-14"}   # export date where it is not STAMP (keyed by stem)
csv.field_size_limit(1 << 30)


def parts(stem):
    ps = sorted(glob.glob(os.path.join(DD, "%s__%s__part*" % (stem, STAMPS.get(stem, STAMP)))))
    ps = [p for p in ps if p.lower().endswith((".csv", ".json"))]
    if stem in ONLY:
        ps = [p for p in ps if os.path.basename(p).split("__part")[1][:2] in ONLY[stem]]
    return ps


def count_part(p):
    """Rows in one part, counted without DuckDB so the two counts are independent."""
    if p.lower().endswith(".csv"):
        with open(p, encoding="utf-8", errors="replace", newline="") as fh:
            return sum(1 for _ in csv.reader(fh)) - 1
    with open(p, "rb") as fh:
        head = fh.read(64).lstrip()
    if head.startswith(b"["):                          # a JSON array
        import ijson
        with open(p, "rb") as fh:
            return sum(1 for _ in ijson.items(fh, "item"))
    with open(p, "rb") as fh:                           # one record per line
        return sum(1 for ln in fh if ln.strip())


def select_sql(p):
    q = p.replace("\\", "/").replace("'", "''")
    if p.lower().endswith(".csv"):
        return "select * from read_csv('%s', all_varchar=true, header=true, max_line_size=16777216)" % q
    return "select * from read_json('%s', format='auto', maximum_object_size=268435456)" % q


def _cols(con, p):
    return [c[0] for c in con.execute("describe select * from (%s)" % select_sql(p)).fetchall() if c[0] != "load_timestamp"]


def _norm_select(con, p, cols=None):
    """Every column except load_timestamp as comparable text: 'T' -> ' ', trailing .000 / Z dropped, midnight dropped
    from dates - so a CSV part (all text) and a JSON part (typed) holding the same rows compare equal.
    24 Sep 2026, widened after dld rent contracts slipped through: text is trimmed with inner whitespace collapsed, and a
    plain decimal loses trailing zeros (CSV '115.00', JSON '115.0' -> '115'). `cols` restricts to the given columns."""
    cols = sorted(cols or _cols(con, p))
    def one(c):
        v = "trim(regexp_replace(coalesce(cast(\"%s\" as varchar), ''), '\\s+', ' ', 'g'))" % c
        v = "regexp_replace(regexp_replace(replace(%s, 'T', ' '), '[.]0+Z?$|Z$', ''), ' 00:00:00$', '')" % v
        v = "regexp_replace(%s, '^(-?[0-9]+[.][0-9]*?)0+$', '\\1')" % v          # 40.540 -> 40.54
        return "regexp_replace(%s, '^(-?[0-9]+)[.]$', '\\1') as \"%s\"" % (v, c)  # 115. -> 115
    return "select %s from (%s)" % (", ".join(one(c) for c in cols), select_sql(p))


def drop_format_copies(con, ps):
    """24 Sep 2026: the portal writes some parts TWICE - partNN.csv, then part(NN+1).json holding the very same rows. Metro
    and tram alternate like this, so summing every part DOUBLED them (42,987,159 metro taps published where ~22.0M are real)
    and the row-count contract, comparing the lake to that same sum, confirmed the doubling instead of catching it. A JSON
    part is now dropped only when it matches the CSV part before it row for row; one that differs is kept and loaded."""
    num = lambda p: int(re.search(r"__part(\d+)\.(?:csv|json)$", p, re.I).group(1))
    by_num = {num(p): p for p in ps}
    keep, dropped = [], []
    for p in ps:
        if p.lower().endswith(".json"):
            prev = by_num.get(num(p) - 1)
            if prev and prev.lower().endswith(".csv"):
                ca, cb = _cols(con, prev), _cols(con, p)
                common = sorted(set(ca) & set(cb))                             # a JSON export may add or drop columns
                if len(common) < 0.6 * max(len(ca), len(cb)):                  # too little in common to call it a copy
                    keep.append(p); continue
                a, b = _norm_select(con, prev, common), _norm_select(con, p, common)
                na = con.execute("select count(*) from (%s)" % a).fetchone()[0]
                nb = con.execute("select count(*) from (%s)" % b).fetchone()[0]
                if na == nb and con.execute("select count(*) from ((%s) except all (%s))" % (b, a)).fetchone()[0] == 0:
                    dropped.append(os.path.basename(p)); continue
        keep.append(p)
    return keep, dropped


def load(con, short, stem, dry):
    ps = parts(stem)
    if not ps:
        print("%-20s no parts on disk - skipped" % short); return None
    t0 = time.time()
    ps, dropped = drop_format_copies(con, ps)
    if dropped:
        print("%-20s %d JSON part(s) are copies of the CSV part before them - not loaded: %s" % (
            short, len(dropped), ", ".join(dropped[:4]) + (" ..." if len(dropped) > 4 else "")))
    expected = 0
    for p in ps:
        expected += count_part(p)
    table = "pp_" + stem
    # CSV parts are read as text; where a JSON part's guessed type differs, UNION BY NAME settles on text as the common type.
    # source_part (24 Sep 2026): the portal's pages OVERLAP - the same rows are served in several parts (tram April 2026 three
    # times) while other months are missing outright (tram March 2026). A repeat ACROSS parts is a paging repeat; a repeat
    # WITHIN one part can be two riders tapping together. Only rows carrying a real time can be told apart, so this loader
    # does not dedupe - it records which part each row came from, so a consumer can keep, per distinct row, the largest
    # count seen within any single part. Measured: bus 4.3%, tram 3.9%, metro timed rows 18.6% are cross-part repeats;
    # metro's 12.3M timeless rows cannot be separated by any rule.
    body = " union all by name ".join("(select *, '%s' as source_part from (%s))" % (
        os.path.basename(p).split("__part")[1], select_sql(p)) for p in ps)
    sql = "select * from (%s)" % body
    if dry:
        n = con.execute("select count(*) from (%s)" % sql).fetchone()[0]
        print("%-20s %2d parts  counted %12s  duckdb %12s  %s  (%.0fs, dry)" % (
            short, len(ps), format(expected, ","), format(n, ","), "MATCH" if n == expected else "MISMATCH", time.time() - t0))
        return n == expected

    def body_tx():
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("create or replace table %s as %s" % (table, sql))
            n = con.execute("select count(*) from %s" % table).fetchone()[0]
            if n != expected:
                raise RuntimeError("contract: %s holds %s rows, the parts hold %s - not published" % (table, n, expected))
            con.execute("COMMIT")
            return n
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
    n = lake.retry(body_tx, "portal parts " + short)
    print("%-20s %2d parts  %12s rows -> %s  (%.0fs)" % (short, len(ps), format(n, ","), table, time.time() - t0))
    return True


def main():
    dry = "--dry" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(DATASETS)
    con = lake.connect(read_only=dry)
    ok = True
    for short in names:
        try:
            r = load(con, short, DATASETS[short], dry)
            ok = ok and (r is not False)
        except Exception as e:
            print("%-20s FAILED: %s" % (short, str(e)[:300])); ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
