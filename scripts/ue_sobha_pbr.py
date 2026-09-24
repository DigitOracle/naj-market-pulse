"""Unreal (commandlet): give every Sobha building the colours of its own renderings - the "unreal" half of each look.

Kendall, 24 Sep 2026: tour v5 showed the towers as near-black blobs. Not a pipeline fault: CityEngine's Datasmith export
gives every facade material a flat TintColor (glass ~0.07-0.13 linear, i.e. dark navy) with no reflectivity, and the
per-look palette written into data/ce/<slug>/facade_refs.json ("unreal": walls / slabs / vision / fins / crown) was never
applied - the applier the pipeline expected (da_apply_pbr.py) was never written. This is it.

For each Sobha actor (tag "sobha", not "duplicate"): the district's facade_match.json names its look by footprint index;
each material slot is classified by its CityEngine name -
    vision / retail_glass / window_glass / balustrade   -> glass    (low roughness, metallic, the look's glass colour)
    spandrel                                             -> glass, a little rougher and darker (the opaque panel)
    balcony_slab / slab_band / parapet                   -> slabs
    *_wall                                               -> walls
    mullion / column / fin                               -> fins
    roof                                                 -> roof (neutral grey)
- and gets a material instance of M_SobhaPBR (Color, Roughness, Metallic, Specular), one per (look, role), under
/Game/Najma/Sobha/PBR. Unknown slots keep their CityEngine material. Nothing is deleted; re-running re-applies.
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_pbr.py
"""
import json, os, re

import unreal

LEVEL = "/Game/Main"
PBR_DIR = "/Game/Najma/Sobha/PBR"
CE = "C:/Dev/naj-market-pulse/data/ce"
log = unreal.log; eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary
MEL = unreal.MaterialEditingLibrary

# linear colour, roughness, metallic, specular
PALETTE = {
    "white":           ((0.80, 0.80, 0.78), 0.55, 0.0, 0.5),
    "pale_concrete":   ((0.62, 0.60, 0.56), 0.80, 0.0, 0.4),
    "warm_render":     ((0.62, 0.52, 0.40), 0.85, 0.0, 0.4),
    "cream_render":    ((0.72, 0.66, 0.54), 0.85, 0.0, 0.4),
    "dark_bronze":     ((0.18, 0.12, 0.08), 0.40, 0.7, 0.5),
    "bronze":          ((0.35, 0.22, 0.12), 0.35, 0.8, 0.5),
    "gold":            ((0.75, 0.55, 0.25), 0.30, 1.0, 0.5),
    "blue_glass":      ((0.14, 0.28, 0.46), 0.06, 0.6, 1.0),
    "deep_blue_glass": ((0.07, 0.18, 0.34), 0.05, 0.6, 1.0),
    "clear_glass":     ((0.32, 0.40, 0.44), 0.05, 0.5, 1.0),
    "bronze_glass":    ((0.34, 0.24, 0.15), 0.06, 0.5, 1.0),
    "tinted_glass":    ((0.18, 0.24, 0.28), 0.08, 0.4, 1.0),
    "akoya_glass":     ((0.20, 0.30, 0.40), 0.06, 0.5, 1.0),
    "dark_glass":      ((0.08, 0.10, 0.12), 0.06, 0.5, 1.0),
    "sandstone":       ((0.66, 0.55, 0.40), 0.85, 0.0, 0.4),
    "dark":            ((0.10, 0.10, 0.10), 0.60, 0.0, 0.4),
    "roof":            ((0.32, 0.32, 0.31), 0.90, 0.0, 0.3),
}
ROLE_OF = [
    (re.compile(r"spandrel", re.I), "spandrel"),
    (re.compile(r"vision|retail_glass|window_glass|balustrade", re.I), "vision"),
    (re.compile(r"balcony_slab|slab_band|parapet", re.I), "slabs"),
    (re.compile(r"mullion|column|fin", re.I), "fins"),
    (re.compile(r"roof", re.I), "roof"),
    (re.compile(r"_wall", re.I), "walls"),
]


