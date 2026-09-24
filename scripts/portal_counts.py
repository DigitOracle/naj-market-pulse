"""portal_counts -- the portal's own row count beside what the gateway served and what we kept (25 Sep 2026).

Why. dm_container_of_the_consignments served 5,222,714 rows through the gateway and the pull kept 985,946; the portal's bulk
export holds 5,222,714. That match is the only reason the loss was provable - "rows we kept" can otherwise only be checked
against itself. This records the independent count for every dataset the portal also exports (matched by dataset id).

Portal count = the sum of the __partNN files when the export is split (capped whole files hold ~1.05M rows, Excel's limit),
else the whole file - but only when not capped. Counted in Python, independently of DuckDB. JSON parts that repeat the CSV
part before them are not double-counted (load_portal_parts.drop_format_copies).

Writes data/raw_downloads/dda/prod/portal_counts.json (not MANIFEST.json, which running pulls rewrite).
    python scripts/portal_counts.py
"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import duckdb
import load_portal_parts as L

ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROD = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod")
CAP = 1_040_000                                   # a whole file at or above this is Excel-capped, not a count


CONTENT_MAX = 600_000     # rows per side for the content diff; larger ones say "content not checked", never "agrees"


def _norm(c):
    v = "trim(regexp_replace(coalesce(cast(\"%s\" as varchar), ''), '\\s+', ' ', 'g'))" % c
    v = "regexp_replace(regexp_replace(replace(%s, 'T', ' '), '[.]0+Z?$|Z$', ''), ' 00:00:00$', '')" % v
    v = "regexp_replace(%s, '^(-?[0-9]+[.][0-9]*?)0+$', '\\1')" % v
    return "regexp_replace(%s, '^(-?[0-9]+)[.]$', '\\1')" % v


def content_diff(con, portal_files, gateway_file):
    """(only_in_portal, only_in_gateway, columns compared) as MULTISETS over the columns both carry, load_timestamp
    excluded. 25 Sep 2026 (Rings): drone services matched on count within 10 rows and differed in ~900 rows each way -
    a count is 'not yet contradicted', only content agreement is 'verified'."""
    gf = gateway_file.replace("\\", "/")
    con.execute("create or replace temp table g as select unnest(results, recursive := false) as r from "
                "read_json('%s', format='auto', maximum_object_size=1000000000)" % gf)
    con.execute("create or replace temp table g as select r.* from g")
    con.execute("create or replace temp table p as " + " union all by name ".join("(%s)" % L.select_sql(f) for f in portal_files))
    gc = {c[0] for c in con.execute("describe g").fetchall()}; pcs = {c[0] for c in con.execute("describe p").fetchall()}
    common = sorted((gc & pcs) - {"load_timestamp"})
    if not common: return None, None, 0
    sel = lambda t: "select %s from %s" % (", ".join("%s as \"%s\"" % (_norm(c), c) for c in common), t)
    a = con.execute("select count(*) from ((%s) except all (%s))" % (sel("p"), sel("g"))).fetchone()[0]
    b = con.execute("select count(*) from ((%s) except all (%s))" % (sel("g"), sel("p"))).fetchone()[0]
    return a, b, len(common)


def rule_reason(o, pv, dv):
    """Two narrow rules, each evidenced, labelled 'rule:' so a reader knows no one looked at that dataset by hand.
    Anything they do not cover stays UNEXPLAINED."""
    kept, por = o.get("kept"), o.get("portal_rows")
    if not kept or not por or o.get("status") != "ok" or kept <= por:
        return ""
    k = round(kept / por)
    if k >= 2 and abs(kept - k * por) <= 0.003 * k * por:
        # checked on ded_license_master 25 Sep 2026: all 533,923 portal licence numbers are in the gateway's 1,067,847
        return "rule: gateway holds %dx the portal file - the portal export is split and one part is on disk (checked by subset on ded_license_master)" % k
    later = (pv.get("pulled") or "") > (dv.get("fetched") or "9999")
    if later and kept - por <= 0.02 * por:
        return "rule: later snapshot - gateway pulled %s, portal exported %s, +%d rows (%.2f%%)" % (
            (pv.get("pulled") or "")[:10], (dv.get("fetched") or "")[:10], kept - por, 100.0 * (kept - por) / por)
    return ""


def main():
    dd = json.load(open(os.path.join(L.DD, "MANIFEST.json"), encoding="utf-8"))
    prod = json.load(open(os.path.join(PROD, "MANIFEST.json"), encoding="utf-8"))
    by_id = {}
    for k, v in dd.items():
        if isinstance(v, dict) and v.get("id") and v.get("file"):
            by_id[str(v["id"])] = (k, v)
    con = duckdb.connect()
    out = {}
    for key, v in sorted(prod.items()):
        hit = by_id.get(str(v.get("id")))
        if not hit: continue
        name, pv = hit
        whole = os.path.join(ROOT, pv["file"]) if not os.path.isabs(pv["file"]) else pv["file"]
        stem = os.path.basename(whole).rsplit(".", 1)[0]
        parts = [p for p in sorted(glob.glob(os.path.join(L.DD, stem + "__part*"))) if p.lower().endswith((".csv", ".json"))]
        how = ""
        try:
            if parts:
                kept, dropped = L.drop_format_copies(con, parts)
                n = sum(L.count_part(p) for p in kept); how = "%d parts" % len(kept)
            elif os.path.exists(whole) and (pv.get("rows") or 0) < CAP:
                n = L.count_part(whole); how = "whole file"
            else:
                n = None; how = "capped whole file, no parts"
        except Exception as e:
            n = None; how = "unreadable: " + str(e)[:80]
        # content: the question a count cannot answer (drone services). Only where both sides are small enough to diff whole.
        content = "content not checked"
        gfile = os.path.join(PROD, v.get("file") or "")
        if n and v.get("status") == "ok" and v.get("file") and os.path.exists(gfile) and n <= CONTENT_MAX and (v.get("rows") or 0) <= CONTENT_MAX:
            try:
                files = (L.drop_format_copies(con, parts)[0] if parts else [whole])
                a, b, nc = content_diff(con, files, gfile)
                content = ("content agrees (%d columns)" % nc) if a == 0 and b == 0 else \
                          ("content differs: %s only in portal, %s only in gateway (%d columns)" % (format(a, ","), format(b, ","), nc)) if nc else "no common columns"
            except Exception as e:
                content = "content diff failed: " + str(e)[:80]
        out[key] = {"portal_rows": n, "portal_how": how, "portal_name": name,
                    "gateway_served": v.get("raw_rows"), "kept": v.get("rows"), "repeats_kept": bool(v.get("repeats_kept")),
                    "status": v.get("status"), "content": content}
    # the lake's own count (25 Sep 2026, question bank): iacad_mosque_donation showed kept 452 = portal 452 while the published
    # table still held 300. 'kept' is the download; only this column says what a reader of the lake actually gets.
    try:
        import lake
        lc = lake.connect(read_only=True)
        tmap = dict(lc.execute("select key, table_name from gov_dataset").fetchall())
        have = {t for (t,) in lc.execute("select table_name from information_schema.tables").fetchall()}
        for k, o in out.items():
            t = tmap.get(k)
            if t and t.startswith("gov_"):      # the registry names the work table; the lake publishes the gated g_ copy
                t = "g_" + t[4:]
            o["lake_table"] = t
            o["lake_rows"] = lc.execute('select count(*) from "%s"' % t).fetchone()[0] if t in have else None
    except Exception as e:
        print("lake count unavailable:", str(e)[:120])
    # A GATE, not a report (25 Sep 2026, Rings): a finished dataset whose count differs from the portal's is UNEXPLAINED until
    # portal_reasons.json carries a written reason. Drone services at 3,329 vs 3,339 looked like noise and was two different
    # rolling windows with ~900 rows differing each way - found only because the small gap was not waved through.
    rp = os.path.join(PROD, "portal_reasons.json")
    reasons = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
    for k, o in out.items():
        o["reason"] = reasons.get(k, "") or rule_reason(o, prod.get(k, {}), dd.get(o["portal_name"], {}))
    json.dump(out, open(os.path.join(PROD, "portal_counts.json"), "w", encoding="utf-8"), indent=1)
    rows = [(k, o) for k, o in out.items() if o["portal_rows"] is not None]
    print("%d gateway datasets matched a portal export; %d with a usable portal count" % (len(out), len(rows)))
    differ = [(k, o) for k, o in rows if o["status"] == "ok" and o["kept"] is not None and o["kept"] != o["portal_rows"]]
    unexplained = [(k, o) for k, o in differ if not o["reason"]]
    print("finished and != portal: %d   (%d explained in portal_reasons.json, %d UNEXPLAINED)" % (
        len(differ), len(differ) - len(unexplained), len(unexplained)))
    for k, o in sorted(unexplained, key=lambda x: x[1]["kept"] / max(1, x[1]["portal_rows"]))[:60]:
        print("  UNEXPLAINED %-56s kept %12s  served %12s  portal %12s  (%s)%s" % (k[:56], format(o["kept"], ","),
              format(o["gateway_served"] or 0, ","), format(o["portal_rows"], ","), o["portal_how"], "  keep" if o["repeats_kept"] else ""))
    # count match is 'not yet contradicted'; say how many are actually verified by content
    import collections
    ok_counts = [o for o in out.values() if o["status"] == "ok" and o["portal_rows"] is not None and o["kept"] == o["portal_rows"]]
    print("count matches portal: %d - of which content agrees %d, content differs %d, not checked %d" % (
        len(ok_counts), sum(o["content"].startswith("content agrees") for o in ok_counts),
        sum(o["content"].startswith("content differs") for o in ok_counts), sum(not o["content"].startswith("content ") or "not checked" in o["content"] for o in ok_counts)))
    for k, o in out.items():
        if o["status"] == "ok" and o["portal_rows"] is not None and o["kept"] == o["portal_rows"] and o["content"].startswith("content differs"):
            print("  COUNT MATCH, CONTENT DIFFERS %-50s %s" % (k[:50], o["content"]))
    lag = [(k, o) for k, o in out.items() if o["status"] == "ok" and o.get("lake_rows") is not None and o["kept"] is not None and o["lake_rows"] < o["kept"]]
    print("lake behind the download: %d (publish pending, or the loader collapsed rows)" % len(lag))
    for k, o in sorted(lag)[:40]:
        print("  LAKE BEHIND %-56s lake %10s  downloaded %10s" % (k[:56], format(o["lake_rows"], ","), format(o["kept"], ",")))
    return len(unexplained)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)     # non-zero while anything finished differs from the portal without a written reason
