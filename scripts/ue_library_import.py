"""Unreal (commandlet): Business Bay Phase 0 - import the C:/Dev/assets library into /Game/DA/Library (28 Sep 2026).

README
------
Roadmap: DigitAlchemy_31MAY2026/Visualization_Engine/Developer_Flythroughs_Unreal/BusinessBay/ROADMAP_28SEP2026.md (phase 0)
Rules:   ../ASSET_PLAYBOOK.md (leaf material, never touch other developers' folders), ../VISUAL_STYLE.md
Project: C:/Dev/UnrealProjects/AzimuthDubai (UE 5.8). Writes ONLY under /Game/DA/Library.

Layout:  /Game/DA/Library/<Source>/<Category>/<Asset>/...   Source = PolyHaven | AmbientCG | Sketchfab
         /Game/DA/Library/HDRI/<PolyHaven|Dubai>/<name>      (TextureCube from .hdr long-lat)
         /Game/DA/Library/Masters/M_DA_PBR, M_DA_Leaf         (shared masters, created here with MaterialEditingLibrary)
  - meshes: fbx (AssetImportTask + FbxImportUI) or glTF/glb (AssetImportTask -> Interchange), then Nanite ON for
    every StaticMesh (skeletal meshes are skipped / left alone).
  - texture sets (ambientCG, Poly Haven textures/): textures imported, one MaterialInstance MI_<asset> of M_DA_PBR
    (BaseColor, Normal, Roughness, AO; static switch UseWorldAlignedUV; scalar Tiling).
  - foliage post-pass: meshes from Plants / palms / vegetation (or tree|palm|plant|shrub|grass|bush folders):
    base material under /Game is set to Two Sided Foliage + masked (opacity mask = base-colour alpha) + used with
    instanced static meshes; materials whose parent lives outside /Game (e.g. Interchange glTF instances) get a
    new MI of M_DA_Leaf with their colour/normal textures copied over.
  - idempotent: an asset whose folder already holds assets is skipped. Failures are logged and the run continues.
  - manifest: C:/Dev/naj-market-pulse/data/board/asset_library_manifest.json (merged by asset path on every run).
  - nested Sketchfab zips are extracted to Saved/LibraryUnzip (C:/Dev/assets is never modified).

Args (after the script path inside -script="..."), or env vars DA_LIB_ONLY / DA_LIB_LIMIT / DA_LIB_SOURCE / DA_LIB_NAMES (comma list):
  --only <category>   e.g. HDRI, Plants, Models, Textures, Tiles, Concrete, street, palms ... (case-insensitive)
  --source <source>   PolyHaven | AmbientCG | Sketchfab | HDRI
  --limit <n>         import at most n NEW assets (trials)
Usage (Unreal must not be running; see logs/bb_phase0_run.ps1):
  UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script="C:/Dev/naj-market-pulse/scripts/ue_library_import.py --only Plants --limit 3"
Log lines are prefixed "DA lib:".
"""
import datetime
import json
import os
import re
import sys
import zipfile

import unreal

ASSETS = "C:/Dev/assets"
LIB = "/Game/DA/Library"
MASTERS = LIB + "/Masters"
HDRI_DIR = LIB + "/HDRI"
PBR_MASTER, LEAF_MASTER = "M_DA_PBR", "M_DA_Leaf"
PROJECT_DIR = "C:/Dev/UnrealProjects/AzimuthDubai"
UNZIP_ROOT = PROJECT_DIR + "/Saved/LibraryUnzip"
MANIFEST = "C:/Dev/naj-market-pulse/data/board/asset_library_manifest.json"
FOLIAGE_CATS = {"plants", "palms", "vegetation"}
FOLIAGE_WORDS = re.compile(r"tree|palm|plant|shrub|grass|bush|succulent|iceplant|flower|hedge|leaf|foliage", re.I)
MESH_PREF = (".fbx", ".glb", ".gltf", ".obj")
TEX_EXT = (".jpg", ".jpeg", ".png", ".tga", ".exr")

log = unreal.log
eal = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
STATS = {"imported": 0, "skipped": 0, "failed": 0}
MANIFEST_ROWS = {}


