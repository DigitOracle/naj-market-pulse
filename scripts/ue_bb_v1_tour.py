"""Unreal (commandlet): Business Bay v1 - camera, validated movers (cars on lanes, boats on the canal with wakes) and MRQ
configs. Reads data/ce/_datasmith/bb_v1/bb_v1_plan.json (bb_v1_prep.py); opens /Game/BusinessBay/L_BB_v1 only.
Writes under /Game/BusinessBay/v1/Cinematics:
  SEQ_BB_v1                    116 s, 25 fps
  MPC_BB_v1                    1080 x 1920 JPG film -> Saved/MovieRenders/BB_v1
  MPC_BB_v1_Still_<name>       one 1080 x 1920 PNG at a single frame (canal 1450 = 58 s, boulevard 875 = 35 s,
                               teaser 2800 = 112 s, the finale frame Kendall picked for the teaser) -> Saved/MovieRenders/BB_v1_stills
Camera: as v0 (CineCamera 20 mm, 9:16, f/8, bloom 0.35, vignette 0.35), exposure bias -0.2 as v0's canal frame, NO LUT.
"""
import json, math, os, sys

import unreal

sys.path.insert(0, "C:/Dev/naj-market-pulse/scripts")
import ue_bb_v1_build as V1B
import ue_bb_v0_tour as T0

B = V1B.B
CINE = V1B.R1 + "/Cinematics"
SEQ_NAME, MPC_NAME = "SEQ_BB_v1", "MPC_BB_v1"
RENDER_DIR = "C:/Dev/UnrealProjects/AzimuthDubai/Saved/MovieRenders/BB_v1"
STILL_DIR = RENDER_DIR + "_stills"
STILLS = {"canal": 1450, "boulevard": 875, "teaser": 2900}
log, warn, eal, ell, tools = B.log, B.warn, B.eal, B.ell, B.tools
ROLE = {"car": "car", "abras": "abra", "speedboats": "speedboat", "yachts": "yacht"}


def camera(plan):
    os.environ["BB_V0_LUT"] = "0"
    cam = T0.camera(plan)
    pp = cam.get_cine_camera_component().post_process_settings
    for k, v in (("override_color_grading_intensity", False), ("override_color_grading_lut", False), ("override_white_temp", True), ("white_temp", float(os.environ.get("BB_V1_WB", "8000"))),
                 ("override_auto_exposure_bias", True), ("auto_exposure_bias", float(os.environ.get("BB_V1_EXPOSURE", "-0.7")))):
        try:
            pp.set_editor_property(k, v)
        except Exception as e:
            warn("camera pp %s: %s" % (k, e))
    cam.get_cine_camera_component().post_process_settings = pp
    q = cam.get_cine_camera_component().post_process_settings
    log("camera pp readback: white_temp %s (override %s), exposure bias %s" % (q.get_editor_property("white_temp"), q.get_editor_property("override_white_temp"), q.get_editor_property("auto_exposure_bias")))
    return cam


def movers(plan, gl, wz, fps, total_s):
    out, used = [], {}
    wake = V1B.obj_mesh("wake")
    for i, m in enumerate(plan.get("movers", []) if V1B.VEHICLES else []):
        role = ROLE.get(m["kind"], m["kind"])
        vs = B.kit(role)
        if not vs:
            continue
        v = vs[m["variant"] % len(vs)]; v["_len_axis"] = role != "abra"
        used[v["folder"]] = used.get(v["folder"], 0) + 1
        boat = role != "car"
        L = sum(math.hypot(m["path"][k + 1][0] - m["path"][k][0], m["path"][k + 1][1] - m["path"][k][1]) for k in range(len(m["path"]) - 1))
        keys, wkeys = [], []
        for j in range(0, int(total_s * 2) + 1):
            t = j * 0.5
            d = m["start_cm"] + m["speed_cms"] * t
            hide = m.get("hide_outside") and not (0.0 <= d <= L)
            p, dr = T0.along(m["path"], max(0.0, min(L, d)))
            yaw = math.degrees(math.atan2(dr[1], dr[0]))
            z = (wz if boat else gl) - (3000.0 if hide else 0.0)
            xf = B.place_xf(v, p[0], p[1], z, yaw)
            l, r = xf.translation, xf.rotation.rotator()
            keys.append((round(t * fps), (l.x, l.y, l.z), (r.roll, r.pitch, r.yaw)))
            wkeys.append((round(t * fps), (p[0], p[1], z + 3.0), (0.0, 0.0, yaw)))
        s = v["scale"]
        for pi, part in enumerate(v["parts"]):
            a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*keys[0][1]), unreal.Rotator(*keys[0][2]))
            a.set_actor_label("%sMOV_%s_%d_%d" % (B.PFX, role, i, pi))
            a.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
            a.static_mesh_component.set_static_mesh(part)
            a.set_actor_scale3d(unreal.Vector(s, s, s))
            out.append((a, keys))
        if boat and wake and m.get("wake"):
            a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*wkeys[0][1]))
            a.set_actor_label("%sMOV_wake_%d" % (B.PFX, i))
            a.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
            a.static_mesh_component.set_static_mesh(wake); a.static_mesh_component.set_cast_shadow(False)
            ws = m.get("len_cm", 1000.0) / 100.0
            a.set_actor_scale3d(unreal.Vector(ws, -ws, 1.0))
            out.append((a, wkeys))
    log("movers: %d part actors for %d movers" % (len(out), len(plan.get("movers", []))))
    return out, used


