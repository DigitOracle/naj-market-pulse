"""Golden Building CE build: footprint SHP -> golden.cga -> generate ->
FGDB (for Pro) + GLB + snapshot. Single-building lane; CE must be running.

Usage: python scripts/golden_build.py
"""
import os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CEDIR = os.path.join(HERE, "..", "data", "ce", "goldensymphony")
PRO = os.path.abspath(os.path.join(HERE, "..", "data", "pro"))
GLB = os.path.join(HERE, "..", "data", "ce", "_glb")
os.makedirs(PRO, exist_ok=True)

from cityengine import CE, FGDBExportModelSettings, GLTFExportModelSettings  # noqa: E402

ce = CE()
ws = ce.toFSPath("/")
proj = os.path.join(ws, "najma")

shutil.copy2(os.path.join(HERE, "..", "rules", "golden.cga"),
             os.path.join(proj, "rules", "golden.cga"))
for f in os.listdir(CEDIR):
    if f.startswith("buildings.") and not f.endswith(".geojson"):
        shutil.copy2(os.path.join(CEDIR, f), os.path.join(proj, "data", f"goldensymphony_{f}"))
try:
    ce.refreshWorkspace()
except Exception:
    pass

ce.newFile("/najma/scenes/goldensymphony.cej")
ce.importFile(ce.toFSPath("/najma/data/goldensymphony_buildings.shp"))
shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
print("shapes:", len(shapes))
if not shapes:
    sys.exit("no shapes imported")

ce.setRuleFile(shapes, "/najma/rules/golden.cga")
ce.setStartRule(shapes, "Lot")
for attr in ("bHeight", "status"):
    try:
        ce.setAttributeSource(shapes, "/ce/rule/" + attr, "OBJECT")
    except Exception:
        pass
ce.generateModels(shapes)
print("generated")

fg = FGDBExportModelSettings()
fg.setOutputPath(PRO)
fg.setGeodatabaseName("najma_goldensymphony")
fg.setExportFeatures(FGDBExportModelSettings.MODELS)
fg.setExportObjectAttributes(True)
ce.export(shapes, fg)
print("FGDB:", os.path.isdir(os.path.join(PRO, "najma_goldensymphony.gdb")))

g = GLTFExportModelSettings()
g.setOutputPath(os.path.abspath(GLB))
g.setBaseName("sky_goldensymphony")
ce.export(shapes, g)

time.sleep(1)
try:
    v = ce.get3DViews()[0]
    ce.setSelection([])
    v.frame(shapes)
    time.sleep(1)
    v.snapshot(os.path.join(os.path.abspath(GLB), "snap_goldensymphony.png"), 1600, 1000)
    print("snapshot written")
except Exception as e:
    print("snapshot:", str(e)[:80])
