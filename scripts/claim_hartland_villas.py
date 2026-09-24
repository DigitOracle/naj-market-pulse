"""Claim the Sobha Hartland (I) villas, Estates townhouses and Greens mid-rises the base map already holds - v12, 24 Sep 2026.

The audit's remaining Hartland gaps are finished, lived-in buildings: Villas Phase 1 (60 register plots), Villas Phase III (50),
Estates townhouses (27 villas), Hartland Greens I and II (2 buildings each). OpenStreetMap drew them years ago - 115 unassigned
villa-sized footprints stand within 300 m of the villa phases' own Google point - but no parcel key reaches them, because the
register's parcels have no geometry here. So they are claimed by shape and place, and the evidence is written with each claim:

  villas     unassigned footprints of 80-700 m2 and <= 15 m, not named for another building (geojson or DM binding), inside
             VILLA_M of the villa phases' Google point (55.30728, 25.17712 - distinct from the Hartland community centroid).
             Estates takes the 27 nearest its own point (55.30629, 25.17774) within 150 m; Villas Phase 1 then takes the 60
             nearest the villa point, Phase III the next 50. Which villa belongs to which phase is NOT known - the split is by
             distance, and says so; the set as a whole is Sobha's. Villas Phase II's only point is Hartland II's centroid: refused.
  greens     unassigned mid-rises (15-60 m, 300-5,000 m2), not named for another building, within GREENS_M of the Greens I/II point
             (55.30961, 25.17610); Phase I takes the 2 nearest, Phase II the next 2.
500 m out the ring reaches Azizi Riviera across the canal; 300 m does not. Claims go to data/identity/sobha_footprint_claims.json
(method "claim"), placeholder_set "hartland_villas". Nothing in any geojson changes.
Usage: python scripts/claim_hartland_villas.py [--dry]
"""
import json, os, sys

from pyproj import Transformer
from shapely.geometry import shape, Point
from shapely.ops import transform

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_sobha_mask import is_sobha_name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = "sobhaheartland"
CLAIMS = os.path.join(ROOT, "data", "identity", "sobha_footprint_claims.json")
TAG = "hartland_villas"
VILLA_PT = (55.3072833, 25.1771234); ESTATES_PT = (55.3062869, 25.177738); GREENS_PT = (55.3096055, 25.1760968)
VILLA_M, ESTATES_M, GREENS_M = 300.0, 150.0, 200.0
tu = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform


def main():
    dry = "--dry" in sys.argv
    fc = json.load(open(os.path.join(ROOT, "data", "ce", SLUG, "buildings.geojson"), encoding="utf-8"))["features"]
    stack = json.load(open(os.path.join(ROOT, "data", "board", "stack_%s.json" % SLUG), encoding="utf-8")).get("buildings_by_id") or {}
    mask = json.load(open(os.path.join(ROOT, "data", "board", "sobha_mask.json"), encoding="utf-8"))
    claims = json.load(open(CLAIMS, encoding="utf-8"))
    dc = claims["districts"].setdefault(SLUG, {})
    for k in [k for k, v in dc.items() if v.get("placeholder_set") == TAG]:
        del dc[k]
    taken = set((mask["districts"].get(SLUG) or {}).get("by_i") or {}) | set(dc)
    cand = []
    for i, f in enumerate(fc):
        if str(i) in taken or not f.get("geometry"):
            continue
        pr = f.get("properties") or {}
        if pr.get("register_placeholder"):
            continue
        nm = (pr.get("name") or "").strip() or ((stack.get(str(i)) or {}).get("name") or "").strip()
        if nm and not is_sobha_name(nm):
            continue
        g = transform(tu, shape(f["geometry"])).buffer(0)
        cand.append((i, g.centroid, g.area, float(pr.get("bHeight") or 0)))
    P = {k: Point(tu(*v)) for k, v in (("villa", VILLA_PT), ("estates", ESTATES_PT), ("greens", GREENS_PT))}
    villas = [c for c in cand if 80 <= c[2] <= 700 and c[3] <= 15 and c[1].distance(P["villa"]) <= VILLA_M]
    mids = [c for c in cand if 300 <= c[2] <= 5000 and 15 < c[3] <= 60 and c[1].distance(P["greens"]) <= GREENS_M]
    out, used = {}, set()

    def take(pool, pt, n, pn, name, basis, within=None):
        got = 0
        for c in sorted(pool, key=lambda c: c[1].distance(P[pt])):
            if got >= n:
                break
            if c[0] in used or (within and c[1].distance(P[pt]) > within):
                continue
            used.add(c[0]); got += 1
            out[str(c[0])] = {"project_number": pn, "name": name, "placeholder_set": TAG,
                              "basis": "%s; %.0f m2, %.0f m tall, %.0f m from the point" % (basis, c[2], c[3], c[1].distance(P[pt]))}
        return got

    n_est = take(villas, "estates", 27, 1837, "Sobha Hartland Estates - Townhouses", "villa-size footprint nearest the Estates Google point", ESTATES_M)
    n_v1 = take(villas, "villa", 60, 1544, "SOBHA HARTLAND VILLAS-PHASE 1", "villa-size footprint by the villa phases' Google point (phase split by distance, not known)")
    n_v3 = take(villas, "villa", 50, 2227, "Sobha Hartland Villas Phase III", "villa-size footprint by the villa phases' Google point (phase split by distance, not known)")
    n_g1 = take(mids, "greens", 2, 1581, "SOBHA HARTLAND GREENS- PHASE I", "mid-rise by the Greens I/II Google point")
    n_g2 = take(mids, "greens", 2, 1798, "SOBHA HARTLAND GREENS PHASE II", "mid-rise by the Greens I/II Google point")
    print("candidates: %d villa-size within %d m, %d mid-rise within %d m" % (len(villas), VILLA_M, len(mids), GREENS_M))
    print("claimed: Estates %d/27, Villas Phase 1 %d/60, Villas Phase III %d/50, Greens I %d/2, Greens II %d/2" % (n_est, n_v1, n_v3, n_g1, n_g2))
    if dry:
        return
    dc.update(out)
    json.dump(claims, open(CLAIMS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-> %d claims written" % len(out))


if __name__ == "__main__":
    main()
