"""film_clusters.py -- DigitAlchemy(R) / Digital Abbot
Building clusters for district film endings (Kendall, 15 Sep: keep the first 20 seconds of the district film, then spend the last
10 moving into a cluster, so a buyer asking about Orchid B is flown into the cluster Orchid sits in).

Clusters are the land-register sub-communities (truth store sub_community, one centroid each) grouped by complete linkage so no
cluster is wider than MAX_D metres: small enough for one camera view at the end of the move. Each cluster is named by the members
people know best. Nearby places (supermarkets, malls from data/ce/<slug>/amenities_osm.json) ride along as labels.

Output: data/ce/<slug>/clusters.json
  {"clusters": [{"id", "name", "members": [{"sub_id", "name", "lat", "lon", "p": [x, y, z]}], "center": [x, y], "lat", "lon",
                 "radius_m", "buildings", "max_h_m", "places": [{"name", "kind", "p"}]}], "by_sub": {sub name: cluster id}}
Usage: python scripts/film_clusters.py <slug> [max_d_m=700]
"""
import json, math, os, sys
import duckdb
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb"); CE = os.path.join(ROOT, "data", "ce")
E0, N0 = 328289.0, 2784598.0
_TR = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
# names as agreed with Kendall on 15 Sep; any cluster not listed is named by its two largest members
NAMES = {"damachills": {frozenset({"Orchid", "Jasmine"}): "Golf Promenade & Orchid", frozenset({"Golf Horizon", "Golf Terrace"}): "Golf Horizon & Golf Terrace",
                        frozenset({"Carson", "Artesia"}): "Carson & Artesia", frozenset({"The Field", "The Flora"}): "The Field & The Flora",
                        frozenset({"Rochester", "Rockwood"}): "Rochester & Rockwood", frozenset({"Piccadilly Green", "Queens Meadow"}): "Piccadilly Green & Queens Meadow",
                        frozenset({"Silver Springs"}): "Silver Springs", frozenset({"Whitefield"}): "Whitefield", frozenset({"Pelham", "Trinity"}): "Pelham & Trinity"}}
PLACE_KINDS = {"supermarket": "Supermarket", "mall": "Mall"}


def to_ue(lon, lat):
    e, n = _TR.transform(lon, lat)
    return (e - E0) * 100.0, (-n + N0) * 100.0


def clean(name, slug):
    n = name
    for pre in ("DAMAC HILLS", "DAMAC HILLS-", "DAMAC HILLS -"):
        if n.upper().startswith(pre): n = n[len(pre):]
    n = n.strip(" -").title().replace("-1", " 1").replace("-2", " 2").replace("-3", " 3")
    return " ".join(n.split())


def main():
    args = [a for a in sys.argv[1:] if a]; kw = dict(a.split("=", 1) for a in args if "=" in a); slug = [a for a in args if "=" not in a][0]
    MAXD = float(kw.get("max_d_m", 700))
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute("select sub_id, name, lat, lon, radius_m, buildings, units from sub_community where district = ? and lat is not null", [slug]).fetchall()
    pts = [{"sub_id": r[0], "name": clean(r[1], slug), "lat": r[2], "lon": r[3], "radius_m": r[4] or 0, "buildings": r[5] or 0, "units": r[6] or 0} for r in rows]
    def dist(a, b): return math.hypot((a["lat"] - b["lat"]) * 111320, (a["lon"] - b["lon"]) * 100800)
    cl = [[p] for p in pts]
    while True:
        best = None
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                m = max(dist(a, b) for a in cl[i] for b in cl[j])
                if m <= MAXD and (best is None or m < best[0]): best = (m, i, j)
        if not best: break
        _, i, j = best; cl[i] += cl[j]; del cl[j]
    feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    fcent = []
    for f in feats:
        ring = f["geometry"]["coordinates"][0]; x = sum(p[0] for p in ring) / len(ring); y = sum(p[1] for p in ring) / len(ring)
        try: h = float(f["properties"].get("bHeight") or 0)
        except (TypeError, ValueError): h = 0.0
        fcent.append((x, y, h))
    places = []
    ap = os.path.join(CE, slug, "amenities_osm.json")
    if os.path.exists(ap):
        for e in json.load(open(ap, encoding="utf-8"))["elements"]:
            t = e.get("tags", {}); kind = t.get("shop")
            if kind not in PLACE_KINDS: continue
            c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
            n = t.get("name:en") or t.get("name") or ""
            if kind == "mall" and not n: n = "DAMAC Mall" if slug == "damachills" else ""
            if not n or "skate" in n.lower(): continue
            places.append({"name": n.strip().title() if n.islower() else n.strip(), "kind": kind, "lat": c["lat"], "lon": c["lon"]})
    out = []
    names = NAMES.get(slug, {})
    for g in sorted(cl, key=lambda g: (-sum(p["buildings"] for p in g))):
        lat = sum(p["lat"] for p in g) / len(g); lon = sum(p["lon"] for p in g) / len(g); cx, cy = to_ue(lon, lat)
        member_names = {p["name"] for p in g}
        nm = next((v for k, v in names.items() if k <= member_names), None)
        if nm is None:
            top = sorted(g, key=lambda p: (-p["units"], -p["buildings"]))[:2]; nm = " & ".join(p["name"] for p in top)
        rad = max(dist({"lat": lat, "lon": lon}, p) + (p["radius_m"] or 0) * 0.5 for p in g)
        hmax = max([h for x, y, h in fcent if math.hypot((y - lat) * 111320, (x - lon) * 100800) <= rad] or [12.0])
        members = []
        for p in sorted(g, key=lambda p: p["name"]):
            x, y = to_ue(p["lon"], p["lat"])
            members.append({"sub_id": p["sub_id"], "name": p["name"], "lat": p["lat"], "lon": p["lon"], "buildings": p["buildings"], "p": [round(x, 1), round(y, 1), 4000.0 if hmax > 20 else 1500.0]})
        near = []
        for pl in places:
            dm = math.hypot((pl["lat"] - lat) * 111320, (pl["lon"] - lon) * 100800)
            if dm <= rad + 900:
                x, y = to_ue(pl["lon"], pl["lat"]); near.append({"name": pl["name"], "kind": pl["kind"], "p": [round(x, 1), round(y, 1), 1200.0], "distance_m": round(dm)})
        out.append({"id": len(out) + 1, "name": nm, "members": members, "center": [round(cx, 1), round(cy, 1)], "lat": round(lat, 6), "lon": round(lon, 6),
                    "radius_m": round(rad), "buildings": sum(p["buildings"] for p in g), "max_h_m": round(hmax, 1), "places": near})
    by_sub = {m["name"]: c["id"] for c in out for m in c["members"]}
    json.dump({"slug": slug, "max_d_m": MAXD, "clusters": out, "by_sub": by_sub}, open(os.path.join(CE, slug, "clusters.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for c in out:
        print(f"{c['id']}. {c['name']}: {len(c['members'])} sub-communities, {c['buildings']} buildings, radius {c['radius_m']} m, tallest {c['max_h_m']} m, places {[p['name'] for p in c['places']]}")


if __name__ == "__main__":
    main()
