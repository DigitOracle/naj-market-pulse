"""ue_storefronts.py -- DigitAlchemy(R) / Digital Abbot
Ground-floor shopfronts for the Unreal city, anchored to real retail (Kendall, 11 Sep: "there's storefronts. All of this you
need to think of"). A street reads as real when the ground floor is glazed, lit and signed; a shop invented in a villa street
reads as fake, so nothing is placed without a reason:

  real POI      an OSM shop / cafe / restaurant / pharmacy / bank / supermarket inside the district, matched to the footprint
                it sits in (or the nearest one within 40 m). Its name and kind drive the signboard.
  retail parade generic unnamed bays, glazed and lit but with a blank sign, only where the ground floor really is retail:
                a building tagged retail/commercial/supermarket/mall, or one standing inside a landuse=retail/commercial
                polygon and fronting a drivable road.
  kiosk         a POI with no footprint within 40 m becomes a 3 m x 3 m standalone unit facing the nearest road.

Per host building the street-facing edge is the one nearest a drivable OSM road (highways_osm.json, 'out geom'), longest edge
if no road within 80 m -- the same test scripts/ce_lod3_datasmith.py uses for villa porches. Bays are set out along that edge
at 6 m centres: glazing, mullions, a sign band, an awning on every other bay, a warm interior light 2 m inside the glass, and
pavement dressing (A-board, planter; tables, chairs and an umbrella for the eating and drinking kinds).

yaw is the along-edge heading chosen so the shop's local +Y points OUT of the building: the Unreal placer scales X along the
shopfront and Y through the wall without having to work out which way is outside. Pavement items are absolute positions.

Output: data/ce/<slug>/storefronts_ue.json
        {"bays":[[x,y,yaw,w,kind]], "mullions":[[x,y,yaw]], "signs":[[x,y,yaw,w,kind,text]], "awnings":[[x,y,yaw,w]],
         "interiors":[[x,y,kind]], "aboards":[[x,y,yaw]], "planters":[[x,y]], "tables":[[x,y]], "chairs":[[x,y,yaw]],
         "umbrellas":[[x,y]], "kiosks":[[x,y,yaw,kind,text]], "sources":{...}}
Cache:  data/names/osm_retail_<slug>.json   (one Overpass call per district, reused)
Usage:  python scripts/ue_storefronts.py <slug> [<slug> ...] | all [--force]
"""
import json, math, os, random, sys, time, urllib.error, urllib.parse, urllib.request

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); os.makedirs(NAMES, exist_ok=True)
E0 = 328289.0; N0 = 2784598.0                      # the fixed Unreal offset every Najma export uses
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
BAY_CM = 600.0; MIN_EDGE_CM = 750.0; MAX_BAYS_PER_BLD = 14; MAX_BAYS_PER_DISTRICT = 4200
EAT = ("cafe", "restaurant", "fast_food", "bar", "ice_cream", "bakery", "coffee")
AMENITY = ("cafe", "restaurant", "fast_food", "bar", "ice_cream", "pharmacy", "bank", "marketplace", "bureau_de_change")
RETAIL_BUILDING = ("retail", "commercial", "supermarket", "kiosk", "mall", "shop")
_TR = None


def to_ue(lon, lat):
    global _TR
    if _TR is None:
        from pyproj import Transformer
        _TR = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    e, n = _TR.transform(lon, lat)
    return (e - E0) * 100.0, (-n + N0) * 100.0


def overpass(q):
    body = urllib.parse.urlencode({"data": q}).encode()
    for i, m in enumerate(MIRRORS):
        try:
            with urllib.request.urlopen(urllib.request.Request(m, data=body, headers={"User-Agent": "DigitAlchemy-Najma/1.0"}), timeout=180) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            print(f"  overpass {m.split('/')[2]}: {str(e)[:70]} — next mirror"); time.sleep(6 + 4 * i)
    return {"elements": []}


