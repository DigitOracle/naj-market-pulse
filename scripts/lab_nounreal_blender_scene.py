"""LAB (no-Unreal, research only): Blender 5.1 Cycles scene for the Business Bay v1 hero stills - runs INSIDE Blender.

Launched by lab_nounreal_blender.py (blender -b --factory-startup -P this -- <cfg.json>); never run it by hand.
Builds the same scene as lab_nounreal_render.py (three.js v2) from the same inputs, read-only:
  towers    data/ce/_glb/sky_businessbay_v5_0.glb (local v5 frame), materials by role and building exactly as the three.js
            renderer decides them (facade_tables: palette looks, landmarks_v2 glass, the M_DA_Facade band / mullion / shopfront
            pattern as a Cycles node group), landmark heights, construction tops + tower cranes, crowns
  downtown  data/ce/_glb/sky_burjkhalifa_v3_0.merged.glb (the un-meshopt'd twin of the v3 backdrop, absolute CE coordinates),
            hidden within 70 m of the Burj, + the hero Burj OBJs
  scenery   data/lab/context/businessbay/{ground,vegetation,furniture,props}_businessbay_v5.glb (EXT_mesh_gpu_instancing ->
            linked duplicates sharing one mesh each; 'json' klass nodes removed for film parity; roughness / metallic /
            emissive / opacity restored from context_palette.json; canal + city water set to the film's water colour)
  context   bb_v1 surroundings OBJs (UE frame) + a 60 km procedural sand plane
Frames: Blender world = (E - 325931, N - 2786402, up) metres; glTF (x, y, z) -> (x, -z, y) by the importer; three.js
(x, y, z) -> (x, -z, y); UE cm (X, Y, Z) -> (X/100 + 2358, -(Y/100 + 1804), Z/100). Land (lift) at z = 1.2 as in the film.
Light: sun lamp (33 deg / 248 deg, colour 1.0 0.88 0.74, 0.54 deg disc) + world = golden_bay_4k HDR desaturated to 0.3 (as
Unreal's sky light), its sun turned onto ours; camera rays see nothing (film transparent: the sky plate is composited in the
develop step). Passes: Combined (denoised), Mist, light groups sun / sky, diffuse direct / indirect / colour -> one
multilayer EXR per view (half float) + timings JSON. Research only; writes only under data/lab/no_unreal/cycles/.
"""
import json
import math
import os
import re
import subprocess
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector

CFG = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
T0 = time.time()
LOG = []


def log(m):
    s = "%7.1fs %s" % (time.time() - T0, m)
    LOG.append(s); print("[cycles] " + s, flush=True)


# ------------------------------------------------------------------------------------------------ shared-machine guards
def free_ram_gb():
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS(); m.dwLength = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 1024.0 ** 3


def three_render_active(sample_s=4.0):
    """a lab_nounreal_render.py job is ACTIVELY rendering: a headless browser (chrome-headless-shell, or chrome / msedge
    --headless) descends from its python (python -> playwright node driver -> browser) AND is working - its CPU time rises
    over sample_s or the GPU is above 10 %. A python that is merely waiting (for RAM or for blender.exe) never counts."""
    ps = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return False
    rows = {}
    for ln in out.splitlines():
        p = ln.split("|", 3)
        if len(p) == 4 and p[0].isdigit():
            rows[int(p[0])] = (int(p[1]) if p[1].isdigit() else 0, p[2].lower(), p[3])
    three = {pid for pid, r in rows.items() if r[1].startswith("python") and "lab_nounreal_render.py" in r[2]}
    if not three:
        return False
    browsers = []
    for pid, (ppid, name, cmd) in rows.items():
        if "headless" in name or (name in ("chrome.exe", "msedge.exe") and "--headless" in cmd):
            p, hops = ppid, 0
            while p and hops < 8:
                if p in three:
                    browsers.append(pid); break
                p = rows.get(p, (0,))[0]; hops += 1
    if not browsers:
        return False

    def cpu():
        q = "(Get-Process -Id %s -ErrorAction SilentlyContinue | Measure-Object -Property CPU -Sum).Sum" % ",".join(str(b) for b in browsers)
        try:
            return float(subprocess.run(["powershell", "-NoProfile", "-Command", q], capture_output=True, text=True, timeout=60).stdout.strip() or 0)
        except Exception:
            return 0.0
    c0 = cpu(); time.sleep(sample_s); c1 = cpu()
    try:
        gpu = float(subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=30).stdout.split()[0])
    except Exception:
        gpu = 0.0
    return (c1 - c0) > 0.2 or gpu > 10.0


def wait_turn(min_gb, max_wait_s):
    t = time.time()
    while True:
        g = free_ram_gb(); hb = three_render_active()
        if g >= min_gb and not hb:
            return g
        if time.time() - t > max_wait_s:
            raise SystemExit("gave up waiting (free RAM %.1f GB, headless three.js render running: %s)" % (g, hb))
        log("waiting: free RAM %.1f GB (need %.1f), three.js headless render running: %s" % (g, min_gb, hb)); time.sleep(30)


