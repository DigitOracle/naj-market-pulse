"""Write data/board/key_bridge_<slug>.json, one per district, from lk_key_bridge in the truth store.

Why this exists (29 Sep 2026 audit). Four scripts read these files every day - bind_plans.py, build_project_index.py,
build_project_team.py, build_sobha_mask.py - and NOTHING in the repo wrote them. They were produced by hand on 22 Sep and
were 7.5 days old when the audit measured them, while the bldgfacts_* they sit beside refreshed daily. An input with a
consumer and no producer cannot go stale loudly: it just quietly stops matching the register underneath it. Measured on
the same day, the week-old files reported a DM-building reach of 21.7% where the freshly rebuilt bridge reports 43.1%.

Reads lk_key_bridge (published by register_joins.py key_bridge, which is now a daily step when the cuts go stale) and
writes one file per district on the twin's rail, in the shape the four consumers already expect: area, comm_num, columns,
buildings, with_parcel, on_dm_parcel, reached_by_units, note, buildings_list.

District selection follows the existing cuts: data/board/_district_cuts_index.json, else the slugs already on disk.
Usage:  python scripts/emit_key_bridge_cuts.py [--slug <slug> ...]
"""
import argparse, glob, io, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
NOTE = ("One canonical crosswalk per DLD property_id: its parcel, the DM buildings on that parcel, its project ids and whether "
        "the units register reaches it. source_parcel names HOW the parcel was reached and is never blended. n_dm_buildings > 1 "
        "means the plot holds several buildings (podium, services block, tower) - pick by floors or type, do not assume. A property "
        "with no parcel_key carries a DLD parcel number the Municipality register has never used; that is a real gap, not a lookup "
        "failure, and no join will close it.")


def districts():
    """The districts to cut: the cuts index if it is there, else whatever key_bridge/bldgfacts files already exist."""
    p = os.path.join(BOARD, "_district_cuts_index.json")
    out = {}
    try:
        idx = json.load(io.open(p, encoding="utf-8"))
        for d in (idx.get("districts") or idx if isinstance(idx, list) else idx.get("districts") or []):
            if isinstance(d, dict) and d.get("slug"):
                out[d["slug"]] = d.get("area") or d.get("area_name_en")
    except Exception:
        pass
    for f in glob.glob(os.path.join(BOARD, "key_bridge_*.json")) + glob.glob(os.path.join(BOARD, "bldgfacts_*.json")):
        s = os.path.basename(f).split("_", 1)[1][:-len(".json")]
        out.setdefault(s, None)
    return out


def area_for(con, slug, known):
    """The register's own area name for this slug: from the existing cut, else the district cut, else the slug itself."""
    if known:
        return known
    for name in ("key_bridge_%s.json" % slug, "dld_buildings_%s.json" % slug, "bldgfacts_%s.json" % slug):
        try:
            d = json.load(io.open(os.path.join(BOARD, name), encoding="utf-8"))
            if d.get("area"):
                return d["area"]
        except Exception:
            continue
    return None


def main():
    import lake                      # lk_* tables are lake-native (LAKE_NATIVE_PREFIXES), not in najma.duckdb
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", nargs="*", default=None)
    a = ap.parse_args()
    con = lake.connect()
    cols = [r[1] for r in con.execute("pragma table_info('lk_key_bridge')").fetchall()]
    if not cols:
        print("lk_key_bridge is not in the store - run: python scripts/register_joins.py key_bridge"); return 1
    want = districts()
    slugs = a.slug or sorted(want)
    made = skipped = 0
    for slug in slugs:
        area = area_for(con, slug, want.get(slug))
        if not area:
            print("  ! %-26s no area name on file - skipped (it names the register rows)" % slug); skipped += 1; continue
        rows = con.execute("select * from lk_key_bridge where lower(trim(area_name_en)) = lower(trim(?))", [area]).fetchall()
        if not rows:
            print("  ! %-26s 0 rows for area %r - skipped rather than writing an empty cut" % (slug, area)); skipped += 1; continue
        recs = [dict(zip(cols, r)) for r in rows]
        comm = next((r.get("comm_num") for r in recs if r.get("comm_num") is not None), None)
        doc = {"area": area, "comm_num": comm, "columns": cols, "buildings": len(recs),
               "with_parcel": sum(1 for r in recs if r.get("parcel_key")),
               "on_dm_parcel": sum(1 for r in recs if r.get("dm_building_id")),
               "reached_by_units": sum(1 for r in recs if (r.get("unit_rows") or 0) > 0),
               "note": NOTE, "buildings_list": recs}
        with io.open(os.path.join(BOARD, "key_bridge_%s.json" % slug), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, default=str)
        made += 1
        print("  %-26s %6d buildings · parcel %6d · DM %6d · units %6d" % (slug, doc["buildings"], doc["with_parcel"], doc["on_dm_parcel"], doc["reached_by_units"]))
    print("key_bridge cuts: %d written, %d skipped" % (made, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
