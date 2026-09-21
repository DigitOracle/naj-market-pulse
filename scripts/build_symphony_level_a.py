"""The Symphony's own floor plans, on the twin - the template building rendered at the fidelity it was worked out at.

Kendall, 21 Sep 2026: the Symphony is the building where "we worked out the floor plans ... the floor plates ... everything",
and it is the template for the roll-out. But on the twin it was scoring 9 of the template's 16 sections, because the page was
reading the same registers as every other building: the Land Department has no units for an off-plan tower, so its plate came
out empty and its flats card never rendered - while the developer's Revit model of that very building sat in data/stack.

This takes the model's stacking plan (data/stack/symphony_units.json: 290 flats over floors 10-34, each with its number, type,
programme and its rectangle on the plate) and writes it into the two files the building page already reads:

  data/board/plates_goldensymphony.json   the plate, basis "revit" - the built layout, not an indicative one
  data/board/units_goldensymphony.json    the flats on each floor, with their real unit numbers

Setting the plan into the surveyed footprint is a fit, not an assumption: the model's plate is 43.4 x 40.0 m and the footprint's
minimum rotated rectangle is 43.3 x 39.9 m, so the two axes are matched by length, the scale is within a decimeter, and the plan
is placed on the footprint's own axes. What is NOT claimed is each flat's compass aspect: the model's "back" labels are to
project north, which is not true north here, so they are carried as programme, never as a view.

  python scripts/build_symphony_level_a.py [--push]
"""
import json, math, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
SRC = os.path.join(ROOT, "data", "stack", "symphony_units.json")
SLUG = "goldensymphony"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# the model's unit codes, in the page's own type keys
TYPE = {"MS": ("1", "Master Suite"), "1BR": ("1", "1 B/R"), "2BR": ("2", "2 B/R"), "3BR": ("3", "3 B/R"),
        "4BR": ("4", "4 B/R"), "DUPL": ("4", "4 B/R duplex, lower"), "DUPU": ("4", "4 B/R duplex, upper")}


