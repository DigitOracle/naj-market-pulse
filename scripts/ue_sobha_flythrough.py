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
    # the tallest building of each district, for an orbit that circles a tower rather than a bounding box's empty middle
    for a in ell.get_all_level_actors():
        tags = [str(t) for t in a.tags]
        if "sobha" not in tags or "duplicate" in tags:
            continue
        d = next((t[9:] for t in tags if t.startswith("district:")), None)
        if not d or d not in out:
            continue
        o, e = a.get_actor_bounds(False)
        if e.z * 2 > out[d].get("hero_h", 0):
            out[d]["hero_h"] = e.z * 2; out[d]["hero"] = unreal.Vector(o.x, o.y, 0); out[d]["hero_name"] = a.get_actor_label()
    return out


def lighting(centre):
    sun = spawn(unreal.DirectionalLight, "SUN_Sobha", (centre.x, centre.y, 50000), (-24, 250, 0))
    lc = sun.light_component
    lc.set_intensity(4.0); lc.set_light_color(unreal.LinearColor(1.0, 0.86, 0.7, 1.0))
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
    if ground and ground.get_actor_scale3d().x < 1000:
        ground.set_actor_scale3d(unreal.Vector(40000, 40000, 1))
    if not ground:
        ground = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(centre.x, centre.y, -5))
        ground.set_actor_label("GROUND_Sobha")
        ground.static_mesh_component.set_static_mesh(eal.load_asset("/Engine/BasicShapes/Plane"))
        ground.set_actor_scale3d(unreal.Vector(40000, 40000, 1))   # the basic Plane is 1 m: this is 40 km
        mic = eal.load_asset("/Game/Najma/Sobha/MI_Ground") if eal.does_asset_exist("/Game/Najma/Sobha/MI_Ground") else None
        if mic:
            unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mic, "Color", unreal.LinearColor(0.10, 0.09, 0.075, 1.0)); unreal.MaterialEditingLibrary.update_material_instance(mic); eal.save_asset("/Game/Najma/Sobha/MI_Ground")
        if not mic:
            mic = unreal.AssetToolsHelpers.get_asset_tools().create_asset("MI_Ground", "/Game/Najma/Sobha", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
            unreal.MaterialEditingLibrary.set_material_instance_parent(mic, eal.load_asset("/Engine/BasicShapes/BasicShapeMaterial"))
            unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mic, "Color", unreal.LinearColor(0.10, 0.09, 0.075, 1.0))
            unreal.MaterialEditingLibrary.update_material_instance(mic); eal.save_asset("/Game/Najma/Sobha/MI_Ground")
        ground.static_mesh_component.set_material(0, mic)
    # v2 (manual EV 12) and v3 (histogram clamped to EV 8-13) both rendered black: the project does not extend the
    # default luminance range, so those numbers are legacy luminance multipliers there. No post-process volume at all;
    # the sun is softened and the camera carries a small negative bias against the v1 blow-out.
    pp = find("PP_Sobha")
    if pp:
        ell.destroy_actor(pp); log("  PP_Sobha removed")
    log("  lighting + ground + post process in place")


def look_at(frm, to):
    return unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*frm), unreal.Vector(*to))


