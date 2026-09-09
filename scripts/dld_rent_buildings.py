"""Rents as Ejari records them - per project (which, for a tower, is the building) and per bedroom type - from the six
rent_contracts export files (about 6.3 million contracts, 2021-2026).

Why. The contracts carry no building name, but `project_name_en` is filled for the towers that matter (SULAFA TOWER, PRINCESS
TOWER, TORCH TOWER ...) and `ejari_property_sub_type_en` is the bedroom type. So for every project in our districts we get:
median annual rent by type, median size by type, contracts per type, new vs renewal, over a chosen window. Joined to the sales
side (dld_tx_buildings.py) by project name this yields rent per type, price per type and a gross yield per type, per building.

Output data/dld/rent_projects.json            {"generated","window","projects":[{area, project, master, n, by_type:{type:{n, median_annual, median_sqm, median_aed_sqm, new, renew}}, metro, mall, landmark}]}
       data/dld/rent_projects_<slug>.json     filtered to each modelled district (DLD area names)
Usage: python scripts/dld_rent_buildings.py [--since 2024-01-01] [--files f1.json ...]
"""
import duckdb, glob, json, os, sys, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dld"); os.makedirs(OUT, exist_ok=True)
DLD_AREA = {
    'Marsa Dubai': ['dubaimarina'],
    'Business Bay': ['businessbay'],
    'Burj Khalifa': ['burjkhalifa'],
    'Palm Jumeirah': ['palmjumeirah'],
    'Al Wasl': ['alwasl'],
    'Al Barsha South Fourth': ['jumeirahvillagecircle'],
    'Al Barsha South Fifth': ['jumeirahvillagetriangle'],
    'Al Hebiah First': ['motorcity'],
    'Palm Deira': ['palmdeira'],
    'Al Jadaf': ['samaaljadaf'],
    'Nad Al Shiba First': ['meydanone'],        # DM community polygon: Meydan One twin district = NADD AL SHIBA FIRST (checked 9 Sep 2026)
    'Al Thanyah Fifth': ['jltnorth', 'althanyahfifth'],
    'Al Thanyah Third': ['jltsouth'],
    'Al Barshaa South Third': ['arjan'],
    'Al Hebiah Third': ['damachills'],
    'Hadaeq Sheikh Mohammed Bin Rashid': ['dubaihills'],
    'Saih Shuaib 3': ['dubaiindustrialcity'],
    'Madinat Dubai Almelaheyah': ['dubaimaritimecity'],
    "Me'Aisem First": ['dubaiproductioncity'],
    'Al Barshaa South Second': ['dubaisciencepark'],
    'Al Hebiah Fourth': ['dubaisportscity'],
    'Al Hebiah Second': ['dubaistudiocity'],
    'Wadi Al Safa 3': ['majan'],
    'Al Merkadh': ['sobhaheartland'],           # DM community polygon: Sobha Hartland twin district = AL MERKADH (the two were swapped until 9 Sep 2026)
    'Nadd Hessa': ['siliconoasis'],
    'Al Hebiah Fifth': ['alhebiahfifth'],
    'Al Khairan First': ['alkhairanfirst'],
    'Al Satwa': ['alsatwa'],
    'Al Yelayiss 1': ['alyelayiss1'],
    'Al Yelayiss 2': ['alyelayiss2'],
    'Al Yufrah 1': ['alyufrah1'],
    'Dubai Investment Park First': ['dubaiinvestmentparkfirst'],
    'Dubai Investment Park Second': ['dubaiinvestmentparksecond'],
    'Jabal Ali First': ['jabalalifirst'],
    'Jabal Ali Industrial Second': ['jabalaliindustrialsecond'],
    'Madinat Al Mataar': ['madinatalmataar'],
    'Madinat Hind 4': ['madinathind4'],
    'Wadi Al Safa 4': ['wadialsafa4'],
    'Wadi Al Safa 5': ['wadialsafa5'],
}
DLD_SLUGS = sorted({x for v in DLD_AREA.values() for x in v})
TYPE = {"Studio": "Studio", "1bed room+Hall": "1 B/R", "2 bed rooms+hall": "2 B/R", "3 bed rooms+hall": "3 B/R", "4 bed rooms+hall": "4 B/R", "5 bed rooms+hall": "5 B/R", "Penthouse": "PENTHOUSE", "Office": "Office", "Shop": "Shop"}


def main():
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "2024-01-01"
    files = sys.argv[sys.argv.index("--files") + 1:] if "--files" in sys.argv else sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\rent_contracts_*.json"))
    files = [f for f in files if "(1)" not in f]
    print("files:", len(files), "| since", since)
    con = duckdb.connect(); t = time.time()
    src = " UNION ALL ".join(f"select area_name_en, project_name_en, master_project_en, ejari_property_sub_type_en, ejari_property_type_en, property_usage_en, contract_reg_type_en, annual_amount, actual_area, contract_start_date, nearest_metro_en, nearest_mall_en, nearest_landmark_en from read_json_auto('{f.replace(chr(92), '/')}', maximum_object_size=200000000, sample_size=20000)" for f in files)
    con.execute(f"create table rc as select * from ({src}) where project_name_en is not null and project_name_en <> '' and cast(contract_start_date as varchar) >= '{since}' and ejari_property_type_en in ('Flat','Office','Shop','Villa','Penthouse')")
    n = con.execute("select count(*) from rc").fetchone()[0]; print(f"contracts with a project, since {since}: {n:,} ({time.time()-t:.0f}s)")
    hdr = con.execute("""select area_name_en, project_name_en, any_value(master_project_en), count(*), any_value(nearest_metro_en), any_value(nearest_mall_en), any_value(nearest_landmark_en)
                         from rc group by 1,2 having count(*) >= 5 order by 1,2""").fetchall()
    bt = con.execute("""select area_name_en, project_name_en, ejari_property_sub_type_en, count(*), round(median(annual_amount)), round(median(actual_area),1),
                        round(median(case when actual_area > 5 then annual_amount/actual_area end)), sum(case when contract_reg_type_en='New' then 1 else 0 end), sum(case when contract_reg_type_en='Renew' then 1 else 0 end)
                        from rc group by 1,2,3""").fetchall()
    B = collections.defaultdict(dict)
    for a, p, ty, c, med, sqm, aedsqm, nw, rn in bt: B[(a, p)][TYPE.get(ty, ty)] = {"n": c, "median_annual": med, "median_sqm": sqm, "median_aed_sqm": aedsqm, "new": nw, "renew": rn}
    out = [{"area": a, "project": p, "master": m, "n": c, "by_type": B.get((a, p), {}), "metro": me, "mall": ma, "landmark": lm} for a, p, m, c, me, ma, lm in hdr]
    json.dump({"generated": time.strftime("%Y-%m-%d"), "window": f"contracts starting {since} onward", "source": "DLD Ejari rent contracts export 2026-09-04", "rows": n, "projects": out}, open(os.path.join(OUT, "rent_projects.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"projects with >=5 contracts: {len(out):,}")
    for area, slugs in DLD_AREA.items():
      for slug in slugs:
        sub = [x for x in out if x["area"] == area]
        json.dump({"district": slug, "area": area, "window": since, "projects": sub}, open(os.path.join(OUT, f"rent_projects_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {slug:<24} {area:<26} projects {len(sub):>4}  contracts {sum(x['n'] for x in sub):>7,}")


if __name__ == "__main__":
    main()
