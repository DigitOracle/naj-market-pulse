"""LAB (technique #5, telling villas from towers) - fetch OpenStreetMap buildings WITH their tags for a district.

Why: data/ce/<slug>/buildings.geojson was cut from OSM by ce_export.py / reexport_footprints.py, but only
status / bHeight / name / levels survived the export - the `building=*` value (house, apartments, warehouse,
school, mosque ...), roof:shape, amenity and the rest were dropped. This pulls them back, once, to disk.

Polite by construction: ONE Overpass query per district, a pause between districts, a cache that is never
re-fetched unless --refresh is given, and the same mirror list and contact User-Agent the repo already uses.

Query (district bbox = the bbox of our own footprints, padded 50 m):
    way["building"] + relation["building"]      out tags geom   (footprints + every tag)
    node[amenity|shop|office|craft|building]    out tags        (POIs that sit inside a footprint)

Context layer (--context, a second polite query per district): landuse=residential|industrial|commercial|retail
areas and amenity=school|kindergarten|college|university|place_of_worship|hospital grounds, out tags geom. The
repo's own data/ce/<slug>/landuse_osm.json was filtered to green / water, so it cannot say "industrial".

Output: data/lab/buildingtype/osm_<slug>.json       {"fetched", "bbox", "query", "elements": [...]}
        data/lab/buildingtype/osm_ctx_<slug>.json   (with --context)
Usage:  python scripts/lab_buildingtype_fetch.py damachills businessbay dubaiinvestmentparkfirst
        python scripts/lab_buildingtype_fetch.py --context damachills businessbay dubaiinvestmentparkfirst
Research use only. Reads data/ce/<slug>/buildings.geojson; writes only under data/lab/buildingtype/.
"""
import json, os, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "lab", "buildingtype"); os.makedirs(OUT, exist_ok=True)
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
UA = {"User-Agent": "najma-lab-buildingtype/1.0 (research; contact@digitalabbot.io)"}
PAUSE_S = 20          # between districts
PAD = 0.0005          # ~50 m


def bbox_of(slug):
    feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    xs, ys = [], []
    for f in feats:
        g = f["geometry"]; polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for x, y in poly[0]:
                xs.append(x); ys.append(y)
    return round(min(ys) - PAD, 6), round(min(xs) - PAD, 6), round(max(ys) + PAD, 6), round(max(xs) + PAD, 6)


def query(bb):
    b = "%s,%s,%s,%s" % bb
    return ("[out:json][timeout:180];"
            "(way[\"building\"](%s);relation[\"building\"](%s););out tags geom;"
            "(node[\"amenity\"](%s);node[\"shop\"](%s);node[\"office\"](%s);node[\"craft\"](%s);node[\"building\"](%s););out body;"
            % (b, b, b, b, b, b, b))
# NOTE (29 Sep run): the three cached osm_<slug>.json files were fetched with `out tags;` on the POI nodes, which drops their
# lat/lon, so their nodes are unusable. The POIs come from the --context query instead (below, `out body`), not a re-fetch.


def query_ctx(bb):
    b = "%s,%s,%s,%s" % bb
    lu = 'landuse~"^(residential|industrial|commercial|retail)$"'
    am = 'amenity~"^(school|kindergarten|college|university|place_of_worship|hospital)$"'
    po = ["amenity", "shop", "office", "craft"]
    return ("[out:json][timeout:180];"
            "(way[%s](%s);way[%s](%s);relation[%s](%s););out geom(%s);" % (lu, b, am, b, am, b, b)   # landuse RELATIONS dropped: 504s on 29 Sep
            + "(" + "".join("node[\"%s\"](%s);" % (k, b) for k in po) + ");out body;")


def fetch(q):
    last = None
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.load(r)["elements"], url
        except Exception as e:
            last = e
            print("  overpass %s: %s - next mirror in 10 s" % (url.split("//")[1].split("/")[0], e), flush=True)
            time.sleep(10)
    raise SystemExit("Overpass unreachable on all mirrors: %s" % last)


def main():
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")]
    refresh = "--refresh" in sys.argv; ctx = "--context" in sys.argv
    fetched_any = False
    for slug in slugs:
        dst = os.path.join(OUT, ("osm_ctx_%s.json" if ctx else "osm_%s.json") % slug)
        if os.path.exists(dst) and not refresh:
            j = json.load(open(dst, encoding="utf-8"))
            print("  %-26s cached %s  (%d elements)" % (slug, j.get("fetched"), len(j.get("elements", []))))
            continue
        if fetched_any:
            print("  pausing %d s (polite)" % PAUSE_S); time.sleep(PAUSE_S)
        bb = bbox_of(slug); q = query_ctx(bb) if ctx else query(bb)
        t = time.time(); els, url = fetch(q); fetched_any = True
        json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "mirror": url, "bbox_s_w_n_e": bb, "query": q, "elements": els},
                  open(dst, "w", encoding="utf-8"), ensure_ascii=False)
        nb = sum(1 for e in els if e["type"] in ("way", "relation")); nn = sum(1 for e in els if e["type"] == "node")
        print("  %-26s %5d building ways/relations, %5d POI nodes  (%.1f s, %s)" % (slug, nb, nn, time.time() - t, url.split("//")[1].split("/")[0]))


if __name__ == "__main__":
    main()
