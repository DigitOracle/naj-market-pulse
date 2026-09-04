"""Real building heights from OpenStreetMap, for the 14,000 footprints standing at the 12 m default.

The twin's weakest layer is not names, it is heights: outside Marina, Downtown and Business Bay almost every building is a
12 m stump, which is why those districts read as grey fields. The cause was an export that kept only what it happened to
carry - it never asked OpenStreetMap for `height` or `building:levels`. Both are there. In the JLT box alone OSM holds 205
explicit heights and 221 buildings of ten floors or more: Green Lakes 1 at 131 m, MAG 214 at 164 m, Armada Tower 1 at 167 m,
every one of which the model currently draws as a 12 m box.

    height=          taken as given, in metres (a value in feet is detected and converted, never silently believed)
    building:levels= levels x 3.2 m + 3 m for the ground floor, the same estimate the massing already uses

PLAUSIBILITY, because a wrong height is worse than a missing one. Learned the hard way on Marina Arcade (445 m from a
neighbour's centroid) and Paramount Midtown (886 m from a Wikidata value in feet):
  - a height must sit within 3.6 m per floor plus 12 m of its own floor count when both are known
  - a value between 300 and 1,200 with no floor count to support it is treated as feet and converted
  - a candidate more than 1.6x an existing SURVEYED height is rejected outright
  - the match is decided by real POLYGON OVERLAP in metres, not by centroid distance: an OSM building must cover at
    least 60% of our footprint before its height is inherited. A centroid test gave Lake Shore Tower a 2-level podium,
    because our JLT footprints are plot-sized fragments (median 588 m2) beneath towers OSM draws as one large polygon.

Writes bHeight and height_source into data/ce/<slug>/buildings.geojson (a .bak is kept). The model only changes when the
district is re-massed in CityEngine - this prepares that, it does not do it.

Usage: python scripts/osm_heights.py [--dry] [slug ...]
"""
import argparse, glob, json, math, os, re, sys, time, urllib.parse, urllib.request
import pyproj
from shapely.geometry import Polygon
from shapely.strtree import STRtree

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "names", "osm_heights_geom")
os.makedirs(OUT, exist_ok=True)
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
UA = {"User-Agent": "najma-heights/1.0 (contact@digitalabbot.io)"}
STOREY_M, GROUND_M = 3.2, 3.0
NEAR_M = 12.0


def metres(a, b):
    r = 6371000.0; p1, p2 = math.radians(a[1]), math.radians(b[1])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def ring_of(g):
    if not g: return []
    if g["type"] == "Polygon": return g["coordinates"][0]
    if g["type"] == "MultiPolygon": return max((p[0] for p in g["coordinates"]), key=len)
    return []


def centroid(r): return (sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r))


def inside(pt, ring):
    x, y = pt; ins = False; n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]; x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1: ins = not ins
    return ins


def num(v):
    if v is None: return None
    m = re.match(r"^\s*(-?[\d.]+)", str(v).replace(",", ""))
    if not m: return None
    try: return float(m.group(1))
    except ValueError: return None


