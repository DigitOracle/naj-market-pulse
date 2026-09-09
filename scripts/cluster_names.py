"""Sub-community names for the villa districts (Kendall, 6 Sep: "for Dubai Hills, why do you not know the names of the buildings...
although these are residential, there are names, and districts. find them, map them").

A villa is not a building in the register - it is a PLOT. So the buildings table, which is where every other district's names come
from, is nearly empty for Dubai Hills or DAMAC Hills, and the twin renders four thousand anonymous houses. What the register does
hold, in the land registry and the units table, is the SUB-COMMUNITY each plot belongs to: Maple 2, Sidra, Acacia at Park Heights,
Golf Promenade, Elo 3. That is also the name a buyer actually uses.

There is no parcel geometry in Dubai, so a plot number cannot be placed. But there are only a few dozen sub-communities per master
community, so each one is geocoded once and every unnamed footprint within its reach is attributed to it. The result is a
NEIGHBOURHOOD attribution, never a building name: the anchor gets `cluster`, and the card reads "in Maple 2, Dubai Hills".

Radius scales with how big the sub-community is (plot count), because Sidra is a district and Rosehill is one block.

Output data/names/clusters_<slug>.json  {"clusters": [{name, lon, lat, plots, units, radius_m, place_id}], "assign": {"<footprint i>": "<name>"}}
       merged into the anchors by apply_identity as `cluster` (never as `name`).
Usage: python scripts/cluster_names.py [--no-geocode] [--limit N] [slug ...]
"""
import duckdb, glob, json, math, os, sys, time, collections
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
from geocode_projects import places_text  # noqa: E402
from bind_dld_buildings import TO_UTM, AREA_LABEL, CACHE, NAMES, CE  # noqa: E402
from dld_rent_buildings import DLD_AREA  # noqa: E402
UNITS = [f for f in sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\units_2026-09-04_*.csv")) if "(1)" not in f]
LAND = r"C:\Dev\naj-market-pulse\data\raw_downloads\land_registry_2026-09-04_17-30-03_0001.csv"
MIN_PLOTS = 12                 # below this a "project" is a single plot or a typo, not a sub-community
R_MIN, R_MAX = 160.0, 900.0    # how far a sub-community's name may reach


GENERIC_T = {"dubai", "hills", "damac", "estate", "the", "at", "by", "residences", "residence", "tower", "towers", "villas",
             "community", "phase", "emaar", "properties", "development", "project", "and", "for", "sale", "apartments"}


def _tok(t):
    import re
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(t or "").lower()) if w not in GENERIC_T}


def place_is_the_cluster(name, place_name, area_label):
    """The place Google returned must BE the sub-community asked for, not its master community and not a neighbour."""
    import re
    a, b = _tok(name), _tok(place_name)
    if not a or not b: return False
    if not _tok(place_name) - _tok(area_label): return False        # the place is just the master community
    shared = {w for w in (a & b) if len(w) >= 4}
    if shared: return True
    # spacing and accents only: "Golf ville" is "Golfville", "Prive Residence" is "Prive Residence"
    import unicodedata
    def compact(t):
        t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]", "", t.lower())
    ca, cb = compact(name), compact(place_name)
    if len(ca) >= 6 and (ca in cb or cb in ca): return True
    # a name that is entirely generic once stripped (SIDRA 2 -> {sidra}) still counts when the stem matches exactly
    return bool(a & b) and min(len(w) for w in (a & b)) >= 4


def _flat(c, out=None):
    out = [] if out is None else out
    if isinstance(c[0], (int, float)): out.extend(c[:2])
    else:
        for k in c: _flat(k, out)
    return out


def area_of(slug):
    for a, v in DLD_AREA.items():
        if slug in v: return a
    return None


def register_clusters(con, area):
    """sub-community -> how many plots and units the register files under it"""
    rows = con.execute("""select cname, sum(plots) p, sum(units) x from (
        select project_name_en as cname, count(*) as plots, 0 as units from l where area_name_en = ? and project_name_en is not null group by 1
        union all
        select project_name_en as cname, 0 as plots, count(*) as units from u where area_name_en = ? and project_name_en is not null group by 1)
        group by 1 order by p + x desc""", [area, area]).fetchall()
    return [(n.strip(), int(p), int(x)) for n, p, x in rows if n and n.strip()]


