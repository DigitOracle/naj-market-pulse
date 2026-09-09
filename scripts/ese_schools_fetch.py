"""Government schools from the Emirates Schools Establishment's own map API (Kendall, 7 Sep: "can we get the government schools
from the ministry site?").

The public site (ese.gov.ae) was connection-reset from every path that day; the schools-map page in the Web Archive revealed
the feed it draws from, and that host answers:  GET https://apigateway.ese.gov.ae/integration/api/schoolmap/GetSchoolMaps
No auth. 490 schools and kindergartens UAE-wide, 48 in the Dubai zone, precise lat/long, Arabic names only (no English variant
on any lang/culture parameter). English names are kept by hand in names_en.json, keyed by the feed's `id`; a new id shows up
in the run log so the map can carry it.

Output data/registers/ese_school_map/GetSchoolMaps_ar.json   (consumed by amenities_official.py)
Usage: python scripts/ese_schools_fetch.py
"""
import json, os, sys
import requests
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "registers", "ese_school_map")
URL = "https://apigateway.ese.gov.ae/integration/api/schoolmap/GetSchoolMaps"
DUBAI = "دبي"          # the zone label the feed uses for Dubai


def main():
    os.makedirs(OUT, exist_ok=True)
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=90)
    r.raise_for_status()
    d = r.json()
    json.dump(d, open(os.path.join(OUT, "GetSchoolMaps_ar.json"), "w", encoding="utf-8"), ensure_ascii=False)
    dxb = [x for x in d if (x.get("educationZone") or "").strip() == DUBAI]
    en_path = os.path.join(OUT, "names_en.json")
    en = json.load(open(en_path, encoding="utf-8")) if os.path.exists(en_path) else {}
    missing = [x for x in dxb if str(x.get("id")) not in en]
    print(f"ESE feed: {len(d)} schools UAE-wide, {len(dxb)} in Dubai, {sum(1 for x in dxb if x.get('latitude'))} with coordinates")
    if missing:
        print(f"  {len(missing)} Dubai school(s) have no English name yet - add them to names_en.json:")
        for x in missing: print(f"    {x['id']}  {x['schoolName']}")


if __name__ == "__main__":
    main()
