"""Bind the Dubai Land Department's named buildings (from the transactions export) to footprints on the twin.

Input  data/dld/tx_buildings_<slug>.json   (dld_tx_buildings.py): building name, project, sales by rooms type, sizes, usage,
                                            nearest metro / mall / landmark - the register's own description of each building.
Stages, cheapest first, each binding recording how it was made:
  1. name match     the DLD building name against names already on the footprints (anchors + identity display names), normalised
                    and stemmed, exact first then unique containment. Free, and most of the big towers are already named.
  2. geocode        the rest: Places text search "<building>, <area>, Dubai" (cached), bound to the nearest footprint taller than
                    MIN_H within NEAR_M. Building-like place types only; a sales office or a shop never names a tower.
Output data/identity/official/dld/tx_bindings.json  {"<slug>": {"<i>": {building, project, master, sales, by_rooms, usage, median_sqm,
       median_aed_sqm, metro, mall, landmark, first, last, method, dist_m, place_id}}, "_unbound": {...}}
The resolver reads this as source "dld" (authoritative -> VERIFIED) and build_unit_mix.py reads it for the sold-by-type table.
Usage: python scripts/bind_dld_buildings.py [--no-geocode] [--limit N] [slug ...]
"""
import json, os, re, sys, time, collections
from shapely.geometry import shape, Point
from shapely.ops import transform
from shapely.strtree import STRtree
import pyproj
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token  # noqa: E402
from geocode_projects import places_text, BUILDINGISH, NOT_BUILDING  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); DLD = os.path.join(ROOT, "data", "dld")
OUTD = os.path.join(ROOT, "data", "identity", "official", "dld"); os.makedirs(OUTD, exist_ok=True)
OUT = os.path.join(OUTD, "tx_bindings.json"); CACHE = os.path.join(OUTD, "geocode_cache.json")
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
NEAR_M = 45.0; MIN_H = 11.9    # 6 Sep 2026: 12.0 m is the model's default massing height where no survey height exists (all of JVC); those footprints must stay bindable
AREA_LABEL = {'dubaimarina': 'Dubai Marina', 'businessbay': 'Business Bay', 'burjkhalifa': 'Downtown Dubai', 'palmjumeirah': 'Palm Jumeirah', 'alwasl': 'Al Wasl', 'jumeirahvillagecircle': 'Jumeirah Village Circle', 'jumeirahvillagetriangle': 'Jumeirah Village Triangle', 'motorcity': 'Motor City', 'palmdeira': 'Dubai Islands', 'samaaljadaf': 'Al Jaddaf', 'sobhaheartland': 'Sobha Hartland', 'jltnorth': 'Jumeirah Lake Towers', 'jltsouth': 'Jumeirah Islands', 'arjan': 'Arjan', 'damachills': 'DAMAC Hills', 'dubaihills': 'Dubai Hills Estate', 'dubaiindustrialcity': 'Dubai Industrial City', 'dubaimaritimecity': 'Dubai Maritime City', 'dubaiproductioncity': 'Dubai Production City', 'dubaisciencepark': 'Dubai Science Park', 'dubaisportscity': 'Dubai Sports City', 'dubaistudiocity': 'Dubai Studio City', 'majan': 'Majan', 'meydanone': 'Meydan One', 'siliconoasis': 'Dubai Silicon Oasis', 'alhebiahfifth': 'Al Hebiah Fifth', 'alkhairanfirst': 'Dubai Creek Harbour', 'alsatwa': 'Al Satwa', 'alyelayiss1': 'Al Yelayiss 1', 'alyelayiss2': 'Town Square Dubai', 'alyufrah1': 'Al Yufrah 1', 'dubaiinvestmentparkfirst': 'Dubai Investments Park', 'dubaiinvestmentparksecond': 'Dubai Investments Park 2', 'jabalalifirst': 'Jebel Ali', 'jabalaliindustrialsecond': 'Jebel Ali Industrial 2', 'madinatalmataar': 'Dubai South', 'madinathind4': 'DAMAC Hills 2', 'wadialsafa4': 'Wadi Al Safa 4', 'wadialsafa5': 'Wadi Al Safa 5', 'althanyahfifth': 'Jumeirah Lake Towers'}
STOP = r"\b(by|the|tower|towers|residences?|residence|building|bldg|apartments?|hotel|apartment|dubai|marina|jlt|jvc|downtown|bay|business|palm|jumeirah|residency|complex|project|phase)\b"


