"""Unreal (commandlet): Business Bay v1 - build /Game/BusinessBay/L_BB_v1 (+ L_BB_v1_Buildings). v0 is left untouched.

Reuses ue_bb_v0_build.py's functions with its module globals re-pointed at v1 paths (assets under /Game/BusinessBay/v1,
actor prefix BB1_). What v1 changes (Kendall's v0 review, 28 Sep):
  - land level: district ground, streets, dressing and towers sit LIFT_CM (1.8 m) above the canal surface; quay wall,
    glass + steel railing, 13 m paving promenade, paved plots, podium edges (bb_v1_prep.py meshes v1_*.obj)
  - roads: mid-grey asphalt, white/yellow markings, kerbs; pavement = light stone (the ambientCG paving read black)
  - no barrier_traffic_cone_pack pieces (scaled x40-x83, the floating black squares), no site_prop pack; site hoardings;
    any kit part with a default/missing material or a floating flat slab is rejected
  - lamps: double-arm lamp built from primitives, emissive LED heads; abras built from primitives; yachts / speedboats
    sized separately (yacht 28 m +-25 %, speedboat 8.5 m, abra 10 m)
  - facades: 16 looks per building (seeded), or data/ce/businessbay/facade_palette_v1.json when present
  - look: sun, sky light (HDR_golden_bay_4k 1.2) and water colour as v0 (Kendall's canal reference); NO LUT (the pink
    wash on greys); neutral beige sand; subtle ripple normal on the water
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_bb_v1_build.py
Log lines are prefixed "BB0:" (shared logger); check for "done: /Game/BusinessBay/L_BB_v1".
"""
import json, math, os, random, re, sys

import unreal

sys.path.insert(0, "C:/Dev/naj-market-pulse/scripts")
import ue_bb_v0_build as B

REPO = B.REPO
V1 = REPO + "/data/ce/_datasmith/bb_v1"
B.LEVEL = "/Game/BusinessBay/L_BB_v1"
B.BLD_LEVEL = "/Game/BusinessBay/L_BB_v1_Buildings"
R1 = "/Game/BusinessBay/v1"
B.DS_BB, B.DS_BURJ = R1 + "/Datasmith/BB", R1 + "/Datasmith/Burj"
B.PBR_DIR, B.GROUND_DIR, B.CTX_DIR, B.FT_DIR, B.POST_DIR = R1 + "/PBR", R1 + "/Ground", R1 + "/Context", R1 + "/Foliage", R1 + "/Post"
B.V0 = V1
B.PLAN = V1 + "/bb_v1_plan.json"
B.USED = V1 + "/used_assets.json"
B.PFX = "BB1_"
VEHICLES = os.environ.get("BB_V1_VEHICLES", "0") == "1"
LEVEL_SHORT, BLD_SHORT = "L_BB_v1", "L_BB_v1_Buildings"
log, warn, eal, ell, MEL, tools = B.log, B.warn, B.eal, B.ell, B.MEL, B.tools
PLAN = B.PLAN

# ------------------------------------------------------------------------------------------------ kits (no packs)
K = B.KITS
for r in ("bollard", "fence", "barrier", "cone", "container", "site_prop", "bin", "boat"):
    K.pop(r, None)
K["yacht"] = (["sketchfab/vehicles/motor_yacht", "sketchfab/vehicles/yacht"], None, 28.0, "len", [])
K["speedboat"] = (["sketchfab/vehicles/speed_boat"], None, 8.5, "len", [])
# outdoor furniture (Kendall 29 Sep: "outdoor furniture ... sitting on a promenade"; Poly Haven audit: every Poly Haven
# furniture model is already downloaded - no patio umbrella there, so the Sketchfab parasol). Imported with
# DA_LIB_NAMES (ue_library_import.py). Missing kits are skipped with a warning.
K["cafe_set"] = (["polyhaven/models/outdoor_table_chair_set_01"], None, 1.7, "len", [])
K["bistro_table"] = (["polyhaven/models/gallinera_table", "polyhaven/models/round_wooden_table_01"], None, 0.75, "h", [])
K["bistro_chair"] = (["polyhaven/models/gallinera_chair", "polyhaven/models/bar_chair_round_01"], None, 0.9, "h", [])
K["umbrella"] = (["sketchfab/pool_outdoor/floating_parasol"], None, 2.6, "h", [])
K["street_seat"] = (["polyhaven/models/modular_street_seating"], None, 2.4, "len", [])
K["planter_box"] = (["polyhaven/models/planter_box_01", "polyhaven/models/planter_box_02", "polyhaven/models/planter_box_03"], None, 1.2, "len", [])
K["potted"] = (["polyhaven/models/potted_plant_01", "polyhaven/models/potted_plant_02", "polyhaven/models/potted_plant_04",
                "polyhaven/models/planter_pot_clay"], None, 1.1, "h", [])
FURNITURE_NAMES = "outdoor_table_chair_set_01,gallinera_table,round_wooden_table_01,gallinera_chair,bar_chair_round_01,modular_street_seating,painted_wooden_bench,planter_box_01,planter_box_02,planter_box_03,potted_plant_01,potted_plant_02,potted_plant_04,planter_pot_clay,floating-parasol-sunshade-patio-umbrella"
_kit0 = B.kit
DEFAULT_MAT = re.compile(r"worldgrid|defaultmaterial|default__", re.I)


def kit_v1(role):
    if role in ("lamp", "abra", "planter"):
        return custom_kit(role)
    out = _kit0(role)
    keep = []
    for v in out:
        badm = False
        for m in v["parts"]:
            for sm in m.get_editor_property("static_materials"):
                mi_ = sm.get_editor_property("material_interface")
                if mi_ is None or DEFAULT_MAT.search(mi_.get_path_name()):
                    badm = True
        if badm:
            warn("kit %s: %s rejected (missing/default material)" % (role, v["folder"].split("/")[-1])); continue
        lo, hi = B._bounds(v["parts"])
        H = hi[2] - lo[2]
        parts = []
        for m in v["parts"]:               # floating flat slabs (a black square hovering over the model) go
            b = m.get_bounds(); e = b.box_extent
            if len(v["parts"]) > 1 and e.z < 0.03 * max(e.x, e.y) and (b.origin.z - e.z - lo[2]) > 0.2 * H and max(e.x, e.y) > 0.3 * max(hi[0] - lo[0], hi[1] - lo[1]):
                warn("kit %s: %s part %s dropped (floating flat slab)" % (role, v["folder"].split("/")[-1], m.get_name())); continue
            parts.append(m)
        v["parts"] = parts or v["parts"]
        keep.append(v)
    B._KIT_CACHE[role] = keep
    return keep


B.kit = kit_v1


