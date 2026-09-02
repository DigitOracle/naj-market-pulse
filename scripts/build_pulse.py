"""Market Pulse aggregator — DLD Open Data -> public/pulse.json

Every source passes the Source Sanity Gate (HANDOVER.md §1/§7) and FAILS CLOSED.
Reads only. Raw CSVs never leave data/ — only derived aggregates are published.

Run:  python scripts/build_pulse.py
"""
import csv, json, statistics, re, sys, os
from collections import Counter
from datetime import datetime, timezone

DATA = "data"
PUB = "public"


def _newest_stamp():
    """Capture date = newest transactions-YYYY-MM-DD.csv in data/, unless PULSE_STAMP pins it."""
    if os.environ.get("PULSE_STAMP"):
        return os.environ["PULSE_STAMP"]
    import glob
    stamps = [re.search(r"transactions-(\d{4}-\d{2}-\d{2})\.csv$", p).group(1)
              for p in glob.glob(os.path.join(DATA, "transactions-*.csv"))
              if re.search(r"transactions-\d{4}-\d{2}-\d{2}\.csv$", p)]
    if not stamps:
        sys.exit("no transactions-YYYY-MM-DD.csv in data/ — run fetch_dld.py or drop a CSV in")
    return max(stamps)


STAMP = None  # resolved in main()
KNOWN_GOOD_STAMP = "2026-08-25"  # the capture the §9 validation numbers belong to
AED_PER_SQFT = 10.7639        # m2 -> ft2 divisor for AED/m2 -> AED/ft2

ATTRIBUTION = ("Source: Dubai Land Department (DLD) Open Data. "
               "Contains information from the Government of Dubai.")


class SourceRejected(Exception):
    """A source failed its sanity gate. Quarantine it — never average it in."""


def sanity_gate(source, rows, *, row_shape, min_rows, max_rows, sample=None):
    """Fail CLOSED. Returns only rows passing row_shape; raises SourceRejected if the
    source as a whole looks poisoned, collapsed or exploded."""
    if not isinstance(rows, list):
        raise SourceRejected(f"{source}: payload is not a list")
    total = len(rows)
    clean = [r for r in rows if row_shape(r)]
    if total - len(clean):
        print(f"  gate[{source}]: dropped {total - len(clean)}/{total} rows failing shape")
    if len(clean) < min_rows:
        raise SourceRejected(f"{source}: only {len(clean)} clean rows (< {min_rows}) — quarantined")
    if len(clean) > max_rows:
        raise SourceRejected(f"{source}: {len(clean)} clean rows (> {max_rows}) — quarantined")
    if sample:
        sample(clean)  # raises SourceRejected on out-of-band headline values
    return clean


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def dwelling_count(r):
    """Registered dwellings in a project row.

    DLD splits the count across CNT_UNIT (apartments) and CNT_VILLA (villas/townhouses);
    villa communities carry CNT_UNIT=0 with the whole count in CNT_VILLA. Reading CNT_UNIT
    alone made 46 projects / 13,674 villas invisible to the supply layer (Al Yelayiss 1,
    The Valley in Al Yufrah 1, Me'Aisem, Saih Shuaib...). Sum both - they are disjoint in
    this file, never double-counted.
    """
    return int(num(r.get("CNT_UNIT")) or 0) + int(num(r.get("CNT_VILLA")) or 0)



