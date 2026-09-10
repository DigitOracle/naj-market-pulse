"""Malls from the authority, not the crowd (Kendall, 7 Sep: "there can't be more than fifteen to twenty major malls").

Definition: a Dubai Municipality building whose registered usage begins 'Shopping Centre', completed, with >= 50,000 m2 of built
area - one entry per parcel (a mall is several DM buildings). Tiers by built area: major >= 200k, large 100-200k, community 50-100k.
DM carries no coordinates or trade names, so each parcel is resolved once through Google Places with a candidate name and the
match is accepted ONLY if the returned address names the same community as the DM record; otherwise the entry keeps its DM facts
and no pin. DLD land-registry project names are used first where the parcel is a registered project (The Dubai Mall, Dubai Marina Mall).

Known gap, stated: Palm Jumeirah, Jebel Ali / Ibn Battuta, International City / Dragon Mart and other Nakheel lands are permitted
by Trakhees, not DM, so they are absent from the DM register. They are added as a short supplement flagged src 'trakhees-gap'.

Output data/registers/dm_malls.json  {"items": [{parcel_id, community, built_m2, buildings, completed, tier, name, lon, lat, src, note}]}
Usage: python scripts/dm_malls.py [--no-google]     GOOGLE_KEY in the environment for lookups; results cached in refine_cache.json
"""
import json, os, re, sys, time
import duckdb
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from geocoders import geocode_google, places_contact  # noqa: E402
REG = os.path.join(ROOT, "data", "registers"); CACHE = os.path.join(REG, "refine_cache.json")
DM = os.path.join(ROOT, "data", "dld", "dm_building_summary_2026-08-31.csv")
LAND = r"C:\Dev\naj-market-pulse\data\raw_downloads\land_registry_2026-09-04_17-30-03_0001.csv"

# candidate trade names per DM parcel, to be VERIFIED by community match - never trusted on their own
CANDIDATE = {
    3450897: "The Dubai Mall", 6316259: "Dubai Hills Mall", 1241085: "Al Ghurair Centre", 3730917: "Mall of the Emirates",
    2514843: "City Centre Mirdif", 4124755: "Dubai Festival City Mall", 3456903: "Dubai Mall Fashion Avenue", 3920479: "Dubai Marina Mall",
    3170983: "BurJuman Centre", 3450826: "Souk Al Bahar", 3364802: "The Boulevard at Emirates Towers", 3370695: "Dubai Mall Zabeel",
    1290171: "City Centre Deira", 3156325: "Wafi Mall", 3150274: "Wafi City", 3540378: "Oasis Centre", 1241195: "Al Ghurair Centre",
    1215568: "Deira Corniche mall", 3920400: "Marina Walk", 2623104: "Arabian Center", 3520969: "Sunset Mall", 6466916: "Cityland Mall",
    2320154: "Madina Mall", 2450743: "Etihad Mall", 1234413: "Al Muteena mall", 1240959: "Al Ghurair Centre", 3762460: "Al Barsha Mall",
    2420193: "Al Qusais mall", 1290227: "Reef Mall", 3220301: "Al Hudaiba mall", 6143109: "Nad Al Hamar Mall", 3430344: "City Walk",
    3927003: "Marina mall", 4237986: "Al Warqa mall", 2310195: "Al Bustan Centre", 3160283: "Al Raffa mall", 2140875: "Garhoud mall",
    3321174: "Mercato Shopping Mall", 3920513: "Marina Gate mall", 3946998: "The Springs Souk", 3920211: "Marina mall", 3640275: "Times Square Center",
    3115810: "Al Shindagha market",
}
TRAKHEES_GAP = [("Ibn Battuta Mall", "Jebel Ali"), ("Nakheel Mall", "Palm Jumeirah"), ("Dragon Mart", "International City"),
                ("The Pointe", "Palm Jumeirah"), ("Golden Mile Galleria", "Palm Jumeirah"), ("Dubai Outlet Mall", "Al Ain Road")]
