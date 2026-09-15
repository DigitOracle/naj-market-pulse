"""Identity as a table: every project name in the sales register linked to a registered project id, scored, reviewable.

Data Spine Phase 4 (13 Sep 2026). Sales and rents name their project in free text ("azizi venice 13 ", "RAW DISTRICT BY
IMTIAZ R", "DAMAC LAGOONS - NICE 1") and carry no project id. The DLD projects register - the one with developer, status,
completion and escrow - names its projects in Arabic, so on 13 Sep only 27 of 3,008 sales project names met it exactly.
Every developer attribution downstream ("Masaar by ARADA", "Treppan by Fakhruddin") was therefore a name guess, and one of
them welded a Fakhruddin source line to an Arada project on 12 Sep.

The bridge: the DLD buildings, units and land registers carry project_id with BOTH the English and the Arabic name. So:

  left    distinct (PROJECT_EN, AREA_EN) from dld_transactions_now in the published lake
  right   registered projects from the buildings, units and land registers (data/raw_downloads/dd): project_id, English
          name, Arabic name, area, master project - the same project_id the projects register uses

Decision, in order:
  1 manual   data/identity/decisions.json - an accept or reject by hand always wins
  2 exact    the normalised name maps to exactly one registered project -> accepted (1.0); to several -> the one whose area
             agrees once marketing names are mapped to DLD areas (data/dld/area_alias.json) -> accepted (0.99), else review
  3 splink   Splink 4 scores what is left on three pieces of evidence: name similarity (Jaro-Winkler levels), the NUMBERS in
             the name (a different tower or cluster number is strong evidence against - AZIZI VENICE 13 is not 14), and area
             agreement. The m-probabilities are set from what the register shows rather than trained by expectation-
             maximisation: unsupervised training on this register decided an exact name was rare for true pairs (look-alike
             siblings dominate its blocks) and scored identical names at 0.59. u-probabilities are estimated by Splink
             from random pairs. >= 0.95 accepted; 0.50-0.95 review; below that unmatched.

Writes to the lake (lake.py), in one transaction:
  lk_identity_xref   job, left_name, left_area, rows, project_id, project_name_en, project_area, probability, method, decision
  lk_project_alias   project_id, alias, lang (en | ar), kind (registered | sales register), source
  lk_dld_projects    the DLD projects register as published (all text), so status/completion/developer join on project_id
  v_transactions_project   dld_transactions_now with the accepted project_id attached
and data/identity/review_tx_project.csv - the uncertain middle, heaviest first, for Kendall.
Usage: python scripts/identity_match.py        Exit 0; 4 = the review queue grew; 1 = error.
"""
import csv, datetime as dt, glob, json, os, re, sys, warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
import lake  # noqa: E402
from register_joins import register_files  # noqa: E402

DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
IDENT = os.path.join(ROOT, "data", "identity")
DECISIONS = os.path.join(IDENT, "decisions.json")
REVIEW_CSV = os.path.join(IDENT, "review_tx_project.csv")
ALIAS = os.path.join(ROOT, "data", "dld", "area_alias.json")
ACCEPT, REVIEW = 0.95, 0.50
JOB = "tx_project"


def norm(s):
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def digits(s):
    d = " ".join(re.findall(r"\d+", s or ""))
    return d or None


