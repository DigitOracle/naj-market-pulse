"""LAB (no-Unreal, research only): ONE command from camera plan to finished film, with no Unreal anywhere.

  python scripts/lab_nounreal_film.py <plan.json> --out <film.mp4> [--mb 2] [--music] [--no-title] [--keep-frames]
                                                  [--render-args "<extra lab_nounreal_render.py flags>"]
  python scripts/lab_nounreal_film.py auto --district <slug> --out <film.mp4> [--secs 30] [--title "Dubai Marina"]
        any district: data/ce/_glb/sky_<slug>_v5_0.glb + data/ce/<slug>/origin_v5.json; scenery from
        data/lab/context/<slug>/manifest.json when present, else the district's context_ue.json + water.json ground;
        with no film plan, one is generated (same schema as bb_v1_plan.json): an orbit, then a flyover along the long axis

  1. frames   lab_nounreal_render.py frames: the plan's camera keys -> headless three.js (Chromium, local GPU) -> one JPEG
              per frame index, named like MRQ's output (bb_v1.<frame>.jpeg), ONLY the frames the edit reads (frame 0, every
              EDIT window, the TEASER windows) - about 1,400 of the path's 3,025
  2. encode   scripts/bb_v1_encode.py main(), imported and run unchanged except for its paths: the same bar-grid edit, the
              same ffmpeg grade (BB_V1_GRADE), the same title card over the opener, the same end card, the same share copy
              and ep08-style teaser, the same optional music (BB_V1_MUSIC) - pointed at our frames and our output folder
  3. credits  the credits file lists what THIS film used (three.js, the scenery agent's ESRI.lib plants, the converted
              crane, the golden-bay HDRI, OpenStreetMap / CityEngine buildings), not the Unreal library
Writes <out>, <out>_share.mp4, <out dir>/teaser_<name>.mp4, *_credits.txt and <out>.timings.json.

What it replaces (logs/bb_v1_run.ps1 + logs/bb_phase0_run.ps1, UE 5.8, project C:/Dev/UnrealProjects/AzimuthDubai):
  UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=scripts/ue_library_import.py      (kit import, Nanite, masters)
  UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=scripts/ue_bb_v1_build.py         (level L_BB_v1: Datasmith
      import of businessbay_lod3 + burjkhalifa_lod3, facades M_DA_Facade2, ground/water/sand, sky/sun/fog/PPV, dressing,
      landmarks/crowns/cranes, storefronts)
  UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=scripts/ue_bb_v1_tour.py          (SEQ_BB_v1 Level Sequence,
      camera post, movers, MPC_BB_v1 / MPC_BB_v1_Still_* Movie Render Queue configs)
  UnrealEditor.exe <uproject> /Game/BusinessBay/L_BB_v1 -game -LevelSequence=.../SEQ_BB_v1
      -MoviePipelineConfig=.../MPC_BB_v1                                                      (the MRQ render -> Saved/MovieRenders/BB_v1)
  (and for stills: -MoviePipelineConfig=MPC_BB_v1_Still_<name>; close-ups: ue_bb_v1_close.py via logs/bb_v1_close.ps1)
Kept as they are (plain CPython, no Unreal): scripts/bb_v1_prep.py (the plan, placements, context OBJs) and
scripts/bb_v1_encode.py (the edit - imported here). Scope: the Business Bay scene (the renderer's inputs are Business Bay's
GLBs / context); a new district needs its own GLB + context paths in lab_nounreal_render.py.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)


def arg(k, d=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


def auto_plan(slug, secs=30.0, fps=25, out=None):
    """a bb_v1_plan.json-schema plan for any district: first half a slow 120-degree orbit of the district centre, second half a
    flyover along the district's long axis (PCA of the footprints); cut by bb_v1_encode on the same 2.14 s bar grid"""
    import math
    import numpy as np
    from pyproj import Transformer
    T = Transformer.from_crs(4326, 32640, always_xy=True)
    g = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))
    pts, hs = [], []
    for f in g["features"]:
        geom = f["geometry"]; ring = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
        xy = [T.transform(lon, lat) for lon, lat in ring[:-1] or ring]
        pts.append((sum(p[0] for p in xy) / len(xy), sum(p[1] for p in xy) / len(xy))); hs.append(float(f["properties"].get("bHeight") or 20.0))
    P = np.array(pts); c = P.mean(0)
    ue = lambda e, n, z=0.0: [(e - 328289.0) * 100.0, (2784598.0 - n) * 100.0, z * 100.0]      # the city-wide Unreal frame
    ev, evec = np.linalg.eigh(np.cov((P - c).T)); ax = evec[:, int(np.argmax(ev))]; ax = ax / np.linalg.norm(ax)
    proj = (P - c) @ ax; L = float(np.percentile(proj, 97) - np.percentile(proj, 3))
    reach = float(np.percentile(np.linalg.norm(P - c, axis=1), 95)); tall = float(max(hs))          # clear the tallest tower
    half = secs / 2.0; keys = []
    R = max(900.0, 1.05 * reach); hgt = max(450.0, 0.5 * R, 1.6 * tall); a0 = math.atan2(-ax[1], -ax[0])
    for i in range(int(round(secs / 0.2)) + 1):
        t = round(i * 0.2, 3)
        if t <= half:                                            # orbit: 120 degrees, eased, looking at the centre 30 m up
            u = t / half; a = a0 + math.radians(120.0) * (0.5 - 0.5 * math.cos(math.pi * u))
            cam = ue(c[0] + R * math.cos(a), c[1] + R * math.sin(a), hgt); tgt = ue(c[0], c[1], 30.0)
        else:                                                    # flyover along the long axis, 250 m up, looking 45 deg ahead-down
            u = (t - half) / half; d = -0.55 * L + 1.1 * L * u
            e, n = c[0] + ax[0] * d, c[1] + ax[1] * d; fh = max(250.0, 1.15 * tall)
            cam = ue(e, n, fh); tgt = ue(e + ax[0] * fh * 1.2, n + ax[1] * fh * 1.2, 0.0)
        keys.append([t, [round(v, 1) for v in cam], [round(v, 1) for v in tgt]])
    lo, hi = P.min(0), P.max(0)
    bar = 2.14; bars = int(half // bar) - 1                       # e.g. 6 bars per half at 30 s: 2 x 12.84 s + the 4.28 s card = 29.96 s
    plan = {"generated_by": "lab_nounreal_film.auto_plan", "district_slug": slug, "fps": fps, "total_s": secs, "focal_mm": 20.0, "bar_s": bar,
            "edit": [[0.3, bars], [round(half + 0.2, 2), bars]], "teaser": [[round(secs - 20.0, 2), secs]] if secs >= 20 else [],
            "lift_cm": 0.0, "gz_cm": 0.0, "water_z_cm": 0.0, "keys": keys,
            "district": {"bbox_cm": ue(lo[0], hi[1]) [:2] + ue(hi[0], lo[1])[:2], "centre_cm": ue(c[0], c[1])[:2], "reach_cm": reach * 100.0,
                         "tallest_cm": tall * 100.0, "buildings": len(pts)},
            "district_cfg": {"slug": slug, "sun_elev_deg": 33.0}, "dress": {}}
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True); json.dump(plan, open(out, "w"), indent=0)
    return plan


