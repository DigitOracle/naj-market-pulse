"""Point the GoldenBuilding scene camera at The Symphony and save (run with propy.bat while Pro is CLOSED)."""
import arcpy, sys
APRX = r"C:\Users\kwils\OneDrive\Documents\ArcGIS\Projects\GoldenBuilding\GoldenBuilding.aprx"
ap = arcpy.mp.ArcGISProject(APRX)
m = next(x for x in ap.listMaps() if x.mapType == "SCENE")
sr = arcpy.SpatialReference(32640)
E, N = 329478.0, 2784621.0
ext = arcpy.Extent(E - 120, N - 120, E + 120, N + 120, spatial_reference=sr)
cam = m.defaultCamera
cam.setExtent(ext)
cam.pitch = -35
cam.heading = 320
m.defaultCamera = cam
lyr = next((l for l in m.listLayers() if l.name == "Symphony rooms (Revit)"), None)
if lyr is not None:
    lyr.visible = True
ap.save()
print("camera set; heading %.0f pitch %.0f; layers %s" % (cam.heading, cam.pitch, [l.name for l in m.listLayers()][:5]))
