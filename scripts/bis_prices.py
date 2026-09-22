"""bis_prices -- the BIS residential property price series for Dubai, on the lake beside our own registers.

Why (22 Sep 2026). The UBS Global Real Estate Bubble Index puts Dubai at 1.09, "elevated risk", the biggest rise of any city in
the 2025 edition. UBS publishes no API - it is a PDF once a year - but its sources page names what Dubai's price index is built
from: REIDIN. The BIS republishes that same REIDIN series for free through its SDMX API, including a DUBAI-ONLY series monthly
back to 2003 in AED per square metre. So we cannot subscribe to UBS's answer, but we can hold the input it used.

    https://stats.bis.org/api/v2/data/dataflow/BIS/WS_DPP/1.0/M.AE....?format=csv&labels=both

That matters because it is the only long, independent price series we have. Everything else on this lake is the Dubai Land
Department's own record of what was registered; this is an outside compiler's view of asking and transaction prices per square
metre. When the two disagree, the disagreement is the finding - so they are kept apart, never blended.

  lk_bis_prices   one row per economy x covered area x period: the series, its compiler, what it covers and the value
  v_bis_dubai     the Dubai series alone, with a year-on-year change, which is the number a page or a video would quote

What this is NOT: a Dubai Land Department figure, a transaction count, or anything derived from our registers. It is REIDIN's
index as republished by the BIS, and the row carries publications='REIDIN' so nobody mistakes it for ours.
"""
import csv, io, os, urllib.request

BIS_URL = ("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_DPP/1.0/M.AE....?format=csv&labels=both")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "external", "bis", "dpp_ae.csv")
KEEP = ("FREQ", "REF_AREA", "COVERED_AREA", "TITLE_GRP", "UNIT_MEASURE", "MEASURE_DETAIL", "PUBLICATIONS",
        "COVERAGE", "DATA_COMP", "COLLECTION_DETAIL", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "META_UPDATE")


def fetch(force=False):
    """The BIS CSV, cached on disk. Free, no key, but a network call we do not want inside every lake build."""
    path = os.path.abspath(CACHE)
    if force or not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        req = urllib.request.Request(BIS_URL, headers={"User-Agent": "DigitAlchemy-Najma/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as out:
            out.write(r.read())
    return path


def rows():
    """(series label, covered area, period, value) with the BIS's own labels kept verbatim."""
    out = []
    with io.open(fetch(), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("OBS_VALUE") or "").strip():
                continue
            d = {k: (r.get(k) or "").strip() or None for k in KEEP}
            try:
                d["OBS_VALUE"] = float(d["OBS_VALUE"])
            except (TypeError, ValueError):
                continue
            # labels=both puts the readable area at the END of TITLE_GRP ("... all dwellings, Dubai"), not on
            # COVERED_AREA, which stays a bare code (4 = Dubai, 2 = Abu Dhabi, 0 = the five emirates)
            title = d["TITLE_GRP"] or ""
            d["area_label"] = title.rsplit(",", 1)[-1].strip() if "," in title else (d["COVERED_AREA"] or "")
            out.append(d)
    return out


def job_bis_prices(con):
    data = rows()
    if not data:
        raise RuntimeError("the BIS returned no UAE observations - check the WS_DPP dataflow before publishing")
    con.execute("""create or replace temp table j_bis (freq varchar, ref_area varchar, covered_area varchar, area_label varchar,
                   series varchar, unit varchar, measure_detail varchar, publications varchar, coverage varchar,
                   data_comp varchar, collection_detail varchar, period varchar, value double, obs_status varchar,
                   meta_update varchar)""")
    con.executemany("insert into j_bis values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [[d["FREQ"], d["REF_AREA"], d["COVERED_AREA"], d["area_label"], d["TITLE_GRP"], d["UNIT_MEASURE"],
                      d["MEASURE_DETAIL"], d["PUBLICATIONS"], d["COVERAGE"], d["DATA_COMP"], d["COLLECTION_DETAIL"],
                      d["TIME_PERIOD"], d["OBS_VALUE"], d["OBS_STATUS"], d["META_UPDATE"]] for d in data])
    q = lambda s: con.execute(s).fetchall()
    n = q("select count(*) from j_bis")[0][0]
    areas = q("select area_label, count(*), min(period), max(period) from j_bis group by 1 order by 2 desc")
    dubai = q("select count(*), min(period), max(period) from j_bis where area_label ilike '%dubai%'")[0]
    dubai_view = """
        select period, value aed_per_sqm, publications as compiled_by, coverage,
               round(100.0 * (value / lag(value, 12) over (order by period) - 1), 1) yoy_pct
        from lk_bis_prices where area_label ilike '%dubai%' order by period"""
    return {"tables": [("lk_bis_prices", "select * from j_bis")],
            "views": [("v_bis_dubai", dubai_view)],
            "keys_in": n, "keys_matched": dubai[0], "rows_in": n,
            "note": "BIS observations that are the Dubai series",
            "report": ["BIS residential property prices, UAE: %s observations" % format(n, ","),
                       "Dubai series: %s observations, %s to %s" % (format(dubai[0], ","), dubai[1], dubai[2]),
                       "compiled by REIDIN and republished by the BIS - an OUTSIDE view, never to be blended with the "
                       "Land Department's own registers"]
                      + ["   %-30s %5s obs  %s..%s" % (a or "?", format(c, ","), lo, hi) for a, c, lo, hi in areas]}
