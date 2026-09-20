"""The other buildings on the plot (DDA session's parcel -> buildings cut, 20 Sep 2026). A parcel is not one tower: 166 of
Business Bay's 209 parcels carry more than one building. Whether the one we bound is the tower or a services block is a fact the
card should state, and a mis-binding shows up here first."""
import io, os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "build_floor_stack.py")
s = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)


sub('BOARD = os.path.join(ROOT, "data", "board")',
    'BOARD = os.path.join(ROOT, "data", "board")\n'
    '# the DDA session writes these with its own slugs (business_bay, damac_hills), one per DM community\n'
    'PARCEL_SLUG = {"businessbay": "business_bay", "damachills": "damac_hills"}')

sub("""def bound_of(district):""",
    '''def parcels_of(district):
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


def bound_of(district):''')

sub("""def build(district, bound, fl):
    shown = map_name(district)""",
    """def build(district, bound, fl):
    shown = map_name(district)
    parcels = parcels_of(district)""")

sub("""                  "area_sqm": round(sum(f["a"] for f in floors)) or None,""",
    """                  "area_sqm": round(sum(f["a"] for f in floors)) or None,
                  "plot": plot_of(r, parcels),""")

sub("""    for c in clashes:
        print("  name conflict, shown on the card - " + c)""",
    """    for c in clashes:
        print("  name conflict, shown on the card - " + c)
    off = [i for i, v in out.items() if v.get("plot") and not v["plot"]["onit"]]
    if off:
        print("  bound to a building that is not on the register's own parcel: %d (%s)" % (len(off), ", ".join(off[:8])))
    shared = sum(1 for v in out.values() if v.get("plot") and v["plot"]["n"] > 1)
    print("  %d of %d stand on a plot they share with another building" % (shared, len(out)))""")

io.open(P, "w", encoding="utf-8", newline="").write(s)
print("plot facts wired into the stack build")
