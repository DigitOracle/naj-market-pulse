"""LAB (no-Unreal, research only) v2: render the Business Bay v1 film WITHOUT Unreal - headless three.js r169 in
Playwright/Chromium on the local GPU (ANGLE D3D11, NVIDIA forced). v1 (first side-by-side) is lab_nounreal_render_v1.py.

v2 closes the renderer gaps found by v1:
  SPEED     frames are encoded INSIDE the page (WebCodecs VideoEncoder, hardware H.264, mp4-muxer) and streamed to disk
            in chunks - no screenshots; the 8k sun shadow map is cached (re-fitted only when the view leaves it, texel-
            snapped in light space); static meshes are merged per material (thousands of draw calls -> ~100).
  LIGHTING  warm sand bounce (hemisphere fill, ground-coloured IBL lower hemisphere), blue-grey sky top, exposure / IBL /
            GTAO tuned against the Unreal frames (lab_nounreal_tune.py).
  FACADES   Unreal's M_DA_Facade as a three.js shader (onBeforeCompile): floor band every FloorH, mullion every PaneW,
            roof mask, ground-floor shopfront layer, world-position based with fwidth anti-aliasing; applied by material
            role exactly as ue_bb_v1_build.apply_pbr_v1 / facade_mis (facade_palette_v1.json looks, landmarks_v2.json glass,
            the seeded 16-look fallback). A v6 GLB with real facade geometry (material names '<look>_<role>' with
            slab_band / mullion / fin) switches the shader off and keeps the GLB's own PBR values.
  LANDMARKS bb_landmark_crowns.py: HEIGHT_FIX, CONSTRUCTION (partial height + construction frame + tower crane on top),
            CROWNS (crown_*.obj on the roof), as ue_bb_v1_build.landmarks().
  DRESSING  data/lab/context/businessbay/{ground,dressing}_businessbay_v5.glb (scenery agent) when present - they
            replace the bb_v1 district ground OBJs; plus the bb_v1 plan's promenade cafe clusters (Poly Haven glTF) and
            tower cranes (converted to data/lab/no_unreal/kits/ by lab_nounreal_kits.py) when present.
Inputs are read-only; frames: UE cm (X = E - 328289, Y = 2784598 - N, Z up) -> three m (x = X/100 + 2358, y = Z/100,
z = Y/100 + 1804) in the Business Bay v5 local frame (origin_v5.json).

  python scripts/lab_nounreal_render.py stills [--w 1080 --h 1920] [--film 6,21,34,42] [--out stills_v2]
  python scripts/lab_nounreal_render.py seq  --film0 36.4 --secs 5 --fps 25 --w 720 --h 1280 [--tag wide]
  python scripts/lab_nounreal_render.py film [--w 1080 --h 1920] [--fps 25]      (whole bb_v1 camera path, 0-121 s)
  python scripts/lab_nounreal_render.py frames --indices edit|<i,j,..> --out <dir> (MRQ-style bb_v1.<frame>.jpeg; see lab_nounreal_film.py)
  python scripts/lab_nounreal_render.py stills --views <views.json>              (custom cameras; see lab_nounreal_close.py)
Common: --no-downtown --downtown-lod v3|v5 (v3 = LOD1 backdrop, the memory-safe default on the shared machine)
        --no-ctx --with-json (show the scenery's non-film 'json' objects) --no-facade --no-ao --no-merge --no-kits
        --towers <glb> --glass-env bpcem|bb-sky|sky|probe --no-ssr --probe-water --mb N --shutter 0.3 --cafe-kits --no-storefronts
        --split-ibl --diff 0.3 --no-hdri --hdri-clamp 8 --bitrate 16e6 --grade --plan <plan.json> --min-ram 5 (GB; also waits while blender.exe renders)
Writes data/lab/no_unreal/<out>/ (+ timings.json). Never touches Unreal or CityEngine.
"""
import ast
import base64
import glob
import json
import math
import os
import random
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "no_unreal")
PLAN = os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v1", "bb_v1_plan.json")
PALETTE = os.path.join(ROOT, "data", "ce", "businessbay", "facade_palette_v1.json")
LANDMARKS = os.path.join(ROOT, "data", "ce", "businessbay", "landmarks", "landmarks_v2.json")
CTX_DIR = os.path.join(ROOT, "data", "lab", "context", "businessbay")
KITS_DIR = os.path.join(OUT, "kits")
BB_ORIGIN = (325931.0, 2786402.0)                 # origin_v5.json businessbay (E, N)
DT_ORIGIN = (326414.0, 2787548.0)                 # origin_v5.json burjkhalifa
UE_E0, UE_N0 = 328289.0, 2784598.0                # bb_v1_prep frame
GRADE = "eq=contrast=1.12:saturation=1.35:gamma=0.92,colorbalance=rs=0.04:gs=0.01:bs=-0.03:rm=0.02:bm=-0.02:bh=0.04"


