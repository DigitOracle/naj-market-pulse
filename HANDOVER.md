# Market Pulse — Build Handover

**A complete, standalone brief for building a Dubai real-estate market dashboard + content engine
from official Dubai Land Department (DLD) open data.**

Written 25 Aug 2026. This document assumes **zero prior context** — it is written to be dropped into a
fresh GitHub repo and handed to a Claude that has never seen any of this. Read it top to bottom before
writing any code. Everything you need is here.

---

## 0. What you are building, and why

**The goal:** replace the habit of quoting *other brokerages'* market reports with **your own**, built
from the same official government data those reports are built on — serving two products:

1. **A dashboard** — a page you open on your phone that shows where the Dubai property market is right now.
2. **A content engine** — verified figures and story angles that turn into short advisory videos and posts.

**The core insight that makes this worth doing:** the paid market-intelligence products (District, Property
Monitor, dldtracker, etc.) are **enrichment layers over free public DLD data.** The data is free and
official. Only the polishing is theirs. You can build the same thing from the same source and **own the
brand instead of citing someone else's** — which, for a broker whose whole positioning is personal
authority, is the difference between borrowing credibility and building it.

**Focus of this handover: the Dubai Land Department (DLD).** Other free sources exist (§11) and slot into
the same architecture later, but DLD alone gives you a complete, defensible product.

---

## 1. 🔴 THE ONE RULE THAT MATTERS MOST — the Source Sanity Gate

Before anything else, internalise this, because it is the lesson that will save you from putting a wrong
number in front of an audience.

**During research for this project, one DLD endpoint (the price-index GraphQL API) was found serving
POISONED data** — anonymous parties had injected junk rows into it:
`indexType:"HACK_TEST" index:99.99`, `index:777.77`, `monthDate:"test-pentest"`, and NoSQL-injection
strings as values. **Had it been wired in naively, the dashboard would have shown a Dubai price index of
777.77 — and it could have been quoted on camera.**

**Therefore: NO data source is ever wired in until it passes a sanity gate, in code, that FAILS CLOSED.**
A source that cannot pass is quarantined, never "temporarily allowed." Every dataset reader you write MUST:

1. **Shape allow-list** — accept only rows whose fields match an expected shape (real ISO dates, known
   category values, numeric values in a plausible band). Reject everything else on sight.
2. **Range canary** — assert each headline figure sits in a defensible band. Out of band → drop the whole
   source for that run and flag it loudly, never silently average it in.
3. **Volume canary** — assert the clean row count is within an expected range of last time. A sudden
   collapse or explosion fails the source.
4. **Freshness stamp** — every source carries its capture date into the output; the dashboard shows it and
   refuses to speak on stale data.
5. **READ ONLY, ALWAYS** — your code issues reads/downloads only. **Never a write/mutation against any
   source, however open the door is left.** (That open write door on the price index is DLD's security
   problem to fix — reported separately — never something to use.)
6. **Quarantine on failure** — a source failing 1–3 is excluded from the published output and recorded with
   its reason, so bad data can reach a human reviewer but never the dashboard, a brief, or a video.

**Rule of thumb: if you cannot describe the shape of a valid row before you fetch it, you are not ready to
wire the source in.** A runnable gate is in §7 — use it for every dataset.

---

## 2. The data — six free DLD datasets (verified, real, in hand)

All six download as **CSV, free**, from **`dubailand.gov.ae` → Open Data → Real Estate Data**. Filter by
date range / area / type, click **Download as CSV**. Current year is served directly; previous years via
**Dubai Pulse** (now redirecting to **data.dubai**). These were pulled live on 25 Aug 2026 and the schemas
below are the **real column headers**.

### 2.1 `transactions` — THE CORE (≈24k sales/8 weeks)

The demand side. Every registered sale, mortgage and gift.

```
TRANSACTION_NUMBER, INSTANCE_DATE, GROUP_EN, PROCEDURE_EN, IS_OFFPLAN_EN, IS_FREE_HOLD_EN,
USAGE_EN, AREA_EN, PROP_TYPE_EN, PROP_SB_TYPE_EN, TRANS_VALUE, PROCEDURE_AREA, ACTUAL_AREA,
ROOMS_EN, PARKING, NEAREST_METRO_EN, NEAREST_MALL_EN, NEAREST_LANDMARK_EN, TOTAL_BUYER,
TOTAL_SELLER, MASTER_PROJECT_EN, PROJECT_EN
```

