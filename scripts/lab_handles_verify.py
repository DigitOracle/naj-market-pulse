"""LAB (handles, research only): prove the handle-edit persistence path headlessly, with PyPRT, on one district.

No CityEngine. The CityEngine end is played by MockCE - the same calls lab_handles_capture.capture() makes on the real
bridge (getObjectsFrom, getRuleFile, getName, getVertices, getAttribute, getAttributeSource, getAttributeList), over a
scene staged the way lab_handles_capture.stage() stages it - so capture -> file -> apply -> rebuild -> GLB is one run:

  1  BASE      production najma_v4.rpk, no handle file                                  -> *_base_0.glb
  2  CAPTURE   two synthetic handle drags (heights) + a podium drag + a facade-class selector pick, a swapped shape
               name, a production-rule shape that must be ignored, one Local Edit     -> overrides_<slug>.json
  3  APPLY v4  production rule + the file (podiumStoreys must be reported unknown)      -> *_ovr_v4_0.glb
  4  APPLY lab najma_v4_handles.rpk + the file (podium must move)                        -> *_ovr_lab_0.glb
  5  LAB idle  najma_v4_handles.rpk, no file: must equal BASE per building              -> *_lab_idle_0.glb
  6  REBUILD   step 4 again from scratch: identical
  7  LOD 0     exact heights (plain extrusion) + the rule's own reports (Height_m, Podium_storeys)
  8  LOGIC     re-key after a reordered geojson, orphan on a moved footprint, reviewed height wins / promoted

  python scripts/lab_handles_verify.py alyufrah1 [--t1 0 --h1 45 --t2 6 --h2 90 --podium 2]
Writes everything under data/lab/handles/ and data/lab/handles/verify_<slug>.json.
"""
import copy
import glob
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
LAB = os.path.join(ROOT, "data", "lab", "handles")
sys.path.insert(0, HERE)
import lab_handles_apply as A      # noqa: E402
import lab_handles_capture as C    # noqa: E402
import pyprt_district as P         # noqa: E402

RPK_V4 = os.path.join(CEDIR, "_rpk", "najma_v4.rpk")
RPK_LAB = os.path.join(LAB, "najma_v4_handles.rpk")


