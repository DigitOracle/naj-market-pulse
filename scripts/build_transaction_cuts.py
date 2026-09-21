"""transactions_<slug>.json for every district: what has actually sold in each building, by name.

"What has sold here" was showing on two districts out of forty, because the transaction cut had only ever been made by hand for
Business Bay and DAMAC Hills. It is the section a buyer asks for first, so it should not wait for a per-district cut.

The whole register is already in the published lake as g_dld__transactions (1.78 M rows, read-only here - it is the DDA
session's table and nothing in this script writes to it). It carries area_name_en and building_name_en, which is all the join
needs: the transaction register holds NO property id and no parcel, so a sale can only ever be bound to a building by NAME, and
build_scheme_links.py applies the strict name rule on top of what this writes.

  python scripts/build_transaction_cuts.py                 every district on the rail
  python scripts/build_transaction_cuts.py dubaimarina     just these
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SQM = 10.7639
SALE = ("Sales",)                      # the register's own group for a sale; mortgages and gifts are not sales
COLUMNS = ["date", "group", "reg_type", "property_type", "property_sub_type", "rooms", "area_sqm", "price",
           "price_per_sqm", "parking"]


def main():
    from lake import connect
    from dld_rent_buildings import DLD_AREA
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    areas = {a: s for a, s in DLD_AREA.items() if not want or any(x in want for x in s)}
    if not areas:
        print("no district matched %s" % want)
        return 1
    c = connect()
    t0, n = time.time(), 0
    for area, slugs in sorted(areas.items()):
        rows = c.execute("""
            select building_name_en, instance_date, trans_group_en, reg_type_en, property_type_en, property_sub_type_en,
                   rooms_en, procedure_area, actual_worth, meter_sale_price, has_parking
              from g_dld__transactions
             where area_name_en = ? and trans_group_en in ('Sales') and building_name_en is not null
               and trim(building_name_en) <> '' order by instance_date""", [area]).fetchall()
        by = {}
        for (bn, d, grp, reg, pt, pst, rooms, parea, worth, psm, park) in rows:
            by.setdefault(str(bn).strip(), []).append({
                "date": str(d)[:10], "group": grp, "reg_type": reg, "property_type": pt, "property_sub_type": pst,
                "rooms": rooms, "area_sqm": round(parea, 2) if parea else None,
                "price": round(worth) if worth else None,
                "price_per_sqm": round(psm, 2) if psm else None, "parking": int(park or 0)})
        doc = {"area": area, "sales": len(rows), "buildings_named": len(by), "columns": COLUMNS, "by_building_name": by,
               "note": ("Every registered sale in this area, grouped by the building name the Land Department wrote on it. The "
                        "transaction register carries no property id and no parcel, so a sale can only be bound to a building "
                        "by name; the strict name rule is applied where these are read, not here. Source: the published lake's "
                        "g_dld__transactions, %s." % time.strftime("%d %b %Y"))}
        for s in slugs:
            p = os.path.join(BOARD, "transactions_%s.json" % s)
            tmp = p + ".tmp"
            json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, p)           # in place, so a reader never sees half a file
            n += 1
        print("  %-28s %7d sales  %5d buildings -> %s" % (area, len(rows), len(by), ", ".join(slugs)))
    print("transaction cuts written: %d files for %d areas in %.0fs" % (n, len(areas), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