def arg(k, d=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


def ue_to_three(p):
    return [p[0] / 100.0 + (UE_E0 - BB_ORIGIN[0]), (p[2] if len(p) > 2 else 0.0) / 100.0, p[1] / 100.0 + (BB_ORIGIN[1] - UE_N0)]


def _gz_m():
    try:
        return float(json.load(open(os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v1", "used_assets.json"), encoding="utf-8")).get("gz_cm", 0.0)) / 100.0
    except Exception:
        return 0.0


GZ_M = _gz_m()
SLUG = "businessbay"


def set_district(slug, plan=None):
    """point every per-district path at data/ce/<slug> (+ data/lab/context/<slug>); the local frame is origin_v5.json"""
    global SLUG, BB_ORIGIN, PALETTE, LANDMARKS, CTX_DIR, GZ_M
    SLUG = slug
    o = json.load(open(os.path.join(ROOT, "data", "ce", slug, "origin_v5.json"), encoding="utf-8"))["origin_utm_en"]
    BB_ORIGIN = (float(o[0]), float(o[1]))
    PALETTE = os.path.join(ROOT, "data", "ce", slug, "facade_palette_v1.json")
    LANDMARKS = os.path.join(ROOT, "data", "ce", slug, "landmarks", "landmarks_v2.json")
    CTX_DIR = os.path.join(ROOT, "data", "lab", "context", slug)
    if plan is not None and "gz_cm" in plan:
        GZ_M = float(plan["gz_cm"]) / 100.0
    else:
        GZ_M = _gz_m() if slug == "businessbay" else 0.0


def ground_layers(slug, out_json):
    """no scenery manifest: the district's own flat ground from data/ce/<slug>/context_ue.json (ue_context_layer.py, city UE
    frame: water / sand / grass / parking / pavement / asphalt / pool, rgb as Unreal) + Overture water (water.json), as
    three.js-ready arrays in the district's local frame"""
    import mapbox_earcut as earcut
    import numpy as np
    out = {"slug": slug, "layers": []}
    cp = os.path.join(ROOT, "data", "ce", slug, "context_ue.json")
    if os.path.exists(cp):
        for L in json.load(open(cp, encoding="utf-8")).get("layers", []):
            V, T = L.get("verts", []), L.get("tris", [])
            if not T:
                continue
            pos = []
            for k in range(0, len(V), 3):
                q = ue_to_three([V[k], V[k + 1], V[k + 2]]); pos += [round(q[0], 2), round(q[1], 3), round(q[2], 2)]
            idx = []
            for k in range(0, len(T), 3):
                idx += [T[k], T[k + 2], T[k + 1]]
            out["layers"].append({"name": L["name"], "rgb": L.get("rgb", [0.5, 0.5, 0.5]), "rough": L.get("roughness", 0.9),
                                  "water": L["name"] in ("water", "pool"), "pos": pos, "idx": idx})
    wp = os.path.join(ROOT, "data", "ce", slug, "water.json")
    if os.path.exists(wp) and not any(L["name"] == "water" for L in out["layers"]):   # Overture rings carry no holes: only when OSM water is missing
        pos, idx = [], []
        for ring in json.load(open(wp, encoding="utf-8")).get("polys", []):
            pts = np.array([[x - BB_ORIGIN[0], z + BB_ORIGIN[1]] for x, z in ring], dtype=np.float64)
            if len(pts) < 3:
                continue
            tri = earcut.triangulate_float64(pts, np.array([len(pts)], dtype=np.uint32))
            base = len(pos) // 3
            for x, z in pts:
                pos += [round(float(x), 2), 0.005, round(float(z), 2)]
            for k in range(0, len(tri), 3):
                idx += [base + int(tri[k]), base + int(tri[k + 2]), base + int(tri[k + 1])]
        out["layers"].insert(0, {"name": "water_overture", "rgb": [0.02, 0.16, 0.22], "rough": 0.07, "water": True, "pos": pos, "idx": idx})
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    json.dump(out, open(out_json, "w"), separators=(",", ":"))
    return {L["name"]: len(L["idx"]) // 3 for L in out["layers"]}


def cam3(p):
    """a UE camera / target point (cm, absolute Z incl. the Datasmith ground offset gz) -> three m in our frame (land = lift)"""
    q = ue_to_three(p); q[1] -= GZ_M; return q


def film_to_render_t(plan, ft):
    bar, t = float(plan["bar_s"]), 0.0
    for t0, bars in plan["edit"]:
        d = bars * bar
        if ft < t + d:
            return t0 + (ft - t)
        t += d
    raise ValueError("film time %.2f is on the end card" % ft)


def edit_frames(plan, fps):
    """the frame indices bb_v1_encode.py reads: frame 0 (its 'first'), every EDIT window and the TEASER windows"""
    bar, keep = float(plan.get("bar_s", 2.14)), {0}
    for t0, bars in plan["edit"]:
        a = int(round(t0 * fps)); keep.update(range(a, a + int(round(bars * bar * fps)) + 1))      # +1: ffmpeg's image2 probes one past the window
    for a, b in plan.get("teaser", []):
        s = int(round(a * fps)); keep.update(range(s, s + int(round((b - a) * fps)) + 1))
    n = int(round(float(plan["total_s"]) * fps))
    return sorted(i for i in keep if i < n)


def add_subs(plan, views, fps, n, shutter):
    """motion blur + TAA: n sub-samples per frame spread over `shutter` of the frame interval, each with a Halton sub-pixel jitter"""
    hal = lambda i, b: sum(((i // b ** k) % b) / float(b ** (k + 1)) for k in range(8))
    for v in views:
        rt = v.get("render_t")
        if rt is None:
            continue
        subs = []
        for k in range(n):
            dt = ((k + 0.5) / n - 0.5) * shutter / float(fps)
            loc, tgt = cam_at(plan, max(0.0, rt + dt))
            subs.append({"pos": cam3(loc), "tgt": cam3(tgt), "jx": hal(k + 1, 2) - 0.5, "jy": hal(k + 1, 3) - 0.5})
        v["subs"] = subs


def cam_at(plan, rt):
    ks = plan["keys"]
    for a, b in zip(ks, ks[1:]):
        if a[0] <= rt <= b[0]:
            f = (rt - a[0]) / (b[0] - a[0])
            lerp = lambda u, v: [u[i] + (v[i] - u[i]) * f for i in range(3)]
            return lerp(a[1], b[1]), lerp(a[2], b[2])
    return ks[-1][1], ks[-1][2]


def _literal(src, name):
    """a dict / list literal assigned at module level in a UE script (parsed, never imported - they import unreal)"""
    tree = ast.parse(open(src, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _lin(h):                                      # ue_bb_v1_build._lin: hex -> linear by ^2.2
    h = h.lstrip("#"); return [round((int(h[i:i + 2], 16) / 255.0) ** 2.2, 4) for i in (0, 2, 4)]


def facade_tables(max_idx=2000):
    """everything ue_bb_v1_build.apply_pbr_v1 / facade_mis / landmark_facade decide per building, as plain tables"""
    P = dict(_literal(os.path.join(HERE, "ue_sobha_pbr.py"), "PALETTE"))
    P.update(_literal(os.path.join(HERE, "ue_bb_v1_build.py"), "EXTRA"))
    looks16 = _literal(os.path.join(HERE, "ue_bb_v1_build.py"), "LOOKS")
    J = json.load(open(PALETTE, encoding="utf-8")) if os.path.exists(PALETTE) else {}
    warm = lambda c: [min(1.0, c[0] * 1.05), c[1] * 1.01, c[2] * 0.92]
    looks = {}
    for name, L in (J.get("palette") or {}).items():
        refl = float(L.get("reflectivity", 0.3)); rough = float(L.get("roughness", 0.5))
        base, sec = warm(_lin(L.get("base_hex", "#CCCCCC"))), warm(_lin(L.get("secondary_hex", L.get("base_hex", "#CCCCCC"))))
        bk, sk = "fp_%s_base" % name, "fp_%s_sec" % name
        if refl >= 0.4:
            P[bk] = (base, max(0.04, rough), min(0.8, refl + 0.1), 1.0); P[sk] = (sec, 0.75, 0.0, 0.4)
            looks[name] = {"vision": bk, "walls": sk, "slabs": sk, "fins": sk}
        else:
            P[bk] = (base, max(0.4, rough), 0.0, 0.4); P[sk] = (sec, 0.08, 0.5, 1.0)
            looks[name] = {"walls": bk, "slabs": bk, "vision": sk, "fins": sk}
    assign = {}
    for i, a in (J.get("assignments") or {}).items():
        if a.get("look") in looks:
            assign[int(i)] = looks[a["look"]]
    for lm in (J.get("landmarks") or {}).values():
        if lm.get("look") in looks:
            for i in lm.get("feature_ids", []):
                assign[int(i)] = looks[lm["look"]]
    per = {}
    for i in range(max_idx):
        if i in assign:
            lk = assign[i]; per[i] = [lk["walls"], lk["vision"], lk["slabs"], lk["fins"]]
        else:
            per[i] = list(looks16[random.Random("bb_v1_%s" % i).randrange(len(looks16))])
    lmk = {}
    for e in (json.load(open(LANDMARKS, encoding="utf-8")).get("landmarks", {}).values() if os.path.exists(LANDMARKS) else []):
        f = e.get("facade") or {}
        if not f.get("base_hex"):
            continue
        r = {"glass": _lin(f["base_hex"]), "frame": _lin(f.get("frame_hex") or f["base_hex"]),
             "span": _lin(f.get("spandrel_hex") or f["base_hex"]), "floor": float(f.get("floor_m") or 3.4),
             "pane": float(f.get("pane_m") or 1.5), "name": e.get("name", "")}
        for i in e.get("ids", []):
            lmk[int(i)] = r
    pal = {k: [list(v[0]), float(v[1]), float(v[2])] for k, v in P.items()}
    return {"pal": pal, "per": per, "lmk": lmk}


def landmark_tables():
    if SLUG != "businessbay":                                    # bb_landmark_crowns.py is Business Bay's research
        return {"height": {}, "construction": {}, "crowns": {}}
    src = os.path.join(HERE, "bb_landmark_crowns.py")
    return {"height": {int(k): float(v) for k, v in _literal(src, "HEIGHT_FIX").items()},
            "construction": {int(k): list(v) for k, v in _literal(src, "CONSTRUCTION").items()},
            "crowns": {int(k): list(v) for k, v in _literal(src, "CROWNS").items()}}


def free_ram_gb():
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS(); m.dwLength = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 1024.0 ** 3


def _blender_cpu_s():
    import subprocess
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process blender -ErrorAction SilentlyContinue | Measure-Object CPU -Sum).Sum"],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out) if out else None
    except Exception:
        return None


def _gpu_util():
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30).stdout
        return max(float(x) for x in out.split()) if out.strip() else 0.0
    except Exception:
        return 0.0


def blender_running():
    """True only while blender.exe is actively rendering (its CPU time rising, or the GPU busy) - an idle blender.exe that
    is itself waiting for this renderer must not block it (that deadlocked on 30 Sep)"""
    c0 = _blender_cpu_s()
    if c0 is None:
        return False
    time.sleep(5)
    c1 = _blender_cpu_s()
    return (c1 is not None and c1 - c0 > 0.5) or _gpu_util() > 10.0


def wait_for_ram(min_gb, max_wait_s=3600):
    """shared machine (CityEngine batch, a Blender Cycles agent, other agents): never start Chromium while free RAM is
    under min_gb or while blender.exe is running (the Blender agent waits for Chromium the same way)"""
    t0 = time.time()
    while True:
        g = free_ram_gb(); bl = blender_running()
        if g >= min_gb and not bl:
            print("free RAM %.1f GB (>= %.1f), no blender.exe: go" % (g, min_gb), flush=True); return g
        if bl:
            print("blender.exe is running - waiting", flush=True); time.sleep(30)
            if time.time() - t0 > max_wait_s:
                raise SystemExit("blender.exe still running after %d s - not starting Chromium" % max_wait_s)
            continue
        if time.time() - t0 > max_wait_s:
            raise SystemExit("free RAM stayed under %.1f GB for %d s - not starting Chromium" % (min_gb, max_wait_s))
        print("free RAM %.1f GB < %.1f GB - waiting" % (g, min_gb), flush=True); time.sleep(30)


def storefront_boxes(plan):
    """ue_bb_v1_build.storefronts(): per bay a glazed shopfront box, a sign band coloured by kind, an awning + valance on
    awning bays (canvas, 24 deg fall); bistro tables / chairs / umbrellas. UE cm boxes -> three m instances
    [cx, cy, cz, sx (along the facade), sy (height), sz (outwards), yaw_rad, tilt_rad]"""
    src = os.path.join(ROOT, "data", "ce", SLUG, "storefronts_ue.json")
    if not os.path.exists(src):
        return None
    S = json.load(open(src, encoding="utf-8"))
    SIGN = _literal(os.path.join(HERE, "ue_bb_v1_build.py"), "SIGN_RGB"); AWN = _literal(os.path.join(HERE, "ue_bb_v1_build.py"), "AWNING_RGB")
    land = GZ_M * 100.0 + float(plan["lift_cm"])
    groups = {}

    def box(key, x, y, yaw, sx, sy, sz, z, lx=0.0, ly=0.0, pitch=0.0):
        r = math.radians(yaw)
        wx = x + lx * math.cos(r) - ly * math.sin(r); wy = y + lx * math.sin(r) + ly * math.cos(r)
        c = cam3([wx, wy, z])
        groups.setdefault(key, []).append([round(c[0], 3), round(c[1], 3), round(c[2], 3), sx / 100.0, sz / 100.0, sy / 100.0, -r, math.radians(-pitch)])
    aw = {(round(a[0]), round(a[1])) for a in S.get("awnings", [])}
    for i, (x, y, yaw, w, kind) in enumerate(S.get("bays", [])):
        box("glass", x, y, yaw, w - 20.0, 30.0, 420.0, land + 210.0, ly=15.0)
        box("sign_" + (kind if kind in SIGN else "other"), x, y, yaw, w, 40.0, 80.0, land + 470.0, ly=25.0)
        if (round(x), round(y)) in aw:
            box("awning_%d" % (i % 4), x, y, yaw, w - 40.0, 190.0, 18.0, land + 360.0, ly=100.0, pitch=-24.0)
            box("awning_%d" % (i % 4), x, y, yaw, w - 40.0, 6.0, 38.0, land + 300.0, ly=188.0)
    colours = {"sign_other": [0.08, 0.08, 0.085]}
    colours.update({"sign_" + k: list(v) for k, v in SIGN.items()}); colours.update({"awning_%d" % i: list(c) for i, c in enumerate(AWN)})
    pt = lambda q: cam3([q[0], q[1], land])
    return {"groups": groups, "colours": colours,
            "tables": [[pt(t)[0], pt(t)[2], 0.0] for t in S.get("tables", [])],
            "chairs": [[pt(c)[0], pt(c)[2], float(c[2]) + 180.0] for c in S.get("chairs", [])],
            "umbrellas": [[pt(u)[0], pt(u)[2], 0.0] for u in S.get("umbrellas", [])]}


class _RO(SimpleHTTPRequestHandler):
    """read-only static server for the page's fetches (GET/HEAD only, no listing), bound to 127.0.0.1"""
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*"); super().end_headers()

    def list_directory(self, path):
        self.send_error(404); return None

    def log_message(self, *a):
        pass


def serve_root():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_RO, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#000}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/",
"mp4-muxer":"https://cdn.jsdelivr.net/npm/mp4-muxer@5.2.1/build/mp4-muxer.mjs"}}</script></head><body>
<script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {Sky} from 'three/addons/objects/Sky.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {GTAOPass} from 'three/addons/postprocessing/GTAOPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';
import {Muxer, StreamTarget} from 'mp4-muxer';
import {RGBELoader} from 'three/addons/loaders/RGBELoader.js';
import {MeshoptDecoder} from 'three/addons/libs/meshopt_decoder.module.js';
import {FullScreenQuad} from 'three/addons/postprocessing/Pass.js';
import {SSRPass} from 'three/addons/postprocessing/SSRPass.js';
import {LightProbeGenerator} from 'three/addons/lights/LightProbeGenerator.js';
const C = window.CFG, W = C.W, H = C.H, T0 = performance.now();
if (C.splitIbl) THREE.ShaderChunk.envmap_physical_pars_fragment = THREE.ShaderChunk.envmap_physical_pars_fragment.replace(
  'return PI * envMapColor.rgb * envMapIntensity;', 'return vec3( 0.0 ); // split IBL: diffuse comes from the SH LightProbe');
window.__log = [];
const log = m => { window.__log.push(((performance.now()-T0)/1000).toFixed(1)+'s '+m); };
const r = new THREE.WebGLRenderer({antialias:false, preserveDrawingBuffer:true, powerPreference:'high-performance'});
r.setPixelRatio(1); r.setSize(W, H); document.body.appendChild(r.domElement);
r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = C.exposure;
r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap; r.shadowMap.autoUpdate = false;
const gl = r.getContext();
{ const e = gl.getExtension('WEBGL_debug_renderer_info'); log('GL ' + (e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : '?')); }
const scene = new THREE.Scene();
const lin = a => new THREE.Color().setRGB(a[0], a[1], a[2]);            // linear values straight in (working space = linear)
const hexLin = h => new THREE.Color(h);
const STAT = {drawGroups: 0, mergedFrom: 0, tris: 0};

// ---------------------------------------------------------------- sky, sun, IBL, bounce
const sunDir = new THREE.Vector3(...C.sun).normalize();
const sky = new Sky(); sky.scale.setScalar(80000);
const su = sky.material.uniforms;
su.mieCoefficient.value = 0.008; su.mieDirectionalG.value = 0.8; su.sunPosition.value.copy(sunDir);
function envFrom(turb, rayleigh, ground) {        // Preetham sky over a flat lower hemisphere (UE sky light: lower_hemisphere_is_black = False)
  su.turbidity.value = turb; su.rayleigh.value = rayleigh;
  const pm = new THREE.PMREMGenerator(r); const ss = new THREE.Scene(); ss.add(sky.clone());
  const gd = new THREE.Mesh(new THREE.CircleGeometry(300000, 32), new THREE.MeshBasicMaterial({color: lin(ground), side: THREE.DoubleSide}));
  gd.rotation.x = -Math.PI/2; gd.position.y = -50; ss.add(gd);
  const t = pm.fromScene(ss, 0, 1, 400000).texture; pm.dispose(); return t; }
scene.environment = envFrom(10, 0.6, C.envGround);                 // fallback IBL until / unless the HDRI loads
scene.environmentIntensity = C.envInt;
let envGlass = (C.glassEnv === 'sky' || C.glassEnv === 'bb-sky' || !C.hdri) ? envFrom(C.envTurb, C.envRayleigh, C.envGlassGround) : null;
async function hdriEnv(url) {                    // UE: SKY light = HDR_golden_bay_4k (Poly Haven), adjust_saturation 0.3, lower hemisphere not black
  const tex = await new RGBELoader().loadAsync(url); const d = tex.image.data, w = tex.image.width, h = tex.image.height, hf = THREE.DataUtils.fromHalfFloat;
  let best = -1, bc = 0, br = 0;
  for (let y = 0; y < h; y += 4) for (let x = 0; x < w; x += 4) { const o = (y*w + x)*4; const l = hf(d[o]) + hf(d[o+1]) + hf(d[o+2]); if (l > best) { best = l; bc = x; br = y; } }
  const du = C.splitIbl ? C.hdriYaw / 360.0 : (C.hdriAlign ? ((bc / w - 0.5) * 2 * Math.PI - Math.atan2(sunDir.z, sunDir.x)) / (2 * Math.PI) : 0.0) + C.hdriYaw / 360.0;   // split: native orientation (UE did not turn it)
  const rtE = new THREE.WebGLRenderTarget(2048, 1024, {type: THREE.HalfFloatType});
  const qm = new THREE.ShaderMaterial({uniforms: {tIn: {value: tex}, du: {value: du}, sat: {value: C.hdriSat}, lmax: {value: C.hdriClamp}}, depthTest: false, depthWrite: false,
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: 'uniform sampler2D tIn; uniform float du, sat, lmax; varying vec2 vUv; void main(){ vec3 c = texture2D(tIn, vec2(fract(vUv.x + du), vUv.y)).rgb; float y = dot(c, vec3(0.2126, 0.7152, 0.0722)); c = max(mix(vec3(y), c, sat), 0.0); c *= min(1.0, lmax / max(y, 1e-4)); gl_FragColor = vec4(c, 1.0); }'});
  const qs = new THREE.Scene(); qs.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), qm));
  const oc = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  if (C.splitIbl) {                             // DIFFUSE: the HDRI WITH its own low warm sun (golden hour, ~opposite our sun), as L2 SH irradiance
    qm.uniforms.lmax.value = 1e9; const rtD = new THREE.WebGLRenderTarget(1024, 512, {type: THREE.HalfFloatType});
    r.setRenderTarget(rtD); r.render(qs, oc); r.setRenderTarget(null); rtD.texture.mapping = THREE.EquirectangularReflectionMapping;
    const cube = new THREE.WebGLCubeRenderTarget(128, {type: THREE.HalfFloatType}).fromEquirectangularTexture(r, rtD.texture);
    const lp = await LightProbeGenerator.fromCubeRenderTarget(r, cube); lp.intensity = C.diffInt; scene.add(lp); cube.dispose(); rtD.dispose();
    qm.uniforms.lmax.value = C.hdriClamp;
    log('split IBL: diffuse = SH light probe of the native HDRI (sun kept) x ' + C.diffInt + '; specular = sun-stripped HDRI (clamp ' + C.hdriClamp + ')'); }
  r.setRenderTarget(rtE); r.render(qs, oc); r.setRenderTarget(null);
  rtE.texture.mapping = THREE.EquirectangularReflectionMapping;
  const pm = new THREE.PMREMGenerator(r); const env = pm.fromEquirectangular(rtE.texture).texture; pm.dispose(); tex.dispose();
  log('HDRI ' + url.split('/').pop() + ': sun texel u=' + (bc/w).toFixed(3) + ' v=' + (br/h).toFixed(3) + ', turned ' + (du*360).toFixed(1) + ' deg onto the sun, saturation ' + C.hdriSat);
  if (C.showHdri) { scene.background = rtE.texture; dome.visible = false; }
  return env; }
const dome = new THREE.Mesh(new THREE.SphereGeometry(45000, 48, 24), new THREE.ShaderMaterial({side: THREE.BackSide, depthWrite: false, fog: false,
  uniforms: {top: {value: lin(C.sky[0])}, mid: {value: lin(C.sky[1])}, hor: {value: lin(C.sky[2])}, low: {value: lin(C.sky[3])}, uTopE: {value: C.skyTopE}},
  vertexShader: 'varying vec3 vW; void main(){ vec4 w = modelMatrix*vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }',
  fragmentShader: 'uniform vec3 top, mid, hor, low; uniform float uTopE; varying vec3 vW; void main(){ vec3 d = normalize(vW - cameraPosition); float e = d.y;' +
    ' vec3 c = e < 0.0 ? mix(hor, low, smoothstep(0.0, 0.04, -e)) : (e < 0.07 ? mix(hor, mid, smoothstep(0.0, 0.07, e)) : mix(mid, top, smoothstep(0.07, uTopE, e)));' +
    ' gl_FragColor = vec4(c, 1.0); }'}));
dome.frustumCulled = false; dome.renderOrder = -10; scene.add(dome);
const sun = new THREE.DirectionalLight(lin(C.sunRGB), C.sunInt);
sun.castShadow = true; sun.shadow.mapSize.set(C.shadowMap, C.shadowMap);
sun.shadow.bias = -0.0003; sun.shadow.normalBias = 0.0; sun.shadow.radius = 1.5;
scene.add(sun); scene.add(sun.target);
scene.fog = new THREE.Fog(lin(C.fogRGB), C.fogNear, C.fogFar);
if (C.fill > 0) scene.add(new THREE.HemisphereLight(lin(C.fillSky), lin(C.fillGround), C.fill));   // Lumen's sand bounce stand-in

// ---------------------------------------------------------------- flat / noise materials
const M = (rgb, rough, metal, extra) => new THREE.MeshStandardMaterial(Object.assign({color: lin(rgb), roughness: rough, metalness: metal}, extra || {}));
function noiseTex(a, b, n) {
  const d = new Uint8Array(n*n*4); const rnd = (x, y) => { const s = Math.sin(x*127.1 + y*311.7)*43758.5453; return s - Math.floor(s); };
  const g = 8, grid = []; for (let j = 0; j <= g; j++) for (let i = 0; i <= g; i++) grid.push(rnd(i % g, j % g));
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const fx = x/n*g, fy = y/n*g, i = Math.floor(fx), j = Math.floor(fy), u = fx-i, v = fy-j, s = t => t*t*(3-2*t), q = (ii, jj) => grid[jj*(g+1)+ii];
    let t = (q(i,j)*(1-s(u)) + q(i+1,j)*s(u))*(1-s(v)) + (q(i,j+1)*(1-s(u)) + q(i+1,j+1)*s(u))*s(v); t = 0.75*t + 0.25*rnd(x*0.37, y*0.71);
    const o = (y*n+x)*4; for (let k = 0; k < 3; k++) d[o+k] = Math.round(Math.pow(a[k] + (b[k]-a[k])*t, 1/2.2)*255); d[o+3] = 255; }
  const tx = new THREE.DataTexture(d, n, n); tx.colorSpace = THREE.SRGBColorSpace; tx.wrapS = tx.wrapT = THREE.RepeatWrapping;
  tx.magFilter = THREE.LinearFilter; tx.minFilter = THREE.LinearMipmapLinearFilter; tx.generateMipmaps = true; tx.anisotropy = 8; tx.needsUpdate = true; return tx; }
const sandTex = noiseTex(C.sandDark, C.sandLight, 256); sandTex.repeat.set(60000/400, 60000/400);
const LOOK = {
  asphalt: [[0.19,0.19,0.195],0.85], pavement: [[0.58,0.58,0.56],0.9], parking: [[0.21,0.21,0.215],0.85],
  grass: [[0.17,0.34,0.085],0.9], pitch: [[0.12,0.33,0.09],0.85], pool: [[0.065,0.40,0.50],0.05], construction: [[0.55,0.51,0.425],0.95],
  buildings: [[0.67,0.65,0.61],0.8], quay: [[0.66,0.58,0.45],0.8], plots: [[0.58,0.53,0.44],0.9], podium: [[0.52,0.47,0.39],0.85],
  kerb: [[0.70,0.70,0.68],0.8], mark_white: [[0.85,0.85,0.83],0.6], mark_yellow: [[0.85,0.62,0.08],0.6], rail_steel: [[0.55,0.56,0.58],0.3,0.9],
  hoarding: [[0.82,0.82,0.80],0.7], promenade: [[0.31,0.29,0.265],0.85]};
const water = new THREE.MeshPhysicalMaterial({color: lin(C.waterRGB), roughness: 0.07, metalness: 0, ior: 1.33, specularIntensity: 1, side: THREE.DoubleSide,
  polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4});
if (envGlass) { water.envMap = envGlass; water.envMapIntensity = C.envInt; }
const layerMat = (key, order) => { const L = LOOK[key]; return M(L[0], L[1], L[2] || 0, {side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -order, polygonOffsetUnits: -order*2}); };

// ---------------------------------------------------------------- M_DA_Facade (ue_bb_facade.py HLSL + HLSL_STORE) as a three.js shader
const FAC_GLSL = `
{ vec3 fw = vFacW; vec3 fn = normalize(cross(dFdx(fw), dFdy(fw)));
  float wall = 1.0 - smoothstep(0.55, 0.75, abs(fn.y));
  float hz = (abs(fn.x) > abs(fn.z) ? fw.z : fw.x);
  float z = (fw.y - uLand) / max(uGeo.x, 0.5), u = hz / max(uGeo.y, 0.3);
  float fz = fract(z), fu = fract(u), wz = max(fwidth(z), 1e-4), wu = max(fwidth(u), 1e-4);
  float bw = clamp(uGeo.z / max(uGeo.x, 0.5), 0.0, 1.0), mw = clamp(uGeo.w / max(uGeo.y, 0.3), 0.0, 1.0);
  float band = smoothstep(1.0 - bw - wz, 1.0 - bw + wz, fz), mull = smoothstep(1.0 - mw - wu, 1.0 - mw + wu, fu);
  band = mix(band, bw, clamp(wz * 2.5 - 0.5, 0.0, 1.0)); mull = mix(mull, mw, clamp(wu * 2.5 - 0.5, 0.0, 1.0));
  float mR = band * wall, mG = mull * wall * (1.0 - band * wall), mB = 1.0 - wall;
  vec3 col = mix(mix(mix(uGlass, uFrame, mG), uSpan, mR), uRoof, mB);
  float rou = mix(mix(mix(uR.x, uR.y, mG), uR.z, mR), uR.w, mB), met = mix(mix(mix(uM.x, uM.y, mG), uM.z, mR), uM.w, mB);
  float inStore = (1.0 - smoothstep(uStoreTop - 0.04, uStoreTop + 0.04, fw.y)) * wall;
  float su = hz / 3.0, swu = max(fwidth(su), 1e-4), sfr = smoothstep(0.94 - swu, 0.94 + swu, fract(su));
  sfr = mix(sfr, 0.06, clamp(swu * 2.5 - 0.5, 0.0, 1.0));
  float sgn = smoothstep(uStoreTop - 0.95, uStoreTop - 0.85, fw.y), sfm = sfr * (1.0 - sgn);
  col = mix(col, mix(mix(uSG, uSF, sfm), uSS, sgn), inStore);
  rou = mix(rou, mix(mix(0.05, 0.4, sfm), 0.4, sgn), inStore); met = mix(met, mix(mix(0.2, 0.8, sfm), 0.05, sgn), inStore);
  diffuseColor.rgb = col; roughnessFactor = rou; metalnessFactor = met; }
`;
function facadeMat(p) {
  const m = new THREE.MeshStandardMaterial({color: 0xffffff, roughness: 1, metalness: 0, flatShading: true, side: THREE.DoubleSide});
  if (envGlass && C.glassEnv !== 'bb-sky') { m.envMap = envGlass; m.envMapIntensity = C.envInt; }
  const U = {uGlass: {value: lin(p.glass)}, uFrame: {value: lin(p.frame)}, uSpan: {value: lin(p.span)}, uRoof: {value: lin(p.roof || [0.42,0.42,0.41])},
    uSG: {value: lin([0.16,0.11,0.06])}, uSF: {value: lin([0.05,0.05,0.05])}, uSS: {value: lin([0.07,0.07,0.075])},
    uR: {value: new THREE.Vector4(p.gr, p.fr, p.sr, 0.85)}, uM: {value: new THREE.Vector4(p.gm, p.fm, p.sm, 0.0)},
    uGeo: {value: new THREE.Vector4(p.floor, p.pane, p.band, p.mull)}, uLand: {value: C.lift}, uStoreTop: {value: p.store === false ? -1e7 : C.lift + 5.5}};
  m.onBeforeCompile = sh => { Object.assign(sh.uniforms, U);
    sh.vertexShader = 'varying vec3 vFacW;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\n vec4 fw4 = vec4(transformed, 1.0);\n#ifdef USE_INSTANCING\n fw4 = instanceMatrix * fw4;\n#endif\n vFacW = (modelMatrix * fw4).xyz;');
    sh.fragmentShader = 'varying vec3 vFacW;\nuniform vec3 uGlass, uFrame, uSpan, uRoof, uSG, uSF, uSS; uniform vec4 uR, uM, uGeo; uniform float uLand, uStoreTop;\n' +
      sh.fragmentShader.replace('#include <metalnessmap_fragment>', '#include <metalnessmap_fragment>\n' + FAC_GLSL); };
  m.customProgramCacheKey = () => 'da_facade2';
  m.userData.facade = p; return m; }

// ---------------------------------------------------------------- local reflections: box-projected cube probe (+ optional SSR)
const BP_GLSL = `uniform vec3 uBoxMin, uBoxMax, uProbePos;
vec3 bpcemDir(vec3 v, vec3 pos) {
  vec3 d = normalize(v);
  if (any(lessThan(pos, uBoxMin)) || any(greaterThan(pos, uBoxMax))) return d;
  vec3 a = (uBoxMax - pos) / d, b = (uBoxMin - pos) / d, m = max(a, b);
  return pos + d * min(min(m.x, m.y), m.z) - uProbePos; }
`;
function boxProject(m, P) {                     // this material's specular IBL samples the probe at the box hit point, not at infinity
  const prev = m.onBeforeCompile, prevKey = m.customProgramCacheKey ? m.customProgramCacheKey() : '';
  m.onBeforeCompile = (sh, rr) => {
    if (prev && prev !== THREE.Material.prototype.onBeforeCompile) prev(sh, rr);
    sh.uniforms.uBoxMin = {value: P.min}; sh.uniforms.uBoxMax = {value: P.max}; sh.uniforms.uProbePos = {value: P.pos};
    if (sh.vertexShader.indexOf('vFacW') < 0) {
      sh.vertexShader = 'varying vec3 vFacW;\n' + sh.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\n vec4 fw4 = vec4(transformed, 1.0);\n#ifdef USE_INSTANCING\n fw4 = instanceMatrix * fw4;\n#endif\n vFacW = (modelMatrix * fw4).xyz;');
      sh.fragmentShader = 'varying vec3 vFacW;\n' + sh.fragmentShader; }
    sh.fragmentShader = sh.fragmentShader.replace('#include <envmap_physical_pars_fragment>', BP_GLSL + THREE.ShaderChunk.envmap_physical_pars_fragment.replace(
      'reflectVec = inverseTransformDirection( reflectVec, viewMatrix );', 'reflectVec = inverseTransformDirection( reflectVec, viewMatrix ); reflectVec = bpcemDir( reflectVec, vFacW );')); };
  m.customProgramCacheKey = () => prevKey + '|bpcem';
  m.envMap = P.tex; m.envMapIntensity = C.envInt * C.probeInt; m.needsUpdate = true; }

// ---------------------------------------------------------------- tower materials: ue_bb_v1_build.apply_pbr_v1 + facade_mis
const F = C.facade, LM = C.landmarks, matCache = {};
function roleOf(nm) { const n = nm.toLowerCase();                          // ue_sobha_pbr.ROLE_OF, then the glass / walls fallback
  if (/spandrel/.test(n)) return 'spandrel'; if (/vision|retail_glass|window_glass|balustrade/.test(n)) return 'vision';
  if (/balcony_slab|slab_band|parapet/.test(n)) return 'slabs'; if (/mullion|column|fin/.test(n)) return 'fins';
  if (/roof/.test(n)) return 'roof'; if (/_wall/.test(n)) return 'walls'; return n.indexOf('glass') >= 0 ? 'vision' : 'walls'; }
const PE = k => F.pal[k] || F.pal['white'];
function simple(key, rgb, rough, metal, transparent, opacity) {
  const k = 's|' + key + (transparent ? '|t' : ''); if (matCache[k]) return matCache[k];
  const m = M(rgb, rough, metal, {flatShading: true, side: THREE.DoubleSide}); m.userData.key = k;
  if (transparent) { m.transparent = true; m.opacity = opacity; m.depthWrite = false; }
  return (matCache[k] = m); }
function facadeKey(idx, kind, isBB) {
  const look = F.per[idx] || ['white', 'blue_glass', 'sandstone', 'white'];     // walls, vision, slabs, fins
  const lf = LM[idx]; const cons = kind === 'cons';
  const k = (isBB ? 'bb|' : 'dt|') + (cons ? 'cons' : lf ? 'lm' + idx : look.join('/')) + '|' + kind + '|' + (F.floor || '') ;
  if (matCache[k]) return matCache[k];
  let p;
  if (cons) p = {glass: [0.035,0.035,0.037], frame: [0.42,0.41,0.39], span: [0.50,0.49,0.47], roof: [0.46,0.45,0.43], floor: 3.4, pane: 7.5, band: 0.45, mull: 0.7,
                 gr: 0.9, gm: 0.0, fr: 0.85, fm: 0.0, sr: 0.85, sm: 0.0, store: false};
  else {
    const g = PE(look[1]), f = PE(look[3]), sl = PE(look[2]), w = PE(look[0]);
    const fh = F.floor || (lf ? lf.floor : 3.4), pw = lf ? lf.pane : 1.5;
    if (kind === 'glass') p = {glass: lf ? lf.glass : g[0], frame: lf ? lf.frame : f[0], span: lf ? lf.span : g[0].map(c => c*0.55), floor: fh, pane: pw,
                               band: F.band || 0.8, mull: F.mull || 0.12, gr: Math.max(0.04, g[1]), gm: Math.min(0.8, g[2] + 0.1), fr: 0.35, fm: 0.6, sr: 0.3, sm: 0.35};
    else p = {glass: w[0], frame: g[0].map(c => c*0.8), span: sl[0], floor: fh, pane: 3.0, band: 0.35, mull: 1.7,
              gr: Math.max(0.5, w[1]), gm: 0.0, fr: 0.08, fm: 0.5, sr: 0.6, sm: 0.0};
  }
  const fm = facadeMat(p); fm.userData.bb = !!isBB; fm.userData.kind = kind;
  if (C.glassEnv === 'bb-sky' && isBB && envGlass) { fm.envMap = envGlass; fm.envMapIntensity = C.envInt; }   // BB glass: blue sky (UE Lumen sees canal + sky); Downtown: the HDRI
  return (matCache[k] = fm); }
function towerMaterial(idx, srcMat, v6, isBB) {
  const nm = srcMat.name || '', role = roleOf(nm);
  if (C.debugRoles) { const dc = {vision: [0.8,0.05,0.05], spandrel: [0.9,0.45,0.05], slabs: [0.05,0.15,0.9], fins: [0.05,0.7,0.1], walls: [0.5,0.5,0.5], roof: [0.02,0.02,0.02]}[role];
    return simple('dbg|' + role + (role === 'walls' && nm.indexOf('glass') >= 0 ? 'g' : ''), role === 'walls' && nm.indexOf('glass') >= 0 ? [0.9,0.1,0.8] : dc, 0.8, 0); }
  if (v6 || !C.useFacade) {                                           // real facade geometry: keep the GLB's PBR, fix shading only
    const k = 'v6|' + srcMat.uuid; if (matCache[k]) return matCache[k];
    const m = srcMat.clone(); m.flatShading = true; m.side = THREE.DoubleSide;
    if (v6 && isBB && role === 'vision' && !srcMat.transparent) { m.userData.facade = {v6: true}; m.userData.bb = true; m.userData.kind = 'glass'; }   // v6 glass joins the probe + SSR
    if (!v6) { const look = F.per[idx] || ['white','blue_glass','sandstone','white'];
      const e = PE(role === 'vision' || role === 'spandrel' ? look[1] : role === 'slabs' ? look[2] : role === 'fins' ? look[3] : role === 'roof' ? 'roof' : look[0]);
      m.color = lin(role === 'spandrel' ? e[0].map(c => c*0.75) : e[0]); m.roughness = e[1]; m.metalness = e[2]; }
    return (matCache[k] = m); }
  const look = F.per[idx] || ['white','blue_glass','sandstone','white'];
  if (isBB && C.lmk.construction[idx]) return facadeKey(idx, 'cons', isBB);
  if (role === 'vision' || role === 'spandrel' || (role === 'walls' && nm.toLowerCase().indexOf('glass') >= 0)) {
    return facadeKey(idx, 'glass', isBB); }
  if (role === 'walls') return facadeKey(idx, 'wall', isBB);
  if (role === 'slabs') { const e = PE(look[2]); return simple(look[2] + '_slabs', e[0], e[1], e[2]); }
  if (role === 'fins') { const e = PE(look[3]); return simple(look[3] + '_fins', e[0], e[1], e[2]); }
  const e = PE('roof'); return simple('roof', e[0], e[1], e[2]); }

// ---------------------------------------------------------------- UE-frame OBJ (v/f only) -> three frame, winding fixed
async function objGeom(url, yOff, xf) {
  const txt = await (await fetch(url)).text(); const V = [], Fc = [];
  let p = 0; const L = txt.length;
  while (p < L) { let e = txt.indexOf('\n', p); if (e < 0) e = L; const c0 = txt.charCodeAt(p), c1 = txt.charCodeAt(p+1);
    if (c0 === 118 && c1 === 32) { const s = txt.substring(p+2, e).split(' '); V.push(+s[0], +s[1], +s[2]); }
    else if (c0 === 102 && c1 === 32) { const s = txt.substring(p+2, e).split(' '); Fc.push(parseInt(s[0])-1, parseInt(s[2])-1, parseInt(s[1])-1); }
    p = e + 1; }
  const n = V.length/3, pos = new Float32Array(n*3);
  xf = xf || {sx: 1, sy: 1, ox: C.ueE, oz: C.ueN};
  for (let i = 0; i < n; i++) { pos[3*i] = V[3*i]/100*xf.sx + xf.ox; pos[3*i+1] = V[3*i+2]/100*xf.sy + yOff; pos[3*i+2] = V[3*i+1]/100*xf.sx + xf.oz; }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(n > 65535 ? new Uint32Array(Fc) : new Uint16Array(Fc), 1)); g.computeVertexNormals(); return g; }