# ------------------------------------------------------------------------------------------------ frames
E0, N0 = 325931.0, 2786402.0
UE_DX, UE_DY = 328289.0 - E0, 2784598.0 - N0          # Blender x = X/100 + 2358 ; Blender y = N - N0 = -(Y/100) - 1804
LIFT = float(CFG["lift"])


def three_to_bl(p):
    return Vector((p[0], -p[2], p[1]))


# ------------------------------------------------------------------------------------------------ node helpers
def _sock(nt, dst, v):
    if isinstance(v, bpy.types.NodeSocket):
        nt.links.new(v, dst)
    elif v is not None:
        if isinstance(v, (int, float)) and dst.type == "VECTOR":
            v = (v, v, v)
        dst.default_value = v


class NB:
    """tiny node-graph builder: math on sockets or constants"""
    def __init__(self, nt):
        self.nt = nt

    def m(self, op, a, b=None, c=None, clamp=False):
        n = self.nt.nodes.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, v in enumerate((a, b, c)):
            _sock(self.nt, n.inputs[i], v)
        return n.outputs[0]

    def v(self, op, a, b=None, c=None):
        n = self.nt.nodes.new("ShaderNodeVectorMath"); n.operation = op
        for i, x in enumerate((a, b, c)):
            _sock(self.nt, n.inputs[i], x)
        return n.outputs[0]

    def smooth(self, x, lo, hi, a=0.0, b=1.0):          # smoothstep(lo, hi, x) remapped to a..b, clamped
        n = self.nt.nodes.new("ShaderNodeMapRange"); n.interpolation_type = "SMOOTHSTEP"; n.clamp = True
        for key, val in (("Value", x), ("From Min", lo), ("From Max", hi), ("To Min", a), ("To Max", b)):
            _sock(self.nt, n.inputs[key], val)
        return n.outputs["Result"]

    def mixf(self, a, b, t):                            # a + (b - a) t
        return self.m("MULTIPLY_ADD", self.m("SUBTRACT", b, a), t, a)

    def mixc(self, a, b, t):                            # colour / vector mix via vector math
        return self.v("MULTIPLY_ADD", self.v("SUBTRACT", b, a), t, a)

    def xyz(self, vec):
        n = self.nt.nodes.new("ShaderNodeSeparateXYZ"); self.nt.links.new(vec, n.inputs[0]); return n.outputs


def facade_group():
    """M_DA_Facade (ue_bb_facade.py HLSL) as lab_nounreal_render.py's FAC_GLSL: floor band every Floor, mullion every Pane,
    roof mask by normal, ground-floor shopfront layer under StoreTop - world-space, Blender z up"""
    ng = bpy.data.node_groups.new("DA_Facade", "ShaderNodeTree")
    I = ng.interface
    for nm in ("Glass", "Frame", "Span", "Roof"):
        I.new_socket(nm, in_out="INPUT", socket_type="NodeSocketColor")
    for nm in ("GR", "FR", "SR", "RR", "GM", "FM", "SM", "RM", "Floor", "Pane", "Band", "Mull", "Land", "StoreTop", "IOR"):
        I.new_socket(nm, in_out="INPUT", socket_type="NodeSocketFloat")
    I.new_socket("BSDF", in_out="OUTPUT", socket_type="NodeSocketShader")
    gi = ng.nodes.new("NodeGroupInput"); go = ng.nodes.new("NodeGroupOutput")
    g = gi.outputs; b = NB(ng)
    geo = ng.nodes.new("ShaderNodeNewGeometry")
    px, py, pz = b.xyz(geo.outputs["Position"])[:3]
    nx, ny, nz = b.xyz(geo.outputs["True Normal"])[:3]
    wall = b.smooth(b.m("ABSOLUTE", nz), 0.55, 0.75, 1.0, 0.0)                     # 1 - smoothstep(0.55, 0.75, |n.z|)
    sel = b.m("GREATER_THAN", b.m("ABSOLUTE", nx), b.m("ABSOLUTE", ny))
    hz = b.mixf(px, b.m("MULTIPLY", py, -1.0), sel)                                  # three: |n.x| > |n.z| ? z : x   (three z = -y)
    fl = b.m("MAXIMUM", g["Floor"], 0.5); pn = b.m("MAXIMUM", g["Pane"], 0.3)
    fz = b.m("FRACT", b.m("DIVIDE", b.m("SUBTRACT", pz, g["Land"]), fl))
    fu = b.m("FRACT", b.m("DIVIDE", hz, pn))
    bw = b.m("DIVIDE", g["Band"], fl, clamp=True); mw = b.m("DIVIDE", g["Mull"], pn, clamp=True)
    band = b.m("GREATER_THAN", fz, b.m("SUBTRACT", 1.0, bw)); mull = b.m("GREATER_THAN", fu, b.m("SUBTRACT", 1.0, mw))
    mR = b.m("MULTIPLY", band, wall)
    mG = b.m("MULTIPLY", b.m("MULTIPLY", mull, wall), b.m("SUBTRACT", 1.0, mR))
    mB = b.m("SUBTRACT", 1.0, wall)
    col = b.mixc(b.mixc(b.mixc(g["Glass"], g["Frame"], mG), g["Span"], mR), g["Roof"], mB)
    rou = b.mixf(b.mixf(b.mixf(g["GR"], g["FR"], mG), g["SR"], mR), g["RR"], mB)
    met = b.mixf(b.mixf(b.mixf(g["GM"], g["FM"], mG), g["SM"], mR), g["RM"], mB)
    st = g["StoreTop"]
    inStore = b.m("MULTIPLY", b.smooth(pz, b.m("SUBTRACT", st, 0.04), b.m("ADD", st, 0.04), 1.0, 0.0), wall)
    sfr = b.m("GREATER_THAN", b.m("FRACT", b.m("DIVIDE", hz, 3.0)), 0.94)
    sgn = b.smooth(pz, b.m("SUBTRACT", st, 0.95), b.m("SUBTRACT", st, 0.85))
    sfm = b.m("MULTIPLY", sfr, b.m("SUBTRACT", 1.0, sgn))
    colS = b.mixc(b.mixc((0.16, 0.11, 0.06), (0.05, 0.05, 0.05), sfm), (0.07, 0.07, 0.075), sgn)
    col = b.mixc(col, colS, inStore)
    rou = b.mixf(rou, b.mixf(b.mixf(0.05, 0.4, sfm), 0.4, sgn), inStore)
    met = b.mixf(met, b.mixf(b.mixf(0.2, 0.8, sfm), 0.05, sgn), inStore)
    bs = ng.nodes.new("ShaderNodeBsdfPrincipled")
    ng.links.new(col, bs.inputs["Base Color"]); ng.links.new(rou, bs.inputs["Roughness"]); ng.links.new(met, bs.inputs["Metallic"])
    ng.links.new(g["IOR"], bs.inputs["IOR"])
    ng.links.new(bs.outputs[0], go.inputs["BSDF"])
    return ng


