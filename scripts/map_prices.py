"""The price-and-bedrooms layer behind the map's sliders (Kendall, 7 Sep: "a slider for price range, a slider for bedrooms...
across all of Dubai, here's everything").

One compact point per priced development: where it is, who built it, and the register median (or marked estimate) per bedroom
count, plus registered rent and live remaining stock where a developer sheet exists. Everything here already exists in the
unit-mix cards, the anchors and the search index - this only folds them into one small file the phone can hold.

Output data/board/map_prices.json  {"items": [{p, n, d, i, lon, lat, dev, st, u, b: {"0": aed, "1": aed, ...}, r: {...rent}, e: [beds estimated], left}]}
        -> KV `map_prices`.   Usage: python scripts/map_prices.py [--no-push]
"""
import glob, json, os, re, sys, time, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
BOARD = os.path.join(ROOT, "data", "board"); NAMES = os.path.join(ROOT, "data", "names"); CE = os.path.join(ROOT, "data", "ce")
BEDS = {"studio": 0, "1 bedroom": 1, "2 bedroom": 2, "3 bedroom": 3, "4 bedroom": 4, "5 bedroom": 5, "6 bedroom": 6, "7 bedroom": 7, "penthouse": 9}


def centroid(coords, acc=None):
    acc = acc if acc is not None else [0.0, 0.0, 0]
    if isinstance(coords[0], (int, float)): acc[0] += coords[0]; acc[1] += coords[1]; acc[2] += 1
    else:
        for c in coords: centroid(c, acc)
    return acc


