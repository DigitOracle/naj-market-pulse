"""Bind every NAMED building in the Dubai Land Department register (units + buildings tables, dld_units_buildings.py) to a footprint.

The transactions pass (bind_dld_buildings.py) only saw buildings with >= 3 unit sales since 2019. The register itself lists every
registered building with a project name (Ciel, Al Habtoor Tower, older stock that rarely trades). Same two stages, same gate:
  1. name match   against names already on the footprints (anchors + transaction bindings), normalised and stemmed
  2. geocode      Places text search "<name>, <area>, Dubai" (cached), nearest footprint >= MIN_H within NEAR_M, and the place must be
                  the building (<= 8 m or a shared significant token)
Output data/identity/official/dld/reg_bindings.json  {"<slug>": {"<i>": {property_id, name, project, master, units, flats, offices, shops,
       floors, parcel, land, method, dist_m, place_id, place_name}}, "_unbound": {...}}
The resolver reads it as source "dld"; build_unit_mix.py looks the footprint's property_id up directly (no name round-trip).
Usage: python scripts/bind_register_buildings.py [--no-geocode] [--limit N] [slug ...]
"""
import json, os, sys, time, collections
from shapely.geometry import shape, Point
from shapely.ops import transform
from shapely.strtree import STRtree
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token  # noqa: E402
from geocode_projects import places_text, BUILDINGISH, NOT_BUILDING  # noqa: E402
from bind_dld_buildings import norm, nkey, same_building, AREA_LABEL, TO_UTM, NEAR_M, MIN_H, CE, NAMES, DLD, OUTD, CACHE  # noqa: E402
OUT = os.path.join(OUTD, "reg_bindings.json"); TX = os.path.join(OUTD, "tx_bindings.json")


