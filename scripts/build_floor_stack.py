"""The floor stack of every register-bound building in a district - what the Symphony viewer does for one tower, from the
registers for all of them (Kendall, 19 Sep 2026: "get all of the buildings ... to look and act like this whilst maintaining
revit and arcgis integrity").

The geometry is never touched. The twin draws each building from the CityEngine massing (ArcGIS footprints + heights), and
the viewer only cuts that mesh into floor bands with clipping planes. This file says what each band IS:

  footprint i (mesh index = unitmix key)  --dm_building_id-->  DM building_floor_level_information (every floor: its use,
  its units, its area)  +  DLD units register levels per type (which floors each unit type sits on)

Levels, said on the card:
  A  unit level   - a Revit model or a developer stacking plan (data/stack/<slug>_units.json; Symphony today)
  B  floor level  - the DM floor register on the building (basis "dm_floors")
     floor level  - no floor register, but the DM permit line (3B+G+89+1R) and the register's type levels (basis "dm_permit")
  C  massing      - no register binding: not in this file

A type on a floor means the DLD units register puts that type somewhere in that floor range - not a unit position. The
viewer says so. Unit positions exist only at level A.

  python scripts/build_floor_stack.py businessbay damachills        -> data/board/stack_<district>.json
  --floors <glob>   read the DM floor register from these files instead of the newest on disk
  --push            publish each district to the app's store (KV stack_<district>), as build_unit_mix.py does for the unit mix
"""
import csv, glob, json, os, re, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
# the DDA session writes these with its own slugs (business_bay, damac_hills), one per DM community
PARCEL_SLUG = {"businessbay": "business_bay", "damachills": "damac_hills"}
FLOORS_CSV = os.path.join(ROOT, "data", "raw_downloads", "building_floor_level_information_2026-08-31_*.csv")
FLOORS_DDA = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dm__dm_building_floor_level_information-open-api.*")
FLOORS_AS_OF = "31 Aug 2026"
MAX_FLOOR = 200            # Burj Khalifa is 163 storeys; anything past this is a data error, not a building
MAX_FLOOR_SQM = 100000     # a floor plate of 10 hectares is a data error too


def floor_files():
    """The DDA pull's merged export when it is finished (newest register), else the 31 Aug portal CSVs. A .part is mid-pull and
    is never read: half a register would quietly thin every stack."""
    dda = [p for p in sorted(glob.glob(FLOORS_DDA)) if p.endswith(".ndjson") or p.endswith(".json")]
    if dda:
        newest = max(dda, key=os.path.getmtime)
        return [newest], "the DDA pull, " + time.strftime("%d %b %Y", time.localtime(os.path.getmtime(newest)))
    return sorted(glob.glob(FLOORS_CSV)), FLOORS_AS_OF

# one use per floor, in the words the card uses. The order is the tie-break when a floor carries two uses of equal area.
USE = {
    "Resedential": "homes", "Hotel Apartment": "homes", "Villa": "villa",
    # not homes a buyer is shopping for, and no listing portal says which buildings carry them (DDA session, 20 Sep)
    "Employees /Students Accommodation": "staff", "Labour Accomadation": "labour",
    "Offices": "office", "Banks": "office",
    "Commercial": "retail", "Shopping Center": "retail", "Cinema": "retail", "Theatre": "retail",
    "Petrol Station /Car Services": "retail",
    "Hotels": "hotel",
    "Education": "civic", "Hospitals": "civic", "Mosques": "civic",
    "Indoor Services": "services", "Warehouse/Factory/Workshop": "services",
}
RANK = ["homes", "villa", "office", "hotel", "retail", "civic", "staff", "labour", "services"]
# a floor's place in the stack: below ground, ground, mezzanine, the numbered floors, penthouse, roof
TIER = {"Under Ground": 0, "Ground": 1, "Mezzanine": 2, "Floor": 3, "Pent House": 4, "Roof Service": 5}
LABEL = {"Under Ground": "B", "Ground": "G", "Mezzanine": "M", "Pent House": "PH", "Roof Service": "R"}
HOME_TYPES = ("studio", "1 bedroom", "2 bedroom", "3 bedroom", "4 bedroom", "5 bedroom", "6 bedroom", "7 bedroom",
              "penthouse", "duplex", "hotel apartment", "room")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def type_key(t):
    """The register's type string -> the filter's chip: studio, 1..4 (4 = four or more), office, retail, other."""
    t = (t or "").strip().lower()
    if t.startswith("studio"):
        return "studio"
    m = re.match(r"(\d+)\s*b", t)
    if m:
        return str(min(int(m.group(1)), 4))
    if "penthouse" in t or "duplex" in t:
        return "4"
    if "office" in t:
        return "office"
    if "shop" in t or "retail" in t or "show" in t:
        return "retail"
    return "other"


