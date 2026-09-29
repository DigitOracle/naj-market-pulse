"""Unreal (commandlet): Business Bay "v0" whole-district fly-through - build the level (28 Sep 2026).

README
------
What:    a quick whole-area preview of Business Bay while the full rebuild (BusinessBay/ROADMAP_28SEP2026.md) proceeds,
         dressed from the new asset library (/Game/DA/Library, imported by ue_library_import.py) to showcase it:
         palms along the main roads, shade trees, hedges and bougainvillea on verges, lamps, benches, bins, bus shelters,
         parked + moving cars, moored + moving boats on the canal, dressed construction sites (cranes, fences, barriers).
Levels:  /Game/BusinessBay/L_BB_v0            persistent: sun/sky/fog, sand, water, streets, dressing, camera
         /Game/BusinessBay/L_BB_v0_Buildings  always-loaded sublevel: ONLY the Datasmith towers (+ Downtown/Burj backdrop),
                                              so the tower geometry source can be swapped without touching the rest
         No other level is opened or saved. Assets are written only under /Game/BusinessBay.
Order (one command: logs/bb_v0_run.ps1):
   1. ue_library_import.py --only <cat>   (Phase 0 importer, per category; idempotent)
   2. python scripts/bb_v0_prep.py        data/ce/_datasmith/bb_v0/{ctx_*.obj, bb_v0_plan.json}
   3. THIS SCRIPT                          build both levels
   4. ue_bb_v0_tour.py                     camera + movers sequence, MRQ config (1080 x 1920, 25 fps)
   5. MRQ render (-game)                   Saved/MovieRenders/BB_v0
   6. python scripts/bb_v0_encode.py       data/media/businessbay/bb_v0_9x16.mp4 (+ _share, credits), ep08 teaser
Buildings: Datasmith import of data/ce/_datasmith/businessbay_lod3.udatasmith ONLY through the .udatasmith (its Assets
         folder holds 49 stale meshes - never glob it). Same UE frame as the Ellington/Sobha levels (X = E - 328289,
         Y = 2784598 - N, cm); the import is checked against the footprints' bounds and shifted if it is off by > 200 m.
         Nanite on for every imported mesh. CityEngine's flat Datasmith tints render near-black, so every slot is
         re-materialed from its CE name (vision/spandrel/wall/slab/fin/roof, fclass glassblue/glassclear/...) with the
         ue_sobha_pbr.py palette on our own M_BB0_PBR (the Sobha PBR folder is never written).
Ground:  sand plane (procedural, ue_sobha_ground recipe), city water sea.obj / inland_water.obj with the mirror fix
         (ue_sobha_water_fix.py: the OBJ importer negates Y -> scale Y = -1), street layers from context_ue.json
         (asphalt/pavement/parking/grass/...) with ambientCG materials when the library has them.
Foliage/props: instanced (InstancedFoliageActor + one FoliageType per mesh part), Nanite meshes from the library; kits
         fall back to /Game/DA/Najma/Models plants if the library has none. Leaf materials flagged for instancing.
Memory:  8 GB VRAM / 32 GB RAM: instancing only, props limited to ~700 m around the low shots (see bb_v0_prep.py CAPS),
         BB_V0_FOLIAGE_SCALE=0.5 halves every scatter count. BB_V0_REIMPORT=1 re-imports the Datasmith towers.
Writes:  data/ce/_datasmith/bb_v0/used_assets.json (every library folder placed, for the credits file).
Usage:   UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_bb_v0_build.py
Log lines are prefixed "BB0:".
"""
import json, math, os, random, re, sys

import unreal

sys.path.insert(0, "C:/Dev/naj-market-pulse/scripts")
import ue_sobha_pbr as SP          # PALETTE + ROLE_OF only (read-only constants; its main() is never called)

REPO = "C:/Dev/naj-market-pulse"
LEVEL = "/Game/BusinessBay/L_BB_v0"
BLD_LEVEL = "/Game/BusinessBay/L_BB_v0_Buildings"
ROOT = "/Game/BusinessBay"
DS_BB, DS_BURJ = ROOT + "/Datasmith/BB", ROOT + "/Datasmith/Burj"
PBR_DIR, GROUND_DIR, CTX_DIR, FT_DIR, POST_DIR = ROOT + "/PBR", ROOT + "/Ground", ROOT + "/Context", ROOT + "/Foliage", ROOT + "/Post"
DATASMITH = REPO + "/data/ce/_datasmith/businessbay_lod3.udatasmith"
DATASMITH_BURJ = REPO + "/data/ce/_datasmith/burjkhalifa_lod3.udatasmith"
V0 = REPO + "/data/ce/_datasmith/bb_v0"
PLAN = V0 + "/bb_v0_plan.json"
USED = V0 + "/used_assets.json"
WATER_OBJ = REPO + "/data/ce/_datasmith/ground"
LIB = "/Game/DA/Library"
NAJMA = "/Game/DA/Najma/Models/"
SCALE = float(os.environ.get("BB_V0_FOLIAGE_SCALE", "1.0"))
PFX = "BB0_"
SUN_ELEV = float(os.environ.get("BB_V0_SUN_ELEV", "33"))
SKY_INT = float(os.environ.get("BB_V0_SKY", "1.2"))
FOG_RGB = (0.62, 0.74, 0.92)
SKY_CUBES = ["/Engine/MapTemplates/Sky/Desert_Outer_HDR", "/Engine/MapTemplates/Sky/SunsetAmbientCubemap", "/Engine/MapTemplates/Sky/DaylightAmbientCubemap"]

log = lambda m: unreal.log("BB0: " + str(m))
warn = lambda m: unreal.log_warning("BB0: " + str(m))
eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary; MEL = unreal.MaterialEditingLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
USED_SET = {}

