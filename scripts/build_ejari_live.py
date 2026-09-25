"""Tenancies running on the export date, per project and property type, from Ejari at contract grain (25 Sep 2026).

Why. The building card's sold block comes from the DLD units register - completed SALES - and cannot say whether anything is
let, vacant or available. Ejari (pp_dld__rent_contracts, the portal's full export, 4,183,941 contract lines with start and end
dates) can say how many tenancies were RUNNING on one date. That is not availability and must never be shown as such: an
owner-occupied home has no Ejari contract. The honest ceiling, per project:
    "N tenancies running on <as_at> against M registered units; the rest are owner-occupied, vacant or unregistered,
     and we cannot tell which."

Grain. A contract has several lines (line_number) and a line covers no_of_prop properties, so:
    live_contracts  distinct contract_id live on as_at (start <= as_at <= end)
    live_props      no_of_prop summed over those live lines
New and Renew are both counted - a renewal normally starts where the old contract ends, so on one date a let home should carry
one live contract; overlaps (same project, same type, more live contracts than registered units) are flagged, not hidden.
The contracts carry no unit identity (no property id, unit number, Makani or parcel): the finest place is the PROJECT. A
multi-building project gets ONE figure for all its buildings; the file says how many rows share it, never divides it.

Output  data/dld/ejari_live_<slug>.json, one per modelled district (DLD area -> slug, as dld_rent_buildings.py), and
        data/dld/ejari_live.json (all areas).
    python scripts/build_ejari_live.py [--as-at 2026-09-09]
"""
import collections, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import lake
from keys import num_sql
from dld_rent_buildings import DLD_AREA

ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld")
AS_AT = sys.argv[sys.argv.index("--as-at") + 1] if "--as-at" in sys.argv else "2026-09-09"   # the portal export's date


def main():
    con = lake.connect(read_only=True)
    t0 = time.time()
    con.execute(f"""create temp table live as
        select area_name_en area, coalesce(nullif(trim(project_name_en), ''), '(no project name)') project,
               {num_sql('project_number')} project_number, any_value(master_project_en) over (partition by project_name_en) master,
               ejari_property_type_en ptype, ejari_property_sub_type_en subtype, property_usage_en usage,
               contract_id, contract_reg_type_en reg, try_cast(no_of_prop as double) props
        from pp_dld__rent_contracts
        where try_cast(contract_start_date as date) <= date '{AS_AT}' and try_cast(contract_end_date as date) >= date '{AS_AT}'""")
    n_lines, n_contracts = con.execute("select count(*), count(distinct contract_id) from live").fetchone()
    reg = dict(con.execute(f"select {num_sql('project_number')}, max(registered_units) from lk_d_project "
                           f"where project_number is not null group by 1").fetchall())
    rows = con.execute("""select area, project, max(project_number), any_value(master), ptype, subtype, usage,
                                 count(distinct contract_id), round(sum(props)),
                                 count(distinct case when reg = 'New' then contract_id end), count(distinct case when reg = 'Renew' then contract_id end)
                          from live group by area, project, ptype, subtype, usage""").fetchall()
    P = collections.OrderedDict()
    for area, proj, pn, master, ptype, sub, usage, lc, lp, nw, rn in sorted(rows, key=lambda r: (r[0] or "", r[1], r[4] or "", r[5] or "")):
        k = (area, proj)
        p = P.setdefault(k, {"area": area, "project": proj, "project_number": pn, "master_project": master,
                             "registered_units": reg.get(pn) if pn is not None else None, "live_contracts": 0, "live_props": 0, "by_type": {}})
        if pn is not None and p["project_number"] is None:
            p["project_number"] = pn; p["registered_units"] = reg.get(pn)
        key = " / ".join(x for x in (ptype, sub) if x) or "(unspecified)"
        p["by_type"][key] = {"usage": usage, "live_contracts": lc, "live_props": lp, "new": nw, "renew": rn}
        p["live_contracts"] += lc; p["live_props"] += lp or 0
    for p in P.values():
        ru = p["registered_units"]
        p["flag"] = ("more live contracts than registered units - overlapping contracts or a unit count that is out of date"
                     if ru and p["live_contracts"] > ru else "")
    projects = list(P.values())
    doc_common = {"as_at": AS_AT, "generated": time.strftime("%Y-%m-%d"),
                  "source": "DLD Ejari rent contracts, portal export 2026-09-09 (pp_dld__rent_contracts), every contract line",
                  "grain": "per project and Ejari property type/sub-type; live_contracts = distinct contract_id live on as_at "
                           "(start <= as_at <= end), live_props = no_of_prop summed over those lines; New and Renew both counted",
                  "read_as": "N tenancies running on as_at against M registered units; the rest are owner-occupied, vacant or "
                             "unregistered, and we cannot tell which. NOT availability - an owner-occupied home has no Ejari contract.",
                  "limits": "No unit identity in Ejari (no property id, unit number, Makani or parcel): a multi-building project "
                            "carries ONE figure for all its buildings - never divide it. 'Live on as_at' is not 'live today'."}
    json.dump(dict(doc_common, contract_lines_live=n_lines, contracts_live=n_contracts, projects=projects),
              open(os.path.join(OUT, "ejari_live.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("live on %s: %s contract lines, %s distinct contracts, %d projects (%.0fs)" % (AS_AT, format(n_lines, ","), format(n_contracts, ","), len(projects), time.time() - t0))
    for area, slugs in DLD_AREA.items():
        for slug in slugs:
            sub = [p for p in projects if p["area"] == area]
            json.dump(dict(doc_common, district=slug, area=area, projects=sub),
                      open(os.path.join(OUT, f"ejari_live_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print("  %-26s %-34s projects %4d  live contracts %7s  flagged %d" % (slug, area, len(sub), format(sum(p["live_contracts"] for p in sub), ","),
                  sum(1 for p in sub if p["flag"])))


if __name__ == "__main__":
    main()
