"""build_tapcards.py -- an interim "tap any building, get its card" table, one JSON per footprint set (1 Oct 2026).

Why. The city model draws ~372,000 building footprints (45 app districts in data/ce/<slug>/blocks.json, 205 DM communities in
data/blocks_city/<slug>/blocks.json) but no plot polygons exist on disk, so a footprint cannot be joined to the registers by
geometry. Until GeoDubai 2165 lands (docs/DM_PARCEL_CROSSWALK_REQUEST_DRAFT.md, ask c) every footprint still gets a card:

  tier community  every footprint: its DM community (centroid in the community polygon), with the community's facts
  tier plot       the footprint's plot is known (LOD 3 point-in-footprint join, data/lab/joins/plot_footprint_<slug>.json)
                  but the plot holds several buildings - plot facts only, never a guessed building
  tier building   one building is identified: the twin binding register (name/structure/geocode match -> DLD property_id),
                  or a plot with exactly ONE Municipality building, or a named footprint whose name is a DLD project with one
                  registered building

Every row carries match_method and confidence, the centroid (6 dp) and area (m2, 1 dp) so a footprint can be re-bound if its
index moves after a rebuild, and the Makani numbers LOD 3 bound to it (makani_footprint_<slug>.json) for DEWA later.

Output: data/tapcards/tapcard_<slug>.json  {as_of, source, fields, rows: {"<i>": {...}}}        files only, nothing published
    python scripts/build_tapcards.py [slug ...]
"""
import glob, json, os, re, sys, time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "tapcards")
import lake
from keys import comm_of_key, name_norm
from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from shapely.ops import transform as sh_transform
from pyproj import Transformer

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
AS_OF = time.strftime("%Y-%m-%d")

FIELDS = ["i", "lon", "lat", "area_m2", "tier", "match_method", "confidence", "comm_num", "community", "community_population",
          "community_dewa_move_ins", "community_bus_coverage_pct", "community_parcels", "community_register_buildings",
          "community_register_units", "community_dm_buildings", "parcel_key", "plot_buildings_dm", "plot_buildings_dld",
          "plot_units", "plot_land_type", "dm_building_id", "dld_property_id", "name", "project", "project_number",
          "developer", "floors", "height_m", "units", "flats", "offices", "shops", "built_up_area", "completion", "usage",
          "building_type", "status", "makani", "footprint_name", "footprint_height_m", "footprint_height_source"]


def load_sets():
    sets = {}
    for base in ("ce", "blocks_city"):
        for p in glob.glob(os.path.join(ROOT, "data", base, "*", "blocks.json")):
            sets[os.path.basename(os.path.dirname(p))] = (base, p)
    return sets


def communities():
    g = json.load(open(os.path.join(ROOT, "data", "board", "communities.geojson"), encoding="utf-8"))
    polys, nums = [], []
    for f in g["features"]:
        polys.append(shape(f["geometry"])); nums.append(int(f["properties"]["comm_num"]))
    return STRtree(polys), polys, nums


def lab(slug, kind):
    p = os.path.join(ROOT, "data", "lab", "joins", "%s_footprint_%s.json" % (kind, slug))
    if not os.path.exists(p):
        return {}
    return {int(r["i"]): r for r in json.load(open(p, encoding="utf-8"))["rows"]}


def anchors(slug):
    """The app's own building names per footprint (data/names/anchors_<slug>.json: id == footprint i). A VERIFIED name is the
    strongest identity we hold - Kendall confirmed JVC 1503 = Binghatti Amber from it, where a located plot point put the
    same footprint on Binghatti Circle's plot."""
    p = os.path.join(ROOT, "data", "names", "anchors_%s.json" % slug)
    if not os.path.exists(p):
        return {}
    out = {}
    for a in json.load(open(p, encoding="utf-8")).get("anchors", []):
        if a.get("name") and a.get("id") is not None:
            try:
                out[int(a["id"])] = (a["name"], a.get("identity_grade"), a.get("source"))
            except (TypeError, ValueError):
                pass
    return out


