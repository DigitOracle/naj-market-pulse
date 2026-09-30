"""LAB (handles, research only): capture handle edits OUT of an open CityEngine lab scene into a per-building file.

The loop this closes:
  1. --stage <slug>   builds a LAB scene /najma/scenes/lab/handles_<slug>.cej (a new file - never a production scene)
                      from buildings.geojson in the same local frame and with the same resolved attributes the
                      headless build uses (lab_handles_apply: geojson + register + height_overrides.json + any
                      earlier handle edits), shapes named b<fi>_<class>, object-sourced, rule
                      /najma/rules/lab/handles/najma_v4_handles.cga.
  2. A person drags handles in the viewport (height, podium, floor height, balcony bay, facade class selector).
     CityEngine records each drag on the INITIAL SHAPE as rule attribute /ce/rule/<attr> with source USER.
  3. capture <slug>   reads every shape carrying a lab handles rule, keeps the attributes whose source is USER and
                      whose value differs from the object value it was staged with, maps the shape to its feature
                      index (name b<fi>, checked against the footprint centroid), and upserts
                      data/lab/handles/overrides_<slug>.json. bHeight goes to "heights" in height_overrides.json's
                      schema, everything else to "attrs". Earlier values are kept under "history".
  4. Every headless rebuild applies that file (lab_handles_apply.apply_overrides). The scene can be thrown away.

Local Edits (Tutorial 20's Local Edits tool) are stored by CityEngine as object attributes named
"/shapeTree/localEdits/<shape-tree path>;Default$<attr>" (seen in Tutorial_20 Simple_Building_LE_04.cej). They are
captured raw under "local_edits" for the record, but NOT replayed: the path is an index into the generated shape
tree, so any change to a split renumbers it, and PRT has no documented way to take them. Promote a local edit to a
per-building attribute instead.

Uses the data/ce/.ce_lock protocol of scripts/export_najma_rpk.py (wait, own line, remove only if ours).

  python scripts/lab_handles_capture.py capture alyufrah1 [--why "..."] [--dry-run]
  python scripts/lab_handles_capture.py stage alyufrah1          (creates + saves the LAB scene; opens nothing else)
  python scripts/lab_handles_capture.py promote alyufrah1        (writes the height_overrides.json fragment to review)
"""
import datetime
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
LAB = os.path.join(ROOT, "data", "lab", "handles")
LOCK = os.path.join(CEDIR, ".ce_lock")
sys.path.insert(0, HERE)
import lab_handles_apply as A  # noqa: E402

LAB_RULE = "/najma/rules/lab/handles/najma_v4_handles.cga"
LAB_RULE_DIR = "/najma/rules/lab/handles/"
HANDLE_ATTRS = ["bHeight", "podiumStoreys", "floorH", "fclass", "balconyBay", "podiumLevels", "fvar", "facadeVariant"]
OBJECT_ATTRS = ("bHeight", "status", "levels", "fclass", "fvar", "pctComplete")   # staged OBJECT-sourced, as ce_batch_v2
LOCAL_EDIT_PREFIX = "/shapeTree/localEdits/"
BID = re.compile(r"^b(\d+)(?:_|$)")
TAG = "lab_handles_capture pid %d" % os.getpid()
NUM_TOL = 1e-3


# ------------------------------------------------------------------ lock (export_najma_rpk.py protocol)
def take_lock(max_wait_s=3600):
    t0 = time.time()
    while os.path.exists(LOCK):
        held = open(LOCK, encoding="utf-8", errors="ignore").read().strip()
        if time.time() - t0 > max_wait_s:
            sys.exit("gave up: CE lock still held by '%s'" % held)
        print("  CE lock held by '%s' - waiting" % held, flush=True)
        time.sleep(20)
    with open(LOCK, "w", encoding="utf-8") as fh:
        fh.write("%s %s" % (TAG, time.strftime("%Y-%m-%dT%H:%M:%S")))


def release_lock():
    try:
        if open(LOCK, encoding="utf-8").read().startswith(TAG):
            os.remove(LOCK)
    except OSError:
        pass


# ------------------------------------------------------------------ helpers
def same(a, b):
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= NUM_TOL
    except (TypeError, ValueError):
        return str(a) == str(b)


def plain(v):
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    try:
        return float(v)
    except Exception:
        return str(v)


def shape_centroid_en(ce, s):
    """Scene frame -> (E', N') up to the frame offset: x = easting, z = -northing."""
    v = list(ce.getVertices(s))
    return A.centroid_area(zip(v[0::3], [-z for z in v[2::3]]))[0]


def lab_shapes(ce):
    out = []
    for s in ce.getObjectsFrom(ce.scene, ce.isShape):
        rf = str(ce.getRuleFile(s) or "")
        if LAB_RULE_DIR in rf.replace("\\", "/"):
            out.append(s)
    return out