# ------------------------------------------------------------------------------------------------ kits
# role -> (library folder substrings, optional mesh-name regex for packs, target size m, size axis "h" or "len", fallback)
KITS = {
    "date_palm":     (["sketchfab/palms/date_palm", "sketchfab/palms/realistic_hd_date_palm"], None, 9.5, "h",
                      [NAJMA + "esri_plant_phoenixdactylifera/PhoenixDactylifera/StaticMeshes/PhoenixDactylifera"]),
    "washingtonia":  (["sketchfab/palms/washingtonia"], None, 13.0, "h",
                      [NAJMA + "esri_plant_washingtoniafilifera/WashingtoniaFilifera/StaticMeshes/WashingtoniaFilifera"]),
    "shade_tree":    (["sketchfab/vegetation/acacia_tree", "sketchfab/vegetation/realistic_hd_frangipani", "polyhaven/plants/jacaranda_tree",
                       "polyhaven/plants/tree_small_02"], None, 7.5, "h",
                      [NAJMA + "jacaranda_tree/jacaranda_tree_1k/StaticMeshes/jacaranda_tree_1k", NAJMA + "tree_small_02/tree_small_02_1k/StaticMeshes/tree_small_02_1k"]),
    "hedge":         (["polyhaven/plants/shrub_01", "polyhaven/plants/shrub_04", "polyhaven/plants/shrub_02"], None, 1.3, "h",
                      [NAJMA + "shrub_01/shrub_01_1k/StaticMeshes/shrub_01_1k"]),
    "bougainvillea": (["sketchfab/vegetation/bougainvillea"], None, 2.2, "h", [NAJMA + "shrub_04/shrub_04_1k/StaticMeshes/shrub_04_1k"]),
    "lamp":          (["sketchfab/street/street_lamps"], None, 9.0, "h", []),     # modern_led_solar: parts at wrong offsets (grey cylinders in the sky)
    "bench":         (["sketchfab/street/modern_bench"], None, 1.9, "len", []),
    "shelter":       (["sketchfab/street/modern_bus_stop_shelter"], None, 2.8, "h", []),
    "bin":           (["polyhaven/models/metal_trash_can", "polyhaven/plants/models_site"], r"trash|bin", 1.0, "h", []),     # packs are single combined meshes: never placed whole
    "bollard":       (["sketchfab/street/barrier_traffic_cone"], r"stick", 1.0, "h", []),
    "car":           (["sketchfab/vehicles/toyota_camry", "sketchfab/vehicles/lexus_lc_500", "sketchfab/vehicles/range_rover_evoque",
                       "sketchfab/vehicles/nissan_patrol", "sketchfab/vehicles/toyota_land_cruiser"],
                      None, 4.7, "len", []),
    "boat":          (["sketchfab/vehicles/motor_yacht", "sketchfab/vehicles/yacht", "sketchfab/vehicles/speed_boat"], None, 22.0, "len", []),
    "crane":         (["sketchfab/construction/liebherr_tower_crane", "sketchfab/construction/tower_crane"], None, 70.0, "h", []),
    "fence":         (["sketchfab/street/barrier_traffic_cone"], r"^fence", 2.0, "h", []),
    "barrier":       (["sketchfab/street/barrier_traffic_cone", "polyhaven/plants/models_site"], r"barrier", 1.0, "h", []),
    "cone":          (["sketchfab/street/barrier_traffic_cone"], r"cone", 0.7, "h", []),
    "container":     ([], None, 2.6, "h", []),
    "site_prop":     (["sketchfab/construction/construction_site_asset_pack", "sketchfab/construction/scaffold"], None, 3.0, "h", []),
}
_KIT_CACHE = {}
# construction models (sketchfab_construction, 30 folders): folder keyword -> target height m. Packs and tower cranes excluded.
SITE_SIZES = [("excavator", 3.2), ("mixer", 3.8), ("mobile_crane", 3.9), ("k_51", 3.9), ("dump_truck", 3.2), ("roller", 3.0), ("forklift", 2.3),
              ("portacabin", 2.7), ("toilet", 2.3), ("shipping_container", 2.6), ("concrete_pump", 3.6), ("generator", 1.6), ("skips", 1.6),
              ("sand", 1.8), ("bricks", 1.1), ("cement", 0.7), ("pallet", 0.9), ("formwork", 1.3), ("rebar", 0.6), ("safety_notice", 2.2),
              ("modular_scaffolding", 9.0)]
KITS["site_kit"] = (["sketchfab/construction/"], None, 1.0, "h", [])
_LIB_MESHES = None


def lib_meshes():
    """every StaticMesh under /Game/DA/Library as (lowercase path, path) - read once"""
    global _LIB_MESHES
    if _LIB_MESHES is None:
        _LIB_MESHES = []
        if eal.does_directory_exist(LIB):
            reg = unreal.AssetRegistryHelpers.get_asset_registry()
            flt = unreal.ARFilter(package_paths=[LIB], recursive_paths=True, class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "StaticMesh")])
            for ad in reg.get_assets(flt):
                p = str(ad.package_name)
                _LIB_MESHES.append((p.lower(), p))
        log("library: %d static meshes under %s" % (len(_LIB_MESHES), LIB))
    return _LIB_MESHES


def _bounds(meshes):
    lo = [1e18] * 3; hi = [-1e18] * 3
    for m in meshes:
        b = m.get_bounds(); o, e = b.origin, b.box_extent
        for i, (oc, ec) in enumerate(((o.x, e.x), (o.y, e.y), (o.z, e.z))):
            lo[i] = min(lo[i], oc - ec); hi[i] = max(hi[i], oc + ec)
    return lo, hi