def simple_mat(name, rgb, rough=0.6, spec=0.5, metal=0.0, emissive=0.0, opacity=None):
    p = "%s/%s" % (B.PBR_DIR, name)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    mat = tools.create_asset(name, B.PBR_DIR, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("two_sided", True)
    if opacity is not None:
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        try:
            mat.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE)
        except Exception:
            pass
    c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, -100); c.constant = unreal.LinearColor(*rgb, 1.0)
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for v, prop, y in ((rough, unreal.MaterialProperty.MP_ROUGHNESS, 100), (spec, unreal.MaterialProperty.MP_SPECULAR, 200), (metal, unreal.MaterialProperty.MP_METALLIC, 300)):
        k = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, y); k.r = v
        MEL.connect_material_property(k, "", prop)
    if emissive:
        e = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, 400); e.constant = unreal.LinearColor(*(x * emissive for x in rgb), 1.0)
        MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    if opacity is not None:
        o = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 500); o.r = opacity
        MEL.connect_material_property(o, "", unreal.MaterialProperty.MP_OPACITY)
    for flag in ("used_with_instanced_static_meshes",):
        try:
            mat.set_editor_property(flag, True)
        except Exception:
            pass
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


_MATS = {}


def M(key):
    specs = {
        "lamp_body": ((0.30, 0.31, 0.32), 0.35, 0.5, 0.9),
        "lamp_head": ((1.0, 0.95, 0.85), 0.3, 0.5, 0.0, 6.0),
        "abra_hull": ((0.30, 0.18, 0.09), 0.6, 0.4, 0.0),
        "abra_roof": ((0.85, 0.82, 0.74), 0.7, 0.4, 0.0),
        "planter": ((0.62, 0.60, 0.56), 0.8, 0.3, 0.0),
        "quay": ((0.66, 0.58, 0.45), 0.8, 0.35, 0.0),          # #CFC6B4 stone face (STREETSCAPE_REFERENCE)
        "plots": ((0.58, 0.53, 0.44), 0.9, 0.3, 0.0),
        "podium": ((0.52, 0.47, 0.39), 0.85, 0.3, 0.0),
        "kerb": ((0.70, 0.70, 0.68), 0.8, 0.35, 0.0),
        "mark_white": ((0.85, 0.85, 0.83), 0.6, 0.4, 0.0),
        "mark_yellow": ((0.85, 0.62, 0.08), 0.6, 0.4, 0.0),
        "rail_steel": ((0.55, 0.56, 0.58), 0.3, 0.5, 0.9),
        "hoarding": ((0.82, 0.82, 0.80), 0.7, 0.35, 0.0),
    }
    if key in _MATS:
        return _MATS[key]
    if key == "promenade":                                  # grey checker #B4B6B8 / #8C8F92, ~0.5 m (reference photo)
        m = B.flat_or_noise("M_BB1_promenade", (0.24, 0.22, 0.20), (0.38, 0.36, 0.33), 0.006, 0.85, 0.35)
    elif key == "rail_glass":                               # reference: silver steel bar railing, not glass -> see-through steel
        m = simple_mat("M_BB1_rail_glass", (0.40, 0.41, 0.43), 0.3, 0.5, 0.9, 0.0, opacity=0.3)
    elif key == "wake":
        m = simple_mat("M_BB1_wake", (0.95, 0.97, 0.97), 0.6, 0.3, 0.0, 0.0, opacity=0.45)
    elif key == "canal":
        m = water_v1()
    else:
        s = specs[key]
        m = simple_mat("M_BB1_" + key, s[0], s[1], s[2], s[3], s[4] if len(s) > 4 else 0.0)
    _MATS[key] = m
    return m


def obj_mesh(key):
    m = B.import_obj(V1 + "/v1_%s.obj" % key, B.GROUND_DIR, "SM_BB1_" + key)
    if m:
        mat = M({"lamp_body": "lamp_body", "lamp_head": "lamp_head", "abra_hull": "abra_hull", "abra_roof": "abra_roof", "planter": "planter", "wake": "wake"}.get(key, key))
        m.set_material(0, mat); eal.save_loaded_asset(m)
    return m


def custom_kit(role):
    if role in B._KIT_CACHE:
        return B._KIT_CACHE[role]
    parts = {"lamp": ["lamp_body", "lamp_head"], "abra": ["abra_hull", "abra_roof"], "planter": ["planter"]}[role]
    ms = [obj_mesh(p) for p in parts]
    ms = [m for m in ms if m]
    out = []
    if ms:
        # the OBJ importer negates Y; these props are symmetric about X, so scale 1 is right
        out = [{"parts": ms, "scale": 1.0, "off": (0.0, 0.0, 0.0), "yaw90": False, "folder": "DigitAlchemy/primitives/" + role, "src_h": 1.0}]
    log("kit %-13s custom from primitives: %d part(s)" % (role, len(ms)))
    B._KIT_CACHE[role] = out
    return out


# ------------------------------------------------------------------------------------------------ materials
def water_v1():
    """v0 turquoise (Kendall's reference) + a subtle world-aligned ripple normal, roughness 0.07"""
    p = B.GROUND_DIR + "/M_BB1_Water"
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    mat = tools.create_asset("M_BB1_Water", B.GROUND_DIR, unreal.Material, unreal.MaterialFactoryNew())
    for v, prop, y in (((0.02, 0.16, 0.22), unreal.MaterialProperty.MP_BASE_COLOR, -300), (0.07, unreal.MaterialProperty.MP_ROUGHNESS, -100),
                       (1.0, unreal.MaterialProperty.MP_SPECULAR, 0), (0.0, unreal.MaterialProperty.MP_METALLIC, 100)):
        if isinstance(v, tuple):
            c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, y); c.constant = unreal.LinearColor(*v, 1.0)
        else:
            c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, y); c.r = v
        MEL.connect_material_property(c, "", prop)
    tex_p = B.LIB + "/AmbientCG/Concrete/Concrete030/T_Concrete030_Normal"
    if eal.does_asset_exist(tex_p):
        try:
            wp = MEL.create_material_expression(mat, unreal.MaterialExpressionWorldPosition, -1400, 300)
            msk = MEL.create_material_expression(mat, unreal.MaterialExpressionComponentMask, -1250, 300)
            msk.set_editor_property("r", True); msk.set_editor_property("g", True)
            sc = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1100, 300)
            sc.set_editor_property("const_b", 1.0 / 900.0)
            MEL.connect_material_expressions(wp, "", msk, ""); MEL.connect_material_expressions(msk, "", sc, "A")
            pan = MEL.create_material_expression(mat, unreal.MaterialExpressionPanner, -950, 300)
            pan.set_editor_property("speed_x", 0.015); pan.set_editor_property("speed_y", 0.01)
            MEL.connect_material_expressions(sc, "", pan, "Coordinate")
            ts = MEL.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -750, 300)
            ts.set_editor_property("texture", eal.load_asset(tex_p)); ts.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
            MEL.connect_material_expressions(pan, "", ts, "UVs")
            flat = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -750, 550); flat.constant = unreal.LinearColor(0, 0, 1, 1)
            lp = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -450, 400)
            lp.set_editor_property("const_alpha", 0.22)                   # subtle: reflections stay, just broken up
            MEL.connect_material_expressions(flat, "", lp, "A"); MEL.connect_material_expressions(ts, "RGB", lp, "B")
            MEL.connect_material_property(lp, "", unreal.MaterialProperty.MP_NORMAL)
            log("  water: ripple normal from %s" % tex_p)
        except Exception as e:
            warn("water ripple: %s" % e)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