FAC = None
MATS = {}


def _nodes(idb):
    """Blender 5.x: node trees are always on; the use_nodes switch is deprecated / may be gone"""
    try:
        if not idb.use_nodes:
            idb.use_nodes = True
    except AttributeError:
        pass


def principled(name, rgb, rough, metal, ior=1.5, alpha=1.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name); _nodes(m)
    bs = m.node_tree.nodes.get("Principled BSDF")
    bs.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bs.inputs["Roughness"].default_value = float(rough); bs.inputs["Metallic"].default_value = float(metal)
    bs.inputs["IOR"].default_value = float(ior)
    if alpha < 1.0:
        bs.inputs["Alpha"].default_value = alpha
    MATS[name] = m
    return m


def facade_mat(name, p):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name); _nodes(m)
    nt = m.node_tree; nt.nodes.remove(nt.nodes.get("Principled BSDF"))
    gn = nt.nodes.new("ShaderNodeGroup"); gn.node_tree = FAC
    out = nt.nodes.get("Material Output"); nt.links.new(gn.outputs[0], out.inputs["Surface"])
    roof = p.get("roof") or [0.42, 0.42, 0.41]
    for k, v in (("Glass", p["glass"]), ("Frame", p["frame"]), ("Span", p["span"]), ("Roof", roof)):
        gn.inputs[k].default_value = (v[0], v[1], v[2], 1.0)
    vals = {"GR": p["gr"], "FR": p["fr"], "SR": p["sr"], "RR": 0.85, "GM": p["gm"], "FM": p["fm"], "SM": p["sm"], "RM": 0.0,
            "Floor": p["floor"], "Pane": p["pane"], "Band": p["band"], "Mull": p["mull"], "Land": LIFT,
            "StoreTop": -1e7 if p.get("store") is False else LIFT + 5.5, "IOR": CFG.get("glass_ior", 1.5)}
    for k, v in vals.items():
        gn.inputs[k].default_value = float(v)
    MATS[name] = m
    return m


# ------------------------------------------------------------------------------------------------ tower materials (lab_nounreal_render.py towerMaterial / facadeKey, same tables)
F = CFG["facade"]; LM = {int(k): v for k, v in CFG["landmarks"].items()}
PER = {int(k): v for k, v in F["per"].items()}
LMK = CFG["lmk"]; CONS = {int(k): v for k, v in LMK["construction"].items()}


def PE(k):
    return F["pal"].get(k) or F["pal"]["white"]


def role_of(nm):
    n = nm.lower()
    if re.search(r"spandrel", n): return "spandrel"
    if re.search(r"vision|retail_glass|window_glass|balustrade", n): return "vision"
    if re.search(r"balcony_slab|slab_band|parapet", n): return "slabs"
    if re.search(r"mullion|column|fin", n): return "fins"
    if re.search(r"roof", n): return "roof"
    if re.search(r"_wall", n): return "walls"
    return "vision" if "glass" in n else "walls"


