"""Export the Dubai Marina CityEngine scene to Datasmith for the Unreal 5.8 hero clip.

Reads   : /najma/scenes/dubaimarina.cej (already built by ce_batch.py; opened, never saved)
Writes  : data/ce/_datasmith/dubaimarina.udatasmith  (+ dubaimarina_Assets/ + export log)
          data/ce/_datasmith/dubaimarina_georef.json  (the global offset that re-centres UTM)
Requires: CityEngine 2025.1 running with the external Python bridge on 25333
          (pip package `cityengine`; z = -northing in the CE frame).

Exporter: the cityengine module has no class named *Datasmith*; the Datasmith writer is
`UnrealExportModelSettings` (docstring: "Encodes geometry into the Datasmith (5.1.0) format").
If that class is absent the script falls back to FBX and says so loudly.

LOCK PROTOCOL: data/ce/.ce_lock is created before the first CE call and removed on exit.
If it already exists we wait (poll 20 s, up to 20 min) - one CE driver at a time.

Usage:  python scripts/ce_export_datasmith.py [--area dubaimarina] [--offset auto|none|X,Y,Z]
"""
import json, os, socket, sys, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
LOCK = os.path.join(CEDIR, ".ce_lock")
OUT = os.path.join(CEDIR, "_datasmith")