NORM = lambda t: re.sub(r"[^a-z]+", " ", (t or "").lower()).split()
COMM_ALIAS = {"burj khalifa": ["downtown", "burj khalifa", "financial"], "hadaeq sheikh mohammed bin rashid": ["dubai hills", "hadaeq"],
              "al muraqqabat": ["muraqqabat", "murqabat", "deira", "rigga"], "al barsha first": ["barsha"], "mirdif": ["mirdif"],
              "al kheeran": ["festival", "kheeran", "khairan"], "marsa dubai": ["marina", "marsa"], "mankhool": ["mankhool", "bur dubai", "khalid bin al waleed"],
              "trade center second": ["trade centre", "trade center", "difc", "sheikh zayed"], "zaa`beel second": ["zabeel", "zaabeel"],
              "port saeed": ["port saeed", "deira", "city centre"], "umm hurair second": ["umm hurair", "oud metha", "wafi", "healthcare"],
              "al quoz first": ["quoz", "goze"], "corniche deira": ["corniche", "deira"], "al mizhar first": ["mizhar"], "jumeira third": ["jumeirah 3", "jumeira 3", "jumeirah"],
              "wadi al safa 4": ["wadi al safa", "dubailand", "city of arabia"], "al qusais first": ["qusais"], "muhaisanah fourth": ["muhaisnah", "muhaisanah"],
              "al muteena": ["muteena"], "al barsha second": ["barsha"], "al qusais ind. first": ["qusais"], "al hudaiba": ["hudaiba", "jumeirah"],
              "ras al khor ind. third": ["ras al khor", "nad al hamar"], "al wasl": ["wasl", "city walk", "jumeirah"], "al warqa`a third": ["warqa"],
              "al nahda first": ["nahda"], "al garhoud": ["garhoud"], "jumeira first": ["jumeirah 1", "jumeira 1", "jumeirah"], "al thanyah  fourth": ["springs", "emirates living", "thanyah"],
              "al qouz ind.first": ["quoz", "goze"], "al shindagha": ["shindagha"]}


def tier(a): return "major" if a >= 200000 else ("large" if a >= 100000 else "community")


def community_ok(dm_comm, address, fallback_area):
    a = (address or "").lower()
    keys = COMM_ALIAS.get((dm_comm or "").lower().strip(), []) + NORM(dm_comm) + NORM(fallback_area)
    keys = [k for k in keys if len(k) >= 4 and k not in ("first", "second", "third", "fourth", "dubai", "united", "arab", "emirates")]
    return any(k in a for k in keys)


