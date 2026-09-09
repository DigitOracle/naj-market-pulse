"""What is around a home: schools, healthcare, metro, malls, parks and beaches, per district (Kendall, 7 Sep).

Source: Overture Maps `place` (POI). Categories are messy - a dance school is not a school and a medical spa is not a hospital -
so each group is an explicit allow-list, and anything outside it is dropped rather than guessed at. Metro comes from the same
source (train / subway stations) because it carries the station's own name.

Output data/board/amenities_<slug>.json  {"district", "counts": {...}, "items": [{k, n, lon, lat}]}   k = group key, n = name
       data/board/amenities.json          every district merged, for the map
Pushed as KV `amenities`. Kept deliberately small: name, group and position only.
Usage: python scripts/amenities.py [--skip-download] [slug ...]
"""
import json, os, subprocess, sys, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); RAW = os.path.join(ROOT, "data", "names", "overture_raw"); BOARD = os.path.join(ROOT, "data", "board")

GROUPS = {
    "school": {"school", "private_school", "elementary_school", "middle_school", "high_school", "primary_school",
               "public_school", "international_school", "preschool", "day_care_preschool", "kindergarten",
               "college_university", "university", "vocational_and_technical_school", "specialty_school", "educational_services"},
    "health": {"hospital", "medical_center", "clinic", "medical_clinic", "health_and_medical", "doctor", "dentist",
               "urgent_care_clinic", "womens_health_clinic", "health_department", "emergency_room", "pharmacy"},
    "metro":  {"train_station", "subway_station", "metro_station", "transit_station", "light_rail_station", "tram_station"},
    "mall":   {"shopping_center", "shopping_mall", "mall", "department_store"},
    "park":   {"park", "amusement_park", "playground", "garden", "public_plaza", "dog_park"},
    "beach":  {"beach", "beach_resort"},
}
CAT2GROUP = {c: g for g, cs in GROUPS.items() for c in cs}
DROP_WORDS = ("dance", "driving", "cooking", "music", "swim", "language", "cosmetology", "surfing", "gymnastics",
              "training", "tutor", "nursery furniture", "supply", "spa", "research")


def bbox(slug):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj): return None
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for f in json.load(open(gj, encoding="utf-8"))["features"]: walk(f["geometry"]["coordinates"])
    if not xs: return None
    return (min(xs) - 0.004, min(ys) - 0.004, max(xs) + 0.004, max(ys) + 0.004)      # ~450 m past the edge


def fetch(slug, bb, skip):
    out = os.path.join(RAW, f"{slug}_place.geojson")
    if os.path.exists(out) and os.path.getsize(out) > 200: return out
    if skip: return None
    os.makedirs(RAW, exist_ok=True)
    try:
        subprocess.run([sys.executable, "-m", "overturemaps", "download", f"--bbox={bb[0]:.5f},{bb[1]:.5f},{bb[2]:.5f},{bb[3]:.5f}",
                        "-f", "geojson", "--type=place", "-o", out], capture_output=True, timeout=900)
    except Exception as e:
        print("   download failed:", slug, str(e)[:50]); return None
    return out if os.path.exists(out) and os.path.getsize(out) > 200 else None


def main():
    skip = "--skip-download" in sys.argv
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    slugs = want or sorted(d for d in os.listdir(CE) if os.path.exists(os.path.join(CE, d, "buildings.geojson")))
    allitems = []; grand = collections.Counter(); t = time.time()
    for slug in slugs:
        bb = bbox(slug)
        if not bb: continue
        src = fetch(slug, bb, skip)
        if not src: continue
        items = []; seen = set()
        try: F = json.load(open(src, encoding="utf-8"))["features"]
        except Exception: continue
        for f in F:
            pr = f.get("properties") or {}
            cat = (pr.get("categories") or {}).get("primary")
            g = CAT2GROUP.get(cat)
            if not g: continue
            nm = ((pr.get("names") or {}).get("primary") or "").strip()
            if not nm or any(w in nm.lower() for w in DROP_WORDS): continue
            geom = f.get("geometry") or {}
            if geom.get("type") != "Point": continue
            lon, lat = geom["coordinates"][:2]
            if not (bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]): continue
            k = (g, round(lon, 5), round(lat, 5))
            if k in seen: continue
            seen.add(k)
            items.append({"k": g, "n": nm[:60], "lon": round(lon, 6), "lat": round(lat, 6)})
        if not items: continue
        c = collections.Counter(i["k"] for i in items)
        json.dump({"district": slug, "generated": time.strftime("%Y-%m-%d"), "source": "Overture Maps places (POI), explicit category allow-list",
                   "counts": dict(c), "items": items}, open(os.path.join(BOARD, f"amenities_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        for i in items: i["d"] = slug
        allitems += items; grand.update(c)
        print(f"  {slug:<26} {len(items):>5} amenities  {dict(c)}", flush=True)
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "counts": dict(grand),
           "note": "Schools, healthcare, metro, malls, parks and beaches from Overture places. Category allow-list; driving and dance schools, medical spas and the like are excluded.",
           "items": allitems}
    json.dump(doc, open(os.path.join(BOARD, "amenities.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nTOTAL {len(allitems):,} amenities | {dict(grand)} | {os.path.getsize(os.path.join(BOARD,'amenities.json'))//1024} KB | {time.time()-t:.0f}s")
    print("amenities ->", push("amenities", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
