"""The Valley (Emaar) evidence pull — DLD transactions/rents/projects + MEED pipeline.

Written 02 Sep 2026 for the Emaar District Ambassador open call (1-15 Sep 2026).
DLD area mapping: The Valley registers as AREA_EN='Al Yufrah 1' (legacy rows: 'THE VALLEY').
Corroborated independently by MEED plot titles ("... Al Yufrah 1 (Plot No. 9150110.5)").

Run:  python -X utf8 scripts/valley_pull.py
"""
import json, pathlib, duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
SQM_TO_SQFT = 10.7639
VALLEY = "(lower(coalesce(PROJECT_EN,'')) like 'the valley%' or AREA_EN='THE VALLEY')"

con = duckdb.connect(str(ROOT / "naj.duckdb"), read_only=True)
out = {"generated": "2026-09-02", "source": "DLD open data + MEED UAE cache (Digital Abbot Cloud snapshot)"}

out["dld_area_mapping"] = con.execute(f"""
    select AREA_EN, count(*) n from transactions where {VALLEY} group by 1 order by n desc
""").fetchdf().to_dict("records")

out["headline"] = con.execute(f"""
    with v as (select try_cast(TRANS_VALUE as double) tv, try_cast(ACTUAL_AREA as double) aa,
                      try_cast(INSTANCE_DATE as date) d
               from transactions where {VALLEY})
    select min(d)::varchar first_tx, max(d)::varchar last_tx, count(*) transactions,
           round(sum(tv)/1e9, 3) total_aed_bn, round(median(tv)) median_price_aed,
           round(median(tv/nullif(aa,0))/{SQM_TO_SQFT}) median_aed_psf
    from v
""").fetchdf().to_dict("records")[0]

out["monthly_sales"] = {
    "valley": con.execute(f"""
        with v as (select try_cast(INSTANCE_DATE as date) d, try_cast(TRANS_VALUE as double) tv,
                          try_cast(ACTUAL_AREA as double) aa
                   from transactions where {VALLEY} and GROUP_EN='Sales')
        select strftime(d,'%Y-%m') "month", count(*) n, round(median(tv)) median_price_aed,
               round(median(tv/nullif(aa,0))/{SQM_TO_SQFT}) median_aed_psf
        from v group by 1 order by 1
    """).fetchdf().to_dict("records"),
    "dubai_all": con.execute(f"""
        with c as (select try_cast(INSTANCE_DATE as date) d, try_cast(TRANS_VALUE as double) tv,
                          try_cast(ACTUAL_AREA as double) aa
                   from transactions where GROUP_EN='Sales')
        select strftime(d,'%Y-%m') "month", count(*) n, round(median(tv)) median_price_aed,
               round(median(tv/nullif(aa,0))/{SQM_TO_SQFT}) median_aed_psf
        from c group by 1 order by 1
    """).fetchdf().to_dict("records"),
}

out["villa_mix"] = con.execute(f"""
    with v as (select ROOMS_EN, try_cast(TRANS_VALUE as double) tv, try_cast(ACTUAL_AREA as double) aa
               from transactions where {VALLEY} and GROUP_EN='Sales' and PROP_SB_TYPE_EN='Villa')
    select ROOMS_EN rooms, count(*) n, round(median(tv)) median_sale_aed,
           round(median(aa)) median_sqm, round(median(aa)*{SQM_TO_SQFT}) median_sqft
    from v group by 1 order by n desc
""").fetchdf().to_dict("records")

out["rents_al_yufrah_1"] = con.execute("""
    select PROP_TYPE_EN prop_type, ROOMS rooms, count(*) contracts,
           round(median(try_cast(ANNUAL_AMOUNT as double))) median_annual_aed
    from rents where AREA_EN='Al Yufrah 1' group by 1,2 order by contracts desc
""").fetchdf().to_dict("records")

out["dld_project_register"] = con.execute("""
    select PROJECT_EN project, PROJECT_STATUS status, PERCENT_COMPLETED pct_complete,
           CNT_VILLA villas, START_DATE::varchar start_date, END_DATE::varchar end_date
    from projects where lower(coalesce(PROJECT_EN,'')) like 'the valley%' order by PROJECT_EN
""").fetchdf().to_dict("records")

meed = json.loads((ROOT / "data/meed/uae_projects.json").read_text(encoding="utf-8"))["items"]
valley = [r for r in meed if "the valley" in r["title"].lower() and "emaar" in r["title"].lower()]
out["meed_pipeline"] = {
    "records": len(valley),
    "total_net_value_usd_m": sum(r["netValueUsdM"] or 0 for r in valley),
    "by_stage": {s: sum(1 for r in valley if r["stageLabel"] == s)
                 for s in sorted({r["stageLabel"] for r in valley})},
    "projects": sorted(valley, key=lambda r: -(r["netValueUsdM"] or 0)),
}

dest = ROOT / "data/valley_evidence.json"
dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {dest}")
print(json.dumps(out["headline"], indent=2))
print("MEED:", out["meed_pipeline"]["records"], "records,",
      out["meed_pipeline"]["total_net_value_usd_m"], "USD m", out["meed_pipeline"]["by_stage"])
