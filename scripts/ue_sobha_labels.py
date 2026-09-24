"""Unreal (commandlet): project labels on the Sobha tour - a leader line up from each project's tallest roof to a box
carrying the project's name, turned to face the camera all the way through the tour.

Kendall, 24 Sep 2026: "add labels to the buildings as well, a line from the top of the building leading to a box with
the name."

One label per PROJECT, not per building (Motor City alone is 97 footprints of two projects): the Sobha actors carry
"sobha:<project name>" tags from ue_sobha_lens.py; each project's label stands on its tallest building.
  LBL_<n>_line   /Engine/BasicShapes/Cylinder, 30 cm thick, vertical from the roof to LINE_M above it
  LBL_<n>        an empty pivot at the top of the line; its children are
  LBL_<n>_box    /Engine/BasicShapes/Cube flattened to a panel sized to the name, M_SobhaLabelBox (dark, unlit-looking)
  LBL_<n>_text   TextRenderActor, the project name, white, centred, TEXT_CM high
The line is vertical, so it needs no turning. Each pivot is added to SEQ_Sobha_Tour with a yaw key at every camera key,
computed from the camera's own keyed positions, so the box faces the lens through every approach, orbit and pull-out.
Names are shown in the register's English form with Title Case ("SOBHA ONE" -> "Sobha One").

Run AFTER ue_sobha_tour.py (it reads that sequence) and before the render. Re-running replaces the labels.
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_labels.py
"""
import math, re

import unreal

LEVEL = "/Game/Main"; SEQ = "/Game/Najma/Cinematics/SEQ_Sobha_Tour"; LBL_DIR = "/Game/Najma/Sobha/Labels"
LINE_M = 60.0          # leader line height above the roof
TEXT_CM = 1400.0       # text height (14 m: legible from the orbit distance)
PAD_CM = 500.0
log = unreal.log; eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary; MEL = unreal.MaterialEditingLibrary
SKIP = {"parcel", "dm", "radius", "geocode"}


def box_material():
    p = LBL_DIR + "/M_SobhaLabelBox"
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    if not eal.does_directory_exist(LBL_DIR):
        eal.make_directory(LBL_DIR)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_SobhaLabelBox", LBL_DIR, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
    c.constant = unreal.LinearColor(0.02, 0.05, 0.07, 1.0)     # Najma dark teal-black panel
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def line_material():
    p = LBL_DIR + "/M_SobhaLabelLine"
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_SobhaLabelLine", LBL_DIR, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
    c.constant = unreal.LinearColor(0.77, 0.65, 0.42, 1.0)     # the house gold #C5A56A
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def pretty(name):
    return " ".join(w if w.isupper() and len(w) <= 3 and w not in ("ONE",) else w.capitalize() for w in re.split(r"\s+", name.strip()))


def projects():
    """project name -> (x, y, roof z) of its tallest non-duplicate Sobha building."""
    best = {}
    for a in ell.get_all_level_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        tags = [str(t) for t in a.tags]
        if "sobha" not in tags or "duplicate" in tags:
            continue
        name = next((t[6:] for t in tags if t.startswith("sobha:") and t[6:] not in SKIP and t[6:]), None)
        if not name:
            continue
        o, e = a.get_actor_bounds(False)
        top = o.z + e.z
        if name not in best or top > best[name][2]:
            best[name] = (o.x, o.y, top)
    return best


def clear_old():
    for a in ell.get_all_level_actors():
        if (a.get_actor_label() or "").startswith("LBL_"):
            ell.destroy_actor(a)


def camera_keys(seq):
    """[(frame, x, y, z)] from the camera binding's location channels."""
    for b in seq.get_bindings():
        for t in b.get_tracks():
            if not isinstance(t, unreal.MovieScene3DTransformTrack):
                continue
            for s in t.get_sections():
                ch = s.get_all_channels()
                xs = [(k.get_time().frame_number.value, k.get_value()) for k in ch[0].get_keys()]
                ys = [k.get_value() for k in ch[1].get_keys()]
                zs = [k.get_value() for k in ch[2].get_keys()]
                if xs and len(xs) == len(ys) == len(zs):
                    return [(f, x, y, z) for (f, x), y, z in zip(xs, ys, zs)]
    return []


