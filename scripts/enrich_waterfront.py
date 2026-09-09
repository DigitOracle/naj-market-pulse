"""Waterfront as knowledge-graph evidence: for every modelled building with an identity record, the nearest named body of water and
its distance, written as evidence records in the resolver's own schema so the graph can carry them.

    {duid, attribute: "waterfront", value: "Dubai Canal 139 m", body, cls, distance_m, source: "overture_water", source_record_id: <body id>,
     method: "nearest-segment", confidence, captured_at}

Input:  data/identity/identity_<slug>.json (by_index -> duid, lon, lat)   data/board/coast.json (bodies + segments, scripts/coastline.py)
Output: data/enrich/waterfront.json  {"generated", "source", "buildings": {duid: {...}}, "by_district": {slug: {"n", "on_water_300m", "bodies": {name: n}}}}
Confidence: 0.9 within 150 m of a named body, 0.7 to 500 m, 0.5 to 1500 m; nothing recorded beyond 1500 m (no waterfront claim).
Usage: python scripts/enrich_waterfront.py
"""
import glob, json, math, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
IDENT = os.path.join(ROOT, "data", "identity"); COAST = os.path.join(ROOT, "data", "board", "coast.json"); OUT = os.path.join(ROOT, "data", "enrich", "waterfront.json")


def seg_dist(pt, a, b):
    k = math.cos(pt[1] * math.pi / 180)
    px, py = pt[0] * k, pt[1]; ax, ay = a[0] * k, a[1]; bx, by = b[0] * k, b[1]
    dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) * 111320.0


def main():
    c = json.load(open(COAST, encoding="utf-8")); bodies = c["bodies"]; segs = c["segments"]
    # coarse grid over segments so 60k buildings x 11k segments stays quick
    grid = {}
    for s in segs:
        for gx in range(int(min(s[0], s[2]) * 100), int(max(s[0], s[2]) * 100) + 1):
            for gy in range(int(min(s[1], s[3]) * 100), int(max(s[1], s[3]) * 100) + 1): grid.setdefault((gx, gy), []).append(s)
    def nearest(pt):
        gx, gy = int(pt[0] * 100), int(pt[1] * 100); best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for s in grid.get((gx + dx, gy + dy), []):
                    d = seg_dist(pt, (s[0], s[1]), (s[2], s[3]))
                    if best is None or d < best[0]: best = (d, s)
        return best
    out = {}; byd = {}; now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for f in sorted(glob.glob(os.path.join(IDENT, "identity_*.json"))):
        j = json.load(open(f, encoding="utf-8")); slug = j.get("district"); n = 0; on = 0; names = {}
        for i, r in (j.get("by_index") or {}).items():
            if not (r.get("lon") and r.get("lat") and r.get("duid")): continue
            n += 1; b = nearest((r["lon"], r["lat"]))
            if not b or b[0] > 1500: continue
            body = bodies[b[1][5]]; d = round(b[0])
            conf = 0.9 if d <= 150 else (0.7 if d <= 500 else 0.5)
            label = (body["name"] if body["named"] else ("the sea" if body["cls"] == "sea" else body["cls"])) + " " + (f"{d} m" if d < 1000 else f"{d / 1000:.1f} km")
            out[r["duid"]] = {"duid": r["duid"], "attribute": "waterfront", "value": label, "body": body["name"], "cls": b[1][4], "distance_m": d, "source": "overture_water",
                              "source_record_id": body["id"], "method": "nearest-segment", "confidence": conf, "captured_at": now, "district": slug}
            if d <= 300: on += 1
            names[body["name"]] = names.get(body["name"], 0) + 1
        byd[slug] = {"buildings": n, "with_waterfront_1500m": sum(1 for v in out.values() if v["district"] == slug), "on_water_300m": on, "bodies": dict(sorted(names.items(), key=lambda x: -x[1])[:8])}
    doc = {"generated": now, "source": "scripts/coastline.py (Overture water = OpenStreetMap) x data/identity", "buildings": out, "by_district": byd}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    tot = sum(v["buildings"] for v in byd.values()); print(f"buildings {tot:,} · with a waterfront record {len(out):,} · on the water (<=300 m) {sum(v['on_water_300m'] for v in byd.values()):,}")
    for s, v in sorted(byd.items(), key=lambda x: -x[1]["on_water_300m"])[:12]: print(f"  {s:24s} {v['buildings']:6,} bldgs · on water {v['on_water_300m']:5,} · {', '.join(k + ' ' + str(n) for k, n in list(v['bodies'].items())[:3])}")
    print("->", OUT)


if __name__ == "__main__":
    main()