def sequence(plan, cam, movs):
    T0.CINE, T0.SEQ_NAME = CINE, SEQ_NAME
    T0.sequence(plan, cam, movs)


def mrq(name, out_dir, res, fps, frame=None):
    p = "%s/%s" % (CINE, name)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    cfg = tools.create_asset(name, CINE, unreal.MoviePipelinePrimaryConfig, unreal.MoviePipelinePrimaryConfigFactory())
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    if frame is None:
        o = cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_JPG)
        try:
            o.set_editor_property("quality", 95)
        except Exception:
            pass
    else:
        cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_resolution = unreal.IntPoint(*res); out.output_directory = unreal.DirectoryPath(out_dir)
    out.file_name_format = ("bb_v1.{frame_number}" if frame is None else name + ".{frame_number}")
    out.use_custom_frame_rate = True; out.output_frame_rate = unreal.FrameRate(fps, 1); out.zero_pad_frame_numbers = 4
    if frame is not None:
        out.set_editor_property("use_custom_playback_range", True)
        out.set_editor_property("custom_start_frame", frame); out.set_editor_property("custom_end_frame", frame + 1)
    aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = 1; aa.temporal_sample_count = 2 if frame is None else 4; aa.override_anti_aliasing = True
    aa.engine_warm_up_count = 64; aa.render_warm_up_count = 32; aa.use_camera_cut_for_warm_up = False
    go = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    for prop, val in (("texture_streaming", unreal.MoviePipelineTextureStreamingMethod.DISABLED), ("flush_grass_streaming", True), ("flush_streaming_managers", True)):
        try:
            go.set_editor_property(prop, val)
        except Exception:
            pass
    cv = cfg.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
    cv.set_editor_property("start_console_commands", ["DisableAllScreenMessages", "r.Lumen.Reflections.Allow 1", "r.Lumen.ScreenProbeGather.ScreenTraces 1",
                                                      "r.Shadow.Virtual.MaxPhysicalPages 2048", "foliage.LODDistanceScale 1.5"])
    eal.save_asset(p)
    log("%s: %dx%d frame %s -> %s" % (p, res[0], res[1], frame, out_dir))


def main():
    plan = json.load(open(V1B.PLAN, encoding="utf-8"))
    fps = int(plan["fps"])
    B.les().load_level(B.LEVEL)
    for a in list(ell.get_all_level_actors()):
        lab = a.get_actor_label() or ""
        if lab.startswith(B.PFX + "CAM") or lab.startswith(B.PFX + "MOV_"):
            ell.destroy_actor(a)
    if not eal.does_directory_exist(CINE):
        eal.make_directory(CINE)
    gz = json.load(open(B.USED, encoding="utf-8")).get("gz_cm", 0.0)
    gl = gz + plan["lift_cm"]; wz = gl + plan["water_z_cm"]
    cam = camera(plan)
    movs, used = movers(plan, gl, wz, fps, plan["total_s"])
    sequence(plan, cam, movs)
    mrq(MPC_NAME, RENDER_DIR, (1080, 1920), fps)
    for nm, fr in STILLS.items():
        mrq("MPC_BB_v1_Still_" + nm, STILL_DIR, (1080, 1920), fps, fr)
    B.les().save_all_dirty_levels()
    u = json.load(open(B.USED, encoding="utf-8")); u["movers"] = used
    json.dump(u, open(B.USED, "w", encoding="utf-8"), indent=1)
    log("tour v1 ready: %s/%s" % (CINE, SEQ_NAME))


if __name__ == "__main__":
    main()
