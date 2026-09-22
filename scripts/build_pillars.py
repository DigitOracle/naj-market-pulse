"""The four pillars, from the registers only (Kendall, 22 Sep 2026).

Broker training says a buyer's four questions are location, the developer's credibility, whether the
developer can finance itself, and price. This builds what the Land Department registers can actually
answer, and is deliberate about what they cannot.

  LOCATION         per building, in the Worker: metro distance + the district's schools and clinics.
                   This file supplies nothing for it - the page already holds it (stack `transit`,
                   `district_amenities`). Here only so the axis list is in one place.
  TRACK RECORD     years since the DLD developer register's license_issue_date, registered project
                   count, and cancellations. NOT "credibility": the register cannot judge that, and a
                   twenty-year developer with three cancellations would outrank a clean five-year one
                   if cancellations were left out - so they are folded in.
  DELIVERY RECORD  the project register: FINISHED against ACTIVE / NOT_STARTED / PENDING, percent
                   complete, and whether an escrow agent is named. NOT "financial strength": there are
                   no balance sheets in DLD. A vertex labelled STRENGTH gets read as "can they finance
                   themselves" whatever the footnote says, so the axis is named for what it measures
                   and Kendall's third pillar is reported as not answerable from this data.
  PRICE            per building, in the Worker: the building's own AED/sq ft against its area's median,
                   as a signed deviation (+18% vs the area), never a 0-100 score - a spider implies
                   bigger is better and "cheaper than the area" has no agreed direction. This file
                   supplies the area medians.

FLOORS, because a percentile computed on noise looks exactly like one computed on evidence:
  an area needs AREA_MIN_SALES residential sales before it gets a median at all (105 of 273 areas clear
  200), and a developer needs DEV_MIN_PROJECTS registered projects before it is scored. Below the floor
  the value is null, and null must render as a gap on the chart - never as a zero. A zero would say
  "scored badly" where the truth is "not held", and those are opposite claims.

  python scripts/build_pillars.py            -> data/board/pillars.json
  python scripts/build_pillars.py --push     -> also publishes KV `pillars`
"""
import datetime as dt
import glob
import json
import os
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
from build_avail_index import env_token, push  # noqa: E402

AED_PER_SQFT = 10.7639          # the same m2 -> ft2 divisor build_pulse.py uses, so the figures agree
AREA_MIN_SALES = 200            # an area below this gets no median and therefore no PRICE axis
DEV_MIN_PROJECTS = 3            # a developer below this gets no TRACK score
DEV_MIN_DUE = 3                 # and needs this many projects PAST their due date before delivery is judged
YEARS_CAP = 30                  # beyond thirty years, longer no longer means better

OUT = os.path.join(ROOT, "data", "board", "pillars.json")
DUCK = os.path.join(ROOT, "naj.duckdb")

AXES = [
    {"key": "location", "label": "LOCATION", "what": "How reachable the everyday things are: the metro, schools and clinics.",
     "source": "RTA metro and tram stations, KHDA private schools, DHA facilities, joined to the building",
     "scope": "building", "direction": "higher is closer"},
    {"key": "track", "label": "TRACK RECORD", "what": "How long the developer has been licensed, how much it has registered, and what it has cancelled.",
     "source": "DLD developer register (license_issue_date) and project register",
     "scope": "developer", "direction": "higher is longer and cleaner",
     "reads": "a rank against the other developers we can judge, not an absolute - 90 means longer licensed, "
              "more registered and fewer cancelled than nine in ten of them."},
    {"key": "delivery", "label": "DELIVERY RECORD", "what": "What it has finished against what is still not started, and whether an escrow agent is named.",
     "source": "DLD project register (project_end_date, project_status, percent_completed, cancellation_date)",
     "scope": "developer", "direction": "higher is more finished",
     "reads": "the share of this developer's projects that were past their due date and had been finished - "
              "100 means every one of them landed. Developers with fewer than 3 projects past their due date "
              "are not scored at all: too early to judge is not the same as a poor record.",
     "note": "Not a financing measure. There are no balance sheets in the Land Department registers, so "
             "whether a developer can fund itself is not answerable from this data and is not claimed here."},
    {"key": "price", "label": "PRICE", "what": "What this building asks per square foot against its own area.",
     "source": "DLD transactions (residential, registered) and the building's own unit mix",
     "scope": "building", "direction": "signed deviation, not a score"},
]


def newest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, "data", "registers", pattern)))
    return fs[-1] if fs else None


