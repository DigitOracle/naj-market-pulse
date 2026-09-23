"""Which ROWS of the government datasets are real, and which are obfuscated staging fill.

The Dubai Data staging environment does not serve stale data only. It serves some values scrambled,
and the first version of this gate got the shape of that wrong in a way worth recording.

It assumed whole datasets were either real or fake, and rated `rta_bus_network_coverage` real. It is
mostly real - 226 of its 235 rows carry genuine Dubai communities with plausible figures, including
AL YUFRAH 1 at 403 residents and one bus stop, and MIRDIF at 68,346 residents and 32 stops - and NINE
rows are fill. Judging the dataset as a whole either throws away 226 good rows or imports nine
fabricated ones. Both are wrong, so the gate now works row by row.

Two signatures, both observed rather than guessed:

  long fill    twelve or more characters of uppercase letters and digits with no break and almost no
               vowels. The visitor-region values are a hundred characters - fifty random letters then
               fifty random digits.
  word fake    a 3-8 letter vowel-poor uppercase run in a column whose NAME promises a word. A month
               called 'HAU' is fill; an airport called 'DXB' is not, which is why the column name
               decides and code-like columns are exempt.

For every materialised table a companion view `g_<entity>__<dataset>` is created carrying only the
rows that pass. `v_gov_usable` names that view, so anything downstream reads clean rows without
having to know any of this. Nothing is deleted: the fabricated rows stay in the base table so the
next pull can be compared against them.
"""
import argparse, os, re, sys

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from contracts import GOV_CONTRACT_DDL, HOLDS_VIEW  # noqa: E402  (13 Sep 2026: held datasets leave v_gov_usable)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..")), "data", "graph", "najma.duckdb")

# A code column may legitimately hold DXB, GBR or AED. A word column may not hold 'HAU'.
CODE_COL_RX = re.compile(r"(code|iso|_id$|^id$|abbr|num$|number$|currency|symbol|ticker|sr_num|no$)", re.I)
WORD_COL_RX = re.compile(r"(month|day|region|name|desc|title|location|unit|type|status|category|city|"
                         r"country|emirate|area|line|station|activity|profession|author|group)", re.I)

# 23 Sep 2026: PROD rows are not obfuscated, so on PROD the fill signatures can only produce false positives - and did, at
# scale. Each earlier fix exempted the values that had just broken (month names 18 Sep, customs codes 19 Sep); by 23 Sep the
# gate was dropping ~290,000 real PROD rows: 87,801 DM food-test results reading SATISFACTORY (4 vowels in 12 letters, 0.333,
# under 0.34), DAFZ legal type FZCO, Dubai Police incident location LAND, and all but 29 of 198,830 DHA professionals because
# professionalcategoryid holds NUR/PHY/DEN and 'categoryid' has no underscore for CODE_COL_RX. The signatures describe the
# STAGING environment's scrambling, so they now run on STAGING rows only. PROD rows pass whole, marked 'prod'.
GATE_ENVS = {"stg"}

# Held back from publishing BY DECISION, whatever the gate says - realness cannot express "real, and not ours to spread".
WITHHOLD = {
    "dha/dha_sheryan_professional_detail-open-api":
        "personal data: full names, phones, emails, gender and nationality of 198,830 named health professionals. The only "
        "use so far is facility positions, already extracted without personal fields into data/board/_dha_precise_points.json. "
        "Publishing the register itself is Kendall's decision (23 Sep 2026).",
}

# Share of fabricated rows above which a dataset is not worth reading at all.
MOSTLY_FAKE = 0.98
# ...and below which it is treated as clean rather than mixed. Some datasets carry a stray oddity.
MOSTLY_CLEAN = 0.02