def main():
    geocode = "--no-geocode" not in sys.argv; lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    want = [a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
    slugs = want or [s[16:-5] for s in sorted(os.listdir(DLD)) if s.startswith("units_buildings_") and s.endswith(".json")]
    key = env_token("GOOGLE_KEY")
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    tx = json.load(open(TX, encoding="utf-8")) if os.path.exists(TX) else {}
    prev = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    out = {k: v for k, v in prev.items() if not k.startswith("_")}; unbound = {}
    ngeo = 0; tot = collections.Counter()
    for slug in slugs:
        U = json.load(open(os.path.join(DLD, f"units_buildings_{slug}.json"), encoding="utf-8"))["buildings"]
        F = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
        anchors = json.load(open(os.path.join(NAMES, f"anchors_{slug}.json"), encoding="utf-8")).get("anchors", []) if os.path.exists(os.path.join(NAMES, f"anchors_{slug}.json")) else []
        byname = collections.defaultdict(set); bykey = collections.defaultdict(set)
        for a in anchors:
            for nm in (a.get("name"), a.get("dev_project")):
                if nm: byname[norm(nm)].add(a["i"]); bykey[nkey(nm)].add(a["i"])
        for k, v in (tx.get(slug) or {}).items():                     # the transactions bindings are footprint names too
            for nm in (v.get("building"), v.get("project")):
                if nm: byname[norm(nm)].add(int(k)); bykey[nkey(nm)].add(int(k))
        polys, idx, hts = [], [], []
        for i, f in enumerate(F):
            if float(f["properties"].get("bHeight") or 0) < MIN_H: continue
            polys.append(transform(TO_UTM, shape(f["geometry"]))); idx.append(i); hts.append(float(f["properties"].get("bHeight") or 0))
        tree = STRtree(polys) if polys else None
        bound = out.setdefault(slug, {}); taken = {int(k) for k in bound}
        s1 = s2 = s3 = miss = 0
        for b in sorted(U, key=lambda x: -x["units"]):
            name = b.get("name"); rec = None
            if not name or b["units"] < 3: continue
            k1, k2 = norm(name), nkey(name)
            cand = byname.get(k1) or (bykey.get(k2) if k2 and len(k2) >= 5 else None)
            if not cand and k2 and len(k2) >= 6:
                hits = {i for kk, ii in bykey.items() if kk and (k2 in kk or kk in k2) and min(len(kk), len(k2)) >= 6 for i in ii}
                cand = hits if len(hits) == 1 else None
            if cand and len(cand) == 1:
                i = next(iter(cand)); rec = {"method": "name match", "dist_m": 0.0}; s1 += 1
            elif geocode and tree is not None and ngeo < lim:
                q = f"{name}, {AREA_LABEL.get(slug, slug)}, Dubai"
                if q in cache: res = cache[q]
                else:
                    try: res = places_text(q, key); cache[q] = res; ngeo += 1; time.sleep(0.12)
                    except Exception as e: res = []; print("   search failed:", q[:50], str(e)[:50])
                for pl in res:
                    types = set(pl.get("types") or [])
                    if types & NOT_BUILDING and not (types & BUILDINGISH): continue
                    loc = pl.get("location") or {}; pt = Point(TO_UTM(loc.get("longitude", 0), loc.get("latitude", 0)))
                    j = tree.nearest(pt); d = polys[j].distance(pt)
                    pn = (pl.get("displayName") or {}).get("text") or ""
                    if d <= NEAR_M and (d <= 8.0 or same_building(name, pn)):
                        i = idx[j]; rec = {"method": "geocoded", "dist_m": round(d, 1), "place_id": pl.get("id"), "place_name": pn}; s2 += 1; break
            if not rec and geocode and tree is not None:
                # stage 3: structure match - the register's floor count picks the one plausible footprint near the geocoded point
                q = f"{name}, {AREA_LABEL.get(slug, slug)}, Dubai"; res = cache.get(q)
                if res is None and ngeo < lim:
                    try: res = places_text(q, key); cache[q] = res; ngeo += 1; time.sleep(0.12)
                    except Exception as e: res = []; print("   search failed:", q[:50], str(e)[:50])
                res = res or []
                fl = b.get("floors") or b.get("floors_max") or 0
                if res and fl >= 8:
                    loc = res[0].get("location") or {}; pt = Point(TO_UTM(loc.get("longitude", 0), loc.get("latitude", 0)))
                    exp = fl * 3.2; band = []
                    for j in tree.query(pt.buffer(90)):
                        d = polys[j].distance(pt)
                        if d > 90 or idx[j] in taken: continue
                        h = hts[j]
                        if abs(h - exp) / exp <= 0.25: band.append((d, j, h))
                    if len(band) == 1:
                        d, j, h = band[0]; i = idx[j]
                        rec = {"method": "structure match", "dist_m": round(d, 1), "place_id": res[0].get("id"), "place_name": (res[0].get("displayName") or {}).get("text") or "", "floors": fl, "footprint_h": round(h, 1)}; s3 += 1
            if not rec: miss += 1; unbound.setdefault(slug, []).append({"name": name, "units": b["units"], "property_id": b["property_id"], "parcel": b.get("parcel")}); continue
            slim = {k: b.get(k) for k in ("property_id", "name", "project", "master", "units", "flats", "offices", "shops", "floors", "parcel", "land", "bno", "levels", "floors_min", "floors_max")}
            if i in taken and bound.get(str(i), {}).get("property_id") != b["property_id"]:
                bound[str(i)].setdefault("also", []).append(slim); continue
            taken.add(i); bound[str(i)] = dict(slim, **rec)
        tot["name"] += s1; tot["geo"] += s2; tot["struct"] += s3; tot["miss"] += miss
        print(f"  {slug:<24} register buildings {len(U):>4} | name-matched {s1:>4} | geocoded {s2:>4} | structure {s3:>3} | unbound {miss:>4}", flush=True)
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(dict(out, _unbound=unbound, _updated=time.strftime("%Y-%m-%d %H:%M"), _source="DLD units + buildings exports 2026-09-04 via dld_units_buildings.py"), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nTOTAL name-matched {tot['name']} | geocoded {tot['geo']} | structure {tot['struct']} ({ngeo} new searches) | unbound {tot['miss']} -> {OUT}")


if __name__ == "__main__":
    main()
