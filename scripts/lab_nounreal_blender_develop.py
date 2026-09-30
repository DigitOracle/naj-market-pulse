"""LAB (no-Unreal, research only): develop Cycles multilayer EXRs into display PNGs - runs INSIDE Blender (for its bundled
OpenImageIO + PyOpenColorIO and Blender's own OCIO config: AgX / Filmic / ACES view transforms and looks, exactly as Blender).

Launched by lab_nounreal_blender.py (blender -b --factory-startup -P this -- <jobs.json>). Per job, in scene-linear:
  1  light-group re-weight (optional): Combined x (ks*sun + kk*sky + rest) / (sun + sky + rest), ratio from blurred passes
  2  exposure x 2^ev
  3  fog from the Mist pass (three.js Fog 6-45 km, colour 0.40 0.42 0.43 x 1.9/0.6 in tone-mapper input units x fog_k)
  4  the film's PPV warm gain and saturation (as the three.js v2 gain pass: 1.12 1.0 0.88, sat 1.2)
  5  bloom (threshold / strength, UnrealBloomPass-like pyramid of box blurs)
  6  OCIO view transform (+ look), un-premultiplied; the sky plate = the three.js v2 dome through three's own ACES fit and
     exposure (so the sky is identical in both renderers and dE compares the lit scene), alpha-over in display space
  7  vignette 0.35 (three.js / Unreal camera)
Writes 8-bit PNGs (optionally downscaled). Research only.
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as OCIO

JOBS = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
_OCIO = {}
_EXR = {}


def ocio_cpu(view, look):
    k = (view, look)
    if k not in _OCIO:
        path = os.path.join(bpy.utils.resource_path("LOCAL"), "datafiles", "colormanagement", "config.ocio")
        cfg = OCIO.Config.CreateFromFile(path)
        src = cfg.getColorSpace("scene_linear").getName()
        lvp = OCIO.LegacyViewingPipeline()
        lvp.setDisplayViewTransform(OCIO.DisplayViewTransform(src=src, display="sRGB", view=view))
        if look and look != "None":
            lvp.setLooksOverrideEnabled(True); lvp.setLooksOverride(look)
        _OCIO[k] = lvp.getProcessor(cfg, cfg.getCurrentContext()).getDefaultCPUProcessor()
    return _OCIO[k]


def read_exr(path, scale):
    k = (path, scale)
    if k in _EXR:
        return _EXR[k]
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise RuntimeError("cannot open " + path + ": " + oiio.geterror())
    names, planes, i = [], [], 0                           # Blender 5.x writes one EXR part (subimage) per pass
    while inp.seek_subimage(i, 0):
        spec = inp.spec()
        px = np.asarray(inp.read_image(i, 0, 0, spec.nchannels, "float"), dtype=np.float32).reshape(spec.height, spec.width, spec.nchannels)
        names += list(spec.channelnames); planes.append(px); i += 1
    inp.close()
    px = np.concatenate(planes, axis=-1)
    if scale != 1:
        f = int(round(1 / scale)); h, w = (px.shape[0] // f) * f, (px.shape[1] // f) * f
        px = px[:h, :w].reshape(h // f, f, w // f, f, -1).mean(axis=(1, 3))

    def ch(pass_name, comps):
        out = []
        for c in comps:
            hits = [i for i, n in enumerate(names) if n.endswith("." + pass_name + "." + c) or n == pass_name + "." + c]
            if not hits:
                return None
            out.append(px[:, :, hits[0]])
        return np.stack(out, -1)
    d = {"rgba": ch("Combined", "RGBA"), "mist": ch("Mist", "Z") if ch("Mist", "Z") is not None else ch("Mist", "V"),
         "sun": ch("Combined_sun", "RGB"), "sky": ch("Combined_sky", "RGB"), "noisy": ch("Noisy Image", "RGB"),
         "dif_dir": ch("Diffuse Direct", "RGB"), "dif_ind": ch("Diffuse Indirect", "RGB"), "dif_col": ch("Diffuse Color", "RGB"), "names": names}
    if d["mist"] is None:
        mi = [i for i, n in enumerate(names) if ".Mist." in n or n.startswith("Mist")]
        d["mist"] = px[:, :, mi[:1]] if mi else None
    _EXR.clear(); _EXR[k] = d
    return d


def box_blur(a, r):
    if r < 1:
        return a
    for ax in (0, 1):
        c = np.cumsum(np.pad(a, [(r + 1, r) if i == ax else (0, 0) for i in range(a.ndim)], mode="edge"), axis=ax, dtype=np.float32)
        n = a.shape[ax]
        hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=ax); lo = np.take(c, np.arange(0, n), axis=ax)
        a = (hi - lo) / (2 * r + 1)
    return a


def aces_three(c, exposure):                           # three.js r169 ACESFilmicToneMapping + LinearTosRGB
    c = c * (exposure / 0.6)
    A = np.array([[0.59719, 0.07600, 0.02840], [0.35458, 0.90834, 0.13383], [0.04823, 0.01566, 0.83777]], np.float32)
    B = np.array([[1.60475, -0.10208, -0.00327], [-0.53108, 1.10813, -0.07276], [-0.07367, -0.00605, 1.07602]], np.float32)
    v = c @ A
    v = (v * (v + 0.0245786) - 0.000090537) / (v * (0.983729 * v + 0.4329510) + 0.238081)
    v = np.clip(v @ B, 0, 1)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t)


def dome_display(cam, h, w, P):
    """lab_nounreal_render.py's sky dome shader, camera-exact, through its gain pass + ACES(exposure) + sRGB"""
    pos, tgt = np.array(cam["pos"], float), np.array(cam["tgt"], float)
    f = tgt - pos; f /= np.linalg.norm(f)
    r = np.cross(f, [0.0, 1.0, 0.0]); r /= np.linalg.norm(r); u = np.cross(r, f)
    tv = math.tan(math.radians(cam["fov_v"]) / 2); th = tv * w / h
    ny = 1 - (np.arange(h) + 0.5) / h * 2; nx = (np.arange(w) + 0.5) / w * 2 - 1
    d = f[None, None, :] + nx[None, :, None] * th * r[None, None, :] + ny[:, None, None] * tv * u[None, None, :]
    e = d[..., 1] / np.linalg.norm(d, axis=-1)
    top, mid, hor, low = [np.array(c, np.float32) for c in P["sky"]]
    mix = lambda a, b, t: a + (b - a) * t[..., None]
    c = np.where((e < 0)[..., None], mix(hor, low, smoothstep(0, 0.04, -e)),
                 np.where((e < 0.07)[..., None], mix(hor, mid, smoothstep(0, 0.07, e)), mix(mid, top, smoothstep(0.07, P["sky_top_e"], e))))
    g = c * np.array(P["three_gain"], np.float32); y = g @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    g = np.maximum(y[..., None] + (g - y[..., None]) * P["three_sat"], 0)
    return aces_three(g.astype(np.float32), P["three_exposure"])


