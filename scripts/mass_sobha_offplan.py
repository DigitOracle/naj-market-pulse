"""Register placeholders for Sobha's off-plan and under-built towers that the base map does not hold - v11 (24 Sep 2026).

Kendall: "fix the stub heights". The v10 audit's stubs were not short towers: they were the WRONG footprints. The radius route
had matched Solis to Motor City villas (87-188 m2, 180-260 m from Solis' own point), Orbis to villas and podiums, SkyParks to a
173 m2 building 2 km away. Raising those to tower heights would have drawn spikes on other people's houses. What is missing is
the towers themselves - off-plan, so OpenStreetMap never drew them - and the fix is the Hartland II / Hartland I method:
one mass per tower, sized from the best published figure, at the project's own site.

  floors    DM permit where the parcel has one (SkyParks 108 fl / 450 m, The Crest 47 fl / 171 m); otherwise Sobha's own
            page or listing sites, researched 24 Sep 2026 (data/identity/sobha_community_pages.md): Orbis 48/36/36/27/27/19/19,
            Solis 4 x 49, Sobha Central Pinnacle 95 fl ~360 m, SeaHaven A 66 / B 47 / C 57. Sobha Central's other towers
            are listed inconsistently (G+60 to G+90): those carry estimate=true and 60-76 floors.
  height    the published metres where stated, otherwise floors x 3.6 m (the Hartland permits run 3.6-3.7 m a floor).
  plate     unknown for off-plan towers: a square of 30 m + 0.1 m per floor, capped at 42 m - a tower's bulk, not a survey.
  position  the project's Google point (data/geocode_cache.json); towers on a grid of (side + 25 m) around it, each moved to
            the first free spot (20 m rings to 200 m) where it clears every existing footprint by 8 m. Footprints that are a
            construction SITE (<= 15 m tall and >= 5,000 m2 - Sobha Central's 15,139 m2 plot) are not obstacles: the towers
            stand inside them.
Every placeholder is appended (never inserted - bld3 payload ids are published by index), carries register_placeholder,
placeholder_set "sobha_offplan", project_number, floors_basis / height_basis / position_basis, and is CLAIMED for its
project in data/identity/sobha_footprint_claims.json, so build_sobha_mask.py reaches the project by the claim route and the
radius route's stray matches drop out. SeaHaven Tower A keeps its parcel footprint (504, named "Sobha Seahaven") with a
height override (scripts/height_overrides.json); B and C get placeholders beside it.
Usage: python scripts/mass_sobha_offplan.py [--dry]      then tile_shp / ce_import_tile / subset exports per changed district.
"""
import json, math, os, shutil, sys, datetime as dt

from pyproj import Transformer
from shapely.geometry import shape, box
from shapely.ops import transform
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mass_hartland2 import square

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CE = os.path.join(ROOT, "data", "ce")
CLAIMS = os.path.join(ROOT, "data", "identity", "sobha_footprint_claims.json")
OVERRIDES = os.path.join(ROOT, "scripts", "height_overrides.json")
TAG = "sobha_offplan"
M_PER_FLOOR = 3.6
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
to_ll = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True).transform
LISTINGS = "listing sites via research 24 Sep 2026 (propsearch.ae, Bayut; see data/identity/sobha_community_pages.md)"

# slug, project_number, name, Google point, [(tower label, floors, metres or None, estimate?)], floors source
PROJECTS = [
    ("motorcity", 3070, "Sobha Orbis", (55.2492832, 25.0482422),
     [("E", 48, None, False), ("A", 36, None, False), ("B", 36, None, False), ("D", 27, None, False), ("F", 27, None, False), ("C", 19, None, False), ("G", 19, None, False)], LISTINGS),
    ("motorcity", 3334, "Sobha Solis", (55.2445314, 25.0474042),
     [("A", 49, None, False), ("B", 49, None, False), ("C", 49, None, False), ("D", 49, None, False)], "sobharealty.com + propsearch.ae (49 storeys each)"),
    ("businessbay", 4137, "Sobha SkyParks", (55.274678, 25.1781685),
     [("", 108, 450.0, False)], "DM permit on parcel 3460107: 108 floors, 450 m"),
    ("jabalalifirst", 4328, "Sobha Central", (55.1331788, 25.0611482),
     [("The Pinnacle", 95, 360.0, False)], "sobharealty.com/sobha-communities/sobha-central: 95 floors, ~360 m"),
    ("jabalalifirst", 3713, "Sobha Central Phase I", (55.1331788, 25.0611482),
     [("The Horizon", 76, None, True), ("The Eden", 60, None, True)], LISTINGS + " - Horizon listed as 76 or G+60/G+90; Eden not found: ESTIMATES"),
    ("jabalalifirst", 4042, "Sobha Central Phase II", (55.1331788, 25.0611482),
     [("The Serene", 65, None, False), ("The Tranquil", 60, None, True)], LISTINGS + " - Serene 65; Tranquil not found: ESTIMATE"),
    ("dubaimarina", 2762, "Sobha Seahaven Tower B & C", (55.1441655, 25.0898909),
     [("Tower B", 47, None, False), ("Tower C", 57, None, False)], LISTINGS + " (SeaHaven A 66 / B 47 / C 57)"),
    ("sobhaheartland", 2447, "Sobha Hartland - The Crest", (55.3149544, 25.1775066),
     [("", 47, 171.0, False)], "DM permit on parcel 3470383: 47 floors, 171 m"),
]
HEIGHT_OVERRIDES = {"dubaimarina": {"504": {"height_m": round(66 * M_PER_FLOOR, 1), "why": "Sobha SeaHaven Tower A (the named 'Sobha Seahaven' parcel footprint, project 2550): 66 floors per listing sites (propsearch.ae, Bayut; researched 24 Sep 2026) x 3.6 m. Massed 24.0 m was the site under construction."}}}


