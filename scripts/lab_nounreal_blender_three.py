"""LAB (no-Unreal, research only): three.js v2 stills for the Cycles lane's extra cameras (street_r31s, eye_prom), so the
pairs sheet has a three.js column there too. Runs lab_nounreal_render.py UNCHANGED (imported; only its camera lookup is
redirected in this process) and writes data/lab/no_unreal/cycles/three/{street_r31s,eye_prom}.png + timings.json.

  python scripts/lab_nounreal_blender_three.py [--views street,eye] [any lab_nounreal_render.py look flags]
Waits like the Cycles lane (no blender.exe, no other lab_nounreal_render.py, free RAM >= 5 GB). Research only.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True                    # importing the renderer must not drop a .pyc into scripts/
sys.path.insert(0, HERE)
import lab_nounreal_blender as B  # noqa: E402
import lab_nounreal_render as R   # noqa: E402


def main():
    names = (B.arg("--views", "street,eye")).split(",")
    vs = B.views(names)
    ue = {i + 1: v for i, v in enumerate(vs)}                      # fake film times 1, 2, ... -> our cameras (UE cm)
    P = B.plan()
    to_ue = lambda p: [(p[0] - (R.UE_E0 - R.BB_ORIGIN[0])) * 100.0, (p[2] - (R.BB_ORIGIN[1] - R.UE_N0)) * 100.0, p[1] * 100.0]
    R.film_to_render_t = lambda plan, ft: ft
    R.cam_at = lambda plan, rt: (to_ue(ue[int(rt)]["pos"]), to_ue(ue[int(rt)]["tgt"]))
    rest = [a for a in sys.argv[1:] if a not in ("--views", B.arg("--views", "@@"))]
    sys.argv = [os.path.join(HERE, "lab_nounreal_render.py"), "stills", "--film", ",".join(str(k) for k in ue), "--out", "cycles/three"] + rest
    B.wait_turn(5.0)
    R.main()
    d = os.path.join(R.OUT, "cycles", "three")
    tm = json.load(open(os.path.join(d, "timings.json")))
    for k, v in ue.items():
        src = os.path.join(d, "film_t%gs.png" % k)
        if os.path.exists(src):
            os.replace(src, os.path.join(d, v["name"] + ".png"))
    for f in tm.get("frames", []):
        f["name"] = ue[int(f["film_t"])]["name"]; f.pop("film_t", None); f.pop("render_t", None)
    json.dump(tm, open(os.path.join(d, "timings.json"), "w"), indent=1)
    print("three.js stills:", ", ".join(v["name"] for v in vs))
    del P


if __name__ == "__main__":
    main()
