"""Build (and, only when asked, publish) a district's BLOCKS payload: every footprint with its height, plus the streets.

The Blocks view (/blocks on the worker, src/blocks_page.js) is the middle layer between the app's map, where buildings are
dots, and the twin, which is full detail: LOD 100, each footprint raised to its height with a flat roof. It draws in MapLibre
(fill-extrusion), so it wants lon/lat footprints and a height per footprint. Nothing on the worker served that - the twin
reads a packed GLB in local metres (sky_<slug>), the anchors carry names but only the outline of NAMED buildings - so this
writes one compact GeoJSON per district:

    KV key   img_blocks_<slug>            served at /img/blocks_<slug> (stored gzipped; the /img route passes gzip through)
    file     data/ce/<slug>/blocks.json   (data/ is gitignored - a rebuildable output)

Features (one FeatureCollection, so it is plain GeoJSON any tool can open):
    buildings  properties {k:"b", i:<footprint index>, h:<metres>, hs:<height source>, n:<building name>?, a:<address>?}
    streets    properties {k:"s", hw:<OSM highway class>, nm:<street name>?}

The footprint index i is the index in data/ce/<slug>/buildings.geojson - the same id the twin, the anchors, the unit-mix
register and /building/<slug>/<id> all use. Heights, in order (hs names the one each building got, so the view can tell a
measured height from a default): data/ce/<slug>/blocks_heights.json when it exists ({"<i>": {"h": <m>, "src": "<source>"}},
hs = its src), then data/board/bldgfacts_<slug>.json buildings_by_id[i].height_m (hs "bldgfacts"; what the building pages
show), then the anchor's roof height ("anchor"; the twin's own, and the value the JVC 1BR static map used for the ten), then
anchors "fps" ("fps"), then the footprint's bHeight ("bHeight"), then 12 m ("default12"). A height of exactly 12.0 with no
levels on record (the footprint's and the anchor's levels both empty), from ANY of those sources, is the pipeline's
placeholder, not a measurement: it keeps h 12 so the block still draws, and hs becomes "unknown". Streets come from
streets.geojson, or data/ce/<slug>/blocks_streets.geojson (same schema: hw, nm) where the district has none. Names are the anchors' only,
and only where the anchors call it a building name (display_role BUILDING_NAME); an ADDRESS name ("Villa 16, Street 5") is
carried as an address, never as a name.

  python scripts/build_blocks.py jumeirahvillagecircle                 write the file, print the size - touches nothing live
  python scripts/build_blocks.py jumeirahvillagecircle --out C:/x.json write it somewhere else
  python scripts/build_blocks.py jumeirahvillagecircle --push          ALSO publish img_blocks_<slug> through /ingest_market
                                                                       and read it back - production, run only when Kendall says so

Written 30 Sep 2026 for the JVC Blocks prototype. Not yet run with --push.
"""
import base64
import datetime
import gzip
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
WORKER = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
CAP = 5 * 1024 * 1024
STREET_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
                  "secondary_link", "tertiary_link", "residential"}
DP = 6          # 6 decimal places of a degree is ~0.1 m here
DEFAULT_H = 12.0


def r6(v):
    return round(float(v), DP)