def facade_key(idx, kind, is_bb):
    look = PER.get(idx) or ["white", "blue_glass", "sandstone", "white"]
    lf = LM.get(idx); cons = kind == "cons"
    key = ("bb|" if is_bb else "dt|") + ("cons" if cons else ("lm%d" % idx if lf else "/".join(look))) + "|" + kind
    if key in MATS:
        return MATS[key]
    if cons:
        p = {"glass": [0.035, 0.035, 0.037], "frame": [0.42, 0.41, 0.39], "span": [0.50, 0.49, 0.47], "roof": [0.46, 0.45, 0.43], "floor": 3.4,
             "pane": 7.5, "band": 0.45, "mull": 0.7, "gr": 0.9, "gm": 0.0, "fr": 0.85, "fm": 0.0, "sr": 0.85, "sm": 0.0, "store": False}
    else:
        gl, fi, sl, wa = PE(look[1]), PE(look[3]), PE(look[2]), PE(look[0])
        fh = F.get("floor") or (lf["floor"] if lf else 3.4); pw = lf["pane"] if lf else 1.5
        if kind == "glass":
            p = {"glass": lf["glass"] if lf else gl[0], "frame": lf["frame"] if lf else fi[0], "span": lf["span"] if lf else [c * 0.55 for c in gl[0]],
                 "floor": fh, "pane": pw, "band": F.get("band") or 0.8, "mull": F.get("mull") or 0.12,
                 "gr": max(0.04, gl[1]), "gm": min(0.8, gl[2] + 0.1), "fr": 0.35, "fm": 0.6, "sr": 0.3, "sm": 0.35}
        else:
            p = {"glass": wa[0], "frame": [c * 0.8 for c in gl[0]], "span": sl[0], "floor": fh, "pane": 3.0, "band": 0.35, "mull": 1.7,
                 "gr": max(0.5, wa[1]), "gm": 0.0, "fr": 0.08, "fm": 0.5, "sr": 0.6, "sm": 0.0}
    return facade_mat(key, p)


def tower_material(idx, src_name, is_bb):
    role = role_of(src_name)
    look = PER.get(idx) or ["white", "blue_glass", "sandstone", "white"]
    if is_bb and idx in CONS:
        return facade_key(idx, "cons", is_bb)
    if role in ("vision", "spandrel") or (role == "walls" and "glass" in src_name.lower()):
        return facade_key(idx, "glass", is_bb)
    if role == "walls":
        return facade_key(idx, "wall", is_bb)
    if role == "slabs":
        e = PE(look[2]); return principled(look[2] + "_slabs", e[0], e[1], e[2])
    if role == "fins":
        e = PE(look[3]); return principled(look[3] + "_fins", e[0], e[1], e[2])
    e = PE("roof"); return principled("roof", e[0], e[1], e[2])


def crown_mat(mk):
    H = lambda h: [(int(h[i:i + 2], 16) / 255.0) for i in (1, 3, 5)]
    lin = lambda c: [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]   # THREE.Color(hex) is sRGB -> linear
    if mk == "cream":
        e = PE("ivory_stone"); return principled("crown_cream", e[0], e[1], 0)
    if mk == "white" or mk not in ("crown_glass", "steel", "bronze"):
        e = PE("white"); return principled("crown_white", e[0], e[1], 0)
    P = {"crown_glass": dict(glass=lin(H("#BFE3F5")), frame=lin(H("#F2F2EF")), span=lin(H("#9FC7DD")), floor=3.0, pane=1.2, band=0.9, mull=0.12, gr=0.05, gm=0.7, fr=0.4, fm=0.8, sr=0.3, sm=0.4, store=False),
         "steel": dict(glass=lin(H("#C8CACC")), frame=lin(H("#B0B2B4")), span=lin(H("#A0A3A6")), floor=3.6, pane=1.5, band=0.9, mull=0.12, gr=0.2, gm=1.0, fr=0.4, fm=0.8, sr=0.3, sm=0.4, store=False),
         "bronze": dict(glass=lin(H("#B8894F")), frame=lin(H("#9A6E3A")), span=lin(H("#8A6234")), floor=3.6, pane=1.5, band=0.9, mull=0.12, gr=0.3, gm=1.0, fr=0.4, fm=1.0, sr=0.3, sm=0.4, store=False)}
    return facade_mat("crown|" + mk, P[mk])


# ------------------------------------------------------------------------------------------------ geometry loaders
def read_obj(path):
    V, Fs = [], []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            if ln.startswith("v "):
                V.append(ln[2:])
            elif ln.startswith("f "):
                Fs.append(ln[2:].split()[:3])
    v = np.array(" ".join(V).split(), dtype=np.float64).reshape(-1, 3)
    f = np.array([[int(t.split("/")[0]) for t in r] for r in Fs], dtype=np.int64) - 1
    return v, f


def mesh_obj(name, v, f, mat, coll):
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(v)); me.vertices.foreach_set("co", v.astype(np.float32).ravel())
    me.loops.add(f.size); me.loops.foreach_set("vertex_index", f.astype(np.int32).ravel())
    me.polygons.add(len(f)); me.polygons.foreach_set("loop_start", (np.arange(len(f), dtype=np.int32) * 3))
    me.update(calc_edges=True)
    if mat:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me); coll.objects.link(ob)
    return ob