def read_csv(name):
    # Prefer the file dated to this run's STAMP; fall back to the newest <name>-*.csv so a
    # transactions/rents-only refresh still builds (valuations/projects/brokers/lands move slowly).
    import glob
    path = os.path.join(DATA, f"{name}-{STAMP}.csv")
    if not os.path.exists(path):
        cands = sorted(glob.glob(os.path.join(DATA, f"{name}-????-??-??.csv")))
        cands = [c for c in cands if "-ytd-" not in c]
        if not cands:
            raise FileNotFoundError(f"no CSV for source '{name}' in {DATA}")
        path = cands[-1]
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- transactions
def collect_transactions():
    rows = read_csv("transactions")

    def shape(r):
        return (bool(re.match(r"^\d{4}-\d{2}-\d{2}", r.get("INSTANCE_DATE", ""))) and
                r.get("GROUP_EN") in {"Sales", "Mortgage", "Gifts"} and
                (num(r.get("TRANS_VALUE")) is None or 0 < num(r["TRANS_VALUE"]) < 5e9))

    def rng(clean):
        biggest = max((num(r["TRANS_VALUE"]) or 0) for r in clean)
        if biggest > 3e9:  # no single Dubai unit sale is > AED 3bn; bigger = a poisoned row
            raise SourceRejected(f"transactions: implausible max value {biggest}")

    rows = sanity_gate("transactions", rows, row_shape=shape,
                       min_rows=1000, max_rows=200000, sample=rng)

    sales = [r for r in rows if r["GROUP_EN"] == "Sales"]
    vals = [num(r["TRANS_VALUE"]) for r in sales if num(r["TRANS_VALUE"])]
    pps = [num(r["TRANS_VALUE"]) / num(r["ACTUAL_AREA"]) for r in sales
           if r["USAGE_EN"] == "Residential" and num(r["ACTUAL_AREA"])
           and num(r["ACTUAL_AREA"]) > 10 and num(r["TRANS_VALUE"])]
    area = Counter(r["AREA_EN"] for r in sales if r["AREA_EN"])
    dates = sorted(r["INSTANCE_DATE"][:10] for r in rows if r["INSTANCE_DATE"])

    # weekly sales counts + value for the trend strip
    weeks = Counter()
    week_val = Counter()
    for r in sales:
        d = r["INSTANCE_DATE"][:10]
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        wk = dt.strftime("%G-W%V")
        weeks[wk] += 1
        week_val[wk] += num(r["TRANS_VALUE"]) or 0
    weekly = [{"week": w, "sales": weeks[w], "valueAedBn": round(week_val[w] / 1e9, 2)}
              for w in sorted(weeks)]

    return {
        "totalRows": len(rows),
        "groups": dict(Counter(r["GROUP_EN"] for r in rows)),
        "periodFrom": dates[0], "periodTo": dates[-1],
        "salesCount": len(sales),
        "salesValueAedBn": round(sum(vals) / 1e9, 1),
        "medianTicketAed": round(statistics.median(vals)) if vals else None,
        "offPlanSplit": dict(Counter(r["IS_OFFPLAN_EN"] for r in sales)),
        "usageSplit": dict(Counter(r["USAGE_EN"] for r in sales)),
        "medianResidentialAedSqft": round(statistics.median(pps) / AED_PER_SQFT) if pps else None,
        "topAreas": [{"area": a, "sales": c} for a, c in area.most_common(10)],
        "weekly": weekly,
    }


# ---------------------------------------------------------------- valuations
def collect_valuations():
    rows = read_csv("valuations")

    def shape(r):
        v = num(r.get("PROPERTY_TOTAL_VALUE"))
        return (bool(re.match(r"^\d{4}-\d{2}-\d{2}", r.get("INSTANCE_DATE", ""))) and
                (v is None or 0 <= v < 5e9))

    rows = sanity_gate("valuations", rows, row_shape=shape, min_rows=100, max_rows=50000)
    vals = [num(r["PROPERTY_TOTAL_VALUE"]) for r in rows if num(r.get("PROPERTY_TOTAL_VALUE"))]
    return {
        "count": len(rows),
        "medianValueAed": round(statistics.median(vals)) if vals else None,
        "byType": dict(Counter(r.get("PROPERTY_TYPE_EN", "") for r in rows).most_common(6)),
    }


