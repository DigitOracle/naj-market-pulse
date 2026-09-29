"""Unreal (commandlet helper): procedural facade material for district fly-throughs (Kendall 29 Sep 2026: "more
definition, more facades"). No UVs needed: the pattern comes from world position + normal, so it works on every
CityEngine / Datasmith tower and on generated hero meshes.

M_DA_Facade (one parent, many instances):
  floor band  every FloorH m (spandrel / slab edge), BandW m tall        -> SpandrelColor
  mullion     every PaneW m along the wall, MullW m wide                 -> FrameColor
  the rest    vision glass (or wall render)                              -> GlassColor
  roofs (|N.z| > 0.7)                                                    -> RoofColor
Bands and mullions are filtered with fwidth and fade to their area-average colour once a band is under ~1 px, so
aerials don't shimmer (moire).
"""
import unreal

eal = unreal.EditorAssetLibrary; MEL = unreal.MaterialEditingLibrary; tools = unreal.AssetToolsHelpers.get_asset_tools()

HLSL = r"""
float3 p = WP / 100.0;
float3 n = normalize(N);
float wall = 1.0 - smoothstep(0.55, 0.75, abs(n.z));
float z = p.z / max(FloorH, 0.5);
float u = (abs(n.x) > abs(n.y) ? p.y : p.x) / max(PaneW, 0.3);
float fz = frac(z);
float fu = frac(u);
float wz = max(fwidth(z), 1e-4);
float wu = max(fwidth(u), 1e-4);
float bw = saturate(BandW / max(FloorH, 0.5));
float mw = saturate(MullW / max(PaneW, 0.3));
float band = smoothstep(1.0 - bw - wz, 1.0 - bw + wz, fz);
float mull = smoothstep(1.0 - mw - wu, 1.0 - mw + wu, fu);
band = lerp(band, bw, saturate(wz * 2.5 - 0.5));
mull = lerp(mull, mw, saturate(wu * 2.5 - 0.5));
return float3(band * wall, mull * wall * (1.0 - band * wall), 1.0 - wall);
"""

# ground-floor retail (Kendall 29 Sep: "storefronts, not just building straight to the street"): below StoreTop (world
# cm) every wall becomes a shopfront - frames every 3 m, a sign band across the top 0.9 m. R = store mask, G = frame, B = sign
HLSL_STORE = r"""
float3 n = normalize(N);
float wall = 1.0 - smoothstep(0.55, 0.75, abs(n.z));
float inStore = (1.0 - smoothstep(StoreTop - 4.0, StoreTop + 4.0, WP.z)) * wall;
float u = (abs(n.x) > abs(n.y) ? WP.y : WP.x) / 300.0;
float fu = frac(u);
float wu = max(fwidth(u), 1e-4);
float fr = smoothstep(0.94 - wu, 0.94 + wu, fu);
float sgn = smoothstep(StoreTop - 95.0, StoreTop - 85.0, WP.z);
return float3(inStore, fr * (1.0 - sgn), sgn);
"""
STORE_TOP = None          # world cm; set by the build (land level + 5.5 m) before parent() is first called


