"""Valley angle pack for the daily kicker (Emaar District Ambassador, open call 1-15 Sep 2026).
While the contest window is open the morning feed carries TWO extra Valley angles beside the five market ones. This builds the
grounding pack they are written from: the register evidence (data/valley_evidence.json, refreshed here from naj.duckdb so the
figures are never stale), the Alva EOI launch as offered, the build-out pipeline, the assets she can actually cut from, the contest
mechanics, and the hard guardrails (what may NOT be claimed). Pushed to KV `valley_pack` -> the Worker reads it in dailyFeedTick.
Usage: python scripts/build_valley_pack.py
"""
import datetime as dt, json, os, statistics, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
from build_avail_index import env_token, push  # noqa: E402

con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
AREAS = "('al yufrah 1','the valley')"
CONTEST_CLOSES = "2026-09-15"

def q(sql):
    return con.execute(sql).fetchall()

# --- register: the community as it actually trades (sales only, 2026)
sales = q("select try_cast(TRANS_VALUE as double) v, try_cast(TRANS_VALUE as double)/nullif(try_cast(PROCEDURE_AREA as double),0)*0.092903 psf, "
          "ROOMS_EN, INSTANCE_DATE, PROP_TYPE_EN from transactions where lower(trim(AREA_EN)) in %s and GROUP_EN='Sales' and try_cast(TRANS_VALUE as double) > 100000" % AREAS)
vals = sorted(r[0] for r in sales if r[0]); psf = [r[1] for r in sales if r[1] and 100 < r[1] < 20000]
rooms = {}
for r in sales:
    if r[2]: rooms[r[2]] = rooms.get(r[2], 0) + 1
city = q("select median(try_cast(TRANS_VALUE as double)), median(try_cast(TRANS_VALUE as double)/nullif(try_cast(PROCEDURE_AREA as double),0)*0.092903) from transactions where GROUP_EN='Sales' and try_cast(TRANS_VALUE as double) > 100000")
rents = q("select ROOMS, count(*), median(try_cast(ANNUAL_AMOUNT as double)) from rents where lower(trim(AREA_EN)) in %s group by 1 order by 2 desc" % AREAS)
reg = q("select PROJECT_EN, CNT_UNIT, PERCENT_COMPLETED, COMPLETION_DATE, PROJECT_STATUS from projects where lower(DEVELOPER_EN) like '%%emaar%%' and lower(PROJECT_EN) like '%%%%' and lower(AREA_EN) in %s" % AREAS)


# --- the cuts that make an angle nobody else can write
months = q("select substr(INSTANCE_DATE,1,7) m, count(*), median(try_cast(TRANS_VALUE as double)) from transactions where lower(trim(AREA_EN)) in %s and GROUP_EN='Sales' group by 1 order by 1" % AREAS)
proc = q("select GROUP_EN, count(*) from transactions where lower(trim(AREA_EN)) in %s group by 1 order by 2 desc" % AREAS)
offp = q("select IS_OFFPLAN_EN, count(*) from transactions where lower(trim(AREA_EN)) in %s and GROUP_EN='Sales' group by 1" % AREAS)
big = q("select max(try_cast(TRANS_VALUE as double)), min(try_cast(TRANS_VALUE as double)) from transactions where lower(trim(AREA_EN)) in %s and GROUP_EN='Sales' and try_cast(TRANS_VALUE as double)>100000" % AREAS)
plot = q("select ROOMS_EN, median(try_cast(PROCEDURE_AREA as double)), count(*) from transactions where lower(trim(AREA_EN)) in %s and GROUP_EN='Sales' and ROOMS_EN is not null group by 1 order by 3 desc" % AREAS)
metro = q("select NEAREST_METRO_EN, NEAREST_MALL_EN, NEAREST_LANDMARK_EN, count(*) from transactions where lower(trim(AREA_EN)) in %s group by 1,2,3 order by 4 desc limit 1" % AREAS)
city_month = q("select substr(INSTANCE_DATE,1,7) m, count(*) from transactions where GROUP_EN='Sales' group by 1 order by 1")