def main():
    U = json.load(open(os.path.join(BOARD, "unitmix_projects_slim.json"), encoding="utf-8"))["projects"]
    SI = json.load(open(os.path.join(BOARD, "search_index.json"), encoding="utf-8"))["items"]
    dev_by_p = {i["p"]: i["dev"] for i in SI if i.get("t") == "development" and i.get("p") and i.get("dev")}
    REJ = {(r.get("district"), str(r.get("project") or "").strip().upper()) for r in (json.load(open(os.path.join(ROOT, "data", "names", "dev_bindings.json"), encoding="utf-8")).get("rejected_by_hand") or [])}   # hand-rejected name-only binds
    dev_by_name = {re.sub(r"[^a-z0-9]", "", (i.get("n") or "").lower()): (i["dev"], i.get("d")) for i in SI if i.get("t") == "development" and i.get("dev")}   # (developer, district) - a name-only match must agree on district (golden R4: JVC Masaar Residences is not Arada)
    anchors, foot = {}, {}
    items = []; est_n = 0
    REMP = os.path.join(BOARD, "remaining.json")
    REM = (json.load(open(REMP, encoding="utf-8")).get("projects") or {}) if os.path.exists(REMP) else {}
    CACHEP = os.path.join(ROOT, "data", "registers", "refine_cache.json")
    cache = json.load(open(CACHEP, encoding="utf-8")) if os.path.exists(CACHEP) else {}
    gkey = os.environ.get("GOOGLE_KEY"); paid = 0
    from geocoders import geocode_google
    DG = json.load(open(os.path.join(BOARD, "districts_geo.json"), encoding="utf-8"))["districts"]
    def district_of(lon, lat):
        for d in DG:
            b = d["bbox"]
            if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]: return d["slug"]
        return None
    BEDKEY = {"studio": 0, "1 b/r": 1, "2 b/r": 2, "3 b/r": 3, "4 b/r": 4, "5 b/r": 5, "6 b/r": 6, "7 b/r": 7}
    seen_rows = {}
    for key, v in U.items():
        rows = v.get("rows") or []
        beds, rent, est = {}, {}, []
        for r in rows:
            b = BEDS.get((r.get("type") or "").lower())
            if b is None: continue
            price = r.get("median_aed") or r.get("est_aed")
            if not price: continue
            if b not in beds or (r.get("median_aed") and not beds.get(b)): beds[b] = int(price)
            if r.get("est_aed") and not r.get("median_aed"): est.append(b)
            if r.get("median_rent"): rent[b] = int(r["median_rent"])
        rem = REM.get(key) or {}
        ask, left = {}, 0
        for tname, bt in (rem.get("by_type") or {}).items():
            b = BEDKEY.get(tname.lower())
            if b is None: continue
            if bt.get("ask_min"): ask[b] = int(bt["ask_min"])
            if bt.get("remaining"): left += int(bt["remaining"])
        if not beds and not ask: continue
        d, i = v.get("district"), v.get("i")
        lon = lat = None
        if d is None or i is None:
            # a launch with a sheet but no footprint yet: place it once by name (cached, never re-paid)
            ck = "project:" + (v.get("name") or key)
            if ck not in cache and gkey:
                try: cache[ck] = geocode_google(gkey, v.get("name") or key, ""); paid += 1
                except Exception: cache[ck] = None
            g = cache.get(ck)
            if not g: continue
            lon, lat = g["lon"], g["lat"]; d = district_of(lon, lat); i = -1
        if lon is None and d not in anchors:
            af = os.path.join(NAMES, f"anchors_{d}.json")
            anchors[d] = {a["i"]: a for a in (json.load(open(af, encoding="utf-8")).get("anchors", []) if os.path.exists(af) else [])}
        a = (anchors.get(d) or {}).get(i) or {}
        if lon is None: lon, lat = a.get("lon"), a.get("lat")
        if not (lon and lat) and d is not None and i is not None and i >= 0:
            if d not in foot:
                gj = os.path.join(CE, d, "buildings.geojson")
                foot[d] = json.load(open(gj, encoding="utf-8"))["features"] if os.path.exists(gj) else []
            F = foot[d]
            if 0 <= i < len(F):
                c = centroid(F[i]["geometry"]["coordinates"])
                if c[2]: lon, lat = c[0] / c[2], c[1] / c[2]
        if not (lon and lat): continue
        left = left or (sum(int(r["remaining"]) for r in rows if isinstance(r.get("remaining"), (int, float)) and r["remaining"] > 0) or None)
        it = {"p": key, "n": v.get("name"), "d": d, "i": i, "lon": round(lon, 6), "lat": round(lat, 6),
              "dev": None if (d, (v.get("name") or "").strip().upper()) in REJ else dev_by_p.get(key) or (lambda hit: hit[0] if hit and (not hit[1] or not d or hit[1] == d) else None)(dev_by_name.get(re.sub(r"[^a-z0-9]", "", (v.get("name") or "").lower()))),
              "st": v.get("status"), "u": sum(int(r.get("units") or 0) for r in rows) or None,
              "b": {str(k): beds[k] for k in sorted(beds)}}
        if rent: it["r"] = {str(k): rent[k] for k in sorted(rent)}
        if est: it["e"] = sorted(set(est)); est_n += 1
        if left: it["left"] = left
        tot = rem.get("totals") or {}
        if tot.get("launched"): it["la"] = int(tot["launched"]); it["so"] = int(tot.get("sold") or 0)
        if ask: it["ask"] = {str(k): ask[k] for k in sorted(ask)}; it["sheet"] = rem.get("sheet_date")
        if v.get("floors"): it["fl"] = v["floors"]
        dk = (it.get("d"), it.get("i"), it.get("n"))          # two unit-mix keys can describe the same footprint (Berkeley Square N/S): one row on the map, facts merged
        if dk in seen_rows:
            first = seen_rows[dk]
            if it.get("u") and first.get("u") and it["u"] != first["u"]: first["u"] = first["u"] + it["u"]
            elif it.get("u") and not first.get("u"): first["u"] = it["u"]
            for fld in ("b", "r", "ask"):
                for k2, v2 in (it.get(fld) or {}).items(): first.setdefault(fld, {}).setdefault(k2, v2)
            for fld in ("la", "so", "left"):
                if it.get(fld): first[fld] = (first.get(fld) or 0) + it[fld]
            if it.get("e"): first["e"] = sorted(set((first.get("e") or []) + it["e"]))
            if not first.get("dev") and it.get("dev"): first["dev"] = it["dev"]
            continue
        seen_rows[dk] = it; items.append(it)
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "count": len(items),
           "note": "Register medians per bedroom count from the unit-mix cards (DLD settled sales; 'e' marks bedroom counts that are estimates, never mixed with asking); ask = lowest asking per bedroom on the developer sheet dated 'sheet'; rent = registered contracts; left = launched minus sold where a sheet exists; la/so = launched and sold in the register for sheet projects.",
           "items": items}
    json.dump(cache, open(CACHEP, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(doc, open(os.path.join(BOARD, "map_prices.json"), "w", encoding="utf-8"), ensure_ascii=False)
    size = os.path.getsize(os.path.join(BOARD, "map_prices.json"))
    print(f"priced developments {len(items):,} | with developer {sum(1 for i in items if i.get('dev')):,} | with rent {sum(1 for i in items if i.get('r')):,} | with live remaining {sum(1 for i in items if i.get('left')):,} | estimates {est_n:,} | {size//1024} KB")
    if "--no-push" not in sys.argv:
        for attempt in range(3):
            try: print("map_prices ->", push("map_prices", doc, env_token("INGEST_TOKEN")).get("ok")); break
            except Exception as e: print("  push retry", attempt + 1, str(e)[:60])


if __name__ == "__main__":
    main()
