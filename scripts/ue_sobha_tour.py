"""Unreal (commandlet): the Sobha TOUR - every Sobha cluster in Dubai, zoom in, circle, pull out, on to the next.

Kendall, 24 Sep 2026: "for each of these clusters we should be zooming in, doing a circular, then leaving back out and
then zooming to the next ... assess how many clusters that is ... leave the other buildings out of it, but we have to
have the context of where this is in Dubai."

Clusters are found from the level itself: every Sobha-tagged building (ue_sobha_lens.py), single-linkage within
CLUSTER_M, and a cluster earns a stop when it has two or more buildings or one tower over TOWER_STOP_M. On 24 Sep that
is nine stops out of eleven groups (The Serene, a 12 m stub in Dubai South, and the single 38 m Daffodil in JVC are
passed over). The tour is a nearest-neighbour walk from Sobha Hartland.

Per stop, in seconds (STOP_S = 12):  arrive high and wide (1.5 km out, ~900 m up)  ->  drop onto the orbit  ->
180-degree orbit at ~1.6 x the tallest tower's height out and 0.6 x its height up  ->  pull back out high  ->  transit
to the next stop's arrival point. The pull-outs and transits are what give Dubai context: the ground is the Esri World
Imagery mosaic of the whole Sobha box (data/ce/_datasmith/sobha_context.jpg, 31 x 45 km, EPSG:32640, north up),
placed by the same offset the districts were exported with, so the coast, the canal, the roads and the empty desert are
where they are - without a single non-Sobha building in the model. Sun, sky, fog: the golden-hour set from v9.

Writes SEQ_Sobha_Tour + MPC_Sobha_Tour (4:5, 1080 x 1350) under /Game/Najma/Cinematics, the texture and material
under /Game/Najma/Sobha, saves Main. Then: render (MRQ, -game) and stitch, as logs/ue_tour_chain.ps1 does.
Usage:  UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_tour.py
"""
import json, math, os

import unreal

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_sobha_flythrough as F   # lighting(), find(), spawn(), look_at(), the level / cinematics paths

LEVEL = "/Game/Main"; CINE = "/Game/Najma/Cinematics"; SOBHA_DIR = "/Game/Najma/Sobha"
SEQ_NAME, MPC_NAME = "SEQ_Sobha_Tour", "MPC_Sobha_Tour"
FPS = 30
RENDER_DIR = "C:/Dev/UnrealProjects/AzimuthDubai/Saved/MovieRenders/SobhaTour"
CONTEXT_JPG = "C:/Dev/naj-market-pulse/data/ce/_datasmith/sobha_context.jpg"
CONTEXT_JSON = "C:/Dev/naj-market-pulse/data/ce/_datasmith/sobha_context.json"
OFFSET_E, OFFSET_N = 328289.0, 2784598.0          # the CityEngine global offset every district was exported with
CLUSTER_M = 700.0; TOWER_STOP_M = 100.0
STOP_S = 12.0; ORBIT_DEG = 180.0
FLIP_NS = False                                    # set if the imagery renders mirrored north-south

log = unreal.log; eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary


def sobha_buildings():
    out = []
    for a in ell.get_all_level_actors():
        tags = [str(t) for t in a.tags]
        if "sobha" not in tags or "duplicate" in tags or not isinstance(a, unreal.StaticMeshActor):
            continue
        o, e = a.get_actor_bounds(False)
        name = next((t[6:] for t in tags if t.startswith("sobha:") and not t[6:] in ("parcel", "dm", "radius", "geocode")), a.get_actor_label())
        out.append({"x": o.x, "y": o.y, "ex": e.x, "ey": e.y, "h": e.z * 2, "name": name, "district": next((t[9:] for t in tags if t.startswith("district:")), "?")})
    return out


