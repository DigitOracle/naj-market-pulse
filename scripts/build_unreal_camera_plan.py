"""Choose where the camera stands for each Business Bay tower, from the positions stage 1 measured in Unreal.

  python scripts/build_unreal_camera_plan.py businessbay

WHY THIS IS A SEPARATE SCRIPT AND RUNS OUTSIDE UNREAL. Every camera decision here is arithmetic on positions that are
already measured and on disk (data/board/unreal_stage1_<slug>.json). Doing it in the editor would mean 193 decisions I
could not inspect until after they were made. Here the whole plan can be read, argued with and corrected before a
single actor exists, and stage 2 becomes a script that places what this decided rather than one that decides.

THE PROBLEM THIS ACTUALLY SOLVES IS OCCLUSION. Business Bay's towers sit on a median footprint of 5,022 m2 packed
along a 4.1 km canal. A camera placed on a fixed bearing - due south of every building, say - puts a neighbour between
the lens and the subject often enough to ruin a batch, and you do not find out until you watch 193 clips. So for each
tower this sweeps 36 bearings and scores each one by what stands in the way:

    for every OTHER building within reach, if it falls inside the cone from camera to subject, it blocks a share of
    the subject's height. A 200 m tower 100 m in front of a 90 m subject blocks all of it; the same tower 800 m away
    and 30 m off-axis blocks none.

The chosen bearing is the clearest one. The score is written out per building, so a clip that still looks wrong can be
checked against what we believed about it rather than re-derived.

WHAT IT DELIBERATELY DOES NOT DO. It does not raise the camera to clear an obstruction: a tower shot from 200 m up to
dodge a neighbour reads as a drone escaping, not as a building. It keeps the camera low - a third of the subject's
height - and moves it around instead, which is how a building is actually filmed. Where no bearing is clear it says so
(`blocked`) rather than picking the least bad one silently, and stage 2 leaves those out.

FRAMING. Distance is set so the building fills a fixed share of the frame given the lens, from the measured height:

    distance = (height / 2 + margin) / tan(vertical_fov / 2)

with a 35 mm lens on a 4:5 filmback, matching README_hero_clip.md so these cut together with the hero material.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FOCAL_MM = 35.0
FILM_W, FILM_H = 18.0, 22.5          # 4:5 vertical, as the hero clip README sets it
FILL = 0.72                          # share of frame height the building occupies
CAM_H_FRAC = 0.33                    # camera eye height as a share of subject height - low, like a person filming
BEARINGS = 36                        # 10 degree steps
REACH_M = 900.0                      # a building further than this cannot meaningfully block
CLEAR_OK = 0.12                      # a bearing blocking <= 12% of the subject's height is "clear"


def vfov():
    return 2.0 * math.atan((FILM_H / 2.0) / FOCAL_MM)


def frame_distance(height_uu):
    """Distance in uu so the building fills FILL of frame height."""
    half = (height_uu / FILL) / 2.0
    return half / math.tan(vfov() / 2.0)


def occlusion(subj, others, bearing_rad, dist_uu):
    """How much of the subject's height is hidden from a camera on this bearing. 0 = clear, 1 = fully blocked."""
    sx, sy, _ = subj["origin"]
    sh = subj["measured_uu"]
    cx = sx + math.cos(bearing_rad) * dist_uu
    cy = sy + math.sin(bearing_rad) * dist_uu
    worst = 0.0
    for o in others:
        ox, oy, _ = o["origin"]
        oh = o["measured_uu"]
        # position of the other building along the camera->subject axis
        vx, vy = sx - cx, sy - cy
        L = math.hypot(vx, vy)
        if L < 1.0:
            continue
        ux, uy = vx / L, vy / L
        t = (ox - cx) * ux + (oy - cy) * uy          # distance along the axis
        if t <= 0 or t >= L:
            continue                                  # behind the camera, or behind the subject
        perp = abs(-(ox - cx) * uy + (oy - cy) * ux)  # lateral offset from the axis
        halfw = max(o["extent"][0], o["extent"][1])
        if perp > halfw:
            continue                                  # not in the way at all
        # how high does it reach in frame, compared with the subject, from the camera's position
        rise_other = oh / t
        rise_subj = sh / L
        if rise_subj <= 0:
            continue
        share = min(1.0, rise_other / rise_subj)
        # a narrow miss blocks less of the width, and so less of the shot
        share *= max(0.0, 1.0 - (perp / halfw) ** 2)
        worst = max(worst, share)
    return worst