def opt(n, d=None, cast=str):
    return cast(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d


# ------------------------------------------------------------------ the CityEngine end, mocked
class MockCE:
    """A staged lab scene: shapes with object attrs (source OBJECT), rule attrs, and a drag() that does what a
    viewport handle does - set /ce/rule/<attr> and flip its source to USER."""

    def __init__(self):
        self.sh = []

    def add(self, name, verts, rule, obj, extra=None):
        self.sh.append({"name": name, "verts": list(verts), "rule": rule, "obj": dict(obj), "rule_vals": {},
                        "src": {k: "OBJECT" for k in obj}, "extra": dict(extra or {})})
        return len(self.sh) - 1

    def drag(self, s, attr, value):
        self.sh[s]["rule_vals"][attr] = value
        self.sh[s]["src"][attr] = "USER"

    # the API surface capture() uses
    def scene(self):
        return "scene"

    def isShape(self, o):
        return True

    def getObjectsFrom(self, container, *filters):
        return list(range(len(self.sh)))

    def getRuleFile(self, s):
        return self.sh[s]["rule"]

    def getName(self, s):
        return self.sh[s]["name"]

    def getVertices(self, s):
        return self.sh[s]["verts"]

    def getAttributeSource(self, s, name):
        return self.sh[s]["src"].get(name.split("/ce/rule/")[-1], "DEFAULT")

    def getAttribute(self, s, name):
        d = self.sh[s]
        if name.startswith("/ce/rule/"):
            k = name[len("/ce/rule/"):]
            return d["rule_vals"].get(k, d["obj"].get(k))
        return d["obj"].get(name, d["extra"].get(name))

    def getAttributeList(self, s):
        return list(self.sh[s]["obj"]) + list(self.sh[s]["extra"])


# ------------------------------------------------------------------ build + measure
def build_glb(slug, rpk, tag, with_overrides, lod=3):
    import pyprt
    from glb_merge_per_building import merge
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    shapes, attrs, idx, skipped, _ = P.prepare(slug, lod, name_style="class")
    rep = A.apply_overrides(slug, feats, attrs, idx, rpk) if with_overrides else None
    raw = "%s_%s_raw" % (slug, tag)
    for f in glob.glob(os.path.join(LAB, raw + "*")):
        os.remove(f)
    t = time.time()
    pyprt.ModelGenerator(shapes).generate_model(
        attrs, os.path.abspath(rpk), "com.esri.prt.codecs.GLTFEncoder",
        {"outputPath": LAB, "baseName": raw, "meshGranularity": "AS_GENERATED", "outputFormat": "GLB"})
    took = round(time.time() - t, 1)
    parts = sorted(glob.glob(os.path.join(LAB, raw + "_*.glb")))
    assert len(parts) == 1, parts
    out = os.path.join(LAB, "%s_%s_0.glb" % (slug, tag))
    m = merge(parts[0], out)
    os.remove(parts[0])
    return out, m, rep, took, attrs, idx


def positions(js, bn, prim):
    from glb_merge_per_building import accessor_raw
    data, n, fmt = accessor_raw(js, bn, prim["attributes"]["POSITION"])
    xs = struct.unpack_from("<%df" % (3 * n), data)
    return list(zip(xs[0::3], xs[1::3], xs[2::3]))


def measure(glb, footprints=None, podium_for=()):
    """Per building: height (max y - min y over its mesh), triangles, xz bbox; for podium_for, the top of the part
    that stands OUTSIDE the footprint by > 0.5 m - the podium set-out (podiumOut = 1.0 m), nothing else reaches it
    when the class draws no balconies."""
    from glb_merge_per_building import read_glb
    from shapely.geometry import Point, Polygon
    js, bn = read_glb(glb)
    out = {}
    for nd in js["nodes"]:
        if "mesh" not in nd:
            continue
        fi = int(nd["name"].split("_")[0][1:])
        ys, tris, xz = [], 0, [1e18, 1e18, -1e18, -1e18]
        pod_top = None
        poly = Polygon([(v[0], v[2]) for v in zip(*[iter(footprints[fi])] * 3)]) if (footprints and fi in podium_for) else None
        for pr in js["meshes"][nd["mesh"]]["primitives"]:
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            ys += [acc["min"][1], acc["max"][1]]
            tris += acc["count"] // 3
            xz = [min(xz[0], acc["min"][0]), min(xz[1], acc["min"][2]), max(xz[2], acc["max"][0]), max(xz[3], acc["max"][2])]
            if poly is not None:
                for x, y, z in positions(js, bn, pr):
                    if poly.exterior.distance(Point(x, z)) > 0.5 and not poly.contains(Point(x, z)):
                        pod_top = y if pod_top is None else max(pod_top, y)
        out[fi] = {"h": round(max(ys) - min(ys), 3), "ymin": round(min(ys), 3), "tris": tris,
                   "xz": [round(v, 1) for v in xz]}
        if poly is not None:
            out[fi]["podium_top"] = round(pod_top, 3) if pod_top is not None else None
    return out


def reports(slug, rpk, lod, fis):
    """Exact heights at LOD 0 (plain extrusion) + the rule's reports, through PyEncoder."""
    import pyprt
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    shapes, attrs, idx, _, _ = P.prepare(slug, lod, name_style="class")
    A.apply_overrides(slug, feats, attrs, idx, rpk)
    ms = pyprt.ModelGenerator(shapes).generate_model(attrs, os.path.abspath(rpk), "com.esri.pyprt.PyEncoder",
                                                     {"emitReport": True, "emitGeometry": True})
    out = {}
    for m in ms:
        fi = idx[m.get_initial_shape_index()]
        if fi in fis:
            ys = m.get_vertices()[1::3]
            r = m.get_report()
            out[fi] = {"h": round(max(ys) - min(ys), 3),
                       "Height_m": r.get("Height_m_sum"), "Podium_storeys": r.get("Podium_storeys_sum"),
                       "Storeys_est": r.get("Storeys_est_sum"), "cga_errors": list(m.get_cga_errors())}
    return out


# ------------------------------------------------------------------ main
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    slug = args[0] if args else "alyufrah1"
    t1, h1 = opt("--t1", 0, int), opt("--h1", 45.0, float)
    t2, h2 = opt("--t2", 6, int), opt("--h2", 90.0, float)
    pod = opt("--podium", 2, int)
    ovp = A.overrides_path(slug)
    if os.path.exists(ovp):
        os.replace(ovp, ovp + ".prev")          # the run owns this file; keep whatever was there
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    ev = {"slug": slug, "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "targets": {"t1": [t1, h1], "t2": [t2, h2, pod, "concrete"]}}

    # 1 BASE
    base_glb, base_m, _, s1, base_attrs, idx = build_glb(slug, RPK_V4, "base", False)
    verts, origin = A.local_verts(slug, feats, idx)
    base = measure(base_glb, verts, podium_for=(t2,))
    ev["base"] = {"glb": os.path.relpath(base_glb, ROOT), "buildings": base_m["buildings"], "triangles": base_m["triangles"],
                  "generate_s": s1, "t1": base[t1], "t2": base[t2]}
    # frame check: the GLB sits on its footprints (same local frame the overrides are measured in)
    xs = [verts[t1][i] for i in range(0, len(verts[t1]), 3)]; zs = [verts[t1][i] for i in range(2, len(verts[t1]), 3)]
    ev["frame_check_t1"] = {"footprint_xz": [round(min(xs), 1), round(min(zs), 1), round(max(xs), 1), round(max(zs), 1)],
                            "glb_xz": base[t1]["xz"]}

    # 2 CAPTURE from a mocked, staged lab scene
    ce = MockCE()
    pos = {fi: k for k, fi in enumerate(idx)}
    shape_of = {}
    SHIFT = (250.0, 0.0, -125.0)             # an arbitrary scene frame offset the capture must recover
    for fi in idx:
        a = base_attrs[pos[fi]]
        v = [c + SHIFT[i % 3] for i, c in enumerate(verts[fi])]
        obj = {k: a[k] for k in C.OBJECT_ATTRS if k in a}
        extra = {}
        if fi == t1:   # one Local Edit on t1, as CityEngine stores it
            extra["/shapeTree/localEdits/0;0;0;(0.0.1);Default$balconyBay"] = 5.0
        shape_of[fi] = ce.add(a["shapeName"], v, C.LAB_RULE, obj, extra)
    # swap two shapes' names: geometry must win over the name
    sa, sb = shape_of[idx[10]], shape_of[idx[11]]
    ce.sh[sa]["name"], ce.sh[sb]["name"] = ce.sh[sb]["name"], ce.sh[sa]["name"]
    # a production-rule shape with a USER edit: must be ignored (not a lab shape)
    prod = ce.add("b%d_render" % t1, [c + SHIFT[i % 3] for i, c in enumerate(verts[t1])], "/najma/rules/najma_v4.cga", {"bHeight": 12.0})
    ce.drag(prod, "bHeight", 333.0)
    # the drags
    ce.drag(shape_of[t1], "bHeight", h1)
    ce.drag(shape_of[t2], "bHeight", h2)
    ce.drag(shape_of[t2], "podiumStoreys", float(pod))
    ce.drag(shape_of[t2], "fclass", "concrete")
    ce.drag(shape_of[idx[12]], "floorH", 3.4)        # dragged and put back where it was: NOT an edit (no baseline -> captured)
    ce.sh[shape_of[idx[12]]]["obj"]["floorH"] = 3.4  #   ... staged with an object floorH 3.4, so equal -> skipped
    edits, crep, reverted = C.capture(ce, slug, feats, why="lab verification: synthetic handle drag (MockCE), not a real decision",
                                      scene_label="MockCE:/najma/scenes/lab/handles_%s.cej" % slug)
    ov, stale = C.merge_into(A.empty(slug), edits, reverted)
    C.write(slug, ov)
    ev["capture"] = {"report": crep, "file": os.path.relpath(ovp, ROOT), "heights": sorted(int(k) for k in ov["heights"]),
                     "attrs": {k: {a: v for a, v in e.items() if a in C.HANDLE_ATTRS} for k, e in ov["attrs"].items()},
                     "local_edits": sorted(int(k) for k in ov["local_edits"]),
                     "production_shape_ignored": "333.0" not in json.dumps(ov["heights"])}

    # 3 APPLY with the production rule
    v4_glb, v4_m, v4_rep, s3, _, _ = build_glb(slug, RPK_V4, "ovr_v4", True)
    v4 = measure(v4_glb, verts, podium_for=(t2,))
    ev["apply_v4"] = {"glb": os.path.relpath(v4_glb, ROOT), "report": v4_rep, "t1": v4[t1], "t2": v4[t2], "generate_s": s3}
    # what the rule should draw: mid-rise top = bHeight; tower top = bHeight - parapetH (sunk deck) + tallest plant box
    # (3.6 m when the variant is 1, else 4.0); podium parapet top = storeys x podiumFloorH 4.5 + parapetH 1.2
    v2 = int(base_attrs[idx.index(t2)]["fvar"])
    ev["expected"] = {"t1_h": h1, "t2_h_lod3": round(h2 - 1.2 + (3.6 if v2 == 1 else 4.0), 3), "t2_h_lod0": h2,
                      "t2_podium_top_auto": round((4 if h2 < 90 else 5 if h2 < 150 else 6) * 4.5 + 1.2, 3),
                      "t2_podium_top_override": round(pod * 4.5 + 1.2, 3)}

    # 4 APPLY with the lab rule (podium moves)
    lab_glb, lab_m, lab_rep, s4, _, _ = build_glb(slug, RPK_LAB, "ovr_lab", True)
    lab = measure(lab_glb, verts, podium_for=(t2,))
    ev["apply_lab"] = {"glb": os.path.relpath(lab_glb, ROOT), "report": lab_rep, "t1": lab[t1], "t2": lab[t2], "generate_s": s4}

    # 5 LAB rule idle == BASE
    idle_glb, _, _, _, _, _ = build_glb(slug, RPK_LAB, "lab_idle", False)
    idle = measure(idle_glb)
    diff = [fi for fi in base if base[fi]["tris"] != idle[fi]["tris"] or abs(base[fi]["h"] - idle[fi]["h"]) > 1e-3]
    ev["lab_rule_idle_equals_base"] = {"buildings": len(base), "differ": diff}

    # locality: nothing but the targets moved
    moved_v4 = [fi for fi in base if fi not in (t1, t2) and (base[fi]["tris"] != v4[fi]["tris"] or abs(base[fi]["h"] - v4[fi]["h"]) > 1e-3)]
    moved_lab = [fi for fi in base if fi not in (t1, t2) and (base[fi]["tris"] != lab[fi]["tris"] or abs(base[fi]["h"] - lab[fi]["h"]) > 1e-3)]
    ev["locality"] = {"others_changed_v4": moved_v4, "others_changed_lab": moved_lab}

    # 6 REBUILD from scratch: same file, same result
    re_glb, _, _, _, _, _ = build_glb(slug, RPK_LAB, "ovr_lab_rebuild", True)
    again = measure(re_glb, verts, podium_for=(t2,))
    ev["rebuild_identical"] = all(again[fi] == lab[fi] for fi in lab)

    # 7 LOD 0 exact + reports
    ev["lod0_lab"] = reports(slug, RPK_LAB, 0, (t1, t2))
    ev["lod3_reports_lab"] = reports(slug, RPK_LAB, 3, (t1, t2))

    # 8 LOGIC: re-key, orphan, reviewed precedence
    n = len(feats)
    rev = list(reversed(feats))
    hs, _, rk = A.resolve(slug, rev, ov, reviewed={})
    ok_rekey = hs == {n - 1 - t1: h1, n - 1 - t2: h2}
    moved = copy.deepcopy(ov); moved["heights"][str(t1)]["fp"]["c"][0] += 25.0
    _, _, orp = A.resolve(slug, feats, moved, reviewed={})
    _, _, pr1 = A.resolve(slug, feats, ov, reviewed={str(t1): {"height_m": 30.0, "why": "x"}, str(t2): {"height_m": h2, "why": "y"}})
    _, _, pr2 = A.resolve(slug, feats, ov, reviewed={str(t1): {"hold": True, "why": "z"}})
    # a second session: the scene is re-staged WITH the first edits (object bHeight = 45), the person drags again
    ce2 = MockCE()
    s0 = ce2.add("b%d_x" % t1, [c + SHIFT[i % 3] for i, c in enumerate(verts[t1])], C.LAB_RULE, {"bHeight": h1})
    for fi in idx[1:8]:
        ce2.add("b%d_x" % fi, [c + SHIFT[i % 3] for i, c in enumerate(verts[fi])], C.LAB_RULE, {"bHeight": 12.0})
    ce2.drag(s0, "bHeight", h1 + 5.0)
    e2, _, rv2 = C.capture(ce2, slug, feats, scene_label="MockCE session 2")
    ov2, _ = C.merge_into(copy.deepcopy(ov), e2, rv2)
    second = ov2["heights"][str(t1)]
    _, _, st = A.resolve(slug, feats, ov, reviewed={}, data_heights={t1: 30.0})
    ev["logic"] = {
        "second_session": {"height_m": second["height_m"], "baseline_m": second["baseline_m"], "history": second.get("history"),
                           "why": second.get("why")},
        "stale_when_data_moved": st["stale"],
        "reordered_geojson_rekeyed": ok_rekey, "rekeyed": rk["rekeyed"][:4],
        "moved_footprint_orphaned": orp["orphans"], "moved_footprint_applied": orp["applied_heights"],
        "reviewed_differs_conflict": pr1["conflicts"], "reviewed_equal_promoted": pr1["promoted"],
        "reviewed_hold_conflict": pr2["conflicts"], "applied_when_reviewed": pr1["applied_heights"] + pr2["applied_heights"]}

    json.dump(ev, open(os.path.join(LAB, "verify_%s.json" % slug), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    # ---- console summary
    print("BASE  %d buildings, %d tris  b%d h %.2f  b%d h %.2f podium_top %s" % (base_m["buildings"], base_m["triangles"], t1, base[t1]["h"], t2, base[t2]["h"], base[t2].get("podium_top")))
    print("frame t1 footprint %s  glb %s" % (ev["frame_check_t1"]["footprint_xz"], ev["frame_check_t1"]["glb_xz"]))
    print("CAPTURE heights %s attrs %s local_edits %s  notes %s  prod-shape ignored %s" % (ev["capture"]["heights"], ev["capture"]["attrs"], ev["capture"]["local_edits"], crep["mapping_notes"], ev["capture"]["production_shape_ignored"]))
    print("EXPECTED %s" % ev["expected"])
    print("APPLY v4   b%d h %.2f  b%d h %.2f podium_top %s  unknown_to_rule %s" % (t1, v4[t1]["h"], t2, v4[t2]["h"], v4[t2].get("podium_top"), v4_rep["unknown_to_rule"]))
    print("APPLY lab  b%d h %.2f  b%d h %.2f podium_top %s" % (t1, lab[t1]["h"], t2, lab[t2]["h"], lab[t2].get("podium_top")))
    print("lab idle == base: differ %s   locality v4 %s lab %s   rebuild identical %s" % (diff, moved_v4, moved_lab, ev["rebuild_identical"]))
    print("LOD0 lab %s" % ev["lod0_lab"])
    print("LOD3 reports lab %s" % ev["lod3_reports_lab"])
    print("LOGIC rekey %s  orphan %s  conflict %s  promoted %s  hold %s" % (ok_rekey, orp["orphans"], pr1["conflicts"], pr1["promoted"], pr2["conflicts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
