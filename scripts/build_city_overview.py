"""All-Dubai twin overview — Kendall, 9 Sep 2026 ("build the all Dubai view").

One compact file for the twin's city level: every modelled building as a box (centre, footprint size, height) in the twin's scene
metres (EPSG:32640 easting / -northing, relative to one origin), with district index, developer index, and flags (named, villa,
townhouse, tower). Plus the 41 district centroids and names, and the waterline segments from coast.json. The Worker serves it at
/img/city_overview and the twin draws it as a single instanced mesh (~64k boxes, one draw call).

Sources: data/ce/<slug>/buildings.geojson (footprint rings, feature order = footprint index), data/graph/najma.duckdb (height,
name, developer, villa kind), data/board/districts_geo.json (district names, corridor), data/board/coast.json (waterline).
Output:  data/board/city_overview.json  and KV city_overview (push).  Usage: python scripts/build_city_overview.py [--no-push]
"""
import base64, json, math, os, struct, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb, pyproj
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); BOARD = os.path.join(ROOT, "data", "board"); DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
ORIGIN_LL = (55.27, 25.12)           # scene origin: central Dubai; x = easting - e0, z = -(northing - n0)
UNIT = 2.0                           # metres per integer step for x/z (int16 covers +-65 km)
DEVS = ["", "omniyat", "hh", "meraas", "select", "ellington", "arada", "zaya", "palma", "fakhruddin", "beyond", "imtiaz", "iman", "emaar", "sobha", "prestigeone"]


def rings(geom):
    if geom.get("type") == "Polygon": return [geom["coordinates"][0]]
    if geom.get("type") == "MultiPolygon": return [p[0] for p in geom["coordinates"]]
    return []


def main():
    t0 = time.time(); e0, n0 = TO_UTM(*ORIGIN_LL)
    con = None
    for k in range(40):                                   # DuckDB is single-writer: wait while a build holds it
        try: con = duckdb.connect(DB, read_only=True); break
        except duckdb.IOException as e:
            if "being used by another process" not in str(e): raise
            print(f"  truth store busy - waiting 30 s ({k+1}/40)"); time.sleep(30)
    if con is None: raise SystemExit("truth store stayed locked")
    facts = {}
    for duid, d, i, h, nm, dev in con.execute("select duid, district, footprint_i, height_m, display_name, developer from building").fetchall():
        facts[(d, i)] = (h, nm, dev)
    kinds = {(d, i): k for d, i, k in con.execute("select district, footprint_i, kind from villa_label").fetchall()}
    dist_names = {d["slug"]: d for d in json.load(open(os.path.join(BOARD, "districts_geo.json"), encoding="utf-8"))["districts"]}
    slugs = sorted(s for s in os.listdir(CE) if os.path.exists(os.path.join(CE, s, "buildings.geojson")))
    xz = []; wd = []; hh = []; flags = []; dist = []; dev = []; districts = []
    for di, slug in enumerate(slugs):
        feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8")).get("features", [])
        sx = sz = 0.0; cnt = 0; named = 0; tallest = 0.0; tallest_name = None
        for idx, ft in enumerate(feats):
            pts = [TO_UTM(px, py) for ring in rings(ft.get("geometry") or {}) for px, py in ring]
            if len(pts) < 3: continue
            es = [p[0] for p in pts]; ns = [p[1] for p in pts]
            cx = (min(es) + max(es)) / 2 - e0; cz = -((min(ns) + max(ns)) / 2 - n0)
            w = max(2.0, min(255.0, max(es) - min(es))); d = max(2.0, min(255.0, max(ns) - min(ns)))
            h, nm, dv = facts.get((slug, idx), (None, None, None))
            if h is None:
                pr = ft.get("properties") or {}
                try: h = float(pr.get("bHeight") or 0) or float(pr.get("levels") or 3) * 3.2
                except (TypeError, ValueError): h = 9.6
            h = max(3.0, min(65535.0, float(h or 3.0)))
            k = kinds.get((slug, idx)); tower = h >= 60
            fl = (1 if nm else 0) | (2 if k == "villa" else 0) | (4 if k == "townhouse" else 0) | (8 if tower else 0)
            xz.append((int(round(cx / UNIT)), int(round(cz / UNIT)))); wd.append((int(round(w)), int(round(d)))); hh.append(int(round(h))); flags.append(fl); dist.append(di)
            dev.append(DEVS.index(dv) if dv in DEVS else 0)
            sx += cx; sz += cz; cnt += 1; named += 1 if nm else 0
            if h > tallest: tallest, tallest_name = h, nm
        dn = dist_names.get(slug, {})
        districts.append({"slug": slug, "name": dn.get("name") or slug, "corridor": dn.get("corridor") or "", "x": round(sx / max(cnt, 1)), "z": round(sz / max(cnt, 1)), "buildings": cnt, "named": named, "tallest_m": round(tallest), "tallest": tallest_name})
        print(f"  {slug:26s} {cnt:6,d} buildings · named {named:5,d} · tallest {round(tallest):4d} m {tallest_name or ''}")
    # waterline: coast.json segments (lon1,lat1,lon2,lat2,cls,body) -> scene int16 pairs, class code
    coast = json.load(open(os.path.join(BOARD, "coast.json"), encoding="utf-8")); cls_ix = {}; segs = []
    for lon1, lat1, lon2, lat2, cls, body in coast.get("segments", []):
        a = TO_UTM(lon1, lat1); b = TO_UTM(lon2, lat2)
        segs.append((int(round((a[0] - e0) / UNIT)), int(round(-(a[1] - n0) / UNIT)), int(round((b[0] - e0) / UNIT)), int(round(-(b[1] - n0) / UNIT)), cls_ix.setdefault(cls, len(cls_ix))))
    def b64(fmt, seq):
        return base64.b64encode(struct.pack("<" + fmt * len(seq), *seq)).decode()
    n = len(xz)
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "crs": "EPSG:32640, x = easting - e0, z = -(northing - n0), y up, metres", "origin": {"lon": ORIGIN_LL[0], "lat": ORIGIN_LL[1], "e": round(e0, 1), "n": round(n0, 1)},
           "unit_m": UNIT, "n": n, "devs": DEVS, "districts": districts, "coast_classes": [k for k, _ in sorted(cls_ix.items(), key=lambda x: x[1])],
           "arrays": {"xz_i16": b64("h", [v for p in xz for v in p]), "wd_u8": b64("B", [v for p in wd for v in p]), "h_u16": b64("H", hh), "flags_u8": b64("B", flags), "dist_u8": b64("B", dist), "dev_u8": b64("B", dev)},
           "coast": {"n": len(segs), "xzxz_i16": b64("h", [v for s in segs for v in s[:4]]), "cls_u8": b64("B", [s[4] for s in segs])}}
    p = os.path.join(BOARD, "city_overview.json"); json.dump(out, open(p, "w", encoding="utf-8")); size = os.path.getsize(p)
    print(f"city overview: {n:,} buildings · {len(districts)} districts · {len(segs):,} waterline segments · {size / 1e6:.2f} MB · {round(time.time() - t0)} s")
    if "--push" not in sys.argv:
        print("  not pushed. data/board/city_overview.json is written; pass --push to ship it, and only with the"
              " deploying session's agreement.")
    if "--push" in sys.argv and "--no-push" not in sys.argv:
        r = push("city_overview", out, env_token("INGEST_TOKEN")); print("city_overview ->", r.get("ok"), r.get("bytes"))


if __name__ == "__main__":
    main()