def develop(job):
    P = job["params"]; sc = job.get("scale", 1.0)
    d = read_exr(job["exr"], sc)
    rgba = d["rgba"]; C = rgba[..., :3].copy(); a = np.clip(rgba[..., 3:4], 0, 1)
    ks = float(P.get("k_sun", 1.0)) * np.array(P.get("sun_tint", [1.0, 1.0, 1.0]), np.float32)
    kk = float(P.get("k_sky", 1.0)) * np.array(P.get("sky_tint", [1.0, 1.0, 1.0]), np.float32)    # light groups are linear per channel
    if (np.abs(ks - 1).max() > 1e-6 or np.abs(kk - 1).max() > 1e-6) and d["sun"] is not None and d["sky"] is not None:
        rb = max(1, int(4 * sc)); S = box_blur(d["sun"], rb); K = box_blur(d["sky"], rb); Cb = box_blur(C, rb)
        E = np.maximum(box_blur(d["noisy"], rb) - S - K, 0) if d["noisy"] is not None else np.maximum(Cb - S - K, 0)
        C = C * (ks * S + kk * K + E + 1e-5) / (S + K + E + 1e-5)
    C *= 2.0 ** float(P.get("ev", 0.0))
    if d["mist"] is not None and P.get("fog_k", 1.0) > 0:
        m = np.clip(d["mist"][..., :1], 0, 1)
        fog = np.array(P.get("fog_rgb", [0.40, 0.42, 0.43]), np.float32) * (1.9 / 0.6) * float(P.get("fog_k", 1.0))
        C = C * (1 - m) + fog * m * a
    g = np.array(P.get("gain", [1.12, 1.0, 0.88]), np.float32); C = C * g
    y = C @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    C = np.maximum(y[..., None] + (C - y[..., None]) * float(P.get("sat", 1.2)), 0)
    bs = float(P.get("bloom", 0.0))
    if bs > 0:
        y = C @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        br = C * (np.maximum(y - P.get("bloom_thr", 3.0), 0) / np.maximum(y, 1e-4))[..., None]
        acc = np.zeros_like(C); wpx = C.shape[1] / 1080.0
        for i, fct in enumerate([1.0, 0.8, 0.6, 0.4, 0.2]):
            rad = max(1, int(round(3 * 2 ** i * wpx)))
            acc += (fct + (1.2 - 2 * fct) * 0.45) * box_blur(box_blur(br, rad), rad)
        C = C + bs * acc
    Cu = np.ascontiguousarray(np.where(a > 1e-4, C / np.maximum(a, 1e-4), 0).astype(np.float32))
    ocio_cpu(P.get("view", "AgX"), P.get("look", "None")).applyRGB(Cu)
    D = np.clip(Cu, 0, 1)
    h, w = D.shape[:2]
    if job.get("cam"):
        D = D * a + dome_display(job["cam"], h, w, P) * (1 - a)
    vg = float(P.get("vignette", 0.35))
    if vg > 0:
        yy = ((np.arange(h) + 0.5) / h - 0.5) * 1.2; xx = (np.arange(w) + 0.5) / w - 0.5
        L = np.sqrt(yy[:, None] ** 2 + xx[None, :] ** 2)
        v = 1 - smoothstep(0.25, 0.85, L)
        D = D * (1 + (v - 1) * vg)[..., None]
    out = np.clip(np.round(D * 255), 0, 255).astype(np.uint8)
    os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
    o = oiio.ImageOutput.create(job["out"]); o.open(job["out"], oiio.ImageSpec(w, h, 3, "uint8")); o.write_image(out); o.close()