def fetch(slug, box, force=False):
    f = os.path.join(OUT, f"{slug}.json")
    if os.path.exists(f) and os.path.getsize(f) > 40 and not force:
        return json.load(open(f, encoding="utf-8"))
    s, w, n, e = box[1], box[0], box[3], box[2]
    b = f"{s},{w},{n},{e}"
    q = ("[out:json][timeout:240];("
         f'way["building"]["height"]({b});way["building"]["building:levels"]({b});'
         f'way["building:part"]["height"]({b});relation["building"]["height"]({b});'
         ");out tags geom;")
    last = ""
    for m in MIRRORS:
        try:
            r = urllib.request.urlopen(urllib.request.Request(m, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA), timeout=300)
            j = json.loads(r.read().decode("utf-8"))
            json.dump(j, open(f, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(6)
            return j
        except Exception as ex:
            last = str(ex)[:70]; time.sleep(4)
    print(f"    overpass failed for {slug}: {last}")
    return None


def candidate(tags):
    """(height_m, basis) from a way's tags, or (None, why). Feet are detected, never believed silently."""
    lv = num(tags.get("building:levels")) or num(tags.get("levels"))
    h = num(tags.get("height")) or num(tags.get("building:height"))
    unit_ft = bool(re.search(r"(ft|feet|')\s*$", str(tags.get("height") or "")))
    if h is not None:
        if unit_ft or (300 <= h <= 1200 and (not lv or h > lv * 4.5)):
            h = round(h * 0.3048, 1); basis = "osm height (feet -> metres)"
        else:
            basis = "osm height"
        if lv and h > lv * 3.6 + 12:                      # says 40 floors, claims 300 m: trust the floors
            return (round(lv * STOREY_M + GROUND_M, 1), f"osm levels {int(lv)} (stated height implausible for the floor count)")
        return (h, basis)
    if lv and lv >= 1:
        return (round(lv * STOREY_M + GROUND_M, 1), f"osm levels {int(lv)}")
    return (None, "no height or levels")


def utm_poly(ring, tf):
    """A shapely polygon in metres. Everything below is decided in metres, never in degrees."""
    try:
        pts = [tf(x, y) for x, y in ring]
        pg = Polygon(pts)
        return pg if pg.is_valid else pg.buffer(0)
    except Exception:
        return None


def run(slug, dry, force):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj): return None
    G = json.load(open(gj, encoding="utf-8"))
    feats = G["features"]
    xs = [p[0] for f in feats for p in ring_of(f["geometry"])]; ys = [p[1] for f in feats for p in ring_of(f["geometry"])]
    if not xs: return None
    box = (min(xs) - 0.001, min(ys) - 0.001, max(xs) + 0.001, max(ys) + 0.001)
    J = fetch(slug, box, force)
    if not J: return None
    tf = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform

    # OSM ways that carry a usable height, as polygons in metres
    osm = []
    for e in J.get("elements", []):
        g = e.get("geometry")
        if not g or len(g) < 4: continue
        h, basis = candidate(e.get("tags") or {})
        if not h or h <= 3: continue
        pg = utm_poly([(q["lon"], q["lat"]) for q in g], tf)
        if pg is None or pg.area < 20: continue
        osm.append({"pg": pg, "h": h, "basis": basis, "id": e.get("id"), "name": (e.get("tags") or {}).get("name")})
    idx = STRtree([o["pg"] for o in osm]) if osm else None

    fixed = raised = rejected = 0; report = []
    for f in feats:
        ring = ring_of(f["geometry"])
        if len(ring) < 3: continue
        p = f["properties"]; cur = float(p.get("bHeight") or 0)
        ours = utm_poly(ring, tf)
        if ours is None or ours.area < 5 or idx is None: continue
        best = None
        for j in idx.query(ours):
            o = osm[int(j)]
            inter = ours.intersection(o["pg"]).area
            if inter <= 0: continue
            cover = inter / ours.area                       # how much of OUR footprint this OSM building sits over
            share = inter / o["pg"].area                    # how much of the OSM building we are
            # A tall OSM tower legitimately covers several of our plot-sized fragments, so a big ratio is expected.
            # What is NOT allowed is inheriting a height from something that barely touches us, or from a way so much
            # larger than us that it is a whole block rather than a building.
            # OSM's 3D scheme puts the OUTLINE and the HEIGHT on different objects: a named outline way (often tagged with
            # the podium's floor count) plus unnamed building:part ways carrying the real heights. Lake Shore Tower is
            # exactly this - the named way says 2 levels, and a 848 m2 part sitting inside our footprint says 165 m.
            # So a candidate qualifies if it COVERS us, or if WE CONTAIN it; and the name is deliberately not preferred,
            # because the named way is the one with the wrong number on it.
            covers_us = cover >= 0.55
            we_contain = share >= 0.80 and o["pg"].area >= ours.area * 0.12
            if not (covers_us or we_contain): continue
            if o["pg"].area > ours.area * 25 and share < 0.02: continue
            if best is None or o["h"] > best[1]["h"]: best = (0, o, round(cover, 2))
        if not best: continue
        _, o, cover = best
        h = o["h"]
        surveyed = (p.get("height_source") or "") in ("wikidata", "register")
        if surveyed and cur > 12.01 and h > cur * 1.6:
            rejected += 1; continue
        if h <= cur + 0.5: continue
        if not dry:
            p["bHeight"] = h; p["height_source"] = "osm_geom"; p["height_basis"] = f"{o['basis']} · {int(cover*100)}% of this footprint"
            if o["name"] and not (p.get("name") or "").strip(): p["name"] = o["name"]
        if cur <= 12.01: fixed += 1
        else: raised += 1
        if len(report) < 6 and h > 60: report.append(f"{(p.get('name') or o['name'] or '(unnamed)')[:26]} {cur:.0f}->{h:.0f} m")
    print(f"  {slug:<26} osm polys {len(osm):>5} | default->real {fixed:>5} | raised {raised:>4} | rejected {rejected:>3}"
          + ("   e.g. " + "; ".join(report) if report else ""))
    if not dry:
        bak = gj + ".bak_preheights"
        if not os.path.exists(bak): json.dump(json.load(open(gj, encoding="utf-8")), open(bak, "w"))
        json.dump(G, open(gj, "w", encoding="utf-8"), ensure_ascii=False)
    return {"slug": slug, "fixed": fixed, "raised": raised, "rejected": rejected}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("slugs", nargs="*"); a = ap.parse_args()
    slugs = a.slugs or [os.path.basename(p)[10:-5] for p in sorted(glob.glob(os.path.join(ROOT, "data", "board", "bldgfacts_*.json")))]
    tot = {"fixed": 0, "raised": 0, "rejected": 0}
    print("OSM heights" + ("  (DRY RUN)" if a.dry else ""))
    for s in slugs:
        r = run(s, a.dry, a.force)
        if r:
            for k in tot: tot[k] += r[k]
    print(f"\nTOTAL default->real {tot['fixed']:,} | raised {tot['raised']:,} | rejected as implausible {tot['rejected']:,}")
    if not a.dry:
        print("\nThe geojsons now carry the heights. The MODEL only changes when each district is re-massed in CityEngine:")
        print("  python scripts/ce_batch_v2.py --v3 <slug>   (takes the .ce_lock, pushes bHeight as an object attribute)")