def main():
    dry = "--dry" in sys.argv
    by_slug = {}
    for p in PROJECTS:
        by_slug.setdefault(p[0], []).append(p)
    claims = json.load(open(CLAIMS, encoding="utf-8")) if os.path.exists(CLAIMS) else {"districts": {}}
    report = []
    for slug, projs in by_slug.items():
        path = os.path.join(CE, slug, "buildings.geojson")
        fc = json.load(open(path, encoding="utf-8"))
        keep = [f for f in fc["features"] if (f.get("properties") or {}).get("placeholder_set") != TAG]
        if len(keep) != len(fc["features"]) and any((f.get("properties") or {}).get("placeholder_set") == TAG for f in fc["features"][:len(keep)]):
            sys.exit("%s: earlier %s placeholders are not all at the tail - refusing to rewrite (indices would shift)" % (slug, TAG))
        obst = []
        for f in keep:
            if not f.get("geometry"):
                continue
            g = transform(to_utm, shape(f["geometry"])).buffer(0)
            h = float((f.get("properties") or {}).get("bHeight") or 0)
            if h <= 15 and g.area >= 5000:
                continue                      # a construction site: towers stand inside it
            obst.append(g)
        tree = STRtree(obst); placed = []

        def free(sq):
            g = sq.buffer(8.0)
            return not any(obst[int(j)].intersects(g) for j in tree.query(g)) and not any(q.intersects(g) for q in placed)

        feats = []
        for _, pn, name, (lon0, lat0), towers, basis in projs:
            ex, ny = to_utm(lon0, lat0)
            n = len(towers); cols = math.ceil(math.sqrt(n))
            for k, (lbl, fl, hm, est) in enumerate(towers):
                side = min(42.0, 30.0 + 0.1 * fl)
                pitch = side + 25.0
                gx = (k % cols - (cols - 1) / 2.0) * pitch; gy = (k // cols - (math.ceil(n / cols) - 1) / 2.0) * pitch
                spot = None
                for r in [0.0] + [20.0 * i for i in range(1, 11)]:
                    for a in ([0] if r == 0 else range(0, 360, 20)):
                        cx = ex + gx + r * math.cos(math.radians(a)); cy = ny + gy + r * math.sin(math.radians(a))
                        sq = box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
                        if free(sq):
                            spot = (cx, cy, r, sq); break
                    if spot:
                        break
                if not spot:
                    report.append((slug, name, lbl, "no free spot - skipped")); continue
                cx, cy, r, sq = spot; placed.append(sq)
                h = hm or round(fl * M_PER_FLOOR, 1)
                lon, lat = to_ll(cx, cy)
                feats.append({"type": "Feature", "geometry": square(lon, lat, side), "properties": {
                    "status": "construction", "bHeight": h, "name": (name + (" - " + lbl if lbl else "")).strip(), "levels": str(fl),
                    "height_source": "dm_register" if "DM permit" in basis else ("estimate" if est else "published"),
                    "height_basis": "%d floors%s; %s" % (fl, "" if hm else " x %.1f m" % M_PER_FLOOR, basis), "estimate": bool(est),
                    "footprint_basis": "square %.0f m (plate unknown for an off-plan tower)" % side,
                    "position_source": "google" if r == 0 else "google grid+nudged %d m" % r, "position_basis": "%.6f,%.6f" % (lon0, lat0),
                    "register_placeholder": True, "placeholder_set": TAG, "project_number": pn, "developer": "sobha"}})
                report.append((slug, name, lbl, "%d fl, %.0f m%s, side %.0f m, %s" % (fl, h, " (ESTIMATE)" if est else "", side, "on the point" if r == 0 else "nudged %d m" % r)))
        base = len(keep)
        cl = claims["districts"].setdefault(slug, {})
        for k in [k for k, v in cl.items() if v.get("placeholder_set") == TAG]:
            del cl[k]
        for j, f in enumerate(feats):
            pr = f["properties"]
            cl[str(base + j)] = {"project_number": pr["project_number"], "name": pr["name"], "placeholder_set": TAG,
                                 "basis": "register placeholder: " + pr["height_basis"]}
        print("%s: %d kept, %d placeholders at %d..%d" % (slug, base, len(feats), base, base + len(feats) - 1))
        if not dry:
            bak = path + ".bak_preoffplan"
            if not os.path.exists(bak):
                shutil.copyfile(path, bak)
            fc["features"] = keep + feats
            json.dump(fc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    for r in report:
        print("  %-14s %-28s %-13s %s" % r)
    if dry:
        return
    json.dump(claims, open(CLAIMS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ov = json.load(open(OVERRIDES, encoding="utf-8"))
    for slug, d in HEIGHT_OVERRIDES.items():
        ov["districts"].setdefault(slug, {}).update(d)
    ov["generated"] = dt.date.today().isoformat()
    json.dump(ov, open(OVERRIDES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-> claims and height overrides written")


if __name__ == "__main__":
    main()