def analyze(job):
    """where the light in ground shadows comes from (render-time strengths, k = 1): pixels of the lower half whose diffuse
    colour is sand / paving (bright, warm-neutral albedo) split by the sun light group into sunlit and shadowed. In shadow
    the sun group can only arrive by bouncing, so sun_group / (sun_group + sky_group) there is the true-GI share."""
    d = read_exr(job["exr"], 1.0); h = d["rgba"].shape[0]
    lo = slice(h // 2, h)
    dc, S, K = d["dif_col"][lo], d["sun"][lo], d["sky"][lo]
    C = d["rgba"][lo][..., :3]; DD, DI = d["dif_dir"][lo], d["dif_ind"][lo]
    L = lambda x: x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    alb = L(dc); sand = (alb > 0.35) & (dc[..., 0] >= dc[..., 2]) & (d["rgba"][lo][..., 3] > 0.99)
    sl = L(S); thr = np.percentile(sl[sand], 90) if sand.any() else 1.0
    lit, sh = sand & (sl > 0.5 * thr), sand & (sl < 0.03 * thr)
    m = lambda a, k: [round(float(x), 4) for x in a[k].mean(0)] if k.any() else None
    out = {"name": os.path.basename(job["exr"]), "sand_px": int(sand.sum()), "lit_px": int(lit.sum()), "shadow_px": int(sh.sum()),
           "lit_rgb": m(C, lit), "shadow_rgb": m(C, sh), "shadow_over_lit": round(float(L(C[sh]).mean() / L(C[lit]).mean()), 4) if sh.any() and lit.any() else None,
           "shadow_sun_bounce_rgb": m(S, sh), "shadow_sky_rgb": m(K, sh),
           "shadow_bounce_share": round(float(L(S[sh]).mean() / (L(S[sh]).mean() + L(K[sh]).mean())), 4) if sh.any() else None,
           "shadow_diffuse_indirect_share": round(float(L(DI[sh]).mean() / (L(DI[sh]).mean() + L(DD[sh]).mean())), 4) if sh.any() else None,
           "lit_diffuse_indirect_share": round(float(L(DI[lit]).mean() / (L(DI[lit]).mean() + L(DD[lit]).mean())), 4) if lit.any() else None}
    json.dump(out, open(job["out"], "w"), indent=1); print("[develop] analysis", json.dumps(out), flush=True)


t0 = time.time()
for i, j in enumerate(JOBS["jobs"]):
    try:
        if j.get("analyze"):
            analyze(j); continue
        develop(j)
    except Exception as e:
        import traceback
        traceback.print_exc(); print("[develop] FAILED", j.get("out"), e, flush=True)
    if i == 0:
        print("[develop] channels:", _EXR and list(_EXR.values())[0]["names"], flush=True)
print("[develop] %d jobs in %.1f s" % (len(JOBS["jobs"]), time.time() - t0), flush=True)