def clusters(blds):
    cl = []
    for b in blds:
        hit = [c for c in cl if any(math.hypot(b["x"] - q["x"], b["y"] - q["y"]) < CLUSTER_M * 100 for q in c)]
        if not hit:
            cl.append([b])
        else:
            base = hit[0]; base.append(b)
            for o in hit[1:]:
                base.extend(o); cl.remove(o)
    out = []
    for c in cl:
        tallest = max(c, key=lambda b: b["h"])
        if len(c) < 2 and tallest["h"] < TOWER_STOP_M * 100:
            log("  passed over: %s (%d building, %.0f m)" % (tallest["name"], len(c), tallest["h"] / 100)); continue
        # Kendall, 24 Sep 2026: "make sure you capture the entire district when you rotate" - the orbit centres on the
        # middle of the cluster's whole footprint (not its tallest tower) and rc is the reach from there to its farthest wall
        x0 = min(b["x"] - b["ex"] for b in c); x1 = max(b["x"] + b["ex"] for b in c)
        y0 = min(b["y"] - b["ey"] for b in c); y1 = max(b["y"] + b["ey"] for b in c)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        rc = max(math.hypot(b["x"] - cx, b["y"] - cy) + math.hypot(b["ex"], b["ey"]) for b in c)
        out.append({"cx": cx, "cy": cy, "rc": rc, "h": tallest["h"], "n": len(c), "name": tallest["name"],
                    "district": tallest["district"], "names": sorted({b["name"] for b in c})})
    # nearest-neighbour walk from Sobha Hartland (the Creek Vistas cluster)
    start = next((c for c in out if c["district"] == "sobhaheartland"), out[0])
    order = [start]; rest = [c for c in out if c is not start]
    while rest:
        last = order[-1]
        nxt = min(rest, key=lambda c: math.hypot(c["cx"] - last["cx"], c["cy"] - last["cy"]))
        order.append(nxt); rest.remove(nxt)
    return order


def tour_keys(stops):
    """(time_s, location, look_at) - one list for the whole tour."""
    keys = []; t = 0.0
    prev_dir = None
    for i, s in enumerate(stops):
        # whole-cluster framing: 24 mm on a 24 x 30 filmback -> tan(half horizontal FOV) = 0.5; the cluster's reach rc
        # must fit inside ~85% of the half-width at the slant distance D, and the tallest tower still gets 1.6 x its height
        H = s["h"]; rc = s.get("rc", 0.0)
        D = max(rc / (0.5 * 0.85), 1.6 * H, 30000.0)
        PITCH = math.radians(30.0)                                        # looking down 30 degrees: the plan reads, towers still stand
        look = (s["cx"], s["cy"], H * 0.3)
        R = D * math.cos(PITCH); z_orb = look[2] + D * math.sin(PITCH)
        FAR = max(150000.0, 1.7 * R); ZFAR = max(H + 90000.0, 1.5 * z_orb)
        # come in from the direction of the previous stop (or from the south-west for the first)
        if prev_dir is None:
            th0 = math.radians(225.0)
        else:
            th0 = prev_dir
        far = (s["cx"] + math.cos(th0) * FAR, s["cy"] + math.sin(th0) * FAR, ZFAR)
        keys.append((t, far, look))                                                    # arrive
        keys.append((t + 2.5, (s["cx"] + math.cos(th0) * R, s["cy"] + math.sin(th0) * R, z_orb), look))   # on the orbit
        n = 6
        for k in range(1, n + 1):
            th = th0 + math.radians(ORBIT_DEG) * k / n
            # constant radius: the whole cluster stays in frame the whole way round (v7 closed in 15% and cropped it)
            keys.append((t + 2.5 + 6.0 * k / n, (s["cx"] + math.cos(th) * R, s["cy"] + math.sin(th) * R, z_orb), look))
        th_end = th0 + math.radians(ORBIT_DEG)
        out = (s["cx"] + math.cos(th_end) * FAR * 1.05, s["cy"] + math.sin(th_end) * FAR * 1.05, ZFAR * 1.05)
        keys.append((t + STOP_S - 0.5, out, look))                                     # pull out, still looking back
        t += STOP_S
        if i + 1 < len(stops):
            nx = stops[i + 1]
            prev_dir = math.atan2(s["cy"] - nx["cy"], s["cx"] - nx["cx"])                # arrive at the next from this side
    return keys, t