def retail_osm(slug, bbox, force=False):
    """shops, eating places and retail/commercial land inside the district bbox; cached per district."""
    p = os.path.join(NAMES, f"osm_retail_{slug}.json")
    if os.path.exists(p) and not force: return json.load(open(p, encoding="utf-8"))
    s, w, n, e = bbox; bb = f"{s},{w},{n},{e}"
    am = "|".join(AMENITY); bl = "|".join(RETAIL_BUILDING)
    # 'out geom' not 'out tags center': the retail/commercial land has to be tested as a real polygon, a centre point says
    # nothing about whether a building 300 m away stands inside it (Damac, 12 Sep).
    q = ("[out:json][timeout:180];("
         f'node["shop"]({bb});way["shop"]({bb});'
         f'node["amenity"~"^({am})$"]({bb});way["amenity"~"^({am})$"]({bb});'
         f'node["tourism"~"^(hotel|hostel)$"]({bb});way["tourism"~"^(hotel|hostel)$"]({bb});'
         f'way["building"~"^({bl})$"]({bb});'
         f'way["landuse"~"^(retail|commercial)$"]({bb});'
         ");out geom;")
    d = overpass(q); d["fetched"] = time.strftime("%Y-%m-%dT%H:%M:%S"); d["bbox"] = bbox
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return d


def malls_in(bbox):
    """the placed rows of the DM mall register (data/registers/dm_malls.json) inside the district bbox"""
    p = os.path.join(ROOT, "data", "registers", "dm_malls.json")
    if not os.path.exists(p): return []
    s, w, n, e = bbox
    return [m for m in json.load(open(p, encoding="utf-8")).get("items", [])
            if m.get("lat") and m.get("lon") and s <= m["lat"] <= n and w <= m["lon"] <= e]


def ring_ue(geom):
    c = geom["coordinates"]
    ring = c[0] if geom["type"] == "Polygon" else c[0][0]
    pts = [to_ue(x, y) for x, y in ring]
    if len(pts) > 2 and pts[0] == pts[-1]: pts = pts[:-1]
    return pts


def inside(pt, ring):
    x, y = pt; n = len(ring); c = False
    for i in range(n):
        x1, y1 = ring[i]; x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1 + 1e-9): c = not c
    return c


class RoadGrid:
    """drivable OSM road segments in Unreal cm, in a 6,000 cm grid for nearest-segment queries"""
    CELL = 6000.0
    SKIP = {"footway", "path", "steps", "cycleway", "pedestrian", "track", "bridleway", "corridor", "construction", "proposed"}

    def __init__(self, path):
        self.g = {}; self.n = 0
        if not os.path.exists(path): return
        for el in json.load(open(path, encoding="utf-8")).get("elements", []):
            if el.get("type") != "way" or not el.get("geometry"): continue
            if (el.get("tags") or {}).get("highway") in self.SKIP: continue
            pts = [to_ue(g["lon"], g["lat"]) for g in el["geometry"]]
            for a, b in zip(pts, pts[1:]):
                self.n += 1
                for cx in range(int(min(a[0], b[0]) // self.CELL), int(max(a[0], b[0]) // self.CELL) + 1):
                    for cy in range(int(min(a[1], b[1]) // self.CELL), int(max(a[1], b[1]) // self.CELL) + 1):
                        self.g.setdefault((cx, cy), []).append((a, b))

    def nearest(self, px, py, rings=2):
        cx, cy = int(px // self.CELL), int(py // self.CELL); best = 1e18; seg = None
        for i in range(cx - rings, cx + rings + 1):
            for j in range(cy - rings, cy + rings + 1):
                for a, b in self.g.get((i, j), ()):
                    dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
                    t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L2)) if L2 else 0.0
                    d = math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))
                    if d < best: best, seg = d, (a, b)
        return best, seg


def street_edge(ring, roads):
    """(midpoint, along-edge yaw with local +Y outward, edge length cm) of the edge facing the street"""
    best = None
    for i in range(len(ring)):
        a = ring[i]; b = ring[(i + 1) % len(ring)]
        dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy)
        if L < MIN_EDGE_CM: continue
        ux, uy = dx / L, dy / L; mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        nx, ny = -uy, ux                                             # one of the two normals
        if inside((mx + nx * 150, my + ny * 150), ring): nx, ny = -nx, -ny   # keep the one pointing out of the footprint
        d, _ = roads.nearest(mx + nx * 400, my + ny * 400)
        score = d if d < 8000 else 1e6 - L                           # no road within 80 m: fall back to the longest edge
        if best is None or score < best[0]:
            ux2, uy2 = ny, -nx                                       # along-edge direction whose local +Y is the outward normal
            best = (score, (mx, my), math.degrees(math.atan2(uy2, ux2)), L, (nx, ny))
    return None if best is None else (best[1], best[2], best[3], best[4])