const staticRoot = new THREE.Group(); scene.add(staticRoot);
async function obj(url, yOff, mat, opt) { opt = opt || {};
  const g = await objGeom(url, yOff, opt.xf); const m = new THREE.Mesh(g, mat); m.castShadow = !!opt.cast; m.receiveShadow = true;
  if (opt.order !== undefined) m.renderOrder = opt.order; (opt.parent || staticRoot).add(m); return m; }

// ---------------------------------------------------------------- towers
async function towers(url, pos, opt) {
  const g = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(url); log('glb ' + url.split('/').pop());
  const mats = new Set(); g.scene.traverse(o => { if (o.isMesh) mats.add(o.material.name || ''); });
  const v6 = C.forceV6 || [...mats].some(n => /slab_band|mullion|(^|_)fin(_|$)/.test(n));
  log('  materials ' + mats.size + (v6 ? ' - v6 facade GEOMETRY detected: shader steps aside' : ' - facade shader on'));
  g.scene.position.set(pos[0], pos[1], pos[2]); if (opt.parent) opt.parent.add(g.scene); g.scene.updateWorldMatrix(true, true);
  const byB = {}; let tris = 0, hidden = 0;
  g.scene.traverse(o => { if (!o.isMesh) return;
    const nm = o.name + ' ' + ((o.parent && o.parent.name) || ''); const mm = /(?:^|\s)b(\d+)/.exec(nm); const idx = mm ? +mm[1] : -1;
    o.userData.b = idx; (byB[idx] = byB[idx] || []).push(o);
    let src = o.material;                          // LOD1 (v3) GLBs: CityEngineMaterial_N - take the role from the node's class token
    if (/^CityEngineMaterial/.test(src.name || '')) src = {name: /glass/.test(nm) ? 'lod1_vision' : 'lod1_wall', transparent: false, opacity: 1, uuid: 'lod1', clone: () => o.material.clone()};
    o.userData.srcMat = src.name; o.material = towerMaterial(idx, src, v6, !!opt.landmarks); o.castShadow = true; o.receiveShadow = true;
    tris += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count)/3; });
  if (opt.hideNear) g.scene.traverse(o => { if (!o.isMesh) return; o.geometry.computeBoundingBox();
    const c = o.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(o.matrixWorld);
    if (Math.hypot(c.x - opt.hideNear[0], c.z - opt.hideNear[1]) < opt.hideNear[2]) { o.visible = false; hidden++; } });
  if (opt.landmarks) landmarkPass(byB);
  (opt.parent || staticRoot).add(g.scene); STAT.tris += tris; log('  tris ' + Math.round(tris) + (opt.hideNear ? ', hidden near Burj ' + hidden : ''));
  return {root: g.scene, byB, v6}; }

