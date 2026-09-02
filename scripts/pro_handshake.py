"""Pro side of the CE<->Pro handshake: open the CE-authored FGDB with arcpy,
enumerate feature classes, count features, report spatial reference + z extent.
Run with propy.bat.
"""
import os, sys
import arcpy

HERE = os.path.dirname(os.path.abspath(__file__))
gdb = os.path.abspath(os.path.join(HERE, "..", "data", "pro", "najma_businessbay.gdb"))
if not os.path.isdir(gdb):
    sys.exit("FGDB missing: " + gdb)

arcpy.env.workspace = gdb
print("FGDB:", gdb)
for ds in [""] + (arcpy.ListDatasets() or []):
    fcs = arcpy.ListFeatureClasses(feature_dataset=ds or None) or []
    for fc in fcs:
        d = arcpy.Describe((ds + "/" if ds else "") + fc)
        n = int(arcpy.management.GetCount(d.catalogPath)[0])
        sr = d.spatialReference
        ext = d.extent
        print(f"  {ds + '/' if ds else ''}{fc}: {d.shapeType}, {n} features, "
              f"SR={sr.name} ({sr.factoryCode}), z {ext.ZMin:.1f}..{ext.ZMax:.1f}"
              if d.hasZ else
              f"  {ds + '/' if ds else ''}{fc}: {d.shapeType}, {n} features, SR={sr.name}")
tabs = arcpy.ListTables() or []
print("tables:", tabs)
print("HANDSHAKE OK — Pro is reading CityEngine's geodatabase")