def main(slug):
    rep = json.load(open(os.path.join(ROOT, "data", "board", "unreal_stage1_%s.json" % slug), encoding="utf-8"))
    found = rep["found"]
    # Everything in the district blocks the lens, not only the things we are filming. Stage 1 records all 654; if an
    # older report has only the targets, fall back and say so rather than silently scoring against a quarter of the city.
    obstacles = rep.get("all_buildings") or found
    partial = "all_buildings" not in rep
    plan, blocked, held = [], [], []
    for f in found:
        if f.get("height_disputed"):
            held.append({"i": f["i"], "name": f["name"], "why": "height disputed - not rendered until settled"})
            continue
        h = f["measured_uu"]
        dist = frame_distance(h)
        others = [o for o in obstacles if o["i"] != f["i"]
                  and math.hypot(o["origin"][0] - f["origin"][0], o["origin"][1] - f["origin"][1]) < REACH_M * 100]
        scored = []
        for b in range(BEARINGS):
            ang = 2.0 * math.pi * b / BEARINGS
            scored.append((occlusion(f, others, ang, dist), ang))
        scored.sort()
        best_score, best_ang = scored[0]
        if best_score > CLEAR_OK:
            blocked.append({"i": f["i"], "name": f["name"], "best_occlusion": round(best_score, 3),
                            "why": "no bearing clears the neighbours; a clip here would have a tower in front of it"})
            continue
        cx = f["origin"][0] + math.cos(best_ang) * dist
        cy = f["origin"][1] + math.sin(best_ang) * dist
        cz = h * CAM_H_FRAC
        # look at the middle of the building, not its base
        plan.append({
            "i": f["i"], "name": f["name"], "label": f["label"],
            "height_m": f["height_m"], "provenance": f.get("provenance"),
            "camera_location": [round(cx, 1), round(cy, 1), round(cz, 1)],
            "look_at": [round(f["origin"][0], 1), round(f["origin"][1], 1), round(h / 2.0, 1)],
            "distance_uu": round(dist, 1),
            "bearing_deg": round(math.degrees(best_ang), 1),
            "occlusion": round(best_score, 3),
            "clear_bearings": sum(1 for s, _ in scored if s <= CLEAR_OK),
        })

    out = {
        "district": slug,
        "from": "unreal_stage1_%s.json" % slug,
        "lens": {"focal_mm": FOCAL_MM, "filmback_mm": [FILM_W, FILM_H], "fill": FILL,
                 "vfov_deg": round(math.degrees(vfov()), 2)},
        "counts": {"planned": len(plan), "blocked": len(blocked), "held": len(held), "targets": len(found)},
        "obstacles_counted": len(obstacles),
        "caveat": ("occlusion scored against only the targets - stage 1 predates all_buildings, so shorter neighbours "
                   "are invisible to it and this UNDER-counts obstruction" if partial else
                   "occlusion scored against every building in the district, targets and neighbours alike"),
        "planned": sorted(plan, key=lambda p: -p["height_m"]),
        "blocked": blocked,
        "held": held,
    }
    dest = os.path.join(ROOT, "data", "board", "unreal_camera_plan_%s.json" % slug)
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("%s: %d cameras planned, %d blocked, %d held  (occlusion vs %d buildings%s)"
          % (slug, len(plan), len(blocked), len(held), len(obstacles), " - TARGETS ONLY, under-counts" if partial else ""))
    print("   lens %.0f mm on %.0fx%.0f, vertical fov %.1f deg, building fills %.0f%% of frame"
          % (FOCAL_MM, FILM_W, FILM_H, math.degrees(vfov()), FILL * 100))
    if plan:
        ds = [p["distance_uu"] / 100 for p in plan]
        print("   camera distance: %.0f m median, %.0f m min, %.0f m max" % (sorted(ds)[len(ds) // 2], min(ds), max(ds)))
        cb = [p["clear_bearings"] for p in plan]
        print("   clear bearings per building: %d median of %d" % (sorted(cb)[len(cb) // 2], BEARINGS))
    for b in blocked[:8]:
        print("   BLOCKED b%-5d %-32s best occlusion %.2f" % (b["i"], b["name"][:32], b["best_occlusion"]))
    print("-> " + dest)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "businessbay")