def level_range(s):
    """ "8–62 (140 levels)" -> (8, 62). The en dash arrives as any of several bytes depending on who wrote it. """
    if not s:
        return None
    m = re.match(r"\s*(-?\d+)\D+?(-?\d+)", str(s))
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"\s*(-?\d+)", str(s))
    return (int(m.group(1)), int(m.group(1))) if m else None


def json_rows(path):
    """Every record of a DDA export, without loading the file. Two shapes: one object per line (.ndjson, or a .part while the
    pull is running), or the merged file - a single line holding metadata and a "results" array of millions of rows.
    Records are flat, so the ends are found with str.find (in C) rather than by walking 1.2 GB a character at a time in Python -
    the careful walk took hours. A record that will not parse (a brace inside a string) is stitched to the next close brace."""
    fh = open(path, encoding="utf-8", errors="replace")
    head = fh.read(1 << 16)
    key = next((k for k in ('"results"', '"data"', '"records"') if k in head), None)
    if key is None:                                   # object per line
        fh.seek(0)
        for line in fh:
            if line.startswith("{"):
                yield json.loads(line)
        fh.close()
        return
    buf = head[head.index("[", head.index(key)) + 1:]
    pos = 0
    while True:
        a = buf.find("{", pos)
        b = buf.find("}", a + 1) if a >= 0 else -1
        while a >= 0 and b >= 0:
            try:
                yield json.loads(buf[a:b + 1])
            except ValueError:
                b = buf.find("}", b + 1)              # a brace inside a string: take the next close brace
                if b >= 0:
                    continue
                break
            pos = b + 1
            a = buf.find("{", pos)
            b = buf.find("}", a + 1) if a >= 0 else -1
        if a < 0 and buf.find("]", pos) >= 0:
            fh.close()
            return
        buf = buf[a if a >= 0 else pos:]
        pos = 0
        chunk = fh.read(1 << 24)
        if not chunk:
            fh.close()
            return
        buf += chunk


def read_floors(paths, wanted):
    """DM floor register rows for the wanted building ids -> {building_id: {(tier, floor_no): {use: [units, area]}}}.
    The export repeats a floor under older load timestamps; the newest load of each (floor, usage) wins."""
    got = {}
    for p in paths:
        fh = None
        rows = json_rows(p) if not p.endswith(".csv") else csv.DictReader(open(p, encoding="utf-8-sig", errors="replace"))
        for r in rows:
            bid = num(r.get("building_id"))
            if bid is None or int(bid) not in wanted:
                continue
            ft = r.get("floor_type_english") or ""
            if ft not in TIER:
                continue
            # the register carries a few impossible rows (DDA pull session, 20 Sep): 13 buildings run past floor 200, one to
            # 47,880, and 129 rows give a floor an area of 100k sqm or more, one of 3.3 bn. Drop the floor, keep the building.
            fno = int(num(r.get("floor_no")) or 0)
            if fno < 0 or fno > MAX_FLOOR:
                continue
            area = num(r.get("usages_area")) or 0
            if area > MAX_FLOOR_SQM:
                area = 0
            key = (TIER[ft], fno)
            use = r.get("usage_description_english") or ""
            ts = r.get("load_timestamp") or ""
            cell = got.setdefault(int(bid), {}).setdefault(key, {})
            if use not in cell or ts >= cell[use][2]:
                cell[use] = [num(r.get("no_of_units")) or 0, area, ts]
    return got


