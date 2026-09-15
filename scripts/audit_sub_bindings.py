"""audit_sub_bindings.py -- does every sub-community card in the app resolve to buildings in the twin? (Kendall, 12 Sep 2026:
"when I click on the building, the twin does not show the individual building")

For every DLD sub-community card (data/board/subs.json or KV /img/subs: name, district, point, radius_m, buildings, units):
  resolved_now   = anchors in that district whose dev_project matches the card name (what the twin highlights today)
  by_radius      = footprints of the district geojson whose centroid lies within radius_m of the card point (what a geometry binding
                   would give), and how many of those are >= 12 m (real buildings, not sheds)
Writes data/audit/sub_bindings_audit.csv (one row per card) and data/audit/sub_bindings_audit.md (per-district summary).

    python scripts/audit_sub_bindings.py [slug ...]
"""
import csv, json, math, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); OUT = os.path.join(ROOT, "data", "audit"); os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
from build_avail_index import WORKER
H = {"User-Agent": "najma-market-pulse/1.0"}


def subs():
    p = os.path.join(ROOT, "data", "board", "subs.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
    else:
        d = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/img/subs", headers=H), timeout=120))
    feats = d["features"] if isinstance(d, dict) and "features" in d else d
    out = []
    for f in feats:
        pr = f.get("properties", f); g = f.get("geometry", {}); c = g.get("coordinates") or [pr.get("lon"), pr.get("lat")]
        if not c or c[0] is None: continue
        out.append({"name": pr.get("name"), "district": pr.get("district"), "lon": c[0], "lat": c[1], "radius_m": pr.get("radius_m") or 150, "buildings": pr.get("buildings") or 0, "units": pr.get("units") or 0, "plots": pr.get("plots") or 0})
    return out


def anchors(slug):
    p = os.path.join(NAMES, f"anchors_{slug}.json")
    if os.path.exists(p): d = json.load(open(p, encoding="utf-8"))
    else:
        try: d = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/img/anchors_" + slug, headers=H), timeout=120))
        except Exception: return []
    items = d if isinstance(d, list) else (d.get("items") or d.get("anchors") or [])
    return [a for a in items if isinstance(a, dict)]


def centroids(slug):
    p = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(p): return []
    g = json.load(open(p, encoding="utf-8")); out = []
    for i, f in enumerate(g["features"]):
        geom = f["geometry"]; rings = geom["coordinates"] if geom["type"] == "Polygon" else (geom["coordinates"][0] if geom["coordinates"] else [])
        if not rings: continue
        ring = rings[0]; xs = [q[0] for q in ring]; ys = [q[1] for q in ring]
        pr = f.get("properties", {}); h = pr.get("bHeight") or 0
        out.append((i, sum(xs) / len(xs), sum(ys) / len(ys), float(h or 0)))
    return out


def dist_m(lon1, lat1, lon2, lat2):
    return math.hypot((lon2 - lon1) * 100800.0, (lat2 - lat1) * 111320.0)


def norm(s): return " ".join(str(s or "").lower().replace("|", " ").split())


def main():
    only = set(sys.argv[1:])
    S = subs(); by_d = {}
    for s in S:
        if only and s["district"] not in only: continue
        by_d.setdefault(s["district"], []).append(s)
    rows = []; summary = []
    for slug in sorted(by_d):
        A = anchors(slug); C = centroids(slug)
        proj_names = {}
        for a in A:
            if a.get("dev_project"): proj_names.setdefault(norm(a["dev_project"]), []).append(a.get("i"))
        n_res = n_geo = 0
        for s in by_d[slug]:
            now = proj_names.get(norm(s["name"]), [])
            near = [(i, h) for i, lon, lat, h in C if dist_m(s["lon"], s["lat"], lon, lat) <= float(s["radius_m"])]
            tall = [i for i, h in near if h >= 12]
            resolved = bool(now); geo = bool(tall)
            n_res += resolved; n_geo += geo
            rows.append({"district": slug, "sub": s["name"], "units": s["units"], "buildings_card": s["buildings"], "plots": s["plots"], "radius_m": s["radius_m"],
                         "resolved_now": len(now), "footprints_in_radius": len(near), "buildings_in_radius": len(tall), "status": "ok" if resolved else ("fixable_by_geometry" if geo else "unresolved")})
        summary.append({"district": slug, "cards": len(by_d[slug]), "resolved_now": n_res, "fixable_by_geometry": n_geo - n_res if n_geo >= n_res else n_geo, "unresolved": len(by_d[slug]) - max(n_res, n_geo), "footprints": len(C), "anchors": len(A)})
        print(f"{slug:26s} cards {len(by_d[slug]):4d}  resolve now {n_res:4d}  by geometry {n_geo:4d}  footprints {len(C):5d}", flush=True)
    with open(os.path.join(OUT, "sub_bindings_audit.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    tot = {"cards": sum(x["cards"] for x in summary), "resolved_now": sum(x["resolved_now"] for x in summary), "geo": sum(min(x["cards"], x["resolved_now"] + x["fixable_by_geometry"]) for x in summary)}
    with open(os.path.join(OUT, "sub_bindings_audit.md"), "w", encoding="utf-8") as f:
        f.write(f"# Sub-community card -> twin building audit ({time.strftime('%d %b %Y %H:%M')})\n\nPrepared for Dr. Digital Abbot.\n\n")
        f.write(f"Cards: **{tot['cards']}** · resolve to a building today: **{tot['resolved_now']}** · would resolve with a geometry binding (footprints within the card radius, >= 12 m): **{tot['geo']}**\n\n")
        f.write("| District | Cards | Resolve now | Fixable by geometry | Unresolved | Footprints | Anchors |\n|---|---|---|---|---|---|---|\n")
        for x in sorted(summary, key=lambda x: -x["cards"]):
            f.write(f"| {x['district']} | {x['cards']} | {x['resolved_now']} | {x['fixable_by_geometry']} | {x['unresolved']} | {x['footprints']} | {x['anchors']} |\n")
        un = [r for r in rows if r["status"] == "unresolved"]; un.sort(key=lambda r: -(r["units"] or 0))
        f.write(f"\n## Unresolved cards by units (top 40 of {len(un)})\n\n| District | Card | Units | Buildings on card | Radius m | Footprints in radius |\n|---|---|---|---|---|---|\n")
        for r in un[:40]: f.write(f"| {r['district']} | {r['sub']} | {r['units']} | {r['buildings_card']} | {r['radius_m']} | {r['footprints_in_radius']} |\n")
    print(f"\nTOTAL cards {tot['cards']} · resolve now {tot['resolved_now']} · with geometry {tot['geo']} -> data/audit/sub_bindings_audit.{{csv,md}}")


if __name__ == "__main__":
    main()