EXTRA = {
    "silver_glass":   ((0.42, 0.46, 0.49), 0.05, 0.7, 1.0),
    "green_glass":    ((0.16, 0.32, 0.30), 0.06, 0.6, 1.0),
    "gold_glass":     ((0.52, 0.40, 0.22), 0.05, 0.8, 1.0),
    "grey_cladding":  ((0.55, 0.56, 0.57), 0.45, 0.6, 0.5),
    "beige_stone":    ((0.70, 0.62, 0.48), 0.80, 0.0, 0.4),
    "white_cladding": ((0.84, 0.84, 0.82), 0.40, 0.2, 0.5),
    "charcoal":       ((0.16, 0.16, 0.17), 0.50, 0.3, 0.5),
    "travertine":     ((0.76, 0.69, 0.56), 0.75, 0.0, 0.4),
}
B.SP.PALETTE.update(EXTRA)
# (walls, vision, slabs, fins) - 16 looks; podium/base = stone tones via "slabs"
LOOKS = [
    ("white_cladding", "blue_glass", "white", "white"), ("beige_stone", "clear_glass", "travertine", "bronze"),
    ("grey_cladding", "silver_glass", "pale_concrete", "grey_cladding"), ("cream_render", "bronze_glass", "sandstone", "rose_bronze"),
    ("white", "green_glass", "ivory_stone", "white"), ("charcoal", "dark_glass", "charcoal", "charcoal"),
    ("travertine", "gold_glass", "sandstone", "gold"), ("pale_concrete", "deep_blue_glass", "pale_concrete", "white"),
    ("ivory_stone", "champagne_glass", "ivory_stone", "rose_bronze"), ("white_cladding", "silver_glass", "white", "grey_cladding"),
    ("sandstone", "tinted_glass", "beige_stone", "dark_bronze"), ("grey_cladding", "blue_glass", "pale_concrete", "white_cladding"),
    ("cream_render", "akoya_glass", "cream_render", "white"), ("beige_stone", "green_glass", "travertine", "bronze"),
    ("white", "dark_glass", "white", "charcoal"), ("travertine", "clear_glass", "sandstone", "white_cladding"),
]
PALETTE_JSON = REPO + "/data/ce/businessbay/facade_palette_v1.json"


def _lin(h):
    h = h.lstrip("#"); return tuple(round((int(h[i:i + 2], 16) / 255.0) ** 2.2, 4) for i in (0, 2, 4))


def facade_looks():
    """facade_palette_v1.json (another agent maintains it in place): palette{look: base_hex, secondary_hex, reflectivity,
    roughness}, assignments{feature id: {look}}, landmarks{name: {feature_ids, look}}. Glassy looks (reflectivity >= 0.4)
    put base_hex on the glass and secondary on walls/slabs/fins; solid looks the other way round."""
    try:
        J = json.load(open(PALETTE_JSON, encoding="utf-8"))
    except FileNotFoundError:
        log("facades: %s not found - seeded 16-look palette" % PALETTE_JSON); return {}
    except Exception as e:
        warn("facades: %s unreadable (%s) - seeded palette" % (PALETTE_JSON, e)); return {}
    looks = {}
    for name, L in (J.get("palette") or {}).items():
        refl = float(L.get("reflectivity", 0.3)); rough = float(L.get("roughness", 0.5))
        warm = lambda c: (min(1.0, c[0] * 1.05), c[1] * 1.01, c[2] * 0.92)       # nudge towards Kendall's warm canal frame
        base, sec = warm(_lin(L.get("base_hex", "#CCCCCC"))), warm(_lin(L.get("secondary_hex", L.get("base_hex", "#CCCCCC"))))
        bk, sk = "fp_%s_base" % name, "fp_%s_sec" % name
        if refl >= 0.4:
            B.SP.PALETTE[bk] = (base, max(0.04, rough), min(0.8, refl + 0.1), 1.0)
            B.SP.PALETTE[sk] = (sec, 0.75, 0.0, 0.4)
            looks[name] = {"vision": bk, "walls": sk, "slabs": sk, "fins": sk}
        else:
            B.SP.PALETTE[bk] = (base, max(0.4, rough), 0.0, 0.4)
            B.SP.PALETTE[sk] = (sec, 0.08, 0.5, 1.0)
            looks[name] = {"walls": bk, "slabs": bk, "vision": sk, "fins": sk}
    out = {}
    for i, a in (J.get("assignments") or {}).items():
        if a.get("look") in looks:
            out[int(i)] = looks[a["look"]]
    for lm in (J.get("landmarks") or {}).values():
        if lm.get("look") in looks:
            for i in lm.get("feature_ids", []):
                out[int(i)] = looks[lm["look"]]
    log("facades: %d buildings, %d looks from %s" % (len(out), len(looks), PALETTE_JSON))
    return out


FACADE_DETAIL = os.environ.get("BB_V1_FACADE", "1") == "1"
LANDMARKS_JSON = REPO + "/data/ce/businessbay/landmarks/landmarks_v2.json"
_LM = None


def landmark_facade(key):
    """per-building facade numbers from the landmark deep dive (landmarks_v2.json, keyed by entry; ids[] = feature ids)"""
    global _LM
    if _LM is None:
        _LM = {}
        try:
            for e in json.load(open(LANDMARKS_JSON, encoding="utf-8")).get("landmarks", {}).values():
                f = e.get("facade") or {}
                if not f.get("base_hex"):
                    continue
                r = {"glass_rgb": _lin(f["base_hex"]), "frame_rgb": _lin(f.get("frame_hex") or f["base_hex"]),
                     "spandrel_rgb": _lin(f.get("spandrel_hex") or f["base_hex"]),
                     "floor_h_m": float(f.get("floor_m") or 3.4), "pane_w_m": float(f.get("pane_m") or 1.5)}
                for i in e.get("ids", []):
                    _LM[int(i)] = r
        except Exception as ex:
            warn("landmarks_v2.json: %s" % ex)
        log("landmark facades: %d buildings" % len(_LM))
    return _LM.get(key) if isinstance(key, int) else None


