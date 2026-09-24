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
        out[key] = {"portal_rows": n, "portal_how": how, "portal_name": name,
                    "gateway_served": v.get("raw_rows"), "kept": v.get("rows"), "repeats_kept": bool(v.get("repeats_kept")),
                    "status": v.get("status")}
    json.dump(out, open(os.path.join(PROD, "portal_counts.json"), "w", encoding="utf-8"), indent=1)
    rows = [(k, o) for k, o in out.items() if o["portal_rows"] is not None]
    print("%d gateway datasets matched a portal export; %d with a usable portal count" % (len(out), len(rows)))
    short = [(k, o) for k, o in rows if o["kept"] is not None and o["kept"] < o["portal_rows"]]
    print("kept < portal count: %d" % len(short))
    for k, o in sorted(short, key=lambda x: x[1]["kept"] / max(1, x[1]["portal_rows"]))[:40]:
        print("  %-60s kept %12s  served %12s  portal %12s  (%s)%s" % (k[:60], format(o["kept"], ","), format(o["gateway_served"] or 0, ","),
              format(o["portal_rows"], ","), o["portal_how"], "  keep" if o["repeats_kept"] else ""))


if __name__ == "__main__":
    main()
