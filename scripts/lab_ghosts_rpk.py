"""LAB (ghosts, research only): compile najma_ghost.cga into a PRT-loadable rule package for PyPRT.

The one step that needs CityEngine. It follows scripts/export_najma_rpk.py's lock protocol exactly: WAIT for
data/ce/.ce_lock (20 s polls, give up after an hour), write our own lock line, compile, remove the lock only if it is
still ours. The compile itself is CityEngine's HEADLESS CGA compiler (com.esri.cgac.application, the route
scripts/build_ev_rpk.py proved on 17 Sep): no GUI, no bridge, no scene is opened, created or saved. It runs in a
throw-away minimal project AND a throw-away Eclipse workspace (-data), so it cannot touch the Default Workspace the
running CityEngine holds. Packing follows build_ev_rpk.py: bytecode under bin/, source under rules/, 7z LZMA non-solid.

  python scripts/lab_ghosts_rpk.py          -> data/lab/ghosts/najma_ghost.rpk (+ rpk_info.json)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOCK = os.path.join(ROOT, "data", "ce", ".ce_lock")
OUT = os.path.join(ROOT, "data", "lab", "ghosts")
NAME = "najma_ghost"
CGA = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "CityEngine", "Default Workspace",
                   "najma", "rules", "lab", "ghosts", NAME + ".cga")
RPK = os.path.join(OUT, NAME + ".rpk")
CITYENGINE = os.environ.get("CITYENGINE_EXE", r"C:\Program Files\ArcGIS\CityEngine2025.1\CityEngine.exe")
SEVENZIP = os.environ.get("SEVENZIP_EXE", r"C:\Program Files\7-Zip\7z.exe")
TAG = "lab_ghosts_rpk pid %d" % os.getpid()
RESOLVEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<resolvemap>
  <entry key="/{name}/rules/{name}.cga" value="rules/{name}.cga" />
  <entry key="rules/{name}.cga" value="rules/{name}.cga" />
  <entry key="bin/{name}.cgb" value="bin/{name}.cgb" />
</resolvemap>
"""


def take_lock(max_wait_s=3600):
    t0 = time.time()
    while os.path.exists(LOCK):
        held = open(LOCK, encoding="utf-8", errors="ignore").read().strip()
        waited = time.time() - t0
        if waited > max_wait_s:
            sys.exit("gave up after %.0f s: CE lock still held by '%s'" % (waited, held))
        print("  CE lock held by '%s' - waiting (%.0f s so far)" % (held, waited), flush=True)
        time.sleep(20)
    with open(LOCK, "w", encoding="utf-8") as fh:
        fh.write("%s %s" % (TAG, time.strftime("%Y-%m-%dT%H:%M:%S")))


def release_lock():
    try:
        if open(LOCK, encoding="utf-8").read().startswith(TAG):
            os.remove(LOCK)
    except OSError:
        pass


def compile_cga(work):
    prj = os.path.join(work, "prj")
    os.makedirs(os.path.join(prj, "rules"))
    shutil.copy2(CGA, os.path.join(prj, "rules", NAME + ".cga"))
    outdir = os.path.join(work, "cgb"); os.makedirs(outdir)
    ws = os.path.join(work, "ws"); os.makedirs(ws)
    cmd = [CITYENGINE, "-application", "com.esri.cgac.application", "-nosplash", "-consoleLog", "-data", ws,
           "-prj", prj, "-out", outdir, os.path.join(prj, "rules", NAME + ".cga")]
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    body = (r.stdout or "") + (r.stderr or "")
    errs = [l for l in body.splitlines() if " - ERROR" in l]
    warns = [l for l in body.splitlines() if " - WARNING" in l]
    for l in warns:
        print("  warning  :", l.strip())
    if errs:
        for l in errs:
            print("  ERROR    :", l.strip())
        sys.exit("%d CGA error(s); rule package not built." % len(errs))
    cgb = None
    for rt, _d, files in os.walk(outdir):
        for f in files:
            if f.endswith(".cgb"):
                cgb = os.path.join(rt, f)
    if not cgb:
        print(body[-2000:])
        sys.exit("compiler produced no .cgb")
    print("compiled   : %s (%d bytes) in %.1f s" % (os.path.basename(cgb), os.path.getsize(cgb), time.time() - t))
    return cgb, warns


def pack(work, cgb):
    stage = os.path.join(work, "stage")
    os.makedirs(os.path.join(stage, "rules")); os.makedirs(os.path.join(stage, "bin"))
    shutil.copy2(CGA, os.path.join(stage, "rules", NAME + ".cga"))
    shutil.copy2(cgb, os.path.join(stage, "bin", NAME + ".cgb"))
    open(os.path.join(stage, ".resolvemap.xml"), "w", encoding="utf-8").write(RESOLVEMAP.format(name=NAME))
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(RPK):
        os.remove(RPK)
    r = subprocess.run([SEVENZIP, "a", "-t7z", RPK, "-m0=lzma", "-md=4m", "-ms=off", ".resolvemap.xml", "rules", "bin"],
                       cwd=stage, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout[-800:]); sys.exit("7z failed (%d)" % r.returncode)
    print("packed     : %s (%d bytes)" % (os.path.relpath(RPK, ROOT), os.path.getsize(RPK)))


def main():
    for p, what in ((CITYENGINE, "CityEngine"), (SEVENZIP, "7-Zip"), (CGA, "najma_ghost.cga")):
        if not os.path.exists(p):
            sys.exit("%s not found: %s" % (what, p))
    work = tempfile.mkdtemp(prefix="ghost_rpk_")
    take_lock()
    try:
        cgb, warns = compile_cga(work)
    finally:
        release_lock()                      # the lock covers the CityEngine call only; packing needs no CityEngine
    try:
        pack(work, cgb)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    import pyprt
    info = pyprt.get_rpk_attributes_info(RPK)
    if not info:
        sys.exit("verify FAILED: PRT read no attributes from %s" % RPK)
    print("verify     : PRT loaded it, attributes %s" % sorted(info))
    json.dump({"rpk": os.path.relpath(RPK, ROOT), "rule": CGA, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "attributes": sorted(info), "warnings": warns, "compiler": "com.esri.cgac.application (headless)"},
              open(os.path.join(OUT, "rpk_info.json"), "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
