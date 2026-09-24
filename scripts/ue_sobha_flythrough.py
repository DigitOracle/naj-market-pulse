"""Unreal (commandlet or editor Python): the first Sobha fly-through - a 10 s glide over the Hartland corridor.

Kendall, 24 Sep 2026: "now in unreal, give me the initial fly through, 10 seconds, so i can assess".

Runs against the AzimuthDubai level that ue_sobha_lens.py already filled (218 Sobha buildings at LOD 3, coral).
  1. Lighting and ground, once, named so re-runs find them: SUN_Sobha (directional, low from the west), SKY_Sobha
     (sky light), ATMO_Sobha (sky atmosphere), FOG_Sobha (height fog for depth over kilometres), GROUND_Sobha (a
     40 km dark plane). The hero-clip README's recipe, done by script.
  2. The path: three districts sit in a line - Sobha Hartland (Creek Vistas), Hartland II (Riverside Crescent,
     Skyscape, Skyvue), Sobha One in Ras Al Khor - about 4 km end to end. The camera starts high and wide
     south-west of Hartland looking along the line, glides north-east over Hartland II at ~450 m, and settles
     looking down on Sobha One. Three keys (0 s, 5 s, 10 s), 30 fps, 300 frames, on CAM_Sobha.
  3. A Level Sequence /Game/Najma/Cinematics/SEQ_Sobha_Fly (camera cut on CAM_Sobha) and a Movie Render Queue
     config /Game/Najma/Cinematics/MPC_Sobha (1920x1080 JPG frames to Saved/MovieRenders/SobhaFly), so the
     render is one command:
       UnrealEditor-Cmd.exe <uproject> /Game/Main -game -LevelSequence=/Game/Najma/Cinematics/SEQ_Sobha_Fly
           -MoviePipelineConfig=/Game/Najma/Cinematics/MPC_Sobha -windowed -resx=1280 -resy=720 -NoLoadingScreen
     then ffmpeg stitches the frames (scripts/ue_sobha_flythrough.py is followed by that in the runbook).
Usage (headless):  UnrealEditor-Cmd.exe C:/Dev/UnrealProjects/AzimuthDubai/AzimuthDubai.uproject -run=pythonscript
                       -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_flythrough.py
"""
import math

import unreal

LEVEL = "/Game/Main"
CINE = "/Game/Najma/Cinematics"
SEQ_NAME, MPC_NAME = "SEQ_Sobha_Fly", "MPC_Sobha"
FPS, FRAMES = 30, 300
RENDER_DIR = "C:/Dev/UnrealProjects/AzimuthDubai/Saved/MovieRenders/SobhaFly"
CORRIDOR = ("sobhaheartland", "bukadra", "rasalkhor")     # the three districts the path follows, in order

log = unreal.log
eal = unreal.EditorAssetLibrary
ell = unreal.EditorLevelLibrary


def find(label):
    for a in ell.get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


def spawn(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
    a = find(label)
    if a:
        return a
    a = ell.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(*rot))
    a.set_actor_label(label)
    return a


def district_centres():
    """Centre and extent of the Sobha buildings per district, from the tags the lens wrote."""
    out = {}
    for a in ell.get_all_level_actors():
        tags = [str(t) for t in a.tags]
        if "sobha" not in tags or "duplicate" in tags:
            continue
        d = next((t[9:] for t in tags if t.startswith("district:")), None)
        if not d:
            continue
        o, e = a.get_actor_bounds(False)
        rec = out.setdefault(d, {"min": None, "max": None})
        lo, hi = o - e, o + e
        rec["min"] = lo if rec["min"] is None else unreal.Vector(min(rec["min"].x, lo.x), min(rec["min"].y, lo.y), min(rec["min"].z, lo.z))
        rec["max"] = hi if rec["max"] is None else unreal.Vector(max(rec["max"].x, hi.x), max(rec["max"].y, hi.y), max(rec["max"].z, hi.z))
    for d, r in out.items():
        r["c"] = (r["min"] + r["max"]) * 0.5; r["top"] = r["max"].z
    return out