def main():
    use_google = "--no-google" not in sys.argv; gkey = os.environ.get("GOOGLE_KEY") if use_google else None
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    con = duckdb.connect()
    rows = con.execute(f"""
      with dm as (select cast(try_cast(parcel_id as double) as bigint) pid, any_value(community_name_english) comm,
                         max(try_cast(building_total_area as double)) area, count(*) nb, min(building_completion_date) done
                  from read_csv_auto('{DM}', all_varchar=true)
                  where building_usages_english ilike 'shopping centre%' and building_completion_date is not null and building_completion_date<>''
                  group by 1 having max(try_cast(building_total_area as double)) >= 50000),
           lr as (select cast(try_cast(parcel_id as double) as bigint) pid, any_value(project_name_en) proj, any_value(master_project_en) master, any_value(area_name_en) area_en
                  from read_csv_auto('{LAND}', all_varchar=true) group by 1)
      select dm.pid, dm.comm, dm.area, dm.nb, dm.done, lr.proj, lr.master, lr.area_en from dm left join lr on lr.pid = dm.pid order by dm.area desc""").fetchall()
    items = []; paid = 0
    for pid, comm, area, nb, done, proj, master, area_en in rows:
        cand = CANDIDATE.get(pid) or (proj if proj and re.search(r"mall|centre|center|souk|walk", proj, re.I) else None)
        it = {"parcel_id": pid, "community": (comm or area_en or "").title().strip(), "built_m2": round(area), "buildings": nb, "completed": (done or "")[:10],
              "tier": tier(area), "dld_project": proj, "master": master, "name": None, "lon": None, "lat": None, "src": "dm"}
        if cand:
            ck = "mall:" + str(pid) + ":" + cand
            if ck not in cache and gkey:
                try: cache[ck] = geocode_google(gkey, cand, (comm or area_en or "") + " Dubai"); paid += 1
                except Exception: cache[ck] = None
            g = cache.get(ck)
            if g and community_ok(comm, g.get("address"), area_en) and re.search(r"shopping|mall|market", (g.get("type") or "") + " " + (g.get("name") or ""), re.I):
                it.update({"name": (g.get("name") or cand)[:60], "lon": round(g["lon"], 6), "lat": round(g["lat"], 6), "src": "dm+google", "note": "position and trade name from a Places match in the same community"})
            else:
                it["note"] = f"candidate '{cand}' not confirmed in {comm}" + (f" (Places said: {g.get('address')})" if g else "")
        items.append(it)
    # one pin per mall: when several DM parcels resolve to the same place (an extension, a car park), keep the largest
    kept = []
    for it in sorted(items, key=lambda x: -(x.get("built_m2") or 0)):
        if it.get("lon") and any(k.get("lon") and k["name"] == it["name"] and (abs(k["lon"] - it["lon"]) < 0.02 and abs(k["lat"] - it["lat"]) < 0.02) for k in kept):   # same trade name within ~2 km = the same mall
            it.update({"name": None, "lon": None, "lat": None, "src": "dm", "note": "same place as a larger parcel already pinned"})
        kept.append(it)
    for nm, area_hint in TRAKHEES_GAP:
        ck = "mall:gap:" + nm
        if ck not in cache and gkey:
            try: cache[ck] = geocode_google(gkey, nm, area_hint + " Dubai"); paid += 1
            except Exception: cache[ck] = None
        g = cache.get(ck)
        if g: items.append({"parcel_id": None, "community": area_hint, "built_m2": None, "buildings": None, "completed": None, "tier": "major" if nm in ("Ibn Battuta Mall", "Nakheel Mall", "Dragon Mart", "Dubai Outlet Mall") else "community",
                            "name": nm, "lon": round(g["lon"], 6), "lat": round(g["lat"], 6), "src": "trakhees-gap", "note": "Trakhees jurisdiction - not in the DM building register; listed so the map is not blind there"})
    # contacts for every placed mall (phone, website, address, hours) - one cached lookup per mall
    for it in items:
        if not (it.get("lon") and it.get("name")): continue
        ck = "mallc:" + it["name"]
        if ck not in cache and gkey:
            try: cache[ck] = places_contact(gkey, it["name"], it.get("community") or ""); paid += 1
            except Exception: cache[ck] = None
        c = cache.get(ck) or {}
        if c.get("tel"): it["tel"] = c["tel"]
        if c.get("web"): it["web"] = c["web"]
        if c.get("address"): it["ad"] = c["address"]
        if c.get("hours"): it["hrs"] = c["hours"]
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "definition": "Dubai Municipality building register: usage 'Shopping Centre', completed, >= 50,000 m2 built, one per parcel; tiers major >= 200k, large >= 100k, community >= 50k",
           "counts": {"dm_parcels": len(rows), "named_and_placed": sum(1 for i in items if i["lon"] and i["src"] == "dm+google"), "unplaced": sum(1 for i in items if not i["lon"]), "trakhees_gap": sum(1 for i in items if i["src"] == "trakhees-gap")},
           "items": items}
    json.dump(doc, open(os.path.join(REG, "dm_malls.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DM mall parcels {len(rows)} | placed {doc['counts']['named_and_placed']} | unplaced {doc['counts']['unplaced']} | gap {doc['counts']['trakhees_gap']} | google paid {paid}")
    for i in items:
        print(f"  {i['tier']:<9} {str(i['name'] or '-'):<34} {i['community'][:22]:<22} {str(i['built_m2'] or ''):>8}  {i['src']:<13} {i.get('note','')[:70]}")


if __name__ == "__main__":
    main()