def facade_mis(key, walls, vision, slabs, fins):
    """two M_DA_Facade instances per look: 'glass' (curtain wall: floor band + mullions) and 'wall' (render / stone:
    punched window strips + slab lines)"""
    import ue_bb_facade as FAC
    par = FAC.parent(B.PBR_DIR)
    P = B.SP.PALETTE; W = P.get("white")
    g, f, sl, w = P.get(vision, W), P.get(fins, W), P.get(slabs, W), P.get(walls, W)
    dark = tuple(c * 0.55 for c in g[0])
    lf = landmark_facade(key) or {}
    fh = float(lf.get("floor_h_m", 3.4)); pw = float(lf.get("pane_w_m", 1.5))
    k = "%s_%s_%s" % (vision, fins, "lm%s" % key if lf else "g")
    glass = FAC.instance(par, B.PBR_DIR, "g_" + k, tuple(lf.get("glass_rgb", g[0])), tuple(lf.get("frame_rgb", f[0])),
                         tuple(lf.get("spandrel_rgb", dark)), roof=(0.42, 0.42, 0.41), floor_h=fh, pane_w=pw,
                         band_w=float(lf.get("band_w_m", 0.8)), mull_w=float(lf.get("mull_w_m", 0.12)),
                         glass_rough=max(0.04, g[1]), glass_metal=min(0.8, g[2] + 0.1), frame_rough=0.35, frame_metal=0.6,
                         spandrel_rough=0.3, spandrel_metal=0.35)
    kw = "%s_%s_%s" % (walls, vision, "lm%s" % key if lf else "g")
    wall = FAC.instance(par, B.PBR_DIR, "w_" + kw, w[0], tuple(c * 0.8 for c in g[0]), sl[0], roof=(0.42, 0.42, 0.41),
                        floor_h=fh, pane_w=3.0, band_w=0.35, mull_w=1.7, glass_rough=max(0.5, w[1]), glass_metal=0.0,
                        frame_rough=0.08, frame_metal=0.5, spandrel_rough=0.6, spandrel_metal=0.0)
    return {"glass": glass, "wall": wall}


def apply_pbr_v1(sa):
    parent = B.pbr_parent(); J = facade_looks(); rx = re.compile(r"^b(\d+)")
    done, byb = 0, {}
    for a in B.descendants(sa):
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        lab = a.get_actor_label() or ""
        m = rx.match(lab)
        key = int(m.group(1)) if m else lab.split("_")[0]
        if key in J and J[key]:
            lk = J[key]; look = (lk.get("walls", "white"), lk.get("vision", "blue_glass"), lk.get("slabs", "sandstone"), lk.get("fins", "white"))
        else:
            look = LOOKS[random.Random("bb_v1_%s" % key).randrange(len(LOOKS))]
        byb[look] = byb.get(look, 0) + 1
        walls, vision, slabs, fins = look
        comp = a.static_mesh_component
        if FACADE_DETAIL:
            fm = facade_mis(key, walls, vision, slabs, fins)
            for si in range(comp.get_num_materials()):
                cur = comp.get_material(si); nm = (cur.get_name() if cur else "").lower()
                role = next((r for x, r in B.SP.ROLE_OF if x.search(nm)), None) or ("vision" if "glass" in nm else "walls")
                if role in ("vision", "spandrel") or (role == "walls" and "glass" in nm):
                    comp.set_material(si, fm["glass"])
                elif role == "walls":
                    comp.set_material(si, fm["wall"])
                elif role in ("slabs", "fins"):
                    comp.set_material(si, B.mi(parent, "%s_%s" % (slabs if role == "slabs" else fins, role), slabs if role == "slabs" else fins))
                else:
                    comp.set_material(si, B.mi(parent, "roof", "roof"))
            done += 1
            continue
        for si in range(comp.get_num_materials()):
            cur = comp.get_material(si); nm = (cur.get_name() if cur else "").lower()
            role = next((r for x, r in B.SP.ROLE_OF if x.search(nm)), None) or ("vision" if "glass" in nm else "walls")
            if role == "vision":
                mat = B.mi(parent, "%s_vision" % vision, vision)
            elif role == "spandrel":
                mat = B.mi(parent, "%s_spandrel" % vision, vision, rough_bias=0.10, dim=0.75)
            elif role == "walls":
                mat = B.mi(parent, "%s_curtain" % vision, vision, rough_bias=0.04) if "glass" in nm else B.mi(parent, "%s_walls" % walls, walls)
            elif role == "slabs":
                mat = B.mi(parent, "%s_slabs" % slabs, slabs)
            elif role == "fins":
                mat = B.mi(parent, "%s_fins" % fins, fins)
            else:
                mat = B.mi(parent, "roof", "roof")
            comp.set_material(si, mat)
        done += 1
    log("pbr v1: %d actors, %d looks used, %d material instances" % (done, len(byb), len(B._MI)))