def lighting(centre):
    sun = spawn(unreal.DirectionalLight, "SUN_Sobha", (centre.x, centre.y, 50000), (-24, 250, 0))
    lc = sun.light_component
    lc.set_intensity(8.0); lc.set_light_color(unreal.LinearColor(1.0, 0.86, 0.7, 1.0))
    try:
        lc.set_editor_property("atmosphere_sun_light", True); lc.set_editor_property("cast_cloud_shadows", True)
    except Exception:
        pass
    sky = spawn(unreal.SkyLight, "SKY_Sobha", (centre.x, centre.y, 20000))
    try:
        sky.light_component.set_editor_property("real_time_capture", True)
    except Exception:
        pass
    spawn(unreal.SkyAtmosphere, "ATMO_Sobha", (centre.x, centre.y, 0))
    fog = spawn(unreal.ExponentialHeightFog, "FOG_Sobha", (centre.x, centre.y, 0))
    try:
        fc = fog.component
        fc.set_editor_property("fog_density", 0.012); fc.set_editor_property("fog_height_falloff", 0.3)
        fc.set_editor_property("volumetric_fog", True)
    except Exception as e:
        log("  fog left at defaults: %s" % e)
    ground = find("GROUND_Sobha")
    if not ground:
        ground = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(centre.x, centre.y, -5))
        ground.set_actor_label("GROUND_Sobha")
        ground.static_mesh_component.set_static_mesh(eal.load_asset("/Engine/BasicShapes/Plane"))
        ground.set_actor_scale3d(unreal.Vector(400, 400, 1))
        mic = eal.load_asset("/Game/Najma/Sobha/MI_Ground") if eal.does_asset_exist("/Game/Najma/Sobha/MI_Ground") else None
        if not mic:
            mic = unreal.AssetToolsHelpers.get_asset_tools().create_asset("MI_Ground", "/Game/Najma/Sobha", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
            unreal.MaterialEditingLibrary.set_material_instance_parent(mic, eal.load_asset("/Engine/BasicShapes/BasicShapeMaterial"))
            unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mic, "Color", unreal.LinearColor(0.02, 0.05, 0.06, 1.0))
            unreal.MaterialEditingLibrary.update_material_instance(mic); eal.save_asset("/Game/Najma/Sobha/MI_Ground")
        ground.static_mesh_component.set_material(0, mic)
    log("  lighting + ground in place")


def look_at(frm, to):
    return unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*frm), unreal.Vector(*to))