pack = {
    "updated": dt.date.today().isoformat(),
    "contest": {"name": "Emaar District Ambassador Program - The Valley", "window": "1-15 Sep 2026", "closes": CONTEST_CLOSES,
                "ask": "60-90 second video: why The Valley is a place to live and invest",
                "segments": ["0-20s why The Valley (masterplan, location, connectivity)", "20-45s lifestyle and community (Community Centre, Golden Beach, Kids Dale, Sports Village, Parks)",
                             "45-70s investment opportunity (growth, future developments, benefits)", "70-90s closing, why live + invest, call to action"],
                "mechanics": "publish on Instagram / TikTok / LinkedIn / Facebook / YouTube inside the window; hashtag #ThisIsTheValley; tag @EmaarInsider; follow @EmaarInsider",
                "judging": ["engagement (views, likes, shares)", "content quality and creativity", "accuracy of messaging", "compliance with Emaar branding guidelines"],
                "prizes": "marketing budget AED 30k / 25k / 20k / 15k / 10k / 5k plus priority access to the next launch"},
    "area_mapping": "The Valley registers with the land department as AREA_EN 'Al Yufrah 1' (a legacy tail sits under 'THE VALLEY')",
    "register_2026": {"sales": len(sales), "median_price_aed": round(statistics.median(vals)) if vals else None,
                      "median_aed_psf": round(statistics.median(psf)) if psf else None, "rooms": dict(sorted(rooms.items(), key=lambda x: -x[1])[:6]),
                      "city_median_price_aed": round(city[0][0]) if city and city[0][0] else None, "city_median_aed_psf": round(city[0][1]) if city and city[0][1] else None},
    "rents": [{"rooms": r[0], "contracts": r[1], "median_annual_aed": round(r[2]) if r[2] else None} for r in rents if r[1] >= 5][:5],
    "pipeline_dld": [{"project": r[0], "units": int(r[1] or 0), "pct_complete": float(r[2] or 0), "completion": str(r[3])[:10] if r[3] else None, "status": r[4]} for r in reg],
    "launch_alva": {"note": "live EOI launch, material received 3 Sep 2026", "sales_rooms": "3 BR and 4 BR only, auto-allocation optional",
                    "from_aed": {"3BR": 4380000, "4BR": 5090000}, "avg_total_sqft": {"3BR": 2788, "4BR": 3081},
                    "implied_aed_psf": {"3BR": 1571, "4BR": 1652}, "eoi_deposit_aed": {"3BR": 100000, "4BR": 150000},
                    "registered": "Alva 196 villas, completion 31 Mar 2030, 0% complete (DLD project register)"},
    "assets_on_hand": ["Emaar lifestyle film 45 s, 1024x576 landscape", "Emaar branded film 13 s, 576x1024 vertical",
                       "build-out and rate cards rendered from the register", "background plates for AI-assisted cutaways"],
    "edges": {
        "note": "Facts a competitor working from the brochure cannot state. Every one is checkable in an official register.",
        "items": [
            {"edge": "The Valley does not exist by that name in the land department register - it books under the area name Al Yufrah 1",
             "why_it_lands": "she can say 'I looked it up where the deals are actually recorded, and here is what the sales say', which no brochure-led entrant can"},
            {"edge": "monthly sales count and median, month by month, for this community alone", "data": "register_2026.monthly"},
            {"edge": "how buyers are paying: sales vs mortgages vs gifts (family transfers)", "data": "register_2026.procedures"},
            {"edge": "off-plan versus ready split inside the community", "data": "register_2026.offplan"},
            {"edge": "actual signed rents from the tenancy register, so the yield is arithmetic rather than a promise", "data": "rents"},
            {"edge": "the build-out that is still coming: registered projects, unit counts, per cent complete and completion dates to 2030", "data": "pipeline_dld"},
            {"edge": "typical plot and built area by bedroom count, from the register rather than the floor plan", "data": "register_2026.typical_area_sqft"},
            {"edge": "the cheapest and the dearest villa the register recorded here this year", "data": "register_2026.range"},
            {"edge": "the community's share of the whole city's sales, month by month", "data": "register_2026.city_share"},
            {"edge": "the launch as offered today, against the community's own transacted history", "data": "launch_alva"}]},
    "creative_modes": [
        "'I checked the register' - open on the official figure, not on a drone shot; the reveal is the source, not the view",
        "what AED X actually buys here versus the same money elsewhere in Dubai, on the same measure",
        "a walk at the pace a resident walks it: school run, park, community centre, home, timed",
        "the room your child grows up in - the room as the argument, not the building",
        "myth-buster: the thing buyers assume about a villa community that the register disproves",
        "count-up: how many homes are still to be built here, and when each one lands",
        "the quiet number - one figure nobody quotes, held on screen while she explains it",
        "then and now: the masterplan render beside the phase that is already handed over",
        "a question posed in the first three seconds and answered at second fifty",
        "one family's arithmetic: rent here versus own here, both numbers from the registers"],
    "creative_rules": [
        "An angle must be one a competitor with only the brochure could NOT write. If a marketing page could say it, do not send it.",
        "Lead with a person or a question, never with an adjective. No 'stunning', 'vibrant', 'oasis', 'nestled'.",
        "One number per angle, said once, in full. The figure is the payoff, not the decoration.",
        "The shot line must be filmable this week with what is on hand: her phone, or a cut from the two supplied films.",
        "Never repeat a hook used in the last twelve days."],
    "figure_basis": {"rule": "SALES ONLY (GROUP_EN='Sales'): mortgages and gifts are not market prices. Valley and the city are always compared on the same basis.",
                     "valley_sales_psf": None, "city_sales_psf": None,
                     "do_not_reuse": ["1,175 AED/sq ft - that is ALL procedures including mortgages and gifts", "1,388 AED/sq ft - an earlier working figure on a different basis"],
                     "note": "Three different Valley rates exist in older working notes. Only the sales-only pair in this pack may be quoted, and only against the city on the same basis."},
    "guardrails": [
        "NEVER claim capital appreciation or rising prices: the median rate is flat over Jan-Aug 2026 (1,262 -> 1,229 AED/sq ft). Accuracy is a judged criterion.",
        "The defensible investment line is VALUE, not momentum: villa square footage below the city median rate per square foot, on a gross yield near 4.6-4.7 %, inside a masterplan still building out.",
        "Yields quoted are GROSS, before service charge, agency and voids. Say so.",
        "Alva prices are 'from' prices as offered; the transacted history is a different figure - never mix the two in one sentence.",
        "Every post carries #ThisIsTheValley and tags @EmaarInsider.",
        "The UAE advertiser permit question is unresolved: flag it, do not assume clearance.",
        "Quote only the sales-only rates in this pack (see figure_basis). Older notes carry 1,175 and 1,388 AED/sq ft on other bases - do not mix them.",
        "Do not use Six Senses or any competing developer's assets in Valley content."],
}
pack["register_2026"]["monthly"] = [{"month": m, "sales": n, "median_aed": round(v) if v else None} for m, n, v in months]
pack["register_2026"]["procedures"] = {r[0]: r[1] for r in proc}
pack["register_2026"]["offplan"] = {(r[0] or "unknown"): r[1] for r in offp}
pack["register_2026"]["range"] = {"lowest_sale_aed": round(big[0][1]) if big and big[0][1] else None, "highest_sale_aed": round(big[0][0]) if big and big[0][0] else None}
pack["register_2026"]["typical_area_sqft"] = {r[0]: round((r[1] or 0) * 10.7639) for r in plot if r[2] >= 5}
pack["register_2026"]["vicinity"] = {"metro": metro[0][0], "mall": metro[0][1], "landmark": metro[0][2]} if metro else {}
_cm = {m: n for m, n in city_month}
pack["register_2026"]["city_share"] = [{"month": x["month"], "valley": x["sales"], "city": _cm.get(x["month"]), "share_pct": round(1000 * x["sales"] / _cm[x["month"]]) / 10 if _cm.get(x["month"]) else None} for x in pack["register_2026"]["monthly"]]
pack["figure_basis"]["valley_sales_psf"] = pack["register_2026"]["median_aed_psf"]
pack["figure_basis"]["city_sales_psf"] = pack["register_2026"]["city_median_aed_psf"]
if pack["register_2026"]["median_aed_psf"] and pack["register_2026"]["city_median_aed_psf"]:
    a, b = pack["register_2026"]["median_aed_psf"], pack["register_2026"]["city_median_aed_psf"]
    pack["value_gap_pct"] = round(100 * (b - a) / b)
out = os.path.join(ROOT, "data", "board", "valley_pack.json"); json.dump(pack, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Valley pack:", pack["register_2026"]["sales"], "sales | median AED", pack["register_2026"]["median_price_aed"], "|", pack["register_2026"]["median_aed_psf"], "AED/sq ft vs city", pack["register_2026"]["city_median_aed_psf"], "| gap", pack.get("value_gap_pct"), "%")
print("rents:", pack["rents"]); print("pipeline:", len(pack["pipeline_dld"]), "registered projects")
r = push("valley_pack", pack, env_token("INGEST_TOKEN")); print("valley_pack ->", r.get("ok"))
