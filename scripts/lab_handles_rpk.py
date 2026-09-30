"""LAB (handles, research only): compile the handle-annotated lab rules and package najma_v4_handles as an .rpk for PyPRT.

The one step here that needs CityEngine. It follows scripts/export_najma_rpk.py's lock protocol exactly: WAIT for
data/ce/.ce_lock (20 s polls, give up after an hour), write our own lock line, do the export, remove the lock only if
it is still ours. No scene is opened, created or saved - exportRPK and getRuleFileInfo work on the rule file alone.

  python scripts/lab_handles_rpk.py            compile both lab rules, export najma_v4_handles.rpk
  python scripts/lab_handles_rpk.py --check    compile only (getRuleFileInfo), no .rpk

Writes data/lab/handles/najma_v4_handles.rpk and data/lab/handles/rule_info.json (the attribute annotations CityEngine
reports back, so the @Handle lines are seen to have compiled, not assumed).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOCK = os.path.join(ROOT, "data", "ce", ".ce_lock")
OUT = os.path.join(ROOT, "data", "lab", "handles")
RULES = ["najma_v4_handles", "najma_v3_handles"]
TAG = "lab_handles_rpk pid %d" % os.getpid()


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
    take_lock()
    try:
        from cityengine import CE, RPKExportSettings  # bridge connects on first call
        ce = CE()
        try:
            ce.refreshWorkspace()   # the lab .cga files were written from outside CityEngine
        except Exception:
            pass
        for r in RULES:
            ws = "/najma/rules/lab/handles/%s.cga" % r
            try:
                info_all[r] = {"ok": True, "info": plain(ce.getRuleFileInfo(ws))}
            except Exception as e:
                info_all[r] = {"ok": False, "error": str(e)[:2000]}
        if not check_only and info_all["najma_v4_handles"]["ok"]:
            s = RPKExportSettings()
            s.setRuleFile("/najma/rules/lab/handles/najma_v4_handles.cga")
            s.setAddFilesAutomatically()
            s.setIncludeSourceFiles(True)
            s.setFile(os.path.join(OUT, "najma_v4_handles.rpk"))
            t = time.time()
            ce.exportRPK(s)
            took["najma_v4_handles"] = round(time.time() - t, 1)
    finally:
        release_lock()
    json.dump({"rules": info_all, "export_s": took, "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
              open(os.path.join(OUT, "rule_info.json"), "w", encoding="utf-8"), indent=1)
    for r, v in info_all.items():
        print("  %-18s %s" % (r, "compiled" if v["ok"] else "FAILED: " + v["error"][:400]))
    rpk = os.path.join(OUT, "najma_v4_handles.rpk")
    if not check_only:
        if not os.path.exists(rpk) or os.path.getsize(rpk) == 0:
            sys.exit("no .rpk written")
        print("  wrote %s  %.2f MB  in %s s" % (os.path.relpath(rpk, ROOT), os.path.getsize(rpk) / 1048576.0,
                                               took.get("najma_v4_handles")))
    return 0 if all(v["ok"] for v in info_all.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