def lake_facts(con):
    f = {}
    f["comm"] = {r[0]: r for r in con.execute("""
        select c.comm_num, coalesce(c.name_en, k.dm_name_en), c.population, c.dewa_move_ins, c.bus_coverage_pct, c.parcels,
               c.register_buildings, c.register_units, c.dm_buildings
        from lk_d_community c left join lk_community k on k.comm_num = c.comm_num""").fetchall()}
    f["parcel"] = {r[0]: r for r in con.execute(
        "select parcel_key, dm_buildings, register_buildings, register_units, land_type, project_id from lk_d_parcel").fetchall()}
    # the ONE Municipality building on a single-building plot
    f["dm_single"] = {r[0]: r for r in con.execute("""
        select b.parcel_key, b.building_id, b.height_m, b.typical_floors, b.completion_date, b.usages, b.building_type, b.status,
               b.total_area_sqm
        from lk_dm_buildings b join lk_d_parcel p on p.parcel_key = try_cast(b.parcel_key as bigint) where p.dm_buildings = 1""").fetchall()}
    f["dld_single"] = {r[0]: r for r in con.execute("""
        select b.parcel_key, b.property_id from lk_d_building b join lk_d_parcel p on p.parcel_key = b.parcel_key
        where p.register_buildings = 1""").fetchall()}
    f["dld_bld"] = {r[0]: r for r in con.execute("""
        select b.property_id, b.parcel_key, b.project_id, b.floors, b.flats, b.offices, b.shops, b.built_up_area, b.creation_date,
               b.property_sub_type, b.master_project_en, b.building_number
        from lk_d_building b""").fetchall()}
    f["project"] = {r[0]: r for r in con.execute("""
        select p.project_id, p.name_en, p.project_number, d.name_en developer, p.completion_date, p.status, p.registered_units
        from lk_d_project p left join lk_d_developer d on d.developer_number = p.developer_number""").fetchall()}
    f["project_by_name"] = {}
    for pid, r in f["project"].items():
        if r[1]:
            f["project_by_name"].setdefault(name_norm(r[1]), []).append(pid)
    f["bridge"] = {}
    for dm, pid in con.execute("select dm_building_id, min(property_id) from lk_key_bridge_pairs group by 1").fetchall():
        f["bridge"][str(dm)] = pid
    # property_id and parcel_key are VARCHAR in the register; a footprint can carry several candidates (1503 in JVC is bound
    # to both "Binghatti Amber" and "Binghatti Amberhall") - name matches outrank geocodes, and 2+ distinct candidates lower
    # the confidence rather than being hidden
    f["twin"] = {}
    for d, i, pid, pk, method, rname, proj, n_cand in con.execute("""
        select district, footprint_i, try_cast(property_id as bigint), try_cast(try_cast(parcel_key as double) as bigint), method,
               register_name, project, count(distinct property_id) over (partition by district, footprint_i)
        from lk_twin_binding_register
        qualify row_number() over (partition by district, footprint_i
                                   order by case method when 'name match' then 0 when 'structure match' then 1 else 2 end, rank) = 1""").fetchall():
        f["twin"][(d, int(i))] = (pid, pk, method, rname, proj, n_cand)
    # a project with exactly one registered building: naming the project names the building
    f["project_single_bld"] = {r[0]: r[1] for r in con.execute("""
        select project_id, min(property_id) from lk_d_building where project_id is not null group by 1 having count(*) = 1""").fetchall()}
    return f


def card_for_project(f, pid, row):
    prj = f["project"][pid]
    row["name"] = row.get("name") or prj[1]; row["project"] = prj[1]; row["project_number"] = prj[2]; row["developer"] = prj[3]
    row["units"] = prj[6]; row["status"] = prj[5]
    row["completion"] = prj[4].isoformat() if hasattr(prj[4], "isoformat") else (prj[4] and str(prj[4]))
    b = f["project_single_bld"].get(pid)
    if b:
        card_for_dld(f, b, row)
    return b is not None


def card_for_dld(f, pid, row):
    b = f["dld_bld"].get(pid)
    if not b:
        return
    row["dld_property_id"] = pid
    row["floors"] = b[3]; row["flats"] = b[4]; row["offices"] = b[5]; row["shops"] = b[6]; row["built_up_area"] = b[7]
    row["completion"] = b[8].isoformat() if b[8] else None
    row["building_type"] = b[9]
    if b[1] and row.get("parcel_key") is None:
        row["parcel_key"] = b[1]
    pr = f["project"].get(b[2]) if b[2] else None
    if pr:
        row["project"] = pr[1]; row["project_number"] = pr[2]; row["developer"] = pr[3]
        row["units"] = pr[6]
        if row.get("name") is None:
            row["name"] = pr[1]
        if row.get("completion") is None and pr[4]:
            row["completion"] = pr[4].isoformat() if hasattr(pr[4], "isoformat") else str(pr[4])
        row["status"] = row.get("status") or pr[5]
    elif b[10] and row.get("name") is None:
        row["name"] = b[10]


