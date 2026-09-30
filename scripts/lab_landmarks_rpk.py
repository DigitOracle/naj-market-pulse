"""LAB (landmarks, research only): compile the landmark rules and package them as .rpk files for PyPRT.

The one step that needs CityEngine. It follows scripts/export_najma_rpk.py's lock protocol exactly: WAIT for
data/ce/.ce_lock (20 s polls, give up after an hour), write our own lock line, do the work, remove the lock only if
it is still ours. No scene is opened, created or saved - refreshFolder, getRuleFileInfo and exportRPK work on rule
files alone.

  python scripts/lab_landmarks_rpk.py            compile every lab rule, export both packages
  python scripts/lab_landmarks_rpk.py --check    compile only (getRuleFileInfo), no .rpk
  --max-wait <s>                                  how long to wait for the lock (default 3600)

Writes data/lab/landmarks/najma_v4_landmarks.rpk (najma_v4 + the landmark hook - what the before/after builds use),
data/lab/landmarks/landmarks.rpk (the families on their own) and data/lab/landmarks/rule_info.json.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOCK = os.path.join(ROOT, "data", "ce", ".ce_lock")
OUT = os.path.join(ROOT, "data", "lab", "landmarks")
WSDIR = "/najma/rules/lab/landmarks/"
RULES = ["lm_common", "gen_Facade_spiral_setback", "gen_Facade_twist", "gen_Facade_void_cube",
         "lm_spiral_setback", "lm_twist", "lm_void_cube", "landmarks", "najma_v4_landmarks"]
PACKAGES = ["najma_v4_landmarks", "landmarks"]
TAG = "lab_landmarks_rpk pid %d" % os.getpid()


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


def plain(o):
    """py4j proxies -> JSON-able."""
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    try:
        return plain(dict(o))
    except Exception:
        pass
    try:
        return plain(list(o))
    except Exception:
        return str(o)


def main():
    check_only = "--check" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    info_all, took = {}, {}
    take_lock(float(sys.argv[sys.argv.index("--max-wait") + 1]) if "--max-wait" in sys.argv else 3600)
    try:
        from cityengine import CE, RPKExportSettings  # bridge connects on first call
        ce = CE()
        try:
            ce.refreshFolder(WSDIR)                    # the lab files were written from outside CityEngine
            ce.refreshFolder("/najma/assets/lab/landmarks/")
        except Exception:
            try:
                ce.refreshWorkspace()
            except Exception:
                pass
        for r in RULES:
            try:
                info_all[r] = {"ok": True, "info": plain(ce.getRuleFileInfo(WSDIR + r + ".cga"))}
            except Exception as e:
                info_all[r] = {"ok": False, "error": str(e)[:3000]}
        if not check_only:
            for pkg in PACKAGES:
                if not info_all[pkg]["ok"]:
                    continue
                target = os.path.join(OUT, "%s.rpk" % pkg)
                if os.path.exists(target):
                    os.remove(target)
                s = RPKExportSettings()
                s.setRuleFile(WSDIR + pkg + ".cga")
                s.setAddFilesAutomatically()
                s.setIncludeSourceFiles(True)
                s.setFile(target)
                t = time.time()
                try:
                    ce.exportRPK(s)
                    took[pkg] = round(time.time() - t, 1)
                except Exception as e:
                    took[pkg] = "FAILED: %s" % str(e)[:2000]
    finally:
        release_lock()
    json.dump({"rules": info_all, "export_s": took, "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
              open(os.path.join(OUT, "rule_info.json"), "w", encoding="utf-8"), indent=1)
    for r, v in info_all.items():
        print("  %-28s %s" % (r, "compiled" if v["ok"] else "FAILED: " + v["error"][:600]))
    for pkg in PACKAGES:
        p = os.path.join(OUT, "%s.rpk" % pkg)
        ok = os.path.exists(p) and os.path.getsize(p) > 0
        print("  %-28s %s" % (pkg + ".rpk", ("%.2f MB in %s s" % (os.path.getsize(p) / 1048576.0, took.get(pkg))) if ok
                                          else "NOT WRITTEN %s" % took.get(pkg, "")))
    return 0 if all(v["ok"] for v in info_all.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
