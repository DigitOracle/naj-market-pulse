"""build_unit_stack.py -- DigitAlchemy(R) / Digital Abbot
Lay the register's unit mix onto a building as stacked, per-floor volumes so the app can colour every home by bedroom count
(Kendall, 11 Sep 2026: the Imtiaz Universe pattern, proved on DAMAC HILLS - ORCHID A and B first because Naj lives there).

What is FACT and comes from the register (data/dld/units_buildings_<district>.json): the building, its storeys, how many homes of each
type, each type's median size, and the floor RANGE that type occupies.
What is INDICATIVE and is derived here: which unit sits at which position on a floor. The register does not say. Units are dealt
round the floor plate in register order, largest type first, so the mix per floor is right even though a given window is not.

Output: data/units/<slug>_<duid>.json   footprint ring (local metres), per-floor unit boxes, legend, provenance.
Usage:  python scripts/build_unit_stack.py <slug> <name fragment>      e.g. damachills orchid
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "units"); os.makedirs(OUT, exist_ok=True)
# bedroom type -> (label, colour). The Imtiaz palette: warm sand, charcoal, sage, teal, then extras.
TYPES = [("Studio", "#D9A441"), ("1 B/R", "#E2B98A"), ("2 B/R", "#3C464F"), ("3 B/R", "#8FC7B9"),
         ("4 B/R", "#4FA8A0"), ("5 B/R", "#7A5A8A"), ("Penthouse", "#C5A56A"), ("Shop", "#8A7A5A"), ("Office", "#6A7A8A")]
COLOUR = dict(TYPES); ORDER = [t for t, _ in TYPES]


def local_ring(coords, lon0, lat0):
    m_lat = 111320.0; m_lon = 111320.0 * math.cos(math.radians(lat0))
    pts = [((lon - lon0) * m_lon, (lat - lat0) * m_lat) for lon, lat in coords]
    if pts[0] == pts[-1]: pts = pts[:-1]
    return [[round(x, 2), round(y, 2)] for x, y in pts]


def perimeter_slots(ring, n):
    """n unit positions dealt evenly round the footprint perimeter, each with a centre and an outward bearing."""
    segs = []
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
        L = math.hypot(x2 - x1, y2 - y1)
        if L > 0.1: segs.append((x1, y1, x2, y2, L))
    total = sum(s[4] for s in segs); step = total / n; out = []
    d = step / 2
    for x1, y1, x2, y2, L in segs:
        while d < L:
            t = d / L; cx, cy = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            out.append({"c": [round(cx, 2), round(cy, 2)], "u": [round(ux, 3), round(uy, 3)], "w": round(step, 2)})
            d += step
        d -= L
    return out[:n]


def main():
    slug, frag = sys.argv[1], sys.argv[2].lower()
    reg = json.load(open(os.path.join(ROOT, "data", "dld", f"units_buildings_{slug}.json"), encoding="utf-8"))
    geo = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))
    import duckdb
    con = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
    rows = con.execute("select duid, footprint_i, display_name, height_m, storeys, lon, lat from building where district=? and lower(display_name) like ? order by display_name", [slug, f"%{frag}%"]).fetchall()
    cands = [b for b in reg["buildings"] if frag in ((b.get("name") or "") + " " + (b.get("project") or "")).lower()]
    if not rows or not cands: print("no match"); return
    for k, (duid, fi, name, h, storeys, lon, lat) in enumerate(rows):
        b = cands[min(k, len(cands) - 1)]
        ring = local_ring(geo["features"][fi]["geometry"]["coordinates"][0], lon, lat)
        floors = int(b.get("levels") or b.get("floors") or storeys or 8)
        by = b.get("by_rooms") or {}
        # order the types largest-home-first so big homes take the corners, and keep register order inside a type
        kinds = sorted(by.items(), key=lambda kv: -(kv[1].get("median_sqm") or 0))
        total = sum(v["n"] for _, v in kinds)
        per_floor = max(1, round(total / max(1, floors - 1)))
        slots = perimeter_slots(ring, per_floor)
        floor_h = round((h or 28.8) / floors, 2)
        # deal: walk floors within each type's own register range
        pool = []
        for t, v in kinds:
            f0 = int(v.get("floors_min") or 1); f1 = int(v.get("floors_max") or floors)
            for i in range(v["n"]):
                fl = f0 + (i * max(1, (f1 - f0 + 1)) // max(1, v["n"]))
                pool.append({"type": t, "floor": min(max(fl, 1), floors), "sqm": v.get("median_sqm")})
        pool.sort(key=lambda u: (u["floor"], ORDER.index(u["type"]) if u["type"] in ORDER else 99))
        units = []; used = {}
        for u in pool:
            fl = u["floor"]; i = used.get(fl, 0)
            while i >= len(slots):                       # floor full: push up, the register's range allowing
                fl = fl + 1 if fl < floors else 1; i = used.get(fl, 0)
            s = slots[i]; used[fl] = i + 1
            units.append({"type": u["type"], "floor": fl, "sqm": u["sqm"], "c": s["c"], "u": s["u"], "w": s["w"],
                          "z": round((fl - 1) * floor_h, 2), "h": floor_h, "colour": COLOUR.get(u["type"], "#8A8A8A")})
        legend = [{"type": t, "n": v["n"], "sqm": v.get("median_sqm"), "colour": COLOUR.get(t, "#8A8A8A"),
                   "floors": [v.get("floors_min"), v.get("floors_max")]} for t, v in sorted(by.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else 99)]
        out = {"slug": slug, "duid": duid, "name": name, "register_name": b.get("name"), "project": b.get("project"),
               "lon": lon, "lat": lat, "height_m": h, "floors": floors, "floor_h": floor_h, "units_total": total,
               "ring": ring, "legend": legend, "units": units,
               "provenance": {"facts": "unit counts, median sizes and floor ranges from the DLD units register via units_buildings_" + slug + ".json; footprint and height from the truth store",
                              "indicative": "which unit sits at which position on a floor is not in any register; positions are dealt round the floor plate so the mix per floor is right",
                              "built": __import__("time").strftime("%Y-%m-%dT%H:%M:%S")}}
        p = os.path.join(OUT, f"{slug}_{duid}.json")
        json.dump(out, open(p, "w"), separators=(",", ":"))
        print(f"{name:28s} {total:4d} units over {floors} floors -> {os.path.basename(p)}  ({', '.join(str(l['n'])+' '+l['type'] for l in legend)})")


if __name__ == "__main__":
    main()
