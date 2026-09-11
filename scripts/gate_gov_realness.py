"""Which of the government datasets are REAL, and which are obfuscated staging fill.

The Dubai Data staging environment does not only serve stale data - it serves some datasets with the
values scrambled. Two found by hand:

    dtcm_overnight_visitors_by_region.total_list_regions -> 'ODTYCXWMYVYISIXNYCKIESCGDY'
    rta_salik_tariff.month                               -> 'HAU', 'OBZ', 'ZGN'

Those are not region names or months. They are random letters of the right length. A dataset like that
is worse than a missing one, because it reads as data and will pass any row count or freshness check.
If one reached the morning feed, Naj would post a number that was never true.

So every landed table is gated before anything is allowed to use it. The test is deliberately crude
and errs towards suspicion: for each text column, what share of its distinct values look like random
uppercase letters - no spaces, no vowel rhythm, no repetition across rows? Real reference data
(BurJuman Metro Station, Green Metro line, PETROLEUM MIXING WORKER) fails that description easily.

Writes `realness` and `realness_note` onto gov_dataset. Nothing is deleted: a scrambled dataset stays
registered and stays on disk, marked, so the next pull can be compared against it.
"""
import argparse, re, sys

import duckdb, os

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..")), "data", "graph", "najma.duckdb")
VOWELS = set("AEIOUaeiou")
# The staging fill is not what it first looked like. The visitor-region values are ONE HUNDRED
# characters - fifty random uppercase letters followed by fifty random digits:
#   'SVJERDHTONGYTIBNUJRGKCJZMBZRFXUGWHQKNEBDXAKFBFLUBM63494341155240133306324743623645345853236161468338'
# A test for pure uppercase runs missed every one of them. Length and charset catch them instead.
LONG_FILL_RX = re.compile(r"^[A-Z0-9]{12,}$")
SHORT_CODE_RX = re.compile(r"^[A-Z]{3,8}$")
# A 3-letter uppercase code is normal in a code column and meaningless in a word column: DXB and GBR
# are real, a month called 'HAU' is not. So the column's own name decides how suspicious to be.
CODE_COL_RX = re.compile(r"(code|iso|_id$|^id$|abbr|num$|number$|currency|symbol|ticker|sr_num)", re.I)
WORD_COL_RX = re.compile(r"(month|year|day|region|name|desc|title|location|unit|type|status|"
                         r"category|city|country|emirate|area|line|station|activity|profession)", re.I)


def low_vowel(s):
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return False
    return (sum(1 for ch in letters if ch in VOWELS) / len(letters)) < 0.34


def looks_scrambled(v, column=""):
    """Synthetic fill, on either of two signatures.

    Long: a dozen or more characters of uppercase letters and digits with no break - nothing a person
    typed looks like that. Short: a 3-8 letter uppercase run with almost no vowels sitting in a column
    whose NAME promises a word. Codes are exempted, because DXB, GBR and AED are all real and all
    vowel-poor."""
    s = str(v or "").strip()
    if len(s) < 3:
        return False
    if LONG_FILL_RX.match(s) and low_vowel(s):
        return True
    if SHORT_CODE_RX.match(s) and low_vowel(s):
        if CODE_COL_RX.search(column or ""):
            return False
        return bool(WORD_COL_RX.search(column or ""))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(DB)
    for col, typ in (("realness", "varchar"), ("realness_note", "varchar")):
        try:
            con.execute("alter table gov_dataset add column %s %s" % (col, typ))
        except Exception:
            pass

    tabs = con.execute("select key, entity, dataset, table_name, rows_loaded from gov_dataset "
                       "where materialised and table_name is not null order by rows_loaded desc").fetchall()
    counts = {"real": 0, "suspect": 0, "scrambled": 0, "thin": 0}
    for key, ent, ds, tn, nrows in tabs:
        try:
            cols = con.execute("select * from %s limit 1" % tn).description
        except Exception:
            con.execute("update gov_dataset set realness='unreadable' where key=?", [key]); continue
        text_cols = [d[0] for d in cols if str(d[1]).lower() in ("string", "varchar", "object")]
        flagged, checked = [], 0
        for cname in text_cols[:12]:
            try:
                vals = [r[0] for r in con.execute(
                    'select distinct "%s" from %s where "%s" is not null limit 40' % (cname, tn, cname)).fetchall()]
            except Exception:
                continue
            vals = [v for v in vals if isinstance(v, str) and v.strip()]
            if len(vals) < 4:
                continue
            checked += 1
            share = sum(1 for v in vals if looks_scrambled(v, cname)) / len(vals)
            if share >= 0.6:
                flagged.append("%s (%.0f%% of values)" % (cname, share * 100))
        if not checked:
            verdict, note = "thin", "no text column with enough distinct values to test"
        elif flagged:
            # One fabricated column is enough to make a dataset unusable: the fake column is
            # invariably the one carrying the meaning. A second only confirms it.
            verdict = "scrambled" if (len(flagged) >= 2 or checked == 1) else "suspect"
            note = "random-letter values in " + "; ".join(flagged[:3])
        else:
            verdict, note = "real", "text values read as real names across %d column(s)" % checked
        counts[verdict] = counts.get(verdict, 0) + 1
        con.execute("update gov_dataset set realness=?, realness_note=? where key=?", [verdict, note, key])
        if a.verbose or verdict in ("scrambled", "suspect"):
            print("  %-10s %-46s %s" % (verdict.upper(), (ent + "/" + ds.replace("-open-api", ""))[:46], note[:70]))

    con.execute("""create or replace view v_gov_usable as
                   select entity, dataset, title, table_name, rows_loaded, realness, realness_note
                   from gov_dataset
                   where materialised and realness = 'real' and rows_loaded > 0
                   order by rows_loaded desc""")
    print()
    for k in ("real", "suspect", "scrambled", "thin"):
        print("  %-10s %3d datasets" % (k, counts.get(k, 0)))
    print("\n  v_gov_usable is the only view anything downstream should read.")
    con.close()


if __name__ == "__main__":
    main()