def floor_use(uses):
    """The use a floor is drawn as: the drawable use with the most area, then the most units; services only if nothing else."""
    best, score = None, None
    for u, (units, area, _) in uses.items():
        k = USE.get(u)
        if not k or (not units and not area):
            continue                   # a usage listed with no units and no area is a placeholder row (podium car parks read "Resedential" 0/0)
        s = (k != "services", area or 0, units or 0, -RANK.index(k))
        if score is None or s > score:
            best, score = k, s
    return best


def stack_from_dm(fl):
    """Ordered floors, bottom to top, basements dropped (the twin draws nothing below ground; their count is kept)."""
    out, bsmt = [], 0
    for (tier, no) in sorted(fl):
        uses = fl[(tier, no)]
        if tier == 0:
            bsmt += 1
            continue
        units = int(sum(v[0] for u, v in uses.items() if USE.get(u) and USE[u] not in ("services",)))
        area = round(sum(v[1] for u, v in uses.items() if USE.get(u)))
        ft = [k for k, t in TIER.items() if t == tier][0]
        label = str(no) if ft == "Floor" else LABEL[ft] + ("" if no <= 1 else str(no))
        u = floor_use(uses) or "services"
        if ft == "Roof Service" and not units:
            u = "services"
        out.append({"l": label, "n": no if ft == "Floor" else None, "u": u, "k": units, "a": area})
    return out, bsmt


def stack_from_permit(dm):
    """No floor register on the building: G, podium levels, the typical floors, roof - from the permit line alone."""
    out = [{"l": "G", "n": None, "u": "retail", "k": 0, "a": 0}]
    pod = int(dm.get("podium") or 0)
    for i in range(pod):
        out.append({"l": "P" + str(i + 1), "n": None, "u": "services", "k": 0, "a": 0})
    for n in range(1, int(dm.get("floors_above") or 0) + 1):
        out.append({"l": str(n), "n": n, "u": "homes", "k": 0, "a": 0})
    if dm.get("roof"):
        out.append({"l": "R", "n": None, "u": "services", "k": 0, "a": 0})
    return out, int(dm.get("basements") or 0)


def types_for(rec):
    """The register's unit types with the floor range each sits on, and what each settles at."""
    out = []
    for r in rec.get("rows") or []:
        lr = level_range(r.get("levels"))
        out.append({"t": r.get("type"), "c": type_key(r.get("type")), "units": r.get("units"),
                    "lo": lr[0] if lr else None, "hi": lr[1] if lr else None,
                    "sqm": r.get("median_sqm"), "aed": r.get("median_aed") or r.get("est_aed"),
                    "est": bool(r.get("est_aed") and not r.get("median_aed")),
                    "rent": r.get("median_rent"), "yield": r.get("gross_yield_pct")})
    return out


def tag_types(floors, types):
    """Each numbered floor gets the types whose register range covers it. G / mezzanine / roof take none.
    The Land Department sometimes counts levels from the ground or the podium (Loreto: types on 3-9, the permit's home floors
    1-7). When the register's top level passes the building's top floor, every range shifts down by the difference; the
    shift is returned so the card can say it."""
    top = max([f["n"] for f in floors if f["n"] is not None] or [0])
    hi = max([t["hi"] for t in types if t["hi"] is not None] or [0])
    shift = hi - top if top and hi > top else 0
    if shift:
        for t in types:
            if t["lo"] is not None:
                t["lo"], t["hi"] = max(1, t["lo"] - shift), t["hi"] - shift
    for f in floors:
        f["t"] = [i for i, t in enumerate(types) if f["n"] is not None and t["lo"] is not None and t["lo"] <= f["n"] <= t["hi"]
                  and (t["c"] not in ("office", "retail") or f["u"] in ("office", "retail"))
                  and (t["c"] in ("office", "retail", "other") or f["u"] in ("homes", "hotel", "villa"))]
    return shift


