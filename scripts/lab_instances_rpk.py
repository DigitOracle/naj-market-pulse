"""LAB #4 (instancing): compile rules/lab/instances/lab_instances.cga into a rule package for PyPRT.

The one step that needs CityEngine. Same CE-lock protocol as scripts/export_najma_rpk.py, copied rather than imported
so this lab file cannot change that script's behaviour: WAIT for data/ce/.ce_lock (never steal it), write our own
holder line, release it in `finally`, and only if it is still ours. No scene is opened, changed or saved: refresh the
workspace so CityEngine sees the new .cga, export the package, done - seconds, not minutes.

Output goes to the lab folder, never to data/ce/_rpk:
  data/lab/instances/lab_instances.rpk

  python scripts/lab_instances_rpk.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOCK = os.path.join(ROOT, "data", "ce", ".ce_lock")
OUT = os.path.join(ROOT, "data", "lab", "instances")
RULE = "/najma/rules/lab/instances/lab_instances.cga"
TAG = "lab_instances_rpk pid %d" % os.getpid()


def take_lock(max_wait_s=1800):
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


def main():
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "lab_instances.rpk")
    take_lock()
    try:
        t = time.time()
        from cityengine import CE, RPKExportSettings  # bridge connects on import
        ce = CE()
        ce.refreshWorkspace()                  # the lab .cga is new on disk; CityEngine must see it before it can compile it
        s = RPKExportSettings()
        s.setRuleFile(RULE)
        s.setAddFilesAutomatically()           # every literal asset path in the rule -> into the package
        s.setIncludeSourceFiles(True)
        s.setFile(target)
        ce.exportRPK(s)
        took = time.time() - t
    finally:
        release_lock()
    if not os.path.exists(target) or os.path.getsize(target) == 0:
        sys.exit("export reported done but %s is missing or empty (compile error? see CityEngine's Problems view)" % target)
    print("wrote %s  %.2f MB  in %.1f s" % (os.path.relpath(target, ROOT), os.path.getsize(target) / 1048576.0, took))
    return 0


if __name__ == "__main__":
    sys.exit(main())
