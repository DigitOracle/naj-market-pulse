"""STAGE 2 of Business Bay in Unreal: build a camera and a sequence for each tower. Still renders nothing.

Run inside Unreal's Python console (Output Log, entry box switched from Cmd to Python):

    exec(open(r"C:\\Dev\\naj-market-pulse\\scripts\\ue_businessbay_stage2.py").read())

By default it builds the first 3 only, so the framing can be looked at before 189 of them exist. To build the rest:

    import ue_businessbay_stage2 as s2; s2.main(limit=None)

or edit LIMIT below. Re-running replaces what it made; nothing else in the level is touched.

WHAT IT MAKES, per planned building:
    CAM_b<i>            a CineCameraActor at the position build_unreal_camera_plan.py chose, aimed at the building
    Seq_b<i>_<name>     a LevelSequence: 5 s at 24 fps, one camera cut, and a slow ORBIT_DEG arc around the subject

It does NOT render, queue, or publish anything. Stage 3 does that, and only for the buildings whose clips look right.

WHERE THE NUMBERS COME FROM. Every position is measured, not derived: stage 1 read each actor's world bounds out of
the editor, and the plan turned those into a camera stand-off and a bearing. This script does no geometry of its own
beyond pointing the camera at the look_at the plan recorded. That is deliberate - the CityEngine to Unreal transform
has already caused one wrong conclusion tonight, and nothing here needs to know it.

THE ARC IS AROUND THE SUBJECT, NOT AROUND THE CAMERA. The camera swings ORBIT_DEG about the building's own vertical
axis at a fixed radius, re-aiming at the look_at on every key, so the building stays centred while the light and the
facade relief move across it. A pan from a fixed point would show the neighbours instead.

BEARINGS WERE CHOSEN TO AVOID OCCLUSION, so the arc is centred on the chosen bearing and kept short. Widening it
walks the camera back into the neighbours the plan was avoiding - the plan records clear_bearings per building, and
an arc wider than that many 10 degree steps is not safe.
"""
import json
import os
import unreal

ROOT = r"C:\Dev\naj-market-pulse"
PLAN = os.path.join(ROOT, "data", "board", "unreal_camera_plan_businessbay.json")
REPORT = os.path.join(ROOT, "data", "board", "unreal_stage2_businessbay.json")
SEQ_DIR = "/Game/Azimuth/Sequences"

LIMIT = 3                 # how many to build by default; main(limit=None) builds all
FPS = 24
SECONDS = 5.0
ORBIT_DEG = 24.0          # total sweep, centred on the plan's bearing
FOCAL_MM = 35.0
FILM_W, FILM_H = 18.0, 22.5

ell = unreal.EditorLevelLibrary
eal = unreal.EditorAssetLibrary


def log(m):
    unreal.log("[azimuth] " + str(m))


def safe(s):
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(s))
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")[:40] or "x"


def look_rotation(frm, to):
    """Rotator aiming from one point at another. unreal.Vector has this built in; no trigonometry of mine."""
    return (unreal.Vector(to[0] - frm[0], to[1] - frm[1], to[2] - frm[2])).rotation()


def existing_actor(label):
    for a in ell.get_all_level_actors():
        try:
            if a.get_actor_label() == label:
                return a
        except Exception:
            pass
    return None


def make_camera(label, loc, rot):
    a = existing_actor(label)
    if a is None:
        a = ell.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(*loc), rot)
        a.set_actor_label(label)
    else:
        a.set_actor_location_and_rotation(unreal.Vector(*loc), rot, False, False)
    comp = a.camera_component
    comp.set_editor_property("current_focal_length", FOCAL_MM)
    fb = comp.get_editor_property("filmback")
    fb.set_editor_property("sensor_width", FILM_W)
    fb.set_editor_property("sensor_height", FILM_H)
    comp.set_editor_property("filmback", fb)
    # manual focus at the subject keeps the depth of field from hunting mid-shot
    fs = comp.get_editor_property("focus_settings")
    fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
    comp.set_editor_property("focus_settings", fs)
    return a


def binding_id(seq, binding):
    """UE has moved this API twice. Try each form and use the one this build has, rather than assume."""
    for fn in (lambda: unreal.MovieSceneSequenceExtensions.make_binding_id(seq, binding),
               lambda: seq.make_binding_id(binding)):
        try:
            return fn()
        except Exception:
            pass
    bid = unreal.MovieSceneObjectBindingID()
    bid.set_editor_property("guid", binding.get_id())
    return bid