def parcels_of(district):
    """{parcel key -> [buildings on it]} from the DM building spine, or {} when that district has not been cut yet."""
    p = os.path.join(BOARD, "parcel_buildings_%s.json" % PARCEL_SLUG.get(district, district))
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8")).get("parcels") or {}


def parcel_key(rec):
    p = ((rec.get("dld") or {}).get("parcel"))
    try:
        return str(int(float(p)))
    except (TypeError, ValueError):
        return None


def plot_of(rec, parcels):
    """What else stands on this building's plot, and whether the record we bound is the tallest thing on it."""
    key = parcel_key(rec)
    rows = parcels.get(key) if key else None
    if not rows:
        return None
    bid = ((rec.get("dm") or {}).get("dm_building_id"))
    mine = next((r for r in rows if bid and r.get("building_id") == bid), None)
    tall = max(rows, key=lambda r: (r.get("floors_above") or 0))
    others = [{"type": r.get("building_type"), "floors": int(r.get("floors_above") or 0), "units": int(r.get("units") or 0)}
              for r in sorted(rows, key=lambda r: -(r.get("floors_above") or 0)) if r is not mine][:4]
    return {"key": key, "n": len(rows), "others": others,
            "onit": bool(mine),                                   # the bound building is on this parcel at all
            "tallest": bool(mine and tall.get("building_id") == mine.get("building_id")),
            "tallest_floors": int(tall.get("floors_above") or 0)}


def bound_of(district):
    um = json.load(open(os.path.join(BOARD, "unitmix_%s.json" % district), encoding="utf-8"))["buildings_by_id"]
    return {i: r for i, r in um.items() if r.get("status") in ("verified", "partial")}


GENERIC = set("the by of and a tower towers residence residences building buildings dubai bay business hills damac park plaza "
              "court courts heights view views point one two three first second phase block wing north south east west centre "
              "center city marina creek downtown grand royal palace suites apartments".split())


def anchors_of(district):
    p = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    if not os.path.exists(p):
        return {}
    a = json.load(open(p, encoding="utf-8"))
    return {str(x["i"]): x for x in (a.get("anchors") or []) if x.get("i") is not None}


def map_name(district):
    """What the twin itself calls each footprint (data/names/anchors_<district>.json), for the conflict check below."""
    return {i: x.get("name") for i, x in anchors_of(district).items() if x.get("name")}


def height_check(rec, anchor, parcels):
    """The plot's register rows against the model's surveyed height. Returns the better-matching building on the plot, if one
    fits far better than the record we bound - a candidate mis-binding, for a person to judge."""
    key = parcel_key(rec)
    rows = parcels.get(key) if key else None
    mh = (anchor or {}).get("h")
    if not rows or not mh or mh < 12:
        return None
    def reg_h(r):
        h = r.get("height_m") or 0
        if not h and r.get("floors_above"):
            h = float(r["floors_above"]) * 3.4
        return h or 0
    bid = ((rec.get("dm") or {}).get("dm_building_id"))
    mine = next((r for r in rows if bid and r.get("building_id") == bid), None)
    cand = [r for r in rows if reg_h(r) > 0]
    if not cand:
        return None
    best = min(cand, key=lambda r: abs(reg_h(r) - mh))
    mine_gap = abs(reg_h(mine) - mh) if mine and reg_h(mine) else None
    best_gap = abs(reg_h(best) - mh)
    if mine and best.get("building_id") == mine.get("building_id"):
        return None
    if mine_gap is None or (mine_gap > 25 and best_gap < mine_gap / 2):
        return {"model_m": round(mh), "bound_m": round(reg_h(mine)) if mine else None,
                "better_id": best.get("building_id"), "better_m": round(best_gap and reg_h(best)),
                "better_floors": int(best.get("floors_above") or 0), "better_type": best.get("building_type")}
    return None


