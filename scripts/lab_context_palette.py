"""LAB (context / scenery, research only): ONE material palette for the ground and the street dressing, shared by
CityEngine (the CGA rule is generated from it), the web GLBs (materials re-applied from it by name) and Unreal (the
values ARE Unreal's - copied from the scripts that build the Business Bay level today, never invented where Unreal
has a value).

Writes data/lab/context/<slug>/:
  context_palette.json   role -> linear rgb, roughness, metallic, UE specular (+ the glTF KHR_materials_specular
                         equivalent), emissive, the two-tone noise recipe Unreal uses (dark, light, noise scale),
                         stack height above land level, draw order, and where every number came from
  textures/ctx_<role>.jpg tileable base-colour tiles baked from the SAME recipe Unreal's material graph evaluates
                         (lerp(dark, light, noise(world * scale))) - so the web and CityEngine get Unreal's variation,
                         not a flat colour. sRGB-encoded; world-projected with tile_m metres per repeat.

Sources (read, never run, never edited):
  ue_bb_v1_build.py   ground() looks (asphalt, pavement, parking, grass, pitch, pool, construction), M() specs (kerb,
                      markings, plots, podium, quay, lamp_body, lamp_head, planter, rail_steel), promenade, water_v1,
                      M_BB1_Sand2 - the CURRENT Business Bay level (L_BB_v1, 29 Sep 2026)
  ue_context_layer.py ORDER (stack heights z_cm, the older flat colours kept as "ue_context_layer_rgb")
  bb_v1_prep.py       LIFT_CM 120 (land above canal), WATER_Z -90 cm; OBJ z of kerb 14, markings 10, promenade 6,
                      podium 4, plots 1 cm
  ue_sobha_pbr.py     PALETTE (building roles, carried for completeness so one file holds every engine colour)
  ue_sobha_ground.py  M_SobhaSand / M_SobhaWater (the city-wide recipe, recorded as the alternative)
  foliage             Unreal draws textured Sketchfab / Poly Haven plants (ue_bb_v0_build KITS); no scalar colour
                      exists, so the leaf / bark colours are the alpha-masked linear MEAN of those same textures
                      (C:/Dev/assets, read-only). Roughness for foliage is not Unreal's (it comes from texture maps).

  python scripts/lab_context_palette.py [businessbay]
"""
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ASSETS = "C:/Dev/assets"
SLUG = (sys.argv[1:] or ["businessbay"])[0]
OUT = os.path.join(ROOT, "data", "lab", "context", SLUG)
TEX = os.path.join(OUT, "textures")

