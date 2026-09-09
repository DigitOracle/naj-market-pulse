"""Sub-community points for the map (KV `subs`): every verified cluster from data/names/clusters_<slug>.json as one GeoJSON point
with name, district, plots, units, radius and how many footprints carry it. A sub-community with zero footprints is still real -
The Valley's Rivana or Elwood Estates are registered plots that are not yet built.

Output data/board/subs.json -> KV `subs`.   Usage: python scripts/subs_points.py [--no-push]
"""
import glob, json, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
NAMES = os.path.join(ROOT, "data", "names"); BOARD = os.path.join(ROOT, "data", "board")


def main():
    feats = []; per = {}
    for f in sorted(glob.glob(os.path.join(NAMES, "clusters_*.json"))):
        slug = os.path.basename(f)[9:-5]
        try: d = json.load(open(f, encoding="utf-8"))
        except Exception: continue
        n = 0
        for c in d.get("clusters") or []:
            if not (c.get("lon") and c.get("lat") and c.get("name")): continue
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                          "properties": {"name": c["name"].strip(), "district": slug, "plots": c.get("plots") or 0, "units": c.get("units") or 0,
                                         "radius_m": c.get("radius_m") or 200, "buildings": c.get("footprints") or 0}})
            n += 1
        per[slug] = n
    doc = {"type": "FeatureCollection", "generated": time.strftime("%Y-%m-%d %H:%M"), "features": feats}
    json.dump(doc, open(os.path.join(BOARD, "subs.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"sub-communities {len(feats):,} across {len(per)} districts | {os.path.getsize(os.path.join(BOARD, 'subs.json'))//1024} KB")
    for s, n in sorted(per.items(), key=lambda x: -x[1])[:8]: print(f"  {s:<26} {n}")
    if "--no-push" not in sys.argv: print("subs ->", push("subs", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