# ------------------------------------------------------------------------------------------------ landmark heights + crowns
def landmarks(sa, gz):
    """research heights (bb_landmark_crowns.CROWNS / HEIGHT_FIX) and signature crowns on the roof of each landmark"""
    import bb_landmark_crowns as LC
    import ue_bb_facade as FAC
    for a in list(ell.get_all_level_actors()):
        if (a.get_actor_label() or "").startswith(B.PFX + "CROWN_"):
            ell.destroy_actor(a)
    par = FAC.parent(B.PBR_DIR)
    mats = {"cream": B.mi(B.pbr_parent(), "crown_cream", "ivory_stone"), "white": B.mi(B.pbr_parent(), "crown_white", "white"),
            "crown_glass": FAC.instance(par, B.PBR_DIR, "crown_glass", _lin("#BFE3F5"), _lin("#F2F2EF"), _lin("#9FC7DD"),
                                        floor_h=3.0, pane_w=1.2, glass_rough=0.05, glass_metal=0.7, store=False),
            "steel": FAC.instance(par, B.PBR_DIR, "crown_steel", _lin("#C8CACC"), _lin("#B0B2B4"), _lin("#A0A3A6"),
                                  glass_rough=0.2, glass_metal=1.0, store=False),
            "bronze": FAC.instance(par, B.PBR_DIR, "crown_bronze", _lin("#B8894F"), _lin("#9A6E3A"), _lin("#8A6234"),
                                   glass_rough=0.3, glass_metal=1.0, frame_metal=1.0, store=False)}
    rx = re.compile(r"^b(\d+)")
    parts = {}
    for a in B.descendants(sa):
        m = rx.match(a.get_actor_label() or "")
        if m and isinstance(a, unreal.StaticMeshActor):
            parts.setdefault(int(m.group(1)), []).append(a)
    want = dict(LC.HEIGHT_FIX); want.update({i: c[3] for i, c in LC.CROWNS.items() if c[3]})
    want.update({i: h * k for i, (h, k) in LC.CONSTRUCTION.items()})
    frame = FAC.instance(par, B.PBR_DIR, "construction_frame", (0.035, 0.035, 0.037), (0.42, 0.41, 0.39), (0.50, 0.49, 0.47),
                         roof=(0.46, 0.45, 0.43), floor_h=3.4, pane_w=7.5, band_w=0.45, mull_w=0.7, glass_rough=0.9,
                         glass_metal=0.0, frame_rough=0.85, frame_metal=0.0, spandrel_rough=0.85, spandrel_metal=0.0, specular=0.3, store=False)
    cranes = B.kit("crane")
    meshes = {}
    for bid, acts in sorted(parts.items()):
        if bid not in want and bid not in LC.CROWNS:
            continue
        lo = min(a.get_actor_bounds(False)[0].z - a.get_actor_bounds(False)[1].z for a in acts)
        hi = max(a.get_actor_bounds(False)[0].z + a.get_actor_bounds(False)[1].z for a in acts)
        if bid in want and hi - lo > 1000.0:
            k = want[bid] * 100.0 / (hi - lo)
            for a in acts:
                sc = a.get_actor_scale3d(); a.set_actor_scale3d(unreal.Vector(sc.x, sc.y, sc.z * k))
                o, e = a.get_actor_bounds(False); l = a.get_actor_location()
                a.set_actor_location(unreal.Vector(l.x, l.y, l.z + (lo - (o.z - e.z))), False, False)
            hi = max(a.get_actor_bounds(False)[0].z + a.get_actor_bounds(False)[1].z for a in acts)
            log("  landmark b%d height %.0f -> %.0f m" % (bid, want[bid] / k, want[bid]))
        if bid in LC.CONSTRUCTION:
            for a in acts:
                comp = a.static_mesh_component
                for si in range(comp.get_num_materials()):
                    comp.set_material(si, frame)
            top = max(acts, key=lambda a: a.get_actor_bounds(False)[0].z + a.get_actor_bounds(False)[1].z)
            o, e = top.get_actor_bounds(False)
            if cranes:
                v = cranes[bid % len(cranes)]
                for pi, part in enumerate(v["parts"]):
                    xf = B.place_xf(v, o.x, o.y, hi, (bid * 37) % 360)
                    c = ell.spawn_actor_from_class(unreal.StaticMeshActor, xf.translation, xf.rotation.rotator())
                    c.set_actor_label(B.PFX + "CROWN_crane_b%d_%d" % (bid, pi))
                    c.static_mesh_component.set_static_mesh(part); c.set_actor_scale3d(xf.scale3d)
            log("  construction b%d: frame to %.0f m (of %.0f), crane on top" % (bid, (hi - gz) / 100, LC.CONSTRUCTION[bid][0]))
            continue
        if bid in LC.CROWNS:
            kind, ch, mk, _ = LC.CROWNS[bid]
            if kind not in meshes:
                meshes[kind] = B.import_obj(V1 + "/crown_%s.obj" % kind, B.PBR_DIR, "SM_BB1_crown_" + kind)
            if not meshes[kind]:
                continue
            top = max(acts, key=lambda a: a.get_actor_bounds(False)[0].z + a.get_actor_bounds(False)[1].z)
            o, e = top.get_actor_bounds(False)
            a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(o.x, o.y, hi))
            a.set_actor_label(B.PFX + "CROWN_b%d" % bid)
            a.static_mesh_component.set_static_mesh(meshes[kind]); a.static_mesh_component.set_material(0, mats[mk])
            w = min(e.x, e.y) * 2.0 * 0.92 / 100.0
            w = min(w, {"needle": 12.0, "fin_ring": 42.0, "corner_spires": 42.0, "cage": 40.0}.get(kind, 45.0))   # bounds include podiums
            if (hi - gz) / 100.0 < 100.0:
                ell.destroy_actor(a); log("  crown on b%d skipped: roof under 100 m" % bid); continue
            a.set_actor_scale3d(unreal.Vector(w, -w, ch))
            log("  crown %s on b%d: %.0f m wide, %.0f m tall, roof %.0f m" % (kind, bid, w, ch, (hi - gz) / 100))


# ------------------------------------------------------------------------------------------------ storefronts
STOREFRONTS = os.environ.get("BB_V1_STOREFRONTS", "1") == "1"
SF_JSON = REPO + "/data/ce/businessbay/storefronts_ue.json"
SIGN_RGB = {"restaurant": (0.32, 0.05, 0.04), "bar": (0.04, 0.06, 0.16), "cafe": (0.06, 0.16, 0.08), "coffee": (0.06, 0.16, 0.08),
            "beauty": (0.55, 0.32, 0.34), "pharmacy": (0.05, 0.30, 0.12), "bank": (0.03, 0.08, 0.22), "hotel": (0.30, 0.22, 0.10),
            "supermarket": (0.40, 0.05, 0.03), "fast_food": (0.55, 0.20, 0.02)}
AWNING_RGB = [(0.78, 0.72, 0.60), (0.45, 0.14, 0.08), (0.12, 0.12, 0.12), (0.20, 0.28, 0.24)]


def storefronts(plan, gz):
    """ground-floor shopfronts (Kendall 29 Sep: "there should also now be storefronts, not just building straight to the
    street"): data/ce/businessbay/storefronts_ue.json (scripts/ue_storefronts.py - real OSM retail POIs + retail parades,
    6 m bays on the street-facing edge, local +Y out of the building). Per bay: glazed shopfront (warm interior tone,
    bronze mullions every 2 m), a coloured sign band by kind, an awning on every other bay; planters on the pavement."""
    import ue_bb_facade as FAC
    try:
        JS = json.load(open(SF_JSON, encoding="utf-8"))
    except Exception as e:
        warn("storefronts: %s" % e); return
    S = JS
    cube = eal.load_asset("/Engine/BasicShapes/Cube")
    par = FAC.parent(B.PBR_DIR)
    glass = FAC.instance(par, B.PBR_DIR, "shopfront", (0.10, 0.075, 0.05), (0.09, 0.07, 0.05), (0.09, 0.07, 0.05),
                         floor_h=40.0, pane_w=2.0, band_w=0.0, mull_w=0.09, glass_rough=0.04, glass_metal=0.35,
                         frame_rough=0.35, frame_metal=0.9, specular=0.8, store=False)
    for k, c in SIGN_RGB.items():
        B.SP.PALETTE["sf_" + k] = (c, 0.4, 0.0, 0.5)
    B.SP.PALETTE["sf_other"] = ((0.08, 0.08, 0.085), 0.4, 0.0, 0.5)
    for i, c in enumerate(AWNING_RGB):
        B.SP.PALETTE["aw_%d" % i] = (c, 0.8, 0.0, 0.3)
    land = gz + float(plan["lift_cm"])
    n = 0

    def box(label, x, y, yaw, sx, sy, sz, z, mat, lx=0.0, ly=0.0, pitch=0.0):
        r = math.radians(yaw)
        wx = x + lx * math.cos(r) - ly * math.sin(r); wy = y + lx * math.sin(r) + ly * math.cos(r)
        a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(wx, wy, z), unreal.Rotator(roll=pitch, pitch=0.0, yaw=yaw))
        a.set_actor_label(B.PFX + label)
        c = a.static_mesh_component; c.set_static_mesh(cube); c.set_material(0, mat)
        a.set_actor_scale3d(unreal.Vector(sx / 100.0, sy / 100.0, sz / 100.0))
        return a

    aw = {(round(a[0]), round(a[1])) for a in S.get("awnings", [])}
    for i, (x, y, yaw, w, kind) in enumerate(S.get("bays", [])):
        box("SF_glass_%d" % i, x, y, yaw, w - 20.0, 30.0, 420.0, land + 210.0, glass, ly=15.0)
        sm = B.mi(B.pbr_parent(), "sign_" + kind if kind in SIGN_RGB else "sign_other", "sf_" + kind if kind in SIGN_RGB else "sf_other")
        box("SF_sign_%d" % i, x, y, yaw, w, 40.0, 80.0, land + 470.0, sm, ly=25.0)
        if (round(x), round(y)) in aw:
            am = B.mi(B.pbr_parent(), "awning_%d" % (i % 4), "aw_%d" % (i % 4))
            box("SF_awning_%d" % i, x, y, yaw, w - 40.0, 190.0, 18.0, land + 360.0, am, ly=100.0, pitch=-24.0)      # canvas, 24 deg fall
            box("SF_valance_%d" % i, x, y, yaw, w - 40.0, 6.0, 38.0, land + 300.0, am, ly=188.0)                     # front flap
        n += 1
    pl = B.kit("potted") or B.kit("planter")
    np_ = 0
    if pl:
        v = pl[0]
        for j, (x, y) in enumerate(S.get("planters", [])):
            for pi, part in enumerate(v["parts"]):
                xf = B.place_xf(v, x, y, land, 0.0)
                a = ell.spawn_actor_from_class(unreal.StaticMeshActor, xf.translation, xf.rotation.rotator())
                a.set_actor_label(B.PFX + "SF_planter_%d_%d" % (j, pi))
                a.static_mesh_component.set_static_mesh(part); a.set_actor_scale3d(xf.scale3d)
            np_ += 1
    S = B.scatter
    S("bistro_table", [[t[0], t[1], 0.0, 1.0, k] for k, t in enumerate(JS.get("tables", []))], land)
    S("bistro_chair", [[c[0], c[1], c[2] + 180.0, 1.0, k] for k, c in enumerate(JS.get("chairs", []))], land)
    S("umbrella", [[u[0], u[1], 0.0, 1.0, 0] for u in JS.get("umbrellas", [])], land)
    log("storefronts: %d bays (glazing + sign band, %d awnings), %d planters, %d cafe tables" % (n, len(aw), np_, len(JS.get("tables", []))))