def ue_obj(path, z_off, mat, coll, sx=1.0, sz=1.0, ox=None, oy=None):
    """UE-frame OBJ (cm, X east, Y south, Z up) -> Blender world; ox / oy = Blender x / y of the OBJ origin (default: the UE origin);
    mirrors Y, so the winding is swapped (as the three.js loader does)"""
    v, f = read_obj(path)
    ox = UE_DX if ox is None else ox; oy = UE_DY if oy is None else oy
    w = np.empty_like(v)
    w[:, 0] = v[:, 0] / 100.0 * sx + ox; w[:, 1] = -(v[:, 1] / 100.0 * sx) + oy; w[:, 2] = v[:, 2] / 100.0 * sz + z_off
    return mesh_obj(os.path.basename(path)[:-4], w, f[:, [0, 2, 1]], mat, coll)


def import_glb(path, shading="NORMALS"):
    before = set(bpy.data.objects)
    t = time.time()
    bpy.ops.import_scene.gltf(filepath=path, import_shading=shading, import_scene_extras=True, import_select_created_objects=False)
    new = [o for o in bpy.data.objects if o not in before]
    log("glb %s: %d objects, %d mesh datablocks, %.1f s" % (os.path.basename(path), len(new), len({o.data for o in new if o.type == "MESH"}), time.time() - t))
    return new


def world_bbox(objs):
    lo = np.array([1e18] * 3); hi = -lo
    for o in objs:
        mw = o.matrix_world
        for c in o.bound_box:
            p = mw @ Vector(c); lo = np.minimum(lo, p); hi = np.maximum(hi, p)
    return lo, hi


# ------------------------------------------------------------------------------------------------ scene
def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    pr = bpy.context.preferences.addons["cycles"].preferences
    pr.compute_device_type = CFG.get("device_type", "OPTIX"); pr.get_devices()
    for d in pr.devices:
        d.use = d.type == pr.compute_device_type
    cy = sc.cycles
    cy.device = "GPU"; cy.samples = int(CFG["samples"]); cy.use_adaptive_sampling = True; cy.adaptive_threshold = float(CFG.get("adaptive", 0.02))
    cy.use_denoising = True; cy.denoiser = CFG.get("denoiser", "OPENIMAGEDENOISE"); cy.denoising_use_gpu = True
    cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"; cy.denoising_prefilter = "ACCURATE"
    cy.max_bounces = 8; cy.diffuse_bounces = int(CFG.get("diffuse_bounces", 4)); cy.glossy_bounces = 4; cy.transmission_bounces = 4
    cy.transparent_max_bounces = 8; cy.volume_bounces = 0
    cy.sample_clamp_indirect = float(CFG.get("clamp_indirect", 10.0)); cy.blur_glossy = 1.0
    cy.caustics_reflective = False; cy.caustics_refractive = False; cy.use_light_tree = True
    cy.seed = int(CFG.get("seed", 0)); cy.use_animated_seed = bool(CFG.get("animated_seed", False))
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = int(CFG["W"]), int(CFG["H"]), 100
    r.film_transparent = True; r.use_persistent_data = True; r.use_motion_blur = False
    r.image_settings.media_type = "MULTI_LAYER_IMAGE"                  # Blender 5.x: multilayer EXR is a media type
    r.image_settings.file_format = "OPEN_EXR_MULTILAYER"; r.image_settings.color_depth = "16"; r.image_settings.exr_codec = "ZIP"
    r.use_compositing = False; r.use_sequencer = False
    sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
    vl = bpy.context.view_layer
    vl.use_pass_mist = True
    if CFG.get("analysis_passes", True):
        vl.use_pass_diffuse_direct = True; vl.use_pass_diffuse_indirect = True; vl.use_pass_diffuse_color = True
    for g in ("sun", "sky"):
        vl.lightgroups.add(name=g)
    return sc


