"""LAB (no-Unreal, research only): convert the two FBX-only kits the Unreal Business Bay v1 build places - the tower crane
(ue_bb_v0_build KITS["crane"], on the construction landmarks' roofs) and the cafe parasol (ue_bb_v1_build K["umbrella"]) -
to GLB for the three.js renderer, with Blender 5.1 in background mode (no UI, factory settings).

Sources (read-only): C:/Dev/assets/sketchfab_construction/liebherr-tower-crane/source/Crane001.fbx (+ textures/),
                     C:/Dev/assets/sketchfab_pool_outdoor/floating-parasol-sunshade-patio-umbrella/.../source/Parasol.zip
Out: data/lab/no_unreal/kits/{tower_crane,parasol}.glb (+ _src/ for the unzipped FBX). Credits: each source's CREDIT.txt
(CC BY 4.0 per the asset audit) - research use only.
  python scripts/lab_nounreal_kits.py
"""
import io
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
KITS = os.path.join(ROOT, "data", "lab", "no_unreal", "kits")
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
A = "C:/Dev/assets"

BPY = r"""
import bpy, sys, os
src, dst, texdir = sys.argv[sys.argv.index('--') + 1:][:3]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
# relink image textures by file name from the kit's textures/ folder (Sketchfab FBX paths point at the author's disk)
for img in bpy.data.images:
    nm = os.path.basename(img.filepath.replace('\\', '/'))
    cand = os.path.join(texdir, nm)
    if nm and os.path.exists(cand):
        img.filepath = cand
# Sketchfab crane: one 'DefaultMaterial' with albedo / metallic / roughness / normal maps - wire them if the FBX left them empty
if texdir and os.path.isdir(texdir):
    files = {f.lower(): os.path.join(texdir, f) for f in os.listdir(texdir)}
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf or bsdf.inputs['Base Color'].is_linked:
            continue
        key = m.name.lower()
        alb = next((p for f, p in files.items() if key in f and ('albedo' in f or 'basecolor' in f)), None)
        if alb:
            t = m.node_tree.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(alb)
            m.node_tree.links.new(t.outputs['Color'], bsdf.inputs['Base Color'])
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_apply=True, export_yup=True, export_image_format='JPEG')
print('KIT_OK', dst, len(bpy.data.objects), 'objects', len(bpy.data.materials), 'materials')
"""


def run(src, dst, texdir):
    script = os.path.join(KITS, "_src", "_convert.py")
    open(script, "w", encoding="utf-8").write(BPY)
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", script, "--", src, dst, texdir], capture_output=True, text=True, timeout=600)
    ok = [l for l in r.stdout.splitlines() if l.startswith("KIT_OK")]
    print(ok[0] if ok else ("FAILED %s\n%s" % (dst, (r.stdout + r.stderr)[-1500:])))


def main():
    os.makedirs(os.path.join(KITS, "_src"), exist_ok=True)
    crane = A + "/sketchfab_construction/liebherr-tower-crane"
    run(crane + "/source/Crane001.fbx", os.path.join(KITS, "tower_crane.glb"), crane + "/textures")
    shutil.copy(crane + "/CREDIT.txt", os.path.join(KITS, "tower_crane_CREDIT.txt"))
    par = A + "/sketchfab_pool_outdoor/floating-parasol-sunshade-patio-umbrella"
    outer = zipfile.ZipFile(par + "/floating-parasol-sunshade-patio-umbrella.zip")
    inner = zipfile.ZipFile(io.BytesIO(outer.read("source/Parasol.zip")))
    d = os.path.join(KITS, "_src", "parasol"); os.makedirs(d, exist_ok=True)
    inner.extractall(d)
    for n in outer.namelist():
        if n.startswith("textures/") and n.endswith(".png"):
            p = os.path.join(d, os.path.basename(n))
            if not os.path.exists(p):
                open(p, "wb").write(outer.read(n))
    run(os.path.join(d, "Parasol.fbx"), os.path.join(KITS, "parasol.glb"), d)
    shutil.copy(par + "/CREDIT.txt", os.path.join(KITS, "parasol_CREDIT.txt"))


if __name__ == "__main__":
    main()
