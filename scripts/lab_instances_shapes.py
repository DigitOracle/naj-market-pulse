"""LAB #4 (instancing) step 1: the INITIAL SHAPES the instancing rule runs on - verge strips and plot-edge strips for one district.

Research only. Writes data/lab/instances/<slug>_shapes.json and nothing else; never touches a published file.

Every shape is a thin quad (1.6 m wide) in the district's LOCAL CE frame - the same frame as the v5 tiles:
    CE-frame metres (x = easting, y = up, z = -northing) = vertex + origin_ce_xyz     (data/ce/<slug>/origin_v5.json)
so an instance GLB built from these shapes drops onto the v5 district tile with the SAME float64 position.

  verge  one strip per straight run of each street side, centred (half carriageway + 1.8 m) off the OSM centreline.
         Carriageway half-width: lanes x 3.3 / 2 when OSM has lanes, else a per-class default. Streets only - no
         motorway / trunk (no verge planting modelled there), no service / footway / track.
  plot   one strip per footprint edge >= 10 m, 2.2 - 3.8 m outside the footprint (the plot-edge planting line).

Both are cut where they would stand in a carriageway (any highway class, buffered), inside or within 1.5 m of a
footprint, and plot strips also where they would double a verge strip. Pieces under 4 m are dropped.

VERTEX ORDER IS THE CONTRACT with rules/lab/instances/lab_instances.cga: every quad is counter-clockwise seen from
above (normal +Y, as PyPRT wants) and its FIRST edge is the reference side (the road for a verge, the building for a
plot strip). The rule aligns its scope to edge 0, so scope x runs along the strip and the reference side is known.

  python scripts/lab_instances_shapes.py alhebiahfifth [--near 150]
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
OUT = os.path.join(ROOT, "data", "lab", "instances")

HALF = {"primary": 11.0, "primary_link": 4.0, "secondary": 9.0, "secondary_link": 4.0, "tertiary": 7.0,
        "tertiary_link": 4.0, "residential": 4.5, "unclassified": 4.0, "living_street": 3.5}
PLANTED = set(HALF)                                        # classes that get verge strips
BLOCKING = PLANTED | {"motorway", "motorway_link", "trunk", "trunk_link", "service", "pedestrian", "track"}
BLOCK_HALF = {"motorway": 14.0, "motorway_link": 5.0, "trunk": 12.0, "trunk_link": 5.0, "service": 3.0,
              "pedestrian": 2.5, "track": 2.0}
VERGE_OFF = 1.8      # strip centre, metres beyond the carriageway edge
STRIP_W = 1.6
PLOT_OFF = 3.0       # plot strip centre, metres outside the footprint
MIN_PIECE = 4.0
NEAR = 150.0         # streets kept within this many metres of a modelled footprint (--near)


def half_width(tags):
    hw = tags.get("highway")
    try:
        lanes = float(str(tags.get("lanes", "")).split(";")[0])
    except ValueError:
        lanes = 0.0
    if lanes > 0:
        return max(3.0, lanes * 3.3 / 2.0)
    return HALF.get(hw) or BLOCK_HALF.get(hw, 3.0)


def quad(p0, p1, side_normal, near, far):
    """Quad whose edge 0 runs p0->p1 on the reference side (offset `near` along side_normal), far edge at `far`.
    Returned counter-clockwise in map (e, n) - normal +Y in the CE frame."""
    nx, ny = side_normal
    a = (p0[0] + nx * near, p0[1] + ny * near); b = (p1[0] + nx * near, p1[1] + ny * near)
    c = (p1[0] + nx * far, p1[1] + ny * far); d = (p0[0] + nx * far, p0[1] + ny * far)
    ring = [a, b, c, d]
    area = sum(ring[i][0] * ring[(i + 1) % 4][1] - ring[(i + 1) % 4][0] * ring[i][1] for i in range(4))
    return ring, area


def ce_verts(ring):
    """map (e, n) metres from the origin -> flat CE-frame vertex list (x = e, y = 0, z = -n)"""
    return [round(v, 3) for e, n in ring for v in (e, 0.0, -n)]


def pieces(line, blockers):
    from shapely.geometry import LineString, MultiLineString
    g = line.difference(blockers) if blockers is not None else line
    if g.is_empty:
        return []
    parts = list(g.geoms) if isinstance(g, MultiLineString) or hasattr(g, "geoms") else [g]
    out = []
    for p in parts:
        if not isinstance(p, LineString) or p.length < MIN_PIECE:
            continue
        s = p.simplify(0.5)
        cs = list(s.coords)
        for i in range(len(cs) - 1):
            if math.dist(cs[i], cs[i + 1]) >= MIN_PIECE:
                out.append((cs[i], cs[i + 1]))
    return out


def main():
    from pyproj import Transformer
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    slug = (sys.argv[1:] or ["alhebiahfifth"])[0]
    origin = json.load(open(os.path.join(CEDIR, slug, "origin_v5.json"), encoding="utf-8"))
    oe, on = origin["origin_utm_en"]
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    loc = lambda lon, lat: (lambda e, n: (e - oe, n - on))(*tf.transform(lon, lat))

    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    fps = []
    for fi, f in enumerate(feats):
        g = f["geometry"]
        rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
        for r in rings:
            poly = Polygon([loc(c[0], c[1]) for c in r])
            if poly.is_valid and poly.area > 4:
                fps.append((fi, poly))
    # the planted area: streets within NEAR metres of a modelled footprint (the whole bounding box of this district is
    # ~9 km2 and 176 km of verge - a city-block test needs the streets around the buildings, not every road in the box)
    near = float(sys.argv[sys.argv.index("--near") + 1]) if "--near" in sys.argv else NEAR
    clip = unary_union([p.buffer(near) for _, p in fps]).simplify(2.0)

    ways = json.load(open(os.path.join(CEDIR, slug, "highways_osm.json"), encoding="utf-8"))["elements"]
    roads = []
    for w in ways:
        tags = w.get("tags", {}); hw = tags.get("highway")
        if hw not in BLOCKING or len(w.get("geometry") or []) < 2:
            continue
        ln = LineString([loc(p["lon"], p["lat"]) for p in w["geometry"]])
        if not ln.intersects(clip):
            continue
        roads.append((w["id"], hw, half_width(tags), ln.intersection(clip), tags.get("oneway") == "yes"))
    carriage = unary_union([ln.buffer(h, cap_style=2) for _, _, h, ln, _ in roads])
    bld = unary_union([p.buffer(1.5) for _, p in fps])
    blockers = unary_union([carriage.buffer(0.3), bld])

    shapes, verge_lines = [], []
    for wid, hw, h, ln, oneway in roads:
        if hw not in PLANTED or ln.is_empty:
            continue
        lines = list(ln.geoms) if hasattr(ln, "geoms") else [ln]
        for part in lines:
            if part.length < MIN_PIECE:
                continue
            for side in (1, -1):              # 1 = left of the way's direction, -1 = right
                off = part.offset_curve(side * (h + VERGE_OFF), join_style=2, mitre_limit=2.0)
                if off.is_empty:
                    continue
                verge_lines.append(off)
                for a, b in pieces(off, blockers):
                    # reference (road) side must be on the RIGHT of edge 0 -> walk so that the road is to the right
                    dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy)
                    ux, uy = dx / L, dy / L
                    rn = (uy, -ux)                                          # right normal of a->b
                    # which side is the road? test the midpoint pushed 1 m to the right
                    m0 = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2); m1 = Point(m0.x + rn[0], m0.y + rn[1])
                    if part.distance(m1) > part.distance(m0):
                        a, b = b, a; ux, uy = -ux, -uy; rn = (uy, -ux)
                    ln_ = (-uy, ux)                                         # left normal = away from the road
                    ring, area = quad(a, b, ln_, -STRIP_W / 2, STRIP_W / 2)
                    if area <= 0:
                        ring = ring[::-1]
                    shapes.append({"kind": "verge", "roadClass": hw, "way": wid, "ring": ring})
    vbuf = unary_union([l.buffer(STRIP_W / 2 + 2.0, cap_style=2) for l in verge_lines]) if verge_lines else None

    blk = unary_union([carriage.buffer(0.3), bld] + ([vbuf] if vbuf is not None else []))    # once, not per footprint
    for fi, p in fps:
        ring = p.buffer(PLOT_OFF, join_style=2, mitre_limit=2.0).exterior
        cs = list(ring.coords)
        if Polygon(cs).exterior.is_ccw is False:
            cs = cs[::-1]
        for i in range(len(cs) - 1):
            e0, e1 = cs[i], cs[i + 1]
            if math.dist(e0, e1) < 10.0:
                continue
            for a, b in pieces(LineString([e0, e1]), blk):
                # CCW ring: building on the LEFT of travel. Reverse so the building is on the RIGHT of edge 0.
                a, b = b, a
                dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy); ux, uy = dx / L, dy / L
                ring4, area = quad(a, b, (-uy, ux), -STRIP_W / 2, STRIP_W / 2)
                if area <= 0:
                    ring4 = ring4[::-1]
                shapes.append({"kind": "plot", "roadClass": "plot", "building": fi, "ring": ring4})

    out = []
    for i, s in enumerate(shapes):
        r = s.pop("ring")
        a = sum(r[k][0] * r[(k + 1) % 4][1] - r[(k + 1) % 4][0] * r[k][1] for k in range(4)) / 2.0
        s.update({"id": i, "verts": ce_verts(r), "length_m": round(math.dist(r[0], r[1]), 2), "area_m2": round(a, 2)})
        out.append(s)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "%s_shapes.json" % slug)
    from collections import Counter
    summary = {"slug": slug, "origin_ce_xyz": origin["origin_ce_xyz"], "frame": origin["contract"],
               "counts": dict(Counter(s["kind"] for s in out)),
               "by_class": dict(Counter(s["roadClass"] for s in out)),
               "length_m": {k: round(sum(s["length_m"] for s in out if s["kind"] == k)) for k in ("verge", "plot")},
               "roads_used": len([r for r in roads if r[1] in PLANTED]), "footprints": len(fps), "near_m": near,
               "contract": "each quad CCW seen from +Y; edge 0 (verts[0:6]) is the reference side: road (verge) or building (plot)"}
    json.dump(dict(summary, shapes=out), open(path, "w", encoding="utf-8"))
    print(json.dumps(summary, indent=1))
    print("->", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
