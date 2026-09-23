"""STAGE 1 of Business Bay in Unreal: bring in the CityEngine LOD 3 district and prove the 193 towers are there.

Run inside Unreal's Python console (Window > Developer Tools > Output Log, switch the entry box to Python):

    exec(open(r"C:\\Dev\\naj-market-pulse\\scripts\\ue_businessbay_stage1.py").read())

WHY IT RENDERS NOTHING. Committing to 193 renders before knowing that the actors exist, are named as expected and are
the right size is how you spend an evening producing 193 wrong clips. This stage answers three questions and stops:

  1. did the full district import, and how many actors came in
  2. do the 193 target buildings resolve to actors, by name
  3. is the scale right - a tower we believe is 252.6 m should measure ~25,260 uu, because Unreal is centimetres

It writes data/board/unreal_stage1_businessbay.json with what it found, including every target it could NOT resolve,
so the failures are a list rather than a silence.

WHAT IT DELIBERATELY DOES NOT ASSUME. The CityEngine -> Unreal transform involves a Y-up to Z-up swap, a metres to
centimetres scale and a sign convention on northing. Rather than reproduce that arithmetic and hope, this reads each
actor's own world bounds out of the editor. The anchors file is used only to CHECK the result, never to place anything.

THE SOBHA LENS IS ALREADY IN THIS LEVEL, and that is why this script is scoped rather than counting actors. The Sobha
session's ue_sobha_lens.py imports businessbay_SOBHA_lod3.udatasmith - a 29-building subset cut from the same source,
so its actors carry the SAME b<i>_ labels as the full district: b26, b27, b28, b88 and b292 are in both. A bare label
search would return two actors for those five and pick whichever came first, which for them is a coral-tinted Sobha
copy. So targets are resolved only among the descendants of the FULL district's own DatasmithSceneActor, and any
label that also exists outside it is recorded as a collision instead of being quietly resolved.

The lens also runs SOBHA_ONLY: every non-Sobha building already in the level is hidden. Newly imported actors are not,
so the district arrives visible - but if the manifest changes and the lens re-runs on next open, it will hide these
too. That is a stage 2 problem, noted here so it is not a surprise then.
"""
import json
import os
import unreal

ROOT = r"C:\Dev\naj-market-pulse"
TARGETS = os.path.join(ROOT, "data", "board", "unreal_targets_businessbay.json")
CE_REPORT = os.path.join(ROOT, "data", "ce", "businessbay", "report_v4.json")
DATASMITH = os.path.join(ROOT, "data", "ce", "_datasmith", "businessbay_lod3.udatasmith")
REPORT = os.path.join(ROOT, "data", "board", "unreal_stage1_businessbay.json")
DEST = "/Game/Azimuth/BusinessBay"
SCENE_TAG = "businessbay_lod3"

ell = unreal.EditorLevelLibrary


def log(msg):
    unreal.log("[azimuth] " + str(msg))


def scene_actor():
    """The DatasmithSceneActor for the FULL district, if this level already holds it."""
    for a in ell.get_all_level_actors():
        if isinstance(a, unreal.DatasmithSceneActor):
            lab = (a.get_actor_label() or "").lower()
            if SCENE_TAG in lab and "sobha" not in lab:
                return a
    return None


def import_district():
    """Import via DatasmithSceneElement - the route ue_sobha_lens.py uses, which ran successfully today."""
    if not os.path.exists(DATASMITH):
        log("MISSING: " + DATASMITH)
        return False
    scene = unreal.DatasmithSceneElement.construct_datasmith_scene_from_file(DATASMITH)
    if scene is None:
        log("Datasmith could not open " + DATASMITH)
        return False
    opts = scene.get_options()
    try:
        opts.base_options.include_light = False
        opts.base_options.include_camera = False
        opts.base_options.include_animation = False
        opts.base_options.static_mesh_options.generate_lightmap_u_vs = False
    except Exception as e:
        log("(import options left default: %s)" % e)
    res = scene.import_scene(DEST)
    scene.destroy_scene()
    ok = bool(res and res.import_succeed)
    log("import %s: %d actors -> %s" % ("ok" if ok else "FAILED", len(res.imported_actors) if ok else 0, DEST))
    return ok


def descendants(actor):
    """Every actor attached under this one, at any depth. Datasmith parents each building to the scene actor."""
    out, stack = [], [actor]
    while stack:
        cur = stack.pop()
        try:
            kids = cur.get_attached_actors()
        except Exception:
            kids = []
        for k in kids:
            out.append(k)
            stack.append(k)
    return out


def prefix_of(label):
    """b84_glassblue_sexistingMesh -> b84. Unreal suffixes duplicate labels, which never touches the prefix."""
    return (label or "").split("_")[0]


def ce_heights():
    """What CityEngine actually GENERATED, per shape, from the district's own v4 report.

    Two different heights reach this script and confusing them would make stage 1 lie. The twin height is what the
    registers say the building is; the CE height is what the rule built. A mismatch between the twin height and the
    measured actor is a DATA disagreement; a mismatch between the CE height and the measured actor is a TRANSFORM
    problem, and only the second one is what "scale" means. Since build_unreal_targets.py takes each target's height
    from this same report they now agree by construction, so the ratio below is a clean scale test. It is carried
    anyway: the day the targets are rebuilt from another source, this is the field that says so.
    """
    out = {}
    try:
        for r in json.load(open(CE_REPORT, encoding="utf-8"))["rows"]:
            nm = str(r.get("shape") or "")
            if nm.startswith("b") and "_" in nm:
                out[int(nm[1:nm.index("_")])] = r.get("height_m")
    except Exception as e:
        log("(no CE report: %s)" % e)
    return out