def _param(mat, cls, name, dv, x, y):
    e = MEL.create_material_expression(mat, cls, x, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("default_value", dv)
    return e


def parent(folder):
    path = folder + "/M_DA_Facade2"
    if eal.does_asset_exist(path):
        return eal.load_asset(path)
    mat = tools.create_asset("M_DA_Facade2", folder, unreal.Material, unreal.MaterialFactoryNew())
    wp = MEL.create_material_expression(mat, unreal.MaterialExpressionWorldPosition, -1400, 0)
    nrm = MEL.create_material_expression(mat, unreal.MaterialExpressionVertexNormalWS, -1400, 120)
    sc = {}
    for i, (k, dv) in enumerate((("FloorH", 3.6), ("PaneW", 1.5), ("BandW", 0.9), ("MullW", 0.12))):
        sc[k] = _param(mat, unreal.MaterialExpressionScalarParameter, k, dv, -1400, 240 + 90 * i)
    cu = MEL.create_material_expression(mat, unreal.MaterialExpressionCustom, -1050, 100)
    cu.set_editor_property("code", HLSL)
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ins = []
    for nm in ("WP", "N", "FloorH", "PaneW", "BandW", "MullW"):
        ci = unreal.CustomInput(); ci.set_editor_property("input_name", nm); ins.append(ci)
    cu.set_editor_property("inputs", ins)
    MEL.connect_material_expressions(wp, "", cu, "WP"); MEL.connect_material_expressions(nrm, "", cu, "N")
    for k, e in sc.items():
        MEL.connect_material_expressions(e, "", cu, k)
    masks = {}
    for i, ch in enumerate(("R", "G", "B")):
        m = MEL.create_material_expression(mat, unreal.MaterialExpressionComponentMask, -800, 40 + 100 * i)
        m.set_editor_property("r", ch == "R"); m.set_editor_property("g", ch == "G"); m.set_editor_property("b", ch == "B")
        MEL.connect_material_expressions(cu, "", m, ""); masks[ch] = m
    V = unreal.MaterialExpressionVectorParameter; S = unreal.MaterialExpressionScalarParameter

    st = _param(mat, unreal.MaterialExpressionScalarParameter, "StoreTop", float(STORE_TOP if STORE_TOP is not None else 700.0), -1400, 700)
    cs = MEL.create_material_expression(mat, unreal.MaterialExpressionCustom, -1050, 700)
    cs.set_editor_property("code", HLSL_STORE)
    cs.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ins2 = []
    for nm in ("WP", "N", "StoreTop"):
        ci = unreal.CustomInput(); ci.set_editor_property("input_name", nm); ins2.append(ci)
    cs.set_editor_property("inputs", ins2)
    MEL.connect_material_expressions(wp, "", cs, "WP"); MEL.connect_material_expressions(nrm, "", cs, "N")
    MEL.connect_material_expressions(st, "", cs, "StoreTop")
    smask = {}
    for i, ch in enumerate(("R", "G", "B")):
        m = MEL.create_material_expression(mat, unreal.MaterialExpressionComponentMask, -800, 700 + 100 * i)
        m.set_editor_property("r", ch == "R"); m.set_editor_property("g", ch == "G"); m.set_editor_property("b", ch == "B")
        MEL.connect_material_expressions(cs, "", m, ""); smask[ch] = m

    def store(prop_in, sglass, sframe, ssign, y):
        """shopfront layer over the tower's own layer (prop_in) where the store mask is set"""
        a1 = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -100, y)
        MEL.connect_material_expressions(sglass, "", a1, "A"); MEL.connect_material_expressions(sframe, "", a1, "B")
        MEL.connect_material_expressions(smask["G"], "", a1, "Alpha")
        a2 = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 0, y)
        MEL.connect_material_expressions(a1, "", a2, "A"); MEL.connect_material_expressions(ssign, "", a2, "B")
        MEL.connect_material_expressions(smask["B"], "", a2, "Alpha")
        a3 = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 100, y)
        MEL.connect_material_expressions(prop_in, "", a3, "A"); MEL.connect_material_expressions(a2, "", a3, "B")
        MEL.connect_material_expressions(smask["R"], "", a3, "Alpha")
        return a3

    def layer(prop, glass, frame, span, roof, y, shop=None):
        l1 = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -450, y)
        MEL.connect_material_expressions(glass, "", l1, "A"); MEL.connect_material_expressions(frame, "", l1, "B")
        MEL.connect_material_expressions(masks["G"], "", l1, "Alpha")
        l2 = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -300, y)
        MEL.connect_material_expressions(l1, "", l2, "A"); MEL.connect_material_expressions(span, "", l2, "B")
        MEL.connect_material_expressions(masks["R"], "", l2, "Alpha")
        l3 = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -150, y)
        MEL.connect_material_expressions(l2, "", l3, "A"); MEL.connect_material_expressions(roof, "", l3, "B")
        MEL.connect_material_expressions(masks["B"], "", l3, "Alpha")
        out = store(l3, shop[0], shop[1], shop[2], y) if shop else l3
        MEL.connect_material_property(out, "", prop)

    g = _param(mat, V, "GlassColor", unreal.LinearColor(0.25, 0.32, 0.38, 1), -700, -500)
    f = _param(mat, V, "FrameColor", unreal.LinearColor(0.55, 0.56, 0.57, 1), -700, -420)
    s = _param(mat, V, "SpandrelColor", unreal.LinearColor(0.18, 0.2, 0.22, 1), -700, -340)
    r = _param(mat, V, "RoofColor", unreal.LinearColor(0.45, 0.44, 0.42, 1), -700, -260)
    sg = _param(mat, V, "StoreGlass", unreal.LinearColor(0.16, 0.11, 0.06, 1), -700, -180)
    sf = _param(mat, V, "StoreFrame", unreal.LinearColor(0.05, 0.05, 0.05, 1), -700, -100)
    ss = _param(mat, V, "SignColor", unreal.LinearColor(0.07, 0.07, 0.075, 1), -700, -20)
    layer(unreal.MaterialProperty.MP_BASE_COLOR, g, f, s, r, -400, (sg, sf, ss))
    gr = _param(mat, S, "GlassRough", 0.08, -700, 420); fr = _param(mat, S, "FrameRough", 0.4, -700, 480)
    sr = _param(mat, S, "SpandrelRough", 0.3, -700, 540); rr = _param(mat, S, "RoofRough", 0.85, -700, 600)
    k1 = _param(mat, S, "StoreGlassRough", 0.05, -700, 640); k2 = _param(mat, S, "StoreFrameRough", 0.4, -700, 660)
    layer(unreal.MaterialProperty.MP_ROUGHNESS, gr, fr, sr, rr, 450, (k1, k2, k2))
    gm = _param(mat, S, "GlassMetal", 0.6, -700, 700); fm = _param(mat, S, "FrameMetal", 0.8, -700, 760)
    sm = _param(mat, S, "SpandrelMetal", 0.4, -700, 820); rm = _param(mat, S, "RoofMetal", 0.0, -700, 880)
    k3 = _param(mat, S, "StoreGlassMetal", 0.2, -700, 920); k4 = _param(mat, S, "StoreFrameMetal", 0.8, -700, 940)
    layer(unreal.MaterialProperty.MP_METALLIC, gm, fm, sm, rm, 750, (k3, k4, k1))
    sp = _param(mat, S, "Specular", 0.6, -300, 950)
    MEL.connect_material_property(sp, "", unreal.MaterialProperty.MP_SPECULAR)
    MEL.recompile_material(mat); eal.save_asset(path)
    return mat


