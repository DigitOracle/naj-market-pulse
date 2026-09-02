"""ArcGIS Pro reads the Revit model: BIM file workspace -> BIM File To Geodatabase (rooms + all DA_ attributes).

Positioning: Revit's internal origin is the plate centre; a .wld3 world file maps local (0,0) -> site anchor
(UTM 40N) with the plate bearing. Units are auto-detected (Revit reads in project units; we try metres, then mm).
Run with propy.bat. Output: data/pro/najma_symphony_bim.gdb/Symphony (feature dataset) + report.
"""
import math, os, shutil, sys
import arcpy

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.abspath(os.path.join(HERE, "..", "data", "pro"))
BIM = os.path.join(PRO, "bim")
os.makedirs(BIM, exist_ok=True)
SRC = os.path.abspath(os.path.join(HERE, "..", "data", "revit", "TheSymphony_by_Imtiaz_MeydanHorizon.rvt"))
RVT = os.path.join(BIM, "TheSymphony_by_Imtiaz_MeydanHorizon.rvt")
shutil.copy2(SRC, RVT)
print("rvt copy:", RVT, round(os.path.getsize(RVT) / 1e6, 1), "MB")

SR = arcpy.SpatialReference(32640)
E, N = 329478.0, 2784621.0           # site anchor, UTM 40N (25.168N 55.308E)
BEARING = -40.0                       # clockwise 40 deg, as in golden_footprint.py
th = math.radians(BEARING)


def wld3(scale):
    """Three-point world file in the BIM file's own units (scale = 1 for m, 1000 for mm)."""
    pts = [(0, 0), (10 * scale, 0), (0, 10 * scale)]
    lines = []
    for x, y in pts:
        xm, ym = x / scale, y / scale
        X = E + xm * math.cos(th) - ym * math.sin(th)
        Y = N + xm * math.sin(th) + ym * math.cos(th)
        lines.append("%s,%s,0 %.3f,%.3f,0" % (x, y, X, Y))
    with open(RVT[:-4] + ".wld3", "w") as f:
        f.write("\n".join(lines) + "\n")


arcpy.env.overwriteOutput = True
GDB = os.path.join(PRO, "najma_symphony_bim.gdb")
if not arcpy.Exists(GDB):
    arcpy.management.CreateFileGDB(PRO, "najma_symphony_bim")


def convert():
    open(RVT[:-4] + ".prj", "w").write(SR.exportToString())   # BIM workspace reads a .prj sidecar
    ds = os.path.join(GDB, "Symphony")
    if arcpy.Exists(ds):
        arcpy.management.Delete(ds)
    arcpy.conversion.BIMFileToGeodatabase(RVT, GDB, "Symphony", SR, "", "INCLUDE_FLOORPLAN")
    return ds


for scale in (1, 1000):
    wld3(scale)
    ds = convert()
    arcpy.env.workspace = ds
    fcs = arcpy.ListFeatureClasses() or []
    rooms_fc = next((f for f in fcs if f.lower().startswith("rooms")), None)
    if not rooms_fc:
        print("no Rooms feature class; classes:", fcs)
        break
    ext = arcpy.Describe(rooms_fc).extent
    cx, cy = (ext.XMin + ext.XMax) / 2, (ext.YMin + ext.YMax) / 2
    off = math.hypot(cx - E, cy - N)
    print("scale %d -> rooms centre offset from anchor %.1f m, width %.1f m" % (scale, off, ext.XMax - ext.XMin))
    if off < 200 and 30 < (ext.XMax - ext.XMin) < 80:
        break

print("\nfeature classes in", ds)
for f in fcs:
    n = int(arcpy.management.GetCount(f)[0])
    print("  %-28s %6d  %s" % (f, n, arcpy.Describe(f).shapeType))
fields = [fl.name for fl in arcpy.ListFields(rooms_fc)]
da = [f for f in fields if f.startswith("DA_")]
print("\nRooms fields:", len(fields), "| DA_ classification fields carried:", da)
keep = ["RoomNumber", "RoomName", "Level", "BldgLevel", "Department"] + da
keep = [k for k in keep if k in fields]
print("sample rooms:")
with arcpy.da.SearchCursor(rooms_fc, keep, where_clause="RoomNumber LIKE '3307-%'") as cur:
    for i, row in enumerate(cur):
        if i >= 5:
            break
        print("  ", dict(zip(keep, [str(v)[:40] for v in row])))