🔑 **Critical gotchas:**
- `GROUP_EN` is **`Sales` | `Mortgage` | `Gifts`**. **For price/volume analysis, filter to `Sales` only** —
  mixing in mortgages doubles-counts and distorts value.
- `IS_OFFPLAN_EN` = **`Off-Plan` | `Ready`** — the single most Dubai-specific story (off-plan runs ~70%).
- `TRANS_VALUE` is AED, a string — parse to float, skip non-numeric.
- **Price per area** = `TRANS_VALUE / ACTUAL_AREA` (AED per m²; ÷ 10.7639 for per ft²). Only compute for
  `USAGE_EN == "Residential"` and `ACTUAL_AREA > 10`, or a land/whole-building row will produce nonsense.
- `USAGE_EN` = `Residential` | `Commercial`. Split them; never blend.

### 2.2 `valuations` — price cross-check (≈760 rows)
```
PROPERTY_TOTAL_VALUE, AREA_EN, ACTUAL_AREA, PROCEDURE_YEAR, PROCEDURE_NUMBER, INSTANCE_DATE,
ACTUAL_WORTH, PROCEDURE_AREA, PROPERTY_TYPE_EN, PROP_SUB_TYPE_EN
```
Official valuations — a sanity check against transaction prices, not a headline dataset.

### 2.3 `projects` — DLD supply pipeline (≈66 rows)
```
PROJECT_NUMBER, PROJECT_EN, DEVELOPER_NUMBER, DEVELOPER_EN, START_DATE, END_DATE, ADOPTION_DATE,
PRJ_TYPE_EN, PROJECT_VALUE, ESCROW_ACCOUNT_NUMBER, PROJECT_STATUS, PERCENT_COMPLETED,
INSPECTION_DATE, COMPLETION_DATE, DESCRIPTION_EN, AREA_EN, ZONE_EN, CNT_LAND, CNT_BUILDING,
CNT_VILLA, CNT_UNIT, MASTER_PROJECT_EN
```
🔑 Carries **`PERCENT_COMPLETED`, `ESCROW_ACCOUNT_NUMBER`, developer name, unit counts** — genuine off-plan
buyer-protection signal. Strong supporting data.

### 2.4 `rents` — YIELDS (⚠️ NOT YET DOWNLOADED — grab this one)
Same page, Rents tab → Download as CSV. **This is the yield half, and it is FREE** (see §3). Download it;
its schema is Ejari rental contracts (rent value, area, property type, period). Add a reader following the
same pattern as transactions.

### 2.5 `lands` — parcels/stock context (≈262k rows)
```
LAND_TYPE_EN, PROP_SUB_TYPE_EN, ACTUAL_AREA, IS_OFFPLAN_EN, PRE_REGISTRATION_NUMBER,
IS_FREE_HOLD_EN, DM_ZIP_CODE, MASTER_PROJECT_EN, PROJECT_NUMBER, PROJECT_EN, AREA_EN, ZONE_EN
```
Reference, not front-page. Useful for zone/area context.

### 2.6 `brokers` — 🔴 CONTAINS PERSONAL DATA (≈43k rows)
```
BROKER_NUMBER, BROKER_EN, GENDER_EN, LICENSE_START_DATE, LICENSE_END_DATE, WEBPAGE, PHONE,
FAX, REAL_ESTATE_NUMBER, REAL_ESTATE_EN
```
🔴 **This file has names, gender, and PHONE numbers for 43,000 individuals.** It is fine as a private
lookup ("how many licensed brokers operate in area X") but **NO individual's name or phone may EVER appear
in a dashboard, a brief, a video, or any published output.** The aggregator must strip `BROKER_EN`,
`PHONE`, `FAX` before anything derived from this file is shown. Counts only, never people.

---

## 3. Free vs paid — you do NOT need to spend anything