// ---------------------------------------------------------------- bb_landmark_crowns: heights, construction + cranes, crowns
const crownJobs = [], craneJobs = [];
function landmarkPass(byB) {
  const want = Object.assign({}, C.lmk.height);
  for (const [i, c] of Object.entries(C.lmk.crowns)) if (c[3]) want[i] = c[3];
  for (const [i, hk] of Object.entries(C.lmk.construction)) want[i] = hk[0] * hk[1];
  for (const [bid, parts] of Object.entries(byB)) {
    if (!(bid in want) && !(bid in C.lmk.crowns)) continue;
    const box = new THREE.Box3(); parts.forEach(o => { o.geometry.computeBoundingBox(); box.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld)); });
    const lo = box.min.y; let hi = box.max.y;
    if (bid in want && hi - lo > 10) { const k = want[bid] / (hi - lo);
      parts.forEach(o => { const l0 = lo - o.matrixWorld.elements[13]; o.geometry.translate(0, -l0, 0).scale(1, k, 1).translate(0, l0, 0); o.geometry.computeBoundingBox(); });
      log('  landmark b' + bid + ' height ' + (hi - lo).toFixed(0) + ' -> ' + want[bid].toFixed(0) + ' m'); hi = lo + want[bid]; }
    let top = null, tb = null; parts.forEach(o => { const b = o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld); if (!tb || b.max.y > tb.max.y) { tb = b; top = o; } });
    const ctr = tb.getCenter(new THREE.Vector3()), ext = tb.getSize(new THREE.Vector3()).multiplyScalar(0.5);
    if (bid in C.lmk.construction) { craneJobs.push({x: ctr.x, z: ctr.z, y: hi, yaw: (bid * 37) % 360, bid: +bid}); continue; }
    if (bid in C.lmk.crowns) { const [kind, ch, mk] = C.lmk.crowns[bid];
      let w = Math.min(ext.x, ext.z) * 2.0 * 0.92; w = Math.min(w, {needle: 12.0, fin_ring: 42.0, corner_spires: 42.0, cage: 40.0}[kind] || 45.0);
      if (hi - C.lift < 100) { log('  crown on b' + bid + ' skipped: roof under 100 m'); continue; }
      crownJobs.push({kind, ch, mk, w, x: ctr.x, z: ctr.z, y: hi, bid: +bid}); } } }
function crownMat(mk) { const k = 'crown|' + mk; if (matCache[k]) return matCache[k];
  const H = h => { const c = new THREE.Color(h); return [c.r, c.g, c.b]; };
  const P = {cream: () => simple('crown_cream', PE('ivory_stone')[0], PE('ivory_stone')[1], 0), white: () => simple('crown_white', PE('white')[0], PE('white')[1], 0),
    crown_glass: () => facadeMat({glass: H('#BFE3F5'), frame: H('#F2F2EF'), span: H('#9FC7DD'), floor: 3.0, pane: 1.2, band: 0.9, mull: 0.12, gr: 0.05, gm: 0.7, fr: 0.4, fm: 0.8, sr: 0.3, sm: 0.4, store: false}),
    steel: () => facadeMat({glass: H('#C8CACC'), frame: H('#B0B2B4'), span: H('#A0A3A6'), floor: 3.6, pane: 1.5, band: 0.9, mull: 0.12, gr: 0.2, gm: 1.0, fr: 0.4, fm: 0.8, sr: 0.3, sm: 0.4, store: false}),
    bronze: () => facadeMat({glass: H('#B8894F'), frame: H('#9A6E3A'), span: H('#8A6234'), floor: 3.6, pane: 1.5, band: 0.9, mull: 0.12, gr: 0.3, gm: 1.0, fr: 0.4, fm: 1.0, sr: 0.3, sm: 0.4, store: false})};
  return (matCache[k] = (P[mk] || P.white)()); }

// ---------------------------------------------------------------- merge static meshes per material (one copy, Uint32 index)
function mergeStatic(root) {
  root.updateMatrixWorld(true); const groups = new Map(); let n = 0;
  const keep = [];
  root.traverse(o => { if (!o.isMesh || o.isInstancedMesh || !o.visible) return; let vis = true, p = o; while (p) { if (!p.visible) vis = false; p = p.parent; } if (!vis) return;
    if (Object.keys(o.geometry.attributes).some(a => a !== 'position' && a !== 'normal' && a !== 'uv') || o.material.transparent) { keep.push(o); return; }
    const key = o.material.uuid + '|' + (o.castShadow ? 1 : 0) + '|' + (o.geometry.attributes.normal ? 1 : 0) + '|' + (o.geometry.attributes.uv ? 1 : 0) + '|' + o.renderOrder;
    if (!groups.has(key)) groups.set(key, {mat: o.material, cast: o.castShadow, order: o.renderOrder, list: []}); groups.get(key).list.push(o); n++; });
  const out = new THREE.Group();
  for (const gr of groups.values()) {
    let nv = 0, ni = 0; const hasN = !!gr.list[0].geometry.attributes.normal;
    for (const o of gr.list) { const g = o.geometry; nv += g.attributes.position.count; ni += g.index ? g.index.count : g.attributes.position.count; }
    const hasU = !!gr.list[0].geometry.attributes.uv, UV = hasU ? new Float32Array(nv*2) : null;
    const P = new Float32Array(nv*3), N = hasN ? new Float32Array(nv*3) : null, I = new Uint32Array(ni); let vo = 0, io = 0;
    const v = new THREE.Vector3(), nm = new THREE.Matrix3();
    for (const o of gr.list) { const g = o.geometry, pa = g.attributes.position, na = g.attributes.normal, mw = o.matrixWorld; nm.getNormalMatrix(mw);
      for (let i = 0; i < pa.count; i++) { v.fromBufferAttribute(pa, i).applyMatrix4(mw); P[3*(vo+i)] = v.x; P[3*(vo+i)+1] = v.y; P[3*(vo+i)+2] = v.z;
        if (N) { v.fromBufferAttribute(na, i).applyMatrix3(nm).normalize(); N[3*(vo+i)] = v.x; N[3*(vo+i)+1] = v.y; N[3*(vo+i)+2] = v.z; }
        if (UV) { const ua = g.attributes.uv; UV[2*(vo+i)] = ua.getX(i); UV[2*(vo+i)+1] = ua.getY(i); } }
      if (g.index) { const ix = g.index.array; for (let k = 0; k < ix.length; k++) I[io+k] = ix[k] + vo; io += ix.length; }
      else { for (let k = 0; k < pa.count; k++) I[io+k] = vo + k; io += pa.count; }
      vo += pa.count; g.dispose(); }
    const bg = new THREE.BufferGeometry(); bg.setAttribute('position', new THREE.BufferAttribute(P, 3)); if (N) bg.setAttribute('normal', new THREE.BufferAttribute(N, 3)); if (UV) bg.setAttribute('uv', new THREE.BufferAttribute(UV, 2));
    bg.setIndex(new THREE.BufferAttribute(I, 1)); bg.computeBoundingSphere();
    const m = new THREE.Mesh(bg, gr.mat); m.castShadow = gr.cast; m.receiveShadow = true; m.renderOrder = gr.order; m.matrixAutoUpdate = false; out.add(m); }
  for (const o of keep) out.attach(o);
  root.removeFromParent(); scene.add(out); STAT.drawGroups = groups.size; STAT.mergedFrom = n; STAT.keptUnmerged = keep.length;
  log('merged ' + n + ' static meshes into ' + groups.size + ' draw groups (' + keep.length + ' textured meshes kept as they are)'); return out; }

