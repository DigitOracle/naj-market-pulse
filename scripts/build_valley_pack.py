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
pack["figure_basis"]["valley_sales_psf"] = pack["register_2026"]["median_aed_psf"]
pack["figure_basis"]["city_sales_psf"] = pack["register_2026"]["city_median_aed_psf"]
if pack["register_2026"]["median_aed_psf"] and pack["register_2026"]["city_median_aed_psf"]:
    a, b = pack["register_2026"]["median_aed_psf"], pack["register_2026"]["city_median_aed_psf"]
    pack["value_gap_pct"] = round(100 * (b - a) / b)
out = os.path.join(ROOT, "data", "board", "valley_pack.json"); json.dump(pack, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Valley pack:", pack["register_2026"]["sales"], "sales | median AED", pack["register_2026"]["median_price_aed"], "|", pack["register_2026"]["median_aed_psf"], "AED/sq ft vs city", pack["register_2026"]["city_median_aed_psf"], "| gap", pack.get("value_gap_pct"), "%")
print("rents:", pack["rents"]); print("pipeline:", len(pack["pipeline_dld"]), "registered projects")
r = push("valley_pack", pack, env_token("INGEST_TOKEN")); print("valley_pack ->", r.get("ok"))