def kit(role):
    """-> list of variants; a variant = {"parts": [StaticMesh], "scale": s, "off": (dx, dy, dz) in mesh units*scale, "yaw90": bool, "folder": str}"""
    if role in _KIT_CACHE:
        return _KIT_CACHE[role]
    folders, pick, size_m, axis, fallback = KITS[role]
    variants = []
    allm = lib_meshes()
    for f in folders:
        key = LIB.lower() + "/" + f.lower()
        hits = [p for lp, p in allm if lp.startswith(key)]
        if not hits:
            continue
        # group by asset folder (/Game/DA/Library/<Source>/<Cat>/<Asset>)
        groups = {}
        for p in hits:
            groups.setdefault("/".join(p.split("/")[:7]), []).append(p)
        for folder, paths in sorted(groups.items()):
            if pick:
                sel = [p for p in paths if re.search(pick, p.split("/")[-1], re.I)]      # packs: named pieces only, never the whole pack
                for p in sel[:3]:                                        # a pack: up to three single-mesh variants
                    variants.append({"parts": [eal.load_asset(p)], "folder": folder})
            elif len(paths) <= 40:
                variants.append({"parts": [eal.load_asset(p) for p in paths], "folder": folder})    # one model in parts
            else:
                ms = [eal.load_asset(p) for p in paths]
                ms.sort(key=lambda m: -m.get_bounds().sphere_radius)
                variants.append({"parts": ms[:1], "folder": folder})
    if not variants:
        for p in fallback:
            m = eal.load_asset(p)
            if isinstance(m, unreal.StaticMesh):
                variants.append({"parts": [m], "folder": p.rsplit("/", 1)[0]})
    if role == "site_kit":                   # keep only the sized single models, each with its own target height
        keep = []
        for v in variants:
            leaf = v["folder"].split("/")[-1].lower()
            hit = next((h for k, h in SITE_SIZES if k in leaf), None)
            if hit and "pack" not in leaf and "tower_crane" not in leaf and len(v["parts"]) <= 40:
                v["_size"] = hit; keep.append(v)
        variants = keep
    out = []
    for v in variants:
        v["parts"] = [m for m in v["parts"] if isinstance(m, unreal.StaticMesh)]
        if not v["parts"]:
            continue
        if len(v["parts"]) > 1:              # drop flat "ground plane" parts shipped inside Sketchfab scenes (mobile crane: a 325 m slab)
            dims = []
            for m in v["parts"]:
                e = m.get_bounds().box_extent; dims.append((max(e.x, e.y), e.z))
            med = sorted(d[0] for d in dims)[len(dims) // 2]
            v["parts"] = [m for m, d in zip(v["parts"], dims) if not (d[0] > 2.5 * med and d[1] < 0.1 * d[0])] or v["parts"]
        lo, hi = _bounds(v["parts"])
        h = hi[2] - lo[2]; lx, ly = hi[0] - lo[0], hi[1] - lo[1]
        ref = h if axis == "h" else max(lx, ly)
        if ref <= 0.1:
            continue
        s = v.get("_size", size_m) * 100.0 / ref
        tgt = v.get("_size", size_m) * 100.0
        if (role == "bougainvillea" and s > 25.0) or s < 1e-5 or max(lx, ly) * s > max(6.0 * tgt, tgt + 3000.0) or h * s > max(6.0 * tgt, tgt + 3000.0):   # x79 bougainvillea carried a sky sphere that shadowed the whole district
            warn("kit %s: %s rejected (%.0f x %.0f m after scaling - broken bounds)" % (role, v["folder"].split("/")[-1], max(lx, ly) * s / 100, h * s / 100))
            continue
        v.update(scale=s, off=(-(lo[0] + hi[0]) / 2.0 * s, -(lo[1] + hi[1]) / 2.0 * s, -lo[2] * s), yaw90=ly > lx, src_h=h)
        out.append(v)
        if role in ("date_palm", "washingtonia", "shade_tree", "hedge", "bougainvillea"):
            flag_instanced(v["parts"])
    log("kit %-13s %d variant(s): %s" % (role, len(out), ", ".join("%s[%d parts, x%.3f]" % (v["folder"].split("/")[-1], len(v["parts"]), v["scale"]) for v in out)[:300]))
    if not out:
        warn("kit %s: nothing in the library or fallbacks - skipped" % role)
    _KIT_CACHE[role] = out
    return out


def flag_instanced(meshes):
    """leaf materials must be flagged for instanced meshes or ISM draws them with the default (black/grey) material"""
    for mesh in meshes:
        try:
            slots = mesh.get_editor_property("static_materials")
        except Exception:
            continue
        for sm in slots:
            base = sm.get_editor_property("material_interface"); g = 0
            while base is not None and isinstance(base, unreal.MaterialInstance) and g < 8:
                base = base.get_editor_property("parent"); g += 1
            if isinstance(base, unreal.Material) and (not base.get_editor_property("used_with_instanced_static_meshes") or not base.get_editor_property("two_sided")):
                try:
                    base.set_editor_property("used_with_instanced_static_meshes", True)
                    base.set_editor_property("two_sided", True)                     # leaves lit from behind too (palms read dark)
                    MEL.recompile_material(base); eal.save_loaded_asset(base)
                except Exception as e:
                    warn("flag %s: %s" % (base.get_name(), e))


def place_xf(v, x, y, z, yaw_deg, js=1.0):
    """world transform for one part of a kit variant at (x, y, z), yaw about the kit's own centre"""
    yaw = yaw_deg + (90.0 if v.get("yaw90") and v.get("_len_axis") else 0.0)
    s = v["scale"] * js
    r = math.radians(yaw)
    dx, dy = v["off"][0] * js, v["off"][1] * js
    wx = x + dx * math.cos(r) - dy * math.sin(r); wy = y + dx * math.sin(r) + dy * math.cos(r)
    return unreal.Transform(unreal.Vector(wx, wy, z + v["off"][2] * js), unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw), unreal.Vector(s, s, s))


_FT = {}


def foliage_type(mesh, shadow=True):
    name = re.sub(r"[^A-Za-z0-9_]", "_", mesh.get_path_name().split(".")[-1])[:60]
    if name in _FT:
        return _FT[name]
    p = "%s/FT_%s" % (FT_DIR, name)
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    ft = None
    for fn in ("FoliageType_InstancedStaticMeshFactory", "FoliageTypeFactory"):
        f = getattr(unreal, fn, None)
        if f is None:
            continue
        try:
            ft = tools.create_asset("FT_" + name, FT_DIR, unreal.FoliageType_InstancedStaticMesh, f())
            if ft:
                break
        except Exception as e:
            warn("foliage type via %s: %s" % (fn, e))
    if ft is None:
        return None
    ft.set_editor_property("mesh", mesh)
    for k, val in (("cast_shadow", shadow), ("cast_dynamic_shadow", shadow), ("cast_static_shadow", False)):
        try:
            ft.set_editor_property(k, val)
        except Exception:
            pass
    eal.save_asset(p)
    _FT[name] = ft
    return ft


def scatter(role, rows, gz, len_axis=False, shadow=True, jitter_idx=None):
    """rows: [x, y, yaw, scale, (variant)] -> instanced placement of every part of every variant"""
    vs = kit(role)
    if not vs or not rows:
        return 0
    if SCALE < 1.0:
        rows = rows[::max(1, int(round(1.0 / SCALE)))]
    world = ell.get_editor_world()
    by = {}
    for r in rows:
        vi = (int(r[4]) if len(r) > 4 else hash((r[0], r[1]))) % len(vs)
        by.setdefault(vi, []).append(r)
    n = 0
    for vi, rs in by.items():
        v = vs[vi]; v["_len_axis"] = len_axis
        USED_SET[v["folder"]] = USED_SET.get(v["folder"], 0) + len(rs)
        for part in v["parts"]:
            ft = foliage_type(part, shadow)
            if ft is None:
                continue
            tf = [place_xf(v, r[0], r[1], gz, r[2], r[3] if len(r) > 3 else 1.0) for r in rs]
            for k in range(0, len(tf), 5000):
                unreal.InstancedFoliageActor.add_instances(world, ft, tf[k:k + 5000])
        n += len(rs)
    log("  %-20s %5d placed (%d variant(s))" % (role, n, len(by)))
    return n


