"""Unreal (commandlet): the Sobha tour's ground made in the engine - procedural sand, real water - instead of a satellite photo.

Kendall, 24 Sep 2026: "we really need to do something about the ground ... replace [the ArcGIS imagery] with something
nice from Unreal."

  GROUND_Sand    the 40 km plane (GROUND_Context, re-used) with M_SobhaSand: two sand tones lerped by large-scale
                 noise, fine noise breaking the surface, roughness 0.95 - reads as desert from 300 m and from 3 km.
  WATER_Sea      data/ce/_datasmith/ground/sea.obj (the Gulf, from the OSM coastline) with M_SobhaWater: deep
                 blue-green, roughness 0.04, specular 1, a little sky in it - glossy, not the Water plugin.
  WATER_Inland   inland_water.obj - Dubai Creek, the Water Canal, Hartland's lagoon, the Marina, lakes.
Both meshes sit 10 cm above the sand so they never z-fight with it. The imagery texture stays on disk; SOBHA_GROUND=imagery
puts it back (ue_sobha_tour.py reads the same switch).
Usage:  UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_ground.py
"""
import os, sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ue_sobha_flythrough as F

LEVEL = "/Game/Main"; SOBHA_DIR = "/Game/Najma/Sobha"; GROUND_DIR = SOBHA_DIR + "/Ground"
MESHES = "C:/Dev/naj-market-pulse/data/ce/_datasmith/ground"
log = unreal.log; eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary
MEL = unreal.MaterialEditingLibrary


def material(name, build):
    p = "%s/%s" % (GROUND_DIR, name)
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    if not eal.does_directory_exist(GROUND_DIR):
        eal.make_directory(GROUND_DIR)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, GROUND_DIR, unreal.Material, unreal.MaterialFactoryNew())
    build(mat)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def const3(mat, r, g, b, x, y):
    n = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, x, y)
    n.constant = unreal.LinearColor(r, g, b, 1.0); return n


def const(mat, v, x, y):
    n = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, x, y); n.r = v; return n


def build_sand(mat):
    macro = MEL.create_material_expression(mat, unreal.MaterialExpressionNoise, -900, -100)
    macro.set_editor_property("scale", 0.00002); macro.set_editor_property("levels", 3); macro.set_editor_property("output_min", 0.0); macro.set_editor_property("output_max", 1.0)
    fine = MEL.create_material_expression(mat, unreal.MaterialExpressionNoise, -900, 250)
    fine.set_editor_property("scale", 0.002); fine.set_editor_property("levels", 2); fine.set_editor_property("output_min", 0.85); fine.set_editor_property("output_max", 1.0)
    light = const3(mat, 0.82, 0.72, 0.52, -600, -250)      # warm pale sand
    dark = const3(mat, 0.55, 0.45, 0.31, -600, -50)        # the darker, gravelly sand
    lerp = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -400, -100)
    MEL.connect_material_expressions(light, "", lerp, "A"); MEL.connect_material_expressions(dark, "", lerp, "B"); MEL.connect_material_expressions(macro, "", lerp, "Alpha")
    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -200, 0)
    MEL.connect_material_expressions(lerp, "", mul, "A"); MEL.connect_material_expressions(fine, "", mul, "B")
    MEL.connect_material_property(mul, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(const(mat, 0.95, -200, 250), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(const(mat, 0.3, -200, 350), "", unreal.MaterialProperty.MP_SPECULAR)


def build_water(mat):
    MEL.connect_material_property(const3(mat, 0.02, 0.16, 0.22, -400, -100), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(const(mat, 0.04, -400, 100), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(const(mat, 1.0, -400, 200), "", unreal.MaterialProperty.MP_SPECULAR)
    MEL.connect_material_property(const(mat, 0.0, -400, 300), "", unreal.MaterialProperty.MP_METALLIC)


def import_mesh(name):
    p = "%s/SM_%s" % (GROUND_DIR, name)
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    src = os.path.join(MESHES, "%s.obj" % name)
    if not os.path.exists(src):
        log("  %s: no mesh at %s" % (name, src)); return None
    task = unreal.AssetImportTask()
    task.filename = src; task.destination_path = GROUND_DIR; task.destination_name = "SM_%s" % name
    task.automated = True; task.save = True; task.replace_existing = True
    opts = unreal.FbxImportUI()
    opts.import_mesh = True; opts.import_materials = False; opts.import_textures = False; opts.import_as_skeletal = False
    try:
        opts.static_mesh_import_data.set_editor_property("combine_meshes", True)
        opts.static_mesh_import_data.set_editor_property("generate_lightmap_u_vs", False)
        opts.static_mesh_import_data.set_editor_property("import_uniform_scale", 1.0)
    except Exception:
        pass
    task.options = opts
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    m = eal.load_asset(p)
    log("  %s: %s" % (name, "imported" if m else "IMPORT FAILED"))
    return m


def place(label, mesh, mat, z=10.0):
    a = F.find(label)
    if not a:
        a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, z)); a.set_actor_label(label)
    a.set_actor_location(unreal.Vector(0, 0, z), False, False)
    a.static_mesh_component.set_static_mesh(mesh)
    for si in range(max(1, a.static_mesh_component.get_num_materials())):
        a.static_mesh_component.set_material(si, mat)
    a.set_actor_hidden_in_game(False); a.set_is_temporarily_hidden_in_editor(False)


def main(save=True):
    try:
        cur = ell.get_editor_world().get_path_name()
    except Exception:
        cur = ""
    if not cur.startswith(LEVEL):
        ell.load_level(LEVEL)
    sand = material("M_SobhaSand", build_sand)
    water = material("M_SobhaWater", build_water)
    g = F.find("GROUND_Context") or F.find("GROUND_Sobha")
    if g:
        g.static_mesh_component.set_material(0, sand); g.set_actor_hidden_in_game(False); g.set_is_temporarily_hidden_in_editor(False)
        g.set_actor_label("GROUND_Sand")
        log("  GROUND_Sand: procedural sand on the 40 km plane")
    for name, label in (("sea", "WATER_Sea"), ("inland_water", "WATER_Inland")):
        m = import_mesh(name)
        if m:
            place(label, m, water)
    if save:
        ell.save_current_level()
    log("Sobha ground: sand + water in place")


if __name__ == "__main__":
    main()