# ---------------------------------------------------------------- projects
def collect_projects():
    rows = read_csv("projects")

    def shape(r):
        pc = num(r.get("PERCENT_COMPLETED"))
        return r.get("PROJECT_EN") and (pc is None or 0 <= pc <= 100)

    rows = sanity_gate("projects", rows, row_shape=shape, min_rows=10, max_rows=5000)
    active = [r for r in rows if (num(r.get("PERCENT_COMPLETED")) or 0) < 100]
    units = sum(dwelling_count(r) for r in rows)

    # v43 — SUPPLY + ESCROW layer from the DLD registered-projects sample. Per-area incoming
    # units and delivery schedule (supply pressure), plus a project lookup carrying the
    # escrow-account and %-complete facts Launch Mode uses to verify a pitch against the register.
    def units_of(r):
        return dwelling_count(r)
    supply_area, deliver_year = {}, {}
    lookup = []
    for r in rows:
        area = (r.get("AREA_EN") or "").strip()
        u = units_of(r)
        end = (r.get("END_DATE") or "")[:10]
        yr = end[:4]
        if area:
            e = supply_area.setdefault(area, {"units": 0, "projects": 0, "nextEnd": None})
            e["units"] += u
            e["projects"] += 1
            if end and (e["nextEnd"] is None or end < e["nextEnd"]):
                e["nextEnd"] = end
        if yr.isdigit():
            deliver_year[yr] = deliver_year.get(yr, 0) + u
        lookup.append({
            "project": (r.get("PROJECT_EN") or "")[:60],
            "developer": (r.get("DEVELOPER_EN") or "")[:50],
            "area": area,
            "startDate": (r.get("START_DATE") or "")[:10] or None,
            "endDate": end or None,
            "percentComplete": num(r.get("PERCENT_COMPLETED")),
            "status": r.get("PROJECT_STATUS") or None,
            "units": u,
            "villas": int(num(r.get("CNT_VILLA")) or 0),
            "buildings": int(num(r.get("CNT_BUILDING")) or 0),
            "escrowRegistered": bool((r.get("ESCROW_ACCOUNT_NUMBER") or "").strip()),
        })

    return {
        "count": len(rows),
        "activeCount": len(active),
        "unitsInPipeline": units,
        "byStatus": dict(Counter(r.get("PROJECT_STATUS", "") for r in rows)),
        "topDevelopers": [{"developer": d, "projects": c} for d, c in
                          Counter(r.get("DEVELOPER_EN", "") for r in rows if r.get("DEVELOPER_EN")).most_common(5)],
        "coverageNote": ("DLD registered-projects open sample — incoming supply and escrow/%-complete "
                         "for the projects it contains; not the full register. Escrow 'registered' means a "
                         "trust account number is on file, not the balance."),
        "supplyByArea": {a: e for a, e in sorted(supply_area.items(), key=lambda x: -x[1]["units"])},
        "deliveryByYear": {y: deliver_year[y] for y in sorted(deliver_year)},
        "projectLookup": lookup,
    }


# ---------------------------------------------------------------- brokers  (PII: counts ONLY)
def collect_brokers():
    rows = read_csv("brokers")

    def shape(r):
        return bool(r.get("BROKER_NUMBER"))

    rows = sanity_gate("brokers", rows, row_shape=shape, min_rows=1000, max_rows=200000)
    # 🔴 PII rule (§2.6): BROKER_EN / PHONE / FAX must never leave this function.
    return {
        "licensedBrokers": len(rows),
        "byGender": dict(Counter(r.get("GENDER_EN", "") for r in rows)),
        "brokerages": len({r.get("REAL_ESTATE_NUMBER") for r in rows if r.get("REAL_ESTATE_NUMBER")}),
    }


# ---------------------------------------------------------------- MEED context (via Digital Abbot Cloud)
# The MEED corpus is a STATIC context layer — it is not refreshed with the DLD pulse.
# Detail comes from local dossier snapshots (asAt 2026-08-19); corpus freshness comes from
# the Digital Abbot Cloud API (status 1u + stats 2u — frugal on quota). The DAC key lives
# in .env (gitignored) and must NEVER appear in code or in any published output.
MEED_DIR = os.environ.get("MEED_SNAPSHOT_DIR",
                          r"C:\Users\kwils\Downloads\MEED\MEED")

# DLD AREA_EN names are inconsistently cased — always match lowercased.
# Mapping confidence is stated per development; never guess an area (HANDOVER lesson).
MEED_DEV_MAP = [
    {"file": "1-eywa.json", "dev": "EYWA", "developer": "R.Evolution",
     "dldAreas": ["business bay"], "mapNote": "Business Bay / Dubai Water Canal — confirmed"},
    {"file": "2-sha-residences.json", "dev": "SHA Residences", "developer": "Imkan",
     "dldAreas": [], "mapNote": "Al Jurf, Abu Dhabi — outside DLD coverage"},
    {"file": "3-treppan-living.json", "dev": "Treppan Living", "developer": "Fakhruddin Properties",
     "dldAreas": ["jumeirah village triangle", "palm deira"],
     "mapNote": "JVT confirmed; Dubai Islands registers in DLD as Palm Deira"},
    {"file": "4-masaar.json", "dev": "Masaar", "developer": "ARADA",
     "dldAreas": [], "mapNote": "Sharjah — outside DLD coverage"},
    {"file": "5-ghaf-woods.json", "dev": "Ghaf Woods", "developer": "Majid Al Futtaim",
     "dldAreas": [], "mapNote": "Dubailand — DLD area name not yet confirmed; unmapped rather than guessed"},
]