# ---------------------------------------------------------------- args / util
def parse_args():
    a = {"only": os.environ.get("DA_LIB_ONLY", ""), "source": os.environ.get("DA_LIB_SOURCE", ""),
         "limit": int(os.environ.get("DA_LIB_LIMIT", "0") or 0)}
    argv = list(sys.argv[1:])
    for i, t in enumerate(argv):
        if t in ("--only", "--source", "--limit") and i + 1 < len(argv):
            a[t[2:]] = int(argv[i + 1]) if t == "--limit" else argv[i + 1]
    a["only"], a["source"] = a["only"].lower(), a["source"].lower()
    return a


def clean(name):
    s = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    s = re.sub(r"_+", "_", s)
    return ("A_" + s) if (not s or s[0].isdigit()) else s


def ensure_dir(d):
    if not eal.does_directory_exist(d):
        eal.make_directory(d)


def folder_has_assets(d):
    return eal.does_directory_exist(d) and len(eal.list_assets(d, recursive=True, include_folder=False)) > 0


def fail(what, e):
    STATS["failed"] += 1
    unreal.log_warning("DA lib: FAIL %s: %s" % (what, e))


def import_files(files, dest, options=None, name=None):
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = f.replace("\\", "/")
        t.destination_path = dest
        t.automated = True
        t.save = True
        t.replace_existing = False
        if name:
            t.destination_name = name
        if options is not None:
            t.options = options
        tasks.append(t)
    tools.import_asset_tasks(tasks)
    out = []
    for t in tasks:
        out.extend([p for p in (t.imported_object_paths or [])])
    return out


def read_credit(folder):
    for fn in ("CREDIT.txt", "credit.txt", "license.txt"):
        p = os.path.join(folder, fn)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    return fh.read().strip()[:2000]
            except Exception:
                pass
    return ""


# ---------------------------------------------------------------- masters
def _tex_param(m, name, x, y, default, sampler):
    e = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("texture", eal.load_asset(default))
    e.set_editor_property("sampler_type", sampler)
    return e


def _uv_network(m):
    """Returns the expression that feeds every sampler's UVs: StaticSwitch(UseWorldAlignedUV, WorldPos.xy/100, UV) * Tiling."""
    tiling = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -1400, 300)
    tiling.set_editor_property("parameter_name", "Tiling"); tiling.set_editor_property("default_value", 1.0)
    uv = MEL.create_material_expression(m, unreal.MaterialExpressionTextureCoordinate, -1400, 0)
    wp = MEL.create_material_expression(m, unreal.MaterialExpressionWorldPosition, -1600, 150)
    mask = MEL.create_material_expression(m, unreal.MaterialExpressionComponentMask, -1400, 150)
    mask.set_editor_property("r", True); mask.set_editor_property("g", True)
    mask.set_editor_property("b", False); mask.set_editor_property("a", False)
    MEL.connect_material_expressions(wp, "", mask, "")
    div = MEL.create_material_expression(m, unreal.MaterialExpressionDivide, -1250, 150)
    div.set_editor_property("const_b", 100.0)            # 1 tile per metre at Tiling 1
    MEL.connect_material_expressions(mask, "", div, "A")
    sw = MEL.create_material_expression(m, unreal.MaterialExpressionStaticSwitchParameter, -1100, 50)
    sw.set_editor_property("parameter_name", "UseWorldAlignedUV"); sw.set_editor_property("default_value", False)
    MEL.connect_material_expressions(div, "", sw, "True")
    MEL.connect_material_expressions(uv, "", sw, "False")
    mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -950, 100)
    MEL.connect_material_expressions(sw, "", mul, "A")
    MEL.connect_material_expressions(tiling, "", mul, "B")
    return mul