def title_patch(E, title):
    """bb_v1_encode's title / end cards say Business Bay: swap the district name in, nothing else"""
    tf = E.textfile

    def textfile(name, text):
        return tf(name, text.replace("BUSINESS BAY", title.upper()).replace("Business Bay", title))
    E.textfile = textfile


def three_credits(E, used_parasol=False, title="Business Bay"):
    """a credits writer for the three.js film (replaces bb_v1_encode.write_credits, which lists the Unreal library)"""
    kits = os.path.join(ROOT, "data", "lab", "no_unreal", "kits")
    crane = open(os.path.join(kits, "tower_crane_CREDIT.txt"), encoding="utf-8", errors="replace").read().strip() if os.path.exists(os.path.join(kits, "tower_crane_CREDIT.txt")) else ""

    def write_credits(mp4, with_music, note=""):
        L = ["%s, Dubai - fly-through (internal research, rendered WITHOUT Unreal: headless three.js). DigitAlchemy(R) Tech Limited, contact@digitalabbot.io" % title, ""]
        if note:
            L += [note, ""]
        L += (["Music:", E.MUSIC_LINE, ""] if with_music else ["Music: none in this file.", ""])
        L += ["3D models (CC BY 4.0 - attribution required):",
              "  Tower crane (Liebherr), Sketchfab - %s (C:/Dev/assets/sketchfab_construction/liebherr-tower-crane/CREDIT.txt)" % (crane or "see CREDIT.txt"), ""]
        L += ["Other assets:",
              "  Palms, trees, shrubs: Esri CityEngine ESRI.lib Webstyles/Vegetation/LowPoly (via the scenery lab, data/lab/context/businessbay)",
              "  Street furniture, lamps, cafe sets, site props: CGA primitives (data/lab/context/businessbay/rules/lab_context.cga)",
              "  Sky light: 'Golden Bay' HDRI, Poly Haven (CC0)",
              "  Renderer: three.js r169 (MIT); mp4-muxer (MIT)", ""]
        L += ["Buildings: CityEngine LOD3 model of %s (DigitAlchemy, internal research use); streets and water from OpenStreetMap" % title,
              "(c) OpenStreetMap contributors, ODbL; Overture Maps water."]
        p = os.path.splitext(mp4)[0] + "_credits.txt"
        open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
        print("credits ->", p)
    return write_credits


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        raise SystemExit(__doc__)
    out = os.path.abspath(arg("--out", os.path.join(ROOT, "data", "lab", "no_unreal", "film_final", "bb_v1_three_9x16.mp4")))
    out_dir = os.path.dirname(out); os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(out))[0]
    slug = arg("--district")
    if sys.argv[1] == "auto" or not os.path.exists(sys.argv[1]):   # no film plan: generate one
        if not slug:
            raise SystemExit("auto plan needs --district <slug>")
        plan_path = os.path.join(out_dir, "plan_%s_auto.json" % slug)
        auto_plan(slug, float(arg("--secs", 30.0)), out=plan_path); print("generated plan", plan_path, flush=True)
    else:
        plan_path = os.path.abspath(sys.argv[1])
    slug = slug or json.load(open(plan_path, encoding="utf-8")).get("district_slug", "businessbay")
    title = arg("--title", {"businessbay": "Business Bay", "dubaimarina": "Dubai Marina"}.get(slug, slug.replace("_", " ").title()))
    work = os.path.join(out_dir, "_" + name + "_work"); os.makedirs(work, exist_ok=True)
    rel_work = os.path.relpath(work, os.path.join(ROOT, "data", "lab", "no_unreal"))
    if rel_work.startswith(".."):
        raise SystemExit("--out must be under data/lab/no_unreal (lab outputs only)")
    T = {"plan": plan_path, "district": slug, "out": out}
    t_all = time.time()
    # 1. frames ------------------------------------------------------------------------------------------------------
    t = time.time()
    cmd = [sys.executable, os.path.join(HERE, "lab_nounreal_render.py"), "frames", "--plan", plan_path, "--district", slug, "--indices", "edit", "--out", rel_work,
           "--w", arg("--w", "1080"), "--h", arg("--h", "1920")]
    if arg("--mb"):
        cmd += ["--mb", arg("--mb")]
    if "--ssr" in sys.argv:
        cmd.append("--ssr")
    cmd += (arg("--render-args", "") or "").split()
    print("render:", " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, check=True)
    T["render_s"] = round(time.time() - t, 1)
    rt = json.load(open(os.path.join(work, "timings.json"), encoding="utf-8"))
    T["render"] = {k: rt.get(k) for k in ("W", "H", "setup_s", "total_s", "film", "free_ram_gb_at_start", "mb_samples", "shutter", "stat")}
    # 2. encode with bb_v1_encode, unchanged but for its paths ----------------------------------------------------------
    t = time.time()
    import bb_v1_encode as E
    E.FRAMES = os.path.join(work, "frames")
    E.PLAN = plan_path
    E.OUT_DIR = out_dir; E.MAIN = out; E.SHARE = os.path.join(out_dir, name + "_share.mp4")
    E.TEASER = os.path.join(out_dir, "teaser_" + name + ".mp4"); E.TMP = os.path.join(work, "_enc_tmp")
    E.write_credits = three_credits(E, title=title)
    title_patch(E, title)
    if "--music" in sys.argv:
        os.environ["BB_V1_MUSIC"] = "1"
    if "--no-title" in sys.argv:
        os.environ["BB_V1_TITLE"] = "0"
    E.main()
    T["encode_s"] = round(time.time() - t, 1)
    T["total_s"] = round(time.time() - t_all, 1)
    pr = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries", "stream=codec_type,nb_read_packets,width,height:format=duration,size",
                         "-of", "json", out], capture_output=True, text=True)
    T["probe"] = json.loads(pr.stdout)
    if "--keep-frames" not in sys.argv:
        shutil.rmtree(os.path.join(work, "frames"), ignore_errors=True); shutil.rmtree(E.TMP, ignore_errors=True)
    json.dump(T, open(os.path.splitext(out)[0] + ".timings.json", "w"), indent=1)
    print("film %s: render %.0f s + encode %.0f s = %.0f s" % (os.path.relpath(out, ROOT), T["render_s"], T["encode_s"], T["total_s"]))


if __name__ == "__main__":
    main()
