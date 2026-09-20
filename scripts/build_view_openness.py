"""Which way can each floor actually see? (Kendall, 20 Sep 2026: "unblocked view would be a good one".)

No portal can answer this, because it needs the city's geometry, and we hold it: every footprint's position and surveyed height
in the twin's own metres (data/names/anchors_<district>.json - the same x, z, h the 3D model is drawn from).

For each floor, for each of eight compass sectors, we ask how much of that sector is actually walled off at that height. A
neighbour blocks only the slice of horizon it subtends - a 355 m tower 600 m away is a finger in front of the view, not a wall -
so each neighbour taller than the floor's eye height contributes its own angular span, the spans are merged, and a sector counts
as OPEN when less than BLOCKED_MAX of it is covered. That is the plain question a buyer asks: "do I look over the roofs on that
side, and from which floor".

What it is NOT: it does not know what you see once you are over the roofs (water, park, the Burj), it assumes flat ground, it
treats each neighbour as a block of WIDTH metres, and it only sees this district's own footprints - a tower one street outside
the tile blocks nothing here. The card says so.

  python scripts/build_view_openness.py businessbay damachills     -> merges "open" into data/board/stack_<district>.json
  --push   publish the merged file to the app's store (this runs AFTER build_floor_stack.py, so it is the one that publishes)
"""
import json, math, os, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
NAMES = os.path.join(ROOT, "data", "names")
RADIUS = 700.0          # metres: past this a neighbour is horizon, not a blocker, and the tile's own edge is near
EYE = 1.6               # a person stands on the floor
WIDTH = 60.0            # how wide a neighbouring tower is taken to be, side on: the footprints are not in this file
BLOCKED_MAX = 0.30      # a sector is open while less than this much of its 45 degrees is walled off
NEAR = 150.0            # a taller neighbour this close fills the side whatever its width: you look at it, not past it
SECTORS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
FLOOR_MIN = 2.8         # a floor is never thinner than this, whatever the model height divided by the register's floors says


def anchors(district):
    p = os.path.join(NAMES, "anchors_%s.json" % district)
    if not os.path.exists(p):
        return {}
    out = {}
    for a in json.load(open(p, encoding="utf-8")).get("anchors") or []:
        if a.get("i") is None or a.get("x") is None or a.get("z") is None:
            continue
        h = a.get("h")
        if not h and a.get("levels"):
            try:
                h = float(a["levels"]) * 3.2
            except (TypeError, ValueError):
                h = None
        out[str(a["i"])] = {"x": float(a["x"]), "z": float(a["z"]), "h": float(h or 0), "name": a.get("name")}
    return out


def bearing(dx, dz):
    """The twin's z runs south, as three.js draws it: north is -z. Degrees clockwise from north."""
    return (math.degrees(math.atan2(dx, -dz)) + 360.0) % 360.0


def covered(spans):
    """Merge [start, end] degree spans (already split so none crosses 0) and return the degrees covered per sector."""
    per = [0.0] * 8
    if not spans:
        return per
    spans.sort()
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in merged:
        for s in range(8):
            lo, hi = s * 45.0 - 22.5, s * 45.0 + 22.5
            if s == 0:                       # north straddles 0/360: count both ends
                per[s] += max(0.0, min(b, 22.5) - max(a, 0.0)) + max(0.0, min(b, 360.0) - max(a, 337.5))
            else:
                per[s] += max(0.0, min(b, hi) - max(a, lo))
    return per


OUT = []


def openness(district):
    stack_path = os.path.join(BOARD, "stack_%s.json" % district)
    if not os.path.exists(stack_path):
        print("%s: no stack file yet" % district)
        return None
    doc = json.load(open(stack_path, encoding="utf-8"))
    A = anchors(district)
    if not A:
        print("%s: no anchors on disk, nothing to measure against" % district)
        return None
    ids = list(A.items())
    done, floors_total, t0 = 0, 0, time.time()
    for i, rec in doc["buildings_by_id"].items():
        me = A.get(str(i))
        if not me:
            continue
        n = len(rec["floors"])
        h = me["h"] or (rec.get("height_m") or 0)
        if not h or not n:
            continue
        fh = max(FLOOR_MIN, h / n)
        near = []
        for j, o in ids:
            if j == str(i) or not o["h"]:
                continue
            dx, dz = o["x"] - me["x"], o["z"] - me["z"]
            d = math.hypot(dx, dz)
            if d > RADIUS or d < 1:
                continue
            half = 24.0 if d <= NEAR else math.degrees(math.atan2(WIDTH / 2.0, d))
            near.append((bearing(dx, dz), half, o["h"]))
        near.sort(key=lambda t: -t[2])
        masks, first = [], [None] * 8
        for k in range(n):
            eye = (k + 0.5) * fh + EYE
            spans = []
            for b, half, oh in near:
                if oh <= eye:
                    break                    # sorted tallest first: the rest are lower still
                a0, a1 = b - half, b + half
                if a0 < 0:
                    spans.append((a0 + 360.0, 360.0)); spans.append((0.0, a1))
                elif a1 > 360:
                    spans.append((a0, 360.0)); spans.append((0.0, a1 - 360.0))
                else:
                    spans.append((a0, a1))
            per = covered(spans)
            m = 0
            for s in range(8):
                if per[s] < 45.0 * BLOCKED_MAX:
                    m |= 1 << s
                    if first[s] is None:
                        first[s] = k
            masks.append(m)
        rec["open"] = masks
        rec["open_from"] = first                       # the floor each side opens on, or null if it never does
        rec["open_radius"] = int(RADIUS)
        done += 1
        floors_total += n
    doc["sources"] = [x for x in (doc.get("sources") or []) if not x.startswith("Open sides")] + [
        "Open sides: every footprint within %d m in this district's own model (surveyed heights), each taken %d m wide, flat "
        "ground; a side counts as open while less than %d%% of it is walled off" % (int(RADIUS), int(WIDTH), int(BLOCKED_MAX * 100))]
    json.dump(doc, open(stack_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("%s: open sides on %d buildings, %d floors (%.0fs) -> %s"
          % (district, done, floors_total, time.time() - t0, os.path.relpath(stack_path, ROOT)))
    OUT.append(doc)
    return doc


def show(doc, names):
    for _k, r in doc["buildings_by_id"].items():
        if r.get("open_from") and any(s in (r["name"] or "").upper() for s in names):
            fr = r["open_from"]
            print("   %s: %s" % (r["name"], ", ".join(
                "%s %s" % (SECTORS[s], "never" if fr[s] is None else ("from G" if fr[s] == 0 else "from " + str(r["floors"][fr[s]]["l"])))
                for s in range(8))))


def main():
    tok = None
    if "--push" in sys.argv:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_avail_index import env_token, push
        tok = env_token("INGEST_TOKEN")
    for d in [a for a in sys.argv[1:] if not a.startswith("--")] or ["businessbay", "damachills"]:
        doc = openness(d)
        if not doc:
            continue
        show(doc, ["AL HABTOOR TOWER", "CARSON"])
        if tok:
            print("  push stack_%s -> %s" % (d, push("stack_" + d, doc, tok).get("ok")))


if __name__ == "__main__":
    main()
