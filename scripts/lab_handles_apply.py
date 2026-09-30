"""LAB (handles, research only): apply per-building handle edits to the headless build, on every rebuild.

A handle drag in CityEngine lives only in the scene, and the production builds never save a scene (ce_batch_v2 sets
SAVE = False for v3/v4) - so it would be gone on the next rebuild. scripts/lab_handles_capture.py lifts the edits out
into data/lab/handles/overrides_<slug>.json; this module folds that file into the per-shape attributes the build
pushes, so the edit is re-applied every time the district regenerates from buildings.geojson.

ONE HEIGHT, ONE HOME. bHeight already has a reviewed home, scripts/height_overrides.json, and this file does not
compete with it:
  * the "heights" section uses height_overrides.json's own entry schema ({height_m, why} + provenance), so promoting a
    handle height is a copy of the entry, not a translation;
  * precedence: geojson  <  heights register (candidate rule)  <  handle height (captured, unreviewed)  <
    height_overrides.json (reviewed). A reviewed entry - height_m OR hold - always wins, and a handle entry for the
    same building is reported (as "promoted" when the values agree, "conflict" when they do not), never applied;
  * a handle height suppresses the register candidate, exactly as a reviewed override does: a person has decided.
Every other attribute (podiumStoreys, floorH, fclass, balconyBay, ...) lives in the "attrs" section; fclass there
outranks facade_v2.json for that one building.

KEYED BY slug + FEATURE INDEX, BUT CHECKED. A feature index is only as stable as buildings.geojson's feature order,
so every entry carries the footprint's fingerprint (UTM centroid + area). If the feature at that index no longer
matches, the entry is re-keyed to the feature that does, or reported as an orphan and NOT applied - it never lands on
a neighbour's footprint. Entries with no fingerprint apply by index with a warning.

Library use (what a production build would call, see data/lab/handles/INTEGRATION.patch):
    from lab_handles_apply import apply_overrides
    report = apply_overrides(slug, feats, attrs, idx, rpk)      # mutates attrs in place

CLI (prints what would apply, builds nothing):
    python scripts/lab_handles_apply.py alyufrah1 [--rpk data/lab/handles/najma_v4_handles.rpk] [--overrides path]
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
LAB = os.path.join(ROOT, "data", "lab", "handles")
REVIEWED = os.path.join(HERE, "height_overrides.json")
sys.path.insert(0, HERE)

FP_CENTROID_M = 1.0      # a footprint that moved more than this is a different footprint
FP_AREA_REL = 0.02       # ... or whose area changed by more than 2 %
STALE_M = 0.5            # the data under a height edit moved by more than this since the drag
PROVENANCE = ("fp", "baseline", "captured", "scene", "shape", "why", "history", "source")   # not rule attributes


def overrides_path(slug):
    return os.path.join(LAB, "overrides_%s.json" % slug)


def empty(slug):
    return {"slug": slug, "schema": "handles-overrides/1", "heights": {}, "attrs": {}, "local_edits": {}}


def load(slug, path=None):
    p = path or overrides_path(slug)
    if not os.path.exists(p):
        return empty(slug)
    d = json.load(open(p, encoding="utf-8"))
    for k in ("heights", "attrs", "local_edits"):
        d.setdefault(k, {})
    return d


def reviewed_heights(slug, path=None):
    p = path or REVIEWED
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8")).get("districts", {}).get(slug, {})


# ------------------------------------------------------------------ fingerprints
_TF = None


def _tf():
    global _TF
    if _TF is None:
        from pyproj import Transformer
        _TF = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    return _TF


def fingerprint(feature):
    """Outer ring of the first part (what CE's SHP import and pyprt_district keep) -> UTM centroid + area."""
    g = feature["geometry"]
    ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
    pts = [_tf().transform(c[0], c[1]) for c in ring]
    (cx, cy), a = centroid_area(pts)
    return {"c": [round(cx, 2), round(cy, 2)], "a": round(a, 1)}


def centroid_area(pts):
    """Area centroid + |area| of a ring. The AREA centroid, not the vertex mean: on an irregular outline (one side
    finely digitised) the two sit metres apart, and the capture compares a scene shape against this."""
    pts = list(pts)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    a = cx = cy = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % len(pts)]
        cr = x0 * y1 - x1 * y0
        a += cr; cx += (x0 + x1) * cr; cy += (y0 + y1) * cr
    a *= 0.5
    if abs(a) < 1e-9:
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    else:
        cx, cy = cx / (6 * a), cy / (6 * a)
    return (cx, cy), abs(a)


