"""DEPRECATED (2 Sep 2026): TransformFeatures on the converted multipatches corrupted the geometry (plate width -> 329 km).
Position the model with Revit shared coordinates instead (ActiveProjectLocation.SetProjectPosition) and re-run pro_bim_import.py.
Kept for the record only.
"Position the converted Revit geodatabase at the site: affine transform (translate + rotate) of every feature class in
najma_symphony_bim.gdb/Symphony from Revit local metres (origin = plate centre, y = project north) to UTM 40N.
BIM File To Geodatabase ignored the .wld3 sidecar, so this is the deterministic step. Run with propy.bat.
Verifies afterwards: Rooms centre must sit within 50 m of the anchor.
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
DS = os.path.join(GDB, "Symphony")
E, N, BEARING = 329478.0, 2784621.0, -40.0          # site anchor (UTM 40N) and plate rotation (clockwise 40 deg)
SR = arcpy.SpatialReference(32640)
th = math.radians(BEARING)

arcpy.env.overwriteOutput = True
arcpy.env.workspace = DS
fcs = [f for f in (arcpy.ListFeatureClasses() or []) if int(arcpy.management.GetCount(f)[0]) > 0]
print("feature classes to position:", fcs)

# displacement links: three local points -> site points (affine needs >= 3 non-collinear links)
links = os.path.join(GDB, "site_links")
if arcpy.Exists(links):
    arcpy.management.Delete(links)
arcpy.management.CreateFeatureclass(GDB, "site_links", "POLYLINE", spatial_reference=SR)
with arcpy.da.InsertCursor(links, ["SHAPE@"]) as cur:
    for lx, ly in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0)):
        X = E + lx * math.cos(th) - ly * math.sin(th)
        Y = N + lx * math.sin(th) + ly * math.cos(th)
        cur.insertRow([arcpy.Polyline(arcpy.Array([arcpy.Point(lx, ly), arcpy.Point(X, Y)]), SR)])

# sanity: are the features already at the site? (re-run protection)
ext = arcpy.Describe(os.path.join(DS, "Rooms_Symphony")).extent
cx, cy = (ext.XMin + ext.XMax) / 2, (ext.YMin + ext.YMax) / 2
if math.hypot(cx - E, cy - N) < 100:
    sys.exit("already positioned (rooms centre %.1f m from anchor)" % math.hypot(cx - E, cy - N))

for f in fcs:
    arcpy.edit.TransformFeatures(os.path.join(DS, f), links, "AFFINE")
    print("  transformed", f)

ext = arcpy.Describe(os.path.join(DS, "Rooms_Symphony")).extent
cx, cy = (ext.XMin + ext.XMax) / 2, (ext.YMin + ext.YMax) / 2
print("rooms centre offset from anchor: %.1f m | plate width %.1f m | z %.1f..%.1f" % (math.hypot(cx - E, cy - N), ext.XMax - ext.XMin, ext.ZMin or 0, ext.ZMax or 0))
flds = [x.name for x in arcpy.ListFields("Rooms_Symphony")]
show = [c for c in ("RoomNumber", "Number", "RoomName", "Name", "Level", "BldgLevel", "Department", "Area", "DA_UniclassSl") if c in flds]
print("rooms fields sample:", show)
with arcpy.da.SearchCursor("Rooms_Symphony", show) as cur:
    for i, row in enumerate(cur):
        if i >= 3:
            break
        print("  ", dict(zip(show, [str(v)[:36] for v in row])))
