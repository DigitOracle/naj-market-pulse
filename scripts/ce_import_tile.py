"""Import ONE (or more) named district tiles into CityEngine as scenes, and nothing else.

ce_batch.py imports every folder that has a buildings.shp and skips only those with a legacy sky_<slug>_0.glb - which today's
v2/v3 districts do not have - so running it to add one tile would re-import the whole city. This does the single step that
is actually needed for a new tile: stage the shapefile into the workspace, make /najma/scenes/<tile>.cej, import, save.
ce_batch_v2.py --v3 then masses it from that scene.

Lock protocol as everywhere: take data/ce/.ce_lock before the first bridge call, poll 20 s up to 30 min if held, release in
`finally`, and NEVER call gateway.shutdown() - that kills the bridge for everyone.

Usage: python scripts/ce_import_tile.py jltnorth jltsouth
"""
import os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce"); LOCK = os.path.join(CEDIR, ".ce_lock")

tiles = [a for a in sys.argv[1:] if not a.startswith("--")]
if not tiles: sys.exit("usage: ce_import_tile.py <tile> [<tile> ...]")
for t in tiles:
    if not os.path.exists(os.path.join(CEDIR, t, "buildings.shp")): sys.exit(f"{t}: no buildings.shp - run split_district.py first")

waited = 0
while os.path.exists(LOCK):
    if waited == 0: print("CityEngine is held by", open(LOCK).read().strip()[:60], "- waiting")
    time.sleep(20); waited += 20
    if waited > 1800: sys.exit("gave up waiting for the CityEngine lock")
open(LOCK, "w").write("ce_import_tile.py " + time.strftime("%Y-%m-%d %H:%M"))
try:
    from cityengine import CE  # noqa: E402  (import AFTER taking the lock)
    ce = CE(); ws = ce.toFSPath("/"); proj = os.path.join(ws, "najma")
    os.makedirs(os.path.join(proj, "data"), exist_ok=True); os.makedirs(os.path.join(proj, "scenes"), exist_ok=True)
    for t in tiles:
        for f in os.listdir(os.path.join(CEDIR, t)):
            if f.startswith("buildings.") and not f.endswith(".geojson"):
                shutil.copy2(os.path.join(CEDIR, t, f), os.path.join(proj, "data", f"{t}_{f}"))
        try: ce.refreshWorkspace()
        except Exception: pass
        ce.newFile(f"/najma/scenes/{t}.cej")
        ce.importFile(ce.toFSPath(f"/najma/data/{t}_buildings.shp"))
        shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
        ce.saveFile(f"/najma/scenes/{t}.cej")
        print(f"  {t}: scene saved with {len(shapes)} shapes", flush=True)
finally:
    try: os.remove(LOCK)
    except Exception: pass
print("done - now: python scripts/ce_batch_v2.py --v3", " ".join(tiles))