def fp_match(fp, ref):
    if not fp or not ref:
        return False
    d = math.hypot(fp["c"][0] - ref["c"][0], fp["c"][1] - ref["c"][1])
    return d <= FP_CENTROID_M and abs(fp["a"] - ref["a"]) <= FP_AREA_REL * max(ref["a"], 1.0)


def rekey(entries, feats, fps=None):
    """{fi: entry} -> ({fi_now: entry}, notes). fps = precomputed fingerprints per feature (list)."""
    fps = fps if fps is not None else [fingerprint(f) for f in feats]
    out, notes = {}, {"rekeyed": [], "orphans": [], "unverified": []}
    for k, e in entries.items():
        fi = int(k)
        fp = e.get("fp")
        if fp is None:
            if 0 <= fi < len(feats):
                out[fi] = e; notes["unverified"].append(fi)
            else:
                notes["orphans"].append({"was": fi, "why": "index out of range, no fingerprint"})
            continue
        if 0 <= fi < len(feats) and fp_match(fp, fps[fi]):
            out[fi] = e; continue
        hits = [j for j, r in enumerate(fps) if fp_match(fp, r)]
        if len(hits) == 1:
            out[hits[0]] = e; notes["rekeyed"].append({"was": fi, "now": hits[0]})
        else:
            notes["orphans"].append({"was": fi, "why": "footprint not found" if not hits else "footprint ambiguous %s" % hits})
    return out, notes


def local_verts(slug, feats, idx):
    """Footprint vertex lists in pyprt_district's local CE frame (x = E - ox, y = 0, z = -(N - oz)), per feature
    index - the exact coordinates prepare() hands PyPRT, for staging a lab scene or measuring a GLB against."""
    import pyprt_district as P
    ox, oz = P.district_origin(feats, _tf())
    return {fi: P.footprint(P.rings(feats[fi]["geometry"])[0], _tf(), ox, oz) for fi in idx}, (ox, oz)


# ------------------------------------------------------------------ resolution
def base_height(pr):
    try:
        return float(pr.get("bHeight") or 0)
    except (TypeError, ValueError):
        return 0.0