def world_and_sun(sc):
    sd = Vector(CFG["sun_bl"]).normalized()
    ld = bpy.data.lights.new("SUN", "SUN"); ld.energy = float(CFG["sun_strength"]); ld.color = CFG["sun_rgb"]
    ld.angle = math.radians(CFG.get("sun_angle_deg", 0.535))
    so = bpy.data.objects.new("SUN", ld); sc.collection.objects.link(so)
    so.rotation_euler = sd.to_track_quat("Z", "Y").to_euler(); so.lightgroup = "sun"
    w = bpy.data.worlds.new("W"); sc.world = w; _nodes(w); w.lightgroup = "sky"
    nt = w.node_tree; nt.nodes.clear(); b = NB(nt)
    out = nt.nodes.new("ShaderNodeOutputWorld"); bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = float(CFG["sky_strength"])
    tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(CFG["hdri_rot_deg"]))
    mode = CFG.get("world", "hdri_nosun")
    if mode == "nishita":                                 # physical sky for the same sun (the lamp is the sun: no disc)
        env = nt.nodes.new("ShaderNodeTexSky"); env.sky_type = "MULTIPLE_SCATTERING"; env.sun_disc = False
        env.sun_elevation = math.asin(sd.z); env.sun_rotation = math.atan2(sd.x, sd.y)     # azimuth clockwise from +Y (north)
        env.altitude = 0.0; env.aerosol_density = float(CFG.get("aerosol", 2.0))
        src = env.outputs["Color"]
    else:
        env = nt.nodes.new("ShaderNodeTexEnvironment"); env.image = bpy.data.images.load(CFG["hdri"])
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
        src = env.outputs["Color"]
        if mode == "hdri_nosun":                          # the HDRI's own sun (and its sea glitter) clipped: the lamp is the only sun
            src = b.v("MINIMUM", src, float(CFG.get("hdri_clamp", 10.0)))
        elif mode == "ue_skylight":                       # Unreal's SkyLight as Lumen uses it: diffuse (and every non-glossy ray)
            eb = nt.nodes.new("ShaderNodeTexEnvironment"); eb.image = bpy.data.images.load(CFG["hdri_blur"])   # sees the whole HDRI,
            nt.links.new(mp.outputs["Vector"], eb.inputs["Vector"])                                            # its sun included,
            lp = nt.nodes.new("ShaderNodeLightPath")                                                            # blurred; glossy rays
            src = b.mixc(eb.outputs["Color"], env.outputs["Color"], lp.outputs["Is Glossy Ray"])               # see the sharp sky
    bw = nt.nodes.new("ShaderNodeRGBToBW"); nt.links.new(src, bw.inputs[0])
    col = b.mixc(bw.outputs[0], src, float(CFG.get("hdri_sat", 0.3)))       # mix(luma, c, 0.3) as UE adjust_saturation
    nt.links.new(col, bg.inputs["Color"]); nt.links.new(bg.outputs[0], out.inputs["Surface"])
    ms = w.mist_settings; ms.start = float(CFG.get("fog_near", 6000.0)); ms.depth = float(CFG.get("fog_far", 45000.0)) - ms.start; ms.falloff = "LINEAR"
    log("sun %.2f W/m2 dir %s colour %s; world %s (%s) x %.2f, turned %.1f deg, saturation %.2f"
        % (ld.energy, tuple(round(x, 3) for x in sd), tuple(CFG["sun_rgb"]), mode, os.path.basename(CFG["hdri"]), CFG["sky_strength"], CFG["hdri_rot_deg"], CFG.get("hdri_sat", 0.3)))


def sand_plane(coll):
    m = bpy.data.materials.new("sand_plane"); _nodes(m); nt = m.node_tree; b = NB(nt)
    bs = nt.nodes.get("Principled BSDF"); bs.inputs["Roughness"].default_value = 0.95
    geo = nt.nodes.new("ShaderNodeNewGeometry"); nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 0.02; nz.inputs["Detail"].default_value = 3.0
    nt.links.new(geo.outputs["Position"], nz.inputs["Vector"])
    t = b.smooth(nz.outputs["Fac"], 0.3, 0.7)
    nt.links.new(b.mixc(tuple(CFG["sand_dark"]), tuple(CFG["sand_light"]), t), bs.inputs["Base Color"])
    v = np.array([[-30000, -30000, -0.2], [30000, -30000, -0.2], [30000, 30000, -0.2], [-30000, 30000, -0.2]], float)
    return mesh_obj("sand_plane", v, np.array([[0, 1, 2], [0, 2, 3]]), m, coll)


def water_mat():
    return principled("water", CFG["water_rgb"], 0.07, 0.0, ior=1.33)


def fix_scenery_materials(objs):
    pal = CFG["ctx_palette"]; seen = set(); fixed = 0
    for o in objs:
        if o.type != "MESH":
            continue
        for s in o.material_slots:
            m = s.material
            if not m or m.name in seen:
                continue
            seen.add(m.name); base = re.sub(r"\.\d+$", "", m.name)
            bs = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m.node_tree else None
            if not bs:
                continue
            role = pal.get(base)
            if role:
                if "roughness" in role and not bs.inputs["Roughness"].is_linked:
                    bs.inputs["Roughness"].default_value = float(role["roughness"]); fixed += 1
                if "metallic" in role and not bs.inputs["Metallic"].is_linked:
                    bs.inputs["Metallic"].default_value = float(role["metallic"])
                if role.get("emissive_rgb") and not bs.inputs["Emission Color"].is_linked:
                    c = role["emissive_rgb"]; bs.inputs["Emission Color"].default_value = (c[0], c[1], c[2], 1.0)
                    if bs.inputs["Emission Strength"].default_value <= 0.0:
                        bs.inputs["Emission Strength"].default_value = 1.0
                if role.get("opacity") is not None and role["opacity"] < 1 and not bs.inputs["Alpha"].is_linked:
                    bs.inputs["Alpha"].default_value = float(role["opacity"])
            if re.search(r"ctx_(canal|water)$", base) and CFG.get("water_override", True):
                for l in list(bs.inputs["Base Color"].links):
                    m.node_tree.links.remove(l)
                c = CFG["water_rgb"]; bs.inputs["Base Color"].default_value = (c[0], c[1], c[2], 1.0)
                bs.inputs["Roughness"].default_value = 0.07; bs.inputs["IOR"].default_value = 1.33
    log("scenery materials: %d, palette values restored on %d" % (len(seen), fixed))