# ------------------------------------------------------------------------------------------------ Burj Khalifa hero mesh
HERO_BURJ = os.environ.get("BB_V1_BURJ_HERO", "1") == "1"


def hero_burj(plan, gz):
    """bb_burj_mesh.py OBJs (spec: data/ce/businessbay/landmarks/burj_khalifa_spec.json): silver reflective glass with
    polished stainless fins every 1.4 m and textured steel spandrels (floor 3.66 m), darker mechanical bands, steel spire"""
    import ue_bb_facade as FAC
    par = FAC.parent(B.PBR_DIR)
    lin = lambda h: _lin(h)
    glass = FAC.instance(par, B.PBR_DIR, "burj_glass", lin("#7f96bd"), lin("#dfe5ee"), lin("#90a0b8"), lin("#a8b4c6"),
                         floor_h=3.66, pane_w=1.4, band_w=0.55, mull_w=0.22, glass_rough=0.06, frame_rough=0.22,
                         glass_metal=0.75, frame_metal=1.0, spandrel_rough=0.35, spandrel_metal=0.9, store=False)
    band = FAC.instance(par, B.PBR_DIR, "burj_band", lin("#5f6b80"), lin("#76819a"), lin("#56627a"), lin("#5f6b80"),
                        floor_h=1.2, pane_w=0.6, band_w=0.35, mull_w=0.1, glass_rough=0.45, frame_rough=0.4,
                        glass_metal=0.6, frame_metal=0.8, store=False)
    spire = FAC.instance(par, B.PBR_DIR, "burj_spire", lin("#c9c9c8"), lin("#b0b0b0"), lin("#9da0a4"), lin("#c9c9c8"),
                         floor_h=4.0, pane_w=0.9, band_w=0.3, mull_w=0.15, glass_rough=0.18, frame_rough=0.25,
                         glass_metal=1.0, frame_metal=1.0, store=False)
    for a in list(ell.get_all_level_actors()):            # the buildings sublevel survives open_levels(): no duplicates
        if (a.get_actor_label() or "").startswith(B.PFX + "BURJ_"):
            ell.destroy_actor(a)
    c = plan["burj_cm"]
    for part, mat in (("glass", glass), ("band", band), ("spire", spire)):
        m = B.import_obj(V1 + "/burj_%s.obj" % part, B.DS_BURJ, "SM_BB1_Burj_" + part)
        if not m:
            warn("burj %s mesh missing - run scripts/bb_burj_mesh.py" % part); continue
        m.set_material(0, mat); eal.save_loaded_asset(m)
        a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(c[0], c[1], gz))
        a.set_actor_label(B.PFX + "BURJ_" + part)
        a.static_mesh_component.set_static_mesh(m)
        a.static_mesh_component.set_material(0, mat)
        a.set_actor_scale3d(unreal.Vector(1, -1, 1))      # the OBJ importer negates Y (ue_sobha_water_fix lesson)
        o, e = a.get_actor_bounds(False)
        log("  burj %s: centre (%.0f, %.0f) m, top %.0f m" % (part, o.x / 100, o.y / 100, (o.z + e.z - gz) / 100))


# ------------------------------------------------------------------------------------------------ level plumbing (v1 names)
def open_levels():
    les = B.les()
    if eal.does_asset_exist(B.LEVEL):
        les.load_level(B.LEVEL); log("reopened " + B.LEVEL)
    else:
        if not les.new_level(B.LEVEL):
            raise RuntimeError("could not create " + B.LEVEL)
        log("created " + B.LEVEL)
    world = ell.get_editor_world()
    names = set()
    for lv in (unreal.EditorLevelUtils.get_levels(world) or []):
        try:
            names.add(lv.get_outermost().get_name())
        except Exception:
            pass
    stream = True if any(n.endswith(BLD_SHORT) for n in names) else None
    if stream is None:
        if eal.does_asset_exist(B.BLD_LEVEL):
            stream = unreal.EditorLevelUtils.add_level_to_world(world, B.BLD_LEVEL, unreal.LevelStreamingAlwaysLoaded)
        else:
            stream = unreal.EditorLevelUtils.create_new_streaming_level(unreal.LevelStreamingAlwaysLoaded, B.BLD_LEVEL, False)
        log("buildings sublevel %s attached" % B.BLD_LEVEL)
    n = 0
    for a in list(ell.get_all_level_actors()):
        if (a.get_actor_label() or "").startswith(B.PFX) or isinstance(a, unreal.InstancedFoliageActor):
            if a.get_level() and BLD_SHORT in a.get_level().get_outermost().get_name():
                continue
            ell.destroy_actor(a); n += 1
    log("cleared %d actors from the previous run" % n)
    return stream


def make_current(buildings):
    nm = BLD_SHORT if buildings else LEVEL_SHORT
    try:
        B.les().set_current_level_by_name(nm)
    except Exception as e:
        warn("set_current_level_by_name %s: %s" % (nm, e))
    log("current level: %s" % B.current_level_name())


# ------------------------------------------------------------------------------------------------ scene
def desat_cube():
    src = B.LIB + "/HDRI/Dubai/HDR_golden_bay_4k"; dst = B.POST_DIR + "/HDR_golden_bay_4k_desat"
    if not eal.does_asset_exist(dst):
        eal.duplicate_asset(src, dst)
    t = eal.load_asset(dst)
    try:
        t.set_editor_property("adjust_saturation", float(os.environ.get("BB_V1_SKY_SAT", "0.3")))
        eal.save_asset(dst)
    except Exception as e:
        warn("sky desat: %s" % e)
    return t


