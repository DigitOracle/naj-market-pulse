"""Site the BIM-derived 2D classes (floor-plan polygons, polylines, points of interest) at the Meydan Horizon anchor.
The BIM workspace ignored the .wld3, so rooms came in at the model origin. Transform Features (similarity) with two
control links: origin->anchor and +10 m east->rotated. Multipatch classes are left at origin (Transform does not take
multipatch); the sited 2D set is what joins/Azimuth need. Run with propy.bat.
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
arcpy.env.overwriteOutput = True

# control links (from model space -> site)
links = os.path.join(GDB, "site_links")
arcpy.management.CreateFeatureclass(GDB, "site_links", "POLYLINE", spatial_reference=SR)
with arcpy.da.InsertCursor(links, ["SHAPE@"]) as cur:
    for x, y in ((0, 0), (10, 0), (0, 10)):
        X = E + x * math.cos(TH) - y * math.sin(TH); Y = N + x * math.sin(TH) + y * math.cos(TH)
        cur.insertRow([arcpy.Polyline(arcpy.Array([arcpy.Point(x, y), arcpy.Point(X, Y)]), SR)])

out_ds = os.path.join(GDB, "Symphony_Sited")
if not arcpy.Exists(out_ds):
    arcpy.management.CreateFeatureDataset(GDB, "Symphony_Sited", SR)
arcpy.env.workspace = SRC
done = []
for fc in ("Floorplan_Polygon_Symphony", "Floorplan_Polyline_Symphony", "PointsOfInterest_Symphony", "Doors_Symphony", "Windows_Symphony"):
    if not arcpy.Exists(fc):
        continue
    if arcpy.Describe(fc).shapeType == "MultiPatch":
        # doors/windows: use their footprints via points of interest instead
        continue
    out = os.path.join(out_ds, fc.replace("_Symphony", "_Sited"))
    arcpy.management.CopyFeatures(fc, out)
    arcpy.edit.TransformFeatures(out, links, "SIMILARITY")
    e = arcpy.Describe(out).extent
    done.append((os.path.basename(out), int(arcpy.management.GetCount(out)[0]), round((e.XMin + e.XMax) / 2), round((e.YMin + e.YMax) / 2)))
for row in done:
    print("  %-28s %6d  centre %d,%d" % row)
print("anchor 329478,2784621 -> sited classes ready in", out_ds)
