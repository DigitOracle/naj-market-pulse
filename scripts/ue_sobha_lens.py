"""Unreal Editor Python: bring the Sobha districts in at LOD 3 and light only Sobha's buildings.

Run INSIDE Unreal Engine 5.8 (Edit -> Plugins -> "Python Editor Script Plugin" and "Datasmith Importer" on):
  Window -> Output Log -> Cmd: py "C:/Dev/naj-market-pulse/scripts/ue_sobha_lens.py"
or  UnrealEditor-Cmd.exe <project>.uproject -run=pythonscript -script="C:/Dev/naj-market-pulse/scripts/ue_sobha_lens.py"

What it does, from data/ce/_datasmith/sobha_unreal.json (build_ue_sobha_manifest.py):
  1. For every district in the manifest, imports <slug>_lod3.udatasmith into /Game/Najma/<slug> unless a
     DatasmithSceneActor for it is already in the level (re-runs never duplicate a district). All exports
     share one CityEngine global offset, so they land in one world.
  2. Finds every actor whose label starts with a Sobha footprint prefix ("b<i>_") from the manifest and
     tags it "sobha", "sobha:<method>", "sobha:<project name>"; every other building actor is tagged "other".
  3. Materials, made once under /Game/Najma/Sobha: MI_Sobha (the house Sobha coral #E07A5F, opaque) for
     buildings reached by parcel / DM, MI_Sobha_Soft (same colour, translucent 0.5) for radius / geocode hits
     and register placeholders - a guess never reads as a survey, in Unreal exactly as on the web twin.
     Applied to every material slot of the Sobha actors (facade detail stays in the mesh; colour says whose).
  4. SOBHA_ONLY: hides every other building (SetActorHiddenInGame + editor visibility); ground, sky and
     context are untouched. Set SOBHA_ONLY = False to keep the city and only colour Sobha.
  5. A CineCameraActor "CAM_Sobha" framed on the bounds of the Sobha buildings, 4:5 filmback, as the hero
     clip README sets it, so a Sequencer orbit can start from it.

Everything it makes is named so it can be found and removed: actors CAM_Sobha, assets under /Game/Najma/Sobha,
tags "sobha*" / "other". Nothing existing is deleted.
"""
import json, os, re

import unreal

MANIFEST = r"C:/Dev/naj-market-pulse/data/ce/_datasmith/sobha_unreal.json"
GAME_ROOT = "/Game/Najma"
SOBHA_DIR = GAME_ROOT + "/Sobha"
SOBHA_ONLY = True
REIMPORT = os.environ.get("SOBHA_REIMPORT") == "1"
CLEAN = os.environ.get("SOBHA_CLEAN") == "1"   # delete /Game/Najma/<slug> outright before reimport (a disk-full window corrupted every mesh reference at once, 24 Sep 2026)
PLACEHOLDER_CORAL = os.environ.get("SOBHA_PLACEHOLDER_CORAL") == "1"   # off: placeholders wear their rule facade (client cut)   # re-exported Datasmith (new facades): purge every district and import again
COLOUR = unreal.LinearColor(0.878, 0.478, 0.373, 1.0)     # #E07A5F, the DEVCOL the web twin uses for Sobha
BASE_MAT = "/Engine/BasicShapes/BasicShapeMaterial"       # has a "Color" vector parameter; ships with every project

log = unreal.log
eal = unreal.EditorAssetLibrary
ell = unreal.EditorLevelLibrary


def ensure_material(name, translucent):
    path = "%s/%s" % (SOBHA_DIR, name)
    if eal.does_asset_exist(path):
        return eal.load_asset(path)
    if not eal.does_directory_exist(SOBHA_DIR):
        eal.make_directory(SOBHA_DIR)
    base = eal.load_asset(BASE_MAT)
    mic = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, SOBHA_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    unreal.MaterialEditingLibrary.set_material_instance_parent(mic, base)
    unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mic, "Color", COLOUR)
    if translucent:
        ov = unreal.MaterialInstanceBasePropertyOverrides()
        ov.set_editor_property("override_blend_mode", True)
        ov.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        mic.set_editor_property("base_property_overrides", ov)
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(mic, "Opacity", 0.5)
    unreal.MaterialEditingLibrary.update_material_instance(mic)
    eal.save_asset(path)
    return mic


def _descendants(a):
    out = []
    for c in a.get_attached_actors():
        out.append(c); out.extend(_descendants(c))
    return out