def build():
    sc = setup_render()
    world_and_sun(sc)
    global FAC
    FAC = facade_group()
    root = sc.collection
    ctx = bpy.data.collections.new("context"); root.children.link(ctx)
    sand_plane(ctx)
    D = CFG["datasmith"]
    wm = water_mat()
    for n in ("sea", "inland_water"):
        ue_obj(os.path.join(D, "ground", n + ".obj"), -0.10, wm, ctx)
    look = {"asphalt": ([0.19, 0.19, 0.195], 0.85), "pavement": ([0.58, 0.58, 0.56], 0.9), "parking": ([0.21, 0.21, 0.215], 0.85),
            "grass": ([0.17, 0.34, 0.085], 0.9)}
    for k, (rgb, rough) in look.items():
        ue_obj(os.path.join(D, "bb_v1", "ctx_s_%s.obj" % k), -0.03, principled("ctx3_" + k, rgb, rough, 0.0), ctx)
    ue_obj(os.path.join(D, "bb_v1", "ctx_s_buildings.obj"), -0.03, principled("ctx3_buildings", [0.67, 0.65, 0.61], 0.8, 0.0), ctx)
    log("bb_v1 context OBJs placed")
    # scenery agent layers, lifted to land level
    json_removed = 0; scen = []
    for L in CFG["ctx_layers"]:
        new = import_glb(L["path"])
        for o in new:
            if o.parent is None:
                o.location.z += LIFT
        js = [o for o in new if o.type == "EMPTY" and o.get("klass") == "json"]
        kill = set()
        for e in js:
            kill.add(e); kill.update(e.children_recursive)
        if not CFG.get("film_parity", True):
            kill = set()
        kill_names = {o.name for o in kill}
        scen += [o for o in new if o.name not in kill_names]          # decided before the removal invalidates the RNA handles
        if kill:
            json_removed += sum(1 for o in kill if o.type == "MESH")
            bpy.data.batch_remove(list(kill))
    fix_scenery_materials(scen)
    log("scenery: %d objects kept, %d 'json' instances removed (film parity)" % (len(scen), json_removed))
    # Business Bay towers + landmarks
    towers = import_glb(CFG["towers"], shading="FLAT")
    by_b = {}
    for o in towers:
        if o.parent is None:
            o.location.z += LIFT
        if o.type != "MESH":
            continue
        mm = re.search(r"(?:^|\s)b(\d+)", o.name + " " + (o.parent.name if o.parent else ""))
        idx = int(mm.group(1)) if mm else -1
        by_b.setdefault(idx, []).append(o)
        for s in o.material_slots:
            if s.material:
                s.material = tower_material(idx, re.sub(r"\.\d+$", "", s.material.name), True)
    bpy.context.view_layer.update()
    landmarks(by_b, ctx)
    log("towers: %d buildings, %d materials so far" % (len(by_b), len(MATS)))
    # Downtown backdrop + hero Burj
    if CFG.get("downtown"):
        dt = import_glb(CFG["downtown"], shading="FLAT")
        burj = three_to_bl(CFG["burj"]); hidden = []
        for o in dt:
            if o.parent is None:
                o.location.x -= E0; o.location.y -= N0
        bpy.context.view_layer.update()
        for o in dt:
            if o.type != "MESH":
                continue
            lo, hi = world_bbox([o]); c = (lo + hi) / 2
            if math.hypot(c[0] - burj.x, c[1] - burj.y) < 70.0:
                hidden.append(o); continue
            mm = re.search(r"(?:^|\s)b(\d+)", o.name); idx = int(mm.group(1)) if mm else -1
            src = "lod1_vision" if "glass" in o.name else "lod1_wall"
            for s in o.material_slots:
                s.material = tower_material(idx, src, False)
        if hidden:
            bpy.data.batch_remove(hidden)
        for part, rgb, rough, metal in (("burj_glass", CFG["burj_glass"], 0.08, 0.8), ("burj_band", CFG["burj_band"], 0.3, 0.6), ("burj_spire", CFG["burj_spire"], 0.25, 0.9)):
            ue_obj(os.path.join(D, "bb_v1", part + ".obj"), 0.0, principled(part, rgb, rough, metal), ctx, ox=burj.x, oy=burj.y)
        log("downtown backdrop: %d kept, %d hidden near the Burj; hero Burj placed" % (len(dt) - len(hidden), len(hidden)))


