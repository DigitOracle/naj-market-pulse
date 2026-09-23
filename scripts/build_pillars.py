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
DECISIONS = os.path.join(ROOT, "data", "identity", "developer_group_decisions.json")
DUCK = os.path.join(ROOT, "naj.duckdb")
DNA_FILE = os.path.join(ROOT, "data", "dev_meta", "developer_dna.json")

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


def districts():
    """Every district's amenity density, RANKED against the others.

    The first cut scored a district against absolute caps - twenty schools, fifty clinics - and Business Bay
    has 26 and 563, so the cap saturated and every dense district scored a flat 100. LOCATION then reduced to
    "how far is the metro, plus fifty", which made a tower 3 km from rail look middling rather than badly
    connected. Ranking restores the discrimination: a thin district scores low because other districts really
    do hold more, not because it missed an arbitrary number.
    """
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "board", "stack_*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        amen = d.get("district_amenities") or {}
        label = ((amen.get("centre") or {}).get("label") or "").strip()
        if not label:
            continue
        out[label] = {"schools": len(amen.get("schools") or []) or amen.get("schools_n") or 0,
                      "health": amen.get("health_n") or 0,
                      "radiusKm": amen.get("radius_km") or 5}
    schools = [v["schools"] for v in out.values()]
    health = [v["health"] for v in out.values()]
    for v in out.values():
        s_r, h_r = pct_rank(v["schools"], schools), pct_rank(v["health"], health)
        v["rank"] = int(round((s_r + h_r) / 2)) if s_r is not None and h_r is not None else None
    return out


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
               -- of the ones that DID finish, how many landed by the date they were due. A developer can
               -- deliver everything eventually and still never be on time, and a buyer choosing a handover
               -- date cares about the difference. 1436 projects carry both dates; 110 of them finished late.
               sum(case when p.project_status = 'FINISHED' and p.completion_date is not null and p.project_end_date is not null then 1 else 0 end) as dated,
               sum(case when p.project_status = 'FINISHED' and p.completion_date is not null and p.project_end_date is not null and p.completion_date <= p.project_end_date then 1 else 0 end) as on_time,
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
         not_started, pending, cancelled, escrowed, due, delivered, overdue, dated, on_time, pct_complete, areas) = r
        first = licensed or registered
        years = round((today - first).days / 365.25, 1) if first else None
        out[str(dev_no)] = {
            "name": (name or "").strip() or None,
            "licensed": first.isoformat() if first else None,
            "years": years,
            "projects": {"total": total, "finished": finished, "active": active,
                         "not_started": not_started, "pending": pending, "cancelled": cancelled,
                         "due": due, "delivered": delivered, "overdue": overdue,
                         "dated": dated, "on_time": on_time, "late": dated - on_time},
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

    return _score_pop(devs, scored, judgeable)


def track_raw(v):
    """Longevity, size and a clean record, composed into one number that is then RANKED.

    Not "credibility": the register cannot judge that. Cancellations are folded in so the axis earns the
    name - without them a twenty-year developer with three cancellations outranks a clean five-year one.
    """
    if v["years"] is None:
        return None
    longevity = min(v["years"], YEARS_CAP) / YEARS_CAP                    # 0-1, flat past the cap
    p = v["projects"]
    size = min(p["total"], 100) / 100.0                                   # 0-1, flat past a hundred
    clean = 1.0 - (p["cancelled"] / p["total"] if p["total"] else 0)
    return 0.45 * longevity + 0.25 * size + 0.30 * clean


def delivery_raw(v):
    """Of the projects that were DUE, how many landed.

    The first cut scored finished/total and gave 0 to a developer with seventeen schemes and none
    finished - which read as "never delivers" when the register only said "not due yet". A young
    programme is unscored rather than condemned. The escrow agent is reported on the card as a fact
    rather than folded in here, because whose bank holds the money is not a delivery measure.
    """
    p = v["projects"]
    if p["due"] < DEV_MIN_DUE:
        return None
    return p["delivered"] / p["due"]



def _score_pop(devs, scored, judgeable, rank_against=None):
    tr = {k: track_raw(v) for k, v in scored.items()}
    dl = {k: delivery_raw(v) for k, v in judgeable.items()}
    tr_pop = rank_against if rank_against is not None else [x for x in tr.values() if x is not None]
    dl_pop = [x for x in dl.values() if x is not None]

    for k, v in devs.items():
        # ON TIME is a rate like DELIVERY, over the projects that finished AND carry both dates. It needs its
        # own floor: one project delivered a week early is not a record. Null where we cannot tell.
        p = v["projects"]
        v["on_time_pct"] = int(round(100 * p["on_time"] / p["dated"])) if p["dated"] >= DEV_MIN_DUE else None
        if v["on_time_pct"] is None:
            v["on_time_why"] = ("only %d of this developer's projects carry both a due date and a completion date"
                                % p["dated"])
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


def groups(devs):
    """The BRAND, aggregated across every DLD entity that belongs to it.

    Kendall, looking at a card reading "DAMAC STAR PROPERTIES - 12 projects": "they have only delivered
    12 projects?" No. DAMAC is EIGHTEEN entities in the register and 146 projects between them; Emaar is
    five and 206. Scoring a legal entity and labelling it with a brand name is a true number attached to
    a claim it does not support - the same fault as a gap with an unearned reason, in a third place.

    The entity links come from developer_dna.json, which already holds them per board developer. Their
    completeness is NOT assumed: `registerShortOf` reports the developer's own portfolio count when the
    register total falls well short of it, so a thin grouping is visible on the card rather than silently
    understating the developer.
    """
    try:
        with open(DNA_FILE, encoding="utf-8") as f:
            dna = json.load(f)["developers"]
    except Exception as e:
        print("  (no developer DNA, so no groups: %s)" % e)
        return {}
    # HAND DECISIONS WIN OVER THE DNA LINKS, and can create a group the DNA has never heard of.
    #
    # developer_dna.json links only the fifteen board developers. DAMAC is not one of them, so the brand a
    # building card was most likely to name had no group at all and showed one entity's 12 projects against
    # the brand's 146. developer_group_decisions.json is the file built for recording that judgement, and
    # it was empty until someone had a reason to fill it. A later entry for the same group and developer
    # number supersedes an earlier one, per that file's own rule - so the LAST decision is the one that
    # counts, and a rejection removes an entity the DNA would otherwise have included.
    decided = {}
    try:
        with open(DECISIONS, encoding="utf-8") as f:
            for e in (json.load(f).get("decisions") or []):
                g, n = str(e.get("group") or "").strip(), e.get("developer_number")
                if g and n is not None:
                    decided.setdefault(g, {})[str(int(n))] = (e.get("decision") == "accepted")
    except Exception as e:
        print("  (no group decisions read: %s)" % e)

    out = {}
    for name in sorted(set(dna) | set(decided)):
        rec = dna.get(name) or {}
        nos = [str(int(l["developer_number"])) for l in (rec.get("dld_entity_links") or [])
               if l.get("developer_number") is not None]
        for n, accepted in (decided.get(name) or {}).items():
            if accepted and n not in nos:
                nos.append(n)
            elif not accepted and n in nos:
                nos.remove(n)
        members = [devs[n] for n in nos if n in devs]
        if not members:
            continue
        agg = {k: sum(m["projects"][k] for m in members) for k in
               ("total", "finished", "active", "not_started", "pending", "cancelled",
                "due", "delivered", "overdue", "dated", "on_time", "late")}
        lic = sorted(m["licensed"] for m in members if m["licensed"])
        esc = [m["escrow_named_pct"] for m in members if m["escrow_named_pct"] is not None]
        port = (rec.get("portfolio") or {}).get("count")
        out[name] = {
            "name": name, "entities": len(members), "members": [n for n in nos if n in devs],
            "entity_names": [m["name"] for m in members if m["name"]][:12],
            "licensed": lic[0] if lic else None,
            "years": round((dt.date.today() - dt.date.fromisoformat(lic[0])).days / 365.25, 1) if lic else None,
            "projects": agg,
            "escrow_named_pct": int(round(sum(esc) / len(esc))) if esc else None,
            "portfolio_count": port,
            "decided": sorted(decided.get(name) or {}),
            # the developer's own portfolio says it built more than the register links account for
            "registerShortOf": port if (port and agg["total"] < port * 0.6) else None,
        }
    return out


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
    dis = districts()
    devs = score(developers(con, proj, devs_csv))
    con.close()
    # Groups are ranked against the ENTITY population, not against the fifteen of themselves. A brand
    # naturally scores higher on TRACK because it really has registered more - that is the fact, not a
    # distortion of it - and fifteen is far too thin a field to rank within.
    grp = groups(devs)
    ent_pop = [x for x in (track_raw(v) for v in devs.values() if v["projects"]["total"] >= DEV_MIN_PROJECTS) if x is not None]
    if grp:
        gscored = {k: v for k, v in grp.items() if v["projects"]["total"] >= DEV_MIN_PROJECTS}
        gjudge = {k: v for k, v in gscored.items() if v["projects"]["due"] >= DEV_MIN_DUE}
        _score_pop(grp, gscored, gjudge, rank_against=ent_pop)

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
        "districts": dis,
        "developers": devs,
        "groups": grp,
        # entity number -> the brand it belongs to. Without this the BUILDING card still resolves the single
        # registered company and prints its 12 projects under a header reading DAMAC; the group only reaches
        # /dev, which is not where a client is looking.
        "group_of": {n: g["name"] for g in grp.values() for n in (g.get("members") or [])},
        "by_name": by_name,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    kb = os.path.getsize(OUT) / 1024
    have_track = sum(1 for v in devs.values() if v["track"] is not None)
    print("areas with a median (>= %d sales): %d" % (AREA_MIN_SALES, len(areas)))
    print("districts with an amenity rank: %d" % sum(1 for v in dis.values() if v["rank"] is not None))
    print("board developers grouped: %d" % len(grp))
    for g in sorted(grp.values(), key=lambda x: -x["projects"]["total"])[:6]:
        p = g["projects"]
        print("    %-14s %2d entities %4d projects  %3d of %3d due delivered  track %s  on time %s%%%s"
              % (g["name"], g["entities"], p["total"], p["delivered"], p["due"], g["track"], g["on_time_pct"],
                 "   (register has %d, its own portfolio says %d)" % (p["total"], g["registerShortOf"]) if g["registerShortOf"] else ""))
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
        # v238.2 - EVERY developer is in the payload, not only the scored ones.
        #
        # The first cut pushed the 198 scored records and dropped the other 833. A building whose developer
        # is real but unscored then resolved to nothing, and the card printed "the register does not join
        # this building to a developer" - which is FALSE, and worse than a missing value, because a reason
        # reads as an explanation and gets believed. On /building/businessbay/12 it contradicted the card's
        # own header, which said OMNIYAT two lines above.
        #
        # Unscored records are thin on purpose: a name and three counts, enough for the page to state the
        # TRUE reason. All 1031 at full width is 415 KB on every render; this is 139 KB.
        PK = ("total", "finished", "cancelled", "due", "delivered", "overdue", "dated", "on_time", "late")
        scored_d, thin_d = {}, {}
        for k, v in devs.items():
            if v["track"] is not None or v["delivery"] is not None:
                r = {kk: vv for kk, vv in v.items() if kk != "areas"}
                r["projects"] = {a: v["projects"][a] for a in PK}
                scored_d[k] = r
            else:
                p = v["projects"]
                thin_d[k] = {"name": v["name"], "total": p["total"], "due": p["due"], "dated": p["dated"]}
        slim = {
            "generated": doc["generated"], "sources": doc["sources"], "floors": doc["floors"], "axes": AXES,
            "areas": areas, "districts": dis, "developers": scored_d, "unscored": thin_d, "groups": grp,
            "group_of": {n: g["name"] for g in grp.values() for n in (g.get("members") or [])},
        }
        slim["by_name"] = {n: ks for n, ks in by_name.items() if any(k in scored_d or k in thin_d for k in ks)}
        raw = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
        print("pushing %d scored + %d unscored developers, %d areas (%.0f KB, from %.0f KB on disk)"
              % (len(scored_d), len(thin_d), len(areas), len(raw.encode()) / 1024, kb))
        print("pushed:", push("pillars", slim, tok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
