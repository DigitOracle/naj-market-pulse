"""CE -> ArcGIS Pro handshake: export a district's generated massing to a File
Geodatabase (multipatch). Pro's 3D Analyst then consumes the SAME features CE
authored — one geometry, two engines.

Usage: python scripts/ce_fgdb.py [slug]     (default: businessbay)
Output: data/pro/najma_<slug>.gdb
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.abspath(os.path.join(HERE, "..", "data", "pro"))
os.makedirs(PRO, exist_ok=True)
slug = sys.argv[1] if len(sys.argv) > 1 else "businessbay"

from cityengine import CE, FGDBExportModelSettings  # noqa: E402

ce = CE()
scene = f"/najma/scenes/{slug}.cej"
ce.openFile(scene)
time.sleep(2)
shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
print(f"{slug}: {len(shapes)} shapes in scene")
if not shapes:
    sys.exit("no shapes — run ce_batch.py first")

ce.generateModels(shapes)
s = FGDBExportModelSettings()
s.setOutputPath(PRO)
s.setGeodatabaseName(f"najma_{slug}")
s.setExportFeatures(FGDBExportModelSettings.MODELS)
s.setExportObjectAttributes(True)
s.setEmitReports(True)
ce.export(shapes, s)
gdb = os.path.join(PRO, f"najma_{slug}.gdb")
for _ in range(30):
    if os.path.isdir(gdb):
        break
    time.sleep(1)
print("exported:", gdb, "| exists:", os.path.isdir(gdb))
