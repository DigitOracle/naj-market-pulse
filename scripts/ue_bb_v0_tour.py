"""Unreal (commandlet): Business Bay v0 - the camera, the moving cars and boats, and the Movie Render Queue configs.

Reads data/ce/_datasmith/bb_v0/bb_v0_plan.json (bb_v0_prep.py): 451 camera keys (every 0.2 s, 90 s, smoothed) and the
movers (8 cars on the boulevard in both directions, 3 boats on the canal stretch). Opens /Game/BusinessBay/L_BB_v0
only (the towers come in with its always-loaded sublevel L_BB_v0_Buildings) and writes under /Game/BusinessBay/Cinematics:
  SEQ_BB_v0           25 fps, 2250 frames: camera transform keys (cubic/auto) + one transform track per mover part
  MPC_BB_v0           1080 x 1920 JPG, 25 fps, TAA 2 temporal samples, warm-up 64 engine / 32 render frames
                      -> Saved/MovieRenders/BB_v0/bb_v0.<frame>.jpeg
  MPC_BB_v0_Preview   540 x 960, every 25th frame (one still a second) -> Saved/MovieRenders/BB_v0_preview
Camera: CineCamera 20 mm on a 24 x 42.667 filmback (9:16), f/8, focus off; exposure as the Ellington tour (auto
exposure, bias -0.2, no post-process volume), bloom 0.35, lens flare 0, vignette 0.35, GoldenHour_Warm LUT at 0.6
(BB_V0_LUT=0 turns it off). The look-at point stays at frame centre, inside the 1080 x 1420 safe zone.
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_bb_v0_tour.py
"""
import json, math, os, sys

import unreal

sys.path.insert(0, "C:/Dev/naj-market-pulse/scripts")
import ue_bb_v0_build as B          # kits, paths, logging (its main() is not run)

CINE = B.ROOT + "/Cinematics"
SEQ_NAME, MPC_NAME, MPC_PREVIEW = "SEQ_BB_v0", "MPC_BB_v0", "MPC_BB_v0_Preview"
RENDER_DIR = "C:/Dev/UnrealProjects/AzimuthDubai/Saved/MovieRenders/BB_v0"
PREVIEW_DIR = RENDER_DIR + "_preview"
log, warn = B.log, B.warn
eal, ell = B.eal, B.ell
tools = B.tools


def look_at(frm, to):
    return unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*frm), unreal.Vector(*to))


def along(pl, d):
    for k in range(len(pl) - 1):
        seg = math.hypot(pl[k + 1][0] - pl[k][0], pl[k + 1][1] - pl[k][1])
        if d <= seg or k == len(pl) - 2:
            u = max(0.0, min(1.0, d / seg)) if seg > 0 else 0.0
            dx, dy = (pl[k + 1][0] - pl[k][0]) / (seg or 1), (pl[k + 1][1] - pl[k][1]) / (seg or 1)
            return [pl[k][0] + u * (pl[k + 1][0] - pl[k][0]), pl[k][1] + u * (pl[k + 1][1] - pl[k][1])], (dx, dy)
        d -= seg
    return list(pl[-1]), (1.0, 0.0)


def camera(plan):
    k0 = plan["keys"][0]
    cam = ell.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(*k0[1]), look_at(k0[1], k0[2]))
    cam.set_actor_label(B.PFX + "CAM")
    cc = cam.get_cine_camera_component()
    fb = cc.filmback; fb.sensor_width = 24.0; fb.sensor_height = 42.667; cc.filmback = fb
    cc.set_editor_property("current_focal_length", float(plan.get("focal_mm", 20.0))); cc.set_editor_property("current_aperture", 8.0)
    fs = cc.focus_settings; fs.focus_method = unreal.CameraFocusMethod.DISABLE; cc.focus_settings = fs
    pp = cc.post_process_settings
    sets = [("override_auto_exposure_bias", True), ("auto_exposure_bias", -0.2), ("override_bloom_intensity", True), ("bloom_intensity", 0.35),
            ("override_lens_flare_intensity", True), ("lens_flare_intensity", 0.0), ("override_vignette_intensity", True), ("vignette_intensity", 0.35),
            ("override_motion_blur_amount", True), ("motion_blur_amount", 0.3)]
    lut = eal.load_asset(B.POST_DIR + "/T_BB0_LUT_GoldenHour") if eal.does_asset_exist(B.POST_DIR + "/T_BB0_LUT_GoldenHour") else None
    if lut and os.environ.get("BB_V0_LUT", "1") == "1":
        sets += [("override_color_grading_lut", True), ("color_grading_lut", lut), ("override_color_grading_intensity", True), ("color_grading_intensity", 0.35)]
    for k, v in sets:
        try:
            pp.set_editor_property(k, v)
        except Exception as e:
            log("  pp %s: %s" % (k, e))
    cc.post_process_settings = pp
    return cam