def main():
    towers = json.load(open(TARGETS, encoding="utf-8"))["towers"]
    ceh = ce_heights()
    log("targets: %d towers | CE report heights: %d shapes" % (len(towers), len(ceh)))

    sa = scene_actor()
    if sa is None:
        log("full district not in level - importing " + os.path.basename(DATASMITH))
        import_district()
        sa = scene_actor()
    if sa is None:
        log("STILL no DatasmithSceneActor for %s - stopping, stage 2 has nothing to stand on" % SCENE_TAG)
        return
    log("district scene actor: " + (sa.get_actor_label() or "?"))

    mine = [a for a in descendants(sa) if isinstance(a, unreal.StaticMeshActor)]
    log("static mesh actors under the district: %d (export holds 654 buildings)" % len(mine))

    by_prefix = {}
    for a in mine:
        by_prefix.setdefault(prefix_of(a.get_actor_label()), []).append(a)

    # anything with the same prefix that is NOT ours - the Sobha subset copies
    outside = {}
    for a in ell.get_all_level_actors():
        if isinstance(a, unreal.StaticMeshActor) and a not in mine:
            p = prefix_of(a.get_actor_label())
            if p.startswith("b") and p[1:].isdigit():
                outside.setdefault(p, []).append(a)

    found, missing, scale_bad, collided = [], [], [], []
    for t in towers:
        key = "b%d" % t["i"]
        cands = by_prefix.get(key) or []
        if not cands:
            missing.append({"i": t["i"], "name": t["name"], "prefix": key})
            continue
        a = cands[0]
        origin, extent = a.get_actor_bounds(False)
        measured_uu = float(extent.z) * 2.0
        expected_uu = t["height_m"] * 100.0
        ratio = (measured_uu / expected_uu) if expected_uu else 0.0
        rec = {
            "i": t["i"], "name": t["name"], "label": a.get_actor_label(),
            "height_m": t["height_m"], "provenance": t.get("provenance"), "levels": t.get("levels"),
            "height_disputed": bool(t.get("height_disputed")),
            "origin": [round(origin.x, 1), round(origin.y, 1), round(origin.z, 1)],
            "extent": [round(extent.x, 1), round(extent.y, 1), round(extent.z, 1)],
            "measured_uu": round(measured_uu, 1), "expected_uu": round(expected_uu, 1),
            "ce_generated_m": ceh.get(t["i"]),
            "scale_ratio": round(ratio, 3),
            "actors_in_district": len(cands),
            "same_label_outside_district": len(outside.get(key) or []),
        }
        found.append(rec)
        if rec["same_label_outside_district"]:
            collided.append(rec)
        if not (0.6 <= ratio <= 1.6):
            scale_bad.append(rec)

    out = {
        "district": "businessbay",
        "export": os.path.basename(DATASMITH),
        "district_actors": len(mine),
        "targets": len(towers),
        "resolved": len(found),
        "missing": len(missing),
        "scale_outliers": len(scale_bad),
        "label_collisions_with_sobha_subset": len(collided),
        "note": "scale_ratio is measured height / expected height. Unreal is centimetres, so a 252.6 m tower should "
                "measure about 25,260 uu and score ~1.0. A ratio near 0.01 means the scene came in as metres; near "
                "100 means it was scaled twice. Resolution is scoped to the full district's own scene actor, so the "
                "Sobha subset's identical b<i>_ labels cannot be mistaken for it.",
        "known_before_running": "36 of the 193 carry a facade class in this 12 Sep export that the data has since "
                                "changed - 49 Business Bay buildings were re-classed on 22 Sep (measured on disk, "
                                "not in Unreal). Geometry and height are unaffected; the material is. The CityEngine "
                                "session is exporting businessbay_lod3_23sep; stage 3 points at that, stage 1 does "
                                "not care. Four targets are marked height_disputed in the targets file and must be "
                                "held back from rendering, not published at a third of their height.",
        "found": found,
        "missing_targets": missing,
        "scale_outlier_rows": scale_bad,
        "collision_rows": collided,
    }
    json.dump(out, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log("=" * 64)
    log("RESOLVED %d of %d | missing %d | scale outliers %d | sobha label collisions %d"
        % (len(found), len(towers), len(missing), len(scale_bad), len(collided)))
    for r in sorted(found, key=lambda x: -x["height_m"])[:6]:
        log("   %-28s %8.0f uu measured, %8.0f expected, ratio %.2f"
            % (r["name"][:28], r["measured_uu"], r["expected_uu"], r["scale_ratio"]))
    if missing:
        log("   MISSING: " + ", ".join(m["prefix"] for m in missing[:12]) + (" ..." if len(missing) > 12 else ""))
    log("report -> " + REPORT)
    log("=" * 64)


main()