MACROS = [
    # Vowel share among the LETTERS only, so a letters-and-digits run is judged on its letters.
    """create or replace macro _vowel_share(s) as (
         case when length(regexp_replace(s, '[^A-Za-z]', '', 'g')) = 0 then 0.0
              else length(regexp_replace(s, '[^AEIOUaeiou]', '', 'g')) * 1.0
                   / length(regexp_replace(s, '[^A-Za-z]', '', 'g')) end)""",
    """create or replace macro _is_long_fill(s) as (
         s is not null and length(s) >= 12
         and regexp_full_match(s, '[A-Z0-9]+')
         and length(regexp_replace(s, '[^A-Z]', '', 'g')) >= 4
         and _vowel_share(s) < 0.34)""",
    # 19 Sep 2026: an all-digit run is a barcode, an HS commodity code or a phone number, not fill - the fill signature is random
    # LETTERS then digits. Without letters the vowel share was 0 and 415,904 of 443,481 real DM cosmetics rows, every 12-digit
    # customs commodity code and the DM detergent / supplement / biocide registers (~680k rows) were dropped as fabricated.
    # 18 Sep 2026: run over PROD rows (not obfuscated) the word signature caught real values - month abbreviations in DEWA's
    # monthly tables, DEWA's units MIGD / MIG, tender status CLOSED - and would have dropped those rows. They are exempt.
    """create or replace macro _is_word_fake(s) as (
         s is not null and regexp_full_match(s, '[A-Z]{3,8}')
         and _vowel_share(s) < 0.34
         and s not in ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'SEPT', 'OCT', 'NOV', 'DEC',
                       'MIGD', 'MIG', 'CLOSED'))""",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    con = duckdb.connect(DB)
    for m in MACROS:
        con.execute(m)
    for col, typ in (("realness", "varchar"), ("realness_note", "varchar"),
                     ("rows_clean", "bigint"), ("rows_fabricated", "bigint"), ("clean_view", "varchar")):
        try:
            con.execute("alter table gov_dataset add column %s %s" % (col, typ))
        except Exception:
            pass

    tabs = con.execute("select key, entity, dataset, table_name, rows_loaded, coalesce(env, 'stg') from gov_dataset "
                       "where materialised and table_name is not null order by rows_loaded desc").fetchall()
    counts = {"clean": 0, "mixed": 0, "fabricated": 0, "untestable": 0, "prod": 0, "withheld": 0}
    for key, ent, ds, tn, nrows, env in tabs:
        view = ("g_" + re.sub(r"^gov_", "", tn))[:120]
        if key in WITHHOLD:
            con.execute("drop view if exists %s" % view)
            con.execute("update gov_dataset set realness='withheld', realness_note=?, rows_clean=0, rows_fabricated=0, "
                        "clean_view=NULL where key=?", [WITHHOLD[key], key])
            counts["withheld"] += 1
            print("  %-11s %-44s %s" % ("WITHHELD", (ent + "/" + ds.replace("-open-api", ""))[:44], WITHHOLD[key][:64]))
            continue
        if env not in GATE_ENVS:
            con.execute("create or replace view %s as select * from %s" % (view, tn))
            con.execute("update gov_dataset set realness='prod', realness_note=?, rows_clean=?, rows_fabricated=0, "
                        "clean_view=? where key=?",
                        ["%s rows: not obfuscated, so not fill-tested; every row passes through %s" % (env, view), nrows, view, key])
            counts["prod"] += 1
            continue
        try:
            cols = con.execute("select * from %s limit 1" % tn).description
        except Exception:
            con.execute("update gov_dataset set realness='unreadable' where key=?", [key])
            continue
        text_cols = [d[0] for d in cols if str(d[1]).lower() in ("string", "varchar", "object")]
        # The two signatures do not deserve the same unit of judgement, and getting that wrong dropped
        # MIRDIF - six letters, two vowels, 33% - as fill. A twelve-character run of letters and digits
        # is unambiguous, so it is judged per ROW. A short vowel-poor uppercase word is not: MIRDIF,
        # ABU HAIL and PORT SAEED all look like 'HAU' to that test. So it is judged per COLUMN, and only
        # when most of the column looks fake is the whole column treated as fill.
        tests = []
        for c in text_cols:
            q = '"%s"' % c
            # 19 Sep 2026: a reference-number column (building_number, pre_registration_number, voucher_no, plot_no, barcode, imonumber)
            # legitimately holds vowel-poor runs like AFSBDMOTHB0180 or WIFBP1611474 - on PROD that dropped 4,775 DLD land-registry and
            # 3,335 DLD building rows (Al Furjan, JVT) off the parcel spine and 90,909 real DM vouchers. Only non-code columns are tested.
            if not CODE_COL_RX.search(c):
                tests.append("_is_long_fill(%s)" % q)
            if WORD_COL_RX.search(c) and not CODE_COL_RX.search(c):
                try:
                    n_all, n_fake = con.execute(
                        'select count(%s), sum(case when _is_word_fake(%s) then 1 else 0 end) from %s'
                        % (q, q, tn)).fetchone()
                except Exception:
                    continue
                if n_all and (int(n_fake or 0) / n_all) >= 0.6:
                    tests.append("_is_word_fake(%s)" % q)
        if not tests:
            # 13 Sep 2026 (Data Spine Phase 1): an untestable dataset still gets its own g_ view. clean_view used to name
            # the BASE table here, so eight datasets (1.10 M rows) were read from base tables, against the rule this gate
            # exists to enforce. The view passes every row through; the realness column says nothing was tested.
            view = ("g_" + re.sub(r"^gov_", "", tn))[:120]
            con.execute("create or replace view %s as select * from %s" % (view, tn))
            con.execute("update gov_dataset set realness=?, realness_note=?, rows_clean=?, rows_fabricated=0, "
                        "clean_view=? where key=?",
                        ["untestable", "no text column to test; rows taken as they are through %s" % view, nrows, view, key])
            counts["untestable"] += 1
            continue

        bad = "(" + " or ".join(tests) + ")"
        tot, fab = con.execute("select count(*), sum(case when %s then 1 else 0 end) from %s" % (bad, tn)).fetchone()
        fab = int(fab or 0)
        clean = int(tot) - fab
        share = (fab / tot) if tot else 0.0

        view = ("g_" + re.sub(r"^gov_", "", tn))[:120]
        if share >= MOSTLY_FAKE:
            verdict = "fabricated"
            note = "every row carries staging fill; nothing usable"
            con.execute("drop view if exists %s" % view)
            view_out = None
        else:
            verdict = "clean" if share <= MOSTLY_CLEAN else "mixed"
            note = ("%d of %d rows are staging fill and are excluded by %s" % (fab, tot, view)) if fab else \
                   ("all %d rows pass; %s is the whole table" % (tot, view))
            con.execute("create or replace view %s as select * from %s where not %s" % (view, tn, bad))
            view_out = view
        counts[verdict] += 1
        con.execute("update gov_dataset set realness=?, realness_note=?, rows_clean=?, rows_fabricated=?, "
                    "clean_view=? where key=?", [verdict, note, clean, fab, view_out, key])
        if a.verbose or verdict != "clean":
            print("  %-11s %-44s %s" % (verdict.upper(), (ent + "/" + ds.replace("-open-api", ""))[:44], note[:64]))

    # The only view anything downstream should read. clean_view is where the rows actually are.
    # 13 Sep 2026 (Data Spine Phase 1): a dataset the feed contract holds (gov_contract_check.py) is not usable either,
    # whatever its realness - a doubled or shrunken load is refused before anything can post from it.
    con.execute(GOV_CONTRACT_DDL)
    con.execute(HOLDS_VIEW)
    con.execute("""create or replace view v_gov_usable as
                   select entity, dataset, title, clean_view, rows_clean, rows_fabricated, realness, realness_note
                   from gov_dataset
                   where materialised and clean_view is not null and rows_clean > 0
                     and key not in (select key from v_gov_contract_holds)
                   order by rows_clean desc""")
    con.execute("""create or replace view v_gov_rejected as
                   select entity, dataset, title, status, realness, realness_note, rows_fabricated
                   from gov_dataset
                   where realness in ('fabricated') or status <> 'ok'
                   order by entity, dataset""")

    print()
    for k in ("prod", "clean", "mixed", "fabricated", "untestable", "withheld"):
        print("  %-11s %3d datasets" % (k, counts[k]))
    tot = con.execute("select sum(rows_clean), sum(rows_fabricated) from gov_dataset "
                      "where clean_view is not null").fetchone()
    print("\n  rows through the gate: %s clean, %s excluded as fill"
          % (f"{int(tot[0] or 0):,}", f"{int(tot[1] or 0):,}"))
    print("  read v_gov_usable and query the clean_view it names.")
    con.close()


if __name__ == "__main__":
    main()
