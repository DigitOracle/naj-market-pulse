"""Pre-flight for the generator output: every opening must sit on a wall and >= half-door + 150 mm from any wall join;
every room seed must be inside its own rectangle; prints the sanitary programme per type. Run before revit_v2_apply."""
import json, math, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
floors = sys.argv[1:] or ["F11", "F24", "F32", "F33", "F34"]
HALF = [505, 455, 405, 905]
def on(w, x, y):
    x0, y0, x1, y1 = w[:4]
    if abs(x0 - x1) < 1: return abs(x - x0) < 1 and min(y0, y1) - 1 <= y <= max(y0, y1) + 1
    if abs(y0 - y1) < 1: return abs(y - y0) < 1 and min(x0, x1) - 1 <= x <= max(x0, x1) + 1
    return False
total_bad = 0
for F in floors:
    j = json.load(open(os.path.join(ROOT, "data", "revit", "v2_%s.json" % F)))
    walls, bad = j["walls"], []
    for x, y, s in j["openings"]:
        host = [w for w in walls if on(w, x, y)]
        if not host:
            bad.append(("nohost", x, y, s)); continue
        h = host[0]
        for w in walls:
            if w is h: continue
            for ex, ey in ((w[0], w[1]), (w[2], w[3])):
                if on(h, ex, ey):
                    d = math.hypot(ex - x, ey - y)
                    if 0 < d < HALF[s] + 150: bad.append((x, y, s, "join", ex, ey, round(d)))
    for r in j["rooms"]:
        x, y, rc = r[0], r[1], r[7]
        if not (rc[0] < x < rc[2] and rc[1] < y < rc[3]): bad.append(("seed-outside", r[3]))
    total_bad += len(bad)
    prog = {u["type"]: u["programme"] for u in j["units"]}
    print(F, "issues:", bad[:8] or "none", "| programme:", {t: "%dBR+%s bath %d pwd %s" % (p["bedrooms"], "maid" if p["maid"] else "-", p["bathrooms"], p["powder"]) for t, p in prog.items()})
print("TOTAL issues", total_bad)
