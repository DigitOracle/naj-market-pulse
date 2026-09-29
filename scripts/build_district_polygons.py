"""District boundaries from the Dubai Municipality community polygons - so "in <district>" means inside it.

Until 29 Sep 2026 both lanes decided membership with the district's RECTANGULAR bbox: the worker's inArea() (a point in
two overlapping boxes counted for both) and amenities_official.in_district() (first box in list order wins - which is
how Business Bay Metro Station came to be tagged Al Wasl). On Business Bay the map said 61 clinics "in community"; the
true boundary holds 47. Kendall approved the fix on 29 Sep.

The boundaries already existed: data/board/communities.geojson, 223 DM community polygons. What was missing was the
mapping from the app's 44 districts (marketing names: Dubai Marina, JVC, Palm Jumeirah) to DM communities (Marsa
Dubai, Al Barsha South Fourth, Nakhlat Jumeira). It is derived from data, not from memory: every sub-community the
live map serves carries its district and a position, and the position falls in exactly one community polygon. A
district takes the communities that hold at least 10% of its sub-communities (boundary strays of one are dropped).
Districts with no sub-communities fall back to a name match (slug or name equals a DM community name), then to the
community containing their centre - marked "CHECK", because a bbox centre can sit in a neighbour.

Writes:
  data/board/district_communities.json   slug -> {comm_nums, names, method, evidence}
  data/board/district_polygons.geojson   one MultiPolygon per district, for the worker's point-in-polygon test

    python scripts/build_district_polygons.py --subs <subs.geojson>   # the /img/subs feed, saved from the live map
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, "data", "board")
MIN_SHARE = 0.10


def load_communities():
    polys = []
    for f in json.load(open(os.path.join(BOARD, "communities.geojson"), encoding="utf-8"))["features"]:
        rings = f["geometry"]["coordinates"]
        xs = [p[0] for p in rings[0]]
        ys = [p[1] for p in rings[0]]
        polys.append({"comm_num": f["properties"]["comm_num"], "name": f["properties"]["name_en"], "rings": rings,
                      "bbox": (min(xs), min(ys), max(xs), max(ys))})
    return polys


def _pip(x, y, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_polygon(x, y, rings):
    """Inside the outer ring and outside every hole."""
    return _pip(x, y, rings[0]) and not any(_pip(x, y, h) for h in rings[1:])


def community_at(x, y, polys):
    for p in polys:
        b = p["bbox"]
        if b[0] <= x <= b[2] and b[1] <= y <= b[3] and in_polygon(x, y, p["rings"]):
            return p
    return None


def main():
    if "--subs" not in sys.argv:
        sys.exit(__doc__)
    subs = json.load(open(sys.argv[sys.argv.index("--subs") + 1], encoding="utf-8"))["features"]
    polys = load_communities()
    by_num = {p["comm_num"]: p for p in polys}
    districts = json.load(open(os.path.join(BOARD, "districts_geo.json"), encoding="utf-8"))["districts"]

    counts = defaultdict(Counter)
    for f in subs:
        x, y = f["geometry"]["coordinates"]
        p = community_at(x, y, polys)
        counts[f["properties"]["district"]][p["comm_num"] if p else None] += 1

    # DM's own parcel keys come first where a district has them: comm_num = parcel_key // 10000 (or // 100000 for the
    # longer keys, e.g. Madinat Hind 4's 9141xxxxx). Sobha Hartland's three sub-community points sit in Al Merkadh
    # (two share one coordinate), but all seven of its parcels are keyed to Nadd Al Shiba First.
    parcels = defaultdict(Counter)
    plots = json.load(open(os.path.join(BOARD, "plots.json"), encoding="utf-8"))
    for q in (plots["features"] if isinstance(plots, dict) and "features" in plots else plots):
        q = q.get("properties", q)
        try:
            key = int(float(q["parcel"]))
        except (KeyError, TypeError, ValueError):
            continue
        comm = key // 10000 if key // 10000 in by_num else key // 100000
        if comm in by_num:
            parcels[q.get("district")][comm] += 1

    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    by_name = {norm(p["name"]): p["comm_num"] for p in polys}
    out, feats = {}, []
    for d in districts:
        slug = d["slug"]
        c = counts.get(slug)
        pc = parcels.get(slug)
        if pc:
            total = sum(pc.values())
            nums = [n for n, k in pc.most_common() if k / total >= MIN_SHARE]
            method, evidence = "DM parcel keys", {str(n): k for n, k in pc.most_common()}
        elif c:
            total = sum(c.values())
            nums = [n for n, k in c.most_common() if n is not None and k / total >= MIN_SHARE]
            method, evidence = "sub-communities", {str(n): k for n, k in c.most_common()}
        elif norm(slug) in by_name or norm(d["name"]) in by_name:
            # the slug or name IS a DM community name (bukadra -> BU KADRA): trust that over a bbox centre, which put
            # Bu Kadra in Nadd Al Shiba First
            nums = [by_name.get(norm(slug)) or by_name[norm(d["name"])]]
            method, evidence = "name match", {}
        else:
            p = community_at(d["centre"][0], d["centre"][1], polys)
            nums = [p["comm_num"]] if p else []
            method, evidence = "district centre - CHECK", {}
        out[slug] = {"name": d["name"], "comm_nums": nums, "names": [by_num[n]["name"] for n in nums],
                     "method": method, "evidence": evidence}
        if nums:
            feats.append({"type": "Feature", "properties": {"slug": slug, "name": d["name"], "comm_nums": nums},
                          "geometry": {"type": "MultiPolygon",
                                       "coordinates": [by_num[n]["rings"] for n in nums]}})

    json.dump({"about": "App district -> DM community polygons (scripts/build_district_polygons.py)",
               "districts": out}, open(os.path.join(BOARD, "district_communities.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"type": "FeatureCollection", "features": feats},
              open(os.path.join(BOARD, "district_polygons.geojson"), "w", encoding="utf-8"), ensure_ascii=False)
    for slug, v in out.items():
        print("%-26s %-17s %s" % (slug, v["method"], ", ".join("%s %s" % x for x in zip(v["comm_nums"], v["names"]))
                                  or "** NONE **"))
    print("%d districts, %d with a boundary" % (len(out), len(feats)))


if __name__ == "__main__":
    main()