def district_present(slug):
    """True when the district's Datasmith scene is in the level AND its meshes still exist. 24 Sep 2026: a level saved
    without its imported assets (the meshes were only ever in memory) comes back as actors with no static mesh - every
    tower invisible. Such a district is purged here so the import runs again."""
    for a in ell.get_all_level_actors():
        if isinstance(a, unreal.DatasmithSceneActor) and slug in (a.get_actor_label() or "").lower():
            kids = _descendants(a)
            broken = [k for k in kids if isinstance(k, unreal.StaticMeshActor) and k.static_mesh_component.static_mesh is None]
            if REIMPORT and not broken:
                log("  %s: SOBHA_REIMPORT set - purging %d actors so the fresh export is taken" % (slug, len(kids))); broken = kids
            if broken:
                log("  %s: %d of %d imported actors have no mesh (assets never saved) - purging and re-importing" % (slug, len(broken), len(kids)))
                for k in kids:
                    ell.destroy_actor(k)
                ell.destroy_actor(a)
                return False
            return True
    return False


def import_district(slug, path):
    dest = "%s/%s" % (GAME_ROOT, slug)
    if district_present(slug):
        if CLEAN:
            log("  %s: SOBHA_CLEAN set - deleting %s outright before reimport" % (slug, dest))
        else:
            log("  %s: already in the level" % slug); return True
    if not os.path.exists(path):
        log("  %s: no export at %s" % (slug, path)); return False
    if CLEAN and eal.does_directory_exist(dest):
        # 24 Sep 2026: a disk-full window corrupted every Sobha district's saved mesh references at once (every actor
        # in the level came back with static_mesh == None). Re-importing into the SAME asset path with the corrupted
        # (but still name-registered) assets already there produced uniformly wrong/black materials across the whole
        # city, not just the districts whose export actually changed. Deleting the path outright first - not just the
        # level actors - forces Datasmith to create every mesh and material from nothing, so nothing stale can collide.
        eal.delete_directory(dest)
    scene = unreal.DatasmithSceneElement.construct_datasmith_scene_from_file(path)
    if scene is None:
        log("  %s: Datasmith could not open %s" % (slug, path)); return False
    opts = scene.get_options()
    try:
        opts.base_options.include_light = False; opts.base_options.include_camera = False; opts.base_options.include_animation = False
        opts.base_options.static_mesh_options.generate_lightmap_u_vs = False
    except Exception as e:
        log("  (import options left default: %s)" % e)
    res = scene.import_scene(dest)
    scene.destroy_scene()
    n = len(res.imported_actors) if res and res.import_succeed else 0
    # the meshes and materials Datasmith just made exist only in memory until saved; a level saved without them
    # references nothing (24 Sep 2026: 218 invisible towers, two renders of sky)
    try:
        eal.save_directory(dest, only_if_is_dirty=False, recursive=True)
    except Exception as e:
        log("  %s: asset save failed: %s" % (slug, e))
    log("  %s: imported %d actors -> %s (assets saved)" % (slug, n, dest))
    return bool(res and res.import_succeed)


LEVEL = "/Game/Main"