def add_transform_keys(seq, actor, frames_keys, frames):
    """frames_keys: [(frame, (x, y, z), (roll, pitch, yaw))]"""
    b = seq.add_possessable(actor)
    tt = b.add_track(unreal.MovieScene3DTransformTrack); sec = tt.add_section(); sec.set_range(0, frames)
    ch = sec.get_all_channels()
    s = actor.get_actor_scale3d()
    prev = None
    for f, loc, rot in frames_keys:
        yaw = rot[2]
        if prev is not None:
            while yaw - prev > 180: yaw -= 360
            while yaw - prev < -180: yaw += 360
        prev = yaw
        for c, v in zip(ch, [loc[0], loc[1], loc[2], rot[0], rot[1], yaw, s.x, s.y, s.z]):
            k = c.add_key(unreal.FrameNumber(int(f)), float(v))
            try:
                k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_CUBIC); k.set_tangent_mode(unreal.RichCurveTangentMode.RCTM_AUTO)
            except Exception:
                pass
    return b


def movers(plan, gz, fps, total_s):
    """spawn one StaticMeshActor per kit part per mover; returns [(actor, keys)]"""
    out = []
    used = {}
    for i, m in enumerate(plan.get("movers", [])):
        vs = B.kit(m["kind"])
        if not vs:
            continue
        v = vs[m["variant"] % len(vs)]; v["_len_axis"] = True
        used[v["folder"]] = used.get(v["folder"], 0) + 1
        keys = []
        for j in range(0, int(total_s * 2) + 1):                    # a key every 0.5 s
            t = j * 0.5
            p, d = along(m["path"], m["start_cm"] + m["speed_cms"] * t)
            x = p[0] - d[1] * m["lane_cm"]; y = p[1] + d[0] * m["lane_cm"]
            yaw = math.degrees(math.atan2(d[1], d[0]))
            xf = B.place_xf(v, x, y, gz + (20.0 if m["kind"] == "boat" else 0.0), yaw)
            l, r = xf.translation, xf.rotation.rotator()
            keys.append((round(t * fps), (l.x, l.y, l.z), (r.roll, r.pitch, r.yaw)))
        s = v["scale"]
        for pi, part in enumerate(v["parts"]):
            a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*keys[0][1]), unreal.Rotator(*keys[0][2]))
            a.set_actor_label("%sMOV_%s_%d_%d" % (B.PFX, m["kind"], i, pi))
            a.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
            a.static_mesh_component.set_static_mesh(part)
            a.set_actor_scale3d(unreal.Vector(s, s, s))
            out.append((a, keys))
    log("movers: %d part actors for %d movers" % (len(out), len(plan.get("movers", []))))
    return out, used


def sequence(plan, cam, movs):
    fps = int(plan["fps"]); frames = int(round(plan["total_s"] * fps))
    p = "%s/%s" % (CINE, SEQ_NAME)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    seq = tools.create_asset(SEQ_NAME, CINE, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(fps, 1)); seq.set_tick_resolution(unreal.FrameRate(fps * 1000, 1))
    seq.set_playback_start(0); seq.set_playback_end(frames)
    ck = []
    for t, loc, tgt in plan["keys"]:
        r = look_at(loc, tgt)
        ck.append((round(t * fps), loc, (r.roll, r.pitch, r.yaw)))
    b = add_transform_keys(seq, cam, ck, frames)
    for a, keys in movs:
        add_transform_keys(seq, a, keys, frames)
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack); cs = cut.add_section(); cs.set_range(0, frames)
    bid = None
    # 28 Sep preview 2: the cut came out unbound (frames from the default pawn at the world origin). Portable id first.
    for nm, make in (("portable", lambda: seq.get_portable_binding_id(seq, b)), ("portable_ext", lambda: unreal.MovieSceneSequenceExtensions.get_portable_binding_id(seq, seq, b)),
                     ("binding_id", lambda: seq.get_binding_id(b))):
        try:
            bid = make()
            if bid is not None:
                log("camera cut bound via %s" % nm); break
        except Exception as e:
            log("  binding id via %s: %s" % (nm, e))
    cs.set_camera_binding_id(bid)
    eal.save_asset(p)
    log("%s: %d camera keys, %d mover tracks, %d frames at %d fps" % (p, len(ck), len(movs), frames, fps))