def _area_pulse(sales, area_keys):
    """DLD demand stats for a set of lowercased AREA_EN names."""
    rows = [r for r in sales if r["AREA_EN"].lower() in area_keys]
    if not rows:
        return None
    vals = [num(r["TRANS_VALUE"]) for r in rows if num(r["TRANS_VALUE"])]
    pps = [num(r["TRANS_VALUE"]) / num(r["ACTUAL_AREA"]) for r in rows
           if r["USAGE_EN"] == "Residential" and num(r["ACTUAL_AREA"])
           and num(r["ACTUAL_AREA"]) > 10 and num(r["TRANS_VALUE"])]
    off = Counter(r["IS_OFFPLAN_EN"] for r in rows)
    return {
        "salesCount": len(rows),
        "salesValueAedM": round(sum(vals) / 1e6) if vals else 0,
        "medianTicketAed": round(statistics.median(vals)) if vals else None,
        "medianResidentialAedSqft": round(statistics.median(pps) / AED_PER_SQFT) if pps else None,
        "offPlanPct": round(100 * off.get("Off-Plan", 0) / len(rows)) if rows else None,
    }


def collect_meed(sales):
    # 1. Corpus freshness from Digital Abbot Cloud (fails soft — snapshot detail still ships)
    corpus = None
    key = os.environ.get("DAC_KEY")
    if not key and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("DAC_KEY="):
                key = line.split("=", 1)[1].strip()
    if key:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://www.digitalabbot.io/api/cloud/v1/meed/status",
                headers={"x-dac-key": key})
            with urllib.request.urlopen(req, timeout=20) as resp:
                st = json.load(resp)["data"]
            c = st.get("corpus", {})
            # sanity gate: shape + plausible band, fail closed to quarantine
            if not (isinstance(c.get("projects"), int) and 5000 < c["projects"] < 200000):
                raise SourceRejected(f"meed: implausible corpus count {c.get('projects')}")
            corpus = {"projects": c["projects"], "version": c.get("version"),
                      "lastSyncAt": c.get("lastSyncAt"),
                      "archived": st.get("detailArchive", {}).get("archived"),
                      "live": False,
                      "servedBy": "Digital Abbot Cloud (DigitAlchemy stored MEED corpus)"}
        except SourceRejected:
            raise
        except Exception as e:
            print(f"  meed: DAC status unreachable ({e}) — shipping snapshot detail only")

    # 2. Development detail from the local dossier snapshots
    devs = []
    as_at = None
    for m in MEED_DEV_MAP:
        path = os.path.join(MEED_DIR, m["file"])
        if not os.path.exists(path):
            print(f"  meed: snapshot missing {m['file']} — skipped")
            continue
        d = json.load(open(path, encoding="utf-8"))
        as_at = d.get("asAt") or as_at
        ds = d.get("dossiers", [])

        def shape(r):
            v = r.get("valueUsdM")
            p = r.get("progressPercent")
            return (str(r.get("projectId", "")).isdigit() and r.get("stage") and
                    (v is None or 0 < v < 50000) and (p is None or 0 <= p <= 100))

        ds = sanity_gate(f"meed:{m['dev']}", ds, row_shape=shape, min_rows=1, max_rows=100)
        live = [r for r in ds if r["stage"] not in {"complete", "cancelled"}]
        vals = [r["valueUsdM"] for r in live if r.get("valueUsdM")]
        devs.append({
            "development": m["dev"], "developer": m["developer"],
            "location": d.get("spec", {}).get("location"),
            "projects": len(ds), "activeProjects": len(live),
            "pipelineValueUsdM": round(sum(vals)),   # MEED estimates — label as such
            "stages": dict(Counter(r["stage"] for r in ds)),
            "nextCompletion": min((r.get("completionDate") for r in live
                                   if r.get("completionDate")), default=None),
            "dldPulse": _area_pulse(sales, set(m["dldAreas"])),
            "mapNote": m["mapNote"],
        })

    return {
        "static": True,
        "note": "MEED context is a fixed snapshot mapped against the refreshed DLD pulse — it is not updated with it.",
        "snapshotAsAt": as_at,
        "corpus": corpus,
        "valueDisclaimer": "Project values are MEED estimates in US$; progress is editorial, not measured.",
        "attribution": "Project data licensed from MEED Projects (GlobalData), served via Digital Abbot Cloud.",
        "developments": devs,
    }