# ------------------------------------------------------------------------------------------------ level plumbing
def les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def ensure_dirs():
    for d in (ROOT, ROOT + "/Datasmith", PBR_DIR, GROUND_DIR, CTX_DIR, FT_DIR, POST_DIR, ROOT + "/Cinematics"):
        if not eal.does_directory_exist(d):
            eal.make_directory(d)


def open_levels():
    if eal.does_asset_exist(LEVEL):
        les().load_level(LEVEL)
        log("reopened " + LEVEL)
    else:
        if not les().new_level(LEVEL):
            raise RuntimeError("could not create " + LEVEL)
        log("created " + LEVEL)
    world = ell.get_editor_world()
    stream = None
    try:
        stream = unreal.GameplayStatics.get_streaming_level(world, "L_BB_v0_Buildings")
    except Exception as e:
        warn("get_streaming_level: %s" % e)
    if stream is None and eal.does_asset_exist(BLD_LEVEL):
        # 28 Sep: add_level_to_world on a sublevel the world already holds asserts (SharedPointer IsValid) - only add
        # when no loaded level is the buildings level
        names = set()
        for lv in (unreal.EditorLevelUtils.get_levels(world) or []):
            try:
                names.add(lv.get_outermost().get_name())
            except Exception:
                pass
        log("loaded levels: %s" % sorted(names))
        if any(n.endswith("L_BB_v0_Buildings") for n in names):
            stream = True
    if stream is None:
        if eal.does_asset_exist(BLD_LEVEL):
            stream = unreal.EditorLevelUtils.add_level_to_world(world, BLD_LEVEL, unreal.LevelStreamingAlwaysLoaded)
        else:
            stream = unreal.EditorLevelUtils.create_new_streaming_level(unreal.LevelStreamingAlwaysLoaded, BLD_LEVEL, False)
        log("buildings sublevel %s attached" % BLD_LEVEL)
    # persistent-level dressing from a previous run goes (BB0_* actors, the foliage actor); the Datasmith sublevel is
    # kept unless BB_V0_REIMPORT=1 (import_datasmith handles that)
    n = 0
    for a in list(ell.get_all_level_actors()):
        if (a.get_actor_label() or "").startswith(PFX) or isinstance(a, unreal.InstancedFoliageActor):
            ell.destroy_actor(a); n += 1
    log("cleared %d actors from the previous run" % n)
    return stream


def current_level_name():
    try:
        return les().get_current_level().get_outer().get_name()
    except Exception:
        return "?"


def make_current(stream_or_none):
    """the buildings sublevel (stream) or the persistent level (None) becomes the level new actors land in"""
    names = ["L_BB_v0_Buildings"] if stream_or_none is not None else ["L_BB_v0", "PersistentLevel"]
    for nm in names:
        try:
            if les().set_current_level_by_name(nm):
                break
        except Exception as e:
            warn("set_current_level_by_name %s: %s" % (nm, e))
    else:
        try:
            unreal.EditorLevelUtils.make_level_current(stream_or_none)
        except Exception as e:
            warn("make_level_current: %s" % e)
    log("current level: %s" % current_level_name())


def descendants(root):
    kids, todo = [], [root]
    allacts = ell.get_all_level_actors()
    by_parent = {}
    for a in allacts:
        p = a.get_attach_parent_actor()
        if p:
            by_parent.setdefault(p.get_name(), []).append(a)
    while todo:
        cur = todo.pop()
        for c in by_parent.get(cur.get_name(), []):
            kids.append(c); todo.append(c)
    return kids


def scene_actor(tag):
    for a in ell.get_all_level_actors():
        if isinstance(a, unreal.DatasmithSceneActor) and tag in (a.get_actor_label() or "").lower():
            return a
    return None


def import_datasmith(path, dest, tag):
    """ONLY via the .udatasmith (never glob its _Assets folder)"""
    old = scene_actor(tag)
    if old and os.environ.get("BB_V0_REIMPORT") != "1":
        log("%s: already in the buildings sublevel (%d actors)" % (tag, len(descendants(old))))
        return old
    if old:
        for a in descendants(old):
            ell.destroy_actor(a)
        ell.destroy_actor(old)
        if eal.does_directory_exist(dest):
            eal.delete_directory(dest)
    scene = unreal.DatasmithSceneElement.construct_datasmith_scene_from_file(path)
    if scene is None:
        raise RuntimeError("Datasmith could not open " + path)
    opts = scene.get_options()
    try:
        opts.base_options.include_light = False; opts.base_options.include_camera = False; opts.base_options.include_animation = False
        opts.base_options.static_mesh_options.generate_lightmap_u_vs = False
    except Exception as e:
        log("(import options left default: %s)" % e)
    res = scene.import_scene(dest)
    scene.destroy_scene()
    ok = bool(res and res.import_succeed)
    eal.save_directory(dest, only_if_is_dirty=False, recursive=True)      # Bible: unsaved Datasmith assets = mesh-less actors
    sa = scene_actor(tag)
    log("%s: import %s, %d actors -> %s" % (tag, "OK" if ok else "FAILED", len(res.imported_actors) if ok else 0, dest))
    return sa


