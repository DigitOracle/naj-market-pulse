"""dda_gap_analysis.py -- what production access changed, dataset by dataset (18 Sep 2026).

Compares the STG pull (data/raw_downloads/dda/stg/MANIFEST.json, 10-15 Sep) with the PROD pull (.../prod/MANIFEST.json, from
18 Sep) across the 523-endpoint catalogue and puts every dataset in one bucket:

  new_access     STG failed (404 / blocked / 503 / 408) and PROD landed it
  now_populated  STG landed 0 rows, PROD landed rows
  grew           both landed, PROD has more rows (STG served samples)
  same           same row count
  shrank         PROD has fewer rows than STG (look: STG pages wrapped, or PROD is filtered)
  prod_empty     PROD landed 0 rows
  lost           STG landed it, PROD failed
  still_missing  neither landed it
  not_pulled     not in the PROD manifest yet (pull still running)

For both sides it also samples up to 2,000 rows and measures the share of rows carrying staging fill, with the same two
signatures as gate_gov_realness.py (long vowel-poor A-Z0-9 runs; 3-8 letter vowel-poor words in word-named columns), and flags a
pull that stopped at the page ceiling (rows = max pages x page size) as truncated.

    python scripts/dda_gap_analysis.py      -> data/raw_downloads/dda/prod/GAP_ANALYSIS.csv + GAP_ANALYSIS.json
"""
import csv, io, json, os, re, sys
from collections import Counter

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
D = os.path.join(ROOT, "data", "raw_downloads", "dda")
STG, PROD = os.path.join(D, "stg"), os.path.join(D, "prod")
SAMPLE = 2000
CEILINGS = {2_000_000, 5_000_000}          # --max-pages 2000 (STG, 10-15 Sep) and 5000 (PROD, 18 Sep) at 1,000 rows a page

CODE_COL = re.compile(r"(code|iso|_id$|^id$|abbr|num$|number$|currency|symbol|ticker|sr_num|no$)", re.I)
WORD_COL = re.compile(r"(month|day|region|name|desc|title|location|unit|type|status|category|city|"
                      r"country|emirate|area|line|station|activity|profession|author|group)", re.I)


def vowel_share(s):
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(re.sub(r"[^AEIOUaeiou]", "", letters)) / len(letters) if letters else 0.0


# Real values the gate's word signature catches, found by running it over PROD rows on 18 Sep (PROD is not obfuscated):
# month abbreviations (dewa_water_production_mig, gross_power_generation), DEWA units, tender status.
REAL_WORDS = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC", "MIGD", "MIG", "CLOSED"}


def is_fill(col, v):
    if not isinstance(v, str) or v in REAL_WORDS: return False
    if len(v) >= 12 and re.fullmatch(r"[A-Z0-9]+", v) and vowel_share(v) < 0.34: return True
    return bool(WORD_COL.search(col) and not CODE_COL.search(col) and re.fullmatch(r"[A-Z]{3,8}", v) and vowel_share(v) < 0.34)


def sample(path):
    """First SAMPLE rows without loading a 700 MB payload whole."""
    if not path or not os.path.exists(path): return []
    try:
        import ijson
        out = []
        with open(path, "rb") as f:
            for rec in ijson.items(f, "results.item", use_float=True):
                out.append(rec)
                if len(out) >= SAMPLE: break
        return out
    except Exception:
        return []


def fill_share(rows):
    if not rows: return None
    bad = sum(1 for r in rows if isinstance(r, dict) and any(is_fill(k, v) for k, v in r.items()))
    return round(bad / len(rows), 3)


def cols_of(rows):
    return sorted({k for r in rows[:200] if isinstance(r, dict) for k in r})


def bucket(s, p):
    if not p: return "not_pulled"
    s_ok, p_ok = s.get("status") == "ok", p.get("status") == "ok"
    sr, pr = s.get("rows") or 0, p.get("rows") or 0
    if not s_ok and p_ok: return "new_access" if pr else "prod_empty"
    if s_ok and not p_ok: return "lost"
    if not s_ok and not p_ok: return "still_missing"
    if pr == 0: return "prod_empty"
    if sr == 0: return "now_populated"
    return "grew" if pr > sr else "same" if pr == sr else "shrank"