def path(dc):
    """Three camera keys along the corridor. Distances in uu (cm)."""
    pts = [dc[d]["c"] for d in CORRIDOR if d in dc]
    tops = [dc[d]["top"] for d in CORRIDOR if d in dc]
    if len(pts) < 2:
        raise RuntimeError("corridor districts not found in the level: %s" % list(dc))
    a, z = pts[0], pts[-1]
    mid = pts[len(pts) // 2]
    dx, dy = z.x - a.x, z.y - a.y; L = math.hypot(dx, dy); ux, uy = dx / L, dy / L   # unit vector along the corridor
    px, py = -uy, ux                                                                  # perpendicular, camera stays off to one side
    h0, h1, h2 = max(tops) + 60000, max(tops) + 25000, tops[-1] + 30000              # 600 m over the start, 250 m mid, 300 m over Sobha One
    k0 = ((a.x - ux * 140000 + px * 90000, a.y - uy * 140000 + py * 90000, h0), (mid.x, mid.y, mid.z))
    k1 = ((mid.x + px * 110000, mid.y + py * 110000, h1), (mid.x + ux * 60000, mid.y + uy * 60000, tops[len(pts) // 2] * 0.4))
    k2 = ((z.x - ux * 60000 + px * 70000, z.y - uy * 60000 + py * 70000, h2), (z.x, z.y, z.z * 0.5))
    return [k0, k1, k2], L


def sequence(cam, keys):
    if not eal.does_directory_exist(CINE):
        eal.make_directory(CINE)
    p = "%s/%s" % (CINE, SEQ_NAME)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(SEQ_NAME, CINE, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(FPS, 1)); seq.set_tick_resolution(unreal.FrameRate(FPS * 800, 1))
    seq.set_playback_start(0); seq.set_playback_end(FRAMES)
    b = seq.add_possessable(cam)
    tt = b.add_track(unreal.MovieScene3DTransformTrack); sec = tt.add_section(); sec.set_range(0, FRAMES)
    ch = sec.get_all_channels()   # Location X Y Z, Rotation X Y Z, Scale X Y Z
    times = [0, FRAMES // 2, FRAMES]
    for (loc, tgt), f in zip(keys, times):
        rot = look_at(loc, tgt)
        vals = [loc[0], loc[1], loc[2], rot.roll, rot.pitch, rot.yaw, 1.0, 1.0, 1.0]
        for c, v in zip(ch, vals):
            k = c.add_key(unreal.FrameNumber(f), float(v))
            try:
                k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_CUBIC); k.set_tangent_mode(unreal.RichCurveTangentMode.RCTM_AUTO)
            except Exception:
                pass
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack); cs = cut.add_section(); cs.set_range(0, FRAMES)
    bid = None
    for make in (lambda: seq.make_binding_id(b, unreal.MovieSceneObjectBindingSpace.LOCAL), lambda: seq.get_binding_id(b),
                 lambda: unreal.MovieSceneSequenceExtensions.get_binding_id(seq, b)):
        try:
            bid = make(); break
        except Exception as e:
            log("  binding id: %s" % e)
    cs.set_camera_binding_id(bid)
    eal.save_asset(p)
    log("  %s: 3 keys over %d frames on %s" % (p, FRAMES, cam.get_actor_label()))
    return seq


def mrq_config():
    p = "%s/%s" % (CINE, MPC_NAME)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    cfg = None
    for make in (lambda: unreal.AssetToolsHelpers.get_asset_tools().create_asset(MPC_NAME, CINE, unreal.MoviePipelinePrimaryConfig, unreal.MoviePipelinePrimaryConfigFactory()),
                 lambda: unreal.AssetToolsHelpers.get_asset_tools().create_asset(MPC_NAME, CINE, unreal.MoviePipelinePrimaryConfig, None)):
        try:
            cfg = make()
            if cfg: break
        except Exception as e:
            log("  config factory: %s" % e)
    if not cfg:
        raise RuntimeError("could not create MoviePipelinePrimaryConfig")
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_JPG)
    out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_resolution = unreal.IntPoint(1920, 1080)
    out.output_directory = unreal.DirectoryPath(RENDER_DIR)
    out.file_name_format = "sobha_fly.{frame_number}"
    out.use_custom_frame_rate = True; out.output_frame_rate = unreal.FrameRate(FPS, 1)
    aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = 1; aa.temporal_sample_count = 2; aa.override_anti_aliasing = True
    try:
        aa.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_TSR
    except Exception:
        pass
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    eal.save_asset(p)
    log("  %s: 1920x1080 JPG -> %s" % (p, RENDER_DIR))


def main():
    ell.load_level(LEVEL)
    dc = district_centres()
    log("Sobha fly-through: districts in level %s" % {d: (round(r['c'].x), round(r['c'].y), round(r['top'])) for d, r in dc.items()})
    corridor = [dc[d]["c"] for d in CORRIDOR if d in dc]
    centre = corridor[len(corridor) // 2] if corridor else list(dc.values())[0]["c"]
    lighting(centre)
    cam = find("CAM_Sobha") or ell.spawn_actor_from_class(unreal.CineCameraActor, centre)
    cam.set_actor_label("CAM_Sobha")
    try:
        cc = cam.camera_component
        cc.filmback.sensor_width = 36.0; cc.filmback.sensor_height = 20.25   # 16:9 for the assessment cut
        cc.current_focal_length = 28.0; cc.current_aperture = 8.0
        cc.focus_settings.focus_method = unreal.CameraFocusMethod.DISABLE
    except Exception as e:
        log("  camera left at defaults: %s" % e)
    keys, L = path(dc)
    loc0 = keys[0][0]; cam.set_actor_location(unreal.Vector(*loc0), False, False); cam.set_actor_rotation(look_at(loc0, keys[0][1]), False)
    log("  corridor %.1f km; keys %s" % (L / 100000.0, [(round(k[0][0] / 100), round(k[0][1] / 100), round(k[0][2] / 100)) for k in keys]))
    sequence(cam, keys)
    mrq_config()
    ell.save_current_level()
    log("Sobha fly-through: ready - render with -LevelSequence=%s/%s -MoviePipelineConfig=%s/%s" % (CINE, SEQ_NAME, CINE, MPC_NAME))


if __name__ == "__main__":
    main()