def get_master(name, leaf):
    p = "%s/%s" % (MASTERS, name)
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    ensure_dir(MASTERS)
    m = tools.create_asset(name, MASTERS, unreal.Material, unreal.MaterialFactoryNew())
    ST = unreal.MaterialSamplerType
    uvs = _uv_network(m)
    bc = _tex_param(m, "BaseColor", -700, -300, "/Engine/EngineMaterials/DefaultDiffuse", ST.SAMPLERTYPE_COLOR)
    nm = _tex_param(m, "Normal", -700, 0, "/Engine/EngineMaterials/FlatNormal", ST.SAMPLERTYPE_NORMAL)
    rg = _tex_param(m, "Roughness", -700, 300, "/Engine/EngineMaterials/WhiteSquareTexture", ST.SAMPLERTYPE_LINEAR_COLOR)
    ao = _tex_param(m, "AO", -700, 600, "/Engine/EngineMaterials/WhiteSquareTexture", ST.SAMPLERTYPE_LINEAR_COLOR)
    for s in (bc, nm, rg, ao):
        MEL.connect_material_expressions(uvs, "", s, "UVs")
    tint = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -700, -500)
    tint.set_editor_property("parameter_name", "Tint"); tint.set_editor_property("default_value", unreal.LinearColor(1, 1, 1, 1))
    mul = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, -350, -350)
    MEL.connect_material_expressions(bc, "RGB", mul, "A")
    MEL.connect_material_expressions(tint, "", mul, "B")
    P = unreal.MaterialProperty
    MEL.connect_material_property(mul, "", P.MP_BASE_COLOR)
    MEL.connect_material_property(nm, "RGB", P.MP_NORMAL)
    MEL.connect_material_property(rg, "R", P.MP_ROUGHNESS)
    MEL.connect_material_property(ao, "R", P.MP_AMBIENT_OCCLUSION)
    if leaf:                                            # ASSET_PLAYBOOK: two-sided foliage, alpha mask, transmission colour
        m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
        m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
        m.set_editor_property("two_sided", True)
        MEL.connect_material_property(bc, "A", P.MP_OPACITY_MASK)
        sss = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -350, 800)
        sss.set_editor_property("parameter_name", "Transmission")
        sss.set_editor_property("default_value", unreal.LinearColor(0.25, 0.35, 0.08, 1))
        MEL.connect_material_property(sss, "", P.MP_SUBSURFACE_COLOR)
    for flag in ("used_with_instanced_static_meshes", "used_with_nanite", "used_with_static_lighting"):
        try:
            m.set_editor_property(flag, True)
        except Exception as e:
            log("DA lib:   master flag %s: %s" % (flag, e))
    MEL.recompile_material(m)
    eal.save_asset(p)
    log("DA lib: created master %s" % p)
    return m


# ---------------------------------------------------------------- meshes
def mesh_options(ext):
    if ext != ".fbx":
        return None                                      # glTF/glb/obj: Interchange defaults
    o = unreal.FbxImportUI()
    o.set_editor_property("import_mesh", True)
    o.set_editor_property("import_materials", True)
    o.set_editor_property("import_textures", True)
    o.set_editor_property("import_as_skeletal", False)
    o.set_editor_property("import_animations", False)
    o.set_editor_property("create_physics_asset", False)
    sm = o.static_mesh_import_data
    for k, v in (("combine_meshes", True), ("generate_lightmap_u_vs", False), ("auto_generate_collision", False),
                 ("build_nanite", True)):
        try:
            sm.set_editor_property(k, v)
        except Exception:
            pass
    return o


def enable_nanite(mesh):
    try:
        ns = mesh.get_editor_property("nanite_settings")
        if not ns.get_editor_property("enabled"):
            ns.set_editor_property("enabled", True)
            mesh.set_editor_property("nanite_settings", ns)
        return True
    except Exception as e:
        log("DA lib:   nanite %s: %s" % (mesh.get_name(), e))
        return False


def tri_count(mesh):
    for fn in (lambda: mesh.get_num_triangles(0),
               lambda: unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).get_number_triangles(mesh, 0),
               lambda: unreal.EditorStaticMeshLibrary.get_number_triangles(mesh, 0)):
        try:
            return int(fn())
        except Exception:
            continue
    return -1


def base_material(mi):
    m = mi
    for _ in range(8):
        if isinstance(m, unreal.Material) or m is None:
            return m
        m = m.get_editor_property("parent")
    return None