def map_to_features(ce, shapes, feats, fps):
    """shape -> feature index. Name first (b<fi>), then checked against the footprint centroid after removing the
    scene's frame offset (median over all named shapes); a name that disagrees with its geometry falls back to the
    nearest footprint and is reported."""
    named = []
    for s in shapes:
        m = BID.match(str(ce.getName(s) or ""))
        named.append((s, int(m.group(1)) if m and int(m.group(1)) < len(feats) else None, shape_centroid_en(ce, s)))
    # the staged scene is in pyprt_district's local frame: E' = E - ox, N' = N - oz. Recover the offset robustly.
    dx = sorted(c[0] - fps[fi]["c"][0] for _, fi, c in named if fi is not None)
    dy = sorted(c[1] - fps[fi]["c"][1] for _, fi, c in named if fi is not None)
    off = (dx[len(dx) // 2], dy[len(dy) // 2]) if dx else (0.0, 0.0)
    out, notes = {}, []
    for s, fi, c in named:
        e, n = c[0] - off[0], c[1] - off[1]
        if fi is not None and math.hypot(e - fps[fi]["c"][0], n - fps[fi]["c"][1]) < 3.0:
            out[s] = fi; continue
        j = min(range(len(fps)), key=lambda k: (fps[k]["c"][0] - e) ** 2 + (fps[k]["c"][1] - n) ** 2)
        d = math.hypot(fps[j]["c"][0] - e, fps[j]["c"][1] - n)
        if d < 3.0:
            out[s] = j; notes.append({"shape": str(ce.getName(s)), "name_says": fi, "geometry_says": j})
        else:
            notes.append({"shape": str(ce.getName(s)), "name_says": fi, "unmatched": round(d, 1)})
    return out, notes, off


# ------------------------------------------------------------------ capture
def capture(ce, slug, feats, why=None, scene_label=None):
    """Read USER-sourced handle attributes and local edits from the open scene. Returns (edits, report)."""
    fps = [A.fingerprint(f) for f in feats]
    shapes = lab_shapes(ce)
    mapping, notes, off = map_to_features(ce, shapes, feats, fps)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    edits = {"heights": {}, "attrs": {}, "local_edits": {}}
    reverted = []
    for s, fi in mapping.items():
        for a in HANDLE_ATTRS:
            try:
                src = str(ce.getAttributeSource(s, "/ce/rule/" + a) or "").upper()
            except Exception:
                continue
            val = plain(ce.getAttribute(s, "/ce/rule/" + a))
            base = plain(ce.getAttribute(s, a))          # the object value it was staged with (None if none)
            if src != "USER":
                reverted.append((fi, a))
                continue
            if base is not None and same(val, base):
                continue                                  # touched and put back: not an edit
            prov = {"captured": now, "scene": scene_label, "shape": str(ce.getName(s)), "fp": fps[fi]}
            if a == "bHeight":
                edits["heights"][str(fi)] = {"height_m": round(float(val), 2),
                                             "why": why or "handle drag in the CityEngine lab scene - needs a why before promotion",
                                             "source": "handle", "baseline_m": base, **prov}
            else:
                e = edits["attrs"].setdefault(str(fi), dict(prov, baseline={}))
                e[a] = val
                e["baseline"][a] = base
                if why:
                    e["why"] = why
        try:
            names = [str(n) for n in ce.getAttributeList(s)]
        except Exception:
            names = []
        le = {n: plain(ce.getAttribute(s, n)) for n in names if n.startswith(LOCAL_EDIT_PREFIX)}
        if le:
            edits["local_edits"][str(fi)] = {"captured": now, "replayable": False, "raw": le, "fp": fps[fi]}
    rep = {"slug": slug, "scene": scene_label, "lab_shapes": len(shapes), "mapped": len(mapping), "frame_offset": off,
           "mapping_notes": notes, "heights": len(edits["heights"]), "attr_buildings": len(edits["attrs"]),
           "local_edit_buildings": len(edits["local_edits"]),
           "not_user_sourced": len(reverted)}
    return edits, rep, reverted


def merge_into(ov, edits, reverted_pairs=()):
    """Upsert captured edits; the previous value of anything replaced goes to that entry's history."""
    for sect in ("heights", "attrs", "local_edits"):
        for k, e in edits[sect].items():
            old = ov[sect].get(k)
            if old and sect == "attrs":
                hist = old.get("history", [])
                changed = {a: old[a] for a in e if a in old and a not in A.PROVENANCE and not same(old[a], e[a])}
                if changed:
                    hist.append({"until": e["captured"], **changed})
                merged = dict(old); merged.update(e); merged["baseline"] = dict(e["baseline"], **old.get("baseline", {}))   # first baseline wins
                if hist:
                    merged["history"] = hist
                ov[sect][k] = merged
            elif old and sect == "heights":
                # the staged scene carries the earlier handle value as its object bHeight, so this capture's baseline
                # is that edit, not the data: keep the FIRST baseline, it is what "stale" is measured against
                e["baseline_m"] = old.get("baseline_m", e.get("baseline_m"))
                if not same(old.get("height_m"), e["height_m"]):
                    e["history"] = old.get("history", []) + [{"until": e["captured"], "height_m": old["height_m"]}]
                else:
                    e["history"] = old.get("history", [])
                    if old.get("why") and "needs a why" in e.get("why", ""):
                        e["why"] = old["why"]
                ov[sect][k] = e
            else:
                ov[sect][k] = e
    # an attribute that is in the file but is no longer USER-sourced in the scene was reset by the person: report it,
    # do not silently drop it (the scene might simply be stale)
    stale = [{"b": fi, "attr": a} for fi, a in reverted_pairs
             if (a == "bHeight" and str(fi) in ov["heights"]) or (a != "bHeight" and a in ov["attrs"].get(str(fi), {}))]
    return ov, stale


def write(slug, ov, path=None):
    p = path or A.overrides_path(slug)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    ov["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    json.dump(ov, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return p


def promote_fragment(slug, ov):
    """The height_overrides.json entries a reviewer would paste in: same keys, same schema, why kept."""
    return {"districts": {slug: {k: {"height_m": e["height_m"], "why": e.get("why", ""),
                                     "source": "handle", "captured": e.get("captured")}
                                 for k, e in ov["heights"].items()}}}


# ------------------------------------------------------------------ stage (creates the LAB scene)
def stage(ce, slug, lod=3):
    """New lab scene, shapes in pyprt_district's local frame, resolved attributes pushed OBJECT-sourced (the handle
    baseline), lab rule assigned. Opens and saves ONLY /najma/scenes/lab/handles_<slug>.cej."""
    import pyprt_district as P
    shapes, attrs, idx, skipped, origin = P.prepare(slug, lod, name_style="class")
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    rpk = os.path.join(LAB, "najma_v4_handles.rpk")
    rep = A.apply_overrides(slug, feats, attrs, idx, rpk)   # earlier handle edits become the new baseline
    verts, _ = A.local_verts(slug, feats, idx)
    scene = "/najma/scenes/lab/handles_%s.cej" % slug
    ce.newFile(scene)
    layer = ce.addShapeLayer("buildings")
    made = []
    for fi, a in zip(idx, attrs):
        s = ce.createShape(layer, verts[fi])
        ce.setName(s, a["shapeName"])
        made.append((s, a))
    for name in OBJECT_ATTRS + ("podiumStoreys", "floorH", "balconyBay", "podiumLevels"):
        for s, a in made:
            if name in a:
                ce.setAttribute([s], name, a[name])
                try:
                    ce.setAttributeSource([s], "/ce/rule/" + name, "OBJECT")
                except Exception:
                    pass
    allsh = [s for s, _ in made]
    ce.setRuleFile(allsh, LAB_RULE)
    ce.setStartRule(allsh, "Lot")
    ce.setAttribute(allsh, "/ce/rule/LOD", lod)
    ce.generateModels(allsh)
    ce.saveFile(scene)
    return {"scene": scene, "shapes": len(made), "skipped": skipped, "origin_ce_xz": origin, "apply": rep}


# ------------------------------------------------------------------ CLI
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2 or args[0] not in ("capture", "stage", "promote"):
        print(__doc__); return 2
    cmd, slug = args[0], args[1]
    opt = lambda n, d=None: sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    if cmd == "promote":
        ov = A.load(slug)
        p = os.path.join(LAB, "height_overrides_promote_%s.json" % slug)
        json.dump(promote_fragment(slug, ov), open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("wrote %s - review, then merge into scripts/height_overrides.json by hand" % os.path.relpath(p, ROOT))
        return 0
    take_lock()
    try:
        from cityengine import CE
        ce = CE()
        if cmd == "stage":
            print(json.dumps(stage(ce, slug), indent=1, default=str)); return 0
        edits, rep, reverted = capture(ce, slug, feats, why=opt("--why"), scene_label="/najma/scenes/lab/handles_%s.cej" % slug)
    finally:
        release_lock()
    ov, stale = merge_into(A.load(slug), edits, reverted)
    rep["file_entries_reset_in_scene"] = stale
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if "--dry-run" not in sys.argv:
        print("wrote", os.path.relpath(write(slug, ov), ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