def name_conflict(reg, shown):
    """A register record bound to the wrong footprint would draw one building's floors on another (footprint 53: Enara's floors
    on The Binary). The test is the Twin Bible's, asymmetric: if the two names share no distinctive word, say so on the card."""
    if not reg or not shown:
        return None
    # "Enara By Omniyat" and "The Binary By Omniyat" share only their developer, which is not the building agreeing: compare
    # what comes before "by <developer>"
    w = lambda s: {x for x in re.findall(r"[a-z0-9]+", re.split(r"\bby\b", s.lower())[0]) if x not in GENERIC and len(x) > 2}
    a, b = w(reg), w(shown)
    if not a or not b or (a & b):
        return None
    return shown


AS_OF = [FLOORS_AS_OF]


def fits_footprint(rec, anchor):
    """Does the footprint we are about to cut actually carry this register building? Al Habtoor City's record is a 346 m tower;
    the footprint bound to it stands 20 m in the model, so it is the podium, and cutting 91 floors into it would be a lie. The
    page and the twin draw the floors only where the model is tall enough to hold them."""
    mh = (anchor or {}).get("h") or 0
    dm = rec.get("dm") or {}
    rh = dm.get("height_m") or ((dm.get("floors_above") or 0) * 3.4)
    if not mh or not rh or rh < 25:
        return True                      # nothing to contradict it
    return mh >= 0.6 * rh