def path(dc):
    """Camera keys, (location, look-at) in uu, one every 30 frames (1 s).

    Kendall, 24 Sep 2026: "more rotational in the end, hollywood style". So: 0-3 s an approach glide from high
    south-west of Sobha Hartland down the corridor; 3-10 s a 200-degree orbit around the Hartland II cluster
    (the tallest group - Skyscape 381 m), descending from 320 m to 200 m and tightening from 750 m to 550 m
    out, the look-at held on the cluster so the towers wheel past. One key per second keeps the cubic curve
    on the circle instead of cutting its chords."""
    pts = [dc[d]["c"] for d in CORRIDOR if d in dc]
    tops = [dc[d]["top"] for d in CORRIDOR if d in dc]
    if len(pts) < 2:
        raise RuntimeError("corridor districts not found in the level: %s" % list(dc))
    # v5: the orbit belongs on the buildings with REAL LOD 3 facades - Creek Vistas Heights and neighbours in Sobha
    # Hartland - not on the Hartland II permit boxes, which are what an assessment of the facade rule cannot use. So the
    # approach now comes in from the Hartland II end (placeholders pass by, coral, in the first three seconds) and the
    # orbit wheels round Sobha Hartland.
    a = pts[len(pts) // 2]; od = CORRIDOR[0]
    mid = dc[od].get("hero", pts[0]); top_mid = dc[od].get("hero_h", tops[0])
    tops = [tops[len(pts) // 2]] + tops[1:]
    log("  orbit centre: %s (%.0f m) in %s" % (dc[od].get("hero_name"), top_mid / 100.0, od))
    dx, dy = mid.x - a.x, mid.y - a.y; L = math.hypot(dx, dy); ux, uy = dx / L, dy / L
    px, py = -uy, ux
    look_mid = (mid.x, mid.y, top_mid * 0.42)
    keys = []
    # approach: 4 keys, 0-3 s
    approach = [((a.x - ux * 70000 + px * 45000, a.y - uy * 70000 + py * 45000, tops[0] + 30000), (a.x, a.y, tops[0] * 0.45)),
                ((a.x - ux * 20000 + px * 40000, a.y - uy * 20000 + py * 40000, tops[0] + 22000), (a.x + ux * 40000, a.y + uy * 40000, tops[0] * 0.4)),
                ((a.x + ux * 45000 + px * 42000, a.y + uy * 45000 + py * 42000, top_mid * 0.6 + 16000), look_mid)]
    keys.extend(approach)
    # orbit: the approach arrives at angle theta0 (direction from mid to the camera); sweep 200 degrees over 7 s
    cx, cy = mid.x, mid.y
    ax, ay = keys[-1][0][0] - cx, keys[-1][0][1] - cy
    theta0 = math.atan2(ay, ax)
    n_orbit = 7
    for k in range(1, n_orbit + 1):
        t = k / float(n_orbit)
        th = theta0 + math.radians(200.0) * t
        r = 48000 - 16000 * t                    # 480 m -> 320 m out: one tower, not a district
        h = top_mid * 0.6 + 12000 - 6000 * t     # settles as it tightens
        keys.append(((cx + r * math.cos(th), cy + r * math.sin(th), h), look_mid))
    path.orbit_mid_deg = math.degrees(theta0 + math.radians(100.0))   # where the camera sits halfway round the orbit
    return keys, L


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
    times = [round(i * FRAMES / float(len(keys) - 1)) for i in range(len(keys))]
    prev_yaw = None
    for (loc, tgt), f in zip(keys, times):
        rot = look_at(loc, tgt)
        yaw = rot.yaw
        if prev_yaw is not None:          # keep yaw continuous across the +-180 seam or the orbit whips round the long way
            while yaw - prev_yaw > 180: yaw -= 360
            while yaw - prev_yaw < -180: yaw += 360
        prev_yaw = yaw
        vals = [loc[0], loc[1], loc[2], rot.roll, rot.pitch, yaw, 1.0, 1.0, 1.0]
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
    log("  %s: %d keys over %d frames on %s" % (p, len(keys), FRAMES, cam.get_actor_label()))
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
    # the first render came back sky-only: Nanite / Lumen / streaming had not settled in the one default warm-up frame
    aa.engine_warm_up_count = 64; aa.render_warm_up_count = 32; aa.use_camera_cut_for_warm_up = True
    try:
        aa.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_TSR
    except Exception:
        pass
    go = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    for prop, val in (("texture_streaming", unreal.MoviePipelineTextureStreamingMethod.DISABLED), ("flush_grass_streaming", True), ("flush_streaming_managers", True)):
        try:
            go.set_editor_property(prop, val)
        except Exception as e:
            log("  game override %s: %s" % (prop, e))
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
        cc.post_process_settings.set_editor_property("override_auto_exposure_method", False)
        cc.post_process_settings.set_editor_property("override_auto_exposure_bias", True)
        cc.post_process_settings.set_editor_property("auto_exposure_bias", -1.0)
    except Exception as e:
        log("  camera left at defaults: %s" % e)
    keys, L = path(dc)
    # v7: light the faces the camera sees. A directional light's yaw is the direction it travels; the camera halfway
    # round the orbit sits at orbit_mid_deg from the tower and looks back (orbit_mid_deg + 180), so the sun travels the
    # same way, swung 35 degrees off-axis for modelling, 30 degrees down - golden and raking, not flat.
    sun = find("SUN_Sobha")
    if sun:
        sun.set_actor_rotation(unreal.Rotator(0.0, -30.0, (path.orbit_mid_deg + 180.0 + 35.0) % 360.0), False)
        log("  sun aimed with the orbit: yaw %.0f" % ((path.orbit_mid_deg + 180.0 + 35.0) % 360.0))
    loc0 = keys[0][0]; cam.set_actor_location(unreal.Vector(*loc0), False, False); cam.set_actor_rotation(look_at(loc0, keys[0][1]), False)
    log("  corridor %.1f km; keys %s" % (L / 100000.0, [(round(k[0][0] / 100), round(k[0][1] / 100), round(k[0][2] / 100)) for k in keys]))
    sequence(cam, keys)
    mrq_config()
    ell.save_current_level()
    log("Sobha fly-through: ready - render with -LevelSequence=%s/%s -MoviePipelineConfig=%s/%s" % (CINE, SEQ_NAME, CINE, MPC_NAME))


if __name__ == "__main__":
    main()
