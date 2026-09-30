"""LAB (no-Unreal, research only): Blender 5.1 Cycles lane for HERO STILLS (true GI) of the Business Bay v1 film.

Same glTF / OBJ assets, cameras, sun and look tables as the headless three.js renderer (lab_nounreal_render.py, imported
read-only for its tables and camera maths), rendered with Cycles on the GPU (OptiX, denoised) instead of rasterised - the
question is whether path-traced bounce light closes the ground and shadow gap to Unreal's Lumen frames.

  python scripts/lab_nounreal_blender.py render  [--views t6,t21,t34,t42,street,eye] [--samples 64] [--sun 8 --sky 1.2]
                                                 [--world hdri_nosun|hdri|nishita|ue_skylight] [--hdri-clamp 10] [--hdri-blur 20]
                                                 [--hdri-rot align|native|<deg>]
                                                 [--w 1080 --h 1920] [--tag stills]
  python scripts/lab_nounreal_blender.py develop [--tag stills] [--params cycles/look.json] [--ev ..] [--view AgX ..]
  python scripts/lab_nounreal_blender.py tune    [--tag stills] [--views ..] [--looks "AgX|None;ACES 1.3|None"] [--evs a:b:step]
                                                 [--k-sky 1] [--k-sun 1] [--fog-k 1]      (grid -> dE to Unreal, best -> look.json)
  python scripts/lab_nounreal_blender.py pairs   [--tag stills]    (Unreal | three.js v2 | Cycles sheet + dE + stats)
  python scripts/lab_nounreal_blender.py seq     --film0 36.4 --secs 2 [--fps 25] [--samples 32] [--w 1080 --h 1920]
Views: t<N> = bb_v1 film time N s (film_frames/ Unreal reference, stills_v2/ three.js); street = render time 31.0 s, the
12 m boulevard shot (Unreal reference from bb_v1_9x16_street_heavy.mp4 @ 23.4 s); eye = a 1.7 m eye-level shot on the canal
promenade between cafe clusters 3 and 4 of the plan (no Unreal reference: the film has no eye-level shot).

Shared machine: before every Blender launch (and inside Blender before every frame) it waits while free RAM < --min-ram
(5 GB), while a three.js headless render (python ... lab_nounreal_render.py) runs, and while any blender.exe runs (one
Blender at a time). Never launches Unreal or CityEngine, never signals other processes.
Writes only data/lab/no_unreal/cycles/. Research only - nothing is published.
"""
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True                    # importing the renderer must not drop a .pyc into scripts/
sys.path.insert(0, HERE)
import lab_nounreal_render as R  # noqa: E402  (tables + camera maths only; importing it launches nothing)

ROOT = R.ROOT
LAB = R.OUT
OUT = os.path.join(LAB, "cycles")
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
SCENE_PY = os.path.join(HERE, "lab_nounreal_blender_scene.py")
DEVELOP_PY = os.path.join(HERE, "lab_nounreal_blender_develop.py")
HDRI = "C:/Dev/assets/polyhaven_2k/hdris_dubai/golden_bay_4k.hdr"
FILM = os.path.join(ROOT, "data", "media", "businessbay", "bb_v1_9x16.mp4")
FILM_SH = os.path.join(ROOT, "data", "media", "businessbay", "bb_v1_9x16_street_heavy.mp4")
GRADE = R.GRADE
DEFAULT_LOOK = {"view": "AgX", "look": "None", "ev": 0.0, "k_sun": 1.0, "k_sky": 1.0, "fog_k": 1.0, "gain": [1.12, 1.0, 0.88], "sat": 1.2,
                "bloom": 0.35, "bloom_thr": 6.0, "vignette": 0.35,
                # the three.js v2 dome (sky plate) and its output chain
                "sky": [[0.02, 0.035, 0.045], [0.10, 0.15, 0.17], [0.55, 0.50, 0.36], [0.45, 0.50, 0.52]], "sky_top_e": 0.35,
                "three_gain": [1.12, 1.0, 0.88], "three_sat": 1.2, "three_exposure": 1.9}


def arg(k, d=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + [str(x) for x in a], check=True)


# ------------------------------------------------------------------------------------------------ shared-machine gate
def procs():
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(blender|python|python3|pythonw)\\.exe$' } | "
          "ForEach-Object { \"$($_.ProcessId)|$($_.Name)|$($_.CommandLine)\" }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120).stdout
    rows = []
    for ln in out.splitlines():
        p = ln.split("|", 2)
        if len(p) == 3:
            rows.append((int(p[0]), p[1].lower(), p[2]))
    return rows


