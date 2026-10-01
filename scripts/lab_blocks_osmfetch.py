"""LAB (Blocks type hints) - fetch OpenStreetMap buildings WITH their tags, plus the context that types them, for one district.

The same idea as scripts/lab_buildingtype_fetch.py (whose three cached districts in data/lab/buildingtype/ are REUSED, never
re-fetched), extended to every district and folded into ONE Overpass query per district:

    way/relation["building"]                                   out tags geom   (footprints + every tag)
    way landuse=residential|industrial|commercial|retail,
    way/relation amenity=school|...|place_of_worship|hospital,
    way/relation shop=mall                                     out tags geom   (grounds that type what stands on them)
    node amenity|shop|office|craft                             out body        (POIs WITH lat/lon)

The area is not the district's bbox (Liwan 1's is 18 x 8 km, Madinat Al Mataar's 212 km2): it is the set of ~1.1 km cells that
actually hold our footprints, each cut to those footprints' extent + ~50 m, unioned inside the one query.

Polite by construction: one query per district, a 30 s pause between districts, the repo's contact User-Agent, three mirrors,
retries with exponential backoff (60 / 120 / 240 s) on 429 / 504 / timeouts, a response carrying an Overpass runtime-error
remark is treated as a failure (never cached), and everything that succeeds is cached to disk and never re-fetched unless
--refresh is given.

Output: data/lab/blocks/osm/osm_<slug>.json   {"fetched", "mirror", "cells", "query", "elements": [...]}
Usage:  python scripts/lab_blocks_osmfetch.py arjan motorcity            (library use: fetch_district(slug))
Research use only. Reads data/ce/<slug>/buildings.geojson; writes only under data/lab/blocks/osm/.
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
OUT = os.path.join(ROOT, "data", "lab", "blocks", "osm"); os.makedirs(OUT, exist_ok=True)
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]   # 4th public instance (OSM wiki list), added 22:25 - the main ones were 504ing
UA = {"User-Agent": "najma-lab-blocks/1.0 (research; contact@digitalabbot.io)"}
PAUSE_S = 30
PAD = 0.0005          # ~50 m
CELL = 0.01           # ~1.1 km
_last_fetch = [0.0]


def cells_of(slug):
    """[(s, w, n, e)] - one box per occupied ~1.1 km cell, cut to the footprints whose first vertex falls in it, padded ~50 m."""
    return cells_from_feats(json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"])


def cells_from_feats(feats):
    box = {}
    for f in feats:
        g = f.get("geometry") or {}
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates") or []
        pts = [c for poly in polys for c in (poly[0] if poly else [])]
        if not pts:
            continue
        key = (int(pts[0][0] // CELL), int(pts[0][1] // CELL))
        b = box.setdefault(key, [999.0, 999.0, -999.0, -999.0])
        for x, y in pts:
            b[0] = min(b[0], y); b[1] = min(b[1], x); b[2] = max(b[2], y); b[3] = max(b[3], x)
    return [(round(b[0] - PAD, 6), round(b[1] - PAD, 6), round(b[2] + PAD, 6), round(b[3] + PAD, 6)) for _, b in sorted(box.items())]


def query(cells, buildings=True):
    bbs = ["%s,%s,%s,%s" % c for c in cells]
    def u(stmt):
        return "".join(stmt % b for b in bbs)
    lu = 'landuse~"^(residential|industrial|commercial|retail)$"'
    am = 'amenity~"^(school|kindergarten|college|university|place_of_worship|hospital)$"'
    q = "[out:json][timeout:%d];" % (240 if len(cells) > 40 else 150 if len(cells) > 10 else 90)   # a lighter declared budget gets a slot sooner under load
    if buildings:
        q += "(" + u('way["building"](%s);') + u('relation["building"](%s);') + ");out tags geom;"
    return (q + "(" + u("way[" + lu + "](%s);") + u("way[" + am + "](%s);") + u("relation[" + am + "](%s);")
            + u('way["shop"="mall"](%s);') + u('relation["shop"="mall"](%s);') + ");out tags geom;"
            "(" + u('node["amenity"](%s);') + u('node["shop"](%s);') + u('node["office"](%s);') + u('node["craft"](%s);') + ");out body;")


def _post(url, q, timeout=360):
    req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.load(r)
    rem = (j.get("remark") or "")
    if "error" in rem.lower() or "timed out" in rem.lower() or "out of memory" in rem.lower():
        raise RuntimeError("overpass remark: %s" % rem[:200])
    return j["elements"]


_good = [0]      # index of the mirror that last answered: start there next time (spreads load off a busy main instance)


def fetch(q, log=print):
    last = None
    for attempt in range(4):
        order = MIRRORS[_good[0]:] + MIRRORS[:_good[0]]
        for url in order:
            host = url.split("//")[1].split("/")[0]
            try:
                els = _post(url, q)
                _good[0] = MIRRORS.index(url)
                return els, url
            except urllib.error.HTTPError as e:
                last = e
                log("  overpass %s: HTTP %s" % (host, e.code))
                if e.code in (429, 504):
                    time.sleep(30)
            except Exception as e:
                last = e
                log("  overpass %s: %s" % (host, str(e)[:160]))
                time.sleep(10)
        wait = 60 * (2 ** attempt)
        log("  all mirrors failed (attempt %d) - backing off %d s" % (attempt + 1, wait))
        time.sleep(wait)
    raise RuntimeError("Overpass unreachable on all mirrors after retries: %s" % last)


def cache_path(slug):
    return os.path.join(OUT, "osm_%s.json" % slug)


def fetch_district(slug, refresh=False, log=print, ctx_only=False):
    dst = os.path.join(OUT, "osm_ctx_%s.json" % slug) if ctx_only else cache_path(slug)
    if os.path.exists(dst) and not refresh:
        return dst, False
    wait = PAUSE_S - (time.time() - _last_fetch[0])
    if _last_fetch[0] and wait > 0:
        log("  pausing %d s (polite)" % wait); time.sleep(wait)
    cells = cells_of(slug); q = query(cells, buildings=not ctx_only)
    t = time.time()
    try:
        els, url = fetch(q, log)
    finally:
        _last_fetch[0] = time.time()
    tmp = dst + ".tmp"
    json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "mirror": url, "cells_s_w_n_e": cells, "query": q, "elements": els},
              open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, dst)
    nb = sum(1 for e in els if e["type"] in ("way", "relation") and "building" in (e.get("tags") or {}))
    nn = sum(1 for e in els if e["type"] == "node")
    log("  %-26s fetched: %d cells, %d building ways/relations, %d POI nodes, %d elements (%.1f s, %s)"
        % (slug, len(cells), nb, nn, len(els), time.time() - t, url.split("//")[1].split("/")[0]))
    return dst, True


# ------------------------------------------------------------------ city communities (data/blocks_city), with cache reuse
CITY_OUT = os.path.join(OUT, "city"); os.makedirs(CITY_OUT, exist_ok=True)
CELLS_INDEX = os.path.join(OUT, "_cells_index.json")


def _cells_index():
    """{cache path (relative to OUT): [[s, w, n, e], ...]} for every combined cache (buildings + context + POIs), built lazily."""
    idx = {}
    try:
        idx = json.load(open(CELLS_INDEX, encoding="utf-8"))
    except Exception:
        pass
    changed = False
    for d in (OUT, CITY_OUT):
        for f in sorted(os.listdir(d)):
            if not (f.startswith("osm_") and f.endswith(".json")) or f.startswith("osm_ctx_"): continue
            rel = os.path.relpath(os.path.join(d, f), OUT).replace("\\", "/")
            if rel in idx: continue
            try:
                j = json.load(open(os.path.join(d, f), encoding="utf-8"))
                idx[rel] = j.get("cells_s_w_n_e") or []; changed = True
            except Exception:
                pass
    if changed:
        tmp = CELLS_INDEX + ".tmp"; json.dump(idx, open(tmp, "w", encoding="utf-8")); os.replace(tmp, CELLS_INDEX)
    return idx


def _fbox(f):
    g = f.get("geometry") or {}
    polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates") or []
    pts = [c for poly in polys for c in (poly[0] if poly else [])]
    if not pts: return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(ys), min(xs), max(ys), max(xs)


def fetch_city(slug, feats, log=print, refresh=False):
    """OSM for a city community: footprints already inside a cached fetch's cells reuse that cache (no query); only the rest
    is fetched, in ONE query. Returns (elements, provenance list)."""
    dst = os.path.join(CITY_OUT, "osm_%s.json" % slug)
    if os.path.exists(dst) and not refresh:
        j = json.load(open(dst, encoding="utf-8"))
        reused = j.get("reused") or []
    else:
        idx = {k: v for k, v in _cells_index().items() if k != "city/osm_%s.json" % slug}
        boxes = [f_ for f_ in (_fbox(f) for f in feats) if f_]
        near = []
        if boxes:
            S = min(b[0] for b in boxes); W = min(b[1] for b in boxes); N = max(b[2] for b in boxes); E = max(b[3] for b in boxes)
            near = [(k, c) for k, cs in idx.items() for c in cs if not (c[0] > N or c[2] < S or c[1] > E or c[3] < W)]
        reused, todo = set(), []
        for f in feats:
            b = _fbox(f)
            if not b: continue
            hit = next((k for k, c in near if c[0] <= b[0] and c[1] <= b[1] and b[2] <= c[2] and b[3] <= c[3]), None)
            if hit: reused.add(hit)
            else: todo.append(f)
        reused = sorted(reused)
        cells = cells_from_feats(todo) if todo else []
        els, url = [], None
        if cells:
            wait = PAUSE_S - (time.time() - _last_fetch[0])
            if _last_fetch[0] and wait > 0:
                log("  pausing %d s (polite)" % wait); time.sleep(wait)
            t = time.time()
            try:
                els, url = fetch(query(cells), log)
            finally:
                _last_fetch[0] = time.time()
            log("  %-26s fetched: %d cells for %d of %d footprints, %d elements (%.1f s, %s); reused %d cache(s)"
                % (slug, len(cells), len(todo), len(feats), len(els), time.time() - t, url.split("//")[1].split("/")[0], len(reused)))
        else:
            log("  %-26s all %d footprints inside cached fetches - no query (%s)" % (slug, len(feats), ", ".join(reused)[:120]))
        tmp = dst + ".tmp"
        json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "mirror": url, "cells_s_w_n_e": cells, "reused": reused,
                   "query": query(cells) if cells else None, "elements": els}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, dst)
        idx = _cells_index()                                     # register this cache's own (fetched) cells for later reuse
        idx["city/osm_%s.json" % slug] = cells
        tmp = CELLS_INDEX + ".tmp"; json.dump(idx, open(tmp, "w", encoding="utf-8")); os.replace(tmp, CELLS_INDEX)
        j = {"elements": els}
    seen, out = set(), []
    for rel in [None] + list(reused):
        src = j["elements"] if rel is None else json.load(open(os.path.join(OUT, rel), encoding="utf-8"))["elements"]
        for e in src:
            key = (e["type"], e["id"])
            if key in seen: continue
            seen.add(key); out.append(e)
    prov = ["data/lab/blocks/osm/city/osm_%s.json" % slug] + ["data/lab/blocks/osm/%s" % r for r in reused]
    return out, prov


def uncovered(feats):
    """The footprints NOT inside any cached fetch's cells (what a query would still have to fetch)."""
    idx = _cells_index()
    boxes = [b for b in (_fbox(f) for f in feats) if b]
    if not boxes:
        return []
    S = min(b[0] for b in boxes); W = min(b[1] for b in boxes); N = max(b[2] for b in boxes); E = max(b[3] for b in boxes)
    near = [c for k, cs in idx.items() for c in cs if not (c[0] > N or c[2] < S or c[1] > E or c[3] < W)]
    return [f for f in feats if (lambda b: b and not any(c[0] <= b[0] and c[1] <= b[1] and b[2] <= c[2] and b[3] <= c[3] for c in near))(_fbox(f))]