def context_ground():
    meta = json.load(open(CONTEXT_JSON, encoding="utf-8"))
    x0, y0, x1, y1 = meta["utm_bbox"]
    tex_path = SOBHA_DIR + "/T_SobhaContext"
    if not eal.does_asset_exist(tex_path):
        task = unreal.AssetImportTask()
        task.filename = CONTEXT_JPG; task.destination_path = SOBHA_DIR; task.destination_name = "T_SobhaContext"
        task.automated = True; task.save = True; task.replace_existing = True
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = eal.load_asset(tex_path)
    if tex is None:
        raise RuntimeError("context texture did not import")
    try:
        tex.set_editor_property("max_texture_size", 4096); tex.set_editor_property("srgb", True)
    except Exception:
        pass
    mat_path = SOBHA_DIR + "/M_SobhaContext"
    if not eal.does_asset_exist(mat_path):
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_SobhaContext", SOBHA_DIR, unreal.Material, unreal.MaterialFactoryNew())
        ts = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -400, 0)
        ts.texture = tex
        unreal.MaterialEditingLibrary.connect_material_property(ts, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
        rough = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 300)
        rough.r = 0.95
        unreal.MaterialEditingLibrary.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
        unreal.MaterialEditingLibrary.recompile_material(mat)
        eal.save_asset(mat_path)
    mat = eal.load_asset(mat_path)
    old = F.find("GROUND_Sobha")
    if old:
        old.set_actor_hidden_in_game(True); old.set_is_temporarily_hidden_in_editor(True)
    g = F.find("GROUND_Context")
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ux, uy = (cx - OFFSET_E) * 100.0, (OFFSET_N - cy) * 100.0     # UE X = easting - offset, UE Y = offset - northing (cm)
    if not g:
        g = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(ux, uy, -20.0)); g.set_actor_label("GROUND_Context")
        g.static_mesh_component.set_static_mesh(eal.load_asset("/Engine/BasicShapes/Plane"))
    g.set_actor_location(unreal.Vector(ux, uy, -20.0), False, False)
    # the basic Plane is 1 m; its +Y is UE south here and the image's top row is north, so no flip unless it renders mirrored
    g.set_actor_scale3d(unreal.Vector((x1 - x0), (y1 - y0) * (-1.0 if FLIP_NS else 1.0), 1.0))
    g.static_mesh_component.set_material(0, mat)
    log("  context ground: %.1f x %.1f km at UE (%.0f, %.0f) m - %s" % ((x1 - x0) / 1000, (y1 - y0) / 1000, ux / 100, uy / 100, meta.get("attribution", "")[:60]))


def sequence(cam, keys, total_s):
    frames = int(round(total_s * FPS))
    p = "%s/%s" % (CINE, SEQ_NAME)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(SEQ_NAME, CINE, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(FPS, 1)); seq.set_tick_resolution(unreal.FrameRate(FPS * 800, 1))
    seq.set_playback_start(0); seq.set_playback_end(frames)
    b = seq.add_possessable(cam)
    tt = b.add_track(unreal.MovieScene3DTransformTrack); sec = tt.add_section(); sec.set_range(0, frames)
    ch = sec.get_all_channels()
    prev_yaw = None
    for (ts, loc, tgt) in keys:
        rot = F.look_at(loc, tgt); yaw = rot.yaw
        if prev_yaw is not None:
            while yaw - prev_yaw > 180: yaw -= 360
            while yaw - prev_yaw < -180: yaw += 360
        prev_yaw = yaw
        f = int(round(ts * FPS))
        for c, v in zip(ch, [loc[0], loc[1], loc[2], rot.roll, rot.pitch, yaw, 1.0, 1.0, 1.0]):
            k = c.add_key(unreal.FrameNumber(f), float(v))
            try:
                k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_CUBIC); k.set_tangent_mode(unreal.RichCurveTangentMode.RCTM_AUTO)
            except Exception:
                pass
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack); cs = cut.add_section(); cs.set_range(0, frames)
    bid = None
    for make in (lambda: seq.get_binding_id(b), lambda: unreal.MovieSceneSequenceExtensions.get_binding_id(seq, b)):
        try:
            bid = make(); break
        except Exception:
            pass
    cs.set_camera_binding_id(bid)
    eal.save_asset(p)
    log("  %s: %d keys, %d frames (%.0f s)" % (p, len(keys), frames, total_s))


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
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_JPG)
    out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_resolution = unreal.IntPoint(1080, 1350); out.output_directory = unreal.DirectoryPath(RENDER_DIR)
    out.file_name_format = "sobha_tour.{frame_number}"; out.use_custom_frame_rate = True; out.output_frame_rate = unreal.FrameRate(FPS, 1)
    aa = cfg.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = 1; aa.temporal_sample_count = 2; aa.override_anti_aliasing = True
    aa.engine_warm_up_count = 64; aa.render_warm_up_count = 32; aa.use_camera_cut_for_warm_up = True
    go = cfg.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    for prop, val in (("texture_streaming", unreal.MoviePipelineTextureStreamingMethod.DISABLED), ("flush_grass_streaming", True), ("flush_streaming_managers", True)):
        try:
            go.set_editor_property(prop, val)
        except Exception:
            pass
    eal.save_asset(p)