# ---------------------------------------------------------------- monthly YTD trend
def collect_monthly_ytd():
    """Full-year monthly series from the year-to-date transactions file. Note: the register
    back-fills — the 8-week window in this file ran ~3% above the earlier same-day capture.
    Capture time matters; each pulse carries its own stamp."""
    import glob
    ytd = sorted(glob.glob(os.path.join(DATA, "transactions-ytd-*.csv")))
    if not ytd:
        raise SourceRejected("monthly: no YTD transactions file present")
    path = ytd[-1]
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    def shape(r):
        return (bool(re.match(r"^\d{4}-\d{2}-\d{2}", r.get("INSTANCE_DATE", ""))) and
                r.get("GROUP_EN") in {"Sales", "Mortgage", "Gifts"} and
                (num(r.get("TRANS_VALUE")) is None or 0 < num(r["TRANS_VALUE"]) < 5e9))

    rows = sanity_gate("transactions-ytd", rows, row_shape=shape,
                       min_rows=50000, max_rows=1000000)
    sales = [r for r in rows if r["GROUP_EN"] == "Sales"]
    months, mval = Counter(), Counter()
    for r in sales:
        m = r["INSTANCE_DATE"][:7]
        months[m] += 1
        mval[m] += num(r["TRANS_VALUE"]) or 0
    vals = [num(r["TRANS_VALUE"]) for r in sales if num(r["TRANS_VALUE"])]
    return {
        "ytdSales": len(sales),
        "ytdValueAedBn": round(sum(vals) / 1e9, 1),
        "series": [{"month": m, "sales": months[m], "valueAedBn": round(mval[m] / 1e9, 1)}
                   for m in sorted(months)],
        "note": "Current month is partial; the register also back-fills prior days.",
    }


# ---------------------------------------------------------------- handover radar
def collect_handover():
    """What is handing over, bucketed by quarter — from the MEED dossier snapshots
    (near-term, package-level) and the DLD projects register (registered pipeline horizon).
    DLD COMPLETION_DATE is empty in the current file; END_DATE is the usable horizon."""
    def bucket(datestr):
        if not datestr:
            return None
        y, m = int(datestr[:4]), int(datestr[5:7])
        return f"{y}-Q{(m - 1) // 3 + 1}"

    # MEED: active packages across the tracked developments
    meed_buckets = {}
    for mdef in MEED_DEV_MAP:
        path = os.path.join(MEED_DIR, mdef["file"])
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        for ds in d.get("dossiers", []):
            if ds.get("stage") in {"complete", "cancelled"}:
                continue
            b = bucket(ds.get("completionDate"))
            if not b:
                continue
            e = meed_buckets.setdefault(b, {"packages": 0, "valueUsdM": 0, "items": []})
            e["packages"] += 1
            e["valueUsdM"] += ds.get("valueUsdM") or 0
            e["items"].append({"dev": mdef["dev"],
                               "title": ds.get("title", "")[:60],
                               "progressPercent": ds.get("progressPercent"),
                               "completionDate": ds.get("completionDate")})

    # DLD registered pipeline: units by END_DATE quarter
    dld_buckets = {}
    for r in read_csv("projects"):
        b = bucket(r.get("END_DATE", ""))
        if not b:
            continue
        e = dld_buckets.setdefault(b, {"projects": 0, "units": 0})
        e["projects"] += 1
        e["units"] += dwelling_count(r)

    return {
        "note": ("MEED = package-level handovers across the tracked developments (fixed snapshot). "
                 "DLD = registered-project pipeline horizon by END_DATE. Dates are declared, not audited."),
        "meedByQuarter": dict(sorted(meed_buckets.items())),
        "dldByQuarter": dict(sorted(dld_buckets.items())),
    }


