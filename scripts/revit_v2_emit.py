"""Golden Building generator v2.1 (Neufert gate G1-G8 + sanitary programme) - Python side.
Computes every wall / opening / room / label for a floor and writes data/revit/v2_<F>.txt (loader format), v2_<F>.json
(geometry incl. room rectangles) and v2_<F>_labels.txt (unit numbers for the plate, room dimensions for the unit plans).
revit_v2_apply.cs builds the floor from the txt; revit_v2_cards.cs adds the labels and exports the card PDFs.

Plate (calibrated 2 Sep 2026 against the Imtiaz sheet): 40 x 43.4 m, core 14 x 22 centred, corridor ring 1.8 m.
Per unit (u along the facade from the entry end, v = depth from the corridor wall):
  hall strip 1.2 m along the corridor wall (G2/G6) - entry door from the corridor (G1)
  wet block at the entry end against the corridor (G8): family bathroom 2.2 x 2.6 + guest powder room 1.2 x 1.6 beside it
  maid's room 2.0 x 2.6 with its own WC 1.2 x 1.6 at the far end of the hall (3BR / 4BR / duplex - Dubai market norm)
  front rooms by fraction (FR) - living/kitchen first, then bedrooms; every habitable room has a facade window or glazed door (G4)
  ensuite 2.2 x 2.0 carved into the hall side of the master (all types) and bedroom 2 (3BR / 4BR); entered from the bedroom
  balcony 1.5 m outside living + master; door widths 1010 entry / 910 room / 810 bath (G5); room minimums checked (G7)
Every opening is kept >= 605 mm (455 half-door + 150) from any wall join so Revit raises no warning dialog.
Usage: python scripts/revit_v2_emit.py F32
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
P, CX, CY, CXo, CYo, H = 20000, 7000, 11000, 8800, 12800, 3500   # P = half plate WIDTH (x)
PY = 21700          # half plate DEPTH (y): N/S bands 8.9 m deep (calibrated to the developer sheet)
WB1 = 4500          # west-band single 3BR / duplex: top of the bay (15.5 m tall = 173 m2 per the sheet)
FR = {"1BR": [.55, .45], "MS": [.5, .5], "2BR": [.40, .32, .28], "3BR": [.34, .24, .21, .21], "4BR": [.30, .20, .17, .17, .16], "DUPL": [.36, .32, .32], "DUPU": [.36, .32, .32]}
NM = {"1BR": ["Living/Kitchen", "Bedroom"], "MS": ["Living/Kitchen", "Master Bedroom"], "2BR": ["Living/Kitchen", "Master Bedroom", "Bedroom 2"],
      "3BR": ["Living/Kitchen", "Master Bedroom", "Bedroom 2", "Bedroom 3"], "4BR": ["Living/Kitchen", "Master Bedroom", "Bedroom 2", "Bedroom 3", "Bedroom 4"],
      "DUPL": ["Living/Kitchen", "Master Bedroom", "Bedroom 2"], "DUPU": ["Family Lounge", "Bedroom 3", "Bedroom 4"]}   # duplex 3307: lower / upper level
ENSUITE = {"1BR": [], "MS": [1], "2BR": [1], "3BR": [1, 2], "4BR": [1, 2], "DUPL": [1, 2], "DUPU": [1, 2]}      # room indices that get an ensuite
MAID = {"1BR": False, "MS": False, "2BR": False, "3BR": True, "4BR": True, "DUPL": True, "DUPU": False}
POWDER = {"1BR": True, "MS": True, "2BR": True, "3BR": True, "4BR": True, "DUPL": True, "DUPU": True}
TYPE_LABEL = {"DUPL": "4BR Duplex (lower)", "DUPU": "4BR Duplex (upper)"}
KINDS = ["living", "bedroom", "bath", "hall", "balcony", "corridor"]
CLS = {"living": ["SL_45_10_45 : Kitchen-dining-living rooms", "11-11 11 11 Residential Spaces - Living Room", "brick:Living_Room", "space room residential"],
       "bedroom": ["SL_45_10_09 : Bedrooms", "11-11 11 14 Residential Spaces - Bedroom", "brick:Bedroom", "space room residential sleep"],
       "bath": ["SL_45_10 : Living spaces (bathroom)", "11-11 11 31 Residential Spaces - Bathroom", "rec:Bathroom", "space room toilet"],
       "hall": ["SL_90 : Circulation spaces (entrance hall)", "11-11 17 11 Circulation Spaces - Corridor", "brick:Hallway", "space corridor entrance"],
       "balcony": ["SL_45 : Residential spaces (balcony)", "11-11 11 11 Residential Spaces - Living Room", "brick:Outdoor_Area", "space outdoor balcony"],
       "corridor": ["SL_90 : Circulation spaces (verify code)", "11-11 17 11 Circulation Spaces - Corridor", "brick:Hallway", "space corridor"]}
SYM = {"dEnt": 0, "dInt": 1, "dBath": 2, "win": 3}   # 1010 / 910 / 810 doors, 1810x1210 window
HALL, BATHW, BATHD, PWDW, PWDD, MAIDW, MAIDD, MWCW, MWCD, ENSW, ENSD, CLR = 1200, 2200, 2600, 1200, 1600, 2000, 3000, 2000, 1600, 2200, 2000, 605
# Neufert-derived minimums (m2): living 14 (21 for 4+ rooms), master 12, bedroom 7 (9 preferred), bath 3.5, ensuite 3.5, powder 1.5, maid 5, hall 1
MIN = {"living": 14, "living_big": 21, "master": 12, "bedroom": 7, "bath": 3.5, "ensuite": 3.5, "powder": 1.5, "maid": 5, "maidwc": 1.5, "hall": 1}


def floor_type(fl):
    if 10 <= fl <= 22: return "T13"
    if fl in (23, 25, 27, 29, 31): return "T11"
    if fl in (24, 26, 28, 30): return "T10"
    return {32: "T9", 33: "T33", 34: "T34"}[fl]


def bays_for(ft):
    b = []
    B = lambda x0, y0, x1, y1, t, back: b.append((x0, y0, x1, y1, t, back))
    S4 = lambda: (B(7000, -PY, P, -CYo, "2BR", "N"), B(0, -PY, 7000, -CYo, "1BR", "N"), B(-7000, -PY, 0, -CYo, "1BR", "N"), B(-P, -PY, -7000, -CYo, "2BR", "N"))
    E3 = lambda: (B(CXo, 3667, P, CY, "1BR", "W"), B(CXo, -3667, P, 3667, "1BR", "W"), B(CXo, -CY, P, -3667, "1BR", "W"))
    if ft == "T13": B(-P, CYo, -9000, PY, "MS", "S"); B(-9000, CYo, -1000, PY, "1BR", "S"); B(-1000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); S4(); B(-P, -CY, -CXo, 0, "MS", "E"); B(-P, 0, -CXo, CY, "MS", "E")
    if ft == "T11": B(-P, CYo, -1000, PY, "2BR", "S"); B(-1000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); S4(); B(-P, -CY, -CXo, WB1, "3BR", "E")
    if ft == "T10": B(-P, CYo, -1000, PY, "3BR", "S"); B(-1000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); B(7000, -PY, P, -CYo, "2BR", "N"); B(-7000, -PY, 7000, -CYo, "1BR", "N"); B(-P, -PY, -7000, -CYo, "2BR", "N"); B(-P, -CY, -CXo, WB1, "3BR", "E")
    if ft == "T9": B(-P, CYo, 7000, PY, "4BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); B(7000, -PY, P, -CYo, "2BR", "N"); B(-7000, -PY, 7000, -CYo, "1BR", "N"); B(-P, -PY, -7000, -CYo, "2BR", "N"); B(-P, -CY, -CXo, CY, "4BR", "E")
    # T33/T34: unit 3307 = the 4BR duplex on the west wing (both levels) + the NW terrace; the deck skips 07 for the others
    if ft == "T33": B(-2000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); S4(); B(-P, -CY, -CXo, WB1, "DUPL", "E")
    if ft == "T34": B(-2000, CYo, 7000, PY, "1BR", "S"); B(7000, CYo, P, PY, "2BR", "S"); E3(); B(7000, -PY, P, -CYo, "2BR", "N"); B(-P, -CY, -CXo, WB1, "DUPU", "E")
    return b


def build(fl):
    ft = floor_type(fl)
    walls, edges, opens, rooms, units, labels, seps = [], set(), [], [], [], [], []   # seps = room separation lines (open-plan boundaries)

    def W(x0, y0, x1, y1, h=H):
        key = (round(min(x0, x1)), round(min(y0, y1)), round(max(x0, x1)), round(max(y0, y1)))
        if key in edges or (abs(x0 - x1) < 1 and abs(y0 - y1) < 1):
            return
        edges.add(key)
        walls.append((round(x0), round(y0), round(x1), round(y1), h))

    # core + 4 corner stubs (close the dead-end corridor legs); units tile the bands with their own boundary walls -> no collinear overlaps
    W(-CX, -CY, CX, -CY); W(CX, -CY, CX, CY); W(CX, CY, -CX, CY); W(-CX, CY, -CX, -CY)
    W(P, CY, P, CYo); W(P, -CY, P, -CYo); W(-P, CY, -P, CYo); W(-P, -CY, -P, -CYo)
    if ft in ("T10", "T11", "T33", "T34"):
        W(-P, WB1, -P, CY)                      # west perimeter above the shortened west-band unit (pocket = corridor/lift lobby)
    if ft == "T34":
        W(-P, -CYo, 7000, -CYo)                 # south edge of the corridor where the 34th has no south-band units

    for u, (x0, y0, x1, y1, t, back) in enumerate(bays_for(ft)):
        idx = u + 1 if ft not in ("T33", "T34") else (7 if t in ("DUPL", "DUPU") else (u + 1 if u < 6 else u + 2))
        unit = "%04d" % (fl * 100 + idx)
        dept = "Unit %s - %s" % (unit, TYPE_LABEL.get(t, t))
        Wd = (x1 - x0) if back in "SN" else (y1 - y0)
        D = (y1 - y0) if back in "SN" else (x1 - x0)
        Wp = {"S": lambda uu, vv: (x0 + uu, y0 + vv), "N": lambda uu, vv: (x1 - uu, y1 - vv),
              "W": lambda uu, vv: (x0 + vv, y1 - uu), "E": lambda uu, vv: (x1 - vv, y0 + uu)}[back]

        def LW(u0, v0, u1, v1, h=H):
            a = Wp(u0, v0); b = Wp(u1, v1); W(a[0], a[1], b[0], b[1], h)

        def rect(u0, v0, u1, v1):
            a = Wp(u0, v0); b = Wp(u1, v1)
            return [round(min(a[0], b[0])), round(min(a[1], b[1])), round(max(a[0], b[0])), round(max(a[1], b[1]))]

        def R(u, v, name, num, kind, mn, u0, v0, u1, v1, role):
            x, y = Wp(u, v)
            rooms.append((round(x), round(y), name, num, dept, kind, mn, rect(u0, v0, u1, v1), role))

        def door(u, v, sym):
            opens.append((*Wp(u, v), SYM[sym]))

        # unit envelope + hall wall
        LW(0, 0, Wd, 0); LW(Wd, 0, Wd, D); LW(Wd, D, 0, D); LW(0, D, 0, 0)
        wet_end = BATHW + (PWDW if POWDER[t] else 0)                 # entry-end wet block width along the corridor wall
        maid_w = (MAIDW if MAID[t] else 0)                           # far-end service block
        liv_end = FR[t][0] * Wd                                      # living/kitchen is OPEN-PLAN to the entrance zone: no hall wall in front of it
        LW(max(wet_end, liv_end), HALL, Wd - maid_w, HALL)          # hall wall only in front of the bedrooms
        if liv_end > wet_end:                                        # ROOM SEPARATION LINE keeps hall and open-plan living distinct rooms (opening >= 1.0 m)
            sa = Wp(wet_end, HALL); sb = Wp(liv_end, HALL); seps.append((round(sa[0]), round(sa[1]), round(sb[0]), round(sb[1])))
        # family bathroom + powder room (entry end, against the corridor wall)
        LW(BATHW, 0, BATHW, BATHD); LW(0, BATHD, BATHW, BATHD)
        R(BATHW / 2, BATHD / 2, "Bathroom", unit + "-WC", "bath", MIN["bath"], 0, 0, BATHW, BATHD, "family bath")
        door(BATHW, 600, "dBath")                                    # from the hall
        if POWDER[t]:
            LW(wet_end, 0, wet_end, PWDD); LW(BATHW, PWDD, wet_end, PWDD)
            R(BATHW + PWDW / 2, PWDD / 2, "Powder Room", unit + "-PR", "bath", MIN["powder"], BATHW, 0, wet_end, PWDD, "guest WC")
            door(wet_end, 600, "dBath")                              # from the hall (on the powder room's far wall)
        # maid's room + maid WC (far end, against the corridor wall)
        if MAID[t]:
            # maid's room 2.0 x 3.0 against the corridor wall, its WC stacked BEHIND it (2.0 x 1.6) so the room nets >= 5 m2
            LW(Wd - maid_w, 0, Wd - maid_w, MAIDD + MWCD); LW(Wd - maid_w, MAIDD, Wd, MAIDD); LW(Wd - maid_w, MAIDD + MWCD, Wd, MAIDD + MWCD)
            R(Wd - maid_w / 2, MAIDD / 2, "Maid's Room", unit + "-M", "bedroom", MIN["maid"], Wd - maid_w, 0, Wd, MAIDD, "maid")
            R(Wd - maid_w / 2, MAIDD + MWCD / 2, "Maid WC", unit + "-MWC", "bath", MIN["maidwc"], Wd - maid_w, MAIDD, Wd, MAIDD + MWCD, "maid WC")
            door(Wd - maid_w, 600, "dBath")                          # maid's room from the hall (600 clear of the corridor wall and the hall-wall join)
            door(Wd - maid_w / 2, MAIDD, "dBath")                    # maid WC from the maid's room
        # entry door from the corridor, clear of the wet block join
        door(wet_end + CLR + 100, 0, "dEnt")
        # front rooms
        fr, nm, pos, spans = FR[t], NM[t], 0, []
        for k, f in enumerate(fr):
            w = f * Wd
            if k < len(fr) - 1:
                LW(pos + w, HALL, pos + w, D)
            spans.append((pos, pos + w)); pos += w
        hall_lo, hall_hi = wet_end, Wd - maid_w
        for k, (s0, s1) in enumerate(spans):
            wk = s1 - s0; m = (s0 + s1) / 2
            ens = k in ENSUITE[t]
            # ensuite carved into the hall side of the bedroom, at the room's entry-side end; bedroom door beside it
            avail = min(s1, hall_hi) - max(s0, hall_lo)              # hall frontage this room really has (wet/maid blocks removed)
            ensw = min(ENSW, avail - (2 * CLR + 50))                 # leave >= 1.26 m of that frontage for the bedroom door
            if ens and ensw * ENSD < MIN["ensuite"] * 1e6:
                ens = False                                          # too narrow for a compliant ensuite -> shares the family bath
            if ens:
                eu0 = s0; eu1 = s0 + ensw
                LW(eu1, HALL, eu1, HALL + ENSD); LW(eu0, HALL + ENSD, eu1, HALL + ENSD)
                R((eu0 + eu1) / 2, HALL + ENSD / 2, "Ensuite", unit + "-E%d" % k, "bath", MIN["ensuite"], eu0, HALL, eu1, HALL + ENSD, "ensuite")
                door(eu1, HALL + ENSD - CLR, "dBath")                # ensuite door from the bedroom, on the ensuite's side wall
                lo, hi = max(eu1, hall_lo) + CLR, min(s1, hall_hi) - CLR
            else:
                lo, hi = max(s0, hall_lo) + CLR, min(s1, hall_hi) - CLR
            if k > 0:                                                # bedrooms: door from the hall; living is open to the entrance zone
                du = min(max(m, lo), hi) if lo <= hi else (lo + hi) / 2
                door(du, HALL, "dInt")
            # facade: balcony for living + master, window for the rest
            if k <= 1 and wk >= 3000:
                LW(s0 + 300, D, s0 + 300, D + 1500, 1100); LW(s0 + 300, D + 1500, s1 - 300, D + 1500, 1100); LW(s1 - 300, D + 1500, s1 - 300, D, 1100)
                door(s0 + 300 + 250 + 455, D, "dInt")
                if wk >= 4000:
                    opens.append((*Wp(s1 - 300 - 250 - 905, D), SYM["win"]))
                R(m, D + 750, "Balcony", unit + "-B%d" % (k + 1), "balcony", 0, s0 + 300, D, s1 - 300, D + 1500, "balcony")
            else:
                opens.append((*Wp(m, D), SYM["win"]))
            kind = "living" if k == 0 else "bedroom"
            mn = (MIN["living_big"] if len(fr) >= 4 else MIN["living"]) if k == 0 else (MIN["master"] if k == 1 else MIN["bedroom"])
            R(m, D - 1800, nm[k] + (" + entrance" if k == 0 else ""), unit + "-%d" % (k + 1), kind, mn, s0, HALL + (ENSD if ens else 0), s1, D, "master" if k == 1 else kind)
        h0 = max(hall_lo, spans[0][1])                               # hall = the strip in front of the bedrooms (the living absorbs the entrance zone)
        R((h0 + hall_hi) / 2, HALL / 2, "Hall", unit + "-H", "hall", MIN["hall"], h0, 0, hall_hi, HALL, "hall")
        units.append({"unit": unit, "type": t, "bay": [x0, y0, x1, y1], "back": back, "width_mm": Wd, "depth_mm": D,
                      "programme": {"bedrooms": len(fr) - 1, "maid": MAID[t], "bathrooms": 1 + len(ENSUITE[t]) + (1 if MAID[t] else 0), "powder": POWDER[t], "ensuites": len(ENSUITE[t])}})
        # unit number sits in the middle of the living room (clear of hall / ensuite walls), not at the bay centre
        liv = next(r for r in rooms if r[3] == unit + "-1"); lrc = liv[7]
        labels.append(("U", (lrc[0] + lrc[2]) // 2, (lrc[1] + lrc[3]) // 2 + 600, unit))
    if ft in ("T33", "T34"):
        W(-P, CYo, -2000, CYo); W(-P, CYo, -P, PY); W(-P, PY, -2000, PY)
        opens.append((-11000, CYo, SYM["dEnt"]))
        rooms.append((-11000, (CYo + PY) // 2, "Pool terrace" if ft == "T33" else "Planted terrace", "%d07-T" % fl, "Unit %d07 - 4BR" % fl, "balcony", 0, [-P, CYo, -2000, PY], "terrace"))
    rooms.append((0, CY + 900, "Corridor", "%02d-COR" % fl, "Circulation", "corridor", 0, [-P, -CYo, P, CYo], "corridor"))
    return ft, walls, [(round(x), round(y), s) for x, y, s in opens], rooms, units, labels, seps


def emit(fl):
    F = "F%02d" % fl
    ft, walls, opens, rooms, units, labels, seps = build(fl)
    out = os.path.join(ROOT, "data", "revit"); os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "v2_%s.txt" % F), "w", encoding="utf-8") as fh:
        for w in walls:
            fh.write("W %d %d %d %d %d\n" % w)
        for o in opens:
            fh.write("O %d %d %d\n" % o)
        for sline in seps:
            fh.write("S %d %d %d %d\n" % sline)
        for x, y, nm, num, dept, kind, mn, rc, role in rooms:
            fh.write("R %d|%d|%s|%s|%s|%d|%g\n" % (x, y, nm, num, dept, KINDS.index(kind), mn))
    # labels: U x y unit  (plate)  /  D x y text|room  (unit plan: inside dimensions of every room)
    with open(os.path.join(out, "v2_%s_labels.txt" % F), "w", encoding="utf-8") as fh:
        for _, x, y, unit in labels:
            fh.write("U %d %d %s\n" % (x, y, unit))
        # inside dimensions only where they fit clear of the room tag: living / bedrooms (tag sits at the facade end, text at the
        # rectangle centre) and the maid's room (tag at centre, text near the corridor wall). Small wet rooms and halls keep tag + schedule only.
        for x, y, nm, num, dept, kind, mn, rc, role in rooms:
            if role not in ("living", "master", "bedroom", "maid"):
                continue
            w_mm, d_mm = rc[2] - rc[0], rc[3] - rc[1]
            cx, cy = (rc[0] + rc[2]) // 2, (rc[1] + rc[3]) // 2
            if role == "maid":
                cy = rc[1] + 450 if y > cy else rc[3] - 450
            elif abs(y - cy) < 900:                                   # tag too close to the centre -> push the text 1.1 m the other way
                cy = cy - 1100 if y >= cy else cy + 1100
            fh.write("D %d %d %.2f x %.2f m|%s\n" % (cx, cy, w_mm / 1000, d_mm / 1000, num))
    json.dump({"floor": F, "ftype": ft, "walls": walls, "openings": opens, "separations": seps, "rooms": rooms, "units": units, "kinds": KINDS, "sym": SYM},
              open(os.path.join(out, "v2_%s.json" % F), "w"), indent=0)
    return F, ft, (len(walls), len(opens), len(rooms))


if __name__ == "__main__":
    fl = int(sys.argv[1].lstrip("Ff"))
    F, ft, counts = emit(fl)
    print(F, ft, "walls/openings/rooms", counts)
