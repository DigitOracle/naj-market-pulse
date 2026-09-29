"""Unreal (commandlet): Business Bay v1 CLOSE-UP proof stills at eye level (Kendall 29 Sep: "I don't see any of the assets
at all"). The film's still frames are 60 m out on the canal / on a shop-less boulevard stretch, so street-level dressing
never shows. This builds SEQ_BB_v1_Close: a camera held 40 frames at each viewpoint (stepped keys), picked from the data:
  cafe      promenade cafe cluster (plan dress.prom_cafes) nearest the canal glide, looking along the promenade
  shops     a shopfront bay with an awning (storefronts_ue.json), from across the pavement
  tables    restaurant pavement tables (storefronts_ue.json tables) with their shopfront behind
Stills: MPC_BB_v1_Close_<name> (1080 x 1920 PNG, frame 30 / 70 / 110) -> Saved/MovieRenders/BB_v1_close
Render: logs/bb_v1_close.ps1
"""
import json, math, os, sys

import unreal

sys.path.insert(0, "C:/Dev/naj-market-pulse/scripts")
import ue_bb_v1_tour as T1

B = T1.B; T0 = T1.T0
log, eal, ell, tools = B.log, B.eal, B.ell, B.tools
CINE = T1.CINE
SEQ = "SEQ_BB_v1_Close"
OUT = T1.RENDER_DIR + "_close"
SF = B.REPO + "/data/ce/businessbay/storefronts_ue.json"
HOLD = 40


def views(plan, land):
    glide = [k[1] for k in plan["keys"] if 56 <= k[0] <= 77]
    S = json.load(open(SF, encoding="utf-8"))
    out = []
    cafes = plan["dress"].get("prom_cafes", [])
    if cafes:
        c = min(cafes, key=lambda r: min(math.hypot(r[0] - g[0], r[1] - g[1]) for g in glide))
        a = math.radians(c[2])
        d = (math.cos(a), math.sin(a))
        cam = (c[0] - d[0] * 1100.0, c[1] - d[1] * 1100.0, land + 170.0)
        out.append(("cafe", cam, (c[0], c[1], land + 90.0)))
    aw = S.get("awnings", [])
    if aw:
        x, y, yaw, w = aw[len(aw) // 3][:4]
        r = math.radians(yaw); n = (-math.sin(r), math.cos(r)); u = (math.cos(r), math.sin(r))
        cam = (x + n[0] * 1300.0 + u[0] * 500.0, y + n[1] * 1300.0 + u[1] * 500.0, land + 180.0)
        out.append(("shops", cam, (x, y, land + 300.0)))
    tb = S.get("tables", [])
    bays = S.get("bays", [])
    if tb and bays:
        t = tb[len(tb) // 2]
        b = min(bays, key=lambda q: math.hypot(q[0] - t[0], q[1] - t[1]))
        v = (t[0] - b[0], t[1] - b[1]); L = math.hypot(*v) or 1.0; v = (v[0] / L, v[1] / L)
        cam = (t[0] + v[0] * 700.0 - v[1] * 250.0, t[1] + v[1] * 700.0 + v[0] * 250.0, land + 160.0)
        out.append(("tables", cam, (b[0], b[1], land + 150.0)))
    return out


def main():
    plan = json.load(open(T1.V1B.PLAN, encoding="utf-8"))
    fps = int(plan["fps"])
    B.les().load_level(B.LEVEL)
    for a in list(ell.get_all_level_actors()):
        if (a.get_actor_label() or "").startswith(B.PFX + "CLOSECAM"):
            ell.destroy_actor(a)
    gz = json.load(open(B.USED, encoding="utf-8")).get("gz_cm", 0.0)
    land = gz + plan["lift_cm"]
    V = views(plan, land)
    cam = T1.camera(plan)
    cam.set_actor_label(B.PFX + "CLOSECAM")
    frames = HOLD * len(V)
    p = "%s/%s" % (CINE, SEQ)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    seq = tools.create_asset(SEQ, CINE, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq.set_display_rate(unreal.FrameRate(fps, 1)); seq.set_tick_resolution(unreal.FrameRate(fps * 1000, 1))
    seq.set_playback_start(0); seq.set_playback_end(frames)
    keys = []
    for i, (nm, c, t) in enumerate(V):
        r = T0.look_at(list(c), list(t))
        for f in (i * HOLD, i * HOLD + HOLD - 1):
            keys.append((f, c, (r.roll, r.pitch, r.yaw)))
        log("close %s: camera (%.0f, %.0f, %.1f m) -> (%.0f, %.0f)" % (nm, c[0] / 100, c[1] / 100, c[2] / 100, t[0] / 100, t[1] / 100))
    b = T0.add_transform_keys(seq, cam, keys, frames)
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack); cs = cut.add_section(); cs.set_range(0, frames)
    cs.set_camera_binding_id(seq.get_portable_binding_id(seq, b))
    eal.save_asset(p)
    for i, (nm, _, _) in enumerate(V):
        T1.mrq("MPC_BB_v1_Close_" + nm, OUT, (1080, 1920), fps, i * HOLD + 30)
    B.les().save_all_dirty_levels()
    log("close ready: %s (%s)" % (p, ", ".join(v[0] for v in V)))


if __name__ == "__main__":
    main()