def leaf_fix(mesh, dest):
    """Foliage post-pass (ASSET_PLAYBOOK: black trees otherwise)."""
    leaf = get_master(LEAF_MASTER, leaf=True)
    mats = mesh.get_editor_property("static_materials")
    changed = False
    for i, sm in enumerate(mats):
        mi = sm.get_editor_property("material_interface")
        if mi is None:
            continue
        base = base_material(mi)
        bpath = base.get_path_name() if base else ""
        if base and bpath.startswith(LIB + "/") and not bpath.startswith(MASTERS):
            try:                                        # our own imported base material: edit in place
                base.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
                base.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
                base.set_editor_property("two_sided", True)
                base.set_editor_property("used_with_instanced_static_meshes", True)
                try:
                    node = MEL.get_material_property_input_node(base, unreal.MaterialProperty.MP_BASE_COLOR)
                    if isinstance(node, unreal.MaterialExpressionTextureSample):
                        MEL.connect_material_property(node, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
                except Exception as e:
                    log("DA lib:   leaf alpha %s: %s" % (base.get_name(), e))
                MEL.recompile_material(base)
                eal.save_asset(bpath.split(".")[0])
                log("DA lib:   leaf fixed in place %s" % bpath)
            except Exception as e:
                fail("leaf edit " + bpath, e)
            continue
        # parent outside our folder (Interchange / engine): new MI of M_DA_Leaf with the textures copied over
        name = clean("MI_Leaf_%s_%d" % (mesh.get_name(), i))
        p = "%s/%s" % (dest, name)
        try:
            nmi = eal.load_asset(p) if eal.does_asset_exist(p) else tools.create_asset(
                name, dest, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
            MEL.set_material_instance_parent(nmi, leaf)
            try:
                for pn in MEL.get_texture_parameter_names(mi):
                    tex = MEL.get_material_instance_texture_parameter_value(mi, pn)
                    k = str(pn).lower()
                    if tex is None:
                        continue
                    if any(w in k for w in ("base", "color", "colour", "diff", "albedo")):
                        MEL.set_material_instance_texture_parameter_value(nmi, "BaseColor", tex)
                    elif "normal" in k:
                        MEL.set_material_instance_texture_parameter_value(nmi, "Normal", tex)
            except Exception as e:
                log("DA lib:   leaf copy params %s: %s" % (mi.get_name(), e))
            eal.save_asset(p)
            sm.set_editor_property("material_interface", nmi)
            mats[i] = sm
            changed = True
        except Exception as e:
            fail("leaf MI " + p, e)
    if changed:
        mesh.set_editor_property("static_materials", mats)


def is_foliage(category, path):
    return category.lower() in FOLIAGE_CATS or bool(FOLIAGE_WORDS.search(path))


def finish_meshes(paths, dest, category, src_file, credit, source):
    for p in paths:
        a = eal.load_asset(p)
        if isinstance(a, unreal.SkeletalMesh):
            log("DA lib:   skeletal (left as is, not in gallery) %s" % p)
        if not isinstance(a, unreal.StaticMesh):
            continue
        nan = enable_nanite(a)
        if is_foliage(category, src_file):
            leaf_fix(a, dest)
        eal.save_asset(p.split(".")[0])
        row = {"asset": p.split(".")[0], "type": "StaticMesh", "source": source, "category": category,
               "source_file": src_file, "triangles": tri_count(a),
               "materials": len(a.get_editor_property("static_materials")), "nanite": nan,
               "foliage_fix": is_foliage(category, src_file), "credit": credit}
        MANIFEST_ROWS[row["asset"]] = row


def pick_mesh_files(folder):
    found = {}
    for root, _, files in os.walk(folder):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in MESH_PREF:
                found.setdefault(ext, []).append(os.path.join(root, f))
    for ext in MESH_PREF:
        if ext in found:
            return ext, sorted(found[ext])
    return None, []


def unzip_pack(folder, key):
    """Extract nested zips of a Sketchfab pack to Saved/LibraryUnzip (never into C:/Dev/assets)."""
    out = os.path.join(UNZIP_ROOT, key)
    if os.path.isdir(out) and os.listdir(out):
        return out
    zips = [os.path.join(r, f) for r, _, fs in os.walk(folder) for f in fs if f.lower().endswith(".zip")]
    zips.sort(key=lambda z: (os.path.dirname(z) == folder, z))       # source/*.zip first, then the pack zip
    for z in zips:
        try:
            with zipfile.ZipFile(z) as zf:
                zf.extractall(os.path.join(out, clean(os.path.splitext(os.path.basename(z))[0])))
        except Exception as e:
            log("DA lib:   unzip %s: %s" % (z, e))
    return out if os.path.isdir(out) else None


# ---------------------------------------------------------------- jobs
def jobs():
    """Yields (source, category, asset_name, kind, folder_or_files)."""
    ph = os.path.join(ASSETS, "polyhaven_2k")
    for d in sorted(os.listdir(ph)):
        full = os.path.join(ph, d)
        if os.path.isdir(full) and d not in ("models", "textures", "hdris", "hdris_dubai"):
            yield ("PolyHaven", "Plants", d, "mesh", full)
    for sub, cat in (("models", "Models"), ("textures", "Textures")):
        base = os.path.join(ph, sub)
        for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if os.path.isdir(os.path.join(base, d)):
                yield ("PolyHaven", cat, d, "mesh" if cat == "Models" else "texset", os.path.join(base, d))
    for sub, grp in (("hdris", "PolyHaven"), ("hdris_dubai", "Dubai")):
        base = os.path.join(ph, sub)
        for f in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if f.lower().endswith(".hdr"):
                yield ("HDRI", grp, os.path.splitext(f)[0], "hdri", os.path.join(base, f))
    ac = os.path.join(ASSETS, "ambientcg_2k")
    for cat in sorted(os.listdir(ac)) if os.path.isdir(ac) else []:
        cdir = os.path.join(ac, cat)
        if os.path.isdir(cdir):
            for d in sorted(os.listdir(cdir)):
                if os.path.isdir(os.path.join(cdir, d)):
                    yield ("AmbientCG", clean(cat), d, "texset", os.path.join(cdir, d))
    for top in sorted(os.listdir(ASSETS)):
        if top.startswith("sketchfab_") and os.path.isdir(os.path.join(ASSETS, top)):
            cat = top[len("sketchfab_"):]
            for d in sorted(os.listdir(os.path.join(ASSETS, top))):
                if os.path.isdir(os.path.join(ASSETS, top, d)):
                    yield ("Sketchfab", cat, d, "mesh", os.path.join(ASSETS, top, d))


def do_mesh(source, category, name, folder, dest):
    credit = read_credit(folder) or ("CC0 - Poly Haven" if source == "PolyHaven" else "")
    ext, files = pick_mesh_files(folder)
    if not files and source == "Sketchfab":
        un = unzip_pack(folder, "%s/%s" % (category, clean(name)))
        if un:
            ext, files = pick_mesh_files(un)
    if not files:
        raise RuntimeError("no fbx/glb/gltf/obj in " + folder)
    if len(files) > 12:
        log("DA lib:   %s: %d mesh files, importing first 12" % (name, len(files)))
        files = files[:12]
    paths = import_files(files, dest, mesh_options(ext))
    if not paths:
        raise RuntimeError("import returned nothing for %s" % files[0])
    finish_meshes(paths, dest, category, ";".join(f.replace("\\", "/") for f in files), credit, source)


def classify_tex(fn):
    f = fn.lower()
    if "displacement" in f or "_disp" in f or "normaldx" in f or "_nor_dx" in f or f.endswith(".png") and "_" not in f:
        return None
    if "normalgl" in f or "_nor_gl" in f or "normal" in f:
        return "Normal"
    if "roughness" in f or "_rough" in f:
        return "Roughness"
    if "ambientocclusion" in f or "_ao" in f:
        return "AO"
    if "_arm" in f:
        return "ARM"                                     # Poly Haven packed AO/Rough/Metal
    if "color" in f or "_diff" in f or "albedo" in f:
        return "BaseColor"
    return None


def do_texset(source, category, name, folder, dest):
    picks = {}
    for root, _, fs in os.walk(folder):
        for f in fs:
            if os.path.splitext(f)[1].lower() in TEX_EXT:
                k = classify_tex(f)
                if k and k not in picks:
                    picks[k] = os.path.join(root, f)
    if "BaseColor" not in picks:
        raise RuntimeError("no colour map in " + folder)
    texs = {}
    for k, f in picks.items():
        got = import_files([f], dest, name=clean("T_%s_%s" % (name, k)))
        if not got:
            continue
        t = eal.load_asset(got[0])
        if k != "BaseColor":
            t.set_editor_property("srgb", False)
            t.set_editor_property("compression_settings",
                                  unreal.TextureCompressionSettings.TC_NORMALMAP if k == "Normal" else unreal.TextureCompressionSettings.TC_MASKS)
            eal.save_asset(got[0].split(".")[0])
        texs[k] = t
    master = get_master(PBR_MASTER, leaf=False)
    mi_name = clean("MI_" + name)
    mi = tools.create_asset(mi_name, dest, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, master)
    for k in ("BaseColor", "Normal", "Roughness", "AO"):
        if k in texs:
            MEL.set_material_instance_texture_parameter_value(mi, k, texs[k])
    if "ARM" in texs:                                    # packed: R = AO, G = roughness (master reads .R, so use AO only)
        MEL.set_material_instance_texture_parameter_value(mi, "AO", texs["ARM"])
    MEL.set_material_instance_scalar_parameter_value(mi, "Tiling", 1.0)
    eal.save_asset("%s/%s" % (dest, mi_name))
    MANIFEST_ROWS["%s/%s" % (dest, mi_name)] = {
        "asset": "%s/%s" % (dest, mi_name), "type": "MaterialInstance", "source": source, "category": category,
        "source_file": folder.replace("\\", "/"), "textures": sorted(texs), "triangles": 0, "materials": 1,
        "credit": read_credit(folder) or ("CC0 - ambientCG" if source == "AmbientCG" else "CC0 - Poly Haven")}


def do_hdri(group, name, f):
    dest = "%s/%s" % (HDRI_DIR, group)
    got = import_files([f], dest, name=clean("HDR_" + name))
    if not got:
        raise RuntimeError("hdr import returned nothing")
    a = eal.load_asset(got[0])
    MANIFEST_ROWS[got[0].split(".")[0]] = {
        "asset": got[0].split(".")[0], "type": a.get_class().get_name(), "source": "PolyHaven", "category": "HDRI/" + group,
        "source_file": f.replace("\\", "/"), "triangles": 0, "materials": 0, "credit": "CC0 - Poly Haven"}
    if not isinstance(a, unreal.TextureCube):
        log("DA lib:   WARN %s imported as %s, not TextureCube" % (name, a.get_class().get_name()))


def load_manifest():
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, encoding="utf-8") as fh:
                for r in json.load(fh).get("assets", []):
                    MANIFEST_ROWS[r["asset"]] = r
        except Exception as e:
            log("DA lib: manifest unreadable, starting fresh: %s" % e)


def save_manifest():
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    rows = sorted(MANIFEST_ROWS.values(), key=lambda r: r["asset"])
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "root": LIB, "count": len(rows), "assets": rows}, fh, indent=1)