def resolve(slug, feats, ov=None, reviewed=None, fps=None, data_heights=None):
    """Per feature index: what the handle file changes, after precedence and re-keying.
    data_heights = {fi: m} the height the build would use WITHOUT the handle file (geojson + register + reviewed);
    defaults to the raw geojson bHeight. It is what "stale" is measured against.
    Returns (heights {fi: m}, attrs {fi: {name: value}}, report)."""
    ov = ov if ov is not None else load(slug)
    reviewed = reviewed if reviewed is not None else reviewed_heights(slug)
    fps = fps if fps is not None else [fingerprint(f) for f in feats]
    hs, hn = rekey(ov.get("heights", {}), feats, fps)
    at, an = rekey(ov.get("attrs", {}), feats, fps)
    rep = {"slug": slug, "applied_heights": [], "applied_attrs": [], "promoted": [], "conflicts": [], "stale": [],
           "rekeyed": hn["rekeyed"] + an["rekeyed"], "orphans": hn["orphans"] + an["orphans"],
           "unverified_keys": sorted(set(hn["unverified"] + an["unverified"])),
           "local_edits_not_replayed": sorted(int(k) for k in ov.get("local_edits", {}))}
    heights = {}
    for fi, e in sorted(hs.items()):
        h = float(e["height_m"])
        rv = reviewed.get(str(fi)) or {}
        if rv.get("height_m") or rv.get("hold"):
            reviewed_val = float(rv["height_m"]) if rv.get("height_m") else "hold"
            if reviewed_val != "hold" and abs(reviewed_val - h) < 0.05:
                rep["promoted"].append({"b": fi, "height_m": h, "note": "already in height_overrides.json - delete the handle entry"})
            else:
                rep["conflicts"].append({"b": fi, "handle_m": h, "reviewed": reviewed_val,
                                         "note": "height_overrides.json is reviewed and wins; handle value NOT applied"})
            continue
        b0 = e.get("baseline_m")
        now = (data_heights or {}).get(fi, base_height(feats[fi]["properties"]))
        if b0 is not None and abs(float(now) - float(b0)) > STALE_M:
            rep["stale"].append({"b": fi, "baseline_m": b0, "data_now_m": now, "handle_m": h,
                                 "note": "the source moved under the edit; still applied - a person should re-check"})
        heights[fi] = h
        rep["applied_heights"].append({"b": fi, "height_m": h})
    attrs = {}
    for fi, e in sorted(at.items()):
        vals = {k: v for k, v in e.items() if k not in PROVENANCE}
        if vals:
            attrs[fi] = vals
            rep["applied_attrs"].append({"b": fi, **vals})
    return heights, attrs, rep


def _cast(v, typ):
    if typ == "float":
        return float(v)
    if typ == "bool":
        return bool(v) if not isinstance(v, str) else v.strip().lower() in ("1", "true", "yes")
    return str(v)


def apply_overrides(slug, feats, attrs_list, idx, rpk, path=None, reviewed=None):
    """Fold the handle file into PyPRT per-shape attribute dicts (as pyprt_district.prepare returns them), in place.

    attrs_list[k] belongs to feature idx[k]. bHeight in attrs_list already carries geojson + register + reviewed
    overrides (pyprt_district.heights); a handle height replaces it only where no reviewed entry exists, which also
    drops the register candidate for that building. Attributes the rule package does not declare are reported and
    skipped - PRT would ignore them silently, and a silent no-op is how an edit gets lost."""
    import pyprt
    known = pyprt.get_rpk_attributes_info(os.path.abspath(rpk))
    pos = {fi: k for k, fi in enumerate(idx)}
    data_h = {fi: attrs_list[k].get("bHeight", 0.0) for fi, k in pos.items()}
    heights, attrs, rep = resolve(slug, feats, load(slug, path), reviewed, data_heights=data_h)
    rep["unknown_to_rule"] = []
    rep["rule"] = os.path.basename(rpk)
    for fi, h in heights.items():
        if fi in pos:
            attrs_list[pos[fi]]["bHeight"] = float(h)
    for fi, vals in attrs.items():
        if fi not in pos:
            continue
        a = attrs_list[pos[fi]]
        for name, v in vals.items():
            if name not in known:
                rep["unknown_to_rule"].append({"b": fi, "attr": name, "value": v})
                continue
            a[name] = _cast(v, known[name]["type"])
            if name == "fclass" and a.get("shapeName", "").startswith("b%d_" % fi):
                a["shapeName"] = "b%d_%s" % (fi, a["fclass"])     # the class travels in the mesh name
    return rep


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    slug = args[0]
    opt = lambda n, d=None: sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d
    feats = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"]
    ovp = opt("--overrides")
    heights, attrs, rep = resolve(slug, feats, load(slug, ovp))
    rpk = opt("--rpk")
    if rpk:
        import pyprt
        known = pyprt.get_rpk_attributes_info(os.path.abspath(rpk))
        rep["unknown_to_rule"] = [{"b": fi, "attr": k} for fi, v in attrs.items() for k in v if k not in known]
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