def check_offset(sa, plan):
    """compare the imported district bounds with the footprints' bounds; shift the scene actor if it is off by > 200 m"""
    kids = [a for a in descendants(sa) if isinstance(a, unreal.StaticMeshActor)]
    if not kids:
        warn("no building actors under the Datasmith scene"); return 0.0
    xs, ys, zs = [], [], []
    for a in kids:
        o, e = a.get_actor_bounds(False)
        xs += [o.x - e.x, o.x + e.x]; ys += [o.y - e.y, o.y + e.y]; zs.append(o.z - e.z)
    got = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    bx = plan["district"]["bbox_cm"]; want = ((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
    dx, dy = want[0] - got[0], want[1] - got[1]
    zs.sort(); gz = zs[len(zs) // 2]
    log("buildings: %d actors, centre (%.0f, %.0f) m vs footprints (%.0f, %.0f) m, median base z %.1f m" %
        (len(kids), got[0] / 100, got[1] / 100, want[0] / 100, want[1] / 100, gz / 100))
    if math.hypot(dx, dy) > 20000.0:
        l = sa.get_actor_location()
        sa.set_actor_location(unreal.Vector(l.x + dx, l.y + dy, l.z), False, False)
        warn("buildings off by %.0f m - scene actor shifted by (%.0f, %.0f) m" % (math.hypot(dx, dy) / 100, dx / 100, dy / 100))
    return gz if abs(gz) > 50.0 else 0.0


def nanite_on(sa):
    sub = None
    try:
        sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    except Exception:
        pass
    seen, n = set(), 0
    for a in descendants(sa):
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        m = a.static_mesh_component.static_mesh
        if m is None or m.get_path_name() in seen:
            continue
        seen.add(m.get_path_name())
        try:
            ns = m.get_editor_property("nanite_settings")
            if ns.get_editor_property("enabled"):
                continue
            ns.set_editor_property("enabled", True)
            if sub and hasattr(sub, "set_nanite_settings"):
                sub.set_nanite_settings(m, ns, apply_changes=True)
            else:
                m.set_editor_property("nanite_settings", ns)
            n += 1
        except Exception as e:
            warn("nanite %s: %s" % (m.get_name(), e)); break
    log("nanite: enabled on %d of %d meshes" % (n, len(seen)))


# ------------------------------------------------------------------------------------------------ materials
def pbr_parent():
    p = PBR_DIR + "/M_BB0_PBR"
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    mat = tools.create_asset("M_BB0_PBR", PBR_DIR, unreal.Material, unreal.MaterialFactoryNew())
    col = MEL.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -500, -200)
    col.set_editor_property("parameter_name", "Color"); col.set_editor_property("default_value", unreal.LinearColor(0.8, 0.8, 0.8, 1))
    MEL.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for i, (name, prop, dv) in enumerate((("Roughness", unreal.MaterialProperty.MP_ROUGHNESS, 0.6), ("Metallic", unreal.MaterialProperty.MP_METALLIC, 0.0),
                                          ("Specular", unreal.MaterialProperty.MP_SPECULAR, 0.5))):
        s = MEL.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -500, 50 + 120 * i)
        s.set_editor_property("parameter_name", name); s.set_editor_property("default_value", dv)
        MEL.connect_material_property(s, "", prop)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


_MI = {}


def mi(parent, key, colour, rough_bias=0.0, dim=1.0):
    name = "MI_BB0_%s" % key
    if name in _MI:
        return _MI[name]
    p = "%s/%s" % (PBR_DIR, name)
    rgb, rough, metal, spec = SP.PALETTE.get(colour, SP.PALETTE["white"])
    if eal.does_asset_exist(p):
        m = eal.load_asset(p)
    else:
        m = tools.create_asset(name, PBR_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(m, parent)
    MEL.set_material_instance_vector_parameter_value(m, "Color", unreal.LinearColor(rgb[0] * dim, rgb[1] * dim, rgb[2] * dim, 1.0))
    MEL.set_material_instance_scalar_parameter_value(m, "Roughness", min(1.0, rough + rough_bias))
    MEL.set_material_instance_scalar_parameter_value(m, "Metallic", metal)
    MEL.set_material_instance_scalar_parameter_value(m, "Specular", spec)
    MEL.update_material_instance(m); eal.save_asset(p)
    _MI[name] = m
    return m


GLASS_OF = [("glassblue", "blue_glass"), ("glassclear", "clear_glass"), ("glassbronze", "bronze_glass"), ("glassdark", "dark_glass"),
            ("glassgreen", "tinted_glass"), ("glassgold", "champagne_glass"), ("glass", "tinted_glass")]
WALL_OF = [("render", "cream_render"), ("stone", "sandstone"), ("sand", "sandstone"), ("concrete", "pale_concrete"), ("white", "white"),
           ("metal", "rose_bronze"), ("dark", "dark")]
GLASS_CYCLE = ["blue_glass", "clear_glass", "tinted_glass", "deep_blue_glass", "bronze_glass", "akoya_glass"]
WALL_CYCLE = ["white", "pale_concrete", "ivory_stone", "cream_render", "sandstone"]


def looks():
    try:
        fm = json.load(open(REPO + "/data/ce/businessbay/facade_match.json", encoding="utf-8"))
        return {int(i): r.get("unreal", {}) for i, r in fm.items()}
    except Exception:
        return {}


def apply_pbr(sa):
    parent = pbr_parent(); lk = looks(); rx = re.compile(r"^b(\d+)_")
    done = 0
    for a in descendants(sa):
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        lab = a.get_actor_label() or ""
        m = rx.match(lab); bi = int(m.group(1)) if m else abs(hash(lab)) % 997
        pal = lk.get(bi, {})
        comp = a.static_mesh_component
        for si in range(comp.get_num_materials()):
            cur = comp.get_material(si); nm = (cur.get_name() if cur else "").lower()
            role = next((r for x, r in SP.ROLE_OF if x.search(nm)), None)
            glass = pal.get("vision") or next((c for k, c in GLASS_OF if k in nm), GLASS_CYCLE[bi % len(GLASS_CYCLE)])
            wall = pal.get("walls") or next((c for k, c in WALL_OF if k in nm), WALL_CYCLE[(bi // 3) % len(WALL_CYCLE)])
            if role is None:
                role = "vision" if "glass" in nm else "walls"
            if role == "vision":
                mat = mi(parent, "%s_vision" % glass, glass)
            elif role == "spandrel":
                mat = mi(parent, "%s_spandrel" % glass, glass, rough_bias=0.10, dim=0.75)
            elif role == "walls":
                mat = mi(parent, "%s_curtain" % glass, glass, rough_bias=0.04) if "glass" in nm else mi(parent, "%s_walls" % wall, wall)
            elif role == "slabs":
                sl = pal.get("slabs") or wall
                mat = mi(parent, "%s_slabs" % sl, sl)
            elif role == "fins":
                fn = pal.get("fins") or ("white" if bi % 2 else "rose_bronze")
                mat = mi(parent, "%s_fins" % fn, fn)
            else:
                mat = mi(parent, "roof", "roof")
            comp.set_material(si, mat)
        done += 1
    log("pbr: %d building actors re-materialed, %d material instances" % (done, len(_MI)))


def flat_or_noise(name, dark, light, scale, rough, spec, lib_cat=None, tiling=0.25):
    """ambientCG material from the library when present (world-aligned UVs), else two-tone noise like ue_sobha_context"""
    p = "%s/%s" % (CTX_DIR, name)
    if lib_cat:
        base = "%s/AmbientCG/%s" % (LIB, lib_cat)
        mis = [x for x in (eal.list_assets(base, recursive=True, include_folder=False) if eal.does_directory_exist(base) else []) if "/MI_" in x]
        if mis:
            parent = eal.load_asset(sorted(mis)[0].split(".")[0])
            if eal.does_asset_exist(p):
                eal.delete_asset(p)
            m = tools.create_asset(name, CTX_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
            MEL.set_material_instance_parent(m, parent)
            try:
                MEL.set_material_instance_static_switch_parameter_value(m, "UseWorldAlignedUV", True)
            except Exception as e:
                warn("static switch: %s" % e)
            MEL.set_material_instance_scalar_parameter_value(m, "Tiling", tiling)
            MEL.update_material_instance(m); eal.save_asset(p)
            USED_SET[sorted(mis)[0].rsplit("/", 1)[0]] = 1
            log("  %s <- %s" % (name, sorted(mis)[0].split(".")[0]))
            return m
    if eal.does_asset_exist(p):
        eal.delete_asset(p)
    mat = tools.create_asset(name, CTX_DIR, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("two_sided", True)
    nz = MEL.create_material_expression(mat, unreal.MaterialExpressionNoise, -900, -100)
    nz.set_editor_property("scale", scale); nz.set_editor_property("levels", 3)
    nz.set_editor_property("output_min", 0.0); nz.set_editor_property("output_max", 1.0)
    a = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -600, -250); a.constant = unreal.LinearColor(*dark, 1.0)
    b = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -600, -50); b.constant = unreal.LinearColor(*light, 1.0)
    lerp = MEL.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -400, -100)
    MEL.connect_material_expressions(a, "", lerp, "A"); MEL.connect_material_expressions(b, "", lerp, "B"); MEL.connect_material_expressions(nz, "", lerp, "Alpha")
    MEL.connect_material_property(lerp, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for v, prop, y in ((rough, unreal.MaterialProperty.MP_ROUGHNESS, 100), (spec, unreal.MaterialProperty.MP_SPECULAR, 200)):
        c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, y); c.r = v
        MEL.connect_material_property(c, "", prop)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def water_material():
    p = GROUND_DIR + "/M_BB0_Water"
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    mat = tools.create_asset("M_BB0_Water", GROUND_DIR, unreal.Material, unreal.MaterialFactoryNew())
    for v, prop, y in (((0.02, 0.16, 0.22), unreal.MaterialProperty.MP_BASE_COLOR, -100), (0.04, unreal.MaterialProperty.MP_ROUGHNESS, 100),
                       (1.0, unreal.MaterialProperty.MP_SPECULAR, 200), (0.0, unreal.MaterialProperty.MP_METALLIC, 300)):
        if isinstance(v, tuple):
            c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, y); c.constant = unreal.LinearColor(*v, 1.0)
        else:
            c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, y); c.r = v
        MEL.connect_material_property(c, "", prop)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def import_obj(src, dest_dir, name):
    p = "%s/%s" % (dest_dir, name)
    if eal.does_asset_exist(p) and os.environ.get("BB_V0_REIMPORT_CTX") != "1":
        return eal.load_asset(p)
    if not os.path.exists(src):
        warn("no mesh at %s" % src); return None
    t = unreal.AssetImportTask()
    t.filename = src; t.destination_path = dest_dir; t.destination_name = name
    t.automated = True; t.save = True; t.replace_existing = True
    o = unreal.FbxImportUI()
    o.import_mesh = True; o.import_materials = False; o.import_textures = False; o.import_as_skeletal = False
    try:
        o.static_mesh_import_data.set_editor_property("combine_meshes", True)
        o.static_mesh_import_data.set_editor_property("generate_lightmap_u_vs", False)
        o.static_mesh_import_data.set_editor_property("import_uniform_scale", 1.0)
    except Exception:
        pass
    t.options = o
    tools.import_asset_tasks([t])
    m = eal.load_asset(p)
    log("  %s: %s" % (name, "imported" if m else "IMPORT FAILED"))
    return m


def place_mesh(label, mesh, mat, z, expect_centre=None, shadow=False):
    a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, z))
    a.set_actor_label(PFX + label)
    c = a.static_mesh_component
    c.set_static_mesh(mesh)
    for si in range(max(1, c.get_num_materials())):
        c.set_material(si, mat)
    c.set_cast_shadow(shadow)
    a.set_actor_scale3d(unreal.Vector(1, -1, 1))               # ue_sobha_water_fix lesson: the OBJ importer negates Y
    if expect_centre:
        o, e = a.get_actor_bounds(False)
        if abs(o.y - expect_centre[1]) > abs(-o.y - expect_centre[1]):
            a.set_actor_scale3d(unreal.Vector(1, 1, 1))
            o, e = a.get_actor_bounds(False)
        log("  %s centre (%.0f, %.0f) m, expected (%.0f, %.0f) m" % (label, o.x / 100, o.y / 100, expect_centre[0] / 100, expect_centre[1] / 100))
    return a