def main():
    # headless (-run=pythonscript) starts on an untitled level: the import then lands in a level that cannot be saved and
    # Main.umap never sees it (24 Sep 2026). Load Main unless it is already the current level (the editor's startup path).
    try:
        cur = unreal.EditorLevelLibrary.get_editor_world().get_path_name()
    except Exception:
        cur = ""
    if not cur.startswith(LEVEL):
        log("Sobha lens: loading %s (current world %s)" % (LEVEL, cur or "none"))
        ell.load_level(LEVEL)
    m = json.load(open(MANIFEST, encoding="utf-8"))
    log("Sobha lens: %d districts, LOD %s, %s" % (len(m["districts"]), m.get("lod"), m.get("rule")))
    mi_solid = ensure_material("MI_Sobha", False)
    mi_soft = ensure_material("MI_Sobha_Soft", True)
    prefixes = {}   # "b<i>_" -> (slug, record)
    for slug, d in m["districts"].items():
        import_district(slug, d["udatasmith"])
        for pre, rec in d["actors"].items():
            prefixes[pre] = (slug, rec)
    bld_re = re.compile(r"^b(\d+)_")
    solid = soft = other = dup = 0
    # a building that stands in two districts' files (their geojsons overlap at the edges) arrives twice in one level: once per
    # manifest (duplicate_of, decided by centroid), and once more by world position for anything the manifest did not cover -
    # the first actor at a location stays, later ones at the same spot (within 1 m) are hidden, never deleted
    seen_xy = {}
    bounds_min, bounds_max = None, None
    for a in ell.get_all_level_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        label = a.get_actor_label() or ""
        mt = bld_re.match(label)
        if not mt:
            continue
        pre = "b%s_" % mt.group(1)
        hit = prefixes.get(pre)
        tags = [t for t in list(a.tags) if not (str(t).startswith("sobha") or str(t) == "other")]
        loc = a.get_actor_location(); xy = (round(loc.x / 100.0), round(loc.y / 100.0))
        if (hit and hit[1].get("duplicate_of")) or xy in seen_xy:
            a.set_actor_hidden_in_game(True); a.set_is_temporarily_hidden_in_editor(True); a.tags = tags + ["duplicate", "duplicate_of:" + str((hit[1].get("duplicate_of") if hit else seen_xy.get(xy)))]
            dup += 1; continue
        seen_xy[xy] = label
        if hit:
            slug, rec = hit
            # v2 (24 Sep 2026, first fly-through): the LOD 3 facade materials CityEngine exported (wall / reveal / mullion /
            # glass / parapet) stay on every real building, because the facade IS what Kendall is assessing. Only register
            # placeholders (plain boxes from the DM permit) take the translucent coral, so a guess still reads as a guess.
            comp = a.static_mesh_component
            if rec.get("register_placeholder") and PLACEHOLDER_CORAL:
                for si in range(comp.get_num_materials()):
                    comp.set_material(si, mi_soft)
            else:
                # 24 Sep 2026, for the client cut: register placeholders wear the facade the rule gave them (from Sobha's own
                # renderings) like every other building. The fact that they are placeholders stays in the tags and the
                # manifest; SOBHA_PLACEHOLDER_CORAL=1 brings the translucent coral back for an internal audit view.
                mesh = comp.static_mesh   # an earlier lens run painted every slot coral; put the exported facade materials back
                for si in range(comp.get_num_materials()):
                    try:
                        comp.set_material(si, mesh.get_material(si))
                    except Exception:
                        pass
            tags += ["sobha", "sobha:" + str(rec.get("method")), "sobha:" + str(rec.get("name") or ""), "district:" + slug]
            if rec.get("soft"): soft += 1
            else: solid += 1
            a.set_actor_hidden_in_game(False); a.set_is_temporarily_hidden_in_editor(False)
            o, e = a.get_actor_bounds(False)
            lo, hi = o - e, o + e
            bounds_min = lo if bounds_min is None else unreal.Vector(min(bounds_min.x, lo.x), min(bounds_min.y, lo.y), min(bounds_min.z, lo.z))
            bounds_max = hi if bounds_max is None else unreal.Vector(max(bounds_max.x, hi.x), max(bounds_max.y, hi.y), max(bounds_max.z, hi.z))
        else:
            tags.append("other"); other += 1
            if SOBHA_ONLY:
                a.set_actor_hidden_in_game(True); a.set_is_temporarily_hidden_in_editor(True)
        a.tags = tags
    log("  Sobha solid %d, soft %d, other buildings %d (%s), duplicates hidden %d" % (solid, soft, other, "hidden" if SOBHA_ONLY else "kept", dup))
    if bounds_min is not None:
        c = (bounds_min + bounds_max) * 0.5; size = bounds_max - bounds_min
        r = max(size.x, size.y, size.z * 1.2, 16000.0)
        cam = None
        for a in ell.get_all_level_actors():
            if a.get_actor_label() == "CAM_Sobha": cam = a
        if cam is None:
            cam = ell.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(0, 0, 0))
            cam.set_actor_label("CAM_Sobha")
        cam.set_actor_location(unreal.Vector(c.x - r * 2.2, c.y + r * 0.6, c.z + r * 1.1), False, False)
        look = unreal.MathLibrary.find_look_at_rotation(cam.get_actor_location(), unreal.Vector(c.x, c.y, c.z * 0.4))
        cam.set_actor_rotation(look, False)
        try:
            cc = cam.camera_component
            cc.filmback.sensor_width = 24.0; cc.filmback.sensor_height = 30.0
            cc.current_focal_length = 32.0; cc.current_aperture = 8.0
            cc.focus_settings.focus_method = unreal.CameraFocusMethod.MANUAL; cc.focus_settings.manual_focus_distance = r * 2.5
        except Exception as e:
            log("  (camera left at defaults: %s)" % e)
        log("  CAM_Sobha framed on %.0f m x %.0f m of Sobha buildings" % (size.x / 100.0, size.y / 100.0))
    try:
        eal.save_directory(SOBHA_DIR, only_if_is_dirty=False, recursive=True)
        ell.save_current_level()
    except Exception as e:
        log("  final save: %s" % e)
    log("Sobha lens done.")


if __name__ == "__main__":
    main()
