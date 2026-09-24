"""Sub-community points for the map (KV `subs`): every verified cluster from data/names/clusters_<slug>.json as one GeoJSON point
with name, district, plots, units, radius and how many footprints carry it. A sub-community with zero footprints is still real -
The Valley's Rivana or Elwood Estates are registered plots that are not yet built.
16 Sep 2026 (digital thread P2.3): each point also carries `sub_id` - the card's own id, the DLD project it names where the register has
one (1,833 of 1,834) - and `project`, so the graph stops numbering cards by their position in this file.

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


def keys():
    """16 Sep 2026 (digital thread P2.3): (district, card name) -> the card's own id and the DLD project it names, from the lake's
    crosswalk (register_joins.py sub_communities). Empty when the lake has none - the ids then stay list positions, as before."""
    try:
        import lake
        lk = lake.connect(read_only=True)
        if not lk.execute("select count(*) from information_schema.tables where table_name = 'lk_sub_community'").fetchone()[0]:
            return {}
        return {(d, n, "%.5f|%.5f" % (lo or 0, la or 0)): (cid, pid) for d, n, lo, la, cid, pid in
                lk.execute("select district, name, lon, lat, canonical_id, project_canonical_id from lk_sub_community").fetchall()}
    except Exception as e:
        print("  sub-community keys unavailable:", str(e)[:90])
        return {}


def main():
    feats = []; per = {}; K = keys(); keyed = 0; seen = set()
    for f in sorted(glob.glob(os.path.join(NAMES, "clusters_*.json"))):
        slug = os.path.basename(f)[9:-5]
        try: d = json.load(open(f, encoding="utf-8"))
        except Exception: continue
        n = 0
        for c in d.get("clusters") or []:
            if not (c.get("lon") and c.get("lat") and c.get("name")): continue
            spot = (slug, c["name"].strip(), "%.5f|%.5f" % (c["lon"], c["lat"]))
            if spot in seen:                     # the same card twice in one file is one place on the map, not two points
                continue
            seen.add(spot)
            sub_id, project = K.get(spot, (None, None))
            keyed += bool(project)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                          "properties": {"name": c["name"].strip(), "district": slug, "plots": c.get("plots") or 0, "units": c.get("units") or 0,
                                         "radius_m": c.get("radius_m") or 200, "buildings": c.get("footprints") or 0,
                                         "sub_id": sub_id, "project": project}})
            n += 1
        per[slug] = n
    doc = {"type": "FeatureCollection", "generated": time.strftime("%Y-%m-%d %H:%M"), "features": feats}
    json.dump(doc, open(os.path.join(BOARD, "subs.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"sub-communities {len(feats):,} across {len(per)} districts | {os.path.getsize(os.path.join(BOARD, 'subs.json'))//1024} KB"
          f" | keyed to a DLD project {keyed:,}")
    for s, n in sorted(per.items(), key=lambda x: -x[1])[:8]: print(f"  {s:<26} {n}")
    if "--push" not in sys.argv:
        print("  not pushed. data/board/subs.json is written; pass --push to ship it, and only with the"
              " deploying session's agreement.")
    if "--push" in sys.argv and "--no-push" not in sys.argv: print("subs ->", push("subs", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