def dress(rnd, out, x, y, nx, ny, ux, uy, kind, i):
    """pavement in front of one bay: A-board or planter always, a table set for the eating and drinking kinds"""
    px, py = x + nx * 190, y + ny * 190
    if i % 2 == 0: out["aboards"].append([round(px, 1), round(py, 1), round(math.degrees(math.atan2(ny, nx)) + rnd.uniform(-25, 25), 1)])
    else: out["planters"].append([round(px + ux * 120, 1), round(py + uy * 120, 1)])
    if kind in EAT:
        tx, ty = x + nx * 300, y + ny * 300
        out["tables"].append([round(tx, 1), round(ty, 1)])
        for s in (-1, 1):
            out["chairs"].append([round(tx + ux * s * 85, 1), round(ty + uy * s * 85, 1), round(math.degrees(math.atan2(-uy * s, -ux * s)), 1)])
        if i % 3 == 0: out["umbrellas"].append([round(tx, 1), round(ty, 1)])


def build(slug, force=False):
    bdir = os.path.join(CE, slug); bp = os.path.join(bdir, "buildings.geojson")
    if not os.path.exists(bp): return "no buildings.geojson"
    outp = os.path.join(bdir, "storefronts_ue.json")
    if os.path.exists(outp) and not force: return "already built (--force to redo)"
    feats = json.load(open(bp, encoding="utf-8"))["features"]
    lons = []; lats = []
    for f in feats:
        c = f["geometry"]["coordinates"]; ring = c[0] if f["geometry"]["type"] == "Polygon" else c[0][0]
        for x, y in ring: lons.append(x); lats.append(y)
    if not lons: return "empty footprints"
    pad = 0.002
    bbox = (min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad)
    osm = retail_osm(slug, bbox, force=force)
    pois = []; land = []
    for el in osm.get("elements", []):
        t = el.get("tags") or {}
        g = el.get("geometry") or []
        if el.get("type") == "node" and el.get("lat") is not None: xy = to_ue(el["lon"], el["lat"])
        elif g: xy = (sum(to_ue(p["lon"], p["lat"])[0] for p in g) / len(g), sum(to_ue(p["lon"], p["lat"])[1] for p in g) / len(g))
        else: continue
        if t.get("landuse") in ("retail", "commercial"):
            if len(g) >= 4: land.append([to_ue(p["lon"], p["lat"]) for p in g])
            continue
        kind = t.get("shop") or t.get("amenity") or t.get("tourism") or t.get("building") or "shop"
        if t.get("building") in RETAIL_BUILDING and not (t.get("shop") or t.get("amenity")): kind = "retail"
        pois.append({"xy": xy, "kind": kind, "name": (t.get("name") or "").strip(), "id": f"{el['type']}/{el['id']}"})
    for m in malls_in(bbox):                                          # the DM mall register outranks OSM: placed, named, ours
        pois.append({"xy": to_ue(m["lon"], m["lat"]), "kind": "mall", "name": m.get("name") or m.get("dld_project") or "", "id": f"dm/{m['parcel_id']}"})
    roads = RoadGrid(os.path.join(bdir, "highways_osm.json"))
    rings = []
    for idx, f in enumerate(feats):
        r = ring_ue(f["geometry"])
        if len(r) < 3: rings.append(None); continue
        cx = sum(p[0] for p in r) / len(r); cy = sum(p[1] for p in r) / len(r)
        rings.append({"idx": idx, "ring": r, "c": (cx, cy), "h": float(f["properties"].get("bHeight") or 0)})
    live = [r for r in rings if r]
    # POI -> host footprint: inside it, else the nearest centroid within 40 m
    host = {}; kiosks = []
    cell = 6000.0; grid = {}
    for r in live: grid.setdefault((int(r["c"][0] // cell), int(r["c"][1] // cell)), []).append(r)
    for p in pois:
        px, py = p["xy"]; cx, cy = int(px // cell), int(py // cell); cands = []
        for i in range(cx - 1, cx + 2):
            for j in range(cy - 1, cy + 2): cands += grid.get((i, j), [])
        hit = next((r for r in cands if inside((px, py), r["ring"])), None)
        if hit is None and cands:
            near = min(cands, key=lambda r: math.hypot(r["c"][0] - px, r["c"][1] - py))
            if math.hypot(near["c"][0] - px, near["c"][1] - py) <= 4000: hit = near
        if hit is None: kiosks.append(p)
        else: host.setdefault(hit["idx"], []).append(p)
    # buildings that carry a retail ground floor with no POI of their own: inside retail/commercial land, fronting a road
    parade = set()
    for r in live:
        if r["idx"] in host or not land: continue
        if not any(inside(r["c"], ring) for ring in land): continue
        d, _ = roads.nearest(r["c"][0], r["c"][1])
        if d <= 6000: parade.add(r["idx"])
    out = {"slug": slug, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "bays": [], "mullions": [], "signs": [], "awnings": [], "interiors": [], "aboards": [], "planters": [],
           "tables": [], "chairs": [], "umbrellas": [], "kiosks": []}
    rnd = random.Random(slug)
    todo = sorted(set(host) | parade, key=lambda i: (-len(host.get(i, ())), i))
    n_named = 0
    for idx in todo:
        if len(out["bays"]) >= MAX_BAYS_PER_DISTRICT: break
        r = rings[idx]; se = street_edge(r["ring"], roads)
        if se is None: continue
        (mx, my), yaw, L, (nx, ny) = se
        ux, uy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        shops = host.get(idx, [])
        n = max(1, min(MAX_BAYS_PER_BLD, int((L - 100) // BAY_CM), (len(shops) + 2) if shops else 4))
        span = n * BAY_CM; start = -span / 2 + BAY_CM / 2
        for i in range(n):
            t = start + i * BAY_CM
            bx, by = mx + ux * t + nx * 12, my + uy * t + ny * 12          # 12 cm out of the wall plane: no z-fighting with the facade
            shop = shops[i] if i < len(shops) else None
            kind = shop["kind"] if shop else "retail"
            text = shop["name"] if shop and shop["name"] else ""
            if text: n_named += 1
            out["bays"].append([round(bx, 1), round(by, 1), round(yaw, 1), BAY_CM, kind])
            out["signs"].append([round(bx, 1), round(by, 1), round(yaw, 1), BAY_CM, kind, text])
            if i % 2 == 0: out["awnings"].append([round(bx, 1), round(by, 1), round(yaw, 1), BAY_CM])
            out["interiors"].append([round(bx - nx * 200, 1), round(by - ny * 200, 1), kind])
            out["mullions"].append([round(bx + ux * (BAY_CM / 2), 1), round(by + uy * (BAY_CM / 2), 1), round(yaw, 1)])
            dress(rnd, out, bx, by, nx, ny, ux, uy, kind, i)
        out["mullions"].append([round(mx + ux * (start - BAY_CM / 2) + nx * 12, 1), round(my + uy * (start - BAY_CM / 2) + ny * 12, 1), round(yaw, 1)])
    for p in kiosks[:300]:
        px, py = p["xy"]; d, seg = roads.nearest(px, py)
        if seg is None or d > 12000: continue
        (ax, ay), (bx, by) = seg; hd = math.degrees(math.atan2(by - ay, bx - ax))
        out["kiosks"].append([round(px, 1), round(py, 1), round(hd, 1), p["kind"], p["name"]])
    out["sources"] = {"pois": len(pois), "dm_malls": len(malls_in(bbox)), "osm_retail_land": len(land), "host_buildings": len(host), "parade_buildings": len(parade),
                      "road_segments": roads.n, "named_signs": n_named, "footprints": len(feats)}
    out["counts"] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
    c = out["counts"]
    return (f"{c['bays']} bays ({n_named} named) on {len(host)} POI buildings + {len(parade)} retail-land buildings, "
            f"{c['kiosks']} kiosks, {c['tables']} tables, {c['planters']} planters, {c['aboards']} A-boards")


def main():
    args = [a for a in sys.argv[1:] if a]; force = "--force" in args; args = [a for a in args if not a.startswith("--")]
    slugs = sorted(d for d in os.listdir(CE) if not d.startswith("_") and os.path.isdir(os.path.join(CE, d))
                   and os.path.exists(os.path.join(CE, d, "buildings.geojson"))) if (not args or args == ["all"]) else args
    print(f"storefronts for {len(slugs)} district(s)")
    for s in slugs:
        t0 = time.time()
        try: print(f"  {s}: {build(s, force)} [{round(time.time()-t0,1)} s]")
        except Exception as ex:
            import traceback; print(f"  {s}: FAILED {str(ex)[:150]}"); print(traceback.format_exc()[-400:])


if __name__ == "__main__":
    main()