def landmarks(by_b, coll):
    """bb_landmark_crowns (as lab_nounreal_render.landmarkPass): height fixes, construction tops + cranes, crowns"""
    want = {int(k): float(v) for k, v in LMK["height"].items()}
    crowns = {int(k): v for k, v in LMK["crowns"].items()}
    for i, c in crowns.items():
        if c[3]:
            want[i] = float(c[3])
    for i, hk in CONS.items():
        want[i] = hk[0] * hk[1]
    cranes, crown_jobs = [], []
    for bid, parts in by_b.items():
        if bid not in want and bid not in crowns:
            continue
        lo, hi = world_bbox(parts); lo_z, hi_z = lo[2], hi[2]
        if bid in want and hi_z - lo_z > 10:
            k = want[bid] / (hi_z - lo_z)
            S = Matrix.Translation((0, 0, lo_z)) @ Matrix.Diagonal((1, 1, k, 1)) @ Matrix.Translation((0, 0, -lo_z))
            for o in parts:
                o.matrix_world = S @ o.matrix_world
            log("  landmark b%d height %.0f -> %.0f m" % (bid, hi_z - lo_z, want[bid])); hi_z = lo_z + want[bid]
        bpy.context.view_layer.update()
        tb = None
        for o in parts:
            l2, h2 = world_bbox([o])
            if tb is None or h2[2] > tb[1][2]:
                tb = (l2, h2)
        ctr = (tb[0] + tb[1]) / 2; ext = (tb[1] - tb[0]) / 2
        if bid in CONS:
            cranes.append((ctr[0], ctr[1], hi_z, (bid * 37) % 360, bid)); continue
        if bid in crowns:
            kind, ch, mk = crowns[bid][:3]
            w = min(min(ext[0], ext[1]) * 2.0 * 0.92, {"needle": 12.0, "fin_ring": 42.0, "corner_spires": 42.0, "cage": 40.0}.get(kind, 45.0))
            if hi_z - LIFT < 100:
                log("  crown on b%d skipped: roof under 100 m" % bid); continue
            crown_jobs.append((kind, ch, mk, w, ctr[0], ctr[1], hi_z, bid))
    D = CFG["datasmith"]
    for kind, ch, mk, w, x, y, z, bid in crown_jobs:
        ue_obj(os.path.join(D, "bb_v1", "crown_%s.obj" % kind), z, crown_mat(mk), coll, sx=w, sz=ch, ox=x, oy=y)
    if crown_jobs:
        log("  crowns " + " ".join("%s@b%d" % (c[0], c[7]) for c in crown_jobs))
    if cranes and CFG.get("crane"):
        kit = import_glb(CFG["crane"])
        meshes = [o for o in kit if o.type == "MESH"]; roots = [o for o in kit if o.parent is None]
        bpy.context.view_layer.update()
        lo, hi = world_bbox(meshes); k = 70.0 / (hi[2] - lo[2])
        base = bpy.data.objects.new("crane_kit", None); coll.objects.link(base)
        for r_ in roots:
            r_.parent = base
        base.hide_render = True; base.hide_viewport = True
        for o in meshes:
            o.hide_render = True
        for x, y, z, yaw, bid in cranes:                    # linked duplicates of the kit, one per construction top
            for o in meshes:
                d = o.copy(); coll.objects.link(d); d.parent = None; d.hide_render = False
                M = Matrix.Translation((x, y, z - lo[2] * k)) @ Matrix.Rotation(math.radians(yaw), 4, "Z") @ Matrix.Scale(k, 4)
                d.matrix_world = M @ o.matrix_world
        log("  tower cranes on construction tops: " + " ".join("b%d" % c[4] for c in cranes))


def camera(sc, v):
    cam = sc.camera
    if cam is None:
        cd = bpy.data.cameras.new("CAM"); cam = bpy.data.objects.new("CAM", cd); sc.collection.objects.link(cam); sc.camera = cam
        cd.sensor_fit = "VERTICAL"; cd.sensor_height = float(CFG["sensor_h_mm"]); cd.lens = float(CFG["focal_mm"])
    p, t = three_to_bl(v["pos"]), three_to_bl(v["tgt"])
    d = t - p
    cam.location = p; cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    dist = d.length
    cam.data.clip_start = max(0.5, min(40.0, dist * 0.012)); cam.data.clip_end = 120000.0
    return dist


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build()
    sc = bpy.context.scene
    t_build = time.time() - T0
    log("scene built in %.1f s: %d objects, %d meshes, %d materials" % (t_build, len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials)))
    if CFG.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=CFG["save_blend"], compress=True); log("saved " + CFG["save_blend"])
    out = {"build_s": round(t_build, 1), "frames": [], "samples": CFG["samples"], "W": CFG["W"], "H": CFG["H"],
           "sun_strength": CFG["sun_strength"], "sky_strength": CFG["sky_strength"], "hdri_rot_deg": CFG["hdri_rot_deg"]}
    os.makedirs(CFG["exr_dir"], exist_ok=True)
    for i, v in enumerate(CFG["views"]):
        # the 5 GB gate runs before Blender starts (driver); here, with this process's own scene resident, a per-frame floor
        g = wait_turn(float(CFG.get("min_ram_frame", 1.5)), float(CFG.get("max_wait_s", 3600)))
        dist = camera(sc, v)
        if CFG.get("animated_seed"):
            sc.frame_set(i + 1)
        sc.render.filepath = os.path.join(CFG["exr_dir"], v["name"] + ".exr")
        t = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - t
        out["frames"].append({"name": v["name"], "render_s": round(dt, 2), "free_ram_gb": round(g, 1), "cam_dist_m": round(dist, 1)})
        log("%s rendered in %.1f s (free RAM before %.1f GB)" % (v["name"], dt, g))
    out["total_s"] = round(time.time() - T0, 1); out["log"] = LOG
    json.dump(out, open(CFG["timings"], "w"), indent=1)
    log("done")


try:
    main()
except SystemExit as e:
    print("[cycles] EXIT", e, flush=True); sys.exit(2)
except Exception:
    import traceback
    traceback.print_exc(); sys.exit(1)