def mrq(name, out_dir, res, fps, step=1):
    p = "%s/%s" % (CINE, name)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    cfg = tools.create_asset(name, CINE, unreal.MoviePipelinePrimaryConfig, unreal.MoviePipelinePrimaryConfigFactory())
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    jpg = cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_JPG)
    try:
        jpg.set_editor_property("quality", 95)
    except Exception:
        pass
    out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_resolution = unreal.IntPoint(*res); out.output_directory = unreal.DirectoryPath(out_dir)
    out.file_name_format = "bb_v0.{frame_number}"; out.use_custom_frame_rate = True; out.output_frame_rate = unreal.FrameRate(fps, 1)
    out.zero_pad_frame_numbers = 4
    if step > 1:
        try:
            out.set_editor_property("output_frame_step", step)
        except Exception as e:
            warn("frame step not available (%s) - the preview renders every frame" % e)
    aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = 1; aa.temporal_sample_count = 2; aa.override_anti_aliasing = True
    aa.engine_warm_up_count = 64; aa.render_warm_up_count = 32; aa.use_camera_cut_for_warm_up = True
    go = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    for prop, val in (("texture_streaming", unreal.MoviePipelineTextureStreamingMethod.DISABLED), ("flush_grass_streaming", True), ("flush_streaming_managers", True)):
        try:
            go.set_editor_property(prop, val)
        except Exception:
            pass
    try:
        cv = cfg.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
        cv.set_editor_property("start_console_commands", ["DisableAllScreenMessages", "r.Lumen.Reflections.Allow 1", "r.Lumen.ScreenProbeGather.ScreenTraces 1",
                                                          "r.Shadow.Virtual.MaxPhysicalPages 2048", "foliage.LODDistanceScale 1.5"])
    except Exception as e:
        log("  console vars: %s" % e)
    eal.save_asset(p)
    log("%s: %dx%d, %d fps, step %d -> %s" % (p, res[0], res[1], fps, step, out_dir))


def main():
    plan = json.load(open(B.PLAN, encoding="utf-8"))
    fps = int(plan["fps"])
    B.les().load_level(B.LEVEL)
    for a in list(ell.get_all_level_actors()):
        lab = a.get_actor_label() or ""
        if lab.startswith(B.PFX + "CAM") or lab.startswith(B.PFX + "MOV_"):
            ell.destroy_actor(a)
    if not eal.does_directory_exist(CINE):
        eal.make_directory(CINE)
    gz = 0.0
    try:
        gz = B.find_ground_z() if hasattr(B, "find_ground_z") else 0.0
    except Exception:
        pass
    sand = next((a for a in ell.get_all_level_actors() if (a.get_actor_label() or "") == B.PFX + "GROUND_Sand"), None)
    if sand:
        gz = sand.get_actor_location().z + 20.0
    cam = camera(plan)
    movs, used = movers(plan, gz, fps, plan["total_s"])
    sequence(plan, cam, movs)
    mrq(MPC_NAME, RENDER_DIR, (1080, 1920), fps)
    mrq(MPC_PREVIEW, PREVIEW_DIR, (540, 960), fps, step=fps)
    B.les().save_all_dirty_levels()
    try:
        u = json.load(open(B.USED, encoding="utf-8"))
    except Exception:
        u = {"placed": {}}
    u["movers"] = used
    json.dump(u, open(B.USED, "w", encoding="utf-8"), indent=1)
    log("tour ready: -LevelSequence=%s/%s -MoviePipelineConfig=%s/%s (preview: %s)" % (CINE, SEQ_NAME, CINE, MPC_NAME, MPC_PREVIEW))


if __name__ == "__main__":
    main()