def three_render_active(sample_s=4.0):
    """a lab_nounreal_render.py job is ACTIVELY rendering: a headless browser (chrome-headless-shell, or chrome / msedge
    --headless) descends from its python (python -> playwright node driver -> browser) AND is working - its CPU time rises
    over sample_s or the GPU is above 10 %. A python that is merely waiting (for RAM or for blender.exe) never counts."""
    ps = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return False
    rows = {}
    for ln in out.splitlines():
        p = ln.split("|", 3)
        if len(p) == 4 and p[0].isdigit():
            rows[int(p[0])] = (int(p[1]) if p[1].isdigit() else 0, p[2].lower(), p[3])
    three = {pid for pid, r in rows.items() if r[1].startswith("python") and "lab_nounreal_render.py" in r[2]}
    if not three:
        return False
    browsers = []
    for pid, (ppid, name, cmd) in rows.items():
        if "headless" in name or (name in ("chrome.exe", "msedge.exe") and "--headless" in cmd):
            p, hops = ppid, 0
            while p and hops < 8:
                if p in three:
                    browsers.append(pid); break
                p = rows.get(p, (0,))[0]; hops += 1
    if not browsers:
        return False

    def cpu():
        q = "(Get-Process -Id %s -ErrorAction SilentlyContinue | Measure-Object -Property CPU -Sum).Sum" % ",".join(str(b) for b in browsers)
        try:
            return float(subprocess.run(["powershell", "-NoProfile", "-Command", q], capture_output=True, text=True, timeout=60).stdout.strip() or 0)
        except Exception:
            return 0.0
    c0 = cpu(); time.sleep(sample_s); c1 = cpu()
    try:
        gpu = float(subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=30).stdout.split()[0])
    except Exception:
        gpu = 0.0
    return (c1 - c0) > 0.2 or gpu > 10.0


def wait_turn(min_gb, max_wait_s=6 * 3600):
    t0 = time.time()
    while True:
        rows = procs()
        blender = [r for r in rows if r[1] == "blender.exe"]
        three = [1] if three_render_active() else []
        g = R.free_ram_gb()
        if not blender and not three and g >= min_gb:
            print("gate: free RAM %.1f GB, no blender.exe, no three.js headless render: go" % g, flush=True)
            return g
        if time.time() - t0 > max_wait_s:
            raise SystemExit("gate: gave up after %d s" % max_wait_s)
        print("gate: waiting - free RAM %.1f GB (need %.1f), blender.exe running %d, three.js headless render active %d"
              % (g, min_gb, len(blender), len(three)), flush=True)
        time.sleep(30)