# ---------------------------------------------------------------- area intelligence (the matching substrate)
def _room_bucket(r):
    """Normalise ROOMS_EN into coarse buckets the broker actually uses."""
    s = (r.get("ROOMS_EN") or "").strip().lower()
    if not s:
        return None
    if "studio" in s:
        return "Studio"
    m = re.match(r"^(\d+)", s)
    if m:
        n = int(m.group(1))
        return f"{n} B/R" if n <= 5 else "6+ B/R"
    return None


# Typical annual service charge, AED per sq ft, by community — from RERA / Mollak PUBLISHED
# service-charge index ranges (labelled as typical; a building-specific Mollak figure, once the
# dataset is licensed, overrides this per area). Villa communities sit low (no shared cooling/
# lifts); chiller-and-amenity towers sit high. Unlisted apartment areas default to 16.
SERVICE_CHARGE_AED_SQFT = {
    "palm jumeirah": 28, "downtown dubai": 24, "burj khalifa": 26, "dubai marina": 22,
    "marsa dubai": 22, "jumeirah beach residence": 22, "business bay": 20, "difc": 30,
    "bluewaters": 27, "city walk": 24, "jumeirah lakes towers": 18, "dubai hills estate": 15,
    "sobha hartland": 18, "dubai creek harbour": 18, "meydan": 16, "jumeirah village circle": 13,
    "jumeirah village triangle": 12, "arjan": 12, "majan": 12, "al furjan": 13, "discovery gardens": 11,
    "international city": 9, "dubai south": 10, "madinat al mataar": 10, "town square": 10,
    "the valley": 6, "damac hills": 12, "damac hills 2": 8, "tilal al ghaf": 10,
    "dubai land residence complex": 11, "city of arabia": 11, "liwan": 11,
    # villa / townhouse communities — materially lower
    "arabian ranches": 5, "the springs": 5, "the meadows": 5, "mudon": 6, "villanova": 6,
    "serena": 6, "wadi al safa 5": 7, "wadi al safa 7": 7, "hadaeq sheikh mohammed bin rashid": 7,
    "nad al sheba": 7, "al barsha": 12, "jabal ali first": 11,
}
SERVICE_CHARGE_DEFAULT = 16   # typical mid-tier Dubai apartment


def collect_area_intel(sales_rows, rents_yields):
    """Per-area, per-room reality from the register — what a given budget ACTUALLY buys,
    the settled price (never asking), the off-plan split, and the yield where known.
    This is what turns 'client has 1.5M, wants a 1-bed' into a sourced recommendation.
    Residential only; areas with < 20 residential sales are omitted (too thin to advise on)."""
    yields = {y["area"].lower(): y["yieldPct"] for y in (rents_yields or [])}
    by_area = {}
    for r in sales_rows:
        if r.get("USAGE_EN") != "Residential":
            continue
        v, a = num(r.get("TRANS_VALUE")), num(r.get("ACTUAL_AREA"))
        if not v or v <= 0:
            continue
        area = (r.get("AREA_EN") or "").strip()
        if not area:
            continue
        e = by_area.setdefault(area, {"vals": [], "psf": [], "off": Counter(), "rooms": {}})
        e["vals"].append(v)
        if a and a > 10:
            e["psf"].append(v / a)
        e["off"][r.get("IS_OFFPLAN_EN") or ""] += 1
        rb = _room_bucket(r)
        if rb:
            e["rooms"].setdefault(rb, []).append(v)

    out = []
    for area, e in by_area.items():
        n = len(e["vals"])
        if n < 20:
            continue
        off = e["off"]
        rooms = {}
        for rb, vals in e["rooms"].items():
            if len(vals) >= 8:                       # only advise on room types with real depth
                rooms[rb] = {
                    "sales": len(vals),
                    "medianAed": round(statistics.median(vals)),
                    "p25Aed": round(statistics.quantiles(vals, n=4)[0]) if len(vals) >= 4 else None,
                    "p75Aed": round(statistics.quantiles(vals, n=4)[2]) if len(vals) >= 4 else None,
                }
        sc = SERVICE_CHARGE_AED_SQFT.get(area.lower(), SERVICE_CHARGE_DEFAULT)
        sc_est = area.lower() not in SERVICE_CHARGE_AED_SQFT
        gross = yields.get(area.lower())
        psf_sale = round(statistics.median(e["psf"]) / AED_PER_SQFT) if e["psf"] else None
        # net yield = gross − (annual service charge / sale price per sq ft). Both per sq ft/yr.
        net = None
        if gross is not None and psf_sale:
            net = round(gross - 100 * sc / psf_sale, 1)
        out.append({
            "area": area,
            "sales": n,
            "medianTicketAed": round(statistics.median(e["vals"])),
            "medianAedSqft": psf_sale,
            "offPlanPct": round(100 * off.get("Off-Plan", 0) / n),
            "grossYieldPct": gross,
            "serviceChargeAedSqftYr": sc,
            "serviceChargeIsEstimate": sc_est,
            "netYieldPct": net,
            "byRoom": rooms,
        })
    out.sort(key=lambda x: -x["sales"])
    return {
        "note": ("Per-area settled prices from the DLD register — what actually transacted, not asking prices. "
                 "Residential only; areas with < 20 sales omitted; room types shown only where >= 8 sales. "
                 "Net yield = gross yield minus service charge; service charge from RERA published community "
                 "ranges (typical — a building-specific Mollak figure overrides). Use to match a client budget."),
        "areas": out[:60],
    }