V1 = "ue_bb_v1_build.py"
# ---------------------------------------------------------------------------------------------------------------------
# GROUND roles. y_m = height above LAND level (the v5 buildings stand at y = 0): Unreal's own stack (ue_context_layer
# ORDER z_cm and the bb_v1 OBJ z values), with L_BB_v1's lift folded in: sand plane 1.20 m below the land (LIFT_CM),
# canal water at -0.90 (WATER_Z), inland water at sand + 0.10 (place_mesh gz + 10).
# noise = (dark rgb, light rgb, UE Noise scale per cm) exactly as passed to flat_or_noise().
GROUND = {
    #  role            dark                  light                 scale/cm  rough spec  y_m     order src
    "sand":         ((0.60, 0.52, 0.39), (0.74, 0.66, 0.52), 0.00005, 0.95, 0.30, -1.20,   0, V1 + " environment(): M_BB1_Sand2 (neutral beige)"),
    "water":        ((0.02, 0.16, 0.22), None,               None,    0.07, 1.00, -1.10,   1, V1 + " water_v1(): M_BB1_Water (inland water: city mesh at gz + 10 cm)"),
    "canal":        ((0.02, 0.16, 0.22), None,               None,    0.07, 1.00, -0.90,   2, V1 + " water_v1() on v1_canal_water.obj (WATER_Z = -90 cm)"),
    "quay":         ((0.66, 0.58, 0.45), None,               None,    0.80, 0.35, None,    3, V1 + " M('quay') #CFC6B4 stone face; mesh keeps its own z (-1.5..+0.08 m)"),
    "plot":         ((0.58, 0.53, 0.44), None,               None,    0.90, 0.30, 0.01,    4, V1 + " M('plots') paved plots, v1_plots.obj z 1 cm"),
    "construction": ((0.50, 0.46, 0.38), (0.60, 0.56, 0.47), 0.001,   0.95, 0.20, 0.02,    5, V1 + " ground() looks['construction']; z 2 cm (ue_context_layer)"),
    "grass":        ((0.12, 0.28, 0.07), (0.22, 0.40, 0.10), 0.0009,  0.90, 0.20, 0.03,    6, V1 + " ground() looks['grass']; z 3 cm"),
    "pitch":        ((0.10, 0.30, 0.08), (0.14, 0.36, 0.10), 0.001,   0.85, 0.20, 0.035,   7, V1 + " ground() looks['pitch']; z 3.5 cm"),
    "parking":      ((0.18, 0.18, 0.185), (0.24, 0.24, 0.245), 0.0009, 0.85, 0.30, 0.04,   8, V1 + " ground() looks['parking']; z 4 cm"),
    "podium":       ((0.52, 0.47, 0.39), None,               None,    0.85, 0.30, 0.042,   9, V1 + " M('podium'), v1_podium.obj z 4 cm (+2 mm so it never ties with parking)"),
    "pavement":     ((0.52, 0.52, 0.50), (0.64, 0.64, 0.62), 0.0012,  0.90, 0.30, 0.05,   10, V1 + " ground() looks['pavement'] (light stone; the ambientCG paving read black); z 5 cm"),
    "promenade":    ((0.24, 0.22, 0.20), (0.38, 0.36, 0.33), 0.006,   0.85, 0.35, 0.06,   11, V1 + " M('promenade') grey checker, v1_promenade.obj z 6 cm"),
    "asphalt":      ((0.16, 0.16, 0.165), (0.22, 0.22, 0.225), 0.0007, 0.85, 0.30, 0.07,  12, V1 + " ground() looks['asphalt'] (mid-grey road); z 7 cm"),
    "pool":         ((0.05, 0.35, 0.45), (0.08, 0.45, 0.55), 0.001,   0.05, 1.00, 0.08,   13, V1 + " ground() looks['pool']; z 8 cm"),
    "marking_white": ((0.85, 0.85, 0.83), None,              None,    0.60, 0.40, 0.10,   14, V1 + " M('mark_white'), v1_mark_white.obj z 10 cm"),
    "marking_yellow": ((0.85, 0.62, 0.08), None,             None,    0.60, 0.40, 0.10,   15, V1 + " M('mark_yellow'), v1_mark_yellow.obj z 10 cm"),
    "kerb":         ((0.70, 0.70, 0.68), None,               None,    0.80, 0.35, 0.14,   16, V1 + " M('kerb'), v1_kerb.obj z 14 cm (top face only, as in Unreal)"),
    "hoarding":     ((0.82, 0.82, 0.80), None,               None,    0.70, 0.35, None,   17, V1 + " M('hoarding') site hoardings, v1_hoarding.obj (2.4 m walls, keep their own z)"),
    "rail_steel":   ((0.55, 0.56, 0.58), None,               None,    0.30, 0.50, None,   18, V1 + " M('rail_steel') quay handrail band, v1_rail_steel.obj"),
    "rail_glass":   ((0.40, 0.41, 0.43), None,               None,    0.30, 0.50, None,   19, V1 + " simple_mat('M_BB1_rail_glass', opacity 0.3) quay balustrade, v1_rail_glass.obj"),
}
GROUND_METAL = {"rail_steel": 0.9, "rail_glass": 0.9}          # the M() / simple_mat metallic of those two
GROUND_OPACITY = {"rail_glass": 0.3}
# the older flat colours ue_context_layer.py writes into context_ue.json (what a level WITHOUT the v1 looks shows)
CTX_LAYER_RGB = {"water": (0.02, 0.07, 0.09), "sand": (0.70, 0.62, 0.46), "construction": (0.60, 0.54, 0.44), "grass": (0.17, 0.30, 0.10),
                 "pitch": (0.14, 0.34, 0.12), "parking": (0.16, 0.16, 0.16), "pavement": (0.60, 0.58, 0.54), "asphalt": (0.085, 0.085, 0.09),
                 "pool": (0.05, 0.35, 0.45)}