// ---------------------------------------------------------------- post: GTAO, UE warm gain, bloom, ACES, vignette
const rt = new THREE.WebGLRenderTarget(W, H, {type: THREE.HalfFloatType, samples: 4});
const cam = new THREE.PerspectiveCamera(C.fovV, W/H, 5, 90000);
const comp = new EffectComposer(r, rt);
let ssr = null;
if (C.ssr) {                                      // screen-space reflections on BB glass + water (selects set after assembly); renders the beauty itself
  ssr = new SSRPass({renderer: r, scene, camera: cam, width: W, height: H, selects: []});
  ssr.beautyRenderTarget.samples = 4; ssr.beautyRenderTarget.depthTexture.type = THREE.UnsignedIntType;
  ssr.normalMaterial.flatShading = true; ssr.normalMaterial.side = THREE.DoubleSide; ssr.normalMaterial.needsUpdate = true;
  ssr.opacity = C.ssrOpacity; ssr.maxDistance = C.ssrDist; ssr.thickness = C.ssrThick; ssr.blur = true;
  ssr.ssrMaterial.defines.MAX_STEP = C.ssrSteps; ssr.ssrMaterial.needsUpdate = true;
  comp.addPass(ssr);
} else comp.addPass(new RenderPass(scene, cam));
function ssrSync() { if (!ssr) return; const u = ssr.ssrMaterial.uniforms; u.cameraNear.value = cam.near; u.cameraFar.value = cam.far;
  if (u.cameraRange) u.cameraRange.value = cam.far - cam.near;
  u.cameraProjectionMatrix.value.copy(cam.projectionMatrix); u.cameraInverseProjectionMatrix.value.copy(cam.projectionMatrixInverse);
  const d = ssr.depthRenderMaterial.uniforms; d.cameraNear.value = cam.near; d.cameraFar.value = cam.far; }
let gtao = null;
if (C.ao) { gtao = new GTAOPass(scene, cam, W, H);
  gtao.normalMaterial.flatShading = true; gtao.normalMaterial.side = THREE.DoubleSide; gtao.normalMaterial.needsUpdate = true;
  gtao.output = GTAOPass.OUTPUT.Default; gtao.blendIntensity = C.aoBlend; comp.addPass(gtao); }
const VS = 'varying vec2 vUv; void main(){vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}';
comp.addPass(new ShaderPass({uniforms: {tDiffuse: {value: null}, gain: {value: new THREE.Vector3(...C.gain)}, sat: {value: C.sat}}, vertexShader: VS,     // UE PPV_WARM gain x WB 8000 K, + saturation
  fragmentShader: 'uniform sampler2D tDiffuse; uniform vec3 gain; uniform float sat; varying vec2 vUv; void main(){ vec4 c=texture2D(tDiffuse,vUv); vec3 g=c.rgb*gain; float y=dot(g, vec3(0.2126,0.7152,0.0722)); gl_FragColor=vec4(max(mix(vec3(y), g, sat), 0.0), c.a); }'}));
if (C.glintClamp > 0) comp.addPass(new ShaderPass({uniforms: {tDiffuse: {value: null}, lmax: {value: C.glintClamp}}, vertexShader: VS,   // clamp HDR glints before bloom (UE's glints stay small)
  fragmentShader: 'uniform sampler2D tDiffuse; uniform float lmax; varying vec2 vUv; void main(){ vec4 c=texture2D(tDiffuse,vUv); float y=dot(c.rgb, vec3(0.2126,0.7152,0.0722)); gl_FragColor=vec4(c.rgb*min(1.0, lmax/max(y,1e-4)), c.a); }'}));
comp.addPass(new UnrealBloomPass(new THREE.Vector2(W/2, H/2), 0.35, C.bloomRadius, 0.92));
comp.addPass(new OutputPass());
comp.addPass(new ShaderPass({uniforms: {tDiffuse: {value: null}, amt: {value: 0.35}}, vertexShader: VS,
  fragmentShader: 'uniform sampler2D tDiffuse; uniform float amt; varying vec2 vUv; void main(){ vec4 c=texture2D(tDiffuse,vUv); vec2 d=(vUv-0.5)*vec2(1.0,1.2); float v=smoothstep(0.85,0.25,length(d)); c.rgb*=mix(1.0,v,amt); gl_FragColor=c; }'}));

// ---------------------------------------------------------------- view + cached, texel-snapped shadow frustum
const upW = new THREE.Vector3(0, 1, 0), lR = new THREE.Vector3().crossVectors(upW, sunDir).normalize(), lU = new THREE.Vector3().crossVectors(sunDir, lR).normalize();
let SH = null; const SHST = {updates: 0};
function fitShadow(ctr, halfWant) {
  const q = Math.pow(1.25, Math.ceil(Math.log(Math.min(4500, Math.max(300, halfWant))) / Math.log(1.25)));
  const tex = 2 * q / C.shadowMap;
  const a = Math.round(ctr.dot(lR) / tex) * tex, b = Math.round(ctr.dot(lU) / tex) * tex, c = ctr.dot(sunDir);
  const s = lR.clone().multiplyScalar(a).addScaledVector(lU, b).addScaledVector(sunDir, c);
  if (SH && SH.q === q && s.distanceTo(SH.c) < q * C.shadowSlack) return false;
  const sc = sun.shadow.camera; sc.left = -q; sc.right = q; sc.top = q; sc.bottom = -q; sc.near = 10; sc.far = 20000; sc.updateProjectionMatrix();
  sun.position.copy(s).addScaledVector(sunDir, 8000); sun.target.position.copy(s); sun.target.updateMatrixWorld(); sun.updateMatrixWorld();
  r.shadowMap.needsUpdate = true; SH = {q, c: s}; SHST.updates++; return true; }
function setView(v) {
  cam.position.set(...v.pos); dome.position.copy(cam.position); const tgt = new THREE.Vector3(...v.tgt); cam.lookAt(tgt);
  const dist = cam.position.distanceTo(tgt);
  cam.near = Math.max(0.25, Math.min(40, dist*0.012, Math.max(0.25, (v.pos[1] - C.lift) * 0.5))); cam.updateProjectionMatrix();   // eye level: near plane under 1 m
  const ctr = tgt.clone().lerp(new THREE.Vector3(v.pos[0], 0, v.pos[2]), 0.25); ctr.y = 0;
  fitShadow(ctr, dist * 1.35);
  if (gtao) gtao.updateGtaoMaterial({radius: Math.min(25, Math.max(3, dist*0.01)), distanceExponent: 1.5, thickness: Math.min(20, Math.max(2, dist*0.008)), scale: C.aoScale, samples: C.aoSamples});
  return dist; }
const px = new Uint8Array(4);
window.__pick = (v, nx, ny) => { setView(v); const rc = new THREE.Raycaster(); rc.setFromCamera(new THREE.Vector2(nx, ny), cam);   // debug: what is at NDC (nx, ny)
  const h = rc.intersectObjects(scene.children, true).filter(x => x.object !== dome && x.object.visible)[0]; if (!h) return null; const o = h.object;
  return {name: o.name, parent: o.parent && o.parent.name, b: o.userData.b, srcMat: o.userData.srcMat, facade: o.material.userData.facade || null, key: o.material.userData.key || null, dist: h.distance}; };
// motion blur + TAA: average N sub-frames (camera along the path within the shutter + Halton sub-pixel jitter), post-tonemap
const accRT = new THREE.WebGLRenderTarget(W, H, {type: THREE.HalfFloatType});
const accQ = new FullScreenQuad(new THREE.ShaderMaterial({uniforms: {tDiffuse: {value: null}, w: {value: 1}}, vertexShader: VS, transparent: true,
  blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
  fragmentShader: 'uniform sampler2D tDiffuse; uniform float w; varying vec2 vUv; void main(){ gl_FragColor = vec4(texture2D(tDiffuse, vUv).rgb * w, 1.0); }'}));
const blitQ = new FullScreenQuad(new THREE.ShaderMaterial({uniforms: {tDiffuse: {value: accRT.texture}}, vertexShader: VS, depthTest: false, depthWrite: false,
  fragmentShader: 'uniform sampler2D tDiffuse; varying vec2 vUv; void main(){ gl_FragColor = vec4(texture2D(tDiffuse, vUv).rgb, 1.0); }'}));
function renderAt(v) {
  if (!v.subs || v.subs.length < 2) { setView(v); ssrSync(); comp.renderToScreen = true; comp.render(); return; }
  comp.renderToScreen = false; r.setRenderTarget(accRT); r.setClearColor(0x000000, 1); r.clear(); r.setRenderTarget(null);
  for (const sv of v.subs) {
    setView(sv); cam.setViewOffset(W, H, sv.jx || 0, sv.jy || 0, W, H); ssrSync(); comp.render(); cam.clearViewOffset();
    accQ.material.uniforms.tDiffuse.value = comp.readBuffer.texture; accQ.material.uniforms.w.value = 1.0 / v.subs.length;
    r.setRenderTarget(accRT); r.autoClear = false; accQ.render(r); r.autoClear = true; r.setRenderTarget(null); }
  blitQ.render(r); }
window.renderView = v => { const t = performance.now(); renderAt(v); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); return performance.now() - t; };
window.renderFrames = async (views, q) => {                  // MRQ-equivalent: one JPEG per frame index, streamed to disk
  const t0 = performance.now(), ms = [], inflight = []; SHST.updates = 0; let tPrev = t0;
  for (let i = 0; i < views.length; i++) {
    renderAt(views[i]); const idx = views[i].idx;
    inflight.push(new Promise(res => r.domElement.toBlob(res, 'image/jpeg', q)).then(b => b.arrayBuffer()).then(ab => b64(new Uint8Array(ab))).then(s => window.__frame(idx, s)));
    if (inflight.length >= 4) await inflight.shift();
    const now = performance.now(); ms.push(now - tPrev); tPrev = now;
    if (i % 100 === 0) await window.__progress(i, views.length, (now - t0) / 1000, SHST.updates);
  }
  await Promise.all(inflight);
  const tot = (performance.now() - t0) / 1000, srt = ms.slice().sort((a, b) => a - b);
  return {frames: views.length, total_s: tot, ms_per_frame_mean: tot * 1000 / views.length, ms_median: srt[srt.length >> 1], ms_p95: srt[Math.floor(srt.length * 0.95)],
          ms_max: srt[srt.length - 1], shadow_updates: SHST.updates}; };

// ---------------------------------------------------------------- film: render loop + WebCodecs H.264 + mp4-muxer, streamed to disk
async function b64(u8) { return await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.slice(fr.result.indexOf(',') + 1)); fr.readAsDataURL(new Blob([u8])); }); }
window.renderFilm = async (views, fps, bitrate) => {
  const pend = []; let bytes = 0;
  const muxer = new Muxer({target: new StreamTarget({onData: (data, pos) => { bytes += data.byteLength; const cp = data.slice(); pend.push(b64(cp).then(s => window.__sink(pos, s))); },
                                                      chunked: true, chunkSize: 8 * 1024 * 1024}),
                           video: {codec: 'avc', width: W, height: H, frameRate: fps}, fastStart: false});
  let encErr = null;
  const enc = new VideoEncoder({output: (chunk, meta) => muxer.addVideoChunk(chunk, meta), error: e => { encErr = String(e); }});
  const cfg = {codec: 'avc1.640033', width: W, height: H, bitrate, framerate: fps, hardwareAcceleration: 'prefer-hardware', avc: {format: 'avc'}, latencyMode: 'quality', bitrateMode: 'variable'};
  const sup = await VideoEncoder.isConfigSupported(cfg); if (!sup.supported) throw new Error('H.264 config not supported');
  enc.configure(cfg);
  const t0 = performance.now(), ms = []; SHST.updates = 0; let tPrev = t0;
  for (let i = 0; i < views.length; i++) {
    renderAt(views[i]);
    const vf = new VideoFrame(r.domElement, {timestamp: Math.round(i * 1e6 / fps), duration: Math.round(1e6 / fps)});
    enc.encode(vf, {keyFrame: i % (fps * 2) === 0}); vf.close();
    while (enc.encodeQueueSize > 3) await new Promise(res => setTimeout(res, 0));
    if (encErr) throw new Error(encErr);
    const now = performance.now(); ms.push(now - tPrev); tPrev = now;
    if (i % 100 === 0) await window.__progress(i, views.length, (now - t0) / 1000, SHST.updates);
  }
  await enc.flush(); muxer.finalize(); await Promise.all(pend);
  const tot = (performance.now() - t0) / 1000, srt = ms.slice().sort((a, b) => a - b);
  return {frames: views.length, total_s: tot, ms_per_frame_mean: tot * 1000 / views.length, ms_median: srt[srt.length >> 1], ms_p95: srt[Math.floor(srt.length * 0.95)],
          ms_max: srt[srt.length - 1], shadow_updates: SHST.updates, bytes, hw: sup.config.hardwareAcceleration}; };