def build(district, bound, fl):
    shown = map_name(district)
    anchors = anchors_of(district)
    parcels = parcels_of(district)
    ids = {int(r["dm"]["dm_building_id"]) for r in bound.values() if (r.get("dm") or {}).get("dm_building_id")}
    print("%s: %d register-bound footprints, %d with a DM building id, %d of those in the floor register"
          % (district, len(bound), len(ids), len(ids & set(fl))))
    out, tally, clashes = {}, {"dm_floors": 0, "dm_permit": 0, "register_levels": 0}, []
    for i, r in bound.items():
        dm = r.get("dm") or {}
        bid = int(dm["dm_building_id"]) if dm.get("dm_building_id") else None
        types = types_for(r)
        if bid in fl:
            floors, bsmt = stack_from_dm(fl[bid])
            basis = "dm_floors"
        elif dm.get("floors_above"):
            floors, bsmt = stack_from_permit(dm)
            basis = "dm_permit"
        elif r.get("floors") and types:
            floors, bsmt = [{"l": str(n), "n": n, "u": "homes", "k": 0, "a": 0} for n in range(1, int(r["floors"]) + 1)], 0
            basis = "register_levels"
        else:
            continue
        if len(floors) < 2:
            continue                   # a villa or a single-storey box: a stack would say nothing the card does not
        shift = tag_types(floors, types)
        tally[basis] += 1
        if name_conflict(r.get("name"), shown.get(i)):
            clashes.append("%s: the register says %r, the map says %r" % (i, r.get("name"), shown.get(i)))
        clash = name_conflict(r.get("name"), shown.get(i))
        uses = sorted({f["u"] for f in floors if f["u"] not in ("services",)})
        podium = any(f["u"] in ("retail", "office") and f["n"] is None for f in floors)      # shops or offices on the ground or mezzanine
        out[i] = {"name": r.get("name"), "basis": basis, "dm": bid, "basements": bsmt, "label": dm.get("floors_label"),
                  "level_shift": shift, "conflict": clash,
                  "uses": uses, "mixed": len(uses) >= 3, "podium": podium,
                  "labour": any(f["u"] == "labour" for f in floors), "staff": any(f["u"] == "staff" for f in floors),
                  "area_sqm": round(sum(f["a"] for f in floors)) or None,
                  "plot": plot_of(r, parcels), "height_flag": height_check(r, anchors.get(i), parcels),
                  "fits": fits_footprint(r, anchors.get(i)),
                  "height_m": dm.get("height_m"), "floors": floors, "types": types,
                  "total_units": r.get("total_units"), "developer": r.get("developer"),
                  "sheet": r.get("sheet")}
    doc = {"district": district, "generated": time.strftime("%Y-%m-%d"),
           "sources": ["Dubai Municipality building_floor_level_information (%s) by building id" % AS_OF[0],
                       "Dubai Municipality building_summary_information (the permit line) where a building has no floor rows",
                       "Dubai Land Department units register: the floor range each unit type sits on"],
           "note": "A type on a floor means the register puts that type in that floor range, not a unit position. Floors are "
                   "drawn by cutting the CityEngine massing into equal bands; the massing height is kept as it is.",
           "levels": tally, "buildings_by_id": out}
    path = os.path.join(BOARD, "stack_%s.json" % district)
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for c in clashes:
        print("  name conflict, shown on the card - " + c)
    off = [i for i, v in out.items() if v.get("plot") and not v["plot"]["onit"]]
    if off:
        print("  bound to a building that is not on the register's own parcel: %d (%s)" % (len(off), ", ".join(off[:8])))
    shared = sum(1 for v in out.values() if v.get("plot") and v["plot"]["n"] > 1)
    print("  %d of %d stand on a plot they share with another building" % (shared, len(out)))
    unfit = [i for i, v in out.items() if not v.get("fits")]
    if unfit:
        print("  %d footprints are too short to hold the register's floors (podium or part of the scheme): %s"
              % (len(unfit), ", ".join("%s %s" % (i, out[i]["name"]) for i in unfit[:6])))
    flags = [(i, v) for i, v in out.items() if v.get("height_flag")]
    if flags:
        print("  %d bindings where another building on the plot fits the model height better:" % len(flags))
        for i, v in flags[:10]:
            f = v["height_flag"]
            print("    %s %s: model %s m, bound record %s m, but building %s on the plot is %s m (%s floors, %s)"
                  % (i, v["name"], f["model_m"], f["bound_m"], f["better_id"], f["better_m"], f["better_floors"], f["better_type"]))
    print("  -> %s: %d buildings (%s), %d KB" % (os.path.relpath(path, ROOT), len(out),
                                                  ", ".join("%s %d" % kv for kv in tally.items()), os.path.getsize(path) // 1024))
    return doc


def main():
    argv = sys.argv[1:]
    fi = argv.index("--floors") if "--floors" in argv else -1
    paths, as_of = (sorted(glob.glob(argv[fi + 1])), argv[fi + 1]) if fi >= 0 else floor_files()
    args = [a for k, a in enumerate(argv) if not a.startswith("--") and not (fi >= 0 and k == fi + 1)] or ["businessbay", "damachills"]
    if not paths:
        sys.exit("no DM floor register: neither %s nor %s" % (FLOORS_DDA, FLOORS_CSV))
    AS_OF[0] = as_of
    print("floor register: %s (%s)" % (os.path.basename(paths[0]), as_of))
    bound = {d: bound_of(d) for d in args}
    wanted = {int(r["dm"]["dm_building_id"]) for b in bound.values() for r in b.values() if (r.get("dm") or {}).get("dm_building_id")}
    t0 = time.time()
    fl = read_floors(paths, wanted) if wanted else {}      # one pass over the register for every district asked for
    print("floor register: %d of %d wanted buildings found in %s (%.0fs)" % (len(fl), len(wanted), os.path.basename(paths[0]), time.time() - t0))
    if wanted and not fl:
        sys.exit("refusing to write: the floor register was read but matched no building. Every stack would silently fall back "
                 "to the permit line, which is thinner than what is already on disk. Check the file format first.")
    tok = None
    if "--push" in argv:
        from build_avail_index import env_token, push
        tok = env_token("INGEST_TOKEN")
    for d in args:
        doc = build(d, bound[d], fl)
        if tok:
            print("  push stack_%s -> %s" % (d, push("stack_" + d, doc, tok).get("ok")))


if __name__ == "__main__":
    main()