# DRESSING roles (materials of the instanced assets). rgb None -> the asset keeps its own texture (Esri street kit).
PROPS = {
    #  role                rgb                  rough metal spec  emissive src
    "prop_lamp_body":   ((0.30, 0.31, 0.32), 0.35, 0.90, 0.50, 0.0, V1 + " M('lamp_body') - the primitive double-arm lamp (bb_v1_prep prop_meshes)"),
    "prop_lamp_head":   ((1.00, 0.95, 0.85), 0.30, 0.00, 0.50, 6.0, V1 + " M('lamp_head') emissive x6 LED head"),
    "prop_planter":     ((0.62, 0.60, 0.56), 0.80, 0.00, 0.30, 0.0, V1 + " M('planter')"),
    "prop_bollard":     ((0.30, 0.31, 0.32), 0.35, 0.90, 0.50, 0.0, "no Unreal value (bollards dropped in v1) - borrows lamp_body"),
    "prop_bench":       (None,               0.60, 0.00, 0.50, 0.0, "Esri Park_Bench_1 LOD1 texture; Unreal uses Sketchfab modern_bench (own textures)"),
    "prop_bin":         (None,               0.55, 0.00, 0.50, 0.0, "Esri Trash_Bin_1 LOD1 texture; Unreal v1 has no bins (kit dropped)"),
    "prop_shelter":     (None,               0.50, 0.00, 0.50, 0.0, "Esri Bus_Stop_2 LOD1 texture; Unreal uses Sketchfab modern_bus_stop_shelter"),
    # cars: Esri's car textures are red, made to be TINTED (material extras ESRI_externalColorMixMode = "tint"); the assets
    # carry a luminance version of the texture and these paints. No Unreal value exists (L_BB_v1 draws no cars,
    # BB_V1_VEHICLES=0; v0 used Sketchfab cars in their own paint) - a Dubai fleet mix, props_ue colour index % 5.
    "prop_car_0":       ((0.80, 0.80, 0.78), 0.30, 0.40, 0.50, 0.0, "car paint white (no Unreal value)"),
    "prop_car_1":       ((0.50, 0.51, 0.53), 0.30, 0.60, 0.50, 0.0, "car paint silver (no Unreal value)"),
    "prop_car_2":       ((0.025, 0.025, 0.03), 0.25, 0.40, 0.50, 0.0, "car paint black (no Unreal value)"),
    "prop_car_3":       ((0.72, 0.70, 0.64), 0.30, 0.40, 0.50, 0.0, "car paint pearl / champagne (no Unreal value)"),
    "prop_car_4":       ((0.09, 0.11, 0.15), 0.30, 0.50, 0.50, 0.0, "car paint dark blue-grey (no Unreal value)"),
    # the promenade cafes of L_BB_v1 (bistro table + 4 chairs + parasol + 2 potted plants per cluster). Unreal draws Poly Haven
    # gallinera / round_wooden tables and chairs and a Sketchfab parasol, all textured: colours are Unreal's texture means
    # where the texture is on disk, else chosen (and said so)
    "prop_cafe_table":  ((0.10, 0.07, 0.05), 0.60, 0.00, 0.50, 0.0, "dark wood - no scalar in Unreal (Poly Haven gallinera_table / round_wooden_table_01 textures, not on disk)"),
    "prop_cafe_chair":  ((0.03, 0.03, 0.035), 0.50, 0.60, 0.50, 0.0, "black metal - no scalar in Unreal (Poly Haven gallinera_chair / bar_chair_round_01)"),
    "prop_umbrella":    ((0.78, 0.76, 0.70), 0.85, 0.00, 0.40, 0.0,
                         "off-white as the parasols read in Unreal's film (v3_close_cafe.png); the Sketchfab fabric base colour is a flat 0.11 linear grey lit by its own emissive map"),
    "prop_pot":         ((0.36, 0.16, 0.10), 0.80, 0.00, 0.30, 0.0, "ue_sobha_pbr PALETTE['terracotta'] (Unreal draws Poly Haven planter_pot_clay)"),
    # construction sites: Esri Transportation/StreetScene LOD1 kit keeps its own textures (Unreal: Sketchfab construction kit)
    "prop_site":        (None,               0.70, 0.00, 0.40, 0.0, "Esri Tower_Crane / Cargo_Box / Dumptruck / Backhoe / Bobcat / Jersey_Barrier LOD1 textures"),
}
# foliage: colour sampled from the textures Unreal draws; (texture, alpha mask or None, rough, src)
FOLIAGE = {
    "veg_palm_frond":  ("sketchfab_palms/date_palm_evolveduk/textures/date_palm_leaf.png", "sketchfab_palms/date_palm_evolveduk/textures/date_palm_leaf_alpha.png", 0.80,
                        "mean of Unreal's date palm leaf texture (Sketchfab date_palm, KITS['date_palm'])"),
    "veg_palm_trunk":  ("sketchfab_palms/date_palm_evolveduk/textures/barkpalm.png", None, 0.90, "mean of Unreal's date palm bark texture"),
    "veg_fan_frond":   ("sketchfab_palms/washingtonia-robusta-palm-02/textures/Washingtonia_leaf_diffuse.jpg",
                        "sketchfab_palms/washingtonia-robusta-palm-02/textures/Washingtonia_leaf_opacity.jpg", 0.75,
                        "mean of Unreal's Washingtonia leaf texture (KITS['washingtonia'])"),
    "veg_tree_crown":  ("sketchfab_vegetation/acacia-tree/textures/acacia branch.png", "sketchfab_vegetation/acacia-tree/textures/acacia_branch_alpha.png", 0.85,
                        "mean of Unreal's acacia branch texture (KITS['shade_tree'] first folder)"),
    "veg_tree_trunk":  ("sketchfab_vegetation/acacia-tree/textures/bark05.png", None, 0.90, "mean of Unreal's acacia bark texture"),
    "veg_shrub":       ("polyhaven_2k/shrub_01/textures", None, 0.85, "mean of Unreal's Poly Haven shrub_01 diffuse (KITS['hedge'])"),
}
# buildings (ue_sobha_pbr.PALETTE) - carried so one file holds every colour both engines use; the facade lab owns these
SOBHA_PBR = {
    "white": ((0.80, 0.80, 0.78), 0.55, 0.0, 0.5), "pale_concrete": ((0.62, 0.60, 0.56), 0.80, 0.0, 0.4), "warm_render": ((0.62, 0.52, 0.40), 0.85, 0.0, 0.4),
    "cream_render": ((0.72, 0.66, 0.54), 0.85, 0.0, 0.4), "dark_bronze": ((0.18, 0.12, 0.08), 0.40, 0.7, 0.5), "bronze": ((0.35, 0.22, 0.12), 0.35, 0.8, 0.5),
    "gold": ((0.75, 0.55, 0.25), 0.30, 1.0, 0.5), "blue_glass": ((0.14, 0.28, 0.46), 0.06, 0.6, 1.0), "deep_blue_glass": ((0.07, 0.18, 0.34), 0.05, 0.6, 1.0),
    "clear_glass": ((0.32, 0.40, 0.44), 0.05, 0.5, 1.0), "bronze_glass": ((0.34, 0.24, 0.15), 0.06, 0.5, 1.0), "tinted_glass": ((0.18, 0.24, 0.28), 0.08, 0.4, 1.0),
    "akoya_glass": ((0.20, 0.30, 0.40), 0.06, 0.5, 1.0), "dark_glass": ((0.08, 0.10, 0.12), 0.06, 0.5, 1.0), "sandstone": ((0.66, 0.55, 0.40), 0.85, 0.0, 0.4),
    "dark": ((0.10, 0.10, 0.10), 0.60, 0.0, 0.4), "roof": ((0.32, 0.32, 0.31), 0.90, 0.0, 0.3), "champagne_glass": ((0.46, 0.36, 0.22), 0.05, 0.7, 1.0),
    "ivory_stone": ((0.78, 0.72, 0.60), 0.70, 0.0, 0.45), "rose_bronze": ((0.42, 0.26, 0.18), 0.30, 0.85, 0.6), "terracotta": ((0.36, 0.16, 0.10), 0.80, 0.0, 0.30),
    "concrete_frame": ((0.34, 0.33, 0.31), 0.92, 0.0, 0.25), "scaffold_glass": ((0.07, 0.13, 0.16), 0.20, 0.3, 0.8),
}
TEX_PX = 512


def srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def lin(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))


def hexs(rgb_lin):
    s = srgb(rgb_lin)
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in s)


def gltf_specular(ue_spec):
    """UE Specular (F0 = 0.08 * spec) -> KHR_materials_specular (F0 = 0.04 * factor * colour, ior 1.5).
    factor <= 1 by the spec; above it the colour factor carries the rest."""
    f = 2.0 * float(ue_spec)
    return (round(f, 4), [1.0, 1.0, 1.0]) if f <= 1.0 else (1.0, [round(f, 4)] * 3)


def fbm_tile(n, cycles, seed, levels=3):
    """tileable fractal noise, n x n, `cycles` base features per tile, `levels` octaves (UE Noise 'Levels') -> 0..1 with
    UE-like statistics (mean 0.5, sd ~0.17)."""
    rng = np.random.default_rng(seed)
    fy = np.fft.fftfreq(n)[:, None] * n
    fx = np.fft.fftfreq(n)[None, :] * n
    r = np.sqrt(fx * fx + fy * fy)
    acc = np.zeros((n, n))
    for o in range(levels):
        f0 = cycles * (2 ** o)
        band = np.exp(-((r - f0) ** 2) / (2 * (0.45 * f0 + 0.5) ** 2))
        wn = np.fft.fft2(rng.standard_normal((n, n)))
        layer = np.real(np.fft.ifft2(wn * band))
        layer /= layer.std() + 1e-12
        acc += layer * (0.5 ** o)
    acc = (acc - acc.mean()) / (acc.std() + 1e-12)
    return np.clip(0.5 + 0.17 * acc, 0.0, 1.0)