| Half | Free source | Paid alternative |
|---|---|---|
| Sales / prices | `transactions` CSV | — |
| **Rents / yields** | **`rents` CSV (free)** | Rental Index API — **AED 30,000/yr + VAT** (real-time only) |
| Supply / projects | `projects` CSV | — |
| Valuations, stock, brokers | 3 more free CSVs | — |

🔑 **The AED 30k "Rental Index API" (on the DLD API Gateway) buys only *real-time* rents.** Monthly market
commentary does **not** need real-time. **Use the free Rents CSV.** Its eligibility also requires a trade
licence with specific IT activities *and* association with a real-estate management company — another reason
to skip it unless real-time rents ever prove worth the cost. **Recommendation: build entirely on free CSVs.**

---

## 4. Licence & attribution — the publication gate

- Dubai government open data is published under a **CC BY 4.0-style Open Data Licence** (Law 26/2015, Law
  2/2016) — **free reuse including commercial, with attribution.** ✅ You may publish *derived analysis*.
- 🔴 **Do NOT redistribute the raw CSVs in bulk.** Publish aggregates, charts and commentary — never a
  re-hosted copy of the source rows. (This is the standard open-data line and how the paid products stay
  compliant too.)
- **Attribution string to carry on every published figure and dashboard:**
  > *Source: Dubai Land Department (DLD) Open Data. Contains information from the Government of Dubai.*
- ⚠️ **Confirm the exact current Open Data Licence PDF** on data.dubai before first publication — "open"
  should be read, not assumed. It is a 5-minute read, and it is the gate before anything goes public.

---

## 5. Architecture for your site + GitHub (self-contained, no dependencies on anyone else's system)

```
  DLD Open Data (dubailand.gov.ae → Open Data → Download CSV)
        │   [human downloads monthly — a captcha blocks automation; see §6]
        ▼
  /data/*.csv  in your repo (or a private data folder)
        │
        ▼
  GitHub Actions  ──  scripts/build_pulse.py   (runs on a schedule, or on push)
        │   • read each CSV → SANITY GATE (§1, §7) → aggregate
        │   • ~all rows in, ONE small pulse.json out (a few KB)
        ▼
  public/pulse.json   (committed by the Action, or written to your host)
        │
        ├──►  your website reads pulse.json → renders the dashboard
        └──►  a "brief" step (optional) drafts content angles from the same JSON
```

**Why this shape:** the raw data is large (transactions alone is 8 MB; lands 30 MB). Your website must
**never parse raw CSVs in the browser** — the Action does the heavy lifting once and emits a tiny
`pulse.json` the site renders instantly. This is the standard "precompute to a small artifact" pattern and
it keeps the site fast and the raw data private.

**Recommended stack** (adapt to what your site already uses):
- **Aggregator:** Python (stdlib `csv` only — no heavy deps needed; a starter is in §8).
- **Scheduler:** GitHub Actions (`.github/workflows/pulse.yml`) on a monthly cron + manual trigger.
- **Site:** whatever you already run. It only needs to fetch one JSON file and draw tables/charts.

---

## 6. The two access routes (and why manual is fine to start)

1. **Manual CSV (works today, $0):** download the CSVs monthly (2 clicks each), drop them in `/data`,
   commit, the Action rebuilds `pulse.json`. A captcha on the download means a human must click — that's
   fine for monthly commentary. **Start here.**
2. **Automated API (later):** DLD issues an **API Key + Secret** (arrives as two emails) after you register
   an account and request dataset access on **data.dubai** / the DLD portal. When you have it, swap the CSV
   reader for an API fetch — **the aggregation and the sanity gate do not change.** Do not block launch on this.

⚠️ **Never scrape the site or drive its forms with a bot** — there are Selenium scrapers on GitHub for this;
they are fragile and outside the site's terms. Official CSV or official API only. A scraped number is not
defensible on camera; that defensibility is the whole point.

---

## 7. The Source Sanity Gate — drop-in code (use for EVERY dataset)

