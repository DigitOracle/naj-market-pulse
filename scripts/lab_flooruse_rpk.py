"""LAB (floor-use technique #2): compile najma/rules/lab/flooruse/flooruse.cga into a rule package for PyPRT.

The only step that needs CityEngine. Same CE-lock protocol as scripts/export_najma_rpk.py, copied rather than imported
so this lab file never changes that one: wait for the lock (never steal it), write it with our pid, release it in
`finally`. No scene is opened, changed or saved - exportRPK only compiles the rule and zips it with its assets
(the space-use CSV is pulled in by setAddFilesAutomatically because the rule reads it).

  python scripts/lab_flooruse_rpk.py            -> data/lab/flooruse/flooruse.rpk
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOCK = os.path.join(ROOT, "data", "ce", ".ce_lock")
OUT = os.path.join(ROOT, "data", "lab", "flooruse")
RULE = "/najma/rules/lab/flooruse/flooruse.cga"
TAG = "lab_flooruse_rpk pid %d" % os.getpid()


def callback_port_busy(port=25334):
    """The cityengine bridge starts a py4j callback server on 127.0.0.1:25334 at import. A client that has released the CE
    lock but is still running keeps that port, and every other client then dies at import (30 Sep: WinError 10048). So wait
    for the port as well as the lock - never take the lock only to fail on it."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def take_lock(max_wait_s=3600):
    t0 = time.time()
    while os.path.exists(LOCK) or callback_port_busy():
        held = open(LOCK, encoding="utf-8", errors="ignore").read().strip() if os.path.exists(LOCK) else "nobody (py4j callback port 25334 in use)"
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
    target = os.path.join(OUT, "flooruse.rpk")
    take_lock()
    try:
        from cityengine import CE, RPKExportSettings
        ce = CE()
        ce.refreshWorkspace()                 # the lab rule is a new file; CE must index it before it can compile it
        s = RPKExportSettings()
        s.setRuleFile(RULE)
        s.setAddFilesAutomatically()
        s.setIncludeSourceFiles(True)
        s.setFile(target)
        t = time.time()
        ce.exportRPK(s)
        took = time.time() - t
    finally:
        release_lock()
    if not os.path.exists(target) or os.path.getsize(target) == 0:
        sys.exit("export reported done but %s is missing or empty" % target)
    print("wrote %s  %.1f KB  in %.1f s" % (os.path.relpath(target, ROOT), os.path.getsize(target) / 1024.0, took))
    try:                                      # an .rpk is a 7z archive, not a zip
        import py7zr
        names = [n for n in py7zr.SevenZipFile(target).getnames() if "." in os.path.basename(n)]
        print("  contents:", names)
        if not any(n.endswith("flooruse_space_types.csv") for n in names):
            sys.exit("the space-use table is not in the package - the rule would fall back to its defaults")
    except ImportError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
