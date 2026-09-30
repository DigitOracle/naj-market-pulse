"""LAB (landmarks, research only): build every landmark in the table with PyPRT, before and after, and check them.

For each row of data/lab/landmarks/landmark_table.json it builds the ONE footprint headlessly, with the same
per-shape attrs pyprt_district.prepare pushes (bHeight by the ce_batch_v2 rule, fclass / fvar from facade_v2.json,
status, levels, LOD 3), in a local frame about the footprint centroid:

  stock       data/ce/_rpk/najma_v4.rpk, generic attrs                     what the v4 lane builds today
  hook_off    najma_v4_landmarks.rpk, landmark = ""                       must equal stock (the hook is a no-op)
  lod2        najma_v4_landmarks.rpk + the row's cga (Facade Wizard LOD 2, splits with depth)
  lod1        the same at lmLOD 1 (flat splits)          |  the wizard's own LOD dial,
  lod0        the same at lmLOD 0 (tile texture)         |  for the web lane's budget
  lod2_pubh   (only where the twin height disagrees with the published one) lod2 at the published height

Writes data/lab/landmarks/glb/<slug>_b<i>_<variant>.glb and data/lab/landmarks/build_report.json with, per build:
triangles (from the GLB), height, triangles per material slot, PyPRT report sums, and the family checks:
  spiral_setback  the tier-1 cut lands on wing 0 and only wing 0 (proves the rotateScope angle convention),
                  every wing is trimmed back by the top tier, and the spire reaches bHeight
  twist           the top floor plate is turned (floors - 1) x twDeg from the ground floor plate
  void_cube       the void glazing exists and the facade has an opening at mid-height on both long faces

  python scripts/lab_landmarks_build.py [--only burjkhalifa:67]
"""
import glob
import json
import math
import os
import shutil
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import pyprt                                                   # noqa: E402
from pyproj import Transformer                                 # noqa: E402
from pyprt_district import heights, rings, footprint, ce_reference   # noqa: E402  (read-only reuse, nothing edited)

CEDIR = os.path.join(ROOT, "data", "ce")
OUT = os.path.join(ROOT, "data", "lab", "landmarks")
GLB = os.path.join(OUT, "glb")
STOCK = os.path.join(CEDIR, "_rpk", "najma_v4.rpk")
LAB = os.path.join(OUT, "najma_v4_landmarks.rpk")
TF = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
PUBLISHED_H = {"businessbay:158": 93.0}                        # CTBUH; the twin carries 71.4 m