def run_blender(script, cfg, tag, min_gb):
    os.makedirs(os.path.join(OUT, "logs"), exist_ok=True)
    cfg_path = os.path.join(OUT, "logs", "%s_cfg.json" % tag)
    json.dump(cfg, open(cfg_path, "w"), indent=1)
    wait_turn(min_gb)
    log_path = os.path.join(OUT, "logs", "%s.log" % tag)
    t = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        p = subprocess.Popen([BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "-P", script, "--", cfg_path],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for ln in p.stdout:
            lf.write(ln)
            if ln.startswith("[cycles]") or ln.startswith("[develop]") or "Error" in ln or "Traceback" in ln:
                print("  " + ln.rstrip(), flush=True)
        rc = p.wait()
    print("blender %s exit %d in %.1f s (log %s)" % (os.path.basename(script), rc, time.time() - t, rel(log_path)), flush=True)
    if rc != 0:
        raise SystemExit("blender failed, see " + log_path)
    return time.time() - t


# ------------------------------------------------------------------------------------------------ cameras
def plan():
    return json.load(open(R.PLAN, encoding="utf-8"))


def fov_v(P):
    return math.degrees(2 * math.atan((42.667 / 2.0) / float(P.get("focal_mm", 20.0))))


def eye_view(P):
    """1.7 m eye level on the canal promenade, between cafe clusters 3 and 4 of the plan, 3 m towards the water, looking
    along the promenade 12 deg towards the canal"""
    c = np.array([r[:2] for r in P["dress"]["prom_cafes"]], float)
    m = (c[3] + c[4]) / 2; t = c[4] - c[3]; t /= np.linalg.norm(t)
    n = np.array([t[1], -t[0]])                                           # water side (UE frame, measured from v1_canal_water.obj)
    a = math.radians(12.0); d = math.cos(a) * t + math.sin(a) * n
    land = float(P["lift_cm"])
    pos = [m[0] + 300 * n[0], m[1] + 300 * n[1], land + 170.0]
    tgt = [pos[0] + 6000 * d[0], pos[1] + 6000 * d[1], land + 70.0]
    return pos, tgt


def views(names):
    P = plan(); out = []
    for nm in names:
        if nm.startswith("t"):
            ft = float(nm[1:]); rt = R.film_to_render_t(P, ft); loc, tgt = R.cam_at(P, rt)
            out.append({"name": "film_t%gs" % ft, "film_t": ft, "render_t": round(rt, 3), "pos": R.ue_to_three(loc), "tgt": R.ue_to_three(tgt),
                        "ue": os.path.join(LAB, "film_frames", "ue_bb_v1_t%gs.png" % ft), "ue_src": (FILM, ft),
                        "three": os.path.join(LAB, "stills_v2", "film_t%gs.png" % ft)})
        elif nm == "street":
            rt = 31.0; loc, tgt = R.cam_at(P, rt)
            out.append({"name": "street_r31s", "render_t": rt, "pos": R.ue_to_three(loc), "tgt": R.ue_to_three(tgt),
                        "ue": os.path.join(OUT, "ref", "ue_street_r31s.png"), "ue_src": (FILM_SH, 23.4),
                        "three": os.path.join(OUT, "three", "street_r31s.png")})
        elif nm == "eye":
            loc, tgt = eye_view(P)
            out.append({"name": "eye_prom", "pos": R.ue_to_three(loc), "tgt": R.ue_to_three(tgt), "ue": None,
                        "three": os.path.join(OUT, "three", "eye_prom.png")})
        else:
            raise SystemExit("unknown view " + nm)
    for v in out:
        v["fov_v"] = fov_v(P)
    return out


def sun_three(P):
    p, y = math.radians(-float(P["district_cfg"].get("sun_elev_deg", 33.0))), math.radians(-22.0)
    fwd = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
    return [-fwd[0], -fwd[2], -fwd[1]]                                  # as lab_nounreal_render.main (UE Rotator(-33, -22))


def hdri_sun_u():
    cache = os.path.join(OUT, "logs", "hdri_sun.json")
    if os.path.exists(cache):
        return json.load(open(cache))["u"]
    import cv2
    im = cv2.imread(HDRI, cv2.IMREAD_UNCHANGED).astype(np.float32)
    s = im[::4, ::4].sum(-1); y, x = np.unravel_index(np.argmax(s), s.shape)   # three.js hdriEnv: brightest texel on a 4-step grid
    u = (x * 4) / im.shape[1]
    os.makedirs(os.path.dirname(cache), exist_ok=True); json.dump({"u": u, "v": (y * 4) / im.shape[0]}, open(cache, "w"))
    return u


def hdri_blurred(sigma_deg):
    """the HDRI convolved with a gaussian of sigma_deg (equirect, wrapped in longitude): a stand-in for the filtered sky
    cubemap Lumen's screen probes fall back to - the HDRI sun becomes a broad warm lobe instead of a second sharp sun"""
    out = os.path.join(OUT, "ref", "golden_bay_blur%g.hdr" % sigma_deg)
    if os.path.exists(out):
        return out
    import cv2
    im = cv2.imread(HDRI, cv2.IMREAD_UNCHANGED).astype(np.float32)
    im = cv2.resize(im, (1024, 512), interpolation=cv2.INTER_AREA)
    s = sigma_deg / (360.0 / 1024); pad = int(3 * s) + 1
    p = np.concatenate([im[:, -pad:], im, im[:, :pad]], axis=1)
    p = np.pad(p, ((pad, pad), (0, 0), (0, 0)), mode="reflect")
    p = cv2.GaussianBlur(p, (0, 0), s)
    os.makedirs(os.path.dirname(out), exist_ok=True); cv2.imwrite(out, p[pad:-pad, pad:-pad])
    return out


def hdri_rotation(sun_bl, mode):
    if mode == "native":
        return 0.0
    if mode not in ("align",):
        return float(mode)
    th_h = math.pi - 2 * math.pi * hdri_sun_u()                       # Cycles equirect: u = (pi - atan2(y, x)) / 2pi
    th_s = math.atan2(sun_bl[1], sun_bl[0])
    return math.degrees(th_h - th_s)                                  # Mapping Z rotation that puts the HDRI sun on ours


# ------------------------------------------------------------------------------------------------ render
def scene_cfg(vs, tag, W, H, samples):
    P = plan(); F = R.facade_tables()
    for k in ("floor", "band", "mull"):
        F.setdefault(k, None)
    lmk = F.pop("lmk")
    s3 = sun_three(P); sun_bl = [s3[0], -s3[2], s3[1]]
    man = json.load(open(os.path.join(R.CTX_DIR, "manifest.json"), encoding="utf-8")); layers = []
    for L in man.get("layers", []):
        f = L.get("file_uncompressed") or L["file"]                  # Blender's glTF importer has no meshopt decoder
        if os.path.exists(os.path.join(R.CTX_DIR, f)):
            layers.append({"layer": L["layer"], "path": os.path.join(R.CTX_DIR, f)})
    pal = json.load(open(os.path.join(R.CTX_DIR, man.get("palette", "context_palette.json")), encoding="utf-8"))["roles"]
    roles = {k: {kk: v.get(kk) for kk in ("roughness", "metallic", "emissive_rgb", "opacity") if kk in v} for k, v in pal.items()}
    rot = hdri_rotation(sun_bl, arg("--hdri-rot", "align"))
    dt = os.path.join(ROOT, "data", "ce", "_glb", "sky_burjkhalifa_v3_0.merged.glb")
    return {"lift": float(P["lift_cm"]) / 100.0, "facade": F, "landmarks": lmk, "lmk": R.landmark_tables(),
            "datasmith": os.path.join(ROOT, "data", "ce", "_datasmith"), "ctx_layers": layers, "ctx_palette": roles,
            "towers": arg("--towers", os.path.join(ROOT, "data", "ce", "_glb", "sky_businessbay_v5_0.glb")),
            "downtown": None if "--no-downtown" in sys.argv else dt,
            "crane": os.path.join(R.KITS_DIR, "tower_crane.glb") if os.path.exists(os.path.join(R.KITS_DIR, "tower_crane.glb")) else None,
            "burj": R.ue_to_three(P["burj_cm"]), "burj_glass": R._lin("#7f96bd"), "burj_band": R._lin("#5f6b80"), "burj_spire": R._lin("#c9c9c8"),
            "sun_bl": sun_bl, "sun_rgb": [1.0, 0.88, 0.74], "sun_strength": float(arg("--sun", 8.0)), "sky_strength": float(arg("--sky", 1.2)),
            "sun_angle_deg": float(arg("--sun-angle", 0.535)),
            "hdri": HDRI, "hdri_rot_deg": rot, "hdri_sat": float(arg("--hdri-sat", 0.3)),
            "world": arg("--world", "hdri_nosun"), "hdri_clamp": float(arg("--hdri-clamp", 10.0)), "aerosol": float(arg("--aerosol", 2.0)),
            "hdri_blur": hdri_blurred(float(arg("--hdri-blur", 20.0))) if arg("--world") == "ue_skylight" else None,
            "sand_dark": [0.60, 0.52, 0.39], "sand_light": [0.74, 0.66, 0.52], "water_rgb": [0.03, 0.25, 0.30],
            "W": W, "H": H, "samples": samples, "denoiser": arg("--denoiser", "OPENIMAGEDENOISE"), "adaptive": float(arg("--adaptive", 0.02)),
            "diffuse_bounces": int(arg("--bounces", 4)), "clamp_indirect": float(arg("--clamp", 10.0)),
            "sensor_h_mm": 42.667, "focal_mm": float(P.get("focal_mm", 20.0)), "fog_near": 6000.0, "fog_far": 45000.0,
            "analysis_passes": "--no-analysis" not in sys.argv, "animated_seed": "--animated-seed" in sys.argv,
            "views": [{"name": v["name"], "pos": v["pos"], "tgt": v["tgt"]} for v in vs],
            "exr_dir": os.path.join(OUT, tag, "exr"), "timings": os.path.join(OUT, tag, "timings.json"),
            "min_ram": float(arg("--min-ram", 5.0)), "min_ram_frame": float(arg("--min-ram-frame", 1.5)), "save_blend": None}


def cmd_render():
    tag = arg("--tag", "stills")
    names = arg("--views", "t6,t21,t34,t42,street,eye").split(",")
    vs = views(names)
    W, H, S = int(arg("--w", 1080)), int(arg("--h", 1920)), int(arg("--samples", 64))
    cfg = scene_cfg(vs, tag, W, H, S)
    os.makedirs(os.path.join(OUT, tag), exist_ok=True)
    json.dump([{k: v[k] for k in v if k != "ue_src"} for v in vs], open(os.path.join(OUT, tag, "views.json"), "w"), indent=1)
    wall = run_blender(SCENE_PY, cfg, "render_" + tag, float(arg("--min-ram", 5.0)))
    tm = json.load(open(cfg["timings"]))
    tm["blender_wall_s"] = round(wall, 1); tm["args"] = sys.argv[1:]
    json.dump(tm, open(cfg["timings"], "w"), indent=1)
    print("build %.1f s; frames: %s" % (tm["build_s"], ", ".join("%s %.1f s" % (f["name"], f["render_s"]) for f in tm["frames"])))


# ------------------------------------------------------------------------------------------------ develop
def look_params(tag):
    P = dict(DEFAULT_LOOK)
    lp = arg("--params", os.path.join(OUT, "look.json"))
    if os.path.exists(lp):
        P.update(json.load(open(lp)).get("params", {}))
    for k in ("ev", "k_sun", "k_sky", "fog_k", "sat", "bloom", "bloom_thr", "vignette"):
        v = arg("--" + k.replace("_", "-"))
        if v is not None and "," not in v and ":" not in v:          # tune passes lists / ranges for the same flags
            P[k] = float(v)
    if arg("--sky-tint"):
        P["sky_tint"] = [float(c) for c in arg("--sky-tint").split("/")]
    if arg("--view"):
        P["view"] = arg("--view")
    if arg("--look"):
        P["look"] = arg("--look")
    return P


def cmd_develop(tag=None, scale=1.0, params=None, names=None, out_dir=None):
    tag = tag or arg("--tag", "stills")
    vs = json.load(open(os.path.join(OUT, tag, "views.json")))
    if names:
        vs = [v for v in vs if v["name"] in names]
    P = params or look_params(tag)
    out_dir = out_dir or os.path.join(OUT, tag, "png")
    jobs = [{"exr": os.path.join(OUT, tag, "exr", v["name"] + ".exr"), "out": os.path.join(out_dir, v["name"] + ".png"), "params": P,
             "cam": {"pos": v["pos"], "tgt": v["tgt"], "fov_v": v["fov_v"]}, "scale": scale} for v in vs
            if os.path.exists(os.path.join(OUT, tag, "exr", v["name"] + ".exr"))]
    run_blender(DEVELOP_PY, {"jobs": jobs}, "develop_" + tag, 0.0)
    json.dump({"params": P}, open(os.path.join(out_dir, "params.json"), "w"), indent=1)
    return [j["out"] for j in jobs]


def cmd_analyze():
    tag = arg("--tag", "stills")
    vs = json.load(open(os.path.join(OUT, tag, "views.json")))
    jobs = [{"exr": os.path.join(OUT, tag, "exr", v["name"] + ".exr"), "out": os.path.join(OUT, tag, "gi_" + v["name"] + ".json"), "analyze": True}
            for v in vs if os.path.exists(os.path.join(OUT, tag, "exr", v["name"] + ".exr"))]
    run_blender(DEVELOP_PY, {"jobs": jobs}, "analyze_" + tag, 0.0)
    rows = [json.load(open(j["out"])) for j in jobs if os.path.exists(j["out"])]
    json.dump(rows, open(os.path.join(OUT, tag, "gi_analysis.json"), "w"), indent=1)
    for r in rows:
        print("%-18s shadow/lit %.3f  sun-bounce share of shadow light %.3f  diffuse-indirect share: shadow %.3f lit %.3f" % (
            r["name"], r["shadow_over_lit"] or -1, r["shadow_bounce_share"] or -1, r["shadow_diffuse_indirect_share"] or -1, r["lit_diffuse_indirect_share"] or -1))


# ------------------------------------------------------------------------------------------------ metric (lab_nounreal_tune.py, same maths)
def load540(p, graded):
    tmp = os.path.join(OUT, "logs", "_m_%d.png" % os.getpid())
    ff("-i", p, "-vf", (GRADE + "," if graded else "") + "scale=540:960", tmp)
    a = np.asarray(Image.open(tmp).convert("RGB")).astype(np.float32); os.remove(tmp); return a


def stats(a, sky=True):
    h = a.shape[0]; out = {}
    if sky:
        out["sky"] = a[: int(h * 0.06)].reshape(-1, 3).mean(0)
    out["ground"] = a[int(h * 0.75):].reshape(-1, 3).mean(0)
    bot = a[h // 2:].reshape(-1, 3); y = bot @ np.array([0.2126, 0.7152, 0.0722])
    out["shadow"] = bot[y <= np.percentile(y, 12)].mean(0); out["lit"] = bot[y >= np.percentile(y, 70)].mean(0)
    out["all"] = a.reshape(-1, 3).mean(0)
    return out


def small(x):
    return np.asarray(Image.fromarray(np.clip(x, 0, 255).astype(np.uint8)).resize((135, 240), Image.BILINEAR)).astype(np.float32)


def de(A, B):
    return float(np.abs(small(A) - small(B)).mean())


def ensure_ue(v):
    if v.get("ue") and not os.path.exists(v["ue"]):
        src, t = v["ue_src"] if v.get("ue_src") else (None, None)
        if v["name"] == "street_r31s":
            src, t = FILM_SH, 23.4
        os.makedirs(os.path.dirname(v["ue"]), exist_ok=True)
        ff("-ss", t, "-i", src, "-frames:v", 1, v["ue"])
    return v.get("ue") if v.get("ue") and os.path.exists(v["ue"]) else None


# ------------------------------------------------------------------------------------------------ tune: develop grid -> grade -> dE
def cmd_tune():
    tag = arg("--tag", "stills")
    vs = [v for v in json.load(open(os.path.join(OUT, tag, "views.json"))) if v.get("ue")]
    want = arg("--views")
    if want:                                                           # names as in views.json (film_t6s, street_r31s ...)
        vs = [v for v in vs if v["name"] in set(want.split(","))]
    for v in vs:
        v["ue_src"] = (FILM, v["film_t"]) if "film_t" in v else (FILM_SH, 23.4)
        ensure_ue(v)
    UE = {v["name"]: load540(v["ue"], False) for v in vs}
    looks = [tuple(x.split("|")) for x in arg("--looks", "AgX|None").split(";")]
    a, b, st = [float(x) for x in arg("--evs", "-4:0:0.5").split(":")]
    evs = [round(a + i * st, 3) for i in range(int(round((b - a) / st)) + 1)]
    ksky = [float(x) for x in arg("--k-sky", "1").split(",")]; ksun = [float(x) for x in arg("--k-sun", "1").split(",")]
    fogk = [float(x) for x in arg("--fog-k", "1").split(",")]
    tints = [[float(c) for c in t.split("/")] for t in arg("--sky-tints", "1/1/1").split(",")]
    base = look_params(tag)
    grid = []
    for vw, lk in looks:
        for ev in evs:
            for ks in ksun:
                for kk in ksky:
                    for fk in fogk:
                        for tn in tints:
                            P = dict(base); P.update({"view": vw, "look": lk, "ev": ev, "k_sun": ks, "k_sky": kk, "fog_k": fk, "sky_tint": tn, "bloom": 0.0})
                            grid.append(P)
    d = os.path.join(OUT, tag, "tune")
    reuse = "--reuse" in sys.argv and os.path.isdir(os.path.join(d, "raw"))    # re-score the last develop grid (same arguments)
    if not reuse:
        shutil.rmtree(d, ignore_errors=True); os.makedirs(os.path.join(d, "raw"))
    shutil.rmtree(os.path.join(d, "graded"), ignore_errors=True); os.makedirs(os.path.join(d, "graded"))
    jobs, index = [], []
    for v in vs:                                                       # grouped by EXR: the develop step caches one EXR at a time
        for gi, P in enumerate(grid):
            n = len(jobs)
            jobs.append({"exr": os.path.join(OUT, tag, "exr", v["name"] + ".exr"), "out": os.path.join(d, "raw", "%05d.png" % n), "params": P,
                         "cam": {"pos": v["pos"], "tgt": v["tgt"], "fov_v": v["fov_v"]}, "scale": 0.5})
            index.append((v["name"], gi))
    print("tune: %d looks x %d views = %d develops" % (len(grid), len(vs), len(jobs)), flush=True)
    if not reuse:
        run_blender(DEVELOP_PY, {"jobs": jobs}, "tune_" + tag, 0.0)
    ff("-start_number", 0, "-i", os.path.join(d, "raw", "%05d.png"), "-vf", GRADE, "-start_number", 0, os.path.join(d, "graded", "%05d.png"))
    res = {}
    for n, (name, gi) in enumerate(index):
        B = np.asarray(Image.open(os.path.join(d, "graded", "%05d.png" % n)).convert("RGB")).astype(np.float32)
        res.setdefault(gi, {})[name] = de(UE[name], B)
    rows = []
    for gi, r in res.items():
        P = grid[gi]; film = [r[k] for k in r if k.startswith("film_")]
        rows.append({"mean_film": float(np.mean(film)) if film else None, "per": {k: round(x, 2) for k, x in r.items()},
                     "view": P["view"], "look": P["look"], "ev": P["ev"], "k_sun": P["k_sun"], "k_sky": P["k_sky"], "fog_k": P["fog_k"], "sky_tint": P["sky_tint"]})
    rows.sort(key=lambda x: x["mean_film"] if x["mean_film"] is not None else np.mean(list(x["per"].values())))
    json.dump(rows, open(os.path.join(d, "tune_results.json"), "w"), indent=1)
    for x in rows[:12]:
        print("dE film mean %.2f  %s  %-12s ev %+.2f k_sun %.2f k_sky %.2f tint %s fog %.2f  per %s" % (
            x["mean_film"] or -1, x["view"], x["look"], x["ev"], x["k_sun"], x["k_sky"], x["sky_tint"], x["fog_k"], x["per"]))
    best = rows[0]; P = dict(base); P.update({k: best[k] for k in ("view", "look", "ev", "k_sun", "k_sky", "fog_k", "sky_tint")})
    if "--save" in sys.argv:
        json.dump({"params": P, "tuned_on": tag, "dE": best}, open(os.path.join(OUT, "look.json"), "w"), indent=1)
        print("saved look.json")
    shutil.rmtree(os.path.join(d, "graded"), ignore_errors=True)            # raw kept for --reuse; the next grid replaces it


# ------------------------------------------------------------------------------------------------ pairs sheet
def cmd_pairs():
    tag = arg("--tag", "stills")
    vs = json.load(open(os.path.join(OUT, tag, "views.json")))
    tm = json.load(open(os.path.join(OUT, tag, "timings.json")))
    ft = {f["name"]: f for f in tm["frames"]}
    t3 = {f["name"]: f for f in json.load(open(os.path.join(LAB, "stills_v2", "timings.json"))).get("frames", [])} if os.path.exists(os.path.join(LAB, "stills_v2", "timings.json")) else {}
    pngs = os.path.join(OUT, tag, "png")
    params = json.load(open(os.path.join(pngs, "params.json")))["params"]
    out = os.path.join(OUT, tag, "pairs"); os.makedirs(out, exist_ok=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30); sm = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    except OSError:
        font = sm = ImageFont.load_default()
    rows, tiles = [], []
    for v in vs:
        v["ue_src"] = (FILM, v["film_t"]) if "film_t" in v else ((FILM_SH, 23.4) if v["name"] == "street_r31s" else None)
        ue = ensure_ue(v) if v.get("ue") else None
        cyc = os.path.join(pngs, v["name"] + ".png")
        if not os.path.exists(cyc):
            continue
        cols = []
        if ue:
            cols.append(("UNREAL 5.8 (MRQ, Lumen)", Image.open(ue).convert("RGB"), None, ue, False))
        if v.get("three") and os.path.exists(v["three"]):
            g = os.path.join(out, "three_%s_graded.png" % v["name"]); ff("-i", v["three"], "-vf", GRADE + ",scale=1080:1920", g)
            ms = t3.get(v["name"], {}).get("render_ms")
            cols.append(("three.js v2 (headless WebGL)", Image.open(g).convert("RGB"), "render %s ms" % (ms if ms is not None else "?"), v["three"], True))
        g = os.path.join(out, "cycles_%s_graded.png" % v["name"]); ff("-i", cyc, "-vf", GRADE + ",scale=1080:1920", g)
        f = ft.get(v["name"], {})
        cols.append(("Blender Cycles (OptiX, %d spp, denoised)" % tm["samples"], Image.open(g).convert("RGB"),
                     "render %.1f s" % f.get("render_s", float("nan")), cyc, True))
        row = {"name": v["name"], "cycles_render_s": f.get("render_s")}
        A = load540(ue, False) if ue else None
        sa = stats(A, v["name"] != "film_t21s") if A is not None else None
        if sa:
            row["ue"] = {k: [round(float(x)) for x in val] for k, val in sa.items()}
        labels = []
        for label, im, info, src, graded in cols:
            if src == ue:
                labels.append((label, "bb_v1 film frame (graded by bb_v1_encode)")); continue
            B = load540(src, True); sb = stats(B, v["name"] != "film_t21s")
            key = "three" if label.startswith("three") else "cycles"
            row[key] = {k: [round(float(x)) for x in val] for k, val in sb.items()}
            if A is not None:
                row[key + "_dE"] = round(de(A, B), 2)
                row[key + "_delta"] = {k: [round(float(x)) for x in (sb[k] - sa[k])] for k in sa}
                labels.append((label, "dE %.1f vs Unreal | %s | same ffmpeg grade" % (row[key + "_dE"], info)))
            else:
                labels.append((label, "%s | same ffmpeg grade (no Unreal frame for this camera)" % info))
        W, H = cols[0][1].size
        pair = Image.new("RGB", (len(cols) * W + (len(cols) - 1) * 12, H + 110), (14, 17, 22)); dr = ImageDraw.Draw(pair)
        for i, ((label, im, info, src, graded), (l1, l2)) in enumerate(zip(cols, labels)):
            x = i * (W + 12); pair.paste(im.resize((W, H)), (x, 110))
            dr.text((x + 16, 12), l1, fill=(232, 228, 216), font=font); dr.text((x + 16, 58), l2, fill=(160, 170, 165), font=sm)
        p = os.path.join(out, "pair_%s.png" % v["name"]); pair.save(p); rows.append(row)
        tiles.append(pair.resize((pair.width // 3, pair.height // 3), Image.LANCZOS))
        print("wrote %s  %s" % (rel(p), {k: row[k] for k in row if k.endswith("_dE")}), flush=True)
    tw = max(t.width for t in tiles); th = max(t.height for t in tiles); ncol = 2
    sheet = Image.new("RGB", (tw * ncol, th * ((len(tiles) + ncol - 1) // ncol)), (14, 17, 22))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % ncol) * tw, (i // ncol) * th))
    sheet.save(os.path.join(out, "pairs_sheet.jpg"), quality=90)
    film = [r for r in rows if r["name"].startswith("film_") and "cycles_dE" in r]
    summary = {"rows": rows, "look": params, "timings": {"build_s": tm["build_s"], "frames": tm["frames"], "samples": tm["samples"],
               "sun_strength": tm.get("sun_strength"), "sky_strength": tm.get("sky_strength")},
               "mean_dE_film": {"three": round(float(np.mean([r["three_dE"] for r in film if "three_dE" in r])), 2) if film else None,
                                "cycles": round(float(np.mean([r["cycles_dE"] for r in film])), 2) if film else None}}
    json.dump(summary, open(os.path.join(out, "dE.json"), "w"), indent=1)
    print("mean dE over the film stills: three.js v2 %s, Cycles %s -> %s" % (summary["mean_dE_film"]["three"], summary["mean_dE_film"]["cycles"], rel(os.path.join(out, "pairs_sheet.jpg"))))


# ------------------------------------------------------------------------------------------------ short sequence
def cmd_seq():
    P = plan(); fps = int(arg("--fps", 25)); f0, secs = float(arg("--film0", 36.4)), float(arg("--secs", 2.0))
    tag = arg("--tag", "seq_%gs" % secs)
    n = int(round(secs * fps)); vs = []
    for i in range(n):
        ft = f0 + i / float(fps); rt = R.film_to_render_t(P, ft); loc, tgt = R.cam_at(P, rt)
        vs.append({"name": "f%04d" % i, "film_t": round(ft, 3), "render_t": round(rt, 3), "pos": R.ue_to_three(loc), "tgt": R.ue_to_three(tgt), "fov_v": fov_v(P)})
    W, H, S = int(arg("--w", 1080)), int(arg("--h", 1920)), int(arg("--samples", 32))
    cfg = scene_cfg(vs, tag, W, H, S)
    os.makedirs(os.path.join(OUT, tag), exist_ok=True)
    json.dump(vs, open(os.path.join(OUT, tag, "views.json"), "w"), indent=1)
    wall = run_blender(SCENE_PY, cfg, "render_" + tag, float(arg("--min-ram", 5.0)))
    t = time.time(); cmd_develop(tag=tag); dev_s = time.time() - t
    mp4 = os.path.join(OUT, tag, "cycles_%s_graded.mp4" % tag)
    ff("-framerate", fps, "-i", os.path.join(OUT, tag, "png", "f%04d.png"), "-vf", GRADE + ",format=yuv420p", "-c:v", "libx264", "-crf", "16", mp4)
    tm = json.load(open(cfg["timings"])); r = [f["render_s"] for f in tm["frames"]]
    tm.update({"blender_wall_s": round(wall, 1), "develop_s": round(dev_s, 1), "frames_n": n, "render_s_mean": round(float(np.mean(r)), 2),
               "render_s_median": round(float(np.median(r)), 2), "render_s_total": round(float(np.sum(r)), 1)})
    # temporal stability: mean |frame(i) - frame(i-1)| on the graded frames (camera motion + denoiser flicker)
    fr = [np.asarray(Image.open(p).convert("L").resize((270, 480))).astype(np.float32) for p in sorted(glob.glob(os.path.join(OUT, tag, "png", "f*.png")))]
    tm["mean_abs_frame_delta"] = round(float(np.mean([np.abs(a - b).mean() for a, b in zip(fr[1:], fr)])), 2) if len(fr) > 1 else None
    json.dump(tm, open(cfg["timings"], "w"), indent=1)
    print("seq %d frames: build %.1f s, render %.1f s total (%.1f s/frame median), develop %.1f s -> %s"
          % (n, tm["build_s"], tm["render_s_total"], tm["render_s_median"], dev_s, rel(mp4)))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    {"render": cmd_render, "develop": cmd_develop, "tune": cmd_tune, "pairs": cmd_pairs, "seq": cmd_seq, "analyze": cmd_analyze}[sys.argv[1]]()