def bake(role, dark, light, scale_cm, seed):
    per_m = scale_cm * 100.0                     # UE Noise: world position (cm) * scale -> one cell per 1/scale cm
    tile_m = float(min(400.0, max(24.0, 4.0 / per_m)))
    cycles = max(1, int(round(tile_m * per_m)))
    t = fbm_tile(TEX_PX, cycles, seed)[..., None]
    col = np.asarray(dark)[None, None, :] * (1 - t) + np.asarray(light)[None, None, :] * t     # lerp in LINEAR, as the UE graph does
    img = (srgb(col) * 255.0 + 0.5).astype(np.uint8)
    os.makedirs(TEX, exist_ok=True)
    p = os.path.join(TEX, "ctx_%s.jpg" % role)
    Image.fromarray(img, "RGB").save(p, quality=86, optimize=True)
    mean_lin = col.reshape(-1, 3).mean(0)
    return {"texture": "textures/ctx_%s.jpg" % role, "tile_m": round(tile_m, 2), "cycles_per_tile": cycles, "px": TEX_PX,
            "bytes": os.path.getsize(p)}, mean_lin


def texture_mean(tex, alpha=None):
    p = os.path.join(ASSETS, tex)
    if os.path.isdir(p):                          # Poly Haven folder: the diffuse map
        c = [f for f in os.listdir(p) if "diff" in f.lower() and f.lower().endswith((".jpg", ".png"))]
        if not c:
            return None
        p = os.path.join(p, sorted(c)[0])
    if not os.path.exists(p):
        return None
    im = Image.open(p).convert("RGBA").resize((256, 256), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float64) / 255.0
    w = a[..., 3]
    if alpha and os.path.exists(os.path.join(ASSETS, alpha)):
        w = np.asarray(Image.open(os.path.join(ASSETS, alpha)).convert("L").resize((256, 256), Image.BILINEAR), dtype=np.float64) / 255.0
    w = (w > 0.5).astype(np.float64)
    if w.sum() < 10:
        w = np.ones_like(w)
    rgb_l = lin(a[..., :3])
    return [float((rgb_l[..., k] * w).sum() / w.sum()) for k in range(3)], os.path.relpath(p, ASSETS).replace("\\", "/")


