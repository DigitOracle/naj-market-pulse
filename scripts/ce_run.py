"""Drive CityEngine end-to-end for a Najma community: project setup, SHP import,
rule assignment, generate, frame, snapshot. Requires CE 2025.1 running with the
external Python bridge listening on 25333 (see reference notes: z = -northing).

Usage: python scripts/ce_run.py --area businessbay
Output: <scratch>/ce_<slug>.png snapshot + scene saved in workspace project /najma
"""
import os, shutil, sys, time

AREA = sys.argv[sys.argv.index("--area") + 1] if "--area" in sys.argv else "businessbay"
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ce", AREA)
SNAP = os.path.join(os.environ.get("TEMP", r"C:\Temp"), f"ce_{AREA}.png")

from cityengine import CE  # noqa: E402

ce = CE()
print("connected to CityEngine")

ws = ce.toFSPath("/")
print("workspace:", ws)
# CE's workspace is an Eclipse workspace: a folder is invisible until it is a PROJECT.
# No newProject in this API — write an Eclipse .project descriptor and importProject it.
proj = os.path.join(ws, "najma")
for sub in ("data", "rules", "scenes"):
    os.makedirs(os.path.join(proj, sub), exist_ok=True)
desc = os.path.join(proj, ".project")
if not os.path.exists(desc):
    open(desc, "w").write('<?xml version="1.0" encoding="UTF-8"?>\n'
        "<projectDescription><name>najma</name><comment></comment><projects></projects>"
        "<buildSpec></buildSpec><natures></natures></projectDescription>\n")
try:
    if "najma" not in [str(x) for x in ce.listProjects()]:
        ce.importProject(proj)
        print("project imported: /najma")
    else:
        print("project already in workspace")
except Exception as e:
    print("importProject:", str(e).splitlines()[0][:120])
print("projects:", [str(x) for x in ce.listProjects()])

for f in os.listdir(SRC):
    if f.startswith("buildings.") and not f.endswith((".geojson",)):
        shutil.copy2(os.path.join(SRC, f), os.path.join(proj, "data", f))
shutil.copy2(os.path.join(SRC, "najma.cga"), os.path.join(proj, "rules", "najma.cga"))
try:
    ce.refreshWorkspace()
except Exception as e:
    print("refreshWorkspace:", e)

scene_ws = f"/najma/scenes/{AREA}.cej"
try:
    ce.newFile(scene_ws)
    print("scene created:", scene_ws)
except Exception as e:
    print("newFile failed (%s) — using current scene" % e)

shp = "/najma/data/buildings.shp"
try:
    ce.importFile(ce.toFSPath(shp))
except Exception:
    ce.importFile(shp)
print("imported", shp)
time.sleep(2)

shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
print("shapes in scene:", len(shapes))
if not shapes:
    sys.exit("import produced no shapes — check SHP")

ce.setRuleFile(shapes, "/najma/rules/najma.cga")
ce.setStartRule(shapes, "Lot")
for attr in ("bHeight", "status"):
    try:
        ce.setAttributeSource(shapes, "/ce/rule/" + attr, "OBJECT")
    except Exception as e:
        print("attr source", attr, ":", e)
print("rule assigned; generating…")
ce.generateModels(shapes)
print("generated")

try:
    ce.waitForUIIdle()
except Exception:
    time.sleep(3)
views = ce.get3DViews()
if not views:
    sys.exit("no 3D view open")
v = views[0]
ce.setSelection([])
v.frame(shapes)
try:
    ce.waitForUIIdle()
except Exception:
    time.sleep(2)
try:
    v.snapshot(SNAP, 1600, 1000)
except TypeError:
    v.snapshot(SNAP)
print("snapshot ->", SNAP)
try:
    ce.saveFile(scene_ws)
except Exception as e:
    print("save:", e)
print("DONE")
