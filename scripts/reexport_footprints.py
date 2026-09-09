"""Re-export a district's footprints from OpenStreetMap at BUILDING level - ways AND relations - replacing plot fragments.

Why this exists. The original export (ce_export.py) asked Overpass for `way["building"]` only. In JLT that returned 3,548
polygons with a median area of 588 m2: podium slabs, plot pieces and outbuildings. The towers themselves are very often
mapped as `relation["building"]` multipolygons (an outer ring with a courtyard or a podium cut-out), and relations were never
requested - so 57 of the 136 tall buildings OSM knows in that box overlap nothing we hold, and the district reads as 84 towers
in a field of 3,400 stumps. Heights cannot fix a footprint that is not there.

What it does, per district:
  1. Overpass: way["building"] + relation["building"], `out geom`, inside the district's existing bbox (kept from the current file,
     so the district does not grow).
  2. Relations become polygons from their OUTER members; ways that are members of a building relation are dropped so a tower is
     not drawn twice (once as the relation, once as its own outline way).
  3. `building:part` ways are NOT footprints (they are pieces of a building) - they are left to osm_heights.py, which reads them
     for height. Tiny slivers (< 15 m2) and non-building tags (roof, shelter, wall, fence) are dropped.
  4. Every footprint keeps the same property schema the massing expects - status, bHeight, name, levels - with bHeight from
     `height=` or `building:levels` where OSM states them (feet detected), plus height_source and an osm id for provenance.
  5. Anything from the OLD file that the new export does not cover (a plot OSM has since deleted) is reported, not silently lost.

Nothing downstream is touched: run osm_heights.py, build_anchors.py, then the CityEngine re-mass, then bldgfacts / push /
resolve / apply. The previous geojson is kept as buildings.geojson.bak_fragments.

Usage: python scripts/reexport_footprints.py --dry <slug>   |   python scripts/reexport_footprints.py <slug>
"""
import argparse, json, math, os, re, sys, time, urllib.parse, urllib.request
import pyproj
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); RAW = os.path.join(ROOT, "data", "names", "osm_footprints_raw"); os.makedirs(RAW, exist_ok=True)
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
UA = {"User-Agent": "najma-footprints/1.0 (contact@digitalabbot.io)"}
NOT_BUILDINGS = {"roof", "shelter", "wall", "fence", "carport", "canopy", "no", "construction_site", "ruins", "tent"}
STOREY_M, GROUND_M = 3.2, 3.0
TF = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform


def num(v):
    m = re.match(r"^\s*(-?[\d.]+)", str(v or "").replace(",", ""))
    try: return float(m.group(1)) if m else None
    except ValueError: return None


def height_of(tags):
    lv = num(tags.get("building:levels")); h = num(tags.get("height"))
    ft = bool(re.search(r"(ft|feet|')\s*$", str(tags.get("height") or "")))
    if h is not None:
        if ft or (300 <= h <= 1200 and (not lv or h > lv * 4.5)): h = round(h * 0.3048, 1)
        if lv and h > lv * 3.6 + 12: return round(lv * STOREY_M + GROUND_M, 1), "osm levels (height implausible)", lv
        return h, "osm height", lv
    if lv and lv >= 1: return round(lv * STOREY_M + GROUND_M, 1), "osm levels", lv
    return None, None, lv


def fetch(slug, bbox, force=False):
    f = os.path.join(RAW, f"{slug}.json")
    if os.path.exists(f) and os.path.getsize(f) > 100 and not force: return json.load(open(f, encoding="utf-8"))
    s, w, n, e = bbox[1], bbox[0], bbox[3], bbox[2]
    q = f'[out:json][timeout:240];(way["building"]({s},{w},{n},{e});relation["building"]({s},{w},{n},{e}););out geom;'
    last = ""
    for m in MIRRORS:
        try:
            r = urllib.request.urlopen(urllib.request.Request(m, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA), timeout=300)
            j = json.loads(r.read().decode("utf-8")); json.dump(j, open(f, "w", encoding="utf-8"), ensure_ascii=False); return j
        except Exception as ex:
            last = str(ex)[:70]; time.sleep(5)
    raise SystemExit(f"overpass failed for {slug}: {last}")


def poly_from_way(geom):
    pts = [(p["lon"], p["lat"]) for p in geom if "lon" in p]
    if len(pts) < 4: return None
    if pts[0] != pts[-1]: pts.append(pts[0])
    pg = Polygon(pts)
    return pg if pg.is_valid else pg.buffer(0)


