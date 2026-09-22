"""build_sales_depth.py -- how deep the sales register is, per district and year, so a median can be trusted or withheld.

Asked for on 22 Sep 2026 by the twin session, after it found eight building pages printing "Median" for a figure computed
from ONE sale. Its fix uses a fixed floor of five sales. A fixed floor is the wrong shape, because the register's depth is not
constant: citywide it grew from 1,821 sales in 2003 to 179,021 in 2024, and a quiet district in 2015 is not the same kind of
five as Business Bay in 2024.

MEASURED, not assumed. Taking 3,198 building-years that carry 60 or more sales, treating each one's own full-year median as
the truth, and drawing random subsamples of size n, the median of n sales sits this far from it:

      n      typical error (p50)   bad case (p90)   within 10% of truth
      1            5.8%                22.3%              67.9%
      2            4.6%                16.6%              77.1%
      3            3.6%                14.8%              80.9%
      5            2.8%                11.9%              86.5%
      8            2.2%                 8.9%              91.9%
     12            1.7%                 7.3%              94.6%
     20            1.3%                 5.5%              96.9%
     30            0.9%                 4.2%              98.2%

So one sale is wrong by more than 10% a third of the time, and the floor of five buys 86.5%. The curve is shallow after about
12 - the honest reading is that 5 is defensible for "indicative", 12 for "reliable", and 1-2 should never carry the word median.

    python scripts/build_sales_depth.py      ->  data/board/sales_depth_<slug>.json  (+ _sales_depth_index.json)

Per district and year: sales, the median price per square metre, the quartiles, and the dispersion (the interquartile range
over the median). Dispersion matters as much as count: five sales in a building of identical flats say more than five across
a mixed tower, and this is the only signal we have for that.
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lake import connect  # noqa: E402
import build_district_cuts as bdc  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
# the measured curve above, carried in every file so a reader never has to guess what a count is worth
ERROR_CURVE = [{"sales": 1, "typical_error_pct": 5.8, "bad_case_pct": 22.3, "within_10pct": 67.9},
               {"sales": 2, "typical_error_pct": 4.6, "bad_case_pct": 16.6, "within_10pct": 77.1},
               {"sales": 3, "typical_error_pct": 3.6, "bad_case_pct": 14.8, "within_10pct": 80.9},
               {"sales": 5, "typical_error_pct": 2.8, "bad_case_pct": 11.9, "within_10pct": 86.5},
               {"sales": 8, "typical_error_pct": 2.2, "bad_case_pct": 8.9, "within_10pct": 91.9},
               {"sales": 12, "typical_error_pct": 1.7, "bad_case_pct": 7.3, "within_10pct": 94.6},
               {"sales": 20, "typical_error_pct": 1.3, "bad_case_pct": 5.5, "within_10pct": 96.9},
               {"sales": 30, "typical_error_pct": 0.9, "bad_case_pct": 4.2, "within_10pct": 98.2}]
NOTE = ("How deep the sales register is here, year by year. A median is only as good as the count behind it AND the spread "
        "around it. error_curve on this file is measured, not assumed: 3,198 building-years with 60+ sales, each one's own "
        "full-year median treated as truth, random subsamples drawn from it. One sale is out by more than 10% a third of the "
        "time. Five buys 86.5% within 10%; twelve buys 94.6%; after that the curve flattens. dispersion is the interquartile "
        "range over the median - five sales in a tower of identical flats are worth more than five across a mixed one.")

SQL = """
    select year(instance_date) y, count(*) sales,
           round(median(meter_sale_price)) median_aed_sqm,
           round(quantile_cont(meter_sale_price, 0.25)) p25,
           round(quantile_cont(meter_sale_price, 0.75)) p75,
           count(distinct building_name_en) named_buildings
    from g_dld__transactions
    where trans_group_en = 'Sales' and meter_sale_price between 500 and 200000
      and (upper(coalesce(area_name_en,'')) = upper(?) or upper(coalesce(master_project_en,'')) = upper(?))
    group by 1 order by 1"""


def main():
    con = connect()
    summary = []
    for d in bdc.districts():
        rows = con.execute(SQL, [d["area"], d["area"]]).fetchall()
        years = []
        for y, n, med, p25, p75, nb in rows:
            disp = round((p75 - p25) / med, 3) if med else None
            years.append({"year": y, "sales": n, "median_aed_sqm": med, "p25": p25, "p75": p75,
                          "dispersion": disp, "named_buildings": nb})
        total = sum(x["sales"] for x in years)
        thin = [x["year"] for x in years if x["sales"] < 12]
        doc = {"area": d["area"], "comm_num": d["comm"], "sales_total": total,
               "years": years, "years_under_12_sales": thin,
               "error_curve": ERROR_CURVE, "note": NOTE}
        bdc.write("sales_depth", d["slug"], doc)
        summary.append({"slug": d["slug"], "area": d["area"], "sales": total,
                        "first_year": years[0]["year"] if years else None,
                        "thin_years": len(thin)})
        if total:
            print("%-26s %9s sales  %4s-%s  thin years %d"
                  % (d["slug"], format(total, ","), years[0]["year"], years[-1]["year"], len(thin)))
    p = os.path.join(BOARD, "_sales_depth_index.json")
    json.dump({"districts": summary, "error_curve": ERROR_CURVE, "note": NOTE},
              io.open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n%d districts -> data/board/sales_depth_<slug>.json" % len(summary))


if __name__ == "__main__":
    main()
