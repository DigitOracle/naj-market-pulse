"""Site the BIM-derived 2D classes (floor-plan polygons, polylines, points of interest) at the Meydan Horizon anchor.
The BIM workspace ignored the .wld3 and TransformFeatures halved the shift, so this applies the similarity transform
directly to the geometry: rotate by the plate bearing, translate to the anchor. Multipatch classes stay at origin.
Run with propy.bat.
"""
import math, os, sys
import arcpy
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.abspath(os.path.join(HERE, "..", "data", "pro"))
GDB = os.path.join(PRO, "najma_symphony_bim.gdb")
SRC = os.path.join(GDB, "Symphony")
SR = arcpy.SpatialReference(32640)
E, N, TH = 329478.0, 2784621.0, math.radians(-40.0)
C, S = math.cos(TH), math.sin(TH)
arcpy.env.overwriteOutput = True


def xf(x, y):
    return E + x * C - y * S, N + x * S + y * C


def move(geom):
    t = geom.type
    if t == "point":
        p = geom.firstPoint; X, Y = xf(p.X, p.Y); return arcpy.PointGeometry(arcpy.Point(X, Y, p.Z), SR)
    parts = arcpy.Array()
    for part in geom:
        arr = arcpy.Array()
        for p in part:
            if p is None:
                arr.add(None); continue
            X, Y = xf(p.X, p.Y); arr.add(arcpy.Point(X, Y, p.Z))
        parts.add(arr)
    return arcpy.Polygon(parts, SR) if t == "polygon" else arcpy.Polyline(parts, SR)


out_ds = os.path.join(GDB, "Symphony_Sited")
if arcpy.Exists(out_ds):
    arcpy.management.Delete(out_ds)
arcpy.management.CreateFeatureDataset(GDB, "Symphony_Sited", SR)
arcpy.env.workspace = SRC
for fc in ("Floorplan_Polygon_Symphony", "Floorplan_Polyline_Symphony", "PointsOfInterest_Symphony"):
    out = os.path.join(out_ds, fc.replace("_Symphony", "_Sited"))
    arcpy.management.CopyFeatures(fc, out)
    n = 0
    with arcpy.da.UpdateCursor(out, ["SHAPE@"]) as cur:
        for row in cur:
            if row[0] is None:
                continue
            cur.updateRow([move(row[0])]); n += 1
    e = arcpy.Describe(out).extent
    print("  %-26s %5d moved  centre %.0f,%.0f  width %.1f m" % (os.path.basename(out), n, (e.XMin + e.XMax) / 2, (e.YMin + e.YMax) / 2, e.XMax - e.XMin))
print("anchor 329478,2784621")
# quick attribute proof on the sited rooms
fc = os.path.join(out_ds, "Floorplan_Polygon_Sited")
flds = [f.name for f in arcpy.ListFields(fc)]
show = [f for f in ("RoomNumber", "RoomName", "Level", "Department", "DA_UniclassSl", "DA_OmniClassT11") if f in flds]
with arcpy.da.SearchCursor(fc, show, where_clause="RoomNumber LIKE '3307-%'") as cur:
    for i, r in enumerate(cur):
        if i >= 4:
            break
        print("  ", dict(zip(show, [str(v)[:34] for v in r])))