# ------------------------------------------------------------------------------------------------ scene
def spawn(cls, label, loc=(0, 0, 0), rot=None):
    a = ell.spawn_actor_from_class(cls, unreal.Vector(*loc), rot or unreal.Rotator(0, 0, 0))
    a.set_actor_label(PFX + label)
    return a


def environment(plan, gz):
    C = plan["district"]["centre_cm"]
    # golden hour: sun ~17 deg up in the WSW, light travelling ENE (UE +X east, +Y south)
    # preview 1 review: street level too dark at 17 deg -> 33 deg up, golden-warm but lighter
    sun = spawn(unreal.DirectionalLight, "SUN", (C[0], C[1], 50000), unreal.Rotator(roll=0.0, pitch=-SUN_ELEV, yaw=-22.0))
    lc = sun.light_component
    lc.set_intensity(8.0); lc.set_light_color(unreal.LinearColor(1.0, 0.91, 0.80, 1.0))   # preview 5: too orange with LUT + golden HDRI
    for k, v in (("atmosphere_sun_light", True), ("atmosphere_sun_disk_color_scale", unreal.LinearColor(0, 0, 0, 1)), ("dynamic_shadow_distance_movable_light", 60000.0)):
        try:
            lc.set_editor_property(k, v)
        except Exception as e:
            log("  sun %s: %s" % (k, e))
    spawn(unreal.SkyAtmosphere, "ATMO", (C[0], C[1], 0))
    sky = spawn(unreal.SkyLight, "SKY", (C[0], C[1], 20000))
    slc = sky.light_component
    try:
        slc.set_editor_property("real_time_capture", False)          # Bible sec.11
        cands = [LIB + "/HDRI/Dubai/HDR_golden_bay_4k", LIB + "/HDRI/Dubai/HDR_shanghai_riverside_4k"] + [x.split(".")[0] for x in (eal.list_assets(LIB + "/HDRI/Dubai", recursive=True, include_folder=False) if eal.does_directory_exist(LIB + "/HDRI/Dubai") else [])] + SKY_CUBES
        cube = next((c for c in (eal.load_asset(p) for p in cands if eal.does_asset_exist(p)) if isinstance(c, unreal.TextureCube)), None)
        log("  sky cubemap candidates %d, chosen %s" % (len(cands), cube.get_path_name() if cube else None))
        if cube:                                                      # a captured scene sky came out black in the commandlet: canyons went black
            slc.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
            slc.set_editor_property("cubemap", cube)
            log("  sky light cubemap: %s" % cube.get_path_name())
        slc.set_editor_property("lower_hemisphere_is_black", False)
        slc.set_intensity(SKY_INT)
        slc.recapture_sky()
    except Exception as e:
        log("  sky: %s" % e)
    fog = spawn(unreal.ExponentialHeightFog, "FOG", (C[0], C[1], 0))
    try:
        fc = fog.component
        for k, v in (("fog_density", 0.012), ("fog_height_falloff", 0.25), ("start_distance", 90000.0), ("fog_max_opacity", 0.6),
                     ("fog_inscattering_luminance", unreal.LinearColor(*FOG_RGB, 1.0)), ("enable_volumetric_fog", False),
                     ("directional_inscattering_luminance", unreal.LinearColor(1.0, 0.85, 0.65, 1.0))):
            fc.set_editor_property(k, v)
    except Exception as e:
        log("  fog: %s" % e)
    # sand: 30 km plane under everything (ue_sobha_ground recipe, own asset)
    sand = flat_or_noise("M_BB0_Sand", (0.42, 0.33, 0.22), (0.86, 0.76, 0.55), 0.00005, 0.95, 0.3)
    g = spawn(unreal.StaticMeshActor, "GROUND_Sand", (C[0], C[1], gz - 20.0))
    g.static_mesh_component.set_static_mesh(eal.load_asset("/Engine/BasicShapes/Plane"))
    g.set_actor_scale3d(unreal.Vector(30000, 30000, 1)); g.static_mesh_component.set_material(0, sand)
    g.static_mesh_component.set_cast_shadow(False)