def pct_rank(value, population):
    """Where `value` sits in `population`, 0-100. Ties share the lower rank, which is the conservative read."""
    if value is None or not population:
        return None
    below = sum(1 for p in population if p < value)
    return int(round(100.0 * below / len(population)))


def area_medians(con):
    """Median AED/sq ft per area, residential registered sales only, floored at AREA_MIN_SALES."""
    rows = con.execute("""
        select AREA_EN,
               median(cast(TRANS_VALUE as double) / cast(ACTUAL_AREA as double)) / ? as aed_sqft,
               count(*) as n
        from transactions
        where USAGE_EN = 'Residential'
          and try_cast(ACTUAL_AREA as double) > 10
          and try_cast(TRANS_VALUE as double) > 0
        group by 1
        having count(*) >= ?
    """, [AED_PER_SQFT, AREA_MIN_SALES]).fetchall()
    return {r[0]: {"aed_sqft": int(round(r[1])), "sales": int(r[2])} for r in rows if r[0] and r[1]}


def developers(con, projects_csv, developers_csv):
    """One record per developer number that appears in the project register, joined to its licence."""
    rows = con.execute("""
        select cast(p.developer_number as bigint)                                as dev_no,
               any_value(d.developer_name_en)                                    as name,
               min(d.license_issue_date)                                         as licensed,
               min(d.registration_date)                                          as registered,
               count(*)                                                          as total,
               sum(case when p.project_status = 'FINISHED' then 1 else 0 end)    as finished,
               sum(case when p.project_status = 'ACTIVE' then 1 else 0 end)      as active,
               sum(case when p.project_status = 'NOT_STARTED' then 1 else 0 end) as not_started,
               sum(case when p.project_status = 'PENDING' then 1 else 0 end)     as pending,
               sum(case when p.cancellation_date is not null then 1 else 0 end)  as cancelled,
               sum(case when p.escrow_agent_name is not null then 1 else 0 end)  as escrowed,
               -- a project is only evidence of delivery once it was DUE. Judging a developer on schemes that
               -- are not yet meant to be finished scores a young programme as a failure, which is a real
               -- number attached to the wrong claim.
               sum(case when p.project_end_date < current_date then 1 else 0 end)                                      as due,
               sum(case when p.project_end_date < current_date and p.project_status = 'FINISHED' then 1 else 0 end)    as delivered,
               sum(case when p.project_end_date < current_date and p.project_status <> 'FINISHED' then 1 else 0 end)   as overdue,
               median(try_cast(p.percent_completed as double))                   as pct_complete,
               list(distinct p.area_name_en)                                     as areas
        from read_csv_auto(?) p
        left join read_csv_auto(?) d
          on cast(p.developer_number as bigint) = cast(cast(d.developer_number as double) as bigint)
        where p.developer_number is not null
        group by 1
    """, [projects_csv, developers_csv]).fetchall()

    today = dt.date.today()
    out = {}
    for r in rows:
        (dev_no, name, licensed, registered, total, finished, active,
         not_started, pending, cancelled, escrowed, due, delivered, overdue, pct_complete, areas) = r
        first = licensed or registered
        years = round((today - first).days / 365.25, 1) if first else None
        out[str(dev_no)] = {
            "name": (name or "").strip() or None,
            "licensed": first.isoformat() if first else None,
            "years": years,
            "projects": {"total": total, "finished": finished, "active": active,
                         "not_started": not_started, "pending": pending, "cancelled": cancelled,
                         "due": due, "delivered": delivered, "overdue": overdue},
            "escrow_named_pct": int(round(100.0 * escrowed / total)) if total else None,
            "pct_complete_median": round(pct_complete, 1) if pct_complete is not None else None,
            "areas": sorted(a for a in (areas or []) if a),
        }
    return out