// ---------------------------------------------------------------- scene assembly
(async () => {
  const gz = 0.0, gl_ = gz + C.lift, ctxOn = !!C.ctx;
  const sand = new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000), new THREE.MeshStandardMaterial({map: sandTex, roughness: 0.95}));
  sand.rotation.x = -Math.PI/2; sand.position.set(0, gz - 0.2, 0); sand.receiveShadow = true; scene.add(sand);
  const D = C.base + 'data/ce/_datasmith/', jobs = [];
  const wy = ctxOn ? gz - 0.10 : gz + 0.10;                             // under the lab ground's own sand/water when it is loaded
  jobs.push(obj(D + 'ground/sea.obj', wy, water), obj(D + 'ground/inland_water.obj', wy, water));
  let o = 1;
  if (C.groundMode === 'bb_v1') {                // Business Bay: bb_v1_prep's 3 km surround
  for (const k of ['s_asphalt','s_pavement','s_parking','s_grass']) jobs.push(obj(D + 'bb_v1/ctx_' + k + '.obj', gz - 0.03, layerMat(k.slice(2), o++)));
  jobs.push(obj(D + 'bb_v1/ctx_s_buildings.obj', gz - 0.03, M(LOOK.buildings[0], 0.8, 0), {cast: true})); }
  if (C.groundMode === 'layers') jobs.push(groundLayers(C.groundLayersUrl, gl_));
  if (C.groundMode === 'bb_v1' && !ctxOn) {
    for (const k of ['asphalt','pavement','parking','grass','pitch','pool','construction']) jobs.push(obj(D + 'bb_v1/ctx_' + k + '.obj', gl_, layerMat(k, o++)));
    jobs.push(obj(D + 'bb_v1/v1_canal_water.obj', gl_, water));
    for (const k of ['quay','promenade','plots','podium','kerb','mark_white','mark_yellow','rail_steel','hoarding'])
      jobs.push(obj(D + 'bb_v1/v1_' + k + '.obj', gl_, layerMat(k, o++), {cast: ['quay','rail_steel','hoarding'].indexOf(k) >= 0}));
  }
  await Promise.all(jobs); log('bb_v1 context meshes: ' + jobs.length + (ctxOn ? ' (district ground from the lab context GLB instead)' : ''));
  if (C.hdri) scene.environment = await hdriEnv(C.hdri);
  const bbGroup = new THREE.Group(); bbGroup.position.set(0, gl_, 0); staticRoot.add(bbGroup);    // v5 local frame, land level = y 0
  const dyn = new THREE.Group(); dyn.position.set(0, gl_, 0); scene.add(dyn);                    // instanced / unmerged: scenery, kits
  if (ctxOn) await scenery(bbGroup, dyn);
  const bb = await towers(C.towersUrl, [0, 0, 0], {landmarks: true, parent: bbGroup});
  if (C.downtown) {
    await towers(C.base + 'data/ce/_glb/sky_burjkhalifa_' + C.downtownLod + '_0.glb', C.dtPos, {hideNear: [C.burj[0], C.burj[2], 70]});
    const bo = {cast: true, xf: {sx: 1, sy: 1, ox: C.burj[0], oz: C.burj[2]}};
    await Promise.all([obj(D + 'bb_v1/burj_glass.obj', gz, M(C.burjGlass, 0.08, 0.8), bo), obj(D + 'bb_v1/burj_band.obj', gz, M(C.burjBand, 0.3, 0.6), bo),
                       obj(D + 'bb_v1/burj_spire.obj', gz, M(C.burjSpire, 0.25, 0.9), bo)]);
    log('hero Burj placed');
  }
  for (const c of crownJobs) await obj(D + 'bb_v1/crown_' + c.kind + '.obj', c.y, crownMat(c.mk), {cast: true, xf: {sx: c.w, sy: c.ch, ox: c.x, oz: c.z}});
  if (crownJobs.length) log('crowns ' + crownJobs.map(c => c.kind + '@b' + c.bid).join(' '));
  if (C.kits && C.kits.crane && craneJobs.length) {
    const g = await new GLTFLoader().loadAsync(C.kits.crane); const box = new THREE.Box3().setFromObject(g.scene); const k = 70.0 / (box.max.y - box.min.y);
    for (const j of craneJobs) { const c = g.scene.clone(); c.scale.setScalar(k); c.rotation.y = THREE.MathUtils.degToRad(j.yaw);
      c.position.set(j.x, j.y - C.lift - box.min.y * k, j.z); c.traverse(q => { if (q.isMesh) { q.castShadow = true; q.receiveShadow = true; } }); dyn.add(c); }
    log('tower cranes on construction tops: ' + craneJobs.map(j => 'b' + j.bid).join(' '));
  }
  if (C.kits && C.kits.cafe && C.cafes.length && (!(ctxOn && C.ctx.hasCafes) || C.cafeKits)) await cafes(dyn);
  if (C.storefronts) await storefronts(C.storefronts);
  if (C.merge) mergeStatic(staticRoot);
  if (C.probe && C.glassEnv === 'bpcem') {       // local reflections: one cube capture of the finished district, box-projected per fragment
    const t0 = performance.now();
    const crt = new THREE.WebGLCubeRenderTarget(C.probeRes, {type: THREE.HalfFloatType});
    const cc = new THREE.CubeCamera(1, 60000, crt); cc.position.set(...C.probe); scene.add(cc); dome.position.set(...C.probe);
    let skyMesh = null;
    if (C.probeSky === 'physical') {             // reflections see a physical (Preetham) sky, as Unreal's glass sees SkyAtmosphere; the camera still sees the dome
      su.turbidity.value = C.envTurb; su.rayleigh.value = C.envRayleigh; skyMesh = sky.clone(); skyMesh.scale.setScalar(50000); skyMesh.position.set(...C.probe);
      skyMesh.material = sky.material.clone(); skyMesh.material.fragmentShader = skyMesh.material.fragmentShader.replace('L0 += ( vSunE * 19000.0 * Fex ) * sundisk;', '');
      skyMesh.material.depthWrite = false; skyMesh.renderOrder = -11; scene.add(skyMesh); dome.visible = false; scene.fog.far *= 4; }
    fitShadow(new THREE.Vector3(C.probe[0], 0, C.probe[2]), 3500); cc.update(r, scene); scene.remove(cc);
    if (skyMesh) { scene.remove(skyMesh); dome.visible = true; scene.fog.far /= 4; }
    const pm = new THREE.PMREMGenerator(r); const tex = pm.fromCubemap(crt.texture).texture; pm.dispose(); crt.dispose();
    const P = {tex, pos: new THREE.Vector3(...C.probe), min: new THREE.Vector3(...C.probeBox[0]), max: new THREE.Vector3(...C.probeBox[1])};
    let n = 0, w = 0;
    for (const m of Object.values(matCache)) if (m.userData.facade && m.userData.bb) { boxProject(m, P); n++; }
    const wm = new Set([water]); scene.traverse(q => { if (q.isMesh && q.material && /ctx_(canal|water|pool)$/.test(q.material.name || '')) wm.add(q.material); });
    if (C.probeWater) for (const m of wm) { boxProject(m, P); w++; }
    log('box-projected probe at (' + C.probe.map(v => v.toFixed(0)).join(', ') + '), ' + C.probeRes + ' px cube, box ' + C.probeBox.map(b => b.map(v => v.toFixed(0)).join('/')).join(' .. ') +
        ': ' + n + ' BB facade + ' + w + ' water materials (' + ((performance.now() - t0)/1000).toFixed(1) + ' s)');
  }
  if (C.probe && (C.glassEnv === 'probe' || C.glassEnv === 'mix')) {   // reflection probe: what Lumen reflections give Unreal's glass (canal, sand, the towers) - one cube capture
    const crt = new THREE.WebGLCubeRenderTarget(C.probeRes, {type: THREE.HalfFloatType});
    const cc = new THREE.CubeCamera(1, 60000, crt); cc.position.set(...C.probe); scene.add(cc); dome.position.set(...C.probe);
    fitShadow(new THREE.Vector3(C.probe[0], 0, C.probe[2]), 3500); cc.update(r, scene); scene.remove(cc);
    const pm = new THREE.PMREMGenerator(r); const envProbe = pm.fromCubemap(crt.texture).texture; pm.dispose(); crt.dispose();
    let n = 0; for (const m of Object.values(matCache)) if (m.userData.facade && (C.glassEnv === 'probe' || m.userData.bb)) { m.envMap = envProbe; m.envMapIntensity = C.envInt * C.probeInt; m.needsUpdate = true; n++; }
    if (C.probeWater) { water.envMap = envProbe; water.envMapIntensity = C.envInt * C.probeInt; water.needsUpdate = true;
      scene.traverse(q => { if (q.isMesh && q.material && /ctx_(canal|water)$/.test(q.material.name || '')) { q.material.envMap = envProbe; q.material.envMapIntensity = C.envInt * C.probeInt; q.material.needsUpdate = true; } }); }
    log('reflection probe at (' + C.probe.map(v => v.toFixed(0)).join(', ') + ') ' + C.probeRes + 'px cube -> ' + n + ' facade materials' + (C.probeWater ? ' + water' : ''));
  }
  if (ssr) { const sel = []; scene.traverse(q => { if (!q.isMesh || !q.material || !q.visible) return; const m = q.material;
      if ((m.userData.facade && m.userData.bb && m.userData.kind === 'glass') || m === water || /ctx_(canal|water|pool)$/.test(m.name || '')) sel.push(q); });
    ssr.selects = sel; log('SSR on ' + sel.length + ' meshes (BB curtain-wall glass + water), opacity ' + C.ssrOpacity + ', max ' + C.ssrDist + ' m, ' + C.ssrSteps + ' steps'); }
  const t = performance.now(); r.compile(scene, cam); fitShadow(new THREE.Vector3(0,0,0), 3000); window.renderView(C.views[0]); window.renderView(C.views[0]);
  log('compile + first 2 renders ' + ((performance.now()-t)/1000).toFixed(1) + ' s');
  window.__stat = STAT; document.title = 'ready';
})().catch(e => { document.title = 'error ' + e + ' ' + (e.stack || ''); });

// ---------------------------------------------------------------- generic district ground (lab_nounreal_render.ground_layers: context_ue.json + water.json)
async function groundLayers(url, y0) {
  const J = await (await fetch(url)).json(); let o = 1, tris = 0;
  for (const L of J.layers) {
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(L.pos), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(L.idx), 1)); g.computeVertexNormals();
    const mat = L.water ? water : M(L.rgb, L.rough, 0, {side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4 * (o++)});
    const m = new THREE.Mesh(g, mat); m.position.y = y0; m.receiveShadow = true; staticRoot.add(m); tris += L.idx.length / 3; }
  log('district ground: ' + J.layers.map(L => L.name).join(', ') + ' (' + tris + ' tris)'); }

// ---------------------------------------------------------------- scenery agent layers (manifest.json): ground + instanced vegetation / furniture / props
async function scenery(groundParent, instParent) {
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder), PR = C.ctx.palette;
  for (const L of C.ctx.layers) {
    const g = await loader.loadAsync(L.url); let inst = 0, hidden = 0, fixed = 0, meshes = 0;
    g.scene.traverse(q => {
      const ud = q.userData || {};
      if (C.filmParity && ud.klass === 'json') { q.visible = false; hidden += ud.instances || 0; }
      if (C.cafeKits && /^(cafe_table|cafe_chair|umbrella|pot)$/.test(ud.asset || '')) q.visible = false;   // close shots: real kits instead of primitives
      if (!q.isMesh) return; meshes++;
      const dor = ud.draw_order !== undefined ? ud.draw_order : ((q.parent && q.parent.userData && q.parent.userData.draw_order) || 0);
      for (const m of (Array.isArray(q.material) ? q.material : [q.material])) {
        const role = PR[m.name];
        if (role) {                                   // PyPRT's glTF writer drops roughness / metallic / emissive: verify against the palette
          if (Math.abs(m.roughness - role.roughness) > 0.02 || Math.abs(m.metalness - role.metallic) > 0.02) { fixed++; m.roughness = role.roughness; m.metalness = role.metallic; }
          if (role.emissive_rgb && m.emissive && m.emissive.r + m.emissive.g + m.emissive.b < 0.01) { fixed++; m.emissive = lin(role.emissive_rgb); m.emissiveIntensity = 1.0; }
          if (role.opacity !== undefined && role.opacity !== null && role.opacity < 1 && !m.transparent) { fixed++; m.transparent = true; m.opacity = role.opacity; m.depthWrite = false; } }
        if (/ctx_(canal|water)$/.test(m.name) && C.waterOverride) { m.color = lin(C.waterRGB); m.roughness = 0.07; }   // UE water reads brighter under Lumen
        if (L.layer === 'ground') { m.polygonOffset = true; m.polygonOffsetFactor = -1; m.polygonOffsetUnits = -6 * dor; m.side = THREE.DoubleSide; }
      }
      if (q.isInstancedMesh) { q.frustumCulled = false; let v = true, pp = q; while (pp) { if (!pp.visible) v = false; pp = pp.parent; } if (v) inst += q.count; }
      q.castShadow = L.layer !== 'ground' || /quay|kerb|hoarding|rail/.test(q.material.name || ''); q.receiveShadow = true; });
    (L.layer === 'ground' ? groundParent : instParent).add(g.scene);
    log('scenery ' + L.layer + ' ' + L.url.split('/').pop() + ': ' + meshes + ' meshes' + (L.layer === 'ground' ? '' : ', ' + inst + ' instances shown, ' + hidden + ' json instances hidden (film parity)') + ', ' + fixed + ' material values restored from context_palette.json');
  } }