def ground(plan, gz):
    water = water_material()
    meta = json.load(open(WATER_OBJ + "/ground_meshes.json", encoding="utf-8"))
    bb = meta["bbox_utm"]
    exp = ((bb[0] + bb[2]) / 2 - 328289.0) * 100.0, (2784598.0 - (bb[1] + bb[3]) / 2) * 100.0
    for name, label in (("sea", "WATER_Sea"), ("inland_water", "WATER_Inland")):
        m = import_obj(WATER_OBJ + "/%s.obj" % name, GROUND_DIR, "SM_BB0_" + name)
        if m:
            place_mesh(label, m, water, gz + 10.0, exp)
    looks = {  # layer -> (dark, light, noise scale, rough, spec, ambientCG category, tiling)
        "asphalt": ((0.13, 0.13, 0.14), (0.21, 0.21, 0.22), 0.0007, 0.8, 0.35, None, 0.2),     # mid-grey road (ambientCG asphalt read black)
        "pavement": ((0.50, 0.48, 0.44), (0.66, 0.63, 0.58), 0.0012, 0.9, 0.25, "paving", 0.5),
        "parking": ((0.16, 0.16, 0.17), (0.24, 0.24, 0.25), 0.0009, 0.85, 0.3, None, 0.2),
        "grass": ((0.10, 0.26, 0.06), (0.22, 0.38, 0.09), 0.0009, 0.9, 0.2, None, 1.0),
        "pitch": ((0.10, 0.30, 0.08), (0.14, 0.36, 0.10), 0.001, 0.85, 0.2, None, 1.0),
        "pool": ((0.05, 0.35, 0.45), (0.08, 0.45, 0.55), 0.001, 0.05, 1.0, None, 1.0),
        "construction": ((0.40, 0.32, 0.22), (0.55, 0.45, 0.33), 0.001, 0.95, 0.2, "Concrete", 0.3),
    }
    for layer, info in sorted(plan.get("context", {}).items()):
        m = import_obj(V0 + "/ctx_%s.obj" % layer, CTX_DIR, "SM_BB0_ctx_%s" % layer)
        if not m:
            continue
        base = layer[2:] if layer.startswith("s_") else layer
        b = info.get("bounds_cm")
        if info.get("role") == "massing":            # surrounding districts: solid pale-grey massing, casts shadows
            mat = flat_or_noise("M_BB0_massing", (0.40, 0.39, 0.37), (0.50, 0.49, 0.46), 0.0005, 0.8, 0.3)
            place_mesh("CTX_" + layer, m, mat, gz, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None, shadow=True)
            continue
        lk = looks.get(base, ((0.3, 0.3, 0.3), (0.4, 0.4, 0.4), 0.001, 0.9, 0.3, None, 1.0))
        mat = flat_or_noise("M_BB0_ctx_%s" % base, lk[0], lk[1], lk[2], lk[3], lk[4], lk[5], lk[6]) if base not in _CTXM else _CTXM[base]
        _CTXM[base] = mat
        place_mesh("CTX_" + layer, m, mat, gz - (3.0 if layer.startswith("s_") else 0.0), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else None)


_CTXM = {}


def dress(plan, gz):
    D = plan["dress"]
    rp = D["road_palms"]
    scatter("date_palm", [r[:4] + [r[4]] for r in rp if r[4] != 2], gz)
    scatter("washingtonia", [r[:4] for r in rp if r[4] == 2], gz)
    scatter("date_palm", D["g_palms"], gz)
    scatter("shade_tree", D["g_trees"], gz)
    scatter("hedge", D["verge_hedge"], gz, shadow=False)
    scatter("bougainvillea", D["verge_bougainvillea"], gz, shadow=False)
    scatter("lamp", D["lamps"], gz)
    scatter("bench", D["benches"], gz, len_axis=True)
    scatter("bin", D["bins"], gz, shadow=False)
    scatter("shelter", D["bus_shelters"], gz, len_axis=True)
    scatter("bollard", D["bollards"], gz, shadow=False)
    scatter("car", D["parked_cars"], gz, len_axis=True)
    scatter("boat", D["boats"], gz + 20.0, len_axis=True)
    sites(plan, gz)