def clean_ring(ring):
    out = []
    for c in ring:
        p = [r6(c[0]), r6(c[1])]
        if not out or p != out[-1]:
            out.append(p)
    if len(out) >= 2 and out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def build(slug):
    g = json.load(open(os.path.join(DATA, "ce", slug, "buildings.geojson"), encoding="utf-8"))
    # streets: the district's own streets.geojson; failing that, the blocks_streets.geojson overlay (same schema: hw, nm)
    st_src = next((nm_ for nm_ in ("streets.geojson", "blocks_streets.geojson")
                   if os.path.exists(os.path.join(DATA, "ce", slug, nm_))), None)
    streets = json.load(open(os.path.join(DATA, "ce", slug, st_src), encoding="utf-8")) if st_src else {"features": []}
    # heights overlay, the FIRST source when present: {"<footprint i>": {"h": <m>, "src": "<source>"}}
    ov_path = os.path.join(DATA, "ce", slug, "blocks_heights.json")
    overlay = {}
    if os.path.exists(ov_path):
        for k, v in (json.load(open(ov_path, encoding="utf-8")) or {}).items():
            try:
                hv, ki = float((v or {}).get("h")), int(k)
            except (TypeError, ValueError, AttributeError):
                continue
            if hv > 0:
                overlay[ki] = (hv, str((v or {}).get("src") or "overlay"))
    an_path = os.path.join(DATA, "names", "anchors_%s.json" % slug)
    anch = json.load(open(an_path, encoding="utf-8")) if os.path.exists(an_path) else {}
    fps_h = {r[0]: r[3] for r in (anch.get("fps") or []) if len(r) > 3 and r[3]}
    bf_path = os.path.join(DATA, "board", "bldgfacts_%s.json" % slug)
    bf_h = {}
    if os.path.exists(bf_path):
        for k, v in ((json.load(open(bf_path, encoding="utf-8")) or {}).get("buildings_by_id") or {}).items():
            try:
                hv, ki = float((v or {}).get("height_m")), int(k)
            except (TypeError, ValueError, AttributeError):
                continue
            if hv > 0:
                bf_h[ki] = hv
    by_i = {}
    for a in anch.get("anchors") or []:
        if a.get("i") is not None and a["i"] not in by_i:
            by_i[a["i"]] = a

    feats, lo_x, lo_y, hi_x, hi_y = [], 999.0, 999.0, -999.0, -999.0
    n_named = n_addr = n_anchor_h = 0
    hs_count = {}
    for i, f in enumerate(g["features"]):
        geom = f.get("geometry") or {}
        polys = [geom["coordinates"]] if geom.get("type") == "Polygon" else geom.get("coordinates") if geom.get("type") == "MultiPolygon" else []
        rings = []
        for poly in polys:
            rr = [x for x in (clean_ring(r) for r in poly) if x]
            if rr:
                rings.append(rr)
        if not rings:
            continue
        a = by_i.get(i) or {}
        bh = (f.get("properties") or {}).get("bHeight")
        if i in overlay:
            h, hs = overlay[i]
        elif i in bf_h:
            h, hs = bf_h[i], "bldgfacts"
        elif a.get("h"):
            h, hs = a["h"], "anchor"
        elif fps_h.get(i):
            h, hs = fps_h[i], "fps"
        elif bh:
            h, hs = bh, "bHeight"
        else:
            h, hs = DEFAULT_H, "default12"
        # 12.0 exactly with no levels anywhere is the placeholder, whichever source carried it
        lv = str((f.get("properties") or {}).get("levels") or "").strip() or str(a.get("levels") or "").strip()
        if abs(float(h) - DEFAULT_H) < 1e-9 and not lv:
            hs = "unknown"
        hs_count[hs] = hs_count.get(hs, 0) + 1
        if hs == "anchor":
            n_anchor_h += 1
        props = {"k": "b", "i": i, "h": round(float(h), 1), "hs": hs}
        nm = (a.get("name") or "").strip()
        if nm and a.get("display_role") == "BUILDING_NAME":
            props["n"] = nm
            n_named += 1
        elif nm and a.get("display_role") == "ADDRESS":
            props["a"] = nm
            n_addr += 1
        geo = {"type": "Polygon", "coordinates": rings[0]} if len(rings) == 1 else {"type": "MultiPolygon", "coordinates": rings}
        feats.append({"type": "Feature", "properties": props, "geometry": geo})
        for rr in rings:
            for x, y in rr[0]:
                lo_x, lo_y, hi_x, hi_y = min(lo_x, x), min(lo_y, y), max(hi_x, x), max(hi_y, y)

    # streets: the classes the static map draws, kept to the buildings' box plus a margin (~300 m)
    m = 0.003
    n_st = 0
    for f in streets.get("features") or []:
        p = f.get("properties") or {}
        if p.get("hw") not in STREET_CLASSES or (f.get("geometry") or {}).get("type") != "LineString":
            continue
        cs = f["geometry"]["coordinates"]
        if all(not (lo_x - m < c[0] < hi_x + m and lo_y - m < c[1] < hi_y + m) for c in cs):
            continue
        line = []
        for c in cs:
            q = [r6(c[0]), r6(c[1])]
            if not line or q != line[-1]:
                line.append(q)
        if len(line) < 2:
            continue
        sp = {"k": "s", "hw": p["hw"]}
        if p.get("nm"):
            sp["nm"] = p["nm"]
        feats.append({"type": "Feature", "properties": sp, "geometry": {"type": "LineString", "coordinates": line}})
        n_st += 1

    return {
        "type": "FeatureCollection",
        "meta": {
            "slug": slug, "v": 1, "generated": datetime.date.today().isoformat(),
            "bbox": [r6(lo_x), r6(lo_y), r6(hi_x), r6(hi_y)],
            "buildings": len(feats) - n_st, "named": n_named, "addresses": n_addr, "anchor_heights": n_anchor_h, "streets": n_st,
            "height_sources": hs_count, "streets_file": st_src or "", "heights_overlay": os.path.exists(ov_path),
            "sources": "footprints and streets: data/ce/%s (OpenStreetMap contributors, district model); heights and names: "
                       "data/names/anchors_%s.json" % (slug, slug),
        },
        "features": feats,
    }


def push(slug, raw, tok):
    gz = gzip.compress(raw, 9)
    if len(gz) > CAP:
        raise SystemExit("img_blocks_%s is %d KB gzipped - over the 5 MB cap, not pushed" % (slug, len(gz) // 1024))
    key = "blocks_" + slug
    body = json.dumps({"imageName": key, "image": base64.b64encode(gz).decode(), "contentType": "application/json"}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-blocks/1.0"})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    print("pushed img_%s (%d KB gz): ok=%s" % (key, len(gz) // 1024, r.get("ok")))
    # read it back: "the push ran" is not evidence (push_sky_gz.py / push_buildings_gz.py do the same)
    back = urllib.request.urlopen(urllib.request.Request(WORKER + "/img/" + key + "?t=verify", headers={"User-Agent": "najma-blocks/1.0"}), timeout=120).read()
    if back[:2] == b"\x1f\x8b":
        back = gzip.decompress(back)
    got = json.loads(back.decode("utf-8"))
    same = len(got.get("features") or []) == len(json.loads(raw.decode("utf-8"))["features"])
    print("read back /img/%s: %d features - %s" % (key, len(got.get("features") or []), "MATCHES" if same else "DOES NOT MATCH"))
    return 0 if same else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    slug = args[0]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(DATA, "ce", slug, "blocks.json")
    if "--out" in sys.argv and out in args:
        args.remove(out)
    fc = build(slug)
    raw = json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "wb").write(raw)
    mm = fc["meta"]
    print("%s: %d buildings (%d named, %d addresses; heights %s), %d streets -> %s  %d KB, %d KB gzipped"
          % (slug, mm["buildings"], mm["named"], mm["addresses"],
             ", ".join("%s %d" % kv for kv in sorted(mm["height_sources"].items(), key=lambda kv: -kv[1])), mm["streets"], out,
             len(raw) // 1024, len(gzip.compress(raw, 9)) // 1024))
    if "--push" in sys.argv:
        sys.path.insert(0, HERE)
        from build_avail_index import env_token
        return push(slug, raw, env_token("INGEST_TOKEN"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
