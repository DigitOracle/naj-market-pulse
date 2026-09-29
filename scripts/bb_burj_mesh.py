"""Burj Khalifa hero mesh (plain CPython + shapely). Kendall 29 Sep 2026: "the Burj Khalifa should look like the Burj
Khalifa ... a very particular cover, colour and shape". Replaces the CityEngine box backdrop.

In:   data/ce/businessbay/landmarks/burj_khalifa_spec.json   (research agent, sources in burj_khalifa_spec.md)
Out:  data/ce/_datasmith/bb_v1/burj_{glass,band,spire}.obj     UE cm, Z up, local to the tower centre, Y = -north
      data/ce/_datasmith/bb_v1/burj_mesh.json                  tier table + bounds (validation)

Plan: each tier = union(centre circle, three tapered wings at bearings A/B/C) with fillets; a wing of length L is the
hull of a root circle (r = min(34, 0.62 L)) and a tip circle (r = min(15, 0.45 L)) at L - r_tip; troughs sit ~36 m
from the centre at the base (spec). Setbacks follow the spec schedule (27 tiers, counter-clockwise A -> B -> C).
Mechanical bands (spec heights) are cut out of the walls as their own mesh (darker material). Above the last occupied
tier (598.9 m) a shrinking tri-lobe then a stepped conical spire to 828 m.
"""
import json, math, os

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(REPO, "data", "ce", "businessbay", "landmarks", "burj_khalifa_spec.json")
OUT = os.path.join(REPO, "data", "ce", "_datasmith", "bb_v1")
RING_N = 180


def wing(bearing, L):
    b = math.radians(bearing)
    d = (math.sin(b), -math.cos(b))                       # UE: x = east, y = -north
    # near-parallel wing (~40 m wide at the root, ~30 m at the rounded tip): root circle 12 m out, tip circle at L - rt
    rt = min(15.0, 0.45 * L); r0 = min(20.0, 0.55 * L); c0 = min(12.0, 0.25 * L)
    tip = Point(d[0] * (L - rt), d[1] * (L - rt)).buffer(rt, 32)
    root = Point(d[0] * c0, d[1] * c0).buffer(r0, 32)
    return unary_union([root, tip]).convex_hull


def plan(bear, lengths):
    g = unary_union([wing(bear[k], lengths[k]) for k in ("A", "B", "C")] + [Point(0, 0).buffer(16.0, 6)])
    g = g.buffer(6.0, 16).buffer(-6.0, 16)
    return g if isinstance(g, Polygon) else max(g.geoms, key=lambda q: q.area)


def ring(poly, n=RING_N):
    ext = poly.exterior
    pts = [ext.interpolate(ext.length * k / n) for k in range(n)]
    xy = [(p.x, p.y) for p in pts]
    a = sum(xy[k][0] * xy[(k + 1) % n][1] - xy[(k + 1) % n][0] * xy[k][1] for k in range(n))
    return xy if a > 0 else xy[::-1]                      # counter-clockwise


class Mesh:
    def __init__(self):
        self.V, self.F = [], []

    def v(self, x, y, z):
        self.V.append((x * 100.0, y * 100.0, z * 100.0)); return len(self.V)

    def wall(self, xy, z0, z1):
        if z1 - z0 < 0.01:
            return
        n = len(xy); b = [self.v(x, y, z0) for x, y in xy]; t = [self.v(x, y, z1) for x, y in xy]
        for k in range(n):
            j = (k + 1) % n
            self.F.append((b[k], b[j], t[j])); self.F.append((b[k], t[j], t[k]))

    def cap(self, xy, z, up=True):
        c = self.v(sum(p[0] for p in xy) / len(xy), sum(p[1] for p in xy) / len(xy), z)
        idx = [self.v(x, y, z) for x, y in xy]
        for k in range(len(idx)):
            j = (k + 1) % len(idx)
            self.F.append((c, idx[k], idx[j]) if up else (c, idx[j], idx[k]))

    def write(self, path, name):
        with open(path, "w", encoding="utf-8") as f:
            f.write("o %s\n" % name)
            for p in self.V:
                f.write("v %.1f %.1f %.1f\n" % p)
            for t in self.F:
                f.write("f %d %d %d\n" % t)
        return {"verts": len(self.V), "tris": len(self.F)}


def main():
    S = json.load(open(SPEC, encoding="utf-8"))
    bear = S["plan"]["wings_true_bearing_deg"]
    tiers = [t for t in S["setbacks"]["schedule"] if "wing_length_after_m" in t]
    bands = []
    for h in S["mechanical_bands"]["heights_m"]:
        bands.append((h[0], h[1]) if isinstance(h, list) else (h - 2.3, h + 2.3))
    glass, band, spire = Mesh(), Mesh(), Mesh()
    z0, table = 0.0, []
    for t in tiers:
        z1 = float(t["top_height_m"])
        xy = ring(plan(bear, t["wing_length_after_m"]))
        cuts = sorted({z0, z1} | {c for a, b in bands for c in (a, b) if z0 < c < z1})
        for a, b in zip(cuts, cuts[1:]):
            mid = (a + b) / 2
            (band if any(p <= mid <= q for p, q in bands) else glass).wall(xy, a, b)
        glass.cap(xy, z1)
        table.append({"tier": t["tier"], "z0": round(z0, 1), "z1": z1, "wings": t["wing_length_after_m"]})
        z0 = z1
    # upper tri-lobe, shrinking, 598.9 -> 660 m (the clad lower spire reads as the core continuing)
    for k, (L, h) in enumerate(((15.0, 612.0), (12.5, 626.0), (10.5, 640.0), (8.5, 655.0))):
        xy = ring(plan(bear, {"A": L, "B": L, "C": L}), 96)
        glass.wall(xy, z0, h); glass.cap(xy, h); z0 = h
    # spire: stepped steel tube to 828 m, 9 m -> 1.2 m
    sp = S["spire"]; steps = 10
    top = float(S["heights"]["architectural_top_m"])
    for k in range(steps):
        a = z0 + (top - z0) * k / steps; b = z0 + (top - z0) * (k + 1) / steps
        r = (4.5 - (4.5 - float(sp["top_diameter_m"]) / 2) * (k / (steps - 1)) ** 0.8)
        xy = [(r * math.cos(2 * math.pi * i / 24), r * math.sin(2 * math.pi * i / 24)) for i in range(24)]
        spire.wall(xy, a, b); spire.cap(xy, b)
    out = {}
    for m, nm in ((glass, "glass"), (band, "band"), (spire, "spire")):
        out[nm] = m.write(os.path.join(OUT, "burj_%s.obj" % nm), "burj_" + nm)
    base = plan(bear, tiers[0]["wing_length_after_m"]); bx = base.bounds
    info = {"tiers": table, "meshes": out, "base_bbox_m": [round(bx[2] - bx[0], 1), round(bx[3] - bx[1], 1)],
            "top_m": top, "spec": SPEC}
    json.dump(info, open(os.path.join(OUT, "burj_mesh.json"), "w", encoding="utf-8"), indent=1)
    print("burj: base %.0f x %.0f m, %d tiers, %s" % (info["base_bbox_m"][0], info["base_bbox_m"][1], len(table), out))


if __name__ == "__main__":
    main()