def entry(rgb, rough, metal, spec, src, **kw):
    sf, sc = gltf_specular(spec)
    e = {"rgb": [round(float(v), 4) for v in rgb] if rgb is not None else None, "hex_srgb": hexs(rgb) if rgb is not None else None,
         "roughness": rough, "metallic": metal, "specular_ue": spec,
         "gltf": {"KHR_materials_specular": {"specularFactor": sf, "specularColorFactor": sc}}, "source": src}
    e.update(kw)
    return e


def main():
    os.makedirs(OUT, exist_ok=True)
    roles = {}
    for k, (role, (dark, light, scale, rough, spec, y, order, src)) in enumerate(GROUND.items()):
        kw = {"kind": "ground", "material": "ctx_" + role, "y_m": y, "draw_order": order}
        rgb = dark
        if light is not None:
            tex, mean_lin = bake(role, dark, light, scale, 1000 + k)
            kw["noise"] = {"dark": list(dark), "light": list(light), "ue_noise_scale_per_cm": scale, "ue_levels": 3,
                           "graph": "BaseColor = lerp(dark, light, Noise(WorldPosition * scale)) (flat_or_noise in ue_bb_v0_build.py)"}
            kw.update(tex)
            rgb = mean_lin
        if role in CTX_LAYER_RGB:
            kw["ue_context_layer_rgb"] = list(CTX_LAYER_RGB[role])
        if role in ("water", "canal"):
            kw["ue_extra"] = "subtle ripple normal: ambientCG Concrete030 normal, world XY / 900 cm, panner (0.015, 0.01), lerp 0.22 to flat"
        if role in GROUND_OPACITY:
            kw["opacity"] = GROUND_OPACITY[role]
        roles["ctx_" + role] = entry(rgb, rough, GROUND_METAL.get(role, 0.0), spec, src, **kw)
    for role, (rgb, rough, metal, spec, em, src) in PROPS.items():
        kw = {"kind": "prop", "material": role}
        if isinstance(rgb, str):                                 # a texture Unreal draws: its mean colour
            r = texture_mean(rgb)
            kw["sampled_from"] = "C:/Dev/assets/" + r[1] if r else None
            rgb = r[0] if r else (0.85, 0.84, 0.80)
        if em:
            kw["emissive_rgb"] = [round(v * em, 4) for v in rgb]
            kw["emissive_ue_multiplier"] = em
            kw["gltf"] = None                    # filled below
        e = entry(rgb, rough, metal, spec, src, **kw)
        if em:
            e["gltf"] = {"KHR_materials_specular": dict(zip(("specularFactor", "specularColorFactor"), gltf_specular(spec))),
                         "emissiveFactor": [1.0, 0.95, 0.85], "KHR_materials_emissive_strength": {"emissiveStrength": em}}
        roles[role] = e
    for role, (tex, alpha, rough, src) in FOLIAGE.items():
        r = texture_mean(tex, alpha)
        if r is None:
            print("  %s: texture missing (%s) - grey fallback" % (role, tex))
            rgb, used = (0.2, 0.25, 0.12), None
        else:
            rgb, used = r
        roles[role] = entry(rgb, rough, 0.0, 0.5, src, kind="foliage", material=role, sampled_from="C:/Dev/assets/" + used if used else None,
                            note="Unreal: two-sided foliage, masked by the texture alpha; here an opaque low-poly crown takes the mean colour")
    pal = {
        "schema": "najma.context_palette/1",
        "slug": SLUG, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "research_only": True,
        "colour_space": "rgb = LINEAR (Unreal LinearColor / glTF baseColorFactor). hex_srgb = the same colour sRGB-encoded (CGA color() takes sRGB).",
        "specular": "specular_ue = Unreal's Specular input (F0 = 0.08 x spec). gltf.KHR_materials_specular is its equivalent (F0 = 0.04 x factor x colour).",
        "heights": "y_m = metres above LAND level (v5 building base y = 0). Unreal L_BB_v1 lifts land 1.20 m above the sand plane; the same offsets here.",
        "frame": "local v5 frame of data/ce/<slug>/origin_v5.json: CE-frame = vertex + origin_ce_xyz (x = easting, y = up, z = -northing)",
        "unreal_frame": "UE cm: X = easting - 328289, Y = 2784598 - northing (ue_greenery / ue_props / ue_furniture)",
        "roles": roles,
        "species": {
            "date_palm":   {"asset": "ESRI.lib Webstyles/Vegetation/LowPoly/PhoenixDactylifera.glb", "target_h_m": 9.5, "materials": ["veg_palm_frond", "veg_palm_trunk"], "ue": "ue_sobha_foliage SPECIES palm[0] / KITS date_palm 9.5 m"},
            "washingtonia": {"asset": "ESRI.lib Webstyles/Vegetation/LowPoly/WashingtoniaFilifera.glb", "target_h_m": 10.5, "materials": ["veg_fan_frond", "veg_palm_trunk"], "ue": "ue_sobha_foliage palm[1] 10.5 m (L_BB_v1 KITS uses 13.0 m)"},
            "acacia":      {"asset": "ESRI.lib Webstyles/Vegetation/LowPoly/AcaciaTortilis.glb", "target_h_m": 6.0, "materials": ["veg_tree_crown", "veg_tree_trunk"], "ue": "ue_sobha_foliage tree[0] 6 m"},
            "ficus":       {"asset": "ESRI.lib Webstyles/Vegetation/LowPoly/FicusBenjamina.glb", "target_h_m": 6.5, "materials": ["veg_tree_crown", "veg_tree_trunk"], "ue": "ue_sobha_foliage tree[1] 6.5 m"},
            "parkinsonia": {"asset": "ESRI.lib Webstyles/Vegetation/LowPoly/ParkinsoniaAculeata.glb", "target_h_m": 5.5, "materials": ["veg_tree_crown", "veg_tree_trunk"], "ue": "ue_sobha_foliage tree[2] 5.5 m"},
            "buxus":       {"asset": "ESRI.lib Webstyles/Vegetation/LowPoly/BuxusSempervirens.glb", "target_h_m": 1.3, "materials": ["veg_shrub", "veg_tree_trunk"], "ue": "ue_sobha_foliage shrub[0] 1.3 m"},
            "lamp":        {"asset": "Unreal's own double-arm lamp: data/ce/_datasmith/bb_v1/v1_lamp_body.obj + v1_lamp_head.obj", "target_h_m": 10.0, "materials": ["prop_lamp_body", "prop_lamp_head"], "ue": "bb_v1_prep prop_meshes (10 m pole, two 2.2 m arms)"},
            "bench":       {"asset": "ESRI.lib StreetScene/Park_Bench_1.glb LOD1", "target_len_m": 1.9, "materials": ["prop_bench"], "ue": "KITS bench 1.9 m long"},
            "bin":         {"asset": "ESRI.lib StreetScene/Trash_Bin_1.glb LOD1", "target_h_m": 1.0, "materials": ["prop_bin"], "ue": "KITS bin 1.0 m"},
            "bus_shelter": {"asset": "ESRI.lib StreetScene/Bus_Stop_2.glb LOD1", "target_h_m": 2.8, "materials": ["prop_shelter"], "ue": "KITS shelter 2.8 m"},
            "bollard":     {"asset": "octagonal steel post (built here)", "target_h_m": 1.0, "materials": ["prop_bollard"], "ue": "KITS bollard 1.0 m"},
            "planter":     {"asset": "Unreal's planter box data/ce/_datasmith/bb_v1/v1_planter.obj + a Buxus on top", "target_h_m": 0.55, "materials": ["prop_planter", "veg_shrub"], "ue": "L_BB_v1 dress(): planter + hedge at +55 cm"},
            "car":         {"asset": "ESRI.lib Transportation/<5 models>.glb LOD1 (luminance texture x paint)", "target_len_m": 4.7, "materials": ["prop_car_0..4"], "ue": "KITS car 4.7 m long (v0 only)"},
            "cafe_table":  {"asset": "primitive round bistro table (built here)", "target_h_m": 0.75, "materials": ["prop_cafe_table"], "ue": "K['bistro_table'] 0.75 m"},
            "cafe_chair":  {"asset": "primitive bistro chair, seat front +x (built here)", "target_h_m": 0.9, "materials": ["prop_cafe_chair"], "ue": "K['bistro_chair'] 0.9 m"},
            "umbrella":    {"asset": "primitive octagonal parasol (built here)", "target_h_m": 2.6, "materials": ["prop_umbrella", "prop_cafe_chair"], "ue": "K['umbrella'] 2.6 m"},
            "pot":         {"asset": "primitive clay pot 0.45 m + a Buxus 0.65 m", "target_h_m": 0.45, "materials": ["prop_pot", "veg_shrub"], "ue": "K['potted'] 1.1 m (pot + plant)"},
            "crane":       {"asset": "ESRI.lib Transportation/Tower_Crane.glb LOD1", "target_h_m": 70.0, "materials": ["prop_site"], "ue": "KITS crane 70 m (liebherr_tower_crane / tower_crane)"},
            "site_kit":    {"asset": "ESRI.lib Cargo_Box / Dumptruck / Backhoe / Bobcat / Jersey_Barrier LOD1, native size", "target_native": True, "materials": ["prop_site"], "ue": "site_kit (SITE_SIZES, 17 Sketchfab construction models)"},
        },
        "unreal_building_palette": {k: {"rgb": list(v[0]), "roughness": v[1], "metallic": v[2], "specular_ue": v[3]} for k, v in SOBHA_PBR.items()},
        "unreal_building_palette_source": "ue_sobha_pbr.py PALETTE (facades are the facade lab's lane - carried here only so one file lists every engine colour)",
        "alternatives": {
            "M_SobhaSand": {"light": [0.82, 0.72, 0.52], "dark": [0.55, 0.45, 0.31], "macro_noise_scale_per_cm": 0.00002, "fine_noise": [0.002, 0.85, 1.0], "roughness": 0.95, "specular_ue": 0.3, "source": "ue_sobha_ground.py (sand_v2: light 0.86,0.76,0.55 dark 0.42,0.33,0.22, macro 0.00005)"},
            "M_SobhaWater": {"rgb": [0.02, 0.16, 0.22], "roughness": 0.04, "specular_ue": 1.0, "metallic": 0.0, "source": "ue_sobha_ground.py"},
        },
    }
    p = os.path.join(OUT, "context_palette.json")
    json.dump(pal, open(p, "w", encoding="utf-8"), indent=1)
    print("wrote %s  (%d roles)" % (os.path.relpath(p, ROOT), len(roles)))
    for k, v in roles.items():
        print("  %-20s %-8s rgb %-24s rough %.2f metal %.2f spec %.2f %s" % (k, v["kind"], v["rgb"], v["roughness"], v["metallic"], v["specular_ue"],
                                                                        ("tile %.0f m" % v["tile_m"]) if v.get("tile_m") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
