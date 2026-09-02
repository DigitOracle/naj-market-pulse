"""Add the Golden Building layers to the GoldenBuilding Pro scene and save the project (run with propy.bat, Pro CLOSED).
Layers: OSM 3D buildings (context), CityEngine massing multipatch (najma_goldensymphony_v2.gdb), BIM rooms multipatch +
floor-plan polygons from BIM To Geodatabase (najma_symphony_bim.gdb/Symphony). Rooms get a level definition so the
Pro floor filter works and popups show unit / room / classification fields (tap-a-room on the map).
"""
import os, sys
import arcpy
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.abspath(os.path.join(HERE, "..", "data", "pro"))
APRX = r"C:\Users\kwils\OneDrive\Documents\ArcGIS\Projects\GoldenBuilding\GoldenBuilding.aprx"
BIM = os.path.join(PRO, "najma_symphony_bim.gdb", "Symphony")
CE = os.path.join(PRO, "najma_goldensymphony_v2.gdb", "Shapesgoldensymphony_buildings_ProcedurallyGeneratedMultipatches")
OSM3D = "https://basemaps3d.arcgis.com/arcgis/rest/services/OpenStreetMap3D_Buildings_v1/SceneServer"
WANT = [("OSM 3D Buildings", OSM3D), ("Symphony massing (CityEngine)", CE),
        ("Symphony rooms (Revit)", os.path.join(BIM, "Rooms_Symphony")),
        ("Symphony floor plans (Revit)", os.path.join(BIM, "Floorplan_Polygon_Symphony")),
        ("Symphony shell (Revit)", os.path.join(BIM, "ExteriorShell_Symphony"))]

ap = arcpy.mp.ArcGISProject(APRX)
m = next(x for x in ap.listMaps() if x.mapType == "SCENE")
have = {l.name for l in m.listLayers()}
for name, src in WANT:
    if name in have:
        print("kept   ", name); continue
    try:
        lyr = m.addDataFromPath(src)
        lyr.name = name
        print("added  ", name, "<-", src)
    except Exception as e:
        print("FAILED ", name, str(e)[:120])
# popups / visibility: rooms visible, walls not added (rooms are the tappable layer); plans off by default
for l in m.listLayers():
    if l.name == "Symphony floor plans (Revit)":
        l.visible = False
ap.save()
print("saved", APRX)
print("scene layers now:", [l.name for l in m.listLayers()])