def score(devs):
    """TRACK and DELIVERY as percentiles among developers that clear the project floor.

    Both are composed first and ranked second, so the score says "where this developer sits among the
    ones we can judge" rather than implying an absolute. A developer under the floor is scored null,
    not zero: three projects is not enough to tell a record from a run of luck.
    """
    scored = {k: v for k, v in devs.items() if v["projects"]["total"] >= DEV_MIN_PROJECTS}
    judgeable = {k: v for k, v in scored.items() if v["projects"]["due"] >= DEV_MIN_DUE}

    def track_raw(v):
        if v["years"] is None:
            return None
        longevity = min(v["years"], YEARS_CAP) / YEARS_CAP                    # 0-1, flat past the cap
        p = v["projects"]
        size = min(p["total"], 100) / 100.0                                   # 0-1, flat past a hundred
        clean = 1.0 - (p["cancelled"] / p["total"] if p["total"] else 0)      # cancellations earn their place here
        return (0.45 * longevity + 0.25 * size + 0.30 * clean)

    def delivery_raw(v):
        """Of the projects that were DUE, how many landed.

        The first cut of this scored finished/total and gave 0 to a developer with seventeen schemes and
        none finished - which read as "never delivers" when the register only said "not due yet". A young
        programme is now unscored rather than condemned, and the escrow agent is reported on the card as a
        fact rather than folded into a score, because whose bank holds the money is not a delivery measure.
        """
        p = v["projects"]
        if p["due"] < DEV_MIN_DUE:
            return None
        return p["delivered"] / p["due"]

    tr = {k: track_raw(v) for k, v in scored.items()}
    dl = {k: delivery_raw(v) for k, v in judgeable.items()}
    tr_pop = [x for x in tr.values() if x is not None]
    dl_pop = [x for x in dl.values() if x is not None]

    for k, v in devs.items():
        v["track"] = pct_rank(tr.get(k), tr_pop) if k in scored else None
        # DELIVERY is the RATE, not a percentile. Ranked, a perfect 17-of-17 scored 52 because so many
        # developers tie at 1.0 - a chart that makes a flawless record look middling. The rate says what it
        # means without a key: 100 is every due project delivered, 0 is none of them.
        v["delivery"] = int(round(100 * dl[k])) if k in judgeable and dl.get(k) is not None else None
        if v["track"] is None:
            v["track_why"] = ("fewer than %d registered projects" % DEV_MIN_PROJECTS) if k not in scored \
                else "no licence date in the developer register"
        if v["delivery"] is None:
            v["delivery_why"] = ("fewer than %d registered projects" % DEV_MIN_PROJECTS) if k not in scored else                 ("too early to judge - %d of %d projects have reached their due date"
                 % (v["projects"]["due"], v["projects"]["total"]))
    return devs


def norm(n):
    """'EMAAR DEVELOPMENT P.J.S.C.' -> 'emaar development', so the app can find a developer by name."""
    t = (n or "").lower()
    for junk in ("l.l.c", "llc", "p.j.s.c", "pjsc", "ش.ذ.م.م", "fze", "f.z.e", "(p.j.s.c)", "co.", "limited", "ltd"):
        t = t.replace(junk, " ")
    return " ".join(ch for ch in t.replace(".", " ").replace(",", " ").split() if ch)


def main():
    proj = newest(os.path.join("projects", "projects_*.csv"))
    devs_csv = newest(os.path.join("developers", "developers_*.csv"))
    if not proj or not devs_csv:
        print("FAIL: the project or developer register is not on disk"); return 2

    con = duckdb.connect(DUCK, read_only=True)
    areas = area_medians(con)
    devs = score(developers(con, proj, devs_csv))
    con.close()

    by_name = {}
    for k, v in devs.items():
        if v["name"]:
            by_name.setdefault(norm(v["name"]), []).append(k)

    doc = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "sources": [
            "DLD project register: " + os.path.basename(proj),
            "DLD developer register: " + os.path.basename(devs_csv),
            "DLD transactions (naj.duckdb), residential registered sales",
        ],
        "floors": {"areaMinSales": AREA_MIN_SALES, "developerMinProjects": DEV_MIN_PROJECTS,
                   "note": "Below a floor the value is null. Null renders as a gap on the chart, never as a zero: "
                           "a zero would say scored badly where the truth is not held."},
        "axes": AXES,
        "areas": areas,
        "developers": devs,
        "by_name": by_name,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    kb = os.path.getsize(OUT) / 1024
    have_track = sum(1 for v in devs.values() if v["track"] is not None)
    print("areas with a median (>= %d sales): %d" % (AREA_MIN_SALES, len(areas)))
    print("developers in the project register: %d" % len(devs))
    print("  scored (>= %d projects): %d   unscored: %d" % (DEV_MIN_PROJECTS, have_track, len(devs) - have_track))
    named = [v for v in devs.values() if v["name"] and v["track"] is not None]
    for v in sorted(named, key=lambda x: -x["projects"]["total"])[:5]:
        print("    %-34s %4.0f yrs  %3d projects  %3d finished  track %3d  delivery %3d"
              % (v["name"][:34], v["years"] or 0, v["projects"]["total"], v["projects"]["finished"], v["track"], v["delivery"]))
    print("-> %s (%.0f KB)" % (OUT, kb))

    if "--push" in sys.argv:
        tok = env_token("INGEST_TOKEN")
        if not tok:
            print("FAIL: no INGEST_TOKEN"); return 2
        print("pushed:", push("pillars", doc, tok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