def environment(plan, gz):
    B.environment(plan, gz)
    cube = desat_cube()
    # warm grade that also reaches MRQ -game renders: an unbound post-process volume (WB 5,500 K, slight warm gain)
    ppv = B.spawn(unreal.PostProcessVolume, "PPV_WARM", (0, 0, 0))
    ppv.set_editor_property("unbound", True)
    ps = ppv.get_editor_property("settings")
    for k, v in (("override_white_temp", True), ("white_temp", float(os.environ.get("BB_V1_WB", "8000"))),
                 ("override_color_gain", True), ("color_gain", unreal.Vector4(1.04, 1.0, 0.93, 1.0))):
        try:
            ps.set_editor_property(k, v)
        except Exception as e:
            warn("ppv %s: %s" % (k, e))
    ppv.set_editor_property("settings", ps)
    r = ppv.get_editor_property("settings")
    log("  PPV_WARM readback: white_temp %s override %s, color_gain %s" % (r.get_editor_property("white_temp"), r.get_editor_property("override_white_temp"), r.get_editor_property("color_gain")))
    for a in ell.get_all_level_actors():
        lab = a.get_actor_label() or ""
        if lab == B.PFX + "SUN":
            a.light_component.set_light_color(unreal.LinearColor(1.0, 0.88, 0.74, 1.0))
            log("  sun colour (1.0, 0.88, 0.74)")
        if lab == B.PFX + "SKY" and cube:
            slc = a.light_component
            slc.set_editor_property("cubemap", cube); slc.recapture_sky()
            log("  sky light: %s (saturation %s)" % (cube.get_path_name(), os.environ.get("BB_V1_SKY_SAT", "0.3")))
        if lab == B.PFX + "FOG":                            # a touch more haze far out: softens the sand ring beyond 3 km
            fc = a.component
            fc.set_editor_property("fog_density", 0.015); fc.set_editor_property("start_distance", 120000.0)
            fc.set_editor_property("directional_inscattering_luminance", unreal.LinearColor(0.95, 0.90, 0.80, 1.0))
        if lab == B.PFX + "GROUND_Sand":                    # neutral beige, less orange (was reading pink under the grade)
            a.static_mesh_component.set_material(0, B.flat_or_noise("M_BB1_Sand2", (0.60, 0.52, 0.39), (0.74, 0.66, 0.52), 0.00005, 0.95, 0.3))


def ground(plan, gz):
    lift = float(plan["lift_cm"]); gl = gz + lift
    water = M("canal")
    meta = json.load(open(B.WATER_OBJ + "/ground_meshes.json", encoding="utf-8"))
    bb = meta["bbox_utm"]
    exp = ((bb[0] + bb[2]) / 2 - 328289.0) * 100.0, (2784598.0 - (bb[1] + bb[3]) / 2) * 100.0
    for name, label in (("sea", "WATER_Sea"), ("inland_water", "WATER_Inland")):
        m = B.import_obj(B.WATER_OBJ + "/%s.obj" % name, B.GROUND_DIR, "SM_BB1_" + name)
        if m:
            B.place_mesh(label, m, water, gz + 10.0, exp)
    looks = {
        "asphalt": ((0.16, 0.16, 0.165), (0.22, 0.22, 0.225), 0.0007, 0.85, 0.3),
        "pavement": ((0.52, 0.52, 0.50), (0.64, 0.64, 0.62), 0.0012, 0.9, 0.3),
        "parking": ((0.18, 0.18, 0.185), (0.24, 0.24, 0.245), 0.0009, 0.85, 0.3),
        "grass": ((0.12, 0.28, 0.07), (0.22, 0.40, 0.10), 0.0009, 0.9, 0.2),
        "pitch": ((0.10, 0.30, 0.08), (0.14, 0.36, 0.10), 0.001, 0.85, 0.2),
        "pool": ((0.05, 0.35, 0.45), (0.08, 0.45, 0.55), 0.001, 0.05, 1.0),
        "construction": ((0.50, 0.46, 0.38), (0.60, 0.56, 0.47), 0.001, 0.95, 0.2),
    }
    mats = {}
    for layer, info in sorted(plan.get("context", {}).items()):
        m = B.import_obj(V1 + "/ctx_%s.obj" % layer, B.CTX_DIR, "SM_BB1_ctx_%s" % layer)
        if not m:
            continue
        base = layer[2:] if layer.startswith("s_") else layer
        b = info.get("bounds_cm"); ctr = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None
        if info.get("role") == "massing":
            mat = B.flat_or_noise("M_BB1_massing", (0.62, 0.60, 0.56), (0.72, 0.70, 0.66), 0.0005, 0.8, 0.3)
            B.place_mesh("CTX_" + layer, m, mat, gz, ctr, shadow=True); continue
        lk = looks.get(base, ((0.3, 0.3, 0.3), (0.4, 0.4, 0.4), 0.001, 0.9, 0.3))
        if base not in mats:
            mats[base] = B.flat_or_noise("M_BB1_ctx_%s" % base, lk[0], lk[1], lk[2], lk[3], lk[4])
        B.place_mesh("CTX_" + layer, m, mats[base], (gz - 3.0) if layer.startswith("s_") else gl, ctr)
    for key in ("canal", "quay", "rail_glass", "rail_steel", "promenade", "plots", "podium", "kerb", "mark_white", "mark_yellow", "hoarding"):
        info = plan.get("v1_meshes", {}).get({"canal": "canal"}.get(key, key))
        m = B.import_obj(V1 + "/v1_%s.obj" % ("canal_water" if key == "canal" else key), B.GROUND_DIR, "SM_BB1_" + key)
        if not m:
            warn("v1 mesh %s missing" % key); continue
        b = info.get("bounds_cm") if info else None
        B.place_mesh("V1_" + key, m, M(key), gz if key == "hoarding" else gl, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None,
                     shadow=key in ("quay", "rail_steel", "hoarding"))
        if key == "hoarding":                                 # sites stay at the lifted ground
            a = next(x for x in ell.get_all_level_actors() if (x.get_actor_label() or "") == B.PFX + "V1_hoarding")
            l = a.get_actor_location(); a.set_actor_location(unreal.Vector(l.x, l.y, gl), False, False)