```python
class SourceRejected(Exception):
    """A source failed its sanity gate. Quarantine it — never average it in."""

def sanity_gate(source, rows, *, row_shape, min_rows, max_rows, sample=None):
    """Fail CLOSED. Returns only rows passing row_shape; raises SourceRejected if the source
    as a whole looks poisoned, collapsed or exploded. (Built after the DLD price-index
    poisoning: HACK_TEST / 777.77 / test-pentest rows must be dropped, and if too few clean
    rows survive, the whole source is refused rather than shipping garbage.)"""
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
        sample(clean)     # raises SourceRejected on out-of-band headline values
    return clean
```

---

## 8. Starter aggregator — runnable, real (adapt & extend)

Save as `scripts/build_pulse.py`. Run: `python scripts/build_pulse.py`. Reads the CSVs in `./data/`,
writes `public/pulse.json`. This is the transactions core; add `rents`, `projects` the same way.

```python
import csv, json, statistics, re, sys
from collections import Counter
from datetime import datetime, timezone
# (paste sanity_gate + SourceRejected from §7 here)

DATA = "data"
AED_PER_SQFT = 10.7639
STAGES = None  # transactions has no stage; kept for parity with other sources

def num(x):
    try: return float(x)
    except: return None

def collect_transactions():
    rows = list(csv.DictReader(open(f"{DATA}/transactions-2026-08-25.csv", encoding="utf-8-sig")))
    def shape(r):
        return (bool(re.match(r"^\d{4}-\d{2}-\d{2}", r.get("INSTANCE_DATE",""))) and
                r.get("GROUP_EN") in {"Sales","Mortgage","Gifts"} and
                (num(r.get("TRANS_VALUE")) is None or 0 < num(r["TRANS_VALUE"]) < 5e9))
    def rng(clean):
        biggest = max((num(r["TRANS_VALUE"]) or 0) for r in clean)
        if biggest > 3e9:  # no single Dubai unit sale is > AED 3bn; bigger = a poisoned row
            raise SourceRejected(f"transactions: implausible max value {biggest}")
    rows = sanity_gate("transactions", rows, row_shape=shape,
                       min_rows=1000, max_rows=200000, sample=rng)

    sales = [r for r in rows if r["GROUP_EN"] == "Sales"]
    vals = [num(r["TRANS_VALUE"]) for r in sales if num(r["TRANS_VALUE"])]
    pps = [num(r["TRANS_VALUE"])/num(r["ACTUAL_AREA"]) for r in sales
           if r["USAGE_EN"]=="Residential" and num(r["ACTUAL_AREA"]) and num(r["ACTUAL_AREA"])>10
           and num(r["TRANS_VALUE"])]
    area = Counter(r["AREA_EN"] for r in sales if r["AREA_EN"])
    dates = sorted(r["INSTANCE_DATE"][:10] for r in rows if r["INSTANCE_DATE"])

    return {
        "source": "Dubai Land Department (DLD) Open Data",
        "periodFrom": dates[0], "periodTo": dates[-1],
        "salesCount": len(sales),
        "salesValueAedBn": round(sum(vals)/1e9, 1),
        "medianTicketAed": round(statistics.median(vals)) if vals else None,
        "offPlanSplit": dict(Counter(r["IS_OFFPLAN_EN"] for r in sales)),
        "usageSplit": dict(Counter(r["USAGE_EN"] for r in sales)),
        "medianResidentialAedSqft": round(statistics.median(pps)/AED_PER_SQFT) if pps else None,
        "topAreas": [{"area": a, "sales": c} for a, c in area.most_common(10)],
    }

def main():
    out = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "attribution": "Source: Dubai Land Department (DLD) Open Data. "
                          "Contains information from the Government of Dubai."}
    quarantine = {}
    for name, fn in {"transactions": collect_transactions}.items():
        try: out[name] = fn()
        except SourceRejected as e: quarantine[name] = str(e); print("QUARANTINED", name, e)
    if quarantine: out["quarantine"] = quarantine
    json.dump(out, open("public/pulse.json", "w"), indent=1)
    print("wrote public/pulse.json")

if __name__ == "__main__":
    main()
```

---

## 9. 🔑 Known-good validation numbers — check your output against these

Your aggregator, run against the 25 Aug 2026 transactions CSV (period **30 Jun – 25 Aug 2026**), MUST
reproduce these. If it doesn't, something is wrong — do not publish until it matches:

| Figure | Value |
|---|---|
| Total rows | 32,855 |
| Groups | Sales 24,049 · Mortgage 7,530 · Gifts 1,276 |
| **Sales value** | **AED 57.3 billion** |
| Median sale ticket | AED 1,151,232 |
| Off-plan split | Off-Plan 16,669 · Ready 7,380 (≈69% off-plan) |
| Usage | Residential 23,603 · Commercial 446 |
| Median residential | ~AED 1,687 / sq ft |
| Value range (sales) | AED 163 → 675,000,000 |
| Junk rows | 0 (clean government CSV) |

These double as your **first content angles**, already sourced: *"Dubai registered AED 57 billion in sales
over eight weeks — 7 in 10 off-plan."*

---

## 10. Turning data into content (the second product)

Each refresh, generate a short **brief** (not a finished script — a brief): three candidate story angles
ranked by how unusual the movement is, each with its exact figure and the attribution line, one line of
"what this means for a buyer," and a final **what-NOT-to-claim** line. Rules for any figure that reaches a
video or post:
- **Every number carries its source and period.** No exceptions. This is what makes it defensible.
- **Transactions ≠ asking prices.** This is what *settled*, not what's *listed* — it will differ from
  portals, and that difference is itself a good angle.
- **It lags.** Registration follows the deal — say "last month," never "this week."
- **No yield/rent claims** until the Rents CSV is added and gated.
- **No individual broker named** (the PII rule, §2.6).

---

## 11. The wider free-data map (add to the same architecture later)

DLD is the core; these extend it, all official, all free, each behind its own sanity gate:

| Source | Adds |
|---|---|
| **Mo'asher** (DLD official price index) | Dubai's official monthly price & rent index — ⚠️ the *public* index is fine, but the raw price-index **API** is the poisoned one; use the published figures, not that endpoint |
| **DARI / ADREC** | Abu Dhabi transactions (the AD edition of this whole build) |
| **FCSC / bayanat.ae / Dubai Statistics** | Population, CPI, economy — macro context lines |
| **Central Bank (CBUAE)** | Mortgages, quarterly housing review |

---

## 12. Build checklist

1. [ ] Read the **Open Data Licence PDF** on data.dubai (§4) — the publication gate.
2. [ ] Create the repo; put the CSVs in `/data`.
3. [ ] Paste the sanity gate (§7); write `collect_transactions` (§8).
4. [ ] Run locally; **confirm output matches the known-good numbers (§9).**
5. [ ] Add `rents`, `projects` readers — each with its own shape allow-list + range/volume canary.
6. [ ] Strip PII from anything touching `brokers` (§2.6).
7. [ ] GitHub Action → writes `public/pulse.json` on a monthly cron.
8. [ ] Website reads `pulse.json` → dashboard. Carry the attribution string on the page.
9. [ ] Brief step (§10) for content angles.
10. [ ] Later: swap manual CSV for the DLD API key when it arrives — aggregation & gate unchanged.

---

## 13. What NOT to do (the short list)

- ❌ Don't scrape the DLD site or drive its forms with a bot. Official CSV/API only.
- ❌ Don't ever **write** to any DLD endpoint. Reads only.
- ❌ Don't trust the price-index GraphQL API — it is poisoned. Use published Mo'asher figures instead.
- ❌ Don't publish raw bulk rows — derived analysis only, with attribution.
- ❌ Don't name or phone-number any individual broker.
- ❌ Don't pay for the AED 30k Rental Index API — the free Rents CSV covers monthly commentary.
- ❌ Don't publish a figure without its source and period attached.

---

## 14. One note on a source referenced elsewhere (MEED)

Some of the parallel work uses a **MEED construction-project corpus** for the *supply* pipeline (what's
being built, GCC-wide). That is accessed through **DigitAlchemy's own licensed product and licence — it is
NOT part of this DLD build and its access is not yours to embed.** If you want supply-pipeline data in your
own product, raise it with Kendall / DigitAlchemy separately; do not attempt to reuse any key. **This
handover is DLD-only, and DLD alone is a complete product.**

---

*Prepared 25 Aug 2026. All schemas, row counts and figures verified against live DLD downloads that day.
No credentials or third-party keys are included in this document by design.*