def main():
    cat = json.load(io.open(os.path.join(D, "api_catalogue.json"), encoding="utf-8"))["rows"]
    stg = json.load(io.open(os.path.join(STG, "MANIFEST.json"), encoding="utf-8"))
    prod = json.load(io.open(os.path.join(PROD, "MANIFEST.json"), encoding="utf-8")) if os.path.exists(os.path.join(PROD, "MANIFEST.json")) else {}
    out = []
    for r in cat:
        if not r.get("endpoints"): continue
        key = f"{r['entity']}/{r['dataset']}"
        s, p = stg.get(key, {}), prod.get(key)
        ss = sample(os.path.join(STG, s["file"])) if s.get("file") else []
        ps = sample(os.path.join(PROD, p["file"])) if p and p.get("file") else []
        sc, pc = set(cols_of(ss)), set(cols_of(ps))
        out.append({
            "key": key, "entity": r["entity"], "dataset": r["dataset"], "title": r.get("title"), "organization": r.get("organization"),
            "bucket": bucket(s, p),
            "stg_status": s.get("status", ""), "stg_rows": s.get("rows") or 0, "stg_fill_share": fill_share(ss),
            "prod_status": (p or {}).get("status", ""), "prod_rows": (p or {}).get("rows") or 0, "prod_fill_share": fill_share(ps),
            "row_gain": ((p or {}).get("rows") or 0) - (s.get("rows") or 0),
            "stg_truncated": (s.get("rows") or 0) in CEILINGS, "prod_truncated": ((p or {}).get("rows") or 0) in CEILINGS,
            "cols_added": ",".join(sorted(pc - sc)) if ss and ps else "", "cols_dropped": ",".join(sorted(sc - pc)) if ss and ps else "",
            "prod_note": (p or {}).get("note", ""),
        })
    out.sort(key=lambda x: (x["bucket"], -x["row_gain"]))
    csv_path, js_path = os.path.join(PROD, "GAP_ANALYSIS.csv"), os.path.join(PROD, "GAP_ANALYSIS.json")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    by = Counter(x["bucket"] for x in out)
    ent = {}
    for x in out:
        e = ent.setdefault(x["entity"], Counter()); e[x["bucket"]] += 1; e["stg_rows"] += x["stg_rows"]; e["prod_rows"] += x["prod_rows"]
    summary = {
        "generated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"), "datasets": len(out), "buckets": dict(by),
        "stg_rows_total": sum(x["stg_rows"] for x in out), "prod_rows_total": sum(x["prod_rows"] for x in out),
        "stg_datasets_with_fill": sum(1 for x in out if (x["stg_fill_share"] or 0) > 0.02),
        "prod_datasets_with_fill": sum(1 for x in out if (x["prod_fill_share"] or 0) > 0.02),
        "prod_truncated": [x["key"] for x in out if x["prod_truncated"]],
        "by_entity": {k: dict(v) for k, v in sorted(ent.items(), key=lambda kv: -kv[1]["prod_rows"])},
        "top_gains": [{k: x[k] for k in ("key", "title", "stg_rows", "prod_rows")} for x in sorted(out, key=lambda x: -x["row_gain"])[:25]],
        "new_access": [{k: x[k] for k in ("key", "title", "stg_status", "prod_rows")} for x in out if x["bucket"] == "new_access"],
        "still_missing": [{k: x[k] for k in ("key", "title", "stg_status", "prod_status", "prod_note")} for x in out if x["bucket"] in ("still_missing", "lost")],
    }
    json.dump(summary, open(js_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(out)} datasets -> {csv_path}")
    for b, n in by.most_common(): print(f"  {b:14} {n:4}")
    print(f"  rows: STG {summary['stg_rows_total']:,} -> PROD {summary['prod_rows_total']:,}")
    print(f"  datasets with >2% staging fill: STG {summary['stg_datasets_with_fill']}, PROD {summary['prod_datasets_with_fill']}")


if __name__ == "__main__":
    main()
