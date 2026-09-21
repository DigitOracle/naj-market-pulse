"""Three things a building can only know from geometry, merged into stack_<district>.json.

The DDA session cut community polygons, transit points and the Municipality's usage list on 21 Sep 2026. Each closes a gap
that string matching could not:

  community   Which community a building stands in, by point-in-polygon on its own anchor - not by matching the district's
              name. "Who lives here" is keyed on DEWA community, so a Business Bay tower by the canal (346) and one against
              the Burj (345) belong to different mixes, and the name match could not see that boundary at all. This is a
              correctness fix, not a new feature: some buildings have been shown the wrong community's residents.

  transit     The nearest metro, tram, marine and bus, measured straight-line from THIS building. What the page shows today
              is the Land Department's nearest-to field, which is its opinion about the project and carries no distance.
              Where a district has no rail at all, the nearest outside it is carried with its distance, because "no metro"
              and "metro 3.4 km away" are different answers.

  usage       Does the Municipality agree this building has the use the floor register fills it with? DM records uses per
              BUILDING, not per floor, so this answers existence, not placement. A building the floor register fills with
              offices whose DM list says villa is a binding to doubt - which is the question standing over the 25 buildings
              whose footprint is too short to hold their floors, where "podium" has been the assumed answer.

Nothing here decides anything. A disagreement is recorded as a disagreement.

  python scripts/build_geo_context.py businessbay damachills [--push]
  python scripts/build_geo_context.py --all --push
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
NAMES = os.path.join(ROOT, "data", "names")
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KINDS = ["metro station", "tram station", "marine station", "bus stop"]
LABEL = {"metro station": "Metro", "tram station": "Tram", "marine station": "Marine station", "bus stop": "Bus stop"}
MAX_M = 3000.0            # past this, a stop is not this building's stop; the district-level nearest is carried instead


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def communities():
    """The 223 DM community polygons, as (comm_num, name, ring, bbox). Outer rings only, which is how they were cut."""
    d = load(os.path.join(BOARD, "communities.geojson"))
    if not d:
        return []
    out = []
    for f in d.get("features") or []:
        g = f.get("geometry") or {}
        cs = g.get("coordinates") or []
        rings = [cs[0]] if g.get("type") == "Polygon" else [p[0] for p in cs if p]
        for ring in rings:
            if not ring or len(ring) < 4:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            out.append((f["properties"].get("comm_num"), f["properties"].get("name_en"), ring,
                        (min(xs), min(ys), max(xs), max(ys))))
    return out


def inside(ring, x, y):
    """Ray casting. A point on a shared edge may land either side; nothing downstream turns on a metre."""
    c = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            c = not c
        j = i
    return c


def community_of(polys, lon, lat):
    for num, name, ring, bb in polys:
        if bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3] and inside(ring, lon, lat):
            return {"num": num, "name": name}
    return None


def transit_for(tr, lat, lon):
    """The nearest of each kind to this building, straight-line. Beyond MAX_M we fall back to the district's own nearest,
    marked as such, so the page can say "the nearest is 3.4 km away, outside this district" rather than saying nothing."""
    if not tr:
        return None
    k = math.cos(math.radians(lat))
    out = []
    for kind in KINDS:
        best = None
        for p in (tr.get("inside") or {}).get(kind) or []:
            if p.get("lat") is None:
                continue
            d = math.hypot((p["lon"] - lon) * k, p["lat"] - lat) * 111320
            if best is None or d < best[0]:
                best = (d, p)
        if best and best[0] <= MAX_M:
            out.append({"kind": LABEL[kind], "name": best[1].get("name"), "m": round(best[0]),
                        "zone": best[1].get("detail")})
        else:
            far = (tr.get("nearest_anywhere") or {}).get(kind)
            if far and far.get("lat") is not None:
                d = math.hypot((far["lon"] - lon) * k, far["lat"] - lat) * 111320
                out.append({"kind": LABEL[kind], "name": far.get("name"), "m": round(d), "outside": True})
    return out or None


def usage_check(rows, floors):
    """Does the Municipality's usage list for this building contain what the floor register fills it with?"""
    if not rows:
        return None
    dm = sorted({str(r.get("usage") or "").strip() for r in rows if r.get("usage")})
    if not dm:
        return None
    low = " ".join(dm).lower()
    # The Municipality's own vocabulary, counted across all 37 cuts rather than guessed - including its spelling of
    # residential, which is "Resedential" on 11,622 rows. Matching "residential" marked half of Business Bay as a
    # disagreement on a typo, which is exactly the kind of false alarm this check must not raise.
    WANT = {"homes": ("resedential", "residential", "hotel apartment", "villa", "employees", "labour"),
            "villa": ("villa", "resedential", "residential"),
            "office": ("offices", "office", "commercial", "banks"),
            "retail": ("shopping center", "commercial", "petrol station", "indoor services"),
            "hotel": ("hotels", "hotel"),
            "civic": ("mosques", "education", "hospitals", "theatre", "cinema", "others")}
    ours = sorted({f.get("u") for f in floors if f.get("u") in WANT})
    missing = [u for u in ours if not any(w in low for w in WANT[u])]
    return {"dm": dm[:6], "register": ours, "missing": missing, "mixed": len(dm) > 1}


def build(district, tok):
    sp = os.path.join(BOARD, "stack_%s.json" % district)
    if not os.path.exists(sp):
        print("%s: no stack" % district)
        return False
    doc = json.load(open(sp, encoding="utf-8"))
    anchors = {str(a.get("i")): a for a in ((load(os.path.join(NAMES, "anchors_%s.json" % district)) or {}).get("anchors") or [])}
    polys = communities()
    tr = load(os.path.join(BOARD, "transit_%s.json" % district))
    us = (load(os.path.join(BOARD, "usages_%s.json" % district)) or {}).get("by_building") or {}
    nc = nt = nu = nd = 0
    seen = {}
    for i, rec in doc["buildings_by_id"].items():
        a = anchors.get(str(i)) or {}
        if a.get("lat") and polys:
            c = community_of(polys, a["lon"], a["lat"])
            if c:
                rec["community"] = c
                seen[c["name"]] = seen.get(c["name"], 0) + 1
                nc += 1
        if a.get("lat"):
            t = transit_for(tr, a["lat"], a["lon"])
            if t:
                rec["transit"] = t
                nt += 1
        u = usage_check(us.get(str(rec.get("dm") or "")), rec.get("floors") or [])
        if u:
            rec["usage"] = u
            nu += 1
            nd += 1 if u["missing"] else 0
    doc["generated"] = doc.get("generated")
    json.dump(doc, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    top = ", ".join("%s %d" % (k, v) for k, v in sorted(seen.items(), key=lambda kv: -kv[1])[:3])
    print("%-26s community %3d (%s) | transit %3d | usage %3d, %d disagree"
          % (district, nc, top or "none", nt, nu, nd))
    if tok:
        from build_avail_index import push
        print("   push stack_%s -> %s" % (district, push("stack_" + district, doc, tok).get("ok")))
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        args = sorted(f[6:-5] for f in os.listdir(BOARD) if f.startswith("stack_") and f.endswith(".json"))
    tok = None
    if "--push" in sys.argv:
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    for d in (args or ["businessbay", "damachills"]):
        build(d, tok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
