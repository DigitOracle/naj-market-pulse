"""Package a Najma CGA rule as a Rule Package (.rpk) so it can run WITHOUT CityEngine, through PyPRT.

The massing pipeline drives the CityEngine GUI over a py4j bridge, and on 27 Sep that bridge stopped
listening at 11:29 with CityEngine itself still up - every generate after it died on connect, and only a
person restarting CityEngine brought it back. PyPRT runs the same CGA headlessly from a compiled rule
package: no bridge, no GUI, no lock. This is the one step that still needs CityEngine - compiling the rule -
and it is a single short call.

It takes the CE lock like every other script here, and WAITS for it rather than stealing it: a build
that is mid-generate must not have the scene changed under it.

  python scripts/export_najma_rpk.py                 najma_v4.cga -> data/ce/_rpk/najma_v4.rpk
  python scripts/export_najma_rpk.py --rule najma_v3
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
LOCK = os.path.join(CEDIR, ".ce_lock")
OUT = os.path.join(CEDIR, "_rpk")


def opt(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


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
        fh.write("export_najma_rpk pid %d %s" % (os.getpid(), time.strftime("%Y-%m-%dT%H:%M:%S")))


def release_lock():
    try:
        if open(LOCK, encoding="utf-8").read().startswith("export_najma_rpk pid %d" % os.getpid()):
            os.remove(LOCK)
    except OSError:
        pass


def main():
    rule = opt("--rule", "najma_v4")
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "%s.rpk" % rule)
    take_lock()
    try:
        from cityengine import CE, RPKExportSettings  # bridge connects on first call
        ce = CE()
        s = RPKExportSettings()
        s.setRuleFile("/najma/rules/%s.cga" % rule)
        s.setAddFilesAutomatically()        # pull in every asset and import the rule references
        s.setIncludeSourceFiles(True)       # keep the .cga in the package so it can be read back
        s.setFile(target)
        t = time.time()
        ce.exportRPK(s)
        took = time.time() - t
    finally:
        release_lock()
    if not os.path.exists(target) or os.path.getsize(target) == 0:
        sys.exit("export reported done but %s is missing or empty" % target)
    print("wrote %s  %.1f MB  in %.1f s" % (os.path.relpath(target, ROOT), os.path.getsize(target) / 1048576.0, took))
    return 0


if __name__ == "__main__":
    sys.exit(main())