def norm(s): return re.sub(r"[^a-z0-9]", "", str(s or "").lower())
def toks(s): return {t for t in re.sub(STOP, " ", str(s or "").lower()).split() if len(t) >= 3 and not t.isdigit()} | {t for t in re.findall(r"\d+", str(s or "")) if len(t) <= 3}
def same_building(dld_name, place_name):
    """the place Google returned must be the building the register named: a shared significant token (word or tower number)"""
    a, b = toks(dld_name), toks(place_name)
    if not a or not b: return False
    if norm(dld_name) and norm(place_name) and (norm(dld_name) in norm(place_name) or norm(place_name) in norm(dld_name)): return True
    return len(a & b) >= 1
def stem(s): return re.sub(STOP, " ", str(s or "").lower())
def nkey(s): return norm(stem(s))


def main():
    geocode = "--no-geocode" not in sys.argv; lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    want = [a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
    slugs = want or [s[13:-5] for s in sorted(os.listdir(DLD)) if s.startswith("tx_buildings_") and s.endswith(".json")]
    key = env_token("GOOGLE_KEY")
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    prev = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    out = {k: v for k, v in prev.items() if not k.startswith("_")}; unbound = {}
    ngeo = 0; tot = collections.Counter()
    for slug in slugs:
        T = json.load(open(os.path.join(DLD, f"tx_buildings_{slug}.json"), encoding="utf-8"))["buildings"]
        F = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
        anchors = json.load(open(os.path.join(NAMES, f"anchors_{slug}.json"), encoding="utf-8")).get("anchors", []) if os.path.exists(os.path.join(NAMES, f"anchors_{slug}.json")) else []
        # names on the footprints
        byname = collections.defaultdict(set); bykey = collections.defaultdict(set)
        for a in anchors:
            for nm in (a.get("name"), a.get("dev_project")):
                if nm: byname[norm(nm)].add(a["i"]); bykey[nkey(nm)].add(a["i"])
        # spatial index of tall footprints
        polys, idx = [], []
        for i, f in enumerate(F):
            if float(f["properties"].get("bHeight") or 0) < MIN_H: continue
            polys.append(transform(TO_UTM, shape(f["geometry"]))); idx.append(i)
        tree = STRtree(polys) if polys else None
        bound = out.setdefault(slug, {})
        for k in list(bound):                                    # re-check earlier geocoded bindings under the tighter gate
            v = bound[k]
            if v.get("method") == "geocoded" and not ((v.get("dist_m") or 99) <= 8.0 or same_building(v.get("building"), v.get("place_name"))):
                unbound.setdefault(slug, []).append({"building": v.get("building"), "project": v.get("project"), "sales": v.get("sales"), "why": "geocode rejected: place name does not match"}); del bound[k]
        taken = {int(k) for k in bound}
        s1 = s2 = miss = 0
        for b in sorted(T, key=lambda x: -x["sales"]):
            name = b["building"]; rec = None
            if not name: continue
            k1, k2 = norm(name), nkey(name)
            cand = byname.get(k1) or (bykey.get(k2) if k2 and len(k2) >= 5 else None)
            if not cand and k2 and len(k2) >= 6:            # unique containment either way
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
            if not rec: miss += 1; unbound.setdefault(slug, []).append({"building": name, "project": b["project"], "sales": b["sales"]}); continue
            if i in taken and bound.get(str(i), {}).get("building") != name:
                # two DLD buildings on one footprint (a podium shared by towers): keep the bigger seller as primary, list the other
                bound[str(i)].setdefault("also", []).append({"building": name, "project": b["project"], "sales": b["sales"], "by_rooms": b["by_rooms"]}); continue
            taken.add(i)
            bound[str(i)] = dict(b, **rec)
        tot["name"] += s1; tot["geo"] += s2; tot["miss"] += miss
        print(f"  {slug:<24} DLD buildings {len(T):>4} | name-matched {s1:>4} | geocoded {s2:>4} | unbound {miss:>4}")
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    out["_unbound"] = unbound; out["_updated"] = time.strftime("%Y-%m-%d %H:%M"); out["_source"] = "DLD transactions export 2026-09-04 via dld_tx_buildings.py"
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nTOTAL name-matched {tot['name']} | geocoded {tot['geo']} ({ngeo} new searches) | unbound {tot['miss']} -> {OUT}")


if __name__ == "__main__":
    main()