def main():
    ell.load_level(LEVEL)
    seq = eal.load_asset(SEQ)
    if seq is None:
        raise RuntimeError("%s not found - run ue_sobha_tour.py first" % SEQ)
    clear_old()
    # drop label bindings from an earlier run
    for b in list(seq.get_bindings()):
        if (b.get_display_name() or "").startswith("LBL_"):
            b.remove()
    cams = camera_keys(seq)
    bm, lm = box_material(), line_material()
    cyl = eal.load_asset("/Engine/BasicShapes/Cylinder"); cube = eal.load_asset("/Engine/BasicShapes/Cube")
    projs = projects()
    for n, (name, (x, y, top)) in enumerate(sorted(projs.items())):
        label = pretty(name)
        line_cm = LINE_M * 100.0
        ln = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, top + line_cm / 2.0))
        ln.set_actor_label("LBL_%02d_line" % n); ln.static_mesh_component.set_static_mesh(cyl)
        ln.set_actor_scale3d(unreal.Vector(0.3, 0.3, line_cm / 100.0)); ln.static_mesh_component.set_material(0, lm)
        ln.static_mesh_component.set_cast_shadow(False)
        piv = ell.spawn_actor_from_class(unreal.Actor, unreal.Vector(x, y, top + line_cm))
        piv.set_actor_label("LBL_%02d" % n)
        try:
            root = unreal.SceneComponent(piv); piv.set_editor_property("root_component", root)
        except Exception:
            pass
        w = max(3000.0, len(label) * TEXT_CM * 0.62) + 2 * PAD_CM; h = TEXT_CM + 2 * PAD_CM
        bx = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, top + line_cm + h / 2.0))
        bx.set_actor_label("LBL_%02d_box" % n); bx.static_mesh_component.set_static_mesh(cube)
        bx.set_actor_scale3d(unreal.Vector(0.4, w / 100.0, h / 100.0)); bx.static_mesh_component.set_material(0, bm)
        bx.static_mesh_component.set_cast_shadow(False)
        tx = ell.spawn_actor_from_class(unreal.TextRenderActor, unreal.Vector(x - 30.0, y, top + line_cm + h / 2.0))
        tx.set_actor_label("LBL_%02d_text" % n)
        tr = tx.text_render
        tr.set_text(label); tr.set_world_size(TEXT_CM); tr.set_text_render_color(unreal.Color(255, 255, 255, 255))
        tr.set_horizontal_alignment(unreal.HorizTextAligment.EHTA_CENTER); tr.set_vertical_alignment(unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
        tr.set_editor_property("cast_shadow", False)
        tx.set_actor_rotation(unreal.Rotator(0, 0, 180), False)      # text reads toward -X, the box's front face
        for c in (bx, tx):
            c.attach_to_actor(piv, "", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
        # face the camera at every camera key
        if cams:
            b = seq.add_possessable(piv)
            tt = b.add_track(unreal.MovieScene3DTransformTrack); sec = tt.add_section(); sec.set_range(0, seq.get_playback_end())
            ch = sec.get_all_channels()
            prev = None
            px, py, pz = x, y, top + line_cm
            for (f, cx, cy, cz) in cams:
                yaw = math.degrees(math.atan2(cy - py, cx - px)) + 180.0     # the box front (-X) toward the camera
                if prev is not None:
                    while yaw - prev > 180: yaw -= 360
                    while yaw - prev < -180: yaw += 360
                prev = yaw
                for c, v in zip(ch, [px, py, pz, 0.0, 0.0, yaw, 1.0, 1.0, 1.0]):
                    k = c.add_key(unreal.FrameNumber(int(f)), float(v))
                    try:
                        k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_CUBIC)
                    except Exception:
                        pass
        log("  label %-34s at roof %.0f m" % (label, top / 100.0))
    eal.save_asset(SEQ)
    ell.save_current_level()
    log("Sobha labels: %d projects labelled, %d camera keys followed" % (len(projs), len(cams)))


if __name__ == "__main__":
    main()
