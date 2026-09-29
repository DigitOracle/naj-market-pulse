"""Unreal (commandlet): Business Bay Phase 0 - asset gallery level + contact-sheet render setup (28 Sep 2026).

Builds /Game/DA/Library/L_AssetGallery: every StaticMesh under /Game/DA/Library laid on a grid, one block per
<Source>/<Category>, 4 m cells, each mesh scaled DOWN to fit 3.6 m (never up), sat on the ground, with a text label.
Sun / sky atmosphere / sky light (real-time capture OFF, Bible sec.11) / neutral ground.
Per category two stills (top-down + 45 deg oblique) cut in SEQ_AssetGallery; MRQ config MPC_AssetGallery writes
1920 x 1080 PNG to Saved/MovieRenders/AssetGallery named {camera_name}.{frame_number}.
Rerunnable: clears its own GAL_* actors first. Only writes under /Game/DA/Library.
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_library_gallery.py
Render: see logs/bb_phase0_run.ps1 (-game -LevelSequence=... -MoviePipelineConfig=...).
"""
import math

import unreal

LIB = "/Game/DA/Library"
LEVEL = LIB + "/L_AssetGallery"
CINE = LIB + "/Gallery"
SEQ_NAME, MPC_NAME = "SEQ_AssetGallery", "MPC_AssetGallery"
RENDER_DIR = "C:/Dev/UnrealProjects/AzimuthDubai/Saved/MovieRenders/AssetGallery"
CELL, FIT, COLS, GAP = 400.0, 360.0, 10, 1200.0          # cm
FPS, SHOT_FRAMES = 30, 6
HFOV = 2 * math.atan(18.0 / 24.0)                      # 24 mm on 36 mm filmback

log = unreal.log
eal = unreal.EditorAssetLibrary
ell = unreal.EditorLevelLibrary
MEL = unreal.MaterialEditingLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()


def spawn(cls, label, loc=(0, 0, 0), rot=None):
    a = ell.spawn_actor_from_class(cls, unreal.Vector(*loc), rot or unreal.Rotator(0, 0, 0))
    a.set_actor_label(label)
    return a


def open_level():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if eal.does_asset_exist(LEVEL):
        les.load_level(LEVEL)
        for a in ell.get_all_level_actors():
            if a.get_actor_label().startswith("GAL_"):
                ell.destroy_actor(a)
        log("DA gallery: reopened %s" % LEVEL)
    elif not les.new_level(LEVEL):
        raise RuntimeError("could not create " + LEVEL)


def environment(cx, cy, size_m):
    sun = spawn(unreal.DirectionalLight, "GAL_SUN", (0, 0, 50000), unreal.Rotator(roll=0.0, pitch=-50.0, yaw=225.0))
    sun.light_component.set_intensity(6.0)
    try:
        sun.light_component.set_editor_property("atmosphere_sun_light", True)
    except Exception as e:
        log("  sun: %s" % e)
    spawn(unreal.SkyAtmosphere, "GAL_ATMO")
    sky = spawn(unreal.SkyLight, "GAL_SKY", (0, 0, 20000))
    try:
        sky.light_component.set_editor_property("real_time_capture", False)
        sky.light_component.recapture_sky()
    except Exception as e:
        log("  sky: %s" % e)
    mp = LIB + "/Masters/M_DA_GalleryGround"
    if eal.does_asset_exist(mp):
        mat = eal.load_asset(mp)
    else:
        mat = tools.create_asset("M_DA_GalleryGround", LIB + "/Masters", unreal.Material, unreal.MaterialFactoryNew())
        c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
        c.constant = unreal.LinearColor(0.18, 0.18, 0.18, 1.0)
        MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
        MEL.recompile_material(mat)
        eal.save_asset(mp)
    g = spawn(unreal.StaticMeshActor, "GAL_GROUND", (cx, cy, -2))
    g.static_mesh_component.set_static_mesh(eal.load_asset("/Engine/BasicShapes/Plane"))
    g.set_actor_scale3d(unreal.Vector(size_m, size_m, 1.0))
    g.static_mesh_component.set_material(0, mat)


def label(name, text, loc, size):
    t = spawn(unreal.TextRenderActor, name, loc, unreal.Rotator(roll=0.0, pitch=90.0, yaw=180.0))   # face up: reads top-down
    c = t.text_render
    c.set_editor_property("text", text); c.set_editor_property("world_size", size)
    c.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_CENTER)
    c.set_editor_property("text_render_color", unreal.Color(255, 255, 255, 255))


def meshes_by_category():
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    f = unreal.ARFilter(package_paths=[LIB], recursive_paths=True,
                        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "StaticMesh")])
    groups = {}
    for ad in reg.get_assets(f):
        pkg = str(ad.package_name)
        parts = pkg.split("/")                          # /Game/DA/Library/<Source>/<Category>/<Asset>/<mesh>
        if len(parts) < 7 or parts[4] in ("Masters", "HDRI"):
            continue
        groups.setdefault("%s_%s" % (parts[4], parts[5]), []).append(pkg)
    return {k: sorted(v) for k, v in sorted(groups.items())}


