"""Batch the CityEngine pipeline over every community that has an OSM export:
scene → import → rule → generate → GLB export → snapshot. Run ce_export.py first
per area (Overpass fetch); CE must be running with the bridge up.

Usage:  python scripts/ce_batch.py            # all areas with data/ce/<slug>/buildings.shp
Output: data/ce/_glb/sky_<slug>.glb + snapshots — then push_assets.py --skylines
"""
import os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CEDIR = os.path.join(HERE, "..", "data", "ce")
GLB = os.path.join(CEDIR, "_glb")

from cityengine import CE, GLTFExportModelSettings  # noqa: E402

ce = CE()
ws = ce.toFSPath("/")
proj = os.path.join(ws, "najma")
os.makedirs(GLB, exist_ok=True)

areas = [d for d in sorted(os.listdir(CEDIR))
         if os.path.exists(os.path.join(CEDIR, d, "buildings.shp"))]
print("areas with footprints:", areas)

for a in areas:
    if os.path.exists(os.path.join(GLB, f"sky_{a}_0.glb")):
        print(f"SKIP {a} (GLB exists)"); continue
    print(f"=== {a}", flush=True)
    for f in os.listdir(os.path.join(CEDIR, a)):
        if f.startswith("buildings.") and not f.endswith(".geojson"):
            shutil.copy2(os.path.join(CEDIR, a, f), os.path.join(proj, "data", f"{a}_{f}"))
    try:
        ce.refreshWorkspace()
    except Exception:
        pass
    try:
        ce.newFile(f"/najma/scenes/{a}.cej")
    except Exception as e:
        print("  newFile:", str(e).splitlines()[0][:80]); continue
    try:
        ce.importFile(ce.toFSPath(f"/najma/data/{a}_buildings.shp"))
    except Exception as e:
        print("  import:", str(e).splitlines()[0][:80]); continue
    shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
    print("  shapes:", len(shapes))
    if not shapes:
        continue
    ce.setRuleFile(shapes, "/najma/rules/najma.cga")
    ce.setStartRule(shapes, "Lot")
    for attr in ("bHeight", "status"):
        try:
            ce.setAttributeSource(shapes, "/ce/rule/" + attr, "OBJECT")
        except Exception:
            pass
    ce.generateModels(shapes)
    s = GLTFExportModelSettings()
    s.setOutputPath(GLB)
    s.setBaseName("sky_" + a)
    ce.export(shapes, s)
    time.sleep(1)
    try:
        v = ce.get3DViews()[0]
        ce.setSelection([])
        v.frame(shapes)
        time.sleep(1)
        v.snapshot(os.path.join(GLB, f"snap_{a}.png"), 1600, 1000)
    except Exception as e:
        print("  snapshot:", str(e)[:60])
    try:
        ce.saveFile(f"/najma/scenes/{a}.cej")
    except Exception:
        pass
    print("  done")

print("\nGLBs:")
for f in sorted(os.listdir(GLB)):
    if f.endswith(".glb"):
        sz = os.path.getsize(os.path.join(GLB, f))
        print(" ", f, sz // 1024, "KB", "⚠️ OVER 5MB KV CAP" if sz > 5*1024*1024 else "")
print("next: python scripts/push_assets.py --skylines")
