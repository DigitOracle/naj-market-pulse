"""Level A without a Revit model: the DLD units register, one row per unit, placed on its floor.

The Symphony viewer knows where every flat is because we built the tower in Revit. For everything else the nearest honest thing
is the register's own unit rows: unit number, its floor, its area, its type. That turns the building page from "the register puts
2-beds somewhere on floors 8-62" into "floor 34 holds 14 homes: 3402 is a 1-bed of 981 sq ft". It still is not a position on the
plate - which side of the corridor a flat sits on is not published - and the page must keep saying so.

  unit row --parent_property_id--> DLD building property_id == unitmix_<district>.buildings_by_id[i].dld.property_id --> footprint i

  python scripts/build_unit_level.py <units-file> businessbay damachills   -> data/board/units_<district>.json
  --push        publish each district (KV units_<district>)
  --min-cover N only keep a building whose unit rows cover at least N% of its registered units (default 80)

Coverage is the point of the guard: a building the pull covered only half of would show half its homes as if that were all of
them. Those buildings stay at floor level, and the file records why.

What the register can and cannot reach (DDA session, measured on all 2,374,092 units, 21 Sep 2026):
  53%  carry a 9-10 digit parent_property_id that meets the DLD building register - the family this script joins on
  38%  carry NO parent at all: land and villa plots, where the unit IS the property
  10%  carry a 13-DIGIT parent (1001794636716) belonging to 4,340 "buildings" that are in no building register - a newer or
       off-plan id space. Those can never meet a footprint here, and are counted and reported rather than silently dropped.
Business Bay and Al Hebiah Third are the good end of that: 95,808 of their 98,634 rows (97%) carry a usable parent. Another
district may sit at half, and its buildings will fall back to floor level - that is the guard working, not a fault.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_floor_stack import json_rows, num, type_key           # the same streaming reader and type vocabulary

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
MIN_COVER = 80.0


def wanted_buildings(districts):
    """{property_id -> (district, footprint id, registered units, name)} for every register-bound building we draw."""
    out = {}
    for d in districts:
        p = os.path.join(BOARD, "unitmix_%s.json" % d)
        if not os.path.exists(p):
            continue
        for i, r in json.load(open(p, encoding="utf-8"))["buildings_by_id"].items():
            pid = (r.get("dld") or {}).get("property_id")
            if not pid or r.get("status") not in ("verified", "partial"):
                continue
            out[str(pid)] = (d, i, int(r.get("total_units") or (r.get("dld") or {}).get("units_registered") or 0), r.get("name"))
    return out


def floor_of(row):
    """The register's floor for a unit. It is a storey number, but it arrives as a string and sometimes as G / M / P."""
    f = row.get("floor")
    if f is None or f == "":
        return None
    s = str(f).strip().upper()
    if s in ("G", "GF", "GROUND"):
        return 0
    n = num(s)
    return int(n) if n is not None and -5 <= n <= 200 else None


def build(units_file, districts, min_cover, tok):
    want = wanted_buildings(districts)
    print("%d register-bound buildings to look for, across %s" % (len(want), ", ".join(districts)))
    held, seen, no_floor, no_parent, far_id, t0 = {}, 0, 0, 0, 0, time.time()
    for row in json_rows(units_file):
        pid = row.get("parent_property_id")
        key = str(int(pid)) if isinstance(pid, (int, float)) else str(pid or "")
        if not key or key == "None":
            no_parent += 1
            continue
        if len(key) >= 12:
            far_id += 1                 # the 13-digit family: no building register row exists for it, here or anywhere
            continue
        if key not in want:
            continue
        seen += 1
        fl = floor_of(row)
        if fl is None:
            no_floor += 1
            continue
        t = row.get("rooms_en") or row.get("rooms") or ""
        held.setdefault(key, {}).setdefault(fl, []).append({
            "u": str(row.get("unit_number") or "").strip(),
            "t": t, "c": type_key(t),
            "sqft": round((num(row.get("actual_area")) or 0) * 10.764) or None,
            "bal": round((num(row.get("unit_balcony_area")) or 0) * 10.764) or None,
            "sub": row.get("property_sub_type_en") or None,
        })
    print("  %d unit rows for those buildings, %d with no usable floor; skipped %d rows with no parent and %d on 13-digit parents "
          "that meet no building register (%.0fs)" % (seen, no_floor, no_parent, far_id, time.time() - t0))
    out = {d: {} for d in districts}
    thin = []
    for key, floors in held.items():
        d, i, registered, name = want[key]
        n = sum(len(v) for v in floors.values())
        cover = 100.0 * n / registered if registered else 100.0
        if cover < min_cover:
            thin.append("%s %s (%d of %d rows, %.0f%%)" % (i, name, n, registered, cover))
            continue
        out[d][i] = {"name": name, "property_id": key, "units": n, "registered": registered, "cover": round(cover),
                     "floors": {str(k): sorted(v, key=lambda x: x["u"]) for k, v in sorted(floors.items())}}
    for d in districts:
        doc = {"district": d, "generated": time.strftime("%Y-%m-%d"),
               "source": "Dubai Land Department units register, one row per unit (property_id, parent_property_id, floor, "
                         "unit_number, actual_area, rooms_en)",
               "note": "A unit is placed on its floor, not on the plate: which side of the corridor it sits on is not published. "
                       "Only buildings whose rows cover at least %d%% of their registered units are here." % int(min_cover),
               "min_cover": int(min_cover), "buildings_by_id": out[d]}
        p = os.path.join(BOARD, "units_%s.json" % d)
        json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print("  -> %s: %d buildings at unit level, %d KB"
              % (os.path.relpath(p, ROOT), len(out[d]), os.path.getsize(p) // 1024))
        if tok:
            from build_avail_index import push
            print("     push units_%s -> %s" % (d, push("units_" + d, doc, tok).get("ok")))
    if thin:
        print("  left at floor level, too thinly covered to be honest: %d" % len(thin))
        for x in thin[:10]:
            print("    " + x)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    units_file, districts = args[0], (args[1:] or ["businessbay", "damachills"])
    if not os.path.exists(units_file):
        sys.exit("no units file at %s" % units_file)
    mc = float(sys.argv[sys.argv.index("--min-cover") + 1]) if "--min-cover" in sys.argv else MIN_COVER
    tok = None
    if "--push" in sys.argv:
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    build(units_file, districts, mc, tok)


if __name__ == "__main__":
    main()