def place(groups):
    blocks, y0 = [], 0.0
    for cat, pkgs in groups.items():
        rows = int(math.ceil(len(pkgs) / float(COLS)))
        label("GAL_HDR_" + cat, cat.replace("_", " / "), (-CELL, y0 + COLS * CELL / 2.0, 1), 150.0)
        for i, pkg in enumerate(pkgs):
            mesh = eal.load_asset(pkg)
            x, y = (i // COLS) * CELL, y0 + (i % COLS) * CELL + CELL / 2.0
            try:
                b = mesh.get_bounds()
                ext, org = b.box_extent, b.origin
                s = min(1.0, FIT / max(2 * ext.x, 2 * ext.y, 2 * ext.z, 1.0))
                a = spawn(unreal.StaticMeshActor, "GAL_%s_%03d" % (cat, i), (x - org.x * s, y - org.y * s, -(org.z - ext.z) * s))
                a.static_mesh_component.set_static_mesh(mesh)
                a.set_actor_scale3d(unreal.Vector(s, s, s))
                label("GAL_LBL_%s_%03d" % (cat, i), pkg.split("/")[-1][:28], (x + CELL * 0.45, y, 2), 22.0)
            except Exception as e:
                unreal.log_warning("DA gallery: FAIL %s: %s" % (pkg, e))
        blocks.append((cat, rows * CELL, y0, COLS * CELL))
        y0 += COLS * CELL + GAP
    return blocks, y0


def cameras(blocks):
    cams = []
    for cat, depth, y0, width in blocks:
        cx, cy = depth / 2.0 - CELL / 2.0, y0 + width / 2.0
        span = max(width, depth * 16.0 / 9.0) * 1.1
        h = (span / 2.0) / math.tan(HFOV / 2.0)
        for kind, loc, rot in (
                ("top", (cx, cy, h), unreal.Rotator(roll=0.0, pitch=-90.0, yaw=0.0)),
                ("obl", (cx - h * 0.75, cy, h * 0.75),
                 unreal.MathLibrary.find_look_at_rotation(unreal.Vector(cx - h * 0.75, cy, h * 0.75), unreal.Vector(cx, cy, 0)))):
            c = spawn(unreal.CineCameraActor, "GAL_CAM_%s_%s" % (cat, kind), loc, rot)
            cc = c.get_cine_camera_component()
            cc.filmback.sensor_width = 36.0; cc.filmback.sensor_height = 20.25
            cc.set_editor_property("current_focal_length", 24.0); cc.set_editor_property("current_aperture", 16.0)
            fs = cc.focus_settings; fs.focus_method = unreal.CameraFocusMethod.DISABLE; cc.focus_settings = fs
            pp = cc.post_process_settings
            for k, v in (("override_auto_exposure_bias", True), ("auto_exposure_bias", -0.2),
                         ("override_lens_flare_intensity", True), ("lens_flare_intensity", 0.0),
                         ("override_vignette_intensity", True), ("vignette_intensity", 0.0)):
                try:
                    pp.set_editor_property(k, v)
                except Exception as e:
                    log("  pp %s: %s" % (k, e))
            cc.post_process_settings = pp
            cams.append(c)
    return cams


def sequence(cams):
    p = "%s/%s" % (CINE, SEQ_NAME)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    seq = tools.create_asset(SEQ_NAME, CINE, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(FPS, 1)); seq.set_playback_start(0); seq.set_playback_end(SHOT_FRAMES * len(cams))
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack)
    for i, c in enumerate(cams):
        b = seq.add_possessable(c)
        cs = cut.add_section(); cs.set_range(i * SHOT_FRAMES, (i + 1) * SHOT_FRAMES)
        bid = None
        for make in (lambda: seq.get_binding_id(b), lambda: unreal.MovieSceneSequenceExtensions.get_binding_id(seq, b)):
            try:
                bid = make(); break
            except Exception:
                pass
        cs.set_camera_binding_id(bid)
    eal.save_asset(p)
    log("DA gallery: %s %d shots" % (p, len(cams)))


def mrq_config():
    p = "%s/%s" % (CINE, MPC_NAME)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    cfg = tools.create_asset(MPC_NAME, CINE, unreal.MoviePipelinePrimaryConfig, unreal.MoviePipelinePrimaryConfigFactory())
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_resolution = unreal.IntPoint(1920, 1080); out.output_directory = unreal.DirectoryPath(RENDER_DIR)
    out.file_name_format = "{camera_name}.{frame_number}"; out.use_custom_frame_rate = True; out.output_frame_rate = unreal.FrameRate(FPS, 1)
    aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = 1; aa.temporal_sample_count = 2; aa.override_anti_aliasing = True
    aa.engine_warm_up_count = 64; aa.render_warm_up_count = 32; aa.use_camera_cut_for_warm_up = True
    go = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    for prop, val in (("texture_streaming", unreal.MoviePipelineTextureStreamingMethod.DISABLED), ("flush_streaming_managers", True)):
        try:
            go.set_editor_property(prop, val)
        except Exception:
            pass
    try:
        cv = cfg.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
        cv.set_editor_property("start_console_commands", ["DisableAllScreenMessages"])
    except Exception as e:
        log("  console vars: %s" % e)
    eal.save_asset(p)


def main():
    for d in (LIB, CINE, LIB + "/Masters"):
        if not eal.does_directory_exist(d):
            eal.make_directory(d)
    groups = meshes_by_category()
    log("DA gallery: %d categories, %d meshes" % (len(groups), sum(len(v) for v in groups.values())))
    if not groups:
        raise RuntimeError("no static meshes under " + LIB + " - run ue_library_import.py first")
    open_level()
    blocks, ymax = place(groups)
    depth = max(b[1] for b in blocks)
    environment(depth / 2.0, ymax / 2.0, max(ymax, depth) / 100.0 + 40)
    cams = cameras(blocks)
    sequence(cams)
    mrq_config()
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    log("DA gallery: done, %d blocks, %d cameras" % (len(blocks), len(cams)))


if __name__ == "__main__":
    main()