def load_decisions():
    if not os.path.exists(DECISIONS):
        os.makedirs(IDENT, exist_ok=True)
        json.dump({"note": "Hand decisions for identity_match.py. Each: {job, left_name, left_area, project_id, decision: accept|reject, by, at, why}. They always win.",
                   "decisions": []}, open(DECISIONS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    d = json.load(open(DECISIONS, encoding="utf-8"))
    return [x for x in d.get("decisions") or [] if x.get("job", JOB) == JOB]


def main():
    t0 = dt.datetime.now()
    alias = {k.lower().strip(): v for k, v in (json.load(open(ALIAS, encoding="utf-8")).get("alias") or {}).items()}
    canon_area = lambda a: norm(alias.get((a or "").lower().strip(), a or ""))
    reg = duckdb.connect()
    # 14 Sep 2026: every part of each newest finished extract (register_files reads the download's file list). The old
    # newest() took the last file by name, which for the three-part units register would have been part 3 alone.
    parts = [lake._p(p) for name, pattern in (("buildings", "dld__buildings__*.csv"), ("units", "dld__units__*.csv"),
                                               ("land_registry", "dld__land_registry__*.csv")) for p in register_files(name, pattern)]
    union = " union all ".join("select project_id, project_name_en, project_name_ar, area_name_en, master_project_en "
                               "from read_csv('%s', all_varchar=true)" % p for p in parts)
    right = reg.execute("""select project_id, mode(project_name_en) name_en, mode(project_name_ar) name_ar,
                                  mode(area_name_en) area, mode(master_project_en) master
                           from (%s) where project_id is not null and trim(project_id) <> ''
                             and project_name_en is not null and trim(project_name_en) <> '' group by project_id""" % union).df()
    projects_csv = lake._p(register_files("projects", "dld__projects__*.csv")[-1])

    L = lake.connect()
    left = L.execute("""select PROJECT_EN as name, AREA_EN as area, count(*) as n from dld_transactions_now
                        where PROJECT_EN is not null and trim(PROJECT_EN) <> '' group by 1, 2""").df()
    try:
        prev_review = L.execute("select count(*) from lk_identity_xref where job = ? and decision = 'review'", [JOB]).fetchone()[0]
    except Exception:
        prev_review = None
    L.close()

    right["name_norm"] = right["name_en"].map(norm)
    right["area_canon"] = right["area"].map(canon_area)
    left["name_norm"] = left["name"].map(norm)
    left["area_canon"] = left["area"].map(canon_area)
    by_name = {}
    for r in right.itertuples():
        by_name.setdefault(r.name_norm, []).append(r)

    decisions = {(d["left_name"], d.get("left_area")): d for d in load_decisions()}
    out, residual = [], []
    for l in left.itertuples():
        manual = decisions.get((l.name, l.area)) or decisions.get((l.name, None))
        if manual:
            rr = right[right.project_id == str(manual.get("project_id"))]
            if manual["decision"] == "accept" and len(rr):
                r = rr.iloc[0]
                out.append((l, r.project_id, r.name_en, r.area, 1.0, "manual", "accepted"))
            else:
                out.append((l, None, None, None, 0.0, "manual", "rejected"))
            continue
        cands = by_name.get(l.name_norm) or []
        if len(cands) == 1:
            r = cands[0]
            if r.area_canon == l.area_canon:
                out.append((l, r.project_id, r.name_en, r.area, 1.0, "exact name", "accepted"))
            else:
                # the name is unique in the register but the sales row labels its area differently. On 13 Sep there were
                # 430 such names; the twelve with the most rows were all area vocabulary, not a wrong project (MEYDAN ONE for
                # Al Merkadh, LIWAN for Wadi Al Safa 2). They are accepted at 0.97, and their areas feed
                # area_alias_evidence.csv instead of being hidden. Lower the 0.97 or route them to review if that stops holding.
                out.append((l, r.project_id, r.name_en, r.area, 0.97, "exact name, area label differs", "accepted"))
        elif len(cands) > 1:
            same = [r for r in cands if r.area_canon == l.area_canon]
            if len(same) == 1:
                r = same[0]
                out.append((l, r.project_id, r.name_en, r.area, 0.99, "exact name + area", "accepted"))
            else:
                r = cands[0]
                out.append((l, r.project_id, r.name_en, r.area, 0.6, "exact name, %d registered projects share it" % len(cands), "review"))
        else:
            residual.append(l)

    if residual:
        from splink import DuckDBAPI, Linker, SettingsCreator, block_on
        import splink.comparison_library as cl
        import pandas as pd
        ldf = pd.DataFrame([{"uid": "L%d" % i, "name_norm": l.name_norm, "area_canon": l.area_canon,
                             "name_digits": digits(l.name_norm), "first_tok": (l.name_norm.split(" ") or [""])[0]}
                            for i, l in enumerate(residual)])
        rdf = pd.DataFrame({"uid": ["R%s" % p for p in right.project_id], "name_norm": right.name_norm, "area_canon": right.area_canon,
                            "name_digits": right.name_norm.map(digits), "first_tok": right.name_norm.map(lambda x: (x.split(" ") or [""])[0])})
        settings = SettingsCreator(
            link_type="link_only",
            unique_id_column_name="uid",
            probability_two_random_records_match=1.0 / max(len(rdf), 1),
            blocking_rules_to_generate_predictions=[block_on("first_tok"), block_on("area_canon")],
            comparisons=[
                cl.JaroWinklerAtThresholds("name_norm", [0.95, 0.88, 0.80]).configure(m_probabilities=[0.80, 0.10, 0.05, 0.03, 0.02]),
                cl.ExactMatch("name_digits").configure(m_probabilities=[0.97, 0.03]),
                cl.ExactMatch("area_canon").configure(m_probabilities=[0.60, 0.40]),
            ],
            retain_intermediate_calculation_columns=False,
        )
        linker = Linker([ldf, rdf], settings, DuckDBAPI())
        linker.training.estimate_u_using_random_sampling(max_pairs=2e6)
        pred = linker.inference.predict(threshold_match_probability=0.05).as_pandas_dataframe()
        best = pred.sort_values("match_probability", ascending=False).drop_duplicates("uid_l").set_index("uid_l")
        rmap = right.set_index(right.project_id.map(lambda p: "R%s" % p))
        for i, l in enumerate(residual):
            uid = "L%d" % i
            if uid not in best.index:
                out.append((l, None, None, None, 0.0, "splink: no candidate", "unmatched"))
                continue
            p = float(best.loc[uid, "match_probability"]); r = rmap.loc[best.loc[uid, "uid_r"]]
            decision = "accepted" if p >= ACCEPT else "review" if p >= REVIEW else "unmatched"
            out.append((l, r.project_id, r.name_en, r.area, round(p, 4), "splink", decision))

    rows = [(JOB, l.name, l.area, int(l.n), pid, pname, parea, prob, method, decision, t0) for l, pid, pname, parea, prob, method, decision in out]
    aliases = [(r.project_id, r.name_en, "en", "registered", "DLD buildings/units/land") for r in right.itertuples()]
    aliases += [(r.project_id, r.name_ar, "ar", "registered", "DLD buildings/units/land") for r in right.itertuples() if r.name_ar]
    aliases += [(pid, l.name, "en", "sales register", "dld_transactions") for l, pid, _, _, _, _, d in out if d == "accepted" and norm(l.name) != l.name]

    W = lake.connect(read_only=False)
    W.execute("create temp table xref_stage (job varchar, left_name varchar, left_area varchar, rows bigint, project_id varchar, "
              "project_name_en varchar, project_area varchar, probability double, method varchar, decision varchar, decided_at timestamp)")
    W.executemany("insert into xref_stage values (?,?,?,?,?,?,?,?,?,?,?)", rows)
    W.execute("create temp table alias_stage (project_id varchar, alias varchar, lang varchar, kind varchar, source varchar)")
    W.executemany("insert into alias_stage values (?,?,?,?,?)", aliases)

    def body():
        W.execute("BEGIN TRANSACTION")
        try:
            W.execute("create or replace table lk_identity_xref as select * from xref_stage")
            W.execute("create or replace table lk_project_alias as select distinct * from alias_stage")
            if projects_csv:
                W.execute("create or replace table lk_dld_projects as select * from read_csv('%s', all_varchar=true)" % projects_csv)
            W.execute("""create or replace view v_transactions_project as
                select t.*, x.project_id, x.probability as project_match_probability, x.method as project_match_method
                from dld_transactions_now t left join lk_identity_xref x
                  on x.job = 'tx_project' and x.decision = 'accepted' and x.left_name = t.PROJECT_EN and x.left_area = t.AREA_EN""")
            W.execute("COMMIT")
        except Exception:
            W.execute("ROLLBACK")
            raise
    lake.retry(body, "identity")

    review = sorted([r for r in rows if r[9] == "review"], key=lambda r: -r[3])
    os.makedirs(IDENT, exist_ok=True)
    with open(REVIEW_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sales_project_name", "sales_area", "sales_rows", "candidate_project_id", "candidate_name", "candidate_area", "probability", "method", "decide (accept|reject)"])
        for r in review:
            w.writerow([r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], ""])

    # Area vocabulary evidence: for every area label the sales register uses, which DLD area its linked projects are actually
    # registered in (rows-weighted), next to what data/dld/area_alias.json says. The alias file feeds the yields, so a
    # disagreement here is a correction to review by hand - it is never applied automatically.
    ev = {}
    for r in rows:
        if r[9] == "accepted" and r[6]:
            ev.setdefault(r[2], {}).setdefault(r[6], 0)
            ev[r[2]][r[6]] += r[3]
    with open(os.path.join(IDENT, "area_alias_evidence.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sales_area_label", "sales_rows_linked", "registered_area_most_rows", "share", "alias_file_says", "agrees", "other_registered_areas"])
        lines = []
        for label, dist in ev.items():
            total = sum(dist.values())
            top, top_n = max(dist.items(), key=lambda kv: kv[1])
            says = alias.get((label or "").lower().strip())
            agrees = "yes" if norm(says or label) == norm(top) else "no"
            others = "; ".join("%s (%d)" % (a, n) for a, n in sorted(dist.items(), key=lambda kv: -kv[1])[1:4])
            lines.append((agrees, -total, [label, total, top, round(top_n / total, 3), says or "", agrees, others]))
        for _, _, line in sorted(lines):
            w.writerow(line)
    disagree = sum(1 for a, _, _ in lines if a == "no")
    # A merge-ready proposal, never applied here: only labels whose linked projects sit >= 85% in one registered DLD area
    # and that carry >= 50 sales. area_alias.json feeds the published yields, so applying it is Kendall's call.
    proposal = {}
    for agrees, neg_total, line in lines:
        label, total, top, share, says = line[0], line[1], line[2], line[3], line[4]
        if agrees == "no" and share >= 0.85 and total >= 50:
            proposal[(label or "").lower().strip()] = {"registered_area": top, "share": share, "sales_rows": total,
                                                       "alias_file_says": says or None}
    json.dump({"generated": dt.datetime.now().isoformat(timespec="seconds"),
               "note": "Proposed corrections to data/dld/area_alias.json from the register: each sales area label -> the DLD area its "
                       "linked projects are registered in. NOT applied. Approve, then merge into area_alias.json['alias'].",
               "changes": proposal}, open(os.path.join(IDENT, "area_alias_proposed.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    tot = sum(r[3] for r in rows)
    acc_rows = sum(r[3] for r in rows if r[9] == "accepted")
    counts = {}
    for r in rows:
        counts[r[9]] = counts.get(r[9], 0) + 1
    by_method = {}
    for r in rows:
        if r[9] == "accepted":
            by_method[r[8]] = by_method.get(r[8], 0) + 1
    print("identity %s: %d names - %s; accepted by %s" % (JOB, len(rows), ", ".join("%d %s" % (v, k) for k, v in sorted(counts.items())), by_method))
    print("sales rows linked to a registered project: %s of %s (%.1f%%); review queue %d -> %s"
          % (f"{acc_rows:,}", f"{tot:,}", 100.0 * acc_rows / max(tot, 1), len(review), os.path.relpath(REVIEW_CSV, ROOT)))
    print("area labels whose registered area disagrees with area_alias.json: %d (data/identity/area_alias_evidence.csv)" % disagree)
    return 4 if (prev_review is not None and len(review) > prev_review) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("identity match error:", str(e)[:300])
        sys.exit(1)