def fetch_batch(name, feats, log=print):
    """ONE query for several small communities' footprints not yet inside a cached fetch (fewer, larger requests: the same
    data, a fraction of the queueing on a 504-ing server). Saved as city/osm__batch_<name>.json and registered in the cells
    index, so each community's own fetch_city then finds its footprints covered and sends nothing."""
    dst = os.path.join(CITY_OUT, "osm__batch_%s.json" % name)
    if os.path.exists(dst):
        return dst
    idx = _cells_index()
    boxes = [b for b in (_fbox(f) for f in feats) if b]
    if not boxes:
        return None
    S = min(b[0] for b in boxes); W = min(b[1] for b in boxes); N = max(b[2] for b in boxes); E = max(b[3] for b in boxes)
    near = [c for k, cs in idx.items() for c in cs if not (c[0] > N or c[2] < S or c[1] > E or c[3] < W)]
    todo = [f for f in feats if (lambda b: b and not any(c[0] <= b[0] and c[1] <= b[1] and b[2] <= c[2] and b[3] <= c[3] for c in near))(_fbox(f))]
    if not todo:
        return None
    cells = cells_from_feats(todo)
    wait = PAUSE_S - (time.time() - _last_fetch[0])
    if _last_fetch[0] and wait > 0:
        log("  pausing %d s (polite)" % wait); time.sleep(wait)
    t = time.time()
    try:
        els, url = fetch(query(cells), log)
    finally:
        _last_fetch[0] = time.time()
    tmp = dst + ".tmp"
    json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "mirror": url, "cells_s_w_n_e": cells, "batch": name,
               "query": query(cells), "elements": els}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, dst)
    idx = _cells_index(); idx["city/osm__batch_%s.json" % name] = cells
    tmp = CELLS_INDEX + ".tmp"; json.dump(idx, open(tmp, "w", encoding="utf-8")); os.replace(tmp, CELLS_INDEX)
    log("  batch %-20s fetched: %d cells for %d footprints, %d elements (%.1f s, %s)"
        % (name, len(cells), len(todo), len(els), time.time() - t, url.split("//")[1].split("/")[0]))
    return dst


if __name__ == "__main__":
    for s in [a for a in sys.argv[1:] if not a.startswith("--")]:
        fetch_district(s, refresh="--refresh" in sys.argv)
