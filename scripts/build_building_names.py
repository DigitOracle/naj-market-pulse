"""build_building_names.py -- a name for every DM building in a community, without a single name match.

Asked for on 20 Sep 2026: DAMAC Hills has 1,006 footprints and one of them is named, while Business Bay has 228. The names do
exist in the registers, just never against a building: the DLD LAND REGISTRY carries project_name_en per plot and a DM parcel_id,
and the DLD UNITS register carries project_name_en against parent_property_id (the building). So:

    DM building --parcel_key--> land registry parcel_id --> project_name_en        (villas and plots: the cluster name)
    DLD unit --parent_property_id--> DLD building property_id --> project_name_en  (apartment buildings: the tower name)

Al Hebiah Third (DAMAC Hills): 2,593 of 2,934 DM buildings (88%) reach a name this way, across 41 clusters - Silver Springs,
Piccadilly Green, Pelham, Rockwood, Topanga, Rochester and the rest. For a villa the cluster name IS the name a buyer uses.

    python scripts/build_building_names.py                      # Business Bay (346) and DAMAC Hills (676)
    python scripts/build_building_names.py --community 683 --slug damac_hills_2

Writes data/board/names_<slug>.json:
    {"community": {...}, "buildings": [{building_id, parcel_key, name, source, building_type, plot_code, floors, units}], ...}
`source` is always stated: "land_registry_parcel" or "units_parent_property". Nothing here is a name match; every row is an id join.
"""
import argparse, collections, datetime as dt, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lake import connect  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
LAND = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_land_registry-open-api.json")
DISTRICTS = [(346, "business_bay", "Business Bay"), (676, "damac_hills", "Al Hebiah Third (DAMAC Hills)")]


def land_names(area_names):
    """parcel_id -> project_name_en, and land_number -> (name, plot reference), from the DLD land registry."""
    rows = json.load(io.open(LAND, encoding="utf-8"))["results"]
    by_parcel = {}
    for r in rows:
        if area_names and (r.get("area_name_en") or "") not in area_names:
            continue
        nm = (r.get("project_name_en") or "").strip()
        if not nm:
            continue
        pid = r.get("parcel_id")
        if pid:
            try: by_parcel[str(int(float(pid)))] = nm
            except Exception: pass
    return by_parcel


def build(con, comm, slug, label):
    area = con.execute("select distinct community_name from lk_dm_buildings where comm_num = ?", [comm]).fetchall()
    dld_area = con.execute("select any_value(area_name_en) from lk_d_building where comm_num = ?", [comm]).fetchone()[0]
    by_parcel = land_names({dld_area} if dld_area else set())
    # the units register names a BUILDING directly, which is what an apartment tower needs
    by_bld = {}
    try:
        for b, nm in con.execute("""select cast(parent_property_id as varchar), any_value(project_name_en) from g_dld__units
                                    where parent_property_id is not null and project_name_en is not null group by 1""").fetchall():
            by_bld[b] = nm
    except Exception:
        pass                                            # units not in the lake yet: parcel naming still works
    plot = {}
    for pk, num in con.execute("select cast(parcel_key as varchar), any_value(building_number) from lk_d_building "
                               "where comm_num = ? and building_number is not null group by 1", [comm]).fetchall():
        plot[pk] = num
    rows = con.execute("""select b.building_id, cast(b.parcel_key as varchar), b.building_type, b.typical_floors, b.status
                          from lk_dm_buildings b where b.comm_num = ?""", [comm]).fetchall()
    out, named = [], 0
    for bid, pk, btype, floors, status in rows:
        name, src = by_bld.get(str(bid)), "units_parent_property"
        if not name:
            name, src = by_parcel.get(pk), "land_registry_parcel"
        if not name:
            src = None
        else:
            named += 1
        out.append({"building_id": bid, "parcel_key": pk, "name": name, "source": src, "building_type": btype,
                    "plot_code": plot.get(pk), "typical_floors": floors, "status": status})
    doc = {"community": {"comm_num": comm, "name": label, "dld_area": dld_area},
           "generated": dt.datetime.now().isoformat(timespec="seconds"),
           "buildings": len(out), "named": named,
           "distinct_names": len({r["name"] for r in out if r["name"]}),
           "sources": {"land_registry_parcel": "DLD land registry project_name_en, joined by DM parcel_id -> parcel_key",
                       "units_parent_property": "DLD units project_name_en, joined by parent_property_id -> building"},
           "note": "Every name here is an ID join, never a name match. For villa clusters the project name IS the name buyers use "
                   "(a Rockwood villa); it is not a unique building name, so show it as the cluster and keep the plot_code for the plot.",
           "buildings_list": out}
    os.makedirs(BOARD, exist_ok=True)
    p = os.path.join(BOARD, "names_%s.json" % slug)
    json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("%-32s %5d buildings, %5d named (%.0f%%), %3d distinct names -> %s"
          % (label, len(out), named, 100.0 * named / max(len(out), 1), doc["distinct_names"], os.path.relpath(p, ROOT)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--community", type=int); ap.add_argument("--slug"); ap.add_argument("--label")
    a = ap.parse_args()
    con = connect()
    todo = [(a.community, a.slug or str(a.community), a.label or str(a.community))] if a.community else DISTRICTS
    for comm, slug, label in todo:
        build(con, comm, slug, label)


if __name__ == "__main__":
    main()