# ---------------------------------------------------------------- rents (Ejari) — REAL
def collect_rents(sales_rows):
    """Registered rental contracts. Shape rule learned on first contact with the data:
    TOTAL_PROPERTIES > 1 rows are bulk building/staff-accommodation leases — one such
    cluster put Dubai Investment Park Second at a fictional 48.9% gross yield. Singles only.
    Yields carry a canary band: an area outside 1.5–12% is excluded WITH its reason."""
    rows = read_csv("rents")

    def shape(r):
        amt = num(r.get("ANNUAL_AMOUNT"))
        return (bool(re.match(r"^\d{4}-\d{2}-\d{2}", r.get("REGISTRATION_DATE", ""))) and
                r.get("VERSION_EN") in {"New", "Renewed"} and
                (amt is None or 1000 < amt < 5e6))

    rows = sanity_gate("rents", rows, row_shape=shape, min_rows=500, max_rows=500000)
    dates = sorted((r["REGISTRATION_DATE"] or "")[:10] for r in rows if r["REGISTRATION_DATE"])

    res = [r for r in rows
           if r["USAGE_EN"] == "Residential" and num(r.get("ANNUAL_AMOUNT"))
           and r.get("PROP_TYPE_EN") in {"Unit", "Villa"}
           and (num(r.get("TOTAL_PROPERTIES")) or 1) == 1]
    amts = [num(r["ANNUAL_AMOUNT"]) for r in res]
    rps = [num(r["ANNUAL_AMOUNT"]) / num(r["ACTUAL_AREA"]) for r in res
           if num(r.get("ACTUAL_AREA")) and 10 < num(r["ACTUAL_AREA"]) < 10000]

    # gross yields: median rent-psf / median sale-psf per area, both sides >= 30 samples
    rent_area, sale_area = {}, {}
    for r in res:
        a = num(r.get("ACTUAL_AREA"))
        if a and 10 < a < 10000:
            rent_area.setdefault(r["AREA_EN"].lower(), []).append(num(r["ANNUAL_AMOUNT"]) / a)
    for r in sales_rows:
        if r["USAGE_EN"] == "Residential":
            v, a = num(r["TRANS_VALUE"]), num(r["ACTUAL_AREA"])
            if v and a and a > 10:
                sale_area.setdefault(r["AREA_EN"].lower(), []).append(v / a)
    yields, excluded = [], []
    for ar, rl in rent_area.items():
        sl = sale_area.get(ar, [])
        if len(rl) >= 30 and len(sl) >= 30:
            y = round(100 * statistics.median(rl) / statistics.median(sl), 1)
            if 1.5 <= y <= 12:
                yields.append({"area": ar.title(), "yieldPct": y,
                               "rentSamples": len(rl), "saleSamples": len(sl)})
            else:
                excluded.append({"area": ar.title(), "yieldPct": y,
                                 "reason": "outside 1.5-12% canary band — mix distortion suspected"})
    yields.sort(key=lambda x: -x["yieldPct"])

    return {
        "registrationFrom": dates[0], "registrationTo": dates[-1],
        "contractsCount": len(rows),
        "versionSplit": dict(Counter(r["VERSION_EN"] for r in rows)),
        "residentialSingles": len(res),
        "medianAnnualRentAed": round(statistics.median(amts)) if amts else None,
        "medianRentAedSqftYr": round(statistics.median(rps) / AED_PER_SQFT, 1) if rps else None,
        "grossYieldPctByArea": yields[:8],
        "excludedYields": excluded,
        "yieldNote": ("Gross yield = median registered rent per sq ft over median sale price per sq ft, "
                      "same area, both sides >= 30 contracts. Registered contracts, not asking rates."),
    }