def main():
    geocode = "--no-geocode" not in sys.argv
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    want = [a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
    slugs = want or sorted({s for v in DLD_AREA.values() for s in v if os.path.exists(os.path.join(CE, s, "buildings.geojson"))})
    key = env_token("GOOGLE_KEY")
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    con = duckdb.connect()
    con.execute(f"create table u as select area_name_en, project_name_en from read_csv_auto({[f.replace(chr(92),'/') for f in UNITS]!r}, sample_size=50000, all_varchar=true, union_by_name=true)")
    con.execute(f"create table l as select area_name_en, project_name_en from read_csv_auto('{LAND.replace(chr(92),'/')}', sample_size=50000, all_varchar=true)")
    ngeo = 0; grand = collections.Counter()
    for slug in slugs:
        area = area_of(slug)
        gj = os.path.join(CE, slug, "buildings.geojson")
        if not area or not os.path.exists(gj): continue
        cl = [c for c in register_clusters(con, area) if c[1] + c[2] >= MIN_PLOTS]
        if not cl: continue
        F = json.load(open(gj, encoding="utf-8"))["features"]
        A = json.load(open(os.path.join(NAMES, f"anchors_{slug}.json"), encoding="utf-8")).get("anchors", []) if os.path.exists(os.path.join(NAMES, f"anchors_{slug}.json")) else []
        named = {a["i"] for a in A if a.get("name")}
        cents, idx = [], []
        for i, f in enumerate(F):
            if i in named: continue
            try: g = transform(TO_UTM, shape(f["geometry"])); c = g.centroid
            except Exception: continue
            cents.append(Point(c.x, c.y)); idx.append(i)
        # a district that is still being built (The Valley) has no unnamed footprints to attribute - its sub-communities are still real
        tree = STRtree(cents) if cents else None
        xs = [x for f in F for x in _flat(f["geometry"]["coordinates"])[0::2]]; ys = [y for f in F for y in _flat(f["geometry"]["coordinates"])[1::2]]
        bbox = (min(xs) - 0.006, min(ys) - 0.006, max(xs) + 0.006, max(ys) + 0.006) if xs else None
        lab = AREA_LABEL.get(slug, slug)
        out, assign, rejected = [], {}, []
        for name, plots, units in cl:
            q = f"{name}, {lab}, Dubai"
            res = cache.get(q)
            if res is None:
                if not geocode or ngeo >= lim: continue
                try: res = places_text(q, key); cache[q] = res; ngeo += 1; time.sleep(0.12)
                except Exception as e: res = []; print("   search failed:", q[:52], str(e)[:40])
            if not res: continue
            pick = None
            for cand in res[:4]:
                pn = (cand.get("displayName") or {}).get("text") or ""
                if place_is_the_cluster(name, pn, lab): pick = cand; break
            if pick is None:
                rejected.append({"name": name, "plots": plots, "units": units,
                                 "place_returned": ((res[0].get("displayName") or {}).get("text") or ""),
                                 "why": "the place returned is not this sub-community"})
                continue
            res = [pick]
            loc = (res[0].get("location") or {})
            if not loc.get("longitude"): continue
            pt = Point(TO_UTM(loc["longitude"], loc["latitude"]))
            r = max(R_MIN, min(R_MAX, 14.0 * math.sqrt(max(plots, units))))     # a bigger community reaches further
            hits = [j for j in tree.query(pt.buffer(r)) if cents[j].distance(pt) <= r] if tree else []
            inside_district = bool(bbox) and bbox[0] <= loc["longitude"] <= bbox[2] and bbox[1] <= loc["latitude"] <= bbox[3]
            if not hits and not inside_district: continue                      # nothing to attribute AND not inside the district: not ours
            out.append({"name": name, "lon": round(loc["longitude"], 6), "lat": round(loc["latitude"], 6), "plots": plots,
                        "units": units, "radius_m": round(r), "place_id": res[0].get("id"),
                        "place_name": (res[0].get("displayName") or {}).get("text") or "", "footprints": len(hits)})
            for j in hits:
                i = idx[j]; d = cents[j].distance(pt)
                prev = assign.get(i)
                if prev is None or d < prev[1]: assign[i] = (name, d)            # nearest sub-community wins
        if not out: continue
        doc = {"district": slug, "area": area, "generated": time.strftime("%Y-%m-%d"),
               "note": "Sub-community attribution, not a building name. The register files each plot under a sub-community; the sub-community is geocoded once and unnamed footprints within its reach are attributed to it.",
               "clusters": sorted(out, key=lambda c: -c["footprints"]), "assign": {str(k): v[0] for k, v in assign.items()},
               "rejected": sorted(rejected, key=lambda r: -(r["plots"] + r["units"]))[:60]}
        json.dump(doc, open(os.path.join(NAMES, f"clusters_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        grand["clusters"] += len(out); grand["footprints"] += len(assign)
        grand["rejected"] += len(rejected)
        print(f"  {slug:<26} sub-communities {len(out):>3} of {len(cl):>3} (rejected {len(rejected):>3}) | unnamed footprints attributed {len(assign):>5} of {len(idx):>5}")
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nTOTAL sub-communities {grand['clusters']:,} | rejected as unverified {grand['rejected']:,} | footprints attributed {grand['footprints']:,} | new lookups {ngeo}")


if __name__ == "__main__":
    main()
