"""The Sobha mask: which massed footprints in the twin belong to Sobha, and how sure each one is.

Kendall, 23 Sep 2026: "isolate the map, the twin - build a version of Sobha-only projects." The twin has no
developer axis: its unit is the district slug, and a building inside it is the footprint index `i` (the
feature order in data/ce/<slug>/buildings.geojson, the mesh index the client keys on) with a `duid` beside
it where the graph has one. So the Sobha view is a MASK - the set of (district, i) the client keeps lit while
everything else dims - and this script is where that set is decided.

WHAT is Sobha is not decided here. That is data/identity/sobha_projects.json (register developer_number in
the accepted Sobha group, developer_group_decisions.json). This script walks from those project numbers to
footprints and records HOW it reached each one, because the routes are not equally sure:

  parcel    the project's register parcels (DLD land / buildings / units registers) matched to the parcel key
            a footprint already carries - stack_<slug>.json plot.key, or unitmix_<slug>.json dld.parcel. A
            parcel is not one tower (podiums and service blocks share plots), so every footprint on the parcel
            is in and the stack's `plot.tallest` says which is the tower. Exact.
  dm        the Municipality building id the key bridge attaches to the project's register buildings
            (key_bridge_<slug>.json dld_project_id -> dm_building_id) matched to the footprint's own `dm`
            (stack or unitmix). Exact, rarer.
  radius    footprints inside the card radius of a sub-community that IS the project (sub_community_building,
            "within card radius, >= 12 m"). A circle, not a parcel.
  geocode   a Google point for the project name (data/geocode_cache.json goog:: keys) and the tallest
            unnamed footprints within 150 m, capped at the register's building count. Guards: towers only
            (height >= 30 m, and the project must register buildings, so villa phases never take this route);
            a footprint already carrying a name that is not Sobha's is refused (Google put One Park Avenue on
            Maybach Six); a point that Google returned for more than one project is a community centroid and
            is refused. Least sure, and carried as such so the client can draw it dimmer.

A project reached by a surer route never takes a less sure one in the same district. Every project the
routes cannot place, and every district the twin has not massed (Ras Al Khor Industrial First for Sobha One,
Wadi Al Safa 2 for Sobha Reserve, Al Safouh Second for The S), is a listed gap, never a silent drop.

Output: data/board/sobha_mask.json
  {"generated", "developer", "rule", "totals", "projects": [coverage per project],
   "districts": {slug: {"n", "i": [...], "duid": [...], "by_i": {i: {"project_number", "name", "method",
                 "tallest", "footprint_name", "height_m"}}}},
   "gaps": [...]}
Usage: python scripts/build_sobha_mask.py [--push]   (--push stores it as KV devmask_sobha, which the skyline client reads)
"""
import json, math, os, sys, datetime as dt
from collections import defaultdict

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = os.path.join(ROOT, "data", "graph", "najma.duckdb")
BOARD = os.path.join(ROOT, "data", "board")
CE = os.path.join(ROOT, "data", "ce")
GEOCODE = os.path.join(ROOT, "data", "geocode_cache.json")
PROJECTS = os.path.join(ROOT, "data", "identity", "sobha_projects.json")
OUT = os.path.join(BOARD, "sobha_mask.json")

# DLD area name -> district slug for the areas Sobha builds in. None = the twin has not massed it: a GAP.
AREA_SLUG = {
    "Al Merkadh": "sobhaheartland", "Bukadra": "bukadra", "Business Bay": "businessbay", "Marsa Dubai": "dubaimarina",
    "Jabal Ali First": "jabalalifirst", "Al Thanyah Fifth": "althanyahfifth", "Al Barsha South Fourth": "jumeirahvillagecircle",
    "Al Hebiah First": "motorcity", "Al Yufrah 1": "alyufrah1", "Madinat Al Mataar": "madinatalmataar",
    "Ras Al Khor Industrial First": "rasalkhor", "Wadi Al Safa 2": None, "Al Safouh Second": None,
}
# Verde by Sobha sits on the JLT boundary and is massed in both neighbouring slugs.
EXTRA_SLUGS = {"Al Thanyah Fifth": ["jltnorth"]}
GEOCODE_RADIUS_M = 150
TOWER_MIN_M = 30
SOBHA_WORDS = ("sobha", "hartland", "riverside crescent", "skyscape", "skyvue", "creek vista", "crest grande", "the crest",
               "one park avenue", "waves", "verde", "seahaven", "orbis", "solis", "sobha central", "ivory", "sapphire", "daffodil",
               "skyparks", "wilton", "kensington", "highbury", "berkeley", "gemini", "elwood", "sanctuary", "the s tower", "serene")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def centroid(geom):
    ring = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def dist_m(lon1, lat1, lon2, lat2):
    return math.hypot((lat1 - lat2) * 111320, (lon1 - lon2) * 100800)