def card_for_dm(f, pk, row):
    d = f["dm_single"].get(pk)
    if not d:
        return False
    row["dm_building_id"] = d[1]; row["height_m"] = d[2]; row["floors"] = row.get("floors") or d[3]
    row["completion"] = d[4].isoformat() if hasattr(d[4], "isoformat") else (d[4] or row.get("completion"))
    row["usage"] = d[5]; row["building_type"] = row.get("building_type") or d[6]; row["status"] = d[7]
    row["built_up_area"] = row.get("built_up_area") or d[8]
    pid = f["bridge"].get(str(d[1]))
    if pid:
        card_for_dld(f, pid, row)
    return True


def plot_facts(f, pk, row):
    p = f["parcel"].get(pk)
    if not p:
        return False
    row["parcel_key"] = pk; row["plot_buildings_dm"] = p[1]; row["plot_buildings_dld"] = p[2]; row["plot_units"] = p[3]
    row["plot_land_type"] = p[4]
    pr = f["project"].get(p[5]) if p[5] else None
    if pr and row.get("project") is None:
        row["project"] = pr[1]; row["project_number"] = pr[2]; row["developer"] = pr[3]
    return True


def build(slug, base, path, tree, polys, nums, f):
    d = json.load(open(path, encoding="utf-8"))
    plots, makanis, anchor_names = lab(slug, "plot"), lab(slug, "makani"), anchors(slug)
    rows, tiers, methods = {}, Counter(), Counter()
    for feat in d["features"]:
        pr = feat.get("properties") or {}
        if pr.get("k") != "b":
            continue
        i = int(pr["i"])
        try:
            geom = shape(feat["geometry"])
        except Exception:
            continue
        c = geom.representative_point() if not geom.is_valid else geom.centroid
        try:
            area = round(sh_transform(TO_UTM, geom).area, 1)
        except Exception:
            area = None
        row = {k: None for k in FIELDS}
        row.update({"i": i, "lon": round(c.x, 6), "lat": round(c.y, 6), "area_m2": area, "footprint_name": pr.get("n"),
                    "footprint_height_m": pr.get("h"), "footprint_height_source": pr.get("hs")})
        hits = [k for k in tree.query(Point(c.x, c.y)) if polys[k].contains(Point(c.x, c.y))]
        comm = nums[hits[0]] if hits else None
        if comm is None and slug in f["slug_comm"]:          # blocks_city folders are one DM community each
            comm = f["slug_comm"][slug]
        row["comm_num"] = comm
        cf = f["comm"].get(comm) if comm is not None else None
        if cf:
            row.update({"community": cf[1], "community_population": cf[2], "community_dewa_move_ins": cf[3],
                        "community_bus_coverage_pct": cf[4], "community_parcels": cf[5], "community_register_buildings": cf[6],
                        "community_register_units": cf[7], "community_dm_buildings": cf[8]})
        mk = makanis.get(i)
        if mk:
            row["makani"] = mk.get("makani")
        tier, method, conf = "community", "centroid in DM community polygon", 1.0 if comm is not None else 0.0

        tw = f["twin"].get((slug, i))
        lp = plots.get(i)
        pk = int(lp["parcel_key"]) if lp and not lp.get("ambiguous") and lp.get("parcel_key") else None
        an = anchor_names.get(i)
        an_pids = f["project_by_name"].get(name_norm(an[0]), []) if an else []
        fn_pids = f["project_by_name"].get(name_norm(pr["n"]), []) if pr.get("n") else []
        if tw and tw[2] == "name match" and tw[0] in f["dld_bld"]:
            row["name"] = tw[3] or tw[4]
            if tw[1] is not None:
                plot_facts(f, tw[1], row)
            card_for_dld(f, tw[0], row)
            tier, method, conf = "building", "twin binding register: name match", 0.9
            if tw[5] > 1:
                method += " (%d candidate buildings, best shown)" % tw[5]; conf = 0.65
        elif len(an_pids) == 1:
            row["name"] = an[0]
            one = card_for_project(f, an_pids[0], row)
            tier = "building" if one else "project"
            method = "app anchor name (%s) = DLD project%s" % (an[1] or an[2] or "unverified", "" if one else "; project has several buildings")
            conf = (0.85 if an[1] == "VERIFIED" else 0.7) * (1.0 if one else 0.9)
            if pk is not None and f["parcel"].get(pk) and f["parcel"][pk][5] not in (None, an_pids[0]):
                method += "; a located plot point disagrees (plot %d)" % pk; conf = round(conf * 0.8, 2)
            elif pk is not None:
                plot_facts(f, pk, row)
        elif pk is not None and plot_facts(f, pk, row):
            if card_for_dm(f, pk, row):
                tier, method, conf = "building", "located plot point in footprint; plot holds one DM building", 0.85
            elif pk in f["dld_single"]:
                card_for_dld(f, f["dld_single"][pk][1], row)
                tier, method, conf = "building", "located plot point in footprint; plot holds one DLD building", 0.8
            else:
                tier, method, conf = "plot", "located plot point in footprint; plot holds several buildings", 0.7
            if an and not an_pids:
                row["name"] = row.get("name") or an[0]
        elif tw and tw[0] in f["dld_bld"]:
            row["name"] = tw[3] or tw[4]
            if tw[1] is not None:
                plot_facts(f, tw[1], row)
            card_for_dld(f, tw[0], row)
            tier, method = "building", "twin binding register: %s" % tw[2]
            conf = 0.8 if tw[2] == "structure match" else 0.6
            if tw[5] > 1:
                method += " (%d candidate buildings, best shown)" % tw[5]; conf = round(conf * 0.7, 2)
        elif len(fn_pids) == 1:
            one = card_for_project(f, fn_pids[0], row)
            tier = "building" if one else "project"
            method, conf = "footprint name = DLD project name (exact, normalised)", 0.7 if one else 0.65
        else:
            row["name"] = (an[0] if an else None) or pr.get("n")
        row["tier"], row["match_method"], row["confidence"] = tier, method, conf
        rows[str(i)] = row
        tiers[tier] += 1; methods[method] += 1
    out = {"as_of": AS_OF, "slug": slug, "footprint_set": "data/%s/%s/blocks.json" % (base, slug),
           "source": "footprints: the set named; communities: data/board/communities.geojson; registers: lake lk_d_community, "
                     "lk_d_parcel, lk_d_building, lk_dm_buildings, lk_d_project, lk_d_developer, lk_key_bridge_pairs, "
                     "lk_twin_binding_register; points: data/lab/joins (LOD 3, 1 Oct 2026)",
           "fields": FIELDS, "tiers": dict(tiers), "rows": rows}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "tapcard_%s.json" % slug), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), default=str)
    return tiers, methods, len(rows)


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    sets = load_sets()
    con = lake.connect(read_only=True)
    f = lake_facts(con)
    # a blocks_city folder is one DM community: its meta names the community number
    f["slug_comm"] = {}
    for slug, (base, path) in sets.items():
        if base == "blocks_city":
            meta = json.load(open(path, encoding="utf-8")).get("meta", {})
            m = re.search(r"community (\d+)", json.dumps(meta))
            if m:
                f["slug_comm"][slug] = int(m.group(1))
    tree, polys, nums = communities()
    total, tiers_all, methods_all, per_set = 0, Counter(), Counter(), Counter()
    t0 = time.time()
    for slug, (base, path) in sorted(sets.items()):
        if want and slug not in want:
            continue
        tiers, methods, n = build(slug, base, path, tree, polys, nums, f)
        total += n; tiers_all += tiers; methods_all += methods; per_set[base] += n
        print("%-28s %-11s %7d rows  %s" % (slug, base, n, ", ".join("%s %d" % kv for kv in sorted(tiers.items()))), flush=True)
    print("\n%d footprints in %d sets (%s) - %.0fs" % (total, len(sets), ", ".join("%s %d" % kv for kv in per_set.items()), time.time() - t0))
    for k, v in tiers_all.most_common():
        print("  tier %-10s %8d" % (k, v))
    for k, v in methods_all.most_common():
        print("  %8d  %s" % (v, k))


if __name__ == "__main__":
    main()
