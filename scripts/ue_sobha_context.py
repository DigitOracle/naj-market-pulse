"""Unreal (commandlet): the v8 context layer for the Sobha tour - ghost massing for every other building within a block or two,
and the streets, parks and parking under it. Meshes from scripts/build_sobha_context_meshes.py (data/ce/_datasmith/context).

  CTX_buildings   M_SobhaGhost: translucent, lit per pixel, near-white, opacity GHOST_OPACITY, two-sided, casts no shadow -
                  "very very light", there to say "city" without competing with the Sobha towers. No labels.
  CTX_<layer>     asphalt / pavement / parking / grass / pitch / pool: opaque, two-sided, the colour/roughness/specular the
                  context builder carries per layer (scripts/ue_context_layer.py), a few cm above the sand.
After import each actor's bounds are checked against the bounds the builder wrote; if the OBJ importer mirrored Y the actor is
given scale Y = -1 (and the log says so), so roads never end up on the wrong side of the towers.
Re-running replaces the CTX_ actors; meshes are re-imported when the OBJ is newer than the asset (SOBHA_CTX_REIMPORT=1 forces).
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_context.py
"""
import json, os

import unreal

LEVEL = "/Game/Main"; CTX_DIR = "/Game/Najma/Sobha/Context"
SRC = "C:/Dev/naj-market-pulse/data/ce/_datasmith/context"
GHOST_OPACITY = float(os.environ.get("SOBHA_GHOST_OPACITY", "0.16"))
log = unreal.log; eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary; MEL = unreal.MaterialEditingLibrary


def lin(c):
    c = [float(x) for x in (c or [0.5, 0.5, 0.5])[:3]]
    if max(c) > 1.0:
        c = [x / 255.0 for x in c]
    return [x ** 2.2 for x in c]          # context colours are display (sRGB) values


def const3(mat, rgb, x, y):
    n = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, x, y)
    n.constant = unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0); return n


def const(mat, v, x, y):
    n = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, x, y); n.r = float(v); return n


def new_material(name):
    p = "%s/%s" % (CTX_DIR, name)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    if not eal.does_directory_exist(CTX_DIR):
        eal.make_directory(CTX_DIR)
    return unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, CTX_DIR, unreal.Material, unreal.MaterialFactoryNew()), p


def ghost_material():
    mat, p = new_material("M_SobhaGhost")
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    mat.set_editor_property("two_sided", True)
    try:
        mat.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
    except Exception:
        pass
    MEL.connect_material_property(const3(mat, [0.80, 0.83, 0.88], -400, -100), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(const(mat, GHOST_OPACITY, -400, 100), "", unreal.MaterialProperty.MP_OPACITY)
    MEL.connect_material_property(const(mat, 0.35, -400, 200), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def surface_material(layer, info):
    mat, p = new_material("M_Ctx_%s" % layer)
    mat.set_editor_property("two_sided", True)
    MEL.connect_material_property(const3(mat, lin(info.get("rgb")), -400, -100), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(const(mat, info.get("roughness") if info.get("roughness") is not None else 0.9, -400, 100), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(const(mat, info.get("specular") if info.get("specular") is not None else 0.3, -400, 200), "", unreal.MaterialProperty.MP_SPECULAR)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def import_mesh(name):
    p = "%s/SM_%s" % (CTX_DIR, name)
    src = os.path.join(SRC, "%s.obj" % name)
    if not os.path.exists(src):
        return None
    if eal.does_asset_exist(p) and os.environ.get("SOBHA_CTX_REIMPORT") != "1":
        try:
            if os.path.getmtime(src) < os.path.getmtime(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()) + "Najma/Sobha/Context/SM_%s.uasset" % name):
                return eal.load_asset(p)
        except Exception:
            return eal.load_asset(p)
    task = unreal.AssetImportTask()
    task.filename = src; task.destination_path = CTX_DIR; task.destination_name = "SM_%s" % name
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


def place(label, mesh, mat, expect, shadows):
    for a in ell.get_all_level_actors():
        if str(a.get_actor_label() or "") == label:
            ell.destroy_actor(a)
    a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
    a.set_actor_label(label)
    c = a.static_mesh_component
    c.set_static_mesh(mesh)
    for si in range(max(1, c.get_num_materials())):
        c.set_material(si, mat)
    c.set_cast_shadow(shadows)
    note = ""
    if expect:
        o, e = a.get_actor_bounds(False)
        ey = (expect[1] + expect[3]) / 2.0; ex = (expect[0] + expect[2]) / 2.0
        if abs(o.y - ey) > abs(o.y + ey) and abs(ey) > 5000:
            a.set_actor_scale3d(unreal.Vector(1, -1, 1)); note = " (importer mirrored Y - corrected)"
        if abs(o.x - ex) > abs(o.x + ex) and abs(ex) > 5000:
            s = a.get_actor_scale3d(); a.set_actor_scale3d(unreal.Vector(-1, s.y, 1)); note += " (mirrored X - corrected)"
        o, e = a.get_actor_bounds(False)
        note += " centre %.0f,%.0f m (expected %.0f,%.0f)" % (o.x / 100, o.y / 100, ex / 100, ey / 100)
    return note


def main(save=True):
    try:
        cur = ell.get_editor_world().get_path_name()
    except Exception:
        cur = ""
    if not cur.startswith(LEVEL):
        ell.load_level(LEVEL)
    meta_p = os.path.join(SRC, "context_meshes.json")
    if not os.path.exists(meta_p):
        log("Sobha context: no %s - run build_sobha_context_meshes.py" % meta_p); return
    meta = json.load(open(meta_p, encoding="utf-8"))
    ghost = ghost_material()
    n = 0
    for name, info in sorted(meta["meshes"].items()):
        m = import_mesh(name)
        if not m:
            continue
        if info.get("role") == "ghost":
            note = place("CTX_buildings", m, ghost, info.get("bounds_cm"), False)
            log("  CTX_buildings: %s ghost buildings%s" % (info.get("buildings"), note))
        else:
            layer = name[4:]
            note = place("CTX_%s" % layer, m, surface_material(layer, info), info.get("bounds_cm"), False)
            log("  CTX_%s: %s tris%s" % (layer, info.get("tris"), note))
        n += 1
    if save:
        eal.save_directory(CTX_DIR, only_if_is_dirty=False, recursive=True)
        ell.save_current_level()
    log("Sobha context: %d meshes placed (radius %s m)" % (n, meta.get("radius_m")))


if __name__ == "__main__":
    main()
