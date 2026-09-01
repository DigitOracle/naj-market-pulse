"""Build mp_areas.json — Dubai community polygons joined to OUR register area names.

Source polygons: github.com/artinbahmani/dubai-transactions-map (MIT) — Dubai Municipality
community polygons already fuzzy-joined to DLD names, with aka fields. We add a curated
alias table for DLD's cross-vintage renames (JVC = Al Barsha South Fourth, etc.).
Unmapped stays unmapped — never guessed (the Ghaf Woods rule).

Reads: scratchpad clone (pass --src) + public/pulse.json (for our live area names)
Writes: public/mp_areas.json  → push with push_assets.py (served at /img/mp_areas)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")

# Our register name -> polygon-set name. Curated, high-confidence only.
ALIASES = {
    "jumeirah village circle": "al barsha south fourth",
    "jumeirah village triangle": "al barsha south fifth",
    "jumeirah lakes towers": "al thanyah fifth",
    "dubai production city": "me aisem first",
    "silicon oasis": "nadd hessa",
    "palm deira": "nakhlat deira",
    "palm jumeirah": "nakhlat jumeirah",
    "dubai marina": "marsa dubai",
    "dubai hills": "hadaeq sheikh mohammed bin rashid",
    "dubai hills estate": "hadaeq sheikh mohammed bin rashid",
    "international city ph 1": "al warsan first",
    "majan": "wadi al safa 3",
    "downtown dubai": "burj khalifa",
    "emirates hills first": "al thanyah third",
    "motor city": "al hebiah first",
    "damac hills": "al hebiah third",
    "town square": "al yelayiss 2",
    "arabian ranches iii": "wadi al safa 5",
    "the valley": "al yufrah 1",
    "international city ph 1": "warsan first",
    "al khairan first": "al kheeran first",
    "sama al jadaf": "al jadaf",
    "sobha heartland": "al merkadh",
    "meydan one": "nadd al shiba first",
}

nz = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower())).strip()


def simplify_ring(ring, tol=0.00005):
    """Douglas-Peucker via shapely if available, else naive decimation."""
    try:
        from shapely.geometry import LineString
        if len(ring) < 8:
            return ring
        simp = list(LineString(ring).simplify(tol, preserve_topology=False).coords)
        return simp if len(simp) >= 4 else ring
    except ImportError:
        return ring[::2] if len(ring) > 40 else ring


def main():
    src = sys.argv[sys.argv.index("--src") + 1] if "--src" in sys.argv else None
    if not src or not os.path.exists(src):
        sys.exit("pass --src <path to dubai-transactions-map/data/areas.geojson>")
    geo = json.load(open(src, encoding="utf-8"))
    pulse = json.load(open(os.path.join(PUB, "pulse.json"), encoding="utf-8"))
    ours = [a["area"] for a in pulse.get("areaIntel", {}).get("areas", [])]

    idx = {}
    for ft in geo["features"]:
        p = ft["properties"]
        for k in ("area_en", "name", "aka", "community_en"):
            if p.get(k):
                idx.setdefault(nz(p[k]), ft)

    out, mapped, missed = [], [], []
    seen_ft = set()
    for o in ours:
        k = nz(o)
        ft = idx.get(k) or idx.get(ALIASES.get(k, ""))
        if not ft:
            missed.append(o)
            continue
        fid = id(ft)
        if fid in seen_ft:                       # two register names, one polygon — first wins
            continue
        seen_ft.add(fid)
        g = ft["geometry"]

        def depth(c):
            d = 0
            while isinstance(c, (list, tuple)) and c:
                c = c[0]; d += 1
            return d

        def ring_clean(r):
            return [[round(p[0], 5), round(p[1], 5)] for p in simplify_ring([(p[0], p[1]) for p in r])]

        dd = depth(g["coordinates"])
        if dd == 3:      # Polygon: [rings][points][xy]
            gg = {"type": "Polygon", "coordinates": [ring_clean(r) for r in g["coordinates"]]}
        elif dd == 4:    # MultiPolygon
            gg = {"type": "MultiPolygon", "coordinates": [[ring_clean(r) for r in poly] for poly in g["coordinates"]]}
        else:
            missed.append(o + " (bad geometry)")
            continue
        out.append({"type": "Feature", "properties": {"n": o}, "geometry": gg})
        mapped.append(o)

    doc = {"type": "FeatureCollection", "features": out}
    path = os.path.join(PUB, "mp_areas.json")
    json.dump(doc, open(path, "w"), separators=(",", ":"))
    kb = os.path.getsize(path) // 1024
    print(f"mp_areas.json: {len(out)} polygons, {kb} KB")
    print(f"mapped {len(mapped)}/{len(ours)} register areas; unmapped ({len(missed)}): {missed}")
    if kb > 900:
        print("WARNING: consider raising simplify tolerance")


if __name__ == "__main__":
    main()