def footprints(slug, duid_of):
    """Every massed footprint of a district: i (feature order), centroid, height, name, duid."""
    g = load_json(os.path.join(CE, slug, "buildings.geojson"))
    if not g:
        return None
    out = {}
    for i, f in enumerate(g["features"]):
        p = f.get("properties") or {}
        lon, lat = centroid(f["geometry"])
        out[i] = {"lon": lon, "lat": lat, "height_m": p.get("bHeight"), "name": (p.get("name") or "").strip() or None,
                  "duid": duid_of.get(i), "parcel_key": str(p.get("parcel_key") or "") or None,
                  "placeholder": bool(p.get("register_placeholder"))}
    return out


def is_sobha_name(name):
    n = (name or "").lower()
    return any(w in n for w in SOBHA_WORDS)


def main():
    spec = load_json(PROJECTS)
    projects = {p["project_number"]: p for p in spec["projects"]}
    con = duckdb.connect(GRAPH, read_only=True)
    pn_list = ",".join(str(n) for n in projects)

    pid_of = {int(n): int(i) for n, i in con.execute(
        "select project_number, project_id from gov_dld__projects where project_number in (%s)" % pn_list).fetchall()}
    pn_of_pid = {v: k for k, v in pid_of.items()}
    # register building counts, the cap on the geocode route (0 = villas / plots only: never geocoded)
    reg_buildings = {int(n): int(b or 0) for n, b in con.execute(
        "select project_number, no_of_buildings from gov_dld__projects where project_number in (%s)" % pn_list).fetchall()}
    # no register row yet (trading only, or CSV only): unknown, not zero - let the geocode route try one tower
    for pn, p in projects.items():
        if pn not in reg_buildings:
            reg_buildings[pn] = 1 if p.get("buildings") is None else int(p.get("buildings") or 0)

    # 1. register parcels per project
    parcels = defaultdict(set)
    for table in ("gov_dld__land_registry", "gov_dld__buildings", "gov_dld__units"):
        for pn, pk in con.execute(
                "select p.project_number, cast(cast(r.parcel_id as bigint) as varchar) from %s r join gov_dld__projects p using(project_id) "
                "where p.project_number in (%s) and r.parcel_id is not null" % (table, pn_list)).fetchall():
            parcels[int(pn)].add(pk)
    parcel_owner = {pk: pn for pn, pks in parcels.items() for pk in pks}

    slugs = sorted({s for s in AREA_SLUG.values() if s} | {s for v in EXTRA_SLUGS.values() for s in v})

    # 2. Municipality building ids per project from the key bridges
    dm_owner = {}
    for slug in slugs:
        for r in (load_json(os.path.join(BOARD, "key_bridge_%s.json" % slug), {}) or {}).get("buildings_list") or []:
            if isinstance(r, dict) and r.get("dm_building_id"):
                try:
                    pn = pn_of_pid.get(int(r.get("dld_project_id") or 0))
                except ValueError:
                    pn = None
                if pn:
                    dm_owner[str(int(r["dm_building_id"]))] = pn

    # 3. sub-community members (radius route), sub-community = the project itself
    # A card's project key is the register project_id; a project the register snapshot has not caught up with yet
    # (SkyParks, Sobha Central - registered 2026, CSV only) is matched by its exact name instead.
    sub_members = defaultdict(lambda: defaultdict(set))   # slug -> project_number -> {(dist_m, duid)}
    pn_of_name = {(p.get("name_en") or "").strip().lower(): pn for pn, p in projects.items() if p.get("name_en")}
    for pid, name, slug, duid, dist in con.execute(
            "select replace(s.project, 'prj:', ''), s.name, b.district, b.duid, coalesce(b.dist_m, 1e9) from sub_community s join sub_community_building b using(sub_id) "
            "where lower(s.name) like '%sobha%'").fetchall():
        pn = None
        try:
            pn = pn_of_pid.get(int(pid))
        except (ValueError, TypeError):
            pass
        pn = pn or pn_of_name.get((name or "").strip().lower())
        if pn:
            sub_members[slug][pn].add((float(dist), duid))

    # 4. Google points, refused when one point serves more than one project (a community centroid)
    geo = load_json(GEOCODE, {}) or {}
    goog = {}
    for pn, p in projects.items():
        nm = (p.get("name_en") or "").strip().lower()
        if not nm:
            continue
        usable = {k: v for k, v in geo.items() if k.startswith("goog::") and isinstance(v, dict) and v.get("lon") is not None}
        keys = [k for k in usable if k[6:].lower().startswith(nm)] or [k for k in usable if nm in k.lower()]
        if keys:
            goog[pn] = (geo[keys[0]]["lon"], geo[keys[0]]["lat"], keys[0])
    point_users = defaultdict(list)
    for pn, (lon, lat, _) in goog.items():
        point_users[(round(lon, 5), round(lat, 5))].append(pn)
    ambiguous = {pn for users in point_users.values() if len(users) > 1 for pn in users}

    duid_by_slug = defaultdict(dict)
    for slug, i, duid in con.execute("select district, footprint_i, duid from building where footprint_i is not null").fetchall():
        duid_by_slug[slug][int(i)] = duid

    coverage = {pn: {"project_number": pn, "name": p.get("name_en"), "area": p.get("area"), "status": p.get("status"),
                     "units": p.get("units"), "register_buildings": reg_buildings.get(pn), "parcels": len(parcels.get(pn) or ()),
                     "footprints": 0, "methods": set(), "districts": set()} for pn, p in projects.items()}
    districts, gaps, fps_by_slug = {}, [], {}
    for slug in slugs:
        fps = footprints(slug, duid_by_slug.get(slug, {}))
        fps_by_slug[slug] = fps
        if fps is None:
            gaps.append({"district": slug, "why": "no data/ce/<slug>/buildings.geojson - district not massed"})
            continue
        stack = (load_json(os.path.join(BOARD, "stack_%s.json" % slug), {}) or {}).get("buildings_by_id") or {}
        unitmix = (load_json(os.path.join(BOARD, "unitmix_%s.json" % slug), {}) or {}).get("buildings_by_id") or {}
        by_i = {}

        def take(i, pn, method, extra=None):
            if i in by_i:
                return
            by_i[i] = {"project_number": pn, "name": projects[pn].get("name_en"), "method": method,
                       "footprint_name": fps[i]["name"], "height_m": fps[i]["height_m"], **(extra or {})}

        # exact routes: parcel key or DM building id already on the footprint
        for i in fps:
            s = stack.get(str(i)) or {}
            u = unitmix.get(str(i)) or {}
            pk = str((s.get("plot") or {}).get("key") or "") or str((u.get("dld") or {}).get("parcel") or "").split(".")[0] or (fps[i]["parcel_key"] or "")
            dm = str(s.get("dm") or "") or str((u.get("dm") or {}).get("dm_building_id") or "")
            # a footprint named for another building is that building, even on a shared plot (Verde by Sobha's parcel
            # also carries Mazaya BB-2, a finished 180 m tower; Verde is the unnamed site beside it)
            if fps[i]["name"] and not is_sobha_name(fps[i]["name"]):
                continue
            if pk and pk in parcel_owner:
                take(i, parcel_owner[pk], "parcel", {"tallest": bool((s.get("plot") or {}).get("tallest")) if s else None,
                                                     "register_placeholder": fps[i]["placeholder"]})
            elif dm and dm in dm_owner:
                take(i, dm_owner[dm], "dm")
        reached = {v["project_number"] for v in by_i.values()}

        # radius route
        # 24 Sep 2026 (Seahaven): a sub-community card's radius is a circle, and in Dubai Harbour it swept up Princess Tower,
        # Emirates Crown, Ciel, the Marriott and a mosque for Seahaven Tower B & C. Two guards:
        #   - a footprint that carries a building name which is not a Sobha name is somebody else's building;
        #   - when a sister project of the same master project already has its site here by parcel or DM, the circle is not
        #     needed: the site is known, and the sister's footprint is it.
        inv = {d: i for i, d in duid_by_slug.get(slug, {}).items()}
        site_masters = {(projects[v["project_number"]].get("master_project") or "").strip().lower()
                        for v in by_i.values() if v["method"] in ("parcel", "dm")} - {""}
        for pn, duids in sub_members.get(slug, {}).items():
            if pn in reached:
                continue
            if (projects[pn].get("master_project") or "").strip().lower() in site_masters:
                continue
            # the circle holds the project AND its neighbours (SkyParks: 1 register building, 26 footprints in the circle):
            # the project is the register's building count of footprints nearest the card's centre
            cap = reg_buildings.get(pn) or 1
            n_taken = 0
            for dist, d in sorted(duids):
                if n_taken >= cap:
                    break
                if d in inv and inv[d] not in by_i:
                    nm = fps[inv[d]]["name"]
                    if nm and not is_sobha_name(nm):
                        continue
                    take(inv[d], pn, "radius", {"dist_m": round(dist)}); n_taken += 1
        reached = {v["project_number"] for v in by_i.values()}

        # geocode route, towers only, guarded
        for pn, p in projects.items():
            home = [AREA_SLUG.get(p.get("area"))] + EXTRA_SLUGS.get(p.get("area"), [])
            if slug not in home or pn in reached or pn not in goog or pn in ambiguous or reg_buildings.get(pn, 0) < 1:
                continue
            lon, lat, key = goog[pn]
            cand = []
            for i, f in fps.items():
                if i in by_i or (f["height_m"] or 0) < TOWER_MIN_M:
                    continue
                if f["name"] and not is_sobha_name(f["name"]):
                    continue
                d = dist_m(lon, lat, f["lon"], f["lat"])
                if d <= GEOCODE_RADIUS_M:
                    cand.append((-(f["height_m"] or 0), d, i))
            for _, d, i in sorted(cand)[:reg_buildings[pn]]:
                take(i, pn, "geocode", {"dist_m": round(d), "geocode_key": key})

        for i, v in by_i.items():
            c = coverage[v["project_number"]]
            c["footprints"] += 1; c["methods"].add(v["method"]); c["districts"].add(slug)
        districts[slug] = {"n": len(by_i), "i": sorted(by_i),
                           "duid": sorted(d for d in (fps[i]["duid"] for i in by_i) if d),
                           "by_i": {str(i): by_i[i] for i in sorted(by_i)}}

    for pn, p in projects.items():
        slug = AREA_SLUG.get(p.get("area"), "?")
        if slug is None:
            gaps.append({"project_number": pn, "name": p.get("name_en"), "area": p.get("area"), "why": "area not massed in the twin - no district slug"})
        elif coverage[pn]["footprints"] == 0:
            if reg_buildings.get(pn, 0) == 0:
                why = "villas / plots only - no tower to mask; needs a parcel-polygon route"
            elif pn in ambiguous:
                why = "Google point shared with another project (community centroid), refused"
            elif pn in goog and fps_by_slug.get(slug):
                lon, lat, _ = goog[pn]
                near = min(dist_m(lon, lat, f["lon"], f["lat"]) for f in fps_by_slug[slug].values())
                why = ("nothing massed where it stands - nearest footprint %d m from the Google point (site not in OSM yet)" % near
                       if near > GEOCODE_RADIUS_M else "no tower >= %d m unnamed within %d m of the Google point" % (TOWER_MIN_M, GEOCODE_RADIUS_M))
            else:
                why = "no footprint reached (parcels %d, no Google point)" % coverage[pn]["parcels"]
            gaps.append({"project_number": pn, "name": p.get("name_en"), "area": p.get("area"), "district": slug, "why": why})

    cov = sorted(coverage.values(), key=lambda c: c["project_number"])
    for c in cov:
        c["methods"] = sorted(c["methods"]); c["districts"] = sorted(c["districts"])
    methods = ("parcel", "dm", "radius", "geocode")
    out = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "developer": "sobha",
        "rule": "projects = data/identity/sobha_projects.json (register developer_number in the accepted Sobha group). "
                "Footprint routes, surest first: parcel, dm, radius, geocode - method says which, and the client should draw geocode dimmer.",
        "totals": {"projects": len(projects), "projects_reached": sum(1 for c in cov if c["footprints"]),
                   "footprints": sum(d["n"] for d in districts.values()),
                   "by_method": {m: sum(1 for d in districts.values() for v in d["by_i"].values() if v["method"] == m) for m in methods}},
        "projects": cov, "districts": districts, "gaps": gaps,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    t = out["totals"]
    print("Sobha mask: %d of %d projects reached, %d footprints (%s)" % (
        t["projects_reached"], t["projects"], t["footprints"], ", ".join("%s %d" % kv for kv in t["by_method"].items())))
    for slug, d in sorted(districts.items()):
        print("  %-22s %4d  %s" % (slug, d["n"], "; ".join(sorted({v["name"] or "?" for v in d["by_i"].values()}))[:120]))
    print("projects:")
    for c in cov:
        print("  %5d %-36s %-26s bldgs %2s parcels %3d  footprints %3d  %s" % (
            c["project_number"], (c["name"] or "?")[:36], (c["area"] or "")[:26], c["register_buildings"], c["parcels"], c["footprints"], ",".join(c["methods"])))
    print("gaps (%d):" % len(gaps))
    for g in gaps:
        print("   %s" % json.dumps(g, ensure_ascii=False))
    print("-> %s (%d KB)" % (OUT, os.path.getsize(OUT) // 1024))
    if "--push" in sys.argv:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_avail_index import env_token, push
        print("   devmask_sobha ->", push("devmask_sobha", out, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