def dress(plan, gz):
    gl = gz + float(plan["lift_cm"]); wz = gz + float(plan["lift_cm"]) + float(plan["water_z_cm"])
    D = plan["dress"]
    S = B.scatter
    S("date_palm", D["median_palms"], gl)
    wash = "washingtonia" if B.kit("washingtonia") else "date_palm"       # washingtonia kits fail the default-material check
    S(wash, [r for r in D["kerb_palms"] if r[4] == 1], gl)
    S("date_palm", [r for r in D["kerb_palms"] if r[4] != 1], gl)
    S("date_palm", D["prom_palms"], gl)
    S("shade_tree", D["park_trees"], gl)
    S("date_palm", D["park_palms"], gl)
    S("lamp", D["lamps"] + D["prom_lamps"], gl)
    seat = "street_seat" if B.kit("street_seat") else "bench"
    S("bench", [r for r in D["benches"] if r[4] != 1], gl, len_axis=True)
    S(seat, [r for r in D["benches"] if r[4] == 1], gl, len_axis=True)
    if B.kit("planter_box"):
        S("planter_box", D["planters"], gl, len_axis=True)
    else:
        S("planter", D["planters"], gl)
        S("hedge", [[r[0], r[1], r[2], 0.8] for r in D["planters"]], gl + 55.0, shadow=False)
    cafes = D.get("prom_cafes", [])                          # promenade cafe clusters: set + umbrella + a potted plant each side
    if cafes:
        # 29 Sep close-up: outdoor_table_chair_set_01 placed (116) but renders invisible - bistro table + 4 chairs instead
        S("bistro_table", [[r[0], r[1], r[2], 1.0, k] for k, r in enumerate(cafes)], gl)
        chairs = []
        for k, r in enumerate(cafes):
            for q in range(4):
                a = math.radians(r[2] + 45.0 + 90.0 * q)
                chairs.append([r[0] + 80.0 * math.cos(a), r[1] + 80.0 * math.sin(a), r[2] + 45.0 + 90.0 * q + 180.0, 1.0, k])
        S("bistro_chair", chairs, gl)
        S("umbrella", [[r[0], r[1], r[2], 1.0, 0] for r in cafes], gl)
        pots = []
        for k, r in enumerate(cafes):
            a = math.radians(r[2])
            for sgn in (-1, 1):
                pots.append([r[0] + sgn * 180.0 * math.cos(a), r[1] + sgn * 180.0 * math.sin(a), k * 40.0, 1.0, k + sgn])
        S("potted", pots, gl)
        log("  promenade cafes: %d clusters" % len(cafes))
    S("shelter", D["bus_shelters"], gl, len_axis=True)
    if VEHICLES:                                             # Kendall 28 Sep: no cars / boats in v1 (flag kept, off)
        S("car", D["parked_cars"], gl, len_axis=True)
        S("yacht", D["yachts"], wz, len_axis=True)
        S("speedboat", D["speedboats"], wz, len_axis=True)
        S("abra", D["abras"], wz)
    sites(plan, gl)


def sites(plan, gz):
    all_s = plan.get("sites") or []
    rnd = random.Random(5)
    cranes, kitrows = [], []
    for q in sorted(all_s, key=lambda q: -q.get("area_m2", 0)):
        x0, y0, x1, y1 = q["x0"], q["y0"], q["x1"], q["y1"]; w, h = x1 - x0, y1 - y0
        cranes.append([x0 + 0.3 * w, y0 + 0.35 * h, rnd.uniform(0, 360), rnd.uniform(0.9, 1.25), 0])
        if w * h > 6000.0 * 6000.0:
            cranes.append([x0 + 0.72 * w, y0 + 0.7 * h, rnd.uniform(0, 360), rnd.uniform(0.8, 1.1), 1])
        for k in range(max(6, min(18, int(w * h / (1500.0 * 1500.0))))):
            kitrows.append([x0 + w * rnd.uniform(0.1, 0.9), y0 + h * rnd.uniform(0.1, 0.9), rnd.choice((0, 90, 180, 270)) + rnd.uniform(-8, 8), 1.0, rnd.randrange(64)])
    B.scatter("crane", cranes, gz)
    B.scatter("site_kit", kitrows, gz, len_axis=True)
    log("  construction sites dressed: %d (hoardings, no pack pieces)" % len(all_s))


def main():
    plan = json.load(open(PLAN, encoding="utf-8"))
    B.ensure_dirs()
    for d in (R1, R1 + "/Datasmith", B.PBR_DIR, B.GROUND_DIR, B.CTX_DIR, B.FT_DIR, B.POST_DIR):
        if not eal.does_directory_exist(d):
            eal.make_directory(d)
    stream = open_levels()
    make_current(True)
    sa = B.import_datasmith(B.DATASMITH, B.DS_BB, "businessbay_lod3")
    burj = B.import_datasmith(B.DATASMITH_BURJ, B.DS_BURJ, "burjkhalifa_lod3") if os.path.exists(B.DATASMITH_BURJ) else None
    gz = 0.0
    if sa:
        gz = B.check_offset(sa, plan)
        l = sa.get_actor_location()
        want = float(plan["lift_cm"])
        tags = [str(t) for t in sa.tags]
        have = sum(float(t.split("_")[-1]) if t.startswith("bb1_lift_") else (180.0 if t == "bb1_lift" else 0.0) for t in tags)
        if abs(have - want) > 0.5:                            # towers sit on the land level (tag records the lift applied)
            sa.set_actor_location(unreal.Vector(l.x, l.y, l.z + want - have), False, False)
            sa.tags = [unreal.Name(t) for t in tags if not t.startswith("bb1_lift")] + [unreal.Name("bb1_lift_%.0f" % want)]
            log("towers lifted %.1f m (was %.1f m) to the land level" % (want / 100, have / 100))
        import ue_bb_facade as FAC
        FAC.STORE_TOP = gz + float(plan["lift_cm"]) + 550.0      # ground-floor shopfronts up to 5.5 m above the land level
        B.nanite_on(sa); apply_pbr_v1(sa)
        landmarks(sa, gz)
    if burj and HERO_BURJ:
        # the burjkhalifa_lod3 scene is ALL of Downtown (~600 actors): remove only the tower itself (bounds centre
        # within 120 m of the Burj point); 29 Sep lesson - deleting the whole scene emptied Downtown
        n, c = 0, plan["burj_cm"]
        for a in list(B.descendants(burj)):
            try:
                o, e = a.get_actor_bounds(False)
                if math.hypot(o.x - c[0], o.y - c[1]) < 12000.0 and e.z > 5000.0:
                    ell.destroy_actor(a); n += 1
            except Exception:
                pass
        log("burj: CityEngine tower removed (%d actors); Downtown backdrop kept" % n)
    if HERO_BURJ:
        hero_burj(plan, gz)
    if burj:
        B.nanite_on(burj); apply_pbr_v1(burj)
    eal.save_directory(R1 + "/Datasmith", only_if_is_dirty=True, recursive=True)
    eal.save_directory(B.PBR_DIR, only_if_is_dirty=False, recursive=True)
    make_current(False)
    environment(plan, gz)
    ground(plan, gz)
    dress(plan, gz)
    if STOREFRONTS:
        storefronts(plan, gz)
    eal.save_directory(R1, only_if_is_dirty=True, recursive=True)
    B.les().save_all_dirty_levels()
    json.dump({"placed": B.USED_SET, "gz_cm": gz}, open(B.USED, "w", encoding="utf-8"), indent=1)
    log("done: %s saved (+ %s)" % (B.LEVEL, B.BLD_LEVEL))


if __name__ == "__main__":
    main()
