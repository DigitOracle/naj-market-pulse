"""LAB #4 (instancing) - Unreal Editor Python, NOT RUN by the lab (research only; run it by hand in a scratch level).

Places data/lab/instances/<slug>_instances_ue.csv as ONE HierarchicalInstancedStaticMeshComponent per asset role - 7 components
for the 7,260 alhebiahfifth instances, where Datasmith straight out of PyPRT gives 4,470 HISM actors (one per initial shape per asset).

CSV contract (scripts/lab_instances_build.py): x_cm, y_cm, z_cm in the repo's Unreal world frame (UE x = (E - 328289) * 100,
UE y = (2784598 - N) * 100 - the same frame as ue_furniture.py and build_foliage_points.py), yaw_deg already negated from the CE
yaw (CE is right-handed y-up, Unreal left-handed z-up), target_m = the height (or length, size_axis "len") the rule gave the
instance. Scale is recomputed here from the Unreal mesh's own bounds, so any mesh can stand in for the library asset.

Mesh per role: ROLE_MESH below; a role with no mesh imports the ESRI.lib GLB it was generated from (Interchange glTF import)
into /Game/DA/Lab/Instances. Rotator is built with KEYWORDS - positional order differs between the C++ and Python signatures.

  UnrealEditor-Cmd.exe <project> -run=pythonscript -script="C:/Dev/naj-market-pulse/scripts/lab_instances_ue_hism.py"
  (or paste into the editor's Python console with a scratch level open)
"""
import csv
import os
import unreal

SLUG = "alhebiahfifth"
CSV = "C:/Dev/naj-market-pulse/data/lab/instances/%s_instances_ue.csv" % SLUG
LIB = os.path.expanduser("~/OneDrive/Documents/CityEngine/Default Workspace/ESRI.lib/assets/Webstyles/")
DEST = "/Game/DA/Lab/Instances"
GROUND_Z = 5.0                  # cm, as ue_sobha_foliage.py
TAG = "lab_instances"
NAJMA = "/Game/DA/Najma/Models/"
ROLE_MESH = {                   # role -> existing Unreal mesh (None = import the Esri GLB below)
    "date_palm": NAJMA + "esri_plant_phoenixdactylifera/PhoenixDactylifera/StaticMeshes/PhoenixDactylifera",
    "washingtonia": NAJMA + "esri_plant_washingtoniafilifera/WashingtoniaFilifera/StaticMeshes/WashingtoniaFilifera",
    "shade_tree": NAJMA + "esri_plant_acaciatortilis/AcaciaTortilis/StaticMeshes/AcaciaTortilis",
    "coconut_palm": None, "lamp": None, "bench": None, "bin": None,
}
ROLE_GLB = {"coconut_palm": LIB + "Vegetation/Realistic/CocosNucifera.glb", "lamp": LIB + "StreetScene/Light_On_Post_-_Light_off.glb",
            "bench": LIB + "StreetScene/Park_Bench_1.glb", "bin": LIB + "StreetScene/Trash_Bin_1.glb"}
eal = unreal.EditorAssetLibrary
ell = unreal.EditorLevelLibrary


def import_glb(path, role):
    task = unreal.AssetImportTask()
    task.filename = path; task.destination_path = DEST + "/" + role
    task.automated = True; task.replace_existing = True; task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    meshes = [p for p in eal.list_assets(task.destination_path, recursive=True) if isinstance(eal.load_asset(p), unreal.StaticMesh)]
    return eal.load_asset(meshes[0]) if meshes else None


def flag_for_instancing(mesh):
    """base materials must allow instanced static meshes, or HISM draws them with the default material (ue_sobha_foliage v15)"""
    for sm in mesh.get_editor_property("static_materials"):
        base = sm.get_editor_property("material_interface")
        while isinstance(base, unreal.MaterialInstance):
            base = base.get_editor_property("parent")
        if isinstance(base, unreal.Material) and not base.get_editor_property("used_with_instanced_static_meshes"):
            base.set_editor_property("used_with_instanced_static_meshes", True)
            unreal.MaterialEditingLibrary.recompile_material(base); eal.save_loaded_asset(base)


def hism_actor(label, mesh):
    """an empty actor carrying one HISM component, built through the SubobjectDataSubsystem (UE 5.1+)"""
    actor = ell.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0))
    actor.set_actor_label(label); actor.tags = [unreal.Name(TAG)]
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    root = sds.k2_gather_subobject_data_for_instance(actor)[0]
    handle, fail = sds.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root,
                                                                     new_class=unreal.HierarchicalInstancedStaticMeshComponent))
    if not fail.is_empty():
        raise RuntimeError(str(fail))
    comp = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle))
    comp.set_static_mesh(mesh)
    comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
    return actor, comp


def main():
    for a in list(ell.get_all_level_actors()):          # a re-run replaces, never stacks
        if TAG in [str(t) for t in a.tags]:
            a.destroy_actor()
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    by_role = {}
    for r in rows:
        by_role.setdefault(r["ue_role"], []).append(r)
    total = 0
    for role, rs in sorted(by_role.items()):
        mesh = eal.load_asset(ROLE_MESH[role]) if ROLE_MESH.get(role) else import_glb(ROLE_GLB[role], role)
        if mesh is None:
            unreal.log_warning("lab_instances: no mesh for %s, %d instances skipped" % (role, len(rs))); continue
        flag_for_instancing(mesh)
        b = mesh.get_bounds()
        native = {"h": 2.0 * b.box_extent.z, "len": 2.0 * max(b.box_extent.x, b.box_extent.y)}      # cm
        zmin = b.origin.z - b.box_extent.z
        tfs = []
        for r in rs:
            s = float(r["target_m"]) * 100.0 / max(1.0, native[r["size_axis"]])
            tfs.append(unreal.Transform(location=unreal.Vector(float(r["x_cm"]), float(r["y_cm"]), float(r["z_cm"]) + GROUND_Z - zmin * s),
                                        rotation=unreal.Rotator(roll=0.0, pitch=0.0, yaw=float(r["yaw_deg"])),
                                        scale=unreal.Vector(s, s, s)))
        try:
            actor, comp = hism_actor("LAB_%s_%s" % (SLUG, role), mesh)
            for k in range(0, len(tfs), 5000):
                comp.add_instances(tfs[k:k + 5000], False, True)            # (transforms, should_return_indices, world_space)
        except Exception as e:                                               # fallback: the foliage system, as ue_sobha_foliage.py
            unreal.log_warning("lab_instances: HISM component failed (%s) - using InstancedFoliageActor for %s" % (e, role))
            ft = unreal.AssetToolsHelpers.get_asset_tools().create_asset("FT_lab_" + role, DEST + "/Foliage",
                                                                         unreal.FoliageType_InstancedStaticMesh,
                                                                         unreal.FoliageType_InstancedStaticMeshFactory())
            ft.set_editor_property("mesh", mesh)
            for k in range(0, len(tfs), 5000):
                unreal.InstancedFoliageActor.add_instances(ell.get_editor_world(), ft, tfs[k:k + 5000])
        total += len(tfs)
        unreal.log("lab_instances: %-13s %5d instances of %s" % (role, len(tfs), mesh.get_path_name()))
    unreal.log("lab_instances: %d instances in %d HISM components" % (total, len(by_role)))


if __name__ == "__main__":
    main()
