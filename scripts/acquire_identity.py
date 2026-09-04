"""Acquisition sweep for building identity: pull every source that can be fetched without a portal click-through.

The survey names we already merge (OpenStreetMap `name`, Overture *buildings*, Wikidata) are exhausted - re-running them adds
nothing. These are the layers we had never pulled:

  overture places      points of interest with names, categories and confidence - the strongest open name source left
  overture addresses   address points: house/building numbers, streets - identity for a villa that has no name
  osm addresses        addr:housenumber / addr:street / building:name / ref on the footprint itself
  wikidata             re-pulled with a wider box so the emirate's outlying towers are included

Everything lands under data/identity/<source>/<slug>.json, raw, with the query that produced it, so a later resolver can score
candidates without re-fetching. Nothing here decides a name: acquisition only. Cross-source resolution is resolve_identity.py.

NOT automated on purpose: the Dubai Land Department's Unit, Building, Land and Project CSVs and Dubai Municipality's Building
Summary / Makani files sit behind a portal with a click-through. The gateway API serves transactions and rents only - `units`,
`buildings`, `lands` and `projects` answer HTTP 500 there while `transactions` answers 200, so the API route for them does not
exist. Those files are downloaded by hand and dropped into data/identity/official/dld/ and .../dm/; see IDENTITY_SOURCES.md.

Usage: python scripts/acquire_identity.py [--overture] [--osm] [--wikidata] [--all] [slug ...]
"""
import argparse, glob, json, os, subprocess, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "identity")
UA = {"User-Agent": "najma-identity/1.0 (contact@digitalabbot.io)"}
PAD = 0.0015          # ~150 m around the district so a POI just outside still reaches its footprint


def districts():
    return [os.path.basename(p)[10:-5] for p in sorted(glob.glob(os.path.join(ROOT, "data", "board", "bldgfacts_*.json")))]


def bbox(slug):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj): return None
    xs, ys = [], []
    for f in json.load(open(gj, encoding="utf-8"))["features"]:
        g = f["geometry"]
        rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
        for r in rings:
            for p in r: xs.append(p[0]); ys.append(p[1])
    if not xs: return None
    return (min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD)


def overture(slug, box, kinds=("place", "address"), force=False):
    d = os.path.join(OUT, "overture"); os.makedirs(d, exist_ok=True)
    got = {}
    for kind in kinds:
        out = os.path.join(d, f"{kind}_{slug}.geojson")
        if os.path.exists(out) and os.path.getsize(out) > 0 and not force:
            got[kind] = "cached"; continue
        cmd = [sys.executable, "-m", "overturemaps", "download",
               f"--bbox={box[0]:.5f},{box[1]:.5f},{box[2]:.5f},{box[3]:.5f}", "-f", "geojson", f"--type={kind}", "-o", out]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
            got[kind] = "ok"
        except subprocess.CalledProcessError as e:
            got[kind] = "FAIL " + (e.stderr or b"").decode("utf-8", "ignore")[:60]
        except Exception as e:
            got[kind] = "FAIL " + str(e)[:60]
    return got


OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def osm_addresses(slug, box, force=False):
    """Every address-bearing or name-bearing building way in the district: house number, street, building name, ref."""
    d = os.path.join(OUT, "osm"); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"addr_{slug}.json")
    if os.path.exists(out) and os.path.getsize(out) > 0 and not force: return "cached"
    s, w, n, e = box[1], box[0], box[3], box[2]
    b = f"{s},{w},{n},{e}"
    q = ('[out:json][timeout:180];('
         f'way["building"]["addr:housenumber"]({b});'
         f'way["building"]["addr:housename"]({b});'
         f'way["building"]["building:name"]({b});'
         f'way["building"]["ref"]({b});'
         f'way["building"]["name:ar"]({b});'
         f'relation["building"]["addr:housenumber"]({b});'
         ');out tags center;')
    for m in OVERPASS:
        try:
            r = urllib.request.urlopen(urllib.request.Request(m, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA), timeout=300)
            j = json.loads(r.read().decode("utf-8"))
            json.dump({"query": q, "elements": j.get("elements", [])}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(8)
            return f"ok {len(j.get('elements', []))}"
        except Exception as ex:
            last = str(ex)[:70]
    return "FAIL " + last


def wikidata(force=False):
    d = os.path.join(OUT, "wikidata"); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "dubai_structures.json")
    if os.path.exists(out) and os.path.getsize(out) > 0 and not force: return "cached"
    # anything that is a building OR an architectural structure, with coordinates, inside the emirate box
    q = """SELECT ?item ?itemLabel ?altLabel ?coord ?typeLabel ?height ?floors WHERE {
  ?item wdt:P31/wdt:P279* ?cls . VALUES ?cls { wd:Q41176 wd:Q811979 wd:Q1497364 wd:Q18142 }
  ?item wdt:P625 ?coord .
  OPTIONAL { ?item wdt:P2048 ?height. } OPTIONAL { ?item wdt:P1101 ?floors. } OPTIONAL { ?item wdt:P31 ?type. }
  OPTIONAL { ?item skos:altLabel ?altLabel FILTER(lang(?altLabel)='en') }
  SERVICE wikibase:box { ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerWest "Point(54.70 24.55)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerEast "Point(56.25 25.55)"^^geo:wktLiteral . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ar". } }"""
    u = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"})
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180)
        j = json.loads(r.read().decode("utf-8"))
        json.dump(j, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        return f"ok {len(j['results']['bindings'])}"
    except Exception as e:
        return "FAIL " + str(e)[:70]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for f in ("overture", "osm", "wikidata", "all", "force"): ap.add_argument("--" + f, action="store_true")
    ap.add_argument("slugs", nargs="*"); a = ap.parse_args()
    if a.all: a.overture = a.osm = a.wikidata = True
    os.makedirs(OUT, exist_ok=True)
    for sub in ("official/dld", "official/dm"): os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    slugs = a.slugs or districts()
    if a.wikidata: print(f"{'wikidata (emirate box)':<28} {wikidata(a.force)}")
    for s in slugs:
        box = bbox(s)
        if not box: print(f"{s:<28} no footprints"); continue
        line = f"{s:<28}"
        if a.overture: line += " overture " + json.dumps(overture(s, box, force=a.force))
        if a.osm: line += " | osm " + osm_addresses(s, box, force=a.force)
        print(line, flush=True)