def poly_from_relation(rel):
    outers, inners = [], []
    for mem in rel.get("members", []):
        if mem.get("type") != "way" or not mem.get("geometry"): continue
        pg = poly_from_way(mem["geometry"])
        if pg is None or pg.is_empty: continue
        (outers if mem.get("role") != "inner" else inners).append(pg)
    if not outers: return None
    body = unary_union(outers)
    if inners:
        try: body = body.difference(unary_union(inners))
        except Exception: pass
    if body.geom_type == "MultiPolygon": body = max(body.geoms, key=lambda g: g.area)     # one massing per building
    return body if body.is_valid and not body.is_empty else None


def area_m2(pg):
    try: return Polygon([TF(x, y) for x, y in pg.exterior.coords]).area
    except Exception: return 0.0


def run(slug, dry, force):
    gj = os.path.join(CE, slug, "buildings.geojson")
    old = json.load(open(gj, encoding="utf-8"))
    xs = [p[0] for f in old["features"] for p in shape(f["geometry"]).exterior.coords]
    ys = [p[1] for f in old["features"] for p in shape(f["geometry"]).exterior.coords]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    J = fetch(slug, bbox, force)
    els = J.get("elements", [])
    member_ways = set()
    for e in els:
        if e.get("type") == "relation":
            for m in e.get("members", []):
                if m.get("type") == "way": member_ways.add(m.get("ref"))
    feats, dropped = [], {"member_of_relation": 0, "not_a_building": 0, "sliver": 0, "bad_geometry": 0}
    for e in els:
        tags = e.get("tags") or {}
        if tags.get("building") in NOT_BUILDINGS: dropped["not_a_building"] += 1; continue
        if e.get("type") == "way":
            if e.get("id") in member_ways: dropped["member_of_relation"] += 1; continue
            pg = poly_from_way(e.get("geometry") or [])
        else:
            pg = poly_from_relation(e)
        if pg is None or pg.is_empty: dropped["bad_geometry"] += 1; continue
        a = area_m2(pg)
        if a < 15: dropped["sliver"] += 1; continue
        h, basis, lv = height_of(tags)
        props = {"status": "existing", "bHeight": h if h else 12.0, "name": (tags.get("name:en") or tags.get("name") or "").strip(),
                 "levels": str(int(lv)) if lv else "", "osm": f"{e.get('type')}/{e.get('id')}", "footprint_m2": round(a)}
        if h: props["height_source"] = "osm_export"; props["height_basis"] = basis
        feats.append({"type": "Feature", "properties": props, "geometry": mapping(pg)})
    new = {"type": "FeatureCollection", "features": feats}
    # what the old file had that the new one does not cover at all (OSM deletions, or our bbox clipping)
    from shapely.strtree import STRtree
    newpolys = [shape(f["geometry"]) for f in feats]; idx = STRtree(newpolys) if newpolys else None
    uncovered = 0
    for f in old["features"]:
        opg = shape(f["geometry"])
        if idx is None or not any(newpolys[int(j)].intersects(opg) for j in idx.query(opg)): uncovered += 1
    areas = sorted(f["properties"]["footprint_m2"] for f in feats)
    tall = sum(1 for f in feats if f["properties"]["bHeight"] > 60); real = sum(1 for f in feats if f["properties"]["bHeight"] > 12.01)
    named = sum(1 for f in feats if f["properties"]["name"])
    rels = sum(1 for f in feats if f["properties"]["osm"].startswith("relation"))
    print(f"{slug}: OLD {len(old['features']):,} footprints  ->  NEW {len(feats):,}  ({rels} from relations)")
    print(f"  median area {areas[len(areas)//2] if areas else 0} m2 (old 588) | named {named:,} | real height {real:,} | towers >60 m {tall}")
    print(f"  dropped: {dropped} | old footprints with no new coverage: {uncovered}")
    if dry: return
    bak = gj + ".bak_fragments"
    if not os.path.exists(bak): json.dump(old, open(bak, "w", encoding="utf-8"))
    json.dump(new, open(gj, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  written -> {gj}  (previous kept as .bak_fragments)")
    print("  next: python scripts/osm_heights.py --force", slug, "| python scripts/build_anchors.py", slug, "| CE re-mass: python scripts/ce_batch_v2.py --v3", slug)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("slug"); a = ap.parse_args()
    run(a.slug, a.dry, a.force)