def sites(plan, gz):
    """cranes, a fence ring, barriers, containers and site props on the camera's site + the 7 largest others"""
    all_s = plan.get("sites") or []
    hero = plan.get("site")
    ss = sorted(all_s, key=lambda q: -q.get("area_m2", 0))          # every OSM construction area + register construction
    if hero and not any(abs(q["cx"] - hero["cx"]) < 1 and abs(q["cy"] - hero["cy"]) < 1 for q in ss):
        ss = [hero] + ss
    rnd = random.Random(5)
    cranes, fences, barriers, cones, conts, props, kitrows = [], [], [], [], [], [], []
    for q in ss:
        x0, y0, x1, y1 = q["x0"], q["y0"], q["x1"], q["y1"]
        w, h = x1 - x0, y1 - y0
        cranes.append([x0 + 0.3 * w, y0 + 0.35 * h, rnd.uniform(0, 360), rnd.uniform(0.9, 1.25), 0])
        if w * h > 6000.0 * 6000.0:
            cranes.append([x0 + 0.72 * w, y0 + 0.7 * h, rnd.uniform(0, 360), rnd.uniform(0.8, 1.1), 1])
        step = 350.0                                                  # fence panels ~3.5 m
        for (ax, ay, bx_, by_) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
            L = math.hypot(bx_ - ax, by_ - ay); n = max(1, int(L / step)); yw = math.degrees(math.atan2(by_ - ay, bx_ - ax))
            for k in range(n):
                u = (k + 0.5) / n
                fences.append([ax + (bx_ - ax) * u, ay + (by_ - ay) * u, yw, 1.0, 0])
        for k in range(6):
            barriers.append([x0 + w * (0.1 + 0.15 * k), y0 - 250.0, 0.0, 1.0, k])
            cones.append([x0 + w * (0.12 + 0.15 * k), y0 - 450.0, 0.0, 1.0, k])
        for k in range(3):
            conts.append([x0 + w * 0.12, y0 + h * (0.15 + 0.12 * k), 90.0, 1.0, k])
        for k in range(1):
            props.append([x0 + w * rnd.uniform(0.2, 0.8), y0 + h * rnd.uniform(0.2, 0.8), rnd.uniform(0, 360), 1.0, k])
        nk = max(6, min(18, int(w * h / (1500.0 * 1500.0))))          # ~one machine / pile per 225 m2, 6-18 per site
        for k in range(nk):
            kitrows.append([x0 + w * rnd.uniform(0.1, 0.9), y0 + h * rnd.uniform(0.1, 0.9), rnd.choice((0, 90, 180, 270)) + rnd.uniform(-8, 8), 1.0, rnd.randrange(64)])
    scatter("crane", cranes, gz)
    scatter("fence", fences, gz, len_axis=True, shadow=False)
    scatter("barrier", barriers, gz, len_axis=True, shadow=False)
    scatter("cone", cones, gz, shadow=False)
    scatter("container", conts, gz, len_axis=True)
    scatter("site_prop", props, gz)
    scatter("site_kit", kitrows, gz, len_axis=True)
    log("  construction sites dressed: %d" % len(ss))


def lut():
    """GoldenHour_Warm LUT for the camera's post process (the tour script applies it); optional"""
    p = POST_DIR + "/T_BB0_LUT_GoldenHour"
    if eal.does_asset_exist(p):
        return
    src = "C:/Dev/assets/finish/luts/DA_GoldenHour_Warm_UE256x16.png"
    if not os.path.exists(src):
        return
    t = unreal.AssetImportTask()
    t.filename = src; t.destination_path = POST_DIR; t.destination_name = "T_BB0_LUT_GoldenHour"; t.automated = True; t.save = True; t.replace_existing = True
    tools.import_asset_tasks([t])
    tex = eal.load_asset(p)
    if tex:
        for k, v in (("lod_group", unreal.TextureGroup.TEXTUREGROUP_COLOR_LOOKUP_TABLE), ("srgb", False), ("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS),
                     ("compression_settings", unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)):
            try:
                tex.set_editor_property(k, v)
            except Exception as e:
                warn("lut %s: %s" % (k, e))
        eal.save_asset(p)
        USED_SET["LUT:DA_GoldenHour_Warm (DigitAlchemy, own)"] = 1


def look_only(plan):
    """BB_V0_LOOK_ONLY=1: rebuild just sun / sky / fog / sand in the existing level (fast lighting iterations)"""
    les().load_level(LEVEL)
    for a in list(ell.get_all_level_actors()):
        if (a.get_actor_label() or "") in (PFX + "SUN", PFX + "ATMO", PFX + "SKY", PFX + "FOG", PFX + "GROUND_Sand"):
            ell.destroy_actor(a)
    sand = next((a for a in ell.get_all_level_actors() if (a.get_actor_label() or "").startswith(PFX + "CTX_asphalt")), None)
    environment(plan, sand.get_actor_location().z if sand else 0.0)
    les().save_all_dirty_levels()
    log("look-only: sun %.0f deg, sky light %.1f" % (SUN_ELEV, SKY_INT))


def main():
    plan = json.load(open(PLAN, encoding="utf-8"))
    if os.environ.get("BB_V0_LOOK_ONLY") == "1":
        return look_only(plan)
    ensure_dirs()
    stream = open_levels()
    # 1. towers into their own sublevel
    make_current(stream)
    sa = import_datasmith(DATASMITH, DS_BB, "businessbay_lod3")
    burj = None
    if os.environ.get("BB_V0_BURJ", "1") == "1" and os.path.exists(DATASMITH_BURJ):
        burj = import_datasmith(DATASMITH_BURJ, DS_BURJ, "burjkhalifa_lod3")
    gz = 0.0
    if sa:
        gz = check_offset(sa, plan)
        nanite_on(sa); apply_pbr(sa)
    if burj:
        nanite_on(burj); apply_pbr(burj)
    eal.save_directory(ROOT + "/Datasmith", only_if_is_dirty=True, recursive=True)
    eal.save_directory(PBR_DIR, only_if_is_dirty=False, recursive=True)
    make_current(None)
    # 2. everything else in the persistent level
    environment(plan, gz)
    ground(plan, gz)
    dress(plan, gz)
    lut()
    eal.save_directory(ROOT, only_if_is_dirty=True, recursive=True)
    les().save_all_dirty_levels()
    json.dump({"placed": USED_SET}, open(USED, "w", encoding="utf-8"), indent=1)
    log("done: %s saved (+ %s); used assets -> %s" % (LEVEL, BLD_LEVEL, USED))


if __name__ == "__main__":
    main()










