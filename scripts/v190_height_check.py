"""Detect bad bindings instead of preventing them (DDA session, 20 Sep 2026: there is no parcel geometry to bind with).

For every building we bound by name, the plot's own register rows give each candidate's height and floor count. If another
building on the same plot matches our surveyed model height far better than the one we bound, that binding is a candidate
mis-binding - we took the podium, or the neighbour, or the wrong tower of a pair. It is a short list to check by eye, not an
automatic correction: nothing is re-bound here.
"""
import io, os

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_floor_stack.py")
s = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


sub('''def map_name(district):
    """What the twin itself calls each footprint (data/names/anchors_<district>.json), for the conflict check below."""
    p = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    if not os.path.exists(p):
        return {}
    a = json.load(open(p, encoding="utf-8"))
    return {str(x.get("i")): x.get("name") for x in (a.get("anchors") or []) if x.get("i") is not None and x.get("name")}''',
'''def anchors_of(district):
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
    return None''')

sub("""def build(district, bound, fl):
    shown = map_name(district)
    parcels = parcels_of(district)""",
    """def build(district, bound, fl):
    shown = map_name(district)
    anchors = anchors_of(district)
    parcels = parcels_of(district)""")

sub('''                  "plot": plot_of(r, parcels),''',
    '''                  "plot": plot_of(r, parcels), "height_flag": height_check(r, anchors.get(i), parcels),''')

sub('''    shared = sum(1 for v in out.values() if v.get("plot") and v["plot"]["n"] > 1)
    print("  %d of %d stand on a plot they share with another building" % (shared, len(out)))''',
    '''    shared = sum(1 for v in out.values() if v.get("plot") and v["plot"]["n"] > 1)
    print("  %d of %d stand on a plot they share with another building" % (shared, len(out)))
    flags = [(i, v) for i, v in out.items() if v.get("height_flag")]
    if flags:
        print("  %d bindings where another building on the plot fits the model height better:" % len(flags))
        for i, v in flags[:10]:
            f = v["height_flag"]
            print("    %s %s: model %s m, bound record %s m, but building %s on the plot is %s m (%s floors, %s)"
                  % (i, v["name"], f["model_m"], f["bound_m"], f["better_id"], f["better_m"], f["better_floors"], f["better_type"]))''')

io.open(P, "w", encoding="utf-8", newline="").write(s)
print("height check wired in")