def opt(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def shape_and_attrs(slug, i):
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    facade = json.load(open(os.path.join(CEDIR, slug, "facade_v2.json"), encoding="utf-8"))["buildings"]
    H = heights(slug, feats)
    f = feats[i]
    ring = rings(f["geometry"])[0]
    en = np.array([TF.transform(c[0], c[1]) for c in ring])
    ox, on = float(round(en[:-1, 0].mean())), float(round(en[:-1, 1].mean()))
    verts = footprint(ring, TF, ox, on)
    rec = facade.get(str(i), {"class": "auto", "variant": i % 3})
    a = {"shapeName": "b%d" % i, "seed": i, "fclass": str(rec["class"]), "fvar": float(int(rec.get("variant", i % 3))),
         "status": str(f["properties"].get("status") or "existing").lower(), "LOD": 3.0, "bandEvery": 1.0}
    if H[i] > 0:
        a["bHeight"] = float(H[i])
    lv = str(f["properties"].get("levels") or "").strip()
    if lv:
        a["levels"] = lv
    return verts, a, (ox, on)


def as_attr(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def build(verts, attrs, rpk, name):
    """GLB via the glTF encoder (one mesh per material) + the PyPRT report; returns stats."""
    os.makedirs(GLB, exist_ok=True)
    tmp = os.path.join(GLB, "_tmp_" + name)
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    t = time.time()
    pyprt.ModelGenerator([pyprt.InitialShape(verts)]).generate_model(
        [attrs], rpk, "com.esri.prt.codecs.GLTFEncoder",
        {"outputPath": tmp, "baseName": name, "meshGranularity": "INITIAL_SHAPE", "outputFormat": "GLB"})
    took = round(time.time() - t, 1)
    parts = sorted(glob.glob(os.path.join(tmp, name + "*.glb")))
    errs = open(os.path.join(tmp, "CGAError.txt"), encoding="utf-8", errors="ignore").read().strip() \
        if os.path.exists(os.path.join(tmp, "CGAError.txt")) else ""
    if not parts:
        return {"error": "no GLB written", "cga_errors": errs[:3000]}
    out = os.path.join(GLB, name + ".glb")
    shutil.move(parts[0], out)
    rep = pyprt.ModelGenerator([pyprt.InitialShape(verts)]).generate_model(
        [attrs], rpk, "com.esri.pyprt.PyEncoder", {"emitReport": True, "emitGeometry": False})[0].get_report()
    shutil.rmtree(tmp, ignore_errors=True)
    st = glb_stats(out)
    st.update({"glb": os.path.relpath(out, ROOT).replace("\\", "/"), "generate_s": took, "glb_mb": round(os.path.getsize(out) / 1048576.0, 2),
               "cga_errors": errs[:2000], "report": {k: v for k, v in rep.items()
                                                      if k.split("_")[0] in ("Faces", "GFA", "Storeys", "Height", "Landmark.spiral", "Landmark.twist", "Landmark.void")
                                                      or k.startswith("Landmark")}})
    return st


def glb_points(path):
    import trimesh
    sc = trimesh.load(path, force="scene")
    per, pts = {}, []
    for g in sc.geometry.values():
        nm = getattr(getattr(g.visual, "material", None), "name", None) or "?"
        per[nm] = per.get(nm, 0) + len(g.faces)
        pts.append(np.asarray(g.vertices))
    P = np.vstack(pts) if pts else np.zeros((0, 3))
    return sc, per, P


def glb_stats(path):
    _, per, P = glb_points(path)
    return {"triangles": int(sum(per.values())), "height_m": round(float(P[:, 1].max() - P[:, 1].min()), 1) if len(P) else 0,
            "slots": dict(sorted(per.items(), key=lambda kv: -kv[1]))}


# ---------------------------------------------------------------- family checks (on the GLB, local CE frame)
def band(P, y0, y1):
    return P[(P[:, 1] >= y0) & (P[:, 1] <= y1)]


def check_spiral(path, cga, bh):
    _, _, P = glb_points(path)
    floors, top_frac, setbacks = cga.get("lmFloors", 154), 0.707, 27
    fh = bh * top_frac / floors
    tier = lambda j: round(j * floors / (setbacks + 1))       # noqa: E731
    ext = []
    for j in (0, 1, 2, 3, setbacks):
        y0 = tier(j) * fh + 0.5; y1 = tier(j + 1) * fh - 0.5 if j < setbacks else bh * top_frac - 0.5
        B = band(P, y0, y1)
        row = []
        for w in range(3):
            a = math.radians(cga["lmAz%d" % w])
            u = np.array([math.cos(a), -math.sin(a)])          # CE frame: x = east, z = -north
            row.append(round(float((B[:, [0, 2]] @ u).max()), 1) if len(B) else None)
        ext.append({"tier": j, "reach_m": row})
    d1 = [ext[0]["reach_m"][w] - ext[1]["reach_m"][w] for w in range(3)]
    return {"wing_reach_by_tier": ext, "tier1_cut_m": [round(x, 1) for x in d1],
            "tier1_cuts_wing0_only": d1[0] > 2.0 and abs(d1[1]) < 1.0 and abs(d1[2]) < 1.0,
            "top_tier_all_trimmed": all(ext[-1]["reach_m"][w] < ext[0]["reach_m"][w] - 0.5 * cga["lmLen%d" % w] for w in range(3)),
            "spire_top_m": round(float(P[:, 1].max()), 1)}


def plate_angle(B):
    """Orientation (deg, mod 90) of a floor plate's vertices: the min-area rectangle's edge angle."""
    from shapely.geometry import MultiPoint
    r = MultiPoint([tuple(p) for p in B[:, [0, 2]]]).minimum_rotated_rectangle
    q = np.array(r.exterior.coords)
    e = q[1] - q[0]
    return math.degrees(math.atan2(e[1], e[0])) % 90


def check_twist(path, cga, bh):
    _, _, P = glb_points(path)
    floors = cga.get("lmFloors", 75); fh = bh / floors
    a0 = plate_angle(band(P, 1 * fh + 0.2 * fh, 1 * fh + 0.8 * fh))
    a1 = plate_angle(band(P, (floors - 2) * fh + 0.2 * fh, (floors - 2) * fh + 0.8 * fh))
    turned = (a1 - a0) % 90
    expect = ((floors - 3) * 1.2) % 90
    return {"floor1_deg_mod90": round(a0, 1), "floor_n-2_deg_mod90": round(a1, 1), "turn_mod90": round(turned, 1),
            "expected_mod90": round(expect, 1), "ok": min(abs(turned - expect), 90 - abs(turned - expect)) < 3.0}


def check_void(path, cga, bh, per):
    _, _, P = glb_points(path)
    floors = cga.get("lmFloors", 21); fh = bh / floors
    mid = band(P, 9.5 * fh, 10.5 * fh)                          # storey 10 = void centre
    a = math.radians(cga["lmAz0"]); u = np.array([math.cos(a), -math.sin(a)])
    s = np.sort(mid[:, [0, 2]] @ u)
    gap = float(np.diff(s).max()) if len(s) > 2 else 0.0
    return {"void_glass_tris": int(per.get("lm_void_glass", 0)), "largest_gap_along_long_axis_at_storey10_m": round(gap, 1),
            "ok": per.get("lm_void_glass", 0) > 0}


def main():
    table = json.load(open(os.path.join(OUT, "landmark_table.json"), encoding="utf-8"))["landmarks"]
    only = opt("--only")
    if not os.path.exists(LAB):
        sys.exit("no %s - run scripts/lab_landmarks_rpk.py first" % LAB)
    known = set(pyprt.get_rpk_attributes_info(LAB).keys())
    res = {"rpk_stock": os.path.relpath(STOCK, ROOT), "rpk_lab": os.path.relpath(LAB, ROOT),
           "lab_rpk_attrs_landmark": sorted(k for k in known if k.startswith("lm") or k == "landmark"), "buildings": {}}
    for key, row in table.items():
        if only and key != only:
            continue
        slug, i = key.split(":"); i = int(i)
        verts, base, origin = shape_and_attrs(slug, i)
        tag = "%s_b%d" % (slug, i)
        missing = [k for k in row["cga"] if k not in known]
        if missing:
            print("  %s: attrs not in the lab rpk: %s" % (key, missing))
        print("%s  %s  bHeight %s" % (key, row["name"], base.get("bHeight")), flush=True)
        runs = {"stock": (STOCK, base), "hook_off": (LAB, {**base, "landmark": ""})}
        cga = {k: as_attr(v) for k, v in row["cga"].items() if k in known}
        for lod in (2, 1, 0):
            runs["lod%d" % lod] = (LAB, {**base, **cga, "lmLOD": float(lod)})
        if key in PUBLISHED_H:
            runs["lod2_pubh"] = (LAB, {**base, **cga, "lmLOD": 2.0, "bHeight": PUBLISHED_H[key]})
        out = {"name": row["name"], "family": row["family"], "origin_utm_en": origin, "attrs_pushed": cga, "builds": {}}
        try:                                                    # what the CityEngine v4 lane published for the same shape
            out["ce_v4_published"] = ce_reference(slug).get(i)
        except Exception as e:
            out["ce_v4_published"] = {"error": repr(e)[:200]}
        for v, (rpk, attrs) in runs.items():
            st = build(verts, attrs, rpk, "%s_%s" % (tag, v))
            out["builds"][v] = st
            print("   %-10s %9s tris  %6s m  %5ss  %s" % (v, st.get("triangles"), st.get("height_m"), st.get("generate_s"),
                                                     ("ERR " + st["cga_errors"][:200]) if st.get("cga_errors") else ""), flush=True)
        b = out["builds"]
        out["hook_is_noop"] = b["stock"].get("triangles") == b["hook_off"].get("triangles") and b["stock"].get("slots") == b["hook_off"].get("slots")
        bh = base.get("bHeight", 0)
        try:
            p2 = os.path.join(ROOT, b["lod2"]["glb"])
            if row["family"] == "spiral_setback":
                out["check"] = check_spiral(p2, row["cga"], bh)
            elif row["family"] == "twist":
                out["check"] = check_twist(p2, row["cga"], bh)
            elif row["family"] == "void_cube":
                out["check"] = check_void(p2, row["cga"], bh, b["lod2"]["slots"])
        except Exception as e:
            out["check"] = {"error": repr(e)}
        print("   hook no-op: %s   check: %s" % (out["hook_is_noop"], json.dumps(out.get("check"))[:400]), flush=True)
        res["buildings"][key] = out
    p = os.path.join(OUT, "build_report.json" if not only else "build_report_%s.json" % only.replace(":", "_"))
    json.dump(res, open(p, "w", encoding="utf-8"), indent=1)
    print("-> %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