def axes(outline):
    """The footprint's own axes and half-lengths, from its minimum rotated rectangle."""
    from shapely.geometry import Polygon
    pts = [(outline[i], outline[i + 1]) for i in range(0, len(outline), 2)]
    r = Polygon(pts).minimum_rotated_rectangle
    x, y = r.exterior.coords.xy
    c = (sum(x[:4]) / 4.0, sum(y[:4]) / 4.0)
    e = [(x[i + 1] - x[i], y[i + 1] - y[i]) for i in range(2)]
    ln = [math.hypot(*v) for v in e]
    u = [(v[0] / l, v[1] / l) for v, l in zip(e, ln)]
    return c, u, ln


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    pf = os.path.join(BOARD, "plates_%s.json" % SLUG)
    doc = json.load(open(pf, encoding="utf-8"))
    bid = list(doc["buildings"])[0]
    B = doc["buildings"][bid]
    c, u, ln = axes(B["outline"])

    # the model's plate, as half-extents in millimetres, matched to the footprint's axes by length
    hx, hy = src["plate"][0] / 1000.0, src["plate"][1] / 1000.0       # 20.0 and 21.7 m
    long_first = ln[0] >= ln[1]
    # the longer model axis (y, 43.4 m) goes on the longer footprint axis
    ax_y, ax_x = (u[0], u[1]) if long_first else (u[1], u[0])
    sc_y = (ln[0] if long_first else ln[1]) / (2 * hy)
    sc_x = (ln[1] if long_first else ln[0]) / (2 * hx)

    def P(mx, my):
        """A model point (mm) on the footprint, in the plate's own metres."""
        a, b = (mx / 1000.0) * sc_x, (my / 1000.0) * sc_y
        return (c[0] + ax_x[0] * a + ax_y[0] * b, c[1] + ax_x[1] * a + ax_y[1] * b)

    # --- the plate, floor by floor ------------------------------------------------------------------------------------------
    by_unit = {}
    for x in src["units"]:
        by_unit[str(x["unit"])] = x
    # re-runnable: drop anything this script added last time, so re-running never stacks a second copy of the model's floors
    keep = [p for p in B["plates"] if p.get("basis") != "revit"]
    index = {k: v for k, v in B["floors"].items() if B["plates"][v].get("basis") != "revit"}
    plates, labels, floors_out = keep, {}, {}
    drawn = 0
    for lvl, rects in sorted(src["plates"].items(), key=lambda kv: int(kv[0])):
        cells, lab, counts = [], {}, {}
        for i, (unum, x0, y0, x1, y1) in enumerate(rects):
            un = by_unit.get(str(unum))
            key = TYPE.get((un or {}).get("code"), ("other", ""))[0]
            poly = []
            for mx, my in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                poly += list(P(mx, my))
            cells.append([key, [round(v, 2) for v in poly], i])
            lab[str(i)] = str(unum)
            counts[key] = counts.get(key, 0) + 1
        plates.append({"use": "homes", "basis": "revit", "counts": counts, "scale": 1.0,
                       "cells": cells, "blocks": [], "tower": None, "skip": None, "dm_use": None})
        index[str(lvl)] = len(plates) - 1
        labels[str(lvl)] = lab
        floors_out[str(lvl)] = rects
        drawn += len(cells)
    B["plates"], B["floors"], B["labels"] = plates, index, labels
    doc["note"] = ("The Symphony is drawn from the developer's Revit model of this building: every flat's number, type and its "
                   "rectangle on the plate are the model's, floors 10 to 34. The outline is the surveyed footprint, and the "
                   "plan is set on its own axes - the model's plate is 43.4 by 40.0 m against a 43.3 by 39.9 m footprint. "
                   "Floors 1 to 9 are offices and the clubhouse, which the model does not divide into units.")
    json.dump(doc, open(pf, "w", encoding="utf-8"), ensure_ascii=False)
    print("plate: %d floors from the model, %d flats drawn -> %s" % (len(src["plates"]), drawn, os.path.basename(pf)))

    # --- the flats on each floor --------------------------------------------------------------------------------------------
    floors = {}
    for x in src["units"]:
        key, label = TYPE.get(x.get("code"), ("other", x.get("type") or ""))
        pr = x.get("programme") or {}
        floors.setdefault(str(x["floor"]), []).append({
            "u": str(x["unit"]), "t": label, "c": key, "sqft": int(round(x.get("sqft_est") or 0)), "bal": None,
            "sub": "Flat", "rooms": (str(pr.get("bathrooms")) + " bath" if pr.get("bathrooms") else None),
        })
    for v in floors.values():
        v.sort(key=lambda r: r["u"])
    n = sum(len(v) for v in floors.values())
    uf = os.path.join(BOARD, "units_%s.json" % SLUG)
    json.dump({"district": SLUG, "generated": doc.get("generated"), "source": "TheSymphony_by_Imtiaz_MeydanHorizon.rvt",
               "note": "The flats are the developer's Revit model of this building, not the Land Department units register: "
                       "the tower is off-plan and the register holds no units for it yet.",
               "min_cover": 0,
               "buildings_by_id": {bid: {"name": B.get("name"), "property_id": None, "units": n, "registered": n,
                                         "cover": 100, "source": "revit", "floors": floors}}},
              open(uf, "w", encoding="utf-8"), ensure_ascii=False)
    print("flats: %d over %d floors -> %s" % (n, len(floors), os.path.basename(uf)))

    if "--push" in sys.argv:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from build_avail_index import env_token, push
        tok = env_token("INGEST_TOKEN")
        print("units ->", push("units_" + SLUG, json.load(open(uf, encoding="utf-8")), tok).get("ok"))
        print("plate ->", push("plate_%s_%s" % (SLUG, bid), {"note": doc["note"], "building": B}, tok).get("ok"))


if __name__ == "__main__":
    main()