def main():
    global STAMP
    STAMP = _newest_stamp()
    os.makedirs(PUB, exist_ok=True)
    prev = {}
    prev_path = os.path.join(PUB, "pulse.json")
    if os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path))
        except Exception:
            pass
    out = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "dataCaptured": STAMP,
           "attribution": ATTRIBUTION}
    quarantine = {}
    for name, fn in {"transactions": collect_transactions,
                     "valuations": collect_valuations,
                     "projects": collect_projects,
                     "brokers": collect_brokers}.items():
        try:
            out[name] = fn()
        except SourceRejected as e:
            quarantine[name] = str(e)
            print("QUARANTINED", name, e)
    sales_rows = [r for r in read_csv("transactions") if r["GROUP_EN"] == "Sales"]
    try:
        out["rents"] = collect_rents(sales_rows)
    except SourceRejected as e:
        quarantine["rents"] = str(e)
        print("QUARANTINED rents", e)
    try:
        out["monthly"] = collect_monthly_ytd()
    except SourceRejected as e:
        quarantine["monthly"] = str(e)
        print("QUARANTINED monthly", e)
    try:
        _yields = (out.get("rents") or {}).get("grossYieldPctByArea")
        out["areaIntel"] = collect_area_intel(sales_rows, _yields)
    except Exception as e:
        quarantine["areaIntel"] = str(e)
        print("QUARANTINED areaIntel", e)
    # MEED context + handover radar are a FIXED snapshot layer. When the snapshot dir is
    # absent (e.g. the weekly Action), carry the blocks forward from the previous pulse.
    if os.path.isdir(MEED_DIR):
        try:
            out["meed"] = collect_meed(sales_rows)
        except SourceRejected as e:
            quarantine["meed"] = str(e)
            print("QUARANTINED meed", e)
        try:
            out["handover"] = collect_handover()
        except SourceRejected as e:
            quarantine["handover"] = str(e)
            print("QUARANTINED handover", e)
    else:
        for block in ("meed", "handover"):
            if prev.get(block):
                out[block] = prev[block]
                print(f"  {block}: snapshot dir absent — carried forward from previous pulse")
    if quarantine:
        out["quarantine"] = quarantine
    with open(os.path.join(PUB, "pulse.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote public/pulse.json")

    # §9 known-good validation — only meaningful against the capture it was pinned to.
    # Weekly refreshes get structural checks via the gates; the register back-fills, so
    # re-running old expectations against new data would fail for the wrong reason.
    if STAMP != KNOWN_GOOD_STAMP:
        print(f"\nS9 VALIDATION: skipped (capture {STAMP}, known-good pinned to {KNOWN_GOOD_STAMP})")
        sys.exit(0)
    t = out.get("transactions", {})
    checks = [
        ("totalRows", t.get("totalRows"), 32855),
        ("sales", t.get("groups", {}).get("Sales"), 24049),
        ("mortgage", t.get("groups", {}).get("Mortgage"), 7530),
        ("gifts", t.get("groups", {}).get("Gifts"), 1276),
        ("salesValueAedBn", t.get("salesValueAedBn"), 57.3),
        ("medianTicketAed", t.get("medianTicketAed"), 1151232),
        ("offPlan", t.get("offPlanSplit", {}).get("Off-Plan"), 16669),
        ("ready", t.get("offPlanSplit", {}).get("Ready"), 7380),
        ("residential", t.get("usageSplit", {}).get("Residential"), 23603),
        ("commercial", t.get("usageSplit", {}).get("Commercial"), 446),
        ("medianResSqft", t.get("medianResidentialAedSqft"), 1687),
    ]
    bad = [(k, got, want) for k, got, want in checks if got != want]
    print("\nS9 VALIDATION:", "ALL PASS" if not bad else "MISMATCH")
    for k, got, want in bad:
        print(f"  {k}: got {got}, expected {want}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