// ---------------------------------------------------------------- storefronts (ue_bb_v1_build.storefronts: glazing, sign bands, awnings, pavement tables)
async function storefronts(SF) {
  const unit = new THREE.BoxGeometry(1, 1, 1), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(0, 0, 0, 'YXZ'), sc = new THREE.Vector3(), ps = new THREE.Vector3();
  const shop = facadeMat({glass: [0.10, 0.075, 0.05], frame: [0.09, 0.07, 0.05], span: [0.09, 0.07, 0.05], floor: 40.0, pane: 2.0, band: 0.0, mull: 0.09,
                          gr: 0.04, gm: 0.35, fr: 0.35, fm: 0.9, sr: 0.3, sm: 0.4, store: false});
  let n = 0;
  for (const [key, list] of Object.entries(SF.groups)) {
    const mat = key === 'glass' ? shop : M(SF.colours[key] || [0.3, 0.3, 0.3], key.startsWith('awning') ? 0.8 : 0.4, 0);
    const im = new THREE.InstancedMesh(unit, mat, list.length); im.castShadow = true; im.receiveShadow = true; im.frustumCulled = false;
    list.forEach((b, i) => { e.set(b[7], b[6], 0); q.setFromEuler(e); sc.set(b[3], b[4], b[5]); ps.set(b[0], b[1], b[2]); im.setMatrixAt(i, m4.compose(ps, q, sc)); });
    scene.add(im); n += list.length; }
  let kitParts = 0;
  if (C.kits && C.kits.cafe) {                   // the pavement tables use the same Poly Haven kits Unreal placed (bistro table / chair, parasol)
    const K = C.kits.cafe;
    for (const [url, h, rows] of [[K.table, 0.75, SF.tables], [K.chair, 0.9, SF.chairs], [K.umbrella, 2.6, SF.umbrellas]]) {
      if (!url || !rows.length) continue;
      const g = await new GLTFLoader().loadAsync(url); const box = new THREE.Box3().setFromObject(g.scene); const k = h / Math.max(0.01, box.max.y - box.min.y);
      g.scene.updateMatrixWorld(true);
      g.scene.traverse(o => { if (!o.isMesh) return; const im = new THREE.InstancedMesh(o.geometry, o.material, rows.length); im.castShadow = true; im.receiveShadow = true; im.frustumCulled = false;
        rows.forEach(([x, z, yaw], i) => { q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -THREE.MathUtils.degToRad(yaw)); sc.setScalar(k); ps.set(x, C.lift - box.min.y * k, z);
          im.setMatrixAt(i, m4.compose(ps, q, sc).multiply(o.matrixWorld)); });
        scene.add(im); kitParts += rows.length; }); } }
  log('storefronts: ' + n + ' boxes (' + (SF.groups.glass || []).length + ' shopfronts, signs, awnings) + ' + kitParts + ' table / chair / parasol parts'); }

// ---------------------------------------------------------------- promenade cafe clusters (ue_bb_v1_build.dress: table + 4 chairs + parasol + 2 pots)
async function cafes(parent) {
  const load = async (url, h) => { const g = await new GLTFLoader().loadAsync(url); const box = new THREE.Box3().setFromObject(g.scene);
    const k = h / Math.max(0.01, box.max.y - box.min.y); const parts = []; g.scene.updateMatrixWorld(true);
    g.scene.traverse(q => { if (q.isMesh) parts.push({geo: q.geometry, mat: q.material, mw: q.matrixWorld.clone()}); }); return {parts, k, y0: box.min.y}; };
  const K = C.kits.cafe, kit = {};
  for (const [name, url, h] of [['table', K.table, 0.75], ['chair', K.chair, 0.9], ['umbrella', K.umbrella, 2.6], ['pot', K.pot, 1.1]]) if (url) kit[name] = await load(url, h);
  const rows = {table: [], chair: [], umbrella: [], pot: []};
  for (const [x, z, yaw] of C.cafes) {
    rows.table.push([x, z, yaw]); rows.umbrella.push([x, z, yaw]);
    for (let q = 0; q < 4; q++) { const a = THREE.MathUtils.degToRad(yaw + 45 + 90*q); rows.chair.push([x + 0.8*Math.cos(a), z + 0.8*Math.sin(a), yaw + 45 + 90*q + 180]); }
    const a = THREE.MathUtils.degToRad(yaw); for (const s of [-1, 1]) rows.pot.push([x + s*1.8*Math.cos(a), z + s*1.8*Math.sin(a), yaw]); }
  let n = 0; const m4 = new THREE.Matrix4(), q4 = new THREE.Quaternion(), sc = new THREE.Vector3(), ps = new THREE.Vector3();
  for (const [name, list] of Object.entries(rows)) { const kt = kit[name]; if (!kt) continue;
    for (const p of kt.parts) { const im = new THREE.InstancedMesh(p.geo, p.mat, list.length); im.castShadow = true; im.receiveShadow = true;
      list.forEach(([x, z, yaw], i) => { q4.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -THREE.MathUtils.degToRad(yaw)); sc.setScalar(kt.k); ps.set(x, -kt.y0*kt.k, z);
        m4.compose(ps, q4, sc).multiply(p.mw); im.setMatrixAt(i, m4); });
      parent.add(im); n += list.length; } }
  log('cafe clusters ' + C.cafes.length + ' (' + n + ' instanced parts)'); }
