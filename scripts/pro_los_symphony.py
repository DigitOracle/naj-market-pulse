"""POC: ArcGIS Pro 3D Analyst Line Of Sight vs the developer's claimed unit views.

Observer: Imtiaz Symphony Tower site, Meydan Horizon / Bukadra (site-level
coordinate — no surveyed footprint exists yet; construction started Nov 2025).
Targets per unit floor: Downtown skyline (Burj Khalifa, pulled back 150 m so the
tower's own massing can't self-obstruct the target) at two heights, and the
Ras Al Khor lagoon surface. Obstructions: CityEngine-authored multipatch massing
for Sobha Hartland + Downtown + Meydan One (5,160 buildings) over a flat TIN.

Run with propy.bat. Output: data/pro/symphony_los.json + console verdicts.
"""
import json, math, os
import arcpy

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.abspath(os.path.join(HERE, "..", "data", "pro"))
GDBS = ["najma_sobhaheartland.gdb", "najma_burjkhalifa.gdb", "najma_meydanone.gdb"]
SR = arcpy.SpatialReference(32640)
WGS = arcpy.SpatialReference(4326)

OBS = (55.308, 25.168)          # Meydan Horizon / Bukadra site centre (site-level)
BURJ = (55.27414, 25.19717)
LAGOON = (55.320, 25.185)       # Ras Al Khor sanctuary water
FLOOR_H = 3.5
UNITS = {"1907": (19, "Cityscape"), "2410": (24, "Boulevard"), "2810": (28, "Boulevard"),
         "2902": (29, "Pool & Boulevard"), "3107": (31, "Cityscape"),
         "3307": (33, "Skyline, Lagoon & Cityscape"), "OFFICE-305": (3, "Cityscape"),
         "OFFICE-401": (4, "Boulevard"), "OFFICE-P406": (4, "Boulevard"),
         "OFFICE-504": (5, "Skyline, Lagoon & Cityscape")}


def utm(lon, lat):
    p = arcpy.PointGeometry(arcpy.Point(lon, lat), WGS).projectAs(SR).firstPoint
    return p.X, p.Y


arcpy.CheckOutExtension("3D")
arcpy.env.overwriteOutput = True
work = os.path.join(PRO, "los_work.gdb")
if not arcpy.Exists(work):
    arcpy.management.CreateFileGDB(PRO, "los_work")

# merge every multipatch FC from the district FGDBs
srcs = []
for g in GDBS:
    arcpy.env.workspace = os.path.join(PRO, g)
    for fc in arcpy.ListFeatureClasses() or []:
        if arcpy.Describe(fc).shapeType == "MultiPatch":
            srcs.append(os.path.join(PRO, g, fc))
blockers = os.path.join(work, "blockers")
arcpy.management.Merge(srcs, blockers)
print("blockers:", arcpy.management.GetCount(blockers)[0], "multipatch features from", len(srcs), "FCs")

ox, oy = utm(*OBS)
bx, by = utm(*BURJ)
lx, ly = utm(*LAGOON)
# pull skyline target 150 m back toward the observer
d = math.hypot(bx - ox, by - oy)
bx2, by2 = bx + (ox - bx) / d * 150, by + (oy - by) / d * 150
print(f"observer UTM ({ox:.0f},{oy:.0f}) · Burj {d/1000:.2f} km · lagoon {math.hypot(lx-ox,ly-oy)/1000:.2f} km")

# flat ground TIN over the corridor
pad = 1500
xs = [ox, bx, lx]; ys = [oy, by, ly]
pts = os.path.join(work, "tin_pts")
arcpy.management.CreateFeatureclass(work, "tin_pts", "POINT", has_z="ENABLED", spatial_reference=SR)
with arcpy.da.InsertCursor(pts, ["SHAPE@"]) as c:
    for X in (min(xs) - pad, max(xs) + pad):
        for Y in (min(ys) - pad, max(ys) + pad):
            c.insertRow([arcpy.Point(X, Y, 0.0)])
tin = os.path.join(PRO, "ground_tin")
arcpy.ddd.CreateTin(tin, SR, [[pts, "Shape.Z", "Mass_Points", ""]])

# sight lines: unit floor -> each target
targets = {"SKYLINE_HI": (bx2, by2, 550.0), "SKYLINE_MID": (bx2, by2, 250.0), "LAGOON": (lx, ly, 2.0)}
lines = os.path.join(work, "sight")
arcpy.management.CreateFeatureclass(work, "sight", "POLYLINE", has_z="ENABLED", spatial_reference=SR)
arcpy.management.AddField(lines, "unit", "TEXT", field_length=20)
arcpy.management.AddField(lines, "target", "TEXT", field_length=20)
oid_map = {}
with arcpy.da.InsertCursor(lines, ["SHAPE@", "unit", "target"]) as c:
    for u, (fl, _) in UNITS.items():
        hz = fl * FLOOR_H + 1.5
        for tname, (tx, ty, tz) in targets.items():
            arr = arcpy.Array([arcpy.Point(ox, oy, hz), arcpy.Point(tx, ty, tz)])
            c.insertRow([arcpy.Polyline(arr, SR, True), u, tname])
with arcpy.da.SearchCursor(lines, ["OID@", "unit", "target"]) as c:
    for oid, u, t in c:
        oid_map[oid] = (u, t)

los = os.path.join(work, "los_out")
obst = os.path.join(work, "los_obstr")
arcpy.ddd.LineOfSight(tin, lines, los, obst, in_features=blockers)

res = {}
with arcpy.da.SearchCursor(los, ["SourceOID", "TarIsVis"]) as c:
    for src, vis in c:
        u, t = oid_map[src]
        res.setdefault(u, {})[t] = int(vis)

out = {"observer": "Imtiaz Symphony Tower, Meydan Horizon/Bukadra (site-level coord 25.168N 55.308E)",
       "engine": "ArcGIS Pro 3.7 3D Analyst LineOfSight",
       "blockers": "CE massing: sobhaheartland+burjkhalifa+meydanone",
       "note": "no surveyed footprint yet (completion Jun 2029); flat-terrain assumption; heights OSM-real where known else 12m default",
       "units": []}
print(f"\n{'unit':<12}{'floor':<6}{'claimed view':<30}{'skyline':<10}{'lagoon'}")
for u, (fl, claim) in UNITS.items():
    r = res.get(u, {})
    sky = "CLEAR" if r.get("SKYLINE_MID") else ("UPPER-ONLY" if r.get("SKYLINE_HI") else "BLOCKED")
    lag = "CLEAR" if r.get("LAGOON") else "BLOCKED"
    out["units"].append({"unit": u, "floor": fl, "claimed": claim, "skyline": sky, "lagoon": lag})
    print(f"{u:<12}{fl:<6}{claim:<30}{sky:<10}{lag}")
with open(os.path.join(PRO, "symphony_los.json"), "w") as f:
    json.dump(out, f, indent=1)
print("\nwritten: data/pro/symphony_los.json")
