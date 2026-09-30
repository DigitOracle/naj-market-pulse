"""check_join_freshness.py -- read lk_join_log and say which register-joins jobs have gone stale (30 Sep 2026).

Why. Every job run through register_joins.py already logs its own run_at and status ('accepted'/'held') to lk_join_log -
gov_thread's last accepted run was 24 Sep, six days before this was written, and nothing had noticed. The tracking already
existed; nobody was reading it. This is that reader: no rebuild, no write to the lake, just a report and a loud exit code
when something has gone quiet.

    python scripts/check_join_freshness.py [--max-days 8] [--job gov_thread,key_bridge]

Exit 0: everything checked is within --max-days of its last accepted run. Exit 1: at least one job is stale or has never
run (a job with zero rows in lk_join_log is reported as "never run", not silently skipped).
"""
import argparse, sys, time
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import lake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=float, default=8.0)
    ap.add_argument("--job", default="", help="comma-separated job names; default is every job that has ever logged a run")
    a = ap.parse_args()
    con = lake.connect(read_only=True)
    jobs = [j.strip() for j in a.job.split(",") if j.strip()] or \
           [r[0] for r in con.execute("select distinct job from lk_join_log order by 1").fetchall()]
    now = time.time()
    stale = []
    for j in jobs:
        row = con.execute("select run_at, status from lk_join_log where job = ? and status = 'accepted' "
                          "order by run_at desc limit 1", [j]).fetchone()
        if row is None:
            print("  NEVER RUN      %-20s (no accepted run in lk_join_log)" % j)
            stale.append(j); continue
        age_days = (now - row[0].timestamp()) / 86400
        flag = "STALE" if age_days > a.max_days else "ok"
        print("  %-14s %-20s last accepted %s (%.1f days ago)" % (flag, j, row[0].strftime("%Y-%m-%d %H:%M"), age_days))
        if age_days > a.max_days: stale.append(j)
    if stale:
        print("%d of %d jobs stale or never run (over %.0f days): %s" % (len(stale), len(jobs), a.max_days, ", ".join(stale)))
    else:
        print("all %d jobs within %.0f days" % (len(jobs), a.max_days))
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