</script></body></html>"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "stills"
    plan = json.load(open(arg("--plan", PLAN), encoding="utf-8"))
    set_district(arg("--district", plan.get("district_slug", "businessbay")), plan)
    W, H = int(arg("--w", 1080 if mode != "seq" else 720)), int(arg("--h", 1920 if mode != "seq" else 1280))
    fps = int(arg("--fps", plan.get("fps", 25)))
    fov_v = math.degrees(2 * math.atan((42.667 / 2.0) / float(plan.get("focal_mm", 20.0))))
    views = []
    if mode == "stills" and arg("--views"):                  # custom cameras: [{"name", "pos_ue"/"tgt_ue" (UE cm) or "pos"/"tgt" (three m)}]
        for v in json.load(open(arg("--views"), encoding="utf-8")):
            views.append({"name": v["name"], "film_t": v.get("film_t"), "render_t": v.get("render_t"),
                          "pos": v["pos"] if "pos" in v else cam3(v["pos_ue"]), "tgt": v["tgt"] if "tgt" in v else cam3(v["tgt_ue"])})
    elif mode == "frames":                                       # MRQ equivalent: bb_v1.<frame>.jpeg for the frame indices asked for
        idx = edit_frames(plan, fps) if arg("--indices", "edit") == "edit" else sorted({int(x) for x in arg("--indices").split(",")})
        for i in idx:
            loc, tgt = cam_at(plan, i / float(fps))
            views.append({"idx": i, "render_t": round(i / float(fps), 3), "pos": cam3(loc), "tgt": cam3(tgt)})
    elif mode == "stills":
        for ft in [float(x) for x in arg("--film", "6,21,34,42").split(",")]:
            rt = film_to_render_t(plan, ft); loc, tgt = cam_at(plan, rt)
            views.append({"name": "film_t%gs" % ft, "film_t": ft, "render_t": round(rt, 3), "pos": cam3(loc), "tgt": cam3(tgt)})
    elif mode == "seq":
        f0, secs = float(arg("--film0", 36.4)), float(arg("--secs", 5))
        for i in range(int(round(secs * fps))):
            ft = f0 + i / float(fps); rt = film_to_render_t(plan, ft); loc, tgt = cam_at(plan, rt)
            views.append({"film_t": round(ft, 3), "render_t": round(rt, 3), "pos": cam3(loc), "tgt": cam3(tgt)})
    else:                                                        # the whole camera path, as MRQ rendered it (0 .. total_s)
        n = int(round(float(plan["total_s"]) * fps))
        for i in range(n):
            loc, tgt = cam_at(plan, i / float(fps))
            views.append({"render_t": round(i / float(fps), 3), "pos": cam3(loc), "tgt": cam3(tgt)})
    if int(arg("--mb", 1)) > 1:                               # UE camera: motion_blur_amount 0.3, MRQ temporal_sample_count 2
        add_subs(plan, views, fps, int(arg("--mb", 1)), float(arg("--shutter", 0.3)))
    p, y = math.radians(-float(plan["district_cfg"].get("sun_elev_deg", 33.0))), math.radians(-22.0)
    fwd = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
    sun = [-fwd[0], -fwd[2], -fwd[1]]                            # UE SUN actor Rotator(-33, -22) == Dubai 29 Sep ~15:35 GST
    ctx = None
    man = os.path.join(CTX_DIR, "manifest.json")
    if "--no-ctx" not in sys.argv and os.path.exists(man):       # scenery agent output (read-only): manifest.json + context_palette.json
        M = json.load(open(man, encoding="utf-8")); layers = []
        for L in M.get("layers", []):
            f = L.get("file_uncompressed") if L.get("file_uncompressed") and os.path.exists(os.path.join(CTX_DIR, L["file_uncompressed"])) else L["file"]
            if os.path.exists(os.path.join(CTX_DIR, f)):
                layers.append({"layer": L["layer"], "url": "data/lab/context/businessbay/" + f})
        pal = json.load(open(os.path.join(CTX_DIR, M.get("palette", "context_palette.json")), encoding="utf-8"))["roles"]
        roles = {k: {kk: v.get(kk) for kk in ("roughness", "metallic", "emissive_rgb", "opacity") if kk in v} for k, v in pal.items()}
        cafes_in = any("cafe_table" in (L.get("by_asset") or {}) for L in M.get("layers", []))
        ctx = {"layers": layers, "palette": roles, "hasCafes": cafes_in, "built": M.get("built")}
    towers = arg("--towers")
    if not towers:
        v6 = sorted(glob.glob(os.path.join(ROOT, "data", "ce", "_glb", "sky_%s_v6*_0.glb" % SLUG)))
        towers = v6[-1] if v6 else os.path.join(ROOT, "data", "ce", "_glb", "sky_%s_v5_0.glb" % SLUG)
    towers_rel = os.path.relpath(os.path.abspath(towers), ROOT).replace(os.sep, "/")
    if towers_rel.startswith(".."):
        raise SystemExit("--towers must be under the repo (served read-only from %s)" % ROOT)
    kits = {}
    if "--no-kits" not in sys.argv:
        rel = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")
        cr = os.path.join(KITS_DIR, "tower_crane.glb")
        if os.path.exists(cr):
            kits["crane"] = rel(cr)
        ph = "C:/Dev/assets/polyhaven_2k/models"
        um = os.path.join(KITS_DIR, "parasol.glb")
        kits["cafe"] = {"table": "/assets/gallinera_table/gallinera_table_2k.gltf", "chair": "/assets/gallinera_chair/gallinera_chair_2k.gltf",
                        "pot": "/assets/potted_plant_01/potted_plant_01_2k.gltf", "umbrella": rel(um) if os.path.exists(um) else None}
        if not os.path.isdir(ph):
            kits.pop("cafe")
    cafes = [[ue_to_three(r)[0], ue_to_three(r)[2], float(r[2])] for r in plan.get("dress", {}).get("prom_cafes", [])]
    cfg = {"W": W, "H": H, "fovV": fov_v, "views": views[:1], "sun": sun, "lift": float(plan["lift_cm"]) / 100.0,
           "ueE": UE_E0 - BB_ORIGIN[0], "ueN": BB_ORIGIN[1] - UE_N0, "burj": ue_to_three(plan.get("burj_cm", [0, 0, 0])), "district": SLUG, "groundMode": None, "groundLayersUrl": None,
           "dtPos": [DT_ORIGIN[0] - BB_ORIGIN[0], 0.0, BB_ORIGIN[1] - DT_ORIGIN[1]], "downtown": SLUG == "businessbay" and "--no-downtown" not in sys.argv, "downtownLod": arg("--downtown-lod", "v3"),
           "facade": facade_tables(), "landmarks": {}, "lmk": landmark_tables(), "useFacade": "--no-facade" not in sys.argv,
           "forceV6": "--v6" in sys.argv, "merge": "--no-merge" not in sys.argv, "ctx": ctx, "kits": kits, "cafes": cafes,
           "towersUrl": None,
           # look (tuned against the Unreal frames with lab_nounreal_tune.py; v1 values in lab_nounreal_render_v1.py)
           "exposure": float(arg("--exposure", 1.9)), "sunInt": float(arg("--sun", 4.6)), "sunRGB": [1.0, 0.88, 0.74],
           "envInt": float(arg("--env", 0.8)), "envGround": [float(x) for x in arg("--env-ground", "0.80,0.62,0.40").split(",")],
           "fill": float(arg("--fill", 2.0)), "fillSky": [float(x) for x in arg("--fill-sky", "0.62,0.60,0.56").split(",")],
           "fillGround": [float(x) for x in arg("--fill-ground", "1.0,0.72,0.42").split(",")],
           "sky": [[float(x) for x in s.split(",")] for s in arg("--sky", "0.02,0.035,0.045;0.10,0.15,0.17;0.55,0.50,0.36;0.45,0.50,0.52").split(";")],
           "splitIbl": "--split-ibl" in sys.argv, "diffInt": float(arg("--diff", 0.3)),
           "hdriSat": float(arg("--hdri-sat", 0.3)), "hdriClamp": float(arg("--hdri-clamp", 8.0)), "hdriYaw": float(arg("--hdri-yaw", 0.0)), "hdriAlign": "--hdri-no-align" not in sys.argv, "showHdri": "--show-hdri" in sys.argv,
           "glassEnv": arg("--glass-env", "bpcem"), "probeBox": None, "probeSky": arg("--probe-sky", "physical"),
           "probe": None, "probeRes": int(arg("--probe-res", 1024)), "probeInt": float(arg("--probe-int", 0.6)), "probeWater": "--probe-water" in sys.argv,
           "ssr": "--no-ssr" not in sys.argv, "ssrOpacity": float(arg("--ssr-opacity", 0.5)), "ssrDist": float(arg("--ssr-dist", 800.0)),
           "ssrThick": float(arg("--ssr-thick", 3.0)), "ssrSteps": int(arg("--ssr-steps", 600)),
           "cafeKits": "--cafe-kits" in sys.argv, "storefronts": None,
           "debugRoles": "--debug-roles" in sys.argv, "filmParity": "--with-json" not in sys.argv, "waterOverride": "--palette-water" not in sys.argv,
           "envGlassGround": [float(x) for x in arg("--env-glass-ground", "0.18,0.30,0.45").split(",")],
           "envTurb": float(arg("--env-turb", 4.0)), "envRayleigh": float(arg("--env-rayleigh", 2.5)),
           "skyTopE": float(arg("--sky-top-e", 0.35)),
           "fogRGB": [float(x) for x in arg("--fog-rgb", "0.40,0.42,0.43").split(",")], "fogNear": float(arg("--fog-near", 6000)),
           "fogFar": float(arg("--fog-far", 45000)), "waterRGB": [float(x) for x in arg("--water-rgb", "0.05,0.17,0.18").split(",")],
           "sat": float(arg("--sat", 1.2)), "glintClamp": float(arg("--glint-clamp", 6.0)), "bloomRadius": float(arg("--bloom-radius", 0.3)),
           "gain": [float(x) for x in arg("--gain", "1.12,1.0,0.88").split(",")],
           "sandDark": [0.60, 0.52, 0.39], "sandLight": [0.74, 0.66, 0.52],
           "burjGlass": _lin("#7f96bd"), "burjBand": _lin("#5f6b80"), "burjSpire": _lin("#c9c9c8"),
           "shadowMap": int(arg("--shadow", 8192)), "shadowSlack": float(arg("--shadow-slack", 0.3)),
           "ao": "--no-ao" not in sys.argv, "aoBlend": float(arg("--ao-blend", 0.5)), "aoScale": float(arg("--ao-scale", 0.8)),
           "aoSamples": int(arg("--ao-samples", 12))}
    if SLUG == "businessbay":
        cfg["groundMode"] = "bb_v1"
    elif ctx:
        cfg["groundMode"] = "ctx"
    else:                                                        # the district's own context_ue.json + water.json, converted once
        gl_json = os.path.join(OUT, "districts", SLUG, "ground_layers.json")
        if not os.path.exists(gl_json) or "--rebuild-ground" in sys.argv:
            print("ground layers:", ground_layers(SLUG, gl_json), flush=True)
        cfg["groundMode"] = "layers"; cfg["groundLayersUrl"] = os.path.relpath(gl_json, ROOT).replace(os.sep, "/")
    if "--no-probe" not in sys.argv and not plan.get("canal_cm"):  # generated plans: probe over the district centre
        bb = plan["district"]["bbox_cm"]; c = plan["district"]["centre_cm"]
        cfg["probe"] = [ue_to_three(c)[0], float(arg("--probe-h", 60.0)), ue_to_three(c)[2]]
        lo, hi = ue_to_three([bb[0], bb[1], 0]), ue_to_three([bb[2], bb[3], 0]); pad = float(arg("--probe-pad", 150.0))
        cfg["probeBox"] = [[min(lo[0], hi[0]) - pad, -1.0, min(lo[2], hi[2]) - pad], [max(lo[0], hi[0]) + pad, float(arg("--probe-top", 700.0)), max(lo[2], hi[2]) + pad]]
    elif "--no-probe" not in sys.argv:
        bb = plan["district"]["bbox_cm"]; c = plan["district"]["centre_cm"]
        if cfg["glassEnv"] == "bpcem":                          # over the canal, at the canal point nearest the district centre
            mid = min(plan["canal_cm"], key=lambda q: (q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2)
            h = float(arg("--probe-h", 60.0))
        else:                                                   # v2 dev probe: the middle of the canal polyline, 40 m up
            mid = plan["canal_cm"][len(plan["canal_cm"]) // 2]; h = float(arg("--probe-h", 40.0))
        cfg["probe"] = [ue_to_three(mid)[0], h, ue_to_three(mid)[2]]
        lo, hi = ue_to_three([bb[0], bb[1], 0]), ue_to_three([bb[2], bb[3], 0])
        pad = float(arg("--probe-pad", 150.0))
        cfg["probeBox"] = [[min(lo[0], hi[0]) - pad, -1.0, min(lo[2], hi[2]) - pad], [max(lo[0], hi[0]) + pad, float(arg("--probe-top", 700.0)), max(lo[2], hi[2]) + pad]]
    if cfg["downtownLod"] != "v5":                             # v3 GLBs carry absolute CE coordinates on their nodes (no origin file)
        cfg["dtPos"] = [-BB_ORIGIN[0], 0.0, BB_ORIGIN[1]]
    for k in ("floor", "band", "mull"):
        if arg("--facade-" + k):
            cfg["facade"][k] = float(arg("--facade-" + k))
    cfg["landmarks"] = cfg["facade"].pop("lmk")
    if "--no-storefronts" not in sys.argv:
        cfg["storefronts"] = storefront_boxes(plan)
    out_name = arg("--out", {"stills": "stills_v2", "seq": "seq_v2_" + arg("--tag", "wide"), "film": "film_v2", "frames": "frames_v2"}[mode])
    out_dir = os.path.join(OUT, out_name); os.makedirs(out_dir, exist_ok=True)
    gpu_args = ["--use-angle=d3d11", "--ignore-gpu-blocklist", "--force_high_performance_gpu", "--gpu-preference=high-performance"]
    srv = serve_root(); base = "http://127.0.0.1:%d/" % srv.server_address[1]
    cfg["base"] = base; cfg["towersUrl"] = base + towers_rel
    if cfg["groundLayersUrl"]:
        cfg["groundLayersUrl"] = base + cfg["groundLayersUrl"]
    if ctx:
        for L in ctx["layers"]:
            L["url"] = base + L["url"]
    hdr = "C:/Dev/assets/polyhaven_2k/hdris_dubai/golden_bay_4k.hdr"
    cfg["hdri"] = base + "__hdri/golden_bay_4k.hdr" if ("--no-hdri" not in sys.argv and os.path.exists(hdr)) else None
    if kits.get("crane"):
        kits["crane"] = base + kits["crane"]
    if kits.get("cafe"):
        c = kits["cafe"]
        for k in ("table", "chair", "pot"):
            c[k] = base + "__ph" + c[k]
        c["umbrella"] = base + c["umbrella"] if c["umbrella"] else None
    timings = {"mode": mode, "district": SLUG, "groundMode": cfg["groundMode"], "W": W, "H": H, "fps": fps, "fov_v_deg": round(fov_v, 2), "towers": towers_rel,
               "ctx": [L["url"].split("/")[-1] for L in ctx["layers"]] if ctx else None, "hdri": bool(cfg["hdri"]),
               "kits": {k: bool(v) for k, v in kits.items()}, "downtown": cfg["downtown"] and cfg["downtownLod"], "ao": cfg["ao"], "merge": cfg["merge"]}
    timings["free_ram_gb_at_start"] = round(wait_for_ram(float(arg("--min-ram", 5.0))), 1)
    t_launch = time.time()
    raw = os.path.join(out_dir, "three_raw.mp4")
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=gpu_args)
        pg = br.new_page(viewport={"width": W, "height": H})

        def handle(route, request):
            u = request.url.split("?")[0]
            if u.endswith("/__nounreal_page.html"):
                route.fulfill(body=PAGE, content_type="text/html")
            elif u.endswith("/__hdri/golden_bay_4k.hdr"):              # the HDRI Unreal's sky light uses (Poly Haven), read-only
                route.fulfill(path="C:/Dev/assets/polyhaven_2k/hdris_dubai/golden_bay_4k.hdr")
            elif "/__ph/assets/" in u:                           # Poly Haven kits, read-only from C:/Dev/assets
                rel = u.split("/__ph/assets/", 1)[1]
                path = os.path.normpath(os.path.join("C:/Dev/assets/polyhaven_2k/models", rel))
                if path.startswith(os.path.normpath("C:/Dev/assets/polyhaven_2k/models")) and os.path.exists(path):
                    route.fulfill(path=path)
                else:
                    route.fulfill(status=404, body="")
            else:
                route.continue_()
        pg.route("**/*", handle)
        fh = {"f": None}

        def sink(pos, s):
            if fh["f"] is None:
                fh["f"] = open(raw, "w+b")
            fh["f"].seek(pos); fh["f"].write(base64.b64decode(s)); return True

        def progress(i, n, el, sh):
            print("  frame %5d / %d  %.1f s  (%.0f ms/frame so far, shadow refits %d)" % (i, n, el, 1000.0 * el / max(1, i), sh), flush=True)
            return True
        fdir = os.path.join(out_dir, "frames") if mode == "frames" else None
        if fdir:
            os.makedirs(fdir, exist_ok=True)

        def frame(i, s):
            open(os.path.join(fdir, "bb_v1.%04d.jpeg" % i), "wb").write(base64.b64decode(s)); return True
        pg.expose_function("__sink", sink); pg.expose_function("__progress", progress); pg.expose_function("__frame", frame)
        pg.add_init_script("window.CFG = %s;" % json.dumps(cfg))
        pg.goto(base + "__nounreal_page.html", wait_until="commit", timeout=300000)   # the title poll below is the real wait
        pg.wait_for_function("document.title === 'ready' || document.title.startsWith('error')", timeout=1200000, polling=1000)
        timings["setup_s"] = round(time.time() - t_launch, 1)
        timings["page_log"] = pg.evaluate("window.__log")
        for line in timings["page_log"]:
            print("  page:", line, flush=True)
        if pg.title() != "ready":
            print(pg.title()); sys.exit(1)
        timings["stat"] = pg.evaluate("window.__stat")
        if mode == "stills":
            timings["frames"] = []
            for v in views:
                t = time.time()
                ms = pg.evaluate("v => window.renderView(v)", v)
                outp = os.path.join(out_dir, "%s.png" % v["name"])
                pg.screenshot(path=outp, clip={"x": 0, "y": 0, "width": W, "height": H})
                timings["frames"].append({"name": v["name"], "film_t": v["film_t"], "render_t": v["render_t"], "render_ms": round(ms, 1),
                                          "frame_wall_s": round(time.time() - t, 3)})
                print("%s  render %.0f ms (incl. shadow refit when the view moved)" % (v["name"], ms), flush=True)
        elif mode == "frames":
            res = pg.evaluate("a => window.renderFrames(a[0], a[1])", [views, float(arg("--jpeg-q", 0.95))])
            timings["film"] = res
            print("rendered %d frames to JPEG in %.1f s: %.0f ms/frame mean, median %.0f, p95 %.0f, max %.0f; shadow refits %d"
                  % (res["frames"], res["total_s"], res["ms_per_frame_mean"], res["ms_median"], res["ms_p95"], res["ms_max"], res["shadow_updates"]), flush=True)
        else:
            bitrate = float(arg("--bitrate", 16e6))
            res = pg.evaluate("a => window.renderFilm(a[0], a[1], a[2])", [views, fps, bitrate])
            if fh["f"]:
                fh["f"].close()
            timings["film"] = res
            print("rendered + encoded %d frames in %.1f s: %.0f ms/frame mean, median %.0f, p95 %.0f, max %.0f; shadow refits %d; %s encoder"
                  % (res["frames"], res["total_s"], res["ms_per_frame_mean"], res["ms_median"], res["ms_p95"], res["ms_max"], res["shadow_updates"], res["hw"]), flush=True)
        br.close()
    timings["total_s"] = round(time.time() - t_launch, 1)
    if mode not in ("stills", "frames"):
        import subprocess
        final = os.path.join(out_dir, "three_%s.mp4" % out_name)
        t = time.time()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-c", "copy", "-movflags", "+faststart", final], check=True)
        timings["remux_s"] = round(time.time() - t, 1)
        if "--grade" in sys.argv:                                # the film's own encode-stage grade (bb_v1_encode.py BB_V1_GRADE)
            t = time.time(); graded = os.path.join(out_dir, "three_%s_graded.mp4" % out_name)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", final, "-vf", GRADE + ",format=yuv420p", "-c:v", "h264_nvenc", "-preset", "p5",
                            "-cq", "19", "-b:v", "0", "-movflags", "+faststart", graded], check=True)
            timings["grade_encode_s"] = round(time.time() - t, 1)
        os.remove(raw)
        pr = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries", "stream=nb_read_packets,width,height,r_frame_rate:format=duration,size",
                             "-of", "json", final], capture_output=True, text=True)
        timings["probe"] = json.loads(pr.stdout)
    timings["mb_samples"] = int(arg("--mb", 1)); timings["shutter"] = float(arg("--shutter", 0.3))
    json.dump(timings, open(os.path.join(out_dir, "timings.json"), "w"), indent=1)
    print("setup %.1f s, total %.1f s -> %s" % (timings["setup_s"], timings["total_s"], out_dir))


if __name__ == "__main__":
    main()