_MI = {}


def instance(par, folder, key, glass, frame, spandrel, roof=(0.45, 0.44, 0.42), floor_h=3.6, pane_w=1.5, band_w=0.9,
             mull_w=0.12, glass_rough=0.08, frame_rough=0.4, glass_metal=0.6, frame_metal=0.8, spandrel_rough=0.3,
             spandrel_metal=0.4, specular=0.6, store=True):
    name = "MI_DA_Facade2_%s" % key
    if name in _MI:
        return _MI[name]
    p = "%s/%s" % (folder, name)
    if eal.does_asset_exist(p):
        m = eal.load_asset(p)
    else:
        m = tools.create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(m, par)
    for k, c in (("GlassColor", glass), ("FrameColor", frame), ("SpandrelColor", spandrel), ("RoofColor", roof)):
        MEL.set_material_instance_vector_parameter_value(m, k, unreal.LinearColor(c[0], c[1], c[2], 1.0))
    for k, v in (("FloorH", floor_h), ("PaneW", pane_w), ("BandW", band_w), ("MullW", mull_w), ("GlassRough", glass_rough),
                 ("FrameRough", frame_rough), ("GlassMetal", glass_metal), ("FrameMetal", frame_metal),
                 ("SpandrelRough", spandrel_rough), ("SpandrelMetal", spandrel_metal), ("Specular", specular)):
        MEL.set_material_instance_scalar_parameter_value(m, k, float(v))
    if STORE_TOP is not None:
        MEL.set_material_instance_scalar_parameter_value(m, "StoreTop", float(STORE_TOP if store else -1.0e7))
    MEL.update_material_instance(m); eal.save_asset(p)
    _MI[name] = m
    return m