def main():
    args = parse_args()
    log("DA lib: start only=%r source=%r limit=%r" % (args["only"], args["source"], args["limit"]))
    load_manifest()
    ensure_dir(LIB)
    new = 0
    for source, category, name, kind, folder in jobs():
        if args["source"] and args["source"] != source.lower():
            continue
        if args["only"] and args["only"] not in (category.lower(), source.lower() if kind == "hdri" else "\0"):
            continue
        names = [n.strip().lower() for n in os.environ.get("DA_LIB_NAMES", "").split(",") if n.strip()]
        if names and name.lower() not in names:            # DA_LIB_NAMES=a,b,c: import just these assets (29 Sep)
            continue
        if args["limit"] and new >= args["limit"]:
            break
        dest = ("%s/%s" % (HDRI_DIR, category)) if kind == "hdri" else "%s/%s/%s/%s" % (LIB, source, clean(category), clean(name))
        if kind == "hdri":
            if eal.does_asset_exist("%s/%s" % (dest, clean("HDR_" + name))):
                STATS["skipped"] += 1
                continue
        elif folder_has_assets(dest):
            STATS["skipped"] += 1
            continue
        try:
            log("DA lib: import %s/%s/%s (%s)" % (source, category, name, kind))
            if kind == "mesh":
                do_mesh(source, category, name, folder, dest)
            elif kind == "texset":
                do_texset(source, category, name, folder, dest)
            else:
                do_hdri(category, name, folder)
            STATS["imported"] += 1
            new += 1
        except Exception as e:
            fail("%s/%s/%s" % (source, category, name), e)
        if new and new % 10 == 0:
            save_manifest()
    save_manifest()
    log("DA lib: done %s manifest=%s (%d rows)" % (STATS, MANIFEST, len(MANIFEST_ROWS)))


if __name__ == "__main__":
    main()
