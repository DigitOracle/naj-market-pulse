"""Unit stack for the Symphony building viewer: every floor of the tower projected onto a developer render.

Source of the homes: the Golden Building generator v2 (scripts/revit_v2_emit.py -> data/revit/v2_F<n>.json) -
290 homes on floors 10-34, calibrated 2 Sep 2026 against the Imtiaz sheet and the developer's floor-plate deck.
Plate coordinates in mm, centred on the core: +x east, +y north, half-width P = 20000 (x), half-depth PY = 21700 (y).

The render (developer-published, imtiaz.ae Exterior 9) shows two faces of the tower from the boulevard: the WEST face
on the right of the image and the NORTH face on the left, meeting at the NW corner. Each face is a plane; a homography
from facade coordinates (u across the face 0..1, v up the tower 0..1, in metres so taller office floors take their
real share) to image pixels places every unit's slice of that face. Four image corners per face are the only calibration.

    python scripts/stack_overlay.py check <render.jpg> <out.jpg>   -> the stack drawn on the render, to check the fit
    python scripts/stack_overlay.py json                           -> data/stack/symphony_units.json for the viewer
"""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P, PY = 20000, 21700
F_LO, F_HI = 10, 34                      # residential floors
# The tower above the podium: floors 1-8 offices, 9 clubhouse and gym, 10-34 homes (35 = plant + the duplex's top, under the crown).
OFF_H, RES_H = float(os.environ.get("OFF_H", 4.0)), 3.5


def base_m(fl):
    """Height of a floor's base above the podium roof, in metres."""
    return (min(fl, 10) - 1) * OFF_H + max(0, fl - 10) * RES_H


TOP_M = base_m(35)

# image corners (px, in the 3332x2500 render) of each face from the podium roof to the top of floor 34:
# bottom-left, bottom-right, top-right, top-left
CORNERS = {
    "west":  [(1455, 1985), (1790, 1950), (1784, 602), (1467, 332)],
    "north": [(1232, 1962), (1455, 1985), (1467, 332), (1251, 738)],
}


def homography(src, dst):
    """3x3 H with dst ~ H * src, from four point pairs (direct linear transform, no numpy)."""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    M = [row[:8] for row in A]; b = [-row[8] for row in A]
    n = 8
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c])); M[c], M[piv] = M[piv], M[c]; b[c], b[piv] = b[piv], b[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * m for a, m in zip(M[r], M[c])]; b[r] -= f * b[c]
    h = [b[i] / M[i][i] for i in range(n)] + [1.0]
    return [h[0:3], h[3:6], h[6:9]]


def apply(H, u, v):
    x = H[0][0] * u + H[0][1] * v + H[0][2]; y = H[1][0] * u + H[1][1] * v + H[1][2]; w = H[2][0] * u + H[2][1] * v + H[2][2]
    return (x / w, y / w)


HS = {face: homography([(0, 0), (1, 0), (1, 1), (0, 1)], CORNERS[face]) for face in CORNERS}


def quad(face, a, b, fl):
    v0, v1 = base_m(fl) / TOP_M, base_m(fl + 1) / TOP_M
    return {"face": face, "pts": [[round(c, 1) for c in apply(HS[face], uu, vv)] for uu, vv in [(a, v0), (b, v0), (b, v1), (a, v1)]]}


def face_segments(bay):
    """Which visible faces a unit bay touches, as (face, u0, u1) with u across the face as seen from outside."""
    x0, y0, x1, y1 = bay
    out = []
    if min(x0, x1) <= -P + 1:                               # west face, seen from the west: north (y=+PY) on the left
        out.append(("west", (PY - max(y0, y1)) / (2 * PY), (PY - min(y0, y1)) / (2 * PY)))
    if max(y0, y1) >= PY - 1:                               # north face, seen from the north: east (x=+P) on the left
        out.append(("north", (P - max(x0, x1)) / (2 * P), (P - min(x0, x1)) / (2 * P)))
    return out


TYPE_NAME = {"1BR": "1 BHK", "MS": "Master Suite", "2BR": "2 BHK", "3BR": "3 BHK", "4BR": "4 BHK", "DUPL": "4 BHK Duplex", "DUPU": "4 BHK Duplex"}


def floor_json(fl):
    return json.load(open(os.path.join(ROOT, "data", "revit", "v2_F%d.json" % fl)))


def units():
    out = []
    for fl in range(F_LO, F_HI + 1):
        d = floor_json(fl)
        for u in d["units"]:
            polys = [quad(face, a, b, fl) for face, a, b in face_segments(u["bay"])]
            rooms = [{"n": r[2], "k": r[5], "r": r[7]} for r in d["rooms"] if r[4].startswith("Unit %s " % u["unit"])]
            out.append({"unit": u["unit"], "floor": fl, "type": TYPE_NAME.get(u["type"], u["type"]), "code": u["type"], "bay": u["bay"],
                        "back": u["back"], "sqft_est": round(u["width_mm"] * u["depth_mm"] / 1e6 * 10.7639),
                        "programme": u.get("programme"), "polys": polys, "rooms": rooms})
    return out


def bands():
    """Floors 1-9 as one band per visible face: offices, then the clubhouse floor."""
    return [{"floor": fl, "type": "Clubhouse" if fl == 9 else "Office", "polys": [quad("west", 0, 1, fl), quad("north", 0, 1, fl)]} for fl in range(1, 10)]


def plates():
    """Every residential floor's bays, for the 'where it sits on the floor' plan."""
    return {str(fl): [[u["unit"]] + u["bay"] for u in floor_json(fl)["units"]] for fl in range(F_LO, F_HI + 1)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "json"
    us = units()
    if cmd == "check":
        from PIL import Image, ImageDraw
        im = Image.open(sys.argv[2]).convert("RGB"); d = ImageDraw.Draw(im, "RGBA")
        col = {"1 BHK": (232, 184, 130, 110), "2 BHK": (60, 72, 88, 130), "3 BHK": (160, 200, 150, 120), "Master Suite": (200, 170, 220, 110),
               "4 BHK": (110, 200, 210, 120), "4 BHK Duplex": (110, 200, 210, 140), "Office": (120, 150, 200, 110), "Clubhouse": (240, 200, 90, 130)}
        for u in us + bands():
            for p in u["polys"]:
                d.polygon([tuple(q) for q in p["pts"]], fill=col.get(u["type"], (255, 0, 0, 90)), outline=(255, 255, 255, 200))
        im.save(sys.argv[3], quality=88)
        print("drawn", sum(len(u["polys"]) for u in us), "unit faces + 9 bands")
    else:
        os.makedirs(os.path.join(ROOT, "data", "stack"), exist_ok=True)
        json.dump({"building": "The Symphony by Imtiaz", "units": us, "bands": bands(), "plates": plates(), "plate": [P, PY]},
                  open(os.path.join(ROOT, "data", "stack", "symphony_units.json"), "w"), indent=0)
        print("units", len(us), "visible", sum(1 for u in us if u["polys"]))