def build_sequence(rec, cam):
    """A 5 s orbit around one building, as its own asset so Movie Render Queue can batch them."""
    name = "Seq_b%d_%s" % (rec["i"], safe(rec["name"]))
    path = "%s/%s" % (SEQ_DIR, name)
    if eal.does_asset_exist(path):
        eal.delete_asset(path)
    if not eal.does_directory_exist(SEQ_DIR):
        eal.make_directory(SEQ_DIR)
    seq = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, SEQ_DIR, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    frames = int(FPS * SECONDS)
    seq.set_display_rate(unreal.FrameRate(FPS, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(frames)

    cb = seq.add_possessable(cam)
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack)
    cs = cut.add_section()
    cs.set_range(0, frames)
    cs.set_camera_binding_id(binding_id(seq, cb))

    tr = cb.add_track(unreal.MovieScene3DTransformTrack)
    ts = tr.add_section()
    ts.set_range(0, frames)
    ch = ts.get_channels()          # loc x,y,z then rot roll,pitch,yaw then scale x,y,z

    import math
    look = rec["look_at"]
    r = rec["distance_uu"]
    b0 = math.radians(rec["bearing_deg"]) - math.radians(ORBIT_DEG) / 2.0
    z = rec["camera_location"][2]
    keys = 9                        # enough for a smooth arc without a key per frame
    for k in range(keys):
        f = int(round(frames * k / (keys - 1.0)))
        ang = b0 + math.radians(ORBIT_DEG) * (k / (keys - 1.0))
        x = look[0] + math.cos(ang) * r
        y = look[1] + math.sin(ang) * r
        rot = look_rotation([x, y, z], look)
        for chan, val in ((ch[0], x), (ch[1], y), (ch[2], z),
                          (ch[3], rot.roll), (ch[4], rot.pitch), (ch[5], rot.yaw)):
            chan.add_key(unreal.FrameNumber(f), float(val))
    eal.save_asset(path)
    return path


def main(limit=LIMIT):
    plan = json.load(open(PLAN, encoding="utf-8"))
    rows = plan["planned"]
    if limit:
        rows = rows[:limit]
    log("stage 2: building %d of %d planned cameras (%s)"
        % (len(rows), len(plan["planned"]), "all" if not limit else "trial - main(limit=None) for the rest"))
    log("plan scored occlusion against %d buildings" % plan.get("obstacles_counted", 0))

    made, failed = [], []
    for rec in rows:
        try:
            cam = make_camera("CAM_b%d" % rec["i"],
                              rec["camera_location"],
                              look_rotation(rec["camera_location"], rec["look_at"]))
            p = build_sequence(rec, cam)
            made.append({"i": rec["i"], "name": rec["name"], "camera": cam.get_actor_label(), "sequence": p,
                         "height_m": rec["height_m"], "distance_m": round(rec["distance_uu"] / 100, 1),
                         "bearing_deg": rec["bearing_deg"], "occlusion": rec["occlusion"]})
            log("   b%-5d %-32s cam %sm out, bearing %.0f" % (rec["i"], rec["name"][:32],
                                                              round(rec["distance_uu"] / 100), rec["bearing_deg"]))
        except Exception as e:
            failed.append({"i": rec["i"], "name": rec["name"], "error": str(e)})
            log("   b%-5d FAILED: %s" % (rec["i"], e))

    out = {"district": "businessbay", "fps": FPS, "seconds": SECONDS, "orbit_deg": ORBIT_DEG,
           "lens": {"focal_mm": FOCAL_MM, "filmback_mm": [FILM_W, FILM_H]},
           "built": len(made), "failed": len(failed),
           "of_planned": len(plan["planned"]), "held": plan["counts"]["held"],
           "note": "cameras and sequences only. Nothing is rendered or published here; that is stage 3, and only for "
                   "the buildings whose clips look right.",
           "made": made, "failures": failed}
    json.dump(out, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("=" * 64)
    log("BUILT %d, failed %d -> %s" % (len(made), len(failed), REPORT))
    if not limit:
        log("all planned cameras built")
    else:
        log("trial only. Look at one in Sequencer, then: main(limit=None)")
    log("=" * 64)


main()