AREA = sys.argv[sys.argv.index("--area") + 1] if "--area" in sys.argv else "dubaimarina"
OFFSET_MODE = sys.argv[sys.argv.index("--offset") + 1] if "--offset" in sys.argv else "auto"
SCENE = f"/najma/scenes/{AREA}.cej"
LOCK_POLL_S, LOCK_MAX_S = 20, 20 * 60
ME = f"ce_export_datasmith.py area={AREA} host={socket.gethostname()} pid={os.getpid()}"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- lock ----
def acquire_lock():
    waited = 0
    while os.path.exists(LOCK):
        holder = ""
        try:
            holder = open(LOCK, encoding="utf-8").read().strip()
        except OSError:
            pass
        if waited >= LOCK_MAX_S:
            sys.exit(f"lock held for {LOCK_MAX_S // 60} min by [{holder}] - giving up, nothing touched")
        log(f"lock held by [{holder}] - waiting ({waited // 60} min elapsed)")
        time.sleep(LOCK_POLL_S)
        waited += LOCK_POLL_S
    os.makedirs(CEDIR, exist_ok=True)
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(ME + " " + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    log("lock taken:", LOCK)


def release_lock():
    try:
        if os.path.exists(LOCK) and ME in open(LOCK, encoding="utf-8").read():
            os.remove(LOCK)
            log("lock released")
    except OSError as e:
        log("lock release failed:", e)


def watchdog(label, seconds=90):
    """Warn if a CE call blocks - usually a modal dialog inside CityEngine waiting for a click."""
    ev = threading.Event()

    def _w():
        if not ev.wait(seconds):
            log(f"WARNING: '{label}' has blocked for {seconds}s - check the CityEngine window for a dialog")
    threading.Thread(target=_w, daemon=True).start()
    return ev


# ------------------------------------------------------------- exporter ----
def pick_exporter(mod):
    names = [n for n in dir(mod) if "atasmith" in n and "ExportModelSettings" in n]
    if names:
        return getattr(mod, names[0]), names[0], "datasmith"
    if hasattr(mod, "UnrealExportModelSettings"):
        return mod.UnrealExportModelSettings, "UnrealExportModelSettings", "datasmith"
    if hasattr(mod, "FBXExportModelSettings"):
        return mod.FBXExportModelSettings, "FBXExportModelSettings", "fbx"
    return None, None, None


def shape_bounds(ce, shapes):
    xs, ys, zs = [], [], []
    for s in shapes:
        try:
            p = ce.getPosition(s)
            xs.append(float(p[0])); ys.append(float(p[1])); zs.append(float(p[2]))
        except Exception:
            continue
    if not xs:
        return None
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def wait_for_callback_port(port=25334, budget_s=LOCK_MAX_S):
    """`import cityengine` opens a py4j gateway whose callback server binds 127.0.0.1:25334.
    A sibling driver that has just released the lock may still hold that port for a moment
    (or a crashed one may hold it for good) - wait, don't crash."""
    waited = 0
    while True:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return
        except OSError:
            s.close()
            if waited >= budget_s:
                sys.exit(f"py4j callback port {port} still held after {budget_s // 60} min - another CE client is alive")
            log(f"py4j callback port {port} busy (another CE client) - waiting")
            time.sleep(LOCK_POLL_S)
            waited += LOCK_POLL_S


def main():
    os.makedirs(OUT, exist_ok=True)
    acquire_lock()                       # lock FIRST: importing cityengine already opens the bridge
    result = {"area": AREA, "scene": SCENE, "ok": False}
    try:
        wait_for_callback_port()
        try:
            import cityengine
            from cityengine import CE
        except ImportError as e:
            sys.exit(f"cityengine module not importable ({e}) - is the CE 2025.1 python bridge installed?")

        Settings, sname, kind = pick_exporter(cityengine)
        if not Settings:
            sys.exit("neither a Datasmith/Unreal nor an FBX exporter exists in this cityengine module")
        if kind == "fbx":
            log("NOTE: Datasmith exporter NOT available in this cityengine build - falling back to FBX")
        log(f"exporter: {sname} ({kind}) - {(Settings.__doc__ or '').strip().splitlines()[0]}")
        result.update(exporter=sname, kind=kind)

        ce = CE()
        log("connected to CityEngine; workspace:", ce.toFSPath("/"))
        scene_fs = ce.toFSPath(SCENE)
        if not os.path.exists(scene_fs):
            sys.exit(f"scene missing on disk: {scene_fs} - run ce_batch.py first")

        ev = watchdog(f"openFile {SCENE}")
        ce.openFile(SCENE)                     # the ONLY scene this script opens; it is never saved
        ev.set()
        log("opened", SCENE)

        shapes = ce.getObjectsFrom(ce.scene, ce.isShape)
        log("shapes in scene:", len(shapes))
        if not shapes:
            sys.exit("scene has no shapes - nothing to export")

        # --- re-centre: UTM easting/northing puts the district ~2,800 km from Unreal's origin,
        #     far outside float32 comfort. Global offset is ADDED to every vertex on export.
        offset = [0.0, 0.0, 0.0]
        bounds = None
        if OFFSET_MODE == "auto":
            bounds = shape_bounds(ce, shapes)
            if bounds:
                (x0, y0, z0), (x1, y1, z1) = bounds
                offset = [-round((x0 + x1) / 2), -round(y0), -round((z0 + z1) / 2)]
                log(f"shape bounds x[{x0:.0f},{x1:.0f}] y[{y0:.0f},{y1:.0f}] z[{z0:.0f},{z1:.0f}] -> offset {offset}")
            else:
                log("could not read shape positions - exporting without offset")
        elif OFFSET_MODE != "none":
            offset = [float(v) for v in OFFSET_MODE.split(",")]

        s = Settings()
        s.setOutputPath(OUT)
        s.setBaseName(AREA)
        applied = {}
        if kind == "datasmith":
            wanted = {
                "setExportGeometry": s.MODEL_GEOMETRY_FALLBACK,   # models; start shape if a rule fails
                "setMeshMerging": s.PERINITIALSHAPE,               # one static mesh per building
                "setInstancing": s.DISABLED,                       # required for per-building metadata
                "setMetadata": s.ALL,                              # bHeight / status / name -> Datasmith metadata
                "setUseUnrealBaseMaterials": True,                 # PBR parent materials in UE
                "setTerrainLayers": s.TERRAIN_NONE,                # no terrain in this scene
                "setWriteLog": True,
                "setGlobalOffset": offset,
            }
        else:
            wanted = {"setGlobalOffset": offset}
        for m, v in wanted.items():
            try:
                getattr(s, m)(v)
                applied[m] = v if not hasattr(v, "__iter__") or isinstance(v, str) else list(v)
            except Exception as e:
                log(f"  setting {m} not applied: {str(e).splitlines()[0][:100]}")
        log("settings applied:", applied)

        t0 = time.time()
        ev = watchdog("export", 600)
        ce.export(shapes, s)
        ev.set()
        dt = time.time() - t0
        log(f"export call returned in {dt:.1f}s")
        try:
            elog = s.getExportLog()
            log("export log:", dict(elog) if elog else elog)
        except Exception:
            pass

        time.sleep(1)
        files = []
        for root, _, fns in os.walk(OUT):
            for fn in fns:
                p = os.path.join(root, fn)
                files.append((os.path.relpath(p, OUT), os.path.getsize(p)))
        main_ext = ".udatasmith" if kind == "datasmith" else ".fbx"
        mains = [f for f in files if f[0].lower().endswith(main_ext)]
        for rel, sz in sorted(files):
            if not rel.startswith(f"{AREA}_Assets"):
                log(f"  {rel}  {sz:,} B")
        n_assets = sum(1 for f in files if f[0].startswith(f"{AREA}_Assets"))
        log(f"  {AREA}_Assets/: {n_assets} files")
        result.update(ok=bool(mains), files=len(files), main=[m[0] for m in mains],
                      offset_ce_xyz=offset, note="CE frame: x=easting, y=up, z=-northing (metres); "
                      "offset was ADDED to vertices, so UTM = exported - offset",
                      utm_zone="EPSG:32640 (WGS84 / UTM 40N) - Dubai", shape_count=len(shapes),
                      seconds=round(dt, 1), scene_bounds=bounds)
        with open(os.path.join(OUT, f"{AREA}_georef.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        log("georef sidecar:", os.path.join(OUT, f"{AREA}_georef.json"))
        if not mains:
            log(f"WARNING: no {main_ext} written - see export log above")
    finally:
        release_lock()          # scene is left open in CE, NOT saved, no other scene touched
    log("done" if result["ok"] else "finished with problems")


if __name__ == "__main__":
    main()