def parent_material():
    p = PBR_DIR + "/M_SobhaPBR"
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    if not eal.does_directory_exist(PBR_DIR):
        eal.make_directory(PBR_DIR)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_SobhaPBR", PBR_DIR, unreal.Material, unreal.MaterialFactoryNew())
    col = MEL.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -500, -200)
    col.set_editor_property("parameter_name", "Color"); col.set_editor_property("default_value", unreal.LinearColor(0.8, 0.8, 0.8, 1))
    MEL.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for i, (name, prop, dv) in enumerate((("Roughness", unreal.MaterialProperty.MP_ROUGHNESS, 0.6),
                                          ("Metallic", unreal.MaterialProperty.MP_METALLIC, 0.0),
                                          ("Specular", unreal.MaterialProperty.MP_SPECULAR, 0.5))):
        s = MEL.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -500, 50 + 120 * i)
        s.set_editor_property("parameter_name", name); s.set_editor_property("default_value", dv)
        MEL.connect_material_property(s, "", prop)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


_CACHE = {}


def instance(parent, key, colour_name, rough_bias=0.0, dim=1.0):
    name = "MI_%s" % key
    if name in _CACHE:
        return _CACHE[name]
    p = "%s/%s" % (PBR_DIR, name)
    rgb, rough, metal, spec = PALETTE.get(colour_name, PALETTE["white"])
    if eal.does_asset_exist(p):
        mi = eal.load_asset(p)
    else:
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, PBR_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, parent)
    MEL.set_material_instance_vector_parameter_value(mi, "Color", unreal.LinearColor(rgb[0] * dim, rgb[1] * dim, rgb[2] * dim, 1.0))
    MEL.set_material_instance_scalar_parameter_value(mi, "Roughness", min(1.0, rough + rough_bias))
    MEL.set_material_instance_scalar_parameter_value(mi, "Metallic", metal)
    MEL.set_material_instance_scalar_parameter_value(mi, "Specular", spec)
    MEL.update_material_instance(mi); eal.save_asset(p)
    _CACHE[name] = mi
    return mi


def looks_by_district():
    out = {}
    for slug in os.listdir(CE):
        fm = os.path.join(CE, slug, "facade_match.json"); fr = os.path.join(CE, slug, "facade_refs.json")
        if not (os.path.exists(fm) and os.path.exists(fr)):
            continue
        refs = json.load(open(fr, encoding="utf-8"))
        match = json.load(open(fm, encoding="utf-8"))
        out[slug] = {int(i): (rec.get("look"), refs.get("looks", {}).get(rec.get("look"), {}).get("unreal", {})) for i, rec in match.items()}
    return out


def main():
    ell.load_level(LEVEL)
    parent = parent_material()
    looks = looks_by_district()
    bld_re = re.compile(r"^b(\d+)_")
    done = skipped = 0
    for a in ell.get_all_level_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        tags = [str(t) for t in a.tags]
        if "sobha" not in tags or "duplicate" in tags:
            continue
        m = bld_re.match(a.get_actor_label() or "")
        slug = next((t[9:] for t in tags if t.startswith("district:")), None)
        if not m or not slug:
            skipped += 1; continue
        look, pal = looks.get(slug, {}).get(int(m.group(1)), (None, {}))
        if not look:
            skipped += 1; continue
        vision = pal.get("vision", "clear_glass"); walls = pal.get("walls", "white"); slabs = pal.get("slabs", walls)
        fins = pal.get("fins", pal.get("crown", "white" if "glass" in vision else walls))
        comp = a.static_mesh_component
        for si in range(comp.get_num_materials()):
            cur = comp.get_material(si)
            nm = cur.get_name() if cur else ""
            role = next((r for rx, r in ROLE_OF if rx.search(nm)), None)
            if role is None:
                continue
            if role == "vision":
                mi = instance(parent, "%s_vision" % look, vision)
            elif role == "spandrel":
                mi = instance(parent, "%s_spandrel" % look, vision, rough_bias=0.10, dim=0.75)
            elif role == "slabs":
                mi = instance(parent, "%s_slabs" % look, slabs)
            elif role == "walls":
                # a glass tower's "wall" slot is its curtain wall: glass, not render
                # a glass-class wall slot (MI_glassblue_wall ...) is the curtain wall itself: it takes the glass colour
                if "glass" in nm.lower():
                    mi = instance(parent, "%s_curtain" % look, vision, rough_bias=0.04)
                else:
                    mi = instance(parent, "%s_walls" % look, walls)
            elif role == "fins":
                mi = instance(parent, "%s_fins" % look, fins)
            else:
                mi = instance(parent, "roof", "roof")
            comp.set_material(si, mi)
        done += 1
    eal.save_directory(PBR_DIR, only_if_is_dirty=False, recursive=True)
    ell.save_current_level()
    log("Sobha PBR: %d buildings re-coloured from their looks, %d skipped, %d material instances" % (done, skipped, len(_CACHE)))


if __name__ == "__main__":
    main()