def main():
    ell.load_level(LEVEL)
    blds = sobha_buildings()
    stops = clusters(blds)
    log("Sobha tour: %d buildings, %d stops" % (len(blds), len(stops)))
    for i, s in enumerate(stops):
        log("  %d. %-22s %-18s %2d bldg  tallest %.0f m  reach %.0f m  %s" % (i + 1, s["district"], s["name"][:18], s["n"], s["h"] / 100, s["rc"] / 100, ", ".join(s["names"])[:70]))
    centre = unreal.Vector(sum(s["cx"] for s in stops) / len(stops), sum(s["cy"] for s in stops) / len(stops), 0)
    F.lighting(centre)
    # 24 Sep 2026: the ground is Unreal-made (procedural sand + real water from OSM) unless SOBHA_GROUND=imagery asks
    # for the satellite mosaic back
    if os.environ.get("SOBHA_GROUND", "unreal") == "imagery":
        context_ground()
    else:
        import ue_sobha_ground
        ue_sobha_ground.main(save=False)
    cam = F.find("CAM_Sobha") or ell.spawn_actor_from_class(unreal.CineCameraActor, centre); cam.set_actor_label("CAM_Sobha")
    try:
        cc = cam.camera_component
        cc.filmback.sensor_width = 24.0; cc.filmback.sensor_height = 30.0; cc.current_focal_length = 24.0; cc.current_aperture = 8.0
        cc.focus_settings.focus_method = unreal.CameraFocusMethod.DISABLE
        cc.post_process_settings.set_editor_property("override_auto_exposure_bias", True); cc.post_process_settings.set_editor_property("auto_exposure_bias", -0.2)
        cc.post_process_settings.set_editor_property("override_bloom_intensity", True); cc.post_process_settings.set_editor_property("bloom_intensity", 0.35)
        cc.post_process_settings.set_editor_property("override_vignette_intensity", True); cc.post_process_settings.set_editor_property("vignette_intensity", 0.35)
    except Exception as e:
        log("  camera: %s" % e)
    keys, total = tour_keys(stops)
    sun = F.find("SUN_Sobha")
    if sun:
        sun.set_actor_rotation(unreal.Rotator(0.0, -11.0, 250.0), False)   # golden hour from the west; the orbits sweep past it
    cam.set_actor_location(unreal.Vector(*keys[0][1]), False, False); cam.set_actor_rotation(F.look_at(keys[0][1], keys[0][2]), False)
    sequence(cam, keys, total)
    mrq_config()
    ell.save_current_level()
    log("Sobha tour: ready - %d stops, %.0f s - render -LevelSequence=%s/%s -MoviePipelineConfig=%s/%s" % (len(stops), total, CINE, SEQ_NAME, CINE, MPC_NAME))


if __name__ == "__main__":
    main()
