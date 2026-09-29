"""Landmark signature crowns as UNIT meshes (plain CPython). Kendall 29 Sep 2026: buildings "should start to look a bit
more like the actual buildings". Research: data/ce/businessbay/landmarks/landmarks_v2.json (signature / massing.crown).

Each OBJ spans x,y in [-50, 50] cm (1 m square footprint) and z in [0, 100] cm (1 m tall), UE cm, Z up. The build
(ue_bb_v1_build.landmarks) scales it to the tower's roof bounds and the crown height from CROWNS below.

  fin_ring       JW Marriott Marquis: ring of 14 pointed sail fins flaring outwards + central mast
  corner_spires  Burj Binghatti: four faceted glass spires rising from the corners
  needle         Millennium Tower: thin needle spire
  lantern        SLS / Damac Maison / Manazel: open white frame (corner posts, top ring, mid ring)
  cage           One by Binghatti: bronze box cage (posts every 1/4 + top and mid rings)
Out: data/ce/_datasmith/bb_v1/crown_<name>.obj
"""
import math, os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "ce", "_datasmith", "bb_v1")

# id -> (crown mesh, crown height m, material key, true height m or None)
CROWNS = {
    3: ("fin_ring", 25.0, "cream", 355.0), 4: ("fin_ring", 25.0, "cream", 355.0), 5: ("fin_ring", 25.0, "cream", 355.0),
    573: ("corner_spires", 90.0, "crown_glass", None),
    1: ("needle", 30.0, "steel", None),
    84: ("lantern", 15.0, "white", 336.0),
    591: ("cage", 20.0, "bronze", None),
    142: ("lantern", 12.0, "white", None),
    170: ("lantern", 10.0, "white", None), 65: ("lantern", 10.0, "white", None), 178: ("lantern", 10.0, "white", None),
}
HEIGHT_FIX = {105: 260.0, 44: 93.0}
# Kendall 29 Sep 2026: under-construction towers shown AS CONSTRUCTION (research: renders only, none complete).
# id -> (true height m, share built): bare concrete frame, no crown, a tower crane on the top slab. Shares are estimates.
CONSTRUCTION = {573: (595.0, 0.58), 603: (376.0, 0.55), 591: (228.0, 0.85), 654: (450.0, 0.70)}          # Vision Tower, The Opus (research; geojson 195 / 73 m)


class M:
    def __init__(self):
        self.V, self.F = [], []

    def box(self, x0, y0, z0, x1, y1, z1):
        b = len(self.V)
        for z in (z0, z1):
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                self.V.append((x, y, z))
        q = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        for a, c, d, e in q:
            self.F += [(b + a, b + c, b + d), (b + a, b + d, b + e)]

    def tri_prism(self, base, apex):
        """pyramid from a polygon base (list of xyz) to an apex"""
        b = len(self.V); self.V += base + [apex]; n = len(base)
        for k in range(n):
            self.F.append((b + k, b + (k + 1) % n, b + n))
        for k in range(1, n - 1):
            self.F.append((b, b + k + 1, b + k))

    def write(self, name):
        p = os.path.join(OUT, "crown_%s.obj" % name)
        with open(p, "w", encoding="utf-8") as f:
            f.write("o crown_%s\n" % name)
            for v in self.V:
                f.write("v %.2f %.2f %.2f\n" % v)
            for t in self.F:
                f.write("f %d %d %d\n" % (t[0] + 1, t[1] + 1, t[2] + 1))
        return p


def fin_ring():
    m = M(); n = 14
    for k in range(n):
        a = 2 * math.pi * k / n; c, s = math.cos(a), math.sin(a)
        t = (-s, c)
        r0, r1, w = 40.0, 58.0, 5.0                      # fins lean outwards (flare) to a point
        base = [(c * r0 + t[0] * w, s * r0 + t[1] * w, 0.0), (c * r0 - t[0] * w, s * r0 - t[1] * w, 0.0),
                (c * (r0 - 4), s * (r0 - 4), 0.0)]
        m.tri_prism(base, (c * r1, s * r1, 100.0))
    m.box(-3, -3, 0, 3, 3, 140)                          # central mast
    m.box(-44, -44, 0, 44, 44, 12)                       # crown drum
    return m


def corner_spires():
    m = M()
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * 38.0, sy * 38.0
            base = [(cx - 12, cy - 12, 0.0), (cx + 12, cy - 12, 0.0), (cx + 12, cy + 12, 0.0), (cx - 12, cy + 12, 0.0)]
            m.tri_prism(base, (cx * 0.8, cy * 0.8, 100.0))           # faceted, leaning slightly inwards
    return m


def needle():
    m = M(); n = 12; base = [(4 * math.cos(2 * math.pi * k / n), 4 * math.sin(2 * math.pi * k / n), 0.0) for k in range(n)]
    m.tri_prism(base, (0.0, 0.0, 100.0)); m.box(-8, -8, 0, 8, 8, 10)
    return m


def lantern():
    m = M(); p = 4.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            m.box(sx * 50 - p, sy * 50 - p, 0, sx * 50 + p, sy * 50 + p, 100)
    for z0 in (45.0, 92.0):
        z1 = z0 + 8
        m.box(-50, -50, z0, 50, -50 + p * 2, z1); m.box(-50, 50 - p * 2, z0, 50, 50, z1)
        m.box(-50, -50, z0, -50 + p * 2, 50, z1); m.box(50 - p * 2, -50, z0, 50, 50, z1)
    return m


def cage():
    m = lantern(); p = 2.5
    for k in (-25.0, 0.0, 25.0):
        for s in (-1, 1):
            m.box(k - p, s * 50 - p, 0, k + p, s * 50 + p, 100); m.box(s * 50 - p, k - p, 0, s * 50 + p, k + p, 100)
    return m


def main():
    for nm, fn in (("fin_ring", fin_ring), ("corner_spires", corner_spires), ("needle", needle), ("lantern", lantern), ("cage", cage)):
        print(fn().write(nm))


if __name__ == "__main__":
    main()
